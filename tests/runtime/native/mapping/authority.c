// SPDX-License-Identifier: GPL-2.0-only
/*
 * The exact src/kernel/{codec,authority}.c are compiled into this
 * userspace executable. Covers authority publication and torn-write rollback.
 */
#include <errno.h>
#include <stdint.h>
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
static swapz_u8 extent[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 previous_extent[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 content[2072];

static int init(void)
{
	return swapz_authority_init(&authority, maps, live, classes, 64, 2048);
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

static int test_initial_rejects_unsafe_capacity(void)
{
	struct swapz_authority a;

	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 512) == -EINVAL);
	CHECK(swapz_authority_init(&a, maps, live, classes, 500, 768) == -ENOSPC);
	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 769) == -EINVAL);
	CHECK(swapz_authority_init(&a, maps, live, classes, 64, 768) == 0);
	CHECK(a.reserve_blocks == 512);
	CHECK(a.next_block == 0);
	return 0;
}

static int test_designated_partition_maximum_capacity(void)
{
	const swapz_u64 partition_bytes = 17179869184ULL;
	const swapz_u32 expected_physical_blocks = 4194048U;
	const swapz_u32 expected_logical_pages = 3727872U;
	const swapz_u32 expected_reserve_blocks = 465984U;
	const swapz_u32 expected_segments = 16383U;
	const swapz_u64 expected_index_bytes = 120470752ULL;
	const swapz_u32 total_blocks =
		(swapz_u32)(partition_bytes / SWAPZ_BLOCK_BYTES);
	const swapz_u32 physical_blocks =
		((total_blocks - 1U) / SWAPZ_SEGMENT_BLOCKS) *
		SWAPZ_SEGMENT_BLOCKS;
	const swapz_u32 segment_count =
		physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	struct swapz_authority a;
	struct swapz_map *large_maps;
	swapz_u16 *live_records;
	swapz_u8 *extent_classes, *segment_roles, *segment_trimmed;
	swapz_u32 *gc_scores, *gc_io_scores, *gc_segment_evictions;
	swapz_u32 *segment_mapped_pages, *segment_program_counts;
	swapz_u32 *segment_first_page, *segment_last_page;
	swapz_u32 *page_prev_in_segment, *page_next_in_segment;
	swapz_u16 *gc_min_live_blocks;
	swapz_u64 index_bytes;

	CHECK(physical_blocks == expected_physical_blocks);
	CHECK(segment_count == expected_segments);
	CHECK((swapz_u64)expected_logical_pages * SWAPZ_BLOCK_BYTES ==
	      15269363712ULL);
	CHECK((swapz_u64)expected_logical_pages *
	      (sizeof(struct swapz_map) + 2U * sizeof(swapz_u32)) +
	      (swapz_u64)physical_blocks *
	      (sizeof(swapz_u16) + sizeof(swapz_u8)) +
	      (swapz_u64)segment_count *
	      (7U * sizeof(swapz_u32) + sizeof(swapz_u16) +
	       2U * sizeof(swapz_u8)) == expected_index_bytes);

	/* Allocate every capacity-dependent authority/index array used by ctr. */
	large_maps = calloc((size_t)expected_logical_pages + 1U,
			    sizeof(*large_maps));
	live_records = calloc(physical_blocks, sizeof(*live_records));
	extent_classes = calloc(physical_blocks, sizeof(*extent_classes));
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
	CHECK(large_maps && live_records && extent_classes && gc_scores &&
	      gc_io_scores && gc_min_live_blocks && gc_segment_evictions &&
	      segment_mapped_pages && segment_program_counts &&
	      segment_first_page && segment_last_page && page_prev_in_segment &&
	      page_next_in_segment && segment_trimmed && segment_roles);

	/* The first page beyond the computed maximum must fail before admission. */
	CHECK(swapz_authority_init(&a, large_maps, live_records, extent_classes,
				   expected_logical_pages + 1U,
				   physical_blocks) == -ENOSPC);
	CHECK(swapz_authority_init(&a, large_maps, live_records, extent_classes,
				   expected_logical_pages,
				   physical_blocks) == 0);
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
		(sizeof(*live_records) + sizeof(*extent_classes)) +
		(swapz_u64)segment_count *
		(7U * sizeof(swapz_u32) + sizeof(swapz_u16) +
		 2U * sizeof(swapz_u8));
	CHECK(index_bytes == expected_index_bytes);

	free(segment_roles);
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
		      observed.extent_blocks == 4 && observed.sequence == 1);
		CHECK(swapz_peek(extent, 16384, observed.record_index, &decoded) == 0);
		CHECK(swapz_read_authoritative_peeked(&authority, index, &observed,
					    extent, 16384, &decoded, &payload) == 0);
		CHECK(decoded.logical_page == index && decoded.generation == 1);
		CHECK(observed.payload_offset == decoded.payload_offset);
		CHECK(payload[0] == index + 1 && payload[2071] == index + 1);
		if (index == 0) {
			struct swapz_map forged = observed;

			forged.payload_offset++;
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
	extent[8] ^= 0x40; /* sequence bytes are rechecked after the peek */
	CHECK(swapz_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == -EUCLEAN);
	extent[8] ^= 0x40;
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
	return swapz_authority_init(a, maps, live, classes, 64, physical_blocks);
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
	CHECK(init_append_only_authority(&a, 768) == 0);
	CHECK(advance_append_only_cursor(&a, 252) == 0);
	CHECK(swapz_stage(&a, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 252 && a.next_block == 256);
	CHECK(!a.alignment_hole_blocks_foreground &&
	      !a.segment_tail_waste_blocks_foreground);
	CHECK(swapz_abort(&a, &tx) == 0);

	/* A skipped extent may not enter the reserved suffix or mutate state. */
	CHECK(init_append_only_authority(&a, 768) == 0);
	CHECK(advance_append_only_cursor(&a, 255) == 0);
	next_sequence = a.next_sequence;
	CHECK(swapz_stage(&a, pages, 1, 2, &tx) == -ENOSPC);
	CHECK(a.next_block == 255 && a.next_sequence == next_sequence &&
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

int main(void)
{
	int passed = 0;

	CHECK(test_initial_rejects_unsafe_capacity() == 0); passed++;
	CHECK(test_designated_partition_maximum_capacity() == 0); passed++;
	CHECK(test_full_publish_and_authoritative_reads() == 0); passed++;
	CHECK(test_peeked_authoritative_read_rechecks_payload_and_sequence() == 0); passed++;
	CHECK(test_torn_write_no_old_mapping_invalidation() == 0); passed++;
	CHECK(test_overwrite_generation_and_liveness() == 0); passed++;
	CHECK(test_last_corrupt_sibling_prevents_all_publication() == 0); passed++;
	CHECK(test_header_corruption_and_wrong_sequence() == 0); passed++;
	CHECK(test_generation_overflow_and_duplicate_rejections() == 0); passed++;
	CHECK(test_allocator_reserve_exhaustion() == 0); passed++;
	CHECK(test_packed_append_only_segment_edges() == 0); passed++;
	CHECK(test_batch_tail_abort_preserves_older_snapshot() == 0); passed++;
	CHECK(test_short_write_always_quarantines() == 0); passed++;
	CHECK(test_old_liveness_corruption_fail_closed() == 0); passed++;
	printf("SWAPZ_EXACT_AUTHORITY_TESTS_PASS=%d\n", passed);
	return 0;
}
