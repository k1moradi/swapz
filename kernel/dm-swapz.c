// SPDX-License-Identifier: GPL-2.0-only
/*
 * dm-swapz.c - volatile LZ4-compressed swap target for slow block devices.
 *
 * V2 goals:
 *  - dedicated block-device backing only;
 *  - serialize I/O through one reclaim-capable worker;
 *  - pack several LZ4-compressed 4 KiB logical pages into 4 KiB writes;
 *  - append sequentially inside 1 MiB log segments and rotate across the device;
 *  - clean only live records from low-live victim segments instead of copying
 *    the whole live set;
 *  - keep all mappings/GC metadata in RAM; no persistent recovery format;
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
#error "swapz V2 currently requires 4 KiB PAGE_SIZE"
#endif

#define SWAPZ_VERSION_MAJOR 0
#define SWAPZ_VERSION_MINOR 2
#define SWAPZ_VERSION_PATCH 0

#define SWAPZ_BLOCK_BYTES PAGE_SIZE
#define SWAPZ_BLOCK_SECTORS (SWAPZ_BLOCK_BYTES >> SECTOR_SHIFT)
#define SWAPZ_MAX_PACKED_RECORDS 8U
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U /* 'SPWZ' little-endian on disk */
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_EMPTY_BLOCK U32_MAX
#define SWAPZ_SEGMENT_BLOCKS 256U        /* 1 MiB at 4 KiB/block. */
#define SWAPZ_GC_HEADROOM_BLOCKS 8U      /* Keep 32 KiB free after cleaning. */
#define SWAPZ_MIN_RESERVE_DIVISOR 4U     /* At least 25% physical GC reserve. */
#define SWAPZ_SEGMENT_FREE 0U
#define SWAPZ_SEGMENT_OPEN 1U
#define SWAPZ_SEGMENT_CLOSED 2U
#define SWAPZ_SEGMENT_CLEANING 3U
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
	u64 segment_switches;
	u64 gc_victims;
	u64 gc_scanned_mappings;
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
	u32 segment_count;
	u32 current_segment;
	u32 segment_write_block;
	u32 allocation_cursor;
	u32 gc_cursor;
	u32 free_segments;
	u32 *segment_high_water;
	u32 *segment_cycles;
	u16 *segment_live_blocks;
	u8 *segment_state;
	u8 *block_live_records;
	u32 *gc_logical_pages;
	u8 *gc_block_counts;

	bool lower_discard_enabled;

	/*
	 * Foreground writes must survive segment advance.  Segment GC uses
	 * input_buffer/compressed_buffer, so keep the current BIO payload and its
	 * compressed form in separate preallocated pages.
	 */
	void *write_buffer;
	void *write_compressed_buffer;

	/* Compaction/read scratch buffers. */
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

static inline u32 swapz_mapping_segment(const struct swapz_mapping *mapping)
{
	return mapping->physical_block / SWAPZ_SEGMENT_BLOCKS;
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

static void swapz_unaccount_mapping(struct swapz_context *context,
				    const struct swapz_mapping *mapping)
{
	u32 physical_block;
	u32 segment;

	if (!swapz_mapping_valid(mapping))
		return;

	physical_block = mapping->physical_block;
	segment = swapz_mapping_segment(mapping);
	if (WARN_ON_ONCE(physical_block >= context->physical_blocks ||
			 context->block_live_records[physical_block] == 0 ||
			 segment >= context->segment_count ||
			 context->segment_live_blocks[segment] == 0)) {
		swapz_set_failed(context, -EUCLEAN);
		return;
	}

	context->block_live_records[physical_block]--;
	if (!context->block_live_records[physical_block])
		context->segment_live_blocks[segment]--;
}

static void swapz_invalidate_mapping(struct swapz_context *context,
				     u32 logical_page)
{
	struct swapz_mapping *mapping = &context->mappings[logical_page];

	swapz_unaccount_mapping(context, mapping);
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
	u32 segment = physical_block / SWAPZ_SEGMENT_BLOCKS;

	swapz_unaccount_mapping(context, mapping);
	if (unlikely(context->failed))
		return;

	if (WARN_ON_ONCE(physical_block >= context->physical_blocks ||
			 segment >= context->segment_count ||
			 context->block_live_records[physical_block] >= SWAPZ_MAX_PACKED_RECORDS)) {
		swapz_set_failed(context, -EUCLEAN);
		return;
	}

	if (!context->block_live_records[physical_block])
		context->segment_live_blocks[segment]++;
	context->block_live_records[physical_block]++;

	mapping->physical_block = physical_block;
	mapping->stored_length = stored_length;
	mapping->record_index = record_index;
	mapping->flags = flags | SWAPZ_MAP_VALID;
}

static u32 swapz_current_physical_block(const struct swapz_context *context)
{
	return context->current_segment * SWAPZ_SEGMENT_BLOCKS +
	       context->segment_write_block;
}

static bool swapz_current_segment_has_block(const struct swapz_context *context)
{
	return context->segment_write_block < SWAPZ_SEGMENT_BLOCKS;
}

static void swapz_reset_pack(struct swapz_context *context)
{
	memset(context->pack_buffer, 0, SWAPZ_CONTAINER_HEADER_BYTES);
	context->pack_payload_end = SWAPZ_CONTAINER_HEADER_BYTES;
	context->pack_record_count = 0;
}

static int swapz_advance_segment(struct swapz_context *context);

static int swapz_ensure_physical_block(struct swapz_context *context,
				       bool allow_rotation)
{
	if (swapz_current_segment_has_block(context))
		return 0;
	if (!allow_rotation)
		return -ENOSPC;
	return swapz_advance_segment(context);
}

static void swapz_note_block_written(struct swapz_context *context)
{
	context->segment_write_block++;
	if (context->segment_write_block >
	    context->segment_high_water[context->current_segment])
		context->segment_high_water[context->current_segment] =
			context->segment_write_block;
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
		if (unlikely(context->failed)) {
			error = -EUCLEAN;
			goto fail_pending;
		}
	}

	for (record_index = 0; record_index < context->pack_record_count; ++record_index) {
		struct swapz_pending_record *pending = &context->pending[record_index];

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
	 * physical block reserved in the current segment, otherwise segment advance would
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
	if (unlikely(context->failed))
		return -EUCLEAN;

	context->stats.raw_pages++;
	swapz_note_block_written(context);
	if (bio)
		swapz_complete_bio(bio, 0);
	return 0;
}

static int swapz_store_page(struct swapz_context *context, struct bio *bio,
			    u32 logical_page, const void *page_data,
			    void *compression_buffer, bool compaction,
			    bool allow_rotation)
{
	int compressed_length;

	compressed_length = LZ4_compress_fast(page_data, compression_buffer,
					      SWAPZ_BLOCK_BYTES,
					      SWAPZ_MAX_COMPRESSED_BYTES,
					      1, context->lz4_workmem);
	if (compressed_length > 0) {
		return swapz_add_compressed_record(context, bio, logical_page,
					   compression_buffer, compressed_length,
					   compaction, allow_rotation);
	}

	return swapz_write_raw_page(context, bio, logical_page, page_data,
				    compaction, allow_rotation);
}

static int swapz_decode_loaded_mapping(struct swapz_context *context,
				       u32 logical_page,
				       const struct swapz_mapping *mapping,
				       void *destination)
{
	if (!(mapping->flags & SWAPZ_MAP_COMPRESSED)) {
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
		    mapping->record_index >= le16_to_cpu(container->record_count) ||
		    mapping->record_index >= SWAPZ_MAX_PACKED_RECORDS)
			return -EIO;

		record = &container->records[mapping->record_index];
		offset = le16_to_cpu(record->offset);
		length = le16_to_cpu(record->length);
		if (le32_to_cpu(record->logical_page) != logical_page ||
		    length != mapping->stored_length ||
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

	return swapz_decode_loaded_mapping(context, logical_page, &mapping,
					   destination);
}

static void swapz_try_discard_segment(struct swapz_context *context, u32 segment)
{
	sector_t sectors;
	sector_t start;
	int error;
	u32 high_water;

	if (!context->lower_discard_enabled)
		return;

	high_water = context->segment_high_water[segment];
	if (!high_water)
		return;

	start = swapz_physical_sector(segment * SWAPZ_SEGMENT_BLOCKS);
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

static int swapz_find_free_segment(struct swapz_context *context, u32 *segment_out)
{
	u32 offset;

	for (offset = 0; offset < context->segment_count; ++offset) {
		u32 segment = (context->allocation_cursor + offset) % context->segment_count;

		if (context->segment_state[segment] != SWAPZ_SEGMENT_FREE)
			continue;

		*segment_out = segment;
		context->allocation_cursor = (segment + 1) % context->segment_count;
		return 0;
	}

	return -ENOSPC;
}

static int swapz_choose_gc_victim(struct swapz_context *context, u32 *segment_out)
{
	u32 best_segment = U32_MAX;
	u32 best_live_blocks = U32_MAX;
	u32 offset;

	/*
	 * Prefer the closed segment with the fewest live physical blocks.  The
	 * headroom requirement prevents cleaning from consuming the whole
	 * destination segment, guaranteeing foreground progress after GC.
	 */
	for (offset = 0; offset < context->segment_count; ++offset) {
		u32 segment = (context->gc_cursor + offset) % context->segment_count;
		u32 live_blocks;

		if (context->segment_state[segment] != SWAPZ_SEGMENT_CLOSED)
			continue;

		live_blocks = context->segment_live_blocks[segment];
		if (live_blocks > SWAPZ_SEGMENT_BLOCKS - SWAPZ_GC_HEADROOM_BLOCKS)
			continue;
		if (live_blocks >= best_live_blocks)
			continue;

		best_segment = segment;
		best_live_blocks = live_blocks;
		if (!live_blocks)
			break;
	}

	if (best_segment == U32_MAX)
		return -ENOSPC;

	*segment_out = best_segment;
	context->gc_cursor = (best_segment + 1) % context->segment_count;
	return 0;
}

static int swapz_clean_segment(struct swapz_context *context, u32 victim)
{
	u32 block_offset;
	u32 logical_page;
	int error;

	if (WARN_ON_ONCE(context->segment_state[victim] != SWAPZ_SEGMENT_CLOSED ||
			 context->segment_state[context->current_segment] != SWAPZ_SEGMENT_OPEN ||
			 context->pack_record_count)) {
		swapz_set_failed(context, -EUCLEAN);
		return -EUCLEAN;
	}

	context->segment_state[victim] = SWAPZ_SEGMENT_CLEANING;
	context->stats.gc_victims++;
	context->stats.gc_scanned_mappings += context->logical_pages;
	memset(context->gc_block_counts, 0,
	       SWAPZ_SEGMENT_BLOCKS * sizeof(*context->gc_block_counts));

	/*
	 * Build a bounded reverse index for this victim only.  The global logical
	 * mapping remains 8 bytes/page; scratch is fixed at 256 * 8 u32 entries
	 * plus one byte count per physical block.
	 */
	for (logical_page = 0; logical_page < context->logical_pages; ++logical_page) {
		const struct swapz_mapping mapping = context->mappings[logical_page];
		u32 count;

		if (!swapz_mapping_valid(&mapping) ||
		    swapz_mapping_segment(&mapping) != victim)
			continue;

		block_offset = mapping.physical_block % SWAPZ_SEGMENT_BLOCKS;
		count = context->gc_block_counts[block_offset];
		if (WARN_ON_ONCE(count >= SWAPZ_MAX_PACKED_RECORDS)) {
			error = -EUCLEAN;
			goto fail;
		}

		context->gc_logical_pages[
			block_offset * SWAPZ_MAX_PACKED_RECORDS + count] = logical_page;
		context->gc_block_counts[block_offset] = (u8)(count + 1);
	}

	/*
	 * Preserve source-container grouping.  Read each live source block once,
	 * then repack only its live records before moving to the next source block.
	 */
	for (block_offset = 0; block_offset < SWAPZ_SEGMENT_BLOCKS; ++block_offset) {
		u32 record_count = context->gc_block_counts[block_offset];
		u32 record_index;
		u32 physical_block;

		if (!record_count)
			continue;

		physical_block = victim * SWAPZ_SEGMENT_BLOCKS + block_offset;
		error = swapz_read_block(context, physical_block, context->io_buffer);
		if (error)
			goto fail;
		context->stats.compaction_read_bytes += SWAPZ_BLOCK_BYTES;

		for (record_index = 0; record_index < record_count; ++record_index) {
			const u32 index =
				block_offset * SWAPZ_MAX_PACKED_RECORDS + record_index;
			const u32 page = context->gc_logical_pages[index];
			const struct swapz_mapping mapping = context->mappings[page];

			if (WARN_ON_ONCE(!swapz_mapping_valid(&mapping) ||
					 mapping.physical_block != physical_block)) {
				error = -EUCLEAN;
				goto fail;
			}

			error = swapz_decode_loaded_mapping(context, page, &mapping,
							 context->input_buffer);
			if (error)
				goto fail;

			error = swapz_store_page(context, NULL, page,
						 context->input_buffer,
						 context->compressed_buffer, true, false);
			if (error)
				goto fail;
			context->stats.compaction_pages++;
		}

		/* Keep one destination block group per live source block. */
		error = swapz_flush_pack(context, true, false);
		if (error)
			goto fail;
	}

	if (WARN_ON_ONCE(context->segment_live_blocks[victim] != 0)) {
		error = -EUCLEAN;
		goto fail;
	}

	swapz_try_discard_segment(context, victim);
	context->segment_high_water[victim] = 0;
	context->segment_state[victim] = SWAPZ_SEGMENT_FREE;
	context->free_segments++;
	return 0;

fail:
	context->segment_state[victim] = SWAPZ_SEGMENT_CLOSED;
	swapz_set_failed(context, error);
	return error;
}

static int swapz_open_free_segment(struct swapz_context *context)
{
	u32 segment;
	int error;

	error = swapz_find_free_segment(context, &segment);
	if (error)
		return error;

	if (WARN_ON_ONCE(context->segment_live_blocks[segment] != 0)) {
		swapz_set_failed(context, -EUCLEAN);
		return -EUCLEAN;
	}

	context->segment_state[segment] = SWAPZ_SEGMENT_OPEN;
	context->free_segments--;
	context->current_segment = segment;
	context->segment_write_block = 0;
	context->segment_high_water[segment] = 0;
	context->segment_cycles[segment]++;
	context->stats.segment_switches++;
	return 0;
}

static int swapz_advance_segment(struct swapz_context *context)
{
	int error;

	if (context->pack_record_count)
		return -EDEADLK;

	if (context->segment_state[context->current_segment] == SWAPZ_SEGMENT_OPEN)
		context->segment_state[context->current_segment] = SWAPZ_SEGMENT_CLOSED;

	for (;;) {
		u32 victim;

		if (!context->free_segments)
			return -ENOSPC;

		error = swapz_open_free_segment(context);
		if (error)
			return error;

		/*
		 * Keep one free segment in reserve.  When opening the last free
		 * segment, clean one low-live closed segment into the new current
		 * segment immediately.  The victim becomes the next reserve segment.
		 */
		if (!context->free_segments) {
			error = swapz_choose_gc_victim(context, &victim);
			if (error)
				return error;
			error = swapz_clean_segment(context, victim);
			if (error)
				return error;
		}

		if (swapz_current_segment_has_block(context))
			return 0;

		/* GC exactly filled the destination; continue with the freed victim. */
		context->segment_state[context->current_segment] = SWAPZ_SEGMENT_CLOSED;
	}
}

static int swapz_process_write(struct swapz_context *context, struct bio *bio)
{
	u32 logical_page = (u32)(bio->bi_iter.bi_sector / SWAPZ_BLOCK_SECTORS);
	int error;

	if (logical_page >= context->logical_pages)
		return -ERANGE;

	/*
	 * Keep the current BIO isolated from compaction scratch.  A store can
	 * trigger segment advance after flushing the final pending container, and
	 * GC reuses input_buffer/compressed_buffer while copying victim live pages.
	 */
	swapz_copy_from_bio(bio, context->write_buffer);
	context->stats.logical_write_bytes += SWAPZ_BLOCK_BYTES;
	error = swapz_store_page(context, bio, logical_page, context->write_buffer,
				 context->write_compressed_buffer, false, true);
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
			(sector_t)context->segment_count * SWAPZ_SEGMENT_BLOCKS *
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
	u32 segment_cycle_min = U32_MAX;
	u32 segment_cycle_max = 0;
	u32 segment;
	unsigned int sz = 0;

	switch (type) {
	case STATUSTYPE_INFO:
		for (segment = 0; segment < context->segment_count; ++segment) {
			segment_cycle_min = min(segment_cycle_min,
						context->segment_cycles[segment]);
			segment_cycle_max = max(segment_cycle_max,
						context->segment_cycles[segment]);
		}
		if (segment_cycle_min == U32_MAX)
			segment_cycle_min = 0;

		DMEMIT("segment=%u/%u head_blocks=%u free_segments=%u live_blocks=%u "
		       "logical_write=%llu physical_write=%llu "
		       "logical_read=%llu physical_read=%llu compressed_payload=%llu "
		       "compressed_pages=%llu raw_pages=%llu upper_discards=%llu rotations=%llu "
		       "segment_cycle_min=%u segment_cycle_max=%u "
		       "gc_victims=%llu gc_scanned=%llu gc_pages=%llu gc_read=%llu gc_write=%llu "
		       "lower_discard=%s discard_bytes=%llu discard_failures=%llu failed=%u",
		       context->current_segment, context->segment_count,
		       context->segment_write_block, context->free_segments,
		       context->segment_live_blocks[context->current_segment],
		       context->stats.logical_write_bytes,
		       context->stats.physical_write_bytes,
		       context->stats.logical_read_bytes,
		       context->stats.physical_read_bytes,
		       context->stats.compressed_payload_bytes,
		       context->stats.compressed_pages,
		       context->stats.raw_pages,
		       context->stats.upper_discards,
		       context->stats.segment_switches,
		       segment_cycle_min,
		       segment_cycle_max,
		       context->stats.gc_victims,
		       context->stats.gc_scanned_mappings,
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
	if (context->write_buffer)
		free_page((unsigned long)context->write_buffer);
	if (context->write_compressed_buffer)
		free_page((unsigned long)context->write_compressed_buffer);
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
	kvfree(context->segment_high_water);
	kvfree(context->segment_cycles);
	kvfree(context->segment_live_blocks);
	kvfree(context->segment_state);
	kvfree(context->block_live_records);
	kvfree(context->gc_logical_pages);
	kvfree(context->gc_block_counts);
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
	u64 usable_blocks64;
	u64 logical_pages64;
	u64 reserve_blocks64;
	u64 segment_count64;
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
		target->error = "Zoned backing devices are unsupported in V2";
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
		target->error = "Backing logical block size is incompatible with 4 KiB V2 blocks";
		error = -EINVAL;
		goto fail;
	}

	physical_sectors = bdev_nr_sectors(context->backing->bdev);
	physical_blocks64 = div_u64(physical_sectors, SWAPZ_BLOCK_SECTORS);
	segment_count64 = div_u64(physical_blocks64, SWAPZ_SEGMENT_BLOCKS);
	usable_blocks64 = segment_count64 * SWAPZ_SEGMENT_BLOCKS;
	logical_pages64 = div_u64(target->len, SWAPZ_BLOCK_SECTORS);
	if (!logical_pages64 || logical_pages64 > U32_MAX ||
	    usable_blocks64 > U32_MAX) {
		target->error = "V2 supports at most 16 TiB physical/logical space";
		error = -E2BIG;
		goto fail;
	}
	if (segment_count64 < 3) {
		target->error = "Backing device needs at least three 1 MiB segments";
		error = -ENOSPC;
		goto fail;
	}

	/*
	 * V2 never relies on compression for capacity.  Keep at least 25% of the
	 * logical size (and at least two segments) as physical GC reserve.  This
	 * makes a low-live victim available even when every logical page is raw.
	 */
	reserve_blocks64 = max_t(u64,
				   DIV_ROUND_UP_ULL(logical_pages64,
						    SWAPZ_MIN_RESERVE_DIVISOR),
				   2ULL * SWAPZ_SEGMENT_BLOCKS);
	if (usable_blocks64 < logical_pages64 + reserve_blocks64) {
		target->error = "Backing device needs >=25% plus two segments of GC reserve";
		error = -ENOSPC;
		goto fail;
	}

	context->logical_pages = (u32)logical_pages64;
	context->physical_blocks = (u32)usable_blocks64;
	context->segment_count = (u32)segment_count64;
	context->current_segment = 0;
	context->segment_write_block = 0;
	context->allocation_cursor = 1 % context->segment_count;
	context->gc_cursor = 0;
	context->free_segments = context->segment_count - 1;

	context->mappings = vzalloc(array_size(context->logical_pages,
					       sizeof(*context->mappings)));
	context->segment_high_water = kvcalloc(context->segment_count,
					       sizeof(*context->segment_high_water), GFP_KERNEL);
	context->segment_cycles = kvcalloc(context->segment_count,
					   sizeof(*context->segment_cycles), GFP_KERNEL);
	context->segment_live_blocks = kvcalloc(context->segment_count,
						sizeof(*context->segment_live_blocks), GFP_KERNEL);
	context->segment_state = kvcalloc(context->segment_count,
					 sizeof(*context->segment_state), GFP_KERNEL);
	context->block_live_records = kvcalloc(context->physical_blocks,
					       sizeof(*context->block_live_records), GFP_KERNEL);
	context->gc_logical_pages = kvcalloc(
		SWAPZ_SEGMENT_BLOCKS * SWAPZ_MAX_PACKED_RECORDS,
		sizeof(*context->gc_logical_pages), GFP_KERNEL);
	context->gc_block_counts = kvcalloc(SWAPZ_SEGMENT_BLOCKS,
					   sizeof(*context->gc_block_counts), GFP_KERNEL);
	if (!context->mappings || !context->segment_high_water ||
	    !context->segment_cycles || !context->segment_live_blocks ||
	    !context->segment_state || !context->block_live_records ||
	    !context->gc_logical_pages || !context->gc_block_counts) {
		target->error = "Cannot allocate mapping/segment metadata";
		error = -ENOMEM;
		goto fail;
	}
	for (index = 0; index < context->logical_pages; ++index)
		context->mappings[index].physical_block = SWAPZ_EMPTY_BLOCK;
	context->segment_state[0] = SWAPZ_SEGMENT_OPEN;
	context->segment_cycles[0] = 1;

	context->write_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->write_compressed_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->input_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->io_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->compressed_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->pack_buffer = (void *)__get_free_page(GFP_KERNEL);
	context->lz4_workmem = kmalloc(LZ4_MEM_COMPRESS, GFP_KERNEL);
	if (!context->write_buffer || !context->write_compressed_buffer ||
	    !context->input_buffer || !context->io_buffer ||
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

	DMINFO("logical=%u pages physical=%u blocks segments=%u segment_blocks=%u free=%u lower_discard=%s",
	       context->logical_pages, context->physical_blocks,
	       context->segment_count, SWAPZ_SEGMENT_BLOCKS,
	       context->free_segments,
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
