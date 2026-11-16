/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round023 independent host-only cross-ABI fixture.
 * The Python driver injects the unchanged, compile-disabled Round022 producer
 * C function bodies at the marker below. Only the test translation unit
 * removes the #if 0 wrapper; the repository/kernel remain DISABLED.
 *
 * The adapter's slot->DM map and all I/O receipts are MOCK/UNTRUSTED. They
 * cannot establish a kernel MM/BIO transport, lower durability or real ACK.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#include "zswap-import-codec.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <lz4.h>
#include <openssl/sha.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PAGE_SIZE 4096U
#define GFP_KERNEL 0
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef struct { u64 val; } swp_entry_t;
typedef struct { atomic_int value; } atomic_t;

struct folio { bool locked; };
struct zswap_pool { const char *tfm_name; void *zs_pool; };
struct zswap_entry {
	swp_entry_t swpentry;
	unsigned int length;
	void *handle;
	struct zswap_pool *pool;
};
struct xarray { const struct zswap_entry *entry; };
struct scatterlist { const u8 *data; };
static struct xarray mock_tree;
static unsigned int allocations, releases;

static bool folio_test_locked(const struct folio *folio)
{
	return folio->locked;
}
static struct xarray *swap_zswap_tree(swp_entry_t slot)
{
	(void)slot;
	return &mock_tree;
}
static unsigned long swp_offset(swp_entry_t slot)
{
	return (unsigned long)slot.val;
}
static const struct zswap_entry *xa_load(const struct xarray *tree,
					unsigned long offset)
{
	(void)offset;
	return tree->entry;
}
static struct zswap_pool *zswap_entry_pool(struct zswap_entry *entry)
{
	return entry->pool;
}
static void *kmalloc(size_t length, int flags)
{
	void *memory;
	(void)flags;
	memory = malloc(length);
	if (memory)
		++allocations;
	return memory;
}
static void kfree(void *memory)
{
	if (memory) {
		++releases;
		free(memory);
	}
}
static int atomic_read(const atomic_t *value)
{
	return atomic_load_explicit(&value->value, memory_order_acquire);
}
static void atomic_set(atomic_t *value, int next)
{
	atomic_store_explicit(&value->value, next, memory_order_release);
}
static int atomic_cmpxchg(atomic_t *value, int expected, int replacement)
{
	atomic_compare_exchange_strong_explicit(
		&value->value, &expected, replacement,
		memory_order_acq_rel, memory_order_acquire);
	return expected;
}
static void zs_obj_read_sg_begin(void *pool, void *handle,
				struct scatterlist list[2], unsigned int length)
{
	(void)pool;
	(void)length;
	list[0].data = handle;
	list[1].data = NULL;
}
static void memcpy_from_sglist(void *destination, const struct scatterlist *list,
			       unsigned int offset, unsigned int length)
{
	memcpy(destination, list[0].data + offset, length);
}
static void zs_obj_read_sg_end(void *pool, void *handle)
{
	(void)pool;
	(void)handle;
}
static void sha256(const u8 *source, size_t length, u8 destination[32])
{
	assert(SHA256(source, length, destination) == destination);
}

/* Independently implemented reflected Castagnoli polynomial. Linux crc32c()
 * returns a running state WITHOUT the final XOR. The producer applies both
 * the ~0U initial state and ~ final XOR; never use IEEE 0xedb88320 here. */
static u32 crc32c(u32 state, const void *source, size_t length)
{
	const u8 *bytes = source;
	for (size_t index = 0; index < length; ++index) {
		state ^= bytes[index];
		for (unsigned int bit = 0; bit < 8U; ++bit)
			state = (state >> 1) ^
				((state & 1U) ? 0x82f63b78U : 0U);
	}
	return state;
}
static u32 crc32_ieee_bytes(const void *source, size_t length)
{
	const u8 *bytes = source;
	u32 state = ~0U;
	for (size_t index = 0; index < length; ++index) {
		state ^= bytes[index];
		for (unsigned int bit = 0; bit < 8U; ++bit)
			state = (state >> 1) ^
				((state & 1U) ? 0xedb88320U : 0U);
	}
	return ~state;
}

/* ROUND023_EXACT_DISABLED_PRODUCER_FUNCTIONS */

/* MOCK/UNTRUSTED identity binding: no real kernel slot->DM page API exists.
 * The two ID domains and GC epoch are mapped only by these fixture fields,
 * never by casting either struct or assuming enum/numeric identity. */
struct round023_mock_mapping {
	u64 source_slot;
	u64 source_store_generation;
	u64 dm_logical_page;
	u64 dm_generation;
	u64 independent_entry_token;
	u64 current_gc_epoch;
	bool mock_authenticated;
	bool single_source_no_clone_or_split;
	bool mock_lower_write_complete;
	bool mock_publication_after_lower_write;
	bool mock_teardown_started;
	unsigned int mock_upper_write_acks;
};

static int round023_mock_adapt(
	const struct zswap_swapz_owned_payload *source,
	const struct zswap_swapz_stored_proof *stored,
	const struct round023_mock_mapping *binding,
	struct swapz_zswap_import_record *destination,
	struct swapz_zswap_import_read_authority *authority)
{
	if (!source || !stored || !binding || !destination || !authority ||
	    !binding->mock_authenticated ||
	    !binding->single_source_no_clone_or_split ||
	    !binding->mock_lower_write_complete ||
	    !binding->mock_publication_after_lower_write ||
	    binding->mock_teardown_started ||
	    binding->mock_upper_write_acks != 1U ||
	    !binding->dm_logical_page || !binding->dm_generation ||
	    !binding->independent_entry_token || !binding->current_gc_epoch)
		return -EACCES;
	if (stored->self != stored || !stored->admitted ||
	    stored->slot.val != binding->source_slot ||
	    stored->generation != binding->source_store_generation ||
	    source->self != source || source->entry_identity.val != binding->source_slot ||
	    source->slot_generation != binding->source_store_generation ||
	    atomic_read(&source->owner_state) != ZSWAP_SWAPZ_PAYLOAD_SUBMITTED ||
	    !source->owned_bytes || !source->owned_allocation ||
	    source->owned_bytes != source->owned_allocation ||
	    !source->semantic_stored_writeback || !source->representation_compressed ||
	    source->representation != ZSWAP_SWAPZ_REPR_ZSWAP_LZ4_V1 ||
	    source->codec != ZSWAP_SWAPZ_CODEC_LZ4 ||
	    source->representation_version != ZSWAP_SWAPZ_RECORD_VERSION ||
	    !zswap_swapz_owned_payload_is_valid(source))
		return -ESTALE;
	memset(destination, 0, sizeof(*destination));
	*destination = (struct swapz_zswap_import_record) {
		.logical_page = binding->dm_logical_page,
		.generation = binding->dm_generation,
		.stored_entry_identity = binding->independent_entry_token,
		.store_generation = source->slot_generation,
		.gc_epoch = binding->current_gc_epoch,
		.compressed_length = source->compressed_length,
		.decoded_length = source->decoded_length,
		/* Source checksum is forwarded, NEVER repaired by the adapter. */
		.compressed_crc32c = source->payload_crc32c,
		.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
		.codec = SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
		.version = SWAPZ_ZSWAP_IMPORT_VERSION,
		.dictionary_id = 0,
		.stored_eviction = (u8)source->semantic_stored_writeback,
		.immutable_owned_copy = (u8)source->representation_compressed,
	};
	memcpy(destination->original_sha256, source->original_sha256, 32U);
	memset(authority, 0, sizeof(*authority));
	*authority = (struct swapz_zswap_import_read_authority) {
		.logical_page = binding->dm_logical_page,
		.generation = binding->dm_generation,
		.stored_entry_identity = binding->independent_entry_token,
		.store_generation = source->slot_generation,
		.gc_epoch = binding->current_gc_epoch,
		.actual_lower_read_bytes = source->compressed_length,
		.mapping_published_after_durable_write =
			(u8)binding->mock_publication_after_lower_write,
		.foreground_write_committed_once = (u8)binding->mock_lower_write_complete,
		.upper_write_ack_count = (u8)binding->mock_upper_write_acks,
		.current_owned_ram_session = 1,
	};
	return 0;
}

static u8 original[PAGE_SIZE], zpool_storage[PAGE_SIZE];
static u8 synthetic_lower_read[PAGE_SIZE];
static u8 scratch[PAGE_SIZE], output[PAGE_SIZE];
static unsigned int refused_cases;

static void reset_output(void)
{
	memset(output, 0xa5, sizeof(output));
}
static int decode(const struct swapz_zswap_import_record *record,
		  const struct swapz_zswap_import_read_authority *authority)
{
	return swapz_zswap_import_decode(
		record, authority, synthetic_lower_read, PAGE_SIZE,
		scratch, PAGE_SIZE, output, PAGE_SIZE, original);
}
static void denied(int result)
{
	assert(result < 0);
	for (size_t index = 0; index < sizeof(output); ++index)
		assert(output[index] == 0xa5);
	++refused_cases;
}
#define DENY_FIELD(object, field, incorrect, record, authority) do { \
	__typeof__((object).field) old_value = (object).field; \
	(object).field = (incorrect); \
	reset_output(); denied(decode((record), (authority))); \
	(object).field = old_value; \
} while (0)

int main(void)
{
	struct zswap_pool pool = { .tfm_name = "lz4", .zs_pool = NULL };
	struct folio locked = { .locked = true };
	struct zswap_entry entry = {
		.swpentry = { .val = 0x12345U }, .pool = &pool,
		.handle = zpool_storage,
	};
	struct zswap_swapz_stored_proof proof = { 0 };
	struct zswap_swapz_owned_payload source = { 0 };
	const swp_entry_t slot = entry.swpentry;
	const u64 store_generation = 29U;
	struct round023_mock_mapping binding = {
		.source_slot = slot.val,
		.source_store_generation = store_generation,
		.dm_logical_page = 17U,
		.dm_generation = 19U,
		.independent_entry_token = 23U,
		.current_gc_epoch = 31U,
		.mock_authenticated = true,
		.single_source_no_clone_or_split = true,
		.mock_lower_write_complete = true,
		.mock_publication_after_lower_write = true,
		.mock_upper_write_acks = 1U,
	};
	struct swapz_zswap_import_record record;
	struct swapz_zswap_import_read_authority authority;
	int length;

	assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U);
	assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U);
	/* Real LZ4 block, not a LZ4 frame and not a simulated compressor. */
	for (unsigned int index = 0; index < PAGE_SIZE; ++index)
		original[index] = (u8)(index / 64U);
	length = LZ4_compress_default((const char *)original,
			(char *)zpool_storage, (int)PAGE_SIZE, (int)PAGE_SIZE);
	assert(length > 0 && length <= 3568);
	entry.length = (unsigned int)length;
	mock_tree.entry = &entry;
	/* These are mocked credentials, never genuine stored zswap admission. */
	mock_tree.entry = NULL;
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, store_generation, &locked,
		original, sizeof(original)) == -ESTALE);
	mock_tree.entry = &entry;
	locked.locked = false;
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, store_generation, &locked,
		original, sizeof(original)) == -EINVAL);
	locked.locked = true;
	pool.tfm_name = "zstd";
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, store_generation, &locked,
		original, sizeof(original)) == -EOPNOTSUPP);
	pool.tfm_name = "lz4";
	entry.length = 3569U;
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, store_generation, &locked,
		original, sizeof(original)) == -EMSGSIZE);
	entry.length = (unsigned int)length;
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, 0U, &locked,
		original, sizeof(original)) == -EINVAL);
	assert(zswap_swapz_bind_stored_entry(
		&proof, &entry, slot, store_generation, &locked,
		original, sizeof(original)) == 0);
	assert(zswap_swapz_capture_owned_payload(
		&source, &entry, slot, &locked, &proof,
		store_generation + 1U) == -ESTALE);
	mock_tree.entry = NULL;
	assert(zswap_swapz_capture_owned_payload(
		&source, &entry, slot, &locked, &proof,
		store_generation) == -ENOENT);
	mock_tree.entry = &entry;
	assert(zswap_swapz_capture_owned_payload(
		&source, &entry, slot, &locked, &proof, store_generation) == 0);
	assert(source.owned_bytes != zpool_storage);
#ifndef ROUND023_EXPECT_WRONG_PRODUCER_CRC
	assert(source.payload_crc32c == ~crc32c(~0U,
			source.owned_bytes, source.compressed_length));
#else
	assert(source.payload_crc32c != swapz_crc32c_bytes(
			source.owned_bytes, source.compressed_length));
#endif
#ifdef ROUND023_EXPECT_WRONG_PRODUCER_CRC
	assert(source.payload_crc32c != swapz_crc32c_bytes(
		source.owned_bytes, source.compressed_length));
#else
	assert(source.payload_crc32c == swapz_crc32c_bytes(
		source.owned_bytes, source.compressed_length));
#endif
	assert(~crc32c(0U, source.owned_bytes, source.compressed_length) !=
			swapz_crc32c_bytes(source.owned_bytes,
						 source.compressed_length));
	assert(crc32_ieee_bytes(source.owned_bytes,
			       source.compressed_length) !=
			swapz_crc32c_bytes(source.owned_bytes,
						 source.compressed_length));
	/* No borrowed pool bytes survive; overwriting the fake pool cannot
	 * corrupt the genuinely owned copy that is submitted below. */
	memcpy(synthetic_lower_read, source.owned_bytes, source.compressed_length);
	memset(zpool_storage, 0xee, sizeof(zpool_storage));
	/* Owned bytes are checked again when the single submitter acquires
	 * CHECKING; neither a corrupted owned buffer nor a descriptor clone
	 * may advance to SUBMITTED. */
	((u8 *)source.owned_allocation)[0] ^= 1U;
	assert(!zswap_swapz_owned_payload_submit(&source));
	assert(atomic_read(&source.owner_state) == ZSWAP_SWAPZ_PAYLOAD_OWNED);
	((u8 *)source.owned_allocation)[0] ^= 1U;
	assert(zswap_swapz_owned_payload_submit(&source));
	assert(!zswap_swapz_owned_payload_submit(&source));
	assert(!zswap_swapz_owned_payload_abort(&source));
	assert(round023_mock_adapt(&source, &proof, &binding,
				  &record, &authority) == 0);
	assert(record.representation != (u8)source.representation);
	assert(record.generation != source.slot_generation);
	assert(record.logical_page != source.entry_identity.val);
	assert(record.compressed_crc32c == source.payload_crc32c);

#ifdef ROUND023_EXPECT_WRONG_PRODUCER_CRC
	reset_output();
	denied(decode(&record, &authority));
	puts("ROUND023_WRONG_PRODUCER_CRC_REJECTED_SOURCE_ONLY");
#else
	reset_output();
	assert(decode(&record, &authority) == 0);
	assert(memcmp(output, original, PAGE_SIZE) == 0);
	assert(memcmp(record.original_sha256, proof.original_sha256, 32U) == 0);
	/* Bad CRC32-IEEE, wrong initial seed, length and unsupported codecs. */
	DENY_FIELD(record, compressed_crc32c,
		   crc32_ieee_bytes(synthetic_lower_read, (unsigned)length),
		   &record, &authority);
	DENY_FIELD(record, compressed_crc32c,
		   ~crc32c(0U, synthetic_lower_read, (size_t)length),
		   &record, &authority);
	DENY_FIELD(record, compressed_length, 0U, &record, &authority);
	DENY_FIELD(record, compressed_length, 3569U, &record, &authority);
	DENY_FIELD(record, decoded_length, 4088U, &record, &authority);
	DENY_FIELD(record, representation, 1U, &record, &authority);
	DENY_FIELD(record, codec, 2U, &record, &authority);
	DENY_FIELD(record, version, 2U, &record, &authority);
	DENY_FIELD(record, dictionary_id, 1U, &record, &authority);
	DENY_FIELD(record, stored_eviction, 0U, &record, &authority);
	DENY_FIELD(record, immutable_owned_copy, 0U, &record, &authority);
	DENY_FIELD(record, logical_page, 18U, &record, &authority);
	DENY_FIELD(record, generation, 18U, &record, &authority);
	DENY_FIELD(record, stored_entry_identity, 24U, &record, &authority);
	DENY_FIELD(record, store_generation, 30U, &record, &authority);
	DENY_FIELD(record, gc_epoch, 32U, &record, &authority);
	DENY_FIELD(authority, logical_page, 18U, &record, &authority);
	DENY_FIELD(authority, generation, 18U, &record, &authority);
	DENY_FIELD(authority, stored_entry_identity, 24U, &record, &authority);
	DENY_FIELD(authority, store_generation, 30U, &record, &authority);
	DENY_FIELD(authority, gc_epoch, 32U, &record, &authority);
	DENY_FIELD(authority, actual_lower_read_bytes,
		   (swapz_u32)(length - 1), &record, &authority);
	DENY_FIELD(authority, lower_read_error, -EIO, &record, &authority);
	DENY_FIELD(authority, mapping_published_after_durable_write,
		   0U, &record, &authority);
	DENY_FIELD(authority, foreground_write_committed_once,
		   0U, &record, &authority);
	DENY_FIELD(authority, upper_write_ack_count, 0U, &record, &authority);
	DENY_FIELD(authority, upper_write_ack_count, 2U, &record, &authority);
	DENY_FIELD(authority, current_owned_ram_session,
		   0U, &record, &authority);
	DENY_FIELD(authority, teardown_started, 1U, &record, &authority);
	DENY_FIELD(authority, upper_read_ack_count, 1U, &record, &authority);
	record.original_sha256[0] ^= 1U;
	reset_output();
	denied(decode(&record, &authority));
	record.original_sha256[0] ^= 1U;
	original[0] ^= 1U;
	reset_output();
	denied(decode(&record, &authority));
	original[0] ^= 1U;
	synthetic_lower_read[0] ^= 1U;
	reset_output();
	denied(decode(&record, &authority));
	synthetic_lower_read[0] ^= 1U;
	/* A mutation with a freshly recomputed CRC still fails the independent
	 * original-page digest, not merely the compressed checksum. */
	synthetic_lower_read[0] ^= 1U;
	const swapz_u32 damaged_crc = swapz_crc32c_bytes(
		synthetic_lower_read, record.compressed_length);
	DENY_FIELD(record, compressed_crc32c, damaged_crc, &record, &authority);
	synthetic_lower_read[0] ^= 1U;
	const u8 lz4_frame_magic[4] = { 0x04U, 0x22U, 0x4dU, 0x18U };
	memcpy(synthetic_lower_read, lz4_frame_magic, sizeof(lz4_frame_magic));
	record.compressed_length = 4U;
	record.compressed_crc32c = swapz_crc32c_bytes(synthetic_lower_read, 4U);
	authority.actual_lower_read_bytes = 4U;
	reset_output();
	denied(decode(&record, &authority));
	/* Restore the exact independent lower read for ownership/alias checks. */
	record.compressed_length = (swapz_u32)length;
	record.compressed_crc32c = source.payload_crc32c;
	authority.actual_lower_read_bytes = (swapz_u32)length;
	memcpy(synthetic_lower_read, source.owned_bytes, source.compressed_length);
	reset_output();
	denied(swapz_zswap_import_decode(
		&record, &authority, synthetic_lower_read, PAGE_SIZE,
		output, PAGE_SIZE, output, PAGE_SIZE, original));
	reset_output();
	denied(swapz_zswap_import_decode(
		&record, &authority, synthetic_lower_read, PAGE_SIZE,
		synthetic_lower_read, PAGE_SIZE, output, PAGE_SIZE, original));
	for (unsigned int item = 0; item < 9U; ++item) {
		struct round023_mock_mapping changed = binding;
		switch (item) {
		case 0: changed.mock_authenticated = false; break;
		case 1: changed.source_slot++; break;
		case 2: changed.source_store_generation++; break;
		case 3: changed.current_gc_epoch = 0U; break;
		case 4: changed.dm_generation = 0U; break;
		case 5: changed.single_source_no_clone_or_split = false; break;
		case 6: changed.mock_lower_write_complete = false; break;
		case 7: changed.mock_upper_write_acks = 2U; break;
		default: changed.mock_teardown_started = true; break;
		}
		struct swapz_zswap_import_record ignored_record;
		struct swapz_zswap_import_read_authority ignored_authority;
		assert(round023_mock_adapt(&source, &proof, &changed,
					  &ignored_record, &ignored_authority) < 0);
	}
	{
		struct zswap_swapz_owned_payload cloned = source;
		assert(!zswap_swapz_owned_payload_submit(&cloned));
		assert(!zswap_swapz_owned_payload_finish(&cloned, 0));
	}
#endif
	assert(zswap_swapz_owned_payload_finish(&source, 0));
	assert(!zswap_swapz_owned_payload_finish(&source, 0));
	assert(!zswap_swapz_owned_payload_abort(&source));
	assert(!zswap_swapz_owned_payload_submit(&source));
	assert(round023_mock_adapt(&source, &proof, &binding,
				  &record, &authority) < 0);
	assert(allocations == releases);
#ifdef ROUND023_EXPECT_WRONG_PRODUCER_CRC
	assert(refused_cases == 1U);
#else
	assert(refused_cases >= 35U);
#endif
	printf("ROUND023_CROSS_ABI_SOURCE_ONLY_PASS rejected=%u\n", refused_cases);
	return 0;
}
