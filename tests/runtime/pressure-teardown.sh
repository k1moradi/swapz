#!/usr/bin/env bash
# Test-only pressure cleanup. Source after test-stack-teardown.sh.
# All resources are named by this test fixture; never touch unrelated swap.

swapz_pressure_cgroup_empty() {
  local procs_path=$1 contents
  # cgroup.procs is a pseudo-file whose st_size may be 0 with live PIDs.
  # Only a successful read yielding no PIDs is proof of quiescence.
  if ! contents=$(cat -- "$procs_path"); then
    echo "ERROR: cannot read cgroup processes at $procs_path; preserving swap" >&2
    return 1
  fi
  if [[ -n "$contents" ]]; then
    echo "ERROR: active tasks remain in $procs_path; preserving swap" >&2
    return 1
  fi
  return 0
}

swapz_pressure_confirm_swap_inactive() {
  local name=$1 expected_device="" swaps swap_path canonical_path
  # If the mapper still exists, its canonical path must be resolvable.
  # If info fails, require an independent successful DM inventory proving
  # absence; an ioctl/permission error is not an absent mapping.
  if dmsetup info "$name" >/dev/null 2>&1; then
    if ! expected_device=$(readlink -e -- "/dev/mapper/$name") ||
       [[ -z "$expected_device" ]]; then
      echo "ERROR: cannot resolve test swap mapper $name; preserving stack" >&2
      return 1
    fi
  else
    swapz_test_confirm_dm_absent "$name" || return 1
  fi
  if ! swaps=$(cat -- /proc/swaps); then
    echo "ERROR: cannot inspect /proc/swaps; preserving stack" >&2
    return 1
  fi
  if [[ "$swaps" != Filename* ]]; then
    echo "ERROR: invalid /proc/swaps inventory; preserving stack" >&2
    return 1
  fi
  while read -r swap_path _; do
    [[ "$swap_path" == Filename ]] && continue
    [[ -z "$swap_path" ]] && continue
    if [[ "$swap_path" == "/dev/mapper/$name" ]]; then
      echo "ERROR: $name is still active swap; preserving stack" >&2
      return 1
    fi
    if [[ -n "$expected_device" ]]; then
      if ! canonical_path=$(readlink -f -- "$swap_path"); then
        echo "ERROR: cannot resolve active swap $swap_path; preserving stack" >&2
        return 1
      fi
      if [[ "$canonical_path" == "$expected_device" ]]; then
        echo "ERROR: $name is still active swap; preserving stack" >&2
        return 1
      fi
    fi
  done <<<"$swaps"
  return 0
}

swapz_pressure_cleanup_resources() {
  local unit unit_state unit_pid unit_cgroup load_state attempt
  for unit in "$FIRST_UNIT" "$SECOND_UNIT"; do
    if ! load_state=$(systemctl show "$unit" -p LoadState --value) ||
       [[ -z "$load_state" ]]; then
      echo "ERROR: cannot inspect unit $unit LoadState; preserving swap" >&2
      return 1
    fi
    [[ "$load_state" == not-found ]] && continue
    if [[ "$load_state" != loaded ]]; then
      echo "ERROR: unexpected unit $unit LoadState=$load_state; preserving swap" >&2
      return 1
    fi
    if ! unit_pid=$(systemctl show "$unit" -p MainPID --value) ||
       [[ ! "$unit_pid" =~ ^[0-9]+$ ]]; then
      echo "ERROR: cannot inspect unit $unit MainPID; preserving swap" >&2
      return 1
    fi
    if ! unit_cgroup=$(systemctl show "$unit" -p ControlGroup --value); then
      echo "ERROR: cannot inspect unit $unit ControlGroup; preserving swap" >&2
      return 1
    fi
    if ! unit_state=$(systemctl show "$unit" -p ActiveState --value) ||
       [[ -z "$unit_state" ]]; then
      echo "ERROR: cannot inspect unit $unit ActiveState; preserving swap" >&2
      return 1
    fi
    # An empty cgroup can be legitimate only after a unit is fully stopped
    # with no main PID. Otherwise it prevents proof that workers are gone.
    if [[ -z "$unit_cgroup" &&
          ( "$unit_pid" != 0 ||
            ( "$unit_state" != inactive && "$unit_state" != failed ) ) ]]; then
      echo "ERROR: unit $unit has unknown cgroup while active; preserving swap" >&2
      return 1
    fi
    if [[ -n "$unit_cgroup" ]]; then
      if [[ "$unit_cgroup" != /* || "$unit_cgroup" == *..* ]]; then
        echo "ERROR: unsafe unit $unit cgroup path; preserving swap" >&2
        return 1
      fi
      # Resume a stopped helper only while its PID still belongs to this
      # exact test-owned unit. Never send signals to a reused PID.
      if [[ "$unit_pid" != 0 && -r "/proc/$unit_pid/cgroup" ]] &&
         grep -Fqx "0::$unit_cgroup" "/proc/$unit_pid/cgroup"; then
        kill -CONT "$unit_pid" 2>/dev/null || true
      fi
    fi
    if ! systemctl stop --no-block "$unit"; then
      echo "ERROR: failed to stop unit $unit; preserving swap" >&2
      return 1
    fi
    for ((attempt=0; attempt<100; ++attempt)); do
      if ! unit_state=$(systemctl show "$unit" -p ActiveState --value) ||
         [[ -z "$unit_state" ]]; then
        echo "ERROR: cannot verify unit $unit state; preserving swap" >&2
        return 1
      fi
      [[ "$unit_state" == inactive || "$unit_state" == failed ||
         "$unit_state" == not-found ]] && break
      sleep 0.1
    done
    if [[ "$unit_state" != inactive && "$unit_state" != failed &&
          "$unit_state" != not-found ]]; then
      echo "ERROR: test-owned unit $unit remains $unit_state; preserving swap" >&2
      return 1
    fi
    if [[ -n "$unit_cgroup" ]]; then
      swapz_pressure_cgroup_empty "/sys/fs/cgroup$unit_cgroup/cgroup.procs" ||
        return 1
    fi
    systemctl reset-failed "$unit" >/dev/null 2>&1 || true
  done

  if (( SWAPON )); then
    if ! swapoff "/dev/mapper/$NAME"; then
      echo "ERROR: swapoff failed for test target $NAME; preserving stack" >&2
      return 1
    fi
    SWAPON=0
  fi
  # Independently check even if a signal arrived after successful swapon
  # but before SWAPON was updated.
  swapz_pressure_confirm_swap_inactive "$NAME" || return 1
  swapz_test_cleanup_dm_stack "$LOOP" "$NAME"
}
