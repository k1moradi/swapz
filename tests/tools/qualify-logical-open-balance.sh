#!/usr/bin/env bash
# Terminal qualification of ID72: skewed-churn logical-open balancing.
# Runs five counterbalanced same-source pairs on owned RAM (null_blk) only.
# Never touches system swap, physical devices, or unrelated DM resources.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source "$ROOT/tests/tools/nullblk-identity.sh"
source "$ROOT/tests/tools/quiet-lower-io.sh"
source "$ROOT/tests/tools/swap-inventory.sh"
cd "$ROOT"

VALIDATED_SOURCE=""
if [[ $# -ge 2 && $1 == --validated-source && $2 =~ ^[0-9a-f]{40}$ ]]; then
    VALIDATED_SOURCE="$2"
    shift 2
fi
if [[ $# != 0 ]]; then
    printf '%s\n' 'Usage: qualify-logical-open-balance.sh --validated-source <sha1>' >&2
    exit 2
fi

[[ $(id -u) == 0 ]] || {
    printf '%s\n' 'BLOCKED: ID72 qualification requires root' >&2
    exit 2
}

MODULE="$ROOT/build/kernel/experimental/dm-swapz.ko"
ORACLE="$ROOT/build/tests/device-roundtrip"
CFGBASE=/sys/kernel/config/nullb

for program in insmod rmmod modprobe dmsetup modinfo blockdev readlink \
               findmnt mountpoint mount timeout sha256sum cmp od awk grep tr \
               mkdir rmdir stat tee cat ls sleep python3 sort cp; do
    command -v "$program" >/dev/null || {
        printf '%s\n' "BLOCKED: missing command $program" >&2
        exit 1
    }
done

[[ -s "$MODULE" && -x "$ORACLE" ]] || {
    printf '%s\n' "BLOCKED: swapz module or oracle not compiled" >&2
    exit 1
}

[[ ! -d /sys/module/dm_swapz && -r /proc/swaps ]] || {
    printf '%s\n' "BLOCKED: another dm_swapz loaded or swap inventory unavailable" >&2
    exit 1
}

SESSION="$(mktemp -d "${TMPDIR:-/tmp}/swapz-id72.XXXXXXXX")"
exec > >(tee -a "$SESSION/session.log") 2>&1

SWAPS_BEFORE="$(cat /proc/swaps)"
SWAPS_ID_BEFORE="$(printf '%s\n' "$SWAPS_BEFORE" |
    swapz_swap_inventory_identity /dev/stdin)" || {
    printf '%s\n' "BLOCKED: cannot parse initial host swap identity" >&2
    exit 1
}

OWN_NULL=0
OWN_DM=0
OWN_MODULE=0
QUARANTINE=0
CONFIG=""
CONFIGNAME=""
DISK=""
DEVNO=""
INDEX=""
LOWER=""
DMNAME=""
UUID=""

cleanup() {
    local rc=$? current_id
    trap - EXIT HUP INT TERM
    set +e
    if ! current_id="$(swapz_swap_inventory_identity /proc/swaps)" ||
       [[ "$current_id" != "$SWAPS_ID_BEFORE" ]]; then
        QUARANTINE=1
        printf '%s\n' "QUARANTINED: host swap identity changed before teardown"
    fi
    if (( OWN_DM && !QUARANTINE )); then
        if [[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null | tr -d '[:space:]')" == "$UUID" ]]; then
            dmsetup remove "$DMNAME" && OWN_DM=0
        fi
    fi
    if (( OWN_MODULE && !QUARANTINE )); then
        rmmod dm_swapz && OWN_MODULE=0
    fi
    if (( OWN_NULL && !QUARANTINE )); then
        echo 0 > "$CONFIG/power" 2>/dev/null || true
        rmdir "$CONFIG" 2>/dev/null && OWN_NULL=0
    fi
    if (( QUARANTINE )); then
        printf '%s\n' "BLOCKED: resources quarantined for safety; inspect $SESSION" >&2
        exit 1
    fi
    exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! mountpoint -q /sys/kernel/config; then
    modprobe configfs
    mount -t configfs configfs /sys/kernel/config || {
        printf '%s\n' "BLOCKED: could not mount configfs" >&2
        exit 1
    }
fi
if [[ ! -d "$CFGBASE" ]]; then
    modprobe null_blk nr_devices=0 || {
        printf '%s\n' "BLOCKED: cannot load null_blk" >&2
        exit 1
    }
fi

TOKEN="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
[[ "$TOKEN" =~ ^[a-f0-9]{16}$ ]] || {
    printf '%s\n' "BLOCKED: bad random test token" >&2
    exit 1
}
CONFIGNAME="nullb-swapz-$TOKEN"
CONFIG="$CFGBASE/$CONFIGNAME"
DMNAME="swapz-demo-$TOKEN"
UUID="SWAPZ-TEST-$TOKEN"

mkdir "$CONFIG" || {
    printf '%s\n' "BLOCKED: cannot create owned null_blk configfs directory" >&2
    exit 1
}
OWN_NULL=1

echo 64 > "$CONFIG/size"
echo 4096 > "$CONFIG/blocksize"
echo 1 > "$CONFIG/memory_backed"
echo 1 > "$CONFIG/discard"
echo 2 > "$CONFIG/queue_mode"
echo 1 > "$CONFIG/submit_queues"
echo 1 > "$CONFIG/hw_queue_depth"
echo 1 > "$CONFIG/power"

INDEX="$(cat "$CONFIG/index")"
for i in {1..50}; do
    DISK="$(swapz_resolve_owned_disk "$CONFIGNAME" "$INDEX" "/sys/block")" && break
    sleep 0.1
done
[[ -n "$DISK" ]] || {
    printf '%s\n' "BLOCKED: owned null_blk disk missing" >&2
    exit 1
}
DEVNO="$(cat "/sys/block/$DISK/dev")"
LOWER="/dev/$DISK"
for i in {1..50}; do
    [[ -b "$LOWER" ]] && break
    sleep 0.1
done
[[ -b "$LOWER" ]] || {
    printf '%s\n' "BLOCKED: lower block device missing" >&2
    exit 1
}
[[ "$(blockdev --getsize64 "$LOWER")" == 67108864 ]] || {
    printf '%s\n' "BLOCKED: RAM lower must be 64MiB" >&2
    exit 1
}

status_u64() {
    local line="$1" key="$2"
    [[ $line =~ (^|[[:space:]])${key}=([0-9]+)($|[[:space:]]) ]] || return 1
    printf '%s\n' "${BASH_REMATCH[2]}"
}

status_delta() {
    local key="$1" before_val after_val
    before_val="$(status_u64 "$status_before" "$key")" || return 1
    after_val="$(status_u64 "$status_after" "$key")" || return 1
    printf '%s\n' "$((after_val - before_val))"
}

printf '%s\n' "START_ID72_QUALIFICATION_PAIRS"

# Five counterbalanced pairs: 10 runs
# Modes: 0, 1, 1, 0, 0, 1, 1, 0, 0, 1
modes=(0 1 1 0 0 1 1 0 0 1)
run_index=0
RESULTS_FILE="$SESSION/results.jsonl"
rm -f "$RESULTS_FILE"

for mode in "${modes[@]}"; do
    printf 'START_ID72_RUN=%u LOGICAL_OPEN_BALANCE=%u\n' "$run_index" "$mode"
    
    # Reload dm_swapz module with the chosen logical_open_balance parameter
    if (( OWN_MODULE )); then
        rmmod dm_swapz || {
            printf '%s\n' "BLOCKED: cannot unload dm_swapz" >&2
            exit 1
        }
        OWN_MODULE=0
    fi
    insmod "$MODULE" "logical_open_balance=$mode" || {
        printf '%s\n' "BLOCKED: cannot insmod dm-swapz.ko with logical_open_balance=$mode" >&2
        exit 1
    }
    OWN_MODULE=1

    # Create 16 MiB swapz DM mapping (4,096 logical pages, window 64, gc policy 2 = io cost)
    UUID="SWAPZ-TEST-$TOKEN-run$run_index"
    dmsetup create "$DMNAME" --uuid "$UUID" \
        --table "0 32768 swapz $LOWER 0 64 0 2 0 1 0 2" || {
        printf '%s\n' "BLOCKED: cannot create swapz DM target for run $run_index" >&2
        exit 1
    }
    OWN_DM=1

    status_before="$(dmsetup status "$DMNAME")"
    [[ "$(status_u64 "$status_before" logical_open_balance)" == "$mode" ]] || {
        printf '%s\n' "BLOCKED: logical_open_balance status mismatch" >&2
        exit 1
    }

    # Execute ID72 70% churn workload
    oracle_out="$(timeout --signal=TERM --kill-after=10s 120s "$ORACLE" \
        "/dev/mapper/$DMNAME" --id72-churn 2>&1)" || {
        printf '%s\n' "$oracle_out" >&2
        printf '%s\n' "FAIL: ID72 churn execution failed on run $run_index (mode=$mode)" >&2
        exit 1
    }
    printf '%s\n' "$oracle_out"

    status_after="$(dmsetup status "$DMNAME")"

    # Extract oracle measurements
    useful_write_mbps="$(printf '%s\n' "$oracle_out" | awk '/^ID72_CHURN_EVIDENCE / {
        for (i=1; i<=NF; ++i) if ($i ~ /^useful_write_mbps:/) { split($i, a, ":"); print a[2]; }
    }')"
    write_p99_ns="$(printf '%s\n' "$oracle_out" | awk '/^ID72_CHURN_EVIDENCE / {
        for (i=1; i<=NF; ++i) if ($i ~ /^write_p99_ns:/) { split($i, a, ":"); print a[2]; }
    }')"
    write_wall_ns="$(printf '%s\n' "$oracle_out" | awk '/^ID72_CHURN_EVIDENCE / {
        for (i=1; i<=NF; ++i) if ($i ~ /^write_wall_ns:/) { split($i, a, ":"); print a[2]; }
    }')"

    # Extract DM status telemetry
    prog_min="$(status_u64 "$status_after" segment_program_min)"
    prog_max="$(status_u64 "$status_after" segment_program_max)"
    prog_sum="$(status_u64 "$status_after" segment_program_sum)"
    prog_segs="$(status_u64 "$status_after" segment_program_segments)"
    spread=$((prog_max - prog_min))

    alloc_probe_segs="$(status_delta alloc_probe_segments)"
    alloc_probe_scans="$(status_delta alloc_probe_full_scans)"
    alloc_probe_wall="$(status_delta alloc_probe_wall_ns)"

    gc_victims="$(status_delta gc_victims)"
    gc_pages="$(status_delta gc_pages)"
    gc_read="$(status_delta gc_read)"
    gc_write="$(status_delta gc_write)"
    gc_read_reqs="$(status_delta gc_read_reqs)"
    gc_write_reqs="$(status_delta gc_write_reqs)"
    gc_wall="$(status_delta gc_wall_ns)"

    trim_completed="$(status_delta segment_discards_completed)"
    trim_sectors="$(status_delta segment_discard_sectors)"
    trim_skipped="$(status_delta segment_discards_skipped_already_trimmed)"

    lower_write_bytes="$(status_delta physical_write)"
    lower_write_reqs="$(status_delta physical_write_reqs)"

    # Record JSON line
    python3 -c "
import json, sys
data = {
    'run_index': $run_index,
    'mode': $mode,
    'prog_min': $prog_min,
    'prog_max': $prog_max,
    'prog_sum': $prog_sum,
    'prog_segs': $prog_segs,
    'spread': $spread,
    'alloc_probe_segs': $alloc_probe_segs,
    'alloc_probe_scans': $alloc_probe_scans,
    'alloc_probe_wall': $alloc_probe_wall,
    'gc_victims': $gc_victims,
    'gc_pages': $gc_pages,
    'gc_read': $gc_read,
    'gc_write': $gc_write,
    'gc_read_reqs': $gc_read_reqs,
    'gc_write_reqs': $gc_write_reqs,
    'gc_wall': $gc_wall,
    'trim_completed': $trim_completed,
    'trim_sectors': $trim_sectors,
    'trim_skipped': $trim_skipped,
    'lower_write_bytes': $lower_write_bytes,
    'lower_write_reqs': $lower_write_reqs,
    'useful_write_mbps': float('$useful_write_mbps'),
    'write_p99_ns': int('$write_p99_ns'),
    'write_wall_ns': int('$write_wall_ns')
}
with open('$RESULTS_FILE', 'a') as f:
    f.write(json.dumps(data) + '\n')
"

    # Remove DM mapping
    dmsetup remove "$DMNAME" || {
        printf '%s\n' "BLOCKED: cannot remove swapz DM mapping on run $run_index" >&2
        exit 1
    }
    OWN_DM=0

    printf 'PASS_ID72_RUN=%u LOGICAL_OPEN_BALANCE=%u spread=%u (min=%u max=%u sum=%u) gc_victims=%u lower_write_bytes=%u useful_mbps=%.2f p99_us=%.1f\n' \
        "$run_index" "$mode" "$spread" "$prog_min" "$prog_max" "$prog_sum" \
        "$gc_victims" "$lower_write_bytes" "$useful_write_mbps" "$((write_p99_ns / 1000))"

    (( run_index += 1 ))
done

printf '%s\n' "PASS_ID72_QUALIFICATION_PAIRS"

# Statistical evaluation of the 5 pairs
python3 -B - "$RESULTS_FILE" <<'PY'
import json
import math
import sys

with open(sys.argv[1], "r") as f:
    records = [json.loads(line) for line in f]

assert len(records) == 10, f"Expected 10 runs, got {len(records)}"

# Map into 5 pairs
# Runs: (0,1), (2,3), (4,5), (6,7), (8,9)
pairs = []
for p in range(5):
    r_a = records[p * 2]
    r_b = records[p * 2 + 1]
    if r_a["mode"] == 0 and r_b["mode"] == 1:
        arm0, arm1 = r_a, r_b
    elif r_a["mode"] == 1 and r_b["mode"] == 0:
        arm0, arm1 = r_b, r_a
    else:
        raise ValueError(f"Pair {p} does not contain one 0 and one 1 mode")
    pairs.append((arm0, arm1))

spreads_0 = [arm0["spread"] for arm0, arm1 in pairs]
spreads_1 = [arm1["spread"] for arm0, arm1 in pairs]

print("\n================== ID72 STATISTICAL SUMMARY ==================")
print(f"Arm 0 (unbalanced) spreads: {spreads_0}")
print(f"Arm 1 (balanced)   spreads: {spreads_1}")

all_unbalanced_le_1 = all(s <= 1 for s in spreads_0)
if all_unbalanced_le_1:
    print("\nDECISION=REMOVE_SWITCH: Every unbalanced arm already has max-min <= 1.")
    print("The workload exposes no useful balancing opportunity; remove the switch and retain circular allocator fairness.")
    sys.exit(0)

# Evaluate paired differences: delta = spread_0 - spread_1 (positive is favorable to balanced)
deltas = [s0 - s1 for s0, s1 in zip(spreads_0, spreads_1)]
mean_0 = sum(spreads_0) / 5.0
mean_1 = sum(spreads_1) / 5.0
mean_delta = sum(deltas) / 5.0
var_delta = sum((d - mean_delta) ** 2 for d in deltas) / 4.0
std_delta = math.sqrt(var_delta)
se_delta = std_delta / math.sqrt(5.0)

# Student's t for 4 d.o.f. at 95% two-sided is 2.776
t_crit = 2.7764
ci_low = mean_delta - t_crit * se_delta
ci_high = mean_delta + t_crit * se_delta

mean_reduction_pct = ((mean_0 - mean_1) / mean_0) * 100.0 if mean_0 > 0 else 0.0

print(f"Mean spread: Arm 0 = {mean_0:.2f}, Arm 1 = {mean_1:.2f}")
print(f"Mean spread reduction: {mean_reduction_pct:.2f}%")
print(f"Paired delta (Arm 0 - Arm 1): mean = {mean_delta:.2f}, 95% CI = [{ci_low:.2f}, {ci_high:.2f}]")

# Check guard metrics (no paired regression > 5% in harmful direction)
# Throughput: higher is better -> regression if arm1 < arm0
# Latency p99: lower is better -> regression if arm1 > arm0
# GC write bytes: lower is better -> regression if arm1 > arm0
# Allocator probe wall: lower is better -> regression if arm1 > arm0
# Lower write bytes: lower is better -> regression if arm1 > arm0
# Lower write reqs: lower is better -> regression if arm1 > arm0

def check_guard(name, values_0, values_1, higher_is_better):
    m0 = sum(values_0) / 5.0
    m1 = sum(values_1) / 5.0
    if higher_is_better:
        reg_pct = ((m0 - m1) / m0) * 100.0 if m0 > 0 else 0.0
    else:
        reg_pct = ((m1 - m0) / m0) * 100.0 if m0 > 0 else 0.0
    passed = reg_pct <= 5.0
    status = "PASS" if passed else "REGRESSION"
    print(f"Guard {name:20s}: Arm0={m0:.1f}, Arm1={m1:.1f}, Harmful Delta={reg_pct:+.2f}% [{status}]")
    return passed

guards_passed = True
guards_passed &= check_guard("Useful Throughput", [a0["useful_write_mbps"] for a0, a1 in pairs], [a1["useful_write_mbps"] for a0, a1 in pairs], higher_is_better=True)
guards_passed &= check_guard("Write p99 Latency", [a0["write_p99_ns"] for a0, a1 in pairs], [a1["write_p99_ns"] for a0, a1 in pairs], higher_is_better=False)
guards_passed &= check_guard("GC Write Bytes",    [a0["gc_write"] for a0, a1 in pairs], [a1["gc_write"] for a0, a1 in pairs], higher_is_better=False)
guards_passed &= check_guard("Alloc Probe Wall",  [a0["alloc_probe_wall"] for a0, a1 in pairs], [a1["alloc_probe_wall"] for a0, a1 in pairs], higher_is_better=False)
guards_passed &= check_guard("Lower Write Bytes", [a0["lower_write_bytes"] for a0, a1 in pairs], [a1["lower_write_bytes"] for a0, a1 in pairs], higher_is_better=False)
guards_passed &= check_guard("Lower Write Reqs",  [a0["lower_write_reqs"] for a0, a1 in pairs], [a1["lower_write_reqs"] for a0, a1 in pairs], higher_is_better=False)

print("==============================================================\n")

if mean_reduction_pct >= 20.0 and ci_low > 0.0 and guards_passed:
    print("DECISION=PROMOTE_TO_DEFAULT_ON: Spread reduction >= 20%, 95% CI excludes 0, all guards pass.")
else:
    reasons = []
    if mean_reduction_pct < 20.0:
        reasons.append(f"spread reduction {mean_reduction_pct:.1f}% < 20%")
    if ci_low <= 0.0:
        reasons.append(f"95% CI [{ci_low:.2f}, {ci_high:.2f}] does not strictly exclude zero")
    if not guards_passed:
        reasons.append("one or more guard metrics regressed > 5%")
    print(f"DECISION=REMOVE_SWITCH: Criteria for promotion not met ({', '.join(reasons)}).")
PY

printf '%s\n' "PASS_ID72_QUALIFICATION_COMPLETE"
