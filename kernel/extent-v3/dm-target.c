// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz3 - EXPERIMENTAL V3.0-alpha volatile Device Mapper swap target.
 *
 * First runtime integration of actual V3 4/8/16KiB extents. Uses 4KiB logical
 * pages, LZ4, bounded size-aware write windows and synchronous dm-io through
 * one WQ_MEM_RECLAIM worker. No in-place compatibility with dm-swapz V2.2.
 *
 * IMPORTANT ALPHA LIMIT: physical allocation is append-only, and GC/recycling
 * is deliberately NOT enabled until relocation/refcount correctness is proven.
 * On ENOSPC fail closed; do not load for unlimited live swap pressure.
 */
#define DM_MSG_PREFIX "swapz3"
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/device-mapper.h>
#include <linux/dm-io.h>
#include <linux/highmem.h>
#include <linux/ioprio.h>
#include <linux/lz4.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/workqueue.h>
#include <linux/spinlock.h>
#include <linux/string.h>
#include "engine.h"

#if PAGE_SIZE != SV3_BLOCK_BYTES
#error "swapz3 V3.0-alpha requires 4KiB PAGE_SIZE"
#endif
#define SV3_SECTORS (SV3_BLOCK_BYTES >> SECTOR_SHIFT)
#define SV3_BATCH_BYTES (SV3_MAX_RECORDS * SV3_BLOCK_BYTES)
#define SV3_ALPHA_VERSION "3.0.0-alpha.2"
#define SV3_WORK_QUANTUM_BIOS 64U

struct sv3_bio_ref {
	struct list_head list;
	struct bio *bio;
};

struct sv3_pending_bio {
	struct bio *bio;
	sv3_u32 logical;
	sv3_u16 length;
};

struct sv3_dm {
	struct dm_target *target;
	struct dm_dev *backing;
	struct dm_io_client *io_client;
	struct workqueue_struct *workqueue;
	struct work_struct worker;
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
	sv3_u32 *gc_scores;  /* [physical 1MiB segments] */
	sv3_u32 segment_count;
	u64 gc_victims;
	u64 gc_pages;
	u64 gc_read_bytes;
	u64 gc_write_bytes;
	sv3_u8 batch_count;
	sv3_u8 max_window;
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
	u64 compressed_pages;
	u64 raw_pages;
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
		     sv3_u8 blocks, u8 *bytes)
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

static int sv3_lower_read(void *opaque, sv3_u32 block, sv3_u8 blocks,
			  sv3_u8 *destination)
{
	return sv3_lower(opaque, REQ_OP_READ, block, blocks, destination);
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
			if (!ctx->used[i] &&
			    (largest < 0 ||
			     ctx->batch[i].length > ctx->batch[largest].length))
				largest = i;
		ctx->used[largest] = 1;
		ctx->planned_to_batch[position++] = (u8)largest;

		/* V3 metadata: header(16) + two descriptors(32). */
		for (i = 0; i < ctx->batch_count; ++i) {
			int remaining;

			if (ctx->used[i])
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
	for (position = 0; position < ctx->batch_count; ++position) {
		sv3_u8 index = ctx->planned_to_batch[position];

		if (index != position)
			ctx->reordered_records++;
		ctx->planned[position] = (struct sv3_compressed_page) {
			.logical_page = ctx->batch[index].logical,
			.payload = ctx->batch_bytes + (size_t)index * SV3_BLOCK_BYTES,
			.length = ctx->batch[index].length,
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
	error = sv3_engine_write_window(&ctx->engine, ctx->gc_planned,
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
	error = sv3_finish_raw(&ctx->authority, &tx, ctx->input_page, completed, error);
	if (!error)
		ctx->gc_pages++;
	return error;
}

static int sv3_gc_choose_victim(struct sv3_dm *ctx, sv3_u32 *victim)
{
	sv3_u32 logical, segment, selected = ~(sv3_u32)0;
	sv3_u32 best = ~(sv3_u32)0;

	memset(ctx->gc_scores, 0,
	       (size_t)ctx->segment_count * sizeof(*ctx->gc_scores));
	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		const struct sv3_map *m = &ctx->maps[logical];

		if (!m->valid)
			continue;
		if (m->start_block >= ctx->physical_blocks)
			return -EUCLEAN;
		ctx->gc_scores[m->start_block / SV3_SEGMENT_BLOCKS]++;
	}
	for (segment = 0; segment < ctx->segment_count; ++segment) {
		sv3_u32 live = ctx->gc_scores[segment];

		if (!live || segment == ctx->authority.open_segment)
			continue;
		if (live < best) {
			best = live;
			selected = segment;
		}
	}
	if (selected == ~(sv3_u32)0)
		return -ENOSPC;
	*victim = selected;
	return 0;
}

static int sv3_gc_compact_one(struct sv3_dm *ctx)
{
	struct sv3_authority *a = &ctx->authority;
	sv3_u32 old_next, old_open, old_probe, victim, logical, block;
	u64 before_read, before_write;
	int error;

	if (a->in_flight || a->gc_allocation)
		return -EBUSY;
	error = sv3_gc_choose_victim(ctx, &victim);
	if (error)
		return error;
	old_next = a->next_block;
	old_open = a->open_segment;
	old_probe = a->next_segment_probe;
	before_read = ctx->physical_read_bytes;
	before_write = ctx->physical_write_bytes;
	/*
	 * Temporarily allow the worker to use a genuinely FREE segment from
	 * the full physical region, including the reserved tail. The liveness
	 * scanner rejects old physical bytes whenever a live mapping points
	 * there. Restore the foreground cursor after the victim is drained.
	 */
	a->gc_allocation = 1;
	a->open_segment = ~(sv3_u32)0;
	a->next_segment_probe =
		(ctx->physical_blocks - a->reserve_blocks) /
		SV3_SEGMENT_BLOCKS;
	ctx->gc_count = 0;

	for (logical = 0; logical < ctx->logical_pages; ++logical) {
		struct sv3_map snapshot = ctx->maps[logical];
		sv3_u16 length;

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
	ctx->gc_victims++;
out:
	ctx->gc_read_bytes += ctx->physical_read_bytes - before_read;
	ctx->gc_write_bytes += ctx->physical_write_bytes - before_write;
	ctx->gc_count = 0;
	a->gc_allocation = 0;
	a->next_block = old_next;
	a->open_segment = old_open;
	a->next_segment_probe = error ? old_probe : victim;
	return error;
}


static int sv3_flush_window(struct sv3_dm *ctx)
{
	sv3_u8 committed = 0, index, count = ctx->batch_count;
	sv3_u8 gc_attempts = 0;
	bool needs_fua = false;
	int error = 0;

	if (!count)
		return 0;
	sv3_order_window(ctx);
	for (index = 0; index < count; ++index)
		if (ctx->batch[index].bio->bi_opf & REQ_FUA)
			needs_fua = true;
	while (committed < count) {
		sv3_u8 succeeded = 0;

		error = sv3_engine_write_window(&ctx->engine,
				ctx->planned + committed,
				count - committed, &succeeded);
		committed += succeeded;
		if (!error)
			continue;
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
		error = blkdev_issue_flush(ctx->backing->bdev);
	if (error && needs_fua)
		sv3_fail(ctx, error);
	for (index = 0; index < count; ++index) {
		struct bio *bio = ctx->batch[ctx->planned_to_batch[index]].bio;

		if (index < committed && !ctx->failed) {
			ctx->logical_write_bytes += SV3_BLOCK_BYTES;
			ctx->compressed_pages++;
			sv3_complete(bio, 0);
		} else {
			sv3_complete(bio, error ? error : -EIO);
		}
	}
	ctx->windows++;
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
			error = sv3_flush_window(ctx);
			if (error)
				return error;
			break;
		}
	if (ctx->batch_count == ctx->max_window) {
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
	if (length <= 0) {
		error = sv3_flush_window(ctx);
		if (error)
			return error;
		error = sv3_raw_write(ctx, bio, logical);
		if (!error && (bio->bi_opf & REQ_FUA))
			error = blkdev_issue_flush(ctx->backing->bdev);
		if (error)
			sv3_fail(ctx, error);
		sv3_complete(bio, error);
		return 0;
	}

	ctx->batch[ctx->batch_count] = (struct sv3_pending_bio) {
		.bio = bio,
		.logical = logical,
		.length = (sv3_u16)length,
	};
	ctx->batch_count++;
	/* FUA enforces an immediate drained window and is acknowledged only
	 * after sv3_flush_window() issues the matching lower cache flush. */
	if (bio->bi_opf & REQ_FUA)
		sv3_flush_window(ctx);
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
	/* All nonwrites, preflushes and barriers must drain older writes. */
	if (op != REQ_OP_WRITE || (bio->bi_opf & REQ_PREFLUSH)) {
		error = sv3_flush_window(ctx);
		if (error) {
			sv3_complete(bio, error);
			return;
		}
	}
	if (bio->bi_opf & REQ_PREFLUSH) {
		error = blkdev_issue_flush(ctx->backing->bdev);
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
	case REQ_OP_FLUSH:
		error = blkdev_issue_flush(ctx->backing->bdev);
		if (error)
			sv3_fail(ctx, error);
		break;
	default:
		error = -EOPNOTSUPP;
		break;
	}
	if (error && error != -EOPNOTSUPP)
		sv3_fail(ctx, error);
	sv3_complete(bio, error);
}

static void sv3_worker(struct work_struct *work)
{
	struct sv3_dm *ctx = container_of(work, struct sv3_dm, worker);
	LIST_HEAD(local);
	struct sv3_bio_ref *entry, *next;
	unsigned long flags;
	unsigned int remaining = SV3_WORK_QUANTUM_BIOS;

	{
		spin_lock_irqsave(&ctx->queue_lock, flags);
		list_splice_init(&ctx->incoming, &local);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
		list_for_each_entry_safe(entry, next, &local, list) {
			list_del_init(&entry->list);
			sv3_process(ctx, entry->bio);
			if (!--remaining)
				break;
		}
		/* No timer to wait for more records: seal what is available. */
		if (ctx->batch_count)
			sv3_flush_window(ctx);
		/*
		 * Unprocessed older entries MUST precede newly admitted BIOs.
		 * Requeue under the same lock as admission and suspend. Every
		 * pending write batch is completed before the work item yields.
		 */
		spin_lock_irqsave(&ctx->queue_lock, flags);
		if (!list_empty(&local))
			list_splice_init(&local, &ctx->incoming);
		if (!list_empty(&ctx->incoming))
			queue_work(ctx->workqueue, &ctx->worker);
		spin_unlock_irqrestore(&ctx->queue_lock, flags);
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
	} else if (bio_op(bio) != REQ_OP_FLUSH) {
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
	queue_work(ctx->workqueue, &ctx->worker);
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
	flush_workqueue(ctx->workqueue);
	/* Every admitted BIO had already been queued under the same lock. */
	if (!ctx->failed) {
		int error = blkdev_issue_flush(ctx->backing->bdev);

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
		flush_workqueue(ctx->workqueue);
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
	vfree(ctx->input_page);
	vfree(ctx->read_page);
	vfree(ctx->read_compressed);
	vfree(ctx->engine.write_scratch);
	vfree(ctx->engine.read_scratch);
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
	u32 budget = 0, window = SV3_MAX_RECORDS;
	int error;

	if (argc < 1 || argc > 3 || ti->len % SV3_SECTORS) {
		ti->error = "Usage: <dedicated backing> [max_read_blocks 0..3] [window 1..64]; 4K aligned";
		return -EINVAL;
	}
	if (argc > 1 && (kstrtou32(argv[1], 10, &budget) || budget > 3))
		return -EINVAL;
	if (argc > 2 && (kstrtou32(argv[2], 10, &window) ||
			 window < 1 || window > SV3_MAX_RECORDS))
		return -EINVAL;
	ctx = kzalloc(sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;
	ti->private = ctx;
	ctx->target = ti;
	ctx->max_window = (sv3_u8)window;
	ctx->engine.max_read_blocks_per_record = (sv3_u8)budget;
	spin_lock_init(&ctx->queue_lock);
	INIT_LIST_HEAD(&ctx->incoming);
	INIT_WORK(&ctx->worker, sv3_worker);

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
	ctx->maps = kvcalloc(logical, sizeof(*ctx->maps), GFP_KERNEL);
	ctx->live_records = kvcalloc(physical, sizeof(*ctx->live_records), GFP_KERNEL);
	ctx->extent_classes = kvcalloc(physical, sizeof(*ctx->extent_classes), GFP_KERNEL);
	ctx->discard_epoch = kvcalloc(physical, sizeof(*ctx->discard_epoch), GFP_KERNEL);
	ctx->discard_count = kvcalloc(physical, sizeof(*ctx->discard_count), GFP_KERNEL);
	if (!ctx->maps || !ctx->live_records || !ctx->extent_classes ||
	    !ctx->discard_epoch || !ctx->discard_count) {
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
	/* Never reuse a partially-live segment; full live relocation is gated. */
	ctx->authority.reuse_dead_segments = 1;
	ctx->batch_bytes = vzalloc(SV3_BATCH_BYTES);
	ctx->gc_bytes_store = vzalloc(SV3_BATCH_BYTES);
	ctx->input_page = vzalloc(SV3_BLOCK_BYTES);
	ctx->read_page = vzalloc(SV3_BLOCK_BYTES);
	ctx->read_compressed = vzalloc(SV3_BLOCK_BYTES);
	ctx->engine.write_scratch = vzalloc(SV3_MAX_EXTENT_BYTES);
	ctx->engine.read_scratch = vzalloc(SV3_MAX_EXTENT_BYTES);
	ctx->lz4_workmem = kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!ctx->batch_bytes || !ctx->gc_bytes_store ||
	    !ctx->gc_scores || !ctx->input_page ||
	    !ctx->read_page || !ctx->read_compressed ||
	    !ctx->engine.write_scratch || !ctx->engine.read_scratch ||
	    !ctx->lz4_workmem) {
		error = -ENOMEM;
		goto fail;
	}
	ctx->engine.authority = &ctx->authority;
	ctx->engine.io.opaque = ctx;
	ctx->engine.io.write_extent = sv3_lower_write;
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
		       "compressed=%llu raw=%llu discarded=%llu "
		       "windows=%llu reordered=%llu cursor=%u reserve=%u "
		       "gc_victims=%llu gc_pages=%llu gc_read=%llu gc_write=%llu "
		       "dead_segment_reuses=%u write_verify_blocks=%u failed=%u error=%d",
		       SV3_ALPHA_VERSION, ctx->logical_write_bytes,
		       ctx->logical_read_bytes, ctx->physical_write_bytes,
		       ctx->physical_write_reqs, ctx->physical_read_bytes,
		       ctx->physical_read_reqs, ctx->compressed_pages,
		       ctx->raw_pages, ctx->discard_pages, ctx->windows,
		       ctx->reordered_records, ctx->authority.next_block,
		       ctx->authority.reserve_blocks,
		       ctx->gc_victims, ctx->gc_pages,
		       ctx->gc_read_bytes, ctx->gc_write_bytes,
		       ctx->authority.recycled_dead_segments,
		       ctx->engine.write_verify_read_blocks,
		       ctx->failed, ctx->last_error);
		break;
	case STATUSTYPE_TABLE:
		DMEMIT("%s %u %u", ctx->backing->name,
		       ctx->engine.max_read_blocks_per_record, ctx->max_window);
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
