#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in dmsetup fio losetup modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d)
LOOP=""
NAME=swapz-write-batch-regression

cleanup() {
  dmsetup remove "$NAME" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

truncate -s 16M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
modprobe dm-swapz

# 2 MiB logical target on 16 MiB physical backing.
dmsetup create "$NAME" --table "0 4096 swapz $LOOP"

fio --name=batch-regression \
    --filename="/dev/mapper/$NAME" \
    --size=1M --io_size=1M --bs=4k --rw=write \
    --ioengine=libaio --iodepth=8 --direct=1 --numjobs=1 \
    --refill_buffers=1 --buffer_compress_percentage=0 \
    --verify=crc32c --do_verify=1 --verify_fatal=1 \
    --group_reporting=1

STATUS=$(dmsetup status "$NAME")
echo "status: $STATUS"

get_counter() {
  local key=$1
  sed -n "s/.*\\b${key}=\\([0-9][0-9]*\\)\\b.*/\\1/p" <<<"$STATUS"
}

RAW=$(get_counter raw_pages)
REQS=$(get_counter physical_write_reqs)
MULTI=$(get_counter multi_write_reqs)
MAXB=$(get_counter max_write_batch)

[[ "$RAW" =~ ^[0-9]+$ && "$REQS" =~ ^[0-9]+$ &&
   "$MULTI" =~ ^[0-9]+$ && "$MAXB" =~ ^[0-9]+$ ]] || {
  echo "missing V2.1 write-batch counters" >&2
  exit 1
}

(( RAW > 0 )) || { echo "raw fallback was not exercised" >&2; exit 1; }
(( MULTI > 0 )) || { echo "no multi-block lower write was observed" >&2; exit 1; }
(( MAXB > 1 )) || { echo "max write batch never exceeded one block" >&2; exit 1; }
(( REQS < RAW )) || {
  echo "physical request count was not reduced below raw-page count" >&2
  exit 1
}

grep -q "failed=0" <<<"$STATUS" || {
  echo "swapz target entered failed state" >&2
  exit 1
}

echo "V2.1 serialized physical-write batching regression: PASS"
