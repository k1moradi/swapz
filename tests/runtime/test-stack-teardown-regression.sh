#!/usr/bin/env bash
# Rootless mocks: no DM, loop, swap, kernel modules, or physical media touched.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/test-stack-teardown.sh"

UPPER="swapz-test-upper-$$"
LOWER="swapz-test-lower-$$"
LOOP_DEVICE=/dev/loop1234
reset_fixture() {
  UPPER_EXISTS=1; LOWER_EXISTS=1; LOOP_ATTACHED=1
  BUSY_TARGET=""; FALSE_REMOVE=""; FALSE_INFO=""; LOOP_HELD=0
  LIST_FAIL=0; AWK_FAIL=0; LIST_MALFORMED=0; LOOP_LIST_FAIL=0; FALSE_DETACH=0
  LOOP_LIST_PADDED=0; LOOP_LIST_MALFORMED=0; LOOP_LIST_EXTRA=0
  LOOP_LIST_FAIL_AFTER=0
  PS_FAIL=0; CHILD_STATE=""; CALLS=(); SIGNALS=(); JOB_RUNNING=1; JOB_STOPPED=0
}
dmsetup() {
  local command=$1 target=""
  case "$command" in
    ls)
      [[ "$2" == --noheadings ]] || return 99
      (( LIST_FAIL )) && return 5
      if (( LIST_MALFORMED )); then printf 'corrupt-inventory-row\n'; return 0; fi
      (( UPPER_EXISTS )) && printf '%s (253:10)\n' "$UPPER"
      (( LOWER_EXISTS )) && printf '%s (253:11)\n' "$LOWER"
      return 0 ;;
    info|status)
      target=$2
      if [[ "$command" == info && "$FALSE_INFO" == "$target" ]]; then return 1; fi ;;
    remove)
      [[ "$2" == --retry ]] || return 99
      target=$3
      CALLS+=("remove:$target")
      [[ "$BUSY_TARGET" != "$target" ]] || return 16 ;;
    *) return 99 ;;
  esac
  case "$target" in
    "$UPPER")
      if [[ "$command" == remove ]]; then
        [[ "$FALSE_REMOVE" == "$target" ]] || UPPER_EXISTS=0
        return 0
      fi
      (( UPPER_EXISTS )) ;;
    "$LOWER")
      if [[ "$command" == remove ]]; then
        [[ "$FALSE_REMOVE" == "$target" ]] || LOWER_EXISTS=0
        return 0
      fi
      (( LOWER_EXISTS )) ;;
    *) return 99 ;;
  esac
}
swapz_test_check_loop_holders() { (( ! LOOP_HELD )); }
awk() { (( AWK_FAIL )) && return 2; command awk "$@"; }
losetup() {
  if [[ "$1" == --list && "$2" == --noheadings && "$3" == --output && "$4" == NAME ]]; then
    # losetup inventory runs in a command substitution: emulate the *post*
    # detach failure using parent-visible attachment state, not a subshell counter.
    (( LOOP_LIST_FAIL || (LOOP_LIST_FAIL_AFTER && ! LOOP_ATTACHED) )) && return 5
    if (( LOOP_LIST_MALFORMED )); then printf 'unparseable-loop-row\n'; return 0; fi
    if (( LOOP_LIST_EXTRA )); then printf '%s unexpected-column\n' "$LOOP_DEVICE"; return 0; fi
    if (( LOOP_ATTACHED )); then
      if (( LOOP_LIST_PADDED )); then printf '  %s  \n' "$LOOP_DEVICE"
      else printf '%s\n' "$LOOP_DEVICE"; fi
    fi
    return 0
  fi
  if [[ "$1" == -d && "$2" == "$LOOP_DEVICE" ]]; then
    CALLS+=("detach:$LOOP_DEVICE")
    (( LOOP_ATTACHED )) || return 1
    (( FALSE_DETACH )) || LOOP_ATTACHED=0
    return 0
  fi
  return 99
}
# Busy upper preserves both lower layers.
reset_fixture
BUSY_TARGET=$UPPER
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER" ]]
echo 'busy upper preserves backing: PASS'

# A successful dmsetup remove must be independently verified.
reset_fixture
FALSE_REMOVE=$UPPER
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER" ]]
echo 'false-positive removal preserves backing: PASS'

# Failed info cannot conceal a mapping visible in the DM listing.
reset_fixture
FALSE_INFO=$UPPER
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${#CALLS[@]}" == 0 ]]
echo 'DM listing blocks false-negative info: PASS'

# Upper gone, lower busy: loop must remain.
reset_fixture
BUSY_TARGET=$LOWER
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER" ]]
echo 'busy lower blocks loop detach: PASS'

# Partial creation: no targets, only the allocated loop.
reset_fixture
UPPER_EXISTS=0; LOWER_EXISTS=0
swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"
(( ! LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "detach:$LOOP_DEVICE" ]]
echo 'partial setup cleanup: PASS'

# Unrelated block holders must keep backing attached.
reset_fixture
LOOP_HELD=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && ! LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER" ]]
echo 'loop holder protects backing: PASS'

# Completed cleanup has strict upper/lower/loop order.
reset_fixture
swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"
(( ! UPPER_EXISTS && ! LOWER_EXISTS && ! LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER detach:$LOOP_DEVICE" ]]
echo 'dependency-ordered cleanup: PASS'

# Do not accept arbitrary DM names or detach an unexpected backing path.
reset_fixture
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" host-important-volume; then exit 1; fi
if swapz_test_detach_loop /dev/sdb1; then exit 1; fi
(( LOOP_ATTACHED ))
[[ "${#CALLS[@]}" == 0 ]]
echo 'unrelated DM/physical device rejected: PASS'

# An unresponsive owned writer must stop cleanup before mapping removal.
jobs() {
  case "$*" in
    -p) printf '%s\n' 424242 ;;
    -pr) (( JOB_RUNNING )) && printf '%s\n' 424242; return 0 ;;
    -ps) (( JOB_STOPPED )) && printf '%s\n' 424242; return 0 ;;
    *) return 99 ;;
  esac
}
kill() {
  case "$1" in
    -0) [[ "$2" == 424242 ]] && [[ -n "$CHILD_STATE" ]] ;;
    -CONT|-TERM) SIGNALS+=("$1:$2"); [[ "$2" == 424242 ]] && [[ -n "$CHILD_STATE" ]] ;;
    *) return 99 ;;
  esac
}
ps() {
  (( PS_FAIL )) && return 5
  [[ "$*" == '-o stat= -p 424242' ]] && printf '%s\n' "$CHILD_STATE"
}
sleep() { :; }
reset_fixture
CHILD_STATE=D
if swapz_test_stop_child 424242; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${#CALLS[@]}" == 0 ]]
echo 'unresponsive writer blocks teardown: PASS'

# Inventory parser and device-list errors must never prove mapping absence.
reset_fixture
AWK_FAIL=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER" ]]
echo 'DM parser failure preserves lower backing: PASS'

reset_fixture
LIST_FAIL=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER" ]]
echo 'DM inventory failure preserves lower backing: PASS'

# Successful dmsetup ls with corrupt rows cannot prove target absence.
reset_fixture
LIST_MALFORMED=1
FALSE_INFO=$UPPER
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${#CALLS[@]}" == 0 ]]
echo 'malformed DM inventory rejected after failed info: PASS'

# A spurious successful losetup -d does not establish detach.
reset_fixture
FALSE_DETACH=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && ! LOWER_EXISTS && LOOP_ATTACHED ))
echo 'false-positive loop detach preserves backing: PASS'

reset_fixture
LOOP_LIST_FAIL=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! UPPER_EXISTS && ! LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER" ]]
echo 'failed loop inventory blocks detach: PASS'

reset_fixture
LOOP_LIST_FAIL_AFTER=2
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( ! LOOP_ATTACHED ))
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER detach:$LOOP_DEVICE" ]]
echo 'post-detach inventory failure prevents successful teardown report: PASS'

reset_fixture
LOOP_LIST_PADDED=1
swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"
(( ! LOOP_ATTACHED ))
echo 'padded loop inventory parsed correctly: PASS'

reset_fixture
LOOP_LIST_MALFORMED=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( LOOP_ATTACHED ))
echo 'malformed loop inventory preserves backing: PASS'

reset_fixture
LOOP_LIST_EXTRA=1
if swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"; then exit 1; fi
(( LOOP_ATTACHED ))
echo 'loop inventory with unexpected column rejected: PASS'

reset_fixture
LOOP_ATTACHED=0
swapz_test_cleanup_dm_stack "$LOOP_DEVICE" "$UPPER" "$LOWER"
[[ "${CALLS[*]}" == "remove:$UPPER remove:$LOWER" ]]
echo 'confirmed already-detached loop: PASS'

# Directly exercise the real find/holder implementation, not its mock.
unset -f swapz_test_check_loop_holders
ROOT_HOLDERS=$(mktemp -d)
trap 'rm -rf -- "$ROOT_HOLDERS"' EXIT
command touch "$ROOT_HOLDERS/dm-1"
if swapz_test_check_loop_holders "$LOOP_DEVICE" "$ROOT_HOLDERS"; then exit 1; fi
rm -f -- "$ROOT_HOLDERS/dm-1"
find() { return 2; }
if swapz_test_check_loop_holders "$LOOP_DEVICE" "$ROOT_HOLDERS"; then exit 1; fi
unset -f find
swapz_test_check_loop_holders "$LOOP_DEVICE" "$ROOT_HOLDERS"
echo 'real holder enumeration, find error and empty directory: PASS'

# Failed ps lookup for a live, shell-owned process must not block in wait.
reset_fixture
PS_FAIL=1
CHILD_STATE=D
if swapz_test_stop_child 424242; then exit 1; fi
echo 'process-state inspection failure preserves stack: PASS'

# No job ownership and no living process means the child was already reaped.
jobs() { [[ "$*" == -pr || "$*" == -ps ]] && :; }
kill() { return 1; }
reset_fixture
swapz_test_stop_child 424242
echo 'already-reaped test child handled without signal: PASS'

# A completed child can remain in jobs -p after its process has exited.
# Simulate PID reuse: kill -0 succeeds, but -pr/-ps do not list the PID.
reset_fixture
JOB_RUNNING=0
CHILD_STATE=R
if swapz_test_stop_child 424242; then exit 1; fi
[[ "${#SIGNALS[@]}" == 0 ]]
echo 'completed-but-listed reused PID is never signaled: PASS'

# All three tracked recall I/O jobs must be visited even if one fails.
STOPPED_CHILDREN=()
STOP_FAIL_PID=11
swapz_test_stop_child() {
  STOPPED_CHILDREN+=("$1")
  [[ "$1" != "$STOP_FAIL_PID" ]]
}
if swapz_test_stop_children 10 11 12; then exit 1; fi
[[ "${STOPPED_CHILDREN[*]}" == "10 11 12" ]]
STOPPED_CHILDREN=()
STOP_FAIL_PID=0
swapz_test_stop_children "" 10 11 12
[[ "${STOPPED_CHILDREN[*]}" == "10 11 12" ]]
echo 'all writer/reader jobs checked; one failure blocks teardown: PASS'

echo 'swapz test-stack teardown rootless regression: PASS'
