#!/usr/bin/env python3
"""Bounded anonymous-memory and CPU pressure for the owned ID36 qualification."""

import argparse
import mmap
import multiprocessing
import os
from pathlib import Path
import signal
import sys
import time


PAGE_BYTES = 4096
MIB = 1024 * 1024


def cpu_burn(stop_event):
    # Preserve CPU contention without starving dmsetup/io-replay control paths.
    os.nice(10)
    value = (os.getpid() << 1) | 1
    while not stop_event.is_set():
        # Fixed integer-only work avoids optional dependencies and allocations.
        for _ in range(20000):
            value = ((value * 2862933555777941757) + 3037000493) & ((1 << 64) - 1)
            value ^= value >> 17


def join_started_workers(workers, seconds):
    """Join only started children against one shared deadline, not per PID."""
    deadline = time.monotonic() + seconds
    for worker in workers:
        worker.join(timeout=max(0.0, deadline - time.monotonic()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-mib", type=int, required=True)
    parser.add_argument("--ready-memory-mib", type=int)
    parser.add_argument("--cpu-workers", type=int, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--activate-file", type=Path)
    parser.add_argument("--active-file", type=Path)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()

    if not 64 <= args.memory_mib <= 768:
        print("FAIL: ID36 memory pressure must be 64..768 MiB", file=sys.stderr)
        return 2
    ready_memory_mib = (
        args.memory_mib if args.ready_memory_mib is None
        else args.ready_memory_mib
    )
    if not 64 <= ready_memory_mib <= args.memory_mib:
        print("FAIL: ID36 ready memory must be 64..final memory MiB",
              file=sys.stderr)
        return 2
    staged = ready_memory_mib < args.memory_mib
    if staged and (args.activate_file is None or args.active_file is None):
        print("FAIL: ID36 staged pressure requires activate/active files",
              file=sys.stderr)
        return 2
    if not 1 <= args.cpu_workers <= 32:
        print("FAIL: ID36 CPU worker count must be 1..32", file=sys.stderr)
        return 2

    stopping = False

    def request_stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    # Fork CPU burners before the large resident mapping exists. Otherwise each
    # burner inherits the faulted mapping's COW page tables and consumes memory
    # that was intended as benchmark working headroom.
    context = multiprocessing.get_context("fork")
    stop_event = context.Event()
    workers = [
        context.Process(target=cpu_burn, args=(stop_event,), daemon=True)
        for _ in range(args.cpu_workers)
    ]
    started_workers = []
    pressure = None
    try:
        # A failed later fork must not orphan already-running CPU burners.
        # Join only Processes that started successfully.
        try:
            for worker in workers:
                worker.start()
                started_workers.append(worker)
        except (OSError, RuntimeError, AssertionError):
            print("FAIL: ID36 CPU pressure worker startup failed; stop started workers",
                  file=sys.stderr)
            return 1

        try:
            # Keep the unfaulted tail genuinely uncharged so the controller can
            # install memory.high between the ready baseline and the final
            # working set. bytearray(size) may eagerly zero pages and therefore
            # cannot provide this two-stage residency boundary reliably.
            pressure = mmap.mmap(
                -1, args.memory_mib * MIB,
                flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
            )
        except (BufferError, OSError, ValueError):
            print("FAIL: ID36 pressure mapping failed", file=sys.stderr)
            return 1

        ready_bytes = ready_memory_mib * MIB
        for offset in range(0, ready_bytes, PAGE_BYTES):
            pressure[offset] = (offset // PAGE_BYTES) & 0xFF

        if any(not worker.is_alive() for worker in workers):
            print("FAIL: ID36 CPU pressure worker exited before readiness",
                  file=sys.stderr)
            return 1

        try:
            args.ready_file.write_text(
                f"memory_mib={args.memory_mib} "
                f"ready_memory_mib={ready_memory_mib} "
                f"cpu_workers={args.cpu_workers}\n",
                encoding="ascii",
            )
        except OSError:
            print("FAIL: ID36 pressure readiness record cannot be written",
                  file=sys.stderr)
            return 1

        if staged:
            while (not stopping and not args.stop_file.exists() and
                   not args.activate_file.exists()):
                if any(not worker.is_alive() for worker in workers):
                    print("FAIL: ID36 CPU pressure worker exited before activation",
                          file=sys.stderr)
                    return 1
                time.sleep(0.01)
            if stopping or args.stop_file.exists():
                return 0

            # The controller has installed memory.high at the ready-state charge.
            # Fault the remaining bounded tail now so crossing the high watermark
            # is deliberate and independent of benchmark allocation behavior.
            for offset in range(ready_bytes, len(pressure), PAGE_BYTES):
                pressure[offset] = (offset // PAGE_BYTES) & 0xFF

            try:
                args.active_file.write_text(
                    f"memory_mib={args.memory_mib} "
                    f"ready_memory_mib={ready_memory_mib}\n",
                    encoding="ascii",
                )
            except OSError:
                print("FAIL: ID36 staged pressure activation record cannot be written",
                      file=sys.stderr)
                return 1

        sweep = 0
        while not stopping and not args.stop_file.exists():
            if any(not worker.is_alive() for worker in workers):
                print("FAIL: ID36 CPU pressure worker exited early", file=sys.stderr)
                return 1
            # Re-reference a sparse subset so reclaim pressure stays active
            # without turning the memory worker into the dominant CPU load.
            start = (sweep % 16) * PAGE_BYTES
            for offset in range(start, len(pressure), 16 * PAGE_BYTES):
                pressure[offset] ^= 1
            sweep += 1
            time.sleep(0.05)
    finally:
        stop_event.set()
        join_started_workers(started_workers, 2.0)
        for worker in started_workers:
            if worker.is_alive():
                worker.terminate()
        join_started_workers(started_workers, 2.0)
        for worker in started_workers:
            if worker.is_alive():
                worker.kill()
        join_started_workers(started_workers, 2.0)
        if pressure is not None:
            pressure.close()
        if any(worker.is_alive() for worker in started_workers):
            print("FAIL: ID36 CPU pressure child could not be reaped after "
                  "bounded TERM/KILL cleanup", file=sys.stderr)
            raise SystemExit(1)

    return 0


# Opt-in preparation API only; the legacy pressure CLI never calls it.
# Both mappings together are bounded by the existing 768 MiB pressure ceiling.
MAX_MATCHED_PAGES = 768 * MIB // (2 * PAGE_BYTES)


class ColdWorkloadError(RuntimeError):
    """Bounded diagnostic; never include backing names, fd IDs or page bytes."""


def _require_private_tmpfs(fd):
    import fcntl
    import stat

    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
            stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 0 or
            info.st_size != 0 or
            fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR):
        raise ColdWorkloadError("backing must be an empty private unlinked read-write file")
    # st_dev alone is insufficient: distinct mounts may share a superblock.
    # Resolve the duplicate's exact mount ID, not a path or guessed mount.
    identities = [line.split(b":", 1)[1].strip()
                  for line in Path(f"/proc/self/fdinfo/{fd}").read_bytes().splitlines()
                  if line.startswith(b"mnt_id:")]
    if len(identities) != 1 or not identities[0].isdigit():
        raise ColdWorkloadError("backing mount identity unavailable")
    matches = [line for line in Path("/proc/self/mountinfo").read_bytes().splitlines()
               if line.split(b" ", 1)[0] == identities[0]]
    if len(matches) != 1:
        raise ColdWorkloadError("backing mount identity unavailable or ambiguous")
    left, separator, right = matches[0].partition(b" - ")
    fields = left.split()
    filesystem = right.split()
    device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}".encode("ascii")
    if (not separator or len(fields) < 6 or len(filesystem) < 3 or
            fields[2] != device or filesystem[0] != b"tmpfs"):
        raise ColdWorkloadError("backing is not a verified tmpfs mount")


def _cold_page(seed, index):
    import hashlib
    import struct

    # Stable, nonuniform and compressible: distinct page-specific 512-byte
    # patterns, not a claim about a representative production corpus.
    pattern = b"\x00\x01" + hashlib.shake_256(struct.pack("<QQ", seed, index)).digest(510)
    return pattern * (PAGE_BYTES // len(pattern))


class MatchedColdWorkload:
    """Exclusive context-owned mappings; no concurrent callers or exported views."""

    backing_kind = "file-backed-tmpfs"

    def __init__(self, anonymous, shmem, page_count, hot_page_count, seed):
        self._anonymous = anonymous
        self._shmem = shmem
        self._page_count = page_count
        self._hot_page_count = hot_page_count
        self._seed = seed
        self._touch_count = 0
        self._usable = True

    @property
    def hot_pages(self):
        return range(self._hot_page_count)

    @property
    def cold_pages(self):
        return range(self._hot_page_count, self._page_count)

    @property
    def logical_bytes_per_mapping(self):
        return self._page_count * PAGE_BYTES

    def _require_usable(self):
        if not self._usable:
            raise ColdWorkloadError("workload closed or invalidated")

    def touch_hot(self):
        """One caller-controlled pass; no timer, worker or cold page access."""
        self._require_usable()
        try:
            for index in self.hot_pages:
                offset = index * PAGE_BYTES
                self._anonymous[offset] ^= 1
                self._shmem[offset] ^= 1
        except BaseException:
            self._usable = False
            raise
        self._touch_count += 1

    def verify(self):
        """Full byte check against independent regeneration, OUTSIDE timing.

        Reads cold pages: call only after the intended cold observation ends.
        """
        self._require_usable()
        for index in range(self._page_count):
            expected = _cold_page(self._seed, index)
            if index < self._hot_page_count and self._touch_count % 2:
                expected = b"\x01" + expected[1:]
            offset = index * PAGE_BYTES
            end = offset + PAGE_BYTES
            if (self._anonymous[offset:end] != expected or
                    self._shmem[offset:end] != expected):
                self._usable = False
                raise ColdWorkloadError("matched workload full-page verification failed")


def prepare_matched_cold_workload(*, page_count, hot_page_count, seed, tmpfs_fd):
    """Return a context manager for two matched 4096-byte page cohorts.

    Caller supplies and retains exclusive ownership of an empty, mode-0600,
    unlinked tmpfs temporary file opened read-write (e.g. TemporaryFile).
    Caller must not close, truncate, map or access it until context exit.
    The context owns a duplicate fd and both mappings; it restores file size
    to zero on exit. No memfd substitution or mount/reclaim operations.
    """
    from contextlib import contextmanager

    if (type(page_count) is not int or not 2 <= page_count <= MAX_MATCHED_PAGES or
            type(hot_page_count) is not int or not 1 <= hot_page_count < page_count or
            type(seed) is not int or not 0 <= seed < 2**64 or
            type(tmpfs_fd) is not int or tmpfs_fd < 0):
        raise ColdWorkloadError("invalid matched workload bounds")
    if os.sysconf("SC_PAGE_SIZE") != PAGE_BYTES:
        raise ColdWorkloadError("matched workload requires 4096-byte host pages")

    @contextmanager
    def owned_mappings():
        duplicate = anonymous = shmem = workload = None
        resize_attempted = False
        first_error = None
        phase = "duplicate backing"
        try:
            try:
                duplicate = os.dup(tmpfs_fd)
                phase = "verify backing"
                _require_private_tmpfs(duplicate)
                length = page_count * PAGE_BYTES
                phase = "reserve backing"
                resize_attempted = True
                # Reserve tmpfs space before touching mapped bytes, avoiding
                # a foreseeable SIGBUS from tmpfs capacity exhaustion.
                os.posix_fallocate(duplicate, 0, length)
                if os.fstat(duplicate).st_size != length:
                    raise ColdWorkloadError("unexpected reserved backing size")
                phase = "map anonymous"
                anonymous = mmap.mmap(-1, length, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
                                      prot=mmap.PROT_READ | mmap.PROT_WRITE)
                phase = "map tmpfs"
                shmem = mmap.mmap(duplicate, length, flags=mmap.MAP_SHARED,
                                  prot=mmap.PROT_READ | mmap.PROT_WRITE)
                phase = "populate mappings"
                for index in range(page_count):
                    page = _cold_page(seed, index)
                    offset = index * PAGE_BYTES
                    anonymous[offset:offset + PAGE_BYTES] = page
                    shmem[offset:offset + PAGE_BYTES] = page
                workload = MatchedColdWorkload(anonymous, shmem, page_count, hot_page_count, seed)
            except (OSError, ValueError, BufferError, MemoryError):
                raise ColdWorkloadError(f"matched workload preparation failed: {phase}") from None
            yield workload
        except BaseException as error:
            first_error = error
            raise
        finally:
            if workload is not None:
                workload._usable = False
            cleanup_errors = []
            shmem_closed = True
            for name, mapping in (("tmpfs mapping", shmem), ("anonymous mapping", anonymous)):
                if mapping is not None:
                    try:
                        mapping.close()
                    except (OSError, BufferError, ValueError):
                        cleanup_errors.append(name)
                        if mapping is shmem:
                            shmem_closed = False
            if duplicate is not None:
                if resize_attempted and shmem_closed:
                    try:
                        os.ftruncate(duplicate, 0)
                    except OSError:
                        cleanup_errors.append("backing reset")
                try:
                    os.close(duplicate)
                except OSError:
                    cleanup_errors.append("backing duplicate close")
            if cleanup_errors:
                message = "matched workload cleanup failed: " + ", ".join(cleanup_errors)
                if first_error is None:
                    raise ColdWorkloadError(message)
                first_error.add_note(message)

    return owned_mappings()


if __name__ == "__main__":
    raise SystemExit(main())
