#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in cmp dd dmsetup modprobe python3; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d /dev/shm/swapz-v22-staged-fault.XXXXXX)
TAG="$$-$RANDOM"
LOWER="swapz-v22-stage-error-$TAG"
TARGET="swapz-v22-stage-fault-$TAG"

cleanup() {
  dmsetup remove "$TARGET" >/dev/null 2>&1 || true
  dmsetup remove "$LOWER" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

modprobe dm-error
modprobe dm-swapz

# Entire lower target rejects I/O. The staged compressed upper write must still
# complete from RAM before the asynchronous lower failure is observed.
dmsetup create "$LOWER" --table "0 32768 error"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER staged 128"

python3 - "$TMP/page.bin" <<'PY'
from pathlib import Path
# Deliberately highly compressible but not all-zero.
Path(__import__("sys").argv[1]).write_bytes((b"swapz-v22-stage" * 257)[:4096].ljust(4096, b"Z"))
PY

# A successful dd proves the upper BIO completed even though the eventual lower
# stream write is guaranteed to fail.
dd if="$TMP/page.bin" of="/dev/mapper/$TARGET" bs=4096 count=1    oflag=direct conv=notrunc status=none

deadline=$((SECONDS + 10))
while (( SECONDS < deadline )); do
  STATUS=$(dmsetup status "$TARGET")
  if grep -q 'failed=1' <<<"$STATUS"; then
    break
  fi
  sleep 0.01
done
STATUS=$(dmsetup status "$TARGET")
echo "status after injected failure: $STATUS"
grep -q 'failed=1' <<<"$STATUS" || {
  echo "lower asynchronous failure was not observed" >&2
  exit 1
}
grep -Eq 'staged_early=[1-9][0-9]*' <<<"$STATUS" || {
  echo "write was not early-completed from staged RAM" >&2
  exit 1
}

# Reads are still permitted in staged mode after write failure so authoritative
# early-completed data can be recovered by swap-in/swapoff.
dd if="/dev/mapper/$TARGET" of="$TMP/readback.bin" bs=4096 count=1    iflag=direct status=none
cmp "$TMP/page.bin" "$TMP/readback.bin"

STATUS2=$(dmsetup status "$TARGET")
echo "status after staged readback: $STATUS2"
grep -Eq 'staged_hits=[1-9][0-9]*' <<<"$STATUS2" || {
  echo "failed-batch page was not served from retained staged RAM" >&2
  exit 1
}

# New writes must not be accepted once backing persistence has failed.
if dd if="$TMP/page.bin" of="/dev/mapper/$TARGET" bs=4096 seek=1 count=1       oflag=direct conv=notrunc status=none 2>"$TMP/new-write.err"; then
  echo "new write unexpectedly succeeded after target failure" >&2
  exit 1
fi

echo "V2.2 staged early-completion lower-failure recovery: PASS"
