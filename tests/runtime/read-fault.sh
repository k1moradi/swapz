#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in cmp dd dmsetup losetup python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
TMP=$(mktemp -d /dev/shm/swapz-v21-read-fault.XXXXXX)
TAG="$$-$RANDOM"
LOOP=""; LOWER="swapz-v21-read-fault-lower-$TAG"; TARGET="swapz-v21-read-fault-$TAG"
cleanup(){ dmsetup remove "$TARGET" >/dev/null 2>&1 || true; dmsetup remove "$LOWER" >/dev/null 2>&1 || true; [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
truncate -s 16M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
dmsetup create "$LOWER" --table "0 32768 linear $LOOP 0"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER"
python3 - "$TMP/known.bin" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600); os.write(fd,os.urandom(4096)); os.close(fd)
PY
dd if="$TMP/known.bin" of="/dev/mapper/$TARGET" bs=4096 count=1 oflag=direct conv=fsync status=none
cmp "$TMP/known.bin" <(dd if="$TMP/backing.img" bs=4096 count=1 status=none)
dmsetup suspend "$LOWER"
printf -v NEW_TABLE "0 8 error\n8 32760 linear %s 0" "$LOOP"
dmsetup reload "$LOWER" --table "$NEW_TABLE"
dmsetup resume "$LOWER"
set +e
dd if="/dev/mapper/$TARGET" of="$TMP/readback.bin" bs=4096 count=1 iflag=direct status=none
READ_EXIT=$?
set -e
STATUS=$(dmsetup status "$TARGET")
echo "read_exit=$READ_EXIT status=$STATUS"
cmp "$TMP/known.bin" <(dd if="$TMP/backing.img" bs=4096 count=1 status=none)
[[ "$READ_EXIT" -ne 0 ]]
grep -q 'failed=1' <<<"$STATUS"
echo 'lower read fault propagation and backing integrity: PASS'
