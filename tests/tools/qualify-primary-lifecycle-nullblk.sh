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
blocked() {
	printf 'BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: %s\n' "$*" >&2
	exit 2
}
note() {
	printf '%s\n' "$*"
}

if [[ $# -ne 2 || $1 != --validated-source ]]; then
	blocked "expected --validated-source <40-hex-sha>"
fi
SOURCE_HEAD="$2"
[[ "$SOURCE_HEAD" =~ ^[0-9a-f]{40}$ ]] ||
	blocked "validated source is malformed"
(( EUID == 0 )) || blocked "owned-nullblk lifecycle rehearsal requires root"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] ||
	blocked "production primary lifecycle admission currently requires Linux x86_64"

for command in cc dmsetup modprobe mountpoint mount blockdev sfdisk udevadm \
	blkid mkswap sha256sum python3 timeout stat findmnt awk sed grep install od \
	tr cut basename readlink rm rmdir ls sleep cat chmod; do
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
CONFIG=
UDEV_RULE=
UDEV_RULE_CONTENT=
CONFIGNAME=
DISK=
LOWER=
PART_SYSFS=
PARTITION=
PARTUUID=
PART_DEVNO=
BY_PARTUUID=
RUN_ID=

[[ ! -e "$TEST_BASE" && ! -L "$TEST_BASE" ]] ||
	blocked "fresh owned-nullblk lifecycle evidence path already exists"
[[ ! -d /sys/module/dm_swapz ]] ||
	blocked "dm_swapz is already loaded before lifecycle rehearsal"
if dmsetup info "$DMNAME" >/dev/null 2>&1; then
	blocked "swapz-primary already exists before lifecycle rehearsal"
fi
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
	local mapper_uuid mapper_table
	local table_start table_sectors table_target table_lower table_rest

	if [[ "$expected_present" == 0 ]]; then
		! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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
}

unrelated_swap_inventory_identity() {
	local mapper_device=""
	if dmsetup info "$DMNAME" >/dev/null 2>&1; then
		mapper_device="$(dmsetup info -c --noheadings --separator ':' \
			-o major,minor "$DMNAME" 2>/dev/null | tr -d '[:space:]')" ||
			return 1
		[[ "$mapper_device" =~ ^[0-9]+:[0-9]+$ ]] || return 1
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

	if ! output="$("$CONTROL" primary prepare 2>&1)"; then
		printf '%s\n' "$output" >&2
		fail "interruption prepare failed"
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
		recover-mapper-removed)
			expected_module=1; expected_mapper=0; expected_swap=0
			;;
		recover-module-unloaded|recover-restored)
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
	! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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
	output="$(timeout --signal=TERM --kill-after=10s 90s "$CONTROL" primary recover 2>&1)"
	rc=$?
	set -e
	printf '%s\n' "$output"
	[[ "$rc" -ne 0 ]] ||
		fail "repeated recovery after $phase unexpectedly reopened COMPLETE"
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
	! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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
	! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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
	! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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

	if [[ -x "$CONTROL" ]]; then
		stage="$(state_stage 2>/dev/null)"
		if dmsetup info "$DMNAME" >/dev/null 2>&1 ||
		   [[ -d /sys/module/dm_swapz ]] ||
		   [[ "$stage" == STARTING || "$stage" == ACTIVE ||
		      "$stage" == STOPPING || "$stage" == RECOVERY_REQUIRED ||
		      "$stage" == RECOVERING || "$stage" == RESTORED ]]; then
			note "RECOVER_PRIMARY_NULLBLK_LIFECYCLE=attempt stage=$stage"
			if ! timeout --signal=TERM --kill-after=10s 60s \
				"$CONTROL" primary recover >/dev/null 2>&1; then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=recovery_failed"
			fi
		fi
	fi

	if dmsetup info "$DMNAME" >/dev/null 2>&1 || [[ -d /sys/module/dm_swapz ]]; then
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
import sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as state_file:
        state = json.load(state_file)
    previous = state.get("recovery_previous_stage")
    if previous not in (None, "STARTING", "STOPPING"):
        raise ValueError("invalid recovery provenance")
    previous_token = "null" if previous is None else '"' + previous + '"'
    canonical_bytes = (
        '{"schema":"swapz-primary-state-v1","run_id":"' +
        sys.argv[2] + '","stage":"COMPLETE",'
        '"recovery_previous_stage":' + previous_token + '}\n'
    ).encode("ascii")
    with open(sys.argv[1], "rb") as state_file:
        actual_bytes = state_file.read()
    valid = (state.get("run_id") == sys.argv[2] and
             state.get("stage") == "COMPLETE" and
             actual_bytes == canonical_bytes)
except (OSError, ValueError, TypeError, AttributeError):
    valid = False
raise SystemExit(0 if valid else 1)
PY
			then
				QUARANTINE=1
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=unfinished_or_ambiguous_durable_state"
			fi
		elif compgen -G "$RECOVERY_BASE/consumed-*.json" >/dev/null; then
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
		if [[ ! "$CONFIGNAME" =~ ^nullb-swapz-[a-f0-9]{16}$ ||
		      "$CONFIG" != "$CONFIGFS/$CONFIGNAME" ||
		      ! -d "$CONFIG" || -L "$CONFIG" ]]; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=config_identity_uncertain"
		else
			echo 0 > "$CONFIG/power" 2>/dev/null || QUARANTINE=1
			rmdir -- "$CONFIG" 2>/dev/null || QUARANTINE=1
			(( QUARANTINE )) &&
				note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=nullblk_cleanup_failed"
		fi
	fi

	if (( OWN_NULL )) && (( ! QUARANTINE )); then
		udevadm settle --timeout=10 >/dev/null 2>&1 || QUARANTINE=1
		if [[ -n "$BY_PARTUUID" &&
		      ( -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ) ]]; then
			QUARANTINE=1
			note "QUARANTINED_PRIMARY_NULLBLK_LIFECYCLE=udev_alias_remains_after_device_removal"
		fi
	fi

	if (( UDEV_RULE_CREATED )); then
		if (( QUARANTINE )); then
			note "RETAINED_PRIMARY_NULLBLK_UDEV_RULE=$UDEV_RULE"
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

	if (( TEST_BASE_CREATED )) && (( ! QUARANTINE )); then
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

	if (( QUARANTINE )); then
		note "PRIMARY_NULLBLK_LIFECYCLE_EVIDENCE_RETAINED=$TEST_BASE config=$CONFIG"
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
from pathlib import Path
import hashlib
machine = Path("/etc/machine-id").read_text(encoding="ascii").strip().lower()
if len(machine) != 32 or any(c not in "0123456789abcdef" for c in machine):
    raise SystemExit(2)
print(hashlib.sha256(b"swapz-host\0" + machine.encode("ascii")).hexdigest())
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
        "architecture": "x86_64",
        "id_sha256": os.environ["HOST_SHA"],
    },
    "source_sha": os.environ["SOURCE_HEAD"],
    "tested_commit_sha": os.environ["SOURCE_HEAD"],
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
mkdir -- "$CONFIG" || blocked "cannot allocate owned null_blk config"
OWN_NULL=1
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
[[ "$(blockdev --getsize64 "$LOWER")" == $((NULLBLK_SIZE_MIB * 1024 * 1024)) ]] ||
	fail "owned null_blk size differs from requested RAM geometry"
[[ -z "$(ls -A "/sys/block/$DISK/holders")" ]] ||
	fail "owned null_blk unexpectedly has holders"

DISK_ID="$(printf '%s' "$TOKEN" | cut -c1-8)"
[[ "$DISK_ID" != 00000000 ]] || DISK_ID=1a2b3c4d
if ! sfdisk --lock --wipe always "$LOWER" >/dev/null <<EOF
label: dos
label-id: 0x$DISK_ID
unit: sectors

start=2048, type=82
EOF
then
	blocked "cannot create partition table on owned RAM null_blk"
fi
udevadm settle --timeout=10 || blocked "udev did not settle owned null_blk partition"

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
for ignored in {1..50}; do
	[[ -b "$PARTITION" ]] && break
	sleep 0.1
done
[[ -b "$PARTITION" && "$PART_DEVNO" =~ ^[0-9]+:[0-9]+$ ]] ||
	blocked "owned null_blk partition node is unavailable"
[[ "$(readlink -f "/sys/dev/block/$PART_DEVNO")" == "$(readlink -f "$PART_SYSFS")" ]] ||
	fail "owned partition sysfs identity changed"

PARTUUID="$(blkid -s PARTUUID -o value "$PARTITION" | tr 'A-F' 'a-f')"
[[ "$PARTUUID" =~ ^[0-9a-f-]{8,64}$ ]] ||
	blocked "kernel did not expose a valid owned partition PARTUUID"
grep -Fxq "PARTUUID=$PARTUUID" "$PART_SYSFS/uevent" ||
	fail "owned partition sysfs PARTUUID disagrees with blkid"
BY_PARTUUID="/dev/disk/by-partuuid/$PARTUUID"

udev_alias_verified() {
	local alias_dev partition_dev udev_properties
	[[ -b "$BY_PARTUUID" ]] || return 1
	alias_dev="$(stat -Lc '%t:%T' "$BY_PARTUUID")" || return 1
	partition_dev="$(stat -Lc '%t:%T' "$PARTITION")" || return 1
	[[ "$alias_dev" == "$partition_dev" ]] || return 1
	[[ "$(readlink -f "$BY_PARTUUID")" == "$(readlink -f "$PARTITION")" ]] ||
		return 1
	udev_properties="$(udevadm info --query=property --path="$PART_SYSFS" 2>/dev/null)" ||
		return 1
	printf '%s\n' "$udev_properties" | grep -F 'DEVLINKS=' |
		grep -Fq -- "$BY_PARTUUID"
}

# The host's standard persistent-storage rules intentionally exclude nullb*
# device names. Trigger those rules first; if they do not publish this exact
# partition alias, add a temporary exact-DEVPATH rule. Udev must create and
# record the alias used by the production coordinator; the shell never
# fabricates the symlink.
udevadm trigger --action=add --subsystem-match=block "$PART_SYSFS" ||
	blocked "cannot trigger udev for the owned null_blk partition"
udevadm settle --timeout=10 ||
	blocked "udev did not settle the owned null_blk partition add event"
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
		install -d -m 0755 -- "$UDEV_RULES_DIR" ||
			blocked "cannot create the temporary udev rules directory"
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
	chmod 0644 "$UDEV_RULE" || blocked "cannot set temporary udev rule mode"
	udevadm control --reload-rules ||
		blocked "udev did not reload the temporary owned-null_blk rule"
	udevadm trigger --action=add --subsystem-match=block "$PART_SYSFS" ||
		blocked "cannot retrigger udev for the owned null_blk partition"
	udevadm settle --timeout=10 ||
		blocked "udev did not settle the exact owned-nullblk rule"
	for ignored in {1..50}; do
		udev_alias_verified && break
		udevadm settle --timeout=1 >/dev/null 2>&1 || true
		sleep 0.1
	done
fi

if [[ -e "$BY_PARTUUID" || -L "$BY_PARTUUID" ]]; then
	udev_alias_verified || fail "by-PARTUUID alias is not udev-recorded for the owned partition"
else
	note "UDEV_PARTUUID_DIAGNOSTIC=devpath:$UDEV_DEVPATH partuuid:$PARTUUID rule:$UDEV_RULE"
	if [[ -n "$UDEV_RULE" && -f "$UDEV_RULE" && ! -L "$UDEV_RULE" ]]; then
		sed -n '1p' "$UDEV_RULE" >&2
	fi
	udevadm info --query=property --path="$PART_SYSFS" 2>/dev/null |
		grep -E '^(DEVPATH|DEVTYPE|ID_PART_ENTRY_UUID|DEVLINKS)=' >&2 || true
	udevadm test --verbose --action=add "$PART_SYSFS" 2>&1 |
		grep -E "$UDEV_RULE|$UDEV_DEVPATH|$PARTUUID|by-partuuid|[Ee]rror|[Ff]ailed|Invalid" >&2 || true
	blocked "udev did not publish the owned partition by-PARTUUID node"
fi

mkswap "$PARTITION" >/dev/null ||
	fail "cannot initialize original swap header on owned RAM partition"
blockdev --flushbufs "$PARTITION" ||
	fail "cannot flush owned RAM partition header"
printf 'PARTUUID=%s\n' "$PARTUUID" > "$CONFIG_BASE/primary-target"
chmod 0600 "$CONFIG_BASE/primary-target"

note "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare"
if ! prepare_output="$("$CONTROL" primary prepare 2>&1)"; then
	printf '%s\n' "$prepare_output" >&2
	if prepare_plan="$("$CONTROL" primary plan 2>&1)"; then
		note "PRIMARY_PREPARE_DIAGNOSTIC_PLAN=$prepare_plan"
	else
		note "PRIMARY_PREPARE_DIAGNOSTIC_PLAN=unavailable"
	fi
	fail "production coordinator prepare failed on owned null_blk"
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

mapper_hex="$(stat -Lc '%t:%T' "/dev/mapper/$DMNAME")" ||
	fail "cannot stat manager-created mapper"
IFS=: read -r mapper_major_hex mapper_minor_hex <<< "$mapper_hex"
printf -v mapper_dev '%d:%d' "0x$mapper_major_hex" "0x$mapper_minor_hex"
active_mapper_entries=0
while read -r swap_path swap_type swap_size swap_used swap_priority; do
	[[ "$swap_path" == Filename || ! -e "$swap_path" ]] && continue
	[[ -b "$swap_path" ]] || continue
	swap_hex="$(stat -Lc '%t:%T' "$swap_path")" || fail "cannot stat active swap entry"
	IFS=: read -r swap_major_hex swap_minor_hex <<< "$swap_hex"
	printf -v swap_dev '%d:%d' "0x$swap_major_hex" "0x$swap_minor_hex"
	[[ "$swap_dev" != "$mapper_dev" ]] ||
		active_mapper_entries=$((active_mapper_entries + 1))
done < /proc/swaps
[[ "$active_mapper_entries" == 1 ]] ||
	fail "manager-created mapper is not the unique active swap identity"

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
! dmsetup info "$DMNAME" >/dev/null 2>&1 ||
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

for phase in stop-stopping stop-swapoff; do
	prepare_interruption_run
	start_interruption_baseline
	note "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=$phase run_id:$RUN_ID"
	interrupt_lifecycle stop "$phase" STOPPING
	if [[ "$phase" == stop-stopping ]]; then
		recover_interruption_run "$phase" STOPPING true true true
	else
		recover_interruption_run "$phase" STOPPING false true true
	fi
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

note "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:15 fresh_process:true host_swap_identity:preserved repeat_recovery:safe"

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
