// SPDX-License-Identifier: GPL-2.0-only
#define SWAPZ_PRIMARY_ROOTLESS_TEST 1
#define SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256 \
	"5832d55be0de0c8ee1dba91f8e61962b9b74cba7d393e937db96bf16d1a925d5"
#define TEST_PARTUUID "7fb9401d-04"
#define TEST_DEVICE_BYTES (16ULL * 1024ULL * 1024ULL * 1024ULL)
#define TEST_SWAP_SIZE_KIB 16777212ULL
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
#include <sys/wait.h>
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

static void test_execution_record_is_boot_source_and_target_bound(void)
{
	static const char boot_id[] = "11111111-2222-3333-4444-555555555555";
	static const char source_sha[] =
		"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
	static const char partuuid[] = "f13428f6-01";
	static const char valid_record[] =
		"schema=swapz-primary-execution-v2\n"
		"boot_id=11111111-2222-3333-4444-555555555555\n"
		"source_sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
		"partuuid=f13428f6-01\n"
		"target_device=8:1\n"
		"target_size_bytes=17179869184\n";
	char changed_record[sizeof(valid_record)];

	assert(swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		partuuid, 8U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U,
		"11111111-2222-3333-4444-555555555556", source_sha,
		partuuid, 8U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id,
		"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		partuuid, 8U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		"f13428f6-02", 8U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		partuuid, 9U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		partuuid, 8U, 2U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		partuuid, 0U, 1U, 17179869184ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 1U, boot_id, source_sha,
		partuuid, 8U, 1U, 17179869185ULL));
	assert(!swapz_primary_execution_record_matches(
		valid_record, sizeof(valid_record) - 2U, boot_id, source_sha,
		partuuid, 8U, 1U, 17179869184ULL));

	memcpy(changed_record, valid_record, sizeof(valid_record));
	changed_record[0] = 'S';
	assert(!swapz_primary_execution_record_matches(
		changed_record, sizeof(changed_record) - 1U, boot_id, source_sha,
		partuuid, 8U, 1U, 17179869184ULL));
	assert(!swapz_primary_boot_id_valid(
		"11111111-2222-3333-4444-55555555555g"));
	assert(!swapz_primary_boot_id_valid(
		"111111112222-3333-4444-555555555555"));
}

static struct swapz_primary_shared_root_scope make_shared_root_scope(void)
{
	struct swapz_primary_shared_root_scope scope = {0};

	memset(scope.host_identity_sha256, 'a', 64U);
	scope.host_identity_sha256[64] = '\0';
	scope.root.device_major = 8U;
	scope.root.device_minor = 3U;
	scope.root.partition_number = 3U;
	scope.root.start_sectors = 1100000ULL;
	scope.root.size_sectors = 100000ULL;
	scope.root.size_bytes = scope.root.size_sectors * 512ULL;
	strcpy(scope.root.partuuid, "7fb9401d-03");
	strcpy(scope.root.parttype, "0x83");
	strcpy(scope.root.partscheme, "dos");
	strcpy(scope.root.part_table_uuid, "7fb9401d");
	strcpy(scope.root.part_table_type, "dos");
	scope.target.device_major = 8U;
	scope.target.device_minor = 4U;
	scope.target.partition_number = 4U;
	scope.target.start_sectors = 1300000ULL;
	scope.target.size_sectors = 65536ULL;
	scope.target.size_bytes = scope.target.size_sectors * 512ULL;
	strcpy(scope.target.partuuid, "7fb9401d-04");
	strcpy(scope.target.parttype, "0x82");
	strcpy(scope.target.partscheme, "dos");
	strcpy(scope.target.part_table_uuid, "7fb9401d");
	strcpy(scope.target.part_table_type, "dos");
	scope.parent_major = 8U;
	scope.parent_minor = 0U;
	scope.parent_size_sectors = 4000000ULL;
	memset(scope.parent_identity_sha256, 'c', 64U);
	scope.parent_identity_sha256[64] = '\0';
	memset(scope.partition_layout_sha256, 'd', 64U);
	scope.partition_layout_sha256[64] = '\0';
	return scope;
}

static void test_shared_root_scope_requires_physical_host_uuid(void)
{
	char normalized[37];
	static const char uppercase_uuid[] =
		"00112233-4455-6677-8899-AABBCCDDEEFF";
	static const char zero_uuid[] =
		"00000000-0000-0000-0000-000000000000";
	static const char malformed_uuid[] =
		"00112233_4455-6677-8899-aabbccddeeff";

	assert(swapz_primary_host_uuid_normalize(
		uppercase_uuid, sizeof(uppercase_uuid) - 1U, normalized) == 0);
	assert(!strcmp(normalized, "00112233-4455-6677-8899-aabbccddeeff"));
	assert(swapz_primary_host_uuid_normalize(
		zero_uuid, sizeof(zero_uuid) - 1U, normalized) < 0);
	assert(swapz_primary_host_uuid_normalize(
		malformed_uuid, sizeof(malformed_uuid) - 1U, normalized) < 0);
	assert(swapz_primary_host_uuid_normalize(
		uppercase_uuid, sizeof(uppercase_uuid) - 2U, normalized) < 0);
}

static void assert_shared_root_record_rejects_scope(
	const char *record, size_t record_length,
	const struct swapz_primary_shared_root_scope *scope)
{
	char digest[65];

	if (swapz_primary_shared_root_scope_sha256(scope, digest) < 0)
		return;
	assert(!swapz_primary_shared_root_scope_record_matches(
		record, record_length, digest));
}

static void test_shared_root_sysfs_layout_skips_attribute_files(void)
{
	char directory[] = "/tmp/swapz-scope-layout-XXXXXX";
	char attribute_path[PATH_MAX];
	char attribute_partition_path[PATH_MAX];
	char partition_path[PATH_MAX];
	char symlink_path[PATH_MAX];
	char missing_path[PATH_MAX];
	int attribute_fd;
	int length;

	assert(mkdtemp(directory));
	length = snprintf(attribute_path, sizeof(attribute_path),
			  "%s/uevent", directory);
	assert(length > 0 && (size_t)length < sizeof(attribute_path));
	length = snprintf(attribute_partition_path,
			  sizeof(attribute_partition_path), "%s/partition",
			  attribute_path);
	assert(length > 0 &&
	       (size_t)length < sizeof(attribute_partition_path));
	length = snprintf(partition_path, sizeof(partition_path),
			  "%s/sda4", directory);
	assert(length > 0 && (size_t)length < sizeof(partition_path));
	length = snprintf(symlink_path, sizeof(symlink_path),
			  "%s/sda4-link", directory);
	assert(length > 0 && (size_t)length < sizeof(symlink_path));
	length = snprintf(missing_path, sizeof(missing_path),
			  "%s/missing", directory);
	assert(length > 0 && (size_t)length < sizeof(missing_path));

	attribute_fd = open(attribute_path,
			    O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	assert(attribute_fd >= 0);
	assert(close(attribute_fd) == 0);
	assert(swapz_primary_sysfs_entry_is_directory(attribute_path) == 0);
	errno = 0;
	assert(lstat(attribute_partition_path, &(struct stat){0}) < 0);
	assert(errno == ENOTDIR);
	assert(mkdir(partition_path, 0700) == 0);
	assert(swapz_primary_sysfs_entry_is_directory(partition_path) == 1);
	assert(symlink(partition_path, symlink_path) == 0);
	assert(swapz_primary_sysfs_entry_is_directory(symlink_path) == 0);
	errno = 0;
	assert(swapz_primary_sysfs_entry_is_directory(missing_path) < 0);
	assert(errno == ENOENT);

	assert(unlink(symlink_path) == 0);
	assert(rmdir(partition_path) == 0);
	assert(unlink(attribute_path) == 0);
	assert(rmdir(directory) == 0);
}

static void test_shared_root_scope_authorization_is_exact(void)
{
	struct swapz_primary_shared_root_scope scope = make_shared_root_scope();
	char digest[65];
	char record[SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_BYTES];
	int length;
	dev_t shared_parent = makedev(8U, 0U);

	assert(swapz_primary_partition_scope_valid(&scope.root));
	assert(swapz_primary_partition_scope_valid(&scope.target));
	assert(swapz_primary_valid_sha256(scope.host_identity_sha256));
	assert(swapz_primary_valid_sha256(scope.parent_identity_sha256));
	assert(swapz_primary_valid_sha256(scope.partition_layout_sha256));
	test_shared_root_scope_requires_physical_host_uuid();
	assert(swapz_primary_shared_root_scope_sha256(&scope, digest) == 0);
	length = snprintf(record, sizeof(record),
			  "schema=swapz-primary-shared-root-v1\n"
			  "scope_sha256=%s\n", digest);
	assert(length > 0 && (size_t)length < sizeof(record));
	assert(swapz_primary_shared_root_scope_record_matches(
		record, (size_t)length, digest));
	assert(swapz_primary_shared_root_parent_relationship_valid(
		shared_parent, shared_parent));
	assert(swapz_primary_runtime_state_fs_magic(TMPFS_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(EXT2_SUPER_MAGIC));

	/* Host, root, target, device, geometry, parent and layout are all bound. */
	scope.host_identity_sha256[0] = 'e';
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.root.partuuid[0] = 'e';
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.root.partition_number++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.root.start_sectors++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.root.size_sectors++;
	scope.root.size_bytes += 512ULL;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.root.device_minor++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.partuuid[0] = 'e';
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.device_minor++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.start_sectors++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.partition_number++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.partuuid[10] = '5';
	assert(swapz_primary_shared_root_scope_sha256(&scope, digest) < 0);
	scope = make_shared_root_scope();
	strcpy(scope.target.parttype, "0x100");
	assert(swapz_primary_shared_root_scope_sha256(&scope, digest) < 0);
	scope = make_shared_root_scope();
	strcpy(scope.target.part_table_uuid, "7fb9401e");
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.target.size_bytes += 512ULL;
	assert(swapz_primary_shared_root_scope_sha256(&scope, digest) < 0);
	scope = make_shared_root_scope();
	scope.parent_identity_sha256[0] = 'e';
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.parent_major++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.parent_minor++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.parent_size_sectors++;
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);
	scope = make_shared_root_scope();
	scope.partition_layout_sha256[0] = 'e';
	assert_shared_root_record_rejects_scope(record, (size_t)length, &scope);

	scope = make_shared_root_scope();
	assert(!swapz_primary_shared_root_parent_relationship_valid(
		makedev(8U, 16U), shared_parent));
	assert(errno == EPERM);
	assert(!swapz_primary_shared_root_parent_relationship_valid(
		shared_parent, makedev(8U, 16U)));
	assert(errno == EPERM);
	assert(!swapz_primary_shared_root_scope_record_matches(
		"schema=swapz-primary-shared-root-v1\n", 36U, digest));

	assert(!swapz_primary_shared_root_scope_record_matches(
		record, (size_t)length - 1U, digest));
	assert(!swapz_primary_shared_root_scope_record_matches(
		"schema=swapz-primary-shared-root-v1\n"
		"scope_sha256=invalid\n", 56U, digest));
	{
		char ambiguous[256];
		int ambiguous_length = snprintf(
			ambiguous, sizeof(ambiguous),
			"schema=swapz-primary-shared-root-v1\n"
			"scope_sha256=%s\n"
			"scope_sha256=%s\n", digest, digest);

		assert(ambiguous_length > 0 &&
		       (size_t)ambiguous_length < sizeof(ambiguous));
		assert(!swapz_primary_shared_root_scope_record_matches(
			ambiguous, (size_t)ambiguous_length, digest));
	}
}

static void test_shared_root_scope_rejects_overlapping_partition_layout(void)
{
	struct swapz_primary_shared_root_scope scope = make_shared_root_scope();
	struct swapz_primary_partition_scope partitions[3] = {0};

	partitions[0] = scope.root;
	partitions[1] = scope.target;
	partitions[2] = scope.root;
	partitions[2].device_major = 8U;
	partitions[2].device_minor = 2U;
	partitions[2].partition_number = 2U;
	partitions[2].start_sectors = 2048ULL;
	partitions[2].size_sectors = 100000ULL;
	partitions[2].size_bytes = partitions[2].size_sectors * 512ULL;
	strcpy(partitions[2].partuuid, "7fb9401d-02");
	strcpy(partitions[2].parttype, "0x83");
	strcpy(partitions[2].partscheme, "dos");
	strcpy(partitions[2].part_table_uuid, "7fb9401d");
	strcpy(partitions[2].part_table_type, "dos");
	assert(swapz_primary_partition_scope_layout_valid(
		partitions, 3U, scope.parent_size_sectors, &scope.root,
		&scope.target));
	partitions[1].start_sectors =
		partitions[0].start_sectors + partitions[0].size_sectors - 1ULL;
	assert(!swapz_primary_partition_scope_layout_valid(
		partitions, 3U, scope.parent_size_sectors, &scope.root,
		&scope.target));
	partitions[1] = scope.target;
	partitions[1].start_sectors = scope.parent_size_sectors -
		partitions[1].size_sectors + 1ULL;
	assert(!swapz_primary_partition_scope_layout_valid(
		partitions, 3U, scope.parent_size_sectors, &scope.root,
		&scope.target));
}

static void test_shared_root_scope_record_requires_private_regular_file(void)
{
	struct swapz_primary_shared_root_scope scope = make_shared_root_scope();
	char directory[] = "/tmp/swapz-root-scope-XXXXXX";
	char digest[65];
	char record[SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_BYTES];
	int length;
	int directory_fd;
	int record_fd;

	assert(swapz_primary_shared_root_scope_sha256(&scope, digest) == 0);
	length = snprintf(record, sizeof(record),
			  "schema=swapz-primary-shared-root-v1\n"
			  "scope_sha256=%s\n", digest);
	assert(length > 0 && (size_t)length < sizeof(record));
	assert(mkdtemp(directory));
	directory_fd = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
	assert(directory_fd >= 0);
	record_fd = openat(directory_fd,
			   SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
			   O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
	assert(record_fd >= 0);
	assert(write(record_fd, record, (size_t)length) == length);
	assert(close(record_fd) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid() == 0U ? 1U : 0U, digest) < 0);
	assert(errno == EPERM);
	assert(fchmodat(directory_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
			0640, 0) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) < 0);
	assert(errno == EPERM);
	assert(fchmodat(directory_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
			0600, 0) == 0);
	assert(linkat(directory_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
		      directory_fd, "scope-hardlink", 0) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) < 0);
	assert(errno == EPERM);
	assert(unlinkat(directory_fd, "scope-hardlink", 0) == 0);
	assert(fchmod(directory_fd, 0720) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) < 0);
	assert(errno == EPERM);
	assert(fchmod(directory_fd, 0700) == 0);
	assert(unlinkat(directory_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
			0) == 0);
	assert(symlinkat("missing", directory_fd,
			 SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) < 0);
	assert(errno == ELOOP);
	assert(unlinkat(directory_fd, SWAPZ_PRIMARY_ROOT_PARENT_SCOPE_RECORD_NAME,
			0) == 0);
	assert(swapz_primary_shared_root_scope_record_read_at(
		directory_fd, geteuid(), digest) < 0);
	assert(errno == ENOENT);
	assert(close(directory_fd) == 0);
	assert(rmdir(directory) == 0);
}

static void test_partuuid_validation_and_normalization(void)
{
	static const char *const invalid_partuuids[] = {
		"--------",
		"-f13428f6",
		"f13428f6-",
		"f13428f6--01",
		"1234567",
		"1234-567",
		"1234567g",
		"not-a-partuuid",
	};
	static const char uppercase_mbr[] = "7FB9401D-04";
	static const char uppercase_gpt[] = "550E8400-E29B-41D4-A716-446655440000";
	static const char canonical_gpt[] = "550e8400-e29b-41d4-a716-446655440000";
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char parsed[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char overlength[SWAPZ_PRIMARY_PARTUUID_LENGTH + 2U];
	char device_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	char swap_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	char record[sizeof("PARTUUID=") + SWAPZ_PRIMARY_PARTUUID_LENGTH + 2U];
	size_t index;
	int length;

	for (index = 0;
	     index < sizeof(invalid_partuuids) / sizeof(invalid_partuuids[0]);
	     ++index) {
		memset(normalized, 'x', sizeof(normalized));
		errno = 0;
		assert(!swapz_primary_partuuid_valid(invalid_partuuids[index]));
		assert(swapz_primary_partuuid_normalize(
			       invalid_partuuids[index], normalized) < 0);
		assert(errno == EINVAL && normalized[0] == '\0');

		memset(parsed, 'x', sizeof(parsed));
		length = snprintf(record, sizeof(record), "PARTUUID=%s\n",
				  invalid_partuuids[index]);
		assert(length > 0 && (size_t)length < sizeof(record));
		errno = 0;
		assert(swapz_primary_target_config_parse(
			       record, (size_t)length, parsed) < 0);
		assert(errno == EINVAL && parsed[0] == '\0');
	}

	memset(overlength, 'a', sizeof(overlength) - 1U);
	overlength[sizeof(overlength) - 1U] = '\0';
	assert(!swapz_primary_partuuid_valid(overlength));
	assert(swapz_primary_partuuid_normalize(overlength, normalized) < 0);
	assert(errno == EINVAL && normalized[0] == '\0');
	length = snprintf(record, sizeof(record), "PARTUUID=%s\n", overlength);
	assert(length > 0 && (size_t)length < sizeof(record));
	memset(parsed, 'x', sizeof(parsed));
	errno = 0;
	assert(swapz_primary_target_config_parse(
		       record, (size_t)length, parsed) < 0);
	assert(errno == EINVAL && parsed[0] == '\0');

	assert(swapz_primary_partuuid_valid("01234567"));
	assert(swapz_primary_partuuid_normalize(
		       uppercase_mbr, normalized) == 0);
	assert(!strcmp(normalized, "7fb9401d-04"));
	assert(swapz_primary_partuuid_normalize(
		       uppercase_gpt, normalized) == 0);
	assert(!strcmp(normalized, canonical_gpt));

	length = snprintf(record, sizeof(record), "PARTUUID=%s\n",
			  uppercase_gpt);
	assert(length > 0 && (size_t)length < sizeof(record));
	assert(swapz_primary_target_config_parse(
		       record, (size_t)length, parsed) == 0);
	assert(!strcmp(parsed, canonical_gpt));

	assert(swapz_primary_systemd_target_units(
		       uppercase_gpt, device_unit, swap_unit) == 0);
	assert(!strcmp(
		device_unit,
		"dev-disk-by\\x2dpartuuid-550e8400\\x2de29b\\x2d41d4"
		"\\x2da716\\x2d446655440000.device"));
	assert(!strcmp(
		swap_unit,
		"dev-disk-by\\x2dpartuuid-550e8400\\x2de29b\\x2d41d4"
		"\\x2da716\\x2d446655440000.swap"));

	memset(device_unit, 'x', sizeof(device_unit));
	memset(swap_unit, 'x', sizeof(swap_unit));
	assert(swapz_primary_systemd_target_units(
		       "f13428f6--01", device_unit, swap_unit) < 0);
	assert(errno == EINVAL);
	assert(device_unit[0] == '\0' && swap_unit[0] == '\0');
}

static void test_recovery_required_state_builder(void)
{
	const char *run_id = "0123456789abcdef0123456789abcdef";
	struct swapz_primary_state current = {0};
	struct swapz_primary_state recovery_required = {0};
	struct swapz_primary_state unchanged;

	memcpy(current.run_id, run_id, SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U);
	current.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert(swapz_primary_recovery_required_state(
		&current, &recovery_required) == 0);
	assert(recovery_required.stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED);
	assert(recovery_required.has_recovery_previous_stage);
	assert(recovery_required.recovery_previous_stage ==
	       SWAPZ_PRIMARY_STAGE_STARTING);

	current = recovery_required;
	current.stage = SWAPZ_PRIMARY_STAGE_RECOVERING;
	memset(&recovery_required, 0, sizeof(recovery_required));
	assert(swapz_primary_recovery_required_state(
		&current, &recovery_required) == 0);
	assert(recovery_required.stage == SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED);
	assert(recovery_required.has_recovery_previous_stage);
	assert(recovery_required.recovery_previous_stage ==
	       SWAPZ_PRIMARY_STAGE_STARTING);

	current.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	unchanged = recovery_required;
	errno = 0;
	assert(swapz_primary_recovery_required_state(
		&current, &recovery_required) < 0);
	assert(errno == EINVAL);
	assert(!memcmp(&recovery_required, &unchanged,
		       sizeof(recovery_required)));
}

struct primary_swap_transition_fixture {
	dev_t mapper_device;
	dev_t backing_device;
	int mapper_active;
	int backing_active;
	int swapon_result;
	int swapon_errno;
	int swapon_applies;
	int swapon_activates_backing;
	int swapoff_result;
	int swapoff_errno;
	int swapoff_applies;
	int active_calls;
	int fail_active_call;
	int swapon_calls;
	int swapoff_calls;
	char path[64];
};

static int primary_swap_transition_active(void *context,
						 dev_t expected_device)
{
	struct primary_swap_transition_fixture *fixture = context;
	++fixture->active_calls;
	if (fixture->active_calls == fixture->fail_active_call) {
		errno = EIO;
		return -1;
	}
	if (expected_device == fixture->mapper_device)
		return fixture->mapper_active;
	if (expected_device == fixture->backing_device)
		return fixture->backing_active;
	errno = ENODEV;
	return -1;
}

static long primary_swap_transition_swapon(void *context,
						   const char *mapper_path)
{
	struct primary_swap_transition_fixture *fixture = context;
	++fixture->swapon_calls;
	assert(strlen(mapper_path) < sizeof(fixture->path));
	strcpy(fixture->path, mapper_path);
	if (fixture->swapon_applies) {
		fixture->mapper_active = 1;
		if (fixture->swapon_activates_backing)
			fixture->backing_active = 1;
	}
	if (fixture->swapon_result < 0)
		errno = fixture->swapon_errno;
	return fixture->swapon_result;
}

static long primary_swap_transition_swapoff(void *context,
						    const char *mapper_path)
{
	struct primary_swap_transition_fixture *fixture = context;
	++fixture->swapoff_calls;
	assert(strlen(mapper_path) < sizeof(fixture->path));
	strcpy(fixture->path, mapper_path);
	if (fixture->swapoff_applies)
		fixture->mapper_active = 0;
	if (fixture->swapoff_result < 0)
		errno = fixture->swapoff_errno;
	return fixture->swapoff_result;
}

static void primary_swap_transition_fixture_init(
	struct primary_swap_transition_fixture *fixture)
{
	memset(fixture, 0, sizeof(*fixture));
	fixture->mapper_device = makedev(253, 91);
	fixture->backing_device = makedev(8, 4);
	fixture->swapon_applies = 1;
	fixture->swapoff_applies = 1;
}

static struct swapz_primary_swap_transition_ops
primary_swap_transition_ops(struct primary_swap_transition_fixture *fixture)
{
	struct swapz_primary_swap_transition_ops ops = {
		.device_active = primary_swap_transition_active,
		.swapon = primary_swap_transition_swapon,
		.swapoff = primary_swap_transition_swapoff,
		.context = fixture,
	};

	return ops;
}

static void test_primary_swap_transition_adapter(void)
{
	const char *path = "/proc/self/fd/55";
	struct primary_swap_transition_fixture fixture;
	struct swapz_primary_swap_transition_ops ops;
	int verified;

	primary_swap_transition_fixture_init(&fixture);
	ops = primary_swap_transition_ops(&fixture);
	verified = 9;
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) == 0);
	assert(verified == 1 && fixture.swapon_calls == 1);
	assert(fixture.mapper_active && !fixture.backing_active);
	assert(!strcmp(fixture.path, path));

	primary_swap_transition_fixture_init(&fixture);
	fixture.swapon_result = -1;
	fixture.swapon_errno = EPERM;
	fixture.swapon_applies = 0;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EPERM && verified == 0 && fixture.swapon_calls == 1);
	assert(!fixture.mapper_active);

	/* A definite syscall error stays a failure even if inventory shows active. */
	primary_swap_transition_fixture_init(&fixture);
	fixture.swapon_result = -1;
	fixture.swapon_errno = EPERM;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EPERM && verified == 0 && fixture.swapon_calls == 1);
	assert(fixture.mapper_active);

	/* A zero syscall result is insufficient when inventory cannot be read. */
	primary_swap_transition_fixture_init(&fixture);
	fixture.fail_active_call = 3;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EIO && verified == 0 && fixture.swapon_calls == 1);
	assert(fixture.mapper_active);

	/* EINTR is reconciled only if exact post-operation inventory is active. */
	primary_swap_transition_fixture_init(&fixture);
	fixture.swapon_result = -1;
	fixture.swapon_errno = EINTR;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) == 0);
	assert(verified == 1 && fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	fixture.swapon_result = -1;
	fixture.swapon_errno = EINTR;
	fixture.swapon_applies = 0;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EINTR && verified == 0 && !fixture.mapper_active);

	/* Existing active state and raw-backing activation both refuse swapon. */
	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EBUSY && verified == 0 && !fixture.swapon_calls);

	primary_swap_transition_fixture_init(&fixture);
	fixture.backing_active = 1;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EBUSY && verified == 0 && !fixture.swapon_calls);

	primary_swap_transition_fixture_init(&fixture);
	fixture.swapon_activates_backing = 1;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		1, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EBUSY && verified == 0 && fixture.mapper_active &&
	       fixture.backing_active);

	/* Failed swapoff or unreadable/active post-state never authorizes removal. */
	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) == 0);
	assert(verified == 1 && fixture.swapoff_calls == 1 &&
	       !fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	fixture.swapoff_applies = 0;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EBUSY && verified == 0 && fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	fixture.swapoff_result = -1;
	fixture.swapoff_errno = EBUSY;
	fixture.swapoff_applies = 0;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EBUSY && verified == 0 && fixture.mapper_active &&
	       fixture.swapoff_calls == 1);

	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	fixture.swapoff_result = -1;
	fixture.swapoff_errno = EINTR;
	ops = primary_swap_transition_ops(&fixture);
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) == 0);
	assert(verified == 1 && !fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	fixture.swapoff_result = -1;
	fixture.swapoff_errno = EINTR;
	fixture.swapoff_applies = 0;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EINTR && verified == 0 && fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	fixture.mapper_active = 1;
	fixture.fail_active_call = 3;
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	errno = 0;
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) < 0);
	assert(errno == EIO && verified == 0 && !fixture.mapper_active);

	primary_swap_transition_fixture_init(&fixture);
	ops = primary_swap_transition_ops(&fixture);
	verified = 7;
	assert(swapz_primary_swap_transition_apply(
		0, fixture.mapper_device, fixture.backing_device, path,
		&ops, &verified) == 0);
	assert(verified == 0 && fixture.swapoff_calls == 0);
}

static void test_swap_inventory_parser(void)
{
	static const char *const invalid_priorities[] = {
		"", "-", "+1", "--1", "1x", "2147483648",
		"-2147483649", "18446744073709551616",
		"-18446744073709551616",
	};
	struct swapz_primary_swap_entry rows[4];
	size_t count = 0;
	size_t index;
	int priority;

	/* Preserve the original raw swap priority policy. Invalid inventory
	 * must not modify the output used by later lifecycle admission. */
	priority = 99;
	assert(swapz_primary_parse_priority("2147483647", &priority) == 0);
	assert(priority == INT_MAX);
	assert(swapz_primary_parse_priority("-2147483648", &priority) == 0);
	assert(priority == INT_MIN);
	assert(swapz_primary_parse_priority("0", &priority) == 0);
	assert(priority == 0);
	assert(swapz_primary_parse_priority("-0", &priority) == 0);
	assert(priority == 0);
	for (index = 0; index < sizeof(invalid_priorities) /
			   sizeof(invalid_priorities[0]); ++index) {
		priority = 99;
		assert(swapz_primary_parse_priority(
			invalid_priorities[index], &priority) < 0);
		assert(priority == 99);
	}
	assert(swapz_primary_parse_priority(NULL, &priority) < 0);
	assert(swapz_primary_parse_priority("1", NULL) < 0);

	assert(swapz_primary_parse_swaps(
		"Filename Type Size Used Priority\n"
		"/dev/sda4 partition 16777212 0 -1\n",
		rows, 4U, &count) == 0);
	assert(count == 1U);
	assert(!strcmp(rows[0].path, "/dev/sda4"));
	assert(!strcmp(rows[0].type, "partition"));
	assert(rows[0].size_kib == TEST_SWAP_SIZE_KIB);
	assert(rows[0].used_kib == 0ULL);
	assert(rows[0].priority == -1);
	assert(swapz_primary_swap_priority_restorable(-1));
	assert(swapz_primary_swap_priority_restorable(-2));
	assert(swapz_primary_swap_priority_restorable(-32768));
	assert(swapz_primary_swap_priority_restorable(0));
	assert(swapz_primary_swap_priority_restorable(32767));
	assert(!swapz_primary_swap_priority_restorable(32768));
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

static void test_memavailable_parser(void)
{
	uint64_t available_kib = UINT64_MAX;

	assert(swapz_primary_parse_memavailable_kib(
		"MemTotal:       8388608 kB\n"
		"MemAvailable:   1572864 kB\n"
		"SwapTotal:      1048576 kB\n",
		&available_kib) == 0);
	assert(available_kib == 1572864ULL);

	available_kib = UINT64_MAX;
	errno = 0;
	assert(swapz_primary_parse_memavailable_kib(
		"MemTotal: 8388608 kB\n", &available_kib) < 0);
	assert(errno == ENODATA);
	assert(available_kib == UINT64_MAX);

	errno = 0;
	assert(swapz_primary_parse_memavailable_kib(
		"MemAvailable: 1024 kB\n"
		"MemAvailable: 1024 kB\n",
		&available_kib) < 0);
	assert(errno == EINVAL);

	errno = 0;
	assert(swapz_primary_parse_memavailable_kib(
		"MemAvailable: 1024 MB\n", &available_kib) < 0);
	assert(errno == EINVAL);
}

static void test_selected_target_swap_admission(void)
{
	struct swapz_primary_swap_entry rows[3] = {0};
	dev_t devices[3] = {0};
	unsigned char is_block[3] = {0};

	strcpy(rows[0].path, "/swapfile");
	strcpy(rows[0].type, "file");
	rows[0].size_kib = 524284U;
	rows[0].used_kib = 123U;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 1U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) == 0);
	devices[0] = makedev(8, 4);
	errno = 0;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 1U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) < 0);
	assert(errno == EBUSY);
	devices[0] = 0;

	strcpy(rows[1].path, "/dev/target-alias");
	strcpy(rows[1].type, "partition");
	rows[1].size_kib = TEST_SWAP_SIZE_KIB;
	rows[1].used_kib = 0U;
	devices[1] = makedev(8, 4);
	is_block[1] = 1U;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 2U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) == 0);

	/* Used pages are ordinary active-swap state. START owns migration. */
	rows[1].used_kib = 1U;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 2U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) == 0);
	rows[1].used_kib = 0U;
	--rows[1].size_kib;
	errno = 0;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 2U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) < 0);
	assert(errno == EBUSY);
	++rows[1].size_kib;

	rows[2] = rows[1];
	strcpy(rows[2].path, "/dev/target-second-alias");
	devices[2] = devices[1];
	is_block[2] = 1U;
	errno = 0;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		rows, devices, is_block, 3U, makedev(8, 4),
		TEST_SWAP_SIZE_KIB) < 0);
	assert(errno == EBUSY);
}

static void test_put_u32_le(unsigned char *buffer, size_t offset,
			   uint32_t value);

static void test_target_identity_and_header_policy(void)
{
	unsigned char block[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	static const unsigned char swap_magic[] = "SWAPSPACE2";
	const uint64_t logical_pages =
		TEST_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES;

	assert(swapz_primary_device_number_matches(makedev(8, 4)));
	assert(swapz_primary_device_number_matches(makedev(259, 18)));
	assert(swapz_primary_device_number_matches(makedev(252, 0)));
	assert(!swapz_primary_device_number_matches(makedev(0, 3)));

	test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_VERSION_OFFSET, 1U);
	test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_LAST_PAGE_OFFSET,
			(uint32_t)(logical_pages - 1U));
	test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 0U);
	memcpy(block + sizeof(block) - sizeof(swap_magic) + 1U,
	       swap_magic, sizeof(swap_magic) - 1U);
	assert(swapz_primary_original_swap_signature(block,
						    TEST_DEVICE_BYTES));
	assert(swapz_primary_physical_blocks_from_header(
		       block, TEST_DEVICE_BYTES) ==
	       swapz_primary_physical_blocks(TEST_DEVICE_BYTES));
	assert(swapz_primary_swap_size_kib_from_header(
		       block, TEST_DEVICE_BYTES) == TEST_SWAP_SIZE_KIB);

	/* Two bad pages in one 1MiB segment cost one swapz segment, while Linux
	 * /proc/swaps charges both listed pages from its raw usable-page count. */
	test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 2U);
	test_put_u32_le(block, SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET, 257U);
	test_put_u32_le(block, SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET +
			sizeof(uint32_t), 258U);
	assert(swapz_primary_physical_blocks_from_header(
		       block, TEST_DEVICE_BYTES) ==
	       swapz_primary_physical_blocks(TEST_DEVICE_BYTES) -
		       SWAPZ_PRIMARY_SEGMENT_BLOCKS);
	assert(swapz_primary_swap_size_kib_from_header(
		       block, TEST_DEVICE_BYTES) == TEST_SWAP_SIZE_KIB - 8U);

	/* A listed bad page in the already-unused segment-alignment tail does
	 * not reduce swapz capacity again. */
	test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 1U);
	test_put_u32_le(block, SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET,
			(uint32_t)(logical_pages - 1U));
	assert(swapz_primary_physical_blocks_from_header(
		       block, TEST_DEVICE_BYTES) ==
	       swapz_primary_physical_blocks(TEST_DEVICE_BYTES));
		test_put_u32_le(block, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 0U);
	/* SWAPSPACE2 capacity is whole-page based. A normal block partition may
	 * have a sub-page tail, which remains outside swapz's writable range.
	 */
	assert(swapz_primary_original_swap_signature(
		block, TEST_DEVICE_BYTES + 511U));
	block[SWAPZ_PRIMARY_SWAP_VERSION_OFFSET] = 2U;
	assert(!swapz_primary_original_swap_signature(block,
						     TEST_DEVICE_BYTES));
}



/*
 * A rootless read hook forces replacement exactly after the real reader has
 * parsed its opened descriptor but before its final live-name identity check.
 */
static const char selector_race_record[] = "PARTUUID=7fb9401d-04\n";
static char selector_race_config_directory[PATH_MAX];
static char selector_race_old_directory[PATH_MAX];
static struct stat selector_race_before;
static struct stat selector_race_after;
static int selector_race_directory_fd = -1;
static int selector_race_kind;

static void test_selector_write_file(int directory_fd)
{
	int fd = openat(directory_fd, "primary-target",
			O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);

	assert(fd >= 0);
	assert(write(fd, selector_race_record,
		     sizeof(selector_race_record) - 1U) ==
	       (ssize_t)(sizeof(selector_race_record) - 1U));
	assert(close(fd) == 0);
}

static void test_selector_replace_before_revalidation(void)
{
	if (selector_race_kind == 1) {
		assert(fstatat(selector_race_directory_fd, "primary-target",
			       &selector_race_before, AT_SYMLINK_NOFOLLOW) == 0);
		assert(renameat(selector_race_directory_fd, "primary-target",
				selector_race_directory_fd,
				"primary-original") == 0);
		test_selector_write_file(selector_race_directory_fd);
		assert(fstatat(selector_race_directory_fd, "primary-target",
			       &selector_race_after, AT_SYMLINK_NOFOLLOW) == 0);
	} else if (selector_race_kind == 2) {
		int new_directory_fd;

		assert(stat(selector_race_config_directory,
			    &selector_race_before) == 0);
		assert(rename(selector_race_config_directory,
			      selector_race_old_directory) == 0);
		assert(mkdir(selector_race_config_directory, 0700) == 0);
		new_directory_fd = open(selector_race_config_directory,
					O_RDONLY | O_DIRECTORY |
					O_NOFOLLOW | O_CLOEXEC);
		assert(new_directory_fd >= 0);
		test_selector_write_file(new_directory_fd);
		assert(stat(selector_race_config_directory,
			    &selector_race_after) == 0);
		assert(close(new_directory_fd) == 0);
	} else {
		assert(!"unexpected selector replacement case");
	}
}

static void test_selector_rejects_replaced_file_and_directory(void)
{
	char template_directory[] = "/tmp/swapz-selector-identity-XXXXXX";
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	struct swapz_primary_target selected_before =
		swapz_primary_selected_target;
	int replacement_directory_fd;
	int length;

	assert(mkdtemp(template_directory));
	length = snprintf(selector_race_config_directory,
			  sizeof(selector_race_config_directory),
			  "%s", template_directory);
	assert(length > 0 &&
	       (size_t)length < sizeof(selector_race_config_directory));
	length = snprintf(selector_race_old_directory,
			  sizeof(selector_race_old_directory),
			  "%s-old", template_directory);
	assert(length > 0 &&
	       (size_t)length < sizeof(selector_race_old_directory));
	selector_race_directory_fd = open(template_directory,
		O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	assert(selector_race_directory_fd >= 0);
	test_selector_write_file(selector_race_directory_fd);
	swapz_primary_rootless_config_base = selector_race_config_directory;
	assert(swapz_primary_target_config_read(partuuid) == 0);
	assert(!strcmp(partuuid, "7fb9401d-04"));

	/* Replace the regular file with identical bytes after its read. */
	selector_race_kind = 1;
	swapz_primary_rootless_selector_before_revalidation =
		test_selector_replace_before_revalidation;
	strcpy(partuuid, "stale");
	errno = 0;
	assert(swapz_primary_target_config_read(partuuid) < 0);
	assert(errno == ESTALE);
	assert(partuuid[0] == '\0');
	assert(selector_race_before.st_dev == selector_race_after.st_dev);
	assert(selector_race_before.st_ino != selector_race_after.st_ino);
	swapz_primary_rootless_selector_before_revalidation = NULL;
	assert(unlinkat(selector_race_directory_fd,
			"primary-original", 0) == 0);
	assert(swapz_primary_target_config_read(partuuid) == 0);
	assert(!strcmp(partuuid, "7fb9401d-04"));

	/* Replace the entire directory path with a second valid directory. */
	selector_race_kind = 2;
	swapz_primary_rootless_selector_before_revalidation =
		test_selector_replace_before_revalidation;
	strcpy(partuuid, "stale");
	errno = 0;
	assert(swapz_primary_target_config_read(partuuid) < 0);
	assert(errno == ESTALE);
	assert(partuuid[0] == '\0');
	assert(selector_race_before.st_dev == selector_race_after.st_dev);
	assert(selector_race_before.st_ino != selector_race_after.st_ino);
	swapz_primary_rootless_selector_before_revalidation = NULL;
	assert(swapz_primary_target_config_read(partuuid) == 0);
	assert(!strcmp(partuuid, "7fb9401d-04"));
	assert(!memcmp(&swapz_primary_selected_target, &selected_before,
		       sizeof(selected_before)));

	/* Only private test files were touched; no mapper/service path is used. */
	replacement_directory_fd = open(selector_race_config_directory,
		O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
	assert(replacement_directory_fd >= 0);
	assert(unlinkat(replacement_directory_fd, "primary-target", 0) == 0);
	assert(close(replacement_directory_fd) == 0);
	assert(rmdir(selector_race_config_directory) == 0);
	assert(unlinkat(selector_race_directory_fd, "primary-target", 0) == 0);
	assert(close(selector_race_directory_fd) == 0);
	selector_race_directory_fd = -1;
	assert(rmdir(selector_race_old_directory) == 0);
	swapz_primary_rootless_config_base = "/etc/swapz";
	selector_race_kind = 0;
}

static void test_target_config_and_dynamic_geometry(void)
{
	static const char target_one[] = "PARTUUID=1A2B3C4D-01\n";
	static const char target_two[] = "PARTUUID=9abc8def-02\n";
	static const char malformed[] = "PARTUUID=not-a-partition\n";
	const char *run_id = "0123456789abcdef0123456789abcdef";
	struct swapz_primary_target original_target =
		swapz_primary_selected_target;
	struct swapz_primary_target alternate = {
		.partuuid = "9abc8def-02",
		.device_major = 259U,
		.device_minor = 18U,
		.device_bytes = 64ULL * 1024ULL * 1024ULL,
	};
	struct swapz_primary_target zero_minor = {
		.partuuid = "abcd0123-01",
		.device_major = 8U,
		.device_minor = 0U,
		.device_bytes = 128ULL * 1024ULL * 1024ULL,
	};
	struct swapz_primary_manifest manifest = {0};
	struct swapz_primary_manifest parsed = {0};
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];
	char device_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	char swap_unit[SWAPZ_PRIMARY_SYSTEMD_UNIT_NAME_MAX];
	char table[128];
	char mapper_name[64];
	char mapper_uuid[64];
	char record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	uint64_t logical_sectors = 0;
	int length;

	assert(swapz_primary_target_config_parse(
		target_one, sizeof(target_one) - 1U, partuuid) == 0);
	assert(!strcmp(partuuid, "1a2b3c4d-01"));
	assert(swapz_primary_target_config_parse(
		target_two, sizeof(target_two) - 1U, partuuid) == 0);
	assert(!strcmp(partuuid, alternate.partuuid));
	assert(swapz_primary_systemd_target_units(
		"1A2B3C4D-01", device_unit, swap_unit) == 0);
	assert(!strcmp(device_unit,
		       "dev-disk-by\\x2dpartuuid-1a2b3c4d\\x2d01.device"));
	assert(!strcmp(swap_unit,
		       "dev-disk-by\\x2dpartuuid-1a2b3c4d\\x2d01.swap"));
	assert(swapz_primary_systemd_target_units(
		alternate.partuuid, device_unit, swap_unit) == 0);
	assert(!strcmp(device_unit,
		       "dev-disk-by\\x2dpartuuid-9abc8def\\x2d02.device"));
	assert(swapz_primary_systemd_target_units(
		"not-a-partuuid", device_unit, swap_unit) < 0);
	assert(!device_unit[0] && !swap_unit[0]);
	assert(swapz_primary_target_valid(&alternate));
	assert(swapz_primary_target_identity_equal(&alternate, &alternate));
	/* The actual production comparator binds all four target identity
	 * fields, not just a PARTUUID pathname or a device label. */
	{
		struct swapz_primary_target stale = alternate;

		stale.partuuid[0] = '8';
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
		stale = alternate;
		stale.device_major = 8U;
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
		stale = alternate;
		stale.device_minor = 19U;
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
		stale = alternate;
		stale.device_bytes += SWAPZ_PRIMARY_BLOCK_BYTES;
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
		stale = alternate;
		stale.device_bytes += 511U;
		assert(swapz_primary_target_valid(&stale));
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
		assert(swapz_primary_physical_blocks(stale.device_bytes) ==
		       swapz_primary_physical_blocks(alternate.device_bytes));
		stale = alternate;
		stale.partuuid[0] = 'z';
		assert(!swapz_primary_target_identity_equal(&alternate, &stale));
	}
	assert(swapz_primary_target_valid(&zero_minor));
	assert(!swapz_primary_target_identity_equal(&alternate, &zero_minor));
	assert(swapz_primary_target_config_parse(
		malformed, sizeof(malformed) - 1U, partuuid) < 0);
	assert(swapz_primary_target_config_parse(
		"PARTUUID=9abc8def-02", sizeof("PARTUUID=9abc8def-02") - 1U,
		partuuid) < 0);
	assert(swapz_primary_target_config_parse(
		"PARTUUID=9abc8def-02\nextra\n",
		sizeof("PARTUUID=9abc8def-02\nextra\n") - 1U,
		partuuid) < 0);
	assert(swapz_primary_target_inspect(alternate.partuuid, &parsed.target) < 0);
	assert(errno == ENOTSUP);
	memcpy(manifest.run_id, run_id, sizeof(manifest.run_id));
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
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	manifest.target = alternate;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	assert(swapz_primary_mapper_layout(&manifest, mapper_name, mapper_uuid,
					  table, &logical_sectors) == 0);
	assert(strstr(table, "swapz 259:18 ") != NULL);
	assert(logical_sectors ==
	       swapz_primary_maximum_logical_pages(
		       swapz_primary_physical_blocks(alternate.device_bytes)) * 8ULL);
	assert(swapz_primary_manifest_format(
		&manifest, record, sizeof(record)) > 0);
	length = (int)strlen(record);
	assert(swapz_primary_manifest_parse(record, (size_t)length, &parsed) == 0);
	assert(!memcmp(&manifest, &parsed, sizeof(manifest)));
	manifest.target = zero_minor;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	assert(swapz_primary_manifest_format(
		&manifest, record, sizeof(record)) > 0);
	length = (int)strlen(record);
	assert(swapz_primary_manifest_parse(record, (size_t)length, &parsed) == 0);
	assert(!memcmp(&manifest, &parsed, sizeof(manifest)));
	swapz_primary_selected_target = original_target;
}

static void test_target_preflight_snapshots_aliased_partuuid(void)
{
	struct swapz_primary_target original_selected_target =
		swapz_primary_selected_target;
	struct swapz_primary_target target = {
		.partuuid = TEST_PARTUUID,
		.device_major = 8U,
		.device_minor = 4U,
		.device_bytes = TEST_DEVICE_BYTES,
	};
	uint64_t device_bytes = 0;
	int original_swap_header = 0;
	int original_header_digest_available = 0;
	unsigned char original_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};

	/* The production caller passes target.partuuid and &target together. */
	errno = 0;
	assert(swapz_primary_target_preflight(
		target.partuuid, &target, &device_bytes, &original_swap_header,
		&original_header_digest_available, original_header) < 0);
	assert(errno == ENODEV);
	assert(target.partuuid[0] == '\0');
	swapz_primary_selected_target = original_selected_target;
}

static void test_put_u32_le(unsigned char *buffer, size_t offset,
			   uint32_t value)
{
	buffer[offset] = (unsigned char)value;
	buffer[offset + 1U] = (unsigned char)(value >> 8);
	buffer[offset + 2U] = (unsigned char)(value >> 16);
	buffer[offset + 3U] = (unsigned char)(value >> 24);
}

static void test_primary_linux_swap_header(void)
{
	static const unsigned char magic[] = "SWAPSPACE2";
	const uint64_t logical_pages =
		swapz_primary_maximum_logical_pages(swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES));
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};

	test_put_u32_le(header, 1024U, 1U);
	test_put_u32_le(header, 1028U, (uint32_t)(logical_pages - 1U));
	header[1036U] = 1U;
	memcpy(header + sizeof(header) - sizeof(magic) + 1U,
	       magic, sizeof(magic) - 1U);
	assert(swapz_primary_linux_swap_header_valid(header, logical_pages));
	/* Format parsing needs one header and one usable page. The target's
	 * separate capacity admission requires at least three physical segments. */
	test_put_u32_le(header, 1028U, 0U);
	assert(!swapz_primary_linux_swap_header_valid(header, 1U));
	test_put_u32_le(header, 1028U, 1U);
	assert(swapz_primary_linux_swap_header_valid(header, 2U));
	test_put_u32_le(header, 1028U, (uint32_t)(logical_pages - 1U));
	assert(!swapz_primary_linux_swap_header_valid(header, 0U));
	assert(!swapz_primary_linux_swap_header_valid(header,
							  (uint64_t)UINT32_MAX + 1U));
	test_put_u32_le(header, 1024U, 0U);
	assert(!swapz_primary_linux_swap_header_valid(header, logical_pages));
	test_put_u32_le(header, 1024U, 1U);
	test_put_u32_le(header, 1028U, (uint32_t)(logical_pages - 2U));
	assert(!swapz_primary_linux_swap_header_valid(header, logical_pages));
	test_put_u32_le(header, 1028U, (uint32_t)(logical_pages - 1U));
	test_put_u32_le(header, 1032U, 1U);
	assert(!swapz_primary_linux_swap_header_valid(header, logical_pages));
	test_put_u32_le(header, 1032U, 0U);
	/* Ordinary swap can deliberately have no UUID; PARTUUID is the selector. */
	memset(header + 1036U, 0, SWAPZ_PRIMARY_SWAP_UUID_BYTES);
	assert(swapz_primary_linux_swap_header_valid(header, logical_pages));
	header[1036U] = 1U;
	header[sizeof(header) - 1U] ^= 1U;
	assert(!swapz_primary_linux_swap_header_valid(header, logical_pages));
}

static void test_primary_run_id_generation(void)
{
	const char *all_zero = "00000000000000000000000000000000";
	const char *uppercase = "0123456789ABCDEF0123456789ABCDEF";
	char unterminated[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];
	char generated[SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U];

	assert(!swapz_primary_valid_run_id(all_zero));
	assert(swapz_primary_valid_run_id("00000000000000000000000000000001"));
	assert(swapz_primary_valid_run_id("10000000000000000000000000000000"));
	assert(!swapz_primary_valid_run_id(uppercase));
	assert(!swapz_primary_valid_run_id("short"));
	memset(unterminated, 'a', sizeof(unterminated));
	assert(!swapz_primary_valid_run_id(unterminated));

	memset(generated, 0xa5, sizeof(generated));
	assert(swapz_primary_run_id_generate(generated) == 0);
	assert(swapz_primary_valid_run_id(generated));
	errno = 0;
	assert(swapz_primary_run_id_generate(NULL) < 0);
	assert(errno == EINVAL);
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
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	length = swapz_primary_manifest_format(&manifest, record,
					      sizeof(record));
	assert(length > 0);
	assert(swapz_primary_manifest_parse(record, (size_t)length, &parsed) == 0);
	assert(!memcmp(&manifest, &parsed, sizeof(manifest)));

	/* Manifest v4 binds volatile raw-swap activation policy. Negative values
	 * are automatic Linux priority policy; nonnegative values are explicit. */
	manifest.original_swap_active = 1;
	manifest.original_swap_priority = -7;
	assert(swapz_primary_manifest_format(
		&manifest, damaged, sizeof(damaged)) > 0);
	assert(swapz_primary_manifest_parse(
		damaged, strlen(damaged), &parsed) == 0);
	assert(parsed.original_swap_active == 1);
	assert(parsed.original_swap_priority == -7);
	manifest.original_swap_priority = 12;
	assert(swapz_primary_manifest_format(
		&manifest, damaged, sizeof(damaged)) > 0);
	assert(swapz_primary_manifest_parse(
		damaged, strlen(damaged), &parsed) == 0);
	assert(parsed.original_swap_priority == 12);
	manifest.original_swap_priority = 32768;
	assert(swapz_primary_manifest_format(
		&manifest, damaged, sizeof(damaged)) < 0);
	manifest.original_swap_active = 0;
	manifest.original_swap_priority = -1;
	assert(swapz_primary_manifest_format(
		&manifest, damaged, sizeof(damaged)) < 0);
	manifest.original_swap_priority = 0;

	/* Editing lifecycle policy without regenerating a canonical record is
	 * rejected independently of device-geometry tamper coverage below. */
	memcpy(damaged, record, (size_t)length + 1U);
	field = strstr(damaged, "original_swap_priority=0\n");
	assert(field);
	field += strlen("original_swap_priority=");
	*field = '1';
	memset(&parsed, 0xa5, sizeof(parsed));
	assert(swapz_primary_manifest_parse(
		damaged, (size_t)length, &parsed) < 0);
	assert(((const unsigned char *)&parsed)[0] == 0xa5U);

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
	memcpy(damaged, record, (size_t)length);
	field = strstr(damaged, "backing_physical_blocks=");
	assert(field);
	field += strlen("backing_physical_blocks=");
	assert(*field >= '1' && *field <= '9');
	*field = *field == '9' ? '8' : '9';
	memset(&parsed, 0xa5, sizeof(parsed));
	assert(swapz_primary_manifest_parse(damaged, (size_t)length,
					    &parsed) < 0);
	assert(((const unsigned char *)&parsed)[0] == 0xa5U);
	assert(swapz_primary_manifest_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	memset(&observed, 0, sizeof(observed));
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      TEST_PARTUUID, geteuid(),
					      &observed) == 0);
	assert(!memcmp(&manifest, &observed, sizeof(manifest)));
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      "1234abcd-01", geteuid(),
					      &observed) < 0);
	assert(errno == EPERM);
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
					      TEST_PARTUUID, geteuid(),
					      &observed) < 0);
	assert(((const unsigned char *)&observed)[0] == 0xa5U);
	assert(pwrite(fd, "8", 1, (off_t)(field - record +
					    strlen("device_major="))) == 1);
	assert(fsync(fd) == 0);
	assert(close(fd) == 0);
	assert(swapz_primary_manifest_read_at(recovery_fd, lock_fd, run_id,
					      TEST_PARTUUID, geteuid(),
					      &observed) == 0);
	assert(!memcmp(&manifest, &observed, sizeof(manifest)));
	assert(unlinkat(recovery_fd, file_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
}

static void test_primary_transaction_manifest_integrity(
	int recovery_fd, int lock_fd, const char *run_id)
{
	static const enum swapz_primary_stage ready_stage[] = {
		SWAPZ_PRIMARY_STAGE_READY,
	};
	static const enum swapz_primary_stage starting_stage[] = {
		SWAPZ_PRIMARY_STAGE_STARTING,
	};
	struct swapz_primary_manifest manifest = {0};
	char manifest_name[96];

	memcpy(manifest.run_id, run_id, sizeof(manifest.run_id));
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
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);

	assert(swapz_primary_manifest_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	assert(swapz_primary_transaction_manifest_matches_at(
		recovery_fd, lock_fd, &manifest, ready_stage,
		sizeof(ready_stage) / sizeof(ready_stage[0]), geteuid()) == 0);
	assert(swapz_primary_transaction_manifest_matches_at(
		recovery_fd, lock_fd, &manifest, starting_stage,
		sizeof(starting_stage) / sizeof(starting_stage[0]), geteuid()) < 0);
	assert(errno == EPERM);

	assert(snprintf(manifest_name, sizeof(manifest_name),
			"primary-manifest-%s.txt", run_id) > 0);
	assert(unlinkat(recovery_fd, manifest_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
	assert(swapz_primary_transaction_manifest_matches_at(
		recovery_fd, lock_fd, &manifest, ready_stage,
		sizeof(ready_stage) / sizeof(ready_stage[0]), geteuid()) < 0);
	assert(errno == ENOENT || errno == EPERM);
}


static void test_primary_module_load_record(
	int recovery_fd, int lock_fd, const char *run_id)
{
	struct swapz_primary_manifest manifest = {0};
	char load_name[96];
	char ignored_record[512];
	char manifest_name[96];

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
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);

	assert(swapz_primary_manifest_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	assert(swapz_primary_module_load_intent_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	assert(swapz_primary_module_load_record_matches_at(
		recovery_fd, &manifest, "INTENT", geteuid()) == 0);
	errno = 0;
	assert(swapz_primary_module_load_intent_write_at(
		recovery_fd, lock_fd, &manifest, geteuid()) < 0);
	assert(errno == EEXIST);
	assert(swapz_primary_module_load_mark_loaded_at(
		recovery_fd, lock_fd, &manifest, geteuid()) == 0);
	assert(swapz_primary_module_load_record_matches_at(
		recovery_fd, &manifest, "LOADED", geteuid()) == 0);
	errno = 0;
	assert(swapz_primary_module_load_record_matches_at(
		recovery_fd, &manifest, "INTENT", geteuid()) < 0);
	assert(errno == EBADMSG);

	assert(swapz_primary_module_load_record_format(
		&manifest, "LOADED", load_name, ignored_record) == 0);
	assert(snprintf(manifest_name, sizeof(manifest_name),
			"primary-manifest-%s.txt", run_id) > 0);
	assert(unlinkat(recovery_fd, load_name, 0) == 0);
	assert(unlinkat(recovery_fd, manifest_name, 0) == 0);
	assert(fsync(recovery_fd) == 0);
}


static void test_primary_dm_table(void)
{
	const char *run_id = "0123456789abcdef0123456789abcdef";
	struct swapz_primary_manifest manifest = {0};
	_Alignas(struct dm_ioctl)
	unsigned char buffer[SWAPZ_PRIMARY_DM_BUFFER_BYTES];
	struct dm_ioctl *io = (struct dm_ioctl *)buffer;
	struct dm_target_spec *target;
	size_t used_bytes = 0;
	uint64_t logical_pages;
	uint64_t expected_logical_sectors;
	uint64_t logical_sectors = 0;
	char mapper_name[64];
	char mapper_uuid[64];
	char table[128];
	char expected_table[128];
	size_t status_record_bytes;
	size_t status_next;
	size_t status_bytes;
	int table_length;

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
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	assert(swapz_primary_mapper_layout(&manifest, mapper_name, mapper_uuid,
					 table, &logical_sectors) == 0);
	assert(!strcmp(mapper_name, "swapz-primary"));
	assert(!strcmp(mapper_uuid,
		       "SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef"));
	logical_pages = swapz_primary_maximum_logical_pages(
		manifest.backing_physical_blocks);
	assert(logical_pages > 0U);
	assert(logical_pages <=
	       UINT64_MAX / SWAPZ_PRIMARY_SECTORS_PER_PAGE);
	expected_logical_sectors =
		logical_pages * SWAPZ_PRIMARY_SECTORS_PER_PAGE;
	assert(logical_sectors == expected_logical_sectors);
	table_length = snprintf(
		expected_table, sizeof(expected_table),
		"0 %llu swapz %u:%u 0 64 0 2 0 1 0 0",
		(unsigned long long)expected_logical_sectors,
		manifest.target.device_major, manifest.target.device_minor);
	assert(table_length > 0 &&
	       (size_t)table_length < sizeof(expected_table));
	assert(!strcmp(table, expected_table));
	assert(swapz_primary_dm_table_load_buffer(
		&manifest, buffer, sizeof(buffer), &used_bytes) == 0);
	assert(used_bytes <= sizeof(buffer));
	assert(io->version[0] == DM_VERSION_MAJOR &&
	       io->version[1] == DM_VERSION_MINOR);
	assert(io->data_size == used_bytes && io->data_start == sizeof(*io));
	assert(io->target_count == 1U);
	assert(!io->name[0] && !strcmp(io->uuid, mapper_uuid));
	memcpy(io->name, mapper_name, strlen(mapper_name) + 1U);
	target = (struct dm_target_spec *)(buffer + io->data_start);
	assert(target->sector_start == 0ULL &&
	       target->length == logical_sectors && target->next == 0U);
	assert(!strcmp(target->target_type, "swapz"));
	assert(!strcmp((char *)(target + 1), "8:4 0 64 0 2 0 1 0 0"));
	status_record_bytes = sizeof(*target) +
		strlen((char *)(target + 1)) + 1U;
	status_next = swapz_primary_dm_align8(status_record_bytes);
	status_bytes = io->data_start + status_record_bytes;
	assert(status_next > status_record_bytes &&
	       status_next <= UINT32_MAX && status_bytes < used_bytes);
	/* DM_TABLE_STATUS uses the aligned next-record stride, unlike DM_TABLE_LOAD. */
	target->next = (uint32_t)status_next;
	io->data_size = (uint32_t)status_bytes;
	assert(swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	/* Some kernels include the zero alignment byte in data_size. */
	io->data_size = (uint32_t)used_bytes;
	assert(swapz_primary_dm_table_status_matches(
		buffer, used_bytes, &manifest));
	io->data_size = (uint32_t)status_bytes;
	--target->length;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	++target->length;
	((char *)(target + 1))[0] = '9';
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	((char *)(target + 1))[0] = '8';
	io->target_count = 2U;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	io->target_count = 1U;
	io->data_size = (uint32_t)(used_bytes + 1U);
	assert(!swapz_primary_dm_table_status_matches(
		buffer, used_bytes + 1U, &manifest));
	io->data_size = (uint32_t)status_bytes;
	io->version[0] = DM_VERSION_MAJOR + 1U;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	io->version[0] = DM_VERSION_MAJOR;
	io->data_start++;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	io->data_start = sizeof(*io);
	target->next = 0U;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	target->next = 8U;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	target->next = (uint32_t)(status_next + 8U);
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	target->next = (uint32_t)status_next;
	io->uuid[0] = 'X';
	assert(!swapz_primary_dm_table_status_matches(
		buffer, status_bytes, &manifest));
	io->uuid[0] = 'S';
	io->data_size = (uint32_t)used_bytes;
	buffer[used_bytes - 1U] = 1U;
	assert(!swapz_primary_dm_table_status_matches(
		buffer, used_bytes, &manifest));
	buffer[used_bytes - 1U] = 0U;
	io->data_size = (uint32_t)status_bytes;
	assert(swapz_primary_dm_table_load_buffer(
		&manifest, buffer + 1U, sizeof(buffer) - 1U, &used_bytes) < 0);
	assert(errno == EINVAL);
	assert(!swapz_primary_dm_table_status_matches(
		buffer + 1U, sizeof(buffer) - 1U, &manifest));
}

static void test_primary_dm_existing_mapper_selector(void)
{
	struct dm_ioctl io;
	const char *expected_name = "swapz-primary";
	const char *expected_uuid =
		"SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef";

	assert(swapz_primary_dm_existing_mapper_ioctl_initialize(
		&io, sizeof(io), expected_name, expected_uuid) == 0);
	assert(io.name[0] == '\0');
	assert(!strcmp(io.uuid, expected_uuid));
	errno = 0;
	assert(swapz_primary_dm_existing_mapper_ioctl_initialize(
		&io, sizeof(io), "", expected_uuid) < 0);
	assert(errno == EINVAL);
	errno = 0;
	assert(swapz_primary_dm_existing_mapper_ioctl_initialize(
		&io, sizeof(io), expected_name, "") < 0);
	assert(errno == EINVAL);
}

static void test_primary_dm_operations_disabled(void)
{
	struct swapz_primary_manifest manifest = {0};
	dev_t mapper_device = (dev_t)-1;
	int created = 1;
	int resumed = 1;
	int removed = 1;
	int unloaded = 1;
	int activated = 1;
	int deactivated = 1;

	assert(swapz_primary_dm_create_mapper(
		-1, -1, &manifest, 1, &created, &resumed,
		&mapper_device) < 0);
	assert(errno == ENODEV);
	assert(created == 0 && resumed == 0 && mapper_device == 0);
	assert(swapz_primary_dm_remove_mapper(-1, -1, &manifest,
					     &removed) < 0);
	assert(errno == ENODEV);
	assert(removed == 0);
	assert(swapz_primary_unload_owned_module(
		-1, -1, &manifest, 0, &unloaded) < 0);
	assert(errno == ENODEV);
	assert(unloaded == 0);
	assert(swapz_primary_format_mapper_swap(
		-1, -1, &manifest, (dev_t)-1) < 0);
	assert(errno == ENODEV);
	assert(swapz_primary_activate_mapper_swap(
		-1, -1, &manifest, (dev_t)-1, &activated) < 0);
	assert(errno == ENODEV);
	assert(activated == 0);
	assert(swapz_primary_deactivate_mapper_swap(
		-1, -1, &manifest, &deactivated) < 0);
	assert(errno == ENODEV);
	assert(deactivated == 0);
}

static void test_mapper_node_retry_policy(void)
{
	const uint64_t maximum_wait_ns =
		(uint64_t)SWAPZ_PRIMARY_MAPPER_NODE_RETRY_ATTEMPTS *
		(uint64_t)SWAPZ_PRIMARY_MAPPER_NODE_RETRY_NS;

	assert(SWAPZ_PRIMARY_MAPPER_NODE_RETRY_ATTEMPTS > 1U);
	assert(SWAPZ_PRIMARY_MAPPER_NODE_RETRY_NS > 0L);
	assert(maximum_wait_ns <= 5000000000ULL);
	assert(swapz_primary_mapper_node_retryable_errno(ENOENT));
	assert(!swapz_primary_mapper_node_retryable_errno(ENODEV));
	assert(!swapz_primary_mapper_node_retryable_errno(EACCES));
	assert(!swapz_primary_mapper_node_retryable_errno(ESTALE));
	assert(!swapz_primary_mapper_node_retryable_errno(EIO));
}

static void test_recoverable_lifecycle_stages(void)
{
	const char *run_id = "0123456789abcdef0123456789abcdef";
	struct swapz_primary_state state = {0};

	memcpy(state.run_id, run_id, SWAPZ_PRIMARY_RUN_ID_LENGTH + 1U);
	state.stage = SWAPZ_PRIMARY_STAGE_READY;
	assert(!swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_STOPPING;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_DISABLING;
	assert(!swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	assert(!swapz_primary_state_recoverable(&state));

	state.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	state.has_recovery_previous_stage = 1;
	state.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_STARTING;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_RECOVERING;
	assert(swapz_primary_state_recoverable(&state));
	state.stage = SWAPZ_PRIMARY_STAGE_RESTORED;
	assert(swapz_primary_state_recoverable(&state));
}

static void test_backing_header_digest_recognition(void)
{
	static const unsigned char swap_magic[] = "SWAPSPACE2";
	struct swapz_primary_manifest manifest = {0};
	unsigned char header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	unsigned char changed[SWAPZ_PRIMARY_BLOCK_BYTES];
	const uint64_t logical_pages =
		TEST_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES;

	test_put_u32_le(header, SWAPZ_PRIMARY_SWAP_VERSION_OFFSET, 1U);
	test_put_u32_le(header, SWAPZ_PRIMARY_SWAP_LAST_PAGE_OFFSET,
			(uint32_t)(logical_pages - 1U));
	test_put_u32_le(header, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 0U);
	memcpy(header + sizeof(header) - sizeof(swap_magic) + 1U,
	       swap_magic, sizeof(swap_magic) - 1U);

	memcpy(manifest.run_id, "0123456789abcdef0123456789abcdef",
	       sizeof(manifest.run_id));
	memset(manifest.source_sha, 'a', SWAPZ_PRIMARY_SOURCE_SHA_LENGTH);
	manifest.source_sha[SWAPZ_PRIMARY_SOURCE_SHA_LENGTH] = '\0';
	memset(manifest.swapzctl_sha256, 'b', SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.swapzctl_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	memset(manifest.module_sha256, 'c', SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.module_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	memset(manifest.qualification_report_sha256, 'd',
	       SWAPZ_PRIMARY_SHA256_LENGTH);
	manifest.qualification_report_sha256[SWAPZ_PRIMARY_SHA256_LENGTH] = '\0';
	manifest.target = swapz_primary_selected_target;
	manifest.backing_physical_blocks = (uint32_t)
		swapz_primary_physical_blocks(manifest.target.device_bytes);
	assert(swapz_primary_sha256(
		header, sizeof(header), manifest.original_header_sha256) == 0);

	assert(swapz_primary_backing_header_matches_manifest(
		header, &manifest) == 0);
	memcpy(changed, header, sizeof(changed));
	changed[128] ^= 0x01U;
	assert(swapz_primary_backing_header_matches_manifest(
		changed, &manifest) < 0);
	assert(errno == ESTALE);
	memcpy(changed, header, sizeof(changed));
	changed[sizeof(changed) - 1U] ^= 0x01U;
	assert(swapz_primary_backing_header_matches_manifest(
		changed, &manifest) < 0);
	assert(errno == EPERM);
}


static void test_exclusive_target_open_paths(void)
{
	char directory[] = "/tmp/swapz-primary-open-XXXXXX";
	char target[PATH_MAX];
	char other[PATH_MAX];
	char uuid_path[PATH_MAX];
	char partuuid_path[PATH_MAX];
	char substituted[PATH_MAX];
	char broken[PATH_MAX];
	unsigned char linux_swap_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
	static const unsigned char swap_magic[] = "SWAPSPACE2";
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
	assert(snprintf(broken, sizeof(broken), "%s/missing", directory) > 0);
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
	/* Production identity claims never open the raw partition writable. */
	errno = 0;
	assert(swapz_primary_open_target_checked_paths_mode(
		target, uuid_path, partuuid_path, O_RDWR | O_EXCL) < 0);
	assert(errno == EINVAL);
	fd = swapz_primary_open_target_checked_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY | O_EXCL);
	assert(fd >= 0);
	assert(fstat(fd, &info) == 0 && S_ISREG(info.st_mode));
	assert((fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDONLY);
	assert(close(fd) == 0);
	fd = swapz_primary_open_target_checked_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY);
	assert(fd >= 0);
	assert(fstat(fd, &info) == 0 && S_ISREG(info.st_mode));
	assert((fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDONLY);
	assert(close(fd) == 0);
	fd = swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY);
	assert(fd >= 0);
	assert(close(fd) == 0);
	fd = swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY | O_EXCL);
	assert(fd >= 0);
	assert((fcntl(fd, F_GETFL) & O_ACCMODE) == O_RDONLY);
	assert(close(fd) == 0);
	assert(unlink(uuid_path) == 0);
	test_put_u32_le(linux_swap_header, SWAPZ_PRIMARY_SWAP_VERSION_OFFSET, 1U);
	test_put_u32_le(
		linux_swap_header, SWAPZ_PRIMARY_SWAP_LAST_PAGE_OFFSET,
		(uint32_t)(TEST_DEVICE_BYTES / SWAPZ_PRIMARY_BLOCK_BYTES - 1U));
	test_put_u32_le(linux_swap_header, SWAPZ_PRIMARY_SWAP_BAD_PAGES_OFFSET, 0U);
	memcpy(linux_swap_header + sizeof(linux_swap_header) -
	       sizeof(swap_magic) + 1U, swap_magic, sizeof(swap_magic) - 1U);
	fd = open(target, O_WRONLY | O_CLOEXEC);
	assert(fd >= 0);
	assert(pwrite(fd, linux_swap_header, sizeof(linux_swap_header), 0) ==
	       (ssize_t)sizeof(linux_swap_header));
	assert(close(fd) == 0);
	fd = swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY);
	assert(fd >= 0);
	assert(close(fd) == 0);
	assert(symlink(broken, uuid_path) == 0);
	assert(swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY) < 0);
	assert(errno == ENOENT);
	assert(unlink(uuid_path) == 0);
	assert(symlink(other, uuid_path) == 0);
	assert(swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY) < 0);
	assert(errno == ESTALE);
	assert(unlink(uuid_path) == 0);
	fd = swapz_primary_open_target_checked_partuuid_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY);
	assert(fd >= 0);
	assert(close(fd) == 0);
	assert(swapz_primary_target_open_readonly() < 0);
	assert(errno == ENOTSUP);
	assert(symlink(target, uuid_path) == 0);
	assert(unlink(partuuid_path) == 0);
	assert(symlink(other, substituted) == 0);
	assert(symlink(substituted, partuuid_path) == 0);
	assert(swapz_primary_open_target_checked_paths_mode(
		target, uuid_path, partuuid_path, O_RDONLY | O_EXCL) < 0);
	assert(errno == ENODEV);
	assert(swapz_primary_open_target_checked_paths_mode(
		target, uuid_path, NULL, O_RDONLY | O_EXCL) < 0);
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

static void test_runtime_state_filesystem_policy(void)
{
	assert(!swapz_primary_runtime_state_fs_magic(EXT2_SUPER_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(XFS_SUPER_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(F2FS_SUPER_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(BTRFS_SUPER_MAGIC));
	assert(swapz_primary_runtime_state_fs_magic(TMPFS_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(RAMFS_MAGIC));
	assert(!swapz_primary_runtime_state_fs_magic(OVERLAYFS_SUPER_MAGIC));
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
		makedev(8U, 4U), makedev(8U, 0U), &facts) == 0);
	assert(facts.root_mount_seen);
	assert(facts.root_device == makedev(8U, 3U));
	assert(!facts.target_mounted);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3 rw\n"
		"37 36 8:4 / /mnt/swap rw - swap /dev/sda4 rw\n",
		makedev(8U, 4U), makedev(8U, 0U), &facts) == 0);
	assert(facts.target_mounted);
	assert(swapz_primary_parse_mountinfo(
		"36 25 259:0 / / rw - ext4 /dev/root rw\n"
		"37 36 8:0 / /mnt/parent rw - ext4 /dev/sda rw\n",
		makedev(8U, 1U), makedev(8U, 0U), &facts) == 0);
	assert(facts.target_mounted);
	/* Every kernel mountinfo record terminates in a newline. A complete-looking
	 * final row without one is still a truncated, ambiguous inventory. */
	assert(swapz_primary_parse_mountinfo(
		"36 25 259:0 / / rw - ext4 /dev/root rw\n"
		"37 36 8:4 / /mnt/swap rw - swap /dev/sda4 rw",
		makedev(8U, 4U), makedev(8U, 0U), &facts) < 0);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:x / / rw - f2fs /dev/sda3 rw\n",
		makedev(8U, 4U), makedev(8U, 0U), &facts) < 0);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3 rw\n"
		"37 36 8:3 / / rw - f2fs /dev/sda3 rw\n",
		makedev(8U, 4U), makedev(8U, 0U), &facts) < 0);
	assert(swapz_primary_parse_mountinfo(
		"36 25 8:3 / / rw - f2fs /dev/sda3\n",
		makedev(8U, 4U), makedev(8U, 0U), &facts) < 0);
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

static void test_primary_module_parameter_parser(void)
{
	int enabled = -1;

	assert(swapz_primary_parse_module_bool("Y", &enabled) == 0 && enabled);
	assert(swapz_primary_parse_module_bool("1", &enabled) == 0 && enabled);
	assert(swapz_primary_parse_module_bool("N", &enabled) == 0 && !enabled);
	assert(swapz_primary_parse_module_bool("0", &enabled) == 0 && !enabled);
	enabled = -1;
	assert(swapz_primary_parse_module_bool("yes", &enabled) < 0);
	assert(errno == EINVAL && enabled == -1);
	assert(swapz_primary_parse_module_bool("Y\n", &enabled) < 0);
	assert(swapz_primary_parse_module_bool(NULL, &enabled) < 0);
	assert(swapz_primary_parse_module_bool("Y", NULL) < 0);
}

static void test_qualified_module_fd(void)
{
	static const unsigned char module_bytes[] = "exact module image bytes\n";
	const char *home = getenv("HOME");
	char root_template[PATH_MAX];
	char libexec_path[PATH_MAX];
	char swapz_path[PATH_MAX];
	char prefix_path[PATH_MAX];
	char module_path[PATH_MAX];
	char control_path[PATH_MAX];
	char renamed_path[PATH_MAX];
	char renamed_directory[PATH_MAX];
	char hardlink_path[PATH_MAX];
	char wrong_path[PATH_MAX];
	char digest[65];
	char wrong_digest[65];
	struct stat info;
	int module_fd;

	assert(home && home[0] == '/');
	assert(snprintf(root_template, sizeof(root_template),
			 "%s/.swapz-primary-module-XXXXXX", home) > 0);
	assert(mkdtemp(root_template));
	assert(chmod(root_template, 0700) == 0);
	test_path_join(libexec_path, sizeof(libexec_path), root_template,
		       "libexec");
	assert(mkdir(libexec_path, 0700) == 0);
	test_path_join(prefix_path, sizeof(prefix_path), root_template, "prefix");
	assert(mkdir(prefix_path, 0700) == 0);
	test_path_join(swapz_path, sizeof(swapz_path), libexec_path, "swapz");
	assert(mkdir(swapz_path, 0700) == 0);
	test_path_join(module_path, sizeof(module_path), swapz_path,
		       "dm-swapz.ko");
	test_path_join(control_path, sizeof(control_path), root_template,
		       "sbin/swapzctl");
	test_path_join(renamed_path, sizeof(renamed_path), swapz_path,
	       "dm-swapz.saved");
	test_path_join(renamed_directory, sizeof(renamed_directory), libexec_path,
	       "swapz.saved");
	test_path_join(hardlink_path, sizeof(hardlink_path), swapz_path,
	       "dm-swapz.copy");
	test_path_join(wrong_path, sizeof(wrong_path), root_template,
	       "prefix/../sbin/swapzctl");
	test_write_text(module_path, (const char *)module_bytes);
	assert(chmod(module_path, 0644) == 0);
	assert(swapz_primary_sha256(module_bytes, sizeof(module_bytes) - 1U,
				    digest) == 0);
	memset(wrong_digest, '0', sizeof(wrong_digest) - 1U);
	wrong_digest[sizeof(wrong_digest) - 1U] = '\0';
	module_fd = swapz_primary_open_qualified_module_fd(
		control_path, digest);
	assert(module_fd >= 0);
	assert(fstat(module_fd, &info) == 0 && S_ISREG(info.st_mode));
	assert(info.st_uid == geteuid() && info.st_nlink == 1U);
	assert((fcntl(module_fd, F_GETFL) & O_ACCMODE) == O_RDONLY);
	assert(close(module_fd) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		control_path, wrong_digest) < 0);
	assert(errno == EBADMSG);
	assert(chmod(module_path, 0664) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		control_path, digest) < 0);
	assert(errno == EPERM);
	assert(chmod(module_path, 0644) == 0);
	assert(link(module_path, hardlink_path) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		control_path, digest) < 0);
	assert(errno == EPERM);
	assert(unlink(hardlink_path) == 0);
	assert(rename(module_path, renamed_path) == 0);
	assert(symlink(renamed_path, module_path) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		control_path, digest) < 0);
	assert(unlink(module_path) == 0);
	assert(rename(renamed_path, module_path) == 0);
	assert(rename(swapz_path, renamed_directory) == 0);
	assert(symlink(renamed_directory, swapz_path) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		control_path, digest) < 0);
	assert(unlink(swapz_path) == 0);
	assert(rename(renamed_directory, swapz_path) == 0);
	assert(swapz_primary_open_qualified_module_fd(
		wrong_path, digest) < 0);
	assert(nftw(root_template, test_remove_tree_entry, 16,
		    FTW_DEPTH | FTW_PHYS) == 0);
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

/* The production parser must refuse before publishing any parsed evidence. */
static void assert_primary_qualification_report_refused(
	const char *json, size_t json_length, const char *expected_source_sha,
	const char *expected_host_sha256)
{
	struct swapz_primary_qualification qualification;
	struct swapz_primary_qualification original;

	memset(&qualification, 0xa5, sizeof(qualification));
	original = qualification;
	errno = 0;
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, json_length, expected_source_sha,
		expected_host_sha256, &qualification) < 0);
	assert(errno == EINVAL);
	assert(!memcmp(&qualification, &original, sizeof(qualification)));
}

static void assert_primary_qualification_trailing_comma_refused(
	const char *json, size_t json_length, const char *closing_marker,
	size_t closing_offset, const char *expected_source_sha,
	const char *expected_host_sha256)
{
	char malformed[4096];
	char *closing;

	assert(json_length + 2U <= sizeof(malformed));
	memcpy(malformed, json, json_length + 1U);
	closing = strstr(malformed, closing_marker);
	assert(closing);
	closing += closing_offset;
	assert(*closing == '}' || *closing == ']');
	memmove(closing + 1, closing, strlen(closing) + 1U);
	*closing = ',';
	assert_primary_qualification_report_refused(
		malformed, json_length + 1U, expected_source_sha,
		expected_host_sha256);
}

static void test_primary_qualification_report_parser(void)
{
	static const char report_template[] =
		"{\"schema\":\"swapz-test-results-v1\","
		"\"host_identity\":{\"schema\":\"swapz-host-v1\","
		"\"architecture\":\"x86_64\",\"id_sha256\":\"%s\"},"
		"\"synthetic_metadata\":{\"note\":\"ignored\","
		"\"values\":[0,true,false,null]},"
		"\"source_sha\":\"%s\",\"tested_commit_sha\":\"%s\","
		"\"kernel_release\":\"6.8.0-48-generic\","
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
	static const unsigned char hardware_bound_host_identity[] =
		"swapz-host-v2\0"
		"00112233-4455-6677-8899-aabbccddeeff"
		"0123456789abcdef0123456789abcdef";
	static const unsigned char legacy_host_identity[] =
		"swapz-host\0"
		"0123456789abcdef0123456789abcdef";
	const char *source = "0123456789abcdef0123456789abcdef01234567";
	char host_sha[65];
	char legacy_host_sha[65];
	char formatter_sha[65];
	char module_sha[65];
	char oracle_sha[65];
	char json[4096];
	struct swapz_primary_qualification qualification;
	int length;

	/* The JSON envelope is v1; its digest binds today's v2 hardware input. */
	assert(swapz_primary_sha256(
		hardware_bound_host_identity,
		sizeof(hardware_bound_host_identity) - 1U, host_sha) == 0);
	assert(!strcmp(
		host_sha,
		"43ff3a146c6a1c8eb61716358170b7d765f7db44f86fc38e18dd449dd2e36d1f"));
	assert(swapz_primary_sha256(
		legacy_host_identity, sizeof(legacy_host_identity) - 1U,
		legacy_host_sha) == 0);
	assert(strcmp(host_sha, legacy_host_sha));
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
	assert(!strcmp(qualification.kernel_release, "6.8.0-48-generic"));
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
	/* The report contents, not only the caller's expected value, are bound. */
	{
		char *digest = strstr(json, "\"id_sha256\":\"");
		char original;

		assert(digest);
		digest += strlen("\"id_sha256\":\"");
		original = *digest;
		*digest = original == '0' ? '1' : '0';
		assert_primary_qualification_report_refused(
			json, (size_t)length, source, host_sha);
		*digest = original;
		memcpy(digest, legacy_host_sha, SWAPZ_PRIMARY_SHA256_LENGTH);
		assert_primary_qualification_report_refused(
			json, (size_t)length, source, host_sha);
		memcpy(digest, host_sha, SWAPZ_PRIMARY_SHA256_LENGTH);
	}
	{
		char *report_source = strstr(json, "\"source_sha\":\"");
		char original;

		assert(report_source);
		report_source += strlen("\"source_sha\":\"");
		original = *report_source;
		*report_source = original == '0' ? '1' : '0';
		assert_primary_qualification_report_refused(
			json, (size_t)length, source, host_sha);
		*report_source = original;
	}
	{
		char *tested_commit = strstr(json, "\"tested_commit_sha\":\"");
		char original;

		assert(tested_commit);
		tested_commit += strlen("\"tested_commit_sha\":\"");
		original = *tested_commit;
		*tested_commit = original == '0' ? '1' : '0';
		assert_primary_qualification_report_refused(
			json, (size_t)length, source, host_sha);
		*tested_commit = original;
	}
	{
		char *artifact_name = strstr(json, "\"oracle_sha256\":\"");

		assert(artifact_name);
		/* This valid unknown field cannot replace the required oracle. */
		memcpy(artifact_name + 1, "unused", 6U);
		assert_primary_qualification_report_refused(
			json, (size_t)length, source, host_sha);
		memcpy(artifact_name + 1, "oracle", 6U);
	}

	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, source, module_sha,
		&qualification) < 0);
	assert(swapz_primary_qualification_parse_json(
		(const unsigned char *)json, (size_t)length, "unknown", host_sha,
		&qualification) < 0);
	assert(swapz_primary_valid_kernel_release("6.8.0-48-generic"));
	assert(!swapz_primary_valid_kernel_release(""));
	assert(!swapz_primary_valid_kernel_release("6.8.0/unsafe"));
	{
		char *kernel_release = strstr(json, "\"kernel_release\":\"");
		char original;

		assert(kernel_release);
		kernel_release += strlen("\"kernel_release\":\"");
		original = *kernel_release;
		*kernel_release = '/';
		assert(swapz_primary_qualification_parse_json(
			(const unsigned char *)json, (size_t)length, source, host_sha,
			&qualification) < 0);
		*kernel_release = original;
	}
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
		static const char duplicate_field[] = "\"overall\":\"FAIL\",";
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
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length, "},\"synthetic_metadata\"", 0U,
		source, host_sha);
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length, "]},\"source_sha\"", 0U,
		source, host_sha);
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length, "]},\"source_sha\"", 1U,
		source, host_sha);
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length,
		"},{\"name\":\"Native and rootless contracts\"", 0U,
		source, host_sha);
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length, "],\"qualified_artifacts\"", 0U,
		source, host_sha);
	assert_primary_qualification_trailing_comma_refused(
		json, (size_t)length, "}}\n", 0U, source, host_sha);
	{
		char malformed[sizeof(json)];
		char *closing;

		assert((size_t)length + 2U <= sizeof(malformed));
		memcpy(malformed, json, (size_t)length + 1U);
		closing = strrchr(malformed, '}');
		assert(closing && closing[1] == '\n');
		memmove(closing + 1, closing, strlen(closing) + 1U);
		*closing = ',';
		assert_primary_qualification_report_refused(
			malformed, (size_t)length + 1U, source, host_sha);
	}
}

static void test_primary_qualification_report_store(void)
{
	static const unsigned char first[] = "first qualification report\n";
	static const unsigned char second[] = "replacement qualification report\n";
	const char *home = getenv("HOME");
	char directory_template[PATH_MAX];
	char first_digest[65];
	char second_digest[65];
	char archive_name[112];
	char fixed_name[] = "primary-qualification.json";
	char active_name[] = "partition-7fb9401d-04.active";
	char actual[128];
	struct stat info;
	int directory_fd = -1;
	int report_fd = -1;
	int lock_fd = -1;
	int file_fd = -1;
	ssize_t count;

	assert(home && home[0] == '/');
	assert(snprintf(directory_template, sizeof(directory_template),
			 "%s/.swapz-primary-report-XXXXXX", home) > 0);
	assert(mkdtemp(directory_template));
	assert(chmod(directory_template, 0700) == 0);
	directory_fd = open(directory_template,
			    O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
	assert(directory_fd >= 0);
	assert(mkdirat(directory_fd, "evidence", 0700) == 0);
	report_fd = openat(directory_fd, "evidence",
		O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
	assert(report_fd >= 0);
	lock_fd = swapz_primary_partition_lock_at(
		directory_fd, "7fb9401d-04", getuid());
	assert(lock_fd >= 0);
	assert(swapz_primary_sha256(first, sizeof(first) - 1U,
				    first_digest) == 0);
	assert(swapz_primary_sha256(second, sizeof(second) - 1U,
				    second_digest) == 0);
	assert(swapz_primary_qualification_report_store_at(
		directory_fd, lock_fd, report_fd, first, sizeof(first) - 1U,
		first_digest, getuid()) == 0);
	file_fd = openat(report_fd, fixed_name,
			 O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	assert(file_fd >= 0);
	assert(fstat(file_fd, &info) == 0 && info.st_size == sizeof(first) - 1U);
	count = pread(file_fd, actual, sizeof(actual), 0);
	assert(count == (ssize_t)(sizeof(first) - 1U));
	assert(!memcmp(actual, first, sizeof(first) - 1U));
	assert(close(file_fd) == 0);
	file_fd = -1;
	assert(snprintf(archive_name, sizeof(archive_name),
			 "primary-qualification-%s.json", first_digest) > 0);
	assert(swapz_primary_qualification_report_store_at(
		directory_fd, lock_fd, report_fd, second, sizeof(second) - 1U,
		second_digest, getuid()) == 0);
	file_fd = openat(report_fd, archive_name,
			 O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	assert(file_fd >= 0);
	count = pread(file_fd, actual, sizeof(actual), 0);
	assert(count == (ssize_t)(sizeof(first) - 1U));
	assert(!memcmp(actual, first, sizeof(first) - 1U));
	assert(close(file_fd) == 0);
	file_fd = openat(report_fd, fixed_name,
			 O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	assert(file_fd >= 0);
	count = pread(file_fd, actual, sizeof(actual), 0);
	assert(count == (ssize_t)(sizeof(second) - 1U));
	assert(!memcmp(actual, second, sizeof(second) - 1U));
	assert(close(file_fd) == 0);
	file_fd = -1;
	assert(swapz_primary_qualification_report_store_at(
		directory_fd, lock_fd, report_fd, second, sizeof(second) - 1U,
		second_digest, getuid()) == 0);
	file_fd = openat(directory_fd, active_name,
			 O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
	assert(file_fd >= 0);
	assert(close(file_fd) == 0);
	file_fd = -1;
	assert(swapz_primary_qualification_report_store_at(
		directory_fd, lock_fd, report_fd, first, sizeof(first) - 1U,
		first_digest, getuid()) < 0);
	assert(errno == EBUSY);
	assert(unlinkat(directory_fd, active_name, 0) == 0);
	assert(close(lock_fd) == 0);
	lock_fd = -1;
	assert(fstatat(directory_fd, fixed_name, &info, AT_SYMLINK_NOFOLLOW) < 0);
	assert(errno == ENOENT);
	assert(unlinkat(report_fd, fixed_name, 0) == 0);
	assert(unlinkat(report_fd, archive_name, 0) == 0);
	assert(close(report_fd) == 0);
	assert(unlinkat(directory_fd, "evidence", AT_REMOVEDIR) == 0);
	assert(unlinkat(directory_fd, "partition-7fb9401d-04.lock", 0) == 0);
	assert(close(directory_fd) == 0);
	directory_fd = -1;
	assert(rmdir(directory_template) == 0);
}

static void test_primary_qualification_live_reader_disabled_in_rootless(void)
{
	char *import_args[] = {
		"qualification-import", "/not-a-real-qualification-report"
	};
	int loaded_by_call = 1;
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
		swapzctl_sha256, module_sha256, oracle_sha256,
		SWAPZ_PRIMARY_ORIGINAL_HEADER_SHA256, NULL) < 0);
	assert(errno == ENODEV);
	errno = 0;
	assert(swapz_primary_load_qualified_module(&loaded_by_call) < 0);
	assert(errno == ENODEV && loaded_by_call == 0);
	assert(!memcmp(swapzctl_sha256, original_hashes[0],
		       sizeof(swapzctl_sha256)));
	assert(!memcmp(module_sha256, original_hashes[1],
		       sizeof(module_sha256)));
	assert(!memcmp(oracle_sha256, original_hashes[2],
		       sizeof(oracle_sha256)));
	errno = 0;
	assert(swapz_primary_command(2, import_args) == 2);
	assert(errno == ENODEV);
}

static void test_orphan_ready_claim_reconciliation(void)
{
	const char *home = getenv("HOME");
	const char *first_run_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
	const char *next_run_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
	char base_template[PATH_MAX];
	char lock_path[PATH_MAX];
	char active_name[64];
	char first_consumed_name[64];
	char next_consumed_name[64];
	char first_record[192];
	char next_record[192];
	char recovered_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char unchanged_state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	char next_state_record[SWAPZ_PRIMARY_STATE_RECORD_MAX + 1U];
	struct swapz_primary_state state = {0};
	struct swapz_primary_state stale_state = {0};
	static const enum swapz_primary_stage stale_stages[] = {
		SWAPZ_PRIMARY_STAGE_ACTIVE,
		SWAPZ_PRIMARY_STAGE_COMPLETE,
	};
	struct stat active_info;
	size_t recovered_length;
	size_t unchanged_state_length;
	size_t next_state_length;
	size_t stale_index;
	int formatted_length;
	int directory_fd;
	int lock_fd;

	assert(home && home[0] == '/');
	assert(snprintf(base_template, sizeof(base_template),
			 "%s/.swapz-primary-orphan-XXXXXX", home) > 0);
	assert(mkdtemp(base_template));
	assert(snprintf(lock_path, sizeof(lock_path),
			 "%s/partition-7fb9401d-04.lock", base_template) > 0);
	assert(snprintf(active_name, sizeof(active_name),
			 "partition-7fb9401d-04.active") > 0);
	assert(snprintf(first_consumed_name, sizeof(first_consumed_name),
			 "consumed-%s.json", first_run_id) > 0);
	assert(snprintf(next_consumed_name, sizeof(next_consumed_name),
			 "consumed-%s.json", next_run_id) > 0);
	assert(snprintf(first_record, sizeof(first_record),
			 "{\"major\":8,\"minor\":4,"
			 "\"partuuid\":\"7fb9401d-04\","
			 "\"run_id\":\"%s\"}\n", first_run_id) > 0);
	assert(snprintf(next_record, sizeof(next_record),
			 "{\"major\":8,\"minor\":4,"
			 "\"partuuid\":\"7fb9401d-04\","
			 "\"run_id\":\"%s\"}\n", next_run_id) > 0);
	directory_fd = swapz_primary_recovery_base_open(
		base_template, geteuid());
	assert(directory_fd >= 0);
	lock_fd = swapz_primary_partition_lock_at(
		directory_fd, "7fb9401d-04", geteuid());
	assert(lock_fd >= 0);
	assert(swapz_primary_claim_partition_owner_at(
		directory_fd, lock_fd, first_run_id, geteuid()) == 0);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(
		recovered_record, recovered_length, &state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_READY &&
	       !strcmp(state.run_id, first_run_id));
	unchanged_state_length = recovered_length;
	memcpy(unchanged_state_record, recovered_record,
	       recovered_length + 1U);
	assert(unlinkat(directory_fd, active_name, 0) == 0);
	assert(unlinkat(directory_fd, first_consumed_name, 0) == 0);
	assert(fsync(directory_fd) == 0);
	errno = 0;
	assert(swapz_primary_reconcile_metadata_claim_at(
		directory_fd, lock_fd, geteuid()) < 0);
	assert(errno == ENOENT);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(recovered_length == unchanged_state_length &&
	       !memcmp(recovered_record, unchanged_state_record,
		       unchanged_state_length));
	assert(swapz_primary_write_record_at(
		directory_fd, first_consumed_name, first_record, geteuid()) == 0);
	assert(swapz_primary_reconcile_metadata_claim_at(
		directory_fd, lock_fd, geteuid()) == 0);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(recovered_record, recovered_length,
					&state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_COMPLETE &&
	       !strcmp(state.run_id, first_run_id));
	assert_record_equals(directory_fd, first_consumed_name, first_record);
	state.stage = SWAPZ_PRIMARY_STAGE_STARTING;
	formatted_length = swapz_primary_state_format(
		&state, recovered_record, sizeof(recovered_record));
	assert(formatted_length > 0);
	assert(swapz_primary_replace_record_at(
		directory_fd, "primary-state.json", first_run_id,
		recovered_record, geteuid()) == 0);
	assert(swapz_primary_reconcile_metadata_claim_at(
		directory_fd, lock_fd, geteuid()) < 0);
	assert(errno == EBUSY);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(recovered_record, recovered_length,
					&state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_STARTING &&
	       !strcmp(state.run_id, first_run_id));
	state.stage = SWAPZ_PRIMARY_STAGE_COMPLETE;
	formatted_length = swapz_primary_state_format(
		&state, recovered_record, sizeof(recovered_record));
	assert(formatted_length > 0);
	assert(swapz_primary_replace_record_at(
		directory_fd, "primary-state.json", first_run_id,
		recovered_record, geteuid()) == 0);
	assert(swapz_primary_claim_partition_owner_at(
		directory_fd, lock_fd, next_run_id, geteuid()) == 0);
	assert_record_equals(directory_fd, active_name, next_record);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(recovered_record, recovered_length,
					&state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_READY &&
	       !strcmp(state.run_id, next_run_id));
	/* A stale activation/deactivation or recovery result from A must not
	 * overwrite B after B has claimed the same partition. */
	next_state_length = recovered_length;
	memcpy(next_state_record, recovered_record,
	       recovered_length + 1U);
	for (stale_index = 0;
	     stale_index < sizeof(stale_stages) / sizeof(stale_stages[0]);
	     ++stale_index) {
		stale_state = state;
		memcpy(stale_state.run_id, first_run_id,
		       sizeof(stale_state.run_id));
		stale_state.stage = stale_stages[stale_index];
		errno = 0;
		assert(swapz_primary_state_write_at(
			directory_fd, lock_fd, &stale_state, geteuid()) < 0);
		assert(errno == EPERM);
	}
	errno = 0;
	assert(swapz_primary_state_require_recovery_at(
		directory_fd, lock_fd, first_run_id, geteuid()) < 0);
	assert(errno == EPERM);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(recovered_length == next_state_length &&
	       !memcmp(recovered_record, next_state_record,
		       next_state_length));
	assert(swapz_primary_reconcile_metadata_claim_at(
		directory_fd, lock_fd, geteuid()) == 0);
	assert(fstatat(directory_fd, active_name, &active_info,
		       AT_SYMLINK_NOFOLLOW) < 0 && errno == ENOENT);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(recovered_record, recovered_length,
					&state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_COMPLETE &&
	       !strcmp(state.run_id, next_run_id));
	assert_record_equals(directory_fd, next_consumed_name, next_record);
	/* Also recover the crash window after COMPLETE but before marker release. */
	assert(swapz_primary_write_record_at(
		directory_fd, active_name, next_record, geteuid()) == 0);
	assert(swapz_primary_reconcile_metadata_claim_at(
		directory_fd, lock_fd, geteuid()) == 0);
	assert(fstatat(directory_fd, active_name, &active_info,
		       AT_SYMLINK_NOFOLLOW) < 0 && errno == ENOENT);
	assert(swapz_primary_record_read_at(
		directory_fd, "primary-state.json", geteuid(), recovered_record,
		sizeof(recovered_record), &recovered_length, NULL) == 0);
	assert(swapz_primary_state_parse(recovered_record, recovered_length,
					&state) == 0);
	assert(state.stage == SWAPZ_PRIMARY_STAGE_COMPLETE &&
	       !strcmp(state.run_id, next_run_id));
	assert(unlinkat(directory_fd, first_consumed_name, 0) == 0);
	assert(unlinkat(directory_fd, next_consumed_name, 0) == 0);
	assert(unlinkat(directory_fd, "primary-state.json", 0) == 0);
	assert(fsync(directory_fd) == 0);
	assert(close(lock_fd) == 0);
	assert(close(directory_fd) == 0);
	assert(unlink(lock_path) == 0);
	assert(rmdir(base_template) == 0);
}

static void write_package_test_artifact(const char *path, const char *bytes)
{
	size_t length = strlen(bytes);
	int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW |
			   O_CLOEXEC, 0600);

	assert(fd >= 0);
	assert(write(fd, bytes, length) == (ssize_t)length);
	assert(fsync(fd) == 0);
	assert(close(fd) == 0);
}


/* Exercise the same production gate helpers that preparation calls, using
 * synthetic records only: no /proc mutations, block opens, or swap syscalls. */
static void test_primary_preparation_refusal_helpers(void)
{
	struct swapz_primary_qualification qualification = {0};
	struct swapz_primary_qualification original_qualification;
	struct swapz_primary_swap_entry entries[2] = {0};
	struct swapz_primary_swap_entry original_entries[2];
	struct swapz_primary_mount_facts mount_facts = {0};
	struct swapz_primary_mount_facts original_mount_facts;
	dev_t resolved_devices[2] = {0};
	unsigned char resolved_is_block[2] = {0};
	char formatter_hash[65];
	char module_hash[65];
	char oracle_hash[65];
	char original_entries_inventory[] =
		"Filename Type Size Used Priority\n";
	size_t entry_count = 17U;
	dev_t target_device = makedev(8U, 4U);

	memset(qualification.formatter_sha256, 'a', 64U);
	memset(qualification.module_sha256, 'b', 64U);
	memset(qualification.oracle_sha256, 'c', 64U);
	original_qualification = qualification;
	memcpy(formatter_hash, qualification.formatter_sha256,
	       sizeof(formatter_hash));
	memcpy(module_hash, qualification.module_sha256, sizeof(module_hash));
	memcpy(oracle_hash, qualification.oracle_sha256, sizeof(oracle_hash));
	assert(swapz_primary_qualification_artifacts_match(
		&qualification, formatter_hash, module_hash, oracle_hash));
	formatter_hash[0] = 'd';
	assert(!swapz_primary_qualification_artifacts_match(
		&qualification, formatter_hash, module_hash, oracle_hash));
	formatter_hash[0] = 'a';
	module_hash[0] = 'd';
	assert(!swapz_primary_qualification_artifacts_match(
		&qualification, formatter_hash, module_hash, oracle_hash));
	module_hash[0] = 'b';
	oracle_hash[0] = 'd';
	assert(!swapz_primary_qualification_artifacts_match(
		&qualification, formatter_hash, module_hash, oracle_hash));
	assert(!memcmp(&qualification, &original_qualification,
		       sizeof(qualification)));

	/* A missing /proc/swaps header is never evidence of quiescence. */
	memset(entries, 0xa5, sizeof(entries));
	memcpy(original_entries, entries, sizeof(entries));
	assert(swapz_primary_parse_swaps("", entries, 2U, &entry_count) < 0);
	assert(entry_count == 17U);
	assert(!memcmp(entries, original_entries, sizeof(entries)));
	assert(swapz_primary_parse_swaps(original_entries_inventory, entries,
		2U, &entry_count) == 0 && entry_count == 0U);

	memset(entries, 0, sizeof(entries));
	strcpy(entries[0].path, "/fixture/unrelated-swapfile");
	strcpy(entries[0].type, "file");
	entries[0].size_kib = 1024U;
	strcpy(entries[1].path, "/fixture/active-swapfile");
	strcpy(entries[1].type, "file");
	entries[1].size_kib = 2048U;
	resolved_devices[0] = makedev(259U, 1U);
	resolved_devices[1] = target_device;
	memcpy(original_entries, entries, sizeof(entries));
	errno = 0;
	assert(swapz_primary_swap_inventory_target_is_admissible(
		entries, resolved_devices, resolved_is_block, 2U,
		target_device, TEST_SWAP_SIZE_KIB) < 0);
	assert(errno == EBUSY);
	assert(!memcmp(entries, original_entries, sizeof(entries)));
	assert(resolved_devices[0] == makedev(259U, 1U));
	assert(resolved_devices[1] == target_device);
	assert(resolved_is_block[0] == 0U && resolved_is_block[1] == 0U);

	/* Parent mounts are rejected regardless of target-partition aliases. */
	assert(swapz_primary_parse_mountinfo(
		"36 25 259:0 / / rw - ext4 /dev/root rw\n"
		"37 36 8:0 / /fixture/parent rw - ext4 /fixture/parent rw\n",
		target_device, makedev(8U, 0U), &mount_facts) == 0);
	assert(mount_facts.root_mount_seen);
	assert(mount_facts.target_mounted);
	original_mount_facts = mount_facts;
	assert(swapz_primary_parse_mountinfo(
		"broken kernel mount inventory\n",
		target_device, makedev(8U, 0U), &mount_facts) < 0);
	assert(!memcmp(&mount_facts, &original_mount_facts,
		       sizeof(mount_facts)));
}

static void test_package_transaction_process_death_guard(void)
{
	static const char journal_record[] =
		"{\"schema\":\"swapz-package-install-v1\",\"phase\":\"cli-published\","
		"\"version\":\"test\",\"kernel_release\":\"test\",\"backup_files\":[]}\n";
	const char *home = getenv("HOME");
	char fixture[PATH_MAX];
	char transactions[PATH_MAX];
	char transaction[PATH_MAX];
	char uninstall_transaction[PATH_MAX];
	char journal[PATH_MAX];
	char cli_artifact[PATH_MAX];
	char module_artifact[PATH_MAX];
	char lock_path[PATH_MAX];
	char unknown_entry[PATH_MAX];
	int directory_fd;
	int lock_fd;
	int status;
	pid_t packaging_pid;

	assert(home && home[0] == '/');
	assert(snprintf(fixture, sizeof(fixture),
			"%s/.swapz-package-crash-XXXXXX", home) > 0);
	assert(mkdtemp(fixture));
	assert(snprintf(transactions, sizeof(transactions),
			"%s/transactions", fixture) > 0);
	assert(snprintf(transaction, sizeof(transaction),
			"%s/swapz-package.12345678", transactions) > 0);
	assert(snprintf(uninstall_transaction, sizeof(uninstall_transaction),
			"%s/swapz-uninstall.87654321", transactions) > 0);
	assert(snprintf(journal, sizeof(journal),
			"%s/state.json", transaction) > 0);
	assert(snprintf(cli_artifact, sizeof(cli_artifact),
			"%s/published-swapzctl", fixture) > 0);
	assert(snprintf(module_artifact, sizeof(module_artifact),
			"%s/published-dm-swapz.ko", fixture) > 0);
	assert(snprintf(lock_path, sizeof(lock_path),
			"%s/%s", fixture, SWAPZ_PRIMARY_MUTATION_LOCK_NAME) > 0);
	assert(snprintf(unknown_entry, sizeof(unknown_entry),
			"%s/unknown-state", transactions) > 0);
	/* A genuinely untouched installation needs no transaction directory. */
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) == 0);
	assert(mkdir(transactions, 0700) == 0);
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) == 0);

	packaging_pid = fork();
	assert(packaging_pid >= 0);
	if (packaging_pid == 0) {
		/* Private stand-ins for module and CLI publication: no real swap. */
		lock_fd = swapz_primary_mutation_lock_at(fixture, geteuid());
		assert(lock_fd >= 0);
		write_package_test_artifact(module_artifact, "module-published\n");
		write_package_test_artifact(cli_artifact, "cli-published\n");
		assert(mkdir(transaction, 0700) == 0);
		write_package_test_artifact(journal, journal_record);
		directory_fd = open(transaction, O_RDONLY | O_DIRECTORY |
				    O_NOFOLLOW | O_CLOEXEC);
		assert(directory_fd >= 0 && fsync(directory_fd) == 0);
		assert(close(directory_fd) == 0);
		directory_fd = open(transactions, O_RDONLY | O_DIRECTORY |
				    O_NOFOLLOW | O_CLOEXEC);
		assert(directory_fd >= 0 && fsync(directory_fd) == 0);
		assert(close(directory_fd) == 0);
		/* Simulate SIGKILL semantics: no trap, unlock or journal cleanup. */
		_exit(86);
	}
	assert(waitpid(packaging_pid, &status, 0) == packaging_pid);
	assert(WIFEXITED(status) && WEXITSTATUS(status) == 86);

	/* The package flock is free again, but durable rollback remains. */
	lock_fd = swapz_primary_mutation_lock_at(fixture, geteuid());
	assert(lock_fd >= 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(close(lock_fd) == 0);
	/* A denied preparation must not consume or rewrite the transaction
	 * journal, nor damage unrelated published package artifacts. */
	directory_fd = open(transaction, O_RDONLY | O_DIRECTORY |
			    O_NOFOLLOW | O_CLOEXEC);
	assert(directory_fd >= 0);
	assert_record_equals(directory_fd, "state.json", journal_record);
	assert(close(directory_fd) == 0);
	directory_fd = open(fixture, O_RDONLY | O_DIRECTORY |
			    O_NOFOLLOW | O_CLOEXEC);
	assert(directory_fd >= 0);
	assert_record_equals(directory_fd, "published-dm-swapz.ko",
			     "module-published\n");
	assert_record_equals(directory_fd, "published-swapzctl",
			     "cli-published\n");
	assert(close(directory_fd) == 0);

	/* Journal validity is not permission to activate before completion. */
	assert(truncate(journal, 0) == 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(unlink(journal) == 0);
	write_package_test_artifact(journal, "{corrupt-json\\n");
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(unlink(journal) == 0);
	assert(symlink("../../published-swapzctl", journal) == 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(unlink(journal) == 0);
	assert(mkfifo(journal, 0600) == 0);
	/* No journal opens: a FIFO must not cause activation to hang. */
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(unlink(journal) == 0);
	/* Even a directory left before the prepared journal is unsafe. */
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(rmdir(transaction) == 0);
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) == 0);

	assert(mkdir(uninstall_transaction, 0700) == 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(rmdir(uninstall_transaction) == 0);
	write_package_test_artifact(unknown_entry, "ambiguous\n");
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EBUSY);
	assert(unlink(unknown_entry) == 0);
	assert(chmod(transactions, 0755) == 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0 && errno == EPERM);
	assert(chmod(transactions, 0700) == 0);
	errno = 0;
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, (uid_t)-1) < 0 && errno == EPERM);

	assert(rmdir(transactions) == 0);
	assert(symlink(fixture, transactions) == 0);
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0);
	assert(unlink(transactions) == 0);
	assert(mkfifo(transactions, 0600) == 0);
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) < 0);
	assert(unlink(transactions) == 0);
	/* Successful package recovery removes the durable directory. */
	assert(mkdir(transactions, 0700) == 0);
	assert(swapz_primary_package_transactions_clear_at(
		       transactions, geteuid()) == 0);
	assert(unlink(cli_artifact) == 0);
	assert(unlink(module_artifact) == 0);
	assert(unlink(lock_path) == 0);
	assert(rmdir(transactions) == 0);
	assert(rmdir(fixture) == 0);
}

int main(void)
{
	swapz_u32 reserve_blocks = 0;
	uint64_t pages;
	const char *home = getenv("HOME");
	char base_template[PATH_MAX];
	char mutation_directory[PATH_MAX];
	char mutation_lock_path[PATH_MAX];
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
	int first_mutation_lock;
	int second_mutation_lock;
	char *plan[] = {"plan"};
	char *prepare[] = {"prepare"};
	char *start[] = {"start"};
	char *stop[] = {"stop"};
	char *recover[] = {"recover"};

	memset(&swapz_primary_selected_target, 0,
	       sizeof(swapz_primary_selected_target));
	memcpy(swapz_primary_selected_target.partuuid, TEST_PARTUUID,
	       sizeof(TEST_PARTUUID));
	swapz_primary_selected_target.device_major = 8U;
	swapz_primary_selected_target.device_minor = 4U;
	swapz_primary_selected_target.device_bytes = TEST_DEVICE_BYTES;
	pages = swapz_primary_maximum_logical_pages(
		swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES));
	assert(pages == 3727616ULL);
	assert(swapz_authority_capacity_window(
		(swapz_u32)pages, (swapz_u32)swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES),
		&reserve_blocks));
	assert(reserve_blocks == 465952U);
	assert(swapz_primary_page_limit_fits(swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES),
						 pages));
	assert(!swapz_primary_page_limit_fits(swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES),
						  pages + 1ULL));
	assert(!swapz_primary_page_limit_fits(
		swapz_primary_physical_blocks(SWAPZ_PRIMARY_DEVICE_BYTES), 3727872ULL));
	assert(swapz_primary_maximum_logical_pages(30465536ULL) ==
	       27080192ULL);
	reserve_blocks = 0;
	assert(swapz_authority_capacity_window(
		27080192U, 30465536U, &reserve_blocks));
	assert(reserve_blocks == 3385024U);
	assert(swapz_primary_page_limit_fits(30465536ULL, 27080192ULL));
	assert(!swapz_primary_page_limit_fits(30465536ULL, 27080193ULL));
	assert(!swapz_primary_page_limit_fits(30465536ULL, 27080448ULL));
	assert(27080192ULL * SWAPZ_PRIMARY_BLOCK_BYTES == 110920466432ULL);
	{
		static const unsigned char swap_magic[] = "SWAPSPACE2";
		unsigned char raw_swap_header[SWAPZ_PRIMARY_BLOCK_BYTES] = {0};
		const uint64_t raw_device_bytes = 124787884032ULL;
		const uint32_t raw_last_page =
			(uint32_t)(raw_device_bytes / SWAPZ_PRIMARY_BLOCK_BYTES - 1ULL);

		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U);
		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET, raw_last_page);
		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 0U);
		memcpy(raw_swap_header + sizeof(raw_swap_header) -
		       sizeof(swap_magic) + 1U,
		       swap_magic, sizeof(swap_magic) - 1U);
		assert(swapz_primary_swap_size_kib_from_header(
			       raw_swap_header, raw_device_bytes) == 121863164ULL);
		/* The SWAPSPACE2 declaration, not a sub-page partition tail,
		 * determines Linux's /proc/swaps Size value. */
		assert(swapz_primary_swap_size_kib_from_header(
			       raw_swap_header, raw_device_bytes + 4095ULL) ==
		       121863164ULL);
		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, 2U);
		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET, 257U);
		test_put_u32_le(raw_swap_header,
				SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET +
					sizeof(uint32_t), 513U);
		assert(swapz_primary_swap_size_kib_from_header(
			       raw_swap_header, raw_device_bytes) == 121863156ULL);
	}
	assert(swapz_primary_linux_swap_size_kib(27080192ULL) == 108320764ULL);
	assert(121863164ULL !=
	       swapz_primary_linux_swap_size_kib(27080192ULL));
	assert(swapz_primary_linux_swap_size_kib(0ULL) == 0ULL);
	assert(swapz_primary_linux_swap_size_kib(UINT64_MAX) == 0ULL);
	assert(!swapz_primary_page_limit_fits(0ULL, 1ULL));
	assert(!swapz_primary_page_limit_fits(
		3ULL * SWAPZ_PRIMARY_SEGMENT_BLOCKS + 1ULL, 1ULL));
	/* First segment-rounded physical geometry outside the kernel u32
	 * address domain must fail before mapper planning, not truncate. */
	assert(!swapz_primary_page_limit_fits(
		(uint64_t)UINT32_MAX + 1ULL, 1ULL));
	assert(swapz_primary_maximum_logical_pages(
		       (uint64_t)UINT32_MAX + 1ULL) == 0ULL);
	assert(swapz_primary_physical_blocks(
		       ((uint64_t)UINT32_MAX + 2ULL) *
		       SWAPZ_PRIMARY_BLOCK_BYTES) == 0ULL);
	test_execution_record_is_boot_source_and_target_bound();
	test_partuuid_validation_and_normalization();
	test_recovery_required_state_builder();
	test_primary_swap_transition_adapter();
	test_swap_inventory_parser();
	test_memavailable_parser();
	test_selected_target_swap_admission();
	test_target_identity_and_header_policy();
	test_target_config_and_dynamic_geometry();
	test_selector_rejects_replaced_file_and_directory();
	test_target_preflight_snapshots_aliased_partuuid();
	test_primary_linux_swap_header();
	test_primary_run_id_generation();
	test_primary_stage_policy();
	test_primary_state_records();
	test_mapper_node_retry_policy();
	test_recoverable_lifecycle_stages();
	test_backing_header_digest_recognition();
	test_primary_dm_table();
	test_primary_dm_existing_mapper_selector();
	test_primary_dm_operations_disabled();
	test_exclusive_target_open_paths();
	test_exact_block_read_helper();
	test_sha256_helper();
	test_sha256_regular_fd();
	test_runtime_state_filesystem_policy();
	test_recovery_source_chain();
	test_mountinfo_parser();
	test_module_mapper_identity_policy();
	test_primary_module_parameter_parser();
	test_qualified_module_fd();
	test_build_source_provenance_policy();
	test_primary_qualification_report_parser();
	test_primary_qualification_report_store();
	test_primary_qualification_live_reader_disabled_in_rootless();
	test_orphan_ready_claim_reconciliation();
	test_primary_preparation_refusal_helpers();
	test_package_transaction_process_death_guard();
	assert(home && home[0] == '/');
	assert(snprintf(base_template, sizeof(base_template),
			 "%s/.swapz-primary-lock-XXXXXX", home) > 0);
	assert(mkdtemp(base_template));
	assert(snprintf(mutation_directory, sizeof(mutation_directory),
			 "%s/mutation-lock", base_template) > 0);
	assert(snprintf(mutation_lock_path, sizeof(mutation_lock_path),
			 "%s/%s", mutation_directory,
			 SWAPZ_PRIMARY_MUTATION_LOCK_NAME) > 0);
	errno = 0;
	assert(access(mutation_directory, F_OK) < 0 && errno == ENOENT);
	first_mutation_lock = swapz_primary_mutation_lock_at(
		mutation_directory, geteuid());
	assert(first_mutation_lock >= 0);
	assert(access(mutation_directory, F_OK) == 0);
	assert(close(first_mutation_lock) == 0);
	assert(unlink(mutation_lock_path) == 0);
	assert(rmdir(mutation_directory) == 0);
	first_mutation_lock = swapz_primary_mutation_lock_at(
		base_template, geteuid());
	assert(first_mutation_lock >= 0);
	second_mutation_lock = swapz_primary_mutation_lock_at(
		base_template, geteuid());
	assert(second_mutation_lock < 0);
	assert(errno == EWOULDBLOCK || errno == EAGAIN);
	assert(close(first_mutation_lock) == 0);
	second_mutation_lock = swapz_primary_mutation_lock_at(
		base_template, geteuid());
	assert(second_mutation_lock >= 0);
	assert(close(second_mutation_lock) == 0);
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
	test_primary_transaction_manifest_integrity(
		recovery_fd, first_lock, run_id);
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
	test_primary_module_load_record(
		recovery_fd, first_lock, run_id);
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	assert(swapz_primary_state_write_at(recovery_fd, first_lock,
						    &lifecycle, geteuid()) == 0);
	assert(swapz_primary_state_require_recovery_at(
		recovery_fd, first_lock, run_id, geteuid()) == 0);
	lifecycle.recovery_previous_stage = SWAPZ_PRIMARY_STAGE_ACTIVE;
	lifecycle.has_recovery_previous_stage = 1;
	lifecycle.stage = SWAPZ_PRIMARY_STAGE_RECOVERY_REQUIRED;
	assert_primary_state_equals(recovery_fd, &lifecycle);
	/* Re-marking the same failure is idempotent and keeps its origin. */
	assert(swapz_primary_state_require_recovery_at(
		recovery_fd, first_lock, run_id, geteuid()) == 0);
	assert_primary_state_equals(recovery_fd, &lifecycle);
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
	/* A completed A-side retry must not mutate B after the same lock is reused. */
	errno = 0;
	assert(swapz_primary_state_require_recovery_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	assert(errno == EPERM);
	assert(swapz_primary_release_partition_owner_at(
		recovery_fd, first_lock, run_id, geteuid()) < 0);
	assert(errno == EPERM);
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
	/* swapz_primary_mutation_lock_at() intentionally leaves its stable lock
	 * inode behind in production. This private fixture owns that inode and
	 * must remove it before asserting the temporary directory is empty. */
	assert(unlinkat(recovery_fd, SWAPZ_PRIMARY_MUTATION_LOCK_NAME, 0) == 0);
	assert(fsync(recovery_fd) == 0);
	assert(close(recovery_fd) == 0);
	assert(chmod(base_template, 0755) == 0);
	assert(swapz_primary_recovery_base_open(
		base_template, geteuid()) < 0);
	assert(chmod(base_template, 0700) == 0);
	assert(rmdir(base_template) == 0);
	assert(swapz_primary_privileged_execution_enabled() == 0);
	assert(swapz_primary_command(1, plan) == 2);
	assert(swapz_primary_command(1, prepare) == 2);
	assert(swapz_primary_command(1, start) == 2);
	assert(swapz_primary_command(1, stop) == 2);
	assert(swapz_primary_command(1, recover) == 2);
	test_shared_root_scope_authorization_is_exact();
	test_shared_root_sysfs_layout_skips_attribute_files();
	test_shared_root_scope_rejects_overlapping_partition_layout();
	test_shared_root_scope_record_requires_private_regular_file();
	puts("PASS: primary swap inventory, capacity, durable stage transitions, owner claims and disabled lifecycle gate");
	return 0;
}
