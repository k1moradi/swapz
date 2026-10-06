#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "root required" >&2; exit 1; }
for tool in losetup truncate fio dmsetup modprobe python3; do command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }; done

TMP=$(mktemp -d)
LOOP=""
NAME=swapz-smoke
cleanup() {
  dmsetup remove "$NAME" >/dev/null 2>&1 || true
  [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

truncate -s 1G "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
modprobe dm-swapz
# 256 MiB logical on 1 GiB backing gives fourfold overprovisioning.
SECTORS=$((256 * 1024 * 1024 / 512))
dmsetup create "$NAME" --table "0 $SECTORS swapz $LOOP"

# Regression test: Linux 7.0 sends fsync/flush as a zero-length
# REQ_OP_WRITE | REQ_PREFLUSH bio through Device Mapper.
python3 - "/dev/mapper/$NAME" <<'PY'
import os
import sys

fd = os.open(sys.argv[1], os.O_RDWR)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY

fio --name=verify --filename="/dev/mapper/$NAME" --size=192M --bs=4k --rw=randwrite \
    --direct=1 --ioengine=libaio --iodepth=8 --numjobs=1 --refill_buffers=1 \
    --buffer_compress_percentage=75 --verify=crc32c --do_verify=1 --group_reporting=1

# Also verify a flush after data has passed through the packer.
python3 - "/dev/mapper/$NAME" <<'PY'
import os
import sys

fd = os.open(sys.argv[1], os.O_RDWR)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY

echo "status: $(dmsetup status "$NAME")"
echo "loop smoke test: PASS"
