#!/usr/bin/env bash
# Private root preflight for make test loaded qualification.
# It cleans verified completed swapz benchmark scratch before its memory
# observation and may remove only an idle module or a proven stale mapping.
set -Eeuo pipefail

# Safety refusals are not reproduced test failures. Never guess a kernel errno
# from the exit code of an external utility.
refuse() {
    local disposition="$1" check="$2" original_errno="$3"
    shift 3
    printf 'BLOCKED: LOADED_PREFLIGHT=%s check=%s errno=%s remedy=%s\n' \
        "$disposition" "$check" "$original_errno" "$*" >&2
    exit 1
}
fail() { refuse BLOCKED ownership_proof unavailable "$*"; }

script_source="${BASH_SOURCE[0]}"
case "$script_source" in
    */*) script_directory="${script_source%/*}" ;;
    *) script_directory=. ;;
esac
SCRIPT_DIR="$(cd -- "$script_directory" 2>/dev/null && pwd -P)" ||
    fail "cannot resolve loaded-preflight helper directory"
cleanup_helper="$SCRIPT_DIR/clear-tmp-before-memory-check.sh"
[[ -r $cleanup_helper ]] ||
    fail "owned temporary-cleanup helper unavailable; restore the readable checkout helper"
source "$cleanup_helper" 2>/dev/null ||
    fail "owned temporary-cleanup helper could not be loaded safely"
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

# Include every unconditionally used external utility in the audit.
for cmd in rmmod dmsetup modprobe timeout awk tr findmnt cat readlink stat sleep id ls find rm rmdir python3 uname; do
    command -v "$cmd" >/dev/null ||
        refuse BLOCKED required_tool 2 "install required executable $cmd before make test"
done
[[ $(id -u) == 0 ]] ||
    refuse NOT_AUTHORIZED effective_uid 1 "provide noninteractive root authorization"

# UID zero in a container need not have host CAP_SYS_ADMIN. This read-only
# probe returns the original file-read errno, never a guessed command errno.
capability_status="$(python3 - /proc/self/status <<'PY'
import sys
try:
    with open(sys.argv[1], "r", encoding="ascii") as status_file:
        matches = [line.split()[1] for line in status_file
                   if line.startswith("CapEff:") and len(line.split()) == 2]
except OSError as error:
    print("unreadable:" + str(error.errno if error.errno is not None else "unavailable"))
else:
    try:
        if len(matches) != 1 or not matches[0] or len(matches[0]) > 16:
            raise ValueError("invalid CapEff")
        effective = int(matches[0], 16)
        print("present" if effective & (1 << 21) else "missing")
    except ValueError:
        print("invalid")
PY
)" || refuse BLOCKED cap_sys_admin unavailable "cannot inspect effective capability record"
case "$capability_status" in
    present) ;;
    missing) refuse NOT_AUTHORIZED cap_sys_admin 1 "CAP_SYS_ADMIN is missing; use an authorized host, not a rootless container" ;;
    invalid) refuse BLOCKED cap_sys_admin 22 "repair malformed /proc/self/status capability evidence" ;;
    unreadable:*) refuse BLOCKED cap_sys_admin "${capability_status#unreadable:}" "restore readable capability evidence" ;;
    *) refuse BLOCKED cap_sys_admin unavailable "unexpected capability probe result" ;;
esac

# Probe module support without loading any module. A configured built-in
# null_blk is already sufficient for this gate.
if [[ ! -d /sys/kernel/config/nullb ]] &&
   ! modprobe -n -q null_blk >/dev/null 2>&1; then
    refuse BLOCKED null_blk_module unavailable "null_blk is not discoverable; restore its kernel module/configuration"
fi

# The later loaded debug evidence remains authoritative. Reject only an
# available but contradictory kernel .config here; a missing config remains
# UNAVAILABLE evidence, not a fabricated sanitizer failure.
kernel_debug_status="$(python3 - /proc/config.gz "/boot/config-$(uname -r)" "/lib/modules/$(uname -r)/build/.config" <<'PY'
import gzip
import os
import sys

selected = None
for candidate in sys.argv[1:]:
    if os.path.isfile(candidate):
        selected = candidate
        break
if selected is None:
    print("unavailable")
else:
    try:
        opener = gzip.open if selected.endswith(".gz") else open
        with opener(selected, "rt", encoding="ascii") as config_file:
            lines = config_file.read().splitlines()
        for symbol in ("CONFIG_KASAN", "CONFIG_KCSAN", "CONFIG_PROVE_LOCKING"):
            enabled = sum(line == symbol + "=y" for line in lines)
            disabled = sum(line == "# " + symbol + " is not set" for line in lines)
            if enabled + disabled != 1:
                raise ValueError("ambiguous kernel debug configuration")
        print("valid")
    except OSError as error:
        print("unreadable:" + str(error.errno if error.errno is not None else 22))
    except (ValueError, UnicodeError):
        print("invalid")
PY
)" || refuse BLOCKED kernel_debug_config unavailable "cannot inspect kernel debug configuration"
case "$kernel_debug_status" in
    valid|unavailable) ;;
    invalid) refuse BLOCKED kernel_debug_config 22 "running kernel debug options are contradictory or malformed; verify original .config" ;;
    unreadable:*) refuse BLOCKED kernel_debug_config "${kernel_debug_status#unreadable:}" "restore readable running-kernel debug configuration" ;;
    *) refuse BLOCKED kernel_debug_config unavailable "unexpected debug configuration probe result" ;;
esac

# A retained package transaction belongs to the package recovery owner.
# Do not erase its journal or conflate it with a clean preflight.
package_journal=/var/lib/swapz-package-transactions
if [[ -e $package_journal || -L $package_journal ]]; then
    [[ -d $package_journal && ! -L $package_journal ]] ||
        refuse BLOCKED package_journal 22 "package journal directory identity is invalid"
    journal_entries="$(ls -A -- "$package_journal" 2>/dev/null)" ||
        refuse BLOCKED package_journal unavailable "inspect journal permissions and recovery ownership"
    [[ -z $journal_entries ]] ||
        refuse BLOCKED package_journal 16 "recover the retained package transaction under its own lock; never delete it to retry"
fi

if swapz_clear_tmp_before_memory_check; then
    :
else
    cleanup_status=$?
    refuse BLOCKED completed_owned_tmp_cleanup unavailable "helper_status=$cleanup_status; check private completion proof and permissions; no broad /tmp deletion"
fi
note "LOADED_PREFLIGHT_TMP_CLEANUP=completed-owned-only"

# Diagnostic only: early loaded-stage RAM is not the later ID36 admission
# sample. Never fail preflight from a transient low reading, and never mutate
# host swap or kernel caches to improve this observation.
early_available_kib="$(awk '
    $1 == "MemAvailable:" {
        if (NF != 3 || $2 !~ /^(0|[1-9][0-9]*)$/ ||
            $3 != "kB" || length($2) > 18 || ++seen != 1)
            invalid = 1
        else
            value = $2
    }
    END {
        if (invalid || seen != 1)
            exit 1
        print value
    }
' /proc/meminfo 2>/dev/null || true)"
if ! is_uint "$early_available_kib"; then
    printf '%s\n' 'OBSERVED_ID36_EARLY_HOST_MEMORY=source:/proc/meminfo status:unavailable required:1048576 unit:kB admission:no; restore readable canonical MemAvailable telemetry before ID36' >&2
elif (( early_available_kib < 1048576 )); then
    printf 'OBSERVED_ID36_EARLY_HOST_MEMORY=source:/proc/meminfo available:%s required:1048576 unit:kB admission:no; allow ordinary reclaim before ID36\n' \
        "$early_available_kib" >&2
fi

# A token-shaped configfs name alone does not prove that this run owns it.
# Never power off or remove another session's RAM device on speculation.
clean_orphaned_nullb() {
    local cfgbase=/sys/kernel/config/nullb
    local cfg name orphan_token
    [[ -d $cfgbase ]] || return 0
    for cfg in "$cfgbase"/nullb-swapz-*; do
        [[ -d $cfg ]] || continue
        name="${cfg##*/}"
        orphan_token="${name#nullb-swapz-}"
        is_hex16 "$orphan_token" || continue
        refuse BLOCKED unclaimed_null_blk 16 "token-named null_blk exists without unique mapper ownership proof; leave it untouched"
    done
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
    if rmmod dm_swapz; then
        :
    else
        module_remove_status=$?
        refuse BLOCKED idle_module_removal unavailable "rmmod_status=$module_remove_status; inspect module users; do not force remove"
    fi
    [[ ! -d /sys/module/dm_swapz ]] ||
        refuse BLOCKED idle_module_removal 16 "module remains after ordinary removal"
}

refcount="$(read_refcount)" || exit 1
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
    refuse BLOCKED mapper_inventory 16 "busy dm_swapz has zero or multiple mappings; no cleanup attempted"
owned_map="${swapz_maps[0]}"
case "$owned_map" in
    swapz-demo-*) token="${owned_map#swapz-demo-}" ;;
    *) fail "pre-existing dm_swapz mapping is not harness-owned; no cleanup attempted" ;;
esac
is_hex16 "$token" ||
    refuse BLOCKED stale_run_token 22 "mapper ownership token is malformed"
uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
    tr -d '[:space:]')" ||
    fail "cannot read pre-existing dm_swapz mapping UUID"
case "$uuid" in
    "SWAPZ-TEST-$token"|"SWAPZ-TEST-$token-gc"| \
    "SWAPZ-TEST-$token-discardtrim"|"SWAPZ-TEST-$token-suspend"| \
    "SWAPZ-TEST-$token-writefault"|"SWAPZ-TEST-$token-flushfault"| \
    "SWAPZ-TEST-$token-packed") ;;
    *) refuse BLOCKED stale_run_token 16 "mapper UUID is not bound to the expected run token" ;;
esac
mapper="/dev/mapper/$owned_map"
[[ -z "$(findmnt -rn -S "$mapper" 2>/dev/null)" ]] ||
    refuse BLOCKED mounted_owned_mapper 16 "owned mapper is mounted; no cleanup attempted"
if awk -v path="$mapper" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps; then
    refuse BLOCKED active_owned_swap 16 "owned mapper is active swap; leave host swap unchanged"
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
            refuse BLOCKED null_blk_owner 22 "lower identity is not an owned null_blk"
        [[ "$lower_token" == "$token" ]] ||
            refuse BLOCKED null_blk_owner 16 "lower ownership token differs from mapper token"
        [[ -d $cfgbase/$lower_name ]] &&
            owned_config="$cfgbase/$lower_name"
        ;;
    nullb*)
        lower_index="${lower_name#nullb}"
        is_uint "$lower_index" ||
            fail "pre-existing harness dm_swapz lower is not null_blk"
        matches=()
        for config in "$cfgbase"/nullb-swapz-*; do
            [[ -d $config && -r $config/index ]] || continue
            [[ "$(cat "$config/index" 2>/dev/null)" == "$lower_index" ]] &&
                matches+=("$config")
        done
        [[ ${#matches[@]} == 1 &&
           ${matches[0]:-} == "$cfgbase/nullb-swapz-$token" ]] ||
            refuse BLOCKED null_blk_owner 16 "index has no unique run-token-bound configfs owner"
        owned_config="${matches[0]}"
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
    refuse BLOCKED mounted_owned_lower 16 "owned lower is mounted; no cleanup attempted"
if awk -v path="$lower" 'NR > 1 && $1 == path { found=1 } END { exit found ? 0 : 1 }' /proc/swaps; then
    refuse BLOCKED active_owned_swap 16 "null_blk lower is active swap; leave host swap unchanged"
fi

# Holder termination is allowed only after the mapper and its lower dependency
# are both positively proven to be private harness RAM. Target the canonical
# dm block node so stale replay processes cannot hide behind the mapper symlink.
mapper_node="$(readlink -f "$mapper" 2>/dev/null || true)"
[[ -n $mapper_node && -b $mapper_node ]] ||
    refuse BLOCKED mapper_device_identity unavailable "canonical mapper block node is missing or unreadable; no holder signal"
mapper_dev="$(stat -Lc '%t:%T' "$mapper" 2>/dev/null)" ||
    refuse BLOCKED mapper_device_identity unavailable "cannot stat mapper; no holder signal"
canonical_dev="$(stat -Lc '%t:%T' "$mapper_node" 2>/dev/null)" ||
    refuse BLOCKED mapper_device_identity unavailable "cannot stat canonical mapper; no holder signal"
[[ -n $mapper_dev && $mapper_dev == "$canonical_dev" ]] ||
    refuse BLOCKED mapper_device_identity 16 "canonical device identity changed; no holder signal"

wait_for_zero_opens() {
    local attempt

    for attempt in {1..30}; do
        opens="$(read_opens)" ||
            refuse BLOCKED mapper_open_count unavailable "cannot inspect live mapper opens; no holder signal"
        [[ $opens == 0 ]] && return 0
        command -v udevadm >/dev/null 2>&1 &&
            udevadm settle --timeout=3 2>/dev/null || true
        sleep 0.1
    done
    return 1
}

opens="$(read_opens)" ||
    refuse BLOCKED mapper_open_count unavailable "cannot inspect initial mapper opens; no holder signal"
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
    refuse BLOCKED mapper_open_count 16 "owned mapping remains open after bounded cleanup; reboot required before make test"

if timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry "$owned_map"; then
    :
else
    mapper_remove_status=$?
    refuse BLOCKED owned_mapper_removal unavailable "dmsetup_status=$mapper_remove_status; nonforce removal refused"
fi
[[ ! -e $mapper ]] ||
    fail "stale harness dm_swapz mapping still exists after ordinary removal"
refcount="$(read_refcount)" || exit 1
[[ $refcount == 0 ]] ||
    fail "dm_swapz still has references after stale harness mapping removal"
if [[ -n $owned_config && -d $owned_config ]]; then
    printf '0\n' > "$owned_config/power" 2>/dev/null ||
        refuse BLOCKED null_blk_power_off unavailable "owned configfs power-off refused; retain proof"
    rmdir -- "$owned_config" 2>/dev/null ||
        refuse BLOCKED null_blk_config_removal unavailable "owned configfs removal refused; retain proof"
fi
remove_idle_module
clean_orphaned_nullb
note "AUTO_REMOVED_STALE_OWNED_DM_SWAPZ=1"
