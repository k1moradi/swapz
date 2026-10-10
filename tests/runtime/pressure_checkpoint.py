#!/usr/bin/env python3
"""Rootless, test-owned, phase-specific pressure checkpoint release protocol.

No NBD, DM, swap, process signaling, or systemd operations are performed.
Only fresh files inside the caller's private per-unit directory are used.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import tempfile
import time


PHASES = ("filled", "verified")
TOKEN_PATTERN = re.compile(r"[0-9a-f]{32}\Z")


def _expected(token: str, phase: str) -> bytes:
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise ValueError("pressure checkpoint token is not a 128-bit hex nonce")
    if phase not in PHASES:
        raise ValueError("invalid pressure checkpoint phase")
    return f"{phase}:{token}\n".encode("ascii")


def _publish_new(path: Path, contents: bytes) -> None:
    """Publish complete bytes atomically, never overwrite an existing token."""
    if not path.parent.is_dir():
        raise FileNotFoundError("pressure checkpoint directory is not available")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                prefix=".swapz-checkpoint-", dir=path.parent,
                delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic no-replace publish: a stale token cannot be overwritten.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_exact_checkpoint(path: Path, expected: bytes) -> None:
    """Read only one short, unlinked regular file; never follow symlinks.

    A malformed file must not act as a successful checkpoint. In particular,
    Path.read_bytes() would accept a symlink to the expected token, read a
    huge file without a bound, or block on a FIFO with no writer.
    """
    # _publish_new() atomically links its complete temporary file into the
    # final name, then unlinks the temporary name. During that tiny window
    # st_nlink is 2. Never accept two links, but allow a finite interval for
    # the publisher to finish unlinking before classifying it as unsafe.
    # A persistent hardlink (or any non-regular file) remains forbidden.
    for attempt in range(51):
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink not in (1, 2):
            raise ValueError(f"unsafe pressure checkpoint file: {path}")
        if before.st_nlink == 1:
            break
        if attempt == 50:
            raise ValueError(f"unsafe pressure checkpoint file: {path}")
        time.sleep(0.001)
    # O_NONBLOCK also protects against a path being swapped to a FIFO
    # between lstat and open. O_NOFOLLOW rejects a replaced symlink.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as handle:
        after = os.fstat(handle.fileno())
        if (not stat.S_ISREG(after.st_mode) or after.st_nlink != 1 or
                (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or
                after.st_size != len(expected) or
                handle.read(len(expected) + 1) != expected):
            raise ValueError(f"invalid pressure checkpoint contents: {path}")


def verify_marker(directory: Path, token: str, phase: str) -> None:
    """Controller-only: require an exact, regular, phase-scoped marker."""
    expected = _expected(token, phase)
    _read_exact_checkpoint(directory / phase, expected)


def publish_release(directory: Path, token: str, phase: str) -> None:
    """Controller: release only a published marker for the matching phase."""
    expected = _expected(token, phase)
    verify_marker(directory, token, phase)
    _publish_new(directory / f"release-{phase}", expected)


def wait_checkpoint(directory: Path, token: str, phase: str, *,
                    timeout_seconds: float = 90.0,
                    poll_seconds: float = 0.05) -> None:
    """Worker: publish readiness, retain memory, wait for exact release."""
    expected = _expected(token, phase)
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("checkpoint wait requires positive finite limits")
    _publish_new(directory / phase, expected)
    release = directory / f"release-{phase}"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            _read_exact_checkpoint(release, expected)
        except FileNotFoundError:
            pass
        else:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"pressure {phase} checkpoint release timed out")
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("release", "check"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("token")
    parser.add_argument("phase", choices=PHASES)
    args = parser.parse_args()
    try:
        if args.mode == "release":
            publish_release(args.directory, args.token, args.phase)
        else:
            verify_marker(args.directory, args.token, args.phase)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"pressure checkpoint release error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
