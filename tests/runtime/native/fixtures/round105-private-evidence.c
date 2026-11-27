/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual built-in owner/recorder/collector/bridge and frozen producer shapes, modeled host primitives.
 * The input wire and buffers are synthetic; stdout is private fixture data.
 */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include <inttypes.h>
#include <openssl/sha.h>
#include <sched.h>
#include "round105-producer-shapes.h"

static pthread_rwlock_t rcu = PTHREAD_RWLOCK_INITIALIZER;
static atomic_bool pause_next, paused, proceed;
static unsigned allocations, frees, fail_allocation, joins, exported;
static size_t allocated_sizes[4];
static void *allocated_pointers[4];
static unsigned int scrubbed;
static bool fail_join;

bool model_try_cmpxchg(atomic_t *counter, int *previous, int next)
{
	bool ok = atomic_compare_exchange_strong_explicit(&counter->value, previous, next,
							  memory_order_relaxed, memory_order_relaxed);
	if (ok && atomic_exchange(&pause_next, false)) {
		atomic_store(&paused, true);
		while (!atomic_load(&proceed))
			sched_yield();
	}
	return ok;
}
void model_read_lock(void) { assert(!pthread_rwlock_rdlock(&rcu)); }
void model_read_unlock(void) { assert(!pthread_rwlock_unlock(&rcu)); }
void model_synchronize_rcu(void)
{
	assert(!pthread_rwlock_wrlock(&rcu));
	assert(!pthread_rwlock_unlock(&rcu));
}
void *model_kvcalloc(size_t count, size_t size, int flags)
{
	(void)flags;
	++allocations;
	if (allocations == fail_allocation)
		return NULL;
	assert(allocations <= 4);
	void *pointer = calloc(count, size);
	allocated_sizes[allocations - 1U] = count * size;
	allocated_pointers[allocations - 1U] = pointer;
	return pointer;
}
void model_kvfree(void *pointer)
{
	++frees;
	/* Actual recorder and bridge allocations must be scrubbed after join. */
	for (unsigned int allocation = 2; allocation < 4; ++allocation) {
		if (pointer != allocated_pointers[allocation])
			continue;
		const u8 *bytes = pointer;
		for (size_t index = 0; index < allocated_sizes[allocation]; ++index)
			assert(!bytes[index]);
		++scrubbed;
	}
	free(pointer);
}
void sha256(const u8 *bytes, unsigned int length, u8 *digest)
{
	assert(SHA256(bytes, length, digest));
}

static bool join(void *context)
{
	assert(context);
	++joins;
	return !fail_join;
}
static bool wire_sink(void *context, const u8 *bytes, size_t length)
{
	return fwrite(bytes, 1, length, context) == length;
}
static bool reject_sink(void *context, const struct swapz_byte_record *record)
{
	(void)context;
	(void)record;
	++exported;
	return false;
}
struct failed_sink {
	unsigned int calls, fail_at;
};

static bool fail_sink(void *context, const u8 *bytes, size_t length)
{
	struct failed_sink *state = context;
	assert(bytes && length);
	return ++state->calls != state->fail_at;
}

static bool refuse_private(void)
{
	struct failed_sink sink = {.fail_at = 1};
	return !swapz_trial_observation_export_private(fail_sink, &sink) && !sink.calls;
}

struct paused_event {
	struct swapz_observation_record record;
	u64 ordinal;
	bool result;
};
static void *paused_append(void *context)
{
	struct paused_event *event = context;
	event->ordinal = swapz_trial_observation_append_sequence(&event->record);
	event->result = swapz_trial_byte_event(&event->record, event->ordinal, NULL, 0);
	return NULL;
}
static void race(struct swapz_observation_record *record)
{
	struct paused_event first = {.record = *record};
	struct swapz_observation_record second = {
		.event = SWAPZ_OBS_PREPARATION, .operation = record->operation, .flags = 1,
	};
	pthread_t producer;
	atomic_store(&pause_next, true);
	assert(!pthread_create(&producer, NULL, paused_append, &first));
	while (!atomic_load(&paused))
		sched_yield();
	u64 ordinal = swapz_trial_observation_append_sequence(&second);
	assert(ordinal == 2);
	/* Byte event cannot pretend the earlier reserved CAPTURE is already
	 * committed. Out-of-order processing loses evidence, never waits. */
	assert(!swapz_trial_byte_event(&second, ordinal, NULL, 0));
	atomic_store(&proceed, true);
	assert(!pthread_join(producer, NULL));
	assert(first.ordinal == 1 && !first.result);
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *mode = argv[1];
	bool clean = !strcmp(mode, "clean") || !strcmp(mode, "error") || !strcmp(mode, "wrong_copy");
	struct swapz_trial_observation_scope scope = {
		.session = 11, .epoch = 12, .target_epoch = 13, .registration_epoch = 14,
		.first_logical = 7, .page_count = 4,
	};
	u32 total, high;
	u8 page[SWAPZ_BYTE_PAGE], replacement[SWAPZ_BYTE_PAGE];
	bool rejected = false;
	memcpy(scope.source, SWAPZ_OBSERVATION_BUILD_SOURCE, 40);
	memset(scope.kernel_sha256, '1', sizeof(scope.kernel_sha256));
	memset(scope.module_sha256, '2', sizeof(scope.module_sha256));
	memset(scope.run_nonce, 'd', sizeof(scope.run_nonce));
	memset(scope.target, '3', sizeof(scope.target));
	assert(fread(&total, sizeof(total), 1, stdin) == 1 && total <= 256);
	assert(fread(&high, sizeof(high), 1, stdin) == 1 && high <= 256);
	assert(fread(scope.workload_sha256, 1, sizeof(scope.workload_sha256), stdin) ==
	       sizeof(scope.workload_sha256));
	assert(!swapz_trial_byte_active() && !swapz_trial_byte_event(NULL, 0, NULL, 0));
	assert(!swapz_trial_byte_stage_input(77, 2, 13, 7, NULL, 0));
	assert(!allocations);
	/* Actual second allocation failure: first allocation freed, neither gate
	 * published, retry valid only because no one-shot publication happened. */
	fail_allocation = 2;
	assert(!swapz_trial_observation_start(&scope, 256));
	assert(allocations == 2 && frees == 1 && !swapz_trial_observation_active());
	assert(!swapz_trial_byte_active());
	fail_allocation = 0;
	assert(swapz_trial_observation_start(&scope, 256));
	assert(swapz_trial_observation_active() && !swapz_trial_byte_active());
	assert(swapz_trial_byte_bind_scope(77, 2, 13));
	assert(swapz_trial_byte_active());
	assert(refuse_private());
	for (u32 index = 1; index <= high; ++index)
		assert(swapz_trial_observation_mint() == index);
	for (u32 index = 1; index <= total; ++index) {
		struct swapz_observation_record record;
		const void *view = NULL;
		size_t length = 0;
		u64 token, ordinal;
		assert(fread(&record, sizeof(record), 1, stdin) == 1 && !record.sequence);
		frozen_shape(&record);
		if (!strcmp(mode, "absent_cleanup") && record.event == SWAPZ_OBS_CLEANUP)
			break;
		if (record.event == SWAPZ_OBS_CAPTURE ||
		    (record.event == SWAPZ_OBS_ACCEPT && record.operation_kind == SWAPZ_OBS_ORDINARY_WRITE) ||
		    record.event == SWAPZ_OBS_ORACLE) {
			assert(fread(page, 1, sizeof(page), stdin) == sizeof(page));
			if (record.event != SWAPZ_OBS_CAPTURE) {
				view = page;
				length = sizeof(page);
			}
		}
		if (record.event == SWAPZ_OBS_CAPTURE) {
			token = swapz_trial_byte_stage_input(77, 2, 13, record.slot, page, sizeof(page));
			assert(token);
			memset(replacement, 0x5a, sizeof(replacement));
			if (!strcmp(mode, "aborted")) {
				swapz_trial_byte_finish_input(token, 0);
			} else {
				swapz_trial_byte_finish_input(token, record.store);
				/* Aborted replacement must preserve the committed bytes. */
				token = swapz_trial_byte_stage_input(77, 2, 13, record.slot,
								   replacement, sizeof(replacement));
				assert(token);
				swapz_trial_byte_finish_input(token, !strcmp(mode, "stale") ?
							      record.store + 1U : 0);
			}
			memset(page, 0, sizeof(page));
			memset(replacement, 0, sizeof(replacement));
			if (!strcmp(mode, "duplicate_finish")) {
				swapz_trial_byte_finish_input(token, record.store);
			} else if (!strcmp(mode, "wrong_scope")) {
				assert(!swapz_trial_byte_stage_input(78, 2, 13, record.slot, page, sizeof(page)));
			} else if (!strcmp(mode, "capacity")) {
				for (u64 slot = 100; slot < 103; ++slot) {
					token = swapz_trial_byte_stage_input(77, 2, 13, slot, page, sizeof(page));
					assert(token);
					swapz_trial_byte_finish_input(token, 1);
				}
				assert(!swapz_trial_byte_stage_input(77, 2, 13, 103, page, sizeof(page)));
			} else if (!strcmp(mode, "race")) {
				race(&record);
				rejected = true;
				break;
			}
		}
		if (!strcmp(mode, "pending") && record.event == SWAPZ_OBS_CLEANUP)
			assert(swapz_trial_byte_stage_input(77, 2, 13, 7, page, sizeof(page)));
		if (!strcmp(mode, "bad_status") && record.event == SWAPZ_OBS_CLONE_ENDIO)
			record.status = 5;
		if (clean) {
			if (!strcmp(mode, "wrong_copy") && record.event == SWAPZ_OBS_ORACLE)
				page[SWAPZ_BYTE_PAGE - 1U] ^= 1U;
			/* Execute frozen MM and target emitter code; exact exported wire
			 * proves one append each. CLEANUP and unsupported producer
			 * outcome events here are explicitly synthetic only. */
			if (record.event == SWAPZ_OBS_UPPER_ENDIO ||
			    record.event == SWAPZ_OBS_CAPTURE ||
			    record.event == SWAPZ_OBS_BIND ||
			    record.event == SWAPZ_OBS_CARRIER_RELEASE)
				assert(swapz_mm_observation_emit(&record));
			else
				swapz_scope_observe_event(&record, view, length);
			if (view)
				memset(page, 0, sizeof(page));
			continue;
		}
		if (!strcmp(mode, "cleanup_debt") && record.event == SWAPZ_OBS_CLEANUP)
			record.bios = 1;
		if (!strcmp(mode, "wrong_original") && record.event == SWAPZ_OBS_UPPER_ENDIO)
			record.original = record.operation;
		ordinal = swapz_trial_observation_append_sequence(&record);
		assert(ordinal == index);
		if (!strcmp(mode, "unforwarded_cleanup") && record.event == SWAPZ_OBS_CLEANUP)
			break;
		if (!strcmp(mode, "gap") && index == 2)
			continue;
		if (!strcmp(mode, "zero") && index == 1)
			ordinal = 0;
		if (!strcmp(mode, "wrong_ordinal") && index == 2)
			ordinal = 1;
		if (!strcmp(mode, "wrong_record") && index == 1)
			record.logical += 1U;
		if (!strcmp(mode, "missing_copy") && record.event == SWAPZ_OBS_ORACLE) {
			view = NULL;
			length = 0;
		}
		if (!strcmp(mode, "wrong_copy") && record.event == SWAPZ_OBS_ORACLE)
			page[SWAPZ_BYTE_PAGE - 1U] ^= 1U;
		if (!swapz_trial_byte_event(&record, ordinal, view, length)) {
			rejected = true;
			break;
		}
		if (!strcmp(mode, "duplicate") && index == 1) {
			assert(!swapz_trial_byte_event(&record, ordinal, view, length));
			rejected = true;
			break;
		}
		if (view)
			memset(page, 0, sizeof(page));
	}
	if (!strcmp(mode, "trailing")) {
		const struct swapz_observation_record extra = {.event = SWAPZ_OBS_CLEANUP, .flags = 7};
		assert(swapz_trial_observation_append_sequence(&extra) == (u64)total + 1U);
	}
	if (!strcmp(mode, "failed_join")) {
		assert(!rejected);
		fail_join = true;
		assert(!swapz_trial_observation_stop(join, &scope));
		assert(joins == 1 && frees == 1 && !swapz_trial_byte_active());
		assert(!swapz_trial_observation_release());
		assert(refuse_private());
		assert(!swapz_trial_observation_export_bytes(reject_sink, NULL) && !exported);
		fail_join = false;
	}
	assert(swapz_trial_observation_stop(join, &scope));
	assert(joins == (!strcmp(mode, "failed_join") ? 2U : 1U));
	assert(!swapz_trial_observation_active() && !swapz_trial_byte_active());
	assert(!swapz_trial_byte_event(NULL, 0, NULL, 0));
	assert(!swapz_trial_byte_stage_input(77, 2, 13, 7, page, sizeof(page)));
	if (clean) {
		assert(!rejected && fgetc(stdin) == EOF);
		/* Fail at header, wire body and collector payload; exact retry
		 * from offset zero must still export the identical full bundle. */
		for (unsigned int attempt = 0; attempt < 3; ++attempt) {
			struct failed_sink sink = {.fail_at = attempt == 0 ? 1U :
				attempt == 1 ? 3U : total + 5U};
			assert(!swapz_trial_observation_export_private(fail_sink, &sink));
			assert(sink.calls == sink.fail_at && frees == 1 && joins == 1);
		}
		assert(swapz_trial_observation_export_private(wire_sink, stdout));
	} else {
		assert(rejected || !strcmp(mode, "failed_join") || !strcmp(mode, "pending") ||
		       !strcmp(mode, "absent_cleanup") || !strcmp(mode, "unforwarded_cleanup") ||
		       !strcmp(mode, "trailing"));
		assert(!swapz_trial_observation_export_bytes(reject_sink, NULL) && !exported);
		assert(refuse_private());
		puts("R105_PRIVATE_REJECTED AUTH=0");
	}
	assert(swapz_trial_observation_release());
	assert(frees == 3 && allocations == 4 && scrubbed == 2);
	assert(refuse_private());
	assert(!swapz_trial_observation_release());
	assert(!swapz_trial_observation_start(&scope, 256));
	return ferror(stdout) ? 1 : 0;
}
