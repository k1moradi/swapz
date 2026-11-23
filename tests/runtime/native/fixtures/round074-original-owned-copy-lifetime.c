// SPDX-License-Identifier: GPL-2.0-only
/*
 * Round074 Agent5: host-only compressed original-source ownership lifetime.
 * Actual src/kernel/authority.c and codec.c are separately linked unmodified.
 * The inherited genuine original-profile LZO1X/LZ4 host harness is included
 * solely for its original codec producer, product allocator and lower reader.
 *
 * The synthetic lease, BIO queue and lower RAM storage are models. There is
 * NO authenticated zswap STORED swapcache entry, real Linux bio_endio, FUA,
 * selected upper ACK or physical device. This program is single-thread-owned
 * and serializes all transitions; it makes no concurrent production claim.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define main swapz_round067_inherited_main
#include "round067-import-disk-payload-read.c"
#undef main

_Static_assert(SWAPZ_IMPORT_DISK_ACTIVE == 0U, "real authority gate activated");
_Static_assert(SWAPZ_ZSWAP_IMPORT_ACTIVE == 0U, "original source gate activated");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "ordinary RAW_4096 changed");
_Static_assert(sizeof(struct swapz_map) == 20U, "volatile map ABI changed");

/* The mutable source pointer is NEVER stored in this owned descriptor.
 * The caller must already hold the *modeled* source or GC read lease.
 * Only the exact compressed bytes and original identity are retained. */
struct round074_owned_source {
	swapz_u8 bytes[SWAPZ_MAX_COMPRESSED];
	swapz_u32 length;
	swapz_u32 compressed_crc32c;
	swapz_u64 store_generation;
	swapz_u8 codec;
	swapz_u8 codec_version;
	bool owns_bytes;
};

/* The independently owned BIO bvec payload is represented here as an
 * inline contiguous private extent, not a Linux struct bio. Memory backs
 * only the test model; the actual product authority validates completion. */
struct round074_queued_bio {
	swapz_u8 bytes[SWAPZ_MAX_EXTENT_BYTES];
	swapz_u32 compressed_length;
	swapz_u32 extent_bytes;
	bool complete;
};

#define ROUND074_CHECK(condition) do { \
	if (!(condition)) { \
		fprintf(stderr, "ROUND074_FIRST_ERROR case=%s line=%d predicate=%s\n", \
			case_name, __LINE__, #condition); \
		return 1; \
	} \
} while (0)

static int round074_capture_owned(
		struct round074_owned_source *owned,
		const struct swapz_authority_import_spec *spec,
		const swapz_u8 *source, size_t available_bytes,
		bool lease_held)
{
	if (!owned || !spec || !source)
		return -EINVAL;
	memset(owned, 0, sizeof(*owned));
	if (!lease_held)
		return -EPERM;
	if (!spec->compressed_length ||
	    spec->compressed_length > sizeof(owned->bytes))
		return -EMSGSIZE;
	if (available_bytes < spec->compressed_length)
		return -EMSGSIZE;
	if (!spec->source_swap_slot || !spec->source_entry_identity ||
	    !spec->source_store_generation || !spec->gc_epoch)
		return -ESTALE;
	memcpy(owned->bytes, source, spec->compressed_length);
	owned->length = spec->compressed_length;
	owned->compressed_crc32c = swapz_crc32c_bytes(
		owned->bytes, owned->length);
	if (owned->compressed_crc32c != spec->compressed_crc32c)
		return -EBADMSG;
	owned->store_generation = spec->source_store_generation;
	owned->codec = spec->codec;
	owned->codec_version = spec->codec_version;
	owned->owns_bytes = true;
	return 0;
}

static int round074_queue_owned(
		const struct round074_owned_source *owned,
		const struct swapz_authority_import_spec *spec,
		const struct swapz_tx *transaction,
		struct round074_queued_bio *queued)
{
	size_t extent_bytes;

	if (!owned || !spec || !transaction || !queued)
		return -EINVAL;
	if (!owned->owns_bytes)
		return -EPERM;
	if (owned->store_generation != spec->source_store_generation ||
	    owned->codec != spec->codec ||
	    owned->codec_version != spec->codec_version ||
	    owned->compressed_crc32c != spec->compressed_crc32c)
		return -ESTALE;
	if (owned->length != spec->compressed_length)
		return -EMSGSIZE;
	extent_bytes = (size_t)transaction->extent_blocks * SWAPZ_BLOCK_BYTES;
	if (!extent_bytes || extent_bytes > sizeof(queued->bytes) ||
	    owned->length > extent_bytes)
		return -EMSGSIZE;
	memset(queued, 0, sizeof(*queued)); /* deterministic lower zero pad */
	memcpy(queued->bytes, owned->bytes, owned->length);
	queued->compressed_length = owned->length;
	queued->extent_bytes = (swapz_u32)extent_bytes;
	return 0;
}

static int round074_lower_complete_once(
		struct round074_queued_bio *queued,
		const struct swapz_tx *transaction,
		swapz_u64 ticket, int lower_error,
		swapz_u8 completed_blocks, int flushed)
{
	swapz_u8 *destination;

	if (!queued || !transaction)
		return -EINVAL;
	if (queued->complete)
		return -ESTALE;
	if (queued->extent_bytes !=
	    (swapz_u32)transaction->extent_blocks * SWAPZ_BLOCK_BYTES)
		return -EMSGSIZE;
	destination = extent_at(transaction->start_block);
	if (!destination)
		return -ERANGE;
	queued->complete = true;
	/* This copies the owned BIO bytes, NEVER any possibly erased source. */
	memcpy(destination, queued->bytes, queued->extent_bytes);
	return receipt(transaction, ticket, lower_error, completed_blocks,
		       flushed);
}

/* Ownership handoff tests never invent the selected upper ACK. */
static int round074_immutable_original_profile(swapz_u8 codec,
					      swapz_u32 logical)
{
	struct round074_owned_source owned = { 0 };
	struct round074_queued_bio queued = { 0 };
	struct swapz_authority_import_spec spec;
	struct swapz_import_disk_view view;
	struct swapz_tx transaction;
	swapz_u64 ticket = 0U;
	swapz_u8 expected[SWAPZ_MAX_COMPRESSED];
	size_t index;

	ROUND074_CHECK(initialize() == 0);
	ROUND074_CHECK(prepare_spec(logical, 1U, codec, &spec) == 0);
	ROUND074_CHECK(round074_capture_owned(&owned, &spec, source_bytes,
					spec.compressed_length, true) == 0);
	memcpy(expected, source_bytes, spec.compressed_length);
	ROUND074_CHECK(stage_submit(&spec, 2U, 0U,
				    &transaction, &ticket) == 0);
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == 0);
	/* Source is erased BEFORE later asynchronous lower completion. */
	memset(source_bytes, 0xc3, sizeof(source_bytes));
	memset(owned.bytes, 0xa6, sizeof(owned.bytes));
	for (index = 0U; index < spec.compressed_length; ++index)
		ROUND074_CHECK(queued.bytes[index] == expected[index]);
	for (; index < queued.extent_bytes; ++index)
		ROUND074_CHECK(queued.bytes[index] == 0U);
	ROUND074_CHECK(round074_lower_complete_once(&queued, &transaction,
			ticket, 0, transaction.extent_blocks, 1) == 0);
	ROUND074_CHECK(round074_lower_complete_once(&queued, &transaction,
			ticket, 0, transaction.extent_blocks, 1) == -ESTALE);
	ROUND074_CHECK(receipt(&transaction, ticket, 0,
			       transaction.extent_blocks, 1) == -ESTALE);
	ROUND074_CHECK(swapz_import_disk_pin(&pool, ticket, &view) == 0);
	ROUND074_CHECK(view.spec.codec == codec &&
		       view.spec.codec_version == 1U &&
		       view.spec.source_store_generation == 0x3344U &&
		       view.spec.gc_epoch == 1U &&
		       view.spec.compressed_crc32c == spec.compressed_crc32c &&
		       view.spec.compressed_length == spec.compressed_length &&
		       !memcmp(view.spec.original_sha256, spec.original_sha256,
			       sizeof(spec.original_sha256)));
	ROUND074_CHECK(!memcmp(extent_at(transaction.start_block),
			       expected, spec.compressed_length));
	ROUND074_CHECK(decode_view(&view, queued.extent_bytes, output) == 0);
	ROUND074_CHECK(!memcmp(output, original, SWAPZ_BLOCK_BYTES));
	ROUND074_CHECK(swapz_import_disk_put(&pool, ticket) == 0);
	ROUND074_CHECK(swapz_import_disk_retire(&pool, ticket) == 0);
	ROUND074_CHECK(swapz_import_disk_close(&pool) == 0);
	ROUND074_CHECK(header_intact() && !maps[logical].valid);
	return 0;
}

static int round074_original_lz4_owned_after_erase(void)
{
	return round074_immutable_original_profile(SWAPZ_AUTHORITY_IMPORT_LZ4, 7U);
}

static int round074_original_lzo1x_owned_after_erase(void)
{
	return round074_immutable_original_profile(SWAPZ_AUTHORITY_IMPORT_LZO1X, 8U);
}

static int round074_reject_borrowed_and_short(void)
{
	struct round074_owned_source owned = { 0 };
	struct round074_queued_bio queued = { 0 };
	struct swapz_authority_import_spec spec;
	struct swapz_tx transaction = { 0 };

	ROUND074_CHECK(initialize() == 0);
	ROUND074_CHECK(prepare_spec(9U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4,
				    &spec) == 0);
	ROUND074_CHECK(round074_capture_owned(&owned, &spec, source_bytes,
			       spec.compressed_length, false) == -EPERM);
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == -EPERM);
	ROUND074_CHECK(round074_capture_owned(&owned, &spec, source_bytes,
			       (size_t)spec.compressed_length - 1U, true)
			       == -EMSGSIZE);
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == -EPERM);
	ROUND074_CHECK(authority.in_flight == 0U && authority.committed_blocks == 0U);
	ROUND074_CHECK(header_intact() && !maps[9U].valid);
	return 0;
}

static int round074_reject_cross_epoch_and_tampered(void)
{
	struct round074_owned_source owned = { 0 };
	struct round074_queued_bio queued = { 0 };
	struct swapz_authority_import_spec spec;
	struct swapz_tx transaction;
	swapz_u64 ticket = 0U;

	ROUND074_CHECK(initialize() == 0);
	ROUND074_CHECK(prepare_spec(12U, 1U, SWAPZ_AUTHORITY_IMPORT_LZO1X,
				    &spec) == 0);
	ROUND074_CHECK(round074_capture_owned(&owned, &spec, source_bytes,
					spec.compressed_length, true) == 0);
	ROUND074_CHECK(stage_submit(&spec, 1U, 0U, &transaction, &ticket) == 0);
	++spec.source_store_generation;
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == -ESTALE);
	--spec.source_store_generation;
	++spec.codec;
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == -ESTALE);
	--spec.codec;
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == 0);
	/* A corrupted queued BIO is caught by actual product source CRC. */
	queued.bytes[0] ^= 0x80U;
	memset(source_bytes, 0xc3, sizeof(source_bytes));
	ROUND074_CHECK(round074_lower_complete_once(&queued, &transaction,
			ticket, 0, transaction.extent_blocks, 1) == -EBADMSG);
	ROUND074_CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	ROUND074_CHECK(authority.committed_blocks == 0U && !maps[12U].valid);
	ROUND074_CHECK(header_intact());
	return 0;
}

static int round074_reject_short_and_duplicate(void)
{
	struct round074_owned_source owned = { 0 };
	struct round074_queued_bio queued = { 0 };
	struct swapz_authority_import_spec spec;
	struct swapz_tx transaction;
	swapz_u64 ticket = 0U;

	ROUND074_CHECK(initialize() == 0);
	ROUND074_CHECK(prepare_spec(15U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4,
				    &spec) == 0);
	ROUND074_CHECK(round074_capture_owned(&owned, &spec, source_bytes,
					spec.compressed_length, true) == 0);
	ROUND074_CHECK(stage_submit(&spec, 2U, 0U, &transaction, &ticket) == 0);
	ROUND074_CHECK(round074_queue_owned(&owned, &spec, &transaction,
					   &queued) == 0);
	memset(source_bytes, 0xa5, sizeof(source_bytes));
	/* 13 bytes is NOT a successful original compressed lower FUA. */
	ROUND074_CHECK(round074_lower_complete_once(&queued, &transaction,
			ticket, -EIO, 0U, 0) == -EIO);
	ROUND074_CHECK(round074_lower_complete_once(&queued, &transaction,
			ticket, 0, transaction.extent_blocks, 1) == -ESTALE);
	ROUND074_CHECK(swapz_import_disk_abort(&pool, ticket) == 0);
	ROUND074_CHECK(!maps[15U].valid && authority.committed_blocks == 0U);
	ROUND074_CHECK(header_intact());
	return 0;
}

static int round074_exact_original_gc_under_reader_pin(void)
{
	struct round074_owned_source source_owned = { 0 };
	struct round074_owned_source gc_owned = { 0 };
	struct round074_queued_bio original_queue = { 0 };
	struct round074_queued_bio gc_queue = { 0 };
	struct swapz_authority_import_spec spec, relocated;
	struct swapz_import_disk_view old_view;
	struct swapz_tx original_tx, gc_tx;
	swapz_u64 original_ticket = 0U, gc_ticket = 0U;
	swapz_u32 original_start, gc_start;
	swapz_u8 original_compressed[SWAPZ_MAX_COMPRESSED];

	ROUND074_CHECK(initialize() == 0);
	ROUND074_CHECK(prepare_spec(20U, 1U, SWAPZ_AUTHORITY_IMPORT_LZ4,
				    &spec) == 0);
	ROUND074_CHECK(round074_capture_owned(&source_owned, &spec,
			       source_bytes, spec.compressed_length, true) == 0);
	memcpy(original_compressed, source_owned.bytes, spec.compressed_length);
	ROUND074_CHECK(stage_submit(&spec, 2U, 0U, &original_tx,
				    &original_ticket) == 0);
	ROUND074_CHECK(round074_queue_owned(&source_owned, &spec, &original_tx,
					   &original_queue) == 0);
	memset(source_bytes, 0x55, sizeof(source_bytes));
	memset(source_owned.bytes, 0x66, sizeof(source_owned.bytes));
	ROUND074_CHECK(round074_lower_complete_once(&original_queue,
			&original_tx, original_ticket, 0,
			original_tx.extent_blocks, 1) == 0);
	ROUND074_CHECK(swapz_import_disk_pin(&pool, original_ticket,
					    &old_view) == 0);
	original_start = original_tx.start_block;
	relocated = old_view.spec;
	++relocated.gc_epoch;
	/* This is an old read-pinned disk extent, NOT a second zswap encoder. */
	ROUND074_CHECK(round074_capture_owned(&gc_owned, &relocated,
			extent_at(original_start), spec.compressed_length,
			true) == 0);
	ROUND074_CHECK(!memcmp(gc_owned.bytes, original_compressed,
			       spec.compressed_length));
	ROUND074_CHECK(stage_submit(&relocated, 4U, original_ticket, &gc_tx,
				    &gc_ticket) == 0);
	ROUND074_CHECK(round074_queue_owned(&gc_owned, &relocated, &gc_tx,
					   &gc_queue) == 0);
	memset(gc_owned.bytes, 0xff, sizeof(gc_owned.bytes));
	ROUND074_CHECK(round074_lower_complete_once(&gc_queue, &gc_tx,
			gc_ticket, 0, gc_tx.extent_blocks, 1) == 0);
	gc_start = gc_tx.start_block;
	ROUND074_CHECK(original_start != gc_start &&
		       live_records[original_start] == 1U &&
		       live_records[gc_start] == 1U);
	ROUND074_CHECK(old_view.spec.codec == relocated.codec &&
		       old_view.spec.codec_version == relocated.codec_version &&
		       old_view.spec.source_swap_slot == relocated.source_swap_slot &&
		       old_view.spec.source_entry_identity ==
		       relocated.source_entry_identity &&
		       old_view.spec.source_store_generation ==
		       relocated.source_store_generation &&
		       old_view.spec.compressed_crc32c ==
		       relocated.compressed_crc32c &&
		       relocated.gc_epoch == old_view.spec.gc_epoch + 1U &&
		       !memcmp(extent_at(original_start), extent_at(gc_start),
			       spec.compressed_length));
	ROUND074_CHECK(swapz_import_disk_pin(&pool, original_ticket,
					    &old_view) == -ESTALE);
	/* The retained old_view was captured before GC; reacquire for READ. */
	ROUND074_CHECK(decode_ticket(gc_ticket) == 0);
	ROUND074_CHECK(swapz_import_disk_put(&pool, original_ticket) == 0);
	ROUND074_CHECK(live_records[original_start] == 0U &&
		       live_records[gc_start] == 1U);
	ROUND074_CHECK(swapz_import_disk_retire(&pool, gc_ticket) == 0);
	ROUND074_CHECK(swapz_import_disk_close(&pool) == 0 && header_intact());
	return 0;
}

struct round074_case {
	const char *name;
	int (*run)(void);
};

static const struct round074_case round074_cases[] = {
	{ "original_lz4_owned_after_erase",
	  round074_original_lz4_owned_after_erase },
	{ "original_lzo1x_owned_after_erase",
	  round074_original_lzo1x_owned_after_erase },
	{ "borrowed_and_short_source_rejected",
	  round074_reject_borrowed_and_short },
	{ "cross_epoch_and_tampered_queue_rejected",
	  round074_reject_cross_epoch_and_tampered },
	{ "short_lower_and_duplicate_callback_rejected",
	  round074_reject_short_and_duplicate },
	{ "original_lz4_GC_byte_identity_reader_pin",
	  round074_exact_original_gc_under_reader_pin },
};

int main(int argc, char **argv)
{
	size_t index;
	size_t executed = 0U;

	for (index = 0U; index < sizeof(round074_cases) /
	     sizeof(round074_cases[0]); ++index) {
		if (argc == 2 && strcmp(argv[1], round074_cases[index].name))
			continue;
		case_name = round074_cases[index].name;
		if (round074_cases[index].run())
			return 3;
		++executed;
	}
	if (!executed) {
		fprintf(stderr, "ROUND074_FIRST_ERROR unknown-case\n");
		return 2;
	}
	if (argc == 1)
		printf("PASS round074_ownership_source_linked_cases=%zu "
		       "actual_authority_C=YES codecs=original_LZO1X_LZ4 "
		       "full_original_bytes=4096 owned_bio_bytes=MODEL "
		       "source_erase_before_completion=YES gc_byte_identity=YES "
		       "reader_pin_last_put=YES upper_ACK=NONE physical=NONE "
		       "import_ACTIVE0=YES AUTH0 PHASE_A=BLOCKED\n",
		       executed);
	return 0;
}
