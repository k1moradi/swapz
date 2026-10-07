#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in cmp dd dmsetup fio g++ losetup modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TMP=$(mktemp -d /dev/shm/swapz-v21-correctness.XXXXXX)
TAG="$$-$RANDOM"
REF="$TMP/reference"
LONG_STRATEGY=${SWAPZ_LONG_STRATEGY:-opportunistic}
LONG_BATCH_KIB=${SWAPZ_LONG_BATCH_KIB:-256}
case "$LONG_STRATEGY" in
  opportunistic|staged) ;;
  *) echo "SWAPZ_LONG_STRATEGY must be opportunistic or staged" >&2; exit 1 ;;
esac
LOOPS=()
NAMES=()
cleanup() {
  local i
  for ((i=${#NAMES[@]}-1; i>=0; --i)); do dmsetup remove "${NAMES[i]}" >/dev/null 2>&1 || true; done
  for ((i=${#LOOPS[@]}-1; i>=0; --i)); do losetup -d "${LOOPS[i]}" >/dev/null 2>&1 || true; done
  rm -rf "$TMP"
}
trap cleanup EXIT
g++ -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror \
  "$ROOT/tests/runtime/reference.cpp" -o "$REF"
modprobe dm-swapz
run_target() {
  local name=$1 backing_mib=$2 sectors=$3 mode=$4
  shift 4
  local image="$TMP/$name.img" loop status strategy="opportunistic"
  [[ $mode != random && $mode != live ]] || strategy="$LONG_STRATEGY"
  truncate -s "${backing_mib}M" "$image"
  loop=$(losetup --find --show "$image")
  LOOPS+=("$loop")
  dmsetup create "$name" --table "0 $sectors swapz $loop $strategy $LONG_BATCH_KIB"
  NAMES+=("$name")
  "$REF" "$mode" "/dev/mapper/$name" "$@"
  status=$(dmsetup status "$name")
  echo "$name status: $status"
  grep -q 'failed=0' <<<"$status"
  [[ $mode != random ]] || grep -Eq 'gc_victims=[1-9][0-9]*' <<<"$status"
  [[ $mode != live ]] || grep -Eq 'gc_pages=[1-9][0-9]*' <<<"$status"
  [[ $mode != selectivity ]] || grep -Eq 'gc_pages=[1-9][0-9]*' <<<"$status"
  if [[ $mode == group ]]; then
    local want=$1 got
    got=$(sed -n 's/.*gc_pages=\([0-9][0-9]*\).*/\1/p' <<<"$status")
    [[ "$got" == "$want" ]]
  fi
  dmsetup remove "$name"
  NAMES=() # this harness runs one target at a time
  losetup -d "$loop"
  LOOPS=()
}
for seed in 0x5a7a2026 0x00000001 0x12345678 0xdeadbeef 0x7fffffff; do
  run_target "swapz-v21-seed-$TAG-${seed#0x}" 16 4096 random "$seed" 100000
done
run_target "swapz-v21-live-gc-$TAG" 3 2048 live 30000
run_target "swapz-v21-selectivity-$TAG" 40 65536 selectivity
run_packed_gc() {
  local live=$1 name="swapz-v21-group-$TAG-$1" image="$TMP/group-$1.img" loop
  truncate -s 4M "$image"
  loop=$(losetup --find --show "$image")
  LOOPS+=("$loop")
  dmsetup create "$name" --table "0 4096 swapz $loop opportunistic $LONG_BATCH_KIB"
  NAMES+=("$name")
  fio --name="pack-$live" --filename="/dev/mapper/$name" --size=32K --io_size=32K \
    --bs=4k --rw=write --ioengine=libaio --iodepth=8 --iodepth_batch_submit=8 \
    --iodepth_batch_complete_min=8 --iodepth_low=8 --direct=1 --numjobs=1 \
    --refill_buffers=1 --randseed=1517953062 --buffer_compress_percentage=100 \
    --buffer_compress_chunk=512 --group_reporting=1 --output-format=normal >/dev/null
  local before status got
  before=$(dmsetup status "$name")
  grep -q 'physical_write=4096' <<<"$before"
  grep -q 'compressed_pages=8' <<<"$before"
  grep -q 'raw_pages=0' <<<"$before"
  dd if="/dev/mapper/$name" of="$TMP/group-$live.before" bs=4096 count=8 status=none
  "$REF" group "/dev/mapper/$name" "$live"
  status=$(dmsetup status "$name")
  echo "$name status: $status"
  got=$(sed -n 's/.*gc_pages=\([0-9][0-9]*\).*/\1/p' <<<"$status")
  [[ "$got" == "$live" ]]
  grep -q 'gc_victims=1' <<<"$status"
  grep -q 'failed=0' <<<"$status"
  if (( live > 0 )); then
    grep -q 'gc_read=4096' <<<"$status"
    grep -q 'gc_write=4096' <<<"$status"
  else
    grep -q 'gc_read=0' <<<"$status"
    grep -q 'gc_write=0' <<<"$status"
  fi
  dd if="/dev/mapper/$name" of="$TMP/group-$live.after" bs=4096 count=8 status=none
  cmp "$TMP/group-$live.before" "$TMP/group-$live.after"
  dmsetup remove "$name"
  NAMES=()
  losetup -d "$loop"
  LOOPS=()
}
for live in 8 4 1 0; do run_packed_gc "$live"; done
echo 'V2.1 runtime correctness suite: PASS'
