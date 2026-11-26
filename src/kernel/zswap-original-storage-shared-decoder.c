// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-storage-shared-decoder.h"

#ifdef SWAPZ_SHARED_STORAGE_DECODER_TEST
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

enum { STORAGE_OPEN = 1, STORAGE_FAULTED, STORAGE_CLOSED };

_Static_assert(sizeof(struct swapz_map) == 20U, "ordinary map ABI");

static int disjoint(const void *first, swapz_u64 first_bytes,
	const void *second, swapz_u64 second_bytes)
{
	unsigned long a = (unsigned long)first, b = (unsigned long)second;

	return first && second && first_bytes && second_bytes &&
		first_bytes - 1U <= (swapz_u64)(~0UL - a) &&
		second_bytes - 1U <= (swapz_u64)(~0UL - b) &&
		(a <= b ? (swapz_u64)(b - a) >= first_bytes :
			(swapz_u64)(a - b) >= second_bytes);
}

static int outside_authority(const struct swapz_authority *a,
	const void *pointer, swapz_u64 bytes)
{
	if (!a || !disjoint(pointer, bytes, a, sizeof(*a)))
		return 0;
#define CHECK_ARRAY(field, count) \
	if (a->field && !disjoint(pointer, bytes, a->field, \
		(swapz_u64)(count) * sizeof(*a->field))) \
		return 0
	CHECK_ARRAY(maps, a->logical_pages);
	CHECK_ARRAY(live_records, a->physical_blocks);
	CHECK_ARRAY(extent_classes, a->physical_blocks);
	CHECK_ARRAY(extent_sequence_delta, a->physical_blocks);
	CHECK_ARRAY(segment_sequence_base, a->sequence_segment_count);
	CHECK_ARRAY(segment_foreground, a->segment_count);
	CHECK_ARRAY(segment_mapped_pages, a->segment_count);
	CHECK_ARRAY(segment_program_counts, a->segment_count);
	CHECK_ARRAY(segment_first_page, a->segment_count);
	CHECK_ARRAY(segment_last_page, a->segment_count);
	CHECK_ARRAY(page_prev_in_segment, a->logical_pages);
	CHECK_ARRAY(page_next_in_segment, a->logical_pages);
	CHECK_ARRAY(segment_gc_live_bytes, a->segment_count);
	CHECK_ARRAY(segment_gc_io_cost, a->segment_count);
	CHECK_ARRAY(segment_gc_min_live_blocks, a->segment_count);
#undef CHECK_ARRAY
	return 1;
}

static int ready(const struct swapz_shared_storage_decoder *storage)
{
	return storage && storage->state == STORAGE_OPEN &&
		storage->storage.authority &&
		storage->storage.authority->original == &storage->storage.owner;
}

static int write_lower(void *context, swapz_u32 start, const swapz_u8 *bytes,
	swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_shared_storage_decoder *storage = context;

	return storage->ops.write(storage->ops.context, start, bytes, length, completed);
}

static int flush_lower(void *context)
{
	struct swapz_shared_storage_decoder *storage = context;

	return storage->ops.flush(storage->ops.context);
}

static int read_lower(void *context, swapz_u32 start, swapz_u8 *bytes,
	swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_shared_storage_decoder *storage = context;

	return storage->ops.read(storage->ops.context, start, bytes, length, completed);
}

/* Legacy token protocol needs a nonnull marker, but there is no record
 * provider acquisition/release. Only the shared owner's two lifecycle
 * leases and one transient lease per decode exist. */
static void *record_marker(void *context, swapz_u8 codec, swapz_u8 version)
{
	struct swapz_shared_storage_decoder *storage = context;

	return ready(storage) && !storage->scoped_pin &&
		(codec == 1U || codec == 2U) && version == 1U ? storage : NULL;
}

static void release_marker(void *context, void *marker)
{
	struct swapz_shared_storage_decoder *storage = context;

	if (marker != storage)
		storage->state = STORAGE_FAULTED;
}

static int reserve_epoch(void *context, swapz_u64 *epoch)
{
	struct swapz_shared_storage_decoder *storage = context;

	return storage->ops.reserve_epoch(storage->ops.context, epoch);
}

/* The allocator sequence is global within this authority lifetime, never
 * rewound by cancel, never wraps. Slot index comes from the actual record,
 * not the logical map or a caller-provided value. */
static int resolve(struct swapz_shared_storage_decoder *storage, swapz_u64 pin,
	struct swapz_original_decoder_value_handle *handle,
	const struct swapz_shared_original_record **resolved)
{
	const struct swapz_shared_original_record *record;
	swapz_u32 index;

	if (!ready(storage))
		return -ESHUTDOWN;
	record = swapz_shared_original_view(storage->storage.authority, pin);
	if (!record || record->decoder != storage || !record->sequence ||
	    record->sequence == ~(swapz_u32)0)
		return -ESTALE;
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		if (record == &storage->storage.owner.records[index])
			break;
	if (index == SWAPZ_SHARED_ORIGINAL_CAPACITY)
		return -EUCLEAN;
	*handle = (struct swapz_original_decoder_value_handle) {
		.lifecycle_epoch = storage->epoch, .generation = record->sequence,
		.slot_index = index, .codec = record->spec.codec,
		.version = record->spec.codec_version,
	};
	*resolved = record;
	return 0;
}

static int snapshot(void *context, swapz_u64 pin,
	struct swapz_original_decoder_value_snapshot *output)
{
	struct swapz_shared_storage_decoder *storage = context;
	struct swapz_original_decoder_value_snapshot result = {0};
	const struct swapz_shared_original_record *record;
	int error;

	if (!pin || pin != storage->scoped_pin || !storage->scoped_bytes)
		return -ESTALE;
	error = resolve(storage, pin, &result.handle, &record);
	if (error)
		return error;
	result.record.compressed_length = record->spec.compressed_length;
	result.record.decoded_length = SWAPZ_BLOCK_BYTES;
	result.record.compressed_crc32c = record->spec.compressed_crc32c;
	memcpy(result.record.original_sha256, record->spec.original_sha256,
		sizeof(result.record.original_sha256));
	result.record.representation = 0x5a;
	result.record.codec = record->spec.codec;
	result.record.version = record->spec.codec_version;
	result.compressed_bytes = storage->scoped_bytes;
	result.compressed_capacity = record->spec.compressed_length;
	*output = result;
	return 0;
}

int swapz_shared_storage_decoder_init(struct swapz_shared_storage_decoder *storage,
	struct swapz_authority *authority, const struct swapz_shared_storage_decoder_ops *ops)
{
	struct swapz_original_storage_ops lower = {
		.context = storage, .write = write_lower, .flush = flush_lower,
		.read = read_lower, .decoder_get = record_marker, .decoder_put = release_marker,
	};
	struct swapz_original_decoder_shared_ops decoder = {
		.context = storage, .reserve_epoch = reserve_epoch, .snapshot = snapshot,
	};
	int error;

	if (!storage || storage->state || !ops || !ops->write || !ops->flush ||
	    !ops->read || !ops->reserve_epoch ||
	    !outside_authority(authority, storage, sizeof(*storage)) ||
	    !disjoint(storage, sizeof(*storage), ops, sizeof(*ops)))
		return -EINVAL;
	storage->ops = *ops;
	error = swapz_shared_storage_init(&storage->storage, authority, &lower);
	if (error)
		return error;
	error = swapz_original_decoder_shared_init(&storage->provider, &decoder,
		SWAPZ_SHARED_ORIGINAL_CAPACITY, &storage->epoch);
	if (error) {
		/* An uncertain provider unwind must not be reused. */
		storage->state = STORAGE_FAULTED;
		if (swapz_shared_storage_close(&storage->storage))
			return -EUCLEAN;
		return error;
	}
	storage->state = STORAGE_OPEN;
	return 0;
}

int swapz_shared_storage_decoder_read(struct swapz_shared_storage_decoder *storage,
	swapz_u64 epoch, swapz_u64 pin, swapz_u8 *compressed, swapz_u8 *scratch,
	swapz_u8 *verified, swapz_u8 *output, swapz_u32 capacity)
{
	const void *buffers[] = { compressed, scratch, verified, output };
	struct swapz_original_decoder_value_handle expected;
	const struct swapz_shared_original_record *record;
	unsigned int index, prior;
	int error;

	if (!ready(storage) || storage->scoped_pin)
		return -ESHUTDOWN;
	if (!epoch || epoch != storage->epoch)
		return -ESTALE;
	if (capacity != SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	for (index = 0; index < sizeof(buffers) / sizeof(buffers[0]); ++index) {
		if (!disjoint(buffers[index], capacity, storage, sizeof(*storage)) ||
		    !outside_authority(storage->storage.authority, buffers[index], capacity))
			return -EINVAL;
		for (prior = 0; prior < index; ++prior)
			if (!disjoint(buffers[index], capacity, buffers[prior], capacity))
				return -EINVAL;
	}
	error = resolve(storage, pin, &expected, &record);
	if (error)
		return error;
	/* The same ordered owner excludes any mutation of the retained record
	 * between the checked lower read and the provider snapshot callback. */
	error = swapz_shared_storage_read(&storage->storage, pin, compressed, capacity);
	if (error)
		return error;
	storage->scoped_pin = pin;
	storage->scoped_bytes = compressed;
	error = swapz_original_decoder_shared_read(&storage->provider, pin, &expected,
		SWAPZ_ORIGINAL_DECODE_M3568, scratch, capacity, verified, capacity,
		output, capacity);
	storage->scoped_bytes = NULL;
	storage->scoped_pin = 0;
	/* Unexpected provider lifetime/lease failures are not recoverable by
	 * continuing writes against the same owner. Keep the attachment alive. */
	if (error == -EIO || error == -ESHUTDOWN || error > 0)
		storage->state = STORAGE_FAULTED;
	return error > 0 ? -EIO : error;
}

int swapz_shared_storage_decoder_close(struct swapz_shared_storage_decoder *storage)
{
	int error;

	if (!ready(storage))
		return -ESHUTDOWN;
	if (storage->scoped_pin)
		return -EBUSY;
	/* Detach checks every current/retired record and pin. Busy leaves the
	 * shared provider open so that the ordered owner can drain normally. */
	error = swapz_shared_storage_close(&storage->storage);
	if (error)
		return error;
	storage->state = STORAGE_FAULTED;
	error = swapz_original_decoder_shared_begin_close(&storage->provider, storage->epoch);
	if (!error)
		error = swapz_original_decoder_shared_finish_close(&storage->provider, storage->epoch);
	if (!error)
		storage->state = STORAGE_CLOSED;
	return error;
}
#endif
