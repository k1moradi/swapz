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
 * Measure GC's actual production authority dead-reserve claim, separating
 * a never-claimed segment from the identical, previously-claimed segment.
 * Current production C always scans both: a virgin-count witness can
 * itself be corrupt. The difference between these two paths is therefore
 * NOT scan cost. A matched traversal control is reported separately.
 * Runs offline in one thread, without lower I/O or shared state.
 */
#define CLAIM_SCAN_REPEATS 5U

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
	uint64_t commit_wall[CLAIM_SCAN_REPEATS];
	uint64_t commit_cpu[CLAIM_SCAN_REPEATS];
	uint64_t commit_worst = 0, virgin_corrupt_wall = 0;
	uint64_t claimed_worst = 0, corrupt_wall;
	uint64_t map_bytes = (uint64_t)logical_pages * sizeof(*large_maps);
	uint64_t reserve = (uint64_t)logical_pages / 8U +
			   (logical_pages % 8U != 0U);
	uint64_t physical_64, clock_start, cpu_start;
	swapz_u32 physical_blocks, segments, reserve_segment, logical;
	unsigned int repeat;
	int result = 1;
#define REQUIRE_CLAIM(condition) do { if (!(condition)) { \
	fprintf(stderr, "%s:%d: FAIL claim geometry=%u: %s\n", \
		__FILE__, __LINE__, logical_pages, #condition); \
	goto cleanup; \
} } while (0)

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
	}
	authority.open_segment = 0;
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

	{
		uint64_t virgin_median = scan_median(virgin_wall);
		uint64_t claimed_median = scan_median(claimed_wall);
		uint64_t virgin_cpu_median = scan_median(virgin_cpu);
		uint64_t claimed_cpu_median = scan_median(claimed_cpu);
		uint64_t traversal_wall_median = scan_median(traversal_wall);
		uint64_t traversal_cpu_median = scan_median(traversal_cpu);
		uint64_t commit_wall_median = scan_median(commit_wall);
		uint64_t commit_cpu_median = scan_median(commit_cpu);

		printf("SWAPZ_GC_PRODUCTION_CLAIM_SCAN_EVIDENCE={"
		       "\"scope\":\"OFFLINE_NATIVE_PRODUCTION_AUTHORITY\","
		       "\"logical_pages\":%u,\"map_bytes\":%" PRIu64 ","
		       "\"repeats\":%u,\"virgin_full_map_scans\":%u,"
		       "\"claimed_full_map_scans\":%u,"
		       "\"virgin_claim_wall_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_wall_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_wall_max_observed_ns\":%" PRIu64 ","
		       "\"virgin_claim_cpu_median_ns\":%" PRIu64 ","
		       "\"claimed_claim_cpu_median_ns\":%" PRIu64 ","
		       "\"traversal_control_wall_median_ns\":%" PRIu64 ","
		       "\"traversal_control_cpu_median_ns\":%" PRIu64 ","
		       "\"virgin_effective_map_gbps\":%.3f,"
		       "\"claimed_effective_map_gbps\":%.3f,"
		       "\"synthetic_gc_commit_wall_median_ns\":%" PRIu64 ","
		       "\"synthetic_gc_commit_cpu_median_ns\":%" PRIu64 ","
		       "\"synthetic_gc_commit_max_observed_ns\":%" PRIu64 ","
		       "\"claimed_last_entry_corruption_rejected_wall_ns\":%" PRIu64 ","
		       "\"virgin_last_entry_corruption_rejected_wall_ns\":%" PRIu64 "}\n",
		       logical_pages, map_bytes, CLAIM_SCAN_REPEATS,
		       CLAIM_SCAN_REPEATS, CLAIM_SCAN_REPEATS,
		       virgin_median, claimed_median, claimed_worst,
		       virgin_cpu_median, claimed_cpu_median,
		       traversal_wall_median, traversal_cpu_median,
		       virgin_median ? (double)map_bytes /
				      (double)virgin_median : 0.0,
		       claimed_median ? (double)map_bytes /
				       (double)claimed_median : 0.0,
		       commit_wall_median, commit_cpu_median, commit_worst,
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
#undef REQUIRE_CLAIM
	return result;
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
	/* Actual production-C authority path; measured separately from GC I/O. */
	CHECK(measure_production_claim_proof(262144U) == 0);
	CHECK(measure_production_claim_proof(1048576U) == 0);
	CHECK(measure_production_claim_proof(4194304U) == 0);
	CHECK(measure_production_claim_proof(27080192U) == 0);
	return 0;
}
