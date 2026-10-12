// SPDX-License-Identifier: GPL-2.0-only
/*
 * Reproducible benchmark for the exact V3 engine C. It uses a bounded RAM
 * lower-I/O adapter. This is not a kernel, block-device, NAND, or V2.2 test.
 */
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

#define LOGICAL_PAGES 256U
#define INITIAL_PHYSICAL_BLOCKS 8192U
#define MAX_OPS 3072U
#define MAX_READS LOGICAL_PAGES
#define LZ4_PAGE 4096U

struct memory_disk {
	sv3_u8 *bytes;
	sv3_u32 block_count;
	sv3_u32 write_calls, read_calls, write_blocks, read_blocks;
	sv3_u32 class_extents[3];
	uint64_t callback_wall_ns;
	sv3_u32 fail_write_call;
	int fail_mode, fail_reads;
};

struct dataset {
	sv3_u32 count;
	struct sv3_compressed_page *pages;
	sv3_u8 *payload_storage, *raw_pages;
	sv3_u16 *lengths;
	int has_raw_pages;
};

struct run_state {
	struct sv3_authority authority;
	struct sv3_engine engine;
	struct sv3_map *maps;
	sv3_u16 *live;
	sv3_u8 *classes, *write_scratch, *read_scratch;
	struct memory_disk disk;
	uint64_t alloc_bytes;
};

struct metrics {
	uint64_t plan_wall_ns, plan_cpu_ns, write_wall_ns, write_cpu_ns;
	uint64_t read_wall_ns, read_cpu_ns;
	uint64_t *write_latency, *read_latency;
	sv3_u32 write_latency_count, read_latency_count;
	sv3_u32 old_ordered_blocks, logical_bytes, payload_bytes;
	sv3_u32 planned_classes[3], committed;
	int error;
};

static uint64_t now_ns(clockid_t id)
{
	struct timespec t;
	if (clock_gettime(id, &t)) {
		perror("clock_gettime");
		exit(2);
	}
	return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}

static sv3_u32 rng_next(sv3_u32 *state)
{
	sv3_u32 x = *state;
	x ^= x << 13;
	x ^= x >> 17;
	x ^= x << 5;
	*state = x ? x : 0x9e3779b9U;
	return *state;
}

static int class_index(sv3_u8 blocks)
{
	return blocks == 1 ? 0 : blocks == 2 ? 1 : blocks == 4 ? 2 : -1;
}

static int memory_write(void *opaque, sv3_u32 start, sv3_u8 blocks,
			const sv3_u8 *source, sv3_u8 *completed)
{
	struct memory_disk *d = opaque;
	uint64_t begin = now_ns(CLOCK_MONOTONIC_RAW);
	sv3_u32 bytes = (sv3_u32)blocks * SV3_BLOCK_BYTES;

	*completed = 0;
	d->write_calls++;
	if (start >= d->block_count || blocks > d->block_count - start)
		return -ERANGE;
	if (d->write_calls == d->fail_write_call) {
		if (d->fail_mode == 1)
			return -EIO;
		if (d->fail_mode == 2 && blocks > 1) {
			memcpy(d->bytes + (size_t)start * SV3_BLOCK_BYTES,
			       source, SV3_BLOCK_BYTES);
			d->write_blocks++;
			*completed = 1;
			return -EIO;
		}
		if (d->fail_mode == 3) {
			*completed = blocks + 1U;
			d->callback_wall_ns +=
				now_ns(CLOCK_MONOTONIC_RAW) - begin;
			return 0;
		}
	}
	memcpy(d->bytes + (size_t)start * SV3_BLOCK_BYTES, source, bytes);
	d->write_blocks += blocks;
	*completed = blocks;
	if (d->fail_mode == 4 && d->write_calls == d->fail_write_call) {
		struct sv3_decoded decoded;
		const sv3_u8 *stored;
		if (!sv3_lookup(source, bytes, 0, &decoded, &stored))
			d->bytes[(size_t)start * SV3_BLOCK_BYTES +
				 decoded.payload_offset] ^= 0x40;
	}
	if (class_index(blocks) >= 0)
		d->class_extents[class_index(blocks)]++;
	d->callback_wall_ns += now_ns(CLOCK_MONOTONIC_RAW) - begin;
	return 0;
}

static int memory_read(void *opaque, sv3_u32 start, sv3_u8 blocks,
		       sv3_u8 *destination)
{
	struct memory_disk *d = opaque;
	d->read_calls++;
	if (d->fail_reads)
		return -EIO;
	if (start >= d->block_count || blocks > d->block_count - start)
		return -ERANGE;
	memcpy(destination, d->bytes + (size_t)start * SV3_BLOCK_BYTES,
	       (size_t)blocks * SV3_BLOCK_BYTES);
	d->read_blocks += blocks;
	return 0;
}

static int state_init(struct run_state *s, sv3_u32 operations)
{
	sv3_u32 blocks = INITIAL_PHYSICAL_BLOCKS;
	uint64_t bytes;
	memset(s, 0, sizeof(*s));
	if (operations > MAX_OPS)
		return -E2BIG;
	if (operations * 4U + 1024U > blocks) {
		blocks = operations * 4U + 1024U;
		blocks = (blocks + SV3_SEGMENT_BLOCKS - 1U) &
			 ~(SV3_SEGMENT_BLOCKS - 1U);
	}
	bytes = (uint64_t)blocks * SV3_BLOCK_BYTES;
	s->disk.bytes = calloc(1, (size_t)bytes);
	s->maps = calloc(LOGICAL_PAGES, sizeof(*s->maps));
	s->live = calloc(blocks, sizeof(*s->live));
	s->classes = calloc(blocks, sizeof(*s->classes));
	s->write_scratch = calloc(1, SV3_MAX_EXTENT_BYTES);
	s->read_scratch = calloc(1, SV3_MAX_EXTENT_BYTES);
	if (!s->disk.bytes || !s->maps || !s->live || !s->classes ||
	    !s->write_scratch || !s->read_scratch)
		return -ENOMEM;
	s->disk.block_count = blocks;
	if (sv3_authority_init(&s->authority, s->maps, s->live, s->classes,
			       LOGICAL_PAGES, blocks))
		return -ENOSPC;
	s->engine.authority = &s->authority;
	s->engine.io.opaque = &s->disk;
	s->engine.io.write_extent = memory_write;
	s->engine.io.read_blocks = memory_read;
	s->engine.write_scratch = s->write_scratch;
	s->engine.read_scratch = s->read_scratch;
	s->alloc_bytes = bytes +
		(uint64_t)LOGICAL_PAGES * sizeof(*s->maps) +
		(uint64_t)blocks * (sizeof(*s->live) + sizeof(*s->classes)) +
		2U * SV3_MAX_EXTENT_BYTES + sizeof(s->engine) +
		sizeof(s->authority);
	return 0;
}

static void state_destroy(struct run_state *s)
{
	free(s->disk.bytes);
	free(s->maps);
	free(s->live);
	free(s->classes);
	free(s->write_scratch);
	free(s->read_scratch);
	memset(s, 0, sizeof(*s));
}

static int dataset_alloc(struct dataset *d, sv3_u32 count, int raw)
{
	memset(d, 0, sizeof(*d));
	d->count = count;
	d->pages = calloc(count, sizeof(*d->pages));
	d->payload_storage = calloc(count, SV3_MAX_COMPRESSED);
	d->lengths = calloc(count, sizeof(*d->lengths));
	if (raw)
		d->raw_pages = calloc(count, LZ4_PAGE);
	if (!d->pages || !d->payload_storage || !d->lengths ||
	    (raw && !d->raw_pages))
		return -ENOMEM;
	d->has_raw_pages = raw;
	return 0;
}

static void dataset_destroy(struct dataset *d)
{
	free(d->pages);
	free(d->payload_storage);
	free(d->lengths);
	free(d->raw_pages);
	memset(d, 0, sizeof(*d));
}

static sv3_u16 synthetic_length(const char *name, sv3_u32 op)
{
	static const sv3_u16 wide[] = {600, 1048, 1600, 2072, 2200, 3500};
	if (!strcmp(name, "uniform2072") || !strcmp(name, "control2072"))
		return 2072;
	if (!strcmp(name, "uniform1048"))
		return 1048;
	if (!strcmp(name, "clustered"))
		return op % 16U < 8U ? 2200 : 1600;
	if (!strcmp(name, "alternating"))
		return op % 2U ? 1600 : 2200;
	if (!strcmp(name, "wide"))
		return wide[op % (sizeof(wide) / sizeof(wide[0]))];
	if (!strcmp(name, "hotcold"))
		return op % 5U ? 1048 : 2200;
	return 0;
}

static int build_synthetic(struct dataset *d, const char *name,
			   sv3_u32 count, sv3_u32 seed)
{
	sv3_u32 state = seed ? seed : 1U, op;
	int rc = dataset_alloc(d, count, 0);
	if (rc)
		return rc;
	for (op = 0; op < count; ++op) {
		sv3_u16 len = synthetic_length(name, op);
		sv3_u8 *payload = d->payload_storage +
			(size_t)op * SV3_MAX_COMPRESSED;
		sv3_u32 local = seed ^ (0xa511e9b3U + op * 0x9e3779b9U);
		sv3_u32 i;
		if (!strcmp(name, "hotcold")) {
			sv3_u32 choice = rng_next(&state) % 10U;
			d->pages[op].logical_page = choice < 8U ?
				rng_next(&state) % 16U :
				16U + rng_next(&state) % (LOGICAL_PAGES - 16U);
		} else {
			d->pages[op].logical_page = op % LOGICAL_PAGES;
		}
		d->pages[op].payload = payload;
		d->pages[op].length = len;
		d->lengths[op] = len;
		for (i = 0; i < len; ++i)
			payload[i] = (sv3_u8)rng_next(&local);
	}
	return 0;
}

/* Source-faithful V2.2 ordered4 container geometry: 8B header, 8B record. */
static int ordered4_blocks(const struct sv3_compressed_page *pages,
			   sv3_u8 count)
{
	unsigned int blocks = 0, records = 0, payload_start = SV3_BLOCK_BYTES;
	sv3_u8 i;
	for (i = 0; i < count; ++i) {
		unsigned int len = pages[i].length;
		unsigned int metadata_end;
		if (!records) {
			blocks++;
			payload_start = SV3_BLOCK_BYTES;
		}
		metadata_end = 8U + (records + 1U) * 8U;
		if (len > payload_start || payload_start - len < metadata_end) {
			records = 0;
			blocks++;
			payload_start = SV3_BLOCK_BYTES;
			metadata_end = 16U;
		}
		if (len > payload_start || payload_start - len < metadata_end)
			return -E2BIG;
		payload_start -= len;
		records++;
	}
	return (int)blocks;
}

static int compare_u64(const void *a, const void *b)
{
	uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
	return x < y ? -1 : x > y ? 1 : 0;
}

static int compare_u16(const void *a, const void *b)
{
	sv3_u16 x = *(const sv3_u16 *)a, y = *(const sv3_u16 *)b;
	return x < y ? -1 : x > y ? 1 : 0;
}

static uint64_t percentile(const uint64_t *values, size_t count,
			   unsigned int percent)
{
	uint64_t *copy, result;
	size_t rank;
	if (!count)
		return 0;
	copy = malloc(count * sizeof(*copy));
	if (!copy)
		return 0;
	memcpy(copy, values, count * sizeof(*copy));
	qsort(copy, count, sizeof(*copy), compare_u64);
	rank = ((size_t)percent * count + 99U) / 100U;
	if (!rank)
		rank = 1;
	if (rank > count)
		rank = count;
	result = copy[rank - 1U];
	free(copy);
	return result;
}

static int dump_input(const char *dir, const char *name, sv3_u32 window,
		      sv3_u32 seed, const struct dataset *d)
{
	char path[1024];
	FILE *f;
	sv3_u32 i;
	if (!dir)
		return 0;
	if (snprintf(path, sizeof(path), "%s/%s-window-%u-seed-%u.input",
		     dir, name, window, seed) >= (int)sizeof(path))
		return -ENAMETOOLONG;
	f = fopen(path, "wb");
	if (!f)
		return -errno;
	for (i = 0; i < d->count; ++i) {
		sv3_u32 page = d->pages[i].logical_page;
		sv3_u16 length = d->pages[i].length;
		if (fwrite(&page, sizeof(page), 1, f) != 1 ||
		    fwrite(&length, sizeof(length), 1, f) != 1 ||
		    fwrite(d->pages[i].payload, length, 1, f) != 1) {
			fclose(f);
			return -EIO;
		}
	}
	return fclose(f) ? -EIO : 0;
}

static int run_dataset(const char *name, sv3_u32 window, sv3_u32 seed,
		       unsigned int repetition, const char *artifact_dir,
		       const struct dataset *d, const int *verify_lz4)
{
	struct run_state s;
	struct metrics m = {0};
	sv3_u32 *last = NULL, start, op, read_count = 0;
	uint64_t *write_samples = NULL, *read_samples = NULL;
	int rc;
	rc = state_init(&s, d->count);
	if (rc)
		return rc;
	write_samples = calloc(d->count / window + 1U, sizeof(*write_samples));
	read_samples = calloc(MAX_READS, sizeof(*read_samples));
	last = malloc(LOGICAL_PAGES * sizeof(*last));
	if (!write_samples || !read_samples || !last) {
		rc = -ENOMEM;
		goto out;
	}
	for (op = 0; op < LOGICAL_PAGES; ++op)
		last[op] = UINT32_MAX;
	for (op = 0; op < d->count; ++op) {
		last[d->pages[op].logical_page] = op;
		m.logical_bytes += 4096U;
		m.payload_bytes += d->pages[op].length;
	}
	for (start = 0; start < d->count; start += window) {
		sv3_u8 count = (sv3_u8)((d->count - start) < window ?
					d->count - start : window);
		sv3_u8 plan_class[SV3_MAX_RECORDS], takes[SV3_MAX_RECORDS];
		sv3_u8 extent_count = 0, committed = 0, i;
		uint64_t wall, cpu;
		int old_blocks;
		wall = now_ns(CLOCK_MONOTONIC_RAW);
		cpu = now_ns(CLOCK_THREAD_CPUTIME_ID);
		rc = sv3_engine_plan(d->pages + start, count, plan_class, takes,
				     &extent_count);
		m.plan_wall_ns += now_ns(CLOCK_MONOTONIC_RAW) - wall;
		m.plan_cpu_ns += now_ns(CLOCK_THREAD_CPUTIME_ID) - cpu;
		if (rc)
			goto out;
		for (i = 0; i < extent_count; ++i) {
			int ci = class_index(plan_class[i]);
			if (ci < 0) {
				rc = -EUCLEAN;
				goto out;
			}
			m.planned_classes[ci]++;
		}
		old_blocks = ordered4_blocks(d->pages + start, count);
		if (old_blocks < 0) {
			rc = old_blocks;
			goto out;
		}
		m.old_ordered_blocks += old_blocks;
		wall = now_ns(CLOCK_MONOTONIC_RAW);
		cpu = now_ns(CLOCK_THREAD_CPUTIME_ID);
		rc = sv3_engine_write_window(&s.engine, d->pages + start, count,
					     &committed);
		m.write_wall_ns += now_ns(CLOCK_MONOTONIC_RAW) - wall;
		m.write_cpu_ns += now_ns(CLOCK_THREAD_CPUTIME_ID) - cpu;
		write_samples[m.write_latency_count++] =
			now_ns(CLOCK_MONOTONIC_RAW) - wall;
		m.committed += committed;
		if (rc || committed != count) {
			m.error = rc ? rc : -EIO;
			goto emit;
		}
	}
	for (op = 0; op < LOGICAL_PAGES; ++op) {
		sv3_u8 output[SV3_MAX_COMPRESSED];
		sv3_u16 length = 0;
		uint64_t wall, cpu;
		sv3_u32 expected;
		if (last[op] == UINT32_MAX)
			continue;
		expected = last[op];
		wall = now_ns(CLOCK_MONOTONIC_RAW);
		cpu = now_ns(CLOCK_THREAD_CPUTIME_ID);
		rc = sv3_engine_read_page(&s.engine, op, output, sizeof(output),
					  &length);
		m.read_wall_ns += now_ns(CLOCK_MONOTONIC_RAW) - wall;
		m.read_cpu_ns += now_ns(CLOCK_THREAD_CPUTIME_ID) - cpu;
		read_samples[read_count++] = now_ns(CLOCK_MONOTONIC_RAW) - wall;
		if (rc || length != d->pages[expected].length ||
		    memcmp(output, d->pages[expected].payload, length)) {
			m.error = rc ? rc : -EBADMSG;
			goto emit;
		}
		if (verify_lz4 && verify_lz4[expected]) {
			sv3_u8 recovered[LZ4_PAGE];
			int decoded = LZ4_decompress_safe((const char *)output,
				(char *)recovered, length, LZ4_PAGE);
			if (decoded != LZ4_PAGE || !d->raw_pages ||
			    memcmp(recovered, d->raw_pages +
				   (size_t)expected * LZ4_PAGE, LZ4_PAGE)) {
				m.error = -EBADMSG;
				goto emit;
			}
		}
	}
emit:
	{
		uint64_t v3_bytes = (uint64_t)s.disk.write_blocks *
			SV3_BLOCK_BYTES;
		uint64_t old_bytes = (uint64_t)m.old_ordered_blocks *
			SV3_BLOCK_BYTES;
		int correct = !m.error && read_count &&
			s.disk.read_blocks == s.engine.physical_read_blocks;
		printf("{\"kind\":\"engine\",\"workload\":\"%s\","
		       "\"window\":%u,\"repetition\":%u,\"seed\":%u,"
		       "\"records\":%u,\"read_pages\":%u,"
		       "\"logical_bytes\":%u,\"payload_bytes\":%u,"
		       "\"ordered4_model_blocks\":%u,"
		       "\"ordered4_model_bytes\":%" PRIu64 ","
		       "\"v3_written_blocks\":%u,\"v3_written_bytes\":%" PRIu64 ","
		       "\"v3_logical_write_ratio\":%.6f,"
		       "\"modeled_ordered_over_v3\":%.6f,"
		       "\"planned_4k_extents\":%u,\"planned_8k_extents\":%u,"
		       "\"planned_16k_extents\":%u,"
		       "\"actual_4k_extents\":%u,\"actual_8k_extents\":%u,"
		       "\"actual_16k_extents\":%u,"
		       "\"metadata_padding_bytes\":%" PRIu64 ","
		       "\"physical_read_blocks\":%u,"
		       "\"read_blocks_per_page\":%.6f,"
		       "\"plan_wall_ns\":%" PRIu64 ",\"plan_cpu_ns\":%" PRIu64 ","
		       "\"write_wall_ns\":%" PRIu64 ",\"write_cpu_ns\":%" PRIu64 ","
		       "\"lower_callback_wall_ns\":%" PRIu64 ","
		       "\"read_wall_ns\":%" PRIu64 ",\"read_cpu_ns\":%" PRIu64 ","
		       "\"read_p50_ns\":%" PRIu64 ",\"read_p95_ns\":%" PRIu64 ","
		       "\"read_p99_ns\":%" PRIu64 ",\"read_max_ns\":%" PRIu64 ","
		       "\"write_window_p50_ns\":%" PRIu64 ","
		       "\"write_window_p95_ns\":%" PRIu64 ","
		       "\"write_window_p99_ns\":%" PRIu64 ","
		       "\"write_window_max_ns\":%" PRIu64 ","
		       "\"submitted_blocks\":%u,\"completed_blocks\":%u,"
		       "\"reserve_blocks\":%u,\"next_block\":%u,"
		       "\"abandoned_blocks\":%u,\"alignment_gap_blocks\":%u,"
		       "\"peak_allocated_bytes\":%" PRIu64 ","
		       "\"correct\":%s,\"error\":%d}\n",
		       name, window, repetition, seed, d->count, read_count,
		       m.logical_bytes, m.payload_bytes, m.old_ordered_blocks,
		       old_bytes, s.disk.write_blocks, v3_bytes,
		       v3_bytes ? (double)m.logical_bytes / v3_bytes : 0.0,
		       v3_bytes ? (double)old_bytes / v3_bytes : 0.0,
		       m.planned_classes[0], m.planned_classes[1],
		       m.planned_classes[2], s.disk.class_extents[0],
		       s.disk.class_extents[1], s.disk.class_extents[2],
		       v3_bytes >= m.payload_bytes ? v3_bytes - m.payload_bytes : 0,
		       s.engine.physical_read_blocks,
		       read_count ? (double)s.engine.physical_read_blocks /
				read_count : 0.0,
		       m.plan_wall_ns, m.plan_cpu_ns, m.write_wall_ns, m.write_cpu_ns,
		       s.disk.callback_wall_ns, m.read_wall_ns, m.read_cpu_ns,
		       percentile(read_samples, read_count, 50),
		       percentile(read_samples, read_count, 95),
		       percentile(read_samples, read_count, 99),
		       percentile(read_samples, read_count, 100),
		       percentile(write_samples, m.write_latency_count, 50),
		       percentile(write_samples, m.write_latency_count, 95),
		       percentile(write_samples, m.write_latency_count, 99),
		       percentile(write_samples, m.write_latency_count, 100),
		       s.engine.submitted_blocks, s.engine.completed_blocks,
		       s.authority.reserve_blocks, s.authority.next_block,
		       s.authority.abandoned_blocks,
		       s.authority.next_block - s.authority.committed_blocks -
				s.authority.abandoned_blocks,
		       s.alloc_bytes + (uint64_t)d->count *
				(SV3_MAX_COMPRESSED + sizeof(*d->pages) +
				 sizeof(*d->lengths)) +
				(d->raw_pages ? (uint64_t)d->count * LZ4_PAGE : 0) +
				(uint64_t)LOGICAL_PAGES * sizeof(*last) +
				(uint64_t)(d->count / window + 1U + MAX_READS) *
				sizeof(uint64_t) +
				(uint64_t)(d->count / window + 1U > MAX_READS ?
					d->count / window + 1U : MAX_READS) *
				sizeof(uint64_t),
		       correct ? "true" : "false", m.error);
	}
	if (!m.error) {
		rc = dump_input(artifact_dir, name, window, seed, d);
		if (rc)
			goto out;
	}
	rc = m.error;
out:
	free(last);
	free(write_samples);
	free(read_samples);
	state_destroy(&s);
	return rc;
}

static int run_synthetic(const char *filter, int selected_window,
			 unsigned int reps, unsigned int warmups,
			 sv3_u32 seed, const char *artifact_dir)
{
	static const char *const names[] = {
		"control2072", "uniform2072", "uniform1048", "clustered",
		"alternating", "wide", "hotcold"
	};
	static const sv3_u32 windows[] = {8, 16, 32, 64};
	size_t si, wi;
	unsigned int warmup, rep;
	for (si = 0; si < sizeof(names) / sizeof(names[0]); ++si) {
		if (filter && strcmp(filter, names[si]))
			continue;
		for (wi = 0; wi < sizeof(windows) / sizeof(windows[0]); ++wi) {
			sv3_u32 window = windows[wi];
			sv3_u32 operations;
			struct dataset data;
			int rc;
			if (selected_window && selected_window != (int)window)
				continue;
			operations = !strcmp(names[si], "control2072") ? 16U :
				(!strcmp(names[si], "hotcold") ? 3072U : window * 8U);
			rc = build_synthetic(&data, names[si], operations, seed);
			if (rc)
				return rc;
			for (warmup = 0; warmup < warmups; ++warmup) {
				rc = run_dataset(names[si], window, seed, 0,
						 artifact_dir, &data, NULL);
				if (rc)
					break;
			}
			for (rep = 1; !rc && rep <= reps; ++rep)
				rc = run_dataset(names[si], window, seed, rep,
						 artifact_dir, &data, NULL);
			dataset_destroy(&data);
			if (rc)
				return rc;
		}
	}
	return 0;
}

static void make_raw_page(sv3_u8 *page, size_t prefix, sv3_u32 seed)
{
	sv3_u32 state = seed ? seed : 1U;
	size_t i;
	for (i = 0; i < LZ4_PAGE; ++i)
		page[i] = i < prefix ? (sv3_u8)rng_next(&state) : 0;
}

static int compress_prefix(sv3_u8 *page, size_t prefix, sv3_u32 seed,
			   sv3_u8 *output, int capacity)
{
	make_raw_page(page, prefix, seed);
	return LZ4_compress_fast((const char *)page, (char *)output, LZ4_PAGE,
				 capacity, 1);
}

static int make_compressed_target(sv3_u8 *page, sv3_u8 *compressed,
				  sv3_u16 *length, unsigned int target,
				  sv3_u32 seed)
{
	sv3_u8 trial[LZ4_COMPRESSBOUND(LZ4_PAGE)];
	size_t low = 0, high = LZ4_PAGE, best_prefix = 0;
	unsigned int best_diff = UINT32_MAX;
	int best_length = 0, iteration;
	for (iteration = 0; iteration < 16; ++iteration) {
		size_t middle = low + (high - low) / 2U;
		int result = compress_prefix(page, middle, seed, trial, sizeof(trial));
		unsigned int diff = result > 0 ?
			(unsigned int)abs(result - (int)target) : UINT32_MAX;
		if (diff < best_diff) {
			best_diff = diff;
			best_prefix = middle;
			best_length = result;
		}
		if (result < (int)target)
			low = middle + 1U;
		else if (middle)
			high = middle - 1U;
		else
			break;
	}
	{
		size_t from = best_prefix > 96U ? best_prefix - 96U : 0;
		size_t to = best_prefix + 96U < LZ4_PAGE ?
			best_prefix + 96U : LZ4_PAGE;
		size_t prefix;
		for (prefix = from; prefix <= to; ++prefix) {
			int result = compress_prefix(page, prefix, seed, trial,
						     sizeof(trial));
			unsigned int diff = result > 0 ?
				(unsigned int)abs(result - (int)target) :
				UINT32_MAX;
			if (diff < best_diff) {
				best_diff = diff;
				best_prefix = prefix;
				best_length = result;
			}
		}
	}
	if (best_length <= 0 || (unsigned int)best_length > SV3_MAX_COMPRESSED)
		return -E2BIG;
	best_length = compress_prefix(page, best_prefix, seed, compressed,
				      SV3_MAX_COMPRESSED);
	if (best_length <= 0 || (unsigned int)best_length > SV3_MAX_COMPRESSED)
		return -E2BIG;
	*length = (sv3_u16)best_length;
	return 0;
}

static int write_lz4_artifacts(const char *dir, const char *name,
			       const struct dataset *d)
{
	char path[1024];
	FILE *f;
	sv3_u32 i;
	if (!dir)
		return 0;
	if (snprintf(path, sizeof(path), "%s/%s-raw-pages.bin", dir, name) >=
	    (int)sizeof(path))
		return -ENAMETOOLONG;
	f = fopen(path, "wb");
	if (!f)
		return -errno;
	for (i = 0; i < d->count; ++i)
		if (fwrite(d->raw_pages + (size_t)i * LZ4_PAGE,
			   LZ4_PAGE, 1, f) != 1) {
			fclose(f);
			return -EIO;
		}
	if (fclose(f))
		return -EIO;
	if (snprintf(path, sizeof(path), "%s/%s-lz4-blocks.bin", dir, name) >=
	    (int)sizeof(path))
		return -ENAMETOOLONG;
	f = fopen(path, "wb");
	if (!f)
		return -errno;
	for (i = 0; i < d->count; ++i)
		if (fwrite(&d->lengths[i], sizeof(d->lengths[i]), 1, f) != 1 ||
		    fwrite(d->pages[i].payload, d->lengths[i], 1, f) != 1) {
			fclose(f);
			return -EIO;
		}
	return fclose(f) ? -EIO : 0;
}

static int run_lz4_fixture(const char *name, const unsigned int *targets,
			   sv3_u32 count, sv3_u32 seed, unsigned int reps,
			   unsigned int warmups, const char *artifact_dir)
{
	struct dataset d;
	int *verify = NULL;
	sv3_u16 sorted[64], minimum = UINT16_MAX, maximum = 0;
	uint64_t sum = 0;
	sv3_u32 i;
	unsigned int warmup, rep;
	int rc = dataset_alloc(&d, count, 1);
	if (rc)
		return rc;
	verify = calloc(count, sizeof(*verify));
	if (!verify) {
		dataset_destroy(&d);
		return -ENOMEM;
	}
	for (i = 0; i < count; ++i) {
		sv3_u8 *raw = d.raw_pages + (size_t)i * LZ4_PAGE;
		sv3_u8 *compressed = d.payload_storage +
			(size_t)i * SV3_MAX_COMPRESSED;
		sv3_u8 recovered[LZ4_PAGE];
		sv3_u32 page_seed = seed ^ (i * 0x9e3779b9U + 1U);
		sv3_u16 length;
		rc = make_compressed_target(raw, compressed, &length, targets[i],
					    page_seed);
		if (rc)
			goto out;
		if (LZ4_decompress_safe((const char *)compressed,
				(char *)recovered, length, LZ4_PAGE) != LZ4_PAGE ||
		    memcmp(raw, recovered, LZ4_PAGE)) {
			rc = -EBADMSG;
			goto out;
		}
		d.pages[i].logical_page = i;
		d.pages[i].payload = compressed;
		d.pages[i].length = length;
		d.lengths[i] = length;
		verify[i] = 1;
		sorted[i] = length;
		sum += length;
		if (length < minimum)
			minimum = length;
		if (length > maximum)
			maximum = length;
	}
	qsort(sorted, count, sizeof(sorted[0]), compare_u16);
	rc = write_lz4_artifacts(artifact_dir, name, &d);
	if (rc)
		goto out;
	printf("{\"kind\":\"lz4_distribution\",\"workload\":\"%s\","
	       "\"seed\":%u,\"records\":%u,\"min\":%u,\"median\":%u,"
	       "\"mean\":%.3f,\"p95\":%u,\"max\":%u,\"raw_fallbacks\":0,"
	       "\"lengths\":[", name, seed, count, minimum, sorted[count / 2U],
	       (double)sum / count,
	       sorted[((count * 95U + 99U) / 100U) - 1U], maximum);
	for (i = 0; i < count; ++i)
		printf("%s%u", i ? "," : "", d.lengths[i]);
	printf("]}\n");
	for (warmup = 0; warmup < warmups; ++warmup) {
		rc = run_dataset(name, count, seed, 0, artifact_dir, &d, verify);
		if (rc)
			goto out;
	}
	for (rep = 1; rep <= reps; ++rep) {
		rc = run_dataset(name, count, seed, rep, artifact_dir, &d, verify);
		if (rc)
			goto out;
	}
out:
	free(verify);
	dataset_destroy(&d);
	return rc;
}

static int run_lz4(unsigned int reps, unsigned int warmups, sv3_u32 seed,
		   const char *artifact_dir)
{
	unsigned int uniform2072[16], uniform1048[16], clustered[16];
	unsigned int alternating[16], wide[16];
	static const unsigned int wide_classes[] =
		{600, 1048, 1600, 2072, 2200, 3500};
	sv3_u32 i;
	for (i = 0; i < 16; ++i) {
		uniform2072[i] = 2072;
		uniform1048[i] = 1048;
		clustered[i] = i < 8 ? 2200 : 1600;
		alternating[i] = i % 2U ? 1600 : 2200;
		wide[i] = wide_classes[i % 6U];
	}
#define RUN_LZ4(n, t) do { \
	int r = run_lz4_fixture((n), (t), 16, seed, reps, warmups, artifact_dir); \
	if (r) return r; \
} while (0)
	RUN_LZ4("lz4_uniform2072", uniform2072);
	RUN_LZ4("lz4_uniform1048", uniform1048);
	RUN_LZ4("lz4_clustered", clustered);
	RUN_LZ4("lz4_alternating", alternating);
	RUN_LZ4("lz4_wide", wide);
#undef RUN_LZ4
	return 0;
}

static int raw_fallback(sv3_u32 seed, const char *artifact_dir)
{
	sv3_u8 raw[LZ4_PAGE], output[SV3_MAX_COMPRESSED];
	sv3_u8 classes[SV3_MAX_RECORDS], takes[SV3_MAX_RECORDS], groups;
	struct sv3_compressed_page page;
	sv3_u32 state = seed ? seed : 1U;
	sv3_u32 i;
	int compressed, rc;
	for (i = 0; i < LZ4_PAGE; ++i)
		raw[i] = (sv3_u8)rng_next(&state);
	compressed = LZ4_compress_fast((const char *)raw, (char *)output,
					       LZ4_PAGE, SV3_MAX_COMPRESSED, 1);
	if (compressed)
		return -EUCLEAN;
	if (artifact_dir) {
		char path[1024];
		FILE *file;
		if (snprintf(path, sizeof(path), "%s/lz4-raw-fallback-page.bin",
			     artifact_dir) >= (int)sizeof(path))
			return -ENAMETOOLONG;
		file = fopen(path, "wb");
		if (!file)
			return -errno;
		int write_error = fwrite(raw, sizeof(raw), 1, file) != 1;
		int close_error = fclose(file) != 0;
		if (write_error || close_error)
			return -EIO;
	}
	page = (struct sv3_compressed_page){
		.logical_page = 0, .payload = raw, .length = LZ4_PAGE
	};
	rc = sv3_engine_plan(&page, 1, classes, takes, &groups);
	printf("{\"kind\":\"lz4_raw_fallback\",\"seed\":%u,"
	       "\"input_bytes\":4096,\"compressed_with_3568_cap\":%d,"
	       "\"engine_plan_rc\":%d,\"expected_unsupported\":%s}\n",
	       seed, compressed, rc, rc == -EOPNOTSUPP ? "true" : "false");
	return rc == -EOPNOTSUPP ? 0 : -EUCLEAN;
}

static int run_faults(void)
{
	static const struct { const char *name; int mode; } cases[] = {
		{"fail_before_write", 1}, {"partial_lower_extent", 2},
		{"overreported_completion", 3},
		{"post_write_payload_corruption", 4}
	};
	size_t i;
	for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
		struct dataset d;
		struct run_state s;
		sv3_u8 committed = 0;
		int rc = build_synthetic(&d, "uniform2072",
					 cases[i].mode == 4 ? 3 : 3, 12345);
		if (rc)
			return rc;
		rc = state_init(&s, d.count);
		if (rc) {
			dataset_destroy(&d);
			return rc;
		}
		s.disk.fail_write_call = 1;
		s.disk.fail_mode = cases[i].mode;
		rc = sv3_engine_write_window(&s.engine, d.pages, d.count,
					     &committed);
		if (cases[i].mode == 4) {
			sv3_u8 output[SV3_MAX_COMPRESSED];
			sv3_u16 length = 0;
			int read_rc = sv3_engine_read_page(&s.engine, 0, output,
						       sizeof(output), &length);
			printf("{\"kind\":\"fault\",\"fault\":\"%s\","
			       "\"engine_rc\":%d,\"committed_pages\":%u,"
			       "\"actual_written_blocks\":%u,"
			       "\"validated_completed_blocks\":%u,"
			       "\"published_maps\":%u,\"read_rc\":%d,"
			       "\"abandoned_blocks\":%u}\n",
			       cases[i].name, rc, committed, s.disk.write_blocks,
			       s.engine.completed_blocks,
			       s.maps[0].valid + s.maps[1].valid + s.maps[2].valid,
			       read_rc, s.authority.abandoned_blocks);
			if (rc || committed != 3 || read_rc != -EBADMSG)
				rc = -EUCLEAN;
			else
				rc = 0;
		} else {
			unsigned int published = s.maps[0].valid + s.maps[1].valid +
				s.maps[2].valid;
			printf("{\"kind\":\"fault\",\"fault\":\"%s\","
			       "\"engine_rc\":%d,\"committed_pages\":%u,"
			       "\"actual_written_blocks\":%u,"
			       "\"validated_completed_blocks\":%u,"
			       "\"published_maps\":%u,\"read_rc\":null,"
			       "\"abandoned_blocks\":%u}\n",
			       cases[i].name, rc, committed, s.disk.write_blocks,
			       s.engine.completed_blocks, published,
			       s.authority.abandoned_blocks);
			if (rc >= 0 || committed || published || s.authority.in_flight)
				rc = -EUCLEAN;
			else
				rc = 0;
		}
		state_destroy(&s);
		dataset_destroy(&d);
		if (rc)
			return rc;
	}
	return 0;
}

static int run_randomized(unsigned int operations, sv3_u32 seed)
{
	struct dataset d;
	struct run_state s;
	sv3_u32 state = seed ? seed : 1U, i, position = 0;
	int rc = build_synthetic(&d, "wide", operations, seed);
	if (rc)
		return rc;
	for (i = 0; i < operations; ++i) {
		d.pages[i].logical_page = rng_next(&state) % LOGICAL_PAGES;
		if (i && i % 3U == 0)
			d.pages[i].logical_page = d.pages[i - 1U].logical_page;
	}
	rc = state_init(&s, operations);
	if (rc) {
		dataset_destroy(&d);
		return rc;
	}
	while (position < operations) {
		sv3_u8 count = (sv3_u8)(1U + rng_next(&state) % 64U);
		sv3_u8 committed = 0;
		if (count > operations - position)
			count = (sv3_u8)(operations - position);
		rc = sv3_engine_write_window(&s.engine, d.pages + position,
					     count, &committed);
		if (rc || committed != count)
			goto out_random;
		position += count;
	}
	for (i = 0; i < LOGICAL_PAGES; ++i) {
		sv3_u32 j, last = UINT32_MAX;
		sv3_u8 output[SV3_MAX_COMPRESSED];
		sv3_u16 length = 0;
		for (j = 0; j < operations; ++j)
			if (d.pages[j].logical_page == i)
				last = j;
		if (last == UINT32_MAX)
			continue;
		rc = sv3_engine_read_page(&s.engine, i, output, sizeof(output),
					  &length);
		if (rc || length != d.pages[last].length ||
		    memcmp(output, d.pages[last].payload, length)) {
			rc = -EBADMSG;
			goto out_random;
		}
	}
	printf("{\"kind\":\"randomized_oracle\",\"seed\":%u,"
	       "\"operations\":%u,\"window_sizes\":\"random-1-to-64\","
	       "\"repeated_slot_every\":3,\"verified_latest_pages\":true,"
	       "\"error\":0}\n", seed, operations);
out_random:
	state_destroy(&s);
	dataset_destroy(&d);
	return rc;
}

static int parse_number(const char *s, int *out)
{
	char *end = NULL;
	long value = strtol(s, &end, 10);
	if (!s[0] || !end || *end || value < 0 || value > INT32_MAX)
		return -EINVAL;
	*out = (int)value;
	return 0;
}

int main(int argc, char **argv)
{
	const char *mode = "synthetic", *scenario = NULL, *artifact_dir = NULL;
	unsigned int reps = 10, warmups = 2;
	sv3_u32 seed = 12345;
	int window = 0, cases = 2048, i, rc;
	for (i = 1; i < argc; ++i) {
		if (!strcmp(argv[i], "--synthetic"))
			mode = "synthetic";
		else if (!strcmp(argv[i], "--lz4"))
			mode = "lz4";
		else if (!strcmp(argv[i], "--faults"))
			mode = "faults";
		else if (!strcmp(argv[i], "--randomized"))
			mode = "randomized";
		else if (!strcmp(argv[i], "--scenario") && i + 1 < argc)
			scenario = argv[++i];
		else if (!strcmp(argv[i], "--artifact-dir") && i + 1 < argc)
			artifact_dir = argv[++i];
		else if (!strcmp(argv[i], "--window") && i + 1 < argc) {
			if (parse_number(argv[++i], &window))
				return 2;
		} else if (!strcmp(argv[i], "--reps") && i + 1 < argc) {
			int v;
			if (parse_number(argv[++i], &v) || v < 1 || v > 100)
				return 2;
			reps = (unsigned int)v;
		} else if (!strcmp(argv[i], "--warmups") && i + 1 < argc) {
			int v;
			if (parse_number(argv[++i], &v) || v > 100)
				return 2;
			warmups = (unsigned int)v;
		} else if (!strcmp(argv[i], "--seed") && i + 1 < argc) {
			int v;
			if (parse_number(argv[++i], &v))
				return 2;
			seed = (sv3_u32)v;
		} else if (!strcmp(argv[i], "--cases") && i + 1 < argc) {
			if (parse_number(argv[++i], &cases) || cases < 1 ||
			    cases > (int)MAX_OPS)
				return 2;
		} else {
			fprintf(stderr, "unknown/incomplete option: %s\n", argv[i]);
			return 2;
		}
	}
	if (window && window != 8 && window != 16 && window != 32 && window != 64)
		return 2;
	if (!strcmp(mode, "synthetic"))
		rc = run_synthetic(scenario, window, reps, warmups, seed,
				   artifact_dir);
	else if (!strcmp(mode, "lz4"))
		rc = run_lz4(reps, warmups, seed, artifact_dir);
	else if (!strcmp(mode, "faults"))
		rc = run_faults();
	else
		rc = run_randomized((unsigned int)cases, seed);
	if (!rc && !strcmp(mode, "lz4"))
		rc = raw_fallback(seed, artifact_dir);
	if (rc) {
		fprintf(stderr, "extent-v3-bench failed: %d\n", rc);
		return 1;
	}
	return 0;
}
