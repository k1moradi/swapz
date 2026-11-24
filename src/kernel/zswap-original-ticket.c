// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-ticket.h"
#ifdef SWAPZ_ORIGINAL_TICKET_TEST
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

static int ticket_lock(struct swapz_ticket_broker *broker, unsigned long *flags, bool nonblocking)
{
#ifdef __KERNEL__
	if (nonblocking) {
		if (!spin_trylock_irqsave(&broker->lock, *flags))
			return -EAGAIN;
	} else {
		spin_lock_irqsave(&broker->lock, *flags);
	}
#else
	int error;
	(void)flags;
	error = nonblocking ? pthread_mutex_trylock(&broker->lock) :
		pthread_mutex_lock(&broker->lock);
	if (error)
		return error == EBUSY && nonblocking ? -EAGAIN : -EIO;
#endif
	return 0;
}

static void ticket_unlock(struct swapz_ticket_broker *broker, unsigned long flags)
{
#ifdef __KERNEL__
	spin_unlock_irqrestore(&broker->lock, flags);
#else
	(void)flags;
	(void)pthread_mutex_unlock(&broker->lock);
#endif
}

/* Linux ABI: unsigned long is pointer-sized. Subtract to avoid overflow. */
static bool overlap(const void *first, size_t first_bytes, const void *second, size_t second_bytes)
{
	unsigned long a = (unsigned long)first, b = (unsigned long)second;
	return a <= b ? b - a < first_bytes : a - b < second_bytes;
}

static bool exact_array(size_t count, size_t stride, size_t bytes)
{
	return stride && count <= (size_t)-1 / stride && bytes == count * stride;
}

int swapz_ticket_init(struct swapz_ticket_broker *broker,
	struct swapz_ticket_slot *slots, size_t metadata_bytes,
	swapz_u8 *payload, size_t payload_bytes, swapz_u32 *free_indices,
	size_t index_bytes, swapz_u32 count, swapz_u32 max_length,
	swapz_u64 byte_limit, swapz_u64 session, swapz_u64 epoch)
{
	size_t stride;
	swapz_u32 index;
	if (!broker || !slots || !payload || !free_indices || !count ||
	    !session || !epoch || !byte_limit || broker->initialized)
		return -EINVAL;
	if (max_length != 3568U && max_length != 4095U)
		return -EMSGSIZE;
	stride = ((size_t)max_length + SWAPZ_TICKET_ALIGNMENT - 1U) &
		~((size_t)SWAPZ_TICKET_ALIGNMENT - 1U);
	if ((unsigned long)payload % SWAPZ_TICKET_ALIGNMENT ||
	    (unsigned long)slots % __alignof__(struct swapz_ticket_slot) ||
	    (unsigned long)free_indices % __alignof__(swapz_u32))
		return -EINVAL;
	if (!exact_array(count, stride, payload_bytes) ||
	    !exact_array(count, sizeof(*slots), metadata_bytes) ||
	    !exact_array(count, sizeof(*free_indices), index_bytes) ||
	    byte_limit > (swapz_u64)count * max_length)
		return -EMSGSIZE;
	if (metadata_bytes > (size_t)-1 - sizeof(*broker) ||
	    index_bytes > (size_t)-1 - sizeof(*broker) - metadata_bytes ||
	    payload_bytes > (size_t)-1 - sizeof(*broker) - metadata_bytes - index_bytes)
		return -EOVERFLOW;
	if (overlap(payload, payload_bytes, slots, metadata_bytes) ||
	    overlap(payload, payload_bytes, free_indices, index_bytes) ||
	    overlap(slots, metadata_bytes, free_indices, index_bytes) ||
	    overlap(broker, sizeof(*broker), payload, payload_bytes) ||
	    overlap(broker, sizeof(*broker), slots, metadata_bytes) ||
	    overlap(broker, sizeof(*broker), free_indices, index_bytes))
		return -EINVAL;
#ifdef __KERNEL__
	spin_lock_init(&broker->lock);
#else
	if (pthread_mutex_init(&broker->lock, NULL))
		return -EIO;
#endif
	memset(slots, 0, metadata_bytes);
	for (index = 0; index < count; ++index)
		free_indices[index] = count - index - 1U;
	broker->slots = slots;
	broker->payload = payload;
	broker->free_indices = free_indices;
	broker->stride = stride;
	broker->payload_bytes = payload_bytes;
	broker->metadata_bytes = metadata_bytes;
	broker->index_bytes = index_bytes;
	broker->session = session;
	broker->epoch = epoch;
	broker->next_generation = 0;
	broker->byte_limit = byte_limit;
	broker->used_bytes = 0;
	broker->capacity = count;
	broker->free_count = count;
	broker->max_length = max_length;
	broker->closing = false;
	broker->initialized = true;
	return 0;
}
static bool key_valid(const struct swapz_ticket_key *key)
{
	return key->area_epoch && key->store_sequence && key->target_session &&
		key->table_epoch && key->target_epoch && key->dm_generation &&
		key->representation == SWAPZ_TICKET_ORIGINAL &&
		(key->codec == SWAPZ_TICKET_LZ4 || key->codec == SWAPZ_TICKET_LZO1X) &&
		key->version == 1U && !key->dictionary &&
		key->decoded_length == SWAPZ_BLOCK_BYTES;
}
static bool keys_equal(const struct swapz_ticket_key *a, const struct swapz_ticket_key *b)
{
	return a->area_epoch == b->area_epoch &&
		a->store_sequence == b->store_sequence &&
		a->slot_offset == b->slot_offset && a->swap_type == b->swap_type &&
		a->target_session == b->target_session &&
		a->table_epoch == b->table_epoch && a->target_epoch == b->target_epoch &&
		a->logical_page == b->logical_page && a->dm_generation == b->dm_generation &&
		a->length == b->length && a->decoded_length == b->decoded_length &&
		a->crc == b->crc && a->representation == b->representation &&
		a->codec == b->codec && a->version == b->version &&
		a->dictionary == b->dictionary &&
		!memcmp(a->sha256, b->sha256, sizeof(a->sha256));
}
/* All slot lookup/metadata changes require the broker lock. */
static struct swapz_ticket_slot *ticket_slot(const struct swapz_ticket_ref *ref)
{
	struct swapz_ticket_broker *broker = ref->broker;
	struct swapz_ticket_slot *slot;
	if (ref->session != broker->session || ref->index >= broker->capacity)
		return NULL;
	slot = &broker->slots[ref->index];
	if (!slot->refs || slot->generation != ref->generation)
		return NULL;
	return slot;
}
static bool ticket_current(const struct swapz_ticket_broker *broker, const struct swapz_ticket_slot *slot)
{
	return !broker->closing && slot->key.table_epoch == broker->epoch &&
		slot->state != SWAPZ_TICKET_REVOKED;
}
int swapz_ticket_reserve(struct swapz_ticket_broker *broker,
	const struct swapz_ticket_key *key, struct swapz_ticket_ref *out)
{
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	swapz_u32 index;
	int error;
	if (!out || out->broker)
		return -EINVAL;
	*out = (struct swapz_ticket_ref){0};
	if (!broker || !broker->initialized || !key || !key_valid(key))
		return -EINVAL;
	if (!key->length || key->length > broker->max_length)
		return -EMSGSIZE;
	error = ticket_lock(broker, &flags, true);
	if (error)
		return error;
	if (broker->closing)
		error = -ESHUTDOWN;
	else if (key->target_session != broker->session || key->table_epoch != broker->epoch)
		error = -ESTALE;
	else if (!broker->free_count)
		error = -ENOSPC;
	else if (key->length > broker->byte_limit - broker->used_bytes)
		error = -ENOSPC;
	else if (broker->next_generation == ~(swapz_u64)0)
		error = -EOVERFLOW;
	else {
		index = broker->free_indices[--broker->free_count];
		slot = &broker->slots[index];
		slot->key = *key;
		slot->generation = ++broker->next_generation;
		slot->refs = 1U;
		slot->state = SWAPZ_TICKET_RESERVED;
		slot->sealed = false;
		broker->used_bytes += key->length;
		*out = (struct swapz_ticket_ref){broker, broker->session, slot->generation, index};
	}
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_seal(struct swapz_ticket_ref *ref, const swapz_u8 *source, swapz_u32 length)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	swapz_u8 *destination;
	swapz_u32 crc, expected_crc;
	unsigned long flags = 0;
	int error;
	if (!ref || !ref->broker)
		return -EINVAL;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot || !ticket_current(broker, slot))
		error = -ESTALE;
	else if (slot->state != SWAPZ_TICKET_RESERVED || slot->refs != 1U)
		error = -EALREADY;
	else if (!source || length != slot->key.length ||
		 overlap(source, length, broker->payload, broker->payload_bytes) ||
		 overlap(source, length, broker->slots, broker->metadata_bytes) ||
		 overlap(source, length, broker->free_indices, broker->index_bytes) ||
		 overlap(source, length, broker, sizeof(*broker))) {
		slot->state = SWAPZ_TICKET_REVOKED;
		error = -EINVAL;
	}
	if (error) {
		ticket_unlock(broker, flags);
		return error;
	}
	slot->state = SWAPZ_TICKET_COPYING;
	destination = broker->payload + (size_t)ref->index * broker->stride;
	expected_crc = slot->key.crc;
	ticket_unlock(broker, flags);
	/* Exclusive producer lease pins storage; revoke/close may invalidate
	 * it during copy but cannot recycle it. No partial reader exposure. */
	memcpy(destination, source, length);
	crc = swapz_crc32c_bytes(destination, length);
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	if (!ticket_current(broker, slot) || slot->state != SWAPZ_TICKET_COPYING)
		error = -ESTALE;
	else if (crc != expected_crc)
		error = -EBADMSG;
	if (error)
		slot->state = SWAPZ_TICKET_REVOKED;
	else {
		slot->sealed = true;
		slot->state = SWAPZ_TICKET_SEALED;
	}
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_retain(const struct swapz_ticket_ref *ref, struct swapz_ticket_ref *out)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	int error;
	if (!out || out->broker)
		return -EINVAL;
	*out = (struct swapz_ticket_ref){0};
	if (!ref || !ref->broker)
		return -EINVAL;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot || !ticket_current(broker, slot))
		error = -ESTALE;
	else if (!slot->sealed)
		error = -EAGAIN;
	else if (slot->refs == ~(swapz_u32)0)
		error = -EOVERFLOW;
	else {
		++slot->refs;
		*out = *ref;
	}
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_claim(const struct swapz_ticket_ref *ref, const struct swapz_ticket_key *key)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	int error;
	if (!ref || !ref->broker || !key)
		return -EINVAL;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, true);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot || !ticket_current(broker, slot) || !keys_equal(&slot->key, key))
		error = -ESTALE;
	else if (slot->state != SWAPZ_TICKET_SEALED)
		error = -EALREADY;
	else
		slot->state = SWAPZ_TICKET_CLAIMED;
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_view(const struct swapz_ticket_ref *ref, struct swapz_ticket_view *out)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	int error;
	if (!ref || !ref->broker || !out)
		return -EINVAL;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot || !slot->sealed)
		error = -ESTALE;
	else {
		out->key = slot->key;
		out->bytes = broker->payload + (size_t)ref->index * broker->stride;
	}
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_cancel(const struct swapz_ticket_ref *ref)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	int error;
	if (!ref || !ref->broker)
		return -EINVAL;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot)
		error = -ESTALE;
	else if (slot->state == SWAPZ_TICKET_CLAIMED)
		error = -EBUSY;
	else
		slot->state = SWAPZ_TICKET_REVOKED;
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_put(struct swapz_ticket_ref *ref)
{
	struct swapz_ticket_broker *broker;
	struct swapz_ticket_slot *slot;
	unsigned long flags = 0;
	swapz_u32 index;
	int error;
	if (!ref || !ref->broker)
		return -EALREADY;
	broker = ref->broker;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	slot = ticket_slot(ref);
	if (!slot) {
		ticket_unlock(broker, flags);
		return -ESTALE;
	}
	index = ref->index;
	*ref = (struct swapz_ticket_ref){0};
	if (--slot->refs == 0U) {
		broker->used_bytes -= slot->key.length;
		slot->sealed = false;
		slot->state = SWAPZ_TICKET_FREE;
		broker->free_indices[broker->free_count++] = index;
	}
	ticket_unlock(broker, flags);
	return 0;
}
/* O(1) logical revocation. Old sealed refs can view/put until last put. */
int swapz_ticket_revoke(struct swapz_ticket_broker *broker, swapz_u64 next_epoch)
{
	unsigned long flags = 0;
	int error;
	if (!broker || !broker->initialized)
		return -EINVAL;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	if (broker->closing || next_epoch <= broker->epoch)
		error = -ESTALE;
	else
		broker->epoch = next_epoch;
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_close(struct swapz_ticket_broker *broker)
{
	unsigned long flags = 0;
	int error;
	if (!broker || !broker->initialized)
		return -EINVAL;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	broker->closing = true;
	if (broker->free_count != broker->capacity)
		error = -EBUSY;
	ticket_unlock(broker, flags);
	return error;
}
int swapz_ticket_destroy(struct swapz_ticket_broker *broker)
{
	unsigned long flags = 0;
	int error;
	if (!broker || !broker->initialized)
		return -EINVAL;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	if (!broker->closing || broker->free_count != broker->capacity || broker->used_bytes)
		error = -EBUSY;
	ticket_unlock(broker, flags);
	if (error)
		return error;
	/* Caller externally quiesces all API entrants before destroy. */
#ifndef __KERNEL__
	if (pthread_mutex_destroy(&broker->lock))
		return -EBUSY;
#endif
	broker->initialized = false;
	return 0;
}
int swapz_ticket_usage(struct swapz_ticket_broker *broker, struct swapz_ticket_usage *out)
{
	unsigned long flags = 0;
	int error;
	if (!broker || !broker->initialized || !out)
		return -EINVAL;
	error = ticket_lock(broker, &flags, false);
	if (error)
		return error;
	*out = (struct swapz_ticket_usage){
		broker->stride, broker->payload_bytes, broker->metadata_bytes,
		broker->index_bytes, sizeof(*broker) + broker->payload_bytes +
			broker->metadata_bytes + broker->index_bytes,
		broker->used_bytes, broker->capacity - broker->free_count};
	ticket_unlock(broker, flags);
	return 0;
}
#endif
