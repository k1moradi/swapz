#!/usr/bin/env bash
# Source-only safety regression. Never opens NBD or Device Mapper devices.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/streaming-benchmark-teardown.sh"

TARGET="swapz-v22-stream-nbd-mock-$$"
TARGET_ACTIVE=1
BACKEND_KIND=nbd
NBD_PID=424242
NULL_CFG=/nonexistent/test-only
CONFIGFS_MOUNTED_BY_US=0
MOCK_EXISTS=1
MOCK_BUSY=1
MOCK_FALSE_REMOVE=0
MOCK_RUNNING=1
MOCK_SIGNAL_COUNT=0
MOCK_WAIT_COUNT=0

dmsetup() {
  case "$1" in
    remove)
      [[ "$2" == "--retry" && "$3" == "$TARGET" ]] || return 99
      if (( MOCK_BUSY )); then return 16; fi
      if (( ! MOCK_FALSE_REMOVE )); then MOCK_EXISTS=0; fi
      return 0 ;;
    info)
      [[ "$2" == "$TARGET" ]] || return 99
      (( MOCK_EXISTS )) ;;
    status) echo "mock-target"; return 0 ;;
    *) return 99 ;;
  esac
}
kill() {
  case "$1" in
    -0) [[ "$2" == "$NBD_PID" ]] && (( MOCK_RUNNING )) ;;
    -TERM)
      [[ "$2" == "$NBD_PID" ]] || return 99
      MOCK_SIGNAL_COUNT=$((MOCK_SIGNAL_COUNT + 1))
      MOCK_RUNNING=0 ;;
    *) return 99 ;;
  esac
}
ps() { return 0; }
wait() { [[ "$1" == "$NBD_PID" ]] && MOCK_WAIT_COUNT=$((MOCK_WAIT_COUNT+1)); }

if swapz_benchmark_cleanup_resources; then
  echo "FAIL: busy DM target accepted by NBD teardown" >&2
  exit 1
fi
(( MOCK_EXISTS && TARGET_ACTIVE && MOCK_SIGNAL_COUNT == 0 ))
echo "busy DM preserves NBD backend: PASS"

MOCK_BUSY=0
MOCK_FALSE_REMOVE=1
if swapz_benchmark_cleanup_resources; then
  echo "FAIL: false-positive DM remove accepted by NBD teardown" >&2
  exit 1
fi
(( MOCK_EXISTS && TARGET_ACTIVE && MOCK_SIGNAL_COUNT == 0 ))
echo "false-positive remove preserves NBD backend: PASS"

MOCK_FALSE_REMOVE=0
swapz_benchmark_cleanup_resources
(( ! MOCK_EXISTS && ! TARGET_ACTIVE ))
(( MOCK_SIGNAL_COUNT == 1 && MOCK_WAIT_COUNT == 1 ))
echo "verified DM removal precedes NBD shutdown: PASS"

echo "V2.2 size-aware NBD teardown mock regression: PASS"
