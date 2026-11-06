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
#include "authority.h"
#include "flush-qual.h"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "%s:%d: %s\n", \
	__FILE__, __LINE__, #x); return 1; } } while (0)
#define NPHYS 1024U
static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[NPHYS];
static swapz_u8 classes[NPHYS];
static swapz_u8 disk_page[SWAPZ_BLOCK_BYTES];

static int init(void)
{
	return swapz_authority_init(&a, maps, live, classes, 32, NPHYS);
}

static int stage_raw(swapz_u32 page, struct swapz_tx *tx)
{
	return swapz_stage(&a, &page, 1, 1, tx);
}

static int test_raw_write_publish_and_overwrite(void)
{
	struct swapz_tx tx;
	struct swapz_map first;

	CHECK(init() == 0);
	CHECK(stage_raw(2, &tx) == 0);
	CHECK(tx.start_block == 0 && tx.records[0].generation == 1);
	memset(disk_page, 0xa5, sizeof(disk_page));
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	CHECK(maps[2].valid && maps[2].raw && maps[2].extent_blocks == 1);
	CHECK(maps[2].generation == 1 && live[0] == 1 && classes[0] == 1);
	first = maps[2];
	CHECK(stage_raw(2, &tx) == 0);
	CHECK(tx.start_block == 1 && tx.records[0].generation == 2);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	CHECK(maps[2].valid && maps[2].raw && maps[2].generation == 2);
	CHECK(maps[2].start_block == 1 && !live[first.start_block]);
	CHECK(live[1] == 1 && classes[1] == 1);
	CHECK(swapz_discard_page(&a, 2) == 0);
	CHECK(!maps[2].valid && maps[2].generation == 3 && !live[1]);
	return 0;
}

static int test_short_write_does_not_publish(void)
{
	struct swapz_tx tx;
	struct swapz_map old;

	CHECK(init() == 0);
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	old = maps[3];
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 0, -EIO) == -EIO);
	CHECK(maps[3].start_block == old.start_block);
	CHECK(maps[3].generation == old.generation && live[old.start_block] == 1);
	CHECK(!live[tx.start_block] && a.abandoned_blocks == 1);
	CHECK(stage_raw(3, &tx) == 0);
	CHECK(tx.start_block == 2);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 0, 0) == -EIO);
	CHECK(maps[3].start_block == old.start_block &&
	      maps[3].generation == old.generation);
	CHECK(a.abandoned_blocks == 2 && !a.in_flight);
	return 0;
}

static int test_mutated_raw_token_does_not_publish(void)
{
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(stage_raw(0, &tx) == 0);
	tx.records[0].logical_page = 1;
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == -ESTALE);
	CHECK(a.in_flight && !maps[0].valid && !maps[1].valid);
	tx.records[0].logical_page = 0;
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(!a.in_flight);
	return 0;
}

static int test_raw_descriptor_reads_fail_closed(void)
{
	struct swapz_tx tx;
	struct swapz_map stale;
	struct swapz_decoded decoded = {0};
	const swapz_u8 *payload;

	CHECK(init() == 0);
	CHECK(stage_raw(0, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	CHECK(swapz_read_authoritative_peeked(&a, 0, &maps[0], disk_page, 4096,
					    &decoded, &payload) == -EOPNOTSUPP);
	stale = maps[0];
	stale.raw_crc32c ^= 1U;
	CHECK(swapz_read_authoritative_peeked(&a, 0, &stale, disk_page, 4096,
					    &decoded, &payload) == -ESTALE);
	return 0;
}

static int test_discard_generation_overflow_fails_without_mutation(void)
{
	CHECK(init() == 0);
	maps[0].generation = UINT32_MAX;
	CHECK(swapz_discard_page(&a, 0) == -EOVERFLOW);
	CHECK(maps[0].generation == UINT32_MAX && !maps[0].valid);
	return 0;
}


/*
 * Fault-inject a source extent that straddles a 1MiB segment or extends
 * beyond capacity. A direct DISCARD and completed COW must refuse it before
 * touching the old generation/reference or publishing the new raw mapping.
 */
static int test_corrupt_source_geometry_preserves_discard_authority(void)
{
	const swapz_u32 logical_page = 9U;
	int fault;

	for (fault = 0; fault < 2; ++fault) {
		const swapz_u32 invalid_start =
			fault ? NPHYS - 1U : SWAPZ_SEGMENT_BLOCKS - 1U;
		struct swapz_tx transaction;
		struct swapz_map original;
		int range_error, discard_error, finish_error;
		int invalidation_prevented;

		CHECK(init() == 0);
		maps[logical_page] = (struct swapz_map) {
			.start_block = invalid_start,
			.generation = 7U,
			.payload_length = 128U,
			.extent_blocks = 2U,
			.valid = 1U,
		};
		live[invalid_start] = 1U;
		classes[invalid_start] = 2U;
		original = maps[logical_page];

		range_error = swapz_prevalidate_discard_range(
			&a, logical_page, 1U);
		discard_error = swapz_discard_page(&a, logical_page);
		CHECK(stage_raw(logical_page, &transaction) == 0);
		finish_error = swapz_finish_raw(&a, &transaction, disk_page, 1U, 0);
		invalidation_prevented =
			!memcmp(&maps[logical_page], &original, sizeof(original)) &&
			live[invalid_start] == 1U &&
			classes[invalid_start] == 2U &&
			!live[transaction.start_block] &&
			!classes[transaction.start_block] &&
			!a.in_flight && a.abandoned_blocks == 1U;
		if (range_error != -EUCLEAN || discard_error != -EUCLEAN ||
		    finish_error != -EUCLEAN || !invalidation_prevented) {
			fprintf(stderr,
				"%s:%d: FAIL range=[9,10) expected_generation=7 "
				"expected_references=1 conflict=%s "
				"original_errnos=range:%d,discard:%d,finish:%d "
				"invalidation_prevented=%s\n",
				__FILE__, __LINE__,
				fault ? "physical_capacity_overrun" :
					"cross_segment_extent",
				range_error, discard_error, finish_error,
				invalidation_prevented ? "yes" : "no");
			return 1;
		}
	}
	return 0;
}

static int test_raw_page_crc_rejects_silent_corruption(void)
{
	struct swapz_tx tx;
	swapz_u32 original_crc;

	CHECK(init() == 0);
	memset(disk_page, 0x51, sizeof(disk_page));
	CHECK(stage_raw(4, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	CHECK(swapz_verify_raw(&a, 4, disk_page) == 0);
	original_crc = maps[4].raw_crc32c;
	CHECK(original_crc == swapz_crc32c_bytes(disk_page, 4096));
	disk_page[317] ^= 0x80;
	CHECK(swapz_verify_raw(&a, 4, disk_page) == -EBADMSG);
	CHECK(maps[4].valid && maps[4].generation == 1 &&
	      maps[4].raw_crc32c == original_crc);
	disk_page[317] ^= 0x80;
	CHECK(swapz_verify_raw(&a, 4, disk_page) == 0);
	CHECK(swapz_discard_page(&a, 4) == 0);
	CHECK(swapz_verify_raw(&a, 4, disk_page) == -EUCLEAN);
	return 0;
}

static int test_missing_raw_buffer_fails_closed(void)
{
	struct swapz_tx tx;

	CHECK(init() == 0);
	CHECK(stage_raw(5, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, NULL, 1, 0) == -EINVAL);
	CHECK(!a.in_flight && !maps[5].valid && a.abandoned_blocks == 1);
	return 0;
}

struct fua_failure_control {
	unsigned int calls;
	int error;
};

static int issue_fua(void *opaque)
{
	struct fua_failure_control *control = opaque;

	control->calls++;
	return control->error;
}

static int test_fua_failure_preserves_previous_raw_generation(void)
{
	struct swapz_tx tx;
	struct swapz_map previous;
	struct fua_failure_control control = { .error = -EIO };
	int error;

	CHECK(init() == 0);
	memset(disk_page, 0x52, sizeof(disk_page));
	CHECK(stage_raw(6, &tx) == 0);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	previous = maps[6];
	CHECK(stage_raw(6, &tx) == 0);
	/* Exact production FUA gate executes before the authority finish.
	 * The media WRITE succeeded, but the cache flush failed. */
	error = swapz_write_flush_before_publish(0, 1, issue_fua, &control);
	CHECK(error == -EIO && control.calls == 1);
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, error) == -EIO);
	CHECK(maps[6].valid && maps[6].generation == previous.generation &&
	      maps[6].start_block == previous.start_block);
	CHECK(live[previous.start_block] == 1 && !live[tx.start_block]);
	CHECK(!a.in_flight && a.abandoned_blocks == 1);
	return 0;
}

static int test_postpublication_flush_negative_control(void)
{
	struct swapz_tx tx;
	struct fua_failure_control control = { .error = -EIO };

	CHECK(init() == 0);
	CHECK(stage_raw(7, &tx) == 0);
	/* The former order (finish, then flush) already exposes generation 1
	 * before -EIO: this negative control demonstrates that ordering gap. */
	CHECK(swapz_finish_raw(&a, &tx, disk_page, 1, 0) == 0);
	CHECK(maps[7].valid && maps[7].generation == 1);
	CHECK(issue_fua(&control) == -EIO && control.calls == 1);
	CHECK(maps[7].valid && maps[7].generation == 1);
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
	CHECK(test_corrupt_source_geometry_preserves_discard_authority() == 0); passed++;
	CHECK(test_raw_page_crc_rejects_silent_corruption() == 0); passed++;
	CHECK(test_missing_raw_buffer_fails_closed() == 0); passed++;
	CHECK(test_fua_failure_preserves_previous_raw_generation() == 0); passed++;
	CHECK(test_postpublication_flush_negative_control() == 0); passed++;
	printf("SWAPZ_RAW_DISCARD_AUTHORITY_TESTS_PASS=%d\n", passed);
	return 0;
}
