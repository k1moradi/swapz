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
    git diff --cached --quiet -- . ':(exclude)test_results.json' || {
    printf '%s\n' 'BLOCKED: dirty tracked source; commit or preserve changes first' >&2
    # Report only repository-relative paths; the generated report is not source.
    printf '%s\n' 'Unstaged tracked paths:' >&2
    git diff --name-only -- . ':(exclude)test_results.json' >&2
    printf '%s\n' 'Staged tracked paths:' >&2
    git diff --cached --name-only -- . ':(exclude)test_results.json' >&2
    exit 2
}
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

run_privileged_bounded() {
    local seconds="$1"
    local rc
    shift
    if "${privileged[@]}" -c '
        limit="$1"
        shift
        exec timeout --signal=TERM --kill-after=10s "${limit}s" bash "$@"
    ' swapz-loaded "$seconds" "$@"; then
        rc=0
    else
        rc=$?
    fi
    assert_git_metadata_unchanged || return 1
    if (( rc == 124 || rc == 137 )); then
        printf 'BLOCKED: privileged loaded helper exceeded %ss: %s\n' \
            "$seconds" "$*" >&2
    elif (( rc == 2 )) && [[ ${1:-} == tests/tools/loaded-preflight.sh ]]; then
        printf '%s\n' \
            'FAIL: loaded preflight exited with shell/runtime status 2 before a normal safety diagnostic' >&2
    fi
    return "$rc"
}

run_privileged_bounded 60 tests/tools/loaded-preflight.sh
printf 'LOADED_QUALIFICATION_SOURCE=%s\n' "$tested_source"

# Native ASan/UBSan/TSan cannot establish loaded-kernel instrumentation.
# Record the running kernel's debug features as observational release evidence;
# absence is not an ordinary make-test failure because production kernels often
# disable these expensive diagnostics.
kernel_debug_config_source=unavailable
kernel_debug_config_path=
kernel_debug_config_gzip=0
if [[ -r /proc/config.gz ]] && command -v gzip >/dev/null 2>&1; then
    kernel_debug_config_source=proc
    kernel_debug_config_path=/proc/config.gz
    kernel_debug_config_gzip=1
elif [[ -r "/boot/config-$(uname -r)" ]]; then
    kernel_debug_config_source=boot
    kernel_debug_config_path="/boot/config-$(uname -r)"
elif [[ -r "/lib/modules/$(uname -r)/build/.config" ]]; then
    kernel_debug_config_source=build
    kernel_debug_config_path="/lib/modules/$(uname -r)/build/.config"
fi

kernel_debug_value() {
    local symbol="$1"
    if [[ $kernel_debug_config_source == unavailable ]]; then
        printf '%s' unknown
        return 0
    fi
    if (( kernel_debug_config_gzip )); then
        if gzip -cd -- "$kernel_debug_config_path" 2>/dev/null |
                grep -Fx -- "$symbol=y" >/dev/null; then
            printf '%s' 1
            return 0
        fi
        if gzip -cd -- "$kernel_debug_config_path" 2>/dev/null |
                grep -Fx -- "# $symbol is not set" >/dev/null; then
            printf '%s' 0
            return 0
        fi
    else
        if grep -Fx -- "$symbol=y" "$kernel_debug_config_path" >/dev/null; then
            printf '%s' 1
            return 0
        fi
        if grep -Fx -- "# $symbol is not set" "$kernel_debug_config_path" >/dev/null; then
            printf '%s' 0
            return 0
        fi
    fi
    printf '%s' unknown
}
kernel_debug_kasan="$(kernel_debug_value CONFIG_KASAN)"
kernel_debug_kcsan="$(kernel_debug_value CONFIG_KCSAN)"
kernel_debug_lockdep="$(kernel_debug_value CONFIG_PROVE_LOCKING)"
printf 'KERNEL_DEBUG_FEATURES=kasan:%s kcsan:%s lockdep:%s config:%s\n' \
    "$kernel_debug_kasan" "$kernel_debug_kcsan" "$kernel_debug_lockdep" \
    "$kernel_debug_config_source"

kernel_debug_dir=""
kernel_debug_baseline_ready=0
cleanup_kernel_debug() {
    if [[ -n "$kernel_debug_dir" &&
          "$kernel_debug_dir" == "$ROOT/build/tests/kernel-debug."* &&
          -d "$kernel_debug_dir" && ! -L "$kernel_debug_dir" ]]; then
        rm -f -- "$kernel_debug_dir/baseline.log" \
            "$kernel_debug_dir/final.log" "$kernel_debug_dir/delta.log"
        rmdir -- "$kernel_debug_dir" 2>/dev/null || true
    fi
}
capture_kernel_debug_log() {
    local output="$1"
    local rc
    if "${privileged[@]}" -c 'exec "$@"' swapz-kernel-debug \
            dmesg --color=never --notime >"$output" 2>/dev/null; then
        rc=0
    else
        rc=$?
    fi
    assert_git_metadata_unchanged || return 1
    return "$rc"
}
if [[ $kernel_debug_kasan == 1 || $kernel_debug_kcsan == 1 ||
      $kernel_debug_lockdep == 1 ]]; then
    mkdir -p "$ROOT/build/tests"
    kernel_debug_dir="$(mktemp -d "$ROOT/build/tests/kernel-debug.XXXXXXXX")"
    trap cleanup_kernel_debug EXIT
    if capture_kernel_debug_log "$kernel_debug_dir/baseline.log"; then
        kernel_debug_baseline_ready=1
    fi
fi

printf '%s\n' 'START_LOADED_MAXIMUM_CAPACITY'
run_privileged_bounded 300 tests/tools/deploy-nullblk.sh \
	--validated-source "$tested_source" --max-boundary-probe
printf '%s\n' 'START_LOADED_GC_ROLL_FORWARD_RECOVERY'
run_privileged_bounded 240 tests/tools/deploy-nullblk.sh \
	--validated-source "$tested_source" --gc-recovery-fault-probe
printf '%s\n' 'START_LOADED_OWNED_NULLBLK_SMOKE'
run_privileged_bounded 600 tests/tools/deploy-nullblk.sh --validated-source "$tested_source"
printf '%s\n' 'PASS_LOADED_OWNED_NULLBLK_SMOKE'
printf '%s\n' 'START_LOADED_OWNED_RAM_RECOVERY'
run_privileged_bounded 150 tests/tools/qualify-owned-ram-recovery.sh \
	--validated-source "$tested_source"
printf '%s\n' 'START_LOADED_PRIMARY_NULLBLK_LIFECYCLE'
# The qualifier can issue up to 144 independently bounded 90-second primary
# lifecycle commands across normal start/stop, eighteen process-death phases,
# repeat-recovery checks and thirteen negative cases. Cleanup has one separate
# 60-second recovery ceiling. Keep the aggregate guard above the 12,960-second
# lifecycle-command ceiling plus setup/cleanup headroom; never weaken an inner
# timeout to make the outer wrapper pass.
run_privileged_bounded 14400 tests/tools/qualify-primary-lifecycle-nullblk.sh \
	--validated-source "$tested_source"

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
printf '%s\n' 'START_LOADED_SHARED_BENCHMARK_PLAN=allocation'
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
    for content in entropy balanced; do
        rm -f -- "$shared_plan/raw-read-$content/fixture.bin" \
            "$shared_plan/raw-read-$content/fixture.json" \
            "$shared_plan/raw-read-$content/plan/trace.jsonl" \
            "$shared_plan/raw-read-$content/plan/manifest.json" \
            "$shared_plan/raw-read-$content/run.log"
        rmdir -- "$shared_plan/raw-read-$content/plan" \
            "$shared_plan/raw-read-$content" 2>/dev/null || true
    done
    rmdir -- "$shared_plan/plan" "$shared_plan" 2>/dev/null || true
}
trap 'cleanup_shared_plan; cleanup_kernel_debug' EXIT
printf '%s\n' 'START_LOADED_SHARED_BENCHMARK_PLAN=fixture'
python3 -B tests/runtime/benchmark/anon-page-fixture.py \
    --output-prefix "$shared_plan/fixture" --pages 128 \
    --seed 0x51a0a9 --weights medium=100
printf '%s\n' 'START_LOADED_SHARED_BENCHMARK_PLAN=trace'
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
printf '%s\n' 'START_LOADED_SHARED_BENCHMARK_PLAN=write-plans'
for qd in 1 4 8 32; do
    python3 -B tests/runtime/benchmark/io-replay.py prepare \
        --fixture "$shared_plan/fixture.bin" \
        --output-dir "$shared_plan/plan-write-qd$qd" \
        --logical-pages 1024 --writer-pages 256 --reader-start 512 \
        --reader-pages 256 --qd "$qd" --read-pct 0 \
        --warmup-ops 256 --measure-ops 4096 --iops 0 --sustained-write
done

# Assert the representative fixture remains in the measured ~2KiB class.
printf '%s\n' 'START_LOADED_SHARED_BENCHMARK_PLAN=verify'
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
printf '%s\n' 'PASS_LOADED_SHARED_BENCHMARK_PLAN'

# Delta64 + DELTA64_SHUF8 + LZ4 remains fixed on for every emulated-device
# workload; the former positive-fixture off/on benchmark is retired.
# Exercise the RAW-aware slots on cold reads as a correctness gate, separate
# from the fixed medium performance matrix. The balanced case also decodes SWZ.
printf '%s\n' 'START_LOADED_RAW_READ_FANOUT'
for content in entropy balanced; do
    raw_plan="$shared_plan/raw-read-$content"
    mkdir -p "$raw_plan"
    weights=entropy=100
    [[ $content == balanced ]] && weights=medium=50,entropy=50
    python3 -B tests/runtime/benchmark/anon-page-fixture.py \
        --output-prefix "$raw_plan/fixture" --pages 128 \
        --seed 0x51a0a9 --weights "$weights" >/dev/null
    python3 -B tests/runtime/benchmark/io-replay.py prepare \
        --fixture "$raw_plan/fixture.bin" --output-dir "$raw_plan/plan" \
        --logical-pages 1024 --writer-pages 256 --reader-start 512 \
        --reader-pages 256 --qd 32 --read-pct 25 \
        --warmup-ops 128 --measure-ops 2048 --iops 0 >/dev/null
    if run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh \
        --validated-source "$tested_source" --run-owned-ram-pair \
        --profile medium --retain-ms 2 --unpaced --lower-mbps 80 \
        --hw-queue-depth 64 --completion-nsec 150000 --async-prepare \
        --shared-plan "$raw_plan" >"$raw_plan/run.log" 2>&1; then
        # Preserve the private full transcript. Forward only bounded,
        # source-defined timing records to the parent qualification reporter.
        # No device identity, fixture path or child diagnostic is relayed.
        if [[ -f $raw_plan/run.log && ! -L $raw_plan/run.log ]]; then
            LC_ALL=C grep -E \
                '^OWNED_PAIR_PHASE_TIMING phase=(setup|fixture|replay|verification|teardown) elapsed_ms=(0|[1-9][0-9]{0,7})$' \
                "$raw_plan/run.log" || :
        fi
    else
        rc=$?
        # The private pair transcript includes teardown lines after the
        # original failure. Find the first failure, not just the last lines.
        raw_failure_reason="no-source-diagnostic"
        raw_failure_kind=FAIL
        if [[ -f "$raw_plan/run.log" && ! -L "$raw_plan/run.log" ]]; then
            raw_failure_line="$(LC_ALL=C grep -m 1 -E \
                '^(BLOCKED: |FAIL: |(AssertionError|OSError|RuntimeError|ValueError|PermissionError):)' \
                "$raw_plan/run.log")" || raw_failure_line=""
            if [[ -n "$raw_failure_line" ]]; then
                raw_failure_reason="$raw_failure_line"
                if [[ "$raw_failure_line" == BLOCKED:* ]]; then
                    raw_failure_kind=BLOCKED
                fi
            fi
            tail -n 12 "$raw_plan/run.log"
        fi
        # This source-controlled, bounded failure marker is sanitized by the
        # parent reporter. Never mark a failed pair or this phase as PASS.
        printf '%s: raw-read fanout profile=%s child_exit=%d cause=%.110s\n' \
            "$raw_failure_kind" "$content" "$rc" "$raw_failure_reason" >&2
        exit "$rc"
    fi
done
python3 -B - "$shared_plan/raw-read-entropy/run.log" \
    "$shared_plan/raw-read-balanced/run.log" <<'PYRAW'
import json
import sys
from pathlib import Path
pages = batches = requests = 0
for path in sys.argv[1:]:
    arms = {}
    for line in Path(path).read_text().splitlines():
        if not line.startswith('{'):
            continue
        record = json.loads(line)
        if record.get('candidate') in ('off', 'swapz'):
            arms[record['candidate']] = record
    assert set(arms) == {'off', 'swapz'}
    for arm in arms.values():
        assert arm['verdict'] == 'PASS' and arm['verified_pages'] == 1024
        assert arm['expected_post_sha256'] == arm['verified_post_sha256']
    actual = arms['swapz']
    async_batches = actual['kernel_read_path']['parallel_read_async_batches']
    lower_requests = actual['lower_io']['lower_read_requests']
    assert async_batches > 0 and lower_requests > 0
    pages += actual['verified_pages']
    batches += async_batches
    requests += lower_requests
print(f'PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:{pages} '
      f'async_batches:{batches} lower_read_reqs:{requests}')
PYRAW

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
        run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
        printf 'PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=%s\n' "$async_prepare"
        (( index += 1 ))
    done
    printf 'PASS_OWNED_RAM_REGIME=%s\n' "$regime"
done

# Directional storage-service envelope sweep. These remain synthetic null_blk
# models, not claims about a specific physical product. Every envelope uses the
# same immutable medium mixed workload and the production-on delta64 +
# DELTA64_SHUF8 + LZ4 stack. QD32 is the offered concurrency; the reporter caps
# analytical 4KiB latency service at min(QD32, hwq).
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
    printf 'START_STORAGE_ENVELOPE=%s\n' "$envelope"
    run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh \
        --validated-source "$tested_source" --run-owned-ram-pair --profile medium \
        --retain-ms 2 --unpaced "${model_args[@]}" --async-prepare \
        --shared-plan "$shared_plan"
    printf 'PASS_STORAGE_ENVELOPE=%s\n' "$envelope"
done

# ID63 adjacent distinct-extent confirmation: vary only exact zero-extra
# coalescing for five matched fast rounds. Standalone same-extent grouping is
# retired; the off arm therefore remains on the ordinary swapz_read() path.
index=0
for read_coalesce in "${confirmation_modes[@]}"; do
    arguments=(--run-owned-ram-pair --profile medium --retain-ms 2 --unpaced
               --lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000
               --read-coalesce "$read_coalesce"
               --invalidate-cache-on-write-admit 1
               --shared-plan "$shared_plan")
    if (( index % 2 )); then
        arguments+=(--swapz-first)
    fi
    printf 'START_READ_COALESCE_AB=%s\n' "$read_coalesce"
    run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
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
    run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
    printf 'PASS_SD_READ_COALESCE_AB=%s\n' "$read_coalesce"
    (( index += 1 ))
done

# Independent lower-READ fan-out is fixed-on production infrastructure.
# The final 11fbc83 ARM64 five-pair decision established large useful-service
# and tail-latency gains; the off/on selector is retired from routine tests.

# Write-only sustained-QD controls stay one sync/async observation per point
# except fast QD4/QD8/QD32 and serial QD32, which keep five adjacent
# counterbalanced rounds. The serial QD32 gate decides whether the one-producer
# preparation path still earns its retained code/state on high-delay media.
# Historical wave-driver evidence is not reused as sustained-QD qualification.
for regime in sd_emulated ssd_emulated; do
    printf 'START_WRITE_SATURATION_REGIME=%s\n' "$regime"
    index=0
    for qd in 1 4 8 32; do
        if [[ ( $regime == ssd_emulated && ( $qd == 4 || $qd == 8 || $qd == 32 ) ) ||
              ( $regime == sd_emulated && $qd == 32 ) ]]; then
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
            run_privileged_bounded 720 tests/tools/benchmark-owned-pair.sh --validated-source "$tested_source" "${arguments[@]}"
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
run_privileged_bounded 960 tests/tools/qualify-resource-pressure.sh \
    --validated-source "$tested_source" --shared-plan "$shared_plan"

kernel_debug_checked=0
kernel_debug_baseline_stable=0
kernel_debug_reports=0
kernel_debug_swapz_reports=0
if [[ $kernel_debug_kasan == 1 || $kernel_debug_kcsan == 1 ||
      $kernel_debug_lockdep == 1 ]]; then
    if (( kernel_debug_baseline_ready )) &&
       capture_kernel_debug_log "$kernel_debug_dir/final.log"; then
        kernel_debug_checked=1
        kernel_debug_baseline_bytes="$(stat -Lc '%s' "$kernel_debug_dir/baseline.log")"
        kernel_debug_final_bytes="$(stat -Lc '%s' "$kernel_debug_dir/final.log")"
        if (( kernel_debug_final_bytes >= kernel_debug_baseline_bytes )) &&
           head -c "$kernel_debug_baseline_bytes" "$kernel_debug_dir/final.log" |
                cmp -s - "$kernel_debug_dir/baseline.log"; then
            kernel_debug_baseline_stable=1
            tail -c "+$((kernel_debug_baseline_bytes + 1))" \
                "$kernel_debug_dir/final.log" >"$kernel_debug_dir/delta.log"
            kernel_debug_pattern='BUG: KASAN:|KASAN:.*(use-after-free|out-of-bounds)|BUG: KCSAN:|KCSAN: data-race|possible circular locking dependency detected|possible recursive locking detected|inconsistent lock state|held lock freed|trying to register non-static key|sleeping function called from invalid context'
            kernel_debug_reports="$(grep -Eic "$kernel_debug_pattern" \
                "$kernel_debug_dir/delta.log" || true)"
            if (( kernel_debug_reports > 0 )); then
                kernel_debug_swapz_reports="$(grep -Ei -B8 -A120 \
                    "$kernel_debug_pattern" "$kernel_debug_dir/delta.log" |
                    grep -Eic '(^|[^[:alnum:]_])(dm[-_]swapz|swapz)([^[:alnum:]_]|$)' ||
                    true)"
            fi
        fi
    fi
fi
printf 'KERNEL_DEBUG_OBSERVATION=checked:%d baseline_stable:%d reports:%d swapz_reports:%d\n' \
    "$kernel_debug_checked" "$kernel_debug_baseline_stable" \
    "$kernel_debug_reports" "$kernel_debug_swapz_reports"
if (( kernel_debug_swapz_reports > 0 )); then
    printf '%s\n' 'FAIL: loaded kernel debug diagnostics implicated swapz' >&2
    exit 1
fi

# ID38 depth=2 remains a diagnostic module/benchmark control. Two idle-host
# five-pair cycles found no useful-throughput or latency benefit. Production
# remains depth=1 and routine qualification no longer spends ten sessions here.

printf '%s\n' \
    'PASS_LOADED_TEST_EXECUTION: smoke, 14 mixed sessions, 4 directional modern-storage envelope sessions, 20 ID63 toggle sessions, 48 sustained write-only sessions, and the ID36 resource-pressure gate completed.' \
    'PERFORMANCE_WIN=EVIDENCE_ONLY: all emulated devices use production delta64+DELTA64_SHUF8+LZ4; fast mixed, ID63, promoted independent READ fan-out, and fast QD4/QD8/QD32 carry bounded matched evidence; delta64 off/on, ordinary LZ4 acceleration, coalescing-cap selection, lower-WRITE depth 1/2, K1 read-bypass and delta64 preparation-width A/Bs are retired from routine qualification.'
