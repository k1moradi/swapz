#!/usr/bin/env python3
"""Opt-in size-aware, serialized, RAM-backed NBD device for swapz benchmarks.

This is an experimental test backend, NOT persistent storage. The Linux NBD
kernel client is attached using ioctl/NBD_SET_SOCK (no network negotiation).
The userspace server implements the NBD transmission phase on a Unix socket.

One request is serviced at a time. Each READ/WRITE pays command_latency +
request_bytes / bandwidth, with no fixed per-tick maximum request size.
Run "selftest" without root; run "serve" only on an explicitly selected,
unused /dev/nbdN device. Never point this program at physical block devices.
"""

from __future__ import annotations

import argparse
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import sys
import threading
import time

BLOCK = 4096
MAX_REQUEST_BYTES = 8 * 1024 * 1024
REQUEST = struct.Struct(">IIQQI")
REPLY = struct.Struct(">IIQ")
REQUEST_MAGIC = 0x25609513
REPLY_MAGIC = 0x67446698

CMD_READ = 0
CMD_WRITE = 1
CMD_DISC = 2
CMD_FLUSH = 3
CMD_TRIM = 4
CMD_WRITE_ZEROES = 6
CMD_FLAG_FUA = 1 << 16
NBD_FLAG_HAS_FLAGS = 1 << 0
NBD_FLAG_SEND_FLUSH = 1 << 2
NBD_FLAG_SEND_FUA = 1 << 3
NBD_FLAG_SEND_TRIM = 1 << 5

# _IO(0xab, nr) on Linux: ioctl direction and size are both zero.
NBD_SET_SOCK = 0xAB00
NBD_SET_BLKSIZE = 0xAB01
NBD_DO_IT = 0xAB03
NBD_CLEAR_SOCK = 0xAB04
NBD_SET_SIZE_BLOCKS = 0xAB07
NBD_DISCONNECT = 0xAB08
NBD_SET_TIMEOUT = 0xAB09
NBD_SET_FLAGS = 0xAB0A
NBD_TIMEOUT_SECONDS = 120
# Preserve a margin for Python transport/teardown overhead at max request size.
MAX_MODELED_REQUEST_SECONDS = NBD_TIMEOUT_SECONDS - 30
ZERO = bytes(BLOCK)


class ProtocolError(Exception):
    pass


class SparseRamDisk:
    """Sparse 4 KiB blocks, never maps host storage or system swap."""

    def __init__(self, size_bytes: int):
        if size_bytes <= 0 or size_bytes % BLOCK:
            raise ValueError("size must be positive and 4096-aligned")
        self.size_bytes = size_bytes
        self.blocks: dict[int, bytes] = {}

    def check(self, offset: int, length: int) -> None:
        if (length <= 0 or length > MAX_REQUEST_BYTES or
                offset % BLOCK or length % BLOCK or
                offset > self.size_bytes or length > self.size_bytes - offset):
            raise ProtocolError("unaligned or out-of-bounds NBD request")

    def read(self, offset: int, length: int) -> bytes:
        self.check(offset, length)
        start = offset // BLOCK
        return b"".join(self.blocks.get(i, ZERO)
                        for i in range(start, start + length // BLOCK))

    def write(self, offset: int, payload: bytes) -> None:
        self.check(offset, len(payload))
        start = offset // BLOCK
        for j in range(0, len(payload), BLOCK):
            block = payload[j:j + BLOCK]
            key = start + j // BLOCK
            if block == ZERO:
                self.blocks.pop(key, None)
            else:
                self.blocks[key] = block

    def trim(self, offset: int, length: int) -> None:
        self.check(offset, length)
        for i in range(offset // BLOCK, (offset + length) // BLOCK):
            self.blocks.pop(i, None)


class SizeAwareDevice:
    def __init__(self, mib: int, bandwidth_mib_s: float,
                 latency_us: int, allow_trim: bool = False,
                 clock=time.monotonic, sleeper=time.sleep):
        if mib < 16 or mib > 4096:
            raise ValueError("export capacity must be 16..4096 MiB")
        if not math.isfinite(bandwidth_mib_s) or not 0 < bandwidth_mib_s <= 100000:
            raise ValueError("bandwidth must be finite and positive")
        if latency_us < 0 or latency_us > 10_000_000:
            raise ValueError("latency_us out of range")
        self.disk = SparseRamDisk(mib * 1024 * 1024)
        self.bps = bandwidth_mib_s * 1048576
        self.latency = latency_us / 1_000_000
        self.allow_trim = allow_trim
        self.clock = clock
        self.sleeper = sleeper
        if self.duration(MAX_REQUEST_BYTES, CMD_WRITE) >= MAX_MODELED_REQUEST_SECONDS:
            raise ValueError("configured worst-case transfer exceeds NBD timeout safety margin")
        self.stats = {
            "reads": 0, "writes": 0, "flushes": 0, "trims": 0,
            "read_bytes": 0, "write_bytes": 0, "trim_bytes": 0,
            "max_request_bytes": 0, "invalid_requests": 0,
        }

    def duration(self, size: int, command: int) -> float:
        # FLUSH has command latency but no payload. TRIM is a metadata hint;
        # model its command latency without charging transferred bytes.
        transferred = size if command in (CMD_READ, CMD_WRITE) else 0
        return self.latency + transferred / self.bps

    def process(self, command: int, offset: int, length: int,
                payload: bytes = b"",
                stopping: threading.Event | None = None) -> bytes:
        if command in (CMD_READ, CMD_WRITE, CMD_TRIM, CMD_WRITE_ZEROES):
            self.disk.check(offset, length)
        elif command != CMD_FLUSH or offset or length:
            raise ProtocolError("unsupported NBD command or invalid flush")

        if command == CMD_READ:
            reply = self.disk.read(offset, length)
            self.stats["reads"] += 1
            self.stats["read_bytes"] += length
        elif command == CMD_WRITE:
            if len(payload) != length:
                raise ProtocolError("incomplete NBD write payload")
            self.disk.write(offset, payload)
            reply = b""
            self.stats["writes"] += 1
            self.stats["write_bytes"] += length
        elif command == CMD_TRIM:
            if not self.allow_trim:
                raise ProtocolError("DISCARD not enabled")
            self.disk.trim(offset, length)
            reply = b""
            self.stats["trims"] += 1
            self.stats["trim_bytes"] += length
        elif command == CMD_WRITE_ZEROES:
            raise ProtocolError("WRITE_ZEROES not advertised")
        else:
            reply = b""
            self.stats["flushes"] += 1

        self.stats["max_request_bytes"] = max(
            self.stats["max_request_bytes"], length)
        duration = self.duration(length, command)
        if stopping is None:
            self.sleeper(duration)
        elif stopping.wait(duration):
            raise EOFError("NBD server stopped during modeled transfer")
        return reply

    def recv_exact(self, conn: socket.socket, count: int,
                   stopping: threading.Event) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            if stopping.is_set():
                raise EOFError("server stopping")
            try:
                part = conn.recv(min(count - len(chunks), 1024 * 1024))
            except socket.timeout:
                continue
            if not part:
                raise EOFError("NBD peer disconnected")
            chunks.extend(part)
        return bytes(chunks)

    def send_exact(self, conn: socket.socket, payload: bytes,
                   stopping: threading.Event) -> None:
        # sendall() loses the transmitted byte count on socket timeout;
        # retrying it could duplicate a partially sent NBD reply.
        pending = memoryview(payload)
        while pending:
            if stopping.is_set():
                raise EOFError("server stopping")
            try:
                sent = conn.send(pending)
            except socket.timeout:
                continue
            if not sent:
                raise EOFError("NBD peer disconnected during reply")
            pending = pending[sent:]

    def serve(self, conn: socket.socket, stopping: threading.Event) -> None:
        conn.settimeout(0.25)
        while not stopping.is_set():
            try:
                raw = self.recv_exact(conn, REQUEST.size, stopping)
                magic, type_flags, cookie, offset, length = REQUEST.unpack(raw)
                if magic != REQUEST_MAGIC:
                    raise ProtocolError("bad NBD request magic")
                command = type_flags & 0xFFFF
                flags = type_flags & 0xFFFF0000
                if flags & ~CMD_FLAG_FUA:
                    raise ProtocolError("unsupported NBD request flag")
                if flags & CMD_FLAG_FUA and command != CMD_WRITE:
                    raise ProtocolError("FUA on non-write")
                if command == CMD_DISC:
                    if offset or length:
                        raise ProtocolError("invalid NBD disconnect")
                    return
                # Reject unsupported or oversized commands before receiving
                # a large write payload, then terminate the session safely.
                if command not in (CMD_READ, CMD_WRITE, CMD_FLUSH, CMD_TRIM):
                    raise ProtocolError("unsupported command")
                if command in (CMD_READ, CMD_WRITE, CMD_TRIM):
                    self.disk.check(offset, length)
                payload = (self.recv_exact(conn, length, stopping)
                           if command == CMD_WRITE else b"")
                reply = self.process(command, offset, length, payload, stopping=stopping)
                self.send_exact(conn, REPLY.pack(REPLY_MAGIC, 0, cookie) + reply,
                                stopping)
            except (EOFError, BrokenPipeError, ConnectionResetError):
                return
            except ProtocolError:
                self.stats["invalid_requests"] += 1
                raise


def verify_nbd_device_identity(name: str, device_number: int) -> None:
    """Require the selected device node to match the actual NBD sysfs device."""
    expected_number = Path("/sys/class/block", name, "dev").read_text().strip()
    observed_number = f"{os.major(device_number)}:{os.minor(device_number)}"
    if observed_number != expected_number:
        raise ValueError("NBD device node major:minor differs from NBD sysfs")


def verify_nbd_no_holders(name: str) -> None:
    """Inspect the actual sysfs holders directory; never infer empty on error."""
    holders = Path("/sys/class/block", name, "holders")
    try:
        with os.scandir(holders) as entries:
            if any(True for _ in entries):
                raise ValueError("selected NBD node has block-device holders")
    except OSError as exc:
        raise ValueError(f"cannot inspect NBD holders for {name}: {exc}") from exc


def validate_nbd_node(path: str) -> str:
    if not re.fullmatch(r"/dev/nbd[0-9]+", path):
        raise ValueError("explicit --device must be /dev/nbdN, never a physical disk")
    # lstat rejects symlinks masquerading as the explicitly named NBD node.
    st = os.lstat(path)
    if not stat.S_ISBLK(st.st_mode):
        raise ValueError("NBD node must be a block device")
    name = os.path.basename(path)
    if not Path("/sys/class/block", name).exists():
        raise ValueError("corresponding NBD sysfs block device is missing")
    # /dev/nbdN can otherwise be replaced by an unrelated block-device node.
    verify_nbd_device_identity(name, st.st_rdev)
    # An inaccessible PID attribute is not proof that no NBD client exists.
    try:
        os.stat(Path("/sys/class/block", name, "pid"))
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ValueError(f"cannot inspect NBD client PID: {exc}") from exc
    else:
        raise ValueError("NBD node has an active client and may not be reused")
    # Reject any mounted NBD block or dependent DM holder. Do not rely on
    # pathname equality: mounts can use alternate /dev symlinks.
    number = f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"
    mountinfo = Path("/proc/self/mountinfo").read_text()
    if any(line.split()[2] == number for line in mountinfo.splitlines()):
        raise ValueError("selected NBD node is mounted")
    verify_nbd_no_holders(name)
    # A partition mounted under /dev/nbdNp1 would have a different dev_t
    # than the parent. Refuse reuse of an NBD node with any partition nodes.
    sysdir = Path("/sys/class/block", name)
    if any(child.name.startswith(name + "p") for child in sysdir.iterdir()):
        raise ValueError("selected NBD node has partitions")
    swaps = Path("/proc/swaps").read_text()
    for line in swaps.splitlines()[1:]:
        swap_path = line.split()[0]
        try:
            swap_st = os.stat(swap_path)
        except OSError as exc:
            raise ValueError(f"cannot inspect active swap path {swap_path}: {exc}") from exc
        if stat.S_ISBLK(swap_st.st_mode) and swap_st.st_rdev == st.st_rdev:
            raise ValueError("selected NBD node is active swap")
    return path


def shutdown_kernel_session(fd: int, attached: bool,
                            worker: threading.Thread | None,
                            stopping: threading.Event,
                            server_sock: socket.socket, kernel_sock: socket.socket,
                            failures: list[str], *,
                            ioctl=fcntl.ioctl, close_fd=os.close,
                            join_timeout: float = 5.0) -> None:
    """Never release NBD descriptors while the kernel worker still owns them.

    When the kernel worker cannot stop promptly, preserve the backing/session
    and wait for it rather than returning successfully and closing live fds.
    """
    def record_shutdown_failure(message: str) -> None:
        failures.append(message)
        # Emit immediately: a stuck worker could make a later final report
        # unreachable, so preserve the specific ioctl failure before join().
        print("ERROR: " + message, file=sys.stderr, flush=True)

    stopping.set()
    if attached and worker is not None and worker.is_alive():
        try:
            ioctl(fd, NBD_DISCONNECT)
        except OSError as exc:
            record_shutdown_failure(f"NBD_DISCONNECT failed: {exc}")
    if worker is not None:
        worker.join(timeout=join_timeout)
        if worker.is_alive():
            warning = ("NBD_DO_IT worker did not stop within shutdown deadline; "
                       "retaining descriptors until it exits; "
                       "investigate DM holders and kernel task state")
            record_shutdown_failure(warning)
            # Releasing the socket/fd here can disconnect a live DM-backed
            # client. Do not abandon a daemon worker or force detach.
            worker.join()
    if attached:
        try:
            ioctl(fd, NBD_CLEAR_SOCK)
        except OSError as exc:
            record_shutdown_failure(f"NBD_CLEAR_SOCK failed: {exc}")
    # Once the kernel worker is definitely stopped, independently close all
    # three owned handles. A later close exception must not hide earlier
    # detach/clear-sock failures or skip another cleanup step.
    for label, closer in (("server socket", server_sock.close),
                          ("kernel socket", kernel_sock.close),
                          ("NBD fd", lambda: close_fd(fd))):
        try:
            closer()
        except OSError as exc:
            record_shutdown_failure(f"could not close {label}: {exc}")


def serve_kernel(args: argparse.Namespace) -> int:
    path = validate_nbd_node(args.device)
    model = SizeAwareDevice(args.size_mib, args.mbps,
                            args.latency_us, args.allow_trim)
    stop = threading.Event()
    errors: list[str] = []

    def stop_handler(_signum: int, _frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    # NBD_SET_SOCK fails if an active kernel client already owns this NBD
    # device. Never change its geometry until that ioctl succeeds.
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        kernel_sock, server_sock = socket.socketpair(socket.AF_UNIX,
                                                      socket.SOCK_STREAM)
    except OSError:
        os.close(fd)
        raise
    attached = False
    worker: threading.Thread | None = None
    try:
        # Recheck the opened descriptor to close the validate/open race before
        # NBD_SET_SOCK, geometry changes, or any other NBD ioctl.
        opened_device = os.fstat(fd)
        if not stat.S_ISBLK(opened_device.st_mode):
            raise ValueError("opened NBD descriptor is not a block device")
        verify_nbd_device_identity(os.path.basename(path), opened_device.st_rdev)
        fcntl.ioctl(fd, NBD_SET_SOCK, kernel_sock.fileno())
        attached = True
        fcntl.ioctl(fd, NBD_SET_BLKSIZE, BLOCK)
        fcntl.ioctl(fd, NBD_SET_SIZE_BLOCKS, model.disk.size_bytes // BLOCK)
        fcntl.ioctl(fd, NBD_SET_TIMEOUT, NBD_TIMEOUT_SECONDS)
        flags = NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH | NBD_FLAG_SEND_FUA
        if args.allow_trim:
            flags |= NBD_FLAG_SEND_TRIM
        fcntl.ioctl(fd, NBD_SET_FLAGS, flags)

        def kernel_thread() -> None:
            try:
                fcntl.ioctl(fd, NBD_DO_IT)
                if not stop.is_set():
                    errors.append("NBD_DO_IT unexpectedly returned before shutdown")
            except OSError as exc:
                if not stop.is_set():
                    errors.append(f"NBD_DO_IT failed: {exc}")
            finally:
                stop.set()

        # The worker must never be abandoned: it owns the NBD file descriptor.
        new_worker = threading.Thread(target=kernel_thread, daemon=False)
        new_worker.start()
        worker = new_worker
        # No auto device selection or formatting: the caller owns the
        # explicit virtual device and all higher DM mappings.
        Path(args.ready_file).write_text(
            json.dumps({"device": path, "pid": os.getpid(),
                        "size_mib": args.size_mib,
                        "bandwidth_mib_s": args.mbps,
                        "latency_us": args.latency_us,
                        "discard": args.allow_trim}) + "\n")
        model.serve(server_sock, stop)
    finally:
        shutdown_kernel_session(fd, attached, worker, stop,
                                server_sock, kernel_sock, errors)
        if args.stats_file:
            try:
                Path(args.stats_file).write_text(
                    json.dumps(model.stats, sort_keys=True) + "\n")
            except OSError as exc:
                errors.append(f"failed to write NBD stats: {exc}")
        if errors:
            print("NBD backend: " + "; ".join(errors), file=sys.stderr)
    # This is evaluated *after* shutdown; errors from disconnect, join and
    # clear-sock must affect the CLI result.
    return 0 if not errors else 1


def client_recv_exact(conn: socket.socket, count: int) -> bytes:
    """Bounded selftest receive: fail on EOF or timeout, never spin on b''."""
    pieces = bytearray()
    while len(pieces) < count:
        try:
            part = conn.recv(count - len(pieces))
        except socket.timeout as exc:
            raise TimeoutError("timed out waiting for NBD test reply") from exc
        if not part:
            raise EOFError("truncated NBD test reply")
        pieces.extend(part)
    return bytes(pieces)


def client_transact(conn: socket.socket, command: int, cookie: int,
                    offset: int, length: int, payload: bytes = b"") -> bytes:
    try:
        conn.sendall(REQUEST.pack(REQUEST_MAGIC, command, cookie,
                                  offset, length) + payload)
    except socket.timeout as exc:
        raise TimeoutError("timed out sending NBD test request") from exc
    magic, error, reply_cookie = REPLY.unpack(client_recv_exact(conn, REPLY.size))
    if (magic, error, reply_cookie) != (REPLY_MAGIC, 0, cookie):
        raise ProtocolError("invalid NBD test reply magic, error or cookie")
    return client_recv_exact(conn, length) if command == CMD_READ else b""


def selftest_failure_gates() -> None:
    """Rootless negative cases against the actual validators and serve loop."""
    import contextlib
    import io
    from types import SimpleNamespace
    from unittest import mock

    # Missing/unreadable directories and iteration failures are *not* empty.
    with mock.patch("os.scandir",
                    return_value=contextlib.nullcontext(iter(()))):
        verify_nbd_no_holders("nbd0")
    with mock.patch("os.scandir",
                    return_value=contextlib.nullcontext(iter((object(),)))):
        try:
            verify_nbd_no_holders("nbd0")
        except ValueError as exc:
            assert "holders" in str(exc)
        else:
            raise AssertionError("populated NBD holders directory was accepted")
    for scan_error in (FileNotFoundError("missing sysfs holders"),
                       PermissionError("denied sysfs holders"),
                       OSError(errno.EIO, "cannot enumerate holders")):
        with mock.patch("os.scandir", side_effect=scan_error):
            try:
                verify_nbd_no_holders("nbd0")
            except ValueError as exc:
                assert "cannot inspect" in str(exc)
            else:
                raise AssertionError("uninspectable NBD holders were accepted")

    class FaultyEntries:
        def __iter__(self):
            raise OSError(errno.EIO, "directory iteration failed")

    with mock.patch("os.scandir",
                    return_value=contextlib.nullcontext(FaultyEntries())):
        try:
            verify_nbd_no_holders("nbd0")
        except ValueError as exc:
            assert "cannot inspect" in str(exc)
        else:
            raise AssertionError("NBD holders iteration failure was accepted")

    # A failed sysfs PID inspection must not pass the full node preflight.
    spoof = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(43, 0))
    with (mock.patch("os.lstat", return_value=spoof),
          mock.patch.object(Path, "exists", return_value=True),
          mock.patch.object(Path, "read_text", return_value="43:0\n"),
          mock.patch("os.stat", side_effect=PermissionError("pid inaccessible"))):
        try:
            validate_nbd_node("/dev/nbd0")
        except ValueError as exc:
            assert "cannot inspect NBD client PID" in str(exc)
        else:
            raise AssertionError("inaccessible NBD client PID was accepted")

    model = SizeAwareDevice(32, 20, 0, sleeper=lambda _delay: None)
    full = b"A" * MAX_REQUEST_BYTES
    capacity = model.disk.size_bytes
    model.process(CMD_WRITE, capacity - MAX_REQUEST_BYTES,
                  MAX_REQUEST_BYTES, full)
    assert model.process(CMD_READ, capacity - MAX_REQUEST_BYTES,
                         MAX_REQUEST_BYTES) == full
    for off, count in ((0, MAX_REQUEST_BYTES + BLOCK),
                       (1, BLOCK),
                       (capacity, BLOCK),
                       (capacity - BLOCK, 2 * BLOCK)):
        try:
            model.disk.check(off, count)
        except ProtocolError as exc:
            assert "unaligned or out-of-bounds" in str(exc)
        else:
            raise AssertionError("invalid NBD size/offset was accepted")

    # For each malformed request, assert the *specific* serve() rejection.
    # No write payload is supplied: over-limit requests must be rejected
    # before attempting to receive a multi-megabyte body.
    cases = (
        ("unknown_command", REQUEST_MAGIC, 0x1234, BLOCK,
         "unsupported command"),
        ("unsupported_flags", REQUEST_MAGIC, (1 << 17) | CMD_READ,
         BLOCK, "unsupported NBD request flag"),
        ("invalid_fua", REQUEST_MAGIC, CMD_FLAG_FUA | CMD_READ,
         BLOCK, "FUA on non-write"),
        ("oversize_write", REQUEST_MAGIC, CMD_WRITE,
         MAX_REQUEST_BYTES + BLOCK, "unaligned or out-of-bounds"),
        ("invalid_flush", REQUEST_MAGIC, CMD_FLUSH,
         BLOCK, "invalid flush"),
    )
    for case_name, magic, type_flags, count, diagnostic in cases:
        server, client = socket.socketpair()
        client.settimeout(1)
        stopped = threading.Event()
        caught: list[Exception] = []

        def serve_bad() -> None:
            try:
                model.serve(server, stopped)
            except Exception as exc:
                caught.append(exc)

        thread = threading.Thread(target=serve_bad, daemon=True)
        try:
            thread.start()
            client.sendall(REQUEST.pack(magic, type_flags, 0xA55A, 0, count))
            thread.join(timeout=1)
            assert not thread.is_alive(), f"{case_name} did not terminate server"
            assert len(caught) == 1 and isinstance(caught[0], ProtocolError)
            assert diagnostic in str(caught[0]), (case_name, caught)
        finally:
            stopped.set()
            client.close()
            server.close()
            if thread.ident is not None:
                thread.join(timeout=1)
        assert not thread.is_alive()

    # Test the complete client transaction with a valid reply header followed
    # by a truncated payload, instead of only testing the recv helper.
    peer, client = socket.socketpair()
    client.settimeout(1)
    try:
        peer.sendall(REPLY.pack(REPLY_MAGIC, 0, 91) + b"short")
        peer.shutdown(socket.SHUT_WR)
        try:
            client_transact(client, CMD_READ, 91, 0, BLOCK)
        except EOFError as exc:
            assert "truncated" in str(exc)
        else:
            raise AssertionError("client_transact accepted a short READ reply")
    finally:
        peer.close()
        client.close()

    # Interrupt an *already active* modeled read wait. Confirm the
    # server sends no successful reply after a cancelled operation.
    entered = threading.Event()

    class ObservedStop(threading.Event):
        def wait(self, timeout: float | None = None) -> bool:
            entered.set()
            return super().wait(timeout)

    server, client = socket.socketpair()
    client.settimeout(1)
    stopped = ObservedStop()
    errors: list[Exception] = []
    slow = SizeAwareDevice(32, 1, 0)

    def serve_slow() -> None:
        try:
            slow.serve(server, stopped)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve_slow, daemon=True)
    try:
        thread.start()
        client.sendall(REQUEST.pack(REQUEST_MAGIC, CMD_READ, 88,
                                    0, 1048576))
        assert entered.wait(timeout=2), "modeled transfer never entered wait"
        assert thread.is_alive(), "server exited before mid-wait cancellation"
        stopped.set()
        thread.join(timeout=2)
        assert not thread.is_alive(), "modeled request ignored mid-wait stop"
        assert not errors, f"unexpected cancellation error: {errors}"
        server.close()
        assert client.recv(1) == b"", "cancelled request emitted a reply"
    finally:
        stopped.set()
        client.close()
        server.close()
        if thread.ident is not None:
            thread.join(timeout=2)
    assert not thread.is_alive()

    # Fail after successful NBD_SET_SOCK but before worker startup. This
    # checks actual serve_kernel() cleanup with mocked descriptors/ioctls;
    # no /dev/nbdN, kernel worker, or system swap is opened.
    class FakeSocket:
        def __init__(self) -> None:
            self.closed = False

        def fileno(self) -> int:
            return 82

        def close(self) -> None:
            self.closed = True

    kernel_sock, server_sock = FakeSocket(), FakeSocket()
    ioctl_steps: list[int] = []

    def setup_ioctl(_fd: int, operation: int, *_args: object) -> None:
        ioctl_steps.append(operation)
        if operation == NBD_SET_BLKSIZE:
            raise OSError(errno.EIO, "injected geometry setup failure")
        if operation == NBD_CLEAR_SOCK:
            raise OSError(errno.EIO, "injected setup clear failure")

    args = argparse.Namespace(device="/dev/nbd0", size_mib=32, mbps=20,
                              latency_us=500, allow_trim=False,
                              ready_file="not-written", stats_file=None)
    err = io.StringIO()
    with (mock.patch(__name__ + ".validate_nbd_node", return_value="/dev/nbd0"),
          mock.patch(__name__ + ".verify_nbd_device_identity"),
          mock.patch("os.open", return_value=81),
          mock.patch("os.fstat", return_value=spoof),
          mock.patch("os.close") as fd_close,
          mock.patch("socket.socketpair", return_value=(kernel_sock, server_sock)),
          mock.patch("fcntl.ioctl", side_effect=setup_ioctl),
          mock.patch("signal.signal"),
          contextlib.redirect_stderr(err)):
        try:
            serve_kernel(args)
        except OSError as exc:
            assert "geometry setup failure" in str(exc)
        else:
            raise AssertionError("NBD setup fault was accepted")
    assert ioctl_steps == [NBD_SET_SOCK, NBD_SET_BLKSIZE, NBD_CLEAR_SOCK]
    assert kernel_sock.closed and server_sock.closed
    fd_close.assert_called_once_with(81)
    assert "NBD_CLEAR_SOCK failed" in err.getvalue()


def selftest() -> int:
    from types import SimpleNamespace
    from unittest import mock

    # No root or device attach: model a spoofed /dev/nbd0 node whose dev_t
    # belongs to a non-NBD disk, while the NBD sysfs entry exists.
    spoofed_node = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 0))
    with (mock.patch("os.lstat", return_value=spoofed_node),
          mock.patch.object(Path, "exists", return_value=True),
          mock.patch.object(Path, "read_text", return_value="43:0\n")):
        try:
            validate_nbd_node("/dev/nbd0")
        except ValueError as exc:
            assert "major:minor" in str(exc)
        else:
            raise AssertionError("spoofed NBD device node was accepted")

    times: list[float] = []
    model = SizeAwareDevice(32, 20, 500, sleeper=times.append)
    data = bytes(range(256)) * 4096  # Exactly 1 MiB.
    model.process(CMD_WRITE, 0, len(data), data)
    assert model.process(CMD_READ, 0, len(data)) == data
    full_duration = 0.0005 + 1 / 20
    assert abs(times[0] - full_duration) < 1e-9
    assert abs(times[1] - full_duration) < 1e-9
    assert model.stats["max_request_bytes"] == 1048576
    assert model.process(CMD_READ, 1048576, BLOCK) == ZERO
    small_duration = times[-1]
    assert abs(small_duration - (0.0005 + BLOCK / (20 * 1048576))) < 1e-9
    assert full_duration > small_duration * 10  # Constant duration must fail.
    model.process(CMD_FLUSH, 0, 0)
    assert abs(times[-1] - 0.0005) < 1e-9
    assert model.stats["flushes"] == 1
    try:
        model.process(CMD_TRIM, 0, BLOCK)
    except ProtocolError:
        pass
    else:
        raise AssertionError("DISCARD unexpectedly enabled")

    for invalid_rate in (float("nan"), float("inf"), 0.0, -1.0, 0.01):
        try:
            SizeAwareDevice(32, invalid_rate, 500)
        except ValueError:
            pass
        else:
            raise AssertionError("unsafe NBD bandwidth accepted")

    # Exercise the real wire framing and server loop using socketpair only;
    # no root, NBD kernel driver, or live block device is touched.
    server, client = socket.socketpair()
    client.settimeout(2)
    stopping = threading.Event()
    thread = threading.Thread(target=model.serve, args=(server, stopping),
                              daemon=True)
    try:
        thread.start()
        assert client_transact(client, CMD_READ, 16, 0, len(data)) == data
        # Full-size WRITE must travel through the socket, not just the model.
        replacement = b"W" * len(data)
        assert client_transact(client, CMD_WRITE, 17, 0, len(data), replacement) == b""
        assert client_transact(client, CMD_READ, 18, 0, len(data)) == replacement
        assert client_transact(client, CMD_WRITE, 12, 1048576, BLOCK,
                               b"Z" * BLOCK) == b""
        assert client_transact(client, CMD_READ, 13, 1048576, BLOCK) == b"Z" * BLOCK
        assert client_transact(client, CMD_FLUSH, 14, 0, 0) == b""
        client.sendall(REQUEST.pack(REQUEST_MAGIC, CMD_DISC, 15, 0, 0))
    finally:
        stopping.set()
        if thread.ident is not None:
            thread.join(timeout=2)
        server.close()
        client.close()
    assert not thread.is_alive()
    assert model.stats["invalid_requests"] == 0

    class PartialReplySocket:
        def __init__(self):
            self.received = bytearray()
            self.attempts = 0

        def send(self, pending: memoryview) -> int:
            self.attempts += 1
            if self.attempts == 2:
                raise socket.timeout("injected transient send timeout")
            sent = min(len(pending), 3)
            self.received.extend(pending[:sent])
            return sent

    # Timeout after a partial send cannot duplicate reply data.
    partial_socket = PartialReplySocket()
    model.send_exact(partial_socket, b"abcdefg", threading.Event())
    assert partial_socket.received == b"abcdefg"

    discard_times: list[float] = []
    discard = SizeAwareDevice(32, 20, 500, allow_trim=True,
                              sleeper=discard_times.append)
    discard.process(CMD_WRITE, 0, BLOCK, b"Q" * BLOCK)
    discard.process(CMD_TRIM, 0, BLOCK)
    assert abs(discard_times[-1] - 0.0005) < 1e-9
    assert discard.process(CMD_READ, 0, BLOCK) == ZERO

    trim_server, trim_client = socket.socketpair()
    trim_client.settimeout(2)
    trim_stop = threading.Event()
    trim_thread = threading.Thread(target=discard.serve,
                                   args=(trim_server, trim_stop), daemon=True)
    try:
        trim_thread.start()
        client_transact(trim_client, CMD_WRITE, 20, 0, BLOCK, b"Q" * BLOCK)
        client_transact(trim_client, CMD_TRIM, 21, 0, BLOCK)
        assert client_transact(trim_client, CMD_READ, 22, 0, BLOCK) == ZERO
        trim_client.sendall(REQUEST.pack(REQUEST_MAGIC, CMD_DISC, 23, 0, 0))
    finally:
        trim_stop.set()
        if trim_thread.ident is not None:
            trim_thread.join(timeout=2)
        trim_client.close()
        trim_server.close()
    assert not trim_thread.is_alive()

    # Incomplete reply headers/payloads, an idle peer and invalid reply
    # framing must fail deterministically rather than hang or spin.
    for case in ("header_eof", "payload_eof", "timeout", "bad_cookie", "bad_magic"):
        peer, client = socket.socketpair()
        client.settimeout(0.05)
        try:
            if case == "header_eof":
                peer.sendall(REPLY.pack(REPLY_MAGIC, 0, 45)[:7])
                peer.shutdown(socket.SHUT_WR)
                try:
                    client_recv_exact(client, REPLY.size)
                except EOFError:
                    pass
                else:
                    raise AssertionError("truncated header was accepted")
            elif case == "payload_eof":
                peer.sendall(b"X" * 5)
                peer.shutdown(socket.SHUT_WR)
                try:
                    client_recv_exact(client, BLOCK)
                except EOFError:
                    pass
                else:
                    raise AssertionError("truncated payload was accepted")
            elif case == "timeout":
                try:
                    client_recv_exact(client, REPLY.size)
                except TimeoutError:
                    pass
                else:
                    raise AssertionError("stalled reply did not time out")
            else:
                cookie = 44 if case == "bad_cookie" else 45
                magic = REPLY_MAGIC if case == "bad_cookie" else 0
                peer.sendall(REPLY.pack(magic, 0, cookie))
                try:
                    client_transact(client, CMD_FLUSH, 45, 0, 0)
                except ProtocolError:
                    pass
                else:
                    raise AssertionError("invalid reply framing accepted")
        finally:
            client.close()
            peer.close()

    # Disabled TRIM and malformed NBD commands must terminate the server.
    for command, magic in ((CMD_TRIM, REQUEST_MAGIC),
                           (CMD_READ, 0xDEADBEEF)):
        bad_server, bad_client = socket.socketpair()
        bad_client.settimeout(1)
        bad_stop = threading.Event()
        failures: list[Exception] = []

        def run_invalid() -> None:
            try:
                model.serve(bad_server, bad_stop)
            except ProtocolError as exc:
                failures.append(exc)

        bad_thread = threading.Thread(target=run_invalid, daemon=True)
        try:
            bad_thread.start()
            bad_client.sendall(REQUEST.pack(magic, command, 60, 0, BLOCK))
            bad_thread.join(timeout=1)
            assert not bad_thread.is_alive() and len(failures) == 1
        finally:
            bad_stop.set()
            bad_client.close()
            bad_server.close()
            if bad_thread.ident is not None:
                bad_thread.join(timeout=1)
        assert not bad_thread.is_alive()

    # A modeled multi-second wait must react immediately to stop.
    slow = SizeAwareDevice(32, 1, 500)
    stopped = threading.Event()
    stopped.set()
    try:
        slow.process(CMD_READ, 0, 1048576, stopping=stopped)
    except EOFError:
        pass
    else:
        raise AssertionError("model delay did not respond to server stop")

    # Mock the *real shutdown helper* without opening an NBD kernel device.
    class ShutdownWorker:
        def __init__(self, slow: bool = False):
            self.alive = True
            self.slow = slow
            self.joins: list[float | None] = []

        def is_alive(self) -> bool:
            return self.alive

        def join(self, timeout: float | None = None) -> None:
            self.joins.append(timeout)
            if not self.slow or timeout is None:
                self.alive = False

    class ShutdownSocket:
        def __init__(self, worker: ShutdownWorker, fail: bool = False):
            self.worker = worker
            self.closed = False
            self.fail = fail

        def close(self) -> None:
            assert not self.worker.is_alive(), "closed socket while worker active"
            self.closed = True
            if self.fail:
                raise OSError(errno.EIO, "injected socket-close failure")

    for failure in ("none", "disconnect", "clear", "slow_worker",
                    "server_close", "kernel_close", "fd_close",
                    "disconnect_server_close"):
        shutdown_worker = ShutdownWorker(slow=failure == "slow_worker")
        shutdown_server = ShutdownSocket(shutdown_worker,
                                         fail=failure in ("server_close", "disconnect_server_close"))
        shutdown_kernel = ShutdownSocket(shutdown_worker,
                                         fail=failure == "kernel_close")
        ioctl_steps: list[int] = []
        fd_closed: list[int] = []
        shutdown_errors: list[str] = []

        def fake_ioctl(_fd: int, operation: int) -> None:
            ioctl_steps.append(operation)
            if ((failure in ("disconnect", "disconnect_server_close")
                 and operation == NBD_DISCONNECT)
                    or (failure == "clear" and operation == NBD_CLEAR_SOCK)):
                raise OSError(errno.EIO, "injected NBD ioctl failure")

        def fake_close(fd: int) -> None:
            fd_closed.append(fd)
            if failure == "fd_close":
                raise OSError(errno.EIO, "injected fd-close failure")

        shutdown_kernel_session(
            99, True, shutdown_worker, threading.Event(),
            shutdown_server, shutdown_kernel, shutdown_errors,
            ioctl=fake_ioctl, close_fd=fake_close, join_timeout=0)
        assert ioctl_steps == [NBD_DISCONNECT, NBD_CLEAR_SOCK]
        assert shutdown_server.closed and shutdown_kernel.closed
        assert fd_closed == [99]
        if failure == "none":
            assert not shutdown_errors
        elif failure == "slow_worker":
            assert len(shutdown_worker.joins) == 2
            assert shutdown_worker.joins[1] is None
            assert any("shutdown deadline" in issue for issue in shutdown_errors)
        elif failure == "disconnect_server_close":
            assert any("NBD_DISCONNECT failed" in issue for issue in shutdown_errors)
            assert any("server socket" in issue for issue in shutdown_errors)
        elif failure in ("server_close", "kernel_close", "fd_close"):
            expected = {"server_close": "server socket",
                        "kernel_close": "kernel socket", "fd_close": "NBD fd"}[failure]
            assert any(expected in issue for issue in shutdown_errors)
        else:
            assert any(failure.upper() in issue for issue in shutdown_errors)

    selftest_failure_gates()
    print("size-aware NBD protocol, 1 MiB wire I/O, timing, TRIM, EOF and shutdown: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("selftest")
    srv = sub.add_parser("serve")
    srv.add_argument("--device", required=True,
                     help="EXPLICIT unused /dev/nbdN, virtual only")
    srv.add_argument("--size-mib", type=int, default=256)
    srv.add_argument("--mbps", type=float, default=20)
    srv.add_argument("--latency-us", type=int, default=500)
    srv.add_argument("--ready-file", required=True)
    srv.add_argument("--stats-file")
    srv.add_argument("--allow-trim", action="store_true")
    args = parser.parse_args()
    if args.mode == "selftest":
        return selftest()
    if os.geteuid() != 0:
        parser.error("serve requires root")
    try:
        return serve_kernel(args)
    except (OSError, ValueError, ProtocolError) as exc:
        print(f"size-aware NBD backend error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
