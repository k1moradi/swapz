#!/usr/bin/env bash
# Source-only mock regression. Does not require root, DM, or null_blk.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/streaming-benchmark-teardown.sh"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
TARGET="swapz-v22-stream-mock-$$"
NULL_CFG="$TMP/null_blk"
mkdir "$NULL_CFG"
printf '1\n' >"$NULL_CFG/power"
CONFIGFS_MOUNTED_BY_US=0
TARGET_ACTIVE=1

MOCK_EXISTS=1
MOCK_BUSY=0
MOCK_FALSE_REMOVAL=0
MOCK_RMDIR_CALLED=0
MOCK_REMOVES=0

dmsetup() {
  case "$1" in
    remove)
      [[ "$2" == "--retry" && "$3" == "$TARGET" ]] || return 99
      MOCK_REMOVES=$((MOCK_REMOVES + 1))
      if (( MOCK_BUSY )); then
        echo "Device or resource busy" >&2
        return 16
      fi
      if (( ! MOCK_FALSE_REMOVAL )); then
        MOCK_EXISTS=0
      fi
      return 0
      ;;
    info)
      [[ "$2" == "$TARGET" ]] || return 99
      (( MOCK_EXISTS ))
      ;;
    status)
      [[ "$2" == "$TARGET" ]] || return 99
      printf 'mock status\n'
      ;;
    *)
      echo "unexpected mock dmsetup invocation: $*" >&2
      return 99
      ;;
  esac
}

# Mock configfs rmdir: its 'power' attribute is virtual, not an actual file.
rmdir() {
  [[ "$1" == "$NULL_CFG" ]] || return 99
  MOCK_RMDIR_CALLED=1
  return 0
}

# Case 1: busy removal must preserve both the DM target and powered backing.
MOCK_BUSY=1
if swapz_benchmark_cleanup_resources; then
  echo "FAIL: busy target cleanup succeeded" >&2
  exit 1
fi
[[ $(cat "$NULL_CFG/power") == 1 ]]
(( TARGET_ACTIVE == 1 && MOCK_EXISTS == 1 && MOCK_RMDIR_CALLED == 0 ))
echo "busy target preserves backing: PASS"

# Case 2: even a successful removal command must be followed by verification.
MOCK_BUSY=0
MOCK_FALSE_REMOVAL=1
if swapz_benchmark_cleanup_resources; then
  echo "FAIL: unremoved target was accepted" >&2
  exit 1
fi
[[ $(cat "$NULL_CFG/power") == 1 ]]
(( TARGET_ACTIVE == 1 && MOCK_EXISTS == 1 && MOCK_RMDIR_CALLED == 0 ))
echo "false-positive removal preserves backing: PASS"

# Case 3: once target removal is confirmed, null_blk can be powered down.
MOCK_FALSE_REMOVAL=0
swapz_benchmark_cleanup_resources
[[ $(cat "$NULL_CFG/power") == 0 ]]
(( TARGET_ACTIVE == 0 && MOCK_EXISTS == 0 && MOCK_RMDIR_CALLED == 1 ))
echo "confirmed removal precedes backing poweroff: PASS"

# Case 4: NBD shutdown must be a preservation-only path until pidfd
# ownership is available. Numeric test PID must NEVER be signaled or probed.
BACKEND_KIND=nbd
NBD_PID=424242
TARGET_ACTIVE=1
MOCK_EXISTS=1
MOCK_FALSE_REMOVAL=0
MOCK_BUSY=0
printf '1\n' >"$NULL_CFG/power"
kill() { echo "FAIL: numeric PID signaling/probing attempted: $*" >&2; exit 97; }
if swapz_benchmark_cleanup_resources; then
  echo "FAIL: unqualified NBD teardown authorized cleanup" >&2
  exit 1
fi
[[ $(cat "$NULL_CFG/power") == 1 ]]
(( MOCK_EXISTS == 0 && TARGET_ACTIVE == 0 ))
echo "unqualified NBD preserves backing without numeric PID signaling: PASS"

echo "V2.2 benchmark teardown safety: PASS"
