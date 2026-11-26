// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-shared.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CAPACITY 1024U
#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR round094-agent7 %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

/* Host storage authority adapter, not the provider implementation. One
 * indexed authoritative sidecar per record, no decoder-side duplicate.
 * External epoch survives destruction/reinitialization of the provider. */
struct sidecar {
	swapz_u64 generation;
	swapz_u32 pins;
	swapz_u8 codec;
	swapz_u8 live;
};

static struct sidecar records[CAPACITY];
static struct swapz_original_decoder_shared owner;
static swapz_u64 next_epoch = 1U, storage_epoch;
static unsigned int checks, snapshot_calls;
static swapz_u8 pages[2][SWAPZ_BLOCK_BYTES], compressed[2][4608];
static struct swapz_original_decode_record descriptors[2];
static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int pause_snapshot, entered, resume_snapshot;

static int reserve_epoch(void *context, swapz_u64 *epoch)
{
	(void)context;
	if (next_epoch == ~(swapz_u64)0)
		return -EOVERFLOW;
	storage_epoch = next_epoch++;
	*epoch = storage_epoch;
	return 0;
}

static int snapshot(void *context, swapz_u64 pin,
	struct swapz_original_decoder_value_snapshot *out)
{
	struct sidecar record;
	unsigned int index, profile;

	(void)context;
	if (!pin || pin > CAPACITY)
		return -ESTALE;
	index = (unsigned int)(pin - 1U);
	if (pthread_mutex_lock(&gate))
		return -EIO;
	if (pause_snapshot) {
		entered = 1;
		pthread_cond_broadcast(&changed);
		while (!resume_snapshot)
			if (pthread_cond_wait(&changed, &gate)) {
				pthread_mutex_unlock(&gate);
				return -EIO;
			}
	}
	++snapshot_calls;
	record = records[index];
	pthread_mutex_unlock(&gate);
	if (!record.pins)
		return -ESTALE;
	profile = record.codec - 1U;
	*out = (struct swapz_original_decoder_value_snapshot){
		.handle = {storage_epoch, record.generation, index, record.codec, 1U},
		.record = descriptors[profile],
		.compressed_bytes = compressed[profile],
		.compressed_capacity = sizeof(compressed[profile]),
	};
	return 0;
}

static struct swapz_original_decoder_value_handle identity(unsigned int index)
{
	return (struct swapz_original_decoder_value_handle){
		storage_epoch, records[index].generation, index, records[index].codec, 1U
	};
}

static int read_page(swapz_u64 pin,
	const struct swapz_original_decoder_value_handle *value, swapz_u8 *output)
{
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES], verified[SWAPZ_BLOCK_BYTES];

	return swapz_original_decoder_shared_read(&owner, pin, value, 3568U,
		scratch, sizeof(scratch), verified, sizeof(verified),
		output, SWAPZ_BLOCK_BYTES);
}

static void reject(const char *label, swapz_u64 pin,
	const struct swapz_original_decoder_value_handle *value, int error)
{
	swapz_u8 output[SWAPZ_BLOCK_BYTES], unchanged[SWAPZ_BLOCK_BYTES];

	memset(output, 0xa5, sizeof(output));
	memset(unchanged, 0xa5, sizeof(unchanged));
	CHECK(label, read_page(pin, value, output) == error);
	CHECK("failure_output_unchanged", !memcmp(output, unchanged, sizeof(output)));
}

struct reader_job {
	struct swapz_original_decoder_value_handle value;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	int result;
};

static void *reader(void *argument)
{
	struct reader_job *job = argument;

	job->result = read_page(1U, &job->value, job->output);
	return NULL;
}

int main(void)
{
	const struct swapz_original_decoder_shared_ops ops = {
		.reserve_epoch = reserve_epoch, .snapshot = snapshot,
	};
	struct swapz_original_decoder_value_handle value, bad, old;
	struct reader_job job = {0};
	pthread_t thread;
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	swapz_u64 epoch = 99U, next;
	unsigned int index, profile;

	CHECK("init", !swapz_original_decoder_shared_init(&owner, &ops, CAPACITY, &epoch));
	CHECK("epoch", epoch == 1U);
	CHECK("lifetime_refs", owner.providers[0].active_readers == 1U &&
		owner.providers[1].active_readers == 1U);
	for (profile = 0U; profile < 2U; ++profile) {
		for (index = 0U; index < SWAPZ_BLOCK_BYTES; ++index)
			pages[profile][index] = (swapz_u8)(index % 127U == 0U ? 0x5aU + profile : 0U);
		descriptors[profile] = (struct swapz_original_decode_record){
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = (swapz_u8)(profile + 1U), .version = 1U,
		};
		CHECK("compress", !round085_compress((swapz_u8)(profile + 1U),
			pages[profile], SWAPZ_BLOCK_BYTES, compressed[profile],
			sizeof(compressed[profile]), &descriptors[profile].compressed_length));
		descriptors[profile].compressed_crc32c = swapz_crc32c_bytes(compressed[profile],
			descriptors[profile].compressed_length);
		CHECK("sha", !swapz_zswap_import_sha256(pages[profile],
			descriptors[profile].original_sha256));
	}
	for (index = 0U; index < CAPACITY; ++index)
		records[index] = (struct sidecar){1U, 1U, (swapz_u8)(1U + index % 2U), 1U};
	for (index = 0U; index < CAPACITY; ++index) {
		value = identity(index);
		CHECK("indexed_read", !read_page(index + 1U, &value, output));
		CHECK("exact_page", !memcmp(output, pages[index % 2U], sizeof(output)));
	}
	CHECK("constant_refs", owner.providers[0].active_readers == 1U &&
		owner.providers[1].active_readers == 1U && !owner.active_reads);
	value = identity(0U);
	bad = value;
	++bad.lifecycle_epoch;
	profile = snapshot_calls;
	reject("wrong_epoch", 1U, &bad, -ESTALE);
	CHECK("epoch_before_lookup", snapshot_calls == profile);
	bad = value;
	++bad.generation;
	reject("wrong_generation", 1U, &bad, -ESTALE);
	bad.generation = 0U;
	reject("zero_generation", 1U, &bad, -ESTALE);
	bad = value;
	bad.codec = 2U;
	reject("wrong_codec", 1U, &bad, -ESTALE);
	bad = value;
	bad.version = 2U;
	reject("wrong_version", 1U, &bad, -ESTALE);
	bad = value;
	bad.slot_index = CAPACITY;
	reject("out_of_bounds", 1U, &bad, -ESTALE);
	reject("wrong_pin", 2U, &value, -ESTALE);
	reject("wrong_pin_index", 3U, &value, -ESTALE);
	records[0].pins = 0U;
	reject("missing_pin", 1U, &value, -ESTALE);
	records[0].pins = 1U;
	/* The external authority issues the final legal generation, never wraps. */
	old = value;
	records[0].pins = 0U;
	records[0].live = 0U;
	records[0].generation = ~(swapz_u64)0;
	records[0].live = 1U;
	records[0].pins = 1U;
	value = identity(0U);
	reject("stale_reuse", 1U, &old, -ESTALE);
	CHECK("final_generation_read", !read_page(1U, &value, output));
	descriptors[0].original_sha256[0] ^= 1U;
	reject("bad_sha", 1U, &value, -EBADMSG);
	descriptors[0].original_sha256[0] ^= 1U;
	CHECK("wrong_close_epoch", swapz_original_decoder_shared_begin_close(&owner, epoch + 1U) == -ESTALE);
	CHECK("finish_before_begin", swapz_original_decoder_shared_finish_close(&owner, epoch) == -ESHUTDOWN);

	/* Deterministically pause an already admitted reader before snapshot.
	 * Retire the mapped record but keep its pin; close fences new readers. */
	job.value = value;
	pause_snapshot = 1;
	CHECK("reader_start", !pthread_create(&thread, NULL, reader, &job));
	CHECK("gate_lock", !pthread_mutex_lock(&gate));
	while (!entered)
		CHECK("gate_wait", !pthread_cond_wait(&changed, &gate));
	records[0].live = 0U;
	CHECK("gate_unlock", !pthread_mutex_unlock(&gate));
	CHECK("begin_close", !swapz_original_decoder_shared_begin_close(&owner, epoch));
	CHECK("begin_idempotent", !swapz_original_decoder_shared_begin_close(&owner, epoch));
	CHECK("finish_busy", swapz_original_decoder_shared_finish_close(&owner, epoch) == -EBUSY);
	/* A bad admission guard mutant must not block in the paused callback. */
	bad = identity(1U);
	CHECK("gate_lock_resume", !pthread_mutex_lock(&gate));
	resume_snapshot = 1;
	pthread_cond_broadcast(&changed);
	CHECK("gate_unlock_resume", !pthread_mutex_unlock(&gate));
	reject("closing_refuses", 2U, &bad, -ESHUTDOWN);
	CHECK("reader_join", !pthread_join(thread, NULL));
	CHECK("retired_read", !job.result && !memcmp(job.output, pages[0], sizeof(job.output)));
	for (index = 0U; index < CAPACITY; ++index) {
		records[index].pins = 0U;
		records[index].live = 0U;
	}
	CHECK("finish", !swapz_original_decoder_shared_finish_close(&owner, epoch));
	old = value;
	memset(&owner, 0, sizeof(owner));
	CHECK("reinit", !swapz_original_decoder_shared_init(&owner, &ops, CAPACITY, &next));
	CHECK("epoch_not_reused", next > epoch);
	records[0] = (struct sidecar){1U, 1U, 1U, 1U};
	reject("old_lifetime", 1U, &old, -ESTALE);
	value = identity(0U);
	CHECK("new_lifetime_read", !read_page(1U, &value, output));
	records[0].pins = 0U;
	records[0].live = 0U;
	CHECK("second_begin", !swapz_original_decoder_shared_begin_close(&owner, next));
	CHECK("second_finish", !swapz_original_decoder_shared_finish_close(&owner, next));
	memset(&owner, 0, sizeof(owner));
	next_epoch = ~(swapz_u64)0;
	next = 99U;
	CHECK("epoch_exhaustion", swapz_original_decoder_shared_init(&owner, &ops, CAPACITY, &next) == -EOVERFLOW);
	CHECK("epoch_output_unchanged", next == 99U);
	CHECK("gate_destroy", !pthread_mutex_destroy(&gate));
	CHECK("cond_destroy", !pthread_cond_destroy(&changed));
	printf("PASS ROUND094_AGENT7 checks=%u records=%u sidecar=%zu owner=%zu handle=%zu codecs=2 AUTH0\n",
		checks, CAPACITY, sizeof(struct sidecar), sizeof(owner), sizeof(value));
	return 0;
}
