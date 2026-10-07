#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'root required' >&2; exit 1; }
for tool in cmp dd dmsetup fio losetup python3 truncate; do
  command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
TMP=$(mktemp -d /dev/shm/swapz-v21-write-fault.XXXXXX)
TAG="$$-$RANDOM"
LOOP=""; LOWER="swapz-v21-write-fault-lower-$TAG"; TARGET="swapz-v21-write-fault-$TAG"
cleanup(){ dmsetup remove "$TARGET" >/dev/null 2>&1 || true; dmsetup remove "$LOWER" >/dev/null 2>&1 || true; [[ -z "$LOOP" ]] || losetup -d "$LOOP" >/dev/null 2>&1 || true; rm -rf "$TMP"; }
trap cleanup EXIT
truncate -s 16M "$TMP/backing.img"
LOOP=$(losetup --find --show "$TMP/backing.img")
printf '0 8 linear %s 0\n8 32760 error\n' "$LOOP" > "$TMP/lower.table"
dmsetup create "$LOWER" "$TMP/lower.table"
dmsetup create "$TARGET" --table "0 4096 swapz /dev/mapper/$LOWER"
python3 - "$TMP/known.bin" <<'PYDATA'
import os, sys
fd = os.open(sys.argv[1], os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
os.write(fd, os.urandom(4096))
os.close(fd)
PYDATA
dd if="$TMP/known.bin" of="/dev/mapper/$TARGET" bs=4096 count=1 oflag=direct conv=fsync status=none
cmp "$TMP/known.bin" <(dd if="$TMP/backing.img" bs=4096 count=1 status=none)
BEFORE=$(dmsetup status "$TARGET")
echo "before fault: $BEFORE"
if fio --name=failed-batch --filename="/dev/mapper/$TARGET" --offset=4096 --size=32768 --io_size=32768 \
  --bs=4096 --rw=write --ioengine=libaio --iodepth=8 --iodepth_batch_submit=8 \
  --iodepth_batch_complete_min=8 --iodepth_low=8 --direct=1 --numjobs=1 \
  --refill_buffers=1 --buffer_compress_percentage=0 --output-format=json --output="$TMP/fio.json" \
  >"$TMP/fio.stdout" 2>"$TMP/fio.stderr"; then
  FIO_EXIT=0
else
  FIO_EXIT=$?
fi
cat "$TMP/fio.stderr"
ERROR_LINES=$(grep -c 'Input/output error: write offset=' "$TMP/fio.stderr" || true)
python3 - "$TMP/fio.json" "$FIO_EXIT" "$ERROR_LINES" <<'PYJSON'
import json, sys
with open(sys.argv[1], encoding="utf-8") as src:
    result = json.load(src)
write = result["jobs"][0]["write"]
errors = int(sys.argv[3])
print(f"fio_exit={sys.argv[2]} write_ios={write.get('total_ios')} error_lines={errors} bytes={write.get('io_bytes')}")
if int(sys.argv[2]) == 0 or write.get("total_ios") != 8 or write.get("io_bytes") != 0 or errors != 8:
    raise SystemExit("expected all eight batched 4 KiB writes to fail")
PYJSON
STATUS=$(dmsetup status "$TARGET")
echo "after fault: $STATUS"
cmp "$TMP/known.bin" <(dd if="$TMP/backing.img" bs=4096 count=1 status=none)
dd if="$TMP/backing.img" of="$TMP/unwritten.bin" bs=4096 skip=1 count=8 status=none
cmp <(head -c 32768 /dev/zero) "$TMP/unwritten.bin"
grep -q 'failed=1' <<<"$STATUS"
echo 'write failure: all eight upper writes failed; prior backing block is intact'
