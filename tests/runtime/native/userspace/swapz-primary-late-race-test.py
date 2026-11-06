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
import os
import re
import shutil
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


def production_struct(source: str, name: str) -> str:
    """Return the exact source type rather than a copied test model."""
    opening = f"struct {name} {{"
    if source.count(opening) != 1:
        raise AssertionError(f"Expected one production type for {name}")
    first = source.index(opening)
    ending = source.index("\n};", first) + len("\n};")
    return source[first:ending]


def production_define(source: str, name: str) -> str:
    """Return one simple production #define verbatim."""
    matches = re.findall(
        rf'^#define[ \t]+{re.escape(name)}[ \t]+[^\n]+$', source, re.M)
    if len(matches) != 1:
        raise AssertionError(f"Expected one production define for {name}")
    return matches[0]


SELECTOR_FUNCTIONS = (
    "swapz_primary_partuuid_normalize", "swapz_primary_partuuid_valid",
    "swapz_primary_target_config_parse",
    "swapz_primary_selector_metadata_matches",
    "swapz_primary_selector_read_stable_fd",
    "swapz_primary_selector_identity_still_live",
    "swapz_primary_selector_admission_open",
    "swapz_primary_selector_admission_close",
    "swapz_primary_selector_admission_still_live",
    "swapz_primary_selector_admission_read_partuuid",
    "swapz_primary_target_config_read",
)


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


def restore_independent_selector_reread(function: str) -> str:
    """Negative control: regress the final pinned-FD content proof to a pathname reread."""
    original = (
        "swapz_primary_selector_admission_read_partuuid(\n"
        "\t\t    &selector_admission, prewrite_partuuid)")
    if function.count(original) != 1:
        raise AssertionError("Expected one pinned selector-content read")
    return function.replace(
        original, "swapz_primary_target_config_read(prewrite_partuuid)")


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
#define FIXTURE_DIAGNOSTIC_BYTES 2048U

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

/*
 * Exercise the actual protected-selector reader in this coordinator fixture,
 * not a copied parser or an in-memory selector model. Rootless mode changes
 * only the expected owner to this process and keeps every path private.
 */
static char fixture_config_base[PATH_MAX];
static void (*swapz_primary_rootless_selector_before_revalidation)(void);
#define SWAPZ_PRIMARY_ROOTLESS_TEST 1
#define SWAPZ_PRIMARY_CONFIG_BASE fixture_config_base
@@SELECTOR_ADMISSION_TYPE@@
@@SELECTOR_FUNCTIONS@@
#undef SWAPZ_PRIMARY_CONFIG_BASE
#undef SWAPZ_PRIMARY_ROOTLESS_TEST

enum fixture_scenario {
    FIXTURE_CLEAN, FIXTURE_SELECTED_MOUNT, FIXTURE_PARENT_MOUNT,
    FIXTURE_FOREIGN_SELECTED, FIXTURE_FOREIGN_PARENT,
    FIXTURE_FOREIGN_SELECTED_INITIAL, FIXTURE_PID_REPLACED_SELECTED,
    FIXTURE_PID_NAMESPACE_REPLACED_SELECTED,
    FIXTURE_SELECTED_SWAPFILE, FIXTURE_PARENT_SWAPFILE,
    FIXTURE_SELECTED_SWAP_PARTITION, FIXTURE_UNRELATED_SIBLING,
    FIXTURE_DISAPPEARED_PID, FIXTURE_PID_STILL_PRESENT,
    FIXTURE_REMOTE_EACCES, FIXTURE_REMOTE_EIO, FIXTURE_REMOTE_CLOSE_EIO,
    FIXTURE_MALFORMED,
    FIXTURE_EMPTY, FIXTURE_LOCAL_MALFORMED, FIXTURE_PARENT_SUBSTITUTED,
    FIXTURE_ROOT_SUBSTITUTED, FIXTURE_ROOT_ON_SELECTED_PARENT,
    FIXTURE_ROOT_SHARED_STABLE, FIXTURE_HOLDER_LATE,
    FIXTURE_SWAP_INVENTORY_MALFORMED, FIXTURE_SWAP_STAT_EACCES,
    FIXTURE_DM_INITIAL, FIXTURE_SWAPS_INITIAL, FIXTURE_ROOT_INITIAL,
    FIXTURE_HOLDER_INITIAL, FIXTURE_UNRELATED_SWAPFILE,
    FIXTURE_WRONG_MOUNT_DEVICE, FIXTURE_REMOTE_OVERSIZED,
    FIXTURE_LOCAL_OVERSIZED, FIXTURE_PID_INVENTORY_EACCES,
    FIXTURE_PID_INVENTORY_EIO, FIXTURE_PID_INVENTORY_READDIR_EIO,
    FIXTURE_SYMLINK_MOUNTINFO, FIXTURE_WRONG_TARGET_OPEN,
    FIXTURE_WRONG_TARGET_GEOMETRY, FIXTURE_TRUNCATED_REMOTE, FIXTURE_TRUNCATED_LOCAL,
    FIXTURE_NAMESPACE_STAT_EACCES, FIXTURE_STALE_PARTUUID,
    FIXTURE_POST_SNAPSHOT_MOUNT, FIXTURE_POST_SNAPSHOT_SWAPON,
    FIXTURE_POST_SNAPSHOT_INVENTORY_EACCES,
    FIXTURE_LIVE_SELECTOR_CHANGED_AFTER_ADMISSION,
    FIXTURE_LIVE_SELECTOR_INODE_REPLACED_AFTER_ADMISSION,
    FIXTURE_LIVE_CONFIG_DIRECTORY_REPLACED_AFTER_ADMISSION,
    FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION,
    FIXTURE_SELECTOR_CROSS_READ_ABA,
    FIXTURE_TARGET_IDENTITY_RACED_RESTORED,
    FIXTURE_SCENARIO_COUNT
};
static const char *const scenario_names[] = {
    "safe control", "selected mount late", "selected parent mount late",
    "foreign selected mount late", "foreign parent mount late",
    "foreign selected mount at initial admission",
    "replacement PID mounts selected partition late",
    "same PID namespace identity replaced with selected mount late",
    "selected swapfile late", "parent swapfile late",
    "selected swap partition late", "unrelated sibling late",
    "disappeared PID late", "PID still present late",
    "remote EACCES late", "remote EIO late", "remote close EIO late",
    "malformed remote late",
    "empty remote late", "malformed self late", "parent substitution late",
    "root parent substitution late", "root on target parent late",
    "root stably shares target parent", "holder appears late",
    "malformed swap inventory late", "swapfile stat EACCES late",
    "DM initially active", "selected swap initially active",
    "root initially on selected parent", "holder initially active",
    "unrelated /swapfile late", "wrong-device mount alias late",
    "oversized remote mountinfo late", "oversized local mountinfo late",
    "unreadable PID inventory late", "PID inventory I/O failure late",
    "PID inventory readdir I/O failure late", "symlink mountinfo late",
    "selected device identity changed before exclusive open",
    "selected device geometry changed before exclusive open",
    "truncated remote mountinfo late", "truncated local mountinfo late",
    "inaccessible PID namespace late", "stale PARTUUID on exclusive open",
    "new mount immediately after final safe inventory",
    "new swap immediately after final safe inventory",
    "PID inventory becomes unreadable after final safe inventory",
    "protected selected PARTUUID changes after initial admission",
    "protected selector inode changes after initial admission",
    "protected configuration-directory inode changes after initial admission",
    "selected target geometry changes after initial admission",
    "transient ancestor path selects different target then original tree returns",
    "target identity changes at last-use inspection then is restored"
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
static unsigned int owner_release_calls;
static unsigned int starting_state_writes;
static unsigned int active_state_writes;
static unsigned int active_inventory_reads;
static unsigned int mount_conflict_observations;
static unsigned int late_mount_conflict_observations;
static unsigned int namespace_identity_initial_reads;
static unsigned int namespace_identity_late_reads;
static dev_t namespace_identity_initial_device;
static dev_t namespace_identity_late_device;
static ino_t namespace_identity_initial_inode;
static ino_t namespace_identity_late_inode;
static int post_snapshot_injected;
static unsigned int fixture_selector_reads;
static unsigned int fixture_selector_aba_windows;
static unsigned int fixture_geometry_last_use_checks;
static unsigned int fixture_target_identity_last_use_checks;
static struct stat fixture_initial_selector_info;
static struct stat fixture_initial_config_info;
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
static const char fixture_self_root[] = "/";
static int fixture_mount_fd = -1;
static int fixture_mount_open_error;
static int fixture_mount_read_error;
static int fixture_mount_close_error;
static int fixture_inventory_error;
static int fixture_inventory_readdir_error;
static int fixture_inventory_seen_foreign_pid;
static DIR *fixture_proc_directory;
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

static void fixture_inventory_remove_if_present(const char *relative)
{
    char path[PATH_MAX];
    int length = snprintf(path, sizeof(path), "%s/%s", fixture_proc_root, relative);

    assert(length > 0 && (size_t)length < sizeof(path));
    if (unlink(path) < 0)
        assert(errno == ENOENT);
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
    /*
     * A preceding case may have replaced PID 3031 with PID 4040 between
     * admission scans. Restore the private directory before the next case.
     */
    {
        char previous_pid[PATH_MAX];
        char replacement_pid[PATH_MAX];
        int previous_length = snprintf(previous_pid, sizeof(previous_pid),
                                       "%s/3031", fixture_proc_root);
        int replacement_length = snprintf(replacement_pid,
                                          sizeof(replacement_pid),
                                          "%s/4040", fixture_proc_root);

        assert(previous_length > 0 &&
               (size_t)previous_length < sizeof(previous_pid));
        assert(replacement_length > 0 &&
               (size_t)replacement_length < sizeof(replacement_pid));
        if (rename(replacement_pid, previous_pid) < 0)
            assert(errno == ENOENT);
    }
    fixture_inventory_remove_if_present("3031/ns/mnt.previous");
    fixture_mount_fd = -1;
    fixture_mount_open_error = fixture_mount_read_error = 0;
    fixture_mount_close_error = fixture_inventory_error = 0;
    fixture_inventory_readdir_error = fixture_inventory_seen_foreign_pid = 0;
    fixture_proc_directory = NULL;
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
    fixture_inventory_file("self/ns/mnt", "coordinator namespace\n");
    fixture_inventory_file("3031/ns/mnt", "namespace present\n");
}

static void fixture_apply_late_inventory(void)
{
    char path[PATH_MAX];
    char replacement_path[PATH_MAX];
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
    case FIXTURE_PID_REPLACED_SELECTED:
        /* An entirely new visible PID must be scanned on final admission. */
        length = snprintf(path, sizeof(path), "%s/3031", fixture_proc_root);
        assert(length > 0 && (size_t)length < sizeof(path));
        length = snprintf(replacement_path, sizeof(replacement_path),
                          "%s/4040", fixture_proc_root);
        assert(length > 0 && (size_t)length < sizeof(replacement_path));
        assert(rename(path, replacement_path) == 0);
        fixture_inventory_file("4040/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
        break;
    case FIXTURE_PID_NAMESPACE_REPLACED_SELECTED:
        /*
         * Keep the numeric PID but replace its namespace identity. Retain the
         * old inode under a private name so the recreated marker cannot reuse
         * that inode during this deterministic fixture.
         */
        length = snprintf(path, sizeof(path), "%s/3031/ns/mnt", fixture_proc_root);
        assert(length > 0 && (size_t)length < sizeof(path));
        length = snprintf(replacement_path, sizeof(replacement_path),
                          "%s/3031/ns/mnt.previous", fixture_proc_root);
        assert(length > 0 && (size_t)length < sizeof(replacement_path));
        assert(rename(path, replacement_path) == 0);
        fixture_inventory_file("3031/ns/mnt", "replacement namespace\n");
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
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
    case FIXTURE_REMOTE_CLOSE_EIO:
        fixture_mount_close_error = EIO;
        break;
    case FIXTURE_PID_INVENTORY_EACCES:
        fixture_inventory_error = EACCES;
        break;
    case FIXTURE_PID_INVENTORY_EIO:
        fixture_inventory_error = EIO;
        break;
    case FIXTURE_PID_INVENTORY_READDIR_EIO:
        fixture_inventory_seen_foreign_pid = 0;
        fixture_inventory_readdir_error = EIO;
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
    int remote = !strcmp(path, "/proc/3031/mountinfo") ||
                 !strcmp(path, "/proc/4040/mountinfo");

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
    int is_remote = fd == fixture_mount_fd;
    int result;

    if (is_remote)
        fixture_mount_fd = -1;
    result = close(fd);
    if (result < 0)
        return result;
    if (is_remote && fixture_mount_close_error) {
        errno = fixture_mount_close_error;
        return -1;
    }
    return 0;
}

static DIR *fixture_proc_opendir(const char *path)
{
    char converted[PATH_MAX];
    DIR *directory;

    if (!strcmp(path, "/proc") && fixture_inventory_error) {
        errno = fixture_inventory_error;
        return NULL;
    }
    directory = opendir(fixture_proc_path(path, converted));
    if (directory && !strcmp(path, "/proc"))
        fixture_proc_directory = directory;
    return directory;
}

static struct dirent *fixture_proc_readdir(DIR *directory)
{
    struct dirent *entry;

    if (directory == fixture_proc_directory &&
        fixture_inventory_readdir_error &&
        fixture_inventory_seen_foreign_pid) {
        errno = fixture_inventory_readdir_error;
        return NULL;
    }
    entry = readdir(directory);
    if (entry && directory == fixture_proc_directory &&
        (!strcmp(entry->d_name, "3031") ||
                  !strcmp(entry->d_name, "4040")))
        fixture_inventory_seen_foreign_pid = 1;
    return entry;
}

static int fixture_proc_stat(const char *path, struct stat *info)
{
    char converted[PATH_MAX];
    int result;

    if (late && scenario == FIXTURE_NAMESPACE_STAT_EACCES &&
        !strcmp(path, "/proc/3031/ns/mnt"))
        return fixture_admission_error(EACCES);
    result = stat(fixture_proc_path(path, converted), info);
    if (result == 0 &&
        scenario == FIXTURE_PID_NAMESPACE_REPLACED_SELECTED &&
        !strcmp(path, "/proc/3031/ns/mnt")) {
        if (late) {
            ++namespace_identity_late_reads;
            namespace_identity_late_device = info->st_dev;
            namespace_identity_late_inode = info->st_ino;
        } else {
            ++namespace_identity_initial_reads;
            namespace_identity_initial_device = info->st_dev;
            namespace_identity_initial_inode = info->st_ino;
        }
    }
    return result;
}

static ssize_t fixture_proc_readlink(const char *path, char *buffer,
                                     size_t size)
{
    const char *basename = strrchr(path, '/');
    size_t length;

    if (strncmp(path, "/proc/", sizeof("/proc/") - 1U) || !basename ||
        strcmp(basename, "/root"))
        return readlink(path, buffer, size);
    length = sizeof(fixture_self_root) - 1U;
    if (length > size)
        length = size;
    memcpy(buffer, fixture_self_root, length);
    return (ssize_t)length;
}

#define open(path,flags) fixture_proc_open(path,flags)
#define read(fd,buffer,length) fixture_proc_read(fd,buffer,length)
#define close(fd) fixture_proc_close(fd)
#define opendir(path) fixture_proc_opendir(path)
#define readdir(directory) fixture_proc_readdir(directory)
#define stat(path,info) fixture_proc_stat(path,info)
#define readlink(path,buffer,size) fixture_proc_readlink(path,buffer,size)
#define getpid() ((pid_t)65535)
/* Extracted, unchanged production PID scanner and bounded mountinfo reader. */
@@MOUNT_READER@@
#undef getpid
#undef readlink
#undef stat
#undef readdir
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
    if (result == 0 && facts->target_mounted) {
        ++mount_conflict_observations;
        if (late)
            ++late_mount_conflict_observations;
    }
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
    length = snprintf(path, sizeof(path), "%s/self/ns", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/self/task", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/self/task/65535",
                      fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031/ns", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031/task", fixture_proc_root);
    assert(length > 0 && (size_t)length < sizeof(path));
    assert(mkdir(path, 0700) == 0);
    length = snprintf(path, sizeof(path), "%s/3031/task/3031",
                      fixture_proc_root);
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

static int fixture_selector_race(enum fixture_scenario candidate)
{
    return candidate == FIXTURE_LIVE_SELECTOR_CHANGED_AFTER_ADMISSION ||
           candidate == FIXTURE_LIVE_SELECTOR_INODE_REPLACED_AFTER_ADMISSION ||
           candidate == FIXTURE_LIVE_CONFIG_DIRECTORY_REPLACED_AFTER_ADMISSION ||
           candidate == FIXTURE_SELECTOR_CROSS_READ_ABA;
}

static void fixture_selector_path(char path[PATH_MAX], const char *name)
{
    int length = snprintf(path, PATH_MAX, "%s/%s", fixture_config_base, name);

    assert(length > 0 && length < PATH_MAX);
}

static void fixture_write_selector(const char *partuuid)
{
    char path[PATH_MAX];
    FILE *stream;

    fixture_selector_path(path, "primary-target");
    stream = fopen(path, "wb");
    assert(stream != NULL);
    assert(fprintf(stream, "PARTUUID=%s\n", partuuid) > 0);
    assert(fclose(stream) == 0);
    assert(chmod(path, 0600) == 0);
}

static void fixture_prepare_selector(enum fixture_scenario candidate)
{
    char selector_path[PATH_MAX];
    int length = snprintf(fixture_config_base, sizeof(fixture_config_base),
                          "%s/config-%u", fixture_proc_root,
                          (unsigned int)candidate);

    assert(length > 0 && (size_t)length < sizeof(fixture_config_base));
    assert(mkdir(fixture_config_base, 0700) == 0);
    fixture_write_selector("f13428f6-01");
    fixture_selector_path(selector_path, "primary-target");
    assert(stat(fixture_config_base, &fixture_initial_config_info) == 0);
    assert(stat(selector_path, &fixture_initial_selector_info) == 0);
}

static void fixture_replace_selector(const char *partuuid)
{
    char selector_path[PATH_MAX];
    char retained_path[PATH_MAX];
    struct stat current;

    fixture_selector_path(selector_path, "primary-target");
    fixture_selector_path(retained_path, "primary-target.previous");
    assert(rename(selector_path, retained_path) == 0);
    fixture_write_selector(partuuid);
    assert(stat(selector_path, &current) == 0);
    assert(current.st_dev != fixture_initial_selector_info.st_dev ||
           current.st_ino != fixture_initial_selector_info.st_ino);
}

static void fixture_selector_aba_path(char path[PATH_MAX], const char *suffix)
{
    int length = snprintf(path, PATH_MAX, "%s.%s", fixture_proc_root, suffix);

    assert(length > 0 && length < PATH_MAX);
}

static void fixture_selector_aba_prepare_root(const char *root)
{
    char config_path[PATH_MAX];
    char selector_path[PATH_MAX];
    FILE *stream;
    int length;

    assert(mkdir(root, 0700) == 0);
    length = snprintf(config_path, sizeof(config_path), "%s/config-%u", root,
                      (unsigned int)scenario);
    assert(length > 0 && (size_t)length < sizeof(config_path));
    assert(mkdir(config_path, 0700) == 0);
    length = snprintf(selector_path, sizeof(selector_path), "%s/primary-target",
                      config_path);
    assert(length > 0 && (size_t)length < sizeof(selector_path));
    stream = fopen(selector_path, "wb");
    assert(stream != NULL);
    assert(fputs("PARTUUID=f13428f6-02\n", stream) >= 0);
    assert(fclose(stream) == 0);
    assert(chmod(selector_path, 0600) == 0);
}

static void fixture_selector_aba_enter(
    char retained_root[PATH_MAX], char substitute_root[PATH_MAX])
{
    fixture_selector_aba_path(retained_root, "selector-aba-retained");
    fixture_selector_aba_path(substitute_root, "selector-aba-substitute");
    fixture_selector_aba_prepare_root(substitute_root);
    /*
     * Swap only an ancestor pathname. The admitted config directory and file
     * inodes are untouched, so their ctime/mtime cannot reveal this ABA.
     */
    assert(rename(fixture_proc_root, retained_root) == 0);
    assert(rename(substitute_root, fixture_proc_root) == 0);
}

static void fixture_selector_aba_leave(
    const char retained_root[PATH_MAX],
    const char substitute_root[PATH_MAX])
{
    char selector_path[PATH_MAX];
    struct stat current;

    assert(rename(fixture_proc_root, substitute_root) == 0);
    assert(rename(retained_root, fixture_proc_root) == 0);
    assert(stat(fixture_config_base, &current) == 0);
    assert(current.st_dev == fixture_initial_config_info.st_dev &&
           current.st_ino == fixture_initial_config_info.st_ino);
    fixture_selector_path(selector_path, "primary-target");
    assert(stat(selector_path, &current) == 0);
    assert(current.st_dev == fixture_initial_selector_info.st_dev &&
           current.st_ino == fixture_initial_selector_info.st_ino);
    assert(nftw(substitute_root, fixture_remove_proc_entry, 16,
                FTW_DEPTH | FTW_PHYS) == 0);
}

static void fixture_replace_config_directory(void)
{
    char retained_path[PATH_MAX];
    char selector_path[PATH_MAX];
    struct stat current;
    int length = snprintf(retained_path, sizeof(retained_path), "%s.previous",
                          fixture_config_base);

    assert(length > 0 && (size_t)length < sizeof(retained_path));
    assert(rename(fixture_config_base, retained_path) == 0);
    assert(mkdir(fixture_config_base, 0700) == 0);
    fixture_write_selector("f13428f6-01");
    fixture_selector_path(selector_path, "primary-target");
    assert(stat(fixture_config_base, &current) == 0);
    assert(current.st_dev != fixture_initial_config_info.st_dev ||
           current.st_ino != fixture_initial_config_info.st_ino);
    assert(stat(selector_path, &current) == 0);
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
               scenario == FIXTURE_ROOT_SHARED_STABLE ||
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
 * Count calls while preserving the real production swap admission result.
 * The post-snapshot race itself is injected by the header-write seam below,
 * after the coordinator has completed every final inventory observation.
 */
static int fixture_observed_swap_device_active(dev_t device)
{
    int active = swapz_primary_swap_device_active(device);

    ++active_inventory_reads;
    return active;
}

static int fixture_selector_read(
    char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
    char retained_root[PATH_MAX];
    char substitute_root[PATH_MAX];
    int result;
    int saved_errno;

    ++fixture_selector_reads;
    if (scenario != FIXTURE_SELECTOR_CROSS_READ_ABA)
        return swapz_primary_target_config_read(partuuid);

    /*
     * Present a different valid selector for exactly the independent reader by
     * replacing an ancestor pathname, then restore the original tree before the
     * coordinator's outer identity check. The pinned config/file metadata stays
     * unchanged, which reproduces the cross-read ABA the final FD read closes.
     */
    fixture_selector_aba_enter(retained_root, substitute_root);
    ++fixture_selector_aba_windows;
    result = swapz_primary_target_config_read(partuuid);
    saved_errno = errno;
    fixture_selector_aba_leave(retained_root, substitute_root);
    if (late)
        post_snapshot_injected = 1;
    errno = saved_errno;
    return result;
}

static int fixture_target(struct swapz_primary_target *target)
{
    char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

    if (fixture_selector_read(partuuid) < 0)
        return -1;
    memset(target, 0, sizeof(*target));
    strcpy(target->partuuid, partuuid);
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
    if (scenario == FIXTURE_WRONG_TARGET_GEOMETRY)
        target->device_bytes += 4096U;
    if (scenario == FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION && late) {
        ++fixture_geometry_last_use_checks;
        target->device_bytes += 4096U;
    }
    if (scenario == FIXTURE_TARGET_IDENTITY_RACED_RESTORED && late) {
        ++fixture_target_identity_last_use_checks;
        if (fixture_target_identity_last_use_checks == 1U)
            target->device_minor = 2U;
    }
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
    if (scenario == FIXTURE_LIVE_SELECTOR_CHANGED_AFTER_ADMISSION) {
        /*
         * A previously read selector is not an authorization for a later
         * mutation. Replace the actual protected selector with a different
         * valid PARTUUID after production completed its successful read.
         */
        fixture_replace_selector("f13428f6-02");
        post_snapshot_injected = 1;
    } else if (scenario ==
               FIXTURE_LIVE_SELECTOR_INODE_REPLACED_AFTER_ADMISSION) {
        /* Same bytes, different protected file identity. */
        fixture_replace_selector("f13428f6-01");
        post_snapshot_injected = 1;
    } else if (scenario ==
               FIXTURE_LIVE_CONFIG_DIRECTORY_REPLACED_AFTER_ADMISSION) {
        /* Same selector bytes, different protected directory identity. */
        fixture_replace_config_directory();
        post_snapshot_injected = 1;
    } else if (scenario == FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION) {
        /* The inspected target changes size only after initial admission. */
        post_snapshot_injected = 1;
    } else if (scenario == FIXTURE_TARGET_IDENTITY_RACED_RESTORED) {
        /*
         * The first final inspection observes a different dev_t; the diagnostic
         * inspection observes the admitted target again.
         */
        post_snapshot_injected = 1;
    }
    return 0;
}
static int fixture_header_write(void)
{
    /*
     * This seam is entered only after production's final mount/parent/swap
     * snapshot has returned safe. Inject immediately before the simulated
     * block-zero write, then prove a fresh production inventory can see the
     * change. That exposes the remaining interval without claiming an atomic
     * kernel exclusion barrier.
     */
    if (scenario == FIXTURE_POST_SNAPSHOT_MOUNT) {
        struct swapz_primary_mount_facts facts = {0};

        assert(!post_snapshot_injected);
        post_snapshot_injected = 1;
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /selected rw - ext4 /dev/selected rw\n");
        assert(swapz_primary_read_mount_facts(
            &facts, makedev(8U, 0U)) == 0 && facts.target_mounted);
    } else if (scenario == FIXTURE_POST_SNAPSHOT_SWAPON) {
        assert(!post_snapshot_injected);
        post_snapshot_injected = 1;
        assert(swapz_primary_swap_device_active(makedev(8U, 1U)) == 1);
    } else if (fixture_selector_race(scenario)) {
        if (scenario == FIXTURE_SELECTOR_CROSS_READ_ABA) {
            /*
             * A vulnerable coordinator reaches mutation after the second
             * transient independent-reader window has already restored the
             * admitted pathname. Do not create a third diagnostic ABA window.
             */
            assert(fixture_selector_aba_windows >= 1U);
        } else {
            char current_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

            /*
             * The mutation occurred after one successful production selector
             * read. Perform a diagnostic production reread only after that
             * observation; it never counts as coordinator prevention.
             */
            assert(post_snapshot_injected && fixture_selector_reads == 1U);
            assert(swapz_primary_target_config_read(current_partuuid) == 0);
            if (scenario == FIXTURE_LIVE_SELECTOR_CHANGED_AFTER_ADMISSION)
                assert(strcmp(current_partuuid, selected_target.partuuid) != 0);
            else
                assert(!strcmp(current_partuuid, selected_target.partuuid));
        }
    } else if (scenario == FIXTURE_POST_SNAPSHOT_INVENTORY_EACCES) {
        struct swapz_primary_mount_facts facts = {0};

        /* This becomes unreadable only after final prewrite verification. */
        assert(!post_snapshot_injected);
        post_snapshot_injected = 1;
        fixture_inventory_error = EACCES;
        errno = 0;
        assert(swapz_primary_read_mount_facts(
            &facts, makedev(8U, 0U)) < 0 && errno == EACCES);
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
static int fixture_owner_release(void)
{
    ++owner_release_calls;
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
#define swapz_primary_target_config_read(partuuid) fixture_selector_read(partuuid)
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
#define swapz_primary_state_require_recovery_at(a,b,c,d) \
	((void)(a), (void)(b), (void)(c), (void)(d), ++recovery_marks, 0)
@@RECOVERY_FAILURE_HELPER@@
#define swapz_primary_release_partition_owner_at(...) fixture_owner_release()
#define swapz_primary_swap_device_active(device) fixture_observed_swap_device_active(device)
#define close(fd) 0

/*
 * This fixture isolates the late inventory race. Exact shared-root scope
 * policy is covered by swapz-primary-policy; here the fixture models a stable
 * positive scope if the synthetic root happens to share the target parent.
 */
static int swapz_primary_shared_root_scope_record_live(
    const struct swapz_primary_target *target, dev_t root_device,
    dev_t target_parent, dev_t root_parent, dev_t recovery_parent,
    int target_fd, char scope_sha256[65])
{
    (void)target;
    (void)root_device;
    (void)target_parent;
    (void)root_parent;
    (void)recovery_parent;
    (void)target_fd;
    if (!scope_sha256) {
        errno = EINVAL;
        return -1;
    }
    if (scenario != FIXTURE_ROOT_SHARED_STABLE) {
        errno = EPERM;
        return -1;
    }
    memset(scope_sha256, 'a', 64U);
    scope_sha256[64] = '\0';
    return 0;
}

/* The actual production coordinator function is inserted verbatim. */
#define SWAPZ_PRIMARY_CONFIG_BASE fixture_config_base
/* Also intercept the late failed-identity classification inspection. */
#define swapz_primary_target_inspect(partuuid,target) \
    fixture_target_inspect(partuuid,target)
@@START_FUNCTION@@
#undef swapz_primary_target_inspect
#undef SWAPZ_PRIMARY_CONFIG_BASE
#undef swapz_primary_target_config_read
#undef close
#undef swapz_primary_swap_device_active
#undef swapz_primary_release_partition_owner_at

static int check_case(enum fixture_scenario candidate)
{
    int expected_safe;
    int expected_error = 0;
    int result;
    int result_errno;
    int saved_stderr;
    int gap_probe;
    int expected_mount_conflict;
    int expected_late_mount_conflict;
    char diagnostic[FIXTURE_DIAGNOSTIC_BYTES] = {0};
    char expected_diagnostic[FIXTURE_DIAGNOSTIC_BYTES];
    size_t diagnostic_length;
    FILE *diagnostic_stream;
    unsigned int writes;
    scenario = candidate;
    late = 0;
    memset(&swapz_primary_selected_target, 0,
           sizeof(swapz_primary_selected_target));
    admission_reads = prewrite_reads = active_inventory_reads = 0U;
    mount_conflict_observations = late_mount_conflict_observations = 0U;
    namespace_identity_initial_reads = namespace_identity_late_reads = 0U;
    namespace_identity_initial_device = namespace_identity_late_device = 0;
    namespace_identity_initial_inode = namespace_identity_late_inode = 0;
    post_snapshot_injected = 0;
    fixture_selector_reads = fixture_selector_aba_windows = 0U;
    fixture_geometry_last_use_checks = fixture_target_identity_last_use_checks = 0U;
    fixture_prepare_selector(candidate);
    fixture_reset_mount_inventory();
    if (candidate == FIXTURE_FOREIGN_SELECTED_INITIAL)
        fixture_inventory_file("3031/mountinfo",
            "36 25 259:9 / / rw - ext4 /dev/other rw\n"
            "37 36 8:1 / /mnt/selected rw - ext4 /dev/sda1 rw\n");
    header_writes = mapper_mutations = mkswap_calls = swapon_calls = 0U;
    module_loads = recovery_marks = owner_release_calls = 0U;
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
    if (ferror(diagnostic_stream) || !feof(diagnostic_stream)) {
        fprintf(stderr,
                "FAIL: %s: incomplete diagnostic capture bytes=%zu "
                "limit=%zu read_error=%d eof=%d\n",
                scenario_names[candidate], diagnostic_length,
                sizeof(diagnostic) - 1U, ferror(diagnostic_stream),
                feof(diagnostic_stream));
        assert(fclose(diagnostic_stream) == 0);
        return 1;
    }
    assert(fclose(diagnostic_stream) == 0);
    diagnostic[diagnostic_length] = '\0';
    gap_probe = candidate == FIXTURE_POST_SNAPSHOT_MOUNT ||
                candidate == FIXTURE_POST_SNAPSHOT_SWAPON ||
                candidate == FIXTURE_POST_SNAPSHOT_INVENTORY_EACCES;
    expected_mount_conflict =
        candidate == FIXTURE_SELECTED_MOUNT ||
        candidate == FIXTURE_PARENT_MOUNT ||
        candidate == FIXTURE_FOREIGN_SELECTED ||
        candidate == FIXTURE_FOREIGN_PARENT ||
        candidate == FIXTURE_FOREIGN_SELECTED_INITIAL ||
        candidate == FIXTURE_PID_REPLACED_SELECTED ||
        candidate == FIXTURE_PID_NAMESPACE_REPLACED_SELECTED;
    expected_late_mount_conflict =
        expected_mount_conflict &&
        candidate != FIXTURE_FOREIGN_SELECTED_INITIAL;
    expected_safe = candidate == FIXTURE_CLEAN ||
        candidate == FIXTURE_ROOT_SHARED_STABLE ||
        candidate == FIXTURE_UNRELATED_SIBLING ||
        candidate == FIXTURE_UNRELATED_SWAPFILE ||
        candidate == FIXTURE_WRONG_MOUNT_DEVICE ||
        candidate == FIXTURE_DISAPPEARED_PID;
    switch (candidate) {
    case FIXTURE_SELECTED_MOUNT:
    case FIXTURE_PARENT_MOUNT:
    case FIXTURE_FOREIGN_SELECTED:
    case FIXTURE_FOREIGN_PARENT:
    case FIXTURE_PID_REPLACED_SELECTED:
    case FIXTURE_PID_NAMESPACE_REPLACED_SELECTED:
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
    case FIXTURE_REMOTE_CLOSE_EIO:
    case FIXTURE_PID_INVENTORY_EIO:
    case FIXTURE_PID_INVENTORY_READDIR_EIO:
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
    case FIXTURE_WRONG_TARGET_GEOMETRY:
    case FIXTURE_STALE_PARTUUID:
        expected_error = ESTALE;
        break;
    case FIXTURE_ROOT_INITIAL:
    case FIXTURE_FOREIGN_SELECTED_INITIAL:
        expected_error = EPERM;
        break;
    case FIXTURE_REMOTE_OVERSIZED:
    case FIXTURE_LOCAL_OVERSIZED:
        expected_error = EOVERFLOW;
        break;
    case FIXTURE_SYMLINK_MOUNTINFO:
        expected_error = ELOOP;
        break;
    case FIXTURE_LIVE_SELECTOR_CHANGED_AFTER_ADMISSION:
    case FIXTURE_LIVE_SELECTOR_INODE_REPLACED_AFTER_ADMISSION:
    case FIXTURE_LIVE_CONFIG_DIRECTORY_REPLACED_AFTER_ADMISSION:
    case FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION:
    case FIXTURE_SELECTOR_CROSS_READ_ABA:
    case FIXTURE_TARGET_IDENTITY_RACED_RESTORED:
        /* These mutation controls have their own explicit last-use verdict. */
        break;
    default:
        assert(expected_safe || gap_probe);
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

    if (fixture_selector_race(candidate) ||
        candidate == FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION ||
        candidate == FIXTURE_TARGET_IDENTITY_RACED_RESTORED) {
        /*
         * These mutation-sensitive controls never label a successful stale
         * selector or target snapshot SAFE. A refusal is valid only after the
         * source-extracted production last-use check and before mutation.
         */
        int geometry_drift =
            candidate == FIXTURE_TARGET_GEOMETRY_CHANGED_AFTER_ADMISSION;
        int selector_aba = candidate == FIXTURE_SELECTOR_CROSS_READ_ABA;
        int target_restored =
            candidate == FIXTURE_TARGET_IDENTITY_RACED_RESTORED;
        const char *expected_phase = geometry_drift || target_restored ?
            "phase=prewrite-target-identity" :
            "phase=prewrite-protected-selector-identity";
        const char *expected_mismatch = geometry_drift ?
            "observed=target-geometry-changed" :
            target_restored ?
                "observed=target-identity-raced-or-restored" :
            selector_aba ?
                "observed=selected-target-not-bound-to-admitted-selector" :
            candidate == FIXTURE_LIVE_CONFIG_DIRECTORY_REPLACED_AFTER_ADMISSION ?
                "observed=configuration-directory-identity-changed" :
                "observed=selector-file-identity-changed";
        const char *expected_detail = geometry_drift || target_restored ?
            "expected=unchanged-admitted-target-partition-and-geometry" :
            selector_aba ?
                "expected=manifest-target-matches-admitted-selector-content" :
                "expected=unchanged-admitted-selector-directory-and-file";
        char expected_errno[48];
        int expected_length = snprintf(expected_errno, sizeof(expected_errno),
                                       "original_errno=%d", ESTALE);
        int race_evidence = selector_aba ?
            fixture_selector_reads == 1U && fixture_selector_aba_windows == 1U :
            target_restored ?
                post_snapshot_injected == 1 &&
                fixture_target_identity_last_use_checks >= 2U :
            geometry_drift ?
                post_snapshot_injected == 1 &&
                fixture_geometry_last_use_checks >= 1U :
                post_snapshot_injected == 1 && fixture_selector_reads >= 1U;
        int refusal = result < 0 && result_errno == ESTALE &&
            race_evidence &&
            header_writes == 0U && mapper_mutations == 0U &&
            mkswap_calls == 0U && swapon_calls == 0U &&
            module_loads == 0U && starting_state_writes == 1U &&
            active_state_writes == 0U && recovery_marks == 1U &&
            owner_release_calls == 0U &&
            strstr(diagnostic, expected_phase) != NULL &&
            strstr(diagnostic, expected_detail) != NULL &&
            strstr(diagnostic, expected_mismatch) != NULL &&
            expected_length > 0 && (size_t)expected_length < sizeof(expected_errno) &&
            strstr(diagnostic, expected_errno) != NULL &&
            strstr(diagnostic, "retained_state=STARTING_PENDING_RECOVERY_UPDATE") != NULL &&
            !strstr(diagnostic, "f13428f6") &&
            !strstr(diagnostic, "0123456789abcdef");
        if (!refusal) {
            fprintf(stderr, "FAIL: phase=post-admission-last-use "
                    "expected=ESTALE-and-zero-mutation "
                    "observed=%s first_errno=%d mutations=%u "
                    "selector_reads=%u selector_aba=%u geometry_rechecks=%u "
                    "target_identity_rechecks=%u case=%d\n",
                    result == 0 ? "stale-selection-reached-mutation" :
                                  "incorrect-refusal",
                    result_errno, writes, fixture_selector_reads,
                    fixture_selector_aba_windows,
                    fixture_geometry_last_use_checks,
                    fixture_target_identity_last_use_checks, candidate);
            return 1;
        }
        printf("DENY: phase=post-admission-last-use case=%d "
               "observed=ESTALE first_errno=%d prevented=all mutations=0\n",
               candidate, result_errno);
        return 0;
    }
    if (gap_probe) {
        /* The injected mount/swap is detected by a diagnostic production
         * reread, but no atomic kernel exclusion is established by this test. */
        if (result != 0 || !post_snapshot_injected ||
            admission_reads != 2U || prewrite_reads != 1U ||
            active_inventory_reads != 4U || writes != 4U ||
            starting_state_writes != 1U || active_state_writes != 1U ||
            recovery_marks != 0U || owner_release_calls != 0U ||
            mount_conflict_observations != 0U ||
            late_mount_conflict_observations != 0U ||
            diagnostic_length != 0U) {
            fprintf(stderr, "FAIL: %s: post-snapshot gap result=%d "
                    "injected=%d reads=%u swap_reads=%u mutations=%u "
                    "diagnostic_bytes=%zu\n", scenario_names[candidate], result,
                    post_snapshot_injected, admission_reads,
                    active_inventory_reads, writes, diagnostic_length);
            return 1;
        }
        printf("UNPROVEN: %s phase=post-final-snapshot errno=%d "
               "prevented=none mutations=4; a read-only scan cannot "
               "exclude changes after it returns\n",
               scenario_names[candidate],
               candidate == FIXTURE_POST_SNAPSHOT_INVENTORY_EACCES
                   ? EACCES : 0);
        return 0;
    }
    if (expected_safe) {
        if (result != 0 || admission_reads != 2U || prewrite_reads != 1U ||
            header_writes != 1U || mapper_mutations != 1U ||
            mkswap_calls != 1U || swapon_calls != 1U ||
            starting_state_writes != 1U || active_state_writes != 1U ||
            recovery_marks != 0U || owner_release_calls != 0U ||
            mount_conflict_observations != 0U ||
            late_mount_conflict_observations != 0U ||
            diagnostic_length != 0U) {
            fprintf(stderr, "FAIL: %s: safe result=%d initial+late=%u "
                    "late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, admission_reads,
                    prewrite_reads, header_writes, mapper_mutations,
                    mkswap_calls, swapon_calls);
            return 1;
        }
    } else {
        const char *phase = late ? "header-write" : "admission";
        size_t expected_diagnostic_length;
        int expected_length;

        switch (candidate) {
        case FIXTURE_FOREIGN_SELECTED_INITIAL:
            phase = "cross-namespace-mount-inventory";
            break;
        case FIXTURE_ROOT_INITIAL:
            phase = "shared-root-parent-authorization-record";
            break;
        case FIXTURE_PARENT_SUBSTITUTED:
            phase = "prewrite-target-parent-identity";
            break;
        case FIXTURE_ROOT_SUBSTITUTED:
        case FIXTURE_ROOT_ON_SELECTED_PARENT:
            phase = "prewrite-root-parent-identity";
            break;
        case FIXTURE_DM_INITIAL:
            phase = "module-mapper-inventory";
            break;
        case FIXTURE_SWAPS_INITIAL:
            phase = "target-swap-inventory";
            break;
        case FIXTURE_HOLDER_INITIAL:
        case FIXTURE_WRONG_TARGET_OPEN:
        case FIXTURE_WRONG_TARGET_GEOMETRY:
        case FIXTURE_STALE_PARTUUID:
            phase = "target-exclusive-open";
            break;
        default:
            break;
        }
        /* Every refusal case here follows READY state and manifest proof. */
        expected_length = snprintf(expected_diagnostic,
            sizeof(expected_diagnostic),
            "PRIMARY_START=FAILED phase=%s errno=%d error=%s "
            "original_errno=%d persistence_boundary=none "
            "durable=OBSERVED mapper=UNOBSERVED swap=UNOBSERVED\n",
            phase, expected_error, strerror(expected_error), expected_error);

        assert(expected_length > 0 &&
               (size_t)expected_length < sizeof(expected_diagnostic));
        expected_diagnostic_length = (size_t)expected_length;
        if (candidate == FIXTURE_ROOT_INITIAL ||
            candidate == FIXTURE_PARENT_SUBSTITUTED ||
            candidate == FIXTURE_ROOT_SUBSTITUTED ||
            candidate == FIXTURE_ROOT_ON_SELECTED_PARENT) {
            const char *expected_class =
                candidate == FIXTURE_ROOT_INITIAL ?
                    "exact-host-root-target-parent-layout-record" :
                candidate == FIXTURE_PARENT_SUBSTITUTED ?
                    "unchanged-admitted-target-parent-device" :
                    "unchanged-admitted-root-parent-device";
            const char *observed_class =
                candidate == FIXTURE_ROOT_INITIAL ?
                    "missing-mismatched-or-unverifiable" :
                candidate == FIXTURE_PARENT_SUBSTITUTED ?
                    "target-parent-device-changed" :
                    "root-parent-device-changed";
            int detail_length = snprintf(
                expected_diagnostic + expected_diagnostic_length,
                sizeof(expected_diagnostic) - expected_diagnostic_length,
                "PRIMARY_START=ADMISSION_DETAIL phase=%s expected=%s "
                "observed=%s errno=%d original_errno=%d "
                "persistence_boundary=none durable=OBSERVED "
                "mapper=UNOBSERVED swap=UNOBSERVED retained_state=%s "
                "target_unchanged=true\n",
                phase, expected_class,
                observed_class, expected_error, expected_error,
                late ? "STARTING_PENDING_RECOVERY_UPDATE" : "READY");

            assert(detail_length > 0 &&
                   (size_t)detail_length <
                       sizeof(expected_diagnostic) -
                           expected_diagnostic_length);
            expected_diagnostic_length += (size_t)detail_length;
        }
        if (result == 0 || result_errno != expected_error ||
            diagnostic_length == 0U ||
            diagnostic_length != expected_diagnostic_length ||
            memcmp(diagnostic, expected_diagnostic,
                   expected_diagnostic_length) != 0 ||
            diagnostic[diagnostic_length - 1U] != '\n' ||
            strstr(diagnostic, "run_id") ||
            strstr(diagnostic, "0123456789abcdef") ||
            strstr(diagnostic, "secret") || strstr(diagnostic, "token") ||
            strstr(diagnostic, "passphrase") ||
            strstr(diagnostic, "/proc/") ||
            mount_conflict_observations !=
                (unsigned int)expected_mount_conflict ||
            late_mount_conflict_observations !=
                (unsigned int)expected_late_mount_conflict ||
            (candidate == FIXTURE_PID_NAMESPACE_REPLACED_SELECTED &&
             (namespace_identity_initial_reads == 0U ||
              namespace_identity_late_reads == 0U ||
              (namespace_identity_initial_device ==
                   namespace_identity_late_device &&
               namespace_identity_initial_inode ==
                   namespace_identity_late_inode))) ||
            writes || module_loads ||
            starting_state_writes != (unsigned int)late ||
            active_state_writes != 0U ||
            recovery_marks != (unsigned int)late ||
            owner_release_calls != 0U ||
            ((candidate == FIXTURE_DM_INITIAL ||
              candidate == FIXTURE_SWAPS_INITIAL ||
              candidate == FIXTURE_ROOT_INITIAL ||
              candidate == FIXTURE_HOLDER_INITIAL ||
              candidate == FIXTURE_WRONG_TARGET_OPEN ||
              candidate == FIXTURE_WRONG_TARGET_GEOMETRY ||
              candidate == FIXTURE_STALE_PARTUUID ||
              candidate == FIXTURE_PARENT_SUBSTITUTED ||
              candidate == FIXTURE_HOLDER_LATE ||
              candidate == FIXTURE_FOREIGN_SELECTED_INITIAL) ?
                 prewrite_reads != 0U : prewrite_reads != 1U)) {
            fprintf(stderr, "FAIL: %s: refusal result=%d errno=%d expected=%d "
                    "initial+late=%u late=%u header_write=%u mapper=%u mkswap=%u swapon=%u\n",
                    scenario_names[candidate], result, result_errno, expected_error,
                    admission_reads, prewrite_reads, header_writes,
                    mapper_mutations, mkswap_calls, swapon_calls);
            fprintf(stderr,
                    "FAIL: redacted diagnostic bytes=%zu mount_conflicts=%u "
                    "late_mount_conflicts=%u namespace_reads=%u/%u\n",
                    diagnostic_length, mount_conflict_observations,
                    late_mount_conflict_observations,
                    namespace_identity_initial_reads,
                    namespace_identity_late_reads);
            return 1;
        }
        printf("DENY: %s phase=%s category=\"%s\" errno=%d "
               "evidence=%s claim=retained state=%s "
               "prevented=header-write,mapper,mkswap,swapon mutations=0\n",
               scenario_names[candidate], phase, scenario_names[candidate],
               expected_error,
               expected_mount_conflict
                   ? "mount-facts-target-mounted" : "phase-errno-zero-mutation",
               late ? "recovery-requested" : "READY");
    }
    return 0;
}

int main(int argc, char **argv)
{
    int failures = 0;
    int candidate;
    int selected_case = -1;

    if (argc > 1) {
        if (!strcmp(argv[1], "negative-control"))
            selected_case = FIXTURE_FOREIGN_SELECTED;
        else if (!strcmp(argv[1], "selector-aba-negative-control"))
            selected_case = FIXTURE_SELECTOR_CROSS_READ_ABA;
        else
            return 2;
    }
    fixture_create_proc_root();
    for (candidate = FIXTURE_CLEAN; candidate < FIXTURE_SCENARIO_COUNT;
         ++candidate) {
        if (selected_case >= 0 && candidate != selected_case)
            continue;
        failures += check_case((enum fixture_scenario)candidate);
    }
    assert(nftw(fixture_proc_root, fixture_remove_proc_entry, 16,
                FTW_DEPTH | FTW_PHYS) == 0);
    if (failures)
        return 1;
    printf("PASS: production primary-start visible admission checks (%d cases; "
           "post-snapshot probes are explicitly UNPROVEN)\n",
           selected_case >= 0 ? 1 : FIXTURE_SCENARIO_COUNT);
    return 0;
}
'''


# A second fixture runs real selector-path and final opened-FD functions.
# It uses only user-owned temporary regular files, never a block or swap device.
LAST_USE_HARNESS = r'''
#define _GNU_SOURCE
#define SWAPZ_PRIMARY_ROOTLESS_TEST 1
#include <assert.h>
#include <ctype.h>
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
#define SWAPZ_PRIMARY_BLOCK_BYTES 4096U

static char fixture_config_base[PATH_MAX];
static void (*swapz_primary_rootless_selector_before_revalidation)(void);
#define SWAPZ_PRIMARY_CONFIG_BASE fixture_config_base
@@SELECTOR_ADMISSION_TYPE@@
@@SELECTOR_FUNCTIONS@@
#undef SWAPZ_PRIMARY_CONFIG_BASE

static struct swapz_primary_target swapz_primary_selected_target;
@@TARGET_VALID_FUNCTIONS@@
static char fixture_alias_path[PATH_MAX];
static char fixture_substitute_path[PATH_MAX];
static char fixture_retained_alias_path[PATH_MAX];
static int fixture_swap_alias_on_open;
static unsigned int fixture_alias_switches;

static int fixture_racing_open(const char *path, int flags)
{
    if (fixture_swap_alias_on_open && !strcmp(path, fixture_alias_path)) {
        fixture_swap_alias_on_open = 0;
        assert(rename(fixture_alias_path, fixture_retained_alias_path) == 0);
        assert(link(fixture_substitute_path, fixture_alias_path) == 0);
        ++fixture_alias_switches;
    }
    return open(path, flags);
}
#define open(path,flags) fixture_racing_open(path,flags)
@@TARGET_OPEN_FUNCTION@@
#undef open
@@HEADER_FUNCTIONS@@

static char fixture_root[PATH_MAX];
static char fixture_selector_path[PATH_MAX];
static char fixture_retained_selector_path[PATH_MAX];
static char fixture_retained_directory_path[PATH_MAX];
static unsigned int fixture_selector_hooks;
static int fixture_selector_race;

enum selector_race {
    SELECTOR_UNCHANGED, SELECTOR_SAME_BYTES_REPLACED,
    SELECTOR_DIFFERENT_BYTES_REPLACED, SELECTOR_DIRECTORY_REPLACED,
    SELECTOR_DIRECTORY_REMOVED, SELECTOR_SYMLINK_REPLACED,
    SELECTOR_FRESH_AFTER_SUCCESS, SELECTOR_RACE_COUNT
};

static void fixture_join(char result[PATH_MAX], const char *base,
                         const char *component)
{
    int length = snprintf(result, PATH_MAX, "%s/%s", base, component);

    assert(length > 0 && length < PATH_MAX);
}

static void fixture_write_record(const char *path, const char *record)
{
    FILE *stream = fopen(path, "wb");

    assert(stream != NULL);
    assert(fputs(record, stream) >= 0);
    assert(fclose(stream) == 0);
}

static void fixture_create_root(void)
{
    char directory[] = "/tmp/swapz-late-last-use-XXXXXX";

    assert(mkdtemp(directory) != NULL);
    assert(strlen(directory) < sizeof(fixture_root));
    strcpy(fixture_root, directory);
    fixture_join(fixture_config_base, fixture_root, "config");
    fixture_join(fixture_selector_path, fixture_config_base, "primary-target");
    fixture_join(fixture_retained_selector_path, fixture_root,
                 "previous-selector");
    fixture_join(fixture_retained_directory_path, fixture_root,
                 "previous-config");
    assert(mkdir(fixture_config_base, 0700) == 0);
    fixture_write_record(fixture_selector_path, "PARTUUID=aaaaaaaa\n");
    assert(chmod(fixture_selector_path, 0600) == 0);
    fixture_selector_hooks = 0U;
    fixture_alias_switches = 0U;
    fixture_swap_alias_on_open = 0;
}

static int fixture_remove_entry(const char *path, const struct stat *info,
                                int type, struct FTW *tree)
{
    (void)info;
    (void)type;
    (void)tree;
    return remove(path);
}

static void fixture_remove_root(void)
{
    assert(nftw(fixture_root, fixture_remove_entry, 16,
                FTW_DEPTH | FTW_PHYS) == 0);
}

static void fixture_selector_inject(void)
{
    ++fixture_selector_hooks;
    switch (fixture_selector_race) {
    case SELECTOR_SAME_BYTES_REPLACED:
    case SELECTOR_DIFFERENT_BYTES_REPLACED:
    case SELECTOR_SYMLINK_REPLACED:
        assert(rename(fixture_selector_path,
                      fixture_retained_selector_path) == 0);
        if (fixture_selector_race == SELECTOR_SYMLINK_REPLACED) {
            assert(symlink(fixture_retained_selector_path,
                           fixture_selector_path) == 0);
        } else {
            fixture_write_record(fixture_selector_path,
                fixture_selector_race == SELECTOR_DIFFERENT_BYTES_REPLACED
                    ? "PARTUUID=bbbbbbbb\n" : "PARTUUID=aaaaaaaa\n");
            assert(chmod(fixture_selector_path, 0600) == 0);
        }
        break;
    case SELECTOR_DIRECTORY_REPLACED:
    case SELECTOR_DIRECTORY_REMOVED:
        assert(rename(fixture_config_base,
                      fixture_retained_directory_path) == 0);
        if (fixture_selector_race == SELECTOR_DIRECTORY_REPLACED) {
            assert(mkdir(fixture_config_base, 0700) == 0);
            fixture_write_record(fixture_selector_path,
                                 "PARTUUID=aaaaaaaa\n");
            assert(chmod(fixture_selector_path, 0600) == 0);
        }
        break;
    default:
        abort();
    }
}

static void fixture_check_selector(int candidate)
{
    char selected_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
    int result;
    int observed_errno;

    fixture_create_root();
    fixture_selector_race = candidate;
    swapz_primary_rootless_selector_before_revalidation =
        candidate == SELECTOR_UNCHANGED ||
        candidate == SELECTOR_FRESH_AFTER_SUCCESS
            ? NULL : fixture_selector_inject;
    memset(selected_partuuid, 'X', sizeof(selected_partuuid));
    errno = 0;
    result = swapz_primary_target_config_read(selected_partuuid);
    observed_errno = errno;
    if (candidate == SELECTOR_UNCHANGED ||
        candidate == SELECTOR_FRESH_AFTER_SUCCESS) {
        assert(result == 0 && !strcmp(selected_partuuid, "aaaaaaaa"));
        assert(fixture_selector_hooks == 0U);
        if (candidate == SELECTOR_FRESH_AFTER_SUCCESS) {
            /* A previous successful read must not cache the old pathname. */
            assert(rename(fixture_selector_path,
                          fixture_retained_selector_path) == 0);
            fixture_write_record(fixture_selector_path,
                                 "PARTUUID=bbbbbbbb\n");
            assert(chmod(fixture_selector_path, 0600) == 0);
            memset(selected_partuuid, 'X', sizeof(selected_partuuid));
            assert(swapz_primary_target_config_read(selected_partuuid) == 0);
            assert(!strcmp(selected_partuuid, "bbbbbbbb"));
        }
    } else {
        assert(result == -1 && observed_errno == ESTALE);
        assert(selected_partuuid[0] == '\0');
        assert(fixture_selector_hooks == 1U);
    }
    swapz_primary_rootless_selector_before_revalidation = NULL;
    printf("PASS: phase=selector-last-read case=%d expected=%s "
           "observed=%s errno=%d output=%s\n", candidate,
           candidate == SELECTOR_UNCHANGED ||
           candidate == SELECTOR_FRESH_AFTER_SUCCESS
               ? "admit-current-inode" : "refuse-stale-inode",
           result == 0 ? "fresh" : "ESTALE", result == 0 ? 0 : observed_errno,
           result == 0 ? "current" : "cleared");
    fixture_remove_root();
}

static void fixture_create_target_file(const char *path)
{
    int fd = open(path, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);

    assert(fd >= 0);
    assert(ftruncate(fd, (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) == 0);
    assert(close(fd) == 0);
}

static void fixture_check_target_and_header(int race)
{
    char target_path[PATH_MAX];
    char partuuid_alias_path[PATH_MAX];
    unsigned char original[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
    unsigned char replacement[SWAPZ_PRIMARY_BLOCK_BYTES];
    unsigned char observed[SWAPZ_PRIMARY_BLOCK_BYTES];
    int fd;
    int result;
    int observed_errno;

    fixture_create_root();
    fixture_join(target_path, fixture_root, "target");
    fixture_join(fixture_alias_path, fixture_root, "uuid");
    fixture_join(partuuid_alias_path, fixture_root, "partuuid");
    fixture_join(fixture_substitute_path, fixture_root, "substitute");
    fixture_join(fixture_retained_alias_path, fixture_root, "previous-uuid");
    fixture_create_target_file(target_path);
    fixture_create_target_file(fixture_substitute_path);
    assert(link(target_path, fixture_alias_path) == 0);
    assert(link(target_path, partuuid_alias_path) == 0);
    memset(&swapz_primary_selected_target, 0,
           sizeof(swapz_primary_selected_target));
    strcpy(swapz_primary_selected_target.partuuid, "aaaaaaaa");
    swapz_primary_selected_target.device_major = 8U;
    swapz_primary_selected_target.device_minor = 1U;
    swapz_primary_selected_target.device_bytes = SWAPZ_PRIMARY_BLOCK_BYTES;
    fixture_swap_alias_on_open = race == 1;
    errno = 0;
    fd = swapz_primary_open_target_checked_paths_mode(
        target_path, fixture_alias_path, partuuid_alias_path,
        O_RDWR | O_EXCL);
    observed_errno = errno;
    if (race == 1) {
        /* An opened substitute cannot inherit the previously named identity. */
        assert(fd == -1 && observed_errno == ENODEV);
        assert(fixture_alias_switches == 1U);
        fd = open(target_path, O_RDONLY | O_CLOEXEC);
        assert(fd >= 0);
        assert(pread(fd, observed, sizeof(observed), 0) ==
               (ssize_t)sizeof(observed));
        assert(memcmp(observed, original, sizeof(original)) == 0);
        printf("PASS: phase=target-exclusive-open expected=refuse-opened-alias "
               "observed=ENODEV errno=%d header=unchanged\n", observed_errno);
    } else {
        assert(fd >= 0 && fixture_alias_switches == 0U);
        memset(replacement, 0x6a, sizeof(replacement));
        if (race == 2) {
            /* A different current header must cause ESTALE before pwrite. */
            assert(pwrite(fd, replacement, sizeof(replacement), 0) ==
                   (ssize_t)sizeof(replacement));
        }
        errno = 0;
        result = swapz_primary_write_header_checked_fd(
            fd, &swapz_primary_selected_target, original,
            race == 2 ? original : replacement);
        observed_errno = errno;
        assert(pread(fd, observed, sizeof(observed), 0) ==
               (ssize_t)sizeof(observed));
        if (race == 2) {
            assert(result == -1 && observed_errno == ESTALE);
            assert(memcmp(observed, replacement, sizeof(observed)) == 0);
        } else {
            assert(result == 0);
            assert(memcmp(observed, replacement, sizeof(observed)) == 0);
        }
        printf("PASS: phase=header-last-use expected=%s "
               "observed=%s errno=%d header=%s\n",
               race == 2 ? "refuse-stale-header" : "write-private-control",
               race == 2 ? "ESTALE" : "written",
               race == 2 ? observed_errno : 0,
               race == 2 ? "unchanged-since-race" : "replacement-verified");
    }
    assert(close(fd) == 0);
    fixture_remove_root();
}

int main(void)
{
    int candidate;

    for (candidate = SELECTOR_UNCHANGED;
         candidate < SELECTOR_RACE_COUNT; ++candidate)
        fixture_check_selector(candidate);
    fixture_check_target_and_header(0);
    fixture_check_target_and_header(1);
    fixture_check_target_and_header(2);
    return 0;
}
'''


def compile_and_run_last_use(source: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    target_valid_functions = (
        "swapz_primary_target_valid", "swapz_primary_same_target_identity",
    )
    header_functions = (
        "swapz_primary_exact_read", "swapz_primary_header_fd_valid",
        "swapz_primary_write_header_checked_fd",
    )
    unit = LAST_USE_HARNESS.replace(
        "@@SELECTOR_ADMISSION_TYPE@@",
        production_struct(source, "swapz_primary_selector_admission")).replace(
        "@@SELECTOR_FUNCTIONS@@",
        "\n\n".join(production_function(source, name)
                    for name in SELECTOR_FUNCTIONS)).replace(
        "@@TARGET_VALID_FUNCTIONS@@",
        "\n\n".join(production_function(source, name)
                    for name in target_valid_functions)).replace(
        "@@TARGET_OPEN_FUNCTION@@",
        production_function(source, "swapz_primary_open_target_checked_paths_mode")).replace(
        "@@HEADER_FUNCTIONS@@",
        "\n\n".join(production_function(source, name)
                    for name in header_functions))
    if "@@" in unit:
        raise AssertionError("Unexpanded production last-use helper")
    c_path = workdir / "last-use.c"
    binary = workdir / "last-use"
    c_path.write_text(unit)
    compilation = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
         "-Wstrict-prototypes", "-Werror",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-fno-omit-frame-pointer",
         "-Wno-unused-function", "-Wno-unused-variable",
         "-I", str(INCLUDE_DIR), str(c_path), "-o", str(binary)],
        text=True, capture_output=True, check=False, timeout=30)
    if compilation.returncode:
        raise AssertionError(f"last-use.c compile failed:\n{compilation.stderr}")
    return subprocess.run(
        [str(binary)], text=True, capture_output=True, check=False,
        timeout=10, env={
            **os.environ,
            "ASAN_OPTIONS": "halt_on_error=1:abort_on_error=1:detect_leaks=1",
            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def compile_and_run(
    source: str, workdir: Path, *, mutant: bool,
    selector_aba_mutant: bool = False,
) -> subprocess.CompletedProcess[str]:
    helpers = (
        "swapz_primary_parse_u64", "swapz_primary_parse_priority",
        "swapz_primary_parse_dev_number", "swapz_primary_split_fields",
        "swapz_primary_mountinfo_path_valid",
        "swapz_primary_mountinfo_device_valid",
        "swapz_primary_mountinfo_rw_options_valid",
        "swapz_primary_mountinfo_optional_valid",
        "swapz_primary_mount_identifier_compare",
        "swapz_primary_parse_swaps", "swapz_primary_swap_inventory_target_is_quiescent",
        "swapz_primary_parse_mountinfo",
    )
    parser_source = '\n\n'.join(production_function(source, helper) for helper in helpers)
    production_defines = '\n'.join(production_define(source, name) for name in (
        "SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES",
        "SWAPZ_PRIMARY_SWAP_ROWS_MAX",
        "SWAPZ_PRIMARY_VISIBLE_TASKS_MAX",
        "SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES",
        "SWAPZ_PRIMARY_STATE_RECORD_MAX",
        "SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT",
    ))
    swap_function = production_function(source, "swapz_primary_swap_device_active")
    selector_source = "\n\n".join(
        production_function(source, name) for name in SELECTOR_FUNCTIONS)
    # The selector extraction already provides partuuid normalization.
    # Keep each production helper definition exactly once in the generated TU.
    target_helpers = '\n\n'.join(production_function(source, name) for name in (
        "swapz_primary_target_valid",
        "swapz_primary_target_identity_equal",
        "swapz_primary_target_revalidate",
    ))
    target_open = production_function(source, "swapz_primary_target_open_exclusive")
    mount_reader = '\n\n'.join(production_function(source, name) for name in (
        "swapz_primary_proc_entry_is_pid",
        "swapz_primary_mountinfo_read_fd",
        "swapz_primary_mountinfo_exit_error",
        "swapz_primary_mountinfo_full_root",
        "swapz_primary_read_nonleader_mount_facts",
        "swapz_primary_read_mount_facts",
    ))
    recovery_failure_helper = production_function(
        source, "swapz_primary_require_recovery_preserving_errno")
    coordinator = production_function(source, "swapz_primary_start_prepared")
    if mutant and selector_aba_mutant:
        raise AssertionError("Negative-control mutations are mutually exclusive")
    if mutant:
        coordinator = omit_final_revalidation(coordinator)
    elif selector_aba_mutant:
        coordinator = restore_independent_selector_reread(coordinator)
    unit = HARNESS.replace('@@PRODUCTION_DEFINES@@', production_defines).replace(
        '@@PARSERS@@', parser_source).replace(
        '@@SELECTOR_ADMISSION_TYPE@@',
        production_struct(source, "swapz_primary_selector_admission")).replace(
        '@@SELECTOR_FUNCTIONS@@', selector_source).replace(
        '@@MOUNT_READER@@', mount_reader).replace(
        '@@SWAP_FUNCTION@@', swap_function).replace(
        '@@TARGET_HELPERS@@', target_helpers).replace(
        '@@TARGET_OPEN_FUNCTION@@', target_open).replace(
        '@@RECOVERY_FAILURE_HELPER@@', recovery_failure_helper).replace(
        '@@START_FUNCTION@@', coordinator)
    if "@@" in unit:
        raise AssertionError("Unexpanded harness placeholder")
    if mutant:
        unit_name = "mutant"
    elif selector_aba_mutant:
        unit_name = "selector-aba-mutant"
    else:
        unit_name = "production"
    c_path = workdir / f"{unit_name}.c"
    binary = workdir / unit_name
    c_path.write_text(unit)
    compilation = subprocess.run(
        ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wpedantic",
         "-Wstrict-prototypes", "-Werror",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-fno-omit-frame-pointer",
         "-Wno-unused-function", "-Wno-unused-variable",
         "-Wno-unused-but-set-variable", "-I", str(INCLUDE_DIR), str(c_path),
         "-o", str(binary)], text=True, capture_output=True, timeout=30,
        check=False)
    if compilation.returncode:
        raise AssertionError(f"{c_path.name} compile failed:\n{compilation.stderr}")
    sanitizer_environment = dict(
        os.environ,
        ASAN_OPTIONS="halt_on_error=1:abort_on_error=1:detect_leaks=1",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    arguments = [str(binary)]
    if mutant:
        arguments.append("negative-control")
    elif selector_aba_mutant:
        arguments.append("selector-aba-negative-control")
    return subprocess.run(
        arguments, text=True, capture_output=True, env=sanitizer_environment,
        timeout=10, check=False)



def check_namespace_child_failure_boundary() -> int:
    """Distinguish namespace setup unavailability from an executed child failure."""
    unshare = shutil.which("unshare")
    if unshare is None:
        print("SKIP: boundary=namespace-setup expected_identity=distinct "
              "observed_identity=unavailable refusal=unshare-absent "
              "first_errno=ENOENT")
        return 0

    namespace_command = [
        unshare, "--user", "--map-root-user", "--mount", "--fork",
    ]
    setup_marker = "SWAPZ_NAMESPACE_SETUP_READY"
    try:
        setup = subprocess.run(
            [*namespace_command, sys.executable, "-c",
             f"print({setup_marker!r}, flush=True)"],
            capture_output=True, text=True, check=False, timeout=10,
            env={**os.environ, "LC_ALL": "C"})
    except OSError as error:
        print(f"FAIL: boundary=namespace-setup-spawn expected_identity=distinct "
              f"observed_identity=unknown refusal=spawn-error "
              f"first_errno={error.errno}",
              file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("FAIL: boundary=namespace-setup expected_identity=distinct "
              "observed_identity=unknown refusal=timeout "
              "first_errno=unavailable",
              file=sys.stderr)
        return 1

    setup_started = setup_marker in setup.stdout.splitlines()
    if setup.returncode != 0:
        if setup_started:
            print(f"FAIL: boundary=namespace-setup-after-start "
                  f"expected_identity=distinct observed_identity=unknown "
                  f"refusal=unexpected-child-exit first_errno=unavailable "
                  f"observed_exit={setup.returncode}",
                  file=sys.stderr)
            return 1
        print("SKIP: boundary=namespace-setup expected_identity=distinct "
              "observed_identity=unavailable "
              "refusal=unshare-setup-unavailable "
              f"first_errno=unavailable observed_exit={setup.returncode}")
        return 0
    if not setup_started:
        print("FAIL: boundary=namespace-setup-child expected_identity=distinct "
              "observed_identity=unknown refusal=missing-start-marker "
              "first_errno=unavailable observed_exit=0",
              file=sys.stderr)
        return 1

    try:
        parent_namespace_fd = os.open(
            "/proc/self/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
    except OSError as error:
        print(f"FAIL: boundary=namespace-parent-reference "
              f"expected_identity=pinned observed_identity=unavailable "
              f"refusal=open-error first_errno={error.errno}",
              file=sys.stderr)
        return 1

    # Keep a real namespace fd open across unshare. This is a pinned namespace
    # reference, unlike a sampled PID/TID or stat tuple, and it avoids putting
    # raw host namespace device/inode values in argv.
    child = (
        "import os, sys\n"
        "print('SWAPZ_NAMESPACE_CHILD_ENTERED', flush=True)\n"
        "pinned = os.fstat(int(sys.argv[1]))\n"
        "current = os.stat('/proc/self/ns/mnt')\n"
        "if (pinned.st_dev, pinned.st_ino) == "
        "(current.st_dev, current.st_ino):\n"
        "    raise SystemExit(24)\n"
        "raise SystemExit(23)\n"
    )
    try:
        try:
            completed = subprocess.run(
                [*namespace_command, sys.executable, "-c", child,
                 str(parent_namespace_fd)],
                pass_fds=(parent_namespace_fd,), capture_output=True, text=True,
                check=False, timeout=10, env={**os.environ, "LC_ALL": "C"})
        except OSError as error:
            print(f"FAIL: boundary=namespace-child-spawn "
                  f"expected_identity=distinct observed_identity=unknown "
                  f"refusal=spawn-error first_errno={error.errno}",
                  file=sys.stderr)
            return 1
        except subprocess.TimeoutExpired:
            print("FAIL: boundary=namespace-child-start "
                  "expected_identity=distinct observed_identity=unknown "
                  "refusal=timeout first_errno=unavailable",
                  file=sys.stderr)
            return 1
    finally:
        os.close(parent_namespace_fd)

    # Namespace setup was already proven. From here onward, no error may be
    # reclassified as an environmental SKIP.
    if "SWAPZ_NAMESPACE_CHILD_ENTERED" not in completed.stdout.splitlines():
        print(f"FAIL: boundary=namespace-child-start expected_identity=distinct "
              f"observed_identity=unknown refusal=missing-start-marker "
              f"first_errno=unavailable observed_exit={completed.returncode}",
              file=sys.stderr)
        return 1
    if completed.returncode != 23:
        print(f"FAIL: boundary=namespace-child-after-start "
              f"expected_identity=distinct observed_identity=unknown "
              f"refusal=unexpected-child-exit first_errno=none "
              f"observed_exit={completed.returncode} expected_exit=23",
              file=sys.stderr)
        return 1
    print("PASS: boundary=namespace-child-after-start expected_identity=distinct "
          "observed_identity=distinct negative_control=executed-child-failure "
          "classification=FAIL refusal=nonzero-exit-not-environment-SKIP "
          "first_errno=none observed_exit=23")
    return 0

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
        selector_aba_mutant = compile_and_run(
            source, workdir, mutant=False, selector_aba_mutant=True)
        if (selector_aba_mutant.returncode != 1 or
                "observed=stale-selection-reached-mutation" not in
                    selector_aba_mutant.stderr or
                "mutations=4" not in selector_aba_mutant.stderr or
                "selector_reads=2 selector_aba=2" not in
                    selector_aba_mutant.stderr):
            print("FAIL: independent final selector reread did not expose cross-read ABA",
                  file=sys.stderr)
            print(selector_aba_mutant.stdout + selector_aba_mutant.stderr,
                  file=sys.stderr, end="")
            return 1
        print("PASS: cross-read ABA negative control reaches all intercepted mutations")
        last_use = compile_and_run_last_use(source, workdir)
        if last_use.returncode:
            print(last_use.stdout, end="")
            print(last_use.stderr, file=sys.stderr, end="")
            return 1
        print(last_use.stdout, end="")
    return check_namespace_child_failure_boundary()


if __name__ == "__main__":
    raise SystemExit(main())
