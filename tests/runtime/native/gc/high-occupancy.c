// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
/*
 * Worst-case RAW allocator/GC occupancy on exact production authority C.
 *
 * Geometry deliberately leaves one complete foreground segment beyond logical
 * RAW occupancy, plus the two rotating reserve segments. This is the minimum
 * current allocator shape that can bootstrap copy-on-write after an all-live
 * fill without borrowing a GC reserve for ordinary foreground publication.
 */
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
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
static swapz_u32 expected_generations[LOGICAL_PAGES];
static swapz_u8 media[PHYSICAL_BLOCKS * SWAPZ_BLOCK_BYTES];
static swapz_u8 page_bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 expected_bytes[SWAPZ_BLOCK_BYTES];
static unsigned long long foreground_writes;
static unsigned long long gc_reads;
static unsigned long long gc_writes;
static unsigned long long gc_bytes_relocated;

/* One serialized authority owner and a bounded, allocation-free failure trace. */
#define CHURN_SEED UINT32_C(0x15a0c0de)
#define CHURN_TRACE_LENGTH 12U

struct churn_operation {
	uint64_t index;
	const char *kind;
	swapz_u32 logical;
	swapz_u32 expected_generation;
	swapz_u32 actual_generation;
	int error;
};

static struct churn_operation churn_trace[CHURN_TRACE_LENGTH];
static uint64_t churn_operation_index;
static unsigned int churn_trace_count;
static int churn_active;

static void record_churn(const char *kind, swapz_u32 logical,
			 swapz_u32 expected_generation,
			 swapz_u32 actual_generation, int error)
{
	uint64_t index;

	if (!churn_active)
		return;
	index = ++churn_operation_index;
	churn_trace[(index - 1U) % CHURN_TRACE_LENGTH] =
		(struct churn_operation) {
			.index = index, .kind = kind, .logical = logical,
			.expected_generation = expected_generation,
			.actual_generation = actual_generation, .error = error,
		};
	if (churn_trace_count < CHURN_TRACE_LENGTH)
		churn_trace_count++;
}

static int churn_invariant_failure(const char *invariant, int line,
				    int failure_error)
{
	const struct churn_operation *last =
		churn_operation_index ?
		&churn_trace[(churn_operation_index - 1U) % CHURN_TRACE_LENGTH] :
		NULL;
	const uint64_t first =
		churn_operation_index - churn_trace_count + 1U;
	unsigned int offset;

	fprintf(stderr, "%s:%d FAIL GC churn seed=0x%08" PRIx32
		" operation_index=%" PRIu64 " invariant=%s"
		" expected_generation=%" PRIu32 " actual_generation=%" PRIu32
		" errno=%d\n", __FILE__, line, (uint32_t)CHURN_SEED,
		churn_operation_index, invariant,
		last ? last->expected_generation : 0U,
		last ? last->actual_generation : 0U, failure_error);
	for (offset = 0; offset < churn_trace_count; ++offset) {
		const struct churn_operation *entry =
			&churn_trace[(first + offset - 1U) % CHURN_TRACE_LENGTH];

		fprintf(stderr, "  operation=%" PRIu64 " kind=%s logical=%" PRIu32
			" expected_generation=%" PRIu32
			" actual_generation=%" PRIu32 " errno=%d\n",
			entry->index, entry->kind, entry->logical,
			entry->expected_generation, entry->actual_generation,
			entry->error);
	}
	fprintf(stderr, "  recovery victim=%" PRIu32 " victim_role=%d"
		" destination=%" PRIu32 " destination_role=%d"
		" open=%" PRIu32 " cursor=%" PRIu32 " active=%d\n",
		a.gc_forbidden_victim,
		a.gc_forbidden_victim < PHYSICAL_SEGMENTS ?
			(int)roles[a.gc_forbidden_victim] : -1,
		a.gc_destination,
		a.gc_destination < PHYSICAL_SEGMENTS ?
			(int)roles[a.gc_destination] : -1,
		a.open_segment, a.next_block, a.gc_allocation);
	return 1;
}

#define CHURN_CHECK(invariant) do { if (!(invariant)) \
	return churn_invariant_failure(#invariant, __LINE__, 0); \
} while (0)
#define CHURN_CHECK_ERROR(invariant, failure_error) do { if (!(invariant)) \
	return churn_invariant_failure(#invariant, __LINE__, (failure_error)); \
} while (0)

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
	memset(expected_generations, 0, sizeof(expected_generations));
	foreground_writes = 0;
	gc_reads = 0;
	gc_writes = 0;
	gc_bytes_relocated = 0;
	return 0;
}

static int write_page(swapz_u32 logical, swapz_u32 version)
{
	const swapz_u32 previous_generation = maps[logical].generation;
	struct swapz_tx tx;
	int error;

	make_raw_page(logical, version, page_bytes);
	error = swapz_stage(&a, &logical, 1, 1, &tx);
	if (error) {
		record_churn("stage_raw", logical, previous_generation,
			     maps[logical].generation, error);
		return error;
	}
	if (tx.start_block >= PHYSICAL_BLOCKS) {
		(void)swapz_finish_raw(&a, &tx, page_bytes, 0, -ERANGE);
		record_churn("raw_bounds", logical, previous_generation,
			     maps[logical].generation, -ERANGE);
		return -ERANGE;
	}
	memcpy(media + (size_t)tx.start_block * SWAPZ_BLOCK_BYTES,
	       page_bytes, SWAPZ_BLOCK_BYTES);
	error = swapz_finish_raw(&a, &tx, page_bytes, 1, 0);
	if (!error) {
		versions[logical] = version;
		if (churn_active)
			expected_generations[logical]++;
		foreground_writes++;
	}
	record_churn("foreground_raw", logical,
		     previous_generation + (error == 0),
		     maps[logical].generation, error);
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
		/* A byte-exact CRC cannot detect an unexpected authority generation. */
		if (churn_active && map->generation != expected_generations[logical]) {
			record_churn("verify_generation", logical,
				     expected_generations[logical], map->generation,
				     -EUCLEAN);
			return -EUCLEAN;
		}
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
		if (churn_active)
			expected_generations[logical]++;
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
	swapz_u32 next_logical = CHURN_SEED % PHYSICAL_SEGMENTS;
	struct timespec wall_start, wall_end;
	clock_t cpu_start, cpu_end;
	unsigned int rotation;
	int error;

	error = setup();
	CHURN_CHECK_ERROR(error == 0, error);
	/* Native host CPU and wall observations are synthetic only: they are
	 * NOT the physical ten-second stall or hour-long qualification gate. */
	CHURN_CHECK_ERROR(clock_gettime(CLOCK_MONOTONIC, &wall_start) == 0,
			  errno);
	cpu_start = clock();
	CHURN_CHECK_ERROR(cpu_start != (clock_t)-1, errno);
	churn_active = 1;
	churn_operation_index = 0;
	churn_trace_count = 0;
	error = fill_all_pages(1);
	CHURN_CHECK_ERROR(error == 0, error);
	for (rotation = 0; rotation < rotations; ++rotation) {
		swapz_u32 victim, block;
		unsigned int attempts;

		error = -EUCLEAN;

		/* A bounded sweep must exhaust all ordinary foreground allocation
		 * even though the target remains 100% logically populated. */
		for (attempts = 0; attempts <= SWAPZ_SEGMENT_BLOCKS; ++attempts) {
			error = overwrite_outside_open(&next_logical);
			if (error)
				break;
		}
		CHURN_CHECK_ERROR(error == -ENOSPC, error);
		/*
		 * Every successful rotation must buy real foreground progress, and
		 * worst-case RAW occupancy can consume at most one segment before
		 * requiring the next bounded reserve exchange.
		 */
		CHURN_CHECK(attempts > 0 && attempts <= SWAPZ_SEGMENT_BLOCKS);
		CHURN_CHECK(!a.in_flight && !a.batch_pending);
		error = choose_partial_victim(&victim);
		CHURN_CHECK_ERROR(error == 0, error);
		CHURN_CHECK(segment_maps[victim] < SWAPZ_SEGMENT_BLOCKS);
		/* A trace generation must come from the authoritative map, never
		 * from a segment's mapped-page occupancy sidecar. */
		{
			const swapz_u32 tracked_logical = LOGICAL_PAGES - 1U;
			const swapz_u32 expected_generation =
				maps[tracked_logical].generation +
				(maps[tracked_logical].valid &&
				 maps[tracked_logical].start_block /
				 SWAPZ_SEGMENT_BLOCKS == victim);

			error = relocate_segment(victim);
			record_churn("gc_rotation", tracked_logical,
				     expected_generation,
				     maps[tracked_logical].generation, error);
		}
		CHURN_CHECK_ERROR(error == 0, error);
		CHURN_CHECK(!roles[victim] && !segment_maps[victim]);
		for (block = victim * SWAPZ_SEGMENT_BLOCKS;
		     block < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
			CHURN_CHECK(!live[block]);
		CHURN_CHECK(reserve_segments() ==
			    PHYSICAL_SEGMENTS - FOREGROUND_SEGMENTS);
		error = verify_all_pages();
		CHURN_CHECK_ERROR(error == 0, error);
	}
	/* A tiny one-live-page victim would make the same rotation counter
	 * pass without exercising nearly full destination relocation. */
	CHURN_CHECK(gc_writes >= (unsigned long long)rotations *
		      (SWAPZ_SEGMENT_BLOCKS / 2U));
	CHURN_CHECK(gc_reads == gc_writes);
	CHURN_CHECK(gc_bytes_relocated == gc_writes * (unsigned long long)SWAPZ_BLOCK_BYTES);
	churn_active = 0;
	cpu_end = clock();
	CHURN_CHECK_ERROR(clock_gettime(CLOCK_MONOTONIC, &wall_end) == 0,
			  errno);
	CHURN_CHECK_ERROR(cpu_end != (clock_t)-1, errno);
	printf("SWAPZ_GC_SYNTHETIC_NATIVE_HOST_CPU_WALL=rotations:%u "
	       "cpu_ms:%.3f wall_ms:%.3f map_scan_count:%llu "
	       "physical_qualification:NOT_RUN\n",
	       rotations, 1000.0 * (double)(cpu_end - cpu_start) / CLOCKS_PER_SEC,
	       1000.0 * ((double)(wall_end.tv_sec - wall_start.tv_sec) +
			 (double)(wall_end.tv_nsec - wall_start.tv_nsec) / 1.0e9),
	       a.alloc_probe_full_scans);
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


/*
 * Force the last mapped logical RAW page to be the last source survivor.
 * The lower layer writes all bytes but reports a failed completion at the
 * publication boundary: this cannot acknowledge the new mapping. The same
 * reserve must resume past the uncertain block, then reclaim the victim only
 * after its very last authoritative reference moves.
 */
static int test_last_mapped_page_partial_victim_failed_publication(void)
{
	const swapz_u32 victim = LOGICAL_SEGMENTS - 1U;
	const swapz_u32 last_logical = LOGICAL_PAGES - 1U;
	struct swapz_map previous;
	struct swapz_tx transaction;
	swapz_u32 failed_block = ~(swapz_u32)0;
	swapz_u32 logical;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1) == 0);
	/* Eight COW overwrites create enough reserve headroom for one torn
	 * destination block while leaving the last logical page untouched. */
	for (logical = victim * SWAPZ_SEGMENT_BLOCKS;
	     logical < victim * SWAPZ_SEGMENT_BLOCKS + 8U; ++logical)
		CHECK(write_page(logical, 2) == 0);
	CHECK(a.open_segment == FOREGROUND_SEGMENTS - 1U);
	CHECK(segment_maps[victim] == SWAPZ_SEGMENT_BLOCKS - 8U);
	previous = maps[last_logical];
	CHECK(previous.valid && previous.raw &&
	      previous.start_block == LOGICAL_PAGES - 1U);
	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	CHECK(a.gc_destination == FOREGROUND_SEGMENTS);

	for (logical = victim * SWAPZ_SEGMENT_BLOCKS + 8U;
	     logical < last_logical; ++logical) {
		const swapz_u32 source = maps[logical].start_block;

		CHECK(source / SWAPZ_SEGMENT_BLOCKS == victim);
		memcpy(page_bytes, media + (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		CHECK(swapz_verify_raw(&a, logical, page_bytes) == 0);
		CHECK(swapz_stage(&a, &logical, 1, 1, &transaction) == 0);
		memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 1, 0) == 0);
		gc_reads++;
		gc_writes++;
		gc_bytes_relocated += SWAPZ_BLOCK_BYTES;
	}
	CHECK(segment_maps[victim] == 1U);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
	CHECK(a.gc_allocation && roles[victim] &&
	      maps[last_logical].start_block == previous.start_block);
	CHECK(verify_all_pages() == 0);

	memcpy(page_bytes,
	       media + (size_t)previous.start_block * SWAPZ_BLOCK_BYTES,
	       SWAPZ_BLOCK_BYTES);
	/* Repeated uncertain completions consume unique destination blocks.
	 * Each failed lower write may still have reached the entire medium. */
	for (unsigned int attempt = 0; attempt < 3U; ++attempt) {
		const int lower_error = attempt == 1U ? -ENOSPC : -EIO;

		CHECK(swapz_stage(&a, &last_logical, 1, 1, &transaction) == 0);
		if (attempt)
			CHECK(transaction.start_block > failed_block);
		failed_block = transaction.start_block;
		memcpy(media + (size_t)failed_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 0,
				       lower_error) == lower_error);
		CHECK(!a.in_flight && a.gc_allocation);
		CHECK(maps[last_logical].start_block == previous.start_block &&
		      maps[last_logical].generation == previous.generation);
		CHECK(!live[failed_block] && !classes[failed_block]);
		CHECK(a.abandoned_blocks == attempt + 1U);
		CHECK(swapz_gc_commit_rotation(&a, victim) == -EUCLEAN);
		CHECK(verify_all_pages() == 0);
	}

	CHECK(swapz_stage(&a, &last_logical, 1, 1, &transaction) == 0);
	CHECK(transaction.start_block > failed_block);
	memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
	       page_bytes, SWAPZ_BLOCK_BYTES);
	CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 1, 0) == 0);
	CHECK(maps[last_logical].generation == previous.generation + 1U);
	CHECK(swapz_gc_commit_rotation(&a, victim) == 0);
	CHECK(!roles[victim] && roles[FOREGROUND_SEGMENTS]);
	for (swapz_u32 block = victim * SWAPZ_SEGMENT_BLOCKS;
	     block < (victim + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		CHECK(!live[block]);
	CHECK(verify_all_pages() == 0);
	return 0;
}


/*
 * One uncertain destination block and 255 RAW survivors exhaust all 256
 * blocks. A full destination cannot become foreground: safely roll forward
 * by reusing the independently proven-dead original victim, preserving each
 * authoritative generation and the untrusted failed media.
 */
static int test_full_destination_raw_roll_forward(void)
{
	const swapz_u32 victim = 0U;
	const swapz_u32 exhausted_destination = FOREGROUND_SEGMENTS;
	const swapz_u32 destination_start =
		exhausted_destination * SWAPZ_SEGMENT_BLOCKS;
	struct swapz_map saved_tail;
	struct swapz_tx transaction;
	swapz_u32 logical, failed_block;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1U) == 0);
	CHECK(write_page(0U, 2U) == 0);
	CHECK(segment_maps[victim] == SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	CHECK(a.gc_destination == exhausted_destination);

	logical = 1U;
	memcpy(page_bytes,
	       media + (size_t)maps[logical].start_block * SWAPZ_BLOCK_BYTES,
	       SWAPZ_BLOCK_BYTES);
	CHECK(swapz_verify_raw(&a, logical, page_bytes) == 0);
	CHECK(swapz_stage(&a, &logical, 1U, 1U, &transaction) == 0);
	failed_block = transaction.start_block;
	CHECK(failed_block == destination_start);
	memcpy(media + (size_t)failed_block * SWAPZ_BLOCK_BYTES,
	       page_bytes, SWAPZ_BLOCK_BYTES);
	CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 0U, -EIO) == -EIO);
	CHECK(!live[failed_block] && !classes[failed_block]);
	CHECK(a.abandoned_blocks == 1U);

	for (logical = 1U; logical < SWAPZ_SEGMENT_BLOCKS; ++logical) {
		const swapz_u32 source = maps[logical].start_block;

		CHECK(source / SWAPZ_SEGMENT_BLOCKS == victim);
		memcpy(page_bytes, media + (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		CHECK(swapz_verify_raw(&a, logical, page_bytes) == 0);
		CHECK(swapz_stage(&a, &logical, 1U, 1U, &transaction) == 0);
		CHECK(transaction.start_block > failed_block);
		memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 1U, 0) == 0);
		gc_reads++;
		gc_writes++;
		gc_bytes_relocated += SWAPZ_BLOCK_BYTES;
	}
	CHECK(!segment_maps[victim]);
	CHECK(a.next_block == destination_start + SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -ENOSPC);
	CHECK(a.gc_allocation && roles[victim] &&
	      !roles[exhausted_destination]);
	CHECK(verify_all_pages() == 0);

	/* A forged last-entry reference cannot be hidden by false-zero victim
	 * counts at the roll-forward boundary, or change the recovery cursor. */
	saved_tail = maps[LOGICAL_PAGES - 1U];
	maps[LOGICAL_PAGES - 1U].start_block = victim;
	CHECK(swapz_gc_roll_forward_rotation(
		      &a, exhausted_destination) == -EUCLEAN);
	CHECK(a.gc_destination == exhausted_destination &&
	      a.next_block == destination_start + SWAPZ_SEGMENT_BLOCKS &&
	      roles[victim] && !roles[exhausted_destination]);
	maps[LOGICAL_PAGES - 1U] = saved_tail;
	CHECK(swapz_gc_roll_forward_rotation(
		      &a, exhausted_destination) == 0);
	CHECK(a.gc_allocation && a.gc_destination == victim &&
	      a.gc_forbidden_victim == exhausted_destination);
	CHECK(!roles[victim] && roles[exhausted_destination] &&
	      a.next_block == victim * SWAPZ_SEGMENT_BLOCKS);
	CHECK(verify_all_pages() == 0);

	for (logical = 1U; logical < SWAPZ_SEGMENT_BLOCKS; ++logical) {
		const swapz_u32 source = maps[logical].start_block;

		CHECK(source / SWAPZ_SEGMENT_BLOCKS == exhausted_destination);
		CHECK(source != failed_block);
		memcpy(page_bytes, media + (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		CHECK(swapz_verify_raw(&a, logical, page_bytes) == 0);
		CHECK(swapz_stage(&a, &logical, 1U, 1U, &transaction) == 0);
		CHECK(transaction.start_block / SWAPZ_SEGMENT_BLOCKS == victim);
		memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 1U, 0) == 0);
		gc_reads++;
		gc_writes++;
		gc_bytes_relocated += SWAPZ_BLOCK_BYTES;
	}
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(swapz_gc_commit_rotation(&a, exhausted_destination) == 0);
	CHECK(roles[victim] && !roles[exhausted_destination]);
	CHECK(reserve_segments() == PHYSICAL_SEGMENTS - FOREGROUND_SEGMENTS);
	CHECK(!live[failed_block] && !classes[failed_block]);
	CHECK(verify_all_pages() == 0);

	/* A successful roll-forward must buy an actual foreground publication,
	 * not just exchange role labels with a one-block allocation tail. */
	{
		const swapz_u32 previous_generation = maps[0].generation;
		const int write_error = write_page(0U, 3U);

		if (write_error || maps[0].generation != previous_generation + 1U ||
		    maps[0].start_block != SWAPZ_SEGMENT_BLOCKS - 1U) {
			fprintf(stderr, "%s:%d FAIL GC "
				"operation=post_roll_forward_foreground_write "
				"original_errno=%d expected_generation=%" PRIu32
				" actual_generation=%" PRIu32
				" victim=%" PRIu32 " victim_role=%u"
				" destination=%" PRIu32 " destination_role=%u"
				" recovery=%d cursor=%" PRIu32 "\n",
				__FILE__, __LINE__, write_error,
				previous_generation + 1U, maps[0].generation,
				exhausted_destination,
				(unsigned int)roles[exhausted_destination],
				victim, (unsigned int)roles[victim],
				a.gc_allocation, a.next_block);
			return 1;
		}
	}
	CHECK(verify_all_pages() == 0);
	return 0;
}


/*
 * Fail-closed recovery when the last authoritative RAW survivor cannot move:
 * two successive reserve destinations can be consumed by writes with unknown
 * completion. Neither the physical bytes nor the zero live sidecars permit
 * claiming those blocks again. There is no safe third destination.
 */
static int test_uncertain_recovery_exhausts_reserves(void)
{
	const swapz_u32 victim = LOGICAL_SEGMENTS - 1U;
	const swapz_u32 last_logical = LOGICAL_PAGES - 1U;
	const swapz_u32 first_destination = FOREGROUND_SEGMENTS;
	const swapz_u32 second_destination = FOREGROUND_SEGMENTS + 1U;
	struct swapz_map authoritative_last;
	struct swapz_tx transaction;
	swapz_u32 logical, uncertain_block = 0U;
	unsigned int attempt;

	CHECK(setup() == 0);
	CHECK(fill_all_pages(1U) == 0);
	for (logical = victim * SWAPZ_SEGMENT_BLOCKS;
	     logical < victim * SWAPZ_SEGMENT_BLOCKS + 8U; ++logical)
		CHECK(write_page(logical, 2U) == 0);
	authoritative_last = maps[last_logical];
	CHECK(swapz_gc_begin_rotation(&a, victim) == 0);
	CHECK(a.gc_destination == first_destination);

	for (logical = victim * SWAPZ_SEGMENT_BLOCKS + 8U;
	     logical < last_logical; ++logical) {
		const swapz_u32 source = maps[logical].start_block;

		CHECK(source / SWAPZ_SEGMENT_BLOCKS == victim);
		memcpy(page_bytes, media + (size_t)source * SWAPZ_BLOCK_BYTES,
		       SWAPZ_BLOCK_BYTES);
		CHECK(swapz_verify_raw(&a, logical, page_bytes) == 0);
		CHECK(swapz_stage(&a, &logical, 1U, 1U, &transaction) == 0);
		memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes, 1U, 0) == 0);
	}
	CHECK(segment_maps[victim] == 1U);
	CHECK(a.next_block == first_destination * SWAPZ_SEGMENT_BLOCKS +
	      SWAPZ_SEGMENT_BLOCKS - 9U);

	memcpy(page_bytes,
	       media + (size_t)authoritative_last.start_block * SWAPZ_BLOCK_BYTES,
	       SWAPZ_BLOCK_BYTES);
	CHECK(swapz_verify_raw(&a, last_logical, page_bytes) == 0);
	for (attempt = 0; attempt < 9U; ++attempt) {
		CHECK(swapz_stage(&a, &last_logical, 1U, 1U, &transaction) == 0);
		if (attempt)
			CHECK(transaction.start_block > uncertain_block);
		uncertain_block = transaction.start_block;
		memcpy(media + (size_t)uncertain_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes,
				       0U, -EIO) == -EIO);
		CHECK(maps[last_logical].start_block ==
		      authoritative_last.start_block &&
		      maps[last_logical].generation ==
		      authoritative_last.generation);
		CHECK(!live[uncertain_block] && !classes[uncertain_block]);
	}
	CHECK(a.next_block == (first_destination + 1U) *
	      SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -ENOSPC);
	CHECK(swapz_gc_roll_forward_rotation(
		      &a, first_destination) == -EUCLEAN);
	CHECK(a.gc_allocation && a.gc_destination == first_destination &&
	      roles[victim] && !roles[first_destination]);
	CHECK(verify_all_pages() == 0);

	CHECK(swapz_gc_advance_rotation_destination(
		      &a, first_destination) == 0);
	CHECK(a.gc_destination == second_destination &&
	      roles[first_destination] && !roles[second_destination]);
	CHECK(a.next_block == second_destination * SWAPZ_SEGMENT_BLOCKS);
	CHECK(verify_all_pages() == 0);

	for (attempt = 0; attempt < SWAPZ_SEGMENT_BLOCKS; ++attempt) {
		CHECK(swapz_stage(&a, &last_logical, 1U, 1U, &transaction) == 0);
		CHECK(transaction.start_block ==
		      second_destination * SWAPZ_SEGMENT_BLOCKS + attempt);
		memcpy(media + (size_t)transaction.start_block * SWAPZ_BLOCK_BYTES,
		       page_bytes, SWAPZ_BLOCK_BYTES);
		CHECK(swapz_finish_raw(&a, &transaction, page_bytes,
				       0U, -EIO) == -EIO);
		CHECK(maps[last_logical].start_block ==
		      authoritative_last.start_block &&
		      maps[last_logical].generation ==
		      authoritative_last.generation);
	}
	CHECK(a.abandoned_blocks == SWAPZ_SEGMENT_BLOCKS + 9U);
	CHECK(a.next_block == PHYSICAL_BLOCKS);
	CHECK(swapz_gc_commit_rotation(&a, victim) == -ENOSPC);
	CHECK(swapz_gc_roll_forward_rotation(
		      &a, second_destination) == -EUCLEAN);
	CHECK(swapz_gc_advance_rotation_destination(
		      &a, second_destination) == -ENOSPC);
	CHECK(a.gc_allocation && a.gc_destination == second_destination &&
	      a.gc_forbidden_victim == victim &&
	      roles[victim] && roles[first_destination] &&
	      !roles[second_destination]);
	CHECK(swapz_stage(&a, &last_logical, 1U, 1U, &transaction) == -ENOSPC);
	CHECK(!a.in_flight && !a.batch_pending);
	CHECK(maps[last_logical].generation == authoritative_last.generation);
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
	CHECK(test_last_mapped_page_partial_victim_failed_publication() == 0);
	passed++;
	CHECK(test_full_destination_raw_roll_forward() == 0);
	passed++;
	CHECK(test_uncertain_recovery_exhausts_reserves() == 0);
	passed++;
	printf("SWAPZ_GC_HIGH_OCCUPANCY_PASS=%d "
	       "foreground_writes=%llu gc_reads=%llu gc_writes=%llu "
	       "gc_bytes_relocated=%llu alloc_probe_256_block_scans=%llu\n",
	       passed, foreground_writes, gc_reads, gc_writes,
	       gc_bytes_relocated, a.alloc_probe_full_scans);
	return 0;
}
