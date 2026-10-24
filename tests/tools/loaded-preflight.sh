#!/usr/bin/env bash
# Private root preflight for make test loaded qualification.
# It may remove only an idle module or one provably stale harness-owned mapping.
set -Eeuo pipefail

fail() { printf 'BLOCKED: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }

for cmd in rmmod dmsetup timeout awk sed tr findmnt cat; do
    command -v "$cmd" >/dev/null || fail "missing required tool $cmd"
done
[[ $(id -u) == 0 ]] || fail "root required for loaded preflight"

if [[ ! -d /sys/module/dm_swapz ]]; then
    note "LOADED_PREFLIGHT_DM_SWAPZ=absent"
    exit 0
fi

read_refcount() {
    local value
    [[ -r /sys/module/dm_swapz/refcnt ]] ||
        fail "pre-existing dm_swapz reference count is unreadable"
    value="$(cat /sys/module/dm_swapz/refcnt)" ||
        fail "cannot read pre-existing dm_swapz reference count"
    [[ $value =~ ^(0|[1-9][0-9]*)$ ]] ||
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
if (( refcount == 0 )); then
    remove_idle_module
    note "AUTO_REMOVED_IDLE_DM_SWAPZ=1"
    exit 0
fi

# A prior bounded qualification may have been killed while its one owned mapper
# was still alive. Recover only the exact private harness identity. Never
# remove multiple mappings, arbitrary swapz mappings, physical lowers, mounts,
# swap aliases, open mappings, or anything requiring force.
mapfile -t swapz_maps < <(
    dmsetup ls --target swapz --noheadings 2>/dev/null |
        awk 'NF { print $1 }'
)
(( ${#swapz_maps[@]} == 1 )) ||
    fail "pre-existing dm_swapz module is busy with non-unique mappings; no cleanup attempted"
owned_map="${swapz_maps[0]}"
[[ $owned_map =~ ^swapz-demo-([a-f0-9]{16})$ ]] ||
    fail "pre-existing dm_swapz mapping is not harness-owned; no cleanup attempted"
token="${BASH_REMATCH[1]}"
uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
    tr -d '[:space:]')" ||
    fail "cannot read pre-existing dm_swapz mapping UUID"
[[ $uuid =~ ^SWAPZ-TEST-$token(-(gc|discardtrim|suspend|writefault|flushfault|packed))?$ ]] ||
    fail "pre-existing dm_swapz mapping UUID is not harness-owned; no cleanup attempted"
opens="$(dmsetup info -c --noheadings -o open "$owned_map" 2>/dev/null |
    tr -d '[:space:]')" ||
    fail "cannot read pre-existing dm_swapz open count"
[[ $opens =~ ^(0|[1-9][0-9]*)$ && $opens == 0 ]] ||
    fail "pre-existing harness dm_swapz mapping is open; no cleanup attempted"

mapper="/dev/mapper/$owned_map"
[[ -z "$(findmnt -rn -S "$mapper" 2>/dev/null)" ]] ||
    fail "pre-existing harness dm_swapz mapping is mounted; no cleanup attempted"
if awk -v path="$mapper" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps; then
    fail "pre-existing harness dm_swapz mapping is active swap; no cleanup attempted"
fi

deps="$(dmsetup deps -o devname "$owned_map" 2>/dev/null)" ||
    fail "cannot read pre-existing dm_swapz dependency"
lower_name="$(printf '%s\n' "$deps" |
    sed -nE 's/^[[:space:]]*1 dependencies[[:space:]]*:[[:space:]]*\(([^()[:space:]]+)\)[[:space:]]*$/\1/p')"
[[ -n $lower_name ]] ||
    fail "pre-existing harness dm_swapz mapping does not have one lower dependency"
[[ $lower_name =~ ^nullb([0-9]+)$ ||
   $lower_name =~ ^nullb-swapz-[a-f0-9]{16}$ ]] ||
    fail "pre-existing harness dm_swapz lower is not null_blk"

cfgbase=/sys/kernel/config/nullb
[[ -d $cfgbase ]] ||
    fail "pre-existing harness null_blk configfs is unavailable"
owned_config=""
if [[ $lower_name =~ ^nullb-swapz-[a-f0-9]{16}$ &&
      -d $cfgbase/$lower_name ]]; then
    owned_config="$cfgbase/$lower_name"
elif [[ $lower_name =~ ^nullb([0-9]+)$ ]]; then
    lower_index="${BASH_REMATCH[1]}"
    matches=()
    shopt -s nullglob
    for config in "$cfgbase"/nullb-swapz-*; do
        [[ -d $config && -r $config/index ]] || continue
        [[ "$(cat "$config/index" 2>/dev/null)" == "$lower_index" ]] &&
            matches+=("$config")
    done
    shopt -u nullglob
    (( ${#matches[@]} == 1 )) &&
        owned_config="${matches[0]}"
fi
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

timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry "$owned_map" ||
    fail "stale harness dm_swapz mapping could not be removed normally"
[[ ! -e $mapper ]] ||
    fail "stale harness dm_swapz mapping still exists after ordinary removal"
refcount="$(read_refcount)"
(( refcount == 0 )) ||
    fail "dm_swapz still has references after stale harness mapping removal"
remove_idle_module
note "AUTO_REMOVED_STALE_OWNED_DM_SWAPZ=1"
