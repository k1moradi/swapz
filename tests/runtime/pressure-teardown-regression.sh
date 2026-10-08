#!/usr/bin/env bash
# Rootless pressure cleanup mocks: never call actual systemd, swapoff, DM, or loop.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/test-stack-teardown.sh"
source "$ROOT/tests/runtime/pressure-teardown.sh"

NAME=swapz-test-pressure-$$
FIRST_UNIT=swapz-test-first-$$.service
SECOND_UNIT=swapz-test-second-$$.service
LOOP=/dev/loop1234

reset_fixture() {
  SWAPON=0
  UNIT_LOAD_FAIL=0; UNIT_GROUP_FAIL=0; UNIT_STATE_FAIL=0
  UNIT_PID_FAIL=0; UNIT_STOP_FAIL=0; CGROUP_PIDS=""
  CGROUP_READ_FAIL=0; SWAPS_READ_FAIL=0; SWAPS_INVALID=0
  MAP_EXISTS=1; MAP_ABSENCE_FAIL=0; MAP_RESOLVE_FAIL=0
  ACTIVE_SWAP=0; SWAPOFF_FAIL=0; CLEAN_CALLS=0; SWAPOFF_CALLS=0
}
cat() {
  [[ "$1" == -- ]] || return 99
  case "$2" in
    /proc/swaps)
      (( SWAPS_READ_FAIL )) && return 5
      if (( SWAPS_INVALID )); then printf 'corrupt header\n'; return 0; fi
      printf 'Filename\tType\tSize\tUsed\tPriority\n'
      printf '/swapfile\tfile\t64\t0\t-1\n'
      (( ACTIVE_SWAP )) && printf '/dev/dm-93\tpartition\t64\t0\t100\n'
      return 0 ;;
    /sys/fs/cgroup/*/cgroup.procs)
      (( CGROUP_READ_FAIL )) && return 5
      [[ -z "$CGROUP_PIDS" ]] || printf '%s\n' "$CGROUP_PIDS"
      return 0 ;;
    *) return 99 ;;
  esac
}
dmsetup() {
  [[ "$1" == info && "$2" == "$NAME" ]] || return 99
  (( MAP_EXISTS ))
}
swapz_test_confirm_dm_absent() {
  [[ "$1" == "$NAME" ]] && (( ! MAP_ABSENCE_FAIL ))
}
readlink() {
  if [[ "$1" == -e && "$2" == -- && "$3" == "/dev/mapper/$NAME" ]]; then
    (( MAP_RESOLVE_FAIL )) && return 5
    printf '/dev/dm-93\n'
  elif [[ "$1" == -f && "$2" == -- ]]; then
    printf '%s\n' "$3"
  else
    return 99
  fi
}
systemctl() {
  if [[ "$1" == show ]]; then
    local prop=$4
    case "$prop" in
      LoadState)
        (( UNIT_LOAD_FAIL )) && return 5
        printf 'loaded\n' ;;
      MainPID)
        (( UNIT_PID_FAIL )) && return 5
        printf '0\n' ;;
      ControlGroup)
        (( UNIT_GROUP_FAIL )) && return 5
        printf '/system.slice/swapz-mock.service\n' ;;
      ActiveState)
        (( UNIT_STATE_FAIL )) && return 5
        printf 'inactive\n' ;;
      *) return 99 ;;
    esac
  elif [[ "$1" == stop ]]; then
    (( UNIT_STOP_FAIL )) && return 5
    return 0
  elif [[ "$1" == reset-failed ]]; then
    return 0
  else
    return 99
  fi
}
swapoff() {
  [[ "$1" == "/dev/mapper/$NAME" ]] || return 99
  ((++SWAPOFF_CALLS))
  (( SWAPOFF_FAIL )) && return 5
  ACTIVE_SWAP=0
  return 0
}
swapz_test_cleanup_dm_stack() {
  [[ "$1" == "$LOOP" && "$2" == "$NAME" ]] || return 99
  ((++CLEAN_CALLS))
  return 0
}
reset_fixture
# A pseudo-file with zero metadata size can still yield active tasks.
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
: >"$TMP/zero-size-pseudo-file"
[[ ! -s "$TMP/zero-size-pseudo-file" ]]
CGROUP_PIDS=424242
if swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs; then exit 1; fi
CGROUP_PIDS=""
CGROUP_READ_FAIL=1
if swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs; then exit 1; fi
CGROUP_READ_FAIL=0
swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs
echo 'zero-size cgroup with PIDs and failed read both block teardown: PASS'

reset_fixture
CGROUP_PIDS=424242
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
echo 'inactive unit with live cgroup tasks: PASS'

reset_fixture
UNIT_LOAD_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
UNIT_GROUP_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
UNIT_STATE_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
UNIT_STOP_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
echo 'systemd inspection and stop errors preserve swap: PASS'

reset_fixture
MAP_RESOLVE_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
SWAPS_READ_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
SWAPS_INVALID=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
echo 'mapper, proc-swaps inspection and bad-header errors preserve swap: PASS'

reset_fixture
ACTIVE_SWAP=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
echo 'active test swap on /dev/dm-N blocks mapper removal: PASS'

reset_fixture
SWAPON=1
ACTIVE_SWAP=1
SWAPOFF_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 1 && SWAPON == 1 ))
echo 'swapoff failure preserves mapper and backing: PASS'

reset_fixture
SWAPON=1
ACTIVE_SWAP=1
swapz_pressure_cleanup_resources
(( CLEAN_CALLS == 1 && SWAPOFF_CALLS == 1 && SWAPON == 0 ))
echo 'successful stop, swapoff, verify, mapper teardown order: PASS'

reset_fixture
MAP_EXISTS=0
swapz_pressure_cleanup_resources
(( CLEAN_CALLS == 1 ))
echo 'confirmed absent test mapping safely handled: PASS'

echo 'swapz pressure teardown rootless regression: PASS'
