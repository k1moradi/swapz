// SPDX-License-Identifier: GPL-2.0-only
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zswap-original-storage.h"

enum { PAGES = 64, BLOCKS = 2048 };
static struct swapz_authority authority;
static struct swapz_map maps[PAGES];
static swapz_u16 live[BLOCKS];
static swapz_u8 classes[BLOCKS];
static struct swapz_original_storage storage;
static swapz_u8 media[BLOCKS][SWAPZ_BLOCK_BYTES];
static swapz_u8 bytes[SWAPZ_BLOCK_BYTES], output[SWAPZ_BLOCK_BYTES];
static unsigned int checks, writes, flushes, reads, leases;
static int write_error, short_write, flush_error, read_error, short_read, refuse_decoder;
static swapz_u32 destination;
static unsigned int lease_ids[SWAPZ_IMPORT_DISK_CAPACITY + 1U];

#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); \
	exit(77); } } while (0)

static int lower_write(void *context, swapz_u32 start, const swapz_u8 *image,
		       swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS);
	CHECK(authority.in_flight && !live[start] && length == SWAPZ_BLOCK_BYTES);
	++writes;
	destination = start;
	memcpy(media[start], image, length);
	*completed = short_write ? length - 1U : length;
	return write_error;
}

static int lower_flush(void *context)
{
	CHECK(context == &storage && authority.in_flight && !live[destination]);
	++flushes;
	return flush_error;
}

static int lower_read(void *context, swapz_u32 start, swapz_u8 *image,
		      swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS && live[start]);
	CHECK(length == SWAPZ_BLOCK_BYTES);
	++reads;
	memcpy(image, media[start], length);
	*completed = short_read ? length - 1U : length;
	return read_error;
}

static void *decoder_get(void *context, swapz_u8 codec, swapz_u8 version)
{
	unsigned int index;

	CHECK(context == &storage && (codec == 1U || codec == 2U) && version == 1U);
	if (refuse_decoder)
		return NULL;
	for (index = 0; index < sizeof(lease_ids) / sizeof(lease_ids[0]); ++index)
		if (!lease_ids[index]) {
			lease_ids[index] = codec;
			++leases;
			return &lease_ids[index];
		}
	return NULL;
}

static void decoder_put(void *context, void *lease)
{
	unsigned int *entry = lease;

	CHECK(context == &storage && leases && *entry);
	*entry = 0;
	--leases;
}

static const struct swapz_original_storage_ops ops = {
	.context = &storage, .write = lower_write, .flush = lower_flush,
	.read = lower_read, .decoder_get = decoder_get, .decoder_put = decoder_put,
};

static void reset(void)
{
	CHECK(!leases);
	CHECK(!swapz_authority_init(&authority, maps, live, classes, PAGES, BLOCKS));
	memset(media, 0xa5, sizeof(media));
	memset(lease_ids, 0, sizeof(lease_ids));
	writes = flushes = reads = 0;
	write_error = short_write = flush_error = read_error = short_read = refuse_decoder = 0;
	CHECK(!swapz_original_storage_init(&storage, &authority, &ops));
}

static struct swapz_authority_import_spec spec(swapz_u32 logical, swapz_u16 length)
{
	struct swapz_authority_import_spec value = {
		.source_swap_slot = 33, .source_entry_identity = 77,
		.source_store_generation = 109, .gc_epoch = 1,
		.logical_page = logical, .compressed_length = length,
		.codec = logical & 1U ? 1U : 2U, .codec_version = 1,
		.requested_fua = 1, .original_sha256 = {0x5a},
	};
	value.compressed_crc32c = swapz_crc32c_bytes(bytes, length);
	return value;
}

static struct swapz_original_extent_input input(
	const struct swapz_authority_import_spec *value)
{
	return (struct swapz_original_extent_input) {
		.bytes = bytes, .bytes_available = value->compressed_length,
		.logical_page = value->logical_page, .generation = 1,
		.length = value->compressed_length, .decoded_length = SWAPZ_BLOCK_BYTES,
		.crc32c = value->compressed_crc32c, .representation = 0x5a,
		.codec = value->codec, .version = value->codec_version,
	};
}

static int store(swapz_u32 logical, swapz_u16 length, swapz_u64 *ticket)
{
	struct swapz_authority_import_spec value = spec(logical, length);
	struct swapz_original_extent_input in = input(&value);

	return swapz_original_storage_write(&storage, &value, &in, ticket);
}

static void unchanged_output(void)
{
	unsigned int index;

	for (index = 0; index < sizeof(output); ++index)
		CHECK(output[index] == 0xa5);
}

int main(void)
{
	swapz_u64 ticket, pin, next, pins[SWAPZ_IMPORT_DISK_CAPACITY], tickets[SWAPZ_IMPORT_DISK_CAPACITY];
	swapz_u32 old, index;
	struct swapz_authority_import_spec value;
	struct swapz_original_extent_input in;

	for (index = 0; index < sizeof(bytes); ++index)
		bytes[index] = (swapz_u8)(index * 31U + 11U);
	reset();
	authority.reuse_dead_segments = 1;
	CHECK(swapz_original_storage_init(&storage, &authority, &ops) < 0);
	authority.reuse_dead_segments = 0;
	maps[0].valid = 1;
	CHECK(swapz_original_storage_init(&storage, &authority, &ops) < 0);
	maps[0].valid = 0;
	CHECK(!swapz_original_storage_init(&storage, &authority, &ops));
	ticket = 99;
	CHECK(store(0, 3569, &ticket) < 0 && ticket == 99);
	CHECK(store(0, 4095, &ticket) < 0 && ticket == 99);
	CHECK(store(0, 4096, &ticket) < 0 && ticket == 99);
	value = spec(0, 321); in = input(&value); in.generation = 2;
	CHECK(swapz_original_storage_write(&storage, &value, &in, &ticket) < 0);
	in = input(&value); in.crc32c ^= 1U;
	CHECK(swapz_original_storage_write(&storage, &value, &in, &ticket) < 0);
	in = input(&value); in.representation = 0;
	CHECK(swapz_original_storage_write(&storage, &value, &in, &ticket) < 0);
	in = input(&value);
	CHECK(swapz_original_storage_write(&storage, &value, &in,
					   &storage.next_pin) < 0);
	in.bytes = storage.gc_copy;
	CHECK(swapz_original_storage_write(&storage, &value, &in, &ticket) < 0);
	CHECK(!writes && !leases && !authority.next_block);
	refuse_decoder = 1;
	CHECK(store(0, 321, &ticket) < 0 && !writes && !leases);
	refuse_decoder = 0;
	/* A clean zero-filled initial image would hide a missing seal.
	 * Dirty the unused suffix before the actual copy/zero-pad test. */
	memset(storage.image, 0xa5, sizeof(storage.image));
	CHECK(!store(0, 3568, &ticket));
	old = destination;
	CHECK(leases == 1 && writes == 1 && flushes == 1 && live[old] == 1);
	CHECK(!maps[0].valid && !maps[0].generation);
	CHECK(!memcmp(media[old], bytes, 3568));
	for (index = 3568; index < SWAPZ_BLOCK_BYTES; ++index)
		CHECK(!media[old][index]);
	CHECK(swapz_original_storage_pin(&storage, ticket, &storage.next_pin) < 0);
	CHECK(!swapz_original_storage_pin(&storage, ticket, &pin));
	CHECK(swapz_original_storage_read(&storage, pin, storage.gc_copy,
					  sizeof(storage.gc_copy)) < 0);
	CHECK(swapz_original_storage_read(&storage, pin, (swapz_u8 *)maps,
					  sizeof(maps)) < 0);
	memset(output, 0xa5, sizeof(output));
	short_read = 1;
	CHECK(swapz_original_storage_read(&storage, pin, output, sizeof(output)) < 0);
	unchanged_output();
	short_read = 0;
	read_error = -EIO;
	CHECK(swapz_original_storage_read(&storage, pin, output, sizeof(output)) == -EIO);
	unchanged_output();
	read_error = 0;
	media[old][0] ^= 1U;
	CHECK(swapz_original_storage_read(&storage, pin, output, sizeof(output)) < 0);
	unchanged_output();
	media[old][0] ^= 1U;
	CHECK(!swapz_original_storage_read(&storage, pin, output, sizeof(output)));
	CHECK(!memcmp(output, bytes, 3568) && output[3568] == 0xa5);
	next = 99;
	CHECK(swapz_original_storage_relocate(&storage, pin, 1, &next) < 0 && next == 99);
	flush_error = -EIO;
	CHECK(swapz_original_storage_relocate(&storage, pin, 2, &next) == -EIO);
	CHECK(next == 99 && leases == 1 && live[old] == 1 && !authority.in_flight);
	CHECK(!live[destination] && classes[destination] == 1U);
	flush_error = 0;
	CHECK(!swapz_original_storage_relocate(&storage, pin, 2, &next));
	CHECK(next != ticket && destination != old && leases == 2 && live[old] && live[destination]);
	CHECK(!memcmp(media[old], media[destination], SWAPZ_BLOCK_BYTES));
	CHECK(swapz_original_storage_pin(&storage, ticket, &tickets[0]) < 0);
	CHECK(!swapz_original_storage_read(&storage, pin, output, sizeof(output)));
	CHECK(!swapz_original_storage_put(&storage, pin));
	CHECK(!live[old] && leases == 1);
	CHECK(swapz_original_storage_put(&storage, pin) < 0);
	CHECK(!swapz_original_storage_pin(&storage, next, &pin));
	CHECK(swapz_original_storage_close(&storage) == -EBUSY);
	CHECK(leases == 1 && live[destination]);
	CHECK(!swapz_original_storage_read(&storage, pin, output, sizeof(output)));
	CHECK(!swapz_original_storage_put(&storage, pin));
	CHECK(!leases && !live[destination]);
	CHECK(!swapz_original_storage_close(&storage));

	reset();
	ticket = 99;
	write_error = -EIO;
	CHECK(store(0, 1, &ticket) == -EIO && ticket == 99 && !leases && !flushes);
	CHECK(!authority.in_flight && !live[destination] && classes[destination] == 1);
	write_error = 0; short_write = 1;
	CHECK(store(0, 1, &ticket) == -EIO && ticket == 99 && !leases && !flushes);
	short_write = 0;
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		CHECK(!store(index, 1, &tickets[index]));
	CHECK(leases == SWAPZ_IMPORT_DISK_CAPACITY);
	CHECK(store(9, 1, &ticket) == -ENOSPC && ticket == 99);
	CHECK(leases == SWAPZ_IMPORT_DISK_CAPACITY);
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		CHECK(!swapz_original_storage_pin(&storage, tickets[0], &pins[index]));
	CHECK(swapz_original_storage_pin(&storage, tickets[0], &pin) == -ENOSPC);
	CHECK(swapz_original_storage_close(&storage) == -EBUSY && leases == 1);
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		CHECK(!swapz_original_storage_put(&storage, pins[index]));
	CHECK(!swapz_original_storage_close(&storage) && !leases);

	reset();
	authority.next_block = authority.physical_blocks - authority.reserve_blocks;
	CHECK(store(0, 1, &ticket) == -ENOSPC && !writes && !leases);
	CHECK(!swapz_original_storage_close(&storage));
	CHECK(sizeof(struct swapz_map) == 20 && SWAPZ_ORIGINAL_STORAGE_ACTIVE == 0);
	printf("PASS ROUND088_AGENT5 checks=%u storage_bytes=%zu map_bytes=%zu\n",
	       checks, sizeof(storage), sizeof(struct swapz_map));
	return 0;
}
