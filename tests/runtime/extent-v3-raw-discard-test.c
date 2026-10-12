// SPDX-License-Identifier: GPL-2.0-only
/*
 * Exact authority.c source test: raw swap fallback, byte-exact logical
 * generation changes, failed/partial raw writes, discard and old live counts.
 * Never opens a block device or loads a Device Mapper target.
 */
#include <stdio.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include "../../kernel/extent-v3/authority.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", \
	__FILE__, __LINE__, #x); return 1; } } while (0)
#define NPHYS 1024U
static struct sv3_authority a;
static struct sv3_map maps[32];
static sv3_u16 live[NPHYS];
static sv3_u8 classes[NPHYS];
static sv3_u8 disk_page[SV3_BLOCK_BYTES];

static int init(void)
{
	return sv3_authority_init(&a, maps, live, classes, 32, NPHYS);
}

static int stage_raw(sv3_u32 page, struct sv3_tx *tx)
{
	return sv3_stage(&a, &page, 1, 1, tx);
}

static int test_raw_write_publish_and_overwrite(void)
{
	struct sv3_tx tx;
	struct sv3_map first;

	CHECK(init() == 0);
	CHECK(stage_raw(2, &tx) == 0);
	CHECK(tx.start_block == 0 && tx.records[0].generation == 1);
	memset(disk_page, 0xa5, sizeof(disk_page));
	CHECK(sv3_finish_raw(&a, &tx, 1, 0) == 0);
	CHECK(maps[2].valid && maps[2].raw && maps[2].extent_blocks == 1);
	CHECK(maps[2].generation == 1 && live[0] == 1 && classes[0] == 1);
	first = maps[2];
	CHECK(stage_raw(2, &tx) == 0);
	CHECK(tx.start_block == 1 && tx.records[0].generation == 2);
	CHECK(sv3_finish_raw(&a, &tx, 1, 0) == 0);
	CHECK(maps[2].valid && maps[2].raw && maps[2].generation == 2);
	CHECK(maps[2].start_block == 1 && !live[first.start_block]);
	CHECK(live[1] == 1 && classes[1] == 1);
	CHECK(sv3_discard_page(&a, 2) == 0);
	CHECK(!maps[2].valid && maps[2].generation == 3 && !live[1]);
	return 0;
}

static int test_short_write_does_not_publish(void)
{
	struct sv3_tx tx;
	struct sv3_map old;

	CHECK(init() == 0);
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(sv3_finish_raw(&a, &tx, 1, 0) == 0);
	old = maps[3];
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(sv3_finish_raw(&a, &tx, 0, -EIO) == -EIO);
	CHECK(maps[3].start_block == old.start_block);
	CHECK(maps[3].generation == old.generation && live[old.start_block] == 1);
	CHECK(!live[tx.start_block] && a.abandoned_blocks == 1);
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(tx.start_block == 2);
	CHECK(sv3_finish_raw(&a, &tx, 0, 0) == -EIO);
	CHECK(maps[3].start_block == old.start_block &&
	      maps[3].generation == old.generation);
	CHECK(a.abandoned_blocks == 2 && !a.in_flight);
	return 0;
}

static int test_mutated_raw_token_does_not_publish(void)
{
	struct sv3_tx tx;

	CHECK(init() == 0);
	CHECK(stage_raw(0, &tx) == 0);
	tx.records[0].logical_page = 1;
	CHECK(sv3_finish_raw(&a, &tx, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[0].valid && !maps[1].valid);
	tx.records[0].logical_page = 0;
	CHECK(sv3_abort(&a, &tx) == 0);
	CHECK(!a.in_flight);
	return 0;
}

static int test_raw_descriptor_reads_fail_closed(void)
{
	struct sv3_tx tx;
	struct sv3_decoded decoded;
	const sv3_u8 *payload;

	CHECK(init() == 0);
	CHECK(stage_raw(0, &tx) == 0);
	CHECK(sv3_finish_raw(&a, &tx, 1, 0) == 0);
	CHECK(sv3_read_authoritative(&a, 0, &maps[0], disk_page, 4096,
				     &decoded, &payload) == -EOPNOTSUPP);
	return 0;
}

static int test_discard_generation_overflow_fails_without_mutation(void)
{
	CHECK(init() == 0);
	maps[0].generation = UINT32_MAX;
	CHECK(sv3_discard_page(&a, 0) == -EOVERFLOW);
	CHECK(maps[0].generation == UINT32_MAX && !maps[0].valid);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_raw_write_publish_and_overwrite() == 0); passed++;
	CHECK(test_short_write_does_not_publish() == 0); passed++;
	CHECK(test_mutated_raw_token_does_not_publish() == 0); passed++;
	CHECK(test_raw_descriptor_reads_fail_closed() == 0); passed++;
	CHECK(test_discard_generation_overflow_fails_without_mutation() == 0); passed++;
	printf("SV3_RAW_DISCARD_AUTHORITY_TESTS_PASS=%d\n", passed);
	return 0;
}
