#!/usr/bin/env bash
# Source actual pressure controller, mock every system/device dependency.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
source "$ROOT/tests/runtime/pressure-runner.sh"
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
UNIT=swapz-test-controller.service
NAME=swapz-test-controller
DEVICE=/dev/mapper/swapz-test-controller
TOKEN=0123456789abcdef0123456789abcdef
EVENTS="$TMP/events"
SCENARIO=normal
note() { printf '%s\n' "$1" >>"$EVENTS"; }
systemd-run() {
  note start
  [[ "$*" == *"--unit=$UNIT"* && "$*" == *"--slice=system.slice"* ]] || return 91
  local dir="${@: -2}" token="${@: -1}"
  [[ "$dir" == "$TMP/$UNIT" && "$token" == "$TOKEN" ]] || return 91
  case "$SCENARIO" in
    missing_filled|early_exit) ;;
    bad_filled) printf 'filled:bad\n' >"$dir/filled" ;;
    symlink_filled)
      printf 'filled:%s\n' "$token" >"$dir/good"
      ln -s good "$dir/filled" ;;
    fifo_filled) mkfifo "$dir/filled" ;;
    *) printf 'filled:%s\n' "$token" >"$dir/filled" ;;
  esac
}
python3() {
  if [[ "${1:-}" == -c ]]; then
    [[ "$2" == 'import secrets; print(secrets.token_hex(16))' ]] || return 91
    printf '%s\n' "$TOKEN"
    return
  fi
  [[ "$1" == "$ROOT/tests/runtime/pressure_checkpoint.py" ]] || return 91
  note "$2:$5"
  command python3 "$@" >/dev/null 2>&1 || return 1
  if [[ "$2:$5" == release:filled ]]; then
    case "$SCENARIO" in
      missing_verified) ;;
      bad_verified) printf 'verified:bad\n' >"$3/verified" ;;
      symlink_verified)
        printf 'verified:%s\n' "$TOKEN" >"$3/good"
        ln -s good "$3/verified" ;;
      *) printf 'verified:%s\n' "$TOKEN" >"$3/verified" ;;
    esac
  fi
}
systemctl() {
  [[ "$1" == show && "$2" == "$UNIT" && "$3" == -p && "$5" == --value ]] || return 91
  note "systemctl:$4"
  case "$4" in
    ActiveState)
      if [[ "$SCENARIO" == early_exit || -f "$TMP/$UNIT/release-verified" ]]; then
        printf 'inactive\n'
      else printf 'active\n'; fi ;;
    ControlGroup)
      if [[ "$SCENARIO" == bad_cgroup ]]; then printf '/system.slice/wrong.service\n'
      else printf '/system.slice/%s\n' "$UNIT"; fi ;;
    Result)
      if [[ "$SCENARIO" == bad_result ]]; then printf 'exit-code\n'
      else printf 'success\n'; fi ;;
    ExecMainStatus) printf '0\n' ;;
    *) return 91 ;;
  esac
}
cat() {
  [[ "$1" == -- && "$2" == "/sys/fs/cgroup/system.slice/$UNIT/memory.swap.current" ]] || return 91
  if [[ "$SCENARIO" == no_memory_swap ]]; then printf '0\n'
  else printf '4096\n'; fi
}
awk() {
  [[ "$*" == *"/proc/swaps"* ]] || return 91
  if [[ "$*" == *"used+0"* ]]; then
    if [[ "$SCENARIO" == no_swap_used ]]; then printf '0\n'
    else printf '16\n'; fi
  else printf 'used=16\n'; fi
}
dmsetup() {
  [[ "$1" == status && "$2" == "$NAME" ]] || return 91
  case "$SCENARIO" in
    bad_status) printf '0 1024 swapz failed=1 gc_pages=5\n' ;;
    status_error) return 5 ;;
    no_gc) printf '0 1024 swapz failed=0 gc_pages=0\n' ;;
    *) printf '0 1024 swapz failed=0 gc_pages=5\n' ;;
  esac
}
sleep() { [[ "$1" == 0.2 ]]; }
kill() { echo 'UNSAFE kill' >&2; return 91; }
swapon() { return 91; }; swapoff() { return 91; }
losetup() { return 91; }; modprobe() { return 91; }; mkswap() { return 91; }
run_case() {
  local expected=$2 required_gc=${3:-1} rc=0
  SCENARIO=$1
  rm -rf -- "$TMP/$UNIT"
  : >"$EVENTS"
  swapz_pressure_run_unit "$UNIT" 1 2M 4M "$required_gc" >"$TMP/stdout" 2>"$TMP/stderr" || rc=$?
  if [[ "$expected" == pass ]]; then
    if (( rc )); then
      echo "FAIL: $SCENARIO returned $rc" >&2
      command cat "$TMP/stderr" >&2; return 1
    fi
    grep -Fxq 'release:verified' "$EVENTS"
  else
    (( rc != 0 )) || { echo "FAIL: $SCENARIO succeeded" >&2; return 1; }
    if [[ "$expected" == no_filled ]]; then
      if grep -Fxq 'release:filled' "$EVENTS"; then return 1; fi
    elif [[ "$expected" == no_verified ]]; then
      if grep -Fxq 'release:verified' "$EVENTS"; then
        echo "FAIL: $SCENARIO released verified despite failed guard" >&2
        return 1
      fi
    fi
  fi
  echo "pressure controller $SCENARIO: PASS"
}
run_case normal pass
run_case normal pass 0
run_case bad_filled no_filled
run_case symlink_filled no_filled
run_case fifo_filled no_filled
run_case missing_filled no_filled
run_case early_exit no_filled
run_case bad_cgroup no_filled
run_case bad_verified no_verified
run_case symlink_verified no_verified
run_case missing_verified no_verified
run_case no_memory_swap no_verified
run_case no_swap_used no_verified
run_case bad_status no_verified
run_case status_error no_verified
run_case no_gc no_verified
run_case bad_result fail_after
echo 'rootless production pressure controller: PASS'
