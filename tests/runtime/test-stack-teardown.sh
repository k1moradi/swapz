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
  if awk -v name="$target_name" '$1 == name { found = 1 } END { exit !found }' <<<"$dm_mappings"; then
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
  local holders_dir="/sys/class/block/$loop_name/holders"
  if [[ ! -d "$holders_dir" ]]; then
    echo "ERROR: cannot verify holders for $loop_device; preserving loop" >&2
    return 1
  fi
  if [[ -n "$(find "$holders_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "ERROR: $loop_device still has block holders; preserving loop" >&2
    return 1
  fi
  return 0
}

swapz_test_detach_loop() {
  local loop_device=$1
  [[ "$loop_device" =~ ^/dev/loop[0-9]+$ ]] || {
    echo "ERROR: refusing to detach a non-loop device: $loop_device" >&2
    return 1
  }
  swapz_test_check_loop_holders "$loop_device" || return 1
  if ! losetup -d "$loop_device"; then
    echo "ERROR: could not detach test loop $loop_device; preserving backing" >&2
    return 1
  fi
  if losetup "$loop_device" >/dev/null 2>&1; then
    echo "ERROR: test loop $loop_device is still attached; preserving backing" >&2
    return 1
  fi
  return 0
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
  local attempt child_state
  [[ "$child_pid" =~ ^[1-9][0-9]*$ ]] || {
    echo "ERROR: invalid test-owned child PID: $child_pid" >&2
    return 1
  }
  if kill -0 "$child_pid" 2>/dev/null; then
    if ! kill -TERM "$child_pid" 2>/dev/null; then
      echo "ERROR: failed to stop test child $child_pid" >&2
      return 1
    fi
    for ((attempt=0; attempt<50; ++attempt)); do
      if ! kill -0 "$child_pid" 2>/dev/null; then
        break
      fi
      child_state=$(ps -o stat= -p "$child_pid" 2>/dev/null || true)
      [[ "$child_state" == Z* ]] && break
      sleep 0.1
    done
    child_state=$(ps -o stat= -p "$child_pid" 2>/dev/null || true)
    if [[ -n "$child_state" && "$child_state" != Z* ]]; then
      echo "ERROR: test child $child_pid did not stop; preserving stack" >&2
      return 1
    fi
  fi
  # SIGTERM may yield a nonzero exit code: this is expected during cleanup.
  wait "$child_pid" 2>/dev/null || true
  return 0
}
