// SPDX-License-Identifier: GPL-2.0-only
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <inttypes.h>
#include <lz4.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <unistd.h>

#include "engine.h"
#include "predictor.h"
#include "predictor-internal.h"
#include "predictor-route.h"

#define PAGE_BYTES SWAPZ_BLOCK_BYTES
#define SIZE_BUCKETS 6U
#define MAX_SAMPLE_PAGES (1ULL << 20)

struct page_sample {
	int baseline_length;
	int candidate_length;
	struct swapz_delta64_route route;
	swapz_u32 score;
	swapz_u8 is_zero;
	swapz_u8 adopted;
};

struct sample_totals {
	uint64_t pages;
	uint64_t zero_pages;
	uint64_t nonzero_same_filled_pages;
	uint64_t baseline_size_buckets[SIZE_BUCKETS];
	uint64_t candidate_size_buckets[SIZE_BUCKETS];
	uint64_t baseline_payload_bytes;
	uint64_t candidate_payload_bytes;
	uint64_t baseline_raw_pages;
	uint64_t candidate_raw_pages;
	uint64_t classifier_eligible_pages;
	uint64_t classifier_scored_pages;
	uint64_t classifier_passes;
	uint64_t classifier_score_buckets[4];
	uint64_t transform_attempts;
	uint64_t adopted_pages;
	uint64_t direct_adoptions;
	uint64_t direct_raw_adoptions;
	uint64_t direct_lz4_adoptions;
	uint64_t raw_rescues;
	uint64_t lz4_rescues;
	uint64_t packing_eligible_pages;
	uint64_t packing_attempts;
	uint64_t packing_adoptions;
	uint64_t payload_bytes_saved;
	uint64_t payload_bytes_added;
	uint64_t planner_windows;
	uint64_t baseline_lower_blocks;
	uint64_t baseline_extents;
	uint64_t candidate_lower_blocks;
	uint64_t candidate_extents;
};

struct sensitive_buffers {
	swapz_u8 page[PAGE_BYTES];
	swapz_u8 scratch[PAGE_BYTES];
	swapz_u8 transformed[PAGE_BYTES];
	char lz4_output[SWAPZ_MAX_COMPRESSED];
};

static const char *const size_bucket_names[SIZE_BUCKETS] = {
	"raw", "1_256", "257_1024", "1025_2048", "2049_3072",
	"3073_3568",
};

static swapz_u8 planner_dummy[PAGE_BYTES];

/* Keep private sample bytes out of swap and make the wipe resistant to DSE. */
static void secure_clear(void *memory, size_t length)
{
	volatile swapz_u8 *bytes = memory;

	while (length--)
		*bytes++ = 0;
}

static int protect_sample_buffers(struct sensitive_buffers *buffers)
{
	struct rlimit core_limit = { 0, 0 };

	if (setrlimit(RLIMIT_CORE, &core_limit))
		return -errno;
	if (prctl(PR_SET_DUMPABLE, 0, 0L, 0L, 0L))
		return -errno;
	if (mlock(buffers, sizeof(*buffers)))
		return -errno;
	return 0;
}

static unsigned int size_bucket(int length)
{
	if (length <= 0)
		return 0;
	if (length <= 256)
		return 1;
	if (length <= 1024)
		return 2;
	if (length <= 2048)
		return 3;
	if (length <= 3072)
		return 4;
	return 5;
}

static int page_is_nonzero_same_filled(const swapz_u8 *page)
{
	swapz_u32 offset;

	if (!page[0])
		return 0;
	for (offset = 1; offset < PAGE_BYTES; ++offset)
		if (page[offset] != page[0])
			return 0;
	return 1;
}

/* Read one complete page without stdio read-ahead or retaining a corpus. */
static int read_page(int fd, swapz_u8 *page, int *eof, int *partial)
{
	size_t used = 0;

	*eof = 0;
	*partial = 0;
	while (used < PAGE_BYTES) {
		ssize_t got = read(fd, page + used, PAGE_BYTES - used);

		if (got > 0) {
			used += (size_t)got;
			continue;
		}
		if (!got) {
			if (!used) {
				*eof = 1;
				return 0;
			}
			*partial = 1;
			return 0;
		}
		if (errno == EINTR)
			continue;
		return -errno;
	}
	return 0;
}

static int compress_page(const swapz_u8 *page, char *output,
		 unsigned int acceleration)
{
	int length = LZ4_compress_fast((const char *)page, output, PAGE_BYTES,
				       SWAPZ_MAX_COMPRESSED, (int)acceleration);

	if (length < 0 || length > (int)SWAPZ_MAX_COMPRESSED)
		return -EUCLEAN;
	return length;
}

static unsigned int classifier_score_bucket(swapz_u32 score)
{
	if (score < 8U)
		return 0;
	if (score < 16U)
		return 1;
	if (score < 24U)
		return 2;
	return 3;
}

static void classifier_observe(struct sample_totals *totals, swapz_u32 score)
{
	totals->classifier_eligible_pages++;
	totals->classifier_scored_pages++;
	totals->classifier_score_buckets[classifier_score_bucket(score)]++;
}

static void record_adoption(struct page_sample *sample,
			    struct sample_totals *totals, int direct)
{
	int baseline_bytes = sample->baseline_length > 0 ?
		sample->baseline_length : (int)PAGE_BYTES;
	int64_t payload_delta = (int64_t)sample->candidate_length -
		baseline_bytes;

	sample->adopted = 1;
	totals->adopted_pages++;
	if (direct) {
		totals->direct_adoptions++;
		if (sample->baseline_length > 0)
			totals->direct_lz4_adoptions++;
		else
			totals->direct_raw_adoptions++;
	} else {
		if (sample->baseline_length > 0)
			totals->lz4_rescues++;
		else
			totals->raw_rescues++;
		if (sample->route.pack_path)
			totals->packing_adoptions++;
	}
	if (payload_delta < 0)
		totals->payload_bytes_saved += (uint64_t)(-payload_delta);
	else
		totals->payload_bytes_added += (uint64_t)payload_delta;
}

static int analyze_page(const swapz_u8 *page, swapz_u8 *scratch,
			swapz_u8 *transformed, char *lz4_output,
			struct page_sample *sample,
			struct sample_totals *totals)
{
	int error;
	unsigned int bucket;

	memset(sample, 0, sizeof(*sample));
	sample->is_zero = swapz_page_is_zero(page);
	totals->pages++;
	totals->zero_pages += sample->is_zero;
	if (!sample->is_zero && page_is_nonzero_same_filled(page))
		totals->nonzero_same_filled_pages++;

	{
		swapz_u32 scalar_score =
			swapz_predict_delta64_sample_score_scalar(page);

		sample->score = swapz_predict_delta64_sample_score(page);
		if (sample->score != scalar_score)
			return -EUCLEAN;
	}
	sample->baseline_length = compress_page(
		page, lz4_output, SWAPZ_LZ4_ORDINARY_ACCELERATION_DEFAULT);
	if (sample->baseline_length < 0)
		return sample->baseline_length;
	error = swapz_predict_delta64_shuf8(page, scratch, transformed);
	if (error)
		return -EUCLEAN;
	sample->candidate_length = compress_page(
		transformed, lz4_output,
		SWAPZ_LZ4_DELTA64_ACCELERATION_DEFAULT);
	if (sample->candidate_length < 0)
		return sample->candidate_length;

	bucket = size_bucket(sample->baseline_length);
	totals->baseline_size_buckets[bucket]++;
	if (sample->baseline_length > 0)
		totals->baseline_payload_bytes +=
			(uint64_t)sample->baseline_length;
	else
		totals->baseline_raw_pages++;

	bucket = size_bucket(sample->candidate_length);
	totals->candidate_size_buckets[bucket]++;
	if (sample->candidate_length > 0)
		totals->candidate_payload_bytes +=
			(uint64_t)sample->candidate_length;
	else
		totals->candidate_raw_pages++;

	/* Production's zero fast path returns before route accounting. */
	if (sample->is_zero)
		return 0;
	if (sample->score >= SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD) {
		classifier_observe(totals, sample->score);
		totals->classifier_passes++;
		totals->transform_attempts++;
		if (sample->candidate_length > 0 &&
		    sample->candidate_length <=
				(int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH) {
			record_adoption(sample, totals, 1);
			return 0;
		}
		if (!swapz_delta64_candidate_smaller(sample->baseline_length,
						 sample->candidate_length) ||
		    !swapz_delta64_route_init(sample->baseline_length,
					      &sample->route) ||
		    !swapz_delta64_candidate_adoptable(
				&sample->route, sample->baseline_length,
				sample->candidate_length))
			return 0;
		record_adoption(sample, totals, 0);
		return 0;
	}
	if (sample->score < SWAPZ_PREDICTOR_PACK_THRESHOLD) {
		if (sample->baseline_length > (int)PAGE_BYTES ||
		    (sample->baseline_length > 0 &&
		     sample->baseline_length < 48))
			return 0;
		classifier_observe(totals, sample->score);
		if (sample->baseline_length > 0 &&
		    sample->baseline_length <=
				(int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH)
			totals->packing_eligible_pages++;
		return 0;
	}
	if (sample->baseline_length <= 0 ||
	    sample->baseline_length > (int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH) {
		if (sample->baseline_length <= (int)PAGE_BYTES)
			classifier_observe(totals, sample->score);
		return 0;
	}
	if (!swapz_delta64_route_init(sample->baseline_length, &sample->route))
		return 0;
	classifier_observe(totals, sample->score);
	totals->packing_eligible_pages += sample->route.pack_path;
	if (sample->score < sample->route.threshold)
		return 0;
	totals->classifier_passes++;
	totals->transform_attempts++;
	if (sample->route.pack_path)
		totals->packing_attempts++;
	if (swapz_delta64_candidate_adoptable(
		    &sample->route, sample->baseline_length,
		    sample->candidate_length))
		record_adoption(sample, totals, 0);

	return 0;
}

static int planner_window(const struct page_sample *samples, swapz_u8 count,
			  int use_candidate, uint64_t *blocks_out,
			  uint64_t *extents_out)
{
	struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
	swapz_u8 classes[SWAPZ_MAX_RECORDS];
	swapz_u8 takes[SWAPZ_MAX_RECORDS];
	swapz_u8 extent_count = 0;
	swapz_u8 compressed_count = 0;
	swapz_u32 raw_count = 0;
	swapz_u32 index;
	int error;

	memset(pages, 0, sizeof(pages));
	for (index = 0; index < count; ++index) {
		int length;

		if (samples[index].is_zero)
			continue;
		length = use_candidate && samples[index].adopted ?
			samples[index].candidate_length :
			samples[index].baseline_length;
		if (length <= 0) {
			raw_count++;
			continue;
		}
		pages[compressed_count].logical_page = index;
		pages[compressed_count].payload = planner_dummy;
		pages[compressed_count].length = (swapz_u16)length;
		pages[compressed_count].raw = 0;
		pages[compressed_count].encoding =
			use_candidate && samples[index].adopted ?
			SWAPZ_ENCODING_DELTA64_SHUF8 : SWAPZ_ENCODING_LZ4;
		compressed_count++;
	}

	*blocks_out = raw_count;
	*extents_out = raw_count;
	if (!compressed_count)
		return 0;
	error = swapz_engine_plan_bounded(pages, compressed_count, 0, classes,
					 takes, &extent_count);
	if (error)
		return error;
	for (index = 0; index < extent_count; ++index)
		*blocks_out += classes[index];
	*extents_out += extent_count;
	return 0;
}

static void print_histogram(const char *name,
			    const uint64_t buckets[SIZE_BUCKETS])
{
	unsigned int index;

	printf("\"%s\":{", name);
	for (index = 0; index < SIZE_BUCKETS; ++index)
		printf("%s\"%s\":%" PRIu64,
		       index ? "," : "", size_bucket_names[index], buckets[index]);
	putchar('}');
}

static int analyze_stream(void)
{
	struct sample_totals totals = { 0 };
	struct page_sample window[SWAPZ_MAX_RECORDS];
	struct sensitive_buffers buffers = { 0 };
	swapz_u8 window_count = 0;
	int buffers_locked = 0;
	int status = 2;
	int error;

	if (isatty(STDIN_FILENO)) {
		fprintf(stderr, "page stream must be supplied on standard input\n");
		return 2;
	}
	if (swapz_predictor_init()) {
		fprintf(stderr, "predictor backend initialization failed\n");
		return 2;
	}
	error = protect_sample_buffers(&buffers);
	if (error) {
		fprintf(stderr, "cannot protect private sample buffers\n");
		goto out;
	}
	buffers_locked = 1;

	for (;;) {
		int eof = 0;
		int partial = 0;
		uint64_t blocks, extents;

		error = read_page(STDIN_FILENO, buffers.page, &eof, &partial);
		if (error) {
			secure_clear(&buffers, sizeof(buffers));
			fprintf(stderr, "cannot read page stream\n");
			goto out;
		}
		if (partial) {
			secure_clear(&buffers, sizeof(buffers));
			fprintf(stderr, "input ended with a partial 4 KiB page\n");
			goto out;
		}
		if (eof)
			break;
		if (totals.pages >= MAX_SAMPLE_PAGES) {
			secure_clear(&buffers, sizeof(buffers));
			fprintf(stderr, "page stream exceeds the bounded sample limit\n");
			goto out;
		}
		error = analyze_page(buffers.page, buffers.scratch,
				    buffers.transformed, buffers.lz4_output,
				    &window[window_count], &totals);
		secure_clear(&buffers, sizeof(buffers));
		if (error) {
			fprintf(stderr, "page analysis failed validation\n");
			goto out;
		}
		window_count++;
		if (window_count < SWAPZ_MAX_RECORDS)
			continue;
		error = planner_window(window, window_count, 0, &blocks, &extents);
		if (error)
			goto planner_error;
		totals.baseline_lower_blocks += blocks;
		totals.baseline_extents += extents;
		error = planner_window(window, window_count, 1, &blocks, &extents);
		if (error)
			goto planner_error;
		totals.candidate_lower_blocks += blocks;
		totals.candidate_extents += extents;
		totals.planner_windows++;
		memset(window, 0, sizeof(window));
		window_count = 0;
	}

	if (!totals.pages) {
		fprintf(stderr, "page stream is empty\n");
		goto out;
	}
	if (window_count) {
		uint64_t blocks, extents;

		error = planner_window(window, window_count, 0, &blocks, &extents);
		if (error)
			goto planner_error;
		totals.baseline_lower_blocks += blocks;
		totals.baseline_extents += extents;
		error = planner_window(window, window_count, 1, &blocks, &extents);
		if (error)
			goto planner_error;
		totals.candidate_lower_blocks += blocks;
		totals.candidate_extents += extents;
		totals.planner_windows++;
	}

	printf("{\"schema\":\"swapz-anon-page-analysis-v1\",");
	printf("\"scope\":\"offline aggregate only; no page bytes retained\",");
	printf("\"predictor_backend\":{\"transform\":\"%s\","
	       "\"inverse\":\"%s\"},\"lz4_version\":%d,",
	       swapz_predictor_transform_backend_name(),
	       swapz_predictor_inverse_backend_name(), LZ4_VERSION_NUMBER);
	printf("\"page_bytes\":%u,\"pages\":%" PRIu64
	       ",\"zero_pages\":%" PRIu64
	       ",\"nonzero_same_filled_pages\":%" PRIu64 ",",
	       PAGE_BYTES, totals.pages, totals.zero_pages,
	       totals.nonzero_same_filled_pages);
	printf("\"lz4\":{\"acceleration\":%u,\"payload_bytes\":%" PRIu64
	       ",\"raw_pages\":%" PRIu64 ",",
	       SWAPZ_LZ4_ORDINARY_ACCELERATION_DEFAULT,
	       totals.baseline_payload_bytes, totals.baseline_raw_pages);
	print_histogram("size_buckets", totals.baseline_size_buckets);
	printf("},\"delta64_shuf8_lz4\":{\"acceleration\":%u,"
	       "\"payload_bytes\":%" PRIu64
	       ",\"raw_pages\":%" PRIu64 ",",
	       SWAPZ_LZ4_DELTA64_ACCELERATION_DEFAULT,
	       totals.candidate_payload_bytes, totals.candidate_raw_pages);
	print_histogram("size_buckets", totals.candidate_size_buckets);
	printf("},\"classifier\":{\"production_threshold\":%u,"
	       "\"eligible_pages\":%" PRIu64
	       ",\"scored_pages\":%" PRIu64
	       ",\"passes\":%" PRIu64
	       ",\"transform_attempts\":%" PRIu64
	       ",\"score_buckets\":{\"0_7\":%" PRIu64
	       ",\"8_15\":%" PRIu64
	       ",\"16_23\":%" PRIu64
	       ",\"ge24\":%" PRIu64 "}},",
	       SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD,
	       totals.classifier_eligible_pages,
	       totals.classifier_scored_pages, totals.classifier_passes,
	       totals.transform_attempts,
	       totals.classifier_score_buckets[0],
	       totals.classifier_score_buckets[1],
	       totals.classifier_score_buckets[2],
	       totals.classifier_score_buckets[3]);
	printf("\"production_route\":{\"adopted_pages\":%" PRIu64
	       ",\"direct_adoptions\":%" PRIu64
	       ",\"direct_raw_adoptions\":%" PRIu64
	       ",\"direct_lz4_adoptions\":%" PRIu64
	       ",\"raw_rescues\":%" PRIu64
	       ",\"lz4_rescues\":%" PRIu64
	       ",\"packing_eligible_pages\":%" PRIu64
	       ",\"packing_attempts\":%" PRIu64
	       ",\"packing_adoptions\":%" PRIu64
	       ",\"payload_bytes_saved\":%" PRIu64
	       ",\"payload_bytes_added\":%" PRIu64 "},",
	       totals.adopted_pages, totals.direct_adoptions,
	       totals.direct_raw_adoptions, totals.direct_lz4_adoptions,
	       totals.raw_rescues, totals.lz4_rescues,
	       totals.packing_eligible_pages, totals.packing_attempts,
	       totals.packing_adoptions, totals.payload_bytes_saved,
	       totals.payload_bytes_added);
	printf("\"planner\":{\"scope\":\"64-page windows; zero pages omitted; geometry only\","
	       "\"windows\":%" PRIu64
	       ",\"baseline_lower_blocks\":%" PRIu64
	       ",\"baseline_extents\":%" PRIu64
	       ",\"production_route_lower_blocks\":%" PRIu64
	       ",\"production_route_extents\":%" PRIu64 "}}\n",
	       totals.planner_windows, totals.baseline_lower_blocks,
	       totals.baseline_extents, totals.candidate_lower_blocks,
	       totals.candidate_extents);
	status = 0;
	goto out;

planner_error:
	fprintf(stderr, "production planner rejected sample geometry\n");
out:
	secure_clear(&buffers, sizeof(buffers));
	if (buffers_locked)
		(void)munlock(&buffers, sizeof(buffers));
	secure_clear(window, sizeof(window));
	secure_clear(&totals, sizeof(totals));
	return status;
}

int main(void)
{
	return analyze_stream();
}
