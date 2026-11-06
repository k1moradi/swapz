#!/usr/bin/env bash
# Private root preflight for make test loaded qualification.
# It cleans verified completed scratch only after null_blk admission.
# A prior session's name, UUID and live device evidence do not establish
# creation authority: pre-existing mapping, RAM lower and module are retained.
set -Eeuo pipefail

# Safety refusals are not reproduced test failures. Never guess a kernel errno
# from the exit code of an external utility.
refuse() {
    local disposition="$1" check="$2" original_errno="$3"
    shift 3
    local remedy="$*"
    [[ $remedy == *expected_proof=* ]] ||
        remedy="$remedy; expected_proof=${check}_admission"
    [[ $remedy == *observed_proof=* ]] ||
        remedy="$remedy; observed_proof=unverified"
    [[ $remedy == *original_errno_or_exit=* ]] ||
        remedy="$remedy; original_errno_or_exit=$original_errno"
    [[ $remedy == *retained_state_action=* ]] ||
        remedy="$remedy; retained_state_action=retain_resources"
    [[ $remedy == *safe_next_action=* ]] ||
        remedy="$remedy; safe_next_action=inspect_read_only"
    printf 'BLOCKED: LOADED_PREFLIGHT=%s check=%s errno=%s remedy=%s\n' \
        "$disposition" "$check" "$original_errno" "$remedy" >&2
    # Safety refusals have one stable process status. Preserve a real errno or
    # external command status in the diagnostic fields above; status 2 remains
    # reserved by test-loaded.sh for shell/runtime failure before classification.
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
# Reuse the native null_blk identity parser; the helper is read-only and
# grants neither inherited creation authority nor permission to clean up.
identity_helper="$SCRIPT_DIR/nullblk-identity.sh"
[[ -r $identity_helper ]] ||
    refuse BLOCKED null_blk_identity_helper unavailable "restore the readable checkout identity helper"
source "$identity_helper" 2>/dev/null ||
    refuse BLOCKED null_blk_identity_helper unavailable "identity helper could not be loaded safely"
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
for cmd in dmsetup modprobe timeout awk tr findmnt cat readlink stat sleep id ls find rm rmdir python3 uname; do
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
        refuse BLOCKED package_journal unavailable "ls_status=$journal_status; original_errno_or_exit=$journal_status; inspect journal permissions and recovery ownership"
    fi
    [[ -z $journal_entries ]] ||
        refuse BLOCKED package_journal unavailable "recover the retained package transaction under its own lock; never delete it to retry"
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
        refuse BLOCKED unclaimed_null_blk unavailable "phase=orphan_scan resource_kind=null_blk expected_proof=creation_authority observed_proof=token_name_only original_errno_or_exit=unavailable retained_state_action=retain_unclaimed_null_blk safe_next_action=original_creator_revalidate_then_cleanup_or_read_only_reconcile"
    done
}

if [[ ! -d /sys/module/dm_swapz ]]; then
    # Resolve ambiguous null_blk ownership before touching completed scratch.
    # A BLOCKED resource gate must not perform even unrelated preflight cleanup.
    clean_orphaned_nullb
if swapz_clear_tmp_before_memory_check; then
    :
else
    cleanup_status=$?
    refuse BLOCKED completed_owned_tmp_cleanup unavailable "helper_status=$cleanup_status; original_errno_or_exit=$cleanup_status; check private completion proof and permissions; no broad /tmp deletion"
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

    note "LOADED_PREFLIGHT_DM_SWAPZ=absent"
    exit 0
fi

read_refcount() {
    local value
    [[ -r /sys/module/dm_swapz/refcnt ]] ||
        refuse BLOCKED module_refcount unavailable "pre-existing dm_swapz reference count is unreadable"
    if value="$(cat /sys/module/dm_swapz/refcnt)"; then
        :
    else
        refcount_status=$?
        refuse BLOCKED module_refcount unavailable "cat_status=$refcount_status; original_errno_or_exit=$refcount_status; cannot read pre-existing dm_swapz reference count"
    fi
    is_uint "$value" ||
        refuse BLOCKED module_refcount unavailable "pre-existing dm_swapz reference count is malformed"
    printf '%s\n' "$value"
}

remove_idle_module() {
    # An idle refcount is not provenance: the module may be another owner's.
    # No module creation authority survives in this preflight process.
    refuse BLOCKED idle_module_removal unavailable "phase=module_unload resource_kind=module expected_proof=creation_authority observed_proof=refcount_only original_errno_or_exit=unavailable retained_state_action=retain_module"
}

refcount="$(read_refcount)" || exit 1
if [[ $refcount == 0 ]]; then
    # The origin of an idle, already-loaded module cannot be inferred.
    remove_idle_module
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
                ++records
                if (records <= 2)
                    printf "%s\t%s\n", $1, substr($2, 2, length($2) - 2)
            }
            END { if (malformed) exit 2 }
        '
)"; then
    :
else
    inventory_status=$?
    refuse BLOCKED mapper_inventory unavailable "pipeline_status=$inventory_status; original_errno_or_exit=$inventory_status; cannot enumerate pre-existing swapz mappings: expected bounded name (canonical decimal major:minor) records, observed invalid or unreadable listing; inspect dmsetup inventory without cleanup"
fi
swapz_map_records=()
swapz_maps=()
swapz_map_devnos=()
if [[ -n $swapz_map_list ]]; then
    mapfile -t swapz_map_records <<< "$swapz_map_list" ||
        refuse BLOCKED mapper_inventory unavailable "cannot parse pre-existing swapz mapping list"
    for swapz_map_record in "${swapz_map_records[@]}"; do
        IFS=$'\t' read -r swapz_map_name swapz_map_devno swapz_map_extra <<< "$swapz_map_record"
        [[ -n $swapz_map_name && -n $swapz_map_devno && -z $swapz_map_extra ]] ||
            refuse BLOCKED mapper_inventory unavailable "parsed mapper inventory record is incomplete"
        swapz_maps+=("$swapz_map_name")
        swapz_map_devnos+=("$swapz_map_devno")
    done
fi
[[ ${#swapz_maps[@]} == 1 ]] ||
    refuse BLOCKED mapper_inventory unavailable "busy dm_swapz has zero or multiple mappings; no cleanup attempted"
[[ ${#swapz_map_devnos[@]} == 1 ]] ||
    refuse BLOCKED mapper_inventory unavailable "single mapper inventory lacks one device identity; no cleanup attempted"
owned_map="${swapz_maps[0]}"
listed_mapper_devno="${swapz_map_devnos[0]}"
case "$owned_map" in
    swapz-demo-*) token="${owned_map#swapz-demo-}" ;;
    *) refuse BLOCKED stale_run_token unavailable "mapping name is not harness-owned; no cleanup attempted" ;;
esac
is_hex16 "$token" ||
    refuse BLOCKED stale_run_token unavailable "mapper ownership token is malformed"
if uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
    tr -d '[:space:]')"; then
    :
else
    uuid_status=$?
    refuse BLOCKED mapper_uuid unavailable "phase=uuid_snapshot resource_kind=mapper expected_proof=readable_uuid observed_proof=probe_failed original_errno_or_exit=$uuid_status retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"
fi
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
        refuse BLOCKED mount_inventory unavailable "findmnt_status=$mount_status; original_errno_or_exit=$mount_status; cannot prove source is unmounted"
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
        refuse BLOCKED swap_device_identity unavailable "stat_status=$swap_status; original_errno_or_exit=$swap_status; cannot inspect owned block source identity"
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
        refuse BLOCKED swap_inventory unavailable "awk_status=$swap_status; original_errno_or_exit=$swap_status; cannot parse host swap inventory"
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
            refuse BLOCKED swap_inventory unavailable "stat_status=$swap_status; original_errno_or_exit=$swap_status; cannot resolve a block swap identity"
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

if dependency_name_proof="$(dmsetup deps -o devname "$owned_map" 2>/dev/null)"; then
    :
else
    dependency_status=$?
    refuse BLOCKED mapper_dependency unavailable "phase=dependency_snapshot resource_kind=mapper expected_proof=readable_dependency_name observed_proof=probe_failed original_errno_or_exit=$dependency_status retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"
fi
if lower_name="$(printf '%s\n' "$dependency_name_proof" | awk '
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
')"; then
    :
else
    dependency_parse_status=$?
    refuse BLOCKED mapper_dependency unavailable "phase=dependency_name_parse resource_kind=mapper expected_proof=one_canonical_dependency_name observed_proof=malformed_or_missing original_errno_or_exit=$dependency_parse_status retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"
fi
if dependency_devno_proof="$(dmsetup deps -o devno "$owned_map" 2>/dev/null)"; then
    :
else
    dependency_status=$?
    refuse BLOCKED mapper_dependency unavailable "phase=dependency_snapshot resource_kind=mapper expected_proof=readable_dependency_devno observed_proof=probe_failed original_errno_or_exit=$dependency_status retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"
fi
if lower_devno="$(printf '%s\n' "$dependency_devno_proof" | awk '
    /^[[:space:]]*1[[:space:]]+dependencies[[:space:]]*:/ {
        value = $0
        sub(/^[^(]*\(/, "", value)
        sub(/\)[[:space:]]*$/, "", value)
        gsub(/[[:space:]]/, "", value)
        count = split(value, devno, ",")
        if (count == 2 &&
            devno[1] ~ /^(0|[1-9][0-9]*)$/ &&
            devno[2] ~ /^(0|[1-9][0-9]*)$/) {
            printf "%s:%s\n", devno[1], devno[2]
            found = 1
        }
    }
    END { exit found ? 0 : 1 }
')"; then
    :
else
    dependency_parse_status=$?
    refuse BLOCKED mapper_dependency unavailable "phase=dependency_devno_parse resource_kind=mapper expected_proof=one_canonical_dependency_devno observed_proof=malformed_or_missing original_errno_or_exit=$dependency_parse_status retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"
fi

cfgbase=/sys/kernel/config/nullb
[[ -d $cfgbase ]] ||
    refuse BLOCKED null_blk_configfs unavailable "pre-existing harness null_blk configfs is unavailable"
owned_config=""
lower_index=""
case "$lower_name" in
    nullb-swapz-*)
        lower_token="${lower_name#nullb-swapz-}"
        is_hex16 "$lower_token" ||
            refuse BLOCKED null_blk_owner unavailable "lower dependency name is not an owned null_blk identity"
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
            config_name="${config##*/}"
            config_token="${config_name#nullb-swapz-}"
            is_hex16 "$config_token" || continue
            [[ "$(cat "$config/index" 2>/dev/null)" == "$lower_index" ]] &&
                matches+=("$config")
        done
        [[ ${#matches[@]} == 1 ]] ||
            refuse BLOCKED null_blk_owner unavailable "dependency index has no unique token-shaped configfs owner"
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

# A mapper UUID binds only its benchmark mapping, not a later same-named
# configfs object. Snapshot the real configfs inode, creation attributes,
# null_blk index, kernel major and the actual lower node's st_rdev. This
# never grants creation ownership to an otherwise unclaimed token-shaped name.
ownership_refuse() {
    local phase="$1" resource_kind="$2" expected="$3" observed="$4"
    local status="${5:-unavailable}" retained_action="${6:-retain_unproven_resources}"
    refuse BLOCKED owned_resource_proof unavailable "phase=$phase resource_kind=$resource_kind expected_proof=$expected observed_proof=$observed original_errno_or_exit=$status retained_state_action=$retained_action safe_next_action=original_creator_revalidate_then_cleanup_or_read_only_reconcile"
}

read_canonical_uint_file() {
    local path="$1" value='' extra_byte=''
    [[ -f $path && ! -L $path ]] || return 1
    {
        IFS= read -r -n 21 value || return 1
        [[ ${#value} -le 20 ]] || return 1
        if IFS= read -r -n 1 extra_byte || [[ -n $extra_byte ]]; then
            return 1
        fi
    } < "$path"
    is_uint "$value" || return 1
    printf '%s\n' "$value"
}

read_owned_config_uint() {
    local result_variable="$1" phase="$2" attribute="$3"
    local value attribute_status
    if value="$(read_canonical_uint_file "$owned_config/$attribute")"; then
        printf -v "$result_variable" '%s' "$value"
    else
        attribute_status=$?
        ownership_refuse "$phase" null_blk "canonical_configfs_$attribute" \
            malformed_or_unreadable "$attribute_status"
    fi
}

read_owned_config_proof() {
    local result_variable="$1" phase="$2" expected_power="$3"
    local config_identity config_index memory_backed config_size blocksize queue_mode
    local power_identity power_state
    [[ -d $owned_config && ! -L $owned_config ]] || return 1
    config_identity="$(stat -Lc '%d:%i' "$owned_config" 2>/dev/null)" || return 1
    [[ $config_identity == *:* && $config_identity != *[!0-9:]* ]] || return 1
    for attribute in index memory_backed size blocksize queue_mode power; do
        [[ -f $owned_config/$attribute && ! -L $owned_config/$attribute ]] || return 1
    done
    read_owned_config_uint config_index "$phase" index
    read_owned_config_uint memory_backed "$phase" memory_backed
    read_owned_config_uint config_size "$phase" size
    read_owned_config_uint blocksize "$phase" blocksize
    read_owned_config_uint queue_mode "$phase" queue_mode
    read_owned_config_uint power_state "$phase" power
    power_identity="$(stat -Lc '%d:%i' "$owned_config/power" 2>/dev/null)" || return 1
    [[ $power_identity == *:* && $power_identity != *[!0-9:]* ]] || return 1
    [[ $memory_backed == 1 && $config_size != 0 && $blocksize == 4096 &&
       $queue_mode == 2 ]] || return 1
    [[ $power_state == "$expected_power" ]] ||
        ownership_refuse "$phase" null_blk expected_power_state changed_or_malformed
    [[ -z $lower_index || $lower_index == "$config_index" ]] || return 1
    [[ "$(stat -Lc '%d:%i' "$owned_config" 2>/dev/null)" == "$config_identity" ]] ||
        return 1
    printf -v "$result_variable" '%s|%s|%s|%s|%s|%s|%s' \
        "$config_identity" "$config_index" "$memory_backed" "$config_size" \
        "$blocksize" "$queue_mode" "$power_identity"
}

read_owned_lower_proof() {
    local result_variable="$1" phase="$2"
    local config_index current_power disk sysfs_devno node_devno block_major system_major
    local partition_marker disk_status devno_status major_status
    config_index="${owned_config_proof#*|}"
    config_index="${config_index%%|*}"
    read_owned_config_uint current_power "$phase" power
    [[ $current_power == 1 ]] ||
        ownership_refuse "$phase" null_blk expected_power_state changed_or_malformed
    # The index name and configfs name are alternatives, not two devices.
    if disk="$(swapz_resolve_owned_disk "${owned_config##*/}" "$config_index" /sys/block)"; then
        :
    else
        disk_status=$?
        ownership_refuse "$phase" null_blk \
            unique_sysfs_disk_alias_and_canonical_devno ambiguous_or_malformed \
            "$disk_status"
    fi
    [[ -b $lower ]] || return 1
    if sysfs_devno="$(swapz_read_canonical_devno "/sys/block/$disk/dev")"; then
        :
    else
        devno_status=$?
        ownership_refuse "$phase" null_blk stable_canonical_sysfs_devno \
            changed_or_malformed "$devno_status"
    fi
    [[ $sysfs_devno == "$lower_devno" ]] || return 1
    for partition_marker in /sys/block/$disk/*/partition; do
        [[ ! -e $partition_marker ]] || return 1
    done
    node_devno="$(stat -Lc '%Hr:%Lr' "$lower" 2>/dev/null)" || return 1
    [[ $node_devno == "$sysfs_devno" ]] || return 1
    block_major="${sysfs_devno%%:*}"
    if system_major="$(awk '
        $0 == "Block devices:" { section = 1; next }
        section && $2 == "nullb" {
            if (NF != 2 || $1 !~ /^(0|[1-9][0-9]*)$/ ||
                length($1) > 10 || ++matches != 1)
                invalid = 1
            else
                major = $1
        }
        END {
            if (invalid || matches != 1) exit 2
            print major
        }
    ' /proc/devices 2>/dev/null)"; then
        :
    else
        major_status=$?
        ownership_refuse "$phase" null_blk one_canonical_nullb_major_record \
            malformed_or_unreadable "$major_status"
    fi
    [[ -n $system_major && $system_major == "$block_major" ]] || return 1
    [[ $sysfs_devno == "$system_major:$config_index" ]] || return 1
    [[ -e /sys/dev/block/$sysfs_devno &&
       "$(readlink -f "/sys/dev/block/$sysfs_devno" 2>/dev/null)" == \
       "$(readlink -f "/sys/block/$disk" 2>/dev/null)" ]] || return 1
    printf -v "$result_variable" '%s|%s|%s' "$disk" "$sysfs_devno" "$node_devno"
}

assert_owned_config_proof() {
    local phase="$1" expected_power="$2" current_proof
    local current_config_fd_identity current_power_fd_identity
    if ! read_owned_config_proof current_proof "$phase" "$expected_power"; then
        ownership_refuse "$phase" null_blk config_inode_index_attributes missing_or_changed
    fi
    [[ $current_proof == "$owned_config_proof" ]] ||
        ownership_refuse "$phase" null_blk original_inode_index_attributes substituted
    current_config_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_config_fd" 2>/dev/null)" ||
        ownership_refuse "$phase" null_blk pinned_config_inode unreadable
    current_power_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_power_fd" 2>/dev/null)" ||
        ownership_refuse "$phase" null_blk pinned_power_inode unreadable
    [[ $current_config_fd_identity == "$owned_config_identity" ]] ||
        ownership_refuse "$phase" null_blk pinned_config_inode substituted
    [[ $current_power_fd_identity == "$owned_power_identity" ]] ||
        ownership_refuse "$phase" null_blk pinned_power_inode substituted
    if [[ $expected_power == 1 ]]; then
        if ! read_owned_lower_proof current_proof "$phase"; then
            ownership_refuse "$phase" null_blk sysfs_major_devno_node_rdev missing_or_changed
        fi
        [[ $current_proof == "$owned_lower_proof" ]] ||
            ownership_refuse "$phase" null_blk original_sysfs_major_devno_node_rdev substituted
    fi
}

assert_owned_mapper_proof() {
    local current_uuid current_dependency_names current_dependency_devnos
    local current_devno current_opens
    current_uuid="$(dmsetup info -c --noheadings -o uuid "$owned_map" 2>/dev/null |
        tr -d '[:space:]')" ||
        ownership_refuse mapper_remove mapper original_uuid unreadable
    current_dependency_names="$(dmsetup deps -o devname "$owned_map" 2>/dev/null)" ||
        ownership_refuse mapper_remove mapper original_dependency_name unreadable
    current_dependency_devnos="$(dmsetup deps -o devno "$owned_map" 2>/dev/null)" ||
        ownership_refuse mapper_remove mapper original_dependency_devno unreadable
    current_devno="$(stat -Lc '%Hr:%Lr' "$mapper" 2>/dev/null)" ||
        ownership_refuse mapper_remove mapper original_devno unreadable
    current_opens="$(read_opens)" ||
        ownership_refuse mapper_remove mapper zero_opens unreadable
    [[ $current_uuid == "$uuid" &&
       $current_dependency_names == "$dependency_name_proof" &&
       $current_dependency_devnos == "$dependency_devno_proof" &&
       $current_devno == "$listed_mapper_devno" && $current_opens == 0 ]] ||
        ownership_refuse mapper_remove mapper uuid_dependency_name_devno_zero_opens substituted_or_busy
}

if ! { exec {owned_config_fd}< "$owned_config"; } 2>/dev/null; then
    ownership_refuse acquire null_blk pinned_config_inode open_failed
fi
owned_config_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_config_fd" 2>/dev/null)" ||
    ownership_refuse acquire null_blk pinned_config_inode fd_stat_failed
if ! read_owned_config_proof owned_config_proof acquire 1; then
    ownership_refuse acquire null_blk config_inode_index_attributes missing_or_incomplete
fi
owned_config_identity="${owned_config_proof%%|*}"
owned_power_identity="${owned_config_proof##*|}"
[[ $owned_config_fd_identity == "$owned_config_identity" ]] ||
    ownership_refuse acquire null_blk pinned_config_inode substituted
# Resolve the power attribute through the already-pinned configfs directory.
# A public-path replacement between the directory proof and this open cannot
# redirect the descriptor to a same-named foreign configfs object.
if ! { exec {owned_power_fd}<> "/proc/$$/fd/$owned_config_fd/power"; } 2>/dev/null; then
    ownership_refuse acquire null_blk pinned_power_inode open_failed
fi
owned_power_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_power_fd" 2>/dev/null)" ||
    ownership_refuse acquire null_blk pinned_power_inode fd_stat_failed
[[ $owned_power_fd_identity == "$owned_power_identity" ]] ||
    ownership_refuse acquire null_blk pinned_power_inode substituted
if ! read_owned_lower_proof owned_lower_proof acquire; then
    ownership_refuse acquire null_blk dependency_sysfs_major_index_devno_node_rdev missing_or_incomplete
fi

assert_not_mounted "$lower" mounted_owned_lower
assert_not_active_swap "$lower"

# Resolve the canonical mapper node before accepting the lower. A matching
# devno alone is insufficient because a removed null_blk index can be reused;
# the current sysfs lower must name this exact mapper as its sole holder.
mapper_node="$(readlink -f "$mapper" 2>/dev/null || true)"
[[ -n $mapper_node && -b $mapper_node ]] ||
    refuse BLOCKED mapper_device_identity unavailable "canonical mapper block node is missing or unreadable; no holder signal"
if mapper_dev="$(stat -Lc '%Hr:%Lr' "$mapper" 2>/dev/null)"; then
    :
else
    mapper_stat_status=$?
    refuse BLOCKED mapper_device_identity unavailable "stat_status=$mapper_stat_status; original_errno_or_exit=$mapper_stat_status; cannot stat mapper; no holder signal"
fi
if canonical_dev="$(stat -Lc '%Hr:%Lr' "$mapper_node" 2>/dev/null)"; then
    :
else
    canonical_stat_status=$?
    refuse BLOCKED mapper_device_identity unavailable "stat_status=$canonical_stat_status; original_errno_or_exit=$canonical_stat_status; cannot stat canonical mapper; no holder signal"
fi
[[ -n $mapper_dev && $mapper_dev == "$canonical_dev" ]] ||
    refuse BLOCKED mapper_device_identity unavailable "canonical device identity changed; no holder signal"
[[ $mapper_dev == "$listed_mapper_devno" ]] ||
    refuse BLOCKED mapper_device_identity unavailable "expected dmsetup inventory device identity to match canonical mapper node; observed mismatch; no holder signal; inspect device-mapper inventory and udev state without cleanup"
mapper_kernel_name="${mapper_node##*/}"
case "$mapper_kernel_name" in
    dm-*) mapper_kernel_index="${mapper_kernel_name#dm-}" ;;
    *) ownership_refuse acquire mapper canonical_dm_kernel_name malformed ;;
esac
is_uint "$mapper_kernel_index" ||
    ownership_refuse acquire mapper canonical_dm_kernel_name malformed
owned_disk="${owned_lower_proof%%|*}"
assert_mapper_is_only_lower_holder() {
    local phase="$1" holder_list holder_target mapper_target
    [[ -d /sys/block/$owned_disk/holders ]] ||
        ownership_refuse "$phase" null_blk mapper_holder missing
    holder_list="$(ls -A "/sys/block/$owned_disk/holders" 2>/dev/null)" ||
        ownership_refuse "$phase" null_blk mapper_holder unreadable
    [[ $holder_list == "$mapper_kernel_name" &&
       -L /sys/block/$owned_disk/holders/$mapper_kernel_name ]] ||
        ownership_refuse "$phase" null_blk exact_single_mapper_holder missing_or_foreign
    holder_target="$(readlink -f "/sys/block/$owned_disk/holders/$mapper_kernel_name" 2>/dev/null)" ||
        ownership_refuse "$phase" null_blk mapper_holder_target unreadable
    mapper_target="$(readlink -f "/sys/block/$mapper_kernel_name" 2>/dev/null)" ||
        ownership_refuse "$phase" mapper mapper_sysfs_target unreadable
    [[ -n $holder_target && $holder_target == "$mapper_target" ]] ||
        ownership_refuse "$phase" null_blk exact_mapper_holder_target substituted
}
assert_mapper_is_only_lower_holder acquire

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
# A matching block node does not establish ownership of holder processes.
# Never signal an inferred PID; a nonzero open count must close naturally.

is_uint "$opens" && [[ $opens == 0 ]] ||
    refuse BLOCKED mapper_open_count unavailable "owned mapping remains open after bounded cleanup; reboot required before make test"

# Recheck host-use gates, then revalidate both original objects and every
# recorded mapper dependency immediately adjacent to the nonforce mutation.
# The UUID operand avoids a public mapper-name reuse after this proof.
assert_not_mounted "$mapper" mounted_owned_mapper
assert_not_active_swap "$mapper"
assert_not_mounted "$lower" mounted_owned_lower
assert_not_active_swap "$lower"
assert_owned_config_proof mapper_remove 1
assert_owned_mapper_proof
assert_mapper_is_only_lower_holder mapper_remove
# Matching live identities, a UUID and a sole holder still cannot prove who
# created this pre-existing object. This new preflight process has no exclusive
# creator claim to inherit: stop before mapper removal, power-off or rmdir.
# The original session must reconcile its retained resources under its own
# creation authority; preflight never adopts or deletes them.
ownership_refuse mapper_remove null_blk creation_authority live_identity_only \
    unavailable retain_unclaimed_null_blk
if timeout --signal=TERM --kill-after=2s 10s dmsetup remove --retry "$uuid"; then
    :
else
    mapper_remove_status=$?
    refuse BLOCKED owned_mapper_removal unavailable "phase=mapper_remove resource_kind=mapper expected_proof=original_uuid_devno_dependencies observed_proof=removal_failed original_errno_or_exit=$mapper_remove_status retained_state_action=retain_remaining_resources"
fi
[[ ! -e $mapper ]] ||
    refuse BLOCKED owned_mapper_removal unavailable "stale harness dm_swapz mapping still exists after ordinary removal"
refcount="$(read_refcount)" || exit 1
[[ $refcount == 0 ]] ||
    refuse BLOCKED module_refcount unavailable "dm_swapz still has references after stale harness mapping removal"
# A different directory can appear at the original path after mapper removal.
# Missing or replaced configfs state is not a successful cleanup.
assert_owned_config_proof power_off 1
[[ -d /sys/block/${owned_lower_proof%%|*}/holders ]] ||
    ownership_refuse power_off null_blk holder_inventory missing
holder_list="$(ls -A "/sys/block/${owned_lower_proof%%|*}/holders" 2>/dev/null)" ||
    ownership_refuse power_off null_blk holder_inventory unreadable
[[ -z $holder_list ]] ||
    ownership_refuse power_off null_blk no_holders busy
assert_owned_config_proof power_off 1
# The power attribute was opened and pinned at acquisition. Re-stat that same
# descriptor immediately before the write; no pathname lookup can retarget it.
current_power_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_power_fd" 2>/dev/null)" ||
    ownership_refuse power_off null_blk pinned_power_inode fd_stat_failed
[[ $current_power_fd_identity == "$owned_power_identity" ]] ||
    ownership_refuse power_off null_blk pinned_power_inode substituted
printf '0\n' >&"$owned_power_fd" ||
    ownership_refuse power_off null_blk pinned_power_inode write_failed "$?" retain_remaining_resources
# Power-off removes sysfs block telemetry. Keep checking the captured configfs
# identity and pinned descriptors through the final pathname-bound rmdir.
assert_owned_config_proof config_remove 0
current_config_fd_identity="$(stat -Lc '%d:%i' "/proc/$$/fd/$owned_config_fd" 2>/dev/null)" ||
    ownership_refuse config_remove null_blk pinned_config_inode fd_stat_failed
[[ $current_config_fd_identity == "$owned_config_identity" ]] ||
    ownership_refuse config_remove null_blk pinned_config_inode substituted
rmdir -- "$owned_config" 2>/dev/null ||
    ownership_refuse config_remove null_blk original_config_inode rmdir_failed "$?" retain_remaining_resources
exec {owned_power_fd}>&-
exec {owned_config_fd}>&-
# The remaining module still lacks independent creation provenance.
remove_idle_module
