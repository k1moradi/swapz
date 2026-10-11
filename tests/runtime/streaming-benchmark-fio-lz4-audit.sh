#!/usr/bin/env bash
# Rootless regular-file diagnostic. Never opens a Device Mapper or block target.
set -euo pipefail
if (( $# != 0 )); then
  echo "usage: $0 (no arguments; generates both 50% and 75% cases)" >&2
  exit 2
fi
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if ! command -v fio >/dev/null || [[ ! "$(fio --version 2>/dev/null)" =~ ^fio-[0-9]+(\.[0-9]+)+$ ]]; then
  echo "ERROR: Flexible I/O Tester, not another command named fio, is required" >&2
  exit 2
fi
for bin in gcc python3 sha256sum stat; do
  command -v "$bin" >/dev/null || { echo "ERROR: missing $bin" >&2; exit 2; }
done
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/swapz-lz4-audit.XXXXXXXX")
printf 'ARTIFACT_DIR=%s (retained on success and failure)\n' "$WORKDIR"
"${CC:-gcc}" -std=c11 -O2 -Wall -Wextra -Werror \
  "$ROOT/tests/runtime/streaming-benchmark-fio-lz4-audit.c" -llz4 -o "$WORKDIR/raw-lz4-audit"
{
  fio --version
  "${CC:-gcc}" --version | head -n 1
  printf 'runner-reference: randwrite, randseed=1517953062, chunk=512, crc32c\n'
  printf 'note: regular file is NOT the 10-second, concurrent random-overwrite sample\n'
} > "$WORKDIR/toolchain.txt"
for pct in 50 75; do
  file="$WORKDIR/fio-$pct.bin"
  fio --name="swapz-audit-$pct" --filename="$file" --rw=randwrite \
    --bs=4k --size=40M --ioengine=sync --iodepth=1 --direct=0 \
    --randrepeat=1 --randseed=1517953062 --refill_buffers=1 \
    --buffer_compress_percentage="$pct" --buffer_compress_chunk=512 \
    --verify=crc32c --do_verify=0 --output-format=json \
    --output="$WORKDIR/fio-$pct.json"
  if [[ "$(stat -c %s -- "$file")" != 41943040 ]]; then
    echo "ERROR: fio regular-file capture was not exactly 40 MiB" >&2
    exit 3
  fi
  "$WORKDIR/raw-lz4-audit" "$file" > "$WORKDIR/raw-lengths-$pct.tsv"
  sha256sum -- "$file" >> "$WORKDIR/hashes.sha256"
done
python3 - "$WORKDIR" <<'PY'
import json
import pathlib
import statistics
import sys

root = pathlib.Path(sys.argv[1])
summary = {}
for pct in (50, 75):
    path = root / f"raw-lengths-{pct}.tsv"
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "page_index\tpayload_bytes\tkind":
        raise SystemExit(f"invalid raw LZ4 trace: {path}")
    records = [line.split("\t") for line in lines[1:]]
    if len(records) != 10240 or any(int(r[0]) != i for i, r in enumerate(records)):
        raise SystemExit(f"missing, duplicate or out-of-order pages: {path}")
    accepted = [int(length) for _, length, kind in records if kind == "compressed"]
    raw = sum(kind == "raw" for _, _, kind in records)
    if raw + len(accepted) != len(records) or any(x <= 0 or x > 3568 for x in accepted):
        raise SystemExit(f"invalid raw/compressed record lengths: {path}")
    sizes = sorted(accepted)
    summary[pct] = {
        "capture_pages": len(records), "raw_fallback_pages": raw,
        "compressed_pages": len(accepted), "pairing_threshold_equal_sizes_bytes": 2036,
        "pages_above_equal_pairing_threshold": sum(x > 2036 for x in accepted),
        "min_payload_bytes": sizes[0] if sizes else None,
        "median_payload_bytes": statistics.median(sizes) if sizes else None,
        "p95_payload_bytes": sizes[int((len(sizes)-1)*.95)] if sizes else None,
        "max_payload_bytes": sizes[-1] if sizes else None,
        "mean_payload_bytes": statistics.mean(sizes) if sizes else None,
        "limitation": "One regular-file pass; not identical to the timed concurrent kernel write stream",
    }
(root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
PY
printf 'Preserved raw length TSV, fio JSON, hashes and input captures under %s\n' "$WORKDIR"
