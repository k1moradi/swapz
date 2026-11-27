/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual built-in owner/recorder/collector/bridge and frozen producer shapes, modeled host primitives.
 * The input wire and buffers are synthetic; stdout is private fixture data.
 */
#include "native-observation-owner-host-model.h"
#include "native-observation-owner.h"
#include <inttypes.h>
#include <openssl/sha.h>
#include <sched.h>
#include "round106-producer-model.h"

static pthread_rwlock_t rcu = PTHREAD_RWLOCK_INITIALIZER;
static atomic_bool pause_next, paused, proceed;
static unsigned allocations, frees, fail_allocation, joins, exported;
static size_t allocated_sizes[8];
static void *allocated_pointers[8];
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
	assert(allocations <= 8);
	void *pointer = calloc(count, size);
	allocated_sizes[allocations - 1U] = count * size;
	allocated_pointers[allocations - 1U] = pointer;
	return pointer;
}
void model_kvfree(void *pointer)
{
	++frees;
	/* Actual recorder and bridge allocations must be scrubbed after join. */
	for (unsigned int allocation = 2; allocation < allocations; ++allocation) {
		if (pointer != allocated_pointers[allocation])
			continue;
		const u8 *bytes = pointer;
		for (size_t index = 0; index < allocated_sizes[allocation]; ++index)
			assert(!bytes[index]);
		++scrubbed;
		allocated_pointers[allocation] = NULL;
		break;
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


static void emit(const struct swapz_observation_record *record, const void *bytes, size_t length)
{
	u64 sequence = swapz_trial_observation_append_sequence(record);
	assert(sequence && swapz_trial_byte_event(record, sequence, bytes, length));
}
static void terminal(struct swapz_bio_ref *entry, int error, bool candidate, bool carrier)
{
	u64 operation = entry->observation_operation, original = entry->observation_original;
	u64 descriptor = entry->observation_descriptor;
	if (candidate)
		swapz_scope_observe_release(operation, descriptor, 0);
	swapz_scope_observe_clone(entry, error);
	assert(!entry->observation_operation);
	const struct swapz_observation_record upper = {
		.event = SWAPZ_OBS_UPPER_ENDIO, .operation = operation, .original = original,
		.status = swapz_scope_status(error),
	};
	assert(swapz_mm_observation_emit(&upper));
	if (carrier) {
		const struct swapz_observation_record release = {
			.event = SWAPZ_OBS_CARRIER_RELEASE, .operation = operation, .original = original,
		};
		assert(swapz_mm_observation_emit(&release));
	}
}

static struct swapz_bio_ref new_entry(void)
{
	return (struct swapz_bio_ref){
		.observation_operation = swapz_trial_observation_mint(),
		.observation_original = swapz_trial_observation_mint(),
		.observation_clone = swapz_trial_observation_mint(),
		.observation_descriptor = swapz_trial_observation_mint(),
	};
}
/* Host-only white-box probes of otherwise unreachable terminal debt. */
void round108_terminal_probe(const char *mode);

static void actual_trace(const char *mode, const struct swapz_trial_observation_scope *scope)
{
	struct swapz_dm ctx = {.logical_pages = 16, .prepublication_fua = true};
	struct modeled_storage storage = {.ctx = &ctx, .transaction.start_block = 1};
	struct swapz_bio_ref entry = new_entry();
	u64 first_operation = entry.observation_operation;
	u64 first_original = entry.observation_original;
	struct swapz_ticket_key *key = &entry.original_view.key;
	struct swapz_round091_claim_context claim = {&ctx, &entry};
	struct swapz_authority_import_spec spec = {.gc_epoch = 1};
	struct swapz_original_extent_input input = {};
	u8 page[SWAPZ_BLOCK_BYTES], raw[SWAPZ_BLOCK_BYTES];
	u32 completed;
	int error = 0;
	bool ordinary = !strcmp(mode, "actual-ordinary") || !strcmp(mode, "actual-packed");
	bool fallback = !strcmp(mode, "actual-fallback");
	bool claimed_error = !strcmp(mode, "actual-error");
	bool read = !strcmp(mode, "actual-read");
	bool controller = !strcmp(mode, "actual-controller");
	bool bad = !strcmp(mode, "actual-missing-candidate") ||
		   !strcmp(mode, "actual-missing-carrier") || !strcmp(mode, "actual-late-carrier") ||
		   !strcmp(mode, "actual-gc") ||
		   !strcmp(mode, "actual-interleave") || !strcmp(mode, "actual-zero") ||
		   !strcmp(mode, "actual-packed");
	bool candidate = true;

	ctx.original_storage = &storage;
	ctx.authority.physical_blocks = 16;
	memset(page, 0x47, sizeof(page));
	memset(modeled_payload, 0x23, sizeof(modeled_payload));
	*key = (struct swapz_ticket_key){
		.logical_page = 7, .slot_offset = 7, .area_epoch = 13, .store_sequence = 11,
		.dm_generation = 1, .swap_type = 2, .length = 32, .decoded_length = 4096,
		.codec = 1, .representation = 90, .version = 1,
	};
	sha256(page, sizeof(page), key->sha256);
	sha256(modeled_payload, key->length, entry.observation_compressed_sha256);
	if (!ordinary) {
		struct swapz_observation_record capture = {
			.event = SWAPZ_OBS_CAPTURE, .operation = entry.observation_operation,
			.operation_kind = SWAPZ_OBS_TYPED_WRITE, .logical = 7, .slot = 7,
			.area_epoch = 13, .store = 11, .swap_type = 2, .generation = 1,
			.compressed_length = key->length, .decoded_length = 4096, .codec = 1,
			.tag = 90, .version = 1,
		};
		memcpy(capture.compressed_sha256, entry.observation_compressed_sha256, 32);
		memcpy(capture.page_sha256, key->sha256, 32);
		u64 token = swapz_trial_byte_stage_input(77, 2, 13, 7, page, sizeof(page));
		assert(token);
		swapz_trial_byte_finish_input(token, 11);
		assert(swapz_mm_observation_emit(&capture));
		const struct swapz_observation_record bind = {
			.event = SWAPZ_OBS_BIND, .operation = entry.observation_operation,
			.original = entry.observation_original,
		};
		assert(swapz_mm_observation_emit(&bind));
		swapz_scope_observe_accept(&entry);
	} else {
		const struct swapz_observation_record accept = {
			.event = SWAPZ_OBS_ACCEPT, .operation = entry.observation_operation,
			.operation_kind = SWAPZ_OBS_ORDINARY_WRITE, .logical = 7,
			.original = entry.observation_original, .clone = entry.observation_clone,
			.descriptor = entry.observation_descriptor,
		};
		emit(&accept, page, sizeof(page));
	}
	swapz_scope_observe_simple(&entry, SWAPZ_OBS_DISPATCH, 1, 0);
	if (!strcmp(mode, "actual-interleave")) {
		struct swapz_bio_ref second = new_entry();
		const struct swapz_observation_record accept = {
			.event = SWAPZ_OBS_ACCEPT, .operation = second.observation_operation,
			.operation_kind = SWAPZ_OBS_ORDINARY_WRITE, .logical = 8,
			.original = second.observation_original, .clone = second.observation_clone,
			.descriptor = second.observation_descriptor,
		};
		swapz_scope_observe_event(&accept, page, sizeof(page));
		goto finish;
	}
	if (!strcmp(mode, "actual-gc")) {
		const struct swapz_observation_record gc = {
			.event = SWAPZ_OBS_GC_BEGIN, .operation = entry.observation_operation,
			.operation_kind = SWAPZ_OBS_GC,
		};
		swapz_scope_observe_event(&gc, NULL, 0);
		goto finish;
	}
	if (!strcmp(mode, "actual-zero"))
		key->length = 0;
	if (!ordinary) {
		claim_error = fallback ? -EOPNOTSUPP : 0;
		lower_error = claimed_error ? -EIO : 0;
		bool result = swapz_scope_transaction(&ctx, &spec, &input, &claim, &error);
		assert(result == !fallback);
		assert(error == (claimed_error ? -EIO : 0));
	}
	if (ordinary || fallback) {
		if (fallback) {
			assert(entry.observation_fallback && !entry.original_claimed);
			swapz_scope_observe_release(entry.observation_operation, entry.observation_descriptor, 0);
			candidate = false;
		}
		entry.observation_extent = swapz_trial_observation_mint();
		ctx.observation_commit = &entry;
		u8 blocks;
		if (!strcmp(mode, "actual-packed")) {
			assert(!swapz_lower_write(&ctx, 1, 2, page, &blocks) && blocks == 2);
			goto finish;
		}
		assert(!swapz_lower_write(&ctx, 1, 1, page, &blocks) && blocks == 1);
		ctx.observation_commit = NULL;
		/* Actual raw lower/flush functions above; publication values from
		 * the frozen initializer, modeled map commit only. */
		struct swapz_observation_record publish = {
			.event = SWAPZ_OBS_PUBLISH, .operation = entry.observation_operation,
			.extent = entry.observation_extent, .new_generation = 1,
			.compressed_length = 4096, .decoded_length = 4096,
		};
		memcpy(publish.compressed_sha256, entry.observation_compressed_sha256, 32);
		memcpy(publish.page_sha256, entry.observation_compressed_sha256, 32);
		emit(&publish, NULL, 0);
	}
	if (!strcmp(mode, "actual-zero"))
		goto finish;
	terminal(&entry, error, !ordinary && candidate && strcmp(mode, "actual-missing-candidate"),
		 !ordinary && strcmp(mode, "actual-missing-carrier") && strcmp(mode, "actual-late-carrier"));
	if (read) {
		entry = new_entry();
		const struct swapz_observation_record accept = {
			.event = SWAPZ_OBS_ACCEPT, .operation = entry.observation_operation,
			.operation_kind = SWAPZ_OBS_TYPED_READ, .logical = 7,
			.original = entry.observation_original, .clone = entry.observation_clone,
			.descriptor = entry.observation_descriptor,
		};
		emit(&accept, NULL, 0);
		swapz_scope_observe_simple(&entry, SWAPZ_OBS_DISPATCH, 2, 0);
		const struct swapz_observation_record pin = {
			.event = SWAPZ_OBS_PIN, .operation = entry.observation_operation,
			.extent = ctx.observation_extent_by_page[6].extent,
			.gc_epoch = 1, .logical = 7, .slot = 7, .swap_type = 2,
			.area_epoch = 13, .store = 11, .generation = 1,
			.pin = swapz_trial_observation_mint(),
		};
		emit(&pin, NULL, 0);
		ctx.observation_read_operation = entry.observation_operation;
		ctx.observation_read_extent = pin.extent;
		ctx.observation_read_block = 1;
		ctx.observation_read_length = 32;
		memcpy(ctx.observation_read_sha256, ctx.observation_extent_by_page[6].compressed_sha256, 32);
		assert(!swapz_round090_storage_read(&ctx, 1, raw, sizeof(raw), &completed) &&
		       completed == sizeof(raw));
		struct swapz_observation_record oracle = {
			.event = SWAPZ_OBS_ORACLE, .operation = entry.observation_operation,
			.pin = pin.pin, .decoded_length = 4096, .compared = 4096, .flags = 1,
		};
		sha256(page, sizeof(page), oracle.page_sha256);
		memcpy(oracle.observed_sha256, oracle.page_sha256, 32);
		emit(&oracle, page, sizeof(page));
		const struct swapz_observation_record release = {
			.event = SWAPZ_OBS_PIN_RELEASE, .operation = entry.observation_operation, .pin = pin.pin,
		};
		emit(&release, NULL, 0);
		terminal(&entry, 0, false, false);
	}
finish:
	if (controller) {
		/* Actual frozen controller finish, with modeled external joins.
		 * No synthetic CLEANUP injected into this path. */
		struct file mapper = {};
		const struct swapz_trial_retained_scope retained = {
			.identity = 77, .session = 11, .epoch = 12, .target_epoch = 13,
		};
		swapz_controller_mapper = &mapper;
		swapz_controller_external_joined = true;
		swapz_controller_mm_revoked = true;
		assert(!swapz_trial_controller_finish(&retained));
		assert(!controller_error && controller_puts == 1 && !swapz_controller_mapper);
	} else {
		/* Synthetic terminal proof ONLY to exercise compatibility of
		 * actual producer callbacks; never credited as native CLEANUP. */
		const struct swapz_observation_record cleanup = {
			.event = SWAPZ_OBS_CLEANUP, .flags = 7, .quarantines = claimed_error ? 1U : 0U,
		};
		swapz_scope_observe_event(&cleanup, NULL, 0);
		if (!strcmp(mode, "actual-late-carrier")) {
			const struct swapz_observation_record late = {
				.event = SWAPZ_OBS_CARRIER_RELEASE, .operation = first_operation,
				.original = first_original,
			};
			assert(swapz_mm_observation_emit(&late));
		}
		assert(swapz_trial_observation_stop(join, (void *)scope));
	}
	struct swapz_private_snapshot *snapshot = NULL;
	if (bad || controller || claimed_error) {
		assert(!swapz_trial_observation_materialize(scope, &snapshot) && !snapshot);
		assert(refuse_private());
	} else {
		assert(swapz_trial_observation_materialize(scope, &snapshot) && snapshot);
	}
	assert(swapz_trial_observation_release());
	if (snapshot)
		swapz_trial_observation_snapshot_release(&snapshot);
	assert(!snapshot);
	puts("R106_ACTUAL_TRANSITION_CHECK AUTH=0");
}

int main(int argc, char **argv)
{
	assert(argc == 2);
	const char *mode = argv[1];
	bool clean = !strcmp(mode, "clean") || !strcmp(mode, "wrong_copy");
	bool pending_finish = !strcmp(mode, "pending_finish");
	bool pending_cancel = !strcmp(mode, "pending_cancel");
	bool unrepresented = !strcmp(mode, "unrepresented");
	bool quarantine_debt = !strcmp(mode, "quarantine_debt");
	bool terminal_reject = pending_finish || pending_cancel || unrepresented ||
			       quarantine_debt || !strcmp(mode, "error");
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
	if (!strncmp(mode, "actual-", 7)) {
		actual_trace(mode, &scope);
		return 0;
	}
	struct swapz_private_snapshot *snapshot = NULL;
	assert(!swapz_trial_observation_materialize(&scope, &snapshot) && !snapshot);
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
		u64 terminal_token = 0;
		if (record.event == SWAPZ_OBS_CLEANUP &&
		    (!strcmp(mode, "pending") || pending_finish || pending_cancel || unrepresented)) {
			terminal_token = swapz_trial_byte_stage_input(77, 2, 13, 7, page, sizeof(page));
			assert(terminal_token);
			if (unrepresented)
				swapz_trial_byte_finish_input(terminal_token, 100);
		}
		if (quarantine_debt && record.event == SWAPZ_OBS_CLEANUP)
			record.quarantines = 1;
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
		bool accepted = swapz_trial_byte_event(&record, ordinal, view, length);
		if (record.event == SWAPZ_OBS_CLEANUP && terminal_reject) {
			/* Refusal must occur at CLEANUP, not merely at close. */
			assert(!accepted);
			if (pending_finish || pending_cancel)
				swapz_trial_byte_finish_input(terminal_token, pending_finish ? 100U : 0U);
		}
		if (!accepted) {
			rejected = true;
			break;
		}
		if (record.event == SWAPZ_OBS_CLEANUP) {
			if (!strcmp(mode, "late_stage"))
				assert(!swapz_trial_byte_stage_input(77, 2, 13, 7, page, sizeof(page)));
			if (!strcmp(mode, "late_finish"))
				swapz_trial_byte_finish_input(1, 100);
			if (!strcmp(mode, "duplicate_cleanup")) {
				u64 extra = swapz_trial_observation_append_sequence(&record);
				assert(extra == ordinal + 1U);
				assert(!swapz_trial_byte_event(&record, extra, NULL, 0));
			}
			round108_terminal_probe(mode);
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
		struct swapz_trial_observation_scope wrong = scope;
		wrong.run_nonce[0] = 'e';
		assert(!swapz_trial_observation_materialize(&wrong, &snapshot) && !snapshot);
		fail_allocation = allocations + 1U;
		assert(!swapz_trial_observation_materialize(&scope, &snapshot) && !snapshot);
		fail_allocation = 0;
		assert(swapz_trial_observation_materialize(&scope, &snapshot) && snapshot);
		assert(!swapz_trial_observation_materialize(&scope, &snapshot));
		struct failed_sink sink = {.fail_at = 1};
		assert(!swapz_trial_observation_deliver(&wrong, snapshot, fail_sink, &sink) && !sink.calls);
		assert(!swapz_trial_observation_deliver(&scope, snapshot, fail_sink, &sink) && sink.calls == 1);
		assert(swapz_trial_observation_release());
		assert(!swapz_trial_observation_export_private(wire_sink, stdout));
		assert(swapz_trial_observation_deliver(&scope, snapshot, wire_sink, stdout));
		swapz_trial_observation_snapshot_release(&snapshot);
		assert(!snapshot && scrubbed == 3 && frees == 4 && allocations == 6);
		swapz_trial_observation_snapshot_release(&snapshot);
		return ferror(stdout) ? 1 : 0;
	} else {
		assert(rejected || !strcmp(mode, "failed_join") || !strcmp(mode, "pending") ||
		       !strcmp(mode, "absent_cleanup") || !strcmp(mode, "unforwarded_cleanup") ||
		       !strcmp(mode, "trailing") || !strcmp(mode, "late_stage") ||
		       !strcmp(mode, "late_finish") || !strcmp(mode, "duplicate_cleanup") ||
		       !strcmp(mode, "late_finish_internal") || !strcmp(mode, "close_pending") ||
		       !strcmp(mode, "close_committed"));
		assert(!swapz_trial_observation_export_bytes(reject_sink, NULL) && !exported);
		assert(refuse_private());
		puts("R106_PRIVATE_REJECTED AUTH=0");
	}
	assert(swapz_trial_observation_release());
	assert(frees == 3 && allocations == 4 && scrubbed == 2);
	assert(refuse_private());
	assert(!swapz_trial_observation_release());
	assert(!swapz_trial_observation_start(&scope, 256));
	return ferror(stdout) ? 1 : 0;
}
