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

int main(void)
{
	swapz_u8 raw_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 compressed_extent[SWAPZ_BLOCK_BYTES];
	swapz_u8 payload[1800];
	uint64_t total_finish_raw_ns = 0;
	uint64_t total_finish_compressed_ns = 0;
	uint64_t total_discard_ns = 0;
	swapz_u32 total_finish_raw_ops = 0;
	swapz_u32 total_finish_compressed_ops = 0;
	swapz_u32 total_discard_ops = 0;
	unsigned int round;

	memset(raw_page, 0x5a, sizeof(raw_page));
	memset(payload, 0x3c, sizeof(payload));

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
		       "\"discard_page\":{\"ops\":%" PRIu32 ",\"ns_per_op\":%" PRIu64 "}}\n",
		       BENCH_ROUNDS,
		       total_finish_raw_ops, avg_finish_raw_ns,
		       total_finish_compressed_ops, avg_finish_compressed_ns,
		       total_discard_ops, avg_discard_ns);
		printf("PASS: authority finish and discard throughput microbenchmark\n");
	}
	return 0;
}
