#!/usr/bin/env bash
# Ephemeral deployment of the exact swapz module onto a NEW, RAM-backed null_blk.
# NEVER alter current swap, unrelated DM mappings or physical storage.
set -Eeuo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
source "$ROOT/tests/tools/nullblk-identity.sh"
source "$ROOT/tests/tools/quiet-lower-io.sh"
source "$ROOT/tests/tools/swap-inventory.sh"
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
SUSPENDED=0
fail() { echo "BLOCKED: $*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
for cmd in git insmod rmmod modprobe dmsetup modinfo blockdev readlink \
           findmnt mountpoint mount timeout sha256sum cmp od awk grep tr \
           tee mktemp ls sleep cat id rmdir stat sort dd; do
	command -v "$cmd" >/dev/null || fail "missing required tool $cmd"
done
[[ $(id -u) == 0 ]] || fail "sudo is required for isolated module loading"
[[ $(git branch --show-current) == main ]] || fail "work only on main"
git diff --quiet && git diff --cached --quiet ||
	fail "dirty tracked source: preserve and commit changes first"
version="$(cat src/kernel/VERSION)"
[[ "$version" =~ ^3[.]0[.]0-alpha[.][0-9]+$ ]] ||
    fail "malformed canonical swapz version"
grep -Fxq "#define SWAPZ_ALPHA_VERSION \"$version\"" build/kernel/experimental/swapz-version.h ||
    fail "staged kernel version header does not match canonical VERSION"
[[ "$(modinfo -F version "$MODULE")" == "$version" ]] ||
    fail "built swapz module version does not match canonical VERSION"
[[ -s "$MODULE" && -x "$ORACLE" ]] || fail "swapz/oracle not compiled"
[[ $(modinfo -F vermagic "$MODULE" | awk '{print $1}') == "$(uname -r)" ]] ||
	fail "swapz vermagic does not match running kernel"
for file in Makefile dm-target.c codec.c authority.c engine.c codec.h \
	    authority.h engine.h flush-qual.h gc-cost.h; do
	cmp -s "src/kernel/$file" "build/kernel/experimental/$file" ||
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
SWAPS_ID_BEFORE="$(printf '%s
' "$SWAPS_BEFORE" |
    swapz_swap_inventory_identity /dev/stdin)" ||
    fail "cannot parse initial host swap identity"
note "HOST_SWAPS_BEFORE:"
printf '%s\n' "$SWAPS_BEFORE"
cleanup() {
	local rc=$? current_id
	trap - EXIT HUP INT TERM
	set +e
	# Inventory changes could make the owned mapper/lower host swap.
	# Quarantine BEFORE teardown; ordinary Used fluctuations are safe.
	if ! current_id="$(swapz_swap_inventory_identity /proc/swaps)" ||
	   [[ "$current_id" != "$SWAPS_ID_BEFORE" ]]; then
		QUARANTINE=1
		note "QUARANTINED: host swap identity changed before teardown"
	fi
	if (( OWN_DM && SUSPENDED && !QUARANTINE )); then
		if [[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" 2>/dev/null |
		          tr -d '[:space:]')" == "$UUID" ]] &&
		   dmsetup resume "$DMNAME" >/dev/null 2>&1; then
			SUSPENDED=0
		else
			note "QUARANTINED: suspended owned mapping could not resume"
			QUARANTINE=1
		fi
	fi
	if (( OWN_DM && !QUARANTINE )); then
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
	if ! current_id="$(printf '%s
' "$swaps_after" |
	        swapz_swap_inventory_identity /dev/stdin)" ||
	   [[ "$current_id" != "$SWAPS_ID_BEFORE" ]]; then
		note "FAIL: system swap identity changed during isolated run"
		rc=1
		QUARANTINE=1
	fi
	if (( QUARANTINE )); then
		note "BLOCKED: resource retained, never forced; log $SESSION/session.log"
		exit 1
	fi
	if (( rc == 0 )); then
		note "PASS: loaded isolated swapz byte-exact I/O, clean teardown"
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
insmod "$MODULE" || fail "swapz kernel module rejected"
OWN_MODULE=1
dmsetup targets | grep -Eq '^swapz[[:space:]]' ||
	fail "swapz target registration missing"
# 16 MiB upper table; current constructor arguments, no injected errors.
dmsetup create "$DMNAME" --uuid "$UUID" \
	--table "0 32768 swapz $LOWER 0 64 1 2 0 1 0" ||
	fail "test-only DM mapping creation failed"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
	fail "owned DM UUID mismatch"
dmsetup table "$DMNAME" | grep -Eq '^0 32768 swapz ' ||
	fail "DM table unexpected"
dmsetup deps -o devname "$DMNAME" | grep -Fq "$DISK" ||
	fail "DM dependency does not match owned RAM lower"
for i in {1..50}; do
	[[ -b "/dev/mapper/$DMNAME" ]] && break
	sleep 0.1
done
[[ -b "/dev/mapper/$DMNAME" ]] || fail "test-only DM device node absent"
# The target status and independent backing counters are not atomic.
# Require two unchanging paired samples around the oracle; this does
# NOT excuse external traffic during the oracle or weaken equality.
# Null_blk stat: read requests [0], 512B sectors [2], write [4]/[6].
if command -v udevadm >/dev/null 2>&1; then
    udevadm settle --timeout=10 ||
        fail "udev queue did not settle before owned oracle"
fi
swapz_capture_quiescent_io "$DMNAME" "/sys/block/$DISK/stat" 12 0.2 ||
    fail "target/backing not quiescent before oracle"
status_before="$SWAPZ_QUIET_STATUS"
lower_before=("${SWAPZ_QUIET_LOWER[@]}")
note "QUIESCENT_BEFORE=attempt:$SWAPZ_QUIET_ATTEMPTS"
note "TARGET_STATUS_BEFORE=$status_before"
note "LOWER_STATS_BEFORE=${lower_before[*]}"
timeout --signal=TERM --kill-after=5s 40s "$ORACLE" "/dev/mapper/$DMNAME" ||
    fail "loaded test roundtrip failed or timed out"
swapz_capture_quiescent_io "$DMNAME" "/sys/block/$DISK/stat" 12 0.2 ||
    fail "target/backing not quiescent after oracle"
status_after="$SWAPZ_QUIET_STATUS"
lower_after=("${SWAPZ_QUIET_LOWER[@]}")
note "QUIESCENT_AFTER=attempt:$SWAPZ_QUIET_ATTEMPTS"
note "TARGET_STATUS_AFTER=$status_after"
note "LOWER_STATS=${lower_after[*]}"

# Exact-zero write savings must appear BOTH in swapz's completed media
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
    fail "independent lower write sectors disagree with swapz"
# Alpha.9 diagnostic conservation: every *nonempty* swapz write window
# increments exactly one primary closing reason. Never sum GC pressure
# encounters or admission coalescing into this independent invariant.
close_total=0
for close_reason in close_unknown close_full close_duplicate close_zero \
                    close_fua close_raw close_read_conflict \
                    close_read_unrelated close_discard close_preflush \
                    close_quantum close_idle close_deadline close_pack_ready close_shutdown close_other; do
    close_delta="$(status_delta "$close_reason")"
    (( close_total += close_delta )) || true
done
window_delta="$(status_delta windows)"
(( close_total == window_delta )) ||
    fail "window close reasons disagree with actual swapz windows: reasons=$close_total windows=$window_delta"
note "PASS_WINDOW_CLOSE_REASONS=windows:$window_delta accounted:$close_total gc_pressure:$(status_delta window_gc_pressure)"
age_total="$(( $(status_delta age_le100us) + $(status_delta age_101_1000us) + $(status_delta age_gt1000us) ))"
(( age_total == window_delta )) ||
    fail "window age bins disagree with actual swapz windows: ages=$age_total windows=$window_delta"
note "PASS_WINDOW_OPEN_AGE=windows:$window_delta bins:$age_total sum_ns:$(status_delta age_sum_ns) max_ns:$(status_delta age_max_ns)"
if (( lower_read_bytes != target_read_bytes )); then
    # Lower disk stats include readers outside swapz; do not assume that an
    # 8KiB excess is an innocent probe or allow a hidden tolerance.
    note "UNATTRIBUTED_LOWER_READ=target_bytes:$target_read_bytes lower_bytes:$lower_read_bytes extra_bytes:$((lower_read_bytes-target_read_bytes)) target_reqs:$target_read_reqs lower_reqs:$lower_read_reqs"
    fail "independent lower read sectors disagree with swapz"
fi
(( target_write_reqs > 0 && lower_write_reqs > 0 &&
   target_read_reqs > 0 && lower_read_reqs > 0 )) ||
    fail "expected oracle lower read/write requests missing"
# Front-end dm_io calls need not equal lower queue requests after splits or
# merges, so report each read/write request pair instead of assuming equality.
note "PASS_ZERO_WRITE_LOWER_IO=logical_bytes:$logical_writes zero_pages:$zero_writes target_write_bytes:$target_write_bytes lower_write_bytes:$lower_write_bytes target_write_reqs:$target_write_reqs lower_write_reqs:$lower_write_reqs"
note "PASS_ORACLE_LOWER_READ=target_read_bytes:$target_read_bytes lower_read_bytes:$lower_read_bytes target_read_reqs:$target_read_reqs lower_read_reqs:$lower_read_reqs"

# Make the oracle's existing RAW and explicit barrier coverage a loaded
# contract instead of relying on the fixture shape implicitly.
raw_writes="$(status_delta raw)"
flush_calls="$(status_delta flush_calls)"
flush_ok="$(status_delta flush_ok)"
flush_err="$(status_delta flush_err)"
flush_injected="$(status_delta flush_injected)"
(( raw_writes == 64 )) ||
    fail "loaded oracle RAW fallback count changed: $raw_writes (expected 64)"
(( flush_calls >= 2 && flush_ok == flush_calls &&
   flush_err == 0 && flush_injected == 0 )) ||
    fail "loaded oracle flush/barrier accounting changed"
note "PASS_LOADED_ORACLE_PROFILE=raw_pages:$raw_writes zero_pages:$zero_writes flush_calls:$flush_calls"

# Force real loaded GC before lifecycle/fault phases. Recreate authority on
# the same positively identified RAM lower, then write five complete logical
# generations while preserving one old survivor per 1MiB logical stripe.
# With 64MiB physical backing and two reserve segments this must create live
# victims rather than qualifying only dead-segment reuse.
note "START_LOADED_LIVE_GC"
dmsetup remove "$DMNAME" || fail "cannot remove ordinary owned mapping before GC phase"
OWN_DM=0
UUID="SWAPZ-TEST-$TOKEN-gc"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 0 2 0 1 0 2" ||
    fail "cannot create live-GC qualification mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "live-GC DM UUID mismatch"
gc_before="$(dmsetup status "$DMNAME")"
timeout --signal=TERM --kill-after=5s 90s "$ORACLE" \
    "/dev/mapper/$DMNAME" --gc-stress 5 ||
    fail "loaded live-GC stress or byte-exact verification failed"
gc_after="$(dmsetup status "$DMNAME")"
gc_victims="$(status_u64 "$gc_after" gc_victims)" ||
    fail "live-GC status lacks victim count"
gc_rotations="$(status_u64 "$gc_after" gc_role_rotations)" ||
    fail "live-GC status lacks role rotations"
gc_pages="$(status_u64 "$gc_after" gc_pages)" ||
    fail "live-GC status lacks relocated page count"
gc_read="$(status_u64 "$gc_after" gc_read)" ||
    fail "live-GC status lacks read bytes"
gc_write="$(status_u64 "$gc_after" gc_write)" ||
    fail "live-GC status lacks write bytes"
gc_read_reqs="$(status_u64 "$gc_after" gc_read_reqs)" ||
    fail "live-GC status lacks read requests"
gc_write_reqs="$(status_u64 "$gc_after" gc_write_reqs)" ||
    fail "live-GC status lacks write requests"
gc_victim="$(status_u64 "$gc_after" last_gc_victim)" ||
    fail "live-GC status lacks last victim"
gc_destination="$(status_u64 "$gc_after" last_gc_destination)" ||
    fail "live-GC status lacks last destination"
(( $(status_u64 "$gc_after" failed) == 0 &&
   gc_victims >= 2 && gc_rotations == gc_victims &&
   gc_pages > 0 && gc_read > 0 && gc_write > 0 &&
   gc_read_reqs > 0 && gc_write_reqs > 0 &&
   gc_victim != gc_destination )) ||
    fail "loaded live-GC did not prove repeated live evacuation and rotation"
note "PASS_LOADED_LIVE_GC=victims:$gc_victims rotations:$gc_rotations pages:$gc_pages read_bytes:$gc_read write_bytes:$gc_write read_reqs:$gc_read_reqs write_reqs:$gc_write_reqs last:$gc_victim->$gc_destination verified_pages:4096"
dmsetup remove "$DMNAME" || fail "cannot remove live-GC qualification mapping"
OWN_DM=0

# Retained lifecycle qualification. Use the maximum already-supported
# retention interval only to make the drain-path race observable; the real
# performance policy remains owner-qualified retain_ms=2. The private writer
# deliberately omits O_SYNC/FUA so a successful timer arm can represent a
# genuinely retained upper write.
note "START_LOADED_SUSPEND_DRAIN"
UUID="SWAPZ-TEST-$TOKEN-suspend"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 1 2 0 1 0 4" ||
    fail "cannot create retained suspend mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "retained suspend DM UUID mismatch"
suspend_before="$(dmsetup status "$DMNAME")"
(( $(status_u64 "$suspend_before" retain_ms) == 4 &&
   $(status_u64 "$suspend_before" failed) == 0 )) ||
    fail "retained suspend mapping policy mismatch"
# Start the sampler before the writer. Learned singleton fast-close can make
# later writes complete immediately, so qualification must observe one of the
# initial full-retention opportunities instead of racing process startup.
lifecycle_probe="$SESSION/retained-open-probe"
: >"$lifecycle_probe"
(
    for i in {1..400}; do
        lifecycle_status="$(dmsetup status "$DMNAME")" || exit 2
        timer_arms="$(status_u64 "$lifecycle_status" retain_timer_arms)" || exit 3
        lifecycle_windows="$(status_u64 "$lifecycle_status" windows)" || exit 4
        if (( timer_arms > lifecycle_windows )); then
            printf 'OPEN\n' >"$lifecycle_probe"
            exit 0
        fi
    done
    exit 1
) &
probe_pid=$!
timeout --signal=TERM --kill-after=2s 15s "$ORACLE" \
    "/dev/mapper/$DMNAME" --write-series 128 2 \
    >"$SESSION/suspend-writer.log" 2>&1 &
writer_pid=$!
probe_rc=0
wait "$probe_pid" || probe_rc=$?
open_window=0
if (( probe_rc == 0 )) && [[ $(cat "$lifecycle_probe") == OPEN ]]; then
    open_window=1
fi
if (( !open_window )); then
    wait "$writer_pid" 2>/dev/null || true
    fail "retained lifecycle writer never exposed an open timed window"
fi
timeout --signal=TERM --kill-after=2s 10s dmsetup suspend "$DMNAME" ||
    fail "owned retained mapping did not suspend/drain"
SUSPENDED=1
timeout --signal=TERM --kill-after=2s 10s dmsetup resume "$DMNAME" ||
    fail "owned retained mapping did not resume"
SUSPENDED=0
wait "$writer_pid" || fail "retained lifecycle writer failed across suspend/resume"
timeout --signal=TERM --kill-after=2s 15s "$ORACLE" \
    "/dev/mapper/$DMNAME" --verify-series 128 2 ||
    fail "retained lifecycle bytes changed across suspend/resume"
suspend_after="$(dmsetup status "$DMNAME")"
lifecycle_failed="$(status_u64 "$suspend_after" failed)" ||
    fail "retained lifecycle status lacks fail state"
(( lifecycle_failed == 0 )) ||
    fail "suspend/resume left retained lifecycle target failed"
# The sampled open 4ms window can legally expire between the status command
# and the separate dmsetup suspend process. Do not require a particular close
# reason across that userspace race. The safety contract is that an open
# retained window was observed, suspend/resume completed, every accepted write
# completed exactly once, and all 128 pages verify byte-exact afterwards.
note "PASS_LOADED_SUSPEND_DRAIN=retain_ms:4 observed_open:$open_window verified_pages:128"
dmsetup remove "$DMNAME" || fail "cannot remove retained suspend mapping"
OWN_DM=0

# Retained-policy synthetic WRITE failure qualification. Reuse only this
# already-owned RAM lower, but recreate the DM target so fault counters and
# fail-closed state are isolated from the ordinary byte-exact oracle.
note "START_LOADED_RETAINED_WRITE_FAULT"
UUID="SWAPZ-TEST-$TOKEN-writefault"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 1 2 0 1 1 2" ||
    fail "cannot create retained WRITE-fault mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "retained WRITE-fault DM UUID mismatch"
write_fault_status_before="$(dmsetup status "$DMNAME")"
(( $(status_u64 "$write_fault_status_before" retain_ms) == 2 &&
   $(status_u64 "$write_fault_status_before" write_fault_nth) == 1 &&
   $(status_u64 "$write_fault_status_before" failed) == 0 )) ||
    fail "retained WRITE-fault mapping policy mismatch"
read -r -a write_fault_lower_before < "/sys/block/$DISK/stat"
if timeout --signal=TERM --kill-after=5s 20s dd if=/dev/urandom \
        of="/dev/mapper/$DMNAME" bs=4096 count=1 oflag=direct status=none; then
    fail "synthetic retained WRITE fault unexpectedly completed successfully"
fi
write_fault_status_after="$(dmsetup status "$DMNAME")"
read -r -a write_fault_lower_after < "/sys/block/$DISK/stat"
(( $(status_u64 "$write_fault_status_after" failed) == 1 &&
   $(status_u64 "$write_fault_status_after" write_fault_calls) == 1 &&
   $(status_u64 "$write_fault_status_after" write_fault_injected) == 1 )) ||
    fail "retained WRITE fault did not fail-close exactly once"
(( write_fault_lower_after[4] == write_fault_lower_before[4] &&
   write_fault_lower_after[6] == write_fault_lower_before[6] )) ||
    fail "pre-submission WRITE fault reached the owned lower device"
note "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 lower_write_delta:0"

dmsetup remove "$DMNAME" || fail "cannot remove retained WRITE-fault mapping"
OWN_DM=0

# Retained-policy synthetic FLUSH failure qualification. The data WRITE must
# reach the owned RAM lower first; only the subsequent explicit fsync/PREFLUSH
# is injected. This is not a device-originated or torn-completion test.
note "START_LOADED_RETAINED_FLUSH_FAULT"
UUID="SWAPZ-TEST-$TOKEN-flushfault"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 1 2 1 1 0 2" ||
    fail "cannot create retained FLUSH-fault mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "retained FLUSH-fault DM UUID mismatch"
flush_fault_status_before="$(dmsetup status "$DMNAME")"
(( $(status_u64 "$flush_fault_status_before" retain_ms) == 2 &&
   $(status_u64 "$flush_fault_status_before" flush_fault_nth) == 1 &&
   $(status_u64 "$flush_fault_status_before" failed) == 0 )) ||
    fail "retained FLUSH-fault mapping policy mismatch"
read -r -a flush_fault_lower_before < "/sys/block/$DISK/stat"
if timeout --signal=TERM --kill-after=5s 20s dd if=/dev/urandom \
        of="/dev/mapper/$DMNAME" bs=4096 count=1 oflag=direct conv=fsync status=none; then
    fail "synthetic retained FLUSH fault unexpectedly completed successfully"
fi
flush_fault_status_after="$(dmsetup status "$DMNAME")"
read -r -a flush_fault_lower_after < "/sys/block/$DISK/stat"
(( $(status_u64 "$flush_fault_status_after" failed) == 1 &&
   $(status_u64 "$flush_fault_status_after" flush_injected) == 1 &&
   $(status_u64 "$flush_fault_status_after" flush_err) == 1 &&
   $(status_u64 "$flush_fault_status_after" write_fault_injected) == 0 )) ||
    fail "retained FLUSH fault did not propagate and fail-close"
(( flush_fault_lower_after[6] > flush_fault_lower_before[6] )) ||
    fail "retained FLUSH-fault setup did not first complete a lower data WRITE"
note "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1"

dmsetup remove "$DMNAME" || fail "cannot remove retained FLUSH-fault mapping"
OWN_DM=0
