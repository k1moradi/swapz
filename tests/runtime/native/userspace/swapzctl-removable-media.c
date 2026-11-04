// SPDX-License-Identifier: GPL-2.0-only
#define _GNU_SOURCE
#define main swapzctl_program_main
#include "../../../../src/userspace/swapzctl.c"
#undef main

#include <assert.h>
#include <stdio.h>

int swapz_primary_target_config_read(
	char partuuid[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U])
{
	(void)partuuid;
	errno = ENOSYS;
	return -1;
}

int swapz_primary_command(int argc, char **argv)
{
	(void)argc;
	(void)argv;
	return 99;
}

static struct format_expectation expectation(const char *device,
					     const char *parent)
{
	struct format_expectation expected;

	assert(parse_format_expectation(device, parent, "124787884032",
					"f13428f6-01", &expected) == 0);
	assert(format_parent_expectation("Multi-Card", "usb", &expected) == 0);
	return expected;
}

static struct stat block_stat(unsigned int device_major,
			      unsigned int device_minor)
{
	const struct stat info = {
		.st_mode = S_IFBLK | 0600,
		.st_rdev = makedev(device_major, device_minor),
	};

	return info;
}

static void test_partuuid_canonicalization_rejects_weak_structures(void)
{
	char normalized[SWAPZ_PRIMARY_PARTUUID_LENGTH + 1U];

	assert(format_partuuid_normalize("F13428F6-01", normalized) == 0);
	assert(!strcmp(normalized, "f13428f6-01"));
	assert(format_partuuid_normalize(
		       "01234567-89AB-CDEF-0123-456789ABCDEF", normalized) == 0);
	assert(!strcmp(normalized, "01234567-89ab-cdef-0123-456789abcdef"));

	assert(format_partuuid_normalize("--------", normalized) < 0);
	assert(format_partuuid_normalize("-f13428f6", normalized) < 0);
	assert(format_partuuid_normalize("f13428f6-", normalized) < 0);
	assert(format_partuuid_normalize("f13428f6--01", normalized) < 0);
	assert(format_partuuid_normalize("abc-def", normalized) < 0);
	assert(format_partuuid_normalize("f13428g6-01", normalized) < 0);
}

static void test_copied_identifiers_cannot_replace_opened_device(void)
{
	struct format_expectation expected = expectation("8:1", "8:0");
	struct stat copied = block_stat(8U, 2U);

	/*
	 * Cloneable strings (PARTUUID/model/size) remain unchanged here.
	 * A different opened block identity is still rejected.
	 */
	assert(!format_identity_values_match(
		&expected, &copied, &copied, &copied, expected.device_bytes,
		makedev(8U, 0U)));
}

static void test_replaced_alias_and_parent_are_rejected(void)
{
	struct format_expectation expected = expectation("8:1", "8:0");
	struct stat path_info = block_stat(8U, 1U);
	struct stat opened_info = block_stat(8U, 1U);
	struct stat alias_info = block_stat(8U, 2U);

	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
	alias_info = path_info;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 16U)));
}

static void test_reconnection_requires_fresh_exact_device_identity(void)
{
	struct format_expectation old_expected = expectation("8:1", "8:0");
	struct format_expectation new_expected = expectation("8:17", "8:16");
	struct stat new_info = block_stat(8U, 17U);

	assert(!format_identity_values_match(
		&old_expected, &new_info, &new_info, &new_info,
		old_expected.device_bytes, makedev(8U, 16U)));
	assert(format_identity_values_match(
		&new_expected, &new_info, &new_info, &new_info,
		new_expected.device_bytes, makedev(8U, 16U)));
}

static void test_geometry_holders_and_active_inventory_fail_closed(void)
{
	struct format_expectation expected = expectation("8:1", "8:0");
	struct stat info = block_stat(8U, 1U);
	dev_t device = makedev(8U, 1U);
	dev_t parent = makedev(8U, 0U);

	assert(!format_identity_values_match(
		&expected, &info, &info, &info,
		expected.device_bytes - SWAPZ_SUPERBLOCK_BYTES, parent));
	assert(format_inventory_device_conflicts(device, device, parent));
	assert(format_inventory_device_conflicts(parent, device, parent));
	assert(!format_inventory_device_conflicts(makedev(8U, 2U),
						  device, parent));

	assert(format_topology_flags_allowed(1, 1, 1, 1, 1, 1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, 0, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 1, 1, 1, 1, -1, 1, 1, 1));
	assert(!format_topology_flags_allowed(1, 0, 1, 1, 1, 1, 1, 1, 1));
}

static void test_same_device_number_is_not_inode_authority(void)
{
	struct format_expectation expected = expectation("8:1", "8:0");
	struct stat path_info = block_stat(8U, 1U);
	struct stat opened_info = path_info;
	struct stat alias_info = path_info;

	path_info.st_dev = makedev(0U, 5U);
	opened_info.st_dev = path_info.st_dev;
	path_info.st_ino = 101U;
	opened_info.st_ino = path_info.st_ino;
	alias_info.st_uid = 0;
	assert(format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
	/* A replacement mknod of the same major:minor is a different pathname. */
	opened_info.st_ino = 102U;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
	opened_info.st_ino = 101U;
	opened_info.st_dev = makedev(0U, 6U);
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
	opened_info.st_dev = path_info.st_dev;
	alias_info.st_uid = 1000U;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
	alias_info.st_uid = 0U;
	alias_info.st_mode |= S_IWOTH;
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));
}

static void test_transport_path_must_still_be_usb(void)
{
	assert(format_usb_transport_path(
		"/sys/devices/pci0000:00/usb1/1-2/host0/target0:0:0/0:0:0:0"));
	assert(!format_usb_transport_path(
		"/sys/devices/pci0000:00/ata1/host0/target0:0:0/0:0:0:0"));
}

/*
 * Mountinfo device numbers can distinguish selected/parent/sibling mounts,
 * but a /proc/swaps pathname supplies no authenticated block or file inode.
 */
static void test_swap_inventory_never_trusts_local_path_identity(void)
{
	static const char header[] =
		"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n";
	static const char *const entries[] = {
		"/tmp/foreign-swapfile file 1 0 -2\n",
		"/dev/selected partition 1 0 -2\n",
		"/dev/parent partition 1 0 -2\n",
		"/dev/sibling partition 1 0 -2\n",
	};
	const dev_t selected_device = makedev(8U, 1U);
	const dev_t parent_device = makedev(8U, 0U);

	assert(format_inventory_device_conflicts(selected_device,
						 selected_device, parent_device));
	assert(format_inventory_device_conflicts(parent_device,
						 selected_device, parent_device));
	assert(!format_inventory_device_conflicts(makedev(8U, 2U),
						  selected_device, parent_device));

	for (size_t index = 0;
	     index < sizeof(entries) / sizeof(entries[0]); ++index) {
		FILE *stream = tmpfile();

		assert(stream);
		assert(fputs(header, stream) >= 0);
		assert(fputs(entries[index], stream) >= 0);
		assert(fseek(stream, 0L, SEEK_SET) == 0);
		errno = 0;
		assert(format_swap_inventory_stream_clear(stream, selected_device,
							 parent_device) < 0);
		assert(errno == EOPNOTSUPP);
		assert(fclose(stream) == 0);
	}
}

/*
 * Deliberately UNSAFE negative control: cloneable PARTUUID and dev_t alone
 * do not prove the inode held by the opened descriptor. Keep this mutant
 * visibly permissive so identity regression tests cannot silently degrade
 * to copied strings or a same-number replacement node.
 */
static int unsafe_partuuid_and_device_number_only(
	const struct format_expectation *expected, const struct stat *opened)
{
	return !strcmp(expected->partuuid, "f13428f6-01") &&
	       opened->st_rdev ==
		       makedev(expected->device_major, expected->device_minor);
}

static void test_unsafe_identity_negative_control(void)
{
	struct format_expectation expected = expectation("8:1", "8:0");
	struct stat path_info = block_stat(8U, 1U);
	struct stat opened_info = path_info;
	struct stat alias_info = path_info;

	path_info.st_dev = makedev(0U, 7U);
	path_info.st_ino = 17U;
	opened_info.st_dev = path_info.st_dev;
	opened_info.st_ino = 19U; /* Same dev_t, substituted inode. */
	alias_info.st_dev = path_info.st_dev;
	alias_info.st_ino = path_info.st_ino;

	assert(unsafe_partuuid_and_device_number_only(&expected, &opened_info));
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 0U)));

	/* A matching opened inode cannot rehabilitate a changed parent. */
	opened_info = path_info;
	assert(unsafe_partuuid_and_device_number_only(&expected, &opened_info));
	assert(!format_identity_values_match(
		&expected, &path_info, &opened_info, &alias_info,
		expected.device_bytes, makedev(8U, 16U)));
}

int main(void)
{
	test_partuuid_canonicalization_rejects_weak_structures();
	test_copied_identifiers_cannot_replace_opened_device();
	test_replaced_alias_and_parent_are_rejected();
	test_reconnection_requires_fresh_exact_device_identity();
	test_geometry_holders_and_active_inventory_fail_closed();
	test_swap_inventory_never_trusts_local_path_identity();
	test_same_device_number_is_not_inode_authority();
	test_transport_path_must_still_be_usb();
	test_unsafe_identity_negative_control();
	puts("PASS: removable-media identity rejects substitution and topology drift");
	return 0;
}
