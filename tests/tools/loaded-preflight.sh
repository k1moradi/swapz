#!/usr/bin/env bash
# Private root preflight for make test loaded qualification.
# It may remove only an idle module or one provably stale harness-owned mapping.
set -Eeuo pipefail

fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
is_uint() {
    local value="$1"
    case "$value" in
        0) return 0 ;;
        ""|0*|*[!0-9]*) return 1 ;;
        *) return 0 ;;
    esac
}
is_hex16() {
    local value="$1"
    [[ ${#value} == 16 ]] || return 1
    case "$value" in
        *[!0-9a-f]*) return 1 ;;
    esac
    return 0
}
preflight_internal_error() {
    local rc="$1" line="$2"
    trap - ERR
    if is_uint "$rc" && is_uint "$line" && [[ $rc != 0 && $line != 0 ]]; then
        printf 'FAIL: loaded preflight internal command failed status=%s line=%s\n' \
            "$rc" "$line" >&2
    else
        printf '%s\n' 'FAIL: loaded preflight internal command failed' >&2
    fi
    exit "$rc"
}
trap 'rc=$?; preflight_internal_error "$rc" "$LINENO"' ERR

for cmd in rmmod dmsetup timeout awk tr findmnt cat readlink stat sleep id ls; do
    command -v "$cmd" >/dev/null || fail "missing required tool $cmd"
done
[[ $(id -u) == 0 ]] || fail "root required for loaded preflight"

clean_orphaned_nullb() {
    local cfgbase=/sys/kernel/config/nullb
    [[ -d $cfgbase ]] || return 0
    local cfg name orphan_token idx dev_disk dev_path holders
    shopt -s nullglob
    for cfg in "$cfgbase"/nullb-swapz-*; do
        [[ -d $cfg ]] || continue
        name="${cfg##*/}"
        case "$name" in
            nullb-swapz-*) orphan_token="${name#nullb-swapz-}" ;;
            *) continue ;;
        esac
        is_hex16 "$orphan_token" || continue
        [[ -r $cfg/memory_backed && "$(cat "$cfg/memory_backed" 2>/dev/null)" == 1 ]] || continue
        idx="$(cat "$cfg/index" 2>/dev/null || true)"
        if is_uint "$idx"; then
            dev_disk="nullb$idx"
            dev_path="/dev/$dev_disk"
            if [[ -d "/sys/block/$dev_disk/holders" ]]; then
                holders="$(ls -A "/sys/block/$dev_disk/holders" 2>/dev/null || true)"
                [[ -z "$holders" ]] || continue
            fi
            [[ -z "$(findmnt -rn -S "$dev_path" 2>/dev/null || true)" ]] || continue
            if awk -v path="$dev_path" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps 2>/dev/null; then
                continue
            fi
        fi
        echo 0 > "$cfg/power" 2>/dev/null || true
        rmdir "$cfg" 2>/dev/null || true
        note "AUTO_REMOVED_ORPHANED_NULLB=$name"
    done
    shopt -u nullglob
}

if [[ ! -d /sys/module/dm_swapz ]]; then
    clean_orphaned_nullb
    note "LOADED_PREFLIGHT_DM_SWAPZ=absent"
    exit 0
fi

read_refcount() {
    local value
    [[ -r /sys/module/dm_swapz/refcnt ]] ||
        fail "pre-existing dm_swapz reference count is unreadable"
    value="$(cat /sys/module/dm_swapz/refcnt)" ||
        fail "cannot read pre-existing dm_swapz reference count"
    is_uint "$value" ||
        fail "pre-existing dm_swapz reference count is malformed"
    printf '%s\n' "$value"
}

remove_idle_module() {
    rmmod dm_swapz ||
        fail "idle pre-existing dm_swapz could not be removed normally"
    [[ ! -d /sys/module/dm_swapz ]] ||
        fail "dm_swapz still present after ordinary removal"
}

refcount="$(read_refcount)"
if [[ $refcount == 0 ]]; then
    remove_idle_module
    clean_orphaned_nullb
    note "AUTO_REMOVED_IDLE_DM_SWAPZ=1"
    exit 0
fi

# A prior bounded qualification may have been killed while its one owned mapper
# was still alive. Recover only the exact private harness identity. Never
# remove multiple mappings, arbitrary swapz mappings, physical lowers, mounts,
# swap aliases, open mappings, or anything requiring force.
swapz_map_list="$(
    dmsetup ls --target swapz --noheadings 2>/dev/null |
        awk 'NF { print $1 }'
)" || fail "cannot enumerate pre-existing swapz mappings"
swapz_maps=()
if [[ -n $swapz_map_list ]]; then
    mapfile -t swapz_maps <<< "$swapz_map_list" ||
        fail "cannot parse pre-existing swapz mapping list"
fi
[[ ${#swapz_maps[@]} == 1 ]] ||
    fail "pre-existing dm_swapz module is busy with non-unique mappings; no cleanup attempted"
owned_map="${swapz_maps[0]}"
case "$owned_map" in
    swapz-demo-*) token="${owned_map#swapz-demo-}" ;;
    *) fail "pre-existing dm_swapz mapping is not harness-owned; no cleanup attempted" ;;
esac
is_hex16 "$token" ||
    fail "pre-existing dm_swapz mapping is not harness-owned; no cleanup attempted"
uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
    tr -d '[:space:]')" ||
    fail "cannot read pre-existing dm_swapz mapping UUID"
case "$uuid" in
    "SWAPZ-TEST-$token"|"SWAPZ-TEST-$token-gc"| \
    "SWAPZ-TEST-$token-discardtrim"|"SWAPZ-TEST-$token-suspend"| \
    "SWAPZ-TEST-$token-writefault"|"SWAPZ-TEST-$token-flushfault"| \
    "SWAPZ-TEST-$token-packed") ;;
    *) fail "pre-existing dm_swapz mapping UUID is not harness-owned; no cleanup attempted" ;;
esac
mapper="/dev/mapper/$owned_map"
[[ -z "$(findmnt -rn -S "$mapper" 2>/dev/null)" ]] ||
    fail "pre-existing harness dm_swapz mapping is mounted; no cleanup attempted"
if awk -v path="$mapper" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps; then
    fail "pre-existing harness dm_swapz mapping is active swap; no cleanup attempted"
fi

read_opens() {
    local val
    val="$(dmsetup info -c --noheadings -o open "$owned_map" 2>/dev/null |
        tr -d '[:space:]')" || return 1
    is_uint "$val" || return 1
    printf '%s\n' "$val"
}

deps="$(dmsetup deps -o devname "$owned_map" 2>/dev/null)" ||
    fail "cannot read pre-existing dm_swapz dependency"
lower_name="$(printf '%s\n' "$deps" | awk '
    /^[[:space:]]*1[[:space:]]+dependencies[[:space:]]*:/ {
        value = $0
        sub(/^[^(]*\(/, "", value)
        sub(/\)[[:space:]]*$/, "", value)
        if (value != "" && value !~ /[()[:space:]]/) {
            print value
            found = 1
        }
    }
    END { exit found ? 0 : 1 }
')" || fail "pre-existing harness dm_swapz mapping does not have one lower dependency"

cfgbase=/sys/kernel/config/nullb
[[ -d $cfgbase ]] ||
    fail "pre-existing harness null_blk configfs is unavailable"
owned_config=""
lower_index=""
case "$lower_name" in
    nullb-swapz-*)
        lower_token="${lower_name#nullb-swapz-}"
        is_hex16 "$lower_token" ||
            fail "pre-existing harness dm_swapz lower is not null_blk"
        [[ -d $cfgbase/$lower_name ]] &&
            owned_config="$cfgbase/$lower_name"
        ;;
    nullb*)
        lower_index="${lower_name#nullb}"
        is_uint "$lower_index" ||
            fail "pre-existing harness dm_swapz lower is not null_blk"
        matches=()
        shopt -s nullglob
        for config in "$cfgbase"/nullb-swapz-*; do
            [[ -d $config && -r $config/index ]] || continue
            [[ "$(cat "$config/index" 2>/dev/null)" == "$lower_index" ]] &&
                matches+=("$config")
        done
        shopt -u nullglob
        if [[ ${#matches[@]} == 1 ]]; then
            owned_config="${matches[0]}"
        fi
        ;;
    *)
        fail "pre-existing harness dm_swapz lower is not null_blk"
        ;;
esac
[[ -n $owned_config &&
   -r $owned_config/memory_backed &&
   -r $owned_config/power &&
   "$(cat "$owned_config/memory_backed" 2>/dev/null)" == 1 &&
   "$(cat "$owned_config/power" 2>/dev/null)" == 1 ]] ||
    fail "pre-existing dm_swapz lower is not a proven owned memory-backed null_blk"

lower="/dev/$lower_name"
[[ -z "$(findmnt -rn -S "$lower" 2>/dev/null)" ]] ||
    fail "pre-existing harness null_blk lower is mounted; no cleanup attempted"
if awk -v path="$lower" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps; then
    fail "pre-existing harness null_blk lower is active swap; no cleanup attempted"
fi

# Holder termination is allowed only after the mapper and its lower dependency
# are both positively proven to be private harness RAM. Target the canonical
# dm block node so stale replay processes cannot hide behind the mapper symlink.
mapper_node="$(readlink -f "$mapper" 2>/dev/null || true)"
[[ -n $mapper_node && -b $mapper_node ]] ||
    fail "pre-existing harness dm_swapz canonical device is unavailable"
mapper_dev="$(stat -Lc '%t:%T' "$mapper" 2>/dev/null)" ||
    fail "cannot stat pre-existing harness dm_swapz mapper"
canonical_dev="$(stat -Lc '%t:%T' "$mapper_node" 2>/dev/null)" ||
    fail "cannot stat pre-existing harness dm_swapz canonical device"
[[ -n $mapper_dev && $mapper_dev == "$canonical_dev" ]] ||
    fail "pre-existing harness dm_swapz canonical device identity changed"

wait_for_zero_opens() {
    local attempt

    for attempt in {1..30}; do
        opens="$(read_opens 2>/dev/null || echo "$opens")"
        [[ $opens == 0 ]] && return 0
        command -v udevadm >/dev/null 2>&1 &&
            udevadm settle --timeout=3 2>/dev/null || true
        sleep 0.1
    done
    return 1
}

opens="$(read_opens 2>/dev/null || true)"
if is_uint "$opens" && [[ $opens != 0 ]]; then
    wait_for_zero_opens || true
fi
if is_uint "$opens" && [[ $opens != 0 ]] && command -v fuser >/dev/null 2>&1; then
    fuser -k -TERM "$mapper_node" >/dev/null 2>&1 || true
    wait_for_zero_opens || true
    if is_uint "$opens" && [[ $opens != 0 ]]; then
        fuser -k -KILL "$mapper_node" >/dev/null 2>&1 || true
        wait_for_zero_opens || true
    fi
fi

is_uint "$opens" && [[ $opens == 0 ]] ||
    fail "proven-owned stale dm_swapz mapping remains open after bounded holder cleanup; reboot required before make test"

timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry "$owned_map" ||
    fail "stale harness dm_swapz mapping could not be removed normally"
[[ ! -e $mapper ]] ||
    fail "stale harness dm_swapz mapping still exists after ordinary removal"
refcount="$(read_refcount)"
[[ $refcount == 0 ]] ||
    fail "dm_swapz still has references after stale harness mapping removal"
if [[ -n $owned_config && -d $owned_config ]]; then
    echo 0 > "$owned_config/power" 2>/dev/null || true
    rmdir "$owned_config" 2>/dev/null || true
fi
remove_idle_module
clean_orphaned_nullb
note "AUTO_REMOVED_STALE_OWNED_DM_SWAPZ=1"
