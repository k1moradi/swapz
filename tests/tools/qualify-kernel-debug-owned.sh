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
command -v timeout >/dev/null || fail "timeout command unavailable"
command -v sudo >/dev/null || fail "noninteractive privilege unavailable"

# This check is first, before sudo and before any device creation. Merely
# detecting the config is not runtime qualification evidence.
python3 -B tests/tools/kernel-debug-qualify.py probe --require "$required" ||
    fail "running kernel lacks the required enabled debug configuration"
sudo -n true || fail "noninteractive privilege unavailable"
mkdir -p build/tests
session="$(mktemp -d build/tests/kernel-debug-owned.XXXXXXXX)" ||
    fail "cannot allocate bounded evidence session"
[[ "$session" == build/tests/kernel-debug-owned.* ]] ||
    fail "evidence directory escaped build/tests"
printf 'KERNEL_DEBUG_OWNED_EVIDENCE=%s\n' "$session"

# The existing helper provisions its own random, memory_backed=1 configfs
# null_blk, proves rdev/size/holders/mounts/swaps, injects its eight bounded
# constructor ENOMEM failures, and quarantines uncertain teardown.
sudo -n dmesg --color=never --notime > "$session/baseline.log" ||
    fail "cannot read kernel diagnostic baseline"
if ! timeout --signal=TERM --kill-after=5s 900s sudo -n bash \
        tests/tools/deploy-nullblk.sh --validated-source "$source_sha" \
        > "$session/execution.log" 2>&1; then
    printf 'FAIL_KERNEL_DEBUG_OWNED: existing owned-null_blk helper failed; inspect %s\n' \
        "$session/execution.log" >&2
    exit 1
fi
sudo -n dmesg --color=never --notime > "$session/final.log" ||
    fail "cannot read final kernel diagnostics"
python3 -B tests/tools/kernel-debug-qualify.py verify \
    --require "$required" \
    --baseline "$session/baseline.log" \
    --final "$session/final.log" \
    --execution "$session/execution.log" ||
    fail "required kernel-debug evidence was incomplete or had diagnostics"
printf 'KERNEL_DEBUG_OWNED_LANE=%s source_sha=%s\n' "$lane" "$source_sha"
