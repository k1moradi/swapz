// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz.c - volatile LZ4-compressed swap target for slow block devices.
 *
 * V1 goals:
 *  - dedicated block-device backing only;
 *  - serialize I/O through one reclaim-capable worker;
 *  - pack several LZ4-compressed 4 KiB logical pages into 4 KiB writes;
 *  - append sequentially inside large arenas and rotate arenas to spread LBAs;
 *  - keep all mappings in RAM; no persistent metadata or recovery format;
 *  - consume upper discard notifications even when the backing device cannot
 *    discard; lower discard is an optional optimization with fail-open fallback.
 *
 * This is experimental software. Hibernation/resume is intentionally unsupported.
 */

#define DM_MSG_PREFIX "swapz"

#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/device-mapper.h>
#include <linux/dm-io.h>
#include <linux/highmem.h>
#include <linux/ioprio.h>
#include <linux/lz4.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/vmalloc.h>
#include <linux/workqueue.h>
#include <linux/delay.h>

#if PAGE_SIZE != 4096
#error "swapz V1 currently requires 4 KiB PAGE_SIZE"
#endif

#define SWAPZ_VERSION_MAJOR 0
#define SWAPZ_VERSION_MINOR 1
#define SWAPZ_VERSION_PATCH 0

#define SWAPZ_BLOCK_BYTES PAGE_SIZE
#define SWAPZ_BLOCK_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)
#define SWAPZ_MAX_PACKED_RECORDS 8U
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U /* 'SPWZ' little-endian on disk */
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_EMPTY_BLOCK U32_MAX
#define SWAPZ_ARENA_ALIGNMENT_BLOCKS 256U /* 1 MiB at 4 KiB/block. */
#define SWAPZ_ARENA_SLACK_DIVISOR 4U     /* 25% worst-case raw slack. */
#define SWAPZ_MIN_ARENA_SLACK_BLOCKS SWAPZ_ARENA_ALIGNMENT_BLOCKS
#define SWAPZ_PACK_WAIT_MIN_US 500U
#define SWAPZ_PACK_WAIT_MAX_US 1000U
#define SWAPZ_MIN_COMPRESS_SAVING 512U

#define SWAPZ_MAP_VALID      BIT(0)
#define SWAPZ_MAP_COMPRESSED BIT(1)

struct swapz_record_disk {
	__le32 logical_page;
	__le16 offset;
	__le16 length;
} __packed;

struct swapz_container_disk {
	__le32 magic;
	__le16 version;
	__le16 record_count;
	struct swapz_record_disk records[SWAPZ_MAX_PACKED_RECORDS];
	u8 payload[];
} __packed;

#define SWAPZ_CONTAINER_HEADER_BYTES ((unsigned int)sizeof(struct swapz_container_disk))
#define SWAPZ_MAX_COMPRESSED_BYTES \
	(SWAPZ_BLOCK_BYTES - SWAPZ_CONTAINER_HEADER_BYTES - SWAPZ_MIN_COMPRESS_SAVING)

struct swapz_mapping {
	u32 physical_block;
	u16 stored_length;
	u8 record_index;
	u8 flags;
};
static_assert(sizeof(struct swapz_mapping) == 8);

struct swapz_per_bio {
	struct list_head list;
	struct bio *bio;
};

struct swapz_pending_record {
	struct bio *bio;
	u32 logical_page;
	u16 stored_length;
	u8 record_index;
};

struct swapz_stats {
	u64 logical_read_bytes;
	u64 logical_write_bytes;
	u64 physical_read_bytes;
	u64 physical_write_bytes;
	u64 compressed_payload_bytes;
	u64 compressed_pages;
	u64 raw_pages;
	u64 upper_discards;
	u64 arena_rotations;
	u64 compaction_pages;
	u64 compaction_read_bytes;
	u64 compaction_write_bytes;
	u64 lower_discard_bytes;
	u64 lower_discard_failures;
	u64 io_errors;
};

struct swapz_context {
	struct dm_target *target;
	struct dm_dev *backing;
	struct dm_io_client *io_client;
	struct workqueue_struct *workqueue;
	struct work_struct io_work;

	spinlock_t queue_lock;
	struct list_head queued_bios;
	bool accepting_io;
	bool failed;

	struct swapz_mapping *mappings;
	u32 logical_pages;

	u32 physical_blocks;
	u32 minimum_arena_blocks;
	u32 arena_blocks;
	u32 arena_count;
	u32 current_arena;
	u32 arena_write_block;
	u32 *arena_high_water;
	u32 *arena_cycles;

	bool lower_discard_enabled;

	void *input_buffer;
	void *io_buffer;
	void *compressed_buffer;
	void *pack_buffer;
	void *lz4_workmem;

	unsigned int pack_payload_end;
	unsigned int pack_record_count;
	struct swapz_pending_record pending[SWAPZ_MAX_PACKED_RECORDS];

	struct swapz_stats stats;
};

static inline bool swapz_mapping_valid(const struct swapz_mapping *mapping)
{
	return mapping->flags & SWAPZ_MAP_VALID;
}

static inline u32 swapz_mapping_arena(const struct swapz_context *context,
				      const struct swapz_mapping *mapping)
{
	return mapping->physical_block / context->arena_blocks;
}

static inline sector_t swapz_physical_sector(u32 physical_block)
{
	return (sector_t)physical_block * SWAPZ_BLOCK_SECTORS;
}

static void swapz_set_failed(struct swapz_context *context, int error)
{
	if (!context->failed)
		DMERR("backing I/O failed (%d); target is now failed", error);
	context->failed = true;
	context->stats.io_errors++;
}

static int swapz_backing_io(struct swapz_context *context, enum req_op operation,
			    u32 physical_block, void *buffer)
{
	struct dm_io_region region = {
		.bdev = context->backing->bdev,
		.sector = swapz_physical_sector(physical_block),
		.count = SWAPZ_BLOCK_SECTORS,
	};
	struct dm_io_request request = {
		.bi_opf = operation,
		.mem = {
			.type = DM_IO_KMEM,
			.offset = 0,
			.ptr.addr = buffer,
		},
		.notify = {
			.fn = NULL,
			.context = NULL,
		},
		.client = context->io_client,
	};
	unsigned long error_bits = 0;
	int error;

	error = dm_io(&request, 1, &region, &error_bits, IOPRIO_DEFAULT);
	if (error || error_bits) {
		if (!error)
			error = -EIO;
		swapz_set_failed(context, error);
		return error;
	}

	if (operation == REQ_OP_READ)
		context->stats.physical_read_bytes += SWAPZ_BLOCK_BYTES;
	else if (operation == REQ_OP_WRITE)
		context->stats.physical_write_bytes += SWAPZ_BLOCK_BYTES;

	return 0;
}

static int swapz_read_block(struct swapz_context *context, u32 physical_block,
			    void *buffer)
{
	return swapz_backing_io(context, REQ_OP_READ, physical_block, buffer);
}

static int swapz_write_block(struct swapz_context *context, u32 physical_block,
			     void *buffer)
{
	return swapz_backing_io(context, REQ_OP_WRITE, physical_block, buffer);
}

static void swapz_copy_from_bio(struct bio *bio, void *destination)
{
	struct bio_vec vector;
	struct bvec_iter iterator;
	u8 *output = destination;

	bio_for_each_segment(vector, bio, iterator) {
		void *mapped = kmap_local_page(vector.bv_page);

		memcpy(output, mapped + vector.bv_offset, vector.bv_len);
		output += vector.bv_len;
		kunmap_local(mapped);
	}
}

static void swapz_copy_to_bio(struct bio *bio, const void *source)
{
	struct bio_vec vector;
	struct bvec_iter iterator;
	const u8 *input = source;

	bio_for_each_segment(vector, bio, iterator) {
		void *mapped = kmap_local_page(vector.bv_page);

		memcpy(mapped + vector.bv_offset, input, vector.bv_len);
		input += vector.bv_len;
		kunmap_local(mapped);
	}
}

static void swapz_complete_bio(struct bio *bio, int error)
{
	if (error)
		bio->bi_status = errno_to_blk_status(error);
	bio_endio(bio);
}

static void swapz_invalidate_mapping(struct swapz_context *context,
				     u32 logical_page)
{
	struct swapz_mapping *mapping = &context->mappings[logical_page];

	mapping->physical_block = SWAPZ_EMPTY_BLOCK;
	mapping->stored_length = 0;
	mapping->record_index = 0;
	mapping->flags = 0;
}

static void swapz_install_mapping(struct swapz_context *context, u32 logical_page,
				  u32 physical_block, u16 stored_length,
				  u8 record_index, u8 flags)
{
	struct swapz_mapping *mapping = &context->mappings[logical_page];

	mapping->physical_block = physical_block;
	mapping->stored_length = stored_length;
	mapping->record_index = record_index;
	mapping->flags = flags | SWAPZ_MAP_VALID;
}

static u32 swapz_current_physical_block(const struct swapz_context *context)
{
	return context->current_arena * context->arena_blocks +
	       context->arena_write_block;
}

static bool swapz_current_arena_has_block(const struct swapz_context *context)
{
	return context->arena_write_block < context->arena_blocks;
}

static void swapz_reset_pack(struct swapz_context *context)
{
	memset(context->pack_buffer, 0, SWAPZ_CONTAINER_HEADER_BYTES);
	context->pack_payload_end = SWAPZ_CONTAINER_HEADER_BYTES;
	context->pack_record_count = 0;
}

static int swapz_rotate_arena(struct swapz_context *context);

static int swapz_ensure_physical_block(struct swapz_context *context,
				       bool allow_rotation)
{
	if (swapz_current_arena_has_block(context))
		return 0;
	if (!allow_rotation)
		return -ENOSPC;
	return swapz_rotate_arena(context);
}

static void swapz_note_block_written(struct swapz_context *context)
{
	context->arena_write_block++;
	if (context->arena_write_block > context->arena_high_water[context->current_arena])
		context->arena_high_water[context->current_arena] = context->arena_write_block;
}

static int swapz_flush_pack(struct swapz_context *context, bool compaction,
			    bool allow_rotation)
{
	struct swapz_container_disk *container = context->pack_buffer;
	u32 physical_block;
	unsigned int record_index;
	int error;

	if (!context->pack_record_count)
		return 0;

	error = swapz_ensure_physical_block(context, allow_rotation);
	if (error)
		goto fail_pending;

	container->magic = cpu_to_le32(SWAPZ_CONTAINER_MAGIC);
	container->version = cpu_to_le16(SWAPZ_CONTAINER_VERSION);
	container->record_count = cpu_to_le16(context->pack_record_count);
	physical_block = swapz_current_physical_block(context);

	error = swapz_write_block(context, physical_block, context->pack_buffer);
	if (error)
		goto fail_pending;

	if (compaction)
		context->stats.compaction_write_bytes += SWAPZ_BLOCK_BYTES;

	for (record_index = 0; record_index < context->pack_record_count; ++record_index) {
		struct swapz_pending_record *pending = &context->pending[record_index];

		swapz_install_mapping(context, pending->logical_page, physical_block,
				      pending->stored_length, pending->record_index,
				      SWAPZ_MAP_COMPRESSED);
		if (pending->bio)
			swapz_complete_bio(pending->bio, 0);
	}

	swapz_note_block_written(context);
	swapz_reset_pack(context);
	return 0;

fail_pending:
	for (record_index = 0; record_index < context->pack_record_count; ++record_index) {
		if (context->pending[record_index].bio)
			swapz_complete_bio(context->pending[record_index].bio, error);
	}
	swapz_reset_pack(context);
	return error;
}

static bool swapz_pack_can_fit(const struct swapz_context *context,
			       unsigned int compressed_length)
{
	if (context->pack_record_count >= SWAPZ_MAX_PACKED_RECORDS)
		return false;
	return compressed_length <= SWAPZ_BLOCK_BYTES - context->pack_payload_end;
}

static int swapz_add_compressed_record(struct swapz_context *context,
				       struct bio *bio, u32 logical_page,
				       const void *compressed, u16 compressed_length,
				       bool compaction, bool allow_rotation)
{
	int error;
	struct swapz_container_disk *container = context->pack_buffer;
	struct swapz_record_disk *record;
	struct swapz_pending_record *pending;
	unsigned int record_index;

	/* Rotate before a new pack starts.  A non-empty pack must always have a
	 * physical block reserved in the current arena, otherwise rotation would
	 * need a second pack buffer while compacting. */
	if (!context->pack_record_count) {
		error = swapz_ensure_physical_block(context, allow_rotation);
		if (error)
			return error;
	}

	if (!swapz_pack_can_fit(context, compressed_length)) {
		error = swapz_flush_pack(context, compaction, allow_rotation);
		if (error)
			return error;
		error = swapz_ensure_physical_block(context, allow_rotation);
		if (error)
			return error;
	}

	if (!swapz_pack_can_fit(context, compressed_length))
		return -E2BIG;

	record_index = context->pack_record_count;
	record = &container->records[record_index];
	record->logical_page = cpu_to_le32(logical_page);
	record->offset = cpu_to_le16(context->pack_payload_end);
	record->length = cpu_to_le16(compressed_length);
	memcpy((u8 *)context->pack_buffer + context->pack_payload_end,
	       compressed, compressed_length);

	pending = &context->pending[record_index];
	pending->bio = bio;
	pending->logical_page = logical_page;
	pending->stored_length = compressed_length;
	pending->record_index = record_index;

	context->pack_payload_end += compressed_length;
	context->pack_record_count++;
	context->stats.compressed_payload_bytes += compressed_length;
	context->stats.compressed_pages++;

	/* A full pack is flushed by the worker/next operation.  Keeping the
	 * current bio pending avoids ambiguous ownership on a synchronous lower
	 * write failure. */
	return 0;
}

static int swapz_write_raw_page(struct swapz_context *context, struct bio *bio,
				u32 logical_page, const void *page_data,
				bool compaction, bool allow_rotation)
{
	u32 physical_block;
	int error;

	error = swapz_flush_pack(context, compaction, allow_rotation);
	if (error)
		return error;

	error = swapz_ensure_physical_block(context, allow_rotation);
	if (error)
		return error;

	physical_block = swapz_current_physical_block(context);
	error = swapz_write_block(context, physical_block, (void *)page_data);
	if (error)
		return error;

	if (compaction)
		context->stats.compaction_write_bytes += SWAPZ_BLOCK_BYTES;

	swapz_install_mapping(context, logical_page, physical_block, SWAPZ_BLOCK_BYTES,
			      0, 0);
	context->stats.raw_pages++;
	swapz_note_block_written(context);
	if (bio)
		swapz_complete_bio(bio, 0);
	return 0;
}

static int swapz_store_page(struct swapz_context *context, struct bio *bio,
			    u32 logical_page, const void *page_data,
			    bool compaction, bool allow_rotation)
{
	int compressed_length;

	compressed_length = LZ4_compress_fast(page_data, context->compressed_buffer,
					      SWAPZ_BLOCK_BYTES,
					      SWAPZ_MAX_COMPRESSED_BYTES,
					      1, context->lz4_workmem);
	if (compressed_length > 0) {
		return swapz_add_compressed_record(context, bio, logical_page,
					   context->compressed_buffer,
					   compressed_length, compaction,
					   allow_rotation);
	}

	return swapz_write_raw_page(context, bio, logical_page, page_data,
				    compaction, allow_rotation);
}

static int swapz_read_mapping(struct swapz_context *context, u32 logical_page,
			      void *destination, bool compaction)
{
	const struct swapz_mapping mapping = context->mappings[logical_page];
	int error;

	if (!swapz_mapping_valid(&mapping)) {
		memset(destination, 0, SWAPZ_BLOCK_BYTES);
		return 0;
	}

	error = swapz_read_block(context, mapping.physical_block, context->io_buffer);
	if (error)
		return error;

	if (compaction)
		context->stats.compaction_read_bytes += SWAPZ_BLOCK_BYTES;

	if (!(mapping.flags & SWAPZ_MAP_COMPRESSED)) {
		memcpy(destination, context->io_buffer, SWAPZ_BLOCK_BYTES);
		return 0;
	}

	{
		const struct swapz_container_disk *container = context->io_buffer;
		const struct swapz_record_disk *record;
		u16 offset;
		u16 length;
		int decompressed;

		if (le32_to_cpu(container->magic) != SWAPZ_CONTAINER_MAGIC ||
		    le16_to_cpu(container->version) != SWAPZ_CONTAINER_VERSION ||
		    mapping.record_index >= le16_to_cpu(container->record_count) ||
		    mapping.record_index >= SWAPZ_MAX_PACKED_RECORDS)
			return -EIO;

		record = &container->records[mapping.record_index];
		offset = le16_to_cpu(record->offset);
		length = le16_to_cpu(record->length);
		if (le32_to_cpu(record->logical_page) != logical_page ||
		    length != mapping.stored_length ||
		    offset < SWAPZ_CONTAINER_HEADER_BYTES ||
		    offset + length > SWAPZ_BLOCK_BYTES)
			return -EIO;

		decompressed = LZ4_decompress_safe((const char *)context->io_buffer + offset,
						   destination, length,
						   SWAPZ_BLOCK_BYTES);
		if (decompressed != SWAPZ_BLOCK_BYTES)
			return -EIO;
	}

	return 0;
}

static void swapz_try_discard_arena(struct swapz_context *context, u32 arena)
{
	sector_t sectors;
	sector_t start;
	int error;
	u32 high_water;

	if (!context->lower_discard_enabled)
		return;

	high_water = context->arena_high_water[arena];
	if (!high_water)
		return;

	start = swapz_physical_sector(arena * context->arena_blocks);
	sectors = (sector_t)high_water * SWAPZ_BLOCK_SECTORS;
	error = blkdev_issue_discard(context->backing->bdev, start, sectors, GFP_NOIO);
	if (error) {
		context->stats.lower_discard_failures++;
		context->lower_discard_enabled = false;
		DMWARN("lower discard failed (%d); disabling it for this target", error);
		return;
	}

	context->stats.lower_discard_bytes += (u64)sectors << SECTOR_SHIFT;
}

static int swapz_rotate_arena(struct swapz_context *context)
{
	u32 old_arena = context->current_arena;
	u32 next_arena = (old_arena + 1) % context->arena_count;
	u32 logical_page;
	int error;

	if (context->pack_record_count)
		return -EDEADLK;

	swapz_try_discard_arena(context, next_arena);
	context->current_arena = next_arena;
	context->arena_write_block = 0;
	context->arena_high_water[next_arena] = 0;
	context->arena_cycles[next_arena]++;
	context->stats.arena_rotations++;

	/*
	 * Invariant: after every successful rotation all live mappings reside in
	 * the current arena.  Therefore next_arena contains no live data when we
	 * select it.  Re-copy each live logical page into the new arena.  This is
	 * intentionally simple for V1; physical-order compaction is a later
	 * optimization if benchmarks justify the complexity.
	 */
	for (logical_page = 0; logical_page < context->logical_pages; ++logical_page) {
		struct swapz_mapping old_mapping = context->mappings[logical_page];

		if (!swapz_mapping_valid(&old_mapping))
			continue;
		if (swapz_mapping_arena(context, &old_mapping) != old_arena) {
			DMERR("mapping invariant broken at logical page %u", logical_page);
			swapz_set_failed(context, -EUCLEAN);
			return -EUCLEAN;
		}

		error = swapz_read_mapping(context, logical_page, context->input_buffer, true);
		if (error) {
			swapz_set_failed(context, error);
			return error;
		}

		error = swapz_store_page(context, NULL, logical_page,
					 context->input_buffer, true, false);
		if (error) {
			swapz_set_failed(context, error);
			return error;
		}
		context->stats.compaction_pages++;
	}

	error = swapz_flush_pack(context, true, false);
	if (error) {
		swapz_set_failed(context, error);
		return error;
	}

	return 0;
}

static int swapz_process_write(struct swapz_context *context, struct bio *bio)
{
	u32 logical_page = (u32)(bio->bi_iter.bi_sector / SWAPZ_BLOCK_SECTORS);
	int error;

	if (logical_page >= context->logical_pages)
		return -ERANGE;

	swapz_copy_from_bio(bio, context->input_buffer);
	context->stats.logical_write_bytes += SWAPZ_BLOCK_BYTES;
	error = swapz_store_page(context, bio, logical_page, context->input_buffer,
				 false, true);
	return error;
}

static int swapz_process_read(struct swapz_context *context, struct bio *bio)
{
	u32 logical_page = (u32)(bio->bi_iter.bi_sector / SWAPZ_BLOCK_SECTORS);
	int error;

	if (logical_page >= context->logical_pages)
		return -ERANGE;

	error = swapz_flush_pack(context, false, true);
	if (error)
		return error;

	error = swapz_read_mapping(context, logical_page, context->input_buffer, false);
	if (error)
		return error;

	swapz_copy_to_bio(bio, context->input_buffer);
	context->stats.logical_read_bytes += SWAPZ_BLOCK_BYTES;
	swapz_complete_bio(bio, 0);
	return 0;
}

static int swapz_process_discard(struct swapz_context *context, struct bio *bio)
{
	sector_t sector = bio->bi_iter.bi_sector;
	sector_t remaining = bio_sectors(bio);
	int error;

	error = swapz_flush_pack(context, false, true);
	if (error)
		return error;

	while (remaining) {
		u32 logical_page;

		if (sector % SWAPZ_BLOCK_SECTORS || remaining < SWAPZ_BLOCK_SECTORS)
			return -EINVAL;
		logical_page = (u32)(sector / SWAPZ_BLOCK_SECTORS);
		if (logical_page >= context->logical_pages)
			return -ERANGE;
		swapz_invalidate_mapping(context, logical_page);
		sector += SWAPZ_BLOCK_SECTORS;
		remaining -= SWAPZ_BLOCK_SECTORS;
		context->stats.upper_discards++;
	}

	swapz_complete_bio(bio, 0);
	return 0;
}

static void swapz_process_flush(struct swapz_context *context, struct bio *bio)
{
	int error;

	error = swapz_flush_pack(context, false, true);
	if (!error)
		error = blkdev_issue_flush(context->backing->bdev);
	if (error)
		swapz_set_failed(context, error);
	swapz_complete_bio(bio, error);
}

static void swapz_process_bio(struct swapz_context *context, struct bio *bio)
{
	int error = 0;

	if (unlikely(context->failed)) {
		swapz_complete_bio(bio, -EIO);
		return;
	}

	if (bio->bi_opf & REQ_PREFLUSH) {
		error = swapz_flush_pack(context, false, true);
		if (!error)
			error = blkdev_issue_flush(context->backing->bdev);
		if (error) {
			swapz_set_failed(context, error);
			swapz_complete_bio(bio, error);
			return;
		}

		/*
		 * Linux 7.0 represents an empty flush as a zero-length
		 * REQ_OP_WRITE | REQ_PREFLUSH bio.  The preflush above is the whole
		 * operation; do not fall through to the normal 4 KiB write path.
		 */
		if (bio_op(bio) == REQ_OP_WRITE && !bio_sectors(bio)) {
			swapz_complete_bio(bio, 0);
			return;
		}
	}

	switch (bio_op(bio)) {
	case REQ_OP_READ:
		error = swapz_process_read(context, bio);
		break;
	case REQ_OP_WRITE:
		error = swapz_process_write(context, bio);
		break;
	case REQ_OP_DISCARD:
		error = swapz_process_discard(context, bio);
		break;
	case REQ_OP_FLUSH:
		swapz_process_flush(context, bio);
		return;
	default:
		error = -EOPNOTSUPP;
		break;
	}

	/* Packed writes are completed later when their containing block is
	 * flushed.  Any error returned here happened before the current bio was
	 * handed to a lower I/O, so this function still owns the bio. */
	if (error)
		swapz_complete_bio(bio, error);
}

static bool swapz_queue_is_empty(struct swapz_context *context)
{
	bool empty;

	spin_lock_irq(&context->queue_lock);
	empty = list_empty(&context->queued_bios);
	spin_unlock_irq(&context->queue_lock);
	return empty;
}

static void swapz_io_worker(struct work_struct *work)
{
	struct swapz_context *context = container_of(work, struct swapz_context, io_work);
	LIST_HEAD(local_bios);

	for (;;) {
		struct swapz_per_bio *entry;
		struct swapz_per_bio *next;

		spin_lock_irq(&context->queue_lock);
		list_splice_init(&context->queued_bios, &local_bios);
		spin_unlock_irq(&context->queue_lock);

		if (!list_empty(&local_bios)) {
			list_for_each_entry_safe(entry, next, &local_bios, list) {
				list_del_init(&entry->list);
				swapz_process_bio(context, entry->bio);
			}
			continue;
		}

		/*
		 * Give concurrent swap-out submissions a very small chance to join
		 * the current 4 KiB pack.  This targets slow serialized media: the
		 * added sub-millisecond latency is small compared with device latency,
		 * while packing two or more pages is what reduces host write bytes.
		 */
		if (context->pack_record_count && !context->failed) {
			usleep_range(SWAPZ_PACK_WAIT_MIN_US, SWAPZ_PACK_WAIT_MAX_US);
			if (!swapz_queue_is_empty(context))
				continue;
			if (swapz_flush_pack(context, false, true))
				context->failed = true;
			continue;
		}

		break;
	}
}

static int swapz_map(struct dm_target *target, struct bio *bio)
{
	struct swapz_context *context = target->private;
	struct swapz_per_bio *entry;
	unsigned long flags;

	if (unlikely(!READ_ONCE(context->accepting_io) || READ_ONCE(context->failed)))
		return DM_MAPIO_KILL;

	if (bio_op(bio) == REQ_OP_READ &&
	    (bio->bi_iter.bi_sector % SWAPZ_BLOCK_SECTORS ||
	     bio_sectors(bio) != SWAPZ_BLOCK_SECTORS))
		return DM_MAPIO_KILL;

	if (bio_op(bio) == REQ_OP_WRITE) {
		const bool empty_preflush =
			!bio_sectors(bio) && (bio->bi_opf & REQ_PREFLUSH);

		if (!empty_preflush &&
		    (bio->bi_iter.bi_sector % SWAPZ_BLOCK_SECTORS ||
		     bio_sectors(bio) != SWAPZ_BLOCK_SECTORS))
			return DM_MAPIO_KILL;
	}

	entry = dm_per_bio_data(bio, sizeof(*entry));
	INIT_LIST_HEAD(&entry->list);
	entry->bio = bio;

	spin_lock_irqsave(&context->queue_lock, flags);
	list_add_tail(&entry->list, &context->queued_bios);
	spin_unlock_irqrestore(&context->queue_lock, flags);
	queue_work(context->workqueue, &context->io_work);
	return DM_MAPIO_SUBMITTED;
}

static void swapz_presuspend(struct dm_target *target)
{
	struct swapz_context *context = target->private;

	WRITE_ONCE(context->accepting_io, false);
	flush_workqueue(context->workqueue);
}

static void swapz_resume(struct dm_target *target)
{
	struct swapz_context *context = target->private;

	if (!context->failed)
		WRITE_ONCE(context->accepting_io, true);
}

static int swapz_iterate_devices(struct dm_target *target,
				 iterate_devices_callout_fn function, void *data)
{
	struct swapz_context *context = target->private;

	return function(target, context->backing, 0,
			(sector_t)context->arena_count * context->arena_blocks *
			SWAPZ_BLOCK_SECTORS, data);
}

static void swapz_io_hints(struct dm_target *target, struct queue_limits *limits)
{
	limits->logical_block_size = SWAPZ_BLOCK_BYTES;
	limits->physical_block_size = max(limits->physical_block_size, SWAPZ_BLOCK_BYTES);
	limits->io_min = SWAPZ_BLOCK_BYTES;
	limits->discard_granularity = SWAPZ_BLOCK_BYTES;
	limits->max_hw_discard_sectors = UINT_MAX;
	limits->max_discard_sectors = UINT_MAX;
}

static void swapz_status(struct dm_target *target, status_type_t type,
			 unsigned int status_flags, char *result, unsigned int maxlen)
{
	struct swapz_context *context = target->private;
	u32 arena_cycle_min = U32_MAX;
	u32 arena_cycle_max = 0;
	u32 arena;
	unsigned int sz = 0;

	switch (type) {
	case STATUSTYPE_INFO:
		for (arena = 0; arena < context->arena_count; ++arena) {
			arena_cycle_min = min(arena_cycle_min, context->arena_cycles[arena]);
			arena_cycle_max = max(arena_cycle_max, context->arena_cycles[arena]);
		}
		if (arena_cycle_min == U32_MAX)
			arena_cycle_min = 0;

		DMEMIT("arena=%u/%u head_blocks=%u logical_write=%llu physical_write=%llu "
		       "logical_read=%llu physical_read=%llu compressed_payload=%llu "
		       "compressed_pages=%llu raw_pages=%llu upper_discards=%llu rotations=%llu "
		       "arena_cycle_min=%u arena_cycle_max=%u "
		       "gc_pages=%llu gc_read=%llu gc_write=%llu lower_discard=%s discard_bytes=%llu "
		       "discard_failures=%llu failed=%u",
		       context->current_arena, context->arena_count,
		       context->arena_write_block,
		       context->stats.logical_write_bytes,
		       context->stats.physical_write_bytes,
		       context->stats.logical_read_bytes,
		       context->stats.physical_read_bytes,
		       context->stats.compressed_payload_bytes,
		       context->stats.compressed_pages,
		       context->stats.raw_pages,
		       context->stats.upper_discards,
		       context->stats.arena_rotations,
		       arena_cycle_min,
		       arena_cycle_max,
		       context->stats.compaction_pages,
		       context->stats.compaction_read_bytes,
		       context->stats.compaction_write_bytes,
		       context->lower_discard_enabled ? "on" : "off",
		       context->stats.lower_discard_bytes,
		       context->stats.lower_discard_failures,
		       context->failed ? 1U : 0U);
		break;
	case STATUSTYPE_TABLE:
		DMEMIT("%s", context->backing->name);
		break;
	case STATUSTYPE_IMA:
		break;
	}
}

static void swapz_free_context(struct swapz_context *context)
{
	if (!context)
		return;
	if (context->workqueue) {
		flush_workqueue(context->workqueue);
		destroy_workqueue(context->workqueue);
	}
	if (context->io_client)
		dm_io_client_destroy(context->io_client);
	if (context->backing)
		dm_put_device(context->target, context->backing);
	if (context->input_buffer)
		free_page((unsigned long)context->input_buffer);
	if (context->io_buffer)
		free_page((unsigned long)context->io_buffer);
	if (context->compressed_buffer)
		free_page((unsigned long)context->compressed_buffer);
	if (context->pack_buffer)
		free_page((unsigned long)context->pack_buffer);
	kfree(context->lz4_workmem);
	vfree(context->mappings);
	kvfree(context->arena_high_water);
	kvfree(context->arena_cycles);
	kfree(context);
}

static void swapz_dtr(struct dm_target *target)
{
	struct swapz_context *context = target->private;

	if (!context)
		return;
	WRITE_ONCE(context->accepting_io, false);
	if (context->workqueue)
		flush_workqueue(context->workqueue);
	swapz_free_context(context);
}

static int swapz_ctr(struct dm_target *target, unsigned int argc, char **argv)
{
	struct swapz_context *context;
	sector_t physical_sectors;
	u64 physical_blocks64;
	u64 logical_pages64;
	u64 slack_blocks;
	u64 minimum_arena_blocks;
	u64 arena_count64;
	u64 arena_blocks64;
	u32 index;
	int error;

	if (argc != 1) {
		target->error = "Usage: <backing_block_device>";
		return -EINVAL;
	}
	if (target->len % SWAPZ_BLOCK_SECTORS) {
		target->error = "Logical size must be 4 KiB aligned";
		return -EINVAL;
	}

	context = kzalloc(sizeof(*context), GFP_KERNEL);
	if (!context) {
		target->error = "Cannot allocate context";
		return -ENOMEM;
	}
	context->target = target;
	target->private = context;

	error = dm_get_device(target, argv[0], dm_table_get_mode(target->table),
			      &context->backing);
	if (error) {
		target->error = "Cannot open backing device";
		goto fail;
	}
	if (bdev_is_zoned(context->backing->bdev)) {
		target->error = "Zoned backing devices are unsupported in V1";
		error = -EOPNOTSUPP;
		goto fail;
	}
	if (bdev_read_only(context->backing->bdev)) {
		target->error = "Backing device is read-only";
		error = -EROFS;
		goto fail;
	}
	if (bdev_logical_block_size(context->backing->bdev) > SWAPZ_BLOCK_BYTES ||
	    SWAPZ_BLOCK_BYTES % bdev_logical_block_size(context->backing->bdev)) {
		target->error = "Backing logical block size is incompatible with 4 KiB V1 blocks";
		error = -EINVAL;
		goto fail;
	}

	physical_sectors = bdev_nr_sectors(context->backing->bdev);
	physical_blocks64 = div_u64(physical_sectors, SWAPZ_BLOCK_SECTORS);
	logical_pages64 = div_u64(target->len, SWAPZ_BLOCK_SECTORS);
	if (!logical_pages64 || logical_pages64 > U32_MAX || physical_blocks64 > U32_MAX) {
		target->error = "V1 supports at most 16 TiB physical/logical space";
		error = -E2BIG;
		goto fail;
	}

	slack_blocks = max_t(u64, DIV_ROUND_UP_ULL(logical_pages64,
						      SWAPZ_ARENA_SLACK_DIVISOR),
			     SWAPZ_MIN_ARENA_SLACK_BLOCKS);
	minimum_arena_blocks = round_up(logical_pages64 + slack_blocks,
					SWAPZ_ARENA_ALIGNMENT_BLOCKS);
	arena_count64 = div_u64(physical_blocks64, minimum_arena_blocks);
	if (arena_count64 < 2) {
		target->error = "Backing device must be at least ~2.5x logical swap size in V1";
		error = -ENOSPC;
		goto fail;
	}
	if (arena_count64 > U32_MAX)
		arena_count64 = U32_MAX;
	arena_blocks64 = round_down(div_u64(physical_blocks64, arena_count64),
				    SWAPZ_ARENA_ALIGNMENT_BLOCKS);
	if (arena_blocks64 < minimum_arena_blocks || arena_blocks64 > U32_MAX) {
		target->error = "Cannot derive safe arena geometry";
		error = -EINVAL;
		goto fail;
	}

	context->logical_pages = (u32)logical_pages64;
	context->physical_blocks = (u32)physical_blocks64;
	context->minimum_arena_blocks = (u32)minimum_arena_blocks;
	context->arena_blocks = (u32)arena_blocks64;
	context->arena_count = (u32)arena_count64;
	context->current_arena = 0;
	context->arena_write_block = 0;

	context->mappings = vzalloc(array_size(context->logical_pages,
					       sizeof(*context->mappings)));
	context->arena_high_water = kvcalloc(context->arena_count,
					     sizeof(*context->arena_high_water), GFP_KERNEL);
	context->arena_cycles = kvcalloc(context->arena_count,
					 sizeof(*context->arena_cycles), GFP_KERNEL);
	if (!context->mappings || !context->arena_high_water || !context->arena_cycles) {
		target->error = "Cannot allocate mapping/arena metadata";
		error = -ENOMEM;
		goto fail;
	}
	for (index = 0; index < context->logical_pages; ++index)
		context->mappings[index].physical_block = SWAPZ_EMPTY_BLOCK;
	context->arena_cycles[0] = 1;

	context->input_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->io_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->compressed_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->pack_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->lz4_workmem = kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!context->input_buffer || !context->io_buffer ||
	    !context->compressed_buffer || !context->pack_buffer || !context->lz4_workmem) {
		target->error = "Cannot allocate preallocated I/O buffers";
		error = -ENOMEM;
		goto fail;
	}
	swapz_reset_pack(context);

	context->io_client = dm_io_client_create();
	if (IS_ERR(context->io_client)) {
		error = PTR_ERR(context->io_client);
		context->io_client = NULL;
		target->error = "Cannot create dm-io client";
		goto fail;
	}

	spin_lock_init(&context->queue_lock);
	INIT_LIST_HEAD(&context->queued_bios);
	INIT_WORK(&context->io_work, swapz_io_worker);
	context->workqueue = alloc_workqueue("swapz-%s",
					     WQ_MEM_RECLAIM | WQ_UNBOUND, 1,
					     dm_table_device_name(target->table));
	if (!context->workqueue) {
		target->error = "Cannot allocate reclaim-safe workqueue";
		error = -ENOMEM;
		goto fail;
	}

	context->lower_discard_enabled =
		bdev_max_discard_sectors(context->backing->bdev) != 0 &&
		bdev_discard_granularity(context->backing->bdev) != 0;
	context->accepting_io = true;

	target->per_io_data_size = sizeof(struct swapz_per_bio);
	target->num_flush_bios = 1;
	target->flush_supported = true;
	target->num_discard_bios = 1;
	target->discards_supported = true;
	target->limit_swap_bios = true;
	error = dm_set_target_max_io_len(target, SWAPZ_BLOCK_SECTORS);
	if (error) {
		target->error = "Cannot set 4 KiB maximum I/O size";
		goto fail;
	}

	DMINFO("logical=%u pages physical=%u blocks arenas=%u arena_blocks=%u lower_discard=%s",
	       context->logical_pages, context->physical_blocks,
	       context->arena_count, context->arena_blocks,
	       context->lower_discard_enabled ? "on" : "off");
	return 0;

fail:
	swapz_free_context(context);
	target->private = NULL;
	return error;
}

static struct target_type swapz_target = {
	.name = "swapz",
	.version = { SWAPZ_VERSION_MAJOR, SWAPZ_VERSION_MINOR, SWAPZ_VERSION_PATCH },
	.features = DM_TARGET_SINGLETON | DM_TARGET_ALWAYS_WRITEABLE,
	.module = THIS_MODULE,
	.ctr = swapz_ctr,
	.dtr = swapz_dtr,
	.map = swapz_map,
	.presuspend = swapz_presuspend,
	.resume = swapz_resume,
	.status = swapz_status,
	.iterate_devices = swapz_iterate_devices,
	.io_hints = swapz_io_hints,
};

static int __init swapz_init(void)
{
	return dm_register_target(&swapz_target);
}

static void __exit swapz_exit(void)
{
	dm_unregister_target(&swapz_target);
}

module_init(swapz_init);
module_exit(swapz_exit);

MODULE_AUTHOR("OpenAI / experimental swapz project");
MODULE_DESCRIPTION("Volatile LZ4-compressed log-structured swap device-mapper target");
MODULE_LICENSE("GPL");
MODULE_ALIAS("dm-swapz");
