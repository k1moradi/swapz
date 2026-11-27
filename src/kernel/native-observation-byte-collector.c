/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-byte-collector.h"
#ifdef __KERNEL__
#include <linux/string.h>
#define LOCK(c) spin_lock_irqsave(&(c)->lock, flags)
#define UNLOCK(c) spin_unlock_irqrestore(&(c)->lock, flags)
#else
#include <string.h>
#define LOCK(c) do { (void)flags; pthread_mutex_lock(&(c)->lock); } while (0)
#define UNLOCK(c) pthread_mutex_unlock(&(c)->lock)
#endif

enum { FRESH, ACTIVE, JOINING, RETAINED, SEALED, RELEASED };
enum { IDLE, BEGUN, ACCEPTED, PINNED, COPIED, UNPINNED, CLONED, UPPER };

static bool write_kind(enum swapz_byte_kind kind)
{
	return kind == SWAPZ_BYTE_WRITE || kind == SWAPZ_BYTE_FALLBACK ||
	       kind == SWAPZ_BYTE_ORDINARY || kind == SWAPZ_BYTE_ERROR;
}

static bool view(const void *bytes, size_t length, bool needed)
{
	return needed ? bytes && length == SWAPZ_BYTE_PAGE : !bytes && !length;
}

static bool live(const struct swapz_byte_collector *collector)
{
	return (collector->state == ACTIVE || collector->state == JOINING) && !collector->loss;
}

/* All append checks and byte copies share this IRQ-safe lock. */
static bool finish(struct swapz_byte_collector *collector, bool ok)
{
	if (!ok && (collector->state == ACTIVE || collector->state == JOINING))
		collector->loss = true;
	return ok;
}

/* v2 tokens share a single namespace, including across identity roles. */
static bool token_used(const struct swapz_byte_collector *collector, u64 token)
{
	unsigned int index;
	for (index = 0; index < collector->count; ++index) {
		const struct swapz_byte_record *record = &collector->records[index];
		if (token == record->operation || token == record->original ||
		    token == record->clone || token == record->descriptor || token == record->pin)
			return true;
	}
	return false;
}

static struct swapz_byte_record *pending(struct swapz_byte_collector *collector, u64 operation)
{
	if (!live(collector) || collector->phase == IDLE || !collector->count ||
	    collector->records[collector->count - 1].operation != operation)
		return NULL;
	return &collector->records[collector->count - 1];
}

bool swapz_byte_start(struct swapz_byte_collector *collector, u32 first, u32 pages)
{
	if (!collector || collector->state != FRESH || !first || !pages ||
	    pages > SWAPZ_BYTE_LOGICAL_PAGES || first > (u32)~0U - (pages - 1))
		return false;
#ifdef __KERNEL__
	spin_lock_init(&collector->lock);
#else
	if (pthread_mutex_init(&collector->lock, NULL))
		return false;
#endif
	collector->first = first;
	collector->pages = pages;
	collector->state = ACTIVE;
	return true;
}

bool swapz_byte_begin(struct swapz_byte_collector *collector, enum swapz_byte_kind kind,
		      u32 logical, u64 operation, u64 original, const void *bytes, size_t length)
{
	unsigned long flags = 0;
	bool ok;
	LOCK(collector);
	ok = live(collector) && collector->phase == IDLE &&
	     collector->count < SWAPZ_BYTE_OPERATIONS && operation && original &&
	     operation != original && !token_used(collector, operation) && !token_used(collector, original) &&
	     (!collector->count || collector->records[collector->count - 1].kind != SWAPZ_BYTE_ERROR) &&
	     kind >= SWAPZ_BYTE_WRITE && kind <= SWAPZ_BYTE_ERROR &&
	     logical >= collector->first && logical - collector->first < collector->pages &&
	     view(bytes, length, write_kind(kind));
	if (ok) {
		struct swapz_byte_record *record = &collector->records[collector->count++];
		record->operation = operation;
		record->original = original;
		record->logical = logical;
		record->kind = kind;
		if (length)
			memcpy(record->input_page, bytes, length);
		collector->phase = BEGUN;
	}
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

bool swapz_byte_accept(struct swapz_byte_collector *collector, u64 operation, u64 original,
		       u64 clone, u64 descriptor, u64 sequence)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && collector->phase == BEGUN && record->original == original &&
	     clone && descriptor && clone != descriptor && !token_used(collector, clone) &&
	     !token_used(collector, descriptor) && sequence && sequence <= SWAPZ_BYTE_MAX_SEQUENCE &&
	     (collector->count == 1 ||
	     sequence > collector->records[collector->count - 2].upper_sequence);
	if (ok) {
		record->clone = clone;
		record->descriptor = descriptor;
		record->accept_sequence = sequence;
		collector->phase = ACCEPTED;
	}
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

static bool pin_event(struct swapz_byte_collector *collector, u64 operation, u64 descriptor,
		      u64 pin, u64 sequence, unsigned int next, const void *bytes, size_t length)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && record->kind == SWAPZ_BYTE_READ && record->descriptor == descriptor && pin &&
	     sequence <= SWAPZ_BYTE_MAX_SEQUENCE;
	if (ok && next == PINNED) {
		ok = collector->phase == ACCEPTED && sequence > record->accept_sequence &&
		     !token_used(collector, pin);
		if (ok) {
			record->pin = pin;
			record->pin_sequence = sequence;
		}
	} else if (ok && next == COPIED) {
		ok = collector->phase == PINNED && record->pin == pin &&
		     sequence > record->pin_sequence && view(bytes, length, true);
		if (ok) {
			memcpy(record->final_copy, bytes, length);
			record->copy_sequence = sequence;
		}
	} else if (ok) {
		ok = collector->phase == COPIED && record->pin == pin && sequence > record->copy_sequence;
		if (ok)
			record->release_sequence = sequence;
	}
	if (ok)
		collector->phase = next;
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

bool swapz_byte_pin(struct swapz_byte_collector *collector, u64 operation, u64 descriptor, u64 pin, u64 sequence)
{
	return pin_event(collector, operation, descriptor, pin, sequence, PINNED, NULL, 0);
}
bool swapz_byte_copy(struct swapz_byte_collector *collector, u64 operation, u64 descriptor, u64 pin,
		     u64 sequence, const void *bytes, size_t length)
{
	return pin_event(collector, operation, descriptor, pin, sequence, COPIED, bytes, length);
}
bool swapz_byte_unpin(struct swapz_byte_collector *collector, u64 operation, u64 descriptor, u64 pin, u64 sequence)
{
	return pin_event(collector, operation, descriptor, pin, sequence, UNPINNED, NULL, 0);
}

bool swapz_byte_clone(struct swapz_byte_collector *collector, u64 operation, u64 clone,
		      u64 descriptor, u64 sequence, unsigned int status)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && record->clone == clone && record->descriptor == descriptor &&
	     sequence <= SWAPZ_BYTE_MAX_SEQUENCE && status <= 255 &&
	     (status != 0) == (record->kind == SWAPZ_BYTE_ERROR) &&
	     (record->kind == SWAPZ_BYTE_READ ? collector->phase == UNPINNED &&
	      sequence > record->release_sequence : collector->phase == ACCEPTED &&
	      sequence > record->accept_sequence);
	if (ok) {
		record->clone_sequence = sequence;
		record->user_status = status;
		collector->phase = CLONED;
	}
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

bool swapz_byte_upper(struct swapz_byte_collector *collector, u64 operation, u64 original,
		      u64 clone, u64 descriptor, u64 sequence, unsigned int status)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && collector->phase == CLONED && record->original == original &&
	     record->clone == clone && record->descriptor == descriptor &&
	     status == record->user_status && sequence > record->clone_sequence &&
	     sequence <= SWAPZ_BYTE_MAX_SEQUENCE;
	if (ok) {
		record->upper_sequence = sequence;
		collector->phase = UPPER;
	}
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

bool swapz_byte_complete(struct swapz_byte_collector *collector, u64 operation, u64 original)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && collector->phase == UPPER && record->original == original;
	if (ok)
		collector->phase = IDLE;
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

#ifndef __KERNEL__
bool swapz_byte_user(struct swapz_byte_collector *collector, u64 operation, u64 original,
		     unsigned int status, const void *bytes, size_t length)
{
	unsigned long flags = 0;
	struct swapz_byte_record *record;
	bool ok;
	LOCK(collector);
	record = pending(collector, operation);
	ok = record && collector->phase == UPPER && record->original == original &&
	     status == record->user_status && view(bytes, length, record->kind == SWAPZ_BYTE_READ);
	if (ok) {
		if (length)
			memcpy(record->user_page, bytes, length);
		collector->phase = IDLE;
	}
	finish(collector, ok);
	UNLOCK(collector);
	return ok;
}

#endif /* historical synthetic user fixture */

void swapz_byte_invalidate(struct swapz_byte_collector *collector)
{
	unsigned long flags = 0;
	LOCK(collector);
	finish(collector, false);
	UNLOCK(collector);
}

bool swapz_byte_stop(struct swapz_byte_collector *collector, swapz_byte_join join, void *context)
{
	unsigned long flags = 0;
	bool joined, clean;
	if (!join || (collector->state != ACTIVE && collector->state != RETAINED))
		return false;
	LOCK(collector);
	collector->state = JOINING;
	UNLOCK(collector);
	joined = join(context);
	LOCK(collector);
	collector->loss |= !joined || collector->phase != IDLE || !collector->count;
	collector->state = joined ? SEALED : RETAINED;
	clean = joined && !collector->loss;
	UNLOCK(collector);
	return clean;
}

bool swapz_byte_export(const struct swapz_byte_collector *collector,
		       const struct swapz_byte_record **records, unsigned int *count)
{
	if (!records || !count)
		return false;
	*records = NULL;
	*count = 0;
	if (collector->state != SEALED || collector->loss)
		return false;
	*records = collector->records;
	*count = collector->count;
	return true;
}

bool swapz_byte_release(struct swapz_byte_collector *collector)
{
	if (collector->state != SEALED)
		return false;
#ifdef __KERNEL__
	memzero_explicit(collector->records, sizeof(collector->records));
#else
	volatile unsigned char *bytes = (volatile unsigned char *)collector->records;
	size_t index;
	for (index = 0; index < sizeof(collector->records); ++index)
		bytes[index] = 0;
#endif
	collector->state = RELEASED;
	return true;
}
