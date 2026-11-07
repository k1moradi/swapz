#!/usr/bin/env bash
# Private native rehearsal of the production primary lifecycle on an owned
# memory-backed null_blk partition. This never authorizes or opens physical
# media and never replaces owner make-test qualification.
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "$0")/../.." && pwd -P)"
cd "$ROOT"
source tests/tools/nullblk-identity.sh
source tests/tools/swap-inventory.sh

fail() {
	printf 'FAIL_PRIMARY_NULLBLK_LIFECYCLE: %s\n' "$*" >&2
	exit 1
}
# A failed owned operation is FAIL, not a preclaim admission BLOCKED.
# Command exit codes are not errno values; do not invent a Linux errno.
owned_setup_failed() {
	local failure_phase="$1"
	local original_exit="${2:-}"

	# Shell command status is not a Linux errno. Preserve the observed exit
	# instead of inventing errno, even if cleanup subsequently also fails.
	if [[ ! "$original_exit" =~ ^[1-9][0-9]{0,2}$ ]] ||
	   (( original_exit > 255 )); then
		fail "phase=$failure_phase original_errno=unavailable original_exit=unavailable expected=owned-setup-operation-success observed=invalid-command-status ownership=claimed next=inspect-private-evidence"
	fi
	fail "phase=$failure_phase original_errno=unavailable original_exit=$original_exit expected=owned-setup-operation-success observed=command-failed ownership=claimed next=inspect-private-evidence"
}
blocked() {
	printf 'BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\n' "$*" >&2
	exit 2
}
note() {
	printf '%s\n' "$*"
}


# Keep the first refusal actionable without echoing free-form command output:
# only the canonical errno/phase record and its optional authenticated
# mount-inventory EAGAIN step may escape this private harness.
verify_prepare_failure_diagnostic() {
	local output="$1"
	local line phase number description expected_error
	local diagnostic_count=0
	local wrapper_count=0
	local mount_diagnostic_count=0
	local diagnostic=""
	local wrapper=""
	local mount_diagnostic=""
	local mount_reason=""

	while IFS= read -r line; do
		[[ -n "$line" ]] ||
			fail "prepare refusal emitted an unexpected blank diagnostic line"
		if [[ "$line" == PRIMARY_PREPARE=FAILED* ]]; then
			diagnostic_count=$((diagnostic_count + 1))
			if [[ ! "$line" =~ ^PRIMARY_PREPARE=FAILED[[:space:]]phase=([a-z][a-z0-9-]*)[[:space:]]errno=([1-9][0-9]{0,3})[[:space:]]error=(.*)$ ]]; then
				fail "prepare refusal has a malformed phase/errno diagnostic"
			fi
			phase="${BASH_REMATCH[1]}"
			number="${BASH_REMATCH[2]}"
			description="${BASH_REMATCH[3]}"
			expected_error="$(LC_ALL=C python3 -c 'import errno, os, sys; n = int(sys.argv[1]); sys.exit(2) if n not in errno.errorcode else None; print(os.strerror(n))' "$number")" ||
				fail "prepare refusal has an unknown errno"
			case "$phase" in
			global-mutation-lock|package-transaction-preflight)
				[[ "$description" == "$expected_error" ]] ||
					fail "prepare refusal exposed a noncanonical diagnostic"
				;;
			identity-admission|configured-target-identity|recovery-directory-open|\
			partition-lock-and-prior-claim|prior-claim-reconciliation|\
			recovery-storage-inspection|recovery-directory-safety|\
			recovery-filesystem-persistence|recovery-target-device-separation|\
			recovery-physical-parent-identity|prior-active-marker|\
			qualification-report-read|qualification-source-identity|\
			qualified-artifact-hash-readback|qualified-artifact-identity|\
			target-header-inspection|target-geometry-identity|\
			original-header-rollback-proof|original-header-digest|\
			raw-target-swap-inventory|target-physical-parent-identity|\
			target-recovery-parent-separation|cross-namespace-mount-inventory|\
			target-mounted-in-visible-namespace|root-device-parent-identity|\
			shared-root-parent-authorization-record|\
			repeated-raw-target-swap-inventory|\
			repeated-target-physical-parent-identity|\
			repeated-target-recovery-parent-separation|\
			repeated-cross-namespace-mount-inventory|\
			repeated-target-mounted-in-visible-namespace|\
			repeated-root-device-parent-identity|repeated-root-parent-identity|\
			repeated-shared-root-parent-authorization|\
			final-root-parent-identity-revalidation|\
			final-shared-root-parent-authorization|physical-parent-swap-inventory|\
			module-mapper-inventory|unexpected-module-or-mapper-present|\
			final-raw-target-swap-inventory|final-preclaim-identity-revalidation|\
			final-physical-parent-swap-inventory|run-id-and-header-construction|\
			partition-owner-claim)
				[[ "$description" == "$expected_error claim=none" ]] ||
					fail "preclaim refusal exposed private state or wrong disposition"
				;;
			global-mutation-lock-close|original-header-backup-write|manifest-write|\
			original-header-backup-readback|manifest-readback|\
			partition-lock-close|recovery-directory-close)
				[[ "$description" == "$expected_error claim=retained target_unchanged=true" ]] ||
					fail "postclaim refusal lacks retained ownership disposition"
				;;
			*)
				fail "prepare refusal has an unknown phase"
				;;
			esac
			diagnostic="$line"
			continue
		fi
		if [[ "$line" == "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE"* ]]; then
			mount_diagnostic_count=$((mount_diagnostic_count + 1))
			# Source-controlled fields only: no PID, path, namespace or device.
			if [[ ! "$line" =~ ^SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE[[:space:]]step=(namespace-fd|root-object|init-root|root-walk|mount-list|listed-mount|root-revalidation)[[:space:]]errno=11([[:space:]]reason=(init-root-statx-race|process-root-not-directory|init-root-not-directory|root-inode-mismatch|process-root-device-mismatch|init-root-device-mismatch))?$ ]]; then
				fail "prepare refusal has a malformed mount-inventory diagnostic"
			fi
			mount_reason="${BASH_REMATCH[3]:-}"
			if [[ -n "$mount_reason" && "${BASH_REMATCH[1]}" != init-root ]]; then
				fail "prepare refusal mount-inventory reason does not match step"
			fi
			mount_diagnostic="$line"
			continue
		fi
		if [[ "$line" == "BLOCKED: primary-swap preparation failed: "* ]]; then
			wrapper_count=$((wrapper_count + 1))
			wrapper="$line"
			continue
		fi
		fail "prepare refusal emitted unexpected sideband diagnostics"
	done <<< "$output"
	(( diagnostic_count == 1 )) ||
		fail "prepare refusal did not emit exactly one phase/errno diagnostic"
	(( wrapper_count == 1 )) ||
		fail "prepare refusal did not emit exactly one coordinator wrapper"
	[[ "$wrapper" == "BLOCKED: primary-swap preparation failed: $expected_error" ]] ||
		fail "prepare refusal wrapper disagrees with errno"
	(( mount_diagnostic_count <= 1 )) ||
		fail "prepare refusal emitted duplicate mount-inventory diagnostics"
	if (( mount_diagnostic_count == 1 )); then
		# A scan marker belongs only to the original fail-closed EAGAIN gate.
		[[ "$number" == 11 && ( "$phase" == cross-namespace-mount-inventory ||
			"$phase" == repeated-cross-namespace-mount-inventory ) ]] ||
			fail "prepare refusal mount-inventory diagnostic disagrees with phase or errno"
		printf '%s\n' "$mount_diagnostic" >&2
	fi
	printf '%s\n' "$diagnostic" >&2
}

block0_sha256() {
	local device_path="$1"
	local digest

	digest="$(dd if="$device_path" bs=4096 count=1 status=none 2>/dev/null | \
		sha256sum | awk '{print $1}')" || return 1
	[[ "$digest" =~ ^[0-9a-f]{64}$ ]] || return 1
	printf '%s\n' "$digest"
}

block_node_devno() {
	local device_path="$1"
	local device_hex major_hex minor_hex device_number

	[[ -b "$device_path" ]] || return 1
	device_hex="$(stat -Lc '%t:%T' "$device_path")" || return 1
	IFS=: read -r major_hex minor_hex <<< "$device_hex"
	[[ "$major_hex" =~ ^[0-9a-fA-F]+$ &&
	   "$minor_hex" =~ ^[0-9a-fA-F]+$ ]] || return 1
	printf -v device_number '%d:%d' "0x$major_hex" "0x$minor_hex" ||
		return 1
	[[ "$device_number" =~ ^[0-9]+:[0-9]+$ ]] || return 1
	printf '%s\n' "$device_number"
}

# A failed dmsetup query is not proof of mapper absence. Check the independent
# sysfs mapper inventory before mutating or destroying private RAM resources.
mapper_absence_proven() {
	local mapper_sysfs observed_name

	if dmsetup info "$DMNAME" >/dev/null 2>&1; then
		return 1
	fi
	[[ -d /sys/class/block && -r /sys/class/block ]] || return 1
	for mapper_sysfs in /sys/class/block/dm-*; do
		[[ -e "$mapper_sysfs" || -L "$mapper_sysfs" ]] || continue
		[[ -r "$mapper_sysfs/dm/name" ]] || return 1
		observed_name="$(cat "$mapper_sysfs/dm/name")" || return 1
		[[ "$observed_name" != "$DMNAME" ]] || return 1
	done
}


# This pathname is not an ownership token. Pin the created config directory,
# compare its stable inode with the captured identity, and verify each
# kernel-defined attribute through that descriptor before teardown. Configfs
# synthesizes a new pseudo-file inode on attribute lookup, so an attribute's
# inode is not a persistent identity across opens.
# Configfs cannot provide an atomic compare-and-rmdir operation or an
# independent creation generation; uncertainty must retain the resource.
owned_nullblk_configfs_proof() {
	local expected_power="$1" power_off="$2" python_status=0

	[[ "$CONFIGNAME" =~ ^nullb-swapz-[a-f0-9]{16}$ &&
	   "$CONFIG" == "$CONFIGFS/$CONFIGNAME" &&
	   "$INDEX" =~ ^(0|[1-9][0-9]*)$ &&
	   "$NULLBLK_SIZE_MIB" =~ ^[1-9][0-9]*$ &&
	   "$CONFIG_IDENTITY" =~ ^[0-9]+:[0-9]+:[0-9]+$ &&
	   "$expected_power" =~ ^[01]$ && "$power_off" =~ ^[01]$ &&
	   ( "$power_off" == 0 || "$expected_power" == 1 ) ]] || return 1

	# Keep the failure handler on the opener; otherwise it becomes Python input.
	python3 - "$CONFIGFS" "$CONFIGNAME" "$CONFIG_IDENTITY" \
		"$INDEX" "$NULLBLK_SIZE_MIB" "$expected_power" "$power_off" \
		2>/dev/null <<'PY' || python_status=$?
import os
import stat
import sys


class IdentityMismatch(Exception):
    pass


class PowerWriteFailure(Exception):
    pass


(configfs_path, config_name, expected_identity, index, size_mib,
 expected_power, power_off) = sys.argv[1:8]
directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
read_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
write_flags = os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
configfs_fd = -1
config_fd = -1
power_fd = -1
write_started = False
result = 2


def identity(metadata):
    return f"{metadata.st_dev}:{metadata.st_ino}:{metadata.st_uid}"


def verify_config_name(metadata):
    if (not stat.S_ISDIR(metadata.st_mode) or
            identity(metadata) != expected_identity):
        raise IdentityMismatch


def verify_named_config():
    named = os.stat(
        config_name, dir_fd=configfs_fd, follow_symlinks=False)
    verify_config_name(named)


def open_attribute(attribute, flags):
    descriptor = os.open(attribute, flags, dir_fd=config_fd)
    metadata = os.fstat(descriptor)
    if (not stat.S_ISREG(metadata.st_mode) or
            metadata.st_dev != config_metadata.st_dev or
            metadata.st_uid != config_metadata.st_uid):
        os.close(descriptor)
        raise IdentityMismatch
    return descriptor


def verify_attribute(attribute, expected):
    descriptor = open_attribute(attribute, read_flags)
    try:
        if os.read(descriptor, 65) != expected:
            raise IdentityMismatch
    finally:
        os.close(descriptor)


try:
    configfs_fd = os.open(configfs_path, directory_flags)
    config_fd = os.open(config_name, directory_flags, dir_fd=configfs_fd)
    config_metadata = os.fstat(config_fd)
    verify_config_name(config_metadata)
    verify_named_config()
    verify_attribute("index", index.encode("ascii") + b"\n")
    verify_attribute("memory_backed", b"1\n")
    verify_attribute("size", size_mib.encode("ascii") + b"\n")
    verify_attribute("blocksize", b"4096\n")
    verify_attribute("power", expected_power.encode("ascii") + b"\n")

    if power_off == "1":
        verify_named_config()
        power_fd = open_attribute("power", write_flags)
        verify_named_config()
        write_started = True
        if os.write(power_fd, b"0\n") != 2:
            raise PowerWriteFailure
        descriptor = power_fd
        power_fd = -1
        os.close(descriptor)
        verify_attribute("power", b"0\n")
        verify_named_config()
    result = 0
except IdentityMismatch:
    result = 2
except PowerWriteFailure:
    result = 3
except OSError:
    result = 3 if write_started else 2
finally:
    for descriptor_name in ("power_fd", "config_fd", "configfs_fd"):
        descriptor = locals()[descriptor_name]
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                if result == 0:
                    result = 3 if write_started else 2
raise SystemExit(result)
PY
	case "$python_status" in
	0) return 0 ;;
	2) return 1 ;;
	*) return 2 ;;
	esac
}

owned_nullblk_config_identity_unchanged() {
	local expected_power="${1:-1}"
	owned_nullblk_configfs_proof "$expected_power" 0
}

owned_nullblk_power_off_pinned() {
	owned_nullblk_configfs_proof 1 1
}

owned_nullblk_live_identity_unchanged() {
	local observed_disk resolved_partition resolved_dev_block

	owned_nullblk_config_identity_unchanged 1 || return 1
	[[ -n "$DISK" && -n "$PART_NAME" &&
	   "$DEVNO" =~ ^[0-9]+:[0-9]+$ &&
	   "$PART_DEVNO" =~ ^[0-9]+:[0-9]+$ &&
	   "$DEVNO" == "$NULL_MAJOR:$INDEX" &&
	   "$LOWER" == "/dev/$DISK" &&
	   "$PARTITION" == "/dev/$PART_NAME" &&
	   "$PART_SYSFS" == "/sys/block/$DISK/$PART_NAME" ]] || return 1
	observed_disk="$(swapz_resolve_owned_disk "$CONFIGNAME" "$INDEX" /sys/block 2>/dev/null)" ||
		return 1
	[[ "$observed_disk" == "$DISK" &&
	   -f "/sys/block/$DISK/dev" && ! -L "/sys/block/$DISK/dev" &&
	   "$(cat "/sys/block/$DISK/dev" 2>/dev/null)" == "$DEVNO" &&
	   "$(block_node_devno "$LOWER" 2>/dev/null)" == "$LOWER_NODE_DEVNO" &&
	   "$LOWER_NODE_DEVNO" == "$DEVNO" &&
	   "$(blockdev --getsize64 "$LOWER" 2>/dev/null)" == $((NULLBLK_SIZE_MIB * 1024 * 1024)) &&
	   -f "$PART_SYSFS/dev" && ! -L "$PART_SYSFS/dev" &&
	   "$(cat "$PART_SYSFS/dev" 2>/dev/null)" == "$PART_DEVNO" &&
	   "$(block_node_devno "$PARTITION" 2>/dev/null)" == "$PARTITION_NODE_DEVNO" &&
	   "$PARTITION_NODE_DEVNO" == "$PART_DEVNO" ]] || return 1
	resolved_partition="$(readlink -f "$PART_SYSFS" 2>/dev/null)" ||
		return 1
	resolved_dev_block="$(readlink -f "/sys/dev/block/$PART_DEVNO" 2>/dev/null)" ||
		return 1
	[[ -n "$resolved_partition" && "$resolved_dev_block" == "$resolved_partition" ]]
}

# A failed dmsetup lookup is not mapper-absence evidence. If a mapper exists,
# check the run UUID and exact durable table before allowing any recovery.
owned_nullblk_mapper_identity_unchanged() {
	local observed_uuid observed_table expected_table

	if ! dmsetup info "$DMNAME" >/dev/null 2>&1; then
		mapper_absence_proven
		return $?
	fi
	[[ "$RUN_ID" =~ ^[0-9a-f]{32}$ && "$PART_DEVNO" =~ ^[0-9]+:[0-9]+$ ]] ||
		return 1
	observed_uuid="$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
		tr -d '[:space:]')" || return 1
	[[ "$observed_uuid" == "SWAPZ-PRIMARY-$RUN_ID" ]] || return 1
	observed_table="$(dmsetup table "$DMNAME" 2>/dev/null)" ||
		observed_table="$(dmsetup table --inactive "$DMNAME" 2>/dev/null)" ||
		return 1
	expected_table="$(sed -n 's/^dm_table=//p' "$RECOVERY_BASE/primary-manifest-$RUN_ID.txt" 2>/dev/null)" ||
		return 1
	[[ -n "$expected_table" && "$observed_table" == "$expected_table" &&
	   "$observed_table" == "0 "*" swapz $PART_DEVNO "* ]]
}

# Power-off removes sysfs block identities. Recheck those still observable
# and the pinned configfs identity before removing its directory.
owned_nullblk_post_power_identity_unchanged() {
	owned_nullblk_config_identity_unchanged 0 || return 1
	# On successful power-off both sysfs nodes may disappear. A node that
	# remains observable must still match the captured device identity.
	if [[ -e "/sys/block/$DISK/dev" || -L "/sys/block/$DISK/dev" ]]; then
		[[ -f "/sys/block/$DISK/dev" && ! -L "/sys/block/$DISK/dev" &&
		   "$(cat "/sys/block/$DISK/dev" 2>/dev/null)" == "$DEVNO" &&
		   "$(block_node_devno "$LOWER" 2>/dev/null)" == "$LOWER_NODE_DEVNO" ]] ||
			return 1
	fi
	if [[ -e "$PART_SYSFS/dev" || -L "$PART_SYSFS/dev" ]]; then
		[[ -f "$PART_SYSFS/dev" && ! -L "$PART_SYSFS/dev" &&
		   "$(cat "$PART_SYSFS/dev" 2>/dev/null)" == "$PART_DEVNO" &&
		   "$(block_node_devno "$PARTITION" 2>/dev/null)" == "$PARTITION_NODE_DEVNO" ]] ||
			return 1
	fi
}

if [[ $# -ne 2 || $1 != --validated-source ]]; then
	blocked "expected --validated-source <40-hex-sha>"
fi
SOURCE_HEAD="$2"
[[ "$SOURCE_HEAD" =~ ^[0-9a-f]{40}$ ]] ||
	blocked "validated source is malformed"
(( EUID == 0 )) || blocked "owned-nullblk lifecycle rehearsal requires root"
HOST_ARCH="$(uname -m)"
[[ "$(uname -s)" == Linux && ( "$HOST_ARCH" == x86_64 || "$HOST_ARCH" == aarch64 ) ]] ||
	blocked "owned RAM primary lifecycle requires Linux x86_64 or aarch64"
# The installed production binary and physical-media admission stay x86_64-only.
export HOST_ARCH

for command in cc dmsetup modprobe mountpoint mount blockdev sfdisk udevadm \
	blkid mkswap sha256sum python3 timeout stat findmnt awk sed grep install od \
	tr cut basename readlink rm rmdir ls sleep cat chmod dd; do
	command -v "$command" >/dev/null 2>&1 ||
		blocked "required command is unavailable: $command"
done

# Branch/source/cleanliness are proved by the unprivileged loaded-test parent
# before sudo and rechecked there after this child returns. The privileged
# helper consumes only the explicit validated SHA and generated build provenance.
[[ -r build/source-build-info.h &&
   -r build/kernel/experimental/dm-swapz.ko &&
   -x build/tests/device-roundtrip ]] ||
	blocked "exact-source module/oracle/build provenance artifacts are unavailable"
grep -Fxq "#define SWAPZ_BUILD_SOURCE_SHA \"$SOURCE_HEAD\"" \
	build/source-build-info.h ||
	blocked "generated build provenance does not match validated source"
grep -Fxq '#define SWAPZ_BUILD_SOURCE_CLEAN 1' build/source-build-info.h ||
	blocked "generated build provenance is not clean"

TOKEN="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
[[ "$TOKEN" =~ ^[a-f0-9]{16}$ ]] ||
	fail "cannot generate lifecycle ownership token"
TEST_BASE="/var/lib/swapz-primary-owned-nullblk-test-$TOKEN"
CONFIG_BASE="$TEST_BASE/config"
RECOVERY_BASE="$TEST_BASE/recovery"
MUTATION_LOCK_BASE="$TEST_BASE/mutation-lock"
PREFIX="$TEST_BASE/prefix"
CONTROL="$PREFIX/sbin/swapzctl"
REPORT="$RECOVERY_BASE/qualification.json"
EVIDENCE_BASE="$TEST_BASE/evidence"
FAULT_FIXTURE="tests/tools/primary-lifecycle-fault-shim.c"
CONFIGFS=/sys/kernel/config/nullb
UDEV_RULES_DIR=/run/udev/rules.d
DMNAME=swapz-primary
NULLBLK_SIZE_MIB=256
OWN_NULL=0
TEST_BASE_CREATED=0
UDEV_RULE_CREATED=0
UDEV_RULES_DIR_CREATED=0
QUARANTINE=0
RETAIN_PRIVATE_EVIDENCE=0
CONFIG=
UDEV_RULE=
UDEV_RULE_CONTENT=
CONFIGNAME=
INDEX=
DISK=
DEVNO=
NULL_MAJOR=
LOWER=
LOWER_NODE_DEVNO=
PART_SYSFS=
PART_NAME=
PARTITION=
PARTUUID=
PART_DEVNO=
PARTITION_NODE_DEVNO=
CONFIG_IDENTITY=
BY_PARTUUID=
RUN_ID=

[[ ! -e "$TEST_BASE" && ! -L "$TEST_BASE" ]] ||
	blocked "fresh owned-nullblk lifecycle evidence path already exists"
[[ ! -d /sys/module/dm_swapz ]] ||
	blocked "dm_swapz is already loaded before lifecycle rehearsal"
mapper_absence_proven ||
	blocked "swapz-primary exists or independent mapper absence is unproven"
SWAPS_ID_BEFORE="$(swapz_swap_inventory_identity /proc/swaps)" ||
	blocked "cannot snapshot host swap identity"

state_stage() {
	local state="$RECOVERY_BASE/primary-state.json"
	[[ -f "$state" && ! -L "$state" ]] || return 0
	python3 - "$state" <<'PY'
import json
import sys
try:
    value = json.load(open(sys.argv[1], "r", encoding="utf-8")).get("stage", "")
except (OSError, ValueError, TypeError):
    value = ""
if isinstance(value, str):
    print(value)
PY
}

assert_lifecycle_state() {
	local run_id="$1"
	local expected_stage="$2"
	local expected_previous="$3"
	python3 - "$RECOVERY_BASE/primary-state.json" \
		"$run_id" "$expected_stage" "$expected_previous" <<'PY'
import json
import sys

state = json.load(open(sys.argv[1], "r", encoding="utf-8"))
if state.get("run_id") != sys.argv[2] or state.get("stage") != sys.argv[3]:
    raise SystemExit(1)
previous = state.get("recovery_previous_stage")
if sys.argv[4] == "null":
    if previous is not None:
        raise SystemExit(1)
elif previous != sys.argv[4]:
    raise SystemExit(1)
PY
}

mapper_swap_entry_count() {
	local mapper_dev
	local swap_path swap_type swap_size swap_used swap_priority
	local swap_hex swap_major_hex swap_minor_hex swap_dev
	local count=0

	if ! dmsetup info "$DMNAME" >/dev/null 2>&1; then
		mapper_absence_proven || return 1
		printf '0\n'
		return 0
	fi
	mapper_dev="$(
		dmsetup info -c --noheadings --separator ':' -o major,minor \
			"$DMNAME" 2>/dev/null | tr -d '[:space:]'
	)" || return 1
	[[ "$mapper_dev" =~ ^[0-9]+:[0-9]+$ ]] || return 1
	while read -r swap_path swap_type swap_size swap_used swap_priority; do
		[[ "$swap_path" == Filename ]] && continue
		# A missing /proc/swaps device alias cannot establish swap absence.
		[[ -e "$swap_path" ]] || return 1
		[[ -b "$swap_path" ]] || continue
		swap_hex="$(stat -Lc '%t:%T' "$swap_path")" || return 1
		IFS=: read -r swap_major_hex swap_minor_hex <<< "$swap_hex"
		printf -v swap_dev '%d:%d' \
			"0x$swap_major_hex" "0x$swap_minor_hex"
		[[ "$swap_dev" != "$mapper_dev" ]] || count=$((count + 1))
	done < /proc/swaps
	printf '%s\n' "$count"
}

assert_exact_owned_mapper() {
	local expected_present="$1"
	local table_mode="${2:-active}"
	local mapper_uuid mapper_table expected_table
	local table_start table_sectors table_target table_lower table_rest

	if [[ "$expected_present" == 0 ]]; then
		mapper_absence_proven ||
			fail "unexpected mapper exists outside transaction ownership"
		return 0
	fi
	dmsetup info "$DMNAME" >/dev/null 2>&1 ||
		fail "expected run-bound mapper is missing"
	mapper_uuid="$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
		tr -d '[:space:]')" ||
		fail "cannot inspect interrupted mapper UUID"
	[[ "$mapper_uuid" == "SWAPZ-PRIMARY-$RUN_ID" ]] ||
		fail "interrupted mapper UUID is not owned by the current run"
	case "$table_mode" in
		active)
			mapper_table="$(dmsetup table "$DMNAME")" ||
				fail "cannot inspect interrupted active mapper table"
			;;
		inactive)
			mapper_table="$(dmsetup table --inactive "$DMNAME")" ||
				fail "cannot inspect interrupted inactive mapper table"
			;;
		*)
			fail "invalid mapper table mode: $table_mode"
			;;
	esac
	read -r table_start table_sectors table_target table_lower table_rest <<< "$mapper_table"
	[[ "$table_start" == 0 && "$table_sectors" =~ ^[1-9][0-9]*$ &&
	   "$table_target" == swapz && "$table_lower" == "$PART_DEVNO" ]] ||
		fail "interrupted mapper table is not bound to the owned partition"
	# Reject extra target rows, altered geometry and silently changed target
	# parameters, not just a matching first four fields.
	expected_table="$(sed -n 's/^dm_table=//p' "$RECOVERY_BASE/primary-manifest-$RUN_ID.txt")" ||
		fail "cannot read the run-bound durable mapper table"
	[[ -n "$expected_table" && "$mapper_table" == "$expected_table" ]] ||
		fail "mapper table differs from the exact run-bound durable manifest"
}

unrelated_swap_inventory_identity() {
	local mapper_device=""
	if dmsetup info "$DMNAME" >/dev/null 2>&1; then
		mapper_device="$(dmsetup info -c --noheadings --separator ':' \
			-o major,minor "$DMNAME" 2>/dev/null | tr -d '[:space:]')" ||
			return 1
		[[ "$mapper_device" =~ ^[0-9]+:[0-9]+$ ]] || return 1
	else
		mapper_absence_proven || return 1
	fi
	python3 - "$mapper_device" <<'PY'
import os
import stat
import sys

mapper_device = sys.argv[1]
with open("/proc/swaps", "r", encoding="utf-8") as swaps:
    header = swaps.readline().split()
    if header != ["Filename", "Type", "Size", "Used", "Priority"]:
        raise SystemExit(1)
    rows = []
    seen = set()
    for raw in swaps:
        fields = raw.split()
        if len(fields) != 5:
            raise SystemExit(1)
        path, swap_type, size_kib, used_kib, priority = fields
        if (not path.startswith("/") or not size_kib.isdigit() or
                not used_kib.isdigit()):
            raise SystemExit(1)
        try:
            int(priority)
        except ValueError:
            raise SystemExit(1)
        if path in seen:
            raise SystemExit(1)
        seen.add(path)
        if mapper_device:
            info = os.stat(path)
            if stat.S_ISBLK(info.st_mode):
                observed = f"{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
                if observed == mapper_device:
                    continue
        rows.append(f"{path}\t{swap_type}\t{size_kib}\t{priority}")
for row in sorted(rows):
    print(row)
PY
}

assert_unrelated_host_swap_identity() {
	local phase="$1"
	local observed

	observed="$(unrelated_swap_inventory_identity)" ||
		fail "cannot inspect unrelated host swap identity during $phase"
	[[ "$observed" == "$SWAPS_ID_BEFORE" ]] ||
		fail "unrelated host swap identity changed during $phase"
}

assert_owned_transaction_records() {
	local expect_active="$1"
	python3 - "$RECOVERY_BASE" "$RUN_ID" "$PARTUUID" "$PART_DEVNO" "$expect_active" <<'PY'
import json
import os
from pathlib import Path
import stat
import sys

recovery_path, run_id, partuuid, devno, expect_active = sys.argv[1:6]
major, minor = map(int, devno.split(":"))
directory = Path(recovery_path)
consumed = directory / ("consumed-" + run_id + ".json")
active = directory / ("partition-" + partuuid + ".active")

def canonical_owned_record(path):
    identity = path.lstat()
    if (not stat.S_ISREG(identity.st_mode) or identity.st_uid != 0 or
            stat.S_IMODE(identity.st_mode) != 0o600 or identity.st_nlink != 1):
        raise ValueError("unsafe transaction record identity")
    payload = path.read_bytes()
    canonical_bytes = (
        '{"major":' + str(major) + ',"minor":' + str(minor) +
        ',"partuuid":"' + partuuid + '","run_id":"' + run_id + '"}\n'
    ).encode("ascii")
    if payload != canonical_bytes:
        raise ValueError("noncanonical or wrong transaction owner")
    return payload

consumed_bytes = canonical_owned_record(consumed)
if expect_active == "1":
    if canonical_owned_record(active) != consumed_bytes:
        raise ValueError("active claim differs from durable consumed ownership")
elif expect_active == "0":
    if active.exists() or active.is_symlink():
        raise ValueError("completed transaction retains active ownership")
else:
    raise ValueError("invalid active owner expectation")
PY
}

prepare_interruption_run() {
	local output

	if ! output="$(timeout --signal=TERM --kill-after=10s 90s \
		"$CONTROL" primary prepare 2>&1)"; then
		verify_prepare_failure_diagnostic "$output"
		if [[ "$output" != *" claim=retained target_unchanged=true"* ]]; then
			blocked "interruption prepare refused before owner claim"
		fi
		fail "interruption prepare failed after owner claim"
	fi
	printf '%s\n' "$output"
	RUN_ID="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_PREPARE=READY run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$RUN_ID" =~ ^[0-9a-f]{32}$ ]] ||
		fail "interruption prepare did not emit one valid run ID"
	assert_lifecycle_state "$RUN_ID" READY null ||
		fail "interruption prepare did not persist clean READY"
	assert_owned_transaction_records 1 ||
		fail "prepare did not prove exact durable transaction ownership"
}

start_interruption_baseline() {
	local output start_run

	if ! output="$(
		timeout --signal=TERM --kill-after=10s 90s \
			"$CONTROL" primary start 2>&1
	)"; then
		printf '%s\n' "$output" >&2
		fail "interruption baseline start failed"
	fi
	printf '%s\n' "$output"
	start_run="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_START=ACTIVE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$start_run" == "$RUN_ID" ]] ||
		fail "interruption baseline start changed run ID"
	grep -Fq 'swapon=true' <<< "$output" ||
		fail "interruption baseline start did not activate swap"
	assert_lifecycle_state "$RUN_ID" ACTIVE null ||
		fail "interruption baseline start did not persist clean ACTIVE"
}

assert_interruption_kernel_facts() {
	local phase="$1"
	local expected_module expected_mapper expected_swap
	local expected_table_mode=active
	local observed_module=0
	local observed_mapper=0
	local observed_swap

	case "$phase" in
		start-starting|start-header-written)
			expected_module=0; expected_mapper=0; expected_swap=0
			;;
		start-module-inserted|start-module-loaded)
			expected_module=1; expected_mapper=0; expected_swap=0
			;;
		start-mapper-inactive)
			expected_module=1; expected_mapper=1; expected_swap=0
			expected_table_mode=inactive
			;;
		start-mapper-resumed|start-mkswap)
			expected_module=1; expected_mapper=1; expected_swap=0
			;;
		start-swapon|stop-stopping|recover-recovering)
			expected_module=1; expected_mapper=1; expected_swap=1
			;;
		stop-swapoff|recover-swapoff)
			expected_module=1; expected_mapper=1; expected_swap=0
			;;
		stop-mapper-removed|recover-mapper-removed)
			expected_module=1; expected_mapper=0; expected_swap=0
			;;
		stop-module-unloaded|stop-restored|recover-module-unloaded|recover-restored)
			expected_module=0; expected_mapper=0; expected_swap=0
			;;
		*)
			fail "unknown interruption phase: $phase"
			;;
	esac

	[[ ! -d /sys/module/dm_swapz ]] || observed_module=1
	dmsetup info "$DMNAME" >/dev/null 2>&1 && observed_mapper=1
	assert_exact_owned_mapper "$expected_mapper" "$expected_table_mode"
	observed_swap="$(mapper_swap_entry_count)" ||
		fail "cannot inspect interrupted mapper swap identity"
	[[ "$observed_module" == "$expected_module" &&
	   "$observed_mapper" == "$expected_mapper" &&
	   "$observed_swap" == "$expected_swap" ]] ||
		fail "unexpected kernel facts after $phase: module=$observed_module/$expected_module mapper=$observed_mapper/$expected_mapper swap=$observed_swap/$expected_swap"
	assert_unrelated_host_swap_identity "$phase"

	if [[ "$phase" == start-starting ]]; then
		[[ ! -e "$RECOVERY_BASE/primary-module-load-$RUN_ID.json" ]] ||
			fail "STARTING interruption unexpectedly published module WAL"
	else
		local expected_wal_phase=LOADED
		if [[ "$phase" == start-header-written ||
		      "$phase" == start-module-inserted ]]; then
			expected_wal_phase=INTENT
		fi
		[[ -f "$RECOVERY_BASE/primary-module-load-$RUN_ID.json" ]] &&
			grep -Fq "\"run_id\":\"$RUN_ID\"" \
				"$RECOVERY_BASE/primary-module-load-$RUN_ID.json" &&
			grep -Fq "\"phase\":\"$expected_wal_phase\"" \
				"$RECOVERY_BASE/primary-module-load-$RUN_ID.json" ||
			fail "interruption does not retain exact $expected_wal_phase module WAL"
	fi
}

capture_interruption_evidence() {
	local phase="$1"
	python3 - "$RECOVERY_BASE" "$EVIDENCE_BASE" "$RUN_ID" "$PARTUUID" "$phase" <<'PY'
import hashlib
import os
import stat
import sys

recovery_directory, evidence_directory, run_id, partuuid, phase = sys.argv[1:6]
if (len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id) or
        phase not in {"start-starting", "start-header-written",
                      "start-module-inserted", "start-module-loaded",
                      "start-mapper-inactive", "start-mapper-resumed",
                      "start-mkswap", "start-swapon",
                      "stop-stopping", "stop-swapoff",
                      "stop-mapper-removed", "stop-module-unloaded",
                      "stop-restored",
                      "recover-recovering", "recover-swapoff",
                      "recover-mapper-removed", "recover-module-unloaded",
                      "recover-restored"}):
    raise SystemExit("unsafe interruption snapshot identity")
record_names = [
    "primary-state.json",
    f"consumed-{run_id}.json",
    f"partition-{partuuid}.active",
    f"primary-manifest-{run_id}.txt",
]
if phase != "start-starting":
    record_names.append(f"primary-module-load-{run_id}.json")
source_fd = os.open(recovery_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
evidence_fd = os.open(evidence_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    for name in record_names:
        source_file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_fd)
        try:
            identity = os.fstat(source_file)
            if (not stat.S_ISREG(identity.st_mode) or identity.st_uid != 0 or
                    stat.S_IMODE(identity.st_mode) != 0o600 or identity.st_nlink != 1):
                raise ValueError("unsafe durable record")
            payload = bytearray()
            while True:
                chunk = os.read(source_file, 65536)
                if not chunk:
                    break
                payload.extend(chunk)
        finally:
            os.close(source_file)
        snapshot_name = f"{run_id}-{phase}-{name}"
        snapshot_fd = os.open(snapshot_name,
                              os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                              os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                              dir_fd=evidence_fd)
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(snapshot_fd, payload[offset:])
                if written <= 0:
                    raise OSError("short interruption evidence write")
                offset += written
            os.fsync(snapshot_fd)
        finally:
            os.close(snapshot_fd)
        print(f"PRIMARY_NULLBLK_INTERRUPTION_RECORD={snapshot_name} "
              f"sha256={hashlib.sha256(payload).hexdigest()}")
    os.fsync(evidence_fd)
finally:
    os.close(evidence_fd)
    os.close(source_fd)
PY
}

interrupt_lifecycle() {
	local operation="$1"
	local phase="$2"
	local expected_stage="$3"
	local expected_previous="${4:-null}"
	local output rc

	set +e
	output="$(
		SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER="$phase" \
		timeout --signal=TERM --kill-after=10s 90s \
			"$CONTROL" primary "$operation" 2>&1
	)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" == 86 ]] ||
		fail "$phase returned $rc instead of deterministic process-death status 86"
	assert_lifecycle_state "$RUN_ID" "$expected_stage" "$expected_previous" ||
		fail "$phase did not leave expected durable $expected_stage state"
	assert_owned_transaction_records 1 ||
		fail "$phase did not retain exact run-bound ownership"
	assert_interruption_kernel_facts "$phase"
	capture_interruption_evidence "$phase" || {
		QUARANTINE=1
		fail "$phase could not preserve byte-exact interruption evidence"
	}
}

recover_interruption_run() {
	local phase="$1"
	local expected_previous="$2"
	local expected_swapoff="$3"
	local expected_mapper_removed="$4"
	local expected_module_unloaded="$5"
	local output recovered_run swaps_after

	if ! output="$(
		timeout --signal=TERM --kill-after=10s 90s \
			"$CONTROL" primary recover 2>&1
	)"; then
		printf '%s\n' "$output" >&2
		fail "fresh-process recovery failed after $phase"
	fi
	printf '%s\n' "$output"
	recovered_run="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_RECOVER=COMPLETE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$recovered_run" == "$RUN_ID" ]] ||
		fail "recovery after $phase changed run ID"
	grep -Fq "swapoff=$expected_swapoff" <<< "$output" ||
		fail "recovery after $phase reported unexpected swapoff ownership"
	grep -Fq "mapper_removed=$expected_mapper_removed" <<< "$output" ||
		fail "recovery after $phase reported unexpected mapper ownership"
	grep -Fq "module_unloaded=$expected_module_unloaded" <<< "$output" ||
		fail "recovery after $phase reported unexpected module ownership"
	assert_lifecycle_state "$RUN_ID" COMPLETE "$expected_previous" ||
		fail "recovery after $phase did not preserve origin in COMPLETE"
	[[ ! -e "$RECOVERY_BASE/partition-$PARTUUID.active" ]] ||
		fail "recovery after $phase left active owner marker"
	assert_owned_transaction_records 0 ||
		fail "recovery after $phase lost consumed or released ownership incorrectly"
	[[ ! -d /sys/module/dm_swapz ]] ||
		fail "recovery after $phase left dm_swapz loaded"
	mapper_absence_proven ||
		fail "recovery after $phase left swapz-primary mapper"
	swaps_after="$(swapz_swap_inventory_identity /proc/swaps)" ||
		fail "cannot snapshot host swap identity after $phase recovery"
	[[ "$swaps_after" == "$SWAPS_ID_BEFORE" ]] ||
		fail "host swap identity differs after $phase recovery"
	assert_repeat_recovery_is_safe "$phase" "$expected_previous"
}

assert_repeat_recovery_is_safe() {
	local phase="$1"
	local expected_previous="$2"
	local before_state after_state before_swaps after_swaps output rc

	before_state="$(sha256sum "$RECOVERY_BASE/primary-state.json" | awk '{print $1}')" ||
		fail "cannot hash COMPLETE state before repeated recovery"
	before_swaps="$(swapz_swap_inventory_identity /proc/swaps)" ||
		fail "cannot snapshot swaps before repeated recovery"
	set +e
	output="$(LC_ALL=C timeout --signal=TERM --kill-after=10s 90s \
		"$CONTROL" primary recover 2>&1)"
	rc=$?
	set -e
	[[ "$rc" -eq 2 &&
	   "$output" == "BLOCKED: primary-swap recovery failed: Operation not permitted" ]] ||
		fail "repeated recovery after $phase lacked the expected COMPLETE refusal"
	after_state="$(sha256sum "$RECOVERY_BASE/primary-state.json" | awk '{print $1}')" ||
		fail "cannot hash COMPLETE state after repeated recovery"
	after_swaps="$(swapz_swap_inventory_identity /proc/swaps)" ||
		fail "cannot snapshot swaps after repeated recovery"
	[[ "$after_state" == "$before_state" && "$after_swaps" == "$before_swaps" &&
	   "$after_swaps" == "$SWAPS_ID_BEFORE" ]] ||
		fail "repeated recovery after $phase changed durable or kernel state"
	assert_lifecycle_state "$RUN_ID" COMPLETE "$expected_previous" ||
		fail "repeated recovery after $phase changed COMPLETE provenance"
	[[ ! -d /sys/module/dm_swapz ]] ||
		fail "repeated recovery after $phase loaded dm_swapz"
	mapper_absence_proven ||
		fail "repeated recovery after $phase recreated swapz-primary"
}

run_faulted_start_failure() {
	local fault="$1"
	local expected_swap="$2"
	local output rc observed_swap

	prepare_interruption_run
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=$fault run_id:$RUN_ID"
	set +e
	output="$(SWAPZ_PRIMARY_TEST_FAULT="$fault" \
		timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary start 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] || fail "$fault unexpectedly completed primary start"
	grep -Fxq "SWAPZ_PRIMARY_TEST_FAULT_HIT=$fault" <<< "$output" ||
		fail "$fault failed for an unrelated reason: no selected fault hit"
	assert_lifecycle_state "$RUN_ID" RECOVERY_REQUIRED STARTING ||
		fail "$fault did not preserve STARTING recovery provenance"
	assert_exact_owned_mapper 1
	observed_swap="$(mapper_swap_entry_count)" ||
		fail "cannot inspect mapper swap state after $fault"
	[[ "$observed_swap" == "$expected_swap" ]] ||
		fail "$fault left unexpected mapper swap state"
	assert_unrelated_host_swap_identity "$fault"
	if [[ "$expected_swap" == 1 ]]; then
		recover_interruption_run "$fault" STARTING true true true
	else
		recover_interruption_run "$fault" STARTING false true true
	fi
}

run_faulted_stop_failure() {
	local fault="$1"
	local expected_swap="$2"
	local output rc observed_swap

	prepare_interruption_run
	start_interruption_baseline
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=$fault run_id:$RUN_ID"
	set +e
	output="$(SWAPZ_PRIMARY_TEST_FAULT="$fault" \
		timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary stop 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] || fail "$fault unexpectedly completed primary stop"
	grep -Fxq "SWAPZ_PRIMARY_TEST_FAULT_HIT=$fault" <<< "$output" ||
		fail "$fault failed for an unrelated reason: no selected fault hit"
	assert_lifecycle_state "$RUN_ID" RECOVERY_REQUIRED STOPPING ||
		fail "$fault did not preserve STOPPING recovery provenance"
	assert_exact_owned_mapper 1
	observed_swap="$(mapper_swap_entry_count)" ||
		fail "cannot inspect mapper swap state after $fault"
	[[ "$observed_swap" == "$expected_swap" ]] ||
		fail "$fault left unexpected mapper swap state"
	assert_unrelated_host_swap_identity "$fault"
	if [[ "$expected_swap" == 1 ]]; then
		recover_interruption_run "$fault" STOPPING true true true
	else
		recover_interruption_run "$fault" STOPPING false true true
	fi
}

run_ambiguous_swapon_applied() {
	local output start_run stop_run

	prepare_interruption_run
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=swapon-eintr-applied run_id:$RUN_ID"
	if ! output="$(SWAPZ_PRIMARY_TEST_FAULT=swapon-eintr-applied \
		timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary start 2>&1)"; then
		printf '%s\n' "$output" >&2
		fail "ambiguous swapon with exact active proof was not reconciled"
	fi
	grep -Fxq "SWAPZ_PRIMARY_TEST_FAULT_HIT=swapon-eintr-applied" <<< "$output" ||
		fail "ambiguous swapon never reached the selected syscall"
	printf '%s\n' "$output"
	start_run="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_START=ACTIVE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$start_run" == "$RUN_ID" ]] ||
		fail "ambiguous swapon reconciliation changed run ID"
	assert_lifecycle_state "$RUN_ID" ACTIVE null ||
		fail "ambiguous swapon reconciliation did not publish ACTIVE"
	assert_exact_owned_mapper 1
	[[ "$(mapper_swap_entry_count)" == 1 ]] ||
		fail "ambiguous swapon reconciliation lacks exact active inventory"
	assert_unrelated_host_swap_identity "swapon-eintr-applied"
	if ! output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary stop 2>&1)"; then
		printf '%s\n' "$output" >&2
		fail "normal stop failed after ambiguous swapon reconciliation"
	fi
	printf '%s\n' "$output"
	stop_run="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_STOP=COMPLETE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$stop_run" == "$RUN_ID" ]] ||
		fail "normal stop after ambiguous swapon changed run ID"
	assert_lifecycle_state "$RUN_ID" COMPLETE null ||
		fail "normal stop after ambiguous swapon did not complete"
	[[ ! -d /sys/module/dm_swapz ]] ||
		fail "normal stop after ambiguous swapon left dm_swapz loaded"
	mapper_absence_proven ||
		fail "normal stop after ambiguous swapon left mapper present"
	assert_unrelated_host_swap_identity "swapon-eintr-applied-stop"
	assert_repeat_recovery_is_safe "swapon-eintr-applied" null
}

run_ambiguous_swapoff_applied() {
	local output stop_run

	prepare_interruption_run
	start_interruption_baseline
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=swapoff-eintr-applied run_id:$RUN_ID"
	if ! output="$(SWAPZ_PRIMARY_TEST_FAULT=swapoff-eintr-applied \
		timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary stop 2>&1)"; then
		printf '%s\n' "$output" >&2
		fail "ambiguous swapoff with exact inactive proof was not reconciled"
	fi
	grep -Fxq "SWAPZ_PRIMARY_TEST_FAULT_HIT=swapoff-eintr-applied" <<< "$output" ||
		fail "ambiguous swapoff never reached the selected syscall"
	printf '%s\n' "$output"
	stop_run="$(printf '%s\n' "$output" |
		sed -n 's/^PRIMARY_STOP=COMPLETE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
	[[ "$stop_run" == "$RUN_ID" ]] ||
		fail "ambiguous swapoff reconciliation changed run ID"
	assert_lifecycle_state "$RUN_ID" COMPLETE null ||
		fail "ambiguous swapoff reconciliation did not publish COMPLETE"
	[[ ! -d /sys/module/dm_swapz ]] ||
		fail "ambiguous swapoff reconciliation left dm_swapz loaded"
	mapper_absence_proven ||
		fail "ambiguous swapoff reconciliation left mapper present"
	assert_unrelated_host_swap_identity "swapoff-eintr-applied"
	assert_repeat_recovery_is_safe "swapoff-eintr-applied" null
}

run_failed_fsync_case() {
	local output rc

	prepare_interruption_run
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=state-dir-fsync run_id:$RUN_ID"
	set +e
	output="$(SWAPZ_PRIMARY_TEST_FSYNC_FAIL_DIRECTORY_CALL=2 \
		timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary start 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] || fail "injected state directory fsync failure was ignored"
	grep -Fxq "SWAPZ_PRIMARY_TEST_FSYNC_DIRECTORY_HIT=2" <<< "$output" ||
		fail "selected post-rename state-directory fsync did not fail"
	assert_lifecycle_state "$RUN_ID" STARTING null ||
		fail "fsync failure did not retain the renamed STARTING record"
	[[ -f "$RECOVERY_BASE/partition-$PARTUUID.active" ]] ||
		fail "fsync failure lost transaction ownership marker"
	assert_interruption_kernel_facts start-starting
	recover_interruption_run "state-dir-fsync" STARTING false false false
}

preserve_state_file() {
	local tag="$1"
	local backup="$EVIDENCE_BASE/primary-state-$tag.bin"
	python3 - "$RECOVERY_BASE/primary-state.json" "$backup" <<'PY'
import os
import sys

source, backup = sys.argv[1:3]
payload = open(source, "rb").read()
fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
try:
    offset = 0
    while offset < len(payload):
        count = os.write(fd, payload[offset:])
        if count <= 0:
            raise OSError("short state evidence write")
        offset += count
    os.fsync(fd)
finally:
    os.close(fd)
directory = os.open(os.path.dirname(backup), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
	printf '%s\n' "$backup"
}

restore_state_file() {
	local backup="$1"
	python3 - "$backup" "$RECOVERY_BASE/primary-state.json" <<'PY'
import os
import sys

backup, target = sys.argv[1:3]
payload = open(backup, "rb").read()
directory_path = os.path.dirname(target)
temporary = target + ".agent7-restore.tmp"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
try:
    offset = 0
    while offset < len(payload):
        count = os.write(fd, payload[offset:])
        if count <= 0:
            raise OSError("short state restore write")
        offset += count
    os.fsync(fd)
finally:
    os.close(fd)
os.replace(temporary, target)
directory = os.open(directory_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

expect_recovery_refusal_preserves_kernel() {
	local case_name="$1"
	local phase="$2"
	local output rc before_state after_state before_claim after_claim
	local state_file="$RECOVERY_BASE/primary-state.json"
	local active_claim="$RECOVERY_BASE/partition-$PARTUUID.active"
	local consumed_claim="$RECOVERY_BASE/consumed-$RUN_ID.json"

	before_state=missing
	[[ ! -e "$state_file" && ! -L "$state_file" ]] ||
		before_state="$(sha256sum "$state_file" | awk '{print $1}')" ||
		fail "cannot hash denied-recovery durable state"
	before_claim="$(sha256sum "$active_claim" "$consumed_claim")" ||
		fail "cannot snapshot denied-recovery ownership records"
	set +e
	output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary recover 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] || fail "$case_name unexpectedly authorized recovery"
	after_state=missing
	[[ ! -e "$state_file" && ! -L "$state_file" ]] ||
		after_state="$(sha256sum "$state_file" | awk '{print $1}')" ||
		fail "cannot hash denied-recovery durable state after refusal"
	after_claim="$(sha256sum "$active_claim" "$consumed_claim")" ||
		fail "cannot resnapshot denied-recovery ownership records"
	[[ "$before_state" == "$after_state" &&
	   "$before_claim" == "$after_claim" ]] ||
		fail "$case_name mutated durable state or transaction ownership on refusal"
	assert_interruption_kernel_facts "$phase"
}

run_stale_run_id_case() {
	local backup alternate before_hash after_hash

	prepare_interruption_run
	interrupt_lifecycle start start-starting STARTING
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=stale-run-id run_id:$RUN_ID"
	backup="$(preserve_state_file stale-run-id)" ||
		fail "cannot preserve state for stale-run-id case"
	before_hash="$(sha256sum "$backup" | awk '{print $1}')"
	alternate=ffffffffffffffffffffffffffffffff
	[[ "$RUN_ID" != "$alternate" ]] || alternate=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
	python3 - "$RECOVERY_BASE/primary-state.json" "$RUN_ID" "$alternate" <<'PY'
import os
import sys

path, original_run_id, alternate_run_id = sys.argv[1:4]
with open(path, "rb") as source:
    original = source.read()
needle = ('"run_id":"' + original_run_id + '"').encode("ascii")
replacement = ('"run_id":"' + alternate_run_id + '"').encode("ascii")
if (len(original_run_id) != 32 or len(alternate_run_id) != 32 or
        original.count(needle) != 1 or not original.endswith(b"}\n")):
    raise SystemExit("unsafe noncanonical run ID fixture")
# Only mutate the transaction identity; preserve every other native state byte.
payload = original.replace(needle, replacement, 1)
if len(payload) != len(original):
    raise SystemExit("stale run ID fixture changed record length")
temporary = path + ".agent7-stale.tmp"
fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
try:
    offset = 0
    while offset < len(payload):
        count = os.write(fd, payload[offset:])
        if count <= 0:
            raise OSError("short stale state write")
        offset += count
    os.fsync(fd)
finally:
    os.close(fd)
os.replace(temporary, path)
directory = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
	expect_recovery_refusal_preserves_kernel stale-run-id start-starting
	restore_state_file "$backup" || fail "cannot restore exact stale-run-id state"
	after_hash="$(sha256sum "$RECOVERY_BASE/primary-state.json" | awk '{print $1}')"
	[[ "$after_hash" == "$before_hash" ]] ||
		fail "stale-run-id state restoration was not byte-exact"
	recover_interruption_run "stale-run-id" STARTING false false false
}

run_lost_state_provenance_case() {
	local backup state_path

	prepare_interruption_run
	interrupt_lifecycle start start-mapper-resumed STARTING
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=lost-state-provenance run_id:$RUN_ID"
	backup="$(preserve_state_file lost-state-provenance)" ||
		fail "cannot preserve state for lost provenance case"
	state_path="$RECOVERY_BASE/primary-state.json"
	rm -- "$state_path" || fail "cannot hide state provenance for negative case"
	python3 - "$RECOVERY_BASE" <<'PY'
import os
import sys

fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
	expect_recovery_refusal_preserves_kernel lost-state-provenance start-mapper-resumed
	restore_state_file "$backup" || fail "cannot restore lost state provenance"
	recover_interruption_run "lost-state-provenance" STARTING false true true
}

run_wrong_mapper_identity_case() {
	local mapper_table exact_uuid wrong_uuid open_count output rc

	prepare_interruption_run
	interrupt_lifecycle start start-mapper-resumed STARTING
	note "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=wrong-mapper-identity run_id:$RUN_ID"
	mapper_table="$(dmsetup table "$DMNAME")" ||
		fail "cannot preserve exact mapper table for wrong-identity case"
	exact_uuid="SWAPZ-PRIMARY-$RUN_ID"
	wrong_uuid="SWAPZ-PRIMARY-ffffffffffffffffffffffffffffffff"
	[[ "$exact_uuid" != "$wrong_uuid" ]] ||
		wrong_uuid="SWAPZ-PRIMARY-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
	[[ "$(mapper_swap_entry_count)" == 0 ]] ||
		fail "wrong-mapper case refuses to replace an active mapper"
	open_count="$(dmsetup info -c --noheadings -o open "$DMNAME" 2>/dev/null |
		tr -d '[:space:]')" ||
		fail "cannot inspect mapper open count before identity mutation"
	[[ "$open_count" == 0 ]] ||
		fail "wrong-mapper case refuses to remove mapper with users"
	dmsetup remove "$DMNAME" ||
		fail "normal removal of inactive owned mapper failed"
	dmsetup create "$DMNAME" --uuid "$wrong_uuid" --table "$mapper_table" ||
		fail "cannot create wrong-identity negative mapper"
	set +e
	output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary recover 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] || fail "recovery accepted wrong mapper identity"
	[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
		tr -d '[:space:]')" == "$wrong_uuid" ]] ||
		fail "recovery altered the wrong mapper"
	[[ "$(mapper_swap_entry_count)" == 0 ]] ||
		fail "wrong mapper became active during refused recovery"
	assert_unrelated_host_swap_identity "wrong-mapper-identity"
	assert_lifecycle_state "$RUN_ID" RECOVERY_REQUIRED STARTING ||
		fail "wrong mapper refusal did not preserve recovery origin"
	open_count="$(dmsetup info -c --noheadings -o open "$DMNAME" 2>/dev/null |
		tr -d '[:space:]')" ||
		fail "cannot inspect wrong mapper users before restoration"
	[[ "$open_count" == 0 ]] ||
		fail "wrong mapper gained users; quarantine required"
	dmsetup remove "$DMNAME" ||
		fail "normal removal of wrong inactive mapper failed"
	dmsetup create "$DMNAME" --uuid "$exact_uuid" --table "$mapper_table" ||
		fail "cannot restore exact owned mapper identity"
	assert_exact_owned_mapper 1
	recover_interruption_run "wrong-mapper-identity" STARTING false true true
}

cleanup() {
	local original_rc=$?
	local stage=""
	local swaps_after=""
	trap - EXIT HUP INT TERM
	set +e

	# Do not invoke production recovery on a replaced or unobservable lower:
	# its mapper/module teardown may otherwise mutate another owner's state.
	if (( OWN_NULL )) &&
	   { ! owned_nullblk_live_identity_unchanged ||
	     ! owned_nullblk_mapper_identity_unchanged; }; then
		QUARANTINE=1
		note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_or_mapper_identity_uncertain"
	fi

	if (( OWN_NULL && ! QUARANTINE )) && [[ -x "$CONTROL" ]]; then
		stage="$(state_stage 2>/dev/null)"
		if ! mapper_absence_proven ||
		   [[ -d /sys/module/dm_swapz ]] ||
		   [[ "$stage" == STARTING || "$stage" == ACTIVE ||
		      "$stage" == STOPPING || "$stage" == RECOVERY_REQUIRED ||
		      "$stage" == RECOVERING || "$stage" == RESTORED ]]; then
			note "RECOVER_PRIMARY_NULLBLK_LIFECYCLE=attempt"
			if ! owned_nullblk_live_identity_unchanged ||
			   ! owned_nullblk_mapper_identity_unchanged; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_or_mapper_identity_uncertain"
			elif ! timeout --signal=TERM --kill-after=10s 60s \
				"$CONTROL" primary recover >/dev/null 2>&1; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=recovery_failed"
			fi
		fi
	fi

	if ! mapper_absence_proven || [[ -d /sys/module/dm_swapz ]]; then
		QUARANTINE=1
		note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=mapper_or_module_remains"
	fi
	swaps_after="$(swapz_swap_inventory_identity /proc/swaps 2>/dev/null)"
	if [[ $? -ne 0 || "$swaps_after" != "$SWAPS_ID_BEFORE" ]]; then
		QUARANTINE=1
		note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=host_swap_identity_changed"
	fi

	if [[ -d "$RECOVERY_BASE" && ! -L "$RECOVERY_BASE" ]]; then
		# An earlier recovery attempt may have completed after the initial
		# stage snapshot. Judge teardown only from the final durable record.
		stage="$(state_stage 2>/dev/null)"
		local state_file="$RECOVERY_BASE/primary-state.json"
		local marker_path
		if [[ -e "$state_file" || -L "$state_file" ]]; then
			if [[ "$stage" != COMPLETE || ! "$RUN_ID" =~ ^[0-9a-f]{32}$ ]] ||
			   ! python3 - "$state_file" "$RUN_ID" <<'PY'
import json
import os
import stat
import sys

def state_identity_safe(identity):
    return (
        stat.S_ISREG(identity.st_mode) and
        identity.st_uid == 0 and
        stat.S_IMODE(identity.st_mode) == 0o600 and
        identity.st_nlink == 1 and
        0 < identity.st_size <= 4096
    )


state_fd = -1
valid = False
try:
    # Reject special files before open, then pin and revalidate the exact inode.
    named_identity = os.lstat(sys.argv[1])
    if not state_identity_safe(named_identity):
        raise ValueError("unsafe named durable state identity")
    state_fd = os.open(
        sys.argv[1],
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    opened_identity = os.fstat(state_fd)
    if (not state_identity_safe(opened_identity) or
            opened_identity.st_dev != named_identity.st_dev or
            opened_identity.st_ino != named_identity.st_ino or
            opened_identity.st_size != named_identity.st_size):
        raise ValueError("durable state identity changed while opening")
    payload = bytearray()
    while len(payload) < opened_identity.st_size:
        chunk = os.read(state_fd, opened_identity.st_size - len(payload))
        if not chunk:
            raise OSError("short durable state read")
        payload.extend(chunk)
    if os.read(state_fd, 1):
        raise ValueError("durable state changed size while reading")
    after_identity = os.lstat(sys.argv[1])
    if (not state_identity_safe(after_identity) or
            after_identity.st_dev != opened_identity.st_dev or
            after_identity.st_ino != opened_identity.st_ino or
            after_identity.st_size != opened_identity.st_size):
        raise ValueError("durable state path changed while reading")
    actual_bytes = bytes(payload)
    state = json.loads(actual_bytes.decode("utf-8"))
    previous = state.get("recovery_previous_stage")
    if previous not in (None, "STARTING", "STOPPING"):
        raise ValueError("invalid recovery provenance")
    previous_token = "null" if previous is None else '"' + previous + '"'
    canonical_bytes = (
        '{"schema":"swapz-primary-state-v1","run_id":"' +
        sys.argv[2] + '","stage":"COMPLETE",'
        '"recovery_previous_stage":' + previous_token + '}\n'
    ).encode("ascii")
    valid = (state.get("run_id") == sys.argv[2] and
             state.get("stage") == "COMPLETE" and
             actual_bytes == canonical_bytes)
except (OSError, ValueError, TypeError, AttributeError):
    valid = False
finally:
    if state_fd >= 0:
        try:
            os.close(state_fd)
        except OSError:
            valid = False
raise SystemExit(0 if valid else 1)
PY
			then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=unfinished_or_ambiguous_durable_state"
			fi
			# COMPLETE alone is insufficient: reject a malformed permanent
			# owner record before discarding the last recovery evidence.
			if [[ "$stage" == COMPLETE ]] &&
			   ! assert_owned_transaction_records 0 >/dev/null 2>&1; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=noncanonical_consumed_owner_record"
			fi
		elif compgen -G "$RECOVERY_BASE/consumed-*.json" >/dev/null ||
		     compgen -G "$RECOVERY_BASE/primary-manifest-*.txt" >/dev/null ||
		     compgen -G "$RECOVERY_BASE/primary-module-load-*.json" >/dev/null; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=lost_state_provenance"
		fi
		for marker_path in "$RECOVERY_BASE"/partition-*.active; do
			if [[ -e "$marker_path" || -L "$marker_path" ]]; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=unresolved_owner_record"
				break
			fi
		done
	fi

	if (( OWN_NULL )) && (( ! QUARANTINE )); then
		if [[ -n "$PART_SYSFS" && -d "$PART_SYSFS/holders" &&
		      -n "$(ls -A "$PART_SYSFS/holders" 2>/dev/null)" ]]; then
			QUARANTINE=1
		elif [[ -n "$DISK" && -d "/sys/block/$DISK/holders" &&
		        -n "$(ls -A "/sys/block/$DISK/holders" 2>/dev/null)" ]]; then
			QUARANTINE=1
		elif [[ -n "$PARTITION" && -n "$(findmnt -rn -S "$PARTITION" 2>/dev/null)" ]]; then
			QUARANTINE=1
		elif [[ -n "$LOWER" && -n "$(findmnt -rn -S "$LOWER" 2>/dev/null)" ]]; then
			QUARANTINE=1
		fi
		if (( QUARANTINE )); then
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=owned_device_busy"
		fi
	fi

	if (( OWN_NULL )) && (( ! QUARANTINE )); then
		local power_off_status=0
		if ! owned_nullblk_live_identity_unchanged ||
		   ! owned_nullblk_mapper_identity_unchanged ||
		   ! mapper_absence_proven || [[ -d /sys/module/dm_swapz ]]; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
		else
			owned_nullblk_power_off_pinned
			power_off_status=$?
			if (( power_off_status == 1 )); then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
			elif (( power_off_status != 0 )); then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
			elif ! mapper_absence_proven || [[ -d /sys/module/dm_swapz ]]; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
			# This is the last observable configfs proof before rmdir.
			# Configfs has no atomic compare-and-remove primitive.
			elif ! owned_nullblk_post_power_identity_unchanged; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
			elif ! rmdir -- "$CONFIG" 2>/dev/null; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
			fi
		fi
	fi

	if (( OWN_NULL )) && (( ! QUARANTINE )); then
		if ! udevadm settle --timeout=10 >/dev/null 2>&1; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=udev_settle_failed_after_device_removal"
		fi
		if [[ -n "$BY_PARTUUID" &&
		      ( -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ) ]]; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=udev_alias_remains_after_device_removal"
		fi
	fi

	if (( UDEV_RULE_CREATED )); then
		if (( QUARANTINE )); then
			note "RETAINED_PRIMARY_NULLBLK_UDEV_RULE=private"
		elif [[ -d "$UDEV_RULES_DIR" && ! -L "$UDEV_RULES_DIR" &&
		        -f "$UDEV_RULE" && ! -L "$UDEV_RULE" &&
		        "$(stat -Lc '%u' "$UDEV_RULE" 2>/dev/null)" == 0 &&
		        "$(cat "$UDEV_RULE" 2>/dev/null)" == "$UDEV_RULE_CONTENT" ]]; then
			rm -- "$UDEV_RULE" || QUARANTINE=1
			if (( !QUARANTINE )); then
				udevadm control --reload-rules || QUARANTINE=1
			fi
			if (( QUARANTINE )); then
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=udev_rule_cleanup_failed"
			fi
		else
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=udev_rule_identity_changed"
		fi
	fi

	if (( UDEV_RULES_DIR_CREATED )) && (( ! QUARANTINE )); then
		rmdir -- "$UDEV_RULES_DIR" 2>/dev/null || true
	fi

	if (( TEST_BASE_CREATED )) && (( ! QUARANTINE )) &&
	   (( ! RETAIN_PRIVATE_EVIDENCE )); then
		if [[ ! "$TOKEN" =~ ^[a-f0-9]{16}$ ||
		      "$TEST_BASE" != "/var/lib/swapz-primary-owned-nullblk-test-$TOKEN" ||
		      ! -d "$TEST_BASE" || -L "$TEST_BASE" ||
		      "$(stat -Lc '%u:%a' "$TEST_BASE" 2>/dev/null)" != 0:700 ]]; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=test_base_identity_uncertain"
		else
			rm -rf --one-file-system -- "$TEST_BASE" || QUARANTINE=1
		fi
	fi

	if (( QUARANTINE || RETAIN_PRIVATE_EVIDENCE )); then
		note "PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=private"
		(( original_rc == 0 )) && original_rc=1
	fi
	exit "$original_rc"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=setup"
install -d -m 0700 "$TEST_BASE" "$CONFIG_BASE" "$RECOVERY_BASE" \
	"$MUTATION_LOCK_BASE" "$EVIDENCE_BASE" "$PREFIX" "$PREFIX/sbin" \
	"$PREFIX/libexec" "$PREFIX/libexec/swapz"
TEST_BASE_CREATED=1

VERSION="$(cat src/kernel/VERSION)"
cc -std=c11 -O2 -g -Wall -Wextra -Werror \
	-include build/source-build-info.h \
	"-DSWAPZ_VERSION=\"$VERSION\"" \
	-DSWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1 \
	"-DSWAPZ_PRIMARY_TEST_CONFIG_BASE=\"$CONFIG_BASE\"" \
	"-DSWAPZ_PRIMARY_TEST_RECOVERY_BASE=\"$RECOVERY_BASE\"" \
	"-DSWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY=\"$MUTATION_LOCK_BASE\"" \
	"-DSWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT=\"$REPORT\"" \
	src/userspace/swapzctl.c src/userspace/swapz-primary.c "$FAULT_FIXTURE" \
	-Wl,--wrap=syscall -Wl,--wrap=open -Wl,--wrap=fsync -o "$CONTROL" ||
	fail "private exact-source swapzctl compilation failed"
chmod 0500 "$CONTROL"
install -m 0400 build/kernel/experimental/dm-swapz.ko \
	"$PREFIX/libexec/swapz/dm-swapz.ko"
install -m 0500 build/tests/device-roundtrip \
	"$PREFIX/libexec/swapz/device-roundtrip"

FORMATTER_SHA="$(sha256sum "$CONTROL" | awk '{print $1}')"
MODULE_SHA="$(sha256sum "$PREFIX/libexec/swapz/dm-swapz.ko" | awk '{print $1}')"
ORACLE_SHA="$(sha256sum "$PREFIX/libexec/swapz/device-roundtrip" | awk '{print $1}')"
HOST_SHA="$(python3 - <<'PY'
import hashlib
import os
import re
import stat

expected_owner = 0

def trusted_host_record(path, byte_limit, pattern):
    file_descriptor = -1
    payload = bytearray()
    try:
        file_descriptor = os.open(
            path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        before = os.fstat(file_descriptor)
        if (not stat.S_ISREG(before.st_mode) or
                before.st_uid != expected_owner or before.st_nlink != 1 or
                before.st_mode & 0o022):
            raise ValueError("untrusted host identity metadata")
        while len(payload) < byte_limit:
            chunk = os.read(file_descriptor, byte_limit - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) == byte_limit:
            raise ValueError("oversized host identity record")
        after = os.fstat(file_descriptor)
        stable_fields = (
            "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
            "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field)
               for field in stable_fields):
            raise ValueError("host identity changed during read")
    except (OSError, ValueError):
        raise SystemExit(2) from None
    finally:
        if file_descriptor >= 0:
            try:
                os.close(file_descriptor)
            except OSError:
                raise SystemExit(2) from None
    record = bytes(payload)
    if record.endswith(b"\n"):
        record = record[:-1]
    if (re.fullmatch(pattern, record) is None or
            not any(byte not in (ord("0"), ord("-")) for byte in record)):
        raise SystemExit(2)
    return record.lower()

machine = trusted_host_record(
    "/etc/machine-id", 64, rb"[0-9a-fA-F]{32}")
if os.environ["HOST_ARCH"] == "aarch64":
    # Never hardware identity: scoped to the private owned RAM rehearsal.
    identity = b"swapz-nullblk-arm64-v1\0" + machine
elif os.environ["HOST_ARCH"] == "x86_64":
    product_uuid = trusted_host_record(
        "/sys/class/dmi/id/product_uuid", 40,
        rb"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        rb"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    identity = b"swapz-host-v2\0" + product_uuid + machine
else:
    raise SystemExit(2)
print(hashlib.sha256(identity).hexdigest())
PY
)" || blocked "cannot derive live host identity"

export SOURCE_HEAD FORMATTER_SHA MODULE_SHA ORACLE_SHA HOST_SHA REPORT
python3 - <<'PY'
import json
import os
from pathlib import Path
report = {
    "schema": "swapz-test-results-v1",
    "host_identity": {
        "schema": "swapz-host-v1",
        "architecture": os.environ["HOST_ARCH"],
        "id_sha256": os.environ["HOST_SHA"],
    },
    "source_sha": os.environ["SOURCE_HEAD"],
    "tested_commit_sha": os.environ["SOURCE_HEAD"],
    "kernel_release": os.uname().release,
    "overall": "PASS",
    "qualification": "RAM_BACKED_NULL_BLK_ONLY",
    "stages": [
        {"name": "Build module and helpers", "status": "PASS", "exit_code": 0},
        {"name": "Native and rootless contracts", "status": "PASS", "exit_code": 0},
        {"name": "Kernel warnings W=1", "status": "PASS", "exit_code": 0},
        {"name": "Kernel warnings W=2", "status": "PASS", "exit_code": 0},
        {"name": "Owned RAM smoke + mixed/QD pilot", "status": "PASS", "exit_code": 0},
    ],
    "qualified_artifacts": {
        "status": "AVAILABLE",
        "formatter_sha256": os.environ["FORMATTER_SHA"],
        "module_sha256": os.environ["MODULE_SHA"],
        "oracle_sha256": os.environ["ORACLE_SHA"],
    },
    "test_scope": "OWNED_NULLBLK_PRIMARY_LIFECYCLE_REHEARSAL",
}
payload = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
path = Path(os.environ["REPORT"])
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
try:
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise OSError("short qualification report write")
        offset += written
    os.fsync(fd)
finally:
    os.close(fd)
PY

mountpoint -q /sys/kernel/config || {
	modprobe configfs || blocked "configfs module unavailable"
	mount -t configfs none /sys/kernel/config ||
		blocked "cannot mount configfs for owned null_blk"
}
if [[ ! -d "$CONFIGFS" ]]; then
	modprobe null_blk nr_devices=0 ||
		blocked "null_blk configfs interface unavailable"
fi
[[ -d "$CONFIGFS" && ! -L "$CONFIGFS" ]] ||
	blocked "null_blk configfs root unavailable"

CONFIGNAME="nullb-swapz-$TOKEN"
CONFIG="$CONFIGFS/$CONFIGNAME"
mkdir -- "$CONFIG" 2>/dev/null || blocked "cannot allocate owned null_blk config"
OWN_NULL=1
CONFIG_IDENTITY="$(stat -c '%d:%i:%u' -- "$CONFIG" 2>/dev/null)" ||
	fail "cannot capture created null_blk configfs identity"
	[[ "$CONFIG_IDENTITY" =~ ^[0-9]+:[0-9]+:0$ &&
   -d "$CONFIG" && ! -L "$CONFIG" &&
   -f "$CONFIG/power" && ! -L "$CONFIG/power" &&
   "$(stat -c '%d:%i:%u' -- "$CONFIG" 2>/dev/null)" == "$CONFIG_IDENTITY" ]] ||
	fail "created null_blk configfs owner or type is unproven"
echo "$NULLBLK_SIZE_MIB" > "$CONFIG/size"
echo 4096 > "$CONFIG/blocksize"
echo 1 > "$CONFIG/memory_backed"
echo 1 > "$CONFIG/discard"
echo 2 > "$CONFIG/queue_mode"
echo 1 > "$CONFIG/submit_queues"
echo 1 > "$CONFIG/hw_queue_depth"
echo 2 > "$CONFIG/irqmode"
echo 14000 > "$CONFIG/completion_nsec"
echo 1 > "$CONFIG/power"
INDEX="$(cat "$CONFIG/index")"
[[ "$INDEX" =~ ^(0|[1-9][0-9]*)$ ]] || fail "owned null_blk index is malformed"

for ignored in {1..50}; do
	DISK="$(swapz_resolve_owned_disk "$CONFIGNAME" "$INDEX" /sys/block)" && break
	sleep 0.1
done
[[ -n "$DISK" ]] || blocked "owned null_blk disk is missing or ambiguous"
DEVNO="$(cat "/sys/block/$DISK/dev")"
NULL_MAJOR="$(awk '/^Block devices:/{b=1;next} b && $2=="nullb"{print $1;exit}' /proc/devices)"
[[ "$DEVNO" =~ ^[0-9]+:[0-9]+$ && -n "$NULL_MAJOR" &&
   "$DEVNO" == "$NULL_MAJOR:$INDEX" ]] ||
	fail "owned null_blk major/minor identity mismatch"
LOWER="/dev/$DISK"
for ignored in {1..50}; do
	[[ -b "$LOWER" ]] && break
	sleep 0.1
done
[[ -b "$LOWER" ]] || blocked "owned null_blk device node is unavailable"
LOWER_NODE_DEVNO="$(block_node_devno "$LOWER")" ||
	fail "cannot resolve owned null_blk device node identity"
[[ "$LOWER_NODE_DEVNO" == "$DEVNO" ]] ||
	fail "owned null_blk device node major/minor differs from sysfs"
[[ "$(blockdev --getsize64 "$LOWER")" == $((NULLBLK_SIZE_MIB * 1024 * 1024)) ]] ||
	fail "owned null_blk size differs from requested RAM geometry"
[[ -z "$(ls -A "/sys/block/$DISK/holders")" ]] ||
	fail "owned null_blk unexpectedly has holders"

DISK_ID="$(printf '%s' "$TOKEN" | cut -c1-8)"
[[ "$DISK_ID" != 00000000 ]] || DISK_ID=1a2b3c4d
if sfdisk --lock --wipe always "$LOWER" >/dev/null 2>&1 <<EOF
label: dos
label-id: 0x$DISK_ID
unit: sectors

start=2048, type=82
EOF
then
	:
else
	# Negating the command with ! would destroy its first exit status.
	owned_setup_failed "partition-table-write" "$?"
fi
udevadm settle --timeout=10 >/dev/null 2>&1 || owned_setup_failed "partition-udev-settle" "$?"

partition_count=0
for candidate in "/sys/block/$DISK/"*; do
	[[ -f "$candidate/partition" ]] || continue
	[[ "$(cat "$candidate/partition")" == 1 ]] ||
		fail "unexpected owned null_blk partition number"
	partition_count=$((partition_count + 1))
	PART_SYSFS="$candidate"
done
[[ "$partition_count" == 1 && -n "$PART_SYSFS" ]] ||
	blocked "owned null_blk did not expose exactly one partition"
PART_NAME="$(basename "$PART_SYSFS")"
PARTITION="/dev/$PART_NAME"
PART_DEVNO="$(cat "$PART_SYSFS/dev")"
[[ "$PART_DEVNO" =~ ^[0-9]+:[0-9]+$ ]] ||
	fail "owned null_blk partition sysfs major/minor is malformed"
for ignored in {1..50}; do
	[[ -b "$PARTITION" ]] && break
	sleep 0.1
done
[[ -b "$PARTITION" ]] ||
	blocked "owned null_blk partition node is unavailable"
PARTITION_NODE_DEVNO="$(block_node_devno "$PARTITION")" ||
	fail "cannot resolve owned null_blk partition node identity"
[[ "$PARTITION_NODE_DEVNO" == "$PART_DEVNO" ]] ||
	fail "owned null_blk partition node major/minor differs from sysfs"
[[ "$(readlink -f "/sys/dev/block/$PART_DEVNO")" == "$(readlink -f "$PART_SYSFS")" ]] ||
	fail "owned partition sysfs identity changed"

PARTUUID="$(blkid -s PARTUUID -o value "$PARTITION" | tr 'A-F' 'a-f')"
[[ "$PARTUUID" =~ ^[0-9a-f-]{8,64}$ ]] ||
	blocked "kernel did not expose a valid owned partition PARTUUID"
grep -Fxq "PARTUUID=$PARTUUID" "$PART_SYSFS/uevent" ||
	fail "owned partition sysfs PARTUUID disagrees with blkid"
BY_PARTUUID="/dev/disk/by-partuuid/$PARTUUID"

udev_alias_verified() {
	local alias_dev partition_dev udev_properties devlinks published_link
	local -a published_links
	[[ -b "$BY_PARTUUID" ]] || return 1
	alias_dev="$(block_node_devno "$BY_PARTUUID")" || return 1
	partition_dev="$(block_node_devno "$PARTITION")" || return 1
	[[ "$alias_dev" == "$PART_DEVNO" &&
	   "$partition_dev" == "$PART_DEVNO" ]] || return 1
	[[ "$(readlink -f "$BY_PARTUUID")" == "$(readlink -f "$PARTITION")" ]] ||
		return 1
	udev_properties="$(udevadm info --query=property --path="$PART_SYSFS" 2>/dev/null)" ||
		return 1
	# Exact whitespace-delimited DEVLINKS token only. A similarly prefixed
	# link or a different udev property cannot claim this partition alias.
	devlinks="$(printf '%s\n' "$udev_properties" | sed -n 's/^DEVLINKS=//p')" ||
		return 1
	[[ -n "$devlinks" && "$devlinks" != *$'\n'* ]] || return 1
	read -r -a published_links <<< "$devlinks"
	for published_link in "${published_links[@]}"; do
		[[ "$published_link" == "$BY_PARTUUID" ]] && return 0
	done
	return 1
}

# The host's standard persistent-storage rules intentionally exclude nullb*
# device names. Trigger those rules first; if they do not publish this exact
# partition alias, add a temporary exact-DEVPATH rule. Udev must create and
# record the alias used by the production coordinator; the shell never
# fabricates the symlink.
udevadm trigger --action=add --subsystem-match=block "$PART_SYSFS" >/dev/null 2>&1 ||
	owned_setup_failed "partition-udev-trigger" "$?"
udevadm settle --timeout=10 >/dev/null 2>&1 ||
	owned_setup_failed "partition-udev-add-settle" "$?"
for ignored in {1..20}; do
	if [[ -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ]]; then
		break
	fi
	udevadm settle --timeout=1 >/dev/null 2>&1 || true
	sleep 0.1
done

if [[ ! -e "$BY_PARTUUID" && ! -L "$BY_PARTUUID" ]]; then
	[[ -d /run/udev && ! -L /run/udev ]] ||
		blocked "udev runtime directory is unavailable for the owned fixture rule"
	if [[ ! -d "$UDEV_RULES_DIR" ]]; then
		install -d -m 0755 -- "$UDEV_RULES_DIR" >/dev/null 2>&1 ||
			owned_setup_failed "udev-rules-directory-create" "$?"
		UDEV_RULES_DIR_CREATED=1
	fi
	[[ -d "$UDEV_RULES_DIR" && ! -L "$UDEV_RULES_DIR" ]] ||
		blocked "temporary udev rules directory identity is invalid"
	UDEV_RULE="$UDEV_RULES_DIR/99-swapz-owned-nullblk-$TOKEN.rules"
	[[ ! -e "$UDEV_RULE" && ! -L "$UDEV_RULE" ]] ||
		blocked "temporary udev rule path already exists"
	PART_SYSFS_REAL="$(readlink -f "$PART_SYSFS")"
	[[ "$PART_SYSFS_REAL" == "/sys/devices/virtual/block/$DISK/$PART_NAME" ]] ||
		fail "owned null_blk partition sysfs path changed"
	UDEV_DEVPATH="${PART_SYSFS_REAL#/sys}"
	# Udev evaluates a rule's match keys before its assignments, so the
	# imported partition UUID must be matched in a following rule.
	printf -v UDEV_RULE_CONTENT \
		'ACTION=="add", SUBSYSTEM=="block", DEVPATH=="%s", IMPORT{builtin}="blkid"\nACTION=="add", SUBSYSTEM=="block", DEVPATH=="%s", ENV{ID_PART_ENTRY_UUID}=="%s", SYMLINK+="disk/by-partuuid/$env{ID_PART_ENTRY_UUID}"' \
		"$UDEV_DEVPATH" "$UDEV_DEVPATH" "$PARTUUID"
	if ! (
		set -o noclobber
		printf '%s\n' "$UDEV_RULE_CONTENT" > "$UDEV_RULE"
	); then
		blocked "cannot create the exact owned-null_blk udev rule"
	fi
	UDEV_RULE_CREATED=1
	chmod 0644 "$UDEV_RULE" >/dev/null 2>&1 || owned_setup_failed "udev-rule-chmod" "$?"
	udevadm control --reload-rules >/dev/null 2>&1 ||
		owned_setup_failed "udev-rule-reload" "$?"
	udevadm trigger --action=add --subsystem-match=block "$PART_SYSFS" >/dev/null 2>&1 ||
		owned_setup_failed "udev-rule-trigger" "$?"
	udevadm settle --timeout=10 >/dev/null 2>&1 ||
		owned_setup_failed "udev-rule-settle" "$?"
	for ignored in {1..50}; do
		udev_alias_verified && break
		udevadm settle --timeout=1 >/dev/null 2>&1 || true
		sleep 0.1
	done
fi

if [[ -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ]]; then
	udev_alias_verified || fail "by-PARTUUID alias is not udev-recorded for the owned partition"
else
	# Preserve raw udev evidence only in the private root-owned run directory.
	# The outer redirect also masks failure to open that private diagnostic.
	if (
		{
			if [[ -n "$UDEV_RULE" && -f "$UDEV_RULE" && ! -L "$UDEV_RULE" ]]; then
				sed -n '1p' "$UDEV_RULE" >&2
			fi
			udevadm info --query=property --path="$PART_SYSFS" 2>/dev/null |
				grep -E '^(DEVPATH|DEVTYPE|ID_PART_ENTRY_UUID|DEVLINKS)=' >&2 || true
			udevadm test --verbose --action=add "$PART_SYSFS" 2>&1 |
				grep -E "$UDEV_RULE|$UDEV_DEVPATH|$PARTUUID|by-partuuid|[Ee]rror|[Ff]ailed|Invalid" >&2 || true
		} > "$EVIDENCE_BASE/udev-alias-diagnostic.log" 2>&1
	) 2>/dev/null; then
		note "UDEV_PARTUUID_DIAGNOSTIC=private"
	else
		note "UDEV_PARTUUID_DIAGNOSTIC=unavailable"
	fi
	RETAIN_PRIVATE_EVIDENCE=1
	blocked "phase=udev-alias-publication original_errno=unavailable expected=owned-recorded-alias observed=publication-unproven ownership=claimed next=inspect-private-evidence"
fi

mkswap "$PARTITION" >/dev/null ||
	fail "cannot initialize original swap header on owned RAM partition"
blockdev --flushbufs "$PARTITION" ||
	fail "cannot flush owned RAM partition header"
printf 'PARTUUID=%s\n' "$PARTUUID" > "$CONFIG_BASE/primary-target"
chmod 0600 "$CONFIG_BASE/primary-target"

note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare"
if ! prepare_output="$(timeout --signal=TERM --kill-after=10s 90s \
	"$CONTROL" primary prepare 2>&1)"; then
	verify_prepare_failure_diagnostic "$prepare_output"
	prepare_plan="$(timeout --signal=TERM --kill-after=10s 90s \
		"$CONTROL" primary plan 2>&1)" || true
	if [[ -n "$prepare_plan" ]]; then
		# Plan JSON can include private device paths and unrelated host swap.
		note "PRIMARY_PREPARE_DIAGNOSTIC_PLAN=available"
	else
		note "PRIMARY_PREPARE_DIAGNOSTIC_PLAN=unavailable"
	fi
	if [[ "$prepare_output" != *" claim=retained target_unchanged=true"* ]]; then
		blocked "production coordinator prepare refused before owner claim"
	fi
	fail "production coordinator prepare failed after owner claim"
fi
printf '%s\n' "$prepare_output"
RUN_ID="$(printf '%s\n' "$prepare_output" |
	sed -n 's/^PRIMARY_PREPARE=READY run_id=\([0-9a-f]\{32\}\).*/\1/p')"
[[ "$RUN_ID" =~ ^[0-9a-f]{32}$ ]] ||
	fail "prepare did not emit one valid run ID"
[[ -f "$RECOVERY_BASE/consumed-$RUN_ID.json" &&
   -f "$RECOVERY_BASE/primary-manifest-$RUN_ID.txt" ]] ||
	fail "prepare did not persist consumed provenance and immutable manifest"

note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=start"
if ! start_output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary start 2>&1)"; then
	printf '%s\n' "$start_output" >&2
	fail "production coordinator start failed on owned null_blk"
fi
printf '%s\n' "$start_output"
start_run="$(printf '%s\n' "$start_output" |
	sed -n 's/^PRIMARY_START=ACTIVE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
[[ "$start_run" == "$RUN_ID" ]] || fail "start run ID differs from prepared run"
grep -Fq 'swapon=true' <<< "$start_output" ||
	fail "start did not report native swap activation"
[[ -f "$RECOVERY_BASE/primary-module-load-$RUN_ID.json" ]] ||
	fail "module-load WAL is missing after start"
grep -Fq "\"run_id\":\"$RUN_ID\"" "$RECOVERY_BASE/primary-module-load-$RUN_ID.json" &&
	grep -Fq '"phase":"LOADED"' "$RECOVERY_BASE/primary-module-load-$RUN_ID.json" ||
	fail "module-load WAL does not prove the exact loaded run"

mapper_uuid="$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null | tr -d '[:space:]')" ||
	fail "cannot inspect manager-created mapper"
[[ "$mapper_uuid" == "SWAPZ-PRIMARY-$RUN_ID" ]] ||
	fail "manager-created mapper UUID is not run-bound"
mapper_table="$(dmsetup table "$DMNAME")" || fail "cannot inspect manager-created mapper table"
read -r table_start table_sectors table_target table_lower table_rest <<< "$mapper_table"
[[ "$table_start" == 0 && "$table_target" == swapz && "$table_lower" == "$PART_DEVNO" ]] ||
	fail "manager-created mapper does not target the owned partition"

# Independently verify the published node against Device Mapper control
# identity, then parse every /proc/swaps path without treating missing aliases
# as absent swap. An unrelated host swap entry must remain byte-identical.
assert_exact_owned_mapper 1
mapper_dev="$(dmsetup info -c --noheadings --separator ':' -o major,minor \
	"$DMNAME" 2>/dev/null | tr -d '[:space:]')" ||
	fail "cannot inspect manager-created mapper device number"
[[ "$mapper_dev" =~ ^[0-9]+:[0-9]+$ ]] ||
	fail "manager-created mapper device number is malformed"
mapper_hex="$(stat -Lc '%t:%T' "/dev/mapper/$DMNAME")" ||
	fail "cannot stat manager-created mapper"
IFS=: read -r mapper_major_hex mapper_minor_hex <<< "$mapper_hex"
printf -v mapper_node_dev '%d:%d' "0x$mapper_major_hex" "0x$mapper_minor_hex"
[[ "$mapper_node_dev" == "$mapper_dev" ]] ||
	fail "published mapper node identity differs from Device Mapper control"
active_mapper_entries="$(mapper_swap_entry_count)" ||
	fail "cannot resolve every /proc/swaps device identity after start"
[[ "$active_mapper_entries" == 1 ]] ||
	fail "manager-created mapper is not the unique active swap identity"
assert_lifecycle_state "$RUN_ID" ACTIVE null ||
	fail "start did not persist exact durable ACTIVE transaction"
assert_owned_transaction_records 1 ||
	fail "start did not retain canonical run-bound consumed/active ownership"
assert_unrelated_host_swap_identity "normal start"
active_backing_header_sha256="$(block0_sha256 "$PARTITION")" ||
	fail "cannot hash run-bound SWZ backing header before stop"

note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=stop"
if ! stop_output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary stop 2>&1)"; then
	printf '%s\n' "$stop_output" >&2
	fail "production coordinator stop failed on owned null_blk"
fi
printf '%s\n' "$stop_output"
stop_run="$(printf '%s\n' "$stop_output" |
	sed -n 's/^PRIMARY_STOP=COMPLETE run_id=\([0-9a-f]\{32\}\).*/\1/p')"
[[ "$stop_run" == "$RUN_ID" ]] || fail "stop run ID differs from prepared run"
[[ ! -d /sys/module/dm_swapz ]] || fail "stop left dm_swapz loaded"
mapper_absence_proven ||
	fail "stop left swapz-primary mapper present"
[[ ! -e "$RECOVERY_BASE/partition-$PARTUUID.active" ]] ||
	fail "stop left the active owner marker"
[[ -f "$RECOVERY_BASE/consumed-$RUN_ID.json" ]] ||
	fail "stop removed permanent consumed provenance"

if ! python3 - "$RECOVERY_BASE/primary-state.json" "$RUN_ID" <<'PY'
import json
import sys
state = json.load(open(sys.argv[1], "r", encoding="utf-8"))
if state.get("run_id") != sys.argv[2] or state.get("stage") != "COMPLETE":
    raise SystemExit(1)
if state.get("recovery_previous_stage") not in (None, ""):
    raise SystemExit(1)
PY
then
	fail "durable lifecycle state is not clean COMPLETE"
fi

SWAPS_ID_AFTER="$(swapz_swap_inventory_identity /proc/swaps)" ||
	fail "cannot resnapshot host swap identity"
[[ "$SWAPS_ID_AFTER" == "$SWAPS_ID_BEFORE" ]] ||
	fail "host swap identity differs after normal lifecycle teardown"
stopped_backing_header_sha256="$(block0_sha256 "$PARTITION")" ||
	fail "cannot hash run-bound SWZ backing header after stop"
[[ "$stopped_backing_header_sha256" == "$active_backing_header_sha256" ]] ||
	fail "normal stop changed the run-bound SWZ backing header"

note "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=run_id:$RUN_ID partuuid:$PARTUUID device:$PART_DEVNO prepare:READY start:ACTIVE swapon:true stop:COMPLETE recovery_required:false"

for phase in start-starting start-header-written start-module-inserted \
	start-module-loaded start-mapper-inactive start-mapper-resumed \
	start-mkswap start-swapon; do
	prepare_interruption_run
	note "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase run_id:$RUN_ID"
	interrupt_lifecycle start "$phase" STARTING
	case "$phase" in
		start-starting|start-header-written)
			recover_interruption_run "$phase" STARTING false false false
			;;
		start-module-inserted|start-module-loaded)
			recover_interruption_run "$phase" STARTING false false true
			;;
		start-mapper-inactive|start-mapper-resumed|start-mkswap)
			recover_interruption_run "$phase" STARTING false true true
			;;
		start-swapon)
			recover_interruption_run "$phase" STARTING true true true
			;;
	esac
	note "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase"
done

for phase in stop-stopping stop-swapoff stop-mapper-removed stop-module-unloaded stop-restored; do
	prepare_interruption_run
	start_interruption_baseline
	note "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase run_id:$RUN_ID"
	if [[ "$phase" == stop-restored ]]; then
		interrupt_lifecycle stop "$phase" RESTORED
	else
		interrupt_lifecycle stop "$phase" STOPPING
	fi
	case "$phase" in
		stop-stopping)
			recover_interruption_run "$phase" STOPPING true true true
			;;
		stop-swapoff)
			recover_interruption_run "$phase" STOPPING false true true
			;;
		stop-mapper-removed)
			recover_interruption_run "$phase" STOPPING false false true
			;;
		stop-module-unloaded)
			recover_interruption_run "$phase" STOPPING false false false
			;;
		stop-restored)
			recover_interruption_run "$phase" RESTORED false false false
			;;
	esac
	note "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase"
done

for phase in recover-recovering recover-swapoff recover-mapper-removed \
	recover-module-unloaded recover-restored; do
	prepare_interruption_run
	# Enter recovery from the hardest ordinary crash shape: STARTING with the
	# exact run-bound mapper already active as swap.
	interrupt_lifecycle start start-swapon STARTING
	note "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase run_id:$RUN_ID"
	if [[ "$phase" == recover-restored ]]; then
		interrupt_lifecycle recover "$phase" RESTORED STARTING
	else
		interrupt_lifecycle recover "$phase" RECOVERING STARTING
	fi
	case "$phase" in
		recover-recovering)
			recover_interruption_run "$phase" STARTING true true true
			;;
		recover-swapoff)
			recover_interruption_run "$phase" STARTING false true true
			;;
		recover-mapper-removed)
			recover_interruption_run "$phase" STARTING false false true
			;;
		recover-module-unloaded|recover-restored)
			recover_interruption_run "$phase" STARTING false false false
			;;
	esac
	note "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase"
done

note "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18 fresh_process:true host_swap_identity:preserved repeat_recovery:safe"

# These cases mutate only the private process boundary or an inactive run-owned
# mapper/state record. Every destructive mapper operation is a normal removal
# after independent inactive/no-user proof; uncertainty falls into quarantine.
run_ambiguous_swapon_applied
run_faulted_start_failure swapon-eintr-noeffect 0
run_faulted_start_failure swapon-eio-noeffect 0
run_faulted_start_failure post-swapon-inventory-eio 1
run_ambiguous_swapoff_applied
run_faulted_stop_failure swapoff-eintr-noeffect 1
run_faulted_stop_failure swapoff-eio-noeffect 1
run_faulted_stop_failure swapoff-ebusy-noeffect 1
run_faulted_stop_failure post-swapoff-inventory-eio 0
run_failed_fsync_case
run_stale_run_id_case
run_lost_state_provenance_case
run_wrong_mapper_identity_case

note "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:13 ambiguous_syscall:true inventory_failure:true definite_io_error:true wrong_mapper:true failed_swapoff:true stale_run:true fsync_failure:true lost_provenance:true repeat_recovery:safe host_swap_identity:preserved"
