// SPDX-License-Identifier: GPL-2.0-only
/*
 * Test-only actual product authority allocator -> distinct native-codec disk
 * record. All lower/FUA receipts are deliberately MODEL INPUTS, never physical
 * writes; no original source BIO, native decoder, production map or upper ACK.
 * One serialized test owner controls staging, pin/put, relocation and close.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "authority.h"

_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "RAW_4096 contract changed");
_Static_assert(SWAPZ_IMPORT_DISK_ACTIVE == 0U, "native import activated");
_Static_assert(SWAPZ_AUTHORITY_IMPORT_ACTIVE == 0U, "native import activated");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "SWAPSPACE2 protection lost");
_Static_assert(sizeof(struct swapz_map) == 20U, "ordinary map ABI changed");

enum { LOGICAL_PAGES = 64, PHYSICAL_BLOCKS = 2048 };
static struct swapz_authority authority;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live_records[PHYSICAL_BLOCKS];
static swapz_u8 extent_classes[PHYSICAL_BLOCKS];
static struct swapz_import_disk_pool disk_pool;
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
	size_t index;

	memset(&authority, 0, sizeof(authority));
	memset(maps, 0, sizeof(maps));
	memset(live_records, 0, sizeof(live_records));
	memset(extent_classes, 0, sizeof(extent_classes));
	for (index = 0; index < sizeof(original_page); ++index)
		original_page[index] = (swapz_u8)((index * 37U + 11U) & 255U);
	if (swapz_authority_init(&authority, maps, live_records,
				 extent_classes, LOGICAL_PAGES, PHYSICAL_BLOCKS))
		return -EIO;
	swapz_import_disk_init(&disk_pool, &authority);
	return 0;
}

static struct swapz_authority_import_spec make_spec(swapz_u32 logical_page,
						    swapz_u64 gc_epoch)
{
	struct swapz_authority_import_spec spec = { 0 };

	spec.source_swap_slot = 33U;
	spec.source_entry_identity = 77U;
	spec.source_store_generation = 109U;
	spec.gc_epoch = gc_epoch;
	spec.logical_page = logical_page;
	spec.compressed_crc32c = 0xdeadbeefU;
	spec.compressed_length = 321U;
	spec.codec = SWAPZ_AUTHORITY_IMPORT_LZO1X;
	spec.codec_version = 1U;
	spec.requested_fua = 1U;
	spec.original_sha256[0] = 0xa5U;
	spec.original_sha256[31] = 0x5aU;
	return spec;
}

static int start_submitted(swapz_u32 logical_page, swapz_u64 gc_epoch,
			   swapz_u64 replaced_ticket,
			   struct swapz_tx *transaction,
			   swapz_u64 *ticket)
{
	const struct swapz_authority_import_spec spec =
		make_spec(logical_page, gc_epoch);
	int error = swapz_import_disk_stage(&disk_pool, &spec, 1U,
					    replaced_ticket, transaction, ticket);

	if (error)
		return error;
	return swapz_import_disk_submit(&disk_pool, *ticket);
}

static int complete_owned(swapz_u32 logical_page, swapz_u64 gc_epoch,
			  swapz_u64 replaced_ticket,
			  struct swapz_tx *transaction, swapz_u64 *ticket)
{
	int error = start_submitted(logical_page, gc_epoch, replaced_ticket,
				    transaction, ticket);

	if (error)
		return error;
	return swapz_import_disk_complete(&disk_pool, *ticket, transaction,
					  0, 1U, 1);
}

static int before_durability_invisible(void)
{
	struct swapz_tx transaction;
	struct swapz_import_disk_view view;
	const struct swapz_authority_import_spec spec = make_spec(3U, 1U);
	swapz_u64 ticket;
	swapz_u32 reserved;

	CHECK(initialize_test() == 0);
	CHECK(swapz_import_disk_stage(&disk_pool, &spec, 2U, 0U,
				      &transaction, &ticket) == 0);
	reserved = transaction.start_block;
	CHECK(!maps[3].valid && !live_records[reserved] &&
	      authority.in_flight == 1);
	CHECK(swapz_import_disk_pin(&disk_pool, ticket, &view) == -ESTALE);
	CHECK(swapz_import_disk_submit(&disk_pool, ticket) == 0);
	CHECK(swapz_import_disk_pin(&disk_pool, ticket, &view) == -ESTALE);
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &transaction,
					  0, 2U, 1) == 0);
	CHECK(authority.in_flight == 0 && authority.committed_blocks == 2U);
	CHECK(!maps[3].valid && maps[3].generation == 0U);
	CHECK(live_records[reserved] == 1U && extent_classes[reserved] == 2U);
	CHECK(swapz_import_disk_pin(&disk_pool, ticket, &view) == 0);
	CHECK(view.ticket == ticket && view.start_block == reserved &&
	      view.extent_blocks == 2U && view.spec.codec ==
		      SWAPZ_AUTHORITY_IMPORT_LZO1X &&
	      view.spec.compressed_crc32c == 0xdeadbeefU);
	CHECK(swapz_import_disk_put(&disk_pool, ticket) == 0);
	CHECK(swapz_import_disk_retire(&disk_pool, ticket) == 0);
	CHECK(live_records[reserved] == 0U && extent_classes[reserved] == 2U);
	CHECK(swapz_import_disk_retire(&disk_pool, ticket) == -ESTALE);
	CHECK(swapz_import_disk_close(&disk_pool) == 0);
	return 0;
}

static int failed_or_short_lower(void)
{
	struct swapz_tx transaction;
	struct swapz_import_disk_view view;
	swapz_u64 ticket;
	swapz_u32 old_start;
	const struct swapz_authority_import_spec invalid =
		make_spec(8U, 1U);
	struct swapz_authority_import_spec missing_fua = invalid;

	CHECK(initialize_test() == 0);
	missing_fua.requested_fua = 0U;
	CHECK(swapz_import_disk_stage(&disk_pool, &missing_fua, 1U, 0U,
				      &transaction, &ticket) == -EINVAL);
	CHECK(authority.in_flight == 0 && authority.next_block == 0U);
	CHECK(start_submitted(8U, 1U, 0U, &transaction, &ticket) == 0);
	old_start = transaction.start_block;
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &transaction,
					  0, 0U, 1) == -EIO);
	CHECK(authority.in_flight == 0 &&
	      authority.abandoned_blocks == 1U && !maps[8].valid);
	CHECK(swapz_import_disk_pin(&disk_pool, ticket, &view) == -ESTALE);
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &transaction,
					  0, 1U, 1) == -ESTALE);
	CHECK(swapz_import_disk_abort(&disk_pool, ticket) == 0);
	CHECK(start_submitted(8U, 1U, 0U, &transaction, &ticket) == 0);
	CHECK(transaction.start_block != old_start);
	old_start = transaction.start_block;
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &transaction,
					  -EIO, 1U, 1) == -EIO);
	CHECK(extent_classes[old_start] == 1U &&
	      live_records[old_start] == 0U && !maps[8].valid);
	CHECK(swapz_import_disk_abort(&disk_pool, ticket) == 0);
	CHECK(start_submitted(8U, 1U, 0U, &transaction, &ticket) == 0);
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &transaction,
					  0, 1U, 0) == -EIO);
	CHECK(swapz_import_disk_abort(&disk_pool, ticket) == 0);
	CHECK(authority.committed_blocks == 0U && !maps[8].valid);
	CHECK(swapz_import_disk_close(&disk_pool) == 0);
	return 0;
}

static int capacity_and_stale_ticket(void)
{
	struct swapz_tx transaction;
	struct swapz_import_disk_view view;
	struct swapz_authority_import_spec spec;
	swapz_u64 tickets[SWAPZ_IMPORT_DISK_CAPACITY];
	swapz_u64 rejected;
	swapz_u8 index;

	CHECK(initialize_test() == 0);
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index) {
		CHECK(complete_owned((swapz_u32)index, 1U, 0U, &transaction,
				     &tickets[index]) == 0);
		CHECK(live_records[transaction.start_block] == 1U);
	}
	spec = make_spec(30U, 1U);
	CHECK(swapz_import_disk_stage(&disk_pool, &spec, 1U, 0U,
				      &transaction, &rejected) == -ENOSPC);
	CHECK(!authority.in_flight && rejected == 0U);
	spec = make_spec(0U, 1U);
	CHECK(swapz_import_disk_stage(&disk_pool, &spec, 1U, 0U,
				      &transaction, &rejected) == -EBUSY);
	CHECK(swapz_import_disk_pin(&disk_pool, tickets[0] + 77U,
				    &view) == -ESTALE);
	CHECK(swapz_import_disk_pin(&disk_pool, tickets[0], &view) == 0);
	CHECK(swapz_import_disk_retire(&disk_pool, tickets[0]) == 0);
	CHECK(swapz_import_disk_pin(&disk_pool, tickets[0], &view) == -ESTALE);
	CHECK(swapz_import_disk_close(&disk_pool) == -EBUSY);
	CHECK(swapz_import_disk_put(&disk_pool, tickets[0]) == 0);
	CHECK(swapz_import_disk_put(&disk_pool, tickets[0]) == -ESTALE);
	CHECK(swapz_import_disk_close(&disk_pool) == 0);
	return 0;
}

static int reader_pinned_relocation(void)
{
	struct swapz_tx old_tx, new_tx;
	struct swapz_import_disk_view view;
	struct swapz_authority_import_spec stale_spec;
	swapz_u64 old_ticket, new_ticket, discarded;
	swapz_u32 old_start, new_start;

	CHECK(initialize_test() == 0);
	CHECK(complete_owned(9U, 1U, 0U, &old_tx, &old_ticket) == 0);
	old_start = old_tx.start_block;
	CHECK(swapz_import_disk_pin(&disk_pool, old_ticket, &view) == 0);
	stale_spec = make_spec(9U, 1U);
	CHECK(swapz_import_disk_stage(&disk_pool, &stale_spec, 1U, old_ticket,
				      &new_tx, &discarded) == -ESTALE);
	stale_spec.gc_epoch = 2U;
	stale_spec.compressed_crc32c++;
	CHECK(swapz_import_disk_stage(&disk_pool, &stale_spec, 1U, old_ticket,
				      &new_tx, &discarded) == -ESTALE);
	CHECK(start_submitted(9U, 2U, old_ticket, &new_tx, &new_ticket) == 0);
	new_start = new_tx.start_block;
	CHECK(old_start != new_start);
	CHECK(live_records[old_start] == 1U &&
	      live_records[new_start] == 0U && !maps[9].valid);
	CHECK(swapz_import_disk_complete(&disk_pool, new_ticket, &new_tx,
					  0, 1U, 1) == 0);
	CHECK(live_records[new_start] == 1U && live_records[old_start] == 1U &&
	      !maps[9].valid);
	CHECK(swapz_import_disk_pin(&disk_pool, old_ticket, &view) == -ESTALE);
	CHECK(swapz_import_disk_pin(&disk_pool, new_ticket, &view) == 0);
	CHECK(swapz_import_disk_put(&disk_pool, new_ticket) == 0);
	CHECK(swapz_import_disk_put(&disk_pool, old_ticket) == 0);
	CHECK(live_records[old_start] == 0U &&
	      extent_classes[old_start] == 1U &&
	      live_records[new_start] == 1U);
	CHECK(swapz_import_disk_retire(&disk_pool, new_ticket) == 0);
	CHECK(live_records[new_start] == 0U);
	CHECK(swapz_import_disk_close(&disk_pool) == 0);
	return 0;
}

static int closing_callback_and_pin(void)
{
	struct swapz_tx tx;
	struct swapz_import_disk_view view;
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(start_submitted(13U, 1U, 0U, &tx, &ticket) == 0);
	CHECK(swapz_import_disk_close(&disk_pool) == -EBUSY);
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &tx,
					  0, 1U, 1) == -ECANCELED);
	CHECK(swapz_import_disk_complete(&disk_pool, ticket, &tx,
					  0, 1U, 1) == -ESTALE);
	CHECK(swapz_import_disk_abort(&disk_pool, ticket) == 0);
	CHECK(swapz_import_disk_pin(&disk_pool, ticket, &view) == -ESTALE);
	CHECK(swapz_import_disk_close(&disk_pool) == 0);
	CHECK(authority.in_flight == 0 && !maps[13].valid);
	return 0;
}

static int ordinary_raw_untouched(void)
{
	struct swapz_tx raw_transaction, import_transaction;
	struct swapz_authority_import_spec spec = make_spec(21U, 1U);
	swapz_u64 ticket;

	CHECK(initialize_test() == 0);
	CHECK(swapz_stage(&authority, &spec.logical_page, 1U, 1U,
			  &raw_transaction) == 0);
	CHECK(swapz_finish_raw(&authority, &raw_transaction, original_page,
			       1U, 0) == 0);
	CHECK(maps[21].raw && maps[21].valid && maps[21].payload_length ==
		      SWAPZ_BLOCK_BYTES &&
	      swapz_verify_raw(&authority, 21U, original_page) == 0);
	CHECK(swapz_import_disk_stage(&disk_pool, &spec, 1U, 0U,
				      &import_transaction, &ticket) == -EINVAL);
	CHECK(maps[21].valid && maps[21].raw &&
	      swapz_import_disk_close(&disk_pool) == 0);
	return 0;
}

struct test_case {
	const char *name;
	int (*run)(void);
};
static const struct test_case cases[] = {
	{ "before_durability_invisible", before_durability_invisible },
	{ "failed_or_short_lower", failed_or_short_lower },
	{ "capacity_and_stale_ticket", capacity_and_stale_ticket },
	{ "reader_pinned_relocation", reader_pinned_relocation },
	{ "closing_callback_and_pin", closing_callback_and_pin },
	{ "ordinary_raw_untouched", ordinary_raw_untouched },
};

int main(int argc, char **argv)
{
	size_t index, passed = 0U;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		int error;

		if (argc == 2 && strcmp(argv[1], cases[index].name))
			continue;
		case_name = cases[index].name;
		error = cases[index].run();
		if (error)
			return error;
		passed++;
	}
	if (!passed)
		return 2;
	if (argc == 1) {
		printf("PASS import_disk_owned_cases=%zu map_bytes=%zu "
		       "pool_bytes=%zu capacity=%u ACTIVE=0 PHASE_A=BLOCKED\n",
		       passed, sizeof(struct swapz_map), sizeof(disk_pool),
		       SWAPZ_IMPORT_DISK_CAPACITY);
	}
	return 0;
}
