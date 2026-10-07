#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in cmp dd dmsetup losetup modprobe python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d /dev/shm/swapz-v22-replacement-fault.XXXXXX)
TAG="$$-$RANDOM"
IMG="$TMP/backing.img"
LOWER="swapz-v22-repl-lower-$TAG"
TARGET="swapz-v22-repl-$TAG"
LOOP=""

cleanup() {
  dmsetup remove "$TARGET" >/dev/null 2>&1 || true
  dmsetup remove "$LOWER" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

truncate -s 16M "$IMG"
LOOP=$(losetup --find --show "$IMG")
SECTORS=$(blockdev --getsz "$LOOP")

modprobe dm-error
modprobe dm-swapz

dmsetup create "$LOWER" --table "0 $SECTORS linear $LOOP 0"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER staged 128"

python3 - "$TMP/old.bin" "$TMP/new.bin" <<'PY'
from pathlib import Path
import os, sys
# Old data compresses and is flushed to a persistent mapping.
Path(sys.argv[1]).write_bytes((b"swapz-old-authoritative-" * 200)[:4096].ljust(4096, b"O"))
# Replacement is intentionally incompressible so staged mode must not early-complete it.
Path(sys.argv[2]).write_bytes(os.urandom(4096))
PY

dd if="$TMP/old.bin" of="/dev/mapper/$TARGET" bs=4096 count=1    oflag=direct conv=notrunc status=none
# Force the staged old record to persistent lower storage.
blockdev --flushbufs "/dev/mapper/$TARGET"

dd if="/dev/mapper/$TARGET" of="$TMP/old-read.bin" bs=4096 count=1    iflag=direct status=none
cmp "$TMP/old.bin" "$TMP/old-read.bin"

# Turn the already-open lower mapped device into a deterministic write/read failure.
dmsetup suspend "$LOWER"
dmsetup load "$LOWER" --table "0 $SECTORS error"
dmsetup resume "$LOWER"

# The raw replacement must fail rather than early-complete.
set +e
timeout --signal=TERM --kill-after=5s 30s   dd if="$TMP/new.bin" of="/dev/mapper/$TARGET" bs=4096 count=1      oflag=direct conv=notrunc status=none 2>"$TMP/replacement.err"
RC=$?
set -e
if (( RC == 0 )); then
  echo "raw replacement unexpectedly succeeded over failing lower device" >&2
  exit 1
fi
if (( RC == 124 || RC == 137 )); then
  echo "raw replacement hung instead of failing" >&2
  dmsetup status "$TARGET" >&2 || true
  exit 1
fi

STATUS=$(dmsetup status "$TARGET")
echo "status after replacement failure: $STATUS"
grep -q 'failed=1' <<<"$STATUS" || {
  echo "target did not enter failed state after lower replacement failure" >&2
  exit 1
}

# Restore the lower path without touching swapz.  A staged-mode READ is allowed after
# target failure specifically so swapoff/recovery can retrieve the last good data.
dmsetup suspend "$LOWER"
dmsetup load "$LOWER" --table "0 $SECTORS linear $LOOP 0"
dmsetup resume "$LOWER"

dd if="/dev/mapper/$TARGET" of="$TMP/recovered.bin" bs=4096 count=1    iflag=direct status=none
cmp "$TMP/old.bin" "$TMP/recovered.bin"

STATUS2=$(dmsetup status "$TARGET")
echo "status after old-mapping recovery: $STATUS2"
echo "V2.2 failed raw replacement preserves previous authoritative mapping: PASS"
