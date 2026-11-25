// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-bridge.h"
#include "zswap-original-storage.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR agent7-bridge %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

static struct swapz_original_decoder_bridge bridge;
static struct swapz_original_storage_ops lower_ops, wrapped_ops;
static swapz_u8 page[SWAPZ_BLOCK_BYTES], compressed[4608],
	scratch[SWAPZ_BLOCK_BYTES], verified[SWAPZ_BLOCK_BYTES],
	output[SWAPZ_BLOCK_BYTES], lower_image[SWAPZ_BLOCK_BYTES];
static unsigned int checks, reads, writes, flushes;
static int lower_result;

static int lower_write(void *context, swapz_u32 start,
		       const swapz_u8 *bytes, swapz_u32 length, swapz_u32 *completed)
{
	if (context != &lower_image || start != 7U || length != SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	++writes;
	if (lower_result)
		return lower_result;
	memcpy(lower_image, bytes, length);
	*completed = length;
	return 0;
}
static int lower_read(void *context, swapz_u32 start,
		      swapz_u8 *bytes, swapz_u32 length, swapz_u32 *completed)
{
	if (context != &lower_image || start != 7U || length != SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	++reads;
	if (lower_result)
		return lower_result;
	memcpy(bytes, lower_image, length);
	*completed = length;
	return 0;
}
static int lower_flush(void *context)
{
	if (context != &lower_image)
		return -EINVAL;
	++flushes;
	return lower_result;
}

static struct swapz_original_decoder_snapshot make_snapshot(
	swapz_u8 codec, swapz_u32 length, const void *token)
{
	struct swapz_original_decoder_snapshot snapshot = {
		.record = {
			.compressed_length = length,
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.compressed_crc32c = swapz_crc32c_bytes(compressed, length),
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = codec, .version = SWAPZ_ZSWAP_IMPORT_VERSION,
		},
		.compressed_bytes = compressed,
		.compressed_capacity = sizeof(compressed),
		.record_token = token,
	};
	CHECK("sha256", !swapz_zswap_import_sha256(page,
							snapshot.record.original_sha256));
	return snapshot;
}

static int decode(const struct swapz_original_decoder_snapshot *snapshot,
		  swapz_u32 ceiling)
{
	return swapz_original_decoder_bridge_read(&bridge, snapshot, ceiling,
		scratch, sizeof(scratch), verified, sizeof(verified),
		output, sizeof(output));
}

static void reject(const char *label,
		   const struct swapz_original_decoder_snapshot *snapshot,
		   swapz_u32 ceiling, int error)
{
	memset(output, 0xa5, sizeof(output));
	CHECK(label, decode(snapshot, ceiling) == error);
	for (unsigned int index = 0; index < sizeof(output); ++index)
		CHECK("failed_output_unchanged", output[index] == 0xa5);
}

struct reader_thread {
	struct swapz_original_decoder_snapshot snapshot;
	int result;
};

static void *parallel_reader(void *argument)
{
	struct reader_thread *thread = argument;
	swapz_u8 local_scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 local_verified[SWAPZ_BLOCK_BYTES];
	swapz_u8 local_output[SWAPZ_BLOCK_BYTES];
	thread->result = swapz_original_decoder_bridge_read(
		&bridge, &thread->snapshot, SWAPZ_ORIGINAL_DECODE_M3568,
		local_scratch, sizeof(local_scratch), local_verified,
		sizeof(local_verified), local_output, sizeof(local_output));
	if (!thread->result && memcmp(local_output, page, sizeof(page)))
		thread->result = -EBADMSG;
	return NULL;
}

int main(void)
{
	struct swapz_original_decoder_snapshot snapshot, bad;
	struct reader_thread readers[4];
	pthread_t threads[4];
	void *token, *next;
	swapz_u32 compressed_length, completed;
	unsigned int index, initial;

	for (index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
		page[index] = (swapz_u8)((index % 127U) == 0U ? 0x5a : 0);
	lower_ops = (struct swapz_original_storage_ops) {
		.context = &lower_image, .write = lower_write,
		.flush = lower_flush, .read = lower_read,
	};
	CHECK("init", !swapz_original_decoder_bridge_init(
		&bridge, &lower_ops, &wrapped_ops));
	CHECK("wrapped_callbacks", wrapped_ops.context == &bridge &&
		wrapped_ops.decoder_get && wrapped_ops.decoder_put &&
		wrapped_ops.write && wrapped_ops.read && wrapped_ops.flush);
	CHECK("bad_codec", !wrapped_ops.decoder_get(&bridge, 3, 1));
	CHECK("bad_version", !wrapped_ops.decoder_get(&bridge, 1, 2));
	CHECK("initial_closed_busy", swapz_original_decoder_bridge_close(&bridge) == 0);
	/* A fresh bridge is needed after successful close; forbid post-close use.
	 * The second bridge is a separate lifecycle, not a reused token. */
	memset(&bridge, 0, sizeof(bridge));
	CHECK("reinit", !swapz_original_decoder_bridge_init(
		&bridge, &lower_ops, &wrapped_ops));
	for (index = 0; index < 2U; ++index) {
		swapz_u8 codec = (swapz_u8)(index + 1U);
		CHECK("original_compress", !round085_compress(codec, page,
			SWAPZ_BLOCK_BYTES, compressed, sizeof(compressed),
			&compressed_length));
		CHECK("small_length", compressed_length > 0U &&
			compressed_length <= SWAPZ_ORIGINAL_DECODE_M3568);
		token = wrapped_ops.decoder_get(&bridge, codec, 1);
		CHECK("token_get", token);
		snapshot = make_snapshot(codec, compressed_length, token);
		memset(output, 0xa5, sizeof(output));
		CHECK("real_decode", !decode(&snapshot, SWAPZ_ORIGINAL_DECODE_M3568));
		CHECK("real_page", !memcmp(output, page, sizeof(page)));
		bad = snapshot;
		bad.record.codec = (swapz_u8)(3U - codec);
		reject("wrong_codec_token", &bad, 3568U, -ESTALE);
		bad = snapshot;
		bad.record.compressed_crc32c ^= 1U;
		reject("bad_crc", &bad, 3568U, -EBADMSG);
		bad = snapshot;
		bad.record.original_sha256[0] ^= 1U;
		reject("bad_sha", &bad, 3568U, -EBADMSG);
		bad = snapshot;
		bad.record.dictionary_id = 1U;
		reject("dictionary", &bad, 3568U, -EOPNOTSUPP);
		bad = snapshot;
		bad.record.version = 2U;
		reject("wrong_version", &bad, 3568U, -ESTALE);
		bad = snapshot;
		bad.compressed_capacity = compressed_length - 1U;
		reject("short_input", &bad, 3568U, -EMSGSIZE);
		/* Invalid pointers, page geometry and aliased workspaces must
		 * fail before the caller's decoded output can be published. */
		bad = snapshot;
		bad.compressed_bytes = NULL;
		reject("null_compressed_bytes", &bad, 3568U, -EINVAL);
		bad = snapshot;
		bad.record_token = NULL;
		reject("null_record_token", &bad, 3568U, -EINVAL);
		CHECK("scratch_short", swapz_original_decoder_bridge_read(
			&bridge, &snapshot, 3568U,
			scratch, SWAPZ_BLOCK_BYTES - 1U,
			verified, sizeof(verified), output, sizeof(output)) == -EINVAL);
		CHECK("verified_short", swapz_original_decoder_bridge_read(
			&bridge, &snapshot, 3568U,
			scratch, sizeof(scratch), verified, SWAPZ_BLOCK_BYTES - 1U,
			output, sizeof(output)) == -EINVAL);
		CHECK("output_short", swapz_original_decoder_bridge_read(
			&bridge, &snapshot, 3568U,
			scratch, sizeof(scratch), verified, sizeof(verified),
			output, SWAPZ_BLOCK_BYTES - 1U) == -EINVAL);
		CHECK("scratch_verified_alias", swapz_original_decoder_bridge_read(
			&bridge, &snapshot, 3568U,
			scratch, sizeof(scratch), scratch, sizeof(scratch),
			output, sizeof(output)) == -EINVAL);
		bad = snapshot;
		bad.record.compressed_length = 0U;
		reject("zero_length", &bad, 3568U, -EMSGSIZE);
		bad = snapshot;
		bad.record.compressed_length = 3569U;
		reject("m3568_ceiling", &bad, 3568U, -EMSGSIZE);
		bad = snapshot;
		bad.record.representation = 0U;
		reject("representation", &bad, 3568U, -EOPNOTSUPP);
		bad = snapshot;
		bad.record_token = &lower_image;
		reject("forged_token", &bad, 3568U, -ESTALE);
		CHECK("alias_output", swapz_original_decoder_bridge_read(
			&bridge, &snapshot, 3568U, scratch, sizeof(scratch),
			verified, sizeof(verified), scratch, sizeof(scratch)) == -EINVAL);
		CHECK("closed_with_record", swapz_original_decoder_bridge_close(&bridge) == -EBUSY);
		if (index == 0U) {
			for (unsigned int thread_index = 0U; thread_index < 4U; ++thread_index) {
				readers[thread_index].snapshot = snapshot;
				CHECK("thread_create", !pthread_create(&threads[thread_index],
					NULL, parallel_reader, &readers[thread_index]));
			}
			for (unsigned int thread_index = 0U; thread_index < 4U; ++thread_index) {
				CHECK("thread_join", !pthread_join(threads[thread_index], NULL));
				CHECK("thread_read", !readers[thread_index].result);
			}
		}
		wrapped_ops.decoder_put(&bridge, token);
		reject("released_token", &snapshot, 3568U, -ESTALE);
		/* A previously issued token must never be revived after new gets. */
		next = wrapped_ops.decoder_get(&bridge, codec, 1);
		CHECK("new_token_address", next && next != token);
		reject("no_ABA_revival", &snapshot, 3568U, -ESTALE);
		wrapped_ops.decoder_put(&bridge, next);
	}
	/* Large valid original streams are experimental-only (M4095). */
	{
		swapz_u32 state = 0x1ad57f91U;

		for (index = 0; index < 3800U; ++index) {
			state ^= state << 13U;
			state ^= state >> 17U;
			state ^= state << 5U;
			page[index] = (swapz_u8)state;
		}
		memset(page + 3800U, 0, sizeof(page) - 3800U);
		CHECK("large_original_compress", !round085_compress(1U, page,
			SWAPZ_BLOCK_BYTES, compressed, sizeof(compressed),
			&compressed_length));
		CHECK("m4095_boundary", compressed_length > 3568U &&
			compressed_length <= 4095U);
		token = wrapped_ops.decoder_get(&bridge, 1U, 1U);
		CHECK("large_token", token);
		snapshot = make_snapshot(1U, compressed_length, token);
		reject("m3568_reject_large", &snapshot, 3568U, -EMSGSIZE);
		CHECK("m4095_decode", !decode(&snapshot, 4095U));
		CHECK("m4095_bytes", !memcmp(output, page, sizeof(page)));
		wrapped_ops.decoder_put(&bridge, token);
	}
	initial = bridge.issued_tokens;
	while (bridge.issued_tokens < SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS) {
		token = wrapped_ops.decoder_get(&bridge, 1, 1);
		CHECK("bounded_get", token);
		wrapped_ops.decoder_put(&bridge, token);
	}
	CHECK("bounded_issued", bridge.issued_tokens ==
		SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS && initial == 5U);
	CHECK("exhausted", !wrapped_ops.decoder_get(&bridge, 1, 1));
	CHECK("io_write", !wrapped_ops.write(&bridge, 7, page,
		SWAPZ_BLOCK_BYTES, &completed) && completed == SWAPZ_BLOCK_BYTES);
	CHECK("io_read", !wrapped_ops.read(&bridge, 7, output,
		SWAPZ_BLOCK_BYTES, &completed) && !memcmp(output, page, sizeof(page)));
	CHECK("io_flush", !wrapped_ops.flush(&bridge));
	lower_result = -EIO;
	CHECK("io_lower_error", wrapped_ops.read(&bridge, 7, output,
		SWAPZ_BLOCK_BYTES, &completed) == -EIO &&
		wrapped_ops.flush(&bridge) == -EIO);
	lower_result = 0;
	CHECK("close_success", !swapz_original_decoder_bridge_close(&bridge));
	CHECK("lower_counts", reads == 2U && writes == 1U && flushes == 2U);
	printf("PASS ROUND090_AGENT7 checks=%u tokens=%u actual_original=2 AUTH0\n",
		checks, SWAPZ_ORIGINAL_DECODER_BRIDGE_TOKENS);
	return 0;
}
