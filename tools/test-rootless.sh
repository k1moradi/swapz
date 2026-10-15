#!/usr/bin/env bash
# Private rootless half of make test, also used in unprivileged CI.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"
export PYTHONPYCACHEPREFIX="$ROOT/build/python-cache"
mkdir -p build/python-cache
make -C tests test
python3 -B tests/runtime/native/source-contract-test.py -v
python3 -B tests/runtime/benchmark/io-replay-test.py -v
python3 -B tests/runtime/native/make-interface-test.py -v
python3 -B tests/runtime/native/test-report-test.py -v
python3 -B tests/runtime/native/package-dkms-test.py -v
bash -n tools/test-rootless.sh tools/test-loaded.sh tools/package-dkms.sh \
  tools/deploy-nullblk.sh tools/swap-inventory.sh tools/quiet-lower-io.sh \
  tools/benchmark-owned-pair.sh tools/nullblk-identity.sh \
  tests/runtime/native/nullblk-identity-test.sh \
  tests/runtime/native/quiet-lower-io-test.sh \
  tests/runtime/native/swap-inventory-test.sh \
  tests/runtime/benchmark/owned-pair-preflight-test.sh
bash tests/runtime/native/nullblk-identity-test.sh
bash tests/runtime/native/quiet-lower-io-test.sh
bash tests/runtime/native/swap-inventory-test.sh
bash tests/runtime/benchmark/owned-pair-preflight-test.sh
grep -Fq 'dmsetup create "$DMNAME" --uuid "$UUID"' tools/deploy-nullblk.sh
grep -Fq 'memory_backed' tools/deploy-nullblk.sh
grep -Fq 'SWAPS_ID_BEFORE' tools/deploy-nullblk.sh
grep -Fq 'SWAPS_ID' tools/benchmark-owned-pair.sh
grep -Fq 'QUARANTINED: host swap identity changed' tools/deploy-nullblk.sh
grep -Fq 'PASS_ZERO_WRITE_LOWER_IO=' tools/deploy-nullblk.sh
grep -Fq 'zero_writes == 9' tools/deploy-nullblk.sh
grep -Fq 'lower_write_bytes == target_write_bytes' tools/deploy-nullblk.sh
grep -Fq 'lower_read_bytes != target_read_bytes' tools/deploy-nullblk.sh
grep -Fq 'swapz_capture_quiescent_io' tools/deploy-nullblk.sh
grep -Fq 'UNATTRIBUTED_LOWER_READ=' tools/deploy-nullblk.sh
grep -Fq 'PASS_ORACLE_LOWER_READ=' tools/deploy-nullblk.sh
grep -Fq 'close_total == window_delta' tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_CLOSE_REASONS=' tools/deploy-nullblk.sh
grep -Fq 'age_total == window_delta' tools/deploy-nullblk.sh
grep -Fq 'PASS_WINDOW_OPEN_AGE=' tools/deploy-nullblk.sh
printf '%s\n' 'PASS: rootless C tests, source contracts, Make policy and owned-device preflights'
