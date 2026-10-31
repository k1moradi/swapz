#!/usr/bin/env bash
# Development-only N-target striped raw/swapz comparison on freshly owned RAM null_blk.
# Never touches system swap, physical devices, or unrelated Device Mapper resources.
set -Eeuo pipefail
umask 077

VALIDATED_SOURCE=""
if [[ $# -ge 3 && $1 == --validated-source &&
      $2 =~ ^[0-9a-f]{40}$ ]]; then
    VALIDATED_SOURCE="$2"
    shift 2
fi
SWAPZ_FIRST=0
if [[ $# -gt 0 && ${!#} == --swapz-first ]]; then
    SWAPZ_FIRST=1
    set -- "${@:1:$(( $# - 1 ))}"
fi
if [[ $# != 7 || $1 != --run-owned-striped || $2 != --model ||
      $4 != --stripes || $6 != --shared-plan ]]; then
    printf '%s\n' 'BLOCKED: exact private striped-development contract required' >&2
    exit 2
fi
MODEL="$3"
STRIPES="$5"
SHARED_PLAN="$7"
[[ $MODEL == nvme5 || $MODEL == sata ]] ||
    { printf '%s\n' 'BLOCKED: striped model must be nvme5 or sata' >&2; exit 2; }
[[ $STRIPES == 1 || $STRIPES == 2 || $STRIPES == 4 ]] ||
    { printf '%s\n' 'BLOCKED: striped count must be 1, 2 or 4' >&2; exit 2; }

case "$MODEL:$STRIPES" in
    nvme5:1) LOWER_MBPS=12000; COMPLETION_NSEC=14000; SUBMIT_QUEUES=4; HW_QUEUE_DEPTH=64 ;;
    nvme5:2) LOWER_MBPS=6000;  COMPLETION_NSEC=14000; SUBMIT_QUEUES=4; HW_QUEUE_DEPTH=32 ;;
    nvme5:4) LOWER_MBPS=3000;  COMPLETION_NSEC=14000; SUBMIT_QUEUES=4; HW_QUEUE_DEPTH=16 ;;
    sata:1)  LOWER_MBPS=500;   COMPLETION_NSEC=100000; SUBMIT_QUEUES=1; HW_QUEUE_DEPTH=32 ;;
    sata:2)  LOWER_MBPS=250;   COMPLETION_NSEC=100000; SUBMIT_QUEUES=1; HW_QUEUE_DEPTH=16 ;;
    sata:4)  LOWER_MBPS=125;   COMPLETION_NSEC=100000; SUBMIT_QUEUES=1; HW_QUEUE_DEPTH=8 ;;
esac
IRQMODE=2
QUEUE_MODE=2

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source "$ROOT/tests/tools/nullblk-identity.sh"
source "$ROOT/tests/tools/swap-inventory.sh"
cd "$ROOT"

note() { printf '%s\n' "$*"; }
fail() { note "BLOCKED: $*" >&2; exit 2; }
devno() {
    local encoded major minor
    encoded="$(stat -Lc '%t:%T' "$1")" || return 1
    IFS=: read -r major minor <<< "$encoded"
    printf '%d:%d\n' "0x$major" "0x$minor"
}
settle_udev() {
    command -v udevadm >/dev/null 2>&1 &&
        udevadm settle --timeout=3 >/dev/null 2>&1 || true
}
active_swap_dev() {
    local dev="$1" path rest
    while read -r path rest; do
        [[ $path == Filename || ! -e $path ]] && continue
        [[ "$(devno "$path" 2>/dev/null || true)" != "$dev" ]] || return 0
    done < /proc/swaps
    return 1
}

for command in insmod rmmod modprobe dmsetup modinfo blockdev readlink \
               findmnt mountpoint timeout sha256sum cmp od awk grep tr \
               mkdir rmdir stat cat ls sleep python3 sort cp rm; do
    command -v "$command" >/dev/null || fail "missing command $command"
done
[[ $(id -u) == 0 ]] || fail 'root required for striped owned-RAM development'
[[ "$VALIDATED_SOURCE" =~ ^[0-9a-f]{40}$ ]] ||
    fail 'unprivileged parent did not provide a validated source revision'
[[ -x build/tests/native/io-replay-native ]] ||
    fail 'native replay helper missing from validated build'
[[ $SHARED_PLAN == "$ROOT/build/tests/benchmark-plan."* &&
   -d $SHARED_PLAN && ! -L $SHARED_PLAN &&
   -f $SHARED_PLAN/fixture.bin && ! -L $SHARED_PLAN/fixture.bin ]] ||
    fail 'striped shared plan is missing or outside owned build root'
for (( stripe=0; stripe<STRIPES; ++stripe )); do
    child="$SHARED_PLAN/striped-$STRIPES/stripe-$stripe"
    [[ -d $child && ! -L $child &&
       -f $child/trace.jsonl && ! -L $child/trace.jsonl &&
       -f $child/manifest.json && ! -L $child/manifest.json ]] ||
        fail 'striped child plan missing or symbolic'
done

MODULE="$ROOT/build/kernel/experimental/dm-swapz.ko"
version="$(cat src/kernel/VERSION)"
[[ "$version" =~ ^3[.]0[.]0-alpha[.][0-9]+$ ]] ||
    fail 'malformed canonical swapz version'
[[ "$(modinfo -F version "$MODULE")" == "$version" ]] ||
    fail 'built swapz module version mismatch'
[[ -s $MODULE && $(modinfo -F vermagic "$MODULE" | awk '{print $1}') == "$(uname -r)" ]] ||
    fail 'swapz module missing or running-kernel vermagic mismatch'
for file in Makefile dm-target.c codec.c authority.c engine.c codec.h \
            authority.h engine.h flush-qual.h gc-cost.h preparation-slots.h; do
    cmp -s "src/kernel/$file" "build/kernel/experimental/$file" ||
        fail "staged kernel source mismatch: $file"
done
[[ ! -d /sys/module/dm_swapz && -r /proc/swaps ]] ||
    fail 'another dm_swapz is loaded or swap inventory is unavailable'

CFGBASE=/sys/kernel/config/nullb
declare -a NAMES=() CONFIGS=() DISKS=() INDEXES=() DEVS=() LOWERS=()
declare -a DMNAMES=() DMUUIDS=() DMDEVS=() DMKNAMES=() OWN_DMS=()
declare -a CHILD_PIDS=()
COUNT=0
READY_COUNT=0
OWN_MODULE=0
QUARANTINE=0
SESSION="$(mktemp -d "${TMPDIR:-/tmp}/swapz-striped.XXXXXXXX")"
SWAPS_ID="$(swapz_swap_inventory_identity /proc/swaps)" ||
    fail 'cannot parse initial host swap identity'

terminate_children() {
    local pid
    for pid in "${CHILD_PIDS[@]:-}"; do
        [[ -n $pid ]] || continue
        kill -TERM "$pid" >/dev/null 2>&1 || true
    done
    for pid in "${CHILD_PIDS[@]:-}"; do
        [[ -n $pid ]] || continue
        wait "$pid" >/dev/null 2>&1 || true
    done
    CHILD_PIDS=()
}

remove_owned_config() {
    local index="$1" attempt
    echo 0 > "${CONFIGS[index]}/power" || return 1
    settle_udev
    for (( attempt=0; attempt<30; ++attempt )); do
        [[ ! -e /sys/block/${DISKS[index]} ]] && break
        sleep 0.1
        settle_udev
    done
    [[ ! -e /sys/block/${DISKS[index]} ]] || return 2
    for (( attempt=0; attempt<30; ++attempt )); do
        rmdir "${CONFIGS[index]}" 2>/dev/null && return 0
        sleep 0.1
    done
    return 3
}

cleanup() {
    local result=$? current_id index current_uuid opens valid=1
    trap - EXIT HUP INT TERM
    set +e
    terminate_children
    current_id="$(swapz_swap_inventory_identity /proc/swaps 2>/dev/null)" ||
        current_id=INVALID
    if [[ "$current_id" != "$SWAPS_ID" ]]; then
        QUARANTINE=1
        note 'QUARANTINED: host swap identity changed during striped experiment'
    fi
    if (( COUNT != READY_COUNT )); then
        QUARANTINE=1
        note 'QUARANTINED: partially initialized striped RAM identity'
    fi
    for (( index=0; index<${#DMNAMES[@]}; ++index )); do
        (( ${OWN_DMS[index]:-0} )) || continue
        current_uuid="$(dmsetup info -c --noheadings -o uuid "${DMNAMES[index]}" 2>/dev/null |
            tr -d '[:space:]')"
        [[ "$current_uuid" == "${DMUUIDS[index]}" ]] || valid=0
    done
    for (( index=0; index<READY_COUNT; ++index )); do
        [[ ${NAMES[index]} =~ ^nullb-swapz-[a-f0-9]{16}$ &&
           ${CONFIGS[index]} == "$CFGBASE/${NAMES[index]}" &&
           "$(cat "${CONFIGS[index]}/index" 2>/dev/null)" == "${INDEXES[index]}" &&
           "$(cat "${CONFIGS[index]}/power" 2>/dev/null)" == 1 &&
           "$(cat "${CONFIGS[index]}/memory_backed" 2>/dev/null)" == 1 &&
           "$(cat "/sys/block/${DISKS[index]}/dev" 2>/dev/null)" == "${DEVS[index]}" &&
           "$(devno "${LOWERS[index]}" 2>/dev/null)" == "${DEVS[index]}" &&
           -z "$(findmnt -rn -S "${LOWERS[index]}" 2>/dev/null)" ]] || valid=0
        active_swap_dev "${DEVS[index]}" && valid=0
    done
    if (( !valid )); then
        QUARANTINE=1
        note 'QUARANTINED: striped owned identity changed before teardown'
    fi
    if (( !QUARANTINE )); then
        for (( index=${#DMNAMES[@]}-1; index>=0; --index )); do
            (( ${OWN_DMS[index]:-0} )) || continue
            opens=unknown
            for _ in {1..30}; do
                opens="$(dmsetup info -c --noheadings -o open "${DMNAMES[index]}" 2>/dev/null |
                    tr -d '[:space:]')"
                [[ "$opens" == 0 ]] && break
                sleep 0.1
            done
            if [[ "$opens" != 0 ]] ||
               ! timeout --signal=TERM --kill-after=2s 10s \
                    dmsetup remove --retry "${DMNAMES[index]}"; then
                QUARANTINE=1
                note 'QUARANTINED: striped mapper did not close cleanly'
                break
            fi
            OWN_DMS[index]=0
            settle_udev
        done
    fi
    if (( !QUARANTINE )); then
        for (( index=0; index<READY_COUNT; ++index )); do
            if [[ -d /sys/block/${DISKS[index]}/holders &&
                  -n "$(ls -A "/sys/block/${DISKS[index]}/holders" 2>/dev/null)" ]]; then
                QUARANTINE=1
                note 'QUARANTINED: striped lower retained a holder after mapper removal'
                break
            fi
        done
    fi
    if (( !QUARANTINE )); then
        for (( index=READY_COUNT-1; index>=0; --index )); do
            remove_owned_config "$index" || {
                QUARANTINE=1
                note 'QUARANTINED: striped owned RAM teardown failed'
                break
            }
        done
    fi
    if (( OWN_MODULE && !QUARANTINE )); then
        rmmod dm_swapz || {
            QUARANTINE=1
            note 'QUARANTINED: dm_swapz remained busy after striped experiment'
        }
    fi
    if (( QUARANTINE )); then
        result=1
        note "BLOCKED: retained striped evidence/resources at $SESSION"
    elif (( result == 0 )); then
        rm -rf -- "$SESSION"
    fi
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! mountpoint -q /sys/kernel/config; then
    modprobe configfs
    mount -t configfs configfs /sys/kernel/config || fail 'cannot mount configfs'
fi
if [[ ! -d $CFGBASE ]]; then
    modprobe null_blk nr_devices=0 || fail 'null_blk configfs missing'
fi
[[ -d $CFGBASE ]] || fail 'null_blk configfs missing'
NULL_MAJOR="$(awk '/^Block devices:/{ok=1;next} ok && $2=="nullb"{print $1;exit}' /proc/devices)"
[[ $NULL_MAJOR =~ ^[0-9]+$ ]] || fail 'null_blk major absent'

create_owned_ram() {
    local token name config index disk="" dev lower attr attempt
    token="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
    [[ $token =~ ^[a-f0-9]{16}$ ]] || fail 'random null_blk identity invalid'
    name="nullb-swapz-$token"
    config="$CFGBASE/$name"
    [[ ! -e $config ]] || fail 'null_blk identity collision'
    mkdir "$config" || fail 'cannot create striped RAM config'
    NAMES[COUNT]="$name"
    CONFIGS[COUNT]="$config"
    (( COUNT += 1 ))
    for attr in size blocksize memory_backed power index mbps irqmode \
                completion_nsec queue_mode submit_queues hw_queue_depth; do
        [[ -e "$config/$attr" ]] || fail "owned RAM lacks $attr"
    done
    echo 64 > "$config/size"
    echo 4096 > "$config/blocksize"
    echo 1 > "$config/memory_backed"
    echo "$LOWER_MBPS" > "$config/mbps"
    echo "$COMPLETION_NSEC" > "$config/completion_nsec"
    echo "$IRQMODE" > "$config/irqmode"
    echo "$QUEUE_MODE" > "$config/queue_mode"
    echo "$SUBMIT_QUEUES" > "$config/submit_queues"
    echo "$HW_QUEUE_DEPTH" > "$config/hw_queue_depth"
    [[ "$(cat "$config/mbps")" == "$LOWER_MBPS" &&
       "$(cat "$config/completion_nsec")" == "$COMPLETION_NSEC" &&
       "$(cat "$config/irqmode")" == "$IRQMODE" &&
       "$(cat "$config/queue_mode")" == "$QUEUE_MODE" &&
       "$(cat "$config/submit_queues")" == "$SUBMIT_QUEUES" &&
       "$(cat "$config/hw_queue_depth")" == "$HW_QUEUE_DEPTH" ]] ||
        fail 'owned striped RAM model rejected requested geometry'
    echo 1 > "$config/power"
    index="$(cat "$config/index")"
    [[ $index =~ ^(0|[1-9][0-9]*)$ ]] || fail 'owned striped index invalid'
    for (( attempt=0; attempt<50; ++attempt )); do
        disk="$(swapz_resolve_owned_disk "$name" "$index" /sys/block)" && break
        sleep 0.1
    done
    [[ -n $disk ]] || fail 'owned striped disk absent or ambiguous'
    dev="$(cat "/sys/block/$disk/dev")"
    [[ "$dev" == "$NULL_MAJOR:$index" &&
       "$(readlink -f "/sys/dev/block/$dev")" == "$(readlink -f "/sys/block/$disk")" ]] ||
        fail 'owned striped driver/index identity mismatch'
    lower="/dev/$disk"
    for (( attempt=0; attempt<50; ++attempt )); do
        [[ -b $lower ]] && break
        sleep 0.1
    done
    [[ -b $lower && "$(devno "$lower")" == "$dev" &&
       "$(blockdev --getsize64 "$lower")" == 67108864 ]] ||
        fail 'owned striped block node/size mismatch'
    [[ -d /sys/block/$disk/holders &&
       -z "$(ls -A "/sys/block/$disk/holders" 2>/dev/null)" &&
       -z "$(findmnt -rn -S "$lower" 2>/dev/null)" ]] ||
        fail 'owned striped lower already in use'
    active_swap_dev "$dev" && fail 'owned striped lower unexpectedly active as swap'
    DISKS[COUNT-1]="$disk"
    INDEXES[COUNT-1]="$index"
    DEVS[COUNT-1]="$dev"
    LOWERS[COUNT-1]="$lower"
    (( READY_COUNT += 1 ))
}

for (( index=0; index<2*STRIPES; ++index )); do
    create_owned_ram
done

mkdir -m 700 "$SESSION/plans"
cp -- "$SHARED_PLAN/fixture.bin" "$SESSION/fixture.bin"
for (( stripe=0; stripe<STRIPES; ++stripe )); do
    mkdir -m 700 "$SESSION/plans/$stripe"
    cp -- "$SHARED_PLAN/striped-$STRIPES/stripe-$stripe/trace.jsonl" \
        "$SESSION/plans/$stripe/trace.jsonl"
    cp -- "$SHARED_PLAN/striped-$STRIPES/stripe-$stripe/manifest.json" \
        "$SESSION/plans/$stripe/manifest.json"
done

modprobe dm_mod
modprobe lz4_compress || fail 'kernel LZ4 compressor unavailable'
insmod "$MODULE" async_prepare=1 delta64_rescue=1 ||
    fail 'swapz module insertion rejected'
OWN_MODULE=1
dmsetup targets | grep -Eq '^swapz[[:space:]]' ||
    fail 'swapz target registration missing'

# io-replay.py requires the swapz mapping to be exactly the stripe's logical
# working range and accepts only SWAPZ-TEST-<16 hex> trial UUIDs.
STRIPE_SECTORS="$(python3 -B - "$SESSION/plans" "$STRIPES" <<'PY'
import json, sys
from pathlib import Path
root, stripes = Path(sys.argv[1]), int(sys.argv[2])
pages = {json.loads((root / str(i) / "manifest.json").read_text())["logical_pages"]
         for i in range(stripes)}
if len(pages) != 1 or next(iter(pages)) <= 0:
    raise SystemExit("striped child plans disagree on logical pages")
print(next(iter(pages)) * 4096 // 512)
PY
)" || fail 'cannot derive striped logical range'
[[ $STRIPE_SECTORS =~ ^[1-9][0-9]*$ ]] && (( STRIPE_SECTORS <= 8192 )) ||
    fail 'striped logical range invalid or larger than the canonical 8192 sectors'
for (( stripe=0; stripe<STRIPES; ++stripe )); do
    token="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
    [[ $token =~ ^[a-f0-9]{16}$ ]] || fail 'random mapper identity invalid'
    name="swapz-stripe-$token-$stripe"
    uuid="SWAPZ-TEST-$token"
    lower_index=$(( STRIPES + stripe ))
    table="0 $STRIPE_SECTORS swapz ${LOWERS[lower_index]} 0 64 0 2 0 1 0 2"
    dmsetup create "$name" --uuid "$uuid" --table "$table" ||
        fail 'striped swapz mapper creation failed'
    OWN_DMS[stripe]=1
    DMNAMES[stripe]="$name"
    DMUUIDS[stripe]="$uuid"
    [[ "$(dmsetup info -c --noheadings -o uuid "$name" | tr -d '[:space:]')" == "$uuid" ]] ||
        fail 'striped mapper UUID mismatch'
    dmsetup deps -o devname "$name" | grep -Fq "${DISKS[lower_index]}" ||
        fail 'striped mapper lower dependency mismatch'
    status="$(dmsetup status "$name")"
    grep -Eq '(^|[[:space:]])write_pipeline_depth=1([[:space:]]|$)' <<<"$status" ||
        fail 'striped target is not production K=1'
    grep -Eq '(^|[[:space:]])async_prepare=1([[:space:]]|$)' <<<"$status" ||
        fail 'striped target async preparation mismatch'
    grep -Eq '(^|[[:space:]])delta64_rescue=1([[:space:]]|$)' <<<"$status" ||
        fail 'striped target delta64 production policy mismatch'
    for _ in {1..50}; do
        [[ -b /dev/mapper/$name ]] && break
        sleep 0.1
    done
    [[ -b /dev/mapper/$name ]] || fail 'striped mapper block node absent'
    DMDEVS[stripe]="$(devno "/dev/mapper/$name")"
    dm_sysfs="$(readlink -f "/sys/dev/block/${DMDEVS[stripe]}")"
    DMKNAMES[stripe]="${dm_sysfs##*/}"
    [[ ${DMKNAMES[stripe]} =~ ^dm-[0-9]+$ ]] ||
        fail 'striped mapper kernel identity ambiguous'
done

aggregate_sampler() {
    local start="$1" stop="$2" ready="$3" output="$4"
    shift 4
    python3 -B - "$start" "$stop" "$ready" "$output" "$@" <<'PY'
import json
from pathlib import Path
import sys
import time

start, stop, ready, output, *disks = sys.argv[1:]
paths = [Path("/sys/block") / disk / "inflight" for disk in disks]
for path in paths:
    if not path.is_file():
        raise SystemExit("missing exact owned inflight counter")
Path(ready).write_text("READY\n")
deadline = time.monotonic() + 60
while not Path(start).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("aggregate sampler start gate timed out")
    time.sleep(0.001)
samples = multiple = max_devices = max_depth = 0
while not Path(stop).exists():
    depths = []
    for path in paths:
        fields = path.read_text(encoding="ascii").split()
        if len(fields) != 2 or not all(field.isdigit() for field in fields):
            raise SystemExit("invalid exact owned inflight counter")
        depths.append(int(fields[1]))
    active = sum(depth > 0 for depth in depths)
    total = sum(depths)
    samples += 1
    multiple += int(active >= 2)
    max_devices = max(max_devices, active)
    max_depth = max(max_depth, total)
    time.sleep(0.0005)
Path(output).write_text(json.dumps({
    "target_interval_ns": 500000,
    "samples": samples,
    "samples_with_multiple_write_devices": multiple,
    "max_simultaneous_write_devices": max_devices,
    "max_aggregate_write_depth": max_depth,
}, sort_keys=True) + "\n")
PY
}

run_arm() {
    local candidate="$1" barrier="$SESSION/barrier-$1"
    local start="$barrier/start" stop="$barrier/stop"
    local sampler_ready="$barrier/sampler-ready" sampler_result="$barrier/sampler.json"
    local stripe lower_index device expected_dev expected_lower pid rc=0 ready_count=0
    local sampler_pid
    local -a arm_disks=() extra=()
    mkdir -m 700 "$barrier"
    CHILD_PIDS=()

    for (( stripe=0; stripe<STRIPES; ++stripe )); do
        if [[ $candidate == off ]]; then
            lower_index=$stripe
            device="${LOWERS[stripe]}"
            expected_dev="${DEVS[stripe]}"
            expected_lower="${DEVS[stripe]}"
            arm_disks+=("${DISKS[stripe]}")
            extra=()
        else
            lower_index=$(( STRIPES + stripe ))
            device="/dev/mapper/${DMNAMES[stripe]}"
            expected_dev="${DMDEVS[stripe]}"
            expected_lower="${DEVS[lower_index]}"
            arm_disks+=("${DISKS[lower_index]}")
            extra=(--expected-dm-uuid "${DMUUIDS[stripe]}")
        fi
        python3 -B tests/runtime/benchmark/io-replay.py run \
            --fixture "$SESSION/fixture.bin" \
            --trace "$SESSION/plans/$stripe/trace.jsonl" \
            --manifest "$SESSION/plans/$stripe/manifest.json" \
            --candidate "$candidate" --source-sha "$VALIDATED_SOURCE" \
            --device "$device" --result "$SESSION/$candidate-$stripe.json" \
            --native-replay --owned-nullblk-name "${NAMES[lower_index]}" \
            --expected-dev "$expected_dev" --expected-lower-dev "$expected_lower" \
            --stripe-ready-file "$barrier/ready-$stripe" \
            --stripe-start-file "$start" "${extra[@]}" \
            >"$SESSION/$candidate-$stripe.stdout" \
            2>"$SESSION/$candidate-$stripe.stderr" &
        CHILD_PIDS+=("$!")
    done

    for _ in {1..6000}; do
        ready_count=0
        for (( stripe=0; stripe<STRIPES; ++stripe )); do
            [[ -f $barrier/ready-$stripe ]] && (( ready_count += 1 ))
        done
        (( ready_count == STRIPES )) && break
        for pid in "${CHILD_PIDS[@]}"; do
            if ! kill -0 "$pid" 2>/dev/null; then
                wait "$pid" || true
                fail "$candidate striped replay exited before synchronized start"
            fi
        done
        sleep 0.01
    done
    (( ready_count == STRIPES )) || fail "$candidate striped replay readiness timed out"

    aggregate_sampler "$start" "$stop" "$sampler_ready" "$sampler_result" \
        "${arm_disks[@]}" &
    sampler_pid=$!
    for _ in {1..1000}; do
        [[ -f $sampler_ready ]] && break
        kill -0 "$sampler_pid" 2>/dev/null ||
            fail "$candidate aggregate lower sampler failed before start"
        sleep 0.01
    done
    [[ -f $sampler_ready ]] || fail "$candidate aggregate lower sampler readiness timed out"
    : > "$start"

    for pid in "${CHILD_PIDS[@]}"; do
        wait "$pid" || rc=1
    done
    CHILD_PIDS=()
    : > "$stop"
    wait "$sampler_pid" || rc=1
    (( rc == 0 )) || fail "$candidate striped replay or sampler failed"

    python3 -B - "$candidate" "$MODEL" "$STRIPES" "$VALIDATED_SOURCE" \
        "$sampler_result" "$SESSION" <<'PY'
import json
import math
from pathlib import Path
import sys

candidate, model, stripes_text, source, sampler_path, session_path = sys.argv[1:]
stripes = int(stripes_text)
session = Path(session_path)
reports = [json.loads((session / f"{candidate}-{index}.json").read_text())
           for index in range(stripes)]
manifests = [json.loads((session / "plans" / str(index) / "manifest.json").read_text())
             for index in range(stripes)]
sampler = json.loads(Path(sampler_path).read_text())
parent_hashes = {manifest.get("parent_trace_sha256") for manifest in manifests}
fixtures = {report.get("fixture_sha256") for report in reports}
starts = [report.get("measured_start_monotonic_ns") for report in reports]
ends = [report.get("measured_end_monotonic_ns") for report in reports]
if (len(parent_hashes) != 1 or len(fixtures) != 1 or
        any(report.get("candidate") != candidate or report.get("verdict") != "PASS" or
            report.get("source_sha") != source or report.get("replay_engine") != "native-c" or
            report.get("replay_mode") != "persistent-mixed" or
            report.get("verified_post_sha256") != report.get("expected_post_sha256")
            for report in reports) or
        any(manifest.get("stripe_count") != stripes or
            manifest.get("stripe_index") != index or
            not manifest.get("stripe_partitionable")
            for index, manifest in enumerate(manifests)) or
        any(type(value) is not int or value <= 0 for value in starts + ends)):
    raise SystemExit("invalid striped report provenance/oracle")
seconds = (max(ends) - min(starts)) / 1e9
if not math.isfinite(seconds) or seconds <= 0:
    raise SystemExit("invalid common striped measurement interval")
logical_write_bytes = sum(report["throughput_mbps"]["logical_write_bytes"]
                          for report in reports)
logical_read_bytes = sum(report["throughput_mbps"]["logical_read_bytes"]
                         for report in reports)
lower_fields = ("lower_read_requests", "lower_read_bytes",
                "lower_write_requests", "lower_write_bytes",
                "lower_flush_requests")
lower = {field: sum(report["lower_io"][field] for report in reports)
         for field in lower_fields}
host_records = [report.get("host_cpu") or {} for report in reports]
host_cpu = {
    "status": ("AVAILABLE" if all(record.get("status") == "AVAILABLE"
                                  for record in host_records) else "PARTIAL")
}
for field in ("busy_fraction", "steal_fraction", "pressure_some_fraction"):
    values = [record.get(field) for record in host_records
              if isinstance(record.get(field), (int, float))]
    host_cpu[field] = max(values) if values else None
def max_latency(field):
    values = [report.get(field) for report in reports
              if isinstance(report.get(field), (int, float))]
    return max(values) if values else None
kernel = None
if candidate == "swapz":
    kernel = {
        "write_pipeline_depth": [
            (report.get("kernel_write_path") or {}).get("write_pipeline_depth")
            for report in reports],
        "pipeline_active_max": [
            (report.get("kernel_write_path") or {}).get("pipeline_active_max")
            for report in reports],
        "lower_write_service_ewma_ns": [
            (report.get("kernel_write_path") or {}).get("lower_write_service_ewma_ns")
            for report in reports],
    }
    if (any(value != 1 for value in kernel["write_pipeline_depth"]) or
            any(type(value) is not int or not 0 <= value <= 1
                for value in kernel["pipeline_active_max"])):
        raise SystemExit("striped swapz arm did not remain independent production K=1")
arm = {
    "candidate": candidate,
    "model": model,
    "stripes": stripes,
    "source_sha": source,
    "fixture_sha256": next(iter(fixtures)),
    "parent_trace_sha256": next(iter(parent_hashes)),
    "measure_ops": sum(report["measure_ops"] for report in reports),
    "seconds": seconds,
    "throughput_mbps": {
        "logical_write_bytes": logical_write_bytes,
        "logical_read_bytes": logical_read_bytes,
        "logical_write_mbps": logical_write_bytes / seconds / 1_000_000,
        "logical_read_mbps": logical_read_bytes / seconds / 1_000_000,
    },
    "lower_io": lower,
    "read_p99_ns": max_latency("read_p99_ns"),
    "write_p99_ns": max_latency("write_p99_ns"),
    "host_cpu": host_cpu,
    "lower_inflight": {
        "per_stripe_write_peak": [
            report["lower_inflight"]["write_peak"] for report in reports],
        "per_stripe_write_time_weighted": [
            report["lower_inflight"]["write_time_weighted"] for report in reports],
        **sampler,
    },
    "kernel_write_path": kernel,
}
(session / f"{candidate}-aggregate.json").write_text(
    json.dumps(arm, sort_keys=True) + "\n")
PY
}

if (( SWAPZ_FIRST )); then
    run_arm swapz
    run_arm off
    ORDER=swapz-first
else
    run_arm off
    run_arm swapz
    ORDER=off-first
fi

python3 -B - "$MODEL" "$STRIPES" "$ORDER" "$LOWER_MBPS" "$SUBMIT_QUEUES" \
    "$HW_QUEUE_DEPTH" "$COMPLETION_NSEC" "$VALIDATED_SOURCE" "$SESSION" <<'PY'
import json
from pathlib import Path
import sys

(model, stripes_text, order, lower_mbps, submit_queues, hw_depth,
 completion_nsec, source, session_path) = sys.argv[1:]
stripes = int(stripes_text)
session = Path(session_path)
off = json.loads((session / "off-aggregate.json").read_text())
swapz = json.loads((session / "swapz-aggregate.json").read_text())
if (off["source_sha"] != swapz["source_sha"] or off["source_sha"] != source or
        off["fixture_sha256"] != swapz["fixture_sha256"] or
        off["parent_trace_sha256"] != swapz["parent_trace_sha256"] or
        off["measure_ops"] != swapz["measure_ops"] or
        off["stripes"] != stripes or swapz["stripes"] != stripes):
    raise SystemExit("striped raw/swapz pair provenance mismatch")
result = {
    "experiment": "multi-target-stripes",
    "scope": "DEVELOPMENT_ONLY_INDEPENDENT_K1_TARGETS",
    "model": model,
    "stripes": stripes,
    "order": order,
    "source_sha": source,
    "fixture_sha256": off["fixture_sha256"],
    "parent_trace_sha256": off["parent_trace_sha256"],
    "aggregate_model": {
        "cap_mib_s": int(lower_mbps) * stripes,
        "submit_queues_x_hw_depth": int(submit_queues) * int(hw_depth) * stripes,
        "completion_nsec": int(completion_nsec),
        "offered_qd": 32,
    },
    "per_device_model": {
        "cap_mib_s": int(lower_mbps),
        "submit_queues": int(submit_queues),
        "hw_queue_depth": int(hw_depth),
        "completion_nsec": int(completion_nsec),
    },
    "arms": {"off": off, "swapz": swapz},
    "lower_write_bytes_saved_fraction":
        1 - swapz["lower_io"]["lower_write_bytes"] / off["lower_io"]["lower_write_bytes"],
    "lower_write_requests_saved_fraction":
        1 - swapz["lower_io"]["lower_write_requests"] / off["lower_io"]["lower_write_requests"],
}
print(json.dumps(result, sort_keys=True))
PY
