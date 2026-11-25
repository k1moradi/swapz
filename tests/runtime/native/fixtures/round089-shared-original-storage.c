// SPDX-License-Identifier: GPL-2.0-only
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zswap-original-storage.h"
#include "engine.h"

enum { PAGES = 64, BLOCKS = 2048, SEGS = BLOCKS / SWAPZ_SEGMENT_BLOCKS };
static struct swapz_authority authority;
static struct swapz_map maps[PAGES];
static swapz_u16 live[BLOCKS], min_blocks[SEGS];
static swapz_u8 classes[BLOCKS], roles[SEGS], delta[BLOCKS];
static swapz_u32 counts[SEGS], programs[SEGS], bases[SEGS], first[SEGS], last[SEGS];
static swapz_u32 prev[PAGES], next[PAGES], costs[SEGS], live_bytes[SEGS];
static struct swapz_shared_storage storage;
static swapz_u8 media[BLOCKS][SWAPZ_BLOCK_BYTES], bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 output[SWAPZ_BLOCK_BYTES], scratch[SWAPZ_MAX_EXTENT_BYTES];
static unsigned int checks, writes, flushes, leases, lease_ids[9];
static int fail_flush, fail_write, short_write;
static struct swapz_tx ordinary;

#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); exit(77); \
	} } while (0)

static int write_lower(void *context, swapz_u32 start, const swapz_u8 *image,
		       swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS && authority.in_flight && !live[start]);
	CHECK(length == SWAPZ_BLOCK_BYTES);
	++writes;
	memcpy(media[start], image, length);
	*completed = short_write ? length - 1U : length;
	return fail_write;
}
static int flush_lower(void *context)
{
	CHECK(context == &storage && authority.in_flight);
	++flushes;
	return fail_flush;
}
static int read_lower(void *context, swapz_u32 start, swapz_u8 *image,
		      swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS && length == SWAPZ_BLOCK_BYTES);
	memcpy(image, media[start], length);
	*completed = length;
	return 0;
}
static void *get_decoder(void *context, swapz_u8 codec, swapz_u8 version)
{
	unsigned int index;
	CHECK(context == &storage && (codec == 1U || codec == 2U) && version == 1U);
	for (index = 0; index < 9U; ++index)
		if (!lease_ids[index]) {
			lease_ids[index] = codec; ++leases; return &lease_ids[index];
		}
	return NULL;
}
static void put_decoder(void *context, void *lease)
{
	unsigned int *entry = lease;
	CHECK(context == &storage && leases && *entry);
	*entry = 0; --leases;
}
static int ordinary_read(void *context, swapz_u32 start, swapz_u8 blocks,
			 swapz_u8 *destination)
{
	(void)context; (void)start; (void)blocks; (void)destination;
	CHECK(0); return -EIO;
}
static const struct swapz_original_storage_ops ops = {
	.context = &storage, .write = write_lower, .flush = flush_lower,
	.read = read_lower, .decoder_get = get_decoder, .decoder_put = put_decoder,
};

static void reset(void)
{
	CHECK(!leases);
	CHECK(!swapz_authority_init(&authority, maps, live, classes, PAGES, BLOCKS));
	CHECK(!swapz_enable_segment_rotation(&authority, roles, SEGS));
	CHECK(!swapz_enable_segment_mapping_counts(&authority, counts, SEGS));
	CHECK(!swapz_enable_segment_program_counts(&authority, programs, SEGS));
	CHECK(!swapz_enable_segment_page_lists(&authority, first, last, prev, next, SEGS, PAGES));
	CHECK(!swapz_enable_segment_gc_accounting(&authority, live_bytes, costs, min_blocks, SEGS));
	CHECK(!swapz_enable_extent_sequence_index(&authority, delta, bases, SEGS));
	authority.reuse_dead_segments = 1;
	CHECK(!swapz_shared_storage_init(&storage, &authority, &ops));
	writes = flushes = 0;
	fail_write = fail_flush = short_write = 0;
}

static int store(swapz_u32 page, swapz_u16 length, swapz_u32 generation)
{
	struct swapz_authority_import_spec spec = {
		.source_swap_slot = page, .source_entry_identity = 17,
		.source_store_generation = 3, .gc_epoch = 1, .logical_page = page,
		.compressed_length = length, .codec = 2, .codec_version = 1,
		.requested_fua = 1, .original_sha256 = {0x51},
	};
	struct swapz_original_extent_input input = {
		.bytes = bytes, .bytes_available = length, .logical_page = page,
		.generation = generation, .length = length, .decoded_length = SWAPZ_BLOCK_BYTES,
		.representation = 0x5a, .codec = 2, .version = 1,
	};
	spec.compressed_crc32c = swapz_crc32c_bytes(bytes, length);
	input.crc32c = spec.compressed_crc32c;
	return swapz_shared_storage_write(&storage, &spec, &input);
}
static void raw(swapz_u32 page)
{
	CHECK(!swapz_stage(&authority, &page, 1U, 1U, &ordinary));
	CHECK(!swapz_finish_raw(&authority, &ordinary, bytes, 1U, 0));
}
static void compressed(swapz_u32 page)
{
	swapz_u32 crc = swapz_crc32c_bytes(bytes, 321);
	memset(scratch, 0, SWAPZ_BLOCK_BYTES);
	memcpy(scratch + SWAPZ_BLOCK_BYTES - 321U, bytes, 321);
	CHECK(!swapz_stage(&authority, &page, 1U, 1U, &ordinary));
	CHECK(!swapz_bind_compressed_record(&authority, &ordinary, 0,
					   SWAPZ_BLOCK_BYTES - 321U, 321, crc, SWAPZ_ENCODING_LZ4));
	CHECK(!swapz_mark_compressed_data_only(&authority, &ordinary));
	CHECK(!swapz_finish(&authority, &ordinary, scratch, SWAPZ_BLOCK_BYTES, 1U, 0));
}
static void discard(swapz_u32 page)
{
	CHECK(!swapz_prevalidate_discard_range(&authority, page, 1));
	CHECK(!swapz_discard_page(&authority, page));
}
int main(void)
{
	swapz_u32 index, start, victim, dest, sequence, before_writes;
	swapz_u64 pin, other;
	swapz_u16 length;
	struct swapz_map old;
	struct swapz_engine engine = {0};
	const swapz_u8 *payload;

	for (index = 0; index < sizeof(bytes); ++index)
		bytes[index] = (swapz_u8)(index * 13U + 7U);
	reset();
	raw(0);
	old = maps[0];
	CHECK(store(0, 3569, 2) < 0 && !writes);
	CHECK(store(0, 321, 1) == -ESTALE && !writes);
	fail_flush = -EIO;
	CHECK(store(0, 321, 2) == -EIO && !memcmp(&old, &maps[0], sizeof(old)));
	CHECK(!authority.in_flight && !leases && live[old.start_block] == 1U);
	fail_flush = 0;
	CHECK(!store(0, 3568, 2));
	start = maps[0].start_block; victim = start / SWAPZ_SEGMENT_BLOCKS;
	CHECK(maps[0].valid && !maps[0].raw && (maps[0].state & SWAPZ_MAP_ORIGINAL));
	CHECK(maps[0].generation == 2 && maps[0].payload_length == 3568 && !live[old.start_block]);
	CHECK(counts[victim] == 1 && live_bytes[victim] == 3568 && costs[victim] == 7664);
	CHECK(min_blocks[victim] == 1 && first[victim] == 0 && last[victim] == 0);
	CHECK(!swapz_extent_sequence_lookup(&authority, start, &sequence) && sequence);
	CHECK(!memcmp(media[start], bytes, 3568) && !media[start][4095]);
	CHECK(swapz_read_authoritative_payload(&authority, 0, &maps[0], bytes, &payload) == -EOPNOTSUPP);
	engine.authority = &authority; engine.read_scratch = scratch; engine.io.read_blocks = ordinary_read;
	CHECK(swapz_engine_read_page(&engine, 0, output, sizeof(output), &length) == -EOPNOTSUPP);
	CHECK(!swapz_shared_original_pin(&authority, 0, &pin));
	/* Close the original victim, using the real allocator to select a new
	 * foreground segment after its cursor reaches the boundary. */
	authority.next_block = (victim + 1U) * SWAPZ_SEGMENT_BLOCKS;
	raw(1);
	CHECK(authority.open_segment != victim);
	CHECK(!swapz_gc_begin_rotation(&authority, victim));
	dest = authority.gc_destination;
	fail_flush = -EIO;
	CHECK(swapz_shared_storage_relocate(&storage, pin, 2) == -EIO);
	CHECK(maps[0].start_block == start && leases == 1 && counts[victim] == 1);
	fail_flush = 0;
	CHECK(!swapz_shared_storage_relocate(&storage, pin, 2));
	CHECK(maps[0].generation == 3 && maps[0].start_block / SWAPZ_SEGMENT_BLOCKS == dest);
	CHECK(!counts[victim] && !live_bytes[victim] && !costs[victim] && !min_blocks[victim]);
	CHECK(counts[dest] == 1 && live_bytes[dest] == 3568 && leases == 2 && !live[start]);
	CHECK(swapz_shared_original_segment_pinned(&authority, victim));
	CHECK(swapz_gc_commit_rotation(&authority, victim) == -EBUSY);
	CHECK(roles[victim] && !roles[dest]);
	CHECK(!swapz_shared_storage_read(&storage, pin, output, sizeof(output)));
	CHECK(!memcmp(output, bytes, 3568));
	CHECK(!swapz_shared_original_put(&authority, pin) && leases == 1);
	CHECK(swapz_shared_original_put(&authority, pin) == -ESTALE);
	CHECK(!swapz_gc_commit_rotation(&authority, victim));
	CHECK(!roles[victim] && roles[dest]);
	CHECK(!swapz_shared_original_pin(&authority, 0, &other));
	compressed(0);
	CHECK(!(maps[0].state & SWAPZ_MAP_ORIGINAL) && !maps[0].raw && maps[0].generation == 4);
	CHECK(leases == 1 && !swapz_shared_storage_read(&storage, other, output, sizeof(output)));
	CHECK(!swapz_shared_original_put(&authority, other) && !leases);
	CHECK(!store(0, 321, 5));
	CHECK(!swapz_shared_original_pin(&authority, 0, &pin));
	raw(0);
	CHECK(maps[0].raw && maps[0].generation == 6 && leases == 1);
	CHECK(!swapz_shared_original_put(&authority, pin) && !leases);
	CHECK(!store(0, 321, 7));
	CHECK(!swapz_shared_original_pin(&authority, 0, &pin));
	discard(0);
	CHECK(!maps[0].valid && maps[0].generation == 8 && leases == 1);
	CHECK(swapz_shared_storage_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_original_put(&authority, pin) && !leases);
	CHECK(!swapz_shared_storage_close(&storage));

	reset();
	fail_write = -EIO;
	CHECK(store(0, 1, 1) == -EIO && !maps[0].valid && !leases && !flushes);
	fail_write = 0; short_write = 1;
	CHECK(store(0, 1, 1) == -EIO && !maps[0].valid && !leases && !flushes);
	short_write = 0;
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		CHECK(!store(index, 1, 1));
	before_writes = writes;
	CHECK(store(9, 1, 1) == -ENOSPC && writes == before_writes);
	CHECK(store(0, 1, 2) == -ENOSPC && writes == before_writes);
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		discard(index);
	CHECK(!leases && !swapz_shared_storage_close(&storage));
	CHECK(sizeof(struct swapz_map) == 20 && SWAPZ_SHARED_ORIGINAL_ACTIVE == 0);
	printf("PASS ROUND089_AGENT5 checks=%u storage_bytes=%zu map_bytes=%zu sidecar_bytes=%zu\n",
	       checks, sizeof(storage), sizeof(struct swapz_map), sizeof(storage.owner));
	return 0;
}
