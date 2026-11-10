// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "swapz-primary.h"
#include "../kernel/swapz-build-info.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <spawn.h>
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
#include <linux/btrfs.h>
#endif
#include <linux/dm-ioctl.h>
#include <linux/fs.h>
#include <linux/magic.h>
#include <linux/stat.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/swap.h>
#include <sys/sysmacros.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <sys/utsname.h>
#include <time.h>
#include <unistd.h>

#include "../kernel/authority.h"
#include "../kernel/superblock.h"

/* Linux swapon(2) ABI policy bit. libc commonly exposes only
 * SWAP_FLAG_DISCARD, so keep the released-cluster selector local. */
#define SWAPZ_PRIMARY_SWAP_FLAG_DISCARD_PAGES 0x40000

/* NS_GET_MNTNS_ID is available since Linux 6.11, including on systems
 * whose userspace headers predate its declaration. Keep the namespace fd
 * pinned, but pass its stable kernel ID to statmount/listmount. Passing the fd
 * in the reserved request word is only supported since Linux 6.18. */
#define SWAPZ_PRIMARY_NS_GET_MNTNS_ID _IOR(0xb7, 0x5, uint64_t)

static struct swapz_primary_target swapz_primary_selected_target;

static void swapz_primary_selected_target_clear(void)
{
	memset(&swapz_primary_selected_target, 0,
	       sizeof(swapz_primary_selected_target));
}

#define SWAPZ_PRIMARY_BLOCK_BYTES ((uint64_t)SWAPZ_BLOCK_BYTES)
#define SWAPZ_PRIMARY_MUTATION_LOCK_NAME "package.lock"
#define SWAPZ_PRIMARY_PACKAGE_TRANSACTION_DIRECTORY \
	"/var/lib/swapz-package-transactions"
#define SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY "/run/swapz"
#define SWAPZ_PRIMARY_EXECUTION_RUNTIME_PARENT "/run"
#define SWAPZ_PRIMARY_EXECUTION_RECORD_NAME "primary-execution.env"
#define SWAPZ_PRIMARY_BOOT_ID_LENGTH 36U
#define SWAPZ_PRIMARY_EXECUTION_RECORD_BYTES 512U
#define SWAPZ_PRIMARY_VISIBLE_TASKS_MAX 4194304U
#define SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES (64U * 1024U * 1024U)
#if defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && \
	defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST)
#error "primary lifecycle test modes are mutually exclusive"
#endif

#if defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST)
#ifndef SWAPZ_PRIMARY_TEST_CONFIG_BASE
#error "owned-null_blk lifecycle test requires private config base"
#endif
#ifndef SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE
#error "owned-null_blk lifecycle test requires private runtime-state base"
#endif
#ifndef SWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT
#error "owned-null_blk lifecycle test requires private qualification report"
#endif
#ifndef SWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY
#error "owned-null_blk lifecycle test requires private mutation lock directory"
#endif
#define SWAPZ_PRIMARY_CONFIG_BASE SWAPZ_PRIMARY_TEST_CONFIG_BASE
#define SWAPZ_PRIMARY_RUNTIME_STATE_BASE SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE
/* Private rehearsal keeps its synthetic qualification report beside its
 * isolated runtime fixture; production evidence remains separately persistent. */
#define SWAPZ_PRIMARY_QUALIFICATION_BASE SWAPZ_PRIMARY_TEST_RUNTIME_STATE_BASE
#define SWAPZ_PRIMARY_QUALIFICATION_REPORT \
	SWAPZ_PRIMARY_TEST_QUALIFICATION_REPORT
#define SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY \
	SWAPZ_PRIMARY_TEST_MUTATION_LOCK_DIRECTORY
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1
#elif defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST)
#ifndef SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL
#error "physical lifecycle qualification requires installed qualified control path"
#endif
#define SWAPZ_PRIMARY_CONFIG_BASE "/etc/swapz"
#define SWAPZ_PRIMARY_RUNTIME_STATE_BASE \
	SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY
#define SWAPZ_PRIMARY_QUALIFICATION_BASE "/var/lib/swapz/physical-recovery"
#define SWAPZ_PRIMARY_QUALIFICATION_REPORT \
	"/var/lib/swapz/physical-recovery/primary-qualification.json"
#define SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY "/run/lock/swapz"
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1
#else
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
/* The rootless policy fixture substitutes only its private test directory. */
static const char *swapz_primary_rootless_config_base = "/etc/swapz";
static void (*swapz_primary_rootless_selector_before_revalidation)(void);
#define SWAPZ_PRIMARY_CONFIG_BASE swapz_primary_rootless_config_base
#else
#define SWAPZ_PRIMARY_CONFIG_BASE "/etc/swapz"
#endif
#define SWAPZ_PRIMARY_RUNTIME_STATE_BASE \
	SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY
#define SWAPZ_PRIMARY_QUALIFICATION_BASE "/var/lib/swapz/physical-recovery"
#define SWAPZ_PRIMARY_QUALIFICATION_REPORT \
	"/var/lib/swapz/physical-recovery/primary-qualification.json"
#define SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY "/run/lock/swapz"
/*
 * Ordinary production contains the qualified lifecycle implementation but is
 * runtime-locked. A successful owner-armed, cross-boot preflight must mint a
 * volatile source/boot/target-bound authorization before mutation is possible.
 * Private qualification seams retain their existing admission behavior.
 */
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 1
#endif

#if !defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && \
	!defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST) && \
	!defined(SWAPZ_PRIMARY_ROOTLESS_TEST)
static int swapz_primary_production_execution_authorized(void);
#endif

static int swapz_primary_lifecycle_runtime_enabled(void)
{
#ifdef SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST
	const char *enabled = getenv("SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION");

	return enabled && !strcmp(enabled, "1");
#elif defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST)
	return 1;
#elif defined(SWAPZ_PRIMARY_ROOTLESS_TEST)
	return 0;
#else
	return swapz_primary_production_execution_authorized();
#endif
}

/*
 * One source of truth for both read-only admission reporting and mutating
 * command dispatch. Ordinary production is compiled capable but remains
 * runtime-locked until the current boot's preflight authorization validates;
 * private qualification seams retain their explicit admission rules.
 */
static int swapz_primary_privileged_execution_enabled(void)
{
	return SWAPZ_PRIMARY_EXECUTION_ENABLED &&
	       swapz_primary_lifecycle_runtime_enabled();
}

/*
 * Activation needs current boot-scoped authorization. Cleanup is different:
 * ordinary production may stop or recover only an already durable transaction,
 * whose operation revalidates clean source, exact target and ownership state.
 * Private qualification seams retain their original runtime authority.
 */
static int swapz_primary_cleanup_execution_enabled(void)
{
#if !defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && \
	!defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST) && \
	!defined(SWAPZ_PRIMARY_ROOTLESS_TEST)
	return SWAPZ_PRIMARY_EXECUTION_ENABLED;
#else
	return swapz_primary_privileged_execution_enabled();
#endif
}

#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
static void swapz_primary_test_interrupt_after(const char *phase)
{
	const char *requested = getenv("SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER");

	if (phase && requested && !strcmp(requested, phase))
		_exit(86);
}
#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) \
	swapz_primary_test_interrupt_after(phase)
#else
#define SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER(phase) do { } while (0)
#endif

#define SWAPZ_PRIMARY_SWAP_VERSION_OFFSET 1024U
#define SWAPZ_PRIMARY_SWAP_LAST_PAGE_OFFSET 1028U
#define SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET 1032U
#define SWAPZ_PRIMARY_SWAP_UUID_OFFSET 1036U
#define SWAPZ_PRIMARY_SWAP_UUID_BYTES 16U
#define SWAPZ_PRIMARY_SWAP_MAGIC_BYTES 10U
#define SWAPZ_PRIMARY_MKSWAP_PATH "/usr/sbin/mkswap"
#define SWAPZ_PRIMARY_SEGMENT_BLOCKS ((uint64_t)SWAPZ_SEGMENT_BLOCKS)
#define SWAPZ_PRIMARY_SECTORS_PER_PAGE (SWAPZ_PRIMARY_BLOCK_BYTES / 512ULL)

_Static_assert(SWAPZ_BLOCK_BYTES % 512U == 0U,
	       "primary mapper pages must contain whole 512-byte sectors");
#define SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT "/dev/disk/by-partuuid/%s"
#define SWAPZ_PRIMARY_PARTITION_NAME_BYTES \
	(sizeof("partition-") - 1U + SWAPZ_PRIMARY_PARTUUID_LENGTH + \
	 sizeof(".active"))
#define SWAPZ_PRIMARY_DEVICE_BYTES \
	(swapz_primary_selected_target.device_bytes)
#define SWAPZ_PRIMARY_PARTUUID \
	(swapz_primary_selected_target.partuuid)
#define SWAPZ_PRIMARY_TARGET_DEVICE \
	makedev(swapz_primary_selected_target.device_major, \
		swapz_primary_selected_target.device_minor)
#define SWAPZ_PRIMARY_PLAN_BUFFER_BYTES 16384U
/* Keep ordinary mount reads on stack; grow only for unusually large hosts.
 * Both the per-table and 64 MiB aggregate read budgets remain bounded. */
#define SWAPZ_PRIMARY_MOUNTINFO_INITIAL_BYTES 65536U
#define SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES (1024U * 1024U)
#define SWAPZ_PRIMARY_DM_MAPPERS_MAX 512U
#define SWAPZ_PRIMARY_SWAP_ROWS_MAX 32U
#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES (64ULL * 1024ULL * 1024ULL)
#define SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME \
	"primary-root-parent-scope"
#define SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_BYTES 128U
#define SWAPZ_PRIMARY_PARTITION_FACTS_MAX 256U
#define SWAPZ_PRIMARY_PARTITION_CANONICAL_BYTES 512U
#define SWAPZ_PRIMARY_DM_CONTROL_PATH "/dev/mapper/control"
#define SWAPZ_PRIMARY_DM_BUFFER_BYTES 4096U
#define SWAPZ_PRIMARY_MAPPER_NODE_RETRY_ATTEMPTS 100U
#define SWAPZ_PRIMARY_MAPPER_NODE_RETRY_NS 50000000L
#define SWAPZ_PRIMARY_MODULE_SUFFIX "/sbin/swapzctl"
#define SWAPZ_PRIMARY_MODULE_RELATIVE_PATH "libexec/swapz/dm-swapz.ko"
#define SWAPZ_PRIMARY_STATE_JSON_PREFIX \
	"{\"schema\":\"swapz-primary-state-v1\",\"run_id\":"

struct swapz_primary_swap_entry {
	char path[PATH_MAX];
	char type[32];
	uint64_t size_kib;
	uint64_t used_kib;
	int priority;
};

/* Bind the exception to partitions and the verified parent, never a pathname. */
struct swapz_primary_partition_scope {
	uint32_t device_major;
	uint32_t device_minor;
	uint32_t partition_number;
	uint64_t start_sectors;
	uint64_t size_sectors;
	uint64_t size_bytes;
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char parttype[64];
	char partscheme[16];
	char part_table_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char part_table_type[16];
};

struct swapz_primary_shared_root_scope {
	char host_identity_sha256[65];
	struct swapz_primary_partition_scope root;
	struct swapz_primary_partition_scope target;
	uint32_t parent_major;
	uint32_t parent_minor;
	uint64_t parent_size_sectors;
	char parent_identity_sha256[65];
	char partition_layout_sha256[65];
};

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
struct swapz_primary_udev_scope_properties {
	char serial[1024];
	char wwn[1024];
	char vendor[256];
	char model[1024];
	char device_type[32];
	char table_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char table_type[16];
	char entry_scheme[16];
	char entry_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char entry_type[64];
	char entry_number[32];
	char entry_offset[32];
	char entry_size[32];
	char entry_disk[32];
};
#endif

static const char *const swapz_primary_stage_names[] = {
	[SWAPZ_PRIMARY_STAGE_READY] = "READY",
	[SWAPZ_PRIMARY_STAGE_STARTING] = "STARTING",
	[SWAPZ_PRIMARY_STAGE_ACTIVE] = "ACTIVE",
	[SWAPZ_PRIMARY_STAGE_STOPPING] = "STOPPING",
	[SWAPZ_PRIMARY_STAGE_RECOVERING] = "RECOVERING",
	[SWAPZ_PRIMARY_STAGE_RESTORED] = "RESTORED",
	[SWAPZ_PRIMARY_STAGE_DISABLING] = "DISABLING",
	[SWAPZ_PRIMARY_STAGE_COMPLETE] = "COMPLETE",
	[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = "RECOVERY_REQUIRED",
};

static int swapz_primary_valid_run_id(const char *run_id);
static int swapz_primary_valid_sha256(const char *digest);
static uint64_t swapz_primary_maximum_logical_pages(uint64_t physical_blocks);
static uint64_t swapz_primary_manifest_physical_blocks(
	const struct swapz_primary_manifest *manifest);
static uint64_t swapz_primary_swap_size_kib_from_header(
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	uint64_t device_bytes);
static uint64_t swapz_primary_linux_swap_size_kib(uint64_t logical_pages);
static int swapz_primary_parse_u64(const char *text, uint64_t *value);
static int swapz_primary_sha256(const unsigned char *bytes, size_t length,
				char digest[65]);
static int swapz_primary_reconcile_metadata_claim_at(
	int recovery_fd, int lock_fd, uid_t expected_owner);
static int swapz_primary_exact_read(int fd, unsigned char *buffer,
				    size_t length);
static int swapz_primary_record_read_at(
	int recovery_fd, const char *name, uid_t expected_owner,
	char *record, size_t capacity, size_t *length, struct stat *identity);

const char *swapz_primary_stage_name(enum swapz_primary_stage stage)
{
	if ((unsigned int)stage >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return NULL;
	return swapz_primary_stage_names[stage];
}

int swapz_primary_stage_parse(const char *name,
			      enum swapz_primary_stage *stage)
{
	enum swapz_primary_stage candidate;

	if (!name || !stage)
		return -1;
	for (candidate = SWAPZ_PRIMARY_STAGE_READY;
	     (unsigned int)candidate < (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT;
	     ++candidate) {
		if (!strcmp(name, swapz_primary_stage_names[candidate])) {
			*stage = candidate;
			return 0;
		}
	}
	return -1;
}

int swapz_primary_stage_transition_allowed(enum swapz_primary_stage from,
						   enum swapz_primary_stage to)
{
	if ((unsigned int)from >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT ||
	    (unsigned int)to >= (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return 0;
	if (from == to)
		return from != SWAPZ_PRIMARY_STAGE_COMPLETE;
	if (to == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED)
		return from != SWAPZ_PRIMARY_STAGE_COMPLETE;
	switch (from) {
	case SWAPZ_PRIMARY_STAGE_READY:
		return to == SWAPZ_PRIMARY_STAGE_STARTING ||
		       to == SWAPZ_PRIMARY_STAGE_DISABLING;
	case SWAPZ_PRIMARY_STAGE_STARTING:
		return to == SWAPZ_PRIMARY_STAGE_ACTIVE;
	case SWAPZ_PRIMARY_STAGE_ACTIVE:
		return to == SWAPZ_PRIMARY_STAGE_STOPPING;
	case SWAPZ_PRIMARY_STAGE_STOPPING:
		return to == SWAPZ_PRIMARY_STAGE_RESTORED;
	case SWAPZ_PRIMARY_STAGE_RECOVERING:
		return to == SWAPZ_PRIMARY_STAGE_RESTORED;
	case SWAPZ_PRIMARY_STAGE_RESTORED:
		return to == SWAPZ_PRIMARY_STAGE_COMPLETE;
	case SWAPZ_PRIMARY_STAGE_DISABLING:
		return to == SWAPZ_PRIMARY_STAGE_COMPLETE;
	case SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED:
		return to == SWAPZ_PRIMARY_STAGE_RECOVERING;
	case SWAPZ_PRIMARY_STAGE_COMPLETE:
	case SWAPZ_PRIMARY_STAGE_COUNT:
		return 0;
	}
	return 0;
}

static int swapz_primary_state_string(const char **cursor,
				      const char *end, char *value,
				      size_t capacity)
{
	size_t length = 0;

	if (!cursor || !*cursor || !value || !capacity || *cursor >= end ||
	    **cursor != '"')
		return -1;
	++*cursor;
	while (*cursor < end && **cursor != '"') {
		unsigned char byte = (unsigned char)**cursor;

		if (byte < 0x20U || byte > 0x7eU || byte == '\\' ||
		    length + 1U >= capacity)
			return -1;
		value[length++] = (char)byte;
		++*cursor;
	}
	if (*cursor >= end || **cursor != '"')
		return -1;
	++*cursor;
	value[length] = '\0';
	return 0;
}

static int swapz_primary_state_run_id_valid(const char *run_id)
{
	unsigned int i;

	if (!run_id || run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH] != '\0')
		return 0;
	for (i = 0; i < SWAPZ_PRIMARY_RUN_ID_LENGTH; ++i)
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return 0;
	return 1;
}

static int swapz_primary_valid_source_sha(const char *source_sha)
{
	unsigned int i;

	if (!source_sha ||
	    strnlen(source_sha, SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 1U) !=
		    SWAPZ_PRIMARY_SOURCE_SHA_LENGTH)
		return 0;
	for (i = 0; i < SWAPZ_PRIMARY_SOURCE_SHA_LENGTH; ++i)
		if (!((source_sha[i] >= '0' && source_sha[i] <= '9') ||
		      (source_sha[i] >= 'a' && source_sha[i] <= 'f')))
			return 0;
	return 1;
}

static int swapz_primary_valid_kernel_release(const char *release)
{
	size_t length;
	size_t index;

	if (!release)
		return 0;
	length = strnlen(release, SWAPZ_PRIMARY_KERNEL_RELEASE_LENGTH + 1U);
	if (!length || length > SWAPZ_PRIMARY_KERNEL_RELEASE_LENGTH)
		return 0;
	for (index = 0; index < length; ++index) {
		unsigned char byte = (unsigned char)release[index];

		if (!((byte >= 'a' && byte <= 'z') ||
		      (byte >= 'A' && byte <= 'Z') ||
		      (byte >= '0' && byte <= '9') || byte == '.' ||
		      byte == '_' || byte == '+' || byte == '-'))
			return 0;
	}
	return 1;
}

static int swapz_primary_build_sources_match(const char *control_sha,
					     int control_clean,
					     const char *module_sha,
					     int module_clean)
{
	return control_clean == 1 && module_clean == 1 &&
	       swapz_primary_valid_source_sha(control_sha) &&
	       swapz_primary_valid_source_sha(module_sha) &&
	       !strcmp(control_sha, module_sha);
}

static int swapz_primary_state_valid(const struct swapz_primary_state *state)
{
	if (!state || !swapz_primary_state_run_id_valid(state->run_id) ||
	    (state->has_recovery_previous_stage != 0 &&
	     state->has_recovery_previous_stage != 1) ||
	    (unsigned int)state->stage >=
			(unsigned int)SWAPZ_PRIMARY_STAGE_COUNT)
		return 0;
	if (!state->has_recovery_previous_stage)
		return state->stage != SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED &&
		       state->stage != SWAPZ_PRIMARY_STAGE_RECOVERING;
	if ((unsigned int)state->recovery_previous_stage >=
	    (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT ||
	    state->recovery_previous_stage == SWAPZ_PRIMARY_STAGE_COMPLETE ||
	    state->recovery_previous_stage ==
			SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	    state->recovery_previous_stage == SWAPZ_PRIMARY_STAGE_RECOVERING)
		return 0;
	return state->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	       state->stage == SWAPZ_PRIMARY_STAGE_RECOVERING ||
	       state->stage == SWAPZ_PRIMARY_STAGE_RESTORED ||
	       state->stage == SWAPZ_PRIMARY_STAGE_COMPLETE;
}

int swapz_primary_state_parse(const char *record, size_t length,
			      struct swapz_primary_state *state)
{
	struct swapz_primary_state parsed = {0};
	char token[64];
	const char *cursor;
	const char *end;

	if (!record || !state || !length ||
	    length > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    memchr(record, '\0', length))
		return -1;
	cursor = record;
	end = record + length;
	if ((size_t)(end - cursor) < sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U ||
	    memcmp(cursor, SWAPZ_PRIMARY_STATE_JSON_PREFIX,
		   sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U))
		return -1;
	cursor += sizeof(SWAPZ_PRIMARY_STATE_JSON_PREFIX) - 1U;
	if (swapz_primary_state_string(&cursor, end, parsed.run_id,
				       sizeof(parsed.run_id)) < 0 ||
	    !swapz_primary_valid_run_id(parsed.run_id) ||
	    (size_t)(end - cursor) < sizeof(",\"stage\":") - 1U ||
	    memcmp(cursor, ",\"stage\":", sizeof(",\"stage\":") - 1U))
		return -1;
	cursor += sizeof(",\"stage\":") - 1U;
	if (swapz_primary_state_string(&cursor, end, token, sizeof(token)) < 0 ||
	    swapz_primary_stage_parse(token, &parsed.stage) < 0 ||
	    (size_t)(end - cursor) <
		    sizeof(",\"recovery_previous_stage\":") - 1U ||
	    memcmp(cursor, ",\"recovery_previous_stage\":",
		   sizeof(",\"recovery_previous_stage\":") - 1U))
		return -1;
	cursor += sizeof(",\"recovery_previous_stage\":") - 1U;
	if ((size_t)(end - cursor) >= sizeof("null}\n") - 1U &&
	    !memcmp(cursor, "null}\n", sizeof("null}\n") - 1U)) {
		cursor += sizeof("null}\n") - 1U;
	} else {
		if (swapz_primary_state_string(&cursor, end, token,
					       sizeof(token)) < 0 ||
		    swapz_primary_stage_parse(token,
					     &parsed.recovery_previous_stage) < 0 ||
		    (size_t)(end - cursor) < sizeof("}\n") - 1U ||
		    memcmp(cursor, "}\n", sizeof("}\n") - 1U))
			return -1;
		cursor += sizeof("}\n") - 1U;
		parsed.has_recovery_previous_stage = 1;
	}
	if (cursor != end || !swapz_primary_state_valid(&parsed))
		return -1;
	*state = parsed;
	return 0;
}

int swapz_primary_state_format(const struct swapz_primary_state *state,
			       char *record, size_t capacity)
{
	const char *previous = "null";
	int length;

	if (!swapz_primary_state_valid(state) || !record || !capacity) {
		errno = EINVAL;
		return -1;
	}
	if (state->has_recovery_previous_stage)
		previous = swapz_primary_stage_name(
			state->recovery_previous_stage);
	length = snprintf(record, capacity,
			  SWAPZ_PRIMARY_STATE_JSON_PREFIX
			  "\"%s\",\"stage\":\"%s\","
			  "\"recovery_previous_stage\":%s%s%s}\n",
			  state->run_id, swapz_primary_stage_name(state->stage),
			  state->has_recovery_previous_stage ? "\"" : "",
			  previous,
			  state->has_recovery_previous_stage ? "\"" : "");
	if (length < 0 || (size_t)length >= capacity ||
	    (size_t)length > SWAPZ_PRIMARY_STATE_RECORD_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	return length;
}

int swapz_primary_state_transition_allowed(
	const struct swapz_primary_state *current,
	const struct swapz_primary_state *next)
{
	enum swapz_primary_stage recovery_origin;

	if (!swapz_primary_state_valid(current) ||
	    !swapz_primary_state_valid(next))
		return 0;
	if (strcmp(current->run_id, next->run_id))
		return current->stage == SWAPZ_PRIMARY_STAGE_COMPLETE &&
		       next->stage == SWAPZ_PRIMARY_STAGE_READY &&
		       !next->has_recovery_previous_stage;
	if (current->stage == SWAPZ_PRIMARY_STAGE_COMPLETE)
		return 0;
	if (next->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED) {
		recovery_origin = current->has_recovery_previous_stage ?
			current->recovery_previous_stage : current->stage;
		return next->has_recovery_previous_stage &&
		       next->recovery_previous_stage == recovery_origin;
	}
	if (current->stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED ||
	    current->stage == SWAPZ_PRIMARY_STAGE_RECOVERING) {
		if (!current->has_recovery_previous_stage ||
		    !next->has_recovery_previous_stage ||
		    current->recovery_previous_stage !=
			    next->recovery_previous_stage)
			return 0;
	} else if (current->stage == SWAPZ_PRIMARY_STAGE_RESTORED &&
		   current->has_recovery_previous_stage) {
		if (!next->has_recovery_previous_stage ||
		    current->recovery_previous_stage !=
			    next->recovery_previous_stage)
			return 0;
	} else if (current->has_recovery_previous_stage ||
		   next->has_recovery_previous_stage) {
		return 0;
	}
	return swapz_primary_stage_transition_allowed(current->stage,
						      next->stage);
}

static int swapz_primary_recovery_required_state(
	const struct swapz_primary_state *current,
	struct swapz_primary_state *recovery_required)
{
	struct swapz_primary_state candidate;

	if (!swapz_primary_state_valid(current) || !recovery_required ||
	    current->stage == SWAPZ_PRIMARY_STAGE_COMPLETE) {
		errno = EINVAL;
		return -1;
	}
	candidate = *current;
	candidate.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	if (!candidate.has_recovery_previous_stage) {
		candidate.has_recovery_previous_stage = 1;
		candidate.recovery_previous_stage = current->stage;
	}
	if (!swapz_primary_state_transition_allowed(current, &candidate)) {
		errno = EPERM;
		return -1;
	}
	*recovery_required = candidate;
	return 0;
}

int swapz_primary_run_id_generate(
	char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U])
{
	static const char hex[] = "0123456789abcdef";
	unsigned char random_bytes[SWAPZ_PRIMARY_RUN_ID_LENGTH / 2U];
	char candidate[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];
	size_t offset = 0;
	size_t i;
	unsigned char any = 0;

	if (!run_id) {
		errno = EINVAL;
		return -1;
	}
	while (offset < sizeof(random_bytes)) {
		ssize_t count = getrandom(random_bytes + offset,
					  sizeof(random_bytes) - offset, 0);

		if (count < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (count == 0) {
			errno = EIO;
			return -1;
		}
		offset += (size_t)count;
	}
	for (i = 0; i < sizeof(random_bytes); ++i) {
		any |= random_bytes[i];
		candidate[i * 2U] = hex[random_bytes[i] >> 4];
		candidate[i * 2U + 1U] = hex[random_bytes[i] & 0x0fU];
	}
	memset(random_bytes, 0, sizeof(random_bytes));
	if (!any) {
		memset(candidate, 0, sizeof(candidate));
		errno = EIO;
		return -1;
	}
	candidate[SWAPZ_PRIMARY_RUN_ID_LENGTH] = '\0';
	memcpy(run_id, candidate, sizeof(candidate));
	memset(candidate, 0, sizeof(candidate));
	return 0;
}

static int swapz_primary_partuuid_normalize(
	const char *partuuid,
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	char candidate[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	size_t hex_digits = 0;
	size_t length;
	size_t i;
	int previous_hyphen = 0;

	if (!normalized) {
		errno = EINVAL;
		return -1;
	}
	normalized[0] = '\0';
	if (!partuuid) {
		errno = EINVAL;
		return -1;
	}
	length = strnlen(partuuid, SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U);
	if (length < 8U || length > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < length; ++i) {
		unsigned char ch = (unsigned char)partuuid[i];
		int is_hex = (ch >= '0' && ch <= '9') ||
			     (ch >= 'a' && ch <= 'f') ||
			     (ch >= 'A' && ch <= 'F');

		if (is_hex) {
			candidate[i] = (char)tolower(ch);
			++hex_digits;
			previous_hyphen = 0;
			continue;
		}
		if (ch != '-' || i == 0U || i + 1U == length ||
		    previous_hyphen) {
			errno = EINVAL;
			return -1;
		}
		candidate[i] = '-';
		previous_hyphen = 1;
	}
	if (hex_digits < 8U) {
		errno = EINVAL;
		return -1;
	}
	candidate[length] = '\0';
	memcpy(normalized, candidate, length + 1U);
	return 0;
}

int swapz_primary_partuuid_valid(const char *partuuid)
{
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

	return swapz_primary_partuuid_normalize(partuuid, normalized) == 0;
}


#if !defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && \
	!defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST)
static int swapz_primary_boot_id_valid(const char *boot_id)
{
	unsigned int index;

	if (!boot_id ||
	    strnlen(boot_id, SWAPZ_PRIMARY_BOOT_ID_LENGTH + 1U) !=
		    SWAPZ_PRIMARY_BOOT_ID_LENGTH)
		return 0;
	for (index = 0; index < SWAPZ_PRIMARY_BOOT_ID_LENGTH; ++index) {
		unsigned char byte = (unsigned char)boot_id[index];
		int hyphen = index == 8U || index == 13U ||
			     index == 18U || index == 23U;

		if (hyphen) {
			if (byte != '-')
				return 0;
			continue;
		}
		if (!((byte >= '0' && byte <= '9') ||
		      (byte >= 'a' && byte <= 'f')))
			return 0;
	}
	return 1;
}

static int swapz_primary_execution_record_matches(
	const char *record, size_t length, const char *boot_id,
	const char *source_sha, const char *partuuid, uint32_t target_device_major,
	uint32_t target_device_minor, uint64_t target_size_bytes)
{
	char expected[SWAPZ_PRIMARY_EXECUTION_RECORD_BYTES];
	int expected_length;

	if (!record || !length || !swapz_primary_boot_id_valid(boot_id) ||
	    !swapz_primary_valid_source_sha(source_sha) ||
	    !swapz_primary_partuuid_valid(partuuid) || !target_device_major ||
	    !target_size_bytes)
		return 0;
	expected_length = snprintf(
		expected, sizeof(expected),
		"schema=swapz-primary-execution-v2\n"
		"boot_id=%s\n"
		"source_sha=%s\n"
		"partuuid=%s\n"
		"target_device=%u:%u\n"
		"target_size_bytes=%llu\n",
		boot_id, source_sha, partuuid, target_device_major,
		target_device_minor, (unsigned long long)target_size_bytes);
	if (expected_length <= 0 ||
	    (size_t)expected_length >= sizeof(expected))
		return 0;
	return length == (size_t)expected_length &&
	       !memcmp(record, expected, (size_t)expected_length);
}
#endif

static int swapz_primary_target_valid(
	const struct swapz_primary_target *target)
{
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	dev_t device;

	if (!target ||
	    strnlen(target->partuuid, sizeof(target->partuuid)) >=
		    sizeof(target->partuuid) ||
	    swapz_primary_partuuid_normalize(target->partuuid, normalized) < 0 ||
	    strcmp(normalized, target->partuuid) ||
	    !target->device_major ||
	    target->device_bytes < SWAPZ_PRIMARY_BLOCK_BYTES)
		return 0;
	device = makedev(target->device_major, target->device_minor);
	return major(device) == target->device_major &&
	       minor(device) == target->device_minor;
}

static int swapz_primary_target_identity_equal(
	const struct swapz_primary_target *left,
	const struct swapz_primary_target *right)
{
	return swapz_primary_target_valid(left) &&
	       swapz_primary_target_valid(right) &&
	       !strcmp(left->partuuid, right->partuuid) &&
	       left->device_major == right->device_major &&
	       left->device_minor == right->device_minor &&
	       left->device_bytes == right->device_bytes;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_target_revalidate(
	const struct swapz_primary_target *expected)
{
	struct swapz_primary_target observed;

	if (!swapz_primary_target_valid(expected)) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_target_inspect(expected->partuuid, &observed) < 0)
		return -1;
	if (!swapz_primary_target_identity_equal(expected, &observed)) {
		errno = ESTALE;
		return -1;
	}
	return 0;
}
#endif

int swapz_primary_target_config_parse(
	const char *record, size_t length,
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	static const char prefix[] = "PARTUUID=";
	char parsed[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	size_t prefix_length = sizeof(prefix) - 1U;
	size_t value_length;

	if (!partuuid) {
		errno = EINVAL;
		return -1;
	}
	partuuid[0] = '\0';
	if (!record || length <= prefix_length + 1U ||
	    length > prefix_length + SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U ||
	    memchr(record, '\0', length) || record[length - 1U] != '\n' ||
	    memcmp(record, prefix, prefix_length)) {
		errno = EINVAL;
		return -1;
	}
	value_length = length - prefix_length - 1U;
	if (!value_length || value_length > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
		errno = EINVAL;
		return -1;
	}
	memcpy(parsed, record + prefix_length, value_length);
	parsed[value_length] = '\0';
	if (swapz_primary_partuuid_normalize(parsed, normalized) < 0) {
		errno = EINVAL;
		return -1;
	}
	memcpy(partuuid, normalized, value_length + 1U);
	return 0;
}

/*
 * Compare the opened inode and its immutable admission metadata. A matching
 * PARTUUID string is not sufficient if either protected path was replaced.
 */
static int swapz_primary_selector_metadata_matches(
	const struct stat *before, const struct stat *after)
{
	return before->st_dev == after->st_dev &&
	       before->st_ino == after->st_ino &&
	       before->st_mode == after->st_mode &&
	       before->st_uid == after->st_uid &&
	       before->st_gid == after->st_gid &&
	       before->st_nlink == after->st_nlink &&
	       before->st_size == after->st_size &&
	       before->st_mtim.tv_sec == after->st_mtim.tv_sec &&
	       before->st_mtim.tv_nsec == after->st_mtim.tv_nsec &&
	       before->st_ctim.tv_sec == after->st_ctim.tv_sec &&
	       before->st_ctim.tv_nsec == after->st_ctim.tv_nsec;
}


/*
 * Read and parse one already-opened protected selector without following the
 * pathname again. The expected stat is the transaction's pinned admission
 * identity; pread keeps descriptor offset irrelevant to repeated last-use
 * checks, and output is published only after metadata remains unchanged.
 */
static int swapz_primary_selector_read_stable_fd(
	int fd, const struct stat *expected_info,
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	char record[SWAPZ_PRIMARY_PARTUUID_LENGTH + sizeof("PARTUUID=\n") + 1U];
	char parsed_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	struct stat before;
	struct stat after;
	size_t completed = 0;
	size_t length;
	ssize_t count;
	int flags;

	if (fd < 0 || !expected_info || !partuuid ||
	    expected_info->st_size <= 0 ||
	    (uint64_t)expected_info->st_size >
		(sizeof("PARTUUID=") - 1U + SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U)) {
		errno = EINVAL;
		return -1;
	}
	partuuid[0] = '\0';
	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		return -1;
	if ((flags & O_ACCMODE) != O_RDONLY) {
		errno = EBADF;
		return -1;
	}
	if (fstat(fd, &before) < 0)
		return -1;
	if (!swapz_primary_selector_metadata_matches(expected_info, &before)) {
		errno = ESTALE;
		return -1;
	}
	length = (size_t)expected_info->st_size;
	while (completed < length) {
		count = pread(fd, record + completed, length - completed,
			      (off_t)completed);
		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0)
			return -1;
		if (!count) {
			errno = ESTALE;
			return -1;
		}
		completed += (size_t)count;
	}
	do {
		unsigned char extra;

		count = pread(fd, &extra, sizeof(extra), (off_t)length);
	} while (count < 0 && errno == EINTR);
	if (count != 0) {
		if (count > 0)
			errno = ESTALE;
		return -1;
	}
	if (fstat(fd, &after) < 0)
		return -1;
	if (!swapz_primary_selector_metadata_matches(expected_info, &after) ||
	    !swapz_primary_selector_metadata_matches(&before, &after)) {
		errno = ESTALE;
		return -1;
	}
	if (swapz_primary_target_config_parse(
		    record, length, parsed_partuuid) < 0)
		return -1;
	memcpy(partuuid, parsed_partuuid, strlen(parsed_partuuid) + 1U);
	return 0;
}

/*
 * Start retains opened protected-selector identities through the final
 * non-mutating check. Only its coordinator owns these two descriptors.
 * The whole-file rootless build has no mutating coordinator, so only the
 * extracted coordinator fixture compiles these production-only declarations.
 */
#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
struct swapz_primary_selector_admission {
	int directory_fd;
	int selector_fd;
	struct stat directory_info;
	struct stat selector_info;
};
#endif

/*
 * The caller retains both descriptors through this final admission check.
 * Reopen the live config pathname, not merely the pinned old directory: an
 * administrator may have renamed the complete protected directory away.
 * Rootless tests invoke this production check with private directory paths.
 */
static int swapz_primary_selector_identity_still_live(
	const char *config_base, int directory_fd, int selector_fd,
	const struct stat *directory_before, const struct stat *selector_before)
{
	struct stat directory_after;
	struct stat selector_after;
	struct stat live_directory;
	struct stat live_selector;
	struct stat named_directory;
	int live_directory_fd;
	int saved_errno;

	if (!config_base || directory_fd < 0 || selector_fd < 0 ||
	    !directory_before || !selector_before) {
		errno = EINVAL;
		return -1;
	}
	if (fstat(directory_fd, &directory_after) < 0 ||
	    fstat(selector_fd, &selector_after) < 0)
		return -1;
	if (!swapz_primary_selector_metadata_matches(
		    directory_before, &directory_after) ||
	    !swapz_primary_selector_metadata_matches(
		    selector_before, &selector_after)) {
		errno = ESTALE;
		return -1;
	}
	live_directory_fd = open(config_base,
				 O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (live_directory_fd < 0) {
		if (errno == ENOENT || errno == ENOTDIR || errno == ELOOP)
			errno = ESTALE;
		return -1;
	}
	if (fstat(live_directory_fd, &live_directory) < 0 ||
	    fstatat(live_directory_fd, "primary-target", &live_selector,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    fstatat(AT_FDCWD, config_base, &named_directory,
		    AT_SYMLINK_NOFOLLOW) < 0) {
		saved_errno = errno;
		(void)close(live_directory_fd);
		errno = saved_errno == ENOENT || saved_errno == ENOTDIR ||
			saved_errno == ELOOP ? ESTALE : saved_errno;
		return -1;
	}
	if (!swapz_primary_selector_metadata_matches(
		    directory_before, &live_directory) ||
	    !swapz_primary_selector_metadata_matches(
		    directory_before, &named_directory) ||
	    !swapz_primary_selector_metadata_matches(
		    selector_before, &live_selector)) {
		(void)close(live_directory_fd);
		errno = ESTALE;
		return -1;
	}
	/*
	 * The live file lookup itself can race with another path replacement.
	 * Recheck the opened metadata and the config name before publishing.
	 */
	if (fstat(directory_fd, &directory_after) < 0 ||
	    fstat(selector_fd, &selector_after) < 0 ||
	    fstatat(AT_FDCWD, config_base, &named_directory,
		    AT_SYMLINK_NOFOLLOW) < 0) {
		saved_errno = errno;
		(void)close(live_directory_fd);
		errno = saved_errno == ENOENT || saved_errno == ENOTDIR ?
			ESTALE : saved_errno;
		return -1;
	}
	if (!swapz_primary_selector_metadata_matches(
		    directory_before, &directory_after) ||
	    !swapz_primary_selector_metadata_matches(
		    selector_before, &selector_after) ||
	    !swapz_primary_selector_metadata_matches(
		    directory_before, &named_directory)) {
		(void)close(live_directory_fd);
		errno = ESTALE;
		return -1;
	}
	if (close(live_directory_fd) < 0)
		return -1;
	return 0;
}


#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
/*
 * Pin both protected named objects before the transaction reads its selector.
 * The ordinary reader validates content; the pinned identities reject later
 * inode and directory replacement, including replacement with identical bytes.
 */
static int swapz_primary_selector_admission_open(
	struct swapz_primary_selector_admission *admission)
{
	uid_t expected_owner = 0;
	int first_errno;

	if (!admission) {
		errno = EINVAL;
		return -1;
	}
	*admission = (struct swapz_primary_selector_admission) {
		.directory_fd = -1, .selector_fd = -1
	};
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	expected_owner = geteuid();
#endif
	admission->directory_fd = open(SWAPZ_PRIMARY_CONFIG_BASE,
		O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (admission->directory_fd < 0)
		goto fail;
	if (fstat(admission->directory_fd, &admission->directory_info) < 0)
		goto fail;
	if (!S_ISDIR(admission->directory_info.st_mode) ||
	    admission->directory_info.st_uid != expected_owner ||
	    (admission->directory_info.st_mode & 0022U)) {
		errno = EPERM;
		goto fail;
	}
	admission->selector_fd = openat(admission->directory_fd,
		"primary-target", O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (admission->selector_fd < 0)
		goto fail;
	if (fstat(admission->selector_fd, &admission->selector_info) < 0)
		goto fail;
	if (!S_ISREG(admission->selector_info.st_mode) ||
	    admission->selector_info.st_uid != expected_owner ||
	    (admission->selector_info.st_mode & 0022U) ||
	    admission->selector_info.st_nlink != 1 ||
	    admission->selector_info.st_size <= 0 ||
	    (size_t)admission->selector_info.st_size >
		(sizeof("PARTUUID=") - 1U + SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U)) {
		errno = EPERM;
		goto fail;
	}
	if (swapz_primary_selector_identity_still_live(
		SWAPZ_PRIMARY_CONFIG_BASE, admission->directory_fd,
		admission->selector_fd, &admission->directory_info,
		&admission->selector_info) < 0)
		goto fail;
	return 0;

fail:
	first_errno = errno ? errno : EIO;
	if (admission->selector_fd >= 0)
		(void)close(admission->selector_fd);
	if (admission->directory_fd >= 0)
		(void)close(admission->directory_fd);
	*admission = (struct swapz_primary_selector_admission) {
		.directory_fd = -1, .selector_fd = -1
	};
	errno = first_errno;
	return -1;
}

/* Close both pinned descriptors and preserve the first close failure. */
static int swapz_primary_selector_admission_close(
	struct swapz_primary_selector_admission *admission)
{
	int first_errno = 0;
	int preserved_errno = errno;

	if (!admission) {
		errno = EINVAL;
		return -1;
	}
	if (admission->selector_fd >= 0) {
		if (close(admission->selector_fd) < 0)
			first_errno = errno;
		admission->selector_fd = -1;
	}
	if (admission->directory_fd >= 0) {
		if (close(admission->directory_fd) < 0 && !first_errno)
			first_errno = errno;
		admission->directory_fd = -1;
	}
	errno = first_errno ? first_errno : preserved_errno;
	return first_errno ? -1 : 0;
}


/*
 * Report the identity class of a stale name before invoking the full pinned
 * descriptor/path race check. The name checks only diagnose a refusal: they
 * never authorize a different inode, and no protected values are printed.
 */
static int swapz_primary_selector_admission_still_live(
	const struct swapz_primary_selector_admission *admission,
	const char **failure_observed)
{
	struct stat named_directory;
	struct stat named_selector;

	if (!admission || !failure_observed) {
		errno = EINVAL;
		return -1;
	}
	*failure_observed = "protected-selector-unverifiable";
	if (fstatat(AT_FDCWD, SWAPZ_PRIMARY_CONFIG_BASE,
		    &named_directory, AT_SYMLINK_NOFOLLOW) < 0) {
		*failure_observed = "configuration-directory-unverifiable";
		if (errno == ENOENT || errno == ENOTDIR || errno == ELOOP)
			errno = ESTALE;
		return -1;
	}
	if (admission->directory_info.st_dev != named_directory.st_dev ||
	    admission->directory_info.st_ino != named_directory.st_ino) {
		*failure_observed = "configuration-directory-identity-changed";
		errno = ESTALE;
		return -1;
	}
	if (fstatat(admission->directory_fd, "primary-target",
		    &named_selector, AT_SYMLINK_NOFOLLOW) < 0) {
		*failure_observed = "selector-file-unverifiable";
		if (errno == ENOENT || errno == ENOTDIR || errno == ELOOP)
			errno = ESTALE;
		return -1;
	}
	if (admission->selector_info.st_dev != named_selector.st_dev ||
	    admission->selector_info.st_ino != named_selector.st_ino) {
		*failure_observed = "selector-file-identity-changed";
		errno = ESTALE;
		return -1;
	}
	if (!swapz_primary_selector_metadata_matches(
		    &admission->directory_info, &named_directory) ||
	    !swapz_primary_selector_metadata_matches(
		    &admission->selector_info, &named_selector)) {
		*failure_observed = "protected-path-metadata-changed";
		errno = ESTALE;
		return -1;
	}
	if (swapz_primary_selector_identity_still_live(
		    SWAPZ_PRIMARY_CONFIG_BASE, admission->directory_fd,
		    admission->selector_fd, &admission->directory_info,
		    &admission->selector_info) < 0) {
		*failure_observed = "selector-identity-raced-or-unverifiable";
		return -1;
	}
	*failure_observed = NULL;
	return 0;
}

/*
 * Bind selector bytes to the inode pinned by this start transaction. Live-name
 * continuity is checked separately immediately before and after this read.
 */
static int swapz_primary_selector_admission_read_partuuid(
	const struct swapz_primary_selector_admission *admission,
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	if (!admission || !partuuid) {
		errno = EINVAL;
		return -1;
	}
	return swapz_primary_selector_read_stable_fd(
		admission->selector_fd, &admission->selector_info, partuuid);
}

#endif

int swapz_primary_target_config_read(
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	char parsed_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	struct stat directory_info;
	struct stat info;
	int directory_fd = -1;
	int fd = -1;
	int saved_errno;
	int result = -1;
	uid_t expected_owner = 0;

#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	expected_owner = geteuid();
#endif
	if (!partuuid) {
		errno = EINVAL;
		return -1;
	}
	partuuid[0] = '\0';
	directory_fd = open(SWAPZ_PRIMARY_CONFIG_BASE,
			    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (directory_fd < 0)
		return -1;
	if (fstat(directory_fd, &directory_info) < 0)
		goto out;
	if (!S_ISDIR(directory_info.st_mode) || directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0022U)) {
		errno = EPERM;
		goto out;
	}
	fd = openat(directory_fd, "primary-target",
		    O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		goto out;
	if (fstat(fd, &info) < 0)
		goto out;
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0022U) || info.st_nlink != 1 ||
	    info.st_size <= 0 ||
	    (size_t)info.st_size > sizeof("PARTUUID=") - 1U +
			   SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U) {
		errno = EPERM;
		goto out;
	}
	/* Parse locally; stale named paths must never publish a selected target. */
	if (swapz_primary_selector_read_stable_fd(
		    fd, &info, parsed_partuuid) < 0)
		goto out;
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (swapz_primary_rootless_selector_before_revalidation)
		swapz_primary_rootless_selector_before_revalidation();
#endif
	if (swapz_primary_selector_identity_still_live(
		    SWAPZ_PRIMARY_CONFIG_BASE, directory_fd, fd,
		    &directory_info, &info) < 0)
		goto out;
	memcpy(partuuid, parsed_partuuid, strlen(parsed_partuuid) + 1U);
	result = 0;
out:
	saved_errno = errno;
	if (fd >= 0 && close(fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (close(directory_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (result < 0) {
		partuuid[0] = '\0';
		errno = saved_errno;
	}
	return result;
}

int swapz_primary_systemd_target_units(
	const char *partuuid,
	char device_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX],
	char swap_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX])
{
	static const char prefix[] = "dev-disk-by\\x2dpartuuid-";
	static const char device_suffix[] = ".device";
	static const char swap_suffix[] = ".swap";
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char device_candidate[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	char swap_candidate[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	size_t length;
	size_t device_length;
	size_t swap_length;
	size_t i;
	size_t offset;

	if (device_unit)
		device_unit[0] = '\0';
	if (swap_unit)
		swap_unit[0] = '\0';
	if (!partuuid || !device_unit || !swap_unit ||
	    device_unit == swap_unit ||
	    swapz_primary_partuuid_normalize(partuuid, normalized) < 0) {
		errno = EINVAL;
		return -1;
	}
	length = strlen(normalized);
	device_length = sizeof(prefix) - 1U + sizeof(device_suffix) - 1U;
	swap_length = sizeof(prefix) - 1U + sizeof(swap_suffix) - 1U;
	for (i = 0; i < length; ++i) {
		size_t encoded_length = normalized[i] == '-' ? 4U : 1U;

		if (device_length > 255U - encoded_length ||
		    swap_length > 255U - encoded_length) {
			errno = ENAMETOOLONG;
			return -1;
		}
		device_length += encoded_length;
		swap_length += encoded_length;
	}
	if (device_length >= sizeof(device_candidate) ||
	    swap_length >= sizeof(swap_candidate)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	memcpy(device_candidate, prefix, sizeof(prefix) - 1U);
	memcpy(swap_candidate, prefix, sizeof(prefix) - 1U);
	offset = sizeof(prefix) - 1U;
	for (i = 0; i < length; ++i) {
		if (normalized[i] == '-') {
			memcpy(device_candidate + offset, "\\x2d", 4U);
			memcpy(swap_candidate + offset, "\\x2d", 4U);
			offset += 4U;
		} else {
			device_candidate[offset] = normalized[i];
			swap_candidate[offset] = normalized[i];
			++offset;
		}
	}
	memcpy(device_candidate + offset, device_suffix, sizeof(device_suffix));
	memcpy(swap_candidate + offset, swap_suffix, sizeof(swap_suffix));
	memcpy(device_unit, device_candidate, device_length + 1U);
	memcpy(swap_unit, swap_candidate, swap_length + 1U);
	memset(normalized, 0, sizeof(normalized));
	memset(device_candidate, 0, sizeof(device_candidate));
	memset(swap_candidate, 0, sizeof(swap_candidate));
	return 0;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_sysfs_partuuid_matches(
	dev_t device, const char *expected_partuuid)
{
	char path[128];
	char record[4096];
	char observed[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	size_t used = 0;
	int length;
	int fd;

	if (!swapz_primary_partuuid_valid(expected_partuuid)) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(path, sizeof(path), "/sys/dev/block/%u:%u/uevent",
			  major(device), minor(device));
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = EOVERFLOW;
		return -1;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used == sizeof(record)) {
		errno = EOVERFLOW;
		return -1;
	}
	{
		const char *cursor = record;
		const char *end = record + used;

		while (cursor < end) {
			const char *line_end = memchr(cursor, '\n',
						       (size_t)(end - cursor));
			size_t line_length = line_end ?
				(size_t)(line_end - cursor) : (size_t)(end - cursor);

			if (line_length >= sizeof("PARTUUID=") - 1U &&
			    !memcmp(cursor, "PARTUUID=", sizeof("PARTUUID=") - 1U)) {
				size_t value_length = line_length -
					(sizeof("PARTUUID=") - 1U);

				if (!value_length || value_length >
				    SWAPZ_PRIMARY_PARTUUID_LENGTH) {
					errno = EBADMSG;
					return -1;
				}
				memcpy(observed, cursor + sizeof("PARTUUID=") - 1U,
				       value_length);
				observed[value_length] = '\0';
				if (swapz_primary_partuuid_normalize(
					    observed, normalized) < 0 ||
				    strcmp(normalized, expected_partuuid)) {
					errno = ESTALE;
					return -1;
				}
				return 0;
			}
			if (!line_end)
				break;
			cursor = line_end + 1;
		}
	}
	errno = ENODATA;
	return -1;
}
#endif

int swapz_primary_target_inspect(const char *partuuid,
				 struct swapz_primary_target *target)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)partuuid;
	(void)target;
	errno = ENOTSUP;
	return -1;
#else
	struct swapz_primary_target inspected = {0};
	char normalized_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	struct stat alias_before;
	struct stat opened;
	struct stat alias_after;
	struct stat partition_attribute;
	char path[PATH_MAX];
	char sysfs_partition[128];
	uint64_t bytes = 0;
	int length;
	int fd = -1;
	int saved_errno;

	if (!target ||
	    swapz_primary_partuuid_normalize(partuuid, normalized_partuuid) < 0) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(path, sizeof(path),
			  SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT,
			  normalized_partuuid);
	if (length < 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (stat(path, &alias_before) < 0)
		return -1;
	if (!S_ISBLK(alias_before.st_mode) ||
	    !major(alias_before.st_rdev)) {
		errno = ENODEV;
		return -1;
	}
	length = snprintf(sysfs_partition, sizeof(sysfs_partition),
			  "/sys/dev/block/%u:%u/partition",
			  major(alias_before.st_rdev), minor(alias_before.st_rdev));
	if (length < 0 || (size_t)length >= sizeof(sysfs_partition) ||
	    stat(sysfs_partition, &partition_attribute) < 0 ||
	    !S_ISREG(partition_attribute.st_mode)) {
		errno = ENODEV;
		return -1;
	}
	if (swapz_primary_sysfs_partuuid_matches(
		    alias_before.st_rdev, normalized_partuuid) < 0)
		return -1;
	fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0 || !S_ISBLK(opened.st_mode) ||
	    opened.st_rdev != alias_before.st_rdev ||
	    ioctl(fd, BLKGETSIZE64, &bytes) < 0 ||
	    bytes < SWAPZ_PRIMARY_BLOCK_BYTES ||
	    stat(path, &alias_after) < 0 || !S_ISBLK(alias_after.st_mode) ||
	    alias_after.st_rdev != opened.st_rdev ||
	    swapz_primary_sysfs_partuuid_matches(
		    opened.st_rdev, normalized_partuuid) < 0) {
		saved_errno = errno ? errno : ESTALE;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	memcpy(inspected.partuuid, normalized_partuuid,
	       strlen(normalized_partuuid) + 1U);
	inspected.device_major = major(opened.st_rdev);
	inspected.device_minor = minor(opened.st_rdev);
	inspected.device_bytes = bytes;
	*target = inspected;
	return 0;
#endif
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_configured_target(
	struct swapz_primary_target *target)
{
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	int saved_errno;

	swapz_primary_selected_target_clear();
	if (!target) {
		errno = EINVAL;
		return -1;
	}
	memset(target, 0, sizeof(*target));
	if (swapz_primary_target_config_read(partuuid) < 0 ||
	    swapz_primary_target_inspect(partuuid, target) < 0) {
		saved_errno = errno ? errno : EIO;
		memset(target, 0, sizeof(*target));
		swapz_primary_selected_target_clear();
		errno = saved_errno;
		return -1;
	}
	swapz_primary_selected_target = *target;
	return 0;
}

#if !defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && \
	!defined(SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST)
static int swapz_primary_read_current_boot_id(
	char boot_id[SWAPZ_PRIMARY_BOOT_ID_LENGTH + 1U])
{
	char record[SWAPZ_PRIMARY_BOOT_ID_LENGTH + 2U];
	size_t used = 0;
	int fd;

	if (!boot_id) {
		errno = EINVAL;
		return -1;
	}
	boot_id[0] = '\0';
	fd = open("/proc/sys/kernel/random/boot_id",
		  O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used != SWAPZ_PRIMARY_BOOT_ID_LENGTH + 1U ||
	    record[SWAPZ_PRIMARY_BOOT_ID_LENGTH] != '\n') {
		errno = EINVAL;
		return -1;
	}
	record[SWAPZ_PRIMARY_BOOT_ID_LENGTH] = '\0';
	if (!swapz_primary_boot_id_valid(record)) {
		errno = EINVAL;
		return -1;
	}
	memcpy(boot_id, record, SWAPZ_PRIMARY_BOOT_ID_LENGTH + 1U);
	return 0;
}

static int swapz_primary_production_execution_authorized(void)
{
	struct swapz_primary_target target = {0};
	struct stat directory_info;
	struct stat before;
	struct stat after;
	char boot_id[SWAPZ_PRIMARY_BOOT_ID_LENGTH + 1U];
	char record[SWAPZ_PRIMARY_EXECUTION_RECORD_BYTES];
	size_t used = 0;
	int directory_fd = -1;
	int fd = -1;
	int authorized = 0;

	if (SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA) ||
	    swapz_primary_read_current_boot_id(boot_id) < 0 ||
	    swapz_primary_configured_target(&target) < 0)
		return 0;

	directory_fd = open(SWAPZ_PRIMARY_EXECUTION_RUNTIME_DIRECTORY,
			    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (directory_fd < 0)
		goto out;
	if (fstat(directory_fd, &directory_info) < 0 ||
	    !S_ISDIR(directory_info.st_mode) || directory_info.st_uid != 0 ||
	    (directory_info.st_mode & 0777U) != 0700U)
		goto out;
	fd = openat(directory_fd, SWAPZ_PRIMARY_EXECUTION_RECORD_NAME,
		    O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		goto out;
	if (fstat(fd, &before) < 0 || !S_ISREG(before.st_mode) ||
	    before.st_uid != 0 || (before.st_mode & 0777U) != 0600U ||
	    before.st_nlink != 1 || before.st_size <= 0 ||
	    (uint64_t)before.st_size >= sizeof(record))
		goto out;
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0)
			goto out;
		if (!count)
			break;
		used += (size_t)count;
	}
	if (used == sizeof(record) || fstat(fd, &after) < 0 ||
	    before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec ||
	    before.st_uid != after.st_uid || before.st_mode != after.st_mode ||
	    before.st_nlink != after.st_nlink || used != (size_t)before.st_size)
		goto out;
	authorized = swapz_primary_execution_record_matches(
		record, used, boot_id, SWAPZ_BUILD_SOURCE_SHA, target.partuuid,
		target.device_major, target.device_minor, target.device_bytes);
out:
	if (fd >= 0)
		(void)close(fd);
	if (directory_fd >= 0)
		(void)close(directory_fd);
	memset(record, 0, sizeof(record));
	memset(&target, 0, sizeof(target));
	/* Authorization is only an admission decision. Lifecycle operations must
	 * establish their own fresh selected-target state after the gate. */
	swapz_primary_selected_target_clear();
	return authorized;
}
#endif
#endif

static int swapz_primary_manifest_take_line(const char **cursor,
					    const char *end,
					    const char *key,
					    char *value,
					    size_t capacity)
{
	const char *line_end;
	char prefix[96];
	int prefix_length;
	size_t value_length;
	size_t i;

	if (!cursor || !*cursor || !key || !value || !capacity || *cursor >= end)
		return -1;
	prefix_length = snprintf(prefix, sizeof(prefix), "%s=", key);
	if (prefix_length < 0 || (size_t)prefix_length >= sizeof(prefix) ||
	    (size_t)(end - *cursor) < (size_t)prefix_length ||
	    memcmp(*cursor, prefix, (size_t)prefix_length))
		return -1;
	*cursor += prefix_length;
	line_end = memchr(*cursor, '\n', (size_t)(end - *cursor));
	if (!line_end)
		return -1;
	value_length = (size_t)(line_end - *cursor);
	if (!value_length || value_length >= capacity)
		return -1;
	for (i = 0; i < value_length; ++i) {
		unsigned char byte = (unsigned char)(*cursor)[i];

		if (byte < 0x20U || byte > 0x7eU)
			return -1;
	}
	memcpy(value, *cursor, value_length);
	value[value_length] = '\0';
	*cursor = line_end + 1;
	return 0;
}

static int swapz_primary_manifest_expect_line(const char **cursor,
					      const char *end,
					      const char *key,
					      const char *expected)
{
	char observed[256];

	if (swapz_primary_manifest_take_line(cursor, end, key, observed,
					     sizeof(observed)) < 0 ||
	    strcmp(observed, expected))
		return -1;
	return 0;
}

static int swapz_primary_manifest_valid(
	const struct swapz_primary_manifest *manifest)
{
	return manifest && swapz_primary_state_run_id_valid(manifest->run_id) &&
	       swapz_primary_valid_source_sha(manifest->source_sha) &&
	       swapz_primary_valid_sha256(manifest->swapzctl_sha256) &&
	       swapz_primary_valid_sha256(manifest->module_sha256) &&
	       swapz_primary_valid_sha256(
		       manifest->qualification_report_sha256) &&
	       swapz_primary_valid_sha256(
		       manifest->original_header_sha256) &&
	       swapz_primary_manifest_physical_blocks(manifest) &&
	       (manifest->original_swap_active == 0 ||
		manifest->original_swap_active == 1) &&
	       manifest->original_swap_priority <= 32767 &&
	       (manifest->original_swap_active ||
		manifest->original_swap_priority == 0) &&
	       swapz_primary_target_valid(&manifest->target);
}

#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
static uint64_t swapz_primary_physical_blocks(uint64_t device_bytes)
{
	uint64_t blocks;
	uint64_t usable_blocks;

	if (device_bytes < SWAPZ_PRIMARY_BLOCK_BYTES)
		return 0;
	/*
	 * Linux swap capacity is page-granular. Ignore any sub-page device tail;
	 * the mapper and iterate_devices range must never include those bytes.
	 */
	blocks = device_bytes / SWAPZ_PRIMARY_BLOCK_BYTES;
	usable_blocks = ((blocks - 1ULL) / SWAPZ_PRIMARY_SEGMENT_BLOCKS) *
			SWAPZ_PRIMARY_SEGMENT_BLOCKS;
	if (usable_blocks > UINT32_MAX ||
	    usable_blocks > (uint64_t)SIZE_MAX / sizeof(swapz_u16))
		return 0;
	return usable_blocks;
}
#endif
static uint64_t swapz_primary_physical_blocks_from_header(
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	uint64_t device_bytes)
{
	struct swapz_linux_swap_layout layout;
	uint64_t clean_segments;
	uint64_t clean_blocks;

	if (!header ||
	    !swapz_linux_swap_header_parse(header, device_bytes, &layout))
		return 0;
	clean_segments = swapz_linux_swap_clean_segment_count(
		header, &layout, SWAPZ_PRIMARY_SEGMENT_BLOCKS);
	if (!clean_segments)
		return 0;
	clean_blocks = clean_segments * SWAPZ_PRIMARY_SEGMENT_BLOCKS;
	if (clean_blocks > UINT32_MAX ||
	    clean_blocks > (uint64_t)SIZE_MAX / sizeof(swapz_u16))
		return 0;
	return clean_blocks;
}

static uint64_t swapz_primary_manifest_physical_blocks(
	const struct swapz_primary_manifest *manifest)
{
	if (!manifest)
		return 0;
	if (manifest->backing_physical_blocks >=
			3U * SWAPZ_PRIMARY_SEGMENT_BLOCKS &&
	    !(manifest->backing_physical_blocks % SWAPZ_PRIMARY_SEGMENT_BLOCKS))
		return manifest->backing_physical_blocks;
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	/* Rootless unit fixtures created before a live header exists retain the
	 * deterministic contiguous synthetic geometry. Production never falls
	 * back from the manifest-bound header-derived value. */
	if (!manifest->backing_physical_blocks)
		return swapz_primary_physical_blocks(manifest->target.device_bytes);
#endif
	return 0;
}


static int swapz_primary_mapper_layout(
	const struct swapz_primary_manifest *manifest, char mapper_name[64],
	char mapper_uuid[64], char table[128], uint64_t *logical_sectors)
{
	uint64_t logical_pages;
	int length;

	if (!swapz_primary_manifest_valid(manifest) || !mapper_name ||
	    !mapper_uuid || !table || !logical_sectors) {
		errno = EINVAL;
		return -1;
	}
	logical_pages = swapz_primary_maximum_logical_pages(
		swapz_primary_manifest_physical_blocks(manifest));
	if (!logical_pages ||
	    logical_pages > UINT64_MAX / SWAPZ_PRIMARY_SECTORS_PER_PAGE) {
		errno = EOVERFLOW;
		return -1;
	}
	*logical_sectors = logical_pages * SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	/* Match the packaged systemd swap unit; UUID remains run-bound. */
	length = snprintf(mapper_name, 64U, "swapz-primary");
	if (length < 0 || length >= 64) {
		errno = EOVERFLOW;
		return -1;
	}
	length = snprintf(mapper_uuid, 64U, "SWAPZ-PRIMARY-%s", manifest->run_id);
	if (length < 0 || length >= 64) {
		errno = EOVERFLOW;
		return -1;
	}
	length = snprintf(table, 128U,
			  "0 %llu swapz %u:%u 0 64 0 2 0 1 0 0",
			  (unsigned long long)*logical_sectors,
			  manifest->target.device_major,
			  manifest->target.device_minor);
	if (length < 0 || length >= 128) {
		errno = EOVERFLOW;
		return -1;
	}
	return 0;
}

static size_t swapz_primary_dm_align8(size_t length)
{
	if (length > SIZE_MAX - 7U)
		return 0;
	return (length + 7U) & ~(size_t)7U;
}

static int swapz_primary_dm_ioctl_initialize(struct dm_ioctl *io,
						    size_t buffer_bytes,
						    const char *name,
						    const char *uuid)
{
	if (!io || buffer_bytes < sizeof(*io) || buffer_bytes > UINT32_MAX) {
		errno = EINVAL;
		return -1;
	}
	memset(io, 0, sizeof(*io));
	io->version[0] = DM_VERSION_MAJOR;
	io->version[1] = DM_VERSION_MINOR;
	io->version[2] = DM_VERSION_PATCHLEVEL;
	io->data_size = (uint32_t)buffer_bytes;
	io->data_start = sizeof(*io);
	if (name) {
		size_t length = strlen(name);

		if (!length || length >= sizeof(io->name)) {
			errno = ENAMETOOLONG;
			return -1;
		}
		memcpy(io->name, name, length + 1U);
	}
	if (uuid) {
		size_t length = strlen(uuid);

		if (!length || length >= sizeof(io->uuid)) {
			errno = ENAMETOOLONG;
			return -1;
		}
		memcpy(io->uuid, uuid, length + 1U);
	}
	return 0;
}

/*
 * Existing mapper ioctls must select by the run-bound UUID only. Linux rejects
 * a lookup that supplies both name and UUID; callers verify both returned IDs.
 */
static int swapz_primary_dm_existing_mapper_ioctl_initialize(
	struct dm_ioctl *io, size_t buffer_bytes,
	const char *expected_name, const char *expected_uuid)
{
	if (!io || !expected_name || !expected_uuid ||
	    !expected_name[0] || !expected_uuid[0] ||
	    strnlen(expected_name, sizeof(io->name)) >= sizeof(io->name) ||
	    strnlen(expected_uuid, sizeof(io->uuid)) >= sizeof(io->uuid)) {
		errno = EINVAL;
		return -1;
	}
	return swapz_primary_dm_ioctl_initialize(
		io, buffer_bytes, NULL, expected_uuid);
}

static int swapz_primary_dm_table_load_buffer(
	const struct swapz_primary_manifest *manifest, unsigned char *buffer,
	size_t capacity, size_t *used_bytes)
{
	char mapper_name[64];
	char mapper_uuid[64];
	char expected_table[128];
	char parameters[96];
	struct dm_ioctl *io;
	struct dm_target_spec *target;
	size_t parameter_bytes;
	size_t target_bytes;
	size_t total_bytes;
	uint64_t logical_sectors;
	int length;

	if (!buffer || !used_bytes || capacity > UINT32_MAX ||
	    ((uintptr_t)buffer % _Alignof(struct dm_ioctl)) != 0U) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					expected_table, &logical_sectors) < 0)
		return -1;
	length = snprintf(parameters, sizeof(parameters),
			   "%u:%u 0 64 0 2 0 1 0 0",
			   manifest->target.device_major,
			   manifest->target.device_minor);
	if (length < 0 || (size_t)length >= sizeof(parameters)) {
		errno = EOVERFLOW;
		return -1;
	}
	parameter_bytes = strlen(parameters) + 1U;
	target_bytes = swapz_primary_dm_align8(sizeof(*target) + parameter_bytes);
	if (!target_bytes || target_bytes > SIZE_MAX - sizeof(*io)) {
		errno = EOVERFLOW;
		return -1;
	}
	total_bytes = sizeof(*io) + target_bytes;
	if (total_bytes > capacity) {
		errno = ENOSPC;
		return -1;
	}
	memset(buffer, 0, total_bytes);
	io = (struct dm_ioctl *)buffer;
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    io, total_bytes, mapper_name, mapper_uuid) < 0)
		return -1;
	io->target_count = 1U;
	target = (struct dm_target_spec *)(buffer + io->data_start);
	target->sector_start = 0ULL;
	target->length = logical_sectors;
	target->next = 0U;
	length = snprintf(target->target_type, sizeof(target->target_type),
			  "swapz");
	if (length < 0 || (size_t)length >= sizeof(target->target_type)) {
		errno = EOVERFLOW;
		return -1;
	}
	memcpy((unsigned char *)(target + 1), parameters, parameter_bytes);
	*used_bytes = total_bytes;
	return 0;
}

static int swapz_primary_dm_table_status_matches(
	const void *buffer, size_t buffer_bytes,
	const struct swapz_primary_manifest *manifest)
{
	char mapper_name[64];
	char mapper_uuid[64];
	char expected_table[128];
	char expected_parameters[96];
	struct dm_ioctl *io = (struct dm_ioctl *)buffer;
	struct dm_target_spec *target;
	char *record_end;
	char *parameters;
	char *parameters_end;
	uint64_t logical_sectors;
	int expected_parameters_length;
	size_t data_bytes;
	size_t record_bytes;
	size_t expected_record_bytes;
	size_t expected_next;
	size_t i;

	if (!buffer ||
	    ((uintptr_t)buffer % _Alignof(struct dm_ioctl)) != 0U ||
	    buffer_bytes < sizeof(*io) ||
	    swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					expected_table, &logical_sectors) < 0)
		return 0;
	expected_parameters_length = snprintf(
		expected_parameters, sizeof(expected_parameters),
		"%u:%u 0 64 0 2 0 1 0 0",
		manifest->target.device_major,
		manifest->target.device_minor);
	if (expected_parameters_length < 0 ||
	    (size_t)expected_parameters_length >= sizeof(expected_parameters)) {
		errno = EOVERFLOW;
		return 0;
	}
	expected_record_bytes = sizeof(*target) +
		(size_t)expected_parameters_length + 1U;
	expected_next = swapz_primary_dm_align8(expected_record_bytes);
	if (!expected_next || expected_next > UINT32_MAX) {
		errno = EOVERFLOW;
		return 0;
	}
	if (io->version[0] != DM_VERSION_MAJOR ||
	    io->data_size < sizeof(*io) || io->data_size > buffer_bytes ||
	    io->data_start != sizeof(*io) || io->data_start > io->data_size ||
	    io->target_count != 1U) {
		errno = EPROTO;
		return 0;
	}
	if (strnlen(io->name, sizeof(io->name)) == sizeof(io->name) ||
	    strnlen(io->uuid, sizeof(io->uuid)) == sizeof(io->uuid) ||
	    strcmp(io->name, mapper_name) || strcmp(io->uuid, mapper_uuid)) {
		errno = EPROTO;
		return 0;
	}
	data_bytes = (size_t)io->data_size - io->data_start;
	if (data_bytes < expected_record_bytes ||
	    data_bytes > expected_next) {
		errno = EPROTO;
		return 0;
	}
	target = (struct dm_target_spec *)((unsigned char *)buffer +
						 io->data_start);
	/*
	 * DM_TABLE_LOAD uses next=0 for this final target, but DM_TABLE_STATUS
	 * reports the aligned stride to the following target slot even when the
	 * table has only one target. Validate that exact stride; requiring the
	 * load representation here makes recovery reject a legitimate inactive
	 * table before it can clear and remove the transaction-owned mapper.
	 */
	if ((size_t)target->next != expected_next) {
		errno = EPROTO;
		return 0;
	}
	record_bytes = data_bytes;
	record_end = (char *)target + record_bytes;
	if ((size_t)(record_end - (char *)(target + 1)) == 0U ||
	    strnlen(target->target_type, sizeof(target->target_type)) ==
		    sizeof(target->target_type) ||
	    strcmp(target->target_type, "swapz") ||
	    target->sector_start != 0ULL || target->length != logical_sectors) {
		errno = EPROTO;
		return 0;
	}
	parameters = (char *)(target + 1);
	parameters_end = memchr(parameters, '\0',
				(size_t)(record_end - parameters));
	if (!parameters_end ||
	    (size_t)(parameters_end - parameters) !=
		    (size_t)expected_parameters_length ||
	    memcmp(parameters, expected_parameters,
		   (size_t)expected_parameters_length)) {
		errno = EPROTO;
		return 0;
	}
	for (i = (size_t)(parameters_end + 1 - (char *)target);
	     i < record_bytes; ++i) {
		if (((unsigned char *)target)[i]) {
			errno = EPROTO;
			return 0;
		}
	}
	return 1;
}

int swapz_primary_manifest_format(
	const struct swapz_primary_manifest *manifest, char *record,
	size_t capacity)
{
	uint64_t logical_pages;
	uint64_t logical_sectors;
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	int length;

	if (!swapz_primary_manifest_valid(manifest) || !record || !capacity) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	logical_pages = logical_sectors / SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	length = snprintf(record, capacity,
			  "schema=swapz-primary-manifest-v4\n"
			  "run_id=%s\n"
			  "source_sha=%s\n"
			  "swapzctl_sha256=%s\n"
			  "module_sha256=%s\n"
			  "qualification_report_sha256=%s\n"
			  "device_major=%u\n"
			  "device_minor=%u\n"
			  "partuuid=%s\n"
			  "device_bytes=%llu\n"
			  "backing_physical_blocks=%u\n"
			  "original_swap_active=%d\n"
			  "original_swap_priority=%d\n"
			  "original_header_sha256=%s\n"
			  "logical_pages=%llu\n"
			  "logical_sectors=%llu\n"
			  "mapper_name=%s\n"
			  "mapper_uuid=%s\n"
			  "dm_table=%s\n",
			  manifest->run_id, manifest->source_sha,
			  manifest->swapzctl_sha256, manifest->module_sha256,
			  manifest->qualification_report_sha256,
			  manifest->target.device_major,
			  manifest->target.device_minor,
			  manifest->target.partuuid,
			  (unsigned long long)manifest->target.device_bytes,
			  manifest->backing_physical_blocks,
			  manifest->original_swap_active,
			  manifest->original_swap_priority,
			  manifest->original_header_sha256,
			  (unsigned long long)logical_pages,
			  (unsigned long long)logical_sectors, mapper_name, mapper_uuid,
			  table);
	if (length < 0 || (size_t)length >= capacity ||
	    (size_t)length > SWAPZ_PRIMARY_STATE_RECORD_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	return length;
}

int swapz_primary_manifest_parse(const char *record, size_t length,
				 struct swapz_primary_manifest *manifest)
{
	struct swapz_primary_manifest parsed = {0};
	char value[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char canonical[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char expected[160];
	char device_major[32];
	char device_minor[32];
	char device_bytes[32];
	char backing_physical_blocks[32];
	char original_swap_active[8];
	char original_swap_priority[32];
	const char *cursor = record;
	const char *end;
	uint64_t logical_pages;
	uint64_t logical_sectors;
	uint64_t parsed_number;
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	int formatted_length;
	int canonical_length;

	if (!record || !manifest || !length ||
	    length > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    memchr(record, '\0', length))
		return -1;
	end = record + length;
	if (swapz_primary_manifest_expect_line(&cursor, end, "schema",
					      "swapz-primary-manifest-v4") < 0 ||
	    swapz_primary_manifest_take_line(&cursor, end, "run_id",
					     parsed.run_id,
					     sizeof(parsed.run_id)) < 0 ||
	    swapz_primary_manifest_take_line(&cursor, end, "source_sha",
					     parsed.source_sha,
					     sizeof(parsed.source_sha)) < 0 ||
	    swapz_primary_manifest_take_line(&cursor, end, "swapzctl_sha256",
					     parsed.swapzctl_sha256,
					     sizeof(parsed.swapzctl_sha256)) < 0 ||
	    swapz_primary_manifest_take_line(&cursor, end, "module_sha256",
					     parsed.module_sha256,
					     sizeof(parsed.module_sha256)) < 0 ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "qualification_report_sha256",
		    parsed.qualification_report_sha256,
		    sizeof(parsed.qualification_report_sha256)) < 0 ||
	    swapz_primary_manifest_take_line(&cursor, end, "device_major",
					     device_major,
					     sizeof(device_major)) < 0 ||
	    swapz_primary_parse_u64(device_major, &parsed_number) < 0 ||
	    !parsed_number || parsed_number > UINT32_MAX)
		return -1;
	parsed.target.device_major = (uint32_t)parsed_number;
	if (swapz_primary_manifest_take_line(&cursor, end, "device_minor",
					     device_minor,
					     sizeof(device_minor)) < 0 ||
	    swapz_primary_parse_u64(device_minor, &parsed_number) < 0 ||
	    parsed_number > UINT32_MAX)
		return -1;
	parsed.target.device_minor = (uint32_t)parsed_number;
	if (swapz_primary_manifest_take_line(&cursor, end, "partuuid",
					     parsed.target.partuuid,
					     sizeof(parsed.target.partuuid)) < 0 ||
	    !swapz_primary_partuuid_valid(parsed.target.partuuid) ||
	    swapz_primary_manifest_take_line(&cursor, end, "device_bytes",
					     device_bytes,
					     sizeof(device_bytes)) < 0 ||
	    swapz_primary_parse_u64(device_bytes, &parsed.target.device_bytes) < 0 ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "backing_physical_blocks",
		    backing_physical_blocks,
		    sizeof(backing_physical_blocks)) < 0 ||
	    swapz_primary_parse_u64(backing_physical_blocks, &parsed_number) < 0 ||
	    parsed_number > UINT32_MAX ||
	    !(parsed.backing_physical_blocks = (uint32_t)parsed_number) ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "original_swap_active",
		    original_swap_active, sizeof(original_swap_active)) < 0 ||
	    swapz_primary_parse_u64(original_swap_active, &parsed_number) < 0 ||
	    parsed_number > 1U ||
	    (parsed.original_swap_active = (int)parsed_number) < 0 ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "original_swap_priority",
		    original_swap_priority, sizeof(original_swap_priority)) < 0 ||
	    swapz_primary_parse_priority(
		    original_swap_priority, &parsed.original_swap_priority) < 0 ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "original_header_sha256",
		    parsed.original_header_sha256,
		    sizeof(parsed.original_header_sha256)) < 0 ||
	    !swapz_primary_manifest_valid(&parsed))
		return -1;
	logical_pages = swapz_primary_maximum_logical_pages(
		swapz_primary_manifest_physical_blocks(&parsed));
	if (!logical_pages ||
	    logical_pages > UINT64_MAX / SWAPZ_PRIMARY_SECTORS_PER_PAGE)
		return -1;
	logical_sectors = logical_pages * SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	if (swapz_primary_manifest_take_line(&cursor, end, "logical_pages",
					     value, sizeof(value)) < 0 ||
	    (formatted_length = snprintf(expected, sizeof(expected), "%llu",
			(unsigned long long)logical_pages)) < 0 ||
	    (size_t)formatted_length >= sizeof(expected) ||
	    strcmp(value, expected) ||
	    swapz_primary_manifest_take_line(&cursor, end, "logical_sectors",
					     value, sizeof(value)) < 0 ||
	    (formatted_length = snprintf(expected, sizeof(expected), "%llu",
			(unsigned long long)logical_sectors)) < 0 ||
	    (size_t)formatted_length >= sizeof(expected) ||
	    strcmp(value, expected))
		return -1;
	if (swapz_primary_mapper_layout(&parsed, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "mapper_name",
					      mapper_name) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "mapper_uuid",
					      mapper_uuid) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "dm_table", table) < 0)
		return -1;
	if (cursor != end)
		return -1;
	canonical_length = swapz_primary_manifest_format(
		&parsed, canonical, sizeof(canonical));
	if (canonical_length < 0 || (size_t)canonical_length != length ||
	    memcmp(canonical, record, length))
		return -1;
	*manifest = parsed;
	return 0;
}

static int swapz_primary_device_number_matches(dev_t device)
{
	/* A whole-disk parent commonly has minor 0 (for example, sda = 8:0). */
	return major(device) != 0U;
}

static int swapz_primary_same_target_identity(const struct stat *left,
					     const struct stat *right)
{
	if (!left || !right)
		return 0;
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	return S_ISREG(left->st_mode) && S_ISREG(right->st_mode) &&
	       left->st_dev == right->st_dev && left->st_ino == right->st_ino;
#else
	return S_ISBLK(left->st_mode) && S_ISBLK(right->st_mode) &&
	       swapz_primary_device_number_matches(left->st_rdev) &&
	       left->st_rdev == right->st_rdev;
#endif
}

static int swapz_primary_open_target_checked_paths_mode(
	const char *device_path, const char *uuid_path, const char *partuuid_path,
	int open_flags)
{
	struct stat device_before;
	struct stat uuid_before;
	struct stat partuuid_before;
	struct stat opened;
	struct stat device_after;
	struct stat uuid_after;
	struct stat partuuid_after;
	int fd;

	if (!device_path || !uuid_path || !partuuid_path ||
	    (open_flags != (O_RDWR | O_EXCL) && open_flags != O_RDONLY) ||
	    !swapz_primary_target_valid(&swapz_primary_selected_target)) {
		errno = EINVAL;
		return -1;
	}
	if (stat(device_path, &device_before) < 0 ||
	    stat(uuid_path, &uuid_before) < 0 ||
	    stat(partuuid_path, &partuuid_before) < 0)
		return -1;
	if (!swapz_primary_same_target_identity(&device_before, &uuid_before) ||
	    !swapz_primary_same_target_identity(&uuid_before, &partuuid_before)) {
		errno = ENODEV;
		return -1;
	}
	fd = open(uuid_path, open_flags | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0)
		goto failed;
	if (!swapz_primary_same_target_identity(&uuid_before, &opened) ||
	    stat(device_path, &device_after) < 0 ||
	    stat(uuid_path, &uuid_after) < 0 ||
	    stat(partuuid_path, &partuuid_after) < 0 ||
	    !swapz_primary_same_target_identity(&opened, &device_after) ||
	    !swapz_primary_same_target_identity(&opened, &uuid_after) ||
	    !swapz_primary_same_target_identity(&opened, &partuuid_after)) {
		errno = ENODEV;
		goto failed;
	}
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (opened.st_size < (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
		errno = EINVAL;
		goto failed;
	}
#else
	{
		uint64_t bytes = 0;

		if (ioctl(fd, BLKGETSIZE64, &bytes) < 0)
			goto failed;
		if (opened.st_rdev != makedev(
			    swapz_primary_selected_target.device_major,
			    swapz_primary_selected_target.device_minor) ||
		    bytes != swapz_primary_selected_target.device_bytes ||
		    swapz_primary_sysfs_partuuid_matches(
			    opened.st_rdev,
			    swapz_primary_selected_target.partuuid) < 0) {
			errno = EINVAL;
			goto failed;
		}
	}
#endif
	return fd;

failed:
	{
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
	}
	return -1;
}

static int swapz_primary_optional_uuid_matches_fd(
	const char *uuid_path, int fd)
{
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES];
	struct stat link_before;
	struct stat link_after;
	struct stat alias_info;
	struct stat opened_info;

	if (!uuid_path || fd < 0) {
		errno = EINVAL;
		return -1;
	}
	if (lstat(uuid_path, &link_before) < 0) {
		if (errno != ENOENT)
			return -1;
		/*
		 * A Linux swap UUID is optional. When no by-UUID alias exists, bind
		 * admission to the already selected PARTUUID/device geometry and the
		 * unchanged ordinary SWAPSPACE2 header instead of inventing another
		 * on-disk identity.
		 */
		if (!swapz_primary_target_valid(&swapz_primary_selected_target) ||
		    swapz_primary_exact_read(fd, header, sizeof(header)) < 0)
			return -1;
		if (!swapz_linux_swap_header_parse(
			    header, swapz_primary_selected_target.device_bytes,
			    NULL)) {
			memset(header, 0, sizeof(header));
			errno = ENODEV;
			return -1;
		}
		memset(header, 0, sizeof(header));
		errno = 0;
		return 0;
	}
	if (stat(uuid_path, &alias_info) < 0 ||
	    lstat(uuid_path, &link_after) < 0)
		return -1;
	if (link_before.st_dev != link_after.st_dev ||
	    link_before.st_ino != link_after.st_ino ||
	    link_before.st_mode != link_after.st_mode) {
		errno = ESTALE;
		return -1;
	}
	if (fstat(fd, &opened_info) < 0)
		return -1;
	if (!swapz_primary_same_target_identity(&alias_info, &opened_info)) {
		errno = ESTALE;
		return -1;
	}
	return 0;
}


static int swapz_primary_open_target_checked_partuuid_paths_mode(
	const char *device_path, const char *uuid_path, const char *partuuid_path,
	int open_flags)
{
	int fd = swapz_primary_open_target_checked_paths_mode(
		device_path, partuuid_path, partuuid_path, open_flags);

	if (fd < 0)
		return -1;
	if (swapz_primary_optional_uuid_matches_fd(uuid_path, fd) < 0) {
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
	return fd;
}

static int swapz_primary_target_open_readonly(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENOTSUP;
	return -1;
#else
	char partuuid_path[PATH_MAX];
	int length;

	if (!swapz_primary_target_valid(&swapz_primary_selected_target)) {
		errno = ENODEV;
		return -1;
	}
	if (swapz_primary_target_revalidate(
		    &swapz_primary_selected_target) < 0)
		return -1;
	length = snprintf(partuuid_path, sizeof(partuuid_path),
			  SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT,
			  SWAPZ_PRIMARY_PARTUUID);
	if (length < 0 || (size_t)length >= sizeof(partuuid_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return swapz_primary_open_target_checked_partuuid_paths_mode(
		partuuid_path, partuuid_path, partuuid_path, O_RDONLY);
#endif
}

int swapz_primary_target_open_exclusive(
	const struct swapz_primary_manifest *manifest)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)manifest;
	errno = ENOTSUP;
	return -1;
#else
	struct swapz_primary_target observed;
	char partuuid_path[PATH_MAX];
	int length;

	if (!swapz_primary_manifest_valid(manifest)) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_target_inspect(manifest->target.partuuid,
					 &observed) < 0)
		return -1;
	if (!swapz_primary_target_identity_equal(&manifest->target,
						 &observed)) {
		errno = ESTALE;
		return -1;
	}
	swapz_primary_selected_target = observed;
	length = snprintf(partuuid_path, sizeof(partuuid_path),
			  SWAPZ_PRIMARY_PARTUUID_PATH_FORMAT,
			  manifest->target.partuuid);
	if (length < 0 || (size_t)length >= sizeof(partuuid_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return swapz_primary_open_target_checked_partuuid_paths_mode(
		partuuid_path, partuuid_path, partuuid_path, O_RDWR | O_EXCL);
#endif
}

static int swapz_primary_original_swap_signature(
	const unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES],
	uint64_t device_bytes)
{
	return swapz_linux_swap_header_parse(block, device_bytes, NULL);
}


int swapz_primary_linux_swap_header_valid(
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	uint64_t logical_pages)
{
	/* Keep mapper validation identical to physical-backing validation. The
	 * mapper page count is already bounded to u32, so conversion to bytes
	 * cannot overflow and the shared validator remains the single authority. */
	if (logical_pages > UINT32_MAX)
		return 0;
	return swapz_linux_swap_header_valid(
		header, logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES);
}

static int swapz_primary_exact_read(int fd, unsigned char *buffer,
				    size_t length)
{
	size_t completed = 0;

	while (completed < length) {
		ssize_t count = pread(fd, buffer + completed,
				      length - completed, (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			return -1;
		}
		completed += (size_t)count;
	}
	return 0;
}

static int swapz_primary_sha256(const unsigned char *bytes, size_t length,
				char digest[65])
{
	static const uint32_t round_constants[64] = {
		0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
		0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
		0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
		0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
		0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
		0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
		0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
		0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
		0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
		0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
		0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
		0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
		0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
		0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
		0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
		0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U,
	};
	static const uint32_t initial_state[8] = {
		0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
		0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U,
	};
	static const char hex_digits[] = "0123456789abcdef";
	uint32_t state[8];
	uint64_t bit_length;
	size_t padded_length;
	size_t offset;
	size_t i;

	#define SWAPZ_ROTR32(value, shift) \
		(((value) >> (shift)) | ((value) << (32U - (shift))))

	if (!bytes || !digest) {
		errno = EINVAL;
		return -1;
	}
	if (length > UINT64_MAX / 8ULL || length > SIZE_MAX - 72U) {
		errno = EOVERFLOW;
		return -1;
	}
	bit_length = (uint64_t)length * 8ULL;
	padded_length = ((length + 9U + 63U) / 64U) * 64U;
	memcpy(state, initial_state, sizeof(state));
	for (offset = 0; offset < padded_length; offset += 64U) {
		unsigned char block[64];
		uint32_t words[64];
		uint32_t a, b, c, d, e, f, g, h;

		for (i = 0; i < sizeof(block); ++i) {
			size_t position = offset + i;

			if (position < length) {
				block[i] = bytes[position];
			} else if (position == length) {
				block[i] = 0x80U;
			} else if (position >= padded_length - 8U) {
				unsigned int shift = (unsigned int)(
					(padded_length - 1U - position) * 8U);

				block[i] = (unsigned char)(bit_length >> shift);
			} else {
				block[i] = 0;
			}
		}
		for (i = 0; i < 16U; ++i)
			words[i] = ((uint32_t)block[i * 4U] << 24) |
				   ((uint32_t)block[i * 4U + 1U] << 16) |
				   ((uint32_t)block[i * 4U + 2U] << 8) |
				   (uint32_t)block[i * 4U + 3U];
		for (i = 16U; i < 64U; ++i) {
			uint32_t small0 = SWAPZ_ROTR32(words[i - 15U], 7U) ^
					   SWAPZ_ROTR32(words[i - 15U], 18U) ^
					   (words[i - 15U] >> 3);
			uint32_t small1 = SWAPZ_ROTR32(words[i - 2U], 17U) ^
					   SWAPZ_ROTR32(words[i - 2U], 19U) ^
					   (words[i - 2U] >> 10);

			words[i] = words[i - 16U] + small0 + words[i - 7U] + small1;
		}
		a = state[0];
		b = state[1];
		c = state[2];
		d = state[3];
		e = state[4];
		f = state[5];
		g = state[6];
		h = state[7];
		for (i = 0; i < 64U; ++i) {
			uint32_t large1 = SWAPZ_ROTR32(e, 6U) ^
					  SWAPZ_ROTR32(e, 11U) ^
					  SWAPZ_ROTR32(e, 25U);
			uint32_t choose = (e & f) ^ (~e & g);
			uint32_t temp1 = h + large1 + choose + round_constants[i] +
					 words[i];
			uint32_t large0 = SWAPZ_ROTR32(a, 2U) ^
					  SWAPZ_ROTR32(a, 13U) ^
					  SWAPZ_ROTR32(a, 22U);
			uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
			uint32_t temp2 = large0 + majority;

			h = g;
			g = f;
			f = e;
			e = d + temp1;
			d = c;
			c = b;
			b = a;
			a = temp1 + temp2;
		}
		state[0] += a;
		state[1] += b;
		state[2] += c;
		state[3] += d;
		state[4] += e;
		state[5] += f;
		state[6] += g;
		state[7] += h;
	}
	for (i = 0; i < 8U; ++i) {
		unsigned int byte;

		for (byte = 0; byte < 4U; ++byte) {
			unsigned int shift = 24U - byte * 8U;
			unsigned char value = (unsigned char)(state[i] >> shift);

			digest[(i * 4U + byte) * 2U] = hex_digits[value >> 4];
			digest[(i * 4U + byte) * 2U + 1U] =
				hex_digits[value & 0x0fU];
		}
	}
	digest[64] = '\0';
	#undef SWAPZ_ROTR32
	return 0;
}


int swapz_primary_sha256_regular_fd(int fd, uid_t expected_owner,
				    uint64_t maximum_bytes, char digest[65])
{
	struct stat before;
	struct stat after;
	unsigned char *bytes = NULL;
	char verified[65];
	uint64_t length;
	size_t completed = 0;
	int flags;
	int result = -1;

	if (fd < 0 || !digest || !maximum_bytes ||
	    maximum_bytes > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES) {
		errno = EINVAL;
		return -1;
	}
	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		return -1;
	if ((flags & O_ACCMODE) != O_RDONLY) {
		errno = EBADF;
		return -1;
	}
	if (fstat(fd, &before) < 0)
		return -1;
	if (!S_ISREG(before.st_mode) || before.st_uid != expected_owner ||
	    (before.st_mode & 0022U) || before.st_nlink != 1 ||
	    before.st_size < 0) {
		errno = EPERM;
		return -1;
	}
	length = (uint64_t)before.st_size;
	if (length > maximum_bytes || length > SIZE_MAX) {
		errno = EFBIG;
		return -1;
	}
	bytes = malloc(length ? (size_t)length : 1U);
	if (!bytes)
		return -1;
	while (completed < (size_t)length) {
		ssize_t count = pread(fd, bytes + completed,
				      (size_t)length - completed,
				      (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto out;
		}
		completed += (size_t)count;
	}
	{
		unsigned char extra;
		ssize_t count;

		do {
			count = pread(fd, &extra, sizeof(extra), (off_t)length);
		} while (count < 0 && errno == EINTR);
		if (count != 0) {
			if (count > 0)
				errno = ESTALE;
			goto out;
		}
	}
	if (fstat(fd, &after) < 0)
		goto out;
	if (after.st_dev != before.st_dev || after.st_ino != before.st_ino ||
	    after.st_mode != before.st_mode || after.st_uid != before.st_uid ||
	    after.st_gid != before.st_gid || after.st_nlink != before.st_nlink ||
	    after.st_size != before.st_size ||
	    after.st_mtim.tv_sec != before.st_mtim.tv_sec ||
	    after.st_mtim.tv_nsec != before.st_mtim.tv_nsec ||
	    after.st_ctim.tv_sec != before.st_ctim.tv_sec ||
	    after.st_ctim.tv_nsec != before.st_ctim.tv_nsec) {
		errno = ESTALE;
		goto out;
	}
	if (swapz_primary_sha256(bytes, (size_t)length, verified) < 0)
		goto out;
	memcpy(digest, verified, sizeof(verified));
	result = 0;

out:
	free(bytes);
	return result;
}

static int swapz_primary_module_directory_owner_allowed(uid_t observed,
							 uid_t expected);

static int swapz_primary_open_private_directory_at(int parent_fd,
						   const char *name,
						   uid_t expected_owner)
{
	struct stat before;
	struct stat after;
	int fd;

	if (parent_fd < 0 || !name || !name[0] || strchr(name, '/') ||
	    !strcmp(name, ".") || !strcmp(name, "..")) {
		errno = EINVAL;
		return -1;
	}
	fd = openat(parent_fd, name,
		    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &before) < 0 ||
	    fstatat(parent_fd, name, &after, AT_SYMLINK_NOFOLLOW) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISDIR(before.st_mode) ||
	    !swapz_primary_module_directory_owner_allowed(before.st_uid,
							  expected_owner) ||
	    (before.st_mode & 0022U) || !S_ISDIR(after.st_mode) ||
	    after.st_dev != before.st_dev || after.st_ino != before.st_ino ||
	    after.st_uid != before.st_uid ||
	    !swapz_primary_module_directory_owner_allowed(after.st_uid,
							  expected_owner) ||
	    (after.st_mode & 0022U)) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	return fd;
}

static int swapz_primary_module_directory_owner_allowed(uid_t observed,
							 uid_t expected)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	return observed == 0 || observed == expected;
#else
	(void)expected;
	return observed == 0;
#endif
}

int swapz_primary_open_qualified_module_fd(
	const char *control_executable, const char expected_sha256[65])
{
	struct stat opened;
	struct stat named;
	char module_path[PATH_MAX];
	char digest[65];
	char *cursor;
	char *component;
	char *separator;
	char *end;
	int directory_fd = -1;
	int module_fd = -1;
	int length;
	size_t prefix_length;
	size_t remaining;
	uid_t expected_owner = 0;

#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	expected_owner = geteuid();
#endif

	if (!control_executable || control_executable[0] != '/' ||
	    !swapz_primary_valid_sha256(expected_sha256) ||
	    strlen(control_executable) >= PATH_MAX) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(module_path, sizeof(module_path), "%s",
			  control_executable);
	if (length < 0 || (size_t)length >= sizeof(module_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	length = (int)strlen(module_path);
	if (length <= (int)(sizeof(SWAPZ_PRIMARY_MODULE_SUFFIX) - 1U) ||
	    strcmp(module_path + length -
		   (int)(sizeof(SWAPZ_PRIMARY_MODULE_SUFFIX) - 1U),
		   SWAPZ_PRIMARY_MODULE_SUFFIX)) {
		errno = EPERM;
		return -1;
	}
	module_path[length -
		   (int)(sizeof(SWAPZ_PRIMARY_MODULE_SUFFIX) - 1U)] = '\0';
	prefix_length = strlen(module_path);
	remaining = sizeof(module_path) - prefix_length;
	length = snprintf(module_path + prefix_length, remaining, "/%s",
			  SWAPZ_PRIMARY_MODULE_RELATIVE_PATH);
	if (length < 0 || (size_t)length >= remaining) {
		errno = ENAMETOOLONG;
		return -1;
	}
	directory_fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
	if (directory_fd < 0)
		return -1;
	{
		struct stat root_info;

		if (fstat(directory_fd, &root_info) < 0) {
			goto failed;
		}
		if (!S_ISDIR(root_info.st_mode) ||
		    !swapz_primary_module_directory_owner_allowed(
			    root_info.st_uid, expected_owner) ||
		    (root_info.st_mode & 0022U)) {
			errno = EPERM;
			goto failed;
		}
	}
	cursor = module_path + 1U;
	for (;;) {
		component = cursor;
		separator = strchr(cursor, '/');
		if (!separator)
			break;
		if (separator == component) {
			errno = EINVAL;
			goto failed;
		}
		*separator = '\0';
		end = separator + 1U;
		{
			int next_fd;
			struct stat next_info;

			next_fd = swapz_primary_open_private_directory_at(
				directory_fd, component, expected_owner);

			if (next_fd < 0)
				goto failed;
			if (fstat(next_fd, &next_info) < 0) {
				int saved_errno = errno;

				close(next_fd);
				errno = saved_errno;
				goto failed;
			}
			if (!swapz_primary_module_directory_owner_allowed(
				    next_info.st_uid, expected_owner)) {
				close(next_fd);
				errno = EPERM;
				goto failed;
			}
			if (close(directory_fd) < 0) {
				directory_fd = next_fd;
				goto failed;
			}
			directory_fd = next_fd;
		}
		cursor = end;
	}
	if (!cursor[0] || strchr(cursor, '/')) {
		errno = EINVAL;
		goto failed;
	}
	module_fd = openat(directory_fd, cursor,
			   O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
	if (module_fd < 0)
		goto failed;
	if (fstat(module_fd, &opened) < 0 ||
	    fstatat(directory_fd, cursor, &named, AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (!S_ISREG(opened.st_mode) || opened.st_uid != expected_owner ||
	    (opened.st_mode & 0022U) || opened.st_nlink != 1U ||
	    opened.st_size <= 0 ||
	    (uint64_t)opened.st_size > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES ||
	    !S_ISREG(named.st_mode) || named.st_dev != opened.st_dev ||
	    named.st_ino != opened.st_ino || named.st_uid != opened.st_uid ||
	    (named.st_mode & 0022U) || named.st_nlink != 1U) {
		errno = EPERM;
		goto failed;
	}
	if (swapz_primary_sha256_regular_fd(
		    module_fd, expected_owner,
		    SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES, digest) < 0)
		goto failed;
	if (strcmp(digest, expected_sha256)) {
		errno = EBADMSG;
		goto failed;
	}
	if (fstat(module_fd, &named) < 0)
		goto failed;
	if (named.st_dev != opened.st_dev || named.st_ino != opened.st_ino ||
	    named.st_mode != opened.st_mode || named.st_uid != opened.st_uid ||
	    named.st_gid != opened.st_gid || named.st_nlink != opened.st_nlink ||
	    named.st_size != opened.st_size ||
	    fstatat(directory_fd, cursor, &named, AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (named.st_dev != opened.st_dev || named.st_ino != opened.st_ino ||
	    named.st_mode != opened.st_mode || named.st_uid != opened.st_uid ||
	    named.st_gid != opened.st_gid || named.st_nlink != opened.st_nlink ||
	    named.st_size != opened.st_size) {
		errno = ESTALE;
		goto failed;
	}
	if (close(directory_fd) < 0) {
		directory_fd = -1;
		goto failed;
	}
	return module_fd;

failed:
	{
		int saved_errno = errno ? errno : EIO;

		if (module_fd >= 0)
			close(module_fd);
		if (directory_fd >= 0)
			close(directory_fd);
		errno = saved_errno;
		return -1;
	}
}

static int swapz_primary_target_preflight(
	const char *partuuid, struct swapz_primary_target *target,
	uint64_t *device_bytes, int *original_swap_header,
	int *original_header_digest_available,
	unsigned char *original_header)
{
	char expected_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

	/*
	 * The input may point into target->partuuid. Snapshot it before clearing
	 * output state so exact revalidation also works for an aliased caller.
	 */
	if (!partuuid || !target ||
	    swapz_primary_partuuid_normalize(partuuid, expected_partuuid) < 0) {
		errno = EINVAL;
		return -1;
	}
	swapz_primary_selected_target_clear();
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	memset(target, 0, sizeof(*target));
	(void)device_bytes;
	(void)original_swap_header;
	(void)original_header_digest_available;
	(void)original_header;
	memset(expected_partuuid, 0, sizeof(expected_partuuid));
	errno = ENODEV;
	return -1;
#else
	unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES];
	char digest[65];
	int fd;

	if (!device_bytes || !original_swap_header ||
	    !original_header_digest_available) {
		errno = EINVAL;
		memset(expected_partuuid, 0, sizeof(expected_partuuid));
		return -1;
	}
	*original_swap_header = 0;
	*original_header_digest_available = 0;
	memset(target, 0, sizeof(*target));
	if (swapz_primary_target_inspect(expected_partuuid, target) < 0) {
		memset(expected_partuuid, 0, sizeof(expected_partuuid));
		return -1;
	}
	swapz_primary_selected_target = *target;
	fd = swapz_primary_target_open_readonly();
	if (fd < 0) {
		memset(expected_partuuid, 0, sizeof(expected_partuuid));
		return -1;
	}
	memset(expected_partuuid, 0, sizeof(expected_partuuid));
	*device_bytes = target->device_bytes;
	if (swapz_primary_exact_read(fd, block, sizeof(block)) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	*original_swap_header = swapz_primary_original_swap_signature(
		block, target->device_bytes);
	if (swapz_primary_sha256(block, sizeof(block), digest) < 0) {
		int saved_errno = errno;

		memset(block, 0, sizeof(block));
		errno = saved_errno;
		return -1;
	}
	*original_header_digest_available = 1;
	if (original_header)
		memcpy(original_header, block, sizeof(block));
	memset(block, 0, sizeof(block));
	return 0;
#endif
}

static int swapz_primary_parse_u64(const char *text, uint64_t *value)
{
	uint64_t parsed = 0;
	const unsigned char *cursor = (const unsigned char *)text;

	if (!text || !*text || !value)
		return -1;
	while (*cursor) {
		unsigned int digit;

		if (*cursor < '0' || *cursor > '9')
			return -1;
		digit = (unsigned int)(*cursor - '0');
		if (parsed > (UINT64_MAX - digit) / 10U)
			return -1;
		parsed = parsed * 10U + digit;
		++cursor;
	}
	*value = parsed;
	return 0;
}

static int swapz_primary_parse_priority(const char *text, int *priority)
{
	uint64_t magnitude;
	int negative = 0;

	if (!text || !*text || !priority)
		return -1;
	if (*text == '-') {
		negative = 1;
		++text;
	}
	if (swapz_primary_parse_u64(text, &magnitude) < 0 ||
	    magnitude > (uint64_t)INT_MAX + (unsigned int)negative)
		return -1;
	if (negative && magnitude == (uint64_t)INT_MAX + 1U)
		*priority = INT_MIN;
	else
		*priority = negative ? -(int)magnitude : (int)magnitude;
	return 0;
}

static int swapz_primary_swap_priority_restorable(int priority)
{
	/*
	 * Explicit util-linux priorities occupy 0..32767 and can be reproduced
	 * exactly. Negative values are kernel-assigned low-priority policy; a
	 * later plain swapon may choose a different negative number, so admission
	 * must preserve the policy class rather than reject ordinary swap.
	 */
	return priority <= 32767;
}

static int swapz_primary_parse_dev_number(const char *text, dev_t *device)
{
	const char *colon;
	char major_text[32];
	uint64_t major_number;
	uint64_t minor_number;
	size_t major_length;

	if (!text || !device) {
		errno = EINVAL;
		return -1;
	}
	colon = strchr(text, ':');
	if (!colon || strchr(colon + 1, ':')) {
		errno = EINVAL;
		return -1;
	}
	major_length = (size_t)(colon - text);
	if (!major_length || major_length >= sizeof(major_text)) {
		errno = EINVAL;
		return -1;
	}
	memcpy(major_text, text, major_length);
	major_text[major_length] = '\0';
	if (swapz_primary_parse_u64(major_text, &major_number) < 0 ||
	    swapz_primary_parse_u64(colon + 1, &minor_number) < 0 ||
	    major_number > UINT_MAX || minor_number > UINT_MAX) {
		errno = EINVAL;
		return -1;
	}
	*device = makedev((unsigned int)major_number,
			  (unsigned int)minor_number);
	if (major(*device) != major_number || minor(*device) != minor_number) {
		errno = ERANGE;
		return -1;
	}
	return 0;
}

static int swapz_primary_split_fields(char *line, char **fields,
				      size_t field_capacity, size_t *field_count)
{
	char *cursor = line;
	size_t count = 0;

	while (*cursor) {
		while (*cursor && isspace((unsigned char)*cursor))
			++cursor;
		if (!*cursor)
			break;
		if (count == field_capacity)
			return -1;
		fields[count++] = cursor;
		while (*cursor && !isspace((unsigned char)*cursor))
			++cursor;
		if (*cursor)
			*cursor++ = '\0';
	}
	*field_count = count;
	return 0;
}

static int swapz_primary_parse_swaps(const char *text,
				     struct swapz_primary_swap_entry *entries,
				     size_t capacity, size_t *entry_count)
{
	const char *line = text;
	int header_seen = 0;
	size_t count = 0;

	if (!text || !entries || !entry_count || !capacity)
		return -1;
	while (*line) {
		char buffer[PATH_MAX + 128U];
		char *fields[6];
		const char *end = strchr(line, '\n');
		size_t length = end ? (size_t)(end - line) : strlen(line);
		size_t field_count = 0;

		if (length >= sizeof(buffer))
			return -1;
		memcpy(buffer, line, length);
		buffer[length] = '\0';
		line = end ? end + 1 : line + length;
		if (!buffer[0])
			continue;
		if (swapz_primary_split_fields(buffer, fields,
					      sizeof(fields) / sizeof(fields[0]),
					      &field_count) < 0)
			return -1;
		if (!header_seen) {
			if (field_count != 5U || strcmp(fields[0], "Filename") ||
			    strcmp(fields[1], "Type") || strcmp(fields[2], "Size") ||
			    strcmp(fields[3], "Used") || strcmp(fields[4], "Priority"))
				return -1;
			header_seen = 1;
			continue;
		}
		if (field_count != 5U || count == capacity ||
		    strlen(fields[0]) >= sizeof(entries[count].path) ||
		    strlen(fields[1]) >= sizeof(entries[count].type) ||
		    !fields[0][0] || !fields[1][0] ||
		    swapz_primary_parse_u64(fields[2], &entries[count].size_kib) < 0 ||
		    swapz_primary_parse_u64(fields[3], &entries[count].used_kib) < 0 ||
		    swapz_primary_parse_priority(fields[4],
						&entries[count].priority) < 0)
			return -1;
		strcpy(entries[count].path, fields[0]);
		strcpy(entries[count].type, fields[1]);
		{
			size_t prior;

			for (prior = 0; prior < count; ++prior)
				if (!strcmp(entries[prior].path, entries[count].path))
					return -1;
		}
		++count;
	}
	if (!header_seen)
		return -1;
	*entry_count = count;
	return 0;
}

static int swapz_primary_read_swap_inventory(
	struct swapz_primary_swap_entry *entries, size_t capacity,
	size_t *entry_count)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)entries;
	(void)capacity;
	(void)entry_count;
	errno = ENODEV;
	return -1;
#else
	char buffer[SWAPZ_PRIMARY_PLAN_BUFFER_BYTES];
	size_t used = 0;
	int fd = open("/proc/swaps", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

	if (fd < 0)
		return -1;
	while (used + 1U < sizeof(buffer)) {
		ssize_t count = read(fd, buffer + used, sizeof(buffer) - used - 1U);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used + 1U == sizeof(buffer)) {
		errno = EOVERFLOW;
		return -1;
	}
	buffer[used] = '\0';
	return swapz_primary_parse_swaps(buffer, entries, capacity, entry_count);
#endif
}

static int swapz_primary_swap_inventory_target_is_quiescent(
	const struct swapz_primary_swap_entry *entries,
	const dev_t *resolved_devices, const unsigned char *resolved_is_block,
	size_t count, dev_t target_device, uint64_t target_size_kib)
{
	size_t index;
	unsigned int target_entries = 0;

	if (!entries || !resolved_devices || !resolved_is_block ||
	    !target_size_kib) {
		errno = EINVAL;
		return -1;
	}
	for (index = 0; index < count; ++index) {
		if (!strcmp(entries[index].type, "file")) {
			/* A swapfile's st_dev is the backing filesystem device. */
			if (resolved_is_block[index]) {
				errno = EINVAL;
				return -1;
			}
			if (resolved_devices[index] == target_device) {
				errno = EBUSY;
				return -1;
			}
			continue;
		}
		if (strcmp(entries[index].type, "partition") ||
		    !resolved_is_block[index]) {
			errno = EINVAL;
			return -1;
		}
		if (resolved_devices[index] != target_device)
			continue;
		++target_entries;
		if (target_entries > 1U ||
		    strcmp(entries[index].type, "partition") ||
		    entries[index].size_kib != target_size_kib ||
		    entries[index].used_kib != 0U) {
			errno = EBUSY;
			return -1;
		}
	}
	return 0;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_original_swap_policy_snapshot(
	uint64_t target_size_kib, int *active, int *priority)
{
	struct swapz_primary_swap_entry entries[SWAPZ_PRIMARY_SWAP_ROWS_MAX];
	dev_t resolved_devices[SWAPZ_PRIMARY_SWAP_ROWS_MAX] = {0};
	unsigned char resolved_is_block[SWAPZ_PRIMARY_SWAP_ROWS_MAX] = {0};
	struct stat info;
	size_t count = 0;
	size_t index;

	if (!target_size_kib ||
	    !swapz_primary_target_valid(&swapz_primary_selected_target)) {
		errno = ENODEV;
		return -1;
	}
	if (active)
		*active = 0;
	if (priority)
		*priority = 0;
	if (swapz_primary_read_swap_inventory(
		    entries, SWAPZ_PRIMARY_SWAP_ROWS_MAX, &count) < 0)
		return -1;
	/*
	 * Resolve every entry so aliases of the selected partition cannot hide
	 * behind another pathname. PREPARE records activation policy only.
	 */
	for (index = 0; index < count; ++index) {
		if (stat(entries[index].path, &info) < 0)
			return -1;
		if (!strcmp(entries[index].type, "partition") &&
		    S_ISBLK(info.st_mode)) {
			resolved_devices[index] = info.st_rdev;
			resolved_is_block[index] = 1U;
		} else if (!strcmp(entries[index].type, "file") &&
			   S_ISREG(info.st_mode)) {
			resolved_devices[index] = info.st_dev;
		} else {
			errno = EINVAL;
			return -1;
		}
	}
	if (swapz_primary_swap_inventory_target_is_quiescent(
		    entries, resolved_devices, resolved_is_block, count,
		    SWAPZ_PRIMARY_TARGET_DEVICE, target_size_kib) < 0)
		return -1;
	for (index = 0; index < count; ++index) {
		if (!resolved_is_block[index] ||
		    resolved_devices[index] != SWAPZ_PRIMARY_TARGET_DEVICE)
			continue;
		if (active)
			*active = 1;
		if (priority)
			*priority = entries[index].priority;
		break;
	}
	return 0;
}

static int swapz_primary_original_swap_is_quiescent(
	uint64_t target_size_kib)
{
	return swapz_primary_original_swap_policy_snapshot(
		target_size_kib, NULL, NULL);
}
#endif

static int swapz_primary_valid_partuuid(const char *partuuid)
{
	return swapz_primary_partuuid_valid(partuuid);
}

static int swapz_primary_recovery_base_open(const char *path,
						    uid_t expected_owner)
{
	struct stat before;
	struct stat opened;
	char prefix[PATH_MAX];
	const char *component;
	const char *cursor;
	size_t length;
	size_t i;
	int fd;

	if (!path || path[0] != '/') {
		errno = EINVAL;
		return -1;
	}
	component = path + 1;
	for (cursor = component; ; ++cursor) {
		if (*cursor != '/' && *cursor != '\0')
			continue;
		if (cursor == component ||
		    (cursor - component == 1 && component[0] == '.') ||
		    (cursor - component == 2 && component[0] == '.' &&
		     component[1] == '.')) {
			errno = EINVAL;
			return -1;
		}
		if (!*cursor)
			break;
		component = cursor + 1;
	}
	length = strlen(path);
	if (length < 2U || length >= sizeof(prefix) || path[length - 1U] == '/') {
		errno = EINVAL;
		return -1;
	}
	memcpy(prefix, path, length + 1U);
	for (i = 1U; i <= length; ++i) {
		if (prefix[i] != '/' && prefix[i] != '\0')
			continue;
		if (prefix[i] == '/' && prefix[i + 1U] == '\0') {
			errno = EINVAL;
			return -1;
		}
		prefix[i] = '\0';
		if (lstat(prefix, &before) < 0 || !S_ISDIR(before.st_mode) ||
		    (before.st_uid != 0 && before.st_uid != expected_owner) ||
		    (before.st_mode & (S_IWGRP | S_IWOTH))) {
			errno = EPERM;
			return -1;
		}
		if (i < length)
			prefix[i] = '/';
	}
	if (stat(path, &before) < 0 || before.st_uid != expected_owner ||
	    (before.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	fd = open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISDIR(opened.st_mode) || opened.st_dev != before.st_dev ||
	    opened.st_ino != before.st_ino || opened.st_uid != expected_owner ||
	    (opened.st_mode & 0777U) != 0700U) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	return fd;
}

static int swapz_primary_runtime_state_base_open(uid_t expected_owner)
{
#ifndef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	if (expected_owner != 0) {
		errno = EPERM;
		return -1;
	}
	/*
	 * /run is root-owned and volatile. mkdir() cannot replace an existing
	 * object; swapz_primary_recovery_base_open() then rejects symlinks,
	 * foreign ownership, writable parent components or an unsafe mode.
	 */
	if (mkdir(SWAPZ_PRIMARY_RUNTIME_STATE_BASE, 0700) < 0 &&
	    errno != EEXIST)
		return -1;
#endif
	return swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RUNTIME_STATE_BASE, expected_owner);
}

#if !defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && !defined(SWAPZ_PRIMARY_ROOTLESS_TEST)
static int swapz_primary_runtime_state_parent_open(void)
{
	struct stat before;
	struct stat opened;
	int fd;

	if (lstat(SWAPZ_PRIMARY_EXECUTION_RUNTIME_PARENT, &before) < 0 ||
	    !S_ISDIR(before.st_mode) || before.st_uid != 0 ||
	    (before.st_mode & (S_IWGRP | S_IWOTH))) {
		errno = EPERM;
		return -1;
	}
	fd = open(SWAPZ_PRIMARY_EXECUTION_RUNTIME_PARENT,
		  O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISDIR(opened.st_mode) || opened.st_dev != before.st_dev ||
	    opened.st_ino != before.st_ino || opened.st_uid != 0 ||
	    (opened.st_mode & (S_IWGRP | S_IWOTH))) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	return fd;
}
#endif

static int swapz_primary_runtime_state_fs_magic(long type)
{
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	/*
	 * The owned-nullblk rehearsal isolates this path under its root-only test
	 * tree. Production runtime ownership never uses a block-backed filesystem.
	 */
	switch ((unsigned long)type) {
	case EXT2_SUPER_MAGIC:
	case XFS_SUPER_MAGIC:
	case F2FS_SUPER_MAGIC:
	case BTRFS_SUPER_MAGIC:
		return 1;
	default:
		return 0;
	}
#else
	return (unsigned long)type == TMPFS_MAGIC;
#endif
}

static int swapz_primary_path_format(char *path, size_t capacity,
				     const char *format, ...)
{
	va_list arguments;
	int length;

	va_start(arguments, format);
	length = vsnprintf(path, capacity, format, arguments);
	va_end(arguments);
	if (length < 0 || (size_t)length >= capacity) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return 0;
}

static int swapz_primary_read_sysfs_text(const char *path, char *buffer,
					size_t capacity)
{
	size_t length = 0;
	int fd;

	if (!path || !buffer || capacity < 2U) {
		errno = EINVAL;
		return -1;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	while (length + 1U < capacity) {
		ssize_t count = read(fd, buffer + length, capacity - length - 1U);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		length += (size_t)count;
	}
	if (length + 1U == capacity) {
		close(fd);
		errno = EOVERFLOW;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	while (length && (buffer[length - 1U] == '\n' ||
			  buffer[length - 1U] == '\r'))
		--length;
	buffer[length] = '\0';
	return 0;
}

static int swapz_primary_sysfs_dev_number(const char *path, dev_t *device)
{
	char buffer[64];

	if (!device || swapz_primary_read_sysfs_text(path, buffer,
						     sizeof(buffer)) < 0)
		return -1;
	return swapz_primary_parse_dev_number(buffer, device);
}


static int swapz_primary_mountinfo_path_valid(const char *path)
{
	size_t length;
	size_t index = 0;

	if (!path || path[0] != '/')
		return 0;
	length = strlen(path);
	while (index < length) {
		unsigned int escaped_byte;

		if (path[index] != '\\') {
			++index;
			continue;
		}
		if (length - index < 4U || path[index + 1U] < '0' ||
		    path[index + 1U] > '7' || path[index + 2U] < '0' ||
		    path[index + 2U] > '7' || path[index + 3U] < '0' ||
		    path[index + 3U] > '7')
			return 0;
		escaped_byte = ((unsigned int)(path[index + 1U] - '0') << 6) |
			       ((unsigned int)(path[index + 2U] - '0') << 3) |
			       (unsigned int)(path[index + 3U] - '0');
		if (escaped_byte != ' ' && escaped_byte != '\t' &&
		    escaped_byte != '\n' && escaped_byte != '\\')
			return 0;
		index += 4U;
	}
	return 1;
}

static int swapz_primary_mountinfo_device_valid(const char *identity,
						dev_t *device)
{
	const char *colon;

	if (!identity || !device)
		return 0;
	colon = strchr(identity, ':');
	if (!colon || colon == identity || !colon[1] || strchr(colon + 1, ':'))
		return 0;
	if ((identity[0] == '0' && colon != identity + 1) ||
	    (colon[1] == '0' && colon[2] != '\0'))
		return 0;
	return swapz_primary_parse_dev_number(identity, device) == 0;
}

static int swapz_primary_mountinfo_rw_options_valid(const char *options)
{
	size_t length;

	if (!options)
		return 0;
	length = strlen(options);
	if (length < 2U)
		return 0;
	if ((memcmp(options, "ro", 2U) && memcmp(options, "rw", 2U)) ||
	    (length > 2U && options[2] != ','))
		return 0;
	return 1;
}

static int swapz_primary_mountinfo_optional_valid(const char *field,
						   unsigned int *seen_fields)
{
	static const struct {
		const char *name;
		unsigned int bit;
	} numeric_fields[] = {
		{ "shared", 1U << 0 },
		{ "master", 1U << 1 },
		{ "propagate_from", 1U << 2 },
	};
	size_t index;

	if (!field || !field[0] || !seen_fields)
		return 0;
	if (!strcmp(field, "unbindable")) {
		const unsigned int bit = 1U << 3;

		if (*seen_fields & bit)
			return 0;
		*seen_fields |= bit;
		return 1;
	}
	if (!strncmp(field, "unbindable:", sizeof("unbindable:") - 1U))
		return 0;
	for (index = 0;
	     index < sizeof(numeric_fields) / sizeof(numeric_fields[0]);
	     ++index) {
		const size_t name_length = strlen(numeric_fields[index].name);
		const char *number;
		uint64_t identifier;

		if (!strcmp(field, numeric_fields[index].name))
			return 0;
		if (strncmp(field, numeric_fields[index].name, name_length) ||
		    field[name_length] != ':')
			continue;
		number = field + name_length + 1U;
		if ((*seen_fields & numeric_fields[index].bit) || !number[0] ||
		    number[0] == '0' ||
		    swapz_primary_parse_u64(number, &identifier) < 0 ||
		    !identifier || identifier > (uint64_t)INT_MAX)
			return 0;
		if (numeric_fields[index].bit == (1U << 2) &&
		    !(*seen_fields & (1U << 1)))
			return 0;
		*seen_fields |= numeric_fields[index].bit;
		return 1;
	}
	return 1;
}

static int swapz_primary_mount_identifier_compare(const void *left,
						   const void *right)
{
	const uint32_t first = *(const uint32_t *)left;
	const uint32_t second = *(const uint32_t *)right;

	return (first > second) - (first < second);
}

struct swapz_primary_mount_facts {
	dev_t root_device;
	int root_mount_seen;
	int target_mounted;
};

static int swapz_primary_parse_mountinfo(const char *text,
					       dev_t target_device,
					       dev_t parent_device,
					       struct swapz_primary_mount_facts *facts)
{
	const char *line = text;
	const char *cursor;
	struct swapz_primary_mount_facts parsed = {0};
	uint32_t *mount_ids = NULL;
	size_t mount_count = 0;
	size_t mount_capacity = 0;

	if (!text || !facts) {
		errno = EINVAL;
		return -1;
	}
	for (cursor = text; *cursor; ++cursor)
		if (*cursor == '\n')
			++mount_capacity;
	if (!mount_capacity ||
	    mount_capacity > SIZE_MAX / sizeof(*mount_ids)) {
		errno = EINVAL;
		return -1;
	}
	mount_ids = malloc(mount_capacity * sizeof(*mount_ids));
	if (!mount_ids)
		return -1;
	while (*line) {
		char buffer[8192];
		char *fields[64];
		char *separator;
		size_t length;
		size_t field_count = 0;
		size_t i;
		size_t separator_index = SIZE_MAX;
		unsigned int optional_fields = 0;
		uint64_t mount_id;
		uint64_t parent_id;
		dev_t mounted_device;
		const char *end = strchr(line, '\n');

		if (!end)
			goto invalid;
		length = (size_t)(end - line);
		if (!length || length >= sizeof(buffer))
			goto invalid;
		memcpy(buffer, line, length);
		buffer[length] = '\0';
		line = end + 1;
		separator = strstr(buffer, " - ");
		if (!separator)
			goto invalid;
		if (swapz_primary_split_fields(buffer, fields,
					      sizeof(fields) / sizeof(fields[0]),
					      &field_count) < 0 ||
		    field_count < 10U || fields[0][0] == '0' ||
		    fields[1][0] == '0' ||
		    swapz_primary_parse_u64(fields[0], &mount_id) < 0 ||
		    swapz_primary_parse_u64(fields[1], &parent_id) < 0 ||
		    !mount_id || !parent_id || mount_id > (uint64_t)INT_MAX ||
		    parent_id > (uint64_t)INT_MAX ||
		    !swapz_primary_mountinfo_device_valid(
			    fields[2], &mounted_device) ||
		    !fields[3][0] ||
		    !swapz_primary_mountinfo_path_valid(fields[4]) ||
		    !swapz_primary_mountinfo_rw_options_valid(fields[5]))
			goto invalid;
		for (i = 0; i < field_count; ++i)
			if (fields[i] == separator + 1) {
				separator_index = i;
				break;
			}
		if (separator_index < 6U ||
		    separator_index + 4U != field_count)
			goto invalid;
		for (i = 6U; i < separator_index; ++i)
			if (!swapz_primary_mountinfo_optional_valid(
				    fields[i], &optional_fields))
				goto invalid;
		if (!swapz_primary_mountinfo_rw_options_valid(
			    fields[separator_index + 3U]))
			goto invalid;
		if (mount_count >= mount_capacity)
			goto invalid;
		mount_ids[mount_count++] = (uint32_t)mount_id;
		if (mounted_device == target_device ||
		    (parent_device && mounted_device == parent_device))
			parsed.target_mounted = 1;
		if (!strcmp(fields[4], "/")) {
			if (parsed.root_mount_seen)
				goto invalid;
			parsed.root_mount_seen = 1;
			parsed.root_device = mounted_device;
		}
	}
	if (!parsed.root_mount_seen || mount_count != mount_capacity)
		goto invalid;
	qsort(mount_ids, mount_count, sizeof(*mount_ids),
	      swapz_primary_mount_identifier_compare);
	for (size_t index = 1U; index < mount_count; ++index)
		if (mount_ids[index] == mount_ids[index - 1U])
			goto invalid;
	free(mount_ids);
	*facts = parsed;
	return 0;

invalid:
	free(mount_ids);
	errno = EINVAL;
	return -1;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_proc_entry_is_pid(const char *name)
{
	const unsigned char *cursor;

	if (!name || !name[0])
		return 0;
	for (cursor = (const unsigned char *)name; *cursor; ++cursor)
		if (*cursor < '0' || *cursor > '9')
			return 0;
	return 1;
}

static int swapz_primary_mountinfo_read_fd(
	int fd, dev_t parent_device, struct swapz_primary_mount_facts *facts,
	size_t *bytes_read)
{
	char initial_buffer[SWAPZ_PRIMARY_MOUNTINFO_INITIAL_BYTES];
	char *buffer = initial_buffer;
	char *expanded_buffer = NULL;
	size_t capacity = sizeof(initial_buffer);
	size_t used = 0;
	int read_error = 0;
	int parse_result;
	int parse_errno;

	if (fd < 0 || !facts) {
		errno = EINVAL;
		return -1;
	}
	for (;;) {
		ssize_t count;

		if (used + 1U == capacity) {
			if (capacity == SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES) {
				/* Do not interpret a truncated table as a clear view.
				 * Report no process, mount or host identifiers.
				 */
				(void)fprintf(stderr,
					      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
					      "step=mountinfo-read errno=%d "
					      "reason=per-table-byte-limit\n",
					      EOVERFLOW);
				read_error = EOVERFLOW;
				break;
			}
			expanded_buffer =
				malloc(SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES);
			if (!expanded_buffer) {
				read_error = errno ? errno : ENOMEM;
				break;
			}
			memcpy(expanded_buffer, initial_buffer, used);
			buffer = expanded_buffer;
			capacity = SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES;
		}
		count = read(fd, buffer + used, capacity - used - 1U);
		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			read_error = errno ? errno : EIO;
			if (read_error == EOVERFLOW)
				(void)fprintf(stderr,
					      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
					      "step=mountinfo-read errno=%d "
					      "reason=read-overflow\n",
					      read_error);
			break;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0 && !read_error)
		read_error = errno ? errno : EIO;
	if (read_error) {
		free(expanded_buffer);
		errno = read_error;
		return -1;
	}
	if (!used || buffer[used - 1U] != '\n' ||
	    memchr(buffer, '\0', used)) {
		/* An empty, unterminated or NUL-containing snapshot must
		 * remain a refusal. Report only the fixed framing category.
		 */
		free(expanded_buffer);
		(void)fprintf(stderr,
			      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
			      "step=mountinfo-read errno=%d "
			      "reason=malformed-mountinfo-frame\n", EINVAL);
		errno = EINVAL;
		return -1;
	}
	buffer[used] = '\0';
	parse_result = swapz_primary_parse_mountinfo(
		buffer, SWAPZ_PRIMARY_TARGET_DEVICE, parent_device, facts);
	parse_errno = errno;
	free(expanded_buffer);
	if (parse_result < 0) {
		if (parse_errno == EINVAL)
			(void)fprintf(stderr,
				      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
				      "step=mountinfo-parse errno=%d "
				      "reason=malformed-mountinfo\n", EINVAL);
		errno = parse_errno ? parse_errno : EINVAL;
		return -1;
	}
	if (bytes_read)
		*bytes_read = used;
	return 0;
}

/*
 * Linux filters a task's mountinfo by the task's filesystem root at open time.
 * Pre/post root strings cannot authenticate the view: a task can chroot for
 * the mountinfo open and restore its root before the second observation.
 *
 * Pin the task's mount namespace, use the task root only as a seed for its
 * unique mount ID, walk mount parents to the namespace root, then enumerate
 * that pinned namespace directly. A PID/root replacement after the namespace
 * pin either still names a mount in the same complete namespace or fails the
 * namespace-scoped statmount lookup. Unsupported or ambiguous inventory is a
 * refusal; never fall back to a filtered mountinfo view as proof of clearance.
 *
 * The FIXTURE_DIAGNOSTIC_BYTES fallback exists only for the separate extracted
 * lifecycle fixture, which intentionally isolates the final revalidation
 * coordinator. Production uses the stable Linux syscall numbers for the
 * project's x86_64/arm64 targets even when libc headers predate the names; an
 * older running kernel returns ENOSYS and remains fail-closed. The owned
 * production mount-namespace fixture exercises the real namespace enumeration.
 */
static int swapz_primary_mountinfo_full_root(
	const char *namespace_path, const char *root_path,
	const struct stat *expected_namespace_info, dev_t parent_device,
	dev_t expected_process_root_device,
	int require_process_root_matches_init)
{
#ifdef FIXTURE_DIAGNOSTIC_BYTES
	char root_link[PATH_MAX];
	ssize_t root_length;

	(void)namespace_path;
	(void)expected_namespace_info;
	(void)parent_device;
	(void)expected_process_root_device;
	(void)require_process_root_matches_init;
	if (!root_path) {
		errno = EINVAL;
		return -1;
	}
	root_length = readlink(root_path, root_link, sizeof(root_link));
	if (root_length < 0)
		return -1;
	if (root_length != 1 || root_link[0] != '/') {
		errno = EAGAIN;
		return -1;
	}
	return 0;
#else
#if !defined(__x86_64__) && !defined(__aarch64__)
	(void)namespace_path;
	(void)root_path;
	(void)expected_namespace_info;
	(void)parent_device;
	(void)expected_process_root_device;
	(void)require_process_root_matches_init;
	errno = EOPNOTSUPP;
	return -1;
#else
	enum {
		statmount_syscall_number = 457,
		listmount_syscall_number = 458,
		mount_id_request_bytes = 32U,
		namespace_mount_batch = 256U,
		namespace_parent_depth_max = 4096U,
		statmount_fixed_bytes = 512U,
	};
	const uint64_t statmount_required_mask = 0x00000003ULL;
	const unsigned int statx_mount_id_unique = 0x00004000U;
	const unsigned int statx_root_request_mask =
		STATX_BASIC_STATS | statx_mount_id_unique;
	const unsigned int statx_root_identity_mask = STATX_TYPE | STATX_INO;
	const unsigned int statx_root_required_mask =
		STATX_TYPE | STATX_INO | statx_mount_id_unique;
	struct mount_id_request {
		uint32_t size;
		uint32_t namespace_reserved;
		uint64_t mount_id;
		uint64_t parameter;
		uint64_t namespace_id;
	};
	struct statmount_basic {
		uint32_t size;
		uint32_t mount_options_offset;
		uint64_t mask;
		uint32_t superblock_device_major;
		uint32_t superblock_device_minor;
		uint64_t superblock_magic;
		uint32_t superblock_flags;
		uint32_t filesystem_type_offset;
		uint64_t mount_id;
		uint64_t parent_mount_id;
		/* Keep the complete fixed statmount UAPI buffer. */
		uint64_t reserved[(statmount_fixed_bytes - 56U) /
				  sizeof(uint64_t)];
	};
	struct mount_id_request request = {0};
	struct statmount_basic mount_status;
	struct stat opened_namespace_info;
	struct statx root_info = {0};
	struct statx init_root_info = {0};
	struct statx confirmed_root_info = {0};
	struct statx confirmed_init_root_info = {0};
	uint64_t mount_ids[namespace_mount_batch];
	uint64_t current_mount_id;
	uint64_t pinned_namespace_id = 0;
	uint64_t root_mount_id;
	uint64_t namespace_root_mount_id = 0;
	uint64_t last_mount_id = 0;
	size_t mount_count = 0;
	int namespace_fd = -1;
	int result = -1;
	int saved_errno = 0;
	const char *failure_step = "namespace-fd";
	const char *failure_reason = NULL;

	_Static_assert(sizeof(struct mount_id_request) == mount_id_request_bytes,
		       "mount ID request ABI size changed");
	_Static_assert(sizeof(struct statmount_basic) == statmount_fixed_bytes,
		       "statmount fixed ABI size changed");
#ifdef SYS_statmount
	_Static_assert(SYS_statmount == statmount_syscall_number,
		       "statmount syscall number changed");
#endif
#ifdef SYS_listmount
	_Static_assert(SYS_listmount == listmount_syscall_number,
		       "listmount syscall number changed");
#endif

	if (!namespace_path || !root_path || !expected_namespace_info) {
		errno = EINVAL;
		return -1;
	}
	namespace_fd = open(namespace_path, O_RDONLY | O_CLOEXEC);
	if (namespace_fd < 0)
		return -1;
	if (namespace_fd == 0) {
		int moved_fd = fcntl(namespace_fd, F_DUPFD_CLOEXEC, 3);
		int move_errno = errno;

		if (close(namespace_fd) < 0 && moved_fd >= 0) {
			int close_errno = errno ? errno : EIO;

			(void)close(moved_fd);
			errno = close_errno;
			return -1;
		}
		if (moved_fd < 0) {
			errno = move_errno ? move_errno : EIO;
			return -1;
		}
		namespace_fd = moved_fd;
	}
	if (fstat(namespace_fd, &opened_namespace_info) < 0)
		goto out;
	if (opened_namespace_info.st_dev != expected_namespace_info->st_dev ||
	    opened_namespace_info.st_ino != expected_namespace_info->st_ino) {
		errno = EAGAIN;
		goto out;
	}
	failure_step = "namespace-id";
	if (ioctl(namespace_fd, SWAPZ_PRIMARY_NS_GET_MNTNS_ID,
		  &pinned_namespace_id) < 0)
		goto out;
	if (!pinned_namespace_id) {
		errno = EOPNOTSUPP;
		goto out;
	}
	failure_step = "root-object";
	if (statx(AT_FDCWD, root_path, 0, statx_root_request_mask,
		  &root_info) < 0)
		goto out;
	if ((root_info.stx_mask & statx_root_required_mask) !=
		    statx_root_required_mask ||
	    !root_info.stx_mnt_id) {
		errno = EOPNOTSUPP;
		goto out;
	}
	current_mount_id = root_info.stx_mnt_id;
	root_mount_id = current_mount_id;
	if (require_process_root_matches_init) {
		failure_step = "init-root";
		if (statx(AT_FDCWD, "/proc/1/root", 0,
			  statx_root_request_mask, &init_root_info) < 0) {
			if (errno == EAGAIN)
				failure_reason = "init-root-statx-race";
			goto out;
		}
		if ((init_root_info.stx_mask & statx_root_identity_mask) !=
		    statx_root_identity_mask) {
			errno = EOPNOTSUPP;
			goto out;
		}
		if (!S_ISDIR(root_info.stx_mode) ||
		    !S_ISDIR(init_root_info.stx_mode) ||
		    root_info.stx_ino != init_root_info.stx_ino ||
		    root_info.stx_dev_major != init_root_info.stx_dev_major ||
		    root_info.stx_dev_minor != init_root_info.stx_dev_minor) {
			/* Classify only the first failed fixed identity predicate.
			 * Do not log inode/device numbers or weaken admission.
			 */
			if (!S_ISDIR(root_info.stx_mode))
				failure_reason = "process-root-not-directory";
			else if (!S_ISDIR(init_root_info.stx_mode))
				failure_reason = "init-root-not-directory";
			else if (root_info.stx_ino != init_root_info.stx_ino)
				failure_reason = "root-inode-mismatch";
			else
				failure_reason = "root-device-mismatch";
			errno = EAGAIN;
			goto out;
		}
	}

	failure_step = "root-walk";
	for (size_t depth = 0; depth < namespace_parent_depth_max; ++depth) {
		dev_t mounted_device;

		memset(&mount_status, 0, sizeof(mount_status));
		request = (struct mount_id_request) {
			.size = mount_id_request_bytes,
			.namespace_id = pinned_namespace_id,
			.mount_id = current_mount_id,
			.parameter = statmount_required_mask,
		};
		if (syscall(statmount_syscall_number, &request, &mount_status,
			    sizeof(mount_status), 0U) < 0) {
			if (errno == EOVERFLOW)
				failure_reason = "statmount-buffer-too-small";
			goto out;
		}
		if (mount_status.size < sizeof(mount_status) ||
		    (mount_status.mask & statmount_required_mask) !=
			    statmount_required_mask ||
		    mount_status.mount_id != current_mount_id) {
			errno = EOPNOTSUPP;
			goto out;
		}
		mounted_device = makedev(mount_status.superblock_device_major,
					 mount_status.superblock_device_minor);
		if (mounted_device == SWAPZ_PRIMARY_TARGET_DEVICE ||
		    (parent_device && mounted_device == parent_device)) {
			result = 1;
			goto out;
		}
		if (require_process_root_matches_init &&
		    current_mount_id == root_mount_id &&
		    mounted_device != expected_process_root_device) {
			/*
			 * mountinfo and statmount identify the same superblock.
			 * Inode st_dev can instead identify a Btrfs subvolume,
			 * so retain this independent superblock identity check.
			 */
			failure_reason = "root-superblock-device-mismatch";
			errno = EAGAIN;
			goto out;
		}
		if (mount_status.parent_mount_id == current_mount_id) {
			namespace_root_mount_id = current_mount_id;
			break;
		}
		if (!mount_status.parent_mount_id) {
			errno = EINVAL;
			goto out;
		}
		current_mount_id = mount_status.parent_mount_id;
	}
	if (!namespace_root_mount_id) {
		failure_reason = "root-parent-depth-limit";
		errno = EOVERFLOW;
		goto out;
	}
	request = (struct mount_id_request) {
		.size = mount_id_request_bytes,
		.namespace_id = pinned_namespace_id,
		.mount_id = namespace_root_mount_id,
	};
	failure_step = "mount-list";
	for (;;) {
		long listed_mounts;

		request.parameter = last_mount_id;
		listed_mounts = syscall(listmount_syscall_number, &request, mount_ids,
					namespace_mount_batch, 0U);
		if (listed_mounts < 0) {
			if (errno == EOVERFLOW)
				failure_reason = "listmount-overflow";
			goto out;
		}
		if (!listed_mounts)
			break;
		if ((size_t)listed_mounts > namespace_mount_batch) {
			errno = EIO;
			goto out;
		}
		for (long index = 0; index < listed_mounts; ++index) {
			dev_t mounted_device;

			if (mount_ids[index] <= last_mount_id) {
				errno = EAGAIN;
				goto out;
			}
			last_mount_id = mount_ids[index];
			if (++mount_count > SWAPZ_PRIMARY_VISIBLE_TASKS_MAX) {
				failure_reason = "mount-count-limit";
				errno = EOVERFLOW;
				goto out;
			}
			memset(&mount_status, 0, sizeof(mount_status));
			request = (struct mount_id_request) {
				.size = mount_id_request_bytes,
				.namespace_id = pinned_namespace_id,
				.mount_id = mount_ids[index],
				.parameter = statmount_required_mask,
			};
			failure_step = "listed-mount";
			if (syscall(statmount_syscall_number, &request, &mount_status,
				    sizeof(mount_status), 0U) < 0) {
				if (errno == EOVERFLOW)
					failure_reason = "statmount-buffer-too-small";
				goto out;
			}
			if (mount_status.size < sizeof(mount_status) ||
			    (mount_status.mask & statmount_required_mask) !=
				    statmount_required_mask ||
			    mount_status.mount_id != mount_ids[index]) {
				errno = EOPNOTSUPP;
				goto out;
			}
			mounted_device =
				makedev(mount_status.superblock_device_major,
					mount_status.superblock_device_minor);
			if (mounted_device == SWAPZ_PRIMARY_TARGET_DEVICE ||
			    (parent_device && mounted_device == parent_device)) {
				result = 1;
				goto out;
			}
		}
		request.mount_id = namespace_root_mount_id;
		failure_step = "mount-list";
	}
	if (require_process_root_matches_init) {
		failure_step = "root-revalidation";
		if (statx(AT_FDCWD, root_path, 0, statx_root_request_mask,
			  &confirmed_root_info) < 0 ||
		    statx(AT_FDCWD, "/proc/1/root", 0,
			  statx_root_request_mask,
			  &confirmed_init_root_info) < 0)
			goto out;
		if ((confirmed_root_info.stx_mask & statx_root_required_mask) !=
			    statx_root_required_mask ||
		    (confirmed_init_root_info.stx_mask &
			     statx_root_identity_mask) != statx_root_identity_mask) {
			errno = EOPNOTSUPP;
			goto out;
		}
		if (confirmed_root_info.stx_mnt_id != root_mount_id ||
		    !S_ISDIR(confirmed_root_info.stx_mode) ||
		    !S_ISDIR(confirmed_init_root_info.stx_mode) ||
		    confirmed_root_info.stx_ino != root_info.stx_ino ||
		    confirmed_root_info.stx_dev_major != root_info.stx_dev_major ||
		    confirmed_root_info.stx_dev_minor != root_info.stx_dev_minor ||
		    confirmed_init_root_info.stx_ino != init_root_info.stx_ino ||
		    confirmed_init_root_info.stx_dev_major !=
			    init_root_info.stx_dev_major ||
		    confirmed_init_root_info.stx_dev_minor !=
			    init_root_info.stx_dev_minor ||
		    confirmed_root_info.stx_ino !=
			    confirmed_init_root_info.stx_ino ||
		    confirmed_root_info.stx_dev_major !=
			    confirmed_init_root_info.stx_dev_major ||
		    confirmed_root_info.stx_dev_minor !=
			    confirmed_init_root_info.stx_dev_minor) {
			errno = EAGAIN;
			goto out;
		}
	}
	result = 0;

out:
	if (result < 0)
		saved_errno = errno ? errno : EIO;
	if (close(namespace_fd) < 0 && result >= 0) {
		saved_errno = errno ? errno : EIO;
		result = -1;
	}
	if (result < 0) {
		/*
		 * Refuse inconsistent mount views. Log only a fixed scan step
		 * and errno, not mount, PID, namespace or device identities.
		 * Restore the original errno after reporting the failure.
		 */
		if (saved_errno == EINVAL || saved_errno == ENOSYS ||
		    saved_errno == EAGAIN ||
		    (saved_errno == EOVERFLOW && failure_reason))
			(void)fprintf(stderr,
				      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
				      "step=%s errno=%d%s%s\n",
				      failure_step, saved_errno,
				      failure_reason ? " reason=" : "",
				      failure_reason ? failure_reason : "");
		errno = saved_errno;
	}
	return result;
#endif
#endif
}

static int swapz_primary_mountinfo_exit_error(int error)
{
	return error == EINVAL || error == ENOENT || error == ESRCH;
}

/*
 * Top-level /proc enumeration returns thread-group leaders only. A thread may
 * have a separate mount namespace, so inspect each non-leader task view too.
 */
static int swapz_primary_read_nonleader_mount_facts(
	const char *task_directory_path, const char *leader_namespace_path,
	const char *leader_tid, int is_self, dev_t parent_device,
	const struct stat *self_namespace_info,
	int coordinator_namespace_inventory_complete,
	struct swapz_primary_mount_facts *combined, size_t *visible_task_count,
	size_t *total_bytes)
{
	struct swapz_primary_mount_facts local = {0};
	DIR *task_directory;
	struct dirent *entry;
	char namespace_path[PATH_MAX];
	char mountinfo_path[PATH_MAX];
	char root_path[PATH_MAX];
	int saved_errno = 0;

	if (!task_directory_path || !leader_namespace_path || !leader_tid ||
	    !self_namespace_info || !combined || !visible_task_count ||
	    !total_bytes) {
		errno = EINVAL;
		return -1;
	}
	task_directory = opendir(task_directory_path);
	if (!task_directory) {
		int open_error = errno ? errno : EIO;
		struct stat leader_namespace;

		if (!is_self && swapz_primary_mountinfo_exit_error(open_error) &&
		    stat(leader_namespace_path, &leader_namespace) < 0 &&
		    swapz_primary_mountinfo_exit_error(errno))
			return 0;
		errno = open_error;
		return -1;
	}
	for (;;) {
		struct stat namespace_info;
		struct stat confirmed_namespace_info;
		size_t bytes_read = 0;
		int path_length;
		int fd;

		errno = 0;
		entry = readdir(task_directory);
		if (!entry) {
			if (errno)
				saved_errno = errno;
			break;
		}
		if (!swapz_primary_proc_entry_is_pid(entry->d_name) ||
		    !strcmp(entry->d_name, leader_tid))
			continue;
		if (++*visible_task_count > SWAPZ_PRIMARY_VISIBLE_TASKS_MAX) {
			saved_errno = EOVERFLOW;
			break;
		}
		path_length = snprintf(namespace_path, sizeof(namespace_path),
				       "%s/%s/ns/mnt", task_directory_path,
				       entry->d_name);
		if (path_length <= 0 ||
		    (size_t)path_length >= sizeof(namespace_path)) {
			saved_errno = EOVERFLOW;
			break;
		}
		if (stat(namespace_path, &namespace_info) < 0) {
			int namespace_error = errno ? errno : EIO;

			if (swapz_primary_mountinfo_exit_error(namespace_error))
				continue;
			saved_errno = namespace_error;
			break;
		}
		/* The coordinator's complete root table covers this exact namespace. */
		if (coordinator_namespace_inventory_complete &&
		    namespace_info.st_dev == self_namespace_info->st_dev &&
		    namespace_info.st_ino == self_namespace_info->st_ino) {
			if (stat(namespace_path, &confirmed_namespace_info) < 0) {
				int namespace_error = errno ? errno : EIO;

				if (swapz_primary_mountinfo_exit_error(namespace_error))
					continue;
				saved_errno = namespace_error;
				break;
			}
			if (confirmed_namespace_info.st_dev ==
				    self_namespace_info->st_dev &&
			    confirmed_namespace_info.st_ino ==
				    self_namespace_info->st_ino)
				continue;
			/* The task moved namespaces; inspect its newly observed view. */
			namespace_info = confirmed_namespace_info;
		}
		path_length = snprintf(mountinfo_path, sizeof(mountinfo_path),
				       "%s/%s/mountinfo", task_directory_path,
				       entry->d_name);
		if (path_length <= 0 ||
		    (size_t)path_length >= sizeof(mountinfo_path)) {
			saved_errno = EOVERFLOW;
			break;
		}

		path_length = snprintf(root_path, sizeof(root_path),
				       "%s/%s/root", task_directory_path,
				       entry->d_name);
		if (path_length <= 0 ||
		    (size_t)path_length >= sizeof(root_path)) {
			saved_errno = EOVERFLOW;
			break;
		}
		fd = open(mountinfo_path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
		if (fd < 0) {
			int open_error = errno ? errno : EIO;

			if (!swapz_primary_mountinfo_exit_error(open_error)) {
				saved_errno = open_error;
				break;
			}
			if (stat(namespace_path, &confirmed_namespace_info) < 0) {
				int namespace_error = errno ? errno : EIO;

				if (swapz_primary_mountinfo_exit_error(namespace_error))
					continue;
				saved_errno = namespace_error;
				break;
			}
			saved_errno = open_error;
			break;
		}
		if (swapz_primary_mountinfo_read_fd(
			    fd, parent_device, &local, &bytes_read) < 0) {
			saved_errno = errno ? errno : EIO;
			break;
		}
		if (stat(namespace_path, &confirmed_namespace_info) < 0) {
			saved_errno = swapz_primary_mountinfo_exit_error(errno) ?
				EAGAIN : (errno ? errno : EIO);
			break;
		}
		if (confirmed_namespace_info.st_dev != namespace_info.st_dev ||
		    confirmed_namespace_info.st_ino != namespace_info.st_ino) {
			saved_errno = EAGAIN;
			break;
		}

		if (bytes_read > SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES - *total_bytes) {
			(void)fprintf(stderr,
				      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
				      "step=mountinfo-aggregate errno=%d "
				      "reason=aggregate-byte-limit\n", EOVERFLOW);
			saved_errno = EOVERFLOW;
			break;
		}
		*total_bytes += bytes_read;
		if (local.target_mounted) {
			combined->target_mounted = 1;
			break;
		}
		{
			int namespace_mounted =
				swapz_primary_mountinfo_full_root(
					namespace_path, root_path,
					&confirmed_namespace_info, parent_device, 0, 0);

			if (namespace_mounted < 0) {
				saved_errno = errno ? errno : EIO;
				break;
			}
			if (namespace_mounted) {
				combined->target_mounted = 1;
				break;
			}
		}
	}
	if (saved_errno)
		errno = saved_errno;
	if (closedir(task_directory) < 0 && !saved_errno)
		saved_errno = errno ? errno : EIO;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return 0;
}
#endif

static int swapz_primary_read_mount_facts(
	struct swapz_primary_mount_facts *facts, dev_t parent_device)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)facts;
	(void)parent_device;
	errno = ENODEV;
	return -1;
#else
	struct swapz_primary_mount_facts combined = {0};
	struct swapz_primary_mount_facts local = {0};
	DIR *proc_directory = NULL;
	struct dirent *entry;
	char self_pid[32];
	char path[PATH_MAX];
	char namespace_path[PATH_MAX];
	char root_path[PATH_MAX];
	struct stat self_namespace_info;
	ssize_t self_root_length;
	size_t visible_task_count = 1U;
	size_t total_bytes = 0;
	int fd;
	int saved_errno = 0;
	int path_length;
	int coordinator_namespace_inventory_complete = 0;
	size_t bytes_read = 0;

	if (!facts) {
		errno = EINVAL;
		return -1;
	}
	fd = open("/proc/self/mountinfo", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	if (swapz_primary_mountinfo_read_fd(
		    fd, parent_device, &local, &bytes_read) < 0)
		return -1;
	combined = local;
	total_bytes = bytes_read;
	if (combined.target_mounted) {
		*facts = combined;
		return 0;
	}
	if (stat("/proc/self/ns/mnt", &self_namespace_info) < 0)
		return -1;
	self_root_length = readlink("/proc/self/root", path, sizeof(path) - 1U);
	if (self_root_length < 0)
		return -1;
	if (self_root_length != 1 || path[0] != '/') {
		errno = EAGAIN;
		return -1;
	}
	{
		int namespace_mounted =
			swapz_primary_mountinfo_full_root(
				"/proc/self/ns/mnt", "/proc/self/root",
				&self_namespace_info, parent_device,
				combined.root_device, 1);

		if (namespace_mounted < 0)
			return -1;
		if (namespace_mounted) {
			combined.target_mounted = 1;
			*facts = combined;
			return 0;
		}
		coordinator_namespace_inventory_complete = 1;
	}
	/*
	 * mountinfo is scoped to a task's mount namespace. Top-level /proc
	 * enumeration returns thread-group leaders only, so inspect each visible
	 * process and every non-leader task view; a process-only scan can miss a
	 * target mounted by one thread in a distinct namespace.
	 * The coordinator's pinned namespace-ID inventory covers mounts that a
	 * process-root-filtered mountinfo view can hide. A task in that same
	 * namespace may therefore be skipped only after its namespace inode matches
	 * and that identity is revalidated immediately before skipping. A normal
	 * switched-root boot can leave the coordinator's process root on a child
	 * mount while the namespace root is rootfs. Require the process-root object
	 * to match PID 1's root, cross-check its device against self mountinfo and
	 * statmount, and complete the pinned inventory from the namespace root
	 * before using the same-namespace shortcut. A root-link spelling alone is
	 * not identity proof. This is a bounded snapshot, so every unreadable,
	 * unsupported or ambiguous inventory fails
	 * closed rather than being treated as evidence that the device is unused.
	 */
	path_length = snprintf(self_pid, sizeof(self_pid), "%lu",
			       (unsigned long)getpid());
	if (path_length <= 0 || (size_t)path_length >= sizeof(self_pid)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (swapz_primary_read_nonleader_mount_facts(
		    "/proc/self/task", "/proc/self/ns/mnt", self_pid, 1,
		    parent_device, &self_namespace_info,
		    coordinator_namespace_inventory_complete, &combined,
		    &visible_task_count,
		    &total_bytes) < 0)
		return -1;
	if (combined.target_mounted) {
		*facts = combined;
		return 0;
	}
	proc_directory = opendir("/proc");
	if (!proc_directory)
		return -1;
	for (;;) {
		int open_error;
		int namespace_error;
		int skip_leader_mountinfo = 0;
		struct stat namespace_info;
		struct stat confirmed_namespace_info;

		errno = 0;
		entry = readdir(proc_directory);
		if (!entry) {
			if (errno)
				saved_errno = errno;
			break;
		}
		if (!swapz_primary_proc_entry_is_pid(entry->d_name))
			continue;
		if (!strcmp(entry->d_name, self_pid))
			continue;
		if (++visible_task_count > SWAPZ_PRIMARY_VISIBLE_TASKS_MAX) {
			saved_errno = EOVERFLOW;
			break;
		}
		path_length = snprintf(namespace_path, sizeof(namespace_path),
				      "/proc/%s/ns/mnt", entry->d_name);
		if (path_length <= 0 ||
		    (size_t)path_length >= sizeof(namespace_path)) {
			saved_errno = EOVERFLOW;
			break;
		}
		if (stat(namespace_path, &namespace_info) < 0) {
			namespace_error = errno ? errno : EIO;
			if (namespace_error == ENOENT || namespace_error == ESRCH) {
				/*
				 * The leader may have exited while a non-leader task
				 * remains visible. Skip only its leader table; still
				 * inspect the task directory before treating the PID as
				 * gone.
				 */
				skip_leader_mountinfo = 1;
			} else {
				saved_errno = namespace_error;
				break;
			}
		}
		if (!skip_leader_mountinfo &&
		    coordinator_namespace_inventory_complete &&
		    namespace_info.st_dev == self_namespace_info.st_dev &&
		    namespace_info.st_ino == self_namespace_info.st_ino) {
			if (stat(namespace_path, &confirmed_namespace_info) < 0) {
				namespace_error = errno ? errno : EIO;
				if (namespace_error == ENOENT ||
				    namespace_error == ESRCH)
					goto scan_nonleader_tasks;
				saved_errno = namespace_error;
				break;
			}
			if (confirmed_namespace_info.st_dev ==
				    self_namespace_info.st_dev &&
			    confirmed_namespace_info.st_ino ==
				    self_namespace_info.st_ino)
				skip_leader_mountinfo = 1;
			else
				namespace_info = confirmed_namespace_info;
		}

		if (!skip_leader_mountinfo) {
			path_length = snprintf(root_path, sizeof(root_path),
					      "/proc/%s/root", entry->d_name);
			if (path_length <= 0 ||
			    (size_t)path_length >= sizeof(root_path)) {
				saved_errno = EOVERFLOW;
				break;
			}
			path_length = snprintf(path, sizeof(path),
					      "/proc/%s/mountinfo", entry->d_name);
			if (path_length <= 0 ||
			    (size_t)path_length >= sizeof(path)) {
				saved_errno = EOVERFLOW;
				break;
			}
			fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
			if (fd < 0) {
				open_error = errno ? errno : EIO;
				if (!swapz_primary_mountinfo_exit_error(open_error)) {
					saved_errno = open_error;
					break;
				}
				if (stat(namespace_path,
					 &confirmed_namespace_info) < 0) {
					namespace_error = errno ? errno : EIO;
					if (namespace_error == ENOENT ||
					    namespace_error == ESRCH)
						goto scan_nonleader_tasks;
					saved_errno = namespace_error;
					break;
				}
				saved_errno = open_error;
				break;
			}
			if (swapz_primary_mountinfo_read_fd(
				    fd, parent_device, &local, &bytes_read) < 0) {
				saved_errno = errno ? errno : EIO;
				break;
			}
			if (stat(namespace_path,
				 &confirmed_namespace_info) < 0) {
				namespace_error = errno ? errno : EIO;
				saved_errno =
					swapz_primary_mountinfo_exit_error(
						namespace_error) ? EAGAIN :
						namespace_error;
				break;
			}
			if (confirmed_namespace_info.st_dev != namespace_info.st_dev ||
			    confirmed_namespace_info.st_ino != namespace_info.st_ino) {
				saved_errno = EAGAIN;
				break;
			}

			if (bytes_read >
			    SWAPZ_PRIMARY_MOUNTINFO_TOTAL_BYTES - total_bytes) {
				(void)fprintf(stderr,
					      "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
					      "step=mountinfo-aggregate errno=%d "
					      "reason=aggregate-byte-limit\n", EOVERFLOW);
				saved_errno = EOVERFLOW;
				break;
			}
			total_bytes += bytes_read;
			if (local.target_mounted) {
				combined.target_mounted = 1;
				break;
			}
			{
				int namespace_mounted =
					swapz_primary_mountinfo_full_root(
						namespace_path, root_path,
						&confirmed_namespace_info,
						parent_device, 0, 0);

				if (namespace_mounted < 0) {
					saved_errno = errno ? errno : EIO;
					break;
				}
				if (namespace_mounted) {
					combined.target_mounted = 1;
					break;
				}
			}
		}
	scan_nonleader_tasks:
		/*
		 * A leader can disappear after either namespace observation or an
		 * unopened mountinfo failure while sibling tasks remain. These jumps
		 * own no leader mountinfo descriptor; continue with the task inventory.
		 */
		path_length = snprintf(path, sizeof(path), "/proc/%s/task",
				      entry->d_name);
		if (path_length <= 0 || (size_t)path_length >= sizeof(path)) {
			saved_errno = EOVERFLOW;
			break;
		}
		if (swapz_primary_read_nonleader_mount_facts(
			    path, namespace_path, entry->d_name, 0, parent_device,
			    &self_namespace_info,
			    coordinator_namespace_inventory_complete,
			    &combined, &visible_task_count, &total_bytes) < 0) {
			saved_errno = errno ? errno : EIO;
			break;
		}
		if (combined.target_mounted)
			break;
	}
	if (saved_errno)
		errno = saved_errno;
	if (closedir(proc_directory) < 0) {
		if (!saved_errno)
			saved_errno = errno ? errno : EIO;
	}
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	*facts = combined;
	return 0;
#endif
}

static int swapz_primary_dm_block_name(const char *name)
{
	const unsigned char *cursor;

	if (!name || strncmp(name, "dm-", 3U) || !name[3])
		return 0;
	for (cursor = (const unsigned char *)name + 3U; *cursor; ++cursor)
		if (*cursor < '0' || *cursor > '9')
			return 0;
	return 1;
}

static int swapz_primary_mapper_identity_is_swapz(const char *name,
						 const char *uuid)
{
	const unsigned char *cursor;

	if (!name || !name[0] || !uuid)
		return -1;
	for (cursor = (const unsigned char *)name; *cursor; ++cursor)
		if (*cursor < 0x20U || *cursor == 0x7fU || *cursor == '/')
			return -1;
	for (cursor = (const unsigned char *)uuid; *cursor; ++cursor)
		if (*cursor < 0x20U || *cursor == 0x7fU)
			return -1;
	return !strncmp(name, "swapz-", 6U) ||
	       !strncmp(uuid, "SWAPZ-", 6U);
}

static int swapz_primary_read_module_mapper_inventory(
	int *module_loaded, int *swapz_mapper_present)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)module_loaded;
	(void)swapz_mapper_present;
	errno = ENODEV;
	return -1;
#else
	struct dirent *entry;
	struct stat module_info;
	DIR *block_directory;
	unsigned int mapper_count = 0;
	int saved_errno = 0;

	if (!module_loaded || !swapz_mapper_present) {
		errno = EINVAL;
		return -1;
	}
	*module_loaded = 0;
	*swapz_mapper_present = 0;
	if (stat("/sys/module/dm_swapz", &module_info) == 0) {
		if (!S_ISDIR(module_info.st_mode)) {
			errno = EINVAL;
			return -1;
		}
		*module_loaded = 1;
	} else if (errno != ENOENT) {
		return -1;
	}
	block_directory = opendir("/sys/block");
	if (!block_directory)
		return -1;
	errno = 0;
	while ((entry = readdir(block_directory)) != NULL) {
		char name_path[PATH_MAX];
		char uuid_path[PATH_MAX];
		char mapper_name[128];
		char mapper_uuid[256];
		int identity;

		if (!swapz_primary_dm_block_name(entry->d_name))
			continue;
		if (++mapper_count > SWAPZ_PRIMARY_DM_MAPPERS_MAX) {
			errno = EOVERFLOW;
			break;
		}
		if (swapz_primary_path_format(name_path, sizeof(name_path),
					      "/sys/block/%s/dm/name",
					      entry->d_name) < 0 ||
		    swapz_primary_path_format(uuid_path, sizeof(uuid_path),
					      "/sys/block/%s/dm/uuid",
					      entry->d_name) < 0 ||
		    swapz_primary_read_sysfs_text(name_path, mapper_name,
						      sizeof(mapper_name)) < 0 ||
		    swapz_primary_read_sysfs_text(uuid_path, mapper_uuid,
						      sizeof(mapper_uuid)) < 0) {
			if (!errno)
				errno = EIO;
			break;
		}
		identity = swapz_primary_mapper_identity_is_swapz(mapper_name,
								   mapper_uuid);
		if (identity < 0) {
			errno = EINVAL;
			break;
		}
		if (identity)
			*swapz_mapper_present = 1;
		errno = 0;
	}
	saved_errno = errno;
	if (closedir(block_directory) < 0)
		return -1;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	return 0;
#endif
}

static int swapz_primary_read_module_build_provenance(
	int module_loaded, char source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U],
	int *source_clean)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)module_loaded;
	(void)source_sha;
	(void)source_clean;
	errno = ENODEV;
	return -1;
#else
	char sha_path[PATH_MAX];
	char clean_path[PATH_MAX];
	char sha_text[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U];
	char clean_text[16];
	int clean;

	if (!source_sha || !source_clean) {
		errno = EINVAL;
		return -1;
	}
	if (!module_loaded) {
		errno = ENODEV;
		return -1;
	}
	if (swapz_primary_path_format(sha_path, sizeof(sha_path),
				      "/sys/module/dm_swapz/parameters/build_source_sha") < 0 ||
	    swapz_primary_path_format(clean_path, sizeof(clean_path),
				      "/sys/module/dm_swapz/parameters/build_source_clean") < 0 ||
	    swapz_primary_read_sysfs_text(sha_path, sha_text,
					      sizeof(sha_text)) < 0 ||
	    swapz_primary_read_sysfs_text(clean_path, clean_text,
					      sizeof(clean_text)) < 0)
		return -1;
	if (strcmp(sha_text, "unknown") &&
	    !swapz_primary_valid_source_sha(sha_text)) {
		errno = EINVAL;
		return -1;
	}
	if (!strcmp(clean_text, "0"))
		clean = 0;
	else if (!strcmp(clean_text, "1"))
		clean = 1;
	else {
		errno = EINVAL;
		return -1;
	}
	memcpy(source_sha, sha_text, strlen(sha_text) + 1U);
	*source_clean = clean;
	return 0;
#endif
}

static int swapz_primary_sysfs_directory_empty(const char *path,
					      int missing_is_empty)
{
	struct dirent *entry;
	DIR *directory = opendir(path);
	int read_error = 0;

	if (!directory)
		return missing_is_empty && errno == ENOENT;
	errno = 0;
	while ((entry = readdir(directory)) != NULL) {
		if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
			continue;
		read_error = ENOTEMPTY;
		break;
	}
	if (!read_error && errno)
		read_error = errno;
	if (closedir(directory) < 0 && !read_error)
		read_error = errno;
	if (read_error) {
		errno = read_error;
		return 0;
	}
	return 1;
}

#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
static int swapz_primary_owned_nullblk_major(unsigned int *nullblk_major)
{
	char buffer[8192];
	char *line;
	char *save = NULL;
	size_t used = 0;
	unsigned int found_major = 0;
	int in_block_devices = 0;
	int found = 0;
	int fd;

	if (!nullblk_major) {
		errno = EINVAL;
		return -1;
	}
	fd = open("/proc/devices", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	while (used + 1U < sizeof(buffer)) {
		ssize_t count = read(fd, buffer + used,
				     sizeof(buffer) - used - 1U);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used + 1U == sizeof(buffer)) {
		errno = EOVERFLOW;
		return -1;
	}
	buffer[used] = '\0';
	for (line = strtok_r(buffer, "\n", &save);
	     line; line = strtok_r(NULL, "\n", &save)) {
		unsigned int major_number;
		char name[64];
		char extra;

		if (!strcmp(line, "Block devices:")) {
			in_block_devices = 1;
			continue;
		}
		if (!in_block_devices ||
		    sscanf(line, " %u %63s %c", &major_number, name, &extra) != 2 ||
		    strcmp(name, "nullb"))
			continue;
		if (found || !major_number) {
			errno = EPROTO;
			return -1;
		}
		found = 1;
		found_major = major_number;
	}
	if (!found) {
		errno = ENODEV;
		return -1;
	}
	*nullblk_major = found_major;
	return 0;
}

static int swapz_primary_owned_nullblk_parent(
	const char *resolved_devices_root, const char *source_realpath,
	const char *parent_path, dev_t observed_parent)
{
	static const char virtual_block[] = "/virtual/block/";
	const char *disk_name;
	size_t devices_root_length;
	size_t parent_length;
	unsigned int nullblk_major = 0;

	if (!resolved_devices_root || !source_realpath || !parent_path ||
	    swapz_primary_owned_nullblk_major(&nullblk_major) < 0 ||
	    major(observed_parent) != nullblk_major)
		return 0;
	devices_root_length = strlen(resolved_devices_root);
	if (strncmp(parent_path, resolved_devices_root, devices_root_length) ||
	    strcmp(parent_path + devices_root_length, virtual_block) == 0 ||
	    strncmp(parent_path + devices_root_length, virtual_block,
		    sizeof(virtual_block) - 1U))
		return 0;
	disk_name = parent_path + devices_root_length +
		    sizeof(virtual_block) - 1U;
	if (!disk_name[0] || strchr(disk_name, '/'))
		return 0;
	parent_length = strlen(parent_path);
	return !strncmp(source_realpath, parent_path, parent_length) &&
	       source_realpath[parent_length] == '/' &&
	       source_realpath[parent_length + 1U] != '\0' &&
	       strchr(source_realpath + parent_length + 1U, '/') == NULL;
}
#endif


#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
static int swapz_primary_owned_nullblk_btrfs_filesystems_match(
	const struct stat *root_directory,
	const struct statfs *root_filesystem_info,
	const struct btrfs_ioctl_fs_info_args *root_filesystem,
	const struct stat *recovery_directory,
	const struct statfs *recovery_filesystem_info,
	const struct btrfs_ioctl_fs_info_args *recovery_filesystem)
{
	static const unsigned char zero_fsid[BTRFS_FSID_SIZE];

	return root_directory && root_filesystem_info && root_filesystem &&
	       recovery_directory && recovery_filesystem_info &&
	       recovery_filesystem && S_ISDIR(root_directory->st_mode) &&
	       S_ISDIR(recovery_directory->st_mode) &&
	       major(root_directory->st_dev) == 0U &&
	       minor(root_directory->st_dev) != 0U &&
	       major(recovery_directory->st_dev) == 0U &&
	       minor(recovery_directory->st_dev) != 0U &&
	       (unsigned long)root_filesystem_info->f_type == BTRFS_SUPER_MAGIC &&
	       (unsigned long)recovery_filesystem_info->f_type ==
		       BTRFS_SUPER_MAGIC &&
	       root_filesystem->num_devices == 1U &&
	       root_filesystem->max_id == 1U &&
	       recovery_filesystem->num_devices == 1U &&
	       recovery_filesystem->max_id == 1U &&
	       !memcmp(root_filesystem->fsid, recovery_filesystem->fsid,
		       BTRFS_FSID_SIZE) &&
	       memcmp(root_filesystem->fsid, zero_fsid, BTRFS_FSID_SIZE);
}

/*
 * Btrfs reports a virtual st_dev rather than its underlying block partition.
 * Resolve it only for the private RAM-backed lifecycle, and only after proving
 * exactly one live Btrfs member tied to an ordinary physical sysfs block node.
 * Production and physical admission must continue rejecting Btrfs.
 */
static int swapz_primary_owned_nullblk_btrfs_partition(
	dev_t filesystem_device, int root_mount_source,
	dev_t *partition_device)
{
	static const char hexadecimal[] = "0123456789abcdef";
	struct btrfs_ioctl_fs_info_args filesystem = {0};
	struct btrfs_ioctl_fs_info_args rechecked_filesystem = {0};
	struct btrfs_ioctl_fs_info_args root_filesystem = {0};
	struct btrfs_ioctl_fs_info_args rechecked_root_filesystem = {0};
	struct btrfs_ioctl_dev_info_args backing = {.devid = 1U};
	struct btrfs_ioctl_dev_info_args rechecked_backing = {.devid = 1U};
	struct stat directory_info;
	struct stat checked_directory;
	struct stat root_directory_info;
	struct stat checked_root_directory;
	struct stat node_info;
	struct stat link_info;
	struct statfs filesystem_info;
	struct statfs root_filesystem_info;
	struct statfs checked_filesystem_info;
	struct statfs checked_root_filesystem_info;
	char backing_path[BTRFS_DEVICE_PATH_NAME_MAX];
	char filesystem_uuid[37];
	char sysfs_link[PATH_MAX];
	char device_link[PATH_MAX];
	char resolved_sysfs_device[PATH_MAX];
	char resolved_device_link[PATH_MAX];
	const char *device_basename;
	size_t uuid_offset = 0;
	size_t index;
	int recovery_fd = -1;
	int root_fd = -1;
	int device_fd = -1;
	int valid = 0;

	if (!partition_device || major(filesystem_device) != 0U)
		return 0;
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		return 0;
	if (fstat(recovery_fd, &directory_info) < 0 ||
	    !S_ISDIR(directory_info.st_mode) ||
	    fstatfs(recovery_fd, &filesystem_info) < 0 ||
	    (unsigned long)filesystem_info.f_type != BTRFS_SUPER_MAGIC ||
	    ioctl(recovery_fd, BTRFS_IOC_FS_INFO, &filesystem) < 0 ||
	    filesystem.num_devices != 1U || filesystem.max_id != 1U ||
	    (!root_mount_source && directory_info.st_dev != filesystem_device))
		goto out;
	if (root_mount_source) {
		root_fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
		if (root_fd < 0 || fstat(root_fd, &root_directory_info) < 0 ||
		    fstatfs(root_fd, &root_filesystem_info) < 0 ||
		    ioctl(root_fd, BTRFS_IOC_FS_INFO, &root_filesystem) < 0 ||
		    !swapz_primary_owned_nullblk_btrfs_filesystems_match(
			    &root_directory_info, &root_filesystem_info,
			    &root_filesystem, &directory_info, &filesystem_info,
			    &filesystem))
			goto out;
	}
	if (ioctl(recovery_fd, BTRFS_IOC_DEV_INFO, &backing) < 0 ||
	    backing.devid != 1U ||
	    memcmp(filesystem.fsid, backing.fsid, BTRFS_FSID_SIZE))
		goto out;

	/* Do not follow a mutable /dev alias supplied by the kernel path. */
	memcpy(backing_path, backing.path, sizeof(backing_path));
	if (!memchr(backing_path, '\0', sizeof(backing_path)) ||
	    strncmp(backing_path, "/dev/", sizeof("/dev/") - 1U))
		goto out;
	device_basename = backing_path + sizeof("/dev/") - 1U;
	if (!device_basename[0] || strchr(device_basename, '/'))
		goto out;
	device_fd = open(backing_path, O_PATH | O_CLOEXEC | O_NOFOLLOW);
	if (device_fd < 0 || fstat(device_fd, &node_info) < 0 ||
	    !S_ISBLK(node_info.st_mode) ||
	    (major(node_info.st_rdev) == 0U && minor(node_info.st_rdev) == 0U))
		goto out;

	/* The Btrfs membership symlink must resolve to that very block node. */
	for (index = 0; index < BTRFS_FSID_SIZE; ++index) {
		if (index == 4U || index == 6U || index == 8U || index == 10U)
			filesystem_uuid[uuid_offset++] = '-';
		filesystem_uuid[uuid_offset++] =
			hexadecimal[filesystem.fsid[index] >> 4U];
		filesystem_uuid[uuid_offset++] =
			hexadecimal[filesystem.fsid[index] & 0x0fU];
	}
	filesystem_uuid[uuid_offset] = '\0';
	if (uuid_offset != 36U ||
	    swapz_primary_path_format(
		    sysfs_link, sizeof(sysfs_link),
		    "/sys/fs/btrfs/%s/devices/%s", filesystem_uuid,
		    device_basename) < 0 ||
	    swapz_primary_path_format(
		    device_link, sizeof(device_link),
		    "/sys/dev/block/%u:%u", major(node_info.st_rdev),
		    minor(node_info.st_rdev)) < 0 ||
	    lstat(sysfs_link, &link_info) < 0 ||
	    !S_ISLNK(link_info.st_mode) ||
	    !realpath(sysfs_link, resolved_sysfs_device) ||
	    !realpath(device_link, resolved_device_link) ||
	    strcmp(resolved_sysfs_device, resolved_device_link))
		goto out;

	/* A second kernel snapshot must still identify the same sole member. */
	if (fstat(recovery_fd, &checked_directory) < 0 ||
	    checked_directory.st_dev != directory_info.st_dev ||
	    checked_directory.st_ino != directory_info.st_ino ||
	    fstatfs(recovery_fd, &checked_filesystem_info) < 0 ||
	    ioctl(recovery_fd, BTRFS_IOC_FS_INFO,
		  &rechecked_filesystem) < 0 ||
	    rechecked_filesystem.num_devices != 1U ||
	    rechecked_filesystem.max_id != 1U ||
	    memcmp(filesystem.fsid, rechecked_filesystem.fsid,
		   BTRFS_FSID_SIZE) ||
	    ioctl(recovery_fd, BTRFS_IOC_DEV_INFO, &rechecked_backing) < 0 ||
	    rechecked_backing.devid != backing.devid ||
	    memcmp(rechecked_backing.fsid, backing.fsid, BTRFS_FSID_SIZE) ||
	    memcmp(rechecked_backing.uuid, backing.uuid, BTRFS_UUID_SIZE) ||
	    memcmp(rechecked_backing.path, backing.path, sizeof(backing.path)))
		goto out;
	if (root_mount_source &&
	    (fstat(root_fd, &checked_root_directory) < 0 ||
	     checked_root_directory.st_dev != root_directory_info.st_dev ||
	     checked_root_directory.st_ino != root_directory_info.st_ino ||
	     fstatfs(root_fd, &checked_root_filesystem_info) < 0 ||
	     ioctl(root_fd, BTRFS_IOC_FS_INFO,
		   &rechecked_root_filesystem) < 0 ||
	     !swapz_primary_owned_nullblk_btrfs_filesystems_match(
		     &checked_root_directory, &checked_root_filesystem_info,
		     &rechecked_root_filesystem, &checked_directory,
		     &checked_filesystem_info, &rechecked_filesystem)))
		goto out;
	*partition_device = node_info.st_rdev;
	valid = 1;
out:
	if (device_fd >= 0 && close(device_fd) < 0)
		valid = 0;
	if (root_fd >= 0 && close(root_fd) < 0)
		valid = 0;
	if (close(recovery_fd) < 0)
		valid = 0;
	return valid;
}
#endif

static int swapz_primary_recovery_source_chain(
	const char *sysfs_root, dev_t source_device, dev_t target_device,
	dev_t *physical_parent_device)
{
	char devices_root[PATH_MAX];
	char block_root[PATH_MAX];
	char link_path[PATH_MAX];
	char node_path[PATH_MAX];
	char parent_path[PATH_MAX];
	char source_realpath[PATH_MAX];
	char device_path[PATH_MAX];
	char device_realpath[PATH_MAX];
	char path[PATH_MAX];
	char *slash;
	char *resolved_devices_root;
	dev_t observed_source;
	dev_t observed_parent;
	struct stat link_info;
	struct stat queue_info;
	uint64_t partition_number;
	size_t devices_root_length;
	int parent_identity_valid = 0;

	if (!sysfs_root || !physical_parent_device ||
	    (major(source_device) == 0U && minor(source_device) == 0U) ||
	    ((major(target_device) != 0U || minor(target_device) != 0U) &&
	     source_device == target_device)) {
		errno = EINVAL;
		return 0;
	}
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	/* Resolve Btrfs virtual st_dev only after its sole-member identity proof. */
	if (major(source_device) == 0U &&
	    !swapz_primary_owned_nullblk_btrfs_partition(
		    source_device, 0, &source_device))
		return 0;
#endif
	if (swapz_primary_path_format(devices_root, sizeof(devices_root),
				      "%s/devices", sysfs_root) < 0 ||
	    swapz_primary_path_format(block_root, sizeof(block_root),
				      "%s/dev/block", sysfs_root) < 0 ||
	    swapz_primary_path_format(link_path, sizeof(link_path), "%s/%u:%u",
				      block_root, major(source_device),
				      minor(source_device)) < 0)
		return 0;
	if (!realpath(devices_root, path))
		return 0;
	resolved_devices_root = strdup(path);
	if (!resolved_devices_root)
		return 0;
	devices_root_length = strlen(resolved_devices_root);
	if (!realpath(link_path, source_realpath) ||
	    strncmp(source_realpath, resolved_devices_root,
		    devices_root_length) ||
	    source_realpath[devices_root_length] != '/')
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      source_realpath) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &observed_source) < 0 ||
	    observed_source != source_device)
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/partition",
				      source_realpath) < 0 ||
	    swapz_primary_read_sysfs_text(path, node_path,
					     sizeof(node_path)) < 0 ||
	    swapz_primary_parse_u64(node_path, &partition_number) < 0 ||
	    partition_number == 0U)
		goto rejected;
	if (swapz_primary_path_format(parent_path, sizeof(parent_path), "%s",
				      source_realpath) < 0)
		goto rejected;
	slash = strrchr(parent_path, '/');
	if (!slash || slash == parent_path)
		goto rejected;
	*slash = '\0';
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      parent_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &observed_parent) < 0 ||
	    observed_parent == source_device ||
	    ((major(target_device) != 0U || minor(target_device) != 0U) &&
	     observed_parent == target_device))
		goto rejected;
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	if (source_device == SWAPZ_PRIMARY_TARGET_DEVICE)
		parent_identity_valid = swapz_primary_owned_nullblk_parent(
			resolved_devices_root, source_realpath, parent_path,
			observed_parent);
#endif
	if (!parent_identity_valid) {
		if (swapz_primary_path_format(device_path, sizeof(device_path),
					       "%s/device", parent_path) < 0 ||
		    lstat(device_path, &link_info) < 0 ||
		    !S_ISLNK(link_info.st_mode) ||
		    !realpath(device_path, device_realpath))
			goto rejected;
		if (strncmp(device_realpath, resolved_devices_root,
			    devices_root_length) ||
		    device_realpath[devices_root_length] != '/' ||
		    strstr(device_realpath, "/virtual/") != NULL)
			goto rejected;
	}
	if (swapz_primary_path_format(path, sizeof(path), "%s/queue",
				      parent_path) < 0 ||
	    stat(path, &queue_info) < 0 || !S_ISDIR(queue_info.st_mode))
		goto rejected;
	if (swapz_primary_path_format(path, sizeof(path), "%s/holders",
				      source_realpath) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 0) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/slaves",
				      source_realpath) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 1) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/holders",
				      parent_path) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 0) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/slaves",
				      parent_path) < 0 ||
	    !swapz_primary_sysfs_directory_empty(path, 1))
		goto rejected;
	*physical_parent_device = observed_parent;
	free(resolved_devices_root);
	return 1;

rejected:
	free(resolved_devices_root);
	return 0;
}

static int swapz_primary_root_source_chain(
	const char *sysfs_root, dev_t root_device, dev_t target_device,
	dev_t *physical_parent_device)
{
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	/*
	 * A Btrfs root mount's mountinfo superblock device can differ from the
	 * st_dev reported by a directory in its subvolume. Bind both pinned paths
	 * by kernel FSID before resolving the sole member in this private test.
	 */
	if (major(root_device) == 0U &&
	    !swapz_primary_owned_nullblk_btrfs_partition(
		    root_device, 1, &root_device))
		return 0;
#else
	/* Production and physical admission never resolve Btrfs backing here. */
	if (major(root_device) == 0U)
		return 0;
#endif
	return swapz_primary_recovery_source_chain(
		sysfs_root, root_device, target_device, physical_parent_device);
}

static int swapz_primary_recovery_preflight(
	int *directory_safe, int *persistent_filesystem,
	unsigned int *filesystem_major, unsigned int *filesystem_minor,
	int *directly_not_target, int *source_chain_checked,
	unsigned int *physical_parent_major, unsigned int *physical_parent_minor,
	int *active_marker_clear)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)directory_safe;
	(void)persistent_filesystem;
	(void)filesystem_major;
	(void)filesystem_minor;
	(void)directly_not_target;
	(void)source_chain_checked;
	(void)physical_parent_major;
	(void)physical_parent_minor;
	(void)active_marker_clear;
	errno = ENODEV;
	return -1;
#else
	struct stat directory_info;
	struct statfs filesystem_info;
	struct stat marker_info;
	char marker_name[96];
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	dev_t source_device;
	dev_t source_parent_device = 0;
#endif
	int recovery_fd;
	int marker_result;
#ifndef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	int runtime_state_missing = 0;
	struct stat runtime_state_path;
#endif

	if (!directory_safe || !persistent_filesystem || !filesystem_major ||
	    !filesystem_minor || !directly_not_target || !source_chain_checked ||
	    !physical_parent_major || !physical_parent_minor ||
	    !active_marker_clear) {
		errno = EINVAL;
		return -1;
	}
	*directory_safe = 0;
	*persistent_filesystem = 0;
	*filesystem_major = 0;
	*filesystem_minor = 0;
	*directly_not_target = 0;
	*source_chain_checked = 0;
	*physical_parent_major = 0;
	*physical_parent_minor = 0;
	*active_marker_clear = 0;
	if (!swapz_primary_target_valid(&swapz_primary_selected_target)) {
		errno = ENODEV;
		return -1;
	}
#ifndef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	if (lstat(SWAPZ_PRIMARY_RUNTIME_STATE_BASE, &runtime_state_path) < 0) {
		if (errno != ENOENT)
			return -1;
		runtime_state_missing = 1;
		recovery_fd = swapz_primary_runtime_state_parent_open();
	} else {
		recovery_fd = swapz_primary_recovery_base_open(
			SWAPZ_PRIMARY_RUNTIME_STATE_BASE, 0);
	}
#else
	recovery_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RUNTIME_STATE_BASE, 0);
#endif
	if (recovery_fd < 0)
		return -1;
	if (fstat(recovery_fd, &directory_info) < 0 ||
	    fstatfs(recovery_fd, &filesystem_info) < 0) {
		int saved_errno = errno;

		close(recovery_fd);
		errno = saved_errno;
		return -1;
	}
	*directory_safe = 1;
	*persistent_filesystem =
		swapz_primary_runtime_state_fs_magic(filesystem_info.f_type);
	*filesystem_major = major(directory_info.st_dev);
	*filesystem_minor = minor(directory_info.st_dev);
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	*directly_not_target =
		(*filesystem_major != 0U || *filesystem_minor != 0U) &&
		!(*filesystem_major == swapz_primary_selected_target.device_major &&
		  *filesystem_minor == swapz_primary_selected_target.device_minor);
	source_device = makedev(*filesystem_major, *filesystem_minor);
	if (*persistent_filesystem && *directly_not_target &&
	    swapz_primary_recovery_source_chain(
		    "/sys", source_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    &source_parent_device)) {
		*source_chain_checked = 1;
		*physical_parent_major = major(source_parent_device);
		*physical_parent_minor = minor(source_parent_device);
	}
#else
	/*
	 * Production runtime state is tmpfs and therefore has no physical backing
	 * parent to compare against the swap target. These legacy plan booleans
	 * remain true for ABI continuity while the parent identity stays 0:0.
	 */
	*directly_not_target = *persistent_filesystem;
	*source_chain_checked = *persistent_filesystem;
#endif
#ifndef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	if (runtime_state_missing) {
		/* No state directory means no ownership marker can exist yet. */
		*active_marker_clear = 1;
	} else
#endif
	{
		if (snprintf(marker_name, sizeof(marker_name), "partition-%s.active",
			     SWAPZ_PRIMARY_PARTUUID) < 0 ||
		    strlen(marker_name) >= sizeof(marker_name)) {
			close(recovery_fd);
			errno = EOVERFLOW;
			return -1;
		}
		marker_result = fstatat(recovery_fd, marker_name, &marker_info,
					AT_SYMLINK_NOFOLLOW);
		if (marker_result < 0 && errno == ENOENT)
			*active_marker_clear = 1;
	}
	if (close(recovery_fd) < 0)
		return -1;
	return 0;
#endif
}

static int swapz_primary_mutation_lock_at(const char *directory,
					      uid_t expected_owner)
{
	struct stat directory_info;
	struct stat lock_info;
	struct stat named_info;
	int directory_fd = -1;
	int lock_fd = -1;
	int saved_errno;

	if (!directory || directory[0] != '/') {
		errno = EINVAL;
		return -1;
	}
	directory_fd = open(directory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW |
				    O_CLOEXEC);
	if (directory_fd < 0 && errno == ENOENT) {
		/*
		 * /run is volatile. Recreate only the configured lock directory,
		 * then reopen and validate its ownership/mode before trusting it.
		 * mkdir() cannot replace an existing object; O_NOFOLLOW and the
		 * metadata checks below reject a raced symlink or foreign inode.
		 */
		if (mkdir(directory, 0755) < 0 && errno != EEXIST)
			return -1;
		directory_fd = open(directory,
				    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	}
	if (directory_fd < 0)
		return -1;
	if (fstat(directory_fd, &directory_info) < 0)
		goto failed;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0022U) != 0U) {
		errno = EPERM;
		goto failed;
	}
	lock_fd = openat(directory_fd, SWAPZ_PRIMARY_MUTATION_LOCK_NAME,
			 O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (lock_fd < 0)
		goto failed;
	if (fstat(lock_fd, &lock_info) < 0)
		goto failed;
	if (!S_ISREG(lock_info.st_mode) || lock_info.st_uid != expected_owner ||
	    (lock_info.st_mode & 0777U) != 0600U || lock_info.st_nlink != 1) {
		errno = EPERM;
		goto failed;
	}
	if (flock(lock_fd, LOCK_EX | LOCK_NB) < 0)
		goto failed;
	if (fstatat(directory_fd, SWAPZ_PRIMARY_MUTATION_LOCK_NAME, &named_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (!S_ISREG(named_info.st_mode) ||
	    named_info.st_dev != lock_info.st_dev ||
	    named_info.st_ino != lock_info.st_ino ||
	    named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U ||
	    named_info.st_nlink != 1) {
		errno = ESTALE;
		goto failed;
	}
	if (close(directory_fd) < 0) {
		saved_errno = errno;
		(void)close(lock_fd);
		errno = saved_errno;
		return -1;
	}
	return lock_fd;

failed:
	saved_errno = errno ? errno : EIO;
	if (lock_fd >= 0)
		(void)close(lock_fd);
	if (directory_fd >= 0)
		(void)close(directory_fd);
	errno = saved_errno;
	return -1;
}

static int swapz_primary_mutation_lock(void)
{
	return swapz_primary_mutation_lock_at(
		SWAPZ_PRIMARY_MUTATION_LOCK_DIRECTORY, 0);
}

/*
 * The installer keeps every uncommitted (including interrupted staging)
 * transaction as an entry in this private durable directory. A flock alone
 * cannot prove completion: process death releases it without removing the
 * journal. Never open an entry or parse its potentially torn state.json;
 * even an empty transaction directory is independently incomplete.
 *
 * The caller holds package.lock. Anchor the directory lookup to a verified
 * parent, reject mount substitution (including same-filesystem bind mounts),
 * and recheck both pathname identities after scanning.
 */
static int swapz_primary_package_transactions_clear_at(
	const char *directory, uid_t expected_owner)
{
	struct stat parent_info;
	struct stat named_parent_info;
	struct stat transaction_info;
	struct stat named_transaction_info;
	struct statx parent_mount;
	struct statx named_parent_mount;
	struct statx transaction_mount;
	struct statx named_transaction_mount;
	struct dirent *entry;
	DIR *entries = NULL;
	const char *separator;
	const char *directory_name;
	char parent_path[PATH_MAX];
	size_t parent_length;
	int parent_fd = -1;
	int transaction_fd = -1;
	int result = -1;
	int saved_errno;

	if (!directory || directory[0] != '/') {
		errno = EINVAL;
		return -1;
	}
	separator = strrchr(directory, '/');
	if (!separator || !separator[1] || !strcmp(separator + 1, ".") ||
	    !strcmp(separator + 1, "..")) {
		errno = EINVAL;
		return -1;
	}
	parent_length = (size_t)(separator - directory);
	if (parent_length >= sizeof(parent_path) ||
	    strlen(directory) >= PATH_MAX) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (parent_length) {
		memcpy(parent_path, directory, parent_length);
		parent_path[parent_length] = '\0';
	} else {
		memcpy(parent_path, "/", sizeof("/"));
	}
	directory_name = separator + 1;
	parent_fd = open(parent_path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW |
				    O_NONBLOCK | O_CLOEXEC);
	if (parent_fd < 0)
		return -1;
	if (fstat(parent_fd, &parent_info) < 0 ||
	    statx(parent_fd, "", AT_EMPTY_PATH, STATX_MNT_ID,
		  &parent_mount) < 0)
		goto out;
	if (!S_ISDIR(parent_info.st_mode) ||
	    parent_info.st_uid != expected_owner ||
	    (parent_info.st_mode & 0022U) != 0U ||
	    !(parent_mount.stx_mask & STATX_MNT_ID)) {
		errno = EPERM;
		goto out;
	}
	transaction_fd = openat(parent_fd, directory_name,
				O_RDONLY | O_DIRECTORY | O_NOFOLLOW |
				O_NONBLOCK | O_CLOEXEC);
	if (transaction_fd < 0) {
		if (errno != ENOENT)
			goto out;
		/* No transaction parent yet is clean only while still absent. */
		if (fstatat(parent_fd, directory_name, &named_transaction_info,
			    AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT) {
			errno = ESTALE;
			goto out;
		}
		result = 0;
		goto verify_parent;
	}
	if (fstat(transaction_fd, &transaction_info) < 0 ||
	    statx(transaction_fd, "", AT_EMPTY_PATH,
		  STATX_BASIC_STATS | STATX_MNT_ID,
		  &transaction_mount) < 0)
		goto out;
	if (!S_ISDIR(transaction_info.st_mode) ||
	    transaction_info.st_uid != expected_owner ||
	    (transaction_info.st_mode & 0777U) != 0700U ||
	    transaction_info.st_dev != parent_info.st_dev ||
	    !(transaction_mount.stx_mask & STATX_MNT_ID) ||
	    transaction_mount.stx_mnt_id != parent_mount.stx_mnt_id) {
		errno = EPERM;
		goto out;
	}
	entries = fdopendir(transaction_fd);
	if (!entries)
		goto out;
	transaction_fd = -1; /* closedir owns the descriptor from here on */
	errno = 0;
	while ((entry = readdir(entries))) {
		if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) {
			errno = EBUSY;
			goto out;
		}
		errno = 0;
	}
	if (errno)
		goto out;
	if (fstatat(parent_fd, directory_name, &named_transaction_info,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    statx(parent_fd, directory_name, AT_SYMLINK_NOFOLLOW,
		  STATX_BASIC_STATS | STATX_MNT_ID,
		  &named_transaction_mount) < 0)
		goto out;
	if (!S_ISDIR(named_transaction_info.st_mode) ||
	    named_transaction_info.st_dev != transaction_info.st_dev ||
	    named_transaction_info.st_ino != transaction_info.st_ino ||
	    named_transaction_info.st_uid != expected_owner ||
	    (named_transaction_info.st_mode & 0777U) != 0700U ||
	    !(named_transaction_mount.stx_mask & STATX_INO) ||
	    !(named_transaction_mount.stx_mask & STATX_TYPE) ||
	    named_transaction_mount.stx_ino != transaction_info.st_ino ||
	    named_transaction_mount.stx_dev_major !=
		    major(transaction_info.st_dev) ||
	    named_transaction_mount.stx_dev_minor !=
		    minor(transaction_info.st_dev) ||
	    named_transaction_mount.stx_uid != transaction_info.st_uid ||
	    (named_transaction_mount.stx_mode & S_IFMT) != S_IFDIR ||
	    !(named_transaction_mount.stx_mask & STATX_MNT_ID) ||
	    named_transaction_mount.stx_mnt_id !=
		    transaction_mount.stx_mnt_id) {
		errno = ESTALE;
		goto out;
	}
	result = 0;

verify_parent:
	if (fstatat(AT_FDCWD, parent_path, &named_parent_info,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    statx(AT_FDCWD, parent_path, AT_SYMLINK_NOFOLLOW,
		  STATX_BASIC_STATS | STATX_MNT_ID,
		  &named_parent_mount) < 0) {
		result = -1;
		goto out;
	}
	if (!S_ISDIR(named_parent_info.st_mode) ||
	    named_parent_info.st_dev != parent_info.st_dev ||
	    named_parent_info.st_ino != parent_info.st_ino ||
	    named_parent_info.st_uid != expected_owner ||
	    (named_parent_info.st_mode & 0022U) != 0U ||
	    !(named_parent_mount.stx_mask & STATX_INO) ||
	    !(named_parent_mount.stx_mask & STATX_TYPE) ||
	    named_parent_mount.stx_ino != parent_info.st_ino ||
	    named_parent_mount.stx_dev_major != major(parent_info.st_dev) ||
	    named_parent_mount.stx_dev_minor != minor(parent_info.st_dev) ||
	    named_parent_mount.stx_uid != parent_info.st_uid ||
	    (named_parent_mount.stx_mode & S_IFMT) != S_IFDIR ||
	    !(named_parent_mount.stx_mask & STATX_MNT_ID) ||
	    named_parent_mount.stx_mnt_id != parent_mount.stx_mnt_id) {
		errno = ESTALE;
		result = -1;
	}

out:
	saved_errno = errno ? errno : EIO;
	if (entries && closedir(entries) < 0 && result == 0) {
		saved_errno = errno;
		result = -1;
	}
	if (transaction_fd >= 0 && close(transaction_fd) < 0 &&
	    result == 0) {
		saved_errno = errno;
		result = -1;
	}
	if (close(parent_fd) < 0 && result == 0) {
		saved_errno = errno;
		result = -1;
	}
	if (result < 0)
		errno = saved_errno;
	return result;
}

static int swapz_primary_partition_lock_at(int recovery_fd,
						   const char *partuuid,
						   uid_t expected_owner)
{
	struct stat info;
	char name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	int fd;

	if (recovery_fd < 0 || !swapz_primary_valid_partuuid(partuuid)) {
		errno = EINVAL;
		return -1;
	}
	{
		int length = snprintf(name, sizeof(name), "partition-%s.lock",
				      partuuid);

		if (length < 0 || (size_t)length >= sizeof(name)) {
			errno = ENAMETOOLONG;
			return -1;
		}
	}
	fd = openat(recovery_fd, name, O_RDWR | O_CREAT | O_NOFOLLOW |
		    O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &info) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0777U) != 0600U || info.st_nlink != 1) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	if (flock(fd, LOCK_EX | LOCK_NB) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (fsync(recovery_fd) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	return fd;
}

static int swapz_primary_valid_run_id(const char *run_id)
{
	size_t i;
	int nonzero = 0;

	if (!run_id ||
	    strnlen(run_id, SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U) !=
		    SWAPZ_PRIMARY_RUN_ID_LENGTH)
		return 0;
	for (i = 0; i < SWAPZ_PRIMARY_RUN_ID_LENGTH; ++i) {
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return 0;
		nonzero |= run_id[i] != '0';
	}
	return nonzero;
}

static int swapz_primary_write_record_at(int recovery_fd, const char *name,
						 const char *record,
						 uid_t expected_owner)
{
	struct stat info;
	const char *cursor = record;
	size_t remaining = strlen(record);
	int fd;
	int saved_errno;

	fd = openat(recovery_fd, name, O_WRONLY | O_CREAT | O_EXCL |
		    O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &info) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0777U) != 0600U || info.st_nlink != 1) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	while (remaining) {
		ssize_t count = write(fd, cursor, remaining);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			saved_errno = count < 0 ? errno : EIO;
			close(fd);
			errno = saved_errno;
			return -1;
		}
		cursor += count;
		remaining -= (size_t)count;
	}
	if (fsync(fd) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	return fsync(recovery_fd);
}

int swapz_primary_replace_record_at(int recovery_fd, const char *name,
				    const char *run_id, const char *record,
				    uid_t expected_owner)
{
	struct stat directory_info;
	struct stat old_info;
	struct stat current_info;
	struct stat temporary_info;
	char temporary_name[256];
	const unsigned char *name_cursor;
	const char *record_cursor = record;
	size_t remaining;
	int old_present = 0;
	int temporary_identity_valid = 0;
	int fd = -1;
	int saved_errno;
	int length;
	size_t name_length;

	if (recovery_fd < 0 || !name || !run_id || !record ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	remaining = strnlen(record, SWAPZ_PRIMARY_STATE_RECORD_MAX);
	if (remaining == SWAPZ_PRIMARY_STATE_RECORD_MAX) {
		errno = EOVERFLOW;
		return -1;
	}
	name_length = strnlen(name, 128U);
	if (!name_length || name_length == 128U || name[0] == '.') {
		errno = EINVAL;
		return -1;
	}
	for (name_cursor = (const unsigned char *)name; *name_cursor;
	     ++name_cursor)
		if (!((*name_cursor >= 'a' && *name_cursor <= 'z') ||
		      (*name_cursor >= 'A' && *name_cursor <= 'Z') ||
		      (*name_cursor >= '0' && *name_cursor <= '9') ||
		      *name_cursor == '.' || *name_cursor == '_' ||
		      *name_cursor == '-')) {
			errno = EINVAL;
			return -1;
		}
	if (fstat(recovery_fd, &directory_info) < 0)
		return -1;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	length = snprintf(temporary_name, sizeof(temporary_name), ".%s.%s.tmp",
			  name, run_id);
	if (length < 0 || (size_t)length >= sizeof(temporary_name)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, name, &old_info, AT_SYMLINK_NOFOLLOW) == 0) {
		if (!S_ISREG(old_info.st_mode) || old_info.st_uid != expected_owner ||
		    (old_info.st_mode & 0777U) != 0600U || old_info.st_nlink != 1) {
			errno = EPERM;
			return -1;
		}
		old_present = 1;
	} else if (errno != ENOENT) {
		return -1;
	}
	fd = openat(recovery_fd, temporary_name,
		    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &temporary_info) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (!S_ISREG(temporary_info.st_mode) ||
	    temporary_info.st_uid != expected_owner ||
	    (temporary_info.st_mode & 0777U) != 0600U ||
	    temporary_info.st_nlink != 1) {
		saved_errno = EPERM;
		goto failed;
	}
	temporary_identity_valid = 1;
	while (remaining) {
		ssize_t count = write(fd, record_cursor, remaining);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			saved_errno = count < 0 ? errno : EIO;
			goto failed;
		}
		record_cursor += count;
		remaining -= (size_t)count;
	}
	if (fsync(fd) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (fstatat(recovery_fd, temporary_name, &current_info,
		    AT_SYMLINK_NOFOLLOW) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (current_info.st_dev != temporary_info.st_dev ||
	    current_info.st_ino != temporary_info.st_ino ||
	    !S_ISREG(current_info.st_mode) || current_info.st_nlink != 1) {
		saved_errno = EPERM;
		goto failed;
	}
	if (old_present) {
		if (fstatat(recovery_fd, name, &current_info,
			    AT_SYMLINK_NOFOLLOW) < 0) {
			saved_errno = errno;
			goto failed;
		}
		if (current_info.st_dev != old_info.st_dev ||
		    current_info.st_ino != old_info.st_ino ||
		    !S_ISREG(current_info.st_mode) ||
		    current_info.st_uid != expected_owner ||
		    (current_info.st_mode & 0777U) != 0600U ||
		    current_info.st_nlink != 1) {
			saved_errno = EPERM;
			goto failed;
		}
	} else {
		if (fstatat(recovery_fd, name, &current_info,
			    AT_SYMLINK_NOFOLLOW) == 0) {
			saved_errno = EEXIST;
			goto failed;
		}
		if (errno != ENOENT) {
			saved_errno = errno;
			goto failed;
		}
	}
	/*
	 * close() may report an error after releasing the descriptor. Complete
	 * that boundary before rename so a failed close cannot publish a stage.
	 * Only recovery_fd remains borrowed; this temporary fd is owned here.
	 */
	if (close(fd) < 0) {
		saved_errno = errno;
		fd = -1;
		goto failed;
	}
	fd = -1;
	if (renameat(recovery_fd, temporary_name, recovery_fd, name) < 0) {
		saved_errno = errno;
		goto failed;
	}
	return fsync(recovery_fd);

failed:
	{
		struct stat named_info;

		if (temporary_identity_valid &&
		    fstatat(recovery_fd, temporary_name, &named_info,
			    AT_SYMLINK_NOFOLLOW) == 0 &&
		    named_info.st_dev == temporary_info.st_dev &&
		    named_info.st_ino == temporary_info.st_ino)
			(void)unlinkat(recovery_fd, temporary_name, 0);
	}
	if (fd >= 0)
		(void)close(fd);
	errno = saved_errno;
	return -1;
}

int swapz_primary_claim_partition_owner_at(int recovery_fd, int lock_fd,
						  const char *run_id,
						  uid_t expected_owner)
{
	struct swapz_primary_state previous_state;
	struct swapz_primary_state ready_state = {0};
	struct stat directory_info;
	struct stat held_lock_info;
	struct stat named_lock_info;
	struct stat marker_info;
	char lock_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	char active_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	char consumed_name[64];
	char record[192];
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t state_length;
	int count;
	int state_length_formatted;
	int previous_state_present = 0;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (fstat(recovery_fd, &directory_info) < 0)
		return -1;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	if (snprintf(lock_name, sizeof(lock_name), "partition-%s.lock",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(consumed_name, sizeof(consumed_name), "consumed-%s.json",
		     run_id) < 0) {
		errno = EIO;
		return -1;
	}
	if (fstat(lock_fd, &held_lock_info) < 0 ||
	    fstatat(recovery_fd, lock_name, &named_lock_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		return -1;
	if (!S_ISREG(held_lock_info.st_mode) ||
	    held_lock_info.st_uid != expected_owner ||
	    (held_lock_info.st_mode & 0777U) != 0600U ||
	    held_lock_info.st_nlink != 1 ||
	    held_lock_info.st_dev != named_lock_info.st_dev ||
	    held_lock_info.st_ino != named_lock_info.st_ino ||
	    !S_ISREG(named_lock_info.st_mode) ||
	    named_lock_info.st_uid != expected_owner ||
	    (named_lock_info.st_mode & 0777U) != 0600U ||
	    named_lock_info.st_nlink != 1) {
		errno = EPERM;
		return -1;
	}
	if (flock(lock_fd, LOCK_EX | LOCK_NB) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &marker_info,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EBUSY;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 NULL) == 0) {
		if (swapz_primary_state_parse(state_record, state_length,
					      &previous_state) < 0 ||
		    previous_state.stage != SWAPZ_PRIMARY_STAGE_COMPLETE) {
			errno = EBUSY;
			return -1;
		}
		previous_state_present = 1;
	} else if (errno != ENOENT) {
		return -1;
	}
	if (fstatat(recovery_fd, consumed_name, &marker_info,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	count = snprintf(record, sizeof(record),
			 "{\"major\":%u,\"minor\":%u,\"partuuid\":\"%s\","
			 "\"run_id\":\"%s\"}\n",
			 swapz_primary_selected_target.device_major,
			 swapz_primary_selected_target.device_minor,
			 SWAPZ_PRIMARY_PARTUUID, run_id);
	if (count < 0 || (size_t)count >= sizeof(record)) {
		errno = EOVERFLOW;
		return -1;
	}
	memcpy(ready_state.run_id, run_id, sizeof(ready_state.run_id));
	ready_state.stage = SWAPZ_PRIMARY_STAGE_READY;
	if (previous_state_present &&
	    !swapz_primary_state_transition_allowed(&previous_state,
						   &ready_state)) {
		errno = EPERM;
		return -1;
	}
	state_length_formatted = swapz_primary_state_format(
		&ready_state, state_record, sizeof(state_record));
	if (state_length_formatted < 0)
		return -1;
	if (swapz_primary_write_record_at(recovery_fd, consumed_name,
					  record, expected_owner) < 0)
		return -1;
	if (swapz_primary_replace_record_at(
		    recovery_fd, "primary-state.json", run_id, state_record,
		    expected_owner) < 0)
		return -1;
	return swapz_primary_write_record_at(recovery_fd, active_name,
					     record, expected_owner);
}

static int swapz_primary_state_lock_valid(int recovery_fd, int lock_fd,
					  uid_t expected_owner)
{
	struct stat directory_info;
	struct stat held_lock_info;
	struct stat named_lock_info;
	char lock_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_target_valid(&swapz_primary_selected_target) ||
	    fstat(recovery_fd, &directory_info) < 0 ||
	    fstat(lock_fd, &held_lock_info) < 0)
		return 0;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U ||
	    !S_ISREG(held_lock_info.st_mode) ||
	    held_lock_info.st_uid != expected_owner ||
	    (held_lock_info.st_mode & 0777U) != 0600U ||
	    held_lock_info.st_nlink != 1) {
		errno = EPERM;
		return 0;
	}
	if (snprintf(lock_name, sizeof(lock_name), "partition-%s.lock",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    fstatat(recovery_fd, lock_name, &named_lock_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		return 0;
	if (!S_ISREG(named_lock_info.st_mode) ||
	    named_lock_info.st_uid != expected_owner ||
	    (named_lock_info.st_mode & 0777U) != 0600U ||
	    named_lock_info.st_nlink != 1 ||
	    named_lock_info.st_dev != held_lock_info.st_dev ||
	    named_lock_info.st_ino != held_lock_info.st_ino) {
		errno = EPERM;
		return 0;
	}
	return flock(lock_fd, LOCK_EX | LOCK_NB) == 0;
}

static int swapz_primary_record_read_at(int recovery_fd, const char *name,
					uid_t expected_owner, char *record,
					size_t capacity, size_t *length,
					struct stat *identity)
{
	struct stat opened_info;
	struct stat named_info;
	struct stat after_info;
	unsigned char extra;
	size_t completed = 0;
	int fd;

	if (recovery_fd < 0 || !name || !record || capacity < 2U || !length) {
		errno = EINVAL;
		return -1;
	}
	if (fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) < 0)
		return -1;
	fd = openat(recovery_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened_info) < 0)
		goto failed;
	if (!S_ISREG(opened_info.st_mode) ||
	    opened_info.st_uid != expected_owner ||
	    (opened_info.st_mode & 0777U) != 0600U ||
	    opened_info.st_nlink != 1 || opened_info.st_size <= 0 ||
	    (uint64_t)opened_info.st_size >= (uint64_t)capacity ||
	    (uint64_t)opened_info.st_size > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    opened_info.st_dev != named_info.st_dev ||
	    opened_info.st_ino != named_info.st_ino) {
		errno = EPERM;
		goto failed;
	}
	while (completed < (size_t)opened_info.st_size) {
		ssize_t count = pread(fd, record + completed,
				      (size_t)opened_info.st_size - completed,
				      (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		completed += (size_t)count;
	}
	for (;;) {
		ssize_t count = pread(fd, &extra, sizeof(extra),
				      opened_info.st_size);

		if (count < 0 && errno == EINTR)
			continue;
		if (count != 0) {
			if (count > 0)
				errno = EOVERFLOW;
			goto failed;
		}
		break;
	}
	if (fstat(fd, &after_info) < 0 ||
	    fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (after_info.st_dev != opened_info.st_dev ||
	    after_info.st_ino != opened_info.st_ino ||
	    after_info.st_size != opened_info.st_size ||
	    after_info.st_mtim.tv_sec != opened_info.st_mtim.tv_sec ||
	    after_info.st_mtim.tv_nsec != opened_info.st_mtim.tv_nsec ||
	    after_info.st_ctim.tv_sec != opened_info.st_ctim.tv_sec ||
	    after_info.st_ctim.tv_nsec != opened_info.st_ctim.tv_nsec ||
	    after_info.st_uid != expected_owner ||
	    (after_info.st_mode & 0777U) != 0600U ||
	    !S_ISREG(after_info.st_mode) || after_info.st_nlink != 1 ||
	    named_info.st_dev != opened_info.st_dev ||
	    named_info.st_ino != opened_info.st_ino ||
	    named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U ||
	    !S_ISREG(named_info.st_mode) || named_info.st_nlink != 1) {
		errno = EPERM;
		goto failed;
	}
	if (close(fd) < 0)
		return -1;
	*length = completed;
	record[completed] = '\0';
	if (identity)
		*identity = opened_info;
	return 0;

failed:
	{
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
}

static int swapz_primary_owner_claim_matches_at(int recovery_fd,
						const char *run_id,
						uid_t expected_owner)
{
	char active_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	char consumed_name[64];
	char expected[192];
	char active_record[256];
	char consumed_record[256];
	size_t active_length;
	size_t consumed_length;
	int expected_length;

	if (!swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return 0;
	}
	if (snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    snprintf(consumed_name, sizeof(consumed_name), "consumed-%s.json",
		     run_id) < 0)
		return 0;
	expected_length = snprintf(expected, sizeof(expected),
				   "{\"major\":%u,\"minor\":%u,"
				   "\"partuuid\":\"%s\",\"run_id\":\"%s\"}\n",
				   swapz_primary_selected_target.device_major,
				   swapz_primary_selected_target.device_minor,
				   SWAPZ_PRIMARY_PARTUUID, run_id);
	if (expected_length < 0 || (size_t)expected_length >= sizeof(expected)) {
		errno = EOVERFLOW;
		return 0;
	}
	if (swapz_primary_record_read_at(recovery_fd, active_name,
					 expected_owner, active_record,
					 sizeof(active_record), &active_length,
					 NULL) < 0 ||
	    swapz_primary_record_read_at(recovery_fd, consumed_name,
					 expected_owner, consumed_record,
					 sizeof(consumed_record), &consumed_length,
					 NULL) < 0)
		return 0;
	if (active_length != (size_t)expected_length ||
	    consumed_length != (size_t)expected_length ||
	    memcmp(active_record, expected, active_length) ||
	    memcmp(consumed_record, expected, consumed_length)) {
		errno = EPERM;
		return 0;
	}
	return 1;
}

static int swapz_primary_reconcile_state_temporary_file_at(
	int recovery_fd, const char *run_id, uid_t expected_owner)
{
	struct stat info;
	char temporary_name[256];
	int length;

	if (recovery_fd < 0 || !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(temporary_name, sizeof(temporary_name),
			  ".primary-state.json.%s.tmp", run_id);
	if (length < 0 || (size_t)length >= sizeof(temporary_name)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, temporary_name, &info,
		    AT_SYMLINK_NOFOLLOW) < 0) {
		if (errno == ENOENT)
			return 0;
		return -1;
	}
	if (!S_ISREG(info.st_mode) || info.st_uid != expected_owner ||
	    (info.st_mode & 0777U) != 0600U || info.st_nlink != 1) {
		errno = EPERM;
		return -1;
	}
	if (unlinkat(recovery_fd, temporary_name, 0) < 0)
		return -1;
	/*
	 * This fsync is the proof that stale unpublished evidence was removed.
	 * If it fails, this state write remains blocked. A later retry may see the
	 * name absent, but cannot publish success until replace_record_at() reaches
	 * its own recovery-directory fsync.
	 */
	if (fsync(recovery_fd) < 0)
		return -1;
	if (fstatat(recovery_fd, temporary_name, &info,
		    AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT) {
		errno = EIO;
		return -1;
	}
	return 0;
}

static int swapz_primary_reconcile_state_temporary_at(
	int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner)
{
	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(
		    recovery_fd, run_id, expected_owner))
		return -1;
	return swapz_primary_reconcile_state_temporary_file_at(
		recovery_fd, run_id, expected_owner);
}

/*
 * READY with an exact active marker or with no active marker can only be left
 * by interruption during metadata-only preparation. STARTING must be durable
 * before any device mutation. COMPLETE with an exact active marker can only
 * be left by interruption before marker release. Preserve consumed runs and
 * close only these states through durable lifecycle edges.
 */
static int swapz_primary_reconcile_metadata_claim_at(
	int recovery_fd, int lock_fd, uid_t expected_owner)
{
	struct swapz_primary_state current;
	struct swapz_primary_state next;
	struct stat active_info;
	char active_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	char consumed_name[64];
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char consumed_record[256];
	char expected_record[192];
	size_t state_length;
	size_t consumed_length;
	int expected_length;
	int formatted_length;
	int active_present = 0;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner))
		return -1;
	if (snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0) {
		errno = EOVERFLOW;
		return -1;
	}
	if (fstatat(recovery_fd, active_name, &active_info,
		    AT_SYMLINK_NOFOLLOW) == 0)
		active_present = 1;
	else if (errno != ENOENT)
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 NULL) < 0) {
		if (errno == ENOENT && !active_present)
			return 0;
		if (errno == ENOENT)
			errno = EBADMSG;
		return -1;
	}
	if (swapz_primary_state_parse(state_record, state_length, &current) < 0) {
		errno = EBADMSG;
		return -1;
	}
	if (current.stage != SWAPZ_PRIMARY_STAGE_READY &&
	    current.stage != SWAPZ_PRIMARY_STAGE_COMPLETE) {
		errno = EBUSY;
		return -1;
	}
	if (snprintf(consumed_name, sizeof(consumed_name), "consumed-%s.json",
		     current.run_id) < 0) {
		errno = EOVERFLOW;
		return -1;
	}
	expected_length = snprintf(
		expected_record, sizeof(expected_record),
		"{\"major\":%u,\"minor\":%u,\"partuuid\":\"%s\","
		"\"run_id\":\"%s\"}\n",
		swapz_primary_selected_target.device_major,
		swapz_primary_selected_target.device_minor,
		SWAPZ_PRIMARY_PARTUUID, current.run_id);
	if (expected_length < 0 ||
	    (size_t)expected_length >= sizeof(expected_record)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (swapz_primary_record_read_at(recovery_fd, consumed_name,
					 expected_owner, consumed_record,
					 sizeof(consumed_record), &consumed_length,
					 NULL) < 0)
		return -1;
	if (consumed_length != (size_t)expected_length ||
	    memcmp(consumed_record, expected_record, consumed_length)) {
		errno = EPERM;
		return -1;
	}
	if (active_present) {
		char active_record[256];
		size_t active_length;
		struct stat active_identity;

		if (swapz_primary_record_read_at(
			    recovery_fd, active_name, expected_owner,
			    active_record, sizeof(active_record), &active_length,
			    &active_identity) < 0 ||
		    active_identity.st_dev != active_info.st_dev ||
		    active_identity.st_ino != active_info.st_ino ||
		    active_length != (size_t)expected_length ||
		    memcmp(active_record, expected_record, active_length)) {
			errno = EPERM;
			return -1;
		}
	}
	if (current.stage == SWAPZ_PRIMARY_STAGE_COMPLETE) {
		if (active_present)
			return swapz_primary_release_partition_owner_at(
				recovery_fd, lock_fd, current.run_id,
				expected_owner);
		/*
		 * A prior unlink may be visible despite a failed directory fsync.
		 * Retry the durability boundary under the partition lock before
		 * allowing a new owner to claim this completed transaction.
		 * The lock serializes cooperative owners; only recovery_fd is
		 * borrowed and no file descriptor ownership transfers here.
		 */
		return fsync(recovery_fd);
	}
	if (current.has_recovery_previous_stage) {
		errno = EBUSY;
		return -1;
	}
	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	/*
	 * READY guarantees no device mutation has started. Close this metadata-
	 * only abort with one atomic state replacement: an intermediate DISABLING
	 * record would be ambiguous with a real teardown after a crash.
	 */
	/*
	 * READY may be durable before the active marker is created. The canonical
	 * state and consumed record above already prove this run under the held
	 * partition lock, so reconcile only its deterministic unpublished temp
	 * without requiring an active-marker claim.
	 */
	if (swapz_primary_reconcile_state_temporary_file_at(
		    recovery_fd, current.run_id, expected_owner) < 0)
		return -1;
	formatted_length = swapz_primary_state_format(
		&next, state_record, sizeof(state_record));
	if (formatted_length < 0 ||
	    swapz_primary_replace_record_at(
		    recovery_fd, "primary-state.json", current.run_id,
		    state_record, expected_owner) < 0)
		return -1;
	if (active_present &&
	    swapz_primary_release_partition_owner_at(
		    recovery_fd, lock_fd, current.run_id, expected_owner) < 0)
		return -1;
	return 0;
}

static int swapz_primary_valid_sha256(const char *digest)
{
	unsigned int i;

	if (!digest || strnlen(digest, 65U) != 64U)
		return 0;
	for (i = 0; i < 64U; ++i)
		if (!((digest[i] >= '0' && digest[i] <= '9') ||
		      (digest[i] >= 'a' && digest[i] <= 'f')))
			return 0;
	return 1;
}

static int swapz_primary_lower_hex_span(const char *value, size_t length)
{
	size_t index;

	if (!value || !length)
		return 0;
	for (index = 0; index < length; ++index) {
		unsigned char byte = (unsigned char)value[index];

		if (!((byte >= '0' && byte <= '9') ||
		      (byte >= 'a' && byte <= 'f')))
			return 0;
	}
	return 1;
}

static int swapz_primary_lower_uuid36(const char *value)
{
	size_t index;

	if (!value || strlen(value) != 36U)
		return 0;
	for (index = 0; index < 36U; ++index) {
		if (index == 8U || index == 13U || index == 18U || index == 23U) {
			if (value[index] != '-')
				return 0;
		} else if (!((value[index] >= '0' && value[index] <= '9') ||
			     (value[index] >= 'a' && value[index] <= 'f'))) {
			return 0;
		}
	}
	return 1;
}

#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
/* An ARM64 RAM-only rehearsal has no DMI UUID to normalize. */
static int swapz_primary_host_uuid_normalize(
	const char *value, size_t length, char normalized[37])
{
	size_t index;
	int nonzero = 0;

	if (!value || !normalized || length != 36U) {
		errno = EINVAL;
		return -1;
	}
	for (index = 0; index < 36U; ++index) {
		unsigned char byte = (unsigned char)value[index];

		if (index == 8U || index == 13U || index == 18U || index == 23U) {
			if (byte != '-') {
				errno = EINVAL;
				return -1;
			}
			normalized[index] = '-';
			continue;
		}
		if (!isxdigit(byte)) {
			errno = EINVAL;
			return -1;
		}
		if (byte != '0')
			nonzero = 1;
		normalized[index] = (char)tolower(byte);
	}
	normalized[36] = '\0';
	if (!nonzero) {
		memset(normalized, 0, 37U);
		errno = EINVAL;
		return -1;
	}
	return 0;
}
#endif

static unsigned int swapz_primary_lower_hex_nibble(char byte)
{
	if (byte >= '0' && byte <= '9')
		return (unsigned int)(byte - '0');
	return (unsigned int)(byte - 'a' + 10);
}

static int swapz_primary_dos_partuuid_valid(const char *value,
					    uint32_t partition_number)
{
	unsigned int observed;

	if (!value || strlen(value) != 11U || value[8] != '-' ||
	    !swapz_primary_lower_hex_span(value, 8U) ||
	    !swapz_primary_lower_hex_span(value + 9U, 2U) ||
	    !partition_number || partition_number > 255U)
		return 0;
	observed = swapz_primary_lower_hex_nibble(value[9]) * 16U +
		swapz_primary_lower_hex_nibble(value[10]);
	return observed == partition_number;
}

static int swapz_primary_partition_scope_valid(
	const struct swapz_primary_partition_scope *partition)
{
	dev_t device;
	char normalized_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char normalized_table_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	size_t type_length;
	int type_valid;

	if (!partition || !partition->device_major ||
	    !partition->partition_number || !partition->size_sectors ||
	    partition->start_sectors > UINT64_MAX - partition->size_sectors ||
	    partition->size_sectors > UINT64_MAX / 512ULL ||
	    partition->size_bytes != partition->size_sectors * 512ULL ||
	    swapz_primary_partuuid_normalize(
		    partition->partuuid, normalized_partuuid) < 0 ||
	    strcmp(partition->partuuid, normalized_partuuid) ||
	    (strcmp(partition->partscheme, "dos") &&
	     strcmp(partition->partscheme, "gpt")) ||
	    strcmp(partition->part_table_type, partition->partscheme) ||
	    !partition->parttype[0] ||
	    (strnlen(partition->parttype, sizeof(partition->parttype)) >=
	     sizeof(partition->parttype)) ||
	    swapz_primary_partuuid_normalize(
		    partition->part_table_uuid, normalized_table_uuid) < 0 ||
	    strcmp(partition->part_table_uuid, normalized_table_uuid))
		return 0;
	type_length = strlen(partition->parttype);
	if (!strcmp(partition->partscheme, "dos")) {
		type_valid = type_length == 4U &&
			!strncmp(partition->parttype, "0x", 2U) &&
			swapz_primary_lower_hex_span(
				partition->parttype + 2U, 2U) &&
			swapz_primary_lower_hex_span(
				partition->part_table_uuid, 8U) &&
			swapz_primary_dos_partuuid_valid(
				partition->partuuid,
				partition->partition_number);
	} else {
		type_valid = swapz_primary_lower_uuid36(partition->parttype) &&
			swapz_primary_lower_uuid36(partition->part_table_uuid) &&
			swapz_primary_lower_uuid36(partition->partuuid);
	}
	if (!type_valid)
		return 0;
	device = makedev(partition->device_major, partition->device_minor);
	return major(device) == partition->device_major &&
	       minor(device) == partition->device_minor;
}

static int swapz_primary_partition_scope_layout_valid(
	const struct swapz_primary_partition_scope *partitions, size_t count,
	uint64_t parent_size_sectors,
	const struct swapz_primary_partition_scope *root,
	const struct swapz_primary_partition_scope *target)
{
	size_t left;
	size_t right;
	int root_seen = 0;
	int target_seen = 0;

	if (!partitions || !count || count > SWAPZ_PRIMARY_PARTITION_FACTS_MAX ||
	    !parent_size_sectors ||
	    !swapz_primary_partition_scope_valid(root) ||
	    !swapz_primary_partition_scope_valid(target))
		return 0;
	for (left = 0; left < count; ++left) {
		uint64_t left_end;

		if (!swapz_primary_partition_scope_valid(&partitions[left]))
			return 0;
		left_end = partitions[left].start_sectors +
			   partitions[left].size_sectors;
		if (left_end > parent_size_sectors)
			return 0;
		if (partitions[left].device_major == root->device_major &&
		    partitions[left].device_minor == root->device_minor &&
		    partitions[left].partition_number == root->partition_number &&
		    partitions[left].start_sectors == root->start_sectors &&
		    partitions[left].size_sectors == root->size_sectors &&
		    !strcmp(partitions[left].partuuid, root->partuuid) &&
		    !strcmp(partitions[left].parttype, root->parttype) &&
		    !strcmp(partitions[left].partscheme, root->partscheme) &&
		    !strcmp(partitions[left].part_table_uuid,
			    root->part_table_uuid))
			root_seen = 1;
		if (partitions[left].device_major == target->device_major &&
		    partitions[left].device_minor == target->device_minor &&
		    partitions[left].partition_number == target->partition_number &&
		    partitions[left].start_sectors == target->start_sectors &&
		    partitions[left].size_sectors == target->size_sectors &&
		    !strcmp(partitions[left].partuuid, target->partuuid) &&
		    !strcmp(partitions[left].parttype, target->parttype) &&
		    !strcmp(partitions[left].partscheme, target->partscheme) &&
		    !strcmp(partitions[left].part_table_uuid,
			    target->part_table_uuid))
			target_seen = 1;
		for (right = left + 1U; right < count; ++right) {
			uint64_t right_end;

			if (!swapz_primary_partition_scope_valid(
				    &partitions[right]) ||
			    partitions[left].partition_number ==
				    partitions[right].partition_number ||
			    (partitions[left].device_major ==
				     partitions[right].device_major &&
			     partitions[left].device_minor ==
				     partitions[right].device_minor) ||
			    !strcmp(partitions[left].partuuid,
				    partitions[right].partuuid) ||
			    strcmp(partitions[left].partscheme,
				   partitions[right].partscheme) ||
			    strcmp(partitions[left].part_table_uuid,
				   partitions[right].part_table_uuid) ||
			    strcmp(partitions[left].part_table_type,
				   partitions[right].part_table_type))
				return 0;
			right_end = partitions[right].start_sectors +
				    partitions[right].size_sectors;
			if (right_end > parent_size_sectors)
				return 0;
			if (partitions[left].start_sectors < right_end &&
			    partitions[right].start_sectors < left_end)
				return 0;
		}
	}
	if (!root_seen || !target_seen ||
	    (root->device_major == target->device_major &&
	     root->device_minor == target->device_minor) ||
	    (root->start_sectors + root->size_sectors > target->start_sectors &&
	     target->start_sectors + target->size_sectors > root->start_sectors))
		return 0;
	return 1;
}

static int swapz_primary_shared_root_scope_sha256(
	const struct swapz_primary_shared_root_scope *scope, char digest[65])
{
	char canonical[1024];
	int length;

	if (!scope || !digest ||
	    !swapz_primary_valid_sha256(scope->host_identity_sha256) ||
	    !swapz_primary_partition_scope_valid(&scope->root) ||
	    !swapz_primary_partition_scope_valid(&scope->target) ||
	    (scope->root.device_major == scope->target.device_major &&
	     scope->root.device_minor == scope->target.device_minor) ||
	    (scope->root.start_sectors + scope->root.size_sectors >
	     scope->target.start_sectors &&
	     scope->target.start_sectors + scope->target.size_sectors >
	     scope->root.start_sectors) ||
	    !scope->parent_major || !scope->parent_size_sectors ||
	    !swapz_primary_valid_sha256(scope->parent_identity_sha256) ||
	    !swapz_primary_valid_sha256(scope->partition_layout_sha256)) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(
		canonical, sizeof(canonical),
		"swapz-primary-shared-root-scope-v1\n"
		"host=%s\n"
		"root=%u:%u,%s,%u,%llu,%llu,%llu,%s,%s,%s,%s\n"
		"target=%u:%u,%s,%u,%llu,%llu,%llu,%s,%s,%s,%s\n"
		"parent=%u:%u,%llu,%s\n"
		"layout=%s\n",
		scope->host_identity_sha256,
		scope->root.device_major, scope->root.device_minor,
		scope->root.partuuid, scope->root.partition_number,
		(unsigned long long)scope->root.start_sectors,
		(unsigned long long)scope->root.size_sectors,
		(unsigned long long)scope->root.size_bytes,
		scope->root.parttype,
		scope->root.partscheme, scope->root.part_table_uuid,
		scope->root.part_table_type,
		scope->target.device_major, scope->target.device_minor,
		scope->target.partuuid, scope->target.partition_number,
		(unsigned long long)scope->target.start_sectors,
		(unsigned long long)scope->target.size_sectors,
		(unsigned long long)scope->target.size_bytes,
		scope->target.parttype,
		scope->target.partscheme, scope->target.part_table_uuid,
		scope->target.part_table_type,
		scope->parent_major, scope->parent_minor,
		(unsigned long long)scope->parent_size_sectors,
		scope->parent_identity_sha256,
		scope->partition_layout_sha256);
	if (length <= 0 || (size_t)length >= sizeof(canonical)) {
		errno = EOVERFLOW;
		return -1;
	}
	return swapz_primary_sha256((const unsigned char *)canonical,
				    (size_t)length, digest);
}

static int swapz_primary_shared_root_scope_record_matches(
	const char *record, size_t length, const char expected_scope_sha256[65])
{
	char expected[SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_BYTES];
	int expected_length;

	if (!record || !length || memchr(record, '\0', length) ||
	    !swapz_primary_valid_sha256(expected_scope_sha256))
		return 0;
	expected_length = snprintf(
		expected, sizeof(expected),
		"schema=swapz-primary-shared-root-v1\n"
		"scope_sha256=%s\n", expected_scope_sha256);
	return expected_length > 0 &&
	       (size_t)expected_length < sizeof(expected) &&
	       length == (size_t)expected_length &&
	       !memcmp(record, expected, (size_t)expected_length);
}

/* The exception binds only the exact root/target physical-parent relationship. */
static int swapz_primary_shared_root_parent_relationship_valid(
	dev_t target_parent, dev_t root_parent)
{
	if (!target_parent || target_parent != root_parent) {
		errno = EPERM;
		return 0;
	}
	return 1;
}

static int swapz_primary_shared_root_scope_record_read_at(
	int config_fd, uid_t expected_owner,
	const char expected_scope_sha256[65])
{
	struct stat directory_info;
	struct stat before;
	struct stat after;
	char record[SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_BYTES];
	size_t used = 0;
	int fd = -1;
	int result = -1;
	int saved_errno = 0;

	if (config_fd < 0 ||
	    !swapz_primary_valid_sha256(expected_scope_sha256)) {
		errno = EINVAL;
		return -1;
	}
	if (fstat(config_fd, &directory_info) < 0)
		return -1;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0022U)) {
		errno = EPERM;
		return -1;
	}
	fd = openat(config_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
		    O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		return -1;
	if (fstat(fd, &before) < 0)
		goto out;
	if (!S_ISREG(before.st_mode) || before.st_uid != expected_owner ||
	    (before.st_mode & 07777U) != 0600U || before.st_nlink != 1U ||
	    before.st_size <= 0 ||
	    (uint64_t)before.st_size >= sizeof(record)) {
		errno = EPERM;
		goto out;
	}
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0)
			goto out;
		if (!count)
			break;
		used += (size_t)count;
	}
	if (used == sizeof(record)) {
		errno = EOVERFLOW;
		goto out;
	}
	if (fstat(fd, &after) < 0)
		goto out;
	if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_uid != after.st_uid || before.st_gid != after.st_gid ||
	    before.st_mode != after.st_mode || before.st_nlink != after.st_nlink ||
	    before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec ||
	    used != (size_t)before.st_size) {
		errno = ESTALE;
		goto out;
	}
	if (!swapz_primary_shared_root_scope_record_matches(
		    record, used, expected_scope_sha256)) {
		errno = EPERM;
		goto out;
	}
	result = 0;
out:
	saved_errno = errno;
	if (close(fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	memset(record, 0, sizeof(record));
	errno = saved_errno;
	return result;
}

static int swapz_primary_manifest_name(const char *run_id, char *name,
					       size_t capacity)
{
	int length;

	if (!swapz_primary_valid_run_id(run_id) || !name || !capacity) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(name, capacity, "primary-manifest-%s.txt", run_id);
	if (length < 0 || (size_t)length >= capacity) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return 0;
}

int swapz_primary_manifest_read_at(
	int recovery_fd, int lock_fd, const char *run_id, const char *partuuid,
	uid_t expected_owner,
	struct swapz_primary_manifest *manifest)
{
	struct swapz_primary_manifest parsed;
	char name[96];
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t length;

	if (recovery_fd < 0 || lock_fd < 0 || !manifest ||
	    !swapz_primary_partuuid_valid(partuuid) ||
	    swapz_primary_manifest_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_record_read_at(recovery_fd, name, expected_owner,
					 record, sizeof(record), &length, NULL) < 0)
		return -1;
	if (swapz_primary_manifest_parse(record, length, &parsed) < 0) {
		errno = EBADMSG;
		return -1;
	}
	if (strcmp(parsed.run_id, run_id) ||
	    strcmp(parsed.target.partuuid, partuuid)) {
		errno = EPERM;
		return -1;
	}
	swapz_primary_selected_target = parsed.target;
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	*manifest = parsed;
	return 0;
}

int swapz_primary_manifest_write_at(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest, uid_t expected_owner)
{
	struct stat directory_info;
	struct stat temporary_info;
	struct stat named_info;
	struct stat named_temporary_info;
	struct swapz_primary_manifest verified_manifest;
	char name[96];
	char temporary[128];
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char verified[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t record_length;
	size_t verified_length;
	size_t written = 0;
	int fd = -1;
	int temporary_identity_valid = 0;
	int saved_errno = 0;
	int length;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_manifest_valid(manifest) ||
	    swapz_primary_manifest_name(manifest->run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	swapz_primary_selected_target = manifest->target;
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, manifest->run_id,
						 expected_owner))
		return -1;
	length = swapz_primary_manifest_format(manifest, record,
					       sizeof(record));
	if (length < 0)
		return -1;
	record_length = (size_t)length;
	if (fstat(recovery_fd, &directory_info) < 0)
		return -1;
	if (!S_ISDIR(directory_info.st_mode) ||
	    directory_info.st_uid != expected_owner ||
	    (directory_info.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	length = snprintf(temporary, sizeof(temporary), ".%s.%s.tmp", name,
			  manifest->run_id);
	if (length < 0 || (size_t)length >= sizeof(temporary)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, name, &named_info, AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	fd = openat(recovery_fd, temporary,
		    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &temporary_info) < 0)
		goto failed;
	if (!S_ISREG(temporary_info.st_mode) ||
	    temporary_info.st_uid != expected_owner ||
	    (temporary_info.st_mode & 0777U) != 0600U ||
	    temporary_info.st_nlink != 1) {
		errno = EPERM;
		goto failed;
	}
	temporary_identity_valid = 1;
	while (written < record_length) {
		ssize_t count = write(fd, record + written, record_length - written);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		written += (size_t)count;
	}
	if (fsync(fd) < 0 || fstat(fd, &named_info) < 0 ||
	    fstatat(recovery_fd, temporary, &named_temporary_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (named_info.st_dev != temporary_info.st_dev ||
	    named_info.st_ino != temporary_info.st_ino ||
	    named_info.st_size != (off_t)record_length ||
	    !S_ISREG(named_info.st_mode) || named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U || named_info.st_nlink != 1 ||
	    named_temporary_info.st_dev != temporary_info.st_dev ||
	    named_temporary_info.st_ino != temporary_info.st_ino) {
		errno = EPERM;
		goto failed;
	}
	if (close(fd) < 0) {
		saved_errno = errno;
		fd = -1;
		errno = saved_errno;
		goto failed;
	}
	fd = -1;
	if (renameat2(recovery_fd, temporary, recovery_fd, name,
		      RENAME_NOREPLACE) < 0)
		goto failed;
	if (fsync(recovery_fd) < 0 ||
	    swapz_primary_record_read_at(recovery_fd, name, expected_owner,
					 verified, sizeof(verified),
					 &verified_length, NULL) < 0)
		return -1;
	if (verified_length != record_length ||
	    swapz_primary_manifest_parse(verified, verified_length,
					 &verified_manifest) < 0 ||
	    memcmp(record, verified, verified_length) ||
	    memcmp(manifest, &verified_manifest, sizeof(*manifest))) {
		errno = EBADMSG;
		return -1;
	}
	return 0;

failed:
	if (!saved_errno)
		saved_errno = errno;
	if (temporary_identity_valid &&
	    fstatat(recovery_fd, temporary, &named_info,
		    AT_SYMLINK_NOFOLLOW) == 0 &&
	    named_info.st_dev == temporary_info.st_dev &&
	    named_info.st_ino == temporary_info.st_ino) {
		(void)unlinkat(recovery_fd, temporary, 0);
		(void)fsync(recovery_fd);
	}
	if (fd >= 0)
		(void)close(fd);
	errno = saved_errno;
	return -1;
}

int swapz_primary_state_write_at(int recovery_fd, int lock_fd,
				 const struct swapz_primary_state *next,
				 uid_t expected_owner)
{
	struct swapz_primary_state current;
	char current_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char next_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t current_length;
	int length;

	if (!swapz_primary_state_valid(next) ||
	    !swapz_primary_target_valid(&swapz_primary_selected_target)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner))
		return -1;
	if (!swapz_primary_owner_claim_matches_at(recovery_fd, next->run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, current_record,
					 sizeof(current_record), &current_length,
					 NULL) == 0) {
		if (swapz_primary_state_parse(current_record, current_length,
					      &current) < 0 ||
		    !swapz_primary_state_transition_allowed(&current, next)) {
			errno = EPERM;
			return -1;
		}
	} else if (errno != ENOENT ||
		   next->stage != SWAPZ_PRIMARY_STAGE_READY ||
		   next->has_recovery_previous_stage) {
		return -1;
	}
	length = swapz_primary_state_format(next, next_record,
					   sizeof(next_record));
	if (length < 0)
		return -1;
	if (swapz_primary_reconcile_state_temporary_at(
		    recovery_fd, lock_fd, next->run_id, expected_owner) < 0)
		return -1;
	if (swapz_primary_replace_record_at(recovery_fd, "primary-state.json",
					   next->run_id, next_record,
					   expected_owner) < 0)
		return -1;
	return 0;
}

int swapz_primary_state_require_recovery_at(
	int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner)
{
	struct swapz_primary_state current;
	struct swapz_primary_state recovery_required;
	char current_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t current_length;

	if (!swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(
		    recovery_fd, run_id, expected_owner))
		return -1;
	if (swapz_primary_record_read_at(
		    recovery_fd, "primary-state.json", expected_owner,
		    current_record, sizeof(current_record), &current_length,
		    NULL) < 0 ||
	    swapz_primary_state_parse(
		    current_record, current_length, &current) < 0 ||
	    strcmp(current.run_id, run_id)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_recovery_required_state(
		    &current, &recovery_required) < 0)
		return -1;
	return swapz_primary_state_write_at(
		recovery_fd, lock_fd, &recovery_required, expected_owner);
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_require_recovery_preserving_errno(
	int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner,
	const char *operation, int original_errno)
{
	const int primary_errno = original_errno ? original_errno : EIO;

	if (swapz_primary_state_require_recovery_at(
		    recovery_fd, lock_fd, run_id, expected_owner) < 0) {
		const int recovery_errno = errno ? errno : EIO;

		fprintf(stderr,
			"PRIMARY_%s=RECOVERY_STATE_FAILED "
			"phase=recovery-state-persist "
			"check=durable-recovery-state "
			"expected_proof=RECOVERY_REQUIRED-persisted "
			"observed_proof=write-failed "
			"original_errno=%d recovery_errno=%d "
			"retained_resource=transaction-evidence "
			"disposition=BLOCKED "
			"safe_next_action=read-only-inspect-recovery-state "
			"persistence_boundary=state-file-fsync-close-rename-directory-fsync "
			"durable=UNCERTAIN mapper=UNCERTAIN swap=UNCERTAIN\n",
			operation, primary_errno, recovery_errno);
	}
	errno = primary_errno;
	return primary_errno;
}
#endif

int swapz_primary_release_partition_owner_at(int recovery_fd, int lock_fd,
						     const char *run_id,
						     uid_t expected_owner)
{
	struct swapz_primary_state state;
	struct stat active_info;
	struct stat named_info;
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char active_name[SWAPZ_PRIMARY_PARTITION_NAME_BYTES];
	size_t state_length;
	int marker_result;

	if (recovery_fd < 0 || lock_fd < 0 ||
	    !swapz_primary_valid_run_id(run_id)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner))
		return -1;
	if (!swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, "primary-state.json",
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 NULL) < 0)
		return -1;
	if (swapz_primary_state_parse(state_record, state_length, &state) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (state.stage != SWAPZ_PRIMARY_STAGE_COMPLETE ||
	    strcmp(state.run_id, run_id)) {
		errno = EPERM;
		return -1;
	}
	{
		int length = snprintf(active_name, sizeof(active_name),
				      "partition-%s.active",
				      SWAPZ_PRIMARY_PARTUUID);

		if (length < 0 || (size_t)length >= sizeof(active_name)) {
			errno = EOVERFLOW;
			return -1;
		}
	}
	if (swapz_primary_record_read_at(recovery_fd, active_name,
					 expected_owner, state_record,
					 sizeof(state_record), &state_length,
					 &active_info) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &named_info,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    named_info.st_dev != active_info.st_dev ||
	    named_info.st_ino != active_info.st_ino ||
	    !S_ISREG(named_info.st_mode) || named_info.st_nlink != 1) {
		errno = EPERM;
		return -1;
	}
	marker_result = unlinkat(recovery_fd, active_name, 0);
	if (marker_result < 0)
		return -1;
	if (fsync(recovery_fd) < 0)
		return -1;
	if (fstatat(recovery_fd, active_name, &named_info,
		    AT_SYMLINK_NOFOLLOW) == 0 || errno != ENOENT) {
		errno = EIO;
		return -1;
	}
	return 0;
}

int swapz_primary_partition_lock_acquire(const char *partuuid)
{
	uid_t expected_owner = 0;
	struct swapz_primary_target target;
	int recovery_fd;
	int lock_fd;
	int saved_errno;

	swapz_primary_selected_target_clear();
	if (geteuid() != expected_owner) {
		errno = EPERM;
		return -1;
	}
	if (!swapz_primary_partuuid_valid(partuuid)) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_target_inspect(partuuid, &target) < 0)
		return -1;
	swapz_primary_selected_target = target;
	recovery_fd = swapz_primary_runtime_state_base_open(expected_owner);
	if (recovery_fd < 0)
		return -1;
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, SWAPZ_PRIMARY_PARTUUID, expected_owner);
	saved_errno = errno;
	close(recovery_fd);
	errno = saved_errno;
	return lock_fd;
}

static int swapz_primary_page_limit_fits(uint64_t physical_blocks,
					uint64_t logical_pages)
{
	if (!logical_pages || logical_pages > UINT32_MAX ||
	    physical_blocks > UINT32_MAX ||
	    logical_pages > (uint64_t)SIZE_MAX / sizeof(struct swapz_map) ||
	    physical_blocks > (uint64_t)SIZE_MAX / sizeof(swapz_u16) ||
	    physical_blocks < 3ULL * SWAPZ_PRIMARY_SEGMENT_BLOCKS ||
	    physical_blocks % SWAPZ_PRIMARY_SEGMENT_BLOCKS)
		return 0;
	return swapz_authority_capacity_window(
		(swapz_u32)logical_pages, (swapz_u32)physical_blocks, NULL);
}

static uint64_t swapz_primary_maximum_logical_pages(uint64_t physical_blocks)
{
	uint64_t low = 0;
	uint64_t high = physical_blocks;

	while (low < high) {
		uint64_t candidate = low + (high - low + 1ULL) / 2ULL;

		if (swapz_primary_page_limit_fits(physical_blocks, candidate))
			low = candidate;
		else
			high = candidate - 1ULL;
	}
	return low;
}

/*
 * /proc/swaps reports Linux's usable swap pages. For a block-device
 * SWAPSPACE2 area that is the header-declared data pages minus listed bad
 * pages, not the raw partition size and not swapz's clean-segment capacity.
 */
static uint64_t swapz_primary_swap_size_kib_from_header(
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	uint64_t device_bytes)
{
	struct swapz_linux_swap_layout layout;
	uint64_t usable_pages;

	if (!header ||
	    !swapz_linux_swap_header_parse(header, device_bytes, &layout) ||
	    layout.bad_pages > layout.last_page)
		return 0;
	usable_pages = (uint64_t)layout.last_page - layout.bad_pages;
	if (usable_pages > UINT64_MAX /
			(SWAPZ_PRIMARY_BLOCK_BYTES / 1024ULL))
		return 0;
	return usable_pages * (SWAPZ_PRIMARY_BLOCK_BYTES / 1024ULL);
}

static uint64_t swapz_primary_linux_swap_size_kib(uint64_t logical_pages)
{
	uint64_t logical_bytes;

	if (!logical_pages ||
	    logical_pages > UINT64_MAX / SWAPZ_PRIMARY_BLOCK_BYTES)
		return 0;
	logical_bytes = logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES;
	return logical_bytes / 1024ULL - SWAPZ_PRIMARY_BLOCK_BYTES / 1024ULL;
}

struct swapz_primary_json_cursor {
	const unsigned char *cursor;
	const unsigned char *end;
	size_t nodes;
};

#define SWAPZ_PRIMARY_JSON_MAX_NODES 4000000U
#define SWAPZ_PRIMARY_JSON_MAX_DEPTH 32U

static void swapz_primary_json_space(struct swapz_primary_json_cursor *json)
{
	while (json->cursor < json->end &&
	       (*json->cursor == ' ' || *json->cursor == '\t' ||
		*json->cursor == '\r' || *json->cursor == '\n'))
		++json->cursor;
}

/* A delimiter must be followed by another member, never a closing token. */
static int swapz_primary_json_comma(
	struct swapz_primary_json_cursor *json, unsigned char closing_token)
{
	if (json->cursor >= json->end || *json->cursor++ != ',')
		return -1;
	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor == closing_token)
		return -1;
	return 0;
}

static int swapz_primary_json_string_span(
	struct swapz_primary_json_cursor *json,
	const unsigned char **value, size_t *length, int allow_escapes)
{
	const unsigned char *start;

	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor++ != '"')
		return -1;
	start = json->cursor;
	while (json->cursor < json->end) {
		unsigned char byte = *json->cursor++;

		if (byte == '"') {
			*value = start;
			*length = (size_t)(json->cursor - start - 1U);
			return 0;
		}
		if (byte < 0x20U)
			return -1;
		if (byte != '\\')
			continue;
		if (!allow_escapes || json->cursor >= json->end)
			return -1;
		byte = *json->cursor++;
		if (byte == '"' || byte == '\\' || byte == '/' || byte == 'b' ||
		    byte == 'f' || byte == 'n' || byte == 'r' || byte == 't')
			continue;
		if (byte == 'u') {
			unsigned int digit;

			for (digit = 0; digit < 4U; ++digit) {
				if (json->cursor >= json->end ||
				    !isxdigit((unsigned char)*json->cursor++))
					return -1;
			}
			continue;
		}
		return -1;
	}
	return -1;
}

static int swapz_primary_json_number(struct swapz_primary_json_cursor *json,
					     const unsigned char **number,
					     size_t *length)
{
	const unsigned char *start;

	swapz_primary_json_space(json);
	start = json->cursor;
	if (json->cursor < json->end && *json->cursor == '-')
		++json->cursor;
	if (json->cursor >= json->end)
		return -1;
	if (*json->cursor == '0') {
		++json->cursor;
		if (json->cursor < json->end && isdigit(*json->cursor))
			return -1;
	} else {
		if (*json->cursor < '1' || *json->cursor > '9')
			return -1;
		while (json->cursor < json->end && isdigit(*json->cursor))
			++json->cursor;
	}
	if (json->cursor < json->end && *json->cursor == '.') {
		++json->cursor;
		if (json->cursor >= json->end || !isdigit(*json->cursor))
			return -1;
		while (json->cursor < json->end && isdigit(*json->cursor))
			++json->cursor;
	}
	if (json->cursor < json->end &&
	    (*json->cursor == 'e' || *json->cursor == 'E')) {
		++json->cursor;
		if (json->cursor < json->end &&
		    (*json->cursor == '+' || *json->cursor == '-'))
			++json->cursor;
		if (json->cursor >= json->end || !isdigit(*json->cursor))
			return -1;
		while (json->cursor < json->end && isdigit(*json->cursor))
			++json->cursor;
	}
	*number = start;
	*length = (size_t)(json->cursor - start);
	return 0;
}

static int swapz_primary_json_skip_value(
	struct swapz_primary_json_cursor *json, unsigned int depth)
{
	swapz_primary_json_space(json);
	if (depth > SWAPZ_PRIMARY_JSON_MAX_DEPTH ||
	    ++json->nodes > SWAPZ_PRIMARY_JSON_MAX_NODES ||
	    json->cursor >= json->end)
		return -1;
	if (*json->cursor == '"') {
		const unsigned char *value;
		size_t length;

		return swapz_primary_json_string_span(json, &value, &length, 1);
	}
	if (*json->cursor == '{' || *json->cursor == '[') {
		unsigned char close = *json->cursor == '{' ? '}' : ']';
		int object = *json->cursor++ == '{';

		swapz_primary_json_space(json);
		if (json->cursor < json->end && *json->cursor == close) {
			++json->cursor;
			return 0;
		}
		for (;;) {
			if (object) {
				const unsigned char *key;
				size_t key_length;

				if (swapz_primary_json_string_span(
					    json, &key, &key_length, 0) < 0)
					return -1;
				swapz_primary_json_space(json);
				if (json->cursor >= json->end ||
				    *json->cursor++ != ':')
					return -1;
			}
			if (swapz_primary_json_skip_value(json, depth + 1U) < 0)
				return -1;
			swapz_primary_json_space(json);
			if (json->cursor >= json->end)
				return -1;
			if (*json->cursor == close) {
				++json->cursor;
				return 0;
			}
			if (swapz_primary_json_comma(json, close) < 0)
				return -1;
			swapz_primary_json_space(json);
		}
	}
	if ((size_t)(json->end - json->cursor) >= 4U &&
	    !memcmp(json->cursor, "true", 4U)) {
		json->cursor += 4U;
		return 0;
	}
	if ((size_t)(json->end - json->cursor) >= 5U &&
	    !memcmp(json->cursor, "false", 5U)) {
		json->cursor += 5U;
		return 0;
	}
	if ((size_t)(json->end - json->cursor) >= 4U &&
	    !memcmp(json->cursor, "null", 4U)) {
		json->cursor += 4U;
		return 0;
	}
	{
		const unsigned char *number;
		size_t length;

		return swapz_primary_json_number(json, &number, &length);
	}
}

static int swapz_primary_json_key_is(const unsigned char *key,
				     size_t key_length, const char *expected)
{
	return key_length == strlen(expected) &&
	       !memcmp(key, expected, key_length);
}

static int swapz_primary_json_plain_string(
	struct swapz_primary_json_cursor *json, char *value, size_t capacity)
{
	const unsigned char *span;
	size_t length;

	if (!capacity || swapz_primary_json_string_span(
		json, &span, &length, 0) < 0 || length >= capacity)
		return -1;
	memcpy(value, span, length);
	value[length] = '\0';
	return 0;
}

static int swapz_primary_json_zero(struct swapz_primary_json_cursor *json)
{
	const unsigned char *number;
	size_t length;

	return swapz_primary_json_number(json, &number, &length) == 0 &&
	       length == 1U && number[0] == '0';
}

static int swapz_primary_qualification_host_parse(
	struct swapz_primary_json_cursor *json,
	struct swapz_primary_qualification *qualification)
{
	unsigned int seen = 0;
	char schema[32];
	char architecture[32];
	const unsigned char *key;
	size_t key_length;

	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor++ != '{')
		return -1;
	for (;;) {
		swapz_primary_json_space(json);
		if (json->cursor < json->end && *json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_string_span(json, &key, &key_length, 0) < 0)
			return -1;
		swapz_primary_json_space(json);
		if (json->cursor >= json->end || *json->cursor++ != ':')
			return -1;
		if (swapz_primary_json_key_is(key, key_length, "schema")) {
			if (seen & 1U || swapz_primary_json_plain_string(
				    json, schema, sizeof(schema)) < 0)
				return -1;
			seen |= 1U;
		} else if (swapz_primary_json_key_is(key, key_length,
						     "architecture")) {
			if (seen & 2U || swapz_primary_json_plain_string(
				    json, architecture, sizeof(architecture)) < 0)
				return -1;
			seen |= 2U;
		} else if (swapz_primary_json_key_is(key, key_length,
						     "id_sha256")) {
			if (seen & 4U || swapz_primary_json_plain_string(
				    json, qualification->host_identity_sha256,
				    sizeof(qualification->host_identity_sha256)) < 0)
				return -1;
			seen |= 4U;
		} else if (swapz_primary_json_skip_value(json, 1U) < 0) {
			return -1;
		}
		swapz_primary_json_space(json);
		if (json->cursor >= json->end)
			return -1;
		if (*json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_comma(json, '}') < 0)
			return -1;
	}
	if (seen != 7U || strcmp(schema, "swapz-host-v1") ||
	    !swapz_primary_valid_sha256(
		    qualification->host_identity_sha256))
		return -1;
	if (!strcmp(architecture, "x86_64"))
		return 0;
#ifdef SWAPZ_PRIMARY_OWNED_NULLBLK_TEST
	/* An ARM64 report is accepted only by the private RAM rehearsal. */
	if (!strcmp(architecture, "aarch64"))
		return 0;
#endif
	return -1;
}

static int swapz_primary_qualification_stage_parse(
	struct swapz_primary_json_cursor *json, unsigned int stage_index)
{
	static const char *const expected_names[] = {
		"Build module and helpers",
		"Native and rootless contracts",
		"Kernel warnings W=1",
		"Kernel warnings W=2",
		"Owned RAM smoke + mixed/QD pilot",
	};
	unsigned int seen = 0;
	char name[96];
	char status[16];
	const unsigned char *key;
	size_t key_length;

	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor++ != '{')
		return -1;
	for (;;) {
		swapz_primary_json_space(json);
		if (json->cursor < json->end && *json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_string_span(json, &key, &key_length, 0) < 0)
			return -1;
		swapz_primary_json_space(json);
		if (json->cursor >= json->end || *json->cursor++ != ':')
			return -1;
		if (swapz_primary_json_key_is(key, key_length, "name")) {
			if (seen & 1U || swapz_primary_json_plain_string(
				    json, name, sizeof(name)) < 0)
				return -1;
			seen |= 1U;
		} else if (swapz_primary_json_key_is(key, key_length, "status")) {
			if (seen & 2U || swapz_primary_json_plain_string(
				    json, status, sizeof(status)) < 0)
				return -1;
			seen |= 2U;
		} else if (swapz_primary_json_key_is(key, key_length,
						     "exit_code")) {
			if (seen & 4U || !swapz_primary_json_zero(json))
				return -1;
			seen |= 4U;
		} else if (swapz_primary_json_skip_value(json, 1U) < 0) {
			return -1;
		}
		swapz_primary_json_space(json);
		if (json->cursor >= json->end)
			return -1;
		if (*json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_comma(json, '}') < 0)
			return -1;
	}
	if (seen == 7U && stage_index < 5U &&
	    !strcmp(name, expected_names[stage_index]) &&
	    !strcmp(status, "PASS"))
		return 0;
	return -1;
}

static int swapz_primary_qualification_stages_parse(
	struct swapz_primary_json_cursor *json)
{
	unsigned int count = 0;

	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor++ != '[')
		return -1;
	for (;;) {
		swapz_primary_json_space(json);
		if (json->cursor < json->end && *json->cursor == ']') {
			++json->cursor;
			break;
		}
		if (count >= 5U ||
		    swapz_primary_qualification_stage_parse(json, count) < 0)
			return -1;
		++count;
		swapz_primary_json_space(json);
		if (json->cursor >= json->end)
			return -1;
		if (*json->cursor == ']') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_comma(json, ']') < 0)
			return -1;
	}
	return count == 5U ? 0 : -1;
}

static int swapz_primary_qualification_artifacts_parse(
	struct swapz_primary_json_cursor *json,
	struct swapz_primary_qualification *qualification)
{
	unsigned int seen = 0;
	char status[24];
	const unsigned char *key;
	size_t key_length;

	swapz_primary_json_space(json);
	if (json->cursor >= json->end || *json->cursor++ != '{')
		return -1;
	for (;;) {
		swapz_primary_json_space(json);
		if (json->cursor < json->end && *json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_string_span(json, &key, &key_length, 0) < 0)
			return -1;
		swapz_primary_json_space(json);
		if (json->cursor >= json->end || *json->cursor++ != ':')
			return -1;
		if (swapz_primary_json_key_is(key, key_length, "status")) {
			if (seen & 1U || swapz_primary_json_plain_string(
				    json, status, sizeof(status)) < 0)
				return -1;
			seen |= 1U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "formatter_sha256")) {
			if (seen & 2U || swapz_primary_json_plain_string(
				    json, qualification->formatter_sha256,
				    sizeof(qualification->formatter_sha256)) < 0)
				return -1;
			seen |= 2U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "module_sha256")) {
			if (seen & 4U || swapz_primary_json_plain_string(
				    json, qualification->module_sha256,
				    sizeof(qualification->module_sha256)) < 0)
				return -1;
			seen |= 4U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "oracle_sha256")) {
			if (seen & 8U || swapz_primary_json_plain_string(
				    json, qualification->oracle_sha256,
				    sizeof(qualification->oracle_sha256)) < 0)
				return -1;
			seen |= 8U;
		} else if (swapz_primary_json_skip_value(json, 1U) < 0) {
			return -1;
		}
		swapz_primary_json_space(json);
		if (json->cursor >= json->end)
			return -1;
		if (*json->cursor == '}') {
			++json->cursor;
			break;
		}
		if (swapz_primary_json_comma(json, '}') < 0)
			return -1;
	}
	if (seen == 15U && !strcmp(status, "AVAILABLE") &&
	    swapz_primary_valid_sha256(qualification->formatter_sha256) &&
	    swapz_primary_valid_sha256(qualification->module_sha256) &&
	    swapz_primary_valid_sha256(qualification->oracle_sha256))
		return 0;
	return -1;
}

int swapz_primary_qualification_parse_json(
	const unsigned char *bytes, size_t length, const char *expected_source_sha,
	const char *expected_host_identity_sha256,
	struct swapz_primary_qualification *qualification)
{
	struct swapz_primary_qualification parsed = {0};
	struct swapz_primary_json_cursor json = {0};
	unsigned int seen = 0;
	char schema[40];
	char tested_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 1U];
	char overall[16];
	char qualification_kind[48];
	const unsigned char *key;
	size_t key_length;

	if (!bytes || !length || length > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES ||
	    !qualification ||
	    !swapz_primary_valid_source_sha(expected_source_sha) ||
	    !swapz_primary_valid_sha256(expected_host_identity_sha256)) {
		errno = EINVAL;
		return -1;
	}
	json.cursor = bytes;
	json.end = bytes + length;
	swapz_primary_json_space(&json);
	if (json.cursor >= json.end || *json.cursor++ != '{')
		goto invalid;
	for (;;) {
		swapz_primary_json_space(&json);
		if (json.cursor < json.end && *json.cursor == '}') {
			++json.cursor;
			break;
		}
		if (swapz_primary_json_string_span(&json, &key, &key_length, 0) < 0)
			goto invalid;
		swapz_primary_json_space(&json);
		if (json.cursor >= json.end || *json.cursor++ != ':')
			goto invalid;
		if (swapz_primary_json_key_is(key, key_length, "schema")) {
			if (seen & 1U || swapz_primary_json_plain_string(
				    &json, schema, sizeof(schema)) < 0)
				goto invalid;
			seen |= 1U;
		} else if (swapz_primary_json_key_is(key, key_length,
						     "source_sha")) {
			if (seen & 2U || swapz_primary_json_plain_string(
				    &json, parsed.source_sha,
				    sizeof(parsed.source_sha)) < 0)
				goto invalid;
			seen |= 2U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "tested_commit_sha")) {
			if (seen & 4U || swapz_primary_json_plain_string(
				    &json, tested_source_sha,
				    sizeof(tested_source_sha)) < 0)
				goto invalid;
			seen |= 4U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "kernel_release")) {
			if (seen & 256U || swapz_primary_json_plain_string(
				    &json, parsed.kernel_release,
				    sizeof(parsed.kernel_release)) < 0)
				goto invalid;
			seen |= 256U;
		} else if (swapz_primary_json_key_is(key, key_length, "overall")) {
			if (seen & 8U || swapz_primary_json_plain_string(
				    &json, overall, sizeof(overall)) < 0)
				goto invalid;
			seen |= 8U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "qualification")) {
			if (seen & 16U || swapz_primary_json_plain_string(
				    &json, qualification_kind,
				    sizeof(qualification_kind)) < 0)
				goto invalid;
			seen |= 16U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "host_identity")) {
			if (seen & 32U ||
			    swapz_primary_qualification_host_parse(
				    &json, &parsed) < 0)
				goto invalid;
			seen |= 32U;
		} else if (swapz_primary_json_key_is(key, key_length, "stages")) {
			if (seen & 64U ||
			    swapz_primary_qualification_stages_parse(&json) < 0)
				goto invalid;
			seen |= 64U;
		} else if (swapz_primary_json_key_is(
				   key, key_length, "qualified_artifacts")) {
			if (seen & 128U ||
			    swapz_primary_qualification_artifacts_parse(
				    &json, &parsed) < 0)
				goto invalid;
			seen |= 128U;
		} else if (swapz_primary_json_skip_value(&json, 1U) < 0) {
			goto invalid;
		}
		swapz_primary_json_space(&json);
		if (json.cursor >= json.end)
			goto invalid;
		if (*json.cursor == '}') {
			++json.cursor;
			break;
		}
		if (swapz_primary_json_comma(&json, '}') < 0)
			goto invalid;
	}
	swapz_primary_json_space(&json);
	if (json.cursor != json.end || seen != 511U ||
	    strcmp(schema, "swapz-test-results-v1") ||
	    !swapz_primary_valid_kernel_release(parsed.kernel_release) ||
	    strcmp(parsed.source_sha, expected_source_sha) ||
	    strcmp(tested_source_sha, expected_source_sha) ||
	    strcmp(overall, "PASS") ||
	    strcmp(qualification_kind, "RAM_BACKED_NULL_BLK_ONLY") ||
	    strcmp(parsed.host_identity_sha256,
		   expected_host_identity_sha256) ||
	    swapz_primary_sha256(bytes, length, parsed.report_sha256) < 0)
		goto invalid;
	*qualification = parsed;
	return 0;

invalid:
	errno = EINVAL;
	return -1;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_running_kernel_matches_qualification(
	const struct swapz_primary_qualification *qualification)
{
	struct utsname system;

	if (!qualification ||
	    !swapz_primary_valid_kernel_release(qualification->kernel_release)) {
		errno = EINVAL;
		return -1;
	}
	if (uname(&system) < 0)
		return -1;
	#if defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__)
	if (strcmp(system.sysname, "Linux") || strcmp(system.machine, "aarch64")) {
		errno = ENOTSUP;
		return -1;
	}
#else
	if (strcmp(system.sysname, "Linux") || strcmp(system.machine, "x86_64")) {
		errno = ENOTSUP;
		return -1;
	}
#endif
	if (!swapz_primary_valid_kernel_release(system.release) ||
	    strcmp(system.release, qualification->kernel_release)) {
		errno = ESTALE;
		return -1;
	}
	return 0;
}
#endif


/*
 * Bind hardware as well as OS identity: the bootable root disk can move to a
 * different computer with its /etc/machine-id intact.
 */
static int swapz_primary_live_host_identity_sha256(char digest[65])
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)digest;
	errno = ENODEV;
	return -1;
#else
#if defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__)
	/* RAM-only private rehearsal: machine identity, never hardware identity. */
	static const unsigned char prefix[] = "swapz-nullblk-arm64-v1";
	static const char required_architecture[] = "aarch64";
	unsigned char identity[sizeof(prefix) + 32U];
#else
	static const unsigned char prefix[] = "swapz-host-v2";
	static const char required_architecture[] = "x86_64";
	unsigned char identity[sizeof(prefix) + 36U + 32U];
#endif
	char machine_id[64];
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	char product_uuid_record[40];
	char product_uuid[37];
#endif
	struct stat before;
	struct stat after;
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	struct stat dmi_before;
	struct stat dmi_after;
#endif
	struct utsname system;
	size_t length = 0;
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	size_t dmi_length = 0;
#endif
	size_t i;
	int machine_id_nonzero = 0;
	int fd = -1;
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	int dmi_fd = -1;
#endif
	int result;
	int saved_errno;

	if (!digest) {
		errno = EINVAL;
		return -1;
	}
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	dmi_fd = open("/sys/class/dmi/id/product_uuid",
		      O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
	if (dmi_fd < 0)
		return -1;
	if (fstat(dmi_fd, &dmi_before) < 0) {
		saved_errno = errno;
		(void)close(dmi_fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(dmi_before.st_mode) || dmi_before.st_uid != 0 ||
	    dmi_before.st_nlink != 1U || (dmi_before.st_mode & 0022U)) {
		(void)close(dmi_fd);
		errno = EPERM;
		return -1;
	}
	while (dmi_length < sizeof(product_uuid_record)) {
		ssize_t count = read(dmi_fd, product_uuid_record + dmi_length,
				     sizeof(product_uuid_record) - dmi_length);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			saved_errno = errno;
			(void)close(dmi_fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		dmi_length += (size_t)count;
	}
	if (dmi_length == sizeof(product_uuid_record)) {
		(void)close(dmi_fd);
		errno = EOVERFLOW;
		return -1;
	}
	if (fstat(dmi_fd, &dmi_after) < 0) {
		saved_errno = errno;
		(void)close(dmi_fd);
		errno = saved_errno;
		return -1;
	}
	if (close(dmi_fd) < 0)
		return -1;
	if (dmi_before.st_dev != dmi_after.st_dev ||
	    dmi_before.st_ino != dmi_after.st_ino ||
	    dmi_before.st_mode != dmi_after.st_mode ||
	    dmi_before.st_uid != dmi_after.st_uid ||
	    dmi_before.st_gid != dmi_after.st_gid ||
	    dmi_before.st_nlink != dmi_after.st_nlink ||
	    dmi_before.st_size != dmi_after.st_size ||
	    dmi_before.st_mtim.tv_sec != dmi_after.st_mtim.tv_sec ||
	    dmi_before.st_mtim.tv_nsec != dmi_after.st_mtim.tv_nsec ||
	    dmi_before.st_ctim.tv_sec != dmi_after.st_ctim.tv_sec ||
	    dmi_before.st_ctim.tv_nsec != dmi_after.st_ctim.tv_nsec ||
	    (dmi_length == 37U && product_uuid_record[36] != '\n') ||
	    (dmi_length != 36U && dmi_length != 37U)) {
		errno = ESTALE;
		return -1;
	}
	if (dmi_length == 37U)
		--dmi_length;
	if (swapz_primary_host_uuid_normalize(
		    product_uuid_record, dmi_length, product_uuid) < 0)
		return -1;
#endif
	fd = open("/etc/machine-id", O_RDONLY | O_CLOEXEC | O_NOFOLLOW |
		  O_NONBLOCK);
	if (fd < 0)
		return -1;
	if (fstat(fd, &before) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISREG(before.st_mode) || before.st_uid != 0 ||
	    before.st_nlink != 1U || (before.st_mode & 0022U)) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	while (length < sizeof(machine_id)) {
		ssize_t count = read(fd, machine_id + length,
				    sizeof(machine_id) - length);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		length += (size_t)count;
	}
	if (length == sizeof(machine_id)) {
		close(fd);
		errno = EOVERFLOW;
		return -1;
	}
	if (fstat(fd, &after) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_mode != after.st_mode || before.st_uid != after.st_uid ||
	    before.st_gid != after.st_gid || before.st_nlink != after.st_nlink ||
	    before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec) {
		errno = EIO;
		return -1;
	}
	if (uname(&system) < 0 || strcmp(system.sysname, "Linux") ||
	    strcmp(system.machine, required_architecture)) {
		errno = ENOTSUP;
		return -1;
	}
	if (length == 33U && machine_id[32] == '\n')
		length = 32U;
	if (length != 32U) {
		errno = EINVAL;
		return -1;
	}
	memcpy(identity, prefix, sizeof(prefix));
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	memcpy(identity + sizeof(prefix), product_uuid, 36U);
#endif
	for (i = 0; i < 32U; ++i) {
		unsigned char byte = (unsigned char)machine_id[i];

		if (!isxdigit(byte)) {
			errno = EINVAL;
			return -1;
		}
		if (byte != '0')
			machine_id_nonzero = 1;
#if defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__)
		identity[sizeof(prefix) + i] =
			(unsigned char)tolower(byte);
#else
		identity[sizeof(prefix) + 36U + i] =
			(unsigned char)tolower(byte);
#endif
	}
	if (!machine_id_nonzero) {
		errno = EINVAL;
		return -1;
	}
	result = swapz_primary_sha256(identity, sizeof(identity), digest);
	saved_errno = errno;
	memset(identity, 0, sizeof(identity));
	memset(machine_id, 0, sizeof(machine_id));
#if !(defined(SWAPZ_PRIMARY_OWNED_NULLBLK_TEST) && defined(__aarch64__))
	memset(product_uuid_record, 0, sizeof(product_uuid_record));
	memset(product_uuid, 0, sizeof(product_uuid));
#endif
	errno = saved_errno;
	return result;
#endif
}

static inline int swapz_primary_sysfs_entry_is_directory(const char *path)
{
	struct stat info;

	if (!path || !path[0]) {
		errno = EINVAL;
		return -1;
	}
	if (lstat(path, &info) < 0)
		return -1;
	return S_ISDIR(info.st_mode);
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_udev_scope_properties_read(
	dev_t device, int partition,
	struct swapz_primary_udev_scope_properties *properties)
{
	struct stat before;
	struct stat after;
	char path[128];
	char record[16384];
	size_t used = 0;
	int fd = -1;
	unsigned int seen = 0U;
	int length;
	int result = -1;
	int saved_errno = 0;

	if (!device || !properties) {
		errno = EINVAL;
		return -1;
	}
	memset(properties, 0, sizeof(*properties));
	length = snprintf(path, sizeof(path), "/run/udev/data/b%u:%u",
			  major(device), minor(device));
	if (length <= 0 || (size_t)length >= sizeof(path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		return -1;
	if (fstat(fd, &before) < 0)
		goto out;
	if (!S_ISREG(before.st_mode) || before.st_uid != 0 ||
	    (before.st_mode & 0022U) || before.st_nlink != 1U ||
	    before.st_size <= 0 ||
	    (uint64_t)before.st_size >= sizeof(record)) {
		errno = EPERM;
		goto out;
	}
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0)
			goto out;
		if (!count)
			break;
		used += (size_t)count;
	}
	if (used == sizeof(record)) {
		errno = EOVERFLOW;
		goto out;
	}
	if (fstat(fd, &after) < 0)
		goto out;
	if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_uid != after.st_uid || before.st_gid != after.st_gid ||
	    before.st_mode != after.st_mode ||
	    before.st_nlink != after.st_nlink || before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec ||
	    used != (size_t)before.st_size || memchr(record, '\0', used)) {
		errno = ESTALE;
		goto out;
	}
	{
		const char *cursor = record;
		const char *end = record + used;

		while (cursor < end) {
			const char *line_end = memchr(cursor, '\n',
						       (size_t)(end - cursor));
			size_t line_length = line_end ?
				(size_t)(line_end - cursor) :
				(size_t)(end - cursor);
			const char *equals;
			size_t key_length;
			const char *value;
			size_t value_length;
			char *destination = NULL;
			size_t capacity = 0U;
			unsigned int bit = 0U;

			if (line_length < 3U || cursor[0] != 'E' ||
			    cursor[1] != ':' || !(equals = memchr(cursor + 2U, '=',
							    line_length - 2U)))
				goto next_line;
			key_length = (size_t)(equals - (cursor + 2U));
			value = equals + 1;
			value_length = line_length - (size_t)(value - cursor);
#define SWAPZ_UDEV_PROPERTY(name, field, flag) \
			if (key_length == sizeof(name) - 1U && \
			    !memcmp(cursor + 2U, name, key_length)) { \
				destination = properties->field; \
				capacity = sizeof(properties->field); \
				bit = flag; \
			}
			SWAPZ_UDEV_PROPERTY("ID_SERIAL", serial, 1U)
			else SWAPZ_UDEV_PROPERTY("ID_WWN", wwn, 2U)
			else SWAPZ_UDEV_PROPERTY("ID_VENDOR", vendor, 4U)
			else SWAPZ_UDEV_PROPERTY("ID_MODEL", model, 8U)
			else SWAPZ_UDEV_PROPERTY("ID_TYPE", device_type, 16U)
			else SWAPZ_UDEV_PROPERTY("ID_PART_TABLE_UUID", table_uuid, 32U)
			else SWAPZ_UDEV_PROPERTY("ID_PART_TABLE_TYPE", table_type, 64U)
			else if (partition) {
				SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_SCHEME", entry_scheme, 128U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_UUID", entry_uuid, 256U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_TYPE", entry_type, 512U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_NUMBER", entry_number, 1024U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_OFFSET", entry_offset, 2048U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_SIZE", entry_size, 4096U)
				else SWAPZ_UDEV_PROPERTY("ID_PART_ENTRY_DISK", entry_disk, 8192U)
			}
#undef SWAPZ_UDEV_PROPERTY
			if (destination) {
				if ((seen & bit) || !value_length ||
				    value_length >= capacity) {
					errno = EBADMSG;
					goto out;
				}
				memcpy(destination, value, value_length);
				destination[value_length] = '\0';
				seen |= bit;
			}
next_line:
			if (!line_end)
				break;
			cursor = line_end + 1U;
		}
	}
	if (partition) {
		const unsigned int required = 32U | 64U | 128U | 256U | 512U |
				      1024U | 2048U | 4096U | 8192U;

		if ((seen & required) != required ||
		    (seen & 16U) == 0U || strcmp(properties->device_type, "disk")) {
			errno = ENODATA;
			goto out;
		}
	} else if (!(seen & 1U) && !(seen & 2U)) {
		errno = ENODATA;
		goto out;
	}
	result = 0;
out:
	saved_errno = errno;
	if (fd >= 0 && close(fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	memset(record, 0, sizeof(record));
	if (result < 0)
		memset(properties, 0, sizeof(*properties));
	errno = saved_errno;
	return result;
}

static int swapz_primary_read_partition_sysfs_partuuid(
	const char *sysfs_path,
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	char path[PATH_MAX];
	char record[4096];
	char observed[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U] = {0};
	size_t used = 0;
	int fd;

	if (!sysfs_path || !partuuid ||
	    swapz_primary_path_format(path, sizeof(path), "%s/uevent",
				      sysfs_path) < 0)
		return -1;
	fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return -1;
	while (used < sizeof(record)) {
		ssize_t count = read(fd, record + used, sizeof(record) - used);

		if (count < 0 && errno == EINTR)
			continue;
		if (count < 0) {
			int saved_errno = errno;

			(void)close(fd);
			errno = saved_errno;
			return -1;
		}
		if (!count)
			break;
		used += (size_t)count;
	}
	if (close(fd) < 0)
		return -1;
	if (used == sizeof(record) || memchr(record, '\0', used)) {
		errno = EOVERFLOW;
		return -1;
	}
	{
		const char *cursor = record;
		const char *end = record + used;
		unsigned int found = 0U;

		while (cursor < end) {
			const char *line_end = memchr(cursor, '\n',
						       (size_t)(end - cursor));
			size_t line_length = line_end ?
				(size_t)(line_end - cursor) :
				(size_t)(end - cursor);
			static const char prefix[] = "PARTUUID=";

			if (line_length >= sizeof(prefix) - 1U &&
			    !memcmp(cursor, prefix, sizeof(prefix) - 1U)) {
				size_t value_length = line_length -
					(sizeof(prefix) - 1U);

				if (found || !value_length ||
				    value_length > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
					errno = EBADMSG;
					return -1;
				}
				memcpy(observed, cursor + sizeof(prefix) - 1U,
				       value_length);
				observed[value_length] = '\0';
				found = 1U;
			}
			if (!line_end)
				break;
			cursor = line_end + 1U;
		}
		if (!found || swapz_primary_partuuid_normalize(
			      observed, partuuid) < 0)
			return -1;
	}
	return 0;
}

static int swapz_primary_read_partition_scope_path(
	const char *sysfs_path, struct swapz_primary_partition_scope *partition)
{
	char path[PATH_MAX];
	char text[64];
	char parent_path[PATH_MAX];
	char sysfs_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char normalized_entry_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	struct swapz_primary_udev_scope_properties properties = {0};
	dev_t device;
	dev_t parent_device;
	dev_t observed_parent_device;
	uint64_t partition_number;
	uint64_t observed_number;
	uint64_t observed_offset;
	uint64_t observed_size;

	if (!sysfs_path || !partition) {
		errno = EINVAL;
		return -1;
	}
	memset(partition, 0, sizeof(*partition));
	if (swapz_primary_path_format(path, sizeof(path), "%s/partition",
				      sysfs_path) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_u64(text, &partition_number) < 0 ||
	    !partition_number || partition_number > UINT32_MAX)
		return -1;
	partition->partition_number = (uint32_t)partition_number;
	if (swapz_primary_path_format(path, sizeof(path), "%s/start",
				      sysfs_path) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_u64(text, &partition->start_sectors) < 0 ||
	    swapz_primary_path_format(path, sizeof(path), "%s/size",
				      sysfs_path) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_u64(text, &partition->size_sectors) < 0 ||
	    swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      sysfs_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &device) < 0)
		return -1;
	partition->device_major = major(device);
	partition->device_minor = minor(device);
	if (swapz_primary_read_partition_sysfs_partuuid(
		    sysfs_path, sysfs_partuuid) < 0)
		return -1;
	if (partition->size_sectors > UINT64_MAX / 512ULL) {
		errno = EOVERFLOW;
		return -1;
	}
	partition->size_bytes = partition->size_sectors * 512ULL;
	if (swapz_primary_path_format(parent_path, sizeof(parent_path), "%s",
				      sysfs_path) < 0)
		return -1;
	{
		char *slash = strrchr(parent_path, '/');

		if (!slash || slash == parent_path) {
			errno = ENODEV;
			return -1;
		}
		*slash = '\0';
	}
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      parent_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &parent_device) < 0 ||
	    swapz_primary_udev_scope_properties_read(device, 1,
						     &properties) < 0 ||
	    swapz_primary_partuuid_normalize(
		    properties.entry_uuid, normalized_entry_uuid) < 0 ||
	    swapz_primary_parse_u64(properties.entry_number,
				     &observed_number) < 0 ||
	    swapz_primary_parse_u64(properties.entry_offset,
				     &observed_offset) < 0 ||
	    swapz_primary_parse_u64(properties.entry_size,
				     &observed_size) < 0) {
		memset(&properties, 0, sizeof(properties));
		return -1;
	}
	if (strcmp(properties.entry_scheme, properties.table_type) ||
	    strcmp(normalized_entry_uuid, sysfs_partuuid) ||
	    observed_number != partition->partition_number ||
	    observed_offset != partition->start_sectors ||
	    observed_size != partition->size_sectors ||
	    swapz_primary_parse_dev_number(properties.entry_disk,
				       &observed_parent_device) < 0 ||
	    parent_device != observed_parent_device) {
		errno = ESTALE;
		memset(&properties, 0, sizeof(properties));
		return -1;
	}
	memcpy(partition->partuuid, normalized_entry_uuid,
	       sizeof(partition->partuuid));
	if (partition->size_sectors > UINT64_MAX / 512ULL) {
		memset(&properties, 0, sizeof(properties));
		errno = EOVERFLOW;
		return -1;
	}
	partition->size_bytes = partition->size_sectors * 512ULL;
	strcpy(partition->parttype, properties.entry_type);
	strcpy(partition->partscheme, properties.entry_scheme);
	strcpy(partition->part_table_uuid, properties.table_uuid);
	strcpy(partition->part_table_type, properties.table_type);
	memset(&properties, 0, sizeof(properties));
	if (!swapz_primary_partition_scope_valid(partition)) {
		errno = EBADMSG;
		return -1;
	}
	return 0;
}

static int swapz_primary_partition_scope_device(
	dev_t expected_device, struct swapz_primary_partition_scope *partition,
	char sysfs_path[PATH_MAX], int verify_opened_device)
{
	char link_path[128];
	struct stat opened;
	uint64_t bytes = 0;
	int fd = -1;
	int length;
	int saved_errno;

	if (!expected_device || !partition || !sysfs_path) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(link_path, sizeof(link_path),
			  "/sys/dev/block/%u:%u", major(expected_device),
			  minor(expected_device));
	if (length <= 0 || (size_t)length >= sizeof(link_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (!realpath(link_path, sysfs_path))
		return -1;
	if (strncmp(sysfs_path, "/sys/devices/",
		    sizeof("/sys/devices/") - 1U)) {
		errno = EXDEV;
		return -1;
	}
	if (swapz_primary_read_partition_scope_path(sysfs_path, partition) < 0)
		return -1;
	if (makedev(partition->device_major, partition->device_minor) !=
	    expected_device) {
		errno = ESTALE;
		return -1;
	}
	if (!verify_opened_device)
		return 0;
	length = snprintf(link_path, sizeof(link_path), "/dev/block/%u:%u",
			  major(expected_device), minor(expected_device));
	if (length <= 0 || (size_t)length >= sizeof(link_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	fd = open(link_path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0) {
		saved_errno = errno;
		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISBLK(opened.st_mode) || opened.st_rdev != expected_device) {
		(void)close(fd);
		errno = ESTALE;
		return -1;
	}
	if (ioctl(fd, BLKGETSIZE64, &bytes) < 0) {
		saved_errno = errno;
		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
	if (bytes != partition->size_bytes) {
		(void)close(fd);
		errno = ESTALE;
		return -1;
	}
	if (swapz_primary_sysfs_partuuid_matches(
		expected_device, partition->partuuid) < 0) {
		saved_errno = errno;
		(void)close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	return 0;
}

static int swapz_primary_udev_parent_identity_sha256(
	dev_t parent_device, const char *parent_sysfs_path,
	uint64_t parent_size_sectors, char digest[65],
	char table_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U],
	char table_type[16])
{
	struct swapz_primary_udev_scope_properties properties = {0};
	struct stat opened;
	char canonical[4096];
	char device_path[128];
	uint64_t opened_bytes = 0;
	int parent_fd = -1;
	int path_length;
	int saved_errno;
	int length;

	if (!parent_device || !parent_sysfs_path || !parent_size_sectors ||
	    !digest || !table_uuid || !table_type ||
	    swapz_primary_udev_scope_properties_read(
		    parent_device, 0, &properties) < 0)
		return -1;
	if (parent_size_sectors > UINT64_MAX / 512ULL) {
		memset(&properties, 0, sizeof(properties));
		errno = EOVERFLOW;
		return -1;
	}
	path_length = snprintf(device_path, sizeof(device_path),
			       "/dev/block/%u:%u", major(parent_device),
			       minor(parent_device));
	if (path_length <= 0 || (size_t)path_length >= sizeof(device_path)) {
		memset(&properties, 0, sizeof(properties));
		errno = ENAMETOOLONG;
		return -1;
	}
	parent_fd = open(device_path, O_RDONLY | O_NONBLOCK | O_CLOEXEC);
	if (parent_fd < 0) {
		memset(&properties, 0, sizeof(properties));
		return -1;
	}
	if (fstat(parent_fd, &opened) < 0)
		goto parent_fd_error;
	if (!S_ISBLK(opened.st_mode) || opened.st_rdev != parent_device) {
		errno = ESTALE;
		goto parent_fd_error;
	}
	if (ioctl(parent_fd, BLKGETSIZE64, &opened_bytes) < 0)
		goto parent_fd_error;
	if (opened_bytes != parent_size_sectors * 512ULL) {
		errno = ESTALE;
		goto parent_fd_error;
	}
	if (close(parent_fd) < 0) {
		saved_errno = errno;
		memset(&properties, 0, sizeof(properties));
		errno = saved_errno;
		return -1;
	}
	parent_fd = -1;
	if (strcmp(properties.device_type, "disk") ||
	    !properties.table_uuid[0] ||
	    (strcmp(properties.table_type, "dos") &&
	     strcmp(properties.table_type, "gpt"))) {
		memset(&properties, 0, sizeof(properties));
		errno = ESTALE;
		return -1;
	}
	length = snprintf(canonical, sizeof(canonical),
			   "parent=%u:%u\nsize=%llu\nserial=%s\nwwn=%s\n"
			   "vendor=%s\nmodel=%s\ntable_uuid=%s\n"
			   "table_type=%s\n",
			   major(parent_device), minor(parent_device),
			   (unsigned long long)parent_size_sectors,
			   properties.serial, properties.wwn,
			   properties.vendor, properties.model,
			   properties.table_uuid, properties.table_type);
	if (length <= 0 || (size_t)length >= sizeof(canonical)) {
		memset(&properties, 0, sizeof(properties));
		errno = EOVERFLOW;
		return -1;
	}
	if (swapz_primary_sha256((const unsigned char *)canonical,
				(size_t)length, digest) < 0) {
		memset(&properties, 0, sizeof(properties));
		memset(canonical, 0, sizeof(canonical));
		return -1;
	}
	memcpy(table_uuid, properties.table_uuid,
	       sizeof(properties.table_uuid));
	memcpy(table_type, properties.table_type, sizeof(properties.table_type));
	memset(&properties, 0, sizeof(properties));
	memset(canonical, 0, sizeof(canonical));
	return 0;

parent_fd_error:
	saved_errno = errno;
	if (close(parent_fd) < 0 && !saved_errno)
		saved_errno = errno;
	memset(&properties, 0, sizeof(properties));
	errno = saved_errno ? saved_errno : EIO;
	return -1;
}

static int swapz_primary_partition_scope_order(
	const void *left_pointer, const void *right_pointer)
{
	const struct swapz_primary_partition_scope *left = left_pointer;
	const struct swapz_primary_partition_scope *right = right_pointer;

	if (left->partition_number < right->partition_number)
		return -1;
	if (left->partition_number > right->partition_number)
		return 1;
	return 0;
}

static int swapz_primary_partition_layout_sha256(
	const char *parent_sysfs_path, uint64_t parent_size_sectors,
	const struct swapz_primary_partition_scope *root,
	const struct swapz_primary_partition_scope *target,
	char digest[65])
{
	struct swapz_primary_partition_scope *partitions = NULL;
	DIR *directory = NULL;
	struct dirent *entry;
	char *canonical = NULL;
	size_t count = 0;
	size_t used = 0;
	int result = -1;
	int saved_errno = 0;

	if (!parent_sysfs_path || !parent_size_sectors || !root || !target ||
	    !digest) {
		errno = EINVAL;
		return -1;
	}
	partitions = calloc(SWAPZ_PRIMARY_PARTITION_FACTS_MAX,
			    sizeof(*partitions));
	canonical = calloc(SWAPZ_PRIMARY_PARTITION_FACTS_MAX,
			   SWAPZ_PRIMARY_PARTITION_CANONICAL_BYTES);
	if (!partitions || !canonical)
		goto out;
	directory = opendir(parent_sysfs_path);
	if (!directory)
		goto out;
	for (;;) {
		char child_path[PATH_MAX];
		char partition_path[PATH_MAX];
		struct stat partition_info;
		int child_is_directory;

		errno = 0;
		entry = readdir(directory);
		if (!entry) {
			if (errno)
				goto out;
			break;
		}
		if (!strcmp(entry->d_name, ".") ||
		    !strcmp(entry->d_name, ".."))
			continue;
		if (swapz_primary_path_format(child_path, sizeof(child_path),
					      "%s/%s", parent_sysfs_path,
					      entry->d_name) < 0)
			goto out;
		/*
		 * Sysfs parent directories also contain regular attributes such as
		 * uevent and symlinks. Only real child directories can be partitions;
		 * probing an attribute/partition path would return ENOTDIR.
		 */
		child_is_directory =
			swapz_primary_sysfs_entry_is_directory(child_path);
		if (child_is_directory < 0)
			goto out;
		if (!child_is_directory)
			continue;
		if (swapz_primary_path_format(partition_path,
					      sizeof(partition_path),
					      "%s/partition", child_path) < 0)
			goto out;
		if (lstat(partition_path, &partition_info) < 0) {
			if (errno == ENOENT)
				continue;
			goto out;
		}
		if (!S_ISREG(partition_info.st_mode) ||
		    count == SWAPZ_PRIMARY_PARTITION_FACTS_MAX ||
		    swapz_primary_read_partition_scope_path(
			    child_path, &partitions[count]) < 0)
			goto out;
		++count;
	}
	if (!count) {
		(void)closedir(directory);
		directory = NULL;
		errno = ENODATA;
		goto out;
	}
	if (closedir(directory) < 0) {
		directory = NULL;
		goto out;
	}
	directory = NULL;
	qsort(partitions, count, sizeof(*partitions),
	      swapz_primary_partition_scope_order);
	if (!swapz_primary_partition_scope_layout_valid(
		    partitions, count, parent_size_sectors, root, target)) {
		errno = EBADMSG;
		goto out;
	}
	for (size_t index = 0; index < count; ++index) {
		int length = snprintf(
			canonical + used,
			SWAPZ_PRIMARY_PARTITION_FACTS_MAX *
				SWAPZ_PRIMARY_PARTITION_CANONICAL_BYTES - used,
			"%u:%u,%u,%llu,%llu,%s,%s,%s,%s,%s\n",
			partitions[index].device_major,
			partitions[index].device_minor,
			partitions[index].partition_number,
			(unsigned long long)partitions[index].start_sectors,
			(unsigned long long)partitions[index].size_sectors,
			partitions[index].partuuid, partitions[index].parttype,
			partitions[index].partscheme,
			partitions[index].part_table_uuid,
			partitions[index].part_table_type);

		if (length <= 0 ||
		    (size_t)length >= SWAPZ_PRIMARY_PARTITION_FACTS_MAX *
				SWAPZ_PRIMARY_PARTITION_CANONICAL_BYTES - used) {
			errno = EOVERFLOW;
			goto out;
		}
		used += (size_t)length;
	}
	if (swapz_primary_sha256((const unsigned char *)canonical, used,
				 digest) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno;
	if (directory && closedir(directory) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (partitions) {
		memset(partitions, 0,
		       SWAPZ_PRIMARY_PARTITION_FACTS_MAX * sizeof(*partitions));
		free(partitions);
	}
	if (canonical) {
		memset(canonical, 0, SWAPZ_PRIMARY_PARTITION_FACTS_MAX *
			       SWAPZ_PRIMARY_PARTITION_CANONICAL_BYTES);
		free(canonical);
	}
	errno = saved_errno;
	return result;
}

static int swapz_primary_shared_root_scope_collect(
	const struct swapz_primary_target *target, dev_t root_device,
	dev_t expected_target_parent, dev_t expected_root_parent,
	int target_fd, struct swapz_primary_shared_root_scope *scope)
{
	struct swapz_primary_partition_scope root = {0};
	struct swapz_primary_partition_scope target_partition = {0};
	char root_sysfs_path[PATH_MAX];
	char target_sysfs_path[PATH_MAX];
	char root_parent_path[PATH_MAX];
	char target_parent_path[PATH_MAX];
	char parent_identity_sha256[65];
	char host_identity_sha256[65];
	char layout_sha256[65];
	char parent_table_uuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char parent_table_type[16];
	char path[PATH_MAX];
	char text[64];
	dev_t root_parent;
	dev_t target_parent;
	uint64_t parent_size_sectors;
	struct stat opened;
	uint64_t opened_size = 0;
	int length;

	if (!target || !scope || !swapz_primary_target_valid(target) ||
	    !root_device || !expected_target_parent ||
	    expected_target_parent != expected_root_parent) {
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_partition_scope_device(
		    root_device, &root, root_sysfs_path, 1) < 0 ||
	    swapz_primary_partition_scope_device(
		    makedev(target->device_major, target->device_minor),
		    &target_partition, target_sysfs_path, 1) < 0)
		return -1;
	if (strcmp(target_partition.partuuid, target->partuuid) ||
	    target_partition.size_bytes != target->device_bytes) {
		errno = ESTALE;
		return -1;
	}
	if (target_fd >= 0) {
		dev_t expected_device = makedev(target->device_major,
						target->device_minor);

		if (fstat(target_fd, &opened) < 0)
			return -1;
		if (!S_ISBLK(opened.st_mode) || opened.st_rdev != expected_device) {
			errno = ESTALE;
			return -1;
		}
		if (ioctl(target_fd, BLKGETSIZE64, &opened_size) < 0)
			return -1;
		if (opened_size != target->device_bytes) {
			errno = ESTALE;
			return -1;
		}
		if (swapz_primary_sysfs_partuuid_matches(
			    opened.st_rdev, target->partuuid) < 0)
			return -1;
	}
	length = snprintf(root_parent_path, sizeof(root_parent_path), "%s",
			  root_sysfs_path);
	if (length <= 0 || (size_t)length >= sizeof(root_parent_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	length = snprintf(target_parent_path, sizeof(target_parent_path), "%s",
			  target_sysfs_path);
	if (length <= 0 || (size_t)length >= sizeof(target_parent_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	{
		char *slash = strrchr(root_parent_path, '/');
		char *target_slash = strrchr(target_parent_path, '/');

		if (!slash || !target_slash || slash == root_parent_path ||
		    target_slash == target_parent_path) {
			errno = ENODEV;
			return -1;
		}
		*slash = '\0';
		*target_slash = '\0';
	}
	if (strcmp(root_parent_path, target_parent_path) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/partition",
				      target_parent_path) < 0) {
		errno = ESTALE;
		return -1;
	}
	if (lstat(path, &(struct stat){0}) == 0) {
		errno = ENODEV;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      target_parent_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &target_parent) < 0)
		return -1;
	if (target_parent != expected_target_parent) {
		errno = ESTALE;
		return -1;
	}
	if (swapz_primary_path_format(path, sizeof(path), "%s/size",
				      target_parent_path) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_u64(text, &parent_size_sectors) < 0)
		return -1;
	if (!parent_size_sectors) {
		errno = ENODATA;
		return -1;
	}
	if (swapz_primary_path_format(path, sizeof(path), "%s/dev",
				      root_parent_path) < 0 ||
	    swapz_primary_sysfs_dev_number(path, &root_parent) < 0)
		return -1;
	if (root_parent != expected_root_parent) {
		errno = ESTALE;
		return -1;
	}
	if (swapz_primary_udev_parent_identity_sha256(
		    target_parent, target_parent_path, parent_size_sectors,
		    parent_identity_sha256, parent_table_uuid,
		    parent_table_type) < 0 ||
	    swapz_primary_partition_layout_sha256(
		    target_parent_path, parent_size_sectors, &root,
		    &target_partition, layout_sha256) < 0 ||
	    swapz_primary_live_host_identity_sha256(host_identity_sha256) < 0)
		return -1;
	if (strcmp(root.part_table_uuid, parent_table_uuid) ||
	    strcmp(target_partition.part_table_uuid, parent_table_uuid) ||
	    strcmp(root.part_table_type, parent_table_type) ||
	    strcmp(target_partition.part_table_type, parent_table_type)) {
		errno = ESTALE;
		return -1;
	}
	memset(scope, 0, sizeof(*scope));
	memcpy(scope->host_identity_sha256, host_identity_sha256,
	       sizeof(scope->host_identity_sha256));
	scope->root = root;
	scope->target = target_partition;
	scope->parent_major = major(target_parent);
	scope->parent_minor = minor(target_parent);
	scope->parent_size_sectors = parent_size_sectors;
	memcpy(scope->parent_identity_sha256, parent_identity_sha256,
	       sizeof(scope->parent_identity_sha256));
	memcpy(scope->partition_layout_sha256, layout_sha256,
	       sizeof(scope->partition_layout_sha256));
	memset(host_identity_sha256, 0, sizeof(host_identity_sha256));
	memset(parent_identity_sha256, 0, sizeof(parent_identity_sha256));
	memset(layout_sha256, 0, sizeof(layout_sha256));
	memset(parent_table_uuid, 0, sizeof(parent_table_uuid));
	memset(parent_table_type, 0, sizeof(parent_table_type));
	return 0;
}

static int swapz_primary_shared_root_scope_record_live(
	const struct swapz_primary_target *target, dev_t root_device,
	dev_t target_parent, dev_t root_parent, int target_fd,
	char scope_sha256[65])
{
	struct swapz_primary_shared_root_scope scope = {0};
	struct stat directory_info;
	char scope_digest[65];
	int directory_fd = -1;
	int result = -1;
	int saved_errno;

	if (!scope_sha256) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_shared_root_parent_relationship_valid(
		target_parent, root_parent))
		return -1;
	if (swapz_primary_shared_root_scope_collect(
		    target, root_device, target_parent, root_parent, target_fd,
		    &scope) < 0 ||
	    swapz_primary_shared_root_scope_sha256(&scope, scope_digest) < 0)
		goto out;
	memcpy(scope_sha256, scope_digest, sizeof(scope_digest));
	directory_fd = open(SWAPZ_PRIMARY_CONFIG_BASE,
			    O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	if (directory_fd < 0)
		goto out;
	if (fstat(directory_fd, &directory_info) < 0 ||
	    !S_ISDIR(directory_info.st_mode) || directory_info.st_uid != 0 ||
	    (directory_info.st_mode & 0022U)) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_shared_root_scope_record_read_at(
		    directory_fd, 0U, scope_digest) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno;
	if (directory_fd >= 0 && close(directory_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	memset(&scope, 0, sizeof(scope));
	memset(scope_digest, 0, sizeof(scope_digest));
	errno = saved_errno;
	return result;
}
#endif

static int swapz_primary_read_qualification_report(
	struct swapz_primary_qualification *qualification)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)qualification;
	errno = ENODEV;
	return -1;
#else
	struct stat before;
	struct stat after;
	char host_identity_sha256[65];
	unsigned char *bytes = NULL;
	size_t length;
	size_t completed = 0;
	int fd = -1;
	int result = -1;

	if (!qualification || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_live_host_identity_sha256(host_identity_sha256) < 0)
		return -1;
	fd = open(SWAPZ_PRIMARY_QUALIFICATION_REPORT,
		  O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
	if (fd < 0)
		return -1;
	if (fstat(fd, &before) < 0 || !S_ISREG(before.st_mode) ||
	    before.st_uid != 0 || before.st_nlink != 1U ||
	    (before.st_mode & 0022U) || before.st_size <= 0 ||
	    (uint64_t)before.st_size > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES) {
		errno = EPERM;
		goto out;
	}
	length = (size_t)before.st_size;
	bytes = malloc(length);
	if (!bytes)
		goto out;
	while (completed < length) {
		ssize_t count = pread(fd, bytes + completed, length - completed,
				      (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto out;
		}
		completed += (size_t)count;
	}
	{
		unsigned char extra;
		ssize_t count;

		do {
			count = pread(fd, &extra, sizeof(extra), (off_t)length);
		} while (count < 0 && errno == EINTR);
		if (count != 0) {
			if (count > 0)
				errno = EFBIG;
			goto out;
		}
	}
	if (fstat(fd, &after) < 0)
		goto out;
	if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_mode != after.st_mode || before.st_uid != after.st_uid ||
	    before.st_gid != after.st_gid || before.st_nlink != after.st_nlink ||
	    before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec) {
		errno = EIO;
		goto out;
	}
	if (swapz_primary_qualification_parse_json(
		    bytes, length, SWAPZ_BUILD_SOURCE_SHA,
		    host_identity_sha256, qualification) < 0 ||
	    swapz_primary_running_kernel_matches_qualification(qualification) < 0)
		goto out;
	result = 0;
out:
	{
		int saved_errno = errno;

		free(bytes);
		if (fd >= 0 && close(fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		errno = saved_errno;
	}
	return result;
#endif
}

static int swapz_primary_qualification_artifacts_match(
	const struct swapz_primary_qualification *qualification,
	const char *swapzctl_sha256, const char *module_sha256,
	const char *oracle_sha256)
{
	return qualification &&
	       swapz_primary_valid_sha256(qualification->formatter_sha256) &&
	       swapz_primary_valid_sha256(qualification->module_sha256) &&
	       swapz_primary_valid_sha256(qualification->oracle_sha256) &&
	       swapz_primary_valid_sha256(swapzctl_sha256) &&
	       swapz_primary_valid_sha256(module_sha256) &&
	       swapz_primary_valid_sha256(oracle_sha256) &&
	       !strcmp(qualification->formatter_sha256, swapzctl_sha256) &&
	       !strcmp(qualification->module_sha256, module_sha256) &&
	       !strcmp(qualification->oracle_sha256, oracle_sha256);
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_hash_regular_path(const char *path, int follow_final,
					   char digest[65])
{
	int flags = O_RDONLY | O_CLOEXEC | O_NONBLOCK;
	int fd;
	int result;

	if (!path || !digest) {
		errno = EINVAL;
		return -1;
	}
	if (!follow_final)
		flags |= O_NOFOLLOW;
	fd = open(path, flags);
	if (fd < 0)
		return -1;
	result = swapz_primary_sha256_regular_fd(fd, 0,
						SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES,
						digest);
	{
		int saved_errno = errno;

		if (close(fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		errno = saved_errno;
	}
	return result;
}
#endif

static int swapz_primary_live_artifact_hashes(char swapzctl_sha256[65],
						     char module_sha256[65],
						     char oracle_sha256[65],
						     const char *expected_module_sha256,
						     int *module_fd_out)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)swapzctl_sha256;
	(void)module_sha256;
	(void)oracle_sha256;
	(void)expected_module_sha256;
	if (module_fd_out)
		*module_fd_out = -1;
	errno = ENODEV;
	return -1;
#else
	static const char control_suffix[] = "/sbin/swapzctl";
	char control_path[PATH_MAX];
	char oracle_path[PATH_MAX];
	ssize_t control_length;
	int prefix_length;
	int length;
	int module_fd = -1;
	int result = -1;

	if (module_fd_out)
		*module_fd_out = -1;
	if (!swapzctl_sha256 || !module_sha256 || !oracle_sha256 ||
	    !swapz_primary_valid_sha256(expected_module_sha256)) {
		errno = EINVAL;
		return -1;
	}
#ifdef SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST
	control_length = snprintf(control_path, sizeof(control_path), "%s",
				  SWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL);
	if (control_length < 0 || (size_t)control_length >= sizeof(control_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (control_path[0] != '/') {
		errno = EPERM;
		return -1;
	}
#else
	control_length = readlink("/proc/self/exe", control_path,
				  sizeof(control_path) - 1U);
	if (control_length < 0)
		return -1;
	if ((size_t)control_length >= sizeof(control_path) - 1U) {
		errno = ENAMETOOLONG;
		return -1;
	}
	control_path[control_length] = '\0';
#endif
	if ((size_t)control_length < sizeof(control_suffix) - 1U ||
	    strcmp(control_path + control_length -
		   (ssize_t)(sizeof(control_suffix) - 1U), control_suffix)) {
		errno = EPERM;
		return -1;
	}
	prefix_length = (int)(control_length -
			      (ssize_t)(sizeof(control_suffix) - 1U));
	if (prefix_length <= 0) {
		errno = EPERM;
		return -1;
	}
	length = snprintf(oracle_path, sizeof(oracle_path),
			  "%.*s/libexec/swapz/device-roundtrip",
			  prefix_length, control_path);
	if (length < 0 || (size_t)length >= sizeof(oracle_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
#ifdef SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST
	if (swapz_primary_hash_regular_path(control_path, 1,
					    swapzctl_sha256) < 0 ||
	    swapz_primary_hash_regular_path(oracle_path, 0, oracle_sha256) < 0)
		return -1;
#else
	if (swapz_primary_hash_regular_path("/proc/self/exe", 1,
					    swapzctl_sha256) < 0 ||
	    swapz_primary_hash_regular_path(oracle_path, 0, oracle_sha256) < 0)
		return -1;
#endif
	module_fd = swapz_primary_open_qualified_module_fd(
		control_path, expected_module_sha256);
	if (module_fd < 0)
		return -1;
	result = swapz_primary_sha256_regular_fd(
		module_fd, 0, SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES,
		module_sha256);
	if (result == 0 && module_fd_out) {
		*module_fd_out = module_fd;
		return 0;
	}
	{
		int saved_errno = errno;

		if (close(module_fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		errno = saved_errno;
	}
	return result;
#endif
}

static int swapz_primary_parse_module_bool(const char *value, int *enabled)
{
	if (!value || !enabled) {
		errno = EINVAL;
		return -1;
	}
	if (!strcmp(value, "Y") || !strcmp(value, "1")) {
		*enabled = 1;
		return 0;
	}
	if (!strcmp(value, "N") || !strcmp(value, "0")) {
		*enabled = 0;
		return 0;
	}
	errno = EINVAL;
	return -1;
}

/* finit_module(2) does not load separate kernel dependencies. Use a fixed
 * kmod invocation only after qualified artifact hashes have matched; retain
 * the exact hashed module fd for finit_module. The provider may be shared by
 * other subsystems and must never be unloaded by swapz.
 */
#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_ensure_lz4_provider(void)
{
	char *const arguments[] = {
		(char *)"modprobe", (char *)"--ignore-install",
		(char *)"--", (char *)"lz4_compress", NULL,
	};
	char *const environment[] = {
		(char *)"LC_ALL=C",
		(char *)"PATH=/usr/sbin:/usr/bin:/sbin:/bin", NULL,
	};
	pid_t child;
	int status;
	int spawn_status;

	/* No shell, PATH executable lookup, ambient variables or install hook. */
	spawn_status = posix_spawn(&child, "/usr/sbin/modprobe", NULL, NULL,
				   arguments, environment);
	if (spawn_status != 0) {
		errno = spawn_status;
		return -1;
	}
	for (;;) {
		if (waitpid(child, &status, 0) == child)
			break;
		if (errno != EINTR)
			return -1;
	}
	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
		errno = EIO;
		return -1;
	}
	return 0;
}
#endif

int swapz_primary_load_qualified_module(int *loaded_by_call)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (!loaded_by_call) {
		errno = EINVAL;
		return -1;
	}
	*loaded_by_call = 0;
	errno = ENODEV;
	return -1;
#else
	struct swapz_primary_qualification qualification;
	char swapzctl_sha256[65];
	char module_sha256[65];
	char oracle_sha256[65];
	char module_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U];
	char module_parameter_path[PATH_MAX];
	char module_parameter[16];
	int module_loaded = 0;
	int swapz_mapper_present = 0;
	int module_inventory_read;
	int module_source_clean = 0;
	int physical_backing_enabled = 0;
	int ram_metadata_qualified_enabled = 0;
	int module_fd = -1;
	int result = -1;
	int saved_errno;

	if (!loaded_by_call) {
		errno = EINVAL;
		return -1;
	}
	*loaded_by_call = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_read_qualification_report(&qualification) < 0 ||
	    strcmp(qualification.source_sha, SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	module_inventory_read = swapz_primary_read_module_mapper_inventory(
		&module_loaded, &swapz_mapper_present) == 0;
	if (!module_inventory_read)
		return -1;
	if (module_loaded || swapz_mapper_present) {
		errno = EBUSY;
		return -1;
	}
	if (swapz_primary_live_artifact_hashes(
		    swapzctl_sha256, module_sha256, oracle_sha256,
		    qualification.module_sha256, &module_fd) < 0)
		return -1;
	if (!swapz_primary_qualification_artifacts_match(
		    &qualification, swapzctl_sha256, module_sha256,
		    oracle_sha256)) {
		errno = EBADMSG;
		goto out;
	}
	if (swapz_primary_ensure_lz4_provider() < 0)
		goto out;
	if (syscall(SYS_finit_module, module_fd,
		    "allow_physical_backing=1 physical_ram_metadata_qualified=1",
		    0U) < 0)
		goto out;
	*loaded_by_call = 1;
	if (close(module_fd) < 0) {
		module_fd = -1;
		goto out;
	}
	module_fd = -1;
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &swapz_mapper_present) < 0)
		goto out;
	if (!module_loaded || swapz_mapper_present) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_read_module_build_provenance(
		    module_loaded, module_source_sha,
		    &module_source_clean) < 0 ||
	    !swapz_primary_build_sources_match(
		    qualification.source_sha, 1, module_source_sha,
		    module_source_clean)) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_path_format(
		    module_parameter_path, sizeof(module_parameter_path),
		    "/sys/module/dm_swapz/parameters/allow_physical_backing") < 0 ||
	    swapz_primary_read_sysfs_text(module_parameter_path,
				      module_parameter,
				      sizeof(module_parameter)) < 0 ||
	    swapz_primary_parse_module_bool(module_parameter,
					    &physical_backing_enabled) < 0 ||
	    !physical_backing_enabled ||
	    swapz_primary_path_format(
		    module_parameter_path, sizeof(module_parameter_path),
		    "/sys/module/dm_swapz/parameters/physical_ram_metadata_qualified") < 0 ||
	    swapz_primary_read_sysfs_text(module_parameter_path,
				      module_parameter,
				      sizeof(module_parameter)) < 0 ||
	    swapz_primary_parse_module_bool(module_parameter,
					    &ram_metadata_qualified_enabled) < 0 ||
	    !ram_metadata_qualified_enabled) {
		errno = EPERM;
		goto out;
	}
	result = 0;
out:
	saved_errno = errno;
	if (module_fd >= 0 && close(module_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	errno = saved_errno;
	return result;
#endif
}

static int swapz_primary_manifest_equal(
	const struct swapz_primary_manifest *left,
	const struct swapz_primary_manifest *right)
{
	return left && right && !strcmp(left->run_id, right->run_id) &&
	       !strcmp(left->source_sha, right->source_sha) &&
	       !strcmp(left->swapzctl_sha256, right->swapzctl_sha256) &&
	       !strcmp(left->module_sha256, right->module_sha256) &&
	       !strcmp(left->qualification_report_sha256,
		       right->qualification_report_sha256) &&
	       !strcmp(left->original_header_sha256,
		       right->original_header_sha256) &&
	       left->backing_physical_blocks == right->backing_physical_blocks &&
	       left->original_swap_active == right->original_swap_active &&
	       left->original_swap_priority == right->original_swap_priority &&
	       !memcmp(&left->target, &right->target,
		       sizeof(left->target));
}

static int swapz_primary_transaction_manifest_matches_at(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	const enum swapz_primary_stage *allowed_stages, size_t stage_count,
	uid_t expected_owner)
{
	struct swapz_primary_state state;
	struct swapz_primary_manifest stored_manifest;
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t record_length = 0;
	size_t i;
	int stage_allowed = 0;

	if (!swapz_primary_manifest_valid(manifest) || !allowed_stages ||
	    !stage_count ||
	    !swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(
		    recovery_fd, manifest->run_id, expected_owner)) {
		errno = EPERM;
		return -1;
	}
	swapz_primary_selected_target = manifest->target;
	if (swapz_primary_record_read_at(
		    recovery_fd, "primary-state.json", expected_owner, record,
		    sizeof(record), &record_length, NULL) < 0 ||
	    swapz_primary_state_parse(record, record_length, &state) < 0 ||
	    strcmp(state.run_id, manifest->run_id)) {
		errno = EPERM;
		return -1;
	}
	for (i = 0; i < stage_count; ++i)
		if (state.stage == allowed_stages[i])
			stage_allowed = 1;
	if (!stage_allowed) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_manifest_read_at(
		    recovery_fd, lock_fd, manifest->run_id,
		    manifest->target.partuuid, expected_owner,
		    &stored_manifest) < 0 ||
	    !swapz_primary_manifest_equal(manifest, &stored_manifest)) {
		errno = EPERM;
		return -1;
	}
	return 0;
}


static int swapz_primary_module_load_record_format(
	const struct swapz_primary_manifest *manifest, const char *phase,
	char name[96], char record[512])
{
	int name_length;
	int record_length;

	if (!swapz_primary_manifest_valid(manifest) || !phase ||
	    (strcmp(phase, "INTENT") && strcmp(phase, "LOADED"))) {
		errno = EINVAL;
		return -1;
	}
	name_length = snprintf(name, 96U, "primary-module-load-%s.json",
			       manifest->run_id);
	if (name_length < 0 || (size_t)name_length >= 96U) {
		errno = ENAMETOOLONG;
		return -1;
	}
	record_length = snprintf(
		record, 512U,
		"{\"schema\":\"swapz-primary-module-load-v1\","
		"\"run_id\":\"%s\",\"source_sha\":\"%s\","
		"\"module_sha256\":\"%s\","
		"\"qualification_report_sha256\":\"%s\","
		"\"phase\":\"%s\"}\n",
		manifest->run_id, manifest->source_sha, manifest->module_sha256,
		manifest->qualification_report_sha256, phase);
	if (record_length < 0 || (size_t)record_length >= 512U) {
		errno = EOVERFLOW;
		return -1;
	}
	return 0;
}

static int swapz_primary_module_load_record_matches_at(
	int recovery_fd, const struct swapz_primary_manifest *manifest,
	const char *phase, uid_t expected_owner)
{
	char name[96];
	char expected[512];
	char observed[512];
	size_t observed_length = 0;
	size_t expected_length;

	if (swapz_primary_module_load_record_format(
		    manifest, phase, name, expected) < 0)
		return -1;
	expected_length = strlen(expected);
	if (swapz_primary_record_read_at(
		    recovery_fd, name, expected_owner, observed, sizeof(observed),
		    &observed_length, NULL) < 0)
		return -1;
	if (observed_length != expected_length ||
	    memcmp(observed, expected, expected_length)) {
		errno = EBADMSG;
		return -1;
	}
	return 0;
}

static int swapz_primary_module_load_intent_write_at(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest, uid_t expected_owner)
{
	static const enum swapz_primary_stage starting[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	char name[96];
	char record[512];

	if (swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, starting,
		    sizeof(starting) / sizeof(starting[0]), expected_owner) < 0 ||
	    swapz_primary_module_load_record_format(
		    manifest, "INTENT", name, record) < 0)
		return -1;
	if (swapz_primary_write_record_at(
		    recovery_fd, name, record, expected_owner) < 0)
		return -1;
	return swapz_primary_module_load_record_matches_at(
		recovery_fd, manifest, "INTENT", expected_owner);
}

static int swapz_primary_module_load_mark_loaded_at(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest, uid_t expected_owner)
{
	static const enum swapz_primary_stage starting[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	char name[96];
	char record[512];

	if (swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, starting,
		    sizeof(starting) / sizeof(starting[0]), expected_owner) < 0 ||
	    swapz_primary_module_load_record_matches_at(
		    recovery_fd, manifest, "INTENT", expected_owner) < 0 ||
	    swapz_primary_module_load_record_format(
		    manifest, "LOADED", name, record) < 0)
		return -1;
	if (swapz_primary_replace_record_at(
		    recovery_fd, name, manifest->run_id, record,
		    expected_owner) < 0)
		return -1;
	return swapz_primary_module_load_record_matches_at(
		recovery_fd, manifest, "LOADED", expected_owner);
}

/*
 * Keep the kernel transition's syscall and inventory decisions in one small
 * production helper. Rootless tests inject only these three boundaries; the
 * privileged callers still perform the manifest, owner-lock, Device Mapper,
 * descriptor and target-identity checks before they reach this helper.
 */
struct swapz_primary_swap_transition_ops {
	int (*device_active)(void *context, dev_t expected_device);
	long (*swapon)(void *context, const char *mapper_path);
	long (*swapoff)(void *context, const char *mapper_path);
	void *context;
};

static int swapz_primary_swap_transition_apply(
	int activate, dev_t mapper_device, dev_t backing_device,
	const char *mapper_path,
	const struct swapz_primary_swap_transition_ops *ops,
	int *operation_verified_by_call)
{
	int mapper_active;
	int backing_active;
	int syscall_errno = 0;
	long syscall_result;
	int result = -1;
	int saved_errno = EIO;

	if ((activate != 0 && activate != 1) || mapper_device == 0 ||
	    backing_device == 0 || !mapper_path || !*mapper_path || !ops ||
	    !ops->device_active || !ops->swapon || !ops->swapoff ||
	    !operation_verified_by_call) {
		errno = EINVAL;
		return -1;
	}
	*operation_verified_by_call = 0;
	backing_active = ops->device_active(ops->context, backing_device);
	if (backing_active < 0)
		goto out;
	if (backing_active != 0) {
		errno = EBUSY;
		goto out;
	}
	mapper_active = ops->device_active(ops->context, mapper_device);
	if (mapper_active < 0)
		goto out;
	if (mapper_active > 1) {
		errno = EPROTO;
		goto out;
	}
	if (activate && mapper_active) {
		/* STARTING must not adopt an unexplained pre-existing swap area. */
		errno = EBUSY;
		goto out;
	}
	if (!activate && !mapper_active) {
		/* Exact inventory absence is already a safe idempotent stop result. */
		result = 0;
		goto out;
	}

	/*
	 * Linux accepts a pathname here. Production supplies /proc/self/fd/N for
	 * the already-open, identity-checked mapper; the inventory callback then
	 * proves that the kernel activated/deactivated that exact block dev_t.
	 * A definite syscall failure is authoritative and returns immediately.
	 * EINTR is ambiguous, so only the post-syscall inventory can reconcile it.
	 */
	errno = 0;
	syscall_result = activate ?
		ops->swapon(ops->context, mapper_path) :
		ops->swapoff(ops->context, mapper_path);
	if (syscall_result < 0)
		syscall_errno = errno ? errno : EIO;
	if (syscall_result < 0 && syscall_errno != EINTR) {
		errno = syscall_errno;
		goto out;
	}

	mapper_active = ops->device_active(ops->context, mapper_device);
	if (mapper_active < 0)
		goto out;
	if (mapper_active > 1) {
		errno = EPROTO;
		goto out;
	}
	backing_active = ops->device_active(ops->context, backing_device);
	if (backing_active < 0)
		goto out;
	if (backing_active > 1) {
		errno = EPROTO;
		goto out;
	}
	if ((activate && mapper_active != 1) ||
	    (!activate && mapper_active != 0) || backing_active != 0) {
		errno = syscall_errno ? syscall_errno : EBUSY;
		goto out;
	}
	*operation_verified_by_call = 1;
	result = 0;
out:
	saved_errno = result == 0 ? 0 : (errno ? errno : EIO);
	if (result < 0)
		errno = saved_errno;
	return result;
}

static int swapz_primary_mapper_node_retryable_errno(int error)
{
	return error == ENOENT;
}

#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_swap_device_active(dev_t expected_device)
{
	struct swapz_primary_swap_entry entries[SWAPZ_PRIMARY_SWAP_ROWS_MAX];
	size_t entry_count = 0;
	size_t i;

	if (swapz_primary_read_swap_inventory(entries,
					     SWAPZ_PRIMARY_SWAP_ROWS_MAX,
					     &entry_count) < 0)
		return -1;
	for (i = 0; i < entry_count; ++i) {
		struct stat info;

		if (stat(entries[i].path, &info) < 0)
			return -1;
		if (!strcmp(entries[i].type, "partition")) {
			if (!S_ISBLK(info.st_mode)) {
				errno = EINVAL;
				return -1;
			}
			if (info.st_rdev == expected_device)
				return 1;
		} else if (!strcmp(entries[i].type, "file")) {
			/*
			 * /proc/swaps names a file, but its filesystem st_dev lets us
			 * reject swapfiles stored on the selected block device.
			 */
			if (!S_ISREG(info.st_mode)) {
				errno = EINVAL;
				return -1;
			}
			if (info.st_dev == expected_device)
				return 1;
		} else {
			errno = EINVAL;
			return -1;
		}
	}
	return 0;
}
#endif /* SWAPZ_PRIMARY_ROOTLESS_TEST: privileged swap inventory */

/* The original SWAPSPACE2 header is immutable for every backing device,
 * including the owned null_blk lifecycle rehearsal. The manifest retains only
 * its SHA-256 identity; lifecycle and recovery re-read live block zero and
 * never persist, restore or replace its bytes.
 */
static int swapz_primary_backing_header_matches_manifest(
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	const struct swapz_primary_manifest *manifest)
{
	char digest[65];

	if (!header || !swapz_primary_manifest_valid(manifest)) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_linux_swap_header_parse(
		    header, manifest->target.device_bytes, NULL) ||
	    swapz_primary_physical_blocks_from_header(
		    header, manifest->target.device_bytes) !=
		    manifest->backing_physical_blocks) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_sha256(header, SWAPZ_PRIMARY_BLOCK_BYTES, digest) < 0)
		return -1;
	if (strcmp(digest, manifest->original_header_sha256)) {
		errno = ESTALE;
		return -1;
	}
	return 0;
}


#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_dm_control_open(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENODEV;
	return -1;
#else
	struct dm_ioctl version;
	struct stat info;
	int fd = open(SWAPZ_PRIMARY_DM_CONTROL_PATH,
		      O_RDWR | O_NOFOLLOW | O_CLOEXEC);
	int saved_errno;

	if (fd < 0)
		return -1;
	if (fstat(fd, &info) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISCHR(info.st_mode) || info.st_uid != 0 ||
	    (info.st_mode & S_IWOTH)) {
		close(fd);
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_dm_ioctl_initialize(&version, sizeof(version),
					      NULL, NULL) < 0 ||
	    ioctl(fd, DM_VERSION, &version) < 0) {
		saved_errno = errno;
		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (version.version[0] != DM_VERSION_MAJOR ||
	    version.data_size < offsetof(struct dm_ioctl, data) ||
	    version.data_size > sizeof(version)) {
		close(fd);
		errno = ENOTSUP;
		return -1;
	}
	return fd;
#endif
}

static int swapz_primary_dm_status_fd(int fd, const char *name,
				      const char *uuid, struct dm_ioctl *status)
{
	if (fd < 0 || !name || !uuid || !status ||
	    swapz_primary_dm_existing_mapper_ioctl_initialize(
		    status, sizeof(*status), name, uuid) < 0)
		return -1;
	if (ioctl(fd, DM_DEV_STATUS, status) < 0)
		return -1;
	if (status->version[0] != DM_VERSION_MAJOR ||
	    status->data_size < offsetof(struct dm_ioctl, data) ||
	    status->data_size > sizeof(*status) ||
	    strnlen(status->name, sizeof(status->name)) == sizeof(status->name) ||
	    strnlen(status->uuid, sizeof(status->uuid)) == sizeof(status->uuid) ||
	    strcmp(status->name, name) || strcmp(status->uuid, uuid)) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_primary_dm_status_by_name_fd(int fd, const char *name,
					     struct dm_ioctl *status)
{
	if (fd < 0 || !name || !status ||
	    swapz_primary_dm_ioctl_initialize(status, sizeof(*status),
					      name, NULL) < 0)
		return -1;
	if (ioctl(fd, DM_DEV_STATUS, status) < 0)
		return -1;
	if (status->version[0] != DM_VERSION_MAJOR ||
	    status->data_size < offsetof(struct dm_ioctl, data) ||
	    status->data_size > sizeof(*status) ||
	    strnlen(status->name, sizeof(status->name)) == sizeof(status->name) ||
	    strnlen(status->uuid, sizeof(status->uuid)) == sizeof(status->uuid) ||
	    strcmp(status->name, name)) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_primary_dm_inactive_target_count_fd(
	int fd, const struct swapz_primary_manifest *manifest,
	dev_t expected_device, uint32_t *target_count)
{
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	struct dm_ioctl status;
	uint64_t logical_sectors;

	if (!target_count ||
	    swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	(void)logical_sectors;
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    &status, sizeof(status), mapper_name, mapper_uuid) < 0)
		return -1;
	status.flags = DM_QUERY_INACTIVE_TABLE_FLAG;
	if (ioctl(fd, DM_DEV_STATUS, &status) < 0)
		return -1;
	if (status.version[0] != DM_VERSION_MAJOR ||
	    status.data_size < offsetof(struct dm_ioctl, data) ||
	    status.data_size > sizeof(status) ||
	    status.dev != (uint64_t)expected_device ||
	    status.open_count != 0 ||
	    (status.flags & (DM_READONLY_FLAG | DM_INTERNAL_SUSPEND_FLAG |
			     DM_DEFERRED_REMOVE)) ||
	    strnlen(status.name, sizeof(status.name)) == sizeof(status.name) ||
	    strnlen(status.uuid, sizeof(status.uuid)) == sizeof(status.uuid) ||
	    strcmp(status.name, mapper_name) ||
	    strcmp(status.uuid, mapper_uuid) || status.target_count > 1U) {
		errno = EPROTO;
		return -1;
	}
	*target_count = status.target_count;
	return 0;
}

static int swapz_primary_dm_table_query_fd(
	int fd, const struct swapz_primary_manifest *manifest, int inactive)
{
	_Alignas(struct dm_ioctl) unsigned char buffer[SWAPZ_PRIMARY_DM_BUFFER_BYTES];
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	struct dm_ioctl *io = (struct dm_ioctl *)buffer;
	uint64_t logical_sectors;

	if (swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	(void)logical_sectors;
	memset(buffer, 0, sizeof(buffer));
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    io, sizeof(buffer), mapper_name, mapper_uuid) < 0)
		return -1;
	io->flags = DM_STATUS_TABLE_FLAG;
	if (inactive)
		io->flags |= DM_QUERY_INACTIVE_TABLE_FLAG;
	if (ioctl(fd, DM_TABLE_STATUS, io) < 0)
		return -1;
	if (io->flags & DM_BUFFER_FULL_FLAG) {
		errno = EOVERFLOW;
		return -1;
	}
	if ((!inactive && !(io->flags & DM_ACTIVE_PRESENT_FLAG)) ||
	    !swapz_primary_dm_table_status_matches(
		    buffer, sizeof(buffer), manifest)) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_primary_dm_dependencies_match_fd(
	int fd, const struct swapz_primary_manifest *manifest)
{
	_Alignas(struct dm_ioctl) unsigned char buffer[SWAPZ_PRIMARY_DM_BUFFER_BYTES];
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	struct dm_ioctl *io = (struct dm_ioctl *)buffer;
	struct dm_target_deps *dependencies;
	uint64_t logical_sectors;
	size_t available;

	if (swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	(void)logical_sectors;
	memset(buffer, 0, sizeof(buffer));
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    io, sizeof(buffer), mapper_name, mapper_uuid) < 0 ||
	    ioctl(fd, DM_TABLE_DEPS, io) < 0)
		return -1;
	if (io->version[0] != DM_VERSION_MAJOR ||
	    io->data_size < sizeof(*io) || io->data_size > sizeof(buffer) ||
	    io->data_start != sizeof(*io) ||
	    io->data_start > io->data_size ||
	    strnlen(io->name, sizeof(io->name)) == sizeof(io->name) ||
	    strnlen(io->uuid, sizeof(io->uuid)) == sizeof(io->uuid) ||
	    strcmp(io->name, mapper_name) || strcmp(io->uuid, mapper_uuid)) {
		errno = EPROTO;
		return -1;
	}
	available = (size_t)io->data_size - io->data_start;
	if (available < sizeof(*dependencies)) {
		errno = EPROTO;
		return -1;
	}
	dependencies = (struct dm_target_deps *)(buffer + io->data_start);
	if (dependencies->count != 1U || dependencies->padding != 0U ||
	    available != sizeof(*dependencies) + sizeof(dependencies->dev[0]) ||
	    dependencies->dev[0] != (uint64_t)SWAPZ_PRIMARY_TARGET_DEVICE) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_primary_dm_sysfs_matches(
	dev_t mapper_device, const char *mapper_name, const char *mapper_uuid,
	uint64_t logical_sectors)
{
	char root[PATH_MAX];
	char path[PATH_MAX];
	char text[256];
	dev_t observed_device;
	uint64_t observed_sectors;
	DIR *slaves = NULL;
	struct dirent *entry;
	unsigned int slave_count = 0;
	int matched_slave = 0;
	int saved_errno = 0;

	if (swapz_primary_path_format(root, sizeof(root),
				      "/sys/dev/block/%u:%u",
				      major(mapper_device), minor(mapper_device)) < 0 ||
	    swapz_primary_path_format(path, sizeof(path), "%s/dev", root) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_dev_number(text, &observed_device) < 0 ||
	    observed_device != mapper_device ||
	    swapz_primary_path_format(path, sizeof(path), "%s/size", root) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    swapz_primary_parse_u64(text, &observed_sectors) < 0 ||
	    observed_sectors != logical_sectors ||
	    swapz_primary_path_format(path, sizeof(path), "%s/dm/name", root) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    strcmp(text, mapper_name) ||
	    swapz_primary_path_format(path, sizeof(path), "%s/dm/uuid", root) < 0 ||
	    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
	    strcmp(text, mapper_uuid)) {
		errno = EPROTO;
		return -1;
	}
	if (swapz_primary_path_format(path, sizeof(path), "%s/slaves", root) < 0)
		return -1;
	slaves = opendir(path);
	if (!slaves)
		return -1;
	errno = 0;
	while ((entry = readdir(slaves)) != NULL) {
		dev_t slave_device;

		if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
			continue;
		if (++slave_count > 1U) {
			errno = EPROTO;
			break;
		}
		if (swapz_primary_path_format(path, sizeof(path),
					      "%s/slaves/%s/dev", root,
					      entry->d_name) < 0 ||
		    swapz_primary_read_sysfs_text(path, text, sizeof(text)) < 0 ||
		    swapz_primary_parse_dev_number(text, &slave_device) < 0)
			break;
		matched_slave = slave_device == SWAPZ_PRIMARY_TARGET_DEVICE;
	}
	saved_errno = errno;
	if (closedir(slaves) < 0 && !saved_errno)
		saved_errno = errno;
	if (saved_errno) {
		errno = saved_errno;
		return -1;
	}
	if (slave_count != 1U || !matched_slave) {
		errno = EPROTO;
		return -1;
	}
	return 0;
}

static int swapz_primary_dm_mapper_verify_fd(
	int fd, const struct swapz_primary_manifest *manifest,
	int require_active, int require_zero_open, dev_t *mapper_device)
{
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	struct dm_ioctl status;
	uint64_t logical_sectors;
	dev_t observed_device;

	if (!mapper_device || (require_active != 0 && require_active != 1) ||
	    (require_zero_open != 0 && require_zero_open != 1) ||
	    swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	*mapper_device = 0;
	if (swapz_primary_dm_status_fd(fd, mapper_name, mapper_uuid,
				       &status) < 0)
		return -1;
	if (status.dev == 0U || status.open_count < 0 ||
	    (status.flags & (DM_READONLY_FLAG | DM_INTERNAL_SUSPEND_FLAG |
			     DM_DEFERRED_REMOVE)) ||
	    (require_active &&
	     (!(status.flags & DM_ACTIVE_PRESENT_FLAG) ||
	      (status.flags & DM_SUSPEND_FLAG))) ||
	    (require_zero_open && status.open_count != 0)) {
		errno = EBUSY;
		return -1;
	}
	observed_device = (dev_t)status.dev;
	if ((uint64_t)observed_device != status.dev ||
	    swapz_primary_dm_table_query_fd(fd, manifest, 0) < 0 ||
	    swapz_primary_dm_dependencies_match_fd(fd, manifest) < 0 ||
	    swapz_primary_dm_sysfs_matches(observed_device, mapper_name,
					    mapper_uuid,
					    logical_sectors) < 0)
		return -1;
	*mapper_device = observed_device;
	return 0;
}

static int swapz_primary_dm_prove_mapper_absent(
	int fd, const char *mapper_name, const char *mapper_uuid)
{
	struct dm_ioctl status;

	errno = 0;
	if (swapz_primary_dm_status_by_name_fd(fd, mapper_name, &status) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENXIO)
		return -1;
	errno = 0;
	if (swapz_primary_dm_status_fd(fd, mapper_name, mapper_uuid,
				       &status) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENXIO)
		return -1;
	errno = 0;
	return 0;
}

static int swapz_primary_mapper_device_open_once(
	const char *mapper_name, dev_t expected_device,
	uint64_t expected_bytes)
{
	struct stat before;
	struct stat opened;
	struct stat after;
	char path[PATH_MAX];
	uint64_t bytes = 0;
	int fd;

	if (!mapper_name || !mapper_name[0] ||
	    swapz_primary_path_format(path, sizeof(path),
				      "/dev/mapper/%s", mapper_name) < 0)
		return -1;
	if (stat(path, &before) < 0)
		return -1;
	if (!S_ISBLK(before.st_mode) || before.st_rdev != expected_device) {
		errno = ENODEV;
		return -1;
	}
	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0 || ioctl(fd, BLKGETSIZE64, &bytes) < 0 ||
	    stat(path, &after) < 0)
		goto failed;
	if (!S_ISBLK(opened.st_mode) || opened.st_rdev != expected_device ||
	    !S_ISBLK(after.st_mode) || after.st_rdev != expected_device ||
	    bytes != expected_bytes) {
		errno = ESTALE;
		goto failed;
	}
	return fd;

failed:
	{
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
	}
	return -1;
}

static int swapz_primary_mapper_device_open(
	const char *mapper_name, dev_t expected_device,
	uint64_t expected_bytes)
{
	const struct timespec delay = {
		.tv_sec = 0,
		.tv_nsec = SWAPZ_PRIMARY_MAPPER_NODE_RETRY_NS,
	};
	unsigned int attempt;

	for (attempt = 0; attempt < SWAPZ_PRIMARY_MAPPER_NODE_RETRY_ATTEMPTS;
	     ++attempt) {
		struct timespec request = delay;
		struct timespec remaining;
		int fd = swapz_primary_mapper_device_open_once(
			mapper_name, expected_device, expected_bytes);

		if (fd >= 0)
			return fd;
		if (!swapz_primary_mapper_node_retryable_errno(errno) ||
		    attempt + 1U == SWAPZ_PRIMARY_MAPPER_NODE_RETRY_ATTEMPTS)
			return -1;
		while (nanosleep(&request, &remaining) < 0) {
			if (errno != EINTR)
				return -1;
			request = remaining;
		}
	}
	errno = EIO;
	return -1;
}

static int swapz_primary_proc_fd_path(int fd, char *path, size_t capacity)
{
	if (fd < 0 || !path || !capacity) {
		errno = EINVAL;
		return -1;
	}
	return swapz_primary_path_format(
		path, capacity, "/proc/self/fd/%d", fd);
}

static int swapz_primary_mkswap_open(void)
{
	struct stat path_info;
	struct stat opened_info;
	int fd;

	if (lstat(SWAPZ_PRIMARY_MKSWAP_PATH, &path_info) < 0)
		return -1;
	if (!S_ISREG(path_info.st_mode) || path_info.st_uid != 0U ||
	    path_info.st_nlink != 1U || (path_info.st_mode & 0022U) ||
	    !(path_info.st_mode & S_IXUSR)) {
		errno = EPERM;
		return -1;
	}
	fd = open(SWAPZ_PRIMARY_MKSWAP_PATH,
		  O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened_info) < 0 ||
	    lstat(SWAPZ_PRIMARY_MKSWAP_PATH, &path_info) < 0)
		goto failed;
	if (!S_ISREG(opened_info.st_mode) || opened_info.st_uid != 0U ||
	    opened_info.st_nlink != 1U || (opened_info.st_mode & 0022U) ||
	    !(opened_info.st_mode & S_IXUSR) ||
	    opened_info.st_dev != path_info.st_dev ||
	    opened_info.st_ino != path_info.st_ino || !S_ISREG(path_info.st_mode) ||
	    path_info.st_uid != 0U || path_info.st_nlink != 1U ||
	    (path_info.st_mode & 0022U) || !(path_info.st_mode & S_IXUSR)) {
		errno = EPERM;
		goto failed;
	}
	return fd;

failed:
	{
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
	}
	return -1;
}

static int swapz_primary_mkswap_output_open(void)
{
	struct stat output_info;
	int fd;

	fd = open("/dev/null", O_WRONLY | O_NOFOLLOW | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fd <= STDERR_FILENO) {
		int retained_fd = fcntl(fd, F_DUPFD_CLOEXEC,
					STDERR_FILENO + 1);

		if (retained_fd < 0)
			goto failed;
		if (close(fd) < 0) {
			int saved_errno = errno;

			(void)close(retained_fd);
			errno = saved_errno;
			return -1;
		}
		fd = retained_fd;
	}
	if (fstat(fd, &output_info) < 0)
		goto failed;
	if (!S_ISCHR(output_info.st_mode) ||
	    output_info.st_rdev != makedev(1U, 3U)) {
		errno = EPERM;
		goto failed;
	}
	return fd;

failed:
	{
		int saved_errno = errno;

		(void)close(fd);
		errno = saved_errno;
	}
	return -1;
}

static int swapz_primary_run_mkswap(int mkswap_fd, int mapper_fd)
{
	char mapper_path[64];
	char *const arguments[] = {
		(char *)"mkswap", (char *)"--", mapper_path, NULL,
	};
	char *const environment[] = {
		(char *)"LC_ALL=C", (char *)"PATH=/usr/sbin:/sbin", NULL,
	};
	pid_t child;
	int status;
	int output_fd;

	if (swapz_primary_proc_fd_path(
		    mapper_fd, mapper_path, sizeof(mapper_path)) < 0)
		return -1;
	output_fd = swapz_primary_mkswap_output_open();
	if (output_fd < 0)
		return -1;
	child = fork();
	if (child < 0) {
		int saved_errno = errno;

		(void)close(output_fd);
		errno = saved_errno;
		return -1;
	}
	if (child == 0) {
		int descriptor_flags = fcntl(mapper_fd, F_GETFD);

		if (dup2(output_fd, STDOUT_FILENO) < 0 ||
		    dup2(output_fd, STDERR_FILENO) < 0 ||
		    close(output_fd) < 0 ||
		    descriptor_flags < 0 ||
		    fcntl(mapper_fd, F_SETFD,
			  descriptor_flags & ~FD_CLOEXEC) < 0)
			_exit(126);
		fexecve(mkswap_fd, arguments, environment);
		_exit(127);
	}
	for (;;) {
		if (waitpid(child, &status, 0) >= 0)
			break;
		if (errno != EINTR) {
			int saved_errno = errno;

			(void)close(output_fd);
			errno = saved_errno;
			return -1;
		}
	}
	if (close(output_fd) < 0)
		return -1;
	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
		errno = EIO;
		return -1;
	}
	return 0;
}
#endif


#ifndef SWAPZ_PRIMARY_ROOTLESS_TEST
static int swapz_primary_native_swap_active(
	void *context, dev_t expected_device)
{
	(void)context;
	return swapz_primary_swap_device_active(expected_device);
}

static long swapz_primary_native_swapon(void *context, const char *mapper_path)
{
	const int swap_flags =
		SWAP_FLAG_DISCARD | SWAPZ_PRIMARY_SWAP_FLAG_DISCARD_PAGES;

	(void)context;
	return syscall(SYS_swapon, mapper_path, swap_flags);
}

static long swapz_primary_native_swapoff(void *context, const char *mapper_path)
{
	(void)context;
	return syscall(SYS_swapoff, mapper_path);
}

static const struct swapz_primary_swap_transition_ops
	swapz_primary_native_swap_transition_ops = {
	.device_active = swapz_primary_native_swap_active,
	.swapon = swapz_primary_native_swapon,
	.swapoff = swapz_primary_native_swapoff,
	.context = NULL,
};
#endif

static int swapz_primary_activate_mapper_swap(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	dev_t expected_mapper_device, int *activated_by_call)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	(void)expected_mapper_device;
	if (!activated_by_call) {
		errno = EINVAL;
		return -1;
	}
	*activated_by_call = 0;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage starting[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	char mapper_path[64];
	uint64_t logical_sectors = 0;
	uint64_t logical_bytes;
	dev_t observed_mapper_device = 0;
	int control_fd = -1;
	int mapper_fd = -1;
	int result = -1;
	int saved_errno = EIO;

	if (!manifest || expected_mapper_device == 0 || !activated_by_call) {
		errno = EINVAL;
		return -1;
	}
	*activated_by_call = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, starting,
		    sizeof(starting) / sizeof(starting[0]), 0) < 0 ||
	    swapz_primary_mapper_layout(
		    manifest, mapper_name, mapper_uuid, table,
		    &logical_sectors) < 0)
		return -1;
	if (!logical_sectors || logical_sectors > UINT64_MAX / 512ULL) {
		errno = EOVERFLOW;
		return -1;
	}
	logical_bytes = logical_sectors * 512ULL;

	control_fd = swapz_primary_dm_control_open();
	if (control_fd < 0 ||
	    swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 1,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device) {
		if (observed_mapper_device &&
		    observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}
	mapper_fd = swapz_primary_mapper_device_open(
		mapper_name, expected_mapper_device, logical_bytes);
	if (mapper_fd < 0 ||
	    swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device ||
	    swapz_primary_proc_fd_path(
		    mapper_fd, mapper_path, sizeof(mapper_path)) < 0) {
		if (observed_mapper_device &&
		    observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}

	/*
	 * The durable ACTIVE state is written by start_prepared only after this
	 * exact-dev_t inventory proof. A successful swapon return alone is not
	 * activation evidence, and EINTR is resolved only by the same proof.
	 */
	if (swapz_primary_swap_transition_apply(
		    1, expected_mapper_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    mapper_path, &swapz_primary_native_swap_transition_ops,
		    activated_by_call) < 0 || !*activated_by_call)
		goto out;
	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device) {
		if (observed_mapper_device &&
		    observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}

	*activated_by_call = 1;
	result = 0;
out:
	saved_errno = result == 0 ? 0 : (errno ? errno : EIO);
	if (mapper_fd >= 0 && close(mapper_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (control_fd >= 0 && close(control_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}

static int swapz_primary_deactivate_mapper_swap(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	int *deactivated_by_call)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	if (!deactivated_by_call) {
		errno = EINVAL;
		return -1;
	}
	*deactivated_by_call = 0;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage deactivation_stages[] = {
		SWAPZ_PRIMARY_STAGE_STOPPING,
		SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED,
		SWAPZ_PRIMARY_STAGE_RECOVERING,
	};
	struct dm_ioctl status;
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	char mapper_path[64];
	uint64_t logical_sectors = 0;
	uint64_t logical_bytes;
	dev_t mapper_device = 0;
	dev_t verified_mapper_device = 0;
	int control_fd = -1;
	int mapper_fd = -1;
	int mapper_active;
	int backing_active;
	int result = -1;
	int saved_errno = EIO;

	if (!manifest || !deactivated_by_call) {
		errno = EINVAL;
		return -1;
	}
	*deactivated_by_call = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, deactivation_stages,
		    sizeof(deactivation_stages) /
			    sizeof(deactivation_stages[0]), 0) < 0 ||
	    swapz_primary_mapper_layout(
		    manifest, mapper_name, mapper_uuid, table,
		    &logical_sectors) < 0)
		return -1;
	if (!logical_sectors || logical_sectors > UINT64_MAX / 512ULL) {
		errno = EOVERFLOW;
		return -1;
	}
	logical_bytes = logical_sectors * 512ULL;

	backing_active =
		swapz_primary_swap_device_active(SWAPZ_PRIMARY_TARGET_DEVICE);
	if (backing_active != 0) {
		if (backing_active > 0)
			errno = EBUSY;
		return -1;
	}

	control_fd = swapz_primary_dm_control_open();
	if (control_fd < 0)
		return -1;
	if (swapz_primary_dm_status_fd(
		    control_fd, mapper_name, mapper_uuid, &status) < 0) {
		if (errno != ENXIO ||
		    swapz_primary_dm_prove_mapper_absent(
			    control_fd, mapper_name, mapper_uuid) < 0)
			goto out;
		result = 0;
		goto out;
	}
	if (status.dev == 0U) {
		errno = EPROTO;
		goto out;
	}
	mapper_device = (dev_t)status.dev;
	if ((uint64_t)mapper_device != status.dev) {
		errno = EPROTO;
		goto out;
	}

	mapper_active = swapz_primary_swap_device_active(mapper_device);
	if (mapper_active < 0)
		goto out;
	if (!mapper_active) {
		result = 0;
		goto out;
	}

	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &verified_mapper_device) < 0 ||
	    verified_mapper_device != mapper_device) {
		if (verified_mapper_device &&
		    verified_mapper_device != mapper_device)
			errno = ESTALE;
		goto out;
	}
	mapper_fd = swapz_primary_mapper_device_open(
		mapper_name, mapper_device, logical_bytes);
	if (mapper_fd < 0 ||
	    swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &verified_mapper_device) < 0 ||
	    verified_mapper_device != mapper_device ||
	    swapz_primary_proc_fd_path(
		    mapper_fd, mapper_path, sizeof(mapper_path)) < 0) {
		if (verified_mapper_device &&
		    verified_mapper_device != mapper_device)
			errno = ESTALE;
		goto out;
	}

	/*
	 * Mapper removal is not a substitute for normal swapoff. This shared
	 * transition succeeds only after exact /proc/swaps absence is proved; an
	 * uncertain result stays recoverable and prevents the caller reaching DM
	 * removal.
	 */
	if (swapz_primary_swap_transition_apply(
		    0, mapper_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    mapper_path, &swapz_primary_native_swap_transition_ops,
		    deactivated_by_call) < 0)
		goto out;
	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &verified_mapper_device) < 0 ||
	    verified_mapper_device != mapper_device) {
		if (verified_mapper_device &&
		    verified_mapper_device != mapper_device)
			errno = ESTALE;
		goto out;
	}

	result = 0;
out:
	saved_errno = result == 0 ? 0 : (errno ? errno : EIO);
	if (mapper_fd >= 0 && close(mapper_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (control_fd >= 0 && close(control_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}

int swapz_primary_dm_create_mapper(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	int module_loaded_by_call, int *created_by_call,
	int *resumed_by_call, dev_t *mapper_device)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	(void)module_loaded_by_call;
	if (!created_by_call || !resumed_by_call || !mapper_device) {
		errno = EINVAL;
		return -1;
	}
	*created_by_call = 0;
	*resumed_by_call = 0;
	*mapper_device = 0;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage starting[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	struct swapz_primary_qualification qualification;
	struct dm_ioctl create;
	struct dm_ioctl resume;
	struct dm_ioctl *table_ioctl;
	_Alignas(struct dm_ioctl)
	unsigned char table_buffer[SWAPZ_PRIMARY_DM_BUFFER_BYTES];
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES];
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	char swapzctl_sha256[65];
	char module_sha256[65];
	char oracle_sha256[65];
	char module_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U];
	char parameter_path[PATH_MAX];
	char parameter_text[16];
	int module_loaded = 0;
	int mapper_present = 0;
	int module_clean = 0;
	int physical_enabled = 0;
	int package_module_fd = -1;
	int target_fd = -1;
	int control_fd = -1;
	int active_swap;
	int result = -1;
	int saved_errno;
	size_t table_bytes = 0;
	uint64_t logical_sectors;
	dev_t observed_mapper_device = 0;

	if (!created_by_call || !resumed_by_call || !mapper_device ||
	    !manifest || module_loaded_by_call != 1) {
		errno = EINVAL;
		return -1;
	}
	*created_by_call = 0;
	*resumed_by_call = 0;
	*mapper_device = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, starting,
		    sizeof(starting) / sizeof(starting[0]), 0) < 0)
		return -1;
	if (swapz_primary_read_qualification_report(&qualification) < 0 ||
	    strcmp(qualification.source_sha, manifest->source_sha) ||
	    strcmp(qualification.report_sha256,
		   manifest->qualification_report_sha256) ||
	    strcmp(qualification.formatter_sha256, manifest->swapzctl_sha256) ||
	    strcmp(qualification.module_sha256, manifest->module_sha256) ||
	    swapz_primary_live_artifact_hashes(
		    swapzctl_sha256, module_sha256, oracle_sha256,
		    qualification.module_sha256, &package_module_fd) < 0 ||
	    !swapz_primary_qualification_artifacts_match(
		    &qualification, swapzctl_sha256, module_sha256,
		    oracle_sha256)) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &mapper_present) < 0 || !module_loaded ||
	    mapper_present ||
	    swapz_primary_read_module_build_provenance(
		    module_loaded, module_source_sha, &module_clean) < 0 ||
	    !swapz_primary_build_sources_match(
		    manifest->source_sha, 1, module_source_sha, module_clean) ||
	    swapz_primary_path_format(
		    parameter_path, sizeof(parameter_path),
		    "/sys/module/dm_swapz/parameters/allow_physical_backing") < 0 ||
	    swapz_primary_read_sysfs_text(parameter_path, parameter_text,
				      sizeof(parameter_text)) < 0 ||
	    swapz_primary_parse_module_bool(parameter_text,
					    &physical_enabled) < 0 ||
	    !physical_enabled) {
		errno = EPERM;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(SWAPZ_PRIMARY_TARGET_DEVICE);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	if (swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		goto out;
	target_fd = swapz_primary_target_open_exclusive(manifest);
	if (target_fd < 0 ||
	    swapz_primary_exact_read(target_fd, header, sizeof(header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(header, manifest) < 0) {
		if (!errno)
			errno = EPERM;
		goto out;
	}
	if (close(target_fd) < 0) {
		target_fd = -1;
		goto out;
	}
	target_fd = -1;
	control_fd = swapz_primary_dm_control_open();
	if (control_fd < 0)
		goto out;
	if (swapz_primary_dm_ioctl_initialize(&create, sizeof(create),
					      mapper_name, mapper_uuid) < 0 ||
	    ioctl(control_fd, DM_DEV_CREATE, &create) < 0)
		goto out;
	*created_by_call = 1;
	if (create.dev == 0U ||
	    strnlen(create.name, sizeof(create.name)) == sizeof(create.name) ||
	    strnlen(create.uuid, sizeof(create.uuid)) == sizeof(create.uuid) ||
	    strcmp(create.name, mapper_name) || strcmp(create.uuid, mapper_uuid)) {
		errno = EPROTO;
		goto out;
	}
	*mapper_device = (dev_t)create.dev;
	if ((uint64_t)*mapper_device != create.dev ||
	    swapz_primary_dm_table_load_buffer(
		    manifest, table_buffer, sizeof(table_buffer), &table_bytes) < 0)
		goto out;
	table_ioctl = (struct dm_ioctl *)table_buffer;
	if (ioctl(control_fd, DM_TABLE_LOAD, table_ioctl) < 0)
		goto out;
	if (table_ioctl->flags & DM_BUFFER_FULL_FLAG) {
		errno = EOVERFLOW;
		goto out;
	}
	if (swapz_primary_dm_table_query_fd(control_fd, manifest, 1) < 0)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-mapper-inactive");
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    &resume, sizeof(resume), mapper_name, mapper_uuid) < 0 ||
	    ioctl(control_fd, DM_DEV_SUSPEND, &resume) < 0)
		goto out;
	*resumed_by_call = 1;
	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != *mapper_device) {
		if (observed_mapper_device != *mapper_device)
			errno = ESTALE;
		goto out;
	}
	result = 0;
out:
	saved_errno = errno;
	if (package_module_fd >= 0 && close(package_module_fd) < 0 &&
	    result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (target_fd >= 0 && close(target_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (control_fd >= 0 && close(control_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	errno = saved_errno;
	return result;
#endif
}

int swapz_primary_format_mapper_swap(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	dev_t expected_mapper_device)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	(void)expected_mapper_device;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage starting[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	unsigned char observed_backing_header[SWAPZ_PRIMARY_BLOCK_BYTES];
	unsigned char swap_header[SWAPZ_PRIMARY_BLOCK_BYTES];
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	uint64_t logical_sectors = 0;
	uint64_t logical_pages;
	uint64_t logical_bytes;
	dev_t observed_mapper_device = 0;
	int active_swap;
	int control_fd = -1;
	int target_fd = -1;
	int mapper_fd = -1;
	int mkswap_fd = -1;
	int result = -1;
	int saved_errno;

	if (!manifest || expected_mapper_device == 0) {
		errno = EINVAL;
		return -1;
	}
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, starting,
		    sizeof(starting) / sizeof(starting[0]), 0) < 0 ||
	    swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	if (!logical_sectors ||
	    logical_sectors % SWAPZ_PRIMARY_SECTORS_PER_PAGE ||
	    logical_sectors > UINT64_MAX / 512ULL) {
		errno = EINVAL;
		return -1;
	}
	logical_pages = logical_sectors / SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	logical_bytes = logical_sectors * 512ULL;
	if (logical_pages > UINT64_MAX / SWAPZ_PRIMARY_BLOCK_BYTES ||
	    logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES != logical_bytes) {
		errno = EOVERFLOW;
		return -1;
	}
	control_fd = swapz_primary_dm_control_open();
	if (control_fd < 0 ||
	    swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 1,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device) {
		if (observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(SWAPZ_PRIMARY_TARGET_DEVICE);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(expected_mapper_device);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	target_fd = swapz_primary_target_open_readonly();
	if (target_fd < 0 ||
	    swapz_primary_exact_read(target_fd, observed_backing_header,
				     sizeof(observed_backing_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_backing_header, manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	mapper_fd = swapz_primary_mapper_device_open(
		mapper_name, expected_mapper_device, logical_bytes);
	if (mapper_fd < 0)
		goto out;
	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device) {
		if (observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}
	mkswap_fd = swapz_primary_mkswap_open();
	if (mkswap_fd < 0 ||
	    swapz_primary_run_mkswap(mkswap_fd, mapper_fd) < 0)
		goto out;
	if (swapz_primary_dm_mapper_verify_fd(
		    control_fd, manifest, 1, 0,
		    &observed_mapper_device) < 0 ||
	    observed_mapper_device != expected_mapper_device) {
		if (observed_mapper_device != expected_mapper_device)
			errno = ESTALE;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(SWAPZ_PRIMARY_TARGET_DEVICE);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(expected_mapper_device);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	if (swapz_primary_exact_read(mapper_fd, swap_header,
				     sizeof(swap_header)) < 0 ||
	    !swapz_primary_linux_swap_header_valid(swap_header, logical_pages)) {
		if (!errno)
			errno = EBADMSG;
		goto out;
	}
	if (swapz_primary_exact_read(target_fd, observed_backing_header,
				     sizeof(observed_backing_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_backing_header, manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	result = 0;
out:
	saved_errno = errno;
	if (mkswap_fd >= 0 && close(mkswap_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (mapper_fd >= 0 && close(mapper_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (target_fd >= 0 && close(target_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	if (control_fd >= 0 && close(control_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	memset(observed_backing_header, 0, sizeof(observed_backing_header));
	memset(swap_header, 0, sizeof(swap_header));
	errno = saved_errno;
	return result;
#endif
}

int swapz_primary_dm_remove_mapper(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest,
	int *removed_by_call)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	if (!removed_by_call) {
		errno = EINVAL;
		return -1;
	}
	*removed_by_call = 0;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage removable_stages[] = {
		SWAPZ_PRIMARY_STAGE_STOPPING,
		SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED,
		SWAPZ_PRIMARY_STAGE_RECOVERING,
	};
	struct dm_ioctl observed;
	struct dm_ioctl remove;
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	uint32_t inactive_targets = 0;
	dev_t mapper_device = 0;
	int active_swap;
	int control_fd = -1;
	int result = -1;
	int saved_errno;
	uint64_t logical_sectors;

	if (!removed_by_call || !manifest) {
		errno = EINVAL;
		return -1;
	}
	*removed_by_call = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, removable_stages,
		    sizeof(removable_stages) / sizeof(removable_stages[0]), 0) < 0 ||
	    swapz_primary_mapper_layout(manifest, mapper_name, mapper_uuid,
					table, &logical_sectors) < 0)
		return -1;
	(void)logical_sectors;
	control_fd = swapz_primary_dm_control_open();
	if (control_fd < 0)
		return -1;
	if (swapz_primary_dm_status_fd(control_fd, mapper_name, mapper_uuid,
				       &observed) < 0) {
		if (errno != ENXIO ||
		    swapz_primary_dm_prove_mapper_absent(
			    control_fd, mapper_name, mapper_uuid) < 0)
			goto out;
		result = 0;
		goto out;
	}
	if (observed.dev == 0U || observed.open_count != 0 ||
	    (observed.flags & (DM_READONLY_FLAG | DM_INTERNAL_SUSPEND_FLAG |
			       DM_DEFERRED_REMOVE))) {
		errno = EBUSY;
		goto out;
	}
	mapper_device = (dev_t)observed.dev;
	if ((uint64_t)mapper_device != observed.dev) {
		errno = EPROTO;
		goto out;
	}
	active_swap = swapz_primary_swap_device_active(mapper_device);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	if (observed.flags & DM_ACTIVE_PRESENT_FLAG) {
		if (swapz_primary_dm_mapper_verify_fd(
			    control_fd, manifest, 0, 1,
			    &mapper_device) < 0 ||
		    swapz_primary_dm_inactive_target_count_fd(
		    control_fd, manifest, mapper_device,
		    &inactive_targets) < 0 ||
		    inactive_targets != 0U) {
			if (inactive_targets != 0U)
				errno = EPROTO;
			goto out;
		}
	} else {
		if (observed.target_count != 0U ||
		    swapz_primary_dm_inactive_target_count_fd(
		    control_fd, manifest, mapper_device,
		    &inactive_targets) < 0 ||
		    inactive_targets > 1U) {
			if (inactive_targets > 1U)
				errno = EPROTO;
			goto out;
		}
		if (inactive_targets == 1U) {
			if (swapz_primary_dm_table_query_fd(
				    control_fd, manifest, 1) < 0 ||
			    swapz_primary_dm_existing_mapper_ioctl_initialize(
				    &remove, sizeof(remove), mapper_name,
				    mapper_uuid) < 0 ||
			    ioctl(control_fd, DM_TABLE_CLEAR, &remove) < 0 ||
			    swapz_primary_dm_inactive_target_count_fd(
			    control_fd, manifest, mapper_device,
			    &inactive_targets) < 0 ||
			    inactive_targets != 0U) {
				if (inactive_targets != 0U)
					errno = EPROTO;
				goto out;
			}
		}
		if (swapz_primary_dm_status_fd(control_fd, mapper_name,
					       mapper_uuid, &observed) < 0 ||
		    observed.dev != (uint64_t)mapper_device ||
		    observed.open_count != 0 ||
		    (observed.flags & (DM_ACTIVE_PRESENT_FLAG |
				       DM_INTERNAL_SUSPEND_FLAG |
				       DM_DEFERRED_REMOVE)) ||
		    observed.target_count != 0U) {
			errno = EPROTO;
			goto out;
		}
	}
	active_swap = swapz_primary_swap_device_active(mapper_device);
	if (active_swap != 0) {
		if (active_swap > 0)
			errno = EBUSY;
		goto out;
	}
	if (swapz_primary_dm_existing_mapper_ioctl_initialize(
		    &remove, sizeof(remove), mapper_name, mapper_uuid) < 0 ||
	    ioctl(control_fd, DM_DEV_REMOVE, &remove) < 0)
		goto out;
	*removed_by_call = 1;
	if (swapz_primary_dm_prove_mapper_absent(
		    control_fd, mapper_name, mapper_uuid) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno;
	if (control_fd >= 0 && close(control_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	errno = saved_errno;
	return result;
#endif
}

static int swapz_primary_read_report_fd(
	int fd, uid_t expected_owner, int require_private,
	unsigned char **bytes_out, size_t *length_out, char digest_out[65])
{
	struct stat before;
	struct stat after;
	unsigned char *bytes = NULL;
	size_t length;
	size_t completed = 0;
	char digest[65];
	int flags;

	if (fd < 0 || !bytes_out || !length_out || !digest_out) {
		errno = EINVAL;
		return -1;
	}
	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		return -1;
	if ((flags & O_ACCMODE) != O_RDONLY) {
		errno = EBADF;
		return -1;
	}
	if (fstat(fd, &before) < 0)
		return -1;
	if (!S_ISREG(before.st_mode) ||
	    (expected_owner != (uid_t)-1 && before.st_uid != expected_owner) ||
	    before.st_nlink != 1U || (before.st_mode & 0022U) ||
	    before.st_size <= 0 ||
	    (uint64_t)before.st_size > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES ||
	    (require_private && (before.st_mode & 0777U) != 0600U)) {
		errno = EPERM;
		return -1;
	}
	length = (size_t)before.st_size;
	bytes = malloc(length);
	if (!bytes)
		return -1;
	while (completed < length) {
		ssize_t count = pread(fd, bytes + completed, length - completed,
				      (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		completed += (size_t)count;
	}
	{
		unsigned char extra;
		ssize_t count;

		do {
			count = pread(fd, &extra, sizeof(extra), (off_t)length);
		} while (count < 0 && errno == EINTR);
		if (count != 0) {
			if (count > 0)
				errno = EFBIG;
			goto failed;
		}
	}
	if (fstat(fd, &after) < 0)
		goto failed;
	if (before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
	    before.st_mode != after.st_mode || before.st_uid != after.st_uid ||
	    before.st_gid != after.st_gid || before.st_nlink != after.st_nlink ||
	    before.st_size != after.st_size ||
	    before.st_mtim.tv_sec != after.st_mtim.tv_sec ||
	    before.st_mtim.tv_nsec != after.st_mtim.tv_nsec ||
	    before.st_ctim.tv_sec != after.st_ctim.tv_sec ||
	    before.st_ctim.tv_nsec != after.st_ctim.tv_nsec) {
		errno = EIO;
		goto failed;
	}
	if (swapz_primary_sha256(bytes, length, digest) < 0)
		goto failed;
	*bytes_out = bytes;
	*length_out = length;
	memcpy(digest_out, digest, sizeof(digest));
	return 0;

failed:
	{
		int saved_errno = errno;

		free(bytes);
		errno = saved_errno;
		return -1;
	}
}

static int swapz_primary_read_report_at(
	int recovery_fd, const char *name, uid_t expected_owner,
	unsigned char **bytes_out, size_t *length_out, char digest_out[65])
{
	struct stat named;
	struct stat opened;
	int fd;
	int result;

	if (recovery_fd < 0 || !name || !bytes_out || !length_out ||
	    !digest_out) {
		errno = EINVAL;
		return -1;
	}
	if (fstatat(recovery_fd, name, &named, AT_SYMLINK_NOFOLLOW) < 0)
		return -1;
	fd = openat(recovery_fd, name,
		    O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened) < 0 || opened.st_dev != named.st_dev ||
	    opened.st_ino != named.st_ino) {
		int saved_errno = errno ? errno : ESTALE;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	result = swapz_primary_read_report_fd(fd, expected_owner, 1, bytes_out,
					     length_out, digest_out);
	{
		int saved_errno = errno;

		if (close(fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		errno = saved_errno;
	}
	return result;
}

static int swapz_primary_write_report_at(
	int recovery_fd, const char *name, const char *digest,
	const unsigned char *bytes, size_t length, uid_t expected_owner,
	int replace_existing)
{
	struct stat directory;
	struct stat temporary;
	struct stat named_temporary;
	struct stat opened_final;
	struct stat named_final;
	char temporary_name[192];
	char verified_digest[65];
	size_t written = 0;
	int fd = -1;
	int saved_errno = 0;
	int result = -1;
	int temporary_identity_valid = 0;
	int name_length;

	if (recovery_fd < 0 || !name || !swapz_primary_valid_sha256(digest) ||
	    !bytes || !length || length > SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES ||
	    (replace_existing != 0 && replace_existing != 1)) {
		errno = EINVAL;
		return -1;
	}
	if (fstat(recovery_fd, &directory) < 0)
		return -1;
	if (!S_ISDIR(directory.st_mode) || directory.st_uid != expected_owner ||
	    (directory.st_mode & 0777U) != 0700U) {
		errno = EPERM;
		return -1;
	}
	name_length = snprintf(temporary_name, sizeof(temporary_name),
			       ".%s.%s.tmp", name, digest);
	if (name_length < 0 || (size_t)name_length >= sizeof(temporary_name)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (fstatat(recovery_fd, temporary_name, &named_temporary,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	fd = openat(recovery_fd, temporary_name,
		    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (fstat(fd, &temporary) < 0)
		goto out;
	if (!S_ISREG(temporary.st_mode) ||
	    temporary.st_uid != expected_owner ||
	    (temporary.st_mode & 0777U) != 0600U || temporary.st_nlink != 1U ||
	    temporary.st_dev != directory.st_dev) {
		errno = EPERM;
		goto out;
	}
	temporary_identity_valid = 1;
	while (written < length) {
		ssize_t count = write(fd, bytes + written, length - written);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto out;
		}
		written += (size_t)count;
	}
	if (fsync(fd) < 0 || fstat(fd, &named_final) < 0 ||
	    fstatat(recovery_fd, temporary_name, &named_temporary,
		    AT_SYMLINK_NOFOLLOW) < 0)
		goto out;
	if (named_final.st_dev != temporary.st_dev ||
	    named_final.st_ino != temporary.st_ino ||
	    named_final.st_size != (off_t)length ||
	    !S_ISREG(named_final.st_mode) || named_final.st_uid != expected_owner ||
	    (named_final.st_mode & 0777U) != 0600U || named_final.st_nlink != 1U ||
	    named_temporary.st_dev != temporary.st_dev ||
	    named_temporary.st_ino != temporary.st_ino) {
		errno = EPERM;
		goto out;
	}
	if (close(fd) < 0) {
		fd = -1;
		goto out;
	}
	fd = -1;
	if (replace_existing) {
		if (renameat(recovery_fd, temporary_name, recovery_fd, name) < 0)
			goto out;
	} else if (renameat2(recovery_fd, temporary_name, recovery_fd, name,
			     RENAME_NOREPLACE) < 0) {
		goto out;
	}
	if (fsync(recovery_fd) < 0)
		goto out;
	fd = openat(recovery_fd, name,
		    O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
	if (fd < 0)
		goto out;
	if (fstat(fd, &opened_final) < 0 ||
	    swapz_primary_sha256_regular_fd(fd, expected_owner,
					    SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES,
					    verified_digest) < 0)
		goto out;
	if (strcmp(verified_digest, digest)) {
		errno = EBADMSG;
		goto out;
	}
	if (fstatat(recovery_fd, name, &named_final,
		    AT_SYMLINK_NOFOLLOW) < 0 ||
	    opened_final.st_dev != named_final.st_dev ||
	    opened_final.st_ino != named_final.st_ino ||
	    !S_ISREG(named_final.st_mode) ||
	    named_final.st_uid != expected_owner ||
	    (named_final.st_mode & 0777U) != 0600U ||
	    named_final.st_nlink != 1U) {
		errno = ESTALE;
		goto out;
	}
	result = 0;
	out:
	if (!result && close(fd) < 0) {
		result = -1;
		saved_errno = errno;
		fd = -1;
	}
	if (fd >= 0) {
		if (close(fd) < 0 && !saved_errno)
			saved_errno = errno;
		fd = -1;
	}
	if (result < 0) {
		if (!saved_errno)
			saved_errno = errno;
		if (temporary_identity_valid &&
		    fstatat(recovery_fd, temporary_name, &named_temporary,
			    AT_SYMLINK_NOFOLLOW) == 0 &&
		    named_temporary.st_dev == temporary.st_dev &&
		    named_temporary.st_ino == temporary.st_ino) {
			(void)unlinkat(recovery_fd, temporary_name, 0);
			(void)fsync(recovery_fd);
		}
		errno = saved_errno;
	}
	return result;
}

static int swapz_primary_qualification_report_store_at(
	int state_fd, int lock_fd, int report_fd, const unsigned char *bytes,
	size_t length, const char *digest, uid_t expected_owner)
{
	struct stat marker;
	struct swapz_primary_state state;
	unsigned char *old_bytes = NULL;
	char old_digest[65];
	char archive_name[112];
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char current_digest[65];
	char archive_digest[65];
	char active_name[96];
	unsigned char *archived_bytes = NULL;
	size_t old_length = 0;
	size_t archived_length = 0;
	size_t state_length = 0;
	int name_length;

	if (state_fd < 0 || lock_fd < 0 || report_fd < 0 || !bytes || !length ||
	    !swapz_primary_valid_sha256(digest) ||
	    !swapz_primary_partuuid_valid(SWAPZ_PRIMARY_PARTUUID) ||
	    !swapz_primary_state_lock_valid(state_fd, lock_fd,
					    expected_owner))
		return -1;
	name_length = snprintf(active_name, sizeof(active_name),
			       "partition-%s.active", SWAPZ_PRIMARY_PARTUUID);
	if (name_length < 0 || (size_t)name_length >= sizeof(active_name)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (fstatat(state_fd, active_name, &marker,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EBUSY;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	if (swapz_primary_record_read_at(
		    state_fd, "primary-state.json", expected_owner,
		    state_record, sizeof(state_record), &state_length, NULL) == 0) {
		if (swapz_primary_state_parse(state_record, state_length, &state) < 0 ||
		    state.stage != SWAPZ_PRIMARY_STAGE_COMPLETE) {
			errno = EBUSY;
			return -1;
		}
	} else if (errno != ENOENT) {
		return -1;
	}
	if (swapz_primary_sha256(bytes, length, current_digest) < 0 ||
	    strcmp(current_digest, digest)) {
		errno = EBADMSG;
		return -1;
	}
	if (swapz_primary_read_report_at(
		    report_fd, "primary-qualification.json", expected_owner,
		    &old_bytes, &old_length, old_digest) == 0) {
		if (old_length == length && !strcmp(old_digest, digest) &&
		    !memcmp(old_bytes, bytes, length)) {
			free(old_bytes);
			return 0;
		}
		name_length = snprintf(archive_name, sizeof(archive_name),
				       "primary-qualification-%s.json", old_digest);
		if (name_length < 0 || (size_t)name_length >= sizeof(archive_name)) {
			free(old_bytes);
			errno = ENAMETOOLONG;
			return -1;
		}
		if (swapz_primary_read_report_at(
			    report_fd, archive_name, expected_owner,
			    &archived_bytes, &archived_length, archive_digest) == 0) {
			int identical = archived_length == old_length &&
				!strcmp(archive_digest, old_digest) &&
				!memcmp(archived_bytes, old_bytes, old_length);

			free(archived_bytes);
			if (!identical) {
				free(old_bytes);
				errno = EBADMSG;
				return -1;
			}
		} else if (errno == ENOENT) {
			if (swapz_primary_write_report_at(
				    report_fd, archive_name, old_digest, old_bytes,
				    old_length, expected_owner, 0) < 0) {
				free(old_bytes);
				return -1;
			}
		} else {
			free(old_bytes);
			return -1;
		}
		free(old_bytes);
	} else if (errno != ENOENT) {
		return -1;
	}
	return swapz_primary_write_report_at(
		report_fd, "primary-qualification.json", digest, bytes,
		length, expected_owner, 1);
}

static int swapz_primary_qualification_import(const char *source_path)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)source_path;
	errno = ENODEV;
	return -1;
#else
	struct swapz_primary_qualification qualification;
	struct swapz_primary_target target = {0};
	unsigned char *bytes = NULL;
	char host_identity_sha256[65];
	char source_digest[65];
	char swapzctl_digest[65];
	char module_digest[65];
	char oracle_digest[65];
	int directory_safe = 0;
	int persistent_filesystem = 0;
	unsigned int filesystem_major = 0;
	unsigned int filesystem_minor = 0;
	int directly_not_target = 0;
	int source_chain_checked = 0;
	unsigned int parent_major = 0;
	unsigned int parent_minor = 0;
	int active_marker_clear = 0;
	size_t length = 0;
	int input_fd = -1;
	int recovery_fd = -1;
	int report_fd = -1;
	int lock_fd = -1;
	int result = -1;

	if (!source_path || !source_path[0] || geteuid() != 0 ||
	    SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_configured_target(&target) < 0)
		goto out;
	input_fd = open(source_path,
			O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
	if (input_fd < 0 ||
	    swapz_primary_read_report_fd(input_fd, (uid_t)-1, 0, &bytes,
					 &length, source_digest) < 0)
		goto out;
	if (close(input_fd) < 0) {
		input_fd = -1;
		goto out;
	}
	input_fd = -1;
	if (swapz_primary_live_host_identity_sha256(host_identity_sha256) < 0 ||
	    swapz_primary_qualification_parse_json(
		    bytes, length, SWAPZ_BUILD_SOURCE_SHA,
		    host_identity_sha256, &qualification) < 0 ||
	    swapz_primary_running_kernel_matches_qualification(&qualification) < 0 ||
	    strcmp(qualification.report_sha256, source_digest) ||
	    swapz_primary_live_artifact_hashes(
		    swapzctl_digest, module_digest, oracle_digest,
		    qualification.module_sha256, NULL) < 0 ||
	    !swapz_primary_qualification_artifacts_match(
		    &qualification, swapzctl_digest, module_digest,
		    oracle_digest)) {
		errno = EPERM;
		goto out;
	}
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		goto out;
	if (swapz_primary_recovery_preflight(
		    &directory_safe, &persistent_filesystem, &filesystem_major,
		    &filesystem_minor, &directly_not_target, &source_chain_checked,
		    &parent_major, &parent_minor, &active_marker_clear) < 0 ||
	    !directory_safe || !persistent_filesystem || !directly_not_target ||
	    !source_chain_checked || !active_marker_clear) {
		errno = EPERM;
		goto out;
	}
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, SWAPZ_PRIMARY_PARTUUID, 0);
	if (lock_fd < 0)
		goto out;
	report_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_QUALIFICATION_BASE, 0);
	if (report_fd < 0)
		goto out;
	if (swapz_primary_qualification_report_store_at(
		    recovery_fd, lock_fd, report_fd, bytes, length,
		    qualification.report_sha256, 0) < 0)
		goto out;
	result = 0;
out:
	{
		int saved_errno = errno;

		free(bytes);
		if (input_fd >= 0 && close(input_fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		if (lock_fd >= 0 && close(lock_fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		if (report_fd >= 0 && close(report_fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		if (recovery_fd >= 0 && close(recovery_fd) < 0 && result == 0) {
			result = -1;
			saved_errno = errno;
		}
		errno = saved_errno;
	}
	if (result == 0)
		printf("Installed primary qualification source=%s report_sha256=%s\n",
		       qualification.source_sha, qualification.report_sha256);
	return result;
#endif
}

static int swapz_primary_prepare_metadata(
	char *prepared_run_id, char *prepared_source_sha,
	uint64_t *prepared_logical_pages)
{
	if (!prepared_run_id || !prepared_source_sha ||
	    !prepared_logical_pages) {
		errno = EINVAL;
		return -1;
	}
	prepared_run_id[0] = '\0';
	prepared_source_sha[0] = '\0';
	*prepared_logical_pages = 0;
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENODEV;
	return -1;
#else
	struct swapz_primary_qualification qualification = {0};
	struct swapz_primary_mount_facts mount_facts = {0};
	struct swapz_primary_target target = {0};
	struct swapz_primary_target verified_target = {0};
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_manifest verified_manifest = {0};
	unsigned char original_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	unsigned char verified_current_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char live_swapzctl_sha256[65];
	char live_module_sha256[65];
	char live_oracle_sha256[65];
	char original_header_sha256[65];
	char shared_root_scope_sha256[65] = {0};
	char rechecked_root_scope_sha256[65] = {0};
	char run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U] = {0};
	uint64_t device_bytes = 0;
	uint64_t backing_physical_blocks = 0;
	uint64_t original_swap_size_kib = 0;
	dev_t target_parent = 0;
	dev_t root_parent = 0;
	int directory_safe = 0;
	int persistent_filesystem = 0;
	unsigned int recovery_filesystem_major = 0;
	unsigned int recovery_filesystem_minor = 0;
	int recovery_directly_not_target = 0;
	int recovery_source_chain_checked = 0;
	unsigned int recovery_parent_major = 0;
	unsigned int recovery_parent_minor = 0;
	int active_marker_clear = 0;
	int original_swap_header = 0;
	int original_header_digest_available = 0;
	int module_loaded = 0;
	int mapper_present = 0;
	int recovery_fd = -1;
	int lock_fd = -1;
	int claimed = 0;
	int shared_root_parent_required = 0;
	const char *failure_expected = NULL;
	const char *failure_observed = NULL;
	int result = -1;
	int saved_errno;
	const char *failure_phase = "identity-admission";

	if (geteuid() != 0 || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "configured-target-identity";
	if (swapz_primary_configured_target(&target) < 0)
		goto out;
	failure_phase = "recovery-directory-open";
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		goto out;
	failure_phase = "partition-lock-and-prior-claim";
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, SWAPZ_PRIMARY_PARTUUID, 0);
	if (lock_fd < 0)
		goto out;
	failure_phase = "prior-claim-reconciliation";
	if (swapz_primary_reconcile_metadata_claim_at(
		    recovery_fd, lock_fd, 0) < 0)
		goto out;
	if (swapz_primary_recovery_preflight(
		    &directory_safe, &persistent_filesystem,
		    &recovery_filesystem_major, &recovery_filesystem_minor,
		    &recovery_directly_not_target, &recovery_source_chain_checked,
		    &recovery_parent_major, &recovery_parent_minor,
		    &active_marker_clear) < 0) {
		failure_phase = "recovery-storage-inspection";
		goto out;
	}
	if (!directory_safe) {
		failure_phase = "recovery-directory-safety";
		errno = EPERM;
		goto out;
	}
	if (!persistent_filesystem) {
		failure_phase = "recovery-filesystem-persistence";
		errno = EPERM;
		goto out;
	}
	if (!recovery_directly_not_target) {
		failure_phase = "recovery-target-device-separation";
		errno = EPERM;
		goto out;
	}
	if (!recovery_source_chain_checked) {
		failure_phase = "recovery-physical-parent-identity";
		errno = EPERM;
		goto out;
	}
	if (!active_marker_clear) {
		failure_phase = "prior-active-marker";
		errno = EPERM;
		goto out;
	}
	failure_phase = "qualification-report-read";
	if (swapz_primary_read_qualification_report(&qualification) < 0)
		goto out;
	if (strcmp(qualification.source_sha, SWAPZ_BUILD_SOURCE_SHA)) {
		failure_phase = "qualification-source-identity";
		errno = EPERM;
		goto out;
	}
	failure_phase = "qualified-artifact-hash-readback";
	if (swapz_primary_live_artifact_hashes(
		    live_swapzctl_sha256, live_module_sha256,
		    live_oracle_sha256, qualification.module_sha256, NULL) < 0)
		goto out;
	if (!swapz_primary_qualification_artifacts_match(
		    &qualification, live_swapzctl_sha256, live_module_sha256,
		    live_oracle_sha256)) {
		failure_phase = "qualified-artifact-identity";
		errno = EPERM;
		goto out;
	}
	failure_phase = "target-header-inspection";
	if (swapz_primary_target_preflight(
		    target.partuuid, &target, &device_bytes, &original_swap_header,
		    &original_header_digest_available, original_header) < 0)
		goto out;
	if (device_bytes != target.device_bytes) {
		failure_phase = "target-geometry-identity";
		errno = EPERM;
		goto out;
	}
	if (!original_header_digest_available) {
		failure_phase = "original-header-identity-proof";
		errno = EPERM;
		goto out;
	}
	backing_physical_blocks = swapz_primary_physical_blocks_from_header(
		original_header, device_bytes);
	original_swap_size_kib = swapz_primary_swap_size_kib_from_header(
		original_header, device_bytes);
	if (!backing_physical_blocks || backing_physical_blocks > UINT32_MAX ||
	    !original_swap_size_kib) {
		failure_phase = "swapspace2-clean-segment-geometry";
		errno = EINVAL;
		goto out;
	}
	if (swapz_primary_sha256(original_header, sizeof(original_header),
			     original_header_sha256) < 0) {
		failure_phase = "original-header-digest";
		goto out;
	}
	failure_phase = "raw-target-swap-inventory";
	if (swapz_primary_original_swap_is_quiescent(original_swap_size_kib) < 0)
		goto out;
	failure_phase = "target-physical-parent-identity";
	if (!swapz_primary_recovery_source_chain(
		    "/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0, &target_parent)) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "cross-namespace-mount-inventory";
	if (swapz_primary_read_mount_facts(&mount_facts, target_parent) < 0)
		goto out;
	if (mount_facts.target_mounted) {
		failure_phase = "target-mounted-in-visible-namespace";
		errno = EPERM;
		goto out;
	}
	failure_phase = "root-device-parent-identity";
	if (!swapz_primary_root_source_chain(
		    "/sys", mount_facts.root_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    &root_parent)) {
		errno = EPERM;
		goto out;
	}
	shared_root_parent_required = target_parent == root_parent;
	if (shared_root_parent_required) {
		failure_phase = "shared-root-parent-authorization-record";
		if (swapz_primary_shared_root_scope_record_live(
			    &target, mount_facts.root_device, target_parent,
			    root_parent,
			    -1, shared_root_scope_sha256) < 0) {
			failure_expected = "exact-host-root-target-parent-layout-record";
			failure_observed = "missing-mismatched-or-unverifiable";
			goto out;
		}
	}
	failure_phase = "repeated-raw-target-swap-inventory";
	if (swapz_primary_original_swap_is_quiescent(original_swap_size_kib) < 0)
		goto out;
	failure_phase = "repeated-target-physical-parent-identity";
	if (!swapz_primary_recovery_source_chain(
		    "/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0, &target_parent)) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "repeated-cross-namespace-mount-inventory";
	if (swapz_primary_read_mount_facts(&mount_facts, target_parent) < 0)
		goto out;
	if (mount_facts.target_mounted) {
		failure_phase = "repeated-target-mounted-in-visible-namespace";
		errno = EPERM;
		goto out;
	}
	failure_phase = "repeated-root-device-parent-identity";
	if (!swapz_primary_root_source_chain(
		    "/sys", mount_facts.root_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    &root_parent)) {
		errno = EPERM;
		goto out;
	}
	if ((target_parent == root_parent) != shared_root_parent_required) {
		failure_phase = "repeated-root-parent-identity";
		errno = ESTALE;
		goto out;
	}
	if (shared_root_parent_required) {
		failure_phase = "repeated-shared-root-parent-authorization";
		if (swapz_primary_shared_root_scope_record_live(
			    &target, mount_facts.root_device, target_parent,
			    root_parent,
			    -1, rechecked_root_scope_sha256) < 0) {
			failure_expected = "unchanged-authorized-root-parent-scope";
			failure_observed = "missing-mismatched-or-changed";
			goto out;
		}
		if (strcmp(shared_root_scope_sha256,
			   rechecked_root_scope_sha256)) {
			errno = ESTALE;
			failure_expected = "unchanged-authorized-root-parent-scope";
			failure_observed = "scope-changed";
			goto out;
		}
	}
	{
		failure_phase = "physical-parent-swap-inventory";
		int parent_swap_active =
			swapz_primary_swap_device_active(target_parent);

		if (parent_swap_active != 0) {
			if (parent_swap_active > 0)
				errno = EBUSY;
			goto out;
		}
	}
	failure_phase = "module-mapper-inventory";
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &mapper_present) < 0)
		goto out;
	if (module_loaded || mapper_present) {
		failure_phase = "unexpected-module-or-mapper-present";
		errno = EBUSY;
		goto out;
	}
	failure_phase = "final-raw-target-swap-inventory";
	if (swapz_primary_original_swap_is_quiescent(original_swap_size_kib) < 0)
		goto out;
	{
		struct swapz_primary_mount_facts verified_mount_facts = {0};
		uint64_t verified_device_bytes = 0;
		int verified_swap_header = 0;
		int verified_header_digest_available = 0;
		int verified_directory_safe = 0;
		int verified_persistent_filesystem = 0;
		int verified_recovery_not_target = 0;
		int verified_recovery_chain = 0;
		int verified_active_marker_clear = 0;
		unsigned int verified_recovery_fs_major = 0;
		unsigned int verified_recovery_fs_minor = 0;
		unsigned int verified_recovery_parent_major = 0;
		unsigned int verified_recovery_parent_minor = 0;
		dev_t verified_target_parent = 0;
		dev_t verified_root_parent = 0;

		failure_phase = "final-preclaim-identity-revalidation";
		failure_expected = "unchanged-target-root-recovery-layout";
		failure_observed = "identity-changed-or-unverifiable";
		if (swapz_primary_target_preflight(
			    target.partuuid, &verified_target,
			    &verified_device_bytes, &verified_swap_header,
			    &verified_header_digest_available,
			    verified_current_header) < 0 ||
		    verified_device_bytes != device_bytes ||
		    !verified_header_digest_available ||
		    memcmp(&target, &verified_target, sizeof(target)) ||
		    memcmp(original_header, verified_current_header,
			   sizeof(original_header)) ||
		    !swapz_primary_recovery_source_chain(
			    "/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0,
			    &verified_target_parent) ||
		    verified_target_parent != target_parent ||
		    swapz_primary_read_mount_facts(
			    &verified_mount_facts, verified_target_parent) < 0 ||
		    verified_mount_facts.target_mounted ||
		    verified_mount_facts.root_device != mount_facts.root_device ||
		    !swapz_primary_root_source_chain(
			    "/sys", verified_mount_facts.root_device,
			    SWAPZ_PRIMARY_TARGET_DEVICE, &verified_root_parent) ||
		    verified_root_parent != root_parent ||
		    swapz_primary_recovery_preflight(
			    &verified_directory_safe,
			    &verified_persistent_filesystem,
			    &verified_recovery_fs_major,
			    &verified_recovery_fs_minor,
			    &verified_recovery_not_target,
			    &verified_recovery_chain,
			    &verified_recovery_parent_major,
			    &verified_recovery_parent_minor,
			    &verified_active_marker_clear) < 0 ||
		    !verified_directory_safe ||
		    !verified_persistent_filesystem ||
		    !verified_recovery_not_target || !verified_recovery_chain ||
		    !verified_active_marker_clear ||
		    verified_recovery_fs_major != recovery_filesystem_major ||
		    verified_recovery_fs_minor != recovery_filesystem_minor ||
		    verified_recovery_parent_major != recovery_parent_major ||
		    verified_recovery_parent_minor != recovery_parent_minor) {
			errno = ESTALE;
			goto out;
		}
		failure_expected = NULL;
		failure_observed = NULL;
		if ((verified_target_parent == verified_root_parent) !=
		    shared_root_parent_required) {
			failure_phase = "final-root-parent-identity-revalidation";
			failure_expected = "unchanged-root-target-parent-relationship";
			failure_observed = "parent-relationship-changed";
			errno = ESTALE;
			goto out;
		}
		if (shared_root_parent_required) {
			failure_phase = "final-shared-root-parent-authorization";
			if (swapz_primary_shared_root_scope_record_live(
				    &verified_target, verified_mount_facts.root_device,
				    verified_target_parent, verified_root_parent,
				    -1, rechecked_root_scope_sha256) < 0) {
				failure_expected =
					"unchanged-authorized-root-parent-scope";
				failure_observed =
					"missing-mismatched-or-changed";
				goto out;
			}
			if (strcmp(shared_root_scope_sha256,
				   rechecked_root_scope_sha256)) {
				errno = ESTALE;
				failure_expected =
					"unchanged-authorized-root-parent-scope";
				failure_observed = "scope-changed";
				goto out;
			}
		}
		failure_phase = "final-physical-parent-swap-inventory";
		{
			int verified_parent_swap_active =
				swapz_primary_swap_device_active(
					verified_target_parent);

			if (verified_parent_swap_active != 0) {
				if (verified_parent_swap_active > 0)
					errno = EBUSY;
				goto out;
			}
		}
	}
	failure_phase = "run-id-construction";
	if (swapz_primary_run_id_generate(run_id) < 0)
		goto out;
	manifest.target = target;
	manifest.backing_physical_blocks = (uint32_t)backing_physical_blocks;
	memcpy(manifest.run_id, run_id, sizeof(manifest.run_id));
	memcpy(manifest.source_sha, qualification.source_sha,
	       sizeof(manifest.source_sha));
	memcpy(manifest.swapzctl_sha256, qualification.formatter_sha256,
	       sizeof(manifest.swapzctl_sha256));
	memcpy(manifest.module_sha256, qualification.module_sha256,
	       sizeof(manifest.module_sha256));
	memcpy(manifest.qualification_report_sha256,
	       qualification.report_sha256,
	       sizeof(manifest.qualification_report_sha256));
	memcpy(manifest.original_header_sha256, original_header_sha256,
	       sizeof(manifest.original_header_sha256));
	failure_phase = "partition-owner-claim";
	if (swapz_primary_claim_partition_owner_at(
		    recovery_fd, lock_fd, run_id, 0) < 0)
		goto out;
	claimed = 1;
	failure_phase = "manifest-write";
	if (swapz_primary_manifest_write_at(
		    recovery_fd, lock_fd, &manifest, 0) < 0)
		goto out;
	failure_phase = "manifest-readback";
	if (swapz_primary_manifest_read_at(
		    recovery_fd, lock_fd, run_id, target.partuuid, 0,
		    &verified_manifest) < 0)
		goto out;
	if (!swapz_primary_manifest_equal(&manifest, &verified_manifest)) {
		errno = EBADMSG;
		goto out;
	}
	result = 0;
	out:
	saved_errno = errno ? errno : EIO;
	if (lock_fd >= 0 && close(lock_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
		failure_phase = "partition-lock-close";
	}
	if (recovery_fd >= 0 && close(recovery_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
		failure_phase = "recovery-directory-close";
	}
	memset(original_header, 0, sizeof(original_header));
	memset(verified_current_header, 0, sizeof(verified_current_header));
	if (result == 0) {
		memcpy(prepared_run_id, run_id, sizeof(run_id));
		memcpy(prepared_source_sha, manifest.source_sha,
		       sizeof(manifest.source_sha));
		*prepared_logical_pages = swapz_primary_maximum_logical_pages(
			manifest.backing_physical_blocks);
	}
	if (result < 0 && claimed)
		fprintf(stderr,
			"PRIMARY_PREPARE=FAILED phase=%s errno=%d error=%s "
			"claim=retained target_unchanged=true\n",
			failure_phase, saved_errno, strerror(saved_errno));
	else if (result < 0)
		fprintf(stderr,
			"PRIMARY_PREPARE=FAILED phase=%s errno=%d error=%s "
			"claim=none\n",
			failure_phase, saved_errno, strerror(saved_errno));
	if (result < 0 && failure_expected && failure_observed)
		fprintf(stderr,
			"PRIMARY_PREPARE=ADMISSION_DETAIL phase=%s expected=%s "
			"observed=%s errno=%d claim=%s target_unchanged=true\n",
			failure_phase, failure_expected, failure_observed,
			saved_errno, claimed ? "retained" : "none");
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}


static int swapz_primary_unload_owned_module(
	int recovery_fd, int lock_fd,
	const struct swapz_primary_manifest *manifest, int allow_intent,
	int *unloaded_by_call)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)recovery_fd;
	(void)lock_fd;
	(void)manifest;
	(void)allow_intent;
	if (!unloaded_by_call) {
		errno = EINVAL;
		return -1;
	}
	*unloaded_by_call = 0;
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage unload_stages[] = {
		SWAPZ_PRIMARY_STAGE_STOPPING,
		SWAPZ_PRIMARY_STAGE_RECOVERING,
	};
	char module_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U];
	char parameter_path[PATH_MAX];
	char parameter_text[16];
	int module_loaded = 0;
	int mapper_present = 0;
	int module_clean = 0;
	int physical_backing_enabled = 0;

	if (!manifest || !unloaded_by_call ||
	    (allow_intent != 0 && allow_intent != 1)) {
		errno = EINVAL;
		return -1;
	}
	*unloaded_by_call = 0;
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, manifest, unload_stages,
		    sizeof(unload_stages) / sizeof(unload_stages[0]), 0) < 0)
		return -1;
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &mapper_present) < 0)
		return -1;
	if (mapper_present) {
		errno = EBUSY;
		return -1;
	}
	/*
	 * A STARTING failure can precede the durable module-load INTENT. If no
	 * module exists there is nothing to adopt or unload. A live module always
	 * requires exact per-run WAL before recovery may touch it.
	 */
	if (!module_loaded)
		return 0;
	if (swapz_primary_module_load_record_matches_at(
		    recovery_fd, manifest, "LOADED", 0) < 0) {
		if (!allow_intent ||
		    swapz_primary_module_load_record_matches_at(
			    recovery_fd, manifest, "INTENT", 0) < 0)
			return -1;
	}
	if (swapz_primary_read_module_build_provenance(
		    module_loaded, module_source_sha, &module_clean) < 0 ||
	    !swapz_primary_build_sources_match(
		    manifest->source_sha, 1, module_source_sha, module_clean) ||
	    swapz_primary_path_format(
		    parameter_path, sizeof(parameter_path),
		    "/sys/module/dm_swapz/parameters/allow_physical_backing") < 0 ||
	    swapz_primary_read_sysfs_text(
		    parameter_path, parameter_text, sizeof(parameter_text)) < 0 ||
	    swapz_primary_parse_module_bool(
		    parameter_text, &physical_backing_enabled) < 0 ||
	    !physical_backing_enabled) {
		errno = EPERM;
		return -1;
	}
	if (syscall(SYS_delete_module, "dm_swapz", O_NONBLOCK) < 0)
		return -1;
	*unloaded_by_call = 1;
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &mapper_present) < 0 ||
	    module_loaded || mapper_present) {
		errno = EBUSY;
		return -1;
	}
	return 0;
#endif
}

/*
 * Failure-observation labels below are per-call stack evidence, not lifecycle
 * state. The partition lock serializes cooperative transaction ownership, but
 * the *_by_call outputs only say whether this invocation issued a mutation;
 * they are never proof that kernel state was observed. Mark OBSERVED only after
 * the corresponding helper returns with its independent proof complete. No
 * descriptor or observation ownership escapes these coordinator functions.
 */
static int swapz_primary_start_prepared(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage ready_stage[] = {
		SWAPZ_PRIMARY_STAGE_READY,
	};
	struct swapz_primary_qualification qualification = {0};
	struct swapz_primary_mount_facts mount_facts = {0};
	struct swapz_primary_target target = {0};
	struct swapz_primary_selector_admission selector_admission = {
		.directory_fd = -1, .selector_fd = -1
	};
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_state state = {0};
	struct swapz_primary_state starting_state = {0};
	struct swapz_primary_state active_state = {0};
	unsigned char observed_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char live_swapzctl_sha256[65];
	char live_module_sha256[65];
	char live_oracle_sha256[65];
	char shared_root_scope_sha256[65] = {0};
	char rechecked_root_scope_sha256[65] = {0};
	char prewrite_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U] = {0};
	size_t state_length = 0;
	dev_t target_parent = 0;
	dev_t root_parent = 0;
	dev_t mapper_device = 0;
	unsigned int recovery_filesystem_major = 0;
	unsigned int recovery_filesystem_minor = 0;
	unsigned int recovery_parent_major = 0;
	unsigned int recovery_parent_minor = 0;
	int recovery_directory_safe = 0;
	int recovery_persistent_filesystem = 0;
	int recovery_directly_not_target = 0;
	int recovery_source_chain_checked = 0;
	int recovery_active_marker_clear = 0;
	int module_loaded = 0;
	int mapper_present = 0;
	int module_loaded_by_call = 0;
	int mapper_created_by_call = 0;
	int mapper_resumed_by_call = 0;
	int swap_activated_by_call = 0;
	int target_swap_active;
	int shared_root_parent_required = 0;
	const char *failure_expected = NULL;
	const char *failure_observed = NULL;
	int recovery_fd = -1;
	int lock_fd = -1;
	int target_fd = -1;
	int starting_persisted = 0;
	int result = -1;
	int saved_errno = EIO;
	const char *failure_phase = "admission";
	const char *persistence_boundary = "none";
	const char *durable_observation = "UNOBSERVED";
	const char *mapper_observation = "UNOBSERVED";
	const char *swap_observation = "UNOBSERVED";

	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	failure_phase = "protected-selector-admission";
	failure_expected = "root-owned-unchanged-protected-selector";
	if (swapz_primary_selector_admission_open(&selector_admission) < 0) {
		failure_observed = "protected-selector-unverifiable";
		goto out;
	}
	if (swapz_primary_configured_target(&target) < 0)
		goto out;
	if (swapz_primary_selector_admission_still_live(
		&selector_admission, &failure_observed) < 0)
		goto out;
	failure_expected = NULL;
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		goto out;
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, target.partuuid, 0);
	if (lock_fd < 0)
		goto out;
	if (swapz_primary_record_read_at(
		    recovery_fd, "primary-state.json", 0, state_record,
		    sizeof(state_record), &state_length, NULL) < 0 ||
	    swapz_primary_state_parse(state_record, state_length, &state) < 0 ||
	    state.stage != SWAPZ_PRIMARY_STAGE_READY ||
	    state.has_recovery_previous_stage) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_manifest_read_at(
		    recovery_fd, lock_fd, state.run_id, target.partuuid, 0,
		    &manifest) < 0 ||
	    memcmp(&manifest.target, &target, sizeof(target)) ||
	    strcmp(manifest.source_sha, SWAPZ_BUILD_SOURCE_SHA) ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, &manifest, ready_stage,
		    sizeof(ready_stage) / sizeof(ready_stage[0]), 0) < 0) {
		errno = EPERM;
		goto out;
	}
	durable_observation = "OBSERVED";
	if (swapz_primary_read_qualification_report(&qualification) < 0 ||
	    strcmp(qualification.source_sha, manifest.source_sha) ||
	    strcmp(qualification.report_sha256,
		   manifest.qualification_report_sha256) ||
	    strcmp(qualification.formatter_sha256, manifest.swapzctl_sha256) ||
	    strcmp(qualification.module_sha256, manifest.module_sha256) ||
	    swapz_primary_live_artifact_hashes(
		    live_swapzctl_sha256, live_module_sha256,
		    live_oracle_sha256, qualification.module_sha256, NULL) < 0 ||
	    !swapz_primary_qualification_artifacts_match(
		    &qualification, live_swapzctl_sha256, live_module_sha256,
		    live_oracle_sha256)) {
		errno = EPERM;
		goto out;
	}
	if (swapz_primary_recovery_preflight(
		    &recovery_directory_safe, &recovery_persistent_filesystem,
		    &recovery_filesystem_major, &recovery_filesystem_minor,
		    &recovery_directly_not_target, &recovery_source_chain_checked,
		    &recovery_parent_major, &recovery_parent_minor,
		    &recovery_active_marker_clear) < 0 ||
	    !recovery_directory_safe || !recovery_persistent_filesystem ||
	    !recovery_directly_not_target || !recovery_source_chain_checked) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "target-physical-parent-identity";
	if (!swapz_primary_recovery_source_chain(
		    "/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0, &target_parent)) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "cross-namespace-mount-inventory";
	if (swapz_primary_read_mount_facts(&mount_facts, target_parent) < 0 ||
	    mount_facts.target_mounted) {
		errno = EPERM;
		goto out;
	}
	failure_phase = "root-device-parent-identity";
	if (!swapz_primary_root_source_chain(
		    "/sys", mount_facts.root_device, SWAPZ_PRIMARY_TARGET_DEVICE,
		    &root_parent)) {
		errno = EPERM;
		goto out;
	}
	shared_root_parent_required = target_parent == root_parent;
	if (shared_root_parent_required) {
		failure_phase = "shared-root-parent-authorization-record";
		if (swapz_primary_shared_root_scope_record_live(
			    &target, mount_facts.root_device, target_parent,
			    root_parent,
			    -1, shared_root_scope_sha256) < 0) {
			failure_expected = "exact-host-root-target-parent-layout-record";
			failure_observed = "missing-mismatched-or-unverifiable";
			goto out;
		}
	}
	failure_phase = "module-mapper-inventory";
	if (swapz_primary_read_module_mapper_inventory(
		    &module_loaded, &mapper_present) < 0 ||
	    module_loaded || mapper_present) {
		errno = EBUSY;
		goto out;
	}
	{
		int parent_swap_active =
			swapz_primary_swap_device_active(target_parent);

		failure_phase = "root-parent-swap-inventory";
		if (parent_swap_active != 0) {
			if (parent_swap_active > 0)
				errno = EBUSY;
			goto out;
		}
	}
	failure_phase = "target-swap-inventory";
	target_swap_active =
		swapz_primary_swap_device_active(SWAPZ_PRIMARY_TARGET_DEVICE);
	if (target_swap_active != 0) {
		if (target_swap_active > 0)
			errno = EBUSY;
		goto out;
	}
	failure_phase = "target-exclusive-open";
	target_fd = swapz_primary_target_open_exclusive(&manifest);
	if (target_fd < 0 ||
	    swapz_primary_exact_read(
		    target_fd, observed_header, sizeof(observed_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_header, &manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	starting_state = state;
	starting_state.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	failure_phase = "state-starting";
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &starting_state, 0) < 0)
		goto out;
	starting_persisted = 1;
	durable_observation = "OBSERVED";
	persistence_boundary = "none";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-starting");
	failure_phase = "module-load-intent";
	if (swapz_primary_module_load_intent_write_at(
		    recovery_fd, lock_fd, &manifest, 0) < 0)
		goto out;
	/*
	 * The admission snapshot predates this exclusive descriptor. Recheck the
	 * mount namespaces, physical-parent identity and swap inventory at the last
	 * boundary before creating the mapper, so a newly visible mount or swap is
	 * not mistaken for the earlier clear snapshot.
	 */
	{
		struct swapz_primary_mount_facts prewrite_mount_facts = {0};
		dev_t prewrite_target_parent = 0;
		dev_t prewrite_root_parent = 0;
		int active;

		if (!swapz_primary_recovery_source_chain(
			    "/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0,
			    &prewrite_target_parent))
			goto out;
		if (prewrite_target_parent != target_parent) {
			failure_phase = "prewrite-target-parent-identity";
			failure_expected = "unchanged-admitted-target-parent-device";
			failure_observed = "target-parent-device-changed";
			errno = ESTALE;
			goto out;
		}
		if (swapz_primary_read_mount_facts(
			    &prewrite_mount_facts, prewrite_target_parent) < 0)
			goto out;
		if (prewrite_mount_facts.target_mounted) {
			errno = EBUSY;
			goto out;
		}
		if (!swapz_primary_root_source_chain(
			    "/sys", prewrite_mount_facts.root_device,
			    SWAPZ_PRIMARY_TARGET_DEVICE, &prewrite_root_parent))
			goto out;
		if (prewrite_root_parent != root_parent) {
			failure_phase = "prewrite-root-parent-identity";
			failure_expected = "unchanged-admitted-root-parent-device";
			failure_observed = "root-parent-device-changed";
			errno = ESTALE;
			goto out;
		}
		if ((prewrite_target_parent == prewrite_root_parent) !=
		    shared_root_parent_required) {
			failure_phase = "prewrite-root-parent-identity";
			failure_expected = "unchanged-root-target-parent-relationship";
			failure_observed = "parent-relationship-changed";
			errno = ESTALE;
			goto out;
		}
		if (shared_root_parent_required) {
			failure_phase = "prewrite-shared-root-parent-authorization";
			if (swapz_primary_shared_root_scope_record_live(
				    &target, prewrite_mount_facts.root_device,
				    prewrite_target_parent, prewrite_root_parent, target_fd,
				    rechecked_root_scope_sha256) < 0) {
				failure_expected =
					"exact-opened-target-and-unchanged-root-scope";
				failure_observed =
					"missing-mismatched-or-unverifiable";
				goto out;
			}
			if (strcmp(shared_root_scope_sha256,
				   rechecked_root_scope_sha256)) {
				errno = ESTALE;
				failure_expected =
					"unchanged-authorized-root-parent-scope";
				failure_observed = "scope-changed";
				goto out;
			}
		}
		active = swapz_primary_swap_device_active(prewrite_target_parent);
		if (active != 0) {
			if (active > 0)
				errno = EBUSY;
			goto out;
		}
		active = swapz_primary_swap_device_active(
			SWAPZ_PRIMARY_TARGET_DEVICE);
		if (active != 0) {
			if (active > 0)
				errno = EBUSY;
			goto out;
		}
	}
	/*
	 * The last safe prewrite decision must still name the admitted protected
	 * selector inode, directory and partition geometry. Read-only validation
	 * cannot freeze privileged pathname or physical-parent changes afterwards.
	 */
	failure_phase = "prewrite-protected-selector-identity";
	failure_expected = "unchanged-admitted-selector-directory-and-file";
	if (swapz_primary_selector_admission_still_live(
		&selector_admission, &failure_observed) < 0)
		goto out;
	failure_expected = "manifest-target-matches-admitted-selector-content";
	if (swapz_primary_selector_admission_read_partuuid(
		    &selector_admission, prewrite_partuuid) < 0) {
		failure_observed = errno == ESTALE ?
			"admitted-selector-content-or-metadata-changed" :
			"admitted-selector-content-unverifiable";
		goto out;
	}
	if (strcmp(prewrite_partuuid, manifest.target.partuuid)) {
		failure_observed = "selected-target-not-bound-to-admitted-selector";
		errno = ESTALE;
		goto out;
	}
	failure_expected = "unchanged-admitted-selector-directory-and-file";
	if (swapz_primary_selector_admission_still_live(
		&selector_admission, &failure_observed) < 0)
		goto out;
	failure_phase = "prewrite-target-identity";
	failure_expected = "unchanged-admitted-target-partition-and-geometry";
	if (swapz_primary_target_revalidate(&manifest.target) < 0) {
		const int first_errno = errno ? errno : EIO;
		struct swapz_primary_target observed_target = {0};

		failure_observed = "target-identity-unverifiable";
		if (first_errno == ESTALE &&
		    swapz_primary_target_inspect(
			    manifest.target.partuuid, &observed_target) == 0) {
			if (observed_target.device_bytes != manifest.target.device_bytes)
				failure_observed = "target-geometry-changed";
			else if (observed_target.device_major !=
				 manifest.target.device_major ||
				 observed_target.device_minor !=
				 manifest.target.device_minor ||
				 strcmp(observed_target.partuuid,
					manifest.target.partuuid))
				failure_observed = "target-partition-identity-changed";
			else
				failure_observed = "target-identity-raced-or-restored";
		}
		errno = first_errno;
		goto out;
	}
	/*
	 * Target revalidation performs fresh pathname/sysfs inspection after the
	 * earlier selector proof. Recheck the admitted selector identity once more
	 * so a replacement during that inspection cannot become the last live
	 * authorization state before mapper creation. This remains a snapshot,
	 * not an atomic exclusion mechanism.
	 */
	failure_phase = "prewrite-protected-selector-identity";
	failure_expected = "unchanged-admitted-selector-directory-and-file";
	if (swapz_primary_selector_admission_still_live(
		&selector_admission, &failure_observed) < 0)
		goto out;
	failure_phase = "prewrite-selector-descriptor-close";
	failure_expected = "both-admitted-descriptors-closed";
	if (swapz_primary_selector_admission_close(&selector_admission) < 0) {
		failure_observed = "descriptor-close-failed";
		goto out;
	}
	failure_expected = NULL;
	failure_observed = NULL;
	failure_phase = "header-verify";
	/*
	 * Block zero is immutable. The raw partition stays a normal SWAPSPACE2
	 * partition while swapz owns only its post-header data area; mkswap is
	 * permitted only on the mapper created below.
	 */
	if (swapz_primary_exact_read(
		    target_fd, observed_header, sizeof(observed_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_header, &manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	if (close(target_fd) < 0) {
		target_fd = -1;
		goto out;
	}
	target_fd = -1;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-header-verified");
	failure_phase = "module-load";
	if (swapz_primary_load_qualified_module(&module_loaded_by_call) < 0 ||
	    module_loaded_by_call != 1)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-module-inserted");
	failure_phase = "module-wal";
	if (swapz_primary_module_load_mark_loaded_at(
		    recovery_fd, lock_fd, &manifest, 0) < 0)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-module-loaded");
	failure_phase = "mapper-create";
	mapper_observation = "UNCERTAIN";
	if (swapz_primary_dm_create_mapper(
		    recovery_fd, lock_fd, &manifest, module_loaded_by_call,
		    &mapper_created_by_call, &mapper_resumed_by_call,
		    &mapper_device) < 0 ||
	    !mapper_created_by_call || !mapper_resumed_by_call ||
	    mapper_device == 0)
		goto out;
	mapper_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-mapper-resumed");
	failure_phase = "mapper-format";
	if (swapz_primary_format_mapper_swap(
		    recovery_fd, lock_fd, &manifest, mapper_device) < 0)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-mkswap");
	failure_phase = "swapon";
	swap_observation = "UNCERTAIN";
	if (swapz_primary_activate_mapper_swap(
		    recovery_fd, lock_fd, &manifest, mapper_device,
		    &swap_activated_by_call) < 0 ||
	    !swap_activated_by_call)
		goto out;
	swap_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("start-swapon");
	failure_phase = "state-active";
	active_state = starting_state;
	active_state.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &active_state, 0) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno ? errno : EIO;
	if (swapz_primary_selector_admission_close(&selector_admission) < 0 &&
	    result == 0) {
		result = -1;
		saved_errno = errno;
		failure_phase = "protected-selector-descriptor-close";
		failure_expected = "both-admitted-descriptors-closed";
		failure_observed = "descriptor-close-failed";
	}
	errno = saved_errno;
	if (result < 0)
		fprintf(stderr,
			"PRIMARY_START=FAILED phase=%s errno=%d error=%s "
			"original_errno=%d persistence_boundary=%s "
			"durable=%s mapper=%s swap=%s\n",
			failure_phase, saved_errno, strerror(saved_errno),
			saved_errno, persistence_boundary, durable_observation,
			mapper_observation, swap_observation);
	if (result < 0 && failure_expected && failure_observed)
		fprintf(stderr,
			"PRIMARY_START=ADMISSION_DETAIL phase=%s expected=%s "
			"observed=%s errno=%d original_errno=%d "
			"persistence_boundary=%s durable=%s mapper=%s swap=%s "
			"retained_state=%s target_unchanged=true\n",
			failure_phase, failure_expected, failure_observed,
			saved_errno, saved_errno, persistence_boundary,
			durable_observation, mapper_observation, swap_observation,
			starting_persisted ?
				"STARTING_PENDING_RECOVERY_UPDATE" : "READY");
	if (result < 0 && starting_persisted && recovery_fd >= 0 &&
	    lock_fd >= 0)
		saved_errno = swapz_primary_require_recovery_preserving_errno(
			recovery_fd, lock_fd, state.run_id, 0, "START", saved_errno);
	if (target_fd >= 0)
		(void)close(target_fd);
	if (lock_fd >= 0)
		(void)close(lock_fd);
	if (recovery_fd >= 0)
		(void)close(recovery_fd);
	memset(observed_header, 0, sizeof(observed_header));
	memset(prewrite_partuuid, 0, sizeof(prewrite_partuuid));
	if (result == 0)
		printf("PRIMARY_START=ACTIVE run_id=%s mapper=/dev/mapper/swapz-primary "
		       "swapon=true\n", state.run_id);
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}


static int swapz_primary_state_recoverable(
	const struct swapz_primary_state *state)
{
	if (!swapz_primary_state_valid(state))
		return 0;
	switch (state->stage) {
	case SWAPZ_PRIMARY_STAGE_STARTING:
	case SWAPZ_PRIMARY_STAGE_ACTIVE:
	case SWAPZ_PRIMARY_STAGE_STOPPING:
	case SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED:
	case SWAPZ_PRIMARY_STAGE_RECOVERING:
	case SWAPZ_PRIMARY_STAGE_RESTORED:
		return 1;
	case SWAPZ_PRIMARY_STAGE_READY:
	case SWAPZ_PRIMARY_STAGE_DISABLING:
	case SWAPZ_PRIMARY_STAGE_COMPLETE:
	case SWAPZ_PRIMARY_STAGE_COUNT:
		return 0;
	}
	return 0;
}

static int swapz_primary_stop_active(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage active_stage[] = {
		SWAPZ_PRIMARY_STAGE_ACTIVE,
	};
	struct swapz_primary_target target = {0};
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_state state = {0};
	struct swapz_primary_state stopping_state = {0};
	struct swapz_primary_state restored_state = {0};
	struct swapz_primary_state complete_state = {0};
	unsigned char observed_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t state_length = 0;
	int recovery_fd = -1;
	int lock_fd = -1;
	int target_fd = -1;
	int mapper_removed_by_call = 0;
	int module_unloaded_by_call = 0;
	int swap_deactivated_by_call = 0;
	int stopping_persisted = 0;
	int complete_persisted = 0;
	int result = -1;
	int saved_errno = EIO;
	const char *failure_phase = "admission";
	const char *persistence_boundary = "none";
	const char *durable_observation = "UNOBSERVED";
	const char *mapper_observation = "UNOBSERVED";
	const char *swap_observation = "UNOBSERVED";

	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_configured_target(&target) < 0)
		goto out;
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		goto out;
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, target.partuuid, 0);
	if (lock_fd < 0)
		goto out;
	if (swapz_primary_record_read_at(
		    recovery_fd, "primary-state.json", 0, state_record,
		    sizeof(state_record), &state_length, NULL) < 0 ||
	    swapz_primary_state_parse(state_record, state_length, &state) < 0 ||
	    state.stage != SWAPZ_PRIMARY_STAGE_ACTIVE ||
	    state.has_recovery_previous_stage ||
	    swapz_primary_manifest_read_at(
		    recovery_fd, lock_fd, state.run_id, target.partuuid, 0,
		    &manifest) < 0 ||
	    memcmp(&manifest.target, &target, sizeof(target)) ||
	    strcmp(manifest.source_sha, SWAPZ_BUILD_SOURCE_SHA) ||
	    swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, &manifest, active_stage,
		    sizeof(active_stage) / sizeof(active_stage[0]), 0) < 0 ||
	    swapz_primary_module_load_record_matches_at(
		    recovery_fd, &manifest, "LOADED", 0) < 0) {
		errno = EPERM;
		goto out;
	}
	durable_observation = "OBSERVED";
	stopping_state = state;
	stopping_state.stage = SWAPZ_PRIMARY_STAGE_STOPPING;
	failure_phase = "state-stopping";
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &stopping_state, 0) < 0)
		goto out;
	stopping_persisted = 1;
	durable_observation = "OBSERVED";
	persistence_boundary = "none";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("stop-stopping");
	failure_phase = "swapoff";
	swap_observation = "UNCERTAIN";
	if (swapz_primary_deactivate_mapper_swap(
		    recovery_fd, lock_fd, &manifest,
		    &swap_deactivated_by_call) < 0)
		goto out;
	swap_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("stop-swapoff");
	failure_phase = "mapper-remove";
	mapper_observation = "UNCERTAIN";
	if (swapz_primary_dm_remove_mapper(
		    recovery_fd, lock_fd, &manifest, &mapper_removed_by_call) < 0)
		goto out;
	mapper_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("stop-mapper-removed");
	failure_phase = "module-unload";
	if (swapz_primary_unload_owned_module(
		    recovery_fd, lock_fd, &manifest, 0,
		    &module_unloaded_by_call) < 0)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("stop-module-unloaded");
	failure_phase = "header-verify";
	target_fd = swapz_primary_target_open_exclusive(&manifest);
	if (target_fd < 0 ||
	    swapz_primary_exact_read(
		    target_fd, observed_header, sizeof(observed_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_header, &manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	if (close(target_fd) < 0) {
		target_fd = -1;
		goto out;
	}
	target_fd = -1;
	failure_phase = "state-restored";
	restored_state = stopping_state;
	restored_state.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &restored_state, 0) < 0)
		goto out;
	durable_observation = "OBSERVED";
	persistence_boundary = "none";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("stop-restored");
	failure_phase = "state-complete";
	complete_state = restored_state;
	complete_state.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &complete_state, 0) < 0)
		goto out;
	complete_persisted = 1;
	durable_observation = "OBSERVED";
	failure_phase = "owner-release";
	persistence_boundary = "owner-unlink-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_release_partition_owner_at(
		    recovery_fd, lock_fd, manifest.run_id, 0) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno ? errno : EIO;
	if (result < 0)
		fprintf(stderr,
			"PRIMARY_STOP=FAILED phase=%s errno=%d error=%s "
			"original_errno=%d persistence_boundary=%s "
			"durable=%s mapper=%s swap=%s\n",
			failure_phase, saved_errno, strerror(saved_errno),
			saved_errno, persistence_boundary, durable_observation,
			mapper_observation, swap_observation);
	if (result < 0 && stopping_persisted && !complete_persisted &&
	    recovery_fd >= 0 && lock_fd >= 0)
		saved_errno = swapz_primary_require_recovery_preserving_errno(
			recovery_fd, lock_fd, state.run_id, 0, "STOP", saved_errno);
	if (target_fd >= 0)
		(void)close(target_fd);
	if (lock_fd >= 0)
		(void)close(lock_fd);
	if (recovery_fd >= 0)
		(void)close(recovery_fd);
	memset(observed_header, 0, sizeof(observed_header));
	if (result == 0)
		printf("PRIMARY_STOP=COMPLETE run_id=%s swapoff=%s "
		       "mapper_removed=%s module_unloaded=%s\n",
		       state.run_id,
		       swap_deactivated_by_call ? "true" : "false",
		       mapper_removed_by_call ? "true" : "false",
		       module_unloaded_by_call ? "true" : "false");
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}


static int swapz_primary_recover(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENODEV;
	return -1;
#else
	static const enum swapz_primary_stage recovery_required_stage[] = {
		SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED,
	};
	struct swapz_primary_target target = {0};
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_state state = {0};
	struct swapz_primary_state recovering_state = {0};
	struct swapz_primary_state restored_state = {0};
	struct swapz_primary_state complete_state = {0};
	unsigned char observed_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t state_length = 0;
	int recovery_fd = -1;
	int lock_fd = -1;
	int target_fd = -1;
	int mapper_removed_by_call = 0;
	int module_unloaded_by_call = 0;
	int swap_deactivated_by_call = 0;
	int recovering_persisted = 0;
	int complete_persisted = 0;
	int result = -1;
	int saved_errno = EIO;
	const char *failure_phase = "admission";
	const char *persistence_boundary = "none";
	const char *durable_observation = "UNOBSERVED";
	const char *mapper_observation = "UNOBSERVED";
	const char *swap_observation = "UNOBSERVED";

	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		errno = ENOTSUP;
		return -1;
	}
	if (geteuid() != 0 || SWAPZ_BUILD_SOURCE_CLEAN != 1 ||
	    !swapz_primary_valid_source_sha(SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		return -1;
	}
	if (swapz_primary_configured_target(&target) < 0)
		goto out;
	recovery_fd = swapz_primary_runtime_state_base_open(0);
	if (recovery_fd < 0)
		goto out;
	lock_fd = swapz_primary_partition_lock_at(
		recovery_fd, target.partuuid, 0);
	if (lock_fd < 0)
		goto out;
	if (swapz_primary_record_read_at(
		    recovery_fd, "primary-state.json", 0, state_record,
		    sizeof(state_record), &state_length, NULL) < 0 ||
	    swapz_primary_state_parse(state_record, state_length, &state) < 0 ||
	    !swapz_primary_state_recoverable(&state) ||
	    swapz_primary_manifest_read_at(
		    recovery_fd, lock_fd, state.run_id, target.partuuid, 0,
		    &manifest) < 0 ||
	    memcmp(&manifest.target, &target, sizeof(target)) ||
	    strcmp(manifest.source_sha, SWAPZ_BUILD_SOURCE_SHA)) {
		errno = EPERM;
		goto out;
	}
	durable_observation = "OBSERVED";

	/*
	 * The mapper may still own the backing partition, so pre-cleanup header
	 * inspection is read-only. The PARTUUID helper still revalidates the exact
	 * manifest-bound selected target before opening it.
	 */
	swapz_primary_selected_target = manifest.target;
	target_fd = swapz_primary_target_open_readonly();
	if (target_fd < 0 ||
	    swapz_primary_exact_read(
		    target_fd, observed_header, sizeof(observed_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_header, &manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	if (close(target_fd) < 0) {
		target_fd = -1;
		goto out;
	}
	target_fd = -1;
	failure_phase = "state-normalize";

	/*
	 * An abrupt process exit cannot write RECOVERY_REQUIRED for itself.
	 * Normalize every durable stage that may follow device mutation before
	 * cleanup, preserving any earlier recovery origin.
	 */
	if (state.stage != SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED) {
		struct swapz_primary_state recovery_required_state;

		if (swapz_primary_recovery_required_state(
			    &state, &recovery_required_state) < 0)
			goto out;
		persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
		durable_observation = "UNCERTAIN";
		if (swapz_primary_state_write_at(
			    recovery_fd, lock_fd, &recovery_required_state, 0) < 0)
			goto out;
		state = recovery_required_state;
		durable_observation = "OBSERVED";
		persistence_boundary = "none";
	}
	failure_phase = "state-recovering";
	if (swapz_primary_transaction_manifest_matches_at(
		    recovery_fd, lock_fd, &manifest, recovery_required_stage,
		    sizeof(recovery_required_stage) /
			    sizeof(recovery_required_stage[0]), 0) < 0)
		goto out;

	recovering_state = state;
	recovering_state.stage = SWAPZ_PRIMARY_STAGE_RECOVERING;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &recovering_state, 0) < 0)
		goto out;
	recovering_persisted = 1;
	durable_observation = "OBSERVED";
	persistence_boundary = "none";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("recover-recovering");

	failure_phase = "swapoff";
	swap_observation = "UNCERTAIN";
	if (swapz_primary_deactivate_mapper_swap(
		    recovery_fd, lock_fd, &manifest,
		    &swap_deactivated_by_call) < 0)
		goto out;
	swap_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("recover-swapoff");
	failure_phase = "mapper-remove";
	mapper_observation = "UNCERTAIN";
	if (swapz_primary_dm_remove_mapper(
		    recovery_fd, lock_fd, &manifest, &mapper_removed_by_call) < 0)
		goto out;
	mapper_observation = "OBSERVED";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("recover-mapper-removed");
	failure_phase = "module-unload";
	if (swapz_primary_unload_owned_module(
		    recovery_fd, lock_fd, &manifest, 1,
		    &module_unloaded_by_call) < 0)
		goto out;
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("recover-module-unloaded");
	failure_phase = "header-verify";

	/* After all holders are gone, prove the same known header through an
	 * exclusive manifest-bound descriptor before closing the transaction. */
	target_fd = swapz_primary_target_open_exclusive(&manifest);
	if (target_fd < 0 ||
	    swapz_primary_exact_read(
		    target_fd, observed_header, sizeof(observed_header)) < 0 ||
	    swapz_primary_backing_header_matches_manifest(
		    observed_header, &manifest) < 0) {
		if (!errno)
			errno = ESTALE;
		goto out;
	}
	if (close(target_fd) < 0) {
		target_fd = -1;
		goto out;
	}
	target_fd = -1;
	failure_phase = "state-restored";

	restored_state = recovering_state;
	restored_state.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &restored_state, 0) < 0)
		goto out;
	durable_observation = "OBSERVED";
	persistence_boundary = "none";
	SWAPZ_PRIMARY_TEST_INTERRUPT_AFTER("recover-restored");
	failure_phase = "state-complete";
	complete_state = restored_state;
	complete_state.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	persistence_boundary = "state-file-fsync-close-rename-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_state_write_at(
		    recovery_fd, lock_fd, &complete_state, 0) < 0)
		goto out;
	complete_persisted = 1;
	durable_observation = "OBSERVED";
	failure_phase = "owner-release";
	persistence_boundary = "owner-unlink-directory-fsync";
	durable_observation = "UNCERTAIN";
	if (swapz_primary_release_partition_owner_at(
		    recovery_fd, lock_fd, manifest.run_id, 0) < 0)
		goto out;
	result = 0;
out:
	saved_errno = errno ? errno : EIO;
	if (result < 0)
		fprintf(stderr,
			"PRIMARY_RECOVER=FAILED phase=%s errno=%d error=%s "
			"original_errno=%d persistence_boundary=%s "
			"durable=%s mapper=%s swap=%s\n",
			failure_phase, saved_errno, strerror(saved_errno),
			saved_errno, persistence_boundary, durable_observation,
			mapper_observation, swap_observation);
	if (result < 0 && recovering_persisted && !complete_persisted &&
	    recovery_fd >= 0 && lock_fd >= 0)
		saved_errno = swapz_primary_require_recovery_preserving_errno(
			recovery_fd, lock_fd, state.run_id, 0, "RECOVER", saved_errno);
	if (target_fd >= 0)
		(void)close(target_fd);
	if (lock_fd >= 0)
		(void)close(lock_fd);
	if (recovery_fd >= 0)
		(void)close(recovery_fd);
	memset(observed_header, 0, sizeof(observed_header));
	if (result == 0)
		printf("PRIMARY_RECOVER=COMPLETE run_id=%s swapoff=%s "
		       "mapper_removed=%s module_unloaded=%s\n",
		       state.run_id,
		       swap_deactivated_by_call ? "true" : "false",
		       mapper_removed_by_call ? "true" : "false",
		       module_unloaded_by_call ? "true" : "false");
	if (result < 0)
		errno = saved_errno;
	return result;
#endif
}

static int swapz_primary_read_only_plan(void)
{
	struct swapz_primary_swap_entry swaps[SWAPZ_PRIMARY_SWAP_ROWS_MAX];
	struct swapz_primary_swap_entry *target_swap = NULL;
	struct swapz_primary_target target = {0};
	unsigned char target_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char configured_partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U] = {0};
	uint64_t logical_pages = 0;
	uint64_t logical_bytes = 0;
	uint64_t linux_swap_kib = 0;
	uint64_t physical_blocks = 0;
	uint64_t target_swap_size_kib_expected = 0;
	uint64_t target_device_bytes = 0;
	swapz_u32 reserve_blocks = 0;
	size_t swap_count = 0;
	size_t target_count = 0;
	size_t i;
	int target_config_read = 0;
	int target_device_preflight = 0;
	int swaps_valid = 0;
	int single_target_swap = 0;
	int target_swap_size_ok = 0;
	int target_swap_zero_used = 0;
	int target_swap_priority_ok = 0;
	int original_swap_header = 0;
	int original_header_digest_available = 0;
	int recovery_preflight_read = 0;
	int recovery_directory_safe = 0;
	int recovery_persistent_filesystem = 0;
	unsigned int recovery_filesystem_major = 0;
	unsigned int recovery_filesystem_minor = 0;
	int recovery_directly_not_target = 0;
	int recovery_source_chain_checked = 0;
	unsigned int recovery_physical_parent_major = 0;
	unsigned int recovery_physical_parent_minor = 0;
	int recovery_active_marker_clear = 0;
	struct swapz_primary_mount_facts mount_facts = {0};
	int mount_inventory_read = 0;
	int target_not_mounted = 0;
	dev_t root_physical_parent = 0;
	dev_t target_physical_parent = 0;
	int target_device_chain_checked = 0;
	int recovery_same_physical_disk = 0;
	int root_mount_source_chain_checked = 0;
	int root_same_physical_disk = 0;
	int shared_root_parent_exception_required = 0;
	int shared_root_parent_exception_errno = 0;
	const char *shared_root_parent_exception_status = "not_required";
	char shared_root_scope_sha256[65] = "unavailable";
	int dm_swapz_module_loaded = 0;
	int swapz_mapper_present = 0;
	char module_build_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 8U] =
		"unavailable";
	int module_build_source_clean = 0;
	int module_mapper_inventory_read =
		swapz_primary_read_module_mapper_inventory(
			&dm_swapz_module_loaded, &swapz_mapper_present) == 0;
	int module_build_provenance_read = module_mapper_inventory_read &&
		swapz_primary_read_module_build_provenance(
			dm_swapz_module_loaded, module_build_source_sha,
			&module_build_source_clean) == 0;
	int control_module_source_matches = module_build_provenance_read &&
		swapz_primary_build_sources_match(
			SWAPZ_BUILD_SOURCE_SHA, SWAPZ_BUILD_SOURCE_CLEAN,
			module_build_source_sha, module_build_source_clean);
	struct swapz_primary_qualification qualification = {0};
	char live_swapzctl_sha256[65] = "unavailable";
	char live_module_sha256[65] = "unavailable";
	char live_oracle_sha256[65] = "unavailable";
	int qualification_report_valid =
		swapz_primary_read_qualification_report(&qualification) == 0;
	int qualification_source_matches_build = qualification_report_valid &&
		SWAPZ_BUILD_SOURCE_CLEAN == 1 &&
		!strcmp(qualification.source_sha, SWAPZ_BUILD_SOURCE_SHA);
	int live_artifact_hashes_read = qualification_report_valid &&
		swapz_primary_live_artifact_hashes(
			live_swapzctl_sha256, live_module_sha256,
			live_oracle_sha256, qualification.module_sha256, NULL) == 0;
	int live_artifacts_match_qualification = live_artifact_hashes_read &&
		swapz_primary_qualification_artifacts_match(
			&qualification, live_swapzctl_sha256, live_module_sha256,
			live_oracle_sha256);
	int privileged_execution_enabled =
		swapz_primary_privileged_execution_enabled();

	/* Each plan is a fresh identity decision; never report stale global target
	 * state if this process is reused after a failed selector read. */
	swapz_primary_selected_target_clear();
	target_config_read =
		swapz_primary_target_config_read(configured_partuuid) == 0;
	target_device_preflight = target_config_read &&
		swapz_primary_target_preflight(
			configured_partuuid, &target, &target_device_bytes,
			&original_swap_header,
			&original_header_digest_available, target_header) == 0;
	if (target_device_preflight) {
		physical_blocks = swapz_primary_physical_blocks_from_header(
			target_header, target.device_bytes);
		target_swap_size_kib_expected =
			swapz_primary_swap_size_kib_from_header(
				target_header, target.device_bytes);
		logical_pages =
			swapz_primary_maximum_logical_pages(physical_blocks);
		if (logical_pages && logical_pages <= UINT32_MAX &&
		    physical_blocks <= UINT32_MAX &&
		    swapz_authority_capacity_window(
			    (swapz_u32)logical_pages,
			    (swapz_u32)physical_blocks, &reserve_blocks)) {
			logical_bytes =
				logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES;
			linux_swap_kib =
				swapz_primary_linux_swap_size_kib(logical_pages);
		} else {
			/* An inconsistent sizing result is not reportable capacity. */
			logical_pages = 0;
		}
	}
	swaps_valid = swapz_primary_read_swap_inventory(
		swaps, SWAPZ_PRIMARY_SWAP_ROWS_MAX, &swap_count) == 0;
	recovery_preflight_read = swapz_primary_recovery_preflight(
		&recovery_directory_safe, &recovery_persistent_filesystem,
		&recovery_filesystem_major, &recovery_filesystem_minor,
		&recovery_directly_not_target, &recovery_source_chain_checked,
		&recovery_physical_parent_major, &recovery_physical_parent_minor,
		&recovery_active_marker_clear) == 0;
	target_device_chain_checked = target_device_preflight &&
		swapz_primary_recovery_source_chain(
			"/sys", SWAPZ_PRIMARY_TARGET_DEVICE, 0,
			&target_physical_parent);
	mount_inventory_read = target_device_chain_checked &&
		swapz_primary_read_mount_facts(
			&mount_facts, target_physical_parent) == 0;
	target_not_mounted = mount_inventory_read && !mount_facts.target_mounted;
	recovery_same_physical_disk = recovery_source_chain_checked &&
		target_device_chain_checked &&
		makedev(recovery_physical_parent_major,
			recovery_physical_parent_minor) == target_physical_parent;
	root_mount_source_chain_checked = mount_inventory_read &&
		target_device_chain_checked &&
		swapz_primary_root_source_chain(
			"/sys", mount_facts.root_device, SWAPZ_PRIMARY_TARGET_DEVICE,
			&root_physical_parent);
	root_same_physical_disk = root_mount_source_chain_checked &&
		root_physical_parent == target_physical_parent;
	shared_root_parent_exception_required = root_same_physical_disk;
	if (shared_root_parent_exception_required) {
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
		shared_root_parent_exception_status = "unavailable_in_rootless_test";
#else
		int scope_record_result = -1;
		int scope_errno = ENODATA;

		if (target_device_preflight && mount_inventory_read &&
		    recovery_source_chain_checked) {
			scope_record_result =
				swapz_primary_shared_root_scope_record_live(
					&target, mount_facts.root_device,
					target_physical_parent, root_physical_parent, -1,
					shared_root_scope_sha256);
			if (scope_record_result < 0)
				scope_errno = errno ? errno : ENODATA;
		}
		if (scope_record_result == 0) {
			shared_root_parent_exception_status = "valid";
		} else {
			shared_root_parent_exception_errno = scope_errno;
			shared_root_parent_exception_status =
				scope_errno == ENOENT ? "missing" :
				"invalid_or_unverifiable";
		}
#endif
	} else if (!root_mount_source_chain_checked) {
		shared_root_parent_exception_status = "root_identity_unavailable";
	}

	if (swaps_valid) {
		for (i = 0; i < swap_count; ++i) {
			struct stat info;

			if (target_device_preflight &&
			    stat(swaps[i].path, &info) == 0 && S_ISBLK(info.st_mode) &&
			    info.st_rdev == SWAPZ_PRIMARY_TARGET_DEVICE) {
				++target_count;
				target_swap = &swaps[i];
			}
		}
		single_target_swap = swap_count == 1U && target_count == 1U;
		if (target_swap) {
			target_swap_size_ok =
				target_swap_size_kib_expected &&
				target_swap->size_kib ==
					target_swap_size_kib_expected &&
				!strcmp(target_swap->type, "partition");
			target_swap_zero_used = target_swap->used_kib == 0ULL;
			target_swap_priority_ok =
				swapz_primary_swap_priority_restorable(
					target_swap->priority);
		}
	}

	printf("{\"schema\":\"swapz-primary-plan-v1\","
	       "\"status\":\"BLOCKED\","
	       "\"privileged_execution_enabled\":%s,"
	       "\"control_build_source_sha\":\"%s\","
	       "\"control_build_source_clean\":%s,"
	       "\"module_build_provenance_read\":%s,"
	       "\"module_build_source_sha\":\"%s\","
	       "\"module_build_source_clean\":%s,"
	       "\"control_module_source_matches\":%s,"
	       "\"qualification_report_valid\":%s,"
	       "\"qualification_source_matches_build\":%s,"
	       "\"qualification_report_sha256\":\"%s\","
	       "\"qualified_swapzctl_sha256\":\"%s\","
	       "\"qualified_module_sha256\":\"%s\","
	       "\"qualified_oracle_sha256\":\"%s\","
	       "\"live_artifact_hashes_read\":%s,"
	       "\"live_swapzctl_sha256\":\"%s\","
	       "\"live_module_sha256\":\"%s\","
	       "\"live_oracle_sha256\":\"%s\","
	       "\"live_artifacts_match_qualification\":%s,"
	       "\"live_device_gates_checked\":false,"
	       "\"target_config_read\":%s,"
	       "\"target_partuuid\":\"%s\","
	       "\"target_device_major\":%u,"
	       "\"target_device_minor\":%u,"
	       "\"target_device_preflight\":%s,"
	       "\"target_device_bytes\":%llu,"
	       "\"original_swap_signature\":%s,"
	       "\"target_block0_digest_available\":%s,"
	       "\"recovery_preflight_read\":%s,"
	       "\"recovery_directory_safe\":%s,"
	       "\"recovery_filesystem_supported\":%s,"
	       "\"recovery_filesystem_major\":%u,"
	       "\"recovery_filesystem_minor\":%u,"
	       "\"recovery_directly_not_target\":%s,"
	       "\"recovery_active_marker_clear\":%s,"
	       "\"recovery_source_chain_checked\":%s,"
	       "\"recovery_physical_parent_major\":%u,"
	       "\"recovery_physical_parent_minor\":%u,"
	       "\"recovery_same_physical_disk_as_target\":%s,"
	       "\"target_device_chain_checked\":%s,"
	       "\"target_physical_parent_major\":%u,"
	       "\"target_physical_parent_minor\":%u,"
	       "\"module_mapper_inventory_read\":%s,"
	       "\"dm_swapz_module_loaded\":%s,"
	       "\"swapz_mapper_absent\":%s,"
	       "\"mount_inventory_read\":%s,"
	       "\"target_not_mounted\":%s,"
	       "\"root_mount_device_major\":%u,"
	       "\"root_mount_device_minor\":%u,"
	       "\"root_mount_source_chain_checked\":%s,"
	       "\"root_same_physical_disk_as_target\":%s,"
	       "\"shared_root_parent_exception_required\":%s,"
	       "\"shared_root_parent_exception_status\":\"%s\","
	       "\"shared_root_parent_exception_errno\":%d,"
	       "\"shared_root_parent_scope_fingerprint\":\"%s\","
	       "\"swap_inventory_read\":%s,"
	       "\"active_swap_entries\":%llu,"
	       "\"target_swap_entries\":%llu,"
	       "\"single_target_swap_active\":%s,"
	       "\"target_swap_size_ok\":%s,"
	       "\"target_swap_zero_used\":%s,"
	       "\"target_swap_priority_ok\":%s,"
	       "\"logical_pages\":%llu,\"logical_bytes\":%llu,"
	       "\"linux_swap_kib\":%llu,\"gc_reserve_blocks\":%llu,"
	       "\"reason\":\"device_identity_recovery_and_lifecycle_gates_not_qualified\"}\n",
	       privileged_execution_enabled ? "true" : "false",
	       SWAPZ_BUILD_SOURCE_SHA,
	       SWAPZ_BUILD_SOURCE_CLEAN ? "true" : "false",
	       module_build_provenance_read ? "true" : "false",
	       module_build_source_sha,
	       module_build_provenance_read && module_build_source_clean ?
		       "true" : "false",
	       control_module_source_matches ? "true" : "false",
	       qualification_report_valid ? "true" : "false",
	       qualification_source_matches_build ? "true" : "false",
	       qualification_report_valid ? qualification.report_sha256 :
		       "unavailable",
	       qualification_report_valid ? qualification.formatter_sha256 :
		       "unavailable",
	       qualification_report_valid ? qualification.module_sha256 :
		       "unavailable",
	       qualification_report_valid ? qualification.oracle_sha256 :
		       "unavailable",
	       live_artifact_hashes_read ? "true" : "false",
	       live_swapzctl_sha256,
	       live_module_sha256,
	       live_oracle_sha256,
	       live_artifacts_match_qualification ? "true" : "false",
	       target_config_read ? "true" : "false",
	       target_config_read ? configured_partuuid : "",
	       target_device_preflight ? target.device_major : 0U,
	       target_device_preflight ? target.device_minor : 0U,
	       target_device_preflight ? "true" : "false",
	       (unsigned long long)target_device_bytes,
	       original_swap_header ? "true" : "false",
	       original_header_digest_available ? "true" : "false",
	       recovery_preflight_read ? "true" : "false",
	       recovery_directory_safe ? "true" : "false",
	       recovery_persistent_filesystem ? "true" : "false",
	       recovery_filesystem_major,
	       recovery_filesystem_minor,
	       recovery_directly_not_target ? "true" : "false",
	       recovery_active_marker_clear ? "true" : "false",
	       recovery_source_chain_checked ? "true" : "false",
	       recovery_physical_parent_major,
	       recovery_physical_parent_minor,
	       recovery_same_physical_disk ? "true" : "false",
	       target_device_chain_checked ? "true" : "false",
	       major(target_physical_parent),
	       minor(target_physical_parent),
	       module_mapper_inventory_read ? "true" : "false",
	       dm_swapz_module_loaded ? "true" : "false",
	       module_mapper_inventory_read && !swapz_mapper_present ?
		       "true" : "false",
	       mount_inventory_read ? "true" : "false",
	       target_not_mounted ? "true" : "false",
	       major(mount_facts.root_device),
	       minor(mount_facts.root_device),
	       root_mount_source_chain_checked ? "true" : "false",
	       root_same_physical_disk ? "true" : "false",
	       shared_root_parent_exception_required ? "true" : "false",
	       shared_root_parent_exception_status,
	       shared_root_parent_exception_errno,
	       shared_root_scope_sha256,
	       swaps_valid ? "true" : "false",
	       (unsigned long long)swap_count,
	       (unsigned long long)target_count,
	       single_target_swap ? "true" : "false",
	       target_swap_size_ok ? "true" : "false",
	       target_swap_zero_used ? "true" : "false",
	       target_swap_priority_ok ? "true" : "false",
	       (unsigned long long)logical_pages,
	       (unsigned long long)logical_bytes,
	       (unsigned long long)linux_swap_kib,
	       (unsigned long long)reserve_blocks);
	return 2;
}

enum swapz_primary_mutating_action {
	SWAPZ_PRIMARY_MUTATING_PREPARE,
	SWAPZ_PRIMARY_MUTATING_START,
	SWAPZ_PRIMARY_MUTATING_STOP,
	SWAPZ_PRIMARY_MUTATING_RECOVER,
};

static int swapz_primary_run_mutating_action(
	enum swapz_primary_mutating_action action)
{
	char prepared_run_id[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U] = {0};
	char prepared_source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH + 1U] = {0};
	uint64_t prepared_logical_pages = 0;
	int mutation_lock_fd;
	int result;
	int saved_errno;

	/*
	 * Lock order is global package/mutation lock first, then the partition
	 * recovery lock acquired by the selected lifecycle operation.
	 */
	mutation_lock_fd = swapz_primary_mutation_lock();
	if (mutation_lock_fd < 0) {
		if (action == SWAPZ_PRIMARY_MUTATING_PREPARE) {
			int failure_errno = errno ? errno : EIO;

			fprintf(stderr,
				"PRIMARY_PREPARE=FAILED phase=global-mutation-lock "
				"errno=%d error=%s\n",
				failure_errno, strerror(failure_errno));
			errno = failure_errno;
		}
		return -1;
	}
	/* The volatile flock survives no process crash; durable state must agree. */
	if ((action == SWAPZ_PRIMARY_MUTATING_PREPARE ||
	     action == SWAPZ_PRIMARY_MUTATING_START) &&
	    swapz_primary_package_transactions_clear_at(
		    SWAPZ_PRIMARY_PACKAGE_TRANSACTION_DIRECTORY, 0) < 0) {
		if (action == SWAPZ_PRIMARY_MUTATING_PREPARE ||
		    action == SWAPZ_PRIMARY_MUTATING_START) {
			int failure_errno = errno ? errno : EIO;
			const char *action_name =
				action == SWAPZ_PRIMARY_MUTATING_PREPARE ?
					"PRIMARY_PREPARE" : "PRIMARY_START";

			fprintf(stderr,
				"%s=FAILED phase=package-transaction-preflight "
				"errno=%d error=%s\n",
				action_name,
				failure_errno, strerror(failure_errno));
			errno = failure_errno;
		}
		result = -1;
		goto unlock;
	}
	switch (action) {
	case SWAPZ_PRIMARY_MUTATING_PREPARE:
		result = swapz_primary_prepare_metadata(
			prepared_run_id, prepared_source_sha,
			&prepared_logical_pages);
		break;
	case SWAPZ_PRIMARY_MUTATING_START:
		result = swapz_primary_start_prepared();
		break;
	case SWAPZ_PRIMARY_MUTATING_STOP:
		result = swapz_primary_stop_active();
		break;
	case SWAPZ_PRIMARY_MUTATING_RECOVER:
		result = swapz_primary_recover();
		break;
	default:
		errno = EINVAL;
		result = -1;
		break;
	}
unlock:
	saved_errno = errno;
	if (close(mutation_lock_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
		if (action == SWAPZ_PRIMARY_MUTATING_PREPARE) {
			fprintf(stderr,
				"PRIMARY_PREPARE=FAILED phase=global-mutation-lock-"
				"close claim=retained target_unchanged=true errno=%d "
				"error=%s\n",
				saved_errno, strerror(saved_errno));
		} else {
			const char *action_name =
				action == SWAPZ_PRIMARY_MUTATING_START ?
					"PRIMARY_START" :
				action == SWAPZ_PRIMARY_MUTATING_STOP ?
					"PRIMARY_STOP" : "PRIMARY_RECOVER";

			fprintf(stderr,
				"%s=FAILED phase=global-mutation-lock-close "
				"errno=%d error=%s\n",
				action_name, saved_errno, strerror(saved_errno));
		}
	}
	if (result == 0 && action == SWAPZ_PRIMARY_MUTATING_PREPARE)
		printf("PRIMARY_PREPARE=READY run_id=%s source=%s logical_pages=%llu "
		       "logical_bytes=%llu swap_kib=%llu\n",
		       prepared_run_id, prepared_source_sha,
		       (unsigned long long)prepared_logical_pages,
		       (unsigned long long)(prepared_logical_pages *
					    SWAPZ_PRIMARY_BLOCK_BYTES),
		       (unsigned long long)swapz_primary_linux_swap_size_kib(
			       prepared_logical_pages));
	errno = saved_errno;
	return result;
}

static int swapz_primary_qualification_import_serialized(
	const char *report_path)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	/*
	 * Rootless policy tests cannot touch the host package lock. The
	 * production and privileged qualification builds take the global lock
	 * below; rootless tests exercise the lock primitive independently.
	 */
	return swapz_primary_qualification_import(report_path);
#else
	int mutation_lock_fd;
	int result;
	int saved_errno;

	mutation_lock_fd = swapz_primary_mutation_lock();
	if (mutation_lock_fd < 0)
		return -1;
	result = swapz_primary_qualification_import(report_path);
	saved_errno = errno;
	if (close(mutation_lock_fd) < 0 && result == 0) {
		result = -1;
		saved_errno = errno;
	}
	errno = saved_errno;
	return result;
#endif
}

int swapz_primary_command(int argc, char **argv)
{
	if (argc == 1 && argv && argv[0] &&
	    !strcmp(argv[0], "systemd-units")) {
		char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
		char device_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
		char swap_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];

		if (swapz_primary_target_config_read(partuuid) < 0 ||
		    swapz_primary_systemd_target_units(partuuid, device_unit,
						       swap_unit) < 0) {
			fprintf(stderr,
				"BLOCKED: cannot derive target systemd units: %s\n",
				strerror(errno));
			return 2;
		}
		if (printf("%s %s\n", device_unit, swap_unit) < 0 ||
		    fflush(stdout) == EOF) {
			fprintf(stderr,
				"BLOCKED: cannot emit target systemd units: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	if (argc == 2 && argv && argv[0] && argv[1] &&
	    !strcmp(argv[0], "qualification-import")) {
		if (swapz_primary_qualification_import_serialized(argv[1]) < 0) {
			fprintf(stderr,
				"BLOCKED: qualification report import failed: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	if (argc != 1 || !argv || !argv[0]) {
		fputs("Usage: swapzctl primary plan|qualification-import <report>"
		      "|systemd-units|prepare|start|stop|recover\n",
		      stderr);
		return 2;
	}
	if (!strcmp(argv[0], "plan"))
		return swapz_primary_read_only_plan();
	if (strcmp(argv[0], "prepare") && strcmp(argv[0], "start") &&
	    strcmp(argv[0], "stop") && strcmp(argv[0], "recover")) {
		fputs("BLOCKED: unsupported primary-swap action\n", stderr);
		return 2;
	}
	if ((!strcmp(argv[0], "prepare") || !strcmp(argv[0], "start")) &&
	    !swapz_primary_privileged_execution_enabled()) {
		fputs("BLOCKED: primary-swap prepare/start remain disabled pending "
		      "current boot authorization\n", stderr);
		return 2;
	}
	if ((!strcmp(argv[0], "stop") || !strcmp(argv[0], "recover")) &&
	    !swapz_primary_cleanup_execution_enabled()) {
		fputs("BLOCKED: primary-swap cleanup authority is unavailable\n",
		      stderr);
		return 2;
	}
	if (!strcmp(argv[0], "prepare")) {
		if (swapz_primary_run_mutating_action(
			    SWAPZ_PRIMARY_MUTATING_PREPARE) < 0) {
			fprintf(stderr, "BLOCKED: primary-swap preparation failed: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	if (!strcmp(argv[0], "start")) {
		if (swapz_primary_run_mutating_action(
			    SWAPZ_PRIMARY_MUTATING_START) < 0) {
			fprintf(stderr, "BLOCKED: primary-swap start failed: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	if (!strcmp(argv[0], "stop")) {
		if (swapz_primary_run_mutating_action(
			    SWAPZ_PRIMARY_MUTATING_STOP) < 0) {
			fprintf(stderr, "BLOCKED: primary-swap stop failed: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	if (!strcmp(argv[0], "recover")) {
		if (swapz_primary_run_mutating_action(
			    SWAPZ_PRIMARY_MUTATING_RECOVER) < 0) {
			fprintf(stderr, "BLOCKED: primary-swap recovery failed: %s\n",
				strerror(errno));
			return 2;
		}
		return 0;
	}
	fputs("BLOCKED: unsupported primary-swap lifecycle action\n", stderr);
	return 2;
}
