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

[[ -r build/source-build-info.h &&
   -r build/kernel/experimental/dm-swapz.ko &&
   -x build/tests/device-roundtrip ]] ||
	blocked "exact-source module/oracle/build provenance artifacts are unavailable"
grep -Fxq "#define SWAPZ_BUILD_SOURCE_SHA \"$SOURCE_HEAD\"" \
	build/source-build-info.h ||
	blocked "generated build provenance does not match validated source"
grep -Fxq '#define SWAPZ_BUILD_SOURCE_CLEAN 1' build/source-build-info.h ||
	blocked "generated build provenance is not clean"

TEST_BASE=/var/lib/swapz-primary-owned-nullblk-test
CONFIG_BASE="$TEST_BASE/config"
RECOVERY_BASE="$TEST_BASE/recovery"
PREFIX="$TEST_BASE/prefix"
CONTROL="$PREFIX/sbin/swapzctl"
REPORT="$RECOVERY_BASE/qualification.json"
CONFIGFS=/sys/kernel/config/nullb
DMNAME=swapz-primary
NULLBLK_SIZE_MIB=256
OWN_NULL=0
TEST_BASE_CREATED=0
QUARANTINE=0
CONFIG=
CONFIGNAME=
DISK=
LOWER=
PART_SYSFS=
PARTITION=
PARTUUID=
PART_DEVNO=
RUN_ID=

[[ ! -e "$TEST_BASE" && ! -L "$TEST_BASE" ]] ||
	blocked "prior owned-nullblk lifecycle evidence exists at $TEST_BASE"
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

	if (( TEST_BASE_CREATED )) && (( ! QUARANTINE )); then
		if [[ "$TEST_BASE" != /var/lib/swapz-primary-owned-nullblk-test ||
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

install -d -m 0700 "$TEST_BASE" "$CONFIG_BASE" "$RECOVERY_BASE" \
	"$PREFIX" "$PREFIX/sbin" "$PREFIX/libexec" "$PREFIX/libexec/swapz"
TEST_BASE_CREATED=1

VERSION="$(cat src/kernel/VERSION)"
cc -std=c11 -O2 -g -Wall -Wextra -Werror \
	-include build/source-build-info.h \
	"-DSWAPZ_VERSION=\"$VERSION\"" \
	-DSWAPZ_PRIMARY_OWNED_NULLBLK_TEST=1 \
	"-DSWAPZ_PRIMARY_TEST_CONFIG_BASE=\"$CONFIG_BASE\"" \
	"-DSWAPZ_PRIMARY_TEST_RECOVERY_BASE=\"$RECOVERY_BASE\"" \
	"-DSWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT=\"$REPORT\"" \
	src/userspace/swapzctl.c src/userspace/swapz-primary.c -o "$CONTROL" ||
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

TOKEN="$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')"
[[ "$TOKEN" =~ ^[a-f0-9]{16}$ ]] || fail "cannot generate null_blk ownership token"
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
if ! sfdisk --wipe always "$LOWER" >/dev/null <<EOF
label: dos
label-id: 0x$DISK_ID
unit: sectors

start=2048, type=82
EOF
then
	blocked "cannot create partition table on owned RAM null_blk"
fi
blockdev --rereadpt "$LOWER" ||
	blocked "kernel refused owned null_blk partition-table reread"
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
for ignored in {1..50}; do
	[[ -b "$BY_PARTUUID" ]] && break
	udevadm settle --timeout=1 >/dev/null 2>&1 || true
	sleep 0.1
done
[[ -b "$BY_PARTUUID" ]] ||
	blocked "udev did not publish the owned partition by-PARTUUID node"
[[ "$(stat -Lc '%t:%T' "$BY_PARTUUID")" == "$(stat -Lc '%t:%T' "$PARTITION")" ]] ||
	fail "by-PARTUUID alias does not name the owned partition"

mkswap --no-discard "$PARTITION" >/dev/null ||
	fail "cannot initialize original swap header on owned RAM partition"
blockdev --flushbufs "$PARTITION" ||
	fail "cannot flush owned RAM partition header"
printf 'PARTUUID=%s\n' "$PARTUUID" > "$CONFIG_BASE/primary-target"
chmod 0600 "$CONFIG_BASE/primary-target"

if ! prepare_output="$("$CONTROL" primary prepare 2>&1)"; then
	printf '%s\n' "$prepare_output" >&2
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
