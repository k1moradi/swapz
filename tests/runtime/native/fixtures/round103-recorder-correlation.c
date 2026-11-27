/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual adapter/owner/collector with modeled host RCU and test buffers only. */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include "native-observation-byte-collector.h"
#include <inttypes.h>
#include <openssl/sha.h>
#include <sched.h>

static pthread_rwlock_t rcu = PTHREAD_RWLOCK_INITIALIZER;
static atomic_bool pause_first, paused, proceed, grace, contention;
static atomic_uint attempts, readers;
static atomic_t *pause_counter;

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	(void)atomic_fetch_add(&attempts, 1U);
	if (atomic_load(&contention)) {
		*previous = atomic_read(counter);
		return false;
	}
	bool ok = atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
							  memory_order_relaxed, memory_order_relaxed);
	if (ok && counter == pause_counter && atomic_exchange(&pause_first, false)) {
		atomic_store(&paused, true);
		while (!atomic_load(&proceed))
			sched_yield();
	}
	return ok;
}
void model_read_lock(void)
{
	(void)atomic_fetch_add(&readers, 1U);
	assert(!pthread_rwlock_rdlock(&rcu));
}
void model_read_unlock(void) { assert(!pthread_rwlock_unlock(&rcu)); }
void model_synchronize_rcu(void)
{
	atomic_store(&grace, true);
	assert(!pthread_rwlock_wrlock(&rcu));
	assert(!pthread_rwlock_unlock(&rcu));
}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	return calloc(count, size);
}
void model_kvfree(void *pointer) { free(pointer); }
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	assert(SHA256(bytes, length, digest));
}

struct trial {
	struct swapz_observation_gate gate;
	struct swapz_observation_recorder recorder;
	struct swapz_observation_record slots[3];
	struct swapz_observation_record event;
	u64 ordinal;
};
static void init(struct trial *trial)
{
	const u8 scope[32] = {1};
	memset(trial, 0, sizeof(*trial));
	swapz_observation_gate_init(&trial->gate);
	assert(swapz_observation_init(&trial->recorder, trial->slots, 3, scope));
	assert(swapz_observation_publish(&trial->gate, &trial->recorder));
	trial->event.operation = swapz_observation_mint(&trial->gate);
	assert(trial->event.operation == 1);
	trial->event.event = SWAPZ_OBS_DISPATCH;
	trial->event.flags = 1;
	trial->ordinal = UINT64_MAX;
	atomic_store(&paused, false);
	atomic_store(&proceed, false);
	atomic_store(&grace, false);
}
static void *producer(void *context)
{
	struct trial *trial = context;
	trial->ordinal = swapz_observation_append_sequence(&trial->gate, &trial->event);
	return NULL;
}
static void *stopper(void *context)
{
	struct trial *trial = context;
	assert(swapz_observation_stop(&trial->gate));
	return NULL;
}
static bool joined(void *context) { return context != NULL; }

static void sequence_cases(void)
{
	struct trial trial;
	pthread_t first, stop;
	u64 ordinal;
	unsigned before;
	init(&trial);
	pause_counter = &trial.recorder.count;
	atomic_store(&pause_first, true);
	assert(!pthread_create(&first, NULL, producer, &trial));
	while (!atomic_load(&paused))
		sched_yield();
	assert(atomic_read(&trial.recorder.count) == 1);
	assert(trial.slots[0].sequence == 0);
	/* A different producer publishes slot 2 before slot 1. Its returned
	 * ordinal is 2, not a completion ordinal or a later shared count. */
	struct swapz_observation_record second = trial.event;
	second.flags = 2;
	ordinal = swapz_observation_append_sequence(&trial.gate, &second);
	assert(ordinal == 2 && trial.slots[1].sequence == 2);
	assert(trial.slots[1].flags == 2 && trial.slots[0].sequence == 0);
	atomic_store(&proceed, true);
	assert(!pthread_join(first, NULL));
	assert(trial.ordinal == 1 && trial.slots[0].sequence == 1);
	assert(trial.slots[0].flags == 1);
	assert(swapz_observation_append(&trial.gate, &trial.event));
	assert(trial.slots[2].sequence == 3);
	ordinal = swapz_observation_append_sequence(&trial.gate, &trial.event);
	assert(!ordinal && atomic_read(&trial.recorder.count) == 3);
	assert(atomic_read(&trial.recorder.loss) == SWAPZ_OBS_LOST_OVERFLOW);
	assert(swapz_observation_stop(&trial.gate));
	assert(swapz_observation_seal(&trial.recorder));

	init(&trial);
	/* Caller must not reuse a committed record with nonzero sequence. */
	struct swapz_observation_record invalid = trial.event;
	invalid.sequence = 1;
	ordinal = UINT64_MAX;
	ordinal = swapz_observation_append_sequence(&trial.gate, &invalid);
	assert(!ordinal && atomic_read(&trial.recorder.count) == 0);
	assert(!swapz_observation_append_sequence(&trial.gate, NULL));
	atomic_store(&contention, true);
	before = atomic_load(&attempts);
	assert(!swapz_observation_append_sequence(&trial.gate, &trial.event));
	assert(atomic_load(&attempts) - before == SWAPZ_OBSERVATION_RESERVATION_ATTEMPTS);
	atomic_store(&contention, false);
	assert(atomic_read(&trial.recorder.count) == 0);
	assert(atomic_read(&trial.recorder.loss) ==
	       (SWAPZ_OBS_LOST_INVALID | SWAPZ_OBS_LOST_CONTENTION));
	assert(swapz_observation_append_sequence(&trial.gate, &trial.event) == 1);
	assert(swapz_observation_stop(&trial.gate));

	init(&trial);
	pause_counter = &trial.recorder.count;
	atomic_store(&pause_first, true);
	assert(!pthread_create(&first, NULL, producer, &trial));
	while (!atomic_load(&paused))
		sched_yield();
	assert(!pthread_create(&stop, NULL, stopper, &trial));
	while (!atomic_load(&grace))
		sched_yield();
	before = atomic_load(&readers);
	assert(!swapz_observation_append_sequence(&trial.gate, &trial.event));
	assert(atomic_load(&readers) == before);
	atomic_store(&proceed, true);
	assert(!pthread_join(first, NULL));
	assert(!pthread_join(stop, NULL));
	assert(trial.ordinal == 0 && trial.slots[0].sequence == 1);
	assert(atomic_read(&trial.recorder.loss) == SWAPZ_OBS_LOST_LATE);
	assert(swapz_observation_seal(&trial.recorder));
	pause_counter = NULL;

	/* The actual built-in wrapper shares one recorder and bool ABI. */
	struct swapz_trial_observation_scope scope = {
		.session = 1, .epoch = 2, .target_epoch = 3, .registration_epoch = 4,
		.first_logical = 7, .page_count = 1,
	};
	memcpy(scope.source, SWAPZ_OBSERVATION_BUILD_SOURCE, 40);
	memset(scope.kernel_sha256, '1', sizeof(scope.kernel_sha256));
	memset(scope.module_sha256, '2', sizeof(scope.module_sha256));
	memset(scope.workload_sha256, '3', sizeof(scope.workload_sha256));
	memset(scope.run_nonce, '4', sizeof(scope.run_nonce));
	memset(scope.target, '5', sizeof(scope.target));
	assert(!swapz_trial_observation_append_sequence(NULL));
	assert(swapz_trial_observation_start(&scope, 2));
	struct swapz_observation_record event = {.event = SWAPZ_OBS_CLEANUP, .flags = 7};
	assert(swapz_trial_observation_append_sequence(&event) == 1);
	assert(swapz_trial_observation_append(&event));
	assert(!swapz_trial_observation_append_sequence(&event));
	assert(!swapz_trial_observation_stop(joined, NULL));
	assert(!swapz_trial_observation_release());
	assert(swapz_trial_observation_stop(joined, &scope));
	assert(!swapz_trial_observation_append_sequence(&event));
	assert(swapz_trial_observation_release());
	puts("R103_ORDINAL_HOST_PASS reservation_order late_loss contention overflow invalid bool_owner missed_join AUTH=0");
}

static struct swapz_byte_collector *fresh(void)
{
	struct swapz_byte_collector *collector = calloc(1, sizeof(*collector));
	assert(collector && swapz_byte_start(collector, 7, 4));
	return collector;
}
static void free_collector(struct swapz_byte_collector *collector)
{
	assert(swapz_byte_release(collector));
	assert(!pthread_mutex_destroy(&collector->lock));
	free(collector);
}
static void collector_cases(void)
{
	const struct swapz_byte_record *records;
	unsigned int count;
	struct swapz_byte_collector *collector = fresh();
	unsigned char bytes[SWAPZ_BYTE_PAGE] = {9};
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, 7, 1, 2, bytes, sizeof(bytes)));
	assert(swapz_byte_accept(collector, 1, 2, 3, 4, 4));
	assert(swapz_byte_clone(collector, 1, 3, 4, 14, 0));
	assert(swapz_byte_upper(collector, 1, 2, 3, 4, 15, 0));
	assert(swapz_byte_complete(collector, 1, 2));
	assert(!swapz_byte_stop(collector, joined, NULL));
	assert(!swapz_byte_release(collector));
	assert(!swapz_byte_stop(collector, joined, collector));
	assert(!swapz_byte_export(collector, &records, &count) && !records && !count);
	free_collector(collector);

	collector = fresh();
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, 7, 1, 2, NULL, 0));
	assert(!swapz_byte_complete(collector, 1, 2));
	assert(!swapz_byte_stop(collector, joined, collector));
	assert(!swapz_byte_export(collector, &records, &count));
	free_collector(collector);

	collector = fresh();
	assert(swapz_byte_begin(collector, SWAPZ_BYTE_ERROR, 7, 1, 2, bytes, sizeof(bytes)));
	assert(swapz_byte_accept(collector, 1, 2, 3, 4, 4));
	assert(swapz_byte_clone(collector, 1, 3, 4, 14, 255));
	assert(!swapz_byte_upper(collector, 1, 2, 3, 4, 15, 5));
	assert(!swapz_byte_stop(collector, joined, collector));
	free_collector(collector);
	puts("R103_COLLECTOR_HOST_PASS missed_join premature_complete status_mismatch AUTH=0");
}

static bool wire_sink(void *context, const u8 *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}
static void hex_page(const unsigned char *page)
{
	if (!page) {
		fputs("null", stdout);
		return;
	}
	putchar('"');
	for (unsigned int index = 0; index < SWAPZ_BYTE_PAGE; ++index)
		printf("%02x", (unsigned int)page[index]);
	putchar('"');
}
static void emit(const struct swapz_byte_record *record)
{
	printf("{\"operation\":%" PRIu64 ",\"original\":%" PRIu64
	       ",\"clone\":%" PRIu64 ",\"descriptor\":%" PRIu64
	       ",\"pin\":%" PRIu64 ",\"accept_sequence\":%" PRIu64
	       ",\"pin_sequence\":%" PRIu64 ",\"copy_sequence\":%" PRIu64
	       ",\"release_sequence\":%" PRIu64 ",\"clone_sequence\":%" PRIu64
	       ",\"upper_sequence\":%" PRIu64 ",\"logical\":%" PRIu32
	       ",\"kind\":%u,\"status\":%u,\"input_page\":",
	       record->operation, record->original, record->clone, record->descriptor,
	       record->pin, record->accept_sequence, record->pin_sequence, record->copy_sequence,
	       record->release_sequence, record->clone_sequence, record->upper_sequence,
	       record->logical, (unsigned int)record->kind, record->user_status);
	hex_page(record->kind == SWAPZ_BYTE_WRITE ? record->input_page : NULL);
	fputs(",\"final_copy\":", stdout);
	hex_page(record->kind == SWAPZ_BYTE_READ ? record->final_copy : NULL);
	putchar('}');
}

/* Input is a fresh synthetic R099 two-operation test wire plus two actual
 * supplied host buffers. Never execute native I/O or read a user pointer.
 * Output wire is the actual selected adapter export, followed by private
 * JSON of the actual collector copies. No private bytes go to test logs.
 */
static void correlation(void)
{
	struct swapz_observation_gate gate;
	struct swapz_observation_recorder recorder;
	struct swapz_observation_record *slots = calloc(256, sizeof(*slots));
	struct swapz_byte_collector *collector = fresh();
	const struct swapz_byte_record *records;
	unsigned int count;
	u32 total, high;
	u8 scope[32], input[SWAPZ_BYTE_PAGE], final[SWAPZ_BYTE_PAGE];
	u64 operation = 0, original = 0, clone = 0, descriptor = 0;
	assert(slots);
	assert(fread(&total, sizeof(total), 1, stdin) == 1 && total <= 256);
	assert(fread(&high, sizeof(high), 1, stdin) == 1 && high <= 256);
	assert(fread(scope, 1, sizeof(scope), stdin) == sizeof(scope));
	assert(fread(input, 1, sizeof(input), stdin) == sizeof(input));
	assert(fread(final, 1, sizeof(final), stdin) == sizeof(final));
	swapz_observation_gate_init(&gate);
	assert(swapz_observation_init(&recorder, slots, 256, scope));
	assert(swapz_observation_publish(&gate, &recorder));
	for (u32 index = 1; index <= high; ++index)
		assert(swapz_observation_mint(&gate) == index);
	for (u32 index = 1; index <= total; ++index) {
		struct swapz_observation_record event;
		u64 sequence;
		assert(fread(&event, sizeof(event), 1, stdin) == 1 && !event.sequence);
		/* Synthetic only: the fixture supplies exact original tokens at
		 * its pre-compression capture boundary (before acceptance). */
		if (event.event == SWAPZ_OBS_CAPTURE) {
			assert(event.operation == 1);
			assert(swapz_byte_begin(collector, SWAPZ_BYTE_WRITE, event.logical,
						event.operation, 2, input, sizeof(input)));
			memset(input, 0, sizeof(input));
		}
		if (event.event == SWAPZ_OBS_ACCEPT && event.operation_kind == SWAPZ_OBS_TYPED_READ)
			assert(swapz_byte_begin(collector, SWAPZ_BYTE_READ, event.logical,
						event.operation, event.original, NULL, 0));
		sequence = swapz_observation_append_sequence(&gate, &event);
		assert(sequence == index);
		switch (event.event) {
		case SWAPZ_OBS_ACCEPT:
			operation = event.operation; original = event.original;
			clone = event.clone; descriptor = event.descriptor;
			assert(swapz_byte_accept(collector, operation, original, clone, descriptor, sequence));
			break;
		case SWAPZ_OBS_PIN:
			assert(swapz_byte_pin(collector, event.operation, descriptor, event.pin, sequence));
			break;
		case SWAPZ_OBS_ORACLE:
			assert(swapz_byte_copy(collector, event.operation, descriptor, event.pin,
					       sequence, final, sizeof(final)));
			memset(final, 0, sizeof(final));
			break;
		case SWAPZ_OBS_PIN_RELEASE:
			assert(swapz_byte_unpin(collector, event.operation, descriptor, event.pin, sequence));
			break;
		case SWAPZ_OBS_CLONE_ENDIO:
			assert(swapz_byte_clone(collector, event.operation, event.clone,
						event.descriptor, sequence, event.status));
			break;
		case SWAPZ_OBS_UPPER_ENDIO:
			assert(swapz_byte_upper(collector, event.operation, event.original,
						clone, descriptor, sequence, event.status));
			assert(swapz_byte_complete(collector, event.operation, event.original));
			break;
		default:
			break;
		}
	}
	assert(fgetc(stdin) == EOF);
	assert(swapz_byte_stop(collector, joined, collector));
	assert(swapz_observation_stop(&gate) && swapz_observation_seal(&recorder));
	assert(swapz_observation_export(&recorder, wire_sink, stdout));
	assert(swapz_byte_export(collector, &records, &count) && count == 2);
	putchar('[');
	emit(&records[0]);
	putchar(',');
	emit(&records[1]);
	puts("]");
	free_collector(collector);
	free(slots);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	if (!strcmp(argv[1], "sequence")) {
		sequence_cases();
		collector_cases();
	} else if (!strcmp(argv[1], "correlation")) {
		correlation();
	} else {
		return 2;
	}
	return ferror(stdout) ? 1 : 0;
}
