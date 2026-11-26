// SPDX-License-Identifier: GPL-2.0-only
/* Actual storage/authority joined to the frozen shared decoder provider.
 * The lower medium and input provenance are explicitly host models only.
 * No source authentication, physical persistence, kernel load or activation.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zswap-original-storage-shared-decoder.h"

enum { PAGES = 64, BLOCKS = 2048, SEGS = BLOCKS / SWAPZ_SEGMENT_BLOCKS };
static struct swapz_authority authority;
static struct swapz_map maps[PAGES];
static swapz_u16 live[BLOCKS], min_blocks[SEGS];
static swapz_u8 classes[BLOCKS], roles[SEGS], delta[BLOCKS];
static swapz_u32 counts[SEGS], programs[SEGS], bases[SEGS], first[SEGS], last[SEGS];
static swapz_u32 prev[PAGES], next[PAGES], costs[SEGS], live_bytes[SEGS];
static struct swapz_shared_storage_decoder storage;
static swapz_u8 media[BLOCKS][SWAPZ_BLOCK_BYTES], bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 compressed[SWAPZ_BLOCK_BYTES], scratch[SWAPZ_BLOCK_BYTES];
static swapz_u8 verified[SWAPZ_BLOCK_BYTES], decoded[SWAPZ_BLOCK_BYTES];
static struct swapz_tx ordinary;
static unsigned int checks, lifecycle_gets, lifecycle_puts, lower_reads, writes, flushes;
static int fail_flush, fail_write, short_write, fail_read;
static swapz_u64 expected_read_pin, host_epoch;
static unsigned int transient_gets, transient_puts;
static int reading;

#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); exit(77); \
	} } while (0)

extern int round085_compress(swapz_u8, const swapz_u8 *, swapz_u32,
	swapz_u8 *, swapz_u32, swapz_u32 *);

static unsigned int codec_references(void)
{
	return storage.provider.providers[0].active_readers + storage.provider.providers[1].active_readers;
}

/* GNU ld wrappers observe real calls, never substitute ownership or decode.
 * Only calls inside the synchronous storage read are counted as transient. */
extern int __real_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *, struct swapz_zswap_import_decoder_lease *);
extern int __real_swapz_zswap_import_decoder_owner_put(struct swapz_zswap_import_decoder_lease *);

int __wrap_swapz_zswap_import_decoder_owner_get(
	struct swapz_zswap_import_decoder_owner *owner, struct swapz_zswap_import_decoder_lease *lease)
{
	unsigned int before = owner->active_readers;
	int error = __real_swapz_zswap_import_decoder_owner_get(owner, lease);
	if (!error) {
		CHECK(lease->owner == owner && owner->active_readers == before + 1U);
		if (reading) {
			CHECK(swapz_shared_original_view(&authority, expected_read_pin));
			++transient_gets;
		} else
			++lifecycle_gets;
	}
	return error;
}

int __wrap_swapz_zswap_import_decoder_owner_put(struct swapz_zswap_import_decoder_lease *lease)
{
	struct swapz_zswap_import_decoder_owner *owner = lease->owner;
	unsigned int before = owner ? owner->active_readers : 0U;
	int error = __real_swapz_zswap_import_decoder_owner_put(lease);
	if (!error) {
		CHECK(owner && before && !lease->owner && owner->active_readers == before - 1U);
		if (reading) {
			CHECK(swapz_shared_original_view(&authority, expected_read_pin));
			++transient_puts;
		} else
			++lifecycle_puts;
	}
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
	++lower_reads;
	if (fail_read)
		return fail_read;
	memcpy(image, media[start], length);
	*completed = length;
	return 0;
}

/* Host-only epoch authority lives outside each fresh wrapper. */
static int reserve_epoch(void *context, swapz_u64 *epoch)
{
	CHECK(context == &storage);
	if (host_epoch >= ~(swapz_u64)0 - 1U)
		return -EOVERFLOW;
	*epoch = ++host_epoch;
	return 0;
}

static const struct swapz_shared_storage_decoder_ops ops = {
	.context = &storage, .write = write_lower, .flush = flush_lower,
	.read = read_lower, .reserve_epoch = reserve_epoch,
};

static void reset(void)
{
	CHECK(!authority.original);
	memset(&storage, 0, sizeof(storage));
	lifecycle_gets = lifecycle_puts = lower_reads = writes = flushes = 0;
	transient_gets = transient_puts = 0;
	reading = 0;
	fail_flush = fail_write = short_write = fail_read = 0;
	CHECK(!swapz_authority_init(&authority, maps, live, classes, PAGES, BLOCKS));
	CHECK(!swapz_enable_segment_rotation(&authority, roles, SEGS));
	CHECK(!swapz_enable_segment_mapping_counts(&authority, counts, SEGS));
	CHECK(!swapz_enable_segment_program_counts(&authority, programs, SEGS));
	CHECK(!swapz_enable_segment_page_lists(&authority, first, last, prev, next, SEGS, PAGES));
	CHECK(!swapz_enable_segment_gc_accounting(&authority, live_bytes, costs, min_blocks, SEGS));
	CHECK(!swapz_enable_extent_sequence_index(&authority, delta, bases, SEGS));
	authority.reuse_dead_segments = 1;
	CHECK(!swapz_shared_storage_decoder_init(&storage, &authority, &ops));
	CHECK(storage.epoch == host_epoch && lifecycle_gets == 2 && codec_references() == 2);
}

static int store(swapz_u32 page, swapz_u32 generation, swapz_u8 codec,
	swapz_u32 *credit, int bad_digest)
{
	static swapz_u8 sealed[SWAPZ_BLOCK_BYTES];
	swapz_u32 written = 0;
	struct swapz_authority_import_spec spec = {
		.source_swap_slot = page, .source_entry_identity = 17,
		.source_store_generation = 3, .gc_epoch = 1, .logical_page = page,
		.codec = codec, .codec_version = 1, .requested_fua = 1,
	};
	struct swapz_original_extent_input input = {
		.bytes = sealed, .logical_page = page, .generation = generation,
		.decoded_length = SWAPZ_BLOCK_BYTES, .representation = 0x5a,
		.codec = codec, .version = 1,
	};

	CHECK(!round085_compress(codec, bytes, sizeof(bytes), sealed, sizeof(sealed), &written));
	CHECK(written && written <= SWAPZ_ORIGINAL_DECODE_M3568);
	CHECK(!swapz_zswap_import_sha256(bytes, spec.original_sha256));
	if (bad_digest)
		spec.original_sha256[0] ^= 1U;
	spec.compressed_length = (swapz_u16)written;
	spec.compressed_crc32c = swapz_crc32c_bytes(sealed, written);
	input.bytes_available = written;
	input.length = written;
	input.crc32c = spec.compressed_crc32c;
	return credit ? swapz_shared_storage_reserve(&storage.storage, &spec, &input, credit) :
		swapz_shared_storage_write(&storage.storage, &spec, &input);
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

static int decode_pin(swapz_u64 pin)
{
	int error;
	expected_read_pin = pin;
	reading = 1;
	error = swapz_shared_storage_decoder_read(&storage, storage.epoch, pin, compressed,
		scratch, verified, decoded, sizeof(decoded));
	reading = 0;
	CHECK(!storage.scoped_pin && !storage.scoped_bytes && !storage.provider.active_reads);
	CHECK(codec_references() == 2 && lifecycle_gets == 2 && !lifecycle_puts);
	return error;
}

static void verify_decoded(swapz_u64 pin)
{
	const struct swapz_shared_original_record *record =
		swapz_shared_original_view(&authority, pin);
	unsigned int before = lower_reads, previous_gets = transient_gets;
	CHECK(record && record->decoder == &storage);
	memset(decoded, 0xa5, sizeof(decoded));
	CHECK(!decode_pin(pin));
	CHECK(lower_reads == before + 1U && transient_gets == previous_gets + 1U &&
		transient_gets == transient_puts);
	CHECK(!memcmp(decoded, bytes, sizeof(decoded)));
	CHECK(!memcmp(compressed, media[record->map.start_block], record->spec.compressed_length));
	CHECK(swapz_shared_original_view(&authority, pin) == record);
}

static void unchanged(void)
{
	swapz_u32 index;
	for (index = 0; index < sizeof(decoded); ++index)
		CHECK(decoded[index] == 0xa5);
}

static void exercise(swapz_u8 codec)
{
	swapz_u64 old_pin, new_pin, other_pin, bad_pin;
	swapz_u32 credit = 0, start, victim, old_sequence, new_sequence;
	unsigned int before, previous_gets;
	const struct swapz_shared_original_record *record;

	reset();
	raw(0);
	start = authority.next_block;
	CHECK(!store(0, 2, codec, &credit, 0));
	CHECK(!swapz_shared_storage_cancel_reserved(&storage.storage, credit));
	CHECK(authority.next_block == start && authority.next_sequence == credit + 1U);
	CHECK(!writes && !flushes && lifecycle_gets == 2 && !lifecycle_puts);
	raw(0);
	CHECK(!store(0, 3, codec, NULL, 0));
	CHECK(!swapz_shared_original_pin(&authority, 0, &old_pin));
	record = swapz_shared_original_view(&authority, old_pin);
	CHECK(record && record->sequence > credit);
	if (storage.epoch > 1U) {
		before = lower_reads;
		memset(decoded, 0xa5, sizeof(decoded));
		CHECK(swapz_shared_storage_decoder_read(&storage, storage.epoch - 1U,
			old_pin, compressed, scratch, verified, decoded, sizeof(decoded)) == -ESTALE);
		CHECK(lower_reads == before);
		unchanged();
	}
	old_sequence = record->sequence;
	victim = record->map.start_block / SWAPZ_SEGMENT_BLOCKS;
	verify_decoded(old_pin);
	/* Another real codec uses the same shared lifetime; no per-record lease. */
	authority.next_block = (victim + 1U) * SWAPZ_SEGMENT_BLOCKS;
	CHECK(!store(1, 1, (swapz_u8)(3U - codec), NULL, 0));
	CHECK(!swapz_shared_original_pin(&authority, 1, &other_pin));
	verify_decoded(other_pin);
	CHECK(!swapz_shared_original_put(&authority, other_pin));
	CHECK(!swapz_gc_begin_rotation(&authority, victim));
	fail_flush = -EIO;
	CHECK(swapz_shared_storage_relocate(&storage.storage, old_pin, 2) == -EIO);
	CHECK(maps[0].generation == 3 && lifecycle_gets == 2);
	fail_flush = 0;
	CHECK(!swapz_shared_storage_relocate(&storage.storage, old_pin, 2));
	CHECK(!swapz_shared_original_pin(&authority, 0, &new_pin));
	record = swapz_shared_original_view(&authority, new_pin);
	CHECK(record && record->sequence > old_sequence && maps[0].generation == 4);
	new_sequence = record->sequence;
	verify_decoded(old_pin);
	verify_decoded(new_pin);
	CHECK(swapz_gc_commit_rotation(&authority, victim) == -EBUSY);
	CHECK(!swapz_shared_original_put(&authority, old_pin));
	CHECK(!swapz_gc_commit_rotation(&authority, victim));
	before = lower_reads;
	memset(decoded, 0xa5, sizeof(decoded));
	CHECK(decode_pin(old_pin) == -ESTALE && lower_reads == before);
	unchanged();
	raw(0);
	verify_decoded(new_pin);
	CHECK(swapz_shared_storage_decoder_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_original_put(&authority, new_pin));
	CHECK(swapz_shared_original_put(&authority, new_pin) == -ESTALE);
	discard(0);
	discard(1);

	/* Same slot reused with a newer sequence; failure leaves full output unchanged. */
	CHECK(!store(2, 1, codec, NULL, 1));
	CHECK(!swapz_shared_original_pin(&authority, 2, &bad_pin));
	record = swapz_shared_original_view(&authority, bad_pin);
	CHECK(record && record->sequence > new_sequence);
	before = lower_reads;
	previous_gets = transient_gets;
	memset(decoded, 0xa5, sizeof(decoded));
	CHECK(decode_pin(bad_pin) == -EBADMSG && lower_reads == before + 1U);
	CHECK(transient_gets == previous_gets + 1U && transient_gets == transient_puts);
	unchanged();
	fail_read = -EIO;
	before = lower_reads;
	previous_gets = transient_gets;
	CHECK(decode_pin(bad_pin) == -EIO && lower_reads == before + 1U &&
		transient_gets == previous_gets);
	unchanged();
	fail_read = 0;
	before = lower_reads;
	CHECK(swapz_shared_storage_decoder_read(&storage, storage.epoch, bad_pin, compressed,
		scratch, verified, verified, sizeof(decoded)) == -EINVAL && lower_reads == before);
	discard(2);
	CHECK(!swapz_shared_original_put(&authority, bad_pin));
	/* Nonwrapping allocator identity is authoritative, no decoder generation table. */
	authority.next_sequence = ~(swapz_u32)0;
	before = writes;
	CHECK(store(3, 1, codec, NULL, 0) != 0 && writes == before && !authority.in_flight);
	maps[3].generation = ~(swapz_u32)0;
	CHECK(store(3, 0, codec, NULL, 0) == -EOVERFLOW && writes == before);
	CHECK(!swapz_shared_storage_decoder_close(&storage) && !authority.original);
	CHECK(lifecycle_gets == 2 && lifecycle_puts == 2 && !codec_references());
	CHECK(transient_gets == 6 && transient_puts == 6);
	printf("PASS ROUND095_AGENT5 codec=%u checks=%u lower_reads=%u lifetime_gets=%u lifetime_puts=%u transient_gets=%u transient_puts=%u map=%zu storage=%zu legacy=%zu provider=%zu sidecar=%zu handle=%zu\n",
		(unsigned int)codec, checks, lower_reads, lifecycle_gets, lifecycle_puts,
		transient_gets, transient_puts, sizeof(struct swapz_map), sizeof(storage),
		sizeof(storage.storage), sizeof(storage.provider), sizeof(storage.storage.owner),
		sizeof(struct swapz_original_decoder_value_handle));
}

int main(void)
{
	swapz_u32 index;
	CHECK(SWAPZ_SHARED_STORAGE_DECODER_ACTIVE == 0U && SWAPZ_ORIGINAL_DECODER_SHARED_ACTIVE == 0U);
	for (index = 0; index < sizeof(bytes); ++index)
		bytes[index] = (swapz_u8)((index / 32U) % 11U);
	exercise(1U);
	checks = 0;
	exercise(2U);
	CHECK(host_epoch == 2);
	return 0;
}
