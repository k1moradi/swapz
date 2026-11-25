// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-decoder-handles.h"

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
#include <errno.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
/* Unique until this process unloads the implementation or the counter
 * saturates. This is NOT a production module lifetime credential. */
static atomic_uint_least64_t next_lifecycle_epoch = 1U;
#else
#include <linux/atomic.h>
#include <linux/errno.h>
#include <linux/string.h>
/* Bounded signed atomic epoch: never permit wrap into another identity. */
static atomic64_t next_lifecycle_epoch = ATOMIC64_INIT(1);
#endif

static int reserve_lifecycle_epoch(swapz_u64 *epoch)
{
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	uint_least64_t observed =
		atomic_load_explicit(&next_lifecycle_epoch, memory_order_relaxed);

	for (;;) {
		if (observed == 0U || observed == UINT_LEAST64_MAX)
			return -EOVERFLOW;
		if (atomic_compare_exchange_weak_explicit(&next_lifecycle_epoch,
				&observed, observed + 1U, memory_order_relaxed,
				memory_order_relaxed)) {
			*epoch = (swapz_u64)observed;
			return 0;
		}
	}
#else
	s64 observed = atomic64_read(&next_lifecycle_epoch);

	for (;;) {
		if (observed <= 0 || observed == 0x7fffffffffffffffLL)
			return -EOVERFLOW;
		if (atomic64_cmpxchg(&next_lifecycle_epoch, observed,
				    observed + 1) == observed) {
			*epoch = (swapz_u64)observed;
			return 0;
		}
		observed = atomic64_read(&next_lifecycle_epoch);
	}
#endif
}

#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
static int owner_lock(struct swapz_original_decoder_handle_owner *owner)
{
	return pthread_mutex_lock(&owner->lock) ? -EIO : 0;
}
static void owner_unlock(struct swapz_original_decoder_handle_owner *owner)
{
	pthread_mutex_unlock(&owner->lock);
}
#define LOCK_OWNER(owner) if (owner_lock(owner)) return -EIO
#define UNLOCK_OWNER(owner) owner_unlock(owner)
#else
#define LOCK_OWNER(owner) spin_lock_irqsave(&(owner)->lock, flags)
#define UNLOCK_OWNER(owner) spin_unlock_irqrestore(&(owner)->lock, flags)
#endif

static int decoder_index(swapz_u8 codec, swapz_u8 version)
{
	if (version != SWAPZ_ZSWAP_IMPORT_VERSION)
		return -1;
	if (codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC)
		return 0;
	if (codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)
		return 1;
	return -1;
}

static struct swapz_original_decoder_value_slot *find_record(
	struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_handle *handle)
{
	struct swapz_original_decoder_value_slot *slot;

	if (handle->lifecycle_epoch != owner->lifecycle_epoch ||
	    handle->generation == 0U ||
	    handle->slot_index >= SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS)
		return NULL;
	slot = &owner->slots[handle->slot_index];
	if (!slot->active || slot->last_generation != handle->generation ||
	    !slot->record_lease.owner ||
	    slot->record_lease.codec != handle->codec ||
	    slot->record_lease.version != handle->version)
		return NULL;
	return slot;
}

int swapz_original_decoder_handles_init(
	struct swapz_original_decoder_handle_owner *owner)
{
	int result;

	if (!owner)
		return -EINVAL;
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	if (pthread_mutex_init(&owner->lock, NULL))
		return -EIO;
#else
	spin_lock_init(&owner->lock);
#endif
	result = swapz_zswap_import_decoder_owner_init(
		&owner->decoders[0], SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
		SWAPZ_ZSWAP_IMPORT_VERSION);
	if (result)
		goto fail_lock;
	result = swapz_zswap_import_decoder_owner_init(
		&owner->decoders[1], SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC,
		SWAPZ_ZSWAP_IMPORT_VERSION);
	if (result)
		goto fail_first;
	result = reserve_lifecycle_epoch(&owner->lifecycle_epoch);
	if (!result)
		return 0;
	swapz_zswap_import_decoder_owner_close_and_drain(&owner->decoders[1]);
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_cond_destroy(&owner->decoders[1].drained);
	pthread_mutex_destroy(&owner->decoders[1].lock);
#endif
fail_first:
	swapz_zswap_import_decoder_owner_close_and_drain(&owner->decoders[0]);
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_cond_destroy(&owner->decoders[0].drained);
	pthread_mutex_destroy(&owner->decoders[0].lock);
#endif
fail_lock:
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	pthread_mutex_destroy(&owner->lock);
#endif
	return result;
}

int swapz_original_decoder_handle_get(
	struct swapz_original_decoder_handle_owner *owner,
	swapz_u8 codec, swapz_u8 version,
	struct swapz_original_decoder_value_handle *handle)
{
	struct swapz_original_decoder_value_slot *slot = NULL;
	struct swapz_original_decoder_value_handle new_handle;
	unsigned int index;
	int result, profile = decoder_index(codec, version);
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !handle || profile < 0)
		return -EINVAL;
	if (swapz_zswap_import_ranges_overlap(owner,
			(swapz_u32)sizeof(*owner), handle,
			(swapz_u32)sizeof(*handle)))
		return -EINVAL;
	LOCK_OWNER(owner);
	result = -ESHUTDOWN;
	if (owner->closing || owner->faulted)
		goto unlock;
	result = -ENOSPC;
	for (index = 0U; index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS; ++index) {
		struct swapz_original_decoder_value_slot *candidate =
			&owner->slots[index];

		if (candidate->active)
			continue;
		if (candidate->last_generation == ~(swapz_u64)0)
			continue;
		slot = candidate;
		break;
	}
	if (!slot) {
		if (owner->active_records == 0U)
			result = -EOVERFLOW;
		goto unlock;
	}
	/* Consume generation even if the codec provider refuses the get.
	 * This prevents an old value from ever becoming valid again. */
	++slot->last_generation;
	result = swapz_zswap_import_decoder_owner_get(
		&owner->decoders[profile], &slot->record_lease);
	if (result)
		goto unlock;
	slot->active = 1U;
	++owner->active_records;
	new_handle = (struct swapz_original_decoder_value_handle) {
		.lifecycle_epoch = owner->lifecycle_epoch,
		.generation = slot->last_generation,
		.slot_index = index,
		.codec = codec,
		.version = version,
	};
	*handle = new_handle;
unlock:
	UNLOCK_OWNER(owner);
	return result;
}

int swapz_original_decoder_handle_put(
	struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_handle *handle)
{
	struct swapz_original_decoder_value_slot *slot;
	int result = -ESTALE;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !handle)
		return -EINVAL;
	if (swapz_zswap_import_ranges_overlap(owner,
			(swapz_u32)sizeof(*owner), handle,
			(swapz_u32)sizeof(*handle)))
		return -EINVAL;
	LOCK_OWNER(owner);
	if (owner->closing || owner->faulted) {
		result = -ESHUTDOWN;
		goto unlock;
	}
	slot = find_record(owner, handle);
	if (slot) {
		result = swapz_zswap_import_decoder_owner_put(&slot->record_lease);
		if (result)
			owner->faulted = 1U;
		else {
			slot->active = 0U;
			--owner->active_records;
		}
	}
unlock:
	UNLOCK_OWNER(owner);
	return result;
}

static int spans_valid(
	const struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	const swapz_u8 *scratch, const swapz_u8 *verified,
	const swapz_u8 *output)
{
	const void *const addresses[] = {
		owner, snapshot, snapshot->compressed_bytes,
		scratch, verified, output
	};
	const swapz_u32 sizes[] = {
		(swapz_u32)sizeof(*owner), (swapz_u32)sizeof(*snapshot),
		snapshot->record.compressed_length, SWAPZ_BLOCK_BYTES,
		SWAPZ_BLOCK_BYTES, SWAPZ_BLOCK_BYTES
	};
	unsigned int first, second;

	for (first = 0U; first < 6U; ++first)
		for (second = first + 1U; second < 6U; ++second)
			if (swapz_zswap_import_ranges_overlap(addresses[first],
				sizes[first], addresses[second], sizes[second]))
				return 0;
	return 1;
}

int swapz_original_decoder_handle_read(
	struct swapz_original_decoder_handle_owner *owner,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *scratch, swapz_u32 scratch_capacity,
	swapz_u8 *verified, swapz_u32 verified_capacity,
	swapz_u8 *output, swapz_u32 output_capacity)
{
	struct swapz_zswap_import_decoder_lease read_lease = {0};
	struct swapz_original_decoder_value_slot *slot;
	struct swapz_original_decode_record record;
	const swapz_u8 *compressed_bytes;
	swapz_u32 compressed_capacity;
	int result = -ESTALE, release_result;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner || !snapshot || !snapshot->compressed_bytes ||
	    !scratch || !verified || !output ||
	    scratch_capacity != SWAPZ_BLOCK_BYTES ||
	    verified_capacity != SWAPZ_BLOCK_BYTES ||
	    output_capacity != SWAPZ_BLOCK_BYTES ||
	    !spans_valid(owner, snapshot, scratch, verified, output))
		return -EINVAL;
	record = snapshot->record;
	compressed_bytes = snapshot->compressed_bytes;
	compressed_capacity = snapshot->compressed_capacity;
	LOCK_OWNER(owner);
	if (owner->closing || owner->faulted) {
		result = -ESHUTDOWN;
	} else {
		slot = find_record(owner, &snapshot->handle);
		if (slot && slot->record_lease.codec == record.codec &&
		    slot->record_lease.version == record.version &&
		    owner->active_reads != ~0U) {
			result = swapz_zswap_import_decoder_owner_get(
				slot->record_lease.owner, &read_lease);
			if (!result)
				++owner->active_reads;
		}
	}
	UNLOCK_OWNER(owner);
	if (result)
		return result;
	result = swapz_original_decode(&read_lease, &record, ceiling,
		compressed_bytes, compressed_capacity, scratch, scratch_capacity,
		verified, verified_capacity);
	release_result = swapz_zswap_import_decoder_owner_put(&read_lease);
	if (release_result)
		result = -EIO;
	/* A put may retire the record after the read acquired its own
	 * independent codec/module lease. The output commit is protected
	 * against close until this last counted reader exits. */
	LOCK_OWNER(owner);
	if (!result)
		memcpy(output, verified, SWAPZ_BLOCK_BYTES);
	--owner->active_reads;
	if (release_result)
		owner->faulted = 1U;
	UNLOCK_OWNER(owner);
	return result;
}

int swapz_original_decoder_handles_close(
	struct swapz_original_decoder_handle_owner *owner)
{
	unsigned int index;
	int result = 0;
#ifndef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	unsigned long flags;
#endif

	if (!owner)
		return -EINVAL;
	LOCK_OWNER(owner);
	if (owner->active_reads || owner->active_records)
		result = -EBUSY;
	else if (owner->closing)
		result = -EALREADY;
	else
		owner->closing = 1U;
	UNLOCK_OWNER(owner);
	if (result)
		return result;
	for (index = 0U; index < 2U; ++index) {
		result = swapz_zswap_import_decoder_owner_close_and_drain(
			&owner->decoders[index]);
		if (result)
			return result;
	}
#ifdef SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST
	for (index = 0U; index < 2U; ++index) {
		pthread_cond_destroy(&owner->decoders[index].drained);
		pthread_mutex_destroy(&owner->decoders[index].lock);
	}
	pthread_mutex_destroy(&owner->lock);
#endif
	return 0;
}
#endif /* SWAPZ_ORIGINAL_STORAGE_TEST */
