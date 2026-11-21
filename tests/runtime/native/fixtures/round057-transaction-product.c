// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round057 Agent5: EXACT linked production authority.c/codec.c and
 * flush-qual.h, plus the real default-disabled import admission header.
 *
 * The lower completion and flush callbacks here are HOST MODELS. They never
 * represent actual DM BIO ownership, NAND durability, zswap source provenance,
 * original BIO ACK, GC reader pins or physical SWAPSPACE2 permission.
 * The ordered owner alone mutates these fixed, volatile test arrays.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "authority.h"
#include "flush-qual.h"
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-admission.h"

_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "original RAW page geometry changed");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "protected header changed");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "bounded imported size changed");
_Static_assert(sizeof(struct swapz_map) == 20U, "production map ABI changed");

enum {
	LOGICAL_PAGE_COUNT = 64,
	PHYSICAL_BLOCK_COUNT = 2048,
	IMPORTED_DESCRIPTOR_LIMIT = 8,
	IMPORTED_STAGING_LIMIT = 2,
};

static struct swapz_authority current_authority;
static struct swapz_map volatile_maps[LOGICAL_PAGE_COUNT];
static swapz_u16 volatile_live_records[PHYSICAL_BLOCK_COUNT];
static swapz_u8 volatile_extent_classes[PHYSICAL_BLOCK_COUNT];
static swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
static const char *current_case;
static unsigned int modeled_flush_calls;
static int modeled_flush_result;

#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FIRST_ERROR %s\n", current_case); \
		return 1; \
	} \
} while (0)

static int initialize_authority(void)
{
	memset(&current_authority, 0, sizeof(current_authority));
	memset(volatile_maps, 0, sizeof(volatile_maps));
	memset(volatile_live_records, 0, sizeof(volatile_live_records));
	memset(volatile_extent_classes, 0, sizeof(volatile_extent_classes));
	modeled_flush_calls = 0U;
	modeled_flush_result = 0;
	for (size_t index = 0; index < sizeof(original_page); ++index)
		original_page[index] = (swapz_u8)((index * 29U + 17U) & 255U);
	return swapz_authority_init(&current_authority, volatile_maps,
		volatile_live_records, volatile_extent_classes,
		LOGICAL_PAGE_COUNT, PHYSICAL_BLOCK_COUNT);
}

static int modeled_lower_cache_flush(void *opaque)
{
	(void)opaque;
	++modeled_flush_calls;
	return modeled_flush_result;
}

static int test_live_import_refusal(void)
{
	struct swapz_zswap_admission_transaction imported = { 0 };

	CHECK(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
	CHECK(SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE == 0U);
	CHECK(swapz_zswap_admission_try_live(&imported) == -EOPNOTSUPP);
	CHECK(imported.phase == SWAPZ_ZSWAP_ADMISSION_EMPTY);
	return 0;
}

static int test_flush_failure(void)
{
	const swapz_u32 logical_page = 5U;
	struct swapz_tx transaction;
	int error;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	CHECK(!volatile_maps[logical_page].valid);
	modeled_flush_result = -EIO;
	error = swapz_write_flush_before_publish(0, 1,
						  modeled_lower_cache_flush, NULL);
	CHECK(error == -EIO && modeled_flush_calls == 1U);
	CHECK(swapz_finish_raw(&current_authority, &transaction, original_page,
			       0U, error) == -EIO);
	CHECK(!current_authority.in_flight && !volatile_maps[logical_page].valid);
	CHECK(current_authority.committed_blocks == 0U);
	return 0;
}

static int test_failed_write_skips_flush(void)
{
	const swapz_u32 logical_page = 7U;
	struct swapz_tx transaction;
	int error;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	error = swapz_write_flush_before_publish(-ENOSPC, 1,
						  modeled_lower_cache_flush, NULL);
	CHECK(error == -ENOSPC && modeled_flush_calls == 0U);
	CHECK(swapz_finish_raw(&current_authority, &transaction, original_page,
			       0U, error) == -ENOSPC);
	CHECK(!current_authority.in_flight && !volatile_maps[logical_page].valid);
	return 0;
}

static int test_short_lower_write(void)
{
	const swapz_u32 logical_page = 11U;
	struct swapz_tx transaction;
	int error;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	error = swapz_write_flush_before_publish(0, 1,
						  modeled_lower_cache_flush, NULL);
	CHECK(error == 0 && modeled_flush_calls == 1U);
	CHECK(swapz_finish_raw(&current_authority, &transaction, original_page,
			       0U, error) == -EIO);
	CHECK(!current_authority.in_flight && !volatile_maps[logical_page].valid);
	return 0;
}

static int test_raw_crc_and_exact_page(void)
{
	const swapz_u32 logical_page = 17U;
	struct swapz_tx transaction;
	swapz_u8 original_byte;
	int error;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	error = swapz_write_flush_before_publish(0, 1,
						  modeled_lower_cache_flush, NULL);
	CHECK(error == 0 && modeled_flush_calls == 1U);
	CHECK(swapz_finish_raw(&current_authority, &transaction, original_page,
			       1U, error) == 0);
	CHECK(!current_authority.in_flight && current_authority.committed_blocks == 1U);
	CHECK(volatile_maps[logical_page].valid && volatile_maps[logical_page].raw);
	CHECK(volatile_maps[logical_page].payload_length == SWAPZ_BLOCK_BYTES);
	CHECK(volatile_maps[logical_page].extent_blocks == 1U);
	CHECK(swapz_verify_raw(&current_authority, logical_page, original_page) == 0);
	original_byte = original_page[SWAPZ_BLOCK_BYTES - 1U];
	original_page[SWAPZ_BLOCK_BYTES - 1U] ^= 1U;
	CHECK(swapz_verify_raw(&current_authority, logical_page, original_page) ==
	      -EBADMSG);
	original_page[SWAPZ_BLOCK_BYTES - 1U] = original_byte;
	CHECK(swapz_verify_raw(&current_authority, logical_page, original_page) == 0);
	return 0;
}

static int test_relocation_replaces_one_raw_authority(void)
{
	const swapz_u32 logical_page = 23U;
	struct swapz_tx first, relocation;
	struct swapz_map prior;
	int error;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U, &first) == 0);
	CHECK(swapz_finish_raw(&current_authority, &first, original_page, 1U, 0) == 0);
	prior = volatile_maps[logical_page];
	CHECK(prior.valid && prior.raw && prior.generation == 1U);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &relocation) == 0);
	CHECK(volatile_maps[logical_page].start_block == prior.start_block);
	error = swapz_write_flush_before_publish(0, 1,
						  modeled_lower_cache_flush, NULL);
	CHECK(error == 0);
	CHECK(swapz_finish_raw(&current_authority, &relocation, original_page,
			       1U, error) == 0);
	CHECK(volatile_maps[logical_page].valid && volatile_maps[logical_page].raw);
	CHECK(volatile_maps[logical_page].generation == prior.generation + 1U);
	CHECK(volatile_maps[logical_page].start_block != prior.start_block);
	CHECK(volatile_maps[logical_page].payload_length == SWAPZ_BLOCK_BYTES);
	CHECK(swapz_verify_raw(&current_authority, logical_page, original_page) == 0);
	return 0;
}

static int test_no_flush_is_not_import_durability(void)
{
	const swapz_u32 logical_page = 29U;
	struct swapz_tx transaction;
	int modeled_write_completion;

	CHECK(initialize_authority() == 0);
	CHECK(swapz_stage(&current_authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	modeled_write_completion = swapz_write_flush_before_publish(
		0, 0, modeled_lower_cache_flush, NULL);
	CHECK(modeled_write_completion == 0 && modeled_flush_calls == 0U);
	/* A successful non-FUA host callback proves no stable-media fence.
	 * Do not publish or acknowledge an imported representation. */
	CHECK(swapz_abort(&current_authority, &transaction) == 0);
	CHECK(!volatile_maps[logical_page].valid && !current_authority.in_flight);
	return 0;
}

struct case_entry {
	const char *name;
	int (*run)(void);
};

int main(int argc, char **argv)
{
	static const struct case_entry cases[] = {
		{ "live_import_refusal", test_live_import_refusal },
		{ "flush_failure", test_flush_failure },
		{ "failed_write_skips_flush", test_failed_write_skips_flush },
		{ "short_lower_write", test_short_lower_write },
		{ "raw_crc_and_exact_page", test_raw_crc_and_exact_page },
		{ "relocation_replaces_one_raw_authority",
		  test_relocation_replaces_one_raw_authority },
		{ "no_flush_is_not_import_durability",
		  test_no_flush_is_not_import_durability },
	};
	size_t executed = 0U;

	if (argc > 2) {
		fprintf(stderr, "FIRST_ERROR invalid_case_arguments\n");
		return 2;
	}
	for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		if (argc == 2 && strcmp(cases[index].name, argv[1]))
			continue;
		current_case = cases[index].name;
		if (cases[index].run())
			return 1;
		++executed;
	}
	if (!executed) {
		fprintf(stderr, "FIRST_ERROR unknown_case\n");
		return 2;
	}
	if (argc == 1)
		printf("PASS product_raw_authority=%zu map_bytes=%zu "
		       "import_record_bytes=%zu descriptor_limit=%u staging_limit=%u "
		       "NOT_AUTH=1 PHASE_A=BLOCKED\n",
		       executed, sizeof(struct swapz_map),
		       sizeof(struct swapz_zswap_import_record),
		       (unsigned int)IMPORTED_DESCRIPTOR_LIMIT,
		       (unsigned int)IMPORTED_STAGING_LIMIT);
	return 0;
}
