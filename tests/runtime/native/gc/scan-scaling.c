// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "gc-cost.h"

#define REPEATS 7U
#define GEOMETRIES 2U

struct scale_row {
	swapz_u32 logical_pages;
	swapz_u32 segments;
	uint64_t legacy_score_scan_ns;
	uint64_t incremental_select_ns;
	uint64_t relocation_scan_ns;
	uint64_t legacy_dead_probe_ns;
	uint64_t mapped_dead_probe_ns;
	swapz_u32 victim_records;
};

static volatile uint64_t evidence_sink;

static uint64_t now_ns(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts))
		return 0;
	return (uint64_t)ts.tv_sec * UINT64_C(1000000000) +
	       (uint64_t)ts.tv_nsec;
}

static int compare_u64(const void *left, const void *right)
{
	uint64_t a = *(const uint64_t *)left;
	uint64_t b = *(const uint64_t *)right;

	return (a > b) - (a < b);
}

static uint64_t median_ns(uint64_t values[REPEATS])
{
	qsort(values, REPEATS, sizeof(values[0]), compare_u64);
	return values[REPEATS / 2U];
}

static uint64_t legacy_score_scan(const struct swapz_map *maps,
				  swapz_u32 logical_pages,
				  swapz_u32 segments,
				  swapz_u32 *bytes,
				  swapz_u32 *io,
				  swapz_u16 *counts,
				  swapz_u16 *min_blocks)
{
	swapz_u32 logical;
	uint64_t start;

	memset(bytes, 0, (size_t)segments * sizeof(*bytes));
	memset(io, 0, (size_t)segments * sizeof(*io));
	memset(counts, 0, (size_t)segments * sizeof(*counts));
	memset(min_blocks, 0, (size_t)segments * sizeof(*min_blocks));
	start = now_ns();
	for (logical = 0; logical < logical_pages; ++logical) {
		const struct swapz_map *m = &maps[logical];
		swapz_u32 segment = m->start_block / SWAPZ_SEGMENT_BLOCKS;
		swapz_u32 live = swapz_gc_live_byte_cost(m);
		swapz_u32 io_cost = swapz_gc_estimated_io_cost(m);

		bytes[segment] += live;
		io[segment] += io_cost;
		counts[segment]++;
		min_blocks[segment] += swapz_gc_min_live_blocks(m);
	}
	evidence_sink += bytes[segments / 2U] + io[segments / 2U] +
			 counts[segments / 2U] + min_blocks[segments / 2U];
	return now_ns() - start;
}

static uint64_t incremental_select(swapz_u32 segments,
				   const swapz_u32 *bytes,
				   const swapz_u32 *io,
				   const swapz_u16 *counts,
				   const swapz_u16 *min_blocks)
{
	swapz_u32 segment, selected = ~(swapz_u32)0;
	swapz_u32 best = ~(swapz_u32)0;
	swapz_u16 best_count = ~(swapz_u16)0;
	uint64_t start = now_ns();

	for (segment = 0; segment < segments; ++segment) {
		swapz_u16 count = counts[segment];
		swapz_u32 score;

		if (!count ||
		    !swapz_gc_candidate_can_free_block(bytes[segment],
						       min_blocks[segment]))
			continue;
		score = io[segment];
		if (swapz_gc_prefer(score, count, best, best_count)) {
			best = score;
			best_count = count;
			selected = segment;
		}
	}
	evidence_sink += selected + best + best_count;
	return now_ns() - start;
}

static uint64_t relocation_scan(const struct swapz_map *maps,
				swapz_u32 logical_pages,
				swapz_u32 victim,
				swapz_u32 *records_out)
{
	swapz_u32 logical, records = 0;
	uint64_t start = now_ns();

	for (logical = 0; logical < logical_pages; ++logical)
		records += maps[logical].valid &&
			maps[logical].start_block / SWAPZ_SEGMENT_BLOCKS == victim;
	evidence_sink += records;
	*records_out = records;
	return now_ns() - start;
}

static uint64_t legacy_dead_probe(const swapz_u16 *live_records,
				 const swapz_u8 *extent_classes,
				 const swapz_u32 *mapped_pages,
				 swapz_u32 segments, swapz_u32 *selected_out)
{
	swapz_u32 segment;
	uint64_t start = now_ns();

	*selected_out = ~(swapz_u32)0;
	for (segment = 0; segment < segments; ++segment) {
		swapz_u32 block = segment * SWAPZ_SEGMENT_BLOCKS;
		swapz_u32 off, live_total = 0, used = 0;

		for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off) {
			live_total += live_records[block + off];
			used += extent_classes[block + off] != 0;
		}
		if (live_total != mapped_pages[segment])
			return 0;
		if (live_total)
			continue;
		*selected_out = segment;
		evidence_sink += used;
		break;
	}
	evidence_sink += *selected_out;
	return now_ns() - start;
}

static uint64_t mapped_dead_probe(const swapz_u16 *live_records,
				 const swapz_u8 *extent_classes,
				 const swapz_u32 *mapped_pages,
				 swapz_u32 segments, swapz_u32 *selected_out)
{
	swapz_u32 segment;
	uint64_t start = now_ns();

	*selected_out = ~(swapz_u32)0;
	for (segment = 0; segment < segments; ++segment) {
		swapz_u32 block, off, live_total = 0, used = 0;

		if (mapped_pages[segment])
			continue;
		block = segment * SWAPZ_SEGMENT_BLOCKS;
		for (off = 0; off < SWAPZ_SEGMENT_BLOCKS; ++off) {
			live_total += live_records[block + off];
			used += extent_classes[block + off] != 0;
		}
		if (live_total)
			return 0;
		*selected_out = segment;
		evidence_sink += used;
		break;
	}
	evidence_sink += *selected_out;
	return now_ns() - start;
}

static int run_geometry(swapz_u32 logical_pages, struct scale_row *row)
{
	swapz_u32 segments = logical_pages / SWAPZ_SEGMENT_BLOCKS;
	struct swapz_map *maps = NULL;
	swapz_u32 *bytes = NULL, *io = NULL, *mapped_pages = NULL;
	swapz_u16 *counts = NULL, *min_blocks = NULL, *live_records = NULL;
	swapz_u8 *extent_classes = NULL;
	uint64_t legacy[REPEATS], select[REPEATS], relocation[REPEATS];
	uint64_t legacy_probe[REPEATS], mapped_probe[REPEATS];
	swapz_u32 logical, repeat, records = 0, selected = 0;
	int rc = 1;

	if (!segments || logical_pages % SWAPZ_SEGMENT_BLOCKS)
		return 1;
	maps = calloc(logical_pages, sizeof(*maps));
	bytes = calloc(segments, sizeof(*bytes));
	io = calloc(segments, sizeof(*io));
	counts = calloc(segments, sizeof(*counts));
	min_blocks = calloc(segments, sizeof(*min_blocks));
	mapped_pages = calloc(segments, sizeof(*mapped_pages));
	live_records = calloc(logical_pages, sizeof(*live_records));
	extent_classes = calloc(logical_pages, sizeof(*extent_classes));
	if (!maps || !bytes || !io || !counts || !min_blocks ||
	    !mapped_pages || !live_records || !extent_classes)
		goto out;

	for (logical = 0; logical < logical_pages; ++logical) {
		maps[logical] = (struct swapz_map){
			.start_block = logical,
			.payload_length = (swapz_u16)(1800U + logical % 401U),
			.extent_blocks = 1,
			.valid = 1,
		};
	}
	/*
	 * Near-full allocator geometry: every segment except the final one has
	 * one authoritative start block. The old probe touches all 256 block
	 * entries before consulting mapped_pages; current policy rejects live
	 * segments from the O(1) sidecar and scans only the zero-mapped candidate.
	 */
	for (logical = 0; logical + 1U < segments; ++logical) {
		swapz_u32 block = logical * SWAPZ_SEGMENT_BLOCKS;

		mapped_pages[logical] = 1;
		live_records[block] = 1;
		extent_classes[block] = 1;
	}
	/* Populate the exact incremental state before timing current selection. */
	(void)legacy_score_scan(maps, logical_pages, segments, bytes, io,
				counts, min_blocks);
	for (repeat = 0; repeat < REPEATS; ++repeat) {
		legacy[repeat] = legacy_score_scan(
			maps, logical_pages, segments, bytes, io,
			counts, min_blocks);
		select[repeat] = incremental_select(
			segments, bytes, io, counts, min_blocks);
		relocation[repeat] = relocation_scan(
			maps, logical_pages, segments / 2U, &records);
		legacy_probe[repeat] = legacy_dead_probe(
			live_records, extent_classes, mapped_pages,
			segments, &selected);
		if (selected != segments - 1U)
			goto out;
		mapped_probe[repeat] = mapped_dead_probe(
			live_records, extent_classes, mapped_pages,
			segments, &selected);
		if (selected != segments - 1U)
			goto out;
	}
	if (records != SWAPZ_SEGMENT_BLOCKS)
		goto out;
	*row = (struct scale_row){
		.logical_pages = logical_pages,
		.segments = segments,
		.legacy_score_scan_ns = median_ns(legacy),
		.incremental_select_ns = median_ns(select),
		.relocation_scan_ns = median_ns(relocation),
		.legacy_dead_probe_ns = median_ns(legacy_probe),
		.mapped_dead_probe_ns = median_ns(mapped_probe),
		.victim_records = records,
	};
	rc = 0;
out:
	free(extent_classes);
	free(live_records);
	free(mapped_pages);
	free(min_blocks);
	free(counts);
	free(io);
	free(bytes);
	free(maps);
	return rc;
}

int main(void)
{
	const swapz_u32 sizes[GEOMETRIES] = { 262144U, 1048576U };
	struct scale_row rows[GEOMETRIES];
	unsigned int index;

	for (index = 0; index < GEOMETRIES; ++index)
		if (run_geometry(sizes[index], &rows[index])) {
			fprintf(stderr, "FAIL GC scaling geometry=%u\n", sizes[index]);
			return 1;
		}

	printf("SWAPZ_GC_SCAN_SCALE_EVIDENCE={\"scope\":"
	       "\"OFFLINE_NATIVE_GC_SCALE_ONLY\",\"rows\":[");
	for (index = 0; index < GEOMETRIES; ++index) {
		const struct scale_row *row = &rows[index];

		printf("%s{\"logical_pages\":%u,\"segments\":%u,"
		       "\"legacy_score_scan_ns\":%" PRIu64 ","
		       "\"incremental_select_ns\":%" PRIu64 ","
		       "\"relocation_scan_ns\":%" PRIu64 ","
		       "\"legacy_dead_probe_ns\":%" PRIu64 ","
		       "\"mapped_dead_probe_ns\":%" PRIu64 ","
		       "\"victim_records\":%u}",
		       index ? "," : "", row->logical_pages, row->segments,
		       row->legacy_score_scan_ns, row->incremental_select_ns,
		       row->relocation_scan_ns, row->legacy_dead_probe_ns,
		       row->mapped_dead_probe_ns, row->victim_records);
	}
	puts("]}");
	puts("PASS: GC victim selection is segment-scaled; relocation scan evidence collected");
	return evidence_sink == UINT64_MAX ? 1 : 0;
}
