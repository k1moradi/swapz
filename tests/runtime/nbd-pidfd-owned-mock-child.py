#!/usr/bin/env python3
"""Fixed synthetic pidfd-owned process: NO NBD, DM, device, or subprocess I/O.

Arguments are exactly an inherited AF_UNIX SOCK_SEQPACKET socket descriptor
and an allowlisted fault-injection mode. Only test-owned regular-file logs.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import time

MODES = frozenset(("normal", "wrong-ready", "exit-before-ready",
                   "exit-after-ready", "ignore-term", "fail-term",
                   "slow-ready", "silent"))


def _sigterm_ok(_signal: int, _frame: object) -> None:
    raise SystemExit(0)


def _sigterm_fail(_signal: int, _frame: object) -> None:
    raise SystemExit(7)


def main() -> int:
    if (len(sys.argv) != 3 or not sys.argv[1].isdecimal()
            or sys.argv[2] not in MODES or os.geteuid() == 0):
        return 99
    mode = sys.argv[2]
    fd = int(sys.argv[1])
    try:
        with socket.socket(fileno=fd) as channel:
            channel.settimeout(1.0)
            hello = channel.recv(128)
            if not (hello.startswith(b"HELLO ") and len(hello) == 38
                    and all(c in b"0123456789abcdef" for c in hello[6:])):
                return 8
            if mode == "exit-before-ready":
                return 4
            if mode == "slow-ready":
                time.sleep(0.8)
            if mode == "silent":
                while True:
                    time.sleep(1.0)
            reply = hello.replace(b"HELLO ", b"READY ", 1)
            if mode == "wrong-ready":
                reply = b"READY " + b"0" * 32
                if reply == b"READY " + hello[6:]:
                    reply = b"READY " + b"1" * 32
            channel.sendall(reply)
            if mode == "exit-after-ready":
                return 0
            if mode == "ignore-term":
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
            elif mode == "fail-term":
                signal.signal(signal.SIGTERM, _sigterm_fail)
            else:
                signal.signal(signal.SIGTERM, _sigterm_ok)
            channel.settimeout(None)
            while True:
                signal.pause()
    except (OSError, ValueError):
        return 9


if __name__ == "__main__":
    raise SystemExit(main())
