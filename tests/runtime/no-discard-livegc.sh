#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source "$ROOT/tests/runtime/test-stack-teardown.sh"
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in dmsetup g++ losetup lsblk modprobe truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
TMP=$(mktemp -d /dev/shm/swapz-v21-no-discard.XXXXXX)
TAG="$$-$RANDOM"
LOOP=""; CRYPT="swapz-v21-crypt-$TAG"; NAME="swapz-v21-no-discard-$TAG"
cleanup() {
  local exit_status=$?
  trap - EXIT
  set +e
  # Remove swapz -> crypt -> loop. Never detach the lower loop if any DM
  # target remains, and preserve the image for investigation on failure.
  if ! swapz_test_cleanup_dm_stack "$LOOP" "$NAME" "$CRYPT"; then
    echo "ERROR: no-DISCARD teardown incomplete; preserved test resources and $TMP" >&2
    (( exit_status != 0 )) || exit_status=1
  elif (( exit_status == 0 )); then
    if rm -rf -- "$TMP"; then
      echo 'V2.2 no-DISCARD live-GC readback and teardown: PASS'
    else
      echo "ERROR: could not remove test directory $TMP" >&2
      exit_status=1
    fi
  else
    echo "ERROR: no-DISCARD fixture failed; diagnostics preserved at $TMP" >&2
  fi
  exit "$exit_status"
}
trap cleanup EXIT
g++ -std=c++23 -O2 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror "$ROOT/tests/runtime/reference.cpp" -o "$TMP/reference"
truncate -s 3M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
dmsetup create "$CRYPT" --table "0 6144 crypt aes-xts-plain64 $KEY 0 $LOOP 0"
udevadm settle
CRYPT_KNAME=$(lsblk -nro KNAME "/dev/mapper/$CRYPT" | head -1)
CRYPT_DISCARD=$(cat "/sys/class/block/$CRYPT_KNAME/queue/discard_max_bytes")
echo "crypt lower queue discard_max_bytes=$CRYPT_DISCARD"
[[ "$CRYPT_DISCARD" == 0 ]]
dmsetup create "$NAME" --table "0 2048 swapz /dev/mapper/$CRYPT"
STATUS0=$(dmsetup status "$NAME")
echo "initial: $STATUS0"
grep -q 'lower_discard=off' <<<"$STATUS0"
"$TMP/reference" live "/dev/mapper/$NAME" 30000
STATUS=$(dmsetup status "$NAME")
echo "final: $STATUS"
grep -q 'failed=0' <<<"$STATUS"
grep -Eq 'gc_pages=[1-9][0-9]*' <<<"$STATUS"
