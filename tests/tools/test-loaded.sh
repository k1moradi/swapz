#!/usr/bin/env bash
# Private loaded qualification phase of make test, after rootless gates.
# No installation, swap activation, physical media, or interactive sudo.
# Each owned-device child enforces exact source, module and host-ownership
# checks and quarantines unexpectedly busy resources instead of forcing removal.
# A private root preflight may ordinarily unload only an already-idle dm_swapz.
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
[[ $(git branch --show-current) == main ]] ||
    { printf '%s\n' 'BLOCKED: loaded qualification requires main' >&2; exit 2; }
git diff --quiet -- . ':(exclude)test_results.json' &&
    git diff --cached --quiet -- . ':(exclude)test_results.json' ||
    { printf '%s\n' 'BLOCKED: dirty tracked source; commit or preserve changes first' >&2; exit 2; }
git merge-base --is-ancestor "$tested_source" HEAD >/dev/null 2>&1 &&
    git diff --quiet "$tested_source..HEAD" -- . ':(exclude)test_results.json' ||
    { printf '%s\n' 'BLOCKED: tested source does not match checkout code' >&2; exit 2; }
git_admin_dir="$(git rev-parse --absolute-git-dir)"
git_index_path="$(git rev-parse --git-path index)"
[[ "$git_index_path" == /* ]] || git_index_path="$ROOT/$git_index_path"
[[ -d "$git_admin_dir" && -f "$git_index_path" &&
   -w "$git_admin_dir" && -w "$git_index_path" ]] ||
    { printf '%s\n' 'BLOCKED: Git metadata is not writable by the invoking user' >&2; exit 2; }
git_admin_identity="$(stat -Lc '%u:%g:%a' "$git_admin_dir")"
git_index_identity="$(stat -Lc '%u:%g:%a' "$git_index_path")"
assert_git_metadata_unchanged() {
    [[ $(stat -Lc '%u:%g:%a' "$git_admin_dir") == "$git_admin_identity" &&
       $(stat -Lc '%u:%g:%a' "$git_index_path") == "$git_index_identity" &&
       -w "$git_admin_dir" && -w "$git_index_path" ]] || {
        printf '%s\n' >&2 'FAIL: privileged loaded qualification changed Git metadata ownership or mode'
        return 1
    }
}
run_privileged() {
    local rc
    if "${privileged[@]}" "$@"; then
        rc=0
    else
        rc=$?
    fi
    assert_git_metadata_unchanged || return 1
    return "$rc"
}

run_privileged tests/tools/loaded-preflight.sh
printf 'LOADED_QUALIFICATION_SOURCE=%s\n' "$tested_source"
printf '%s\n' 'START_LOADED_OWNED_NULLBLK_SMOKE'
run_privileged tests/tools/deploy-nullblk.sh --validated-source "$tested_source"
printf '%s\n' 'PASS_LOADED_OWNED_NULLBLK_SMOKE'

# One deterministic, measured-LZ4 immutable fixture/trace for the paired
# mixed/read/write benchmark families. Safe user-space preparation happens
# before any new device.
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
        "$shared_plan/plan/trace.jsonl" "$shared_plan/plan/manifest.json" \
        "$shared_plan/plan-id36/trace.jsonl" "$shared_plan/plan-id36/manifest.json"
    rmdir -- "$shared_plan/plan-id36" 2>/dev/null || true
    for qd in 1 4 8 32; do
        rm -f -- "$shared_plan/plan-write-qd$qd/trace.jsonl" \
            "$shared_plan/plan-write-qd$qd/manifest.json"
        rmdir -- "$shared_plan/plan-write-qd$qd" 2>/dev/null || true
    done
    rm -f -- "$shared_plan/delta64/fixture.bin"         "$shared_plan/delta64/fixture.json"         "$shared_plan/delta64/plan-write-qd32/trace.jsonl"         "$shared_plan/delta64/plan-write-qd32/manifest.json"
    rmdir -- "$shared_plan/delta64/plan-write-qd32"         "$shared_plan/delta64" 2>/dev/null || true
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
# ID36 is a forward-progress/correctness gate, not a throughput benchmark.
# Keep the same QD32 mixed geometry and immutable fixture, but shorten the
# measured trace so CPU/memory contention cannot turn a fixed replay timeout
# into the qualification result. Packed byte-exact reads remain enabled.
python3 -B tests/runtime/benchmark/io-replay.py prepare \
    --fixture "$shared_plan/fixture.bin" --output-dir "$shared_plan/plan-id36" \
    --logical-pages 1024 --writer-pages 256 --reader-start 512 \
    --reader-pages 256 --qd 32 --read-pct 25 \
    --warmup-ops 128 --measure-ops 2048 --iops 0
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

# Delta64 CPU-parallelism positive control. The fixture is deliberately
# synthetic: every page is a 64-bit counter/timestamp-like sequence whose
# adjacent deltas are small and nonzero. This makes classifier passes and
# adoptions mandatory evidence instead of benchmarking worker overhead on the
# historical medium fixture, which produced zero production rescue attempts.
mkdir -p "$shared_plan/delta64"
python3 -B tests/runtime/benchmark/anon-page-fixture.py     --output-prefix "$shared_plan/delta64/fixture" --pages 128     --seed 0x51a0a9 --weights delta64=100
python3 -B tests/runtime/benchmark/io-replay.py prepare     --fixture "$shared_plan/delta64/fixture.bin"     --output-dir "$shared_plan/delta64/plan-write-qd32"     --logical-pages 1024 --writer-pages 256 --reader-start 512     --reader-pages 256 --qd 32 --read-pct 0     --warmup-ops 256 --measure-ops 4096 --iops 0 --sustained-write
python3 -B - "$shared_plan/delta64/fixture.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as inp:
    fixture = json.load(inp)
assert fixture["pages"] == 128
assert fixture["profile_pages"] == {"delta64": 128}
assert fixture["lz4_size_buckets"] == {"2049_3072": 128}
assert fixture["raw_pages"] == 0
assert 2200 <= fixture["lz4_min_accepted_payload_bytes"]
assert fixture["lz4_max_accepted_payload_bytes"] <= 2450
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
        run_privileged tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
        printf 'PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        (( index += 1 ))
    done
    printf 'PASS_OWNED_RAM_REGIME=%s\n' "$regime"
done

# Directional storage-service envelope sweep. These remain synthetic null_blk
# models, not claims about a specific physical product. Each envelope runs the
# same immutable mixed workload with production async preparation, then the
# positive delta64 write-only fixture so reports can distinguish lower-byte
# opportunity from CPU/serialization capture. QD32 is the offered concurrency;
# the reporter therefore caps analytical 4KiB latency service at min(QD32, hwq).
for envelope in sd_card sata_ssd nvme_gen4 nvme_gen5; do
    case "$envelope" in
        sd_card)
            model_args=(--lower-mbps 100 --submit-queues 1
                        --hw-queue-depth 4 --completion-nsec 500000)
            ;;
        sata_ssd)
            model_args=(--lower-mbps 500 --submit-queues 1
                        --hw-queue-depth 32 --completion-nsec 100000)
            ;;
        nvme_gen4)
            model_args=(--lower-mbps 6500 --submit-queues 4
                        --hw-queue-depth 64 --completion-nsec 25000)
            ;;
        nvme_gen5)
            model_args=(--lower-mbps 12000 --submit-queues 4
                        --hw-queue-depth 64 --completion-nsec 14000)
            ;;
        *) echo 'BLOCKED: unsupported storage service envelope' >&2; exit 2 ;;
    esac
    for delta64_rescue in 0 1; do
        arguments=(--run-owned-ram-pair --profile medium
                   --retain-ms 2 --unpaced "${model_args[@]}")
        if (( delta64_rescue )); then
            # Suffix order mirrors benchmark-owned-pair.sh's bounded parser:
            # shared plan, delta acceleration, rescue, async, write-only,
            # completion, hwq, submit queues, then lower MiB/s.
            arguments+=(--write-only-qd 32 --async-prepare
                        --delta64-rescue --delta64-lz4-acceleration 4
                        --shared-plan "$shared_plan/delta64")
        else
            arguments+=(--async-prepare --shared-plan "$shared_plan")
        fi
        printf 'START_STORAGE_ENVELOPE=%s DELTA64_RESCUE=%s\n' \
            "$envelope" "$delta64_rescue"
        run_privileged tests/tools/benchmark-owned-pair.sh \
            --validated-source "$tested_source" "${arguments[@]}"
        printf 'PASS_STORAGE_ENVELOPE=%s DELTA64_RESCUE=%s\n' \
            "$envelope" "$delta64_rescue"
    done
done

# Delta64 rescue confirmation at fixed K=1 with second-LZ4 acceleration 4.
# Five counterbalanced off/on pairs reuse the exact positive delta64 fixture
# and SSD RAM model; the off arm also carries acceleration 4.
index=0
for delta64_rescue in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium
               --retain-ms 2 --unpaced
               --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000
               --write-only-qd 32 --async-prepare)
    # benchmark-owned-pair.sh peels private suffixes from the tail:
    # shared plan, workers, second-LZ4 acceleration, then rescue.
    if (( delta64_rescue )); then
        arguments+=(--delta64-rescue)
    fi
    arguments+=(--delta64-lz4-acceleration 4
               --shared-plan "$shared_plan/delta64")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_DELTA64_RESCUE=%s\n' "$delta64_rescue"
    run_privileged tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
    printf 'PASS_DELTA64_RESCUE=%s\n' "$delta64_rescue"
    (( index += 1 ))
done

# ID63 adjacent distinct-extent confirmation: vary only exact zero-extra
# coalescing for five matched fast rounds. Standalone same-extent grouping is
# retired; the off arm therefore remains on the ordinary swapz_read() path.
index=0
for read_coalesce in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000
               --read-coalesce "$read_coalesce"
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_READ_COALESCE_AB=%s\n' "$read_coalesce"
    run_privileged tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
    printf 'PASS_READ_COALESCE_AB=%s\n' "$read_coalesce"
    (( index += 1 ))
done

# ID63 depth-one adjacent coalescing confirmation: vary only exact zero-extra
# adjacent-range coalescing on the serial model; the off arm is ordinary FIFO.
index=0
for read_coalesce in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000
               --read-coalesce "$read_coalesce"
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_SD_READ_COALESCE_AB=%s\n' "$read_coalesce"
    run_privileged tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
    printf 'PASS_SD_READ_COALESCE_AB=%s\n' "$read_coalesce"
    (( index += 1 ))
done

# Independent lower-READ fan-out is fixed-on production infrastructure.
# The final 11fbc83 ARM64 five-pair decision established large useful-service
# and tail-latency gains; the off/on selector is retired from routine tests.

# Write-only sustained-QD controls stay one sync/async observation per point
# except fast QD8 and QD32, which keep five adjacent counterbalanced rounds.
# Historical wave-driver evidence is not reused as sustained-QD qualification.
for regime in sd_emulated ssd_emulated; do
    printf 'START_WRITE_SATURATION_REGIME=%s\n' "$regime"
    index=0
    for qd in 1 4 8 32; do
        if [[ $regime == ssd_emulated && ( $qd == 4 || $qd == 8 || $qd == 32 ) ]]; then
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
            run_privileged tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
            printf 'PASS_WRITE_SATURATION_PAIR_QD=%s ASYNC_PREPARE=%s\n' \
                "$qd" "$async_prepare"
            (( index += 1 ))
        done
    done
    printf 'PASS_WRITE_SATURATION_REGIME=%s\n' "$regime"
done

# ID36 release gate: constrain one production async pair to a cgroup-v2
# memory.high/memory.max domain while oversubscribing CPU. The helper itself
# owns only null_blk-backed resources and requires observable reclaim/throttle
# and CPU PSI without any OOM event.
run_privileged tests/tools/qualify-resource-pressure.sh \
    --validated-source "$tested_source" --shared-plan "$shared_plan"

# ID38 depth=2 remains a diagnostic module/benchmark control. Two idle-host
# five-pair cycles found no useful-throughput or latency benefit. Production
# remains depth=1 and routine qualification no longer spends ten sessions here.

printf '%s\n' \
    'PASS_LOADED_TEST_EXECUTION: smoke, 14 mixed sessions, 8 directional modern-storage envelope sessions, 10 paired delta64 rescue/second-LZ4 sessions, 20 ID63 toggle sessions, 40 sustained write-only sessions, and the ID36 resource-pressure gate completed.' \
    'PERFORMANCE_WIN=EVIDENCE_ONLY: fast mixed, ID63, predictor-first delta64, promoted independent READ fan-out, and fast QD4/QD8/QD32 carry bounded matched evidence; ordinary LZ4 acceleration, coalescing-cap selection, lower-WRITE depth 1/2, K1 read-bypass and delta64 preparation-width A/Bs are retired from routine qualification.'
