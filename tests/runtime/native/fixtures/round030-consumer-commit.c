/* Round030: compile EXACT production DM C with fake lower-device boundary. */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_ADMISSION_HOST_TEST 1
#include "authority.h"
#include "zswap-import-admission.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define smp_load_acquire(address) (*(address))
#define lockdep_assert_held(address) assert(*(address) == 1)

struct fake_gc_recovery { bool active; };
struct swapz_dm {
	struct swapz_authority authority;
	struct swapz_map *maps;
	struct swapz_tx raw_io_transaction;
	struct fake_gc_recovery gc_recovery;
	bool accepting;
	bool failed;
	bool prepublication_fua;
	int ordered_owner;
};
static swapz_u8 disk_data[8U * SWAPZ_BLOCK_BYTES];
static int lower_write_error, lower_read_error, finish_error, stage_error;
static int lower_writes, lower_reads, lower_fua, stage_calls, finish_calls, abort_calls;
static swapz_u32 next_sequence = 5U;

static int swapz_zswap_lz4_header_only_probe(void) { return 0; }
static int swapz_open_segment_fits(const struct swapz_authority *authority,
				  swapz_u8 blocks)
{
	return !authority->in_flight && (blocks == 1U || blocks == 2U ||
					blocks == 4U);
}
static int swapz_stage(struct swapz_authority *authority,
		       const swapz_u32 *logical_pages, swapz_u8 count,
		       swapz_u8 blocks, struct swapz_tx *transaction)
{
	if (stage_error) return stage_error;
	assert(count == 1U);
	assert(blocks == 1U || blocks == 2U || blocks == 4U);
	assert(logical_pages[0] != 0U);
	assert(authority->in_flight == 0U);
	++stage_calls;
	memset(transaction, 0, sizeof(*transaction));
	transaction->count = count;
	transaction->extent_blocks = blocks;
	transaction->start_block = 2U;
	transaction->sequence = next_sequence;
	transaction->records[0].logical_page = logical_pages[0];
	transaction->records[0].generation =
		authority->maps[logical_pages[0]].generation + 1U;
	authority->in_flight = 1U;
	return 0;
}
static int swapz_bind_compressed_record(struct swapz_authority *authority,
				       struct swapz_tx *transaction,
				       swapz_u8 record_index, swapz_u16 payload_offset,
				       swapz_u16 payload_length, swapz_u32 payload_crc32c,
				       swapz_u8 encoding)
{
	(void)authority;
	assert(record_index == 0U);
	assert(encoding == SWAPZ_ENCODING_LZ4);
	transaction->records[0].payload_offset = payload_offset;
	transaction->records[0].payload_length = payload_length;
	transaction->records[0].payload_crc32c = payload_crc32c;
	transaction->records[0].encoding = encoding;
	transaction->records[0].compressed_metadata_bound = 1U;
	return 0;
}
static int swapz_mark_compressed_data_only(struct swapz_authority *authority,
					  struct swapz_tx *transaction)
{
	(void)authority;
	assert(transaction->records[0].compressed_metadata_bound);
	transaction->compressed_data_only = 1U;
	return 0;
}
static int swapz_lower_write(void *opaque, swapz_u32 block, swapz_u8 blocks,
			     const swapz_u8 *bytes, swapz_u8 *completed)
{
	struct swapz_dm *ctx = opaque;
	*completed = 0U;
	++lower_writes;
	if (lower_write_error) return lower_write_error;
	if (ctx->prepublication_fua) ++lower_fua;
	assert(block >= 1U && block + blocks <= 8U);
	memcpy(disk_data + block * SWAPZ_BLOCK_BYTES,
	       bytes, (size_t)blocks * SWAPZ_BLOCK_BYTES);
	*completed = blocks;
	return 0;
}
static int swapz_finish(struct swapz_authority *authority,
			const struct swapz_tx *transaction, const void *extent,
			swapz_u32 total_bytes, swapz_u8 completed, int io_error)
{
	const struct swapz_tx_record *record = &transaction->records[0];
	struct swapz_map *mapping = &authority->maps[record->logical_page];
	++finish_calls;
	assert(authority->in_flight == 1U);
	authority->in_flight = 0U;
	if (io_error) return io_error;
	if (finish_error) return finish_error;
	if (!extent || total_bytes != SWAPZ_BLOCK_BYTES * transaction->extent_blocks ||
	    completed != transaction->extent_blocks ||
	    !transaction->compressed_data_only)
		return -EIO;
	assert(swapz_crc32c_bytes((const swapz_u8 *)extent + record->payload_offset,
				 record->payload_length) == record->payload_crc32c);
	memset(mapping, 0, sizeof(*mapping));
	mapping->start_block = transaction->start_block;
	mapping->generation = record->generation;
	mapping->extent_blocks = transaction->extent_blocks;
	mapping->record_index = swapz_map_pack_record_index(0U, record->encoding);
	mapping->valid = 1U;
	mapping->payload_offset = record->payload_offset;
	mapping->payload_length = record->payload_length;
	mapping->payload_crc32c = record->payload_crc32c;
	return 0;
}
static int swapz_abort(struct swapz_authority *authority,
		       const struct swapz_tx *transaction)
{
	(void)transaction;
	++abort_calls;
	authority->in_flight = 0U;
	return 0;
}
static int swapz_extent_sequence_lookup(const struct swapz_authority *authority,
					swapz_u32 block, swapz_u32 *sequence)
{
	(void)authority;
	if (block != 2U) return -ESTALE;
	*sequence = next_sequence;
	return 0;
}
static int swapz_preserve_first_error(int original, int later)
{
	return original ? original : later;
}
static void swapz_fail(struct swapz_dm *ctx, int error)
{
	(void)error;
	ctx->failed = true;
}
static int swapz_round028_dm_stage_owned_payload(
		const struct swapz_zswap_admission_transaction *transaction,
		const swapz_u8 *owned, swapz_u32 capacity,
		swapz_u8 *image, swapz_u32 image_capacity)
{
	const swapz_u32 extent_bytes = transaction->physical_extent_bytes;
	if (!owned || !image || transaction->phase != SWAPZ_ZSWAP_ADMISSION_PREPARED ||
	    transaction->owned_compressed_bytes != owned ||
	    !transaction->record.compressed_length ||
	    capacity < transaction->record.compressed_length ||
	    image_capacity < extent_bytes)
		return -EMSGSIZE;
	if (swapz_crc32c_bytes(owned, transaction->record.compressed_length) !=
	    transaction->record.compressed_crc32c)
		return -EBADMSG;
	memset(image, 0, extent_bytes);
	memcpy(image + transaction->compressed_payload_offset, owned,
	       transaction->record.compressed_length);
	return 0;
}
static int swapz_round028_dm_owned_lower_readback(
		struct swapz_dm *ctx,
		const struct swapz_zswap_admission_transaction *transaction,
		swapz_u32 logical, swapz_u8 *lower_image,
		swapz_u32 capacity, swapz_u8 *scratch, swapz_u8 *decoded)
{
	const struct swapz_map *mapped = &ctx->authority.maps[logical];
	const swapz_u32 bytes = (swapz_u32)mapped->extent_blocks * SWAPZ_BLOCK_BYTES;
	++lower_reads;
	if (lower_read_error || capacity < bytes) return -EIO;
	memcpy(lower_image, disk_data + mapped->start_block * SWAPZ_BLOCK_BYTES, bytes);
	return swapz_zswap_admission_read_4096(
		transaction, logical, mapped->generation,
		transaction->record.gc_epoch,
		lower_image + mapped->payload_offset, bytes, 0, scratch, decoded, NULL);
}
/* ROUND030_EXACT_DM_COMMIT_SOURCE */

static swapz_u8 original[SWAPZ_BLOCK_BYTES], compressed[SWAPZ_MAX_COMPRESSED];
static swapz_u8 lower_image[4U * SWAPZ_BLOCK_BYTES];
static swapz_u8 scratch[SWAPZ_BLOCK_BYTES], output[SWAPZ_BLOCK_BYTES];
static struct swapz_map maps[32];

static void initial_state(struct swapz_dm *ctx,
			  struct swapz_zswap_admission_transaction *transaction,
			  struct swapz_round030_dm_volatile_descriptor *descriptor,
			  swapz_u32 physical_bytes, swapz_u32 compressed_length)
{
	unsigned int index;
	struct swapz_zswap_admission_mapping mapping = { 0 };
	struct swapz_zswap_import_record record = { 0 };
	memset(ctx, 0, sizeof(*ctx));
	memset(maps, 0, sizeof(maps));
	memset(descriptor, 0, sizeof(*descriptor));
	memset(transaction, 0, sizeof(*transaction));
	ctx->authority.maps = maps;
	ctx->authority.logical_pages = 32U;
	ctx->maps = maps;
	ctx->accepting = true;
	ctx->ordered_owner = 1;
	mapping.source_swap_slot = 1234U;
	mapping.source_store_generation = 333U;
	mapping.source_stored_entry_identity = 222U;
	mapping.dm_logical_page = 5U;
	mapping.dm_generation = 1U;
	mapping.dm_gc_epoch = 444U;
	mapping.physical_extent_bytes = physical_bytes;
	mapping.compressed_payload_offset = physical_bytes - compressed_length;
	mapping.mock_bridge_only = 1U;
	mapping.source_stored_eviction_verified = 1U;
	mapping.compressed_source_owned_copy = 1U;
	mapping.original_sha256_from_store = 1U;
	mapping.post_header_extent_authorized = 1U;
	mapping.deterministic_zero_padding = 1U;
	record.logical_page = 5U;
	record.generation = 1U;
	record.stored_entry_identity = 222U;
	record.store_generation = 333U;
	record.gc_epoch = 444U;
	record.compressed_length = compressed_length;
	record.compressed_crc32c = swapz_crc32c_bytes(compressed, compressed_length);
	record.decoded_length = SWAPZ_BLOCK_BYTES;
	record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
	record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
	record.version = SWAPZ_ZSWAP_IMPORT_VERSION;
	record.immutable_owned_copy = 1U;
	record.stored_eviction = 1U;
	assert(SHA256(original, SWAPZ_BLOCK_BYTES, record.original_sha256));
	assert(swapz_zswap_admission_begin_mock(
			transaction, &mapping, &record, compressed,
			SWAPZ_MAX_COMPRESSED) == 0);
	assert(swapz_zswap_admission_try_live(transaction) == -EOPNOTSUPP);
	for (index = 0U; index < sizeof(lower_image); ++index)
		lower_image[index] = 0xa5U;
	lower_write_error = lower_read_error = finish_error = stage_error = 0;
	lower_writes = lower_reads = lower_fua = stage_calls = finish_calls = abort_calls = 0;
}

int main(void)
{
	struct swapz_dm ctx = { 0 };
	struct swapz_zswap_admission_transaction transaction = { 0 };
	struct swapz_round030_dm_volatile_descriptor descriptor = { 0 };
	swapz_u32 original_offset, compressed_length;
	int packed;
	unsigned int index, extent;

	(void)swapz_zswap_lz4_header_only_probe();
	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		original[index] = (swapz_u8)(index % 251U);
	packed = LZ4_compress_default((const char *)original, (char *)compressed,
				      (int)SWAPZ_BLOCK_BYTES,
				      (int)SWAPZ_MAX_COMPRESSED);
	assert(packed > 0);
	compressed_length = (swapz_u32)packed;
	for (extent = 1U; extent <= 4U; extent *= 2U) {
		initial_state(&ctx, &transaction, &descriptor,
			      extent * SWAPZ_BLOCK_BYTES, compressed_length);
		original_offset = transaction.compressed_payload_offset;
		assert(swapz_round030_dm_commit_owned_lz4(
			&ctx, &transaction, 1234U, compressed, compressed_length,
			lower_image, sizeof(lower_image), &descriptor, true) == 0);
		assert(stage_calls == 1 && lower_writes == 1 &&
		       finish_calls == 1 && lower_fua == 1);
		assert(!abort_calls);
		assert(descriptor.published && descriptor.hypothetical_ack_count == 1U);
		assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_ACKED);
		assert(memcmp(disk_data + 2U * SWAPZ_BLOCK_BYTES + original_offset,
			      compressed, compressed_length) == 0);
		for (index = 0; index < original_offset; ++index)
			assert(disk_data[2U * SWAPZ_BLOCK_BYTES + index] == 0U);
		memset(output, 0xa5, sizeof(output));
		assert(swapz_round030_dm_read_owned_lz4(
			&ctx, &descriptor, &transaction, lower_image,
			sizeof(lower_image), scratch, output) == 0);
		assert(memcmp(output, original, sizeof(output)) == 0);
		assert(swapz_round030_dm_commit_owned_lz4(
			&ctx, &transaction, 1234U, compressed, compressed_length,
			lower_image, sizeof(lower_image), &descriptor, true) == -ESTALE);
		assert(lower_writes == 1);
		descriptor.mapping.generation++;
		memset(output, 0x77, sizeof(output));
		assert(swapz_round030_dm_read_owned_lz4(
			&ctx, &descriptor, &transaction, lower_image,
			sizeof(lower_image), scratch, output) == -ESTALE);
		assert(output[0] == 0x77U);
	}
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	lower_write_error = -EIO;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, true) == -EIO);
	assert(!maps[5].valid && !descriptor.published && !descriptor.hypothetical_ack_count);
	assert(transaction.phase == SWAPZ_ZSWAP_ADMISSION_DISCARDED);
	assert(finish_calls == 1 && lower_writes == 1);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	transaction.record.compressed_crc32c ^= 1U;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == -EBADMSG);
	assert(!lower_writes && abort_calls == 1 && !maps[5].valid);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	transaction.record.codec = 8U;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == -EOPNOTSUPP);
	assert(!stage_calls && !lower_writes);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	transaction.record.generation = 4U;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == -ESTALE);
	assert(!lower_writes);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	stage_error = -ENOSPC;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == -ENOSPC);
	assert(!lower_writes);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	transaction.teardown_started = 1U;
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == -ESTALE);
	assert(!lower_writes);
	initial_state(&ctx, &transaction, &descriptor, SWAPZ_BLOCK_BYTES,
		      compressed_length);
	assert(swapz_round030_dm_commit_owned_lz4(
		&ctx, &transaction, 1234U, compressed, compressed_length,
		lower_image, sizeof(lower_image), &descriptor, false) == 0);
	lower_read_error = -EIO;
	memset(output, 0xa5, sizeof(output));
	assert(swapz_round030_dm_read_owned_lz4(
		&ctx, &descriptor, &transaction, lower_image, sizeof(lower_image),
		scratch, output) == -EIO);
	assert(output[0] == 0xa5U);
	lower_read_error = 0;
	disk_data[2U * SWAPZ_BLOCK_BYTES + transaction.compressed_payload_offset] ^= 0x80;
	assert(swapz_round030_dm_read_owned_lz4(
		&ctx, &descriptor, &transaction, lower_image, sizeof(lower_image),
		scratch, output) == -EBADMSG);
	assert(output[0] == 0xa5U);
	puts("ROUND030_DM_SOURCE_EXTRACTED_ORDERED_COMMIT_PASS");
	return 0;
}
