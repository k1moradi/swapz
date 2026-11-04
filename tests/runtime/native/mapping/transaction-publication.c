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
	/* Preserve the valid boundary: two blocks ending at media end. */
	maps[0].extent_blocks = 2;
	maps[0].start_block = PHYSICAL - 2U;
	CHECK(swapz_engine_required_read_range(&engine, &logical, 1,
		maps[0].start_block, 2, &first_block, &blocks) == 0);
	CHECK(first_block == 0 && blocks == 1);
	CHECK(invalid_extent_read_calls == 0);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_page_identity_mutation() == 0); passed++;
	CHECK(test_generation_identity_mutation() == 0); passed++;
	CHECK(test_last_sibling_mutation_is_all_or_nothing() == 0); passed++;
	CHECK(test_duplicate_media_descriptor_fails_closed() == 0); passed++;
	CHECK(test_mutated_replacement_preserves_prior_authority() == 0); passed++;
	CHECK(test_engine_extent_geometry_before_lower_read() == 0); passed++;
	printf("SWAPZ_TX_IMMUTABLE_SNAPSHOT_TESTS_PASS=%d\n", passed);
	return 0;
}
