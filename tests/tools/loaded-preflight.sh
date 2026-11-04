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
    refuse BLOCKED preflight_helper_directory unavailable "cannot resolve loaded-preflight helper directory"
cleanup_helper="$SCRIPT_DIR/clear-tmp-before-memory-check.sh"
[[ -r $cleanup_helper ]] ||
    refuse BLOCKED completed_owned_tmp_cleanup_helper unavailable "restore the readable checkout cleanup helper"
source "$cleanup_helper" 2>/dev/null ||
    refuse BLOCKED completed_owned_tmp_cleanup_helper unavailable "cleanup helper could not be loaded safely"
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
        refuse BLOCKED required_tool unavailable "install required executable $cmd before make test"
done
[[ $(id -u) == 0 ]] ||
    refuse NOT_AUTHORIZED effective_uid unavailable "provide noninteractive root authorization"

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
    missing) refuse NOT_AUTHORIZED cap_sys_admin unavailable "CAP_SYS_ADMIN is missing; use an authorized host, not a rootless container" ;;
    invalid) refuse BLOCKED cap_sys_admin unavailable "repair malformed /proc/self/status capability evidence" ;;
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
    except (gzip.BadGzipFile, EOFError, ValueError, UnicodeError):
        print("invalid")
    except OSError as error:
        print("unreadable:" + str(error.errno if error.errno is not None else "unavailable"))
PY
)" || refuse BLOCKED kernel_debug_config unavailable "cannot inspect kernel debug configuration"
case "$kernel_debug_status" in
    valid|unavailable) ;;
    invalid) refuse BLOCKED kernel_debug_config unavailable "running kernel debug options are contradictory or malformed; verify original .config" ;;
    unreadable:*) refuse BLOCKED kernel_debug_config "${kernel_debug_status#unreadable:}" "restore readable running-kernel debug configuration" ;;
    *) refuse BLOCKED kernel_debug_config unavailable "unexpected debug configuration probe result" ;;
esac

# A retained package transaction belongs to the package recovery owner.
# Do not erase its journal or conflate it with a clean preflight.
package_journal=/var/lib/swapz-package-transactions
if [[ -e $package_journal || -L $package_journal ]]; then
    [[ -d $package_journal && ! -L $package_journal ]] ||
        refuse BLOCKED package_journal unavailable "package journal directory identity is invalid"
    if journal_entries="$(ls -A -- "$package_journal" 2>/dev/null)"; then
        :
    else
        journal_status=$?
        refuse BLOCKED package_journal unavailable "ls_status=$journal_status; inspect journal permissions and recovery ownership"
    fi
    [[ -z $journal_entries ]] ||
        refuse BLOCKED package_journal unavailable "recover the retained package transaction under its own lock; never delete it to retry"
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
        refuse BLOCKED unclaimed_null_blk unavailable "token-named null_blk exists without unique mapper ownership proof; leave it untouched"
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
        refuse BLOCKED module_refcount unavailable "pre-existing dm_swapz reference count is unreadable"
    value="$(cat /sys/module/dm_swapz/refcnt)" ||
        refuse BLOCKED module_refcount unavailable "cannot read pre-existing dm_swapz reference count"
    is_uint "$value" ||
        refuse BLOCKED module_refcount unavailable "pre-existing dm_swapz reference count is malformed"
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
        refuse BLOCKED idle_module_removal unavailable "module remains after ordinary removal"
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
# Do not turn a malformed dmsetup device number into an apparent owned name.
# Every record needs one bounded name and a canonical decimal major:minor pair.
if swapz_map_list="$(
    dmsetup ls --target swapz --noheadings 2>/dev/null |
        awk '
            {
                if (NF != 2 || length($1) > 127 || length($2) > 23 ||
                    $2 !~ /^[(](0|[1-9][0-9]*):(0|[1-9][0-9]*)[)]$/) {
                    malformed = 1
                    next
                }
                print $1
            }
            END { if (malformed) exit 2 }
        '
)"; then
    :
else
    inventory_status=$?
    refuse BLOCKED mapper_inventory unavailable "pipeline_status=$inventory_status; cannot enumerate pre-existing swapz mappings: expected bounded name (canonical decimal major:minor) records, observed invalid or unreadable listing; inspect dmsetup inventory without cleanup"
fi
swapz_maps=()
if [[ -n $swapz_map_list ]]; then
    mapfile -t swapz_maps <<< "$swapz_map_list" ||
        refuse BLOCKED mapper_inventory unavailable "cannot parse pre-existing swapz mapping list"
fi
[[ ${#swapz_maps[@]} == 1 ]] ||
    refuse BLOCKED mapper_inventory unavailable "busy dm_swapz has zero or multiple mappings; no cleanup attempted"
owned_map="${swapz_maps[0]}"
case "$owned_map" in
    swapz-demo-*) token="${owned_map#swapz-demo-}" ;;
    *) refuse BLOCKED stale_run_token unavailable "mapping name is not harness-owned; no cleanup attempted" ;;
esac
is_hex16 "$token" ||
    refuse BLOCKED stale_run_token unavailable "mapper ownership token is malformed"
uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
    tr -d '[:space:]')" ||
    refuse BLOCKED mapper_uuid unavailable "cannot read pre-existing dm_swapz mapping UUID"
case "$uuid" in
    "SWAPZ-TEST-$token"|"SWAPZ-TEST-$token-gc"| \
    "SWAPZ-TEST-$token-discardtrim"|"SWAPZ-TEST-$token-suspend"| \
    "SWAPZ-TEST-$token-writefault"|"SWAPZ-TEST-$token-readfault"| \
    "SWAPZ-TEST-$token-flushfault"|"SWAPZ-TEST-$token-packed"| \
    "SWAPZ-TEST-$token-codec-inline"|"SWAPZ-TEST-$token-codec-submitter"| \
    "SWAPZ-TEST-$token-codec-background"|"SWAPZ-TEST-$token-completion"| \
    "SWAPZ-TEST-$token-completionfault"|"SWAPZ-TEST-$token-ctor-"[1-8]) ;;
    *) refuse BLOCKED stale_run_token unavailable "mapper UUID is not bound to the expected run token" ;;
esac
assert_not_mounted() {
    local source="$1" check="$2" mount_output mount_status

    if mount_output="$(findmnt -rn -S "$source" 2>/dev/null)"; then
        [[ -n $mount_output ]] ||
            refuse BLOCKED mount_inventory unavailable "findmnt returned success without a mount identity"
        refuse BLOCKED "$check" unavailable "source is mounted; no cleanup attempted"
    else
        mount_status=$?
    fi
    [[ $mount_status == 1 ]] ||
        refuse BLOCKED mount_inventory unavailable "findmnt_status=$mount_status; cannot prove source is unmounted"
}

assert_not_active_swap() {
    local source="$1" swap_entries swap_status source_devno
    local swap_path swap_type swap_devno

    [[ -b $source ]] ||
        refuse BLOCKED swap_device_identity unavailable "owned swap candidate is not a readable block device"
    if source_devno="$(stat -Lc '%t:%T' "$source" 2>/dev/null)"; then
        [[ -n $source_devno ]] ||
            refuse BLOCKED swap_device_identity unavailable "owned block source has empty device identity"
    else
        swap_status=$?
        refuse BLOCKED swap_device_identity unavailable "stat_status=$swap_status; cannot inspect owned block source identity"
    fi

    if swap_entries="$(awk '
        NR == 1 {
            if (NF != 5 || $1 != "Filename" || $2 != "Type" ||
                $3 != "Size" || $4 != "Used" || $5 != "Priority")
                invalid = 1
            next
        }
        NF {
            if (NF != 5 || substr($1, 1, 1) != "/" ||
                ($2 != "file" && $2 != "partition") ||
                $3 !~ /^(0|[1-9][0-9]*)$/ ||
                $4 !~ /^(0|[1-9][0-9]*)$/ ||
                $5 !~ /^(0|-[1-9][0-9]*|[1-9][0-9]*)$/)
                invalid = 1
            else
                printf "%s\t%s\n", $1, $2
        }
        END {
            if (invalid || NR < 1)
                exit 2
        }
    ' /proc/swaps 2>/dev/null)"; then
        :
    else
        swap_status=$?
        refuse BLOCKED swap_inventory unavailable "awk_status=$swap_status; cannot parse host swap inventory"
    fi

    [[ -n $swap_entries ]] || return 0
    while IFS=$'\t' read -r swap_path swap_type; do
        [[ -n $swap_path && -n $swap_type ]] ||
            refuse BLOCKED swap_inventory unavailable "parsed swap identity is incomplete"
        [[ $swap_path != "$source" ]] ||
            refuse BLOCKED active_owned_swap unavailable "owned source is active swap; leave host swap unchanged"
        [[ $swap_type == partition ]] || continue
        [[ -b $swap_path ]] ||
            refuse BLOCKED swap_inventory unavailable "block swap path is unavailable; cannot prove its identity differs"
        if swap_devno="$(stat -Lc '%t:%T' "$swap_path" 2>/dev/null)"; then
            :
        else
            swap_status=$?
            refuse BLOCKED swap_inventory unavailable "stat_status=$swap_status; cannot resolve a block swap identity"
        fi
        [[ -n $swap_devno ]] ||
            refuse BLOCKED swap_inventory unavailable "block swap identity is empty"
        [[ $swap_devno != "$source_devno" ]] ||
            refuse BLOCKED active_owned_swap unavailable "owned block identity is active swap under another path"
    done <<< "$swap_entries"
}

mapper="/dev/mapper/$owned_map"
assert_not_mounted "$mapper" mounted_owned_mapper
assert_not_active_swap "$mapper"

read_opens() {
    local val
    val="$(dmsetup info -c --noheadings -o open "$owned_map" 2>/dev/null |
        tr -d '[:space:]')" || return 1
    is_uint "$val" || return 1
    printf '%s\n' "$val"
}

deps="$(dmsetup deps -o devname "$owned_map" 2>/dev/null)" ||
    refuse BLOCKED mapper_dependency unavailable "cannot read pre-existing dm_swapz dependency"
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
')" || refuse BLOCKED mapper_dependency unavailable "mapping does not expose one lower dependency"

cfgbase=/sys/kernel/config/nullb
[[ -d $cfgbase ]] ||
    refuse BLOCKED null_blk_configfs unavailable "pre-existing harness null_blk configfs is unavailable"
owned_config=""
lower_index=""
case "$lower_name" in
    nullb-swapz-*)
        lower_token="${lower_name#nullb-swapz-}"
        is_hex16 "$lower_token" ||
            refuse BLOCKED null_blk_owner unavailable "lower identity is not an owned null_blk"
        [[ "$lower_token" == "$token" ]] ||
            refuse BLOCKED null_blk_owner unavailable "lower ownership token differs from mapper token"
        [[ -d $cfgbase/$lower_name ]] &&
            owned_config="$cfgbase/$lower_name"
        ;;
    nullb*)
        lower_index="${lower_name#nullb}"
        is_uint "$lower_index" ||
            refuse BLOCKED null_blk_owner unavailable "pre-existing harness dm_swapz lower is not null_blk"
        matches=()
        for config in "$cfgbase"/nullb-swapz-*; do
            [[ -d $config && -r $config/index ]] || continue
            [[ "$(cat "$config/index" 2>/dev/null)" == "$lower_index" ]] &&
                matches+=("$config")
        done
        [[ ${#matches[@]} == 1 &&
           ${matches[0]:-} == "$cfgbase/nullb-swapz-$token" ]] ||
            refuse BLOCKED null_blk_owner unavailable "index has no unique run-token-bound configfs owner"
        owned_config="${matches[0]}"
        ;;
    *)
        refuse BLOCKED null_blk_owner unavailable "pre-existing harness dm_swapz lower is not null_blk"
        ;;
esac
[[ -n $owned_config &&
   -r $owned_config/memory_backed &&
   -r $owned_config/power &&
   "$(cat "$owned_config/memory_backed" 2>/dev/null)" == 1 &&
   "$(cat "$owned_config/power" 2>/dev/null)" == 1 ]] ||
    refuse BLOCKED null_blk_owner unavailable "pre-existing dm_swapz lower is not a proven owned memory-backed null_blk"

lower="/dev/$lower_name"
assert_not_mounted "$lower" mounted_owned_lower
assert_not_active_swap "$lower"

# Holder termination is allowed only after the mapper and its lower dependency
# are both positively proven to be private harness RAM. Target the canonical
# dm block node so stale replay processes cannot hide behind the mapper symlink.
mapper_node="$(readlink -f "$mapper" 2>/dev/null || true)"
[[ -n $mapper_node && -b $mapper_node ]] ||
    refuse BLOCKED mapper_device_identity unavailable "canonical mapper block node is missing or unreadable; no holder signal"
if mapper_dev="$(stat -Lc '%t:%T' "$mapper" 2>/dev/null)"; then
    :
else
    mapper_stat_status=$?
    refuse BLOCKED mapper_device_identity unavailable "stat_status=$mapper_stat_status; cannot stat mapper; no holder signal"
fi
if canonical_dev="$(stat -Lc '%t:%T' "$mapper_node" 2>/dev/null)"; then
    :
else
    canonical_stat_status=$?
    refuse BLOCKED mapper_device_identity unavailable "stat_status=$canonical_stat_status; cannot stat canonical mapper; no holder signal"
fi
[[ -n $mapper_dev && $mapper_dev == "$canonical_dev" ]] ||
    refuse BLOCKED mapper_device_identity unavailable "canonical device identity changed; no holder signal"

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
    refuse BLOCKED mapper_open_count unavailable "owned mapping remains open after bounded cleanup; reboot required before make test"

if timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry "$owned_map"; then
    :
else
    mapper_remove_status=$?
    refuse BLOCKED owned_mapper_removal unavailable "dmsetup_status=$mapper_remove_status; nonforce removal refused"
fi
[[ ! -e $mapper ]] ||
    refuse BLOCKED owned_mapper_removal unavailable "stale harness dm_swapz mapping still exists after ordinary removal"
refcount="$(read_refcount)" || exit 1
[[ $refcount == 0 ]] ||
    refuse BLOCKED module_refcount unavailable "dm_swapz still has references after stale harness mapping removal"
if [[ -n $owned_config && -d $owned_config ]]; then
    printf '0\n' > "$owned_config/power" 2>/dev/null ||
        refuse BLOCKED null_blk_power_off unavailable "owned configfs power-off refused; retain proof"
    rmdir -- "$owned_config" 2>/dev/null ||
        refuse BLOCKED null_blk_config_removal unavailable "owned configfs removal refused; retain proof"
fi
remove_idle_module
clean_orphaned_nullb
note "AUTO_REMOVED_STALE_OWNED_DM_SWAPZ=1"
