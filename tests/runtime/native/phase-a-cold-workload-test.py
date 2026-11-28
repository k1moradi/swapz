#!/usr/bin/env python3
"""Tiny rootless matched-cohort tests; never execute the pressure worker."""
import hashlib
import importlib.util
import mmap
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "benchmark/resource-pressure.py"
SPEC = importlib.util.spec_from_file_location("resource_pressure", SOURCE)
pressure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pressure)
PAGE = 4096


def existing_tmpfs_file():
    # Independent availability probe; a defect in the helper must fail tests,
    # not turn them into a tmpfs-unavailable skip.
    try:
        backing = tempfile.TemporaryFile(dir="/dev/shm")
    except OSError:
        raise unittest.SkipTest("existing private tmpfs file unavailable") from None
    try:
        fd = backing.fileno()
        identity = next(line.split()[1] for line in
                        Path(f"/proc/self/fdinfo/{fd}").read_bytes().splitlines()
                        if line.startswith(b"mnt_id:"))
        rows = [line for line in Path("/proc/self/mountinfo").read_bytes().splitlines()
                if line.split()[0] == identity]
        if len(rows) != 1 or rows[0].split(b" - ")[1].split()[0] != b"tmpfs":
            raise unittest.SkipTest("existing file-backed tmpfs unavailable")
    except BaseException:
        backing.close()
        raise
    return backing


def expected_page(seed, index):
    return (bytes((0, 1)) + hashlib.shake_256(struct.pack("<QQ", seed, index)).digest(510)) * 8


def fd_count():
    return len(os.listdir("/proc/self/fd"))


class ColdWorkloadTests(unittest.TestCase):
    def test_matched_real_tmpfs_and_anonymous_hot_cold(self):
        with existing_tmpfs_file() as backing:
            before = fd_count()
            with pressure.prepare_matched_cold_workload(page_count=16, hot_page_count=5,
                                                        seed=42, tmpfs_fd=backing.fileno()) as work:
                self.assertEqual(work.backing_kind, "file-backed-tmpfs")
                self.assertEqual(work.logical_bytes_per_mapping, 16 * PAGE)
                self.assertEqual(tuple(work.hot_pages), tuple(range(5)))
                self.assertEqual(tuple(work.cold_pages), tuple(range(5, 16)))
                for _ in range(3):
                    work.touch_hot()
                # First cold access since initial population is verification.
                work.verify()
                for index in range(16):
                    page = expected_page(42, index)
                    if index < 5:
                        page = b"\x01" + page[1:]
                    offset = index * PAGE
                    self.assertEqual(work._anonymous[offset:offset+PAGE], page)
                    self.assertEqual(work._shmem[offset:offset+PAGE], page)
                    self.assertGreater(len(set(page)), 1)
                self.assertEqual(os.fstat(backing.fileno()).st_size, 16 * PAGE)
                work.touch_hot()
                work.verify()  # even parity restores the original hot bytes
            self.assertTrue(work._anonymous.closed and work._shmem.closed)
            self.assertEqual(os.fstat(backing.fileno()).st_size, 0)
            self.assertEqual(fd_count(), before)
            with self.assertRaisesRegex(pressure.ColdWorkloadError, "closed or invalidated"):
                work.touch_hot()
            with self.assertRaises(pressure.ColdWorkloadError):
                work.verify()

    def test_seed_and_full_byte_corruption(self):
        with existing_tmpfs_file() as backing:
            digests = []
            for seed in (7, 7, 8):
                with pressure.prepare_matched_cold_workload(page_count=4, hot_page_count=1,
                                                            seed=seed, tmpfs_fd=backing.fileno()) as work:
                    work.verify()
                    digests.append(hashlib.sha256(work._shmem[:]).digest())
            self.assertEqual(digests[0], digests[1])
            self.assertNotEqual(digests[0], digests[2])
            with pressure.prepare_matched_cold_workload(page_count=4, hot_page_count=1,
                                                        seed=7, tmpfs_fd=backing.fileno()) as work:
                work._shmem[4 * PAGE - 1] ^= 1
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "full-page verification failed"):
                    work.verify()
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "invalidated"):
                    work.touch_hot()
            self.assertEqual(os.fstat(backing.fileno()).st_size, 0)

    def test_bounds_and_bad_descriptor(self):
        for page_count, hot, seed, fd in ((1, 1, 0, 0), (2, 0, 0, 0), (2, 2, 0, 0),
                                         (pressure.MAX_MATCHED_PAGES + 1, 1, 0, 0),
                                         (2, 1, -1, 0), (2, 1, 2**64, 0),
                                         (True, 1, 0, 0), (2, 1, 0, -1), (2, 1, 0, False)):
            with self.subTest(page_count=page_count, hot=hot):
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "bounds"):
                    pressure.prepare_matched_cold_workload(page_count=page_count, hot_page_count=hot,
                                                          seed=seed, tmpfs_fd=fd)
        read_fd, write_fd = os.pipe()
        try:
            before = fd_count()
            with self.assertRaisesRegex(pressure.ColdWorkloadError, "private unlinked"):
                with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                            seed=0, tmpfs_fd=read_fd):
                    self.fail("pipe was accepted")
            self.assertEqual(fd_count(), before)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_invalid_backing_not_modified(self):
        with tempfile.TemporaryFile(dir="/tmp") as backing:
            fd = backing.fileno()
            identity = next(line.split()[1] for line in
                            Path(f"/proc/self/fdinfo/{fd}").read_bytes().splitlines()
                            if line.startswith(b"mnt_id:"))
            row = next(line for line in Path("/proc/self/mountinfo").read_bytes().splitlines()
                       if line.split()[0] == identity)
            if row.split(b" - ")[1].split()[0] == b"tmpfs":
                self.skipTest("non-tmpfs temporary backing unavailable")
            before = fd_count()
            with self.assertRaisesRegex(pressure.ColdWorkloadError, "not a verified tmpfs"):
                with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                            seed=0, tmpfs_fd=fd):
                    self.fail("non-tmpfs was accepted")
            self.assertEqual(os.fstat(fd).st_size, 0)
            self.assertEqual(fd_count(), before)

    def test_named_nonempty_readonly_and_unlisted_mount(self):
        with existing_tmpfs_file() as backing:
            fd = backing.fileno()
            with tempfile.NamedTemporaryFile(dir="/dev/shm") as named:
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "private unlinked"):
                    with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                                seed=0, tmpfs_fd=named.fileno()):
                        self.fail("named file was accepted")
            os.ftruncate(fd, 1)
            with self.assertRaisesRegex(pressure.ColdWorkloadError, "private unlinked"):
                with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                            seed=0, tmpfs_fd=fd):
                    self.fail("nonempty file was accepted")
            self.assertEqual(os.fstat(fd).st_size, 1)
            os.ftruncate(fd, 0)
            readonly = os.open(f"/proc/self/fd/{fd}", os.O_RDONLY)
            try:
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "private unlinked"):
                    with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                                seed=0, tmpfs_fd=readonly):
                        self.fail("readonly file was accepted")
            finally:
                os.close(readonly)
            before = fd_count()
            with patch.object(Path, "read_bytes", return_value=b"mnt_id:\t999999999999\n"):
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "identity unavailable"):
                    with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                                seed=0, tmpfs_fd=fd):
                        self.fail("unlisted mount was accepted")
            self.assertEqual(fd_count(), before)
            self.assertEqual(os.fstat(fd).st_size, 0)

    def test_partial_reserve_map_and_fill_cleanup(self):
        real_map = mmap.mmap
        real_page = pressure._cold_page
        with existing_tmpfs_file() as backing:
            fd = backing.fileno()
            before = fd_count()
            def partial_reserve(duplicate, offset, length):
                os.ftruncate(duplicate, PAGE)
                raise OSError("injected reserve error")
            with patch.object(os, "posix_fallocate", side_effect=partial_reserve):
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "reserve backing"):
                    with pressure.prepare_matched_cold_workload(page_count=4, hot_page_count=1,
                                                                seed=0, tmpfs_fd=fd):
                        self.fail("failed reserve succeeded")
            self.assertEqual(os.fstat(fd).st_size, 0)
            self.assertEqual(fd_count(), before)
            mappings = []
            def fail_second_map(*args, **kwargs):
                if mappings:
                    raise OSError("injected second mapping error")
                mapped = real_map(*args, **kwargs)
                mappings.append(mapped)
                return mapped
            with patch.object(mmap, "mmap", side_effect=fail_second_map):
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "map tmpfs"):
                    with pressure.prepare_matched_cold_workload(page_count=4, hot_page_count=1,
                                                                seed=0, tmpfs_fd=fd):
                        self.fail("failed mapping succeeded")
            self.assertEqual(len(mappings), 1)
            self.assertTrue(mappings[0].closed)
            self.assertEqual(os.fstat(fd).st_size, 0)
            self.assertEqual(fd_count(), before)
            mappings.clear()
            def record_map(*args, **kwargs):
                mapped = real_map(*args, **kwargs)
                mappings.append(mapped)
                return mapped
            def fail_fill(seed, index):
                if index == 1:
                    raise OSError("injected fill error")
                return real_page(seed, index)
            with patch.object(mmap, "mmap", side_effect=record_map), patch.object(pressure, "_cold_page", side_effect=fail_fill):
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "populate mappings"):
                    with pressure.prepare_matched_cold_workload(page_count=4, hot_page_count=1,
                                                                seed=0, tmpfs_fd=fd):
                        self.fail("failed fill succeeded")
            self.assertEqual(len(mappings), 2)
            self.assertTrue(all(mapped.closed for mapped in mappings))
            self.assertEqual(os.fstat(fd).st_size, 0)
            self.assertEqual(fd_count(), before)

    def test_body_first_error_survives_cleanup_error(self):
        with existing_tmpfs_file() as backing:
            before = fd_count()
            first_error = RuntimeError("caller first error")
            with patch.object(os, "ftruncate", side_effect=OSError("injected cleanup error")):
                with self.assertRaises(RuntimeError) as caught:
                    with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                                seed=0, tmpfs_fd=backing.fileno()) as work:
                        raise first_error
            self.assertIs(caught.exception, first_error)
            self.assertEqual(first_error.__notes__, ["matched workload cleanup failed: backing reset"])
            self.assertTrue(work._anonymous.closed and work._shmem.closed)
            self.assertEqual(fd_count(), before)
            # The caller still owns the file; explicitly clean up injected failure.
            os.ftruncate(backing.fileno(), 0)

    def test_close_failure_does_not_truncate_live_mapping(self):
        with existing_tmpfs_file() as backing:
            before = fd_count()
            view = None
            try:
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "cleanup failed: tmpfs mapping"):
                    with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                                seed=0, tmpfs_fd=backing.fileno()) as work:
                        # Deliberately violate the private no-export contract to
                        # exercise a real mmap.close() BufferError, not a fake map.
                        view = memoryview(work._shmem)
                self.assertTrue(work._anonymous.closed)
                self.assertFalse(work._shmem.closed)
                self.assertEqual(os.fstat(backing.fileno()).st_size, 2 * PAGE)
                with self.assertRaisesRegex(pressure.ColdWorkloadError, "invalidated"):
                    work.touch_hot()
            finally:
                if view is not None:
                    view.release()
                    work._shmem.close()
                    os.ftruncate(backing.fileno(), 0)
            self.assertEqual(fd_count(), before)

    @unittest.skipUnless(hasattr(os, "memfd_create"), "memfd unavailable")
    def test_memfd_is_not_silently_labeled_file_backed_tmpfs(self):
        fd = os.memfd_create("rootless-cold-test", os.MFD_CLOEXEC)
        try:
            os.fchmod(fd, 0o600)
            before = fd_count()
            with self.assertRaisesRegex(pressure.ColdWorkloadError, "mount identity|not a verified tmpfs"):
                with pressure.prepare_matched_cold_workload(page_count=2, hot_page_count=1,
                                                            seed=0, tmpfs_fd=fd):
                    self.fail("memfd was accepted as file-backed tmpfs")
            self.assertEqual(os.fstat(fd).st_size, 0)
            self.assertEqual(fd_count(), before)
        finally:
            os.close(fd)

    def test_legacy_cli_help_and_invalid_bounds_no_pressure(self):
        help_result = subprocess.run([sys.executable, "-B", str(SOURCE), "--help"],
                                     capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(help_result.returncode, 0)
        for flag in ("--memory-mib", "--ready-memory-mib", "--cpu-workers", "--ready-file",
                     "--activate-file", "--active-file", "--stop-file"):
            self.assertIn(flag, help_result.stdout)
        self.assertNotIn("--cold", help_result.stdout)
        args = [sys.executable, "-B", str(SOURCE), "--memory-mib", "1", "--cpu-workers", "1",
                "--ready-file", "unused", "--stop-file", "unused"]
        invalid = subprocess.run(args, capture_output=True, text=True, check=False, timeout=5)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(invalid.stderr, "FAIL: ID36 memory pressure must be 64..768 MiB\n")
        self.assertEqual(invalid.stdout, "")


if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("FAIL: focused cold workload tests require unprivileged execution")
    unittest.main(verbosity=2)
