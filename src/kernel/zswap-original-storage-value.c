// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-storage-value.h"

#ifdef SWAPZ_SHARED_STORAGE_VALUE_TEST
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

_Static_assert(sizeof(struct swapz_map) == 20U, "ordinary map unchanged");
_Static_assert(SWAPZ_SHARED_ORIGINAL_CAPACITY <= SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS,
	       "bounded private retention table");

static int spans_disjoint(const void *first, swapz_u64 first_bytes,
			  const void *second, swapz_u64 second_bytes)
{
	unsigned long a = (unsigned long)first, b = (unsigned long)second;

	return first && second && first_bytes && second_bytes &&
	       first_bytes - 1U <= (swapz_u64)(~0UL - a) &&
	       second_bytes - 1U <= (swapz_u64)(~0UL - b) &&
	       (a <= b ? (swapz_u64)(b - a) >= first_bytes :
			 (swapz_u64)(a - b) >= second_bytes);
}

/* The whole value wrapper, including its private retention table, must
 * be disjoint from the actual authority arrays. Legacy I/O entry points
 * additionally validate their own input/output spans against authority.
 */
static int outside_authority(const struct swapz_authority *authority,
			     const void *pointer, swapz_u64 bytes)
{
	if (!authority || !spans_disjoint(pointer, bytes, authority, sizeof(*authority)))
		return 0;
#define CHECK_ARRAY(field, count) \
	if (authority->field && !spans_disjoint(pointer, bytes, authority->field, \
			(swapz_u64)(count) * sizeof(*authority->field))) \
		return 0
	CHECK_ARRAY(maps, authority->logical_pages);
	CHECK_ARRAY(live_records, authority->physical_blocks);
	CHECK_ARRAY(extent_classes, authority->physical_blocks);
	CHECK_ARRAY(extent_sequence_delta, authority->physical_blocks);
	CHECK_ARRAY(segment_sequence_base, authority->sequence_segment_count);
	CHECK_ARRAY(segment_foreground, authority->segment_count);
	CHECK_ARRAY(segment_mapped_pages, authority->segment_count);
	CHECK_ARRAY(segment_program_counts, authority->segment_count);
	CHECK_ARRAY(segment_first_page, authority->segment_count);
	CHECK_ARRAY(segment_last_page, authority->segment_count);
	CHECK_ARRAY(page_prev_in_segment, authority->logical_pages);
	CHECK_ARRAY(page_next_in_segment, authority->logical_pages);
	CHECK_ARRAY(segment_gc_live_bytes, authority->segment_count);
	CHECK_ARRAY(segment_gc_io_cost, authority->segment_count);
	CHECK_ARRAY(segment_gc_min_live_blocks, authority->segment_count);
#undef CHECK_ARRAY
	return 1;
}

static int outside_storage(const struct swapz_shared_storage_value *storage,
			   const void *pointer, swapz_u64 bytes)
{
	return spans_disjoint(pointer, bytes, storage, sizeof(*storage));
}

static int attached(const struct swapz_shared_storage_value *storage)
{
	return storage && storage->shared.authority &&
	       storage->shared.authority->original == &storage->shared.owner;
}

static int ready(const struct swapz_shared_storage_value *storage)
{
	return !attached(storage) ? -EINVAL : storage->faulted ? -EUCLEAN : 0;
}

static struct swapz_shared_storage_value_slot *find_slot(
	struct swapz_shared_storage_value *storage, const void *token)
{
	unsigned int index;

	/* Equality only: never subtract or dereference an untrusted token. */
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		if (token == &storage->slots[index])
			return &storage->slots[index];
	return NULL;
}

static void *retain_value(void *context, swapz_u8 codec, swapz_u8 version)
{
	struct swapz_shared_storage_value *storage = context;
	struct swapz_shared_storage_value_slot *slot = NULL;
	struct swapz_original_decoder_value_handle handle = {0};
	unsigned int index;
	int error;

	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		if (!storage->slots[index].active) {
			slot = &storage->slots[index];
			break;
		}
	if (!slot) {
		storage->get_error = -ENOSPC;
		return NULL;
	}
	error = storage->ops.decoder_get(storage->ops.context, codec, version, &handle);
	if (error) {
		storage->get_error = error < 0 ? error : -EIO;
		return NULL;
	}
	/* A malformed successful callback cannot be safely put: it might name
	 * an already-owned record. Hard-refuse rather than release ambiguity.
	 * The retained provider and wrapper must remain alive on this fault.
	 */
	if (!handle.lifecycle_epoch || !handle.generation ||
	    handle.slot_index >= SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS ||
	    handle.codec != codec || handle.version != version ||
	    (storage->lifecycle_epoch && handle.lifecycle_epoch != storage->lifecycle_epoch) ||
	    handle.generation <= storage->last_generation[handle.slot_index]) {
		storage->faulted = 1;
		storage->get_error = -EUCLEAN;
		return NULL;
	}
	/* A provider slot cannot be reused before its existing record put. */
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		if (storage->slots[index].active &&
		    storage->slots[index].handle.slot_index == handle.slot_index) {
			storage->faulted = 1;
			storage->get_error = -EUCLEAN;
			return NULL;
		}
	storage->lifecycle_epoch = handle.lifecycle_epoch;
	storage->last_generation[handle.slot_index] = handle.generation;
	slot->handle = handle;
	slot->active = 1;
	return slot;
}

static void release_value(void *context, void *token)
{
	struct swapz_shared_storage_value *storage = context;
	struct swapz_shared_storage_value_slot *slot = find_slot(storage, token);

	if (!slot || !slot->active) {
		storage->faulted = 1;
		return;
	}
	if (storage->ops.decoder_put(storage->ops.context, &slot->handle)) {
		/* Legacy authority put is infallible. Preserve the unreleased value
		 * and quarantine the slot rather than silently freeing ownership.
		 * Do not turn an already published map into a false lower failure.
		 */
		storage->faulted = 1;
		return;
	}
	memset(slot, 0, sizeof(*slot));
}

static int write_lower(void *context, swapz_u32 start, const swapz_u8 *bytes,
		       swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_shared_storage_value *storage = context;

	return storage->ops.write(storage->ops.context, start, bytes, length, completed);
}

static int flush_lower(void *context)
{
	struct swapz_shared_storage_value *storage = context;

	return storage->ops.flush(storage->ops.context);
}

static int read_lower(void *context, swapz_u32 start, swapz_u8 *bytes,
		      swapz_u32 length, swapz_u32 *completed)
{
	struct swapz_shared_storage_value *storage = context;

	return storage->ops.read(storage->ops.context, start, bytes, length, completed);
}

int swapz_shared_storage_value_init(struct swapz_shared_storage_value *storage,
	struct swapz_authority *authority, const struct swapz_shared_storage_value_ops *ops)
{
	struct swapz_original_storage_ops bridge = {
		.context = storage, .write = write_lower, .flush = flush_lower,
		.read = read_lower, .decoder_get = retain_value, .decoder_put = release_value,
	};

	if (!storage || !authority || !ops ||
	    !outside_authority(authority, storage, sizeof(*storage)) ||
	    !outside_storage(storage, ops, sizeof(*ops)) ||
	    !ops->write || !ops->flush || !ops->read ||
	    !ops->decoder_get || !ops->decoder_put || !ops->decoder_read)
		return -EINVAL;
	if (authority->original)
		return -EBUSY;
	memset(storage, 0, sizeof(*storage));
	storage->ops = *ops;
	return swapz_shared_storage_init(&storage->shared, authority, &bridge);
}

static int valid_input(const struct swapz_shared_storage_value *storage,
	const struct swapz_authority_import_spec *spec,
	const struct swapz_original_extent_input *input)
{
	return outside_storage(storage, spec, sizeof(*spec)) &&
	       outside_storage(storage, input, sizeof(*input)) &&
	       outside_storage(storage, input->bytes, input->bytes_available);
}

static int get_result(const struct swapz_shared_storage_value *storage, int error)
{
	/* The pointer adapter maps get failure to EAGAIN. Preserve the exact
	 * value-provider error only when a get was actually attempted.
	 */
	return error == -EAGAIN && storage->get_error ? storage->get_error : error;
}

int swapz_shared_storage_value_write(struct swapz_shared_storage_value *storage,
	const struct swapz_authority_import_spec *spec, const struct swapz_original_extent_input *input)
{
	int error = ready(storage);

	if (error)
		return error;
	if (!valid_input(storage, spec, input))
		return -EINVAL;
	storage->get_error = 0;
	return get_result(storage, swapz_shared_storage_write(&storage->shared, spec, input));
}

int swapz_shared_storage_value_reserve(struct swapz_shared_storage_value *storage,
	const struct swapz_authority_import_spec *spec, const struct swapz_original_extent_input *input,
	swapz_u32 *credit)
{
	int error = ready(storage);

	if (error)
		return error;
	if (!valid_input(storage, spec, input) || !outside_storage(storage, credit, sizeof(*credit)))
		return -EINVAL;
	storage->get_error = 0;
	return get_result(storage, swapz_shared_storage_reserve(&storage->shared, spec, input, credit));
}

int swapz_shared_storage_value_cancel_reserved(struct swapz_shared_storage_value *storage,
	swapz_u32 credit)
{
	/* Drain an existing token even if a provider fault was detected. */
	return attached(storage) ? swapz_shared_storage_cancel_reserved(&storage->shared, credit) : -EINVAL;
}

int swapz_shared_storage_value_commit_reserved(struct swapz_shared_storage_value *storage,
	swapz_u32 credit)
{
	int error = ready(storage);

	return error ? error : swapz_shared_storage_commit_reserved(&storage->shared, credit);
}

int swapz_shared_storage_value_pin(struct swapz_shared_storage_value *storage,
	swapz_u32 logical, swapz_u64 *pin)
{
	int error = ready(storage);

	if (error)
		return error;
	if (!outside_storage(storage, pin, sizeof(*pin)) ||
	    !outside_authority(storage->shared.authority, pin, sizeof(*pin)))
		return -EINVAL;
	return swapz_shared_original_pin(storage->shared.authority, logical, pin);
}

int swapz_shared_storage_value_put(struct swapz_shared_storage_value *storage, swapz_u64 pin)
{
	return attached(storage) ? swapz_shared_original_put(storage->shared.authority, pin) : -EINVAL;
}

static const struct swapz_shared_storage_value_slot *pinned_slot(
	struct swapz_shared_storage_value *storage, swapz_u64 pin)
{
	const struct swapz_shared_original_record *record =
		swapz_shared_original_view(storage->shared.authority, pin);
	const struct swapz_shared_storage_value_slot *slot;

	if (!record)
		return NULL;
	slot = find_slot(storage, record->decoder);
	if (!slot || !slot->active ||
	    slot->handle.codec != record->spec.codec ||
	    slot->handle.version != record->spec.codec_version ||
	    slot->handle.lifecycle_epoch != storage->lifecycle_epoch ||
	    slot->handle.slot_index >= SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS ||
	    slot->handle.generation != storage->last_generation[slot->handle.slot_index])
		return NULL;
	return slot;
}

struct swapz_shared_storage_value_result swapz_shared_storage_value_read_pinned(
	struct swapz_shared_storage_value *storage, swapz_u64 pin, swapz_u8 *output, swapz_u32 capacity)
{
	struct swapz_shared_storage_value_result result = {0};
	struct swapz_shared_storage_snapshot legacy;
	const struct swapz_shared_storage_value_slot *slot;

	result.error = ready(storage);
	if (result.error)
		return result;
	if (!outside_storage(storage, output, capacity)) {
		result.error = -EINVAL;
		return result;
	}
	slot = pinned_slot(storage, pin);
	if (!slot) {
		result.error = -ESTALE;
		return result;
	}
	result.error = swapz_shared_storage_read_pinned(&storage->shared, pin, output, capacity, &legacy);
	if (!result.error) {
		result.snapshot.spec = legacy.spec;
		result.snapshot.map = legacy.map;
		result.snapshot.sequence = legacy.sequence;
		result.snapshot.handle = slot->handle;
	}
	return result;
}

int swapz_shared_storage_value_decode_pinned(struct swapz_shared_storage_value *storage,
	swapz_u64 pin, swapz_u8 *compressed, swapz_u8 *scratch,
	swapz_u8 *verified, swapz_u8 *output, swapz_u32 capacity)
{
	const void *buffers[] = { compressed, scratch, verified, output };
	struct swapz_shared_storage_value_result result;
	struct swapz_original_decoder_value_snapshot snapshot = {0};
	unsigned int index, prior;
	int error = ready(storage);

	if (error)
		return error;
	if (capacity != SWAPZ_BLOCK_BYTES)
		return -EINVAL;
	for (index = 0; index < sizeof(buffers) / sizeof(buffers[0]); ++index) {
		if (!outside_storage(storage, buffers[index], capacity) ||
		    !outside_authority(storage->shared.authority, buffers[index], capacity))
			return -EINVAL;
		for (prior = 0; prior < index; ++prior)
			if (!spans_disjoint(buffers[index], capacity, buffers[prior], capacity))
				return -EINVAL;
	}
	result = swapz_shared_storage_value_read_pinned(storage, pin, compressed, capacity);
	if (result.error)
		return result.error;

	/* The existing storage pin owns this immutable, CRC-checked record
	 * across the synchronous callback. The callback independently gets
	 * and puts a transient decoder lease, never the record reference. */
	snapshot.handle = result.snapshot.handle;
	snapshot.record.compressed_length = result.snapshot.spec.compressed_length;
	snapshot.record.decoded_length = SWAPZ_BLOCK_BYTES;
	snapshot.record.compressed_crc32c = result.snapshot.spec.compressed_crc32c;
	memcpy(snapshot.record.original_sha256, result.snapshot.spec.original_sha256,
	       sizeof(snapshot.record.original_sha256));
	snapshot.record.representation = 0x5a;
	snapshot.record.codec = result.snapshot.spec.codec;
	snapshot.record.version = result.snapshot.spec.codec_version;
	snapshot.compressed_bytes = compressed;
	snapshot.compressed_capacity = result.snapshot.spec.compressed_length;
	error = storage->ops.decoder_read(storage->ops.context, &snapshot,
		SWAPZ_ORIGINAL_DECODE_M3568, scratch, capacity, verified, capacity,
		output, capacity);
	return error > 0 ? -EIO : error;
}

int swapz_shared_storage_value_relocate(struct swapz_shared_storage_value *storage,
	swapz_u64 pin, swapz_u64 epoch)
{
	int error = ready(storage);

	if (error)
		return error;
	if (!pinned_slot(storage, pin))
		return -ESTALE;
	storage->get_error = 0;
	return get_result(storage, swapz_shared_storage_relocate(&storage->shared, pin, epoch));
}

int swapz_shared_storage_value_close(struct swapz_shared_storage_value *storage)
{
	unsigned int index;
	int error = ready(storage);

	if (error)
		return error;
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		if (storage->slots[index].active)
			return -EBUSY;
	return swapz_shared_storage_close(&storage->shared);
}
#endif
