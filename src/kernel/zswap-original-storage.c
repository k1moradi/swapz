// SPDX-License-Identifier: GPL-2.0-only
#include "zswap-original-storage.h"

#ifdef SWAPZ_ORIGINAL_STORAGE_TEST
#ifdef __KERNEL__
#include <linux/errno.h>
#include <linux/string.h>
#else
#include <errno.h>
#include <string.h>
#endif

_Static_assert(sizeof(struct swapz_map) == 20U, "ordinary map ABI");
_Static_assert(SWAPZ_MAX_COMPRESSED == 3568U, "ordinary cap");

static int isolated(const struct swapz_authority *authority)
{
	return authority && authority->maps && authority->live_records &&
	       authority->extent_classes && !authority->reuse_dead_segments &&
	       !authority->gc_allocation && !authority->segment_foreground &&
	       !authority->segment_mapped_pages && !authority->segment_program_counts &&
	       !authority->segment_first_page && !authority->segment_last_page &&
	       !authority->page_prev_in_segment && !authority->page_next_in_segment &&
	       !authority->segment_gc_live_bytes && !authority->segment_gc_io_cost &&
	       !authority->segment_gc_min_live_blocks &&
	       !authority->extent_sequence_delta && !authority->segment_sequence_base;
}

/* Compare integer address differences, never unrelated C pointers. */
static int span_valid(const void *pointer, swapz_u64 bytes)
{
	return pointer && bytes && bytes - 1U <=
	       (swapz_u64)(~0UL - (unsigned long)pointer);
}

static int disjoint(const void *first, swapz_u64 first_bytes,
		    const void *second, swapz_u64 second_bytes)
{
	unsigned long a = (unsigned long)first, b = (unsigned long)second;

	return span_valid(first, first_bytes) && span_valid(second, second_bytes) &&
	       (a <= b ? (swapz_u64)(b - a) >= first_bytes :
			 (swapz_u64)(a - b) >= second_bytes);
}

static int outside_authority(const struct swapz_authority *authority,
			     const void *pointer, swapz_u64 bytes)
{
	return disjoint(pointer, bytes, authority, sizeof(*authority)) &&
	       disjoint(pointer, bytes, authority->maps,
			(swapz_u64)authority->logical_pages * sizeof(*authority->maps)) &&
	       disjoint(pointer, bytes, authority->live_records,
			(swapz_u64)authority->physical_blocks *
			sizeof(*authority->live_records)) &&
	       disjoint(pointer, bytes, authority->extent_classes,
			authority->physical_blocks);
}

static int outside_owner(const struct swapz_original_storage *storage,
			 const void *pointer, swapz_u64 bytes)
{
	return storage && storage->disk.authority &&
	       disjoint(pointer, bytes, storage, sizeof(*storage)) &&
	       outside_authority(storage->disk.authority, pointer, bytes);
}

static int ready(const struct swapz_original_storage *storage)
{
	return storage && !storage->faulted && !storage->disk.closing &&
	       isolated(storage->disk.authority);
}

static int record_index(const struct swapz_original_storage *storage,
			swapz_u64 ticket)
{
	unsigned int index;

	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		if (storage->disk.records[index].state != SWAPZ_IMPORT_DISK_EMPTY &&
		    storage->disk.records[index].ticket == ticket)
			return (int)index;
	return -1;
}

static struct swapz_original_storage_pin *find_pin(
	struct swapz_original_storage *storage, swapz_u64 pin)
{
	unsigned int index;

	if (!storage || !pin)
		return NULL;
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		if (storage->pins[index].id == pin)
			return &storage->pins[index];
	return NULL;
}

/* Only release decoder references after the actual allocator owner has
 * released its record. In particular, a retired reader holds both lifetimes. */
static void release_empty(struct swapz_original_storage *storage)
{
	unsigned int index;

	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		if (storage->decoder[index] &&
		    storage->disk.records[index].state == SWAPZ_IMPORT_DISK_EMPTY) {
			storage->ops.decoder_put(storage->ops.context,
						 storage->decoder[index]);
			storage->decoder[index] = NULL;
		}
}

int swapz_original_storage_init(struct swapz_original_storage *storage,
	struct swapz_authority *authority, const struct swapz_original_storage_ops *ops)
{
	swapz_u32 page, block;

	if (!storage || !isolated(authority) || !ops || !ops->write ||
	    !ops->flush || !ops->read || !ops->decoder_get || !ops->decoder_put ||
	    authority->in_flight || authority->batch_pending ||
	    !outside_authority(authority, storage, sizeof(*storage)) ||
	    !disjoint(storage, sizeof(*storage), ops, sizeof(*ops)))
		return -EINVAL;
	/* The existing dormant owner cannot coexist with valid ordinary maps.
	 * Reject existing liveness too; no competing ownership domain. */
	for (page = 0; page < authority->logical_pages; ++page)
		if (authority->maps[page].valid)
			return -EBUSY;
	for (block = 0; block < authority->physical_blocks; ++block)
		if (authority->live_records[block])
			return -EBUSY;
	memset(storage, 0, sizeof(*storage));
	storage->ops = *ops;
	swapz_import_disk_init(&storage->disk, authority);
	return 0;
}

static int fail_reservation(struct swapz_original_storage *storage,
			    swapz_u64 ticket, int error)
{
	int index = record_index(storage, ticket);

	if (index < 0 ||
	    swapz_import_disk_abort(&storage->disk, ticket)) {
		/* Unexpected ownership fault: do not free a possible live lease or
		 * reuse a possibly submitted reservation. Fence new work. */
		storage->faulted = 1;
		return error;
	}
	release_empty(storage);
	return error;
}

static int write_record(struct swapz_original_storage *storage,
	const struct swapz_authority_import_spec *spec,
	const struct swapz_original_extent_input *input,
	swapz_u64 replaces, swapz_u64 *ticket)
{
	struct swapz_authority *authority;
	swapz_u64 reserved;
	swapz_u32 completed = 0;
	void *lease;
	int index, error, flush_completed = 0;

	if (!ready(storage) || !spec || !input || !ticket)
		return -EINVAL;
	authority = storage->disk.authority;
	if (spec->logical_page >= authority->logical_pages ||
	    authority->maps[spec->logical_page].valid ||
	    authority->maps[spec->logical_page].generation == ~(swapz_u32)0 ||
	    input->generation != authority->maps[spec->logical_page].generation + 1U ||
	    input->logical_page != spec->logical_page ||
	    input->length != spec->compressed_length ||
	    input->crc32c != spec->compressed_crc32c ||
	    input->codec != spec->codec || input->version != spec->codec_version)
		return -ESTALE;
	/* The actual extent implementation checks typed profile, bounds,
	 * overlap, CRC and deterministic zero suffix before any reservation. */
	error = swapz_original_extent_begin(&storage->extent, storage->image,
		SWAPZ_BLOCK_BYTES, &storage->record, sizeof(storage->record), 1U,
		SWAPZ_ORIGINAL_EXTENT_CONSERVATIVE, SWAPZ_ORIGINAL_EXTENT_DEDICATED);
	if (error)
		return error;
	error = swapz_original_extent_append(&storage->extent, input);
	if (error)
		return error;
	error = swapz_original_extent_seal(&storage->extent);
	if (error)
		return error;
	lease = storage->ops.decoder_get(storage->ops.context, input->codec,
					 input->version);
	if (!lease)
		return -EAGAIN;
	error = swapz_import_disk_stage(&storage->disk, spec, 1U, replaces,
					&storage->transaction, &reserved);
	if (error) {
		storage->ops.decoder_put(storage->ops.context, lease);
		return error;
	}
	index = record_index(storage, reserved);
	if (index < 0 || storage->decoder[index]) {
		/* Impossible with exclusive initialized owner. Preserve the
		 * reservation and fence; no ordinary fallback after claim. */
		storage->faulted = 1;
		storage->ops.decoder_put(storage->ops.context, lease);
		return -EUCLEAN;
	}
	storage->decoder[index] = lease;
	error = swapz_import_disk_submit(&storage->disk, reserved);
	if (error)
		return fail_reservation(storage, reserved, error);
	error = storage->ops.write(storage->ops.context,
				   storage->transaction.start_block,
				   storage->image, SWAPZ_BLOCK_BYTES, &completed);
	if (!error && completed != SWAPZ_BLOCK_BYTES)
		error = -EIO;
	if (!error) {
		error = storage->ops.flush(storage->ops.context);
		flush_completed = !error;
	}
	if (error > 0)
		error = -EIO;
	/* The lower outcome comes solely from the supplied callbacks. The
	 * dormant primitive transfers real reservation liveness only after
	 * full write + flush; it is not a production map or real upper ACK. */
	error = swapz_import_disk_complete_payload(&storage->disk, reserved,
		&storage->transaction, storage->image, SWAPZ_BLOCK_BYTES,
		error, completed == SWAPZ_BLOCK_BYTES ? 1U : 0U, flush_completed);
	if (error)
		return fail_reservation(storage, reserved, error);
	release_empty(storage);
	*ticket = reserved;
	return 0;
}

int swapz_original_storage_write(struct swapz_original_storage *storage,
	const struct swapz_authority_import_spec *spec,
	const struct swapz_original_extent_input *input, swapz_u64 *ticket)
{
	if (!ready(storage) ||
	    !outside_owner(storage, spec, sizeof(*spec)) ||
	    !outside_owner(storage, input, sizeof(*input)) ||
	    !outside_owner(storage, ticket, sizeof(*ticket)) ||
	    !outside_owner(storage, input->bytes, input->bytes_available) ||
	    !disjoint(ticket, sizeof(*ticket), spec, sizeof(*spec)) ||
	    !disjoint(ticket, sizeof(*ticket), input, sizeof(*input)) ||
	    !disjoint(ticket, sizeof(*ticket), input->bytes, input->bytes_available))
		return -EINVAL;
	return write_record(storage, spec, input, 0U, ticket);
}

int swapz_original_storage_pin(struct swapz_original_storage *storage,
	swapz_u64 ticket, swapz_u64 *pin)
{
	unsigned int index;
	int record, error;

	if (!ready(storage) || !outside_owner(storage, pin, sizeof(*pin)))
		return -EINVAL;
	record = record_index(storage, ticket);
	if (record < 0 || !storage->decoder[record])
		return -ESTALE;
	if (storage->next_pin == ~(swapz_u64)0)
		return -EOVERFLOW;
	for (index = 0; index < SWAPZ_IMPORT_DISK_CAPACITY; ++index)
		if (!storage->pins[index].id)
			break;
	if (index == SWAPZ_IMPORT_DISK_CAPACITY)
		return -ENOSPC;
	error = swapz_import_disk_pin(&storage->disk, ticket,
				      &storage->pins[index].view);
	if (error)
		return error;
	storage->pins[index].id = ++storage->next_pin;
	*pin = storage->pins[index].id;
	return 0;
}

static int read_record(struct swapz_original_storage *storage,
	swapz_u64 pin, swapz_u8 *output, swapz_u32 capacity)
{
	struct swapz_original_storage_pin *held = find_pin(storage, pin);
	swapz_u32 completed = 0;
	int index, error;

	if (!held || !output || !isolated(storage->disk.authority) ||
	    capacity < held->view.spec.compressed_length)
		return -EINVAL;
	index = record_index(storage, held->view.ticket);
	if (index < 0 || !storage->decoder[index])
		return -ESTALE;
	error = storage->ops.read(storage->ops.context, held->view.start_block,
				  storage->read_image, SWAPZ_BLOCK_BYTES, &completed);
	if (error)
		return error < 0 ? error : -EIO;
	if (completed != SWAPZ_BLOCK_BYTES)
		return -EIO;
	return swapz_import_disk_read_pinned(&storage->disk, &held->view,
		storage->read_image, completed, output, capacity);
}

int swapz_original_storage_read(struct swapz_original_storage *storage,
	swapz_u64 pin, swapz_u8 *output, swapz_u32 capacity)
{
	if (!outside_owner(storage, output, capacity))
		return -EINVAL;
	return read_record(storage, pin, output, capacity);
}

int swapz_original_storage_put(struct swapz_original_storage *storage,
	swapz_u64 pin)
{
	struct swapz_original_storage_pin *held = find_pin(storage, pin);
	int error;

	if (!held)
		return -ESTALE;
	error = swapz_import_disk_put(&storage->disk, held->view.ticket);
	if (error) {
		storage->faulted = 1;
		return error;
	}
	memset(held, 0, sizeof(*held));
	release_empty(storage);
	return 0;
}

int swapz_original_storage_relocate(struct swapz_original_storage *storage,
	swapz_u64 pin, swapz_u64 next_epoch, swapz_u64 *ticket)
{
	struct swapz_original_storage_pin *held = find_pin(storage, pin);
	struct swapz_authority_import_spec spec;
	struct swapz_original_extent_input input;
	int index, error;

	if (!ready(storage) || !held ||
	    !outside_owner(storage, ticket, sizeof(*ticket)))
		return -EINVAL;
	index = record_index(storage, held->view.ticket);
	if (index < 0 ||
	    storage->disk.records[index].state != SWAPZ_IMPORT_DISK_OWNED ||
	    next_epoch <= held->view.spec.gc_epoch)
		return -ESTALE;
	error = read_record(storage, pin, storage->gc_copy,
			    sizeof(storage->gc_copy));
	if (error)
		return error;
	spec = held->view.spec;
	spec.gc_epoch = next_epoch;
	input = (struct swapz_original_extent_input) {
		.bytes = storage->gc_copy,
		.bytes_available = spec.compressed_length,
		.logical_page = spec.logical_page,
		.generation = held->view.ordinary_generation,
		.length = spec.compressed_length,
		.decoded_length = SWAPZ_BLOCK_BYTES,
		.crc32c = spec.compressed_crc32c,
		.representation = SWAPZ_ORIGINAL_EXTENT_REPRESENTATION,
		.codec = spec.codec,
		.version = spec.codec_version,
	};
	return write_record(storage, &spec, &input, held->view.ticket, ticket);
}

int swapz_original_storage_retire(struct swapz_original_storage *storage,
	swapz_u64 ticket)
{
	int error;

	if (!ready(storage))
		return -EINVAL;
	error = swapz_import_disk_retire(&storage->disk, ticket);
	release_empty(storage);
	return error;
}

int swapz_original_storage_close(struct swapz_original_storage *storage)
{
	int error;

	if (!storage || !isolated(storage->disk.authority))
		return -EINVAL;
	error = swapz_import_disk_close(&storage->disk);
	release_empty(storage);
	return error;
}
#endif
