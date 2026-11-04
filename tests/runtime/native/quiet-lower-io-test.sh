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
mode=steady
case_count=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
EXPECTED_STATUS="$(python3 - "$ROOT/src/kernel/dm-target.c" <<'PY'
import re
import sys

source = open(sys.argv[1], encoding="utf-8").read()
start = source.index("static void swapz_status(")
end = source.index("static int swapz_message", start)
status_source = source[start:end]
fields = re.findall(r"([A-Za-z0-9_]+)=%(?:[0-9.*]*)(?:[A-Za-z]+)", status_source)
fields = [field for field in fields if field != "status_snapshot_error"]
tokens = []
for field in fields:
    if field == "version":
        tokens.extend(("version=1", "mode=alpha-live-gc"))
    else:
        tokens.append(f"{field}=0")
print("0 32768 swapz " + " ".join(tokens))
PY
)" || fail 'cannot construct production status fixture'
[[ $(wc -w <<< "$EXPECTED_STATUS") == 476 &&
   $EXPECTED_STATUS == *' gc_pages=0 '* &&
   $EXPECTED_STATUS == *' prep_slots_in_use=0 '* &&
   $EXPECTED_STATUS == *' submitter_prepare_active=0 '* &&
   $EXPECTED_STATUS == *' endio_write_forced_err=0' ]] ||
    fail 'production status schema changed; update the quiet-I/O parser and fixture together'
reset_case() {
    mode="$1"
    printf '%s\n' "$LOWER_17" > "$STAT"
    printf '0\n' > "$CALLS"
    printf '0\n' > "$INFO_CALLS"
    printf '0\n' > "$SLEEP_CALLS"
    case_count=$((case_count + 1))
}

# The production helper bounds dmsetup with coreutils timeout. This rootless
# shim keeps fake dmsetup as a shell function and injects deterministic timeout.
timeout() {
    while (( $# > 0 )); do
        case "$1" in
            --signal=*|--kill-after=*) shift ;;
            *s) shift; break ;;
            *) break ;;
        esac
    done
    if [[ $mode == identity_timeout_first && ${1:-} == dmsetup && ${2:-} == info ]]; then
        return 124
    fi
    if [[ $mode == status_timeout_first && ${1:-} == dmsetup && ${2:-} == status ]]; then
        return 124
    fi
    "$@"
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
        lower_wrap_between_attempts)
            (( calls == 2 )) && printf '%s\n' '4 0 32 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT"
            (( calls == 3 )) && printf '%s\n' '3 0 24 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT" ;;
        lower_inflight_once)
            if (( calls <= 2 )); then
                printf '%s\n' '3 0 24 0 0 0 0 0 1 0 0 0 0 0 0 0 0' > "$STAT"
            else
                printf '%s\n' "$LOWER_17" > "$STAT"
            fi ;;
        width_change)
            (( calls == 2 )) && printf '%s\n' "$LOWER_15" > "$STAT" ;;
        width_change_later)
            (( calls == 2 )) && printf '%s\n' '4 0 32 0 0 0 0 0 0 0 0 0 0 0 0 0 0' > "$STAT"
            (( calls == 3 )) && printf '%s\n' "$LOWER_15" > "$STAT" ;;
    esac
    case $mode in
        target_busy|identity_switch_later) physical_read="$calls" ;;
        target_once) (( calls >= 2 )) && physical_read=1 ;;
        target_active_once) : ;;
        target_wrap) (( calls == 1 )) && physical_read=19 || physical_read=2 ;;
        target_wrap_between_attempts)
            (( calls == 2 )) && physical_read=7
            (( calls >= 3 )) && physical_read=2 ;;
        leading_zero_status) physical_read=01 ;;
        negative_status) physical_read=-1 ;;
        overflow_status) physical_read=9223372036854775808 ;;
    esac
    status_text="${EXPECTED_STATUS/physical_read=0 /physical_read=$physical_read }"
    if [[ $mode == target_active ]]; then
        status_text="${status_text/completion_active=0/completion_active=1}"
    elif [[ $mode == target_active_once && $calls -le 2 ]]; then
        status_text="${status_text/completion_active=0/completion_active=1}"
    fi
    case $mode in
        truncated_status) status_text="${status_text% endio_write_forced_err=0}" ;;
        partial_status) status_text='0 32768 swapz version=1 mode=alpha-live-gc physical_read=0' ;;
        internal_truncated_status) status_text="${status_text/ gc_pages=0 / }" ;;
        duplicate_status) status_text="${status_text/ gc_pages=0 / physical_read=0 }" ;;
        malformed_status) status_text="${status_text/ endio_write_forced_err=0/ opaque=invalid endio_write_forced_err=0}" ;;
        snapshot_error) status_text='0 32768 swapz status_snapshot_error=-12' ;;
        wrong_target) status_text="${status_text/swapz version=/linear version=}" ;;
        newline_status) status_text="$status_text"$'\n''0 32768 swapz physical_read=0' ;;
        noncanonical_failure) status_text="${status_text/failed=0/failed=01}" ;;
        negative_read_fault_calls) status_text="${status_text/read_fault_calls=0/read_fault_calls=-1}" ;;
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
    grep -Fq "retained_status=$retained " "$TMP/err" &&
        grep -Fq 'published=none' "$TMP/err" ||
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
reset_case target_active_once
expect_success 2 17
reset_case lower_inflight_once
expect_success 2 17
reset_case target_active
expect_unavailable attempt-budget exhausted:active-target-work initial+final
reset_case lower_inflight
printf '%s\n' '3 0 24 0 0 0 0 0 1 0 0 0 0 0 0 0 0' > "$STAT"
expect_unavailable attempt-budget exhausted:lower-io-in-flight initial+final
reset_case target_busy
expect_unavailable attempt-budget exhausted:unstable-target-status initial+final
[[ $(command cat "$CALLS") == 6 ]] || fail 'target-busy attempts not bounded'
reset_case lower_busy
expect_unavailable attempt-budget exhausted:unstable-lower-counter initial+final
reset_case target_wrap
expect_unavailable target-counter counter-regression-or-wrap initial+final
reset_case lower_wrap
expect_unavailable lower-counter counter-regression-or-wrap initial+final
reset_case target_wrap_between_attempts
expect_unavailable initial-status counter-regression-or-wrap initial
reset_case lower_wrap_between_attempts
expect_unavailable initial-lower counter-regression-or-wrap initial
reset_case width_change
expect_unavailable final-lower lower-counter-width-changed initial+final
reset_case width_change_later
expect_unavailable initial-lower lower-counter-width-changed initial
reset_case truncated_status
expect_unavailable initial-status incomplete-status none
reset_case partial_status
expect_unavailable initial-status incomplete-status none
reset_case internal_truncated_status
expect_unavailable initial-status incomplete-status none
reset_case duplicate_status
expect_unavailable initial-status malformed-status none
reset_case malformed_status
expect_unavailable initial-status malformed-status none
reset_case snapshot_error
expect_unavailable initial-status status-snapshot-error none
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
reset_case negative_read_fault_calls
expect_unavailable initial-status malformed-status none
reset_case bad_tail_with_failed_one
expect_unavailable initial-status incomplete-status none
reset_case malformed_identity
expect_unavailable initial-identity malformed-mapping-identity none
reset_case identity_switch
expect_unavailable final-identity mapping-identity-changed initial+final
reset_case identity_switch_later
expect_unavailable initial-identity mapping-identity-changed none
reset_case identity_fail_first
expect_unavailable initial-identity identity-command-failed none
grep -Fq 'detail=rc=7' "$TMP/err" || fail 'identity failure lost command status'
reset_case identity_fail_second
expect_unavailable final-identity identity-command-failed initial+final
reset_case identity_timeout_first
expect_unavailable initial-identity identity-command-timeout none
grep -Fq 'detail=rc=124' "$TMP/err" || fail 'identity timeout lost command status'
reset_case status_timeout_first
expect_unavailable initial-status status-command-timeout none
grep -Fq 'retained_evidence=identity-before' "$TMP/err" ||
    fail 'status timeout lost retained mapping identity'
grep -Fq 'detail=rc=124' "$TMP/err" || fail 'status timeout lost command status'
reset_case status_fail_first
expect_unavailable initial-status status-command-failed none
grep -Fq 'retained_evidence=identity-before' "$TMP/err" ||
    fail 'status failure lost retained mapping identity'
grep -Fq 'detail=rc=9' "$TMP/err" || fail 'status failure lost command status'
reset_case status_fail_second
expect_unavailable final-status status-command-failed initial
grep -Fq 'retained_evidence=identity-before,status-before,lower-before' "$TMP/err" ||
    fail 'final status failure lost retained initial evidence'
grep -Fq 'detail=rc=9' "$TMP/err" || fail 'final status failure lost command status'
reset_case sleep_timeout
expect_unavailable sample-interval interval-timeout initial
grep -Fq 'detail=rc=124' "$TMP/err" || fail 'interval timeout lost command status'
reset_case sleep_failed
expect_unavailable sample-interval interval-command-failed initial
grep -Fq 'detail=rc=7' "$TMP/err" || fail 'interval failure lost command status'
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
