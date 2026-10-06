#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in cmp dd dmsetup losetup modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d)
LOOP=""
NAME=""

cleanup() {
  [[ -z "$NAME" ]] || dmsetup remove "$NAME" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

modprobe dm-swapz

run_case() {
  local case_name=$1
  local page_a=$2
  local page_b=$3
  local expected_counter=$4
  local backing="$TMP/backing-$case_name.img"
  local readback="$TMP/readback-$case_name"

  NAME="swapz-rotation-$case_name"
  truncate -s 8M "$backing"
  LOOP=$(losetup --find --show "$backing")

  # One logical 4 KiB page backed by 8 MiB gives four 2 MiB arenas.
  # With one container emitted per synchronous write, the 513th overwrite
  # forces the first rotation: 512 writes fill arena 0, compaction copies
  # the current live page into arena 1, then the triggering foreground write
  # must remain intact.
  dmsetup create "$NAME" --table "0 8 swapz $LOOP"

  for ((write_number = 1; write_number <= 513; ++write_number)); do
    if ((write_number % 2)); then
      SOURCE="$page_a"
    else
      SOURCE="$page_b"
    fi

    dd if="$SOURCE" of="/dev/mapper/$NAME" bs=4096 count=1 \
       oflag=direct conv=notrunc status=none
  done

  dd if="/dev/mapper/$NAME" of="$readback" bs=4096 count=1 \
     iflag=direct status=none
  cmp "$page_a" "$readback"

  STATUS=$(dmsetup status "$NAME")
  echo "$case_name status: $STATUS"

  grep -Eq 'rotations=[1-9][0-9]*' <<<"$STATUS" || {
    echo "$case_name case did not trigger arena rotation" >&2
    exit 1
  }

  grep -Eq "$expected_counter=[1-9][0-9]*" <<<"$STATUS" || {
    echo "$case_name case did not exercise $expected_counter" >&2
    exit 1
  }

  grep -q 'failed=0' <<<"$STATUS" || {
    echo "$case_name case entered failed state" >&2
    exit 1
  }

  dmsetup remove "$NAME"
  NAME=""
  losetup -d "$LOOP"
  LOOP=""
}

# Incompressible pages exercise raw fallback while rotation compaction reuses
# its own input/compression scratch.
dd if=/dev/urandom of="$TMP/raw-a" bs=4096 count=1 status=none
dd if=/dev/urandom of="$TMP/raw-b" bs=4096 count=1 status=none
run_case raw "$TMP/raw-a" "$TMP/raw-b" raw_pages

# Highly compressible but different pages verify that the foreground
# compressed result also survives compaction's use of its separate scratch.
dd if=/dev/zero of="$TMP/compressed-a" bs=4096 count=1 status=none
tr '\000' '\377' < /dev/zero | dd of="$TMP/compressed-b" bs=4096 count=1 status=none
run_case compressed "$TMP/compressed-a" "$TMP/compressed-b" compressed_pages

echo "arena rotation foreground-write regressions: PASS"
