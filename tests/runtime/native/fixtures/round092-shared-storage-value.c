// SPDX-License-Identifier: GPL-2.0-only
/* Actual authority/storage with explicit modeled provider and RAM lower I/O.
 * Frozen value ABI only; no decoder implementation, VM, or physical I/O.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zswap-original-storage-value.h"

enum { PAGES = 64, BLOCKS = 2048, SEGS = BLOCKS / SWAPZ_SEGMENT_BLOCKS };
static struct swapz_authority authority;
static struct swapz_map maps[PAGES];
static swapz_u16 live[BLOCKS], min_blocks[SEGS];
static swapz_u8 classes[BLOCKS], roles[SEGS], delta[BLOCKS];
static swapz_u32 counts[SEGS], programs[SEGS], bases[SEGS], first[SEGS], last[SEGS];
static swapz_u32 prev[PAGES], next[PAGES], costs[SEGS], live_bytes[SEGS];
static struct swapz_shared_storage_value storage;
static swapz_u8 media[BLOCKS][SWAPZ_BLOCK_BYTES], bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 output[SWAPZ_BLOCK_BYTES];
static swapz_u8 compressed[SWAPZ_BLOCK_BYTES], scratch[SWAPZ_BLOCK_BYTES];
static swapz_u8 verified[SWAPZ_BLOCK_BYTES], decoded[SWAPZ_BLOCK_BYTES];
static swapz_u64 expected_read_pin;
static unsigned int read_gets, read_puts, active_reads, read_calls;
static int fail_read_acquire, fail_decode;
static struct swapz_tx ordinary;
static struct swapz_original_decoder_value_handle provider[SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS];
static swapz_u64 generations[SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS], epoch;
static struct swapz_original_decoder_value_handle stale;
static unsigned int checks, gets, puts, retained, writes, flushes;
static int fail_flush, fail_write, short_write, fail_read, fail_put, bad_get;

#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); exit(77); \
	} } while (0)

static int same_handle(const struct swapz_original_decoder_value_handle *a,
		       const struct swapz_original_decoder_value_handle *b)
{
	return a->lifecycle_epoch == b->lifecycle_epoch && a->generation == b->generation &&
	       a->slot_index == b->slot_index && a->codec == b->codec && a->version == b->version;
}

static int handle_live(const struct swapz_original_decoder_value_handle *handle)
{
	return handle->generation && handle->slot_index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS &&
	       same_handle(handle, &provider[handle->slot_index]);
}

static int provider_get(void *context, swapz_u8 codec, swapz_u8 version,
			struct swapz_original_decoder_value_handle *handle)
{
	swapz_u32 index;

	CHECK(context == &storage && (codec == 1U || codec == 2U) && version == 1U);
	if (bad_get == 1) {
		*handle = stale;
		return 0;
	}
	if (bad_get == 2) {
		*handle = stale;
		++handle->lifecycle_epoch;
		++handle->generation;
		return 0;
	}
	for (index = 0; index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS; ++index)
		if (!provider[index].generation) {
			provider[index] = (struct swapz_original_decoder_value_handle) {
				.lifecycle_epoch = epoch, .generation = ++generations[index],
				.slot_index = index, .codec = codec, .version = version,
			};
			*handle = provider[index];
			++gets;
			++retained;
			return 0;
		}
	return -ENOSPC;
}

static int provider_put(void *context, const struct swapz_original_decoder_value_handle *handle)
{
	CHECK(context == &storage && retained && handle_live(handle));
	if (fail_put)
		return -EIO;
	stale = *handle;
	memset(&provider[handle->slot_index], 0, sizeof(provider[0]));
	++puts;
	--retained;
	return 0;
}

/* This is a modeled provider, not original codec execution. The separate
 * read reference is acquired from the live borrowed handle and retired
 * before output publication, without touching the record reference. */
static int provider_read(void *context,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *work, swapz_u32 work_capacity,
	swapz_u8 *checked, swapz_u32 checked_capacity,
	swapz_u8 *destination, swapz_u32 destination_capacity)
{
	const struct swapz_shared_original_record *record =
		swapz_shared_original_view(&authority, expected_read_pin);
	unsigned int prior_gets = gets, prior_puts = puts, prior_retained = retained;
	int error;

	++read_calls;
	CHECK(context == &storage && record && record->pins && !active_reads);
	CHECK(handle_live(&snapshot->handle) && snapshot->record.codec == snapshot->handle.codec);
	CHECK(snapshot->record.version == snapshot->handle.version);
	CHECK(snapshot->record.compressed_length == record->spec.compressed_length);
	CHECK(snapshot->record.compressed_crc32c == record->spec.compressed_crc32c);
	CHECK(!memcmp(snapshot->record.original_sha256, record->spec.original_sha256,
		sizeof(snapshot->record.original_sha256)));
	CHECK(snapshot->record.decoded_length == SWAPZ_BLOCK_BYTES &&
		snapshot->record.representation == 0x5a && !snapshot->record.dictionary_id);
	CHECK(snapshot->compressed_bytes == compressed &&
		snapshot->compressed_capacity == record->spec.compressed_length);
	CHECK(!memcmp(snapshot->compressed_bytes, bytes, snapshot->compressed_capacity));
	CHECK(ceiling == SWAPZ_ORIGINAL_DECODE_M3568 &&
		work == scratch && checked == verified && destination == decoded &&
		work_capacity == SWAPZ_BLOCK_BYTES && checked_capacity == SWAPZ_BLOCK_BYTES &&
		destination_capacity == SWAPZ_BLOCK_BYTES);
	if (fail_read_acquire)
		return fail_read_acquire;
	++read_gets;
	++active_reads;
	CHECK(active_reads == 1 && retained == prior_retained && retained != 0);
	/* Model the provider's distinct acquired-read lifetime and close gate.
	 * The storage owner is serialized: no reentrant authority mutation. */
	memset(work, 0x42, work_capacity);
	memset(checked, 0x73, checked_capacity);
	error = fail_decode;
	CHECK(active_reads == 1 && swapz_shared_original_view(&authority, expected_read_pin) == record);
	CHECK(handle_live(&snapshot->handle) && gets == prior_gets && puts == prior_puts);
	++read_puts;
	--active_reads;
	if (!error)
		memcpy(destination, checked, destination_capacity);
	return error;
}

static int write_lower(void *context, swapz_u32 start, const swapz_u8 *image,
		       swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS && authority.in_flight && !live[start]);
	CHECK(!authority.shared_unissued_sequence && length == SWAPZ_BLOCK_BYTES);
	++writes;
	memcpy(media[start], image, length);
	*completed = short_write ? length - 1U : length;
	return fail_write;
}

static int flush_lower(void *context)
{
	CHECK(context == &storage && authority.in_flight);
	++flushes;
	return fail_flush;
}

static int read_lower(void *context, swapz_u32 start, swapz_u8 *image,
		      swapz_u32 length, swapz_u32 *completed)
{
	CHECK(context == &storage && start < BLOCKS && length == SWAPZ_BLOCK_BYTES);
	if (fail_read)
		return fail_read;
	memcpy(image, media[start], length);
	*completed = length;
	return 0;
}

static const struct swapz_shared_storage_value_ops ops = {
	.context = &storage, .write = write_lower, .flush = flush_lower,
	.read = read_lower, .decoder_get = provider_get, .decoder_put = provider_put,
	.decoder_read = provider_read,
};

static void reset(void)
{
	CHECK(!retained && gets == puts && !authority.original);
	CHECK(!swapz_authority_init(&authority, maps, live, classes, PAGES, BLOCKS));
	CHECK(!swapz_enable_segment_rotation(&authority, roles, SEGS));
	CHECK(!swapz_enable_segment_mapping_counts(&authority, counts, SEGS));
	CHECK(!swapz_enable_segment_program_counts(&authority, programs, SEGS));
	CHECK(!swapz_enable_segment_page_lists(&authority, first, last, prev, next, SEGS, PAGES));
	CHECK(!swapz_enable_segment_gc_accounting(&authority, live_bytes, costs, min_blocks, SEGS));
	CHECK(!swapz_enable_extent_sequence_index(&authority, delta, bases, SEGS));
	authority.reuse_dead_segments = 1;
	++epoch;
	CHECK(!swapz_shared_storage_value_init(&storage, &authority, &ops));
	gets = puts = writes = flushes = 0;
	read_gets = read_puts = active_reads = read_calls = 0;
	fail_read_acquire = fail_decode = 0;
	fail_write = fail_flush = short_write = fail_read = fail_put = bad_get = 0;
}

static int store(swapz_u32 page, swapz_u32 generation, swapz_u8 codec, swapz_u32 *credit)
{
	struct swapz_authority_import_spec spec = {
		.source_swap_slot = page, .source_entry_identity = 17,
		.source_store_generation = 3, .gc_epoch = 1, .logical_page = page,
		.compressed_length = 321, .codec = codec, .codec_version = 1,
		.requested_fua = 1, .original_sha256 = {0x51},
	};
	struct swapz_original_extent_input input = {
		.bytes = bytes, .bytes_available = 321, .logical_page = page,
		.generation = generation, .length = 321, .decoded_length = SWAPZ_BLOCK_BYTES,
		.representation = 0x5a, .codec = codec, .version = 1,
	};

	spec.compressed_crc32c = swapz_crc32c_bytes(bytes, 321);
	input.crc32c = spec.compressed_crc32c;
	return credit ? swapz_shared_storage_value_reserve(&storage, &spec, &input, credit) :
		swapz_shared_storage_value_write(&storage, &spec, &input);
}

static void raw(swapz_u32 page)
{
	CHECK(!swapz_stage(&authority, &page, 1U, 1U, &ordinary));
	CHECK(!swapz_finish_raw(&authority, &ordinary, bytes, 1U, 0));
}

static void discard(swapz_u32 page)
{
	CHECK(!swapz_prevalidate_discard_range(&authority, page, 1));
	CHECK(!swapz_discard_page(&authority, page));
}

static void clean_close(void)
{
	CHECK(!retained && gets == puts);
	CHECK(!active_reads && read_gets == read_puts);
	CHECK(!swapz_shared_storage_value_close(&storage));
	CHECK(!authority.original);
}

static struct swapz_shared_storage_value_snapshot read_pin(swapz_u64 pin)
{
	struct swapz_shared_storage_value_result result =
		swapz_shared_storage_value_read_pinned(&storage, pin, output, sizeof(output));

	CHECK(!result.error && !memcmp(output, bytes, 321));
	CHECK(handle_live(&result.snapshot.handle));
	CHECK(result.snapshot.spec.compressed_length == 321U);
	CHECK(result.snapshot.spec.codec == result.snapshot.handle.codec);
	CHECK(result.snapshot.spec.codec_version == result.snapshot.handle.version);
	return result.snapshot;
}

static void cancel_and_failures(void)
{
	struct swapz_map old;
	swapz_u32 credit = 0, refused = 0x1234U, start, mode;

	reset();
	raw(0);
	old = maps[0];
	start = authority.next_block;
	CHECK(store(0, 2, 2, &storage.slots[0].handle.slot_index) == -EINVAL);
	CHECK(!retained && !authority.in_flight && authority.next_block == start);
	CHECK(!store(0, 2, 2, &credit) && credit);
	CHECK(retained == 1 && !writes && !flushes && authority.shared_unissued_sequence == credit);
	CHECK(swapz_shared_storage_value_cancel_reserved(&storage, credit + 1U) == -ESTALE);
	CHECK(swapz_shared_storage_value_commit_reserved(&storage, credit + 1U) == -ESTALE);
	CHECK(swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_cancel_reserved(&storage, credit));
	CHECK(!retained && gets == puts && authority.next_block == start);
	CHECK(!authority.in_flight && !authority.abandoned_blocks && authority.next_sequence == credit + 1U);
	CHECK(!memcmp(&old, &maps[0], sizeof(old)));
	CHECK(swapz_shared_storage_value_cancel_reserved(&storage, credit) == -ESTALE);
	CHECK(store(0, 2, 2, &refused) == -EAGAIN && refused == 0x1234U);
	raw(0);
	old = maps[0];
	for (mode = 0; mode < 3U; ++mode) {
		start = authority.next_block;
		CHECK(!store(0, 3, 2, &credit));
		fail_write = mode == 0 ? -EIO : 0;
		short_write = mode == 1;
		fail_flush = mode == 2 ? -EIO : 0;
		CHECK(swapz_shared_storage_value_commit_reserved(&storage, credit) == -EIO);
		CHECK(!retained && gets == puts && !authority.in_flight);
		CHECK(authority.next_block == start + 1U && authority.abandoned_blocks == mode + 1U);
		CHECK(!memcmp(&old, &maps[0], sizeof(old)));
		CHECK(swapz_shared_storage_value_cancel_reserved(&storage, credit) == -ESTALE);
	}
	discard(0);
	clean_close();
}

static void pinned_overwrite_and_aba(void)
{
	struct swapz_shared_storage_value_snapshot old, second, replacement;
	struct swapz_shared_storage_value_result failed;
	swapz_u64 pin, duplicate, next_pin;

	reset();
	CHECK(!store(0, 1, 1, NULL));
	CHECK(swapz_shared_storage_value_pin(&storage, 0, &storage.lifecycle_epoch) == -EINVAL);
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &pin));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &duplicate));
	failed = swapz_shared_storage_value_read_pinned(&storage, pin,
		storage.shared.read_image, sizeof(storage.shared.read_image));
	CHECK(failed.error == -EINVAL && !failed.snapshot.handle.generation);
	old = read_pin(pin);
	second = read_pin(duplicate);
	CHECK(same_handle(&old.handle, &second.handle) && gets == 1 && retained == 1);
	CHECK(old.map.generation == 1 && old.sequence);
	memset(output, 0xa5, sizeof(output));
	fail_read = -EIO;
	failed = swapz_shared_storage_value_read_pinned(&storage, pin, output, sizeof(output));
	CHECK(failed.error == -EIO && !failed.snapshot.handle.generation && output[0] == 0xa5U);
	fail_read = 0;
	media[old.map.start_block][0] ^= 1U;
	failed = swapz_shared_storage_value_read_pinned(&storage, pin, output, sizeof(output));
	CHECK(failed.error == -EBADMSG && !failed.snapshot.handle.generation && output[0] == 0xa5U);
	media[old.map.start_block][0] ^= 1U;
	raw(0);
	CHECK(retained == 1 && handle_live(&old.handle));
	second = read_pin(pin);
	CHECK(same_handle(&old.handle, &second.handle) && second.map.generation == 1);
	CHECK(!swapz_shared_storage_value_put(&storage, pin) && retained == 1);
	CHECK(swapz_shared_storage_value_put(&storage, pin) == -ESTALE);
	CHECK(!swapz_shared_storage_value_put(&storage, duplicate) && !retained);
	CHECK(!handle_live(&old.handle));
	CHECK(!store(0, 3, 2, NULL));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &next_pin));
	replacement = read_pin(next_pin);
	CHECK(replacement.handle.slot_index == old.handle.slot_index);
	CHECK(replacement.handle.generation > old.handle.generation && !handle_live(&old.handle));
	CHECK(replacement.handle.lifecycle_epoch == old.handle.lifecycle_epoch);
	memset(output, 0x5a, sizeof(output));
	failed = swapz_shared_storage_value_read_pinned(&storage, duplicate, output, sizeof(output));
	CHECK(failed.error == -ESTALE && !failed.snapshot.handle.generation && output[0] == 0x5aU);
	discard(0);
	CHECK(retained == 1 && swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, next_pin));
	clean_close();
}

static void relocate(void)
{
	struct swapz_shared_storage_value_snapshot old, relocated, again;
	swapz_u32 victim;
	swapz_u64 pin, new_pin;

	reset();
	CHECK(!store(0, 1, 2, NULL));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &pin));
	old = read_pin(pin);
	victim = old.map.start_block / SWAPZ_SEGMENT_BLOCKS;
	authority.next_block = (victim + 1U) * SWAPZ_SEGMENT_BLOCKS;
	raw(1);
	CHECK(!swapz_gc_begin_rotation(&authority, victim));
	fail_flush = -EIO;
	CHECK(swapz_shared_storage_value_relocate(&storage, pin, 2) == -EIO);
	CHECK(retained == 1 && handle_live(&old.handle) && maps[0].generation == 1);
	fail_flush = 0;
	CHECK(!swapz_shared_storage_value_relocate(&storage, pin, 2));
	CHECK(retained == 2 && maps[0].generation == 2 && handle_live(&old.handle));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &new_pin));
	relocated = read_pin(new_pin);
	again = read_pin(pin);
	CHECK(!same_handle(&relocated.handle, &old.handle));
	CHECK(same_handle(&again.handle, &old.handle) && again.map.generation == 1);
	CHECK(relocated.spec.gc_epoch == 2 && relocated.map.generation == 2);
	CHECK(swapz_gc_commit_rotation(&authority, victim) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, pin) && retained == 1);
	CHECK(!handle_live(&old.handle));
	CHECK(!swapz_gc_commit_rotation(&authority, victim));
	discard(0);
	CHECK(retained == 1);
	CHECK(!swapz_shared_storage_value_put(&storage, new_pin));
	discard(1);
	clean_close();
}

static int decode_pin(swapz_u64 pin)
{
	expected_read_pin = pin;
	return swapz_shared_storage_value_decode_pinned(&storage, pin, compressed,
		scratch, verified, decoded, sizeof(decoded));
}

static void transient_read_lifetime(void)
{
	struct swapz_shared_storage_value_ops missing_read = ops;
	swapz_u64 pin, current_pin;
	swapz_u32 index, victim;
	unsigned int retained_before, calls_before;
	struct swapz_shared_storage_value_snapshot old;

	reset();
	missing_read.decoder_read = NULL;
	CHECK(swapz_shared_storage_value_init(&storage, &authority, &missing_read) == -EINVAL);
	CHECK(!store(0, 1, 1, NULL));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &pin));
	old = read_pin(pin);
	CHECK(!decode_pin(pin) && read_gets == 1 && read_puts == 1 && !active_reads);
	for (index = 0; index < sizeof(decoded); ++index)
		CHECK(decoded[index] == 0x73);
	CHECK(gets == 1 && !puts && retained == 1);
	memset(decoded, 0xa5, sizeof(decoded));
	fail_read_acquire = -ESHUTDOWN;
	CHECK(decode_pin(pin) == -ESHUTDOWN && read_gets == 1 && read_puts == 1);
	fail_read_acquire = 0;
	fail_decode = -EBADMSG;
	CHECK(decode_pin(pin) == -EBADMSG && read_gets == 2 && read_puts == 2 && !active_reads);
	fail_decode = 0;
	for (index = 0; index < sizeof(decoded); ++index)
		CHECK(decoded[index] == 0xa5);
	calls_before = read_calls;
	fail_read = -EIO;
	CHECK(decode_pin(pin) == -EIO && read_calls == calls_before);
	fail_read = 0;
	CHECK(swapz_shared_storage_value_decode_pinned(&storage, pin, compressed,
		scratch, verified, verified, sizeof(decoded)) == -EINVAL);
	CHECK(swapz_shared_storage_value_decode_pinned(&storage, pin, compressed,
		scratch, verified, decoded, sizeof(decoded) - 1U) == -EINVAL);
	CHECK(swapz_shared_storage_value_decode_pinned(&storage, pin, compressed,
		scratch, verified, storage.shared.read_image, sizeof(decoded)) == -EINVAL);
	CHECK(read_calls == calls_before);

	/* Relocate a live record, then read the retired original under its
	 * exact old pin; temporary reads must not release either record. */
	victim = old.map.start_block / SWAPZ_SEGMENT_BLOCKS;
	authority.next_block = (victim + 1U) * SWAPZ_SEGMENT_BLOCKS;
	raw(1);
	CHECK(!swapz_gc_begin_rotation(&authority, victim));
	CHECK(!swapz_shared_storage_value_relocate(&storage, pin, 2));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &current_pin));
	retained_before = retained;
	CHECK(retained_before == 2 && !decode_pin(pin) && !decode_pin(current_pin));
	CHECK(retained == retained_before && read_gets == 4 && read_puts == 4 && !active_reads);
	CHECK(swapz_gc_commit_rotation(&authority, victim) == -EBUSY);
	CHECK(swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, pin) && retained == 1);
	CHECK(!swapz_gc_commit_rotation(&authority, victim));
	calls_before = read_calls;
	CHECK(decode_pin(pin) == -ESTALE && read_calls == calls_before);
	discard(0);
	CHECK(!decode_pin(current_pin) && retained == 1 && read_gets == 5 && read_puts == 5);
	CHECK(swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, current_pin) && !retained);
	discard(1);
	clean_close();
}

static void exhaustion(void)
{
	struct swapz_original_decoder_value_handle external[SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS];
	swapz_u32 index, credit = 0x1234U, before_gets, start;

	reset();
	raw(0);
	start = authority.next_block;
	for (index = 0; index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS; ++index)
		CHECK(!provider_get(&storage, 1, 1, &external[index]));
	CHECK(store(0, 2, 2, &credit) == -ENOSPC && credit == 0x1234U);
	CHECK(!authority.in_flight && authority.next_block == start && !writes && !flushes);
	for (index = 0; index < SWAPZ_ORIGINAL_DECODER_HANDLE_SLOTS; ++index)
		CHECK(!provider_put(&storage, &external[index]));
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		CHECK(!store(index + 1U, 1, 2, NULL));
	before_gets = gets;
	start = authority.next_block;
	CHECK(store(0, 2, 2, &credit) == -ENOSPC && credit == 0x1234U);
	CHECK(gets == before_gets && authority.next_block == start && !authority.in_flight);
	CHECK(retained == SWAPZ_SHARED_ORIGINAL_CAPACITY);
	for (index = 0; index < SWAPZ_SHARED_ORIGINAL_CAPACITY; ++index)
		discard(index + 1U);
	discard(0);
	clean_close();
}

static void provider_fault(int mode)
{
	swapz_u32 credit = 0x1234U, before_puts;
	swapz_u64 pin;

	reset();
	CHECK(!store(0, 1, 2, NULL));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &pin));
	if (mode == 3) {
		fail_put = 1;
		discard(0);
		CHECK(!swapz_shared_storage_value_put(&storage, pin));
		CHECK(retained == 1 && storage.faulted);
	} else {
		CHECK(!swapz_shared_storage_value_put(&storage, pin));
		discard(0);
		CHECK(!retained && gets == puts);
		before_puts = puts;
		bad_get = mode;
		CHECK(store(0, 3, 2, NULL) == -EUCLEAN && !authority.in_flight);
		CHECK(puts == before_puts && storage.faulted && !maps[0].valid);
	}
	CHECK(swapz_shared_storage_value_close(&storage) == -EUCLEAN);
	CHECK(store(1, 1, 2, &credit) == -EUCLEAN && credit == 0x1234U);
	CHECK(authority.original == &storage.shared.owner);
}

int main(int argc, char **argv)
{
	swapz_u32 index;

	for (index = 0; index < sizeof(bytes); ++index)
		bytes[index] = (swapz_u8)(index * 13U + 7U);
	CHECK(sizeof(struct swapz_map) == 20U && SWAPZ_SHARED_STORAGE_VALUE_ACTIVE == 0U);
	if (argc == 1) {
		cancel_and_failures();
		pinned_overwrite_and_aba();
		relocate();
		transient_read_lifetime();
		exhaustion();
	} else {
		CHECK(argc == 2 && strlen(argv[1]) == 1U && argv[1][0] >= '1' && argv[1][0] <= '3');
		provider_fault(argv[1][0] - '0');
	}
	printf("PASS ROUND093_AGENT5 checks=%u storage_bytes=%zu legacy_bytes=%zu map_bytes=%zu sidecar_bytes=%zu slot_bytes=%zu handle_bytes=%zu\n",
	       checks, sizeof(storage), sizeof(storage.shared), sizeof(struct swapz_map),
	       sizeof(storage.shared.owner), sizeof(storage.slots[0]), sizeof(storage.slots[0].handle));
	return 0;
}
