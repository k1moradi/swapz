#!/usr/bin/env bash
# Ephemeral deployment of the exact V3 module onto a NEW, RAM-backed null_blk.
# NEVER alter current swap, unrelated DM mappings or physical storage.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
MODULE="$ROOT/build/kernel/experimental/dm-swapz.ko"
ORACLE="$ROOT/build/tests/device-roundtrip"
CONFIG=""
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
           findmnt mountpoint mount timeout sha256sum cmp od awk grep tr; do
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
[[ ! -e /sys/module/dm_swapz ]] ||
	fail "another dm_swapz module already loaded; do not touch it"
[[ -r /proc/swaps ]] || fail "cannot audit host swap"
mkdir -p "$ROOT/build/deploy"
SESSION="$(mktemp -d "$ROOT/build/deploy/session.XXXXXXXX")"
exec > >(tee -a "$SESSION/session.log") 2>&1
note "SOURCE_HEAD=$(git rev-parse HEAD)"
note "RUNNING_KERNEL=$(uname -r)"
note "MODULE_SHA256=$(sha256sum "$MODULE")"
note "HOST_SWAPS_BEFORE:"
cat /proc/swaps
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
		elif [[ -n "$LOWER" && -d "$CONFIG" && -d "/sys/block/${LOWER##*/}/holders" ]] &&
		     [[ "$(cat "$CONFIG/memory_backed" 2>/dev/null)" == 1 ]] &&
		     [[ -z "$(ls -A "/sys/block/${LOWER##*/}/holders" 2>/dev/null)" ]]; then
			echo 0 > "$CONFIG/power" && rmdir "$CONFIG" ||
				{ note "QUARANTINED: cannot safely delete owned null_blk"; QUARANTINE=1; }
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
	cat /proc/swaps
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
CONFIG="$CFGBASE/swapz$TOKEN"
DMNAME="swapz-demo-$TOKEN"
UUID="SWAPZ-TEST-$TOKEN"
[[ ! -e "$CONFIG" && ! -e "/dev/mapper/$DMNAME" ]] ||
	fail "unique test identity already exists"
mkdir "$CONFIG" || fail "cannot create owned null_blk"
OWN_NULL=1
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
[[ "$INDEX" =~ ^[0-9]+$ ]] || fail "invalid owned null_blk index"
LOWER="/dev/nullb$INDEX"
for i in {1..50}; do
	[[ -b "$LOWER" && -r "/sys/block/nullb$INDEX/dev" ]] && break
	sleep 0.1
done
[[ -b "$LOWER" ]] || fail "owned lower block node did not appear"
DEVNO="$(cat "/sys/block/nullb$INDEX/dev")"
[[ "$(readlink -f "/sys/dev/block/$DEVNO")" == "$(readlink -f "/sys/block/nullb$INDEX")" ]] ||
	fail "lower devno does not match configfs index"
[[ "$(blockdev --getsize64 "$LOWER")" == 67108864 ]] ||
	fail "RAM lower is not exactly 64MiB"
[[ -z "$(ls -A "/sys/block/nullb$INDEX/holders")" ]] ||
	fail "new RAM lower has unexpected holders"
[[ -z "$(findmnt -rn -S "$LOWER")" ]] || fail "new RAM lower mounted"
if awk -v d="$LOWER" 'NR>1 && $1==d {f=1} END{exit !f}' /proc/swaps; then
	fail "new RAM lower already active as swap"
fi
note "OWNED_RAM_LOWER=$LOWER DEVICE=$DEVNO UUID=$UUID"
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
dmsetup deps -o devname "$DMNAME" | grep -Fq "nullb$INDEX" ||
	fail "DM dependency does not match owned RAM lower"
for i in {1..50}; do
	[[ -b "/dev/mapper/$DMNAME" ]] && break
	sleep 0.1
done
[[ -b "/dev/mapper/$DMNAME" ]] || fail "test-only DM device node absent"
note "TARGET_STATUS_BEFORE=$(dmsetup status "$DMNAME")"
timeout --signal=TERM --kill-after=5s 40s "$ORACLE" "/dev/mapper/$DMNAME" ||
	fail "loaded test roundtrip failed or timed out"
note "TARGET_STATUS_AFTER=$(dmsetup status "$DMNAME")"
note "LOWER_STATS=$(cat "/sys/block/nullb$INDEX/stat")"
