#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in awk blockdev dmsetup fio git insmod losetup make modprobe rmmod tar truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
V2_REF=1e3a0c71b4e514bccae58d79be9f319640478b5c
if [[ -n "${SWAPZ_V21_REF:-}" ]]; then
  V21_REF=$SWAPZ_V21_REF
elif git -C "$ROOT" rev-parse --verify origin/main >/dev/null 2>&1; then
  V21_REF=$(git -C "$ROOT" rev-parse origin/main)
else
  V21_REF=$(git -C "$ROOT" rev-parse HEAD)
fi
KDIR="/lib/modules/$(uname -r)/build"
TMP=$(mktemp -d /dev/shm/swapz-v21-ab.XXXXXX)
TAG="$$-$RANDOM"
BENCH_IMG="$TMP/bench.img"; LATENCY_IMG="$TMP/latency.img"
BENCH_LOOP=""; LATENCY_LOOP=""
DELAY_NAME="swapz-v21-ab-delay-$TAG"; LATENCY_DELAY="swapz-v21-latency-delay-$TAG"
TARGET_NAME="swapz-v21-ab-target-$TAG"; LATENCY_TARGET="swapz-v21-latency-target-$TAG"
WAS_LOADED=0
lsmod | awk '$1=="dm_swapz" {found=1} END {exit !found}' && WAS_LOADED=1 || true
remove_mapper(){
  local name=$1
  for _ in $(seq 1 50); do
    dmsetup remove "$name" >/dev/null 2>&1 && return 0
    sleep 0.1
  done
  echo "could not remove mapper $name" >&2
  dmsetup info "$name" >&2 || true
  return 1
}
cleanup(){
  dmsetup remove "$LATENCY_TARGET" >/dev/null 2>&1 || true
  dmsetup remove "$TARGET_NAME" >/dev/null 2>&1 || true
  dmsetup remove "$LATENCY_DELAY" >/dev/null 2>&1 || true
  dmsetup remove "$DELAY_NAME" >/dev/null 2>&1 || true
  [[ -z "$LATENCY_LOOP" ]] || losetup -d "$LATENCY_LOOP" >/dev/null 2>&1 || true
  [[ -z "$BENCH_LOOP" ]] || losetup -d "$BENCH_LOOP" >/dev/null 2>&1 || true
  rmmod dm_swapz >/dev/null 2>&1 || true
  if (( WAS_LOADED )); then modprobe dm-swapz >/dev/null 2>&1 || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT
mkdir -p "$TMP/v2" "$TMP/v21"
git -C "$ROOT" archive "$V2_REF" | tar -x -C "$TMP/v2"
git -C "$ROOT" archive "$V21_REF" | tar -x -C "$TMP/v21"
make -C "$TMP/v2/kernel" KDIR="$KDIR" W=1
make -C "$TMP/v21/kernel" KDIR="$KDIR" W=1
V2_MODULE="$TMP/v2/kernel/dm-swapz.ko"
V21_MODULE="$TMP/v21/kernel/dm-swapz.ko"
printf 'V2_REF=%s\nV2.1_REF=%s\n' "$V2_REF" "$V21_REF"
printf 'KERNEL=%s\n' "$(uname -r)"
printf 'STACK=16MiB and 3MiB /dev/shm loop backing through dm-delay 1ms read and write\n'
truncate -s 16M "$BENCH_IMG"
BENCH_LOOP=$(losetup --find --show "$BENCH_IMG")
truncate -s 3M "$LATENCY_IMG"
LATENCY_LOOP=$(losetup --find --show "$LATENCY_IMG")
modprobe dm-delay
modprobe lz4_compress
dmsetup create "$DELAY_NAME" --table "0 32768 delay $BENCH_LOOP 0 1 $BENCH_LOOP 0 1"
dmsetup create "$LATENCY_DELAY" --table "0 6144 delay $LATENCY_LOOP 0 1 $LATENCY_LOOP 0 1"
DELAY_KNAME=$(basename "$(readlink -f "/dev/mapper/$DELAY_NAME")")
LOOP_KNAME=$(basename "$BENCH_LOOP")
LOOP_STAT="/sys/class/block/$LOOP_KNAME/stat"
DELAY_STAT="/sys/class/block/$DELAY_KNAME/stat"

read_stats(){
  awk '{print $1, $3, $5, $7}' "$LOOP_STAT"
  awk '{print $1, $3, $5, $7}' "$DELAY_STAT"
}
install_module(){
  local module=$1
  rmmod dm_swapz >/dev/null 2>&1 || true
  insmod "$module"
  grep -q '^dm_swapz ' /proc/modules
}
run_fio(){
  local version=$1 path_kind=$2 compress=$3 qd=$4 path=$5 size=$6 label=$7
  local json="$TMP/$version-$path_kind-$compress-qd$qd.json"
  local before after status
  blockdev --flushbufs "$path" >/dev/null 2>&1 || true
  before=$(read_stats)
  fio --name="$label" --filename="$path" --size="$size" --io_size=64M \
    --bs=4k --rw=randwrite --ioengine=libaio --iodepth="$qd" \
    --iodepth_batch_submit="$qd" --iodepth_batch_complete_min="$qd" \
    --iodepth_low="$qd" --numjobs=1 --direct=1 --refill_buffers=1 \
    --randseed=1517953062 --randrepeat=1 \
    --buffer_compress_percentage="$compress" --buffer_compress_chunk=512 \
    --percentile_list=50:90:95:99:99.9:99.99 --output-format=json --output="$json"
  blockdev --flushbufs "$path" >/dev/null 2>&1 || true
  after=$(read_stats)
  status=none
  if [[ "$path_kind" == swapz ]]; then
    status=$(dmsetup status "$TARGET_NAME")
    grep -q 'failed=0' <<<"$status"
  fi
  python3 - "$json" "$before" "$after" "$version" "$path_kind" "$compress" "$qd" "$status" "$LOOP_KNAME" "$DELAY_KNAME" <<'PY'
import json, os, sys
path, before, after, version, kind, compress, qd, status, loop_kname, delay_kname = sys.argv[1:]
with open(path, encoding="utf-8") as src:
    root = json.load(src)
job = root["jobs"][0]
write = job["write"]
clat = write.get("clat_ns", {})
percentile = clat.get("percentile", {})
def pctl(key):
    return float(percentile.get(key, 0)) / 1_000_000
b = [int(x) for x in before.split()]
a = [int(x) for x in after.split()]
status_map = {}
if status != "none":
    for token in status.split():
        if "=" in token:
            key, value = token.split("=", 1)
            status_map[key] = value
physical_bytes = int(status_map.get("physical_write", 0))
physical_reqs = int(status_map.get("physical_write_reqs", 0))
result = {
    "version": version, "path": kind, "compress_pct": int(compress), "qd": int(qd),
    "logical_bytes": int(write.get("io_bytes", 0)),
    "throughput_mib_s": round(float(write.get("bw_bytes", 0)) / (1024 * 1024), 3),
    "clat_mean_ms": round(float(clat.get("mean", 0)) / 1_000_000, 3),
    "p95_ms": round(pctl("95.000000"), 3), "p99_ms": round(pctl("99.000000"), 3),
    "max_ms": round(float(clat.get("max", 0)) / 1_000_000, 3),
    "usr_cpu_pct": round(float(job.get("usr_cpu", 0)), 3),
    "sys_cpu_pct": round(float(job.get("sys_cpu", 0)), 3),
    "loop_read_ios": a[0] - b[0], "loop_read_sectors": a[1] - b[1],
    "loop_write_ios": a[2] - b[2], "loop_write_sectors": a[3] - b[3],
    "delay_read_ios": a[4] - b[4], "delay_read_sectors": a[5] - b[5],
    "delay_write_ios": a[6] - b[6], "delay_write_sectors": a[7] - b[7],
    "swapz_physical_write_reqs": physical_reqs,
    "physical_blocks_per_swapz_request": round(physical_bytes / 4096 / physical_reqs, 3) if physical_reqs else None,
    "lower_sectors_per_logical_sector": round((a[3] - b[3]) / (int(write.get("io_bytes", 0)) / 512), 4) if write.get("io_bytes") else None,
    "status": status,
}
print("RESULT " + json.dumps(result, sort_keys=True))
PY
}
run_latency(){
  local version=$1 module=$2 status
  install_module "$module"
  dmsetup create "$LATENCY_TARGET" --table "0 2048 swapz /dev/mapper/$LATENCY_DELAY"
  fio --name="latency-pack-$version" --filename="/dev/mapper/$LATENCY_TARGET" \
    --size=32K --io_size=32K --bs=4k --rw=write --ioengine=libaio --iodepth=8 \
    --iodepth_batch_submit=8 --iodepth_batch_complete_min=8 --iodepth_low=8 \
    --direct=1 --numjobs=1 --refill_buffers=1 --randseed=1517953062 \
    --buffer_compress_percentage=100 --buffer_compress_chunk=512 --output-format=json \
    --output="$TMP/latency-pack-$version.json"
  status=$(dmsetup status "$LATENCY_TARGET")
  echo "LATENCY_SETUP version=$version status=$status"
  grep -q 'compressed_pages=8' <<<"$status"
  python3 "$ROOT/tests/runtime/live-gc-latency.py" \
    --device "/dev/mapper/$LATENCY_TARGET" --target-name "$LATENCY_TARGET" \
    --operations 8192
  remove_mapper "$LATENCY_TARGET"
}
for version in V2 V2.1; do
  if [[ "$version" == V2 ]]; then module=$V2_MODULE; else module=$V21_MODULE; fi
  install_module "$module"
  for qd in 1 8; do
    for spec in compressible:100 partial:50 incompressible:0; do
      workload=${spec%%:*}; compress=${spec##*:}
      run_fio "$version" raw "$compress" "$qd" "/dev/mapper/$DELAY_NAME" 16M "$workload-raw-$version"
      dmsetup create "$TARGET_NAME" --table "0 4096 swapz /dev/mapper/$DELAY_NAME"
      run_fio "$version" swapz "$compress" "$qd" "/dev/mapper/$TARGET_NAME" 2M "$workload-swapz-$version"
      remove_mapper "$TARGET_NAME"
    done
  done
  run_latency "$version" "$module"
  rmmod dm_swapz
done
printf 'A/B benchmark and delayed live-GC latency: PASS\n'
