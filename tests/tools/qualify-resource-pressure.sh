#!/usr/bin/env bash
# ID36: bounded low-memory + CPU-oversubscription qualification on owned RAM only.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"

VALIDATED_SOURCE=""
SHARED_PLAN=""
if [[ $# -ge 4 && $1 == --validated-source && $2 =~ ^[0-9a-f]{40}$ &&
      $3 == --shared-plan ]]; then
    VALIDATED_SOURCE="$2"
    SHARED_PLAN="$4"
    shift 4
fi
if [[ $# != 0 || ! -d $SHARED_PLAN ]]; then
    printf '%s\n' 'BLOCKED: ID36 requires validated source and owned shared plan' >&2
    exit 2
fi
[[ $(id -u) == 0 ]] || {
    printf '%s\n' 'BLOCKED: ID36 resource-pressure qualification requires root' >&2
    exit 2
}

CGROUP_ROOT=/sys/fs/cgroup
PRESSURE_MIB=576
PRESSURE_RAMP_MIB=80
READY_PRESSURE_MIB=$((PRESSURE_MIB - PRESSURE_RAMP_MIB))
PRESSURE_RAMP_BYTES=$((PRESSURE_RAMP_MIB * 1024 * 1024))
MEMORY_HEADROOM_BYTES=$((64 * 1024 * 1024))
MEMORY_MAX_BYTES=$((896 * 1024 * 1024))
# Two independently bounded candidate replays run inside this pair. Keep the
# pair watchdog strictly outside both 280s replay bounds plus bounded barrier,
# comparison and teardown slack, so the parent cannot manufacture a timeout
# while a child is still within its own forward-progress contract.
PAIR_REPLAY_TIMEOUT_SECONDS=280
PAIR_OUTER_SLACK_SECONDS=120
PAIR_OUTER_SECONDS=$((PAIR_REPLAY_TIMEOUT_SECONDS * 2 + PAIR_OUTER_SLACK_SECONDS))
MIN_AVAILABLE_KIB=$((1024 * 1024))
PRESSURE_SCRIPT="$ROOT/tests/runtime/benchmark/resource-pressure.py"
PAIR="$ROOT/tests/tools/benchmark-owned-pair.sh"

[[ -f $CGROUP_ROOT/cgroup.controllers &&
   -r $CGROUP_ROOT/cgroup.subtree_control ]] || {
    printf '%s\n' 'BLOCKED: ID36 requires cgroup v2' >&2
    exit 2
}
grep -qw memory "$CGROUP_ROOT/cgroup.controllers" || {
    printf '%s\n' 'BLOCKED: ID36 cgroup v2 memory controller unavailable' >&2
    exit 2
}
grep -qw cpu "$CGROUP_ROOT/cgroup.controllers" || {
    printf '%s\n' 'BLOCKED: ID36 cgroup v2 CPU controller unavailable' >&2
    exit 2
}
grep -qw memory "$CGROUP_ROOT/cgroup.subtree_control" || {
    printf '%s\n' 'BLOCKED: ID36 parent cgroup has no delegated memory controller' >&2
    exit 2
}
grep -qw cpu "$CGROUP_ROOT/cgroup.subtree_control" || {
    printf '%s\n' 'BLOCKED: ID36 parent cgroup has no delegated CPU controller' >&2
    exit 2
}
[[ -r $PRESSURE_SCRIPT && -r $PAIR ]] || {
    printf '%s\n' 'BLOCKED: ID36 helper files unavailable' >&2
    exit 2
}

available_kib="$(awk '/^MemAvailable:/ { print $2; exit }' /proc/meminfo)"
[[ $available_kib =~ ^[0-9]+$ && $available_kib -ge $MIN_AVAILABLE_KIB ]] || {
    printf '%s\n' 'BLOCKED: ID36 host lacks 1 GiB MemAvailable safety headroom' >&2
    exit 2
}

token="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
[[ $token =~ ^[a-f0-9]{16}$ ]] || {
    printf '%s\n' 'BLOCKED: ID36 random identity unavailable' >&2
    exit 2
}
CGROUP="$CGROUP_ROOT/swapz-id36-$token"
SESSION="$(mktemp -d "${TMPDIR:-/tmp}/swapz-id36.XXXXXXXX")"
READY="$SESSION/pressure.ready"
PRESSURE_ACTIVATE="$SESSION/pressure.activate"
PRESSURE_ACTIVE="$SESSION/pressure.active"
STOP="$SESSION/pressure.stop"
PAIR_READY="$SESSION/pair.ready"
PAIR_GO="$SESSION/pair.go"
PRESSURE_LOG="$SESSION/pressure.log"
PAIR_LOG="$SESSION/pair.log"
PRESSURE_PID=""
PAIR_PID=""

cleanup() {
    local result=$?
    trap - EXIT HUP INT TERM
    set +e
    : > "$STOP"
    if [[ -n $PAIR_PID ]]; then
        kill -TERM "$PAIR_PID" 2>/dev/null
        wait "$PAIR_PID" 2>/dev/null
    fi
    if [[ -n $PRESSURE_PID ]]; then
        for _ in {1..40}; do
            kill -0 "$PRESSURE_PID" 2>/dev/null || break
            sleep 0.05
        done
        if kill -0 "$PRESSURE_PID" 2>/dev/null; then
            kill -TERM "$PRESSURE_PID" 2>/dev/null
        fi
        wait "$PRESSURE_PID" 2>/dev/null
    fi
    if [[ -d $CGROUP ]]; then
        if [[ -f $CGROUP/cgroup.kill &&
              -n $(cat "$CGROUP/cgroup.procs" 2>/dev/null) ]]; then
            echo 1 > "$CGROUP/cgroup.kill" 2>/dev/null
        fi
        for _ in {1..40}; do
            [[ -z $(cat "$CGROUP/cgroup.procs" 2>/dev/null) ]] && break
            sleep 0.05
        done
        rmdir "$CGROUP" 2>/dev/null || result=1
    fi
    rm -rf "$SESSION"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir "$CGROUP" || {
    printf '%s\n' 'BLOCKED: ID36 cannot create isolated cgroup' >&2
    exit 2
}
for control in memory.max memory.high memory.current memory.events cpu.pressure cgroup.procs; do
    [[ -e "$CGROUP/$control" ]] || {
        printf 'BLOCKED: ID36 missing cgroup control %s\n' "$control" >&2
        exit 2
    }
done

echo "$MEMORY_MAX_BYTES" > "$CGROUP/memory.max"
# Establish the resident helper baseline before applying the real high
# watermark. The workload-scoped boundary is installed just before release.
echo "$MEMORY_MAX_BYTES" > "$CGROUP/memory.high"
if [[ -e $CGROUP/memory.swap.max ]]; then
    echo 0 > "$CGROUP/memory.swap.max"
fi

online_cpus="$(getconf _NPROCESSORS_ONLN)"
[[ $online_cpus =~ ^[1-9][0-9]*$ ]] || {
    printf '%s\n' 'BLOCKED: ID36 cannot determine online CPU count' >&2
    exit 2
}
cpu_workers=$((online_cpus * 2))
(( cpu_workers > 32 )) && cpu_workers=32
(( cpu_workers < 2 )) && cpu_workers=2

event_value() {
    local name=$1
    awk -v key="$name" '$1 == key { print $2; found=1 } END { if (!found) print 0 }'         "$CGROUP/memory.events"
}
cpu_some_total() {
    awk '$1 == "some" {
        for (i = 2; i <= NF; ++i)
            if ($i ~ /^total=/) {
                split($i, value, "="); print value[2]; found=1
            }
    } END { if (!found) print 0 }' "$CGROUP/cpu.pressure"
}

oom_start="$(event_value oom)"
oom_kill_start="$(event_value oom_kill)"

# Fault both memory-backed lowers before the pair enters ID36. The pair moves
# itself into the cgroup after prewarm and waits at the private barrier, so the
# lower backing pages do not consume the cgroup's pressure budget while module
# load, target construction, replay and teardown still run under ID36.
SWAPZ_ID36_PAIR_READY="$PAIR_READY" \
SWAPZ_ID36_PAIR_GO="$PAIR_GO" \
SWAPZ_ID36_CGROUP="$CGROUP" \
SWAPZ_ID36_REPLAY_TIMEOUT_SECONDS="$PAIR_REPLAY_TIMEOUT_SECONDS" \
    timeout --signal=TERM --kill-after=10s "${PAIR_OUTER_SECONDS}s" \
    bash "$PAIR" --validated-source "$VALIDATED_SOURCE" \
    --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced \
    --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000 \
    --async-prepare --resource-pressure-short --shared-plan "$SHARED_PLAN" \
    >"$PAIR_LOG" 2>&1 &
PAIR_PID=$!

for _ in {1..600}; do
    [[ -s $PAIR_READY ]] && break
    kill -0 "$PAIR_PID" 2>/dev/null || {
        cat "$PAIR_LOG" >&2
        printf '%s\n' 'FAIL: ID36 owned-RAM pair exited before null_blk prewarm barrier' >&2
        exit 1
    }
    sleep 0.05
done
[[ -s $PAIR_READY ]] || {
    printf '%s\n' 'FAIL: ID36 owned-RAM pair did not reach null_blk prewarm barrier' >&2
    exit 1
}
pair_cgroup_pid="$(awk -F= '$1 == "pid" && $2 ~ /^[0-9]+$/ { print $2; exit }' "$PAIR_READY")"
[[ $pair_cgroup_pid =~ ^[1-9][0-9]*$ ]] || {
    cat "$PAIR_LOG" >&2
    printf '%s\n' 'FAIL: ID36 pair readiness did not report migrated PID' >&2
    exit 1
}
grep -Fxq "$pair_cgroup_pid" "$CGROUP/cgroup.procs" || {
    cat "$PAIR_LOG" >&2
    printf '%s\n' 'FAIL: ID36 pair did not enter pressure cgroup after prewarm' >&2
    exit 1
}

bash -c '
    set -e
    cgroup=$1
    shift
    echo $$ > "$cgroup/cgroup.procs"
    exec "$@"
' _ "$CGROUP" python3 -B "$PRESSURE_SCRIPT" \
    --memory-mib "$PRESSURE_MIB" --ready-memory-mib "$READY_PRESSURE_MIB" \
    --cpu-workers "$cpu_workers" --ready-file "$READY" \
    --activate-file "$PRESSURE_ACTIVATE" --active-file "$PRESSURE_ACTIVE" \
    --stop-file "$STOP" >"$PRESSURE_LOG" 2>&1 &
PRESSURE_PID=$!

for _ in {1..800}; do
    [[ -s $READY ]] && break
    kill -0 "$PRESSURE_PID" 2>/dev/null || {
        cat "$PRESSURE_LOG" >&2
        printf '%s\n' 'FAIL: ID36 pressure helper exited before readiness' >&2
        exit 1
    }
    sleep 0.05
done
[[ -s $READY ]] || {
    printf '%s\n' 'FAIL: ID36 pressure helper did not become ready' >&2
    exit 1
}

pressure_current="$(cat "$CGROUP/memory.current")"
[[ $pressure_current =~ ^[0-9]+$ &&
   $pressure_current -ge $((READY_PRESSURE_MIB * 1024 * 1024)) ]] || {
    printf 'FAIL: ID36 ready-stage resident pressure too small: %s bytes\n' \
        "$pressure_current" >&2
    exit 1
}
oom_ready="$(event_value oom)"
oom_kill_ready="$(event_value oom_kill)"
(( oom_ready == oom_start && oom_kill_ready == oom_kill_start )) || {
    printf 'FAIL: ID36 pressure startup encountered OOM events oom:%s oom_kill:%s\n' \
        "$((oom_ready - oom_start))" "$((oom_kill_ready - oom_kill_start))" >&2
    exit 1
}

# Base memory.high on the actual ready-state charge, which already includes
# pair/helper/worker overhead. Exactly 64 MiB remains for target construction
# and replay before reclaim/throttling begins.
MEMORY_HIGH_BYTES=$((pressure_current + MEMORY_HEADROOM_BYTES))
(( MEMORY_HIGH_BYTES < MEMORY_MAX_BYTES )) || {
    printf 'FAIL: ID36 ready-state charge leaves no bounded memory.high headroom: %s bytes\n' \
        "$pressure_current" >&2
    exit 1
}
(( pressure_current + PRESSURE_RAMP_BYTES < MEMORY_MAX_BYTES )) || {
    printf 'BLOCKED: ID36 staged pressure would exceed memory.max safety bound: %s bytes\n' \
        "$pressure_current" >&2
    exit 2
}
(( PRESSURE_RAMP_BYTES > MEMORY_HEADROOM_BYTES )) || {
    printf '%s\n' 'FAIL: ID36 staged pressure must cross the memory.high headroom' >&2
    exit 1
}
echo "$MEMORY_HIGH_BYTES" > "$CGROUP/memory.high"

# Establish high-pressure evidence deliberately before releasing the benchmark.
# The final anonymous working set remains 576 MiB; only its last 80 MiB is
# faulted after memory.high is installed. This proves the cgroup is actually
# reclaiming/throttling without depending on incidental replay allocations.
high_before="$(event_value high)"
oom_before="$(event_value oom)"
oom_kill_before="$(event_value oom_kill)"

printf 'START_ID36_RESOURCE_PRESSURE=memory_high:%s memory_max:%s pressure_mib:%s cpu_workers:%s ready_bytes:%s headroom_bytes:%s ready_pressure_mib:%s ramp_mib:%s\n' \
    "$MEMORY_HIGH_BYTES" "$MEMORY_MAX_BYTES" "$PRESSURE_MIB" "$cpu_workers" \
    "$pressure_current" "$MEMORY_HEADROOM_BYTES" "$READY_PRESSURE_MIB" \
    "$PRESSURE_RAMP_MIB"

: > "$PRESSURE_ACTIVATE"
for _ in {1..800}; do
    [[ -s $PRESSURE_ACTIVE ]] && break
    kill -0 "$PRESSURE_PID" 2>/dev/null || {
        cat "$PRESSURE_LOG" >&2
        printf '%s\n' 'FAIL: ID36 pressure helper exited during staged activation' >&2
        exit 1
    }
    sleep 0.05
done
[[ -s $PRESSURE_ACTIVE ]] || {
    printf '%s\n' 'FAIL: ID36 pressure helper did not complete staged activation' >&2
    exit 1
}

high_active="$(event_value high)"
oom_active="$(event_value oom)"
oom_kill_active="$(event_value oom_kill)"
(( high_active > high_before )) || {
    printf '%s\n' 'FAIL: ID36 controlled pressure ramp did not trigger memory.high' >&2
    exit 1
}
(( oom_active == oom_before && oom_kill_active == oom_kill_before )) || {
    printf 'FAIL: ID36 staged pressure encountered OOM events oom:%s oom_kill:%s\n' \
        "$((oom_active - oom_before))" "$((oom_kill_active - oom_kill_before))" >&2
    exit 1
}

# CPU PSI qualification is scoped to the actual released pair, while the
# already-proven memory.high event remains part of the same bounded ID36 run.
cpu_some_before="$(cpu_some_total)"
: > "$PAIR_GO"
set +e
wait "$PAIR_PID"
pair_rc=$?
set -e
PAIR_PID=""
cat "$PAIR_LOG"

high_after="$(event_value high)"
oom_after="$(event_value oom)"
oom_kill_after="$(event_value oom_kill)"
cpu_some_after="$(cpu_some_total)"
peak_bytes="$(cat "$CGROUP/memory.peak" 2>/dev/null || printf '%s' "$pressure_current")"
current_after="$(cat "$CGROUP/memory.current" 2>/dev/null || printf '%s' 0)"
last_phase="$(grep -E '^BENCH_IO_PHASE=(off|swapz):(prefill|mixed|packed_read)$' "$PAIR_LOG" |
    tail -n 1 | cut -d= -f2- || true)"
[[ -n $last_phase ]] || last_phase=none

high_delta=$((high_after - high_before))
oom_delta=$((oom_after - oom_before))
oom_kill_delta=$((oom_kill_after - oom_kill_before))
cpu_some_delta=$((cpu_some_after - cpu_some_before))

if (( pair_rc != 0 )); then
    if (( oom_delta != 0 || oom_kill_delta != 0 )); then
        printf 'FAIL: ID36 cgroup OOM during owned-RAM pair oom:%s oom_kill:%s\n' \
            "$oom_delta" "$oom_kill_delta" >&2
    elif (( pair_rc == 124 || pair_rc == 137 )); then
        printf 'FAIL: ID36 outer owned-RAM pair timeout rc:%s phase:%s high:%s peak:%s current:%s cpu_psi_usec:%s\n' \
            "$pair_rc" "$last_phase" "$high_delta" "$peak_bytes" \
            "$current_after" "$cpu_some_delta" >&2
    elif grep -q 'uncompressed replay exceeded bounded timeout' "$PAIR_LOG"; then
        printf '%s\n' 'FAIL: ID36 uncompressed replay exceeded its bounded timeout under pressure' >&2
    elif grep -q 'swapz replay exceeded bounded timeout' "$PAIR_LOG"; then
        printf '%s\n' 'FAIL: ID36 swapz replay exceeded its bounded timeout under pressure' >&2
    else
        printf 'FAIL: ID36 owned-RAM pair failed rc:%s high:%s cpu_psi_usec:%s oom:%s oom_kill:%s\n' \
            "$pair_rc" "$high_delta" "$cpu_some_delta" "$oom_delta" "$oom_kill_delta" >&2
    fi
    exit 1
fi

(( high_delta > 0 )) || {
    printf '%s\n' 'FAIL: ID36 memory.high reclaim/throttle pressure was not observed' >&2
    exit 1
}
(( oom_delta == 0 && oom_kill_delta == 0 )) || {
    printf 'FAIL: ID36 encountered OOM events oom:%s oom_kill:%s\n'         "$oom_delta" "$oom_kill_delta" >&2
    exit 1
}
(( cpu_some_delta > 0 )) || {
    printf '%s\n' 'FAIL: ID36 CPU oversubscription produced no CPU PSI stall evidence' >&2
    exit 1
}
kill -0 "$PRESSURE_PID" 2>/dev/null || {
    cat "$PRESSURE_LOG" >&2
    printf '%s\n' 'FAIL: ID36 pressure helper died during qualification' >&2
    exit 1
}

printf 'PASS_ID36_RESOURCE_PRESSURE=memory_high_events:%s memory_peak_bytes:%s cpu_some_usec:%s cpu_workers:%s pressure_mib:%s oom:0 oom_kill:0\n'     "$high_delta" "$peak_bytes" "$cpu_some_delta" "$cpu_workers" "$PRESSURE_MIB"
