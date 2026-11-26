// SPDX-License-Identifier: GPL-2.0-only
/* Actual storage/authority joined to the frozen original decoder handles.
 * The lower medium and input provenance are explicitly host models only.
 * No source authentication, physical persistence, kernel load or activation.
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
static struct swapz_tx ordinary;
static struct swapz_original_decoder_handle_owner provider;
static unsigned int checks, gets, puts, read_calls, writes, flushes;
static int fail_flush, fail_write, short_write, fail_read;
static swapz_u64 expected_read_pin;
static unsigned int transient_gets, transient_puts;
static int reading;

#define CHECK(expr) do { ++checks; if (!(expr)) { \
	fprintf(stderr, "SEMANTIC_FAIL line=%d %s\n", __LINE__, #expr); exit(77); \
	} } while (0)

extern int round085_compress(swapz_u8, const swapz_u8 *, swapz_u32,
	swapz_u8 *, swapz_u32, swapz_u32 *);

static unsigned int codec_references(void)
{
	return provider.decoders[0].active_readers + provider.decoders[1].active_readers;
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
	if (reading && !error) {
		CHECK(lease->owner == owner && owner->active_readers == before + 1U);
		++transient_gets;
	}
	return error;
}

int __wrap_swapz_zswap_import_decoder_owner_put(struct swapz_zswap_import_decoder_lease *lease)
{
	struct swapz_zswap_import_decoder_owner *owner = lease->owner;
	unsigned int before = owner ? owner->active_readers : 0U;
	int error = __real_swapz_zswap_import_decoder_owner_put(lease);
	if (reading && !error) {
		CHECK(owner && before && !lease->owner && owner->active_readers == before - 1U);
		++transient_puts;
	}
	return error;
}

static int provider_get(void *context, swapz_u8 codec, swapz_u8 version,
	struct swapz_original_decoder_value_handle *handle)
{
	int error;
	CHECK(context == &storage && !provider.active_reads);
	error = swapz_original_decoder_handle_get(&provider, codec, version, handle);
	if (!error)
		++gets;
	CHECK(provider.active_records == gets - puts &&
		codec_references() == provider.active_records);
	return error;
}

static int provider_put(void *context, const struct swapz_original_decoder_value_handle *handle)
{
	int error;
	CHECK(context == &storage && !provider.active_reads);
	error = swapz_original_decoder_handle_put(&provider, handle);
	if (!error)
		++puts;
	CHECK(provider.active_records == gets - puts &&
		codec_references() == provider.active_records);
	return error;
}

static int provider_read(void *context,
	const struct swapz_original_decoder_value_snapshot *snapshot,
	swapz_u32 ceiling, swapz_u8 *work, swapz_u32 work_capacity,
	swapz_u8 *checked, swapz_u32 checked_capacity,
	swapz_u8 *destination, swapz_u32 destination_capacity)
{
	const struct swapz_shared_original_record *record =
		swapz_shared_original_view(&authority, expected_read_pin);
	unsigned int records = provider.active_records, references = codec_references();
	unsigned int read_gets_before = transient_gets, read_puts_before = transient_puts;
	int error;

	++read_calls;
	CHECK(context == &storage && record && record->pins && records && !provider.active_reads);
	CHECK(references == records && records == gets - puts);
	/* Close must refuse while the record pin holds its exact reference. */
	CHECK(swapz_original_decoder_handles_close(&provider) == -EBUSY);
	reading = 1;
	error = swapz_original_decoder_handle_read(&provider, snapshot, ceiling,
		work, work_capacity, checked, checked_capacity, destination, destination_capacity);
	reading = 0;
	CHECK(transient_gets == read_gets_before + 1U && transient_puts == read_puts_before + 1U);
	CHECK(swapz_shared_original_view(&authority, expected_read_pin) == record);
	CHECK(!provider.active_reads && provider.active_records == records &&
		codec_references() == references && !provider.faulted);
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
	CHECK(!authority.original);
	memset(&provider, 0, sizeof(provider));
	gets = puts = read_calls = writes = flushes = 0;
	transient_gets = transient_puts = 0;
	reading = 0;
	fail_flush = fail_write = short_write = fail_read = 0;
	CHECK(!swapz_original_decoder_handles_init(&provider));
	CHECK(!swapz_authority_init(&authority, maps, live, classes, PAGES, BLOCKS));
	CHECK(!swapz_enable_segment_rotation(&authority, roles, SEGS));
	CHECK(!swapz_enable_segment_mapping_counts(&authority, counts, SEGS));
	CHECK(!swapz_enable_segment_program_counts(&authority, programs, SEGS));
	CHECK(!swapz_enable_segment_page_lists(&authority, first, last, prev, next, SEGS, PAGES));
	CHECK(!swapz_enable_segment_gc_accounting(&authority, live_bytes, costs, min_blocks, SEGS));
	CHECK(!swapz_enable_extent_sequence_index(&authority, delta, bases, SEGS));
	authority.reuse_dead_segments = 1;
	CHECK(!swapz_shared_storage_value_init(&storage, &authority, &ops));
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

static int decode_pin(swapz_u64 pin)
{
	expected_read_pin = pin;
	return swapz_shared_storage_value_decode_pinned(&storage, pin, compressed,
		scratch, verified, decoded, sizeof(decoded));
}

static void verify_decoded(swapz_u64 pin)
{
	memset(decoded, 0xa5, sizeof(decoded));
	CHECK(!decode_pin(pin));
	CHECK(!memcmp(decoded, bytes, sizeof(decoded)));
}

static void exercise(swapz_u8 codec)
{
	swapz_u32 credit = 0, start, victim, index;
	swapz_u64 pin, current_pin, bad_pin;
	struct swapz_shared_storage_value_result snapshot;
	unsigned int calls;

	reset();
	raw(0);
	start = authority.next_block;
	CHECK(!store(0, 2, codec, &credit, 0) && credit);
	CHECK(provider.active_records == 1 && codec_references() == 1 && !writes && !flushes);
	CHECK(!swapz_shared_storage_value_cancel_reserved(&storage, credit));
	CHECK(!provider.active_records && gets == puts && authority.next_block == start);
	CHECK(authority.next_sequence == credit + 1U && !authority.abandoned_blocks);
	CHECK(swapz_shared_storage_value_cancel_reserved(&storage, credit) == -ESTALE);
	raw(0);
	CHECK(!store(0, 3, codec, NULL, 0));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &pin));
	snapshot = swapz_shared_storage_value_read_pinned(&storage, pin, output, sizeof(output));
	CHECK(!snapshot.error && snapshot.snapshot.handle.codec == codec);
	verify_decoded(pin);
	CHECK(provider.active_records == 1 && codec_references() == 1);
	calls = read_calls;
	fail_read = -EIO;
	memset(decoded, 0xa5, sizeof(decoded));
	CHECK(decode_pin(pin) == -EIO && read_calls == calls);
	fail_read = 0;
	for (index = 0; index < sizeof(decoded); ++index)
		CHECK(decoded[index] == 0xa5);

	victim = snapshot.snapshot.map.start_block / SWAPZ_SEGMENT_BLOCKS;
	authority.next_block = (victim + 1U) * SWAPZ_SEGMENT_BLOCKS;
	raw(1);
	CHECK(!swapz_gc_begin_rotation(&authority, victim));
	fail_flush = -EIO;
	CHECK(swapz_shared_storage_value_relocate(&storage, pin, 2) == -EIO);
	CHECK(provider.active_records == 1 && maps[0].generation == 3);
	fail_flush = 0;
	CHECK(!swapz_shared_storage_value_relocate(&storage, pin, 2));
	CHECK(!swapz_shared_storage_value_pin(&storage, 0, &current_pin));
	CHECK(provider.active_records == 2 && maps[0].generation == 4);
	verify_decoded(pin);
	verify_decoded(current_pin);
	CHECK(swapz_gc_commit_rotation(&authority, victim) == -EBUSY);
	CHECK(swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, pin));
	CHECK(provider.active_records == 1 && codec_references() == 1);
	CHECK(!swapz_gc_commit_rotation(&authority, victim));
	calls = read_calls;
	CHECK(decode_pin(pin) == -ESTALE && read_calls == calls);
	raw(0);
	verify_decoded(current_pin);
	CHECK(provider.active_records == 1 && swapz_shared_storage_value_close(&storage) == -EBUSY);
	CHECK(!swapz_shared_storage_value_put(&storage, current_pin));
	CHECK(!provider.active_records && gets == puts);
	discard(0);
	discard(1);

	/* Correct compressed bytes with an intentionally wrong original digest:
	 * the actual decoder acquires/releases its temporary lease but refuses
	 * the decoded page, preserving every output byte. */
	CHECK(!store(2, 1, codec, NULL, 1));
	CHECK(!swapz_shared_storage_value_pin(&storage, 2, &bad_pin));
	memset(decoded, 0xa5, sizeof(decoded));
	calls = read_calls;
	CHECK(decode_pin(bad_pin) == -EBADMSG && read_calls == calls + 1U);
	for (index = 0; index < sizeof(decoded); ++index)
		CHECK(decoded[index] == 0xa5);
	CHECK(provider.active_records == 1 && codec_references() == 1 && !provider.active_reads);
	discard(2);
	CHECK(!swapz_shared_storage_value_put(&storage, bad_pin));
	CHECK(!provider.active_records && !codec_references() && gets == puts);
	CHECK(!swapz_shared_storage_value_close(&storage) && !authority.original);
	CHECK(!swapz_original_decoder_handles_close(&provider));
	printf("PASS ROUND094_AGENT5_REAL codec=%u checks=%u gets=%u puts=%u reads=%u transient_gets=%u transient_puts=%u map=%zu storage=%zu legacy=%zu owner=%zu handle=%zu\n",
		(unsigned int)codec, checks, gets, puts, read_calls, transient_gets, transient_puts,
		sizeof(struct swapz_map),
		sizeof(storage), sizeof(storage.shared), sizeof(provider), sizeof(struct swapz_original_decoder_value_handle));
}

int main(void)
{
	swapz_u32 index;
	CHECK(SWAPZ_SHARED_STORAGE_VALUE_ACTIVE == 0U &&
		SWAPZ_ORIGINAL_DECODER_HANDLES_ACTIVE == 0U && sizeof(struct swapz_map) == 20U);
	for (index = 0; index < sizeof(bytes); ++index)
		bytes[index] = (swapz_u8)((index / 64U) % 7U);
	exercise(1U);
	checks = 0;
	exercise(2U);
	return 0;
}
