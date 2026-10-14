#!/usr/bin/env bash
# No privilege: verify missing/unknown opt-in cannot provision anything.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
SCRIPT="$ROOT/tools/benchmark-owned-pair.sh"
bash -n "$SCRIPT"
[[ $(bash "$SCRIPT" --help) == *'--run-owned-ram-pair'* ]]
[[ $(bash "$SCRIPT" --help) == *'--profile medium'* ]]
if bash "$SCRIPT" >/dev/null 2>&1 ||
   bash "$SCRIPT" --unknown >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile unknown >/dev/null 2>&1 ||
   bash "$SCRIPT" --profile medium >/dev/null 2>&1; then
    echo 'FAIL: unsafe default benchmark execution' >&2
    exit 1
fi
for contract in 'SWAPS=' 'nullb-swapz-' 'memory_backed' 'dmsetup remove' \
                'READY_COUNT=0' 'COUNT != READY_COUNT' \
                'QUARANTINE=0' '--expected-dm-uuid' 'timeout --signal=TERM'; do
    grep -Fq -- "$contract" "$SCRIPT" ||
        { echo "FAIL: missing owned-pair safety contract $contract" >&2; exit 1; }
done
echo 'PASS: owned-pair rootless opt-in and syntax'
