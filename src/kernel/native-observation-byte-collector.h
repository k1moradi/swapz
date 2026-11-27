/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_BYTE_COLLECTOR_H
#define SWAPZ_NATIVE_OBSERVATION_BYTE_COLLECTOR_H
#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/spinlock.h>
#else
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <pthread.h>
typedef uint64_t u64;
typedef uint32_t u32;
#endif

#define SWAPZ_BYTE_PAGE 4096U
#define SWAPZ_BYTE_OPERATIONS 64U
#define SWAPZ_BYTE_LOGICAL_PAGES 16U
#define SWAPZ_BYTE_MAX_SEQUENCE 8192U

enum swapz_byte_kind {
	SWAPZ_BYTE_WRITE = 1, SWAPZ_BYTE_READ, SWAPZ_BYTE_FALLBACK,
	SWAPZ_BYTE_ORDINARY, SWAPZ_BYTE_DISCARD, SWAPZ_BYTE_ERROR
};
struct swapz_byte_record {
	u64 operation, original, clone, descriptor, pin;
	u64 accept_sequence, pin_sequence, copy_sequence, release_sequence, clone_sequence, upper_sequence;
	u32 logical;
	enum swapz_byte_kind kind;
	unsigned int user_status; /* v2 completion status, not a user observation */
	unsigned char input_page[SWAPZ_BYTE_PAGE];
	unsigned char final_copy[SWAPZ_BYTE_PAGE];
#ifndef __KERNEL__
	/* Historical R102 synthetic fixture only; never kernel storage. */
	unsigned char user_page[SWAPZ_BYTE_PAGE];
#endif
};
/* Cold caller-owned zeroed storage (not stack); never relocate or reuse.
 * One controller serializes start/stop/export/release. Caller gates entry
 * before any hot-path work and joins ALL entrants before releasing storage.
 * Hot views are stable, already accessible kernel buffers, not user pointers;
 * caller holds the real BIO/page/pin authority through each synchronous copy.
 * IDs/ordinals come from actual v2 events; no pointer-derived identities.
 * Only one unsplit operation is in flight. False means lost evidence, not I/O
 * failure. No hook, export transport or authorization is installed here.
 */
struct swapz_byte_collector {
#ifdef __KERNEL__
	spinlock_t lock;
#else
	pthread_mutex_t lock;
#endif
	unsigned int state, count, phase;
	bool loss;
	u32 first, pages;
	struct swapz_byte_record records[SWAPZ_BYTE_OPERATIONS];
};
typedef bool (*swapz_byte_join)(void *context);
bool swapz_byte_start(struct swapz_byte_collector *collector, u32 first, u32 pages);
bool swapz_byte_begin(struct swapz_byte_collector *collector, enum swapz_byte_kind kind,
		      u32 logical, u64 operation, u64 original, const void *bytes, size_t length);
bool swapz_byte_accept(struct swapz_byte_collector *collector, u64 operation, u64 original,
		       u64 clone, u64 descriptor, u64 sequence);
bool swapz_byte_pin(struct swapz_byte_collector *collector, u64 operation, u64 descriptor,
		    u64 pin, u64 sequence);
bool swapz_byte_copy(struct swapz_byte_collector *collector, u64 operation, u64 descriptor,
		     u64 pin, u64 sequence, const void *bytes, size_t length);
bool swapz_byte_unpin(struct swapz_byte_collector *collector, u64 operation, u64 descriptor,
		      u64 pin, u64 sequence);
/* A provisional typed write may be classified once, before clone ACK.
 * Bridge must prove the actual ordered outcome; this is not authorization.
 */
bool swapz_byte_classify(struct swapz_byte_collector *collector, u64 operation,
			 enum swapz_byte_kind kind);
bool swapz_byte_clone(struct swapz_byte_collector *collector, u64 operation, u64 clone,
		      u64 descriptor, u64 sequence, unsigned int status);
bool swapz_byte_upper(struct swapz_byte_collector *collector, u64 operation, u64 original,
		      u64 clone, u64 descriptor, u64 sequence, unsigned int status);
/* Complete kernel evidence after actual original ACK, without any user
 * pointer or claimed user status. Independent userspace joins offline.
 */
bool swapz_byte_complete(struct swapz_byte_collector *collector, u64 operation, u64 original);
#ifndef __KERNEL__
/* Historical synthetic fixture only; not a kernel entry point. */
bool swapz_byte_user(struct swapz_byte_collector *collector, u64 operation, u64 original,
		     unsigned int status, const void *bytes, size_t length);
#endif
/* Join is synchronous, non-reentrant, outside append lock. Failed join
 * retains storage and sticks loss; retry must perform a genuine join.
 * Export borrows immutable storage until release, only after clean join.
 * Release scrubs bytes; caller frees only after release succeeds.
 */
/* Report an observed gap even when there is no complete record to append. */
void swapz_byte_invalidate(struct swapz_byte_collector *collector);
bool swapz_byte_stop(struct swapz_byte_collector *collector, swapz_byte_join join, void *context);
/* Cold owner already performed the genuine external join, exactly once.
 * All admissions must be closed before this call; false retains storage.
 */
bool swapz_byte_stop_after_join(struct swapz_byte_collector *collector, bool joined);
bool swapz_byte_export(const struct swapz_byte_collector *collector,
		       const struct swapz_byte_record **records, unsigned int *count);
bool swapz_byte_release(struct swapz_byte_collector *collector);
#endif
