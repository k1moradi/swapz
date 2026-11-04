#!/usr/bin/env bash
# Private, explicit opt-in only. Codex coordinates all loaded null_blk runs.
# No physical media, active swap, kernel install, reboot or global fault toggles.
set -Eeuo pipefail

fail() { printf 'BLOCKED_KERNEL_DEBUG_OWNED: %s\n' "$*" >&2; exit 2; }

[[ $# == 4 && "$1" == --validated-source && "$3" == --lane ]] ||
    fail "expected --validated-source <40-hex SHA> --lane kasan-lockdep|kcsan"
source_sha="$2"
lane="$4"
[[ "$source_sha" =~ ^[a-f0-9]{40}$ ]] || fail "invalid source SHA"
case "$lane" in
    kasan-lockdep) required=kasan,lockdep ;;
    kcsan) required=kcsan ;;
    *) fail "unknown debug lane" ;;
esac
[[ "${SWAPZ_DEBUG_OWNED_COORDINATED:-}" == YES_OWNED_NULLBLK_ONLY ]] ||
    fail "explicit owner/Codex coordination token required"
[[ "$(id -u)" != 0 ]] || fail "invoke from an unprivileged main checkout"
[[ "$(git branch --show-current)" == main ]] || fail "main branch required"
[[ "$(git rev-parse HEAD)" == "$source_sha" ]] || fail "source HEAD mismatch"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] ||
    fail "working tree is not clean"
[[ ! -d /sys/module/dm_swapz ]] ||
    fail "pre-existing dm_swapz is not owned by this session"
for command_name in git grep make modinfo nm python3 sudo timeout; do
    command -v "$command_name" >/dev/null ||
        fail "missing required tool $command_name"
done

# Run the rootless negative controls before any privileged access. Then detect
# build-time support before sudo; runtime activity is proved separately.
if ! python3 -B tests/runtime/native/kernel-debug-qualification-test.py -q; then
    fail "rootless kernel-debug contracts failed"
fi
python3 -B tests/tools/kernel-debug-qualify.py probe --require "$required" ||
    fail "running kernel lacks the required debug build configuration"
sudo -n true || fail "noninteractive privilege unavailable"

# Rebuild exact-source artifacts instead of trusting a pre-existing build tree.
# Signing, when required, must remain noninteractive.
SWAPZ_SIGN_NONINTERACTIVE=1 make ||
    fail "exact-source module/helper build failed"
[[ "$(git rev-parse HEAD)" == "$source_sha" &&
   -z "$(git status --porcelain --untracked-files=all)" ]] ||
    fail "source changed during exact-source build"
module=build/kernel/experimental/dm-swapz.ko
[[ "$(modinfo -F swapz_build_source_sha "$module" 2>/dev/null)" == "$source_sha" ]] ||
    fail "module build source does not match validated source"
[[ "$(modinfo -F swapz_build_source_clean "$module" 2>/dev/null)" == 1 ]] ||
    fail "module was not built from a clean validated source"
undefined_symbols="$(nm -u "$module" 2>/dev/null)" ||
    fail "cannot inspect module sanitizer instrumentation"
case "$lane" in
    kasan-lockdep)
        grep -Eq '(__asan_|__hwasan_|kasan_report)' <<< "$undefined_symbols" ||
            fail "module lacks observable KASAN instrumentation references"
        ;;
    kcsan)
        grep -Eq '(__tsan_|__kcsan_)' <<< "$undefined_symbols" ||
            fail "module lacks observable KCSAN instrumentation references"
        ;;
esac

mkdir -p build/tests
session="$(mktemp -d build/tests/kernel-debug-owned.XXXXXXXX)" ||
    fail "cannot allocate bounded evidence session"
[[ "$session" == build/tests/kernel-debug-owned.* ]] ||
    fail "evidence directory escaped build/tests"
printf 'KERNEL_DEBUG_OWNED_EVIDENCE=%s\n' "$session"

capture_runtime_snapshot() {
    local output="$1"
    sudo -n python3 -B tests/tools/kernel-debug-qualify.py runtime-snapshot \
        --require "$required" > "$output"
}

# KCSAN can be compiled but globally disabled through debugfs, and lockdep
# turns debug_locks off after its first detected inconsistency. Prove the live
# state before and after the owned I/O rather than treating Kconfig as runtime
# evidence. Missing debugfs/proc observability blocks before module insertion.
capture_runtime_snapshot "$session/runtime-before.json" ||
    fail "cannot prove required debug feature is active before owned I/O"

# The existing helper provisions its own random, memory_backed=1 configfs
# null_blk, proves rdev/size/holders/mounts/swaps, injects its eight bounded
# constructor ENOMEM failures, and quarantines uncertain teardown.
sudo -n dmesg --color=never --notime > "$session/baseline.log" ||
    fail "cannot read kernel diagnostic baseline"
helper_rc=0
timeout --signal=TERM --kill-after=5s 900s sudo -n bash \
    tests/tools/deploy-nullblk.sh --validated-source "$source_sha" \
    > "$session/execution.log" 2>&1 || helper_rc=$?
if (( helper_rc != 0 )); then
    # Best-effort postmortem evidence only; the failed helper is already
    # authoritative and no diagnostic capture can convert it into a PASS.
    sudo -n dmesg --color=never --notime > "$session/final.log" 2>/dev/null || true
    capture_runtime_snapshot "$session/runtime-after.json" 2>/dev/null || true
    printf 'FAIL_KERNEL_DEBUG_OWNED: existing owned-null_blk helper failed rc=%d; inspect %s\n' \
        "$helper_rc" "$session/execution.log" >&2
    exit 1
fi
capture_runtime_snapshot "$session/runtime-after.json" ||
    fail "cannot observe required debug feature after owned I/O"
sudo -n dmesg --color=never --notime > "$session/final.log" ||
    fail "cannot read final kernel diagnostics"

set +e
python3 -B tests/tools/kernel-debug-qualify.py verify \
    --require "$required" \
    --source-sha "$source_sha" \
    --baseline "$session/baseline.log" \
    --final "$session/final.log" \
    --execution "$session/execution.log" \
    --runtime-before "$session/runtime-before.json" \
    --runtime-after "$session/runtime-after.json"
verify_rc=$?
set -e
(( verify_rc == 0 )) || exit "$verify_rc"
printf 'KERNEL_DEBUG_OWNED_LANE=%s source_sha=%s\n' "$lane" "$source_sha"
