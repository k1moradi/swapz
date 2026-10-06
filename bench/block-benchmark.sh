#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage:
  sudo ./bench/block-benchmark.sh \
      --backing /dev/DEVICE --size 1G --destroy \
      [--runtime 30] [--iodepth 1]

DESTRUCTIVE: overwrites the selected backing device.
Use only an explicitly disposable dedicated partition/device.

The backing device must hold the requested logical size plus the V2 reserve:
max(25% of logical size, 2 MiB).

The script runs paired raw-device and swapz workloads for:
  compressible (100%)
  partially compressible (50%)
  incompressible (0%)

It reports actual lower-device sectors written for every run.
USAGE
  exit 2
}

BACKING=""
SIZE=""
RUNTIME=30
IODEPTH=1
DESTROY=0
NAME=swapzbench

while (($#)); do
  case "$1" in
    --backing) BACKING=$2; shift 2;;
    --size) SIZE=$2; shift 2;;
    --runtime) RUNTIME=$2; shift 2;;
    --iodepth) IODEPTH=$2; shift 2;;
    --destroy) DESTROY=1; shift;;
    *) usage;;
  esac
done

[[ -n "$BACKING" && -n "$SIZE" && $DESTROY -eq 1 ]] || usage
[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }

for tool in awk blockdev dmsetup fio lsblk modprobe numfmt; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

[[ -b "$BACKING" ]] || { echo "$BACKING is not a block device" >&2; exit 1; }

if grep -qE "^\${BACKING//\//\\/}[[:space:]]" /proc/swaps; then
  echo "$BACKING is active swap" >&2
  exit 1
fi

if lsblk -nrpo MOUNTPOINTS "$BACKING" | grep -q '[^[:space:]]'; then
  echo "$BACKING or a descendant is mounted" >&2
  exit 1
fi

SIZE_BYTES=$(numfmt --from=iec "$SIZE")
SIZE_BYTES=$((SIZE_BYTES / 4096 * 4096))
((SIZE_BYTES > 0)) || { echo "invalid logical size" >&2; exit 1; }

BACKING_BYTES=$(blockdev --getsize64 "$BACKING")
RATIO_RESERVE=$(((SIZE_BYTES + 3) / 4))
MIN_RESERVE=$((2 * 1024 * 1024))
if ((RATIO_RESERVE > MIN_RESERVE)); then
  MIN_RESERVE=$RATIO_RESERVE
fi
if ((SIZE_BYTES > BACKING_BYTES || MIN_RESERVE > BACKING_BYTES - SIZE_BYTES)); then
  echo "backing device does not satisfy V2 logical size + GC reserve" >&2
  exit 1
fi

KNAME=$(lsblk -nro KNAME "$BACKING" | head -1)
STAT=/sys/class/block/$KNAME/stat
[[ -r "$STAT" ]] || { echo "cannot read $STAT" >&2; exit 1; }

sectors_written() {
  awk '{print $7}' "$STAT"
}

sectors_read() {
  awk '{print $3}' "$STAT"
}

bytes_from_sectors() {
  awk -v s="$1" 'BEGIN { printf "%.0f", s * 512 }'
}

cleanup() {
  dmsetup remove "$NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

run_fio() {
  local target=$1
  local label=$2
  local compress=$3
  local before_w after_w before_r after_r
  local start end

  blockdev --flushbufs "$target" || true
  before_w=$(sectors_written)
  before_r=$(sectors_read)
  start=$(date +%s%N)

  fio --name="$label" --filename="$target" --size="$SIZE" --direct=1 \
      --ioengine=libaio --iodepth="$IODEPTH" --numjobs=1 --bs=4k \
      --rw=randwrite --time_based=1 --runtime="$RUNTIME" \
      --group_reporting=1 --refill_buffers=1 --randrepeat=0 \
      --buffer_compress_percentage="$compress" --buffer_compress_chunk=512 \
      --output-format=normal

  blockdev --flushbufs "$target" || true
  end=$(date +%s%N)
  after_w=$(sectors_written)
  after_r=$(sectors_read)

  local delta_w=$((after_w - before_w))
  local delta_r=$((after_r - before_r))

  printf 'RESULT label=%s compress_pct=%s qd=%s lower_write_sectors=%s lower_write_bytes=%s lower_read_sectors=%s lower_read_bytes=%s elapsed_ns=%s\n' \
      "$label" "$compress" "$IODEPTH" \
      "$delta_w" "$(bytes_from_sectors "$delta_w")" \
      "$delta_r" "$(bytes_from_sectors "$delta_r")" \
      "$((end - start))"
}

SECTORS=$((SIZE_BYTES / 512))

printf 'Backing: %s (%s) physical_bytes=%s logical_bytes=%s runtime=%ss iodepth=%s\n' \
    "$BACKING" "$KNAME" "$BACKING_BYTES" "$SIZE_BYTES" "$RUNTIME" "$IODEPTH"
printf 'Queue: logical=%s physical=%s minimum_io=%s discard_granularity=%s discard_max=%s\n' \
    "$(cat "/sys/class/block/$KNAME/queue/logical_block_size" 2>/dev/null || echo unknown)" \
    "$(cat "/sys/class/block/$KNAME/queue/physical_block_size" 2>/dev/null || echo unknown)" \
    "$(cat "/sys/class/block/$KNAME/queue/minimum_io_size" 2>/dev/null || echo unknown)" \
    "$(cat "/sys/class/block/$KNAME/queue/discard_granularity" 2>/dev/null || echo unknown)" \
    "$(cat "/sys/class/block/$KNAME/queue/discard_max_bytes" 2>/dev/null || echo unknown)"

modprobe dm-swapz

for spec in "compressible:100" "partial:50" "incompressible:0"; do
  workload=\${spec%%:*}
  compression=\${spec##*:}

  echo
  echo "=== $workload: raw baseline ==="
  run_fio "$BACKING" "\${workload}-raw" "$compression"

  dmsetup create "$NAME" --table "0 $SECTORS swapz $BACKING"

  echo "=== $workload: swapz ==="
  run_fio "/dev/mapper/$NAME" "\${workload}-swapz" "$compression"
  echo "STATUS workload=$workload $(dmsetup status "$NAME")"

  dmsetup remove "$NAME"
done

echo
echo 'Interpretation: compare paired lower_write_sectors and fio throughput/latency.'
echo 'Host-write reduction is an endurance proxy; NAND wear remains FTL-dependent.'
