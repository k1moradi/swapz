// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include "swapz-primary.h"
#include "../kernel/swapz-build-info.h"

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/fs.h>
#include <linux/magic.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/vfs.h>
#include <sys/utsname.h>
#include <unistd.h>

#include "../kernel/superblock.h"

#define SWAPZ_PRIMARY_BLOCK_BYTES 4096ULL
#define SWAPZ_PRIMARY_SEGMENT_BLOCKS 256ULL
#define SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS 512ULL
#define SWAPZ_PRIMARY_DEVICE_BYTES 17179869184ULL
#define SWAPZ_PRIMARY_SECTORS_PER_PAGE 8ULL
#define SWAPZ_PRIMARY_SWAP_SIZE_KIB 16777212ULL
#define SWAPZ_PRIMARY_DEVICE_PATH "/dev/sda4"
#define SWAPZ_PRIMARY_UUID_PATH \
	"/dev/disk/by-uuid/728b4c06-44b0-46ee-91ec-560ab1bad358"
#define SWAPZ_PRIMARY_PARTUUID_PATH "/dev/disk/by-partuuid/7fb9401d-04"
#define SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256 \
	"ace016a7a3ecd22b0aca05946a305aef2113bc50439452756ae68909010f0afe"
#define SWAPZ_PRIMARY_PLAN_BUFFER_BYTES 16384U
#define SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES 65536U
#define SWAPZ_PRIMARY_DM_MAPPERS_MAX 512U
#define SWAPZ_PRIMARY_SWAP_ROWS_MAX 32U
#define SWAPZ_PRIMARY_STATE_RECORD_MAX 4096U
#define SWAPZ_PRIMARY_HASH_FILE_MAX_BYTES (64ULL * 1024ULL * 1024ULL)
#define SWAPZ_PRIMARY_STATE_JSON_PREFIX \
	"{\"schema\":\"swapz-primary-state-v1\",\"run_id\":"
#define SWAPZ_PRIMARY_RECOVERY_BASE "/var/lib/swapz/physical-recovery"
#define SWAPZ_PRIMARY_QUALIFICATION_REPORT \
	"/var/lib/swapz/physical-recovery/primary-qualification.json"
#define SWAPZ_PRIMARY_PARTUUID "7fb9401d-04"
#define SWAPZ_PRIMARY_PHYSICAL_BLOCKS \
	(((SWAPZ_PRIMARY_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES - 1ULL) / \
	  SWAPZ_PRIMARY_SEGMENT_BLOCKS) * SWAPZ_PRIMARY_SEGMENT_BLOCKS)

/* Privileged lifecycle stays disabled until provisioning and recovery qualify. */
#define SWAPZ_PRIMARY_EXECUTION_ENABLED 0

struct swapz_primary_swap_entry {
	char path[PATH_MAX];
	char type[32];
	uint64_t size_kib;
	uint64_t used_kib;
	int priority;
};

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
	       !strcmp(manifest->original_header_sha256,
		       SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256);
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
	logical_pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	if (!logical_pages ||
	    logical_pages > UINT64_MAX / SWAPZ_PRIMARY_SECTORS_PER_PAGE) {
		errno = EOVERFLOW;
		return -1;
	}
	logical_sectors = logical_pages * SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	length = snprintf(mapper_name, sizeof(mapper_name),
			  "swapz-primary-%s", manifest->run_id);
	if (length < 0 || (size_t)length >= sizeof(mapper_name)) {
		errno = EOVERFLOW;
		return -1;
	}
	length = snprintf(mapper_uuid, sizeof(mapper_uuid),
			  "SWAPZ-PRIMARY-%s", manifest->run_id);
	if (length < 0 || (size_t)length >= sizeof(mapper_uuid)) {
		errno = EOVERFLOW;
		return -1;
	}
	length = snprintf(table, sizeof(table),
			  "0 %llu swapz 8:4 0 64 0 2 0 1 0 0",
			  (unsigned long long)logical_sectors);
	if (length < 0 || (size_t)length >= sizeof(table)) {
		errno = EOVERFLOW;
		return -1;
	}
	length = snprintf(record, capacity,
			  "schema=swapz-primary-manifest-v1\n"
			  "run_id=%s\n"
			  "source_sha=%s\n"
			  "swapzctl_sha256=%s\n"
			  "module_sha256=%s\n"
			  "qualification_report_sha256=%s\n"
			  "device_path=%s\n"
			  "device_major=8\n"
			  "device_minor=4\n"
			  "partuuid=%s\n"
			  "uuid_path=%s\n"
			  "partuuid_path=%s\n"
			  "device_bytes=%llu\n"
			  "original_header_sha256=%s\n"
			  "logical_pages=%llu\n"
			  "logical_sectors=%llu\n"
			  "mapper_name=%s\n"
			  "mapper_uuid=%s\n"
			  "dm_table=%s\n",
			  manifest->run_id, manifest->source_sha,
			  manifest->swapzctl_sha256, manifest->module_sha256,
			  manifest->qualification_report_sha256,
			  SWAPZ_PRIMARY_DEVICE_PATH, SWAPZ_PRIMARY_PARTUUID,
			  SWAPZ_PRIMARY_UUID_PATH, SWAPZ_PRIMARY_PARTUUID_PATH,
			  (unsigned long long)SWAPZ_PRIMARY_DEVICE_BYTES,
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
	const char *cursor = record;
	const char *end;
	uint64_t logical_pages;
	uint64_t logical_sectors;
	int formatted_length;
	int canonical_length;

	if (!record || !manifest || !length ||
	    length > SWAPZ_PRIMARY_STATE_RECORD_MAX ||
	    memchr(record, '\0', length))
		return -1;
	end = record + length;
	logical_pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	logical_sectors = logical_pages * SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	formatted_length = snprintf(expected, sizeof(expected), "%llu",
				     (unsigned long long)SWAPZ_PRIMARY_DEVICE_BYTES);
	if (formatted_length < 0 ||
	    (size_t)formatted_length >= sizeof(expected))
		return -1;
	if (swapz_primary_manifest_expect_line(&cursor, end, "schema",
					      "swapz-primary-manifest-v1") < 0 ||
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
	    swapz_primary_manifest_expect_line(&cursor, end, "device_path",
					      SWAPZ_PRIMARY_DEVICE_PATH) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "device_major",
					      "8") < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "device_minor",
					      "4") < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "partuuid",
					      SWAPZ_PRIMARY_PARTUUID) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "uuid_path",
					      SWAPZ_PRIMARY_UUID_PATH) < 0 ||
	    swapz_primary_manifest_expect_line(
		    &cursor, end, "partuuid_path", SWAPZ_PRIMARY_PARTUUID_PATH) < 0 ||
	    swapz_primary_manifest_expect_line(&cursor, end, "device_bytes",
					      expected) < 0 ||
	    swapz_primary_manifest_take_line(
		    &cursor, end, "original_header_sha256",
		    parsed.original_header_sha256,
		    sizeof(parsed.original_header_sha256)) < 0 ||
	    !swapz_primary_manifest_valid(&parsed) ||
	    swapz_primary_manifest_take_line(&cursor, end, "logical_pages",
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
	{
		char mapper_name[64];
		char mapper_uuid[64];

		if (snprintf(mapper_name, sizeof(mapper_name), "swapz-primary-%s",
			      parsed.run_id) < 0 ||
		    swapz_primary_manifest_expect_line(&cursor, end, "mapper_name",
						      mapper_name) < 0 ||
		    snprintf(mapper_uuid, sizeof(mapper_uuid), "SWAPZ-PRIMARY-%s",
			      parsed.run_id) < 0 ||
		    swapz_primary_manifest_expect_line(&cursor, end, "mapper_uuid",
						      mapper_uuid) < 0 ||
		    (formatted_length = snprintf(expected, sizeof(expected),
			     "0 %llu swapz 8:4 0 64 0 2 0 1 0 0",
			     (unsigned long long)logical_sectors)) < 0 ||
		    (size_t)formatted_length >= sizeof(expected) ||
		    swapz_primary_manifest_expect_line(
			    &cursor, end, "dm_table", expected) < 0)
			return -1;
	}
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
	return major(device) == 8U && minor(device) == 4U;
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

static int swapz_primary_open_target_checked_paths(const char *device_path,
						   const char *uuid_path,
						   const char *partuuid_path)
{
	struct stat device_before;
	struct stat uuid_before;
	struct stat partuuid_before;
	struct stat opened;
	struct stat device_after;
	struct stat uuid_after;
	struct stat partuuid_after;
	int fd;

	if (!device_path || !uuid_path || !partuuid_path) {
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
	fd = open(uuid_path, O_RDWR | O_EXCL | O_NONBLOCK | O_CLOEXEC);
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
		if (bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
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

int swapz_primary_target_open_exclusive(void)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	errno = ENOTSUP;
	return -1;
#else
	return swapz_primary_open_target_checked_paths(
		SWAPZ_PRIMARY_DEVICE_PATH, SWAPZ_PRIMARY_UUID_PATH,
		SWAPZ_PRIMARY_PARTUUID_PATH);
#endif
}

static int swapz_primary_original_swap_signature(
	const unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	static const unsigned char magic[] = "SWAPSPACE2";

	return !swapz_sb_valid(block, SWAPZ_PRIMARY_DEVICE_BYTES) &&
	       !memcmp(block + SWAPZ_PRIMARY_BLOCK_BYTES - sizeof(magic) + 1U,
		       magic, sizeof(magic) - 1U);
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

static int swapz_primary_header_fd_valid(int fd)
{
	struct stat info;
	int flags;

	if (fd < 0 || fstat(fd, &info) < 0)
		return 0;
	flags = fcntl(fd, F_GETFL);
	if (flags < 0)
		return 0;
	if ((flags & O_ACCMODE) != O_RDWR) {
		errno = EBADF;
		return 0;
	}
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	if (!S_ISREG(info.st_mode) ||
	    info.st_size < (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
		errno = ENODEV;
		return 0;
	}
#else
	{
		uint64_t bytes = 0;

		if (!S_ISBLK(info.st_mode) ||
		    !swapz_primary_device_number_matches(info.st_rdev)) {
			errno = EPERM;
			return 0;
		}
		if (ioctl(fd, BLKGETSIZE64, &bytes) < 0)
			return 0;
		if (bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
			errno = EINVAL;
			return 0;
		}
	}
#endif
	return 1;
}

int swapz_primary_write_header_checked_fd(
	int fd, const unsigned char expected_current[SWAPZ_PRIMARY_BLOCK_BYTES],
	const unsigned char replacement[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	unsigned char observed[SWAPZ_PRIMARY_BLOCK_BYTES];
	size_t completed = 0;

	if (!expected_current || !replacement) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_header_fd_valid(fd))
		return -1;
	if (swapz_primary_exact_read(fd, observed, sizeof(observed)) < 0)
		return -1;
	if (memcmp(observed, expected_current, sizeof(observed))) {
		errno = ESTALE;
		return -1;
	}
	while (completed < sizeof(observed)) {
		ssize_t count = pwrite(fd, replacement + completed,
				       sizeof(observed) - completed,
				       (off_t)completed);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			return -1;
		}
		completed += (size_t)count;
	}
	if (fsync(fd) < 0 || !swapz_primary_header_fd_valid(fd) ||
	    swapz_primary_exact_read(fd, observed, sizeof(observed)) < 0)
		return -1;
	if (memcmp(observed, replacement, sizeof(observed))) {
		errno = EIO;
		return -1;
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

static int swapz_primary_target_preflight(uint64_t *device_bytes,
						 int *original_swap_header,
						 int *original_header_hash_matches)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)device_bytes;
	(void)original_swap_header;
	(void)original_header_hash_matches;
	errno = ENODEV;
	return -1;
#else
	struct stat uuid_info;
	struct stat partuuid_info;
	struct stat device_info;
	struct stat opened_info;
	unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES];
	char digest[65];
	int fd;

	if (!device_bytes || !original_swap_header ||
	    !original_header_hash_matches) {
		errno = EINVAL;
		return -1;
	}
	*original_swap_header = 0;
	*original_header_hash_matches = 0;
	if (stat(SWAPZ_PRIMARY_UUID_PATH, &uuid_info) < 0 ||
	    stat(SWAPZ_PRIMARY_PARTUUID_PATH, &partuuid_info) < 0 ||
	    stat(SWAPZ_PRIMARY_DEVICE_PATH, &device_info) < 0)
		return -1;
	if (!S_ISBLK(uuid_info.st_mode) || !S_ISBLK(partuuid_info.st_mode) ||
	    !S_ISBLK(device_info.st_mode) ||
	    !swapz_primary_device_number_matches(uuid_info.st_rdev) ||
	    uuid_info.st_rdev != partuuid_info.st_rdev ||
	    uuid_info.st_rdev != device_info.st_rdev) {
		errno = ENODEV;
		return -1;
	}
	fd = open(SWAPZ_PRIMARY_UUID_PATH, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &opened_info) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (!S_ISBLK(opened_info.st_mode) ||
	    opened_info.st_rdev != uuid_info.st_rdev ||
	    !swapz_primary_device_number_matches(opened_info.st_rdev)) {
		close(fd);
		errno = ENODEV;
		return -1;
	}
	if (ioctl(fd, BLKGETSIZE64, device_bytes) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (*device_bytes != SWAPZ_PRIMARY_DEVICE_BYTES) {
		close(fd);
		errno = EINVAL;
		return -1;
	}
	if (swapz_primary_exact_read(fd, block, sizeof(block)) < 0) {
		int saved_errno = errno;

		close(fd);
		errno = saved_errno;
		return -1;
	}
	if (close(fd) < 0)
		return -1;
	*original_swap_header = swapz_primary_original_swap_signature(block);
	if (*original_swap_header &&
	    swapz_primary_sha256(block, sizeof(block), digest) == 0)
		*original_header_hash_matches =
			!strcmp(digest, SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256);
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

static int swapz_primary_valid_partuuid(const char *partuuid)
{
	size_t i;

	if (!partuuid || !partuuid[0] || strlen(partuuid) > 36U)
		return 0;
	for (i = 0; partuuid[i]; ++i) {
		unsigned char ch = (unsigned char)partuuid[i];

		if (!((ch >= '0' && ch <= '9') ||
		      (ch >= 'a' && ch <= 'f') ||
		      (ch >= 'A' && ch <= 'F') || ch == '-'))
			return 0;
	}
	return 1;
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

static int swapz_primary_persistent_fs_magic(long type)
{
	switch ((unsigned long)type) {
	case EXT2_SUPER_MAGIC:
	case XFS_SUPER_MAGIC:
	case F2FS_SUPER_MAGIC:
		return 1;
	default:
		return 0;
	}
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

struct swapz_primary_mount_facts {
	dev_t root_device;
	int root_mount_seen;
	int target_mounted;
};

static int swapz_primary_parse_mountinfo(const char *text,
					       dev_t target_device,
					       struct swapz_primary_mount_facts *facts)
{
	const char *line = text;
	struct swapz_primary_mount_facts parsed = {0};

	if (!text || !facts)
		return -1;
	while (*line) {
		char buffer[8192];
		char *fields[64];
		char *separator;
		size_t length;
		size_t field_count = 0;
		size_t i;
		size_t separator_index = SIZE_MAX;
		uint64_t mount_id;
		uint64_t parent_id;
		dev_t mounted_device;
		const char *end = strchr(line, '\n');

		length = end ? (size_t)(end - line) : strlen(line);
		if (!length || length >= sizeof(buffer))
			return -1;
		memcpy(buffer, line, length);
		buffer[length] = '\0';
		line = end ? end + 1 : line + length;
		separator = strstr(buffer, " - ");
		if (!separator || strstr(separator + 3, " - "))
			return -1;
		if (swapz_primary_split_fields(buffer, fields,
					      sizeof(fields) / sizeof(fields[0]),
					      &field_count) < 0 || field_count < 10U ||
		    swapz_primary_parse_u64(fields[0], &mount_id) < 0 ||
		    swapz_primary_parse_u64(fields[1], &parent_id) < 0 ||
		    !mount_id || !parent_id ||
		    swapz_primary_parse_dev_number(fields[2], &mounted_device) < 0 ||
		    !fields[3][0] || fields[4][0] != '/')
			return -1;
		for (i = 0; i < field_count; ++i) {
			if (strcmp(fields[i], "-"))
				continue;
			if (separator_index != SIZE_MAX)
				return -1;
			separator_index = i;
		}
		if (separator_index < 6U || separator_index + 3U >= field_count)
			return -1;
		if (mounted_device == target_device)
			parsed.target_mounted = 1;
		if (!strcmp(fields[4], "/")) {
			if (parsed.root_mount_seen)
				return -1;
			parsed.root_mount_seen = 1;
			parsed.root_device = mounted_device;
		}
	}
	if (!parsed.root_mount_seen)
		return -1;
	*facts = parsed;
	return 0;
}

static int swapz_primary_read_mount_facts(
	struct swapz_primary_mount_facts *facts)
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)facts;
	errno = ENODEV;
	return -1;
#else
	char buffer[SWAPZ_PRIMARY_MOUNTINFO_BUFFER_BYTES];
	size_t used = 0;
	int fd = open("/proc/self/mountinfo", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);

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
	return swapz_primary_parse_mountinfo(buffer, makedev(8U, 4U), facts);
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

	if (!sysfs_root || !physical_parent_device ||
	    (major(source_device) == 0U && minor(source_device) == 0U) ||
	    ((major(target_device) != 0U || minor(target_device) != 0U) &&
	     source_device == target_device)) {
		errno = EINVAL;
		return 0;
	}
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
	if (swapz_primary_path_format(device_path, sizeof(device_path),
				       "%s/device", parent_path) < 0 ||
	    lstat(device_path, &link_info) < 0 || !S_ISLNK(link_info.st_mode) ||
	    !realpath(device_path, device_realpath))
		goto rejected;
	if (strncmp(device_realpath, resolved_devices_root,
		    devices_root_length) ||
	    device_realpath[devices_root_length] != '/' ||
	    strstr(device_realpath, "/virtual/") != NULL)
		goto rejected;
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
	dev_t source_device;
	dev_t source_parent_device = 0;
	int recovery_fd;
	int marker_result;

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
	recovery_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RECOVERY_BASE, 0);
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
		swapz_primary_persistent_fs_magic(filesystem_info.f_type);
	*filesystem_major = major(directory_info.st_dev);
	*filesystem_minor = minor(directory_info.st_dev);
	*directly_not_target =
		(*filesystem_major != 0U || *filesystem_minor != 0U) &&
		!(*filesystem_major == 8U && *filesystem_minor == 4U);
	source_device = makedev(*filesystem_major, *filesystem_minor);
	if (*persistent_filesystem && *directly_not_target &&
	    swapz_primary_recovery_source_chain(
		    "/sys", source_device, makedev(8U, 4U),
		    &source_parent_device)) {
		*source_chain_checked = 1;
		*physical_parent_major = major(source_parent_device);
		*physical_parent_minor = minor(source_parent_device);
	}
	marker_result = fstatat(recovery_fd,
				"partition-7fb9401d-04.active", &marker_info,
				AT_SYMLINK_NOFOLLOW);
	if (marker_result < 0 && errno == ENOENT)
		*active_marker_clear = 1;
	if (close(recovery_fd) < 0)
		return -1;
	return 0;
#endif
}

static int swapz_primary_partition_lock_at(int recovery_fd,
						   const char *partuuid,
						   uid_t expected_owner)
{
	struct stat info;
	char name[64];
	int fd;

	if (recovery_fd < 0 || !swapz_primary_valid_partuuid(partuuid)) {
		errno = EINVAL;
		return -1;
	}
	if (snprintf(name, sizeof(name), "partition-%s.lock", partuuid) < 0 ||
	    strlen(name) >= sizeof(name)) {
		errno = ENAMETOOLONG;
		return -1;
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

	if (!run_id || strlen(run_id) != 32U)
		return 0;
	for (i = 0; i < 32U; ++i) {
		if (!((run_id[i] >= '0' && run_id[i] <= '9') ||
		      (run_id[i] >= 'a' && run_id[i] <= 'f')))
			return 0;
	}
	return 1;
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
	if (renameat(recovery_fd, temporary_name, recovery_fd, name) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (close(fd) < 0)
		return -1;
	return fsync(recovery_fd);

failed:
	if (fd >= 0) {
		struct stat named_info;

		if (temporary_identity_valid &&
		    fstatat(recovery_fd, temporary_name, &named_info,
			    AT_SYMLINK_NOFOLLOW) == 0 &&
		    named_info.st_dev == temporary_info.st_dev &&
		    named_info.st_ino == temporary_info.st_ino)
			(void)unlinkat(recovery_fd, temporary_name, 0);
		(void)close(fd);
	}
	errno = saved_errno;
	return -1;
}

int swapz_primary_claim_partition_owner_at(int recovery_fd, int lock_fd,
						  const char *run_id,
						  uid_t expected_owner)
{
	struct stat directory_info;
	struct stat held_lock_info;
	struct stat named_lock_info;
	struct stat marker_info;
	char lock_name[64];
	char active_name[64];
	char consumed_name[64];
	char record[192];
	int count;

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
	if (fstatat(recovery_fd, consumed_name, &marker_info,
		    AT_SYMLINK_NOFOLLOW) == 0) {
		errno = EEXIST;
		return -1;
	}
	if (errno != ENOENT)
		return -1;
	count = snprintf(record, sizeof(record),
			 "{\"major\":8,\"minor\":4,\"partuuid\":\"%s\","
			 "\"run_id\":\"%s\"}\n",
			 SWAPZ_PRIMARY_PARTUUID, run_id);
	if (count < 0 || (size_t)count >= sizeof(record)) {
		errno = EOVERFLOW;
		return -1;
	}
	if (swapz_primary_write_record_at(recovery_fd, consumed_name,
					  record, expected_owner) < 0)
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
	char lock_name[64];

	if (recovery_fd < 0 || lock_fd < 0 ||
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
	char active_name[64];
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
				   "{\"major\":8,\"minor\":4,"
				   "\"partuuid\":\"%s\",\"run_id\":\"%s\"}\n",
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
	int recovery_fd, int lock_fd, const char *run_id, uid_t expected_owner,
	struct swapz_primary_manifest *manifest)
{
	struct swapz_primary_manifest parsed;
	char name[96];
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	size_t length;

	if (recovery_fd < 0 || lock_fd < 0 || !manifest ||
	    swapz_primary_manifest_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, name, expected_owner,
					 record, sizeof(record), &length, NULL) < 0)
		return -1;
	if (swapz_primary_manifest_parse(record, length, &parsed) < 0) {
		errno = EBADMSG;
		return -1;
	}
	if (strcmp(parsed.run_id, run_id)) {
		errno = EPERM;
		return -1;
	}
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

static int swapz_primary_header_backup_name(const char *run_id,
						    char *name, size_t capacity)
{
	int length;

	if (!swapz_primary_valid_run_id(run_id) || !name || !capacity) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(name, capacity, "block0-%s.bin", run_id);
	if (length < 0 || (size_t)length >= capacity) {
		errno = ENAMETOOLONG;
		return -1;
	}
	return 0;
}

int swapz_primary_header_backup_read_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const char *expected_sha256, uid_t expected_owner,
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES])
{
	unsigned char saved[SWAPZ_PRIMARY_BLOCK_BYTES + 1U];
	char name[64];
	char digest[65];
	size_t length;

	if (recovery_fd < 0 || lock_fd < 0 || !header ||
	    !swapz_primary_valid_sha256(expected_sha256) ||
	    swapz_primary_header_backup_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_record_read_at(recovery_fd, name, expected_owner,
					 (char *)saved, sizeof(saved), &length,
					 NULL) < 0)
		return -1;
	if (length != SWAPZ_PRIMARY_BLOCK_BYTES ||
	    swapz_primary_sha256(saved, length, digest) < 0)
		return -1;
	if (strcmp(digest, expected_sha256)) {
		errno = EBADMSG;
		return -1;
	}
	memcpy(header, saved, SWAPZ_PRIMARY_BLOCK_BYTES);
	return 0;
}

int swapz_primary_header_backup_write_at(
	int recovery_fd, int lock_fd, const char *run_id,
	const unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES],
	const char *expected_sha256, uid_t expected_owner)
{
	struct stat directory_info;
	struct stat temporary_info;
	struct stat named_info;
	unsigned char verified[SWAPZ_PRIMARY_BLOCK_BYTES];
	char name[64];
	char temporary[96];
	char digest[65];
	int fd = -1;
	int temporary_identity_valid = 0;
	int saved_errno = 0;
	int length;
	size_t written = 0;

	if (recovery_fd < 0 || lock_fd < 0 || !header ||
	    !swapz_primary_valid_sha256(expected_sha256) ||
	    swapz_primary_header_backup_name(run_id, name, sizeof(name)) < 0) {
		errno = EINVAL;
		return -1;
	}
	if (!swapz_primary_state_lock_valid(recovery_fd, lock_fd,
					    expected_owner) ||
	    !swapz_primary_owner_claim_matches_at(recovery_fd, run_id,
						 expected_owner))
		return -1;
	if (swapz_primary_sha256(header, SWAPZ_PRIMARY_BLOCK_BYTES, digest) < 0)
		return -1;
	if (strcmp(digest, expected_sha256)) {
		errno = EBADMSG;
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
	length = snprintf(temporary, sizeof(temporary), ".%s.%s.tmp", name,
			  run_id);
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
	while (written < SWAPZ_PRIMARY_BLOCK_BYTES) {
		ssize_t count = write(fd, header + written,
				     SWAPZ_PRIMARY_BLOCK_BYTES - written);

		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0) {
			if (!count)
				errno = EIO;
			goto failed;
		}
		written += (size_t)count;
	}
	if (fsync(fd) < 0 ||
	    fstatat(recovery_fd, temporary, &named_info,
		    AT_SYMLINK_NOFOLLOW) < 0)
		goto failed;
	if (named_info.st_dev != temporary_info.st_dev ||
	    named_info.st_ino != temporary_info.st_ino ||
	    !S_ISREG(named_info.st_mode) ||
	    named_info.st_uid != expected_owner ||
	    (named_info.st_mode & 0777U) != 0600U ||
	    named_info.st_nlink != 1 ||
	    named_info.st_size != (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) {
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
		       RENAME_NOREPLACE) < 0) {
		saved_errno = errno;
		goto failed;
	}
	if (fsync(recovery_fd) < 0 ||
	    swapz_primary_header_backup_read_at(recovery_fd, lock_fd, run_id,
						expected_sha256, expected_owner,
						verified) < 0)
		return -1;
	if (memcmp(header, verified, sizeof(verified))) {
		errno = EIO;
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

	if (!swapz_primary_state_valid(next)) {
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
	if (swapz_primary_replace_record_at(recovery_fd, "primary-state.json",
					   next->run_id, next_record,
					   expected_owner) < 0)
		return -1;
	return 0;
}

int swapz_primary_release_partition_owner_at(int recovery_fd, int lock_fd,
						     const char *run_id,
						     uid_t expected_owner)
{
	struct swapz_primary_state state;
	struct stat active_info;
	struct stat named_info;
	char state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char active_name[64];
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
	if (snprintf(active_name, sizeof(active_name), "partition-%s.active",
		     SWAPZ_PRIMARY_PARTUUID) < 0)
		return -1;
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

int swapz_primary_partition_lock_acquire(void)
{
	uid_t expected_owner = 0;
	int recovery_fd;
	int lock_fd;
	int saved_errno;

	if (geteuid() != expected_owner) {
		errno = EPERM;
		return -1;
	}
	recovery_fd = swapz_primary_recovery_base_open(
		SWAPZ_PRIMARY_RECOVERY_BASE, expected_owner);
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
	uint64_t reserve;
	uint64_t data_blocks;

	reserve = (logical_pages + 7ULL) / 8ULL;
	if (reserve < SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS)
		reserve = SWAPZ_PRIMARY_MIN_RESERVE_BLOCKS;
	if (reserve >= physical_blocks)
		return 0;
	data_blocks = ((physical_blocks - reserve) /
		       SWAPZ_PRIMARY_SEGMENT_BLOCKS) *
		      SWAPZ_PRIMARY_SEGMENT_BLOCKS;
	return logical_pages <= data_blocks;
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
			if (*json->cursor++ != ',')
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
		if (*json->cursor++ != ',')
			return -1;
	}
	if (seen == 7U && !strcmp(schema, "swapz-host-v1") &&
	    !strcmp(architecture, "x86_64") &&
	    swapz_primary_valid_sha256(
		    qualification->host_identity_sha256))
		return 0;
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
		if (*json->cursor++ != ',')
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
		if (*json->cursor++ != ',')
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
		if (*json->cursor++ != ',')
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
		if (*json.cursor++ != ',')
			goto invalid;
	}
	swapz_primary_json_space(&json);
	if (json.cursor != json.end || seen != 255U ||
	    strcmp(schema, "swapz-test-results-v1") ||
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

static int swapz_primary_live_host_identity_sha256(char digest[65])
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)digest;
	errno = ENODEV;
	return -1;
#else
	static const unsigned char prefix[] = "swapz-host";
	unsigned char identity[sizeof(prefix) + 32U];
	char machine_id[64];
	struct stat before;
	struct stat after;
	struct utsname system;
	size_t length = 0;
	size_t i;
	int machine_id_nonzero = 0;
	int fd;

	if (!digest) {
		errno = EINVAL;
		return -1;
	}
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
	    strcmp(system.machine, "x86_64")) {
		errno = ENOTSUP;
		return -1;
	}
	if (length == 33U && machine_id[32] == '\n')
		length = 32U;
	if (length != 32U) {
		errno = EINVAL;
		return -1;
	}
	for (i = 0; i < 32U; ++i) {
		unsigned char byte = (unsigned char)machine_id[i];

		if (!isxdigit(byte)) {
			errno = EINVAL;
			return -1;
		}
		if (byte != '0')
			machine_id_nonzero = 1;
		identity[sizeof(prefix) + i] = (unsigned char)tolower(byte);
	}
	if (!machine_id_nonzero) {
		errno = EINVAL;
		return -1;
	}
	memcpy(identity, prefix, sizeof(prefix));
	return swapz_primary_sha256(identity, sizeof(identity), digest);
#endif
}

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
		    host_identity_sha256, qualification) < 0)
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
						     char oracle_sha256[65])
{
#ifdef SWAPZ_PRIMARY_ROOTLESS_TEST
	(void)swapzctl_sha256;
	(void)module_sha256;
	(void)oracle_sha256;
	errno = ENODEV;
	return -1;
#else
	static const char control_suffix[] = "/sbin/swapzctl";
	struct utsname system;
	char control_path[PATH_MAX];
	char oracle_path[PATH_MAX];
	char module_path[PATH_MAX];
	ssize_t control_length;
	int prefix_length;
	int length;

	if (!swapzctl_sha256 || !module_sha256 || !oracle_sha256) {
		errno = EINVAL;
		return -1;
	}
	control_length = readlink("/proc/self/exe", control_path,
				  sizeof(control_path) - 1U);
	if (control_length < 0)
		return -1;
	if ((size_t)control_length >= sizeof(control_path) - 1U) {
		errno = ENAMETOOLONG;
		return -1;
	}
	control_path[control_length] = '\0';
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
	if (uname(&system) < 0)
		return -1;
	if (!system.release[0] ||
	    strspn(system.release,
		   "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._+-") !=
		    strlen(system.release) || strstr(system.release, "..")) {
		errno = EINVAL;
		return -1;
	}
	length = snprintf(module_path, sizeof(module_path),
			  "/lib/modules/%s/updates/dkms/dm-swapz.ko",
			  system.release);
	if (length < 0 || (size_t)length >= sizeof(module_path)) {
		errno = ENAMETOOLONG;
		return -1;
	}
	if (swapz_primary_hash_regular_path("/proc/self/exe", 1,
					    swapzctl_sha256) < 0 ||
	    swapz_primary_hash_regular_path(module_path, 0, module_sha256) < 0 ||
	    swapz_primary_hash_regular_path(oracle_path, 0, oracle_sha256) < 0)
		return -1;
	return 0;
#endif
}

static int swapz_primary_read_only_plan(void)
{
	struct swapz_primary_swap_entry swaps[SWAPZ_PRIMARY_SWAP_ROWS_MAX];
	struct swapz_primary_swap_entry *target_swap = NULL;
	uint64_t logical_pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	uint64_t logical_bytes = logical_pages * SWAPZ_PRIMARY_BLOCK_BYTES;
	uint64_t reserve = (logical_pages + 7ULL) / 8ULL;
	uint64_t target_device_bytes = 0;
	size_t swap_count = 0;
	size_t target_count = 0;
	size_t i;
	int swaps_valid = swapz_primary_read_swap_inventory(
		swaps, SWAPZ_PRIMARY_SWAP_ROWS_MAX, &swap_count) == 0;
	int single_target_swap = 0;
	int target_swap_size_ok = 0;
	int target_swap_zero_used = 0;
	int target_swap_priority_ok = 0;
	int original_swap_header = 0;
	int original_header_hash_matches = 0;
	int target_device_preflight = swapz_primary_target_preflight(
		&target_device_bytes, &original_swap_header,
		&original_header_hash_matches) == 0;
	int recovery_directory_safe = 0;
	int recovery_persistent_filesystem = 0;
	unsigned int recovery_filesystem_major = 0;
	unsigned int recovery_filesystem_minor = 0;
	int recovery_directly_not_target = 0;
	int recovery_source_chain_checked = 0;
	unsigned int recovery_physical_parent_major = 0;
	unsigned int recovery_physical_parent_minor = 0;
	int recovery_active_marker_clear = 0;
	int recovery_preflight_read = swapz_primary_recovery_preflight(
		&recovery_directory_safe, &recovery_persistent_filesystem,
		&recovery_filesystem_major, &recovery_filesystem_minor,
		&recovery_directly_not_target, &recovery_source_chain_checked,
		&recovery_physical_parent_major,
		&recovery_physical_parent_minor,
		&recovery_active_marker_clear) == 0;
	struct swapz_primary_mount_facts mount_facts = {0};
	int mount_inventory_read = swapz_primary_read_mount_facts(&mount_facts) == 0;
	int target_not_mounted = mount_inventory_read &&
		!mount_facts.target_mounted;
	dev_t root_physical_parent = 0;
	dev_t target_physical_parent = 0;
	int target_device_chain_checked = target_device_preflight &&
		swapz_primary_recovery_source_chain(
			"/sys", makedev(8U, 4U), 0,
			&target_physical_parent);
	int recovery_same_physical_disk = recovery_source_chain_checked &&
		target_device_chain_checked &&
		makedev(recovery_physical_parent_major,
			recovery_physical_parent_minor) == target_physical_parent;
	int root_mount_source_chain_checked = mount_inventory_read &&
		target_device_chain_checked &&
		swapz_primary_recovery_source_chain(
			"/sys", mount_facts.root_device, makedev(8U, 4U),
			&root_physical_parent);
	int root_same_physical_disk = root_mount_source_chain_checked &&
		root_physical_parent == target_physical_parent;
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
			live_oracle_sha256) == 0;
	int live_artifacts_match_qualification = live_artifact_hashes_read &&
		swapz_primary_qualification_artifacts_match(
			&qualification, live_swapzctl_sha256, live_module_sha256,
			live_oracle_sha256);

	if (swaps_valid) {
		for (i = 0; i < swap_count; ++i) {
			struct stat info;

			if (stat(swaps[i].path, &info) == 0 && S_ISBLK(info.st_mode) &&
			    major(info.st_rdev) == 8U && minor(info.st_rdev) == 4U) {
				++target_count;
				target_swap = &swaps[i];
			}
		}
		single_target_swap = swap_count == 1U && target_count == 1U;
		if (target_swap) {
			target_swap_size_ok =
				target_swap->size_kib == SWAPZ_PRIMARY_SWAP_SIZE_KIB &&
				!strcmp(target_swap->type, "partition");
			target_swap_zero_used = target_swap->used_kib == 0ULL;
			target_swap_priority_ok = target_swap->priority == -1;
		}
	}

	printf("{\"schema\":\"swapz-primary-plan-v1\","
	       "\"status\":\"BLOCKED\","
	       "\"privileged_execution_enabled\":false,"
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
	       "\"target_device_preflight\":%s,"
	       "\"target_device_bytes\":%llu,"
	       "\"original_swap_signature\":%s,"
	       "\"original_header_hash_matches\":%s,"
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
	       target_device_preflight ? "true" : "false",
	       (unsigned long long)target_device_bytes,
	       original_swap_header ? "true" : "false",
	       original_header_hash_matches ? "true" : "false",
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
	       swaps_valid ? "true" : "false",
	       (unsigned long long)swap_count,
	       (unsigned long long)target_count,
	       single_target_swap ? "true" : "false",
	       target_swap_size_ok ? "true" : "false",
	       target_swap_zero_used ? "true" : "false",
	       target_swap_priority_ok ? "true" : "false",
	       (unsigned long long)logical_pages,
	       (unsigned long long)logical_bytes,
	       (unsigned long long)(logical_bytes / 1024ULL - 4ULL),
	       (unsigned long long)reserve);
	return 2;
}

int swapz_primary_command(int argc, char **argv)
{
	if (argc != 1 || !argv || !argv[0]) {
		fputs("Usage: swapzctl primary plan|prepare|start|stop|recover\n",
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
	if (!SWAPZ_PRIMARY_EXECUTION_ENABLED) {
		fputs("BLOCKED: primary-swap provisioning, activation, teardown and "
		      "recovery remain disabled pending qualification\n", stderr);
		return 2;
	}
	fputs("BLOCKED: primary-swap lifecycle action is not implemented\n", stderr);
	return 2;
}
