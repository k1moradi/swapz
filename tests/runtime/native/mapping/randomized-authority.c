/* SPDX-License-Identifier: GPL-2.0-only */
/* Deterministic rootless property and failure test for the exact V3 engine C. */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "engine.h"

#define LOGICAL_PAGES 128U
#define PHYSICAL_BLOCKS 4096U
#define ITERATIONS_PER_CAP 100U
/* Four segments: two foreground, two independently claimed GC reserves. */
#define MIXED_PHYSICAL_BLOCKS (4U * SWAPZ_SEGMENT_BLOCKS)
#define MIXED_SEGMENTS 4U
#define MIXED_STEPS 850U
#define MIXED_TRACE_LENGTH 24U
#define MIXED_BATCH_LIMIT 6U
#define CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "FAIL: randomized-authority.c:%d expression=%s\n", \
			__LINE__, \
			#condition); \
		return 1; \
	} \
} while (0)

struct memory_disk {
	swapz_u8 *bytes;
	swapz_u32 write_calls;
	swapz_u32 write_blocks;
	swapz_u32 read_blocks;
	swapz_u32 read_calls;
	swapz_u32 fail_read_on;
	swapz_u32 fail_on;
};

static struct swapz_authority authority;
static struct swapz_map maps[LOGICAL_PAGES];
static swapz_u16 live[PHYSICAL_BLOCKS];
static swapz_u8 classes[PHYSICAL_BLOCKS];
static swapz_u8 extent_sequence_delta[PHYSICAL_BLOCKS];
static swapz_u32 segment_sequence_base[
	PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 write_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 read_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 data_store[SWAPZ_MAX_RECORDS][SWAPZ_MAX_COMPRESSED];
static swapz_u8 output[SWAPZ_MAX_COMPRESSED];
static swapz_u8 reference[LOGICAL_PAGES][SWAPZ_MAX_COMPRESSED];
static swapz_u16 reference_length[LOGICAL_PAGES];
static swapz_u32 reference_generation[LOGICAL_PAGES];
static int reference_valid[LOGICAL_PAGES];
static struct swapz_compressed_page pages[SWAPZ_MAX_RECORDS];
static struct swapz_engine engine;
static struct memory_disk disk;
/* These are fixed-size native-only fixtures; no allocation in the hot loop. */
static swapz_u8 mixed_roles[MIXED_SEGMENTS];
static swapz_u32 mixed_segment_maps[MIXED_SEGMENTS];
static swapz_u32 mixed_program_counts[MIXED_SEGMENTS];
static swapz_u8 mixed_quarantine[MIXED_PHYSICAL_BLOCKS];
static swapz_u8 mixed_payloads[MIXED_BATCH_LIMIT][SWAPZ_BLOCK_BYTES];
/* GC must not alias pending foreground retry inputs. */
static swapz_u8 mixed_relocation_payload[SWAPZ_BLOCK_BYTES];
static swapz_u8 mixed_raw_oracle[LOGICAL_PAGES][SWAPZ_BLOCK_BYTES];
static swapz_u8 mixed_mode[LOGICAL_PAGES]; /* 0=discard, 1=SWZ, 2=RAW, 3=zero */
static swapz_u8 mixed_bulk_scratch[SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES];
static struct swapz_tx mixed_bulk_transactions[SWAPZ_MAX_RECORDS];
static unsigned int mixed_active;
static unsigned int mixed_failed_writes;
static unsigned int mixed_failed_reads;
static unsigned int mixed_completed_rotations;
static unsigned int mixed_gc_write_failures;
static int mixed_failure_reported;
static uint32_t mixed_seed;

struct mixed_trace_entry {
	swapz_u32 step;
	swapz_u32 logical;
	swapz_u32 block;
	int result;
	swapz_u8 count;
	char operation;
};
static struct mixed_trace_entry mixed_trace[MIXED_TRACE_LENGTH];
static unsigned int mixed_trace_count;
static unsigned int mixed_step_number;

static struct mixed_trace_entry *mixed_note(char operation, swapz_u32 logical,
					     swapz_u8 count)
{
	struct mixed_trace_entry *entry =
		&mixed_trace[mixed_trace_count % MIXED_TRACE_LENGTH];

	*entry = (struct mixed_trace_entry) {
		.step = mixed_step_number, .logical = logical,
		.block = authority.next_block, .count = count,
		.operation = operation,
	};
	mixed_trace_count++;
	return entry;
}

static int mixed_failure(const char *reason, unsigned int line)
{
	unsigned int first = mixed_trace_count > 12U ?
		mixed_trace_count - 12U : 0U;

	if (mixed_failure_reported)
		return -EUCLEAN;
	mixed_failure_reported = 1;
	fprintf(stderr, "MIXED_FAIL reason=%s line=%u seed=0x%08x step=%u "
		"open=%u next=%u victim=%u destination=%u\n",
		reason, line, mixed_seed, mixed_step_number,
		authority.open_segment, authority.next_block,
		authority.gc_forbidden_victim, authority.gc_destination);
	for (unsigned int index = first; index < mixed_trace_count; ++index) {
		const struct mixed_trace_entry *entry =
			&mixed_trace[index % MIXED_TRACE_LENGTH];

		fprintf(stderr, "TRACE step=%u op=%c logical=%u count=%u "
			"block=%u result=%d\n", entry->step,
			entry->operation, entry->logical, entry->count,
			entry->block, entry->result);
	}
	return -EUCLEAN;
}

#define MIXED_REQUIRE(condition, reason) do { \
	if (!(condition)) \
		return mixed_failure(reason, __LINE__); \
} while (0)

static uint32_t random_state = 0x0d3a5eedU;
static uint32_t transition_random_state = 0xa17e4c39U;

static uint32_t next_random(void)
{
	random_state ^= random_state << 13;
	random_state ^= random_state >> 17;
	random_state ^= random_state << 5;
	return random_state;
}

static uint32_t next_transition_random(void)
{
	transition_random_state ^= transition_random_state << 13;
	transition_random_state ^= transition_random_state >> 17;
	transition_random_state ^= transition_random_state << 5;
	return transition_random_state;
}

static int lower_write(void *opaque, swapz_u32 start, swapz_u8 blocks,
		       const swapz_u8 *source, swapz_u8 *completed)
{
	struct memory_disk *memory = opaque;
	const swapz_u32 physical_limit =
		mixed_active ? MIXED_PHYSICAL_BLOCKS : PHYSICAL_BLOCKS;
	swapz_u8 written = blocks;

	*completed = 0;
	if (start >= physical_limit || blocks > physical_limit - start)
		return -ERANGE;
	if (mixed_active) {
		for (swapz_u32 block = start; block < start + blocks; ++block)
			if (mixed_quarantine[block])
				return -EUCLEAN;
	}
	memory->write_calls++;
	if (memory->write_calls == memory->fail_on)
		written = blocks > 1 ? 1 : 0;
	if (mixed_active && written != blocks) {
		for (swapz_u32 block = start; block < start + blocks; ++block)
			mixed_quarantine[block] = 1;
		mixed_failed_writes++;
	}
	if (written) {
		memcpy(memory->bytes + (size_t)start * SWAPZ_BLOCK_BYTES, source,
		       (size_t)written * SWAPZ_BLOCK_BYTES);
		memory->write_blocks += written;
		*completed = written;
	}
	return written == blocks ? 0 : -EIO;
}

static int lower_read(void *opaque, swapz_u32 start, swapz_u8 blocks,
		      swapz_u8 *destination)
{
	struct memory_disk *memory = opaque;
	const swapz_u32 physical_limit =
		mixed_active ? MIXED_PHYSICAL_BLOCKS : PHYSICAL_BLOCKS;

	if (start >= physical_limit || blocks > physical_limit - start)
		return -ERANGE;
	memory->read_calls++;
	if (memory->read_calls == memory->fail_read_on) {
		mixed_failed_reads++;
		return -EIO;
	}
	memcpy(destination, memory->bytes + (size_t)start * SWAPZ_BLOCK_BYTES,
	       (size_t)blocks * SWAPZ_BLOCK_BYTES);
	memory->read_blocks += blocks;
	return 0;
}

static int initialize_engine(unsigned read_cap)
{
	memset(reference_length, 0, sizeof(reference_length));
	memset(reference_generation, 0, sizeof(reference_generation));
	memset(reference_valid, 0, sizeof(reference_valid));
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_blocks = 0;
	disk.read_calls = 0;
	disk.fail_read_on = 0;
	disk.fail_on = 0;
	if (swapz_authority_init(&authority, maps, live, classes,
			       LOGICAL_PAGES, PHYSICAL_BLOCKS) ||
	    swapz_enable_extent_sequence_index(
		    &authority, extent_sequence_delta, segment_sequence_base,
		    PHYSICAL_BLOCKS / SWAPZ_SEGMENT_BLOCKS))
		return -1;
	memset(&engine, 0, sizeof(engine));
	engine.authority = &authority;
	engine.io.opaque = &disk;
	engine.io.write_extent = lower_write;
	engine.io.read_blocks = lower_read;
	engine.write_scratch = write_scratch;
	engine.read_scratch = read_scratch;
	engine.max_read_blocks_per_record = (swapz_u8)read_cap;
	return 0;
}

static int validate_page_authority(unsigned logical_page)
{
	const struct swapz_map *map = &maps[logical_page];

	if (map->generation != reference_generation[logical_page] ||
	    !!map->valid != !!reference_valid[logical_page])
		return -1;
	if (!map->valid)
		return 0;
	if (map->raw || !map->extent_blocks ||
	    map->start_block >= PHYSICAL_BLOCKS ||
	    classes[map->start_block] != map->extent_blocks ||
	    !live[map->start_block])
		return -1;
	return 0;
}

static int verify_page(unsigned logical_page)
{
	swapz_u16 output_length = 0;
	int result = swapz_engine_read_page(&engine, logical_page, output,
					    sizeof(output), &output_length);

	if (!reference_valid[logical_page])
		return result == -ESTALE ? 0 : -1;
	if (result || output_length != reference_length[logical_page] ||
	    memcmp(output, reference[logical_page], output_length)) {
		fprintf(stderr,
			"oracle mismatch page=%u result=%d got=%u expected=%u\n",
			logical_page, result, output_length,
			reference_length[logical_page]);
		return -1;
	}
	return 0;
}

static void update_reference(const struct swapz_compressed_page *page)
{
	reference_generation[page->logical_page]++;
	reference_valid[page->logical_page] = 1;
	reference_length[page->logical_page] = page->length;
	memcpy(reference[page->logical_page], page->payload, page->length);
}


/*
 * A model of one serialized production owner. Interleavings are explicit,
 * never concurrent kernel execution. A returned lower error may have written
 * media, but NO uncertain block is reusable until the production authority's
 * dead-segment proof invokes its recycle callback.
 */
static int mixed_recycle(void *opaque, swapz_u32 segment)
{
	swapz_u8 *quarantine = opaque;

	if (segment >= MIXED_SEGMENTS)
		return -ERANGE;
	memset(quarantine + (size_t)segment * SWAPZ_SEGMENT_BLOCKS, 0,
	       SWAPZ_SEGMENT_BLOCKS);
	return 0;
}

static int mixed_write_run(void *opaque, swapz_u32 start, swapz_u16 blocks,
			   const swapz_u8 *source, swapz_u16 *completed)
{
	struct memory_disk *memory = opaque;
	swapz_u16 written = blocks;

	*completed = 0;
	if (!blocks || blocks > SWAPZ_BULK_BLOCKS ||
	    start >= MIXED_PHYSICAL_BLOCKS ||
	    blocks > MIXED_PHYSICAL_BLOCKS - start ||
	    start / SWAPZ_SEGMENT_BLOCKS !=
		    (start + blocks - 1U) / SWAPZ_SEGMENT_BLOCKS)
		return -ERANGE;
	for (swapz_u32 block = start; block < start + blocks; ++block)
		if (mixed_quarantine[block])
			return -EUCLEAN;
	memory->write_calls++;
	if (memory->write_calls == memory->fail_on)
		written = blocks > 1U ? 1U : 0U;
	if (written != blocks) {
		for (swapz_u32 block = start; block < start + blocks; ++block)
			mixed_quarantine[block] = 1;
		mixed_failed_writes++;
	}
	if (written) {
		memcpy(memory->bytes + (size_t)start * SWAPZ_BLOCK_BYTES,
		       source, (size_t)written * SWAPZ_BLOCK_BYTES);
		memory->write_blocks += written;
		*completed = written;
	}
	return written == blocks ? 0 : -EIO;
}

static int mixed_setup(uint32_t seed)
{
	mixed_seed = seed;
	random_state = seed;
	mixed_step_number = 0;
	mixed_trace_count = 0;
	mixed_failed_reads = 0;
	mixed_failed_writes = 0;
	mixed_completed_rotations = 0;
	mixed_gc_write_failures = 0;
	mixed_failure_reported = 0;
	mixed_active = 0;
	memset(mixed_quarantine, 0, sizeof(mixed_quarantine));
	memset(mixed_mode, 0, sizeof(mixed_mode));
	memset(reference_valid, 0, sizeof(reference_valid));
	memset(reference_generation, 0, sizeof(reference_generation));
	memset(reference_length, 0, sizeof(reference_length));
	disk.write_calls = 0;
	disk.write_blocks = 0;
	disk.read_calls = 0;
	disk.read_blocks = 0;
	disk.fail_on = 0;
	disk.fail_read_on = 0;
	MIXED_REQUIRE(swapz_authority_init(&authority, maps, live, classes,
			   LOGICAL_PAGES, MIXED_PHYSICAL_BLOCKS) == 0,
		      "GEOMETRY_INIT");
	MIXED_REQUIRE(swapz_enable_extent_sequence_index(
			   &authority, extent_sequence_delta,
			   segment_sequence_base, MIXED_SEGMENTS) == 0,
		      "SEQUENCE_INDEX");
	authority.reuse_dead_segments = 1;
	MIXED_REQUIRE(swapz_enable_segment_rotation(&authority, mixed_roles,
						   MIXED_SEGMENTS) == 0,
		      "ROTATION_INIT");
	MIXED_REQUIRE(swapz_enable_segment_mapping_counts(
			   &authority, mixed_segment_maps, MIXED_SEGMENTS) == 0,
		      "SEGMENT_COUNTS");
	MIXED_REQUIRE(swapz_enable_segment_program_counts(
			   &authority, mixed_program_counts, MIXED_SEGMENTS) == 0,
		      "PROGRAM_COUNTS");
	authority.dead_segment_recycle = mixed_recycle;
	authority.dead_segment_recycle_opaque = mixed_quarantine;
	memset(&engine, 0, sizeof(engine));
	engine.authority = &authority;
	engine.io.opaque = &disk;
	engine.io.write_extent = lower_write;
	engine.io.write_run = mixed_write_run;
	engine.io.read_blocks = lower_read;
	engine.write_scratch = write_scratch;
	engine.read_scratch = read_scratch;
	engine.bulk_enabled = 1;
	engine.bulk_scratch = mixed_bulk_scratch;
	engine.bulk_txs = mixed_bulk_transactions;
	mixed_active = 1;
	return 0;
}

static void mixed_publish(const struct swapz_compressed_page *page)
{
	const swapz_u32 logical = page->logical_page;

	reference_generation[logical]++;
	reference_valid[logical] = 1;
	reference_length[logical] = page->length;
	mixed_mode[logical] = page->raw ? 2U : 1U;
	if (page->raw)
		memcpy(mixed_raw_oracle[logical], page->payload,
		       SWAPZ_BLOCK_BYTES);
	else
		memcpy(reference[logical], page->payload, page->length);
}

/* Check every map, all extent-start liveness, segment sidecars and every
 * authoritative byte. No probabilistic sampling may hide a lost old value. */
static int mixed_verify_full_map(void)
{
	swapz_u16 expected_live[MIXED_PHYSICAL_BLOCKS] = {0};
	swapz_u8 expected_class[MIXED_PHYSICAL_BLOCKS] = {0};
	swapz_u8 occupied[MIXED_PHYSICAL_BLOCKS] = {0};
	swapz_u32 expected_segment_maps[MIXED_SEGMENTS] = {0};

	swapz_engine_invalidate_read_cache(&engine);
	MIXED_REQUIRE(!authority.in_flight && !authority.batch_pending &&
		      !authority.batch_replaying, "UNACKNOWLEDGED_INFLIGHT");
	for (swapz_u32 logical = 0; logical < LOGICAL_PAGES; ++logical) {
		const struct swapz_map *map = &maps[logical];

		MIXED_REQUIRE(map->generation == reference_generation[logical],
			      "STALE_GENERATION");
		MIXED_REQUIRE(!!map->valid == !!reference_valid[logical],
			      "UNACKNOWLEDGED_PUBLISH");
		if (!map->valid) {
			swapz_u16 length = 0;

			MIXED_REQUIRE(mixed_mode[logical] == 0U ||
				      mixed_mode[logical] == 3U,
				      "FALSE_ZERO_STATE");
			MIXED_REQUIRE(swapz_engine_read_page(&engine, logical, output,
				    sizeof(output), &length) == -ESTALE,
				      "DISCARDED_PAGE_VISIBLE");
			continue;
		}
		MIXED_REQUIRE(map->start_block < MIXED_PHYSICAL_BLOCKS &&
			      (map->extent_blocks == 1U ||
			       map->extent_blocks == 2U ||
			       map->extent_blocks == 4U) &&
			      map->extent_blocks <=
				      MIXED_PHYSICAL_BLOCKS - map->start_block,
			      "MAP_OUT_OF_RANGE");
		MIXED_REQUIRE(map->start_block / SWAPZ_SEGMENT_BLOCKS ==
			      (map->start_block + map->extent_blocks - 1U) /
			      SWAPZ_SEGMENT_BLOCKS, "CROSS_SEGMENT_EXTENT");
		MIXED_REQUIRE(classes[map->start_block] == map->extent_blocks,
			      "EXTENT_CLASS");
		MIXED_REQUIRE(!mixed_quarantine[map->start_block],
			      "FORBIDDEN_EXTENT_REUSE");
		MIXED_REQUIRE((map->raw && mixed_mode[logical] == 2U &&
			       map->extent_blocks == 1U) ||
			      (!map->raw && mixed_mode[logical] == 1U),
			      "FALSE_RAW_OR_ZERO");
		expected_live[map->start_block]++;
		expected_class[map->start_block] = map->extent_blocks;
		expected_segment_maps[map->start_block / SWAPZ_SEGMENT_BLOCKS]++;
		if (!map->raw) {
			swapz_u16 length = 0;

			MIXED_REQUIRE(swapz_engine_read_page(&engine, logical, output,
				    sizeof(output), &length) == 0 &&
				      length == reference_length[logical] &&
				      !memcmp(output, reference[logical], length),
				      "COMPRESSED_BYTES_OR_CRC");
		} else {
			const swapz_u8 *stored = disk.bytes +
				(size_t)map->start_block * SWAPZ_BLOCK_BYTES;

			MIXED_REQUIRE(!memcmp(stored, mixed_raw_oracle[logical],
				      SWAPZ_BLOCK_BYTES) &&
				      swapz_verify_raw(&authority, logical, stored) == 0,
				      "RAW_BYTES_OR_CRC");
		}
	}
	for (swapz_u32 block = 0; block < MIXED_PHYSICAL_BLOCKS; ++block) {
		if (expected_live[block]) {
			for (swapz_u32 offset = 0;
			     offset < expected_class[block]; ++offset) {
				MIXED_REQUIRE(!occupied[block + offset],
					      "OVERLAPPING_LIVE_EXTENTS");
				occupied[block + offset] = 1;
				MIXED_REQUIRE(!mixed_quarantine[block + offset],
					      "FORBIDDEN_EXTENT_REUSE");
			}
		}
		/* Dead extents retain historical class metadata until reclaim. */
		MIXED_REQUIRE(live[block] == expected_live[block] &&
			      (!expected_live[block] ||
			       classes[block] == expected_class[block]) &&
			      (classes[block] == 0U ||
			       classes[block] == 1U ||
			       classes[block] == 2U ||
			       classes[block] == 4U),
			      "FULL_MAP_LIVENESS");
	}
	for (swapz_u32 segment = 0; segment < MIXED_SEGMENTS; ++segment)
		MIXED_REQUIRE(mixed_segment_maps[segment] ==
			      expected_segment_maps[segment],
			      "FALSE_ZERO_SIDECAR");
	return 0;
}

static void mixed_make_payload(swapz_u8 *destination, swapz_u16 length)
{
	for (swapz_u32 byte = 0; byte < length; ++byte)
		destination[byte] = (swapz_u8)next_random();
}

static int mixed_relocate_one(swapz_u32 logical)
{
	struct swapz_compressed_page page;
	struct swapz_map old = maps[logical];
	struct mixed_trace_entry *trace = mixed_note('G', logical, 1);
	swapz_u8 completed = 0;
	swapz_u16 length = 0;
	int error;

	/* Read the old authoritative bytes before allocating a destination. */
	if (old.raw) {
		error = lower_read(&disk, old.start_block, 1, mixed_relocation_payload);
		length = SWAPZ_BLOCK_BYTES;
	} else {
		error = swapz_engine_read_page(&engine, logical, mixed_relocation_payload,
					    SWAPZ_BLOCK_BYTES, &length);
	}
	if (error) {
		trace->result = error;
		return error;
	}
	if (old.raw) {
		struct swapz_tx transaction;
		swapz_u8 written = 0;

		error = swapz_stage(&authority, &logical, 1, 1, &transaction);
		if (error)
			return error;
		error = lower_write(&disk, transaction.start_block, 1,
				    mixed_relocation_payload, &written);
		error = swapz_finish_raw(&authority, &transaction,
					 mixed_relocation_payload, written, error);
		completed = error ? 0U : 1U;
	} else {
		page = (struct swapz_compressed_page) {
			.logical_page = logical, .payload = mixed_relocation_payload,
			.length = length, .encoding = swapz_map_encoding(&old),
		};
		error = swapz_engine_write_window_batched(&engine, &page, 1,
							   &completed);
	}
	trace->result = error;
	if (!error) {
		MIXED_REQUIRE(completed == 1U, "GC_UNACKNOWLEDGED_PUBLISH");
		MIXED_REQUIRE(maps[logical].start_block != old.start_block &&
			      maps[logical].generation == old.generation + 1U,
			      "GC_STALE_GENERATION");
		reference_generation[logical]++;
	} else {
		MIXED_REQUIRE(error == -EIO, "GC_UNEXPECTED_ERROR");
		MIXED_REQUIRE(!completed &&
			      maps[logical].start_block == old.start_block &&
			      maps[logical].generation == old.generation,
			      "GC_FAILED_WRITE_PUBLISHED");
	}
	return error;
}

static int mixed_collect_until_progress(void)
{
	unsigned int attempts;

	for (attempts = 0; attempts < 512U; ++attempts) {
		swapz_u32 victim = authority.gc_forbidden_victim;
		int error;

		mixed_step_number++;
		if (!authority.gc_allocation) {
			swapz_u32 best = SWAPZ_SEGMENT_BLOCKS + 1U;

			victim = MIXED_SEGMENTS;
			for (swapz_u32 segment = 0; segment < MIXED_SEGMENTS;
			     ++segment) {
				if (!mixed_roles[segment] ||
				    segment == authority.open_segment ||
				    !mixed_segment_maps[segment])
					continue;
				if (mixed_segment_maps[segment] < best) {
					best = mixed_segment_maps[segment];
					victim = segment;
				}
			}
			MIXED_REQUIRE(victim < MIXED_SEGMENTS,
				      "CAPACITY_DEADLOCK_NO_VICTIM");
			error = swapz_gc_begin_rotation(&authority, victim);
			MIXED_REQUIRE(!error, "CAPACITY_DEADLOCK_NO_RESERVE");
		}
		MIXED_REQUIRE(authority.gc_allocation &&
			      authority.gc_forbidden_victim == victim &&
			      authority.open_segment == authority.gc_destination &&
			      victim != authority.gc_destination,
			      "RESERVE_OWNERSHIP");
		for (swapz_u32 logical = 0; logical < LOGICAL_PAGES; ++logical) {
			if (!maps[logical].valid ||
			    maps[logical].start_block / SWAPZ_SEGMENT_BLOCKS != victim)
				continue;
			const swapz_u32 writes_before = disk.write_calls;

			/* Guarantee both fault boundaries for every seed, then vary
			 * subsequent transient read/write failures by the PRNG. */
			if (!mixed_failed_reads) {
				swapz_engine_invalidate_read_cache(&engine);
				disk.fail_read_on = disk.read_calls + 1U;
			} else if (!mixed_gc_write_failures) {
				disk.fail_on = disk.write_calls + 1U;
			} else {
				if (next_random() % 19U == 0U)
					disk.fail_read_on = disk.read_calls + 1U;
				if (next_random() % 19U == 0U)
					disk.fail_on = disk.write_calls + 1U;
			}
			error = mixed_relocate_one(logical);
			disk.fail_on = 0;
			disk.fail_read_on = 0;
			MIXED_REQUIRE(!error || error == -EIO,
				      "GC_RELOCATION_FAILED");
			if (error == -EIO && disk.write_calls > writes_before)
				mixed_gc_write_failures++;
			MIXED_REQUIRE(mixed_verify_full_map() == 0,
				      "GC_MAP_CORRUPTION");
			break; /* Deliberately partial: rescan authoritative victim. */
		}
		if (!mixed_segment_maps[victim]) {
			struct mixed_trace_entry *trace = mixed_note('C', victim, 0);

			error = swapz_gc_commit_rotation(&authority, victim);
			trace->result = error;
			MIXED_REQUIRE(!error && !authority.gc_allocation &&
				      !mixed_roles[victim], "GC_COMMIT_DEADLOCK");
			mixed_completed_rotations++;
			MIXED_REQUIRE(mixed_verify_full_map() == 0,
				      "GC_COMMIT_CORRUPTION");
			return 0;
		}
	}
	return mixed_failure("UNBOUNDED_GC_NO_PROGRESS", __LINE__);
}

static int mixed_write_batch(void)
{
	static const swapz_u16 compressed_lengths[] = {
		26U, 257U, 1048U, 2072U, SWAPZ_MAX_COMPRESSED
	};
	struct swapz_compressed_page records[MIXED_BATCH_LIMIT] = {0};
	swapz_u8 logical_order[LOGICAL_PAGES];
	swapz_u8 count = 1U + next_random() % MIXED_BATCH_LIMIT;
	swapz_u8 compressed_count = next_random() % (count + 1U);
	struct mixed_trace_entry *trace;
	swapz_u8 acknowledged = 0;

	for (swapz_u32 logical = 0; logical < LOGICAL_PAGES; ++logical)
		logical_order[logical] = (swapz_u8)logical;
	for (swapz_u32 index = 0; index < count; ++index) {
		swapz_u32 swap_index = index +
			next_random() % (LOGICAL_PAGES - index);
		swapz_u8 temp = logical_order[index];

		logical_order[index] = logical_order[swap_index];
		logical_order[swap_index] = temp;
	}
	for (swapz_u32 index = 0; index < count; ++index) {
		swapz_u8 is_raw = index >= compressed_count;
		swapz_u16 length = is_raw ? SWAPZ_BLOCK_BYTES :
			compressed_lengths[next_random() %
				(sizeof(compressed_lengths) /
				 sizeof(compressed_lengths[0]))];

		mixed_make_payload(mixed_payloads[index], length);
		records[index] = (struct swapz_compressed_page) {
			.logical_page = logical_order[index],
			.payload = mixed_payloads[index],
			.length = length, .raw = is_raw,
		};
	}
	trace = mixed_note('W', records[0].logical_page, count);
	if (next_random() % 11U == 0U)
		disk.fail_on = disk.write_calls + 1U + next_random() % 2U;
	for (unsigned int retry = 0; retry < 16U && acknowledged < count;
	     ++retry) {
		swapz_u8 published = 0;
		int error = swapz_engine_write_window_batched(
			&engine, records + acknowledged, count - acknowledged,
			&published);

		disk.fail_on = 0;
		trace->result = error;
		MIXED_REQUIRE(published <= count - acknowledged,
			      "PUBLISHED_PREFIX_OVERFLOW");
		for (swapz_u32 index = acknowledged;
		     index < acknowledged + published; ++index)
			mixed_publish(&records[index]);
		acknowledged += published;
		MIXED_REQUIRE(mixed_verify_full_map() == 0,
			      "WRITE_PREFIX_CORRUPTION");
		if (!error) {
			MIXED_REQUIRE(acknowledged == count,
				      "SUCCESS_WITHOUT_ACKNOWLEDGEMENT");
			break;
		}
		MIXED_REQUIRE(error == -EIO || error == -ENOSPC,
			      "UNEXPECTED_LOWER_ERROR");
		if (error == -ENOSPC)
			MIXED_REQUIRE(mixed_collect_until_progress() == 0,
				      "CAPACITY_NO_PROGRESS");
	}
	MIXED_REQUIRE(acknowledged == count, "UNBOUNDED_WRITE_RETRY");
	return 0;
}

static int run_mixed_seed(uint32_t seed)
{
	unsigned int rotation_count = 0;

	MIXED_REQUIRE(mixed_setup(seed) == 0, "MIXED_SETUP");
	for (unsigned int step = 0; step < MIXED_STEPS; ++step) {
		swapz_u32 operation = next_random() % 100U;
		swapz_u32 logical = next_random() % LOGICAL_PAGES;
		struct mixed_trace_entry *trace;
		int error;

		mixed_step_number++;
		if (operation < 72U) {
			MIXED_REQUIRE(mixed_write_batch() == 0,
				      "WRITE_OR_RETRY_FAILURE");
		} else if (operation < 86U) {
			trace = mixed_note('D', logical, 1);
			error = swapz_discard_page(&authority, logical);
			trace->result = error;
			MIXED_REQUIRE(!error, "DISCARD_ERROR");
			reference_generation[logical]++;
			reference_valid[logical] = 0;
			reference_length[logical] = 0;
			mixed_mode[logical] = 0;
		} else if (operation < 94U) {
			/* Caller-owned zero representation: never publish a fake
			 * valid mapping; prove even the last nonzero byte is found. */
			trace = mixed_note('Z', logical, 1);
			memset(mixed_payloads[0], 0, SWAPZ_BLOCK_BYTES);
			MIXED_REQUIRE(swapz_page_is_zero(mixed_payloads[0]),
				      "ZERO_CLASSIFIER");
			mixed_payloads[0][SWAPZ_BLOCK_BYTES - 1U] = 1;
			MIXED_REQUIRE(!swapz_page_is_zero(mixed_payloads[0]),
				      "FALSE_ZERO_LAST_BYTE");
			error = swapz_discard_page(&authority, logical);
			trace->result = error;
			MIXED_REQUIRE(!error, "ZERO_DISCARD_ERROR");
			reference_generation[logical]++;
			reference_valid[logical] = 0;
			reference_length[logical] = 0;
			mixed_mode[logical] = 3;
		} else {
			trace = mixed_note('R', logical, 1);
			trace->result = 0;
		}
		MIXED_REQUIRE(mixed_verify_full_map() == 0,
			      "STEP_ORACLE_MISMATCH");
	}
	for (swapz_u32 segment = 0; segment < MIXED_SEGMENTS; ++segment)
		if (mixed_program_counts[segment] > 1U)
			rotation_count++;
	MIXED_REQUIRE(rotation_count > 0U &&
		      mixed_completed_rotations >= 2U,
		      "NO_REPEATED_RESERVE_COVERAGE");
	MIXED_REQUIRE(mixed_failed_writes > 0U, "NO_WRITE_EIO_COVERAGE");
	MIXED_REQUIRE(mixed_failed_reads > 0U, "NO_READ_EIO_COVERAGE");
	MIXED_REQUIRE(mixed_gc_write_failures > 0U, "NO_GC_FAULT_COVERAGE");
	printf("MIXED_PRODUCTION_C_PASS steps=%u "
	       "failed_writes=%u failed_reads=%u rotations=%u "
	       "gc_faults=%u recycled_segments=%u "
	       "synthetic_native_host_only=1\n",
	       MIXED_STEPS, mixed_failed_writes, mixed_failed_reads,
	       mixed_completed_rotations, mixed_gc_write_failures,
	       rotation_count);
	mixed_active = 0;
	return 0;
}

int main(void)
{
	static const swapz_u16 payload_lengths[] = {
		26, 257, 512, 1048, 1055, 1590, 1600, 2072, 2082, 2200,
		2224, 3000, 3500, 3568
	};
	static const unsigned read_caps[] = {0, 1, 2, 3};
	unsigned total_records = 0;

	disk.bytes = calloc(PHYSICAL_BLOCKS, SWAPZ_BLOCK_BYTES);
	CHECK(disk.bytes != NULL);

	for (unsigned cap_index = 0;
	     cap_index < sizeof(read_caps) / sizeof(read_caps[0]); cap_index++) {
		unsigned read_cap = read_caps[cap_index];
		unsigned generated_records = 0;

		CHECK(initialize_engine(read_cap) == 0);
		for (unsigned iteration = 0;
		     iteration < ITERATIONS_PER_CAP; iteration++) {
			unsigned count = 1U + next_random() % SWAPZ_MAX_RECORDS;
			swapz_u8 order[LOGICAL_PAGES];
			swapz_u8 committed = 0;
			int result;

			generated_records += count;
			total_records += count;
			for (unsigned i = 0; i < LOGICAL_PAGES; i++)
				order[i] = (swapz_u8)i;
			for (unsigned i = 0; i < count; i++) {
				unsigned j = i + next_random() %
					(LOGICAL_PAGES - i);
				swapz_u8 temporary = order[i];
				order[i] = order[j];
				order[j] = temporary;
			}
			for (unsigned i = 0; i < count; i++) {
				unsigned logical_page = order[i];
				swapz_u16 length = payload_lengths[
					next_random() % (sizeof(payload_lengths) /
						       sizeof(payload_lengths[0]))];

				pages[i].logical_page = logical_page;
				pages[i].payload = data_store[i];
				pages[i].length = length;
				for (unsigned j = 0; j < length; j++)
					data_store[i][j] = (swapz_u8)next_random();
			}
			result = swapz_engine_write_window_batched(&engine, pages,
							 (swapz_u8)count,
							 &committed);
			CHECK(result == 0);
			CHECK(committed == count);
			CHECK(!authority.in_flight);
			for (unsigned i = 0; i < count; i++) {
				update_reference(&pages[i]);
				CHECK(validate_page_authority(
					      pages[i].logical_page) == 0);
				CHECK(verify_page(pages[i].logical_page) == 0);
			}
			for (unsigned sample = 0; sample < 4; sample++) {
				unsigned logical_page =
					next_random() % LOGICAL_PAGES;

				CHECK(validate_page_authority(logical_page) == 0);
				CHECK(verify_page(logical_page) == 0);
			}
			/* Randomized WRITE/overwrite/DISCARD/read state machine.
			 * DISCARD advances generation even for an already-empty slot. */
			if ((next_transition_random() & 3U) == 0U) {
				unsigned logical_page =
					next_transition_random() % LOGICAL_PAGES;

				CHECK(swapz_discard_page(&authority,
						       logical_page) == 0);
				reference_generation[logical_page]++;
				reference_valid[logical_page] = 0;
				reference_length[logical_page] = 0;
				CHECK(validate_page_authority(logical_page) == 0);
				CHECK(verify_page(logical_page) == 0);
			}
		}

		/* Duplicate logical IDs must occupy separate planned extents. */
		{
			swapz_u8 plan[SWAPZ_MAX_RECORDS];
			swapz_u8 takes[SWAPZ_MAX_RECORDS];
			swapz_u8 groups = 0;
			swapz_u8 committed = 0;

			pages[0] = (struct swapz_compressed_page) {
				.logical_page = 7,
				.payload = data_store[0],
				.length = 2072,
			};
			pages[1] = (struct swapz_compressed_page) {
				.logical_page = 7,
				.payload = data_store[1],
				.length = 2072,
			};
			memset(data_store[0], 0x31, pages[0].length);
			memset(data_store[1], 0xa7, pages[1].length);
			CHECK(swapz_engine_plan_bounded(pages, 2, (swapz_u8)read_cap,
						      plan, takes, &groups) == 0);
			CHECK(groups == 2 && takes[0] == 1);
			CHECK(swapz_engine_write_window_batched(&engine, pages, 2,
						      &committed) == 0);
			CHECK(committed == 2);
			update_reference(&pages[0]);
			update_reference(&pages[1]);
			CHECK(validate_page_authority(7) == 0);
			CHECK(verify_page(7) == 0);
		}

		/* A partial second extent commits only the first complete prefix. */
		{
			swapz_u8 plan[SWAPZ_MAX_RECORDS];
			swapz_u8 takes[SWAPZ_MAX_RECORDS];
			swapz_u8 groups = 0;
			swapz_u8 committed = 0;
			swapz_u8 prefix;
			int result;

			for (unsigned i = 0; i < 16; i++) {
				pages[i] = (struct swapz_compressed_page) {
					.logical_page = i,
					.payload = data_store[i],
					.length = 2072,
				};
				memset(data_store[i], (int)(0x40 + i), 2072);
			}
			CHECK(swapz_engine_plan_bounded(pages, 16,
						      (swapz_u8)read_cap, plan,
						      takes, &groups) == 0);
			CHECK(groups > 1);
			prefix = takes[0];
			disk.fail_on = disk.write_calls + 2;
			result = swapz_engine_write_window_batched(&engine, pages, 16,
							 &committed);
			CHECK(result == -EIO);
			CHECK(committed == prefix);
			CHECK(!authority.in_flight);
			for (unsigned i = 0; i < 16; i++) {
				if (i < prefix)
					update_reference(&pages[i]);
				CHECK(validate_page_authority(
					      pages[i].logical_page) == 0);
				CHECK(verify_page(pages[i].logical_page) == 0);
			}
			CHECK(authority.abandoned_blocks > 0);
			disk.fail_on = 0;
		}

		printf("RANDOM_ENGINE_PASS cap=%u windows=%u generated_records=%u "
		       "writes=%u blocks=%u reads=%u next_block=%u\n",
		       read_cap, ITERATIONS_PER_CAP, generated_records,
		       disk.write_calls, disk.write_blocks, disk.read_blocks,
		       authority.next_block);
	}

	{
		static const uint32_t seeds[] = {
			0x38549a17U, 0x7e19e5b3U, 0xbad5eed1U
		};
		const char *selected_seed = getenv("SWAPZ_RANDOM_SEED");

		if (selected_seed && *selected_seed) {
			char *end = NULL;
			unsigned long parsed;

			errno = 0;
			parsed = strtoul(selected_seed, &end, 0);
			if (errno || end == selected_seed || *end ||
			    !parsed || parsed > UINT32_MAX) {
				fprintf(stderr, "INVALID_SWZ_RANDOM_SEED=%s\n",
					selected_seed);
				free(disk.bytes);
				return 1;
			}
			if (run_mixed_seed((uint32_t)parsed)) {
				free(disk.bytes);
				return 1;
			}
		} else {
			for (unsigned int index = 0;
			     index < sizeof(seeds) / sizeof(seeds[0]); ++index)
				if (run_mixed_seed(seeds[index])) {
					free(disk.bytes);
					return 1;
				}
		}
	}
	free(disk.bytes);
	printf("RANDOM_ENGINE_ALL_CAPS_PASS iterations=400 "
	       "generated_records=%u plus duplicate/fault cases records=pass\n",
	       total_records);
	return 0;
}
