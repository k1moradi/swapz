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

# One deterministic, measured-LZ4 immutable fixture/trace for all four
# comparisons. Safe user-space preparation happens before any new device.
# Children copy this verified plan into their own owned-device session.
umask 077
# The benchmark session directory is root-owned (umask 077) from older
# privileged runs. Never allocate a user-owned fixture there: mktemp
# would fail with EACCES after the loaded smoke already passed.
# The rootless/native build owns build/tests; keep the immutable fixture
# there, and let each privileged child COPY it to its own private session.
mkdir -p "$ROOT/build/tests"
shared_plan="$(mktemp -d "$ROOT/build/tests/benchmark-plan.XXXXXXXX")"
cleanup_shared_plan() {
    # Remove only exactly named files from this freshly allocated directory.
    [[ $shared_plan == "$ROOT/build/tests/benchmark-plan."* &&
       -d $shared_plan && ! -L $shared_plan ]] || return
    rm -f -- "$shared_plan/fixture.bin" "$shared_plan/fixture.json" \
        "$shared_plan/plan/trace.jsonl" "$shared_plan/plan/manifest.json"
    rmdir -- "$shared_plan/plan" "$shared_plan" 2>/dev/null || true
}
trap cleanup_shared_plan EXIT
python3 -B tests/runtime/benchmark/anon-page-fixture.py \
    --output-prefix "$shared_plan/fixture" --pages 128 \
    --seed 0x51a0a9 --weights medium=100
python3 -B tests/runtime/benchmark/io-replay.py prepare \
    --fixture "$shared_plan/fixture.bin" --output-dir "$shared_plan/plan" \
    --logical-pages 1024 --writer-pages 256 --reader-start 512 \
    --reader-pages 256 --qd 32 --read-pct 25 \
    --warmup-ops 1024 --measure-ops 16384 --iops 0
# Assert the representative fixture remains in the measured ~2KiB class.
python3 -B - "$shared_plan/fixture.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as inp:
    fixture = json.load(inp)
assert fixture["pages"] == 128
assert fixture["profile_pages"] == {"medium": 128}
assert fixture["lz4_size_buckets"] == {"2049_3072": 128}
assert fixture["raw_pages"] == 0
assert 2049 <= fixture["lz4_min_accepted_payload_bytes"] <= fixture["lz4_max_accepted_payload_bytes"] <= 2200
PY

# Two representative delay-modeled RAM-backed environments provide paired
# write/read evidence. Drop the uncapped and bandwidth-only repeats from
# every mandatory run: old evidence remains in Git history, while neither
# resembles actual SD/SSD latency. Keep four counterbalanced pairs per
# environment (two sync and two async) and all owned-device safety gates.
for regime in sd_emulated ssd_emulated; do
    printf 'START_OWNED_RAM_REGIME=%s\n' "$regime"
    index=0
    for async_prepare in 0 1 1 0; do
        arguments=(--run-owned-ram-pair --profile medium
                   --retain-ms 2 --unpaced)
        case "$regime" in
            sd_emulated) arguments+=(--lower-mbps 10 --completion-nsec 1000000) ;;
            ssd_emulated) arguments+=(--lower-mbps 80 --completion-nsec 150000) ;;
            *) echo 'BLOCKED: unsupported owned storage model' >&2; exit 2 ;;
        esac
        if (( async_prepare )); then
            arguments+=(--async-prepare)
        fi
        arguments+=(--shared-plan "$shared_plan")
        if (( index % 2 )); then
            arguments+=(--v3-first)
        fi
        printf 'START_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        "${privileged[@]}" tools/benchmark-owned-pair.sh "${arguments[@]}"
        printf 'PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        (( index += 1 ))
    done
    printf 'PASS_OWNED_RAM_REGIME=%s\n' "$regime"
done

printf '%s\n' \
    'PASS_LOADED_TEST_EXECUTION: smoke and eight modelled RAM-only benchmark pairs completed.' \
    'PERFORMANCE_WIN=UNDETERMINED: review independent MB/s, p95/p99 and read/write request results.'
