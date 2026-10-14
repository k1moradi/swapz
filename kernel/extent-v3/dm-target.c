// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz3 - EXPERIMENTAL V3.0-alpha volatile Device Mapper swap target.
 *
 * First runtime integration of actual V3 4/8/16KiB extents. Uses 4KiB logical
 * pages, LZ4, bounded size-aware write windows and synchronous dm-io through
 * one WQ_MEM_RECLAIM worker. No in-place compatibility with dm-swapz V2.2.
 *
 * IMPORTANT ALPHA LIMIT: GC is experimentally live with rotating reserved
 * segments, but it remains null_blk-only until independently qualified.
 * On ENOSPC or failed lower I/O, fail closed; never use as system swap.
 */
#define DM_MSG_PREFIX "swapz3"
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/device-mapper.h>
#include <linux/dm-io.h>
#include <linux/highmem.h>
#include <linux/ioprio.h>
#include <linux/ktime.h>
#include <linux/lz4.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/sched.h>
#include <linux/vmalloc.h>
#include <linux/workqueue.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include "engine.h"
#include "gc-cost.h"
#include "flush-qual.h"

#if PAGE_SIZE != SV3_BLOCK_BYTES
#error "swapz3 V3.0-alpha requires 4KiB PAGE_SIZE"
#endif
#define SV3_SECTORS (SV3_BLOCK_BYTES >> SECTOR_SHIFT)
#define SV3_BATCH_BYTES (SV3_MAX_RECORDS * SV3_BLOCK_BYTES)
#define SV3_ALPHA_VERSION "3.0.0-alpha.10"
#define SV3_WORK_QUANTUM_BIOS 64U
#define SV3_MAX_COALESCE_MS 4U

struct sv3_bio_ref {
	struct list_head list;
	struct bio *bio;
};

struct sv3_pending_bio {
	struct bio *bio;
	sv3_u32 logical;
	sv3_u16 length;
	/* True only for the full 4KiB incompressible fallback. */
	sv3_u8 raw;
};

/* The worker attributes exactly one primary reason to each real window.
 * Historical alpha.8 read bypass is intentionally NOT re-enabled. */
enum sv3_window_close_reason {
	SV3_CLOSE_UNKNOWN,
	SV3_CLOSE_FULL,
	SV3_CLOSE_DUPLICATE,
	SV3_CLOSE_ZERO,
	SV3_CLOSE_FUA,
	SV3_CLOSE_RAW,
	SV3_CLOSE_READ_CONFLICT,
	SV3_CLOSE_READ_UNRELATED,
	SV3_CLOSE_DISCARD,
	SV3_CLOSE_PREFLUSH,
	SV3_CLOSE_QUANTUM,
	SV3_CLOSE_IDLE,
	SV3_CLOSE_SHUTDOWN,
	SV3_CLOSE_OTHER,
	SV3_CLOSE_REASON_COUNT,
};

struct sv3_dm {
	struct dm_target *target;
	struct dm_dev *backing;
	struct dm_io_client *io_client;
	struct workqueue_struct *workqueue;
	struct delayed_work worker;
	spinlock_t queue_lock;
	struct list_head incoming;
	bool accepting;
	bool failed;
	int last_error;

	struct sv3_authority authority;
	struct sv3_engine engine;
	struct sv3_map *maps;
	sv3_u16 *live_records;
	sv3_u8 *extent_classes;
	/* Per-discard epoch/delta scratch validates shared-extent liveness
	 * before any mapping or generation is mutated. */
	sv3_u32 *discard_epoch;
	sv3_u16 *discard_count;
	sv3_u32 discard_serial;
	sv3_u32 physical_blocks;
	sv3_u32 logical_pages;

	/* Serialized, entirely preallocated normal reclaim path. */
	struct sv3_pending_bio batch[SV3_MAX_RECORDS];
	struct sv3_compressed_page planned[SV3_MAX_RECORDS];
	sv3_u8 planned_to_batch[SV3_MAX_RECORDS];
	sv3_u8 used[SV3_MAX_RECORDS];
	/* Separate GC metadata and compressed record storage. Foreground upper
	 * BIO descriptors/data stay immutable throughout an emergency cleaning. */
	struct sv3_pending_bio gc_pending[SV3_MAX_RECORDS];
	struct sv3_compressed_page gc_planned[SV3_MAX_RECORDS];
	sv3_u8 gc_to_pending[SV3_MAX_RECORDS];
	sv3_u8 gc_used[SV3_MAX_RECORDS];
	sv3_u8 gc_count;
	u8 *gc_bytes_store;
	sv3_u32 *gc_scores;  /* authoritative payload+descriptor bytes */
	sv3_u32 *gc_io_scores; /* conservative read+write cost per victim */
	sv3_u16 *gc_live_counts; /* count for ties/control comparison */
	sv3_u16 *gc_min_live_blocks; /* proven per-survivor block bound */
	sv3_u8 *segment_roles; /* 1=foreground, 0=free GC reserve */
	sv3_u32 segment_count;
	sv3_u8 gc_cost_policy; /* 0=record count; 1=payload bytes; 2=I/O */
	u64 gc_selected_io_cost;
	u64 gc_no_headroom_skips;
	u64 gc_selected_live_bytes;
	u64 gc_selected_live_records;
	u64 gc_victims;
	u64 gc_role_rotations;
	sv3_u32 last_gc_victim;
	sv3_u32 last_gc_destination;
	u64 gc_pages;
	u64 gc_read_bytes;
	u64 gc_write_bytes;
	u64 gc_read_reqs;
	u64 gc_write_reqs;
	sv3_u8 batch_count;
	sv3_u8 max_window;
	/* Admission coalescing is optional and bounded by one timer expiry.
	 * No write is published/ACKed until its actual lower I/O completes. */
	sv3_u8 coalesce_ms;
	u64 coalesce_deferred;
	u64 coalesce_urgent;
	u64 window_records_total;
	/* Worker-owned telemetry only; status is a diagnostic snapshot. */
	enum sv3_window_close_reason next_window_close;
	u64 window_close_reasons[SV3_CLOSE_REASON_COUNT];
	u64 window_gc_pressure;
	/* First accepted record -> flush entry, excluding physical I/O. */
	u64 window_first_ns;
	u64 window_age_sum_ns;
	u64 window_age_max_ns;
	u64 window_age_le_100us;
	u64 window_age_101_1000us;
	u64 window_age_gt_1000us;
	u64 window_size_counts[SV3_MAX_RECORDS + 1];
	u64 window_bins[6]; /* 1,2,3-4,5-8,9-16,17-64 */
	u8 *batch_bytes;       /* VMALLOC: 64 * 4KiB output slots */
	u8 *input_page;        /* VMALLOC: 4KiB copy from upper bio */
	u8 *read_page;         /* VMALLOC: 4KiB decompressed upper bio */
	u8 *read_compressed;   /* VMALLOC: 4KiB compressed record buffer */
	void *lz4_workmem;
	u64 logical_write_bytes;
	u64 logical_read_bytes;
	u64 physical_write_bytes;
	u64 physical_write_reqs;
	u64 physical_read_bytes;
	u64 physical_read_reqs;
	/* Submitted I/O, including failed/torn lower requests. These counters
	 * are NOT completed or proven-media bytes; never mix the two. */
	u64 lower_write_submitted_bytes;
	u64 lower_write_submitted_reqs;
	/* Null_blk-only, pre-submission lower WRITE fault injection. It tests
	 * upper error propagation, NOT partially completed device writes. */
	u32 write_fault_nth;
	u64 write_fault_calls;
	u64 write_fault_injected;
	u64 lower_read_submitted_bytes;
	u64 lower_read_submitted_reqs;
	struct sv3_flush_meter flush_meter;
	u64 worker_requeues;
	u64 one_page_windows;
	u64 compressed_pages;
	u64 raw_pages;
	/* Successfully acknowledged all-zero logical writes needing no data I/O. */
	u64 zero_elided_pages;
	/*
	 * Attempt-side histogram, NOT acknowledged logical writes or media
	 * occupancy. Only user-supplied foreground 4KiB WRITE pages enter
	 * this histogram; GC copies, verification and synthetic readback do
	 * not. Samples can include later failed / aborted windows.
	 * Index 0..4: successful LZ4 <=256/1024/2048/3072/3568 bytes;
	 * index 5: LZ4 did not fit SV3_MAX_COMPRESSED -> raw fallback.
	 */
	u64 lz4_attempts;
	u64 lz4_accepted_bytes;
	u64 lz4_size_bins[6];
	u64 discard_pages;
	u64 windows;
	u64 reordered_records;
	u64 io_failures;
};

static void sv3_complete(struct bio *bio, int error)
{
	if (error)
		bio->bi_status = errno_to_blk_status(error);
	bio_endio(bio);
}

static void sv3_fail(struct sv3_dm *ctx, int error)
{
	if (!ctx->failed) {
		ctx->failed = true;
		ctx->last_error = error < 0 ? error : -EIO;
		ctx->io_failures++;
		DMERR("V3 alpha: lower or mapping error %d; rejecting subsequent I/O",
		      ctx->last_error);
	}
}

/*
 * This adapter reports completed blocks only after SYNCHRONOUS dm_io returns
 * successfully with an empty error bitmap.  No assumed partial completions.
 * On an error, the entire reserved extent is quarantined by the V3 authority.
 * Scratch is vmalloc-backed: DM_IO_VMA, never DM_IO_KMEM.
 */
static int sv3_lower(struct sv3_dm *ctx, enum req_op op, sv3_u32 block,
		     sv3_u16 blocks, u8 *bytes)
{
	struct dm_io_region region;
	struct dm_io_request req = {
		.bi_opf = op | REQ_SWAP | (op == REQ_OP_READ ? REQ_SYNC : 0),
		.mem = {
			.type = DM_IO_VMA,
			.offset = 0,
			.ptr.vma = bytes,
		},
		.notify = { .fn = NULL, .context = NULL },
		.client = ctx->io_client,
	};
	unsigned long bitmap = 0;
	int error;

	if (!blocks || block >= ctx->physical_blocks ||
	    blocks > ctx->physical_blocks - block)
		return -ERANGE;
	region.bdev = ctx->backing->bdev;
	region.sector = (sector_t)block * SV3_SECTORS;
	region.count = (sector_t)blocks * SV3_SECTORS;
	/* Inject at the common physical WRITE boundary, including foreground
	 * mixed runs, serialized controls and GC relocation. Never count this
	 * synthetic rejection as submitted/completed lower-device I/O. */
	if (op == REQ_OP_WRITE && ctx->write_fault_nth &&
	    ++ctx->write_fault_calls == ctx->write_fault_nth) {
		ctx->write_fault_injected++;
		return -EIO;
	}
	if (op == REQ_OP_READ) {
		ctx->lower_read_submitted_bytes +=
			(u64)blocks * SV3_BLOCK_BYTES;
		ctx->lower_read_submitted_reqs++;
	} else {
		ctx->lower_write_submitted_bytes +=
			(u64)blocks * SV3_BLOCK_BYTES;
		ctx->lower_write_submitted_reqs++;
	}
	error = dm_io(&req, 1, &region, &bitmap, IOPRIO_DEFAULT);
	if (error || bitmap)
		return error ? error : -EIO;
	if (op == REQ_OP_READ) {
		ctx->physical_read_bytes += (u64)blocks * SV3_BLOCK_BYTES;
		ctx->physical_read_reqs++;
	} else {
		ctx->physical_write_bytes += (u64)blocks * SV3_BLOCK_BYTES;
		ctx->physical_write_reqs++;
	}
	return 0;
}

/*
 * Linux does not accept REQ_OP_FLUSH as an upper bio opcode; a valid
 * empty upper flush is a zero-sector REQ_OP_WRITE|REQ_PREFLUSH.
 * blkdev_issue_flush() submits that protocol itself and may complete
 * without an actual hardware command if the lower queue has no volatile
 * write-back cache. Every actual invocation is accounted separately from
 * physical read/write traffic. A controlled, *pre-submission* failure is
 * supported only for owned null_blk alpha qualification.
 */
static int sv3_kernel_lower_flush(void *opaque)
{
	struct sv3_dm *ctx = opaque;

	return blkdev_issue_flush(ctx->backing->bdev);
}

static int sv3_issue_flush(struct sv3_dm *ctx)
{
	int error = sv3_flush_accounted(&ctx->flush_meter,
				      sv3_kernel_lower_flush, ctx);

	if (error)
		sv3_fail(ctx, error);
	return error;
}

static int sv3_lower_write(void *opaque, sv3_u32 block, sv3_u8 blocks,
			   const sv3_u8 *bytes, sv3_u8 *completed)
{
	struct sv3_dm *ctx = opaque;
	int error;

	*completed = 0;
	error = sv3_lower(ctx, REQ_OP_WRITE, block, blocks, (u8 *)bytes);
	if (!error)
		*completed = blocks;
	return error;
}

/*
 * A single synchronous dm_io submission covers many adjacent, individually
 * valid SWZ3 extents. The portable engine does NOT publish their logical
 * maps until this WHOLE lower submission has completed successfully.
 * dm_io request count is NOT guaranteed to equal block-queue request
 * count after bio splitting/merging; independent null_blk stat is needed.
 */
static int sv3_lower_write_run(void *opaque, sv3_u32 block,
			      sv3_u16 blocks, const sv3_u8 *bytes,
			      sv3_u16 *completed)
{
	struct sv3_dm *ctx = opaque;
	int error;

	*completed = 0;
	if (!blocks || blocks > SV3_BULK_BLOCKS)
		return -ERANGE;
	error = sv3_lower(ctx, REQ_OP_WRITE, block, blocks, (u8 *)bytes);
	if (!error)
		*completed = blocks;
	return error;
}

static int sv3_lower_read(void *opaque, sv3_u32 block, sv3_u8 blocks,
			  sv3_u8 *destination)
{
	return sv3_lower(opaque, REQ_OP_READ, block, blocks, destination);
}

/*
 * Optional diagnostic verification for raw pages, matching the compressed
 * engine's verify-after-write behavior. The raw page has no spare on-media
 * bytes for CRC, so compare a fresh complete lower read to the original
 * data BEFORE sv3_finish_raw publishes mapping authority. This is not an
 * fsync/power-loss guarantee. Disabled in the default performance policy.
 */
static int sv3_verify_raw_write(struct sv3_dm *ctx, sv3_u32 block,
				const u8 *original)
{
	int error;

	if (!ctx->engine.verify_after_write)
		return 0;
	if (!original || ctx->read_page == original)
		return -EINVAL;
	error = sv3_lower_read(ctx, block, 1, ctx->read_page);
	if (error)
		return error;
	ctx->engine.write_verify_read_blocks++;
	return memcmp(ctx->read_page, original, SV3_BLOCK_BYTES) ?
		-EBADMSG : 0;
}

static int sv3_copy_bio(struct bio *bio, void *buffer, bool to_bio)
{
	struct bio_vec vec;
	struct bvec_iter iter;
	size_t offset = 0;

	bio_for_each_segment(vec, bio, iter) {
		void *mapped;

		if (vec.bv_len > SV3_BLOCK_BYTES - offset)
			return -EINVAL;
		mapped = kmap_local_page(vec.bv_page);
		if (to_bio)
			memcpy((u8 *)mapped + vec.bv_offset,
			       (u8 *)buffer + offset, vec.bv_len);
		else
			memcpy((u8 *)buffer + offset,
			       (u8 *)mapped + vec.bv_offset, vec.bv_len);
		kunmap_local(mapped);
		offset += vec.bv_len;
	}
	return offset == SV3_BLOCK_BYTES ? 0 : -EINVAL;
}

/*
 * Sort already-accepted, distinct-slot pages into size-complementary pairs.
 * The greedy largest-plus-best-fitting partner is intentionally bounded by
 * 64 records and stable for equal-size/tie cases. The extent engine then
 * optimizes 4/8/16KiB contiguous physical geometry over this order.
 *
 * NEVER reorder across flush/FUA, discard, reads or duplicate logical slots.
 */
static void sv3_order_window(struct sv3_dm *ctx)
{
	sv3_u8 position = 0;

	memset(ctx->used, 0, sizeof(ctx->used));
	while (position < ctx->batch_count) {
		int largest = -1, partner = -1;
		int best_slack = INT_MAX;
		sv3_u8 i;

		for (i = 0; i < ctx->batch_count; ++i)
			if (!ctx->used[i] && !ctx->batch[i].raw &&
			    (largest < 0 ||
			     ctx->batch[i].length > ctx->batch[largest].length))
				largest = i;
		/* All raw pages go after the compressed DP-planned prefix so
		 * they can share one physically contiguous, deferred lower run. */
		if (largest < 0)
			break;
		ctx->used[largest] = 1;
		ctx->planned_to_batch[position++] = (u8)largest;

		/* V3 metadata: header(16) + two descriptors(32). */
		for (i = 0; i < ctx->batch_count; ++i) {
			int remaining;

			if (ctx->used[i] || ctx->batch[i].raw)
				continue;
			remaining = SV3_BLOCK_BYTES - 48 -
				ctx->batch[largest].length - ctx->batch[i].length;
			if (remaining >= 0 && remaining < best_slack) {
				best_slack = remaining;
				partner = i;
			}
		}
		if (partner >= 0) {
			ctx->used[partner] = 1;
			ctx->planned_to_batch[position++] = (u8)partner;
		}
	}
	/* The unsorted tail contains raw pages in their original order. */
	{
		sv3_u8 index;

		for (index = 0; index < ctx->batch_count; ++index)
			if (!ctx->used[index])
				ctx->planned_to_batch[position++] = index;
	}
	for (position = 0; position < ctx->batch_count; ++position) {
		sv3_u8 index = ctx->planned_to_batch[position];

		if (index != position)
			ctx->reordered_records++;
		ctx->planned[position] = (struct sv3_compressed_page) {
			.logical_page = ctx->batch[index].logical,
			.payload = ctx->batch_bytes + (size_t)index * SV3_BLOCK_BYTES,
			.length = ctx->batch[index].length,
			.raw = ctx->batch[index].raw,
		};
	}
}

/*
 * Size-classed live relocation. The victim is NEVER erased by this function.
 * Instead, every live logical map is re-encoded into a new, fully completed
 * physical extent (or raw block), then old per-extent liveness is decremented.
 * Only after a final mapping+refcount scan proves the victim wholly dead may
 * the normal allocator reuse it. All callbacks are synchronous, under one
 * serialized worker; NO recursive GC calls can occur.
 */
static void sv3_gc_sort(struct sv3_dm *ctx)
{
	sv3_u8 position = 0, i;

	memset(ctx->gc_used, 0, sizeof(ctx->gc_used));
	while (position < ctx->gc_count) {
		int largest = -1, partner = -1, slack_best = INT_MAX;

		for (i = 0; i < ctx->gc_count; ++i)
			if (!ctx->gc_used[i] &&
			    (largest < 0 || ctx->gc_pending[i].length >
			     ctx->gc_pending[largest].length))
				largest = i;
		ctx->gc_used[largest] = 1;
		ctx->gc_to_pending[position++] = largest;
		for (i = 0; i < ctx->gc_count; ++i) {
			int slack;

			if (ctx->gc_used[i])
				continue;
			slack = SV3_BLOCK_BYTES - 48 -
				ctx->gc_pending[largest].length -
				ctx->gc_pending[i].length;
			if (slack >= 0 && slack < slack_best) {
				slack_best = slack;
				partner = i;
			}
		}
		if (partner >= 0) {
			ctx->gc_used[partner] = 1;
			ctx->gc_to_pending[position++] = partner;
		}
	}
	for (position = 0; position < ctx->gc_count; ++position) {
		sv3_u8 index = ctx->gc_to_pending[position];

		ctx->gc_planned[position] = (struct sv3_compressed_page) {
			.logical_page = ctx->gc_pending[index].logical,
			.payload = ctx->gc_bytes_store +
				(size_t)index * SV3_BLOCK_BYTES,
			.length = ctx->gc_pending[index].length,
		};
	}
}

static int sv3_gc_flush(struct sv3_dm *ctx)
{
	sv3_u8 completed = 0;
	int error;

	if (!ctx->gc_count)
		return 0;
	sv3_gc_sort(ctx);
	error = sv3_engine_write_window_batched(&ctx->engine, ctx->gc_planned,
					 ctx->gc_count, &completed);
	ctx->gc_pages += completed;
	ctx->gc_count = 0;
	return error;
}

static int sv3_gc_move_raw(struct sv3_dm *ctx, sv3_u32 logical,
			   const struct sv3_map *old)
{
	struct sv3_tx tx;
	sv3_u8 completed = 0;
	int error;

	if (old->extent_blocks != 1 || old->start_block >= ctx->physical_blocks)
		return -EUCLEAN;
	error = sv3_lower_read(ctx, old->start_block, 1, ctx->input_page);
	if (error)
		return error;
	/* Never propagate a corrupted raw page into a new GC location. */
	error = sv3_verify_raw(&ctx->authority, logical, ctx->input_page);
	if (error)
		return error;
	error = sv3_stage(&ctx->authority, &logical, 1, 1, &tx);
	if (error)
		return error;
	error = sv3_lower_write(ctx, tx.start_block, 1,
				ctx->input_page, &completed);
	if (!error && completed == 1)
		error = sv3_verify_raw_write(ctx, tx.start_block,
					   ctx->input_page);
	error = sv3_finish_raw(&ctx->authority, &tx, ctx->input_page, completed, error);
	if (!error)
		ctx->gc_pages++;
	return error;
}

/*
 * Evaluate actual authoritative compressed-body BYTES + descriptor cost,
 * rather than treating a live 200-byte record like a live 4096-byte raw
 * page. This is a conservative cost estimate, not a prediction of the
 * optimizer's final physical extent count or actual read amplification.
 * It can be switched to the old count heuristic for matched benchmarks.
 */
static int sv3_gc_choose_victim(struct sv3_dm *ctx, sv3_u32 *victim)
{
	sv3_u32 logical, segment, selected = ~(sv3_u32)0;
	sv3_u32 best = ~(sv3_u32)0;
	sv3_u16 best_count = ~(sv3_u16)0;

	memset(ctx->gc_scores, 0,
	       (size_t)ctx->segment_count * sizeof(*ctx->gc_scores));
	memset(ctx->gc_live_counts, 0,
	       (size_t)ctx->segment_count * sizeof(*ctx->gc_live_counts));
	memset(ctx->gc_io_scores, 0,
	       (size_t)ctx->segment_count * sizeof(*ctx->gc_io_scores));
	memset(ctx->gc_min_live_blocks, 0,
	       (size_t)ctx->segment_count *
			       sizeof(*ctx->gc_min_live_blocks));
	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		const struct sv3_map *m = &ctx->maps[logical];
		sv3_u32 cost, io_cost;

		if (!m->valid)
			continue;
		if (m->start_block >= ctx->physical_blocks)
			return -EUCLEAN;
		cost = sv3_gc_live_byte_cost(m);
		io_cost = sv3_gc_estimated_io_cost(m);
		if (!cost || !io_cost)
			return -EUCLEAN;
		segment = m->start_block / SV3_SEGMENT_BLOCKS;
		if (ctx->gc_scores[segment] > ~(sv3_u32)0 - cost ||
		    ctx->gc_io_scores[segment] > ~(sv3_u32)0 - io_cost ||
		    ctx->gc_live_counts[segment] == ~(sv3_u16)0)
			return -EOVERFLOW;
		ctx->gc_scores[segment] += cost;
		ctx->gc_io_scores[segment] += io_cost;
		ctx->gc_min_live_blocks[segment] +=
					sv3_gc_min_live_blocks(m);
		ctx->gc_live_counts[segment]++;
	}
	for (segment = 0; segment < ctx->segment_count; ++segment) {
		sv3_u16 count = ctx->gc_live_counts[segment];
		sv3_u32 score;

		/* GC must create *foreground usable* space. Evacuating a
		 * reserve segment only moves survivors between GC reserves
		 * and causes false progress followed by foreground ENOSPC. */
		if (!count || !ctx->segment_roles[segment] ||
		    segment == ctx->authority.open_segment)
			continue;
		/* Reject a provably non-reclaimable full victim BEFORE paying
		 * for up to 1MiB of GC reads/writes. Such an eviction could
		 * only fill its sole reserve destination and return ENOSPC. */
		if (!sv3_gc_candidate_can_free_block(ctx->gc_scores[segment],
					      ctx->gc_min_live_blocks[segment])) {
			ctx->gc_no_headroom_skips++;
			continue;
		}
		switch (ctx->gc_cost_policy) {
		case 0:
			score = count;
			break;
		case 1:
			score = ctx->gc_scores[segment];
			break;
		default:
			score = ctx->gc_io_scores[segment];
			break;
		}
		if (sv3_gc_prefer(score, count, best, best_count)) {
			best = score;
			best_count = count;
			selected = segment;
		}
	}
	if (selected == ~(sv3_u32)0)
		return -ENOSPC;
	*victim = selected;
	ctx->gc_selected_live_bytes += ctx->gc_scores[selected];
	ctx->gc_selected_live_records += ctx->gc_live_counts[selected];
	ctx->gc_selected_io_cost += ctx->gc_io_scores[selected];
	return 0;
}

static int sv3_gc_compact_one(struct sv3_dm *ctx)
{
	struct sv3_authority *a = &ctx->authority;
	sv3_u32 old_next, old_open, old_probe, victim, logical, block;
	u64 before_read, before_write;
	u64 before_read_reqs, before_write_reqs;
	int error;

	/*
	 * GC may only begin after every deferred contiguous lower WRITE has
	 * been completely replayed or aborted. An in-flight group has already
	 * reserved real physical blocks but has NOT published its authority;
	 * scanning its apparent zero-live segment here would risk recycling
	 * those reservations before lower completion.
	 */
	if (a->in_flight || a->batch_pending || a->batch_replaying ||
	    a->gc_allocation)
		return -EBUSY;
	error = sv3_gc_choose_victim(ctx, &victim);
	if (error)
		return error;
	old_next = a->next_block;
	old_open = a->open_segment;
	old_probe = a->next_segment_probe;
	before_read = ctx->physical_read_bytes;
	before_write = ctx->physical_write_bytes;
	before_read_reqs = ctx->physical_read_reqs;
	before_write_reqs = ctx->physical_write_reqs;
	/*
	 * Copying GC: choose exactly ONE wholly dead reserve segment. After
	 * successfully evacuating the foreground victim, exchange physical
	 * roles and keep the foreground cursor inside the newly compacted
	 * destination. This replenishes the reserve rather than gradually
	 * filling a fixed tail or cycling between two reserve segments.
	 */
	error = sv3_gc_begin_rotation(a, victim);
	if (error)
		goto out;
	ctx->gc_count = 0;

	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		struct sv3_map snapshot = ctx->maps[logical];
		sv3_u16 length;

		/* GC can scan a large volatile map while the worker owns it.
		 * Yield CPU periodically without permitting another mapping
		 * writer: the same worker remains the only authority owner. */
		if (!(logical & 63U))
			cond_resched();
		if (!snapshot.valid ||
		    snapshot.start_block / SV3_SEGMENT_BLOCKS != victim)
			continue;
		if (snapshot.raw) {
			error = sv3_gc_flush(ctx);
			if (error)
				goto out;
			error = sv3_gc_move_raw(ctx, logical, &snapshot);
			if (error)
				goto out;
			continue;
		}
		/* Existing media bytes remain authoritative until this page's
		 * full replacement is successfully committed by the V3 engine. */
		error = sv3_engine_read_page(&ctx->engine, logical,
						ctx->read_compressed,
						SV3_BLOCK_BYTES, &length);
		if (error)
			goto out;
		if (!length || length > SV3_MAX_COMPRESSED) {
			error = -EUCLEAN;
			goto out;
		}
		memcpy(ctx->gc_bytes_store +
		       (size_t)ctx->gc_count * SV3_BLOCK_BYTES,
		       ctx->read_compressed, length);
		ctx->gc_pending[ctx->gc_count++] =
			(struct sv3_pending_bio) {
				.bio = NULL,
				.logical = logical,
				.length = length,
			};
		if (ctx->gc_count == SV3_MAX_RECORDS) {
			error = sv3_gc_flush(ctx);
			if (error)
				goto out;
		}
	}
	error = sv3_gc_flush(ctx);
	if (error)
		goto out;

	/*
	 * Do not deem the victim reclaimable merely because GC wrote some
	 * replacements. Independently verify no live mapping and no physical
	 * liveness record remain in the original segment. If this test fails,
	 * return an error without recycling any physical bytes.
	 */
	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		const struct sv3_map *m = &ctx->maps[logical];

		if (m->valid &&
		    m->start_block / SV3_SEGMENT_BLOCKS == victim) {
			error = -EUCLEAN;
			goto out;
		}
	}
	for (block = victim * SV3_SEGMENT_BLOCKS;
	     block < (victim + 1) * SV3_SEGMENT_BLOCKS; ++block) {
		if (a->live_records[block]) {
			error = -EUCLEAN;
			goto out;
		}
	}
	/* Atomically exchange reserve/foreground ownership only after ALL
	 * authoritative mappings and live refcounts vacate the victim. */
	{
		sv3_u32 destination = a->gc_destination;

		error = sv3_gc_commit_rotation(a, victim);
		if (error)
			goto out;
		ctx->last_gc_victim = victim;
		ctx->last_gc_destination = destination;
		ctx->gc_role_rotations++;
	}
	ctx->gc_victims++;
out:
	ctx->gc_read_bytes += ctx->physical_read_bytes - before_read;
	ctx->gc_write_bytes += ctx->physical_write_bytes - before_write;
	ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs;
	ctx->gc_write_reqs += ctx->physical_write_reqs - before_write_reqs;
	ctx->gc_count = 0;
	if (error) {
		/* No role exchange on failure. All previous authoritative
		 * records remain intact; any committed partial relocation is
		 * still live in its reserved destination. Fail closed rather
		 * than treating that reserve as freely overwritable. */
		a->gc_allocation = 0;
		a->gc_forbidden_open = ~(sv3_u32)0;
		a->gc_forbidden_victim = ~(sv3_u32)0;
		a->gc_destination = ~(sv3_u32)0;
		a->next_block = old_next;
		a->open_segment = old_open;
		a->next_segment_probe = old_probe;
	}
	return error;
}


static void sv3_window_admit_clock(struct sv3_dm *ctx)
{
	/* Serialized worker: do not refresh the start for later records. */
	if (!ctx->batch_count)
		ctx->window_first_ns = ktime_get_ns();
}

static int sv3_flush_window(struct sv3_dm *ctx)
{
	sv3_u8 committed = 0, index, count = ctx->batch_count;
	sv3_u8 gc_attempts = 0;
	bool needs_fua = false;
	u64 end_ns, open_age_ns;
	int error = 0;

	if (!count) {
		ctx->next_window_close = SV3_CLOSE_UNKNOWN;
		ctx->window_first_ns = 0;
		return 0;
	}
	/* Measure BEFORE any dm_io, GC, verification or lower FUA. */
	end_ns = ktime_get_ns();
	open_age_ns = ctx->window_first_ns && end_ns >= ctx->window_first_ns ?
		end_ns - ctx->window_first_ns : 0;
	ctx->window_first_ns = 0;
	ctx->window_age_sum_ns += open_age_ns;
	if (open_age_ns > ctx->window_age_max_ns)
		ctx->window_age_max_ns = open_age_ns;
	if (open_age_ns <= 100000ULL)
		ctx->window_age_le_100us++;
	else if (open_age_ns <= 1000000ULL)
		ctx->window_age_101_1000us++;
	else
		ctx->window_age_gt_1000us++;
	ctx->window_close_reasons[ctx->next_window_close]++;
	ctx->next_window_close = SV3_CLOSE_UNKNOWN;
	sv3_order_window(ctx);
	for (index = 0; index < count; ++index)
		if (ctx->batch[index].bio->bi_opf & REQ_FUA)
			needs_fua = true;
	while (committed < count) {
		sv3_u8 succeeded = 0;

		error = sv3_engine_write_window_batched(&ctx->engine,
				ctx->planned + committed,
				count - committed, &succeeded);
		committed += succeeded;
		if (!error)
			continue;
		if (error == -ENOSPC)
			ctx->window_gc_pressure++;
		if (error == -ENOSPC && gc_attempts++ < 4) {
			/*
			 * The engine committed only the explicitly returned
			 * prefix. Keep pending BIOs and buffers intact while
			 * relocating one fully verified low-live segment.
			 * Retry ONLY the remaining logical records afterwards.
			 */
			error = sv3_gc_compact_one(ctx);
			if (!error)
				continue;
		}
		break;
	}
	/*
	 * Do not end any upper FUA BIO before the lower cache flush reports
	 * success. A failed post-write flush permanently fails this target:
	 * the newly published RAM mapping must not be trusted after -EIO.
	 */
	if (!error && committed == count && needs_fua)
		error = sv3_issue_flush(ctx);
	if (error && needs_fua)
		sv3_fail(ctx, error);
	for (index = 0; index < count; ++index) {
		struct bio *bio = ctx->batch[ctx->planned_to_batch[index]].bio;

		if (index < committed && !ctx->failed) {
			ctx->logical_write_bytes += SV3_BLOCK_BYTES;
			if (ctx->planned[index].raw)
				ctx->raw_pages++;
			else
				ctx->compressed_pages++;
			sv3_complete(bio, 0);
		} else {
			sv3_complete(bio, error ? error : -EIO);
		}
	}
	ctx->windows++;
	ctx->window_records_total += count;
	ctx->window_size_counts[count]++;
	if (count == 1)
		ctx->window_bins[0]++;
	else if (count == 2)
		ctx->window_bins[1]++;
	else if (count <= 4)
		ctx->window_bins[2]++;
	else if (count <= 8)
		ctx->window_bins[3]++;
	else if (count <= 16)
		ctx->window_bins[4]++;
	else
		ctx->window_bins[5]++;
	if (count == 1)
		ctx->one_page_windows++;
	ctx->batch_count = 0;
	if (error || committed != count) {
		sv3_fail(ctx, error ? error : -EIO);
		return error ? error : -EIO;
	}
	return 0;
}

static int sv3_raw_write(struct sv3_dm *ctx, struct bio *bio, sv3_u32 logical)
{
	struct sv3_tx tx;
	sv3_u8 completed = 0;
	int error;

	error = sv3_copy_bio(bio, ctx->input_page, false);
	if (error)
		return error;
	error = sv3_stage(&ctx->authority, &logical, 1, 1, &tx);
	if (error == -ENOSPC) {
		/* GC may use input_page, so recopy the still-owned upper BIO
		 * after victim relocation, before writing a raw replacement. */
		error = sv3_gc_compact_one(ctx);
		if (error)
			return error;
		error = sv3_copy_bio(bio, ctx->input_page, false);
		if (error)
			return error;
		error = sv3_stage(&ctx->authority, &logical, 1, 1, &tx);
	}
	if (error)
		return error;
	error = sv3_lower_write(ctx, tx.start_block, 1, ctx->input_page,
				&completed);
	if (!error && completed == 1)
		error = sv3_verify_raw_write(ctx, tx.start_block,
					   ctx->input_page);
	error = sv3_finish_raw(&ctx->authority, &tx, ctx->input_page, completed, error);
	if (!error) {
		ctx->raw_pages++;
		ctx->logical_write_bytes += SV3_BLOCK_BYTES;
	}
	return error;
}

static int sv3_accept_write(struct sv3_dm *ctx, struct bio *bio)
{
	sv3_u32 logical = (sv3_u32)(bio->bi_iter.bi_sector / SV3_SECTORS);
	sv3_u8 i;
	int length;
	int error;

	for (i = 0; i < ctx->batch_count; ++i)
		if (ctx->batch[i].logical == logical) {
			ctx->next_window_close = SV3_CLOSE_DUPLICATE;
			error = sv3_flush_window(ctx);
			if (error)
				return error;
			break;
		}
	if (ctx->batch_count == ctx->max_window) {
		ctx->next_window_close = SV3_CLOSE_FULL;
		error = sv3_flush_window(ctx);
		if (error)
			return error;
	}

	error = sv3_copy_bio(bio, ctx->input_page, false);
	if (error)
		return error;
	length = LZ4_compress_fast(ctx->input_page,
			ctx->batch_bytes +
				(size_t)ctx->batch_count * SV3_BLOCK_BYTES,
			SV3_BLOCK_BYTES, SV3_MAX_COMPRESSED, 1,
			ctx->lz4_workmem);
	/* Account for compressibility as the kernel itself observes it.
	 * A file extension or userspace fixture label is not the codec result;
	 * raw fallback is already selected when the configured output cap
	 * cannot be met. Do not interpret these attempt counters as committed
	 * pages, or infer the original anonymous/file-backed memory type. */
	ctx->lz4_attempts++;
	if (length <= 0)
		ctx->lz4_size_bins[5]++;
	else {
		ctx->lz4_accepted_bytes += length;
		if (length <= 256)
			ctx->lz4_size_bins[0]++;
		else if (length <= 1024)
			ctx->lz4_size_bins[1]++;
		else if (length <= 2048)
			ctx->lz4_size_bins[2]++;
		else if (length <= 3072)
			ctx->lz4_size_bins[3]++;
		else
			ctx->lz4_size_bins[4]++;
	}
	/*
	 * Zero is a first-class logical value: an invalid authoritative
	 * mapping already reads as an exact 4KiB zero page. Only inspect
	 * complete input for zero when LZ4 reported an exceptionally tiny
	 * payload; never mistake ordinary compressible data for zero.
	 *
	 * Any earlier accepted upper writes must be physically committed
	 * before invalidating this mapping. sv3_discard_page advances its
	 * generation and releases prior liveness without a lower WRITE.
	 * PREFLUSH was already honored in sv3_process(); FUA still requires
	 * the lower flush before this upper BIO completes.
	 */
	if (length > 0 && length <= 64 &&
	    sv3_page_is_zero(ctx->input_page)) {
		ctx->next_window_close = SV3_CLOSE_ZERO;
		error = sv3_flush_window(ctx);
		if (!error)
			error = sv3_discard_page(&ctx->authority, logical);
		if (!error && (bio->bi_opf & REQ_FUA))
			error = sv3_issue_flush(ctx);
		if (error) {
			sv3_fail(ctx, error);
		} else {
			ctx->logical_write_bytes += SV3_BLOCK_BYTES;
			ctx->zero_elided_pages++;
		}
		sv3_complete(bio, error);
		return 0;
	}
	if (length <= 0 && ctx->engine.bulk_enabled &&
	    !ctx->engine.verify_after_write) {
		/* Preserve the complete original 4KiB page in worker-owned
		 * staging. Admission and FUA ordering match compressed BIOs;
		 * CRC authority is published only after the shared lower write. */
		memcpy(ctx->batch_bytes +
		       (size_t)ctx->batch_count * SV3_BLOCK_BYTES,
		       ctx->input_page, SV3_BLOCK_BYTES);
		sv3_window_admit_clock(ctx);
		ctx->batch[ctx->batch_count++] = (struct sv3_pending_bio) {
			.bio = bio,
			.logical = logical,
			.length = SV3_BLOCK_BYTES,
			.raw = 1,
		};
		if (bio->bi_opf & REQ_FUA) {
			ctx->next_window_close = SV3_CLOSE_FUA;
			sv3_flush_window(ctx);
		}
		return 0;
	}
	if (length <= 0) {
		ctx->next_window_close = SV3_CLOSE_RAW;
		error = sv3_flush_window(ctx);
		if (error)
			return error;
		error = sv3_raw_write(ctx, bio, logical);
		if (!error && (bio->bi_opf & REQ_FUA))
			error = sv3_issue_flush(ctx);
		if (error)
			sv3_fail(ctx, error);
		sv3_complete(bio, error);
		return 0;
	}

	sv3_window_admit_clock(ctx);
	ctx->batch[ctx->batch_count] = (struct sv3_pending_bio) {
		.bio = bio,
		.logical = logical,
		.length = (sv3_u16)length,
	};
	ctx->batch_count++;
	/* FUA enforces an immediate drained window and is acknowledged only
	 * after sv3_flush_window() issues the matching lower cache flush. */
	if (bio->bi_opf & REQ_FUA) {
		ctx->next_window_close = SV3_CLOSE_FUA;
		sv3_flush_window(ctx);
	}
	return 0;
}

static int sv3_read(struct sv3_dm *ctx, struct bio *bio)
{
	sv3_u32 logical = (sv3_u32)(bio->bi_iter.bi_sector / SV3_SECTORS);
	const struct sv3_map *map = &ctx->maps[logical];
	sv3_u16 payload_bytes = 0;
	int error, decompressed;

	if (!map->valid) {
		memset(ctx->read_page, 0, SV3_BLOCK_BYTES);
	} else if (map->raw) {
		if (map->extent_blocks != 1 ||
		    map->start_block >= ctx->physical_blocks)
			return -EUCLEAN;
		error = sv3_lower_read(ctx, map->start_block, 1, ctx->read_page);
		if (error)
			return error;
		error = sv3_verify_raw(&ctx->authority, logical, ctx->read_page);
		if (error)
			return error;
	} else {
		error = sv3_engine_read_page(&ctx->engine, logical,
				ctx->read_compressed, SV3_BLOCK_BYTES,
				&payload_bytes);
		if (error)
			return error;
		decompressed = LZ4_decompress_safe(ctx->read_compressed,
						  ctx->read_page,
						  payload_bytes,
						  SV3_BLOCK_BYTES);
		if (decompressed != SV3_BLOCK_BYTES)
			return -EBADMSG;
	}
	error = sv3_copy_bio(bio, ctx->read_page, true);
	if (!error)
		ctx->logical_read_bytes += SV3_BLOCK_BYTES;
	return error;
}

static int sv3_discard(struct sv3_dm *ctx, struct bio *bio)
{
	sector_t sector = bio->bi_iter.bi_sector;
	sector_t remaining = bio_sectors(bio);
	int error;

	if (sector % SV3_SECTORS || remaining % SV3_SECTORS ||
	    sector / SV3_SECTORS >= ctx->logical_pages ||
	    remaining / SV3_SECTORS >
			ctx->logical_pages - sector / SV3_SECTORS)
		return -ERANGE;
	/*
	 * The discard must be all-or-nothing on any detectable mapping,
	 * generation or liveness corruption. Validate every affected logical
	 * page before changing even the first generation or refcount.
	 */
	{
		sector_t check_sector = sector;
		sector_t check_remaining = remaining;
		sv3_u32 epoch = ++ctx->discard_serial;

		if (!epoch) {
			memset(ctx->discard_epoch, 0,
			       (size_t)ctx->physical_blocks *
			       sizeof(*ctx->discard_epoch));
			epoch = ++ctx->discard_serial;
		}
		while (check_remaining) {
			sv3_u32 logical = (sv3_u32)(check_sector / SV3_SECTORS);
			const struct sv3_map *m = &ctx->maps[logical];

			if (m->generation == ~(sv3_u32)0)
				return -EOVERFLOW;
			if (m->valid) {
				sv3_u32 start = m->start_block;

				if (start >= ctx->physical_blocks ||
				    (m->extent_blocks != 1 &&
				     m->extent_blocks != 2 &&
				     m->extent_blocks != 4) ||
				    ctx->extent_classes[start] != m->extent_blocks ||
				    !ctx->live_records[start])
					return -EUCLEAN;
				if (ctx->discard_epoch[start] != epoch) {
					ctx->discard_epoch[start] = epoch;
					ctx->discard_count[start] = 0;
				}
				/*
				 * Every logical page in this DISCARD sharing the
				 * same physical extent consumes a separate live
				 * record. Check the aggregated count first.
				 */
				if (++ctx->discard_count[start] >
				    ctx->live_records[start])
					return -EUCLEAN;
			}
			check_sector += SV3_SECTORS;
			check_remaining -= SV3_SECTORS;
		}
	}
	while (remaining) {
		error = sv3_discard_page(&ctx->authority,
				       (sv3_u32)(sector / SV3_SECTORS));
		if (error)
			return error;
		ctx->discard_pages++;
		sector += SV3_SECTORS;
		remaining -= SV3_SECTORS;
	}
	return 0;
}

static void sv3_process(struct sv3_dm *ctx, struct bio *bio)
{
	int error = 0;
	const enum req_op op = bio_op(bio);

	if (ctx->failed) {
		sv3_complete(bio, ctx->last_error ? ctx->last_error : -EIO);
		return;
	}
	/* Classification only: unrelated READs still drain pending writes.
	 * This preserves all original FIFO, generation and flush ordering. */
	if (op != REQ_OP_WRITE || (bio->bi_opf & REQ_PREFLUSH)) {
		if (bio->bi_opf & REQ_PREFLUSH) {
			ctx->next_window_close = SV3_CLOSE_PREFLUSH;
		} else if (op == REQ_OP_READ) {
			sv3_u32 logical = (sv3_u32)(bio->bi_iter.bi_sector /
						      SV3_SECTORS);
			sv3_u8 index;

			ctx->next_window_close = SV3_CLOSE_READ_UNRELATED;
			for (index = 0; index < ctx->batch_count; ++index) {
				if (ctx->batch[index].logical == logical) {
					ctx->next_window_close = SV3_CLOSE_READ_CONFLICT;
					break;
				}
			}
		} else if (op == REQ_OP_DISCARD) {
			ctx->next_window_close = SV3_CLOSE_DISCARD;
		} else {
			ctx->next_window_close = SV3_CLOSE_OTHER;
		}
		error = sv3_flush_window(ctx);
		if (error) {
			sv3_complete(bio, error);
			return;
		}
	}
	if (bio->bi_opf & REQ_PREFLUSH) {
		error = sv3_issue_flush(ctx);
		if (error) {
			sv3_fail(ctx, error);
			sv3_complete(bio, error);
			return;
		}
		if (op == REQ_OP_WRITE && !bio_sectors(bio)) {
			sv3_complete(bio, 0);
			return;
		}
	}
	switch (op) {
	case REQ_OP_WRITE:
		/* A write BIO is completed by raw_write or flush_window. */
		error = sv3_accept_write(ctx, bio);
		if (error)
			sv3_complete(bio, error);
		return;
	case REQ_OP_READ:
		error = sv3_read(ctx, bio);
		break;
	case REQ_OP_DISCARD:
		error = sv3_discard(ctx, bio);
		break;
	default:
		error = -EOPNOTSUPP;
		break;
	}
	if (error && error != -EOPNOTSUPP)
		sv3_fail(ctx, error);
	sv3_complete(bio, error);
}

/*
 * Normal operation: a finite quantum keeps write ownership and CPU
 * latency bounded, with older queued BIOs ahead of new admissions.
 * Presuspend: admission is closed under queue_lock, so the same worker
 * may finish ALL previously accepted BIOs without building a potentially
 * unbounded chain of requeued delayed works during drain_workqueue().
 */
static void sv3_worker(struct work_struct *work)
{
	struct sv3_dm *ctx =
		container_of(to_delayed_work(work), struct sv3_dm, worker);
	LIST_HEAD(local);
	struct sv3_bio_ref *entry, *next;
	unsigned long flags;
	unsigned int remaining;

	for (;;) {
		remaining = SV3_WORK_QUANTUM_BIOS;
		spin_lock_irqsave(&ctx->queue_lock, flags);
		list_splice_init(&ctx->incoming, &local);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);

		list_for_each_entry_safe(entry, next, &local, list) {
			list_del_init(&entry->list);
			sv3_process(ctx, entry->bio);
			if (!(remaining & 7U))
				cond_resched();
			if (!--remaining)
				break;
		}
		/*
		 * Never carry a partially published upper write window
		 * across work items; a later read/FUA could overtake it.
		 */
		if (ctx->batch_count) {
			ctx->next_window_close = !READ_ONCE(ctx->accepting) ?
				SV3_CLOSE_SHUTDOWN : !remaining ?
				SV3_CLOSE_QUANTUM : SV3_CLOSE_IDLE;
			sv3_flush_window(ctx);
		}

		spin_lock_irqsave(&ctx->queue_lock, flags);
		if (!list_empty(&local))
			list_splice_init(&local, &ctx->incoming);
		if (list_empty(&ctx->incoming)) {
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			return;
		}
		if (ctx->accepting) {
			/*
			 * Preserves FIFO: unfinished older BIOs are already
			 * at the head, ahead of concurrently admitted BIOs.
			 */
			ctx->worker_requeues++;
			mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			return;
		}
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		/*
		 * Shutdown: no new admissions. Complete every previously
		 * accepted BIO in this invocation. Avoid requeue chains or
		 * leaving accepted BIOs behind flush_delayed_work().
		 */
		cond_resched();
	}
}

static int sv3_map(struct dm_target *ti, struct bio *bio)
{
	struct sv3_dm *ctx = ti->private;
	struct sv3_bio_ref *entry;
	unsigned long flags;
	sector_t sector = bio->bi_iter.bi_sector;
	sector_t count = bio_sectors(bio);

	if (!READ_ONCE(ctx->accepting))
		return DM_MAPIO_KILL;
	if (bio_op(bio) == REQ_OP_READ || bio_op(bio) == REQ_OP_WRITE) {
		if ((bio_op(bio) == REQ_OP_WRITE && !count &&
		     (bio->bi_opf & REQ_PREFLUSH))) {
			/* empty flush represented as PREFLUSH|WRITE */
		} else if (sector % SV3_SECTORS || count != SV3_SECTORS ||
			   sector / SV3_SECTORS >= ctx->logical_pages) {
			return DM_MAPIO_KILL;
		}
	} else if (bio_op(bio) == REQ_OP_DISCARD) {
		if (sector % SV3_SECTORS || count % SV3_SECTORS ||
		    sector / SV3_SECTORS >= ctx->logical_pages ||
		    count / SV3_SECTORS >
				ctx->logical_pages - sector / SV3_SECTORS)
			return DM_MAPIO_KILL;
	} else {
		/* A REQ_OP_FLUSH upper BIO is invalid on Linux: blk-core
		 * rejects it before dm's ->map. The real empty-flush
		 * protocol is WRITE|PREFLUSH with zero sectors. */
		return DM_MAPIO_KILL;
	}
	entry = dm_per_bio_data(bio, sizeof(*entry));
	INIT_LIST_HEAD(&entry->list);
	entry->bio = bio;
	spin_lock_irqsave(&ctx->queue_lock, flags);
	/*
	 * Admission and shutdown share queue_lock: presuspend cannot finish
	 * draining while a previously admitted BIO is added after the drain.
	 */
	if (!ctx->accepting) {
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		return DM_MAPIO_KILL;
	}
	list_add_tail(&entry->list, &ctx->incoming);
	/*
	 * First ordinary WRITE starts one finite coalescing interval; later
	 * writes join without extending the deadline. Urgent reads, discard,
	 * flush/FUA and preflush bypass that wait to preserve swap-in latency
	 * and ordering. Workqueue is serialized and completes every upper BIO.
	 * On already-running work, the next work item is queued normally.
	 */
	if (bio_op(bio) != REQ_OP_WRITE ||
	    (bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)) ||
	    !bio_sectors(bio)) {
		ctx->coalesce_urgent++;
		mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
	} else if (queue_delayed_work(ctx->workqueue, &ctx->worker,
				      msecs_to_jiffies(ctx->coalesce_ms))) {
		if (ctx->coalesce_ms)
			ctx->coalesce_deferred++;
	}
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	return DM_MAPIO_SUBMITTED;
}

static void sv3_drain(struct dm_target *ti)
{
	struct sv3_dm *ctx = ti->private;

	unsigned long flags;

	spin_lock_irqsave(&ctx->queue_lock, flags);
	WRITE_ONCE(ctx->accepting, false);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	/*
	 * flush_delayed_work() only waits for the last queued instance.
	 * This worker can chain itself after its 64-BIO quantum, so merely
	 * flushing that instance (or the workqueue once) is insufficient:
	 * presuspend must not return while a requeued accepted BIO exists.
	 *
	 * The admission lock is now closed. Force the pending timer to fire,
	 * wait for it, then drain *all chained* worker executions before
	 * releasing the target. drain_workqueue() explicitly allows chaining
	 * by work already executing on the draining queue.
	 */
	mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
	flush_delayed_work(&ctx->worker);
	drain_workqueue(ctx->workqueue);
	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!list_empty(&ctx->incoming) || ctx->batch_count ||
	    ctx->authority.batch_pending || ctx->authority.in_flight) {
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		DMERR("V3 drain invariant: accepted BIOs remain after draining");
		sv3_fail(ctx, -EUCLEAN);
	} else {
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
	}
	/* Every admitted BIO was queued under the same lock before this drain. */
	if (!ctx->failed) {
		int error = sv3_issue_flush(ctx);

		if (error)
			sv3_fail(ctx, error);
	}
}

static void sv3_resume(struct dm_target *ti)
{
	struct sv3_dm *ctx = ti->private;
	unsigned long flags;

	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!ctx->failed)
		WRITE_ONCE(ctx->accepting, true);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
}

static void sv3_free(struct sv3_dm *ctx)
{
	if (!ctx)
		return;
	if (ctx->workqueue) {
		/* The constructor-failure path has no accepted BIOs.
		 * The live teardown path already closed admission and drained
		 * every chained work item before arriving here. */
		cancel_delayed_work_sync(&ctx->worker);
		drain_workqueue(ctx->workqueue);
		destroy_workqueue(ctx->workqueue);
	}
	if (ctx->io_client)
		dm_io_client_destroy(ctx->io_client);
	if (ctx->backing)
		dm_put_device(ctx->target, ctx->backing);
	kvfree(ctx->maps);
	kvfree(ctx->live_records);
	kvfree(ctx->extent_classes);
	kvfree(ctx->discard_epoch);
	kvfree(ctx->discard_count);
	vfree(ctx->batch_bytes);
	vfree(ctx->gc_bytes_store);
	kvfree(ctx->gc_scores);
	kvfree(ctx->gc_io_scores);
	kvfree(ctx->gc_live_counts);
	kvfree(ctx->gc_min_live_blocks);
	kvfree(ctx->segment_roles);
	vfree(ctx->input_page);
	vfree(ctx->read_page);
	vfree(ctx->read_compressed);
	vfree(ctx->engine.write_scratch);
	vfree(ctx->engine.read_scratch);
	vfree(ctx->engine.bulk_scratch);
	kvfree(ctx->engine.bulk_txs);
	kfree(ctx->lz4_workmem);
	kfree(ctx);
}

static void sv3_dtr(struct dm_target *ti)
{
	struct sv3_dm *ctx = ti->private;

	if (!ctx)
		return;
	sv3_drain(ti);
	sv3_free(ctx);
	ti->private = NULL;
}

static int sv3_ctr(struct dm_target *ti, unsigned int argc, char **argv)
{
	struct sv3_dm *ctx;
	u64 logical, physical;
	u32 budget = 0, window = SV3_MAX_RECORDS, verify = 0;
	u32 gc_policy = 2, coalesce = 0, flush_fail_nth = 0;
	u32 lower_bulk = 1, write_fail_nth = 0;
	int error;

	if (argc < 1 || argc > 9 || ti->len % SV3_SECTORS) {
		ti->error = "Usage: <owned null_blk backing> [read_blocks 0..3] [window 1..64] [verify 0|1] [gc 0=count|1=bytes|2=io] [coalesce_ms 0..4] [test_fail_flush_nth 0..64] [lower_bulk 0=off|1=adjacent|2=allow-padding] [test_fail_write_nth 0..65535]";
		return -EINVAL;
	}
	if (argc > 1 && (kstrtou32(argv[1], 10, &budget) || budget > 3))
		return -EINVAL;
	if (argc > 2 && (kstrtou32(argv[2], 10, &window) ||
			 window < 1 || window > SV3_MAX_RECORDS))
		return -EINVAL;
	if (argc > 3 && (kstrtou32(argv[3], 10, &verify) || verify > 1U))
		return -EINVAL;
	if (argc > 4 && (kstrtou32(argv[4], 10, &gc_policy) ||
			 gc_policy > 2U))
		return -EINVAL;
	if (argc > 5 && (kstrtou32(argv[5], 10, &coalesce) ||
			 coalesce > SV3_MAX_COALESCE_MS))
		return -EINVAL;
	/* Fault injection is a diagnostic only, restricted by the same
	 * null_blk admission guard as all live V3 alpha IO. */
	if (argc > 6 && (kstrtou32(argv[6], 10, &flush_fail_nth) ||
			 flush_fail_nth > 64U))
		return -EINVAL;
	if (argc > 7 && (kstrtou32(argv[7], 10, &lower_bulk) ||
			 lower_bulk > 2U))
		return -EINVAL;
	/* Nth synchronous lower WRITE attempt, regardless of foreground/GC.
	 * It fails BEFORE dm_io, for isolated fail-closed protocol testing. */
	if (argc > 8 && (kstrtou32(argv[8], 10, &write_fail_nth) ||
			 write_fail_nth > 65535U))
		return -EINVAL;
	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ti->private = ctx;
	ctx->target = ti;
	ctx->max_window = (sv3_u8)window;
	ctx->gc_cost_policy = gc_policy;
	ctx->coalesce_ms = coalesce;
	ctx->flush_meter.fail_nth = flush_fail_nth;
	ctx->write_fault_nth = write_fail_nth;
	ctx->engine.max_read_blocks_per_record = (sv3_u8)budget;
	ctx->engine.verify_after_write = verify;
	ctx->engine.bulk_enabled = lower_bulk;
	spin_lock_init(&ctx->queue_lock);
	INIT_LIST_HEAD(&ctx->incoming);
	INIT_DELAYED_WORK(&ctx->worker, sv3_worker);

	error = dm_get_device(ti, argv[0], dm_table_get_mode(ti->table),
			      &ctx->backing);
	if (error) {
		ti->error = "Cannot open V3 dedicated backing device";
		goto fail;
	}
	/*
	 * Alpha device admission is intentionally stricter than user
	 * authorization. Only an owned, RAM-backed null_blk node may become
	 * a live V3 target before fault/reclaim qualification; a physical
	 * SD, HDD or SSD partition must never be selected accidentally.
	 * Device ownership/UUID checks remain the test harness's duty.
	 */
	if (!ctx->backing->bdev->bd_disk ||
	    strncmp(ctx->backing->bdev->bd_disk->disk_name, "nullb", 5)) {
		ti->error = "swapz3 alpha accepts null_blk backing only";
		error = -EOPNOTSUPP;
		goto fail;
	}
	if (bdev_is_zoned(ctx->backing->bdev) ||
	    bdev_read_only(ctx->backing->bdev) ||
	    bdev_logical_block_size(ctx->backing->bdev) > SV3_BLOCK_BYTES ||
	    SV3_BLOCK_BYTES % bdev_logical_block_size(ctx->backing->bdev)) {
		ti->error = "Unsupported zoned, read-only or unaligned V3 backing";
		error = -EINVAL;
		goto fail;
	}
	logical = div_u64(ti->len, SV3_SECTORS);
	physical = div_u64(bdev_nr_sectors(ctx->backing->bdev), SV3_SECTORS);
	physical = div_u64(physical, SV3_SEGMENT_BLOCKS) * SV3_SEGMENT_BLOCKS;
	if (!logical || logical > U32_MAX || physical > U32_MAX ||
	    physical < 3U * SV3_SEGMENT_BLOCKS) {
		ti->error = "V3 requires at least three 1MiB physical segments";
		error = -EINVAL;
		goto fail;
	}
	ctx->logical_pages = logical;
	ctx->physical_blocks = physical;
	ctx->segment_count = physical / SV3_SEGMENT_BLOCKS;
	ctx->gc_scores = kvcalloc(ctx->segment_count,
				  sizeof(*ctx->gc_scores), GFP_KERNEL);
	ctx->gc_io_scores = kvcalloc(ctx->segment_count,
				     sizeof(*ctx->gc_io_scores), GFP_KERNEL);
	ctx->gc_live_counts = kvcalloc(ctx->segment_count,
				      sizeof(*ctx->gc_live_counts), GFP_KERNEL);
	ctx->gc_min_live_blocks = kvcalloc(ctx->segment_count,
					  sizeof(*ctx->gc_min_live_blocks),
					  GFP_KERNEL);
	ctx->segment_roles = kvcalloc(ctx->segment_count,
				     sizeof(*ctx->segment_roles), GFP_KERNEL);
	ctx->maps = kvcalloc(logical, sizeof(*ctx->maps), GFP_KERNEL);
	ctx->live_records = kvcalloc(physical, sizeof(*ctx->live_records), GFP_KERNEL);
	ctx->extent_classes = kvcalloc(physical, sizeof(*ctx->extent_classes), GFP_KERNEL);
	ctx->discard_epoch = kvcalloc(physical, sizeof(*ctx->discard_epoch), GFP_KERNEL);
	ctx->discard_count = kvcalloc(physical, sizeof(*ctx->discard_count), GFP_KERNEL);
	if (!ctx->maps || !ctx->live_records || !ctx->extent_classes ||
	    !ctx->discard_epoch || !ctx->discard_count ||
	    !ctx->gc_scores || !ctx->gc_io_scores ||
	    !ctx->gc_live_counts || !ctx->gc_min_live_blocks ||
	    !ctx->segment_roles) {
		error = -ENOMEM;
		goto fail;
	}
	error = sv3_authority_init(&ctx->authority, ctx->maps,
				  ctx->live_records, ctx->extent_classes,
				  (u32)logical, (u32)physical);
	if (error) {
		ti->error = "Insufficient capacity for uncompressed pages plus V3 reserve";
		goto fail;
	}
	/* Production allocator exchanges ownership of one GC reserve segment
	 * and one fully evacuated foreground victim every completed cycle. */
	ctx->authority.reuse_dead_segments = 1;
	error = sv3_enable_segment_rotation(&ctx->authority,
					  ctx->segment_roles, ctx->segment_count);
	if (error) {
		ti->error = "Cannot initialize rotating GC reserve roles";
		goto fail;
	}
	ctx->batch_bytes = vzalloc(SV3_BATCH_BYTES);
	ctx->gc_bytes_store = vzalloc(SV3_BATCH_BYTES);
	ctx->input_page = vzalloc(SV3_BLOCK_BYTES);
	ctx->read_page = vzalloc(SV3_BLOCK_BYTES);
	ctx->read_compressed = vzalloc(SV3_BLOCK_BYTES);
	ctx->engine.write_scratch = vzalloc(SV3_MAX_EXTENT_BYTES);
	ctx->engine.read_scratch = vzalloc(SV3_MAX_EXTENT_BYTES);
	ctx->engine.bulk_scratch = vzalloc(SV3_BULK_BLOCKS * SV3_BLOCK_BYTES);
	ctx->engine.bulk_txs = kvcalloc(SV3_MAX_RECORDS,
				       sizeof(*ctx->engine.bulk_txs),
				       GFP_KERNEL);
	ctx->lz4_workmem = kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!ctx->batch_bytes || !ctx->gc_bytes_store ||
	    !ctx->gc_scores || !ctx->gc_io_scores || !ctx->input_page ||
	    !ctx->read_page || !ctx->read_compressed ||
	    !ctx->engine.write_scratch || !ctx->engine.read_scratch ||
	    !ctx->engine.bulk_scratch || !ctx->engine.bulk_txs ||
	    !ctx->lz4_workmem) {
		error = -ENOMEM;
		goto fail;
	}
	ctx->engine.authority = &ctx->authority;
	ctx->engine.io.opaque = ctx;
	ctx->engine.io.write_extent = sv3_lower_write;
	ctx->engine.io.write_run = sv3_lower_write_run;
	ctx->engine.io.read_blocks = sv3_lower_read;
	ctx->io_client = dm_io_client_create();
	if (IS_ERR(ctx->io_client)) {
		error = PTR_ERR(ctx->io_client);
		ctx->io_client = NULL;
		goto fail;
	}
	ctx->workqueue = alloc_workqueue("swapz3", WQ_MEM_RECLAIM, 1);
	if (!ctx->workqueue) {
		error = -ENOMEM;
		goto fail;
	}
	ti->per_io_data_size = sizeof(struct sv3_bio_ref);
	ti->num_flush_bios = 1;
	ti->flush_supported = true;
	ti->num_discard_bios = 1;
	ti->discards_supported = true;
	ti->limit_swap_bios = true;
	error = dm_set_target_max_io_len(ti, SV3_SECTORS);
	if (error)
		goto fail;
	WRITE_ONCE(ctx->accepting, true);
	DMINFO("V3 alpha %s logical_pages=%u physical_blocks=%u window=%u read_cap=%u LIVE GC EXPERIMENTAL",
	       SV3_ALPHA_VERSION, ctx->logical_pages, ctx->physical_blocks,
	       ctx->max_window, (unsigned int)budget);
	return 0;
fail:
	sv3_free(ctx);
	ti->private = NULL;
	return error;
}

static int sv3_iterate_devices(struct dm_target *ti,
			      iterate_devices_callout_fn fn, void *data)
{
	struct sv3_dm *ctx = ti->private;

	return fn(ti, ctx->backing, 0,
		  (sector_t)ctx->physical_blocks * SV3_SECTORS, data);
}

static void sv3_io_hints(struct dm_target *ti, struct queue_limits *limits)
{
	(void)ti;
	limits->logical_block_size = SV3_BLOCK_BYTES;
	limits->physical_block_size = max(limits->physical_block_size,
					  (unsigned int)SV3_BLOCK_BYTES);
	limits->io_min = SV3_BLOCK_BYTES;
	limits->discard_granularity = SV3_BLOCK_BYTES;
	limits->max_hw_discard_sectors = UINT_MAX;
	limits->max_discard_sectors = UINT_MAX;
}

static void sv3_status(struct dm_target *ti, status_type_t type,
		       unsigned int flags, char *result, unsigned int maxlen)
{
	struct sv3_dm *ctx = ti->private;
	unsigned int sz = 0;

	(void)flags;
	switch (type) {
	case STATUSTYPE_INFO:
		DMEMIT("version=%s mode=alpha-live-gc logical_write=%llu logical_read=%llu "
		       "physical_write=%llu physical_write_reqs=%llu "
		       "physical_read=%llu physical_read_reqs=%llu "
		       "compressed=%llu raw=%llu zero_elided=%llu discarded=%llu "
		       "lz4_attempts=%llu lz4_accepted_bytes=%llu "
		       "lz4_size_le256=%llu lz4_size_257_1024=%llu "
		       "lz4_size_1025_2048=%llu lz4_size_2049_3072=%llu "
		       "lz4_size_3073_3568=%llu lz4_raw_fallback=%llu "
		       "windows=%llu reordered=%llu cursor=%u reserve=%u "
		       "gc_victims=%llu gc_role_rotations=%llu "
		       "last_gc_victim=%u last_gc_destination=%u "
		       "gc_pages=%llu gc_read=%llu gc_write=%llu "
		       "gc_policy=%u gc_selected_bytes=%llu gc_selected_pages=%llu "
		       "gc_selected_io_estimate=%llu gc_no_headroom_skips=%llu "
		       "gc_read_reqs=%llu gc_write_reqs=%llu "
		       "dead_segment_reuses=%u write_verify_blocks=%u verify=%u "
		       "write_submitted=%llu write_submitted_reqs=%llu "
		       "read_submitted=%llu read_submitted_reqs=%llu "
		       "write_fault_nth=%u write_fault_calls=%llu write_fault_injected=%llu "
		       "flush_calls=%llu flush_ok=%llu flush_err=%llu "
		       "flush_injected=%llu flush_fault_nth=%u "
		       "bulk_mode=%u bulk_io=%u bulk_extents=%u bulk_padding=%u "
		       "bulk_mixed_io=%u bulk_raw_only_io=%u bulk_raw_entries=%u "
		       "worker_requeues=%llu one_page_windows=%llu "
		       "window_records=%llu coalesce_ms=%u "
		       "win1=%llu win2=%llu win3_4=%llu win5_8=%llu "
		       "win9_16=%llu win17_64=%llu "
		       "coalesce_deferred=%llu coalesce_urgent=%llu "
		       "close_unknown=%llu close_full=%llu close_duplicate=%llu "
		       "close_zero=%llu close_fua=%llu close_raw=%llu "
		       "close_read_conflict=%llu close_read_unrelated=%llu "
		       "close_discard=%llu close_preflush=%llu "
		       "close_quantum=%llu close_idle=%llu close_shutdown=%llu "
		       "close_other=%llu window_gc_pressure=%llu "
		       "age_le100us=%llu age_101_1000us=%llu "
		       "age_gt1000us=%llu age_sum_ns=%llu age_max_ns=%llu "
		       "failed=%u error=%d",
		       SV3_ALPHA_VERSION, ctx->logical_write_bytes,
		       ctx->logical_read_bytes, ctx->physical_write_bytes,
		       ctx->physical_write_reqs, ctx->physical_read_bytes,
		       ctx->physical_read_reqs, ctx->compressed_pages,
		       ctx->raw_pages, ctx->zero_elided_pages,
		       ctx->discard_pages,
		       ctx->lz4_attempts, ctx->lz4_accepted_bytes,
		       ctx->lz4_size_bins[0], ctx->lz4_size_bins[1],
		       ctx->lz4_size_bins[2], ctx->lz4_size_bins[3],
		       ctx->lz4_size_bins[4], ctx->lz4_size_bins[5],
		       ctx->windows,
		       ctx->reordered_records, ctx->authority.next_block,
		       ctx->authority.reserve_blocks,
		       ctx->gc_victims, ctx->gc_role_rotations,
		       ctx->last_gc_victim, ctx->last_gc_destination,
		       ctx->gc_pages, ctx->gc_read_bytes, ctx->gc_write_bytes,
		       ctx->gc_cost_policy, ctx->gc_selected_live_bytes,
		       ctx->gc_selected_live_records, ctx->gc_selected_io_cost,
		       ctx->gc_no_headroom_skips,
		       ctx->gc_read_reqs, ctx->gc_write_reqs,
		       ctx->authority.recycled_dead_segments,
		       ctx->engine.write_verify_read_blocks,
		       ctx->engine.verify_after_write,
		       ctx->lower_write_submitted_bytes,
		       ctx->lower_write_submitted_reqs,
		       ctx->lower_read_submitted_bytes,
		       ctx->lower_read_submitted_reqs,
		       ctx->write_fault_nth, ctx->write_fault_calls,
		       ctx->write_fault_injected,
		       ctx->flush_meter.attempts, ctx->flush_meter.successes,
		       ctx->flush_meter.failures, ctx->flush_meter.injected,
		       ctx->flush_meter.fail_nth,
		       ctx->engine.bulk_enabled,
		       ctx->engine.bulk_writes, ctx->engine.bulk_extents,
		       ctx->engine.bulk_padding_blocks,
		       ctx->engine.bulk_mixed_runs,
		       ctx->engine.bulk_raw_only_runs,
		       ctx->engine.bulk_raw_entries,
		       ctx->worker_requeues, ctx->one_page_windows,
		       ctx->window_records_total, ctx->coalesce_ms,
		       ctx->window_bins[0], ctx->window_bins[1],
		       ctx->window_bins[2], ctx->window_bins[3],
		       ctx->window_bins[4], ctx->window_bins[5],
		       ctx->coalesce_deferred, ctx->coalesce_urgent,
		       ctx->window_close_reasons[SV3_CLOSE_UNKNOWN],
		       ctx->window_close_reasons[SV3_CLOSE_FULL],
		       ctx->window_close_reasons[SV3_CLOSE_DUPLICATE],
		       ctx->window_close_reasons[SV3_CLOSE_ZERO],
		       ctx->window_close_reasons[SV3_CLOSE_FUA],
		       ctx->window_close_reasons[SV3_CLOSE_RAW],
		       ctx->window_close_reasons[SV3_CLOSE_READ_CONFLICT],
		       ctx->window_close_reasons[SV3_CLOSE_READ_UNRELATED],
		       ctx->window_close_reasons[SV3_CLOSE_DISCARD],
		       ctx->window_close_reasons[SV3_CLOSE_PREFLUSH],
		       ctx->window_close_reasons[SV3_CLOSE_QUANTUM],
		       ctx->window_close_reasons[SV3_CLOSE_IDLE],
		       ctx->window_close_reasons[SV3_CLOSE_SHUTDOWN],
		       ctx->window_close_reasons[SV3_CLOSE_OTHER],
		       ctx->window_gc_pressure,
		       ctx->window_age_le_100us, ctx->window_age_101_1000us,
		       ctx->window_age_gt_1000us, ctx->window_age_sum_ns,
		       ctx->window_age_max_ns,
		       ctx->failed, ctx->last_error);
		break;
	case STATUSTYPE_TABLE:
		DMEMIT("%s %u %u %u %u %u %u %u %u", ctx->backing->name,
		       ctx->engine.max_read_blocks_per_record,
		       ctx->max_window, ctx->engine.verify_after_write,
		       ctx->gc_cost_policy, ctx->coalesce_ms,
		       ctx->flush_meter.fail_nth,
		       ctx->engine.bulk_enabled, ctx->write_fault_nth);
		break;
	case STATUSTYPE_IMA:
	default:
		break;
	}
}

static struct target_type sv3_target = {
	.name = "swapz3",
	.version = {3, 0, 0},
	.features = DM_TARGET_SINGLETON | DM_TARGET_ALWAYS_WRITEABLE,
	.module = THIS_MODULE,
	.ctr = sv3_ctr,
	.dtr = sv3_dtr,
	.map = sv3_map,
	.presuspend = sv3_drain,
	.resume = sv3_resume,
	.iterate_devices = sv3_iterate_devices,
	.io_hints = sv3_io_hints,
	.status = sv3_status,
};

static int __init sv3_dm_init(void)
{
	return dm_register_target(&sv3_target);
}

static void __exit sv3_dm_exit(void)
{
	dm_unregister_target(&sv3_target);
}

module_init(sv3_dm_init);
module_exit(sv3_dm_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("swapz main developer");
MODULE_DESCRIPTION("V3.0-alpha size-aware 4/8/16KiB volatile swap target; experimental live GC");
MODULE_ALIAS("dm-swapz3");
