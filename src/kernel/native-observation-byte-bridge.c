/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-byte-bridge.h"
#include <linux/export.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/vmalloc.h>
#ifdef __KERNEL__
#include <linux/spinlock.h>
static DEFINE_SPINLOCK(bridge_lock);
#define BRIDGE_LOCK() spin_lock_irqsave(&bridge_lock, flags)
#define BRIDGE_UNLOCK() spin_unlock_irqrestore(&bridge_lock, flags)
#else
static pthread_mutex_t bridge_lock = PTHREAD_MUTEX_INITIALIZER;
#define BRIDGE_LOCK() do { (void)flags; pthread_mutex_lock(&bridge_lock); } while (0)
#define BRIDGE_UNLOCK() pthread_mutex_unlock(&bridge_lock)
#endif

/* Two banks preserve the last committed input when a replacement aborts.
 * The inactive bank is pending; successful finish flips ownership, not bytes.
 * All identities are values. No folio, BIO, target, module or user pointer.
 */
struct staged_input {
	u64 slot, store, token;
	unsigned int bank;
	bool committed;
	u8 bytes[2][SWAPZ_BYTE_PAGE];
};
struct byte_operation {
	struct swapz_observation_record capture;
	u64 operation, original, descriptor, clone, lower, extent, credit, reserved_extent;
	u32 kind, logical;
	unsigned int staged;
	bool captured, bound, accepted, dispatched, claimed, refused, cancelled, fallback;
	bool submitted, completed, failed, flushed, published, quarantined, discarded;
	bool clone_done, done, candidate_released, carrier_released;
};
struct byte_bridge {
	struct swapz_observation_recorder *recorder;
	struct swapz_byte_collector collector;
	struct staged_input input[SWAPZ_BYTE_LOGICAL_PAGES];
	struct byte_operation op;
	u64 identity, area_epoch, last_sequence, next_token;
	u32 swap_type, pages;
	bool bound, closed, joined, loss, cleaned;
};

/* Static lock/hint outlive even callers paused before entering. The lock
 * protects every dereference of storage, including recorder slot validation.
 * Cold owner mutex serializes prepare/close/export/release; no sink or join
 * callback is invoked under this lock. Nesting is bridge -> collector only.
 */
static struct byte_bridge *bridge;
static bool active_hint;

static void scrub(void *pointer, size_t length)
{
#ifdef __KERNEL__
	memzero_explicit(pointer, length);
#else
	volatile u8 *bytes = pointer;
	while (length--)
		*bytes++ = 0;
#endif
}

static bool lose(struct byte_bridge *state)
{
	if (state && !state->closed) {
		state->loss = true;
		swapz_byte_invalidate(&state->collector);
		atomic_or(SWAPZ_OBS_LOST_INVALID, &state->recorder->loss);
	}
	return false;
}

static bool usable(const struct byte_bridge *state)
{
	return state && state->bound && !state->closed && !state->loss &&
	       smp_load_acquire(&state->recorder->enabled);
}

bool swapz_byte_bridge_prepare(struct swapz_observation_recorder *recorder,
			      u32 first, u32 pages)
{
	struct byte_bridge *state;
	unsigned long flags = 0;

	if (!recorder || !pages || pages > SWAPZ_BYTE_LOGICAL_PAGES)
		return false;
	state = kvcalloc(1, sizeof(*state), GFP_KERNEL);
	if (!state)
		return false;
	if (!swapz_byte_start(&state->collector, first, pages)) {
		kvfree(state);
		return false;
	}
	state->recorder = recorder;
	state->pages = pages;
	BRIDGE_LOCK();
	if (bridge) {
		BRIDGE_UNLOCK();
#ifndef __KERNEL__
		pthread_mutex_destroy(&state->collector.lock);
#endif
		kvfree(state);
		return false;
	}
	bridge = state;
	BRIDGE_UNLOCK();
	return true;
}

static void destroy(struct byte_bridge *state)
{
#ifndef __KERNEL__
	pthread_mutex_destroy(&state->collector.lock);
#endif
	scrub(state, sizeof(*state));
	kvfree(state);
}

void swapz_byte_bridge_abort(void)
{
	unsigned long flags = 0;
	struct byte_bridge *state;

	BRIDGE_LOCK();
	state = bridge;
	/* Only the owner before any successful recorder publication. */
	if (!state || state->bound || smp_load_acquire(&state->recorder->enabled)) {
		BRIDGE_UNLOCK();
		return;
	}
	bridge = NULL;
	BRIDGE_UNLOCK();
	destroy(state);
}

bool swapz_trial_byte_active(void)
{
	return smp_load_acquire(&active_hint);
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_active);

bool swapz_trial_byte_bind_scope(u64 identity, u32 swap_type, u64 area_epoch)
{
	unsigned long flags = 0;
	struct byte_bridge *state;
	bool ok = false;

	BRIDGE_LOCK();
	state = bridge;
	if (state && !state->bound && !state->closed && !state->loss &&
	    smp_load_acquire(&state->recorder->enabled) &&
	    identity && swap_type <= 255U && area_epoch) {
		state->identity = identity;
		state->swap_type = swap_type;
		state->area_epoch = area_epoch;
		state->bound = true;
		smp_store_release(&active_hint, true);
		ok = true;
	} else {
		lose(state);
	}
	BRIDGE_UNLOCK();
	return ok;
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_bind_scope);

u64 swapz_trial_byte_stage_input(u64 identity, u32 swap_type, u64 area_epoch,
				u64 slot, const void *bytes, size_t length)
{
	unsigned long flags = 0;
	struct byte_bridge *state;
	struct staged_input *input = NULL, *empty = NULL;
	u64 token = 0;

	if (!swapz_trial_byte_active())
		return 0;
	BRIDGE_LOCK();
	state = bridge;
	if (!usable(state))
		goto out;
	if (identity != state->identity || swap_type != state->swap_type ||
	    area_epoch != state->area_epoch || state->cleaned || !slot || !bytes ||
	    length != SWAPZ_BYTE_PAGE || state->next_token >= SWAPZ_BYTE_OPERATIONS)
		goto invalid;
	for (unsigned int index = 0; index < state->pages; ++index) {
		struct staged_input *candidate = &state->input[index];

		if (candidate->slot == slot) {
			input = candidate;
			break;
		}
		if (!candidate->slot && !empty)
			empty = candidate;
	}
	if (!input)
		input = empty;
	if (!input || input->token)
		goto invalid;
	input->slot = slot;
	input->token = ++state->next_token;
	memcpy(input->bytes[input->bank ^ 1U], bytes, length);
	token = input->token;
	goto out;
invalid:
	lose(state);
out:
	BRIDGE_UNLOCK();
	return token;
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_stage_input);

void swapz_trial_byte_finish_input(u64 input_token, u64 store_sequence)
{
	unsigned long flags = 0;
	struct byte_bridge *state;

	if (!swapz_trial_byte_active())
		return;
	BRIDGE_LOCK();
	state = bridge;
	if (!usable(state))
		goto out;
	/* CLEANUP is the terminal byte boundary, not permission to finish a
	 * staged input. Retain both banks for the actual external join. */
	if (state->cleaned) {
		lose(state);
		goto out;
	}
	for (unsigned int index = 0; input_token && index < state->pages; ++index) {
		struct staged_input *input = &state->input[index];

		if (input->token != input_token)
			continue;
		if (store_sequence && (store_sequence <= input->store ||
		    (state->op.captured && !state->op.bound && state->op.staged == index)))
			break;
		input->token = 0;
		if (store_sequence) {
			scrub(input->bytes[input->bank], SWAPZ_BYTE_PAGE);
			input->bank ^= 1U;
			input->store = store_sequence;
			input->committed = true;
		} else {
			scrub(input->bytes[input->bank ^ 1U], SWAPZ_BYTE_PAGE);
		}
		goto out;
	}
	lose(state);
out:
	BRIDGE_UNLOCK();
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_finish_input);

static bool exact_record(const struct byte_bridge *state,
			 const struct swapz_observation_record *record, u64 sequence)
{
	const struct swapz_observation_record *committed;

	if (!record || record->sequence || !sequence ||
	    sequence > state->recorder->capacity || sequence != state->last_sequence + 1U)
		return false;
	committed = &state->recorder->records[sequence - 1U];
	/* No count read or second reservation. The marker release-publishes
	 * all remaining fields, which are immutable until the external join.
	 */
	return smp_load_acquire(&committed->sequence) == sequence &&
	       !memcmp(&committed->operation, &record->operation,
		       sizeof(*record) - sizeof(record->sequence));
}

static bool scoped_key(const struct byte_bridge *state,
		       const struct swapz_observation_record *record)
{
	return record->swap_type == state->swap_type &&
	       record->area_epoch == state->area_epoch && record->slot && record->store &&
	       record->generation && record->logical >= state->collector.first &&
	       record->logical - state->collector.first < state->pages;
}

static bool same_key(const struct swapz_observation_record *a,
		     const struct swapz_observation_record *b)
{
	return a->logical == b->logical && a->swap_type == b->swap_type &&
	       a->area_epoch == b->area_epoch && a->slot == b->slot &&
	       a->store == b->store && a->generation == b->generation;
}

static bool begin_operation(struct byte_bridge *state, const struct swapz_observation_record *record)
{
	if (state->cleaned || (state->op.operation && (!state->op.done ||
	    (state->op.captured && (!state->op.candidate_released || !state->op.carrier_released)))))
		return false;
	memset(&state->op, 0, sizeof(state->op));
	state->op.operation = record->operation;
	state->op.logical = record->logical;
	state->op.kind = record->operation_kind;
	return record->operation != 0;
}

static bool capture_input(struct byte_bridge *state, const struct swapz_observation_record *record)
{
	struct byte_operation *op = &state->op;

	if (record->operation_kind != SWAPZ_OBS_TYPED_WRITE || !scoped_key(state, record) ||
	    !begin_operation(state, record))
		return false;
	for (unsigned int index = 0; index < state->pages; ++index) {
		const struct staged_input *input = &state->input[index];

		if (input->committed && input->slot == record->slot && input->store == record->store) {
			op->capture = *record;
			op->captured = true;
			op->staged = index;
			return true;
		}
	}
	return false;
}

static bool bind_input(struct byte_bridge *state, const struct swapz_observation_record *record)
{
	struct byte_operation *op = &state->op;
	struct staged_input *input;

	if (!op->captured || op->bound || !record->original)
		return false;
	input = &state->input[op->staged];
	if (!input->committed || input->slot != op->capture.slot ||
	    input->store != op->capture.store ||
	    !swapz_byte_begin(&state->collector, SWAPZ_BYTE_WRITE, op->logical,
			      op->operation, record->original, input->bytes[input->bank],
			      SWAPZ_BYTE_PAGE))
		return false;
	input->committed = false;
	scrub(input->bytes[input->bank], SWAPZ_BYTE_PAGE);
	op->original = record->original;
	op->bound = true;
	return true;
}

static bool accept_operation(struct byte_bridge *state,
			     const struct swapz_observation_record *record, u64 sequence,
			     const void *bytes, size_t length)
{
	struct byte_operation *op = &state->op;
	enum swapz_byte_kind kind;

	if (record->operation_kind == SWAPZ_OBS_TYPED_WRITE) {
		if (bytes || length || !op->bound || op->accepted ||
		    op->operation != record->operation || op->original != record->original ||
		    record->flags != 1 || !same_key(&op->capture, record))
			return false;
	} else {
		switch (record->operation_kind) {
		case SWAPZ_OBS_TYPED_READ: kind = SWAPZ_BYTE_READ; break;
		case SWAPZ_OBS_ORDINARY_WRITE: kind = SWAPZ_BYTE_ORDINARY; break;
		case SWAPZ_OBS_DISCARD_BIO: kind = SWAPZ_BYTE_DISCARD; break;
		default: return false;
		}
		if (record->flags || record->slot || record->store || record->area_epoch ||
		    record->swap_type || record->generation || !begin_operation(state, record) ||
		    !swapz_byte_begin(&state->collector, kind, record->logical,
				      record->operation, record->original, bytes, length))
			return false;
		op->original = record->original;
	}
	if (!swapz_byte_accept(&state->collector, record->operation, record->original,
			       record->clone, record->descriptor, sequence))
		return false;
	op->clone = record->clone;
	op->descriptor = record->descriptor;
	op->accepted = true;
	return true;
}

/* Actual outcome events only. R099 independently checks the entire wire,
 * including generation, payload/digest, map, credit and cleanup semantics.
 * Here classification is deliberately limited to one unsplit lower extent.
 */
static bool outcome(struct byte_bridge *state, const struct swapz_observation_record *record)
{
	struct byte_operation *op = &state->op;
	bool typed = op->kind == SWAPZ_OBS_TYPED_WRITE;
	bool read = op->kind == SWAPZ_OBS_TYPED_READ;

	if (!op->dispatched || op->clone_done)
		return false;
	switch (record->event) {
	case SWAPZ_OBS_RESERVE:
		if (!typed || op->candidate_released || op->credit || op->refused ||
		    !record->credit || !record->extent)
			return false;
		op->credit = record->credit;
		op->reserved_extent = record->extent;
		return true;
	case SWAPZ_OBS_CLAIM:
		if (!typed || op->candidate_released || !op->credit || op->claimed || op->refused ||
		    record->credit != op->credit || record->descriptor != op->descriptor)
			return false;
		op->claimed = true;
		return true;
	case SWAPZ_OBS_REFUSE:
		if (!typed || op->claimed || op->refused || !record->status)
			return false;
		op->refused = true;
		return true;
	case SWAPZ_OBS_CANCEL:
		if (!op->refused || op->claimed || op->cancelled || !op->credit ||
		    record->credit != op->credit || record->flags != 1 || op->submitted)
			return false;
		op->cancelled = true;
		return true;
	case SWAPZ_OBS_FALLBACK:
		if (!op->refused || op->claimed || op->fallback || (op->credit && !op->cancelled) ||
		    !swapz_byte_classify(&state->collector, op->operation, SWAPZ_BYTE_FALLBACK))
			return false;
		op->fallback = true;
		return true;
	case SWAPZ_OBS_LOWER_SUBMIT:
		if (op->submitted || !record->lower || !record->extent ||
		    record->requested != SWAPZ_BYTE_PAGE || record->flags != (read ? 1U : 2U) ||
		    op->kind == SWAPZ_OBS_DISCARD_BIO ||
		    (typed && !op->claimed && !op->fallback) ||
		    (op->claimed && record->extent != op->reserved_extent))
			return false;
		op->lower = record->lower;
		op->extent = record->extent;
		op->submitted = true;
		return true;
	case SWAPZ_OBS_LOWER_COMPLETE:
		if (!op->submitted || op->completed || record->lower != op->lower)
			return false;
		op->completed = true;
		op->failed = record->status || record->completed != SWAPZ_BYTE_PAGE;
		return true;
	case SWAPZ_OBS_FLUSH:
		if (read || !op->completed || op->failed || op->flushed ||
		    record->extent != op->extent)
			return false;
		op->flushed = true;
		op->failed = record->status != 0;
		return true;
	case SWAPZ_OBS_PUBLISH:
		if (read || !op->flushed || op->failed || op->published || record->extent != op->extent)
			return false;
		op->published = true;
		return true;
	case SWAPZ_OBS_QUARANTINE:
		if (!typed || !op->claimed || !op->completed || !op->failed ||
		    op->published || op->quarantined || record->extent != op->extent ||
		    !swapz_byte_classify(&state->collector, op->operation, SWAPZ_BYTE_ERROR))
			return false;
		op->quarantined = true;
		return true;
	case SWAPZ_OBS_DISCARD:
		if (op->kind != SWAPZ_OBS_DISCARD_BIO || op->discarded)
			return false;
		op->discarded = true;
		return true;
	default:
		return false;
	}
}

/* Caller holds bridge_lock. Only BIND consumes a committed input into
 * the collector; a canceled replacement leaves the prior committed bank.
 * The bounded cold census cannot infer retirement from a zero token.
 */
static bool terminal_ready(const struct byte_bridge *state)
{
	const struct byte_operation *op = &state->op;

	if (!op->done ||
	    (op->captured && (!op->candidate_released || !op->carrier_released)))
		return false;
	for (unsigned int index = 0; index < state->pages; ++index)
		if (state->input[index].token || state->input[index].committed)
			return false;
	return true;
}

static bool apply_event(struct byte_bridge *state, const struct swapz_observation_record *record,
			u64 sequence, const void *bytes, size_t length)
{
	struct byte_operation *op = &state->op;
	bool ok;

	if (record->event != SWAPZ_OBS_ACCEPT && record->event != SWAPZ_OBS_ORACLE &&
	    (bytes || length))
		return false;
	switch (record->event) {
	case SWAPZ_OBS_CAPTURE:
		return capture_input(state, record);
	case SWAPZ_OBS_ACCEPT:
		return accept_operation(state, record, sequence, bytes, length);
	case SWAPZ_OBS_CLEANUP:
		if (state->cleaned || !terminal_ready(state) ||
		    record->flags != 7 || record->caps ||
		    record->tickets || record->pins || record->reservations || record->bios ||
		    record->maps || record->quarantines)
			return false;
		state->cleaned = true;
		return true;
	case SWAPZ_OBS_CAPTURE_DROP:
	case SWAPZ_OBS_GC_BEGIN:
	case SWAPZ_OBS_GC_END:
		return false;
	default:
		break;
	}
	if (state->cleaned || !op->operation || record->operation != op->operation)
		return false;
	switch (record->event) {
	case SWAPZ_OBS_BIND:
		return bind_input(state, record);
	case SWAPZ_OBS_PREPARATION:
		return !op->clone_done && (op->captured || op->accepted);
	case SWAPZ_OBS_CANDIDATE_RELEASE:
		if (!op->captured || !op->accepted || op->candidate_released ||
		    record->descriptor != op->descriptor || record->status)
			return false;
		op->candidate_released = true;
		return true;
	case SWAPZ_OBS_CARRIER_RELEASE:
		if (!op->bound || !op->done || op->carrier_released ||
		    record->original != op->original || record->status)
			return false;
		op->carrier_released = true;
		return true;
	case SWAPZ_OBS_DISPATCH:
		if (!op->accepted || op->dispatched ||
		    (record->flags != 1 && (record->flags != 2 || op->kind != SWAPZ_OBS_TYPED_READ)))
			return false;
		op->dispatched = true;
		return true;
	case SWAPZ_OBS_PIN:
		return op->dispatched && scoped_key(state, record) && record->logical == op->logical &&
		       swapz_byte_pin(&state->collector, op->operation, op->descriptor,
				      record->pin, sequence);
	case SWAPZ_OBS_ORACLE:
		return op->completed && !op->failed && !record->status && record->flags == 1 &&
		       record->decoded_length == SWAPZ_BYTE_PAGE && record->compared == SWAPZ_BYTE_PAGE &&
		       swapz_byte_copy(&state->collector, op->operation, op->descriptor,
				       record->pin, sequence, bytes, length);
	case SWAPZ_OBS_PIN_RELEASE:
		return !record->status && swapz_byte_unpin(&state->collector, op->operation,
							   op->descriptor, record->pin, sequence);
	case SWAPZ_OBS_CLONE_ENDIO:
		if (!op->dispatched || op->clone_done ||
		    (op->kind == SWAPZ_OBS_TYPED_WRITE ? !(op->published || op->quarantined) :
		     op->kind == SWAPZ_OBS_ORDINARY_WRITE ? !op->published :
		     op->kind == SWAPZ_OBS_DISCARD_BIO ? !op->discarded : !op->completed))
			return false;
		ok = swapz_byte_clone(&state->collector, op->operation, record->clone,
				      record->descriptor, sequence, record->status);
		op->clone_done = ok;
		return ok;
	case SWAPZ_OBS_UPPER_ENDIO:
		if (!op->clone_done || op->done ||
		    !swapz_byte_upper(&state->collector, op->operation, record->original,
				      op->clone, op->descriptor, sequence, record->status))
			return false;
		op->done = swapz_byte_complete(&state->collector, op->operation, record->original);
		return op->done;
	default:
		return outcome(state, record);
	}
}

bool swapz_trial_byte_event(const struct swapz_observation_record *record,
			   u64 sequence, const void *bytes, size_t length)
{
	unsigned long flags = 0;
	struct byte_bridge *state;
	bool ok = false;

	if (!swapz_trial_byte_active())
		return false;
	BRIDGE_LOCK();
	state = bridge;
	if (usable(state)) {
		ok = exact_record(state, record, sequence) &&
		     apply_event(state, record, sequence, bytes, length);
		if (ok)
			state->last_sequence = sequence;
		else
			lose(state);
	}
	BRIDGE_UNLOCK();
	return ok;
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_event);

void swapz_trial_byte_invalidate(void)
{
	unsigned long flags = 0;

	if (!swapz_trial_byte_active())
		return;
	BRIDGE_LOCK();
	lose(bridge);
	BRIDGE_UNLOCK();
}
EXPORT_SYMBOL_GPL(swapz_trial_byte_invalidate);

void swapz_byte_bridge_close(bool joined)
{
	unsigned long flags = 0;
	struct byte_bridge *state;

	BRIDGE_LOCK();
	state = bridge;
	if (!state || state->joined) {
		BRIDGE_UNLOCK();
		return;
	}
	/* Independently repeat the input/operation census at actual close.
	 * Loss never substitutes for the caller's external join. */
	if (!state->bound || !state->cleaned || !terminal_ready(state))
		lose(state);
	if (!joined)
		lose(state);
	state->closed = true;
	state->joined = joined;
	smp_store_release(&active_hint, false);
	BRIDGE_UNLOCK();
	/* All bridge callers now see closed even if paused before the lock.
	 * Actual external join is already known; do not invoke it twice.
	 */
	if (!swapz_byte_stop_after_join(&state->collector, joined))
		atomic_or(SWAPZ_OBS_LOST_INVALID, &state->recorder->loss);
}

bool swapz_byte_bridge_export(swapz_byte_record_sink sink, void *context)
{
	const struct swapz_byte_record *records;
	unsigned int count;
	/* Owner mutex excludes release; private sink is synchronous and
	 * non-reentrant. No borrowed storage escapes this callback contract.
	 */
	if (!bridge || !bridge->joined || !sink || atomic_read(&bridge->recorder->loss) ||
	    !bridge->recorder->sealed || !bridge->cleaned ||
	    bridge->last_sequence != (u64)atomic_read(&bridge->recorder->count) ||
	    !swapz_byte_export(&bridge->collector, &records, &count))
		return false;
	for (unsigned int index = 0; index < count; ++index)
		if (!sink(context, &records[index]))
			return false;
	return true;
}

bool swapz_byte_bridge_release(void)
{
	unsigned long flags = 0;
	struct byte_bridge *state;

	BRIDGE_LOCK();
	state = bridge;
	if (!state || !state->joined || !state->closed) {
		BRIDGE_UNLOCK();
		return false;
	}
	bridge = NULL;
	BRIDGE_UNLOCK();
	if (!swapz_byte_release(&state->collector)) {
		/* No admission can reopen; retain on unexpected release failure. */
		BRIDGE_LOCK();
		bridge = state;
		BRIDGE_UNLOCK();
		return false;
	}
	destroy(state);
	return true;
}
