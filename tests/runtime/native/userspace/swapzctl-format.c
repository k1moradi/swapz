// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#include <sys/types.h>
#include <unistd.h>

/* Inject a short successful system write into the real formatter helper. */
static unsigned int test_pwrite_calls;
static int test_pwrite_short;
static ssize_t test_format_pwrite(int fd, const void *buffer, size_t length,
				  off_t offset);

#define pwrite test_format_pwrite
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main
#undef pwrite

#include <assert.h>
#include <stdio.h>

static const char *test_configured_partuuid = "f13428f6-01";
static int test_config_error;

int swapz_primary_target_config_read(
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	if (test_config_error || !test_configured_partuuid) {
		errno = test_config_error ? test_config_error : ENOENT;
		return -1;
	}
	if (strlen(test_configured_partuuid) > SWAPZ_PRIMARY_PARTUUID_LENGTH) {
		errno = EINVAL;
		return -1;
	}
	strcpy(partuuid, test_configured_partuuid);
	return 0;
}

static ssize_t test_format_pwrite(int fd, const void *buffer, size_t length,
				  off_t offset)
{
	++test_pwrite_calls;
	if (test_pwrite_short)
		return pwrite(fd, buffer, length / 2U, offset);
	return pwrite(fd, buffer, length, offset);
}

int swapz_primary_command(int argc, char **argv)
{
	(void)argc;
	(void)argv;
	return 99;
}

struct mock_format_context {
	unsigned char media[SWAPZ_SUPERBLOCK_BYTES];
	int preopen_error;
	int open_error;
	int read_error;
	int random_error;
	int write_error;
	int sync_error;
	int close_error;
	int verify_errors[8];
	size_t verify_error_count;
	size_t verify_error_index;
	int authorization_errors[8];
	size_t authorization_error_count;
	size_t authorization_error_index;
	unsigned int authorization_calls;
	unsigned int preopen_calls;
	unsigned int open_calls;
	unsigned int verify_calls;
	unsigned int read_calls;
	unsigned int random_calls;
	unsigned int write_calls;
	unsigned int sync_calls;
	unsigned int close_calls;
};

static struct format_expectation authorized_expectation(void)
{
	struct format_expectation expected;

	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6-01", &expected) == 0);
	assert(format_parent_expectation("Multi-Card", "usb", &expected) == 0);
	return expected;
}

static int mock_authorized_target_verify(
	void *opaque, const struct format_expectation *expected)
{
	struct mock_format_context *context = opaque;
	int error = 0;

	assert(expected != NULL);
	context->authorization_calls++;
	if (context->authorization_error_index <
	    context->authorization_error_count)
		error = context->authorization_errors[
			context->authorization_error_index++];
	if (error) {
		errno = error;
		return -1;
	}
	return 0;
}

static int mock_preopen_verify(void *opaque, const char *path,
			       const struct format_expectation *expected)
{
	struct mock_format_context *context = opaque;

	assert(path != NULL);
	assert(expected != NULL);
	context->preopen_calls++;
	if (context->preopen_error) {
		errno = context->preopen_error;
		return -1;
	}
	return 0;
}

static int mock_open_device(void *opaque, const char *path)
{
	struct mock_format_context *context = opaque;

	assert(path != NULL);
	context->open_calls++;
	if (context->open_error) {
		errno = context->open_error;
		return -1;
	}
	return 17;
}

static int mock_verify_opened(void *opaque, int fd, const char *path,
			      const struct format_expectation *expected)
{
	struct mock_format_context *context = opaque;
	int error = 0;

	assert(fd == 17);
	assert(path != NULL);
	assert(expected != NULL);
	context->verify_calls++;
	if (context->verify_error_index < context->verify_error_count)
		error = context->verify_errors[context->verify_error_index++];
	if (error) {
		errno = error;
		return -1;
	}
	return 0;
}

static int mock_read_header(void *opaque, int fd,
			    unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->read_calls++;
	if (context->read_error) {
		errno = context->read_error;
		return -1;
	}
	memcpy(block, context->media, sizeof(context->media));
	return 0;
}

static int mock_random_bytes(void *opaque, unsigned char *bytes, size_t length)
{
	struct mock_format_context *context = opaque;

	context->random_calls++;
	if (context->random_error) {
		errno = context->random_error;
		return -1;
	}
	memset(bytes, 0x5a, length);
	return 0;
}

static int mock_write_header(
	void *opaque, int fd,
	const unsigned char block[SWAPZ_SUPERBLOCK_BYTES])
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->write_calls++;
	if (context->write_error) {
		/*
		 * Model a transport failure after a possible torn publication:
		 * callers must not infer "no bytes written" from an error return.
		 */
		memcpy(context->media, block, sizeof(context->media) / 2U);
		errno = context->write_error;
		return -1;
	}
	memcpy(context->media, block, sizeof(context->media));
	return 0;
}

static int mock_sync_device(void *opaque, int fd)
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->sync_calls++;
	if (context->sync_error) {
		errno = context->sync_error;
		return -1;
	}
	return 0;
}

static int mock_close_device(void *opaque, int fd)
{
	struct mock_format_context *context = opaque;

	assert(fd == 17);
	context->close_calls++;
	if (context->close_error) {
		errno = context->close_error;
		return -1;
	}
	return 0;
}

static struct format_runtime_ops mock_ops(struct mock_format_context *context)
{
	const struct format_runtime_ops ops = {
		.context = context,
		.authorized_target_verify = mock_authorized_target_verify,
		.preopen_verify = mock_preopen_verify,
		.open_device = mock_open_device,
		.verify_opened = mock_verify_opened,
		.read_header = mock_read_header,
		.random_bytes = mock_random_bytes,
		.write_header = mock_write_header,
		.sync_device = mock_sync_device,
		.close_device = mock_close_device,
	};

	return ops;
}

static void make_valid_header(
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES],
	unsigned long long device_bytes)
{
	memset(header, 0, SWAPZ_SUPERBLOCK_BYTES);
	memcpy(header + SWAPZ_SUPERBLOCK_MAGIC_OFFSET, swapz_superblock_magic,
	       SWAPZ_SUPERBLOCK_MAGIC_BYTES);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_VERSION_OFFSET,
			 SWAPZ_SUPERBLOCK_VERSION);
	swapz_sb_put_u32(header + SWAPZ_SUPERBLOCK_HEADER_BYTES_OFFSET,
			 SWAPZ_SUPERBLOCK_BYTES);
	swapz_sb_put_u64(header + SWAPZ_SUPERBLOCK_DEVICE_BYTES_OFFSET,
			 device_bytes);
	memset(header + SWAPZ_SUPERBLOCK_UUID_OFFSET, 0x33,
	       SWAPZ_SUPERBLOCK_UUID_BYTES);
}

static void test_numeric_bound_parser(void)
{
	const char *end = NULL;
	unsigned long long value = 0;

	assert(parse_unsigned_decimal("1", 1ULL, &end, &value) == 0);
	assert(*end == '\0' && value == 1ULL);
	assert(parse_unsigned_decimal("2", 1ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("01", 10ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("00", 10ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("9", 0ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal(NULL, 1ULL, &end, &value) < 0);
	assert(parse_unsigned_decimal("1", 1ULL, NULL, &value) < 0);
	assert(parse_unsigned_decimal("1", 1ULL, &end, NULL) < 0);
	assert(format_parse_text_u64("1\n", 1ULL, &value) == 0);
	assert(value == 1ULL);
	assert(format_parse_text_u64("01\n", 10ULL, &value) < 0);
	assert(format_parse_text_u64("2\n", 1ULL, &value) < 0);
}

static void test_format_expectation_parser(void)
{
	struct format_expectation expected;
	char too_long[SWAPZ_PRIMARY_PARTUUID_LENGTH + 2U];

	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"F13428F6-01", &expected) == 0);
	assert(expected.device_major == 8U);
	assert(expected.device_minor == 1U);
	assert(expected.parent_major == 8U);
	assert(expected.parent_minor == 0U);
	assert(expected.device_bytes == 124787884032ULL);
	assert(!strcmp(expected.partuuid, "f13428f6-01"));
	assert(format_parent_expectation("Multi-Card", "usb", &expected) == 0);
	assert(!strcmp(expected.parent_model, "Multi-Card"));
	assert(format_parent_expectation("", "usb", &expected) < 0);
	assert(format_parent_expectation(" Multi-Card", "usb", &expected) < 0);
	assert(format_parent_expectation("Multi-Card", "sata", &expected) < 0);
	assert(parse_format_expectation("259:17", "259:16", "8589934592",
					"ABCDEF12-34", &expected) == 0);

	memset(too_long, 'a', sizeof(too_long));
	too_long[sizeof(too_long) - 1U] = '\0';
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"--------", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"-f13428f6", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6-", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428f6--01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"f13428g6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					"abc-def", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884032",
					too_long, &expected) < 0);

	assert(parse_format_expectation("-8:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("08:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:01", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "0124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("0:1", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "0:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1 ", "8:0", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:1", "124787884032",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "124787884033",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0", "1",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("8:1", "8:0",
					"18446744073709551616",
					"f13428f6-01", &expected) < 0);
	assert(parse_format_expectation("4294967296:1", "8:0",
					"124787884032", "f13428f6-01",
					&expected) < 0);
}

static void test_identity_table_rejects_substitution(void)
{
	struct format_expectation expected = authorized_expectation();
	struct stat path_info = { .st_mode = S_IFBLK | 0600,
				  .st_rdev = makedev(8U, 1U) };
	struct stat opened_info = path_info;
	struct stat partuuid_info = path_info;

	assert(format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));

	path_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	path_info = opened_info;

	opened_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	opened_info = path_info;

	partuuid_info.st_rdev = makedev(8U, 2U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
	partuuid_info = path_info;

	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes - SWAPZ_SUPERBLOCK_BYTES, makedev(8U, 0U)));
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 16U)));

	opened_info.st_mode = S_IFREG | 0600;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &partuuid_info,
		expected.device_bytes, makedev(8U, 0U)));
}

static void test_topology_flags_fail_closed(void)
{
	assert(format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(0, 1, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 0, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 0, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 0, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 0, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 0, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 0, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 0, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 1, 0));
	assert(format_usb_transport_path(
		"/sys/devices/pci0000:00/usb1/1-2/host0/target0:0:0/0:0:0:0"));
	assert(!format_usb_transport_path(
		"/sys/devices/pci0000:00/ata1/host0/target0:0:0/0:0:0:0"));
	{
		char model[] = "Multi-Card   \n";
		char wrong_model[] = "Other\n";

		assert(format_observed_model_matches(model, "Multi-Card"));
		assert(!format_observed_model_matches(wrong_model, "Multi-Card"));
	}
}

static void test_mountinfo_device_parser(void)
{
	dev_t device = 0;
	unsigned int optional_fields = 0U;
	const char token[] = "rw";

	/* Invalid spans fail without undefined pointer arithmetic under UBSan. */
	assert(!format_mountinfo_optional_valid(NULL, token + 2U,
						 &optional_fields));
	assert(!format_mountinfo_optional_valid(token, NULL, &optional_fields));
	assert(!format_mountinfo_rw_options_valid(NULL, token + 2U));
	assert(!format_mountinfo_rw_options_valid(token, NULL));

	assert(format_mountinfo_line_device(
		"36 25 8:1 / /mnt rw,relatime - ext4 /dev/sda1 rw\n",
		&device) == 0);
	assert(device == makedev(8U, 1U));
	assert(format_mountinfo_line_device("36 25 bad / /mnt rw\n",
					    &device) < 0);
	assert(format_mountinfo_line_device("36 25 8:1\n", &device) < 0);
	assert(format_mountinfo_line_device(
		"036 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"2147483648 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	/*
	 * Pseudo-filesystem mounts (major zero) and filesystem-specific root
	 * tokens are normal. They must not reject unrelated host namespaces.
	 */
	assert(format_mountinfo_line_device(
		"36 25 0:20 / /proc rw - proc proc rw\n", &device) == 0);
	assert(device == makedev(0U, 20U));
	assert(!format_inventory_device_conflicts(device, makedev(8U, 1U),
						 makedev(8U, 0U)));
	assert(format_mountinfo_line_device(
		"37 25 0:0 / /tmp rw - tmpfs tmpfs rw\n", &device) == 0);
	assert(device == makedev(0U, 0U));
	assert(format_mountinfo_line_device(
		"38 25 0:4 net:[4026531840] /run/netns/example rw - nsfs nsfs rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 0:4294967296 / /proc rw - proc proc rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 -1:20 / /proc rw - proc proc rw\n", &device) < 0);

	/* An unrelated device cannot make an incomplete inventory harmless. */
	assert(format_mountinfo_line_device(
		"garbage 25 8:2 / /other rw - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 - ext4 /dev/sda2 rw\n", &device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2 rw trailing\n",
		&device) < 0);

	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:7 - ext4 /dev/sda2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other ro,nosuid - ext4 /dev/sda2 ro,errors=remount-ro\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other invalid - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw - ext4 /dev/sda2 invalid\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:7 shared:8 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw master:7 master:8 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw propagate_from:7 - ext4 /dev/sda2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw master:7 propagate_from:8 - ext4 /dev/sda2 rw\n",
		&device) == 0);
	/* Unknown optional fields are explicitly forward-compatible mountinfo. */
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw future:abc - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\040name rw shared:7 - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\9xx rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\000 rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\377 rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other\\011tab rw - ext4 /dev/sdb2 rw\n",
		&device) == 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 opaque-root relative rw - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:garbage - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw shared:0 - ext4 /dev/sdb2 rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 8:2 / /other rw mysterious:123 - ext4 /dev/sdb2 rw\n",
		&device) == 0);
}

static void test_mount_and_swap_identity_conflicts(void)
{
	dev_t device = makedev(8U, 1U);
	dev_t parent = makedev(8U, 0U);

	assert(format_inventory_device_conflicts(device, device, parent));
	assert(format_inventory_device_conflicts(parent, device, parent));
	assert(!format_inventory_device_conflicts(makedev(8U, 2U),
						  device, parent));
}

static void test_mountinfo_fixture_path(char path[PATH_MAX],
					const char *root, const char *relative)
{
	int length = snprintf(path, PATH_MAX, "%s/%s", root, relative);

	assert(length > 0 && (size_t)length < PATH_MAX);
}

static void test_mountinfo_fixture_write(const char *root,
					 const char *relative,
					 const char *contents)
{
	char path[PATH_MAX];
	FILE *stream;

	test_mountinfo_fixture_path(path, root, relative);
	stream = fopen(path, "w");
	assert(stream);
	assert(fputs(contents, stream) >= 0);
	assert(fclose(stream) == 0);
}

static void test_mounts_in_other_namespaces_refuse_formatting(void)
{
	char root[] = "/tmp/swapzctl-mountinfo-XXXXXX";
	char path[PATH_MAX];
	const dev_t device = makedev(8U, 1U);
	const dev_t parent = makedev(8U, 0U);

	/* No real mount, block device, or mount namespace is touched. */
	assert(mkdtemp(root));
	test_mountinfo_fixture_path(path, root, "self");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "3031");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_path(path, root, "3031/ns");
	assert(mkdir(path, 0700) == 0);
	test_mountinfo_fixture_write(root, "3031/ns/mnt", "namespace\n");
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"36 25 0:20 / /proc rw - proc proc rw\n");
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:1 / /card rw - ext4 /dev/sda1 rw\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EBUSY);

	/* The parent disk also conflicts, but a sibling does not. */
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:0 / /disk rw - ext4 /dev/sda rw\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EBUSY);
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	assert(format_mount_inventory_clear_from_proc(root, device, parent) == 0);

	/* A readable but empty or truncated live inventory is not clearance. */
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_write(root, "3031/mountinfo", "");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_write(
		root, "3031/mountinfo",
		"37 25 8:2 / /other rw - ext4 /dev/sda2 rw\n");
	test_mountinfo_fixture_write(root, "self/mountinfo", "");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_write(
		root, "self/mountinfo",
		"36 25 0:20 / /proc rw - proc proc rw\n");

	/* Malformed or missing evidence for a live mount namespace still fails. */
	test_mountinfo_fixture_write(root, "3031/mountinfo", "invalid\n");
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == EPROTO);
	test_mountinfo_fixture_path(path, root, "3031/mountinfo");
	assert(unlink(path) == 0);
	errno = 0;
	assert(format_mount_inventory_clear_from_proc(root, device, parent) < 0);
	assert(errno == ENOENT);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EINVAL) == 0);

	/*
	 * A task with no mount namespace cannot keep the selected storage mounted.
	 * Model the Linux zombie/exit race: the PID entry remains, mountinfo is
	 * unavailable, and ns/mnt is absent. Only known task-exit errors may pass.
	 */
	test_mountinfo_fixture_path(path, root, "3031/ns/mnt");
	assert(unlink(path) == 0);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EINVAL) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", ENOENT) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", ESRCH) == 1);
	assert(format_mountinfo_open_failure_ignorable(
		       root, "3031", EACCES) == 0);
	assert(format_mount_inventory_clear_from_proc(root, device, parent) == 0);

	test_mountinfo_fixture_path(path, root, "self/mountinfo");
	assert(unlink(path) == 0);
	test_mountinfo_fixture_path(path, root, "3031/ns");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, root, "3031");
	assert(rmdir(path) == 0);
	test_mountinfo_fixture_path(path, root, "self");
	assert(rmdir(path) == 0);
	assert(rmdir(root) == 0);
}

static FILE *test_swap_inventory_stream(const char *contents)
{
	FILE *stream = tmpfile();

	assert(stream);
	if (contents && *contents)
		assert(fputs(contents, stream) >= 0);
	rewind(stream);
	return stream;
}

static void test_swap_inventory_requires_complete_kernel_table(void)
{
	char swap_path[] = "/tmp/swapzctl-swapfile-XXXXXX";
	char inventory[PATH_MAX + 128U];
	struct stat info;
	FILE *stream;
	dev_t parent_device;
	int swap_fd;
	int length;

	swap_fd = mkstemp(swap_path);
	assert(swap_fd >= 0);
	assert(fstat(swap_fd, &info) == 0);
	parent_device = makedev(1U, 1U);
	if (parent_device == info.st_dev)
		parent_device = makedev(1U, 2U);

	stream = test_swap_inventory_stream("");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	stream = test_swap_inventory_stream(
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n");
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) == 0);
	assert(fclose(stream) == 0);

	/* The kernel header grammar is literal, not merely five whitespace tokens. */
	stream = test_swap_inventory_stream(
		"Filename Type Size Used Priority\n");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	stream = test_swap_inventory_stream(
		"Filename Type Size Used\n");
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	length = snprintf(inventory, sizeof(inventory), "%s file 1 0 -2\n",
			  swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	length = snprintf(
		inventory, sizeof(inventory),
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n%s file 1 0 -2\n",
		swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EBUSY);
	assert(fclose(stream) == 0);

	length = snprintf(
		inventory, sizeof(inventory),
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n%s partition 1 0 -2\n",
		swap_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_swap_inventory_stream(inventory);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, info.st_dev,
						  parent_device) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);

	assert(close(swap_fd) == 0);
	assert(unlink(swap_path) == 0);
}

/*
 * Exercise the real production parsers with byte-exact, rootless inventories.
 * No swapon, mount, device nodes or formatter writes are performed.
 */
static FILE *test_inventory_binary_stream(const void *bytes, size_t length)
{
	FILE *stream = tmpfile();

	assert(stream);
	assert(fwrite(bytes, 1U, length, stream) == length);
	rewind(stream);
	return stream;
}

static void test_mountinfo_adversarial_inventory(void)
{
	static const char unrelated[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n";
	static const char duplicate[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n"
		"36 25 8:3 / /another rw - ext4 /dev/sdb3 rw\n";
	static const char embedded_nul[] =
		"36 25 8:2 / /other rw - ext4 /dev/sdb2 rw\n\0"
		"37 25 8:1 / /card rw - ext4 /dev/sda1 rw\n";
	static const char high_bytes[] =
		"36 25 8:2 /r\xc3\xa9 /mnt rw - ext4 /dev/sdb2 rw\n";
	static const char raw_control[] =
		"36 25 8:2 / /mnt\rname rw - ext4 /dev/sdb2 rw\n";
	const dev_t device = makedev(8U, 1U);
	const dev_t parent = makedev(8U, 0U);
	char oversized[SWAPZ_FORMAT_PROC_LINE_BYTES + 4U];
	FILE *stream;
	unsigned int state = 0x728b31f5U;

	stream = test_inventory_binary_stream(unrelated, sizeof(unrelated) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(high_bytes, sizeof(high_bytes) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	/* Only NUL is impossible in a pathname; other raw filename bytes are legal. */
	stream = test_inventory_binary_stream(raw_control,
					     sizeof(raw_control) - 1U);
	assert(format_mountinfo_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(duplicate, sizeof(duplicate) - 1U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(embedded_nul,
					     sizeof(embedded_nul) - 1U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(unrelated, sizeof(unrelated) - 2U);
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	memset(oversized, 'x', sizeof(oversized));
	oversized[sizeof(oversized) - 1U] = '\n';
	stream = test_inventory_binary_stream(oversized, sizeof(oversized));
	errno = 0;
	assert(format_mountinfo_stream_clear(stream, device, parent) < 0);
	assert(errno == EOVERFLOW);
	assert(fclose(stream) == 0);

	/* Deterministic bounded byte mutation: NUL can never hide a busy row. */
	for (unsigned int iteration = 0; iteration < 256U; ++iteration) {
		char mutated[sizeof(unrelated)];
		size_t index;

		memcpy(mutated, unrelated, sizeof(unrelated) - 1U);
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		index = state % (sizeof(unrelated) - 1U);
		mutated[index] = '\0';
		stream = test_inventory_binary_stream(mutated,
						       sizeof(unrelated) - 1U);
		assert(format_mountinfo_stream_clear(stream, device,
							     parent) < 0);
		assert(fclose(stream) == 0);
	}
}

static void test_swap_adversarial_inventory(void)
{
	static const char header[] =
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n";
	char file_path[] = "/tmp/swapzctl-unrelated-XXXXXX";
	char second_path[] = "/tmp/swapzctl-second-XXXXXX";
	char alias_path[] = "/tmp/swapzctl-same-inode-XXXXXX";
	char inventory[PATH_MAX + 256U];
	char duplicate[2U * PATH_MAX + 256U];
	struct stat info;
	struct stat other_info;
	dev_t device = makedev(8U, 1U);
	dev_t parent = makedev(8U, 0U);
	unsigned int state = 0x9e3779b9U;
	FILE *stream;
	int fd;
	int second_fd;
	int alias_fd;
	int length;
	char parsed_path[PATH_MAX];
	int block_entry;

	fd = mkstemp(file_path);
	assert(fd >= 0);
	assert(fstat(fd, &info) == 0);
	if (info.st_dev == device)
		device = makedev(8U, 3U);
	if (info.st_dev == parent)
		parent = makedev(8U, 4U);
	length = snprintf(inventory, sizeof(inventory),
			  "%s%s file 1 0 -2\n", header, file_path);
	assert(length > 0 && (size_t)length < sizeof(inventory));
	stream = test_inventory_binary_stream(inventory, (size_t)length);
	assert(format_swap_inventory_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);
	/* Distinct unrelated files on the same filesystem are both permitted. */
	second_fd = mkstemp(second_path);
	assert(second_fd >= 0);
	assert(fstat(second_fd, &other_info) == 0);
	assert(other_info.st_dev == info.st_dev);
	assert(other_info.st_ino != info.st_ino);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -3\n",
			  header, file_path, second_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	assert(format_swap_inventory_stream_clear(stream, device, parent) == 0);
	assert(fclose(stream) == 0);

	/* A hard-link alias of the SAME inode must not become a second swap. */
	alias_fd = mkstemp(alias_path);
	assert(alias_fd >= 0);
	assert(close(alias_fd) == 0);
	assert(unlink(alias_path) == 0);
	assert(link(file_path, alias_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -3\n",
			  header, file_path, alias_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	assert(unlink(alias_path) == 0);
	/*
	 * A pathname substituted with a symlink after swapon is not trusted:
	 * the active kernel object was not the symlink target we would follow now.
	 */
	assert(symlink(file_path, alias_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -3\n", header, alias_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	assert(unlink(alias_path) == 0);
	assert(close(second_fd) == 0);
	assert(unlink(second_path) == 0);
	length = snprintf(duplicate, sizeof(duplicate),
			  "%s%s file 1 0 -2\n%s file 1 0 -2\n",
			  header, file_path, file_path);
	assert(length > 0 && (size_t)length < sizeof(duplicate));
	stream = test_inventory_binary_stream(duplicate, (size_t)length);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	stream = test_inventory_binary_stream(inventory,
					     strlen(inventory) - 1U);
	errno = 0;
	assert(format_swap_inventory_stream_clear(stream, device, parent) < 0);
	assert(errno == EPROTO);
	assert(fclose(stream) == 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/\xc3\xa9 file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!block_entry);
	assert(!strcmp(parsed_path, "/tmp/\xc3\xa9"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\040file file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap file"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\134name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\\name"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\011name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\tname"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\\012name file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\nname"));
	assert(format_swap_inventory_entry_parse(
		       "/tmp/swap\rname file 1 0 -2\n", parsed_path,
		       &block_entry) == 0);
	assert(!strcmp(parsed_path, "/tmp/swap\rname"));

	/* Unknown row types, invalid sizes, priorities and missing columns fail. */
	static const char *const malformed_rows[] = {
		"/tmp/file unknown 1 0 -2\n",
		"/tmp/file file 0 0 -2\n",
		"/tmp/file file 1 2 -2\n",
		"/tmp/file file -1 0 -2\n",
		"/tmp/file file 1 0 +2\n",
		"/tmp/file file 1 0 -0\n",
		"/tmp/file file 01 0 -2\n",
		"/tmp/file file 1 00 -2\n",
		"/tmp/file file 1 0 -02\n",
		"/tmp/swap\\000name file 1 0 -2\n",
		"/tmp/swap\\777name file 1 0 -2\n",
		"/tmp/swap\\9xx file 1 0 -2\n",
		"/tmp/file file 18446744073709551616 0 -2\n",
		"/tmp/file file 1 0 -2147483649\n",
		"/tmp/file file 1 0 2147483648\n",
		"/tmp/file file 1 0\n",
		"relative file 1 0 -2\n",
	};
	for (size_t index = 0;
	     index < sizeof(malformed_rows) / sizeof(malformed_rows[0]);
	     ++index)
		assert(format_swap_inventory_entry_parse(
			       malformed_rows[index], parsed_path, &block_entry) < 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/file file 1 0 2147483647\n", parsed_path,
		       &block_entry) == 0);
	assert(format_swap_inventory_entry_parse(
		       "/tmp/file file 1 0 -2147483648\n", parsed_path,
		       &block_entry) == 0);

	for (unsigned int iteration = 0; iteration < 256U; ++iteration) {
		char mutated[sizeof(inventory)];
		size_t index;

		memcpy(mutated, inventory, strlen(inventory));
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		index = state % strlen(inventory);
		mutated[index] = '\0';
		stream = test_inventory_binary_stream(mutated,
						       strlen(inventory));
		assert(format_swap_inventory_stream_clear(stream, device,
								     parent) < 0);
		assert(fclose(stream) == 0);
	}

	/*
	 * An unrelated active swapfile name is emitted escaped by the kernel.
	 * Decode it before stat/lstat so a harmless filename cannot block format.
	 */
	{
		char directory[] = "/tmp/swapzctl-escaped-XXXXXX";
		char spaced_path[PATH_MAX];
		char encoded_path[PATH_MAX + 16U];
		int spaced_fd;

		assert(mkdtemp(directory));
		assert(snprintf(spaced_path, sizeof(spaced_path), "%s/swap file",
				directory) > 0);
		spaced_fd = open(spaced_path, O_CREAT | O_EXCL | O_RDWR, 0600);
		assert(spaced_fd >= 0);
		assert(snprintf(encoded_path, sizeof(encoded_path), "%s/swap\\040file",
				directory) > 0);
		length = snprintf(inventory, sizeof(inventory),
				  "%s%s file 1 0 -2\n", header, encoded_path);
		assert(length > 0 && (size_t)length < sizeof(inventory));
		stream = test_inventory_binary_stream(inventory, (size_t)length);
		assert(format_swap_inventory_stream_clear(stream, device, parent) == 0);
		assert(fclose(stream) == 0);
		assert(close(spaced_fd) == 0);
		assert(unlink(spaced_path) == 0);
		assert(rmdir(directory) == 0);
	}

	/* Byte and row budgets are checked without allocating enormous fixtures. */
	{
		char bounded_line[4];
		size_t bytes_read = SWAPZ_FORMAT_PROC_MAX_BYTES - 1U;
		size_t count = SWAPZ_FORMAT_PROC_MAX_ROWS;
		size_t capacity = 0;
		void *entries = NULL;
		unsigned long long identifier = 7ULL;

		stream = test_inventory_binary_stream("a\n", 2U);
		errno = 0;
		assert(format_inventory_read_line(stream, bounded_line,
						   sizeof(bounded_line),
						   &bytes_read) < 0);
		assert(errno == EOVERFLOW);
		assert(fclose(stream) == 0);
		errno = 0;
		assert(format_inventory_append(&entries, &count, &capacity,
						 &identifier, sizeof(identifier)) < 0);
		assert(errno == EOVERFLOW);
		assert(entries == NULL);
	}
	/* A sysfs attribute with an embedded NUL cannot pass text validation. */
	assert(lseek(fd, 0, SEEK_SET) == 0);
	assert(write(fd, "1\0\n", 3U) == 3);
	errno = 0;
	assert(format_read_text_file(file_path, parsed_path,
					     sizeof(parsed_path)) < 0);
	assert(errno == EPROTO);
	assert(close(fd) == 0);
	assert(unlink(file_path) == 0);
}

static void test_formatter_path_admission(void)
{
	struct format_expectation expected = authorized_expectation();
	struct stat path_info = {
		.st_mode = S_IFBLK | 0600, .st_rdev = makedev(8U, 1U),
		.st_dev = makedev(0U, 7U), .st_ino = 17U,
	};
	struct stat opened_info = path_info;
	struct stat partuuid_info = path_info;
	char regular[] = "/tmp/swapzctl-nofollow-XXXXXX";
	char alias[sizeof(regular) + 8U];
	int fd;

	assert(format_identity_values_match(&expected, &path_info, &opened_info,
						  &partuuid_info,
						  expected.device_bytes,
						  makedev(8U, 0U)));
	opened_info.st_ino++;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));
	opened_info = path_info;
	path_info.st_uid = 42U;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));
	path_info = opened_info;
	path_info.st_mode |= S_IWOTH;
	assert(!format_identity_values_match(&expected, &path_info, &opened_info,
						   &partuuid_info,
						   expected.device_bytes,
						   makedev(8U, 0U)));

	fd = mkstemp(regular);
	assert(fd >= 0);
	assert(snprintf(alias, sizeof(alias), "%s.link", regular) > 0);
	assert(symlink(regular, alias) == 0);
	errno = 0;
	assert(format_default_open_device(NULL, alias) < 0);
	assert(errno == ELOOP);
	assert(unlink(alias) == 0);
	assert(close(fd) == 0);
	assert(unlink(regular) == 0);
}

static void test_superblock_validation_and_reserved_bytes(void)
{
	struct format_expectation expected = authorized_expectation();
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES];

	make_valid_header(header, expected.device_bytes);
	assert(swapz_sb_valid(header, expected.device_bytes));
	header[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 1U;
	assert(!swapz_sb_valid(header, expected.device_bytes));
	header[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 0U;
	memset(header + SWAPZ_SUPERBLOCK_UUID_OFFSET, 0,
	       SWAPZ_SUPERBLOCK_UUID_BYTES);
	assert(!swapz_sb_valid(header, expected.device_bytes));
	make_valid_header(header, expected.device_bytes);
	assert(!swapz_sb_valid(header,
			       expected.device_bytes - SWAPZ_SUPERBLOCK_BYTES));
}

static void test_unbound_cli_is_blocked_before_io(void)
{
	char *unbound[] = { "swapzctl", "format", "/dev/anything" };
	char *old_bound[] = {
		"swapzctl", "format", "/dev/anything",
		"--expect-major-minor", "8:1",
		"--expect-bytes", "124787884032",
	};

	assert(swapzctl_program_main(3, unbound) == 2);
	assert(swapzctl_program_main(7, old_bound) == 2);
}

static void test_protected_selector_is_mandatory(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.authorization_errors = { EPERM },
		.authorization_error_count = 1U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_default_authorized_target_verify(NULL, &expected) == 0);
	test_configured_partuuid = "deadbeef-01";
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == EPERM);
	test_configured_partuuid = NULL;
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == ENOENT);
	test_configured_partuuid = "f13428f6-01";
	test_config_error = EACCES;
	errno = 0;
	assert(format_default_authorized_target_verify(NULL, &expected) < 0);
	assert(errno == EACCES);
	test_config_error = 0;

	/* An absent or mismatched selector cannot even open media. */
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.authorization_calls == 1U);
	assert(context.preopen_calls == 0U);
	assert(context.open_calls == 0U);
	assert(context.write_calls == 0U);
}

static void test_selector_revocation_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.authorization_errors = { 0, 0, EPERM },
		.authorization_error_count = 3U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.authorization_calls == 3U);
	assert(context.preopen_calls == 1U);
	assert(context.verify_calls == 1U);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_partial_header_write_is_not_resumed(void)
{
	unsigned char header[SWAPZ_SUPERBLOCK_BYTES] = {0};
	FILE *file = tmpfile();
	int fd;

	assert(file != NULL);
	fd = fileno(file);
	assert(fd >= 0);
	test_pwrite_calls = 0;
	test_pwrite_short = 1;
	errno = 0;
	assert(exact_io(fd, header, sizeof(header), 1) < 0);
	assert(errno == EIO);
	assert(test_pwrite_calls == 1U);
	test_pwrite_short = 0;
	assert(fclose(file) == 0);
}

static void test_preopen_permission_refuses_before_open_or_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = { .preopen_error = EACCES };
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.preopen_calls == 1U);
	assert(context.open_calls == 0U);
	assert(context.read_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 0U);
}

static void test_wrong_opened_device_refuses_before_read_or_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { ESTALE },
		.verify_error_count = 1U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.open_calls == 1U);
	assert(context.verify_calls == 1U);
	assert(context.read_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_invalid_header_refuses_without_write(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);

	make_valid_header(context.media, expected.device_bytes);
	context.media[SWAPZ_SUPERBLOCK_RESERVED_OFFSET] = 1U;
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_stale_identity_refuses_at_last_prewrite_gate(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, ESTALE },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.random_calls == 1U);
	assert(context.verify_calls == 2U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_device_disappearance_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, ENODEV },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.write_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_inventory_gate_errors_never_reach_header_write(void)
{
	static const int inventory_errors[] = {
		EPROTO, EOVERFLOW, EBUSY, EACCES,
	};
	struct format_expectation expected = authorized_expectation();

	for (size_t index = 0;
	     index < sizeof(inventory_errors) / sizeof(inventory_errors[0]);
	     ++index) {
		struct mock_format_context preopen = {
			.preopen_error = inventory_errors[index],
		};
		struct format_runtime_ops preopen_ops = mock_ops(&preopen);
		struct mock_format_context recheck = {
			.verify_errors = { 0 },
			.verify_error_count = 2U,
		};
		struct format_runtime_ops recheck_ops = mock_ops(&recheck);

		/* Even a late discovered mount/swap/parse ambiguity is no-write. */
		recheck.verify_errors[1] = inventory_errors[index];
		assert(format_device_with_ops("/synthetic/card", &expected,
					      &preopen_ops) == 2);
		assert(preopen.open_calls == 0U);
		assert(preopen.write_calls == 0U);
		assert(format_device_with_ops("/synthetic/card", &expected,
					      &recheck_ops) == 2);
		assert(recheck.read_calls == 1U);
		assert(recheck.random_calls == 1U);
		assert(recheck.write_calls == 0U);
		assert(recheck.sync_calls == 0U);
	}
}

static void test_read_only_transition_before_write_refuses(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, EROFS },
		.verify_error_count = 2U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 2);
	assert(context.read_calls == 1U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
}

static void test_publication_failures_are_explicitly_uncertain(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context write_context = { .write_error = EIO };
	struct format_runtime_ops write_ops = mock_ops(&write_context);
	struct mock_format_context sync_context = { .sync_error = EIO };
	struct format_runtime_ops sync_ops = mock_ops(&sync_context);
	struct mock_format_context close_context = { .close_error = EIO };
	struct format_runtime_ops close_ops = mock_ops(&close_context);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &write_ops) == 3);
	assert(write_context.write_calls == 1U);
	assert(write_context.sync_calls == 0U);
	/*
	 * The simulated failed write changed media, but it may coincidentally
	 * contain a structurally valid header because reserved tail bytes are zero.
	 * The error return still makes publication/durability uncertain.
	 */
	assert(!block_is_zero(write_context.media));
	assert(write_context.close_calls == 1U);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &sync_ops) == 3);
	assert(sync_context.write_calls == 1U);
	assert(sync_context.sync_calls == 1U);
	assert(swapz_sb_valid(sync_context.media, expected.device_bytes));
	assert(sync_context.close_calls == 1U);

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &close_ops) == 3);
	assert(close_context.write_calls == 1U);
	assert(close_context.sync_calls == 1U);
	assert(swapz_sb_valid(close_context.media, expected.device_bytes));
	assert(close_context.close_calls == 1U);
}

static void test_zero_header_format_and_readback(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);
	unsigned int i;

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 0);
	assert(context.preopen_calls == 1U);
	assert(context.open_calls == 1U);
	assert(context.verify_calls == 4U);
	assert(context.authorization_calls == 5U);
	assert(context.read_calls == 2U);
	assert(context.random_calls == 1U);
	assert(context.write_calls == 1U);
	assert(context.sync_calls == 1U);
	assert(context.close_calls == 1U);
	assert(swapz_sb_valid(context.media, expected.device_bytes));
	assert((context.media[SWAPZ_SUPERBLOCK_UUID_OFFSET + 6U] & 0xf0U) ==
	       0x40U);
	assert((context.media[SWAPZ_SUPERBLOCK_UUID_OFFSET + 8U] & 0xc0U) ==
	       0x80U);
	for (i = SWAPZ_SUPERBLOCK_RESERVED_OFFSET;
	     i < SWAPZ_SUPERBLOCK_BYTES; ++i)
		assert(context.media[i] == 0U);
}

static void test_repeat_format_is_idempotent_and_non_destructive(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {0};
	struct format_runtime_ops ops = mock_ops(&context);
	unsigned char original[SWAPZ_SUPERBLOCK_BYTES];

	make_valid_header(context.media, expected.device_bytes);
	memcpy(original, context.media, sizeof(original));
	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 0);
	assert(context.verify_calls == 2U);
	assert(context.authorization_calls == 3U);
	assert(context.read_calls == 1U);
	assert(context.random_calls == 0U);
	assert(context.write_calls == 0U);
	assert(context.sync_calls == 0U);
	assert(context.close_calls == 1U);
	assert(!memcmp(context.media, original, sizeof(original)));
}

static void test_disappearance_after_write_is_never_success(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context context = {
		.verify_errors = { 0, 0, ENODEV },
		.verify_error_count = 3U,
	};
	struct format_runtime_ops ops = mock_ops(&context);

	assert(format_device_with_ops("/synthetic/card", &expected, &ops) == 3);
	assert(context.write_calls == 1U);
	assert(context.sync_calls == 1U);
	assert(context.read_calls == 1U);
	assert(context.close_calls == 1U);
}

static void test_truncated_read_and_close_failure_are_not_success(void)
{
	struct format_expectation expected = authorized_expectation();
	struct mock_format_context read_context = { .read_error = EIO };
	struct format_runtime_ops read_ops = mock_ops(&read_context);
	struct mock_format_context close_context = { .close_error = EIO };
	struct format_runtime_ops close_ops = mock_ops(&close_context);
	unsigned char buffer[SWAPZ_SUPERBLOCK_BYTES];
	FILE *file = tmpfile();
	int fd;

	assert(format_device_with_ops("/synthetic/card", &expected,
				      &read_ops) == 1);
	assert(read_context.write_calls == 0U);
	assert(read_context.close_calls == 1U);

	assert(file != NULL);
	fd = fileno(file);
	assert(fd >= 0);
	assert(write(fd, "abc", 3U) == 3);
	errno = 0;
	assert(exact_io(fd, buffer, sizeof(buffer), 0) < 0);
	assert(errno == EIO);
	assert(fclose(file) == 0);

	make_valid_header(close_context.media, expected.device_bytes);
	assert(format_device_with_ops("/synthetic/card", &expected,
				      &close_ops) == 1);
	assert(close_context.write_calls == 0U);
	assert(close_context.close_calls == 1U);
}

int main(void)
{
	test_numeric_bound_parser();
	test_format_expectation_parser();
	test_identity_table_rejects_substitution();
	test_topology_flags_fail_closed();
	test_mountinfo_device_parser();
	test_mountinfo_adversarial_inventory();
	test_mount_and_swap_identity_conflicts();
	test_mounts_in_other_namespaces_refuse_formatting();
	test_swap_inventory_requires_complete_kernel_table();
	test_swap_adversarial_inventory();
	test_formatter_path_admission();
	test_superblock_validation_and_reserved_bytes();
	test_unbound_cli_is_blocked_before_io();
	test_protected_selector_is_mandatory();
	test_selector_revocation_before_write_refuses();
	test_partial_header_write_is_not_resumed();
	test_preopen_permission_refuses_before_open_or_write();
	test_wrong_opened_device_refuses_before_read_or_write();
	test_invalid_header_refuses_without_write();
	test_stale_identity_refuses_at_last_prewrite_gate();
	test_inventory_gate_errors_never_reach_header_write();
	test_device_disappearance_before_write_refuses();
	test_read_only_transition_before_write_refuses();
	test_publication_failures_are_explicitly_uncertain();
	test_zero_header_format_and_readback();
	test_repeat_format_is_idempotent_and_non_destructive();
	test_disappearance_after_write_is_never_success();
	test_truncated_read_and_close_failure_are_not_success();
	puts("PASS: swapzctl formatter identity and destructive-action gates");
	return 0;
}
