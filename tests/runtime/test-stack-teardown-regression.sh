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
  CHILD_STATE=""; CALLS=()
}
dmsetup() {
  local command=$1 target=""
  case "$command" in
    ls)
      [[ "$2" == --noheadings ]] || return 99
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
losetup() {
  if [[ "$1" == -d && "$2" == "$LOOP_DEVICE" ]]; then
    CALLS+=("detach:$LOOP_DEVICE")
    (( LOOP_ATTACHED )) || return 1
    LOOP_ATTACHED=0
    return 0
  fi
  [[ "$1" == "$LOOP_DEVICE" ]] && (( LOOP_ATTACHED ))
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
jobs() { [[ "$*" == -p ]] && printf '%s\n' 424242; }
kill() {
  case "$1" in
    -0|-TERM) [[ "$2" == 424242 ]] && [[ -n "$CHILD_STATE" ]] ;;
    *) return 99 ;;
  esac
}
ps() { [[ "$*" == '-o stat= -p 424242' ]] && printf '%s\n' "$CHILD_STATE"; }
sleep() { :; }
reset_fixture
CHILD_STATE=D
if swapz_test_stop_child 424242; then exit 1; fi
(( UPPER_EXISTS && LOWER_EXISTS && LOOP_ATTACHED ))
[[ "${#CALLS[@]}" == 0 ]]
echo 'unresponsive writer blocks teardown: PASS'
echo 'swapz test-stack teardown rootless regression: PASS'
