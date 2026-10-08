#!/usr/bin/env bash
# Prevent silent reintroduction of unsafe lower DISCARD on bandwidth-limited
# null_blk. Source-only check; no root or block device needed.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
python3 - "$ROOT/tests/runtime/streaming-benchmark.sh" <<'PY'
from pathlib import Path
import sys

s = Path(sys.argv[1]).read_text()
checks = {
    "lower discard disabled by default": 'BENCH_DISCARD=${SWAPZ_BENCH_DISCARD:-0}',
    "explicit rejection on throttled backend": 'BANDWIDTH > 0 && BENCH_DISCARD == 1',
    "runtime null_blk discard configuration": 'echo "$BENCH_DISCARD" >"$NULL_CFG/discard"',
    "target lower-discard verification": "grep -q 'lower_discard=off'",
    "oversized write batch rejection": "batch * 1024 > NULLBLK_TICK_BYTES",
}
for label, needle in checks.items():
    if needle not in s:
        raise SystemExit(f"null_blk DISCARD safety invariant failure: {label}")
if not (s.index(checks["explicit rejection on throttled backend"])
        < s.index("setup_nullblk()")):
    raise SystemExit("null_blk DISCARD safety invariant failure: rejection must precede setup")
if 'echo 1 >"$NULL_CFG/discard"' in s:
    raise SystemExit("null_blk DISCARD safety invariant failure: unconditional discard enable")
print("V2.2 null_blk lower-DISCARD safety invariants: PASS")
PY
