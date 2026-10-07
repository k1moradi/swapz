#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in dmsetup g++ losetup modprobe timeout truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TMP=$(mktemp -d /dev/shm/swapz-v22-progress.XXXXXX)
TAG="$$-$RANDOM"
IMG="$TMP/backing.img"
REF="$TMP/reference"
LOOP=""
TARGET="swapz-v22-progress-$TAG"

cleanup() {
  dmsetup remove "$TARGET" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

g++ -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror \
  "$ROOT/tests/runtime/reference.cpp" -o "$REF"

truncate -s 3M "$IMG"
LOOP=$(losetup --find --show "$IMG")
modprobe dm-swapz

# Matches the live-GC geometry that exposed the V2.2 forward-progress hang.
dmsetup create "$TARGET" --table "0 2048 swapz $LOOP opportunistic 256"

BEFORE=$(cat "/sys/class/block/$(basename "$LOOP")/stat")
set +e
timeout --signal=TERM --kill-after=5s 120s \
  "$REF" live "/dev/mapper/$TARGET" 10000
rc=$?
set -e
if (( rc != 0 )); then
  echo "live-GC progress regression failed/timed out rc=$rc" >&2
  echo "target status:" >&2
  dmsetup status "$TARGET" >&2 || true
  echo "target table:" >&2
  dmsetup table "$TARGET" >&2 || true
  echo "loop stat before: $BEFORE" >&2
  echo "loop stat after:  $(cat "/sys/class/block/$(basename "$LOOP")/stat")" >&2
  echo "dm tree:" >&2
  dmsetup ls --tree >&2 || true
  exit "$rc"
fi

STATUS=$(dmsetup status "$TARGET")
echo "status: $STATUS"
grep -q "failed=0" <<<"$STATUS" || {
  echo "target entered failed state" >&2
  exit 1
}
grep -Eq "gc_victims=[1-9][0-9]*" <<<"$STATUS" || {
  echo "live-GC progress test did not reach GC" >&2
  exit 1
}
grep -Eq "gc_pages=[1-9][0-9]*" <<<"$STATUS" || {
  echo "live-GC progress test did not move live data" >&2
  exit 1
}

echo "V2.2 asynchronous completion/live-GC forward progress: PASS"
