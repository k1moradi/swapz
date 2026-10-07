#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in cmp dd dmsetup losetup python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
TMP=$(mktemp -d /dev/shm/swapz-v21-lifecycle.XXXXXX)
TAG="$$-$RANDOM"
LOOP=""; NAME="swapz-v21-lifecycle-$TAG"
cleanup(){ dmsetup remove "$NAME" >/dev/null 2>&1 || true; [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
truncate -s 16M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
python3 - "$TMP/page.bin" <<'PY'
import os,sys
fd=os.open(sys.argv[1],os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600); os.write(fd,os.urandom(4096)); os.close(fd)
PY
for i in $(seq 1 100); do
  dmsetup create "$NAME" --table "0 8 swapz $LOOP"
  dd if="$TMP/page.bin" of="/dev/mapper/$NAME" bs=4096 count=1 oflag=direct conv=fsync status=none
  dd if="/dev/mapper/$NAME" of="$TMP/readback.bin" bs=4096 count=1 iflag=direct status=none
  cmp "$TMP/page.bin" "$TMP/readback.bin"
  dmsetup status "$NAME" | grep -q 'failed=0'
  dmsetup remove "$NAME"
done
echo '100 create/use/destroy cycles: PASS'
