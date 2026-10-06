#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in cmp dd dmsetup losetup modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d)
LOOP=""
NAME=swapz-rotation-regression

cleanup() {
  dmsetup remove "$NAME" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

# One logical 4 KiB page backed by 8 MiB gives four 2 MiB arenas.
# With incompressible data, the 513th overwrite forces the first rotation:
# 512 physical raw writes fill arena 0, compaction copies the current live
# page into arena 1, then the triggering foreground write must remain intact.
truncate -s 8M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
modprobe dm-swapz

SECTORS=8
dmsetup create "$NAME" --table "0 $SECTORS swapz $LOOP"

dd if=/dev/urandom of="$TMP/page-a" bs=4096 count=1 status=none
dd if=/dev/urandom of="$TMP/page-b" bs=4096 count=1 status=none

for ((write_number = 1; write_number <= 513; ++write_number)); do
  if ((write_number % 2)); then
    SOURCE="$TMP/page-a"
  else
    SOURCE="$TMP/page-b"
  fi

  dd if="$SOURCE" of="/dev/mapper/$NAME" bs=4096 count=1 \
     oflag=direct conv=notrunc status=none
done

dd if="/dev/mapper/$NAME" of="$TMP/readback" bs=4096 count=1 \
   iflag=direct status=none

cmp "$TMP/page-a" "$TMP/readback"

STATUS=$(dmsetup status "$NAME")
echo "status: $STATUS"

grep -Eq 'rotations=[1-9][0-9]*' <<<"$STATUS" || {
  echo "rotation regression did not trigger arena rotation" >&2
  exit 1
}

grep -Eq 'raw_pages=[1-9][0-9]*' <<<"$STATUS" || {
  echo "rotation regression did not exercise raw fallback" >&2
  exit 1
}

grep -q 'failed=0' <<<"$STATUS" || {
  echo "swapz target entered failed state" >&2
  exit 1
}

echo "arena rotation foreground-write regression: PASS"
