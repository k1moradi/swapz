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


def publish_release(directory: Path, token: str, phase: str) -> None:
    """Controller: release only a published marker for the matching phase."""
    expected = _expected(token, phase)
    marker = directory / phase
    if marker.read_bytes() != expected:
        raise ValueError(f"invalid {phase} checkpoint marker")
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
            value = release.read_bytes()
        except FileNotFoundError:
            pass
        else:
            if value == expected:
                return
            raise ValueError(f"invalid {phase} checkpoint release token")
        if time.monotonic() >= deadline:
            raise TimeoutError(f"pressure {phase} checkpoint release timed out")
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("release",))
    parser.add_argument("directory", type=Path)
    parser.add_argument("token")
    parser.add_argument("phase", choices=PHASES)
    args = parser.parse_args()
    try:
        publish_release(args.directory, args.token, args.phase)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"pressure checkpoint release error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
