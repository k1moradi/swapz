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

static void test_swapfile_backing_identity_conflicts(void)
{
	const dev_t device = makedev(8U, 1U);
	const dev_t parent = makedev(8U, 0U);
	struct stat swap_entry = { .st_mode = S_IFREG, .st_dev = device };

	assert(format_swap_entry_conflicts(&swap_entry, device, parent));
	swap_entry.st_dev = parent;
	assert(format_swap_entry_conflicts(&swap_entry, device, parent));
	swap_entry.st_dev = makedev(259U, 1U);
	assert(!format_swap_entry_conflicts(&swap_entry, device, parent));

	/* File identity is st_dev; an incidental rdev must not misclassify it. */
	swap_entry.st_dev = makedev(259U, 1U);
	swap_entry.st_rdev = device;
	assert(!format_swap_entry_conflicts(&swap_entry, device, parent));
	swap_entry.st_dev = device;
	swap_entry.st_rdev = makedev(259U, 2U);
	assert(format_swap_entry_conflicts(&swap_entry, device, parent));

	swap_entry.st_mode = S_IFBLK;
	swap_entry.st_dev = device;
	swap_entry.st_rdev = device;
	assert(format_swap_entry_conflicts(&swap_entry, device, parent));
	swap_entry.st_rdev = makedev(8U, 2U);
	assert(!format_swap_entry_conflicts(&swap_entry, device, parent));
	/* Block swap identity is rdev; a matching containing filesystem is not. */
	swap_entry.st_dev = parent;
	assert(!format_swap_entry_conflicts(&swap_entry, device, parent));

	swap_entry.st_mode = S_IFDIR;
	assert(format_swap_entry_conflicts(&swap_entry, device, parent));
	assert(format_swap_entry_conflicts(NULL, device, parent));
}

int main(void)
{
	test_partuuid_canonicalization_rejects_weak_structures();
	test_copied_identifiers_cannot_replace_opened_device();
	test_replaced_alias_and_parent_are_rejected();
	test_reconnection_requires_fresh_exact_device_identity();
	test_geometry_holders_and_active_inventory_fail_closed();
	test_swapfile_backing_identity_conflicts();
	test_same_device_number_is_not_inode_authority();
	test_transport_path_must_still_be_usb();
	puts("PASS: removable-media identity rejects substitution and topology drift");
	return 0;
}
