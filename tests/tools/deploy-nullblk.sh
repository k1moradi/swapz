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
# This script runs as root during loaded qualification. Git source checks are
# read-only; disable optional index refresh/locking so privileged inspection can
# never replace the operator-owned .git/index with a root-owned file.
export GIT_OPTIONAL_LOCKS=0
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
# test_results.json.xz is the one generated, overwriteable evidence file.
# It is not source and may contain the previous run until this run finishes.
git diff --quiet -- . ':(exclude)test_results.json.xz' &&
	git diff --cached --quiet -- . ':(exclude)test_results.json.xz' ||
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
SOURCE_HEAD="${SWAPZ_TESTED_SOURCE_SHA:-$(git rev-parse HEAD)}"
[[ "$SOURCE_HEAD" =~ ^[0-9a-f]{40}$ ]] || fail "invalid tested source revision"
git merge-base --is-ancestor "$SOURCE_HEAD" HEAD >/dev/null 2>&1 &&
    git diff --quiet "$SOURCE_HEAD..HEAD" -- . ':(exclude)test_results.json.xz' ||
    fail "tested source does not match checkout code"
note "SOURCE_HEAD=$SOURCE_HEAD"
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
for attr in size memory_backed blocksize power index queue_mode submit_queues hw_queue_depth discard; do
	[[ -e "$CONFIG/$attr" ]] || fail "missing configfs attribute $attr"
done
# Linux null_blk configfs size unit is MiB. Never use the module default!
echo 64 > "$CONFIG/size"
echo 4096 > "$CONFIG/blocksize"
echo 1 > "$CONFIG/memory_backed"
echo 1 > "$CONFIG/discard"
echo 2 > "$CONFIG/queue_mode"
echo 1 > "$CONFIG/submit_queues"
echo 1 > "$CONFIG/hw_queue_depth"
[[ "$(cat "$CONFIG/queue_mode")" == 2 &&
   "$(cat "$CONFIG/submit_queues")" == 1 &&
   "$(cat "$CONFIG/hw_queue_depth")" == 1 ]] ||
    fail "owned RAM serial queue geometry rejected"
echo 1 > "$CONFIG/power"
[[ "$(cat "$CONFIG/memory_backed")" == 1 &&
   "$(cat "$CONFIG/discard")" == 1 &&
   "$(cat "$CONFIG/power")" == 1 ]] ||
	fail "RAM backing/discard not active"
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
# the same positively identified RAM lower, then write five logical generations
# while cumulatively preserving one page from every prior generation per 1MiB
# logical stripe. With 64MiB physical backing and the authority's four 1MiB
# reserve segments, dead-segment reuse alone cannot satisfy capacity pressure.
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
if ! gc_oracle_output="$(timeout --signal=TERM --kill-after=5s 90s "$ORACLE" \
    "/dev/mapper/$DMNAME" --gc-stress 5 2>&1)"; then
    printf '%s\n' "$gc_oracle_output"
    fail "loaded live-GC stress or byte-exact verification failed"
fi
printf '%s\n' "$gc_oracle_output"
gc_round_count="$(printf '%s\n' "$gc_oracle_output" |
    awk '/^GC_PRESSURE_ROUND=/ { count++ } END { print count + 0 }')"
gc_write_wall_ns="$(printf '%s\n' "$gc_oracle_output" |
    awk '/^GC_PRESSURE_ROUND=/ {
        for (i = 1; i <= NF; ++i)
            if ($i ~ /^write_wall_ns:/) {
                split($i, value, ":"); total += value[2]
            }
    } END { printf "%.0f\n", total + 0 }')"
gc_baseline_p99_ns="$(printf '%s\n' "$gc_oracle_output" |
    awk '/^GC_PRESSURE_ROUND=0 / {
        for (i = 1; i <= NF; ++i)
            if ($i ~ /^write_p99_ns:/) {
                split($i, value, ":"); print value[2]; found = 1
            }
    } END { if (!found) print 0 }')"
gc_pressure_p99_ns="$(printf '%s\n' "$gc_oracle_output" |
    awk '/^GC_PRESSURE_ROUND=[1-9][0-9]* / {
        for (i = 1; i <= NF; ++i)
            if ($i ~ /^write_p99_ns:/) {
                split($i, value, ":")
                if (value[2] + 0 > maximum + 0) maximum = value[2]
            }
    } END { printf "%.0f\n", maximum + 0 }')"
gc_after="$(dmsetup status "$DMNAME")"
gc_victims="$(status_u64 "$gc_after" gc_victims)" ||
    fail "live-GC status lacks victim count"
gc_rotations="$(status_u64 "$gc_after" gc_role_rotations)" ||
    fail "live-GC status lacks role rotations"
gc_distinct="$(status_u64 "$gc_after" gc_distinct_victims)" ||
    fail "live-GC status lacks distinct victim count"
gc_victim_min="$(status_u64 "$gc_after" gc_victim_min_evictions)" ||
    fail "live-GC status lacks victim minimum eviction count"
gc_victim_max="$(status_u64 "$gc_after" gc_victim_max_evictions)" ||
    fail "live-GC status lacks victim maximum eviction count"
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
gc_dead_reuses="$(status_u64 "$gc_after" dead_segment_reuses)" ||
    fail "live-GC status lacks dead-segment reuse count"
gc_no_headroom="$(status_u64 "$gc_after" gc_no_headroom_skips)" ||
    fail "live-GC status lacks no-headroom skip count"
gc_wall_before="$(status_u64 "$gc_before" gc_wall_ns)" ||
    fail "live-GC baseline lacks GC wall"
gc_wall_after="$(status_u64 "$gc_after" gc_wall_ns)" ||
    fail "live-GC status lacks GC wall"
gc_choose_wall_before="$(status_u64 "$gc_before" gc_choose_wall_ns)" ||
    fail "live-GC baseline lacks choose wall"
gc_choose_wall_after="$(status_u64 "$gc_after" gc_choose_wall_ns)" ||
    fail "live-GC status lacks choose wall"
gc_choose_calls_before="$(status_u64 "$gc_before" gc_choose_calls)" ||
    fail "live-GC baseline lacks choose calls"
gc_choose_calls_after="$(status_u64 "$gc_after" gc_choose_calls)" ||
    fail "live-GC status lacks choose calls"
gc_choose_map_before="$(status_u64 "$gc_before" gc_choose_map_entries)" ||
    fail "live-GC baseline lacks choose map entries"
gc_choose_map_after="$(status_u64 "$gc_after" gc_choose_map_entries)" ||
    fail "live-GC status lacks choose map entries"
gc_choose_segment_before="$(status_u64 "$gc_before" gc_choose_segment_entries)" ||
    fail "live-GC baseline lacks choose segment entries"
gc_choose_segment_after="$(status_u64 "$gc_after" gc_choose_segment_entries)" ||
    fail "live-GC status lacks choose segment entries"
gc_relocation_map_before="$(status_u64 "$gc_before" gc_relocation_map_entries)" ||
    fail "live-GC baseline lacks relocation map entries"
gc_relocation_map_after="$(status_u64 "$gc_after" gc_relocation_map_entries)" ||
    fail "live-GC status lacks relocation map entries"
gc_wall_ns=$((gc_wall_after - gc_wall_before))
gc_choose_wall_ns=$((gc_choose_wall_after - gc_choose_wall_before))
gc_choose_calls=$((gc_choose_calls_after - gc_choose_calls_before))
gc_choose_map_entries=$((gc_choose_map_after - gc_choose_map_before))
gc_choose_segment_entries=$((gc_choose_segment_after - gc_choose_segment_before))
gc_relocation_map_entries=$((gc_relocation_map_after - gc_relocation_map_before))
if (( gc_write_wall_ns > 0 )); then
    gc_fraction_ppm=$((gc_wall_ns * 1000000 / gc_write_wall_ns))
else
    gc_fraction_ppm=0
fi
gc_discards_eligible="$(status_u64 "$gc_after" segment_discards_eligible)" ||
    fail "live-GC status lacks discard eligibility count"
gc_discards_issued="$(status_u64 "$gc_after" segment_discards_issued)" ||
    fail "live-GC status lacks discard issued count"
gc_discards_completed="$(status_u64 "$gc_after" segment_discards_completed)" ||
    fail "live-GC status lacks discard completion count"
gc_discards_unsupported="$(status_u64 "$gc_after" segment_discards_unsupported)" ||
    fail "live-GC status lacks discard unsupported count"
gc_discards_failed="$(status_u64 "$gc_after" segment_discards_failed)" ||
    fail "live-GC status lacks discard failure count"
gc_discard_sectors="$(status_u64 "$gc_after" segment_discard_sectors)" ||
    fail "live-GC status lacks discard sector count"
gc_discard_skipped="$(status_u64 "$gc_after" segment_discards_skipped_already_trimmed)" ||
    fail "live-GC status lacks duplicate-discard skip count"
alignment_hole_fg="$(status_u64 "$gc_after" alignment_hole_blocks_foreground)" ||
    fail "live-GC status lacks foreground alignment-hole count"
alignment_hole_gc="$(status_u64 "$gc_after" alignment_hole_blocks_gc)" ||
    fail "live-GC status lacks GC alignment-hole count"
tail_waste_fg="$(status_u64 "$gc_after" segment_tail_waste_blocks_foreground)" ||
    fail "live-GC status lacks foreground segment-tail waste"
tail_waste_gc="$(status_u64 "$gc_after" segment_tail_waste_blocks_gc)" ||
    fail "live-GC status lacks GC segment-tail waste"
run_splits_by_hole="$(status_u64 "$gc_after" run_splits_by_hole)" ||
    fail "live-GC status lacks hole-split count"
alloc_probe_segments="$(status_u64 "$gc_after" alloc_probe_segments)" ||
    fail "live-GC status lacks allocator-probe segment count"
alloc_probe_full_scans="$(status_u64 "$gc_after" alloc_probe_full_scans)" ||
    fail "live-GC status lacks allocator full-scan count"
alloc_probe_wall_ns="$(status_u64 "$gc_after" alloc_probe_wall_ns)" ||
    fail "live-GC status lacks allocator-probe wall time"
segment_program_min="$(status_u64 "$gc_after" segment_program_min)" ||
    fail "live-GC status lacks segment-open minimum"
segment_program_sum="$(status_u64 "$gc_after" segment_program_sum)" ||
    fail "live-GC status lacks segment-open sum"
segment_program_max="$(status_u64 "$gc_after" segment_program_max)" ||
    fail "live-GC status lacks segment-open maximum"
segment_program_segments="$(status_u64 "$gc_after" segment_program_segments)" ||
    fail "live-GC status lacks segment-open population"
note "LIVE_GC_EVIDENCE=victims:$gc_victims rotations:$gc_rotations distinct:$gc_distinct victim_min:$gc_victim_min victim_max:$gc_victim_max pages:$gc_pages read_reqs:$gc_read_reqs write_reqs:$gc_write_reqs dead_reuses:$gc_dead_reuses no_headroom:$gc_no_headroom last:$gc_victim->$gc_destination"
note "LIVE_GC_PRESSURE=rounds:$gc_round_count write_wall_ns:$gc_write_wall_ns baseline_p99_ns:$gc_baseline_p99_ns pressure_p99_ns:$gc_pressure_p99_ns gc_wall_ns:$gc_wall_ns gc_fraction_ppm:$gc_fraction_ppm choose_wall_ns:$gc_choose_wall_ns choose_calls:$gc_choose_calls choose_map_entries:$gc_choose_map_entries choose_segment_entries:$gc_choose_segment_entries relocation_map_entries:$gc_relocation_map_entries no_headroom_skips:$gc_no_headroom"
(( $(status_u64 "$gc_after" failed) == 0 &&
   gc_victims >= 2 && gc_rotations == gc_victims &&
   gc_distinct >= 3 && gc_victim_min > 0 &&
   gc_victim_max >= gc_victim_min && gc_victim_max <= gc_victims &&
   gc_pages > 0 && gc_read > 0 && gc_write > 0 &&
   gc_read_reqs > 0 && gc_write_reqs > 0 &&
   gc_victim != gc_destination &&
   gc_discards_eligible >= gc_victims &&
   gc_discards_issued == gc_discards_completed &&
   gc_discards_completed >= gc_victims &&
   gc_discards_unsupported == 0 && gc_discards_failed == 0 &&
   gc_discard_sectors == gc_discards_completed * 2048 &&
   gc_round_count == 5 && gc_write_wall_ns > 0 &&
   gc_baseline_p99_ns > 0 && gc_pressure_p99_ns > 0 &&
   gc_wall_ns > 0 && gc_choose_wall_ns > 0 &&
   gc_choose_calls >= gc_victims &&
   gc_choose_map_entries == 0 &&
   gc_choose_segment_entries > 0 &&
   gc_relocation_map_entries == gc_pages &&
   tail_waste_fg <= alignment_hole_fg &&
   tail_waste_gc <= alignment_hole_gc &&
   alloc_probe_segments > 0 &&
   alloc_probe_full_scans > 0 &&
   alloc_probe_full_scans <= alloc_probe_segments &&
   segment_program_segments > 0 &&
   segment_program_min <= segment_program_max &&
   segment_program_sum >= segment_program_max &&
   gc_discard_skipped <= gc_discards_eligible )) ||
    fail "loaded live-GC did not prove repeated distributed live evacuation and rotation"
note "PASS_LOADED_LIVE_GC=victims:$gc_victims rotations:$gc_rotations pages:$gc_pages read_bytes:$gc_read write_bytes:$gc_write read_reqs:$gc_read_reqs write_reqs:$gc_write_reqs distinct:$gc_distinct victim_min:$gc_victim_min victim_max:$gc_victim_max last:$gc_victim->$gc_destination discards:$gc_discards_completed discard_sectors:$gc_discard_sectors discard_unsupported:$gc_discards_unsupported discard_failed:$gc_discards_failed verified_pages:4096"
note "PASS_LOADED_GC_PRESSURE=rounds:$gc_round_count write_wall_ns:$gc_write_wall_ns baseline_p99_ns:$gc_baseline_p99_ns pressure_p99_ns:$gc_pressure_p99_ns gc_wall_ns:$gc_wall_ns gc_fraction_ppm:$gc_fraction_ppm choose_wall_ns:$gc_choose_wall_ns choose_calls:$gc_choose_calls choose_map_entries:$gc_choose_map_entries choose_segment_entries:$gc_choose_segment_entries relocation_map_entries:$gc_relocation_map_entries no_headroom_skips:$gc_no_headroom alignment_hole_fg:$alignment_hole_fg alignment_hole_gc:$alignment_hole_gc tail_waste_fg:$tail_waste_fg tail_waste_gc:$tail_waste_gc run_splits_by_hole:$run_splits_by_hole alloc_probe_segments:$alloc_probe_segments alloc_probe_full_scans:$alloc_probe_full_scans alloc_probe_wall_ns:$alloc_probe_wall_ns trim_skipped:$gc_discard_skipped segment_program_min:$segment_program_min segment_program_sum:$segment_program_sum segment_program_max:$segment_program_max segment_program_segments:$segment_program_segments"
dmsetup remove "$DMNAME" || fail "cannot remove live-GC qualification mapping"
OWN_DM=0

# ID70c: upper DISCARD is already serialized by the ordered worker. Prove that
# invalidating the final mapping in a CLOSED 1MiB segment immediately issues
# one lower whole-segment TRIM, then prove later allocator reuse observes
# ID70a's successful-TRIM state and skips a duplicate pre-write DISCARD.
note "START_LOADED_DISCARD_TRIM"
UUID="SWAPZ-TEST-$TOKEN-discardtrim"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 1 2 0 1 0" ||
    fail "cannot create discard-time TRIM mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "discard-time TRIM DM UUID mismatch"
timeout --signal=TERM --kill-after=5s 30s "$ORACLE" \
    "/dev/mapper/$DMNAME" --raw-write-series 257 0 ||
    fail "discard-time TRIM setup write failed"
trim_before="$(dmsetup status "$DMNAME")"
trim_completed_before="$(status_u64 "$trim_before" segment_discards_completed)" ||
    fail "discard-time TRIM status lacks completion count"
trim_sectors_before="$(status_u64 "$trim_before" segment_discard_sectors)" ||
    fail "discard-time TRIM status lacks sector count"
trim_skips_before="$(status_u64 "$trim_before" segment_discards_skipped_already_trimmed)" ||
    fail "discard-time TRIM status lacks duplicate-skip count"
discard_pages_before="$(status_u64 "$trim_before" discarded)" ||
    fail "discard-time TRIM status lacks upper discard count"
timeout --signal=TERM --kill-after=5s 20s "$ORACLE" \
    "/dev/mapper/$DMNAME" --discard-pages 0 256 ||
    fail "owned upper DISCARD failed"
trim_after_discard="$(dmsetup status "$DMNAME")"
trim_completed_after="$(status_u64 "$trim_after_discard" segment_discards_completed)" ||
    fail "discard-time TRIM post-discard completion count missing"
trim_sectors_after="$(status_u64 "$trim_after_discard" segment_discard_sectors)" ||
    fail "discard-time TRIM post-discard sector count missing"
trim_skips_after="$(status_u64 "$trim_after_discard" segment_discards_skipped_already_trimmed)" ||
    fail "discard-time TRIM post-discard skip count missing"
discard_pages_after="$(status_u64 "$trim_after_discard" discarded)" ||
    fail "discard-time TRIM post-discard upper count missing"
(( trim_completed_after - trim_completed_before == 1 &&
   trim_sectors_after - trim_sectors_before == 2048 &&
   trim_skips_after == trim_skips_before &&
   discard_pages_after - discard_pages_before == 256 &&
   $(status_u64 "$trim_after_discard" failed) == 0 )) ||
    fail "upper DISCARD did not immediately reclaim exactly one closed segment"
for trim_round in 1 2 3 4; do
    timeout --signal=TERM --kill-after=5s 60s "$ORACLE" \
        "/dev/mapper/$DMNAME" --raw-write-series 4096 "$trim_round" ||
        fail "discard-time TRIM reuse round failed"
done
timeout --signal=TERM --kill-after=5s 60s "$ORACLE" \
    "/dev/mapper/$DMNAME" --raw-verify-series 4096 4 ||
    fail "discard-time TRIM reuse verification failed"
trim_after_reuse="$(dmsetup status "$DMNAME")"
trim_skips_reuse="$(status_u64 "$trim_after_reuse" segment_discards_skipped_already_trimmed)" ||
    fail "discard-time TRIM reuse skip count missing"
trim_reuse_delta=$((trim_skips_reuse - trim_skips_after))
(( trim_reuse_delta >= 1 && $(status_u64 "$trim_after_reuse" failed) == 0 )) ||
    fail "later allocator reuse did not suppress prior discard-time TRIM"
note "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:$trim_reuse_delta verified_pages:4096"
dmsetup remove "$DMNAME" || fail "cannot remove discard-time TRIM mapping"
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
# Launch the bounded private writer first, then sample for exactly as long as
# that writer remains alive. A fixed poll count can exhaust before the child is
# scheduled and falsely miss the first 4ms retained window. Poll without sleep
# so adaptive singleton fast-close cannot hide the initial full-retention
# opportunity; timer_arms > windows still proves a window is open NOW rather
# than merely proving historical timer activity.
lifecycle_probe="$SESSION/retained-open-probe"
: >"$lifecycle_probe"
timeout --signal=TERM --kill-after=2s 15s "$ORACLE" \
    "/dev/mapper/$DMNAME" --write-series 128 2 \
    >"$SESSION/suspend-writer.log" 2>&1 &
writer_pid=$!
(
    while kill -0 "$writer_pid" 2>/dev/null; do
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

# ID69 remains an opt-in evidence arm. Reload only the already-owned module
# with packed placement enabled, then run the byte-exact mixed smoke on the
# same owned RAM lower. The full benchmark matrix continues to use default=0.
rmmod dm_swapz || fail "cannot reload swapz for packed-placement smoke"
OWN_MODULE=0
insmod "$MODULE" packed_placement=1 ||
    fail "swapz packed-placement module arm rejected"
OWN_MODULE=1
note "START_LOADED_PACKED_PLACEMENT"
UUID="SWAPZ-TEST-$TOKEN-packed"
dmsetup create "$DMNAME" --uuid "$UUID" \
    --table "0 32768 swapz $LOWER 0 64 1 2 0 1 0" ||
    fail "cannot create packed-placement mapping"
OWN_DM=1
[[ "$(dmsetup info -c --noheadings -o uuid "$DMNAME" | tr -d '[:space:]')" == "$UUID" ]] ||
    fail "packed-placement DM UUID mismatch"
packed_before="$(dmsetup status "$DMNAME")"
(( $(status_u64 "$packed_before" packed_placement) == 1 &&
   $(status_u64 "$packed_before" failed) == 0 )) ||
    fail "packed-placement module policy mismatch"
timeout --signal=TERM --kill-after=5s 30s "$ORACLE" "/dev/mapper/$DMNAME" ||
    fail "packed-placement byte-exact smoke failed"
packed_after="$(dmsetup status "$DMNAME")"
packed_holes="$(status_u64 "$packed_after" alignment_hole_blocks_foreground)" ||
    fail "packed-placement status lacks hole count"
packed_splits="$(status_u64 "$packed_after" run_splits_by_hole)" ||
    fail "packed-placement status lacks hole-split count"
packed_failed="$(status_u64 "$packed_after" failed)" ||
    fail "packed-placement status lacks failure state"
(( $(status_u64 "$packed_after" packed_placement) == 1 &&
   packed_failed == 0 )) ||
    fail "packed-placement smoke did not remain healthy"
note "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 holes:$packed_holes run_splits:$packed_splits failed:$packed_failed"
dmsetup remove "$DMNAME" || fail "cannot remove packed-placement mapping"
OWN_DM=0
