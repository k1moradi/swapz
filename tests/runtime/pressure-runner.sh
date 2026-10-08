#!/usr/bin/env bash
# Source-only pressure fixture controller. No actions at import time.
# Caller provides fixture-owned TMP/ROOT/NAME/DEVICE variables.
# Do not invoke outside the disposable pressure fixture or rootless mocks.

swapz_pressure_run_unit() {
  local unit=$1 size=$2 mem=$3 swap=$4 require_gc=$5
  local dir="$TMP/$unit" token ready=0 cg="" state="" attempt
  # Refuse to reuse checkpoint files or stale release tokens.
  if [[ -e "$dir" ]]; then
    echo "ERROR: pressure checkpoint directory already exists: $dir" >&2
    return 1
  fi
  if ! mkdir -- "$dir"; then
    echo "ERROR: cannot create pressure checkpoint directory $dir" >&2
    return 1
  fi
  if [[ "$require_gc" != 0 && "$require_gc" != 1 ]]; then
    echo "ERROR: invalid pressure GC requirement $require_gc" >&2
    return 1
  fi
  token=$(python3 -c 'import secrets; print(secrets.token_hex(16))') || return 1
  # Only exact, test-owned system.slice units are accepted in teardown.
  systemd-run --unit="$unit" --slice=system.slice --property="MemoryMax=$mem" --property="MemorySwapMax=$swap" \
    --property=TasksMax=32 --property=RuntimeMaxSec=300 \
    --no-block /usr/bin/python3 "$ROOT/tests/runtime/pressure-helper.py" "$size" "$dir" "$token" >/dev/null || {
    echo "ERROR: failed to launch pressure checkpoint unit $unit" >&2
    return 1
  }

  # The helper publishes filled only after touching all pages. The matching
  # token, rather than MainPID/ps stop state, proves which phase is waiting.
  for ((attempt=0; attempt<300; ++attempt)); do
    if [[ -e "$dir/filled" || -L "$dir/filled" ]]; then
      # Use the bounded nofollow regular-file validator, not cat: a FIFO
      # or symlink must not block or spoof checkpoint readiness.
      if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" check "$dir" "$token" filled; then
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
    sleep 0.2 || return 1
  done
  (( ready )) || { echo "$unit did not reach filled checkpoint" >&2; return 1; }
  cg=$(systemctl show "$unit" -p ControlGroup --value) || return 1
  if [[ "$cg" != "/system.slice/$unit" ]]; then
    echo "ERROR: unexpected pressure unit ControlGroup $cg" >&2
    return 1
  fi
  local filled_swap filled_used filled_status
  if ! filled_swap=$(cat -- "/sys/fs/cgroup$cg/memory.swap.current") ||
     ! filled_used=$(python3 "$ROOT/tests/runtime/pressure-swap-inventory.py" "$DEVICE") ||
     ! filled_status=$(dmsetup status "$NAME"); then
    echo "ERROR: cannot inspect filled pressure checkpoint metrics for $unit" >&2
    return 1
  fi
  echo "$unit filled checkpoint cgroup=$cg memory.swap.current=$filled_swap /proc/swaps_used_kib=$filled_used"
  if [[ ! "$filled_status" =~ (^|[[:space:]])failed=0([[:space:]]|$) ]]; then
    echo "ERROR: filled pressure DM status indicates a failure for $unit" >&2
    return 1
  fi
  echo "$unit swapz status: $filled_status"
  if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" release "$dir" "$token" filled; then
    echo "ERROR: could not release filled checkpoint for $unit" >&2
    return 1
  fi

  ready=0
  for ((attempt=0; attempt<300; ++attempt)); do
    if [[ -e "$dir/verified" || -L "$dir/verified" ]]; then
      if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" check "$dir" "$token" verified; then
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
    sleep 0.2 || return 1
  done
  (( ready )) || { echo "$unit did not reach verified checkpoint" >&2; return 1; }
  local swap_current swap_used status gc_pages
  if ! swap_current=$(cat -- "/sys/fs/cgroup$cg/memory.swap.current") ||
     ! swap_used=$(python3 "$ROOT/tests/runtime/pressure-swap-inventory.py" "$DEVICE") ||
     ! status=$(dmsetup status "$NAME"); then
    echo "ERROR: cannot inspect verified pressure accounting for $unit" >&2
    return 1
  fi
  echo "$unit verified checkpoint cgroup memory.swap.current=$swap_current /proc/swaps_used_kib=$swap_used"
  echo "$unit swapz verified status: $status"
  if [[ ! "$status" =~ (^|[[:space:]])failed=0([[:space:]]|$) ||
        ! "$swap_current" =~ ^[0-9]+$ || ! "$swap_used" =~ ^[0-9]+$ ]] ||
     ! (( 10#$swap_current > 0 && 10#$swap_used > 0 )); then
    echo "ERROR: failed or nonpositive verified pressure accounting for $unit" >&2
    return 1
  fi
  if (( require_gc )); then
    if ! gc_pages=$(sed -n 's/.*gc_pages=\([0-9][0-9]*\).*/\1/p' <<<"$status") ||
       [[ ! "$gc_pages" =~ ^[0-9]+$ ]] ||
       ! (( 10#$gc_pages > 0 )); then
      echo "ERROR: required GC pages missing or zero for $unit" >&2
      return 1
    fi
  fi
  if ! python3 "$ROOT/tests/runtime/pressure_checkpoint.py" release "$dir" "$token" verified; then
    echo "ERROR: could not release verified checkpoint for $unit" >&2
    return 1
  fi
  state=""
  for ((attempt=0; attempt<300; ++attempt)); do
    state=$(systemctl show "$unit" -p ActiveState --value 2>/dev/null) || return 1
    [[ "$state" != active && "$state" != activating ]] && break
    sleep 0.2 || return 1
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
