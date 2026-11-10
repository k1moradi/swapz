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
LOWER_TOKEN=cccccccccccccccc
cleanup() {
    # This single mktemp-owned build fixture is not a /tmp cleanup candidate.
    [[ "$TMP" == "$ROOT/build/tests/nullblk-name."* ]] &&
        rm -rf -- "$TMP"
}
trap cleanup EXIT
# A failure can originate in a direct shell command, not an assertion. Print
# only a source-controlled case, line and status; simulated device identities
# and child stderr remain private. No extra work on a successful run.
current_nullblk_case=setup
nullblk_failure_reported=0
report_nullblk_failure_marker() {
    local failure_reason=$1 failure_status=$2 failure_line=$3
    (( nullblk_failure_reported == 0 )) || return 0
    nullblk_failure_reported=1
    [[ $current_nullblk_case =~ ^[a-z][a-z0-9_-]{0,63}$ ]] ||
        current_nullblk_case=unavailable
    [[ $failure_line =~ ^[1-9][0-9]{0,6}$ ]] || failure_line=unavailable
    [[ $failure_status =~ ^[1-9][0-9]{0,2}$ ]] || failure_status=1
    printf 'FAIL: rootless nullblk fixture case=%s line=%s reason=%s status=%s\n' \
        "$current_nullblk_case" "$failure_line" "$failure_reason" "$failure_status" >&2
}
report_nullblk_unexpected_error() {
    local original_status=$1 failure_line=$2
    report_nullblk_failure_marker command_exit "$original_status" "$failure_line"
}
trap 'report_nullblk_unexpected_error "$?" "$LINENO"' ERR
die() {
    report_nullblk_failure_marker fixture_assertion 1 "$BASH_LINENO"
    printf 'FAIL: rootless null_blk fixture: %s\n' "$*" >&2
    exit 1
}
refused_disk() {
    if swapz_resolve_owned_disk "$1" "$2" "$3" >/dev/null; then
        die "unproved null_blk name or dev telemetry accepted"
    fi
}

mkdir -p "$TMP/sysblock/$NAME"
printf '240:7\n' > "$TMP/sysblock/$NAME/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP/sysblock")" == "$NAME" ]] ||
    die "private configfs disk name was not resolved"
mkdir -p "$TMP/sysblock/nullb7"
ln -s "$TMP/missing-dev" "$TMP/sysblock/nullb7/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/nullb7/dev"
rmdir -- "$TMP/sysblock/nullb7"
rm -- "$TMP/sysblock/$NAME/dev"
rmdir -- "$TMP/sysblock/$NAME"
mkdir -p "$TMP/sysblock/nullb7"
printf '240:7\n' > "$TMP/sysblock/nullb7/dev"
[[ "$(swapz_resolve_owned_disk "$NAME" 7 "$TMP/sysblock")" == nullb7 ]] ||
    die "indexed disk name was not resolved"
mkdir -p "$TMP/sysblock/$NAME"
ln -s "$TMP/missing-dev" "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/$NAME/dev"
rmdir -- "$TMP/sysblock/$NAME"
mkdir -p "$TMP/sysblock/$NAME"
printf '240:7\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
rm -- "$TMP/sysblock/$NAME/dev" "$TMP/sysblock/nullb7/dev"
rmdir -- "$TMP/sysblock/$NAME" "$TMP/sysblock/nullb7"
refused_disk "$NAME" 7 "$TMP/sysblock"
refused_disk swapz-0123456789abcdef 7 "$TMP/sysblock"
refused_disk /dev/nullb7 7 "$TMP/sysblock"
refused_disk "$NAME" abc "$TMP/sysblock"
mkdir -p "$TMP/sysblock/$NAME"
printf 'garbage\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
printf '240:07\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
printf '240:7\n241:8\n' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
printf '240:7' > "$TMP/sysblock/$NAME/dev"
refused_disk "$NAME" 7 "$TMP/sysblock"
# A malformed record must be rejected without first reading its entire body.
python3 - "$TMP/sysblock/$NAME/dev" <<'PY'
import pathlib
import sys
pathlib.Path(sys.argv[1]).write_text("2" * 1048576 + "\n", encoding="ascii")
PY
before_devno_rchar="$(awk '$1 == "rchar:" { print $2 }' "/proc/$$/io")"
refused_disk "$NAME" 7 "$TMP/sysblock"
after_devno_rchar="$(awk '$1 == "rchar:" { print $2 }' "/proc/$$/io")"
(( after_devno_rchar - before_devno_rchar < 65536 )) ||
    die "oversized dev telemetry was not read with a bounded buffer"
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
import re
import sys

source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
root = pathlib.Path(sys.argv[3])
path_replacements = {
    # Match nested paths first: /dev also prefixes /sys/dev/block and /proc/devices.
    "/proc/devices": str(root / "proc/devices"),
    "/sys/dev/block": str(root / "sys/dev/block"),
    "/var/lib/swapz-package-transactions": str(root / "var/lib/swapz-package-transactions"),
    "/lib/modules/": str(root / "lib/modules/"),
    "/proc": str(root / "proc"),
    "/sys": str(root / "sys"),
    "/boot": str(root / "boot"),
    "/dev": str(root / "dev"),
}
# Replace absolute path roots only once. A root such as `/dev` must not match
# a later path component in `/sys/block/<device>/dev`.
path_pattern = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:"
    + "|".join(
        re.escape(original)
        for original in sorted(path_replacements, key=len, reverse=True)
    )
    + r")"
)
source = path_pattern.sub(
    lambda match: path_replacements[match.group(0)],
    source,
)
rewritten_probe = path_pattern.sub(
    lambda match: path_replacements[match.group(0)],
    '"/sys/block/nullb-swapz-cccccccccccccccc/dev"',
)
if rewritten_probe != f'"{root}/sys/block/nullb-swapz-cccccccccccccccc/dev"':
    raise SystemExit("fixture path rewrite altered a nested sysfs dev component")
source = source.replace(
    '[[ -n $mapper_node && -b $mapper_node ]] ||',
    '[[ -n $mapper_node && -e $mapper_node ]] ||',
)
source = source.replace('[[ -b $source ]]', '[[ -e $source ]]')
source = source.replace('-b $lower', '-e $lower')
# Inspect only this synthetic process's pinned descriptors through procfs.
source = source.replace(str(root / "proc") + '/$$/fd/', '/proc/$$/fd/')
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
cp -- "$ROOT/tests/tools/nullblk-identity.sh" "$TOOLS/nullblk-identity.sh"
cat > "$TOOLS/clear-tmp-before-memory-check.sh" <<'SH'
# Test-only replacement: never touch /tmp or real completion proofs.
swapz_recover_abandoned_ram_resources() { return 0; }
swapz_clear_tmp_before_memory_check() {
    # Marker only; no real completed-session scratch is ever removed.
    printf 'called\n' > "$SWAPZ_FIXTURE_ROOT/completed-cleanup-probe"
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
if [[ "\$1" == "-Lc" && "\$2" == "%u" ]]; then
    case "\$3" in
        /proc/[0-9]*/fd/[0-9]*)
            # The sandbox files belong to the CI account, but this descriptor
            # models a root-owned configfs attribute on the privileged host.
            if [[ \${SWAPZ_FIXTURE_CASE:-} == power_attribute_wrong_owner ]]; then
                printf '1000\n'
            else
                printf '0\n'
            fi
            exit 0
            ;;
    esac
fi
if [[ "\$1" == "-Lc" && "\$2" == "%Hr:%Lr" &&
      "\$3" == "$FIXTURE/dev/mapper/swapz-demo-$TOKEN" ]]; then
    printf '253:0\n'
    exit 0
fi
if [[ "\$1" == "-Lc" && "\$2" == "%Hr:%Lr" &&
      ( "\$3" == "$FIXTURE/dev/nullb-swapz-$LOWER_TOKEN" ||
        "\$3" == "$FIXTURE/dev/dm-0" ) ]]; then
    if [[ "\$3" == "$FIXTURE/dev/dm-0" ]]; then
        printf '253:0\n'
    else
        printf '240:7\n'
    fi
    exit 0
fi
if [[ "\$1" == "-Lc" && "\$2" == "%t:%T" &&
      "\$3" == "$FIXTURE/dev/foreign-swap" ]]; then
    # Fake regular nodes otherwise all report 0:0; give the unrelated swap a
    # distinct synthetic rdev so the alias test models block identity correctly.
    printf '8:1\n'
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
        printf "attempted\n" > "$SWAPZ_FIXTURE_ROOT/attempted-mapper-removal"
        fake_root="$SWAPZ_FIXTURE_ROOT"
        config="$fake_root/sys/kernel/config/nullb/nullb-swapz-cccccccccccccccc"
        rm -- "$fake_root/sys/block/nullb-swapz-cccccccccccccccc/holders/dm-0" || exit 98
        rm -- "$fake_root/dev/mapper/swapz-demo-aaaaaaaaaaaaaaaa" "$fake_root/dev/dm-0" || exit 98
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
    *) printf "unexpected\n" > "$SWAPZ_FIXTURE_ROOT/unexpected-timeout"; exit 98 ;;
esac
SH
cat > "$STUBS/rmdir" <<SH
#!/bin/bash
printf "attempted\\n" > "\$SWAPZ_FIXTURE_ROOT/attempted-config-removal"
[[ "\$1" == -- && "\$2" == "\$SWAPZ_FIXTURE_ROOT/sys/kernel/config/nullb/nullb-swapz-cccccccccccccccc" ]] || exit 98
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
            changed_mapper_token)
                if [[ -e "$SWAPZ_FIXTURE_ROOT/uuid-seen" ]]; then
                    printf 'SWAPZ-TEST-bbbbbbbbbbbbbbbb\n'
                else
                    : > "$SWAPZ_FIXTURE_ROOT/uuid-seen"
                    printf 'SWAPZ-TEST-aaaaaaaaaaaaaaaa\n'
                fi
                ;;
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
        elif [[ $SWAPZ_FIXTURE_CASE == ambiguous_index_owner ||
                 $SWAPZ_FIXTURE_CASE == unknown_index_owner ]]; then
            printf '1 dependencies : (nullb7)\n'
        elif [[ $SWAPZ_FIXTURE_CASE == foreign_dependency ]]; then
            counter_file="$SWAPZ_FIXTURE_ROOT/dependency-count"
            if [[ -e $counter_file ]]; then
                printf '2\n' > "$counter_file"
                printf '1 dependencies : (nullb-swapz-bbbbbbbbbbbbbbbb)\n'
            else
                printf '1\n' > "$counter_file"
                printf '1 dependencies : (nullb-swapz-cccccccccccccccc)\n'
            fi
        else
            printf '1 dependencies : (nullb-swapz-cccccccccccccccc)\n'
        fi
        ;;
    "deps -o devno swapz-demo-aaaaaaaaaaaaaaaa")
        if [[ $SWAPZ_FIXTURE_CASE == dependency_probe_failure ]]; then
            exit 98
        elif [[ $SWAPZ_FIXTURE_CASE == dependency_devno_mismatch ]]; then
            printf '1 dependencies : (240, 8)\n'
        elif [[ $SWAPZ_FIXTURE_CASE == foreign_dependency &&
                -f "$SWAPZ_FIXTURE_ROOT/dependency-count" &&
                "$(cat "$SWAPZ_FIXTURE_ROOT/dependency-count")" == 2 ]]; then
            printf '1 dependencies : (240, 8)\n'
        else
            printf '1 dependencies : (240, 7)\n'
        fi
        ;;
    "info -c --noheadings -o open swapz-demo-aaaaaaaaaaaaaaaa")
        if [[ $SWAPZ_FIXTURE_CASE == replaced_inode &&
              ! -e "$SWAPZ_FIXTURE_ROOT/retained-original-config" ]]; then
            # Replace the public pathname after acquisition but before the
            # pre-removal inode recheck. Pinned descriptors keep the original.
            fake_root="$SWAPZ_FIXTURE_ROOT"
            config="$fake_root/sys/kernel/config/nullb/nullb-swapz-cccccccccccccccc"
            mv -- "$config" "$fake_root/retained-original-config" || exit 98
            mkdir -- "$config" || exit 98
            for attribute in index memory_backed size blocksize queue_mode power; do
                cp -- "$fake_root/retained-original-config/$attribute" "$config/$attribute" || exit 98
            done
        fi
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
for fake_command in "$STUBS"/*; do
    [[ -f $fake_command && ! -L $fake_command ]] || continue
    bash -n "$fake_command" || die "generated fake command has invalid shell syntax"
done

reset_fake() {
    # Delete only this test's known fake roots; never real /proc, /sys or /dev.
    rm -rf -- "$FIXTURE/proc" "$FIXTURE/sys" "$FIXTURE/dev" \
        "$FIXTURE/boot" "$FIXTURE/lib" "$FIXTURE/var" \
        "$FIXTURE/retained-original-config" "$FIXTURE/dependency-count" \
        "$FIXTURE/unexpected-rmmod" "$FIXTURE/unexpected-timeout" \
        "$FIXTURE/attempted-mapper-removal" "$FIXTURE/attempted-config-removal" \
        "$FIXTURE/completed-cleanup-probe" "$FIXTURE/old-owner-record" "$FIXTURE/uuid-seen"
    mkdir -p "$FIXTURE/proc/self" "$FIXTURE/sys/kernel/config" \
        "$FIXTURE/sys/module" "$FIXTURE/dev/mapper"
    # Keep rewritten stderr suppression inside the private fixture filesystem.
    : > "$FIXTURE/dev/null"
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
    mkdir -p "$FIXTURE/sys/block/dm-0"
    : > "$FIXTURE/dev/dm-0"
    ln -s "../dm-0" "$FIXTURE/dev/mapper/swapz-demo-$TOKEN"
}
setup_owned_lower() {
    local config="$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN"
    local disk="$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN"
    mkdir -p "$config" "$disk/holders" "$FIXTURE/sys/dev/block"
    printf '1\n' > "$config/memory_backed"
    printf '1\n' > "$config/power"
    printf '7\n' > "$config/index"
    printf '64\n' > "$config/size"
    printf '4096\n' > "$config/blocksize"
    printf '2\n' > "$config/queue_mode"
    printf '240:7\n' > "$disk/dev"
    ln -s "$disk" "$FIXTURE/sys/dev/block/240:7"
    : > "$FIXTURE/dev/nullb-swapz-$LOWER_TOKEN"
    ln -s "$FIXTURE/sys/block/dm-0" "$disk/holders/dm-0"
}
assert_private_safe_refusal() {
    local case_name="$1" output="$2" safe_next_action
    [[ "$output" != *"$FIXTURE/"* &&
       "$output" != *"$TOKEN"* &&
       "$output" != *"$OTHER_TOKEN"* &&
       "$output" != *"$LOWER_TOKEN"* &&
       "$output" != *"nullb-swapz-"* &&
       "$output" != *"swapz-demo-"* &&
       "$output" != *"SWAPZ-TEST-"* &&
       "$output" != *"240:7"* &&
       "$output" != *"240:8"* &&
       "$output" != *"253:0"* &&
       "$output" != *"253:1"* &&
       "$output" != *"254:9"* &&
       "$output" != *"dm-0"* &&
       "$output" != *"dm-9"* &&
       "$output" != *"nullb7"* &&
       "$output" != *"rmmod"* &&
       "$output" != *"unload"* &&
       "$output" != *"delete"* &&
       "$output" != *"power off"* &&
       "$output" != *"power-off"* &&
       "$output" != *"power_off"* &&
       "$output" != *"claim="* ]] ||
        die "$case_name disclosed a private identity or recommended unsafe cleanup"
    [[ "$output" =~ safe_next_action=([A-Za-z0-9_-]+) ]] ||
        die "$case_name omitted its bounded safe next action"
    safe_next_action="${BASH_REMATCH[1]}"
    case "$safe_next_action" in
        inspect_read_only|original_creator_revalidate_then_cleanup_or_read_only_reconcile)
            ;;
        *) die "$case_name recommended an unapproved follow-up action" ;;
    esac
}
run_case() {
    local case_name="$1" expected="$2" expected_result="$3" expected_errno="$4"
    local result=0 output unclaimed_config unclaimed_disk
    current_nullblk_case=$case_name
    reset_fake
    case "$case_name" in
        missing_capability) printf 'CapEff:\t0000000000000000\n' > "$FIXTURE/proc/self/status" ;;
        capability_unreadable)
            rm -- "$FIXTURE/proc/self/status"
            mkdir "$FIXTURE/proc/self/status"
            ;;
        missing_module|missing_tool|missing_unused_rmmod|cleanup_permission|retained_journal|journal_permission|invalid_debug|low_memory|unrelated_swap|foreign_nullb|unclaimed_nullb|unclaimed_nullb_pair|unclaimed_full_proof|unclaimed_pair_foreign|stale_owner_record|internal_failure) ;;
        idle_module_busy)
            mkdir -p "$FIXTURE/sys/module/dm_swapz"
            printf '0\n' > "$FIXTURE/sys/module/dm_swapz/refcnt"
            ;;
        busy_mapper|mapper_inventory_error|noncanonical_mapper_major|malformed_mapper_fields|mapper_inventory_identity_mismatch|power_attribute_wrong_owner|stale_token|changed_mapper_token|primary_namespace|wrong_owner|owned_swap|owned_swap_alias|foreign_active_swap|unresolved_swap_alias|unreadable_identity|mounted_mapper|mount_inventory_empty|mount_inventory_error|swap_inventory_error|malformed_swap_inventory|recognized_readfault|recognized_codec|recognized_completion|recognized_constructor|owned_cleanup|replaced_inode|missing_sysfs_proof|mismatched_major|mismatched_devno|mismatched_index|dependency_devno_mismatch|dependency_probe_failure|partitioned_lower|foreign_holder|foreign_dependency|cleanup_failure|ambiguous_index_owner|unknown_index_owner|partial_config_proof|malformed_config_index|reused_index_alias|empty_index_alias|malformed_sysfs_dev|dangling_index_dev|malformed_proc_nullb_major|duplicate_proc_block_header|extra_foreign_holder|changed_holder_target)
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
        noncanonical_mapper_major|malformed_mapper_fields|mapper_inventory_identity_mismatch|power_attribute_wrong_owner|recognized_readfault|recognized_codec|recognized_completion|recognized_constructor|owned_cleanup|replaced_inode|changed_mapper_token|foreign_active_swap|missing_sysfs_proof|mismatched_major|mismatched_devno|mismatched_index|dependency_devno_mismatch|dependency_probe_failure|partitioned_lower|foreign_holder|foreign_dependency|cleanup_failure|ambiguous_index_owner|unknown_index_owner|partial_config_proof|malformed_config_index|reused_index_alias|empty_index_alias|malformed_sysfs_dev|dangling_index_dev|malformed_proc_nullb_major|duplicate_proc_block_header|extra_foreign_holder|changed_holder_target)
            setup_owned_lower
            setup_mapper_node
            if [[ $case_name == missing_sysfs_proof ]]; then
                rm -- "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/dev"
            elif [[ $case_name == mismatched_major ]]; then
                printf 'Character devices:\n\nBlock devices:\n241 nullb\n' > "$FIXTURE/proc/devices"
            elif [[ $case_name == mismatched_devno ]]; then
                printf '240:8\n' > "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/dev"
            elif [[ $case_name == mismatched_index ]]; then
                printf '8\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN/index"
            elif [[ $case_name == partial_config_proof ]]; then
                rm -- "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN/size"
            elif [[ $case_name == malformed_config_index ]]; then
                # Command substitution used to erase this extra blank record.
                printf '7\n\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN/index"
            elif [[ $case_name == ambiguous_index_owner ]]; then
                mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN"
                printf '7\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/index"
                printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed"
                printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/power"
            elif [[ $case_name == unknown_index_owner ]]; then
                # Missing canonical index means this candidate is not proven different.
                mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN"
                printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed"
                printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/power"
            elif [[ $case_name == reused_index_alias ]]; then
                mkdir -p "$FIXTURE/sys/block/nullb7"
                printf '240:7\n' > "$FIXTURE/sys/block/nullb7/dev"
            elif [[ $case_name == empty_index_alias ]]; then
                # A torn/reused alternate disk entry is ambiguity even without dev.
                mkdir -p "$FIXTURE/sys/block/nullb7"
            elif [[ $case_name == malformed_sysfs_dev ]]; then
                # Command substitution used to erase this extra blank record.
                printf '240:7\n\n' > "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/dev"
            elif [[ $case_name == dangling_index_dev ]]; then
                mkdir -p "$FIXTURE/sys/block/nullb7"
                ln -s "$FIXTURE/missing-dev" "$FIXTURE/sys/block/nullb7/dev"
            elif [[ $case_name == malformed_proc_nullb_major ]]; then
                printf 'Character devices:\n\nBlock devices:\n240 nullb extra\n' > "$FIXTURE/proc/devices"
            elif [[ $case_name == duplicate_proc_block_header ]]; then
                printf 'Character devices:\n\nBlock devices:\n240 nullb\nBlock devices:\n' > "$FIXTURE/proc/devices"
            elif [[ $case_name == partitioned_lower ]]; then
                mkdir -p "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/nullb-swapz-${LOWER_TOKEN}1"
                printf '1\n' > "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/nullb-swapz-${LOWER_TOKEN}1/partition"
            elif [[ $case_name == foreign_holder ]]; then
                rm -- "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-0"
                mkdir -p "$FIXTURE/sys/block/dm-9"
                ln -s "$FIXTURE/sys/block/dm-9" \
                    "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-9"
            elif [[ $case_name == foreign_active_swap ]]; then
                : > "$FIXTURE/dev/foreign-swap"
                printf '%s partition 1024 0 -4\n' "$FIXTURE/dev/foreign-swap" >> "$FIXTURE/proc/swaps"
            elif [[ $case_name == extra_foreign_holder ||
                    $case_name == changed_holder_target ]]; then
                mkdir -p "$FIXTURE/sys/block/dm-9"
                if [[ $case_name == changed_holder_target ]]; then
                    rm -- "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-0"
                    ln -s "$FIXTURE/sys/block/dm-9" \
                        "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-0"
                else
                    ln -s "$FIXTURE/sys/block/dm-9" \
                        "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-9"
                fi
            fi
            ;;
        foreign_nullb)
            # An unrelated index-named device is not evidence of this run's ownership.
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/foreign-device" \
                "$FIXTURE/sys/block/nullb7"
            printf '240:7\n' > "$FIXTURE/sys/block/nullb7/dev"
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-${OTHER_TOKEN}-foreign"
            ;;
        unclaimed_nullb)
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN"
            ;;
        unclaimed_full_proof)
            # Complete-looking attributes and sysfs identity are not provenance.
            setup_owned_lower
            ;;
        stale_owner_record)
            setup_owned_lower
            printf 'token=%s\n' "$LOWER_TOKEN" > "$FIXTURE/old-owner-record"
            ;;
        unclaimed_nullb_pair|unclaimed_pair_foreign)
            # Two plausible names still provide zero independent creation proof.
            mkdir -p "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN" \
                "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN"
            printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/memory_backed"
            printf '1\n' > "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed"
            if [[ $case_name == unclaimed_pair_foreign ]]; then
                mkdir -p "$FIXTURE/sys/kernel/config/nullb/foreign-device" \
                    "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-${OTHER_TOKEN}-foreign" \
                    "$FIXTURE/sys/block/nullb7"
                printf '240:7\n' > "$FIXTURE/sys/block/nullb7/dev"
            fi
            ;;
    esac
    case "$case_name" in
        missing_tool)
            mv -- "$STUBS/dmsetup" "$STUBS/dmsetup.hidden"
            ;;
        missing_unused_rmmod)
            mv -- "$STUBS/rmmod" "$STUBS/rmmod.hidden"
            ;;
    esac
    if SWAPZ_FIXTURE_CASE="$case_name" SWAPZ_FIXTURE_ROOT="$FIXTURE" \
        SWAPZ_NULLBLK_CREATION_AUTHORITY="$TOKEN" PATH="$STUBS" "$STUBS/bash" "$TOOLS/loaded-preflight.sh" \
        > "$FIXTURE/output.log" 2>&1; then
        result=0
    else
        result=$?
    fi
    case "$case_name" in
        missing_tool)
            mv -- "$STUBS/dmsetup.hidden" "$STUBS/dmsetup"
            ;;
        missing_unused_rmmod)
            mv -- "$STUBS/rmmod.hidden" "$STUBS/rmmod"
            ;;
    esac
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
    if [[ "$expected_result" == BLOCKED || "$expected_result" == NOT_AUTHORIZED ]]; then
        [[ "$output" == *"expected_proof="* &&
           "$output" == *"observed_proof="* &&
           "$output" == *"original_errno_or_exit="* &&
           "$output" == *"retained_state_action="* &&
           "$output" == *"safe_next_action="* ]] ||
            die "$case_name omitted structured refusal proof or safe action: $output"
    fi
    if [[ "$case_name" == noncanonical_mapper_major ||
          "$case_name" == malformed_mapper_fields ]]; then
        [[ "$output" == *'pipeline_status=2; '* &&
           "$output" == *'original_errno_or_exit=2'* &&
           "$output" == *'observed invalid or unreadable listing;'* ]] ||
            die "$case_name did not refuse malformed mapper identity before cleanup: $output"
    elif [[ "$case_name" == mapper_inventory_identity_mismatch ]]; then
        [[ "$output" == *'expected dmsetup inventory device identity to match canonical mapper node; observed mismatch; no holder signal; inspect device-mapper inventory and udev state without cleanup'* &&
           "$output" != *"$FIXTURE/dev/"* ]] ||
            die "$case_name did not refuse the stale mapper identity safely: $output"
    elif [[ "$case_name" == power_attribute_wrong_owner ]]; then
        [[ "$output" == *'phase=acquire resource_kind=null_blk expected_proof=pinned_power_attribute observed_proof=invalid_type_or_owner'* ]] ||
            die "$case_name accepted a non-root pinned power attribute: $output"
    fi
    # Exact proof classes, not just exit codes; no host/fixture IDs in a refusal.
    case "$case_name" in
        unclaimed_nullb|unclaimed_nullb_pair|unclaimed_full_proof|unclaimed_pair_foreign|stale_owner_record)
            [[ "$output" == *"LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed"* &&
               "$output" != *"$FIXTURE/"* &&
               "$output" != *"nullb-swapz-"* &&
               "$output" != *"$TOKEN"* &&
               "$output" != *"$OTHER_TOKEN"* &&
               "$output" != *"$LOWER_TOKEN"* ]] ||
                die "$case_name did not report retained unclaimed resources safely"
            ;;
        ambiguous_index_owner)
            [[ "$output" == *"check=null_blk_owner errno=unavailable remedy=phase=dependency_owner resource_kind=null_blk expected_proof=unique_canonical_configfs_index_owner observed_proof=multiple_matching_owners original_errno_or_exit=unavailable retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"* ]] ||
                die "$case_name did not reject multiple matching index owners"
            ;;
        unknown_index_owner)
            [[ "$output" == *"check=null_blk_owner errno=unavailable remedy=phase=dependency_owner resource_kind=null_blk expected_proof=unique_canonical_configfs_index_owner observed_proof=ambiguous_or_unreadable original_errno_or_exit=1 retained_state_action=retain_unproven_resources safe_next_action=inspect_read_only"* ]] ||
                die "$case_name skipped a token-shaped owner with unknown index"
            ;;
        partial_config_proof)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=config_inode_index_attributes observed_proof=missing_or_incomplete original_errno_or_exit=unavailable retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not identify incomplete configfs proof"
            ;;
        malformed_config_index)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=canonical_configfs_index observed_proof=malformed_or_unreadable original_errno_or_exit=1 retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not preserve malformed configfs index attribution"
            ;;
        mismatched_major)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=dependency_sysfs_major_index_devno_node_rdev observed_proof=missing_or_incomplete original_errno_or_exit=unavailable retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name accepted a null_blk major mismatch"
            ;;
        foreign_active_swap)
            [[ "$output" == *"phase=mapper_remove resource_kind=null_blk expected_proof=creation_authority observed_proof=live_identity_only"* ]] ||
                die "$case_name let an unrelated active swap change ownership admission"
            ;;
        reused_index_alias|empty_index_alias|malformed_sysfs_dev|dangling_index_dev)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=unique_sysfs_disk_alias_and_canonical_devno observed_proof=ambiguous_or_malformed original_errno_or_exit=1 retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not identify the first ambiguous sysfs disk proof"
            ;;
        malformed_proc_nullb_major|duplicate_proc_block_header)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=one_canonical_nullb_major_record observed_proof=malformed_or_unreadable original_errno_or_exit=2 retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not preserve the malformed /proc parser status"
            ;;
        extra_foreign_holder)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=exact_single_mapper_holder observed_proof=missing_or_foreign original_errno_or_exit=unavailable retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not identify concurrent foreign holder"
            ;;
        changed_holder_target)
            [[ "$output" == *"phase=acquire resource_kind=null_blk expected_proof=exact_mapper_holder_target observed_proof=substituted original_errno_or_exit=unavailable retained_state_action=retain_unproven_resources"* ]] ||
                die "$case_name did not identify substituted holder link"
            ;;
    esac
    case "$case_name" in
        ambiguous_index_owner|unknown_index_owner|partial_config_proof|malformed_config_index|mismatched_major|foreign_active_swap|reused_index_alias|empty_index_alias|malformed_sysfs_dev|dangling_index_dev|malformed_proc_nullb_major|duplicate_proc_block_header|extra_foreign_holder|changed_holder_target)
            assert_private_safe_refusal "$case_name" "$output"
            ;;
    esac
    [[ -f "$FIXTURE/proc/swaps" ]] || die "host swap inventory was mutated"
    # Admission must run before even the verified completed-scratch helper.
    # Only clean preflight passes and the helper's own injected failure reach it.
    if [[ "$expected_result" == PASS || "$case_name" == cleanup_permission ]]; then
        [[ -f "$FIXTURE/completed-cleanup-probe" ]] ||
            die "$case_name skipped its completed-scratch helper"
    else
        [[ ! -e "$FIXTURE/completed-cleanup-probe" ]] ||
            die "$case_name ran completed-scratch cleanup after a BLOCKED admission"
    fi
    [[ ! -e "$FIXTURE/unexpected-rmmod" &&
       ! -e "$FIXTURE/unexpected-timeout" ]] ||
        die "$case_name attempted unexpected host cleanup"
    # No old preflight process can inherit exclusive creation authority.
    # Even matching UUID, inode, holder and geometry proofs permit no cleanup.
    [[ ! -e "$FIXTURE/attempted-mapper-removal" &&
       ! -e "$FIXTURE/attempted-config-removal" ]] ||
        die "$case_name attempted unclaimed mapper or configfs removal"
    # Every synthetic power attribute must remain on after a refusal.
    for retained_config in "$FIXTURE"/sys/kernel/config/nullb/nullb-swapz-*; do
        [[ -d $retained_config && -f $retained_config/power ]] || continue
        [[ "$(cat "$retained_config/power")" == 1 ]] ||
            die "$case_name powered off unproved configfs state"
    done
    if [[ "$case_name" == foreign_nullb ]]; then
        [[ -d "$FIXTURE/sys/kernel/config/nullb/foreign-device" &&
           -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-${OTHER_TOKEN}-foreign" &&
           -f "$FIXTURE/sys/block/nullb7/dev" &&
           "$(cat "$FIXTURE/sys/block/nullb7/dev")" == "240:7" ]] ||
            die "unrelated null_blk device was claimed or changed"
    elif [[ "$case_name" == unclaimed_nullb_pair ||
            "$case_name" == unclaimed_pair_foreign ]]; then
        [[ -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN" &&
           -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN" &&
           "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$TOKEN/memory_backed")" == 1 &&
           "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$OTHER_TOKEN/memory_backed")" == 1 &&
           "$output" == *"LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed count=2"* &&
           "$output" != *"$FIXTURE/"* &&
           "$output" != *"nullb-swapz-"* ]] ||
            die "ambiguous null_blk devices were changed, claimed or disclosed"
        if [[ "$case_name" == unclaimed_pair_foreign ]]; then
            [[ -d "$FIXTURE/sys/kernel/config/nullb/foreign-device" &&
               -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-${OTHER_TOKEN}-foreign" &&
               "$(cat "$FIXTURE/sys/block/nullb7/dev")" == "240:7" ]] ||
                die "simultaneous foreign null_blk objects were changed"
        fi
    fi
    if [[ "$case_name" == unclaimed_full_proof || "$case_name" == stale_owner_record ]]; then
        unclaimed_config="$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN"
        unclaimed_disk="$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN"
        [[ "$(cat "$unclaimed_config/index")" == 7 &&
           "$(cat "$unclaimed_config/memory_backed")" == 1 &&
           "$(cat "$unclaimed_config/power")" == 1 &&
           "$(cat "$unclaimed_config/size")" == 64 &&
           "$(cat "$unclaimed_config/blocksize")" == 4096 &&
           "$(cat "$unclaimed_config/queue_mode")" == 2 &&
           "$(cat "$unclaimed_disk/dev")" == "240:7" &&
           -L "$FIXTURE/sys/dev/block/240:7" &&
           "$(readlink -f "$FIXTURE/sys/dev/block/240:7")" == "$unclaimed_disk" &&
           -e "$FIXTURE/dev/nullb-swapz-$LOWER_TOKEN" &&
           -L "$unclaimed_disk/holders/dm-0" ]] ||
            die "complete-looking unclaimed null_blk inventory changed"
    fi
    if [[ "$case_name" == stale_owner_record ]]; then
        [[ "$(cat "$FIXTURE/old-owner-record")" == "token=$LOWER_TOKEN" ]] ||
            die "untrusted ownership record was consumed or changed"
    fi
    if [[ "$case_name" == owned_cleanup || "$case_name" == cleanup_failure ]]; then
        [[ -d "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN" &&
           "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN/power")" == 1 &&
           -L "$FIXTURE/sys/block/nullb-swapz-$LOWER_TOKEN/holders/dm-0" &&
           -L "$FIXTURE/dev/mapper/swapz-demo-$TOKEN" &&
           ! -e "$FIXTURE/retained-original-config" &&
           "$output" == *"phase=mapper_remove resource_kind=null_blk expected_proof=creation_authority observed_proof=live_identity_only"* &&
           "$output" == *"retained_state_action=retain_unclaimed_null_blk safe_next_action=original_creator_revalidate_then_cleanup_or_read_only_reconcile"* ]] ||
            die "$case_name incorrectly admitted stale ownership or mutated the fixture"
    elif [[ "$case_name" == replaced_inode ]]; then
        [[ -d "$FIXTURE/retained-original-config" &&
           "$(cat "$FIXTURE/retained-original-config/power")" == 1 &&
           "$(cat "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN/power")" == 1 &&
           "$(stat -Lc '%d:%i' "$FIXTURE/retained-original-config")" != \
               "$(stat -Lc '%d:%i' "$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN")" &&
           "$output" == *"phase=mapper_remove resource_kind=null_blk expected_proof=original_inode_index_attributes observed_proof=substituted"* ]] ||
            die "same-name replacement was not detected before any cleanup"
    elif [[ "$case_name" == dependency_probe_failure ]]; then
        [[ "$output" == *"original_errno_or_exit=98"* &&
           "$output" == *"expected_proof=readable_dependency_devno observed_proof=probe_failed"* ]] ||
            die "dependency probe masked the original failure status"
    fi
    case "$case_name" in
        cleanup_permission)
            [[ "$output" == *"original_errno_or_exit=1"* ]] ||
                die "$case_name lost original cleanup-helper status 1"
            ;;
        journal_permission|mapper_inventory_error|mount_inventory_error|swap_inventory_error)
            [[ "$output" == *"original_errno_or_exit=98"* ]] ||
                die "$case_name lost original command status 98"
            ;;
        noncanonical_mapper_major|malformed_mapper_fields|malformed_swap_inventory)
            [[ "$output" == *"original_errno_or_exit=2"* ]] ||
                die "$case_name lost original parse status 2"
            ;;
        unreadable_identity)
            [[ "$output" == *"original_errno_or_exit=13"* ]] ||
                die "$case_name lost original stat status 13"
            ;;
    esac
    if [[ "$case_name" == owned_cleanup || "$case_name" == replaced_inode ||
          "$case_name" == cleanup_failure || "$case_name" == foreign_active_swap ||
          "$case_name" == missing_sysfs_proof || "$case_name" == mismatched_major ||
          "$case_name" == mismatched_devno || "$case_name" == mismatched_index ||
          "$case_name" == dependency_devno_mismatch ||
          "$case_name" == partitioned_lower || "$case_name" == foreign_holder ||
          "$case_name" == foreign_dependency ||
          "$case_name" == changed_mapper_token ||
          "$case_name" == partial_config_proof ||
          "$case_name" == malformed_config_index ||
          "$case_name" == reused_index_alias ||
          "$case_name" == empty_index_alias ||
          "$case_name" == malformed_sysfs_dev ||
          "$case_name" == dangling_index_dev ||
          "$case_name" == malformed_proc_nullb_major ||
          "$case_name" == duplicate_proc_block_header ||
          "$case_name" == unknown_index_owner ||
          "$case_name" == extra_foreign_holder ||
          "$case_name" == changed_holder_target ]]; then
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
    elif [[ "$case_name" == foreign_active_swap ]]; then
        grep -Fxq "$FIXTURE/dev/foreign-swap partition 1024 0 -4" "$FIXTURE/proc/swaps" ||
            die "foreign active swap inventory changed"
    fi
}

# Demonstrate the first old path-only false admission entirely in this private
# directory. The old ownership check admitted the replacement because its
# pathname, memory_backed and power values matched after the inode changed.
reset_fake
setup_owned_lower
legacy_config="$FIXTURE/sys/kernel/config/nullb/nullb-swapz-$LOWER_TOKEN"
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
run_case missing_unused_rmmod LOADED_PREFLIGHT_DM_SWAPZ=absent PASS unavailable
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
run_case power_attribute_wrong_owner owned_resource_proof BLOCKED unavailable
run_case stale_token stale_run_token BLOCKED unavailable
run_case changed_mapper_token owned_resource_proof BLOCKED unavailable
run_case wrong_owner null_blk_owner BLOCKED unavailable
run_case owned_swap active_owned_swap BLOCKED unavailable
run_case owned_swap_alias active_owned_swap BLOCKED unavailable
run_case foreign_active_swap owned_resource_proof BLOCKED unavailable
run_case unresolved_swap_alias swap_inventory BLOCKED unavailable
run_case mounted_mapper mounted_owned_mapper BLOCKED unavailable
run_case mount_inventory_empty mount_inventory BLOCKED unavailable
run_case mount_inventory_error mount_inventory BLOCKED unavailable
run_case swap_inventory_error swap_inventory BLOCKED unavailable
run_case malformed_swap_inventory swap_inventory BLOCKED unavailable
run_case unreadable_identity swap_device_identity BLOCKED unavailable
run_case recognized_readfault owned_resource_proof BLOCKED unavailable
run_case recognized_codec owned_resource_proof BLOCKED unavailable
run_case recognized_completion owned_resource_proof BLOCKED unavailable
run_case recognized_constructor owned_resource_proof BLOCKED unavailable
run_case primary_namespace stale_run_token BLOCKED unavailable
run_case missing_sysfs_proof owned_resource_proof BLOCKED unavailable
run_case mismatched_major owned_resource_proof BLOCKED unavailable
run_case mismatched_devno owned_resource_proof BLOCKED unavailable
run_case mismatched_index owned_resource_proof BLOCKED unavailable
run_case dependency_devno_mismatch owned_resource_proof BLOCKED unavailable
run_case dependency_probe_failure mapper_dependency BLOCKED unavailable
run_case partitioned_lower owned_resource_proof BLOCKED unavailable
run_case foreign_holder owned_resource_proof BLOCKED unavailable
run_case extra_foreign_holder owned_resource_proof BLOCKED unavailable
run_case changed_holder_target owned_resource_proof BLOCKED unavailable
run_case partial_config_proof owned_resource_proof BLOCKED unavailable
run_case malformed_config_index owned_resource_proof BLOCKED unavailable
run_case reused_index_alias owned_resource_proof BLOCKED unavailable
run_case empty_index_alias owned_resource_proof BLOCKED unavailable
run_case malformed_sysfs_dev owned_resource_proof BLOCKED unavailable
run_case dangling_index_dev owned_resource_proof BLOCKED unavailable
run_case malformed_proc_nullb_major owned_resource_proof BLOCKED unavailable
run_case duplicate_proc_block_header owned_resource_proof BLOCKED unavailable
run_case ambiguous_index_owner null_blk_owner BLOCKED unavailable
run_case unknown_index_owner null_blk_owner BLOCKED unavailable
run_case foreign_dependency owned_resource_proof BLOCKED unavailable
run_case replaced_inode owned_resource_proof BLOCKED unavailable
run_case cleanup_failure owned_resource_proof BLOCKED unavailable
run_case owned_cleanup owned_resource_proof BLOCKED unavailable
run_case unclaimed_nullb LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed\ count=1 PASS unavailable
run_case unclaimed_nullb_pair LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed\ count=2 PASS unavailable
run_case unclaimed_full_proof LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed\ count=1 PASS unavailable
run_case stale_owner_record LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed\ count=1 PASS unavailable
run_case unclaimed_pair_foreign LOADED_PREFLIGHT_NULL_BLK=retained_unclaimed\ count=2 PASS unavailable
run_case foreign_nullb LOADED_PREFLIGHT_DM_SWAPZ=absent PASS unavailable
run_case internal_failure internal_failure FAIL unavailable
# Early MemAvailable is observational only; later ID36 owns admission.
run_case low_memory OBSERVED_ID36_EARLY_HOST_MEMORY PASS unavailable
run_case unrelated_swap LOADED_PREFLIGHT_DM_SWAPZ=absent PASS unavailable

current_nullblk_case=native_creator_source_proof
# Exercise the unmodified native creator's configfs proof against private,
# regular-file fixtures. A private Python launcher changes attribute inode
# observations at each fstat, as configfs may do across attribute lookups;
# the owning directory retains its real, stable identity. This is not a
# synthetic claim that two ordinary files have the same inode.
python3 - "$ROOT/tests/tools/qualify-primary-lifecycle-nullblk.sh" "$TMP" <<'PY'
import os
import pathlib
import re
import shlex
import subprocess
import sys

native_source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
fixture_root = pathlib.Path(sys.argv[2]) / "creator-configfs-proof"
fixture_root.mkdir()
source_match = re.search(
    r"(?ms)^owned_nullblk_configfs_proof\(\) \{\n.*?^\}\n",
    native_source,
)
if source_match is None:
    print("FAIL: phase=source_extract expected_proof=native_creator_proof "
          "observed_proof=missing original_errno=unavailable "
          "original_exit=unavailable ownership=retained", file=sys.stderr)
    sys.exit(1)

extracted_shell = fixture_root / "native-proof.sh"
extracted_shell.write_text(source_match.group(0), encoding="utf-8")
shim_directory = fixture_root / "shim"
shim_directory.mkdir()
(shim_directory / "volatile_inode_shim.py").write_text(r'''
import os
import stat
import sys

_original_open = os.open
_original_fstat = os.fstat
_original_close = os.close
_original_write = os.write
_attribute_descriptors = {}
_lookup_number = 0
_replacement_triggered = False
_attribute_names = frozenset((
    "index", "memory_backed", "size", "blocksize", "power"
))


class VolatileAttributeMetadata:
    def __init__(self, metadata, inode):
        self.metadata = metadata
        self.st_ino = inode

    def __getattr__(self, name):
        return getattr(self.metadata, name)


def attribute_name(path, dir_fd):
    path_text = os.fsdecode(path)
    if dir_fd is not None and path_text in _attribute_names:
        return path_text
    configfs_path, config_name = sys.argv[1:3]
    for attribute in _attribute_names:
        if os.path.normpath(path_text) == os.path.join(
                configfs_path, config_name, attribute):
            return attribute
    return None


def install_matching_replacement(retained_name):
    global _replacement_triggered
    configfs_path, config_name = sys.argv[1:3]
    case_root = os.path.dirname(configfs_path)
    public_config = os.path.join(configfs_path, config_name)
    retained_config = os.path.join(case_root, retained_name)
    os.rename(public_config, retained_config)
    os.mkdir(public_config)
    for attribute in _attribute_names:
        with open(os.path.join(retained_config, attribute), "rb") as source:
            value = source.read()
        with open(os.path.join(public_config, attribute), "wb") as destination:
            destination.write(value)
    _replacement_triggered = True
    return case_root, public_config, retained_config


def power_write_open(path, flags):
    if not flags & (os.O_WRONLY | os.O_RDWR):
        return False
    path_text = os.fsdecode(path)
    if path_text == "power":
        return True
    configfs_path, config_name = sys.argv[1:3]
    return os.path.normpath(path_text) == os.path.join(
        configfs_path, config_name, "power")


def tracked_open(path, flags, mode=0o777, *, dir_fd=None):
    aba_paths = None
    if (not _replacement_triggered and
            os.environ.get("SWAPZ_ABA_DURING_POWER_OPEN") == "1" and
            power_write_open(path, flags)):
        # Put matching foreign state at the public name only while open(2)
        # resolves power. A pinned config-directory fd must still select the
        # creator-owned attribute; public-path lookup would select the foreign
        # object even though the original name is restored before revalidation.
        aba_paths = install_matching_replacement(
            "retained-original-during-power-open")
    try:
        descriptor = _original_open(path, flags, mode, dir_fd=dir_fd)
    finally:
        if aba_paths is not None:
            case_root, public_config, retained_config = aba_paths
            foreign_config = os.path.join(
                case_root, "retained-foreign-during-power-open")
            os.rename(public_config, foreign_config)
            os.rename(retained_config, public_config)
    attribute = attribute_name(path, dir_fd)
    if attribute is not None:
        _attribute_descriptors[descriptor] = attribute
    return descriptor


def replace_config_after_pin(metadata):
    if (_replacement_triggered or
            os.environ.get("SWAPZ_REPLACE_AFTER_CONFIG_PIN") != "1" or
            not stat.S_ISDIR(metadata.st_mode)):
        return
    install_matching_replacement("retained-pinned-directory")


def volatile_fstat(descriptor):
    global _lookup_number
    metadata = _original_fstat(descriptor)
    replace_config_after_pin(metadata)
    attribute = _attribute_descriptors.get(descriptor)
    if attribute is None or not stat.S_ISREG(metadata.st_mode):
        return metadata
    _lookup_number += 1
    synthetic_inode = metadata.st_ino + _lookup_number * 1000003
    with open(os.environ["SWAPZ_INODE_TRACE"], "a", encoding="ascii") as trace:
        trace.write(f"{attribute}:{synthetic_inode}\n")
    return VolatileAttributeMetadata(metadata, synthetic_inode)


def tracked_write(descriptor, data):
    if _attribute_descriptors.get(descriptor) == "power":
        with open(os.environ["SWAPZ_POWER_TRACE"], "a", encoding="ascii") as trace:
            trace.write("power_write\n")
    return _original_write(descriptor, data)


def tracked_close(descriptor):
    _original_close(descriptor)
    _attribute_descriptors.pop(descriptor, None)


os.open = tracked_open
os.fstat = volatile_fstat
os.write = tracked_write
os.close = tracked_close
''', encoding="ascii")

# Explicitly launch the unchanged native Python here-document with the
# fixture shim. Host Python startup hooks can shadow PYTHONPATH sitecustomize.
python_loader = (
    "import os, runpy, sys; "
    "runpy.run_path(os.environ['SWAPZ_SHIM_PATH']); "
    "exec(compile(sys.stdin.read(), '<pinned-nullblk-source>', 'exec'), "
    "{'__name__': '__main__'})"
)
python_wrapper = shim_directory / "python3"
python_wrapper.write_text(
    "#!/usr/bin/env bash\n"
    '[[ "$1" == - ]] || exit 98\n'
    "shift\n"
    f'exec {shlex.quote(sys.executable)} -c '
    f'{shlex.quote(python_loader)} "$@"\n',
    encoding="ascii",
)
python_wrapper.chmod(0o700)

config_name = "nullb-swapz-0123456789abcdef"
attribute_values = {
    "index": "7\n",
    "memory_backed": "1\n",
    "size": "256\n",
    "blocksize": "4096\n",
    "power": "1\n",
}


class AuditFailure(Exception):
    def __init__(self, phase, observed, original_exit="unavailable"):
        super().__init__(phase)
        self.phase = phase
        self.observed = observed
        self.original_exit = original_exit


def require(condition, phase, observed, original_exit="unavailable"):
    if not condition:
        raise AuditFailure(phase, observed, original_exit)


def create_config(case):
    case_root = fixture_root / case
    configfs = case_root / "configfs"
    configfs.mkdir(parents=True)
    config = configfs / config_name
    config.mkdir()
    for name, value in attribute_values.items():
        (config / name).write_text(value, encoding="ascii")
    metadata = config.stat()
    identity = f"{metadata.st_dev}:{metadata.st_ino}:{metadata.st_uid}"
    return case_root, configfs, config, identity


def run_proof(
        case_root, configfs, identity, power_off, replace_after_pin=False,
        aba_during_power_open=False):
    inode_trace = case_root / "attribute-inodes"
    power_trace = case_root / "power-writes"
    environment = os.environ.copy()
    environment["PATH"] = str(shim_directory) + os.pathsep + os.environ["PATH"]
    environment["SWAPZ_SHIM_PATH"] = str(shim_directory / "volatile_inode_shim.py")
    environment["SWAPZ_INODE_TRACE"] = str(inode_trace)
    environment["SWAPZ_POWER_TRACE"] = str(power_trace)
    if replace_after_pin:
        environment["SWAPZ_REPLACE_AFTER_CONFIG_PIN"] = "1"
    if aba_during_power_open:
        environment["SWAPZ_ABA_DURING_POWER_OPEN"] = "1"
    program = "\n".join((
        f"CONFIGFS={shlex.quote(str(configfs))}",
        f"CONFIGNAME={shlex.quote(config_name)}",
        f"CONFIG={shlex.quote(str(configfs / config_name))}",
        f"CONFIG_IDENTITY={shlex.quote(identity)}",
        "INDEX=7",
        "NULLBLK_SIZE_MIB=256",
        f"source {shlex.quote(str(extracted_shell))}",
        f"owned_nullblk_configfs_proof 1 {power_off}",
    ))
    result = subprocess.run(
        ["bash", "-c", program],
        env=environment, capture_output=True, text=True,
        timeout=10, check=False,
    )
    require(not result.stdout and not result.stderr,
            "native_source_execution", "unexpected_diagnostic", result.returncode)
    return result.returncode, inode_trace, power_trace


def assert_refused(case, edit):
    case_root, configfs, config, identity = create_config(case)
    edit(case_root, configfs, config)
    status, _, power_trace = run_proof(case_root, configfs, identity, 1)
    require(status == 1, case, "unproved_object_admitted", status)
    require(not power_trace.exists(), case, "power_write_attempted", status)
    require(configfs.is_dir(), case, "configfs_root_removed", status)
    return case_root, configfs, config


try:
    case_root, configfs, config, identity = create_config("volatile_owned_read")
    status, inode_trace, power_trace = run_proof(case_root, configfs, identity, 0)
    require(status == 0 and not power_trace.exists(),
            "volatile_owned_read", "stable_directory_rejected", status)
    require((config / "power").read_text(encoding="ascii") == "1\n",
            "volatile_owned_read", "read_only_probe_mutated_power")

    case_root, configfs, config, identity = create_config("volatile_owned_poweroff")
    status, inode_trace, power_trace = run_proof(case_root, configfs, identity, 1)
    require(status == 0 and (config / "power").read_text(encoding="ascii") == "0\n",
            "volatile_owned_poweroff", "owned_poweroff_rejected", status)
    require(power_trace.read_text(encoding="ascii") == "power_write\n",
            "volatile_owned_poweroff", "unexpected_power_write_count")
    entries = inode_trace.read_text(encoding="ascii").splitlines()
    power_inodes = [entry.split(":", 1)[1] for entry in entries
                    if entry.startswith("power:")]
    require(len(power_inodes) >= 3 and len(set(power_inodes)) == len(power_inodes),
            "configfs_inode_model", "attribute_inodes_not_volatile")
    # Negative control: persisting an attribute inode across these lookups
    # would falsely reject this proven, unchanged creator-owned directory.
    require(power_inodes[0] != power_inodes[-1],
            "legacy_inode_negative_control", "old_attribute_comparison_not_rejected")

    def replace_same_name(case_root, configfs, config):
        original = case_root / "retained-created-directory"
        config.rename(original)
        config.mkdir()
        for name, value in attribute_values.items():
            (config / name).write_text(value, encoding="ascii")

    case_root, configfs, config = assert_refused(
        "same_name_foreign_replacement", replace_same_name)
    require((config / "power").read_text(encoding="ascii") == "1\n" and
            (case_root / "retained-created-directory/power").read_text(
                encoding="ascii") == "1\n",
            "same_name_foreign_replacement", "creator_or_foreign_power_changed")

    case_root, configfs, config, identity = create_config(
        "same_name_replacement_after_pin")
    status, _, power_trace = run_proof(
        case_root, configfs, identity, 1, replace_after_pin=True)
    retained_config = case_root / "retained-pinned-directory"
    require(status == 1 and not power_trace.exists(),
            "same_name_replacement_after_pin",
            "post_pin_replacement_admitted_or_powered_off", status)
    require(retained_config.is_dir() and config.is_dir(),
            "same_name_replacement_after_pin",
            "creator_or_replacement_directory_missing")
    retained_metadata = retained_config.stat()
    replacement_metadata = config.stat()
    retained_identity = (
        f"{retained_metadata.st_dev}:{retained_metadata.st_ino}:"
        f"{retained_metadata.st_uid}"
    )
    require(retained_identity == identity and
            retained_metadata.st_ino != replacement_metadata.st_ino and
            (retained_config / "power").read_text(encoding="ascii") == "1\n" and
            (config / "power").read_text(encoding="ascii") == "1\n",
            "same_name_replacement_after_pin",
            "creator_or_replacement_not_retained")

    case_root, configfs, config, identity = create_config(
        "same_name_aba_during_power_open")
    status, _, power_trace = run_proof(
        case_root, configfs, identity, 1, aba_during_power_open=True)
    foreign_config = case_root / "retained-foreign-during-power-open"
    restored_metadata = config.stat()
    restored_identity = (
        f"{restored_metadata.st_dev}:{restored_metadata.st_ino}:"
        f"{restored_metadata.st_uid}"
    )
    require(status == 0 and
            power_trace.read_text(encoding="ascii") == "power_write\n",
            "same_name_aba_during_power_open",
            "pinned_power_write_rejected_or_repeated", status)
    require(restored_identity == identity and foreign_config.is_dir() and
            (config / "power").read_text(encoding="ascii") == "0\n" and
            (foreign_config / "power").read_text(encoding="ascii") == "1\n",
            "same_name_aba_during_power_open",
            "foreign_power_selected_by_public_name")

    def replace_with_foreign(case_root, configfs, config):
        original = case_root / "retained-created-directory"
        config.rename(original)
        config.mkdir()
        for name, value in attribute_values.items():
            (config / name).write_text(value, encoding="ascii")
        (original / "index").write_text("8\n", encoding="ascii")

    _, _, foreign = assert_refused("foreign_matching_attributes", replace_with_foreign)
    require((foreign / "power").read_text(encoding="ascii") == "1\n",
            "foreign_matching_attributes", "foreign_power_changed")

    _, _, missing_index = assert_refused(
        "missing_index", lambda _root, _base, config: (config / "index").unlink())
    require(not (missing_index / "index").exists(),
            "missing_index", "missing_attribute_recreated")
    _, _, malformed_index = assert_refused(
        "malformed_index", lambda _root, _base, config:
        (config / "index").write_text("07\n", encoding="ascii"))
    require((malformed_index / "index").read_text(encoding="ascii") == "07\n",
            "malformed_index", "malformed_attribute_rewritten")
    _, _, missing_power = assert_refused(
        "missing_power", lambda _root, _base, config: (config / "power").unlink())
    require(not (missing_power / "power").exists(),
            "missing_power", "missing_power_recreated")
    _, _, invalid_power = assert_refused(
        "unverifiable_power", lambda _root, _base, config:
        (config / "power").write_text("unknown\n", encoding="ascii"))
    require((invalid_power / "power").read_text(encoding="ascii") == "unknown\n",
            "unverifiable_power", "unverified_power_written")

    def power_symlink(case_root, _configfs, config):
        (config / "power").unlink()
        foreign_power = case_root / "foreign-power"
        foreign_power.write_text("1\n", encoding="ascii")
        (config / "power").symlink_to(foreign_power)

    case_root, _, linked_power = assert_refused("linked_power", power_symlink)
    require((case_root / "foreign-power").read_text(encoding="ascii") == "1\n" and
            (linked_power / "power").is_symlink(),
            "linked_power", "foreign_power_target_changed")
    case_root, _, absent = assert_refused(
        "identity_unavailable", lambda case_root, _base, config:
        config.rename(case_root / "retained-unobservable-directory"))
    retained_unobservable = case_root / "retained-unobservable-directory"
    require(not absent.exists() and retained_unobservable.is_dir() and
            (retained_unobservable / "power").read_text(encoding="ascii") == "1\n",
            "identity_unavailable", "unobservable_object_not_retained")
except AuditFailure as failure:
    print(f"FAIL: phase={failure.phase} "
          "expected_proof=pinned_creator_config_directory_and_canonical_attributes "
          f"observed_proof={failure.observed} original_errno=unavailable "
          f"original_exit={failure.original_exit} ownership=retained",
          file=sys.stderr)
    sys.exit(1)
except Exception as failure:
    original_errno = failure.errno if isinstance(failure, OSError) else "unavailable"
    print("FAIL: phase=isolated_source_control "
          "expected_proof=source_execution_without_host_mutations "
          "observed_proof=fixture_error "
          f"original_errno={original_errno} original_exit=unavailable "
          "ownership=retained", file=sys.stderr)
    sys.exit(1)
PY

printf '%s\n' 'PASS: null_blk identity, configfs race controls, legacy false admission and 66 isolated preflight fixtures (zero stale-resource cleanup)'
