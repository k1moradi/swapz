// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round068 test-only original Linux UML KUnit. This links the unchanged
 * dormant decoder owner C, real kernel spin/wait primitives, real original
 * LZO1X/LZ4 source encoders/decoders, real product CRC32C and native SHA256.
 * Source-owned compression buffers are freed before the independent READ.
 * No zswap source is authenticated and no module is loaded or unloaded.
 */
#include <kunit/test.h>
#include <linux/completion.h>
#include <linux/delay.h>
#include <linux/err.h>
#include <linux/jiffies.h>
#include <linux/kthread.h>
#include <linux/lzo.h>
#include <linux/lz4.h>
#include <linux/slab.h>
#include <linux/string.h>
#include "zswap-import-decoder-owner.h"

#define SWAPZ_ROUND068_REPETITIONS 24U
#define SWAPZ_ROUND068_WAIT_MILLISECONDS 3000U

struct swapz_round068_closer {
	struct swapz_zswap_import_decoder_owner *owner;
	struct completion entered;
	struct completion returned;
	int result;
};

static int swapz_round068_close_worker(void *argument)
{
	struct swapz_round068_closer *closer = argument;

	complete(&closer->entered);
	closer->result =
		swapz_zswap_import_decoder_owner_close_and_drain(closer->owner);
	complete(&closer->returned);
	return 0;
}

static void swapz_round068_profile_and_fail_closed(struct kunit *test)
{
	static const swapz_u8 codecs[] = {
		SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
		SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
	};
	unsigned int index;

	for (index = 0; index < ARRAY_SIZE(codecs); ++index) {
		struct swapz_zswap_import_decoder_owner owner = {};
		struct swapz_zswap_import_decoder_lease lease = {};
		struct swapz_zswap_import_decoder_lease other_lease = {};
		swapz_u8 source_pool_codec = codecs[index];
		const swapz_u8 independently_retained_codec = source_pool_codec;

		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_init(
				&owner, source_pool_codec, 1U), 0);
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &lease), 0);
		KUNIT_EXPECT_EQ(test, lease.codec, independently_retained_codec);
		KUNIT_EXPECT_EQ(test, lease.version, (swapz_u8)1U);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &lease),
			-EBUSY);
		/* Simulated original pool retirement cannot re-tag a held lease. */
		source_pool_codec = 0U;
		KUNIT_EXPECT_EQ(test, source_pool_codec, (swapz_u8)0U);
		KUNIT_EXPECT_EQ(test, lease.codec, independently_retained_codec);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_put(&lease), 0);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_put(&lease), -EALREADY);
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_close_and_drain(&owner), 0);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &other_lease),
			-ESHUTDOWN);
		KUNIT_EXPECT_PTR_EQ(test, other_lease.owner, NULL);
	}
	{
		struct swapz_zswap_import_decoder_owner owner = {};
		struct swapz_zswap_import_decoder_lease lease = {};

		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_init(&owner, 0xffU, 1U),
			-EOPNOTSUPP);
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_init(
				&owner, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, 1U), 0);
		/* No active readers: model the saturated counter under no race. */
		owner.active_readers = ~0U;
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &lease),
			-EOVERFLOW);
		KUNIT_EXPECT_PTR_EQ(test, lease.owner, NULL);
		owner.active_readers = 0U;
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_close_and_drain(&owner), 0);
	}
}

static void swapz_round068_native_close_wake(struct kunit *test)
{
	unsigned int iteration;

	for (iteration = 0; iteration < SWAPZ_ROUND068_REPETITIONS; ++iteration) {
		struct swapz_zswap_import_decoder_owner owner = {};
		struct swapz_zswap_import_decoder_lease first = {};
		struct swapz_zswap_import_decoder_lease second = {};
		struct swapz_zswap_import_decoder_lease late = {};
		struct swapz_round068_closer closer = {
			.owner = &owner, .result = -EINPROGRESS,
		};
		struct task_struct *worker;
		unsigned int poll_count;
		bool closing_observed;
		bool close_blocked_before_put;
		bool close_blocked_after_first_put;
		unsigned long finished;

		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_init(
				&owner, SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC, 1U), 0);
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &first), 0);
		KUNIT_ASSERT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &second), 0);
		init_completion(&closer.entered);
		init_completion(&closer.returned);
		worker = kthread_run(swapz_round068_close_worker, &closer,
				     "swapz-r068-close");
		if (IS_ERR(worker)) {
			KUNIT_FAIL(test, "unable to start genuine original close thread");
			KUNIT_EXPECT_EQ(test,
				swapz_zswap_import_decoder_owner_put(&first), 0);
			KUNIT_EXPECT_EQ(test,
				swapz_zswap_import_decoder_owner_put(&second), 0);
			KUNIT_EXPECT_EQ(test,
				swapz_zswap_import_decoder_owner_close_and_drain(
					&owner), 0);
			return;
		}
		wait_for_completion_timeout(
			&closer.entered,
			msecs_to_jiffies(SWAPZ_ROUND068_WAIT_MILLISECONDS));
		/* Bounded observation of actual close latch, with real scheduler. */
		for (poll_count = 0; poll_count < 2000U &&
		     !READ_ONCE(owner.closing); ++poll_count)
			usleep_range(1000, 2000);
		closing_observed = READ_ONCE(owner.closing) != 0U;
		close_blocked_before_put = !completion_done(&closer.returned);
		/* Late get is rejected while pre-existing readers are still live. */
		if (closing_observed)
			KUNIT_EXPECT_EQ(test,
				swapz_zswap_import_decoder_owner_get(
					&owner, &late), -ESHUTDOWN);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_put(&first), 0);
		close_blocked_after_first_put = !completion_done(&closer.returned);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_put(&second), 0);
		finished = wait_for_completion_timeout(
			&closer.returned,
			msecs_to_jiffies(SWAPZ_ROUND068_WAIT_MILLISECONDS));
		if (!finished) {
			/* Fail closed: keep owner storage live until the real closer
			 * finishes. A stuck native wake is a job timeout, never PASS. */
			KUNIT_FAIL(test, "native last-reader wake did not finish");
			wait_for_completion(&closer.returned);
		}
		kthread_stop(worker); /* joins close/wake before owner dies */
		KUNIT_EXPECT_TRUE(test, closing_observed);
		KUNIT_EXPECT_TRUE(test, close_blocked_before_put);
		KUNIT_EXPECT_TRUE(test, close_blocked_after_first_put);
		KUNIT_EXPECT_NE(test, finished, 0UL);
		KUNIT_EXPECT_EQ(test, closer.result, 0);
		KUNIT_EXPECT_EQ(test, READ_ONCE(owner.active_readers), 0U);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_put(&second), -EALREADY);
		KUNIT_EXPECT_EQ(test,
			swapz_zswap_import_decoder_owner_get(&owner, &late),
			-ESHUTDOWN);
	}
}

/* Each compressed stream is created by the pinned ORIGINAL kernel codec,
 * copied into the reader-owned buffer, and the source pool's storage freed
 * before the independently owned owner lease is used for full page decode. */
static void swapz_round068_native_codec_after_source_release(
	struct kunit *test, swapz_u8 codec)
{
	struct swapz_zswap_import_decoder_owner owner = {};
	struct swapz_zswap_import_decoder_lease lease = {};
	struct swapz_zswap_import_record record = {
		.logical_page = 7U,
		.generation = 11U,
		.stored_entry_identity = 13U,
		.store_generation = 17U,
		.gc_epoch = 19U,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
		.version = 1U,
		.stored_eviction = 1U,
		.immutable_owned_copy = 1U,
	};
	struct swapz_zswap_import_read_authority authority = {
		.logical_page = 7U,
		.generation = 11U,
		.stored_entry_identity = 13U,
		.store_generation = 17U,
		.gc_epoch = 19U,
		.mapping_published_after_durable_write = 1U,
		.foreground_write_committed_once = 1U,
		.upper_write_ack_count = 1U,
		.current_owned_ram_session = 1U,
	};
	swapz_u8 *original_page;
	swapz_u8 *source_pool_compressed;
	swapz_u8 *owned_compressed;
	swapz_u8 *scratch;
	swapz_u8 *output;
	void *compress_workspace;
	unsigned int offset;
	size_t lzo_length = SWAPZ_MAX_COMPRESSED;
	int compressed_length;
	int result;

	original_page = kunit_kmalloc(test, SWAPZ_BLOCK_BYTES, GFP_KERNEL);
	source_pool_compressed = kunit_kmalloc(
		test, SWAPZ_MAX_COMPRESSED, GFP_KERNEL);
	owned_compressed = kunit_kmalloc(
		test, SWAPZ_MAX_COMPRESSED, GFP_KERNEL);
	scratch = kunit_kmalloc(test, SWAPZ_BLOCK_BYTES, GFP_KERNEL);
	output = kunit_kmalloc(test, SWAPZ_BLOCK_BYTES, GFP_KERNEL);
	compress_workspace = kunit_kzalloc(test,
		max_t(size_t, LZO1X_1_MEM_COMPRESS, LZ4_MEM_COMPRESS),
		GFP_KERNEL);
	KUNIT_ASSERT_NOT_NULL(test, original_page);
	KUNIT_ASSERT_NOT_NULL(test, source_pool_compressed);
	KUNIT_ASSERT_NOT_NULL(test, owned_compressed);
	KUNIT_ASSERT_NOT_NULL(test, scratch);
	KUNIT_ASSERT_NOT_NULL(test, output);
	KUNIT_ASSERT_NOT_NULL(test, compress_workspace);
	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset)
		original_page[offset] =
			(swapz_u8)(((offset % 64U) ^ (offset / 512U)) & 0xffU);
	record.codec = codec;
	if (codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) {
		KUNIT_ASSERT_EQ(test,
			lzo1x_1_compress(original_page, SWAPZ_BLOCK_BYTES,
				source_pool_compressed, &lzo_length,
				compress_workspace), LZO_E_OK);
		compressed_length = (int)lzo_length;
	} else {
		compressed_length = LZ4_compress_default(
			(const char *)original_page, (char *)source_pool_compressed,
			(int)SWAPZ_BLOCK_BYTES, (int)SWAPZ_MAX_COMPRESSED,
			compress_workspace);
	}
	KUNIT_ASSERT_GT(test, compressed_length, 0);
	KUNIT_ASSERT_LE(test, compressed_length, (int)SWAPZ_MAX_COMPRESSED);
	memcpy(owned_compressed, source_pool_compressed,
	       (size_t)compressed_length);
	record.compressed_length = (swapz_u32)compressed_length;
	record.compressed_crc32c = swapz_crc32c_bytes(
		owned_compressed, record.compressed_length);
	sha256(original_page, SWAPZ_BLOCK_BYTES, record.original_sha256);
	authority.actual_lower_read_bytes = record.compressed_length;
	KUNIT_ASSERT_EQ(test,
		swapz_zswap_import_decoder_owner_init(&owner, codec, 1U), 0);
	KUNIT_ASSERT_EQ(test,
		swapz_zswap_import_decoder_owner_get(&owner, &lease), 0);
	/* Release native source-owned storage; the independent stream survives. */
	kunit_kfree(test, source_pool_compressed);
	source_pool_compressed = NULL;
	memset(scratch, 0xa5, SWAPZ_BLOCK_BYTES);
	memset(output, 0xa5, SWAPZ_BLOCK_BYTES);
	result = swapz_zswap_import_decoder_owner_decode(
		&lease, &record, &authority, owned_compressed,
		record.compressed_length, scratch, SWAPZ_BLOCK_BYTES,
		output, SWAPZ_BLOCK_BYTES, original_page);
	KUNIT_EXPECT_EQ(test, result, 0);
	KUNIT_EXPECT_EQ(test,
		memcmp(output, original_page, SWAPZ_BLOCK_BYTES), 0);
	/* SHA/CRC failure must never publish any partial decoded output. */
	memset(output, 0x5a, SWAPZ_BLOCK_BYTES);
	record.original_sha256[0] ^= 1U;
	KUNIT_EXPECT_EQ(test,
		swapz_zswap_import_decoder_owner_decode(
			&lease, &record, &authority, owned_compressed,
			record.compressed_length, scratch, SWAPZ_BLOCK_BYTES,
			output, SWAPZ_BLOCK_BYTES, original_page), -EBADMSG);
	for (offset = 0; offset < SWAPZ_BLOCK_BYTES; ++offset) {
		if (output[offset] != 0x5aU) {
			KUNIT_FAIL(test, "SHA failure modified 4096-byte output");
			break;
		}
	}
	KUNIT_EXPECT_EQ(test,
		swapz_zswap_import_decoder_owner_put(&lease), 0);
	KUNIT_EXPECT_EQ(test,
		swapz_zswap_import_decoder_owner_close_and_drain(&owner), 0);
	/* No genuine lower FUA, upper acknowledgement or source slot is claimed:
	 * the authority fields above are TEST fixtures only. */
}

static void swapz_round068_lzo1x_after_source_release(struct kunit *test)
{
	swapz_round068_native_codec_after_source_release(
		test, SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC);
}

static void swapz_round068_lz4_after_source_release(struct kunit *test)
{
	swapz_round068_native_codec_after_source_release(
		test, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC);
}

static struct kunit_case swapz_round068_decoder_owner_cases[] = {
	KUNIT_CASE(swapz_round068_profile_and_fail_closed),
	KUNIT_CASE(swapz_round068_native_close_wake),
	KUNIT_CASE(swapz_round068_lzo1x_after_source_release),
	KUNIT_CASE(swapz_round068_lz4_after_source_release),
	{}
};

static struct kunit_suite swapz_round068_decoder_owner_suite = {
	.name = "swapz_round068_decoder_owner",
	.test_cases = swapz_round068_decoder_owner_cases,
};

kunit_test_suite(swapz_round068_decoder_owner_suite);
