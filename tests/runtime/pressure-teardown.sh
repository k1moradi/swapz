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

# A cgroup may disappear after unit shutdown. os.stat distinguishes
# ENOENT from EACCES/EIO: Bash -d / -e alone cannot do so.
swapz_pressure_cgroup_state() {
  local path=$1 result
  if ! result=$(python3 -c '
import errno, os, stat, sys
try:
    details = os.stat(sys.argv[1])
except OSError as exc:
    if exc.errno == errno.ENOENT:
        print("absent")
    else:
        raise
else:
    if not stat.S_ISDIR(details.st_mode):
        raise NotADirectoryError(sys.argv[1])
    print("present")
' "$path"); then
    echo "ERROR: cannot inspect cgroup directory $path; preserving swap" >&2
    return 1
  fi
  case "$result" in
    present|absent) printf '%s\n' "$result" ;;
    *) echo "ERROR: invalid cgroup inspection result; preserving swap" >&2; return 1 ;;
  esac
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
  # An unreadable or malformed inventory is NOT evidence of inactive swap.
  # Do not accept a prefix-only header such as "Filename invalid columns".
  local swap_line swap_type swap_size swap_used swap_priority row=0
  local -a fields
  while IFS= read -r swap_line; do
    read -r -a fields <<<"$swap_line"
    if (( row == 0 )); then
      if (( ${#fields[@]} != 5 )) ||
         [[ "${fields[*]}" != "Filename Type Size Used Priority" ]]; then
        echo "ERROR: invalid /proc/swaps header; preserving stack" >&2
        return 1
      fi
    else
      if (( ${#fields[@]} != 5 )); then
        echo "ERROR: malformed /proc/swaps entry; preserving stack" >&2
        return 1
      fi
      swap_path=${fields[0]}
      swap_type=${fields[1]}
      swap_size=${fields[2]}
      swap_used=${fields[3]}
      swap_priority=${fields[4]}
      if [[ "$swap_path" != /* ||
            ( "$swap_type" != file && "$swap_type" != partition ) ||
            ! "$swap_size" =~ ^[0-9]+$ ||
            ! "$swap_used" =~ ^[0-9]+$ ||
            ! "$swap_priority" =~ ^-?[0-9]+$ ]]; then
        echo "ERROR: invalid /proc/swaps fields; preserving stack" >&2
        return 1
      fi
      if [[ "$swap_path" == "/dev/mapper/$name" ]]; then
        echo "ERROR: $name is still active swap; preserving stack" >&2
        return 1
      fi
      if [[ -n "$expected_device" ]]; then
        if ! canonical_path=$(readlink -f -- "$swap_path") ||
           [[ -z "$canonical_path" ]]; then
          echo "ERROR: cannot resolve active swap $swap_path; preserving stack" >&2
          return 1
        fi
        if [[ "$canonical_path" == "$expected_device" ]]; then
          echo "ERROR: $name is still active swap; preserving stack" >&2
          return 1
        fi
      fi
    fi
    ((++row))
  done <<<"$swaps"
  if (( row == 0 )); then
    echo "ERROR: empty /proc/swaps inventory; preserving stack" >&2
    return 1
  fi
  return 0
}

swapz_pressure_cleanup_resources() {
  local unit unit_state unit_pid unit_cgroup load_state attempt
  # The pressure fixture creates two distinct, transient system.slice services.
  # If their names alias, we cannot verify both workloads independently.
  if [[ -z "$FIRST_UNIT" || -z "$SECOND_UNIT" ||
        "$FIRST_UNIT" == "$SECOND_UNIT" ]]; then
    echo "ERROR: invalid or duplicate test unit names; preserving swap" >&2
    return 1
  fi
  # Validate BOTH identifiers before stopping or inspecting EITHER unit.
  # Otherwise an invalid second name could partially stop the first.
  for unit in "$FIRST_UNIT" "$SECOND_UNIT"; do
    if [[ ! "$unit" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.@-]*\.service$ ]]; then
      echo "ERROR: invalid transient unit name $unit; preserving swap" >&2
      return 1
    fi
  done
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
      # The fixture pins systemd-run to system.slice. An unrelated or
      # duplicated ControlGroup would allow checking the WRONG workers and
      # could falsely authorize swapoff or lower device teardown.
      if [[ "$unit_cgroup" != "/system.slice/$unit" ]]; then
        echo "ERROR: unit $unit ControlGroup identity mismatch; preserving swap" >&2
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
      local cgroup_dir="/sys/fs/cgroup$unit_cgroup" group_state
      if ! group_state=$(swapz_pressure_cgroup_state "$cgroup_dir"); then
        return 1
      fi
      case "$group_state" in
        present) swapz_pressure_cgroup_empty "$cgroup_dir/cgroup.procs" || return 1 ;;
        absent) # Positive ENOENT is safe only because ActiveState is stopped.
          if [[ "$unit_state" != inactive && "$unit_state" != failed &&
                "$unit_state" != not-found ]]; then
            echo "ERROR: cgroup absent but unit $unit is not stopped" >&2
            return 1
          fi ;;
        *) echo "ERROR: unknown cgroup state; preserving swap" >&2; return 1 ;;
      esac
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
