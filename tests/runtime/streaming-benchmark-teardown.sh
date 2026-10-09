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

  # --retry handles transient opens from udev or consumers just exiting.
  # Never use --force or --deferred: the backing must not be powered off
  # until the DM target is actually gone.
  if ! dmsetup remove --retry "$TARGET"; then
    echo "ERROR: normal DM removal failed for test target $TARGET; leaving backing powered." >&2
    dmsetup info "$TARGET" >&2 || true
    dmsetup status "$TARGET" >&2 || true
    return 1
  fi

  # A successful remove command is not enough: verify that the name is gone.
  if dmsetup info "$TARGET" >/dev/null 2>&1; then
    echo "ERROR: test DM target $TARGET still exists after removal; leaving backing powered." >&2
    return 1
  fi

  TARGET_ACTIVE=0
  return 0
}

swapz_benchmark_cleanup_resources() {
  # The active flag is set immediately after create succeeds. Also check the
  # exact test name defensively for a partial create/udev failure.
  if (( TARGET_ACTIVE )) || dmsetup info "$TARGET" >/dev/null 2>&1; then
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
    if ! echo 0 >"$NULL_CFG/power"; then
      echo "ERROR: could not power off test null_blk $NULL_CFG" >&2
      return 1
    fi
    if ! rmdir "$NULL_CFG"; then
      echo "ERROR: could not remove test null_blk config $NULL_CFG" >&2
      return 1
    fi
  fi

  if (( CONFIGFS_MOUNTED_BY_US )); then
    if ! umount /sys/kernel/config; then
      echo "ERROR: could not unmount test-owned configfs" >&2
      return 1
    fi
    CONFIGFS_MOUNTED_BY_US=0
  fi
  return 0
}
