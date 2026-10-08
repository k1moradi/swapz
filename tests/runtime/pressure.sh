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
run_pressure(){
  local unit=$1 size=$2 mem=$3 swap=$4 require_gc=$5
  local dir="$TMP/$unit" token ready=0 cg="" state="" attempt
  # Refuse to reuse checkpoint files or stale release tokens.
  if [[ -e "$dir" ]]; then
    echo "ERROR: pressure checkpoint directory already exists: $dir" >&2
    return 1
  fi
  mkdir -- "$dir"
  token=$(python3 -c 'import secrets; print(secrets.token_hex(16))') || return 1
  # Only exact, test-owned system.slice units are accepted in teardown.
  systemd-run --unit="$unit" --slice=system.slice --property="MemoryMax=$mem" --property="MemorySwapMax=$swap" \
    --property=TasksMax=32 --property=RuntimeMaxSec=300 \
    --no-block /usr/bin/python3 "$ROOT/tests/runtime/pressure-helper.py" "$size" "$dir" "$token" >/dev/null

  # The helper publishes filled only after touching all pages. The matching
  # token, rather than MainPID/ps stop state, proves which phase is waiting.
  for ((attempt=0; attempt<300; ++attempt)); do
    if [[ -e "$dir/filled" ]]; then
      if [[ "$(cat -- "$dir/filled")" != "filled:$token" ]]; then
        echo "ERROR: invalid filled checkpoint marker for $unit" >&2
        return 1
      fi
      ready=1
      break
    fi
    state=$(systemctl show "$unit" -p ActiveState --value 2>/dev/null) || return 1
    if [[ "$state" != active && "$state" != activating ]]; then
      echo "$unit exited before reaching filled checkpoint" >&2
      return 1
    fi
    sleep 0.2
  done
  (( ready )) || { echo "$unit did not reach filled checkpoint" >&2; return 1; }
  cg=$(systemctl show "$unit" -p ControlGroup --value) || return 1
  if [[ "$cg" != "/system.slice/$unit" ]]; then
    echo "ERROR: unexpected pressure unit ControlGroup $cg" >&2
    return 1
  fi
  echo "$unit filled checkpoint cgroup=$cg memory.swap.current=$(cat -- "/sys/fs/cgroup$cg/memory.swap.current")"
  awk -v d="$DEVICE" -v label="$unit filled" '$1==d {print label " /proc/swaps_used_kib=" $4}' /proc/swaps
  echo "$unit swapz status: $(dmsetup status "$NAME")"
  if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" release "$dir" "$token" filled; then
    echo "ERROR: could not release filled checkpoint for $unit" >&2
    return 1
  fi

  ready=0
  for ((attempt=0; attempt<300; ++attempt)); do
    if [[ -e "$dir/verified" ]]; then
      if [[ "$(cat -- "$dir/verified")" != "verified:$token" ]]; then
        echo "ERROR: invalid verified checkpoint marker for $unit" >&2
        return 1
      fi
      ready=1
      break
    fi
    state=$(systemctl show "$unit" -p ActiveState --value 2>/dev/null) || return 1
    if [[ "$state" != active && "$state" != activating ]]; then
      echo "$unit exited before reaching verified checkpoint" >&2
      return 1
    fi
    sleep 0.2
  done
  (( ready )) || { echo "$unit did not reach verified checkpoint" >&2; return 1; }
  local swap_current swap_used status gc_pages
  swap_current=$(cat -- "/sys/fs/cgroup$cg/memory.swap.current")
  swap_used=$(awk -v d="$DEVICE" '$1==d {used=$4} END {print used+0}' /proc/swaps)
  status=$(dmsetup status "$NAME")
  echo "$unit verified checkpoint cgroup memory.swap.current=$swap_current /proc/swaps_used_kib=$swap_used"
  echo "$unit swapz verified status: $status"
  grep -q 'failed=0' <<<"$status"
  (( swap_current > 0 && swap_used > 0 ))
  if (( require_gc )); then
    gc_pages=$(sed -n 's/.*gc_pages=\([0-9][0-9]*\).*/\1/p' <<<"$status")
    (( gc_pages > 0 ))
  fi
  if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" release "$dir" "$token" verified; then
    echo "ERROR: could not release verified checkpoint for $unit" >&2
    return 1
  fi
  state=""
  for ((attempt=0; attempt<300; ++attempt)); do
    state=$(systemctl show "$unit" -p ActiveState --value 2>/dev/null) || return 1
    [[ "$state" != active && "$state" != activating ]] && break
    sleep 0.2
  done
  if [[ "$state" == active || "$state" == activating ]]; then
    echo "ERROR: $unit did not exit after verified release" >&2
    return 1
  fi
  local result exit_status
  result=$(systemctl show "$unit" -p Result --value 2>/dev/null) || return 1
  exit_status=$(systemctl show "$unit" -p ExecMainStatus --value 2>/dev/null) || return 1
  echo "$unit result=$result exit=$exit_status"
  [[ "$result" == success && "$exit_status" == 0 && -s "$dir/verified" ]] || return 1
  echo "$unit readback: PASS"
}
run_pressure "$FIRST_UNIT" 160 64M 192M 1
swapoff "/dev/mapper/$NAME"
SWAPON=0
echo "after first swapoff: $(dmsetup status "$NAME")"
mkswap "/dev/mapper/$NAME" >/dev/null
swapon --priority "$PRIORITY" --discard=pages "/dev/mapper/$NAME"
SWAPON=1
echo "second swapon active: $(awk -v d="$DEVICE" '$1==d {print "used_kib=" $4}' /proc/swaps)"
run_pressure "$SECOND_UNIT" 32 16M 48M 0
swapoff "/dev/mapper/$NAME"
SWAPON=0
echo "after second swapoff: $(dmsetup status "$NAME")"
