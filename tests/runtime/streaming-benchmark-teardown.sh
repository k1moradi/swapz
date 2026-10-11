#!/usr/bin/env bash
# Sourced by streaming-benchmark.sh. Keep the teardown contract independently
# testable without requiring a real Device Mapper/null_blk device.
#
# Required caller globals: TARGET, TARGET_ACTIVE, NULL_CFG,
# CONFIGFS_MOUNTED_BY_US. Never operate on non-test DM devices.

swapz_benchmark_remove_target() {
  if (( ! TARGET_ACTIVE )); then
    return 0
  fi

  # For the production runner, explicitly validate the unique DM UUID
  # before EVER removing a target by its generated name. No path from a
  # partial create may remove a foreign mapping with a colliding name.
  local removal_identity="$TARGET"
  if declare -F swapz_benchmark_verify_owned_target >/dev/null; then
    swapz_benchmark_verify_owned_target || {
      echo "ERROR: target UUID not verified; refusing to remove any DM mapping." >&2
      return 1
    }
    # Resolve by UUID as well as validating it: if a name is replaced in
    # the narrow interval after our check, never remove the replacement.
    removal_identity="$TARGET_UUID"
  fi

  # --retry handles transient opens from udev or consumers just exiting.
  # Never use --force or --deferred: the backing must not be powered off
  # until the DM target is actually gone.
  # A production runner provides the bounded command adapter. Rootless
  # teardown regression fixtures deliberately keep using their mocked
  # dmsetup when sourced independently. Never force/defer removal.
  if declare -F swapz_benchmark_bounded >/dev/null; then
    if ! swapz_benchmark_bounded "owned DM normal removal" 20s \
        dmsetup remove --retry "$removal_identity"; then
      echo "ERROR: DM target removal uncertain; leave backing powered." >&2
      return 1
    fi
  elif ! dmsetup remove --retry "$removal_identity"; then
    echo "ERROR: normal DM removal failed for test target $TARGET; leaving backing powered." >&2
    dmsetup info "$TARGET" >&2 || true
    dmsetup status "$TARGET" >&2 || true
    return 1
  fi

  # A successful remove is insufficient; proof of disappearance is required.
  # A timed-out enumeration must NEVER be interpreted as absence.
  if declare -F swapz_benchmark_target_exists >/dev/null; then
    local probe_rc=0
    swapz_benchmark_target_exists || probe_rc=$?
    if (( probe_rc != 1 )); then
      echo "ERROR: owned DM target still exists or its identity is uncertain." >&2
      BENCH_QUARANTINE=1
      return 1
    fi
  elif dmsetup info "$TARGET" >/dev/null 2>&1; then
    echo "ERROR: test DM target $TARGET still exists after removal; leaving backing powered." >&2
    return 1
  fi

  TARGET_ACTIVE=0
  return 0
}

swapz_benchmark_cleanup_resources() {
  # The active flag is set immediately after create succeeds. Also check the
  # exact test name defensively for a partial create/udev failure.
  if (( TARGET_ACTIVE )); then
    swapz_benchmark_remove_target || return 1
  elif declare -F swapz_benchmark_target_exists >/dev/null; then
    # Production path: distinguish confirmed absence from uncertainty.
    local target_probe=0
    swapz_benchmark_target_exists || target_probe=$?
    if (( target_probe == 0 )); then
      TARGET_ACTIVE=1
      swapz_benchmark_remove_target || return 1
    elif (( target_probe != 1 )); then
      echo "ERROR: DM ownership query uncertain; preserve null_blk." >&2
      return 1
    fi
  elif dmsetup info "$TARGET" >/dev/null 2>&1; then
    TARGET_ACTIVE=1
    swapz_benchmark_remove_target || return 1
  fi

  # NBD is not qualified for safe backend teardown. Historical Bash PID
  # liveness checks and numeric-PID kill/wait can target a reused PID. The
  # streaming benchmark rejects NBD mode *before* any launch; retain this
  # fail-closed guard as defense in depth for sourced callers. It deliberately
  # does not signal, detach, or claim a clean server exit.
  if [[ "${BACKEND_KIND:-null_blk}" == "nbd" ]]; then
    echo "ERROR: NBD backend teardown requires a verified pidfd-owned server; preserving backing and diagnostics." >&2
    return 1
  fi

  # Strict dependency ordering: never power off null_blk before removing DM.
  if [[ -d "$NULL_CFG" ]]; then
    if [[ "${NULL_CFG_OWNED:-0}" != 1 ]]; then
      echo "ERROR: null_blk config is not positively owned by this run; refusing to power off." >&2
      return 1
    fi
    if declare -F swapz_benchmark_bounded >/dev/null; then
      swapz_benchmark_bounded "test-owned null_blk powerdown" 12s \
          bash -c 'printf "0\n" > "$1"' _ "$NULL_CFG/power" || return 1
    elif ! echo 0 >"$NULL_CFG/power"; then
      echo "ERROR: could not power off test null_blk $NULL_CFG" >&2
      return 1
    fi
    if declare -F swapz_benchmark_bounded >/dev/null; then
      swapz_benchmark_bounded "test null_blk config removal" 10s rmdir "$NULL_CFG" || return 1
    elif ! rmdir "$NULL_CFG"; then
      echo "ERROR: could not remove test null_blk config $NULL_CFG" >&2
      return 1
    fi
    NULL_CFG_OWNED=0
  fi

  if (( CONFIGFS_MOUNTED_BY_US )); then
    if declare -F swapz_benchmark_bounded >/dev/null; then
      swapz_benchmark_bounded "owned configfs unmount" 10s umount /sys/kernel/config || return 1
    elif ! umount /sys/kernel/config; then
      echo "ERROR: could not unmount test-owned configfs" >&2
      return 1
    fi
    CONFIGFS_MOUNTED_BY_US=0
  fi
  return 0
}
