// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-shared.h"

#ifdef SWAPZ_ORIGINAL_DECODER_SHARED_TEST
enum {
	SHARED_OPEN = 1,
	SHARED_CLOSING,
	SHARED_FINISHING,
	SHARED_FAULTED,
	SHARED_IDLE,
	SHARED_PREPARING,
};

/* Admission increments under the enclosing lock. Release is infallible
 * after output publication and is the last access to the counted object.
 * Use the signed native atomic range on both platforms. */
#define SHARED_COUNT_MAX 0x7fffffffU
static void count_init(swapz_shared_decoder_count *count)
{
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	atomic_init(count, 0U);
#else
	atomic_set(count, 0);
#endif
}

static unsigned int count_read(const swapz_shared_decoder_count *count)
{
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	return atomic_load_explicit(count, memory_order_acquire);
#else
	return (unsigned int)atomic_read_acquire(count);
#endif
}

static void count_enter(swapz_shared_decoder_count *count)
{
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	atomic_fetch_add_explicit(count, 1U, memory_order_relaxed);
#else
	atomic_inc(count);
#endif
}

static void count_leave(swapz_shared_decoder_count *count)
{
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	atomic_fetch_sub_explicit(count, 1U, memory_order_acq_rel);
#else
	(void)atomic_dec_return(count);
#endif
}

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#define SHARED_LOCK(owner) do { if (pthread_mutex_lock(&(owner)->lock)) return -EIO; } while (0)
#define SHARED_UNLOCK(owner) pthread_mutex_unlock(&(owner)->lock)
#else
#define SHARED_LOCK(owner) spin_lock_irqsave(&(owner)->lock, flags)
#define SHARED_UNLOCK(owner) spin_unlock_irqrestore(&(owner)->lock, flags)
#endif

static int valid_profile(swapz_u8 codec, swapz_u8 version)
{
	return version == SWAPZ_ZSWAP_IMPORT_VERSION &&
		(codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC ||
		 codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC);
}

/* Exclusive initialization unwind or externally quiesced teardown.
 * Never enter a blocking drain on an inconsistent reference count. */
static int release_provider(struct swapz_original_decoder_shared *owner,
	unsigned int index)
{
	int result;

	if (owner->providers[index].active_readers !=
	    (owner->retained[index].owner ? 1U : 0U))
		return -EUCLEAN;
	if (owner->retained[index].owner) {
		result = swapz_zswap_import_decoder_owner_put(&owner->retained[index]);
		if (result)
			return result;
	}
	result = swapz_zswap_import_decoder_owner_close_and_drain(&owner->providers[index]);
	if (result)
		return result;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_cond_destroy(&owner->providers[index].drained) ||
	    pthread_mutex_destroy(&owner->providers[index].lock))
		return -EIO;
#endif
	return 0;
}

int swapz_original_decoder_shared_init(
	struct swapz_original_decoder_shared *owner,
	const struct swapz_original_decoder_shared_ops *ops,
	swapz_u32 capacity, swapz_u64 *epoch)
{
	swapz_u64 identity = 0U;
	unsigned int initialized = 0U;
	int result, unwind_error = 0;

	if (!owner || !ops || !ops->reserve_epoch || !ops->snapshot ||
	    !capacity || !epoch || owner->state)
		return -EINVAL;
	if (swapz_zswap_import_ranges_overlap(owner, (swapz_u32)sizeof(*owner),
		epoch, (swapz_u32)sizeof(*epoch)) ||
	    swapz_zswap_import_ranges_overlap(owner, (swapz_u32)sizeof(*owner),
		ops, (swapz_u32)sizeof(*ops)))
		return -EINVAL;
	result = ops->reserve_epoch(ops->context, &identity);
	if (result)
		return result;
	if (!identity || identity == ~(swapz_u64)0)
		return -EOVERFLOW;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_init(&owner->lock, NULL))
		return -EIO;
#else
	spin_lock_init(&owner->lock);
#endif
	while (initialized < 2U) {
		const unsigned int index = initialized;

		result = swapz_zswap_import_decoder_owner_init(&owner->providers[index],
			(swapz_u8)(index + 1U), SWAPZ_ZSWAP_IMPORT_VERSION);
		if (result)
			goto unwind;
		++initialized;
		result = swapz_zswap_import_decoder_owner_get(&owner->providers[index],
			&owner->retained[index]);
		if (result)
			goto unwind;
	}
	count_init(&owner->active_reads);
	owner->ops = *ops;
	owner->epoch = identity;
	owner->capacity = capacity;
	owner->state = SHARED_OPEN;
	*epoch = identity;
	return 0;

unwind:
	/* Independent initialized codecs must each be unwound, even if one
	 * release fails. Keep the failed owner quarantined, never retry it. */
	while (initialized) {
		if (release_provider(owner, --initialized))
			unwind_error = -EIO;
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (!unwind_error && pthread_mutex_destroy(&owner->lock))
		unwind_error = -EIO;
#endif
	owner->state = unwind_error ? SHARED_FAULTED : SHARED_FINISHING;
	return unwind_error ? unwind_error : result;
}

static int disjoint(const struct swapz_original_decoder_shared *owner,
	const struct swapz_original_decoder_value_handle *expected,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	const swapz_u8 *scratch, const swapz_u8 *verified, const swapz_u8 *output)
{
	const void *const addresses[] = {
		owner, expected, snapshot, snapshot->compressed_bytes,
		scratch, verified, output
	};
	const swapz_u32 sizes[] = {
		(swapz_u32)sizeof(*owner), (swapz_u32)sizeof(*expected),
		(swapz_u32)sizeof(*snapshot), snapshot->record.compressed_length,
		SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES
	};
	unsigned int first, second;

	for (first = 0U; first < 7U; ++first)
		for (second = first + 1U; second < 7U; ++second)
			if (swapz_zswap_import_ranges_overlap(addresses[first],
				sizes[first], addresses[second], sizes[second]))
				return 0;
	return 1;
}

int swapz_original_decoder_shared_read(
	struct swapz_original_decoder_shared *owner, swapz_u64 pin,
	const struct swapz_original_decoder_value_handle *expected,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	struct swapz_original_decoder_value_snapshot snapshot = {0};
	struct swapz_zswap_import_decoder_lease lease = {0};
	int result, release_result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !pin || !expected || !scratch || !verified || !output ||
	    scratch_capacity != SWAPZ_BLOCK_BYTES ||
	    verified_capacity != SWAPZ_BLOCK_BYTES ||
	    output_capacity != SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	SHARED_LOCK(owner);
	result = -ESHUTDOWN;
	if (owner->state != SHARED_OPEN)
		goto refuse;
	result = -ESTALE;
	if (expected->lifecycle_epoch != owner->epoch ||
	    expected->slot_index >= owner->capacity || !expected->generation ||
	    !valid_profile(expected->codec, expected->version))
		goto refuse;
	result = -EOVERFLOW;
	if (count_read(&owner->active_reads) == SHARED_COUNT_MAX)
		goto refuse;
	count_enter(&owner->active_reads);
	SHARED_UNLOCK(owner);

	/* Authority resolves the exact retained pin, not an untrusted snapshot.
	 * External pin and entrant lifetime are independent of the codec lease. */
	result = owner->ops.snapshot(owner->ops.context, pin, &snapshot);
	if (result)
		goto leave;
	if (snapshot.handle.lifecycle_epoch != expected->lifecycle_epoch ||
	    snapshot.handle.generation != expected->generation ||
	    snapshot.handle.slot_index != expected->slot_index ||
	    snapshot.handle.codec != expected->codec ||
	    snapshot.handle.version != expected->version ||
	    snapshot.record.codec != expected->codec ||
	    snapshot.record.version != expected->version) {
		result = -ESTALE;
		goto leave;
	}
	if (!snapshot.compressed_bytes ||
	    !disjoint(owner, expected, &snapshot, scratch, verified, output)) {
		result = -EINVAL;
		goto leave;
	}
	result = swapz_zswap_import_decoder_owner_get(
		&owner->providers[expected->codec - 1U], &lease);
	if (result)
		goto leave;
	result = swapz_original_decode(&lease, &snapshot.record, ceiling,
		snapshot.compressed_bytes, snapshot.compressed_capacity,
		scratch, scratch_capacity, verified, verified_capacity);
	release_result = swapz_zswap_import_decoder_owner_put(&lease);
	if (release_result)
		result = -EIO;
leave:
	if (release_result) {
		SHARED_LOCK(owner);
		owner->state = SHARED_FAULTED;
		SHARED_UNLOCK(owner);
	}
	/* Keep the admitted read counted through the final unlocked copy.
	 * No fallible operation follows output publication. The external
	 * entrant and storage pin still remain held through return. */
	if (!result)
		memcpy(output, verified, SWAPZ_BLOCK_BYTES);
	count_leave(&owner->active_reads);
	return result;
refuse:
	SHARED_UNLOCK(owner);
	return result;
}

int swapz_original_decoder_shared_begin_close(
	struct swapz_original_decoder_shared *owner, swapz_u64 epoch)
{
	int result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !epoch)
		return -EINVAL;
	SHARED_LOCK(owner);
	if (owner->epoch != epoch)
		result = -ESTALE;
	else if (owner->state == SHARED_OPEN)
		owner->state = SHARED_CLOSING;
	else if (owner->state != SHARED_CLOSING)
		result = -ESHUTDOWN;
	SHARED_UNLOCK(owner);
	return result;
}

int swapz_original_decoder_shared_finish_close(
	struct swapz_original_decoder_shared *owner, swapz_u64 epoch)
{
	unsigned int index;
	int result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !epoch)
		return -EINVAL;
	SHARED_LOCK(owner);
	if (owner->epoch != epoch)
		result = -ESTALE;
	else if (owner->state != SHARED_CLOSING)
		result = -ESHUTDOWN;
	else if (count_read(&owner->active_reads))
		result = -EBUSY;
	else
		owner->state = SHARED_FINISHING;
	SHARED_UNLOCK(owner);
	if (result)
		return result;
	/* External entrant revocation/join is mandatory before this point.
	 * No new get can start. Validate BOTH independent owners before the
	 * first destructive step, so a count mismatch cannot half-close. */
	for (index = 0U; index < 2U; ++index) {
		if (owner->retained[index].owner != &owner->providers[index] ||
		    owner->providers[index].active_readers != 1U) {
			SHARED_LOCK(owner);
			owner->state = SHARED_FAULTED;
			SHARED_UNLOCK(owner);
			return -EUCLEAN;
		}
	}
	/* Each shared retained lease is released once. A later primitive
	 * failure quarantines partially destroyed storage; never retry. */
	for (index = 0U; index < 2U; ++index) {
		result = release_provider(owner, index);
		if (result) {
			SHARED_LOCK(owner);
			owner->state = SHARED_FAULTED;
			SHARED_UNLOCK(owner);
			return result;
		}
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_destroy(&owner->lock)) {
		owner->state = SHARED_FAULTED;
		return -EIO;
	}
#endif
	return 0;
}

/* Gate callbacks are used only while the external gate retains authority.
 * Lifecycle serialization excludes changing the copied callbacks. */
static int gate_reserve_epoch(void *context, swapz_u64 *epoch)
{
	struct swapz_original_decoder_shared_gate *gate = context;
	swapz_u64 identity = 0U;
	int result = gate->authority.reserve_epoch(gate->authority.context, &identity);

	if (result)
		return result;
	if (identity != gate->last_session)
		return -ESTALE;
	*epoch = identity;
	return 0;
}

static int gate_snapshot(void *context, swapz_u64 pin,
	struct swapz_original_decoder_value_snapshot *snapshot)
{
	struct swapz_original_decoder_shared_gate *gate = context;

	return gate->authority.snapshot(gate->authority.context, pin, snapshot);
}

int swapz_original_decoder_shared_gate_init(
	struct swapz_original_decoder_shared_gate *gate)
{
	if (!gate || gate->state)
		return -EINVAL;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_init(&gate->lock, NULL))
		return -EIO;
#else
	spin_lock_init(&gate->lock);
#endif
	count_init(&gate->entrants);
	gate->state = SHARED_IDLE;
	return 0;
}

int swapz_original_decoder_shared_gate_open(
	struct swapz_original_decoder_shared_gate *gate,
	struct swapz_original_decoder_shared *owner,
	const struct swapz_original_decoder_shared_ops *authority,
	swapz_u32 capacity, swapz_u64 session, swapz_u64 broker_epoch)
{
	const struct swapz_original_decoder_shared_ops ops = {
		.context = gate, .reserve_epoch = gate_reserve_epoch,
		.snapshot = gate_snapshot,
	};
	swapz_u64 epoch = 0U;
	int result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!gate || !owner || owner->state || !authority ||
	    !authority->reserve_epoch || !authority->snapshot || !capacity ||
	    !session || session == ~(swapz_u64)0 || session != broker_epoch)
		return -EINVAL;
	if (swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		owner, (swapz_u32)sizeof(*owner)) ||
	    swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		authority, (swapz_u32)sizeof(*authority)))
		return -EINVAL;
	SHARED_LOCK(gate);
	if (gate->state != SHARED_IDLE) {
		SHARED_UNLOCK(gate);
		return -EBUSY;
	}
	if (session <= gate->last_session) {
		SHARED_UNLOCK(gate);
		return -ESTALE;
	}
	/* Burn the exact fresh broker identity before any fallible setup. */
	gate->last_session = session;
	gate->state = SHARED_PREPARING;
	gate->authority = *authority;
	gate->owner = owner;
	SHARED_UNLOCK(gate);
	result = swapz_original_decoder_shared_init(owner, &ops, capacity, &epoch);
	SHARED_LOCK(gate);
	if (result) {
		if (owner->state == SHARED_FAULTED)
			gate->state = SHARED_FAULTED;
		else {
			gate->owner = NULL;
			memset(&gate->authority, 0, sizeof(gate->authority));
			gate->state = SHARED_IDLE;
		}
	} else
		gate->state = SHARED_OPEN;
	SHARED_UNLOCK(gate);
	return result;
}

int swapz_original_decoder_shared_gate_read(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session,
	swapz_u64 pin, const struct swapz_original_decoder_value_handle *expected,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	struct swapz_original_decoder_shared *owner;
	int result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!gate || !session || !expected || !scratch || !verified || !output)
		return -EINVAL;
	if (swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		expected, (swapz_u32)sizeof(*expected)) ||
	    swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		scratch, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		verified, SWAPZ_BLOCK_BYTES) ||
	    swapz_zswap_import_ranges_overlap(gate, (swapz_u32)sizeof(*gate),
		output, SWAPZ_BLOCK_BYTES))
		return -EINVAL;
	SHARED_LOCK(gate);
	if (gate->state != SHARED_OPEN || session != gate->last_session) {
		SHARED_UNLOCK(gate);
		return -ESTALE;
	}
	if (count_read(&gate->entrants) == SHARED_COUNT_MAX) {
		SHARED_UNLOCK(gate);
		return -EOVERFLOW;
	}
	owner = gate->owner;
	count_enter(&gate->entrants);
	SHARED_UNLOCK(gate);
	result = swapz_original_decoder_shared_read(owner, pin, expected, ceiling,
		scratch, scratch_capacity, verified, verified_capacity, output, output_capacity);
	count_leave(&gate->entrants);
	return result;
}

int swapz_original_decoder_shared_gate_begin_close(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session)
{
	struct swapz_original_decoder_shared *owner;
	int result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!gate || !session)
		return -EINVAL;
	SHARED_LOCK(gate);
	if (session != gate->last_session ||
	    (gate->state != SHARED_OPEN && gate->state != SHARED_CLOSING)) {
		SHARED_UNLOCK(gate);
		return -ESTALE;
	}
	gate->state = SHARED_CLOSING;
	owner = gate->owner;
	SHARED_UNLOCK(gate);
	result = swapz_original_decoder_shared_begin_close(owner, session);
	if (result) {
		SHARED_LOCK(gate);
		gate->state = SHARED_FAULTED;
		SHARED_UNLOCK(gate);
	}
	return result;
}

int swapz_original_decoder_shared_gate_finish_close(
	struct swapz_original_decoder_shared_gate *gate, swapz_u64 session)
{
	struct swapz_original_decoder_shared *owner;
	int result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!gate || !session)
		return -EINVAL;
	SHARED_LOCK(gate);
	if (session != gate->last_session || gate->state != SHARED_CLOSING) {
		SHARED_UNLOCK(gate);
		return -ESTALE;
	}
	if (count_read(&gate->entrants)) {
		SHARED_UNLOCK(gate);
		return -EBUSY;
	}
	gate->state = SHARED_FINISHING;
	owner = gate->owner;
	SHARED_UNLOCK(gate);
	result = swapz_original_decoder_shared_finish_close(owner, session);
	SHARED_LOCK(gate);
	if (!result) {
		gate->owner = NULL;
		memset(&gate->authority, 0, sizeof(gate->authority));
		gate->state = SHARED_IDLE;
	} else
		gate->state = result == -EBUSY ? SHARED_CLOSING : SHARED_FAULTED;
	SHARED_UNLOCK(gate);
	return result;
}
#endif
