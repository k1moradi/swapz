/* SPDX-License-Identifier: GPL-2.0-only */
/* Explicit host-only substitutes for the extracted frozen R105 transition
 * functions. Real recorder, byte bridge and owner are linked separately.
 * Lower/storage/retirement success here is modeled, never native proof.
 */
#ifndef SWAPZ_R106_PRODUCER_MODEL_H
#define SWAPZ_R106_PRODUCER_MODEL_H
#include <errno.h>
#define SWAPZ_SCOPED_TARGET_OBSERVATION 1
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_ROUND094_GENERATION_PAGES 16U
#define __maybe_unused __attribute__((unused))
#define lockdep_assert_held(lock) ((void)(lock))
#define REQ_OP_WRITE 1
typedef u32 swapz_u32;
typedef u8 swapz_u8;
struct swapz_ticket_key {
	u64 logical_page, slot_offset, area_epoch, store_sequence, dm_generation;
	u32 swap_type, length, decoded_length, codec, representation, version, dictionary;
	u8 sha256[32];
};
struct swapz_bio_ref {
	u64 observation_operation, observation_original, observation_clone;
	u64 observation_descriptor, observation_extent;
	struct { struct swapz_ticket_key key; } original_view;
	u8 observation_compressed_sha256[32];
	bool original_claimed, observation_fallback, observation_claim_lower_failed;
};
struct swapz_dm;
struct modeled_storage {
	struct swapz_dm *ctx;
	struct { u32 start_block; } transaction;
	bool pending_decoder;
};
struct swapz_dm {
	struct modeled_storage *original_storage;
	struct swapz_bio_ref *observation_commit;
	struct {
		u64 abandoned_blocks;
		u32 physical_blocks;
		bool in_flight;
		u8 live_records[16], extent_classes[16];
	} authority;
	struct { u32 generation; } maps[16];
	struct { u64 extent, gc_epoch; u32 generation; u8 compressed_sha256[32]; }
		observation_extent_by_page[16];
	u64 logical_pages, observation_read_operation, observation_read_extent;
	u32 observation_read_block, observation_read_length;
	bool observation_read_seen, prepublication_fua;
	u8 observation_read_sha256[32];
};
struct swapz_authority_import_spec { u64 gc_epoch; };
struct swapz_original_extent_input { u32 unused; };
struct swapz_round091_claim_context { struct swapz_dm *ctx; struct swapz_bio_ref *entry; };
static int lower_error, flush_error, reserve_error, claim_error;
static u8 modeled_payload[SWAPZ_BLOCK_BYTES];
static int swapz_lower(void *opaque, int op, u32 block, u8 blocks, u8 *bytes)
{
	assert(opaque && op == REQ_OP_WRITE && block == 1 && (blocks == 1 || blocks == 2) && bytes);
	return lower_error;
}
static int swapz_lower_read(void *opaque, u32 block, u8 blocks, u8 *bytes)
{
	assert(opaque && block == 1 && blocks == 1);
	memcpy(bytes, modeled_payload, sizeof(modeled_payload));
	return lower_error;
}
static int swapz_issue_flush(void *opaque)
{
	assert(opaque);
	return flush_error;
}
static int swapz_write_flush_before_publish(int error, bool fua,
					    int (*flush)(void *), void *opaque)
{
	return error || !fua ? error : flush(opaque);
}
static int swapz_shared_storage_reserve(struct modeled_storage *storage,
		const struct swapz_authority_import_spec *spec,
		const struct swapz_original_extent_input *input, u32 *credit)
{
	assert(storage && spec && input);
	if (reserve_error)
		return reserve_error;
	*credit = 1;
	storage->ctx->authority.in_flight = true;
	return 0;
}
static int swapz_shared_storage_cancel_reserved(struct modeled_storage *storage, u32 credit)
{
	assert(credit == 1 && storage->ctx->authority.in_flight);
	storage->ctx->authority.in_flight = false;
	return 0;
}
static int swapz_round091_claim_reserved(void *opaque, u32 credit);
static int swapz_shared_storage_commit_reserved(struct modeled_storage *storage, u32 credit);

struct file { int unused; };
struct swapz_trial_retained_scope { u64 identity, session, epoch, target_epoch; };
static DEFINE_MUTEX(swapz_controller_lock);
static bool swapz_controller_external_joined, swapz_controller_mm_revoked;
static struct file *swapz_controller_mapper;
static unsigned int controller_puts;
static int controller_error;
static bool swapz_controller_matches_locked(const struct swapz_trial_retained_scope *scope)
{
	return scope && scope->identity == 77 && scope->session == 11 &&
	       scope->epoch == 12 && scope->target_epoch == 13;
}
static int swapz_mm_broker_owner_retired(u64 session, u64 epoch)
{
	return session == 11 && epoch == 12 ? 0 : -ESTALE;
}
static void swapz_controller_record_error(int error) { controller_error = error; }
static void fput(struct file *file) { assert(file); ++controller_puts; }

#include "round106-producer-shapes.h"

static int swapz_round091_claim_reserved(void *opaque, u32 credit)
{
	struct swapz_round091_claim_context *claim = opaque;
	assert(credit == 1);
	if (claim_error)
		return claim_error;
	claim->entry->original_claimed = true;
	swapz_scope_observe_credit(claim->entry, SWAPZ_OBS_CLAIM, credit);
	return 0;
}
static int swapz_shared_storage_commit_reserved(struct modeled_storage *storage, u32 credit)
{
	u32 completed;
	struct swapz_dm *ctx = storage->ctx;
	assert(credit == 1 && ctx->authority.in_flight);
	int error = swapz_round090_storage_write(ctx, 1, modeled_payload,
					       sizeof(modeled_payload), &completed);
	if (!error) {
		assert(completed == sizeof(modeled_payload));
		error = swapz_round090_storage_flush(ctx);
	}
	ctx->authority.in_flight = false;
	if (error)
		++ctx->authority.abandoned_blocks;
	return error;
}
#endif
