// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz - EXPERIMENTAL swapz volatile Device Mapper swap target.
 *
 * Uses SWZ3 4/8/16KiB extents, 4KiB logical pages, LZ4, bounded
 * size-aware write windows and synchronous dm-io through one serialized
 * WQ_MEM_RECLAIM | WQ_UNBOUND worker.
 *
 * IMPORTANT ALPHA LIMIT: GC is experimentally live with rotating reserved
 * segments, but it remains null_blk-only until independently qualified.
 * On ENOSPC or failed lower I/O, fail closed; never use as system swap.
 */
#define DM_MSG_PREFIX "swapz"
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/device-mapper.h>
#include <linux/dm-io.h>
#include <linux/highmem.h>
#include <linux/hrtimer.h>
#include <linux/ioprio.h>
#include <linux/completion.h>
#include <linux/mempool.h>
#include <linux/semaphore.h>
#include <linux/ktime.h>
#include <linux/lz4.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/sched.h>
#include <linux/vmalloc.h>
#include <linux/version.h>
#include <linux/workqueue.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include "engine.h"
#include "gc-cost.h"
#include "flush-qual.h"
#include "window-policy.h"

#if PAGE_SIZE != SWAPZ_BLOCK_BYTES
#error "swapz requires 4KiB PAGE_SIZE"
#endif
#define SWAPZ_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)
#define SWAPZ_BATCH_BYTES (SWAPZ_MAX_RECORDS * SWAPZ_BLOCK_BYTES)
#include "swapz-version.h" /* generated from src/kernel/VERSION */
#define SWAPZ_WORK_QUANTUM_BIOS 64U
#define SWAPZ_MAX_RETAIN_MS 4U
#define SWAPZ_SINGLETON_DEADLINE_STREAK 2U

/*
 * Experimental opt-in: a separate bounded LZ4 producer may prepare future
 * writes while the existing ordered commit worker waits on lower dm_io.
 * The physical I/O and mapping authority remain single-thread owned.
 */
static bool swapz_async_prepare;
module_param_named(async_prepare, swapz_async_prepare, bool, 0444);
MODULE_PARM_DESC(async_prepare,
		 "Prepare bounded LZ4 writes concurrently with ordered lower I/O");

struct swapz_prepared_page {
	int length;
	bool zero;
	bool payload_crc_valid;
	u32 payload_crc32c;
	u8 bytes[SWAPZ_BLOCK_BYTES];
};

struct swapz_bio_ref {
	struct list_head list;
	struct bio *bio;
	/* Both lists refer to this dm_per_bio_data object. The ordered worker
	 * waits for preparation_finished before touching the payload or BIO.
	 * Only the ordered worker returns a prepared buffer to its pool. */
	struct list_head preparation_list;
	struct completion preparation_finished;
	struct swapz_prepared_page *prepared_page;
	/* Set only when the ordered worker atomically removes this BIO from
	 * preparation_incoming before the producer claims it. */
	bool preparation_inline;
	mempool_t *preparation_pool;
	struct semaphore *preparation_slots;
	int preparation_error;
};

/* The worker attributes exactly one primary reason to each real window. */
enum swapz_window_close_reason {
	SWAPZ_CLOSE_UNKNOWN,
	SWAPZ_CLOSE_FULL,
	SWAPZ_CLOSE_DUPLICATE,
	SWAPZ_CLOSE_ZERO,
	SWAPZ_CLOSE_FUA,
	SWAPZ_CLOSE_RAW,
	SWAPZ_CLOSE_READ_CONFLICT,
	SWAPZ_CLOSE_READ_UNRELATED,
	SWAPZ_CLOSE_DISCARD,
	SWAPZ_CLOSE_PREFLUSH,
	SWAPZ_CLOSE_QUANTUM,
	SWAPZ_CLOSE_IDLE,
	SWAPZ_CLOSE_DEADLINE,
	SWAPZ_CLOSE_PACK_READY,
	SWAPZ_CLOSE_SHUTDOWN,
	SWAPZ_CLOSE_OTHER,
	SWAPZ_CLOSE_REASON_COUNT,
};

struct swapz_dm {
	struct dm_target *target;
	struct dm_dev *backing;
	struct dm_io_client *io_client;
	struct workqueue_struct *workqueue;
	struct delayed_work worker;
	/* One bounded LZ4 producer, separate from the ordered I/O worker.
	 * No producer ever changes maps, stages extents or completes BIOs. */
	bool async_prepare;
	struct workqueue_struct *preparation_workqueue;
	struct work_struct preparation_worker;
	struct list_head preparation_incoming;
	struct semaphore preparation_slots;
	mempool_t *preparation_pool;
	u8 *preparation_input_page;
	/* Producer and ordered worker may now compress concurrently. Never
	 * share LZ4 work memory or a single-writer timing accumulator. */
	void *preparation_lz4_workmem;
	u64 preparation_lz4_wall_ns;
	atomic_t lower_write_active;
	/*
	 * One opposite-end preparation token earned by ordered inline WRITE work.
	 * For a retained window the token may outlive swapz_process() and bridge
	 * the inter-BIO admission gap until the producer consumes it or the
	 * worker closes the window. This preserves one-for-one pacing without
	 * exposing worker-owned batch_count to ->map.
	 */
	atomic_t preparation_tail_credit;
	u64 preparation_producer_head_claims;
	u64 preparation_producer_tail_claims;
	u64 preparation_ordered_inline;
	u64 preparation_ordered_handoffs;
	u64 preparation_ordered_waits;
	u64 preparation_ordered_wait_wall_ns;
	u64 preparation_wave_kicks;
	u64 prepared_during_lower_write;
	u64 preparation_lz4_lower_write_overlap_ns;
	/* Callback only queues the serialized worker; it never owns BIOs. */
	struct hrtimer retention_timer;
	spinlock_t queue_lock;
	struct list_head incoming;
	bool accepting;
	bool failed;
	int last_error;

	struct swapz_authority authority;
	struct swapz_engine engine;
	struct swapz_map *maps;
	swapz_u16 *live_records;
	swapz_u8 *extent_classes;
	/* Per-discard epoch/delta scratch validates shared-extent liveness
	 * before any mapping or generation is mutated. */
	swapz_u32 *discard_epoch;
	swapz_u16 *discard_count;
	swapz_u32 discard_serial;
	swapz_u32 physical_blocks;
	swapz_u32 logical_pages;

	/* Serialized, entirely preallocated normal reclaim path. */
	struct swapz_pending_bio batch[SWAPZ_MAX_RECORDS];
	struct swapz_compressed_page planned[SWAPZ_MAX_RECORDS];
	swapz_u8 planned_to_batch[SWAPZ_MAX_RECORDS];
	swapz_u8 used[SWAPZ_MAX_RECORDS];
	/* Separate GC metadata and compressed record storage. Foreground upper
	 * BIO descriptors/data stay immutable throughout an emergency cleaning. */
	struct swapz_pending_bio gc_pending[SWAPZ_MAX_RECORDS];
	struct swapz_compressed_page gc_planned[SWAPZ_MAX_RECORDS];
	swapz_u8 gc_to_pending[SWAPZ_MAX_RECORDS];
	swapz_u8 gc_used[SWAPZ_MAX_RECORDS];
	swapz_u8 gc_count;
	u8 *gc_bytes_store;
	swapz_u32 *gc_scores;  /* authoritative payload+descriptor bytes */
	swapz_u32 *gc_io_scores; /* conservative read+write cost per victim */
	swapz_u16 *gc_live_counts; /* count for ties/control comparison */
	swapz_u16 *gc_min_live_blocks; /* proven per-survivor block bound */
	swapz_u8 *segment_roles; /* 1=foreground, 0=free GC reserve */
	swapz_u32 *gc_victim_counts;
	swapz_u32 *gc_destination_counts;
	swapz_u32 segment_count;
	swapz_u32 gc_victim_unique;
	swapz_u32 gc_destination_unique;
	swapz_u32 gc_victim_max_reuse;
	swapz_u32 gc_destination_max_reuse;
	swapz_u8 gc_cost_policy; /* 0=record count; 1=payload bytes; 2=I/O */
	u64 gc_selected_io_cost;
	u64 gc_no_headroom_skips;
	u64 gc_selected_live_bytes;
	u64 gc_selected_live_records;
	u64 gc_victims;
	u64 gc_role_rotations;
	swapz_u32 last_gc_victim;
	swapz_u32 last_gc_destination;
	u64 gc_pages;
	u64 gc_read_bytes;
	u64 gc_write_bytes;
	u64 gc_read_reqs;
	u64 gc_write_reqs;
	swapz_u8 batch_count;
	swapz_u8 max_window;
	/* Admission coalescing is optional and bounded by one timer expiry.
	 * No write is published/ACKed until its actual lower I/O completes. */
	/* Explicitly opt-in, disabled at zero. Worker-owned finite window
	 * retention only: never changes original physical publication gate. */
	swapz_u8 retain_ms;
	u64 retain_worker_passes;
	u64 retain_timer_arms;
	u64 retain_timer_arm_skips;
	/*
	 * Adaptive retained-singleton policy. Two consecutive one-page
	 * worker-empty deadline closes prove that this stream has supplied no
	 * companion work despite receiving the full retention opportunity.
	 * Fast-close remains active only until real accepted concurrency appears.
	 */
	swapz_u8 singleton_deadline_streak;
	bool singleton_fast_close;
	/*
	 * Diagnostic-only attribution of the hard 2ms retention deadline.
	 * These four mutually exclusive sites must sum to close_deadline.
	 */
	u64 deadline_before_bio;
	u64 deadline_after_read;
	u64 deadline_worker_with_local;
	u64 deadline_worker_empty;
	u64 retained_read_bypasses;
	/*
	 * Successful retained reads serviced during the current accepted worker
	 * burst. Intermediate packed/fence commits may carry this finite service
	 * evidence forward; a true idle or hard ordering boundary clears it.
	 */
	swapz_u8 retained_window_read_bypasses;
	/* A zero/duplicate/raw/read fence interrupted a still-active accepted
	 * burst. This can release only a tiny dry residue, never predict arrivals. */
	bool retained_wave_interrupted;
	u64 packed_early_commits;
	u64 single_pack_deferrals;
	/*
	 * Only finite accepted work can justify extending a ready pack:
	 * remaining worker-local BIOs or BIOs already present in incoming
	 * when the local snapshot reaches its tail. Future arrivals do not.
	 */
	bool worker_has_immediate_followup;
	/*
	 * Useful pack geometry remains open until the learned retained-burst
	 * width. retained_tail_target is a one-shot target backed only by
	 * already-admitted FIFO evidence: either the residual tail after a
	 * packed commit or the accepted width sampled while the current first
	 * pack is still open. It never predicts or waits for future arrivals.
	 */
	bool single_pack_deferred;
	bool accepted_burst_pack_ready;
	u64 accepted_burst_extensions;
	u64 accepted_burst_tail_flushes;
	u64 accepted_burst_read_caps;
	swapz_u8 retained_burst_target;
	swapz_u8 retained_tail_target;
	swapz_u8 retained_chain_completed;
	bool pack_close_pending_tail_sample;
	u64 window_records_total;
	/* Worker-owned telemetry only; status is a diagnostic snapshot. */
	enum swapz_window_close_reason next_window_close;
	u64 window_close_reasons[SWAPZ_CLOSE_REASON_COUNT];
	/* Joint diagnostic: which primary closure actually produced win1. */
	u64 one_page_close_reasons[SWAPZ_CLOSE_REASON_COUNT];
	u64 window_gc_pressure;
	/* First accepted record -> flush entry, excluding physical I/O. */
	u64 window_first_ns;
	u64 window_age_sum_ns;
	u64 window_age_max_ns;
	u64 window_age_le_100us;
	u64 window_age_101_1000us;
	u64 window_age_gt_1000us;
	u64 window_size_counts[SWAPZ_MAX_RECORDS + 1];
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
	struct swapz_flush_meter flush_meter;
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
	 * index 5: LZ4 did not fit SWAPZ_MAX_COMPRESSED -> raw fallback.
	 */
	u64 lz4_attempts;
	/* Cumulative monotonic wall-time diagnostics; includes warmup and
	 * oracle, NOT CPU cycles and NOT a measurement-interval delta. */
	u64 lz4_wall_ns;
	u64 decode_wall_ns;
	/*
	 * Explicit RAM-copy attribution. Producer and ordered write paths keep
	 * separate single-writer accumulators and are summed only for status.
	 * Bytes count successful explicit copies, not LZ4's own memory traffic.
	 */
	u64 preparation_copy_wall_ns;
	u64 preparation_copy_bytes;
	u64 preparation_direct_lz4_pages;
	u64 preparation_crc_wall_ns;
	u64 preparation_crc_bytes;
	u64 ordered_write_copy_wall_ns;
	u64 ordered_write_copy_bytes;
	u64 ordered_direct_lz4_pages;
	u64 ordered_crc_wall_ns;
	u64 ordered_crc_bytes;
	u64 read_copy_wall_ns;
	u64 read_copy_bytes;
	u64 window_sort_wall_ns;
	u64 window_commit_wall_ns;
	/* Engine commit wall time with synchronous lower-WRITE wait removed. */
	u64 window_commit_nonio_wall_ns;
	u64 engine_plan_wall_ns;
	u64 engine_pack_wall_ns;
	u64 engine_publish_wall_ns;
	u64 engine_stage_wall_ns;
	u64 engine_pause_wall_ns;
	u64 engine_hole_clear_wall_ns;
	u64 engine_resume_wall_ns;
	u64 publish_initial_validate_wall_ns;
	u64 publish_phase1_wall_ns;
	u64 publish_lookup_wall_ns;
	u64 publish_mutation_wall_ns;
	u64 publish_pause_hash_wall_ns;
	u64 publish_resume_hash_wall_ns;
	/* Targeted-read engine wall time with synchronous lower-READ wait removed. */
	u64 read_engine_nonio_wall_ns;
	u64 gc_wall_ns;
	u64 lower_read_wall_ns;
	u64 lower_write_wall_ns;
	/*
	 * Portable callback-active wall upper bounds. Ordered accounting subtracts
	 * measured synchronous lower READ/WRITE waits and producer-completion wait;
	 * preparation has no intentional sleep. Preemption may still inflate either
	 * metric, so these are never labeled CPU time or used for policy.
	 */
	u64 ordered_worker_active_wall_ns;
	u64 preparation_worker_active_wall_ns;
	u64 ordered_active_underflow_events;
	/*
	 * PACK_READY dry-close arrival probe. One pending marker is consumed by
	 * the first later upper WRITE admission. It is diagnostic only.
	 */
	atomic64_t dry_close_pending_ns;
	u64 dry_close_samples;
	u64 dry_close_next_sum_ns;
	u64 dry_close_next_le10us;
	u64 dry_close_next_11_50us;
	u64 dry_close_next_51_200us;
	u64 dry_close_next_gt200us;
	/* Completed synchronous lower WRITE callbacks by wall-wait duration;
	 * nested in lower_write_wall_ns, not hardware command latency. */
	u64 write_wait_le_1ms;
	u64 write_wait_1_to_4ms;
	u64 write_wait_gt_4ms;
	u64 lz4_accepted_bytes;
	u64 lz4_size_bins[6];
	u64 discard_pages;
	u64 windows;
	u64 reordered_records;
	u64 io_failures;
};

static u32 swapz_crc32c_accounted(const void *bytes, u32 length,
				   u64 *wall_ns, u64 *crc_bytes)
{
	u64 start_ns = ktime_get_ns();
	u32 crc = swapz_crc32c_bytes(bytes, length);

	*wall_ns += swapz_elapsed_ns(start_ns, ktime_get_ns());
	*crc_bytes += length;
	return crc;
}

static void swapz_account_preparation_active_wall(struct swapz_dm *ctx,
						  u64 start_ns)
{
	ctx->preparation_worker_active_wall_ns +=
		swapz_elapsed_ns(start_ns, ktime_get_ns());
}

static void swapz_account_ordered_active_wall(struct swapz_dm *ctx,
					      u64 start_ns,
					      u64 lower_read_before,
					      u64 lower_write_before,
					      u64 prep_wait_before)
{
	u64 elapsed = swapz_elapsed_ns(start_ns, ktime_get_ns());
	u64 known_wait =
		(ctx->lower_read_wall_ns - lower_read_before) +
		(ctx->lower_write_wall_ns - lower_write_before) +
		(ctx->preparation_ordered_wait_wall_ns - prep_wait_before);

	if (elapsed >= known_wait)
		ctx->ordered_worker_active_wall_ns += elapsed - known_wait;
	else
		ctx->ordered_active_underflow_events++;
}

static void swapz_record_dry_close_arrival(struct swapz_dm *ctx)
{
	u64 marked = (u64)atomic64_xchg(&ctx->dry_close_pending_ns, 0);
	u64 elapsed;

	if (!marked)
		return;
	elapsed = swapz_elapsed_ns(marked, ktime_get_ns());
	ctx->dry_close_samples++;
	ctx->dry_close_next_sum_ns += elapsed;
	if (elapsed <= 10000ULL)
		ctx->dry_close_next_le10us++;
	else if (elapsed <= 50000ULL)
		ctx->dry_close_next_11_50us++;
	else if (elapsed <= 200000ULL)
		ctx->dry_close_next_51_200us++;
	else
		ctx->dry_close_next_gt200us++;
}

/*
 * Per-BIO prepared bytes have one final owner: the serialized worker.
 * Release before bio_endio(), which can invalidate dm_per_bio_data.
 * Early release after copying into batch_bytes bounds producer memory.
 */
static void swapz_release_prepared(struct bio *bio)
{
	struct swapz_bio_ref *entry = dm_per_bio_data(bio, sizeof(*entry));

	if (!entry->prepared_page)
		return;
	mempool_free(entry->prepared_page, entry->preparation_pool);
	entry->prepared_page = NULL;
	up(entry->preparation_slots);
}

static void swapz_complete(struct bio *bio, int error)
{
	swapz_release_prepared(bio);
	if (error)
		bio->bi_status = errno_to_blk_status(error);
	bio_endio(bio);
}

static void swapz_fail(struct swapz_dm *ctx, int error)
{
	if (!ctx->failed) {
		ctx->failed = true;
		ctx->last_error = error < 0 ? error : -EIO;
		ctx->io_failures++;
		DMERR("swapz alpha: lower or mapping error %d; rejecting subsequent I/O",
		      ctx->last_error);
	}
}

/*
 * This adapter reports completed blocks only after SYNCHRONOUS dm_io returns
 * successfully with an empty error bitmap.  No assumed partial completions.
 * On an error, the entire reserved extent is quarantined by the swapz authority.
 * Scratch is vmalloc-backed: DM_IO_VMA, never DM_IO_KMEM.
 */
static int swapz_lower(struct swapz_dm *ctx, enum req_op op, swapz_u32 block,
		     swapz_u16 blocks, u8 *bytes)
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
	u64 section_start, elapsed_ns;
	int error;

	if (!blocks || block >= ctx->physical_blocks ||
	    blocks > ctx->physical_blocks - block)
		return -ERANGE;
	region.bdev = ctx->backing->bdev;
	region.sector = (sector_t)block * SWAPZ_SECTORS;
	region.count = (sector_t)blocks * SWAPZ_SECTORS;
	/* Inject at the common physical WRITE boundary, including foreground
	 * mixed runs, serialized controls and GC relocation. Never count this
	 * synthetic rejection as submitted/completed lower-device I/O. */
	if (op == REQ_OP_WRITE && ctx->write_fault_nth &&
	    ++ctx->write_fault_calls == ctx->write_fault_nth) {
		ctx->write_fault_injected++;
		return -EIO;
	}
	/* Cover direct RAW writes and GC relocation as well as engine writes.
	 * The synchronous lower worker exclusively owns read_scratch. */
	if (op == REQ_OP_WRITE)
		swapz_engine_invalidate_read_cache(&ctx->engine);
	if (op == REQ_OP_READ) {
		ctx->lower_read_submitted_bytes +=
			(u64)blocks * SWAPZ_BLOCK_BYTES;
		ctx->lower_read_submitted_reqs++;
	} else {
		ctx->lower_write_submitted_bytes +=
			(u64)blocks * SWAPZ_BLOCK_BYTES;
		ctx->lower_write_submitted_reqs++;
	}
	section_start = ktime_get_ns();
	/* The producer observes only this atomic diagnostic; lower I/O
	 * completion and mapping publication remain owned by this caller.
	 * If an inline-steal head left preparation work queued, a real lower
	 * WRITE is the overlap opportunity that should wake the producer. */
	if (op == REQ_OP_WRITE) {
		atomic_set(&ctx->lower_write_active, 1);
		if (ctx->async_prepare) {
			unsigned long irq_flags;

			spin_lock_irqsave(&ctx->queue_lock, irq_flags);
			if (!list_empty(&ctx->preparation_incoming))
				queue_work(ctx->preparation_workqueue,
					   &ctx->preparation_worker);
			spin_unlock_irqrestore(&ctx->queue_lock, irq_flags);
		}
	}
	error = dm_io(&req, 1, &region, &bitmap, IOPRIO_DEFAULT);
	if (op == REQ_OP_WRITE)
		atomic_set(&ctx->lower_write_active, 0);
	elapsed_ns = swapz_elapsed_ns(section_start, ktime_get_ns());
	if (op == REQ_OP_READ)
		ctx->lower_read_wall_ns += elapsed_ns;
	else
		ctx->lower_write_wall_ns += elapsed_ns;
	if (error || bitmap)
		return error ? error : -EIO;
	/* Count SUCCESSFUL dm_io callbacks, not attempted or error-injected
	 * requests. Each accepted lower write is in exactly one wait bin. */
	if (op == REQ_OP_WRITE) {
		if (elapsed_ns <= 1000000ULL)
			ctx->write_wait_le_1ms++;
		else if (elapsed_ns <= 4000000ULL)
			ctx->write_wait_1_to_4ms++;
		else
			ctx->write_wait_gt_4ms++;
	}
	if (op == REQ_OP_READ) {
		ctx->physical_read_bytes += (u64)blocks * SWAPZ_BLOCK_BYTES;
		ctx->physical_read_reqs++;
	} else {
		ctx->physical_write_bytes += (u64)blocks * SWAPZ_BLOCK_BYTES;
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
static int swapz_kernel_lower_flush(void *opaque)
{
	struct swapz_dm *ctx = opaque;

	return blkdev_issue_flush(ctx->backing->bdev);
}

static int swapz_issue_flush(struct swapz_dm *ctx)
{
	int error = swapz_flush_accounted(&ctx->flush_meter,
				      swapz_kernel_lower_flush, ctx);

	if (error)
		swapz_fail(ctx, error);
	return error;
}

static int swapz_lower_write(void *opaque, swapz_u32 block, swapz_u8 blocks,
			   const swapz_u8 *bytes, swapz_u8 *completed)
{
	struct swapz_dm *ctx = opaque;
	int error;

	*completed = 0;
	error = swapz_lower(ctx, REQ_OP_WRITE, block, blocks, (u8 *)bytes);
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
static int swapz_lower_write_run(void *opaque, swapz_u32 block,
			      swapz_u16 blocks, const swapz_u8 *bytes,
			      swapz_u16 *completed)
{
	struct swapz_dm *ctx = opaque;
	int error;

	*completed = 0;
	if (!blocks || blocks > SWAPZ_BULK_BLOCKS)
		return -ERANGE;
	error = swapz_lower(ctx, REQ_OP_WRITE, block, blocks, (u8 *)bytes);
	if (!error)
		*completed = blocks;
	return error;
}

static int swapz_lower_read(void *opaque, swapz_u32 block, swapz_u8 blocks,
			  swapz_u8 *destination)
{
	return swapz_lower(opaque, REQ_OP_READ, block, blocks, destination);
}

/*
 * Optional diagnostic verification for raw pages, matching the compressed
 * engine's verify-after-write behavior. The raw page has no spare on-media
 * bytes for CRC, so compare a fresh complete lower read to the original
 * data BEFORE swapz_finish_raw publishes mapping authority. This is not an
 * fsync/power-loss guarantee. Disabled in the default performance policy.
 */
static int swapz_verify_raw_write(struct swapz_dm *ctx, swapz_u32 block,
				const u8 *original)
{
	int error;

	if (!ctx->engine.verify_after_write)
		return 0;
	if (!original || ctx->read_page == original)
		return -EINVAL;
	error = swapz_lower_read(ctx, block, 1, ctx->read_page);
	if (error)
		return error;
	ctx->engine.write_verify_read_blocks++;
	return memcmp(ctx->read_page, original, SWAPZ_BLOCK_BYTES) ?
		-EBADMSG : 0;
}

static int swapz_copy_bio(struct bio *bio, void *buffer, bool to_bio)
{
	struct bio_vec vec;
	struct bvec_iter iter;
	size_t offset = 0;

	bio_for_each_segment(vec, bio, iter) {
		void *mapped;

		if (vec.bv_len > SWAPZ_BLOCK_BYTES - offset)
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
	return offset == SWAPZ_BLOCK_BYTES ? 0 : -EINVAL;
}

/*
 * A normal swap page commonly arrives as one complete 4KiB bvec. Keep that
 * upper page pinned by BIO ownership and map it only for the synchronous
 * LZ4/zero-scan section. Multi-bvec BIOs retain the established copy fallback.
 */
static const u8 *swapz_map_single_bio_input(struct bio *bio, void **mapped)
{
	struct bio_vec only = { 0 };
	struct bio_vec vec;
	struct bvec_iter iter;
	unsigned int segments = 0;

	*mapped = NULL;
	bio_for_each_segment(vec, bio, iter) {
		if (++segments > 1)
			return NULL;
		only = vec;
	}
	if (segments != 1 || only.bv_len != SWAPZ_BLOCK_BYTES ||
	    only.bv_offset != 0)
		return NULL;
	*mapped = kmap_local_page(only.bv_page);
	return *mapped;
}

static int swapz_copy_bio_accounted(struct bio *bio, void *buffer, bool to_bio,
				    u64 *wall_ns, u64 *bytes)
{
	u64 start_ns = ktime_get_ns();
	int error = swapz_copy_bio(bio, buffer, to_bio);

	*wall_ns += swapz_elapsed_ns(start_ns, ktime_get_ns());
	if (!error)
		*bytes += SWAPZ_BLOCK_BYTES;
	return error;
}

static void swapz_memcpy_accounted(void *destination, const void *source,
				   size_t bytes, u64 *wall_ns, u64 *copied_bytes)
{
	u64 start_ns = ktime_get_ns();

	memcpy(destination, source, bytes);
	*wall_ns += swapz_elapsed_ns(start_ns, ktime_get_ns());
	*copied_bytes += bytes;
}

/*
 * Asynchronous compression is restricted to an independent, finite producer.
 * It neither acknowledges nor publishes any write. queue_lock transfers a
 * BIO descriptor from preparation_incoming to this worker, which can then
 * read its still-pinned upper BIO data. The ordered consumer waits on its
 * completion and is solely responsible for recycling prepared_page.
 *
 * preparation_slots caps resident prepared pages to SWAPZ_MAX_RECORDS even
 * under unlimited incoming BIOs. The producer never waits for a slot while
 * holding queue_lock. Tail claims cannot deadlock the FIFO consumer because
 * the ordered worker can keep stealing unclaimed head entries inline without
 * consuming preparation slots, then releases prepared slots as it reaches
 * already-completed entries in admission order.
 */
static void swapz_preparation_worker(struct work_struct *work)
{
	struct swapz_dm *ctx =
		container_of(work, struct swapz_dm, preparation_worker);
	struct swapz_bio_ref *entry;
	unsigned long flags;
	u64 active_start_ns = ktime_get_ns();

	for (;;) {
		struct swapz_prepared_page *prepared;
		const u8 *input;
		void *mapped_input = NULL;
		u64 section_start;
		bool tail_claim = false;
		bool lower_write_overlap;
		u64 elapsed_ns;
		int error;

		/*
		 * Reserve bounded prepared-page capacity before claiming a BIO.
		 * Never block here: with opposite-end claiming, blocking after
		 * removing an earlier FIFO entry could deadlock the ordered worker
		 * behind prepared tail entries that own every slot. If capacity is
		 * exhausted, leave all remaining entries claimable by inline steal.
		 */
		if (down_trylock(&ctx->preparation_slots)) {
			swapz_account_preparation_active_wall(ctx, active_start_ns);
			return;
		}
		spin_lock_irqsave(&ctx->queue_lock, flags);
		if (list_empty(&ctx->preparation_incoming)) {
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			up(&ctx->preparation_slots);
			swapz_account_preparation_active_wall(ctx, active_start_ns);
			return;
		}
		/*
		 * If the ordered worker is sleeping in synchronous lower WRITE I/O,
		 * prepare the FIFO head it will need next. Otherwise that worker is
		 * free to steal from the head, so consume the tail and let both CPUs
		 * meet in the middle instead of convoying on wait_for_completion().
		 */
		if (atomic_read(&ctx->lower_write_active)) {
			/*
			 * The ordered worker is blocked in synchronous lower WRITE I/O.
			 * Drain from the FIFO head while that real overlap interval lasts.
			 * A prior tail credit is obsolete once lower I/O becomes the owner
			 * of preparation overlap.
			 */
			atomic_set(&ctx->preparation_tail_credit, 0);
			entry = list_first_entry(&ctx->preparation_incoming,
						 struct swapz_bio_ref,
						 preparation_list);
			ctx->preparation_producer_head_claims++;
		} else {
			/*
			 * On a singular list, list_last_entry is also the FIFO head the
			 * ordered worker is about to steal inline. Claiming that sole
			 * entry manufactures a wait_for_completion() collision. Leave
			 * both the head and its earned credit intact until a true tail
			 * exists behind it.
			 */
			if (list_is_singular(&ctx->preparation_incoming) ||
			    !atomic_xchg(&ctx->preparation_tail_credit, 0)) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				up(&ctx->preparation_slots);
				swapz_account_preparation_active_wall(ctx, active_start_ns);
				return;
			}
			entry = list_last_entry(&ctx->preparation_incoming,
						struct swapz_bio_ref,
						preparation_list);
			tail_claim = true;
			ctx->preparation_producer_tail_claims++;
		}
		list_del_init(&entry->preparation_list);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);

		prepared = mempool_alloc(ctx->preparation_pool, GFP_NOIO);
		if (!prepared) {
			entry->preparation_error = -ENOMEM;
			up(&ctx->preparation_slots);
			complete(&entry->preparation_finished);
			if (tail_claim && !atomic_read(&ctx->lower_write_active) &&
			    !atomic_read(&ctx->preparation_tail_credit)) {
				swapz_account_preparation_active_wall(ctx, active_start_ns);
				return;
			}
			continue;
		}
		input = swapz_map_single_bio_input(entry->bio, &mapped_input);
		if (input) {
			ctx->preparation_direct_lz4_pages++;
		} else {
			error = swapz_copy_bio_accounted(entry->bio,
					    ctx->preparation_input_page, false,
					    &ctx->preparation_copy_wall_ns,
					    &ctx->preparation_copy_bytes);
			if (error) {
				mempool_free(prepared, ctx->preparation_pool);
				up(&ctx->preparation_slots);
				entry->preparation_error = error;
				complete(&entry->preparation_finished);
				if (tail_claim &&
				    !atomic_read(&ctx->lower_write_active) &&
				    !atomic_read(&ctx->preparation_tail_credit)) {
					swapz_account_preparation_active_wall(ctx, active_start_ns);
					return;
				}
				continue;
			}
			input = ctx->preparation_input_page;
		}
		section_start = ktime_get_ns();
		/*
		 * Count a producer compression as lower-I/O overlap only when the
		 * synchronous WRITE is active at both ends of this short LZ4 section.
		 * This deliberately undercounts boundary crossings rather than
		 * inventing overlap that did not fully exist.
		 */
		lower_write_overlap = atomic_read(&ctx->lower_write_active);
		if (lower_write_overlap)
			ctx->prepared_during_lower_write++;
		prepared->length = LZ4_compress_fast(
					input,
					prepared->bytes, SWAPZ_BLOCK_BYTES,
					SWAPZ_MAX_COMPRESSED, 1,
					ctx->preparation_lz4_workmem);
		elapsed_ns = swapz_elapsed_ns(section_start, ktime_get_ns());
		ctx->preparation_lz4_wall_ns += elapsed_ns;
		if (lower_write_overlap &&
		    atomic_read(&ctx->lower_write_active))
			ctx->preparation_lz4_lower_write_overlap_ns += elapsed_ns;
		prepared->zero = prepared->length > 0 &&
				 prepared->length <= 64 &&
				 swapz_page_is_zero(input);
		prepared->payload_crc_valid =
			prepared->length > 0 && !prepared->zero;
		prepared->payload_crc32c = prepared->payload_crc_valid ?
			swapz_crc32c_accounted(prepared->bytes,
					      (u32)prepared->length,
					      &ctx->preparation_crc_wall_ns,
					      &ctx->preparation_crc_bytes) : 0;
		if (prepared->length <= 0)
			swapz_memcpy_accounted(prepared->bytes, input,
					      SWAPZ_BLOCK_BYTES,
					      &ctx->preparation_copy_wall_ns,
					      &ctx->preparation_copy_bytes);
		if (mapped_input)
			kunmap_local(mapped_input);
		/* Release ordering: complete() wakes the sole consumer. Do not
		 * touch entry again after signaling: it may be bio_endio'd. */
		entry->prepared_page = prepared;
		entry->preparation_error = 0;
		complete(&entry->preparation_finished);
		/*
		 * A tail claim consumes one token. If ordered inline work earned a
		 * fresh token while this page was being prepared, stay on this
		 * already-running worker and consume that token on the next loop.
		 * Otherwise stop; the producer never drains uncredited tail work.
		 */
		if (tail_claim && !atomic_read(&ctx->lower_write_active) &&
		    !atomic_read(&ctx->preparation_tail_credit)) {
			swapz_account_preparation_active_wall(ctx, active_start_ns);
			return;
		}
	}
}

/*
 * Sort already-accepted, distinct-slot pages into size-complementary pairs.
 * The greedy largest-plus-best-fitting partner is intentionally bounded by
 * 64 records and stable for equal-size/tie cases. The extent engine then
 * optimizes 4/8/16KiB contiguous physical geometry over this order.
 *
 * NEVER reorder across flush/FUA, discard, dependent reads or duplicate slots.
 */
static void swapz_order_window_greedy(struct swapz_dm *ctx)
{
	swapz_u8 position = 0;

	memset(ctx->used, 0, sizeof(ctx->used));
	while (position < ctx->batch_count) {
		int largest = -1, partner = -1;
		int best_slack = INT_MAX;
		swapz_u8 i;

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

		/* SWZ3 metadata: header(16) + two descriptors(32). */
		for (i = 0; i < ctx->batch_count; ++i) {
			int remaining;

			if (ctx->used[i] || ctx->batch[i].raw)
				continue;
			remaining = SWAPZ_BLOCK_BYTES - 48 -
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
		swapz_u8 index;

		for (index = 0; index < ctx->batch_count; ++index)
			if (!ctx->used[index])
				ctx->planned_to_batch[position++] = index;
	}
}

static void swapz_order_window(struct swapz_dm *ctx)
{
	swapz_u8 position;

	if (swapz_window_uniform_compressed(ctx->batch, ctx->batch_count)) {
		/* Equal compressed lengths imply stable greedy identity order,
		 * regardless of whether two records share a 4KiB extent.
		 * Avoid scanning every already-consumed record at every step.
		 * The actual extent planner and commit gate are UNCHANGED. */
		for (position = 0; position < ctx->batch_count; ++position)
			ctx->planned_to_batch[position] = position;
	} else {
		swapz_order_window_greedy(ctx);
	}
	for (position = 0; position < ctx->batch_count; ++position) {
		swapz_u8 index = ctx->planned_to_batch[position];

		if (index != position)
			ctx->reordered_records++;
		ctx->planned[position] = (struct swapz_compressed_page) {
			.logical_page = ctx->batch[index].logical,
			.payload = ctx->batch_bytes + (size_t)index * SWAPZ_BLOCK_BYTES,
			.payload_crc32c = ctx->batch[index].payload_crc32c,
			.length = ctx->batch[index].length,
			.payload_crc_valid = ctx->batch[index].payload_crc_valid,
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
static void swapz_gc_sort(struct swapz_dm *ctx)
{
	swapz_u8 position = 0, i;

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
			slack = SWAPZ_BLOCK_BYTES - 48 -
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
		swapz_u8 index = ctx->gc_to_pending[position];

		ctx->gc_planned[position] = (struct swapz_compressed_page) {
			.logical_page = ctx->gc_pending[index].logical,
			.payload = ctx->gc_bytes_store +
				(size_t)index * SWAPZ_BLOCK_BYTES,
			.payload_crc32c = ctx->gc_pending[index].payload_crc32c,
			.length = ctx->gc_pending[index].length,
			.payload_crc_valid = ctx->gc_pending[index].payload_crc_valid,
		};
	}
}

static int swapz_gc_flush(struct swapz_dm *ctx)
{
	swapz_u8 completed = 0;
	int error;

	if (!ctx->gc_count)
		return 0;
	swapz_gc_sort(ctx);
	error = swapz_engine_write_window_batched(&ctx->engine, ctx->gc_planned,
					 ctx->gc_count, &completed);
	ctx->gc_pages += completed;
	ctx->gc_count = 0;
	return error;
}

static int swapz_gc_move_raw(struct swapz_dm *ctx, swapz_u32 logical,
			   const struct swapz_map *old)
{
	struct swapz_tx tx;
	swapz_u8 completed = 0;
	int error;

	if (old->extent_blocks != 1 || old->start_block >= ctx->physical_blocks)
		return -EUCLEAN;
	error = swapz_lower_read(ctx, old->start_block, 1, ctx->input_page);
	if (error)
		return error;
	/* Never propagate a corrupted raw page into a new GC location. */
	error = swapz_verify_raw(&ctx->authority, logical, ctx->input_page);
	if (error)
		return error;
	error = swapz_stage(&ctx->authority, &logical, 1, 1, &tx);
	if (error)
		return error;
	error = swapz_lower_write(ctx, tx.start_block, 1,
				ctx->input_page, &completed);
	if (!error && completed == 1)
		error = swapz_verify_raw_write(ctx, tx.start_block,
					   ctx->input_page);
	error = swapz_finish_raw(&ctx->authority, &tx, ctx->input_page, completed, error);
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
static int swapz_gc_choose_victim(struct swapz_dm *ctx, swapz_u32 *victim)
{
	swapz_u32 logical, segment, selected = ~(swapz_u32)0;
	swapz_u32 best = ~(swapz_u32)0;
	swapz_u16 best_count = ~(swapz_u16)0;

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
		const struct swapz_map *m = &ctx->maps[logical];
		swapz_u32 cost, io_cost;

		if (!m->valid)
			continue;
		if (m->start_block >= ctx->physical_blocks)
			return -EUCLEAN;
		cost = swapz_gc_live_byte_cost(m);
		io_cost = swapz_gc_estimated_io_cost(m);
		if (!cost || !io_cost)
			return -EUCLEAN;
		segment = m->start_block / SWAPZ_SEGMENT_BLOCKS;
		if (ctx->gc_scores[segment] > ~(swapz_u32)0 - cost ||
		    ctx->gc_io_scores[segment] > ~(swapz_u32)0 - io_cost ||
		    ctx->gc_live_counts[segment] == ~(swapz_u16)0)
			return -EOVERFLOW;
		ctx->gc_scores[segment] += cost;
		ctx->gc_io_scores[segment] += io_cost;
		ctx->gc_min_live_blocks[segment] +=
					swapz_gc_min_live_blocks(m);
		ctx->gc_live_counts[segment]++;
	}
	for (segment = 0; segment < ctx->segment_count; ++segment) {
		swapz_u16 count = ctx->gc_live_counts[segment];
		swapz_u32 score;

		/* GC must create *foreground usable* space. Evacuating a
		 * reserve segment only moves survivors between GC reserves
		 * and causes false progress followed by foreground ENOSPC. */
		if (!count || !ctx->segment_roles[segment] ||
		    segment == ctx->authority.open_segment)
			continue;
		/* Reject a provably non-reclaimable full victim BEFORE paying
		 * for up to 1MiB of GC reads/writes. Such an eviction could
		 * only fill its sole reserve destination and return ENOSPC. */
		if (!swapz_gc_candidate_can_free_block(ctx->gc_scores[segment],
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
		if (swapz_gc_prefer(score, count, best, best_count)) {
			best = score;
			best_count = count;
			selected = segment;
		}
	}
	if (selected == ~(swapz_u32)0)
		return -ENOSPC;
	*victim = selected;
	ctx->gc_selected_live_bytes += ctx->gc_scores[selected];
	ctx->gc_selected_live_records += ctx->gc_live_counts[selected];
	ctx->gc_selected_io_cost += ctx->gc_io_scores[selected];
	return 0;
}

static int swapz_gc_compact_one(struct swapz_dm *ctx)
{
	struct swapz_authority *a = &ctx->authority;
	swapz_u32 old_next, old_open, old_probe, victim, logical, block;
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
	error = swapz_gc_choose_victim(ctx, &victim);
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
	error = swapz_gc_begin_rotation(a, victim);
	if (error)
		goto out;
	ctx->gc_count = 0;

	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		struct swapz_map snapshot = ctx->maps[logical];
		swapz_u16 length;

		/* GC can scan a large volatile map while the worker owns it.
		 * Yield CPU periodically without permitting another mapping
		 * writer: the same worker remains the only authority owner. */
		if (!(logical & 63U))
			cond_resched();
		if (!snapshot.valid ||
		    snapshot.start_block / SWAPZ_SEGMENT_BLOCKS != victim)
			continue;
		if (snapshot.raw) {
			error = swapz_gc_flush(ctx);
			if (error)
				goto out;
			error = swapz_gc_move_raw(ctx, logical, &snapshot);
			if (error)
				goto out;
			continue;
		}
		/* Existing media bytes remain authoritative until this page's
		 * full replacement is successfully committed by the swapz engine. */
		error = swapz_engine_read_page(&ctx->engine, logical,
						ctx->read_compressed,
						SWAPZ_BLOCK_BYTES, &length);
		if (error)
			goto out;
		if (!length || length > SWAPZ_MAX_COMPRESSED) {
			error = -EUCLEAN;
			goto out;
		}
		memcpy(ctx->gc_bytes_store +
		       (size_t)ctx->gc_count * SWAPZ_BLOCK_BYTES,
		       ctx->read_compressed, length);
		ctx->gc_pending[ctx->gc_count++] =
			(struct swapz_pending_bio) {
				.bio = NULL,
				.logical = logical,
				.length = length,
			};
		if (ctx->gc_count == SWAPZ_MAX_RECORDS) {
			error = swapz_gc_flush(ctx);
			if (error)
				goto out;
		}
	}
	error = swapz_gc_flush(ctx);
	if (error)
		goto out;

	/*
	 * Do not deem the victim reclaimable merely because GC wrote some
	 * replacements. Independently verify no live mapping and no physical
	 * liveness record remain in the original segment. If this test fails,
	 * return an error without recycling any physical bytes.
	 */
	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		const struct swapz_map *m = &ctx->maps[logical];

		if (m->valid &&
		    m->start_block / SWAPZ_SEGMENT_BLOCKS == victim) {
			error = -EUCLEAN;
			goto out;
		}
	}
	for (block = victim * SWAPZ_SEGMENT_BLOCKS;
	     block < (victim + 1) * SWAPZ_SEGMENT_BLOCKS; ++block) {
		if (a->live_records[block]) {
			error = -EUCLEAN;
			goto out;
		}
	}
	/* Atomically exchange reserve/foreground ownership only after ALL
	 * authoritative mappings and live refcounts vacate the victim. */
	{
		swapz_u32 destination = a->gc_destination;

		error = swapz_gc_commit_rotation(a, victim);
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
		a->gc_forbidden_open = ~(swapz_u32)0;
		a->gc_forbidden_victim = ~(swapz_u32)0;
		a->gc_destination = ~(swapz_u32)0;
		a->next_block = old_next;
		a->open_segment = old_open;
		a->next_segment_probe = old_probe;
	}
	return error;
}


static void swapz_window_admit_clock(struct swapz_dm *ctx)
{
	/* Serialized worker: do not refresh the start for later records. */
	if (!ctx->batch_count)
		ctx->window_first_ns = ktime_get_ns();
}

static int swapz_flush_window(struct swapz_dm *ctx)
{
	swapz_u8 committed = 0, index, count = ctx->batch_count;
	swapz_u8 gc_attempts = 0;
	bool needs_fua = false;
	bool packed_close = ctx->next_window_close == SWAPZ_CLOSE_PACK_READY;
	bool accepted_burst_extended = ctx->accepted_burst_pack_ready;
	enum swapz_window_close_reason close_reason = ctx->next_window_close;
	swapz_u8 planning_read_cap = ctx->engine.max_read_blocks_per_record;
	u64 end_ns, open_age_ns, section_start;
	bool interrupted_close =
		close_reason == SWAPZ_CLOSE_ZERO ||
		close_reason == SWAPZ_CLOSE_DUPLICATE ||
		close_reason == SWAPZ_CLOSE_RAW ||
		close_reason == SWAPZ_CLOSE_READ_CONFLICT ||
		close_reason == SWAPZ_CLOSE_READ_UNRELATED;
	bool hard_boundary =
		close_reason == SWAPZ_CLOSE_FUA ||
		close_reason == SWAPZ_CLOSE_PREFLUSH ||
		close_reason == SWAPZ_CLOSE_DISCARD ||
		close_reason == SWAPZ_CLOSE_DEADLINE ||
		close_reason == SWAPZ_CLOSE_IDLE ||
		close_reason == SWAPZ_CLOSE_QUANTUM ||
		close_reason == SWAPZ_CLOSE_SHUTDOWN ||
		close_reason == SWAPZ_CLOSE_OTHER;
	bool chain_continues;
	int error = 0;

	/*
	 * An empty flush is not a committed write window. In particular, a READ
	 * or zero-page immediately after PACK_READY must not erase the serviced
	 * chain before the ordered worker can observe already-accepted followers.
	 * Real ordering barriers still terminate scheduling evidence.
	 */
	if (!count) {
		if (hard_boundary) {
			ctx->single_pack_deferred = false;
			ctx->accepted_burst_pack_ready = false;
			ctx->retained_tail_target = 0;
			ctx->pack_close_pending_tail_sample = false;
			ctx->retained_chain_completed = 0;
			ctx->retained_window_read_bypasses = 0;
			ctx->retained_wave_interrupted = false;
		} else if (ctx->retain_ms && interrupted_close &&
			   ctx->worker_has_immediate_followup) {
			ctx->retained_wave_interrupted = true;
		}
		ctx->next_window_close = SWAPZ_CLOSE_UNKNOWN;
		ctx->window_first_ns = 0;
		return 0;
	}

	/*
	 * A real nonempty window close ends any unconsumed preparation token
	 * earned by that window. Lower-WRITE overlap below has its own explicit
	 * head-first producer wake and does not depend on this tail credit.
	 */
	atomic_set(&ctx->preparation_tail_credit, 0);

	/*
	 * DUPLICATE/FULL flush older writes before the current WRITE continues.
	 * ZERO/RAW continue a chain only when a later BIO was already accepted.
	 * PACK_READY is always a serviced chain. Only PACK_READY requests a
	 * post-I/O admitted-tail sample; the other cases are service evidence,
	 * not permission to infer a future burst width.
	 */
	chain_continues = ctx->retain_ms &&
		(packed_close ||
		 close_reason == SWAPZ_CLOSE_DUPLICATE ||
		 close_reason == SWAPZ_CLOSE_FULL ||
		 ((close_reason == SWAPZ_CLOSE_ZERO ||
		   close_reason == SWAPZ_CLOSE_RAW) &&
		  ctx->worker_has_immediate_followup));

	ctx->single_pack_deferred = false;
	ctx->accepted_burst_pack_ready = false;
	ctx->retained_tail_target = 0;
	/* A real multi-record window disproves isolated closed-loop behavior.
	 * Before bypass is learned, any non-deadline singleton also breaks the
	 * consecutive-deadline evidence chain. Learned singleton fast-close
	 * persists across its own ordinary idle closes until concurrency appears. */
	if (count > 1U) {
		ctx->singleton_deadline_streak = 0;
		ctx->singleton_fast_close = false;
	} else if (count == 1U &&
		   ctx->next_window_close != SWAPZ_CLOSE_DEADLINE &&
		   !ctx->singleton_fast_close) {
		ctx->singleton_deadline_streak = 0;
	}
	/* Measure BEFORE any dm_io, GC, verification or lower FUA. */
	end_ns = ktime_get_ns();
	/* The timer can only be armed by opted-in retained windows.
	 * Nonretained singleton windows have no callback to synchronize,
	 * so avoid a needless hrtimer_cancel() on every physical WRITE.
	 * With retention enabled, cancellation remains synchronous and
	 * outside queue_lock because the callback takes that lock.
	 * Shutdown/free retain unconditional cancellation. */
	if (swapz_window_timer_enabled(ctx->retain_ms))
		hrtimer_cancel(&ctx->retention_timer);
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
	ctx->window_close_reasons[close_reason]++;
	ctx->next_window_close = SWAPZ_CLOSE_UNKNOWN;
	/* An independent READ can fail while older writes are only prepared.
	 * Complete their original owners once, without ordering/staging or
	 * submitting any unpublished bytes after the target has failed. */
	if (ctx->failed) {
		error = ctx->last_error ? ctx->last_error : -EIO;
		for (index = 0; index < count; ++index)
			swapz_complete(ctx->batch[index].bio, error);
		goto accounted;
	}
	/* The accepted-burst experiment may aggregate many logical records
	 * without waiting for future arrivals. Keep that lower-run opportunity,
	 * but cap only ITS write planner to at most two cold read blocks per
	 * record. Runtime reads retain the target's configured policy. */
	if (accepted_burst_extended && !planning_read_cap) {
		planning_read_cap = 2U;
		ctx->accepted_burst_read_caps++;
	}
	section_start = ktime_get_ns();
	swapz_order_window(ctx);
	ctx->window_sort_wall_ns +=
		swapz_elapsed_ns(section_start, ktime_get_ns());
	for (index = 0; index < count; ++index)
		if (ctx->batch[index].bio->bi_opf & REQ_FUA)
			needs_fua = true;
	while (committed < count) {
		swapz_u8 succeeded = 0;

		u64 lower_write_before = ctx->lower_write_wall_ns;
		u64 plan_before = ctx->engine.plan_wall_ns;
		u64 pack_before = ctx->engine.pack_wall_ns;
		u64 publish_before = ctx->engine.publish_wall_ns;
		u64 commit_elapsed;
		u64 lower_write_elapsed;

		section_start = ktime_get_ns();
		error = swapz_engine_write_window_batched_read_cap(&ctx->engine,
				ctx->planned + committed,
				count - committed, &succeeded,
				planning_read_cap);
		commit_elapsed = swapz_elapsed_ns(section_start, ktime_get_ns());
		lower_write_elapsed = ctx->lower_write_wall_ns - lower_write_before;
		ctx->window_commit_wall_ns += commit_elapsed;
		if (commit_elapsed >= lower_write_elapsed)
			ctx->window_commit_nonio_wall_ns +=
				commit_elapsed - lower_write_elapsed;
		ctx->engine_plan_wall_ns +=
			ctx->engine.plan_wall_ns - plan_before;
		ctx->engine_pack_wall_ns +=
			ctx->engine.pack_wall_ns - pack_before;
		ctx->engine_publish_wall_ns +=
			ctx->engine.publish_wall_ns - publish_before;
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
			section_start = ktime_get_ns();
			error = swapz_gc_compact_one(ctx);
			ctx->gc_wall_ns +=
				swapz_elapsed_ns(section_start, ktime_get_ns());
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
		error = swapz_issue_flush(ctx);
	if (error && needs_fua)
		swapz_fail(ctx, error);
	for (index = 0; index < count; ++index) {
		struct bio *bio = ctx->batch[ctx->planned_to_batch[index]].bio;

		if (index < committed && !ctx->failed) {
			ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES;
			if (ctx->planned[index].raw)
				ctx->raw_pages++;
			else
				ctx->compressed_pages++;
			swapz_complete(bio, 0);
		} else {
			swapz_complete(bio, error ? error : -EIO);
		}
	}
accounted:
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
	if (count == 1) {
		ctx->one_page_windows++;
		ctx->one_page_close_reasons[close_reason]++;
	}
	ctx->batch_count = 0;
	if (error || committed != count) {
		ctx->retained_chain_completed = 0;
		ctx->pack_close_pending_tail_sample = false;
		ctx->retained_window_read_bypasses = 0;
		ctx->retained_wave_interrupted = false;
		swapz_fail(ctx, error ? error : -EIO);
		return error ? error : -EIO;
	}
	if (chain_continues) {
		unsigned int chain = (unsigned int)ctx->retained_chain_completed + count;

		ctx->retained_chain_completed = (swapz_u8)min_t(
			unsigned int, chain, ctx->max_window);
		ctx->pack_close_pending_tail_sample = packed_close;
	} else {
		ctx->retained_chain_completed = 0;
		ctx->pack_close_pending_tail_sample = false;
	}
	/*
	 * Carry read/fence service across intermediate retained work, but consume
	 * it when PACK_READY closes a refreshed dry tail. That close has already
	 * used the finite wave-tail exception; carrying it farther would fragment
	 * later windows into repeated singleton PACK_READY closes.
	 *
	 * DUPLICATE/FULL are different: they flush an older batch while the
	 * current WRITE itself continues into the next batch, so no-followup does
	 * not mean the retained wave is dry there. Empty flushes returned above
	 * also preserve the existing evidence semantics.
	 */
	if (!ctx->retain_ms || hard_boundary ||
	    (packed_close && !ctx->worker_has_immediate_followup)) {
		ctx->retained_window_read_bypasses = 0;
		ctx->retained_wave_interrupted = false;
	} else if (interrupted_close &&
		   (ctx->worker_has_immediate_followup ||
		    close_reason == SWAPZ_CLOSE_DUPLICATE)) {
		ctx->retained_wave_interrupted = true;
	}
	return 0;
}

static int swapz_raw_write(struct swapz_dm *ctx, struct bio *bio, swapz_u32 logical)
{
	struct swapz_tx tx;
	swapz_u8 completed = 0;
	int error;

	error = swapz_copy_bio_accounted(bio, ctx->input_page, false,
					 &ctx->ordered_write_copy_wall_ns,
					 &ctx->ordered_write_copy_bytes);
	if (error)
		return error;
	error = swapz_stage(&ctx->authority, &logical, 1, 1, &tx);
	if (error == -ENOSPC) {
		/* GC may use input_page, so recopy the still-owned upper BIO
		 * after victim relocation, before writing a raw replacement. */
		error = swapz_gc_compact_one(ctx);
		if (error)
			return error;
		error = swapz_copy_bio_accounted(bio, ctx->input_page, false,
					 &ctx->ordered_write_copy_wall_ns,
					 &ctx->ordered_write_copy_bytes);
		if (error)
			return error;
		error = swapz_stage(&ctx->authority, &logical, 1, 1, &tx);
	}
	if (error)
		return error;
	error = swapz_lower_write(ctx, tx.start_block, 1, ctx->input_page,
				&completed);
	if (!error && completed == 1)
		error = swapz_verify_raw_write(ctx, tx.start_block,
					   ctx->input_page);
	error = swapz_finish_raw(&ctx->authority, &tx, ctx->input_page, completed, error);
	if (!error) {
		ctx->raw_pages++;
		ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES;
	}
	return error;
}

/*
 * Refresh only from BIOs already admitted under queue_lock. This never waits
 * for a future arrival and never moves ownership; it closes the stale-snapshot
 * gap while preparation/copy/LZ4 work was running on the ordered worker.
 */
static void swapz_refresh_accepted_followup(struct swapz_dm *ctx)
{
	unsigned long flags;

	if (ctx->worker_has_immediate_followup)
		return;
	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!list_empty(&ctx->incoming))
		ctx->worker_has_immediate_followup = true;
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	if (ctx->worker_has_immediate_followup) {
		ctx->singleton_deadline_streak = 0;
		ctx->singleton_fast_close = false;
	}
}

static bool swapz_plain_retained_write(const struct bio *bio)
{
	return bio_op(bio) == REQ_OP_WRITE && bio_sectors(bio) &&
		!(bio->bi_opf & (REQ_PREFLUSH | REQ_FUA));
}
static void swapz_sample_pack_tail_locked(struct swapz_dm *ctx,
					  struct list_head *local)
{
	struct swapz_bio_ref *entry;
	swapz_u8 tail = 0;
	swapz_u8 room;
	bool prefix_open = true;

	/*
	 * Sample only after a real PACK_READY lower write. Sampling before the
	 * first lower I/O observes thread-submission gaps rather than a stable
	 * accepted tail and can pin QD8/QD32 to a transient four-record prefix.
	 */
	if (!ctx->pack_close_pending_tail_sample)
		return;
	room = ctx->retained_chain_completed < ctx->max_window ?
		ctx->max_window - ctx->retained_chain_completed : 0;
	/*
	 * local is older than incoming. Count the complete already-admitted FIFO
	 * prefix in that order so asynchronous preparation cannot hide residual
	 * burst width merely because the worker spliced it out of incoming.
	 */
	if (local) {
		list_for_each_entry(entry, local, list) {
			if (!room)
				break;
			if (!swapz_plain_retained_write(entry->bio)) {
				prefix_open = false;
				break;
			}
			tail++;
			room--;
		}
	}
	if (prefix_open && room) {
		list_for_each_entry(entry, &ctx->incoming, list) {
			if (!room || !swapz_plain_retained_write(entry->bio))
				break;
			tail++;
			room--;
		}
	}
	if (tail) {
		ctx->retained_burst_target = swapz_window_grow_burst_target(
			ctx->retained_burst_target, ctx->retained_chain_completed,
			tail, ctx->max_window);
		ctx->retained_tail_target = tail;
	} else {
		ctx->retained_chain_completed = 0;
		ctx->retained_tail_target = 0;
	}
	ctx->pack_close_pending_tail_sample = false;
}

/*
 * The worker-tail path has refreshed both its local FIFO and incoming under
 * queue_lock. It may close any nonempty residue below the learned target only
 * after real synchronous service in this retained chain/window: a prior packed
 * commit or a successful independent read while the window was open.
 *
 * That service interval already gave accepted followers time to queue. If the
 * refreshed FIFO is still dry, burning the remaining retention budget cannot
 * discover already-accepted work. A sampled tail is stronger evidence and
 * must still drain to its one-shot target.
 */
static bool swapz_retained_target_close_ready(struct swapz_dm *ctx)
{
	return swapz_window_burst_close_ready(
		ctx->single_pack_deferred, 0,
		ctx->batch_count, ctx->retained_burst_target,
		ctx->retained_tail_target);
}

/*
 * A serviced useful pack may close below a learned target after the refreshed
 * accepted queue is dry. Tiny mixed/fence residues are a separate bounded
 * exception: read service or a forced mid-burst fence may release only 1..3
 * records. Write-only medium QD8/QD32 therefore cannot cascade into singleton
 * closes merely because an earlier PACK_READY write completed.
 */
static bool swapz_retained_pack_close_ready(struct swapz_dm *ctx)
{
	bool service_proven_dry_pack =
		!ctx->retained_tail_target && ctx->batch_count &&
		(((ctx->retained_chain_completed ||
		   ctx->retained_window_read_bypasses) &&
		  (ctx->single_pack_deferred ||
		   ctx->accepted_burst_pack_ready)) ||
		 ((ctx->retained_window_read_bypasses ||
		   ctx->retained_wave_interrupted) &&
		  ctx->batch_count < 4U));

	return swapz_window_burst_close_ready(
		ctx->single_pack_deferred, service_proven_dry_pack,
		ctx->batch_count, ctx->retained_burst_target,
		ctx->retained_tail_target);
}

static int swapz_accept_write(struct swapz_dm *ctx, struct bio *bio)
{
	swapz_u32 logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	struct swapz_bio_ref *entry = dm_per_bio_data(bio, sizeof(*entry));
	const u8 *input = NULL;
	void *mapped_input = NULL;
	swapz_u8 i;
	u32 payload_crc32c = 0;
	u64 section_start;
	bool inline_zero = false;
	bool payload_crc_valid = false;
	bool raw_staged_in_batch = false;
	bool bulk_raw_eligible = ctx->engine.bulk_enabled &&
				 !ctx->engine.verify_after_write;
	bool prepared_async = ctx->async_prepare && !entry->preparation_inline;
	int length;
	int error;

	for (i = 0; i < ctx->batch_count; ++i)
		if (ctx->batch[i].logical == logical) {
			ctx->next_window_close = SWAPZ_CLOSE_DUPLICATE;
			error = swapz_flush_window(ctx);
			if (error)
				return error;
			break;
		}
	if (ctx->batch_count == ctx->max_window) {
		ctx->next_window_close = SWAPZ_CLOSE_FULL;
		error = swapz_flush_window(ctx);
		if (error)
			return error;
	}

	if (prepared_async) {
		/*
		 * The producer has completed before the ordered worker entered
		 * swapz_process(). Only this worker may consume/release the slot.
		 * The input page and LZ4 work memory belong to the producer.
		 */
		if (entry->preparation_error || !entry->prepared_page)
			return entry->preparation_error ?
				entry->preparation_error : -EIO;
		length = entry->prepared_page->length;
		payload_crc_valid = entry->prepared_page->payload_crc_valid;
		payload_crc32c = entry->prepared_page->payload_crc32c;
		if (length > 0)
			swapz_memcpy_accounted(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				entry->prepared_page->bytes, (size_t)length,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
	} else {
		input = swapz_map_single_bio_input(bio, &mapped_input);
		if (input) {
			ctx->ordered_direct_lz4_pages++;
		} else {
			error = swapz_copy_bio_accounted(
				bio, ctx->input_page, false,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
			if (error)
				return error;
			input = ctx->input_page;
		}
		section_start = ktime_get_ns();
		length = LZ4_compress_fast(input,
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				SWAPZ_BLOCK_BYTES, SWAPZ_MAX_COMPRESSED, 1,
				ctx->lz4_workmem);
		ctx->lz4_wall_ns += swapz_elapsed_ns(section_start,
						   ktime_get_ns());
		if (length > 0 && length <= 64)
			inline_zero = swapz_page_is_zero(input);
		if (length > 0 && !inline_zero) {
			payload_crc32c = swapz_crc32c_accounted(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				(u32)length, &ctx->ordered_crc_wall_ns,
				&ctx->ordered_crc_bytes);
			payload_crc_valid = true;
		}
		/*
		 * If retained bulk RAW admission is available, copy the mapped
		 * upper page exactly once into its durable batch slot before the
		 * temporary mapping goes away. Non-bulk RAW keeps BIO ownership
		 * through swapz_flush_window() and lets swapz_raw_write() perform
		 * its one required copy afterwards.
		 */
		if (length <= 0 && mapped_input && bulk_raw_eligible) {
			swapz_memcpy_accounted(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				input, SWAPZ_BLOCK_BYTES,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
			raw_staged_in_batch = true;
		}
		if (mapped_input)
			kunmap_local(mapped_input);
	}
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
	 * before invalidating this mapping. swapz_discard_page advances its
	 * generation and releases prior liveness without a lower WRITE.
	 * PREFLUSH was already honored in swapz_process(); FUA still requires
	 * the lower flush before this upper BIO completes.
	 */
	if (length > 0 && length <= 64 &&
	    (prepared_async ? entry->prepared_page->zero : inline_zero)) {
		ctx->next_window_close = SWAPZ_CLOSE_ZERO;
		error = swapz_flush_window(ctx);
		if (!error)
			error = swapz_discard_page(&ctx->authority, logical);
		if (!error && (bio->bi_opf & REQ_FUA))
			error = swapz_issue_flush(ctx);
		if (error) {
			swapz_fail(ctx, error);
		} else {
			ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES;
			ctx->zero_elided_pages++;
		}
		swapz_complete(bio, error);
		return 0;
	}
	if (length <= 0 && bulk_raw_eligible) {
		/* Preserve the complete original 4KiB page in worker-owned
		 * staging. Admission and FUA ordering match compressed BIOs;
		 * CRC authority is published only after the shared lower write. */
		if (prepared_async)
			swapz_memcpy_accounted(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				entry->prepared_page->bytes, SWAPZ_BLOCK_BYTES,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
		else if (!raw_staged_in_batch)
			swapz_memcpy_accounted(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				ctx->input_page, SWAPZ_BLOCK_BYTES,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
		swapz_release_prepared(bio);
		swapz_window_admit_clock(ctx);
		ctx->batch[ctx->batch_count++] = (struct swapz_pending_bio) {
			.bio = bio,
			.logical = logical,
			.length = SWAPZ_BLOCK_BYTES,
			.payload_crc_valid = 0,
			.raw = 1,
		};
		if (bio->bi_opf & REQ_FUA) {
			ctx->next_window_close = SWAPZ_CLOSE_FUA;
			swapz_flush_window(ctx);
		}
		return 0;
	}
	if (length <= 0) {
		ctx->next_window_close = SWAPZ_CLOSE_RAW;
		error = swapz_flush_window(ctx);
		if (error)
			return error;
		error = swapz_raw_write(ctx, bio, logical);
		if (!error && (bio->bi_opf & REQ_FUA))
			error = swapz_issue_flush(ctx);
		if (error)
			swapz_fail(ctx, error);
		swapz_complete(bio, error);
		return 0;
	}

	/* batch_bytes now owns an immutable copy; release producer capacity
	 * before waiting for a packed window's synchronous lower I/O. */
	swapz_release_prepared(bio);
	swapz_window_admit_clock(ctx);
	ctx->batch[ctx->batch_count] = (struct swapz_pending_bio) {
		.bio = bio,
		.logical = logical,
		.payload_crc32c = payload_crc32c,
		.length = (swapz_u16)length,
		.payload_crc_valid = payload_crc_valid,
	};
	ctx->batch_count++;
	/*
	 * Compression/preparation can take long enough for another upper BIO
	 * to reach ->map after the worker's initial queue snapshot. Refresh the
	 * already-admitted tail before deciding that a useful pack is isolated.
	 */
	if (!(bio->bi_opf & REQ_FUA) && ctx->retain_ms)
		swapz_refresh_accepted_followup(ctx);
	/* FUA remains an immediate drained, lower-flushed fence. */
	if (bio->bi_opf & REQ_FUA) {
		ctx->next_window_close = SWAPZ_CLOSE_FUA;
		swapz_flush_window(ctx);
	} else {
		if (swapz_window_single_pack_ready(ctx->batch, ctx->batch_count,
				ctx->retain_ms, ctx->engine.max_read_blocks_per_record) &&
		    !ctx->single_pack_deferred) {
			ctx->single_pack_deferred = true;
			ctx->single_pack_deferrals++;
		}
		if (swapz_window_pack_ready(ctx->batch, ctx->batch_count,
				ctx->retain_ms, ctx->engine.max_read_blocks_per_record) &&
		    !ctx->accepted_burst_pack_ready) {
			ctx->accepted_burst_pack_ready = true;
			ctx->accepted_burst_extensions++;
		}
		/*
		 * Target closure is safe in admission only after refreshing the
		 * accepted queue above. Below-target service-proven closure remains a
		 * worker-tail decision after local+incoming have been refreshed.
		 */
		if (swapz_retained_target_close_ready(ctx) &&
		    !ctx->worker_has_immediate_followup) {
			ctx->next_window_close = SWAPZ_CLOSE_PACK_READY;
			ctx->packed_early_commits++;
			if (ctx->accepted_burst_pack_ready)
				ctx->accepted_burst_tail_flushes++;
			swapz_flush_window(ctx);
		}
	}
	return 0;
}

static int swapz_read(struct swapz_dm *ctx, struct bio *bio)
{
	swapz_u32 logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	const struct swapz_map *map = &ctx->maps[logical];
	swapz_u16 payload_bytes = 0;
	u64 section_start;
	int error, decompressed;

	if (!map->valid) {
		memset(ctx->read_page, 0, SWAPZ_BLOCK_BYTES);
	} else if (map->raw) {
		if (map->extent_blocks != 1 ||
		    map->start_block >= ctx->physical_blocks)
			return -EUCLEAN;
		error = swapz_lower_read(ctx, map->start_block, 1, ctx->read_page);
		if (error)
			return error;
		error = swapz_verify_raw(&ctx->authority, logical, ctx->read_page);
		if (error)
			return error;
	} else {
		u64 lower_read_before = ctx->lower_read_wall_ns;
		u64 read_engine_start = ktime_get_ns();
		u64 read_engine_elapsed;
		u64 lower_read_elapsed;

		error = swapz_engine_read_page(&ctx->engine, logical,
				ctx->read_compressed, SWAPZ_BLOCK_BYTES,
				&payload_bytes);
		read_engine_elapsed =
			swapz_elapsed_ns(read_engine_start, ktime_get_ns());
		lower_read_elapsed = ctx->lower_read_wall_ns - lower_read_before;
		if (read_engine_elapsed >= lower_read_elapsed)
			ctx->read_engine_nonio_wall_ns +=
				read_engine_elapsed - lower_read_elapsed;
		if (error)
			return error;
		section_start = ktime_get_ns();
		decompressed = LZ4_decompress_safe(ctx->read_compressed,
						  ctx->read_page,
						  payload_bytes,
						  SWAPZ_BLOCK_BYTES);
		ctx->decode_wall_ns +=
			swapz_elapsed_ns(section_start, ktime_get_ns());
		if (decompressed != SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	}
	error = swapz_copy_bio_accounted(bio, ctx->read_page, true,
					 &ctx->read_copy_wall_ns,
					 &ctx->read_copy_bytes);
	if (!error)
		ctx->logical_read_bytes += SWAPZ_BLOCK_BYTES;
	return error;
}

static int swapz_discard(struct swapz_dm *ctx, struct bio *bio)
{
	sector_t sector = bio->bi_iter.bi_sector;
	sector_t remaining = bio_sectors(bio);
	int error;

	if (sector % SWAPZ_SECTORS || remaining % SWAPZ_SECTORS ||
	    sector / SWAPZ_SECTORS >= ctx->logical_pages ||
	    remaining / SWAPZ_SECTORS >
			ctx->logical_pages - sector / SWAPZ_SECTORS)
		return -ERANGE;
	/*
	 * The discard must be all-or-nothing on any detectable mapping,
	 * generation or liveness corruption. Validate every affected logical
	 * page before changing even the first generation or refcount.
	 */
	{
		sector_t check_sector = sector;
		sector_t check_remaining = remaining;
		swapz_u32 epoch = ++ctx->discard_serial;

		if (!epoch) {
			memset(ctx->discard_epoch, 0,
			       (size_t)ctx->physical_blocks *
			       sizeof(*ctx->discard_epoch));
			epoch = ++ctx->discard_serial;
		}
		while (check_remaining) {
			swapz_u32 logical = (swapz_u32)(check_sector / SWAPZ_SECTORS);
			const struct swapz_map *m = &ctx->maps[logical];

			if (m->generation == ~(swapz_u32)0)
				return -EOVERFLOW;
			if (m->valid) {
				swapz_u32 start = m->start_block;

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
			check_sector += SWAPZ_SECTORS;
			check_remaining -= SWAPZ_SECTORS;
		}
	}
	while (remaining) {
		error = swapz_discard_page(&ctx->authority,
				       (swapz_u32)(sector / SWAPZ_SECTORS));
		if (error)
			return error;
		ctx->discard_pages++;
		sector += SWAPZ_SECTORS;
		remaining -= SWAPZ_SECTORS;
	}
	return 0;
}

static bool swapz_retention_expired(struct swapz_dm *ctx);

static bool swapz_read_is_independent(struct swapz_dm *ctx, struct bio *bio)
{
	swapz_u32 logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	bool blocked = !READ_ONCE(ctx->accepting) || ctx->failed ||
		ctx->authority.in_flight || ctx->authority.batch_pending ||
		(bio->bi_opf & (REQ_PREFLUSH | REQ_FUA));

	return swapz_window_read_independent(ctx->batch, ctx->batch_count,
					 logical, ctx->retain_ms, blocked);
}

static void swapz_process(struct swapz_dm *ctx, struct bio *bio)
{
	int error = 0;
	const enum req_op op = bio_op(bio);

	/* Invalidate even when a discard/flush changes authority without
	 * writing any lower blocks. READ-only runs may reuse one metadata page. */
	if (op != REQ_OP_READ || (bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)))
		swapz_engine_invalidate_read_cache(&ctx->engine);
	if (ctx->failed) {
		swapz_complete(bio, ctx->last_error ? ctx->last_error : -EIO);
		return;
	}
	/* Future arrivals never refresh the retention budget. Expiry bounds
	 * idle waiting, not finite already-accepted work or synchronous service
	 * of an independent read. Let accepted work reach the existing
	 * pack/order gates before applying the remaining idle budget. */
	if (ctx->batch_count && ctx->retain_ms &&
	    !ctx->worker_has_immediate_followup &&
	    swapz_retention_expired(ctx)) {
		ctx->next_window_close = SWAPZ_CLOSE_DEADLINE;
		ctx->deadline_before_bio++;
		error = swapz_flush_window(ctx);
		if (error) {
			swapz_complete(bio, error);
			return;
		}
	}
	/* Only the opt-in retained stream can service a disjoint READ from
	 * committed authority. Read scratch is separate from batch_bytes;
	 * one worker still owns every mapping and all lower I/O. */
	if (op == REQ_OP_READ && swapz_read_is_independent(ctx, bio)) {
		u64 read_start_ns = ktime_get_ns();

		error = swapz_read(ctx, bio);
		if (error) {
			swapz_fail(ctx, error);
			ctx->next_window_close = SWAPZ_CLOSE_OTHER;
			/* Abort pending owners without submitting their data. */
			swapz_flush_window(ctx);
		}
		if (!error) {
			u64 read_end_ns = ktime_get_ns();

			/* BIOs may have arrived while synchronous lower READ I/O ran. */
			swapz_refresh_accepted_followup(ctx);
			ctx->retained_read_bypasses++;
			if (ctx->retained_window_read_bypasses < SWAPZ_MAX_RECORDS)
				ctx->retained_window_read_bypasses++;
			/*
			 * Retention measures time available for companion writes, not
			 * synchronous service of an unrelated committed read. Shift the
			 * pinned origin by exactly that service interval; because the
			 * open window predates this read, the resulting deadline remains
			 * bounded by read_end_ns + retain_ms and future arrivals cannot
			 * refresh it. An already-armed old hrtimer may wake early; the
			 * worker rechecks this shifted origin before closing/rearming.
			 */
			if (ctx->window_first_ns && read_end_ns > read_start_ns) {
				u64 read_elapsed = read_end_ns - read_start_ns;

				if (ctx->window_first_ns <= read_start_ns)
					ctx->window_first_ns += read_elapsed;
				else
					ctx->window_first_ns = read_end_ns;
			}
		}
		swapz_complete(bio, error);
		/* A successful independent read is already authoritative.
		 * Do not add an unrelated lower WRITE's latency/error to its
		 * completion. A slow read may cross the pinned deadline, but
		 * already-accepted follow-up work is finite and must not be
		 * fragmented merely because the ordered worker serviced that read. */
		if (!error && !ctx->worker_has_immediate_followup &&
		    swapz_retention_expired(ctx)) {
			ctx->next_window_close = SWAPZ_CLOSE_DEADLINE;
			ctx->deadline_after_read++;
			swapz_flush_window(ctx);
		}
		return;
	}
	/* Dependencies and barriers drain in original admission order. */
	if (op != REQ_OP_WRITE || (bio->bi_opf & REQ_PREFLUSH)) {
		if (bio->bi_opf & REQ_PREFLUSH) {
			ctx->next_window_close = SWAPZ_CLOSE_PREFLUSH;
		} else if (op == REQ_OP_READ) {
			swapz_u32 logical = (swapz_u32)(bio->bi_iter.bi_sector /
						      SWAPZ_SECTORS);
			swapz_u8 index;

			ctx->next_window_close = SWAPZ_CLOSE_READ_UNRELATED;
			for (index = 0; index < ctx->batch_count; ++index) {
				if (ctx->batch[index].logical == logical) {
					ctx->next_window_close = SWAPZ_CLOSE_READ_CONFLICT;
					break;
				}
			}
		} else if (op == REQ_OP_DISCARD) {
			ctx->next_window_close = SWAPZ_CLOSE_DISCARD;
		} else {
			ctx->next_window_close = SWAPZ_CLOSE_OTHER;
		}
		error = swapz_flush_window(ctx);
		if (error) {
			swapz_complete(bio, error);
			return;
		}
	}
	if (bio->bi_opf & REQ_PREFLUSH) {
		error = swapz_issue_flush(ctx);
		if (error) {
			swapz_fail(ctx, error);
			swapz_complete(bio, error);
			return;
		}
		if (op == REQ_OP_WRITE && !bio_sectors(bio)) {
			swapz_complete(bio, 0);
			return;
		}
	}
	switch (op) {
	case REQ_OP_WRITE:
		/* A write BIO is completed by raw_write or flush_window. */
		error = swapz_accept_write(ctx, bio);
		if (error)
			swapz_complete(bio, error);
		return;
	case REQ_OP_READ:
		error = swapz_read(ctx, bio);
		if (!error && ctx->retain_ms) {
			/* A READ with no open batch can still spend real synchronous
			 * service time while later writes become accepted. Carry that
			 * evidence only when such a finite follower now exists. */
			swapz_refresh_accepted_followup(ctx);
			if (ctx->worker_has_immediate_followup &&
			    ctx->retained_window_read_bypasses < SWAPZ_MAX_RECORDS)
				ctx->retained_window_read_bypasses++;
		}
		break;
	case REQ_OP_DISCARD:
		error = swapz_discard(ctx, bio);
		break;
	default:
		error = -EOPNOTSUPP;
		break;
	}
	if (error && error != -EOPNOTSUPP)
		swapz_fail(ctx, error);
	swapz_complete(bio, error);
}

/*
 * Normal operation: a finite quantum keeps write ownership and CPU
 * latency bounded, with older queued BIOs ahead of new admissions.
 * Presuspend: admission is closed under queue_lock, so the same worker
 * may finish ALL previously accepted BIOs without building a potentially
 * unbounded chain of requeued delayed works during drain_workqueue().
 */
/* The first staged record pins a finite absolute window deadline.
 * Computing the remaining time on each rearm avoids extending it when
 * additional incoming writes arrive before the next worker invocation.
 * All calls are from the one serialized worker, never the ->map path. */
static bool swapz_retention_expired(struct swapz_dm *ctx)
{
	return swapz_window_retention_expired(ctx->window_first_ns,
					    ktime_get_ns(), ctx->retain_ms);
}

static enum hrtimer_restart swapz_retention_wake(struct hrtimer *timer)
{
	struct swapz_dm *ctx = container_of(timer, struct swapz_dm, retention_timer);
	unsigned long flags;

	/* No batch/map accesses or sleeping I/O in timer context. The same
	 * admission lock prevents a wake from racing past suspend/free. */
	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (ctx->accepting)
		mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	return HRTIMER_NORESTART;
}

static void swapz_worker(struct work_struct *work)
{
	struct swapz_dm *ctx =
		container_of(to_delayed_work(work), struct swapz_dm, worker);
	LIST_HEAD(local);
	struct swapz_bio_ref *entry;
	unsigned long flags;
	unsigned int remaining;
	u64 cpu_start_ns = swapz_current_task_cpu_ns();

	for (;;) {
		remaining = SWAPZ_WORK_QUANTUM_BIOS;
		spin_lock_irqsave(&ctx->queue_lock, flags);
		list_splice_init(&ctx->incoming, &local);
		/*
		 * A finite accepted wave with at least two unclaimed WRITE
		 * preparations is direct FIFO-distance evidence: the ordered worker
		 * owns the head while a distinct tail exists for the producer.
		 * Start one tail credit before processing the head so QD4/QD8 can
		 * overlap LZ4 immediately. The producer still preserves one FIFO head
		 * via its singular-list guard, and no future-arrival wait is added.
		 */
		if (ctx->async_prepare &&
		    !list_empty(&ctx->preparation_incoming) &&
		    !list_is_singular(&ctx->preparation_incoming)) {
			atomic_set(&ctx->preparation_tail_credit, 1);
			ctx->preparation_wave_kicks++;
			queue_work(ctx->preparation_workqueue,
				   &ctx->preparation_worker);
		}
		spin_unlock_irqrestore(&ctx->queue_lock, flags);

		while (remaining && !list_empty(&local)) {
			bool wait_for_preparation = false;
			bool inline_preparation = false;

			entry = list_first_entry(&local, struct swapz_bio_ref, list);
			/*
			 * The two queues share queue_lock. If the bounded producer has
			 * not claimed this FIFO entry yet, the ordered worker may steal
			 * only that unstarted preparation and compress it inline with its
			 * own scratch/workmem. If the producer already removed it, retain
			 * the original completion handoff and never touch its scratch.
			 */
			if (ctx->async_prepare && bio_op(entry->bio) == REQ_OP_WRITE &&
			    bio_sectors(entry->bio)) {
				wait_for_preparation = true;
				spin_lock_irqsave(&ctx->queue_lock, flags);
				/*
				 * Reserve this FIFO head under the same lock used by producer
				 * claim. A successful inline steal grants exactly one
				 * opposite-end producer claim while this BIO executes. Do not
				 * erase an accepted-wave starter credit before the producer has
				 * had a chance to consume it.
				 */
				if (!list_empty(&entry->preparation_list)) {
					list_del_init(&entry->preparation_list);
					entry->preparation_inline = true;
					inline_preparation = true;
					wait_for_preparation = false;
					ctx->preparation_ordered_inline++;
					atomic_set(&ctx->preparation_tail_credit, 1);
					if (!list_empty(&ctx->preparation_incoming))
						queue_work(ctx->preparation_workqueue,
							   &ctx->preparation_worker);
				} else {
					/* This head is already producer-owned. It cannot earn a
					 * second tail claim until ordered work resumes inline. */
					atomic_set(&ctx->preparation_tail_credit, 0);
					ctx->preparation_ordered_handoffs++;
				}
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				if (wait_for_preparation) {
					u64 wait_start = 0;

					if (!completion_done(&entry->preparation_finished)) {
						ctx->preparation_ordered_waits++;
						wait_start = ktime_get_ns();
					}
					wait_for_completion(&entry->preparation_finished);
					if (wait_start)
						ctx->preparation_ordered_wait_wall_ns +=
							swapz_elapsed_ns(wait_start,
								       ktime_get_ns());
				}
			} else if (ctx->async_prepare) {
				/*
				 * A READ/barrier can also provide real ordered service time.
				 * Permit one future WRITE preparation during that BIO, but never
				 * let the producer chain through the rest of the FIFO.
				 */
				spin_lock_irqsave(&ctx->queue_lock, flags);
				atomic_set(&ctx->preparation_tail_credit, 1);
				if (!list_empty(&ctx->preparation_incoming))
					queue_work(ctx->preparation_workqueue,
						   &ctx->preparation_worker);
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
			} else {
				atomic_set(&ctx->preparation_tail_credit, 0);
			}
			ctx->worker_has_immediate_followup =
				entry->list.next != &local;
			swapz_refresh_accepted_followup(ctx);
			list_del_init(&entry->list);
			swapz_process(ctx, entry->bio);
			/*
			 * An inline WRITE earns one producer token. Keep an unconsumed
			 * token across the inter-BIO gap only while this worker still owns
			 * an open retained window. A nonempty flush clears it in
			 * swapz_flush_window(); all other paths expire it here.
			 *
			 * Use the local flag: swapz_process() may complete the BIO, so the
			 * dm_per_bio_data entry must not be dereferenced afterwards.
			 */
			if (!inline_preparation || !ctx->retain_ms ||
			    !ctx->batch_count || ctx->singleton_fast_close ||
			    ctx->failed || !READ_ONCE(ctx->accepting))
				atomic_set(&ctx->preparation_tail_credit, 0);

			/*
			 * If this was the local tail, BIOs may have been admitted while
			 * swapz_process() copied/compressed the page. Consume only those
			 * already present now, append them in FIFO order, and stay within
			 * the same hard 64-BIO quantum. There is no wait for future work.
			 */
			if (remaining > 1U && list_empty(&local)) {
				spin_lock_irqsave(&ctx->queue_lock, flags);
				swapz_sample_pack_tail_locked(ctx, &local);
				if (!list_empty(&ctx->incoming)) {
					list_splice_tail_init(&ctx->incoming, &local);
					ctx->worker_has_immediate_followup = true;
				}
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				if (ctx->worker_has_immediate_followup) {
					ctx->singleton_deadline_streak = 0;
					ctx->singleton_fast_close = false;
				}
			}
			if (swapz_retained_pack_close_ready(ctx) &&
			    !ctx->worker_has_immediate_followup &&
			    ctx->batch_count && !ctx->failed &&
			    READ_ONCE(ctx->accepting) &&
			    !swapz_retention_expired(ctx)) {
				ctx->next_window_close = SWAPZ_CLOSE_PACK_READY;
				ctx->packed_early_commits++;
				if (ctx->accepted_burst_pack_ready)
					ctx->accepted_burst_tail_flushes++;
				swapz_flush_window(ctx);
			}
			ctx->worker_has_immediate_followup = false;
			if (!(remaining & 7U))
				cond_resched();
			remaining--;
		}
		/*
		 * Opt-in 3B: a pending window retains worker-owned copies
		 * and upper BIO ownership across quanta ONLY until the
		 * pinned deadline. Dependencies and barriers drain before
		 * observing older writes; disjoint reads use committed maps.
		 */
		if (ctx->batch_count &&
		    (!ctx->retain_ms || ctx->failed ||
		     !READ_ONCE(ctx->accepting) ||
		     ctx->batch_count >= ctx->max_window ||
		     swapz_retention_expired(ctx))) {
			if (!READ_ONCE(ctx->accepting))
				ctx->next_window_close = SWAPZ_CLOSE_SHUTDOWN;
			else if (ctx->retain_ms &&
				 ctx->batch_count >= ctx->max_window)
				ctx->next_window_close = SWAPZ_CLOSE_FULL;
			else if (ctx->retain_ms &&
				 swapz_retention_expired(ctx)) {
				ctx->next_window_close = SWAPZ_CLOSE_DEADLINE;
				if (!list_empty(&local)) {
					ctx->deadline_worker_with_local++;
					ctx->singleton_deadline_streak = 0;
					ctx->singleton_fast_close = false;
				} else {
					ctx->deadline_worker_empty++;
					if (ctx->batch_count == 1U) {
						if (ctx->singleton_deadline_streak <
						    SWAPZ_SINGLETON_DEADLINE_STREAK)
							ctx->singleton_deadline_streak++;
						if (ctx->singleton_deadline_streak >=
						    SWAPZ_SINGLETON_DEADLINE_STREAK)
							ctx->singleton_fast_close = true;
					} else {
						ctx->singleton_deadline_streak = 0;
						ctx->singleton_fast_close = false;
						if ((ctx->single_pack_deferred ||
						     ctx->accepted_burst_pack_ready) &&
						    !ctx->retained_tail_target &&
						    !ctx->retained_chain_completed)
							ctx->retained_burst_target =
								swapz_window_shrink_burst_target(
									ctx->retained_burst_target,
									ctx->batch_count);
					}
				}
			} else {
				ctx->next_window_close = !remaining ?
					SWAPZ_CLOSE_QUANTUM : SWAPZ_CLOSE_IDLE;
			}
			swapz_flush_window(ctx);
		} else if (ctx->batch_count) {
			ctx->retain_worker_passes++;
		}

		spin_lock_irqsave(&ctx->queue_lock, flags);
		swapz_sample_pack_tail_locked(ctx, &local);
		if (!list_empty(&local))
			list_splice_init(&local, &ctx->incoming);
		if (list_empty(&ctx->incoming)) {
			/*
			 * With no pending retained window and no accepted FIFO work, this
			 * invocation has reached a real burst boundary. Do not let read or
			 * forced-fence service evidence leak into a later unrelated wave.
			 */
			if (!ctx->batch_count) {
				ctx->retained_window_read_bypasses = 0;
				ctx->retained_wave_interrupted = false;
				ctx->retained_chain_completed = 0;
				ctx->retained_tail_target = 0;
				ctx->pack_close_pending_tail_sample = false;
			}
			/*
			 * Once repeated full-deadline singleton closes prove that no
			 * companion work arrives, stop charging the same closed-loop
			 * stream another retention deadline. This changes no lower byte
			 * geometry: a one-record window already occupies one 4KiB block.
			 * Any accepted concurrency above clears the learned bypass.
			 */
			if (ctx->accepting && !ctx->failed &&
			    ctx->singleton_fast_close && ctx->batch_count == 1U &&
			    ctx->retain_ms && !swapz_retention_expired(ctx)) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				ctx->next_window_close = SWAPZ_CLOSE_IDLE;
				swapz_flush_window(ctx);
				swapz_account_worker_cpu(&ctx->ordered_worker_cpu_ns,
							cpu_start_ns);
				return;
			}
			if (ctx->batch_count &&
			    swapz_window_timer_enabled(ctx->retain_ms) &&
			    ctx->accepting && !ctx->failed) {
				/* The first record pins the deadline. A queued
				 * timer already carries that identical expiry;
				 * avoid hrtimer_start() when later BIOs cause
				 * another empty-queue worker pass. The callback
				 * may have dequeued; in that case safely rearm
				 * at the SAME pinned deadline. All decisions
				 * here are under admission queue_lock. */
				if (swapz_retention_timer_needs_arm(ctx->retain_ms,
					hrtimer_is_queued(&ctx->retention_timer))) {
					ctx->retain_timer_arms++;
					hrtimer_start(&ctx->retention_timer,
						ns_to_ktime(ctx->window_first_ns +
							(u64)ctx->retain_ms * 1000000ULL),
						HRTIMER_MODE_ABS);
				} else {
					ctx->retain_timer_arm_skips++;
				}
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				swapz_account_worker_cpu(&ctx->ordered_worker_cpu_ns,
							cpu_start_ns);
				return;
			}
			if (ctx->batch_count && !ctx->accepting) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				ctx->next_window_close = SWAPZ_CLOSE_SHUTDOWN;
				swapz_flush_window(ctx);
				swapz_account_worker_cpu(&ctx->ordered_worker_cpu_ns,
							cpu_start_ns);
				return;
			}
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			swapz_account_worker_cpu(&ctx->ordered_worker_cpu_ns,
						cpu_start_ns);
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
			swapz_account_worker_cpu(&ctx->ordered_worker_cpu_ns,
						cpu_start_ns);
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

static int swapz_map(struct dm_target *ti, struct bio *bio)
{
	struct swapz_dm *ctx = ti->private;
	struct swapz_bio_ref *entry;
	unsigned long flags;
	sector_t sector = bio->bi_iter.bi_sector;
	sector_t count = bio_sectors(bio);

	if (!READ_ONCE(ctx->accepting))
		return DM_MAPIO_KILL;
	if (bio_op(bio) == REQ_OP_READ || bio_op(bio) == REQ_OP_WRITE) {
		if ((bio_op(bio) == REQ_OP_WRITE && !count &&
		     (bio->bi_opf & REQ_PREFLUSH))) {
			/* empty flush represented as PREFLUSH|WRITE */
		} else if (sector % SWAPZ_SECTORS || count != SWAPZ_SECTORS ||
			   sector / SWAPZ_SECTORS >= ctx->logical_pages) {
			return DM_MAPIO_KILL;
		}
	} else if (bio_op(bio) == REQ_OP_DISCARD) {
		if (sector % SWAPZ_SECTORS || count % SWAPZ_SECTORS ||
		    sector / SWAPZ_SECTORS >= ctx->logical_pages ||
		    count / SWAPZ_SECTORS >
				ctx->logical_pages - sector / SWAPZ_SECTORS)
			return DM_MAPIO_KILL;
	} else {
		/* A REQ_OP_FLUSH upper BIO is invalid on Linux: blk-core
		 * rejects it before dm's ->map. The real empty-flush
		 * protocol is WRITE|PREFLUSH with zero sectors. */
		return DM_MAPIO_KILL;
	}
	entry = dm_per_bio_data(bio, sizeof(*entry));
	INIT_LIST_HEAD(&entry->list);
	INIT_LIST_HEAD(&entry->preparation_list);
	entry->prepared_page = NULL;
	entry->preparation_inline = false;
	entry->preparation_pool = ctx->preparation_pool;
	entry->preparation_slots = &ctx->preparation_slots;
	entry->preparation_error = 0;
	if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count)
		init_completion(&entry->preparation_finished);
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
	if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count) {
		/*
		 * A cold lone head belongs to the ordered worker first. A retained
		 * inline WRITE may leave one earned tail token alive after that worker
		 * goes idle; the next admitted companion can therefore wake the
		 * producer without reading worker-owned batch_count. A real lower
		 * WRITE remains the independent head-first overlap signal.
		 */
		list_add_tail(&entry->preparation_list,
			      &ctx->preparation_incoming);
		if (atomic_read(&ctx->lower_write_active) ||
		    atomic_read(&ctx->preparation_tail_credit))
			queue_work(ctx->preparation_workqueue,
				   &ctx->preparation_worker);
	}
	/*
	 * Urgent dependencies wake the ordered worker immediately. Retained
	 * writes also enter it immediately because their bounded wait begins
	 * only after preparation. With retention disabled, preserve the prior
	 * coalesce=0 behavior: queue one immediate finite worker instance and
	 * let additional writes join while that instance is pending/running.
	 */
	if (bio_op(bio) != REQ_OP_WRITE ||
	    (bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)) ||
	    !bio_sectors(bio) || ctx->retain_ms)
		mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
	else
		queue_delayed_work(ctx->workqueue, &ctx->worker, 0);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	return DM_MAPIO_SUBMITTED;
}

static void swapz_drain(struct dm_target *ti)
{
	struct swapz_dm *ctx = ti->private;

	unsigned long flags;

	spin_lock_irqsave(&ctx->queue_lock, flags);
	WRITE_ONCE(ctx->accepting, false);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	/* The callback takes queue_lock. Close admission first, then cancel
	 * outside that lock before waiting for any worker or freeing it. */
	hrtimer_cancel(&ctx->retention_timer);
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
	/* The ordered worker frees prepared slots in FIFO order, allowing
	 * even a full producer queue to drain. Do not destroy either queue
	 * until every admitted BIO has reached its sole completion owner. */
	if (ctx->preparation_workqueue)
		drain_workqueue(ctx->preparation_workqueue);
	flush_delayed_work(&ctx->worker);
	drain_workqueue(ctx->workqueue);
	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!list_empty(&ctx->incoming) ||
	    !list_empty(&ctx->preparation_incoming) || ctx->batch_count ||
	    ctx->authority.batch_pending || ctx->authority.in_flight) {
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		DMERR("swapz drain invariant: accepted BIOs remain after draining");
		swapz_fail(ctx, -EUCLEAN);
	} else {
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
	}
	/* Every admitted BIO was queued under the same lock before this drain. */
	if (!ctx->failed) {
		int error = swapz_issue_flush(ctx);

		if (error)
			swapz_fail(ctx, error);
	}
}

static void swapz_resume(struct dm_target *ti)
{
	struct swapz_dm *ctx = ti->private;
	unsigned long flags;

	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!ctx->failed)
		WRITE_ONCE(ctx->accepting, true);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
}

static void swapz_free(struct swapz_dm *ctx)
{
	if (!ctx)
		return;
	hrtimer_cancel(&ctx->retention_timer);
	if (ctx->workqueue) {
		/* The constructor-failure path has no accepted BIOs.
		 * The live teardown path already closed admission and drained
		 * every chained work item before arriving here. */
		cancel_delayed_work_sync(&ctx->worker);
		drain_workqueue(ctx->workqueue);
		destroy_workqueue(ctx->workqueue);
	}
	if (ctx->preparation_workqueue) {
		cancel_work_sync(&ctx->preparation_worker);
		drain_workqueue(ctx->preparation_workqueue);
		destroy_workqueue(ctx->preparation_workqueue);
	}
	if (ctx->preparation_pool)
		mempool_destroy(ctx->preparation_pool);
	kfree(ctx->preparation_lz4_workmem);
	vfree(ctx->preparation_input_page);
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
	vfree(ctx->engine.read_metadata_cache);
	vfree(ctx->engine.bulk_scratch);
	kvfree(ctx->engine.bulk_txs);
	kfree(ctx->lz4_workmem);
	kfree(ctx);
}

static void swapz_dtr(struct dm_target *ti)
{
	struct swapz_dm *ctx = ti->private;

	if (!ctx)
		return;
	swapz_drain(ti);
	swapz_free(ctx);
	ti->private = NULL;
}

static int swapz_ctr(struct dm_target *ti, unsigned int argc, char **argv)
{
	struct swapz_dm *ctx;
	u64 logical, physical;
	u32 budget = 0, window = SWAPZ_MAX_RECORDS, verify = 0;
	u32 gc_policy = 2, flush_fail_nth = 0;
	u32 lower_bulk = 1, write_fail_nth = 0, retain = 0;
	int error;

	if (argc < 1 || argc > 9 || ti->len % SWAPZ_SECTORS) {
		ti->error = "Usage: <owned null_blk backing> [read_blocks 0..3] [window 1..64] [verify 0|1] [gc 0=count|1=bytes|2=io] [test_fail_flush_nth 0..64] [lower_bulk 0=off|1=adjacent|2=allow-padding] [test_fail_write_nth 0..65535] [retain_ms 0..4]";
		return -EINVAL;
	}
	if (argc > 1 && (kstrtou32(argv[1], 10, &budget) || budget > 3))
		return -EINVAL;
	if (argc > 2 && (kstrtou32(argv[2], 10, &window) ||
			 window < 1 || window > SWAPZ_MAX_RECORDS))
		return -EINVAL;
	if (argc > 3 && (kstrtou32(argv[3], 10, &verify) || verify > 1U))
		return -EINVAL;
	if (argc > 4 && (kstrtou32(argv[4], 10, &gc_policy) ||
			 gc_policy > 2U))
		return -EINVAL;
	/* Fault injection is test-only and restricted by the same null_blk
	 * admission guard as all loaded swapz I/O. */
	if (argc > 5 && (kstrtou32(argv[5], 10, &flush_fail_nth) ||
			 flush_fail_nth > 64U))
		return -EINVAL;
	if (argc > 6 && (kstrtou32(argv[6], 10, &lower_bulk) ||
			 lower_bulk > 2U))
		return -EINVAL;
	/* Nth synchronous lower WRITE attempt, regardless of foreground/GC.
	 * It fails BEFORE dm_io, for isolated fail-closed protocol testing. */
	if (argc > 7 && (kstrtou32(argv[7], 10, &write_fail_nth) ||
			 write_fail_nth > 65535U))
		return -EINVAL;
	if (argc > 8 && (kstrtou32(argv[8], 10, &retain) ||
			 retain > SWAPZ_MAX_RETAIN_MS))
		return -EINVAL;
	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ti->private = ctx;
	ctx->target = ti;
	ctx->max_window = (swapz_u8)window;
	ctx->retained_burst_target =
		swapz_window_initial_burst_target(ctx->max_window);
	ctx->gc_cost_policy = gc_policy;
	ctx->retain_ms = retain;
	ctx->flush_meter.fail_nth = flush_fail_nth;
	ctx->write_fault_nth = write_fail_nth;
	ctx->engine.max_read_blocks_per_record = (swapz_u8)budget;
	ctx->engine.verify_after_write = verify;
	ctx->engine.bulk_enabled = lower_bulk;
	ctx->async_prepare = swapz_async_prepare;
	spin_lock_init(&ctx->queue_lock);
	INIT_LIST_HEAD(&ctx->incoming);
	INIT_LIST_HEAD(&ctx->preparation_incoming);
	INIT_DELAYED_WORK(&ctx->worker, swapz_worker);
	INIT_WORK(&ctx->preparation_worker, swapz_preparation_worker);
	sema_init(&ctx->preparation_slots, SWAPZ_MAX_RECORDS);
	atomic_set(&ctx->lower_write_active, 0);
	atomic_set(&ctx->preparation_tail_credit, 0);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 13, 0)
	hrtimer_setup(&ctx->retention_timer, swapz_retention_wake,
		      CLOCK_MONOTONIC, HRTIMER_MODE_ABS);
#else
	hrtimer_init(&ctx->retention_timer, CLOCK_MONOTONIC, HRTIMER_MODE_ABS);
	ctx->retention_timer.function = swapz_retention_wake;
#endif

	error = dm_get_device(ti, argv[0], dm_table_get_mode(ti->table),
			      &ctx->backing);
	if (error) {
		ti->error = "Cannot open swapz dedicated backing device";
		goto fail;
	}
	/*
	 * Alpha device admission is intentionally stricter than user
	 * authorization. Only an owned, RAM-backed null_blk node may become
	 * a live swapz target before fault/reclaim qualification; a physical
	 * SD, HDD or SSD partition must never be selected accidentally.
	 * Device ownership/UUID checks remain the test harness's duty.
	 */
	if (!ctx->backing->bdev->bd_disk ||
	    strncmp(ctx->backing->bdev->bd_disk->disk_name, "nullb", 5)) {
		ti->error = "swapz alpha accepts null_blk backing only";
		error = -EOPNOTSUPP;
		goto fail;
	}
	if (bdev_is_zoned(ctx->backing->bdev) ||
	    bdev_read_only(ctx->backing->bdev) ||
	    bdev_logical_block_size(ctx->backing->bdev) > SWAPZ_BLOCK_BYTES ||
	    SWAPZ_BLOCK_BYTES % bdev_logical_block_size(ctx->backing->bdev)) {
		ti->error = "Unsupported zoned, read-only or unaligned swapz backing";
		error = -EINVAL;
		goto fail;
	}
	logical = div_u64(ti->len, SWAPZ_SECTORS);
	physical = div_u64(bdev_nr_sectors(ctx->backing->bdev), SWAPZ_SECTORS);
	physical = div_u64(physical, SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;
	if (!logical || logical > U32_MAX || physical > U32_MAX ||
	    physical < 3U * SWAPZ_SEGMENT_BLOCKS) {
		ti->error = "swapz requires at least three 1MiB physical segments";
		error = -EINVAL;
		goto fail;
	}
	ctx->logical_pages = logical;
	ctx->physical_blocks = physical;
	ctx->segment_count = physical / SWAPZ_SEGMENT_BLOCKS;
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
	error = swapz_authority_init(&ctx->authority, ctx->maps,
				  ctx->live_records, ctx->extent_classes,
				  (u32)logical, (u32)physical);
	if (error) {
		ti->error = "Insufficient capacity for uncompressed pages plus swapz reserve";
		goto fail;
	}
	/* Production allocator exchanges ownership of one GC reserve segment
	 * and one fully evacuated foreground victim every completed cycle. */
	ctx->authority.reuse_dead_segments = 1;
	error = swapz_enable_segment_rotation(&ctx->authority,
					  ctx->segment_roles, ctx->segment_count);
	if (error) {
		ti->error = "Cannot initialize rotating GC reserve roles";
		goto fail;
	}
	ctx->batch_bytes = vzalloc(SWAPZ_BATCH_BYTES);
	ctx->gc_bytes_store = vzalloc(SWAPZ_BATCH_BYTES);
	ctx->input_page = vzalloc(SWAPZ_BLOCK_BYTES);
	ctx->read_page = vzalloc(SWAPZ_BLOCK_BYTES);
	ctx->read_compressed = vzalloc(SWAPZ_BLOCK_BYTES);
	ctx->engine.write_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES);
	ctx->engine.read_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES);
	ctx->engine.read_metadata_cache =
		vzalloc(SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES);
	ctx->engine.bulk_scratch = vzalloc(SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES);
	ctx->engine.bulk_txs = kvcalloc(SWAPZ_MAX_RECORDS,
				       sizeof(*ctx->engine.bulk_txs),
				       GFP_KERNEL);
	ctx->lz4_workmem = kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!ctx->batch_bytes || !ctx->gc_bytes_store ||
	    !ctx->gc_scores || !ctx->gc_io_scores || !ctx->input_page ||
	    !ctx->read_page || !ctx->read_compressed ||
	    !ctx->engine.write_scratch || !ctx->engine.read_scratch ||
	    !ctx->engine.read_metadata_cache ||
	    !ctx->engine.bulk_scratch || !ctx->engine.bulk_txs ||
	    !ctx->lz4_workmem) {
		error = -ENOMEM;
		goto fail;
	}
	ctx->engine.authority = &ctx->authority;
	ctx->engine.io.opaque = ctx;
	ctx->engine.io.write_extent = swapz_lower_write;
	ctx->engine.io.write_run = swapz_lower_write_run;
	ctx->engine.io.read_blocks = swapz_lower_read;
	ctx->io_client = dm_io_client_create();
	if (IS_ERR(ctx->io_client)) {
		error = PTR_ERR(ctx->io_client);
		ctx->io_client = NULL;
		goto fail;
	}
	ctx->workqueue = alloc_workqueue(
				"swapz", WQ_MEM_RECLAIM | WQ_UNBOUND, 1);
	if (!ctx->workqueue) {
		error = -ENOMEM;
		goto fail;
	}
	if (ctx->async_prepare) {
		/* 64 preallocated producer pages, a semaphore enforcing the
		 * same hard bound, and no dynamic allocations in ->map. */
		ctx->preparation_input_page = vzalloc(SWAPZ_BLOCK_BYTES);
		ctx->preparation_lz4_workmem =
			kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
		ctx->preparation_pool = mempool_create_kmalloc_pool(
					SWAPZ_MAX_RECORDS,
					sizeof(struct swapz_prepared_page));
		if (!ctx->preparation_input_page ||
		    !ctx->preparation_lz4_workmem || !ctx->preparation_pool) {
			error = -ENOMEM;
			goto fail;
		}
		ctx->preparation_workqueue = alloc_workqueue(
					"swapz-lz4", WQ_MEM_RECLAIM | WQ_UNBOUND,
					1);
		if (!ctx->preparation_workqueue) {
			error = -ENOMEM;
			goto fail;
		}
	}
	ti->per_io_data_size = sizeof(struct swapz_bio_ref);
	ti->num_flush_bios = 1;
	ti->flush_supported = true;
	ti->num_discard_bios = 1;
	ti->discards_supported = true;
	ti->limit_swap_bios = true;
	error = dm_set_target_max_io_len(ti, SWAPZ_SECTORS);
	if (error)
		goto fail;
	WRITE_ONCE(ctx->accepting, true);
	DMINFO("swapz alpha %s logical_pages=%u physical_blocks=%u window=%u read_cap=%u LIVE GC EXPERIMENTAL",
	       SWAPZ_ALPHA_VERSION, ctx->logical_pages, ctx->physical_blocks,
	       ctx->max_window, (unsigned int)budget);
	return 0;
fail:
	swapz_free(ctx);
	ti->private = NULL;
	return error;
}

static int swapz_iterate_devices(struct dm_target *ti,
			      iterate_devices_callout_fn fn, void *data)
{
	struct swapz_dm *ctx = ti->private;

	return fn(ti, ctx->backing, 0,
		  (sector_t)ctx->physical_blocks * SWAPZ_SECTORS, data);
}

static void swapz_io_hints(struct dm_target *ti, struct queue_limits *limits)
{
	(void)ti;
	limits->logical_block_size = SWAPZ_BLOCK_BYTES;
	limits->physical_block_size = max(limits->physical_block_size,
					  (unsigned int)SWAPZ_BLOCK_BYTES);
	limits->io_min = SWAPZ_BLOCK_BYTES;
	limits->discard_granularity = SWAPZ_BLOCK_BYTES;
	limits->max_hw_discard_sectors = UINT_MAX;
	limits->max_discard_sectors = UINT_MAX;
}

static void swapz_status(struct dm_target *ti, status_type_t type,
		       unsigned int flags, char *result, unsigned int maxlen)
{
	struct swapz_dm *ctx = ti->private;
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
		       "window_records=%llu "
		       "win1=%llu win2=%llu win3_4=%llu win5_8=%llu "
		       "win9_16=%llu win17_64=%llu "
		       "close_unknown=%llu close_full=%llu close_duplicate=%llu "
		       "close_zero=%llu close_fua=%llu close_raw=%llu "
		       "close_read_conflict=%llu close_read_unrelated=%llu "
		       "close_discard=%llu close_preflush=%llu "
		       "close_quantum=%llu close_idle=%llu close_shutdown=%llu "
		       "close_other=%llu "
		       "win1_unknown=%llu win1_full=%llu win1_duplicate=%llu "
		       "win1_zero=%llu win1_fua=%llu win1_raw=%llu "
		       "win1_read_conflict=%llu win1_read_unrelated=%llu "
		       "win1_discard=%llu win1_preflush=%llu win1_quantum=%llu "
		       "win1_idle=%llu win1_shutdown=%llu win1_other=%llu "
		       "win1_deadline=%llu win1_pack_ready=%llu "
		       "window_gc_pressure=%llu "
		       "age_le100us=%llu age_101_1000us=%llu "
		       "age_gt1000us=%llu age_sum_ns=%llu age_max_ns=%llu "
		       "retain_ms=%u retain_passes=%llu retain_timer_arms=%llu "
		       "retain_timer_arm_skips=%llu "
		       "async_prepare=%u prep_lower_write_overlap_starts=%llu "
		       "prep_lower_write_overlap_ns=%llu prep_wave_kicks=%llu "
		       "prep_producer_head_claims=%llu prep_producer_tail_claims=%llu "
		       "prep_ordered_inline=%llu prep_ordered_handoffs=%llu "
		       "prep_ordered_waits=%llu prep_wait_wall_ns=%llu "
		       "lz4_wall_ns=%llu decode_wall_ns=%llu "
		       "write_copy_wall_ns=%llu write_copy_bytes=%llu "
		       "direct_lz4_input_pages=%llu "
		       "read_copy_wall_ns=%llu read_copy_bytes=%llu "
		       "window_sort_wall_ns=%llu window_commit_wall_ns=%llu "
		       "window_commit_nonio_wall_ns=%llu "
		       "engine_plan_wall_ns=%llu engine_pack_wall_ns=%llu "
		       "engine_publish_wall_ns=%llu "
		       "read_engine_nonio_wall_ns=%llu "
		       "lower_read_wall_ns=%llu lower_write_wall_ns=%llu "
		       "ordered_worker_cpu_ns=%llu prep_worker_cpu_ns=%llu "
		       "write_wait_le1ms=%llu write_wait_1to4ms=%llu "
		       "write_wait_gt4ms=%llu gc_wall_ns=%llu "
		       "close_deadline=%llu "
		       "deadline_before_bio=%llu deadline_after_read=%llu "
		       "deadline_worker_with_local=%llu deadline_worker_empty=%llu "
		       "retained_read_bypasses=%llu "
		       "close_pack_ready=%llu packed_early_commits=%llu "
		       "single_pack_deferrals=%llu accepted_burst_extensions=%llu "
		       "accepted_burst_tail_flushes=%llu accepted_burst_read_caps=%llu "
		       "retained_burst_target=%u "
		       "read_meta_reqs=%u read_payload_reqs=%u "
		       "read_payload_blocks=%u read_meta_cache_hits=%u "
		       "read_meta_lru_hits=%u "
		       "read_full_extent_reqs=%u read_full_cache_hits=%u "
		       "read_two_block_skips=%u "
		       "failed=%u error=%d",
		       SWAPZ_ALPHA_VERSION, ctx->logical_write_bytes,
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
		       ctx->window_records_total,
		       ctx->window_bins[0], ctx->window_bins[1],
		       ctx->window_bins[2], ctx->window_bins[3],
		       ctx->window_bins[4], ctx->window_bins[5],
		       ctx->window_close_reasons[SWAPZ_CLOSE_UNKNOWN],
		       ctx->window_close_reasons[SWAPZ_CLOSE_FULL],
		       ctx->window_close_reasons[SWAPZ_CLOSE_DUPLICATE],
		       ctx->window_close_reasons[SWAPZ_CLOSE_ZERO],
		       ctx->window_close_reasons[SWAPZ_CLOSE_FUA],
		       ctx->window_close_reasons[SWAPZ_CLOSE_RAW],
		       ctx->window_close_reasons[SWAPZ_CLOSE_READ_CONFLICT],
		       ctx->window_close_reasons[SWAPZ_CLOSE_READ_UNRELATED],
		       ctx->window_close_reasons[SWAPZ_CLOSE_DISCARD],
		       ctx->window_close_reasons[SWAPZ_CLOSE_PREFLUSH],
		       ctx->window_close_reasons[SWAPZ_CLOSE_QUANTUM],
		       ctx->window_close_reasons[SWAPZ_CLOSE_IDLE],
		       ctx->window_close_reasons[SWAPZ_CLOSE_SHUTDOWN],
		       ctx->window_close_reasons[SWAPZ_CLOSE_OTHER],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_UNKNOWN],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_FULL],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_DUPLICATE],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_ZERO],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_FUA],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_RAW],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_READ_CONFLICT],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_READ_UNRELATED],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_DISCARD],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_PREFLUSH],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_QUANTUM],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_IDLE],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_SHUTDOWN],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_OTHER],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_DEADLINE],
		       ctx->one_page_close_reasons[SWAPZ_CLOSE_PACK_READY],
		       ctx->window_gc_pressure,
		       ctx->window_age_le_100us, ctx->window_age_101_1000us,
		       ctx->window_age_gt_1000us, ctx->window_age_sum_ns,
		       ctx->window_age_max_ns,
		       ctx->retain_ms, ctx->retain_worker_passes,
		       ctx->retain_timer_arms, ctx->retain_timer_arm_skips,
		       ctx->async_prepare, ctx->prepared_during_lower_write,
		       ctx->preparation_lz4_lower_write_overlap_ns,
		       ctx->preparation_wave_kicks,
		       ctx->preparation_producer_head_claims,
		       ctx->preparation_producer_tail_claims,
		       ctx->preparation_ordered_inline,
		       ctx->preparation_ordered_handoffs,
		       ctx->preparation_ordered_waits,
		       ctx->preparation_ordered_wait_wall_ns,
		       ctx->lz4_wall_ns + ctx->preparation_lz4_wall_ns,
		       ctx->decode_wall_ns,
		       ctx->preparation_copy_wall_ns +
			       ctx->ordered_write_copy_wall_ns,
		       ctx->preparation_copy_bytes +
			       ctx->ordered_write_copy_bytes,
		       ctx->preparation_direct_lz4_pages +
			       ctx->ordered_direct_lz4_pages,
		       ctx->read_copy_wall_ns, ctx->read_copy_bytes,
		       ctx->window_sort_wall_ns, ctx->window_commit_wall_ns,
		       ctx->window_commit_nonio_wall_ns,
		       ctx->engine_plan_wall_ns, ctx->engine_pack_wall_ns,
		       ctx->engine_publish_wall_ns,
		       ctx->read_engine_nonio_wall_ns,
		       ctx->lower_read_wall_ns, ctx->lower_write_wall_ns,
		       ctx->ordered_worker_cpu_ns,
		       ctx->preparation_worker_cpu_ns,
		       ctx->write_wait_le_1ms, ctx->write_wait_1_to_4ms,
		       ctx->write_wait_gt_4ms, ctx->gc_wall_ns,
		       ctx->window_close_reasons[SWAPZ_CLOSE_DEADLINE],
		       ctx->deadline_before_bio, ctx->deadline_after_read,
		       ctx->deadline_worker_with_local, ctx->deadline_worker_empty,
		       ctx->retained_read_bypasses,
		       ctx->window_close_reasons[SWAPZ_CLOSE_PACK_READY],
		       ctx->packed_early_commits,
		       ctx->single_pack_deferrals,
		       ctx->accepted_burst_extensions,
		       ctx->accepted_burst_tail_flushes,
		       ctx->accepted_burst_read_caps,
		       ctx->retained_burst_target,
		       ctx->engine.read_metadata_requests,
		       ctx->engine.read_payload_requests,
		       ctx->engine.read_payload_blocks,
		       ctx->engine.read_metadata_cache_hits,
		       ctx->engine.read_metadata_lru_hits,
		       ctx->engine.read_full_extent_requests,
		       ctx->engine.read_full_extent_cache_hits,
		       ctx->engine.read_two_block_skips,
		       ctx->failed, ctx->last_error);
		break;
	case STATUSTYPE_TABLE:
		DMEMIT("%s %u %u %u %u %u %u %u %u", ctx->backing->name,
		       ctx->engine.max_read_blocks_per_record,
		       ctx->max_window, ctx->engine.verify_after_write,
		       ctx->gc_cost_policy, ctx->flush_meter.fail_nth,
		       ctx->engine.bulk_enabled, ctx->write_fault_nth,
		       ctx->retain_ms);
		break;
	case STATUSTYPE_IMA:
	default:
		break;
	}
}

static struct target_type swapz_target = {
	.name = "swapz",
	.version = {3, 0, 0},
	.features = DM_TARGET_SINGLETON | DM_TARGET_ALWAYS_WRITEABLE,
	.module = THIS_MODULE,
	.ctr = swapz_ctr,
	.dtr = swapz_dtr,
	.map = swapz_map,
	.presuspend = swapz_drain,
	.resume = swapz_resume,
	.iterate_devices = swapz_iterate_devices,
	.io_hints = swapz_io_hints,
	.status = swapz_status,
};

static int __init swapz_dm_init(void)
{
	return dm_register_target(&swapz_target);
}

static void __exit swapz_dm_exit(void)
{
	dm_unregister_target(&swapz_target);
}

module_init(swapz_dm_init);
module_exit(swapz_dm_exit);
MODULE_LICENSE("GPL");
MODULE_AUTHOR("swapz main developer");
MODULE_DESCRIPTION("swapz size-aware 4/8/16KiB volatile swap target; experimental live GC");
MODULE_ALIAS("dm-swapz");
MODULE_VERSION(SWAPZ_ALPHA_VERSION);
