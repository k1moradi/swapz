// SPDX-License-Identifier: GPL-2.0-only
/*
 * The exact src/kernel/{codec,authority}.c are compiled into this
 * userspace executable. Covers authority publication and torn-write rollback.
 */
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct swapz_authority authority;
static struct swapz_map maps[128];
static swapz_u16 live[2048];
static swapz_u8 classes[2048];
static swapz_u8 extent_sequence_delta[2048];
static swapz_u32 segment_sequence_base[8];
static swapz_u8 extent[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 previous_extent[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 content[2072];

static int init(void)
{
	int error = swapz_authority_init(&authority, maps, live, classes,
					 64, 2048);

	if (error)
		return error;
	return swapz_enable_extent_sequence_index(
		&authority, extent_sequence_delta, segment_sequence_base, 8);
}

static int encode(const struct swapz_tx *tx)
{
	struct swapz_builder b;
	swapz_u8 index;

	if (swapz_begin(&b, extent,
		      (swapz_u32)tx->extent_blocks * SWAPZ_BLOCK_BYTES,
		      tx->sequence))
		return 1;
	for (index = 0; index < tx->count; ++index) {
		memset(content, (int)(tx->records[index].logical_page + 1U),
		       sizeof(content));
		if (swapz_append(&b, tx->records[index].logical_page,
			       tx->records[index].generation,
			       content, sizeof(content)))
			return 1;
	}
	return swapz_seal(&b) != 0;
}

static swapz_u64 round_up_4k(swapz_u64 bytes)
{
	return (bytes + (SWAPZ_BLOCK_BYTES - 1U)) &
	       ~((swapz_u64)SWAPZ_BLOCK_BYTES - 1U);
}

static swapz_u64 leaf_pte_pages_4k(swapz_u64 bytes)
{
	const swapz_u64 payload_pages =
		round_up_4k(bytes) / SWAPZ_BLOCK_BYTES;

	/* x86_64/arm64 qualification uses 4KiB pages with 512 8-byte PTEs/page.
	 * This is a conservative independent-leaf-table sizing oracle only. */
	return (payload_pages + 511U) / 512U;
}

static int test_initial_rejects_unsafe_capacity(void)
{
	struct swapz_authority_geometry geometry;
	struct swapz_authority a;

	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 512) == -EINVAL);
	CHECK(swapz_authority_init(&a, maps, live, classes, 500, 768) == -ENOSPC);
	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 769) == -EINVAL);
	CHECK(swapz_authority_capacity(768, &geometry) == -ENOSPC);
	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 768) == -ENOSPC);
	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 1024) == 0);
	CHECK(a.reserve_blocks == 512);
	CHECK(a.next_block == 0);
	return 0;
}


/*
 * Exercise every segment transition across the GC minimum -> proportional
 * reserve crossover without copying the capacity formula into the test.
 * The production capacity helper and admission gate must agree at both edges.
 */
static int test_capacity_preflight_segment_sweep(void)
{
	swapz_u32 segment_count;

	for (segment_count = 3U; segment_count <= 2048U; ++segment_count) {
		const swapz_u32 physical_blocks =
			segment_count * SWAPZ_SEGMENT_BLOCKS;
		struct swapz_authority_geometry geometry;
		swapz_u32 reserve = 0x5a5a5a5aU;
		int error;

		memset(&geometry, 0x5a, sizeof(geometry));
		error = swapz_authority_capacity(physical_blocks, &geometry);
		if (segment_count == 3U) {
			CHECK(error == -ENOSPC);
			CHECK(geometry.maximum_logical_pages == 0x5a5a5a5aU);
			continue;
		}
		CHECK(error == 0);
		CHECK(geometry.usable_physical_blocks == physical_blocks);
		CHECK(geometry.gc_reserve_blocks >= 2U * SWAPZ_SEGMENT_BLOCKS);
		CHECK(geometry.required_foreground_headroom_blocks ==
		      SWAPZ_FOREGROUND_HEADROOM_BLOCKS);
		CHECK(geometry.maximum_logical_pages > 0U);
		CHECK(geometry.logical_mapper_bytes ==
		      (swapz_u64)geometry.maximum_logical_pages *
		      SWAPZ_BLOCK_BYTES);
		CHECK(geometry.linux_usable_swap_bytes ==
		      (swapz_u64)(geometry.maximum_logical_pages -
				  SWAPZ_LINUX_SWAP_HEADER_BLOCKS) *
		      SWAPZ_BLOCK_BYTES);
		CHECK(swapz_authority_validate_geometry(
			      geometry.maximum_logical_pages,
			      physical_blocks, &reserve) == 0);
		CHECK(reserve == geometry.gc_reserve_blocks);
		CHECK(((physical_blocks - reserve) / SWAPZ_SEGMENT_BLOCKS) *
			      SWAPZ_SEGMENT_BLOCKS -
			      geometry.maximum_logical_pages >=
		      SWAPZ_FOREGROUND_HEADROOM_BLOCKS);
		reserve = 0x5a5a5a5aU;
		CHECK(swapz_authority_validate_geometry(
			      geometry.maximum_logical_pages + 1U,
			      physical_blocks, &reserve) == -ENOSPC);
		CHECK(reserve == 0x5a5a5a5aU);
	}
	return 0;
}

static int test_selected_card_geometry_and_memory_scaling(void)
{
	const swapz_u64 partition_bytes = 124787884032ULL;
	const swapz_u32 expected_physical_blocks = 30465536U;
	const swapz_u32 expected_logical_pages = 27080192U;
	const swapz_u32 expected_reserve_blocks = 3385024U;
	const swapz_u32 expected_segments = 119006U;
	const swapz_u64 expected_mapper_bytes = 110920466432ULL;
	const swapz_u64 expected_linux_swap_bytes = 110920462336ULL;
	const swapz_u64 expected_index_bytes = 884391736ULL;
	const swapz_u64 expected_page_rounded_bytes = 884436992ULL;
	const swapz_u64 expected_largest_allocation = 541603840ULL;
	const swapz_u32 near_u32_physical = 0xffffff00U;
	const swapz_u32 near_u32_logical = 3817748224U;
	const swapz_u32 near_u32_reserve = 477218528U;
	const swapz_u32 total_blocks =
		(swapz_u32)(partition_bytes / SWAPZ_BLOCK_BYTES);
	const swapz_u32 physical_blocks =
		((total_blocks - 1U) / SWAPZ_SEGMENT_BLOCKS) *
		SWAPZ_SEGMENT_BLOCKS;
	const swapz_u32 segment_count =
		physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	struct swapz_authority_geometry geometry;
	struct swapz_authority_geometry near_u32_geometry;
	swapz_u64 index_bytes, rounded_bytes, leaf_pte_pages;
	swapz_u32 reserve = 0;

	CHECK(partition_bytes % SWAPZ_BLOCK_BYTES == 0);
	CHECK(physical_blocks == expected_physical_blocks);
	CHECK(segment_count == expected_segments);
	CHECK(swapz_authority_capacity(physical_blocks, &geometry) == 0);
	CHECK(geometry.usable_physical_blocks == expected_physical_blocks);
	CHECK(geometry.gc_reserve_blocks == expected_reserve_blocks);
	CHECK(geometry.required_foreground_headroom_blocks ==
	      SWAPZ_SEGMENT_BLOCKS);
	CHECK(geometry.maximum_logical_pages == expected_logical_pages);
	CHECK(geometry.logical_mapper_bytes == expected_mapper_bytes);
	CHECK(geometry.linux_usable_swap_bytes == expected_linux_swap_bytes);
	CHECK(swapz_authority_validate_geometry(expected_logical_pages,
						 physical_blocks,
						 &reserve) == 0);
	CHECK(reserve == expected_reserve_blocks);
	reserve = 0xa5a5a5a5U;
	CHECK(swapz_authority_validate_geometry(expected_logical_pages + 1U,
						 physical_blocks,
						 &reserve) == -ENOSPC);
	CHECK(reserve == 0xa5a5a5a5U);
	CHECK(expected_logical_pages - 1U == 27080191U);
	CHECK((swapz_u64)expected_logical_pages * SWAPZ_BLOCK_BYTES ==
	      expected_mapper_bytes);
	CHECK(((physical_blocks - expected_reserve_blocks) /
	       SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS -
	      expected_logical_pages == SWAPZ_SEGMENT_BLOCKS);

	index_bytes = (swapz_u64)expected_logical_pages *
		(sizeof(struct swapz_map) + 2U * sizeof(swapz_u32)) +
		(swapz_u64)physical_blocks *
		(sizeof(swapz_u16) + 2U * sizeof(swapz_u8)) +
		(swapz_u64)segment_count *
		(8U * sizeof(swapz_u32) + sizeof(swapz_u16) +
		 2U * sizeof(swapz_u8));
	CHECK(index_bytes == expected_index_bytes);
	CHECK((swapz_u64)expected_logical_pages * sizeof(struct swapz_map) ==
	      expected_largest_allocation);

	/* Current x86 host uses 4KiB allocation pages. This is page-rounding
	 * payload overhead only; vmalloc metadata/page tables remain external. */
	rounded_bytes =
		round_up_4k((swapz_u64)expected_logical_pages *
			    sizeof(struct swapz_map)) +
		2U * round_up_4k((swapz_u64)expected_logical_pages *
				 sizeof(swapz_u32)) +
		round_up_4k((swapz_u64)physical_blocks * sizeof(swapz_u16)) +
		2U * round_up_4k((swapz_u64)physical_blocks *
				 sizeof(swapz_u8)) +
		8U * round_up_4k((swapz_u64)segment_count *
				 sizeof(swapz_u32)) +
		round_up_4k((swapz_u64)segment_count * sizeof(swapz_u16)) +
		2U * round_up_4k((swapz_u64)segment_count *
				 sizeof(swapz_u8));
	CHECK(rounded_bytes == expected_page_rounded_bytes);
	CHECK(rounded_bytes - index_bytes == 45256ULL);

	/* Count leaf PTE pages if all 17 current indexes are independently
	 * vmalloc-backed. Actual vmalloc/slab metadata and shared upper page-table
	 * levels remain loaded-host measurements. */
	leaf_pte_pages =
		leaf_pte_pages_4k((swapz_u64)expected_logical_pages *
				   sizeof(struct swapz_map)) +
		2U * leaf_pte_pages_4k((swapz_u64)expected_logical_pages *
					 sizeof(swapz_u32)) +
		leaf_pte_pages_4k((swapz_u64)physical_blocks *
				   sizeof(swapz_u16)) +
		2U * leaf_pte_pages_4k((swapz_u64)physical_blocks *
					 sizeof(swapz_u8)) +
		8U * leaf_pte_pages_4k((swapz_u64)segment_count *
					 sizeof(swapz_u32)) +
		leaf_pte_pages_4k((swapz_u64)segment_count *
				   sizeof(swapz_u16)) +
		2U * leaf_pte_pages_4k((swapz_u64)segment_count *
					 sizeof(swapz_u8));
	CHECK(leaf_pte_pages == 434ULL);
	CHECK(leaf_pte_pages * SWAPZ_BLOCK_BYTES == 1777664ULL);

	/* Exercise the top aligned u32 geometry without allocating it.
	 * On 32-bit systems its physical liveness index is unaddressable even
	 * though widened reserve/headroom arithmetic itself remains valid. */
	if (sizeof(size_t) < sizeof(swapz_u64)) {
		reserve = 0x5a5a5a5aU;
		CHECK(swapz_authority_capacity(near_u32_physical,
					       &near_u32_geometry) == -EOVERFLOW);
		CHECK(swapz_authority_validate_geometry(near_u32_logical,
							 near_u32_physical,
							 &reserve) == -EOVERFLOW);
		CHECK(reserve == 0x5a5a5a5aU);
	} else {
		CHECK(swapz_authority_capacity(near_u32_physical,
					       &near_u32_geometry) == 0);
		CHECK(near_u32_geometry.maximum_logical_pages ==
		      near_u32_logical);
		CHECK(near_u32_geometry.gc_reserve_blocks ==
		      near_u32_reserve);
		CHECK(near_u32_geometry.required_foreground_headroom_blocks ==
		      SWAPZ_SEGMENT_BLOCKS);
		CHECK(swapz_authority_validate_geometry(near_u32_logical,
							 near_u32_physical,
							 &reserve) == 0);
		CHECK(reserve == near_u32_reserve);
	}
	reserve = 0x5a5a5a5aU;
	CHECK(swapz_authority_validate_geometry(near_u32_logical + 1U,
						 near_u32_physical,
						 &reserve) == -ENOSPC);
	CHECK(reserve == 0x5a5a5a5aU);
	CHECK(swapz_authority_capacity(0xffffffffU, &geometry) == -EINVAL);
	CHECK(swapz_authority_validate_geometry(1U, 0xffffffffU,
						 NULL) == -EINVAL);
	return 0;
}

static int test_16gib_fixture_maximum_capacity(void)
{
	const swapz_u64 partition_bytes = 17179869184ULL;
	const swapz_u32 expected_physical_blocks = 4194048U;
	const swapz_u32 expected_logical_pages = 3727616U;
	const swapz_u32 expected_reserve_blocks = 465952U;
	const swapz_u32 expected_segments = 16383U;
	const swapz_u64 expected_mapper_bytes = 15268315136ULL;
	const swapz_u64 expected_linux_swap_bytes = 15268311040ULL;
	const swapz_u64 expected_index_bytes = 106828764ULL;
	const swapz_u32 total_blocks =
		(swapz_u32)(partition_bytes / SWAPZ_BLOCK_BYTES);
	const swapz_u32 physical_blocks =
		((total_blocks - 1U) / SWAPZ_SEGMENT_BLOCKS) *
		SWAPZ_SEGMENT_BLOCKS;
	const swapz_u32 segment_count =
		physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	struct swapz_authority_geometry geometry;
	struct swapz_authority a;
	struct swapz_map *large_maps;
	swapz_u16 *live_records;
	swapz_u8 *extent_classes, *extent_sequence_delta;
	swapz_u8 *segment_roles, *segment_trimmed;
	swapz_u32 *segment_sequence_base;
	swapz_u32 *gc_scores, *gc_io_scores, *gc_segment_evictions;
	swapz_u32 *segment_mapped_pages, *segment_program_counts;
	swapz_u32 *segment_first_page, *segment_last_page;
	swapz_u32 *page_prev_in_segment, *page_next_in_segment;
	swapz_u16 *gc_min_live_blocks;
	swapz_u64 index_bytes;

	CHECK(physical_blocks == expected_physical_blocks);
	CHECK(segment_count == expected_segments);
	CHECK(swapz_authority_capacity(physical_blocks, &geometry) == 0);
	CHECK(geometry.usable_physical_blocks == expected_physical_blocks);
	CHECK(geometry.gc_reserve_blocks == expected_reserve_blocks);
	CHECK(geometry.required_foreground_headroom_blocks ==
	      SWAPZ_SEGMENT_BLOCKS);
	CHECK(geometry.maximum_logical_pages == expected_logical_pages);
	CHECK(geometry.logical_mapper_bytes == expected_mapper_bytes);
	CHECK(geometry.linux_usable_swap_bytes == expected_linux_swap_bytes);
	CHECK(swapz_authority_validate_geometry(expected_logical_pages + 1U,
						 physical_blocks, NULL) == -ENOSPC);
	CHECK((swapz_u64)expected_logical_pages * SWAPZ_BLOCK_BYTES ==
	      expected_mapper_bytes);
	CHECK((swapz_u64)expected_logical_pages *
	      (sizeof(struct swapz_map) + 2U * sizeof(swapz_u32)) +
	      (swapz_u64)physical_blocks *
	      (sizeof(swapz_u16) + 2U * sizeof(swapz_u8)) +
	      (swapz_u64)segment_count *
	      (7U * sizeof(swapz_u32) + sizeof(swapz_u16) +
	       2U * sizeof(swapz_u8) + sizeof(swapz_u32)) ==
	      expected_index_bytes);

	/* Allocate every capacity-dependent authority/index array used by ctr. */
	large_maps = calloc(expected_logical_pages, sizeof(*large_maps));
	live_records = calloc(physical_blocks, sizeof(*live_records));
	extent_classes = calloc(physical_blocks, sizeof(*extent_classes));
	extent_sequence_delta = calloc(physical_blocks,
					sizeof(*extent_sequence_delta));
	segment_sequence_base = calloc(segment_count,
					       sizeof(*segment_sequence_base));
	gc_scores = calloc(segment_count, sizeof(*gc_scores));
	gc_io_scores = calloc(segment_count, sizeof(*gc_io_scores));
	gc_min_live_blocks = calloc(segment_count, sizeof(*gc_min_live_blocks));
	gc_segment_evictions = calloc(segment_count,
				      sizeof(*gc_segment_evictions));
	segment_mapped_pages = calloc(segment_count,
				      sizeof(*segment_mapped_pages));
	segment_program_counts = calloc(segment_count,
					 sizeof(*segment_program_counts));
	segment_first_page = calloc(segment_count, sizeof(*segment_first_page));
	segment_last_page = calloc(segment_count, sizeof(*segment_last_page));
	page_prev_in_segment = calloc(expected_logical_pages,
				      sizeof(*page_prev_in_segment));
	page_next_in_segment = calloc(expected_logical_pages,
				      sizeof(*page_next_in_segment));
	segment_trimmed = calloc(segment_count, sizeof(*segment_trimmed));
	segment_roles = calloc(segment_count, sizeof(*segment_roles));
	CHECK(large_maps && live_records && extent_classes &&
	      extent_sequence_delta && segment_sequence_base && gc_scores &&
	      gc_io_scores && gc_min_live_blocks && gc_segment_evictions &&
	      segment_mapped_pages && segment_program_counts &&
	      segment_first_page && segment_last_page && page_prev_in_segment &&
	      page_next_in_segment && segment_trimmed && segment_roles);

	/* The one-past maximum was rejected above before these large arrays. */
	CHECK(swapz_authority_init(&a, large_maps, live_records, extent_classes,
				   expected_logical_pages,
				   physical_blocks) == 0);
	CHECK(swapz_enable_extent_sequence_index(&a, extent_sequence_delta,
						  segment_sequence_base,
						  segment_count) == 0);
	CHECK(a.reserve_blocks == expected_reserve_blocks);
	CHECK(a.logical_pages == expected_logical_pages);
	CHECK(swapz_enable_segment_rotation(&a, segment_roles,
					    segment_count) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&a, segment_mapped_pages,
						 segment_count) == 0);
	CHECK(swapz_enable_segment_program_counts(&a, segment_program_counts,
						segment_count) == 0);
	CHECK(swapz_enable_segment_page_lists(&a, segment_first_page,
						segment_last_page,
						page_prev_in_segment,
						page_next_in_segment,
						segment_count,
						expected_logical_pages) == 0);
	CHECK(swapz_enable_segment_gc_accounting(&a, gc_scores, gc_io_scores,
						 gc_min_live_blocks,
						 segment_count) == 0);
	CHECK(a.segment_count == expected_segments);

	index_bytes = (swapz_u64)expected_logical_pages *
		(sizeof(*large_maps) + 2U * sizeof(swapz_u32)) +
		(swapz_u64)physical_blocks *
		(sizeof(*live_records) + sizeof(*extent_classes) +
		 sizeof(*extent_sequence_delta)) +
		(swapz_u64)segment_count *
		(7U * sizeof(swapz_u32) + sizeof(swapz_u16) +
		 2U * sizeof(swapz_u8) + sizeof(*segment_sequence_base));
	CHECK(index_bytes == expected_index_bytes);

	free(segment_roles);
	free(segment_sequence_base);
	free(segment_trimmed);
	free(page_next_in_segment);
	free(page_prev_in_segment);
	free(segment_last_page);
	free(segment_first_page);
	free(segment_program_counts);
	free(segment_mapped_pages);
	free(gc_segment_evictions);
	free(gc_min_live_blocks);
	free(gc_io_scores);
	free(gc_scores);
	free(extent_classes);
	free(extent_sequence_delta);
	free(live_records);
	free(large_maps);
	return 0;
}

static int test_full_publish_and_authoritative_reads(void)
{
	const swapz_u32 pages[] = {0, 1, 2, 3, 4, 5, 6};
	struct swapz_tx tx;
	struct swapz_decoded decoded;
	const swapz_u8 *payload;
	struct swapz_map observed;
	swapz_u32 index;
	swapz_u32 sequence;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 7, 4, &tx) == 0);
	CHECK(authority.in_flight && tx.start_block == 0 &&
	      tx.sequence == 1 && authority.next_block == 4);
	CHECK(swapz_stage(&authority, pages, 7, 4, &tx) == -EBUSY);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, 16384, 4, 0) == 0);
	CHECK(!authority.in_flight && authority.committed_blocks == 4);
	CHECK(live[0] == 7 && classes[0] == 4);

	for (index = 0; index < 7; ++index) {
		observed = maps[index];
		CHECK(observed.valid && observed.start_block == 0 &&
		      observed.generation == 1 && observed.record_index == index &&
		      observed.extent_blocks == 4);
		CHECK(swapz_extent_sequence_lookup(&authority,
						  observed.start_block,
						  &sequence) == 0 &&
		      sequence == 1);
		CHECK(swapz_peek(extent, 16384, observed.record_index, &decoded) == 0);
		CHECK(swapz_read_authoritative_peeked(&authority, index, &observed,
					    extent, 16384, &decoded, &payload) == 0);
		CHECK(decoded.logical_page == index && decoded.generation == 1);
		CHECK(observed.payload_offset == decoded.payload_offset);
		CHECK(observed.payload_crc32c == decoded.payload_crc32c);
		CHECK(payload[0] == index + 1 && payload[2071] == index + 1);
		if (index == 0) {
			struct swapz_map forged = observed;

			forged.payload_offset++;
			CHECK(swapz_read_authoritative_peeked(&authority, index, &forged,
					    extent, 16384,
					    &decoded, &payload) == -ESTALE);
			forged = observed;
			forged.payload_crc32c ^= 1U;
			CHECK(swapz_read_authoritative_peeked(&authority, index, &forged,
					    extent, 16384,
					    &decoded, &payload) == -ESTALE);
		}
	}
	CHECK(swapz_finish(&authority, &tx, extent, 16384, 4, 0) == -ESTALE);
	return 0;
}

static int test_peeked_authoritative_read_rechecks_payload_and_sequence(void)
{
	const swapz_u32 pages[] = {0, 1, 2};
	struct swapz_tx tx;
	struct swapz_decoded peeked, forged;
	struct swapz_map observed;
	const swapz_u8 *payload = NULL;
	swapz_u16 offset;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 3, 2, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, 8192, 2, 0) == 0);
	observed = maps[1];
	CHECK(swapz_peek(extent, 8192, observed.record_index, &peeked) == 0);
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == 0);
	CHECK(payload && payload[0] == 2 && payload[2071] == 2);

	offset = peeked.payload_offset;
	extent[offset] ^= 0x40;
	payload = (const swapz_u8 *)1;
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == -EBADMSG);
	CHECK(payload == NULL);
	extent[offset] ^= 0x40;

	forged = peeked;
	forged.generation++;
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &forged, &payload) == -EUCLEAN);
	forged = peeked;
	forged.payload_crc32c ^= 1U;
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &forged, &payload) == -EUCLEAN);
	extent[8] ^= 0x40; /* sequence bytes are rechecked after the peek */
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == -EUCLEAN);
	extent[8] ^= 0x40;
	return 0;
}

static int test_inflight_interleavings_preserve_authority(void)
{
	const swapz_u32 page[] = {11};
	const swapz_u32 other_page[] = {12};
	struct swapz_tx first, pending, forged, blocked, failed;
	struct swapz_map old, committed;
	struct swapz_decoded decoded;
	const swapz_u8 *payload = NULL;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, page, 1, 1, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, SWAPZ_BLOCK_BYTES,
			   1, 0) == 0);
	memcpy(previous_extent, extent, SWAPZ_BLOCK_BYTES);
	old = maps[page[0]];

	CHECK(swapz_stage(&authority, page, 1, 1, &pending) == 0);
	CHECK(pending.records[0].generation == old.generation + 1U);
	CHECK(encode(&pending) == 0);
	CHECK(swapz_discard_page(&authority, page[0]) == -EBUSY);
	CHECK(swapz_stage(&authority, other_page, 1, 1, &blocked) == -EBUSY);
	CHECK(maps[page[0]].start_block == old.start_block &&
	      maps[page[0]].generation == old.generation);
	CHECK(swapz_peek(previous_extent, SWAPZ_BLOCK_BYTES,
			 old.record_index, &decoded) == 0);
	CHECK(swapz_read_authoritative_peeked(&authority, page[0], &old,
					     previous_extent,
					     SWAPZ_BLOCK_BYTES,
					     &decoded, &payload) == 0);

	forged = pending;
	forged.records[0].generation++;
	CHECK(swapz_finish(&authority, &forged, extent, SWAPZ_BLOCK_BYTES,
			   1, 0) == -ESTALE);
	CHECK(authority.in_flight);
	CHECK(maps[page[0]].generation == old.generation);

	CHECK(swapz_finish(&authority, &pending, extent, SWAPZ_BLOCK_BYTES,
			   1, 0) == 0);
	committed = maps[page[0]];
	CHECK(committed.valid && committed.generation == old.generation + 1U);
	CHECK(swapz_read_authoritative_peeked(&authority, page[0], &old,
					     previous_extent,
					     SWAPZ_BLOCK_BYTES,
					     &decoded, &payload) == -ESTALE);
	CHECK(swapz_finish(&authority, &pending, extent, SWAPZ_BLOCK_BYTES,
			   1, 0) == -ESTALE);

	CHECK(swapz_discard_page(&authority, page[0]) == 0);
	CHECK(!maps[page[0]].valid &&
	      maps[page[0]].generation == committed.generation + 1U);
	CHECK(swapz_stage(&authority, page, 1, 1, &failed) == 0);
	CHECK(failed.records[0].generation == committed.generation + 2U);
	CHECK(encode(&failed) == 0);
	CHECK(swapz_finish(&authority, &failed, extent, SWAPZ_BLOCK_BYTES,
			   0, -EIO) == -EIO);
	CHECK(!maps[page[0]].valid &&
	      maps[page[0]].generation == committed.generation + 1U);
	return 0;
}

static int test_torn_write_no_old_mapping_invalidation(void)
{
	const swapz_u32 pages[] = {0, 1, 2};
	struct swapz_tx first, pending, later;
	struct swapz_map original;
	swapz_u32 new_page[] = {7};

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 3, 2, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, 8192, 2, 0) == 0);
	original = maps[0];
	CHECK(live[0] == 3);
	CHECK(swapz_stage(&authority, pages, 3, 2, &pending) == 0);
	CHECK(pending.start_block == 2 && pending.records[0].generation == 2);
	CHECK(encode(&pending) == 0);
	CHECK(swapz_finish(&authority, &pending, extent, 8192, 1, -EIO) == -EIO);
	CHECK(maps[0].start_block == original.start_block &&
	      maps[0].generation == 1 && live[0] == 3);
	CHECK(live[2] == 0 && authority.abandoned_blocks == 2);
	CHECK(swapz_stage(&authority, new_page, 1, 2, &later) == 0);
	CHECK(later.start_block == 4); /* never reuse torn location */
	CHECK(swapz_abort(&authority, &later) == 0);
	CHECK(authority.abandoned_blocks == 4);
	return 0;
}

static int test_overwrite_generation_and_liveness(void)
{
	const swapz_u32 original_pages[] = {0, 1, 2, 3, 4, 5, 6};
	const swapz_u32 overwritten[] = {0, 1, 2};
	struct swapz_tx first, second;
	struct swapz_map old;
	struct swapz_decoded decoded;
	const swapz_u8 *payload;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, original_pages, 7, 4, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, 16384, 4, 0) == 0);
	memcpy(previous_extent, extent, 16384);
	old = maps[0];

	CHECK(swapz_stage(&authority, overwritten, 3, 2, &second) == 0);
	CHECK(second.start_block == 4 && second.sequence == 2);
	CHECK(second.records[0].generation == 2);
	CHECK(encode(&second) == 0);
	CHECK(swapz_finish(&authority, &second, extent, 8192, 2, 0) == 0);
	CHECK(live[0] == 4 && live[4] == 3);
	CHECK(classes[0] == 4 && classes[4] == 2);
	CHECK(maps[0].generation == 2 && maps[3].generation == 1);
	CHECK(swapz_peek(previous_extent, 16384, old.record_index, &decoded) == 0);
	CHECK(swapz_read_authoritative_peeked(&authority, 0, &old,
				    previous_extent, 16384,
				    &decoded, &payload) == -ESTALE);
	CHECK(swapz_peek(extent, 8192, maps[0].record_index, &decoded) == 0);
	CHECK(swapz_read_authoritative_peeked(&authority, 0, &maps[0],
				    extent, 8192, &decoded, &payload) == 0);
	CHECK(decoded.generation == 2 && decoded.logical_page == 0);
	CHECK(swapz_peek(previous_extent, 16384, maps[3].record_index, &decoded) == 0);
	CHECK(swapz_read_authoritative_peeked(&authority, 3, &maps[3],
				    previous_extent, 16384,
				    &decoded, &payload) == 0);
	return 0;
}

static int test_last_corrupt_sibling_prevents_all_publication(void)
{
	const swapz_u32 pages[] = {0, 1, 2};
	struct swapz_tx first, second;
	struct swapz_map snapshot[3];
	struct swapz_decoded decoded;
	const swapz_u8 *payload;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 3, 2, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, 8192, 2, 0) == 0);
	memcpy(snapshot, maps, sizeof(snapshot));
	CHECK(swapz_stage(&authority, pages, 3, 2, &second) == 0);
	CHECK(encode(&second) == 0);
	CHECK(swapz_lookup(extent, 8192, 2, &decoded, &payload) == 0);
	extent[decoded.payload_offset] ^= 0x80; /* third record CRC failure */
	CHECK(swapz_finish(&authority, &second, extent, 8192, 2, 0) == -EBADMSG);
	CHECK(memcmp(snapshot, maps, sizeof(snapshot)) == 0);
	CHECK(live[0] == 3 && live[2] == 0);
	CHECK(authority.abandoned_blocks == 2 && !authority.in_flight);
	return 0;
}

static int test_header_corruption_and_wrong_sequence(void)
{
	const swapz_u32 pages[] = {0};
	struct swapz_tx first, second;
	struct swapz_map original;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 1, 1, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, 4096, 1, 0) == 0);
	original = maps[0];

	CHECK(swapz_stage(&authority, pages, 1, 1, &second) == 0);
	CHECK(encode(&second) == 0);
	extent[8] ^= 0x40; /* metadata sequence, not payload */
	CHECK(swapz_finish(&authority, &second, extent, 4096, 1, 0) == -EBADMSG);
	CHECK(maps[0].generation == original.generation);
	CHECK(maps[0].start_block == original.start_block);
	CHECK(authority.abandoned_blocks == 1);
	return 0;
}

static int test_generation_overflow_and_duplicate_rejections(void)
{
	const swapz_u32 duplicate[] = {4, 4};
	const swapz_u32 good[] = {4};
	const swapz_u32 invalid[] = {128};
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, duplicate, 2, 2, &tx) == -EEXIST);
	CHECK(swapz_stage(&authority, invalid, 1, 2, &tx) == -ERANGE);
	CHECK(swapz_stage(&authority, good, 0, 2, &tx) == -EINVAL);
	CHECK(swapz_stage(&authority, good, 1, 3, &tx) == -EINVAL);
	maps[4].generation = UINT32_MAX;
	CHECK(swapz_stage(&authority, good, 1, 2, &tx) == -EOVERFLOW);
	CHECK(authority.next_block == 0 && authority.in_flight == 0);
	return 0;
}

static int test_allocator_reserve_exhaustion(void)
{
	struct swapz_tx tx;
	const swapz_u32 pages[] = {0};
	unsigned int i;

	CHECK(init() == 0);
	for (i = 0; i < 384; ++i) {
		CHECK(swapz_stage(&authority, pages, 1, 4, &tx) == 0);
		CHECK(tx.start_block == i * 4);
		CHECK(tx.start_block % 4 == 0);
		CHECK(tx.start_block % 256 <= 252);
		CHECK(swapz_abort(&authority, &tx) == 0);
	}
	CHECK(authority.next_block == 1536);
	CHECK(authority.reserve_blocks == 512);
	CHECK(authority.abandoned_blocks == 1536);
	CHECK(swapz_stage(&authority, pages, 1, 4, &tx) == -ENOSPC);
	CHECK(!authority.in_flight);
	return 0;
}

static int advance_append_only_cursor(struct swapz_authority *a,
				      swapz_u32 blocks)
{
	const swapz_u32 pages[] = {0};
	struct swapz_tx tx;
	swapz_u32 cursor;

	for (cursor = 0; cursor < blocks; ++cursor) {
		if (swapz_stage(a, pages, 1, 1, &tx) ||
		    tx.start_block != cursor || swapz_abort(a, &tx))
			return -1;
	}
	return 0;
}

static int init_append_only_authority(struct swapz_authority *a,
				     swapz_u32 physical_blocks)
{
	int error = swapz_authority_init(a, maps, live, classes, 64,
					 physical_blocks);

	if (error)
		return error;
	return swapz_enable_extent_sequence_index(
		a, extent_sequence_delta, segment_sequence_base,
		physical_blocks / SWAPZ_SEGMENT_BLOCKS);
}

static int verify_append_only_page(struct swapz_authority *a,
				   const struct swapz_tx *tx)
{
	struct swapz_decoded decoded;
	struct swapz_map observed = maps[0];
	const swapz_u8 *payload = NULL;
	swapz_u32 bytes_total = (swapz_u32)tx->extent_blocks *
		SWAPZ_BLOCK_BYTES;

	if (!observed.valid || observed.start_block != tx->start_block ||
	    observed.extent_blocks != tx->extent_blocks ||
	    observed.record_index || observed.payload_length != sizeof(content) ||
	    swapz_peek(extent, bytes_total, observed.record_index, &decoded) ||
	    swapz_read_authoritative_peeked(a, 0, &observed, extent, bytes_total,
					    &decoded, &payload) ||
	    !payload || memcmp(payload, content, sizeof(content)))
		return -1;
	return 0;
}

static int test_packed_append_only_segment_edges(void)
{
	const swapz_u32 pages[] = {0};
	struct swapz_authority a;
	struct swapz_tx tx;
	swapz_u32 next_sequence;

	/* Two blocks exactly fill the segment tail without waste. */
	CHECK(init_append_only_authority(&a, 2048) == 0);
	CHECK(advance_append_only_cursor(&a, 254) == 0);
	CHECK(swapz_stage(&a, pages, 1, 2, &tx) == 0);
	CHECK(tx.start_block == 254 && a.next_block == 256);
	CHECK(!a.alignment_hole_blocks_foreground &&
	      !a.segment_tail_waste_blocks_foreground);
	CHECK(swapz_abort(&a, &tx) == 0);

	/* Two blocks at 255 skip one block and publish byte-exactly. */
	CHECK(init_append_only_authority(&a, 2048) == 0);
	CHECK(advance_append_only_cursor(&a, 255) == 0);
	CHECK(swapz_stage(&a, pages, 1, 2, &tx) == 0);
	CHECK(tx.start_block == 256 && a.next_block == 258);
	CHECK(a.alignment_hole_blocks_foreground == 1 &&
	      a.segment_tail_waste_blocks_foreground == 1);
	CHECK(!a.alignment_hole_blocks_gc && !a.segment_tail_waste_blocks_gc);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, extent, 2U * SWAPZ_BLOCK_BYTES, 2, 0) == 0);
	CHECK(maps[0].valid && maps[0].start_block == 256 &&
	      maps[0].generation == 1 && live[256] == 1);
	CHECK(verify_append_only_page(&a, &tx) == 0);

	/* Four blocks exactly fill a segment without waste. */
	CHECK(init_append_only_authority(&a, 2048) == 0);
	CHECK(advance_append_only_cursor(&a, 252) == 0);
	CHECK(swapz_stage(&a, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 252 && a.next_block == 256);
	CHECK(!a.alignment_hole_blocks_foreground &&
	      !a.segment_tail_waste_blocks_foreground);
	CHECK(swapz_abort(&a, &tx) == 0);

	/* Four blocks at 254 skip two tail blocks and publish byte-exactly. */
	CHECK(init_append_only_authority(&a, 2048) == 0);
	CHECK(advance_append_only_cursor(&a, 254) == 0);
	CHECK(swapz_stage(&a, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 256 && a.next_block == 260);
	CHECK(a.alignment_hole_blocks_foreground == 2 &&
	      a.segment_tail_waste_blocks_foreground == 2);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, extent, 4U * SWAPZ_BLOCK_BYTES, 4, 0) == 0);
	CHECK(maps[0].valid && maps[0].start_block == 256 &&
	      maps[0].generation == 1 && live[256] == 1);
	CHECK(verify_append_only_page(&a, &tx) == 0);

	/* An extent exactly filling the foreground area may end at the reserve. */
	CHECK(init_append_only_authority(&a, 1024) == 0);
	CHECK(advance_append_only_cursor(&a, 508) == 0);
	CHECK(swapz_stage(&a, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 508 && a.next_block == 512);
	CHECK(!a.alignment_hole_blocks_foreground &&
	      !a.segment_tail_waste_blocks_foreground);
	CHECK(swapz_abort(&a, &tx) == 0);

	/* A skipped extent may not enter the reserved suffix or mutate state. */
	CHECK(init_append_only_authority(&a, 1024) == 0);
	CHECK(advance_append_only_cursor(&a, 511) == 0);
	next_sequence = a.next_sequence;
	CHECK(swapz_stage(&a, pages, 1, 2, &tx) == -ENOSPC);
	CHECK(a.next_block == 511 && a.next_sequence == next_sequence &&
	      !a.in_flight &&
	      !a.alignment_hole_blocks_foreground &&
	      !a.segment_tail_waste_blocks_foreground &&
	      !a.alignment_hole_blocks_gc && !a.segment_tail_waste_blocks_gc);
	return 0;
}


static int test_batch_tail_abort_preserves_older_snapshot(void)
{
	const swapz_u32 first_page[] = {0};
	const swapz_u32 second_page[] = {1};
	struct swapz_tx first, second;
	unsigned int abandoned_before;

	CHECK(init() == 0);
	/* Production batching uses rotating/dead-segment allocation semantics. */
	authority.reuse_dead_segments = 1;

	CHECK(swapz_stage_batch(&authority, first_page, 1, 1, &first) == 0);
	CHECK(first.start_block == 0 && first.sequence == 1);
	CHECK(encode(&first) == 0);
	memcpy(previous_extent, extent, SWAPZ_BLOCK_BYTES);
	CHECK(swapz_batch_pause(&authority, &first) == 0);
	CHECK(!authority.in_flight && authority.batch_pending == 1 &&
	      authority.batch_consumed == 0);

	CHECK(swapz_stage_batch(&authority, second_page, 1, 1, &second) == 0);
	CHECK(second.start_block == 1 && second.sequence == 2);
	CHECK(encode(&second) == 0);
	CHECK(swapz_batch_pause(&authority, &second) == 0);
	CHECK(!authority.in_flight && authority.batch_pending == 2 &&
	      authority.batch_first_sequence == 1 &&
	      authority.batch_consumed == 0);

	/* Only the newest verified snapshot may be cancelled. */
	CHECK(swapz_batch_abort_tail(&authority, &first) == -ESTALE);
	abandoned_before = authority.abandoned_blocks;
	CHECK(swapz_batch_abort_tail(&authority, &second) == 0);
	CHECK(authority.abandoned_blocks == abandoned_before + 1);
	CHECK(authority.batch_pending == 1 &&
	      authority.batch_first_sequence == 1 &&
	      authority.batch_consumed == 0);

	/* The older physical run remains replayable and publishes normally. */
	CHECK(swapz_batch_resume(&authority, &first) == 0);
	CHECK(authority.in_flight && authority.batch_replaying);
	CHECK(swapz_finish(&authority, &first, previous_extent,
			  SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	CHECK(!authority.in_flight && !authority.batch_pending &&
	      !authority.batch_replaying);
	CHECK(maps[0].valid && maps[0].start_block == first.start_block &&
	      maps[0].generation == 1);
	CHECK(!maps[1].valid);
	CHECK(live[first.start_block] == 1 && !live[second.start_block]);
	return 0;
}

static int test_compact_extent_sequence_delta_bound(void)
{
	const swapz_u32 first_page[] = {0};
	const swapz_u32 later_page[] = {1};
	struct swapz_tx tx;
	swapz_u32 index, sequence;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, first_page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0 && tx.sequence == 1 && encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, SWAPZ_BLOCK_BYTES, 1, 0) == 0);

	/* Aborted reservations still consume their unique physical block and
	 * sequence. The last possible one-block extent in a segment must fit the
	 * full 8-bit delta from the first committed extent. */
	for (index = 0; index < SWAPZ_SEGMENT_BLOCKS - 2U; ++index) {
		CHECK(swapz_stage(&authority, later_page, 1, 1, &tx) == 0);
		CHECK(tx.start_block == index + 1U);
		CHECK(swapz_abort(&authority, &tx) == 0);
	}
	CHECK(swapz_stage(&authority, later_page, 1, 1, &tx) == 0);
	CHECK(tx.start_block == SWAPZ_SEGMENT_BLOCKS - 1U &&
	      tx.sequence == SWAPZ_SEGMENT_BLOCKS && encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	CHECK(swapz_extent_sequence_lookup(&authority, tx.start_block,
						  &sequence) == 0 &&
	      sequence == tx.sequence);
	CHECK(extent_sequence_delta[tx.start_block] == (swapz_u8)~0U);
	return 0;
}

static int test_compact_extent_sequence_overflow_fails_closed(void)
{
	const swapz_u32 first_page[] = {0};
	const swapz_u32 later_page[] = {1};
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, first_page, 1, 1, &tx) == 0);
	CHECK(tx.sequence == 1 && encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	authority.next_sequence = 257;
	CHECK(swapz_stage(&authority, later_page, 1, 1, &tx) == 0);
	CHECK(tx.sequence == 257 && encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, SWAPZ_BLOCK_BYTES, 1, 0) ==
	      -EOVERFLOW);
	CHECK(maps[0].valid && !maps[1].valid && live[tx.start_block] == 0);
	return 0;
}

static int test_short_write_always_quarantines(void)
{
	const swapz_u32 pages[] = {9};
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 1, 4, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&authority, &tx, extent, 16384, 3, 0) == -EIO);
	CHECK(!maps[9].valid && authority.abandoned_blocks == 4);
	CHECK(swapz_stage(&authority, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 4);
	CHECK(swapz_abort(&authority, &tx) == 0);
	return 0;
}

static int test_old_liveness_corruption_fail_closed(void)
{
	const swapz_u32 pages[] = {0};
	struct swapz_tx first, second;
	struct swapz_map old;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, pages, 1, 1, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(swapz_finish(&authority, &first, extent, 4096, 1, 0) == 0);
	old = maps[0];
	live[0] = 0; /* fault injection: corrupted runtime refcount */
	CHECK(swapz_stage(&authority, pages, 1, 1, &second) == 0);
	CHECK(encode(&second) == 0);
	CHECK(swapz_finish(&authority, &second, extent, 4096, 1, 0) == -EUCLEAN);
	CHECK(maps[0].start_block == old.start_block &&
	      maps[0].generation == old.generation);
	CHECK(live[1] == 0 && authority.abandoned_blocks == 1);
	return 0;
}


#define CAPACITY_PROGRESS_PHYSICAL_SEGMENTS 8U
#define CAPACITY_PROGRESS_PHYSICAL_BLOCKS \
	(CAPACITY_PROGRESS_PHYSICAL_SEGMENTS * SWAPZ_SEGMENT_BLOCKS)

static struct swapz_authority capacity_progress_authority;
static struct swapz_map capacity_progress_maps[CAPACITY_PROGRESS_PHYSICAL_BLOCKS];
static swapz_u16 capacity_progress_live[CAPACITY_PROGRESS_PHYSICAL_BLOCKS];
static swapz_u8 capacity_progress_classes[CAPACITY_PROGRESS_PHYSICAL_BLOCKS];
static swapz_u8 capacity_progress_roles[CAPACITY_PROGRESS_PHYSICAL_SEGMENTS];
static swapz_u32 capacity_progress_segment_maps[
	CAPACITY_PROGRESS_PHYSICAL_SEGMENTS];
static swapz_u32 capacity_progress_versions[CAPACITY_PROGRESS_PHYSICAL_BLOCKS];
static swapz_u32 capacity_progress_generations[
	CAPACITY_PROGRESS_PHYSICAL_BLOCKS];
static swapz_u8 capacity_progress_media[
	CAPACITY_PROGRESS_PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES];
static swapz_u8 capacity_progress_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 capacity_progress_expected[SWAPZ_BLOCK_BYTES];
static swapz_u32 capacity_progress_logical_pages;
static unsigned long long capacity_progress_gc_writes;

static void capacity_progress_make_raw_page(swapz_u32 logical,
					    swapz_u32 version,
					    swapz_u8 *output)
{
	swapz_u32 state = 0x9e3779b9U ^
		(logical * 0x85ebca6bU) ^ (version * 0xc2b2ae35U);
	swapz_u32 offset;

	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; offset += 4U) {
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		output[offset] = (swapz_u8)state;
		output[offset + 1U] = (swapz_u8)(state >> 8);
		output[offset + 2U] = (swapz_u8)(state >> 16);
		output[offset + 3U] = (swapz_u8)(state >> 24);
	}
}

static int capacity_progress_setup(void)
{
	struct swapz_authority_geometry geometry;
	int error;

	error = swapz_authority_capacity(CAPACITY_PROGRESS_PHYSICAL_BLOCKS,
					 &geometry);
	if (error)
		return error;
	if (geometry.maximum_logical_pages !=
	    5U * SWAPZ_SEGMENT_BLOCKS ||
	    geometry.gc_reserve_blocks != 2U * SWAPZ_SEGMENT_BLOCKS ||
	    geometry.required_foreground_headroom_blocks !=
		    SWAPZ_SEGMENT_BLOCKS)
		return -EUCLEAN;
	if (swapz_authority_validate_geometry(
		    geometry.maximum_logical_pages + 1U,
		    CAPACITY_PROGRESS_PHYSICAL_BLOCKS, NULL) != -ENOSPC)
		return -EUCLEAN;

	capacity_progress_logical_pages = geometry.maximum_logical_pages;
	memset(capacity_progress_maps, 0, sizeof(capacity_progress_maps));
	memset(capacity_progress_live, 0, sizeof(capacity_progress_live));
	memset(capacity_progress_classes, 0, sizeof(capacity_progress_classes));
	memset(capacity_progress_roles, 0, sizeof(capacity_progress_roles));
	memset(capacity_progress_segment_maps, 0,
	       sizeof(capacity_progress_segment_maps));
	memset(capacity_progress_versions, 0, sizeof(capacity_progress_versions));
	memset(capacity_progress_generations, 0,
	       sizeof(capacity_progress_generations));
	memset(capacity_progress_media, 0, sizeof(capacity_progress_media));
	capacity_progress_gc_writes = 0;

	error = swapz_authority_init(
		&capacity_progress_authority, capacity_progress_maps,
		capacity_progress_live, capacity_progress_classes,
		capacity_progress_logical_pages,
		CAPACITY_PROGRESS_PHYSICAL_BLOCKS);
	if (error)
		return error;
	capacity_progress_authority.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(
		&capacity_progress_authority, capacity_progress_roles,
		CAPACITY_PROGRESS_PHYSICAL_SEGMENTS);
	if (error)
		return error;
	return swapz_enable_segment_mapping_counts(
		&capacity_progress_authority, capacity_progress_segment_maps,
		CAPACITY_PROGRESS_PHYSICAL_SEGMENTS);
}

static int capacity_progress_write_page(swapz_u32 logical, swapz_u32 version)
{
	struct swapz_tx tx;
	int error;

	if (logical >= capacity_progress_logical_pages)
		return -ERANGE;
	capacity_progress_make_raw_page(logical, version,
					capacity_progress_page);
	error = swapz_stage(&capacity_progress_authority, &logical, 1, 1, &tx);
	if (error)
		return error;
	if (tx.start_block >= CAPACITY_PROGRESS_PHYSICAL_BLOCKS) {
		(void)swapz_finish_raw(&capacity_progress_authority, &tx,
				      capacity_progress_page, 0, -ERANGE);
		return -ERANGE;
	}
	memcpy(capacity_progress_media +
		       (size_t)tx.start_block * SWAPZ_BLOCK_BYTES,
	       capacity_progress_page, SWAPZ_BLOCK_BYTES);
	error = swapz_finish_raw(&capacity_progress_authority, &tx,
				 capacity_progress_page, 1, 0);
	if (error)
		return error;
	capacity_progress_versions[logical] = version;
	capacity_progress_generations[logical]++;
	if (capacity_progress_maps[logical].generation !=
	    capacity_progress_generations[logical])
		return -EUCLEAN;
	return 0;
}

static int capacity_progress_verify_all_pages(void)
{
	swapz_u32 logical;

	for (logical = 0; logical < capacity_progress_logical_pages; ++logical) {
		const struct swapz_map *map = &capacity_progress_maps[logical];
		const swapz_u8 *stored;

		if (!map->valid || !map->raw || map->extent_blocks != 1 ||
		    map->start_block >= CAPACITY_PROGRESS_PHYSICAL_BLOCKS ||
		    map->generation != capacity_progress_generations[logical])
			return -EUCLEAN;
		stored = capacity_progress_media +
			(size_t)map->start_block * SWAPZ_BLOCK_BYTES;
		capacity_progress_make_raw_page(
			logical, capacity_progress_versions[logical],
			capacity_progress_expected);
		if (memcmp(stored, capacity_progress_expected,
			   SWAPZ_BLOCK_BYTES) ||
		    swapz_verify_raw(&capacity_progress_authority, logical,
				     stored))
			return -EBADMSG;
	}
	return 0;
}

static int capacity_progress_fill_all_pages(swapz_u32 version)
{
	swapz_u32 logical;

	for (logical = 0; logical < capacity_progress_logical_pages; ++logical) {
		int error = capacity_progress_write_page(logical, version);

		if (error)
			return error;
	}
	return 0;
}

static unsigned int capacity_progress_reserve_segments(void)
{
	unsigned int count = 0;
	swapz_u32 segment;

	for (segment = 0; segment < CAPACITY_PROGRESS_PHYSICAL_SEGMENTS;
	     ++segment)
		if (!capacity_progress_roles[segment])
			count++;
	return count;
}

static int capacity_progress_relocate_segment(swapz_u32 victim)
{
	swapz_u32 logical;
	int error;

	error = swapz_gc_begin_rotation(&capacity_progress_authority, victim);
	if (error)
		return error;
	for (logical = 0; logical < capacity_progress_logical_pages; ++logical) {
		struct swapz_tx tx;
		swapz_u32 source;

		if (!capacity_progress_maps[logical].valid ||
		    capacity_progress_maps[logical].start_block /
				    SWAPZ_SEGMENT_BLOCKS != victim)
			continue;
		source = capacity_progress_maps[logical].start_block;
		memcpy(capacity_progress_page,
		       capacity_progress_media +
			       (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		if (swapz_verify_raw(&capacity_progress_authority, logical,
				     capacity_progress_page))
			return -EBADMSG;
		error = swapz_stage(&capacity_progress_authority, &logical, 1, 1,
				    &tx);
		if (error)
			return error;
		memcpy(capacity_progress_media +
			       (size_t)tx.start_block * SWAPZ_BLOCK_BYTES,
		       capacity_progress_page, SWAPZ_BLOCK_BYTES);
		error = swapz_finish_raw(&capacity_progress_authority, &tx,
					 capacity_progress_page, 1, 0);
		if (error)
			return error;
		capacity_progress_generations[logical]++;
		capacity_progress_gc_writes++;
		if (capacity_progress_maps[logical].generation !=
		    capacity_progress_generations[logical])
			return -EUCLEAN;
	}
	return swapz_gc_commit_rotation(&capacity_progress_authority, victim);
}

static int capacity_progress_overwrite_outside_open(
	swapz_u32 *next_source_segment)
{
	swapz_u32 offset;

	for (offset = 0; offset < CAPACITY_PROGRESS_PHYSICAL_SEGMENTS;
	     ++offset) {
		swapz_u32 segment =
			(*next_source_segment + offset) %
			CAPACITY_PROGRESS_PHYSICAL_SEGMENTS;
		swapz_u32 logical;

		if (!capacity_progress_roles[segment] ||
		    segment == capacity_progress_authority.open_segment ||
		    capacity_progress_segment_maps[segment] < 2U)
			continue;
		for (logical = 0; logical < capacity_progress_logical_pages;
		     ++logical) {
			swapz_u32 source;

			if (!capacity_progress_maps[logical].valid ||
			    capacity_progress_maps[logical].start_block >=
				    CAPACITY_PROGRESS_PHYSICAL_BLOCKS)
				return -EUCLEAN;
			source = capacity_progress_maps[logical].start_block /
				 SWAPZ_SEGMENT_BLOCKS;
			if (source == segment) {
				int error = capacity_progress_write_page(
					logical,
					capacity_progress_versions[logical] + 1U);

				if (!error)
					*next_source_segment =
						(segment + 1U) %
						CAPACITY_PROGRESS_PHYSICAL_SEGMENTS;
				return error;
			}
		}
		return -EUCLEAN;
	}
	return -EUCLEAN;
}

static int capacity_progress_choose_partial_victim(swapz_u32 *victim)
{
	swapz_u32 segment;
	swapz_u32 best = ~(swapz_u32)0;
	swapz_u32 fewest_live = SWAPZ_SEGMENT_BLOCKS;

	for (segment = 0; segment < CAPACITY_PROGRESS_PHYSICAL_SEGMENTS;
	     ++segment) {
		if (!capacity_progress_roles[segment] ||
		    segment == capacity_progress_authority.open_segment ||
		    !capacity_progress_segment_maps[segment] ||
		    capacity_progress_segment_maps[segment] >= fewest_live)
			continue;
		fewest_live = capacity_progress_segment_maps[segment];
		best = segment;
	}
	if (best == ~(swapz_u32)0)
		return -ENOSPC;
	*victim = best;
	return 0;
}


/*
 * Exactly one stale RAW block in a 256-block victim requires relocation of
 * 255 live records. The GC destination must retain its final single block;
 * an overwrite within that last block must not corrupt the earlier records.
 * A second rotation of the opposite (one-survivor) victim proves forward
 * progress without consuming either reserve role.
 */
static int test_maximum_capacity_single_block_gc_reclaim(void)
{
	swapz_u32 overwrite_index;
	swapz_u32 logical = 2U;
	struct swapz_tx tx;

	CHECK(capacity_progress_setup() == 0);
	CHECK(capacity_progress_fill_all_pages(1U) == 0);
	for (overwrite_index = 0U; overwrite_index < SWAPZ_SEGMENT_BLOCKS;
	     ++overwrite_index)
		CHECK(capacity_progress_write_page(0U, overwrite_index + 2U) == 0);
	CHECK(capacity_progress_authority.open_segment == 5U);
	CHECK(capacity_progress_authority.next_block ==
	      6U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(capacity_progress_segment_maps[0] ==
	      SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(capacity_progress_segment_maps[5] == 1U);
	CHECK(swapz_stage(&capacity_progress_authority, &logical, 1, 1,
			  &tx) == -ENOSPC);
	CHECK(!capacity_progress_authority.in_flight);
	CHECK(capacity_progress_verify_all_pages() == 0);

	CHECK(capacity_progress_relocate_segment(0U) == 0);
	CHECK(capacity_progress_gc_writes == SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(capacity_progress_segment_maps[6] ==
	      SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(capacity_progress_authority.open_segment == 6U);
	CHECK(capacity_progress_authority.next_block ==
	      7U * SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(capacity_progress_reserve_segments() == 2U);
	CHECK(capacity_progress_verify_all_pages() == 0);

	/* Consuming the last free destination block must preserve prior data. */
	CHECK(capacity_progress_write_page(1U, 2U) == 0);
	CHECK(capacity_progress_authority.next_block ==
	      7U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_stage(&capacity_progress_authority, &logical, 1, 1,
			  &tx) == -ENOSPC);
	CHECK(!capacity_progress_authority.in_flight);
	CHECK(capacity_progress_verify_all_pages() == 0);

	CHECK(capacity_progress_relocate_segment(5U) == 0);
	CHECK(capacity_progress_gc_writes == SWAPZ_SEGMENT_BLOCKS);
	CHECK(capacity_progress_segment_maps[7] == 1U);
	CHECK(capacity_progress_authority.open_segment == 7U);
	CHECK(capacity_progress_reserve_segments() == 2U);
	CHECK(capacity_progress_write_page(logical, 2U) == 0);
	CHECK(capacity_progress_verify_all_pages() == 0);
	return 0;
}

static int test_maximum_capacity_raw_cow_and_gc_progress(void)
{
	const unsigned int rotations = 8U;
	swapz_u32 next_source_segment = 0;
	unsigned int rotation;

	CHECK(capacity_progress_setup() == 0);
	CHECK(capacity_progress_reserve_segments() == 2U);
	CHECK(capacity_progress_fill_all_pages(1U) == 0);
	CHECK(capacity_progress_authority.next_block ==
	      capacity_progress_logical_pages);
	CHECK(capacity_progress_verify_all_pages() == 0);

	/* The accepted all-RAW maximum must have one ordinary COW block now. */
	CHECK(capacity_progress_write_page(0U, 2U) == 0);
	CHECK(capacity_progress_verify_all_pages() == 0);

	for (rotation = 0; rotation < rotations; ++rotation) {
		swapz_u32 victim;
		swapz_u32 victim_live;
		unsigned int attempts;
		unsigned long long gc_writes_before;
		int error = 0;

		for (attempts = 0;
		     attempts < CAPACITY_PROGRESS_PHYSICAL_SEGMENTS *
				     SWAPZ_SEGMENT_BLOCKS;
		     ++attempts) {
			error = capacity_progress_overwrite_outside_open(
				&next_source_segment);
			if (error)
				break;
		}
		CHECK(error == -ENOSPC);
		CHECK(!capacity_progress_authority.in_flight);
		CHECK(capacity_progress_choose_partial_victim(&victim) == 0);
		victim_live = capacity_progress_segment_maps[victim];
		CHECK(victim_live >= SWAPZ_SEGMENT_BLOCKS / 2U);
		CHECK(victim_live < SWAPZ_SEGMENT_BLOCKS);
		gc_writes_before = capacity_progress_gc_writes;
		CHECK(capacity_progress_relocate_segment(victim) == 0);
		CHECK(capacity_progress_gc_writes - gc_writes_before ==
		      victim_live);
		CHECK(capacity_progress_reserve_segments() == 2U);
		CHECK(capacity_progress_verify_all_pages() == 0);
	}
	CHECK(capacity_progress_gc_writes >=
	      (unsigned long long)rotations * (SWAPZ_SEGMENT_BLOCKS / 2U));
	return 0;
}


/*
 * Model the exact 17 constructor capacity-index sites with tiny geometry.
 * The real constructor attempts all 17 allocations before testing the combined
 * null predicate, so injection skips exactly one calloc but still allocates
 * every later site before reverse-order cleanup. Success attaches the real
 * production authority. This never allocates max-capacity memory or claims to
 * exercise the loaded DM constructor.
 */
static int test_small_index_failure_and_repeated_lifecycle(void)
{
	const swapz_u32 physical_blocks = 4U * SWAPZ_SEGMENT_BLOCKS;
	const swapz_u32 segment_count =
		physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	struct swapz_authority_geometry geometry;
	struct swapz_authority temporary_authority;
	/* Keep this in the exact production constructor order. */
	const size_t allocation_sizes[] = {
		sizeof(swapz_u32), sizeof(swapz_u32), sizeof(swapz_u16),
		sizeof(swapz_u32), sizeof(swapz_u32), sizeof(swapz_u32),
		sizeof(swapz_u32), sizeof(swapz_u32),
		sizeof(swapz_u32), sizeof(swapz_u32),
		sizeof(swapz_u8), sizeof(swapz_u8),
		sizeof(struct swapz_map), sizeof(swapz_u16),
		sizeof(swapz_u8), sizeof(swapz_u8), sizeof(swapz_u32),
	};
	const size_t allocation_count = sizeof(allocation_sizes) /
					sizeof(allocation_sizes[0]);
	size_t allocation_lengths[17];
	size_t iteration;

	CHECK(allocation_count == 17U);
	CHECK(swapz_authority_capacity(physical_blocks, &geometry) == 0);
	CHECK(geometry.maximum_logical_pages == SWAPZ_SEGMENT_BLOCKS);
	for (iteration = 0U; iteration < 8U; ++iteration)
		allocation_lengths[iteration] = segment_count;
	allocation_lengths[8] = geometry.maximum_logical_pages;
	allocation_lengths[9] = geometry.maximum_logical_pages;
	allocation_lengths[10] = segment_count;
	allocation_lengths[11] = segment_count;
	allocation_lengths[12] = geometry.maximum_logical_pages;
	allocation_lengths[13] = physical_blocks;
	allocation_lengths[14] = physical_blocks;
	allocation_lengths[15] = physical_blocks;
	allocation_lengths[16] = segment_count;

	/* 17 injected site failures plus success, repeated 8 times each. */
	for (iteration = 0; iteration < 8U * (allocation_count + 1U);
	     ++iteration) {
		void *allocated_indexes[17] = {0};
		size_t site, failure_site = iteration % (allocation_count + 1U);
		int error = 0;
		bool allocated_all = false;

		for (site = 0; site < allocation_count; ++site) {
			if (site == failure_site) {
				error = -ENOMEM;
				continue;
			}
			allocated_indexes[site] =
				calloc(allocation_lengths[site],
				       allocation_sizes[site]);
			if (!allocated_indexes[site])
				error = -ENOMEM;
		}
		if (!error) {
			allocated_all = true;
			error = swapz_authority_init(
				&temporary_authority,
				(struct swapz_map *)allocated_indexes[12],
				(swapz_u16 *)allocated_indexes[13],
				(swapz_u8 *)allocated_indexes[14],
				geometry.maximum_logical_pages, physical_blocks);
			if (!error)
				error = swapz_enable_extent_sequence_index(
					&temporary_authority,
					(swapz_u8 *)allocated_indexes[15],
					(swapz_u32 *)allocated_indexes[16],
					segment_count);
			if (!error)
				error = swapz_enable_segment_rotation(
					&temporary_authority,
					(swapz_u8 *)allocated_indexes[11],
					segment_count);
			if (!error)
				error = swapz_enable_segment_mapping_counts(
					&temporary_authority,
					(swapz_u32 *)allocated_indexes[4],
					segment_count);
			if (!error)
				error = swapz_enable_segment_program_counts(
					&temporary_authority,
					(swapz_u32 *)allocated_indexes[5],
					segment_count);
			if (!error)
				error = swapz_enable_segment_page_lists(
					&temporary_authority,
					(swapz_u32 *)allocated_indexes[6],
					(swapz_u32 *)allocated_indexes[7],
					(swapz_u32 *)allocated_indexes[8],
					(swapz_u32 *)allocated_indexes[9],
					segment_count,
					geometry.maximum_logical_pages);
			if (!error)
				error = swapz_enable_segment_gc_accounting(
					&temporary_authority,
					(swapz_u32 *)allocated_indexes[0],
					(swapz_u32 *)allocated_indexes[1],
					(swapz_u16 *)allocated_indexes[2],
					segment_count);
			if (!error) {
				/* These two sidecars are target-owned rather than authority-
				 * attached; touch their final elements before teardown. */
				((swapz_u32 *)allocated_indexes[3])[segment_count - 1U] = 1U;
				((swapz_u8 *)allocated_indexes[10])[segment_count - 1U] = 1U;
				if (temporary_authority.reserve_blocks !=
				    geometry.gc_reserve_blocks)
					error = -EUCLEAN;
			}
		}
		if (failure_site < allocation_count) {
			CHECK(!allocated_indexes[failure_site]);
			for (site = 0; site < allocation_count; ++site)
				if (site != failure_site)
					CHECK(allocated_indexes[site]);
		}
		CHECK(failure_site == allocation_count ?
		      allocated_all && !error :
		      !allocated_all && error == -ENOMEM);
		/* Model constructor unwind and normal teardown alike. */
		for (site = allocation_count; site > 0U; --site)
			free(allocated_indexes[site - 1U]);
	}
	return 0;
}


static int test_discard_range_prevalidation_rejects_detached_page_list_cycle(void)
{
	enum {
		test_logical_pages = 3U,
		test_physical_blocks = 4U * SWAPZ_SEGMENT_BLOCKS,
		test_segments = 4U,
	};
	const swapz_u32 none = ~(swapz_u32)0;
	struct swapz_authority test_authority;
	struct swapz_map test_maps[test_logical_pages];
	struct swapz_map maps_before[test_logical_pages];
	swapz_u16 test_live[test_physical_blocks];
	swapz_u16 live_before[test_physical_blocks];
	swapz_u8 test_classes[test_physical_blocks];
	swapz_u8 classes_before[test_physical_blocks];
	swapz_u8 test_roles[test_segments];
	swapz_u8 roles_before[test_segments];
	swapz_u32 test_mapped_pages[test_segments];
	swapz_u32 mapped_before[test_segments];
	swapz_u32 test_first_page[test_segments];
	swapz_u32 first_before[test_segments];
	swapz_u32 test_last_page[test_segments];
	swapz_u32 last_before[test_segments];
	swapz_u32 test_prev_page[test_logical_pages];
	swapz_u32 prev_before[test_logical_pages];
	swapz_u32 test_next_page[test_logical_pages];
	swapz_u32 next_before[test_logical_pages];
	swapz_u32 reserve_before;
	swapz_u32 open_segment_before;
	swapz_u32 logical;
	int error;
	int state_retained;

	CHECK(swapz_authority_init(&test_authority, test_maps, test_live,
				   test_classes, test_logical_pages,
				   test_physical_blocks) == 0);
	CHECK(swapz_enable_segment_rotation(&test_authority, test_roles,
					    test_segments) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&test_authority,
						   test_mapped_pages,
						   test_segments) == 0);
	CHECK(swapz_enable_segment_page_lists(
		      &test_authority, test_first_page, test_last_page,
		      test_prev_page, test_next_page, test_segments,
		      test_logical_pages) == 0);

	for (logical = 0; logical < test_logical_pages; ++logical) {
		test_maps[logical] = (struct swapz_map) {
			.start_block = logical,
			.generation = 1U,
			.payload_length = SWAPZ_BLOCK_BYTES,
			.extent_blocks = 1U,
			.raw = 1U,
			.valid = 1U,
		};
		test_live[logical] = 1U;
		test_classes[logical] = 1U;
	}
	test_mapped_pages[0] = test_logical_pages;

	/*
	 * Page zero is the visible singleton list. Pages one and two form a
	 * detached reciprocal cycle in the same segment. Every local neighbor check
	 * succeeds, but neither corrupt page is reachable from the authoritative
	 * segment head.
	 */
	test_first_page[0] = 0U;
	test_last_page[0] = 0U;
	test_prev_page[0] = none;
	test_next_page[0] = none;
	test_prev_page[1] = 2U;
	test_next_page[1] = 2U;
	test_prev_page[2] = 1U;
	test_next_page[2] = 1U;

	memcpy(maps_before, test_maps, sizeof(maps_before));
	memcpy(live_before, test_live, sizeof(live_before));
	memcpy(classes_before, test_classes, sizeof(classes_before));
	memcpy(roles_before, test_roles, sizeof(roles_before));
	memcpy(mapped_before, test_mapped_pages, sizeof(mapped_before));
	memcpy(first_before, test_first_page, sizeof(first_before));
	memcpy(last_before, test_last_page, sizeof(last_before));
	memcpy(prev_before, test_prev_page, sizeof(prev_before));
	memcpy(next_before, test_next_page, sizeof(next_before));
	reserve_before = test_authority.reserve_blocks;
	open_segment_before = test_authority.open_segment;

	error = swapz_prevalidate_discard_range(
		&test_authority, 0U, test_logical_pages);
	state_retained =
		!memcmp(maps_before, test_maps, sizeof(maps_before)) &&
		!memcmp(live_before, test_live, sizeof(live_before)) &&
		!memcmp(classes_before, test_classes, sizeof(classes_before)) &&
		!memcmp(roles_before, test_roles, sizeof(roles_before)) &&
		!memcmp(mapped_before, test_mapped_pages, sizeof(mapped_before)) &&
		!memcmp(first_before, test_first_page, sizeof(first_before)) &&
		!memcmp(last_before, test_last_page, sizeof(last_before)) &&
		!memcmp(prev_before, test_prev_page, sizeof(prev_before)) &&
		!memcmp(next_before, test_next_page, sizeof(next_before)) &&
		test_authority.reserve_blocks == reserve_before &&
		test_authority.open_segment == open_segment_before;
	if (error != -EUCLEAN || !state_retained) {
		fprintf(stderr,
			"%s:%d: FAIL discard page-list proof bad_page=1 segment=0 "
			"class=detached_cycle expected=head_reachable "
			"observed=detached_two_page_cycle original_error=%d "
			"retained_authority=%s lower_mutations=0 "
			"safe_disposition=%s\n",
			__FILE__, __LINE__, error, state_retained ? "yes" : "no",
			state_retained ? "fail_closed_no_publication" :
				"unexpected_authority_change");
		return 1;
	}
	return 0;
}


static int test_discard_range_prevalidation_blocks_late_sidecar_corruption(void)
{
	enum {
		test_logical_pages = 2U,
		test_physical_blocks = 4U * SWAPZ_SEGMENT_BLOCKS,
		test_segments = 4U,
	};
	struct swapz_authority test_authority;
	struct swapz_map test_maps[test_logical_pages];
	swapz_u16 test_live[test_physical_blocks];
	swapz_u8 test_classes[test_physical_blocks];
	swapz_u8 test_roles[test_segments];
	swapz_u32 test_mapped_pages[test_segments];

	CHECK(swapz_authority_init(&test_authority, test_maps, test_live,
				   test_classes, test_logical_pages,
				   test_physical_blocks) == 0);
	CHECK(swapz_enable_segment_rotation(&test_authority, test_roles,
					    test_segments) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&test_authority,
						   test_mapped_pages,
						   test_segments) == 0);
	test_maps[0] = (struct swapz_map) {
		.start_block = 0U,
		.generation = 1U,
		.payload_length = SWAPZ_BLOCK_BYTES,
		.extent_blocks = 1U,
		.raw = 1U,
		.valid = 1U,
	};
	test_maps[1] = (struct swapz_map) {
		.start_block = SWAPZ_SEGMENT_BLOCKS,
		.generation = 1U,
		.payload_length = SWAPZ_BLOCK_BYTES,
		.extent_blocks = 1U,
		.raw = 1U,
		.valid = 1U,
	};
	test_live[0] = 1U;
	test_live[SWAPZ_SEGMENT_BLOCKS] = 1U;
	test_classes[0] = 1U;
	test_classes[SWAPZ_SEGMENT_BLOCKS] = 1U;
	test_mapped_pages[0] = 1U;
	test_mapped_pages[1] = 0U; /* Corrupt only the later page's cached count. */

	CHECK(swapz_prevalidate_discard_range(
		      &test_authority, 0U, test_logical_pages) == -EUCLEAN);
	CHECK(test_maps[0].valid && test_maps[0].generation == 1U &&
	      test_maps[1].valid && test_maps[1].generation == 1U);
	CHECK(test_live[0] == 1U &&
	      test_live[SWAPZ_SEGMENT_BLOCKS] == 1U);
	CHECK(test_mapped_pages[0] == 1U && test_mapped_pages[1] == 0U);

	/*
	 * A non-authoritative physical liveness entry in a segment that this
	 * range would make dead must be refused before the first page changes.
	 * This is exactly the later swapz_discard_dead_segment() corruption
	 * check, moved into the allocation-free transactional preflight.
	 */
	test_mapped_pages[1] = 1U;
	test_live[1U] = 1U;
	CHECK(swapz_prevalidate_discard_range(
		      &test_authority, 0U, test_logical_pages) == -EUCLEAN);
	CHECK(test_maps[0].valid && test_maps[0].generation == 1U &&
	      test_maps[1].valid && test_maps[1].generation == 1U);
	CHECK(test_live[0] == 1U && test_live[1U] == 1U &&
	      test_live[SWAPZ_SEGMENT_BLOCKS] == 1U);
	CHECK(test_mapped_pages[0] == 1U && test_mapped_pages[1] == 1U);
	test_live[1U] = 0U;

	/*
	 * A false-one count plus false-zero physical liveness must not hide an
	 * authoritative survivor outside the range. Keep the survivor at a
	 * distinct physical start in the same segment so the physical-liveness
	 * scan passes and the range-wide full-map proof is the rejecting gate.
	 */
	test_maps[1].start_block = 1U;
	test_live[0] = 1U;
	test_live[1U] = 0U;
	test_live[SWAPZ_SEGMENT_BLOCKS] = 0U;
	test_classes[1U] = 1U;
	test_classes[SWAPZ_SEGMENT_BLOCKS] = 0U;
	test_mapped_pages[0] = 1U;
	CHECK(swapz_prevalidate_discard_range(&test_authority, 0U, 1U) ==
	      -EUCLEAN);
	CHECK(test_maps[0].valid && test_maps[0].generation == 1U &&
	      test_maps[1].valid && test_maps[1].generation == 1U);
	CHECK(test_live[0] == 1U && !test_live[1U] &&
	      test_mapped_pages[0] == 1U);

	/* Valid shared-extent removal decrements its physical reference exactly
	 * once per logical map; repeated DISCARD advances only generations. */
	test_maps[1].start_block = 0U;
	test_live[0] = 2U;
	test_classes[1U] = 0U;
	test_mapped_pages[0] = 2U;
	CHECK(swapz_prevalidate_discard_range(
		      &test_authority, 0U, test_logical_pages) == 0);
	CHECK(test_live[0] == 2U && test_mapped_pages[0] == 2U);
	CHECK(swapz_discard_page(&test_authority, 0U) == 0);
	CHECK(test_live[0] == 1U && test_mapped_pages[0] == 1U);
	CHECK(swapz_discard_page(&test_authority, 1U) == 0);
	CHECK(!test_live[0] && !test_mapped_pages[0]);
	CHECK(!test_maps[0].valid && test_maps[0].generation == 2U &&
	      !test_maps[1].valid && test_maps[1].generation == 2U);
	CHECK(swapz_prevalidate_discard_range(
		      &test_authority, 0U, test_logical_pages) == 0);
	CHECK(swapz_discard_page(&test_authority, 0U) == 0);
	CHECK(swapz_discard_page(&test_authority, 1U) == 0);
	CHECK(!test_live[0] && !test_mapped_pages[0]);
	CHECK(test_maps[0].generation == 3U && test_maps[1].generation == 3U);
	return 0;
}


static int test_discard_range_prevalidation_restores_shared_compressed_gc_underflow(void)
{
	enum {
		test_logical_pages = 2U,
		test_physical_blocks = 4U * SWAPZ_SEGMENT_BLOCKS,
		test_segments = 4U,
	};
	const swapz_u32 none = ~(swapz_u32)0;
	const swapz_u32 pages[test_logical_pages] = { 0U, 1U };
	struct swapz_authority test_authority;
	struct swapz_tx tx;
	struct swapz_map test_maps[test_logical_pages];
	struct swapz_map maps_before[test_logical_pages];
	swapz_u16 test_live[test_physical_blocks];
	swapz_u16 live_before[test_physical_blocks];
	swapz_u8 test_classes[test_physical_blocks];
	swapz_u8 classes_before[test_physical_blocks];
	swapz_u8 test_roles[test_segments];
	swapz_u8 roles_before[test_segments];
	swapz_u32 test_mapped_pages[test_segments];
	swapz_u32 mapped_before[test_segments];
	swapz_u32 test_first_page[test_segments];
	swapz_u32 first_before[test_segments];
	swapz_u32 test_last_page[test_segments];
	swapz_u32 last_before[test_segments];
	swapz_u32 test_prev_page[test_logical_pages];
	swapz_u32 prev_before[test_logical_pages];
	swapz_u32 test_next_page[test_logical_pages];
	swapz_u32 next_before[test_logical_pages];
	swapz_u32 test_gc_live_bytes[test_segments];
	swapz_u32 gc_live_before[test_segments];
	swapz_u32 test_gc_io_cost[test_segments];
	swapz_u32 gc_io_before[test_segments];
	swapz_u16 test_gc_min_blocks[test_segments];
	swapz_u16 gc_min_before[test_segments];
	swapz_u32 first_live_bytes;
	swapz_u32 second_live_bytes;
	swapz_u32 reserve_before;
	swapz_u32 open_segment_before;
	swapz_u32 next_block_before;
	swapz_u32 next_probe_before;
	swapz_u32 committed_before;
	swapz_u32 abandoned_before;
	int error;
	int state_retained;

	CHECK(swapz_authority_init(&test_authority, test_maps, test_live,
				   test_classes, test_logical_pages,
				   test_physical_blocks) == 0);
	CHECK(swapz_enable_segment_rotation(&test_authority, test_roles,
					    test_segments) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&test_authority,
						   test_mapped_pages,
						   test_segments) == 0);
	CHECK(swapz_enable_segment_page_lists(
		      &test_authority, test_first_page, test_last_page,
		      test_prev_page, test_next_page, test_segments,
		      test_logical_pages) == 0);
	CHECK(swapz_enable_segment_gc_accounting(
		      &test_authority, test_gc_live_bytes, test_gc_io_cost,
		      test_gc_min_blocks, test_segments) == 0);

	/*
	 * Publish a real two-record compressed extent before fault injection.
	 * This keeps payload offsets, record indexes, generation and GC costs
	 * identical to production authority state rather than hand-building maps.
	 */
	CHECK(swapz_stage(&test_authority, pages, test_logical_pages, 2U, &tx) == 0);
	CHECK(tx.start_block == 0U && tx.extent_blocks == 2U);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&test_authority, &tx, extent,
			   (swapz_u32)tx.extent_blocks * SWAPZ_BLOCK_BYTES,
			   tx.extent_blocks, 0) == 0);
	CHECK(test_maps[0].valid && !test_maps[0].raw &&
	      test_maps[0].extent_blocks == 2U &&
	      test_maps[0].start_block == 0U);
	CHECK(test_maps[1].valid && !test_maps[1].raw &&
	      test_maps[1].extent_blocks == 2U &&
	      test_maps[1].start_block == 0U);
	CHECK(test_live[0] == 2U && test_classes[0] == 2U &&
	      test_mapped_pages[0] == 2U);
	CHECK(test_first_page[0] == 0U && test_last_page[0] == 1U &&
	      test_prev_page[0] == none && test_next_page[0] == 1U &&
	      test_prev_page[1] == 0U && test_next_page[1] == none);

	/* Production page-list path: stale-low liveness must preserve siblings. */
	test_live[0] = 1U;
	{
		int prevalidate_error = swapz_prevalidate_discard_range(
			&test_authority, 0U, 1U);
		int discard_error = swapz_discard_page(&test_authority, 0U);
		int invalidation_prevented =
			prevalidate_error == -EUCLEAN &&
			discard_error == -EUCLEAN &&
			test_live[0] == 1U &&
			test_maps[0].valid && test_maps[1].valid &&
			test_maps[0].generation == 1U &&
			test_maps[1].generation == 1U;

		if (!invalidation_prevented) {
			fprintf(stderr,
				"%s:%d: FAIL range=[0,1) expected_generation=1 "
				"expected_references=2 observed_references=%u "
				"conflict=shared_extent_stale_low_page_list "
				"original_errnos=prevalidate:%d,discard:%d "
				"invalidation_prevented=%s\n",
				__FILE__, __LINE__, (unsigned int)test_live[0],
				prevalidate_error, discard_error,
				invalidation_prevented ? "yes" : "no");
			return 1;
		}
	}
	test_live[0] = 2U;

	first_live_bytes = test_maps[0].payload_length +
			   sizeof(struct swapz_record);
	second_live_bytes = test_maps[1].payload_length +
			    sizeof(struct swapz_record);
	CHECK(test_gc_live_bytes[0] == first_live_bytes + second_live_bytes);

	/*
	 * The score is still sufficient for page zero, then becomes one byte
	 * short for page one after the first modeled decrement. This specifically
	 * exercises cumulative shared-extent rollback before any publication.
	 */
	test_gc_live_bytes[0]--;

	memcpy(maps_before, test_maps, sizeof(maps_before));
	memcpy(live_before, test_live, sizeof(live_before));
	memcpy(classes_before, test_classes, sizeof(classes_before));
	memcpy(roles_before, test_roles, sizeof(roles_before));
	memcpy(mapped_before, test_mapped_pages, sizeof(mapped_before));
	memcpy(first_before, test_first_page, sizeof(first_before));
	memcpy(last_before, test_last_page, sizeof(last_before));
	memcpy(prev_before, test_prev_page, sizeof(prev_before));
	memcpy(next_before, test_next_page, sizeof(next_before));
	memcpy(gc_live_before, test_gc_live_bytes, sizeof(gc_live_before));
	memcpy(gc_io_before, test_gc_io_cost, sizeof(gc_io_before));
	memcpy(gc_min_before, test_gc_min_blocks, sizeof(gc_min_before));
	reserve_before = test_authority.reserve_blocks;
	open_segment_before = test_authority.open_segment;
	next_block_before = test_authority.next_block;
	next_probe_before = test_authority.next_segment_probe;
	committed_before = test_authority.committed_blocks;
	abandoned_before = test_authority.abandoned_blocks;

	error = swapz_prevalidate_discard_range(
		&test_authority, 0U, test_logical_pages);
	state_retained =
		!memcmp(maps_before, test_maps, sizeof(maps_before)) &&
		!memcmp(live_before, test_live, sizeof(live_before)) &&
		!memcmp(classes_before, test_classes, sizeof(classes_before)) &&
		!memcmp(roles_before, test_roles, sizeof(roles_before)) &&
		!memcmp(mapped_before, test_mapped_pages, sizeof(mapped_before)) &&
		!memcmp(first_before, test_first_page, sizeof(first_before)) &&
		!memcmp(last_before, test_last_page, sizeof(last_before)) &&
		!memcmp(prev_before, test_prev_page, sizeof(prev_before)) &&
		!memcmp(next_before, test_next_page, sizeof(next_before)) &&
		!memcmp(gc_live_before, test_gc_live_bytes,
			sizeof(gc_live_before)) &&
		!memcmp(gc_io_before, test_gc_io_cost, sizeof(gc_io_before)) &&
		!memcmp(gc_min_before, test_gc_min_blocks,
			sizeof(gc_min_before)) &&
		test_authority.reserve_blocks == reserve_before &&
		test_authority.open_segment == open_segment_before &&
		test_authority.next_block == next_block_before &&
		test_authority.next_segment_probe == next_probe_before &&
		test_authority.committed_blocks == committed_before &&
		test_authority.abandoned_blocks == abandoned_before;
	if (error != -EUCLEAN || !state_retained) {
		fprintf(stderr,
			"%s:%d: FAIL discard cumulative GC proof bad_page=1 "
			"segment=0 expected_class=gc_score_covers_shared_reference "
			"observed_class=gc_live_bytes_short_by_one "
			"expected_bytes=%u observed_bytes=%u original_error=%d "
			"retained_authority=%s lower_mutations=0 "
			"safe_disposition=%s\n",
			__FILE__, __LINE__, second_live_bytes,
			second_live_bytes - 1U, error,
			state_retained ? "yes" : "no",
			state_retained ? "fail_closed_no_publication" :
				"unexpected_authority_change");
		return 1;
	}

	/*
	 * A positive stale score is the complementary cumulative-accounting
	 * corruption. The range would remove both real shared references, so an
	 * exact GC score must reach zero before any logical generation can move.
	 */
	test_gc_live_bytes[0] += 2U;
	memcpy(gc_live_before, test_gc_live_bytes, sizeof(gc_live_before));
	error = swapz_prevalidate_discard_range(
		&test_authority, 0U, test_logical_pages);
	state_retained =
		!memcmp(maps_before, test_maps, sizeof(maps_before)) &&
		!memcmp(live_before, test_live, sizeof(live_before)) &&
		!memcmp(classes_before, test_classes, sizeof(classes_before)) &&
		!memcmp(roles_before, test_roles, sizeof(roles_before)) &&
		!memcmp(mapped_before, test_mapped_pages, sizeof(mapped_before)) &&
		!memcmp(first_before, test_first_page, sizeof(first_before)) &&
		!memcmp(last_before, test_last_page, sizeof(last_before)) &&
		!memcmp(prev_before, test_prev_page, sizeof(prev_before)) &&
		!memcmp(next_before, test_next_page, sizeof(next_before)) &&
		!memcmp(gc_live_before, test_gc_live_bytes,
			sizeof(gc_live_before)) &&
		!memcmp(gc_io_before, test_gc_io_cost, sizeof(gc_io_before)) &&
		!memcmp(gc_min_before, test_gc_min_blocks,
			sizeof(gc_min_before)) &&
		test_authority.reserve_blocks == reserve_before &&
		test_authority.open_segment == open_segment_before &&
		test_authority.next_block == next_block_before &&
		test_authority.next_segment_probe == next_probe_before &&
		test_authority.committed_blocks == committed_before &&
		test_authority.abandoned_blocks == abandoned_before;
	if (error != -EUCLEAN || !state_retained) {
		unsigned int invalidations =
			(test_maps[0].valid ? 0U : 1U) +
			(test_maps[1].valid ? 0U : 1U);

		fprintf(stderr,
			"%s:%d: FAIL discard stale GC proof range=[0,2) "
			"expected_generations=%u,%u observed_generations=%u,%u "
			"expected_shared_refs=%u observed_shared_refs=%u "
			"expected_mapped=%u observed_mapped=%u "
			"expected_gc_live=%u observed_gc_live=%u "
			"conflict=gc_live_bytes_surplus first_errno=%d "
			"invalidations=%u retained_authority=%s lower_mutations=0\n",
			__FILE__, __LINE__, maps_before[0].generation,
			maps_before[1].generation, test_maps[0].generation,
			test_maps[1].generation, (unsigned int)live_before[0],
			(unsigned int)test_live[0], mapped_before[0],
			test_mapped_pages[0], first_live_bytes + second_live_bytes,
			gc_live_before[0], error, invalidations,
			state_retained ? "yes" : "no");
		return 1;
	}
	return 0;
}

static int test_shared_extent_stale_low_reference_fails_closed(void)
{
	const swapz_u32 shared_pages[] = { 0U, 1U };
	const swapz_u32 replacement_page = 0U;
	struct swapz_tx shared_tx, replacement_tx;
	struct swapz_map shared_before[2];
	swapz_u32 shared_start;
	int scenario;

	for (scenario = 0; scenario < 3; ++scenario) {
		int error, prevalidate_error = 0;
		int invalidation_prevented;

		CHECK(init() == 0);
		CHECK(swapz_stage(&authority, shared_pages, 2U, 2U,
				  &shared_tx) == 0);
		CHECK(encode(&shared_tx) == 0);
		CHECK(swapz_finish(&authority, &shared_tx, extent,
				   2U * SWAPZ_BLOCK_BYTES, 2U, 0) == 0);
		shared_start = maps[0].start_block;
		CHECK(shared_start == maps[1].start_block &&
		      maps[0].shared_extent && maps[1].shared_extent &&
		      live[shared_start] == 2U);
		shared_before[0] = maps[0];
		shared_before[1] = maps[1];

		/* Fault injection: two authoritative siblings, one cached reference. */
		live[shared_start] = 1U;
		if (scenario == 0) {
			prevalidate_error = swapz_prevalidate_discard_range(
				&authority, 0U, 1U);
			error = swapz_discard_page(&authority, 0U);
		} else {
			CHECK(swapz_stage(&authority, &replacement_page, 1U, 1U,
					  &replacement_tx) == 0);
			if (scenario == 1) {
				CHECK(encode(&replacement_tx) == 0);
				error = swapz_finish(
					&authority, &replacement_tx, extent,
					SWAPZ_BLOCK_BYTES, 1U, 0);
			} else {
				memset(extent, 0x6d, SWAPZ_BLOCK_BYTES);
				error = swapz_finish_raw(
					&authority, &replacement_tx, extent,
					1U, 0);
			}
		}
		invalidation_prevented =
			(scenario != 0 || prevalidate_error == -EUCLEAN) &&
			error == -EUCLEAN &&
			!memcmp(&maps[0], &shared_before[0], sizeof(maps[0])) &&
			!memcmp(&maps[1], &shared_before[1], sizeof(maps[1])) &&
			live[shared_start] == 1U &&
			classes[shared_start] == shared_before[0].extent_blocks &&
			(scenario == 0 ||
			 (!authority.in_flight &&
			  !live[replacement_tx.start_block] &&
			  !classes[replacement_tx.start_block]));
		if (!invalidation_prevented) {
			fprintf(stderr,
				"%s:%d: FAIL range=[0,1) "
				"expected_generation=%u expected_references=2 "
				"observed_references=%u "
				"conflict=shared_extent_stale_low_reference "
				"operation=%s original_errnos=prevalidate:%d,"
				"operation:%d invalidation_prevented=%s\n",
				__FILE__, __LINE__, shared_before[0].generation,
				(unsigned int)live[shared_start],
				scenario == 0 ? "discard" :
				scenario == 1 ? "compressed_cow" : "raw_cow",
				prevalidate_error, error,
				invalidation_prevented ? "yes" : "no");
			return 1;
		}
	}
	return 0;
}

/*
 * Model a multi-page DISCARD whose first page is healthy, the second is
 * malformed, and a third authoritative map must survive outside the range.
 * The preflight's speculative first-page refcount decrement must roll back.
 */
static int test_discard_range_bad_tail_keeps_unrelated_authority(void)
{
	enum {
		logical_pages = 3U,
		physical_blocks = 4U * SWAPZ_SEGMENT_BLOCKS,
	};
	struct swapz_authority test_authority;
	struct swapz_map test_maps[logical_pages];
	struct swapz_map maps_before[logical_pages];
	swapz_u16 test_live[physical_blocks];
	swapz_u16 live_before[physical_blocks];
	swapz_u8 test_classes[physical_blocks];
	swapz_u8 classes_before[physical_blocks];
	int fault;

	for (fault = 0; fault < 4; ++fault) {
		swapz_u32 invalid_start = fault == 3 ? 1U : fault == 2 ?
			physical_blocks - 1U :
			fault == 1 ? 1U : SWAPZ_SEGMENT_BLOCKS - 1U;
		swapz_u8 invalid_blocks = fault == 1 ? 1U : 2U;
		int error, expected_error, invalidation_prevented;

		CHECK(swapz_authority_init(&test_authority, test_maps,
					   test_live, test_classes,
					   logical_pages, physical_blocks) == 0);
		test_maps[0] = (struct swapz_map) {
			.start_block = 0U, .generation = 1U,
			.payload_length = SWAPZ_BLOCK_BYTES,
			.extent_blocks = 1U, .raw = 1U, .valid = 1U,
		};
		test_maps[1] = (struct swapz_map) {
			.start_block = invalid_start,
			.generation = fault == 1 ? ~(swapz_u32)0 : 1U,
			.payload_length = fault == 3 ? SWAPZ_BLOCK_BYTES : 128U,
			.extent_blocks = invalid_blocks,
			.raw = fault == 3, .valid = 1U,
		};
		test_maps[2] = (struct swapz_map) {
			.start_block = SWAPZ_SEGMENT_BLOCKS,
			.generation = 4U, .payload_length = SWAPZ_BLOCK_BYTES,
			.extent_blocks = 1U, .raw = 1U, .valid = 1U,
		};
		test_live[0] = 1U;
		test_classes[0] = 1U;
		test_live[invalid_start] = 1U;
		test_classes[invalid_start] = invalid_blocks;
		test_live[SWAPZ_SEGMENT_BLOCKS] = 1U;
		test_classes[SWAPZ_SEGMENT_BLOCKS] = 1U;

		memcpy(maps_before, test_maps, sizeof(maps_before));
		memcpy(live_before, test_live, sizeof(live_before));
		memcpy(classes_before, test_classes, sizeof(classes_before));
		error = swapz_prevalidate_discard_range(
			&test_authority, 0U, 2U);
		expected_error = fault == 1 ? -EOVERFLOW : -EUCLEAN;
		invalidation_prevented =
			!memcmp(maps_before, test_maps, sizeof(maps_before)) &&
			!memcmp(live_before, test_live, sizeof(live_before)) &&
			!memcmp(classes_before, test_classes,
				sizeof(classes_before));
		if (error != expected_error || !invalidation_prevented) {
			fprintf(stderr,
				"%s:%d: FAIL range=[0,2) survivor=outside_range "
				"expected_generation=1 expected_references=1 "
				"conflict=%s original_errno=%d "
				"invalidation_prevented=%s\n",
				__FILE__, __LINE__,
				fault == 1 ? "generation_overflow" :
				fault == 2 ? "physical_capacity_overrun" :
				fault == 3 ? "raw_multiblock_extent" :
					     "cross_segment_extent",
				error, invalidation_prevented ? "yes" : "no");
			return 1;
		}
	}
	return 0;
}

/*
 * An asynchronously completed compressed COW must not publish over an old
 * map whose physical span was corrupted after its earlier publication.
 */
static int test_compressed_finish_rejects_corrupt_source_geometry(void)
{
	const swapz_u32 logical_page = 9U;
	const swapz_u32 invalid_start = SWAPZ_SEGMENT_BLOCKS - 1U;
	struct swapz_tx transaction;
	struct swapz_map original;
	int error, invalidation_prevented;

	CHECK(init() == 0);
	CHECK(swapz_stage(&authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	CHECK(encode(&transaction) == 0);
	CHECK(swapz_finish(&authority, &transaction, extent,
			   SWAPZ_BLOCK_BYTES, 1U, 0) == 0);
	CHECK(maps[logical_page].valid && !maps[logical_page].raw);
	live[maps[logical_page].start_block] = 0U;
	classes[maps[logical_page].start_block] = 0U;
	maps[logical_page].start_block = invalid_start;
	maps[logical_page].extent_blocks = 2U;
	live[invalid_start] = 1U;
	classes[invalid_start] = 2U;
	original = maps[logical_page];

	CHECK(swapz_stage(&authority, &logical_page, 1U, 1U,
			  &transaction) == 0);
	CHECK(encode(&transaction) == 0);
	error = swapz_finish(&authority, &transaction, extent,
			     SWAPZ_BLOCK_BYTES, 1U, 0);
	invalidation_prevented =
		!memcmp(&maps[logical_page], &original, sizeof(original)) &&
		live[invalid_start] == 1U && classes[invalid_start] == 2U &&
		!live[transaction.start_block] &&
		!classes[transaction.start_block] &&
		!authority.in_flight && authority.abandoned_blocks == 1U;
	if (error != -EUCLEAN || !invalidation_prevented) {
		fprintf(stderr,
			"%s:%d: FAIL range=[9,10) "
			"expected_generation=%u expected_references=1 "
			"conflict=compressed_old_extent_cross_segment "
			"original_errno=%d invalidation_prevented=%s\n",
			__FILE__, __LINE__, original.generation, error,
			invalidation_prevented ? "yes" : "no");
		return 1;
	}
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_initial_rejects_unsafe_capacity() == 0); passed++;
	CHECK(test_capacity_preflight_segment_sweep() == 0); passed++;
	CHECK(test_selected_card_geometry_and_memory_scaling() == 0); passed++;
	CHECK(test_small_index_failure_and_repeated_lifecycle() == 0); passed++;
	CHECK(test_16gib_fixture_maximum_capacity() == 0); passed++;
	CHECK(test_maximum_capacity_single_block_gc_reclaim() == 0); passed++;
	CHECK(test_maximum_capacity_raw_cow_and_gc_progress() == 0); passed++;
	CHECK(test_full_publish_and_authoritative_reads() == 0); passed++;
	CHECK(test_peeked_authoritative_read_rechecks_payload_and_sequence() == 0); passed++;
	CHECK(test_inflight_interleavings_preserve_authority() == 0); passed++;
	CHECK(test_torn_write_no_old_mapping_invalidation() == 0); passed++;
	CHECK(test_overwrite_generation_and_liveness() == 0); passed++;
	CHECK(test_last_corrupt_sibling_prevents_all_publication() == 0); passed++;
	CHECK(test_header_corruption_and_wrong_sequence() == 0); passed++;
	CHECK(test_generation_overflow_and_duplicate_rejections() == 0); passed++;
	CHECK(test_allocator_reserve_exhaustion() == 0); passed++;
	CHECK(test_packed_append_only_segment_edges() == 0); passed++;
	CHECK(test_batch_tail_abort_preserves_older_snapshot() == 0); passed++;
	CHECK(test_compact_extent_sequence_delta_bound() == 0); passed++;
	CHECK(test_compact_extent_sequence_overflow_fails_closed() == 0); passed++;
	CHECK(test_short_write_always_quarantines() == 0); passed++;
	CHECK(test_old_liveness_corruption_fail_closed() == 0); passed++;
	CHECK(test_discard_range_prevalidation_rejects_detached_page_list_cycle() == 0); passed++;
	CHECK(test_discard_range_prevalidation_blocks_late_sidecar_corruption() == 0); passed++;
	CHECK(test_shared_extent_stale_low_reference_fails_closed() == 0); passed++;
	CHECK(test_discard_range_bad_tail_keeps_unrelated_authority() == 0); passed++;
	CHECK(test_compressed_finish_rejects_corrupt_source_geometry() == 0); passed++;
	CHECK(test_discard_range_prevalidation_restores_shared_compressed_gc_underflow() == 0); passed++;
	printf("SWAPZ_EXACT_AUTHORITY_TESTS_PASS=%d\n", passed);
	return 0;
}
