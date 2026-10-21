// SPDX-License-Identifier: GPL-2.0-only
/*
 * ID73 offline geometry study. This is a deterministic simulator only:
 * it does not create new SWZ classes, change kernel policy, or touch media.
 */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "codec.h"
#include "authority.h"

#define LOGICAL_PAGES 1024U
#define WINDOW_PAGES 64U
#define NORMAL_WINDOWS 64U
#define GC_INTERVAL 8U
#define GC_SURVIVORS 16U
#define MAX_CLASSES 5U

struct geometry {
	const char *name;
	uint8_t packed;
	uint8_t classes[MAX_CLASSES];
	uint8_t class_count;
};

struct logical_map {
	uint32_t extent_id;
	uint16_t payload_length;
	uint8_t valid;
	uint8_t raw;
	uint8_t cold_blocks;
	uint8_t payload_first;
};

struct study {
	uint64_t physical_blocks;
	uint64_t waste_blocks;
	uint64_t write_runs;
	uint64_t cold_blocks_sum;
	uint64_t cold_pages;
	uint64_t seq_4m_requests;
	uint32_t cursor;
	uint32_t next_extent_id;
	uint32_t run_start;
	uint32_t run_blocks;
	uint8_t run_valid;
	struct logical_map maps[LOGICAL_PAGES];
	uint16_t current_length[LOGICAL_PAGES];
	uint8_t current_raw[LOGICAL_PAGES];
	uint8_t current_valid[LOGICAL_PAGES];
};

struct record {
	uint32_t logical;
	uint16_t length;
	uint8_t raw;
};

struct plan_cell {
	uint32_t blocks;
	uint32_t reads;
	uint16_t extents;
	uint8_t chosen_class;
	uint8_t take;
	uint8_t valid;
};

static uint16_t payload_for(uint32_t logical, uint32_t round, uint8_t *raw)
{
	uint32_t selector = (logical * 17U + round * 13U + (round / 8U) * 7U) % 16U;

	*raw = 0;
	if (selector < 4U)
		return (uint16_t)(64U + (logical * 29U + round * 11U) % 384U);
	if (selector < 9U)
		return (uint16_t)(900U + (logical * 97U + round * 53U) % 2200U);
	if (selector < 13U) {
		static const uint16_t mixed[] = { 400U, 1500U, 2600U, 3400U };

		return mixed[selector - 9U];
	}
	*raw = 1;
	return SWAPZ_BLOCK_BYTES;
}

static uint8_t fit_records(const struct record *records, uint8_t count,
			   uint8_t start, uint8_t blocks, uint32_t *reads_out)
{
	uint32_t payload_start = (uint32_t)blocks * SWAPZ_BLOCK_BYTES;
	uint32_t reads = 0;
	uint8_t take = 0;

	while ((uint8_t)(start + take) < count) {
		const struct record *r = &records[start + take];
		uint32_t offset, first, last;

		if (r->raw || payload_start < r->length)
			break;
		offset = payload_start - r->length;
		if (offset < sizeof(struct swapz_header) +
			     ((uint32_t)take + 1U) * sizeof(struct swapz_record))
			break;
		first = offset / SWAPZ_BLOCK_BYTES;
		last = (payload_start - 1U) / SWAPZ_BLOCK_BYTES;
		reads += last - first + 1U + (first ? 1U : 0U);
		payload_start = offset;
		take++;
	}
	*reads_out = reads;
	return take;
}

static int plan_window(const struct geometry *g, const struct record *records,
		       uint8_t count, uint8_t *classes, uint8_t *takes,
		       uint8_t *extent_count)
{
	struct plan_cell dp[WINDOW_PAGES + 1U];
	int index;

	memset(dp, 0, sizeof(dp));
	dp[count].valid = 1;
	for (index = (int)count - 1; index >= 0; --index) {
		uint8_t ci;

		for (ci = 0; ci < g->class_count; ++ci) {
			uint8_t blocks = g->classes[ci];
			uint32_t local_reads;
			uint8_t take = fit_records(records, count, (uint8_t)index,
						   blocks, &local_reads);
			struct plan_cell *tail;
			uint32_t candidate_blocks, candidate_reads;
			uint16_t candidate_extents;

			if (!take)
				continue;
			tail = &dp[index + take];
			if (!tail->valid)
				continue;
			candidate_blocks = blocks + tail->blocks;
			candidate_reads = local_reads + tail->reads;
			candidate_extents = (uint16_t)(tail->extents + 1U);
			if (!dp[index].valid ||
			    candidate_blocks < dp[index].blocks ||
			    (candidate_blocks == dp[index].blocks &&
			     candidate_reads < dp[index].reads) ||
			    (candidate_blocks == dp[index].blocks &&
			     candidate_reads == dp[index].reads &&
			     candidate_extents < dp[index].extents) ||
			    (candidate_blocks == dp[index].blocks &&
			     candidate_reads == dp[index].reads &&
			     candidate_extents == dp[index].extents &&
			     blocks > dp[index].chosen_class)) {
				dp[index].valid = 1;
				dp[index].blocks = candidate_blocks;
				dp[index].reads = candidate_reads;
				dp[index].extents = candidate_extents;
				dp[index].chosen_class = blocks;
				dp[index].take = take;
			}
		}
	}
	if (!dp[0].valid)
		return -1;
	*extent_count = 0;
	for (index = 0; index < count;) {
		if (!dp[index].take || *extent_count >= WINDOW_PAGES)
			return -1;
		classes[*extent_count] = dp[index].chosen_class;
		takes[*extent_count] = dp[index].take;
		index += dp[index].take;
		(*extent_count)++;
	}
	return 0;
}

static uint32_t place_extent(struct study *s, const struct geometry *g,
			     uint8_t blocks)
{
	uint32_t start = s->cursor;
	uint32_t offset;

	if (!g->packed)
		start = (start + blocks - 1U) & ~(uint32_t)(blocks - 1U);
	offset = start % SWAPZ_SEGMENT_BLOCKS;
	if (offset + blocks > SWAPZ_SEGMENT_BLOCKS) {
		uint32_t tail = SWAPZ_SEGMENT_BLOCKS - (s->cursor % SWAPZ_SEGMENT_BLOCKS);

		if (s->cursor % SWAPZ_SEGMENT_BLOCKS)
			s->waste_blocks += tail;
		s->cursor += tail;
		start = s->cursor;
		if (!g->packed)
			start = (start + blocks - 1U) & ~(uint32_t)(blocks - 1U);
	} else if (start > s->cursor) {
		s->waste_blocks += start - s->cursor;
	}
	s->cursor = start + blocks;
	s->physical_blocks += blocks;

	if (!s->run_valid ||
	    start / SWAPZ_SEGMENT_BLOCKS != s->run_start / SWAPZ_SEGMENT_BLOCKS ||
	    start != s->run_start + s->run_blocks ||
	    s->run_blocks + blocks > 64U) {
		s->write_runs++;
		s->run_start = start;
		s->run_blocks = blocks;
		s->run_valid = 1;
	} else {
		s->run_blocks += blocks;
	}
	return start;
}

static void map_extent(struct study *s, const struct record *records,
		       uint8_t start_record, uint8_t take, uint8_t blocks)
{
	uint32_t payload_start = (uint32_t)blocks * SWAPZ_BLOCK_BYTES;
	uint32_t extent_id = ++s->next_extent_id;
	uint8_t j;

	for (j = 0; j < take; ++j) {
		const struct record *r = &records[start_record + j];
		uint32_t offset = payload_start - r->length;
		uint32_t first = offset / SWAPZ_BLOCK_BYTES;
		uint32_t last = (payload_start - 1U) / SWAPZ_BLOCK_BYTES;
		struct logical_map *m = &s->maps[r->logical];

		m->extent_id = extent_id;
		m->payload_length = r->length;
		m->valid = 1;
		m->raw = 0;
		m->cold_blocks = (uint8_t)(last - first + 1U + (first ? 1U : 0U));
		m->payload_first = (uint8_t)first;
		payload_start = offset;
	}
}

static int emit_window(struct study *s, const struct geometry *g,
		       const struct record *window, uint8_t count)
{
	struct record compressed[WINDOW_PAGES];
	struct record raw[WINDOW_PAGES];
	uint8_t classes[WINDOW_PAGES], takes[WINDOW_PAGES];
	uint8_t compressed_count = 0, raw_count = 0, extent_count = 0;
	uint8_t i, pos = 0;

	/* Lower aggregation never crosses an independently committed window. */
	s->run_valid = 0;
	for (i = 0; i < count; ++i) {
		if (window[i].raw)
			raw[raw_count++] = window[i];
		else
			compressed[compressed_count++] = window[i];
	}
	if (compressed_count &&
	    plan_window(g, compressed, compressed_count, classes, takes,
			&extent_count))
		return -1;
	for (i = 0; i < extent_count; ++i) {
		(void)place_extent(s, g, classes[i]);
		map_extent(s, compressed, pos, takes[i], classes[i]);
		pos += takes[i];
	}
	for (i = 0; i < raw_count; ++i) {
		struct logical_map *m;
		uint32_t extent_id;

		(void)place_extent(s, g, 1);
		extent_id = ++s->next_extent_id;
		m = &s->maps[raw[i].logical];
		m->extent_id = extent_id;
		m->payload_length = SWAPZ_BLOCK_BYTES;
		m->valid = 1;
		m->raw = 1;
		m->cold_blocks = 1;
		m->payload_first = 0;
	}
	return 0;
}

static void update_current(struct study *s, const struct record *window, uint8_t count)
{
	uint8_t i;

	for (i = 0; i < count; ++i) {
		s->current_length[window[i].logical] = window[i].length;
		s->current_raw[window[i].logical] = window[i].raw;
		s->current_valid[window[i].logical] = 1;
	}
}

static uint64_t sequential_requests(const struct study *s)
{
	uint32_t logical, previous_extent = 0;
	uint64_t requests = 0;

	for (logical = 0; logical < LOGICAL_PAGES; ++logical) {
		const struct logical_map *m = &s->maps[logical];

		if (!m->valid)
			continue;
		if (m->raw) {
			requests++;
		} else {
			/* One payload-range request; add metadata block zero only when
			 * this extent was not the immediately preceding logical page and
			 * the payload range itself does not already include block zero. */
			requests++;
			if (m->extent_id != previous_extent && m->payload_first)
				requests++;
		}
		previous_extent = m->extent_id;
	}
	return requests;
}

static int run_geometry(const struct geometry *g, struct study *s)
{
	uint32_t window_no;

	memset(s, 0, sizeof(*s));
	for (window_no = 0; window_no < NORMAL_WINDOWS; ++window_no) {
		struct record window[WINDOW_PAGES];
		uint8_t i;

		for (i = 0; i < WINDOW_PAGES; ++i) {
			uint32_t logical = (window_no * 53U + i) % LOGICAL_PAGES;
			uint8_t raw;
			uint16_t length = payload_for(logical, window_no, &raw);

			window[i] = (struct record){
				.logical = logical,
				.length = length,
				.raw = raw,
			};
		}
		if (emit_window(s, g, window, WINDOW_PAGES))
			return -1;
		update_current(s, window, WINDOW_PAGES);

		if ((window_no + 1U) % GC_INTERVAL == 0) {
			struct record survivors[GC_SURVIVORS];
			uint8_t survivor_count = 0;
			uint32_t base = (window_no * 31U) % LOGICAL_PAGES;

			for (i = 0; i < GC_SURVIVORS; ++i) {
				uint32_t logical =
					(base + (uint32_t)i * 61U) % LOGICAL_PAGES;

				if (!s->current_valid[logical])
					continue;
				survivors[survivor_count++] = (struct record){
					.logical = logical,
					.length = s->current_length[logical],
					.raw = s->current_raw[logical],
				};
			}
			if (survivor_count &&
			    emit_window(s, g, survivors, survivor_count))
				return -1;
		}
	}
	s->cold_blocks_sum = 0;
	s->cold_pages = 0;
	for (window_no = 0; window_no < LOGICAL_PAGES; ++window_no) {
		if (!s->maps[window_no].valid)
			return -1;
		s->cold_blocks_sum += s->maps[window_no].cold_blocks;
		s->cold_pages++;
	}
	s->seq_4m_requests = sequential_requests(s);
	return 0;
}

int main(void)
{
	static const struct geometry geometries[] = {
		{ "aligned_1_2_4", 0, { 1, 2, 4, 0, 0 }, 3 },
		{ "packed_1_2_4", 1, { 1, 2, 4, 0, 0 }, 3 },
		{ "packed_1_2_3_4", 1, { 1, 2, 3, 4, 0 }, 4 },
		{ "packed_1_2_4_8", 1, { 1, 2, 4, 8, 0 }, 4 },
		{ "packed_1_2_4_8_16", 1, { 1, 2, 4, 8, 16 }, 5 },
	};
	struct study studies[sizeof(geometries) / sizeof(geometries[0])];
	size_t i;

	for (i = 0; i < sizeof(geometries) / sizeof(geometries[0]); ++i)
		if (run_geometry(&geometries[i], &studies[i]))
			return 1;

	printf("SWAPZ_EXTENT_GEOMETRY_EVIDENCE={\"scope\":"
	       "\"OFFLINE_NATIVE_GEOMETRY_ONLY_NOT_FORMAT_POLICY\","
	       "\"logical_pages\":%u,\"normal_windows\":%u,\"rows\":[",
	       LOGICAL_PAGES, NORMAL_WINDOWS);
	for (i = 0; i < sizeof(geometries) / sizeof(geometries[0]); ++i) {
		const struct study *s = &studies[i];

		if (i)
			putchar(',');
		printf("{\"name\":\"%s\",\"physical_blocks\":%" PRIu64
		       ",\"waste_blocks\":%" PRIu64
		       ",\"write_runs\":%" PRIu64
		       ",\"cold_read_blocks_x1000\":%" PRIu64
		       ",\"seq_4m_requests\":%" PRIu64 "}",
		       geometries[i].name, s->physical_blocks, s->waste_blocks,
		       s->write_runs,
		       s->cold_pages ?
		       s->cold_blocks_sum * UINT64_C(1000) / s->cold_pages : 0,
		       s->seq_4m_requests);
	}
	printf("]}\n");
	return 0;
}
