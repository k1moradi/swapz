#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in blkdiscard cmp dd dmsetup losetup modprobe python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/test-stack-teardown.sh"
TMP=$(mktemp -d /dev/shm/swapz-v22-recall.XXXXXX)
TAG="$$-$RANDOM"
IMG="$TMP/backing.img"
LOOP=""
DELAY="swapz-v22-recall-delay-$TAG"
TARGET="swapz-v22-recall-$TAG"
WRITER=""
PIDA=""
PIDB=""

cleanup() {
  local exit_status=$?
  trap - EXIT
  set +e
  # A failed/interrupted dual read may leave two test-owned I/O children.
  # Share the exact stop-then-cleanup decision with rootless integration
  # regressions; no DM/loop teardown if ANY child is still running.
  local teardown_result=0
  swapz_test_stop_children_then_cleanup_stack "$LOOP" "$TARGET" "$DELAY" \
    "$WRITER" "$PIDA" "$PIDB" || teardown_result=$?
  if (( teardown_result == 2 )); then
    echo "ERROR: recall I/O child still active; preserving test stack and $TMP" >&2
    (( exit_status != 0 )) || exit_status=1
  elif (( teardown_result != 0 )); then
    echo "ERROR: recall stack teardown incomplete; preserving backing and $TMP" >&2
    (( exit_status != 0 )) || exit_status=1
  elif (( exit_status == 0 )); then
    if rm -rf -- "$TMP"; then
      echo 'V2.2 staged A/B recall and unsent cancellation: PASS'
    else
      echo "ERROR: could not remove test directory $TMP" >&2
      exit_status=1
    fi
  else
    echo "ERROR: recall fixture failed; diagnostic files preserved at $TMP" >&2
  fi
  exit "$exit_status"
}
trap cleanup EXIT

python3 - "$TMP/pages.bin" <<'PY'
from pathlib import Path
import random, sys

rng = random.Random(0x5A7A2202)
out = bytearray()
# Keep the writer short enough that the shell reaches the recall checks while
# the first 500 ms lower write is still active. A larger fixture can advance
# past the intended A/B staged-buffer window before the checks begin.
for page in range(9):
    random_half = bytes(rng.randrange(256) for _ in range(2048))
    repeated = bytes([(page * 17 + 3) & 0xff]) * 2048
    out += random_half + repeated
Path(sys.argv[1]).write_bytes(out)
PY

truncate -s 16M "$IMG"
LOOP=$(losetup --find --show "$IMG")
modprobe dm-delay
modprobe dm-swapz

dmsetup create "$DELAY" --table "0 32768 delay $LOOP 0 500 $LOOP 0 500"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$DELAY staged 128"

status_value() {
  local key=$1
  dmsetup status "$TARGET" | sed -n "s/.*\\b${key}=\\([^ ]*\\).*/\\1/p"
}

wait_state() {
  local min_fill=$1
  local deadline=$((SECONDS + 10))
  while (( SECONDS < deadline )); do
    local inflight fill failed
    inflight=$(status_value inflight_blocks)
    fill=$(status_value fill_blocks)
    failed=$(status_value failed)
    [[ "$failed" == 0 ]] || {
      echo "target failed while waiting for buffer state" >&2
      dmsetup status "$TARGET" >&2
      exit 1
    }
    if [[ "$inflight" =~ ^[0-9]+$ && "$fill" =~ ^[0-9]+$ ]] &&
       (( inflight > 0 && fill >= min_fill )); then
      echo "BUFFER_STATE inflight_blocks=$inflight fill_blocks=$fill"
      return 0
    fi
    sleep 0.01
  done
  echo "timed out waiting for A in-flight and B filling" >&2
  dmsetup status "$TARGET" >&2
  exit 1
}

read_page() {
  local page=$1 out=$2 expected=$3
  local start end
  dd if="$TMP/pages.bin" of="$expected" bs=4096 skip="$page" count=1 status=none
  start=$(date +%s%N)
  dd if="/dev/mapper/$TARGET" of="$out" bs=4096 skip="$page" count=1 iflag=direct status=none
  end=$(date +%s%N)
  cmp "$expected" "$out"
  echo $((end - start))
}

# With staged compressed writes, the first page can become Buffer A and be
# submitted immediately; while its 500 ms lower write is active, later pages
# early-complete into Buffer B.
dd if="$TMP/pages.bin" of="/dev/mapper/$TARGET" bs=4096 count=9 oflag=direct conv=notrunc status=none &
WRITER=$!

wait_state 8

HITS0=$(status_value staged_hits)

# (1) Demand data from Buffer A while Buffer B is filling.
A_NS=$(read_page 0 "$TMP/read-a" "$TMP/expected-a")
HITS1=$(status_value staged_hits)
(( HITS1 > HITS0 )) || { echo "Buffer A read did not hit staged RAM" >&2; exit 1; }

# (2) Demand data from Buffer B while Buffer A is saving.
B_NS=$(read_page 4 "$TMP/read-b" "$TMP/expected-b")
HITS2=$(status_value staged_hits)
(( HITS2 > HITS1 )) || { echo "Buffer B read did not hit staged RAM" >&2; exit 1; }

# (3) Demand data from both buffers while one lower write remains active.
start_both=$(date +%s%N)
read_page 0 "$TMP/read-a2" "$TMP/expected-a2" >"$TMP/a2.ns" &
PIDA=$!
read_page 5 "$TMP/read-b2" "$TMP/expected-b2" >"$TMP/b2.ns" &
PIDB=$!
wait "$PIDA"
PIDA=""
wait "$PIDB"
PIDB=""
end_both=$(date +%s%N)
BOTH_NS=$((end_both - start_both))
HITS3=$(status_value staged_hits)
(( HITS3 >= HITS2 + 2 )) || {
  echo "dual-buffer reads were not both satisfied from staged RAM" >&2
  exit 1
}

# A disk read on this fixture costs at least about 500 ms. Allow generous
# scheduler noise but require staged recall to remain clearly below that.
LIMIT_NS=300000000
(( A_NS < LIMIT_NS )) || { echo "Buffer A recall waited too long: $A_NS ns" >&2; exit 1; }
(( B_NS < LIMIT_NS )) || { echo "Buffer B recall waited too long: $B_NS ns" >&2; exit 1; }
(( BOTH_NS < LIMIT_NS )) || { echo "dual recall waited too long: $BOTH_NS ns" >&2; exit 1; }

# A READ must not invalidate swap data. DISCARD is the proof that makes the
# old generation unnecessary. Invalidate a page expected to still be buffered;
# generation checks/repacking must suppress stale publication and, when unsent,
# can remove the record before lower I/O.
blkdiscard -o $((6 * 4096)) -l 4096 "/dev/mapper/$TARGET"

wait "$WRITER"
WRITER=""

python3 - "/dev/mapper/$TARGET" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY

STATUS=$(dmsetup status "$TARGET")
echo "status: $STATUS"
CANCEL=$(status_value staged_cancel)
FAILED=$(status_value failed)
(( CANCEL > 0 )) || { echo "no staged cancellation/repack was observed" >&2; exit 1; }
[[ "$FAILED" == 0 ]] || { echo "target ended failed" >&2; exit 1; }

python3 - "$A_NS" "$B_NS" "$BOTH_NS" <<'PY'
import sys
a, b, both = (int(x) / 1e6 for x in sys.argv[1:])
print(f"RECALL A_inflight_ms={a:.3f} B_fill_ms={b:.3f} both_ms={both:.3f}")
PY

