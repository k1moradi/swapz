#!/usr/bin/env bash
# Rootless fake-sysfs test, never invokes a real dmsetup or device.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
source "$ROOT/tools/quiet-lower-io.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/quiet-io.XXXXXXXX")"
trap 'rm -f "$TMP/stat" "$TMP/calls"; rmdir "$TMP"' EXIT
STAT="$TMP/stat"
CALLS="$TMP/calls"
printf '%s\n' '3 0 24 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT"
printf '0\n' > "$CALLS"
mode=steady
dmsetup() {
    [[ $# == 2 && "$1" == status && "$2" == owned-test-mapper ]] || return 1
    local calls
    calls="$(cat "$CALLS")"
    calls="$((calls + 1))"
    printf '%s\n' "$calls" > "$CALLS"
    if [[ $mode == backing_busy ]]; then
        printf '%s\n' "$((3 + calls)) 0 $((24 + calls * 8)) 0 0 0 0 0 0 0 0 0 0 0 0 0 0" > "$STAT"
    fi
    if [[ $mode == target_busy ]]; then
        printf '0 32768 swapz3 physical_read=%d\n' "$calls"
    else
        printf '0 32768 swapz3 physical_read=0\n'
    fi
}
sleep() { :; }
swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0
[[ "$SWAPZ_QUIET_ATTEMPTS" == 1 &&
   "$SWAPZ_QUIET_STATUS" == '0 32768 swapz3 physical_read=0' &&
   "${SWAPZ_QUIET_LOWER[0]}" == 3 &&
   "${SWAPZ_QUIET_LOWER[2]}" == 24 ]]
mode=target_busy
if swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0; then
    echo 'FAIL: changing V3 counters were accepted' >&2
    exit 1
fi
[[ "$(cat "$CALLS")" == 8 ]]
[[ -z $SWAPZ_QUIET_STATUS && ${#SWAPZ_QUIET_LOWER[@]} == 0 ]]
mode=backing_busy
if swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0; then
    echo 'FAIL: extra lower reads were accepted' >&2
    exit 1
fi
[[ "$(cat "$CALLS")" == 14 ]]
mode=steady
printf '%s\n' '3 0 24 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT"
swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0
printf '3 0 24\n' > "$STAT"
if swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0; then
    echo 'FAIL: truncated lower stat accepted' >&2
    exit 1
fi
echo 'PASS: stable status, changing V3/lower and truncated stat gates'
