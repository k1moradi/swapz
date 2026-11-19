/*
 * Round041 ORIGINAL kernel page_io.c pure C source extraction. Nothing here
 * runs an active swap area, DM target, lower I/O or natural zswap eviction.
 * Negative fixtures intentionally forge target identity and lease booleans.
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

/* ROUND041_EXACT_ORIGINAL_SECTOR_DOMAIN_C */

static struct swapz_round041_sector_domain_evidence original_source_fixture(void)
{
	static const unsigned char original_area;
	static const unsigned char original_bdev;
	static const unsigned char pretend_dm_target;
	struct swapz_round041_sector_domain_evidence evidence = {
		.source_swap_entry = UINT64_C(0x100000025),
		.candidate_swap_entry = UINT64_C(0x100000025),
		.source_slot_offset = 37U,
		.candidate_slot_offset = 37U,
		.source_slot_epoch = 17U,
		.candidate_slot_epoch = 17U,
		.source_area_generation = 3U,
		.candidate_area_generation = 3U,
		.source_area_identity = &original_area,
		.candidate_area_identity = &original_area,
		.source_bdev_identity = &original_bdev,
		.candidate_source_bdev_identity = &original_bdev,
		.original_backing_sector = 4096U,
		.original_bio_sector = 4096U,
		.candidate_original_backing_sector = 4096U,
		.dm_target_begin = 128U,
		.dm_target_length = 512U,
		.claimed_dm_relative_sector = 296U,
		.current_dm_target_identity = &pretend_dm_target,
		.claimed_dm_target_identity = &pretend_dm_target,
		.current_dm_map_generation = 4U,
		.claimed_dm_map_generation = 4U,
		.current_dm_gc_generation = 5U,
		.claimed_dm_gc_generation = 5U,
		.original_upper_bio_bytes = 4096U,
		.original_upper_bvec_bytes = 4096U,
		.original_upper_req_swap_write = true,
		.genuine_source_bio_owner = true,
		.area_ref_released_before_submit = true,
		.current_allocation_incarnation_ref_held = true,
		.current_dm_target_ref_held = true,
		.current_dm_gc_ref_held = true,
	};
	return evidence;
}

int main(void)
{
	struct swapz_round041_sector_domain_evidence source = original_source_fixture();
	struct swapz_round041_sector_domain_evidence candidate = source;
	struct swapz_round041_sector_domain_evidence unchanged = source;
	static const unsigned char other_bdev;
	static const unsigned char other_target;
	static const unsigned char other_area;
#define CHECK(expected) \
	assert(swapz_round041_sector_domain_refuse(&candidate) == (expected))
	assert(source.original_backing_sector != source.source_slot_offset * 8U);
	assert(source.original_backing_sector != source.claimed_dm_relative_sector);
	assert(source.original_upper_bi_vcnt == 0U);
	CHECK(-EOPNOTSUPP);

	candidate.original_bio_sector = source.source_slot_offset * 8U;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_original_backing_sector = 296U;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_source_bdev_identity = &other_bdev;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_area_identity = &other_area;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_swap_entry++;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_slot_epoch++;
	CHECK(-ESTALE);
	candidate = source;
	candidate.candidate_area_generation++;
	CHECK(-ESTALE);
	candidate = source;
	candidate.area_ref_released_before_submit = false;
	CHECK(-ESTALE);
	candidate = source;
	candidate.original_upper_bi_vcnt = 1U;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.original_upper_bvec_bytes = 2048U;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.original_upper_req_swap_write = false;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.current_dm_target_identity = NULL;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.claimed_dm_target_identity = &other_target;
	CHECK(-ESTALE);
	candidate = source;
	candidate.dm_target_length = 7U;
	CHECK(-ERANGE);
	candidate = source;
	candidate.dm_target_begin = UINT64_MAX - 3U;
	CHECK(-ERANGE);
	candidate = source;
	candidate.claimed_dm_relative_sector = UINT64_MAX - 7U;
	CHECK(-ERANGE);
	candidate = source;
	candidate.claimed_dm_relative_sector = 4096U;
	candidate.dm_target_begin = 4000U;
	candidate.dm_target_length = 512U;
	CHECK(-EOPNOTSUPP); /* Numerically identical original/DM is NO AUTHORITY. */
	candidate = source;
	candidate.claimed_dm_map_generation++;
	CHECK(-ESTALE);
	candidate = source;
	candidate.claimed_dm_gc_generation++;
	CHECK(-ESTALE);
	candidate = source;
	candidate.target_tearing_down = true;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.current_allocation_incarnation_ref_held = false;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.current_dm_target_ref_held = false;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.current_dm_gc_ref_held = false;
	CHECK(-EOPNOTSUPP);
	candidate = source;
	candidate.source_slot_offset = UINT64_MAX;
	candidate.candidate_slot_offset = UINT64_MAX;
	CHECK(-ERANGE);
	candidate = source;
	candidate.original_backing_sector = UINT64_MAX - 7U;
	candidate.original_bio_sector = UINT64_MAX - 7U;
	candidate.candidate_original_backing_sector = UINT64_MAX - 7U;
	CHECK(-ERANGE);
	candidate = source;
	candidate.dm_target_begin = 256U;
	candidate.dm_target_length = 8U;
	candidate.claimed_dm_relative_sector = 256U;
	CHECK(-EOPNOTSUPP);
	assert(memcmp(&source, &unchanged, sizeof(source)) == 0);
	assert(swapz_round041_sector_domain_refuse(NULL) == -EINVAL);
	puts("ROUND031_REAL_ROUND041_ORIGINAL_SECTOR_DOMAIN_EXTRACTED_C_HOST_PASS");
	return 0;
}
