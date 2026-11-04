// SPDX-License-Identifier: GPL-2.0-only
/*
 * Worst-case RAW allocator/GC occupancy on exact production authority C.
 *
 * Geometry deliberately leaves one complete foreground segment beyond logical
 * RAW occupancy, plus the two rotating reserve segments. This is the minimum
 * current allocator shape that can bootstrap copy-on-write after an all-live
 * fill without borrowing a GC reserve for ordinary foreground publication.
 */
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define PHYSICAL_SEGMENTS 8U
#define FOREGROUND_SEGMENTS 6U
#define LOGICAL_SEGMENTS 5U
#define PHYSICAL_BLOCKS (PHYSICAL_SEGMENTS * SWAPZ_SEGMENT_BLOCKS)
#define LOGICAL_PAGES (LOGICAL_SEGMENTS * SWAPZ_SEGMENT_BLOCKS)

static struct swapz_authority a;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live[PHYSICAL_BLOCKS];
static swapz_u8 classes[PHYSICAL_BLOCKS];
static swapz_u8 roles[PHYSICAL_SEGMENTS];
static swapz_u32 segment_maps[PHYSICAL_SEGMENTS];
static swapz_u32 program_counts[PHYSICAL_SEGMENTS];
static swapz_u32 versions[LOGICAL_PAGES];
static swapz_u8 media[PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES];
static swapz_u8 page_bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 expected_bytes[SWAPZ_BLOCK_BYTES];
static unsigned long long foreground_writes;
static unsigned long long gc_reads;
static unsigned long long gc_writes;
static unsigned long long gc_bytes_relocated;

static void make_raw_page(swapz_u32 logical, swapz_u32 version, swapz_u8 *out)
{
	swapz_u32 state = 0x9e3779b9U ^
		(logical * 0x85ebca6bU) ^ (version * 0xc2b2ae35U);
	swapz_u32 offset;

	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; offset += 4U) {
		state ^= state << 13;
		state ^= state >> 17;
		state ^= state << 5;
		out[offset] = (swapz_u8)state;
		out[offset + 1U] = (swapz_u8)(state >> 8);
		out[offset + 2U] = (swapz_u8)(state >> 16);
		out[offset + 3U] = (swapz_u8)(state >> 24);
	}
}

static int setup(void)
{
	int error;

	error = swapz_authority_init(&a, maps, live, classes,
				    LOGICAL_PAGES, PHYSICAL_BLOCKS);
	if (error)
		return error;
	a.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(&a, roles, PHYSICAL_SEGMENTS);
	if (error)
		return error;
	error = swapz_enable_segment_mapping_counts(
		&a, segment_maps, PHYSICAL_SEGMENTS);
	if (error)
		return error;
	error = swapz_enable_segment_program_counts(&a, program_counts,
						     PHYSICAL_SEGMENTS);
	if (error)
		return error;
	memset(media, 0, sizeof(media));
	memset(versions, 0, sizeof(versions));
	foreground_writes = 0;
	gc_reads = 0;
	gc_writes = 0;
	gc_bytes_relocated = 0;
	return 0;
}

static int write_page(swapz_u32 logical, swapz_u32 version)
{
	struct swapz_tx tx;
	int error;

	make_raw_page(logical, version, page_bytes);
	error = swapz_stage(&a, &logical, 1, 1, &tx);
	if (error)
		return error;
	if (tx.start_block >= PHYSICAL_BLOCKS) {
		(void)swapz_finish_raw(&a, &tx, page_bytes, 0, -ERANGE);
		return -ERANGE;
	}
	memcpy(media + (size_t)tx.start_block * SWAPZ_BLOCK_BYTES,
	       page_bytes, SWAPZ_BLOCK_BYTES);
	error = swapz_finish_raw(&a, &tx, page_bytes, 1, 0);
	if (!error) {
		versions[logical] = version;
		foreground_writes++;
	}
	return error;
}

static int verify_all_pages(void)
{
	swapz_u32 logical;

	for (logical = 0; logical < LOGICAL_PAGES; ++logical) {
		const struct swapz_map *map = &maps[logical];
		const swapz_u8 *stored;

		if (!map->valid || !map->raw || map->extent_blocks != 1 ||
		    map->start_block >= PHYSICAL_BLOCKS)
			return -EUCLEAN;
		stored = media + (size_t)map->start_block * SWAPZ_BLOCK_BYTES;
		make_raw_page(logical, versions[logical], expected_bytes);
		if (memcmp(stored, expected_bytes, SWAPZ_BLOCK_BYTES) ||
		    swapz_verify_raw(&a, logical, stored))
			return -EBADMSG;
	}
	return 0;
}

static int relocate_segment_pages(swapz_u32 victim)
{
	swapz_u32 logical;
	int error;

	error = swapz_gc_begin_rotation(&a, victim);
	if (error)
		return error;
	for (logical = 0; logical < LOGICAL_PAGES; ++logical) {
		struct swapz_tx tx;
		swapz_u32 source;

		if (!maps[logical].valid ||
		    maps[logical].start_block / SWAPZ_SEGMENT_BLOCKS != victim)
			continue;
		source = maps[logical].start_block;
		memcpy(page_bytes,
		       media + (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		if (swapz_verify_raw(&a, logical, page_bytes))
			return -EBADMSG;
		gc_reads++;
		error = swapz_stage(&a, &logical, 1, 1, &tx);
		if (error)
			return error;
		memcpy(media + (size_t)tx.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		error = swapz_finish_raw(&a, &tx, page_bytes, 1, 0);
		if (error)
			return error;
		gc_writes++;
		gc_bytes_relocated += SWAPZ_BLOCK_BYTES;
	}
	return 0;
}

static int relocate_segment(swapz_u32 victim)
{
	int error = relocate_segment_pages(victim);

	return error ? error : swapz_gc_commit_rotation(&a, victim);
}

static unsigned int reserve_segments(void)
{
	unsigned int count = 0;
	swapz_u32 segment;

	for (segment = 0; segment < PHYSICAL_SEGMENTS; ++segment)
		if (!roles[segment])
			count++;
	return count;
}

static int fill_all_pages(swapz_u32 version)
{
	swapz_u32 logical;

	for (logical = 0; logical < LOGICAL_PAGES; ++logical) {
		int error = write_page(logical, version);

		if (error)
			return error;
	}
	return 0;
}

static int test_repeated_raw_reclaim_and_reuse(void)
{
	swapz_u32 version;

	CHECK(setup() == 0);
	CHECK(reserve_segments() == PHYSICAL_SEGMENTS - FOREGROUND_SEGMENTS);
	CHECK(fill_all_pages(1) == 0);
	CHECK(a.open_segment == LOGICAL_SEGMENTS - 1U);
	CHECK(a.next_block == LOGICAL_PAGES);
	CHECK(segment_maps[LOGICAL_SEGMENTS] == 0);
	CHECK(verify_all_pages() == 0);

	/* Six complete rewrite rounds cycle logical page zero through every
	 * foreground segment and back to physical block zero. Every round starts
	 * with one wholly free foreground segment, then reclaims the segment made
	 * dead by the preceding 256 RAW overwrites. */
	for (version = 2; version <= 7; ++version) {
		CHECK(fill_all_pages(version) == 0);
		CHECK(verify_all_pages() == 0);
		CHECK(reserve_segments() ==
		      PHYSICAL_SEGMENTS - FOREGROUND_SEGMENTS);
	}
	CHECK(maps[0].start_block == 0);
	CHECK(a.recycled_dead_segments >= 29);
	return 0;
}

static int test_fragmented_raw_gc_restores_progress(void)
{
	struct swapz_tx tx;
	swapz_u32 i;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1) == 0);

	/* Consume the one foreground spare with 256 overwrites distributed across
	 * all five live source segments. No source is wholly dead, so ordinary
	 * allocation must stop until GC compacts one fragmented victim. */
	for (i = 0; i < SWAPZ_SEGMENT_BLOCKS; ++i) {
		swapz_u32 source_segment = i % LOGICAL_SEGMENTS;
		swapz_u32 source_offset = i / LOGICAL_SEGMENTS;
		swapz_u32 logical =
			source_segment * SWAPZ_SEGMENT_BLOCKS + source_offset;

		CHECK(write_page(logical, 2) == 0);
	}
	CHECK(a.open_segment == FOREGROUND_SEGMENTS - 1U);
	CHECK(a.next_block == FOREGROUND_SEGMENTS * SWAPZ_SEGMENT_BLOCKS);
	CHECK(segment_maps[0] == 204);
	CHECK(segment_maps[1] == 205);
	i = 200;
	CHECK(swapz_stage(&a, &i, 1, 1, &tx) == -ENOSPC);
	CHECK(!a.in_flight);
	CHECK(verify_all_pages() == 0);

	/* Victim0 has 204 live RAW pages. Moving exactly those pages into reserve6
	 * leaves 52 foreground blocks; role exchange restores allocation progress
	 * while preserving two reserve-role segments. */
	CHECK(relocate_segment(0) == 0);
	CHECK(roles[0] == 0 && roles[6] == 1);
	CHECK(a.open_segment == 6);
	CHECK(a.next_block == 6U * SWAPZ_SEGMENT_BLOCKS + 204U);
	CHECK(reserve_segments() == 2);
	CHECK(verify_all_pages() == 0);

	/* Fill those 52 blocks from victim1. A second ENOSPC must compact victim1
	 * into the other reserve, proving reserve rotation rather than permanent
	 * consumption of the first GC destination. */
	for (i = 100; i < 152; ++i)
		CHECK(write_page(SWAPZ_SEGMENT_BLOCKS + i, 3) == 0);
	CHECK(segment_maps[1] == 153);
	i = SWAPZ_SEGMENT_BLOCKS + 200U;
	CHECK(swapz_stage(&a, &i, 1, 1, &tx) == -ENOSPC);
	CHECK(!a.in_flight);
	CHECK(relocate_segment(1) == 0);
	CHECK(roles[1] == 0 && roles[7] == 1);
	CHECK(a.open_segment == 7);
	CHECK(a.next_block == 7U * SWAPZ_SEGMENT_BLOCKS + 153U);
	CHECK(reserve_segments() == 2);
	CHECK(write_page(2U * SWAPZ_SEGMENT_BLOCKS + 100U, 3) == 0);
	CHECK(verify_all_pages() == 0);
	CHECK(gc_reads == 357 && gc_writes == 357);
	CHECK(gc_bytes_relocated == 357ULL * SWAPZ_BLOCK_BYTES);
	return 0;
}

/*
 * Keep every other foreground segment partially LIVE while consuming the
 * active segment. That prevents opportunistic whole-dead reuse and forces
 * repeated GC reserve exchanges at exactly worst-case RAW occupancy.
 */
static int overwrite_outside_open(swapz_u32 *next_source_segment)
{
	swapz_u32 offset;

	/*
	 * Walk PHYSICAL source segments, not adjacent logical page indices.
	 * Logical indices are initially clustered by source; a sequential
	 * logical sweep would empty one victim before touching the others and
	 * exercise only one survivor per rotation instead of high-live GC.
	 */
	for (offset = 0; offset < PHYSICAL_SEGMENTS; ++offset) {
		swapz_u32 segment =
			(*next_source_segment + offset) % PHYSICAL_SEGMENTS;
		swapz_u32 logical;

		if (!roles[segment] || segment == a.open_segment ||
		    segment_maps[segment] < 2U)
			continue;
		for (logical = 0; logical < LOGICAL_PAGES; ++logical) {
			swapz_u32 source;

			if (!maps[logical].valid ||
			    maps[logical].start_block >= PHYSICAL_BLOCKS)
				return -EUCLEAN;
			source = maps[logical].start_block / SWAPZ_SEGMENT_BLOCKS;
			if (source == segment) {
				int error = write_page(logical, versions[logical] + 1U);

				if (!error)
					*next_source_segment =
						(segment + 1U) % PHYSICAL_SEGMENTS;
				return error;
			}
		}
		return -EUCLEAN;
	}
	return -EUCLEAN;
}

static int choose_partial_victim(swapz_u32 *victim)
{
	swapz_u32 segment, best = ~(swapz_u32)0;
	swapz_u32 fewest_live = SWAPZ_SEGMENT_BLOCKS;

	for (segment = 0; segment < PHYSICAL_SEGMENTS; ++segment) {
		if (!roles[segment] || segment == a.open_segment ||
		    !segment_maps[segment] ||
		    segment_maps[segment] >= fewest_live)
			continue;
		fewest_live = segment_maps[segment];
		best = segment;
	}
	if (best == ~(swapz_u32)0)
		return -ENOSPC;
	*victim = best;
	return 0;
}

static int test_sustained_all_raw_gc_rotations(void)
{
	const unsigned int rotations = 64U;
	swapz_u32 next_logical = 0;
	unsigned int rotation;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1) == 0);
	for (rotation = 0; rotation < rotations; ++rotation) {
		swapz_u32 victim, block;
		unsigned int attempts;
		int error = -EUCLEAN;

		/* A bounded sweep must exhaust all ordinary foreground allocation
		 * even though the target remains 100% logically populated. */
		for (attempts = 0; attempts <= SWAPZ_SEGMENT_BLOCKS; ++attempts) {
			error = overwrite_outside_open(&next_logical);
			if (error)
				break;
		}
		CHECK(error == -ENOSPC);
		/*
		 * Every successful rotation must buy real foreground progress, and
		 * worst-case RAW occupancy can consume at most one segment before
		 * requiring the next bounded reserve exchange.
		 */
		CHECK(attempts > 0 && attempts <= SWAPZ_SEGMENT_BLOCKS);
		CHECK(!a.in_flight && !a.batch_pending);
		CHECK(choose_partial_victim(&victim) == 0);
		CHECK(segment_maps[victim] < SWAPZ_SEGMENT_BLOCKS);
		CHECK(relocate_segment(victim) == 0);
		CHECK(!roles[victim] && !segment_maps[victim]);
		for (block = victim * SWAPZ_SEGMENT_BLOCKS;
		     block < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
			CHECK(!live[block]);
		CHECK(reserve_segments() == PHYSICAL_SEGMENTS - FOREGROUND_SEGMENTS);
		CHECK(verify_all_pages() == 0);
	}
	/* A tiny one-live-page victim would make the same rotation counter
	 * pass without exercising nearly full destination relocation. */
	CHECK(gc_writes >= (unsigned long long)rotations *
		      (SWAPZ_SEGMENT_BLOCKS / 2U));
	CHECK(gc_reads == gc_writes);
	CHECK(gc_bytes_relocated == gc_writes * (unsigned long long)SWAPZ_BLOCK_BYTES);
	printf("SWAPZ_GC_SUSTAINED_EVIDENCE=rotations:%u "
	       "foreground_writes:%llu gc_reads:%llu gc_writes:%llu "
	       "gc_bytes_relocated:%llu\n",
	       rotations, foreground_writes, gc_reads, gc_writes,
	       gc_bytes_relocated);
	return 0;
}



/*
 * The sidecar zero condition never authorizes reclaim or role exchange by
 * itself. A fabricated, last-survivor reference is checked after all 204
 * other pages have moved. Restore it before byte-exact verification.
 */
static int test_false_zero_sidecar_blocks_commit_and_reuse(void)
{
	swapz_u32 logical, saved_block, saved_open, saved_next;
	unsigned long long probes_before;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1) == 0);
	for (logical = 0; logical < 52U; ++logical)
		CHECK(write_page(logical, 2) == 0);
	CHECK(relocate_segment_pages(0) == 0);
	CHECK(!segment_maps[0] && program_counts[0] != 0);
	CHECK(roles[0] && !roles[6]);

	logical = 52U;
	saved_block = maps[logical].start_block;
	CHECK(saved_block / SWAPZ_SEGMENT_BLOCKS == 6U);
	maps[logical].start_block = logical; /* Hidden authoritative victim ref. */
	CHECK(swapz_gc_commit_rotation(&a, 0) == -EUCLEAN);
	CHECK(roles[0] && !roles[6] && a.gc_allocation);
	maps[logical].start_block = saved_block;
	CHECK(swapz_gc_commit_rotation(&a, 0) == 0);
	CHECK(!roles[0] && roles[6] && !segment_maps[0]);
	CHECK(verify_all_pages() == 0);

	/* The former victim is now a claimed reserve with zero sidecars.
	 * A false-zero reuse candidate must fail before roles or reclaim move. */
	saved_open = a.open_segment;
	saved_next = a.next_block;
	probes_before = a.alloc_probe_full_scans;
	maps[logical].start_block = logical;
	a.next_segment_probe = 0;
	CHECK(swapz_gc_begin_rotation(&a, 1) == -EUCLEAN);
	CHECK(!a.gc_allocation && !roles[0] && roles[6]);
	CHECK(a.alloc_probe_full_scans == probes_before + 1ULL);
	CHECK(a.next_block == saved_next);
	maps[logical].start_block = saved_block;

	/* Production caller restores the saved cursor after failed GC begin. */
	a.open_segment = saved_open;
	a.next_segment_probe = 0;
	CHECK(swapz_gc_begin_rotation(&a, 1) == 0);
	CHECK(a.gc_destination == 0 && program_counts[0] >= 2U);
	CHECK(!roles[0] && roles[6]);
	CHECK(verify_all_pages() == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_repeated_raw_reclaim_and_reuse() == 0); passed++;
	CHECK(test_sustained_all_raw_gc_rotations() == 0); passed++;
	CHECK(test_fragmented_raw_gc_restores_progress() == 0); passed++;
	CHECK(test_false_zero_sidecar_blocks_commit_and_reuse() == 0); passed++;
	printf("SWAPZ_GC_HIGH_OCCUPANCY_PASS=%d "
	       "foreground_writes=%llu gc_reads=%llu gc_writes=%llu "
	       "gc_bytes_relocated=%llu alloc_probe_256_block_scans=%llu\n",
	       passed, foreground_writes, gc_reads, gc_writes,
	       gc_bytes_relocated, a.alloc_probe_full_scans);
	return 0;
}
