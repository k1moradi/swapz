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
    printf '%s\n' 'BLOCKED: ID36 helper files unavailable' >&2
    exit 2
}

# This marker precedes admission so an early BLOCKED result cannot inherit the
# preceding synthetic storage envelope's last benchmark phase.
printf '%s\n' 'START_ID36_RESOURCE_PRESSURE=admission'

# Completed OFF/swapz pairs retain a private fixture snapshot and copied
# immutable replay inputs under /tmp for investigation. Before the 1 GiB
# headroom gate, remove only those large inputs from positively identified,
# successful sessions whose owning benchmark process has exited. Keep session
# logs, reports, markers, failures, quarantines, and all non-Swapz /tmp data.
cleanup_completed_benchmark_scratch() {
    local tmp_root candidate_tmp session owner_marker complete_marker session_log
    local pid source_sha command_line scratch bytes local_path
    local -a owner_fields complete_fields
    local reclaimed=0 sessions=0
    local roots=(/tmp)
    if [[ ${TMPDIR:-} == /* ]]; then
        candidate_tmp="$TMPDIR"
        while [[ $candidate_tmp != / && $candidate_tmp == */ ]]; do
            candidate_tmp="${candidate_tmp%/}"
        done
        if [[ $candidate_tmp != / && $candidate_tmp != /tmp ]]; then
            roots+=("$candidate_tmp")
        fi
    fi

    for tmp_root in "${roots[@]}"; do
        [[ -d $tmp_root && ! -L $tmp_root ]] || continue
        [[ $(stat -c '%u' -- "$tmp_root" 2>/dev/null) == 0 ]] || continue
        for session in "$tmp_root"/swapz-benchmark.*; do
            [[ -e $session || -L $session ]] || continue
            [[ -d $session && ! -L $session ]] || continue
            [[ $(stat -c '%u:%a' -- "$session" 2>/dev/null) == 0:700 ]] || continue

            owner_marker="$session/.swapz-benchmark-owner"
            complete_marker="$session/.swapz-benchmark-complete"
            session_log="$session/session.log"
            [[ -f $owner_marker && ! -L $owner_marker &&
               $(stat -c '%u:%a' -- "$owner_marker" 2>/dev/null) == 0:600 ]] || {
                printf '%s\n' \
                    'BLOCKED: unmarked Swapz benchmark session prevents ID36 memory admission' >&2
                return 1
            }
            mapfile -t owner_fields < "$owner_marker"
            (( ${#owner_fields[@]} == 2 )) || {
                printf '%s\n' 'BLOCKED: malformed Swapz benchmark owner marker' >&2
                return 1
            }
            [[ ${owner_fields[0]} =~ ^pid=([1-9][0-9]*)$ ]] || {
                printf '%s\n' 'BLOCKED: malformed Swapz benchmark owner PID' >&2
                return 1
            }
            pid="${BASH_REMATCH[1]}"
            [[ ${owner_fields[1]} =~ ^source_sha=([a-f0-9]{40})$ ]] || {
                printf '%s\n' 'BLOCKED: malformed Swapz benchmark source identity' >&2
                return 1
            }
            source_sha="${BASH_REMATCH[1]}"

            # Any live session blocks the memory-pressure phase, even if it
            # has not reached the successful-completion marker.
            if [[ -r /proc/$pid/cmdline ]]; then
                command_line="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
                if [[ $command_line == *benchmark-owned-pair.sh* ]]; then
                    printf '%s\n' \
                        'BLOCKED: a swapz benchmark pair is still active during ID36 cleanup' >&2
                    return 1
                fi
            fi

            [[ -f $complete_marker && ! -L $complete_marker &&
               -f $session_log && ! -L $session_log &&
               $(stat -c '%u:%a' -- "$complete_marker" 2>/dev/null) == 0:600 ]] || {
                printf '%s\n' \
                    'BLOCKED: incomplete Swapz benchmark session prevents ID36 memory admission' >&2
                return 1
            }
            mapfile -t complete_fields < "$complete_marker"
            (( ${#complete_fields[@]} == 2 )) || {
                printf '%s\n' 'BLOCKED: malformed Swapz benchmark completion marker' >&2
                return 1
            }
            [[ ${complete_fields[0]} == "pid=$pid" &&
               ${complete_fields[1]} == "source_sha=$source_sha" ]] || {
                printf '%s\n' \
                    'BLOCKED: inconsistent Swapz benchmark completion identity' >&2
                return 1
            }

            if [[ -e $session/plan || -L $session/plan ]]; then
                [[ -d $session/plan && ! -L $session/plan &&
                   $(stat -c '%u:%a' -- "$session/plan" 2>/dev/null) == 0:700 ]] || {
                    printf '%s\n' \
                        'BLOCKED: unexpected object in owned benchmark plan path' >&2
                    return 1
                }
            fi
            for scratch in fixture.bin plan/trace.jsonl plan/manifest.json; do
                local_path="$session/$scratch"
                [[ -e $local_path || -L $local_path ]] || continue
                [[ -f $local_path && ! -L $local_path ]] || {
                    printf '%s\n' 'BLOCKED: unexpected object in owned benchmark scratch path' >&2
                    return 1
                }
                bytes="$(stat -c '%s' -- "$local_path")" || return 1
                rm -- "$local_path" || return 1
                reclaimed=$((reclaimed + bytes))
            done
            rmdir -- "$session/plan" 2>/dev/null || true
            (( sessions += 1 ))
        done
    done
    printf 'ID36_BENCHMARK_TMP_CLEANUP=sessions:%s bytes:%s\n' \
        "$sessions" "$reclaimed"
}

cleanup_completed_benchmark_scratch || {
    printf '%s\n' \
        'BLOCKED: cannot safely clear completed Swapz benchmark scratch before memory admission' >&2
    exit 2
}

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
                $3 != "kB" || ++seen[$1] != 1)
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
    ' /proc/meminfo
}

# A prior owned-device stage may have just finished kernel teardown. Give
# normal reclaim a bounded four seconds to settle; do not drop caches, change
# swap, or relax the exact 1 GiB admission floor.
initial_available_kib=""
for admission_sample in 1 2 3 4 5; do
    if ! memory_inventory="$(read_host_memory_inventory)"; then
        printf '%s\n' 'BLOCKED: ID36 cannot obtain canonical /proc/meminfo kB inventory' >&2
        exit 2
    fi
    read -r total_kib available_kib free_kib cached_kib         reclaimable_kib swap_total_kib swap_free_kib <<< "$memory_inventory"
    [[ -n $initial_available_kib ]] || initial_available_kib="$available_kib"
    if (( available_kib >= MIN_AVAILABLE_KIB )); then
        break
    fi
    if [[ $admission_sample != 5 ]]; then
        sleep 1
    fi
done
deficit_kib=0
if (( available_kib < MIN_AVAILABLE_KIB )); then
    deficit_kib=$((MIN_AVAILABLE_KIB - available_kib))
fi
printf 'ID36_HOST_MEMORY=source:/proc/meminfo unit:kB total:%s initial_available:%s available:%s required:%s deficit:%s free:%s cached:%s sreclaimable:%s swap_total:%s swap_free:%s samples:%s\n'     "$total_kib" "$initial_available_kib" "$available_kib"     "$MIN_AVAILABLE_KIB" "$deficit_kib" "$free_kib" "$cached_kib"     "$reclaimable_kib" "$swap_total_kib" "$swap_free_kib"     "$admission_sample"

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
    [[ -e $memory_max_path && -e $memory_current_path ]] || return 1
    memory_max="$(cat "$memory_max_path" 2>/dev/null)" || return 1
    memory_current="$(cat "$memory_current_path" 2>/dev/null)" || return 1
    if [[ $memory_max != max &&
          ! $memory_max =~ ^(0|[1-9][0-9]*)$ ]]; then
        return 1
    fi
    [[ $memory_current =~ ^(0|[1-9][0-9]*)$ ]] || return 1
    if [[ $memory_max == max ]]; then
        headroom_status=unbounded
    else
        headroom_status="$(awk -v limit="$memory_max" \
            -v current="$memory_current" -v required="$MIN_AVAILABLE_BYTES" '
            BEGIN {
                if (current > limit)
                    exit 1
                if ((limit - current) >= required)
                    print "sufficient"
                else
                    print "insufficient"
            }
        ')" || return 1
    fi
    printf '%s %s %s\n' "$memory_max" "$memory_current" "$headroom_status"
}

if ! parent_memory_inventory="$(read_cgroup_root_memory_inventory)"; then
    printf '%s\n' 'BLOCKED: ID36 cgroup-root memory inventory is inconsistent or malformed' >&2
    exit 2
fi
read -r parent_memory_max parent_memory_current parent_headroom_status \
    <<< "$parent_memory_inventory"
printf 'ID36_PARENT_CGROUP_MEMORY=source:%s memory_max:%s memory_current:%s headroom:%s required_headroom_bytes:%s\n' \
    "$CGROUP_ROOT" "$parent_memory_max" "$parent_memory_current" \
    "$parent_headroom_status" "$MIN_AVAILABLE_BYTES"
if [[ $parent_headroom_status == insufficient ]]; then
    printf '%s\n' 'BLOCKED: ID36 cgroup root lacks 1 GiB effective memory headroom' >&2
    exit 2
fi
if (( available_kib < MIN_AVAILABLE_KIB )); then
    printf '%s\n' 'BLOCKED: ID36 host lacks 1 GiB MemAvailable safety headroom' >&2
    exit 2
fi

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

# Missing, duplicate, or malformed counters are not zero OOM/PSI evidence.
# The caller inherits status 2 (BLOCKED) rather than silently passing.
event_value() {
    local name=$1
    local value
    if ! value="$(awk -v key="$name" '
        $1 == key {
            if (NF != 2 || $2 !~ /^(0|[1-9][0-9]*)$/ ||
                ++seen != 1)
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
        printf 'BLOCKED: ID36 memory.events counter %s missing or malformed\n' "$name" >&2
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
                    if (candidate !~ /^(0|[1-9][0-9]*)$/)
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
        printf '%s\n' 'BLOCKED: ID36 cpu.pressure some total missing or malformed' >&2
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
