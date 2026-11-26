/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#include "native-observation-recorder.h"

#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CHECK(condition) do { if (!(condition)) { \
	fprintf(stderr, "RECORDER_TEST_FAILURE line=%d\n", __LINE__); \
	exit(EXIT_FAILURE); } } while (0)

static struct swapz_observation_recorder recorder;
static struct swapz_observation_record storage[SWAPZ_OBSERVATION_MAX_RECORDS];
static uint64_t checks;

#define check(condition) do { CHECK(condition); ++checks; } while (0)

static uint64_t mint(void)
{
	uint64_t result = swapz_observation_mint(&recorder);
	CHECK(result != 0);
	return result;
}

static void emit(struct swapz_observation_record record)
{
	CHECK(swapz_observation_append(&recorder, &record));
}

static bool file_sink(void *context, const uint8_t *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}

static bool reject_sink(void *context, const uint8_t *bytes, size_t length)
{
	(void)context;
	(void)bytes;
	(void)length;
	return false;
}

struct identity {
	uint64_t operation, descriptor, clone, original, extent, lower, pin;
	uint32_t logical;
	uint8_t digest, page_digest;
};

static struct identity identity_new(uint32_t logical, uint8_t digest,
				    uint8_t page_digest, bool read)
{
	struct identity id = {
		.operation = mint(), .descriptor = mint(), .clone = mint(),
		.original = mint(), .lower = mint(), .logical = logical,
		.digest = digest, .page_digest = page_digest,
	};

	if (read)
		id.pin = mint();
	else
		id.extent = mint();
	return id;
}

static void source_key(struct swapz_observation_record *record,
		       const struct identity *id)
{
	record->logical = id->logical;
	record->swap_type = 1;
	record->slot = id->logical;
	record->area_epoch = 3;
	record->store = 7;
	record->generation = 1;
}

static void typed_payload(struct swapz_observation_record *record,
			  const struct identity *id)
{
	record->compressed_length = 100;
	record->decoded_length = 4096;
	record->codec = id->logical == 1 ? 1U : 2U;
	record->tag = 90;
	record->version = 1;
	memset(record->compressed_sha256, id->digest, 32);
	memset(record->page_sha256, id->page_digest, 32);
}

static void lower_submit(const struct identity *id, uint32_t direction)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_LOWER_SUBMIT, .operation = id->operation,
		.lower = id->lower, .extent = id->extent, .flags = direction,
		.requested = 4096, .compressed_length = 100,
	};
	memset(record.compressed_sha256, id->digest, 32);
	emit(record);
}

static void lower_complete(const struct identity *id)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_LOWER_COMPLETE, .operation = id->operation,
		.lower = id->lower, .completed = 4096,
	};
	memset(record.observed_sha256, id->digest, 32);
	emit(record);
}

static void clone_endio(const struct identity *id)
{
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_CLONE_ENDIO, .operation = id->operation,
		.descriptor = id->descriptor, .clone = id->clone,
	});
}

static void upper_endio(const struct identity *id)
{
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_UPPER_ENDIO, .operation = id->operation,
		.original = id->original,
	});
}

static void candidate_release(const struct identity *id)
{
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_CANDIDATE_RELEASE, .operation = id->operation,
		.descriptor = id->descriptor,
	});
}

static void carrier_release(const struct identity *id)
{
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_CARRIER_RELEASE, .operation = id->operation,
		.original = id->original,
	});
}

static void capture_write(const struct identity *id, uint64_t credit,
			  bool release_before_completion)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_CAPTURE, .operation = id->operation,
		.operation_kind = SWAPZ_OBS_TYPED_WRITE,
	};
	source_key(&record, id);
	typed_payload(&record, id);
	emit(record);
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_PREPARATION, .operation = id->operation, .flags = 1,
	});
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_BIND, .operation = id->operation, .original = id->original,
	});
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_ACCEPT, .operation = id->operation,
		.operation_kind = SWAPZ_OBS_TYPED_WRITE, .descriptor = id->descriptor,
		.clone = id->clone, .original = id->original, .flags = 1,
	};
	source_key(&record, id);
	emit(record);
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_PREPARATION, .operation = id->operation, .flags = 2,
	});
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_DISPATCH, .operation = id->operation, .flags = 1,
	});
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_RESERVE, .operation = id->operation,
		.credit = credit, .extent = id->extent,
	});
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_CLAIM, .operation = id->operation,
		.credit = credit, .descriptor = id->descriptor,
	});
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_PREPARATION, .operation = id->operation, .flags = 4,
	});
	lower_submit(id, 2);
	lower_complete(id);
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_FLUSH, .operation = id->operation, .extent = id->extent,
	});
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_PUBLISH, .operation = id->operation,
		.extent = id->extent, .gc_epoch = 1, .new_generation = 1,
	};
	typed_payload(&record, id);
	emit(record);
	if (release_before_completion)
		candidate_release(id);
	clone_endio(id);
	upper_endio(id);
	if (release_before_completion)
		carrier_release(id);
	/* Otherwise leave both deferred release debts until independent reads. */
}

static void read_start(const struct identity *id)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_ACCEPT, .operation = id->operation,
		.operation_kind = SWAPZ_OBS_TYPED_READ, .logical = id->logical,
		.descriptor = id->descriptor, .clone = id->clone, .original = id->original,
	};
	emit(record);
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_DISPATCH, .operation = id->operation, .flags = 2,
	});
	record = (struct swapz_observation_record){
		.event = SWAPZ_OBS_PIN, .operation = id->operation,
		.pin = id->pin, .extent = id->extent, .gc_epoch = 1,
	};
	source_key(&record, id);
	emit(record);
	lower_submit(id, 1);
}

static void read_finish(const struct identity *id)
{
	struct swapz_observation_record record = {
		.event = SWAPZ_OBS_ORACLE, .operation = id->operation,
		.pin = id->pin, .decoded_length = 4096, .compared = 4096, .flags = 1,
	};
	lower_complete(id);
	memset(record.page_sha256, id->page_digest, 32);
	memset(record.observed_sha256, id->page_digest, 32);
	emit(record);
	emit((struct swapz_observation_record){
		.event = SWAPZ_OBS_PIN_RELEASE, .operation = id->operation, .pin = id->pin,
	});
	clone_endio(id);
	upper_endio(id);
}

/* This deliberately interleaves independently pinned reads and deferred work.
 * It is a fabricated producer, NOT execution of MM, DM or codec code. */
static void fixture(const uint8_t scope[32])
{
	CHECK(swapz_observation_init(&recorder, storage, 128, scope));
	struct identity first = identity_new(1, 0x11, 0x22, false);
	struct identity second = identity_new(2, 0x33, 0x44, false);
	capture_write(&first, 1, true);
	capture_write(&second, 2, false);
	struct identity read_a = identity_new(1, first.digest, first.page_digest, true);
	struct identity read_b = identity_new(2, second.digest, second.page_digest, true);
	read_a.extent = first.extent;
	read_b.extent = second.extent;
	read_start(&read_a);
	read_start(&read_b);
	candidate_release(&second);
	read_finish(&read_b); /* B completion precedes A, without sorting. */
	carrier_release(&second);
	read_finish(&read_a);
	emit((struct swapz_observation_record){.event = SWAPZ_OBS_CLEANUP, .flags = 7});
	swapz_observation_stop(&recorder);
	CHECK(swapz_observation_seal(&recorder));
	CHECK(swapz_observation_export(&recorder, file_sink, stdout));
	CHECK(fflush(stdout) == 0);
}

static void loss_fixture(const uint8_t scope[32])
{
	CHECK(swapz_observation_init(&recorder, storage, 1, scope));
	const uint64_t op = mint();
	const struct swapz_observation_record record = {
		.event = SWAPZ_OBS_PREPARATION, .operation = op, .flags = 1,
	};
	emit(record);
	CHECK(!swapz_observation_append(&recorder, &record));
	swapz_observation_stop(&recorder);
	CHECK(swapz_observation_seal(&recorder));
	CHECK(swapz_observation_export(&recorder, file_sink, stdout));
	CHECK(fflush(stdout) == 0);
}

struct producer {
	struct swapz_observation_record record;
	size_t successes;
};

static atomic_bool go;

static void *producer_run(void *opaque)
{
	struct producer *producer = opaque;

	while (!atomic_load_explicit(&go, memory_order_acquire))
		;
	for (unsigned index = 0; index < 2048U; ++index)
		if (swapz_observation_append(&recorder, &producer->record))
			++producer->successes;
	return NULL;
}

static uint64_t monotonic_ns(void)
{
	struct timespec now;
	CHECK(clock_gettime(CLOCK_MONOTONIC, &now) == 0);
	CHECK(now.tv_sec >= 0 && now.tv_nsec >= 0);
	return (uint64_t)now.tv_sec * UINT64_C(1000000000) + (uint64_t)now.tv_nsec;
}

static void selftest(const uint8_t scope[32])
{
	uint8_t zero[32] = {0};
	check(!swapz_observation_init(&recorder, storage, 0, scope));
	check(!swapz_observation_init(&recorder, storage, 8193, scope));
	check(!swapz_observation_init(&recorder, storage, 1, zero));
	check(swapz_observation_init(&recorder, storage, 2, scope));
	check(!swapz_observation_seal(&recorder));
	check(!swapz_observation_export(&recorder, reject_sink, NULL));
	uint64_t operation = mint();
	struct swapz_observation_record record = {
		.operation = operation, .event = SWAPZ_OBS_PREPARATION, .flags = 1,
	};
	atomic_store_explicit(&recorder.locked, true, memory_order_release);
	check(!swapz_observation_append(&recorder, &record));
	check(swapz_observation_mint(&recorder) == 0);
	atomic_store_explicit(&recorder.locked, false, memory_order_release);
	check((atomic_load(&recorder.loss) & SWAPZ_OBS_LOST_CONTENTION) != 0);
	record.sequence = 1;
	check(!swapz_observation_append(&recorder, &record));
	record.sequence = 0;
	record.descriptor = UINT64_MAX;
	check(!swapz_observation_append(&recorder, &record));
	record.descriptor = 0;
	check((atomic_load(&recorder.loss) & SWAPZ_OBS_LOST_INVALID) != 0);
	check(swapz_observation_append(&recorder, &record));
	check(swapz_observation_append(&recorder, &record));
	check(!swapz_observation_append(&recorder, &record));
	check((atomic_load(&recorder.loss) & SWAPZ_OBS_LOST_OVERFLOW) != 0);
	check(storage[0].sequence == 1 && storage[1].sequence == 2);
	for (unsigned index = 1; index < 16U; ++index)
		check(mint() == (uint64_t)index + 1U);
	check(swapz_observation_mint(&recorder) == 0);
	swapz_observation_stop(&recorder);
	check(!swapz_observation_append(&recorder, &record));
	check(swapz_observation_mint(&recorder) == 0);
	check(swapz_observation_seal(&recorder));
	check(!swapz_observation_export(&recorder, reject_sink, NULL));
	check(recorder.count == 2);

	/* Two real host threads contend for one nonblocking recorder, using
	 * separate immutable input records. A lost event is never concealed. */
	check(swapz_observation_init(&recorder, storage, 4096, scope));
	struct producer producers[2] = {
		{.record = {.operation = mint(), .event = SWAPZ_OBS_PREPARATION, .flags = 1}},
		{.record = {.operation = mint(), .event = SWAPZ_OBS_PREPARATION, .flags = 2}},
	};
	pthread_t threads[2];
	atomic_init(&go, false);
	CHECK(pthread_create(&threads[0], NULL, producer_run, &producers[0]) == 0);
	CHECK(pthread_create(&threads[1], NULL, producer_run, &producers[1]) == 0);
	atomic_store_explicit(&go, true, memory_order_release);
	CHECK(pthread_join(threads[0], NULL) == 0);
	CHECK(pthread_join(threads[1], NULL) == 0);
	size_t accepted = producers[0].successes + producers[1].successes;
	check(accepted == recorder.count && accepted > 0 && accepted <= 4096);
	check(accepted == 4096 ? atomic_load(&recorder.loss) == 0 :
	      (atomic_load(&recorder.loss) & SWAPZ_OBS_LOST_CONTENTION) != 0);
	size_t seen[2] = {0};
	for (size_t index = 0; index < accepted; ++index) {
		check(storage[index].sequence == (uint64_t)index + 1U);
		check(storage[index].flags == 1 || storage[index].flags == 2);
		size_t producer = storage[index].flags - 1U;
		check(storage[index].operation == producers[producer].record.operation);
		++seen[producer];
	}
	check(seen[0] == producers[0].successes && seen[1] == producers[1].successes);
	swapz_observation_stop(&recorder);
	check(swapz_observation_seal(&recorder));
	printf("THREADS attempts=4096 accepted=%zu lost=%zu loss_flags=%u\n",
	       accepted, (size_t)4096 - accepted, atomic_load(&recorder.loss));

	/* Measure host append/disabled path only, not kernel capture, hashing,
	 * scheduling or device overhead. No timing threshold or pass inference. */
	uint64_t enabled_ns = 0, disabled_ns = 0;
	const unsigned rounds = 32;
	for (unsigned round = 0; round < rounds; ++round) {
		check(swapz_observation_init(&recorder, storage, 8192, scope));
		record.operation = mint();
		uint64_t start = monotonic_ns();
		for (unsigned index = 0; index < 8192; ++index)
			CHECK(swapz_observation_append(&recorder, &record));
		enabled_ns += monotonic_ns() - start;
		swapz_observation_stop(&recorder);
		start = monotonic_ns();
		for (unsigned index = 0; index < 8192; ++index)
			CHECK(!swapz_observation_append(&recorder, &record));
		disabled_ns += monotonic_ns() - start;
		check(swapz_observation_seal(&recorder));
	}
	printf("RECORDER_METRICS checks=%" PRIu64 " record_bytes=%zu owner_bytes=%zu "
	       "capacity_8192_bytes=%zu capacity_1024_bytes=%zu samples=%u "
	       "append_ns_total=%" PRIu64 " disabled_ns_total=%" PRIu64 "\n",
	       checks, sizeof(storage[0]), sizeof(recorder), sizeof(storage),
	       sizeof(storage[0]) * 1024U, rounds * 8192U, enabled_ns, disabled_ns);
}

static int hex_digit(char character)
{
	if (character >= '0' && character <= '9')
		return character - '0';
	if (character >= 'a' && character <= 'f')
		return character - 'a' + 10;
	return -1;
}

int main(int argc, char **argv)
{
	uint8_t scope[32];
	CHECK(argc == 3 && strlen(argv[2]) == 64);
	for (size_t index = 0; index < sizeof(scope); ++index) {
		int high = hex_digit(argv[2][2U * index]);
		int low = hex_digit(argv[2][2U * index + 1U]);
		CHECK(high >= 0 && low >= 0);
		scope[index] = (uint8_t)(high * 16 + low);
	}
	if (strcmp(argv[1], "fixture") == 0)
		fixture(scope);
	else if (strcmp(argv[1], "loss") == 0)
		loss_fixture(scope);
	else if (strcmp(argv[1], "selftest") == 0)
		selftest(scope);
	else
		return EXIT_FAILURE;
	return EXIT_SUCCESS;
}
