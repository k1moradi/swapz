#!/usr/bin/env bash
# Private rootless half of make test, also used in unprivileged CI.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
export PYTHONPYCACHEPREFIX="$ROOT/build/python-cache"
mkdir -p build/python-cache
make_args=(make)
if [[ -n ${SWAPZ_TEST_JOBS:-} ]]; then
  [[ $SWAPZ_TEST_JOBS =~ ^[1-9][0-9]*$ ]] && (( SWAPZ_TEST_JOBS <= 16 )) ||
    { printf '%s\n' 'BLOCKED: invalid automatic build job count' >&2; exit 2; }
  make_args+=("-j$SWAPZ_TEST_JOBS")
fi
"${make_args[@]}" -C tests test
python3 -B tests/runtime/native/source-contract-test.py -v
python3 -B tests/runtime/benchmark/io-replay-test.py -v
python3 -B tests/runtime/native/make-interface-test.py -v
python3 -B tests/runtime/native/test-report-test.py -v
python3 -B tests/runtime/native/package-dkms-test.py -v
python3 -B tests/runtime/benchmark/resource-pressure.py --help >/dev/null
[[ -x tests/tools/loaded-preflight.sh ]] || {
  printf '%s\n' 'FAIL: loaded-preflight.sh must remain executable' >&2
  exit 1
}
bash -n tests/tools/test-rootless.sh tests/tools/test-loaded.sh \
  tests/tools/qualify-resource-pressure.sh \
  tests/tools/qualify-logical-open-balance.sh packaging/package-dkms.sh \
  packaging/sign-module.sh \
  tests/tools/deploy-nullblk.sh tests/tools/loaded-preflight.sh tests/tools/swap-inventory.sh \
  tests/tools/quiet-lower-io.sh \
  tests/tools/benchmark-owned-pair.sh tests/tools/nullblk-identity.sh \
  tests/runtime/native/nullblk-identity-test.sh \
  tests/runtime/native/quiet-lower-io-test.sh \
  tests/runtime/native/swap-inventory-test.sh
bash tests/runtime/native/nullblk-identity-test.sh
bash tests/runtime/native/quiet-lower-io-test.sh
bash tests/runtime/native/swap-inventory-test.sh
if [[ "$(uname -m)" == "x86_64" ]]; then
  objdump -d build/tests/native/predictor-sse2.o > build/tests/native/predictor-sse2.disasm
  objdump -d build/tests/native/predictor-avx2.o > build/tests/native/predictor-avx2.disasm
  objdump -d build/tests/native/predictor-avx512.o > build/tests/native/predictor-avx512.disasm
  grep -Eq 'psubq|paddq' build/tests/native/predictor-sse2.disasm
  grep -Eq 'vpsubq|vpaddq' build/tests/native/predictor-avx2.disasm
  grep -Eq 'vpsubq|vpaddq' build/tests/native/predictor-avx512.disasm
  grep -Eq 'valignq' build/tests/native/predictor-avx512.disasm
  rm -f build/tests/native/predictor-sse2.disasm build/tests/native/predictor-avx2.disasm \
    build/tests/native/predictor-avx512.disasm
fi
grep -Fq 'dmsetup create "$DMNAME" --uuid "$UUID"' tests/tools/deploy-nullblk.sh
grep -Fq 'memory_backed' tests/tools/deploy-nullblk.sh
grep -Fq 'modprobe lz4_compress || fail "kernel LZ4 compressor unavailable"' tests/tools/deploy-nullblk.sh
grep -Fq 'SWAPS_ID_BEFORE' tests/tools/deploy-nullblk.sh
grep -Fq 'SWAPS_ID' tests/tools/benchmark-owned-pair.sh
grep -Fq 'cat /sys/module/dm_swapz/refcnt' tests/tools/loaded-preflight.sh
grep -Fq '(( refcount == 0 ))' tests/tools/loaded-preflight.sh
grep -Fq 'rmmod dm_swapz' tests/tools/loaded-preflight.sh
grep -Fq 'AUTO_REMOVED_IDLE_DM_SWAPZ=1' tests/tools/loaded-preflight.sh
! grep -Fq 'rmmod -f' tests/tools/loaded-preflight.sh
grep -Fq 'QUARANTINED: host swap identity changed' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_ZERO_WRITE_LOWER_IO=' tests/tools/deploy-nullblk.sh
grep -Fq 'zero_writes == 9' tests/tools/deploy-nullblk.sh
grep -Fq 'lower_write_bytes == target_write_bytes' tests/tools/deploy-nullblk.sh
grep -Fq 'lower_read_bytes != target_read_bytes' tests/tools/deploy-nullblk.sh
grep -Fq 'swapz_capture_quiescent_io' tests/tools/deploy-nullblk.sh
grep -Fq 'UNATTRIBUTED_LOWER_READ=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_ORACLE_LOWER_READ=' tests/tools/deploy-nullblk.sh
grep -Fq 'close_total == window_delta' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_CLOSE_REASONS=' tests/tools/deploy-nullblk.sh
grep -Fq 'age_total == window_delta' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_OPEN_AGE=' tests/tools/deploy-nullblk.sh
grep -Fq 'raw_writes == 64' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_LOADED_ORACLE_PROFILE=' tests/tools/deploy-nullblk.sh
grep -Fq 'timer_arms > lifecycle_windows' tests/tools/deploy-nullblk.sh
grep -Fq 'dmsetup suspend "$DMNAME"' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_LOADED_SUSPEND_DRAIN=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_RETAINED_SYNTHETIC_WRITE_FAULT=' tests/tools/deploy-nullblk.sh
grep -Fq 'PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=' tests/tools/deploy-nullblk.sh
grep -Fq -- '--write-series' tests/tools/device-roundtrip.c
grep -Fq -- '--verify-series' tests/tools/device-roundtrip.c
printf '%s\n' 'PASS: rootless C tests, source contracts, Make policy and owned-device preflights'
