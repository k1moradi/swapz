/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-kernel-shim.h"
#include "native-observation-recorder.h"
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>

_Atomic unsigned shim_reads, shim_cas, shim_acquires, shim_ors;
const atomic_t *shim_fail_cas;
static pthread_mutex_t pause_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pause_cond = PTHREAD_COND_INITIALIZER;
static const void *pause_address;
static bool paused, resume_writer;
static unsigned checks;
#define CHECK(expression) do { \
	++checks; \
	if (!(expression)) { \
		fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #expression); \
		exit(EXIT_FAILURE); \
	} \
} while (0)

void shim_before_release(const void *address)
{
	if (address != pause_address)
		return;
	if (pthread_mutex_lock(&pause_lock))
		abort();
	paused = true;
	if (pthread_cond_broadcast(&pause_cond))
		abort();
	while (!resume_writer)
		if (pthread_cond_wait(&pause_cond, &pause_lock))
			abort();
	if (pthread_mutex_unlock(&pause_lock))
		abort();
}

static const u8 scope[32] = { 1 };
static const struct swapz_native_observation_record cleanup = {
	.event = SWAPZ_OBS_CLEANUP,
};
static bool joined(void *context)
{
	return *(const bool *)context;
}
static void *writer(void *context)
{
	if (swapz_native_observation_append(context, &cleanup))
		abort(); /* late stop must be reported */
	return NULL;
}

struct wire_output {
	u8 bytes[SWAPZ_OBSERVATION_HEADER_BYTES + 2U * SWAPZ_OBSERVATION_RECORD_BYTES +
		SWAPZ_OBSERVATION_FOOTER_BYTES];
	size_t length;
	size_t limit;
};
static bool sink(void *context, const u8 *bytes, size_t length)
{
	struct wire_output *wire = context;
	if (length > wire->limit - wire->length)
		return false;
	memcpy(wire->bytes + wire->length, bytes, length);
	wire->length += length;
	return true;
}

int main(void)
{
	struct swapz_native_observation_recorder recorder;
	struct swapz_native_observation_slot slots[2];
	pthread_t thread;
	bool external_join = false;
	struct wire_output wire = { .limit = sizeof(wire.bytes) };
	unsigned reads, cas, acquires, ors;
	size_t footer;

	CHECK(!swapz_native_observation_init(&recorder, slots, 0, scope));
	CHECK(swapz_native_observation_init(&recorder, slots, 2, scope));
	reads = atomic_load(&shim_reads);
	cas = atomic_load(&shim_cas);
	acquires = atomic_load(&shim_acquires);
	ors = atomic_load(&shim_ors);
	CHECK(!swapz_native_observation_append(&recorder, NULL));
	CHECK(!swapz_native_observation_mint(&recorder));
	CHECK(atomic_load(&shim_reads) == reads);
	CHECK(atomic_load(&shim_cas) == cas);
	CHECK(atomic_load(&shim_ors) == ors);
	CHECK(atomic_load(&shim_acquires) == acquires + 2);
	CHECK(swapz_native_observation_start(&recorder));
	CHECK(!swapz_native_observation_start(&recorder));
	CHECK(swapz_native_observation_mint(&recorder) == 1);
	CHECK(!swapz_native_observation_drain(&recorder, joined, &external_join));
	pause_address = &slots[0].published;
	CHECK(pthread_create(&thread, NULL, writer, &recorder) == 0);
	CHECK(pthread_mutex_lock(&pause_lock) == 0);
	while (!paused)
		CHECK(pthread_cond_wait(&pause_cond, &pause_lock) == 0);
	CHECK(pthread_mutex_unlock(&pause_lock) == 0);
	CHECK(smp_load_acquire(&slots[0].published) == 0);
	CHECK(swapz_native_observation_append(&recorder, &cleanup));
	CHECK(smp_load_acquire(&slots[1].published) == 2);
	swapz_native_observation_stop(&recorder);
	CHECK(!swapz_native_observation_start(&recorder));
	CHECK(!swapz_native_observation_seal(&recorder));
	CHECK(!swapz_native_observation_drain(&recorder, joined, &external_join));
	CHECK(!swapz_native_observation_export(&recorder, sink, &wire));
	CHECK(pthread_mutex_lock(&pause_lock) == 0);
	resume_writer = true;
	CHECK(pthread_cond_broadcast(&pause_cond) == 0);
	CHECK(pthread_mutex_unlock(&pause_lock) == 0);
	CHECK(pthread_join(thread, NULL) == 0);
	pause_address = NULL;
	external_join = true;
	CHECK(swapz_native_observation_drain(&recorder, joined, &external_join));
	CHECK(swapz_native_observation_seal(&recorder));
	CHECK(smp_load_acquire(&slots[0].published) == 1);
	CHECK(atomic_read(&recorder.loss) == SWAPZ_OBS_LOST_LATE);
	CHECK(swapz_native_observation_export(&recorder, sink, &wire));
	CHECK(wire.length == sizeof(wire.bytes));
	CHECK(!memcmp(wire.bytes, "SWZOBS2\0", 8));
	CHECK(!memcmp(wire.bytes + 8, SWAPZ_OBSERVATION_MAPPING_SOURCE, 40));
	CHECK(wire.bytes[80] == 2 && wire.bytes[88] == 1);
	CHECK(wire.bytes[96] == 2 && wire.bytes[100] == 40 && wire.bytes[101] == 1);
	CHECK(wire.bytes[104] == 1 && wire.bytes[400] == 2);
	CHECK(wire.bytes[104 + 104] == SWAPZ_OBS_CLEANUP);
	footer = wire.length - SWAPZ_OBSERVATION_FOOTER_BYTES;
	CHECK(!memcmp(wire.bytes + footer, "SWZEND2\0", 8));
	CHECK(wire.bytes[footer + 8] == 2 && wire.bytes[footer + 16] == SWAPZ_OBS_LOST_LATE);
	wire.length = 0;
	wire.limit = SWAPZ_OBSERVATION_HEADER_BYTES;
	CHECK(!swapz_native_observation_export(&recorder, sink, &wire));

	/* Quiescent unpublished reservation must never be exported. */
	CHECK(swapz_native_observation_init(&recorder, slots, 2, scope));
	CHECK(swapz_native_observation_start(&recorder));
	atomic_set(&recorder.count, 1);
	swapz_native_observation_stop(&recorder);
	CHECK(swapz_native_observation_drain(&recorder, joined, &external_join));
	CHECK(!swapz_native_observation_seal(&recorder));
	CHECK(atomic_read(&recorder.loss) == SWAPZ_OBS_LOST_INVALID);

	/* Deterministic exhaustion: shim refuses exactly the fixed CAS budget. */
	CHECK(swapz_native_observation_init(&recorder, slots, 1, scope));
	CHECK(swapz_native_observation_start(&recorder));
	shim_fail_cas = &recorder.count;
	cas = atomic_load(&shim_cas);
	CHECK(!swapz_native_observation_append(&recorder, &cleanup));
	CHECK(atomic_load(&shim_cas) - cas == SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
	CHECK(atomic_read(&recorder.count) == 0);
	CHECK(atomic_read(&recorder.loss) == SWAPZ_OBS_LOST_CONTENTION);
	shim_fail_cas = &recorder.token_high;
	cas = atomic_load(&shim_cas);
	CHECK(!swapz_native_observation_mint(&recorder));
	CHECK(atomic_load(&shim_cas) - cas == SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
	shim_fail_cas = NULL;
	CHECK(swapz_native_observation_append(&recorder, &cleanup));
	CHECK(!swapz_native_observation_append(&recorder, &cleanup));
	CHECK(atomic_read(&recorder.count) == 1);
	CHECK(atomic_read(&recorder.loss) == (SWAPZ_OBS_LOST_CONTENTION | SWAPZ_OBS_LOST_OVERFLOW));
	swapz_native_observation_stop(&recorder);
	CHECK(swapz_native_observation_drain(&recorder, joined, &external_join));
	CHECK(swapz_native_observation_seal(&recorder));
	printf("{\"checks\":%u,\"scenarios\":3,\"native_kernel_execution\":false,\"physical_io\":false}\n", checks);
	return EXIT_SUCCESS;
}
