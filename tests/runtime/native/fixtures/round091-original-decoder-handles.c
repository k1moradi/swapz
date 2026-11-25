// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-handles.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR round091-agent7 %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

static struct swapz_original_decoder_handle_owner owner;
static swapz_u8 page[SWAPZ_BLOCK_BYTES], compressed[4608];
static unsigned int checks, successful_reads, rejected_reads;

static struct swapz_original_decoder_value_snapshot snapshot_for(
	swapz_u8 codec, swapz_u32 length,
	struct swapz_original_decoder_value_handle handle)
{
	struct swapz_original_decoder_value_snapshot snapshot = {
		.handle = handle,
		.record = {
			.compressed_length = length,
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.compressed_crc32c = swapz_crc32c_bytes(compressed, length),
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = codec,
			.version = SWAPZ_ZSWAP_IMPORT_VERSION,
		},
		.compressed_bytes = compressed,
		.compressed_capacity = sizeof(compressed),
	};

	CHECK("record_sha", !swapz_zswap_import_sha256(page,
				snapshot.record.original_sha256));
	return snapshot;
}

static int decode(
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *output)
{
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES], verified[SWAPZ_BLOCK_BYTES];

	return swapz_original_decoder_handle_read(&owner, snapshot, ceiling,
		scratch, sizeof(scratch), verified, sizeof(verified),
		output, SWAPZ_BLOCK_BYTES);
}

static void reject(const char *label,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, int expected)
{
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	unsigned int index;

	memset(output, 0xa5, sizeof(output));
	CHECK(label, decode(snapshot, ceiling, output) == expected);
	for (index = 0U; index < sizeof(output); ++index)
		CHECK("failure_output_unchanged", output[index] == 0xa5);
}

struct racing_reader {
	struct swapz_original_decoder_value_snapshot snapshot;
	int result;
};

static void *race_reader(void *argument)
{
	struct racing_reader *reader = argument;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	unsigned int index;

	memset(output, 0xa5, sizeof(output));
	reader->result = decode(&reader->snapshot, SWAPZ_ORIGINAL_DECODE_M3568,
				output);
	if (!reader->result) {
		if (memcmp(output, page, sizeof(page)))
			reader->result = -EBADMSG;
	} else if (reader->result == -ESTALE) {
		for (index = 0U; index < sizeof(output); ++index)
			if (output[index] != 0xa5) {
				reader->result = -EFAULT;
				break;
			}
	}
	return NULL;
}

struct churn_worker {
	unsigned int number_of_operations;
	int error;
};

static void *churn_records(void *argument)
{
	struct churn_worker *worker = argument;
	struct swapz_original_decoder_value_handle handle;
	unsigned int index;

	for (index = 0; index < worker->number_of_operations; ++index) {
		worker->error = swapz_original_decoder_handle_get(
			&owner, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
			SWAPZ_ZSWAP_IMPORT_VERSION, &handle);
		if (worker->error)
			return NULL;
		worker->error = swapz_original_decoder_handle_put(&owner, &handle);
		if (worker->error)
			return NULL;
	}
	return NULL;
}

int main(void)
{
	struct swapz_original_decoder_value_handle handle, old_handle, new_handle;
	struct swapz_original_decoder_value_handle previous_lifecycle_handle;
	struct swapz_original_decoder_value_snapshot snapshot, bad;
	struct racing_reader racing[4];
	struct churn_worker workers[4] = {{2000U, 0}, {2000U, 0},
					{2000U, 0}, {2000U, 0}};
	pthread_t threads[4];
	swapz_u8 output[SWAPZ_BLOCK_BYTES], scratch[SWAPZ_BLOCK_BYTES];
	swapz_u8 verified[SWAPZ_BLOCK_BYTES];
	swapz_u32 length;
	swapz_u64 first_epoch;
	unsigned int index, iteration, successes = 0U, declines = 0U;
	int result;

	for (index = 0U; index < sizeof(page); ++index)
		page[index] = (swapz_u8)((index % 127U) == 0U ? 0x5a : 0U);
	CHECK("init", !swapz_original_decoder_handles_init(&owner));
	first_epoch = owner.lifecycle_epoch;
	CHECK("epoch_nonzero", first_epoch != 0U);
	CHECK("unknown_codec", swapz_original_decoder_handle_get(
		&owner, 3U, 1U, &handle) == -EINVAL);
	CHECK("unknown_version", swapz_original_decoder_handle_get(
		&owner, 1U, 2U, &handle) == -EINVAL);
	for (index = 0U; index < 2U; ++index) {
		swapz_u8 codec = (swapz_u8)(index + 1U);

		CHECK("real_original_compress", !round085_compress(codec, page,
			SWAPZ_BLOCK_BYTES, compressed, sizeof(compressed), &length));
		CHECK("m3568", length != 0U &&
			length <= SWAPZ_ORIGINAL_DECODE_M3568);
		CHECK("record_get", !swapz_original_decoder_handle_get(
			&owner, codec, 1U, &handle));
		snapshot = snapshot_for(codec, length, handle);
		CHECK("real_original_decode", !decode(&snapshot, 3568U, output));
		CHECK("decoded_bytes", !memcmp(output, page, sizeof(page)));
		CHECK("live_close_busy", swapz_original_decoder_handles_close(
			&owner) == -EBUSY);
		bad = snapshot;
		bad.record.codec = (swapz_u8)(3U - codec);
		reject("wrong_codec", &bad, 3568U, -ESTALE);
		bad = snapshot;
		bad.record.compressed_crc32c ^= 1U;
		reject("CRC", &bad, 3568U, -EBADMSG);
		bad = snapshot;
		bad.record.original_sha256[0] ^= 1U;
		reject("SHA", &bad, 3568U, -EBADMSG);
		bad = snapshot;
		bad.record.dictionary_id = 1U;
		reject("dictionary", &bad, 3568U, -EOPNOTSUPP);
		bad = snapshot;
		bad.compressed_capacity = length - 1U;
		reject("short_input", &bad, 3568U, -EMSGSIZE);
		bad = snapshot;
		bad.handle.generation ^= 1U;
		reject("wrong_generation", &bad, 3568U, -ESTALE);
		bad = snapshot;
		bad.handle.lifecycle_epoch ^= 1U;
		reject("wrong_epoch", &bad, 3568U, -ESTALE);
		bad = snapshot;
		bad.handle.slot_index = SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS;
		reject("wrong_slot", &bad, 3568U, -ESTALE);
		CHECK("output_alias", swapz_original_decoder_handle_read(
			&owner, &snapshot, 3568U, scratch, sizeof(scratch),
			verified, sizeof(verified), scratch, sizeof(scratch)) == -EINVAL);
		old_handle = handle;
		CHECK("record_put", !swapz_original_decoder_handle_put(&owner,
			&handle));
		CHECK("duplicate_put", swapz_original_decoder_handle_put(
			&owner, &handle) == -ESTALE);
		reject("stale_retired", &snapshot, 3568U, -ESTALE);
		CHECK("reuse_get", !swapz_original_decoder_handle_get(
			&owner, codec, 1U, &new_handle));
		CHECK("same_slot_new_generation",
			new_handle.slot_index == old_handle.slot_index &&
			new_handle.generation > old_handle.generation);
		reject("retired_not_revived", &snapshot, 3568U, -ESTALE);
		CHECK("reuse_put", !swapz_original_decoder_handle_put(
			&owner, &new_handle));
	}

	/* More than 64 total record lifetimes, with reuses and full concurrency.
	 * All worker tokens are independent value copies, not pointer addresses. */
	for (index = 0U; index < 4U; ++index)
		CHECK("churn_start", !pthread_create(&threads[index], NULL,
			churn_records, &workers[index]));
	for (index = 0U; index < 4U; ++index) {
		CHECK("churn_join", !pthread_join(threads[index], NULL));
		CHECK("churn_result", !workers[index].error);
	}
	for (iteration = 0U; iteration < 16000U; ++iteration) {
		CHECK("steady_get", !swapz_original_decoder_handle_get(
			&owner, 1U, 1U, &handle));
		CHECK("steady_put", !swapz_original_decoder_handle_put(
			&owner, &handle));
	}
	CHECK("record_churn_count", owner.active_records == 0U);

	/* A retiring record cannot invalidate an already retained read lease.
	 * Racing readers may succeed or decline before admission, never corrupt. */
	CHECK("race_compress", !round085_compress(1U, page, SWAPZ_BLOCK_BYTES,
		compressed, sizeof(compressed), &length));
	CHECK("race_get", !swapz_original_decoder_handle_get(
		&owner, 1U, 1U, &handle));
	snapshot = snapshot_for(1U, length, handle);
	for (index = 0U; index < 4U; ++index) {
		racing[index].snapshot = snapshot;
		CHECK("read_start", !pthread_create(&threads[index], NULL,
			race_reader, &racing[index]));
	}
	CHECK("race_retire", !swapz_original_decoder_handle_put(&owner, &handle));
	for (index = 0U; index < 4U; ++index) {
		CHECK("read_join", !pthread_join(threads[index], NULL));
		result = racing[index].result;
		CHECK("read_race_valid", !result || result == -ESTALE);
		if (!result)
			++successes;
		else
			++declines;
	}
	CHECK("read_race_accounted", successes + declines == 4U);
	reject("race_retired_replay", &snapshot, 3568U, -ESTALE);

	/* Experimental ceiling is distinct from conservative M3568. */
	{
		swapz_u32 state = 0x1ad57f91U;

		for (index = 0U; index < 3800U; ++index) {
			state ^= state << 13U;
			state ^= state >> 17U;
			state ^= state << 5U;
			page[index] = (swapz_u8)state;
		}
		memset(page + 3800U, 0, sizeof(page) - 3800U);
		CHECK("large_compress", !round085_compress(1U, page, 4096U,
			compressed, sizeof(compressed), &length));
		CHECK("large_boundary", length > 3568U && length <= 4095U);
		CHECK("large_get", !swapz_original_decoder_handle_get(
			&owner, 1U, 1U, &handle));
		snapshot = snapshot_for(1U, length, handle);
		reject("m3568_reject", &snapshot, 3568U, -EMSGSIZE);
		CHECK("m4095_decode", !decode(&snapshot, 4095U, output));
		CHECK("m4095_page", !memcmp(output, page, sizeof(page)));
		previous_lifecycle_handle = handle;
		CHECK("large_put", !swapz_original_decoder_handle_put(
			&owner, &handle));
	}
	/* Exhaust generation per slot without wrapping; no stale handle revive. */
	for (index = 0U; index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS; ++index)
		owner.slots[index].last_generation = ~(swapz_u64)0;
	memset(&new_handle, 0xa5, sizeof(new_handle));
	old_handle = new_handle;
	CHECK("saturated_generations", swapz_original_decoder_handle_get(
		&owner, 1U, 1U, &new_handle) == -EOVERFLOW);
	CHECK("overflow_output_unchanged",
		!memcmp(&new_handle, &old_handle, sizeof(new_handle)));
	CHECK("close", !swapz_original_decoder_handles_close(&owner));
	memset(&owner, 0, sizeof(owner));
	CHECK("second_lifecycle_init", !swapz_original_decoder_handles_init(&owner));
	CHECK("epoch_changes", first_epoch != owner.lifecycle_epoch);
	CHECK("new_lifecycle_get", !swapz_original_decoder_handle_get(
		&owner, 1U, 1U, &handle));
	bad = snapshot;
	bad.handle = previous_lifecycle_handle;
	reject("old_lifecycle_stale", &bad, 4095U, -ESTALE);
	CHECK("new_lifecycle_put", !swapz_original_decoder_handle_put(
		&owner, &handle));
	CHECK("second_lifecycle_close",
		!swapz_original_decoder_handles_close(&owner));
	printf("PASS ROUND091_AGENT7 checks=%u churn=24000 codecs=2 "
	       "races=%u/%u epoch=2 AUTH0\n",
		checks, successes, declines);
	return 0;
}
