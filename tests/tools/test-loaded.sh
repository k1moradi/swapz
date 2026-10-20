#!/usr/bin/env bash
# Private loaded qualification phase of make test, after rootless gates.
# No installation, swap activation, physical media, or interactive sudo.
# Each owned-device child enforces exact source, module and host-ownership
# checks and quarantines unexpectedly busy resources instead of forcing removal.
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
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

tested_source="${SWAPZ_TESTED_SOURCE_SHA:-$(git rev-parse HEAD)}"
[[ "$tested_source" =~ ^[0-9a-f]{40}$ ]] ||
    { printf '%s\n' 'BLOCKED: invalid tested source revision' >&2; exit 2; }
git merge-base --is-ancestor "$tested_source" HEAD >/dev/null 2>&1 &&
    git diff --quiet "$tested_source..HEAD" -- . ':(exclude)test_results.json.xz' ||
    { printf '%s\n' 'BLOCKED: tested source does not match checkout code' >&2; exit 2; }
printf 'LOADED_QUALIFICATION_SOURCE=%s\n' "$tested_source"
printf '%s\n' 'START_LOADED_OWNED_NULLBLK_SMOKE'
"${privileged[@]}" tests/tools/deploy-nullblk.sh
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
    for qd in 1 4 8 32; do
        rm -f -- "$shared_plan/plan-write-qd$qd/trace.jsonl" \
            "$shared_plan/plan-write-qd$qd/manifest.json"
        rmdir -- "$shared_plan/plan-write-qd$qd" 2>/dev/null || true
    done
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
# Four immutable unpaced write-only plans reuse the identical fixture and
# logical volume. Persistent lane-owned workers sustain offered QD without
# per-I/O Future dispatch or an artificial barrier between completed writes.
for qd in 1 4 8 32; do
    python3 -B tests/runtime/benchmark/io-replay.py prepare \
        --fixture "$shared_plan/fixture.bin" \
        --output-dir "$shared_plan/plan-write-qd$qd" \
        --logical-pages 1024 --writer-pages 256 --reader-start 512 \
        --reader-pages 256 --qd "$qd" --read-pct 0 \
        --warmup-ops 256 --measure-ops 4096 --iops 0 --sustained-write
done

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
# write/read evidence. Slow remains a bounded directional control. Fast runs
# five adjacent counterbalanced sync/async rounds so the report can compute a
# paired 95% confidence interval without changing the workload or policy.
confirmation_modes=(0 1 1 0 0 1 1 0 0 1)
directional_modes=(0 1)
for regime in sd_emulated ssd_emulated; do
    printf 'START_OWNED_RAM_REGIME=%s\n' "$regime"
    index=0
    if [[ $regime == ssd_emulated ]]; then
        modes=("${confirmation_modes[@]}")
    else
        modes=(0 1 1 0)
    fi
    for async_prepare in "${modes[@]}"; do
        arguments=(--run-owned-ram-pair --profile medium
                   --retain-ms 2 --unpaced)
        case "$regime" in
            sd_emulated) arguments+=(--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000) ;;
            ssd_emulated) arguments+=(--lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000) ;;
            *) echo 'BLOCKED: unsupported owned storage model' >&2; exit 2 ;;
        esac
        if (( async_prepare )); then
            arguments+=(--async-prepare)
        fi
        arguments+=(--shared-plan "$shared_plan")
        if (( index % 2 )); then
            arguments+=(--swapz-first)
        fi
        printf 'START_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        "${privileged[@]}" tests/tools/benchmark-owned-pair.sh "${arguments[@]}"
        printf 'PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        (( index += 1 ))
    done
    printf 'PASS_OWNED_RAM_REGIME=%s\n' "$regime"
done

# ID64 is owner-qualified. Retain one fast off/on directional control with
# async preparation enabled to catch a structural regression without repeating
# the retired five-pair performance experiment.
index=0
for guard in "${directional_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000
               --async-prepare
               --guard-inflight-zero-shrink "$guard"
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_BURST_GUARD_AB=%s\n' "$guard"
    "${privileged[@]}" tests/tools/benchmark-owned-pair.sh "${arguments[@]}"
    printf 'PASS_BURST_GUARD_AB=%s\n' "$guard"
    (( index += 1 ))
done

# ID63 adjacent distinct-extent confirmation: vary only exact zero-extra
# coalescing for five matched fast rounds. Standalone same-extent grouping is
# retired; the off arm therefore remains on the ordinary swapz_read() path.
index=0
for read_coalesce in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000
               --read-coalesce "$read_coalesce" --parallel-reads 1
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_READ_COALESCE_AB=%s\n' "$read_coalesce"
    "${privileged[@]}" tests/tools/benchmark-owned-pair.sh "${arguments[@]}"
    printf 'PASS_READ_COALESCE_AB=%s\n' "$read_coalesce"
    (( index += 1 ))
done

# ID63 depth-one adjacent coalescing confirmation: vary only exact zero-extra
# adjacent-range coalescing on the serial model; the off arm is ordinary FIFO.
index=0
for read_coalesce in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000
               --read-coalesce "$read_coalesce" --parallel-reads 1
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_SD_READ_COALESCE_AB=%s\n' "$read_coalesce"
    "${privileged[@]}" tests/tools/benchmark-owned-pair.sh "${arguments[@]}"
    printf 'PASS_SD_READ_COALESCE_AB=%s\n' "$read_coalesce"
    (( index += 1 ))
done

# Write-only sustained-QD controls stay one sync/async observation per point
# except fast QD8, which keeps five adjacent counterbalanced rounds. Historical
# wave-driver QD8 evidence is not reused as sustained-QD qualification.
for regime in sd_emulated ssd_emulated; do
    printf 'START_WRITE_SATURATION_REGIME=%s\n' "$regime"
    index=0
    for qd in 1 4 8 32; do
        if [[ $regime == ssd_emulated && $qd == 8 ]]; then
            modes=("${confirmation_modes[@]}")
        else
            modes=(0 1)
        fi
        for async_prepare in "${modes[@]}"; do
            arguments=(--run-owned-ram-pair --profile medium
                       --retain-ms 2 --unpaced)
            case "$regime" in
                sd_emulated) arguments+=(--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000) ;;
                ssd_emulated) arguments+=(--lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000) ;;
                *) echo 'BLOCKED: unsupported owned storage model' >&2; exit 2 ;;
            esac
            arguments+=(--write-only-qd "$qd")
            if (( async_prepare )); then
                arguments+=(--async-prepare)
            fi
            arguments+=(--shared-plan "$shared_plan")
            if (( index % 2 )); then
                arguments+=(--swapz-first)
            fi
            printf 'START_WRITE_SATURATION_PAIR_QD=%s ASYNC_PREPARE=%s\n' \
                "$qd" "$async_prepare"
            "${privileged[@]}" tests/tools/benchmark-owned-pair.sh "${arguments[@]}"
            printf 'PASS_WRITE_SATURATION_PAIR_QD=%s ASYNC_PREPARE=%s\n' \
                "$qd" "$async_prepare"
            (( index += 1 ))
        done
    done
    printf 'PASS_WRITE_SATURATION_REGIME=%s\n' "$regime"
done

printf '%s\n' \
    'PASS_LOADED_TEST_EXECUTION: smoke, 14 mixed sessions, 10 Kread sessions, and 24 write-only sessions completed.' \
    'PERFORMANCE_WIN=EVIDENCE_ONLY: fast mixed, Kread, and fast QD8 carry five matched rounds with paired 95% CIs; QD4 is directional.'
