// SPDX-License-Identifier: GPL-2.0-only
/*
 * Main-developer regression for Codex's independently reproduced stage/finish
 * transaction-record identity substitution. Uses EXACT production C, not
 * a mock of sv3_finish. Failure must leave the originally staged transaction
 * active and must not publish ANY of the substituted caller-provided records.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "authority.h"

#define CHECK(expr) do { \
	if (!(expr)) { \
		fprintf(stderr, "%s:%d FAILED: %s\n", __FILE__, __LINE__, #expr); \
		return 1; \
	} \
} while (0)

#define LOGICAL 64
#define PHYSICAL 2048

static struct sv3_authority a;
static struct sv3_map maps[LOGICAL];
static sv3_u16 live[PHYSICAL];
static sv3_u8 classes[PHYSICAL];
static sv3_u8 bytes[SV3_MAX_EXTENT_BYTES];
static sv3_u8 compressed[2072];

static int init(void)
{
	return sv3_authority_init(&a, maps, live, classes,
				 LOGICAL, PHYSICAL);
}

static int encode(const struct sv3_tx *tx)
{
	struct sv3_builder b;
	sv3_u8 i;

	memset(compressed, 0x5a, sizeof(compressed));
	if (sv3_begin(&b, bytes, tx->extent_blocks * SV3_BLOCK_BYTES,
		      tx->sequence))
		return 1;
	for (i = 0; i < tx->count; ++i)
		if (sv3_append(&b, tx->records[i].logical_page,
			       tx->records[i].generation,
			       compressed, sizeof(compressed)))
			return 1;
	return sv3_seal(&b);
}

static int test_page_identity_mutation(void)
{
	const sv3_u32 pages[] = {0};
	struct sv3_tx tx;

	CHECK(init() == 0);
	CHECK(sv3_stage(&a, pages, 1, 1, &tx) == 0);
	CHECK(tx.records[0].logical_page == 0);
	tx.records[0].logical_page = 1;
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, SV3_BLOCK_BYTES, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[0].valid && !maps[1].valid);
	CHECK(a.committed_blocks == 0 && a.abandoned_blocks == 0);
	/* Wrong caller handle must also fail to abort the valid transaction. */
	CHECK(sv3_abort(&a, &tx) == -ESTALE);
	CHECK(a.in_flight);
	tx.records[0].logical_page = 0;
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, SV3_BLOCK_BYTES, 1, 0) == 0);
	CHECK(!a.in_flight && maps[0].valid && maps[0].generation == 1);
	CHECK(!maps[1].valid && live[0] == 1);
	return 0;
}

static int test_generation_identity_mutation(void)
{
	const sv3_u32 pages[] = {3};
	struct sv3_tx tx;

	CHECK(init() == 0);
	CHECK(sv3_stage(&a, pages, 1, 1, &tx) == 0);
	tx.records[0].generation++;
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, SV3_BLOCK_BYTES, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[3].valid);
	CHECK(sv3_abort(&a, &tx) == -ESTALE);
	tx.records[0].generation--;
	CHECK(sv3_abort(&a, &tx) == 0);
	CHECK(!a.in_flight && a.abandoned_blocks == 1);
	CHECK(!maps[3].valid);
	return 0;
}

static int test_last_sibling_mutation_is_all_or_nothing(void)
{
	const sv3_u32 pages[] = {0, 1, 2};
	struct sv3_tx tx;
	struct sv3_map before[LOGICAL];

	CHECK(init() == 0);
	CHECK(sv3_stage(&a, pages, 3, 2, &tx) == 0);
	tx.records[2].logical_page = 9;
	CHECK(encode(&tx) == 0);
	memcpy(before, maps, sizeof(before));
	CHECK(sv3_finish(&a, &tx, bytes, 8192, 2, 0) == -ESTALE);
	CHECK(memcmp(before, maps, sizeof(before)) == 0);
	CHECK(a.in_flight && !live[0]);
	tx.records[2].logical_page = 2;
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, 8192, 2, 0) == 0);
	CHECK(maps[0].valid && maps[1].valid && maps[2].valid);
	CHECK(!maps[9].valid && live[0] == 3);
	return 0;
}

static int test_mutated_replacement_preserves_prior_authority(void)
{
	const sv3_u32 pages[] = {0};
	struct sv3_tx tx;
	struct sv3_map old;

	CHECK(init() == 0);
	CHECK(sv3_stage(&a, pages, 1, 1, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, 4096, 1, 0) == 0);
	old = maps[0];

	CHECK(sv3_stage(&a, pages, 1, 1, &tx) == 0);
	tx.records[0].logical_page = 1;
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&a, &tx, bytes, 4096, 1, 0) == -ESTALE);
	CHECK(maps[0].start_block == old.start_block);
	CHECK(maps[0].generation == old.generation && !maps[1].valid);
	CHECK(live[old.start_block] == 1 && a.in_flight);
	tx.records[0].logical_page = 0;
	CHECK(sv3_abort(&a, &tx) == 0);
	CHECK(maps[0].generation == 1 &&
	      live[old.start_block] == 1 && a.abandoned_blocks == 1);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_page_identity_mutation() == 0); passed++;
	CHECK(test_generation_identity_mutation() == 0); passed++;
	CHECK(test_last_sibling_mutation_is_all_or_nothing() == 0); passed++;
	CHECK(test_mutated_replacement_preserves_prior_authority() == 0); passed++;
	printf("SV3_TX_IMMUTABLE_SNAPSHOT_TESTS_PASS=%d\n", passed);
	return 0;
}
