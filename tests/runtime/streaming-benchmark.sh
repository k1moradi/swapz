#!/usr/bin/env bash
set -euo pipefail

# Validate benchmark policy and null_blk request sizes before checking root
# privileges, allocating fixture files, or touching any kernel resources.
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
# NBD benchmarking is intentionally disabled until its test-owned service
# lifecycle is controlled through a retained pidfd. The historical Bash
# background PID plus kill -TERM path can signal a reused numeric PID. This
# guard executes before allocation, NBD attachment, or worker launch.
if [[ "$BACKEND_KIND" == nbd ]]; then
  echo "ERROR: NBD backend disabled: numeric-PID service ownership is not safe; preserve backing and use a separately reviewed pidfd-owned controller." >&2
  exit 4
fi
BANDWIDTH=${SWAPZ_BENCH_MBPS:-20}
LATENCY_NS=${SWAPZ_BENCH_LATENCY_NS:-500000}
RUNTIME=${SWAPZ_BENCH_RUNTIME:-3}
WRITE_QD=${SWAPZ_BENCH_QD:-64}
COMPRESS=${SWAPZ_BENCH_COMPRESS:-50}
READ_IOPS=${SWAPZ_BENCH_READ_IOPS:-100}
# Validate independently of fio before even checking privileges or devices.
if [[ ! "$READ_IOPS" =~ ^[1-9][0-9]{0,3}$ ]] || (( READ_IOPS > 2000 )); then
  echo "ERROR: SWAPZ_BENCH_READ_IOPS must be an integer in 1..2000" >&2
  exit 4
fi
# Keep exact fio latency artifacts only when explicitly requested; preserving
# these diagnostics never upgrades them to independent benchmark evidence.
KEEP_ARTIFACTS=${SWAPZ_BENCH_KEEP_ARTIFACTS:-0}
case "$KEEP_ARTIFACTS" in
  0|1) ;;
  *) echo "ERROR: SWAPZ_BENCH_KEEP_ARTIFACTS must be 0 or 1" >&2; exit 4 ;;
esac
# Throttled null_blk also charges DISCARD by request size. GC discards a
# full 1 MiB segment and can permanently requeue above the 50 Hz budget.
# Disable lower DISCARD in the synthetic bandwidth tests; its correctness
# and availability are exercised separately by runtime GC/discard tests.
BENCH_DISCARD=${SWAPZ_BENCH_DISCARD:-0}
case "$BENCH_DISCARD" in
  0|1) ;;
  *) echo "ERROR: SWAPZ_BENCH_DISCARD must be 0 or 1" >&2; exit 4 ;;
esac
STRATEGIES=${SWAPZ_BENCH_STRATEGIES:-"immediate opportunistic staged"}
REQUESTED_BATCHES=${SWAPZ_BENCH_BATCHES:-auto}
# The rootless planner admits only serviceable null_blk requests; an explicit
# 512/1024 KiB batch under a 20 MiB/s throttle is rejected before even
# creating a null_blk configfs entry. With "auto", use only feasible sizes.
if ! BATCHES=$(python3 -B "$ROOT/tests/runtime/streaming-benchmark-plan.py" \
    --backend "$BACKEND_KIND" --mbps "$BANDWIDTH" \
    --latency-ns "$LATENCY_NS" --strategies "$STRATEGIES" \
    --runtime "$RUNTIME" --qd "$WRITE_QD" --compress "$COMPRESS" \
    --batches "$REQUESTED_BATCHES" --repeats 1 --emit-batches); then
  echo "ERROR: benchmark pre-device plan rejected configuration; no fixture allocated." >&2
  exit 4
fi
if [[ "$BACKEND_KIND" == null_blk ]] && (( BANDWIDTH > 0 && BENCH_DISCARD == 1 )); then
  echo "ERROR: null_blk mbps may requeue a 1 MiB GC DISCARD forever; use SWAPZ_BENCH_DISCARD=0 with bandwidth throttling." >&2
  exit 4
fi
# The Python Fiona package also installs a CLI named 'fio'. Reject it before
# root checks, null_blk setup or any DM creation; actual fio CLAT compatibility
# is exercised independently by the rootless regular-file integration test.
if ! command -v fio >/dev/null 2>&1; then
  echo "ERROR: Flexible I/O Tester (fio) unavailable before device setup" >&2
  exit 4
fi
if ! FIO_VERSION=$(fio --version 2>/dev/null) ||
   [[ ! "$FIO_VERSION" =~ ^fio-[0-9]+(\.[0-9]+)+ ]]; then
  echo "ERROR: fio executable is not Flexible I/O Tester (got '${FIO_VERSION:-unknown}'); refusing device setup" >&2
  exit 4
fi
[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in awk blockdev cmp dd dmsetup fio modprobe python3; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
# Preserve a second fail-closed guard after setup as defense in depth.
NULLBLK_TICKS_PER_SEC=50
NULLBLK_TICK_BYTES=$(( BANDWIDTH > 0 ? (1048576 / NULLBLK_TICKS_PER_SEC) * BANDWIDTH : 0 ))
LOGICAL_MIB=32
COLD_MIB=4
WRITER_MIB=$((LOGICAL_MIB - COLD_MIB))
# Reserve the final 4 KiB logical page as an independent compressed readback
# sentinel. Fio's writer never overlaps it. This is a limited integrity probe,
# NOT proof of the correctness of all random writes.
SENTINEL_PAGE=$(( LOGICAL_MIB * 256 - 1 ))
WRITER_BYTES=$(( WRITER_MIB * 1048576 - 4096 ))
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
    echo "ERROR: benchmark cleanup incomplete; preserving the test DM target, backing device, and $TMP for diagnosis." >&2
    if (( rc == 0 )); then
      rc=1
    fi
    exit "$rc"
  fi
  if (( rc == 0 )); then
    # NBD server stats are emitted only after its graceful shutdown. Keep
    # actual observed maximum lower request size visible before deleting TMP.
    if [[ "$BACKEND_KIND" == nbd && -s "$NBD_STATS" ]]; then
      echo "SIZE_AWARE_NBD_STATS=$(cat "$NBD_STATS")"
    fi
    if [[ "$KEEP_ARTIFACTS" == 1 ]]; then
      echo "DIAGNOSTIC_ARTIFACTS=$TMP (UNQUALIFIED; no independent drain/quiescence attestation)"
    else
      rm -rf "$TMP"
    fi
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
  # Defense in depth: the top-level backend guard must already reject NBD.
  # Never spawn a server without an independently qualified pidfd-owned
  # service/controller and a safe, exact-child shutdown acknowledgment.
  echo "ERROR: NBD backend launch is disabled pending verified process ownership." >&2
  return 4
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

prefill_writer_verified() {
  local path=$1 case_id=$2
  # Seed every 4 KiB page with an fio CRC32C header before random overwrites.
  # This setup happens before timed lower-device snapshots and is not measured.
  fio --name=writer-prefill --filename="$path" \
      --offset="${COLD_MIB}M" --size="$WRITER_BYTES" --rw=write \
      --bs=4k --ioengine=libaio --iodepth=16 --direct=1 \
      --verify=crc32c --do_verify=0 --refill_buffers=1 \
      --buffer_compress_percentage="$COMPRESS" --buffer_compress_chunk=512 \
      --output-format=json --output="$TMP/$case_id.writer-prefill.json"
  flush_device "$path"
}

run_case() {
  local strategy=$1 batch=$2
  local table_sectors=$((LOGICAL_MIB * 1024 * 1024 / 512))
  local path="/dev/mapper/$TARGET"
  local fiofile="$TMP/${strategy}-${batch}.fio"
  local json="$TMP/${strategy}-${batch}.json"
  local before after status start_ns end_ns read_log_prefix latency_summary verify_summary
  local sentinel="$TMP/${strategy}-${batch}.sentinel"
  local sentinel_read="$TMP/${strategy}-${batch}.sentinel.readback"
  read_log_prefix="$TMP/${strategy}-${batch}-reader"

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
  prefill_writer_verified "$path" "${strategy}-${batch}"
  # Write and persist a known compressible page before the timed workload.
  # Its logical page is never targeted by the fio writer or reader.
  python3 - "$sentinel" <<'PY'
import sys
with open(sys.argv[1], "xb") as out:
    out.write(b"SWAPZ_V22_PROBE_" * 256)
PY
  dd if="$sentinel" of="$path" bs=4096 count=1 seek="$SENTINEL_PAGE" \
      oflag=direct conv=notrunc status=none
  flush_device "$path"

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
size=$WRITER_BYTES
iodepth=$WRITE_QD
refill_buffers=1
buffer_compress_percentage=$COMPRESS
buffer_compress_chunk=512
# Every randomly overwritten page carries a CRC32C header. The post-run
# verifier scans *all* writer pages after timing, including untouched prefill.
verify=crc32c
do_verify=0

[reader]
filename=$path
rw=randread
offset=0
size=${COLD_MIB}M
iodepth=1
# Exact, unaveraged completion-latency samples for this sole reader job.
# Fio's per_job_logs=0 removes a job-index suffix from the CLAT log.
rate_iops=$READ_IOPS
write_lat_log=$read_log_prefix
log_avg_msec=0
per_job_logs=0
# Avoid reallocating fio's default 1024 log entries during common 30-60s diagnostics.
log_entries=32768
EOF

  before=$(read_stat)
  # An elapsed interval cannot use wall-clock time (date can jump).
  start_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
  fio "$fiofile" --output-format=json --output="$json"
  # Stop the flush-inclusive physical-counter window immediately after the
  # drain; parsing large CLAT logs beforehand would bias its duration and
  # let background writes progress outside the intended measurement phase.
  flush_device "$path"
  end_ns=$(python3 -c 'import time; print(time.monotonic_ns())')
  after=$(read_stat)
  # Require one exact latency for every completed reader I/O; a missing,
  # aggregated, or inconsistent fio log fails the case before publication.
  latency_summary=$(python3 -B "$ROOT/tests/runtime/streaming-benchmark-read-latency.py" \
      --fio-json "$json" --fio-clat-log "${read_log_prefix}_clat.log" \
      --sidecar "$TMP/${strategy}-${batch}.latbin") || return 1
  # After snapshotting the flush-inclusive measurement window, verify
  # every writer page using fio's embedded CRC32C headers. The verification
  # workload is 4 KiB READ ONLY, and cannot alter timed throughput or p99.
  local writer_verify_json="$TMP/${strategy}-${batch}.writer-verify.json"
  fio --name=writer-verify --filename="$path" --rw=read \
      --offset="${COLD_MIB}M" --size="$WRITER_BYTES" --bs=4k \
      --ioengine=libaio --iodepth=1 --direct=1 --verify=crc32c \
      --output-format=json --output="$writer_verify_json"
  verify_summary=$(python3 -B "$ROOT/tests/runtime/streaming-benchmark-writer-verify.py" \
      --fio-json "$writer_verify_json" --expected-bytes "$WRITER_BYTES") || return 1
  # Separately verify a protected page that the timed writer never addresses.
  # Any mismatch fails the entire case; never publish misleading good p99.
  dd if="$path" of="$sentinel_read" bs=4096 count=1 skip="$SENTINEL_PAGE" \
      iflag=direct status=none
  if ! cmp -s "$sentinel" "$sentinel_read"; then
    echo "ERROR: post-drain compressed sentinel readback differs; preserve fixture and diagnostics" >&2
    return 1
  fi
  status=$(dmsetup status "$TARGET")
  grep -q "failed=0" <<<"$status"

  python3 - "$json" "$before" "$after" "$status" "$strategy" "$batch" \
      "$start_ns" "$end_ns" "$BACKEND" "$latency_summary" "$verify_summary" >>"$RESULTS" <<'PY'
import json, sys
path, before, after, status, strategy, batch, start_ns, end_ns, backend, latency_summary, verify_summary = sys.argv[1:]
with open(path, encoding="utf-8") as f:
    root = json.load(f)
source_jobs = root.get("jobs") if isinstance(root, dict) else None
if (type(source_jobs) is not list or len(source_jobs) != 2 or
        any(type(job) is not dict or type(job.get("jobname")) is not str
            for job in source_jobs)):
    raise SystemExit("fio JSON must contain exactly two named jobs; preserve artifacts")
jobs = {job["jobname"]: job for job in source_jobs}
if set(jobs) != {"writer", "reader"} or len(jobs) != len(source_jobs):
    raise SystemExit("fio JSON missing/duplicate writer or reader; preserve artifacts")
if any(type(job.get("error")) is not int or job["error"] != 0
       for job in source_jobs):
    raise SystemExit("fio job-level error or missing status; preserve artifacts")
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
if elapsed_s <= 0:
    raise SystemExit("nonpositive monotonic benchmark interval; preserve artifacts")
if len(a) != 4 or len(b) != 4 or any(x < 0 for x in a + b):
    raise SystemExit("missing or corrupt lower-device counters; preserve artifacts")
read_count = int(r.get("total_ios", 0))
exact_latency = json.loads(latency_summary)
exact_count = exact_latency.get("read_count") if isinstance(exact_latency, dict) else None
exact_p99 = exact_latency.get("read_p99_ns") if isinstance(exact_latency, dict) else None
if (type(exact_count) is not int or exact_count != read_count or
        type(exact_p99) is not int or exact_p99 <= 0):
    raise SystemExit("invalid/mismatched exact reader latency; preserve artifacts")
lower_sectors = a[3] - b[3]
lower_ios = a[2] - b[2]
if any(a[index] < b[index] for index in range(4)):
    raise SystemExit("lower-device counters decreased; preserve artifacts")
row = {
    "backend": backend, "strategy": strategy, "batch_kib": int(batch),
    "write_qd": int(jobs["writer"]["job options"].get("iodepth", 0) or 0),
    "logical_write_bytes": logical,
    "upper_write_mib_s": float(w.get("bw_bytes", 0)) / 1048576,
    # This is a logical completion rate including a flush, NOT drained physical bytes.
    "logical_flush_window_mib_s": logical / 1048576 / elapsed_s,
    # Separate sysfs lower-device counter window; shared-I/O attribution and
    # kernel quiescence remain unproven until a trusted collector is available.
    "lower_counter_window_mib_s": lower_sectors * 512 / 1048576 / elapsed_s,
    "drain_window_s": elapsed_s,
    "read_count": read_count,
    "write_avg_ms": float(w.get("clat_ns", {}).get("mean", 0)) / 1e6,
    "write_p99_ms": p(w, "99.000000"),
    "read_avg_ms": float(r.get("clat_ns", {}).get("mean", 0)) / 1e6,
    "read_p95_ms": p(r, "95.000000"),
    "read_p99_ms": exact_p99 / 1e6,
    "fio_summary_read_p99_ms": p(r, "99.000000"),
    "read_max_ms": float(r.get("clat_ns", {}).get("max", 0)) / 1e6,
    "usr_cpu_pct": float(w.get("usr_cpu", 0)) + float(r.get("usr_cpu", 0)),
    "sys_cpu_pct": float(w.get("sys_cpu", 0)) + float(r.get("sys_cpu", 0)),
    "lower_read_ios": a[0]-b[0], "lower_read_sectors": a[1]-b[1],
    "lower_write_ios": lower_ios, "lower_write_sectors": lower_sectors,
    "status": s,
    # One protected compressed page survived the fio workload and flush.
    # This is NOT full random-writer data integrity attestation.
    "isolated_sentinel_readback_ok": True,
    # Separate bounded fio checksum-read of every writer page after timing;
    # still diagnostic, not independent kernel/device provenance.
    "fio_full_writer_verification": json.loads(verify_summary),
    # Exact fio read samples are retained separately from the non-qualifying
    # summarized fio read_p99_ms and unverified lower-counter window.
    "exact_read_latency": exact_latency,
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
echo "READ_IOPS_TARGET=$READ_IOPS (actual completions validated per case)"
echo "KEEP_ARTIFACTS=$KEEP_ARTIFACTS"

for strategy in $STRATEGIES; do
  if [[ "$strategy" == immediate ]]; then
    run_case immediate 4
    continue
  fi
  for batch in $BATCHES; do
    run_case "$strategy" "$batch"
  done
done

# Diagnostic reporting must not infer a physical-drain plateau or nominate a
# "winner" from one logical-completion timing per batch. The read-only
# reporter instead cross-checks lower-sector deltas and states the missing
# independent I/O-drain and p99 sample/repetition evidence explicitly.
python3 "$ROOT/tests/runtime/streaming-benchmark-report.py" --results "$RESULTS"

echo "V2.2 streaming single-sweep diagnostics: PASS (NO QUALIFIED WINNER)"
