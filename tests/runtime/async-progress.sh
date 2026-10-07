#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in dmsetup g++ losetup modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TMP=$(mktemp -d /dev/shm/swapz-v22-progress.XXXXXX)
TAG="$$-$RANDOM"
IMG="$TMP/backing.img"
REF="$TMP/reference"
LOOP=""
TARGET="swapz-v22-progress-$TAG"
KEEP_STATE=0

cleanup() {
  if (( KEEP_STATE )); then
    echo "preserving failed state: target=$TARGET loop=$LOOP tmp=$TMP" >&2
    return
  fi
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
"$REF" live "/dev/mapper/$TARGET" 10000 &
WRITER_PID=$!
DEADLINE=$((SECONDS + 120))

while kill -0 "$WRITER_PID" 2>/dev/null; do
  if (( SECONDS >= DEADLINE )); then
    echo "live-GC progress regression exceeded 120 seconds; writer_pid=$WRITER_PID" >&2
    echo "writer state:" >&2
    ps -p "$WRITER_PID" -o pid,ppid,stat,wchan:32,etime,cmd >&2 || true
    if [[ -r "/proc/$WRITER_PID/stack" ]]; then
      echo "writer stack:" >&2
      cat "/proc/$WRITER_PID/stack" >&2 || true
    fi
    echo "target status:" >&2
    dmsetup status "$TARGET" >&2 || true
    echo "target table:" >&2
    dmsetup table "$TARGET" >&2 || true
    echo "loop stat before: $BEFORE" >&2
    echo "loop stat after:  $(cat "/sys/class/block/$(basename "$LOOP")/stat")" >&2
    echo "dm tree:" >&2
    dmsetup ls --tree >&2 || true
    kill -TERM "$WRITER_PID" 2>/dev/null || true
    sleep 1
    kill -KILL "$WRITER_PID" 2>/dev/null || true
    disown "$WRITER_PID" 2>/dev/null || true
    KEEP_STATE=1
    exit 124
  fi
  sleep 0.1
done

set +e
wait "$WRITER_PID"
rc=$?
set -e
if (( rc != 0 )); then
  echo "live-GC progress regression failed rc=$rc" >&2
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
