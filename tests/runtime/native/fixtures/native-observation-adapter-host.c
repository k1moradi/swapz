/* SPDX-License-Identifier: GPL-2.0-only */
/* Source-linked native adapter with explicit host substitutes for Linux APIs. */
#include "native-observation-adapter.h"
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static pthread_rwlock_t model_rcu = PTHREAD_RWLOCK_INITIALIZER;
static atomic_uint attempts, readers;
static atomic_bool force_contention, pause_reservation, pause_pre_entry;
static atomic_bool writer_paused, release_writer, grace_started, stop_finished;
static atomic_t *pause_counter;
static unsigned checks, scenarios;

#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "adapter check failed at line %d: %s\n", __LINE__, #condition); \
		exit(1); \
	} \
} while (0)

static void wait_true(const atomic_bool *flag)
{
	while (!atomic_load_explicit(flag, memory_order_acquire))
		sched_yield();
}

static void pause_writer(void)
{
	atomic_store_explicit(&writer_paused, true, memory_order_release);
	wait_true(&release_writer);
}

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	(void)atomic_fetch_add_explicit(&attempts, 1U, memory_order_relaxed);
	if (atomic_load_explicit(&force_contention, memory_order_relaxed)) {
		*previous = atomic_read(counter);
		return false;
	}
	bool success = atomic_compare_exchange_strong_explicit(&counter->value,
		previous, next, memory_order_relaxed, memory_order_relaxed);
	if (success && counter == pause_counter &&
	    atomic_load_explicit(&pause_reservation, memory_order_relaxed))
		pause_writer();
	return success;
}

void model_read_lock(void)
{
	(void)atomic_fetch_add_explicit(&readers, 1U, memory_order_relaxed);
	if (atomic_load_explicit(&pause_pre_entry, memory_order_relaxed))
		pause_writer();
	if (pthread_rwlock_rdlock(&model_rcu))
		abort();
}

void model_read_unlock(void)
{
	if (pthread_rwlock_unlock(&model_rcu))
		abort();
}

void model_synchronize_rcu(void)
{
	atomic_store_explicit(&grace_started, true, memory_order_release);
	if (pthread_rwlock_wrlock(&model_rcu) || pthread_rwlock_unlock(&model_rcu))
		abort();
}

struct trial {
	struct swapz_observation_gate gate;
	struct swapz_observation_recorder recorder;
	struct swapz_observation_record records[2];
	struct swapz_observation_record event;
	bool writer_result;
	bool stop_result;
};

static void setup(struct trial *trial)
{
	static const u8 scope[32] = {1};
	memset(trial, 0, sizeof(*trial));
	swapz_observation_gate_init(&trial->gate);
	CHECK(swapz_observation_init(&trial->recorder, trial->records, 2, scope));
	CHECK(!swapz_observation_append(&trial->gate, NULL));
	CHECK(!swapz_observation_seal(&trial->recorder));
	CHECK(swapz_observation_publish(&trial->gate, &trial->recorder));
	CHECK(!swapz_observation_publish(&trial->gate, &trial->recorder));
	trial->event.operation = swapz_observation_mint(&trial->gate);
	CHECK(trial->event.operation == 1);
	trial->event.event = SWAPZ_OBS_DISPATCH;
	trial->event.flags = 1;
}

static void reset_pause(void)
{
	atomic_store(&writer_paused, false);
	atomic_store(&release_writer, false);
	atomic_store(&grace_started, false);
	atomic_store(&stop_finished, false);
}

static void *writer(void *context)
{
	struct trial *trial = context;
	trial->writer_result = swapz_observation_append(&trial->gate, &trial->event);
	return NULL;
}

static void *stopper(void *context)
{
	struct trial *trial = context;
	trial->stop_result = swapz_observation_stop(&trial->gate);
	atomic_store_explicit(&stop_finished, true, memory_order_release);
	return NULL;
}

struct output {
	u8 bytes[104 + 2 * 296 + 24];
	size_t length;
	unsigned calls;
	unsigned fail_call;
};

static bool sink(void *context, const u8 *bytes, size_t length)
{
	struct output *output = context;
	++output->calls;
	if (output->calls == output->fail_call ||
	    length > sizeof(output->bytes) - output->length)
		return false;
	memcpy(output->bytes + output->length, bytes, length);
	output->length += length;
	return true;
}

static void check_one_wire(const struct trial *trial, u8 loss)
{
	struct output output = {0};
	u8 expected[104 + 296 + 24] = {0};
	memcpy(expected, "SWZOBS2\0", 8);
	memcpy(expected + 8, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40);
	expected[48] = 1; /* scope digest */
	expected[80] = 1; /* record count */
	expected[88] = 1; /* token high water */
	expected[96] = 2; /* capacity */
	expected[100] = 40; expected[101] = 1; /* 296 little endian */
	expected[104] = 1; /* sequence */
	expected[112] = 1; /* operation */
	expected[104 + 13 * 8] = SWAPZ_OBS_DISPATCH;
	expected[104 + 13 * 8 + 16 * 4] = 1; /* flags */
	memcpy(expected + 400, "SWZEND2\0", 8);
	expected[408] = 1;
	expected[416] = loss;
	CHECK(swapz_observation_export(&trial->recorder, sink, &output));
	CHECK(output.calls == 3);
	CHECK(output.length == sizeof(expected));
	CHECK(!memcmp(output.bytes, expected, sizeof(expected)));
	output = (struct output){.fail_call = 2};
	CHECK(!swapz_observation_export(&trial->recorder, sink, &output));
	CHECK(output.calls == 2 && output.length == 104);
}

static void stop_paused_writer(void)
{
	struct trial trial;
	pthread_t producer, stop;
	setup(&trial);
	reset_pause();
	pause_counter = &trial.recorder.count;
	atomic_store(&pause_reservation, true);
	CHECK(!pthread_create(&producer, NULL, writer, &trial));
	wait_true(&writer_paused);
	CHECK(atomic_read(&trial.recorder.count) == 1);
	/* The writer is paused after successful reservation, before slot copy. */
	CHECK(!swapz_observation_seal(&trial.recorder));
	CHECK(!pthread_create(&stop, NULL, stopper, &trial));
	wait_true(&grace_started);
	CHECK(!atomic_load_explicit(&stop_finished, memory_order_acquire));
	CHECK(!swapz_observation_append(&trial.gate, NULL));
	atomic_store_explicit(&release_writer, true, memory_order_release);
	CHECK(!pthread_join(producer, NULL));
	CHECK(!pthread_join(stop, NULL));
	atomic_store(&pause_reservation, false);
	pause_counter = NULL;
	CHECK(!trial.writer_result && trial.stop_result);
	CHECK(atomic_read(&trial.recorder.loss) == SWAPZ_OBS_LOST_LATE);
	CHECK(trial.records[0].sequence == 1);
	CHECK(!trial.gate.retained);
	CHECK(swapz_observation_stop(&trial.gate));
	CHECK(!swapz_observation_publish(&trial.gate, &trial.recorder));
	CHECK(swapz_observation_seal(&trial.recorder));
	check_one_wire(&trial, SWAPZ_OBS_LOST_LATE);
	++scenarios;
}

static void stop_pre_entry(void)
{
	struct trial trial;
	pthread_t producer;
	setup(&trial);
	reset_pause();
	atomic_store(&pause_pre_entry, true);
	CHECK(!pthread_create(&producer, NULL, writer, &trial));
	wait_true(&writer_paused);
	/* Paused before acquiring modeled RCU: stop need not wait for gate-only
	 * caller. Gate lifetime still spans the join below. */
	CHECK(swapz_observation_stop(&trial.gate));
	CHECK(swapz_observation_seal(&trial.recorder));
	CHECK(atomic_read(&trial.recorder.count) == 0);
	CHECK(!trial.gate.retained);
	atomic_store_explicit(&release_writer, true, memory_order_release);
	CHECK(!pthread_join(producer, NULL));
	atomic_store(&pause_pre_entry, false);
	CHECK(!trial.writer_result);
	CHECK(atomic_read(&trial.recorder.count) == 0);
	CHECK(atomic_read(&trial.recorder.loss) == 0);
	++scenarios;
}

static void unpublished_slot(void)
{
	struct trial trial;
	struct output output = {0};
	setup(&trial);
	CHECK(swapz_observation_stop(&trial.gate));
	/* Inject a hole after drain; not a native writer or product fault. */
	atomic_set(&trial.recorder.count, 1);
	CHECK(!swapz_observation_seal(&trial.recorder));
	CHECK(!swapz_observation_export(&trial.recorder, sink, &output));
	CHECK(output.calls == 0);
	CHECK(atomic_read(&trial.recorder.loss) == SWAPZ_OBS_LOST_INVALID);
	++scenarios;
}

static void exhaustion_and_overflow(void)
{
	struct trial trial;
	setup(&trial);
	unsigned before = atomic_load(&attempts);
	atomic_store(&force_contention, true);
	CHECK(!swapz_observation_append(&trial.gate, &trial.event));
	CHECK(atomic_load(&attempts) - before == SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
	CHECK(atomic_read(&trial.recorder.count) == 0);
	before = atomic_load(&attempts);
	CHECK(!swapz_observation_mint(&trial.gate));
	CHECK(atomic_load(&attempts) - before == SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
	CHECK(atomic_read(&trial.recorder.token_high) == 1);
	atomic_store(&force_contention, false);
	CHECK(swapz_observation_append(&trial.gate, &trial.event));
	CHECK(swapz_observation_append(&trial.gate, &trial.event));
	CHECK(!swapz_observation_append(&trial.gate, &trial.event));
	CHECK(atomic_read(&trial.recorder.count) == 2);
	CHECK(atomic_read(&trial.recorder.loss) ==
		(SWAPZ_OBS_LOST_CONTENTION | SWAPZ_OBS_LOST_OVERFLOW));
	CHECK(swapz_observation_stop(&trial.gate));
	CHECK(swapz_observation_seal(&trial.recorder));
	++scenarios;
}

static void disabled_and_clean_wire(void)
{
	struct trial trial;
	struct timespec start, end;
	setup(&trial);
	CHECK(swapz_observation_append(&trial.gate, &trial.event));
	CHECK(swapz_observation_stop(&trial.gate));
	CHECK(swapz_observation_seal(&trial.recorder));
	check_one_wire(&trial, 0);
	unsigned old_readers = atomic_load(&readers);
	unsigned old_attempts = atomic_load(&attempts);
	CHECK(!clock_gettime(CLOCK_MONOTONIC, &start));
	for (unsigned index = 0; index < 100000U; ++index) {
		CHECK(!swapz_observation_append(&trial.gate, NULL));
		CHECK(!swapz_observation_mint(&trial.gate));
	}
	CHECK(!clock_gettime(CLOCK_MONOTONIC, &end));
	CHECK(atomic_load(&readers) == old_readers);
	CHECK(atomic_load(&attempts) == old_attempts);
	CHECK(atomic_read(&trial.recorder.loss) == 0);
	long long elapsed = (long long)(end.tv_sec - start.tv_sec) * 1000000000LL +
		(long long)(end.tv_nsec - start.tv_nsec);
	printf("disabled_calls=200000 disabled_rcu_entries=0 disabled_cas_attempts=0 elapsed_ns=%lld (host only; includes checks)\n", elapsed);
	++scenarios;
}

int main(void)
{
	stop_paused_writer();
	stop_pre_entry();
	unpublished_slot();
	exhaustion_and_overflow();
	disabled_and_clean_wire();
	printf("checks=%u scenarios=%u owner_bytes=%zu gate_bytes=%zu record_bytes=%zu wire_bytes=296 auth=0 native_capture=0 host_substitutes=1\n",
		checks, scenarios, sizeof(struct swapz_observation_recorder),
		sizeof(struct swapz_observation_gate), sizeof(struct swapz_observation_record));
	return 0;
}
