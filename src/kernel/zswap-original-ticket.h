/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_ORIGINAL_TICKET_H
#define SWAPZ_ORIGINAL_TICKET_H
#include "codec.h"
#define SWAPZ_ORIGINAL_TICKET_ACTIVE 0U
#ifdef SWAPZ_ORIGINAL_TICKET_TEST
#ifdef __KERNEL__
#include <linux/spinlock.h>
#include <linux/stddef.h>
#else
#include <stdbool.h>
#include <stddef.h>
#include <pthread.h>
#endif
#define SWAPZ_TICKET_ALIGNMENT 64U
#define SWAPZ_TICKET_ORIGINAL 0x5aU
#define SWAPZ_TICKET_LZ4 1U
#define SWAPZ_TICKET_LZO1X 2U
/* Test-supplied identities, not actual MM/DM authentication. */
struct swapz_ticket_key {
	swapz_u64 area_epoch, store_sequence, slot_offset;
	swapz_u64 target_session, table_epoch, target_epoch;
	swapz_u64 logical_page, dm_generation;
	swapz_u32 swap_type, length, decoded_length, crc;
	swapz_u8 sha256[32];
	swapz_u8 representation, codec, version, dictionary;
};
enum swapz_ticket_state {
	SWAPZ_TICKET_FREE, SWAPZ_TICKET_RESERVED, SWAPZ_TICKET_COPYING,
	SWAPZ_TICKET_SEALED, SWAPZ_TICKET_CLAIMED, SWAPZ_TICKET_REVOKED
};
/* Private state exposed only for caller allocation and test fault injection. */
struct swapz_ticket_slot {
	struct swapz_ticket_key key;
	swapz_u64 generation;
	swapz_u32 refs;
	enum swapz_ticket_state state;
	bool sealed;
};
struct swapz_ticket_broker {
#ifdef __KERNEL__
	spinlock_t lock;
#else
	pthread_mutex_t lock;
#endif
	struct swapz_ticket_slot *slots;
	swapz_u8 *payload;
	swapz_u32 *free_indices;
	size_t stride, payload_bytes, metadata_bytes, index_bytes;
	swapz_u64 session, epoch, next_generation, byte_limit, used_bytes;
	swapz_u32 capacity, free_count, max_length;
	bool closing, initialized;
};
/* Move-only lease by caller contract; each variable has one thread owner.
 * Retain creates a new lease, put consumes it. Never manufacture a ref by
 * copying a lease. Broker and arrays outlive all API calls and refs. */
struct swapz_ticket_ref {
	struct swapz_ticket_broker *broker;
	swapz_u64 session, generation;
	swapz_u32 index;
};
struct swapz_ticket_view {
	const swapz_u8 *bytes; /* valid only while holding caller's lease */
	struct swapz_ticket_key key;
};
struct swapz_ticket_usage {
	size_t stride, payload_bytes, metadata_bytes, index_bytes, total_bytes;
	swapz_u64 reserved_bytes;
	swapz_u32 live_slots;
};
/* Zero broker at init. Exact aligned disjoint arrays, nonreused session.
 * No allocations. Reserve/claim try once; other calls serialize by lock.
 * No calls under foreign locks; no callback or credit wait. Source must be
 * stable until seal returns, copied outside lock with exclusive lease.
 * Failed seal/cancel stays charged until put. Close never waits for refs.
 * Destroy requires external quiescence of ALL entrants, not just no refs.
 * Kernel adapter unqualified; normal Kbuild does not link this component. */
int swapz_ticket_init(struct swapz_ticket_broker *broker,
	struct swapz_ticket_slot *slots, size_t metadata_bytes,
	swapz_u8 *payload, size_t payload_bytes, swapz_u32 *free_indices,
	size_t index_bytes, swapz_u32 count, swapz_u32 max_length,
	swapz_u64 byte_limit, swapz_u64 session, swapz_u64 epoch);
int swapz_ticket_reserve(struct swapz_ticket_broker *, const struct swapz_ticket_key *, struct swapz_ticket_ref *);
int swapz_ticket_seal(struct swapz_ticket_ref *, const swapz_u8 *, swapz_u32);
int swapz_ticket_retain(const struct swapz_ticket_ref *, struct swapz_ticket_ref *);
int swapz_ticket_claim(const struct swapz_ticket_ref *, const struct swapz_ticket_key *);
int swapz_ticket_view(const struct swapz_ticket_ref *, struct swapz_ticket_view *);
int swapz_ticket_cancel(const struct swapz_ticket_ref *);
int swapz_ticket_put(struct swapz_ticket_ref *);
int swapz_ticket_revoke(struct swapz_ticket_broker *, swapz_u64);
int swapz_ticket_close(struct swapz_ticket_broker *);
int swapz_ticket_destroy(struct swapz_ticket_broker *);
int swapz_ticket_usage(struct swapz_ticket_broker *, struct swapz_ticket_usage *);
#endif
#endif
