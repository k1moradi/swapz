/*
 * Round045 REAL original mm/page_io.c pure-C source extraction harness.
 * No fake C implementation of the kernel refusal function is permitted:
 * the source test must substitute the exact generated original C helper.
 * No live kernel, real zswap pressure, DM or physical disk authority.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>

typedef uint64_t u64;
typedef uint32_t u32;

/* ROUND045_EXACT_ORIGINAL_SOURCE_C */

static struct swapz_round045_stored_bio_scope_evidence original_source_fixture(void)
{
	static const unsigned char original_area;
	static const unsigned char original_bdev;
	struct swapz_round045_stored_bio_scope_evidence evidence = {
		.original_typed_slot = UINT64_C(0x100000025),
		.source_typed_slot = UINT64_C(0x100000025),
		.original_slot_offset = 37U,
		.original_slot_epoch = 17U,
		.current_slot_epoch = 17U,
		.original_area_identity = &original_area,
		.bio_area_identity = &original_area,
		.original_backing_bdev = &original_bdev,
		.bio_backing_bdev = &original_bdev,
		.original_backing_sector = 4096U,
		.original_bio_sector = 4096U,
		.claimed_dm_relative_sector = 4096U,
		.original_bio_bytes = 4096U,
		.original_bvec_bytes = 4096U,
		.original_swap_write = true,
		.original_stored_lz4_owner_checked = true,
		.area_ref_acquired_for_source_observation = true,
		.area_ref_released_before_submit = true,
		.source_entry_erased_and_freed = true,
	};
	return evidence;
}

int main(void)
{
	struct swapz_round045_stored_bio_scope_evidence original =
		original_source_fixture();
	struct swapz_round045_stored_bio_scope_evidence candidate = original;
	static const unsigned char other_bdev;
	static const unsigned char other_area;
#define CHECK(expected) \
	assert(swapz_round045_stored_bio_scope_refuse(&candidate) == (expected))
	assert(original.original_backing_sector != original.original_slot_offset * 8U);
	assert(original.original_backing_sector == original.claimed_dm_relative_sector);
	CHECK(-EOPNOTSUPP);
	candidate.original_slot_epoch++;
	CHECK(-ESTALE);
	candidate = original;
	candidate.source_typed_slot++;
	CHECK(-ESTALE);
	candidate = original;
	candidate.bio_area_identity = &other_area;
	CHECK(-ESTALE);
	candidate = original;
	candidate.bio_backing_bdev = &other_bdev;
	CHECK(-ESTALE);
	candidate = original;
	candidate.original_bio_sector = 296U;
	CHECK(-ESTALE);
	candidate = original;
	candidate.original_backing_sector = 0U;
	CHECK(-ERANGE);
	candidate = original;
	candidate.original_backing_sector = UINT64_MAX;
	CHECK(-ERANGE);
	candidate = original;
	candidate.original_bvec_bytes = 2048U;
	CHECK(-EOPNOTSUPP);
	candidate = original;
	candidate.original_bio_bytes = 2048U;
	CHECK(-EOPNOTSUPP);
	candidate = original;
	candidate.original_bio_vec_count = 1U;
	CHECK(-EOPNOTSUPP);
	candidate = original;
	candidate.original_swap_write = false;
	CHECK(-EOPNOTSUPP);
	candidate = original;
	candidate.original_stored_lz4_owner_checked = false;
	CHECK(-ESTALE);
	candidate = original;
	candidate.area_ref_acquired_for_source_observation = false;
	CHECK(-ESTALE);
	candidate = original;
	candidate.area_ref_released_before_submit = false;
	CHECK(-ESTALE);
	candidate = original;
	candidate.source_entry_erased_and_freed = false;
	CHECK(-ESTALE);
	candidate = original;
	candidate.cloned_split_or_reissued = true;
	CHECK(-EOPNOTSUPP);
	candidate = original;
	candidate.source_slot_incarnation_ref_held_across_async = true;
	candidate.current_dm_table_extent_gc_ref_held = true;
	CHECK(-EOPNOTSUPP); /* Forged positive flags have no real ref. */
	assert(swapz_round045_stored_bio_scope_refuse(NULL) == -EINVAL);
#undef CHECK
	puts("ROUND031_REAL_ROUND045_ORIGINAL_STORED_BIO_SCOPE_HOST_PASS");
	return 0;
}
