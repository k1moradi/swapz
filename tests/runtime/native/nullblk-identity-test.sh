#!/usr/bin/env bash
# Rootless identity and preflight regression fixtures: no modules, block IO,
# mknod, host swap mutations, privileged runner or real host /sys writes.
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/../../.." && pwd -P)"
source "$ROOT/tests/tools/nullblk-identity.sh"
mkdir -p "$ROOT/build/tests"
TMP="$(mktemp -d "$ROOT/build/tests/nullblk-name.XXXXXXXX")"
NAME=nullb-swapz-0123456789abcdef
TOKEN=aaaaaaaaaaaaaaaa
OTHER_TOKEN=bbbbbbbbbbbbbbbb
cleanup() {
    # This single mktemp-owned build fixture is not a /tmp cleanup candidate.
    [[ "$TMP" == "$ROOT/build/tests/nullblk-name."* ]] &&
        rm -rf -- "$TMP"
}
trap cleanup EXIT
die() { printf 'FAIL: rootless null_blk fixture: %s\n' "$*" >&2; exit 1; }
refused_disk() {
    if swapz_resolve_owned_disk "$1" "$2" "$3" >/dev/null; then
        die "unproved null_blk name or dev telemetry accepted"
    fi
}

mkdir -p "$TMP/sysblock/$NAME" "$TMP/sysblock/nullb7"
printf '240:7\n' > "$TMP/sysblock/$NAME/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP/sysblock")" == "$NAME" ]] ||
    die "private configfs disk name was not resolved"
rm -- "$TMP/sysblock/$NAME/dev"
printf '240:7\n' > "$TMP/sysblock/nullb7/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP/sysblock")" == nullb7 ]] ||
    die "indexed disk name was not resolved"
printf '240:7\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/$NAME/dev" "$TMP/sysblock/nullb7/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
refused_disk swapz-0123456789abcdef 7 "$TMP/sysblock"
refused_disk /dev/nullb7 7 "$TMP/sysblock"
refused_disk "$NAME" abc "$TMP/sysblock"
printf 'garbage\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
printf '240:07\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/$NAME/dev"
ln -s /dev/null "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/$NAME/dev"

# A fixture-only copy rewrites every absolute proc/sys/dev and package
# journal root to the private build directory. The copied cleanup helper
# cannot invoke the real completed-session cleaner, even when run as root.
FIXTURE="$TMP/preflight-fixture"
TOOLS="$FIXTURE/tools"
STUBS="$FIXTURE/stubs"
mkdir -p "$TOOLS" "$STUBS"
python3 - "$ROOT/tests/tools/loaded-preflight.sh" "$TOOLS/loaded-preflight.sh" "$FIXTURE" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
root = pathlib.Path(sys.argv[3])
for original, replacement in (
    ("/var/lib/swapz-package-transactions", str(root / "var/lib/swapz-package-transactions")),
    ("/lib/modules/", str(root / "lib/modules/")),
    ("/proc", str(root / "proc")),
    ("/sys", str(root / "sys")),
    ("/boot", str(root / "boot")),
    ("/dev", str(root / "dev")),
):
    source = source.replace(original, replacement)
pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")
PY
cat > "$TOOLS/clear-tmp-before-memory-check.sh" <<'SH'
# Test-only replacement: never touch /tmp or real completion proofs.
swapz_clear_tmp_before_memory_check() {
    if [[ $SWAPZ_FIXTURE_CASE == cleanup_permission ]]; then
        printf 'BLOCKED: exact completed-owned cleanup helper returned EACCES\n' >&2
        return 13
    fi
    return 0
}
SH
# Only these utilities exist in the child PATH. All potentially privileged
# commands are fixed stubs, never inherited host commands.
for command in bash awk tr cat readlink stat ls find rm rmdir python3; do
    executable="$(command -v "$command")" || die "fixture setup lacks $command"
    ln -s "$executable" "$STUBS/$command"
done
cat > "$STUBS/id" <<'SH'
#!/bin/bash
[[ "$*" == "-u" ]] || exit 98
printf '0\n'
SH
cat > "$STUBS/uname" <<'SH'
#!/bin/bash
[[ "$*" == "-r" ]] || exit 98
printf 'fixture-kernel\n'
SH
cat > "$STUBS/modprobe" <<'SH'
#!/bin/bash
[[ "$*" == "-n -q null_blk" ]] || exit 98
[[ $SWAPZ_FIXTURE_CASE != missing_module ]]
SH
cat > "$STUBS/rmmod" <<'SH'
#!/bin/bash
# Refuse any unexpected mutation in the fake-preflight negative cases.
exit 98
SH
cat > "$STUBS/timeout" <<'SH'
#!/bin/bash
exit 98
SH
cat > "$STUBS/findmnt" <<'SH'
#!/bin/bash
[[ $SWAPZ_FIXTURE_CASE != mounted_mapper ]] || printf 'fixture-mount\n'
[[ $SWAPZ_FIXTURE_CASE != mounted_mapper ]]
SH
cat > "$STUBS/dmsetup" <<'SH'
#!/bin/bash
case "$*" in
    "ls --target swapz --noheadings")
        if [[ $SWAPZ_FIXTURE_CASE == busy_mapper ]]; then
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (253:0)\nswapz-demo-bbbbbbbbbbbbbbbb (253:1)\n'
        else
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (253:0)\n'
        fi
        ;;
    "info -c --noheadings -o uuid swapz-demo-aaaaaaaaaaaaaaaa")
        if [[ $SWAPZ_FIXTURE_CASE == stale_token ]]; then
            printf 'SWAPZ-TEST-bbbbbbbbbbbbbbbb\n'
        else
            printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa\n'
        fi
        ;;
    "deps -o devname swapz-demo-aaaaaaaaaaaaaaaa")
        if [[ $SWAPZ_FIXTURE_CASE == wrong_owner ]]; then
            printf '1 dependencies : (nullb-swapz-bbbbbbbbbbbbbbbb)\n'
        else
            printf '1 dependencies : (nullb-swapz-aaaaaaaaaaaaaaaa)\n'
        fi
        ;;
    "info -c --noheadings -o open swapz-demo-aaaaaaaaaaaaaaaa")
        printf '0\n'
        ;;
    *) exit 98 ;;
esac
SH
cat > "$STUBS/sleep" <<'SH'
#!/bin/bash
exit 98
SH
chmod 0755 "$STUBS"/id "$STUBS"/uname "$STUBS"/modprobe \
    "$STUBS"/rmmod "$STUBS"/timeout "$STUBS"/findmnt \
    "$STUBS"/dmsetup "$STUBS"/sleep

reset_fake() {
    # Delete only this test's known fake roots; never real /proc, /sys or /dev.
    rm -rf -- "$FIXTURE/proc" "$FIXTURE/sys" "$FIXTURE/dev" \
        "$FIXTURE/boot" "$FIXTURE/lib" "$FIXTURE/var"
    mkdir -p "$FIXTURE/proc/self" "$FIXTURE/sys/kernel/config" \
        "$FIXTURE/sys/module" "$FIXTURE/dev/mapper"
    printf 'CapEff:\t0000000000200000\n' > "$FIXTURE/proc/self/status"
    printf 'MemAvailable: 2097152 kB\n' > "$FIXTURE/proc/meminfo"
    printf 'Filename Type Size Used Priority\n' > "$FIXTURE/proc/swaps"
}

setup_busy_module() {
    mkdir -p "$FIXTURE/sys/module/dm_swapz"
    printf '1\n' > "$FIXTURE/sys/module/dm_swapz/refcnt"
}
setup_owned_lower() {
    mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN"
    printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/memory_backed"
    printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/power"
}
run_case() {
    local case_name="$1" expected="$2" expected_result="$3"
    local result=0 output
    reset_fake
    case "$case_name" in
        missing_capability) printf 'CapEff:\t0000000000000000\n' > "$FIXTURE/proc/self/status" ;;
        missing_module|missing_tool|cleanup_permission|retained_journal|invalid_debug|low_memory|unrelated_swap) ;;
        busy_mapper|stale_token|wrong_owner|owned_swap|unreadable_identity|mounted_mapper)
            setup_busy_module ;;
        *) die "unknown fixture case $case_name" ;;
    esac
    case "$case_name" in
        invalid_debug)
            mkdir -p "$FIXTURE/proc"
            printf 'not a gzip kernel configuration\n' > "$FIXTURE/proc/config.gz" ;;
        retained_journal)
            mkdir -p "$FIXTURE/var/lib/swapz-package-transactions"
            printf 'retain\n' > "$FIXTURE/var/lib/swapz-package-transactions/transaction" ;;
        low_memory) printf 'MemAvailable: 512000 kB\n' > "$FIXTURE/proc/meminfo" ;;
        unrelated_swap)
            printf '/var/swapfile file 1024 0 -3\n' >> "$FIXTURE/proc/swaps" ;;
        owned_swap)
            printf '/dev/mapper/swapz-demo-aaaaaaaaaaaaaaaa partition 1024 0 -2\n' >> "$FIXTURE/proc/swaps" ;;
        wrong_owner)
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN"
            printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed" ;;
        unreadable_identity) setup_owned_lower ;;
    esac
    if [[ "$case_name" == missing_tool ]]; then
        mv -- "$STUBS/rmmod" "$STUBS/rmmod.hidden"
    fi
    if SWAPZ_FIXTURE_CASE="$case_name" SWAPZ_FIXTURE_ROOT="$FIXTURE" \
        PATH="$STUBS" "$STUBS/bash" "$TOOLS/loaded-preflight.sh" \
        > "$FIXTURE/output.log" 2>&1; then
        result=0
    else
        result=$?
    fi
    if [[ "$case_name" == missing_tool ]]; then
        mv -- "$STUBS/rmmod.hidden" "$STUBS/rmmod"
    fi
    output="$(cat "$FIXTURE/output.log")"
    if [[ "$expected_result" == BLOCKED ]]; then
        [[ $result == 1 && "$output" == *"BLOCKED: LOADED_PREFLIGHT=BLOCKED check=$expected"* ]] ||
            die "$case_name failed to refuse with check=$expected status=$result: $output"
    elif [[ "$expected_result" == NOT_AUTHORIZED ]]; then
        [[ $result == 1 && "$output" == *"BLOCKED: LOADED_PREFLIGHT=NOT_AUTHORIZED check=$expected"* ]] ||
            die "$case_name did not classify lack of authorization: $output"
    else
        [[ $result == 0 && "$output" != *'BLOCKED:'* && "$output" != *'FAIL:'* ]] ||
            die "$case_name unexpectedly refused or masked a failure: $output"
        [[ "$output" == *"$expected"* ]] ||
            die "$case_name omitted expected observation: $output"
    fi
    [[ -f "$FIXTURE/proc/swaps" ]] || die "host swap inventory was mutated"
    if [[ "$case_name" == unrelated_swap ]]; then
        grep -Fxq '/var/swapfile file 1024 0 -3' "$FIXTURE/proc/swaps" ||
            die "unrelated swap disappeared"
    fi
}

[[ -x "$ROOT/tests/tools/loaded-preflight.sh" ]] ||
    die "preflight executable mode is missing"
bash -n "$TOOLS/loaded-preflight.sh" ||
    die "sandboxed preflight syntax is invalid"
run_case missing_capability cap_sys_admin NOT_AUTHORIZED
run_case missing_module null_blk_module BLOCKED
run_case missing_tool required_tool BLOCKED
run_case invalid_debug kernel_debug_config BLOCKED
run_case retained_journal package_journal BLOCKED
run_case cleanup_permission completed_owned_tmp_cleanup BLOCKED
run_case busy_mapper mapper_inventory BLOCKED
run_case stale_token stale_run_token BLOCKED
run_case wrong_owner null_blk_owner BLOCKED
run_case owned_swap active_owned_swap BLOCKED
run_case mounted_mapper mounted_owned_mapper BLOCKED
run_case unreadable_identity mapper_device_identity BLOCKED
# Early MemAvailable is observational only; later ID36 owns admission.
run_case low_memory OBSERVED_ID36_EARLY_HOST_MEMORY PASS
run_case unrelated_swap LOADED_PREFLIGHT_DM_SWAPZ=absent PASS
printf '%s\n' 'PASS: null_blk identity and 14 isolated preflight refusal/observation fixtures'
