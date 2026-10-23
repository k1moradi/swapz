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
MEMORY_HIGH_BYTES=$((576 * 1024 * 1024))
MEMORY_MAX_BYTES=$((896 * 1024 * 1024))
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
STOP="$SESSION/pressure.stop"
PRESSURE_LOG="$SESSION/pressure.log"
PRESSURE_PID=""

cleanup() {
    local result=$?
    trap - EXIT HUP INT TERM
    set +e
    : > "$STOP"
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
echo "$MEMORY_HIGH_BYTES" > "$CGROUP/memory.high"
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

high_before="$(event_value high)"
oom_before="$(event_value oom)"
oom_kill_before="$(event_value oom_kill)"
cpu_some_before="$(cpu_some_total)"

# Enter the child cgroup before allocating so both resident pressure and CPU
# burners are accounted to the bounded ID36 domain.
bash -c '
    set -e
    cgroup=$1
    shift
    echo $$ > "$cgroup/cgroup.procs"
    exec "$@"
' _ "$CGROUP" python3 -B "$PRESSURE_SCRIPT"     --memory-mib "$PRESSURE_MIB" --cpu-workers "$cpu_workers"     --ready-file "$READY" --stop-file "$STOP" >"$PRESSURE_LOG" 2>&1 &
PRESSURE_PID=$!

for _ in {1..400}; do
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
   $pressure_current -ge $((PRESSURE_MIB * 1024 * 1024)) ]] || {
    printf 'FAIL: ID36 resident pressure too small: %s bytes\n' "$pressure_current" >&2
    exit 1
}

printf 'START_ID36_RESOURCE_PRESSURE=memory_high:%s memory_max:%s pressure_mib:%s cpu_workers:%s\n'     "$MEMORY_HIGH_BYTES" "$MEMORY_MAX_BYTES" "$PRESSURE_MIB" "$cpu_workers"

# Use the production async policy and the fast/deep owned-RAM model. The normal
# pair still performs final byte-exact packed readback and ordinary teardown.
if ! bash -c '
    set -e
    cgroup=$1
    shift
    echo $$ > "$cgroup/cgroup.procs"
    exec "$@"
' _ "$CGROUP" timeout --signal=TERM --kill-after=10s 300s     "$PAIR" --validated-source "$VALIDATED_SOURCE"     --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced     --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000     --async-prepare --shared-plan "$SHARED_PLAN"; then
    printf '%s\n' 'FAIL: ID36 owned-RAM pair failed under resource pressure' >&2
    exit 1
fi

high_after="$(event_value high)"
oom_after="$(event_value oom)"
oom_kill_after="$(event_value oom_kill)"
cpu_some_after="$(cpu_some_total)"
peak_bytes="$(cat "$CGROUP/memory.peak" 2>/dev/null || printf '%s' "$pressure_current")"

high_delta=$((high_after - high_before))
oom_delta=$((oom_after - oom_before))
oom_kill_delta=$((oom_kill_after - oom_kill_before))
cpu_some_delta=$((cpu_some_after - cpu_some_before))

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
