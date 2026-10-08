#!/usr/bin/env python3
"""Strict, rootless-testable /proc/swaps accounting for the pressure fixture.

The controller must not infer swap usage from AWK's numeric coercion or
from an inventory in which its named device is missing or duplicated.
The real fixture always reads /proc/swaps; --fixture is for isolated tests.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


HEADER = ("Filename", "Type", "Size", "Used", "Priority")


def _decimal(field: str, *, signed: bool = False) -> int:
    value = field[1:] if signed and field.startswith("-") else field
    # Require bounded ASCII decimal, not Python's permissive Unicode digits
    # or arbitrary-length strings.
    if not 1 <= len(value) <= 19 or not value.isascii() or not value.isdecimal():
        raise ValueError("malformed /proc/swaps numeric field")
    return int(field, 10)


def read_test_swap_used(inventory: str, target: str) -> int:
    """Return test-device Used KiB iff every inventory row is well formed."""
    if not target.startswith("/") or not os.path.isabs(target):
        raise ValueError("target swap path must be absolute")
    rows = inventory.splitlines()
    if not rows or tuple(rows[0].split()) != HEADER:
        raise ValueError("malformed /proc/swaps header")
    if not inventory.endswith("\n"):
        raise ValueError("truncated /proc/swaps inventory")
    canonical_target = os.path.realpath(target)
    matched: list[int] = []
    for row in rows[1:]:
        fields = row.split()
        if len(fields) != 5:
            raise ValueError("malformed /proc/swaps row")
        path, kind, size_text, used_text, priority_text = fields
        if not path.startswith("/") or kind not in ("file", "partition"):
            raise ValueError("invalid /proc/swaps path or type")
        size = _decimal(size_text)
        used = _decimal(used_text)
        _decimal(priority_text, signed=True)
        if size == 0 or used > size:
            raise ValueError("impossible /proc/swaps size/used accounting")
        if os.path.realpath(path) == canonical_target:
            matched.append(used)
    if len(matched) != 1:
        raise ValueError("test swap entry missing or duplicated in /proc/swaps")
    return matched[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", help="canonical path of test swap device")
    parser.add_argument("--fixture", type=Path, default=Path("/proc/swaps"),
                        help="override inventory for rootless tests only")
    args = parser.parse_args()
    try:
        inventory = args.fixture.read_text(encoding="utf-8")
        used = read_test_swap_used(inventory, args.device)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: cannot verify test swap accounting: {exc}", file=sys.stderr)
        return 1
    print(used)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
