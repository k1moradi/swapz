#!/usr/bin/env bash
# ID36: bounded low-memory + CPU-oversubscription qualification on owned RAM only.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
source "$ROOT/tests/tools/clear-tmp-before-memory-check.sh"

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
# pair watchdog strictly outside both 280s replay bounds plus one replay-bound
# orchestration allowance for the private barrier, pressure-throttled target
# setup, comparison and teardown. This does not extend either candidate's
# forward-progress bound; it prevents the parent from preempting a legal child.
PAIR_REPLAY_TIMEOUT_SECONDS=280
PAIR_OUTER_SLACK_SECONDS=$PAIR_REPLAY_TIMEOUT_SECONDS
PAIR_OUTER_SECONDS=$((PAIR_REPLAY_TIMEOUT_SECONDS * 2 + PAIR_OUTER_SLACK_SECONDS))
MIN_AVAILABLE_KIB=$((1024 * 1024))
MIN_AVAILABLE_BYTES=$((MIN_AVAILABLE_KIB * 1024))
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
    printf '%s\n' 'BLOCKED: ID36 required owned RAM pair or pressure helper unavailable; restore readable checkout helpers before qualification' >&2
    exit 2
}
for required_command in awk bash cat cut getconf grep id mkdir mktemp od python3 \
                        rm rmdir sleep tail timeout tr; do
    command -v "$required_command" >/dev/null 2>&1 || {
        printf 'BLOCKED: ID36 missing required command %s; restore the standard qualification toolchain before retrying\n' \
            "$required_command" >&2
        exit 2
    }
done

# This marker precedes admission so an early BLOCKED result cannot inherit the
# preceding synthetic storage envelope's last benchmark phase.
printf '%s\n' 'START_ID36_RESOURCE_PRESSURE=admission'

swapz_clear_tmp_before_memory_check || {
    printf '%s\n' \
        'BLOCKED: ID36 completed-owned /tmp cleanup refused; verify session completion proofs, ownership, mounts and helper availability (no broad cleanup attempted)' >&2
    exit 2
}
printf '%s\n' 'ID36_TMP_CLEANUP=completed-owned-only'

# Read one coherent host snapshot with canonical kernel kB units. Reject
# missing, duplicated, nondecimal or unitless fields instead of treating
# malformed observations as enough free RAM.
read_host_memory_inventory() {
    awk '
        $1 == "MemTotal:" || $1 == "MemAvailable:" ||
        $1 == "MemFree:" || $1 == "Cached:" ||
        $1 == "SReclaimable:" || $1 == "SwapTotal:" ||
        $1 == "SwapFree:" {
            if (NF != 3 || $2 !~ /^(0|[1-9][0-9]*)$/ ||
                $3 != "kB" || length($2) > 18 || ++seen[$1] != 1)
                invalid = 1
            else
                values[$1] = $2
        }
        END {
            if (invalid || seen["MemTotal:"] != 1 ||
                seen["MemAvailable:"] != 1 || seen["MemFree:"] != 1 ||
                seen["Cached:"] != 1 || seen["SReclaimable:"] != 1 ||
                seen["SwapTotal:"] != 1 || seen["SwapFree:"] != 1)
                exit 1
            printf "%s %s %s %s %s %s %s\n",
                values["MemTotal:"], values["MemAvailable:"],
                values["MemFree:"], values["Cached:"],
                values["SReclaimable:"], values["SwapTotal:"],
                values["SwapFree:"]
        }
    ' "${1:-/proc/meminfo}"
}

# A prior owned-device stage may have just finished kernel teardown. Give
# normal reclaim a bounded four seconds to settle; do not drop caches, change
# swap, or relax the exact 1 GiB admission floor. Two consecutive canonical
# samples are required so a transient one-off high reading cannot admit ID36.
sample_host_memory_admission() {
    local inventory_source="${1:-/proc/meminfo}"
    local admission_sample memory_inventory total_kib available_kib free_kib
    local cached_kib reclaimable_kib swap_total_kib swap_free_kib
    local initial_available_kib="" last_available_kib="" minimum_observed_kib=""
    local maximum_observed_kib="" consecutive_sufficient=0

    for admission_sample in 1 2 3 4 5; do
        if ! memory_inventory="$(read_host_memory_inventory "$inventory_source" 2>/dev/null)"; then
            printf 'BLOCKED: ID36 MemAvailable unavailable or malformed (required:%s kB; /proc/meminfo must be readable with one canonical kB value for each inventory field)\n' \
                "$MIN_AVAILABLE_KIB" >&2
            return 2
        fi
        read -r total_kib available_kib free_kib cached_kib \
            reclaimable_kib swap_total_kib swap_free_kib <<< "$memory_inventory"
        [[ -n $initial_available_kib ]] || initial_available_kib="$available_kib"
        last_available_kib="$available_kib"
        if [[ -z $minimum_observed_kib ]] || (( available_kib < minimum_observed_kib )); then
            minimum_observed_kib="$available_kib"
        fi
        if [[ -z $maximum_observed_kib ]] || (( available_kib > maximum_observed_kib )); then
            maximum_observed_kib="$available_kib"
        fi
        if (( available_kib >= MIN_AVAILABLE_KIB )); then
            (( consecutive_sufficient += 1 ))
        else
            consecutive_sufficient=0
        fi
        (( consecutive_sufficient < 2 )) || return 0
        if [[ $admission_sample != 5 ]]; then
            sleep 1
        fi
    done
    printf 'BLOCKED: ID36 host lacks 1 GiB MemAvailable (two consecutive samples required): initial:%s last:%s minimum:%s maximum:%s required:%s unit:kB samples:5; allow ordinary reclaim or free legitimate workloads, do not drop caches or alter host swap\n' \
        "$initial_available_kib" "$last_available_kib" "$minimum_observed_kib" \
        "$maximum_observed_kib" "$MIN_AVAILABLE_KIB" >&2
    return 2
}
sample_host_memory_admission || exit 2

# Report the mounted cgroup hierarchy root separately from whole-host
# MemAvailable. Linux cgroup v2 deliberately omits memory.max/current on the
# true root cgroup because the root is exempt from resource control. A
# namespaced/non-root hierarchy root may expose both files; validate those
# values for provenance, but do not invent a second admission floor from the
# 896 MiB child containment limit.
read_cgroup_root_memory_inventory() {
    local memory_max_path="$CGROUP_ROOT/memory.max"
    local memory_current_path="$CGROUP_ROOT/memory.current"
    local memory_max memory_current headroom_status

    if [[ ! -e $memory_max_path && ! -e $memory_current_path ]]; then
        printf '%s\n' 'root-exempt root-exempt unbounded'
        return 0
    fi
    if [[ ! -e $memory_max_path || ! -e $memory_current_path ]]; then
        printf '%s\n' 'BLOCKED: ID36 parent cgroup memory.max/current telemetry incomplete; restore both controls or a verified root-exempt hierarchy' >&2
        return 2
    fi
    if ! memory_max="$(cat "$memory_max_path" 2>/dev/null)" ||
       ! memory_current="$(cat "$memory_current_path" 2>/dev/null)"; then
        printf '%s\n' 'BLOCKED: ID36 parent cgroup memory.max/current unreadable; restore readable cgroup v2 memory controls' >&2
        return 2
    fi
    if (( ${#memory_max} > 20 || ${#memory_current} > 20 )); then
        printf '%s\n' 'BLOCKED: ID36 parent cgroup memory.max/current exceeds unsigned 64-bit telemetry bounds; repair cgroup reporting' >&2
        return 2
    fi
    # cgroup byte counters are unsigned 64-bit values. Validate that range
    # exactly; digit-count checks alone admit malformed 20-digit values above
    # U64_MAX. Python also avoids Bash/awk signed or floating-point overflow.
    headroom_status="$(python3 -I -B - "$memory_max" "$memory_current" \
        "$MIN_AVAILABLE_BYTES" <<'PY'
import re
import sys

maximum_token, current_token, required_token = sys.argv[1:]
canonical = re.compile(r"0|[1-9][0-9]*")
u64_max = (1 << 64) - 1

def parse_u64(token):
    if len(token) > 20 or canonical.fullmatch(token) is None:
        raise ValueError("noncanonical decimal")
    value = int(token)
    if value > u64_max:
        raise ValueError("unsigned 64-bit overflow")
    return value

try:
    current = parse_u64(current_token)
    required = parse_u64(required_token)
    if maximum_token == "max":
        print("unbounded")
    else:
        maximum = parse_u64(maximum_token)
        if current > maximum:
            raise ValueError("memory.current exceeds memory.max")
        headroom = maximum - current
        status = "sufficient" if headroom >= required else "insufficient"
        print(status)
except ValueError as error:
    print(f"BLOCKED: ID36 parent cgroup memory.max/current invalid: {error}; repair canonical u64 cgroup telemetry", file=sys.stderr)
    raise SystemExit(2)
PY
    )" || return 2
    printf '%s %s %s\n' "$memory_max" "$memory_current" "$headroom_status"
}

if ! parent_memory_inventory="$(read_cgroup_root_memory_inventory)"; then
    exit 2
fi
read -r parent_memory_max parent_memory_current parent_headroom_status \
    parent_headroom_bytes <<< "$parent_memory_inventory"
if [[ $parent_headroom_status == insufficient ]]; then
    # The inventory reader retains its canonical three-field interface.
    # Compute large unsigned byte differences only on the refused path.
    parent_headroom_bytes="$(python3 -I -B - "$parent_memory_max" "$parent_memory_current" <<'PY'
import sys
print(int(sys.argv[1]) - int(sys.argv[2]))
PY
    )" || {
        printf '%s\n' 'BLOCKED: ID36 cannot compute validated parent cgroup headroom; restore Python u64 arithmetic' >&2
        exit 2
    }
    printf 'ID36_PARENT_CGROUP_MEMORY=source:cgroup-v2-root memory_max:%s memory_current:%s headroom:%s required_headroom_bytes:%s\n' \
        "$parent_memory_max" "$parent_memory_current" "$parent_headroom_bytes" "$MIN_AVAILABLE_BYTES" >&2
    printf 'BLOCKED: ID36 cgroup root lacks 1 GiB effective memory headroom: finite parent memory.max:%s memory.current:%s headroom:%s required:%s deficit:%s unit:bytes; raise the delegated parent limit or reduce its legitimate charge before retrying\n' \
        "$parent_memory_max" "$parent_memory_current" "$parent_headroom_bytes" \
        "$MIN_AVAILABLE_BYTES" "$((MIN_AVAILABLE_BYTES - parent_headroom_bytes))" >&2
    exit 2
fi

if ! token="$(od -An -N8 -tx1 /dev/urandom 2>/dev/null |
        tr -d '[:space:]' 2>/dev/null)"; then
    printf '%s\n' 'BLOCKED: ID36 random identity unavailable; require readable /dev/urandom and working od/tr before private cgroup creation' >&2
    exit 2
fi
[[ $token =~ ^[a-f0-9]{16}$ ]] || {
    printf '%s\n' 'BLOCKED: ID36 random identity malformed; require exactly 8 bytes of readable kernel randomness' >&2
    exit 2
}
CGROUP="$CGROUP_ROOT/swapz-id36-$token"
if ! SESSION="$(mktemp -d "${TMPDIR:-/tmp}/swapz-id36.XXXXXXXX" 2>/dev/null)"; then
    printf '%s\n' 'BLOCKED: ID36 cannot create private scratch session; require a writable temporary directory with safe mktemp semantics' >&2
    exit 2
fi
[[ -d $SESSION && ! -L $SESSION ]] || {
    printf '%s\n' 'BLOCKED: ID36 private scratch session identity is unsafe; require a newly created real directory' >&2
    exit 2
}
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

# Extract at most one short fail-only reason from a private helper log. Never
# echo paths or unbounded diagnostics from privileged children.
bounded_safe_log_reason() {
    local log_path="$1" prefix="$2"

    [[ $prefix == 'BLOCKED: ' || $prefix == 'FAIL: ' ]] || return 2
    awk -v prefix="$prefix" '
        NR > 128 { exit }
        index($0, prefix) == 1 {
            reason = substr($0, length(prefix) + 1)
            if (length(reason) > 192 || reason ~ /[\\/]/ ||
                reason ~ /[[:cntrl:]]/)
                print "diagnostic details withheld for privacy"
            else
                print reason
            exit
        }
    ' "$log_path" 2>/dev/null
}

write_cgroup_control() {
    local control="$1" value="$2"

    if ! (printf '%s\n' "$value" > "$CGROUP/$control") 2>/dev/null; then
        printf 'BLOCKED: ID36 cannot set cgroup control %s; require a writable delegated cgroup v2 memory subtree\n' \
            "$control" >&2
        return 2
    fi
}

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
    printf '%s\n' 'BLOCKED: ID36 cannot create isolated cgroup; require delegated writable cgroup v2 memory/CPU subtree without changing existing host groups' >&2
    exit 2
}
for control in memory.max memory.high memory.current memory.peak memory.events cpu.pressure cgroup.procs; do
    [[ -e "$CGROUP/$control" ]] || {
        printf 'BLOCKED: ID36 missing cgroup v2 control %s; provide delegated memory/CPU controllers and a kernel supporting this telemetry\n' "$control" >&2
        exit 2
    }
done

write_cgroup_control memory.max "$MEMORY_MAX_BYTES" || exit 2
# Establish the resident helper baseline before applying the real high
# watermark. The workload-scoped boundary is installed just before release.
write_cgroup_control memory.high "$MEMORY_MAX_BYTES" || exit 2
if [[ -e $CGROUP/memory.swap.max ]]; then
    write_cgroup_control memory.swap.max 0 || exit 2
fi

if ! online_cpus="$(getconf _NPROCESSORS_ONLN 2>/dev/null)"; then
    printf '%s\n' 'BLOCKED: ID36 online CPU count unavailable; restore working getconf _NPROCESSORS_ONLN telemetry' >&2
    exit 2
fi
[[ $online_cpus =~ ^[1-9][0-9]*$ && ${#online_cpus} -le 18 ]] || {
    printf '%s\n' 'BLOCKED: ID36 online CPU count unavailable or malformed; restore canonical getconf _NPROCESSORS_ONLN telemetry' >&2
    exit 2
}
# Clamp before multiplication so even unusual large CPU counts cannot wrap.
if (( online_cpus >= 16 )); then
    cpu_workers=32
else
    cpu_workers=$((online_cpus * 2))
    (( cpu_workers < 2 )) && cpu_workers=2
fi

# Missing, duplicate, or malformed counters are not zero OOM/PSI evidence.
# The caller inherits status 2 (BLOCKED) rather than silently passing.
event_value() {
    local name=$1
    local value
    if ! value="$(awk -v key="$name" '
        $1 == key {
            if (NF != 2 || $2 !~ /^(0|[1-9][0-9]*)$/ ||
                length($2) > 18 || ++seen != 1)
                invalid = 1
            else
                counter = $2
        }
        END {
            if (invalid || seen != 1)
                exit 1
            print counter
        }
    ' "$CGROUP/memory.events" 2>/dev/null)"; then
        printf 'BLOCKED: ID36 memory.events counter %s missing or malformed; require one canonical nonnegative decimal counter before ID36\n' "$name" >&2
        return 2
    fi
    printf '%s\n' "$value"
}
cpu_some_total() {
    local value
    if ! value="$(awk '
        $1 == "some" {
            if (++seen != 1)
                invalid = 1
            for (i = 2; i <= NF; ++i) {
                if ($i ~ /^total=/) {
                    if (++totals != 1)
                        invalid = 1
                    candidate = substr($i, 7)
                    if (candidate !~ /^(0|[1-9][0-9]*)$/ ||
                        length(candidate) > 18)
                        invalid = 1
                    else
                        total = candidate
                }
            }
        }
        END {
            if (invalid || seen != 1 || totals != 1)
                exit 1
            print total
        }
    ' "$CGROUP/cpu.pressure" 2>/dev/null)"; then
        printf '%s\n' 'BLOCKED: ID36 cpu.pressure some total missing or malformed; require one canonical nonnegative decimal some total counter before ID36' >&2
        return 2
    fi
    printf '%s\n' "$value"
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
        if ! pair_blocked_reason="$(bounded_safe_log_reason "$PAIR_LOG" 'BLOCKED: ')"; then
            printf '%s\n' 'BLOCKED: ID36 owned-RAM pair prerequisite telemetry is unreadable; preserve the private session and retry after restoring scratch access' >&2
            exit 2
        fi
        if [[ -n $pair_blocked_reason ]]; then
            printf 'BLOCKED: ID36 owned-RAM pair prerequisite before prewarm: %s\n' \
                "$pair_blocked_reason" >&2
            exit 2
        fi
        pair_fail_reason="$(bounded_safe_log_reason "$PAIR_LOG" 'FAIL: ' 2>/dev/null || true)"
        if [[ -n $pair_fail_reason ]]; then
            printf 'FAIL: ID36 owned-RAM pair exited before prewarm: %s\n' \
                "$pair_fail_reason" >&2
        else
            printf '%s\n' 'FAIL: ID36 owned-RAM pair exited before null_blk prewarm barrier without a bounded diagnostic' >&2
        fi
        exit 1
    }
    sleep 0.05
done
[[ -s $PAIR_READY ]] || {
    printf '%s\n' 'FAIL: ID36 owned-RAM pair did not reach null_blk prewarm barrier' >&2
    exit 1
}
if ! pair_cgroup_pid="$(awk -F= '$1 == "pid" && $2 ~ /^[0-9]+$/ { print $2; exit }' \
        "$PAIR_READY" 2>/dev/null)"; then
    printf '%s\n' 'BLOCKED: ID36 pair readiness telemetry became unreadable; require the owned private barrier to remain readable' >&2
    exit 2
fi
[[ $pair_cgroup_pid =~ ^[1-9][0-9]*$ ]] || {
    printf '%s\n' 'FAIL: ID36 pair readiness did not report migrated PID' >&2
    exit 1
}
if grep -Fxq "$pair_cgroup_pid" "$CGROUP/cgroup.procs" 2>/dev/null; then
    :
else
    cgroup_procs_rc=$?
    if (( cgroup_procs_rc > 1 )); then
        printf '%s\n' 'BLOCKED: ID36 cgroup.procs telemetry unreadable after pair migration; restore readable cgroup v2 process membership' >&2
        exit 2
    fi
    printf '%s\n' 'FAIL: ID36 pair did not enter pressure cgroup after prewarm' >&2
    exit 1
fi

bash -c '
    set -e
    cgroup=$1
    shift
    if ! (printf "%s\\n" "$BASHPID" > "$cgroup/cgroup.procs") 2>/dev/null; then
        printf "%s\\n" "BLOCKED: ID36 pressure helper could not enter isolated cgroup" >&2
        exit 2
    fi
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
        if ! pressure_blocked_reason="$(bounded_safe_log_reason "$PRESSURE_LOG" 'BLOCKED: ')"; then
            printf '%s\n' 'BLOCKED: ID36 pressure-helper diagnostic telemetry is unreadable; require the private scratch log to remain readable' >&2
            exit 2
        fi
        if [[ -n $pressure_blocked_reason ]]; then
            printf 'BLOCKED: ID36 pressure-helper prerequisite before readiness: %s\n' \
                "$pressure_blocked_reason" >&2
            exit 2
        fi
        pressure_fail_reason="$(bounded_safe_log_reason "$PRESSURE_LOG" 'FAIL: ' 2>/dev/null || true)"
        if [[ -n $pressure_fail_reason ]]; then
            printf 'FAIL: ID36 pressure helper exited before readiness: %s\n' \
                "$pressure_fail_reason" >&2
        else
            printf '%s\n' 'FAIL: ID36 pressure helper exited before readiness without a bounded diagnostic' >&2
        fi
        exit 1
    }
    sleep 0.05
done
[[ -s $READY ]] || {
    printf '%s\n' 'FAIL: ID36 pressure helper did not become ready' >&2
    exit 1
}

pressure_current="$(cat "$CGROUP/memory.current" 2>/dev/null)" || {
    printf '%s\n' 'BLOCKED: ID36 ready-stage memory.current unreadable; restore cgroup memory telemetry' >&2
    exit 2
}
[[ $pressure_current =~ ^(0|[1-9][0-9]*)$ &&
   ${#pressure_current} -le 18 ]] || {
    printf '%s\n' 'BLOCKED: ID36 ready-stage memory.current malformed or outside safe signed arithmetic range; restore canonical byte telemetry' >&2
    exit 2
}
(( pressure_current >= READY_PRESSURE_MIB * 1024 * 1024 )) || {
    printf 'FAIL: ID36 ready-stage resident pressure too small: observed:%s required:%s unit:bytes; inspect owned pressure helper readiness\n' \
        "$pressure_current" "$((READY_PRESSURE_MIB * 1024 * 1024))" >&2
    exit 1
}
oom_ready="$(event_value oom)"
oom_kill_ready="$(event_value oom_kill)"
if (( oom_ready < oom_start || oom_kill_ready < oom_kill_start )); then
    printf '%s\n' 'BLOCKED: ID36 memory.events OOM counters decreased across startup samples; require stable canonical cgroup telemetry' >&2
    exit 2
fi
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
    printf 'BLOCKED: ID36 ready-state charge cannot fit the memory.high boundary: observed:%s required_additional:%s memory.max:%s unit:bytes; reduce legitimate startup charge before retrying\n' \
        "$pressure_current" "$MEMORY_HEADROOM_BYTES" "$MEMORY_MAX_BYTES" >&2
    exit 2
}
(( pressure_current + PRESSURE_RAMP_BYTES < MEMORY_MAX_BYTES )) || {
    printf 'BLOCKED: ID36 staged pressure would exceed memory.max safety bound: observed:%s proposed_ramp:%s memory.max:%s unit:bytes; reduce legitimate startup charge before retrying\n' \
        "$pressure_current" "$PRESSURE_RAMP_BYTES" "$MEMORY_MAX_BYTES" >&2
    exit 2
}
(( PRESSURE_RAMP_BYTES > MEMORY_HEADROOM_BYTES )) || {
    printf '%s\n' 'FAIL: ID36 staged pressure must cross the memory.high headroom' >&2
    exit 1
}
write_cgroup_control memory.high "$MEMORY_HIGH_BYTES" || exit 2

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

if ! (: > "$PRESSURE_ACTIVATE") 2>/dev/null; then
    printf '%s\n' 'BLOCKED: ID36 cannot signal staged pressure activation; require the owned private scratch session to remain writable' >&2
    exit 2
fi
for _ in {1..800}; do
    [[ -s $PRESSURE_ACTIVE ]] && break
    kill -0 "$PRESSURE_PID" 2>/dev/null || {
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
if (( high_active < high_before || oom_active < oom_before ||
      oom_kill_active < oom_kill_before )); then
    printf '%s\n' 'BLOCKED: ID36 memory.events counters decreased during the staged ramp; require stable canonical cgroup telemetry' >&2
    exit 2
fi
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
if ! (: > "$PAIR_GO") 2>/dev/null; then
    printf '%s\n' 'BLOCKED: ID36 cannot release the owned pair barrier; require the private scratch session to remain writable' >&2
    exit 2
fi
set +e
wait "$PAIR_PID"
pair_rc=$?
set -e
PAIR_PID=""
# Preserve ordinary pair evidence only on success; a failed pair's unbounded
# private log must not be copied into admission diagnostics.
if (( pair_rc == 0 )); then
    cat "$PAIR_LOG"
fi

high_after="$(event_value high)"
oom_after="$(event_value oom)"
oom_kill_after="$(event_value oom_kill)"
cpu_some_after="$(cpu_some_total)"
peak_bytes="$(cat "$CGROUP/memory.peak" 2>/dev/null)" || {
    printf '%s\n' 'BLOCKED: ID36 memory.peak unreadable; require kernel cgroup peak telemetry' >&2
    exit 2
}
current_after="$(cat "$CGROUP/memory.current" 2>/dev/null)" || {
    printf '%s\n' 'BLOCKED: ID36 memory.current unreadable after pair; restore cgroup memory telemetry' >&2
    exit 2
}
if [[ ! $peak_bytes =~ ^(0|[1-9][0-9]*)$ ||
      ! $current_after =~ ^(0|[1-9][0-9]*)$ ||
      ${#peak_bytes} -gt 18 || ${#current_after} -gt 18 ]]; then
    printf '%s\n' 'BLOCKED: ID36 memory.peak/current malformed or outside safe signed arithmetic range; restore canonical byte telemetry' >&2
    exit 2
fi
last_phase="$(grep -E '^BENCH_IO_PHASE=(off|swapz):(prefill|mixed|packed_read)$' "$PAIR_LOG" |
    tail -n 1 | cut -d= -f2- || true)"
[[ -n $last_phase ]] || last_phase=none

if (( high_after < high_before || oom_after < oom_before ||
      oom_kill_after < oom_kill_before || cpu_some_after < cpu_some_before )); then
    printf '%s\n' 'BLOCKED: ID36 memory.events or cpu.pressure counters decreased across replay samples; require stable canonical OOM/PSI telemetry' >&2
    exit 2
fi
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
    printf '%s\n' 'FAIL: ID36 pressure helper died during qualification' >&2
    exit 1
}

printf 'PASS_ID36_RESOURCE_PRESSURE=memory_high_events:%s memory_peak_bytes:%s cpu_some_usec:%s cpu_workers:%s pressure_mib:%s oom:0 oom_kill:0\n'     "$high_delta" "$peak_bytes" "$cpu_some_delta" "$cpu_workers" "$PRESSURE_MIB"
