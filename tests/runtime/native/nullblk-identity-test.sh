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
printf '240:7\n241:8\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
printf '240:7' > "$TMP/sysblock/$NAME/dev"
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
source = source.replace(
    '[[ -n $mapper_node && -b $mapper_node ]] ||',
    '[[ -n $mapper_node && -e $mapper_node ]] ||',
)
source = source.replace('[[ -b $source ]]', '[[ -e $source ]]')
source = source.replace('-b $lower', '-e $lower')
# Inspect only this synthetic process's opened fd through procfs.
source = source.replace(str(root / "proc") + '/$BASHPID/fd/', '/proc/$BASHPID/fd/')
source = source.replace(
    '[[ -n $source_devno && -b $swap_path ]]',
    '[[ -n $source_devno && -e $swap_path ]]',
)
source = source.replace('[[ -b $swap_path ]]', '[[ -e $swap_path ]]')
source = source.replace(
    'trap \'rc=$?; preflight_internal_error "$rc" "$LINENO"\' ERR',
    'trap \'rc=$?; preflight_internal_error "$rc" "$LINENO"\' ERR\n'
    '[[ ${SWAPZ_FIXTURE_CASE:-} != internal_failure ]] || false',
)
pathlib.Path(sys.argv[2]).write_text(source, encoding="utf-8")
PY
cat > "$TOOLS/clear-tmp-before-memory-check.sh" <<'SH'
# Test-only replacement: never touch /tmp or real completion proofs.
swapz_clear_tmp_before_memory_check() {
    if [[ $SWAPZ_FIXTURE_CASE == cleanup_permission ]]; then
        printf 'BLOCKED: exact completed-owned cleanup helper returned EACCES\n' >&2
        return 1
    fi
    return 0
}
SH
# Only these utilities exist in the child PATH. All potentially privileged
# commands are fixed stubs, never inherited host commands.
for command in bash tr cat readlink find rm python3 mkdir mv cp; do
    executable="$(command -v "$command")" || die "fixture setup lacks $command"
    ln -s "$executable" "$STUBS/$command"
done
REAL_AWK="$(command -v awk)" || die "fixture setup lacks awk"
REAL_LS="$(command -v ls)" || die "fixture setup lacks ls"
REAL_STAT="$(command -v stat)" || die "fixture setup lacks stat"
REAL_RMDIR="$(command -v rmdir)" || die "fixture setup lacks rmdir"
cat > "$STUBS/awk" <<SH
#!/bin/bash
if [[ \${SWAPZ_FIXTURE_CASE:-} == swap_inventory_error &&
      "\$*" == *"/proc/swaps"* ]]; then
    exit 98
fi
exec "$REAL_AWK" "\$@"
SH
cat > "$STUBS/ls" <<SH
#!/bin/bash
if [[ \${SWAPZ_FIXTURE_CASE:-} == journal_permission ]]; then
    exit 98
fi
exec "$REAL_LS" "\$@"
SH
cat > "$STUBS/stat" <<SH
#!/bin/bash
if [[ \${SWAPZ_FIXTURE_CASE:-} == unreadable_identity ]]; then
    exit 13
fi
if [[ "\$1" == "-Lc" && "\$2" == "%Hr:%Lr" &&
      "\$3" == "$FIXTURE/dev/mapper/swapz-demo-$TOKEN" ]]; then
    printf '253:0\n'
    exit 0
fi
if [[ "\$1" == "-Lc" && "\$2" == "%Hr:%Lr" &&
      "\$3" == "$FIXTURE/dev/nullb-swapz-$TOKEN" ]]; then
    printf '240:7\n'
    exit 0
fi
exec "$REAL_STAT" "\$@"
SH
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
printf 'unexpected\n' > "$SWAPZ_FIXTURE_ROOT/unexpected-rmmod"
exit 98
SH
cat > "$STUBS/timeout" <<'SH'
#!/bin/bash
case "$SWAPZ_FIXTURE_CASE" in
    owned_cleanup|replaced_inode|cleanup_failure)
        [[ "$*" == *"dmsetup remove --retry SWAPZ-TEST-aaaaaaaaaaaaaaaa" ]] || exit 98
        fake_root="$SWAPZ_FIXTURE_ROOT"
        config="$fake_root/sys/kernel/config/nullb/nullb-swapz-aaaaaaaaaaaaaaaa"
        rm -- "$fake_root/dev/mapper/swapz-demo-aaaaaaaaaaaaaaaa" || exit 98
        printf '0\n' > "$fake_root/sys/module/dm_swapz/refcnt"
        if [[ $SWAPZ_FIXTURE_CASE == replaced_inode ]]; then
            mv -- "$config" "$fake_root/retained-original-config" || exit 98
            mkdir -- "$config" || exit 98
            for attribute in index memory_backed size blocksize queue_mode power; do
                cp -- "$fake_root/retained-original-config/$attribute" "$config/$attribute" || exit 98
            done
        fi
        exit 0
        ;;
    *) exit 98 ;;
esac
SH
cat > "$STUBS/rmdir" <<SH
#!/bin/bash
[[ "\$1" == -- && "\$2" == "\$SWAPZ_FIXTURE_ROOT/sys/kernel/config/nullb/nullb-swapz-aaaaaaaaaaaaaaaa" ]] || exit 98
[[ "\$SWAPZ_FIXTURE_CASE" == owned_cleanup ]] || exit 98
for attribute in index memory_backed size blocksize queue_mode power; do
    rm -- "\$2/\$attribute" || exit 98
done
exec "$REAL_RMDIR" -- "\$2"
SH
cat > "$STUBS/findmnt" <<'SH'
#!/bin/bash
case "$SWAPZ_FIXTURE_CASE" in
    mounted_mapper)
        printf 'fixture-mount\n'
        exit 0
        ;;
    mount_inventory_empty)
        exit 0
        ;;
    mount_inventory_error)
        exit 98
        ;;
    *)
        exit 1
        ;;
esac
SH
cat > "$STUBS/dmsetup" <<'SH'
#!/bin/bash
case "$*" in
    "ls --target swapz --noheadings")
        if [[ $SWAPZ_FIXTURE_CASE == mapper_inventory_error ]]; then
            exit 98
        elif [[ $SWAPZ_FIXTURE_CASE == busy_mapper ]]; then
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (253:0)\nswapz-demo-bbbbbbbbbbbbbbbb (253:1)\n'
        elif [[ $SWAPZ_FIXTURE_CASE == noncanonical_mapper_major ]]; then
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (0253:0)\n'
        elif [[ $SWAPZ_FIXTURE_CASE == malformed_mapper_fields ]]; then
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (253:0) extra\n'
        elif [[ $SWAPZ_FIXTURE_CASE == mapper_inventory_identity_mismatch ]]; then
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (254:9)\n'
        else
            printf 'swapz-demo-aaaaaaaaaaaaaaaa (253:0)\n'
        fi
        ;;
    "info -c --noheadings -o uuid swapz-demo-aaaaaaaaaaaaaaaa")
        case "$SWAPZ_FIXTURE_CASE" in
            stale_token) printf 'SWAPZ-TEST-bbbbbbbbbbbbbbbb\n' ;;
            primary_namespace) printf 'SWAPZ-PRIMARY-aaaaaaaaaaaaaaaa\n' ;;
            recognized_readfault) printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa-readfault\n' ;;
            recognized_codec) printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa-codec-background\n' ;;
            recognized_completion) printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa-completionfault\n' ;;
            recognized_constructor) printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa-ctor-8\n' ;;
            *) printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa\n' ;;
        esac
        ;;
    "deps -o devname swapz-demo-aaaaaaaaaaaaaaaa")
        if [[ $SWAPZ_FIXTURE_CASE == wrong_owner ]]; then
            printf '1 dependencies : (nullb-swapz-bbbbbbbbbbbbbbbb)\n'
        elif [[ $SWAPZ_FIXTURE_CASE == foreign_dependency ]]; then
            counter_file="$SWAPZ_FIXTURE_ROOT/dependency-count"
            if [[ -e $counter_file ]]; then
                printf '1 dependencies : (nullb-swapz-bbbbbbbbbbbbbbbb)\n'
            else
                : > "$counter_file"
                printf '1 dependencies : (nullb-swapz-aaaaaaaaaaaaaaaa)\n'
            fi
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
chmod 0755 "$STUBS"/awk "$STUBS"/ls "$STUBS"/stat \
    "$STUBS"/id "$STUBS"/uname "$STUBS"/modprobe \
    "$STUBS"/rmmod "$STUBS"/timeout "$STUBS"/rmdir "$STUBS"/findmnt \
    "$STUBS"/dmsetup "$STUBS"/sleep

reset_fake() {
    # Delete only this test's known fake roots; never real /proc, /sys or /dev.
    rm -rf -- "$FIXTURE/proc" "$FIXTURE/sys" "$FIXTURE/dev" \
        "$FIXTURE/boot" "$FIXTURE/lib" "$FIXTURE/var" \
        "$FIXTURE/retained-original-config" "$FIXTURE/dependency-count" \
        "$FIXTURE/unexpected-rmmod"
    mkdir -p "$FIXTURE/proc/self" "$FIXTURE/sys/kernel/config" \
        "$FIXTURE/sys/module" "$FIXTURE/dev/mapper"
    printf 'CapEff:\t0000000000200000\n' > "$FIXTURE/proc/self/status"
    printf 'MemAvailable: 2097152 kB\n' > "$FIXTURE/proc/meminfo"
    printf 'Filename Type Size Used Priority\n' > "$FIXTURE/proc/swaps"
    printf 'Character devices:\n\nBlock devices:\n240 nullb\n' > "$FIXTURE/proc/devices"
}

setup_busy_module() {
    mkdir -p "$FIXTURE/sys/module/dm_swapz"
    printf '1\n' > "$FIXTURE/sys/module/dm_swapz/refcnt"
}
setup_mapper_node() {
    : > "$FIXTURE/dev/mapper/swapz-demo-$TOKEN"
}
setup_owned_lower() {
    local config="$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN"
    local disk="$FIXTURE/sys/block/nullb-swapz-$TOKEN"
    mkdir -p "$config" "$disk/holders" "$FIXTURE/sys/dev/block"
    printf '1\n' > "$config/memory_backed"
    printf '1\n' > "$config/power"
    printf '7\n' > "$config/index"
    printf '64\n' > "$config/size"
    printf '4096\n' > "$config/blocksize"
    printf '2\n' > "$config/queue_mode"
    printf '240:7\n' > "$disk/dev"
    ln -s "$disk" "$FIXTURE/sys/dev/block/240:7"
    : > "$FIXTURE/dev/nullb-swapz-$TOKEN"
}
run_case() {
    local case_name="$1" expected="$2" expected_result="$3" expected_errno="$4"
    local result=0 output
    reset_fake
    case "$case_name" in
        missing_capability) printf 'CapEff:\t0000000000000000\n' > "$FIXTURE/proc/self/status" ;;
        capability_unreadable)
            rm -- "$FIXTURE/proc/self/status"
            mkdir "$FIXTURE/proc/self/status"
            ;;
        missing_module|missing_tool|cleanup_permission|retained_journal|journal_permission|invalid_debug|low_memory|unrelated_swap|unclaimed_nullb|internal_failure) ;;
        idle_module_busy)
            mkdir -p "$FIXTURE/sys/module/dm_swapz"
            printf '0\n' > "$FIXTURE/sys/module/dm_swapz/refcnt"
            ;;
        busy_mapper|mapper_inventory_error|noncanonical_mapper_major|malformed_mapper_fields|mapper_inventory_identity_mismatch|stale_token|primary_namespace|wrong_owner|owned_swap|owned_swap_alias|unresolved_swap_alias|unreadable_identity|mounted_mapper|mount_inventory_empty|mount_inventory_error|swap_inventory_error|malformed_swap_inventory|recognized_readfault|recognized_codec|recognized_completion|recognized_constructor|owned_cleanup|replaced_inode|missing_sysfs_proof|mismatched_devno|foreign_dependency|cleanup_failure)
            setup_busy_module
            ;;
        *) die "unknown fixture case $case_name" ;;
    esac
    case "$case_name" in
        invalid_debug)
            mkdir -p "$FIXTURE/proc"
            printf 'not a gzip kernel configuration\n' > "$FIXTURE/proc/config.gz" ;;
        retained_journal|journal_permission)
            mkdir -p "$FIXTURE/var/lib/swapz-package-transactions"
            printf 'retain\n' > "$FIXTURE/var/lib/swapz-package-transactions/transaction" ;;
        low_memory) printf 'MemAvailable: 512000 kB\n' > "$FIXTURE/proc/meminfo" ;;
        unrelated_swap)
            printf '/var/swapfile file 1024 0 -3\n' >> "$FIXTURE/proc/swaps" ;;
        owned_swap)
            setup_mapper_node
            printf '%s\n' "$FIXTURE/dev/mapper/swapz-demo-aaaaaaaaaaaaaaaa partition 1024 0 -2" >> "$FIXTURE/proc/swaps" ;;
        owned_swap_alias)
            setup_mapper_node
            : > "$FIXTURE/dev/dm-0"
            printf '%s\n' "$FIXTURE/dev/dm-0 partition 1024 0 -2" >> "$FIXTURE/proc/swaps" ;;
        unresolved_swap_alias)
            setup_mapper_node
            printf '%s\n' "$FIXTURE/dev/dm-missing partition 1024 0 -2" >> "$FIXTURE/proc/swaps" ;;
        swap_inventory_error|malformed_swap_inventory)
            setup_mapper_node
            if [[ "$case_name" == malformed_swap_inventory ]]; then
                printf 'malformed swap record\n' >> "$FIXTURE/proc/swaps"
            fi
            ;;
        wrong_owner)
            setup_mapper_node
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN"
            printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed" ;;
        unreadable_identity)
            setup_owned_lower
            setup_mapper_node
            ;;
        noncanonical_mapper_major|malformed_mapper_fields|mapper_inventory_identity_mismatch|recognized_readfault|recognized_codec|recognized_completion|recognized_constructor|owned_cleanup|replaced_inode|missing_sysfs_proof|mismatched_devno|foreign_dependency|cleanup_failure)
            setup_owned_lower
            setup_mapper_node
            if [[ $case_name == missing_sysfs_proof ]]; then
                rm -- "$FIXTURE/sys/block/nullb-swapz-$TOKEN/dev"
            elif [[ $case_name == mismatched_devno ]]; then
                printf '240:8\n' > "$FIXTURE/sys/block/nullb-swapz-$TOKEN/dev"
            fi
            ;;
        unclaimed_nullb)
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN"
            ;;
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
        [[ $result == 1 &&
           "$output" == *"BLOCKED: LOADED_PREFLIGHT=BLOCKED check=$expected errno=$expected_errno "* ]] ||
            die "$case_name failed to refuse with check=$expected errno=$expected_errno status=$result: $output"
    elif [[ "$expected_result" == NOT_AUTHORIZED ]]; then
        [[ $result == 1 &&
           "$output" == *"BLOCKED: LOADED_PREFLIGHT=NOT_AUTHORIZED check=$expected errno=$expected_errno "* ]] ||
            die "$case_name did not classify lack of authorization: $output"
    elif [[ "$expected_result" == FAIL ]]; then
        [[ $result == 1 &&
           "$output" == *'FAIL: loaded preflight internal command failed status=1 line='* &&
           "$output" != *'BLOCKED: LOADED_PREFLIGHT='* ]] ||
            die "$case_name did not preserve unexpected failure attribution: $output"
    else
        [[ $result == 0 && "$output" != *'BLOCKED:'* && "$output" != *'FAIL:'* ]] ||
            die "$case_name unexpectedly refused or masked a failure: $output"
        [[ "$output" == *"$expected"* ]] ||
            die "$case_name omitted expected observation: $output"
    fi
    if [[ "$case_name" == noncanonical_mapper_major ||
          "$case_name" == malformed_mapper_fields ]]; then
        [[ "$output" == *'pipeline_status=2; '* &&
           "$output" == *'observed invalid or unreadable listing;'* ]] ||
            die "$case_name did not refuse malformed mapper identity before cleanup: $output"
    elif [[ "$case_name" == mapper_inventory_identity_mismatch ]]; then
        [[ "$output" == *'expected dmsetup inventory device identity to match canonical mapper node; observed mismatch; no holder signal; inspect device-mapper inventory and udev state without cleanup'* &&
           "$output" != *"$FIXTURE/dev/"* ]] ||
            die "$case_name did not refuse the stale mapper identity safely: $output"
    fi
    [[ -f "$FIXTURE/proc/swaps" ]] || die "host swap inventory was mutated"
    [[ ! -e "$FIXTURE/unexpected-rmmod" ]] ||
        die "unowned module unload was attempted"
    if [[ "$case_name" == owned_cleanup ]]; then
        [[ ! -e "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN" &&
           ! -e "$FIXTURE/dev/mapper/swapz-demo-$TOKEN" ]] ||
            die "owned cleanup did not remove its proven mapper and configfs object"
    elif [[ "$case_name" == replaced_inode ]]; then
        [[ "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/power")" == 1 &&
           "$(cat "$FIXTURE/retained-original-config/power")" == 1 ]] ||
            die "replaced configfs inode was powered off"
    elif [[ "$case_name" == cleanup_failure ]]; then
        [[ -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN" &&
           "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/power")" == 0 ]] ||
            die "cleanup error failed to retain powered-off configfs state"
    fi
    if [[ "$case_name" == owned_cleanup || "$case_name" == replaced_inode ||
          "$case_name" == cleanup_failure || "$case_name" == missing_sysfs_proof ||
          "$case_name" == mismatched_devno || "$case_name" == foreign_dependency ]]; then
        [[ "$output" == *"phase="* && "$output" == *"resource_kind="* &&
           "$output" == *"expected_proof="* && "$output" == *"observed_proof="* &&
           "$output" == *"original_errno_or_exit="* &&
           "$output" == *"retained_state_action="* &&
           "$output" != *"$FIXTURE/"* ]] ||
            die "$case_name omitted private-safe cleanup failure attribution"
    fi
    if [[ "$case_name" == unrelated_swap ]]; then
        grep -Fxq '/var/swapfile file 1024 0 -3' "$FIXTURE/proc/swaps" ||
            die "unrelated swap disappeared"
    fi
}

# Demonstrate the first old path-only false admission entirely in this private
# directory. The old ownership check admitted the replacement because its
# pathname, memory_backed and power values matched after the inode changed.
reset_fake
setup_owned_lower
legacy_config="$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN"
[[ -d $legacy_config && "$(cat "$legacy_config/memory_backed")" == 1 &&
   "$(cat "$legacy_config/power")" == 1 ]] ||
    die "legacy ownership model did not admit the initial synthetic object"
mv -- "$legacy_config" "$FIXTURE/retained-original-config"
mkdir -- "$legacy_config"
for attribute in index memory_backed size blocksize queue_mode power; do
    cp -- "$FIXTURE/retained-original-config/$attribute" "$legacy_config/$attribute"
done
[[ -d $legacy_config && "$(cat "$legacy_config/memory_backed")" == 1 &&
   "$(cat "$legacy_config/power")" == 1 ]] ||
    die "legacy pathname predicate did not admit replacement"
printf '0\n' > "$legacy_config/power"
[[ "$(cat "$legacy_config/power")" == 0 &&
   "$(cat "$FIXTURE/retained-original-config/power")" == 1 ]] ||
    die "legacy false-cleanup admission did not mutate only the replacement"

[[ -x "$ROOT/tests/tools/loaded-preflight.sh" ]] ||
    die "preflight executable mode is missing"
bash -n "$TOOLS/loaded-preflight.sh" ||
    die "sandboxed preflight syntax is invalid"
run_case missing_capability cap_sys_admin NOT_AUTHORIZED unavailable
run_case capability_unreadable cap_sys_admin BLOCKED 21
run_case missing_module null_blk_module BLOCKED unavailable
run_case missing_tool required_tool BLOCKED unavailable
run_case invalid_debug kernel_debug_config BLOCKED unavailable
run_case retained_journal package_journal BLOCKED unavailable
run_case journal_permission package_journal BLOCKED unavailable
run_case cleanup_permission completed_owned_tmp_cleanup BLOCKED unavailable
run_case idle_module_busy idle_module_removal BLOCKED unavailable
run_case busy_mapper mapper_inventory BLOCKED unavailable
run_case mapper_inventory_error mapper_inventory BLOCKED unavailable
run_case noncanonical_mapper_major mapper_inventory BLOCKED unavailable
run_case malformed_mapper_fields mapper_inventory BLOCKED unavailable
run_case mapper_inventory_identity_mismatch mapper_device_identity BLOCKED unavailable
run_case stale_token stale_run_token BLOCKED unavailable
run_case wrong_owner null_blk_owner BLOCKED unavailable
run_case owned_swap active_owned_swap BLOCKED unavailable
run_case owned_swap_alias active_owned_swap BLOCKED unavailable
run_case unresolved_swap_alias swap_inventory BLOCKED unavailable
run_case mounted_mapper mounted_owned_mapper BLOCKED unavailable
run_case mount_inventory_empty mount_inventory BLOCKED unavailable
run_case mount_inventory_error mount_inventory BLOCKED unavailable
run_case swap_inventory_error swap_inventory BLOCKED unavailable
run_case malformed_swap_inventory swap_inventory BLOCKED unavailable
run_case unreadable_identity swap_device_identity BLOCKED unavailable
run_case recognized_readfault owned_mapper_removal BLOCKED unavailable
run_case recognized_codec owned_mapper_removal BLOCKED unavailable
run_case recognized_completion owned_mapper_removal BLOCKED unavailable
run_case recognized_constructor owned_mapper_removal BLOCKED unavailable
run_case primary_namespace stale_run_token BLOCKED unavailable
run_case missing_sysfs_proof owned_resource_proof BLOCKED unavailable
run_case mismatched_devno owned_resource_proof BLOCKED unavailable
run_case foreign_dependency owned_resource_proof BLOCKED unavailable
run_case replaced_inode owned_resource_proof BLOCKED unavailable
run_case cleanup_failure owned_resource_proof BLOCKED 98
run_case owned_cleanup idle_module_removal BLOCKED unavailable
run_case unclaimed_nullb unclaimed_null_blk BLOCKED unavailable
run_case internal_failure internal_failure FAIL unavailable
# Early MemAvailable is observational only; later ID36 owns admission.
run_case low_memory OBSERVED_ID36_EARLY_HOST_MEMORY PASS unavailable
run_case unrelated_swap LOADED_PREFLIGHT_DM_SWAPZ=absent PASS unavailable
printf '%s\n' 'PASS: null_blk identity, legacy false admission and 41 isolated preflight fixtures'
