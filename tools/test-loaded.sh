#!/usr/bin/env bash
# Private loaded qualification phase of make test, after rootless gates.
# No installation, swap activation, physical media, or interactive sudo.
# Each owned-device child enforces exact source, module and host-ownership
# checks and quarantines unexpectedly busy resources instead of forcing removal.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT"

if (( EUID == 0 )); then
    privileged=(bash)
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    # Never prompt, request a password, or add broad sudo permissions.
    privileged=(sudo -n bash)
else
    printf '%s\n' >&2 \
        'BLOCKED_LOADED_QUALIFICATION: running the real Device Mapper target requires root.' \
        'No privileged module/device work was attempted; no loaded benchmark passed.' \
        'Arrange explicit noninteractive administrator authorization before make test.'
    exit 2
fi

printf 'LOADED_QUALIFICATION_SOURCE=%s\n' "$(git rev-parse HEAD)"
printf '%s\n' 'START_LOADED_OWNED_NULLBLK_SMOKE'
"${privileged[@]}" tools/deploy-nullblk.sh
printf '%s\n' 'PASS_LOADED_OWNED_NULLBLK_SMOKE'

# Counterbalanced two-pair A/B/B/A pilot: every child constructs newly
# owned RAM-backed null_blk lowers and reports independent device counters.
# This is a loaded performance experiment, NOT an assertion of a throughput
# advantage or evidence of physical SD/SSD/HDD endurance.
for async_prepare in 0 1 1 0; do
    arguments=(--run-owned-ram-pair --profile medium
               --retain-ms 2 --unpaced --lower-mbps 20)
    if (( async_prepare )); then
        arguments+=(--async-prepare)
    fi
    printf 'START_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
    "${privileged[@]}" tools/benchmark-owned-pair.sh "${arguments[@]}"
    printf 'PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
done

printf '%s\n' \
    'PASS_LOADED_TEST_EXECUTION: smoke and four rate-capped off/V3 pairs completed.' \
    'PERFORMANCE_WIN=UNDETERMINED: review independent MB/s, p95/p99 and read/write request results.'
