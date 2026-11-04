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
# These are requirements for a future loaded owner-host observation, not
# evidence that this invocation has executed either instrumentation lane.
printf 'LOADED_HOST_CHECKLIST kernel=running-uname-r config=matching-running-kernel module=sha256+vermagic+clean-build-source source_sha=%s boot_id=pre/post-same-boot instrumentation=%s\n' "$source_sha" "$required"
printf '%s\n' 'LOADED_HOST_CHECKLIST markers=SOURCE_HEAD,RUNNING_KERNEL,MODULE_SHA256,PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP,PASS_LOADED_COMPOUND_BIO,PASS_LOADED_LIVE_GC,PASS_LOADED_DISCARD_TRIM,PASS_LOADED_SUSPEND_DRAIN,PASS_RETAINED_SYNTHETIC_WRITE_FAULT,PASS_LOADED_SYNTHETIC_READ_FAULT,PASS_RETAINED_SYNTHETIC_FLUSH_FAULT,PASS_LOADED_CODEC_ERROR_PATHS,PASS_LOADED_COMPLETION_HANDOFF'
printf '%s\n' 'LOADED_HOST_CHECKLIST final_marker=PASS: loaded isolated swapz byte-exact I/O, clean teardown'
printf '%s\n' 'LOADED_HOST_CHECKLIST diagnostics=complete-newline-dmesg-baseline-to-final-on-one-boot bounded_by=owned-helper-900s+5s-kill-after runtime=before-and-after-I/O'
[[ "${SWAPZ_DEBUG_OWNED_COORDINATED:-}" == YES_OWNED_NULLBLK_ONLY ]] ||
    fail "explicit owner/Codex coordination token required"

# The rootless unittest uses a private, generated PATH containing inert command
# mocks. Never treat its observations as loaded-kernel qualification.
replay_only=0
if [[ "${SWAPZ_KERNEL_DEBUG_REPLAY_ONLY:-}" == ROOTLESS_VALIDATOR_ONLY ]]; then
    replay_only=1
    replay_bin="${SWAPZ_KERNEL_DEBUG_REPLAY_BIN:-}"
    [[ -n "$replay_bin" && -f "$replay_bin/ROOTLESS_VALIDATOR_ONLY" ]] ||
        fail "rootless replay mock directory missing"
    for mocked_command in sudo python3 git make modinfo nm; do
        [[ "$(command -v "$mocked_command")" == "$replay_bin/$mocked_command" ]] ||
            fail "rootless replay requires isolated $mocked_command mock"
    done
    printf '%s\n' 'ROOTLESS_VALIDATOR_ONLY=ACTIVE; no kernel module or device operations'
else
    [[ "$(id -u)" != 0 ]] || fail "invoke from an unprivileged main checkout"
fi
[[ "$(git branch --show-current)" == main ]] || fail "main branch required"
[[ "$(git rev-parse HEAD)" == "$source_sha" ]] || fail "source HEAD mismatch"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] ||
    fail "working tree is not clean"
if (( !replay_only )); then
    [[ ! -d /sys/module/dm_swapz ]] ||
        fail "pre-existing dm_swapz is not owned by this session"
fi
for command_name in git grep make modinfo nm python3 sudo timeout; do
    command -v "$command_name" >/dev/null ||
        fail "missing required tool $command_name"
done

# Run the rootless negative controls before any privileged access. Then detect
# build-time support before sudo; runtime activity is proved separately.
if (( !replay_only )); then
    if ! python3 -B tests/runtime/native/kernel-debug-qualification-test.py -q; then
        fail "rootless kernel-debug contracts failed"
    fi
fi
probe_rc=0
python3 -B tests/tools/kernel-debug-qualify.py probe --require "$required" ||
    probe_rc=$?
(( probe_rc == 0 )) ||
    fail "required instrumentation unavailable: $required (probe exit=$probe_rc)"
privilege_rc=0
sudo -n true || privilege_rc=$?
(( privilege_rc == 0 )) ||
    fail "noninteractive privilege unavailable (exit=$privilege_rc)"

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
runtime_before_rc=0
capture_runtime_snapshot "$session/runtime-before.json" ||
    runtime_before_rc=$?
(( runtime_before_rc == 0 )) ||
    fail "required $required runtime instrumentation unavailable before I/O (exit=$runtime_before_rc)"
runtime_check_rc=0
python3 -B tests/tools/kernel-debug-qualify.py snapshot-check \
    --require "$required" --snapshot "$session/runtime-before.json" ||
    runtime_check_rc=$?
(( runtime_check_rc == 0 )) ||
    fail "required $required runtime instrumentation inactive before I/O (exit=$runtime_check_rc)"

# The existing helper provisions its own random, memory_backed=1 configfs
# null_blk, proves rdev/size/holders/mounts/swaps, injects its eight bounded
# constructor ENOMEM failures, and quarantines uncertain teardown.
baseline_rc=0
sudo -n dmesg --color=never --notime > "$session/baseline.log" ||
    baseline_rc=$?
(( baseline_rc == 0 )) ||
    fail "kernel diagnostic baseline unreadable (exit=$baseline_rc)"
helper_timeout=900s
helper_kill_after=5s
if (( replay_only )); then
    helper_timeout=1s
    helper_kill_after=1s
fi
helper_rc=0
timeout --signal=TERM --kill-after="$helper_kill_after" "$helper_timeout" sudo -n bash \
    tests/tools/deploy-nullblk.sh --validated-source "$source_sha" \
    > "$session/execution.log" 2>&1 || helper_rc=$?

# Always inspect the bounded interval, including on helper failure: a KASAN,
# KCSAN or lockdep splat is stronger information than a later missing preflight.
final_rc=0
sudo -n dmesg --color=never --notime > "$session/final.log" ||
    final_rc=$?
runtime_after_rc=0
capture_runtime_snapshot "$session/runtime-after.json" ||
    runtime_after_rc=$?
if (( runtime_after_rc != 0 )); then
    # An unavailable after-snapshot cannot manufacture a clean run.
    printf '%s\n' '{}' > "$session/runtime-after.json"
fi

verify_rc=0
verify_output="$(python3 -B tests/tools/kernel-debug-qualify.py verify \
    --require "$required" \
    --source-sha "$source_sha" \
    --baseline "$session/baseline.log" \
    --final "$session/final.log" \
    --execution "$session/execution.log" \
    --runtime-before "$session/runtime-before.json" \
    --runtime-after "$session/runtime-after.json")" || verify_rc=$?
if (( helper_rc != 0 )); then
    # The helper/timeout is an independent FAIL even if final evidence is
    # incomplete. Include an independently confirmed bounded kernel FAIL.
    if (( verify_rc == 1 )); then
        printf '%s\n' "$verify_output"
    fi
    printf 'FAIL_KERNEL_DEBUG_OWNED: owned null_blk helper exit=%d (lane=%s; bounded evidence retained)\n' \
        "$helper_rc" "$lane" >&2
    exit 1
fi
if (( verify_rc == 1 )); then
    printf '%s\n' "$verify_output"
    exit 1
fi
(( final_rc == 0 )) ||
    fail "final kernel diagnostic capture unavailable (exit=$final_rc)"
(( runtime_after_rc == 0 )) ||
    fail "required $required runtime instrumentation unavailable after I/O (exit=$runtime_after_rc)"
if (( replay_only )); then
    if (( verify_rc == 0 )); then
        printf 'ROOTLESS_VALIDATOR_ONLY=PASS lane=%s; LOADED_KERNEL_PASS=NOT_RUN\n' "$lane"
    else
        printf '%s\n' "$verify_output"
    fi
else
    printf '%s\n' "$verify_output"
    if (( verify_rc == 0 )); then
        printf 'KERNEL_DEBUG_OWNED_LANE=%s source_sha=%s\n' "$lane" "$source_sha"
    fi
fi
exit "$verify_rc"
