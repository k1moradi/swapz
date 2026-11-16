/* Source-only Round023 consumer admission: no DM/kernel runtime integration. */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_ADMISSION_HOST_TEST 1
#include "zswap-import-admission.h"
#include <assert.h>
#include <lz4.h>
#include <openssl/sha.h>
#include <stdio.h>
#include <string.h>

static swapz_u8 original[4096], lower_extent[4096], scratch[4096], output[4096];

static void expect_unmodified(int result)
{
	assert(result < 0);
	for (unsigned int index = 0; index < 4096U; ++index)
		assert(output[index] == 0xa5U);
}

static void reset_output(void)
{
	memset(output, 0xa5, sizeof(output));
}

static int mock_read(struct swapz_zswap_admission_transaction *transaction,
		     swapz_u64 page, swapz_u64 generation,
		     swapz_u64 epoch, swapz_u32 lower_bytes, int lower_error,
		     const swapz_u8 *independent_original)
{
	return swapz_zswap_admission_read_4096(
		transaction, page, generation, epoch,
		lower_extent + transaction->compressed_payload_offset,
		lower_bytes, lower_error, scratch, output, independent_original);
}

int main(void)
{
	struct swapz_zswap_import_record record = {
		.logical_page = 301U, .generation = 901U,
		.stored_entry_identity = 77U, .store_generation = 17U,
		.gc_epoch = 42U, .decoded_length = 4096U,
		.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
		.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
		.version = SWAPZ_ZSWAP_IMPORT_VERSION,
		.stored_eviction = 1U, .immutable_owned_copy = 1U,
	};
	struct swapz_zswap_admission_mapping mapping = {
		.source_swap_slot = 7U, .source_store_generation = 17U,
		.source_stored_entry_identity = 77U, .dm_logical_page = 301U,
		.dm_generation = 901U, .dm_gc_epoch = 42U,
		.physical_extent_bytes = 4096U, .compressed_payload_offset = 128U,
		.post_header_extent_authorized = 1U,
		.deterministic_zero_padding = 1U,
		.source_stored_eviction_verified = 1U,
		.compressed_source_owned_copy = 1U,
		.original_sha256_from_store = 1U,
		.mock_bridge_only = 1U,
	};
	struct swapz_zswap_admission_transaction transaction = { 0 };
	int compressed_length;

	assert(SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE == 0U);
	assert(swapz_zswap_admission_try_live(&transaction) == -EOPNOTSUPP);
	for (unsigned int index = 0; index < 4096U; ++index)
		original[index] = (swapz_u8)(index % 251U);
	compressed_length = LZ4_compress_default(
		(const char *)original, (char *)lower_extent + 128,
		4096, 3568);
	assert(compressed_length > 0 && compressed_length <= 3568);
	record.compressed_length = (swapz_u32)compressed_length;
	record.compressed_crc32c = swapz_crc32c_bytes(
		lower_extent + 128, record.compressed_length);
	assert(SHA256(original, sizeof(original), record.original_sha256));
	/* Separate provenance namespaces: source slot 7, DM page 301,
	 * DM generation 901, source generation 17, GC epoch 42.
	 */
	mapping.mock_bridge_only = 0U;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -ESTALE);
	mapping.mock_bridge_only = 1U;
	mapping.source_store_generation++;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -ESTALE);
	mapping.source_store_generation--;
	mapping.physical_extent_bytes = 4095U;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -EMSGSIZE);
	mapping.physical_extent_bytes = 4096U;
	mapping.post_header_extent_authorized = 0U;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -ESTALE);
	mapping.post_header_extent_authorized = 1U;
	record.compressed_crc32c ^= 1U;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -EBADMSG);
	record.compressed_crc32c ^= 1U;
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == 0);
	assert(swapz_zswap_admission_begin_mock(&transaction, &mapping, &record,
		lower_extent + 128, record.compressed_length) == -EBUSY);
	assert(swapz_zswap_admission_publish_ram_mapping(&transaction,301,901,42)
	       == -ESTALE);
	assert(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE);
	assert(swapz_zswap_admission_lower_write_done(&transaction, -EIO, 4096)
	       == -EIO);
	assert(swapz_zswap_admission_lower_write_done(&transaction, 0, 4095)
	       == -EIO);
	assert(swapz_zswap_admission_lower_write_done(&transaction, 0, 4096)
	       == 0);
	assert(swapz_zswap_admission_lower_write_done(&transaction, 0, 4096)
	       == -ESTALE);
	assert(swapz_zswap_admission_publish_ram_mapping(&transaction,301,901,43)
	       == -ESTALE);
	assert(swapz_zswap_admission_publish_ram_mapping(&transaction,301,902,42)
	       == -ESTALE);
	assert(swapz_zswap_admission_publish_ram_mapping(&transaction,301,901,42)
	       == 0);
	assert(swapz_zswap_admission_upper_write_ack(&transaction) == 0);
	assert(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE);
	reset_output();
	assert(mock_read(&transaction,301,901,42,4096,0,original)==0);
	assert(memcmp(output,original,4096)==0);
	reset_output();
	expect_unmodified(mock_read(&transaction,301,902,42,4096,0,original));
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,43,4096,0,original));
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4095,0,original));
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4096,-EIO,original));
	transaction.record.compressed_crc32c ^= 1U;
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4096,0,original));
	transaction.record.compressed_crc32c ^= 1U;
	transaction.record.original_sha256[0] ^= 1U;
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4096,0,original));
	transaction.record.original_sha256[0] ^= 1U;
	original[0] ^= 1U;
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4096,0,original));
	original[0] ^= 1U;
	swapz_zswap_admission_invalidate(&transaction);
	reset_output();
	expect_unmodified(mock_read(&transaction,301,901,42,4096,0,original));
	assert(swapz_zswap_admission_upper_write_ack(&transaction) == -ESTALE);
	/* Only compressed bytes lie in the payload-only lower extent. */
	for (unsigned int index = 0; index < 128U; ++index)
		assert(lower_extent[index] == 0U);
	puts("ROUND023_DM_ADMISSION_SOURCE_ONLY_PASS");
	return 0;
}
