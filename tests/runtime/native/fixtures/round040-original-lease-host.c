/*
 * Round040 hosted original-source-only ASan/UBSan negative runtime.
 * The exact original mm/page_io.c pure helper C is injected between
 * markers; it is NEVER a surrogate for active Linux swapoff, swapcache,
 * original pressure eviction, or a current downstream DM target GC ref.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

typedef uint64_t u64;
typedef uint32_t u32;

/* ROUND040_EXACT_ORIGINAL_ASYNC_LEASE_C */

static struct swapz_round040_async_lease_evidence original_source_fixture(void)
{
	static const unsigned char opaque_bdev_identity;
	struct swapz_round040_async_lease_evidence evidence = {
		.source_swap_entry = UINT64_C(0x100000025),
		.candidate_swap_entry = UINT64_C(0x100000025),
		.source_slot_epoch = 17U,
		.candidate_slot_epoch = 17U,
		.original_area_generation = 3U,
		.candidate_area_generation = 3U,
		.original_bdev = &opaque_bdev_identity,
		.candidate_bdev = &opaque_bdev_identity,
		.original_sector = 4096U,
		.candidate_sector = 4096U,
		.original_bio_bytes = 4096U,
		.candidate_bio_bytes = 4096U,
		.area_ref_was_scoped = true,
		.area_ref_released_before_submit = true,
		.source_bio_live = true,
		.original_owner_live = true,
		.folio_unlocked_for_writeback = true,
		.async_endio_pending = true,
	};
	return evidence;
}

int main(void)
{
	struct swapz_round040_async_lease_evidence source = original_source_fixture();
	struct swapz_round040_async_lease_evidence consumer = source;
	struct swapz_round040_async_lease_evidence unchanged = source;
	static const unsigned char unrelated_bdev_identity;
#define CHECK(expected) \
	assert(swapz_round040_async_lease_refuse(&consumer) == (expected))
	CHECK(-EOPNOTSUPP);
	consumer.area_ref_released_before_submit = false;
	CHECK(-ESTALE);
	consumer = source;
	consumer.source_bio_live = false;
	CHECK(-ESTALE);
	consumer = source;
	consumer.candidate_slot_epoch++;
	CHECK(-ESTALE);
	consumer = source;
	consumer.candidate_swap_entry++;
	CHECK(-ESTALE);
	consumer = source;
	consumer.candidate_area_generation++;
	CHECK(-ESTALE);
	consumer = source;
	consumer.candidate_bdev = &unrelated_bdev_identity;
	CHECK(-ESTALE);
	consumer = source;
	consumer.candidate_sector = 296U;
	CHECK(-ERANGE);
	consumer = source;
	consumer.candidate_bio_bytes = 2048U;
	CHECK(-EOPNOTSUPP);
	consumer = source;
	consumer.bio_cloned = true;
	CHECK(-EOPNOTSUPP);
	consumer = source;
	consumer.bio_split = true;
	CHECK(-EOPNOTSUPP);
	consumer = source;
	consumer.original_owner_live = false;
	CHECK(-ESTALE);
	consumer = source;
	consumer.async_endio_pending = false;
	CHECK(-EOPNOTSUPP);
	consumer = source;
	consumer.canceled_or_teardown = true;
	CHECK(-EOPNOTSUPP);
	consumer = source;
	consumer.source_allocation_lease_held = true;
	consumer.current_dm_gc_lease_held = true;
	consumer.expected_dm_map_generation = 33U;
	consumer.expected_dm_gc_generation = 34U;
	CHECK(-EOPNOTSUPP);
	assert(memcmp(&source, &unchanged, sizeof(source)) == 0);
	assert(swapz_round040_async_lease_refuse(NULL) == -EINVAL);
	puts("ROUND031_REAL_ROUND040_ORIGINAL_ASYNC_LEASE_EXTRACTED_C_HOST_PASS");
	return 0;
}
