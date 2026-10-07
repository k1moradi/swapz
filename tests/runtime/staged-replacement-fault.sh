#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in blockdev cmp dd dmsetup losetup modprobe python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

TMP=$(mktemp -d /dev/shm/swapz-v22-replacement-fault.XXXXXX)
TAG="$$-$RANDOM"
IMG="$TMP/backing.img"
LOWER="swapz-v22-repl-lower-$TAG"
TARGET="swapz-v22-repl-$TAG"
LOOP=""
KEEP_STATE=0

cleanup() {
  if (( KEEP_STATE )); then
    echo "preserving failed state: target=$TARGET lower=$LOWER loop=$LOOP tmp=$TMP" >&2
    return
  fi
  dmsetup remove "$TARGET" >/dev/null 2>&1 || true
  dmsetup remove "$LOWER" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

truncate -s 16M "$IMG"
LOOP=$(losetup --find --show "$IMG")
SECTORS=$(blockdev --getsz "$LOOP")

modprobe dm-error
modprobe dm-swapz

dmsetup create "$LOWER" --table "0 $SECTORS linear $LOOP 0"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER staged 128"

python3 - "$TMP/old.bin" "$TMP/new.bin" <<'PY'
from pathlib import Path
import os, sys
# Old data compresses and is flushed to a persistent mapping.
Path(sys.argv[1]).write_bytes((b"swapz-old-authoritative-" * 200)[:4096].ljust(4096, b"O"))
# Replacement is intentionally incompressible so staged mode must not early-complete it.
Path(sys.argv[2]).write_bytes(os.urandom(4096))
PY

dd if="$TMP/old.bin" of="/dev/mapper/$TARGET" bs=4096 count=1 \
   oflag=direct conv=notrunc,fsync status=none

dd if="/dev/mapper/$TARGET" of="$TMP/old-read.bin" bs=4096 count=1 \
   iflag=direct status=none
cmp "$TMP/old.bin" "$TMP/old-read.bin"

# Turn the already-open lower mapped device into a deterministic failure.
dmsetup suspend "$LOWER"
dmsetup load "$LOWER" --table "0 $SECTORS error"
dmsetup resume "$LOWER"

# The raw replacement must fail rather than early-complete.
dd if="$TMP/new.bin" of="/dev/mapper/$TARGET" bs=4096 count=1 \
   oflag=direct conv=notrunc status=none 2>"$TMP/replacement.err" &
WRITER_PID=$!
DEADLINE=$((SECONDS + 30))
while kill -0 "$WRITER_PID" 2>/dev/null; do
  if (( SECONDS >= DEADLINE )); then
    echo "raw replacement hung instead of failing; writer_pid=$WRITER_PID" >&2
    ps -p "$WRITER_PID" -o pid,ppid,stat,wchan:32,etime,cmd >&2 || true
    if [[ -r "/proc/$WRITER_PID/stack" ]]; then
      cat "/proc/$WRITER_PID/stack" >&2 || true
    fi
    dmsetup status "$TARGET" >&2 || true
    dmsetup table "$TARGET" >&2 || true
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
RC=$?
set -e
if (( RC == 0 )); then
  echo "raw replacement unexpectedly succeeded over failing lower device" >&2
  exit 1
fi

STATUS=$(dmsetup status "$TARGET")
echo "status after replacement failure: $STATUS"
grep -q 'failed=1' <<<"$STATUS" || {
  echo "target did not enter failed state after lower replacement failure" >&2
  exit 1
}

# Restore the lower path without touching swapz.  A staged-mode READ is allowed after
# target failure so swapoff/recovery can retrieve the last good persistent data.
dmsetup suspend "$LOWER"
dmsetup load "$LOWER" --table "0 $SECTORS linear $LOOP 0"
dmsetup resume "$LOWER"

dd if="/dev/mapper/$TARGET" of="$TMP/recovered.bin" bs=4096 count=1 \
   iflag=direct status=none
cmp "$TMP/old.bin" "$TMP/recovered.bin"

STATUS2=$(dmsetup status "$TARGET")
echo "status after old-mapping recovery: $STATUS2"
echo "V2.2 failed raw replacement preserves previous authoritative mapping: PASS"
