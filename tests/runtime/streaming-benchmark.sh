#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in awk blockdev dmsetup fio modprobe python3; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
BACKEND_KIND=${SWAPZ_BENCH_BACKEND:-null_blk}
case "$BACKEND_KIND" in
  null_blk|nbd) ;;
  *) echo "ERROR: SWAPZ_BENCH_BACKEND must be null_blk or nbd" >&2; exit 4 ;;
esac
NBD_DEVICE=${SWAPZ_BENCH_NBD_DEVICE:-}
if [[ "$BACKEND_KIND" == nbd && ! "$NBD_DEVICE" =~ ^/dev/nbd[0-9]+$ ]]; then
  echo "ERROR: NBD backend requires an explicit unused SWAPZ_BENCH_NBD_DEVICE=/dev/nbdN" >&2
  exit 4
fi
BANDWIDTH=${SWAPZ_BENCH_MBPS:-20}
LATENCY_NS=${SWAPZ_BENCH_LATENCY_NS:-500000}
RUNTIME=${SWAPZ_BENCH_RUNTIME:-3}
WRITE_QD=${SWAPZ_BENCH_QD:-64}
COMPRESS=${SWAPZ_BENCH_COMPRESS:-50}
# Throttled null_blk also charges DISCARD by request size. GC discards a
# full 1 MiB segment and can permanently requeue above the 50 Hz budget.
# Disable lower DISCARD in the synthetic bandwidth tests; its correctness
# and availability are exercised separately by runtime GC/discard tests.
BENCH_DISCARD=${SWAPZ_BENCH_DISCARD:-0}
case "$BENCH_DISCARD" in
  0|1) ;;
  *) echo "ERROR: SWAPZ_BENCH_DISCARD must be 0 or 1" >&2; exit 4 ;;
esac
if [[ "$BACKEND_KIND" == null_blk ]] && (( BANDWIDTH > 0 && BENCH_DISCARD == 1 )); then
  echo "ERROR: null_blk mbps may requeue a 1 MiB GC DISCARD forever; use SWAPZ_BENCH_DISCARD=0 with bandwidth throttling." >&2
  exit 4
fi
BATCHES=${SWAPZ_BENCH_BATCHES:-"4 8 16 32 64 128 256 512 1024"}
STRATEGIES=${SWAPZ_BENCH_STRATEGIES:-"immediate opportunistic staged"}
# null_blk's mbps throttle replenishes bytes at 50 ticks/second. A request
# larger than one tick's byte budget is permanently requeued by null_blk and
# can never complete. Keep this backend limitation explicit so a large swapz
# batch cannot be misreported as a swapz timeout.
NULLBLK_TICKS_PER_SEC=50
NULLBLK_TICK_BYTES=$(( BANDWIDTH > 0 ? (1048576 / NULLBLK_TICKS_PER_SEC) * BANDWIDTH : 0 ))
LOGICAL_MIB=32
COLD_MIB=4
WRITER_MIB=$((LOGICAL_MIB - COLD_MIB))
TMP=$(mktemp -d /dev/shm/swapz-v22-stream.XXXXXX)
TAG="$$-$RANDOM"
TARGET="swapz-v22-stream-$TAG"
NULL_NAME="swapzv22$TAG"
NULL_CFG="/sys/kernel/config/nullb/$NULL_NAME"
BACKING=""
BACKING_KNAME=""
BACKEND=""
CONFIGFS_MOUNTED_BY_US=0
RESULTS="$TMP/results.jsonl"
TARGET_ACTIVE=0
NBD_PID=""
NBD_READY="$TMP/nbd.ready"
NBD_STATS="$TMP/nbd.stats.json"
NBD_LOG="$TMP/nbd-server.log"

# Teardown is deliberately a separate, mock-testable helper. A failed normal
# dmsetup removal must NEVER power off the backing null_blk device.
source "$ROOT/tests/runtime/streaming-benchmark-teardown.sh"

cleanup() {
  local rc=$?
  trap - EXIT
  set +e
  if ! swapz_benchmark_cleanup_resources; then
    echo "ERROR: benchmark cleanup incomplete; preserving the DM target, null_blk backing, and $TMP for diagnosis." >&2
    if (( rc == 0 )); then
      rc=1
    fi
    exit "$rc"
  fi
  if (( rc == 0 )); then
    rm -rf "$TMP"
  else
    echo "Benchmark exited with status $rc; diagnostic artifacts preserved at $TMP" >&2
  fi
  exit "$rc"
}
trap cleanup EXIT

setup_nullblk() {
  modprobe null_blk nr_devices=0 >/dev/null 2>&1 || return 1
  [[ -d /sys/kernel/config ]] || return 1
  if ! mountpoint -q /sys/kernel/config; then
    mount -t configfs none /sys/kernel/config || return 1
    CONFIGFS_MOUNTED_BY_US=1
  fi
  [[ -d /sys/kernel/config/nullb ]] || return 1
  mkdir "$NULL_CFG" || return 1
  for attr in size memory_backed irqmode completion_nsec hw_queue_depth max_sectors mbps power; do
    [[ -e "$NULL_CFG/$attr" ]] || return 1
  done
  echo 256 >"$NULL_CFG/size"
  echo 1 >"$NULL_CFG/memory_backed"
  echo 2 >"$NULL_CFG/irqmode"
  echo "$LATENCY_NS" >"$NULL_CFG/completion_nsec"
  echo 1 >"$NULL_CFG/hw_queue_depth"
  echo 2048 >"$NULL_CFG/max_sectors"
  echo "$BANDWIDTH" >"$NULL_CFG/mbps"
  if [[ -e "$NULL_CFG/discard" ]]; then
    echo "$BENCH_DISCARD" >"$NULL_CFG/discard"
  elif (( BENCH_DISCARD )); then
    echo "ERROR: null_blk discard requested but configfs has no discard control" >&2
    return 1
  fi
  echo 1 >"$NULL_CFG/power"
  local index candidate
  index=$(cat "$NULL_CFG/index")
  BACKING=""
  # Configfs null_blk naming differs across kernel versions. Newer kernels may
  # expose /dev/<configfs-name>; older ones commonly expose /dev/nullb<index>.
  for _ in $(seq 1 50); do
    for candidate in "/dev/$NULL_NAME" "/dev/nullb$index"; do
      if [[ -b "$candidate" ]]; then
        BACKING="$candidate"
        break 2
      fi
    done
    sleep 0.05
  done
  [[ -n "$BACKING" && -b "$BACKING" ]] || return 1
  BACKING_KNAME=""
  for candidate in "$(basename "$BACKING")" "$NULL_NAME" "nullb$index"; do
    if [[ -e "/sys/class/block/$candidate/stat" ]]; then
      BACKING_KNAME="$candidate"
      break
    fi
  done
  [[ -n "$BACKING_KNAME" ]] || return 1
  if (( BANDWIDTH > 0 )); then
    BACKEND="null_blk-${BANDWIDTH}MiBps-${LATENCY_NS}ns-QD1"
  else
    BACKEND="null_blk-unthrottled-${LATENCY_NS}ns-QD1"
  fi
  return 0
}

# NBD is strictly opt-in. The operator must identify an unused *virtual*
# /dev/nbdN; this harness will never pick or touch a physical device.
setup_nbd() {
  [[ -b "$NBD_DEVICE" ]] || {
    echo "ERROR: $NBD_DEVICE is unavailable. Load the NBD kernel driver separately before testing." >&2
    return 1
  }
  (( BANDWIDTH > 0 )) || {
    echo "ERROR: NBD requires positive bandwidth; zero means unthrottled null_blk only." >&2
    return 1
  }
  (( LATENCY_NS >= 0 && LATENCY_NS % 1000 == 0 )) || {
    echo "ERROR: NBD completion latency must be a nonnegative whole number of microseconds." >&2
    return 1
  }
  local cmd=(
    python3 "$ROOT/tests/runtime/size-aware-nbd.py" serve
    --device "$NBD_DEVICE" --size-mib 256
    --mbps "$BANDWIDTH" --latency-us "$((LATENCY_NS / 1000))"
    --ready-file "$NBD_READY" --stats-file "$NBD_STATS"
  )
  (( BENCH_DISCARD )) && cmd+=(--allow-trim)
  "${cmd[@]}" >"$NBD_LOG" 2>&1 &
  NBD_PID=$!
  BACKING="$NBD_DEVICE"
  BACKING_KNAME=${NBD_DEVICE##*/}
  BACKEND="size-aware-nbd-${BANDWIDTH}MiBps-${LATENCY_NS}ns-serialized"
  local i
  for ((i=0; i<100; ++i)); do
    if [[ -s "$NBD_READY" && -e "/sys/class/block/$BACKING_KNAME/stat" ]]; then
      break
    fi
    if ! kill -0 "$NBD_PID" 2>/dev/null; then
      echo "ERROR: size-aware NBD server failed during startup:" >&2
      cat "$NBD_LOG" >&2
      return 1
    fi
    sleep 0.1
  done
  [[ -s "$NBD_READY" && -e "/sys/class/block/$BACKING_KNAME/stat" ]] || {
    echo "ERROR: size-aware NBD server did not become ready" >&2
    return 1
  }
  local backing_bytes
  backing_bytes=$(blockdev --getsize64 "$BACKING") || return 1
  [[ "$backing_bytes" == 268435456 ]] || {
    echo "ERROR: size-aware NBD device has unexpected capacity: $backing_bytes" >&2
    return 1
  }
  return 0
}

if [[ "$BACKEND_KIND" == nbd ]]; then
  if ! setup_nbd; then
    echo "ERROR: opt-in size-aware NBD backend setup failed; inspect $NBD_LOG" >&2
    exit 2
  fi
elif ! setup_nullblk; then
  echo "ERROR: null_blk with memory_backed+mbps+completion_nsec is required for the controlled V2.2 sweep." >&2
  echo "Use bench/request-plateau.py for a model-only sweep or install a kernel with null_blk controls." >&2
  exit 2
fi

if [[ "$BACKEND_KIND" == null_blk ]] && (( BANDWIDTH > 0 )); then
  unsafe=()
  for batch in $BATCHES; do
    if (( batch * 1024 > NULLBLK_TICK_BYTES )); then
      unsafe+=("$batch")
    fi
  done
  if (( ${#unsafe[@]} )); then
    safe_kib=$(( NULLBLK_TICK_BYTES / 1024 ))
    echo "ERROR: null_blk mbps backend cannot complete a single request larger than its per-tick byte budget." >&2
    echo "At ${BANDWIDTH} MiB/s the budget is ${NULLBLK_TICK_BYTES} bytes (~${safe_kib} KiB); unsafe batch ceiling(s): ${unsafe[*]} KiB." >&2
    echo "Restrict SWAPZ_BENCH_BATCHES to safe values, use SWAPZ_BENCH_MBPS=0 for latency-only large-request testing, or use a different size-aware bandwidth backend." >&2
    exit 3
  fi
fi

STAT="/sys/class/block/$BACKING_KNAME/stat"
read_stat() { awk '{print $1, $3, $5, $7}' "$STAT"; }

flush_device() {
  python3 - "$1" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
}

status_value() {
  local status=$1 key=$2
  sed -n "s/.*\\b${key}=\\([^ ]*\\).*/\\1/p" <<<"$status"
}

prefill_cold() {
  local path=$1
  fio --name=prefill --filename="$path" --offset=0 --size="${COLD_MIB}M" \
      --io_size="${COLD_MIB}M" --rw=write --bs=4k --ioengine=libaio \
      --iodepth=16 --direct=1 --numjobs=1 --refill_buffers=1 \
      --buffer_compress_percentage=0 --randseed=1517953062 \
      --output-format=normal >/dev/null
  flush_device "$path"
}

run_case() {
  local strategy=$1 batch=$2
  local table_sectors=$((LOGICAL_MIB * 1024 * 1024 / 512))
  local path="/dev/mapper/$TARGET"
  local fiofile="$TMP/${strategy}-${batch}.fio"
  local json="$TMP/${strategy}-${batch}.json"
  local before after status start_ns end_ns

  # Never reuse the target name if a prior case failed to remove it.
  if (( TARGET_ACTIVE )) || dmsetup info "$TARGET" >/dev/null 2>&1; then
    echo "ERROR: previous benchmark DM target still exists; refusing to start another case." >&2
    return 1
  fi
  dmsetup create "$TARGET" --table "0 $table_sectors swapz $BACKING $strategy $batch"
  TARGET_ACTIVE=1
  # Prove the throttled fixture cannot issue a full-segment lower DISCARD
  # before any write/GC can reach it.
  if (( ! BENCH_DISCARD )) && ! dmsetup status "$TARGET" | grep -q 'lower_discard=off'; then
    echo "ERROR: benchmark backend unexpectedly advertises lower DISCARD; refusing unsafe workload." >&2
    return 1
  fi
  prefill_cold "$path"

  cat >"$fiofile" <<EOF
[global]
ioengine=libaio
direct=1
bs=4k
time_based=1
runtime=$RUNTIME
randrepeat=1
randseed=1517953062
percentile_list=50:90:95:99:99.9

[writer]
filename=$path
rw=randwrite
offset=${COLD_MIB}M
size=${WRITER_MIB}M
iodepth=$WRITE_QD
refill_buffers=1
buffer_compress_percentage=$COMPRESS
buffer_compress_chunk=512

[reader]
filename=$path
rw=randread
offset=0
size=${COLD_MIB}M
iodepth=1
rate_iops=100
EOF

  before=$(read_stat)
  start_ns=$(date +%s%N)
  fio "$fiofile" --output-format=json --output="$json"
  # Staged upper completions may precede physical drain. Include the explicit
  # flush in the end-to-end drain clock.
  flush_device "$path"
  end_ns=$(date +%s%N)
  after=$(read_stat)
  status=$(dmsetup status "$TARGET")
  grep -q "failed=0" <<<"$status"

  python3 - "$json" "$before" "$after" "$status" "$strategy" "$batch" \
      "$start_ns" "$end_ns" "$BACKEND" >>"$RESULTS" <<'PY'
import json, sys
path, before, after, status, strategy, batch, start_ns, end_ns, backend = sys.argv[1:]
with open(path, encoding="utf-8") as f:
    root = json.load(f)
jobs = {job["jobname"]: job for job in root["jobs"]}
w = jobs["writer"]["write"]
r = jobs["reader"]["read"]
def status_map(text):
    out = {}
    for tok in text.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out
def p(job, key):
    return float(job.get("clat_ns", {}).get("percentile", {}).get(key, 0)) / 1e6
b = [int(x) for x in before.split()]
a = [int(x) for x in after.split()]
s = status_map(status)
logical = int(w.get("io_bytes", 0))
elapsed_s = (int(end_ns) - int(start_ns)) / 1e9
row = {
    "backend": backend, "strategy": strategy, "batch_kib": int(batch),
    "write_qd": int(jobs["writer"]["job options"].get("iodepth", 0) or 0),
    "logical_write_bytes": logical,
    "upper_write_mib_s": float(w.get("bw_bytes", 0)) / 1048576,
    "drained_write_mib_s": logical / 1048576 / elapsed_s if elapsed_s else 0,
    "write_avg_ms": float(w.get("clat_ns", {}).get("mean", 0)) / 1e6,
    "write_p99_ms": p(w, "99.000000"),
    "read_avg_ms": float(r.get("clat_ns", {}).get("mean", 0)) / 1e6,
    "read_p95_ms": p(r, "95.000000"), "read_p99_ms": p(r, "99.000000"),
    "read_max_ms": float(r.get("clat_ns", {}).get("max", 0)) / 1e6,
    "usr_cpu_pct": float(w.get("usr_cpu", 0)) + float(r.get("usr_cpu", 0)),
    "sys_cpu_pct": float(w.get("sys_cpu", 0)) + float(r.get("sys_cpu", 0)),
    "lower_read_ios": a[0]-b[0], "lower_read_sectors": a[1]-b[1],
    "lower_write_ios": a[2]-b[2], "lower_write_sectors": a[3]-b[3],
    "status": s,
}
row["staged_hits"] = int(s.get("staged_hits", 0))
row["staged_early"] = int(s.get("staged_early", 0))
row["staged_cancel"] = int(s.get("staged_cancel", 0))
row["physical_write_reqs"] = int(s.get("physical_write_reqs", 0))
row["max_write_batch"] = int(s.get("max_write_batch", 0))
print(json.dumps(row, sort_keys=True))
PY

  # A RESULT is only valid after successful, verified teardown. In particular,
  # do not allow an open-count/udev race to abort the sweep and trigger unsafe
  # backing removal in the EXIT trap.
  swapz_benchmark_remove_target || return 1
  echo "RESULT strategy=$strategy batch_kib=$batch $(tail -n1 "$RESULTS")"
}

echo "BACKEND=$BACKEND"
echo "LOWER_DISCARD=$BENCH_DISCARD"
echo "NBD_DEVICE=${NBD_DEVICE:-not-used}"
echo "BATCHES=$BATCHES"
echo "STRATEGIES=$STRATEGIES"

for strategy in $STRATEGIES; do
  if [[ "$strategy" == immediate ]]; then
    run_case immediate 4
    continue
  fi
  for batch in $BATCHES; do
    run_case "$strategy" "$batch"
  done
done

python3 - "$RESULTS" <<'PY'
import json, sys
rows = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
print("\n=== THROUGHPUT / SWAP-IN LATENCY FRONTIER ===")
for strategy in sorted({r["strategy"] for r in rows}):
    group = sorted((r for r in rows if r["strategy"] == strategy), key=lambda r: r["batch_kib"])
    best = max(r["drained_write_mib_s"] for r in group)
    plateau = [r for r in group if r["drained_write_mib_s"] >= best * 0.97]
    first = min(plateau, key=lambda r: r["batch_kib"])
    min_p99 = min(r["read_p99_ms"] for r in plateau)
    guarded = [r for r in plateau if r["read_p99_ms"] <= min_p99 * 1.10]
    winner = min(guarded, key=lambda r: r["batch_kib"])
    print(
        f"{strategy}: best_drain={best:.3f} MiB/s "
        f"first_97pct={first['batch_kib']}KiB "
        f"latency_guarded={winner['batch_kib']}KiB "
        f"read_p99={winner['read_p99_ms']:.3f}ms "
        f"upper={winner['upper_write_mib_s']:.3f}MiB/s"
    )
    for r in group:
        print(
            f"  {r['batch_kib']:4d}KiB "
            f"upper={r['upper_write_mib_s']:8.3f} "
            f"drain={r['drained_write_mib_s']:8.3f} "
            f"read_p99={r['read_p99_ms']:8.3f}ms "
            f"read_max={r['read_max_ms']:8.3f}ms "
            f"lower_wios={r['lower_write_ios']:7d} "
            f"early={r['staged_early']:7d}"
        )
PY

echo "V2.2 streaming plateau/latency sweep: PASS"
