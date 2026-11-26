/* SPDX-License-Identifier: GPL-2.0-only */
#define _POSIX_C_SOURCE 200809L
#include "native-observation-recorder.h"

#include <inttypes.h>
#include <limits.h>
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
	/* The historical recorder-wide lock no longer exists; reservation
	 * contention is exercised by the separate concurrent qualification. */
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

	/* Two real host threads reserve independent slots in one recorder, using
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

/* Separate changed-reservation qualification: do not rerun accepted
 * semantic parser cases or the original recorder selftest in this lane.
 */
#define CONCURRENT_THREADS 8U
#define CONCURRENT_ATTEMPTS 8192U
#define CONCURRENT_ROUNDS 4U

struct concurrent_producer {
	uint64_t tokens[CONCURRENT_ATTEMPTS];
	bool recorded[CONCURRENT_ATTEMPTS];
	unsigned attempts;
	bool mint_only;
	unsigned accepted;
	unsigned minted;
};

static struct concurrent_producer concurrent_producers[CONCURRENT_THREADS];
static atomic_uint producers_ready;
static unsigned positions[CONCURRENT_ATTEMPTS * 8U + 1U];
static uint64_t concurrent_attempted, concurrent_recorded, concurrent_minted;
static uint64_t expected_overflow, concurrent_elapsed_ns;
static unsigned concurrent_scenarios;

static void *concurrent_run(void *opaque)
{
	struct concurrent_producer *producer_state = opaque;

	atomic_fetch_add_explicit(&producers_ready, 1U, memory_order_release);
	while (!atomic_load_explicit(&go, memory_order_acquire))
		;
	for (unsigned index = 0; index < producer_state->attempts; ++index) {
		uint64_t token = swapz_observation_mint(&recorder);

		producer_state->tokens[index] = token;
		if (!token)
			continue;
		++producer_state->minted;
		if (producer_state->mint_only)
			continue;
		const struct swapz_observation_record record = {
			.operation = token, .event = SWAPZ_OBS_PREPARATION, .flags = 1,
		};
		producer_state->recorded[index] = swapz_observation_append(&recorder, &record);
		if (producer_state->recorded[index])
			++producer_state->accepted;
	}
	return NULL;
}

static uint64_t wire_u64(const uint8_t *bytes)
{
	uint64_t value = 0;

	for (unsigned index = 0; index < 8U; ++index)
		value |= (uint64_t)bytes[index] << (index * 8U);
	return value;
}

struct export_check {
	unsigned next;
	unsigned count;
	unsigned loss;
	unsigned token_high;
	bool complete;
};

/* Verify actual exported reservation order without reusing the old semantic
 * corpus. The stream is deliberately synthetic, not valid native evidence.
 */
static bool verify_export(void *opaque, const uint8_t *bytes, size_t length)
{
	struct export_check *context = opaque;

	if (!context->next) {
		check(length == SWAPZ_OBSERVATION_HEADER_BYTES);
		check(memcmp(bytes, "SWZOBS2\0", 8) == 0);
		check(wire_u64(bytes + 80) == context->count);
		check(wire_u64(bytes + 88) == context->token_high);
	} else if (context->next <= context->count) {
		check(length == SWAPZ_OBSERVATION_RECORD_BYTES);
		check(wire_u64(bytes) == context->next);
		check(wire_u64(bytes + 8) == storage[context->next - 1U].operation);
	} else {
		check(!context->complete);
		check(length == SWAPZ_OBSERVATION_FOOTER_BYTES);
		check(memcmp(bytes, "SWZEND2\0", 8) == 0);
		check(wire_u64(bytes + 8) == context->count);
		check(wire_u64(bytes + 16) == context->loss);
		context->complete = true;
	}
	++context->next;
	return true;
}

static void concurrent_case(const uint8_t scope[32], unsigned thread_count,
			    unsigned capacity, bool mint_only)
{
	const unsigned attempts = CONCURRENT_ATTEMPTS;
	const unsigned token_limit = capacity * 8U;
	const unsigned wanted_tokens = attempts < token_limit ? attempts : token_limit;
	const unsigned wanted_records = mint_only ? 0U :
		(wanted_tokens < capacity ? wanted_tokens : capacity);
	const unsigned wanted_loss = wanted_tokens < attempts ||
		(!mint_only && wanted_records < wanted_tokens) ? SWAPZ_OBS_LOST_OVERFLOW : 0U;
	pthread_t threads[CONCURRENT_THREADS];

	check(swapz_observation_init(&recorder, storage, capacity, scope));
	memset(concurrent_producers, 0, sizeof(concurrent_producers));
	memset(positions, 0, sizeof(positions));
	atomic_init(&go, false);
	atomic_init(&producers_ready, 0U);
	for (unsigned thread_index = 0; thread_index < thread_count; ++thread_index) {
		struct concurrent_producer *producer_state = &concurrent_producers[thread_index];

		producer_state->attempts = attempts / thread_count;
		producer_state->mint_only = mint_only;
		CHECK(pthread_create(&threads[thread_index], NULL, concurrent_run, producer_state) == 0);
	}
	while (atomic_load_explicit(&producers_ready, memory_order_acquire) != thread_count)
		;
	const uint64_t start = monotonic_ns();
	atomic_store_explicit(&go, true, memory_order_release);
	for (unsigned thread_index = 0; thread_index < thread_count; ++thread_index)
		CHECK(pthread_join(threads[thread_index], NULL) == 0);
	const uint64_t elapsed = monotonic_ns() - start;
	const unsigned count = atomic_load(&recorder.count);
	const unsigned high = atomic_load(&recorder.token_high);
	const unsigned loss = atomic_load(&recorder.loss);
	/* Print actual observations before assertions so loss cannot be hidden. */
	printf("CONCURRENT_CASE threads=%u capacity=%u mint_only=%u attempts=%u "
	       "minted=%u recorded=%u loss=%u elapsed_ns=%" PRIu64 "\n",
	       thread_count, capacity, mint_only ? 1U : 0U, attempts, high, count, loss, elapsed);
	CHECK(fflush(stdout) == 0);
	check(count == wanted_records && high == wanted_tokens && loss == wanted_loss);
	for (unsigned index = 0; index < count; ++index) {
		const struct swapz_observation_record *record = &storage[index];

		check(record->sequence == (uint64_t)index + 1U);
		check(record->operation > 0 && record->operation <= high);
		check(record->event == SWAPZ_OBS_PREPARATION && record->flags == 1);
		check(positions[record->operation] == 0);
		positions[record->operation] = index + 1U;
	}
	/* Every minted token is unique, every successful append appears exactly
	 * once, and each producer's program order survives cross-thread overlap.
	 */
	unsigned minted = 0, accepted = 0;
	for (unsigned thread_index = 0; thread_index < thread_count; ++thread_index) {
		const struct concurrent_producer *producer_state = &concurrent_producers[thread_index];
		unsigned last_position = 0, producer_minted = 0, producer_accepted = 0;
		uint64_t last_token = 0;

		for (unsigned index = 0; index < producer_state->attempts; ++index) {
			const uint64_t token = producer_state->tokens[index];

			if (!token) {
				check(!producer_state->recorded[index]);
				continue;
			}
			check(token > last_token && token <= high);
			last_token = token;
			const unsigned position = positions[token];
			if (producer_state->recorded[index]) {
				check(position > last_position && position <= count);
				last_position = position;
				++producer_accepted;
			} else {
				check(position == 0);
			}
			/* Mark every consumed token, including those never recorded. */
			positions[token] = UINT_MAX;
			++producer_minted;
		}
		check(producer_minted == producer_state->minted);
		check(producer_accepted == producer_state->accepted);
		minted += producer_minted;
		accepted += producer_accepted;
	}
	check(minted == high && accepted == count);
	for (unsigned token = 1; token <= high; ++token)
		check(positions[token] == UINT_MAX);
	swapz_observation_stop(&recorder);
	check(swapz_observation_seal(&recorder));
	struct export_check context = {.count = count, .loss = loss, .token_high = high};
	check(swapz_observation_export(&recorder, verify_export, &context));
	check(context.complete && context.next == count + 2U);
	concurrent_attempted += attempts;
	concurrent_minted += minted;
	concurrent_recorded += accepted;
	if (wanted_loss)
		expected_overflow += mint_only ? attempts - minted : attempts - accepted;
	concurrent_elapsed_ns += elapsed;
	++concurrent_scenarios;
}

static void concurrency_test(const uint8_t scope[32])
{
	for (unsigned round = 0; round < CONCURRENT_ROUNDS; ++round) {
		concurrent_case(scope, 2U, CONCURRENT_ATTEMPTS, false);
		concurrent_case(scope, 4U, CONCURRENT_ATTEMPTS, false);
		concurrent_case(scope, 8U, CONCURRENT_ATTEMPTS, false);
	}
	concurrent_case(scope, 8U, 1024U, false);
	concurrent_case(scope, 8U, 256U, true);

	/* Inject an abandoned reservation only after producer quiescence.
	 * A seal with an uncommitted marker cannot publish fabricated records.
	 */
	check(swapz_observation_init(&recorder, storage, 2U, scope));
	atomic_store(&recorder.count, 1U);
	swapz_observation_stop(&recorder);
	check(!swapz_observation_seal(&recorder));
	check((atomic_load(&recorder.loss) & SWAPZ_OBS_LOST_INVALID) != 0);
	check(!swapz_observation_export(&recorder, reject_sink, NULL));

	/* Reinitialization must clear prior sequence markers and loss. */
	check(swapz_observation_init(&recorder, storage, 2U, scope));
	const uint64_t token = mint();
	const struct swapz_observation_record record = {
		.operation = token, .event = SWAPZ_OBS_PREPARATION, .flags = 1,
	};
	check(swapz_observation_append(&recorder, &record));
	check(storage[0].sequence == 1 && storage[1].sequence == 0);
	check(atomic_load(&recorder.loss) == 0);
	swapz_observation_stop(&recorder);
	check(swapz_observation_seal(&recorder));
	check(!swapz_observation_append(&recorder, &record));
	check(atomic_load(&recorder.count) == 1);
	check(atomic_load(&recorder.loss) == 0);

	printf("CONCURRENT_METRICS checks=%" PRIu64 " scenarios=%u attempted=%" PRIu64
	       " minted=%" PRIu64 " recorded=%" PRIu64 " expected_overflow=%" PRIu64
	       " elapsed_ns=%" PRIu64 " record_bytes=%zu owner_bytes=%zu "
	       "reservation_attempts=%u\n", checks, concurrent_scenarios,
	       concurrent_attempted, concurrent_minted, concurrent_recorded,
	       expected_overflow, concurrent_elapsed_ns, sizeof(storage[0]), sizeof(recorder),
	       SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
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
	else if (strcmp(argv[1], "concurrent") == 0)
		concurrency_test(scope);
	else
		return EXIT_FAILURE;
	return EXIT_SUCCESS;
}
