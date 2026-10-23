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
#include "predictor-internal.h"
#include "predictor-route.h"

#define PREDICTOR_CAP ((int)SWAPZ_MAX_COMPRESSED)
#define MAX_EVIDENCE_PAGES 1024U
#define STRUCTURED_KINDS 10U
#define STRUCTURED_PAGES_PER_KIND 32U
#define GENERATED_NEGATIVE_PAGES 32U
#define NEGATIVE_PROFILE_COUNT 5U
#define TRANSFORM_COUNT 1U
#define TRANSFORM_DELTA64 0U
#define THRESHOLD_COUNT 5U
#define CLASSIFIER_BENCH_REPEATS 256U
#define TRANSFORM_BENCH_REPEATS 64U
#define SSE2_FORWARD_AB_REPEATS 64U
#define SSE2_FORWARD_AB_PAIRS 5U
#define LZ4_BENCH_REPEATS 32U
#define LZ4_ACCEL_BENCH_REPEATS 16U
#define LZ4_ACCELERATION_COUNT 4U
#define MAX_BACKEND_BENCHMARKS 4U
#define SD_EMULATED_BLOCK_NS 390625ULL
#define SSD_EMULATED_BLOCK_NS 48828ULL

typedef swapz_u32 (*predict_fn)(const swapz_u8 *, swapz_u8 *);
typedef void (*unpredict_fn)(const swapz_u8 *, swapz_u8 *);

struct transform {
	const char *name;
	predict_fn predict;
	unpredict_fn unpredict;
};
struct backend_benchmark {
	const char *name;
	predict_fn predict;
	unpredict_fn unpredict;
	uint64_t transform_ns_per_page;
	uint64_t inverse_ns_per_page;
};
struct sse2_forward_ab_pair {
	uint64_t baseline_ns_per_page;
	uint64_t unrolled_ns_per_page;
};

struct page_evidence {
	int baseline_length;
	int candidate_length[TRANSFORM_COUNT];
	struct swapz_delta64_route route;
	swapz_u32 classifier_score;
	swapz_u8 negative_profile;
	swapz_u8 classifier_ran;
	int structured;
};

struct transform_summary {
	uint64_t transform_ns;
	uint64_t inverse_ns;
	uint64_t scalar_transform_ns;
	uint64_t scalar_inverse_ns;
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

struct profile_threshold_summary {
	swapz_u32 pages;
	swapz_u32 eligible;
	swapz_u32 calls;
	swapz_u32 useful;
};

struct threshold_summary {
	swapz_u32 threshold;
	swapz_u32 negative_eligible;
	swapz_u32 negative_calls;
	swapz_u32 negative_useful;
	swapz_u32 structured_eligible;
	swapz_u32 structured_calls;
	swapz_u32 structured_useful;
	swapz_u32 routed_baseline_blocks;
	swapz_u32 routed_candidate_blocks;
	swapz_u32 routed_baseline_extents;
	swapz_u32 routed_candidate_extents;
	uint64_t routed_cpu_ns_total;
	uint64_t routed_cpu_ns_per_page;
	uint64_t ns_per_saved_block;
	struct profile_threshold_summary profiles[NEGATIVE_PROFILE_COUNT];
};

struct classifier_summary {
	uint64_t wall_ns;
	uint64_t scalar_wall_ns;
	uint64_t benchmark_calls;
	swapz_u32 pages;
	swapz_u32 early_abort_pages;
};

struct lz4_acceleration_summary {
	unsigned int acceleration;
	uint64_t wall_ns_per_page;
	uint64_t accepted_payload_bytes;
	swapz_u32 raw_pages;
	swapz_u32 planner_blocks;
	swapz_u32 planner_extents;
};

struct production_route_summary {
	swapz_u32 eligible_pages;
	swapz_u32 packing_eligible_pages;
	swapz_u32 classifier_passes;
	swapz_u32 candidate_attempts;
	swapz_u32 adopted_pages;
	swapz_u32 raw_rescues;
	swapz_u32 lz4_rescues;
	swapz_u32 packing_adoptions;
	uint64_t payload_bytes_saved;
	swapz_u32 baseline_blocks;
	swapz_u32 candidate_blocks;
	swapz_u32 baseline_extents;
	swapz_u32 candidate_extents;
	uint64_t modeled_wall_ns_total;
	uint64_t modeled_wall_ns_per_page;
	uint64_t ns_per_saved_block;
};

struct sampling_control {
	const char *name;
	swapz_u32 score;
	swapz_u32 minimum_score;
};

static struct page_evidence evidence[MAX_EVIDENCE_PAGES];
static swapz_u8 evidence_pages[MAX_EVIDENCE_PAGES][SWAPZ_BLOCK_BYTES];
static swapz_u8 delta64_pages[MAX_EVIDENCE_PAGES][SWAPZ_BLOCK_BYTES];
static volatile uint64_t classifier_benchmark_sink;
static volatile uint64_t transform_benchmark_sink;
static swapz_u8 transform_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 scalar_transform_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 recovered_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 scalar_recovered_page[SWAPZ_BLOCK_BYTES];
static int lz4_acceleration_lengths[MAX_EVIDENCE_PAGES];
static char compressed_page[SWAPZ_BLOCK_BYTES];
static swapz_u8 planner_dummy[SWAPZ_BLOCK_BYTES];

static const struct transform transforms[TRANSFORM_COUNT] = {
	{ "delta64", swapz_predict_delta64, swapz_unpredict_delta64 },
};

static const char *negative_profile_names[NEGATIVE_PROFILE_COUNT] = {
	"zero", "repeat", "entropy", "mixed", "medium"
};
static const swapz_u32 thresholds[THRESHOLD_COUNT] = {
	4U, 8U, 16U, 24U, 32U
};

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
	case 9: {
		unsigned int base;

		for (base = 0; base < SWAPZ_BLOCK_BYTES;
		     base += SWAPZ_PREDICTOR_SUBPAGE_BYTES) {
			uint64_t value = ((uint64_t)next_u32(&state) << 32) |
				next_u32(&state);
			unsigned int word;

			for (word = 0;
			     word < SWAPZ_PREDICTOR_SUBPAGE_BYTES / sizeof(value);
			     ++word) {
				value += 8U + (next_u32(&state) & 0x3fU);
				put_u64(page + base + word * sizeof(value), value);
			}
		}
		break;
	}
	default:
		abort();
	}
}

static int evaluate_sampling_controls(struct sampling_control *controls)
{
	swapz_u8 page[SWAPZ_BLOCK_BYTES];
	swapz_u32 subpage, word;
	uint64_t value;

	if (!controls)
		return -EINVAL;

	/* Repeated headers occupy the old fixed sample offset in every 512B area. */
	for (subpage = 0; subpage <
	     SWAPZ_BLOCK_BYTES / SWAPZ_PREDICTOR_SUBPAGE_BYTES; ++subpage) {
		swapz_u32 base = subpage * SWAPZ_PREDICTOR_SUBPAGE_BYTES;
		uint64_t header = 0x1122334455667788ULL;

		put_u64(page + base, header);
		put_u64(page + base + sizeof(header), header);
		value = header;
		for (word = 2; word <
		     SWAPZ_PREDICTOR_SUBPAGE_BYTES / sizeof(value); ++word) {
			value += 8U;
			put_u64(page + base + word * sizeof(value), value);
		}
	}
	controls[0].name = "repeated_512b_headers";
	controls[0].score = swapz_predict_delta64_sample_score(page);
	controls[0].minimum_score = 24U;
	if (controls[0].score < controls[0].minimum_score ||
	    controls[0].score !=
		swapz_predict_delta64_sample_score_scalar(page))
		return -EUCLEAN;

	/* Structured pairs exist only in lane 1 of each 512B region. */
	memset(page, 0, sizeof(page));
	for (subpage = 0; subpage <
	     SWAPZ_BLOCK_BYTES / SWAPZ_PREDICTOR_SUBPAGE_BYTES; ++subpage) {
		swapz_u32 base = subpage * SWAPZ_PREDICTOR_SUBPAGE_BYTES +
			SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES;
		value = 0x100000000ULL + (uint64_t)subpage * 0x10000ULL;
		for (word = 0; word <
		     SWAPZ_PREDICTOR_SAMPLE_STRIDE_BYTES / sizeof(value); ++word) {
			put_u64(page + base + word * sizeof(value), value);
			value += 8U;
		}
	}
	controls[1].name = "lane1_only_signal";
	controls[1].score = swapz_predict_delta64_sample_score(page);
	controls[1].minimum_score = SWAPZ_PREDICTOR_PACK_THRESHOLD;
	if (controls[1].score < controls[1].minimum_score ||
	    controls[1].score !=
		swapz_predict_delta64_sample_score_scalar(page))
		return -EUCLEAN;

	return 0;
}

static int evaluate_route_controls(void)
{
	struct swapz_delta64_route route;
	swapz_u16 baseline;

	if (!swapz_delta64_route_init(-1, &route) || route.pack_path ||
	    route.threshold != SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD ||
	    !swapz_delta64_candidate_adoptable(&route, -1, 1) ||
	    swapz_delta64_candidate_adoptable(&route, 100, 100) ||
	    !swapz_delta64_route_init(SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH + 1,
				      &route) || route.pack_path ||
	    route.threshold != SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD ||
	    swapz_delta64_route_init(SWAPZ_BLOCK_BYTES + 1, &route))
		return -EUCLEAN;

	for (baseline = 1; baseline <= SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH;
	     ++baseline) {
		int eligible = swapz_delta64_route_init(baseline, &route);

		if (eligible != !!route.pack_limit ||
		    (eligible && (!route.pack_path ||
				  route.threshold != SWAPZ_PREDICTOR_PACK_THRESHOLD ||
				  route.pack_limit >= baseline ||
				  !swapz_delta64_candidate_adoptable(
					  &route, baseline, route.pack_limit) ||
				  swapz_delta64_candidate_adoptable(
					  &route, baseline,
					  route.pack_limit + 1U))))
			return -EUCLEAN;
	}
	return 0;
}

static int evaluate_page(const swapz_u8 *page, int structured,
			 swapz_u8 negative_profile, struct page_evidence *out,
			 struct transform_summary *summary,
			 struct classifier_summary *classifier)
{
	unsigned int transform_index;
	int baseline;
	int route_eligible;
	(void)summary;
	baseline = compress_page_lz4(page);
	if (baseline < 0 || baseline > PREDICTOR_CAP) return -EINVAL;
	memset(out, 0, sizeof(*out));
	out->baseline_length = baseline; out->structured = structured;
	out->negative_profile = negative_profile;
	route_eligible = swapz_delta64_route_init(baseline, &out->route);
	if (route_eligible) {
		swapz_u32 scalar_score = swapz_predict_delta64_sample_score_scalar(page);
		out->classifier_score = swapz_predict_delta64_sample_score(page);
		if (out->classifier_score != scalar_score) return -EUCLEAN;
		classifier->pages++; classifier->early_abort_pages += out->classifier_score == 0;
		out->classifier_ran = 1;
	}
	for (transform_index = 0; transform_index < TRANSFORM_COUNT; ++transform_index) {
		const struct transform *transform = &transforms[transform_index];
		int candidate;
		if (transform->predict(page, transform_page) ||
		    swapz_predict_delta64_scalar(page, scalar_transform_page)) return -EUCLEAN;
		if (memcmp(transform_page, scalar_transform_page, SWAPZ_BLOCK_BYTES)) return -EUCLEAN;
		transform->unpredict(transform_page, recovered_page);
		if (memcmp(page, recovered_page, SWAPZ_BLOCK_BYTES)) return -EUCLEAN;
		swapz_unpredict_delta64_scalar(scalar_transform_page, scalar_recovered_page);
		if (memcmp(page, scalar_recovered_page, SWAPZ_BLOCK_BYTES)) return -EUCLEAN;
		candidate = compress_page_lz4(transform_page);
		if (candidate < 0 || candidate > PREDICTOR_CAP) return -EINVAL;
		out->candidate_length[transform_index] = candidate;
	}
	return 0;
}

static int append_generated_negative(swapz_u8 profile,
				     swapz_u32 *count,
				     struct transform_summary *summary,
				     struct classifier_summary *classifier)
{
	swapz_u8 page[SWAPZ_BLOCK_BYTES];
	unsigned int page_index;

	for (page_index = 0; page_index < GENERATED_NEGATIVE_PAGES;
	     ++page_index) {
		unsigned int offset;
		uint64_t word = 0x0102030405060708ULL +
			(uint64_t)page_index * 0x101010101010101ULL;
		int error;

		if (*count >= MAX_EVIDENCE_PAGES)
			return -E2BIG;
		if (profile == 0) {
			memset(page, 0, sizeof(page));
		} else if (profile == 1) {
			for (offset = 0; offset < sizeof(page); offset += sizeof(word))
				put_u64(page + offset, word);
		} else {
			return -EINVAL;
		}
		memcpy(evidence_pages[*count], page, sizeof(page));
		error = evaluate_page(page, 0, profile, &evidence[*count],
				      summary, classifier);
		if (error)
			return error;
		(*count)++;
	}
	return 0;
}

static int append_negative_file(const char *path, swapz_u8 profile,
				swapz_u32 *count,
				struct transform_summary *summary,
				struct classifier_summary *classifier)
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
		memcpy(evidence_pages[*count], page, sizeof(page));
		error = evaluate_page(page, 0, profile, &evidence[*count],
				      summary, classifier);
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
			  swapz_u32 route_threshold,
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

			if (candidate_mode == 1)
				length = chosen_length(length,
					row->candidate_length[transform_index]);
			else if (candidate_mode == 2 && row->classifier_ran) {
				struct swapz_delta64_route route = row->route;
				int candidate =
					row->candidate_length[transform_index];

				if (route_threshold)
					route.threshold = (swapz_u8)route_threshold;
				if (row->classifier_score >= route.threshold &&
				    swapz_delta64_candidate_adoptable(
					    &route, row->baseline_length, candidate))
					length = candidate;
			}
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

static int planner_length_totals(const int *lengths, swapz_u32 count,
				 swapz_u32 *blocks_out,
				 swapz_u32 *extents_out)
{
	swapz_u32 offset = 0, blocks_total = 0, extents_total = 0;

	while (offset < count) {
		struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
		swapz_u8 classes[SWAPZ_MAX_RECORDS], takes[SWAPZ_MAX_RECORDS];
		swapz_u8 extent_count = 0, compressed_count = 0;
		swapz_u32 raw_count = 0;
		swapz_u32 window = count - offset;
		swapz_u32 index;
		int error;

		if (window > SWAPZ_MAX_RECORDS)
			window = SWAPZ_MAX_RECORDS;
		memset(pages, 0, sizeof(pages));
		for (index = 0; index < window; ++index) {
			int length = lengths[offset + index];

			if (length <= 0) {
				raw_count++;
				continue;
			}
			pages[compressed_count].logical_page = compressed_count;
			pages[compressed_count].payload = planner_dummy;
			pages[compressed_count].length = (swapz_u16)length;
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

static int collect_lz4_acceleration_sweep(
			const struct page_evidence *rows, swapz_u32 count,
			struct lz4_acceleration_summary *summaries)
{
	static const unsigned int accelerations[LZ4_ACCELERATION_COUNT] = {
		1U, 2U, 3U, 4U
	};
	unsigned int acceleration_index;

	for (acceleration_index = 0;
	     acceleration_index < LZ4_ACCELERATION_COUNT;
	     ++acceleration_index) {
		struct lz4_acceleration_summary *summary =
			&summaries[acceleration_index];
		uint64_t start, end, calls;
		unsigned int repeat;
		swapz_u32 index;
		int error;

		summary->acceleration = accelerations[acceleration_index];
		start = now_ns();
		for (repeat = 0; repeat < LZ4_ACCEL_BENCH_REPEATS; ++repeat)
			for (index = 0; index < count; ++index) {
				int length = LZ4_compress_fast(
					(const char *)evidence_pages[index],
					compressed_page, SWAPZ_BLOCK_BYTES,
					PREDICTOR_CAP, summary->acceleration);

				if (length < 0 || length > PREDICTOR_CAP)
					return -EUCLEAN;
				transform_benchmark_sink += (uint64_t)length;
				if (repeat)
					continue;
				lz4_acceleration_lengths[index] = length;
				if (summary->acceleration == 1U &&
				    length != rows[index].baseline_length)
					return -EUCLEAN;
				if (length > 0) {
					int decoded = LZ4_decompress_safe(
						compressed_page,
						(char *)recovered_page,
						length, SWAPZ_BLOCK_BYTES);

					if (decoded != SWAPZ_BLOCK_BYTES ||
					    memcmp(recovered_page,
						   evidence_pages[index],
						   SWAPZ_BLOCK_BYTES))
						return -EBADMSG;
					summary->accepted_payload_bytes +=
						(uint64_t)length;
				} else {
					summary->raw_pages++;
				}
			}
		end = now_ns();
		calls = (uint64_t)count * LZ4_ACCEL_BENCH_REPEATS;
		if (!start || !end || !calls || end < start)
			return -EUCLEAN;
		summary->wall_ns_per_page = (end - start) / calls;
		error = planner_length_totals(
			lz4_acceleration_lengths, count,
			&summary->planner_blocks, &summary->planner_extents);
		if (error)
			return error;
	}
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
		if (rows[index].route.threshold &&
		    candidate > 0 && candidate <= 2024)
			summary->cliff_2024++;
	}
}

static int benchmark_classifier(const struct page_evidence *rows, swapz_u32 count,
				struct classifier_summary *summary)
{
	uint64_t calls = 0, sink = 0, start, end; unsigned int repeat; swapz_u32 index;
	if (!rows || !summary || !summary->pages) return -EINVAL;
	start = now_ns();
	for (repeat = 0; repeat < CLASSIFIER_BENCH_REPEATS; ++repeat)
		for (index = 0; index < count; ++index)
			if (rows[index].classifier_ran) {
				sink += swapz_predict_delta64_sample_score(evidence_pages[index]); calls++;
			}
	end = now_ns(); classifier_benchmark_sink = sink;
	if (!start || !end || calls != (uint64_t)summary->pages * CLASSIFIER_BENCH_REPEATS)
		return -EUCLEAN;
	summary->wall_ns = end - start; summary->scalar_wall_ns = summary->wall_ns;
	summary->benchmark_calls = calls; return 0;
}
static int build_delta64_pages(swapz_u32 count)
{
	swapz_u32 index;
	for (index = 0; index < count; ++index)
		if (swapz_predict_delta64_scalar(evidence_pages[index], delta64_pages[index]))
			return -EUCLEAN;
	return 0;
}
static int benchmark_backend(struct backend_benchmark *backend, swapz_u32 count)
{
	uint64_t start, end, sink = 0, calls = (uint64_t)count * TRANSFORM_BENCH_REPEATS;
	unsigned int repeat; swapz_u32 index;
	if (!backend || !backend->predict || !backend->unpredict || !count) return -EINVAL;
	for (index = 0; index < count; ++index) {
		if (backend->predict(evidence_pages[index], transform_page)) return -EUCLEAN;
		if (memcmp(transform_page, delta64_pages[index], SWAPZ_BLOCK_BYTES)) return -EUCLEAN;
		backend->unpredict(delta64_pages[index], recovered_page);
		if (memcmp(recovered_page, evidence_pages[index], SWAPZ_BLOCK_BYTES)) return -EUCLEAN;
	}
	start = now_ns();
	for (repeat = 0; repeat < TRANSFORM_BENCH_REPEATS; ++repeat)
		for (index = 0; index < count; ++index) {
			backend->predict(evidence_pages[index], transform_page);
			sink += transform_page[(index + repeat) & (SWAPZ_BLOCK_BYTES - 1U)];
		}
	end = now_ns(); if (!start || !end || !calls) return -EUCLEAN;
	backend->transform_ns_per_page = (end - start) / calls;
	start = now_ns();
	for (repeat = 0; repeat < TRANSFORM_BENCH_REPEATS; ++repeat)
		for (index = 0; index < count; ++index) {
			backend->unpredict(delta64_pages[index], recovered_page);
			sink += recovered_page[(index + repeat) & (SWAPZ_BLOCK_BYTES - 1U)];
		}
	end = now_ns(); transform_benchmark_sink += sink;
	if (!start || !end) return -EUCLEAN;
	backend->inverse_ns_per_page = (end - start) / calls; return 0;
}
static int collect_backend_benchmarks(struct backend_benchmark *backends,
				      unsigned int *count_out, swapz_u32 page_count)
{
	unsigned int count = 0, index;
	backends[count++] = (struct backend_benchmark){ "scalar", swapz_predict_delta64_scalar, swapz_unpredict_delta64_scalar, 0, 0 };
#if defined(__x86_64__)
	backends[count++] = (struct backend_benchmark){ "sse2", swapz_predict_delta64_sse2, swapz_unpredict_delta64_sse2, 0, 0 };
	__builtin_cpu_init();
	if (__builtin_cpu_supports("avx2"))
		backends[count++] = (struct backend_benchmark){ "avx2", swapz_predict_delta64_avx2, swapz_unpredict_delta64_avx2, 0, 0 };
	if (__builtin_cpu_supports("avx512f"))
		backends[count++] = (struct backend_benchmark){ "avx512", swapz_predict_delta64_avx512, swapz_unpredict_delta64_avx512, 0, 0 };
#elif defined(__aarch64__)
	backends[count++] = (struct backend_benchmark){ "neon", swapz_predict_delta64_neon, swapz_unpredict_delta64_neon, 0, 0 };
#endif
	if (count > MAX_BACKEND_BENCHMARKS) return -E2BIG;
	for (index = 0; index < count; ++index) { int error = benchmark_backend(&backends[index], page_count); if (error) return error; }
	*count_out = count; return 0;
}

#if defined(__x86_64__)
static int benchmark_sse2_forward_arm(predict_fn transform, swapz_u32 count,
				      uint64_t *ns_per_page)
{
	const uint64_t calls = (uint64_t)count * SSE2_FORWARD_AB_REPEATS;
	uint64_t start, end, sink = 0;
	unsigned int repeat;
	swapz_u32 index;

	if (!transform || !count || !ns_per_page)
		return -EINVAL;
	start = now_ns();
	for (repeat = 0; repeat < SSE2_FORWARD_AB_REPEATS; ++repeat)
		for (index = 0; index < count; ++index) {
			if (transform(evidence_pages[index], transform_page))
				return -EUCLEAN;
			sink += transform_page[(index + repeat) &
					      (SWAPZ_BLOCK_BYTES - 1U)];
		}
	end = now_ns();
	transform_benchmark_sink += sink;
	if (!start || end <= start)
		return -EUCLEAN;
	*ns_per_page = (end - start) / calls;
	return *ns_per_page ? 0 : -EUCLEAN;
}
#endif

static int benchmark_sse2_forward_ab(
	swapz_u32 count, struct sse2_forward_ab_pair *pairs)
{
#if defined(__x86_64__)
	unsigned int round;
	swapz_u32 index;

	if (!pairs || !count)
		return -EINVAL;
	/*
	 * Keep both arms byte-identical to scalar. The legacy 1x implementation
	 * remains native-only; the 2x arm is now the production SSE2 function.
	 */
	for (index = 0; index < count; ++index) {
		if (swapz_predict_delta64_sse2_baseline(
			    evidence_pages[index], transform_page) ||
		    memcmp(transform_page, delta64_pages[index],
			   SWAPZ_BLOCK_BYTES) ||
		    swapz_predict_delta64_sse2(
			    evidence_pages[index], transform_page) ||
		    memcmp(transform_page, delta64_pages[index],
			   SWAPZ_BLOCK_BYTES))
			return -EUCLEAN;
	}
	for (round = 0; round < SSE2_FORWARD_AB_PAIRS; ++round) {
		struct sse2_forward_ab_pair *pair = &pairs[round];

		/*
		 * Warm both arms on the same immutable corpus before each pair.
		 * Alternate timed order to limit drift bias. JSON keeps the historical
		 * "unrolled" field name for report compatibility; it now means the
		 * promoted production 2x implementation.
		 */
		for (index = 0; index < count; ++index) {
			if (swapz_predict_delta64_sse2_baseline(
				    evidence_pages[index], transform_page) ||
			    swapz_predict_delta64_sse2(
				    evidence_pages[index], transform_page))
				return -EUCLEAN;
		}
		if (round & 1U) {
			if (benchmark_sse2_forward_arm(
				    swapz_predict_delta64_sse2, count,
				    &pair->unrolled_ns_per_page) ||
			    benchmark_sse2_forward_arm(
				    swapz_predict_delta64_sse2_baseline, count,
				    &pair->baseline_ns_per_page))
				return -EUCLEAN;
		} else {
			if (benchmark_sse2_forward_arm(
				    swapz_predict_delta64_sse2_baseline, count,
				    &pair->baseline_ns_per_page) ||
			    benchmark_sse2_forward_arm(
				    swapz_predict_delta64_sse2, count,
				    &pair->unrolled_ns_per_page))
				return -EUCLEAN;
		}
	}
#else
	(void)count;
	(void)pairs;
#endif
	return 0;
}

static const struct backend_benchmark *find_backend(const struct backend_benchmark *backends,
						     unsigned int count, const char *name)
{
	unsigned int index; for (index = 0; index < count; ++index) if (!strcmp(backends[index].name, name)) return &backends[index];
	return NULL;
}
static int benchmark_second_lz4(swapz_u32 count, uint64_t *ns_per_page)
{
	uint64_t start, end, sink = 0, calls = (uint64_t)count * LZ4_BENCH_REPEATS;
	unsigned int repeat; swapz_u32 index;
	if (!count || !ns_per_page) return -EINVAL;
	start = now_ns();
	for (repeat = 0; repeat < LZ4_BENCH_REPEATS; ++repeat)
		for (index = 0; index < count; ++index) {
			int length = compress_page_lz4(delta64_pages[index]);
			if (length < 0 || length > PREDICTOR_CAP) return -EUCLEAN;
			sink += (uint64_t)length;
		}
	end = now_ns(); transform_benchmark_sink += sink;
	if (!start || !end || !calls) return -EUCLEAN;
	*ns_per_page = (end - start) / calls; return 0;
}
static int account_routed_cpu(struct threshold_summary *rows,
			      const struct classifier_summary *classifier,
			      const struct transform_summary *transform,
			      swapz_u32 total_count)
{
	uint64_t classifier_ns, transform_ns, second_lz4_ns; unsigned int index;
	if (!rows || !classifier || !transform || !total_count || !classifier->benchmark_calls) return -EINVAL;
	classifier_ns = classifier->wall_ns / classifier->benchmark_calls;
	transform_ns = transform->transform_ns / total_count;
	second_lz4_ns = transform->second_lz4_ns / total_count;
	for (index = 0; index < THRESHOLD_COUNT; ++index) {
		uint64_t eligible = (uint64_t)rows[index].negative_eligible + rows[index].structured_eligible;
		uint64_t calls = (uint64_t)rows[index].negative_calls + rows[index].structured_calls;
		long saved = (long)rows[index].routed_baseline_blocks - (long)rows[index].routed_candidate_blocks;
		rows[index].routed_cpu_ns_total = eligible * classifier_ns + calls * (transform_ns + second_lz4_ns);
		rows[index].routed_cpu_ns_per_page = rows[index].routed_cpu_ns_total / total_count;
		rows[index].ns_per_saved_block = saved > 0 ? rows[index].routed_cpu_ns_total / (uint64_t)saved : 0;
	}
	return 0;
}

static int summarize_thresholds(const struct page_evidence *rows,
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
		int error;

		summary->threshold = thresholds[threshold_index];
		for (index = 0; index < total_count; ++index) {
			const struct page_evidence *row = &rows[index];
			int candidate = row->candidate_length[TRANSFORM_DELTA64];
			struct swapz_delta64_route route = row->route;
			int eligible = route.threshold != 0;
			int call = eligible && row->classifier_ran &&
				row->classifier_score >= summary->threshold;
			int useful;
			int structured = index >= structured_start;

			route.threshold = (swapz_u8)summary->threshold;
			useful = call && swapz_delta64_candidate_adoptable(
				&route, row->baseline_length, candidate);

			if (structured) {
				if (!eligible)
					continue;
				summary->structured_eligible++;
				summary->structured_calls += call;
				summary->structured_useful += useful;
			} else if (index < negative_count &&
				   row->negative_profile < NEGATIVE_PROFILE_COUNT) {
				struct profile_threshold_summary *profile =
					&summary->profiles[row->negative_profile];

				profile->pages++;
				if (!eligible)
					continue;
				profile->eligible++;
				profile->calls += call;
				profile->useful += useful;
				summary->negative_eligible++;
				summary->negative_calls += call;
				summary->negative_useful += useful;
			}
		}
		error = planner_totals(rows + structured_start,
			total_count - structured_start, TRANSFORM_DELTA64,
			0, 0, &summary->routed_baseline_blocks,
			&summary->routed_baseline_extents);
		if (!error)
				error = planner_totals(rows + structured_start,
				total_count - structured_start, TRANSFORM_DELTA64,
				2, summary->threshold,
				&summary->routed_candidate_blocks,
				&summary->routed_candidate_extents);
		if (error)
			return error;
	}
	return 0;
}

static int summarize_production_route(const struct page_evidence *rows,
				      swapz_u32 count,
				      uint64_t classifier_ns_per_page,
				      uint64_t transform_ns_per_page,
				      uint64_t second_lz4_ns_per_page,
				      struct production_route_summary *summary)
{
	swapz_u32 index;
	uint64_t transform_calls = 0;
	long saved_blocks;
	int error;

	if (!rows || !count || !summary)
		return -EINVAL;
	memset(summary, 0, sizeof(*summary));
	for (index = 0; index < count; ++index) {
		const struct page_evidence *row = &rows[index];
		int candidate = row->candidate_length[TRANSFORM_DELTA64];

		if (!row->route.threshold)
			continue;
		summary->eligible_pages++;
		summary->packing_eligible_pages += row->route.pack_path;
		if (!row->classifier_ran ||
		    row->classifier_score < row->route.threshold)
			continue;
		summary->classifier_passes++;
		transform_calls++;
		summary->candidate_attempts++;
		if (!swapz_delta64_candidate_smaller(row->baseline_length,
						     candidate))
			continue;
		if (row->route.pack_path && candidate > row->route.pack_limit)
			continue;
		summary->adopted_pages++;
		summary->packing_adoptions += row->route.pack_path;
		if (row->baseline_length > 0)
			summary->lz4_rescues++;
		else
			summary->raw_rescues++;
		summary->payload_bytes_saved += (uint64_t)(
			(row->baseline_length > 0 ? row->baseline_length :
			 (int)SWAPZ_BLOCK_BYTES) - candidate);
	}
	error = planner_totals(rows, count, TRANSFORM_DELTA64, 0, 0,
		&summary->baseline_blocks, &summary->baseline_extents);
	if (!error)
		error = planner_totals(rows, count, TRANSFORM_DELTA64, 2, 0,
			&summary->candidate_blocks, &summary->candidate_extents);
	if (error)
		return error;
	summary->modeled_wall_ns_total =
		(uint64_t)summary->eligible_pages * classifier_ns_per_page +
		transform_calls * (transform_ns_per_page + second_lz4_ns_per_page);
	summary->modeled_wall_ns_per_page =
		summary->modeled_wall_ns_total / count;
	saved_blocks = (long)summary->baseline_blocks -
		(long)summary->candidate_blocks;
	summary->ns_per_saved_block = saved_blocks > 0 ?
		summary->modeled_wall_ns_total / (uint64_t)saved_blocks : 0;
	return 0;
}

int main(int argc, char **argv)
{
	struct transform_summary total_summary[TRANSFORM_COUNT] = { 0 };
	struct transform_summary structured_summary[TRANSFORM_COUNT] = { 0 };
	struct threshold_summary threshold_summary[THRESHOLD_COUNT] = { 0 };
	struct classifier_summary classifier_summary = { 0 };
	struct production_route_summary production_route = { 0 };
	struct sampling_control sampling_controls[2] = { 0 };
	struct backend_benchmark backend_benchmarks[MAX_BACKEND_BENCHMARKS] = { 0 };
	struct sse2_forward_ab_pair sse2_forward_ab[SSE2_FORWARD_AB_PAIRS] = { 0 };
	struct lz4_acceleration_summary
		lz4_acceleration_summaries[LZ4_ACCELERATION_COUNT] = { 0 };
	const struct backend_benchmark *selected_transform, *selected_inverse, *scalar_backend;
	uint64_t second_lz4_ns_per_page = 0;
	unsigned int backend_count = 0;
	swapz_u32 count = 0, negative_count, structured_start;
	swapz_u8 page[SWAPZ_BLOCK_BYTES];
	unsigned int kind, page_index, transform_index, threshold_index;
	int argument, error;

	error = swapz_predictor_init();
	if (error) {
		fprintf(stderr, "predictor backend initialization failed: %d\n",
			error);
		return 1;
	}
	error = evaluate_sampling_controls(sampling_controls);
	if (!error)
		error = evaluate_route_controls();
	if (error) {
		fprintf(stderr, "predictor sampling/route control failed: %d\n",
			error);
		return 1;
	}
	if (argc != 4) {
		fprintf(stderr, "predictor qualification requires entropy/mixed/medium fixtures\n");
		return 2;
	}
	for (argument = 0; argument < 2; ++argument) {
		int error = append_generated_negative((swapz_u8)argument, &count,
						 total_summary,
						 &classifier_summary);

		if (error)
			return 1;
	}
	for (argument = 1; argument < argc; ++argument) {
		int error = append_negative_file(argv[argument],
			(swapz_u8)(argument + 1), &count, total_summary,
			&classifier_summary);

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
			memcpy(evidence_pages[count], page, sizeof(page));
			error = evaluate_page(page, 1, 0, &evidence[count],
					      total_summary, &classifier_summary);
			if (error) {
				fprintf(stderr,
					"structured predictor roundtrip failed kind=%u page=%u error=%d\n",
					kind, page_index, error);
				return 1;
			}
			count++;
		}

	error = benchmark_classifier(evidence, count, &classifier_summary);
	if (error) {
		fprintf(stderr, "predictor classifier batch benchmark failed: %d\n", error);
		return 1;
	}
	error = build_delta64_pages(count);
	if (!error) error = collect_backend_benchmarks(backend_benchmarks, &backend_count, count);
	if (!error) error = benchmark_sse2_forward_ab(count, sse2_forward_ab);
	if (!error) error = benchmark_second_lz4(count, &second_lz4_ns_per_page);
	if (error) { fprintf(stderr, "predictor backend batch benchmark failed: %d\n", error); return 1; }
	selected_transform = find_backend(backend_benchmarks, backend_count, swapz_predictor_transform_backend_name());
	selected_inverse = find_backend(backend_benchmarks, backend_count, swapz_predictor_inverse_backend_name());
	scalar_backend = find_backend(backend_benchmarks, backend_count, "scalar");
	if (!selected_transform || !selected_inverse || !scalar_backend) return 1;
	total_summary[0].transform_ns = selected_transform->transform_ns_per_page * count;
	total_summary[0].inverse_ns = selected_inverse->inverse_ns_per_page * count;
	total_summary[0].scalar_transform_ns = scalar_backend->transform_ns_per_page * count;
	total_summary[0].scalar_inverse_ns = scalar_backend->inverse_ns_per_page * count;
	total_summary[0].second_lz4_ns = second_lz4_ns_per_page * count;

	for (transform_index = 0; transform_index < TRANSFORM_COUNT;
	     ++transform_index) {
		int error;

		structured_summary[transform_index].transform_ns =
			total_summary[transform_index].transform_ns;
		structured_summary[transform_index].inverse_ns =
			total_summary[transform_index].inverse_ns;
		structured_summary[transform_index].scalar_transform_ns =
			total_summary[transform_index].scalar_transform_ns;
		structured_summary[transform_index].scalar_inverse_ns =
			total_summary[transform_index].scalar_inverse_ns;
		structured_summary[transform_index].second_lz4_ns =
			total_summary[transform_index].second_lz4_ns;
		summarize_transform(evidence + structured_start,
			count - structured_start, transform_index,
			&structured_summary[transform_index]);
		error = planner_totals(evidence + structured_start,
			count - structured_start, transform_index, 0, 0,
			&structured_summary[transform_index].baseline_blocks,
			&structured_summary[transform_index].baseline_extents);
		if (!error)
			error = planner_totals(evidence + structured_start,
				count - structured_start, transform_index, 1, 0,
				&structured_summary[transform_index].candidate_blocks,
				&structured_summary[transform_index].candidate_extents);
		if (error) {
			fprintf(stderr, "production planner rejected evidence: %d\n", error);
			return 1;
		}
	}
	error = summarize_thresholds(evidence, negative_count, structured_start, count, threshold_summary);
	if (!error) error = account_routed_cpu(threshold_summary, &classifier_summary, &total_summary[0], count);
	if (!error)
		error = summarize_production_route(evidence, count,
			classifier_summary.benchmark_calls ?
			classifier_summary.wall_ns /
			classifier_summary.benchmark_calls : 0,
			total_summary[0].transform_ns / count,
			total_summary[0].second_lz4_ns / count,
			&production_route);
	if (!error && production_route.eligible_pages != classifier_summary.pages)
		error = -EUCLEAN;
	if (!error)
		error = collect_lz4_acceleration_sweep(
			evidence, count, lz4_acceleration_summaries);
	if (error) {
		fprintf(stderr, "routed production planner rejected evidence: %d\n",
			error);
		return 1;
	}

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
	       "\"classifier\":{\"candidate\":\"delta64\","
	       "\"backend\":\"scalar\","
	       "\"sample_pairs\":%u,\"stage1_pairs\":%u,"
	       "\"stage1_min_score\":%u,\"eligible_pages\":%u,"
	       "\"early_abort_pages\":%u,\"benchmark_repeats\":%u,"
	       "\"benchmark_calls\":%" PRIu64 ","
	       "\"ns_per_page\":%" PRIu64 ","
	       "\"scalar_ns_per_page\":%" PRIu64 "}",
	       negative_count, count - structured_start,
	       SWAPZ_PREDICTOR_SAMPLE_PAIRS, SWAPZ_PREDICTOR_STAGE1_PAIRS,
	       SWAPZ_PREDICTOR_STAGE1_MIN_SCORE, classifier_summary.pages,
	       classifier_summary.early_abort_pages, CLASSIFIER_BENCH_REPEATS,
	       classifier_summary.benchmark_calls,
	       classifier_summary.benchmark_calls ?
	       classifier_summary.wall_ns / classifier_summary.benchmark_calls : 0,
	       classifier_summary.benchmark_calls ?
	       classifier_summary.scalar_wall_ns / classifier_summary.benchmark_calls : 0);
	printf(",\"lz4_acceleration_sweep\":[");
	for (threshold_index = 0;
	     threshold_index < LZ4_ACCELERATION_COUNT;
	     ++threshold_index) {
		const struct lz4_acceleration_summary *item =
			&lz4_acceleration_summaries[threshold_index];

		printf("%s{\"acceleration\":%u,\"wall_ns_per_page\":%" PRIu64
		       ",\"accepted_payload_bytes\":%" PRIu64
		       ",\"raw_pages\":%u,\"planner_blocks\":%u,"
		       "\"planner_extents\":%u}",
		       threshold_index ? "," : "", item->acceleration,
		       item->wall_ns_per_page, item->accepted_payload_bytes,
		       item->raw_pages, item->planner_blocks,
		       item->planner_extents);
	}
	printf("],\"sampling_controls\":[");
	for (threshold_index = 0; threshold_index < 2U; ++threshold_index)
		printf("%s{\"name\":\"%s\",\"score\":%u,"
		       "\"minimum_score\":%u}",
		       threshold_index ? "," : "",
		       sampling_controls[threshold_index].name,
		       sampling_controls[threshold_index].score,
		       sampling_controls[threshold_index].minimum_score);
	printf("],\"backend_benchmarks\":[");
	for (transform_index = 0; transform_index < backend_count; ++transform_index) {
		const struct backend_benchmark *backend = &backend_benchmarks[transform_index];
		printf("%s{\"name\":\"%s\",\"transform_ns_per_page\":%" PRIu64 ",\"inverse_ns_per_page\":%" PRIu64 "}",
		       transform_index ? "," : "", backend->name, backend->transform_ns_per_page, backend->inverse_ns_per_page);
	}
	printf("],\"sse2_forward_ab\":");
#if defined(__x86_64__)
	printf("{\"scope\":\"SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION\","
	       "\"pages\":%u,\"repeats_per_arm\":%u,\"pairs\":[",
	       count, SSE2_FORWARD_AB_REPEATS);
	for (transform_index = 0; transform_index < SSE2_FORWARD_AB_PAIRS;
	     ++transform_index) {
		const struct sse2_forward_ab_pair *pair =
			&sse2_forward_ab[transform_index];

		printf("%s{\"order\":\"%s\",\"baseline_ns_per_page\":%" PRIu64
		       ",\"unrolled_ns_per_page\":%" PRIu64 "}",
		       transform_index ? "," : "",
		       transform_index & 1U ? "unrolled_first" : "baseline_first",
		       pair->baseline_ns_per_page, pair->unrolled_ns_per_page);
	}
	printf("]}");
#else
	printf("null");
#endif
	printf(",\"io_model_block_ns\":{\"sd_emulated\":%" PRIu64 ",\"ssd_emulated\":%" PRIu64 "},\"thresholds\":[",
	       (uint64_t)SD_EMULATED_BLOCK_NS, (uint64_t)SSD_EMULATED_BLOCK_NS);
	for (threshold_index = 0; threshold_index < THRESHOLD_COUNT;
	     ++threshold_index) {
		const struct threshold_summary *item =
			&threshold_summary[threshold_index];

		unsigned int profile_index;

		printf("%s{\"threshold\":%u,\"negative_eligible\":%u,"
		       "\"negative_calls\":%u,\"negative_useful\":%u,"
		       "\"structured_eligible\":%u,\"structured_calls\":%u,"
		       "\"structured_useful\":%u,"
		       "\"routed_baseline_blocks\":%u,"
		       "\"routed_candidate_blocks\":%u,"
		       "\"routed_blocks_saved\":%ld,"
		       "\"routed_baseline_extents\":%u,"
		       "\"routed_candidate_extents\":%u,"
		       "\"routed_extents_saved\":%ld,\"routed_cpu_ns_total\":%" PRIu64 ",\"routed_cpu_ns_per_page\":%" PRIu64 ",\"ns_per_saved_block\":%" PRIu64 ","
		       "\"negative_profiles\":[",
		       threshold_index ? "," : "", item->threshold,
		       item->negative_eligible, item->negative_calls,
		       item->negative_useful, item->structured_eligible,
		       item->structured_calls, item->structured_useful,
		       item->routed_baseline_blocks, item->routed_candidate_blocks,
		       (long)item->routed_baseline_blocks -
			       (long)item->routed_candidate_blocks,
		       item->routed_baseline_extents, item->routed_candidate_extents,
		       (long)item->routed_baseline_extents - (long)item->routed_candidate_extents,
		       item->routed_cpu_ns_total, item->routed_cpu_ns_per_page, item->ns_per_saved_block);
		for (profile_index = 0; profile_index < NEGATIVE_PROFILE_COUNT;
		     ++profile_index) {
			const struct profile_threshold_summary *profile =
				&item->profiles[profile_index];

			printf("%s{\"name\":\"%s\",\"pages\":%u,"
			       "\"eligible\":%u,\"calls\":%u,\"useful\":%u}",
			       profile_index ? "," : "",
			       negative_profile_names[profile_index],
			       profile->pages, profile->eligible,
			       profile->calls, profile->useful);
		}
		printf("]}");
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
		       "\"planner_extents_saved\":%ld,\"transform_backend\":\"%s\",\"inverse_backend\":\"%s\","
		       "\"transform_ns_per_page\":%" PRIu64 ","
		       "\"inverse_ns_per_page\":%" PRIu64 ","
		       "\"scalar_transform_ns_per_page\":%" PRIu64 ","
		       "\"scalar_inverse_ns_per_page\":%" PRIu64 ","
		       "\"second_lz4_ns_per_page\":%" PRIu64 "}",
		       transform_index ? "," : "", transforms[transform_index].name,
		       item->adopted, item->raw_rescued, item->cliff_2024,
		       item->saved_payload_bytes, item->baseline_blocks,
		       item->candidate_blocks, block_saved,
		       item->baseline_extents, item->candidate_extents, extent_saved,
		       swapz_predictor_transform_backend_name(), swapz_predictor_inverse_backend_name(),
		       total_summary[transform_index].transform_ns / pages,
		       total_summary[transform_index].inverse_ns / pages,
		       total_summary[transform_index].scalar_transform_ns / pages,
		       total_summary[transform_index].scalar_inverse_ns / pages,
		       total_summary[transform_index].second_lz4_ns / pages);
	}
	printf("],\"production_route\":{\"scope\":"
	       "\"OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY\","
	       "\"general_threshold\":%u,\"packing_threshold\":%u,"
	       "\"eligible_pages\":%u,\"packing_eligible_pages\":%u,"
	       "\"classifier_passes\":%u,\"candidate_attempts\":%u,"
	       "\"adopted_pages\":%u,\"raw_rescues\":%u,"
	       "\"lz4_rescues\":%u,\"packing_adoptions\":%u,"
	       "\"payload_bytes_saved\":%" PRIu64 ","
	       "\"baseline_blocks\":%u,\"candidate_blocks\":%u,"
	       "\"blocks_saved\":%ld,\"baseline_extents\":%u,"
	       "\"candidate_extents\":%u,\"extents_saved\":%ld,"
	       "\"modeled_wall_ns_total\":%" PRIu64 ","
	       "\"modeled_wall_ns_per_page\":%" PRIu64 ","
	       "\"ns_per_saved_block\":%" PRIu64 "}}\n",
	       SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD,
	       SWAPZ_PREDICTOR_PACK_THRESHOLD,
	       production_route.eligible_pages,
	       production_route.packing_eligible_pages,
	       production_route.classifier_passes,
	       production_route.candidate_attempts,
	       production_route.adopted_pages,
	       production_route.raw_rescues,
	       production_route.lz4_rescues,
	       production_route.packing_adoptions,
	       production_route.payload_bytes_saved,
	       production_route.baseline_blocks,
	       production_route.candidate_blocks,
	       (long)production_route.baseline_blocks -
	       (long)production_route.candidate_blocks,
	       production_route.baseline_extents,
	       production_route.candidate_extents,
	       (long)production_route.baseline_extents -
	       (long)production_route.candidate_extents,
	       production_route.modeled_wall_ns_total,
	       production_route.modeled_wall_ns_per_page,
	       production_route.ns_per_saved_block);
	printf("PASS: predictor transforms round-trip; structured corpus saves planner blocks; "
	       "negative controls measured\n");
	return 0;
}
