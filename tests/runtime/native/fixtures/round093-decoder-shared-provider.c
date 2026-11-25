// SPDX-License-Identifier: GPL-2.0-only
/* Host-only storage-sidecar model with actual linked original codec owners.
 * Single external authority thread owns metadata; a joined worker exclusively
 * borrows one retained decode lease. No production mapping or authentication.
 */
#include "zswap-original-decode.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CAPACITY 1024U
#define CHECK(label, condition) do { ++checks; if (!(condition)) { \
	fprintf(stderr, "FIRST_ERROR round093-agent7 %s line=%d\n", label, __LINE__); \
	exit(77); } } while (0)

int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
	swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written);

struct sidecar {
	swapz_u64 generation;
	swapz_u32 pins;
	swapz_u8 codec;
	swapz_u8 live;
};
struct identity {
	swapz_u64 epoch;
	swapz_u64 generation;
	swapz_u32 index;
	swapz_u8 codec;
	swapz_u8 version;
};
static struct sidecar records[CAPACITY];
static struct swapz_zswap_import_decoder_owner providers[2];
static swapz_u64 epoch = 1U; /* External authority model; not a reload proof. */
static unsigned int checks, live_records, read_pins;
static int admission = 1;

static int publish(unsigned int index, swapz_u8 codec, struct identity *value)
{
	struct sidecar *record;

	if (!admission)
		return -ESHUTDOWN;
	if (index >= CAPACITY || codec < 1U || codec > 2U)
		return -EINVAL;
	record = &records[index];
	if (record->live || record->pins)
		return -EBUSY;
	if (record->generation == ~(swapz_u64)0)
		return -EOVERFLOW;
	++record->generation;
	record->codec = codec;
	record->live = 1U;
	++live_records;
	*value = (struct identity){epoch, record->generation, index, codec, 1U};
	return 0;
}

static struct sidecar *lookup(const struct identity *value)
{
	struct sidecar *record;

	if (value->epoch != epoch || value->index >= CAPACITY ||
	    value->version != 1U || !value->generation)
		return NULL;
	record = &records[value->index];
	if (!record->live || record->generation != value->generation ||
	    record->codec != value->codec)
		return NULL;
	return record;
}

static int acquire(const struct identity *value,
	struct swapz_zswap_import_decoder_lease *lease)
{
	struct sidecar *record;
	int result;

	if (!admission)
		return -ESHUTDOWN;
	record = lookup(value);
	if (!record)
		return -ESTALE;
	if (record->pins == ~(swapz_u32)0 || read_pins == ~0U)
		return -EOVERFLOW;
	result = swapz_zswap_import_decoder_owner_get(
		&providers[record->codec - 1U], lease);
	if (result)
		return result;
	++record->pins;
	++read_pins;
	return 0;
}

static int retire(const struct identity *value)
{
	struct sidecar *record = lookup(value);

	if (!record)
		return -ESTALE;
	record->live = 0U;
	--live_records;
	return 0;
}

struct read_job {
	struct swapz_zswap_import_decoder_lease lease;
	struct swapz_original_decode_record record;
	swapz_u8 page[SWAPZ_BLOCK_BYTES];
	swapz_u8 input[4608];
	swapz_u8 output[SWAPZ_BLOCK_BYTES];
	int result;
};

static void *decode_worker(void *argument)
{
	struct read_job *job = argument;
	swapz_u8 scratch[SWAPZ_BLOCK_BYTES];

	job->result = swapz_original_decode(&job->lease, &job->record, 3568U,
		job->input, sizeof(job->input), scratch, sizeof(scratch),
		job->output, sizeof(job->output));
	if (swapz_zswap_import_decoder_owner_put(&job->lease))
		job->result = -EIO;
	return NULL;
}

int main(void)
{
	struct identity values[CAPACITY], stale, replacement, bad;
	struct swapz_zswap_import_decoder_lease rejected = {0};
	struct read_job job = {0};
	pthread_t worker;
	unsigned int index, profile;

	for (profile = 0U; profile < 2U; ++profile)
		CHECK("provider_init", !swapz_zswap_import_decoder_owner_init(
			&providers[profile], (swapz_u8)(profile + 1U), 1U));
	for (index = 0U; index < CAPACITY; ++index)
		CHECK("publish", !publish(index, (swapz_u8)(1U + index % 2U),
			&values[index]));
	CHECK("simultaneous_capacity", live_records == CAPACITY);
	CHECK("no_record_provider_refs", !providers[0].active_readers &&
		!providers[1].active_readers);
	CHECK("capacity_bound", publish(CAPACITY, 1U, &replacement) == -EINVAL);
	CHECK("occupied_slot", publish(0U, 1U, &replacement) == -EBUSY);
	for (profile = 0U; profile < 2U; ++profile) {
		stale = values[profile];
		bad = stale;
		++bad.epoch;
		CHECK("foreign_epoch", acquire(&bad, &rejected) == -ESTALE);
		bad = stale;
		++bad.generation;
		CHECK("foreign_generation", acquire(&bad, &rejected) == -ESTALE);
		bad = stale;
		bad.codec = (swapz_u8)(3U - stale.codec);
		CHECK("foreign_codec", acquire(&bad, &rejected) == -ESTALE);
		memset(&job, 0, sizeof(job));
		for (index = 0U; index < sizeof(job.page); ++index)
			job.page[index] = (swapz_u8)(index % 127U == 0U ? 0x5a : 0U);
		job.record = (struct swapz_original_decode_record){
			.decoded_length = SWAPZ_BLOCK_BYTES,
			.representation = SWAPZ_ZSWAP_IMPORT_REPRESENTATION,
			.codec = stale.codec, .version = 1U,
		};
		CHECK("original_compress", !round085_compress(stale.codec,
			job.page, sizeof(job.page), job.input, sizeof(job.input),
			&job.record.compressed_length));
		job.record.compressed_crc32c = swapz_crc32c_bytes(job.input,
			job.record.compressed_length);
		CHECK("original_sha", !swapz_zswap_import_sha256(job.page,
			job.record.original_sha256));
		CHECK("read_pin", !acquire(&stale, &job.lease));
		CHECK("independent_provider_ref", providers[profile].active_readers == 1U);
		CHECK("retire", !retire(&stale));
		CHECK("stale_refused", acquire(&stale, &rejected) == -ESTALE);
		CHECK("pinned_slot_not_recycled", publish(profile, stale.codec,
			&replacement) == -EBUSY);
		admission = 0;
		CHECK("revoked_admission", acquire(&values[2], &rejected) == -ESHUTDOWN);
		CHECK("teardown_not_ready", read_pins == 1U && live_records != 0U);
		/* Transfer exclusive lease to worker; no metadata mutation by worker.
		 * Join before releasing the storage pin or inspecting worker output. */
		CHECK("worker_start", !pthread_create(&worker, NULL, decode_worker, &job));
		CHECK("worker_join", !pthread_join(worker, NULL));
		CHECK("retired_read_bytes", !job.result &&
			!memcmp(job.page, job.output, sizeof(job.page)));
		CHECK("provider_drained", !providers[profile].active_readers &&
			!job.lease.owner);
		--records[profile].pins;
		--read_pins;
		admission = 1;
		CHECK("reuse_after_join", !publish(profile, stale.codec, &replacement));
		CHECK("generation_advanced", replacement.generation > stale.generation);
		CHECK("old_value_not_revived", acquire(&stale, &rejected) == -ESTALE);
		values[profile] = replacement;
	}
	for (index = 0U; index < CAPACITY; ++index)
		CHECK("drain_record", !retire(&values[index]));
	CHECK("drained", !live_records && !read_pins);
	records[0].generation = ~(swapz_u64)0;
	CHECK("generation_exhaustion", publish(0U, 1U, &replacement) == -EOVERFLOW);
	stale = values[1];
	++epoch; /* Model external non-reloadable authority, after full drain. */
	CHECK("new_epoch_publish", !publish(1U, stale.codec, &replacement));
	CHECK("old_epoch_refused", acquire(&stale, &rejected) == -ESTALE);
	CHECK("new_epoch_retire", !retire(&replacement));
	admission = 0;
	CHECK("final_quiescence", !read_pins && !live_records);
	for (profile = 0U; profile < 2U; ++profile) {
		CHECK("provider_close", !swapz_zswap_import_decoder_owner_close_and_drain(
			&providers[profile]));
		CHECK("provider_cond_destroy", !pthread_cond_destroy(&providers[profile].drained));
		CHECK("provider_lock_destroy", !pthread_mutex_destroy(&providers[profile].lock));
	}
	printf("PASS ROUND093_AGENT7 scale checks=%u records=%u sidecar=%zu providers=%zu codecs=2 AUTH0\n",
		checks, CAPACITY, sizeof(struct sidecar), sizeof(providers));
	return 0;
}
