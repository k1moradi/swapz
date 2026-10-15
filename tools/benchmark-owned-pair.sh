#!/usr/bin/env bash
# Opt-in OFF/V3 comparison on two freshly owned RAM-backed null_blk devices.
# Never touches system swap, physical devices, or unrelated DM resources.
set -Eeuo pipefail
umask 077
if [[ $# == 1 && $1 == --help ]]; then
    echo 'Usage: sudo bash tools/benchmark-owned-pair.sh --run-owned-ram-pair [--profile medium] [--retain-ms 2] [--unpaced] | --run-owned-ram-pair --profile medium --retain-ms 1 --unpaced [--lower-mbps 20] [--async-prepare]'
    exit 0
fi
PROFILE=default
RETAIN_MS=0
RATE_MODE=paced
QD=8
WARMUP_OPS=256
MEASURE_OPS=1024
IOPS=500
ASYNC_PREPARE=0
LOWER_MBPS=0
# Explicitly permit asynchronous preparation on the QD32 medium experiment.
# Nothing about an arbitrary extra flag may authorize RAM device creation.
if [[ $# -gt 1 && ${!#} == --async-prepare ]]; then
    ASYNC_PREPARE=1
    set -- "${@:1:$(( $# - 1 ))}"
fi
# Only an exact 20 MiB/s cap on both owned null_blk devices is allowed.
if [[ $# -ge 3 && ${@: -2:1} == --lower-mbps && ${!#} == 20 ]]; then
    LOWER_MBPS=20
    set -- "${@:1:$(( $# - 2 ))}"
fi
if [[ $# == 1 && $1 == --run-owned-ram-pair ]]; then
    :
elif [[ $# == 3 && $1 == --run-owned-ram-pair &&
        $2 == --profile && $3 == medium ]]; then
    PROFILE=medium
elif [[ $# == 5 && $1 == --run-owned-ram-pair &&
        $2 == --profile && $3 == medium &&
        $4 == --retain-ms && $5 == 2 ]]; then
    PROFILE=medium
    RETAIN_MS=2
elif [[ $# == 6 && $1 == --run-owned-ram-pair &&
        $2 == --profile && $3 == medium &&
        $4 == --retain-ms && ( $5 == 1 || $5 == 2 ) &&
        $6 == --unpaced ]]; then
    # Same alpha.20 source, same immutable unpaced QD32 replay:
    # isolate 1ms vs 2ms window retention without a new kernel policy.
    # Only two exact retention values are admitted before provisioning.
    PROFILE=medium
    RETAIN_MS="$5"
    RATE_MODE=unpaced
    QD=32
    WARMUP_OPS=1024
    MEASURE_OPS=16384
    IOPS=0
else
    echo 'BLOCKED: explicit owned-RAM opt-in and supported profile required' >&2
    exit 2
fi
if (( ASYNC_PREPARE || LOWER_MBPS )) &&
   [[ $RATE_MODE != unpaced || $PROFILE != medium ]]; then
    echo 'BLOCKED: async/rate-cap trials require owned medium unpaced QD32' >&2
    exit 2
fi
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/tools/nullblk-identity.sh"
source "$ROOT/tools/swap-inventory.sh"
cd "$ROOT"
MODULE="$ROOT/build/kernel/experimental/dm-swapz.ko"
CFGBASE=/sys/kernel/config/nullb
declare -a NAMES=() CONFIGS=() DISKS=() INDEXES=() DEVS=() LOWERS=()
COUNT=0
READY_COUNT=0
OWN_MODULE=0
OWN_DM=0
QUARANTINE=0
DMNAME=""
DMUUID=""
note() { printf '%s\n' "$*"; }
fail() { note "BLOCKED: $*" >&2; exit 1; }
devno() {
    local encoded major minor
    encoded="$(stat -Lc '%t:%T' "$1")" || return 1
    IFS=: read -r major minor <<< "$encoded"
    printf '%d:%d\n' "0x$major" "0x$minor"
}
for program in git insmod rmmod modprobe dmsetup modinfo blockdev readlink \
               findmnt mountpoint mount timeout sha256sum cmp od awk grep tr \
               mkdir rmdir stat tee cat ls sleep python3 sort; do
    command -v "$program" >/dev/null || fail "missing command $program"
done
[[ $(id -u) == 0 ]] || fail "root required for isolated RAM devices"
[[ $(git branch --show-current) == main ]] || fail "main only"
git diff --quiet && git diff --cached --quiet || fail "dirty tracked sources"
[[ $(cat kernel/extent-v3/VERSION) == 3.0.0-alpha.21 ]] ||
    fail "unexpected V3 revision"
[[ -s $MODULE && $(modinfo -F vermagic "$MODULE" | awk '{print $1}') == "$(uname -r)" ]] ||
    fail "V3 module missing or running-kernel vermagic mismatch"
for file in Makefile dm-target.c codec.c authority.c engine.c codec.h \
            authority.h engine.h flush-qual.h gc-cost.h; do
    cmp -s "kernel/extent-v3/$file" "build/kernel/experimental/$file" ||
        fail "staged kernel source mismatch: $file"
done
[[ ! -d /sys/module/dm_swapz && -r /proc/swaps ]] ||
    fail "another dm_swapz loaded or swap inventory unavailable"
mkdir -p "$ROOT/build/benchmark"
SESSION="$(mktemp -d "$ROOT/build/benchmark/session.XXXXXXXX")"
exec > >(tee -a "$SESSION/session.log") 2>&1
SWAPS="$(cat /proc/swaps)"
SWAPS_ID="$(printf '%s
' "$SWAPS" |
    swapz_swap_inventory_identity /dev/stdin)" ||
    fail "cannot parse initial host swap identity"
SOURCE="$(git rev-parse HEAD)"
note "SOURCE_HEAD=$SOURCE MODULE_SHA256=$(sha256sum "$MODULE")"
note "BENCH_PROFILE=$PROFILE RETAIN_MS=$RETAIN_MS ASYNC_PREPARE=$ASYNC_PREPARE LOWER_MBPS=$LOWER_MBPS RATE_MODE=$RATE_MODE QD=$QD WARMUP_OPS=$WARMUP_OPS MEASURE_OPS=$MEASURE_OPS OFFERED_IOPS=$IOPS"
note "RUNNING_KERNEL=$(uname -r)"
note "HOST_SWAPS_BEFORE:"
note "$SWAPS"
note "EVIDENCE_DIR=$SESSION"

# Never force removal: first close the exact DM UUID, then prove every RAM
# config/index/rdev/holder is still ours. Partial setup is quarantined.
cleanup() {
    local result=$? i valid=1 end_swaps current_id
    trap - EXIT HUP INT TERM
    set +e
    # Genuine inventory changes forbid teardown. Ignore ONLY volatile
    # swap Used; path/type/size/priority must remain exactly the same.
    if ! current_id="$(swapz_swap_inventory_identity /proc/swaps)" ||
       [[ "$current_id" != "$SWAPS_ID" ]]; then
        QUARANTINE=1
        note 'QUARANTINED: host swap changed during owned pair'
    fi
    if (( OWN_DM && !QUARANTINE )); then
        if [[ $(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
                  tr -d '[:space:]') == "$DMUUID" ]] &&
            dmsetup remove "$DMNAME"; then
            OWN_DM=0
        else
            QUARANTINE=1
            note 'QUARANTINED: DM UUID changed or mapping busy'
        fi
    fi
    if (( COUNT != READY_COUNT )); then
        QUARANTINE=1
        note 'QUARANTINED: partially initialized RAM identity'
    elif (( COUNT == 2 && !OWN_DM && !QUARANTINE )); then
        for (( i=0; i<2; ++i )); do
            if [[ ! ${NAMES[i]} =~ ^nullb-swapz-[a-f0-9]{16}$ ||
                  ${CONFIGS[i]} != "$CFGBASE/${NAMES[i]}" ||
                  $(cat "${CONFIGS[i]}/index" 2>/dev/null) != "${INDEXES[i]}" ||
                  $(cat "${CONFIGS[i]}/power" 2>/dev/null) != 1 ||
                  $(cat "${CONFIGS[i]}/memory_backed" 2>/dev/null) != 1 ||
                  $(cat "/sys/block/${DISKS[i]}/dev" 2>/dev/null) != "${DEVS[i]}" ||
                  $(readlink -f "/sys/dev/block/${DEVS[i]}") != "$(readlink -f "/sys/block/${DISKS[i]}")" ||
                  $(devno "${LOWERS[i]}" 2>/dev/null) != "${DEVS[i]}" ||
                  ! -d /sys/block/${DISKS[i]}/holders ||
                  -n $(ls -A "/sys/block/${DISKS[i]}/holders" 2>/dev/null) ||
                  -n $(findmnt -rn -S "${LOWERS[i]}" 2>/dev/null) ]]; then
                valid=0
            fi
        done
        if (( valid )); then
            for (( i=1; i>=0; --i )); do
                if ! { echo 0 > "${CONFIGS[i]}/power" &&
                       rmdir "${CONFIGS[i]}"; }; then
                    QUARANTINE=1
                    note 'QUARANTINED: cannot remove owned RAM backing'
                    break
                fi
            done
        else
            QUARANTINE=1
            note 'QUARANTINED: backing identity/holders changed'
        fi
    fi
    if (( OWN_MODULE && !OWN_DM && !QUARANTINE )); then
        rmmod dm_swapz || { QUARANTINE=1; note 'QUARANTINED: V3 module busy'; }
    fi
    end_swaps="$(cat /proc/swaps)"
    note "HOST_SWAPS_AFTER:"
    note "$end_swaps"
    if ! current_id="$(printf '%s
' "$end_swaps" |
            swapz_swap_inventory_identity /dev/stdin)" ||
       [[ "$current_id" != "$SWAPS_ID" ]]; then
        result=1
        QUARANTINE=1
        note 'FAIL: system swap identity changed'
    fi
    if (( QUARANTINE )); then
        result=1
        note 'BLOCKED: retain all remaining resources for read-only investigation'
    elif (( result == 0 )); then
        note 'PASS: isolated pair and ordinary teardown'
    fi
    note "EVIDENCE=$SESSION/session.log"
    exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! mountpoint -q /sys/kernel/config; then
    modprobe configfs
    mount -t configfs configfs /sys/kernel/config ||
        fail 'cannot mount configfs'
fi
if [[ ! -d $CFGBASE ]]; then
    modprobe null_blk nr_devices=0 || fail 'null_blk configfs missing'
fi
[[ -d $CFGBASE ]] || fail 'null_blk configfs missing'
NULL_MAJOR="$(awk '/^Block devices:/{ok=1;next} ok && $2=="nullb"{print $1;exit}' /proc/devices)"
[[ $NULL_MAJOR =~ ^[0-9]+$ ]] || fail 'null_blk major absent'

create_owned_ram() {
    local token name config index disk="" dev lower n path rest
    token="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
    [[ $token =~ ^[a-f0-9]{16}$ ]] || fail 'random identity invalid'
    name="nullb-swapz-$token"
    config="$CFGBASE/$name"
    [[ ! -e $config && ! -e /dev/$name ]] || fail 'RAM identity collision'
    mkdir "$config" || fail 'cannot create RAM config'
    NAMES[COUNT]="$name"
    CONFIGS[COUNT]="$config"
    (( COUNT += 1 ))
    for attr in size blocksize memory_backed power index; do
        [[ -e "$config/$attr" ]] || fail 'missing RAM config attribute'
    done
    echo 64 > "$config/size"
    echo 4096 > "$config/blocksize"
    echo 1 > "$config/memory_backed"
    if (( LOWER_MBPS )); then
        [[ -e "$config/mbps" ]] ||
            fail 'owned null_blk does not expose a per-device mbps limit'
        echo "$LOWER_MBPS" > "$config/mbps" ||
            fail 'owned null_blk rejected bandwidth limit'
        [[ $(cat "$config/mbps") == "$LOWER_MBPS" ]] ||
            fail 'owned null_blk bandwidth limit did not match'
    fi
    echo 1 > "$config/power"
    [[ $(cat "$config/memory_backed") == 1 && $(cat "$config/power") == 1 ]] ||
        fail 'RAM backing is not active'
    if (( LOWER_MBPS )); then
        [[ $(cat "$config/mbps") == "$LOWER_MBPS" ]] ||
            fail 'owned null_blk powered bandwidth cap mismatch'
    fi
    index="$(cat "$config/index")"
    [[ $index =~ ^(0|[1-9][0-9]*)$ ]] || fail 'configfs index invalid'
    for (( n=0; n<50; ++n )); do
        disk="$(swapz_resolve_owned_disk "$name" "$index" /sys/block)" && break
        sleep 0.1
    done
    [[ -n $disk ]] || fail 'owned disk absent or ambiguous'
    dev="$(cat "/sys/block/$disk/dev")"
    [[ $dev == "$NULL_MAJOR:$index" &&
       $(readlink -f "/sys/dev/block/$dev") == "$(readlink -f "/sys/block/$disk")" ]] ||
        fail 'RAM registered driver/index identity mismatch'
    lower="/dev/$disk"
    for (( n=0; n<50; ++n )); do
        [[ -b $lower ]] && break
        sleep 0.1
    done
    [[ -b $lower && $(devno "$lower") == "$dev" &&
       $(blockdev --getsize64 "$lower") == 67108864 ]] ||
        fail 'RAM block node or size unexpected'
    [[ -d /sys/block/$disk/holders &&
       -z $(ls -A "/sys/block/$disk/holders") &&
       -z $(findmnt -rn -S "$lower") ]] || fail 'owned RAM lower in use'
    while read -r path rest; do
        [[ $path == Filename || ! -e $path ]] && continue
        [[ $(devno "$path") != "$dev" ]] || fail 'owned lower is active swap'
    done < /proc/swaps
    DISKS[COUNT-1]="$disk"
    INDEXES[COUNT-1]="$index"
    DEVS[COUNT-1]="$dev"
    LOWERS[COUNT-1]="$lower"
    (( READY_COUNT += 1 ))
    note "OWNED_RAM[$((COUNT-1))]=$lower DEVICE=$dev"
}
create_owned_ram  # bare uncompressed
create_owned_ram  # V3 backing, separate device
[[ ${DEVS[0]} != "${DEVS[1]}" ]] || fail 'pair backed by same RAM device'
modprobe dm_mod
insmod "$MODULE" "async_prepare=$ASYNC_PREPARE" ||
    fail 'V3 module insertion rejected'
OWN_MODULE=1
dmsetup targets | grep -Eq '^swapz3[[:space:]]' ||
    fail 'V3 target registration missing'
token="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
[[ $token =~ ^[a-f0-9]{16}$ ]] || fail 'mapper token invalid'
DMNAME="swapz-demo-$token"
DMUUID="SWAPZ-TEST-$token"
[[ ! -e /dev/mapper/$DMNAME ]] || fail 'DM name collision'
# 4MiB upper (1024 pages), verify=0, gc_policy=2, lower_bulk=1,
# coalesce=0 and both diagnostic fault knobs disabled.
# The explicit ninth policy field is 0 for default/control trials.
# Retained unpaced sessions permit --retain-ms 1 OR 2; only the original
# paced candidate permits 2. Both are pinned above before any setup.
if ! dmsetup create "$DMNAME" --uuid "$DMUUID" \
    --table "0 8192 swapz3 ${LOWERS[1]} 0 64 0 2 0 0 1 0 $RETAIN_MS"; then
    if [[ $(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
             tr -d '[:space:]') == "$DMUUID" ]]; then
        OWN_DM=1
    else
        QUARANTINE=1
    fi
    fail 'V3 DM creation failed'
fi
OWN_DM=1
[[ $(dmsetup info -c --noheadings -o uuid "$DMNAME" |
      tr -d '[:space:]') == "$DMUUID" ]] || fail 'owned DM UUID mismatch'
dmsetup status "$DMNAME" | grep -Eq "(^|[[:space:]])retain_ms=$RETAIN_MS([[:space:]]|$)" ||
    fail 'unexpected V3 retained policy after owned DM creation'
dmsetup deps -o devname "$DMNAME" | grep -Fq "${DISKS[1]}" ||
    fail 'owned DM backing dependency mismatch'
for (( n=0; n<50; ++n )); do
    [[ -b /dev/mapper/$DMNAME ]] && break
    sleep 0.1
done
[[ -b /dev/mapper/$DMNAME ]] || fail 'owned DM block node missing'
DMDEV="$(devno "/dev/mapper/$DMNAME")"
if [[ $PROFILE == medium ]]; then
    python3 -B tests/runtime/benchmark/anon-page-fixture.py \
        --output-prefix "$SESSION/fixture" --pages 128 \
        --seed 0x51a0a9 --weights medium=100
    # Reject the fixture before any replay unless actual host liblz4
    # outputs meet the predeclared medium nonzero-page size range.
    python3 -B - "$SESSION/fixture.json" <<'PY'
import json
import sys
from pathlib import Path
manifest = json.loads(Path(sys.argv[1]).read_text())
assert manifest["pages"] == 128
assert manifest["profile_pages"] == {"medium": 128}
assert manifest["lz4_size_buckets"] == {"2049_3072": 128}
assert manifest["raw_pages"] == 0
assert 2049 <= manifest["lz4_min_accepted_payload_bytes"] <= manifest["lz4_max_accepted_payload_bytes"] <= 2200
assert 128 * 2049 <= manifest["lz4_accepted_payload_bytes"] <= 128 * 2200
print("MEDIUM_FIXTURE_MEASURED_LZ4_BYTES=" +
      str(manifest["lz4_accepted_payload_bytes"]))
PY
else
    python3 -B tests/runtime/benchmark/anon-page-fixture.py \
        --output-prefix "$SESSION/fixture" --pages 128 --seed 0x51a0a9
fi
python3 -B tests/runtime/benchmark/io-replay.py prepare \
    --fixture "$SESSION/fixture.bin" --output-dir "$SESSION/plan" \
    --logical-pages 1024 --writer-pages 256 --reader-start 512 \
    --reader-pages 256 --qd "$QD" --read-pct 25 \
    --warmup-ops "$WARMUP_OPS" --measure-ops "$MEASURE_OPS" --iops "$IOPS"
note "V3_STATUS_BEFORE=$(dmsetup status "$DMNAME")"
timeout --signal=TERM --kill-after=5s 120s python3 -B \
    tests/runtime/benchmark/io-replay.py run \
    --fixture "$SESSION/fixture.bin" \
    --trace "$SESSION/plan/trace.jsonl" \
    --manifest "$SESSION/plan/manifest.json" \
    --candidate off --source-sha "$SOURCE" \
    --device "${LOWERS[0]}" --result "$SESSION/off.json" \
    --owned-nullblk-name "${NAMES[0]}" \
    --expected-dev "${DEVS[0]}" --expected-lower-dev "${DEVS[0]}" ||
    fail 'uncompressed replay rejected'
timeout --signal=TERM --kill-after=5s 120s python3 -B \
    tests/runtime/benchmark/io-replay.py run \
    --fixture "$SESSION/fixture.bin" \
    --trace "$SESSION/plan/trace.jsonl" \
    --manifest "$SESSION/plan/manifest.json" \
    --candidate v3 --source-sha "$SOURCE" \
    --device "/dev/mapper/$DMNAME" --result "$SESSION/v3.json" \
    --owned-nullblk-name "${NAMES[1]}" \
    --expected-dev "$DMDEV" --expected-lower-dev "${DEVS[1]}" \
    --expected-dm-uuid "$DMUUID" || fail 'V3 replay rejected'
note "V3_STATUS_AFTER=$(dmsetup status "$DMNAME")"
python3 -B tests/runtime/benchmark/io-replay.py compare \
    --reports "$SESSION/off.json" "$SESSION/v3.json" |
    tee "$SESSION/pair.json" || fail 'pair verification rejected'
note 'PASS: bounded same-work pilot, not sustained GC/CPU/p99 qualification'
