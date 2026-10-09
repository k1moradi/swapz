#!/usr/bin/env python3
"""Fixed rootless crash-owner harness for independent pidfd exit observation.

Only used by nbd-pidfd-owned-session-test.py. This owner deliberately dies
with os._exit() after passing its exact synthetic child's pidfd via SCM_RIGHTS
to the test parent. It never handles a real NBD attachment or block device.
"""

from __future__ import annotations

from array import array
import importlib.util
import os
from pathlib import Path
import socket
import sys

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_crash_owner_session", HERE / "nbd-pidfd-owned-session.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

STAGES = frozenset(("pre-ready", "post-ready", "idle", "ignore-term-idle"))


def share_fd(channel: socket.socket, fd: int, marker: bytes) -> None:
    channel.sendmsg(
        [marker], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array("i", [fd]))]
    )


def main() -> int:
    if (len(sys.argv) != 4 or not sys.argv[1].isdecimal()
            or sys.argv[2] not in STAGES or os.geteuid() == 0):
        return 99
    sock_fd, stage, root = int(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    if not root.is_absolute():
        return 98
    with socket.socket(fileno=sock_fd) as observer:
        fixture = root / "fixed-owned-server"
        fixture.mkdir(mode=0o700)
        session = module.RootlessOwnedServer(
            fixture,
            mode="ignore-term" if stage == "ignore-term-idle" else "normal",
            start_timeout=0.6, stop_timeout=0.2,
        )
        if stage == "pre-ready":
            genuine = module.os.pidfd_open
            calls = [0]

            def report_and_crash(pid: int, flags: int = 0) -> int:
                descriptor = genuine(pid, flags)
                calls[0] += 1
                if calls[0] == 2:
                    # Second pidfd_open is the new child, after preflight
                    # opens the parent's pidfd. Send before any READY packet.
                    share_fd(observer, descriptor, b"PRE_READY")
                    os._exit(81)
                return descriptor

            module.os.pidfd_open = report_and_crash
            session.start()
            return 97  # unreachable
        session.start()
        assert session.pidfd is not None
        share_fd(observer, session.pidfd, b"READY")
        if stage == "post-ready":
            os._exit(82)
        if observer.recv(64) != b"CRASH":
            return 96
        os._exit(83)


if __name__ == "__main__":
    raise SystemExit(main())
