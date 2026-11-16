/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ZSWAP_IMPORT_ADMISSION_H
#define SWAPZ_ZSWAP_IMPORT_ADMISSION_H

/*
 * Round023 source-only typed compressed import transaction. Unreferenced by
 * production DM. A real kernel carrier is NOT authenticated and cannot be
 * inferred from bi_swap_origin, an ordinary 4096-byte BIO or a matching slot.
 * This header is executable only by a MOCK/UNTRUSTED host fixture.
 */
#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U
#include "zswap-import-codec.h"

enum swapz_zswap_admission_phase {
	SWAPZ_ZSWAP_ADMISSION_EMPTY = 0,
	SWAPZ_ZSWAP_ADMISSION_PREPARED,
	SWAPZ_ZSWAP_ADMISSION_DURABLE,
	SWAPZ_ZSWAP_ADMISSION_MAPPED,
	SWAPZ_ZSWAP_ADMISSION_ACKED,
	SWAPZ_ZSWAP_ADMISSION_DISCARDED,
};

struct swapz_zswap_admission_mapping {
	/* Source and DM identity domains are independent, never bit-cast. */
	swapz_u64 source_swap_slot;
	swapz_u64 source_store_generation;
	swapz_u64 source_stored_entry_identity;
	swapz_u64 dm_logical_page;
	swapz_u64 dm_generation;
	swapz_u64 dm_gc_epoch;
	swapz_u32 physical_extent_bytes; /* 4096/8192/16384 lower image. */
	swapz_u32 compressed_payload_offset;
	swapz_u8 post_header_extent_authorized;
	swapz_u8 deterministic_zero_padding;
	swapz_u8 source_stored_eviction_verified;
	swapz_u8 compressed_source_owned_copy;
	swapz_u8 original_sha256_from_store;
	swapz_u8 mock_bridge_only;
};

struct swapz_zswap_admission_transaction {
	struct swapz_zswap_import_record record;
	const swapz_u8 *owned_compressed_bytes;
	enum swapz_zswap_admission_phase phase;
	swapz_u32 payload_capacity;
	swapz_u32 physical_extent_bytes;
	swapz_u32 compressed_payload_offset;
	swapz_u32 durable_bytes;
	swapz_u8 upper_write_ack_count;
	swapz_u8 teardown_started;
};

/* No production transport exists. Never write a compressed-length payload
 * into the conventional 4096-byte REQ_SWAP upper BIO. Return no authority.
 */
static inline int swapz_zswap_admission_try_live(
		struct swapz_zswap_admission_transaction *transaction)
{
	(void)transaction;
	return -EOPNOTSUPP;
}

/*
 * MOCK ONLY: source pointers remain owned by the fixture through completion.
 * All real source provenance fields are still UNAUTHENTICATED by this test.
 * Ordered caller owns transaction exclusively: NOT safe for concurrent state
 * mutation; a future DM path must add ordered-owner and generation fences.
 */
static inline int swapz_zswap_admission_begin_mock(
		struct swapz_zswap_admission_transaction *transaction,
		const struct swapz_zswap_admission_mapping *mapping,
		const struct swapz_zswap_import_record *record,
		const swapz_u8 *owned_compressed_bytes,
		swapz_u32 compressed_capacity)
{
#ifdef SWAPZ_ZSWAP_ADMISSION_HOST_TEST
	swapz_u8 digest_present = 0;
	unsigned int index;

	if (!transaction || !mapping || !record || !owned_compressed_bytes)
		return -EINVAL;
	if (transaction->phase != SWAPZ_ZSWAP_ADMISSION_EMPTY)
		return -EBUSY;
	if (!mapping->mock_bridge_only ||
	    !mapping->source_stored_eviction_verified ||
	    !mapping->compressed_source_owned_copy ||
	    !mapping->original_sha256_from_store ||
	    !mapping->source_swap_slot ||
	    !mapping->source_store_generation ||
	    !mapping->source_stored_entry_identity ||
	    !mapping->dm_logical_page ||
	    !mapping->dm_generation || !mapping->dm_gc_epoch ||
	    mapping->dm_logical_page != record->logical_page ||
	    mapping->dm_generation != record->generation ||
	    mapping->dm_gc_epoch != record->gc_epoch ||
	    mapping->source_store_generation != record->store_generation ||
	    mapping->source_stored_entry_identity != record->stored_entry_identity ||
	    !mapping->post_header_extent_authorized ||
	    !mapping->deterministic_zero_padding)
		return -ESTALE;
	/* One existing payload-only 4/8/16KiB lower image. The offset is
	 * relative to that image, NOT SWAPSPACE2 header page zero.
	 */
	if ((mapping->physical_extent_bytes != SWAPZ_BLOCK_BYTES &&
	     mapping->physical_extent_bytes != 2U * SWAPZ_BLOCK_BYTES &&
	     mapping->physical_extent_bytes != 4U * SWAPZ_BLOCK_BYTES) ||
	    mapping->compressed_payload_offset >= mapping->physical_extent_bytes ||
	    record->compressed_length >
	      mapping->physical_extent_bytes - mapping->compressed_payload_offset)
		return -EMSGSIZE;
	if (record->representation != SWAPZ_ZSWAP_IMPORT_REPRESENTATION ||
	    record->version != SWAPZ_ZSWAP_IMPORT_VERSION ||
	    record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC ||
	    record->dictionary_id || !record->stored_eviction ||
	    !record->immutable_owned_copy)
		return -EOPNOTSUPP;
	if (!record->compressed_length ||
	    record->compressed_length > SWAPZ_MAX_COMPRESSED ||
	    record->decoded_length != SWAPZ_BLOCK_BYTES ||
	    compressed_capacity < record->compressed_length)
		return -EMSGSIZE;
	for (index = 0; index < sizeof(record->original_sha256); ++index)
		digest_present |= record->original_sha256[index];
	if (!digest_present)
		return -ENODATA;
	if (swapz_crc32c_bytes(owned_compressed_bytes,
			      record->compressed_length) !=
	    record->compressed_crc32c)
		return -EBADMSG;
	transaction->record = *record;
	transaction->owned_compressed_bytes = owned_compressed_bytes;
	transaction->payload_capacity = compressed_capacity;
	transaction->physical_extent_bytes = mapping->physical_extent_bytes;
	transaction->compressed_payload_offset = mapping->compressed_payload_offset;
	transaction->phase = SWAPZ_ZSWAP_ADMISSION_PREPARED;
	return 0;
#else
	(void)transaction;
	(void)mapping;
	(void)record;
	(void)owned_compressed_bytes;
	(void)compressed_capacity;
	return -EOPNOTSUPP;
#endif
}

static inline int swapz_zswap_admission_lower_write_done(
		struct swapz_zswap_admission_transaction *transaction,
		int lower_error, swapz_u32 actual_written_bytes)
{
	if (!transaction || transaction->phase !=
	    SWAPZ_ZSWAP_ADMISSION_PREPARED || transaction->teardown_started)
		return -ESTALE;
	if (lower_error || actual_written_bytes !=
	    transaction->physical_extent_bytes)
		return -EIO;
	transaction->durable_bytes = actual_written_bytes;
	transaction->phase = SWAPZ_ZSWAP_ADMISSION_DURABLE;
	return 0;
}

static inline int swapz_zswap_admission_publish_ram_mapping(
		struct swapz_zswap_admission_transaction *transaction,
		swapz_u64 current_dm_logical, swapz_u64 current_dm_generation,
		swapz_u64 current_gc_epoch)
{
	if (!transaction || transaction->phase != SWAPZ_ZSWAP_ADMISSION_DURABLE ||
	    transaction->teardown_started ||
	    transaction->durable_bytes != transaction->physical_extent_bytes ||
	    current_dm_logical != transaction->record.logical_page ||
	    current_dm_generation != transaction->record.generation ||
	    current_gc_epoch != transaction->record.gc_epoch)
		return -ESTALE;
	transaction->phase = SWAPZ_ZSWAP_ADMISSION_MAPPED;
	return 0;
}

static inline int swapz_zswap_admission_upper_write_ack(
		struct swapz_zswap_admission_transaction *transaction)
{
	if (!transaction || transaction->phase != SWAPZ_ZSWAP_ADMISSION_MAPPED ||
	    transaction->teardown_started || transaction->upper_write_ack_count)
		return -ESTALE;
	transaction->upper_write_ack_count = 1U;
	transaction->phase = SWAPZ_ZSWAP_ADMISSION_ACKED;
	return 0;
}

/* Caller already owns a committed lower READ, its current RAM mapping and
 * two disjoint output buffers. No partial decoded bytes reach upper READ on
 * error; the imported decoder copies only after LZ4+CRC32C+SHA256 success.
 */
static inline int swapz_zswap_admission_read_4096(
		const struct swapz_zswap_admission_transaction *transaction,
		swapz_u64 current_dm_logical, swapz_u64 current_dm_generation,
		swapz_u64 current_gc_epoch, const swapz_u8 *lower_bytes,
		swapz_u32 actual_lower_extent_bytes, int lower_read_error,
		swapz_u8 *scratch, swapz_u8 *output,
		const swapz_u8 *independent_original_page)
{
	struct swapz_zswap_import_read_authority authority;

	if (!transaction || transaction->phase != SWAPZ_ZSWAP_ADMISSION_ACKED ||
	    transaction->teardown_started ||
	    transaction->upper_write_ack_count != 1U ||
	    current_dm_logical != transaction->record.logical_page ||
	    current_dm_generation != transaction->record.generation ||
	    current_gc_epoch != transaction->record.gc_epoch)
		return -ESTALE;
	if (lower_read_error || actual_lower_extent_bytes !=
	    transaction->physical_extent_bytes)
		return -EIO;
	authority = (struct swapz_zswap_import_read_authority) {
		.logical_page = transaction->record.logical_page,
		.generation = transaction->record.generation,
		.stored_entry_identity = transaction->record.stored_entry_identity,
		.store_generation = transaction->record.store_generation,
		.gc_epoch = transaction->record.gc_epoch,
		.actual_lower_read_bytes = transaction->record.compressed_length,
		.mapping_published_after_durable_write = 1U,
		.foreground_write_committed_once = 1U,
		.upper_write_ack_count = 1U,
		.current_owned_ram_session = 1U,
	};
	return swapz_zswap_import_decode(
		&transaction->record, &authority, lower_bytes,
		transaction->record.compressed_length, scratch, SWAPZ_BLOCK_BYTES,
		output, SWAPZ_BLOCK_BYTES, independent_original_page);
}

static inline void swapz_zswap_admission_invalidate(
		struct swapz_zswap_admission_transaction *transaction)
{
	if (!transaction)
		return;
	transaction->teardown_started = 1U;
	transaction->phase = SWAPZ_ZSWAP_ADMISSION_DISCARDED;
	/* Caller retains ownership of source buffer and frees it only after
	 * every callback is quiescent. Never free a borrowed pointer here.
	 */
}

#endif /* SWAPZ_ZSWAP_IMPORT_ADMISSION_H */
