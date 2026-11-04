#!/usr/bin/env bash
# Rootless fake-sysfs test, never invokes a real dmsetup or device.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
source "$ROOT/tests/tools/quiet-lower-io.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/quiet-io.XXXXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT
STAT="$TMP/stat"
CALLS="$TMP/calls"
INFO_CALLS="$TMP/info-calls"
SLEEP_CALLS="$TMP/sleep-calls"
LOWER_17='3 0 24 0 0 0 0 0 0 0 0 0 0 0 0 0 0'
LOWER_15='3 0 24 0 0 0 0 0 0 0 0 0 0 0 0'
LOWER_11='3 0 24 0 0 0 0 0 0 0 0'
EXPECTED_STATUS='0 32768 swapz version=1 mode=alpha-live-gc logical_write=0 logical_read=0 physical_write=0 physical_write_reqs=0 physical_read=0 physical_read_reqs=0 failed=0 error=0 completion_active=0 upper_write_completed_ok=0 upper_write_completed_err=0 endio_write_forced_err=0'
mode=steady
case_count=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
reset_case() {
    mode="$1"
    printf '%s\n' "$LOWER_17" > "$STAT"
    printf '0\n' > "$CALLS"
    printf '0\n' > "$INFO_CALLS"
    printf '0\n' > "$SLEEP_CALLS"
    case_count=$((case_count + 1))
}

# This function deliberately accepts *only* read-only observational dmsetup
# requests. A new control-path command is a test failure, never real I/O.
dmsetup() {
    local calls physical_read=0 status_text
    if [[ $1 == info && $# == 8 && $2 == -c && $3 == --noheadings &&
            $4 == --separator && $5 == : && $6 == -o &&
            $7 == uuid,major,minor,events && $8 == owned-test-mapper ]]; then
        :
    elif [[ $1 == status && $# == 2 && $2 == owned-test-mapper ]]; then
        :
    else
        fail "unexpected dmsetup command (not observational)"
    fi
    if [[ $1 == info ]]; then
        calls="$(command cat "$INFO_CALLS")"
        calls=$((calls + 1))
        printf '%s\n' "$calls" > "$INFO_CALLS"
        [[ $mode == identity_fail_first && $calls == 1 ]] && return 7
        [[ $mode == identity_fail_second && $calls == 2 ]] && return 7
        case $mode in
            identity_switch)
                (( calls >= 2 )) && { printf 'other-mapper:253:2:1\n'; return; } ;;
            identity_switch_later)
                (( calls >= 3 )) && { printf 'other-mapper:253:2:1\n'; return; } ;;
            malformed_identity) printf 'owned-uuid:0253:1:0\n'; return ;;
        esac
        printf 'owned-uuid:253:1:0\n'
        return
    fi
    calls="$(command cat "$CALLS")"
    calls=$((calls + 1))
    printf '%s\n' "$calls" > "$CALLS"
    [[ $mode == status_fail_first && $calls == 1 ]] && return 9
    [[ $mode == status_fail_second && $calls == 2 ]] && return 9
    case $mode in
        lower_busy)
            (( calls % 2 == 0 )) && printf '%s\n' "$((3 + calls)) 0 $((24 + calls * 8)) 0 0 0 0 0 0 0 0 0 0 0 0 0 0" > "$STAT" ;;
        lower_once)
            (( calls == 2 )) && printf '%s\n' '4 0 32 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT" ;;
        lower_wrap)
            (( calls == 2 )) && printf '%s\n' '1 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT" ;;
        width_change)
            (( calls == 2 )) && printf '%s\n' "$LOWER_15" > "$STAT" ;;
        width_change_later)
            (( calls == 2 )) && printf '%s\n' '4 0 32 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT"
            (( calls == 3 )) && printf '%s\n' "$LOWER_15" > "$STAT" ;;
    esac
    case $mode in
        target_busy|identity_switch_later) physical_read="$calls" ;;
        target_once) (( calls >= 2 )) && physical_read=1 ;;
        target_wrap) (( calls == 1 )) && physical_read=19 || physical_read=2 ;;
        leading_zero_status) physical_read=01 ;;
        negative_status) physical_read=-1 ;;
        overflow_status) physical_read=9223372036854775808 ;;
    esac
    status_text="${EXPECTED_STATUS/physical_read=0 /physical_read=$physical_read }"
    case $mode in
        truncated_status) status_text="${status_text% endio_write_forced_err=0}" ;;
        partial_status) status_text='0 32768 swapz version=1 mode=alpha-live-gc physical_read=0' ;;
        duplicate_status) status_text="${status_text/ endio_write_forced_err=0/ physical_read=0 endio_write_forced_err=0}" ;;
        malformed_status) status_text="${status_text/ endio_write_forced_err=0/ opaque=invalid endio_write_forced_err=0}" ;;
        snapshot_error) status_text='0 32768 swapz status_snapshot_error=-12' ;;
        wrong_target) status_text="${status_text/swapz version=/linear version=}" ;;
        newline_status) status_text="$status_text"$'\n''0 32768 swapz physical_read=0' ;;
        noncanonical_failure) status_text="${status_text/failed=0/failed=01}" ;;
        bad_tail_with_failed_one) status_text="${status_text/failed=0/failed=1}"; status_text="${status_text% endio_write_forced_err=0}" ;;
        failed_target) status_text="${status_text/failed=0 error=0/failed=1 error=-5}" ;;
    esac
    printf '%s\n' "$status_text"
}
sleep() {
    local calls
    calls="$(command cat "$SLEEP_CALLS")"
    printf '%s\n' "$((calls + 1))" > "$SLEEP_CALLS"
    [[ $mode == sleep_timeout ]] && return 124
    [[ $mode == sleep_failed ]] && return 7
    return 0
}
# A failed sysfs read after prerequisite inspection must not become zero I/O.
cat() {
    [[ $mode == lower_read_failed && ${2:-} == "$STAT" ]] && return 7
    command cat "$@"
}

expect_success() {
    local expected_attempts="$1" expected_width="$2"
    if ! swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 0 > "$TMP/out" 2> "$TMP/err"; then
        fail "$mode unexpectedly unavailable: $(command cat "$TMP/err")"
    fi
    [[ ! -s "$TMP/out" && ! -s "$TMP/err" ]] || fail "$mode logged on success"
    [[ $SWAPZ_QUIET_ATTEMPTS == "$expected_attempts" &&
       ${#SWAPZ_QUIET_LOWER[@]} == "$expected_width" &&
       $SWAPZ_QUIET_STATUS == *'endio_write_forced_err=0' &&
       -z $SWAPZ_QUIET_LAST_FAILURE &&
       -z $SWAPZ_QUIET_RETAINED_STATUS_BEFORE &&
       -z $SWAPZ_QUIET_RETAINED_STATUS_AFTER ]] || fail "$mode returned incomplete success"
}
expect_unavailable() {
    local phase="$1" reason="$2" retained="$3" attempts="${4:-3}"
    if swapz_capture_quiescent_io owned-test-mapper "$STAT" "$attempts" 0 > "$TMP/out" 2> "$TMP/err"; then
        fail "$mode false quiescence"
    fi
    [[ ! -s "$TMP/out" && $(wc -l < "$TMP/err") == 1 ]] ||
        fail "$mode unexpected success or repeated logs"
    grep -Fq "phase=$phase reason=$reason" "$TMP/err" ||
        fail "$mode wrong diagnostic: $(command cat "$TMP/err")"
    grep -Fq "retained=$retained published=none" "$TMP/err" ||
        fail "$mode wrong retained evidence: $(command cat "$TMP/err")"
    [[ -z $SWAPZ_QUIET_STATUS && ${#SWAPZ_QUIET_LOWER[@]} == 0 &&
       $SWAPZ_QUIET_ATTEMPTS == 0 &&
       $SWAPZ_QUIET_LAST_FAILURE == *"reason=$reason"* ]] ||
        fail "$mode published unavailable counters"
    if [[ $retained == initial+final ]]; then
        [[ -n $SWAPZ_QUIET_RETAINED_STATUS_BEFORE &&
           -n $SWAPZ_QUIET_RETAINED_STATUS_AFTER ]] || fail "$mode lost diagnostic samples"
    fi
}

reset_case steady
expect_success 1 17
reset_case stat_11
printf '%s\n' "$LOWER_11" > "$STAT"
expect_unavailable initial-lower incomplete-lower-stat-prerequisite initial
reset_case stat_15
printf '%s\n' "$LOWER_15" > "$STAT"
expect_unavailable initial-lower incomplete-lower-stat-prerequisite initial
reset_case failed_target
expect_success 1 17
reset_case target_once
expect_success 2 17
reset_case lower_once
expect_success 2 17
reset_case target_busy
expect_unavailable attempt-budget exhausted:unstable-target-status initial+final
[[ $(command cat "$CALLS") == 6 ]] || fail 'target-busy attempts not bounded'
reset_case lower_busy
expect_unavailable attempt-budget exhausted:unstable-lower-counter initial+final
reset_case target_wrap
expect_unavailable target-counter counter-regression-or-wrap initial+final
reset_case lower_wrap
expect_unavailable lower-counter counter-regression-or-wrap initial+final
reset_case width_change
expect_unavailable final-lower lower-counter-width-changed initial+final
reset_case width_change_later
expect_unavailable initial-lower lower-counter-width-changed initial
reset_case truncated_status
expect_unavailable initial-status missing-status-field:endio_write_forced_err none
reset_case partial_status
expect_unavailable initial-status malformed-status none
reset_case duplicate_status
expect_unavailable initial-status malformed-status none
reset_case malformed_status
expect_unavailable initial-status malformed-status none
reset_case snapshot_error
expect_unavailable initial-status malformed-status none
reset_case wrong_target
expect_unavailable initial-status malformed-status none
reset_case newline_status
expect_unavailable initial-status malformed-status none
reset_case leading_zero_status
expect_unavailable initial-status malformed-status none
reset_case negative_status
expect_unavailable initial-status malformed-status none
reset_case overflow_status
expect_unavailable initial-status malformed-status none
reset_case noncanonical_failure
expect_unavailable initial-status malformed-status none
reset_case bad_tail_with_failed_one
expect_unavailable initial-status missing-status-field:endio_write_forced_err none
reset_case malformed_identity
expect_unavailable initial-identity malformed-mapping-identity none
reset_case identity_switch
expect_unavailable final-identity mapping-identity-changed initial+final
reset_case identity_switch_later
expect_unavailable initial-identity mapping-identity-changed none
reset_case identity_fail_first
expect_unavailable initial-identity identity-command-failed none
reset_case identity_fail_second
expect_unavailable final-identity identity-command-failed initial+final
reset_case status_fail_first
expect_unavailable initial-status status-command-failed none
reset_case status_fail_second
expect_unavailable final-status status-command-failed initial
reset_case sleep_timeout
expect_unavailable sample-interval interval-timeout initial
reset_case sleep_failed
expect_unavailable sample-interval interval-command-failed initial
reset_case malformed_lower_short
printf '%s\n' '3 0 24 0 0 0 0' > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case malformed_lower_extra
printf '%s 0\n' "$LOWER_17" > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case malformed_lower_zero_prefix
printf '03%s\n' "${LOWER_17#3}" > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case malformed_lower_negative
printf '%s\n' "${LOWER_17/3 /-1 }" > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case malformed_lower_overflow
printf '%s\n' "${LOWER_17/3 /9223372036854775808 }" > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case multiline_lower
printf '%s\n%s\n' "$LOWER_17" "$LOWER_17" > "$STAT"
expect_unavailable initial-lower malformed-lower-stat initial
reset_case lower_read_failed
expect_unavailable initial-lower lower-stat-read-failed initial
reset_case missing_lower
rm -- "$STAT"
expect_unavailable prerequisite invalid-or-missing none
reset_case symlink_lower
mv -- "$STAT" "$TMP/actual-stat"
ln -s actual-stat "$STAT"
expect_unavailable prerequisite invalid-or-missing none
rm -- "$STAT" "$TMP/actual-stat"
reset_case invalid_attempts
if swapz_capture_quiescent_io owned-test-mapper "$STAT" 999999999999999999999 0 > "$TMP/out" 2> "$TMP/err"; then
    fail 'unbounded attempt count accepted'
fi
grep -Fq 'phase=prerequisite' "$TMP/err" || fail 'no bounded-attempt diagnostic'
reset_case invalid_interval
if swapz_capture_quiescent_io owned-test-mapper "$STAT" 3 inf > "$TMP/out" 2> "$TMP/err"; then
    fail 'unbounded sleep interval accepted'
fi
grep -Fq 'phase=prerequisite' "$TMP/err" || fail 'no interval diagnostic'
reset_case steady
expect_success 1 17
printf 'PASS: %d rootless valid/unstable/malformed/failed-observation quiescence cases\n' "$case_count"
