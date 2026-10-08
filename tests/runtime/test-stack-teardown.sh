#!/usr/bin/env bash
# Shared by disposable swapz runtime fixtures. Never touch a non-test target.
# Caller owns the exact DM names and loop returned by losetup --find --show.
# Remove higher DM mappings before lower mappings, then detach the loop.
# On any failure leave all remaining dependencies and backing data intact.

swapz_test_confirm_dm_absent() {
  local target_name=$1
  local dm_mappings
  # A failing `dmsetup info` alone is not proof that the target is gone.
  if ! dm_mappings=$(dmsetup ls --noheadings 2>/dev/null); then
    echo "ERROR: cannot list DM devices to verify $target_name removal" >&2
    return 1
  fi
  local matched
  # Parse output must succeed independently of whether the target matched.
  # A broken parser must never be treated as verified DM absence.
  if ! matched=$(awk -v name="$target_name" '$1 == name { print "present"; exit }' <<<"$dm_mappings"); then
    echo "ERROR: cannot parse DM device inventory; preserving backing" >&2
    return 1
  fi
  if [[ -n "$matched" ]]; then
    echo "ERROR: DM target $target_name is still listed; preserving backing" >&2
    return 1
  fi
  return 0
}

swapz_test_remove_dm_target() {
  local target_name=$1
  [[ "$target_name" == swapz-* ]] || {
    echo "ERROR: refusing removal of non-test DM target: $target_name" >&2
    return 1
  }
  # The caller may have failed before creating this mapping.
  if ! dmsetup info "$target_name" >/dev/null 2>&1; then
    swapz_test_confirm_dm_absent "$target_name" || return 1
    return 0
  fi
  if ! dmsetup remove --retry "$target_name"; then
    echo "ERROR: DM removal failed for $target_name; backing preserved" >&2
    dmsetup info "$target_name" >&2 || true
    dmsetup status "$target_name" >&2 || true
    return 1
  fi
  if dmsetup info "$target_name" >/dev/null 2>&1; then
    echo "ERROR: DM target $target_name still exists after removal; backing preserved" >&2
    return 1
  fi
  swapz_test_confirm_dm_absent "$target_name" || return 1
  return 0
}

swapz_test_check_loop_holders() {
  local loop_device=$1
  local loop_name=${loop_device##*/}
  # Optional directory argument is only for source-only mocked holder tests.
  local holders_dir=${2:-"/sys/class/block/$loop_name/holders"}
  local first_holder
  if [[ ! -d "$holders_dir" ]]; then
    echo "ERROR: cannot verify holders for $loop_device; preserving loop" >&2
    return 1
  fi
  if ! first_holder=$(find "$holders_dir" -mindepth 1 -maxdepth 1 -print -quit); then
    echo "ERROR: could not inspect holders for $loop_device; preserving loop" >&2
    return 1
  fi
  if [[ -n "$first_holder" ]]; then
    echo "ERROR: $loop_device still has block holders; preserving loop" >&2
    return 1
  fi
  return 0
}

# Exit 0: exact loop is attached; 1: definitely absent; 2: inspection failed.
# Unlike `losetup /dev/loopN`, this uses a successful full inventory query,
# so a query error can never be mistaken for a safely detached loop.
swapz_test_loop_presence() {
  local loop_device=$1
  local inventory entry
  if ! inventory=$(losetup --list --noheadings --output NAME); then
    echo "ERROR: cannot inventory loop attachments; preserving backing" >&2
    return 2
  fi
  # `read` splits/strips column padding emitted by some losetup builds.
  while read -r entry _; do
    [[ -z "$entry" ]] && continue
    if [[ ! "$entry" =~ ^/dev/loop[0-9]+$ ]]; then
      echo "ERROR: malformed loop inventory entry: $entry" >&2
      return 2
    fi
    [[ "$entry" == "$loop_device" ]] && return 0
  done <<<"$inventory"
  return 1
}

swapz_test_detach_loop() {
  local loop_device=$1
  [[ "$loop_device" =~ ^/dev/loop[0-9]+$ ]] || {
    echo "ERROR: refusing to detach a non-loop device: $loop_device" >&2
    return 1
  }
  if swapz_test_loop_presence "$loop_device"; then
    : # Still attached; verify holders before attempting detach.
  else
    case $? in
      1) return 0 ;; # Confirmed already absent after successful inventory.
      *) return 1 ;; # Inventory command failed: do not delete backing.
    esac
  fi
  swapz_test_check_loop_holders "$loop_device" || return 1
  if ! losetup -d "$loop_device"; then
    echo "ERROR: could not detach test loop $loop_device; preserving backing" >&2
    return 1
  fi
  if swapz_test_loop_presence "$loop_device"; then
    echo "ERROR: test loop $loop_device is still attached; preserving backing" >&2
    return 1
  else
    case $? in
      1) return 0 ;; # Successfully inventoried and confirmed absent.
      *) return 1 ;; # Inspection failure is not proof of detach.
    esac
  fi
}

swapz_test_cleanup_dm_stack() {
  local loop_device=$1
  shift
  local target_name
  for target_name in "$@"; do
    [[ -z "$target_name" ]] && continue
    swapz_test_remove_dm_target "$target_name" || return 1
  done
  if [[ -n "$loop_device" ]]; then
    swapz_test_detach_loop "$loop_device" || return 1
  fi
  return 0
}

swapz_test_stop_child() {
  local child_pid=$1
  local attempt child_state job_pids
  [[ "$child_pid" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: invalid test-owned child PID: $child_pid" >&2
    return 1
  }
  # Never signal an arbitrary PID: require a shell-owned job or positively
  # verify the old child is no longer running (already waited/reaped).
  if ! job_pids=$(jobs -p); then
    echo "ERROR: cannot inspect shell jobs; preserving test stack" >&2
    return 1
  fi
  if ! grep -Fxq "$child_pid" <<<"$job_pids"; then
    if kill -0 "$child_pid" 2>/dev/null; then
      echo "ERROR: child PID $child_pid is running without shell ownership; preserving stack" >&2
      return 1
    fi
    return 0
  fi
  if kill -0 "$child_pid" 2>/dev/null; then
    # Stopped checkpoint jobs need CONT before TERM can be processed.
    if ! kill -CONT "$child_pid" 2>/dev/null ||
       ! kill -TERM "$child_pid" 2>/dev/null; then
      echo "ERROR: failed to stop test child $child_pid" >&2
      return 1
    fi
    for ((attempt=0; attempt<50; ++attempt)); do
      if ! kill -0 "$child_pid" 2>/dev/null; then
        break
      fi
      if ! child_state=$(ps -o stat= -p "$child_pid" 2>/dev/null); then
        # A disappearing child can race ps; if still alive, fail closed.
        if kill -0 "$child_pid" 2>/dev/null; then
          echo "ERROR: cannot inspect live test child $child_pid; preserving stack" >&2
          return 1
        fi
        break
      fi
      [[ "$child_state" == Z* ]] && break
      sleep 0.1
    done
    if kill -0 "$child_pid" 2>/dev/null; then
      if ! child_state=$(ps -o stat= -p "$child_pid" 2>/dev/null); then
        echo "ERROR: cannot verify test child $child_pid stopped; preserving stack" >&2
        return 1
      fi
      if [[ "$child_state" != Z* ]]; then
        echo "ERROR: test child $child_pid did not stop; preserving stack" >&2
        return 1
      fi
    fi
  fi
  # A terminated or already-reaped child cannot keep test I/O active.
  wait "$child_pid" 2>/dev/null || true
  return 0
}

# Always attempt to stop every test-owned I/O child. One failure blocks all
# mapper/loop teardown, but cannot prevent checking the remaining children.
swapz_test_stop_children() {
  local child failed=0
  for child in "$@"; do
    [[ -z "$child" ]] && continue
    swapz_test_stop_child "$child" || failed=1
  done
  (( failed == 0 ))
}
