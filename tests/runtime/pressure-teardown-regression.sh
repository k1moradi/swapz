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
TMP=$(mktemp -d)
EVENT_LOG="$TMP/cleanup-events"
trap 'rm -rf -- "$TMP"' EXIT
record() { printf '%s\n' "$1" >>"$EVENT_LOG"; }

reset_fixture() {
  SWAPON=0
  GROUP_REMOVED=0; GROUP_INSPECT_FAIL=0
  UNIT_LOAD_FAIL=0; UNIT_GROUP_FAIL=0; UNIT_STATE_FAIL=0
  UNIT_PID_FAIL=0; UNIT_STOP_FAIL=0; CGROUP_PIDS=""
  CGROUP_READ_FAIL=0; CGROUP_SECOND_PIDS=""; SWAPS_READ_FAIL=0; SWAPS_INVALID=0
  SWAPS_FAKE_CONTENT=""
  MAP_EXISTS=1; MAP_ABSENCE_FAIL=0; MAP_RESOLVE_FAIL=0; SWAP_RESOLVE_FAIL=0
  ACTIVE_SWAP=0; SWAPOFF_FAIL=0; CLEAN_CALLS=0; SWAPOFF_CALLS=0
  : >"$EVENT_LOG"
}
# Exercise the real os.stat-based tri-state checker on ordinary temp paths
# before replacing it with controlled mocks for later systemd scenarios.
mkdir "$TMP/present-cgroup"
[[ "$(swapz_pressure_cgroup_state "$TMP/present-cgroup")" == present ]]
[[ "$(swapz_pressure_cgroup_state "$TMP/absent-cgroup")" == absent ]]
printf marker >"$TMP/not-a-directory"
if swapz_pressure_cgroup_state "$TMP/not-a-directory"; then exit 1; fi
python3() { return 5; }
if swapz_pressure_cgroup_state "$TMP/present-cgroup"; then exit 1; fi
unset -f python3
echo 'real cgroup tri-state: present, ENOENT, invalid type and inspection failure: PASS'

swapz_pressure_cgroup_state() {
  (( GROUP_INSPECT_FAIL )) && return 5
  if (( GROUP_REMOVED )); then printf 'absent\n'
  else printf 'present\n'; fi
}
cat() {
  [[ "$1" == -- ]] || return 99
  case "$2" in
    /proc/swaps)
      record 'verify-swap'
      (( SWAPS_READ_FAIL )) && return 5
      if (( SWAPS_INVALID )); then printf 'corrupt header\n'; return 0; fi
      if [[ -n "$SWAPS_FAKE_CONTENT" ]]; then
        printf '%s\n' "$SWAPS_FAKE_CONTENT"
        return 0
      fi
      printf 'Filename\tType\tSize\tUsed\tPriority\n'
      printf '/swapfile\tfile\t64\t0\t-1\n'
      (( ACTIVE_SWAP )) && printf '/dev/dm-93\tpartition\t64\t0\t100\n'
      return 0 ;;
    /sys/fs/cgroup/*/cgroup.procs)
      case "$2" in
        "/sys/fs/cgroup/system.slice/$FIRST_UNIT/cgroup.procs"|"/sys/fs/cgroup/system.slice/$SECOND_UNIT/cgroup.procs"|"/sys/fs/cgroup/test/cgroup.procs")
          record "verify-cgroup:$2" ;;
        *) echo "ERROR: unexpected test cgroup $2" >&2; return 99 ;;
      esac
      (( CGROUP_READ_FAIL )) && return 5
      if [[ "$2" == "/sys/fs/cgroup/system.slice/$SECOND_UNIT/cgroup.procs" &&
            -n "$CGROUP_SECOND_PIDS" ]]; then
        printf '%s\n' "$CGROUP_SECOND_PIDS"
      elif [[ -n "$CGROUP_PIDS" ]]; then
        printf '%s\n' "$CGROUP_PIDS"
      fi
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
    (( SWAP_RESOLVE_FAIL )) && return 5
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
        printf '/system.slice/%s\n' "$2" ;;
      ActiveState)
        (( UNIT_STATE_FAIL )) && return 5
        printf 'inactive\n' ;;
      *) return 99 ;;
    esac
  elif [[ "$1" == stop ]]; then
    record "stop:$3"
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
  record 'swapoff'
  ((++SWAPOFF_CALLS))
  (( SWAPOFF_FAIL )) && return 5
  ACTIVE_SWAP=0
  return 0
}
swapz_test_cleanup_dm_stack() {
  [[ "$1" == "$LOOP" && "$2" == "$NAME" ]] || return 99
  if (( ACTIVE_SWAP )); then echo "ERROR: cleanup mock saw active swap" >&2; return 11; fi
  record 'cleanup-stack'
  ((++CLEAN_CALLS))
  return 0
}
reset_fixture
# Rootless mock simulates cgroup.procs content independent of st_size.
# This does not claim to create a real zero-size cgroup pseudo-file.
CGROUP_PIDS=424242
if swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs; then exit 1; fi
CGROUP_PIDS=""
CGROUP_READ_FAIL=1
if swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs; then exit 1; fi
CGROUP_READ_FAIL=0
swapz_pressure_cgroup_empty /sys/fs/cgroup/test/cgroup.procs
echo 'mocked cgroup.procs PIDs and read failure both block teardown: PASS'

reset_fixture
CGROUP_PIDS=424242
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
echo 'inactive unit with live cgroup tasks: PASS'

reset_fixture
CGROUP_SECOND_PIDS=424242
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
mapfile -t group_events <"$EVENT_LOG"
[[ "${group_events[*]}" == "stop:$FIRST_UNIT verify-cgroup:/sys/fs/cgroup/system.slice/$FIRST_UNIT/cgroup.procs stop:$SECOND_UNIT verify-cgroup:/sys/fs/cgroup/system.slice/$SECOND_UNIT/cgroup.procs" ]]
echo 'second unit cgroup checked independently: PASS'

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
SWAPON=1
ACTIVE_SWAP=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 && SWAPON == 1 && ACTIVE_SWAP == 1 ))
[[ "$(command cat "$EVENT_LOG")" == "stop:$FIRST_UNIT" ]]
reset_fixture
UNIT_PID_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
reset_fixture
GROUP_INSPECT_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
echo 'MainPID and cgroup tri-state inspection errors block teardown: PASS'

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
reset_fixture
MAP_EXISTS=0
MAP_ABSENCE_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
reset_fixture
ACTIVE_SWAP=1
SWAP_RESOLVE_FAIL=1
if swapz_pressure_cleanup_resources; then exit 1; fi
(( CLEAN_CALLS == 0 ))
echo 'missing mapper and failed active-swap resolution block teardown: PASS'

echo 'mapper, proc-swaps inspection and bad-header errors preserve swap: PASS'

# A partially correct header, truncated row or bad accounting must not
# establish that a test-owned mapping is absent from the active swap list.
BAD_SWAPS=(
  "Filename NOT_Type Size Used Priority"
  "Filename Type Size Used Priority|/swapfile file"
  "Filename Type Size Used Priority|/swapfile file unknown 0 -1"
  "Filename Type Size Used Priority|/swapfile file 64 0 not-a-priority"
)
for bad_swaps in "${BAD_SWAPS[@]}"; do
  reset_fixture
  SWAPS_FAKE_CONTENT=${bad_swaps//|/$'\n'}
  if swapz_pressure_cleanup_resources; then exit 1; fi
  (( CLEAN_CALLS == 0 && SWAPOFF_CALLS == 0 ))
done
echo 'malformed swap header, row and numeric fields block mapper teardown: PASS'

reset_fixture
SWAPS_FAKE_CONTENT="Filename Type Size Used Priority"$'\n'"/swapfile file 64 0 -1"
swapz_pressure_cleanup_resources
(( CLEAN_CALLS == 1 && SWAPOFF_CALLS == 0 ))
echo 'valid unrelated negative-priority swap permits test-only cleanup: PASS'

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
mapfile -t ordered_events <"$EVENT_LOG"
[[ "${ordered_events[*]}" == "stop:$FIRST_UNIT verify-cgroup:/sys/fs/cgroup/system.slice/$FIRST_UNIT/cgroup.procs stop:$SECOND_UNIT verify-cgroup:/sys/fs/cgroup/system.slice/$SECOND_UNIT/cgroup.procs swapoff verify-swap cleanup-stack" ]]
echo 'successful stop, swapoff, verify, mapper teardown order: PASS'

reset_fixture
GROUP_REMOVED=1
swapz_pressure_cleanup_resources
(( CLEAN_CALLS == 1 ))
echo 'stopped unit with confirmed removed cgroup: PASS'

reset_fixture
MAP_EXISTS=0
swapz_pressure_cleanup_resources
(( CLEAN_CALLS == 1 ))
echo 'confirmed absent test mapping safely handled: PASS'

echo 'swapz pressure teardown rootless regression: PASS'
