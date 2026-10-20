// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <lz4.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "engine.h"
#include "predictor.h"

#define PREDICTOR_CAP SWAPZ_MAX_COMPRESSED
#define MAX_EVIDENCE_PAGES 1024U
#define STRUCTURED_KINDS 9U
#define STRUCTURED_PAGES_PER_KIND 32U
#define TRANSFORM_COUNT 5U
#define THRESHOLD_COUNT 4U

typedef swapz_u32 (*predict_fn)(const swapz_u8 *, swapz_u8 *);
typedef void (*unpredict_fn)(const swapz_u8 *, swapz_u8 *);

struct transform {
	const char *name;
	predict_fn predict;
	unpredict_fn unpredict;
};

struct page_evidence {
	int baseline_length;
	int candidate_length[TRANSFORM_COUNT];
	swapz_u32 cl_score;
	int structured;
};

struct transform_summary {
	uint64_t transform_ns;
	uint64_t inverse_ns;
	uint64_t second_lz4_ns;
	uint64_t saved_payload_bytes;
	uint64_t pages;
	swapz_u32 adopted;
	swapz_u32 raw_rescued;
	swapz_u32 cliff_2024;
	swapz_u32 baseline_blocks;
	swapz_u32 candidate_blocks;
	swapz_u32 baseline_extents;
	swapz_u32 candidate_extents;
};

struct threshold_summary {
	swapz_u32 threshold;
	swapz_u32 negative_eligible;
	swapz_u32 negative_calls;
	swapz_u32 negative_useful;
	swapz_u32 structured_eligible;
	swapz_u32 structured_calls;
	swapz_u32 structured_useful;
};

static struct page_evidence evidence[MAX_EVIDENCE_PAGES];
static swapz_u8 transform_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 recovered_page[SWAPZ_BLOCK_BYTES];
static char compressed_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 planner_dummy[SWAPZ_BLOCK_BYTES];

static const struct transform transforms[TRANSFORM_COUNT] = {
	{ "cl_delta32x2", swapz_predict_cl_delta32x2,
	  swapz_unpredict_cl_delta32x2 },
	{ "cl_bytedelta8", swapz_predict_cl_bytedelta8,
	  swapz_unpredict_cl_bytedelta8 },
	{ "delta32", swapz_predict_delta32, swapz_unpredict_delta32 },
	{ "delta64", swapz_predict_delta64, swapz_unpredict_delta64 },
	{ "xor64", swapz_predict_xor64, swapz_unpredict_xor64 },
};

static const swapz_u32 thresholds[THRESHOLD_COUNT] = { 64U, 96U, 128U, 192U };

static uint64_t now_ns(void)
{
	struct timespec now;

	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return 0;
	return (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
}

static uint32_t next_u32(uint32_t *state)
{
	uint32_t value = *state;

	value ^= value << 13;
	value ^= value >> 17;
	value ^= value << 5;
	*state = value ? value : 0x9e3779b9U;
	return *state;
}

static int compress_page_lz4(const swapz_u8 *page)
{
	return LZ4_compress_fast((const char *)page, compressed_page,
				 SWAPZ_BLOCK_BYTES, PREDICTOR_CAP, 1);
}

static int chosen_length(int baseline, int candidate)
{
	if (candidate > 0 && (!baseline || candidate < baseline))
		return candidate;
	return baseline;
}

static void put_u32(swapz_u8 *bytes, swapz_u32 value)
{
	memcpy(bytes, &value, sizeof(value));
}

static void put_u64(swapz_u8 *bytes, uint64_t value)
{
	memcpy(bytes, &value, sizeof(value));
}

static void generate_structured_page(unsigned int kind, unsigned int page_index,
				     swapz_u8 *page)
{
	uint32_t state = 0x6a09e667U ^ (kind * 0x9e3779b9U) ^
		(page_index * 0x85ebca6bU);
	unsigned int index;

	memset(page, 0, SWAPZ_BLOCK_BYTES);
	switch (kind) {
	case 0: {
		swapz_u32 lane0 = 0x10000000U ^ next_u32(&state);
		swapz_u32 lane1 = 0x70000000U ^ next_u32(&state);

		for (index = 0; index < SWAPZ_BLOCK_BYTES / 8U; ++index) {
			lane0 += 1U + (next_u32(&state) & 0x7fU);
			lane1 += 1U + (next_u32(&state) & 0x3fU);
			put_u32(page + index * 8U, lane0);
			put_u32(page + index * 8U + 4U, lane1);
		}
		break;
	}
	case 1: {
		uint64_t pointer = 0xffff888000000000ULL +
			((uint64_t)page_index << 20);

		for (index = 0; index < SWAPZ_BLOCK_BYTES / 8U; ++index) {
			pointer += 16U + (next_u32(&state) & 0x1f0U);
			put_u64(page + index * 8U, pointer);
		}
		break;
	}
	case 2: {
		uint64_t physical = 0x0000001000000000ULL +
			((uint64_t)page_index << 21);

		for (index = 0; index < SWAPZ_BLOCK_BYTES / 8U; ++index) {
			uint64_t flags = 0x003ULL | ((uint64_t)(index & 7U) << 5);

			physical += 4096ULL * (1ULL + (next_u32(&state) & 3U));
			put_u64(page + index * 8U, physical | flags);
		}
		break;
	}
	case 3: {
		swapz_u32 value = 0x40000000U ^ next_u32(&state);

		for (index = 0; index < SWAPZ_BLOCK_BYTES / 4U; ++index) {
			value += 1U + (next_u32(&state) & 0xffU);
			put_u32(page + index * 4U, value);
		}
		break;
	}
	case 4: {
		uint64_t stamp = 1700000000000000000ULL +
			(uint64_t)page_index * 1000000ULL;

		for (index = 0; index < SWAPZ_BLOCK_BYTES / 8U; ++index) {
			stamp += 1000ULL + (next_u32(&state) & 0x3ffU);
			put_u64(page + index * 8U, stamp);
		}
		break;
	}
	case 5:
		for (index = 0; index < SWAPZ_BLOCK_BYTES / sizeof(double); ++index) {
			double value = 1000.0 + (double)page_index * 0.25 +
				(double)index * 0.0009765625 +
				(double)(next_u32(&state) & 7U) * 0.0000001;

			memcpy(page + index * sizeof(value), &value, sizeof(value));
		}
		break;
	case 6:
		for (index = 0; index < SWAPZ_BLOCK_BYTES / 8U; ++index) {
			swapz_u32 id = page_index * 100000U + index * 3U +
				(next_u32(&state) & 3U);
			swapz_u32 counter = 0x50000000U + index * 5U +
				(next_u32(&state) & 7U);

			put_u32(page + index * 8U, id);
			put_u32(page + index * 8U + 4U, counter);
		}
		break;
	case 7:
		for (index = 0; index < SWAPZ_BLOCK_BYTES;
		     index += SWAPZ_PREDICTOR_CACHELINE_BYTES) {
			unsigned int word;
			uint64_t base = 0xffff900000000000ULL +
				((uint64_t)page_index << 18) + index * 64ULL;

			for (word = 0; word < 8U; ++word) {
				uint64_t value;

				if (word < 6U)
					value = base + word * 64U +
						(next_u32(&state) & 0x1fU);
				else
					value = ((uint64_t)next_u32(&state) << 32) |
						next_u32(&state);
				put_u64(page + index + word * 8U, value);
			}
		}
		break;
	case 8:
		for (index = 0; index < SWAPZ_BLOCK_BYTES / sizeof(float); ++index) {
			float value = 64.0f + (float)page_index * 0.125f +
				(float)index * 0.001953125f +
				(float)(next_u32(&state) & 7U) * 0.00001f;

			memcpy(page + index * sizeof(value), &value, sizeof(value));
		}
		break;
	default:
		abort();
	}
}

static int evaluate_page(const swapz_u8 *page, int structured,
			 struct page_evidence *out,
			 struct transform_summary *summary)
{
	unsigned int transform_index;
	uint64_t start;
	int baseline;

	baseline = compress_page_lz4(page);
	if (baseline < 0 || baseline > PREDICTOR_CAP)
		return -EINVAL;
	memset(out, 0, sizeof(*out));
	out->baseline_length = baseline;
	out->structured = structured;
	for (transform_index = 0; transform_index < TRANSFORM_COUNT;
	     ++transform_index) {
		const struct transform *transform = &transforms[transform_index];
		swapz_u32 score;
		int candidate;

		start = now_ns();
		score = transform->predict(page, transform_page);
		summary[transform_index].transform_ns += now_ns() - start;

		start = now_ns();
		transform->unpredict(transform_page, recovered_page);
		summary[transform_index].inverse_ns += now_ns() - start;
		if (memcmp(page, recovered_page, SWAPZ_BLOCK_BYTES))
			return -EUCLEAN;

		start = now_ns();
		candidate = compress_page_lz4(transform_page);
		summary[transform_index].second_lz4_ns += now_ns() - start;
		if (candidate < 0 || candidate > PREDICTOR_CAP)
			return -EINVAL;
		out->candidate_length[transform_index] = candidate;
		if (!transform_index)
			out->cl_score = score;
	}
	return 0;
}

static int append_negative_file(const char *path, swapz_u32 *count,
				struct transform_summary *summary)
{
	FILE *file = fopen(path, "rb");
	swapz_u8 page[SWAPZ_BLOCK_BYTES];

	if (!file)
		return -errno;
	while (fread(page, 1, sizeof(page), file) == sizeof(page)) {
		int error;

		if (*count >= MAX_EVIDENCE_PAGES) {
			fclose(file);
			return -E2BIG;
		}
		error = evaluate_page(page, 0, &evidence[*count], summary);
		if (error) {
			fclose(file);
			return error;
		}
		(*count)++;
	}
	if (ferror(file)) {
		int error = errno ? -errno : -EIO;

		fclose(file);
		return error;
	}
	if (!feof(file)) {
		fclose(file);
		return -EINVAL;
	}
	fclose(file);
	return 0;
}

static int planner_totals(const struct page_evidence *rows, swapz_u32 count,
			  unsigned int transform_index, int candidate_mode,
			  swapz_u32 *blocks_out, swapz_u32 *extents_out)
{
	swapz_u32 offset = 0;
	swapz_u32 blocks_total = 0, extents_total = 0;

	while (offset < count) {
		struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
		swapz_u8 classes[SWAPZ_MAX_RECORDS];
		swapz_u8 takes[SWAPZ_MAX_RECORDS];
		swapz_u8 extent_count = 0;
		swapz_u8 compressed_count = 0;
		swapz_u32 raw_count = 0;
		swapz_u32 window = count - offset;
		swapz_u32 index;
		int error;

		if (window > SWAPZ_MAX_RECORDS)
			window = SWAPZ_MAX_RECORDS;
		memset(pages, 0, sizeof(pages));
		for (index = 0; index < window; ++index) {
			const struct page_evidence *row = &rows[offset + index];
			int length = row->baseline_length;

			if (candidate_mode)
				length = chosen_length(length,
					row->candidate_length[transform_index]);
			if (!length) {
				raw_count++;
				continue;
			}
			pages[compressed_count].logical_page = compressed_count;
			pages[compressed_count].payload = planner_dummy;
			pages[compressed_count].length = (swapz_u16)length;
			pages[compressed_count].raw = 0;
			compressed_count++;
		}
		blocks_total += raw_count;
		extents_total += raw_count;
		if (compressed_count) {
			error = swapz_engine_plan_bounded(
				pages, compressed_count, 0, classes, takes,
				&extent_count);
			if (error)
				return error;
			for (index = 0; index < extent_count; ++index)
				blocks_total += classes[index];
			extents_total += extent_count;
		}
		offset += window;
	}
	*blocks_out = blocks_total;
	*extents_out = extents_total;
	return 0;
}

static void summarize_transform(const struct page_evidence *rows,
				swapz_u32 count, unsigned int transform_index,
				struct transform_summary *summary)
{
	swapz_u32 index;

	for (index = 0; index < count; ++index) {
		int baseline = rows[index].baseline_length;
		int candidate = rows[index].candidate_length[transform_index];
		int chosen = chosen_length(baseline, candidate);
		unsigned int baseline_bytes = baseline ? (unsigned int)baseline :
			SWAPZ_BLOCK_BYTES;
		unsigned int chosen_bytes = chosen ? (unsigned int)chosen :
			SWAPZ_BLOCK_BYTES;

		summary->pages++;
		if (chosen != baseline) {
			summary->adopted++;
			summary->saved_payload_bytes += baseline_bytes - chosen_bytes;
		}
		if (!baseline && candidate > 0)
			summary->raw_rescued++;
		if ((!baseline || baseline > 2024) &&
		    candidate > 0 && candidate <= 2024)
			summary->cliff_2024++;
	}
}

static void summarize_thresholds(const struct page_evidence *rows,
				 swapz_u32 negative_count,
				 swapz_u32 structured_start,
				 swapz_u32 total_count,
				 struct threshold_summary *out)
{
	unsigned int threshold_index;

	for (threshold_index = 0; threshold_index < THRESHOLD_COUNT;
	     ++threshold_index) {
		swapz_u32 index;
		struct threshold_summary *summary = &out[threshold_index];

		summary->threshold = thresholds[threshold_index];
		for (index = 0; index < total_count; ++index) {
			const struct page_evidence *row = &rows[index];
			int baseline = row->baseline_length;
			int candidate = row->candidate_length[0];
			int eligible = !baseline || baseline > 2024;
			int call = eligible && row->cl_score >= summary->threshold;
			int useful = call && candidate > 0 &&
				(!baseline || candidate < baseline);
			int structured = index >= structured_start;

			if (!eligible)
				continue;
			if (structured) {
				summary->structured_eligible++;
				summary->structured_calls += call;
				summary->structured_useful += useful;
			} else if (index < negative_count) {
				summary->negative_eligible++;
				summary->negative_calls += call;
				summary->negative_useful += useful;
			}
		}
	}
}

int main(int argc, char **argv)
{
	struct transform_summary total_summary[TRANSFORM_COUNT] = { 0 };
	struct transform_summary structured_summary[TRANSFORM_COUNT] = { 0 };
	struct threshold_summary threshold_summary[THRESHOLD_COUNT] = { 0 };
	swapz_u32 count = 0, negative_count, structured_start;
	swapz_u8 page[SWAPZ_BLOCK_BYTES];
	unsigned int kind, page_index, transform_index, threshold_index;
	int argument;

	if (argc < 2) {
		fprintf(stderr, "predictor qualification requires negative-control fixtures\n");
		return 2;
	}
	for (argument = 1; argument < argc; ++argument) {
		int error = append_negative_file(argv[argument], &count, total_summary);

		if (error) {
			fprintf(stderr, "negative fixture failed: %s (%d)\n",
				argv[argument], error);
			return 1;
		}
	}
	negative_count = count;
	structured_start = count;
	for (kind = 0; kind < STRUCTURED_KINDS; ++kind)
		for (page_index = 0; page_index < STRUCTURED_PAGES_PER_KIND;
		     ++page_index) {
			int error;

			if (count >= MAX_EVIDENCE_PAGES)
				return 1;
			generate_structured_page(kind, page_index, page);
			error = evaluate_page(page, 1, &evidence[count], total_summary);
			if (error) {
				fprintf(stderr,
					"structured predictor roundtrip failed kind=%u page=%u error=%d\n",
					kind, page_index, error);
				return 1;
			}
			count++;
		}

	for (transform_index = 0; transform_index < TRANSFORM_COUNT;
	     ++transform_index) {
		int error;

		structured_summary[transform_index].transform_ns =
			total_summary[transform_index].transform_ns;
		structured_summary[transform_index].inverse_ns =
			total_summary[transform_index].inverse_ns;
		structured_summary[transform_index].second_lz4_ns =
			total_summary[transform_index].second_lz4_ns;
		summarize_transform(evidence + structured_start,
			count - structured_start, transform_index,
			&structured_summary[transform_index]);
		error = planner_totals(evidence + structured_start,
			count - structured_start, transform_index, 0,
			&structured_summary[transform_index].baseline_blocks,
			&structured_summary[transform_index].baseline_extents);
		if (!error)
			error = planner_totals(evidence + structured_start,
				count - structured_start, transform_index, 1,
				&structured_summary[transform_index].candidate_blocks,
				&structured_summary[transform_index].candidate_extents);
		if (error) {
			fprintf(stderr, "production planner rejected evidence: %d\n", error);
			return 1;
		}
	}
	summarize_thresholds(evidence, negative_count, structured_start, count,
			     threshold_summary);

	if (!negative_count || structured_start == count ||
	    !structured_summary[0].adopted ||
	    structured_summary[0].candidate_blocks >=
		structured_summary[0].baseline_blocks) {
		fprintf(stderr, "predictor positive/negative controls did not exercise mechanism\n");
		return 1;
	}

	printf("SWAPZ_PREDICTOR_EVIDENCE={\"scope\":"
	       "\"OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY\","
	       "\"negative_pages\":%u,\"structured_pages\":%u,"
	       "\"residual_lanes\":%u,\"thresholds\":[",
	       negative_count, count - structured_start,
	       SWAPZ_PREDICTOR_CL_DELTA32X2_RESIDUALS);
	for (threshold_index = 0; threshold_index < THRESHOLD_COUNT;
	     ++threshold_index) {
		const struct threshold_summary *item =
			&threshold_summary[threshold_index];

		printf("%s{\"threshold\":%u,\"negative_eligible\":%u,"
		       "\"negative_calls\":%u,\"negative_useful\":%u,"
		       "\"structured_eligible\":%u,\"structured_calls\":%u,"
		       "\"structured_useful\":%u}",
		       threshold_index ? "," : "", item->threshold,
		       item->negative_eligible, item->negative_calls,
		       item->negative_useful, item->structured_eligible,
		       item->structured_calls, item->structured_useful);
	}
	printf("],\"transforms\":[");
	for (transform_index = 0; transform_index < TRANSFORM_COUNT;
	     ++transform_index) {
		const struct transform_summary *item =
			&structured_summary[transform_index];
		uint64_t pages = count ? count : 1;
		long block_saved =
			(long)item->baseline_blocks - (long)item->candidate_blocks;
		long extent_saved =
			(long)item->baseline_extents - (long)item->candidate_extents;

		printf("%s{\"name\":\"%s\",\"adopted\":%u,"
		       "\"raw_rescued\":%u,\"cliff_2024\":%u,"
		       "\"saved_payload_bytes\":%" PRIu64 ","
		       "\"baseline_blocks\":%u,\"candidate_blocks\":%u,"
		       "\"planner_blocks_saved\":%ld,"
		       "\"baseline_extents\":%u,\"candidate_extents\":%u,"
		       "\"planner_extents_saved\":%ld,"
		       "\"transform_ns_per_page\":%" PRIu64 ","
		       "\"inverse_ns_per_page\":%" PRIu64 ","
		       "\"second_lz4_ns_per_page\":%" PRIu64 "}",
		       transform_index ? "," : "", transforms[transform_index].name,
		       item->adopted, item->raw_rescued, item->cliff_2024,
		       item->saved_payload_bytes, item->baseline_blocks,
		       item->candidate_blocks, block_saved,
		       item->baseline_extents, item->candidate_extents, extent_saved,
		       total_summary[transform_index].transform_ns / pages,
		       total_summary[transform_index].inverse_ns / pages,
		       total_summary[transform_index].second_lz4_ns / pages);
	}
	printf("]}\n");
	printf("PASS: predictor transforms round-trip; structured corpus saves planner blocks; "
	       "negative controls measured\n");
	return 0;
}
