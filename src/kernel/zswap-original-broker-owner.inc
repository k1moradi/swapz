/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Included once in the staged built-in ticket broker translation unit.
 * The admission gate and broker address are permanent; only their bounded
 * backing arrays are session-owned. No extra broker or module self-pin.
 */
#if defined(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) || defined(SWAPZ_TICKET_OWNER_HOST_TEST)
#ifdef __KERNEL__
#include <linux/mutex.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
static DEFINE_MUTEX(owner_lifecycle_lock);
static DEFINE_SPINLOCK(owner_gate_lock);
#define owner_lock() mutex_lock(&owner_lifecycle_lock)
#define owner_unlock() mutex_unlock(&owner_lifecycle_lock)
#define gate_lock(flags) spin_lock_irqsave(&owner_gate_lock, flags)
#define gate_unlock(flags) spin_unlock_irqrestore(&owner_gate_lock, flags)
static void *owner_allocate(size_t bytes)
{
	return kvmalloc(bytes, GFP_KERNEL);
}
static void owner_free(void *pointer)
{
	kvfree(pointer);
}
#else
/* Host adapter substitutes only allocation/locking and deterministic pauses. */
static pthread_mutex_t owner_lifecycle_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t owner_gate_lock = PTHREAD_MUTEX_INITIALIZER;
#define owner_lock() r094_owner_mutex_lock(&owner_lifecycle_lock)
#define owner_unlock() r094_owner_mutex_unlock(&owner_lifecycle_lock)
#define gate_lock(flags) do { (void)(flags); r094_owner_mutex_lock(&owner_gate_lock); } while (0)
#define gate_unlock(flags) do { (void)(flags); r094_owner_mutex_unlock(&owner_gate_lock); } while (0)
#define owner_allocate(bytes) r094_owner_allocate(bytes)
#define owner_free(pointer) r094_owner_free(pointer)
#endif

/* Explicit development bound, not full-device capacity. At M4095 the
 * payload is at most 4 MiB; metadata and index sizes are checked separately.
 */
#define SWAPZ_OWNER_MAX_CAPACITY 1024U
static struct swapz_ticket_broker owner_broker;
static swapz_u64 owner_last_identity;
static swapz_u64 owner_session, owner_epoch;
static swapz_u32 owner_entrants;
static bool owner_accepting, owner_draining, owner_quarantined;

/* Admission and identity are checked before touching any session storage.
 * A delayed old pointer is harmless even across reopen: the broker address
 * is permanent and the nonreused identity is checked under the gate.
 * The caller still needs an RCU-covered borrow or retained capability.
 */
static int owner_enter(swapz_u64 session, swapz_u64 epoch)
{
	unsigned long flags = 0;
	int error = 0;

	gate_lock(flags);
	if (!owner_accepting || session != owner_session || epoch != owner_epoch)
		error = -ESTALE;
	else if (owner_entrants == ~(swapz_u32)0)
		error = -EOVERFLOW;
	else
		++owner_entrants;
	gate_unlock(flags);
	return error;
}

static void owner_leave(void)
{
	unsigned long flags = 0;

	gate_lock(flags);
	/* Every successful enter has precisely one leave in the wrapper. */
	--owner_entrants;
	gate_unlock(flags);
}

int swapz_ticket_broker_try_get(struct swapz_ticket_broker *broker,
	swapz_u64 session, swapz_u64 epoch, struct swapz_ticket_cap *out)
{
	int error;

	/* The guarded composition has exactly one broker. Reject unrelated
	 * addresses before any dereference, including stale foreign pointers.
	 */
	if (broker != &owner_broker)
		return -ESTALE;
	error = owner_enter(session, epoch);
	if (error)
		return error;
#ifndef __KERNEL__
	r094_owner_after_enter();
#endif
	error = ticket_broker_try_get_raw(broker, session, epoch, out);
	owner_leave();
	return error;
}

static bool owner_array_bytes(size_t count, size_t stride, size_t *bytes)
{
	if (!stride || count > (size_t)-1 / stride)
		return false;
	*bytes = count * stride;
	return true;
}

/* Lifecycle operations are sleepable and serialized by a permanent mutex.
 * The admission gate is never held across a broker lock or allocation.
 */
int swapz_mm_broker_owner_open(swapz_u32 capacity, swapz_u32 max_length,
	swapz_u64 byte_limit, struct swapz_ticket_cap *out)
{
	struct swapz_ticket_slot *slots = NULL;
	swapz_u8 *payload = NULL;
	swapz_u32 *indices = NULL;
	struct swapz_ticket_cap cap = {0};
	size_t stride, metadata_bytes, payload_bytes, index_bytes;
	unsigned long flags = 0;
	swapz_u64 identity;
	int error;

	if (!out || out->broker || !capacity || capacity > SWAPZ_OWNER_MAX_CAPACITY ||
	    !byte_limit)
		return -EINVAL;
	if (max_length != 3568U && max_length != 4095U)
		return -EMSGSIZE;
	if (byte_limit > (swapz_u64)capacity * max_length)
		return -EMSGSIZE;
	stride = ((size_t)max_length + SWAPZ_TICKET_ALIGNMENT - 1U) &
		~((size_t)SWAPZ_TICKET_ALIGNMENT - 1U);
	if (!owner_array_bytes(capacity, sizeof(*slots), &metadata_bytes) ||
	    !owner_array_bytes(capacity, stride, &payload_bytes) ||
	    !owner_array_bytes(capacity, sizeof(*indices), &index_bytes))
		return -EOVERFLOW;

	owner_lock();
	if (owner_broker.initialized || owner_quarantined) {
		error = -EBUSY;
		goto unlock;
	}
	if (owner_last_identity == ~(swapz_u64)0) {
		error = -EOVERFLOW;
		goto unlock;
	}
	/* Never publish a partially initialized allocation. */
	slots = owner_allocate(metadata_bytes);
	if (!slots)
		goto no_memory;
	payload = owner_allocate(payload_bytes);
	if (!payload)
		goto no_memory;
	indices = owner_allocate(index_bytes);
	if (!indices)
		goto no_memory;
	identity = ++owner_last_identity;
	error = swapz_ticket_init(&owner_broker, slots, metadata_bytes, payload,
		payload_bytes, indices, index_bytes, capacity, max_length,
		byte_limit, identity, identity);
	if (error)
		goto free_arrays;
	/* Private acquisition before publishing the gate; no outside entrant. */
	error = ticket_broker_try_get_raw(&owner_broker, identity, identity, &cap);
	if (error) {
		if (swapz_ticket_close(&owner_broker) ||
		    swapz_ticket_destroy(&owner_broker)) {
			owner_quarantined = true;
			goto unlock;
		}
		goto free_arrays;
	}
	gate_lock(flags);
	owner_session = identity;
	owner_epoch = identity;
	owner_accepting = true;
	gate_unlock(flags);
	owner_draining = false;
	*out = cap;
	goto unlock;

no_memory:
	error = -ENOMEM;
free_arrays:
	owner_free(indices);
	owner_free(payload);
	owner_free(slots);
unlock:
	owner_unlock();
	return error;
}

int swapz_mm_broker_owner_begin_close(swapz_u64 session, swapz_u64 epoch)
{
	unsigned long flags = 0;
	int error;

	owner_lock();
	if (!owner_broker.initialized || session != owner_session || epoch != owner_epoch) {
		error = -ESTALE;
		goto unlock;
	}
	if (owner_quarantined) {
		error = -EIO;
		goto unlock;
	}
	/* Caller has invalidated the route and stopped external publication.
	 * Close admission first; even pre-reference entrants already inside
	 * are counted. Broker close then fences reserve, retain and claim.
	 */
	gate_lock(flags);
	owner_accepting = false;
	gate_unlock(flags);
	error = swapz_ticket_close(&owner_broker);
	if (error && error != -EBUSY) {
		owner_quarantined = true;
		goto unlock;
	}
	owner_draining = true;
	error = 0; /* Active refs are expected; finish performs the drain check. */
unlock:
	owner_unlock();
	return error;
}

int swapz_mm_broker_owner_finish_close(swapz_u64 session, swapz_u64 epoch)
{
	unsigned long flags = 0;
	bool quiescent;
	int error;

	owner_lock();
	if (!owner_broker.initialized || session != owner_session || epoch != owner_epoch) {
		error = -ESTALE;
		goto unlock;
	}
	if (owner_quarantined) {
		error = -EIO;
		goto unlock;
	}
	if (!owner_draining) {
		error = -EBUSY;
		goto unlock;
	}
	gate_lock(flags);
	quiescent = !owner_accepting && !owner_entrants;
	gate_unlock(flags);
	if (!quiescent) {
		error = -EBUSY;
		goto unlock;
	}
	/* No future gate entrant until a fresh session. RCU-covered callers
	 * outside the gate may still reach the permanent address, but cannot
	 * access arrays. Other APIs require a retained ticket/cap; destroy
	 * checks them under the broker lock before reclaiming the arrays.
	 */
	error = swapz_ticket_destroy(&owner_broker);
	if (error) {
		if (error != -EBUSY)
			owner_quarantined = true;
		goto unlock;
	}
	/* Revocation may have advanced the table epoch beyond the open ID.
	 * Burn that high-water mark too; never reuse any earlier epoch.
	 */
	if (owner_broker.epoch > owner_last_identity)
		owner_last_identity = owner_broker.epoch;
	owner_free(owner_broker.free_indices);
	owner_free(owner_broker.payload);
	owner_free(owner_broker.slots);
	owner_broker.free_indices = NULL;
	owner_broker.payload = NULL;
	owner_broker.slots = NULL;
	owner_draining = false;
unlock:
	owner_unlock();
	return error;
}

#ifdef __KERNEL__
EXPORT_SYMBOL_GPL(swapz_mm_broker_owner_open);
EXPORT_SYMBOL_GPL(swapz_mm_broker_owner_begin_close);
EXPORT_SYMBOL_GPL(swapz_mm_broker_owner_finish_close);
#endif
#undef owner_lock
#undef owner_unlock
#undef gate_lock
#undef gate_unlock
#endif
