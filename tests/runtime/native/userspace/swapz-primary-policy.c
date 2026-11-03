// SPDX-License-Identifier: GPL-2.0-only
#define SWAPZ_PRIMARY_ROOTLESS_TEST 1
#define main swapzctl_program_main
#include "../../../../src/userspace/swapz-primary.c"
#undef main

#include <assert.h>
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
#include <sys/types.h>
#include <unistd.h>

static void assert_record_equals(int directory_fd, const char *name,
				 const char *expected)
{
	struct stat info;
	char buffer[192];
	ssize_t count;
	int fd = openat(directory_fd, name, O_RDONLY | O_NOFOLLOW);

	assert(fd >= 0);
	assert(fstat(fd, &info) == 0);
	assert(S_ISREG(info.st_mode));
	assert(info.st_uid == geteuid());
	assert((info.st_mode & 0777U) == 0600U);
	count = read(fd, buffer, sizeof(buffer) - 1U);
	assert(count >= 0);
	buffer[count] = '\0';
	assert(strcmp(buffer, expected) == 0);
	assert(close(fd) == 0);
}

static void assert_primary_state_equals(
	int directory_fd, const struct swapz_primary_state *state)
{
	char record[256];
	int length = swapz_primary_state_format(state, record, sizeof(record));

	assert(length > 0);
	assert_record_equals(directory_fd, "primary-state.json", record);
}

static void test_swap_inventory_parser(void)
{
	struct swapz_primary_swap_entry rows[4];
	size_t count = 0;

	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 -1\n",
		rows, 4U, &count) == 0);
	assert(count == 1U);
	assert(!strcmp(rows[0].path, "/dev/sda4"));
	assert(!strcmp(rows[0].type, "partition"));
	assert(rows[0].size_kib == SWAPZ_PRIMARY_SWAP_SIZE_KIB);
	assert(rows[0].used_kib == 0ULL);
	assert(rows[0].priority == -1);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\r\n"
		"/dev/sda4 partition 16777212 1 -1\r\n"
		"/swapfile file 524284 2 10\r\n",
		rows, 4U, &count) == 0);
	assert(count == 2U);
	assert(rows[1].priority == 10);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 -1 extra\n",
		rows, 4U, &count) < 0);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 18446744073709551616 0 -1\n",
		rows, 4U, &count) < 0);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 -1 -1\n",
		rows, 4U, &count) < 0);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 +1\n",
		rows, 4U, &count) < 0);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 -1\n"
		"/dev/sda4 partition 16777212 0 -1\n",
		rows, 4U, &count) < 0);
	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 -1\n",
		rows, 0U, &count) < 0);
}

static void test_target_identity_and_header_policy(void)
{
	unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	static const unsigned char swap_magic[] = "SWAPSPACE2";

	assert(swapz_primary_device_number_matches(makedev(8, 4)));
	assert(!swapz_primary_device_number_matches(makedev(8, 3)));
	assert(!swapz_primary_device_number_matches(makedev(252, 0)));
	memcpy(block + sizeof(block) - sizeof(swap_magic) + 1U,
	       swap_magic, sizeof(swap_magic) - 1U);
	assert(swapz_primary_original_swap_signature(block));
	memset(block, 0, sizeof(block));
	memcpy(block + SWAPZ_SUPERBLOCK_MAGIC_OFFSET, swapz_superblock_magic,
	       SWAPZ_SUPERBLOCK_MAGIC_BYTES);
	swapz_sb_put_u32(block + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);
	swapz_sb_put_u32(block + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);
	swapz_sb_put_u64(block + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 SWAPZ_PRIMARY_DEVICE_BYTES);
	block[SWAPZ_SUPERBLOCK_UUID_OFFSET] = 1U;
	assert(swapz_sb_valid(block, SWAPZ_PRIMARY_DEVICE_BYTES));
	assert(!swapz_primary_original_swap_signature(block));
}

static void test_primary_stage_policy(void)
{
	static const unsigned char allowed[SWAPZ_PRIMARY_STAGE_COUNT]
					       [SWAPZ_PRIMARY_STAGE_COUNT] = {
		[SWAPZ_PRIMARY_STAGE_READY] = {
			[SWAPZ_PRIMARY_STAGE_READY] = 1,
			[SWAPZ_PRIMARY_STAGE_STARTING] = 1,
			[SWAPZ_PRIMARY_STAGE_DISABLING] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_STARTING] = {
			[SWAPZ_PRIMARY_STAGE_STARTING] = 1,
			[SWAPZ_PRIMARY_STAGE_ACTIVE] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_ACTIVE] = {
			[SWAPZ_PRIMARY_STAGE_ACTIVE] = 1,
			[SWAPZ_PRIMARY_STAGE_STOPPING] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_STOPPING] = {
			[SWAPZ_PRIMARY_STAGE_STOPPING] = 1,
			[SWAPZ_PRIMARY_STAGE_RESTORED] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_RECOVERING] = {
			[SWAPZ_PRIMARY_STAGE_RECOVERING] = 1,
			[SWAPZ_PRIMARY_STAGE_RESTORED] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_RESTORED] = {
			[SWAPZ_PRIMARY_STAGE_RESTORED] = 1,
			[SWAPZ_PRIMARY_STAGE_COMPLETE] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_DISABLING] = {
			[SWAPZ_PRIMARY_STAGE_DISABLING] = 1,
			[SWAPZ_PRIMARY_STAGE_COMPLETE] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
		},
		[SWAPZ_PRIMARY_STAGE_COMPLETE] = {0},
		[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = {
			[SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED] = 1,
			[SWAPZ_PRIMARY_STAGE_RECOVERING] = 1,
		},
	};
	enum swapz_primary_stage from;
	enum swapz_primary_stage to;
	enum swapz_primary_stage parsed = SWAPZ_PRIMARY_STAGE_READY;
	unsigned int i;
	unsigned int j;

	for (i = 0; i < (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT; ++i) {
		from = (enum swapz_primary_stage)i;
		assert(swapz_primary_stage_name(from));
		assert(swapz_primary_stage_parse(swapz_primary_stage_name(from),
						 &parsed) == 0);
		assert(parsed == from);
		for (j = 0; j < (unsigned int)SWAPZ_PRIMARY_STAGE_COUNT; ++j) {
			to = (enum swapz_primary_stage)j;
			assert(swapz_primary_stage_transition_allowed(from, to) ==
			       (int)allowed[i][j]);
		}
	}
	assert(!swapz_primary_stage_name((enum swapz_primary_stage)-1));
	assert(!swapz_primary_stage_name(SWAPZ_PRIMARY_STAGE_COUNT));
	assert(swapz_primary_stage_transition_allowed(
		(enum swapz_primary_stage)-1, SWAPZ_PRIMARY_STAGE_READY) == 0);
	assert(swapz_primary_stage_transition_allowed(
		SWAPZ_PRIMARY_STAGE_READY,
		(enum swapz_primary_stage)-1) == 0);
	parsed = SWAPZ_PRIMARY_STAGE_COMPLETE;
	assert(swapz_primary_stage_parse("unknown", &parsed) < 0);
	assert(parsed == SWAPZ_PRIMARY_STAGE_COMPLETE);
	assert(swapz_primary_stage_parse(NULL, &parsed) < 0);
	assert(swapz_primary_stage_parse("READY", NULL) < 0);
}

static void test_primary_state_records(void)
{
	const char *run_id = "0123456789abcdef0123456789abcdef";
	const char *next_run_id = "fedcba9876543210fedcba9876543210";
	const char *duplicate_key_record =
		"{\"schema\":\"swapz-primary-state-v1\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\","
		"\"stage\":\"READY\",\"recovery_previous_stage\":null}\n";
	const char *unknown_key_record =
		"{\"schema\":\"swapz-primary-state-v1\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\","
		"\"unknown\":0,\"stage\":\"READY\","
		"\"recovery_previous_stage\":null}\n";
	const char *escaped_stage_record =
		"{\"schema\":\"swapz-primary-state-v1\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\","
		"\"stage\":\"RE\\u0041DY\","
		"\"recovery_previous_stage\":null}\n";
	struct swapz_primary_state current = {0};
	struct swapz_primary_state next = {0};
	struct swapz_primary_state parsed = {0};
	struct swapz_primary_state invalid = {0};
	char record[256];
	int length;

	memcpy(current.run_id, run_id, sizeof(current.run_id));
	current.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_STOPPING;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	length = swapz_primary_state_format(&current, record, sizeof(record));
	assert(length > 0);
	assert(swapz_primary_state_parse(record, (size_t)length, &parsed) == 0);
	assert(!strcmp(current.run_id, parsed.run_id));
	assert(current.stage == parsed.stage);
	assert(current.has_recovery_previous_stage ==
	       parsed.has_recovery_previous_stage);
	assert(swapz_primary_state_parse(duplicate_key_record,
					 strlen(duplicate_key_record), &parsed) < 0);
	assert(swapz_primary_state_parse(unknown_key_record,
					 strlen(unknown_key_record), &parsed) < 0);
	assert(swapz_primary_state_parse(escaped_stage_record,
					 strlen(escaped_stage_record), &parsed) < 0);
	invalid = current;
	memset(invalid.run_id, 'a', sizeof(invalid.run_id));
	assert(!swapz_primary_state_transition_allowed(&current, &invalid));
	invalid = current;
	invalid.has_recovery_previous_stage = 2;
	assert(swapz_primary_state_format(&invalid, record, sizeof(record)) < 0);
	assert(swapz_primary_state_parse(record, (size_t)length - 1U,
					 &parsed) < 0);
	assert(swapz_primary_state_parse(record, (size_t)length + 1U,
					 &parsed) < 0);
	record[length] = 'x';
	assert(swapz_primary_state_parse(record, (size_t)length + 1U,
					 &parsed) < 0);
	assert(swapz_primary_state_format(&current, record, 1U) < 0);

	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	next.has_recovery_previous_stage = 1;
	next.recovery_previous_stage = current.stage;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	length = swapz_primary_state_format(&next, record, sizeof(record));
	assert(length > 0);
	assert(swapz_primary_state_parse(record, (size_t)length, &parsed) == 0);
	assert(!strcmp(next.run_id, parsed.run_id));
	assert(next.stage == parsed.stage);
	assert(next.has_recovery_previous_stage ==
	       parsed.has_recovery_previous_stage);
	assert(next.recovery_previous_stage == parsed.recovery_previous_stage);
	current = next;
	next.stage = SWAPZ_PRIMARY_STAGE_RECOVERING;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	current = next;
	next.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	current = next;
	next.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	current = next;
	memcpy(next.run_id, next_run_id, sizeof(next.run_id));
	next.stage = SWAPZ_PRIMARY_STAGE_READY;
	next.has_recovery_previous_stage = 0;
	assert(swapz_primary_state_transition_allowed(&current, &next));

	current = parsed;
	memcpy(current.run_id, run_id, sizeof(current.run_id));
	current.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	current.has_recovery_previous_stage = 0;
	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	next.has_recovery_previous_stage = 1;
	next.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_READY;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
	next.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert(swapz_primary_state_transition_allowed(&current, &next));
	next.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
	current.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	next = current;
	next.stage = SWAPZ_PRIMARY_STAGE_READY;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
	memcpy(next.run_id, next_run_id, sizeof(next.run_id));
	assert(swapz_primary_state_transition_allowed(&current, &next));
	next.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
	next.stage = SWAPZ_PRIMARY_STAGE_READY;
	next.has_recovery_previous_stage = 1;
	next.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert(!swapz_primary_state_transition_allowed(&current, &next));
}

static void test_primary_header_backup(int recovery_fd, int lock_fd,
				       const char *run_id)
{
	static const unsigned char swap_magic[] = "SWAPSPACE2";
	unsigned char original[SWAPZ_PRIMARY_BLOCK_BYTES];
	unsigned char restored[SWAPZ_PRIMARY_BLOCK_BYTES];
	char backup_name[64];
	char digest[65];
	char wrong_digest[65];
	size_t i;

	for (i = 0; i < sizeof(original); ++i)
		original[i] = (unsigned char)((i * 37U + 11U) & 0xffU);
	memcpy(original + sizeof(original) - sizeof(swap_magic) + 1U,
	       swap_magic, sizeof(swap_magic) - 1U);
	assert(swapz_primary_original_swap_signature(original));
	assert(swapz_primary_sha256(original, sizeof(original), digest) == 0);
	assert(swapz_primary_header_backup_write_at(
		recovery_fd, lock_fd, run_id, original, digest, geteuid()) == 0);
	memset(restored, 0xa5, sizeof(restored));
	assert(swapz_primary_header_backup_read_at(
		recovery_fd, lock_fd, run_id, digest, geteuid(), restored) == 0);
	assert(!memcmp(original, restored, sizeof(original)));
	assert(swapz_primary_header_backup_write_at(
		recovery_fd, lock_fd, run_id, original, digest, geteuid()) < 0);
	assert(errno == EEXIST);
	memcpy(wrong_digest, digest, sizeof(wrong_digest));
	wrong_digest[0] = wrong_digest[0] == '0' ? '1' : '0';
	memset(restored, 0xa5, sizeof(restored));
	assert(swapz_primary_header_backup_read_at(
		recovery_fd, lock_fd, run_id, wrong_digest, geteuid(), restored) < 0);
	assert(errno == EBADMSG);
	assert(restored[0] == 0xa5);
	assert(snprintf(backup_name, sizeof(backup_name), "block0-%s.bin",
			 run_id) > 0);
	assert(unlinkat(recovery_fd, backup_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
}

static void test_primary_manifest(int recovery_fd, int lock_fd,
				  const char *run_id)
{
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_manifest parsed = {0};
	struct swapz_primary_manifest observed = {0};
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char damaged[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char file_name[96];
	char *field;
	int length;
	int fd;

	memcpy(manifest.run_id, run_id, SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U);
	memset(manifest.source_sha, 'a', SWAPZ_PRIMARY_SOURCE_SHA_LENGTH);
	manifest.source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH] = '\0';
	memset(manifest.swapzctl_sha256, 'b', SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.swapzctl_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	memset(manifest.module_sha256, 'c', SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.module_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	memset(manifest.qualification_report_sha256, 'd',
	       SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.qualification_report_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	memcpy(manifest.original_header_sha256,
	       SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256,
	       sizeof(manifest.original_header_sha256));
	length = swapz_primary_manifest_format(&manifest, record,
					      sizeof(record));
	assert(length > 0);
	assert(swapz_primary_manifest_parse(record, (size_t)length, &parsed) == 0);
	assert(!memcmp(&manifest, &parsed, sizeof(manifest)));
	manifest.source_sha[0] = 'A';
	assert(swapz_primary_manifest_format(&manifest, damaged,
					     sizeof(damaged)) < 0);
	manifest.source_sha[0] = 'a';
	memcpy(damaged, record, (size_t)length);
	field = strstr(damaged, "device_major=8\n");
	assert(field);
	field[strlen("device_major=")] = '9';
	memset(&parsed, 0xa5, sizeof(parsed));
	assert(swapz_primary_manifest_parse(damaged, (size_t)length,
					    &parsed) < 0);
	assert(((const unsigned char *)&parsed)[0] == 0xa5U);
	assert(swapz_primary_manifest_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	memset(&observed, 0, sizeof(observed));
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      geteuid(), &observed) == 0);
	assert(!memcmp(&manifest, &observed, sizeof(manifest)));
	assert(swapz_primary_manifest_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) < 0);
	assert(errno == EEXIST);
	assert(snprintf(file_name, sizeof(file_name), "primary-manifest-%s.txt",
			run_id) > 0);
	fd = openat(recovery_fd, file_name, O_RDWR | O_NOFOLLOW | O_CLOEXEC);
	assert(fd >= 0);
	field = strstr(record, "device_major=8\n");
	assert(field);
	assert(pwrite(fd, "9", 1, (off_t)(field - record +
					    strlen("device_major="))) == 1);
	assert(fsync(fd) == 0);
	memset(&observed, 0xa5, sizeof(observed));
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      geteuid(), &observed) < 0);
	assert(((const unsigned char *)&observed)[0] == 0xa5U);
	assert(pwrite(fd, "8", 1, (off_t)(field - record +
					    strlen("device_major="))) == 1);
	assert(fsync(fd) == 0);
	assert(close(fd) == 0);
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      geteuid(), &observed) == 0);
	assert(!memcmp(&manifest, &observed, sizeof(manifest)));
	assert(unlinkat(recovery_fd, file_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
}

static void test_checked_header_write(void)
{
	unsigned char original[SWAPZ_PRIMARY_BLOCK_BYTES];
	unsigned char replacement[SWAPZ_PRIMARY_BLOCK_BYTES];
	unsigned char observed[SWAPZ_PRIMARY_BLOCK_BYTES];
	char path[] = "/tmp/swapz-primary-header-write-XXXXXX";
	size_t i;
	int fd;

	fd = mkstemp(path);
	assert(fd >= 0);
	assert(ftruncate(fd, (off_t)sizeof(original)) == 0);
	for (i = 0; i < sizeof(original); ++i) {
		original[i] = (unsigned char)((i * 13U + 7U) & 0xffU);
		replacement[i] = (unsigned char)((i * 29U + 3U) & 0xffU);
	}
	assert(pwrite(fd, original, sizeof(original), 0) ==
	       (ssize_t)sizeof(original));
	assert(fsync(fd) == 0);
	assert(swapz_primary_write_header_checked_fd(
		fd, original, replacement) == 0);
	assert(swapz_primary_exact_read(fd, observed, sizeof(observed)) == 0);
	assert(!memcmp(observed, replacement, sizeof(observed)));
	assert(swapz_primary_write_header_checked_fd(
		fd, original, original) < 0);
	assert(errno == ESTALE);
	assert(swapz_primary_exact_read(fd, observed, sizeof(observed)) == 0);
	assert(!memcmp(observed, replacement, sizeof(observed)));
	assert(swapz_primary_write_header_checked_fd(
		fd, replacement, original) == 0);
	assert(swapz_primary_exact_read(fd, observed, sizeof(observed)) == 0);
	assert(!memcmp(observed, original, sizeof(observed)));
	assert(close(fd) == 0);
	assert(unlink(path) == 0);
}

static void test_exclusive_target_open_paths(void)
{
	char directory[] = "/tmp/swapz-primary-open-XXXXXX";
	char target[PATH_MAX];
	char other[PATH_MAX];
	char uuid_path[PATH_MAX];
	char partuuid_path[PATH_MAX];
	char substituted[PATH_MAX];
	struct stat info;
	int fd;

	assert(mkdtemp(directory) != NULL);
	assert(snprintf(target, sizeof(target), "%s/target", directory) > 0);
	assert(snprintf(other, sizeof(other), "%s/other", directory) > 0);
	assert(snprintf(uuid_path, sizeof(uuid_path), "%s/by-uuid", directory) > 0);
	assert(snprintf(partuuid_path, sizeof(partuuid_path), "%s/by-partuuid",
			 directory) > 0);
	assert(snprintf(substituted, sizeof(substituted), "%s/substituted",
			 directory) > 0);
	fd = open(target, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	assert(fd >= 0);
	assert(ftruncate(fd, (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) == 0);
	assert(close(fd) == 0);
	fd = open(other, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	assert(fd >= 0);
	assert(ftruncate(fd, (off_t)SWAPZ_PRIMARY_BLOCK_BYTES) == 0);
	assert(close(fd) == 0);
	assert(symlink(target, uuid_path) == 0);
	assert(symlink(target, partuuid_path) == 0);
	fd = swapz_primary_open_target_checked_paths(target, uuid_path,
						     partuuid_path);
	assert(fd >= 0);
	assert(fstat(fd, &info) == 0 && S_ISREG(info.st_mode));
	assert((fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDWR);
	assert(close(fd) == 0);
	assert(unlink(partuuid_path) == 0);
	assert(symlink(other, substituted) == 0);
	assert(symlink(substituted, partuuid_path) == 0);
	assert(swapz_primary_open_target_checked_paths(target, uuid_path,
						     partuuid_path) < 0);
	assert(errno == ENODEV);
	assert(swapz_primary_open_target_checked_paths(target, uuid_path,
						     NULL) < 0);
	assert(errno == EINVAL);
	assert(unlink(partuuid_path) == 0);
	assert(unlink(substituted) == 0);
	assert(unlink(uuid_path) == 0);
	assert(unlink(other) == 0);
	assert(unlink(target) == 0);
	assert(rmdir(directory) == 0);
}

static void test_exact_block_read_helper(void)
{
	const char *home = getenv("HOME");
	char path[PATH_MAX];
	unsigned char expected[SWAPZ_PRIMARY_BLOCK_BYTES];
	unsigned char observed[SWAPZ_PRIMARY_BLOCK_BYTES];
	size_t i;
	int fd;

	assert(home && home[0] == '/');
	assert(snprintf(path, sizeof(path),
			 "%s/.swapz-primary-read-XXXXXX", home) > 0);
	fd = mkstemp(path);
	assert(fd >= 0);
	for (i = 0; i < sizeof(expected); ++i)
		expected[i] = (unsigned char)(i & 0xffU);
	assert(write(fd, expected, sizeof(expected)) == (ssize_t)sizeof(expected));
	assert(fsync(fd) == 0);
	assert(swapz_primary_exact_read(fd, observed, sizeof(observed)) == 0);
	assert(!memcmp(expected, observed, sizeof(expected)));
	assert(ftruncate(fd, 0) == 0);
	errno = 0;
	assert(swapz_primary_exact_read(fd, observed, sizeof(observed)) < 0);
	assert(errno == EIO);
	assert(close(fd) == 0);
	assert(unlink(path) == 0);
}

static void test_sha256_helper(void)
{
	static const unsigned char abc[] = "abc";
	static const char abc_expected[] =
		"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
	static const char empty_expected[] =
		"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
	static const char expected[] =
		"ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7";
	unsigned char zeroes[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	char digest[65];

	assert(swapz_primary_sha256(abc, sizeof(abc) - 1U, digest) == 0);
	assert(!strcmp(digest, abc_expected));
	assert(swapz_primary_sha256(abc, 0, digest) == 0);
	assert(!strcmp(digest, empty_expected));
	assert(swapz_primary_sha256(zeroes, sizeof(zeroes), digest) == 0);
	assert(!strcmp(digest, expected));
	memset(digest, 'x', sizeof(digest));
	assert(swapz_primary_sha256(abc, SIZE_MAX, digest) < 0);
	assert(errno == EOVERFLOW);
	assert(digest[0] == 'x');
}

static void test_sha256_regular_fd(void)
{
	static const char expected[] =
		"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
	char path[] = "/tmp/swapz-primary-hash-file-XXXXXX";
	char link_path[PATH_MAX];
	char digest[65];
	int fd;
	int write_fd;

	fd = mkstemp(path);
	assert(fd >= 0);
	assert(write(fd, "abc", 3U) == 3);
	assert(fsync(fd) == 0);
	assert(close(fd) == 0);
	fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
	assert(fd >= 0);
	assert(swapz_primary_sha256_regular_fd(
		fd, geteuid(), 1024U, digest) == 0);
	assert(!strcmp(digest, expected));
	memset(digest, 'x', sizeof(digest));
	assert(swapz_primary_sha256_regular_fd(
		fd, geteuid(), 2U, digest) < 0);
	assert(errno == EFBIG && digest[0] == 'x');
	assert(fchmod(fd, 0660) == 0);
	assert(swapz_primary_sha256_regular_fd(
		fd, geteuid(), 1024U, digest) < 0);
	assert(errno == EPERM && digest[0] == 'x');
	assert(fchmod(fd, 0600) == 0);
	assert(snprintf(link_path, sizeof(link_path), "%s.link", path) > 0);
	assert(link(path, link_path) == 0);
	assert(swapz_primary_sha256_regular_fd(
		fd, geteuid(), 1024U, digest) < 0);
	assert(errno == EPERM && digest[0] == 'x');
	assert(unlink(link_path) == 0);
	assert(close(fd) == 0);
	write_fd = open(path, O_WRONLY | O_CLOEXEC);
	assert(write_fd >= 0);
	assert(swapz_primary_sha256_regular_fd(
		write_fd, geteuid(), 1024U, digest) < 0);
	assert(errno == EBADF && digest[0] == 'x');
	assert(close(write_fd) == 0);
	assert(unlink(path) == 0);
}

static void test_recovery_filesystem_policy(void)
{
	assert(swapz_primary_persistent_fs_magic(EXT2_SUPER_MAGIC));
	assert(swapz_primary_persistent_fs_magic(XFS_SUPER_MAGIC));
	assert(swapz_primary_persistent_fs_magic(F2FS_SUPER_MAGIC));
	assert(!swapz_primary_persistent_fs_magic(BTRFS_SUPER_MAGIC));
	assert(!swapz_primary_persistent_fs_magic(TMPFS_MAGIC));
	assert(!swapz_primary_persistent_fs_magic(RAMFS_MAGIC));
	assert(!swapz_primary_persistent_fs_magic(OVERLAYFS_SUPER_MAGIC));
}

static void test_path_join(char *path, size_t capacity, const char *parent,
			   const char *child)
{
	int length = snprintf(path, capacity, "%s/%s", parent, child);

	assert(length > 0 && (size_t)length < capacity);
}

static void test_write_text(const char *path, const char *text)
{
	size_t length = strlen(text);
	const char *cursor = text;
	int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);

	assert(fd >= 0);
	while (length) {
		ssize_t count = write(fd, cursor, length);

		if (count < 0 && errno == EINTR)
			continue;
		assert(count > 0);
		cursor += count;
		length -= (size_t)count;
	}
	assert(close(fd) == 0);
}

static int test_remove_tree_entry(const char *path, const struct stat *info,
				 int type, struct FTW *walk)
{
	(void)info;
	(void)type;
	(void)walk;
	return remove(path);
}

static void test_recovery_source_chain(void)
{
	char root_template[] = "/tmp/swapz-primary-sysfs-XXXXXX";
	char root[PATH_MAX];
	char devices[PATH_MAX];
	char transport[PATH_MAX];
	char block[PATH_MAX];
	char disk[PATH_MAX];
	char physical[PATH_MAX];
	char node3[PATH_MAX];
	char node4[PATH_MAX];
	char virtual_device[PATH_MAX];
	char dev_directory[PATH_MAX];
	char block_directory[PATH_MAX];
	char source_link[PATH_MAX];
	char target_link[PATH_MAX];
	char path[PATH_MAX];
	char path2[PATH_MAX];
	dev_t physical_device = 0;
	dev_t target_parent_device = 0;

	assert(mkdtemp(root_template));
	assert(strlen(root_template) < sizeof(root));
	strcpy(root, root_template);
	test_path_join(devices, sizeof(devices), root, "devices");
	test_path_join(dev_directory, sizeof(dev_directory), root, "dev");
	test_path_join(block_directory, sizeof(block_directory), dev_directory,
		       "block");
	assert(mkdir(devices, 0700) == 0);
	assert(mkdir(dev_directory, 0700) == 0);
	assert(mkdir(block_directory, 0700) == 0);
	test_path_join(transport, sizeof(transport), devices, "transport");
	test_path_join(block, sizeof(block), transport, "block");
	test_path_join(disk, sizeof(disk), block, "sda");
	test_path_join(physical, sizeof(physical), transport, "scsi-device");
	test_path_join(node3, sizeof(node3), disk, "sda3");
	test_path_join(node4, sizeof(node4), disk, "sda4");
	assert(mkdir(transport, 0700) == 0);
	assert(mkdir(block, 0700) == 0);
	assert(mkdir(disk, 0700) == 0);
	assert(mkdir(physical, 0700) == 0);
	test_path_join(path, sizeof(path), devices, "virtual");
	assert(mkdir(path, 0700) == 0);
	test_path_join(virtual_device, sizeof(virtual_device), path, "block-device");
	assert(mkdir(virtual_device, 0700) == 0);
	assert(mkdir(node3, 0700) == 0);
	assert(mkdir(node4, 0700) == 0);
	test_path_join(path, sizeof(path), disk, "queue");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path, sizeof(path), disk, "holders");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path, sizeof(path), disk, "slaves");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path, sizeof(path), node3, "holders");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path, sizeof(path), node4, "holders");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path, sizeof(path), disk, "device");
	assert(symlink(physical, path) == 0);
	test_path_join(path, sizeof(path), disk, "dev");
	test_write_text(path, "8:0\n");
	test_path_join(path, sizeof(path), node3, "dev");
	test_write_text(path, "8:3\n");
	test_path_join(path, sizeof(path), node3, "partition");
	test_write_text(path, "3\n");
	test_path_join(path, sizeof(path), node4, "dev");
	test_write_text(path, "8:4\n");
	test_path_join(path, sizeof(path), node4, "partition");
	test_write_text(path, "4\n");
	test_path_join(source_link, sizeof(source_link), block_directory, "8:3");
	test_path_join(target_link, sizeof(target_link), block_directory, "8:4");
	assert(symlink(node3, source_link) == 0);
	assert(symlink(node4, target_link) == 0);
	assert(swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	assert(physical_device == makedev(8U, 0U));
	assert(swapz_primary_recovery_source_chain(
		root, makedev(8U, 4U), 0, &target_parent_device));
	assert(target_parent_device == physical_device);
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 4U), makedev(8U, 4U), &target_parent_device));
	test_path_join(path, sizeof(path), node3, "holders");
	test_path_join(path2, sizeof(path2), path, "dm-0");
	test_write_text(path2, "held\n");
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	assert(unlink(path2) == 0);
	test_path_join(path, sizeof(path), node3, "slaves");
	assert(mkdir(path, 0700) == 0);
	test_path_join(path2, sizeof(path2), path, "8:5");
	test_write_text(path2, "stacked\n");
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	assert(unlink(path2) == 0);
	assert(rmdir(path) == 0);
	test_path_join(path, sizeof(path), node3, "dev");
	test_write_text(path, "8:30\n");
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	test_write_text(path, "8:3\n");
	test_path_join(path, sizeof(path), disk, "device");
	assert(unlink(path) == 0);
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	assert(symlink(virtual_device, path) == 0);
	assert(!swapz_primary_recovery_source_chain(
		root, makedev(8U, 3U), makedev(8U, 4U), &physical_device));
	assert(unlink(path) == 0);
	assert(symlink(physical, path) == 0);
	assert(nftw(root, test_remove_tree_entry, 16, FTW_DEPTH | FTW_PHYS) == 0);
}

static void test_mountinfo_parser(void)
{
	struct swapz_primary_mount_facts facts;

	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw,relatime - f2fs /dev/sda3 rw\n"
		"37 36 8:3 /data /data\\040archive rw - f2fs /dev/sda3 rw\n"
		"38 37 0:5 mnt:[4026531840] /run/ns rw - nsfs nsfs rw\n",
		makedev(8U, 4U), &facts) == 0);
	assert(facts.root_mount_seen);
	assert(facts.root_device == makedev(8U, 3U));
	assert(!facts.target_mounted);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3 rw\n"
		"37 36 8:4 / /mnt/swap rw - swap /dev/sda4 rw\n",
		makedev(8U, 4U), &facts) == 0);
	assert(facts.target_mounted);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:x / / rw - f2fs /dev/sda3 rw\n",
		makedev(8U, 4U), &facts) < 0);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3 rw\n"
		"37 36 8:3 / / rw - f2fs /dev/sda3 rw\n",
		makedev(8U, 4U), &facts) < 0);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3\n",
		makedev(8U, 4U), &facts) < 0);
}

static void test_module_mapper_identity_policy(void)
{
	assert(swapz_primary_dm_block_name("dm-0"));
	assert(swapz_primary_dm_block_name("dm-123"));
	assert(!swapz_primary_dm_block_name("dm-"));
	assert(!swapz_primary_dm_block_name("dm-1x"));
	assert(!swapz_primary_dm_block_name("sda"));
	assert(swapz_primary_mapper_identity_is_swapz(
		"swapz-live-0123456789abcdef", "") == 1);
	assert(swapz_primary_mapper_identity_is_swapz(
		"swapz-demo-physical-0123456789abcdef", "") == 1);
	assert(swapz_primary_mapper_identity_is_swapz(
		"unrelated-map", "SWAPZ-LIVE-0123456789ABCDEF") == 1);
	assert(swapz_primary_mapper_identity_is_swapz(
		"crypt-root", "CRYPT-LUKS1-0123456789") == 0);
	assert(swapz_primary_mapper_identity_is_swapz("", "") < 0);
	assert(swapz_primary_mapper_identity_is_swapz("bad/name", "") < 0);
	assert(swapz_primary_mapper_identity_is_swapz("map", "bad\001uuid") < 0);
}

static void test_build_source_provenance_policy(void)
{
	const char *same_sha =
		"0123456789abcdef0123456789abcdef01234567";
	const char *other_sha =
		"fedcba9876543210fedcba9876543210fedcba98";

	assert(swapz_primary_build_sources_match(same_sha, 1, same_sha, 1));
	assert(!swapz_primary_build_sources_match(same_sha, 0, same_sha, 1));
	assert(!swapz_primary_build_sources_match(same_sha, 1, same_sha, 0));
	assert(!swapz_primary_build_sources_match(same_sha, 2, same_sha, 1));
	assert(!swapz_primary_build_sources_match(same_sha, 1, same_sha, -1));
	assert(!swapz_primary_build_sources_match(same_sha, 1, other_sha, 1));
	assert(!swapz_primary_build_sources_match("unknown", 1, "unknown", 1));
	assert(!swapz_primary_build_sources_match("invalid", 1, same_sha, 1));
}

static void test_primary_qualification_report_parser(void)
{
	static const char report_template[] =
		"{\"schema\":\"swapz-test-results-v1\","
		"\"host_identity\":{\"schema\":\"swapz-host-v1\","
		"\"architecture\":\"x86_64\",\"id_sha256\":\"%s\"},"
		"\"source_sha\":\"%s\",\"tested_commit_sha\":\"%s\","
		"\"overall\":\"PASS\","
		"\"qualification\":\"RAM_BACKED_NULL_BLK_ONLY\","
		"\"stages\":["
		"{\"name\":\"Build module and helpers\",\"status\":\"PASS\",\"exit_code\":0},"
		"{\"name\":\"Native and rootless contracts\",\"status\":\"PASS\",\"exit_code\":0},"
		"{\"name\":\"Kernel warnings W=1\",\"status\":\"PASS\",\"exit_code\":0},"
		"{\"name\":\"Kernel warnings W=2\",\"status\":\"PASS\",\"exit_code\":0},"
		"{\"name\":\"Owned RAM smoke + mixed/QD pilot\",\"status\":\"PASS\",\"exit_code\":0}],"
		"\"qualified_artifacts\":{\"status\":\"AVAILABLE\","
		"\"formatter_sha256\":\"%s\",\"module_sha256\":\"%s\","
		"\"oracle_sha256\":\"%s\"}}\n";
	const char *source = "0123456789abcdef0123456789abcdef01234567";
	char host_sha[65];
	char formatter_sha[65];
	char module_sha[65];
	char oracle_sha[65];
	char json[4096];
	struct swapz_primary_qualification qualification;
	int length;

	memset(host_sha, 'a', 64U);
	host_sha[64] = '\0';
	memset(formatter_sha, 'b', 64U);
	formatter_sha[64] = '\0';
	memset(module_sha, 'c', 64U);
	module_sha[64] = '\0';
	memset(oracle_sha, 'd', 64U);
	oracle_sha[64] = '\0';
	length = snprintf(json, sizeof(json), report_template, host_sha,
			  source, source, formatter_sha, module_sha, oracle_sha);
	assert(length > 0 && (size_t)length < sizeof(json));
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, source, host_sha,
		&qualification) == 0);
	assert(!strcmp(qualification.source_sha, source));
	assert(!strcmp(qualification.host_identity_sha256, host_sha));
	assert(!strcmp(qualification.formatter_sha256, formatter_sha));
	assert(!strcmp(qualification.module_sha256, module_sha));
	assert(!strcmp(qualification.oracle_sha256, oracle_sha));
	assert(swapz_primary_valid_sha256(qualification.report_sha256));
	assert(swapz_primary_qualification_artifacts_match(
		&qualification, formatter_sha, module_sha, oracle_sha));
	assert(!swapz_primary_qualification_artifacts_match(
		&qualification, module_sha, module_sha, oracle_sha));
	assert(!swapz_primary_qualification_artifacts_match(
		&qualification, formatter_sha, "invalid", oracle_sha));
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, source, module_sha,
		&qualification) < 0);
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, "unknown", host_sha,
		&qualification) < 0);
	{
		char *overall = strstr(json, "\"overall\":\"PASS\"");

		assert(overall);
		overall[strlen("\"overall\":\"")] = 'F';
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		overall[strlen("\"overall\":\"")] = 'P';
	}
	{
		char *scope = strstr(json, "\"qualification\":\"");

		assert(scope);
		scope[strlen("\"qualification\":\"")] = 'X';
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		scope[strlen("\"qualification\":\"")] = 'R';
	}
	{
		char *stage_status = strstr(json, "\"status\":\"PASS\"");

		assert(stage_status);
		memcpy(stage_status + strlen("\"status\":\""), "FAIL", 4U);
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		memcpy(stage_status + strlen("\"status\":\""), "PASS", 4U);
	}
	{
		char *exit_code = strstr(json, "\"exit_code\":0");

		assert(exit_code);
		exit_code[strlen("\"exit_code\":")] = '1';
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		exit_code[strlen("\"exit_code\":")] = '0';
	}
	{
		char *formatter = strstr(json, "\"formatter_sha256\":\"");
		char original;

		assert(formatter);
		formatter += strlen("\"formatter_sha256\":\"");
		original = *formatter;
		*formatter = 'z';
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		*formatter = original;
	}
	json[length - 1] = 'x';
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, source, host_sha,
		&qualification) < 0);
	json[length - 1] = '\n';
	{
		char duplicate[4096];
		static const char duplicate_field[] = "\"overall\":\"PASS\",";
		size_t duplicate_length = sizeof(duplicate_field) - 1U;
		char *needle;

		memcpy(duplicate, json, (size_t)length + 1U);
		needle = strstr(duplicate, "\"overall\":\"PASS\",");
		assert(needle);
		memmove(needle + duplicate_length, needle,
			strlen(needle) + 1U);
		memcpy(needle, duplicate_field, duplicate_length);
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)duplicate, strlen(duplicate), source,
			host_sha, &qualification) < 0);
	}
}

static void test_primary_qualification_live_reader_disabled_in_rootless(void)
{
	struct swapz_primary_qualification qualification;
	struct swapz_primary_qualification original;
	char host_identity_sha256[65];
	char swapzctl_sha256[65];
	char module_sha256[65];
	char oracle_sha256[65];
	char original_hashes[3][65];

	memset(&qualification, 0xa5, sizeof(qualification));
	original = qualification;
	assert(swapz_primary_read_qualification_report(&qualification) < 0);
	assert(errno == ENODEV);
	assert(!memcmp(&qualification, &original, sizeof(qualification)));
	assert(swapz_primary_live_host_identity_sha256(host_identity_sha256) < 0);
	assert(errno == ENODEV);
	memset(swapzctl_sha256, 0xa5, sizeof(swapzctl_sha256));
	memset(module_sha256, 0xa5, sizeof(module_sha256));
	memset(oracle_sha256, 0xa5, sizeof(oracle_sha256));
	memcpy(original_hashes[0], swapzctl_sha256, sizeof(swapzctl_sha256));
	memcpy(original_hashes[1], module_sha256, sizeof(module_sha256));
	memcpy(original_hashes[2], oracle_sha256, sizeof(oracle_sha256));
	assert(swapz_primary_live_artifact_hashes(
		swapzctl_sha256, module_sha256, oracle_sha256) < 0);
	assert(errno == ENODEV);
	assert(!memcmp(swapzctl_sha256, original_hashes[0],
		       sizeof(swapzctl_sha256)));
	assert(!memcmp(module_sha256, original_hashes[1],
		       sizeof(module_sha256)));
	assert(!memcmp(oracle_sha256, original_hashes[2],
		       sizeof(oracle_sha256)));
}

int main(void)
{
	uint64_t pages = swapz_primary_maximum_logical_pages(
		SWAPZ_PRIMARY_PHYSICAL_BLOCKS);
	const char *home = getenv("HOME");
	char base_template[PATH_MAX];
	char lock_path[PATH_MAX];
	char target_path[PATH_MAX];
	char active_name[64];
	char consumed_name[64];
	char next_consumed_name[64];
	struct swapz_primary_state lifecycle = {0};
	struct stat state_link_info;
	const char *run_id = "0123456789abcdef0123456789abcdef";
	const char *other_run_id = "fedcba9876543210fedcba9876543210";
	const char *expected_record =
		"{\"major\":8,\"minor\":4,\"partuuid\":\"7fb9401d-04\","
		"\"run_id\":\"0123456789abcdef0123456789abcdef\"}\n";
	int recovery_fd;
	int first_lock;
	int second_lock;
	int unlocked_lock;
	char *plan[] = {"plan"};
	char *prepare[] = {"prepare"};
	char *start[] = {"start"};
	char *stop[] = {"stop"};
	char *recover[] = {"recover"};

	assert(pages == 3727872ULL);
	assert(swapz_primary_page_limit_fits(SWAPZ_PRIMARY_PHYSICAL_BLOCKS,
						 pages));
	assert(!swapz_primary_page_limit_fits(SWAPZ_PRIMARY_PHYSICAL_BLOCKS,
						  pages + 1ULL));
	test_swap_inventory_parser();
	test_target_identity_and_header_policy();
	test_primary_stage_policy();
	test_primary_state_records();
	test_checked_header_write();
	test_exclusive_target_open_paths();
	test_exact_block_read_helper();
	test_sha256_helper();
	test_sha256_regular_fd();
	test_recovery_filesystem_policy();
	test_recovery_source_chain();
	test_mountinfo_parser();
	test_module_mapper_identity_policy();
	test_build_source_provenance_policy();
	test_primary_qualification_report_parser();
	test_primary_qualification_live_reader_disabled_in_rootless();
	assert(home && home[0] == '/');
	assert(snprintf(base_template, sizeof(base_template),
			 "%s/.swapz-primary-lock-XXXXXX", home) > 0);
	assert(mkdtemp(base_template));
	assert(snprintf(lock_path, sizeof(lock_path),
			 "%s/partition-7fb9401d-04.lock", base_template) > 0);
	assert(snprintf(target_path, sizeof(target_path),
			 "%s/target", base_template) > 0);
	assert(snprintf(active_name, sizeof(active_name),
			 "partition-7fb9401d-04.active") > 0);
	assert(snprintf(consumed_name, sizeof(consumed_name),
			 "consumed-%s.json", run_id) > 0);
	assert(snprintf(next_consumed_name, sizeof(next_consumed_name),
			 "consumed-%s.json", other_run_id) > 0);
	recovery_fd = swapz_primary_recovery_base_open(
		base_template, geteuid());
	assert(recovery_fd >= 0);
	first_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(first_lock >= 0);
	second_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(second_lock < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	unlocked_lock = openat(recovery_fd, "partition-7fb9401d-04.lock",
			      O_RDWR | O_NOFOLLOW);
	assert(unlocked_lock >= 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, unlocked_lock, run_id, geteuid()) < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	assert(close(unlocked_lock) == 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, "invalid-run-id", geteuid()) < 0);
	assert(errno == EINVAL);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) == 0);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	assert(errno == EBUSY);
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, other_run_id, geteuid()) < 0);
	assert(errno == EBUSY);
	assert_record_equals(recovery_fd, active_name, expected_record);
	assert_record_equals(recovery_fd, consumed_name, expected_record);
	test_primary_header_backup(recovery_fd, first_lock, run_id);
	test_primary_manifest(recovery_fd, first_lock, run_id);
	memcpy(lifecycle.run_id, run_id, sizeof(lifecycle.run_id));
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_READY;
	unlocked_lock = openat(recovery_fd, "partition-7fb9401d-04.lock",
			      O_RDWR | O_NOFOLLOW);
	assert(unlocked_lock >= 0);
	assert(swapz_primary_state_write_at(recovery_fd, unlocked_lock,
						    &lifecycle, geteuid()) < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	assert(close(unlocked_lock) == 0);
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert_primary_state_equals(recovery_fd, &lifecycle);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert_primary_state_equals(recovery_fd, &lifecycle);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_STOPPING;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) < 0);
	assert(errno == EPERM);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert_primary_state_equals(recovery_fd, &lifecycle);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	lifecycle.recovery_previous_stage = lifecycle.stage;
	lifecycle.has_recovery_previous_stage = 1;
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_RECOVERING;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	lifecycle.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_READY;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) < 0);
	assert(errno == EPERM);
	lifecycle.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert_primary_state_equals(recovery_fd, &lifecycle);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert(swapz_primary_release_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	assert(errno == EPERM);
	assert_record_equals(recovery_fd, active_name, expected_record);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert(swapz_primary_release_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) == 0);
	assert(fstatat(recovery_fd, active_name, &state_link_info,
		       AT_SYMLINK_NOFOLLOW) < 0 && errno == ENOENT);
	assert_record_equals(recovery_fd, consumed_name, expected_record);
	assert(swapz_primary_release_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	memcpy(lifecycle.run_id, other_run_id, sizeof(lifecycle.run_id));
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_READY;
	lifecycle.has_recovery_previous_stage = 0;
	assert(swapz_primary_claim_partition_owner_at(
		recovery_fd, first_lock, other_run_id, geteuid()) == 0);
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert_primary_state_equals(recovery_fd, &lifecycle);
	assert(swapz_primary_write_record_at(recovery_fd, "state-target",
					     "target\n", geteuid()) == 0);
	assert(symlinkat("state-target", recovery_fd, "state-link") == 0);
	assert(swapz_primary_replace_record_at(
		recovery_fd, "state-link", run_id, "replacement\n", geteuid()) < 0);
	assert(errno == EPERM);
	assert(fstatat(recovery_fd, "state-link", &state_link_info,
		       AT_SYMLINK_NOFOLLOW) == 0 && S_ISLNK(state_link_info.st_mode));
	assert(close(first_lock) == 0);
	first_lock = swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid());
	assert(first_lock >= 0);
	assert(close(first_lock) == 0);
	assert(close(recovery_fd) == 0);
	assert(unlink(lock_path) == 0);
	assert(symlink("target", lock_path) == 0);
	recovery_fd = swapz_primary_recovery_base_open(
		base_template, geteuid());
	assert(recovery_fd >= 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid()) < 0);
	assert(unlink(lock_path) == 0);
	first_lock = open(target_path, O_WRONLY | O_CREAT | O_EXCL, 0600);
	assert(first_lock >= 0);
	assert(close(first_lock) == 0);
	assert(unlink(target_path) == 0);
	first_lock = openat(recovery_fd, "partition-7fb9401d-04.lock",
			    O_RDWR | O_CREAT | O_EXCL, 0600);
	assert(first_lock >= 0);
	assert(fchmod(first_lock, 0644) == 0);
	assert(close(first_lock) == 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "7fb9401d-04", geteuid()) < 0);
	assert(unlink(lock_path) == 0);
	assert(swapz_primary_partition_lock_at(
		recovery_fd, "../sda4", geteuid()) < 0);
	assert(unlinkat(recovery_fd, active_name, 0) == 0);
	assert(unlinkat(recovery_fd, consumed_name, 0) == 0);
	assert(unlinkat(recovery_fd, next_consumed_name, 0) == 0);
	assert(unlinkat(recovery_fd, "primary-state.json", 0) == 0);
	assert(unlinkat(recovery_fd, "state-link", 0) == 0);
	assert(unlinkat(recovery_fd, "state-target", 0) == 0);
	assert(fsync(recovery_fd) == 0);
	assert(close(recovery_fd) == 0);
	assert(chmod(base_template, 0755) == 0);
	assert(swapz_primary_recovery_base_open(
		base_template, geteuid()) < 0);
	assert(chmod(base_template, 0700) == 0);
	assert(rmdir(base_template) == 0);
	assert(swapz_primary_command(1, plan) == 2);
	assert(swapz_primary_command(1, prepare) == 2);
	assert(swapz_primary_command(1, start) == 2);
	assert(swapz_primary_command(1, stop) == 2);
	assert(swapz_primary_command(1, recover) == 2);
	puts("PASS: primary swap inventory, capacity, durable stage transitions, owner claims and disabled lifecycle gate");
	return 0;
}
