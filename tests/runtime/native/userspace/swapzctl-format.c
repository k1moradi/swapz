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

	assert(format_mountinfo_line_device(
		"36 25 8:1 / /mnt rw,relatime - ext4 /dev/sda1 rw\n",
		&device) == 0);
	assert(device == makedev(8U, 1U));
	assert(format_mountinfo_line_device("36 25 bad / /mnt rw\n",
					    &device) < 0);
	assert(format_mountinfo_line_device("36 25 8:1\n", &device) < 0);
	/*
	 * Pseudo-filesystem mounts (major zero) are normal on Linux hosts.
	 * They must be parseable without ever authorizing a physical target.
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
		"36 25 0:4294967296 / /proc rw - proc proc rw\n",
		&device) < 0);
	assert(format_mountinfo_line_device(
		"36 25 -1:20 / /proc rw - proc proc rw\n", &device) < 0);
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
	test_format_expectation_parser();
	test_identity_table_rejects_substitution();
	test_topology_flags_fail_closed();
	test_mountinfo_device_parser();
	test_mount_and_swap_identity_conflicts();
	test_superblock_validation_and_reserved_bytes();
	test_unbound_cli_is_blocked_before_io();
	test_protected_selector_is_mandatory();
	test_selector_revocation_before_write_refuses();
	test_partial_header_write_is_not_resumed();
	test_preopen_permission_refuses_before_open_or_write();
	test_wrong_opened_device_refuses_before_read_or_write();
	test_invalid_header_refuses_without_write();
	test_stale_identity_refuses_at_last_prewrite_gate();
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
