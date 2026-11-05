// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "authority.h"
#include "codec.h"
#include "gc-cost.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

#define LOGICAL_PAGES 1024U
#define PHYSICAL_BLOCKS 4096U
#define SEGMENTS (PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS)
#define BENCH_ROUNDS 10U
#define VALIDATE_ROUNDS 20000U
#define APPEND_ROUNDS 4000U
#define EXTENT_RECORDS 2U

static struct swapz_authority a;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live[PHYSICAL_BLOCKS];
static swapz_u8 classes[PHYSICAL_BLOCKS];
static swapz_u8 roles[SEGMENTS];
static swapz_u32 mapped_pages[SEGMENTS];
static swapz_u32 program_counts[SEGMENTS];
static swapz_u32 first_page[SEGMENTS];
static swapz_u32 last_page[SEGMENTS];
static swapz_u32 prev_page[LOGICAL_PAGES];
static swapz_u32 next_page[LOGICAL_PAGES];
static swapz_u32 gc_live_bytes[SEGMENTS];
static swapz_u32 gc_io_cost[SEGMENTS];
static swapz_u16 gc_min_live_blocks[SEGMENTS];

static uint64_t now_ns(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts))
		return 0;
	return (uint64_t)ts.tv_sec * UINT64_C(1000000000) +
	       (uint64_t)ts.tv_nsec;
}

static int init_authority(void)
{
	CHECK(swapz_authority_init(&a, maps, live, classes, LOGICAL_PAGES,
				   PHYSICAL_BLOCKS) == 0);
	a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(&a, roles, SEGMENTS) == 0);
	CHECK(swapz_enable_segment_mapping_counts(&a, mapped_pages, SEGMENTS) == 0);
	CHECK(swapz_enable_segment_program_counts(&a, program_counts, SEGMENTS) == 0);
	CHECK(swapz_enable_segment_page_lists(&a, first_page, last_page,
					     prev_page, next_page, SEGMENTS,
					     LOGICAL_PAGES) == 0);
	CHECK(swapz_enable_segment_gc_accounting(&a, gc_live_bytes, gc_io_cost,
						gc_min_live_blocks, SEGMENTS) == 0);
	return 0;
}

/*
 * Fixed-reserve research callers can run without mapped-page sidecars. A
 * malformed live extent that starts in the preceding segment must therefore
 * be rejected before the allocator reuses the segment it illegally overlaps.
 */
static int test_legacy_reuse_rejects_cross_segment_map(void)
{
	enum {
		TEST_LOGICAL_PAGES = 2U,
		TEST_PHYSICAL_BLOCKS = 4U * SWAPZ_SEGMENT_BLOCKS,
	};
	struct swapz_authority authority;
	struct swapz_map test_maps[TEST_LOGICAL_PAGES];
	swapz_u16 test_live[TEST_PHYSICAL_BLOCKS];
	swapz_u8 test_classes[TEST_PHYSICAL_BLOCKS];
	struct swapz_tx transaction;
	const swapz_u32 corrupt_start = SWAPZ_SEGMENT_BLOCKS - 1U;
	swapz_u32 page = 1U;

	CHECK(swapz_authority_init(
		&authority, test_maps, test_live, test_classes,
		TEST_LOGICAL_PAGES, TEST_PHYSICAL_BLOCKS) == 0);
	authority.reuse_dead_segments = 1;
	test_maps[0] = (struct swapz_map) {
		.start_block = corrupt_start,
		.payload_offset =
			sizeof(struct swapz_header) + sizeof(struct swapz_record),
		.payload_length = 128U,
		.extent_blocks = 2U,
		.valid = 1U,
	};
	test_live[corrupt_start] = 1U;
	test_classes[corrupt_start] = 2U;

	CHECK(swapz_stage(&authority, &page, 1U, 1U, &transaction) == -EUCLEAN);
	CHECK(!authority.in_flight);
	CHECK(authority.open_segment == ~(swapz_u32)0);
	CHECK(authority.next_block == 0U);
	puts("PASS: legacy fixed-reserve reclaim rejects cross-segment map corruption");
	return 0;
}


/*
 * Measure GC's actual production authority dead-reserve claim, separating
 * a never-claimed segment from the identical, previously-claimed segment.
 * Current production C always scans both: a virgin-count witness can
 * itself be corrupt. The difference between these two paths is therefore
 * NOT scan cost. A matched traversal control is reported separately.
 * Runs offline in one thread, without lower I/O or shared state.
 */
#define CLAIM_SCAN_REPEATS 5U

/* Optional host-specific upper bound; zero disables a flaky CI time gate. */
static uint64_t max_verified_latency_gate_ns;

static int compare_scan_u64(const void *left, const void *right)
{
	uint64_t first = *(const uint64_t *)left;
	uint64_t second = *(const uint64_t *)right;

	return (first > second) - (first < second);
}

static uint64_t scan_median(uint64_t values[CLAIM_SCAN_REPEATS])
{
	qsort(values, CLAIM_SCAN_REPEATS, sizeof(values[0]), compare_scan_u64);
	return values[CLAIM_SCAN_REPEATS / 2U];
}

static uint64_t thread_cpu_ns(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts))
		return 0;
	return (uint64_t)ts.tv_sec * UINT64_C(1000000000) +
	       (uint64_t)ts.tv_nsec;
}


/*
 * Reference CPU traversal of the same logical map and map-indexed liveness /
 * class sidecars. This is a baseline for dependent memory touches, not an
 * unprotected GC algorithm. Unlike the production verifier, it deliberately
 * does not prove bounds, extent containment or candidate ownership; never use
 * it for reclaim.
 */
static volatile uint64_t scan_touch_sink;

static swapz_u32 touch_map_control(const struct swapz_map *maps,
				   const swapz_u16 *live_records,
				   const swapz_u8 *extent_classes,
				   swapz_u32 logical_pages,
				   swapz_u32 physical_blocks)
{
	swapz_u32 logical, touched = 0;

	for (logical = 0; logical < logical_pages; ++logical) {
		const struct swapz_map *map = &maps[logical];

		if (!map->valid)
			continue;
		if (map->start_block >= physical_blocks)
			return ~(swapz_u32)0;
		touched += live_records[map->start_block] &&
			   extent_classes[map->start_block] ==
				   map->extent_blocks;
	}
	scan_touch_sink += touched;
	return touched;
}

static int measure_production_claim_proof(swapz_u32 logical_pages)
{
	struct swapz_authority authority, sample;
	struct swapz_map *large_maps = NULL;
	swapz_u16 *large_live = NULL;
	swapz_u8 *large_classes = NULL, *large_roles = NULL;
	swapz_u32 *large_counts = NULL, *large_programs = NULL;
	uint64_t virgin_wall[CLAIM_SCAN_REPEATS], claimed_wall[CLAIM_SCAN_REPEATS];
	uint64_t virgin_cpu[CLAIM_SCAN_REPEATS], claimed_cpu[CLAIM_SCAN_REPEATS];
	uint64_t traversal_wall[CLAIM_SCAN_REPEATS];
	uint64_t traversal_cpu[CLAIM_SCAN_REPEATS];
	uint64_t final_publish_wall[CLAIM_SCAN_REPEATS];
	uint64_t final_publish_cpu[CLAIM_SCAN_REPEATS];
	uint64_t commit_wall[CLAIM_SCAN_REPEATS];
	uint64_t commit_cpu[CLAIM_SCAN_REPEATS];
	uint64_t final_publish_worst = 0, commit_worst = 0;
	uint64_t virgin_worst = 0;
	uint64_t virgin_corrupt_wall = 0;
	uint64_t claimed_worst = 0, corrupt_wall;
	uint64_t recovery_metadata_worst = 0;
	uint64_t map_bytes = (uint64_t)logical_pages * sizeof(*large_maps);
	uint64_t reserve = (uint64_t)logical_pages / 8U +
			   (logical_pages % 8U != 0U);
	uint64_t physical_64, clock_start, cpu_start;
	swapz_u8 raw_page[SWAPZ_BLOCK_BYTES];
	swapz_u32 physical_blocks, segments, reserve_segment, logical;
	unsigned int repeat;
	int result = 1;
#define REQUIRE_CLAIM(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: FAIL claim geometry=%u: %s\n", \
		__FILE__, __LINE__, logical_pages, #condition); \
	goto cleanup; \
} } while (0)
#define REQUIRE_TIMED_CLAIM(call, expected_result) do { \
	uint64_t timed_start = now_ns(); \
	int timed_result = (call); \
	uint64_t timed_end = now_ns(); \
	uint64_t timed_elapsed; \
	REQUIRE_CLAIM(timed_start && timed_end >= timed_start); \
	timed_elapsed = timed_end - timed_start; \
	if (timed_elapsed > recovery_metadata_worst) \
		recovery_metadata_worst = timed_elapsed; \
	REQUIRE_CLAIM(timed_result == (expected_result)); \
} while (0)

	if (reserve < 2U * SWAPZ_SEGMENT_BLOCKS)
		reserve = 2U * SWAPZ_SEGMENT_BLOCKS;
	/* One full foreground headroom segment plus the reserved blocks. */
	physical_64 = (logical_pages + reserve +
		       2U * SWAPZ_SEGMENT_BLOCKS - 1U) /
		      SWAPZ_SEGMENT_BLOCKS * SWAPZ_SEGMENT_BLOCKS;
	REQUIRE_CLAIM(physical_64 <= UINT32_MAX);
	physical_blocks = (swapz_u32)physical_64;
	segments = physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	reserve_segment = segments - 1U;

	large_maps = calloc(logical_pages, sizeof(*large_maps));
	large_live = calloc(physical_blocks, sizeof(*large_live));
	large_classes = calloc(physical_blocks, sizeof(*large_classes));
	large_roles = calloc(segments, sizeof(*large_roles));
	large_counts = calloc(segments, sizeof(*large_counts));
	large_programs = calloc(segments, sizeof(*large_programs));
	REQUIRE_CLAIM(large_maps && large_live && large_classes &&
		      large_roles && large_counts && large_programs);
	REQUIRE_CLAIM(swapz_authority_init(
		&authority, large_maps, large_live, large_classes,
		logical_pages, physical_blocks) == 0);
	authority.reuse_dead_segments = 1;
	REQUIRE_CLAIM(swapz_enable_segment_rotation(
		&authority, large_roles, segments) == 0);
	REQUIRE_CLAIM(swapz_enable_segment_mapping_counts(
		&authority, large_counts, segments) == 0);
	REQUIRE_CLAIM(swapz_enable_segment_program_counts(
		&authority, large_programs, segments) == 0);
	REQUIRE_CLAIM(!large_roles[reserve_segment] && large_roles[1U]);
	memset(raw_page, 0x5a, sizeof(raw_page));

	/* Every logical map is valid, distinct, and physically within the
	 * foreground. The last reserve is unreferenced and must scan to end. */
	for (logical = 0; logical < logical_pages; ++logical) {
		large_maps[logical].start_block = logical;
		large_maps[logical].valid = 1;
		large_maps[logical].raw = 1;
		large_maps[logical].extent_blocks = 1;
		large_maps[logical].payload_length = SWAPZ_BLOCK_BYTES;
		large_live[logical] = 1U;
		large_classes[logical] = 1U;
		large_counts[logical / SWAPZ_SEGMENT_BLOCKS]++;
		large_programs[logical / SWAPZ_SEGMENT_BLOCKS] = 1U;
	}
	authority.open_segment =
		logical_pages / SWAPZ_SEGMENT_BLOCKS - 1U;
	authority.next_block = logical_pages;
	authority.next_segment_probe = reserve_segment;
	for (repeat = 0; repeat < CLAIM_SCAN_REPEATS; ++repeat) {
		/* A clean virgin witness is an intentionally reset measurement
		 * fixture only. Production counters must never be decremented. */
		large_programs[reserve_segment] = 0;
		sample = authority;
		clock_start = now_ns();
		cpu_start = thread_cpu_ns();
		REQUIRE_CLAIM(clock_start && cpu_start);
		REQUIRE_CLAIM(swapz_gc_begin_rotation(&sample, 1U) == 0);
		virgin_wall[repeat] = now_ns() - clock_start;
		virgin_cpu[repeat] = thread_cpu_ns() - cpu_start;
		if (virgin_wall[repeat] > virgin_worst)
			virgin_worst = virgin_wall[repeat];
		REQUIRE_CLAIM(sample.gc_destination == reserve_segment &&
			      sample.alloc_probe_full_scans == 1ULL &&
			      large_programs[reserve_segment] == 1U);

		large_programs[reserve_segment] = 1;
		sample = authority;
		clock_start = now_ns();
		cpu_start = thread_cpu_ns();
		REQUIRE_CLAIM(clock_start && cpu_start);
		REQUIRE_CLAIM(swapz_gc_begin_rotation(&sample, 1U) == 0);
		claimed_wall[repeat] = now_ns() - clock_start;
		claimed_cpu[repeat] = thread_cpu_ns() - cpu_start;
		REQUIRE_CLAIM(sample.gc_destination == reserve_segment &&
			      sample.alloc_probe_full_scans == 1ULL &&
			      large_programs[reserve_segment] == 2U);
		if (claimed_wall[repeat] > claimed_worst)
			claimed_worst = claimed_wall[repeat];

		/* Memory-only comparator over the same valid entries. Timing
		 * includes its reduction and volatile sink publication. */
		clock_start = now_ns();
		cpu_start = thread_cpu_ns();
		REQUIRE_CLAIM(touch_map_control(
			      large_maps, large_live, large_classes,
			      logical_pages, physical_blocks) == logical_pages);
		traversal_wall[repeat] = now_ns() - clock_start;
		traversal_cpu[repeat] = thread_cpu_ns() - cpu_start;
	}

	/* A forged zero sidecar cannot hide even a final-entry reference. */
	large_programs[reserve_segment] = 1;
	large_maps[logical_pages - 1U].start_block =
		reserve_segment * SWAPZ_SEGMENT_BLOCKS;
	sample = authority;
	clock_start = now_ns();
	REQUIRE_CLAIM(swapz_gc_begin_rotation(&sample, 1U) == -EUCLEAN);
	corrupt_wall = now_ns() - clock_start;
	REQUIRE_CLAIM(!sample.gc_allocation &&
		      sample.alloc_probe_full_scans == 1ULL &&
		      large_programs[reserve_segment] == 1U);
	/* The zero program-count witness is also untrusted: even a
	 * nominally virgin reserve cannot reuse a forged live map. */
	large_programs[reserve_segment] = 0;
	sample = authority;
	clock_start = now_ns();
	REQUIRE_CLAIM(swapz_gc_begin_rotation(&sample, 1U) == -EUCLEAN);
	virgin_corrupt_wall = now_ns() - clock_start;
	REQUIRE_CLAIM(!sample.gc_allocation &&
		      sample.alloc_probe_full_scans == 1ULL &&
		      large_programs[reserve_segment] == 0U);
	large_maps[logical_pages - 1U].start_block = logical_pages - 1U;

	/*
	 * A RAW GC move that removes the apparent final mapping from a closed
	 * victim performs another authoritative full-map proof inside
	 * swapz_finish_raw(), before cached counts can reach zero. Keep 255 of
	 * victim segment 1's mappings valid in the foreground headroom segment,
	 * leave one source mapping behind, then stage that last move into the
	 * final free headroom block. Staging itself fits the open segment and is
	 * deliberately outside the timed publication boundary.
	 */
	{
		const swapz_u32 victim = 1U;
		const swapz_u32 victim_start = victim * SWAPZ_SEGMENT_BLOCKS;
		const swapz_u32 spare_start = logical_pages;
		const swapz_u32 spare_segment =
			spare_start / SWAPZ_SEGMENT_BLOCKS;
		const swapz_u32 moved_first = victim_start + 1U;
		const swapz_u32 moved_end = victim_start + SWAPZ_SEGMENT_BLOCKS;

		REQUIRE_CLAIM(spare_start + SWAPZ_SEGMENT_BLOCKS <=
			      reserve_segment * SWAPZ_SEGMENT_BLOCKS);
		for (logical = moved_first; logical < moved_end; ++logical) {
			swapz_u32 new_start = spare_start + logical - moved_first;

			large_maps[logical].start_block = new_start;
			large_live[logical] = 0U;
			large_classes[logical] = 0U;
			large_live[new_start] = 1U;
			large_classes[new_start] = 1U;
		}
		large_counts[victim] = 1U;
		large_counts[spare_segment] = SWAPZ_SEGMENT_BLOCKS - 1U;
		large_programs[spare_segment] = 1U;
		for (repeat = 0; repeat < CLAIM_SCAN_REPEATS; ++repeat) {
			struct swapz_map old_map = large_maps[victim_start];
			struct swapz_tx tx;
			swapz_u32 page = victim_start;
			swapz_u32 destination = spare_start +
				SWAPZ_SEGMENT_BLOCKS - 1U;

			sample = authority;
			sample.open_segment = spare_segment;
			sample.next_block = destination;
			REQUIRE_CLAIM(swapz_stage(
				&sample, &page, 1U, 1U, &tx) == 0);
			REQUIRE_CLAIM(tx.start_block == destination);
			clock_start = now_ns();
			cpu_start = thread_cpu_ns();
			REQUIRE_CLAIM(swapz_finish_raw(
				&sample, &tx, raw_page, 1U, 0) == 0);
			final_publish_wall[repeat] = now_ns() - clock_start;
			final_publish_cpu[repeat] =
				thread_cpu_ns() - cpu_start;
			if (final_publish_wall[repeat] > final_publish_worst)
				final_publish_worst =
					final_publish_wall[repeat];

			large_maps[victim_start] = old_map;
			large_live[victim_start] = 1U;
			large_classes[victim_start] = 1U;
			large_live[destination] = 0U;
			large_classes[destination] = 0U;
			large_counts[victim] = 1U;
			large_counts[spare_segment] =
				SWAPZ_SEGMENT_BLOCKS - 1U;
		}
		for (logical = moved_first; logical < moved_end; ++logical) {
			swapz_u32 moved_start =
				spare_start + logical - moved_first;

			large_maps[logical].start_block = logical;
			large_live[moved_start] = 0U;
			large_classes[moved_start] = 0U;
			large_live[logical] = 1U;
			large_classes[logical] = 1U;
		}
		large_counts[victim] = SWAPZ_SEGMENT_BLOCKS;
		large_counts[spare_segment] = 0U;
	}

	/*
	 * Isolate the second authoritative proof at GC commit. Manufacture
	 * already-evacuated, mutually consistent metadata only; live relocation
	 * and its byte oracle are tested separately by gc/high-occupancy.c.
	 * No lower device I/O is timed or simulated as a physical write.
	 */
	{
		const swapz_u32 spare_start = logical_pages;
		const swapz_u32 reserve_start =
			reserve_segment * SWAPZ_SEGMENT_BLOCKS;

		for (logical = SWAPZ_SEGMENT_BLOCKS;
		     logical < 2U * SWAPZ_SEGMENT_BLOCKS; ++logical) {
			swapz_u32 new_start =
				spare_start + logical - SWAPZ_SEGMENT_BLOCKS;

			large_maps[logical].start_block = new_start;
			large_live[logical] = 0U;
			large_classes[logical] = 0U;
			large_live[new_start] = 1U;
			large_classes[new_start] = 1U;
		}
		large_counts[1U] = 0;
		large_counts[spare_start / SWAPZ_SEGMENT_BLOCKS] =
			SWAPZ_SEGMENT_BLOCKS;
		REQUIRE_CLAIM(spare_start + SWAPZ_SEGMENT_BLOCKS <=
			      reserve_start);
		for (repeat = 0; repeat < CLAIM_SCAN_REPEATS; ++repeat) {
			large_roles[1U] = 1;
			large_roles[reserve_segment] = 0;
			large_programs[reserve_segment] = 1;
			sample = authority;
			REQUIRE_CLAIM(swapz_gc_begin_rotation(
				&sample, 1U) == 0);
			REQUIRE_CLAIM(sample.gc_destination ==
				      reserve_segment);
			/* A single successfully relocated record creates
			 * foreground progress and a consistent destination. */
			large_maps[SWAPZ_SEGMENT_BLOCKS].start_block =
				reserve_start;
			large_counts[spare_start / SWAPZ_SEGMENT_BLOCKS]--;
			large_counts[reserve_segment]++;
			large_live[spare_start] = 0U;
			large_classes[spare_start] = 0U;
			large_live[reserve_start] = 1U;
			large_classes[reserve_start] = 1U;
			sample.next_block = reserve_start + 1U;
			clock_start = now_ns();
			cpu_start = thread_cpu_ns();
			REQUIRE_CLAIM(swapz_gc_commit_rotation(
				&sample, 1U) == 0);
			commit_wall[repeat] = now_ns() - clock_start;
			commit_cpu[repeat] = thread_cpu_ns() - cpu_start;
			REQUIRE_CLAIM(!large_roles[1U] &&
				      large_roles[reserve_segment] &&
				      !sample.gc_allocation);
			if (commit_wall[repeat] > commit_worst)
				commit_worst = commit_wall[repeat];
			large_maps[SWAPZ_SEGMENT_BLOCKS].start_block =
				spare_start;
			large_counts[spare_start / SWAPZ_SEGMENT_BLOCKS]++;
			large_counts[reserve_segment]--;
			large_live[spare_start] = 1U;
			large_classes[spare_start] = 1U;
			large_live[reserve_start] = 0U;
			large_classes[reserve_start] = 0U;
		}
	}

	/*
	 * The recovery/commit proof must visit the final logical entry and
	 * authenticate physical descriptors on survivors outside the victim.
	 * All refusal checks precede role changes, including falsely zero
	 * victim mapped-page sidecars and nonzero 2-block extent interiors.
	 */
	{
		const swapz_u32 victim_start = SWAPZ_SEGMENT_BLOCKS;
		const swapz_u32 spare_start = logical_pages;
		const swapz_u32 spare_segment =
			spare_start / SWAPZ_SEGMENT_BLOCKS;
		const swapz_u32 reserve_start =
			reserve_segment * SWAPZ_SEGMENT_BLOCKS;
		const swapz_u32 tail = logical_pages - 1U;
		const swapz_u32 tail_segment = tail / SWAPZ_SEGMENT_BLOCKS;

		large_roles[1U] = 1U;
		large_roles[reserve_segment] = 0U;
		large_programs[reserve_segment] = 1U;
		sample = authority;
		REQUIRE_CLAIM(swapz_gc_begin_rotation(&sample, 1U) == 0);
		large_maps[victim_start].start_block = reserve_start;
		large_counts[spare_segment]--;
		large_counts[reserve_segment]++;
		large_live[spare_start] = 0U;
		large_classes[spare_start] = 0U;
		large_live[reserve_start] = 1U;
		large_classes[reserve_start] = 1U;
		sample.next_block = reserve_start + 1U;

		/* The cached victim occupancy alone may not authorize reuse. */
		large_counts[1U] = 1U;
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_counts[1U] = 0U;

		/* The last valid map has a false-zero physical class at its start. */
		large_classes[tail] = 0U;
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_classes[tail] = 1U;

		/* Start-block liveness is an independent physical witness. */
		large_live[tail] = 0U;
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_live[tail] = 1U;

		/* A false-zero victim count cannot hide a tail reference. */
		large_maps[tail].start_block = victim_start;
		/* Physical sidecars remain zero, so only the full logical-map
		 * proof can find this forged final-entry victim reference. */
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_maps[tail].start_block = tail;

		/*
		 * Build one otherwise-clean two-block survivor. Class and liveness
		 * interior corruption are rejected independently; neither witness
		 * may be dropped from the recovery-role proof.
		 */
		REQUIRE_CLAIM(large_counts[tail_segment] >= 2U);
		large_maps[tail - 1U].valid = 0U;
		large_counts[tail_segment]--;
		large_maps[tail].start_block = tail - 1U;
		large_maps[tail].payload_offset =
			sizeof(struct swapz_header) + sizeof(struct swapz_record);
		large_maps[tail].payload_length = 128U;
		large_maps[tail].record_index = 0U;
		large_maps[tail].extent_blocks = 2U;
		large_maps[tail].raw = 0U;
		REQUIRE_CLAIM(!large_maps[tail].raw);
		large_classes[tail - 1U] = 2U;
		large_classes[tail] = 0U;
		large_live[tail] = 0U;

		large_classes[tail] = 1U;
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_classes[tail] = 0U;

		large_live[tail] = 1U;
		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
		REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
			      !large_roles[reserve_segment]);
		large_live[tail] = 0U;

		/* Advance uses the same full-map authentication. A late corrupt
		 * compressed interior must not mutate cursor or reserve roles. */
		{
			const swapz_u32 saved_next = sample.next_block;

			sample.next_block =
				reserve_start + SWAPZ_SEGMENT_BLOCKS - 1U;
			large_classes[tail] = 1U;
			REQUIRE_TIMED_CLAIM(swapz_gc_advance_rotation_destination(
				      &sample, reserve_segment), -EUCLEAN);
			REQUIRE_CLAIM(sample.next_block ==
				      reserve_start + SWAPZ_SEGMENT_BLOCKS - 1U &&
				      sample.gc_destination == reserve_segment &&
				      sample.gc_forbidden_victim == 1U &&
				      large_roles[1U] && !large_roles[reserve_segment]);
			large_classes[tail] = 0U;
			sample.next_block = saved_next;
		}

		/* Retain the historical two-block checks above, then authenticate
		 * all three interiors of a four-block compressed tail extent. */
		REQUIRE_CLAIM(large_counts[tail_segment] >= 3U);
		large_maps[tail - 3U].valid = 0U;
		large_maps[tail - 2U].valid = 0U;
		large_counts[tail_segment] -= 2U;
		large_maps[tail].start_block = tail - 3U;
		large_maps[tail].extent_blocks = 4U;
		large_maps[tail].raw = 0U;
		REQUIRE_CLAIM(!large_maps[tail].raw);
		large_classes[tail - 3U] = 4U;
		large_live[tail - 3U] = 1U;
		large_classes[tail - 2U] = 0U;
		large_live[tail - 2U] = 0U;
		large_classes[tail - 1U] = 0U;
		large_live[tail - 1U] = 0U;
		large_classes[tail] = 0U;
		large_live[tail] = 0U;
		for (swapz_u8 block_offset = 1U; block_offset < 4U;
		     ++block_offset) {
			const swapz_u32 interior = tail - 3U + block_offset;

			large_classes[interior] = 1U;
			REQUIRE_TIMED_CLAIM(
				swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
			REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
				      !large_roles[reserve_segment]);
			large_classes[interior] = 0U;

			large_live[interior] = 1U;
			REQUIRE_TIMED_CLAIM(
				swapz_gc_commit_rotation(&sample, 1U), -EUCLEAN);
			REQUIRE_CLAIM(sample.gc_allocation && large_roles[1U] &&
				      !large_roles[reserve_segment]);
			large_live[interior] = 0U;
		}

		REQUIRE_TIMED_CLAIM(swapz_gc_commit_rotation(&sample, 1U), 0);
		REQUIRE_CLAIM(!sample.gc_allocation && !large_roles[1U] &&
			      large_roles[reserve_segment]);
	}

	{
		uint64_t virgin_median = scan_median(virgin_wall);
		uint64_t claimed_median = scan_median(claimed_wall);
		uint64_t virgin_cpu_median = scan_median(virgin_cpu);
		uint64_t claimed_cpu_median = scan_median(claimed_cpu);
		uint64_t traversal_wall_median = scan_median(traversal_wall);
		uint64_t traversal_cpu_median = scan_median(traversal_cpu);
		uint64_t final_publish_wall_median =
			scan_median(final_publish_wall);
		uint64_t final_publish_cpu_median =
			scan_median(final_publish_cpu);
		uint64_t commit_wall_median = scan_median(commit_wall);
		uint64_t commit_cpu_median = scan_median(commit_cpu);
		uint64_t maximum_verified_wall_ns = virgin_worst;

		if (claimed_worst > maximum_verified_wall_ns)
			maximum_verified_wall_ns = claimed_worst;
		if (final_publish_worst > maximum_verified_wall_ns)
			maximum_verified_wall_ns = final_publish_worst;
		if (commit_worst > maximum_verified_wall_ns)
			maximum_verified_wall_ns = commit_worst;
		if (corrupt_wall > maximum_verified_wall_ns)
			maximum_verified_wall_ns = corrupt_wall;
		if (virgin_corrupt_wall > maximum_verified_wall_ns)
			maximum_verified_wall_ns = virgin_corrupt_wall;
		if (recovery_metadata_worst > maximum_verified_wall_ns)
			maximum_verified_wall_ns = recovery_metadata_worst;
		if (max_verified_latency_gate_ns &&
		    maximum_verified_wall_ns > max_verified_latency_gate_ns) {
			fprintf(stderr, "FAIL proof latency geometry=%u observed=%" PRIu64
				" gate=%" PRIu64 " ns\n", logical_pages,
				maximum_verified_wall_ns,
				max_verified_latency_gate_ns);
			goto cleanup;
		}

		printf("SWAPZ_GC_PRODUCTION_CLAIM_SCAN_EVIDENCE={"
		       "\"scope\":\"OFFLINE_NATIVE_PRODUCTION_AUTHORITY\","
		       "\"kernel_only_reschedule_opportunity_entries\":4096,"
		       "\"loaded_kernel_latency\":\"NOT_RUN\","
		       "\"optional_latency_gate_scope\":\"DEVELOPER_HOST_ONLY\","
		       "\"logical_pages\":%u,\"map_bytes\":%" PRIu64 ","
		       "\"repeats\":%u,\"virgin_full_map_scans\":%u,"
		       "\"claimed_full_map_scans\":%u,"
		       "\"virgin_claim_wall_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_wall_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_wall_max_observed_ns\":%" PRIu64 ","
		       "\"virgin_claim_wall_max_observed_ns\":%" PRIu64 ","
		       "\"virgin_claim_cpu_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_cpu_median_ns\":%" PRIu64 ","
		       "\"traversal_control_wall_median_ns\":%" PRIu64 ","
		       "\"traversal_control_cpu_median_ns\":%" PRIu64 ","
		       "\"virgin_effective_map_gbps\":%.3f,"
		       "\"claimed_effective_map_gbps\":%.3f,"
		       "\"final_map_publish_wall_median_ns\":%" PRIu64 ","
		       "\"final_map_publish_cpu_median_ns\":%" PRIu64 ","
		       "\"final_map_publish_max_observed_ns\":%" PRIu64 ","
		       "\"synthetic_gc_commit_wall_median_ns\":%" PRIu64 ","
		       "\"synthetic_gc_commit_cpu_median_ns\":%" PRIu64 ","
		       "\"synthetic_gc_commit_max_observed_ns\":%" PRIu64 ","
		       "\"recovery_metadata_wall_max_observed_ns\":%" PRIu64 ","
		       "\"max_verified_transition_wall_ns\":%" PRIu64 ","
		       "\"latency_gate_ns\":%" PRIu64 ","
		       "\"claimed_last_entry_corruption_rejected_wall_ns\":%" PRIu64 ","
		       "\"virgin_last_entry_corruption_rejected_wall_ns\":%" PRIu64 "}\n",
		       logical_pages, map_bytes, CLAIM_SCAN_REPEATS,
		       CLAIM_SCAN_REPEATS, CLAIM_SCAN_REPEATS,
		       virgin_median, claimed_median, claimed_worst,
		       virgin_worst, virgin_cpu_median, claimed_cpu_median,
		       traversal_wall_median, traversal_cpu_median,
		       virgin_median ? (double)map_bytes /
				      (double)virgin_median : 0.0,
		       claimed_median ? (double)map_bytes /
				       (double)claimed_median : 0.0,
		       final_publish_wall_median, final_publish_cpu_median,
		       final_publish_worst,
		       commit_wall_median, commit_cpu_median, commit_worst,
		       recovery_metadata_worst, maximum_verified_wall_ns,
		       max_verified_latency_gate_ns,
		       corrupt_wall, virgin_corrupt_wall);
	}
	result = 0;
cleanup:
	free(large_programs);
	free(large_counts);
	free(large_roles);
	free(large_classes);
	free(large_live);
	free(large_maps);
#undef REQUIRE_TIMED_CLAIM
#undef REQUIRE_CLAIM
	return result;
}


struct swapz_discard_scaling_measurement {
	swapz_u32 discard_pages;
	swapz_u32 dead_segment_transitions;
	uint64_t full_map_scans;
	uint64_t mappings_examined;
	uint64_t cpu_ns;
};

static int prepare_manual_discard_authority(
	struct swapz_authority *authority, struct swapz_map *test_maps,
	swapz_u16 *test_live, swapz_u8 *test_classes, swapz_u8 *test_roles,
	swapz_u32 *test_mapped_pages, swapz_u32 logical_pages,
	swapz_u32 physical_blocks, swapz_u32 valid_pages)
{
	swapz_u32 logical;
	swapz_u32 segments = physical_blocks / SWAPZ_SEGMENT_BLOCKS;

	CHECK(valid_pages <= logical_pages);
	CHECK(swapz_authority_init(authority, test_maps, test_live,
				   test_classes, logical_pages,
				   physical_blocks) == 0);
	CHECK(swapz_enable_segment_rotation(authority, test_roles,
					    segments) == 0);
	CHECK(swapz_enable_segment_mapping_counts(authority,
						   test_mapped_pages,
						   segments) == 0);
	for (logical = 0; logical < valid_pages; ++logical) {
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
		test_mapped_pages[logical / SWAPZ_SEGMENT_BLOCKS]++;
	}
	/*
	 * These maps model already-published cold swap pages. No allocation cursor
	 * is active while DISCARD runs, so every populated segment is closed and
	 * a final-map removal exercises the production authoritative proof.
	 */
	authority->open_segment = ~(swapz_u32)0;
	return 0;
}

static int measure_dense_discard_scaling(
	swapz_u32 discard_pages, struct swapz_discard_scaling_measurement *result)
{
	enum {
		DENSE_LOGICAL_PAGES = 100001U,
		DENSE_PHYSICAL_BLOCKS = 131072U,
		DENSE_SEGMENTS = DENSE_PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS,
	};
	struct swapz_authority authority;
	struct swapz_map *test_maps = NULL;
	swapz_u16 *test_live = NULL;
	swapz_u8 *test_classes = NULL, *test_roles = NULL;
	swapz_u32 *test_mapped_pages = NULL;
	swapz_u32 logical, dead_segments;
	uint64_t cpu_start, cpu_end;
	int status = 1;

#define REQUIRE_DENSE(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: FAIL dense discard pages=%u: %s\n", \
		__FILE__, __LINE__, discard_pages, #condition); \
	goto cleanup; \
} } while (0)

	REQUIRE_DENSE(result && discard_pages &&
		      discard_pages < DENSE_LOGICAL_PAGES);
	test_maps = calloc(DENSE_LOGICAL_PAGES, sizeof(*test_maps));
	test_live = calloc(DENSE_PHYSICAL_BLOCKS, sizeof(*test_live));
	test_classes = calloc(DENSE_PHYSICAL_BLOCKS, sizeof(*test_classes));
	test_roles = calloc(DENSE_SEGMENTS, sizeof(*test_roles));
	test_mapped_pages = calloc(DENSE_SEGMENTS, sizeof(*test_mapped_pages));
	REQUIRE_DENSE(test_maps && test_live && test_classes &&
		      test_roles && test_mapped_pages);
	REQUIRE_DENSE(prepare_manual_discard_authority(
		      &authority, test_maps, test_live, test_classes,
		      test_roles, test_mapped_pages, DENSE_LOGICAL_PAGES,
		      DENSE_PHYSICAL_BLOCKS, DENSE_LOGICAL_PAGES) == 0);

	cpu_start = thread_cpu_ns();
	REQUIRE_DENSE(cpu_start);
	REQUIRE_DENSE(swapz_prevalidate_discard_range(
		      &authority, 0U, discard_pages) == 0);
	for (logical = 0; logical < discard_pages; ++logical)
		REQUIRE_DENSE(swapz_discard_page(&authority, logical) == 0);
	cpu_end = thread_cpu_ns();
	REQUIRE_DENSE(cpu_end >= cpu_start);

	dead_segments = discard_pages / SWAPZ_SEGMENT_BLOCKS;
	for (logical = 0; logical < discard_pages; ++logical)
		REQUIRE_DENSE(!test_maps[logical].valid &&
			      test_maps[logical].generation == 2U &&
			      !test_live[logical]);
	REQUIRE_DENSE(test_maps[discard_pages].valid &&
		      test_maps[discard_pages].generation == 1U &&
		      test_live[discard_pages] == 1U);
	for (logical = 0; logical < dead_segments; ++logical)
		REQUIRE_DENSE(!test_mapped_pages[logical]);
	{
		swapz_u32 partial_start =
			dead_segments * SWAPZ_SEGMENT_BLOCKS;
		swapz_u32 initial_partial =
			DENSE_LOGICAL_PAGES - partial_start;
		swapz_u32 removed_partial =
			discard_pages - partial_start;

		if (initial_partial > SWAPZ_SEGMENT_BLOCKS)
			initial_partial = SWAPZ_SEGMENT_BLOCKS;
		REQUIRE_DENSE(test_mapped_pages[dead_segments] ==
			      initial_partial - removed_partial);
	}

	result->discard_pages = discard_pages;
	result->dead_segment_transitions = dead_segments;
	/* One range-wide preflight proof plus one proof for every closed segment
	 * whose final mapping is committed by swapz_discard_page(). */
	result->full_map_scans = 1ULL + dead_segments;
	result->mappings_examined =
		result->full_map_scans * DENSE_LOGICAL_PAGES;
	result->cpu_ns = cpu_end - cpu_start;
	status = 0;
cleanup:
	free(test_mapped_pages);
	free(test_roles);
	free(test_classes);
	free(test_live);
	free(test_maps);
#undef REQUIRE_DENSE
	return status;
}

static int measure_sparse_discard_scaling(
	swapz_u32 discard_pages, struct swapz_discard_scaling_measurement *result)
{
	enum {
		SPARSE_LOGICAL_PAGES = 4096U,
		SPARSE_PHYSICAL_BLOCKS = 8192U,
		SPARSE_SEGMENTS = SPARSE_PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS,
	};
	struct swapz_authority authority;
	struct swapz_map *test_maps = NULL;
	swapz_u16 *test_live = NULL;
	swapz_u8 *test_classes = NULL, *test_roles = NULL;
	swapz_u32 *test_mapped_pages = NULL;
	swapz_u32 iteration;
	uint64_t cpu_start, cpu_end;
	int status = 1;

#define REQUIRE_SPARSE(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: FAIL sparse discard pages=%u: %s\n", \
		__FILE__, __LINE__, discard_pages, #condition); \
	goto cleanup; \
} } while (0)

	REQUIRE_SPARSE(result && discard_pages);
	test_maps = calloc(SPARSE_LOGICAL_PAGES, sizeof(*test_maps));
	test_live = calloc(SPARSE_PHYSICAL_BLOCKS, sizeof(*test_live));
	test_classes = calloc(SPARSE_PHYSICAL_BLOCKS, sizeof(*test_classes));
	test_roles = calloc(SPARSE_SEGMENTS, sizeof(*test_roles));
	test_mapped_pages = calloc(SPARSE_SEGMENTS, sizeof(*test_mapped_pages));
	REQUIRE_SPARSE(test_maps && test_live && test_classes &&
		       test_roles && test_mapped_pages);
	REQUIRE_SPARSE(prepare_manual_discard_authority(
		       &authority, test_maps, test_live, test_classes,
		       test_roles, test_mapped_pages, SPARSE_LOGICAL_PAGES,
		       SPARSE_PHYSICAL_BLOCKS, 1U) == 0);

	cpu_start = thread_cpu_ns();
	REQUIRE_SPARSE(cpu_start);
	for (iteration = 0; iteration < discard_pages; ++iteration) {
		REQUIRE_SPARSE(swapz_prevalidate_discard_range(
			       &authority, 0U, 1U) == 0);
		REQUIRE_SPARSE(swapz_discard_page(&authority, 0U) == 0);
		REQUIRE_SPARSE(!test_maps[0].valid && !test_live[0] &&
			       !test_mapped_pages[0]);
		if (iteration + 1U != discard_pages) {
			/*
			 * Test-only rearm isolates repeated final-map proof cost.
			 * Correct production slot reuse/generation publication remains
			 * covered by the authority/raw/GC suites.
			 */
			test_maps[0].valid = 1U;
			test_live[0] = 1U;
			test_mapped_pages[0] = 1U;
		}
	}
	cpu_end = thread_cpu_ns();
	REQUIRE_SPARSE(cpu_end >= cpu_start);

	result->discard_pages = discard_pages;
	result->dead_segment_transitions = discard_pages;
	/* Each one-page upper range runs its range proof, then the final-map proof. */
	result->full_map_scans = 2ULL * discard_pages;
	result->mappings_examined =
		result->full_map_scans * SPARSE_LOGICAL_PAGES;
	result->cpu_ns = cpu_end - cpu_start;
	status = 0;
cleanup:
	free(test_mapped_pages);
	free(test_roles);
	free(test_classes);
	free(test_live);
	free(test_maps);
#undef REQUIRE_SPARSE
	return status;
}

static void print_discard_scaling_evidence(
	const char *pattern, swapz_u32 logical_pages,
	const struct swapz_discard_scaling_measurement *result)
{
	printf("SWAPZ_DISCARD_SCALING_EVIDENCE={"
	       "\"scope\":\"OFFLINE_NATIVE_PRODUCTION_AUTHORITY\","
	       "\"pattern\":\"%s\",\"logical_pages\":%u,"
	       "\"discard_pages\":%u,\"dead_segment_transitions\":%u,"
	       "\"complete_table_verification_scans\":%" PRIu64 ","
	       "\"logical_mappings_examined\":%" PRIu64 ","
	       "\"thread_cpu_ns\":%" PRIu64 ","
	       "\"operation_allocations\":0,\"lower_read_bytes\":0,"
	       "\"decompression_calls\":0}\n",
	       pattern, logical_pages, result->discard_pages,
	       result->dead_segment_transitions, result->full_map_scans,
	       result->mappings_examined, result->cpu_ns);
}

static int measure_discard_scaling(void)
{
	struct swapz_discard_scaling_measurement dense_1000 = {0};
	struct swapz_discard_scaling_measurement dense_100000 = {0};
	struct swapz_discard_scaling_measurement sparse_1000 = {0};
	struct swapz_discard_scaling_measurement sparse_100000 = {0};

	CHECK(measure_dense_discard_scaling(1000U, &dense_1000) == 0);
	CHECK(measure_dense_discard_scaling(100000U, &dense_100000) == 0);
	CHECK(measure_sparse_discard_scaling(1000U, &sparse_1000) == 0);
	CHECK(measure_sparse_discard_scaling(100000U, &sparse_100000) == 0);
	print_discard_scaling_evidence("dense", 100001U, &dense_1000);
	print_discard_scaling_evidence("dense", 100001U, &dense_100000);
	print_discard_scaling_evidence("sparse-final-map", 4096U, &sparse_1000);
	print_discard_scaling_evidence("sparse-final-map", 4096U, &sparse_100000);
	return 0;
}

int main(void)
{
	swapz_u8 raw_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 compressed_extent[SWAPZ_BLOCK_BYTES];
	swapz_u8 payload[1800];
	swapz_u8 tiny_payload[32];
	swapz_u8 checked_extent[SWAPZ_BLOCK_BYTES];
	swapz_u8 unique_extent[SWAPZ_BLOCK_BYTES];
	uint64_t total_finish_raw_ns = 0;
	uint64_t total_finish_compressed_ns = 0;
	uint64_t total_discard_ns = 0;
	uint64_t full_validate_ns = 0, metadata_validate_ns = 0;
	uint64_t checked_append_ns = 0, unique_append_ns = 0;
	swapz_u32 total_finish_raw_ops = 0;
	swapz_u32 total_finish_compressed_ops = 0;
	swapz_u32 total_discard_ops = 0;
	unsigned int round;
	const char *latency_gate = getenv("SWAPZ_GC_MAX_PROOF_WALL_NS");

	if (latency_gate && *latency_gate) {
		char *end = NULL;
		unsigned long long parsed;

		errno = 0;
		parsed = strtoull(latency_gate, &end, 10);
		CHECK(!errno && end != latency_gate && !*end && parsed);
		max_verified_latency_gate_ns = (uint64_t)parsed;
	}

	memset(raw_page, 0x5a, sizeof(raw_page));
	memset(payload, 0x3c, sizeof(payload));
	memset(tiny_payload, 0x2d, sizeof(tiny_payload));

	{
		struct swapz_builder builder;
		swapz_u32 crc = swapz_crc32c_bytes(tiny_payload,
						   sizeof(tiny_payload));
		swapz_u32 page;
		uint64_t start, end;

		CHECK(swapz_begin(&builder, checked_extent,
				  sizeof(checked_extent), 1) == 0);
		for (page = 0; page < SWAPZ_MAX_RECORDS; ++page)
			CHECK(swapz_append_prehashed_encoded(
				&builder, page, 1, tiny_payload,
				sizeof(tiny_payload), crc,
				SWAPZ_ENCODING_LZ4) == 0);
		CHECK(swapz_seal(&builder) == 0);
		memcpy(unique_extent, checked_extent, sizeof(unique_extent));

		start = now_ns();
		for (round = 0; round < VALIDATE_ROUNDS; ++round)
			CHECK(swapz_validate(checked_extent,
					     sizeof(checked_extent)) == 0);
		end = now_ns();
		if (end >= start)
			full_validate_ns = end - start;

		start = now_ns();
		for (round = 0; round < VALIDATE_ROUNDS; ++round)
			CHECK(swapz_validate_metadata_crc(
				checked_extent, sizeof(checked_extent)) == 0);
		end = now_ns();
		if (end >= start)
			metadata_validate_ns = end - start;

		start = now_ns();
		for (round = 0; round < APPEND_ROUNDS; ++round) {
			CHECK(swapz_begin(&builder, checked_extent,
					  sizeof(checked_extent), 1) == 0);
			for (page = 0; page < SWAPZ_MAX_RECORDS; ++page)
				CHECK(swapz_append_prehashed_encoded(
					&builder, page, 1, tiny_payload,
					sizeof(tiny_payload), crc,
					SWAPZ_ENCODING_LZ4) == 0);
		}
		end = now_ns();
		if (end >= start)
			checked_append_ns = end - start;

		start = now_ns();
		for (round = 0; round < APPEND_ROUNDS; ++round) {
			CHECK(swapz_begin(&builder, unique_extent,
					  sizeof(unique_extent), 1) == 0);
			for (page = 0; page < SWAPZ_MAX_RECORDS; ++page)
				CHECK(swapz_append_prehashed_encoded_unique(
					&builder, page, 1, tiny_payload,
					sizeof(tiny_payload), crc,
					SWAPZ_ENCODING_LZ4) == 0);
		}
		end = now_ns();
		if (end >= start)
			unique_append_ns = end - start;

		CHECK(!memcmp(checked_extent, unique_extent,
			      sizeof(checked_extent)));
	}

	CHECK(test_legacy_reuse_rejects_cross_segment_map() == 0);
	CHECK(init_authority() == 0);

	for (round = 0; round < BENCH_ROUNDS; ++round) {
		swapz_u32 page;
		uint64_t start, end;

		/* 1. Benchmark swapz_finish_raw across 512 pages */
		for (page = 0; page < 512; ++page) {
			struct swapz_tx tx;

			CHECK(swapz_stage(&a, &page, 1, 1, &tx) == 0);
			start = now_ns();
			CHECK(swapz_finish_raw(&a, &tx, raw_page, 1, 0) == 0);
			end = now_ns();
			if (end >= start)
				total_finish_raw_ns += (end - start);
			total_finish_raw_ops++;
		}

		/* 2. Benchmark swapz_finish (compressed pairs) overwriting those 512 pages */
		for (page = 0; page < 512; page += EXTENT_RECORDS) {
			struct swapz_tx tx;
			struct swapz_builder b;
			swapz_u32 pages[EXTENT_RECORDS];
			swapz_u8 i;

			for (i = 0; i < EXTENT_RECORDS; ++i)
				pages[i] = page + i;
			CHECK(swapz_stage(&a, pages, EXTENT_RECORDS, 1, &tx) == 0);
			CHECK(swapz_begin(&b, compressed_extent,
					  sizeof(compressed_extent),
					  tx.sequence) == 0);
			for (i = 0; i < EXTENT_RECORDS; ++i)
				CHECK(swapz_append(&b, pages[i],
						   tx.records[i].generation,
						   payload, sizeof(payload)) == 0);
			CHECK(swapz_seal(&b) == 0);
			start = now_ns();
			CHECK(swapz_finish(&a, &tx, compressed_extent,
					   sizeof(compressed_extent), 1, 0) == 0);
			end = now_ns();
			if (end >= start)
				total_finish_compressed_ns += (end - start);
			total_finish_compressed_ops++;
		}

		/* 3. Benchmark swapz_discard_page across the 512 pages */
		for (page = 0; page < 512; ++page) {
			start = now_ns();
			CHECK(swapz_discard_page(&a, page) == 0);
			end = now_ns();
			if (end >= start)
				total_discard_ns += (end - start);
			total_discard_ops++;
		}
	}

	{
		uint64_t avg_finish_raw_ns = total_finish_raw_ops ?
			total_finish_raw_ns / total_finish_raw_ops : 0;
		uint64_t avg_finish_compressed_ns = total_finish_compressed_ops ?
			total_finish_compressed_ns / total_finish_compressed_ops : 0;
		uint64_t avg_discard_ns = total_discard_ops ?
			total_discard_ns / total_discard_ops : 0;

		printf("SWAPZ_AUTHORITY_THROUGHPUT_EVIDENCE={\"scope\":"
		       "\"OFFLINE_NATIVE_AUTHORITY_THROUGHPUT\",\"rounds\":%u,"
		       "\"finish_raw\":{\"ops\":%" PRIu32 ",\"ns_per_op\":%" PRIu64 "},"
		       "\"finish_compressed\":{\"ops\":%" PRIu32 ",\"ns_per_op\":%" PRIu64 "},"
		       "\"discard_page\":{\"ops\":%" PRIu32 ",\"ns_per_op\":%" PRIu64 "},"
		       "\"validate64_full\":{\"calls\":%u,\"ns_per_call\":%" PRIu64 "},"
		       "\"validate64_metadata_crc\":{\"calls\":%u,\"ns_per_call\":%" PRIu64 "},"
		       "\"append64_checked\":{\"extents\":%u,\"ns_per_extent\":%" PRIu64 "},"
		       "\"append64_unique\":{\"extents\":%u,\"ns_per_extent\":%" PRIu64 "}}\n",
		       BENCH_ROUNDS,
		       total_finish_raw_ops, avg_finish_raw_ns,
		       total_finish_compressed_ops, avg_finish_compressed_ns,
		       total_discard_ops, avg_discard_ns,
		       VALIDATE_ROUNDS,
		       full_validate_ns / VALIDATE_ROUNDS,
		       VALIDATE_ROUNDS,
		       metadata_validate_ns / VALIDATE_ROUNDS,
		       APPEND_ROUNDS,
		       checked_append_ns / APPEND_ROUNDS,
		       APPEND_ROUNDS,
		       unique_append_ns / APPEND_ROUNDS);
		printf("PASS: authority finish and discard throughput microbenchmark\n");
	}
	/* Allocation-free upper-DISCARD authority work, with no lower I/O. */
	CHECK(measure_discard_scaling() == 0);
	/* Actual production-C authority path; measured separately from GC I/O. */
	CHECK(measure_production_claim_proof(262144U) == 0);
	CHECK(measure_production_claim_proof(1048576U) == 0);
	CHECK(measure_production_claim_proof(4194304U) == 0);
	CHECK(measure_production_claim_proof(27080192U) == 0);
	return 0;
}
