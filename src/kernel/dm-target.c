// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz - EXPERIMENTAL swapz volatile Device Mapper swap target.
 *
 * Uses SWZ 4/8/16KiB extents, 4KiB logical pages, LZ4 and bounded
 * size-aware write windows. Write publication stays on one serialized
 * WQ_MEM_RECLAIM | WQ_UNBOUND owner; bounded private read slots may overlap
 * up to eight independent lower READs without publishing authority.
 *
 * Physical backing is opt-in and requires an explicit block-0 SWAPZ format
 * header; null_blk remains the default qualification path. Capacity exhaustion
 * fails only the affected write BIOs so committed pages remain readable.
 */
#define DM_MSG_PREFIX "swapz"
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/cache.h>
#include <linux/device-mapper.h>
#include <linux/dm-io.h>
#include <linux/highmem.h>
#include <linux/hrtimer.h>
#include <linux/ioprio.h>
#include <linux/completion.h>
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
#include "preparation-slots.h"
#include "predictor.h"
#include "predictor-route.h"
#include "superblock.h"

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
 * Idle producer wakes need enough unclaimed distance to amortize a workqueue
 * handoff. The wave-starter sees the ordered FIFO head too, so it requires one
 * extra descriptor; after the ordered head is stolen inline, four true tails
 * remain the wake threshold. An already-active lower WRITE is a separate real
 * overlap signal and may wake preparation for any queued page.
 */
#define SWAPZ_PREPARATION_TAIL_WAKE_MIN 4U
#define SWAPZ_PREPARATION_STARTER_WAKE_MIN \
	(SWAPZ_PREPARATION_TAIL_WAKE_MIN + 1U)
#define SWAPZ_PREPARATION_TAIL_CLAIM_MIN 2U
#define SWAPZ_WRITE_PIPELINE_DEPTH 1U
#define SWAPZ_DELTA64_PREPARATION_WORKERS 1U
#define SWAPZ_ORDINARY_LZ4_ACCELERATION 1U
#define SWAPZ_READ_COALESCE_MAX_BLOCKS (2U * SWAPZ_MAX_BLOCKS)
/*
 * A separate bounded LZ4 producer may prepare future writes while the
 * existing ordered commit worker waits on lower dm_io. WRITE physical I/O
 * and all mapping authority remain single-thread owned; bounded READ helpers
 * never publish or mutate authority.
 */
static bool swapz_async_prepare = true;
module_param_named(async_prepare, swapz_async_prepare, bool, 0444);
MODULE_PARM_DESC(async_prepare,
		 "Prepare bounded LZ4 writes concurrently with ordered lower I/O; "
		 "set async_prepare=0 for synchronous qualification");

static bool swapz_allow_physical_backing;
module_param_named(allow_physical_backing, swapz_allow_physical_backing, bool, 0444);
MODULE_PARM_DESC(allow_physical_backing,
		 "Allow explicitly formatted non-null_blk backing; default off");

static bool swapz_delta64_rescue_enabled;
module_param_named(delta64_rescue, swapz_delta64_rescue_enabled, bool, 0444);
MODULE_PARM_DESC(delta64_rescue,
		 "Opt in to page-local delta64 rescue with predictor-first high-score path; default off");

static unsigned int swapz_delta64_lz4_acceleration = 1U;
module_param_named(delta64_lz4_acceleration, swapz_delta64_lz4_acceleration,
		   uint, 0444);
MODULE_PARM_DESC(delta64_lz4_acceleration,
		 "Second-pass LZ4 acceleration 1..4 used only by delta64 rescue");

static bool swapz_read_coalesce = true;
module_param_named(read_coalesce, swapz_read_coalesce, bool, 0444);
MODULE_PARM_DESC(read_coalesce,
		 "Enable zero-extra adjacent distinct-extent READ coalescing");

static bool swapz_invalidate_cache_on_write_admit;
module_param_named(invalidate_cache_on_write_admit,
		   swapz_invalidate_cache_on_write_admit, bool, 0444);
MODULE_PARM_DESC(invalidate_cache_on_write_admit,
		 "A/B only: restore pre-2e309ec read-cache invalidation at "
		 "ordinary WRITE admission; default off");


struct swapz_delta64_stats {
	u64 eligible;
	u64 classifier_pass;
	u64 attempts;
	u64 adopted;
	u64 direct_adopted;
	u64 first_lz4_skipped;
	u64 raw_rescues;
	u64 lz4_rescues;
	u64 pack_eligible;
	u64 pack_attempts;
	u64 pack_cliff_crossings;
	u64 pack_adopted;
	u64 score_0_7;
	u64 score_8_15;
	u64 score_16_23;
	u64 score_ge24;
	u64 payload_bytes_saved;
	u64 raw_payload_bytes_saved;
	u64 lz4_payload_bytes_saved;
	u64 transform_calls;
	u64 transform_wall_ns;
	u64 wall_ns;
} ____cacheline_aligned_in_smp;

struct swapz_prepared_page {
	int length;
	bool zero;
	bool payload_crc32c_valid;
	swapz_u8 encoding;
	swapz_u32 payload_crc32c;
	u8 bytes[SWAPZ_BLOCK_BYTES];
} __aligned(64);

struct swapz_dm;

struct swapz_inflight_write {
	struct swapz_dm *ctx;
	struct swapz_io_run run;
	struct completion lower_done;
	struct bio *bios[SWAPZ_MAX_RECORDS];
	swapz_u8 raw[SWAPZ_MAX_RECORDS];
	swapz_u8 count;
	bool active;
	int lower_error;
	u64 lower_start_ns;
	u64 lower_end_ns;
	u64 commit_start_ns;
	u64 prepare_nonio_ns;
};

struct swapz_preparation_lane {
	struct work_struct work;
	struct swapz_dm *ctx;
	u8 *input_page;
	u8 *predictor_page;
	u8 *delta64_candidate_page;
	void *lz4_workmem;
	struct swapz_delta64_stats delta64;
	u64 lz4_wall_ns;
	u64 lower_write_overlap_ns;
	u64 lower_read_overlap_ns;
	u64 copy_wall_ns;
	u64 copy_bytes;
	u64 direct_lz4_pages;
	u64 copy_fallback_pages;
	u64 crc_wall_ns;
	u64 worker_wall_ns;
	u64 worker_cpu_ns;
	u64 prepared_during_lower_write;
	u64 prepared_during_lower_read;
	u64 prepared_pages;
};

struct swapz_preparation_totals {
	struct swapz_delta64_stats delta64;
	u64 lz4_wall_ns;
	u64 lower_write_overlap_ns;
	u64 lower_read_overlap_ns;
	u64 copy_wall_ns;
	u64 copy_bytes;
	u64 direct_lz4_pages;
	u64 copy_fallback_pages;
	u64 crc_wall_ns;
	u64 worker_wall_ns;
	u64 worker_cpu_ns;
	u64 prepared_during_lower_write;
	u64 prepared_during_lower_read;
	u64 prepared_pages;
};

struct swapz_read_slot {
	struct swapz_dm *ctx;
	struct swapz_engine engine;
	struct bio *bios[SWAPZ_MAX_RECORDS];
	swapz_u32 logical_pages[SWAPZ_MAX_RECORDS];
	swapz_u8 bio_count;
	swapz_u32 start_block;
	swapz_u8 extent_blocks;
	u8 *read_pages; /* one 4KiB output for each grouped BIO */
	u8 *read_compressed;
	u8 *predictor_page;
	struct completion lower_done;
	int error;
	int lower_error;
	swapz_u8 lower_first_block;
	swapz_u8 lower_blocks;
	bool lower_submitted;
	u64 lower_start_ns;
	u64 lower_end_ns;
	u64 lower_read_submitted_bytes;
	u64 lower_read_submitted_reqs;
	u64 physical_read_bytes;
	u64 physical_read_reqs;
	u64 lower_read_wall_ns;
	u64 read_engine_nonio_wall_ns;
	u64 decode_wall_ns;
};

struct swapz_bio_ref {
	struct list_head list;
	struct bio *bio;
	/* Both lists refer to this dm_per_bio_data object. The ordered worker
	 * waits for preparation_finished before touching the payload or BIO.
	 * Only the ordered worker returns a completed prepared buffer's slot. */
	struct list_head preparation_list;
	struct completion preparation_finished;
	struct swapz_prepared_page *prepared_page;
	/* Set only when the ordered worker atomically removes this BIO from
	 * preparation_incoming before the producer claims it. */
	bool preparation_inline;
	struct swapz_dm *preparation_ctx;
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

/* Diagnostic-only primary trigger for each PACK_READY close. */
enum swapz_pack_close_cause {
	SWAPZ_PACK_CLOSE_NONE,
	SWAPZ_PACK_CLOSE_TAIL_TARGET,
	SWAPZ_PACK_CLOSE_BURST_TARGET,
	SWAPZ_PACK_CLOSE_SERVICE_DRY,
};

enum swapz_burst_close_site {
	SWAPZ_BURST_CLOSE_NONE,
	SWAPZ_BURST_CLOSE_ADMISSION,
	SWAPZ_BURST_CLOSE_WORKER,
};

struct swapz_dm {
	struct dm_target *target;
	struct dm_dev *backing;
	struct dm_io_client *io_client;
	struct workqueue_struct *workqueue;
	struct delayed_work worker;
	/* Bounded read grouping/coalescing scratch. The ordered worker remains
	 * the sole read execution, authority and BIO-completion owner. */
	struct swapz_read_slot *read_slots;
	/* All active ID63 slots share one 64-page decode-output pool. */
	u8 *read_pages_store;
	u8 *read_coalesce_scratch; /* 2 * SWAPZ_MAX_EXTENT_BYTES */
	bool read_grouping_enabled;
	bool read_coalescing_enabled;
	/* Bounded independent lower-READ fan-out uses private slot scratch. */
	u64 parallel_read_pairs;
	u64 parallel_read_async_batches;
	u64 parallel_read_async_slots;
	u64 parallel_read_same_extent_pairs;
	/* ID63 passive evidence for the two distinct extents already selected
	 * in one Kread dispatch; no dispatch or cache policy depends on it. */
	u64 parallel_read_distinct_extent_pairs;
	u64 parallel_read_adjacent_extent_pairs;
	u64 parallel_read_adjacent_extent_blocks;
	/* Passive conservative evidence for extending ID63 beyond a pair. These
	 * count 3+ physically adjacent admitted extents whose complete extent
	 * span fits the existing eight-block/32KiB coalescing scratch. Exact
	 * missing ranges can only create additional opportunities. */
	u64 parallel_read_adjacent_chain_3plus;
	u64 parallel_read_adjacent_chain_extent_max;
	u64 parallel_read_adjacent_chain_blocks_max;
	/* ID63 active zero-extra-byte merges of the exact missing lower ranges. */
	u64 parallel_read_coalesced_pairs;
	u64 parallel_read_coalesced_reqs_saved;
	u64 parallel_read_coalesced_blocks;
	u64 parallel_read_coalesce_extra_blocks;
	/* Passive reason attribution for adjacent pairs that ID63 could not merge.
	 * The three expected reasons are mutually exclusive; skip_other is a
	 * defensive invariant bucket and must remain zero in qualification. */
	u64 parallel_read_coalesce_skip_cached;
	u64 parallel_read_coalesce_skip_noncontig_slot;
	u64 parallel_read_coalesce_skip_gap;
	u64 parallel_read_coalesce_skip_other;
	/* Bounded preparation lanes, separate from the ordered I/O worker.
	 * No producer ever changes maps, stages extents or completes BIOs. */
	bool async_prepare;
	bool delta64_rescue_enabled;
	bool invalidate_cache_on_write_admit;
	swapz_u8 delta64_lz4_acceleration;
	struct workqueue_struct *preparation_workqueue;
	struct swapz_preparation_lane *preparation_lanes;
	swapz_u8 preparation_worker_count;
	struct list_head preparation_incoming;
	/* Exact unclaimed preparation descriptors, protected by queue_lock. */
	swapz_u32 preparation_queued;
	struct swapz_prepared_page *preparation_pages;
	atomic64_t preparation_free_mask;
	/* Each producer lane owns input/predictor/LZ4 scratch and diagnostics.
	 * The ordered worker remains the sole planner/publisher/ACK owner. */
	atomic_t lower_write_active;
	/* Count active lower READ service while the ordered worker cannot consume
	 * preparation_incoming. Producers may prepare only immutable WRITE input;
	 * they still never publish mappings or complete upper BIOs. */
	atomic_t lower_read_active;
	atomic_t preparation_workers_active;
	atomic_t preparation_workers_active_max;
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
	/* Diagnostic queue-depth samples at synchronous lower-WRITE boundaries. */
	u64 prep_lower_write_samples;
	u64 prep_lower_write_start_queued;
	u64 prep_lower_write_start_nonempty;
	u64 prep_lower_write_end_queued;
	u64 prep_lower_write_end_nonempty;
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
	swapz_u32 physical_blocks;
	swapz_u32 data_start_block;
	bool physical_backing;
	u64 backing_device_bytes;
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
	swapz_u16 *gc_min_live_blocks; /* proven per-survivor block bound */
	swapz_u32 *gc_segment_evictions; /* successful committed victim rotations */
	swapz_u32 *segment_mapped_pages; /* exact current logical maps per segment */
	swapz_u32 *segment_program_counts; /* logical allocator opens, not NAND wear */
	swapz_u32 *segment_first_page; /* exact current logical membership */
	swapz_u32 *segment_last_page;
	swapz_u32 *page_prev_in_segment;
	swapz_u32 *page_next_in_segment;
	swapz_u8 *segment_trimmed; /* successful whole-segment DISCARD since write */
	swapz_u8 *segment_roles; /* 1=foreground, 0=free GC reserve */
	swapz_u32 segment_count;
	swapz_u8 gc_cost_policy; /* 0=record count; 1=payload bytes; 2=I/O */
	u64 gc_selected_io_cost;
	u64 gc_no_headroom_skips;
	u64 gc_selected_live_bytes;
	u64 gc_selected_live_records;
	/* ID61 foreground-GC scaling/latency evidence. These counters observe
	 * existing serialized GC only; they never participate in victim choice. */
	u64 gc_choose_wall_ns;
	u64 gc_choose_calls;
	u64 gc_choose_map_entries;
	u64 gc_choose_segment_entries;
	u64 gc_relocation_map_entries;
	u64 gc_victims;
	u64 gc_role_rotations;
	swapz_u32 last_gc_victim;
	swapz_u32 last_gc_destination;
	u64 gc_pages;
	u64 gc_read_bytes;
	u64 gc_write_bytes;
	u64 gc_read_reqs;
	u64 gc_write_reqs;
	/* ID29 advisory lower discard of already-dead whole 1MiB segments. */
	u64 segment_discards_eligible;
	u64 segment_discards_issued;
	u64 segment_discards_completed;
	u64 segment_discards_unsupported;
	u64 segment_discards_failed;
	u64 segment_discard_sectors;
	u64 segment_discard_wall_ns;
	u64 segment_discards_skipped_already_trimmed;
	swapz_u8 batch_count;
	swapz_u8 max_window;
	/*
	 * One immutable physical lower-WRITE owner reuses
	 * engine.bulk_scratch/bulk_txs. Only the ordered worker publishes
	 * authority and upper BIO completions.
	 */
	struct swapz_inflight_write inflight_write;
	swapz_u8 inflight_count;
	swapz_u8 pipeline_active_max;
	u64 pipeline_async_runs;
	u64 pipeline_completed_runs;
	u64 pipeline_collected_pages;
	u64 pipeline_read_bypass_skips;
	u64 pipeline_finalize_waits;
	u64 pipeline_finalize_wait_wall_ns;
	/* Time after an asynchronous lower WRITE callback until the ordered owner
	 * finishes publication/abort and releases the immutable run slot. */
	u64 pipeline_post_lower_wall_ns;
	/* ID38 passive evidence: a nonempty ready window reached flush while
	 * the sole immutable lower run was genuinely unfinished. */
	u64 k1_ready_wait_windows;
	u64 k1_ready_wait_records;
	u64 k1_ready_wait_wall_ns;
	u64 k1_ready_wait_max_records;
	u64 k1_ready_wait_pack_ready;
	u64 k1_ready_wait_full;
	u64 k1_ready_wait_deadline;
	u64 k1_ready_wait_fence;
	u64 k1_ready_wait_other;
	/* Sum of per-slot occupancy; depth=2 may exceed wall time by overlap. */
	u64 pipeline_active_wall_ns;
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
	/* A one-record post-PACK sample is too timing-sensitive to authorize
	 * another PACK_READY close. Keep that singleton open until a companion
	 * joins or the ordinary first-record retention deadline expires. */
	bool retained_single_tail_deferred;
	/* Exact lifecycle attribution for every sampled singleton deferral. */
	u64 single_tail_deferrals;
	u64 single_tail_companions;
	u64 win1_deadline_deferred_tail;
	u64 win1_idle_deferred_tail;
	u64 single_tail_other_clears;
	/* ID52 passive timing/service state; no field changes closure policy. */
	u64 single_tail_deferred_start_ns;
	bool single_tail_lower_done_seen;
	bool single_tail_read_bypass_seen;
	u64 single_tail_companion_age_le250us;
	u64 single_tail_companion_age_251_500us;
	u64 single_tail_companion_age_501_1000us;
	u64 single_tail_companion_age_gt1000us;
	u64 single_tail_companion_age_1001_1250us;
	u64 single_tail_companion_age_1251_1500us;
	u64 single_tail_companion_age_1501_1750us;
	u64 single_tail_companion_age_gt1750us;
	u64 single_tail_deadline_age_le250us;
	u64 single_tail_deadline_age_251_500us;
	u64 single_tail_deadline_age_501_1000us;
	u64 single_tail_deadline_age_gt1000us;
	u64 single_tail_companion_after_lower_done;
	u64 single_tail_companion_after_read_bypass;
	u64 single_tail_companion_after_both;
	u64 single_tail_deadline_after_lower_done;
	u64 single_tail_deadline_after_read_bypass;
	u64 single_tail_deadline_after_both;
	swapz_u8 retained_chain_completed;
	bool pack_close_pending_tail_sample;
	u64 window_records_total;
	/* Worker-owned telemetry only; status is a diagnostic snapshot. */
	enum swapz_window_close_reason next_window_close;
	u64 window_close_reasons[SWAPZ_CLOSE_REASON_COUNT];
	/* Joint diagnostic: which primary closure actually produced win1. */
	u64 one_page_close_reasons[SWAPZ_CLOSE_REASON_COUNT];
	/* Mutually exclusive attribution for one-page PACK_READY closes. */
	u64 win1_pack_tail_target;
	u64 win1_pack_read_bypass;
	u64 win1_pack_wave_interrupted;
	/* Mutually exclusive primary attribution for every PACK_READY window. */
	enum swapz_pack_close_cause next_pack_close_cause;
	enum swapz_burst_close_site next_burst_close_site;
	swapz_u8 next_burst_close_target;
	u64 pack_close_tail_target;
	u64 pack_close_tail_target_le4;
	u64 pack_close_burst_target;
	u64 pack_close_service_dry;
	/* ID55: passive attribution inside the learned burst-target bucket. */
	u64 pack_close_burst_admission;
	u64 pack_close_burst_worker;
	u64 pack_close_burst_target_le4;
	u64 pack_close_burst_target_5_8;
	u64 pack_close_burst_target_9_16;
	u64 pack_close_burst_target_17_64;
	u64 pack_close_burst_count_le4;
	u64 pack_close_burst_count_5_8;
	u64 pack_close_burst_count_9_16;
	u64 pack_close_burst_count_17_64;
	u64 pack_close_burst_overshoot;
	/* ID56: passive post-PACK_READY tail-sample timing evidence. */
	u64 pack_tail_samples;
	u64 pack_tail_zero_inflight;
	u64 pack_tail_zero_idle;
	u64 pack_tail_one_inflight;
	u64 pack_tail_one_idle;
	u64 pack_tail_many_inflight;
	u64 pack_tail_many_idle;
	u64 burst_target_grows;
	u64 burst_target_shrinks;
	/* Passive causal attribution for every actual learned-target shrink. */
	u64 burst_shrink_after_read_bypass;
	u64 burst_shrink_other;
	u64 burst_shrink_target_le8;
	u64 burst_shrink_target_9_32;
	u64 burst_shrink_target_gt32;
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
	u8 *predictor_page;    /* 4KiB delta64 transform/decode scratch */
	u8 *delta64_candidate_page; /* predictor-first candidate output */
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
	/* Foreground attempt-side diagnostics, including speculative preparation
	 * later aborted before publication. Each worker owns its accumulator;
	 * only status sums them. Payload savings are not lower-device savings. */
	struct swapz_delta64_stats ordered_delta64;
	/* Cumulative monotonic wall-time diagnostics; includes warmup and
	 * oracle, NOT CPU cycles and NOT a measurement-interval delta. */
	u64 lz4_wall_ns;
	u64 decode_wall_ns;
	/*
	 * Explicit RAM-copy attribution. Producer and ordered write paths keep
	 * separate single-writer accumulators and are summed only for status.
	 * Bytes count successful explicit copies, not LZ4's own memory traffic.
	 */
	u64 ordered_write_copy_wall_ns;
	u64 ordered_write_copy_bytes;
	u64 ordered_direct_lz4_pages;
	u64 ordered_copy_fallback_pages;
	/* Upper BIO shape and memory-input observation counters (ID43). */
	u64 bio_segments_gt1;
	u32 bio_segments_max;
	u64 bio_nonzero_offset;
	u64 bio_compound_folio_pages;
	u64 read_copy_wall_ns;
	u64 read_copy_bytes;
	u64 window_sort_wall_ns;
	u64 window_commit_wall_ns;
	/* Engine commit wall time with synchronous lower-WRITE wait removed. */
	u64 window_commit_nonio_wall_ns;
	u64 engine_plan_wall_ns;
	u64 engine_pack_wall_ns;
	u64 engine_publish_wall_ns;
	u64 engine_publish_crc_wall_ns;
	/* Targeted-read engine wall time with synchronous lower-READ wait removed. */
	u64 read_engine_nonio_wall_ns;
	u64 gc_wall_ns;
	u64 lower_read_wall_ns;
	u64 lower_write_wall_ns;
	/*
	 * Callback residency wall time includes sleep and scheduler delay.
	 * Scheduler-accounted worker CPU samples intentionally exclude those
	 * intervals; direct sum_exec_runtime reads can conservatively miss the
	 * current unaccounted slice but never turn sleep into CPU time.
	 */
	u64 ordered_worker_wall_ns;
	u64 ordered_worker_cpu_ns;
	/* Retained status-ABI field for the retired ID39 helper; remains zero. */
	u64 read_worker_cpu_ns;
	u64 ordered_crc_wall_ns;
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

static u64 swapz_worker_cpu_sample(void)
{
	return READ_ONCE(current->se.sum_exec_runtime);
}

static void swapz_account_worker_runtime(u64 *wall_counter, u64 wall_start_ns,
					 u64 *cpu_counter, u64 cpu_start_ns)
{
	u64 cpu_end_ns = swapz_worker_cpu_sample();

	*wall_counter += swapz_elapsed_ns(wall_start_ns, ktime_get_ns());
	*cpu_counter += swapz_elapsed_ns(cpu_start_ns, cpu_end_ns);
}

static void swapz_delta64_stats_add(struct swapz_delta64_stats *total,
				    const struct swapz_delta64_stats *part)
{
#define SWAPZ_ADD_DELTA64_FIELD(field) total->field += READ_ONCE(part->field)
	SWAPZ_ADD_DELTA64_FIELD(eligible);
	SWAPZ_ADD_DELTA64_FIELD(classifier_pass);
	SWAPZ_ADD_DELTA64_FIELD(attempts);
	SWAPZ_ADD_DELTA64_FIELD(adopted);
	SWAPZ_ADD_DELTA64_FIELD(direct_adopted);
	SWAPZ_ADD_DELTA64_FIELD(first_lz4_skipped);
	SWAPZ_ADD_DELTA64_FIELD(raw_rescues);
	SWAPZ_ADD_DELTA64_FIELD(lz4_rescues);
	SWAPZ_ADD_DELTA64_FIELD(pack_eligible);
	SWAPZ_ADD_DELTA64_FIELD(pack_attempts);
	SWAPZ_ADD_DELTA64_FIELD(pack_cliff_crossings);
	SWAPZ_ADD_DELTA64_FIELD(pack_adopted);
	SWAPZ_ADD_DELTA64_FIELD(score_0_7);
	SWAPZ_ADD_DELTA64_FIELD(score_8_15);
	SWAPZ_ADD_DELTA64_FIELD(score_16_23);
	SWAPZ_ADD_DELTA64_FIELD(score_ge24);
	SWAPZ_ADD_DELTA64_FIELD(payload_bytes_saved);
	SWAPZ_ADD_DELTA64_FIELD(raw_payload_bytes_saved);
	SWAPZ_ADD_DELTA64_FIELD(lz4_payload_bytes_saved);
	SWAPZ_ADD_DELTA64_FIELD(transform_calls);
	SWAPZ_ADD_DELTA64_FIELD(transform_wall_ns);
	SWAPZ_ADD_DELTA64_FIELD(wall_ns);
#undef SWAPZ_ADD_DELTA64_FIELD
}

static void swapz_preparation_totals_snapshot(
	const struct swapz_dm *ctx, struct swapz_preparation_totals *total)
{
	swapz_u8 index;

	memset(total, 0, sizeof(*total));
	if (!ctx->preparation_lanes)
		return;
	for (index = 0; index < ctx->preparation_worker_count; ++index) {
		const struct swapz_preparation_lane *lane =
			&ctx->preparation_lanes[index];

		swapz_delta64_stats_add(&total->delta64, &lane->delta64);
		total->lz4_wall_ns += READ_ONCE(lane->lz4_wall_ns);
		total->lower_write_overlap_ns += READ_ONCE(lane->lower_write_overlap_ns);
		total->lower_read_overlap_ns += READ_ONCE(lane->lower_read_overlap_ns);
		total->copy_wall_ns += READ_ONCE(lane->copy_wall_ns);
		total->copy_bytes += READ_ONCE(lane->copy_bytes);
		total->direct_lz4_pages += READ_ONCE(lane->direct_lz4_pages);
		total->copy_fallback_pages += READ_ONCE(lane->copy_fallback_pages);
		total->crc_wall_ns += READ_ONCE(lane->crc_wall_ns);
		total->worker_wall_ns += READ_ONCE(lane->worker_wall_ns);
		total->worker_cpu_ns += READ_ONCE(lane->worker_cpu_ns);
		total->prepared_during_lower_write +=
			READ_ONCE(lane->prepared_during_lower_write);
		total->prepared_during_lower_read +=
			READ_ONCE(lane->prepared_during_lower_read);
		total->prepared_pages += READ_ONCE(lane->prepared_pages);
	}
}

/*
 * Per-BIO prepared bytes have one final owner: the serialized worker.
 * Release before bio_endio(), which can invalidate dm_per_bio_data.
 * Early release after copying into batch_bytes bounds producer memory.
 */
static void swapz_release_prepared(struct bio *bio)
{
	struct swapz_bio_ref *entry = dm_per_bio_data(bio, sizeof(*entry));
	struct swapz_dm *ctx = entry->preparation_ctx;
	size_t slot;

	if (!entry->prepared_page)
		return;
	slot = (size_t)(entry->prepared_page - ctx->preparation_pages);
	entry->prepared_page = NULL;
	swapz_preparation_release_slot(&ctx->preparation_free_mask,
				       (unsigned int)slot);
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
	/* Capacity exhaustion is a per-write result. Existing committed maps
	 * remain authoritative and readable; only integrity/lower-I/O faults
	 * poison the target. */
	if (error == -ENOSPC)
		return;
	if (!ctx->failed) {
		ctx->failed = true;
		ctx->last_error = error < 0 ? error : -EIO;
		ctx->io_failures++;
		DMERR("swapz alpha: lower or mapping error %d; rejecting subsequent I/O",
		      ctx->last_error);
	}
}

static int swapz_validate_physical_superblock(struct swapz_dm *ctx,
					      u64 device_bytes)
{
	struct dm_io_region region;
	struct dm_io_request req = {
		.bi_opf = REQ_OP_READ | REQ_SYNC,
		.mem = {
			.type = DM_IO_KMEM,
			.offset = 0,
		},
		.notify = {
			.fn = NULL,
			.context = NULL,
		},
		.client = ctx->io_client,
	};
	unsigned long error_bits = 0;
	u8 *block;
	int error;

	block = kzalloc(SWAPZ_SUPERBLOCK_BYTES, GFP_KERNEL);
	if (!block)
		return -ENOMEM;
	req.mem.ptr.addr = block;
	region.bdev = ctx->backing->bdev;
	region.sector = 0;
	region.count = SWAPZ_SUPERBLOCK_BYTES >> SECTOR_SHIFT;
	error = dm_io(&req, 1, &region, &error_bits, IOPRIO_DEFAULT);
	if (!error && error_bits)
		error = -EIO;
	if (!error && !swapz_sb_valid(block, device_bytes))
		error = -EPERM;
	kfree(block);
	return error;
}


static void swapz_invalidate_read_caches(struct swapz_dm *ctx)
{
	swapz_u8 slot;

	swapz_engine_invalidate_read_cache(&ctx->engine);
	if (!ctx->read_slots)
		return;
	for (slot = 0; slot < SWAPZ_PARALLEL_READ_SLOTS; ++slot)
		swapz_engine_invalidate_read_cache(&ctx->read_slots[slot].engine);
}

static void swapz_invalidate_read_caches_range(struct swapz_dm *ctx,
					       swapz_u32 block,
					       swapz_u16 blocks)
{
	swapz_u8 slot;

	if (ctx->invalidate_cache_on_write_admit ||
	    ctx->engine.verify_after_write) {
		swapz_invalidate_read_caches(ctx);
		return;
	}
	swapz_engine_invalidate_read_range(&ctx->engine, block, blocks);
	if (!ctx->read_slots)
		return;
	for (slot = 0; slot < SWAPZ_PARALLEL_READ_SLOTS; ++slot)
		swapz_engine_invalidate_read_range(
			&ctx->read_slots[slot].engine, block, blocks);
}

static void swapz_queue_preparation_workers(struct swapz_dm *ctx)
{
	swapz_u8 lane;

	if (!ctx->preparation_workqueue || !ctx->preparation_lanes)
		return;
	for (lane = 0; lane < ctx->preparation_worker_count; ++lane)
		queue_work(ctx->preparation_workqueue,
			   &ctx->preparation_lanes[lane].work);
}

/*
 * A lower READ is useful preparation overlap just like a detached lower WRITE:
 * the ordered owner cannot consume preparation_incoming while it waits for the
 * device, but the producer may safely compress immutable queued WRITE input.
 * Keep this as an exact nested count so map-time arrivals can wake the producer
 * throughout a multi-request READ batch.
 */
static void swapz_lower_read_overlap_begin(struct swapz_dm *ctx)
{
	if (!ctx->async_prepare)
		return;
	atomic_inc(&ctx->lower_read_active);
	if (READ_ONCE(ctx->preparation_queued))
		swapz_queue_preparation_workers(ctx);
}

static void swapz_lower_read_overlap_end(struct swapz_dm *ctx)
{
	if (ctx->async_prepare)
		atomic_dec(&ctx->lower_read_active);
}

static bool swapz_has_inflight(const struct swapz_dm *ctx)
{
	return READ_ONCE(ctx->inflight_count) != 0U;
}

static struct swapz_inflight_write *swapz_inflight_head_slot(struct swapz_dm *ctx)
{
	if (!swapz_has_inflight(ctx))
		return NULL;
	return &ctx->inflight_write;
}

static struct swapz_inflight_write *swapz_inflight_tail_slot(struct swapz_dm *ctx)
{
	if (ctx->inflight_count >= SWAPZ_WRITE_PIPELINE_DEPTH)
		return NULL;
	return &ctx->inflight_write;
}

static bool swapz_inflight_lower_pending(struct swapz_dm *ctx)
{
	return READ_ONCE(ctx->inflight_write.active) &&
		!completion_done(&ctx->inflight_write.lower_done);
}

static bool swapz_inflight_uses_segment(struct swapz_dm *ctx, swapz_u32 segment)
{
	return READ_ONCE(ctx->inflight_write.active) &&
		ctx->inflight_write.run.start_block / SWAPZ_SEGMENT_BLOCKS == segment;
}

static bool swapz_inflight_run_touches_logical(struct swapz_dm *ctx,
					       swapz_u32 logical)
{
	struct swapz_inflight_write *inflight = &ctx->inflight_write;
	struct swapz_io_run *run = &inflight->run;
	swapz_u8 extent, record, pending = 0;

	if (!swapz_has_inflight(ctx))
		return false;
	if (ctx->inflight_count != SWAPZ_WRITE_PIPELINE_DEPTH ||
	    !READ_ONCE(inflight->active) || !run->txs ||
	    !run->extent_count || run->extent_count > SWAPZ_MAX_RECORDS)
		return true;
	pending = run->extent_count;
	for (extent = 0; extent < run->extent_count; ++extent) {
		const struct swapz_tx *tx = &run->txs[extent];

		if (!tx->count || tx->count > SWAPZ_MAX_RECORDS)
			return true;
		for (record = 0; record < tx->count; ++record)
			if (tx->records[record].logical_page == logical)
				return true;
	}
	return ctx->authority.batch_pending != pending;
}

static void swapz_async_lower_write_done(unsigned long error, void *context)
{
	struct swapz_inflight_write *inflight = context;
	struct swapz_dm *ctx = inflight->ctx;
	unsigned long flags;

	WRITE_ONCE(inflight->lower_error, error ? -EIO : 0);
	WRITE_ONCE(inflight->lower_end_ns, ktime_get_ns());
	spin_lock_irqsave(&ctx->queue_lock, flags);
	ctx->prep_lower_write_end_queued += ctx->preparation_queued;
	if (ctx->preparation_queued)
		ctx->prep_lower_write_end_nonempty++;
	atomic_dec(&ctx->lower_write_active);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	complete(&inflight->lower_done);
	mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
}

static void swapz_mark_segments_dirty(struct swapz_dm *ctx,
				      swapz_u32 block, swapz_u16 blocks)
{
	swapz_u32 segment, last_segment;

	if (!ctx->segment_trimmed || !blocks)
		return;
	segment = block / SWAPZ_SEGMENT_BLOCKS;
	last_segment = (block + blocks - 1U) / SWAPZ_SEGMENT_BLOCKS;
	for (; segment <= last_segment; ++segment)
		WRITE_ONCE(ctx->segment_trimmed[segment], 0);
}

static int swapz_submit_inflight_write(struct swapz_dm *ctx,
				       struct swapz_inflight_write *inflight)
{
	struct dm_io_region region;
	struct dm_io_request req = {
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.mem = {
			.type = DM_IO_VMA,
			.offset = 0,
			.ptr.vma = inflight->run.bytes,
		},
		.notify = {
			.fn = swapz_async_lower_write_done,
			.context = inflight,
		},
		.client = ctx->io_client,
	};
	unsigned long flags;
	int error;

	if (!inflight || inflight != swapz_inflight_tail_slot(ctx) ||
	    inflight->active || !inflight->run.blocks ||
	    inflight->run.start_block >= ctx->physical_blocks ||
	    inflight->run.blocks >
		ctx->physical_blocks - inflight->run.start_block)
		return -EINVAL;
	if (ctx->write_fault_nth &&
	    ++ctx->write_fault_calls == ctx->write_fault_nth) {
		ctx->write_fault_injected++;
		return -EIO;
	}
	swapz_mark_segments_dirty(ctx, inflight->run.start_block,
				 inflight->run.blocks);
	swapz_invalidate_read_caches_range(ctx, inflight->run.start_block,
					   inflight->run.blocks);
	ctx->lower_write_submitted_bytes +=
		(u64)inflight->run.blocks * SWAPZ_BLOCK_BYTES;
	ctx->lower_write_submitted_reqs++;
	ctx->engine.submitted_blocks += inflight->run.blocks;
	region.bdev = ctx->backing->bdev;
	region.sector = (sector_t)(ctx->data_start_block + inflight->run.start_block) *
		SWAPZ_SECTORS;
	region.count = (sector_t)inflight->run.blocks * SWAPZ_SECTORS;
	reinit_completion(&inflight->lower_done);
	inflight->lower_error = 0;
	inflight->lower_start_ns = ktime_get_ns();
	inflight->lower_end_ns = 0;
	WRITE_ONCE(inflight->active, true);
	ctx->inflight_count++;
	spin_lock_irqsave(&ctx->queue_lock, flags);
	atomic_inc(&ctx->lower_write_active);
	ctx->prep_lower_write_samples++;
	ctx->prep_lower_write_start_queued += ctx->preparation_queued;
	if (ctx->preparation_queued)
		ctx->prep_lower_write_start_nonempty++;
	if (ctx->async_prepare && ctx->preparation_queued)
		swapz_queue_preparation_workers(ctx);
	spin_unlock_irqrestore(&ctx->queue_lock, flags);
	error = dm_io(&req, 1, &region, NULL, IOPRIO_DEFAULT);
	if (error) {
		spin_lock_irqsave(&ctx->queue_lock, flags);
		ctx->prep_lower_write_end_queued += ctx->preparation_queued;
		if (ctx->preparation_queued)
			ctx->prep_lower_write_end_nonempty++;
		atomic_dec(&ctx->lower_write_active);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		inflight->lower_end_ns = ktime_get_ns();
		inflight->lower_error = error;
		WRITE_ONCE(inflight->active, false);
		ctx->inflight_count--;
		return error;
	}
	ctx->pipeline_active_max =
		max_t(swapz_u8, ctx->pipeline_active_max, ctx->inflight_count);
	ctx->pipeline_async_runs++;
	return 0;
}

static int swapz_finalize_inflight_write(struct swapz_dm *ctx, bool wait)
{
	struct swapz_inflight_write *inflight = swapz_inflight_head_slot(ctx);
	u64 publish_before, publish_crc_before, complete_start, complete_elapsed;
	u64 lower_end, lower_elapsed, commit_elapsed, finalize_end;
	swapz_u8 committed = 0, index;
	int lower_error, error;

	if (!inflight)
		return 0;
	if (!READ_ONCE(inflight->active))
		return -EUCLEAN;
	if (!completion_done(&inflight->lower_done)) {
		if (!wait)
			return 0;
		ctx->pipeline_finalize_waits++;
		{
			u64 wait_start_ns = ktime_get_ns();

			wait_for_completion(&inflight->lower_done);
			ctx->pipeline_finalize_wait_wall_ns +=
				swapz_elapsed_ns(wait_start_ns, ktime_get_ns());
		}
	}
	lower_end = READ_ONCE(inflight->lower_end_ns);
	lower_error = READ_ONCE(inflight->lower_error);
	lower_elapsed = swapz_elapsed_ns(inflight->lower_start_ns, lower_end);
	/*
	 * Completion owns the only path that can release the immutable run.
	 * A corrupt/missing callback timestamp is therefore a run failure, not
	 * an early-return condition: abort through the ordinary completion path
	 * so authority reservations and every upper BIO are released exactly once.
	 */
	if (!lower_end || lower_end < inflight->lower_start_ns) {
		if (!lower_error)
			lower_error = -EUCLEAN;
		lower_elapsed = 0;
	}
	ctx->lower_write_wall_ns += lower_elapsed;
	if (!lower_error) {
		ctx->physical_write_bytes +=
			(u64)inflight->run.blocks * SWAPZ_BLOCK_BYTES;
		ctx->physical_write_reqs++;
		if (lower_elapsed <= 1000000ULL)
			ctx->write_wait_le_1ms++;
		else if (lower_elapsed <= 4000000ULL)
			ctx->write_wait_1_to_4ms++;
		else
			ctx->write_wait_gt_4ms++;
	}
	error = lower_error;
	if (!error && ctx->failed)
		error = ctx->last_error ? ctx->last_error : -EIO;
	publish_before = ctx->engine.publish_wall_ns;
	publish_crc_before = ctx->authority.publish_crc_wall_ns;
	complete_start = ktime_get_ns();
	{
		int complete_error = swapz_engine_complete_batched_run(
			&ctx->engine, &inflight->run,
			error ? 0 : inflight->run.blocks, error, &committed);

		if (complete_error)
			error = complete_error;
	}
	finalize_end = ktime_get_ns();
	complete_elapsed = swapz_elapsed_ns(complete_start, finalize_end);
	ctx->engine_publish_wall_ns +=
		ctx->engine.publish_wall_ns - publish_before;
	if (ctx->authority.publish_crc_wall_ns >= publish_crc_before)
		ctx->engine_publish_crc_wall_ns +=
			ctx->authority.publish_crc_wall_ns - publish_crc_before;
	commit_elapsed = swapz_elapsed_ns(inflight->commit_start_ns,
					 finalize_end);
	ctx->window_commit_wall_ns += commit_elapsed;
	ctx->window_commit_nonio_wall_ns +=
		inflight->prepare_nonio_ns + complete_elapsed;
	ctx->pipeline_active_wall_ns +=
		swapz_elapsed_ns(inflight->lower_start_ns, finalize_end);
	if (lower_end && lower_end >= inflight->lower_start_ns &&
	    lower_end <= finalize_end)
		ctx->pipeline_post_lower_wall_ns +=
			swapz_elapsed_ns(lower_end, finalize_end);

	WRITE_ONCE(inflight->active, false);
	ctx->inflight_count--;
	if (ctx->retained_single_tail_deferred)
		ctx->single_tail_lower_done_seen = true;
	if (error || committed != inflight->count) {
		error = error ? error : -EIO;
		swapz_fail(ctx, error);
		for (index = 0; index < inflight->count; ++index)
			swapz_complete(inflight->bios[index], error);
		inflight->count = 0;
		return error;
	}
	for (index = 0; index < inflight->count; ++index) {
		ctx->logical_write_bytes += SWAPZ_BLOCK_BYTES;
		if (inflight->raw[index])
			ctx->raw_pages++;
		else
			ctx->compressed_pages++;
		swapz_complete(inflight->bios[index], 0);
	}
	ctx->pipeline_completed_runs++;
	inflight->count = 0;
	return 0;
}

static int swapz_finalize_all_inflight(struct swapz_dm *ctx, bool wait)
{
	int first_error = 0;

	while (swapz_has_inflight(ctx)) {
		struct swapz_inflight_write *head = swapz_inflight_head_slot(ctx);
		int error;

		if (!wait && (!head || !completion_done(&head->lower_done)))
			break;
		error = swapz_finalize_inflight_write(ctx, wait);
		if (error && !first_error)
			first_error = error;
		if (!wait && error)
			break;
	}
	return first_error;
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
	region.sector = (sector_t)(ctx->data_start_block + block) * SWAPZ_SECTORS;
	region.count = (sector_t)blocks * SWAPZ_SECTORS;
	/* Inject at the common physical WRITE boundary, including foreground
	 * mixed runs, serialized controls and GC relocation. Never count this
	 * synthetic rejection as submitted/completed lower-device I/O. */
	if (op == REQ_OP_WRITE && ctx->write_fault_nth &&
	    ++ctx->write_fault_calls == ctx->write_fault_nth) {
		ctx->write_fault_injected++;
		return -EIO;
	}
	/* A submitted write may dirty media even if completion later fails. */
	if (op == REQ_OP_WRITE)
		swapz_mark_segments_dirty(ctx, block, blocks);
	/* Cover direct RAW writes and GC relocation as well as engine writes.
	 * The synchronous lower worker exclusively owns read_scratch. */
	if (op == REQ_OP_WRITE)
		swapz_invalidate_read_caches_range(ctx, block, blocks);
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
		unsigned long irq_flags;

		spin_lock_irqsave(&ctx->queue_lock, irq_flags);
		atomic_set(&ctx->lower_write_active, 1);
		ctx->prep_lower_write_samples++;
		ctx->prep_lower_write_start_queued += ctx->preparation_queued;
		if (ctx->preparation_queued)
			ctx->prep_lower_write_start_nonempty++;
		if (ctx->async_prepare && ctx->preparation_queued)
			swapz_queue_preparation_workers(ctx);
		spin_unlock_irqrestore(&ctx->queue_lock, irq_flags);
	}
	if (op == REQ_OP_READ)
		swapz_lower_read_overlap_begin(ctx);
	error = dm_io(&req, 1, &region, &bitmap, IOPRIO_DEFAULT);
	if (op == REQ_OP_WRITE) {
		unsigned long irq_flags;

		spin_lock_irqsave(&ctx->queue_lock, irq_flags);
		ctx->prep_lower_write_end_queued += ctx->preparation_queued;
		if (ctx->preparation_queued)
			ctx->prep_lower_write_end_nonempty++;
		atomic_set(&ctx->lower_write_active, 0);
		spin_unlock_irqrestore(&ctx->queue_lock, irq_flags);
	} else if (op == REQ_OP_READ) {
		swapz_lower_read_overlap_end(ctx);
	}
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
 * valid SWZ extents. The portable engine does NOT publish their logical
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
 * ID29: media reclamation is allowed only after serialized authority has
 * already proven an entire 1MiB segment non-authoritative. DISCARD never
 * creates deadness. Unsupported/media failures are diagnostic and nonfatal;
 * an ownership inconsistency blocks reuse before any new allocation.
 */
static int swapz_discard_dead_segment(void *opaque, swapz_u32 segment)
{
	struct swapz_dm *ctx = opaque;
	struct swapz_authority *a;
	sector_t start_sector, sectors;
	u64 start_ns;
	swapz_u32 block;
	int error;

	if (!ctx || segment >= ctx->segment_count)
		return -EINVAL;
	a = &ctx->authority;
	/*
	 * Reject only ownership that can reference this physical segment. ID29
	 * must not serialize an unrelated K=1 run or staged batch merely because
	 * some other segment has lower I/O in flight.
	 */
	if (a->in_flight &&
	    a->active_start / SWAPZ_SEGMENT_BLOCKS == segment)
		return -EBUSY;
	if ((a->batch_pending || a->batch_replaying) &&
	    a->batch_segment == segment)
		return -EBUSY;
	if (swapz_inflight_uses_segment(ctx, segment))
		return -EBUSY;
	/* Never send TRIM against the segment still named as foreground OPEN.
	 * Reuse remains legal; this rare same-segment wrap simply skips TRIM. */
	if (segment == a->open_segment)
		return 0;
	if (a->segment_mapped_pages && a->segment_mapped_pages[segment])
		return -EUCLEAN;
	for (block = segment * SWAPZ_SEGMENT_BLOCKS;
	     block < (segment + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		if (a->live_records[block])
			return -EUCLEAN;

	swapz_invalidate_read_caches_range(
		ctx, segment * SWAPZ_SEGMENT_BLOCKS, SWAPZ_SEGMENT_BLOCKS);
	ctx->segment_discards_eligible++;
	if (ctx->segment_trimmed && READ_ONCE(ctx->segment_trimmed[segment])) {
		ctx->segment_discards_skipped_already_trimmed++;
		return 0;
	}
	sectors = (sector_t)SWAPZ_SEGMENT_BLOCKS * SWAPZ_SECTORS;
	if (!bdev_max_discard_sectors(ctx->backing->bdev)) {
		ctx->segment_discards_unsupported++;
		return 0;
	}
	start_sector = (sector_t)ctx->data_start_block * SWAPZ_SECTORS +
		(sector_t)segment * sectors;
	ctx->segment_discards_issued++;
	start_ns = ktime_get_ns();
	error = blkdev_issue_discard(ctx->backing->bdev, start_sector, sectors,
				     GFP_NOIO);
	ctx->segment_discard_wall_ns +=
		swapz_elapsed_ns(start_ns, ktime_get_ns());
	if (error == -EOPNOTSUPP) {
		ctx->segment_discards_unsupported++;
		return 0;
	}
	if (error) {
		ctx->segment_discards_failed++;
		return 0;
	}
	ctx->segment_discards_completed++;
	ctx->segment_discard_sectors += sectors;
	if (ctx->segment_trimmed)
		WRITE_ONCE(ctx->segment_trimmed[segment], 1);
	return 0;
}

/* Private read-slot lower adapter. It never mutates target counters: the
 * ordered worker joins the helper and merges these deltas afterwards. */
static int swapz_parallel_lower_read(void *opaque, swapz_u32 block,
				    swapz_u8 blocks, swapz_u8 *destination)
{
	struct swapz_read_slot *slot = opaque;
	struct swapz_dm *ctx = slot->ctx;
	struct dm_io_region region;
	struct dm_io_request req = {
		.bi_opf = REQ_OP_READ | REQ_SWAP | REQ_SYNC,
		.mem = {
			.type = DM_IO_VMA,
			.offset = 0,
			.ptr.vma = destination,
		},
		.notify = { .fn = NULL, .context = NULL },
		.client = ctx->io_client,
	};
	unsigned long bitmap = 0;
	u64 start_ns, elapsed_ns;
	int error;

	if (!blocks || block >= ctx->physical_blocks ||
	    blocks > ctx->physical_blocks - block)
		return -ERANGE;
	region.bdev = ctx->backing->bdev;
	region.sector = (sector_t)(ctx->data_start_block + block) * SWAPZ_SECTORS;
	region.count = (sector_t)blocks * SWAPZ_SECTORS;
	slot->lower_read_submitted_bytes += (u64)blocks * SWAPZ_BLOCK_BYTES;
	slot->lower_read_submitted_reqs++;
	start_ns = ktime_get_ns();
	swapz_lower_read_overlap_begin(ctx);
	error = dm_io(&req, 1, &region, &bitmap, IOPRIO_DEFAULT);
	swapz_lower_read_overlap_end(ctx);
	elapsed_ns = swapz_elapsed_ns(start_ns, ktime_get_ns());
	slot->lower_read_wall_ns += elapsed_ns;
	if (error || bitmap)
		return error ? error : -EIO;
	slot->physical_read_bytes += (u64)blocks * SWAPZ_BLOCK_BYTES;
	slot->physical_read_reqs++;
	return 0;
}

static void swapz_async_lower_read_done(unsigned long error, void *context)
{
	struct swapz_read_slot *slot = context;

	WRITE_ONCE(slot->lower_error, error ? -EIO : 0);
	WRITE_ONCE(slot->lower_end_ns, ktime_get_ns());
	complete(&slot->lower_done);
}

static int swapz_submit_read_slot_range(struct swapz_read_slot *slot,
				       swapz_u8 first_block, swapz_u8 blocks)
{
	struct swapz_dm *ctx = slot->ctx;
	struct dm_io_region region;
	struct dm_io_request req = {
		.bi_opf = REQ_OP_READ | REQ_SWAP | REQ_SYNC,
		.mem = {
			.type = DM_IO_VMA,
			.offset = 0,
			.ptr.vma = slot->engine.read_scratch +
				(size_t)first_block * SWAPZ_BLOCK_BYTES,
		},
		.notify = {
			.fn = swapz_async_lower_read_done,
			.context = slot,
		},
		.client = ctx->io_client,
	};
	int error;

	if (!blocks || first_block >= slot->extent_blocks ||
	    blocks > slot->extent_blocks - first_block ||
	    slot->start_block >= ctx->physical_blocks ||
	    slot->extent_blocks > ctx->physical_blocks - slot->start_block)
		return -EINVAL;
	region.bdev = ctx->backing->bdev;
	region.sector = (sector_t)(ctx->data_start_block +
			      slot->start_block + first_block) *
		SWAPZ_SECTORS;
	region.count = (sector_t)blocks * SWAPZ_SECTORS;
	reinit_completion(&slot->lower_done);
	slot->lower_error = 0;
	slot->lower_first_block = first_block;
	slot->lower_blocks = blocks;
	slot->lower_start_ns = ktime_get_ns();
	slot->lower_end_ns = 0;
	slot->lower_submitted = true;
	slot->lower_read_submitted_bytes += (u64)blocks * SWAPZ_BLOCK_BYTES;
	slot->lower_read_submitted_reqs++;
	error = dm_io(&req, 1, &region, NULL, IOPRIO_DEFAULT);
	if (error) {
		slot->lower_error = error;
		slot->lower_end_ns = ktime_get_ns();
		slot->lower_submitted = false;
	}
	return error;
}

static int swapz_finish_read_slot_range(struct swapz_read_slot *slot)
{
	int error;

	if (!slot->lower_submitted)
		return slot->lower_error;
	wait_for_completion(&slot->lower_done);
	slot->lower_submitted = false;
	slot->lower_read_wall_ns += swapz_elapsed_ns(
		slot->lower_start_ns, READ_ONCE(slot->lower_end_ns));
	error = READ_ONCE(slot->lower_error);
	if (error)
		return error;
	slot->physical_read_bytes += (u64)slot->lower_blocks * SWAPZ_BLOCK_BYTES;
	slot->physical_read_reqs++;
	return swapz_engine_seed_read_range(
		&slot->engine, slot->start_block, slot->extent_blocks,
		slot->lower_first_block, slot->lower_blocks);
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

	if (likely(bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES)) {
		struct bio_vec bv = bio_iter_iovec(bio, bio->bi_iter);
		if (likely(bv.bv_len == SWAPZ_BLOCK_BYTES)) {
			void *mapped = kmap_local_page(bv.bv_page);
			if (to_bio)
				memcpy((u8 *)mapped + bv.bv_offset,
				       buffer, SWAPZ_BLOCK_BYTES);
			else
				memcpy(buffer,
				       (u8 *)mapped + bv.bv_offset, SWAPZ_BLOCK_BYTES);
			kunmap_local(mapped);
			return 0;
		}
	}

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
	if (likely(bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES)) {
		struct bio_vec bv = bio_iter_iovec(bio, bio->bi_iter);
		if (likely(bv.bv_len == SWAPZ_BLOCK_BYTES && bv.bv_offset == 0)) {
			*mapped = kmap_local_page(bv.bv_page);
			return *mapped;
		}
	}
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
static void swapz_delta64_note_score(struct swapz_delta64_stats *stats,
				     swapz_u32 score)
{
	if (score < 8U)
		stats->score_0_7++;
	else if (score < 16U)
		stats->score_8_15++;
	else if (score < SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD)
		stats->score_16_23++;
	else
		stats->score_ge24++;
}

/*
 * Predictor-first rescue: score before ordinary LZ4. High-score pages run
 * delta64+LZ4 first and candidates <=2024 bytes may be adopted directly,
 * genuinely skipping ordinary LZ4. Larger candidates retain the old strict
 * comparison after ordinary LZ4. Lower scores run ordinary LZ4 first and may
 * enter only the existing packing-cliff route.
 */
static int swapz_compress_page(struct swapz_dm *ctx, const u8 *input,
			       u8 *output, u8 *transform_scratch,
			       u8 *candidate_output, void *lz4_workmem,
			       u64 *lz4_wall_ns, swapz_u8 *encoding,
			       struct swapz_delta64_stats *stats,
			       bool *zero)
{
	struct swapz_delta64_route route;
	swapz_u32 score = 0;
	u64 start, elapsed, rescue_wall = 0, saved;
	int baseline, candidate = 0;
	bool high_score = false;

	if (!ctx || !input || !output || !lz4_workmem || !lz4_wall_ns ||
	    !encoding || !zero)
		return -EINVAL;
	*encoding = SWAPZ_ENCODING_LZ4;
	*zero = false;

	if (ctx->delta64_rescue_enabled) {
		if (!transform_scratch || !candidate_output || !stats)
			return -EINVAL;
		start = ktime_get_ns();
		score = swapz_predict_delta64_sample_score(input);
		rescue_wall += swapz_elapsed_ns(start, ktime_get_ns());
		high_score = score >= SWAPZ_PREDICTOR_PRODUCTION_THRESHOLD;
		if (high_score) {
			stats->eligible++;
			swapz_delta64_note_score(stats, score);
			stats->classifier_pass++;
			stats->attempts++;
			start = ktime_get_ns();
			if (swapz_predict_delta64(input, transform_scratch)) {
				elapsed = swapz_elapsed_ns(start, ktime_get_ns());
				stats->transform_wall_ns += elapsed;
				stats->transform_calls++;
				rescue_wall += elapsed;
				goto ordinary;
			}
			elapsed = swapz_elapsed_ns(start, ktime_get_ns());
			stats->transform_wall_ns += elapsed;
			stats->transform_calls++;
			rescue_wall += elapsed;
			start = ktime_get_ns();
			candidate = LZ4_compress_fast(
				transform_scratch, output, SWAPZ_BLOCK_BYTES,
				SWAPZ_MAX_COMPRESSED, ctx->delta64_lz4_acceleration,
				lz4_workmem);
			elapsed = swapz_elapsed_ns(start, ktime_get_ns());
			*lz4_wall_ns += elapsed;
			rescue_wall += elapsed;
			if (candidate > 0 &&
			    candidate <= (int)SWAPZ_PREDICTOR_RESCUE_MIN_LENGTH) {
				if (candidate <= 64 && swapz_page_is_zero(input)) {
					stats->first_lz4_skipped++;
					stats->wall_ns += rescue_wall;
					*zero = true;
					return candidate;
				}
				*encoding = SWAPZ_ENCODING_DELTA64;
				stats->adopted++;
				stats->direct_adopted++;
				stats->first_lz4_skipped++;
				stats->wall_ns += rescue_wall;
				return candidate;
			}
			/*
			 * Ordinary LZ4 will overwrite output. Preserve only a viable
			 * non-direct candidate for the later strict comparison path.
			 */
			if (candidate > 0)
				memcpy(candidate_output, output, (size_t)candidate);
		}
	}

ordinary:
	start = ktime_get_ns();
	baseline = LZ4_compress_fast(input, output, SWAPZ_BLOCK_BYTES,
				     SWAPZ_MAX_COMPRESSED, SWAPZ_ORDINARY_LZ4_ACCELERATION,
				     lz4_workmem);
	*lz4_wall_ns += swapz_elapsed_ns(start, ktime_get_ns());
	if (baseline > 0 && baseline <= 64 && swapz_page_is_zero(input)) {
		*zero = true;
		if (ctx->delta64_rescue_enabled)
			stats->wall_ns += rescue_wall;
		return baseline;
	}
	if (!ctx->delta64_rescue_enabled)
		return baseline;

	if (high_score) {
		if (!candidate || !swapz_delta64_route_init(baseline, &route))
			goto out;
	} else {
		if (!swapz_delta64_route_init(baseline, &route))
			goto out;
		stats->eligible++;
		if (route.pack_path)
			stats->pack_eligible++;
		swapz_delta64_note_score(stats, score);
		if (score < route.threshold)
			goto out;
		stats->classifier_pass++;
		stats->attempts++;
		if (route.pack_path)
			stats->pack_attempts++;
		start = ktime_get_ns();
		if (swapz_predict_delta64(input, transform_scratch)) {
			elapsed = swapz_elapsed_ns(start, ktime_get_ns());
			stats->transform_wall_ns += elapsed;
			stats->transform_calls++;
			rescue_wall += elapsed;
			goto out;
		}
		elapsed = swapz_elapsed_ns(start, ktime_get_ns());
		stats->transform_wall_ns += elapsed;
		stats->transform_calls++;
		rescue_wall += elapsed;
		start = ktime_get_ns();
		candidate = LZ4_compress_fast(
			transform_scratch, candidate_output, SWAPZ_BLOCK_BYTES,
			SWAPZ_MAX_COMPRESSED, ctx->delta64_lz4_acceleration,
			lz4_workmem);
		elapsed = swapz_elapsed_ns(start, ktime_get_ns());
		*lz4_wall_ns += elapsed;
		rescue_wall += elapsed;
	}
	if (!swapz_delta64_candidate_smaller(baseline, candidate))
		goto out;
	if (baseline > 0 && route.pack_limit &&
	    candidate <= (int)route.pack_limit)
		stats->pack_cliff_crossings++;
	if (!swapz_delta64_candidate_adoptable(&route, baseline, candidate))
		goto out;
	memcpy(output, candidate_output, (size_t)candidate);
	*encoding = SWAPZ_ENCODING_DELTA64;
	saved = baseline > 0 ? (u64)baseline : SWAPZ_BLOCK_BYTES;
	saved -= (u64)candidate;
	stats->adopted++;
	if (route.pack_path)
		stats->pack_adopted++;
	stats->payload_bytes_saved += saved;
	if (baseline > 0) {
		stats->lz4_rescues++;
		stats->lz4_payload_bytes_saved += saved;
	} else {
		stats->raw_rescues++;
		stats->raw_payload_bytes_saved += saved;
	}
	baseline = candidate;
out:
	stats->wall_ns += rescue_wall;
	return baseline;
}


/*
 * Asynchronous compression is restricted to an independent, finite producer.
 * It neither acknowledges nor publishes any write. queue_lock transfers a
 * BIO descriptor from preparation_incoming to this worker, which can then
 * read its still-pinned upper BIO data. The ordered consumer waits on its
 * completion and is solely responsible for recycling prepared_page.
 *
 * The array/free mask caps prepared pages to SWAPZ_MAX_RECORDS even under
 * unlimited incoming BIOs. The producer never waits for a slot while
 * holding queue_lock. Tail claims cannot deadlock the FIFO consumer because
 * the ordered worker can keep stealing unclaimed head entries inline without
 * consuming preparation slots, then releases prepared slots as it reaches
 * already-completed entries in admission order.
 */
static void swapz_preparation_worker(struct work_struct *work)
{
	struct swapz_preparation_lane *lane =
		container_of(work, struct swapz_preparation_lane, work);
	struct swapz_dm *ctx = lane->ctx;
	struct swapz_bio_ref *entry;
	unsigned long flags;
	u64 wall_start_ns = ktime_get_ns();
	u64 cpu_start_ns = swapz_worker_cpu_sample();
	int active, peak, observed;

	active = atomic_inc_return(&ctx->preparation_workers_active);
	peak = atomic_read(&ctx->preparation_workers_active_max);
	while (active > peak) {
		observed = atomic_cmpxchg(&ctx->preparation_workers_active_max,
					 peak, active);
		if (observed == peak)
			break;
		peak = observed;
	}

	for (;;) {
		struct swapz_prepared_page *prepared;
		const u8 *input;
		void *mapped_input = NULL;
		u64 section_start;
		bool tail_claim = false;
		bool lower_write_overlap;
		bool lower_read_overlap;
		u64 elapsed_ns;
		int error;
		int slot;

		if (!READ_ONCE(ctx->preparation_queued))
			goto out;
		slot = swapz_preparation_claim_slot(&ctx->preparation_free_mask);
		if (slot < 0)
			goto out;
		prepared = &ctx->preparation_pages[slot];
		spin_lock_irqsave(&ctx->queue_lock, flags);
		if (list_empty(&ctx->preparation_incoming)) {
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			swapz_preparation_release_slot(&ctx->preparation_free_mask, slot);
			goto out;
		}
		/*
		 * Active lower I/O is a head-first overlap signal. A lower READ is
		 * equally useful: the ordered owner is blocked in device service and
		 * cannot steal from preparation_incoming. When no lower I/O is active,
		 * retain the one-credit tail policy and one unclaimed FIFO head.
		 */
		if (atomic_read(&ctx->lower_write_active) ||
		    atomic_read(&ctx->lower_read_active)) {
			atomic_set(&ctx->preparation_tail_credit, 0);
			entry = list_first_entry(&ctx->preparation_incoming,
						 struct swapz_bio_ref,
						 preparation_list);
			ctx->preparation_producer_head_claims++;
		} else {
			if (ctx->preparation_queued < SWAPZ_PREPARATION_TAIL_CLAIM_MIN ||
			    list_is_singular(&ctx->preparation_incoming) ||
			    !atomic_xchg(&ctx->preparation_tail_credit, 0)) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				swapz_preparation_release_slot(
					&ctx->preparation_free_mask, slot);
				goto out;
			}
			entry = list_last_entry(&ctx->preparation_incoming,
						struct swapz_bio_ref,
						preparation_list);
			tail_claim = true;
			ctx->preparation_producer_tail_claims++;
		}
		if (ctx->preparation_queued)
			ctx->preparation_queued--;
		list_del_init(&entry->preparation_list);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);

		input = swapz_map_single_bio_input(entry->bio, &mapped_input);
		if (input) {
			lane->direct_lz4_pages++;
		} else {
			lane->copy_fallback_pages++;
			error = swapz_copy_bio_accounted(entry->bio, lane->input_page,
						 false, &lane->copy_wall_ns,
						 &lane->copy_bytes);
			if (error) {
				swapz_preparation_release_slot(
					&ctx->preparation_free_mask, slot);
				entry->preparation_error = error;
				complete(&entry->preparation_finished);
				if (tail_claim &&
				    !atomic_read(&ctx->lower_write_active) &&
				    !atomic_read(&ctx->lower_read_active) &&
				    !atomic_read(&ctx->preparation_tail_credit))
					goto out;
				continue;
			}
			input = lane->input_page;
		}
		section_start = ktime_get_ns();
		lower_write_overlap = atomic_read(&ctx->lower_write_active);
		lower_read_overlap = atomic_read(&ctx->lower_read_active);
		if (lower_write_overlap)
			lane->prepared_during_lower_write++;
		if (lower_read_overlap)
			lane->prepared_during_lower_read++;
		prepared->length = swapz_compress_page(
			ctx, input, prepared->bytes, lane->predictor_page,
			lane->delta64_candidate_page, lane->lz4_workmem,
			&lane->lz4_wall_ns, &prepared->encoding,
			&lane->delta64, &prepared->zero);
		elapsed_ns = swapz_elapsed_ns(section_start, ktime_get_ns());
		if (lower_write_overlap && atomic_read(&ctx->lower_write_active))
			lane->lower_write_overlap_ns += elapsed_ns;
		if (lower_read_overlap && atomic_read(&ctx->lower_read_active))
			lane->lower_read_overlap_ns += elapsed_ns;
		prepared->payload_crc32c_valid = false;
		if (prepared->length > 0 && !prepared->zero) {
			section_start = ktime_get_ns();
			prepared->payload_crc32c =
				swapz_crc32c_bytes(prepared->bytes, prepared->length);
			lane->crc_wall_ns +=
				swapz_elapsed_ns(section_start, ktime_get_ns());
			prepared->payload_crc32c_valid = true;
		}
		if (prepared->length <= 0)
			swapz_memcpy_accounted(prepared->bytes, input,
					      SWAPZ_BLOCK_BYTES,
					      &lane->copy_wall_ns, &lane->copy_bytes);
		if (mapped_input)
			kunmap_local(mapped_input);
		lane->prepared_pages++;
		entry->prepared_page = prepared;
		entry->preparation_error = 0;
		complete(&entry->preparation_finished);
		if (tail_claim && !atomic_read(&ctx->lower_write_active) &&
		    !atomic_read(&ctx->lower_read_active) &&
		    !atomic_read(&ctx->preparation_tail_credit))
			goto out;
	}
out:
	lane->worker_wall_ns += swapz_elapsed_ns(wall_start_ns, ktime_get_ns());
	lane->worker_cpu_ns +=
		swapz_elapsed_ns(cpu_start_ns, swapz_worker_cpu_sample());
	atomic_dec(&ctx->preparation_workers_active);
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
	swapz_u8 first_unused = 0;

	memset(ctx->used, 0, ctx->batch_count);
	while (position < ctx->batch_count) {
		int largest = -1, partner = -1;
		int best_slack = INT_MAX;
		int min_length = INT_MAX;
		swapz_u8 i;

		while (first_unused < ctx->batch_count &&
		       (ctx->used[first_unused] || ctx->batch[first_unused].raw))
			first_unused++;

		for (i = first_unused; i < ctx->batch_count; ++i) {
			if (!ctx->used[i] && !ctx->batch[i].raw) {
				if (largest < 0 ||
				    ctx->batch[i].length > ctx->batch[largest].length)
					largest = i;
				if (ctx->batch[i].length < min_length)
					min_length = ctx->batch[i].length;
			}
		}
		/* All raw pages go after the compressed DP-planned prefix so
		 * they can share one physically contiguous, deferred lower run. */
		if (largest < 0)
			break;
		ctx->used[largest] = 1;
		ctx->planned_to_batch[position++] = (u8)largest;

		/* SWZ metadata: header(16) + two descriptors(32). */
		if (SWAPZ_BLOCK_BYTES - 48 - ctx->batch[largest].length >= min_length) {
			for (i = first_unused; i < ctx->batch_count; ++i) {
				int remaining;

				if (ctx->used[i] || ctx->batch[i].raw)
					continue;
				remaining = SWAPZ_BLOCK_BYTES - 48 -
					ctx->batch[largest].length - ctx->batch[i].length;
				if (remaining >= 0 && remaining < best_slack) {
					best_slack = remaining;
					partner = i;
					if (remaining == 0)
						break;
				}
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
			.payload_crc32c_valid =
				ctx->batch[index].payload_crc32c_valid,
			.encoding = ctx->batch[index].encoding,
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
	swapz_u8 first_unused = 0;

	if (swapz_window_uniform_compressed(ctx->gc_pending, ctx->gc_count)) {
		for (position = 0; position < ctx->gc_count; ++position)
			ctx->gc_to_pending[position] = position;
		goto materialize;
	}
	memset(ctx->gc_used, 0, ctx->gc_count);
	while (position < ctx->gc_count) {
		int largest = -1, partner = -1, slack_best = INT_MAX;
		int min_length = INT_MAX;

		while (first_unused < ctx->gc_count && ctx->gc_used[first_unused])
			first_unused++;

		for (i = first_unused; i < ctx->gc_count; ++i) {
			if (!ctx->gc_used[i]) {
				if (largest < 0 || ctx->gc_pending[i].length >
				    ctx->gc_pending[largest].length)
					largest = i;
				if (ctx->gc_pending[i].length < min_length)
					min_length = ctx->gc_pending[i].length;
			}
		}
		if (largest < 0)
			break;
		ctx->gc_used[largest] = 1;
		ctx->gc_to_pending[position++] = largest;
		if (SWAPZ_BLOCK_BYTES - 48 - ctx->gc_pending[largest].length >= min_length) {
			for (i = first_unused; i < ctx->gc_count; ++i) {
				int slack;

				if (ctx->gc_used[i])
					continue;
				slack = SWAPZ_BLOCK_BYTES - 48 -
					ctx->gc_pending[largest].length -
					ctx->gc_pending[i].length;
				if (slack >= 0 && slack < slack_best) {
					slack_best = slack;
					partner = i;
					if (slack == 0)
						break;
				}
			}
		}
		if (partner >= 0) {
			ctx->gc_used[partner] = 1;
			ctx->gc_to_pending[position++] = partner;
		}
	}
materialize:
	for (position = 0; position < ctx->gc_count; ++position) {
		swapz_u8 index = ctx->gc_to_pending[position];

		ctx->gc_planned[position] = (struct swapz_compressed_page) {
			.logical_page = ctx->gc_pending[index].logical,
			.payload = ctx->gc_bytes_store +
				(size_t)index * SWAPZ_BLOCK_BYTES,
			.payload_crc32c = ctx->gc_pending[index].payload_crc32c,
			.length = ctx->gc_pending[index].length,
			.payload_crc32c_valid =
				ctx->gc_pending[index].payload_crc32c_valid,
			.encoding = ctx->gc_pending[index].encoding,
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
	swapz_u32 scan, segment, selected = ~(swapz_u32)0;
	swapz_u32 start_probe = ctx->authority.next_segment_probe;
	swapz_u32 best = ~(swapz_u32)0;
	swapz_u16 best_count = ~(swapz_u16)0;

	ctx->gc_choose_calls++;
	if (ctx->authority.segment_gc_live_bytes != ctx->gc_scores ||
	    ctx->authority.segment_gc_io_cost != ctx->gc_io_scores ||
	    ctx->authority.segment_gc_min_live_blocks !=
		    ctx->gc_min_live_blocks ||
	    ctx->authority.segment_mapped_pages != ctx->segment_mapped_pages)
		return -EUCLEAN;
	for (scan = 0; scan < ctx->segment_count; ++scan) {
		swapz_u32 mapped;

		segment = (start_probe + scan) % ctx->segment_count;
		mapped = ctx->segment_mapped_pages[segment];
		swapz_u16 count;
		swapz_u32 score;

		ctx->gc_choose_segment_entries++;
		if (mapped > (swapz_u32)(swapz_u16)~0U)
			return -EUCLEAN;
		count = (swapz_u16)mapped;
		if (!count) {
			if (ctx->gc_scores[segment] ||
			    ctx->gc_io_scores[segment] ||
			    ctx->gc_min_live_blocks[segment])
				return -EUCLEAN;
			continue;
		}
		if (!ctx->gc_scores[segment] || !ctx->gc_io_scores[segment] ||
		    ctx->gc_min_live_blocks[segment] > count)
			return -EUCLEAN;
		if (!ctx->segment_roles[segment] ||
		    segment == ctx->authority.open_segment)
			continue;
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
	ctx->gc_selected_live_records += ctx->segment_mapped_pages[selected];
	ctx->gc_selected_io_cost += ctx->gc_io_scores[selected];
	return 0;
}

static int swapz_gc_relocate_one(struct swapz_dm *ctx, swapz_u32 victim,
				 swapz_u32 logical)
{
	struct swapz_map snapshot;
	swapz_u16 length;
	int error;

	if (logical >= ctx->logical_pages)
		return -EUCLEAN;
	snapshot = ctx->maps[logical];
	if (!snapshot.valid || snapshot.start_block >= ctx->physical_blocks ||
	    snapshot.start_block / SWAPZ_SEGMENT_BLOCKS != victim)
		return -EUCLEAN;
	if (snapshot.raw) {
		error = swapz_gc_flush(ctx);
		if (error)
			return error;
		return swapz_gc_move_raw(ctx, logical, &snapshot);
	}
	error = swapz_engine_read_page(&ctx->engine, logical,
				      ctx->read_compressed,
				      SWAPZ_BLOCK_BYTES, &length);
	if (error)
		return error;
	if (!length || length > SWAPZ_MAX_COMPRESSED)
		return -EUCLEAN;
	memcpy(ctx->gc_bytes_store +
	       (size_t)ctx->gc_count * SWAPZ_BLOCK_BYTES,
	       ctx->read_compressed, length);
	ctx->gc_pending[ctx->gc_count++] =
		(struct swapz_pending_bio) {
			.bio = NULL,
			.logical = logical,
			.payload_crc32c =
				ctx->engine.read_validated_payload_crc32c,
			.length = length,
			.payload_crc32c_valid = 1,
			.encoding = swapz_map_encoding(&snapshot),
		};
	if (ctx->gc_count == SWAPZ_MAX_RECORDS)
		return swapz_gc_flush(ctx);
	return 0;
}

static int swapz_gc_compact_one_inner(struct swapz_dm *ctx)
{
	struct swapz_authority *a = &ctx->authority;
	swapz_u32 old_next, old_open, old_probe, victim, logical, block;
	swapz_u32 expected_victim_pages = 0, visited_victim_pages = 0;
	u64 before_read, before_write;
	u64 before_read_reqs, before_write_reqs;
	u64 choose_start;
	bool rotation_committed = false;
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
	choose_start = ktime_get_ns();
	error = swapz_gc_choose_victim(ctx, &victim);
	ctx->gc_choose_wall_ns +=
		swapz_elapsed_ns(choose_start, ktime_get_ns());
	if (error)
		return error;
	old_next = a->next_block;
	old_open = a->open_segment;
	old_probe = a->next_segment_probe;
	if (a->segment_mapped_pages)
		expected_victim_pages = a->segment_mapped_pages[victim];
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

	if (a->segment_first_page && a->page_next_in_segment) {
		const swapz_u32 none = ~(swapz_u32)0;

		logical = a->segment_first_page[victim];
		while (logical != none) {
			swapz_u32 next;

			if (logical >= ctx->logical_pages ||
			    visited_victim_pages >= expected_victim_pages ||
			    visited_victim_pages >= ctx->logical_pages) {
				error = -EUCLEAN;
				goto out;
			}
			next = a->page_next_in_segment[logical];
			ctx->gc_relocation_map_entries++;
			visited_victim_pages++;
			if (!(visited_victim_pages & 63U))
				cond_resched();
			error = swapz_gc_relocate_one(ctx, victim, logical);
			if (error)
				goto out;
			logical = next;
		}
		if (visited_victim_pages != expected_victim_pages) {
			error = -EUCLEAN;
			goto out;
		}
	} else {
		for (logical = 0; logical < ctx->logical_pages; ++logical) {
			const struct swapz_map *snapshot = &ctx->maps[logical];

			ctx->gc_relocation_map_entries++;
			if (!(logical & 63U))
				cond_resched();
			if (!snapshot->valid ||
			    snapshot->start_block / SWAPZ_SEGMENT_BLOCKS != victim)
				continue;
			error = swapz_gc_relocate_one(ctx, victim, logical);
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
	if (a->segment_mapped_pages) {
		if (victim >= a->segment_count ||
		    a->segment_mapped_pages[victim]) {
			error = -EUCLEAN;
			goto out;
		}
	} else {
		for (logical = 0; logical < ctx->logical_pages; ++logical) {
			const struct swapz_map *m = &ctx->maps[logical];

			if (m->valid &&
			    m->start_block / SWAPZ_SEGMENT_BLOCKS == victim) {
				error = -EUCLEAN;
				goto out;
			}
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
		rotation_committed = true;
		/* Only now is the old foreground victim a dead reserve. */
		error = swapz_discard_dead_segment(ctx, victim);
		if (error) {
			swapz_fail(ctx, error);
			goto out;
		}
		ctx->last_gc_victim = victim;
		ctx->last_gc_destination = destination;
		if (ctx->gc_segment_evictions[victim] != U32_MAX)
			ctx->gc_segment_evictions[victim]++;
		ctx->gc_role_rotations++;
	}
	ctx->gc_victims++;
out:
	ctx->gc_read_bytes += ctx->physical_read_bytes - before_read;
	ctx->gc_write_bytes += ctx->physical_write_bytes - before_write;
	ctx->gc_read_reqs += ctx->physical_read_reqs - before_read_reqs;
	ctx->gc_write_reqs += ctx->physical_write_reqs - before_write_reqs;
	ctx->gc_count = 0;
	if (error && !rotation_committed) {
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

/* Measure every foreground compaction attempt in one place, including RAW
 * callers and failed/no-headroom attempts. The metric is wall residency of the
 * existing serialized GC path, not scheduler CPU time. */
static int swapz_gc_compact_one(struct swapz_dm *ctx)
{
	u64 start_ns = ktime_get_ns();
	int error = swapz_gc_compact_one_inner(ctx);

	ctx->gc_wall_ns += swapz_elapsed_ns(start_ns, ktime_get_ns());
	return error;
}


static void swapz_window_admit_clock(struct swapz_dm *ctx)
{
	/* Serialized worker: do not refresh the start for later records. */
	if (!ctx->batch_count)
		ctx->window_first_ns = ktime_get_ns();
}

static void swapz_account_single_tail_terminal(struct swapz_dm *ctx,
					       bool companion,
					       bool deadline);

static int swapz_flush_window(struct swapz_dm *ctx)
{
	swapz_u8 committed = 0, index, count = ctx->batch_count;
	swapz_u8 gc_attempts = 0;
	bool needs_fua = false;
	bool packed_close = ctx->next_window_close == SWAPZ_CLOSE_PACK_READY;
	enum swapz_pack_close_cause pack_close_cause =
		ctx->next_pack_close_cause;
	enum swapz_burst_close_site burst_close_site =
		ctx->next_burst_close_site;
	swapz_u8 burst_close_target = ctx->next_burst_close_target;
	bool win1_pack_tail_target = count == 1U && packed_close &&
		ctx->retained_tail_target == 1U;
	bool win1_pack_read_bypass = count == 1U && packed_close &&
		!ctx->retained_tail_target && ctx->retained_window_read_bypasses;
	bool win1_pack_wave_interrupted = count == 1U && packed_close &&
		!ctx->retained_tail_target && !ctx->retained_window_read_bypasses &&
		ctx->retained_wave_interrupted;
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
	bool ordering_boundary =
		close_reason == SWAPZ_CLOSE_FUA ||
		close_reason == SWAPZ_CLOSE_PREFLUSH ||
		close_reason == SWAPZ_CLOSE_DISCARD ||
		close_reason == SWAPZ_CLOSE_SHUTDOWN ||
		close_reason == SWAPZ_CLOSE_OTHER;
	bool hard_boundary =
		ordering_boundary ||
		close_reason == SWAPZ_CLOSE_DEADLINE ||
		close_reason == SWAPZ_CLOSE_IDLE ||
		close_reason == SWAPZ_CLOSE_QUANTUM;
	bool chain_continues;
	bool deferred_single_tail = ctx->retained_single_tail_deferred;
	bool async_submitted = false;
	bool async_detach_ready;
	struct swapz_inflight_write *detached_inflight = NULL;
	int error = 0;

	/*
	 * An empty flush cannot form another physical run. Preserve the original
	 * drain boundary for empty barriers/reads; a nonempty write window decides
	 * below whether the depth=2 diagnostic can safely append one more run.
	 */
	if (!count && swapz_has_inflight(ctx)) {
		error = swapz_finalize_all_inflight(ctx, true);
		if (error)
			return error;
	}
	/*
	 * Learned singleton bypass describes one uninterrupted admission stream.
	 * Explicit ordering boundaries end that stream even when they carry no
	 * data window, while ordinary IDLE/DEADLINE closes intentionally retain
	 * the learned QD1 behavior.
	 */
	if (ordering_boundary) {
		ctx->singleton_deadline_streak = 0;
		ctx->singleton_fast_close = false;
	}
	if (deferred_single_tail && (count || hard_boundary)) {
		if (count == 1U && close_reason == SWAPZ_CLOSE_DEADLINE) {
			ctx->win1_deadline_deferred_tail++;
			swapz_account_single_tail_terminal(ctx, false, true);
		} else if (count == 1U && close_reason == SWAPZ_CLOSE_IDLE) {
			ctx->win1_idle_deferred_tail++;
			swapz_account_single_tail_terminal(ctx, false, false);
		} else {
			ctx->single_tail_other_clears++;
			swapz_account_single_tail_terminal(ctx, false, false);
		}
		ctx->retained_single_tail_deferred = false;
	}

	/*
	 * An empty flush is not a committed write window. In particular, a READ
	 * or zero-page immediately after PACK_READY must not erase the serviced
	 * chain before the ordered worker can observe already-accepted followers.
	 * Real ordering barriers still terminate scheduling evidence.
	 */
	if (!count) {
		if (hard_boundary) {
			if (!swapz_has_inflight(ctx))
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
		ctx->next_pack_close_cause = SWAPZ_PACK_CLOSE_NONE;
		ctx->next_burst_close_site = SWAPZ_BURST_CLOSE_NONE;
		ctx->next_burst_close_target = 0;
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
	if (packed_close) {
		switch (pack_close_cause) {
		case SWAPZ_PACK_CLOSE_TAIL_TARGET:
			ctx->pack_close_tail_target++;
			if (count <= 4U)
				ctx->pack_close_tail_target_le4++;
			break;
		case SWAPZ_PACK_CLOSE_BURST_TARGET:
			ctx->pack_close_burst_target++;
			if (burst_close_site == SWAPZ_BURST_CLOSE_ADMISSION)
				ctx->pack_close_burst_admission++;
			else if (burst_close_site == SWAPZ_BURST_CLOSE_WORKER)
				ctx->pack_close_burst_worker++;
			if (burst_close_target <= 4U)
				ctx->pack_close_burst_target_le4++;
			else if (burst_close_target <= 8U)
				ctx->pack_close_burst_target_5_8++;
			else if (burst_close_target <= 16U)
				ctx->pack_close_burst_target_9_16++;
			else
				ctx->pack_close_burst_target_17_64++;
			if (count <= 4U)
				ctx->pack_close_burst_count_le4++;
			else if (count <= 8U)
				ctx->pack_close_burst_count_5_8++;
			else if (count <= 16U)
				ctx->pack_close_burst_count_9_16++;
			else
				ctx->pack_close_burst_count_17_64++;
			if (burst_close_target && count > burst_close_target)
				ctx->pack_close_burst_overshoot++;
			break;
		case SWAPZ_PACK_CLOSE_SERVICE_DRY:
			ctx->pack_close_service_dry++;
			break;
		default:
			break;
		}
	}
	ctx->next_pack_close_cause = SWAPZ_PACK_CLOSE_NONE;
	ctx->next_burst_close_site = SWAPZ_BURST_CLOSE_NONE;
	ctx->next_burst_close_target = 0;
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
	async_detach_ready =
		ctx->async_prepare && READ_ONCE(ctx->accepting) &&
		(count > 4U || READ_ONCE(ctx->preparation_queued) > 0U) &&
		!needs_fua && ctx->engine.bulk_enabled &&
		!ctx->engine.verify_after_write &&
		(close_reason == SWAPZ_CLOSE_FULL ||
		 close_reason == SWAPZ_CLOSE_DUPLICATE ||
		 close_reason == SWAPZ_CLOSE_QUANTUM ||
		 close_reason == SWAPZ_CLOSE_IDLE ||
		 close_reason == SWAPZ_CLOSE_DEADLINE ||
		 close_reason == SWAPZ_CLOSE_PACK_READY);
	/*
	 * The read-bypass guard is fixed after the two-host A/B showed no service
	 * benefit from relaxing it. Keep passive pressure attribution, but do not
	 * carry an alternate scheduling branch in production.
	 */
	if (async_detach_ready && ctx->retained_window_read_bypasses &&
	    swapz_has_inflight(ctx))
		ctx->pipeline_read_bypass_skips++;

	if (swapz_has_inflight(ctx)) {
		struct swapz_inflight_write *head = swapz_inflight_head_slot(ctx);
		bool k1_ready_wait = SWAPZ_WRITE_PIPELINE_DEPTH == 1U && count &&
			head && !completion_done(&head->lower_done);
		u64 wait_before = ctx->pipeline_finalize_wait_wall_ns;

		error = swapz_finalize_all_inflight(ctx, true);
		if (k1_ready_wait) {
			u64 waited = ctx->pipeline_finalize_wait_wall_ns - wait_before;

			ctx->k1_ready_wait_windows++;
			ctx->k1_ready_wait_records += count;
			ctx->k1_ready_wait_wall_ns += waited;
			ctx->k1_ready_wait_max_records =
				max_t(u64, ctx->k1_ready_wait_max_records, count);
			switch (close_reason) {
			case SWAPZ_CLOSE_PACK_READY:
				ctx->k1_ready_wait_pack_ready++;
				break;
			case SWAPZ_CLOSE_FULL:
				ctx->k1_ready_wait_full++;
				break;
			case SWAPZ_CLOSE_DEADLINE:
				ctx->k1_ready_wait_deadline++;
				break;
			case SWAPZ_CLOSE_FUA:
			case SWAPZ_CLOSE_PREFLUSH:
			case SWAPZ_CLOSE_DISCARD:
			case SWAPZ_CLOSE_SHUTDOWN:
				ctx->k1_ready_wait_fence++;
				break;
			default:
				ctx->k1_ready_wait_other++;
				break;
			}
		}
		if (error)
			goto commit_done;
	}
	/*
	 * Only a complete multi-record window with no hard immediate fence and no
	 * read bypass is detached. If geometry yields only a prefix, complete that
	 * prefix synchronously and keep the existing retry path for the remainder.
	 */
	if (async_detach_ready &&
	    (!ctx->retained_window_read_bypasses || !swapz_has_inflight(ctx))) {
		struct swapz_inflight_write *inflight =
			swapz_inflight_tail_slot(ctx);
		swapz_u8 prior_inflight_count = ctx->inflight_count;
		swapz_u8 prepared = 0;
		u64 plan_before = ctx->engine.plan_wall_ns;
		u64 pack_before = ctx->engine.pack_wall_ns;
		u64 prepare_start = ktime_get_ns();
		u64 prepare_elapsed;

		if (!inflight) {
			error = -EUCLEAN;
			goto commit_done;
		}
		inflight->commit_start_ns = prepare_start;
		error = swapz_engine_prepare_batched_run(
			&ctx->engine, ctx->planned, count, &inflight->run,
			&prepared, planning_read_cap);
		prepare_elapsed = swapz_elapsed_ns(prepare_start, ktime_get_ns());
		ctx->engine_plan_wall_ns +=
			ctx->engine.plan_wall_ns - plan_before;
		ctx->engine_pack_wall_ns +=
			ctx->engine.pack_wall_ns - pack_before;
		if (!error && prepared == count) {
			inflight->prepare_nonio_ns = prepare_elapsed;
			inflight->count = count;
			error = swapz_submit_inflight_write(ctx, inflight);
			if (!error) {
				committed = count; /* ownership detached, not ACKed */
				async_submitted = true;
				detached_inflight = inflight;
			} else {
				u64 complete_start = ktime_get_ns();
				int complete_error;

				if (prior_inflight_count)
					complete_error =
						swapz_engine_abort_batched_run_tail(
							&ctx->engine,
							&inflight->run);
				else {
					swapz_u8 aborted = 0;

					complete_error =
						swapz_engine_complete_batched_run(
							&ctx->engine,
							&inflight->run, 0,
							error, &aborted);
				}
				ctx->window_commit_nonio_wall_ns +=
					prepare_elapsed +
					swapz_elapsed_ns(complete_start,
							 ktime_get_ns());
				if (complete_error)
					error = complete_error;
				inflight->count = 0;
			}
		} else if (!error && prepared) {
			swapz_u16 completed_blocks = 0;
			swapz_u8 published = 0;
			u64 complete_start;
			int io_error;

			if (prior_inflight_count) {
				int older_error =
					swapz_finalize_all_inflight(ctx, true);

				if (older_error) {
					swapz_u8 aborted = 0;
					int cleanup = swapz_engine_complete_batched_run(
						&ctx->engine, &inflight->run, 0,
						older_error, &aborted);

					error = cleanup ? cleanup : older_error;
					goto commit_done;
				}
			}
			ctx->engine.submitted_blocks += inflight->run.blocks;
			io_error = swapz_lower_write_run(
				ctx, inflight->run.start_block,
				inflight->run.blocks, inflight->run.bytes,
				&completed_blocks);
			complete_start = ktime_get_ns();
			error = swapz_engine_complete_batched_run(
				&ctx->engine, &inflight->run, completed_blocks,
				io_error, &published);
			ctx->window_commit_nonio_wall_ns +=
				prepare_elapsed +
				swapz_elapsed_ns(complete_start, ktime_get_ns());
			if (!error) {
				committed = published;
				if (published != prepared)
					error = -EUCLEAN;
			}
		}
		if (error == -ENOSPC && prior_inflight_count) {
			int older_error = swapz_finalize_all_inflight(ctx, true);

			if (older_error) {
				error = older_error;
				goto commit_done;
			}
		}
		if (error && error != -ENOSPC)
			goto commit_done;
		if (error == -ENOSPC)
			error = 0; /* existing loop/GC path retries unchanged */
	}
	while (!async_submitted && committed < count) {
		swapz_u8 succeeded = 0;

		u64 lower_write_before = ctx->lower_write_wall_ns;
		u64 plan_before = ctx->engine.plan_wall_ns;
		u64 pack_before = ctx->engine.pack_wall_ns;
		u64 publish_before = ctx->engine.publish_wall_ns;
		u64 publish_crc_before = ctx->authority.publish_crc_wall_ns;
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
		if (ctx->authority.publish_crc_wall_ns >= publish_crc_before)
			ctx->engine_publish_crc_wall_ns +=
				ctx->authority.publish_crc_wall_ns - publish_crc_before;
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
			error = swapz_gc_compact_one(ctx);
			if (!error)
				continue;
		}
		break;
	}
commit_done:
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

		if (async_submitted) {
			detached_inflight->bios[index] = bio;
			detached_inflight->raw[index] = ctx->planned[index].raw;
		} else if (index < committed && !ctx->failed) {
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
		if (close_reason == SWAPZ_CLOSE_PACK_READY) {
			if (win1_pack_tail_target)
				ctx->win1_pack_tail_target++;
			else if (win1_pack_read_bypass)
				ctx->win1_pack_read_bypass++;
			else if (win1_pack_wave_interrupted)
				ctx->win1_pack_wave_interrupted++;
		}
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
	 * READ service evidence belongs to the write window that was just
	 * committed. Never carry it into the next nonempty window: stale bypass
	 * evidence can otherwise authorize a false service-dry close or block a
	 * K=1 detach before the new window has serviced any READ. Empty flushes
	 * returned above retain their separate boundary semantics.
	 */
	ctx->retained_window_read_bypasses = 0;
	if (!ctx->retain_ms || hard_boundary ||
	    (packed_close && !ctx->worker_has_immediate_followup)) {
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
static void swapz_reset_single_tail_observation(struct swapz_dm *ctx)
{
	ctx->single_tail_deferred_start_ns = 0;
	ctx->single_tail_lower_done_seen = false;
	ctx->single_tail_read_bypass_seen = false;
}

static void swapz_account_single_tail_terminal(struct swapz_dm *ctx,
					       bool companion,
					       bool deadline)
{
	u64 now = ktime_get_ns();
	u64 elapsed = ctx->single_tail_deferred_start_ns &&
		now >= ctx->single_tail_deferred_start_ns ?
		now - ctx->single_tail_deferred_start_ns : 0;
	u64 *le250, *to500, *to1000, *gt1000;

	if (!companion && !deadline) {
		swapz_reset_single_tail_observation(ctx);
		return;
	}
	if (companion) {
		le250 = &ctx->single_tail_companion_age_le250us;
		to500 = &ctx->single_tail_companion_age_251_500us;
		to1000 = &ctx->single_tail_companion_age_501_1000us;
		gt1000 = &ctx->single_tail_companion_age_gt1000us;
		if (ctx->single_tail_lower_done_seen)
			ctx->single_tail_companion_after_lower_done++;
		if (ctx->single_tail_read_bypass_seen)
			ctx->single_tail_companion_after_read_bypass++;
		if (ctx->single_tail_lower_done_seen &&
		    ctx->single_tail_read_bypass_seen)
			ctx->single_tail_companion_after_both++;
	} else {
		le250 = &ctx->single_tail_deadline_age_le250us;
		to500 = &ctx->single_tail_deadline_age_251_500us;
		to1000 = &ctx->single_tail_deadline_age_501_1000us;
		gt1000 = &ctx->single_tail_deadline_age_gt1000us;
		if (ctx->single_tail_lower_done_seen)
			ctx->single_tail_deadline_after_lower_done++;
		if (ctx->single_tail_read_bypass_seen)
			ctx->single_tail_deadline_after_read_bypass++;
		if (ctx->single_tail_lower_done_seen &&
		    ctx->single_tail_read_bypass_seen)
			ctx->single_tail_deadline_after_both++;
	}
	if (elapsed <= 250000ULL)
		(*le250)++;
	else if (elapsed <= 500000ULL)
		(*to500)++;
	else if (elapsed <= 1000000ULL)
		(*to1000)++;
	else {
		(*gt1000)++;
		if (companion) {
			if (elapsed <= 1250000ULL)
				ctx->single_tail_companion_age_1001_1250us++;
			else if (elapsed <= 1500000ULL)
				ctx->single_tail_companion_age_1251_1500us++;
			else if (elapsed <= 1750000ULL)
				ctx->single_tail_companion_age_1501_1750us++;
			else
				ctx->single_tail_companion_age_gt1750us++;
		}
	}
	swapz_reset_single_tail_observation(ctx);
}

static void swapz_note_single_tail_read_bypass(struct swapz_dm *ctx)
{
	if (ctx->retained_single_tail_deferred)
		ctx->single_tail_read_bypass_seen = true;
}

static void swapz_sample_pack_tail_locked(struct swapz_dm *ctx,
					  struct list_head *local)
{
	struct swapz_bio_ref *entry;
	swapz_u8 tail = 0;
	swapz_u8 room;
	bool prefix_open = true;
	bool inflight;

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
	/*
	 * ID56 is observation only. In particular, do not defer/consume a sample
	 * differently based on K=1 state here: first measure whether async is
	 * actually declaring an empty post-PACK_READY tail before its detached
	 * lower write and upper completions have finished.
	 */
	inflight = swapz_has_inflight(ctx);
	/*
	 * Any tail while detached K=1 is still unfinalized is premature: upper
	 * BIO completions have not been delivered via bio_endio() yet and cannot
	 * have yielded their next wave. Keep the PACK_READY sample pending until
	 * swapz_finalize_inflight_write() has completed the upper BIOs.
	 */
	if (inflight)
		return;
	ctx->pack_tail_samples++;
	if (!tail) {
		/*
		 * A zero tail while detached K=1 is incomplete returned above, so
		 * every counted zero is completion-aware idle evidence.
		 */
		ctx->pack_tail_zero_idle++;
	} else if (tail == 1U) {
		if (inflight)
			ctx->pack_tail_one_inflight++;
		else
			ctx->pack_tail_one_idle++;
	} else if (inflight) {
		ctx->pack_tail_many_inflight++;
	} else {
		ctx->pack_tail_many_idle++;
	}
	/* A later sample supersedes any still-open deferred singleton. Account
	 * that old lifecycle before starting a new one so cumulative counters
	 * conserve exactly at quiescent boundaries. */
	if (ctx->retained_single_tail_deferred) {
		ctx->single_tail_other_clears++;
		ctx->retained_single_tail_deferred = false;
		swapz_account_single_tail_terminal(ctx, false, false);
	}
	if (tail) {
		swapz_u8 old_target = ctx->retained_burst_target;

		ctx->retained_burst_target = swapz_window_grow_burst_target(
			ctx->retained_burst_target, ctx->retained_chain_completed,
			tail, ctx->max_window);
		if (ctx->retained_burst_target != old_target)
			ctx->burst_target_grows++;
		if (tail == 1U) {
			ctx->retained_tail_target = 0;
			ctx->single_tail_deferrals++;
			ctx->single_tail_deferred_start_ns = ktime_get_ns();
			ctx->single_tail_lower_done_seen = false;
			ctx->single_tail_read_bypass_seen = false;
			ctx->retained_single_tail_deferred = true;
		} else {
			ctx->retained_tail_target = tail;
		}
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
	if (ctx->retained_single_tail_deferred && ctx->batch_count == 1U)
		return false;
	return swapz_window_burst_close_ready(
		ctx->single_pack_deferred, 0,
		ctx->batch_count, ctx->retained_burst_target,
		ctx->retained_tail_target);
}

static bool swapz_service_proven_dry_pack(const struct swapz_dm *ctx)
{
	return !ctx->retained_tail_target && ctx->batch_count &&
		(((ctx->retained_chain_completed ||
		   ctx->retained_window_read_bypasses) &&
		  (ctx->single_pack_deferred ||
		   ctx->accepted_burst_pack_ready)) ||
		 ((ctx->retained_window_read_bypasses ||
		   ctx->retained_wave_interrupted) &&
		  ctx->batch_count < 4U));
}

static bool swapz_retained_pack_close_ready(struct swapz_dm *ctx)
{
	bool service_proven_dry_pack;

	if (ctx->retained_single_tail_deferred && ctx->batch_count == 1U)
		return false;
	service_proven_dry_pack = swapz_service_proven_dry_pack(ctx);
	return swapz_window_burst_close_ready(
		ctx->single_pack_deferred, service_proven_dry_pack,
		ctx->batch_count, ctx->retained_burst_target,
		ctx->retained_tail_target);
}

static void swapz_resolve_single_tail_companion(struct swapz_dm *ctx)
{
	if (!ctx->retained_single_tail_deferred || ctx->batch_count < 2U)
		return;
	ctx->single_tail_companions++;
	swapz_account_single_tail_terminal(ctx, true, false);
	ctx->retained_single_tail_deferred = false;
}

static int swapz_accept_write(struct swapz_dm *ctx, struct bio *bio)
{
	swapz_u32 logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	struct swapz_bio_ref *entry = dm_per_bio_data(bio, sizeof(*entry));
	const u8 *input = NULL;
	void *mapped_input = NULL;
	swapz_u8 i;
	u64 section_start;
	swapz_u32 payload_crc32c = 0;
	bool payload_crc32c_valid = false;
	swapz_u8 encoding = SWAPZ_ENCODING_LZ4;
	bool inline_zero = false;
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
		payload_crc32c = entry->prepared_page->payload_crc32c;
		payload_crc32c_valid = entry->prepared_page->payload_crc32c_valid;
		encoding = entry->prepared_page->encoding;
		if (length > 0 && !entry->prepared_page->zero)
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
			ctx->ordered_copy_fallback_pages++;
			error = swapz_copy_bio_accounted(
				bio, ctx->input_page, false,
				&ctx->ordered_write_copy_wall_ns,
				&ctx->ordered_write_copy_bytes);
			if (error)
				return error;
			input = ctx->input_page;
		}
		length = swapz_compress_page(
			ctx, input,
			ctx->batch_bytes +
				(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
			ctx->predictor_page, ctx->delta64_candidate_page,
			ctx->lz4_workmem, &ctx->lz4_wall_ns, &encoding,
			&ctx->ordered_delta64, &inline_zero);
		if (length > 0 && !inline_zero) {
			section_start = ktime_get_ns();
			payload_crc32c = swapz_crc32c_bytes(
				ctx->batch_bytes +
					(size_t)ctx->batch_count * SWAPZ_BLOCK_BYTES,
				(swapz_u32)length);
			ctx->ordered_crc_wall_ns +=
				swapz_elapsed_ns(section_start, ktime_get_ns());
			payload_crc32c_valid = true;
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
		swapz_u32 old_segment = ~(swapz_u32)0;
		bool became_dead = false;

		ctx->next_window_close = SWAPZ_CLOSE_ZERO;
		error = swapz_flush_window(ctx);
		if (!error) {
			const struct swapz_map *old = &ctx->maps[logical];

			/*
			 * Mirror upper DISCARD: after all older accepted writes are
			 * committed, snapshot whether removing this mapping kills a
			 * closed segment. The advisory TRIM occurs only after authority
			 * has removed the final live mapping.
			 */
			if (old->valid && ctx->segment_mapped_pages) {
				old_segment =
					old->start_block / SWAPZ_SEGMENT_BLOCKS;
				became_dead =
					ctx->segment_mapped_pages[old_segment] == 1U;
			}
			error = swapz_discard_page(&ctx->authority, logical);
		}
		if (!error && became_dead &&
		    old_segment != ctx->authority.open_segment)
			error = swapz_discard_dead_segment(ctx, old_segment);
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
			.raw = 1,
		};
		swapz_resolve_single_tail_companion(ctx);
		if (swapz_has_inflight(ctx))
			ctx->pipeline_collected_pages++;
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
		.payload_crc32c_valid = payload_crc32c_valid,
		.encoding = encoding,
	};
	ctx->batch_count++;
	swapz_resolve_single_tail_companion(ctx);
	if (swapz_has_inflight(ctx))
		ctx->pipeline_collected_pages++;
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
		    !ctx->worker_has_immediate_followup &&
		    !(SWAPZ_WRITE_PIPELINE_DEPTH == 1U &&
		      swapz_inflight_lower_pending(ctx))) {
			ctx->next_pack_close_cause = ctx->retained_tail_target ?
				SWAPZ_PACK_CLOSE_TAIL_TARGET :
				SWAPZ_PACK_CLOSE_BURST_TARGET;
			if (ctx->next_pack_close_cause ==
			    SWAPZ_PACK_CLOSE_BURST_TARGET) {
				ctx->next_burst_close_site =
					SWAPZ_BURST_CLOSE_ADMISSION;
				ctx->next_burst_close_target =
					ctx->retained_burst_target;
			}
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
		if (swapz_map_encoding(map) == SWAPZ_ENCODING_DELTA64) {
			if (!ctx->predictor_page)
				return -EUCLEAN;
			decompressed = LZ4_decompress_safe(ctx->read_compressed,
						  ctx->predictor_page,
						  payload_bytes,
						  SWAPZ_BLOCK_BYTES);
			if (decompressed == SWAPZ_BLOCK_BYTES)
				swapz_unpredict_delta64(ctx->predictor_page,
						       ctx->read_page);
		} else {
			decompressed = LZ4_decompress_safe(ctx->read_compressed,
						  ctx->read_page,
						  payload_bytes,
						  SWAPZ_BLOCK_BYTES);
		}
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

static void swapz_read_slot_prepare(struct swapz_read_slot *slot,
				    swapz_u32 start_block,
				    swapz_u8 extent_blocks)
{
	swapz_engine_invalidate_read_cache(&slot->engine);
	slot->bio_count = 0;
	slot->start_block = start_block;
	slot->extent_blocks = extent_blocks;
	slot->error = 0;
	slot->lower_error = 0;
	slot->lower_first_block = 0;
	slot->lower_blocks = 0;
	slot->lower_submitted = false;
	slot->lower_start_ns = 0;
	slot->lower_end_ns = 0;
	slot->lower_read_submitted_bytes = 0;
	slot->lower_read_submitted_reqs = 0;
	slot->physical_read_bytes = 0;
	slot->physical_read_reqs = 0;
	slot->lower_read_wall_ns = 0;
	slot->read_engine_nonio_wall_ns = 0;
	slot->decode_wall_ns = 0;
}

static int swapz_read_slot_run(struct swapz_read_slot *slot)
{
	struct swapz_dm *ctx = slot->ctx;
	swapz_u8 index;

	if (!slot->bio_count || slot->bio_count > SWAPZ_MAX_RECORDS)
		return -EINVAL;
	for (index = 0; index < slot->bio_count; ++index) {
		struct bio *bio = slot->bios[index];
		swapz_u32 logical =
			(swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
		const struct swapz_map *map = &ctx->maps[logical];
		swapz_u8 *read_page = slot->read_pages +
			(size_t)index * SWAPZ_BLOCK_BYTES;
		swapz_u16 payload_bytes = 0;
		u64 lower_before, engine_start, engine_elapsed, lower_elapsed;
		u64 section_start;
		int error, decompressed;

		if (!map->valid || map->raw ||
		    map->start_block != slot->start_block ||
		    map->extent_blocks != slot->extent_blocks)
			return -ESTALE;
		lower_before = slot->lower_read_wall_ns;
		engine_start = ktime_get_ns();
		error = swapz_engine_read_page(&slot->engine, logical,
				slot->read_compressed, SWAPZ_BLOCK_BYTES,
				&payload_bytes);
		engine_elapsed = swapz_elapsed_ns(engine_start, ktime_get_ns());
		lower_elapsed = slot->lower_read_wall_ns - lower_before;
		if (engine_elapsed >= lower_elapsed)
			slot->read_engine_nonio_wall_ns += engine_elapsed - lower_elapsed;
		if (error)
			return error;
		section_start = ktime_get_ns();
		if (swapz_map_encoding(map) == SWAPZ_ENCODING_DELTA64) {
			if (!slot->predictor_page)
				return -EUCLEAN;
			decompressed = LZ4_decompress_safe(slot->read_compressed,
						 slot->predictor_page,
						 payload_bytes,
						 SWAPZ_BLOCK_BYTES);
			if (decompressed == SWAPZ_BLOCK_BYTES)
				swapz_unpredict_delta64(slot->predictor_page,
						       read_page);
		} else {
			decompressed = LZ4_decompress_safe(slot->read_compressed,
						 read_page, payload_bytes,
						 SWAPZ_BLOCK_BYTES);
		}
		slot->decode_wall_ns +=
			swapz_elapsed_ns(section_start, ktime_get_ns());
		if (decompressed != SWAPZ_BLOCK_BYTES)
			return -EBADMSG;
	}
	return 0;
}

static void swapz_merge_read_slot(struct swapz_dm *ctx,
				  struct swapz_read_slot *slot,
				  bool absorb_cache)
{
	ctx->lower_read_submitted_bytes += slot->lower_read_submitted_bytes;
	ctx->lower_read_submitted_reqs += slot->lower_read_submitted_reqs;
	ctx->physical_read_bytes += slot->physical_read_bytes;
	ctx->physical_read_reqs += slot->physical_read_reqs;
	ctx->lower_read_wall_ns += slot->lower_read_wall_ns;
	ctx->read_engine_nonio_wall_ns += slot->read_engine_nonio_wall_ns;
	ctx->decode_wall_ns += slot->decode_wall_ns;
	if (absorb_cache)
		swapz_engine_absorb_read_slot(&ctx->engine, &slot->engine);
	else
		swapz_engine_merge_read_telemetry(&ctx->engine, &slot->engine);
	slot->lower_read_submitted_bytes = 0;
	slot->lower_read_submitted_reqs = 0;
	slot->physical_read_bytes = 0;
	slot->physical_read_reqs = 0;
	slot->lower_read_wall_ns = 0;
	slot->read_engine_nonio_wall_ns = 0;
	slot->decode_wall_ns = 0;
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
	 * page and restore temporary liveness accounting before committing the
	 * first generation or persistent refcount change.
	 */
	{
		sector_t check_sector = sector;
		sector_t check_remaining = remaining;
		sector_t restore_sector;
		int check_error = 0;

		/*
		 * Account shared extents by temporarily consuming one live-record
		 * reference per validated logical page. The ordered worker is the sole
		 * authority mutator and this pass performs no I/O, so the exact prefix
		 * is restored before either returning or committing the discard.
		 */
		while (check_remaining) {
			swapz_u32 logical = (swapz_u32)(check_sector / SWAPZ_SECTORS);
			const struct swapz_map *m = &ctx->maps[logical];

			if (m->generation == ~(swapz_u32)0) {
				check_error = -EOVERFLOW;
				break;
			}
			if (m->valid) {
				swapz_u32 start = m->start_block;

				if (start >= ctx->physical_blocks ||
				    (m->extent_blocks != 1 &&
				     m->extent_blocks != 2 &&
				     m->extent_blocks != 4) ||
				    ctx->extent_classes[start] != m->extent_blocks ||
				    !ctx->live_records[start]) {
					check_error = -EUCLEAN;
					break;
				}
				ctx->live_records[start]--;
			}
			check_sector += SWAPZ_SECTORS;
			check_remaining -= SWAPZ_SECTORS;
		}
		for (restore_sector = sector; restore_sector < check_sector;
		     restore_sector += SWAPZ_SECTORS) {
			swapz_u32 logical =
				(swapz_u32)(restore_sector / SWAPZ_SECTORS);
			const struct swapz_map *m = &ctx->maps[logical];

			if (m->valid)
				ctx->live_records[m->start_block]++;
		}
		if (check_error)
			return check_error;
	}
	while (remaining) {
		swapz_u32 logical =
			(swapz_u32)(sector / SWAPZ_SECTORS);
		const struct swapz_map *old = &ctx->maps[logical];
		swapz_u32 old_segment = ~(swapz_u32)0;
		bool became_dead = false;

		if (old->valid && ctx->segment_mapped_pages) {
			old_segment = old->start_block / SWAPZ_SEGMENT_BLOCKS;
			became_dead =
				ctx->segment_mapped_pages[old_segment] == 1U;
		}
		error = swapz_discard_page(&ctx->authority, logical);
		if (error)
			return error;
		/*
		 * Upper DISCARD already owns the ordered worker and has removed the
		 * final authoritative mapping. Reclaim a newly-dead CLOSED segment
		 * now; ID70a makes a later allocator recycle a zero-I/O duplicate
		 * skip. Device DISCARD failures remain advisory in the helper.
		 */
		if (became_dead &&
		    old_segment != ctx->authority.open_segment) {
			error = swapz_discard_dead_segment(ctx, old_segment);
			if (error)
				return error;
		}
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
	bool inflight_active = swapz_has_inflight(ctx);
	bool blocked = !READ_ONCE(ctx->accepting) || ctx->failed ||
		ctx->authority.in_flight || ctx->authority.batch_replaying ||
		(ctx->authority.batch_pending && !inflight_active) ||
		(bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)) ||
		swapz_inflight_run_touches_logical(ctx, logical);

	/*
	 * A K=1 lower run has reserved unpublished generations, but its committed
	 * predecessor mappings remain authoritative until ordered completion.
	 * Unrelated reads may therefore use those committed mappings while the
	 * lower WRITE is active. Same-page reads and collector conflicts still
	 * fence and force ordered finalization.
	 */
	return swapz_window_read_independent(ctx->batch, ctx->batch_count,
					 logical, ctx->retain_ms, blocked);
}

static bool swapz_read_can_parallel(struct swapz_dm *ctx, struct bio *bio)
{
	swapz_u32 logical;
	bool inflight_active;
	bool blocked;

	if (bio_op(bio) != REQ_OP_READ ||
	    (bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)))
		return false;
	if (ctx->batch_count)
		return swapz_read_is_independent(ctx, bio);
	logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	inflight_active = swapz_has_inflight(ctx);
	blocked = !READ_ONCE(ctx->accepting) || ctx->failed ||
		ctx->authority.in_flight || ctx->authority.batch_replaying ||
		(ctx->authority.batch_pending && !inflight_active) ||
		swapz_inflight_run_touches_logical(ctx, logical);
	return !blocked;
}

static bool swapz_parallel_read_extent_mapped(struct swapz_dm *ctx,
					      struct bio *bio,
					      swapz_u32 *start_block,
					      swapz_u8 *extent_blocks)
{
	swapz_u32 logical;
	const struct swapz_map *map;

	logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	map = &ctx->maps[logical];
	if (!map->valid || map->raw || !map->extent_blocks ||
	    map->extent_blocks > SWAPZ_MAX_BLOCKS)
		return false;
	*start_block = map->start_block;
	*extent_blocks = map->extent_blocks;
	return true;
}

static bool swapz_parallel_read_extent(struct swapz_dm *ctx,
				       struct bio *bio,
				       swapz_u32 *start_block,
				       swapz_u8 *extent_blocks)
{
	if (!swapz_read_can_parallel(ctx, bio))
		return false;
	return swapz_parallel_read_extent_mapped(ctx, bio, start_block,
						 extent_blocks);
}

/*
 * Find the longest physically adjacent sequence containing the FIFO-head
 * extent whose complete span fits the selected 2..8-block evidence cap.
 * The scratch remains sized for the hard eight-block/32KiB maximum. Exact
 * missing ranges are checked before FIFO ownership or cache copies.
 */
static unsigned int swapz_adjacent_extent_chain_candidate(
					struct swapz_dm *ctx,
					struct list_head *local,
					unsigned int prefix,
					swapz_u32 required_start,
					swapz_u32 *chain_starts,
					swapz_u8 *chain_extents,
					swapz_u16 *blocks_out)
{
	struct swapz_bio_ref *entry;
	swapz_u32 starts[SWAPZ_MAX_RECORDS];
	swapz_u8 extents[SWAPZ_MAX_RECORDS];
	unsigned int seen = 0, unique = 0, best_index = 0;
	unsigned int best_extents = 0, index;
	swapz_u16 best_blocks = 0;

	if (!chain_starts || !chain_extents || !blocks_out)
		return 0;
	*blocks_out = 0;
	list_for_each_entry(entry, local, list) {
		swapz_u32 start;
		swapz_u8 blocks;
		unsigned int position;

		if (seen++ >= prefix)
			break;
		if (!swapz_parallel_read_extent_mapped(ctx, entry->bio, &start, &blocks))
			continue;
		for (position = 0; position < unique; ++position) {
			if (starts[position] == start || starts[position] > start)
				break;
		}
		if (position < unique && starts[position] == start)
			continue;
		if (unique >= SWAPZ_MAX_RECORDS)
			break;
		for (index = unique; index > position; --index) {
			starts[index] = starts[index - 1U];
			extents[index] = extents[index - 1U];
		}
		starts[position] = start;
		extents[position] = blocks;
		unique++;
	}
	for (index = 0; index < unique; ++index) {
		swapz_u32 next_start = starts[index];
		swapz_u32 segment = starts[index] / SWAPZ_SEGMENT_BLOCKS;
		swapz_u16 chain_blocks = 0;
		unsigned int chain_count = 0, next = index;
		bool contains_required = false;

		while (next < unique && starts[next] == next_start &&
		       starts[next] / SWAPZ_SEGMENT_BLOCKS == segment &&
		       chain_blocks + extents[next] <=
			SWAPZ_READ_COALESCE_MAX_BLOCKS) {
			if (starts[next] == required_start)
				contains_required = true;
			chain_blocks += extents[next];
			next_start += extents[next];
			chain_count++;
			next++;
		}
		if (contains_required &&
		    (chain_count > best_extents ||
		     (chain_count == best_extents && chain_blocks > best_blocks))) {
			best_index = index;
			best_extents = chain_count;
			best_blocks = chain_blocks;
		}
	}
	if (best_extents > SWAPZ_PARALLEL_READ_SLOTS)
		return 0;
	for (index = 0; index < best_extents; ++index) {
		chain_starts[index] = starts[best_index + index];
		chain_extents[index] = extents[best_index + index];
	}
	*blocks_out = best_blocks;
	return best_extents;
}

/* Scan only the already-admitted independent READ prefix. ID63 consumes the
 * longest exact contiguous missing-range chain that includes the FIFO head.
 * Two through eight immutable extents may share one zero-padding lower read,
 * bounded by the existing eight-block/32KiB scratch. */
static bool swapz_try_concurrent_read_slots(struct swapz_dm *ctx,
					    struct list_head *local,
					    unsigned int remaining,
					    unsigned int *processed_out)
{
	struct swapz_bio_ref *entry;
	struct list_head *position;
	swapz_u32 starts[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 extents[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 first[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 blocks[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u32 skipped_writes[SWAPZ_MAX_RECORDS];
	unsigned int skipped_write_count = 0, scanned = 0;
	unsigned int slot_count = 0, selected = 0, output_pages = 0;
	unsigned int missing_slots = 0;
	unsigned int slot_index, index, completed = 0;
	bool retained_bypass, any_same_extent = false;
	u64 read_start_ns, read_end_ns;
	int batch_error = 0;

	/*
	 * Independent lower-READ fan-out is fixed-on production infrastructure.
	 * read_coalesce controls only adjacent exact-range merging, so the ID63
	 * control still varies one mechanism while this fallback remains common.
	 *
	 * A retained plain WRITE has only staged immutable RAM state and no
	 * ordering flag. Independent READs may pass such queued WRITEs exactly as
	 * they may bypass the already-staged retained window. Preserve same-page
	 * ordering by rejecting a READ that conflicts with any earlier skipped
	 * WRITE in this local FIFO prefix.
	 */
	if (!ctx->read_slots || !ctx->read_pages_store ||
	    remaining < 2U || list_empty(local))
		return false;

	entry = list_first_entry(local, struct swapz_bio_ref, list);
	if (bio_op(entry->bio) != REQ_OP_READ)
		return false;

	list_for_each(position, local) {
		struct bio *bio;
		swapz_u32 start_block, logical;
		swapz_u8 extent_blocks;
		unsigned int write_index;
		bool write_conflict = false;
		int found = -1;

		if (scanned >= remaining || scanned >= SWAPZ_MAX_RECORDS ||
		    selected >= remaining || selected >= SWAPZ_MAX_RECORDS)
			break;
		scanned++;
		entry = list_entry(position, struct swapz_bio_ref, list);
		bio = entry->bio;
		if (ctx->retain_ms &&
		    swapz_plain_retained_write(bio)) {
			if (skipped_write_count >= SWAPZ_MAX_RECORDS)
				break;
			skipped_writes[skipped_write_count++] =
				(swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
			continue;
		}
		if (!swapz_parallel_read_extent(ctx, bio, &start_block, &extent_blocks))
			break;
		logical = (swapz_u32)(bio->bi_iter.bi_sector / SWAPZ_SECTORS);
		for (write_index = 0; write_index < skipped_write_count;
		     ++write_index) {
			if (skipped_writes[write_index] == logical) {
				write_conflict = true;
				break;
			}
		}
		if (write_conflict)
			break;
		for (slot_index = 0; slot_index < slot_count; ++slot_index)
			if (starts[slot_index] == start_block &&
			    extents[slot_index] == extent_blocks) {
				found = (int)slot_index;
				break;
			}
		if (found < 0) {
			if (slot_count == SWAPZ_PARALLEL_READ_SLOTS)
				break;
			found = (int)slot_count++;
			starts[found] = start_block;
			extents[found] = extent_blocks;
			swapz_read_slot_prepare(&ctx->read_slots[found],
						start_block, extent_blocks);
		}
		if (ctx->read_slots[found].bio_count == SWAPZ_MAX_RECORDS)
			break;
		ctx->read_slots[found].bios[ctx->read_slots[found].bio_count] = bio;
		ctx->read_slots[found].logical_pages[
			ctx->read_slots[found].bio_count++] = logical;
		selected++;
	}
	if (slot_count < 2U || selected < 2U)
		return false;

	for (slot_index = 0; slot_index < slot_count; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];
		int error;

		if (output_pages + slot->bio_count > SWAPZ_MAX_RECORDS)
			return false;
		slot->read_pages = ctx->read_pages_store +
			(size_t)output_pages * SWAPZ_BLOCK_BYTES;
		output_pages += slot->bio_count;
		swapz_engine_prime_read_slot(&ctx->engine, &slot->engine,
					     starts[slot_index], extents[slot_index]);
		error = swapz_engine_required_read_range(
			&slot->engine, slot->logical_pages, slot->bio_count,
			starts[slot_index], extents[slot_index],
			&first[slot_index], &blocks[slot_index]);
		if (error)
			return false;
		if (blocks[slot_index])
			missing_slots++;
	}
	if (missing_slots < 2U)
		return false;

	for (slot_index = 0; slot_index < slot_count; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

		for (index = 0; index < slot->bio_count; ++index) {
			entry = dm_per_bio_data(slot->bios[index], sizeof(*entry));
			list_del_init(&entry->list);
		}
		if (slot->bio_count > 1U)
			any_same_extent = true;
	}
	ctx->worker_has_immediate_followup = !list_empty(local);
	if (ctx->async_prepare)
		atomic_set(&ctx->preparation_tail_credit, 0);
	retained_bypass = (ctx->batch_count || skipped_write_count) && ctx->retain_ms;
	read_start_ns = ktime_get_ns();
	swapz_lower_read_overlap_begin(ctx);

	/* Submit every independent missing range before joining any slot. */
	for (slot_index = 0; slot_index < slot_count; ++slot_index) {
		int error;

		if (!blocks[slot_index])
			continue;
		error = swapz_submit_read_slot_range(
			&ctx->read_slots[slot_index], first[slot_index],
			blocks[slot_index]);
		if (error && !batch_error)
			batch_error = error;
		else if (!error)
			ctx->parallel_read_async_slots++;
	}
	for (slot_index = 0; slot_index < slot_count; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];
		int error;

		if (!slot->lower_submitted)
			continue;
		error = swapz_finish_read_slot_range(slot);
		if (error && !batch_error)
			batch_error = error;
	}
	swapz_lower_read_overlap_end(ctx);
	if (!batch_error)
		ctx->parallel_read_async_batches++;

	if (!batch_error)
		for (slot_index = 0; slot_index < slot_count; ++slot_index) {
			struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

			slot->error = swapz_read_slot_run(slot);
			if (slot->error) {
				batch_error = slot->error;
				break;
			}
			for (index = 0; index < slot->bio_count; ++index) {
				batch_error = swapz_copy_bio_accounted(
					slot->bios[index],
					slot->read_pages +
						(size_t)index * SWAPZ_BLOCK_BYTES,
					true, &ctx->read_copy_wall_ns,
					&ctx->read_copy_bytes);
				if (batch_error)
					break;
			}
			if (batch_error)
				break;
			for (index = 0; index < slot->bio_count; ++index) {
				swapz_complete(slot->bios[index], 0);
				slot->bios[index] = NULL;
				completed++;
			}
			swapz_engine_absorb_read_slot(&ctx->engine, &slot->engine);
		}
	read_end_ns = ktime_get_ns();

	for (slot_index = 0; slot_index < slot_count; ++slot_index)
		swapz_merge_read_slot(ctx, &ctx->read_slots[slot_index], false);
	ctx->parallel_read_pairs++;
	ctx->parallel_read_distinct_extent_pairs++;
	if (any_same_extent)
		ctx->parallel_read_same_extent_pairs++;
	*processed_out = selected;
	if (batch_error) {
		swapz_fail(ctx, batch_error);
		ctx->next_window_close = SWAPZ_CLOSE_OTHER;
		if (ctx->batch_count)
			swapz_flush_window(ctx);
		for (slot_index = 0; slot_index < slot_count; ++slot_index) {
			struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

			for (index = 0; index < slot->bio_count; ++index)
				if (slot->bios[index])
					swapz_complete(slot->bios[index], batch_error);
		}
		ctx->logical_read_bytes += (u64)completed * SWAPZ_BLOCK_BYTES;
		atomic_set(&ctx->preparation_tail_credit, 0);
		return true;
	}

	ctx->logical_read_bytes += (u64)selected * SWAPZ_BLOCK_BYTES;
	swapz_refresh_accepted_followup(ctx);
	if (retained_bypass) {
		u64 elapsed = read_end_ns > read_start_ns ?
			read_end_ns - read_start_ns : 0;
		unsigned int bypasses =
			(unsigned int)ctx->retained_window_read_bypasses + selected;

		ctx->retained_read_bypasses += selected;
		swapz_note_single_tail_read_bypass(ctx);
		ctx->retained_window_read_bypasses = (swapz_u8)min_t(
			unsigned int, bypasses, SWAPZ_MAX_RECORDS);
		if (ctx->window_first_ns && elapsed) {
			if (ctx->window_first_ns <= read_start_ns)
				ctx->window_first_ns += elapsed;
			else
				ctx->window_first_ns = read_end_ns;
		}
	}
	atomic_set(&ctx->preparation_tail_credit, 0);
	if (retained_bypass && !ctx->worker_has_immediate_followup &&
	    swapz_retention_expired(ctx)) {
		ctx->next_window_close = SWAPZ_CLOSE_DEADLINE;
		ctx->deadline_after_read++;
		swapz_flush_window(ctx);
	}
	return true;
}

static bool swapz_try_parallel_read_batch(struct swapz_dm *ctx,
					  struct list_head *local,
					  unsigned int remaining,
					  unsigned int *processed_out)
{
	struct swapz_engine *chain_engines[SWAPZ_PARALLEL_READ_SLOTS];
	struct swapz_bio_ref *entry;
	swapz_u32 chain_starts[SWAPZ_PARALLEL_READ_SLOTS];
	swapz_u32 execute_starts[SWAPZ_PARALLEL_READ_SLOTS];
	swapz_u32 start0, start, head_logical;
	swapz_u8 chain_extents[SWAPZ_PARALLEL_READ_SLOTS];
	swapz_u8 request_first[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 request_blocks[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 execute_extents[SWAPZ_PARALLEL_READ_SLOTS];
	swapz_u8 execute_first[SWAPZ_PARALLEL_READ_SLOTS];
	swapz_u8 execute_blocks[SWAPZ_PARALLEL_READ_SLOTS];
	int range_errors[SWAPZ_PARALLEL_READ_SLOTS] = { 0 };
	swapz_u8 blocks0, blocks, head_first = 0, head_blocks = 0;
	unsigned int prefix = 0, covered_prefix = 0, seen = 0, index, slot_index;
	unsigned int chain_count, head_index = SWAPZ_PARALLEL_READ_SLOTS;
	unsigned int chain_first, chain_last, execute_count, selected = 0;
	unsigned int output_pages = 0;
	swapz_u16 candidate_blocks = 0, full_span_blocks = 0;
	swapz_u16 combined_blocks;
	swapz_u32 combined_start, combined_end;
	bool retained_bypass, any_same_extent = false;
	u64 read_start_ns, read_end_ns;
	int batch_error = 0, head_range_error;

	*processed_out = 0;
	/*
	 * The disabled arm is the performance control: it must not execute any
	 * ID63 cache probe, candidate scan, private-slot preparation or counters.
	 */
	if (!ctx->read_grouping_enabled || !ctx->read_coalescing_enabled ||
	    !ctx->read_slots || !ctx->read_pages_store ||
	    remaining < 2U || list_empty(local))
		return false;
	entry = list_first_entry(local, struct swapz_bio_ref, list);
	if (!swapz_parallel_read_extent(ctx, entry->bio, &start0, &blocks0))
		return false;
	/*
	 * If the FIFO head's exact extent range is already resident, no lower
	 * merge is possible for that BIO. Avoid rebuilding the same 64-BIO chain
	 * for each cached sibling in a multi-record extent.
	 */
	head_logical =
		(swapz_u32)(entry->bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	head_range_error = swapz_engine_required_read_range_cached(
		&ctx->engine, &head_logical, 1U, start0, blocks0,
		&head_first, &head_blocks);
	if (!head_range_error && !head_blocks) {
		ctx->parallel_read_coalesce_skip_cached++;
		return false;
	}
	list_for_each_entry(entry, local, list) {
		if (prefix >= remaining || !swapz_read_can_parallel(ctx, entry->bio))
			break;
		prefix++;
	}
	if (prefix < 2U)
		return false;

	chain_count = swapz_adjacent_extent_chain_candidate(
		ctx, local, prefix, start0, chain_starts, chain_extents,
		&candidate_blocks);
	if (chain_count >= 3U) {
		ctx->parallel_read_adjacent_chain_3plus++;
		if (chain_count > ctx->parallel_read_adjacent_chain_extent_max)
			ctx->parallel_read_adjacent_chain_extent_max = chain_count;
		if (candidate_blocks > ctx->parallel_read_adjacent_chain_blocks_max)
			ctx->parallel_read_adjacent_chain_blocks_max = candidate_blocks;
	}
	if (chain_count < 2U)
		return false;

	for (slot_index = 0; slot_index < chain_count; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

		swapz_read_slot_prepare(slot, chain_starts[slot_index],
					chain_extents[slot_index]);
		if (chain_starts[slot_index] == start0)
			head_index = slot_index;
	}
	if (head_index >= chain_count)
		return false;

	list_for_each_entry(entry, local, list) {
		if (seen++ >= prefix)
			break;
		if (!swapz_parallel_read_extent_mapped(ctx, entry->bio, &start, &blocks))
			continue;
		for (slot_index = 0; slot_index < chain_count; ++slot_index)
			if (chain_starts[slot_index] == start &&
			    chain_extents[slot_index] == blocks)
				break;
		if (slot_index == chain_count)
			continue;
		covered_prefix++;
		if (ctx->read_slots[slot_index].bio_count >= SWAPZ_MAX_RECORDS)
			return false;
		ctx->read_slots[slot_index].bios[
			ctx->read_slots[slot_index].bio_count] = entry->bio;
		ctx->read_slots[slot_index].logical_pages[
			ctx->read_slots[slot_index].bio_count++] =
			(swapz_u32)(entry->bio->bi_iter.bi_sector / SWAPZ_SECTORS);
	}
	/*
	 * Do not synchronously coalesce a small adjacent subset while unrelated
	 * independent READs from the same admitted prefix wait unsubmitted. When
	 * the chain does not cover the whole parallel prefix, fall back to the
	 * asynchronous private-slot path so device queue parallelism wins. A chain
	 * reaching the maximum coalesced block cap is already full.
	 */
	if (covered_prefix != prefix &&
	    chain_count < SWAPZ_PARALLEL_READ_SLOTS &&
	    candidate_blocks < SWAPZ_READ_COALESCE_MAX_BLOCKS)
		return false;

	for (slot_index = 0; slot_index < chain_count; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

		if (!slot->bio_count)
			return false;
		range_errors[slot_index] = swapz_engine_required_read_range_cached(
			&ctx->engine, slot->logical_pages, slot->bio_count,
			chain_starts[slot_index], chain_extents[slot_index],
			&request_first[slot_index], &request_blocks[slot_index]);
	}

	if (range_errors[head_index] || !request_blocks[head_index])
		goto rejected_chain;
	chain_first = head_index;
	chain_last = head_index;
	combined_start = chain_starts[head_index] + request_first[head_index];
	combined_end = combined_start + request_blocks[head_index];
	combined_blocks = request_blocks[head_index];
	while (chain_first > 0U) {
		unsigned int previous = chain_first - 1U;
		swapz_u32 physical;

		if (range_errors[previous] || !request_blocks[previous])
			break;
		physical = chain_starts[previous] + request_first[previous];
		if (physical + request_blocks[previous] != combined_start ||
		    combined_blocks + request_blocks[previous] >
				SWAPZ_READ_COALESCE_MAX_BLOCKS)
			break;
		combined_start = physical;
		combined_blocks += request_blocks[previous];
		chain_first = previous;
	}
	while (chain_last + 1U < chain_count) {
		unsigned int next = chain_last + 1U;
		swapz_u32 physical;

		if (range_errors[next] || !request_blocks[next])
			break;
		physical = chain_starts[next] + request_first[next];
		if (physical != combined_end ||
		    combined_blocks + request_blocks[next] >
				SWAPZ_READ_COALESCE_MAX_BLOCKS)
			break;
		combined_end += request_blocks[next];
		combined_blocks += request_blocks[next];
		chain_last = next;
	}
	if (chain_last == chain_first)
		goto rejected_chain;

	execute_count = chain_last - chain_first + 1U;
	/*
	 * If cache residency or a gap shrinks the merged span below the candidate
	 * fan-out batch, let the asynchronous path submit all independent missing
	 * ranges together instead of blocking them behind a partial sync merge.
	 * A merged span retaining at least two adjacent extents remains eligible.
	 */
	if (execute_count != chain_count) {
		if (execute_count < 2U)
			return false;
	}
	for (slot_index = chain_first; slot_index <= chain_last; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];
		unsigned int execute_index = slot_index - chain_first;

		if (output_pages + slot->bio_count > SWAPZ_MAX_RECORDS)
			return false;
		slot->read_pages = ctx->read_pages_store +
			(size_t)output_pages * SWAPZ_BLOCK_BYTES;
		output_pages += slot->bio_count;
		chain_engines[execute_index] = &slot->engine;
		execute_starts[execute_index] = chain_starts[slot_index];
		execute_extents[execute_index] = chain_extents[slot_index];
		execute_first[execute_index] = request_first[slot_index];
		execute_blocks[execute_index] = request_blocks[slot_index];
		full_span_blocks += chain_extents[slot_index];
		swapz_engine_prime_read_slot(&ctx->engine, &slot->engine,
					     chain_starts[slot_index],
					     chain_extents[slot_index]);
	}
	for (slot_index = chain_first; slot_index <= chain_last; ++slot_index) {
		struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

		for (index = 0; index < slot->bio_count; ++index) {
			entry = dm_per_bio_data(slot->bios[index], sizeof(*entry));
			list_del_init(&entry->list);
		}
		selected += slot->bio_count;
		if (slot->bio_count > 1U)
			any_same_extent = true;
	}
	ctx->parallel_read_distinct_extent_pairs++;
	ctx->parallel_read_adjacent_extent_pairs++;
	ctx->parallel_read_adjacent_extent_blocks += full_span_blocks;
	ctx->worker_has_immediate_followup = !list_empty(local);
	if (ctx->async_prepare)
		atomic_set(&ctx->preparation_tail_credit, 0);

	retained_bypass = ctx->batch_count && ctx->retain_ms;
	read_start_ns = ktime_get_ns();
	batch_error = swapz_engine_coalesce_read_chain(
		chain_engines, execute_starts, execute_extents, execute_first,
		execute_blocks, (swapz_u8)execute_count,
		ctx->read_coalesce_scratch, SWAPZ_READ_COALESCE_MAX_BLOCKS);
	if (!batch_error) {
		ctx->parallel_read_coalesced_pairs++;
		ctx->parallel_read_coalesced_reqs_saved += execute_count - 1U;
		ctx->parallel_read_coalesced_blocks += combined_blocks;
		ctx->parallel_read_coalesce_extra_blocks += 0;
		for (slot_index = chain_first; slot_index <= chain_last; ++slot_index) {
			struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

			slot->error = swapz_read_slot_run(slot);
			if (slot->error) {
				batch_error = slot->error;
				break;
			}
			for (index = 0; index < slot->bio_count; ++index) {
				batch_error = swapz_copy_bio_accounted(
					slot->bios[index],
					slot->read_pages +
						(size_t)index * SWAPZ_BLOCK_BYTES,
					true, &ctx->read_copy_wall_ns,
					&ctx->read_copy_bytes);
				if (batch_error)
					break;
			}
			if (batch_error)
				break;
			for (index = 0; index < slot->bio_count; ++index) {
				swapz_complete(slot->bios[index], 0);
				slot->bios[index] = NULL;
			}
			swapz_engine_absorb_read_slot(&ctx->engine, &slot->engine);
		}
	}
	read_end_ns = ktime_get_ns();

	for (slot_index = chain_first; slot_index <= chain_last; ++slot_index)
		swapz_merge_read_slot(ctx, &ctx->read_slots[slot_index], false);
	ctx->parallel_read_pairs++;
	if (any_same_extent)
		ctx->parallel_read_same_extent_pairs++;
	*processed_out = selected;
	if (batch_error) {
		swapz_fail(ctx, batch_error);
		ctx->next_window_close = SWAPZ_CLOSE_OTHER;
		if (ctx->batch_count)
			swapz_flush_window(ctx);
		for (slot_index = chain_first; slot_index <= chain_last; ++slot_index) {
			struct swapz_read_slot *slot = &ctx->read_slots[slot_index];

			for (index = 0; index < slot->bio_count; ++index)
				if (slot->bios[index])
					swapz_complete(slot->bios[index], batch_error);
		}
		atomic_set(&ctx->preparation_tail_credit, 0);
		return true;
	}

	ctx->logical_read_bytes += (u64)selected * SWAPZ_BLOCK_BYTES;
	swapz_refresh_accepted_followup(ctx);
	if (retained_bypass) {
		u64 elapsed = read_end_ns > read_start_ns ?
			read_end_ns - read_start_ns : 0;
		unsigned int bypasses =
			(unsigned int)ctx->retained_window_read_bypasses + selected;

		ctx->retained_read_bypasses += selected;
		swapz_note_single_tail_read_bypass(ctx);
		ctx->retained_window_read_bypasses = (swapz_u8)min_t(
			unsigned int, bypasses, SWAPZ_MAX_RECORDS);
		if (ctx->window_first_ns && elapsed) {
			if (ctx->window_first_ns <= read_start_ns)
				ctx->window_first_ns += elapsed;
			else
				ctx->window_first_ns = read_end_ns;
		}
	}
	atomic_set(&ctx->preparation_tail_credit, 0);
	if (retained_bypass && !ctx->worker_has_immediate_followup &&
	    swapz_retention_expired(ctx)) {
		ctx->next_window_close = SWAPZ_CLOSE_DEADLINE;
		ctx->deadline_after_read++;
		swapz_flush_window(ctx);
	}
	return true;

rejected_chain:
	for (slot_index = 0; slot_index < chain_count; ++slot_index)
		if (!range_errors[slot_index] && !request_blocks[slot_index]) {
			ctx->parallel_read_coalesce_skip_cached++;
			return false;
		}
	for (slot_index = 0; slot_index < chain_count; ++slot_index)
		if (range_errors[slot_index] == -EOPNOTSUPP) {
			ctx->parallel_read_coalesce_skip_noncontig_slot++;
			return false;
		}
	for (slot_index = 0; slot_index < chain_count; ++slot_index)
		if (range_errors[slot_index]) {
			ctx->parallel_read_coalesce_skip_other++;
			return false;
		}
	ctx->parallel_read_coalesce_skip_gap++;
	return false;
}

static void swapz_process(struct swapz_dm *ctx, struct bio *bio)
{
	int error = 0;
	const enum req_op op = bio_op(bio);

	/*
	 * Ordinary WRITE admission only stages immutable upper data in RAM.
	 * Do not discard validated read residency until a path can actually
	 * change media: synchronous/asynchronous lower WRITE submission already
	 * invalidates immediately before that mutation. Keep DISCARD conservative
	 * in this first A/B because it changes mapping authority even without
	 * lower media I/O, and keep hard ordering barriers as explicit resets.
	 */
	if (op == REQ_OP_DISCARD ||
	    (op == REQ_OP_WRITE && ctx->invalidate_cache_on_write_admit) ||
	    (bio->bi_opf & (REQ_PREFLUSH | REQ_FUA)))
		swapz_invalidate_read_caches(ctx);
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
		if (error && !(op == REQ_OP_READ && error == -ENOSPC)) {
			swapz_complete(bio, error);
			return;
		}
		if (op == REQ_OP_READ && error == -ENOSPC)
			error = 0;
	}
	/* Only the opt-in retained stream can service a disjoint READ from
	 * committed authority. Read scratch is separate from batch_bytes;
	 * one worker still owns every mapping and all lower I/O. */
	if (op == REQ_OP_READ && swapz_read_is_independent(ctx, bio)) {
		u64 read_start_ns = ktime_get_ns();
		u64 lower_reqs_before = ctx->lower_read_submitted_reqs;

		error = swapz_read(ctx, bio);
		if (error) {
			swapz_fail(ctx, error);
			ctx->next_window_close = SWAPZ_CLOSE_OTHER;
			/* Abort pending owners without submitting their data. */
			swapz_flush_window(ctx);
		}
		if (!error) {
			u64 read_end_ns = ktime_get_ns();
			bool had_lower_io =
				ctx->lower_read_submitted_reqs != lower_reqs_before;

			/* BIOs may have arrived while synchronous lower READ I/O ran. */
			swapz_refresh_accepted_followup(ctx);
			ctx->retained_read_bypasses++;
			/*
			 * Cache hits are independent READ bypasses, but they do not prove
			 * a lower-device service interval and therefore cannot authorize
			 * service-dry window closure or extend the retention deadline.
			 */
			if (had_lower_io) {
				swapz_note_single_tail_read_bypass(ctx);
				if (ctx->retained_window_read_bypasses < SWAPZ_MAX_RECORDS)
					ctx->retained_window_read_bypasses++;
				if (ctx->window_first_ns && read_end_ns > read_start_ns) {
					u64 read_elapsed = read_end_ns - read_start_ns;

					if (ctx->window_first_ns <= read_start_ns)
						ctx->window_first_ns += read_elapsed;
					else
						ctx->window_first_ns = read_end_ns;
				}
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
		if (error && !(op == REQ_OP_READ && error == -ENOSPC)) {
			swapz_complete(bio, error);
			return;
		}
		if (op == REQ_OP_READ && error == -ENOSPC)
			error = 0;
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
		if (!error && ctx->retain_ms)
			swapz_refresh_accepted_followup(ctx);
		break;
	case REQ_OP_DISCARD:
		error = swapz_discard(ctx, bio);
		break;
	default:
		error = -EOPNOTSUPP;
		break;
	}
	if (error && error != -EOPNOTSUPP && error != -ENOSPC)
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
/* Every retained window, including a deferred sampled singleton, uses only
 * the ordinary first-record absolute deadline. ID53's shorter active cutoff
 * was rejected by owner evidence and is intentionally absent here. */
static u64 swapz_retention_deadline_ns(struct swapz_dm *ctx)
{
	return swapz_window_retention_deadline_ns(
		ctx->window_first_ns, ctx->retain_ms);
}

static bool swapz_retention_expired(struct swapz_dm *ctx)
{
	return swapz_window_deadline_expired(swapz_retention_deadline_ns(ctx),
					     ktime_get_ns());
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
	u64 wall_start_ns = ktime_get_ns();
	u64 cpu_start_ns = swapz_worker_cpu_sample();

	for (;;) {
		while (swapz_has_inflight(ctx)) {
			struct swapz_inflight_write *head =
				swapz_inflight_head_slot(ctx);
			int inflight_error;

			if (!head || !completion_done(&head->lower_done))
				break;
			inflight_error = swapz_finalize_inflight_write(ctx, false);
			if (inflight_error) {
				swapz_finalize_all_inflight(ctx, true);
				if (ctx->batch_count) {
					ctx->next_window_close = SWAPZ_CLOSE_OTHER;
					swapz_flush_window(ctx);
				}
				break;
			}
		}
		remaining = SWAPZ_WORK_QUANTUM_BIOS;
		spin_lock_irqsave(&ctx->queue_lock, flags);
		list_splice_init(&ctx->incoming, &local);
		/*
		 * An idle producer starts only when the accepted wave contains the
		 * ordered head plus at least four unclaimed tails. This keeps QD4
		 * entirely inline while preserving an immediate producer start for
		 * QD8/QD32. Real active lower READ or WRITE service is an
		 * independent head-first overlap signal and is not subject to this
		 * idle threshold.
		 */
		if (ctx->async_prepare &&
		    ctx->preparation_queued >=
			    SWAPZ_PREPARATION_STARTER_WAKE_MIN) {
			atomic_set(&ctx->preparation_tail_credit, 1);
			ctx->preparation_wave_kicks++;
			swapz_queue_preparation_workers(ctx);
		}
		spin_unlock_irqrestore(&ctx->queue_lock, flags);

		while (remaining && !list_empty(&local)) {
			bool wait_for_preparation = false;
			bool inline_preparation = false;
			unsigned int processed_bios = 1;

			if (remaining > 1U &&
			    swapz_try_parallel_read_batch(ctx, &local, remaining,
							 &processed_bios))
				goto processed_bio;
			if (remaining > 1U &&
			    swapz_try_concurrent_read_slots(ctx, &local, remaining,
							  &processed_bios))
				goto processed_bio;
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
					if (ctx->preparation_queued)
						ctx->preparation_queued--;
					list_del_init(&entry->preparation_list);
					entry->preparation_inline = true;
					inline_preparation = true;
					wait_for_preparation = false;
					ctx->preparation_ordered_inline++;
					atomic_set(&ctx->preparation_tail_credit, 1);
					if (!list_empty(&ctx->preparation_incoming) &&
					    (atomic_read(&ctx->lower_write_active) ||
					     atomic_read(&ctx->lower_read_active) ||
					     ctx->preparation_queued >=
						SWAPZ_PREPARATION_TAIL_WAKE_MIN))
						swapz_queue_preparation_workers(ctx);
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
				/* READs/barriers revoke idle WRITE-wave credit. */
				atomic_set(&ctx->preparation_tail_credit, 0);
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
		processed_bio:
			if (swapz_has_inflight(ctx) &&
			    !swapz_inflight_lower_pending(ctx)) {
				if (swapz_finalize_inflight_write(ctx, false) &&
				    ctx->batch_count) {
					ctx->next_window_close = SWAPZ_CLOSE_OTHER;
					swapz_flush_window(ctx);
				}
			}

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
					if (ctx->async_prepare &&
					    ctx->preparation_queued >=
						SWAPZ_PREPARATION_TAIL_WAKE_MIN) {
						atomic_set(&ctx->preparation_tail_credit, 1);
						ctx->preparation_wave_kicks++;
						swapz_queue_preparation_workers(ctx);
					}
				}
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				if (ctx->worker_has_immediate_followup) {
					ctx->singleton_deadline_streak = 0;
					ctx->singleton_fast_close = false;
				}
			}
			if (swapz_retained_pack_close_ready(ctx) &&
			    !ctx->worker_has_immediate_followup &&
			    !(SWAPZ_WRITE_PIPELINE_DEPTH == 1U &&
			      swapz_inflight_lower_pending(ctx)) &&
			    ctx->batch_count && !ctx->failed &&
			    READ_ONCE(ctx->accepting) &&
			    !swapz_retention_expired(ctx)) {
				ctx->next_pack_close_cause =
					swapz_service_proven_dry_pack(ctx) ?
					SWAPZ_PACK_CLOSE_SERVICE_DRY :
					(ctx->retained_tail_target ?
					 SWAPZ_PACK_CLOSE_TAIL_TARGET :
					 SWAPZ_PACK_CLOSE_BURST_TARGET);
				if (ctx->next_pack_close_cause ==
				    SWAPZ_PACK_CLOSE_BURST_TARGET) {
					ctx->next_burst_close_site =
						SWAPZ_BURST_CLOSE_WORKER;
					ctx->next_burst_close_target =
						ctx->retained_burst_target;
				}
				ctx->next_window_close = SWAPZ_CLOSE_PACK_READY;
				ctx->packed_early_commits++;
				if (ctx->accepted_burst_pack_ready)
					ctx->accepted_burst_tail_flushes++;
				swapz_flush_window(ctx);
			}
			ctx->worker_has_immediate_followup = false;
			if (!(remaining & 7U))
				cond_resched();
			remaining -= processed_bios;
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
						    !ctx->retained_chain_completed) {
							swapz_u8 old_target =
								ctx->retained_burst_target;
							swapz_u8 candidate_target =
								swapz_window_shrink_burst_target(
									old_target,
									ctx->batch_count);

							if (candidate_target != old_target) {
								ctx->retained_burst_target = candidate_target;
								ctx->burst_target_shrinks++;
								if (ctx->retained_window_read_bypasses)
									ctx->burst_shrink_after_read_bypass++;
								else
									ctx->burst_shrink_other++;
								if (ctx->retained_burst_target <= 8U)
									ctx->burst_shrink_target_le8++;
								else if (ctx->retained_burst_target <= 32U)
									ctx->burst_shrink_target_9_32++;
								else
									ctx->burst_shrink_target_gt32++;
							}
						}
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

		if (swapz_has_inflight(ctx) &&
		    !swapz_inflight_lower_pending(ctx))
			swapz_finalize_inflight_write(ctx, false);

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
				if (!swapz_has_inflight(ctx))
					ctx->retained_window_read_bypasses = 0;
				ctx->retained_wave_interrupted = false;
				ctx->retained_chain_completed = 0;
				ctx->retained_tail_target = 0;
				if (ctx->retained_single_tail_deferred) {
					ctx->single_tail_other_clears++;
					swapz_account_single_tail_terminal(ctx, false, false);
					ctx->retained_single_tail_deferred = false;
				}
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
			    !ctx->retained_single_tail_deferred &&
			    ctx->retain_ms && !swapz_retention_expired(ctx)) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				ctx->next_window_close = SWAPZ_CLOSE_IDLE;
				swapz_flush_window(ctx);
				swapz_account_worker_runtime(&ctx->ordered_worker_wall_ns,
						 wall_start_ns,
						 &ctx->ordered_worker_cpu_ns,
						 cpu_start_ns);
				return;
			}
			if (ctx->batch_count &&
			    swapz_window_timer_enabled(ctx->retain_ms) &&
			    ctx->accepting && !ctx->failed) {
				if (swapz_retention_timer_needs_arm(
						ctx->retain_ms,
						hrtimer_is_queued(&ctx->retention_timer))) {
					ctx->retain_timer_arms++;
					hrtimer_start(&ctx->retention_timer,
						ns_to_ktime(swapz_retention_deadline_ns(ctx)),
						HRTIMER_MODE_ABS);
				} else {
					ctx->retain_timer_arm_skips++;
				}
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				swapz_account_worker_runtime(&ctx->ordered_worker_wall_ns,
						 wall_start_ns,
						 &ctx->ordered_worker_cpu_ns,
						 cpu_start_ns);
				return;
			}
			if (ctx->batch_count && !ctx->accepting) {
				spin_unlock_irqrestore(&ctx->queue_lock, flags);
				ctx->next_window_close = SWAPZ_CLOSE_SHUTDOWN;
				swapz_flush_window(ctx);
				swapz_account_worker_runtime(&ctx->ordered_worker_wall_ns,
						 wall_start_ns,
						 &ctx->ordered_worker_cpu_ns,
						 cpu_start_ns);
				return;
			}
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			swapz_account_worker_runtime(&ctx->ordered_worker_wall_ns,
					 wall_start_ns,
					 &ctx->ordered_worker_cpu_ns,
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
			swapz_account_worker_runtime(&ctx->ordered_worker_wall_ns,
					 wall_start_ns,
					 &ctx->ordered_worker_cpu_ns,
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
		return ctx->failed ? DM_MAPIO_KILL : DM_MAPIO_REQUEUE;
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
	entry->preparation_ctx = ctx;
	entry->preparation_error = 0;
	if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count)
		init_completion(&entry->preparation_finished);
	entry->bio = bio;
	{
		unsigned int bio_segs = 0;
		bool bio_nonzero_off = false;
		bool bio_compound = false;

		if (count && (bio_op(bio) == REQ_OP_READ ||
			      bio_op(bio) == REQ_OP_WRITE)) {
			if (likely(count == SWAPZ_SECTORS && bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES)) {
				struct bio_vec bv = bio_iter_iovec(bio, bio->bi_iter);
				if (likely(bv.bv_len == SWAPZ_BLOCK_BYTES)) {
					bio_segs = 1;
					bio_nonzero_off = (bv.bv_offset != 0);
					if (bv.bv_page && (PageCompound(bv.bv_page) ||
							    folio_test_large(page_folio(bv.bv_page))))
						bio_compound = true;
					goto segs_done;
				}
			}
			struct bio_vec vec;
			struct bvec_iter iter;

			bio_for_each_segment(vec, bio, iter) {
				bio_segs++;
				if (vec.bv_offset != 0)
					bio_nonzero_off = true;
				if (vec.bv_page && (PageCompound(vec.bv_page) ||
						    folio_test_large(page_folio(vec.bv_page))))
					bio_compound = true;
			}
		segs_done: ;
		}
		spin_lock_irqsave(&ctx->queue_lock, flags);
		/*
		 * Admission and shutdown share queue_lock: presuspend cannot finish
		 * draining while a previously admitted BIO is added after the drain.
		 */
		if (!ctx->accepting) {
			spin_unlock_irqrestore(&ctx->queue_lock, flags);
			return ctx->failed ? DM_MAPIO_KILL : DM_MAPIO_REQUEUE;
		}
		if (count && (bio_op(bio) == REQ_OP_READ ||
			      bio_op(bio) == REQ_OP_WRITE)) {
			if (bio_segs > 1) {
				ctx->bio_segments_gt1++;
				if (bio_segs > ctx->bio_segments_max)
					ctx->bio_segments_max = bio_segs;
			} else if (bio_segs == 1 && ctx->bio_segments_max == 0) {
				ctx->bio_segments_max = 1;
			}
			if (bio_nonzero_off)
				ctx->bio_nonzero_offset++;
			if (bio_compound)
				ctx->bio_compound_folio_pages++;
		}
	}
	list_add_tail(&entry->list, &ctx->incoming);
	if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count) {
		/*
		 * A cold lone head belongs to the ordered worker first. A retained
		 * inline WRITE may leave one earned tail token alive after that worker
		 * goes idle; the next admitted companion can therefore wake the
		 * producer without reading worker-owned batch_count. Real lower
		 * READ or WRITE service remains the independent head-first overlap
		 * signal.
		 */
		list_add_tail(&entry->preparation_list,
			      &ctx->preparation_incoming);
		ctx->preparation_queued++;
		if (atomic_read(&ctx->lower_write_active) ||
		    atomic_read(&ctx->lower_read_active) ||
		    (atomic_read(&ctx->preparation_tail_credit) &&
		     ctx->preparation_queued >= SWAPZ_PREPARATION_TAIL_WAKE_MIN))
			swapz_queue_preparation_workers(ctx);
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
	while (swapz_has_inflight(ctx)) {
		struct swapz_inflight_write *head = swapz_inflight_head_slot(ctx);

		if (!head)
			break;
		wait_for_completion(&head->lower_done);
		mod_delayed_work(ctx->workqueue, &ctx->worker, 0);
		flush_delayed_work(&ctx->worker);
	}
	drain_workqueue(ctx->workqueue);
	/* The ordered worker can queue a final producer invocation while it
	 * drains. Wait for that invocation to release even an empty-queue slot
	 * before checking the free mask. Admission and ordered work are now
	 * quiescent, and the producer never queues ordered work itself. */
	if (ctx->preparation_workqueue)
		drain_workqueue(ctx->preparation_workqueue);
	spin_lock_irqsave(&ctx->queue_lock, flags);
	if (!list_empty(&ctx->incoming) ||
	    !list_empty(&ctx->preparation_incoming) || ctx->preparation_queued ||
	    (u64)atomic64_read(&ctx->preparation_free_mask) !=
					SWAPZ_PREPARATION_FREE_MASK ||
	    atomic_read(&ctx->preparation_workers_active) ||
	    ctx->batch_count || swapz_has_inflight(ctx) ||
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
	swapz_u8 slot, prep_lane;

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
		for (prep_lane = 0; prep_lane < ctx->preparation_worker_count;
		     ++prep_lane)
			cancel_work_sync(&ctx->preparation_lanes[prep_lane].work);
		drain_workqueue(ctx->preparation_workqueue);
		destroy_workqueue(ctx->preparation_workqueue);
	}
	if (ctx->preparation_lanes) {
		for (prep_lane = 0; prep_lane < ctx->preparation_worker_count;
		     ++prep_lane) {
			vfree(ctx->preparation_lanes[prep_lane].input_page);
			kvfree(ctx->preparation_lanes[prep_lane].predictor_page);
			kvfree(ctx->preparation_lanes[prep_lane].delta64_candidate_page);
			kvfree(ctx->preparation_lanes[prep_lane].lz4_workmem);
		}
		kfree(ctx->preparation_lanes);
	}
	vfree(ctx->preparation_pages);
	if (ctx->io_client)
		dm_io_client_destroy(ctx->io_client);
	if (ctx->backing)
		dm_put_device(ctx->target, ctx->backing);
	kvfree(ctx->maps);
	kvfree(ctx->live_records);
	kvfree(ctx->extent_classes);
	vfree(ctx->batch_bytes);
	vfree(ctx->gc_bytes_store);
	kvfree(ctx->gc_scores);
	kvfree(ctx->gc_io_scores);
	kvfree(ctx->gc_min_live_blocks);
	kvfree(ctx->gc_segment_evictions);
	kvfree(ctx->segment_mapped_pages);
	kvfree(ctx->segment_program_counts);
	kvfree(ctx->segment_first_page);
	kvfree(ctx->segment_last_page);
	kvfree(ctx->page_prev_in_segment);
	kvfree(ctx->page_next_in_segment);
	kvfree(ctx->segment_trimmed);
	kvfree(ctx->segment_roles);
	vfree(ctx->input_page);
	kvfree(ctx->predictor_page);
	kvfree(ctx->delta64_candidate_page);
	vfree(ctx->read_page);
	vfree(ctx->read_compressed);
	vfree(ctx->engine.write_scratch);
	vfree(ctx->engine.read_scratch);
	vfree(ctx->engine.read_metadata_cache);
	vfree(ctx->engine.read_extent_cache);
	vfree(ctx->read_pages_store);
	vfree(ctx->read_coalesce_scratch);
	if (ctx->read_slots) {
		for (slot = 0; slot < SWAPZ_PARALLEL_READ_SLOTS; ++slot) {
			vfree(ctx->read_slots[slot].engine.read_scratch);
			vfree(ctx->read_slots[slot].read_compressed);
			kvfree(ctx->read_slots[slot].predictor_page);
		}
		kvfree(ctx->read_slots);
	}
	vfree(ctx->engine.bulk_scratch);
	kvfree(ctx->engine.bulk_txs);
	kvfree(ctx->lz4_workmem);
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
	u64 logical, physical, total_blocks, device_bytes;
	bool is_nullb;
	u32 budget = 0, window = SWAPZ_MAX_RECORDS, verify = 0;
	u32 gc_policy = 2, flush_fail_nth = 0;
	u32 lower_bulk = 1, write_fail_nth = 0, retain = 0;
	swapz_u8 read_slot, prep_lane;
	int error;

	if (argc < 1 || argc > 9 || ti->len % SWAPZ_SECTORS) {
		ti->error = "Usage: <dedicated backing> [read_blocks 0..3] [window 1..64] [verify 0|1] [gc 0=count|1=bytes|2=io] [test_fail_flush_nth 0..64] [lower_bulk 0=off|1=adjacent|2=allow-padding] [test_fail_write_nth 0..65535] [retain_ms 0..4]";
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
	if (!swapz_delta64_lz4_acceleration ||
	    swapz_delta64_lz4_acceleration > 4U) {
		ti->error = "delta64_lz4_acceleration must be in 1..4";
		return -EINVAL;
	}
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
	ctx->delta64_rescue_enabled = swapz_delta64_rescue_enabled;
	ctx->invalidate_cache_on_write_admit =
		swapz_invalidate_cache_on_write_admit;
	ctx->preparation_worker_count =
		ctx->async_prepare ? SWAPZ_DELTA64_PREPARATION_WORKERS : 0U;
	ctx->delta64_lz4_acceleration =
		(swapz_u8)swapz_delta64_lz4_acceleration;
	spin_lock_init(&ctx->queue_lock);
	INIT_LIST_HEAD(&ctx->incoming);
	INIT_LIST_HEAD(&ctx->preparation_incoming);
	INIT_DELAYED_WORK(&ctx->worker, swapz_worker);
	atomic64_set(&ctx->preparation_free_mask,
		     (s64)SWAPZ_PREPARATION_FREE_MASK);
	atomic_set(&ctx->lower_write_active, 0);
	atomic_set(&ctx->lower_read_active, 0);
	atomic_set(&ctx->preparation_workers_active, 0);
	atomic_set(&ctx->preparation_workers_active_max, 0);
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
	if (!ctx->backing->bdev->bd_disk) {
		ti->error = "Backing device has no disk identity";
		error = -EINVAL;
		goto fail;
	}
	is_nullb = !strncmp(ctx->backing->bdev->bd_disk->disk_name, "nullb", 5);
	if (bdev_is_zoned(ctx->backing->bdev) ||
	    bdev_read_only(ctx->backing->bdev) ||
	    bdev_logical_block_size(ctx->backing->bdev) > SWAPZ_BLOCK_BYTES ||
	    SWAPZ_BLOCK_BYTES % bdev_logical_block_size(ctx->backing->bdev)) {
		ti->error = "Unsupported zoned, read-only or unaligned swapz backing";
		error = -EINVAL;
		goto fail;
	}
	ctx->io_client = dm_io_client_create();
	if (IS_ERR(ctx->io_client)) {
		error = PTR_ERR(ctx->io_client);
		ctx->io_client = NULL;
		goto fail;
	}
	device_bytes = (u64)bdev_nr_sectors(ctx->backing->bdev) << SECTOR_SHIFT;
	ctx->backing_device_bytes = device_bytes;
	if (is_nullb) {
		ctx->data_start_block = 0;
		ctx->physical_backing = false;
	} else {
		if (!swapz_allow_physical_backing) {
			ti->error = "Physical backing requires allow_physical_backing=1";
			error = -EOPNOTSUPP;
			goto fail;
		}
		if (flush_fail_nth || write_fail_nth) {
			ti->error = "Fault injection is forbidden on physical backing";
			error = -EINVAL;
			goto fail;
		}
		error = swapz_validate_physical_superblock(ctx, device_bytes);
		if (error) {
			ti->error = "Physical backing lacks a valid matching SWAPZ superblock";
			goto fail;
		}
		ctx->data_start_block = 1U;
		ctx->physical_backing = true;
	}
	/* Bounded ordered-worker fan-out is fixed-on production infrastructure.
	 * ID63 independently controls only adjacent exact-range coalescing. */
	ctx->read_grouping_enabled = true;
	ctx->read_coalescing_enabled = swapz_read_coalesce;
	logical = div_u64(ti->len, SWAPZ_SECTORS);
	total_blocks = div_u64(bdev_nr_sectors(ctx->backing->bdev), SWAPZ_SECTORS);
	if (total_blocks <= ctx->data_start_block) {
		ti->error = "Backing has no usable SWAPZ data blocks";
		error = -EINVAL;
		goto fail;
	}
	physical = total_blocks - ctx->data_start_block;
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
	ctx->gc_min_live_blocks = kvcalloc(ctx->segment_count,
					  sizeof(*ctx->gc_min_live_blocks),
					  GFP_KERNEL);
	ctx->gc_segment_evictions = kvcalloc(ctx->segment_count,
					    sizeof(*ctx->gc_segment_evictions),
					    GFP_KERNEL);
	ctx->segment_mapped_pages = kvcalloc(ctx->segment_count,
					    sizeof(*ctx->segment_mapped_pages),
					    GFP_KERNEL);
	ctx->segment_program_counts = kvcalloc(ctx->segment_count,
					      sizeof(*ctx->segment_program_counts),
					      GFP_KERNEL);
	ctx->segment_first_page = kvcalloc(ctx->segment_count,
					   sizeof(*ctx->segment_first_page),
					   GFP_KERNEL);
	ctx->segment_last_page = kvcalloc(ctx->segment_count,
					  sizeof(*ctx->segment_last_page),
					  GFP_KERNEL);
	ctx->page_prev_in_segment = kvcalloc(logical,
					     sizeof(*ctx->page_prev_in_segment),
					     GFP_KERNEL);
	ctx->page_next_in_segment = kvcalloc(logical,
					     sizeof(*ctx->page_next_in_segment),
					     GFP_KERNEL);
	ctx->segment_trimmed = kvcalloc(ctx->segment_count,
					sizeof(*ctx->segment_trimmed), GFP_KERNEL);
	ctx->segment_roles = kvcalloc(ctx->segment_count,
				     sizeof(*ctx->segment_roles), GFP_KERNEL);
	ctx->maps = kvcalloc(logical, sizeof(*ctx->maps), GFP_KERNEL);
	ctx->live_records = kvcalloc(physical, sizeof(*ctx->live_records), GFP_KERNEL);
	ctx->extent_classes = kvcalloc(physical, sizeof(*ctx->extent_classes), GFP_KERNEL);
	if (!ctx->maps || !ctx->live_records || !ctx->extent_classes ||
	    !ctx->gc_scores || !ctx->gc_io_scores ||
	    !ctx->gc_min_live_blocks ||
	    !ctx->gc_segment_evictions || !ctx->segment_mapped_pages ||
	    !ctx->segment_program_counts || !ctx->segment_first_page ||
	    !ctx->segment_last_page || !ctx->page_prev_in_segment ||
	    !ctx->page_next_in_segment || !ctx->segment_trimmed ||
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
	error = swapz_enable_segment_mapping_counts(&ctx->authority,
						ctx->segment_mapped_pages,
						ctx->segment_count);
	if (error) {
		ti->error = "Cannot initialize exact segment mapping counts";
		goto fail;
	}
	error = swapz_enable_segment_program_counts(&ctx->authority,
						 ctx->segment_program_counts,
						 ctx->segment_count);
	if (error) {
		ti->error = "Cannot initialize logical segment-open accounting";
		goto fail;
	}
	error = swapz_enable_segment_page_lists(&ctx->authority,
					      ctx->segment_first_page,
					      ctx->segment_last_page,
					      ctx->page_prev_in_segment,
					      ctx->page_next_in_segment,
					      ctx->segment_count,
					      ctx->logical_pages);
	if (error) {
		ti->error = "Cannot initialize exact segment page lists";
		goto fail;
	}
	error = swapz_enable_segment_gc_accounting(&ctx->authority,
					      ctx->gc_scores,
					      ctx->gc_io_scores,
					      ctx->gc_min_live_blocks,
					      ctx->segment_count);
	if (error) {
		ti->error = "Cannot initialize incremental GC victim accounting";
		goto fail;
	}
	ctx->authority.dead_segment_recycle = swapz_discard_dead_segment;
	ctx->authority.dead_segment_recycle_opaque = ctx;
	ctx->batch_bytes = vzalloc(SWAPZ_BATCH_BYTES);
	ctx->gc_bytes_store = vzalloc(SWAPZ_BATCH_BYTES);
	ctx->input_page = vzalloc(SWAPZ_BLOCK_BYTES);
	if (ctx->delta64_rescue_enabled) {
		ctx->predictor_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL);
		ctx->delta64_candidate_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL);
	}
	ctx->read_page = vzalloc(SWAPZ_BLOCK_BYTES);
	ctx->read_compressed = vzalloc(SWAPZ_BLOCK_BYTES);
	ctx->engine.write_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES);
	ctx->engine.read_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES);
	ctx->engine.read_metadata_cache =
		vzalloc(SWAPZ_READ_METADATA_CACHE_ENTRIES * SWAPZ_BLOCK_BYTES);
	ctx->engine.read_extent_cache =
		vzalloc(SWAPZ_READ_EXTENT_CACHE_ENTRIES * SWAPZ_MAX_EXTENT_BYTES);
	if (ctx->read_grouping_enabled) {
		ctx->read_slots = kvcalloc(SWAPZ_PARALLEL_READ_SLOTS,
					   sizeof(*ctx->read_slots), GFP_KERNEL);
		ctx->read_pages_store =
			vzalloc((size_t)SWAPZ_MAX_RECORDS * SWAPZ_BLOCK_BYTES);
		ctx->read_coalesce_scratch =
			vzalloc(2U * SWAPZ_MAX_EXTENT_BYTES);
	}
	ctx->engine.bulk_scratch = vzalloc(SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES);
	ctx->engine.bulk_txs = kvcalloc(SWAPZ_MAX_RECORDS,
				       sizeof(*ctx->engine.bulk_txs),
				       GFP_KERNEL);
	ctx->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!ctx->batch_bytes || !ctx->gc_bytes_store ||
	    !ctx->gc_scores || !ctx->gc_io_scores || !ctx->input_page ||
	    (ctx->delta64_rescue_enabled &&
	     (!ctx->predictor_page || !ctx->delta64_candidate_page)) ||
	    !ctx->read_page || !ctx->read_compressed ||
	    !ctx->engine.write_scratch || !ctx->engine.read_scratch ||
	    !ctx->engine.read_metadata_cache || !ctx->engine.read_extent_cache ||
	    (ctx->read_grouping_enabled &&
	     (!ctx->read_slots || !ctx->read_pages_store ||
	      !ctx->read_coalesce_scratch)) ||
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
	for (read_slot = 0; ctx->read_grouping_enabled &&
	     read_slot < SWAPZ_PARALLEL_READ_SLOTS; ++read_slot) {
		struct swapz_read_slot *slot = &ctx->read_slots[read_slot];

		slot->ctx = ctx;
		init_completion(&slot->lower_done);
		slot->engine.authority = &ctx->authority;
		slot->engine.io.opaque = slot;
		slot->engine.io.read_blocks = swapz_parallel_lower_read;
		slot->engine.max_read_blocks_per_record = (swapz_u8)budget;
		slot->engine.read_scratch = vzalloc(SWAPZ_MAX_EXTENT_BYTES);
		slot->read_compressed = vzalloc(SWAPZ_BLOCK_BYTES);
		if (ctx->delta64_rescue_enabled)
			slot->predictor_page = kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL);
		if (!slot->engine.read_scratch || !slot->read_compressed ||
		    (ctx->delta64_rescue_enabled && !slot->predictor_page)) {
			error = -ENOMEM;
			goto fail;
		}
	}
	ctx->inflight_write.run.bytes = ctx->engine.bulk_scratch;
	ctx->inflight_write.run.txs = ctx->engine.bulk_txs;
	ctx->inflight_write.ctx = ctx;
	init_completion(&ctx->inflight_write.lower_done);
	ctx->workqueue = alloc_workqueue(
				"swapz", WQ_MEM_RECLAIM | WQ_UNBOUND, 1);
	if (!ctx->workqueue) {
		error = -ENOMEM;
		goto fail;
	}
	if (ctx->async_prepare) {
		/* Prepared payload capacity stays globally bounded at 64 pages.
		 * Production uses one preparation lane; planner/authority publication
		 * remains ordered and singular. */
		ctx->preparation_pages = vzalloc(SWAPZ_MAX_RECORDS *
					       sizeof(*ctx->preparation_pages));
		ctx->preparation_lanes = kcalloc(ctx->preparation_worker_count,
					       sizeof(*ctx->preparation_lanes),
					       GFP_KERNEL);
		if (!ctx->preparation_pages || !ctx->preparation_lanes) {
			error = -ENOMEM;
			goto fail;
		}
		for (prep_lane = 0; prep_lane < ctx->preparation_worker_count;
		     ++prep_lane) {
			struct swapz_preparation_lane *lane =
				&ctx->preparation_lanes[prep_lane];

			lane->ctx = ctx;
			INIT_WORK(&lane->work, swapz_preparation_worker);
			lane->input_page = vzalloc(SWAPZ_BLOCK_BYTES);
			if (ctx->delta64_rescue_enabled) {
				lane->predictor_page =
					kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL);
				lane->delta64_candidate_page =
					kvmalloc(SWAPZ_BLOCK_BYTES, GFP_KERNEL);
			}
			lane->lz4_workmem = kvmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
			if (!lane->input_page ||
			    (ctx->delta64_rescue_enabled &&
			     (!lane->predictor_page || !lane->delta64_candidate_page)) ||
			    !lane->lz4_workmem) {
				error = -ENOMEM;
				goto fail;
			}
		}
		ctx->preparation_workqueue = alloc_workqueue(
					"swapz-lz4", WQ_MEM_RECLAIM | WQ_UNBOUND,
					ctx->preparation_worker_count);
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
	DMINFO("swapz alpha %s logical_pages=%u physical_blocks=%u data_start=%u physical=%u window=%u read_cap=%u LIVE GC EXPERIMENTAL",
	       SWAPZ_ALPHA_VERSION, ctx->logical_pages, ctx->physical_blocks,
	       ctx->data_start_block, ctx->physical_backing ? 1U : 0U,
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
		  (sector_t)(ctx->data_start_block + ctx->physical_blocks) *
			  SWAPZ_SECTORS, data);
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

static void swapz_gc_victim_distribution(const struct swapz_dm *ctx,
					  swapz_u32 *distinct,
					  swapz_u32 *minimum,
					  swapz_u32 *maximum)
{
	swapz_u32 segment;
	swapz_u32 seen = 0, min_count = U32_MAX, max_count = 0;

	for (segment = 0; segment < ctx->segment_count; ++segment) {
		swapz_u32 count = ctx->gc_segment_evictions[segment];

		if (!count)
			continue;
		seen++;
		min_count = min(min_count, count);
		max_count = max(max_count, count);
	}
	*distinct = seen;
	*minimum = seen ? min_count : 0;
	*maximum = max_count;
}

static void swapz_segment_program_distribution(const struct swapz_dm *ctx,
					      swapz_u32 *minimum,
					      u64 *sum,
					      swapz_u32 *maximum)
{
	swapz_u32 segment, min_count = U32_MAX, max_count = 0;
	u64 total = 0;

	for (segment = 0; segment < ctx->segment_count; ++segment) {
		swapz_u32 count = ctx->segment_program_counts[segment];

		min_count = min(min_count, count);
		max_count = max(max_count, count);
		total += count;
	}
	*minimum = min_count == U32_MAX ? 0 : min_count;
	*sum = total;
	*maximum = max_count;
}

static void swapz_status(struct dm_target *ti, status_type_t type,
		       unsigned int flags, char *result, unsigned int maxlen)
{
	struct swapz_dm *ctx = ti->private;
	swapz_u32 gc_distinct_victims, gc_victim_min_evictions;
	swapz_u32 gc_victim_max_evictions;
	swapz_u32 segment_program_min, segment_program_max;
	u64 segment_program_sum;
	u64 engine_publish_auth_wall_ns;
	struct swapz_preparation_totals prep;
	unsigned int sz = 0;

	(void)flags;
	swapz_preparation_totals_snapshot(ctx, &prep);
	swapz_gc_victim_distribution(ctx, &gc_distinct_victims,
				     &gc_victim_min_evictions,
				     &gc_victim_max_evictions);
	swapz_segment_program_distribution(ctx, &segment_program_min,
					   &segment_program_sum,
					   &segment_program_max);
	engine_publish_auth_wall_ns =
		ctx->engine_publish_wall_ns >= ctx->engine_publish_crc_wall_ns ?
		ctx->engine_publish_wall_ns - ctx->engine_publish_crc_wall_ns : 0;
	switch (type) {
	case STATUSTYPE_INFO:
		DMEMIT("version=%s mode=alpha-live-gc logical_write=%llu logical_read=%llu "
		       "physical_write=%llu physical_write_reqs=%llu "
		       "physical_read=%llu physical_read_reqs=%llu "
		       "compressed=%llu raw=%llu zero_elided=%llu discarded=%llu "
		       "lz4_acceleration=%u delta64_lz4_acceleration=%u "
		       "lz4_attempts=%llu lz4_accepted_bytes=%llu "
		       "lz4_size_le256=%llu lz4_size_257_1024=%llu "
		       "lz4_size_1025_2048=%llu lz4_size_2049_3072=%llu "
		       "lz4_size_3073_3568=%llu lz4_raw_fallback=%llu "
		       "windows=%llu reordered=%llu cursor=%u reserve=%u "
		       "gc_victims=%llu gc_role_rotations=%llu "
		       "gc_distinct_victims=%u gc_victim_min_evictions=%u "
		       "gc_victim_max_evictions=%u "
		       "last_gc_victim=%u last_gc_destination=%u "
		       "gc_pages=%llu gc_read=%llu gc_write=%llu "
		       "gc_policy=%u gc_selected_bytes=%llu gc_selected_pages=%llu "
		       "gc_selected_io_estimate=%llu gc_no_headroom_skips=%llu "
		       "gc_choose_wall_ns=%llu gc_choose_calls=%llu "
		       "gc_choose_map_entries=%llu gc_choose_segment_entries=%llu "
		       "gc_relocation_map_entries=%llu "
		       "gc_read_reqs=%llu gc_write_reqs=%llu "
		       "dead_segment_reuses=%u "
		       "segment_discards_eligible=%llu segment_discards_issued=%llu "
		       "segment_discards_completed=%llu segment_discards_unsupported=%llu "
		       "segment_discards_failed=%llu segment_discard_sectors=%llu "
		       "segment_discard_wall_ns=%llu "
		       "segment_discards_skipped_already_trimmed=%llu "
		       "alignment_hole_blocks_foreground=%llu "
		       "alignment_hole_blocks_gc=%llu "
		       "segment_tail_waste_blocks_foreground=%llu "
		       "segment_tail_waste_blocks_gc=%llu run_splits_by_hole=%u "
		       "alloc_probe_segments=%llu alloc_probe_full_scans=%llu "
		       "alloc_probe_wall_ns=%llu "
		       "segment_program_min=%u segment_program_sum=%llu "
		       "segment_program_max=%u segment_program_segments=%u "
		       "write_verify_blocks=%u verify=%u "
		       "write_submitted=%llu write_submitted_reqs=%llu "
		       "read_submitted=%llu read_submitted_reqs=%llu "
		       "write_fault_nth=%u write_fault_calls=%llu write_fault_injected=%llu "
		       "flush_calls=%llu flush_ok=%llu flush_err=%llu "
		       "flush_injected=%llu flush_fault_nth=%u "
		       "packed_placement=%u logical_open_balance=%u "
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
		       "win1_pack_tail_target=%llu win1_pack_read_bypass=%llu "
		       "win1_pack_wave_interrupted=%llu "
		       "single_tail_deferrals=%llu single_tail_companions=%llu "
		       "win1_deadline_deferred_tail=%llu "
		       "win1_idle_deferred_tail=%llu single_tail_other_clears=%llu "
		       "single_tail_comp_age_le250us=%llu "
		       "single_tail_comp_age_251_500us=%llu "
		       "single_tail_comp_age_501_1000us=%llu "
		       "single_tail_comp_age_gt1000us=%llu "
		       "single_tail_comp_age_1001_1250us=%llu "
		       "single_tail_comp_age_1251_1500us=%llu "
		       "single_tail_comp_age_1501_1750us=%llu "
		       "single_tail_comp_age_gt1750us=%llu "
		       "single_tail_deadline_age_le250us=%llu "
		       "single_tail_deadline_age_251_500us=%llu "
		       "single_tail_deadline_age_501_1000us=%llu "
		       "single_tail_deadline_age_gt1000us=%llu "
		       "single_tail_comp_after_lower_done=%llu "
		       "single_tail_comp_after_read_bypass=%llu "
		       "single_tail_comp_after_both=%llu "
		       "single_tail_deadline_after_lower_done=%llu "
		       "single_tail_deadline_after_read_bypass=%llu "
		       "single_tail_deadline_after_both=%llu "
		       "window_gc_pressure=%llu "
		       "age_le100us=%llu age_101_1000us=%llu "
		       "age_gt1000us=%llu age_sum_ns=%llu age_max_ns=%llu "
		       "retain_ms=%u retain_passes=%llu retain_timer_arms=%llu "
		       "retain_timer_arm_skips=%llu "
		       "async_prepare=%u delta64_prepare_workers=%u "
		       "delta64_prepare_active_max=%u delta64_prepare_pages=%llu "
		       "write_pipeline_depth=%u pipeline_active_max=%u "
		       "delta64_prepare_parallel_starts=%llu "
		       "guard_inflight_zero_shrink=%u "
		       "prep_lower_write_overlap_starts=%llu "
		       "prep_lower_write_overlap_ns=%llu "
		       "prep_lower_read_overlap_starts=%llu "
		       "prep_lower_read_overlap_ns=%llu prep_wave_kicks=%llu "
		       "prep_lower_write_samples=%llu "
		       "prep_lower_write_start_queued=%llu "
		       "prep_lower_write_start_nonempty=%llu "
		       "prep_lower_write_end_queued=%llu "
		       "prep_lower_write_end_nonempty=%llu "
		       "pipeline_async_runs=%llu pipeline_completed_runs=%llu "
		       "pipeline_collected_pages=%llu pipeline_read_bypass_skips=%llu "
		       "pipeline_finalize_waits=%llu pipeline_finalize_wait_wall_ns=%llu "
		       "k1_ready_wait_windows=%llu k1_ready_wait_records=%llu "
		       "k1_ready_wait_wall_ns=%llu k1_ready_wait_max_records=%llu "
		       "k1_ready_wait_pack_ready=%llu k1_ready_wait_full=%llu "
		       "k1_ready_wait_deadline=%llu k1_ready_wait_fence=%llu "
		       "k1_ready_wait_other=%llu pipeline_active_wall_ns=%llu "
		       "pipeline_post_lower_wall_ns=%llu "
		       "prep_producer_head_claims=%llu prep_producer_tail_claims=%llu "
		       "prep_ordered_inline=%llu prep_ordered_handoffs=%llu "
		       "prep_ordered_waits=%llu prep_wait_wall_ns=%llu "
		       "lz4_wall_ns=%llu decode_wall_ns=%llu "
		       "ordered_lz4_wall_ns=%llu prep_lz4_wall_ns=%llu "
		       "write_copy_wall_ns=%llu write_copy_bytes=%llu "
		       "ordered_write_copy_wall_ns=%llu prep_write_copy_wall_ns=%llu "
		       "direct_lz4_input_pages=%llu "
		       "read_copy_wall_ns=%llu read_copy_bytes=%llu "
		       "window_sort_wall_ns=%llu window_commit_wall_ns=%llu "
		       "window_commit_nonio_wall_ns=%llu "
		       "engine_plan_wall_ns=%llu engine_pack_wall_ns=%llu "
		       "engine_publish_wall_ns=%llu engine_publish_crc_wall_ns=%llu "
		       "engine_publish_auth_wall_ns=%llu engine_prehashed_records=%u "
		       "batch_snapshot_crc_wall_ns=%llu "
		       "batch_pause_crc_wall_ns=%llu batch_resume_crc_wall_ns=%llu "
		       "prep_crc_wall_ns=%llu ordered_crc_wall_ns=%llu "
		       "read_engine_nonio_wall_ns=%llu "
		       "lower_read_wall_ns=%llu lower_write_wall_ns=%llu "
		       "ordered_worker_wall_ns=%llu prep_worker_wall_ns=%llu "
		       "ordered_worker_cpu_ns=%llu prep_worker_cpu_ns=%llu "
		       "read_worker_cpu_ns=%llu "
		       "write_wait_le1ms=%llu write_wait_1to4ms=%llu "
		       "write_wait_gt4ms=%llu gc_wall_ns=%llu "
		       "close_deadline=%llu "
		       "deadline_before_bio=%llu deadline_after_read=%llu "
		       "deadline_worker_with_local=%llu deadline_worker_empty=%llu "
		       "retained_read_bypasses=%llu "
		       "close_pack_ready=%llu "
		       "pack_close_tail_target=%llu pack_close_tail_target_le4=%llu "
		       "pack_close_burst_target=%llu pack_close_service_dry=%llu "
		       "pack_close_burst_admission=%llu pack_close_burst_worker=%llu "
		       "pack_close_burst_target_le4=%llu "
		       "pack_close_burst_target_5_8=%llu "
		       "pack_close_burst_target_9_16=%llu "
		       "pack_close_burst_target_17_64=%llu "
		       "pack_close_burst_count_le4=%llu "
		       "pack_close_burst_count_5_8=%llu "
		       "pack_close_burst_count_9_16=%llu "
		       "pack_close_burst_count_17_64=%llu "
		       "pack_close_burst_overshoot=%llu "
		       "pack_tail_samples=%llu "
		       "pack_tail_zero_inflight=%llu pack_tail_zero_idle=%llu "
		       "pack_tail_one_inflight=%llu pack_tail_one_idle=%llu "
		       "pack_tail_many_inflight=%llu pack_tail_many_idle=%llu "
		       "burst_target_grows=%llu burst_target_shrinks=%llu "
		       "burst_shrink_inflight_zero_skips=%llu "
		       "burst_shrink_after_inflight_zero=%llu "
		       "burst_shrink_after_read_bypass=%llu "
		       "burst_shrink_other=%llu "
		       "burst_shrink_target_le8=%llu "
		       "burst_shrink_target_9_32=%llu "
		       "burst_shrink_target_gt32=%llu "
		       "packed_early_commits=%llu "
		       "single_pack_deferrals=%llu accepted_burst_extensions=%llu "
		       "accepted_burst_tail_flushes=%llu accepted_burst_read_caps=%llu "
		       "retained_burst_target=%u "
		       "read_meta_reqs=%u read_payload_reqs=%u "
		       "read_payload_blocks=%u read_meta_cache_hits=%u "
		       "read_meta_lru_hits=%u "
		       "read_meta_set_lookups=%llu read_meta_set_hits=%llu "
		       "read_meta_set_probes=%llu read_meta_set_replacements=%llu "
		       "read_meta_primary_hits=%llu read_meta_secondary_hits=%llu "
		       "read_meta_copy_bytes=%llu "
		       "read_full_extent_reqs=%u read_full_cache_hits=%u "
		       "read_two_block_skips=%u "
		       "read_grouping_enabled=%u read_coalescing_enabled=%u "
		       "parallel_reads_enabled=%u "
		       "parallel_read_pairs=%llu parallel_read_same_extent_pairs=%llu "
		       "parallel_read_async_batches=%llu parallel_read_async_slots=%llu "
		       "parallel_read_distinct_extent_pairs=%llu "
		       "parallel_read_adjacent_extent_pairs=%llu "
		       "parallel_read_adjacent_extent_blocks=%llu "
		       "parallel_read_adjacent_chain_3plus=%llu "
		       "parallel_read_adjacent_chain_extent_max=%llu "
		       "parallel_read_adjacent_chain_blocks_max=%llu "
		       "parallel_read_coalesced_pairs=%llu "
		       "parallel_read_coalesced_reqs_saved=%llu "
		       "parallel_read_coalesced_blocks=%llu "
		       "parallel_read_coalesce_extra_blocks=%llu "
		       "parallel_read_coalesce_skip_cached=%llu "
		       "parallel_read_coalesce_skip_noncontig_slot=%llu "
		       "parallel_read_coalesce_skip_gap=%llu "
		       "parallel_read_coalesce_skip_other=%llu "
		       "failed=%u error=%d",
		       SWAPZ_ALPHA_VERSION, ctx->logical_write_bytes,
		       ctx->logical_read_bytes, ctx->physical_write_bytes,
		       ctx->physical_write_reqs, ctx->physical_read_bytes,
		       ctx->physical_read_reqs, ctx->compressed_pages,
		       ctx->raw_pages, ctx->zero_elided_pages,
		       ctx->discard_pages,
		       SWAPZ_ORDINARY_LZ4_ACCELERATION, ctx->delta64_lz4_acceleration,
		       ctx->lz4_attempts, ctx->lz4_accepted_bytes,
		       ctx->lz4_size_bins[0], ctx->lz4_size_bins[1],
		       ctx->lz4_size_bins[2], ctx->lz4_size_bins[3],
		       ctx->lz4_size_bins[4], ctx->lz4_size_bins[5],
		       ctx->windows,
		       ctx->reordered_records, ctx->authority.next_block,
		       ctx->authority.reserve_blocks,
		       ctx->gc_victims, ctx->gc_role_rotations,
		       gc_distinct_victims, gc_victim_min_evictions,
		       gc_victim_max_evictions,
		       ctx->last_gc_victim, ctx->last_gc_destination,
		       ctx->gc_pages, ctx->gc_read_bytes, ctx->gc_write_bytes,
		       ctx->gc_cost_policy, ctx->gc_selected_live_bytes,
		       ctx->gc_selected_live_records, ctx->gc_selected_io_cost,
		       ctx->gc_no_headroom_skips,
		       ctx->gc_choose_wall_ns, ctx->gc_choose_calls,
		       ctx->gc_choose_map_entries, ctx->gc_choose_segment_entries,
		       ctx->gc_relocation_map_entries,
		       ctx->gc_read_reqs, ctx->gc_write_reqs,
		       ctx->authority.recycled_dead_segments,
		       ctx->segment_discards_eligible,
		       ctx->segment_discards_issued,
		       ctx->segment_discards_completed,
		       ctx->segment_discards_unsupported,
		       ctx->segment_discards_failed,
		       ctx->segment_discard_sectors,
		       ctx->segment_discard_wall_ns,
		       ctx->segment_discards_skipped_already_trimmed,
		       ctx->authority.alignment_hole_blocks_foreground,
		       ctx->authority.alignment_hole_blocks_gc,
		       ctx->authority.segment_tail_waste_blocks_foreground,
		       ctx->authority.segment_tail_waste_blocks_gc,
		       ctx->engine.run_splits_by_hole,
		       ctx->authority.alloc_probe_segments,
		       ctx->authority.alloc_probe_full_scans,
		       ctx->authority.alloc_probe_wall_ns,
		       segment_program_min, segment_program_sum,
		       segment_program_max, ctx->segment_count,
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
		       1U,
		       0U,
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
		       ctx->win1_pack_tail_target,
		       ctx->win1_pack_read_bypass,
		       ctx->win1_pack_wave_interrupted,
		       ctx->single_tail_deferrals,
		       ctx->single_tail_companions,
		       ctx->win1_deadline_deferred_tail,
		       ctx->win1_idle_deferred_tail,
		       ctx->single_tail_other_clears,
		       ctx->single_tail_companion_age_le250us,
		       ctx->single_tail_companion_age_251_500us,
		       ctx->single_tail_companion_age_501_1000us,
		       ctx->single_tail_companion_age_gt1000us,
		       ctx->single_tail_companion_age_1001_1250us,
		       ctx->single_tail_companion_age_1251_1500us,
		       ctx->single_tail_companion_age_1501_1750us,
		       ctx->single_tail_companion_age_gt1750us,
		       ctx->single_tail_deadline_age_le250us,
		       ctx->single_tail_deadline_age_251_500us,
		       ctx->single_tail_deadline_age_501_1000us,
		       ctx->single_tail_deadline_age_gt1000us,
		       ctx->single_tail_companion_after_lower_done,
		       ctx->single_tail_companion_after_read_bypass,
		       ctx->single_tail_companion_after_both,
		       ctx->single_tail_deadline_after_lower_done,
		       ctx->single_tail_deadline_after_read_bypass,
		       ctx->single_tail_deadline_after_both,
		       ctx->window_gc_pressure,
		       ctx->window_age_le_100us, ctx->window_age_101_1000us,
		       ctx->window_age_gt_1000us, ctx->window_age_sum_ns,
		       ctx->window_age_max_ns,
		       ctx->retain_ms, ctx->retain_worker_passes,
		       ctx->retain_timer_arms, ctx->retain_timer_arm_skips,
		       ctx->async_prepare, ctx->preparation_worker_count,
		       (unsigned int)atomic_read(&ctx->preparation_workers_active_max),
		       prep.prepared_pages,
		       SWAPZ_WRITE_PIPELINE_DEPTH, ctx->pipeline_active_max,
		       0ULL, 0U,
		       prep.prepared_during_lower_write,
		       prep.lower_write_overlap_ns,
		       prep.prepared_during_lower_read,
		       prep.lower_read_overlap_ns,
		       ctx->preparation_wave_kicks,
		       ctx->prep_lower_write_samples,
		       ctx->prep_lower_write_start_queued,
		       ctx->prep_lower_write_start_nonempty,
		       ctx->prep_lower_write_end_queued,
		       ctx->prep_lower_write_end_nonempty,
		       ctx->pipeline_async_runs, ctx->pipeline_completed_runs,
		       ctx->pipeline_collected_pages,
		       ctx->pipeline_read_bypass_skips,
		       ctx->pipeline_finalize_waits,
		       ctx->pipeline_finalize_wait_wall_ns,
		       ctx->k1_ready_wait_windows,
		       ctx->k1_ready_wait_records,
		       ctx->k1_ready_wait_wall_ns,
		       ctx->k1_ready_wait_max_records,
		       ctx->k1_ready_wait_pack_ready,
		       ctx->k1_ready_wait_full,
		       ctx->k1_ready_wait_deadline,
		       ctx->k1_ready_wait_fence,
		       ctx->k1_ready_wait_other,
		       ctx->pipeline_active_wall_ns,
		       ctx->pipeline_post_lower_wall_ns,
		       ctx->preparation_producer_head_claims,
		       ctx->preparation_producer_tail_claims,
		       ctx->preparation_ordered_inline,
		       ctx->preparation_ordered_handoffs,
		       ctx->preparation_ordered_waits,
		       ctx->preparation_ordered_wait_wall_ns,
		       ctx->lz4_wall_ns + prep.lz4_wall_ns,
		       ctx->decode_wall_ns,
		       ctx->lz4_wall_ns, prep.lz4_wall_ns,
		       prep.copy_wall_ns +
			       ctx->ordered_write_copy_wall_ns,
		       prep.copy_bytes +
			       ctx->ordered_write_copy_bytes,
		       ctx->ordered_write_copy_wall_ns,
		       prep.copy_wall_ns,
		       prep.direct_lz4_pages +
			       ctx->ordered_direct_lz4_pages,
		       ctx->read_copy_wall_ns, ctx->read_copy_bytes,
		       ctx->window_sort_wall_ns, ctx->window_commit_wall_ns,
		       ctx->window_commit_nonio_wall_ns,
		       ctx->engine_plan_wall_ns, ctx->engine_pack_wall_ns,
		       ctx->engine_publish_wall_ns, ctx->engine_publish_crc_wall_ns,
		       engine_publish_auth_wall_ns, ctx->engine.prehashed_records,
		       ctx->authority.batch_snapshot_crc_wall_ns,
		       ctx->authority.batch_pause_crc_wall_ns,
		       ctx->authority.batch_resume_crc_wall_ns,
		       prep.crc_wall_ns, ctx->ordered_crc_wall_ns,
		       ctx->read_engine_nonio_wall_ns,
		       ctx->lower_read_wall_ns, ctx->lower_write_wall_ns,
		       ctx->ordered_worker_wall_ns,
		       prep.worker_wall_ns,
		       ctx->ordered_worker_cpu_ns,
		       prep.worker_cpu_ns,
		       ctx->read_worker_cpu_ns,
		       ctx->write_wait_le_1ms, ctx->write_wait_1_to_4ms,
		       ctx->write_wait_gt_4ms, ctx->gc_wall_ns,
		       ctx->window_close_reasons[SWAPZ_CLOSE_DEADLINE],
		       ctx->deadline_before_bio, ctx->deadline_after_read,
		       ctx->deadline_worker_with_local, ctx->deadline_worker_empty,
		       ctx->retained_read_bypasses,
		       ctx->window_close_reasons[SWAPZ_CLOSE_PACK_READY],
		       ctx->pack_close_tail_target,
		       ctx->pack_close_tail_target_le4,
		       ctx->pack_close_burst_target,
		       ctx->pack_close_service_dry,
		       ctx->pack_close_burst_admission,
		       ctx->pack_close_burst_worker,
		       ctx->pack_close_burst_target_le4,
		       ctx->pack_close_burst_target_5_8,
		       ctx->pack_close_burst_target_9_16,
		       ctx->pack_close_burst_target_17_64,
		       ctx->pack_close_burst_count_le4,
		       ctx->pack_close_burst_count_5_8,
		       ctx->pack_close_burst_count_9_16,
		       ctx->pack_close_burst_count_17_64,
		       ctx->pack_close_burst_overshoot,
		       ctx->pack_tail_samples,
		       ctx->pack_tail_zero_inflight,
		       ctx->pack_tail_zero_idle,
		       ctx->pack_tail_one_inflight,
		       ctx->pack_tail_one_idle,
		       ctx->pack_tail_many_inflight,
		       ctx->pack_tail_many_idle,
		       ctx->burst_target_grows,
		       ctx->burst_target_shrinks,
		       0ULL, /* retired ID64 compatibility token */
		       0ULL, /* completion-aware zero-tail makes this impossible */
		       ctx->burst_shrink_after_read_bypass,
		       ctx->burst_shrink_other,
		       ctx->burst_shrink_target_le8,
		       ctx->burst_shrink_target_9_32,
		       ctx->burst_shrink_target_gt32,
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
		       ctx->engine.read_metadata_set_lookups,
		       ctx->engine.read_metadata_set_hits,
		       ctx->engine.read_metadata_set_probes,
		       ctx->engine.read_metadata_set_replacements,
		       ctx->engine.read_metadata_primary_hits,
		       ctx->engine.read_metadata_secondary_hits,
		       ctx->engine.read_metadata_copy_bytes,
		       ctx->engine.read_full_extent_requests,
		       ctx->engine.read_full_extent_cache_hits,
		       ctx->engine.read_two_block_skips,
		       ctx->read_grouping_enabled,
		       ctx->read_coalescing_enabled,
		       1U,
		       ctx->parallel_read_pairs,
		       ctx->parallel_read_same_extent_pairs,
		       ctx->parallel_read_async_batches,
		       ctx->parallel_read_async_slots,
		       ctx->parallel_read_distinct_extent_pairs,
		       ctx->parallel_read_adjacent_extent_pairs,
		       ctx->parallel_read_adjacent_extent_blocks,
		       ctx->parallel_read_adjacent_chain_3plus,
		       ctx->parallel_read_adjacent_chain_extent_max,
		       ctx->parallel_read_adjacent_chain_blocks_max,
		       ctx->parallel_read_coalesced_pairs,
		       ctx->parallel_read_coalesced_reqs_saved,
		       ctx->parallel_read_coalesced_blocks,
		       ctx->parallel_read_coalesce_extra_blocks,
		       ctx->parallel_read_coalesce_skip_cached,
		       ctx->parallel_read_coalesce_skip_noncontig_slot,
		       ctx->parallel_read_coalesce_skip_gap,
		       ctx->parallel_read_coalesce_skip_other,
		       ctx->failed, ctx->last_error);
		/* Retired compatibility token: the read-bypass detach override is gone. */
		DMEMIT(" k1_allow_after_read_bypass=0 "
		       "read_coalesce_max_blocks=%u "
		       "invalidate_cache_on_write_admit=%u "
		       "bio_segments_gt1=%llu bio_segments_max=%u "
		       "bio_nonzero_offset=%llu bio_compound_folio_pages=%llu "
		       "bio_copy_fallback_pages=%llu",
		       SWAPZ_READ_COALESCE_MAX_BLOCKS,
		       ctx->invalidate_cache_on_write_admit,
		       ctx->bio_segments_gt1, ctx->bio_segments_max,
		       ctx->bio_nonzero_offset, ctx->bio_compound_folio_pages,
		       ctx->ordered_copy_fallback_pages + prep.copy_fallback_pages);
		/* These independent single-writer values are diagnostic while busy;
		 * qualification snapshots only at drained measurement boundaries. */
		DMEMIT(" delta64_rescue=%u delta64_eligible=%llu "
		       "delta64_classifier_pass=%llu "
		       "delta64_attempts=%llu delta64_adopted=%llu "
		       "delta64_direct_adopted=%llu delta64_first_lz4_skipped=%llu "
		       "delta64_raw_rescues=%llu delta64_lz4_rescues=%llu "
		       "delta64_pack_eligible=%llu delta64_pack_attempts=%llu "
		       "delta64_pack_cliff_crossings=%llu delta64_pack_adopted=%llu "
		       "delta64_score_0_7=%llu delta64_score_8_15=%llu "
		       "delta64_score_16_23=%llu delta64_score_ge24=%llu "
		       "delta64_payload_bytes_saved=%llu "
		       "delta64_raw_payload_bytes_saved=%llu "
		       "delta64_lz4_payload_bytes_saved=%llu "
		       "delta64_transform_calls=%llu "
		       "delta64_transform_wall_ns=%llu delta64_wall_ns=%llu",
		       ctx->delta64_rescue_enabled,
		       READ_ONCE(ctx->ordered_delta64.eligible) +
			prep.delta64.eligible,
		       READ_ONCE(ctx->ordered_delta64.classifier_pass) +
			prep.delta64.classifier_pass,
		       READ_ONCE(ctx->ordered_delta64.attempts) +
			prep.delta64.attempts,
		       READ_ONCE(ctx->ordered_delta64.adopted) +
			prep.delta64.adopted,
		       READ_ONCE(ctx->ordered_delta64.direct_adopted) +
			prep.delta64.direct_adopted,
		       READ_ONCE(ctx->ordered_delta64.first_lz4_skipped) +
			prep.delta64.first_lz4_skipped,
		       READ_ONCE(ctx->ordered_delta64.raw_rescues) +
			prep.delta64.raw_rescues,
		       READ_ONCE(ctx->ordered_delta64.lz4_rescues) +
			prep.delta64.lz4_rescues,
		       READ_ONCE(ctx->ordered_delta64.pack_eligible) +
			prep.delta64.pack_eligible,
		       READ_ONCE(ctx->ordered_delta64.pack_attempts) +
			prep.delta64.pack_attempts,
		       READ_ONCE(ctx->ordered_delta64.pack_cliff_crossings) +
			prep.delta64.pack_cliff_crossings,
		       READ_ONCE(ctx->ordered_delta64.pack_adopted) +
			prep.delta64.pack_adopted,
		       READ_ONCE(ctx->ordered_delta64.score_0_7) +
			prep.delta64.score_0_7,
		       READ_ONCE(ctx->ordered_delta64.score_8_15) +
			prep.delta64.score_8_15,
		       READ_ONCE(ctx->ordered_delta64.score_16_23) +
			prep.delta64.score_16_23,
		       READ_ONCE(ctx->ordered_delta64.score_ge24) +
			prep.delta64.score_ge24,
		       READ_ONCE(ctx->ordered_delta64.payload_bytes_saved) +
			prep.delta64.payload_bytes_saved,
		       READ_ONCE(ctx->ordered_delta64.raw_payload_bytes_saved) +
			prep.delta64.raw_payload_bytes_saved,
		       READ_ONCE(ctx->ordered_delta64.lz4_payload_bytes_saved) +
			prep.delta64.lz4_payload_bytes_saved,
		       READ_ONCE(ctx->ordered_delta64.transform_calls) +
			prep.delta64.transform_calls,
		       READ_ONCE(ctx->ordered_delta64.transform_wall_ns) +
			prep.delta64.transform_wall_ns,
		       READ_ONCE(ctx->ordered_delta64.wall_ns) +
			prep.delta64.wall_ns);
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
	int error;

	error = swapz_predictor_init();
	if (error)
		return error;
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
