// SPDX-License-Identifier: GPL-2.0-only
/*
 * Main-developer regression for Codex's independently reproduced stage/finish
 * transaction-record identity substitution. Uses EXACT production C, not
 * a mock of swapz_finish. Failure must leave the originally staged transaction
 * active and must not publish ANY of the substituted caller-provided records.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "authority.h"
#include "flush-qual.h"
/* Compile the exact production engine body into this test: no change to
 * shared suite/link rules or a duplicated read-range model. */
#include "engine.c"

#define CHECK(expr) do { \
	if (!(expr)) { \
		fprintf(stderr, "%s:%d FAILED: %s\n", __FILE__, __LINE__, #expr); \
		return 1; \
	} \
} while (0)

#define LOGICAL 64
#define PHYSICAL 2048

static struct swapz_authority a;
static struct swapz_map maps[LOGICAL];
static swapz_u16 live[PHYSICAL];
static swapz_u8 classes[PHYSICAL];
static swapz_u8 bytes[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 compressed[2072];

static int init(void)
{
	return swapz_authority_init(&a, maps, live, classes,
				 LOGICAL, PHYSICAL);
}

static int encode(const struct swapz_tx *tx)
{
	struct swapz_builder b;
	swapz_u8 i;

	memset(compressed, 0x5a, sizeof(compressed));
	if (swapz_begin(&b, bytes, tx->extent_blocks * SWAPZ_BLOCK_BYTES,
		      tx->sequence))
		return 1;
	for (i = 0; i < tx->count; ++i)
		if (swapz_append(&b, tx->records[i].logical_page,
			       tx->records[i].generation,
			       compressed, sizeof(compressed)))
			return 1;
	return swapz_seal(&b);
}

static int test_page_identity_mutation(void)
{
	const swapz_u32 pages[] = {0};
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 1, 1, &tx) == 0);
	CHECK(tx.records[0].logical_page == 0);
	tx.records[0].logical_page = 1;
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[0].valid && !maps[1].valid);
	CHECK(a.committed_blocks == 0 && a.abandoned_blocks == 0);
	/* Wrong caller handle must also fail to abort the valid transaction. */
	CHECK(swapz_abort(&a, &tx) == -ESTALE);
	CHECK(a.in_flight);
	tx.records[0].logical_page = 0;
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	CHECK(!a.in_flight && maps[0].valid && maps[0].generation == 1);
	CHECK(!maps[1].valid && live[0] == 1);
	return 0;
}

static int test_generation_identity_mutation(void)
{
	const swapz_u32 pages[] = {3};
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 1, 1, &tx) == 0);
	tx.records[0].generation++;
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[3].valid);
	CHECK(swapz_abort(&a, &tx) == -ESTALE);
	tx.records[0].generation--;
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(!a.in_flight && a.abandoned_blocks == 1);
	CHECK(!maps[3].valid);
	return 0;
}

static int test_bound_compressed_metadata_is_transaction_identity(void)
{
	const swapz_u32 pages[] = { 5 };
	struct swapz_builder builder;
	struct swapz_tx transaction;
	swapz_u32 payload_crc32c;

	CHECK(init() == 0);
	memset(compressed, 0x4d, sizeof(compressed));
	payload_crc32c = swapz_crc32c_bytes(compressed, sizeof(compressed));
	CHECK(swapz_stage(&a, pages, 1, 1, &transaction) == 0);
	CHECK(swapz_begin(&builder, bytes, SWAPZ_BLOCK_BYTES,
			  transaction.sequence) == 0);
	CHECK(swapz_append_prehashed_encoded(
			  &builder, transaction.records[0].logical_page,
			  transaction.records[0].generation,
			  compressed, sizeof(compressed), payload_crc32c,
			  SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_bind_compressed_record(
			  &a, &transaction, 0,
			  builder.last_payload_offset,
			  builder.last_payload_length,
			  builder.last_payload_crc32c,
			  builder.last_encoding) == 0);
	CHECK(swapz_seal(&builder) == 0);
	CHECK(transaction.records[0].compressed_metadata_bound == 1 &&
	      a.active_tx.records[0].compressed_metadata_bound == 1);
	CHECK(transaction.records[0].payload_crc32c == payload_crc32c &&
	      transaction.records[0].payload_offset ==
		      builder.last_payload_offset &&
	      transaction.records[0].payload_length == sizeof(compressed));

	transaction.records[0].payload_crc32c ^= 1U;
	CHECK(swapz_finish(&a, &transaction, bytes,
			   SWAPZ_BLOCK_BYTES, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[5].valid);
	CHECK(swapz_abort(&a, &transaction) == -ESTALE);
	transaction.records[0].payload_crc32c ^= 1U;
	CHECK(swapz_finish(&a, &transaction, bytes,
			   SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	CHECK(!a.in_flight && maps[5].valid &&
	      maps[5].payload_crc32c == payload_crc32c &&
	      maps[5].payload_offset == builder.last_payload_offset);
	return 0;
}

static int test_data_only_payload_publishes_from_bound_ram_metadata(void)
{
	const swapz_u32 pages[] = { 6, 7 };
	struct swapz_decoded ram_records[2] = { { 0 } };
	struct swapz_ram_extent builder;
	struct swapz_tx transaction;
	swapz_u8 index;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 2, 2, &transaction) == 0);
	memset(bytes, 0xa5, 2U * SWAPZ_BLOCK_BYTES);
	CHECK(swapz_ram_extent_begin(&builder, bytes,
				     2U * SWAPZ_BLOCK_BYTES,
				     transaction.sequence, ram_records, 2) == 0);
	for (index = 0; index < 2; ++index) {
		memset(compressed, 0x61 + index, sizeof(compressed));
		CHECK(swapz_ram_extent_append(
			      &builder, transaction.records[index].logical_page,
			      transaction.records[index].generation,
			      compressed, sizeof(compressed),
			      index ? SWAPZ_ENCODING_DELTA64 :
				      SWAPZ_ENCODING_LZ4) == 0);
		CHECK(swapz_bind_compressed_record(
			      &a, &transaction, index,
			      ram_records[index].payload_offset,
			      ram_records[index].payload_length,
			      ram_records[index].payload_crc32c,
			      ram_records[index].encoding) == 0);
	}
	CHECK(swapz_ram_extent_seal(&builder) == 0);
	CHECK(swapz_mark_compressed_data_only(&a, &transaction) == 0);
	CHECK(transaction.compressed_data_only == 1 &&
	      a.active_tx.compressed_data_only == 1);
	for (index = 0; index < sizeof(struct swapz_header); ++index)
		CHECK(bytes[index] == 0);
	CHECK(swapz_finish(&a, &transaction, bytes,
			   2U * SWAPZ_BLOCK_BYTES, 2, 0) == 0);
	CHECK(maps[6].valid && maps[7].valid &&
	      maps[6].start_block == maps[7].start_block &&
	      maps[6].payload_crc32c == ram_records[0].payload_crc32c &&
	      maps[7].payload_crc32c == ram_records[1].payload_crc32c &&
	      maps[6].payload_offset == ram_records[0].payload_offset &&
	      maps[7].payload_offset == ram_records[1].payload_offset);
	return 0;
}

static int test_last_sibling_mutation_is_all_or_nothing(void)
{
	const swapz_u32 pages[] = {0, 1, 2};
	struct swapz_tx tx;
	struct swapz_map before[LOGICAL];

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 3, 2, &tx) == 0);
	tx.records[2].logical_page = 9;
	CHECK(encode(&tx) == 0);
	memcpy(before, maps, sizeof(before));
	CHECK(swapz_finish(&a, &tx, bytes, 8192, 2, 0) == -ESTALE);
	CHECK(memcmp(before, maps, sizeof(before)) == 0);
	CHECK(a.in_flight && !live[0]);
	tx.records[2].logical_page = 2;
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, 8192, 2, 0) == 0);
	CHECK(maps[0].valid && maps[1].valid && maps[2].valid);
	CHECK(!maps[9].valid && live[0] == 3);
	return 0;
}

static int test_duplicate_media_descriptor_fails_closed(void)
{
	const swapz_u32 pages[] = {0, 1};
	struct swapz_tx tx;
	struct swapz_builder b;
	struct swapz_map before[LOGICAL];
	swapz_u32 payload_crc;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 2, 2, &tx) == 0);
	memset(compressed, 0x6c, sizeof(compressed));
	payload_crc = swapz_crc32c_bytes(compressed, sizeof(compressed));
	CHECK(swapz_begin(&b, bytes, 2U * SWAPZ_BLOCK_BYTES, tx.sequence) == 0);
	/*
	 * The unique append helper intentionally trusts its caller's window-wide
	 * uniqueness proof. Violate that private precondition here to prove both
	 * the public validator and publication's tx identity check still fail
	 * closed rather than accepting two descriptors for logical page zero.
	 */
	CHECK(swapz_append_prehashed_encoded_unique(
		&b, tx.records[0].logical_page, tx.records[0].generation,
		compressed, sizeof(compressed), payload_crc,
		SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_append_prehashed_encoded_unique(
		&b, tx.records[0].logical_page, tx.records[1].generation,
		compressed, sizeof(compressed), payload_crc,
		SWAPZ_ENCODING_LZ4) == 0);
	CHECK(swapz_seal(&b) == 0);
	CHECK(swapz_validate(bytes, 2U * SWAPZ_BLOCK_BYTES) == -EUCLEAN);
	memcpy(before, maps, sizeof(before));
	CHECK(swapz_finish(&a, &tx, bytes, 2U * SWAPZ_BLOCK_BYTES, 2, 0) ==
	      -EUCLEAN);
	CHECK(!a.in_flight && a.abandoned_blocks == 2);
	CHECK(memcmp(before, maps, sizeof(before)) == 0);
	CHECK(!live[tx.start_block]);
	return 0;
}

static int test_mutated_replacement_preserves_prior_authority(void)
{
	const swapz_u32 pages[] = {0};
	struct swapz_tx tx;
	struct swapz_map old;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 1, 1, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, 4096, 1, 0) == 0);
	old = maps[0];

	CHECK(swapz_stage(&a, pages, 1, 1, &tx) == 0);
	tx.records[0].logical_page = 1;
	CHECK(encode(&tx) == 0);
	CHECK(swapz_finish(&a, &tx, bytes, 4096, 1, 0) == -ESTALE);
	CHECK(maps[0].start_block == old.start_block);
	CHECK(maps[0].generation == old.generation && !maps[1].valid);
	CHECK(live[old.start_block] == 1 && a.in_flight);
	tx.records[0].logical_page = 0;
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(maps[0].generation == 1 &&
	      live[old.start_block] == 1 && a.abandoned_blocks == 1);
	return 0;
}

static unsigned int invalid_extent_read_calls;

static int invalid_extent_read(void *opaque, swapz_u32 start_block,
			       swapz_u8 extent_blocks, swapz_u8 *destination)
{
	(void)opaque;
	(void)start_block;
	(void)extent_blocks;
	(void)destination;
	invalid_extent_read_calls++;
	return -EIO;
}

static int test_engine_extent_geometry_before_lower_read(void)
{
	struct swapz_engine engine = { 0 };
	const swapz_u32 logical = 0;
	swapz_u8 first_block = 0, blocks = 0;
	swapz_u16 payload_length = 0;

	CHECK(init() == 0);
	invalid_extent_read_calls = 0;
	engine.authority = &a;
	engine.read_scratch = bytes;
	engine.io.read_blocks = invalid_extent_read;
	maps[0].valid = 1;
	maps[0].raw = 0;
	maps[0].extent_blocks = 2;
	maps[0].payload_offset = 64;
	maps[0].payload_length = 8;
	/* Full extent fits physical media but crosses a 256-block segment. */
	maps[0].start_block = SWAPZ_SEGMENT_BLOCKS - 1U;
	CHECK(swapz_engine_required_read_range(&engine, &logical, 1,
		maps[0].start_block, 2, &first_block, &blocks) == -EINVAL);
	CHECK(swapz_engine_read_page(&engine, logical, compressed,
		sizeof(compressed), &payload_length) == -ESTALE);
	CHECK(invalid_extent_read_calls == 0);
	/* Full extent, not merely its start, must fit the physical device. */
	maps[0].start_block = PHYSICAL - 1U;
	CHECK(swapz_engine_required_read_range(&engine, &logical, 1,
		maps[0].start_block, 2, &first_block, &blocks) == -EINVAL);
	CHECK(swapz_engine_read_page(&engine, logical, compressed,
		sizeof(compressed), &payload_length) == -ESTALE);
	CHECK(invalid_extent_read_calls == 0);
	/* An impossible three-block class is never a valid SWZ extent. */
	maps[0].start_block = 0;
	maps[0].extent_blocks = 3;
	CHECK(swapz_engine_required_read_range(&engine, &logical, 1,
		maps[0].start_block, 3, &first_block, &blocks) == -EINVAL);
	CHECK(swapz_engine_read_page(&engine, logical, compressed,
		sizeof(compressed), &payload_length) == -ESTALE);
	CHECK(invalid_extent_read_calls == 0);
	/*
	 * A cache lookup used to shift 1U by this corrupt u8 extent count
	 * before its common validator ran. With UBSan, the old behavior is a
	 * deterministic runtime error, not merely a rejected lower read.
	 */
	engine.read_extent_lru_clock = 1;
	CHECK(swapz_engine_required_read_range_cached(&engine, &logical, 1,
		0, 32, &first_block, &blocks) == -EINVAL);
	CHECK(swapz_engine_required_read_range_cached(&engine, &logical, 1,
		SWAPZ_SEGMENT_BLOCKS - 1U, 2,
		&first_block, &blocks) == -EINVAL);
	engine.read_extent_lru_clock = 0;
	CHECK(invalid_extent_read_calls == 0);
	/* Preserve the valid boundary: two blocks ending at media end. */
	maps[0].extent_blocks = 2;
	maps[0].start_block = PHYSICAL - 2U;
	CHECK(swapz_engine_required_read_range(&engine, &logical, 1,
		maps[0].start_block, 2, &first_block, &blocks) == 0);
	CHECK(first_block == 0 && blocks == 1);
	CHECK(invalid_extent_read_calls == 0);
	return 0;
}


/*
 * An existing generation remains authoritative if a replacement's lower
 * WRITE fails (even after a partial media write) or if its required FUA
 * flush fails. Only the production gate can authorize the finish call.
 * SWAPZ_TEST_PUBLISH_BEFORE_FUA is a deliberately failing negative control.
 */
struct durability_fault {
	unsigned int flush_calls;
	int flush_error;
};

static int durable_flush(void *opaque)
{
	struct durability_fault *fault = opaque;

	fault->flush_calls++;
	return fault->flush_error;
}

static int finish_fua_replacement(struct swapz_tx *tx,
				  struct durability_fault *fault,
				  int write_error, swapz_u8 completed_blocks)
{
	int error;

#ifdef SWAPZ_TEST_PUBLISH_BEFORE_FUA
	/* Negative control: an acknowledged lower WRITE is not necessarily durable. */
	if (!write_error) {
		int published = swapz_finish(&a, tx, bytes, SWAPZ_BLOCK_BYTES,
					   completed_blocks, 0);

		if (published)
			return published;
		return swapz_write_flush_before_publish(
			write_error, 1, durable_flush, fault);
	}
#endif
	error = swapz_write_flush_before_publish(
		write_error, 1, durable_flush, fault);
	return swapz_finish(&a, tx, bytes, SWAPZ_BLOCK_BYTES,
			    error ? 0 : completed_blocks, error);
}

static int test_fua_failure_preserves_prior_generation(void)
{
	const swapz_u32 pages[] = { 7 };
	struct durability_fault fault = { 0 };
	struct swapz_tx transaction;
	struct swapz_map previous;
	unsigned int attempt;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 1, 1, &transaction) == 0);
	CHECK(encode(&transaction) == 0);
	CHECK(swapz_finish(&a, &transaction, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	previous = maps[7];
	CHECK(previous.valid && previous.generation == 1);

	/* Lower EIO before or after media may have changed, and a post-WRITE
	 * flush EIO, must all abort without publishing the new generation. */
	for (attempt = 0; attempt < 3U; ++attempt) {
		int write_error = attempt == 2U ? 0 : -EIO;
		swapz_u8 completed_blocks = attempt == 1U ? 1 : 0;
		unsigned int before_flushes = fault.flush_calls;

		CHECK(swapz_stage(&a, pages, 1, 1, &transaction) == 0);
		CHECK(encode(&transaction) == 0);
		fault.flush_error = attempt == 2U ? -EIO : 0;
		CHECK(finish_fua_replacement(&transaction, &fault,
					     write_error, completed_blocks) == -EIO);
		CHECK(!a.in_flight);
		CHECK(maps[7].valid &&
		      maps[7].generation == previous.generation &&
		      maps[7].start_block == previous.start_block);
		CHECK(live[previous.start_block] == 1);
		CHECK(fault.flush_calls == before_flushes +
		      (attempt == 2U ? 1U : 0U));
	}
	CHECK(a.abandoned_blocks == 3);
	CHECK(swapz_stage(&a, pages, 1, 1, &transaction) == 0);
	CHECK(encode(&transaction) == 0);
	fault.flush_error = 0;
	CHECK(finish_fua_replacement(&transaction, &fault, 0, 1) == 0);
	CHECK(maps[7].valid && maps[7].generation == 2 &&
	      maps[7].start_block != previous.start_block);
	CHECK(live[previous.start_block] == 0);
	return 0;
}

static int test_zero_overwrite_fua_fences_before_zero_publication(void)
{
	const swapz_u32 pages[] = { 4 };
	struct durability_fault fault = { .flush_error = -EIO };
	struct swapz_tx transaction;
	struct swapz_map previous;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 1, 1, &transaction) == 0);
	CHECK(encode(&transaction) == 0);
	CHECK(swapz_finish(&a, &transaction, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	previous = maps[4];

	/*
	 * A zero overwrite remains an upper WRITE|FUA even though the target
	 * publishes zero by invalidating its old mapping instead of writing data.
	 * The failed durability fence must leave generation 1 authoritative.
	 */
	CHECK(swapz_write_flush_before_publish(0, 1, durable_flush,
						&fault) == -EIO);
	CHECK(maps[4].valid && maps[4].generation == previous.generation);
	CHECK(live[previous.start_block] == 1);
	fault.flush_error = 0;
	CHECK(swapz_write_flush_before_publish(0, 1, durable_flush,
						&fault) == 0);
	CHECK(swapz_discard_page(&a, 4) == 0);
	CHECK(!maps[4].valid && maps[4].generation == 2);
	CHECK(live[previous.start_block] == 0 && fault.flush_calls == 2);
	return 0;
}

static int test_short_completion_preserves_prior_generation(void)
{
	const swapz_u32 pages[] = { 12, 13 };
	struct swapz_tx transaction;
	struct swapz_map previous[2];
	swapz_u32 replacement_start;

	CHECK(init() == 0);
	CHECK(swapz_stage(&a, pages, 2, 2, &transaction) == 0);
	CHECK(transaction.count == 2 && transaction.extent_blocks == 2);
	CHECK(encode(&transaction) == 0);
	CHECK(swapz_finish(&a, &transaction, bytes,
			   2U * SWAPZ_BLOCK_BYTES, 2, 0) == 0);
	previous[0] = maps[12];
	previous[1] = maps[13];
	CHECK(previous[0].valid && previous[1].valid);
	CHECK(previous[0].generation == 1 && previous[1].generation == 1);
	CHECK(previous[0].start_block == previous[1].start_block);
	CHECK(live[previous[0].start_block] == 2);

	CHECK(swapz_stage(&a, pages, 2, 2, &transaction) == 0);
	replacement_start = transaction.start_block;
	CHECK(replacement_start != previous[0].start_block);
	CHECK(encode(&transaction) == 0);
	/* A nominally successful lower call that reports only one of two blocks
	 * completed is not publishable. No replacement generation may escape. */
	CHECK(swapz_finish(&a, &transaction, bytes,
			   2U * SWAPZ_BLOCK_BYTES, 1, 0) == -EIO);
	CHECK(!a.in_flight);
	CHECK(maps[12].generation == previous[0].generation &&
	      maps[12].start_block == previous[0].start_block);
	CHECK(maps[13].generation == previous[1].generation &&
	      maps[13].start_block == previous[1].start_block);
	CHECK(live[previous[0].start_block] == 2);
	CHECK(!live[replacement_start] && a.abandoned_blocks == 2);
	return 0;
}


/*
 * One serialized mixed-run regression: a physically written prefix followed
 * by -EIO must not publish compressed/RAW replacements, a new logical page,
 * or a DISCARD, even near the u32 logical-generation ceiling. The exact
 * production engine prepares, submits and replays the batch; callbacks model
 * completed lower bytes only, never loaded-kernel behavior.
 */
#define PUBLICATION_MEDIA_BLOCKS 8U
static swapz_u8 publication_media[PUBLICATION_MEDIA_BLOCKS * SWAPZ_BLOCK_BYTES];
static swapz_u8 publication_first_block[SWAPZ_BLOCK_BYTES];
static swapz_u8 publication_old_raw[SWAPZ_BLOCK_BYTES];
static swapz_u8 publication_new_raw[SWAPZ_BLOCK_BYTES];
static swapz_u8 publication_new_compressed[2][1024];
static swapz_u8 publication_readback[SWAPZ_BLOCK_BYTES];
static swapz_u8 publication_read_scratch[SWAPZ_MAX_EXTENT_BYTES];
static swapz_u8 publication_bulk_bytes[SWAPZ_BULK_BLOCKS * SWAPZ_BLOCK_BYTES];
static struct swapz_tx publication_transactions[SWAPZ_MAX_RECORDS];
static swapz_u8 publication_roles[PHYSICAL / SWAPZ_SEGMENT_BLOCKS];
static swapz_u8 publication_sequence_delta[PHYSICAL];
static swapz_u32 publication_sequence_base[PHYSICAL / SWAPZ_SEGMENT_BLOCKS];
static struct swapz_engine publication_engine;

struct publication_fault_control {
	unsigned int lower_runs;
	unsigned int read_calls;
	unsigned int sealed_calls;
	unsigned int sealed_pages;
	unsigned int published_calls;
	unsigned int published_pages;
	unsigned int ownership_violations;
	swapz_u32 failed_start;
	swapz_u16 failed_blocks;
	int original_errno;
};

struct publication_expectation {
	unsigned int lower_runs;
	unsigned int sealed_calls;
	unsigned int sealed_pages;
	unsigned int published_calls;
	unsigned int published_pages;
	swapz_u8 committed_pages;
	swapz_u32 next_block;
	swapz_u32 committed_blocks;
	swapz_u32 abandoned_blocks;
	swapz_u32 submitted_blocks;
	swapz_u32 completed_blocks;
	swapz_u32 bulk_writes;
	swapz_u32 bulk_extents;
	swapz_u32 bulk_mixed_runs;
	swapz_u32 bulk_raw_entries;
};

static int publication_lower_read(void *opaque, swapz_u32 start_block,
				  swapz_u8 blocks, swapz_u8 *destination)
{
	struct publication_fault_control *control = opaque;
	const size_t stride = SWAPZ_BLOCK_BYTES;

	if (!blocks || start_block >= PUBLICATION_MEDIA_BLOCKS ||
	    blocks > PUBLICATION_MEDIA_BLOCKS - start_block)
		return -ERANGE;
	control->read_calls++;
	memcpy(destination, publication_media + (size_t)start_block * stride,
	       (size_t)blocks * stride);
	return 0;
}

static void publication_write_sealed(void *opaque, swapz_u8 count)
{
	struct publication_fault_control *control = opaque;

	control->sealed_calls++;
	control->sealed_pages += count;
}

static void publication_write_published(void *opaque, swapz_u8 count)
{
	struct publication_fault_control *control = opaque;

	control->published_calls++;
	control->published_pages += count;
	if (!maps[0].valid || maps[0].raw || !maps[1].valid ||
	    !maps[1].raw || !maps[2].valid || maps[2].raw)
		control->ownership_violations++;
}

static int publication_lower_write(void *opaque, swapz_u32 start_block,
				   swapz_u16 blocks, const swapz_u8 *image,
				   swapz_u16 *completed_blocks)
{
	struct publication_fault_control *control = opaque;
	const swapz_u32 protected_page = 0;
	const size_t stride = SWAPZ_BLOCK_BYTES;
	struct swapz_tx refused;

	*completed_blocks = 0;
	if (blocks < 2U || blocks > SWAPZ_BULK_BLOCKS ||
	    start_block >= PUBLICATION_MEDIA_BLOCKS ||
	    blocks > PUBLICATION_MEDIA_BLOCKS - start_block)
		return -ERANGE;
	control->lower_runs++;
	/* This callback runs under the one serialized owner, with paused
	 * reservations. Neither another stage nor DISCARD can steal them. */
	if (a.batch_pending != 2U || a.in_flight ||
	    swapz_discard_page(&a, protected_page) != -EBUSY ||
	    swapz_stage(&a, &protected_page, 1, 1, &refused) != -EBUSY ||
	    maps[0].generation != UINT32_MAX - 2U ||
	    maps[1].generation != UINT32_MAX - 2U || maps[2].valid)
		control->ownership_violations++;
	if (control->lower_runs == 1U) {
		control->failed_start = start_block;
		control->failed_blocks = blocks;
		memcpy(publication_first_block, image, stride);
		memcpy(publication_media + (size_t)start_block * stride,
		       image, stride);
		*completed_blocks = 1;
		return control->original_errno;
	}
	memcpy(publication_media + (size_t)start_block * stride,
	       image, (size_t)blocks * stride);
	*completed_blocks = blocks;
	return 0;
}

static int publication_failure(
	const char *operation, swapz_u32 logical_generation, const char *phase,
	int expected_errno, int actual_errno, swapz_u8 actual_committed_pages,
	const struct publication_fault_control *control,
	const struct publication_expectation *expected,
	const struct swapz_map *initial_raw,
	const struct swapz_map *initial_compressed)
{
	fprintf(stderr,
		"FAIL operation=%s logical_generation=%u phase=%s "
		"original_errno=%d expected_errno=%d actual_errno=%d "
		"initial_authority=raw(gen:%u,start:%u),compressed(gen:%u,start:%u) "
		"retained_authority=p0(gen:%u,start:%u,raw:%u,valid:%u),"
		"p1(gen:%u,start:%u,raw:%u,valid:%u),"
		"p2(gen:%u,start:%u,raw:%u,valid:%u) "
		"reservation=(start:%u,blocks:%u) "
		"counters_expected_actual="
		"lower_runs:%u/%u,sealed_calls:%u/%u,sealed_pages:%u/%u,"
		"published_calls:%u/%u,published_pages:%u/%u,"
		"committed_pages:%u/%u,next_block:%u/%u,"
		"committed_blocks:%u/%u,abandoned_blocks:%u/%u,"
		"submitted_blocks:%u/%u,completed_blocks:%u/%u,"
		"bulk_writes:%u/%u,bulk_extents:%u/%u,"
		"bulk_mixed_runs:%u/%u,bulk_raw_entries:%u/%u\n",
		operation, logical_generation, phase, control->original_errno,
		expected_errno, actual_errno,
		initial_raw->generation, initial_raw->start_block,
		initial_compressed->generation, initial_compressed->start_block,
		maps[0].generation, maps[0].start_block,
		(unsigned int)maps[0].raw, (unsigned int)maps[0].valid,
		maps[1].generation, maps[1].start_block,
		(unsigned int)maps[1].raw, (unsigned int)maps[1].valid,
		maps[2].generation, maps[2].start_block,
		(unsigned int)maps[2].raw, (unsigned int)maps[2].valid,
		control->failed_start, (unsigned int)control->failed_blocks,
		expected->lower_runs, control->lower_runs,
		expected->sealed_calls, control->sealed_calls,
		expected->sealed_pages, control->sealed_pages,
		expected->published_calls, control->published_calls,
		expected->published_pages, control->published_pages,
		(unsigned int)expected->committed_pages,
		(unsigned int)actual_committed_pages,
		expected->next_block, a.next_block,
		expected->committed_blocks, a.committed_blocks,
		expected->abandoned_blocks, a.abandoned_blocks,
		expected->submitted_blocks, publication_engine.submitted_blocks,
		expected->completed_blocks, publication_engine.completed_blocks,
		expected->bulk_writes, publication_engine.bulk_writes,
		expected->bulk_extents, publication_engine.bulk_extents,
		expected->bulk_mixed_runs, publication_engine.bulk_mixed_runs,
		expected->bulk_raw_entries, publication_engine.bulk_raw_entries);
	return 1;
}

#define REQUIRE_PUBLICATION(condition, operation, generation, phase, \
			    expected_errno, actual_errno) do { \
	if (!(condition)) \
		return publication_failure(operation, generation, phase, \
					   expected_errno, actual_errno, committed_pages, \
					   &control, \
					   &expectation, &retained_raw, \
					   &retained_compressed); \
} while (0)

static int test_torn_mixed_replacement_discard_generation_rollover(void)
{
	const swapz_u32 raw_logical = 0, compressed_logical = 1;
	const size_t stride = SWAPZ_BLOCK_BYTES;
	struct publication_fault_control control = { .original_errno = -EIO };
	struct publication_expectation expectation = { 0 };
	struct swapz_tx transaction;
	struct swapz_map retained_raw, retained_compressed;
	struct swapz_compressed_page replacement[3] = { 0 };
	swapz_u8 committed_pages = 0;
	swapz_u16 payload_length = 0;
	swapz_u32 first_retry_block;
	unsigned int read_calls_before;
	int error;

	CHECK(init() == 0);
	CHECK(swapz_enable_extent_sequence_index(
		&a, publication_sequence_delta, publication_sequence_base,
		PHYSICAL / SWAPZ_SEGMENT_BLOCKS) == 0);
	/* Batch pause requires the ordered owner to opt into rotating allocation.
	 * Segment-role storage alone does not enable the publication fence. */
	a.reuse_dead_segments = 1;
	CHECK(swapz_enable_segment_rotation(
		&a, publication_roles, PHYSICAL / SWAPZ_SEGMENT_BLOCKS) == 0);
	memset(publication_media, 0, sizeof(publication_media));
	memset(&publication_engine, 0, sizeof(publication_engine));
	memset(publication_old_raw, 0x42, sizeof(publication_old_raw));
	memset(publication_new_raw, 0x91, sizeof(publication_new_raw));
	memset(publication_new_compressed[0], 0x36,
	       sizeof(publication_new_compressed[0]));
	memset(publication_new_compressed[1], 0x73,
	       sizeof(publication_new_compressed[1]));

	/* Seed two real surviving extents at generation UINT32_MAX - 2. */
	maps[raw_logical].generation = UINT32_MAX - 3U;
	maps[compressed_logical].generation = UINT32_MAX - 3U;
	CHECK(swapz_stage(&a, &raw_logical, 1, 1, &transaction) == 0);
	CHECK(transaction.start_block < PUBLICATION_MEDIA_BLOCKS);
	memcpy(publication_media + (size_t)transaction.start_block * stride,
	       publication_old_raw, stride);
	CHECK(swapz_finish_raw(&a, &transaction, publication_old_raw, 1, 0) == 0);
	CHECK(swapz_stage(&a, &compressed_logical, 1, 1, &transaction) == 0);
	CHECK(transaction.start_block < PUBLICATION_MEDIA_BLOCKS);
	CHECK(encode(&transaction) == 0);
	memcpy(publication_media + (size_t)transaction.start_block * stride,
	       bytes, stride);
	CHECK(swapz_finish(&a, &transaction, bytes, SWAPZ_BLOCK_BYTES, 1, 0) == 0);
	retained_raw = maps[raw_logical];
	retained_compressed = maps[compressed_logical];
	CHECK(retained_raw.valid && retained_raw.raw &&
	      retained_raw.generation == UINT32_MAX - 2U);
	CHECK(retained_compressed.valid && !retained_compressed.raw &&
	      retained_compressed.generation == UINT32_MAX - 2U);
	CHECK(a.committed_blocks == 2 && a.abandoned_blocks == 0);

	replacement[0] = (struct swapz_compressed_page){
		.logical_page = raw_logical,
		.payload = publication_new_compressed[0],
		.length = sizeof(publication_new_compressed[0]),
		.encoding = SWAPZ_ENCODING_LZ4,
	};
	replacement[1] = (struct swapz_compressed_page){
		.logical_page = 2,
		.payload = publication_new_compressed[1],
		.length = sizeof(publication_new_compressed[1]),
		.encoding = SWAPZ_ENCODING_LZ4,
	};
	replacement[2] = (struct swapz_compressed_page){
		.logical_page = compressed_logical,
		.payload = publication_new_raw,
		.length = SWAPZ_BLOCK_BYTES,
		.raw = 1,
	};
	publication_engine.authority = &a;
	publication_engine.io.opaque = &control;
	publication_engine.io.write_run = publication_lower_write;
	publication_engine.io.read_blocks = publication_lower_read;
	publication_engine.io.write_sealed = publication_write_sealed;
	publication_engine.io.write_published = publication_write_published;
	publication_engine.read_scratch = publication_read_scratch;
	publication_engine.bulk_scratch = publication_bulk_bytes;
	publication_engine.bulk_txs = publication_transactions;
	publication_engine.bulk_enabled = 1;

	/* One 4KiB media prefix really lands before -EIO; the second block
	 * stays untouched. No paused snapshot may become a new mapping. */
	committed_pages = 99;
	error = swapz_engine_write_window_batched(&publication_engine,
						   replacement, 3, &committed_pages);
	expectation = (struct publication_expectation){
		.lower_runs = 1,
		.sealed_calls = 1,
		.sealed_pages = 3,
		.published_calls = 0,
		.published_pages = 0,
		.committed_pages = 0,
		.next_block = 4,
		.committed_blocks = 2,
		.abandoned_blocks = 2,
		.submitted_blocks = 2,
		.completed_blocks = 1,
		.bulk_writes = 0,
		.bulk_extents = 0,
		.bulk_mixed_runs = 0,
		.bulk_raw_entries = 0,
	};
	REQUIRE_PUBLICATION(error == -EIO &&
			    committed_pages == expectation.committed_pages,
			    "mixed_batch_replace", UINT32_MAX - 1U,
			    "lower_prefix_eio", -EIO, error);
	REQUIRE_PUBLICATION(control.lower_runs == expectation.lower_runs &&
			    control.sealed_calls == expectation.sealed_calls &&
			    control.sealed_pages == expectation.sealed_pages &&
			    control.published_calls == expectation.published_calls &&
			    control.published_pages == expectation.published_pages &&
			    !control.ownership_violations &&
			    control.failed_start == 2 && control.failed_blocks == 2,
			    "mixed_batch_replace", UINT32_MAX - 1U,
			    "staged_unpublished", -EIO, error);
	REQUIRE_PUBLICATION(!a.in_flight && !a.batch_pending &&
			    a.committed_blocks == expectation.committed_blocks &&
			    a.abandoned_blocks == expectation.abandoned_blocks &&
			    a.next_block == expectation.next_block &&
			    publication_engine.submitted_blocks ==
				    expectation.submitted_blocks &&
			    publication_engine.completed_blocks ==
				    expectation.completed_blocks &&
			    publication_engine.bulk_writes ==
				    expectation.bulk_writes &&
			    publication_engine.bulk_extents ==
				    expectation.bulk_extents &&
			    publication_engine.bulk_mixed_runs ==
				    expectation.bulk_mixed_runs &&
			    publication_engine.bulk_raw_entries ==
				    expectation.bulk_raw_entries &&
			    maps[0].generation == retained_raw.generation &&
			    maps[1].generation == retained_compressed.generation &&
			    !memcmp(&maps[0], &retained_raw, sizeof(retained_raw)) &&
			    !memcmp(&maps[1], &retained_compressed,
				    sizeof(retained_compressed)) &&
			    !maps[2].valid && maps[2].generation == 0 &&
			    live[retained_raw.start_block] == 1 &&
			    live[retained_compressed.start_block] == 1 &&
			    !live[2] && !live[3] && !classes[2] && !classes[3],
			    "mixed_batch_replace", UINT32_MAX - 1U,
			    "reservation_quarantine", -EIO, error);
	REQUIRE_PUBLICATION(!memcmp(publication_media + 2U * stride,
				     publication_first_block, stride),
			    "mixed_batch_replace", UINT32_MAX - 1U,
			    "physical_prefix", -EIO, error);
	{
		static const swapz_u8 empty_block[SWAPZ_BLOCK_BYTES];

		REQUIRE_PUBLICATION(!memcmp(publication_media + 3U * stride,
					     empty_block, stride),
				    "mixed_batch_replace", UINT32_MAX - 1U,
				    "unwritten_suffix", -EIO, error);
	}

	error = swapz_verify_raw(
		&a, raw_logical,
		publication_media + (size_t)retained_raw.start_block * stride);
	REQUIRE_PUBLICATION(
		!memcmp(publication_media +
			(size_t)retained_raw.start_block * stride,
			publication_old_raw, stride) && !error,
		"raw_survivor_read", retained_raw.generation,
		"retained_authority", 0, error);

	error = swapz_engine_read_page(
		&publication_engine, compressed_logical, publication_readback,
		sizeof(publication_readback), &payload_length);
	REQUIRE_PUBLICATION(error == 0 && payload_length == sizeof(compressed) &&
			    !memcmp(publication_readback, compressed, payload_length),
			    "compressed_survivor_read",
			    retained_compressed.generation,
			    "retained_authority", 0, error);

	read_calls_before = control.read_calls;
	payload_length = 7;
	error = swapz_engine_read_page(
		&publication_engine, 2, publication_readback,
		sizeof(publication_readback), &payload_length);
	REQUIRE_PUBLICATION(error == -ESTALE && !payload_length &&
			    control.read_calls == read_calls_before,
			    "unpublished_newcomer_read", maps[2].generation,
			    "unpublished_bytes", -ESTALE, error);

	/* A retry takes a fresh physical reservation, changes both storage
	 * representations, and publishes exactly three logical generations. */
	committed_pages = 99;
	error = swapz_engine_write_window_batched(&publication_engine,
						   replacement, 3, &committed_pages);
	expectation = (struct publication_expectation){
		.lower_runs = 2,
		.sealed_calls = 2,
		.sealed_pages = 6,
		.published_calls = 1,
		.published_pages = 3,
		.committed_pages = 3,
		.next_block = 6,
		.committed_blocks = 4,
		.abandoned_blocks = 2,
		.submitted_blocks = 4,
		.completed_blocks = 3,
		.bulk_writes = 1,
		.bulk_extents = 2,
		.bulk_mixed_runs = 1,
		.bulk_raw_entries = 1,
	};
	REQUIRE_PUBLICATION(!error &&
			    committed_pages == expectation.committed_pages &&
			    control.lower_runs == expectation.lower_runs &&
			    control.sealed_calls == expectation.sealed_calls &&
			    control.sealed_pages == expectation.sealed_pages &&
			    control.published_calls == expectation.published_calls &&
			    control.published_pages == expectation.published_pages &&
			    !control.ownership_violations &&
			    !a.in_flight && !a.batch_pending &&
			    a.committed_blocks == expectation.committed_blocks &&
			    a.abandoned_blocks == expectation.abandoned_blocks &&
			    a.next_block == expectation.next_block &&
			    publication_engine.submitted_blocks ==
				    expectation.submitted_blocks &&
			    publication_engine.completed_blocks ==
				    expectation.completed_blocks &&
			    publication_engine.bulk_writes ==
				    expectation.bulk_writes &&
			    publication_engine.bulk_extents ==
				    expectation.bulk_extents &&
			    publication_engine.bulk_mixed_runs ==
				    expectation.bulk_mixed_runs &&
			    publication_engine.bulk_raw_entries ==
				    expectation.bulk_raw_entries &&
			    !live[retained_raw.start_block] &&
			    !live[retained_compressed.start_block] &&
			    maps[0].valid && !maps[0].raw &&
			    maps[0].generation == UINT32_MAX - 1U &&
			    maps[1].valid && maps[1].raw &&
			    maps[1].generation == UINT32_MAX - 1U &&
			    maps[2].valid && !maps[2].raw && maps[2].generation == 1,
			    "mixed_batch_retry", UINT32_MAX - 1U,
			    "retry_publication", 0, error);
	first_retry_block = maps[0].start_block;
	REQUIRE_PUBLICATION(first_retry_block == 4 && maps[1].start_block == 5 &&
			    live[first_retry_block] == 2 && live[5] == 1,
			    "mixed_batch_retry", UINT32_MAX - 1U,
			    "retry_reservation", 0, error);

	error = swapz_engine_read_page(
		&publication_engine, 0, publication_readback,
		sizeof(publication_readback), &payload_length);
	REQUIRE_PUBLICATION(
		error == 0 &&
		payload_length == sizeof(publication_new_compressed[0]) &&
		!memcmp(publication_readback, publication_new_compressed[0],
			payload_length),
		"compressed_replacement_read", maps[0].generation,
		"published_authority", 0, error);

	error = swapz_engine_read_page(
		&publication_engine, 2, publication_readback,
		sizeof(publication_readback), &payload_length);
	REQUIRE_PUBLICATION(
		error == 0 &&
		payload_length == sizeof(publication_new_compressed[1]) &&
		!memcmp(publication_readback, publication_new_compressed[1],
			payload_length),
		"newcomer_read", maps[2].generation,
		"published_authority", 0, error);

	error = swapz_verify_raw(
		&a, compressed_logical,
		publication_media + (size_t)maps[1].start_block * stride);
	REQUIRE_PUBLICATION(
		!memcmp(publication_media + (size_t)maps[1].start_block * stride,
			publication_new_raw, stride) && !error,
		"raw_replacement_read", maps[1].generation,
		"published_authority", 0, error);

	/* DISCARD takes the last available generation without reviving bytes.
	 * Neither a second DISCARD nor WRITE may wrap that logical generation. */
	error = swapz_discard_page(&a, compressed_logical);
	REQUIRE_PUBLICATION(error == 0 && !maps[1].valid &&
			    maps[1].generation == UINT32_MAX && !live[5],
			    "discard", UINT32_MAX, "publish_invalidation", 0, error);

	error = swapz_discard_page(&a, compressed_logical);
	REQUIRE_PUBLICATION(error == -EOVERFLOW,
			    "discard", maps[1].generation,
			    "generation_rollover_refusal", -EOVERFLOW, error);

	error = swapz_stage(&a, &compressed_logical, 1, 1, &transaction);
	REQUIRE_PUBLICATION(error == -EOVERFLOW &&
			    !a.in_flight && a.next_block == expectation.next_block &&
			    maps[0].valid && maps[0].generation == UINT32_MAX - 1U &&
			    maps[2].valid && maps[2].generation == 1 &&
			    live[first_retry_block] == 2 &&
			    a.committed_blocks == expectation.committed_blocks &&
			    a.abandoned_blocks == expectation.abandoned_blocks,
			    "write_stage", maps[1].generation,
			    "generation_rollover_refusal", -EOVERFLOW, error);
	return 0;
}
#undef REQUIRE_PUBLICATION


int main(void)
{
	int passed = 0;

	CHECK(test_page_identity_mutation() == 0); passed++;
	CHECK(test_generation_identity_mutation() == 0); passed++;
	CHECK(test_bound_compressed_metadata_is_transaction_identity() == 0); passed++;
	CHECK(test_data_only_payload_publishes_from_bound_ram_metadata() == 0); passed++;
	CHECK(test_last_sibling_mutation_is_all_or_nothing() == 0); passed++;
	CHECK(test_duplicate_media_descriptor_fails_closed() == 0); passed++;
	CHECK(test_mutated_replacement_preserves_prior_authority() == 0); passed++;
	CHECK(test_engine_extent_geometry_before_lower_read() == 0); passed++;
	CHECK(test_fua_failure_preserves_prior_generation() == 0); passed++;
	CHECK(test_zero_overwrite_fua_fences_before_zero_publication() == 0); passed++;
	CHECK(test_short_completion_preserves_prior_generation() == 0); passed++;
	CHECK(test_torn_mixed_replacement_discard_generation_rollover() == 0); passed++;
	printf("SWAPZ_TX_IMMUTABLE_SNAPSHOT_TESTS_PASS=%d\n", passed);
	return 0;
}
