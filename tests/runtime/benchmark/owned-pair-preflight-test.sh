#!/usr/bin/env bash
# No privilege: verify missing/unknown opt-in cannot provision anything.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
SCRIPT="$ROOT/tools/benchmark-owned-pair.sh"
bash -n "$SCRIPT"
[[ $(bash "$SCRIPT" --help) == *'--run-owned-ram-pair'* ]]
[[ $(bash "$SCRIPT" --help) == *'--profile medium'* ]]
[[ $(bash "$SCRIPT" --help) == *'--retain-ms 2'* ]]
[[ $(bash "$SCRIPT" --help) == *'--unpaced'* ]]
[[ $(bash "$SCRIPT" --help) == *'--retain-ms 2 --unpaced'* ]]
[[ $(bash "$SCRIPT" --help) == *'--async-prepare'* ]]
[[ $(bash "$SCRIPT" --help) == *'--lower-mbps 10|20|80'* ]]
[[ $(bash "$SCRIPT" --help) == *'--completion-nsec 150000|1000000'* ]]
if bash "$SCRIPT" >/dev/null 2>&1 ||
   bash "$SCRIPT" --unknown >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile unknown >/dev/null 2>&1 ||
   bash "$SCRIPT" --profile medium >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --retain-ms 2 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --unpaced >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --unpaced >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 0 --unpaced >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 1 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile default --retain-ms 1 --unpaced >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 3 --unpaced >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 1 --unpaced --extra >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --unknown >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --lower-mbps 20 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --lower-mbps 19 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --lower-mbps 20 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --lower-mbps 10 --completion-nsec 150000 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --lower-mbps 80 --completion-nsec 1000000 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --unpaced --completion-nsec 1000000 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --async-prepare >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 2 --async-prepare >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms 4 >/dev/null 2>&1 ||
   bash "$SCRIPT" --run-owned-ram-pair --profile medium --retain-ms unknown >/dev/null 2>&1; then
    echo 'FAIL: unsafe default benchmark execution' >&2
    exit 1
fi
for contract in '0:0|20:0|10:1000000|80:150000' '"$config/mbps"' '"$config/irqmode"' '"$config/completion_nsec"' 'PASS_RAM_MODEL_LOWER_MBPS=' 'RATE_MODE=unpaced' 'MEASURE_OPS=16384' 'IOPS=0' '--unpaced' 'RETAIN_MS="$5"' '$5 == 1 || $5 == 2' 'SWAPS=' 'nullb-swapz-' 'memory_backed' 'dmsetup remove' \
                'READY_COUNT=0' 'COUNT != READY_COUNT' \
                'QUARANTINE=0' '--expected-dm-uuid' 'timeout --signal=TERM'; do
    grep -Fq -- "$contract" "$SCRIPT" ||
        { echo "FAIL: missing owned-pair safety contract $contract" >&2; exit 1; }
done
echo 'PASS: owned-pair rootless opt-in and syntax'
