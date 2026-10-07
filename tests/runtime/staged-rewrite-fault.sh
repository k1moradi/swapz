#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in cmp dd dmsetup losetup modprobe python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d /dev/shm/swapz-v22-rewrite-fault.XXXXXX)
TAG="$$-$RANDOM"
LOWER="swapz-v22-rewrite-lower-$TAG"
TARGET="swapz-v22-rewrite-$TAG"
LOOP=""

cleanup() {
  dmsetup remove "$TARGET" >/dev/null 2>&1 || true
  dmsetup remove "$LOWER" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

modprobe dm-delay
modprobe dm-error
modprobe dm-swapz

truncate -s 16M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")

cat >"$TMP/lower.table" <<EOF
0 8 delay $LOOP 0 1000
8 32760 error
EOF

dmsetup create "$LOWER" "$TMP/lower.table"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER staged 128"

python3 - "$TMP/old.bin" "$TMP/new.bin" <<'PY'
from pathlib import Path
import sys
Path(sys.argv[1]).write_bytes((b"OLD-STAGED-GENERATION-" * 220)[:4096].ljust(4096, b"O"))
Path(sys.argv[2]).write_bytes((b"NEW-FAILED-GENERATION-" * 220)[:4096].ljust(4096, b"N"))
PY

start_ns=$(date +%s%N)
dd if="$TMP/old.bin" of="/dev/mapper/$TARGET" bs=4096 count=1    oflag=direct conv=notrunc status=none
first_ms=$(( ($(date +%s%N) - start_ns) / 1000000 ))

if (( first_ms >= 800 )); then
  echo "first staged write did not early-complete: ${first_ms}ms" >&2
  exit 1
fi

status=$(dmsetup status "$TARGET")
echo "after first staged write (${first_ms}ms): $status"
grep -Eq 'staged_early=[1-9][0-9]*' <<<"$status"

start_ns=$(date +%s%N)
set +e
dd if="$TMP/new.bin" of="/dev/mapper/$TARGET" bs=4096 count=1    oflag=direct conv=notrunc status=none 2>"$TMP/rewrite.err"
rc=$?
set -e
rewrite_ms=$(( ($(date +%s%N) - start_ns) / 1000000 ))

if (( rc == 0 )); then
  echo "same-slot replacement unexpectedly succeeded" >&2
  exit 1
fi
if (( rewrite_ms < 700 )); then
  echo "replacement failed before prior staged generation was drained: ${rewrite_ms}ms" >&2
  exit 1
fi

status=$(dmsetup status "$TARGET")
echo "after failed replacement (${rewrite_ms}ms): $status"
grep -q 'failed=1' <<<"$status"
grep -q 'physical_write=4096' <<<"$status"

dd if="/dev/mapper/$TARGET" of="$TMP/readback.bin" bs=4096 count=1    iflag=direct status=none
cmp "$TMP/old.bin" "$TMP/readback.bin"

if cmp -s "$TMP/new.bin" "$TMP/readback.bin"; then
  echo "failed replacement became authoritative" >&2
  exit 1
fi

echo "V2.2 same-slot staged replacement atomicity: PASS"
