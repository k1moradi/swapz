// SPDX-License-Identifier: GPL-2.0-only
/*
 * Host-executed original Linux LZO1X/LZ4 wire-format compatibility and
 * *actual product* dormant decode with a separately owned reader lease.
 * liblzo2 is the userland ABI-compatible LZO source, NOT pinned kernel code.
 * Native pinned original kernel symbol/provider provenance is a separate job.
 * No real zswap source pool, module unload, durability, BIO or upper ACK.
 */
#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1
#define SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST 1
#define SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST 1
#include "zswap-import-decoder-owner.h"

#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "ROUND066_DECODER_OWNER_FIRST_ERROR line=%d\n", __LINE__); \
	return 1; \
} } while (0)

struct close_attempt {
	struct swapz_zswap_import_decoder_owner *owner;
	atomic_int started;
	atomic_int finished;
	int result;
};

static void *close_owner_thread(void *context)
{
	struct close_attempt *attempt = context;

	atomic_store_explicit(&attempt->started, 1, memory_order_release);
	attempt->result = swapz_zswap_import_decoder_owner_close_and_drain(
		attempt->owner);
	atomic_store_explicit(&attempt->finished, 1, memory_order_release);
	return NULL;
}

static int wait_until_closing(struct swapz_zswap_import_decoder_owner *owner)
{
	for (unsigned int iteration = 0; iteration < 2000000U; ++iteration) {
		int closing;

		if (pthread_mutex_lock(&owner->lock))
			return -1;
		closing = owner->closing;
		pthread_mutex_unlock(&owner->lock);
		if (closing)
			return 0;
		sched_yield();
	}
	return -1;
}

static void destroy_closed_owner(struct swapz_zswap_import_decoder_owner *owner)
{
	pthread_cond_destroy(&owner->drained);
	pthread_mutex_destroy(&owner->lock);
}

static int check_profile(swapz_u8 codec)
{
	struct swapz_zswap_import_decoder_owner owner;
	struct swapz_zswap_import_decoder_lease lease = {0};
	struct swapz_zswap_import_decoder_lease extra_lease = {0};
	struct swapz_zswap_import_record record = {0};
	struct swapz_zswap_import_read_authority authority = {0};
	struct close_attempt attempt = {0};
	pthread_t close_thread;
	swapz_u8 original_page[SWAPZ_BLOCK_BYTES];
	swapz_u8 sealed[SWAPZ_BLOCK_BYTES + 512U];
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	swapz_u8 sentinel[SWAPZ_BLOCK_BYTES];
	swapz_u8 lzo_workmem[65536U] = {0};
	swapz_u8 *source_pool_buffer;
	size_t compressed_length = sizeof(sealed);
	int compressed;
	int decoded;

	for (unsigned int position = 0; position < SWAPZ_BLOCK_BYTES; ++position)
		original_page[position] = (swapz_u8)((position / 64U) % 4U);

	source_pool_buffer = malloc(sizeof(sealed));
	CHECK(source_pool_buffer != NULL);
	if (codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) {
		CHECK(lzo1x_1_compress(original_page, SWAPZ_BLOCK_BYTES,
			source_pool_buffer, &compressed_length,
			lzo_workmem) == LZO_E_OK);
	} else {
		compressed = LZ4_compress_default((const char *)original_page,
			(char *)source_pool_buffer, SWAPZ_BLOCK_BYTES,
			(int)sizeof(sealed));
		CHECK(compressed > 0);
		compressed_length = (size_t)compressed;
	}
	CHECK(compressed_length > 0 && compressed_length <= SWAPZ_MAX_COMPRESSED);
	memcpy(sealed, source_pool_buffer, compressed_length);
	memset(source_pool_buffer, 0x7e, sizeof(sealed));
	free(source_pool_buffer);
	/* After this point the original source/pool buffer no longer exists. */

	record.logical_page = 9U;
	record.generation = 10U;
	record.stored_entry_identity = 11U;
	record.store_generation = 12U;
	record.gc_epoch = 13U;
	record.compressed_length = (swapz_u32)compressed_length;
	record.decoded_length = SWAPZ_BLOCK_BYTES;
	record.compressed_crc32c = swapz_crc32c_bytes(sealed,
		(swapz_u32)compressed_length);
	CHECK(SHA256(original_page, SWAPZ_BLOCK_BYTES,
		record.original_sha256) != NULL);
	record.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION;
	record.codec = codec;
	record.version = SWAPZ_ZSWAP_IMPORT_VERSION;
	record.dictionary_id = 0U;
	record.stored_eviction = 1U;
	record.immutable_owned_copy = 1U;
	authority.logical_page = record.logical_page;
	authority.generation = record.generation;
	authority.stored_entry_identity = record.stored_entry_identity;
	authority.store_generation = record.store_generation;
	authority.gc_epoch = record.gc_epoch;
	authority.actual_lower_read_bytes = record.compressed_length;
	/* These are synthetic ABI inputs, NOT physical durable-write authority. */
	authority.mapping_published_after_durable_write = 1U;
	authority.foreground_write_committed_once = 1U;
	authority.upper_write_ack_count = 1U;
	authority.current_owned_ram_session = 1U;

	CHECK(swapz_zswap_import_decoder_owner_init(&owner, codec,
		record.version) == 0);
	CHECK(swapz_zswap_import_decoder_owner_get(&owner, &lease) == 0);
	CHECK(swapz_zswap_import_decoder_owner_get(&owner, &lease) == -EBUSY);
	CHECK(swapz_zswap_import_decoder_owner_decode(NULL, &record,
		&authority, sealed, record.compressed_length, scratch,
		SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES,
		original_page) == -EINVAL);
	memset(sentinel, 0xa7, sizeof(sentinel));
	memcpy(output, sentinel, sizeof(output));
#define DECODE() swapz_zswap_import_decoder_owner_decode(&lease, &record, \
	&authority, sealed, record.compressed_length, scratch, \
	SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES, original_page)
	decoded = DECODE();
	CHECK(decoded == 0);
	CHECK(memcmp(output, original_page, SWAPZ_BLOCK_BYTES) == 0);
	memcpy(output, sentinel, sizeof(output));
	record.version++;
	CHECK(DECODE() == -EOPNOTSUPP);
	record.version--;
	CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
	record.codec = codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC ?
		SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC : SWAPZ_ZSWAP_IMPORT_LZ4_CODEC;
	CHECK(DECODE() == -EOPNOTSUPP);
	record.codec = codec;
	CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
	record.original_sha256[0] ^= 0xffU;
	CHECK(DECODE() == -EBADMSG);
	record.original_sha256[0] ^= 0xffU;
	CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
	record.compressed_crc32c ^= 1U;
	CHECK(DECODE() == -EBADMSG);
	record.compressed_crc32c ^= 1U;
	CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
	authority.actual_lower_read_bytes--;
	CHECK(DECODE() == -EIO);
	authority.actual_lower_read_bytes++;
	CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
	/* Distinguish a valid CRC over malformed, too-short native compressed
	 * input from a CRC mismatch: the ORIGINAL selected decoder must reject. */
	{
		const swapz_u32 saved_length = record.compressed_length;
		const swapz_u32 saved_crc32c = record.compressed_crc32c;

		record.compressed_length = 1U;
		record.compressed_crc32c = swapz_crc32c_bytes(sealed, 1U);
		authority.actual_lower_read_bytes = 1U;
		CHECK(DECODE() == -EBADMSG);
		CHECK(memcmp(output, sentinel, sizeof(output)) == 0);
		record.compressed_length = saved_length;
		record.compressed_crc32c = saved_crc32c;
		authority.actual_lower_read_bytes = saved_length;
	}
	CHECK(swapz_zswap_import_decoder_owner_decode(&lease, &record,
		&authority, sealed, record.compressed_length, scratch,
		SWAPZ_BLOCK_BYTES, scratch, SWAPZ_BLOCK_BYTES,
		original_page) == -EINVAL);
	/* End-to-end provider decoding is still allowed under an acquired lease
	 * after a concurrent close starts, but close must wait for this reader. */
	attempt.owner = &owner;
	CHECK(pthread_create(&close_thread, NULL, close_owner_thread, &attempt) == 0);
	CHECK(wait_until_closing(&owner) == 0);
	CHECK(atomic_load_explicit(&attempt.finished, memory_order_acquire) == 0);
	CHECK(swapz_zswap_import_decoder_owner_get(&owner, &extra_lease) == -ESHUTDOWN);
	CHECK(DECODE() == 0);
	CHECK(memcmp(output, original_page, SWAPZ_BLOCK_BYTES) == 0);
	CHECK(swapz_zswap_import_decoder_owner_put(&lease) == 0);
	CHECK(swapz_zswap_import_decoder_owner_put(&lease) == -EALREADY);
	CHECK(pthread_join(close_thread, NULL) == 0);
	CHECK(attempt.result == 0);
	CHECK(atomic_load_explicit(&attempt.finished, memory_order_acquire) == 1);
	CHECK(swapz_zswap_import_decoder_owner_get(&owner, &lease) == -ESHUTDOWN);
	CHECK(swapz_zswap_import_decoder_owner_decode(&lease, &record,
		&authority, sealed, record.compressed_length, scratch,
		SWAPZ_BLOCK_BYTES, output, SWAPZ_BLOCK_BYTES,
		original_page) == -EINVAL);
	CHECK(swapz_zswap_import_decoder_owner_close_and_drain(&owner) == 0);
	destroy_closed_owner(&owner);
	return 0;
#undef DECODE
}

static int check_overflow_and_bad_initialization(void)
{
	struct swapz_zswap_import_decoder_owner owner;
	struct swapz_zswap_import_decoder_lease lease = {0};

	CHECK(swapz_zswap_import_decoder_owner_init(NULL,
		SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION) == -EINVAL);
	CHECK(swapz_zswap_import_decoder_owner_init(&owner,
		0xffU, SWAPZ_ZSWAP_IMPORT_VERSION) == -EOPNOTSUPP);
	CHECK(swapz_zswap_import_decoder_owner_init(&owner,
		SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 0xffU) == -EOPNOTSUPP);
	CHECK(swapz_zswap_import_decoder_owner_init(&owner,
		SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION) == 0);
	CHECK(pthread_mutex_lock(&owner.lock) == 0);
	owner.active_readers = UINT_MAX;
	CHECK(pthread_mutex_unlock(&owner.lock) == 0);
	CHECK(swapz_zswap_import_decoder_owner_get(&owner, &lease) == -EOVERFLOW);
	CHECK(lease.owner == NULL);
	CHECK(pthread_mutex_lock(&owner.lock) == 0);
	owner.active_readers = 0U;
	CHECK(pthread_mutex_unlock(&owner.lock) == 0);
	CHECK(swapz_zswap_import_decoder_owner_close_and_drain(&owner) == 0);
	destroy_closed_owner(&owner);
	return 0;
}

int main(void)
{
	if (check_overflow_and_bad_initialization() ||
	    check_profile(SWAPZ_ZSWAP_IMPORT_LZ4_CODEC) ||
	    check_profile(SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC))
		return 1;
	printf("ROUND066_DECODER_OWNER_HOST_PASS profiles=2 "
	       "source_pool_retired_simulated=2 close_drain=2 "
	       "exact_original_pages=2 denied_new_read_after_close=2 "
	       "native_provider_runtime_unload=NOT_TESTED auth=0\n");
	return 0;
}
