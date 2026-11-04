#!/usr/bin/env python3
"""Rootless execution of the production primary-start late-admission boundary.

Compile the unmodified start coordinator and production mount/swap parsers in a
private C fixture. Only its external environment and mutation primitives are
intercepted: no real devices, mappers, mkswap, or swapon are touched.
A deliberately weakened local copy must demonstrate the regression's power.
"""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "src/userspace/swapz-primary.c"
INCLUDE_DIR = ROOT / "src/userspace"


def code_only(source: str) -> str:
    """Mask C comments and literals while preserving the exact byte offsets."""
    pattern = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S)
    return pattern.sub(lambda match: re.sub(r'[^\n]', ' ', match.group()), source)


def production_function(source: str, name: str) -> str:
    masked = code_only(source)
    expression = r'\b(?:static\s+)?int\s+' + re.escape(name) + r'\s*\([^;]*?\)\s*\{'
    found = re.search(expression, masked, re.S)
    if not found:
        raise AssertionError(f"Missing production function: {name}")
    nesting = 1
    for position in range(found.end(), len(masked)):
        if masked[position] == '{':
            nesting += 1
        elif masked[position] == '}':
            nesting -= 1
            if not nesting:
                return source[found.start():position + 1]
    raise AssertionError(f"Unclosed production function: {name}")


def omit_final_revalidation(function: str) -> str:
    """Negative control: remove exactly the block between intent and header write."""
    masked = code_only(function)
    anchor = masked.index('struct swapz_primary_mount_facts prewrite_mount_facts')
    opening = masked.rfind('{', 0, anchor)
    if opening < 0:
        raise AssertionError('Missing final revalidation compound statement')
    nesting = 1
    closing = None
    for position in range(opening + 1, len(masked)):
        if masked[position] == '{':
            nesting += 1
        elif masked[position] == '}':
            nesting -= 1
            if not nesting:
                closing = position + 1
                break
    if closing is None:
        raise AssertionError('Unclosed final revalidation compound statement')
    if 'swapz_primary_write_header_checked_fd' not in masked[closing:]:
        raise AssertionError('No destructive boundary after final check')
    return function[:opening] + '(void)0; /* negative-control omission */' + function[closing:]


# The fixture never calls any privileged system operation. Production start
# control flow is preserved; C shims supply staged, synthetic inventory data.
HARNESS = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include "swapz-primary.h"

#define SWAPZ_PRIMARY_BLOCK_BYTES 4096U
#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_RECOVERY_BASE "/fixture/recovery"
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1
#define SWAPZ_BUILD_SOURCE_CLEAN 1
#define SWAPZ_BUILD_SOURCE_SHA "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
#define SWAPZ_PRIMARY_TARGET_DEVICE makedev(8U, 1U)
#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) ((void)(phase))

struct swapz_primary_mount_facts {
    dev_t root_device;
    int root_mount_seen;
    int target_mounted;
};
struct swapz_primary_swap_entry {
    char path[PATH_MAX];
    char type[32];
    uint64_t size_kib;
    uint64_t used_kib;
    int priority;
};

/* Directly extracted production parsers follow: no test-model parser. */
@@PARSERS@@

enum fixture_scenario {
    FIXTURE_CLEAN, FIXTURE_SELECTED_MOUNT, FIXTURE_PARENT_MOUNT,
    FIXTURE_FOREIGN_SELECTED, FIXTURE_FOREIGN_PARENT,
    FIXTURE_SELECTED_SWAPFILE, FIXTURE_PARENT_SWAPFILE,
    FIXTURE_SELECTED_SWAP_PARTITION, FIXTURE_UNRELATED_SIBLING,
    FIXTURE_DISAPPEARED_PID, FIXTURE_PID_STILL_PRESENT,
    FIXTURE_REMOTE_EACCES, FIXTURE_REMOTE_EIO, FIXTURE_MALFORMED,
    FIXTURE_EMPTY, FIXTURE_LOCAL_MALFORMED, FIXTURE_PARENT_SUBSTITUTED,
    FIXTURE_ROOT_SUBSTITUTED, FIXTURE_ROOT_ON_SELECTED_PARENT, FIXTURE_HOLDER_LATE,
    FIXTURE_SWAP_INVENTORY_MALFORMED, FIXTURE_SWAP_STAT_EACCES,
    FIXTURE_DM_INITIAL, FIXTURE_SWAPS_INITIAL, FIXTURE_ROOT_INITIAL,
    FIXTURE_HOLDER_INITIAL, FIXTURE_SCENARIO_COUNT
};
static const char *const scenario_names[] = {
    "safe control", "selected mount late", "selected parent mount late",
    "foreign selected mount late", "foreign parent mount late",
    "selected swapfile late", "parent swapfile late",
    "selected swap partition late", "unrelated sibling late",
    "disappeared PID late", "PID still present late",
    "remote EACCES late", "remote EIO late", "malformed remote late",
    "empty remote late", "malformed self late", "parent substitution late",
    "root parent substitution late", "root on target parent late", "holder appears late",
    "malformed swap inventory late", "swapfile stat EACCES late",
    "DM initially active", "selected swap initially active",
    "root initially on selected parent", "holder initially active"
};
static enum fixture_scenario scenario;
static int late;
static unsigned int admission_reads;
static unsigned int prewrite_reads;
static unsigned int header_writes;
static unsigned int mapper_mutations;
static unsigned int mkswap_calls;
static unsigned int swapon_calls;
static unsigned int module_loads;
static unsigned int recovery_marks;
static struct swapz_primary_target selected_target;

static int fixture_admission_error(int error)
{
    errno = error;
    return -1;
}

static int fixture_mount_facts(struct swapz_primary_mount_facts *facts,
                               dev_t physical_parent)
{
    static const char *const safe_local =
        "36 25 259:0 / / rw - ext4 /dev/root rw\n";
    static const char *const safe_foreign =
        "36 25 259:9 / / rw - ext4 /dev/other rw\n";
    const char *local = safe_local;
    const char *foreign = safe_foreign;
    struct swapz_primary_mount_facts foreign_facts = {0};
    ++admission_reads;
    if (late)
        ++prewrite_reads;
    if (late && scenario == FIXTURE_LOCAL_MALFORMED)
        local = "malformed\n";
    if (late && scenario == FIXTURE_SELECTED_MOUNT)
        local = "36 25 259:0 / / rw - ext4 /dev/root rw\n"
                "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n";
    if (late && scenario == FIXTURE_PARENT_MOUNT)
        local = "36 25 259:0 / / rw - ext4 /dev/root rw\n"
                "37 36 8:0 / /mnt/parent rw - ext4 /dev/sda rw\n";
    if (late) {
        switch (scenario) {
        case FIXTURE_FOREIGN_SELECTED:
            foreign = "36 25 259:9 / / rw - ext4 /dev/other rw\n"
                      "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n";
            break;
        case FIXTURE_FOREIGN_PARENT:
            foreign = "36 25 259:9 / / rw - ext4 /dev/other rw\n"
                      "37 36 8:0 / /mnt/parent rw - ext4 /dev/sda rw\n";
            break;
        case FIXTURE_UNRELATED_SIBLING:
            foreign = "36 25 259:9 / / rw - ext4 /dev/other rw\n"
                      "37 36 8:2 / /mnt/sibling rw - ext4 /dev/sda2 rw\n";
            break;
        case FIXTURE_MALFORMED:
            foreign = "malformed\n";
            break;
        case FIXTURE_EMPTY:
            foreign = "";
            break;
        case FIXTURE_PID_STILL_PRESENT:
            return fixture_admission_error(ENOENT);
        case FIXTURE_REMOTE_EACCES:
            return fixture_admission_error(EACCES);
        case FIXTURE_REMOTE_EIO:
            return fixture_admission_error(EIO);
        default:
            break;
        }
    }
    if (swapz_primary_parse_mountinfo(local, SWAPZ_PRIMARY_TARGET_DEVICE,
                                       physical_parent, facts) < 0)
        return fixture_admission_error(EINVAL);
    /* Simulated disappearance means the PID and its namespace both vanished. */
    if (late && scenario == FIXTURE_DISAPPEARED_PID)
        return 0;
    if (swapz_primary_parse_mountinfo(foreign, SWAPZ_PRIMARY_TARGET_DEVICE,
                                      physical_parent, &foreign_facts) < 0)
        return fixture_admission_error(EINVAL);
    facts->target_mounted |= foreign_facts.target_mounted;
    return 0;
}

static int fixture_source_chain(const char *sysfs_root, dev_t device,
                                dev_t excluded, dev_t *parent)
{
    (void)sysfs_root;
    (void)excluded;
    if (device == SWAPZ_PRIMARY_TARGET_DEVICE) {
        /* The source-chain gate also checks selected/parent holders. */
        if (late && scenario == FIXTURE_HOLDER_LATE) {
            errno = EBUSY;
            return 0;
        }
        *parent = late && scenario == FIXTURE_PARENT_SUBSTITUTED
            ? makedev(8U, 9U) : makedev(8U, 0U);
        return 1;
    }
    if (device == makedev(259U, 0U)) {
        *parent = late && scenario == FIXTURE_ROOT_SUBSTITUTED
            ? makedev(259U, 2U)
            : (scenario == FIXTURE_ROOT_INITIAL ||
               (late && scenario == FIXTURE_ROOT_ON_SELECTED_PARENT))
                ? makedev(8U, 0U) : makedev(259U, 0U);
        return 1;
    }
    errno = ENODEV;
    return 0;
}

/* The read-inventory and stat seams feed actual production swap admission. */
static int fixture_swap_inventory(struct swapz_primary_swap_entry *entries,
                                  size_t capacity, size_t *count)
{
    static const char *const header = "Filename Type Size Used Priority\n";
    static const char *const regular =
        "Filename Type Size Used Priority\n"
        "/synthetic-swapfile file 8192 1 -2\n";
    static const char *const partition =
        "Filename Type Size Used Priority\n"
        "/synthetic-partition partition 4096 1 -2\n";
    const char *text = header;
    if ((!late && scenario == FIXTURE_SWAPS_INITIAL) ||
        (late && (scenario == FIXTURE_SELECTED_SWAPFILE ||
                  scenario == FIXTURE_PARENT_SWAPFILE ||
                  scenario == FIXTURE_SWAP_STAT_EACCES)))
        text = regular;
    if (late && scenario == FIXTURE_SELECTED_SWAP_PARTITION)
        text = partition;
    if (late && scenario == FIXTURE_SWAP_INVENTORY_MALFORMED)
        text = "broken inventory\n";
    if (swapz_primary_parse_swaps(text, entries, capacity, count) < 0)
        return fixture_admission_error(EINVAL);
    return 0;
}
static int fixture_stat(const char *path, struct stat *info)
{
    memset(info, 0, sizeof(*info));
    if (late && scenario == FIXTURE_SWAP_STAT_EACCES)
        return fixture_admission_error(EACCES);
    if (!strcmp(path, "/synthetic-swapfile")) {
        info->st_mode = S_IFREG | 0600U;
        info->st_dev = scenario == FIXTURE_PARENT_SWAPFILE
            ? makedev(8U, 0U) : SWAPZ_PRIMARY_TARGET_DEVICE;
        return 0;
    }
    if (!strcmp(path, "/synthetic-partition")) {
        info->st_mode = S_IFBLK | 0600U;
        info->st_rdev = SWAPZ_PRIMARY_TARGET_DEVICE;
        return 0;
    }
    return fixture_admission_error(ENOENT);
}
#define SWAPZ_PRIMARY_SWAP_ROWS_MAX 32U
#define swapz_primary_read_swap_inventory(a,b,c) fixture_swap_inventory(a,b,c)
#define stat(path,info) fixture_stat(path,info)
@@SWAP_FUNCTION@@
#undef stat
#undef swapz_primary_read_swap_inventory

static int fixture_target(struct swapz_primary_target *target)
{
    memset(target, 0, sizeof(*target));
    strcpy(target->partuuid, "f13428f6-01");
    target->device_major = 8U;
    target->device_minor = 1U;
    target->device_bytes = 17179869184ULL;
    selected_target = *target;
    return 0;
}
static int fixture_state_parse(struct swapz_primary_state *state)
{
    strcpy(state->run_id, "0123456789abcdef0123456789abcdef");
    state->stage = SWAPZ_PRIMARY_STAGE_READY;
    return 0;
}
static int fixture_manifest(struct swapz_primary_manifest *manifest)
{
    memset(manifest, 0, sizeof(*manifest));
    manifest->target = selected_target;
    strcpy(manifest->source_sha, SWAPZ_BUILD_SOURCE_SHA);
    strcpy(manifest->run_id, "0123456789abcdef0123456789abcdef");
    return 0;
}
static int fixture_report(struct swapz_primary_qualification *qualification)
{
    strcpy(qualification->source_sha, SWAPZ_BUILD_SOURCE_SHA);
    return 0;
}
static int fixture_recovery(int *safe, int *persistent, unsigned int *fs_major,
                            unsigned int *fs_minor, int *not_target,
                            int *chain, unsigned int *parent_major,
                            unsigned int *parent_minor, int *marker_clear)
{
    *safe = *persistent = *not_target = *chain = *marker_clear = 1;
    *fs_major = 259U;
    *fs_minor = 9U;
    *parent_major = 259U;
    *parent_minor = 9U;
    return 0;
}
static int fixture_module_inventory(int *loaded, int *mapper)
{
    *loaded = scenario == FIXTURE_DM_INITIAL;
    *mapper = scenario == FIXTURE_DM_INITIAL;
    return 0;
}
static int fixture_target_open(void)
{
    if (scenario == FIXTURE_HOLDER_INITIAL)
        return fixture_admission_error(EBUSY);
    return 99;
}
static int fixture_intent(void)
{
    /* All initial admissions happened before the environment changes. */
    if (admission_reads != 1U)
        abort();
    late = 1;
    return 0;
}
static int fixture_header_write(void)
{
    ++header_writes;
    return 0;
}
static int fixture_load_module(int *loaded)
{
    ++module_loads;
    *loaded = 1;
    return 0;
}
static int fixture_mapper_create(int *created, int *resumed, dev_t *device)
{
    ++mapper_mutations;
    *created = *resumed = 1;
    *device = makedev(253U, 8U);
    return 0;
}
static int fixture_mkswap(void)
{
    ++mkswap_calls;
    return 0;
}
static int fixture_swapon(int *activated)
{
    ++swapon_calls;
    *activated = 1;
    return 0;
}
static int fixture_record_read(size_t *length)
{
    *length = 1U;
    return 0;
}
static int fixture_hashes(char *control, char *module, char *oracle)
{
    control[0] = module[0] = oracle[0] = '\0';
    return 0;
}

/* Stub only ancillary preconditions/side effects, not start control flow. */
#define geteuid() 0
#define swapz_primary_valid_source_sha(...) 1
#define swapz_primary_configured_target(target) fixture_target(target)
#define swapz_primary_recovery_base_open(...) 3
#define swapz_primary_partition_lock_at(...) 4
#define swapz_primary_record_read_at(r, n, o, b, c, length, x) fixture_record_read(length)
#define swapz_primary_state_parse(r, length, state) fixture_state_parse(state)
#define swapz_primary_manifest_read_at(a,b,c,d,e,manifest) fixture_manifest(manifest)
#define swapz_primary_transaction_manifest_matches_at(...) 0
#define swapz_primary_read_qualification_report(q) fixture_report(q)
#define swapz_primary_live_artifact_hashes(a,b,c,d,e) fixture_hashes(a,b,c)
#define swapz_primary_qualification_artifacts_match(...) 1
#define swapz_primary_recovery_preflight(a,b,c,d,e,f,g,h,i) fixture_recovery(a,b,c,d,e,f,g,h,i)
#define swapz_primary_recovery_source_chain(a,b,c,d) fixture_source_chain(a,b,c,d)
#define swapz_primary_read_mount_facts(facts, parent) fixture_mount_facts(facts,parent)
#define swapz_primary_read_module_mapper_inventory(a,b) fixture_module_inventory(a,b)
#define swapz_primary_header_backup_read_at(...) 0
#define swapz_primary_header_build(...) 0
#define swapz_primary_target_open_exclusive(...) fixture_target_open()
#define swapz_primary_exact_read(...) 0
#define swapz_primary_state_write_at(...) 0
#define swapz_primary_module_load_intent_write_at(...) fixture_intent()
#define swapz_primary_write_header_checked_fd(...) fixture_header_write()
#define swapz_primary_load_qualified_module(loaded) fixture_load_module(loaded)
#define swapz_primary_module_load_mark_loaded_at(...) 0
#define swapz_primary_dm_create_mapper(a,b,c,d,e,f,g) fixture_mapper_create(e,f,g)
#define swapz_primary_format_mapper_swap(...) fixture_mkswap()
#define swapz_primary_activate_mapper_swap(a,b,c,d,e) fixture_swapon(e)
#define swapz_primary_state_require_recovery_at(...) (++recovery_marks, 0)
#define close(fd) 0

/* The actual production coordinator function is inserted verbatim. */
@@START_FUNCTION@@

static int check_case(enum fixture_scenario candidate)
{
    int expected_safe;
    int result;
    unsigned int writes;
    scenario = candidate;
    late = 0;
    admission_reads = prewrite_reads = 0U;
    header_writes = mapper_mutations = mkswap_calls = swapon_calls = 0U;
    module_loads = recovery_marks = 0U;
    errno = 0;
    result = swapz_primary_start_prepared();
    expected_safe = candidate == FIXTURE_CLEAN ||
        candidate == FIXTURE_UNRELATED_SIBLING ||
        candidate == FIXTURE_DISAPPEARED_PID;
    writes = header_writes + mapper_mutations + mkswap_calls + swapon_calls;
    if (expected_safe) {
        if (result != 0 || admission_reads != 2U || prewrite_reads != 1U ||
            header_writes != 1U || mapper_mutations != 1U ||
            mkswap_calls != 1U || swapon_calls != 1U) {
            fprintf(stderr, "FAIL: %s: safe result=%d initial+late=%u "
                    "late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, admission_reads,
                    prewrite_reads, header_writes, mapper_mutations,
                    mkswap_calls, swapon_calls);
            return 1;
        }
    } else {
        if (result == 0 || writes || module_loads ||
            ((candidate >= FIXTURE_DM_INITIAL ||
              candidate == FIXTURE_PARENT_SUBSTITUTED ||
              candidate == FIXTURE_HOLDER_LATE) ?
                 prewrite_reads != 0U : prewrite_reads != 1U)) {
            fprintf(stderr, "FAIL: %s: refusal result=%d initial+late=%u "
                    "late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, admission_reads,
                    prewrite_reads, header_writes, mapper_mutations,
                    mkswap_calls, swapon_calls);
            return 1;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    int failures = 0;
    int candidate;
    (void)argv;
    for (candidate = FIXTURE_CLEAN; candidate < FIXTURE_SCENARIO_COUNT;
         ++candidate) {
        /* Negative control needs a late-mount case that must reject writes. */
        if (argc > 1 && candidate != FIXTURE_FOREIGN_SELECTED)
            continue;
        failures += check_case((enum fixture_scenario)candidate);
    }
    if (failures)
        return 1;
    printf("PASS: production primary-start lifecycle late-race (%d cases)\n",
           argc > 1 ? 1 : FIXTURE_SCENARIO_COUNT);
    return 0;
}
'''


def compile_and_run(source: str, workdir: Path, *, mutant: bool) -> subprocess.CompletedProcess[str]:
    helpers = (
        "swapz_primary_parse_u64", "swapz_primary_parse_priority",
        "swapz_primary_parse_dev_number", "swapz_primary_split_fields",
        "swapz_primary_parse_swaps", "swapz_primary_swap_inventory_target_is_quiescent",
        "swapz_primary_parse_mountinfo",
    )
    parser_source = '\n\n'.join(production_function(source, helper) for helper in helpers)
    swap_function = production_function(source, "swapz_primary_swap_device_active")
    coordinator = production_function(source, "swapz_primary_start_prepared")
    if mutant:
        coordinator = omit_final_revalidation(coordinator)
    unit = HARNESS.replace('@@PARSERS@@', parser_source).replace(
        '@@SWAP_FUNCTION@@', swap_function).replace(
        '@@START_FUNCTION@@', coordinator)
    c_path = workdir / ("mutant.c" if mutant else "production.c")
    binary = workdir / ("mutant" if mutant else "production")
    c_path.write_text(unit)
    compilation = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-Wno-unused-function", "-Wno-unused-variable", "-Wno-unused-but-set-variable", "-I", str(INCLUDE_DIR), str(c_path),
         "-o", str(binary)], text=True, capture_output=True, check=False)
    if compilation.returncode:
        raise AssertionError(f"{c_path.name} compile failed:\n{compilation.stderr}")
    return subprocess.run(
        [str(binary), "negative-control"] if mutant else [str(binary)],
        text=True, capture_output=True, check=False)


def main() -> int:
    source = SOURCE.read_text()
    with tempfile.TemporaryDirectory(prefix="swapz-primary-late-race-") as folder:
        workdir = Path(folder)
        production = compile_and_run(source, workdir, mutant=False)
        if production.returncode:
            print(production.stdout, end="")
            print(production.stderr, file=sys.stderr, end="")
            return 1
        print(production.stdout, end="")
        mutant = compile_and_run(source, workdir, mutant=True)
        if mutant.returncode == 0 or "header_write=1" not in mutant.stderr:
            print("FAIL: omission of final recheck did not expose a write", file=sys.stderr)
            print(mutant.stdout + mutant.stderr, file=sys.stderr, end="")
            return 1
        print("PASS: negative control fails on intercepted header write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
