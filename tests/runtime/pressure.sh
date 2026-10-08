#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/test-stack-teardown.sh"
source "$ROOT/tests/runtime/pressure-teardown.sh"
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in awk dmsetup losetup mkswap modprobe python3 readlink swapon swapoff systemctl systemd-run truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
grep -qw memory /sys/fs/cgroup/cgroup.controllers || { echo 'cgroup v2 memory controller unavailable' >&2; exit 1; }
TMP=$(mktemp -d /dev/shm/swapz-v21-pressure.XXXXXX)
TAG="$$-$RANDOM"
NAME="swapz-v21-pressure-$TAG"; PRIORITY=100; SWAPON=0; FIRST_UNIT="swapz-v21-pressure-$TAG-first.service"; SECOND_UNIT="swapz-v21-pressure-$TAG-second.service"
LOOP=""
cleanup() {
  local exit_status=$?
  trap - EXIT
  set +e
  if ! swapz_pressure_cleanup_resources; then
    echo "ERROR: pressure teardown incomplete; preserving test resources and $TMP" >&2
    (( exit_status != 0 )) || exit_status=1
  elif (( exit_status == 0 )); then
    if rm -rf -- "$TMP"; then
      echo 'bounded swap pressure, swapoff, second swapon and teardown: PASS'
    else
      echo "ERROR: could not remove test directory $TMP" >&2
      exit_status=1
    fi
  else
    echo "ERROR: pressure fixture failed; diagnostics preserved at $TMP" >&2
  fi
  exit "$exit_status"
}
trap cleanup EXIT
truncate -s 320M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
modprobe dm-swapz
dmsetup create "$NAME" --table "0 524288 swapz $LOOP"
mkswap "/dev/mapper/$NAME" >/dev/null
swapon --priority "$PRIORITY" --discard=pages "/dev/mapper/$NAME"
SWAPON=1
DEVICE=$(readlink -f "/dev/mapper/$NAME")
echo "active swap entry before pressure:"; awk -v d="$DEVICE" 'NR==1 || $1==d' /proc/swaps
# Source the same phase controller used by rootless integration regression.
source "$ROOT/tests/runtime/pressure-runner.sh"

swapz_pressure_run_unit "$FIRST_UNIT" 160 64M 192M 1
swapoff "/dev/mapper/$NAME"
SWAPON=0
echo "after first swapoff: $(dmsetup status "$NAME")"
mkswap "/dev/mapper/$NAME" >/dev/null
swapon --priority "$PRIORITY" --discard=pages "/dev/mapper/$NAME"
SWAPON=1
echo "second swapon active: $(awk -v d="$DEVICE" '$1==d {print "used_kib=" $4}' /proc/swaps)"
swapz_pressure_run_unit "$SECOND_UNIT" 32 16M 48M 0
swapoff "/dev/mapper/$NAME"
SWAPON=0
echo "after second swapoff: $(dmsetup status "$NAME")"
