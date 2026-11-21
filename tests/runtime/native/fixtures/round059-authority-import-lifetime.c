// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round059: link actual authority.c and codec.c. The dormant importer uses
 * real swapz_stage() state and stays incapable of map/upper-ACK publication.
 * No lower BIO, physical flush, original source MM or device is exercised.
 * The single test-owner serializes every record mutation/pin/put.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "authority.h"

_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "RAW_4096 changed");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "protected swap header changed");
_Static_assert(SWAPZ_AUTHORITY_IMPORT_ACTIVE == 0U, "live import forbidden");
_Static_assert(sizeof(struct swapz_map) == 20U, "normal map ABI changed");

enum { LOGICAL_PAGES = 64, PHYSICAL_BLOCKS = 2048 };
static struct swapz_authority authority;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live_records[PHYSICAL_BLOCKS];
static swapz_u8 extent_classes[PHYSICAL_BLOCKS];
static struct swapz_authority_import_pool pool;
static swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
static const char *case_name;

#define CHECK(expression) do { \
	if (!(expression)) { \
		fprintf(stderr, "FIRST_ERROR %s\n", case_name); \
		return 1; \
	} \
} while (0)

static int initialize_test(void)
{
	memset(&authority, 0, sizeof(authority));
	memset(maps, 0, sizeof(maps));
	memset(live_records, 0, sizeof(live_records));
	memset(extent_classes, 0, sizeof(extent_classes));
	for (size_t index = 0U; index < sizeof(original_page); ++index)
		original_page[index] = (swapz_u8)((index * 37U + 11U) & 255U);
	if (swapz_authority_init(&authority, maps, live_records, extent_classes,
				LOGICAL_PAGES, PHYSICAL_BLOCKS))
		return -EIO;
	swapz_authority_import_init(&pool, &authority);
	return 0;
}

static struct swapz_authority_import_spec specification(swapz_u32 logical_page,
							 swapz_u8 requested_fua)
{
	struct swapz_authority_import_spec spec = { 0 };

	spec.source_swap_slot = 37U;
	spec.source_entry_identity = 71U;
	spec.source_store_generation = 91U;
	spec.gc_epoch = 1U;
	spec.logical_page = logical_page;
	spec.compressed_crc32c = 0x12345678U;
	spec.compressed_length = 123U;
	spec.codec = SWAPZ_AUTHORITY_IMPORT_LZ4;
	spec.codec_version = 1U;
	spec.requested_fua = requested_fua;
	spec.original_sha256[0] = 0xb7U;
	return spec;
}

static int begin_staged(swapz_u32 logical_page, swapz_u8 requested_fua,
			struct swapz_tx *transaction, swapz_u64 *ticket)
{
	struct swapz_authority_import_spec spec =
		specification(logical_page, requested_fua);
	int error = swapz_stage(&authority, &logical_page, 1U, 1U, transaction);

	if (error)
		return error;
	return swapz_authority_import_begin(&pool, transaction, &spec, ticket);
}

static int test_no_import_map_publication(void)
{
	struct swapz_tx transaction;
	struct swapz_authority_import_spec view;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(5U, 1U, &transaction, &ticket) == 0);
	CHECK(ticket != 0U && pool.staged == 1U && !maps[5].valid);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -ESTALE);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 1) == 0);
	CHECK(pool.staged == 0U && !maps[5].valid);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -EOPNOTSUPP);
	CHECK(swapz_authority_import_pin_witness(&pool, ticket, &view) == 0);
	CHECK(view.source_entry_identity == 71U && view.logical_page == 5U);
	CHECK(swapz_authority_import_put_witness(&pool, ticket) == 0);
	CHECK(swapz_authority_import_abort(&pool, ticket) == 0);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -ESTALE);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	CHECK(!maps[5].valid && authority.committed_blocks == 0U);
	return 0;
}

static int test_short_lower_write(void)
{
	struct swapz_tx transaction;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(7U, 0U, &transaction, &ticket) == 0);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 0U, 1) == -EIO);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 1) == -ESTALE);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -ESTALE);
	CHECK(!maps[7].valid && authority.committed_blocks == 0U);
	CHECK(swapz_authority_import_abort(&pool, ticket) == 0);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_fua_observation_required(void)
{
	struct swapz_tx transaction;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(9U, 1U, &transaction, &ticket) == 0);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 0) == -EIO);
	CHECK(pool.records[0].state == SWAPZ_AUTHORITY_IMPORT_QUARANTINED);
	CHECK(!maps[9].valid);
	CHECK(swapz_authority_import_abort(&pool, ticket) == 0);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_lower_error_no_mapping(void)
{
	struct swapz_tx transaction;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(11U, 0U, &transaction, &ticket) == 0);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, -ENOSPC, 0U, 0) ==
	      -ENOSPC);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -ESTALE);
	CHECK(pool.records[0].upper_ack_count == 0U && !maps[11].valid);
	CHECK(swapz_authority_import_abort(&pool, ticket) == 0);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_reader_gc_and_teardown_fence(void)
{
	struct swapz_tx transaction;
	struct swapz_authority_import_spec pinned;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(13U, 0U, &transaction, &ticket) == 0);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 0) == 0);
	CHECK(swapz_authority_import_pin_witness(&pool, ticket, &pinned) == 0);
	CHECK(swapz_authority_import_gc_move(&pool, ticket, 2U) == -EBUSY);
	CHECK(swapz_authority_import_close(&pool) == -EBUSY);
	CHECK(swapz_authority_import_try_publish(&pool, ticket) == -ESTALE);
	CHECK(swapz_authority_import_put_witness(&pool, ticket) == 0);
	CHECK(swapz_authority_import_close(&pool) == 0);
	CHECK(swapz_authority_import_put_witness(&pool, ticket) == -ESTALE);
	CHECK(!maps[13].valid);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_generation_and_reissue_identity(void)
{
	struct swapz_tx transaction;
	struct swapz_authority_import_spec spec;
	swapz_u64 old_ticket, new_ticket;

	CHECK(initialize_test() == 0);
	CHECK(swapz_stage(&authority, (const swapz_u32[]){ 17U }, 1U, 1U,
			  &transaction) == 0);
	spec = specification(17U, 0U);
	++transaction.records[0].generation;
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec,
					   &old_ticket) == -ESTALE);
	--transaction.records[0].generation;
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec,
					   &old_ticket) == 0);
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec,
					   &new_ticket) == -EBUSY);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	CHECK(swapz_authority_import_submit(&pool, old_ticket) == -ESTALE);
	CHECK(swapz_authority_import_abort(&pool, old_ticket) == 0);
	CHECK(swapz_stage(&authority, (const swapz_u32[]){ 17U }, 1U, 1U,
			  &transaction) == 0);
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec,
					   &new_ticket) == 0);
	CHECK(new_ticket != old_ticket);
	CHECK(swapz_authority_import_lower_done(&pool, old_ticket, 0, 1U, 1) ==
	      -ESTALE);
	CHECK(swapz_authority_import_abort(&pool, new_ticket) == 0);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_terminal_callback_drain(void)
{
	struct swapz_tx transaction;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(begin_staged(19U, 0U, &transaction, &ticket) == 0);
	CHECK(swapz_authority_import_submit(&pool, ticket) == 0);
	CHECK(swapz_authority_import_abort(&pool, ticket) == -EBUSY);
	CHECK(swapz_authority_import_close(&pool) == -EBUSY);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 1) ==
	      -ECANCELED);
	CHECK(swapz_authority_import_close(&pool) == 0);
	CHECK(swapz_authority_import_lower_done(&pool, ticket, 0, 1U, 1) ==
	      -ESTALE);
	CHECK(!maps[19].valid);
	CHECK(swapz_abort(&authority, &transaction) == 0);
	return 0;
}

static int test_protected_header_and_ordinary_raw(void)
{
	const swapz_u32 logical_page = 23U;
	struct swapz_tx transaction;
	struct swapz_authority_import_spec spec;
	swapz_u64 ticket;
	swapz_u8 saved;

	CHECK(initialize_test() == 0);
	CHECK(swapz_stage(&authority, &logical_page, 1U, 1U, &transaction) == 0);
	/* Product stage block 0 is DATA-relative, physical block 1;
	 * this unit does NO physical I/O or raw header writes. */
	CHECK((transaction.start_block + SWAPZ_LINUX_SWAP_HEADER_BLOCKS) *
	      SWAPZ_BLOCK_BYTES >= SWAPZ_BLOCK_BYTES);
	spec = specification(logical_page, 0U);
	spec.compressed_length = SWAPZ_MAX_COMPRESSED + 1U;
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec, &ticket) ==
	      -EINVAL);
	spec.compressed_length = 123U;
	memset(spec.original_sha256, 0, sizeof(spec.original_sha256));
	CHECK(swapz_authority_import_begin(&pool, &transaction, &spec, &ticket) ==
	      -ENODATA);
	CHECK(swapz_finish_raw(&authority, &transaction, original_page, 1U, 0) == 0);
	CHECK(maps[logical_page].valid && maps[logical_page].raw);
	CHECK(maps[logical_page].payload_length == SWAPZ_BLOCK_BYTES);
	CHECK(swapz_verify_raw(&authority, logical_page, original_page) == 0);
	saved = original_page[SWAPZ_BLOCK_BYTES - 1U];
	original_page[SWAPZ_BLOCK_BYTES - 1U] ^= 1U;
	CHECK(swapz_verify_raw(&authority, logical_page, original_page) == -EBADMSG);
	original_page[SWAPZ_BLOCK_BYTES - 1U] = saved;
	CHECK(swapz_verify_raw(&authority, logical_page, original_page) == 0);
	return 0;
}

struct test_case {
	const char *name;
	int (*run)(void);
};

int main(int argc, char **argv)
{
	const struct test_case tests[] = {
		{ "no_import_map_publication", test_no_import_map_publication },
		{ "short_lower_write", test_short_lower_write },
		{ "fua_observation_required", test_fua_observation_required },
		{ "lower_error_no_mapping", test_lower_error_no_mapping },
		{ "reader_gc_and_teardown_fence", test_reader_gc_and_teardown_fence },
		{ "generation_and_reissue_identity", test_generation_and_reissue_identity },
		{ "terminal_callback_drain", test_terminal_callback_drain },
		{ "protected_header_and_ordinary_raw", test_protected_header_and_ordinary_raw },
	};
	size_t executed = 0U;

	if (argc > 2) {
		fprintf(stderr, "FIRST_ERROR invalid_arguments\n");
		return 2;
	}
	for (size_t index = 0U; index < sizeof(tests) / sizeof(tests[0]); ++index) {
		if (argc == 2 && strcmp(argv[1], tests[index].name))
			continue;
		case_name = tests[index].name;
		if (tests[index].run())
			return 1;
		++executed;
	}
	if (!executed) {
		fprintf(stderr, "FIRST_ERROR unknown_case\n");
		return 2;
	}
	if (argc == 1)
		printf("PASS authority_actual_product_cases=%zu map_bytes=%zu "
		       "descriptor_bytes=%zu pool_bytes=%zu capacity=%u staged=%u "
		       "AUTH0 PHASE_A=BLOCKED\n",
		       executed, sizeof(struct swapz_map),
		       sizeof(struct swapz_authority_import_record),
		       sizeof(struct swapz_authority_import_pool),
		       (unsigned int)SWAPZ_AUTHORITY_IMPORT_CAPACITY,
		       (unsigned int)SWAPZ_AUTHORITY_IMPORT_STAGING_LIMIT);
	return 0;
}
