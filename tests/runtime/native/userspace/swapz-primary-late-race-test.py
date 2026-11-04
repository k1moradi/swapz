#!/usr/bin/env python3
"""Rootless execution of the production primary-start late-admission boundary.

Compile the unmodified start coordinator and actual production mount-inventory
reader and swap parsers in a private C fixture. Its /proc and mutations are
intercepted: no real mounts, devices, mappers, mkswap or swapon are touched.
The late inventory is changed after initial admission, before header write.
This proves only the bounded final snapshot: it cannot exclude a concurrent
mount or swap activation after that snapshot returns and before header mutation.
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


def production_define(source: str, name: str) -> str:
    """Return one simple production #define verbatim."""
    matches = re.findall(
        rf'^#define[ \t]+{re.escape(name)}[ \t]+[^\n]+$', source, re.M)
    if len(matches) != 1:
        raise AssertionError(f"Expected one production define for {name}")
    return matches[0]


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
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#include "swapz-primary.h"

@@PRODUCTION_DEFINES@@
#define SWAPZ_PRIMARY_BLOCK_BYTES 4096U
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
    FIXTURE_HOLDER_INITIAL, FIXTURE_UNRELATED_SWAPFILE,
    FIXTURE_WRONG_MOUNT_DEVICE, FIXTURE_REMOTE_OVERSIZED,
    FIXTURE_LOCAL_OVERSIZED, FIXTURE_PID_INVENTORY_EACCES,
    FIXTURE_SYMLINK_MOUNTINFO, FIXTURE_WRONG_TARGET_OPEN,
    FIXTURE_TRUNCATED_REMOTE, FIXTURE_TRUNCATED_LOCAL,
    FIXTURE_NAMESPACE_STAT_EACCES, FIXTURE_STALE_PARTUUID,
    FIXTURE_POST_SNAPSHOT_MOUNT, FIXTURE_POST_SNAPSHOT_SWAPON,
    FIXTURE_SCENARIO_COUNT
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
    "root initially on selected parent", "holder initially active",
    "unrelated /swapfile late", "wrong-device mount alias late",
    "oversized remote mountinfo late", "oversized local mountinfo late",
    "unreadable PID inventory late", "symlink mountinfo late",
    "selected device identity changed before exclusive open",
    "truncated remote mountinfo late", "truncated local mountinfo late",
    "inaccessible PID namespace late", "stale PARTUUID on exclusive open",
    "new mount immediately after final safe inventory",
    "new swap immediately after final safe inventory"
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
static unsigned int starting_state_writes;
static unsigned int active_state_writes;
static unsigned int active_inventory_reads;
static int post_snapshot_injected;
static struct swapz_primary_target selected_target;
static struct swapz_primary_target swapz_primary_selected_target;

static int fixture_admission_error(int error)
{
    errno = error;
    return -1;
}


/*
 * The production mount reader below performs the real open/read/readdir/stat
 * sequence. Only /proc paths are redirected into private regular files.
 * No privileged namespace change or host mount table is observed.
 */
static char fixture_proc_root[PATH_MAX];
static int fixture_mount_fd = -1;
static int fixture_mount_open_error;
static int fixture_mount_read_error;
static int fixture_inventory_error;
static unsigned int fixture_mount_open_count;
static unsigned int fixture_mount_read_count;

static const char *fixture_proc_path(const char *path, char converted[PATH_MAX])
{
    int length;

    if (strncmp(path, "/proc", 5U) || (path[5] && path[5] != '/'))
        return path;
    length = snprintf(converted, PATH_MAX, "%s%s", fixture_proc_root, path + 5U);
    assert(length >= 0 && length < PATH_MAX);
    return converted;
}

static void fixture_inventory_file(const char *relative, const char *contents)
{
    char path[PATH_MAX];
    int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root, relative);
    FILE *stream;

    assert(length > 0 && (size_t)length < sizeof(path));
    stream = fopen(path, "wb");
    assert(stream != NULL);
    assert(fputs(contents, stream) >= 0);
    assert(fclose(stream) == 0);
}

static void fixture_inventory_remove(const char *relative)
{
    char path[PATH_MAX];
    int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root, relative);

    assert(length > 0 && (size_t)length < sizeof(path));
    assert(unlink(path) == 0);
}

static void fixture_oversized_mountinfo(const char *relative)
{
    char path[PATH_MAX];
    char bytes[256];
    int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root, relative);
    FILE *stream;
    size_t index;

    assert(length > 0 && (size_t)length < sizeof(path));
    stream = fopen(path, "wb");
    assert(stream != NULL);
    memset(bytes, 'X', sizeof(bytes));
    for (index = 0; index <= SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES /
                               sizeof(bytes); ++index)
        assert(fwrite(bytes, 1U, sizeof(bytes), stream) == sizeof(bytes));
    assert(fclose(stream) == 0);
}

static void fixture_reset_mount_inventory(void)
{
    fixture_mount_fd = -1;
    fixture_mount_open_error = fixture_mount_read_error = fixture_inventory_error = 0;
    fixture_mount_open_count = fixture_mount_read_count = 0U;
    /* Remove a preceding case's no-follow symlink before recreating the file. */
    {
        char path[PATH_MAX];
        int length = snprintf(path, sizeof(path), "%s/self/mountinfo", fixture_proc_root);

        assert(length > 0 && (size_t)length < sizeof(path));
        if (unlink(path) < 0)
            assert(errno == ENOENT);
    }
    fixture_inventory_file("self/mountinfo",
                           "36 25 259:0 / / rw - ext4 /dev/root rw\n");
    fixture_inventory_file("3031/mountinfo",
                           "36 25 259:9 / / rw - ext4 /dev/other rw\n");
    fixture_inventory_file("3031/ns/mnt", "namespace present\n");
}

static void fixture_apply_late_inventory(void)
{
    char path[PATH_MAX];
    int length;

    switch (scenario) {
    case FIXTURE_SELECTED_MOUNT:
        fixture_inventory_file("self/mountinfo",
            "36 25 259:0 / / rw - ext4 /dev/root rw\n"
            "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
        break;
    case FIXTURE_PARENT_MOUNT:
        fixture_inventory_file("self/mountinfo",
            "36 25 259:0 / / rw - ext4 /dev/root rw\n"
            "37 36 8:0 / /mnt/parent rw - ext4 /dev/sda rw\n");
        break;
    case FIXTURE_FOREIGN_SELECTED:
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
        break;
    case FIXTURE_FOREIGN_PARENT:
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:0 / /mnt/parent rw - ext4 /dev/sda rw\n");
        break;
    case FIXTURE_UNRELATED_SIBLING:
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:2 / /mnt/sibling rw - ext4 /dev/sda2 rw\n");
        break;
    case FIXTURE_WRONG_MOUNT_DEVICE:
        /* A misleading /dev source name never overrides the 8:2 identity. */
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:2 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
        break;
    case FIXTURE_MALFORMED:
        fixture_inventory_file("3031/mountinfo", "malformed\n");
        break;
    case FIXTURE_EMPTY:
        fixture_inventory_file("3031/mountinfo", "");
        break;
    case FIXTURE_LOCAL_MALFORMED:
        fixture_inventory_file("self/mountinfo", "malformed\n");
        break;
    case FIXTURE_REMOTE_OVERSIZED:
        fixture_oversized_mountinfo("3031/mountinfo");
        break;
    case FIXTURE_LOCAL_OVERSIZED:
        fixture_oversized_mountinfo("self/mountinfo");
        break;
    case FIXTURE_PID_STILL_PRESENT:
        fixture_mount_open_error = ENOENT;
        break;
    case FIXTURE_DISAPPEARED_PID:
        fixture_inventory_remove("3031/mountinfo");
        fixture_inventory_remove("3031/ns/mnt");
        break;
    case FIXTURE_REMOTE_EACCES:
        fixture_mount_open_error = EACCES;
        break;
    case FIXTURE_REMOTE_EIO:
        fixture_mount_read_error = EIO;
        break;
    case FIXTURE_PID_INVENTORY_EACCES:
        fixture_inventory_error = EACCES;
        break;
    case FIXTURE_SYMLINK_MOUNTINFO:
        fixture_inventory_remove("self/mountinfo");
        length = snprintf(path, sizeof(path), "%s/self/mountinfo", fixture_proc_root);
        assert(length > 0 && (size_t)length < sizeof(path));
        assert(symlink("../3031/mountinfo", path) == 0);
        break;
    case FIXTURE_TRUNCATED_REMOTE:
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /selected rw - ext4 /dev/selected");
        break;
    case FIXTURE_TRUNCATED_LOCAL:
        fixture_inventory_file("self/mountinfo",
            "36 25 259:0 / / rw - ext4 /dev/root rw\n"
            "37 36 8:1 / /selected rw - ext4 /dev/selected");
        break;
    case FIXTURE_NAMESPACE_STAT_EACCES:
        fixture_mount_open_error = ENOENT;
        break;
    default:
        /* Every other test also starts with a freshly initialized safe table. */
        break;
    }
}

static int fixture_proc_open(const char *path, int flags)
{
    char converted[PATH_MAX];
    int fd;
    int remote = !strcmp(path, "/proc/3031/mountinfo");

    if (strstr(path, "/mountinfo")) {
        ++fixture_mount_open_count;
        /* Production must never follow mountinfo symlinks. */
        assert((flags & O_NOFOLLOW) != 0);
    }
    if (remote && fixture_mount_open_error) {
        errno = fixture_mount_open_error;
        return -1;
    }
    fd = open(fixture_proc_path(path, converted), flags);
    if (remote && fd >= 0)
        fixture_mount_fd = fd;
    return fd;
}

static ssize_t fixture_proc_read(int fd, void *buffer, size_t length)
{
    ++fixture_mount_read_count;
    if (fd == fixture_mount_fd && fixture_mount_read_error) {
        errno = fixture_mount_read_error;
        return -1;
    }
    return read(fd, buffer, length);
}

static int fixture_proc_close(int fd)
{
    if (fd == fixture_mount_fd)
        fixture_mount_fd = -1;
    return close(fd);
}

static DIR *fixture_proc_opendir(const char *path)
{
    char converted[PATH_MAX];

    if (!strcmp(path, "/proc") && fixture_inventory_error) {
        errno = fixture_inventory_error;
        return NULL;
    }
    return opendir(fixture_proc_path(path, converted));
}

static int fixture_proc_stat(const char *path, struct stat *info)
{
    char converted[PATH_MAX];

    if (late && scenario == FIXTURE_NAMESPACE_STAT_EACCES &&
        !strcmp(path, "/proc/3031/ns/mnt"))
        return fixture_admission_error(EACCES);
    return stat(fixture_proc_path(path, converted), info);
}

#define open(path,flags) fixture_proc_open(path,flags)
#define read(fd,buffer,length) fixture_proc_read(fd,buffer,length)
#define close(fd) fixture_proc_close(fd)
#define opendir(path) fixture_proc_opendir(path)
#define stat(path,info) fixture_proc_stat(path,info)
#define getpid() ((pid_t)65535)
/* Extracted, unchanged production PID scanner and bounded mountinfo reader. */
@@MOUNT_READER@@
#undef getpid
#undef stat
#undef opendir
#undef close
#undef read
#undef open

static int fixture_read_mount_facts(struct swapz_primary_mount_facts *facts,
                                    dev_t parent_device)
{
    int result;

    ++admission_reads;
    if (late)
        ++prewrite_reads;
    result = swapz_primary_read_mount_facts(facts, parent_device);
    assert(fixture_mount_fd == -1);
    return result;
}

static void fixture_create_proc_root(void)
{
    char template_path[] = "/tmp/swapz-start-reader-XXXXXX";
    char path[PATH_MAX];
    int length;

    assert(mkdtemp(template_path) != NULL);
    assert(strlen(template_path) < sizeof(fixture_proc_root));
    strcpy(fixture_proc_root, template_path);
    length = snprintf(path, sizeof(path), "%s/self", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031/ns", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
}

static int fixture_remove_proc_entry(const char *path, const struct stat *info,
                                     int type, struct FTW *tree)
{
    (void)info;
    (void)type;
    (void)tree;
    return remove(path);
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
    static const char *const unrelated =
        "Filename Type Size Used Priority\n"
        "/swapfile file 8192 1 -2\n";
    const char *text = header;
    if ((!late && scenario == FIXTURE_SWAPS_INITIAL) ||
        (late && (scenario == FIXTURE_SELECTED_SWAPFILE ||
                  scenario == FIXTURE_PARENT_SWAPFILE ||
                  scenario == FIXTURE_SWAP_STAT_EACCES)))
        text = regular;
    if (late && scenario == FIXTURE_SELECTED_SWAP_PARTITION)
        text = partition;
    if (late && scenario == FIXTURE_UNRELATED_SWAPFILE)
        text = unrelated;
    if (late && scenario == FIXTURE_SWAP_INVENTORY_MALFORMED)
        text = "broken inventory\n";
    if (post_snapshot_injected && scenario == FIXTURE_POST_SNAPSHOT_SWAPON)
        text = regular;
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
    if (!strcmp(path, "/swapfile")) {
        info->st_mode = S_IFREG | 0600U;
        info->st_dev = makedev(259U, 9U);
        return 0;
    }
    if (!strcmp(path, "/synthetic-partition")) {
        info->st_mode = S_IFBLK | 0600U;
        info->st_rdev = SWAPZ_PRIMARY_TARGET_DEVICE;
        return 0;
    }
    return fixture_admission_error(ENOENT);
}
#define swapz_primary_read_swap_inventory(a,b,c) fixture_swap_inventory(a,b,c)
#define stat(path,info) fixture_stat(path,info)
@@SWAP_FUNCTION@@
#undef stat
#undef swapz_primary_read_swap_inventory

/*
 * Keep the real production swap admission result. Only after the fourth
 * (final selected-device) inventory has returned safe do we inject a new
 * mount or swap. This is an observation of the remaining gap, NOT proof of
 * kernel exclusivity, and the header-write seam never touches a device.
 */
static int fixture_observed_swap_device_active(dev_t device)
{
    int active = swapz_primary_swap_device_active(device);

    ++active_inventory_reads;
    if (late && active == 0 && active_inventory_reads == 4U &&
        (scenario == FIXTURE_POST_SNAPSHOT_MOUNT ||
         scenario == FIXTURE_POST_SNAPSHOT_SWAPON)) {
        post_snapshot_injected = 1;
        if (scenario == FIXTURE_POST_SNAPSHOT_MOUNT)
            fixture_inventory_file("3031/mountinfo",
                "36 25 259:9 / / rw - ext4 /dev/other rw\n"
                "37 36 8:1 / /selected rw - ext4 /dev/selected rw\n");
    }
    return active;
}

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
static int fixture_target_inspect(const char *partuuid,
                                  struct swapz_primary_target *target)
{
    if (strcmp(partuuid, selected_target.partuuid))
        return fixture_admission_error(EINVAL);
    *target = selected_target;
    if (scenario == FIXTURE_WRONG_TARGET_OPEN)
        target->device_minor = 2U;
    if (scenario == FIXTURE_STALE_PARTUUID)
        strcpy(target->partuuid, "f13428f6-02");
    return 0;
}

static int fixture_target_checked_open(const char *device_path,
                                       const char *uuid_path,
                                       const char *partuuid_path,
                                       int flags)
{
    char expected_path[PATH_MAX];
    int length = snprintf(expected_path, sizeof(expected_path),
                          SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT,
                          selected_target.partuuid);

    assert(length > 0 && (size_t)length < sizeof(expected_path));
    assert(!strcmp(device_path, expected_path));
    assert(!strcmp(uuid_path, expected_path));
    assert(!strcmp(partuuid_path, expected_path));
    assert(flags == (O_RDWR | O_EXCL));
    if (scenario == FIXTURE_HOLDER_INITIAL)
        return fixture_admission_error(EBUSY);
    return 99;
}

#define swapz_primary_manifest_valid(...) 1
#define swapz_primary_target_inspect(partuuid, target) \
    fixture_target_inspect(partuuid, target)
#define swapz_primary_open_target_checked_partuuid_paths_mode(a,b,c,d) \
    fixture_target_checked_open(a,b,c,d)
/*
 * Keep production target normalization/geometry/identity and the exclusive
 * opener. Only device inspection and the final block-device open are rooted in
 * the fixture, so wrong major:minor is detected by production comparison code.
 */
@@TARGET_HELPERS@@
@@TARGET_OPEN_FUNCTION@@
#undef swapz_primary_open_target_checked_partuuid_paths_mode
#undef swapz_primary_target_inspect
#undef swapz_primary_manifest_valid
static int fixture_intent(void)
{
    /* All initial admissions happened before the environment changes. */
    if (admission_reads != 1U)
        abort();
    late = 1;
    fixture_apply_late_inventory();
    return 0;
}
static int fixture_header_write(void)
{
    /* A diagnostic reread proves that the post-snapshot change is visible,
     * but it deliberately does not gate the simulated destructive boundary. */
    if (scenario == FIXTURE_POST_SNAPSHOT_MOUNT) {
        struct swapz_primary_mount_facts facts = {0};

        assert(post_snapshot_injected);
        assert(swapz_primary_read_mount_facts(
            &facts, makedev(8U, 0U)) == 0 && facts.target_mounted);
    }
    if (scenario == FIXTURE_POST_SNAPSHOT_SWAPON) {
        assert(post_snapshot_injected);
        assert(swapz_primary_swap_device_active(makedev(8U, 1U)) == 1);
    }
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
static int fixture_state_write(const struct swapz_primary_state *state)
{
    if (state->stage == SWAPZ_PRIMARY_STAGE_STARTING)
        ++starting_state_writes;
    else if (state->stage == SWAPZ_PRIMARY_STAGE_ACTIVE)
        ++active_state_writes;
    else
        abort();
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
#define swapz_primary_read_mount_facts(facts, parent) fixture_read_mount_facts(facts,parent)
#define swapz_primary_read_module_mapper_inventory(a,b) fixture_module_inventory(a,b)
#define swapz_primary_header_backup_read_at(...) 0
#define swapz_primary_header_build(...) 0
#define swapz_primary_exact_read(...) 0
#define swapz_primary_state_write_at(a,b,state,owner) fixture_state_write(state)
#define swapz_primary_module_load_intent_write_at(...) fixture_intent()
#define swapz_primary_write_header_checked_fd(...) fixture_header_write()
#define swapz_primary_load_qualified_module(loaded) fixture_load_module(loaded)
#define swapz_primary_module_load_mark_loaded_at(...) 0
#define swapz_primary_dm_create_mapper(a,b,c,d,e,f,g) fixture_mapper_create(e,f,g)
#define swapz_primary_format_mapper_swap(...) fixture_mkswap()
#define swapz_primary_activate_mapper_swap(a,b,c,d,e) fixture_swapon(e)
#define swapz_primary_state_require_recovery_at(...) (++recovery_marks, 0)
#define swapz_primary_swap_device_active(device) fixture_observed_swap_device_active(device)
#define close(fd) 0

/* The actual production coordinator function is inserted verbatim. */
@@START_FUNCTION@@
#undef close
#undef swapz_primary_swap_device_active

static int check_case(enum fixture_scenario candidate)
{
    int expected_safe;
    int expected_error = 0;
    int result;
    int result_errno;
    int saved_stderr;
    int gap_probe;
    char diagnostic[512] = {0};
    char expected_diagnostic[128];
    size_t diagnostic_length;
    FILE *diagnostic_stream;
    unsigned int writes;
    scenario = candidate;
    late = 0;
    memset(&swapz_primary_selected_target, 0,
           sizeof(swapz_primary_selected_target));
    admission_reads = prewrite_reads = active_inventory_reads = 0U;
    post_snapshot_injected = 0;
    fixture_reset_mount_inventory();
    header_writes = mapper_mutations = mkswap_calls = swapon_calls = 0U;
    module_loads = recovery_marks = 0U;
    starting_state_writes = active_state_writes = 0U;
    diagnostic_stream = tmpfile();
    assert(diagnostic_stream != NULL);
    assert(fflush(stderr) == 0);
    saved_stderr = dup(STDERR_FILENO);
    assert(saved_stderr >= 0);
    assert(dup2(fileno(diagnostic_stream), STDERR_FILENO) == STDERR_FILENO);
    errno = 0;
    result = swapz_primary_start_prepared();
    result_errno = errno;
    assert(fflush(stderr) == 0);
    assert(dup2(saved_stderr, STDERR_FILENO) == STDERR_FILENO);
    assert(close(saved_stderr) == 0);
    assert(fseek(diagnostic_stream, 0L, SEEK_SET) == 0);
    diagnostic_length = fread(diagnostic, 1U, sizeof(diagnostic) - 1U,
                              diagnostic_stream);
    assert(!ferror(diagnostic_stream) && feof(diagnostic_stream));
    assert(fclose(diagnostic_stream) == 0);
    diagnostic[diagnostic_length] = '\0';
    gap_probe = candidate == FIXTURE_POST_SNAPSHOT_MOUNT ||
                candidate == FIXTURE_POST_SNAPSHOT_SWAPON;
    expected_safe = candidate == FIXTURE_CLEAN ||
        candidate == FIXTURE_UNRELATED_SIBLING ||
        candidate == FIXTURE_UNRELATED_SWAPFILE ||
        candidate == FIXTURE_WRONG_MOUNT_DEVICE ||
        candidate == FIXTURE_DISAPPEARED_PID;
    switch (candidate) {
    case FIXTURE_SELECTED_MOUNT:
    case FIXTURE_PARENT_MOUNT:
    case FIXTURE_FOREIGN_SELECTED:
    case FIXTURE_FOREIGN_PARENT:
    case FIXTURE_SELECTED_SWAPFILE:
    case FIXTURE_PARENT_SWAPFILE:
    case FIXTURE_SELECTED_SWAP_PARTITION:
    case FIXTURE_HOLDER_LATE:
    case FIXTURE_DM_INITIAL:
    case FIXTURE_SWAPS_INITIAL:
    case FIXTURE_HOLDER_INITIAL:
        expected_error = EBUSY;
        break;
    case FIXTURE_PID_STILL_PRESENT:
        expected_error = ENOENT;
        break;
    case FIXTURE_REMOTE_EACCES:
    case FIXTURE_SWAP_STAT_EACCES:
    case FIXTURE_PID_INVENTORY_EACCES:
    case FIXTURE_NAMESPACE_STAT_EACCES:
        expected_error = EACCES;
        break;
    case FIXTURE_REMOTE_EIO:
        expected_error = EIO;
        break;
    case FIXTURE_MALFORMED:
    case FIXTURE_EMPTY:
    case FIXTURE_LOCAL_MALFORMED:
    case FIXTURE_SWAP_INVENTORY_MALFORMED:
    case FIXTURE_TRUNCATED_REMOTE:
    case FIXTURE_TRUNCATED_LOCAL:
        expected_error = EINVAL;
        break;
    case FIXTURE_PARENT_SUBSTITUTED:
    case FIXTURE_ROOT_SUBSTITUTED:
    case FIXTURE_ROOT_ON_SELECTED_PARENT:
    case FIXTURE_WRONG_TARGET_OPEN:
    case FIXTURE_STALE_PARTUUID:
        expected_error = ESTALE;
        break;
    case FIXTURE_ROOT_INITIAL:
        expected_error = EPERM;
        break;
    case FIXTURE_REMOTE_OVERSIZED:
    case FIXTURE_LOCAL_OVERSIZED:
        expected_error = EOVERFLOW;
        break;
    case FIXTURE_SYMLINK_MOUNTINFO:
        expected_error = ELOOP;
        break;
    default:
        assert(expected_safe);
        break;
    }
    writes = header_writes + mapper_mutations + mkswap_calls + swapon_calls;
    /* The full production reader must have opened and read real fixture fds. */
    if (fixture_mount_open_count < admission_reads ||
        fixture_mount_read_count < admission_reads ||
        fixture_mount_fd != -1) {
        fprintf(stderr, "FAIL: %s: reader not executed (opens=%u reads=%u admissions=%u)\n",
                scenario_names[candidate], fixture_mount_open_count,
                fixture_mount_read_count, admission_reads);
        return 1;
    }
    if (gap_probe) {
        /* The injected mount/swap is detected by a diagnostic production
         * reread, but no atomic kernel exclusion is established by this test. */
        if (result != 0 || !post_snapshot_injected ||
            admission_reads != 2U || prewrite_reads != 1U ||
            active_inventory_reads != 4U || writes != 4U ||
            starting_state_writes != 1U || active_state_writes != 1U ||
            recovery_marks != 0U || diagnostic_length != 0U) {
            fprintf(stderr, "FAIL: %s: post-snapshot gap result=%d "
                    "injected=%d reads=%u swap_reads=%u mutations=%u "
                    "diagnostic=%s\n", scenario_names[candidate], result,
                    post_snapshot_injected, admission_reads,
                    active_inventory_reads, writes, diagnostic);
            return 1;
        }
        printf("UNPROVEN: %s: post-final-snapshot mount/swapon exclusivity "
               "requires a separate host-only kernel proof\n",
               scenario_names[candidate]);
        return 0;
    }
    if (expected_safe) {
        if (result != 0 || admission_reads != 2U || prewrite_reads != 1U ||
            header_writes != 1U || mapper_mutations != 1U ||
            mkswap_calls != 1U || swapon_calls != 1U ||
            starting_state_writes != 1U || active_state_writes != 1U ||
            recovery_marks != 0U || diagnostic_length != 0U) {
            fprintf(stderr, "FAIL: %s: safe result=%d initial+late=%u "
                    "late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, admission_reads,
                    prewrite_reads, header_writes, mapper_mutations,
                    mkswap_calls, swapon_calls);
            return 1;
        }
    } else {
        const char *phase = late ? "header-write" : "admission";
        int prefix_length = snprintf(expected_diagnostic,
            sizeof(expected_diagnostic),
            "PRIMARY_START=FAILED phase=%s errno=%d error=",
            phase, expected_error);

        assert(prefix_length > 0 &&
               (size_t)prefix_length < sizeof(expected_diagnostic));
        if (result == 0 || result_errno != expected_error ||
            strncmp(diagnostic, expected_diagnostic,
                    (size_t)prefix_length) != 0 ||
            strchr(diagnostic, '\n') != diagnostic + strlen(diagnostic) - 1U ||
            strstr(diagnostic, "run_id") ||
            strstr(diagnostic, "0123456789abcdef") ||
            strstr(diagnostic, "secret") || writes || module_loads ||
            starting_state_writes != (unsigned int)late ||
            active_state_writes != 0U ||
            recovery_marks != (unsigned int)late ||
            ((candidate == FIXTURE_DM_INITIAL ||
              candidate == FIXTURE_SWAPS_INITIAL ||
              candidate == FIXTURE_ROOT_INITIAL ||
              candidate == FIXTURE_HOLDER_INITIAL ||
              candidate == FIXTURE_WRONG_TARGET_OPEN ||
              candidate == FIXTURE_STALE_PARTUUID ||
              candidate == FIXTURE_PARENT_SUBSTITUTED ||
              candidate == FIXTURE_HOLDER_LATE) ?
                 prewrite_reads != 0U : prewrite_reads != 1U)) {
            fprintf(stderr, "FAIL: %s: refusal result=%d errno=%d expected=%d "
                    "initial+late=%u late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, result_errno, expected_error,
                    admission_reads, prewrite_reads, header_writes,
                    mapper_mutations, mkswap_calls, swapon_calls);
            fprintf(stderr, "FAIL: diagnostic=%s\n", diagnostic);
            return 1;
        }
        printf("DENY: %s phase=%s errno=%d claim=retained "
               "state=%s mutations=0\n", scenario_names[candidate],
               phase, expected_error, late ? "recovery-requested" : "READY");
    }
    return 0;
}

int main(int argc, char **argv)
{
    int failures = 0;
    int candidate;
    (void)argv;
    fixture_create_proc_root();
    for (candidate = FIXTURE_CLEAN; candidate < FIXTURE_SCENARIO_COUNT;
         ++candidate) {
        /* Negative control needs a late-mount case that must reject writes. */
        if (argc > 1 && candidate != FIXTURE_FOREIGN_SELECTED)
            continue;
        failures += check_case((enum fixture_scenario)candidate);
    }
    assert(nftw(fixture_proc_root, fixture_remove_proc_entry, 16,
                FTW_DEPTH | FTW_PHYS) == 0);
    if (failures)
        return 1;
    printf("PASS: production primary-start visible admission checks (%d cases; "
           "post-snapshot probes are explicitly UNPROVEN)\n",
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
    production_defines = '\n'.join(production_define(source, name) for name in (
        "SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES",
        "SWAPZ_PRIMARY_SWAP_ROWS_MAX",
        "SWAPZ_PRIMARY_VISIBLE_PIDS_MAX",
        "SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES",
        "SWAPZ_PRIMARY_STATE_RECORD_MAX",
        "SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT",
    ))
    swap_function = production_function(source, "swapz_primary_swap_device_active")
    target_helpers = '\n\n'.join(production_function(source, name) for name in (
        "swapz_primary_partuuid_normalize",
        "swapz_primary_target_valid",
        "swapz_primary_target_identity_equal",
    ))
    target_open = production_function(source, "swapz_primary_target_open_exclusive")
    mount_reader = '\n\n'.join(production_function(source, name) for name in (
        "swapz_primary_proc_entry_is_pid",
        "swapz_primary_mountinfo_read_fd",
        "swapz_primary_mountinfo_exit_error",
        "swapz_primary_read_mount_facts",
    ))
    coordinator = production_function(source, "swapz_primary_start_prepared")
    if re.search(r'\bswapz_primary_release_partition_owner_at\s*\(', coordinator):
        raise AssertionError("Primary start must not consume a prepared claim")
    if mutant:
        coordinator = omit_final_revalidation(coordinator)
    unit = HARNESS.replace('@@PRODUCTION_DEFINES@@', production_defines).replace(
        '@@PARSERS@@', parser_source).replace(
        '@@MOUNT_READER@@', mount_reader).replace(
        '@@SWAP_FUNCTION@@', swap_function).replace(
        '@@TARGET_HELPERS@@', target_helpers).replace(
        '@@TARGET_OPEN_FUNCTION@@', target_open).replace(
        '@@START_FUNCTION@@', coordinator)
    if "@@" in unit:
        raise AssertionError("Unexpanded harness placeholder")
    c_path = workdir / ("mutant.c" if mutant else "production.c")
    binary = workdir / ("mutant" if mutant else "production")
    c_path.write_text(unit)
    compilation = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-fno-omit-frame-pointer",
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
        expected_mutations = "header_write=1 mapper=1 mkswap=1 swapon=1"
        if mutant.returncode != 1 or expected_mutations not in mutant.stderr:
            print("FAIL: omission of final recheck did not expose all intercepted mutations",
                  file=sys.stderr)
            print(mutant.stdout + mutant.stderr, file=sys.stderr, end="")
            return 1
        print("PASS: negative control exposes all intercepted destructive boundaries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
