/* Round023 independent source-only zswap-producer -> swapz-consumer bridge.
 * This file is appended after the actual disabled pinned Linux producer C
 * body and the existing source test's host shims. All bridge values below
 * are MOCK/UNTRUSTED; no kernel slot-to-DM ABI exists.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-codec.h"
#include <lz4.h>
#include <stdio.h>

struct round023_untrusted_slot_mapping {
	swp_entry_t source_slot;
	u64 source_store_generation;
	u64 claimed_source_entry;
	u64 dm_logical_page;
	u64 dm_generation;
	u64 dm_gc_epoch;
	bool mock_authorized;
};

static int round023_test_adapter(
	const struct zswap_swapz_owned_payload *source,
	const struct round023_untrusted_slot_mapping *mapping,
	struct swapz_zswap_import_record *record)
{
	if (!source || !mapping || !record)
		return -EINVAL;
	/* A synthetic origin-BIO bit, recycled slot, or guessed index fails. */
	if (!mapping->mock_authorized || !mapping->claimed_source_entry ||
	    mapping->source_slot.val != source->entry_identity.val ||
	    !mapping->source_store_generation ||
	    mapping->source_store_generation != source->slot_generation ||
	    !mapping->dm_logical_page || !mapping->dm_generation ||
	    !mapping->dm_gc_epoch)
		return -ESTALE;
	if (source->self != source || !source->owned_allocation ||
	    source->owned_bytes != source->owned_allocation ||
	    atomic_read(&source->owner_state) != ZSWAP_SWAPZ_PAYLOAD_SUBMITTED ||
	    !source->semantic_stored_writeback ||
	    !source->representation_compressed ||
	    source->representation_version != ZSWAP_SWAPZ_RECORD_VERSION ||
	    source->representation != ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 ||
	    source->codec != ZSWAP_SWAPZ_CODEC_LZ4 ||
	    !source->compressed_length ||
	    source->compressed_length > SWAPZ_MAX_COMPRESSED ||
	    source->decoded_length != SWAPZ_BLOCK_BYTES)
		return -EOPNOTSUPP;
	/* The C producer & production codec.c must use identical CRC32C. */
	if (source->payload_crc32c !=
	    swapz_crc32c_bytes(source->owned_bytes, source->compressed_length))
		return -EBADMSG;
	*record = (struct swapz_zswap_import_record){
		.logical_page = mapping->dm_logical_page,
		.generation = mapping->dm_generation,
		.stored_entry_identity = mapping->claimed_source_entry,
		.store_generation = source->slot_generation,
		.gc_epoch = mapping->dm_gc_epoch,
		.compressed_length = source->compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.compressed_crc32c = source->payload_crc32c,
		.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
		.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
		.version = SWAPZ_ZSWAP_IMPORT_VERSION,
		.stored_eviction = 1U,
		.immutable_owned_copy = 1U,
	};
	memcpy(record->original_sha256, source->original_sha256,
	       sizeof(record->original_sha256));
	return 0;
}

static void round023_expect_denied(int error, const u8 *output)
{
	assert(error < 0);
	for (unsigned int index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		assert(output[index] == 0xa5U);
}

int main(void)
{
	struct zswap_entry stored = { .swpentry = { .val = 7U }, .length = 0U };
	struct folio locked = { true };
	struct zswap_swapz_stored_proof proof = { 0 };
	struct zswap_swapz_owned_payload producer = { 0 };
	struct round023_untrusted_slot_mapping mapping = {
		.source_slot = { .val = 7U }, .source_store_generation = 17U,
		.claimed_source_entry = 77U, .dm_logical_page = 301U,
		.dm_generation = 901U, .dm_gc_epoch = 42U,
		.mock_authorized = true,
	};
	struct swapz_zswap_import_record record = { 0 };
	struct swapz_zswap_import_read_authority reader = {
		.logical_page = 301U, .generation = 901U,
		.stored_entry_identity = 77U, .store_generation = 17U,
		.gc_epoch = 42U,
		.mapping_published_after_durable_write = 1U,
		.foreground_write_committed_once = 1U,
		.upper_write_ack_count = 1U, .current_owned_ram_session = 1U,
	};
	u8 scratch[SWAPZ_BLOCK_BYTES], output[SWAPZ_BLOCK_BYTES];
	const u8 crc_vector[] = { '1','2','3','4','5','6','7','8','9' };
	const swp_entry_t source_slot = { .val = 7U };
	int compressed_length;

	assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
	assert(~crc32c(~0U, crc_vector, sizeof(crc_vector)) == 0xe3069283U);
	assert(swapz_crc32c_bytes(crc_vector, 9U) == 0xe3069283U);
	assert(crc32c(0U, crc_vector, sizeof(crc_vector)) == 0x58e3fa20U);
	for (unsigned int index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		host_original_page[index] = (u8)(index % 251U);
	compressed_length = LZ4_compress_default(
		(const char *)host_original_page, (char *)zpool_bytes,
		(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED);
	assert(compressed_length > 0 && compressed_length <= (int)SWAPZ_MAX_COMPRESSED);
	stored.length = (unsigned int)compressed_length;
	tree.ptr = &stored;
	assert(zswap_swapz_bind_stored_entry(&proof, &stored, source_slot,
		17U, &locked, host_original_page, SWAPZ_BLOCK_BYTES) == 0);
	assert(zswap_swapz_capture_owned_payload(&producer, &stored, source_slot,
		&locked, &proof, 17U) == 0);
	assert(zswap_swapz_owned_payload_submit(&producer));
	/* A pending source cannot abort while lower authority is outstanding. */
	assert(!zswap_swapz_owned_payload_abort(&producer));

	/* Distinct ID domains: 7 != 301 != 901 != 42; no struct bit-cast. */
	assert(round023_test_adapter(&producer, &mapping, &record) == 0);
	reader.actual_lower_read_bytes = record.compressed_length;
	memset(output, 0xa5, sizeof(output));
	assert(swapz_zswap_import_decode(&record, &reader, producer.owned_bytes,
		record.compressed_length, scratch, sizeof(scratch),
		output, sizeof(output), host_original_page) == 0);
	assert(memcmp(output, host_original_page, sizeof(output)) == 0);
	/* Only the non-authoritative fixture can claim a fake bridge. */
	mapping.mock_authorized = false;
	assert(round023_test_adapter(&producer, &mapping, &record) == -ESTALE);
	mapping.mock_authorized = true;
	mapping.source_slot.val++;
	assert(round023_test_adapter(&producer, &mapping, &record) == -ESTALE);
	mapping.source_slot.val--;
	mapping.source_store_generation++;
	assert(round023_test_adapter(&producer, &mapping, &record) == -ESTALE);
	mapping.source_store_generation--;
	producer.payload_crc32c = crc32(0, producer.owned_bytes,
					producer.compressed_length);
	assert(round023_test_adapter(&producer, &mapping, &record) == -EBADMSG);
	producer.payload_crc32c = crc32c(0, producer.owned_bytes,
					producer.compressed_length);
	assert(round023_test_adapter(&producer, &mapping, &record) == -EBADMSG);
	producer.payload_crc32c = swapz_crc32c_bytes(producer.owned_bytes,
					producer.compressed_length);
	assert(round023_test_adapter(&producer, &mapping, &record) == 0);
#define CHECK_DENIED(mutate,restore) do { mutate; memset(output,0xa5,sizeof(output)); \
	round023_expect_denied(swapz_zswap_import_decode(&record,&reader, \
	producer.owned_bytes,record.compressed_length,scratch,sizeof(scratch), \
	output,sizeof(output),host_original_page),output); restore; } while (0)
	CHECK_DENIED(record.compressed_crc32c ^= 1U,
		     record.compressed_crc32c ^= 1U);
	CHECK_DENIED(record.compressed_crc32c = crc32(0,producer.owned_bytes,
		     producer.compressed_length),
		     record.compressed_crc32c = producer.payload_crc32c);
	CHECK_DENIED(record.codec = 2U, record.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
	CHECK_DENIED(record.version = 2U, record.version = SWAPZ_ZSWAP_IMPORT_VERSION);
	CHECK_DENIED(record.dictionary_id = 1U, record.dictionary_id = 0U);
	CHECK_DENIED(record.compressed_length = 0U,
		     record.compressed_length = producer.compressed_length);
	CHECK_DENIED(record.compressed_length = 3569U,
		     record.compressed_length = producer.compressed_length);
	CHECK_DENIED(record.original_sha256[0] ^= 1U,
		     record.original_sha256[0] ^= 1U);
	CHECK_DENIED(reader.generation++, reader.generation--);
	CHECK_DENIED(reader.gc_epoch++, reader.gc_epoch--);
	CHECK_DENIED(reader.actual_lower_read_bytes--,
		     reader.actual_lower_read_bytes++);
	CHECK_DENIED(reader.mapping_published_after_durable_write = 0U,
		     reader.mapping_published_after_durable_write = 1U);
	CHECK_DENIED(reader.foreground_write_committed_once = 0U,
		     reader.foreground_write_committed_once = 1U);
	CHECK_DENIED(reader.upper_write_ack_count = 0U,
		     reader.upper_write_ack_count = 1U);
	CHECK_DENIED(reader.upper_write_ack_count = 2U,
		     reader.upper_write_ack_count = 1U);
	CHECK_DENIED(reader.teardown_started = 1U, reader.teardown_started = 0U);
	CHECK_DENIED(reader.lower_read_error = -EIO, reader.lower_read_error = 0);
#undef CHECK_DENIED
	memset(output, 0xa5, sizeof(output));
	round023_expect_denied(swapz_zswap_import_decode(
		&record, &reader, producer.owned_bytes, record.compressed_length,
		output, sizeof(output), output, sizeof(output), host_original_page),
		output);
	/* A source buffer still owned only until its exactly-once finish. */
	assert(zswap_swapz_owned_payload_finish(&producer, 0));
	assert(!zswap_swapz_owned_payload_finish(&producer, -EIO));
	assert(round023_test_adapter(&producer, &mapping, &record) == -EOPNOTSUPP);
	puts("ROUND023_CROSS_ABI_SOURCE_ONLY_PASS");
	return 0;
}
