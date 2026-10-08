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
        if bandwidth_mib_s <= 0 or bandwidth_mib_s > 100000:
            raise ValueError("bandwidth must be positive")
        if latency_us < 0 or latency_us > 10_000_000:
            raise ValueError("latency_us out of range")
        self.disk = SparseRamDisk(mib * 1024 * 1024)
        self.bps = bandwidth_mib_s * 1048576
        self.latency = latency_us / 1_000_000
        self.allow_trim = allow_trim
        self.clock = clock
        self.sleeper = sleeper
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
                payload: bytes = b"") -> bytes:
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
        self.sleeper(self.duration(length, command))
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
                reply = self.process(command, offset, length, payload)
                conn.sendall(REPLY.pack(REPLY_MAGIC, 0, cookie) + reply)
            except (EOFError, BrokenPipeError, ConnectionResetError):
                return
            except ProtocolError:
                self.stats["invalid_requests"] += 1
                raise


def validate_nbd_node(path: str) -> str:
    if not re.fullmatch(r"/dev/nbd[0-9]+", path):
        raise ValueError("explicit --device must be /dev/nbdN, never a physical disk")
    st = os.stat(path)
    if not stat.S_ISBLK(st.st_mode):
        raise ValueError("NBD node must be a block device")
    name = os.path.basename(path)
    if not Path("/sys/class/block", name).exists():
        raise ValueError("corresponding NBD sysfs block device is missing")
    if Path("/sys/class/block", name, "pid").exists():
        raise ValueError("NBD node has an active client and may not be reused")
    swaps = Path("/proc/swaps").read_text()
    if path in swaps.split():
        raise ValueError("selected NBD node is active swap")
    return path


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
    fd = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    kernel_sock, server_sock = socket.socketpair(socket.AF_UNIX,
                                                  socket.SOCK_STREAM)
    attached = False
    worker: threading.Thread | None = None
    try:
        fcntl.ioctl(fd, NBD_SET_SOCK, kernel_sock.fileno())
        attached = True
        fcntl.ioctl(fd, NBD_SET_BLKSIZE, BLOCK)
        fcntl.ioctl(fd, NBD_SET_SIZE_BLOCKS, model.disk.size_bytes // BLOCK)
        fcntl.ioctl(fd, NBD_SET_TIMEOUT, 120)
        flags = NBD_FLAG_HAS_FLAGS | NBD_FLAG_SEND_FLUSH | NBD_FLAG_SEND_FUA
        if args.allow_trim:
            flags |= NBD_FLAG_SEND_TRIM
        fcntl.ioctl(fd, NBD_SET_FLAGS, flags)

        def kernel_thread() -> None:
            try:
                fcntl.ioctl(fd, NBD_DO_IT)
            except OSError as exc:
                if not stop.is_set():
                    errors.append(str(exc))
            finally:
                stop.set()

        worker = threading.Thread(target=kernel_thread, daemon=True)
        worker.start()
        # No auto device selection or formatting: the caller owns the
        # explicit virtual device and all higher DM mappings.
        Path(args.ready_file).write_text(
            json.dumps({"device": path, "pid": os.getpid(),
                        "size_mib": args.size_mib,
                        "bandwidth_mib_s": args.mbps,
                        "latency_us": args.latency_us,
                        "discard": args.allow_trim}) + "\n")
        try:
            model.serve(server_sock, stop)
        finally:
            stop.set()
        return 0 if not errors else 1
    finally:
        if attached:
            try:
                fcntl.ioctl(fd, NBD_DISCONNECT)
            except OSError:
                pass
        server_sock.close()
        kernel_sock.close()
        if worker is not None:
            worker.join(timeout=5)
        if attached:
            try:
                fcntl.ioctl(fd, NBD_CLEAR_SOCK)
            except OSError:
                pass
        os.close(fd)
        if args.stats_file:
            Path(args.stats_file).write_text(
                json.dumps(model.stats, sort_keys=True) + "\n")
        if errors:
            print("kernel NBD worker: " + "; ".join(errors), file=sys.stderr)


def selftest() -> int:
    times: list[float] = []
    model = SizeAwareDevice(32, 20, 500, sleeper=times.append)
    data = bytes(range(256)) * 4096  # Exactly 1 MiB.
    model.process(CMD_WRITE, 0, len(data), data)
    assert model.process(CMD_READ, 0, len(data)) == data
    assert abs(times[0] - (0.0005 + 1 / 20)) < 1e-9
    assert model.stats["max_request_bytes"] == 1048576
    assert model.process(CMD_READ, 1048576, 4096) == ZERO
    model.process(CMD_FLUSH, 0, 0)
    assert model.stats["flushes"] == 1
    try:
        model.process(CMD_TRIM, 0, 4096)
    except ProtocolError:
        pass
    else:
        raise AssertionError("DISCARD unexpectedly enabled")

    # Exercise the real wire framing and server loop using socketpair only;
    # no root, NBD kernel driver, or live block device is touched.
    server, client = socket.socketpair()
    stopping = threading.Event()
    thread = threading.Thread(target=model.serve, args=(server, stopping))
    thread.start()

    def transact(command: int, cookie: int, offset: int,
                 length: int, payload: bytes = b"") -> bytes:
        client.sendall(REQUEST.pack(REQUEST_MAGIC, command, cookie,
                                    offset, length) + payload)
        hdr = b""
        while len(hdr) < REPLY.size:
            hdr += client.recv(REPLY.size - len(hdr))
        magic, error, reply_cookie = REPLY.unpack(hdr)
        assert (magic, error, reply_cookie) == (REPLY_MAGIC, 0, cookie)
        result = b""
        if command == CMD_READ:
            while len(result) < length:
                result += client.recv(length - len(result))
        return result

    assert transact(CMD_READ, 11, 0, 4096) == data[:4096]
    assert transact(CMD_WRITE, 12, 1048576, 4096, b"Z" * 4096) == b""
    assert transact(CMD_READ, 13, 1048576, 4096) == b"Z" * 4096
    assert transact(CMD_FLUSH, 14, 0, 0) == b""
    client.sendall(REQUEST.pack(REQUEST_MAGIC, CMD_DISC, 15, 0, 0))
    thread.join(timeout=2)
    assert not thread.is_alive()
    server.close()
    client.close()
    assert model.stats["invalid_requests"] == 0

    discard = SizeAwareDevice(32, 20, 500, allow_trim=True, sleeper=lambda _: None)
    discard.process(CMD_WRITE, 0, 4096, b"Q" * 4096)
    discard.process(CMD_TRIM, 0, 4096)
    assert discard.process(CMD_READ, 0, 4096) == ZERO
    print("size-aware NBD protocol, 1 MiB request, timing and TRIM: PASS")
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
