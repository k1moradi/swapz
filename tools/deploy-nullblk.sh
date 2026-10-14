#!/usr/bin/env bash
# Ephemeral deployment of the exact V3 module onto a NEW, RAM-backed null_blk.
# NEVER alter current swap, unrelated DM mappings or physical storage.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/tools/nullblk-identity.sh"
cd "$ROOT"
MODULE="$ROOT/build/kernel/experimental/dm-swapz.ko"
ORACLE="$ROOT/build/tests/device-roundtrip"
CONFIG=""
CONFIGNAME=""
DISK=""
DEVNO=""
INDEX=""
LOWER=""
DMNAME=""
UUID=""
OWN_NULL=0
OWN_DM=0
OWN_MODULE=0
QUARANTINE=0
fail() { echo "BLOCKED: $*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
for cmd in git insmod rmmod modprobe dmsetup modinfo blockdev readlink \
           findmnt mountpoint mount timeout sha256sum cmp od awk grep tr \
           tee mktemp ls sleep cat id rmdir stat; do
	command -v "$cmd" >/dev/null || fail "missing required tool $cmd"
done
[[ $(id -u) == 0 ]] || fail "sudo is required for isolated module loading"
[[ $(git branch --show-current) == main ]] || fail "work only on main"
git diff --quiet && git diff --cached --quiet ||
	fail "dirty tracked source: preserve and commit changes first"
[[ $(cat kernel/extent-v3/VERSION) == 3.0.0-alpha.7 ]] ||
	fail "unexpected active V3 version"
[[ -s "$MODULE" && -x "$ORACLE" ]] || fail "V3/oracle not compiled"
[[ $(modinfo -F vermagic "$MODULE" | awk '{print $1}') == "$(uname -r)" ]] ||
	fail "V3 vermagic does not match running kernel"
for file in Makefile dm-target.c codec.c authority.c engine.c codec.h \
	    authority.h engine.h flush-qual.h gc-cost.h; do
	cmp -s "kernel/extent-v3/$file" "build/kernel/experimental/$file" ||
		fail "staged module source mismatch: $file"
done
[[ ! -d /sys/module/dm_swapz ]] ||
	fail "another dm_swapz module already loaded; do not touch it"
[[ -r /proc/swaps ]] || fail "cannot audit host swap"
mkdir -p "$ROOT/build/deploy"
SESSION="$(mktemp -d "$ROOT/build/deploy/session.XXXXXXXX")"
exec > >(tee -a "$SESSION/session.log") 2>&1
note "SOURCE_HEAD=$(git rev-parse HEAD)"
note "RUNNING_KERNEL=$(uname -r)"
note "MODULE_SHA256=$(sha256sum "$MODULE")"
SWAPS_BEFORE="$(cat /proc/swaps)"
note "HOST_SWAPS_BEFORE:"
printf '%s\n' "$SWAPS_BEFORE"
cleanup() {
	local rc=$?
	trap - EXIT HUP INT TERM
	set +e
	if (( OWN_DM )); then
		if [[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null | tr -d '[:space:]')" == "$UUID" ]]; then
			dmsetup remove "$DMNAME"
			if [[ $? == 0 ]]; then
				OWN_DM=0
			else
				note "QUARANTINED: owned mapping still busy, not force-removing"
				QUARANTINE=1
			fi
		else
			note "QUARANTINED: mapping UUID changed, no deletion"
			QUARANTINE=1
		fi
	fi
	if (( OWN_NULL )); then
		if (( OWN_DM || QUARANTINE )); then
			note "QUARANTINED: preserving RAM lower for investigation"
		elif [[ "$CONFIGNAME" =~ ^nullb-swapz-[a-f0-9]{16}$ &&
		        "$CONFIG" == "$CFGBASE/$CONFIGNAME" &&
		        -n "$DISK" && -n "$DEVNO" && -n "$INDEX" &&
		        -d "$CONFIG" && -r "$CONFIG/index" &&
		        "$(cat "$CONFIG/index" 2>/dev/null)" == "$INDEX" &&
		        -r "/sys/block/$DISK/dev" &&
		        "$(cat "/sys/block/$DISK/dev" 2>/dev/null)" == "$DEVNO" &&
		        "$(readlink -f "/sys/dev/block/$DEVNO")" == "$(readlink -f "/sys/block/$DISK")" &&
		        "$(cat "$CONFIG/memory_backed" 2>/dev/null)" == 1 &&
		        -d "/sys/block/$DISK/holders" &&
		        -z "$(ls -A "/sys/block/$DISK/holders" 2>/dev/null)" &&
		        -z "$(findmnt -rn -S "$LOWER" 2>/dev/null)" ]]; then
			echo 0 > "$CONFIG/power" && rmdir "$CONFIG" ||
				{ note "QUARANTINED: cannot remove owned null_blk safely"; QUARANTINE=1; }
		else
			note "QUARANTINED: lower identity/holders changed"
			QUARANTINE=1
		fi
	fi
	if (( OWN_MODULE && ! QUARANTINE && ! OWN_DM )); then
		rmmod dm_swapz ||
			{ note "QUARANTINED: test module remains loaded"; QUARANTINE=1; }
	fi
	note "HOST_SWAPS_AFTER:"
	local swaps_after
	swaps_after="$(cat /proc/swaps)"
	printf '%s\n' "$swaps_after"
	if [[ "$swaps_after" != "$SWAPS_BEFORE" ]]; then
		note "FAIL: system swap inventory changed during isolated run"
		rc=1
	fi
	if (( QUARANTINE )); then
		note "BLOCKED: resource retained, never forced; log $SESSION/session.log"
		exit 1
	fi
	if (( rc == 0 )); then
		note "PASS: loaded isolated V3 byte-exact I/O, clean teardown"
	else
		note "FAIL: test exit $rc; safe teardown attempted"
	fi
	note "EVIDENCE=$SESSION/session.log"
	exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! mountpoint -q /sys/kernel/config; then
	modprobe configfs
	mount -t configfs configfs /sys/kernel/config ||
		fail "could not mount configfs"
fi
CFGBASE=/sys/kernel/config/nullb
if [[ ! -d "$CFGBASE" ]]; then
	modprobe null_blk nr_devices=0 || fail "cannot load null_blk"
fi
[[ -d "$CFGBASE" ]] || fail "configfs null_blk support unavailable"
TOKEN="$(od -An -N8 -tx1 /dev/urandom | tr -d '[:space:]')"
[[ "$TOKEN" =~ ^[a-f0-9]{16}$ ]] || fail "bad random test token"
CONFIGNAME="nullb-swapz-$TOKEN"
CONFIG="$CFGBASE/$CONFIGNAME"
DMNAME="swapz-demo-$TOKEN"
UUID="SWAPZ-TEST-$TOKEN"
[[ ! -e "$CONFIG" && ! -e "/dev/mapper/$DMNAME" ]] ||
	fail "unique test identity already exists"
mkdir "$CONFIG" || fail "cannot create owned null_blk"
OWN_NULL=1
note "OWNED_CONFIG=$CONFIG UUID=$UUID"
for attr in size memory_backed blocksize power index; do
	[[ -e "$CONFIG/$attr" ]] || fail "missing configfs attribute $attr"
done
# Linux null_blk configfs size unit is MiB. Never use the module default!
echo 64 > "$CONFIG/size"
echo 4096 > "$CONFIG/blocksize"
echo 1 > "$CONFIG/memory_backed"
echo 1 > "$CONFIG/power"
[[ "$(cat "$CONFIG/memory_backed")" == 1 ]] && [[ "$(cat "$CONFIG/power")" == 1 ]] ||
	fail "RAM backing not active"
INDEX="$(cat "$CONFIG/index")"
[[ "$INDEX" =~ ^(0|[1-9][0-9]*)$ ]] || fail "invalid configfs index"
# New null_blk names the block disk after configfs; old kernels use nullbN.
# Only a disk with EXACT expected name or index is permitted.
for i in {1..50}; do
    DISK="$(swapz_resolve_owned_disk "$CONFIGNAME" "$INDEX" "/sys/block")" && break
    sleep 0.1
done
[[ -n "$DISK" ]] || fail "owned configfs disk missing or ambiguous: $CONFIG index=$INDEX"
DEVNO="$(cat "/sys/block/$DISK/dev")"
[[ "$DEVNO" =~ ^[0-9]+:[0-9]+$ ]] || fail "invalid device identity"
MAJOR="$(printf '%s' "$DEVNO" | cut -d: -f1)"
MINOR="$(printf '%s' "$DEVNO" | cut -d: -f2)"
NULL_MAJOR="$(awk '/^Block devices:/{b=1;next} b && $2=="nullb"{print $1;exit}' /proc/devices)"
[[ -n "$NULL_MAJOR" && "$MAJOR" == "$NULL_MAJOR" && "$MINOR" == "$INDEX" ]] ||
    fail "sysfs device is not owned null_blk index: $DEVNO"
[[ "$(readlink -f "/sys/dev/block/$DEVNO")" == "$(readlink -f "/sys/block/$DISK")" ]] ||
    fail "sysfs major:minor points elsewhere"
LOWER="/dev/$DISK"
for i in {1..50}; do
    [[ -b "$LOWER" ]] && break
    sleep 0.1
done
[[ -b "$LOWER" ]] ||
    fail "udev node $LOWER missing (configfs=$CONFIG dev=$DEVNO); refusing alternate disk"
NODEHEX="$(stat -Lc '%t:%T' "$LOWER")" || fail "cannot stat owned node"
IFS=: read -r HMAJ HMIN <<< "$NODEHEX"
printf -v NODEDEV '%d:%d' "0x$HMAJ" "0x$HMIN"
[[ "$NODEDEV" == "$DEVNO" ]] || fail "block node does not match sysfs"
[[ "$(blockdev --getsize64 "$LOWER")" == 67108864 ]] || fail "RAM lower must be 64MiB"
[[ -d "/sys/block/$DISK/holders" && -z "$(ls -A "/sys/block/$DISK/holders")" ]] ||
    fail "unexpected lower holders"
[[ -z "$(findmnt -rn -S "$LOWER")" ]] || fail "owned RAM lower is mounted"
while read -r SWAP_PATH rest; do
    [[ "$SWAP_PATH" == Filename || ! -e "$SWAP_PATH" ]] && continue
    SWAPHEX="$(stat -Lc '%t:%T' "$SWAP_PATH")" || fail "active swap stat failed"
    IFS=: read -r SMAJ SMIN <<< "$SWAPHEX"
    printf -v SWAPDEV '%d:%d' "0x$SMAJ" "0x$SMIN"
    [[ "$SWAPDEV" != "$DEVNO" ]] || fail "owned lower is active swap"
done < /proc/swaps
note "OWNED_RAM_LOWER=$LOWER CONFIG=$CONFIG DISK=$DISK DEVICE=$DEVNO UUID=$UUID"
modprobe dm_mod || fail "device mapper core unavailable"
insmod "$MODULE" || fail "V3 kernel module rejected"
OWN_MODULE=1
dmsetup targets | grep -Eq '^swapz3[[:space:]]' ||
	fail "V3 target registration missing"
# 16 MiB upper table; 9 constructor arguments, no injected errors.
dmsetup create "$DMNAME" --uuid "$UUID" \
	--table "0 32768 swapz3 $LOWER 0 64 1 2 0 0 1 0" ||
	fail "test-only DM mapping creation failed"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
	fail "owned DM UUID mismatch"
dmsetup table "$DMNAME" | grep -Eq '^0 32768 swapz3 ' ||
	fail "DM table unexpected"
dmsetup deps -o devname "$DMNAME" | grep -Fq "$DISK" ||
	fail "DM dependency does not match owned RAM lower"
for i in {1..50}; do
	[[ -b "/dev/mapper/$DMNAME" ]] && break
	sleep 0.1
done
[[ -b "/dev/mapper/$DMNAME" ]] || fail "test-only DM device node absent"
# Keep the test's independent backing counters from BEFORE the oracle.
# Null_blk stat arrays: read requests [0], 512B read sectors [2],
# write requests [4], and 512B write sectors [6]. The samples bracket
# only the oracle, excluding earlier device probing and setup I/O.
status_before="$(dmsetup status "$DMNAME")"
read -r -a lower_before < "/sys/block/$DISK/stat" ||
    fail "cannot snapshot owned lower before readback"
[[ ${#lower_before[@]} -ge 7 ]] ||
    fail "owned null_blk stat line incomplete"
note "TARGET_STATUS_BEFORE=$status_before"
note "LOWER_STATS_BEFORE=${lower_before[*]}"
timeout --signal=TERM --kill-after=5s 40s "$ORACLE" "/dev/mapper/$DMNAME" ||
	fail "loaded test roundtrip failed or timed out"
status_after="$(dmsetup status "$DMNAME")"
read -r -a lower_after < "/sys/block/$DISK/stat" ||
    fail "cannot snapshot owned lower after readback"
[[ ${#lower_after[@]} -ge 7 ]] ||
    fail "owned null_blk final stat line incomplete"
note "TARGET_STATUS_AFTER=$status_after"
note "LOWER_STATS=${lower_after[*]}"

# Exact-zero write savings must appear BOTH in V3's completed media
# counters and in the separate owned lower-device accounting. Reject
# a future C regression that merely increments a status counter.
# The fixed C oracle submits 128 initial + 64 overwrite pages; of
# those, initial page 0 and eight second-pass pages are ALL zero.
status_u64() {
    local line="$1" key="$2"
    [[ $line =~ (^|[[:space:]])${key}=([0-9]+)($|[[:space:]]) ]] ||
        return 1
    printf '%s\n' "${BASH_REMATCH[2]}"
}
status_delta() {
    local key="$1" before_value after_value
    before_value="$(status_u64 "$status_before" "$key")" ||
        fail "target status missing pre-oracle $key"
    after_value="$(status_u64 "$status_after" "$key")" ||
        fail "target status missing post-oracle $key"
    (( after_value >= before_value )) || fail "target status $key regressed"
    printf '%s\n' "$((after_value - before_value))"
}
logical_writes="$(status_delta logical_write)"
zero_writes="$(status_delta zero_elided)"
target_write_bytes="$(status_delta physical_write)"
target_write_reqs="$(status_delta physical_write_reqs)"
target_read_bytes="$(status_delta physical_read)"
target_read_reqs="$(status_delta physical_read_reqs)"
(( lower_after[0] >= lower_before[0] &&
   lower_after[2] >= lower_before[2] &&
   lower_after[4] >= lower_before[4] &&
   lower_after[6] >= lower_before[6] )) ||
    fail "owned lower stat counters regressed"
lower_read_reqs="$((lower_after[0] - lower_before[0]))"
lower_read_bytes="$(((lower_after[2] - lower_before[2]) * 512))"
lower_write_reqs="$((lower_after[4] - lower_before[4]))"
lower_write_bytes="$(((lower_after[6] - lower_before[6]) * 512))"
(( logical_writes == 192 * 4096 )) ||
    fail "unexpected completed logical work: $logical_writes"
(( zero_writes == 9 )) ||
    fail "zero-write recognition changed: $zero_writes (expected 9)"
(( target_write_bytes <= logical_writes - zero_writes * 4096 )) ||
    fail "zero elisions did not reduce completed lower bytes"
(( lower_write_bytes == target_write_bytes )) ||
    fail "independent lower write sectors disagree with V3"
(( lower_read_bytes == target_read_bytes )) ||
    fail "independent lower read sectors disagree with V3"
(( target_write_reqs > 0 && lower_write_reqs > 0 &&
   target_read_reqs > 0 && lower_read_reqs > 0 )) ||
    fail "expected oracle lower read/write requests missing"
# Front-end dm_io calls need not equal lower queue requests after splits or
# merges, so report each read/write request pair instead of assuming equality.
note "PASS_ZERO_WRITE_LOWER_IO=logical_bytes:$logical_writes zero_pages:$zero_writes target_write_bytes:$target_write_bytes lower_write_bytes:$lower_write_bytes target_write_reqs:$target_write_reqs lower_write_reqs:$lower_write_reqs"
note "PASS_ORACLE_LOWER_READ=target_read_bytes:$target_read_bytes lower_read_bytes:$lower_read_bytes target_read_reqs:$target_read_reqs lower_read_reqs:$lower_read_reqs"
