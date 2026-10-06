#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: sudo ./bench/block-benchmark.sh --backing /dev/DEVICE --size 1G --destroy [--runtime 30] [--iodepth 8]

DESTRUCTIVE: overwrites the backing device. Use only a dedicated test partition.
Compares direct raw 4 KiB writes with dm-swapz using the same fio workload and
reports backing-device sectors written. The backing device must be >= ~2.5x SIZE.
USAGE
  exit 2
}

BACKING=""
SIZE=""
RUNTIME=30
IODEPTH=8
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
for tool in fio dmsetup modprobe blockdev lsblk awk numfmt; do command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }; done
[[ -b "$BACKING" ]] || { echo "$BACKING is not a block device" >&2; exit 1; }
if grep -qE "^${BACKING//\//\\/}[[:space:]]" /proc/swaps; then echo "$BACKING is active swap" >&2; exit 1; fi
if [[ -n "$(lsblk -nro MOUNTPOINTS "$BACKING" | tr -d '[:space:]')" ]]; then echo "$BACKING is mounted" >&2; exit 1; fi

KNAME=$(lsblk -nro KNAME "$BACKING" | head -1)
STAT=/sys/class/block/$KNAME/stat
[[ -r "$STAT" ]] || { echo "cannot read $STAT" >&2; exit 1; }
sectors_written() { awk '{print $7}' "$STAT"; }
bytes_from_sectors() { awk -v s="$1" 'BEGIN { printf "%.0f", s * 512 }'; }
cleanup() { dmsetup remove "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

run_fio() {
  local target=$1 label=$2 compress=$3
  local before after delta start end elapsed
  blockdev --flushbufs "$BACKING" || true
  before=$(sectors_written)
  start=$(date +%s%N)
  fio --name="$label" --filename="$target" --size="$SIZE" --direct=1 \
      --ioengine=libaio --iodepth="$IODEPTH" --numjobs=1 --bs=4k --rw=randwrite \
      --time_based=1 --runtime="$RUNTIME" --group_reporting=1 --refill_buffers=1 \
      --randrepeat=0 --buffer_compress_percentage="$compress" --output-format=normal
  end=$(date +%s%N)
  blockdev --flushbufs "$BACKING" || true
  after=$(sectors_written)
  delta=$((after-before))
  elapsed=$((end-start))
  printf '%s backing_sectors_written=%s backing_bytes_written=%s elapsed_ns=%s\n' \
    "$label" "$delta" "$(bytes_from_sectors "$delta")" "$elapsed"
}

printf 'Backing: %s (%s) logical test size=%s runtime=%ss iodepth=%s\n' "$BACKING" "$KNAME" "$SIZE" "$RUNTIME" "$IODEPTH"
echo '=== Baseline: 75% compressible buffers, raw device ==='
BASELINE=$(run_fio "$BACKING" baseline 75 | tee /dev/stderr | tail -1)

modprobe dm-swapz
SIZE_BYTES=$(numfmt --from=iec "$SIZE")
SIZE_BYTES=$((SIZE_BYTES / 4096 * 4096))
SECTORS=$((SIZE_BYTES / 512))
dmsetup create "$NAME" --table "0 $SECTORS swapz $BACKING"

echo '=== swapz: same 75% compressible workload ==='
SWAPZ=$(run_fio "/dev/mapper/$NAME" swapz 75 | tee /dev/stderr | tail -1)
echo "dm status: $(dmsetup status "$NAME")"

# Recreate the volatile target so the incompressible control starts with an
# empty mapping and fresh arena head rather than inheriting the compressible run.
dmsetup remove "$NAME"
dmsetup create "$NAME" --table "0 $SECTORS swapz $BACKING"

echo '=== Control: incompressible workload through fresh swapz target ==='
CONTROL=$(run_fio "/dev/mapper/$NAME" swapz-incompressible 0 | tee /dev/stderr | tail -1)

echo
printf '%s\n%s\n%s\n' "$BASELINE" "$SWAPZ" "$CONTROL"
echo 'Interpretation: compare backing_bytes_written and fio bandwidth. Host-write reduction is the endurance proxy; NAND wear itself remains controller-dependent.'
