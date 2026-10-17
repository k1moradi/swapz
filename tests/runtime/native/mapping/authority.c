// SPDX-License-Identifier: GPL-2.0-only
/*
 * The exact kernel/extent-v3/{codec,authority}.c are compiled into this
 * userspace executable. Covers authority publication and torn-write rollback.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "authority.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct sv3_authority authority;
static struct sv3_map maps[128];
static sv3_u16 live[2048];
static sv3_u8 classes[2048];
static sv3_u8 extent[SV3_MAX_EXTENT_BYTES];
static sv3_u8 previous_extent[SV3_MAX_EXTENT_BYTES];
static sv3_u8 content[2072];

static int init(void)
{
	return sv3_authority_init(&authority, maps, live, classes, 64, 2048);
}

static int encode(const struct sv3_tx *tx)
{
	struct sv3_builder b;
	sv3_u8 index;

	if (sv3_begin(&b, extent,
		      (sv3_u32)tx->extent_blocks * SV3_BLOCK_BYTES,
		      tx->sequence))
		return 1;
	for (index = 0; index < tx->count; ++index) {
		memset(content, (int)(tx->records[index].logical_page + 1U),
		       sizeof(content));
		if (sv3_append(&b, tx->records[index].logical_page,
			       tx->records[index].generation,
			       content, sizeof(content)))
			return 1;
	}
	return sv3_seal(&b) != 0;
}

static int test_initial_rejects_unsafe_capacity(void)
{
	struct sv3_authority a;

	CHECK(sv3_authority_init(&a, maps, live, classes, 64, 512) == -EINVAL);
	CHECK(sv3_authority_init(&a, maps, live, classes, 500, 768) == -ENOSPC);
	CHECK(sv3_authority_init(&a, maps, live, classes, 64, 769) == -EINVAL);
	CHECK(sv3_authority_init(&a, maps, live, classes, 64, 768) == 0);
	CHECK(a.reserve_blocks == 512);
	CHECK(a.next_block == 0);
	return 0;
}

static int test_full_publish_and_authoritative_reads(void)
{
	const sv3_u32 pages[] = {0, 1, 2, 3, 4, 5, 6};
	struct sv3_tx tx;
	struct sv3_decoded decoded;
	const sv3_u8 *payload;
	struct sv3_map observed;
	sv3_u32 index;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 7, 4, &tx) == 0);
	CHECK(authority.in_flight && tx.start_block == 0 &&
	      tx.sequence == 1 && authority.next_block == 4);
	CHECK(sv3_stage(&authority, pages, 7, 4, &tx) == -EBUSY);
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&authority, &tx, extent, 16384, 4, 0) == 0);
	CHECK(!authority.in_flight && authority.committed_blocks == 4);
	CHECK(live[0] == 7 && classes[0] == 4);

	for (index = 0; index < 7; ++index) {
		observed = maps[index];
		CHECK(observed.valid && observed.start_block == 0 &&
		      observed.generation == 1 && observed.record_index == index &&
		      observed.extent_blocks == 4 && observed.sequence == 1);
		CHECK(sv3_read_authoritative(&authority, index, &observed,
					    extent, 16384, &decoded, &payload) == 0);
		CHECK(decoded.logical_page == index && decoded.generation == 1);
		CHECK(observed.payload_offset == decoded.payload_offset);
		CHECK(payload[0] == index + 1 && payload[2071] == index + 1);
		if (index == 0) {
			struct sv3_map forged = observed;

			forged.payload_offset++;
			CHECK(sv3_read_authoritative(&authority, index, &forged,
					    extent, 16384,
					    &decoded, &payload) == -ESTALE);
		}
	}
	CHECK(sv3_finish(&authority, &tx, extent, 16384, 4, 0) == -ESTALE);
	return 0;
}

static int test_peeked_authoritative_read_rechecks_payload_and_sequence(void)
{
	const sv3_u32 pages[] = {0, 1, 2};
	struct sv3_tx tx;
	struct sv3_decoded peeked, forged;
	struct sv3_map observed;
	const sv3_u8 *payload = NULL;
	sv3_u16 offset;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 3, 2, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&authority, &tx, extent, 8192, 2, 0) == 0);
	observed = maps[1];
	CHECK(sv3_peek(extent, 8192, observed.record_index, &peeked) == 0);
	CHECK(sv3_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == 0);
	CHECK(payload && payload[0] == 2 && payload[2071] == 2);

	offset = peeked.payload_offset;
	extent[offset] ^= 0x40;
	payload = (const sv3_u8 *)1;
	CHECK(sv3_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == -EBADMSG);
	CHECK(payload == NULL);
	extent[offset] ^= 0x40;

	forged = peeked;
	forged.generation++;
	CHECK(sv3_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &forged, &payload) == -EUCLEAN);
	extent[8] ^= 0x40; /* sequence bytes are rechecked after the peek */
	CHECK(sv3_read_authoritative_peeked(&authority, 1, &observed,
					    extent, 8192,
					    &peeked, &payload) == -EUCLEAN);
	extent[8] ^= 0x40;
	return 0;
}

static int test_torn_write_no_old_mapping_invalidation(void)
{
	const sv3_u32 pages[] = {0, 1, 2};
	struct sv3_tx first, pending, later;
	struct sv3_map original;
	sv3_u32 new_page[] = {7};

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 3, 2, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(sv3_finish(&authority, &first, extent, 8192, 2, 0) == 0);
	original = maps[0];
	CHECK(live[0] == 3);
	CHECK(sv3_stage(&authority, pages, 3, 2, &pending) == 0);
	CHECK(pending.start_block == 2 && pending.records[0].generation == 2);
	CHECK(encode(&pending) == 0);
	CHECK(sv3_finish(&authority, &pending, extent, 8192, 1, -EIO) == -EIO);
	CHECK(maps[0].start_block == original.start_block &&
	      maps[0].generation == 1 && live[0] == 3);
	CHECK(live[2] == 0 && authority.abandoned_blocks == 2);
	CHECK(sv3_stage(&authority, new_page, 1, 2, &later) == 0);
	CHECK(later.start_block == 4); /* never reuse torn location */
	CHECK(sv3_abort(&authority, &later) == 0);
	CHECK(authority.abandoned_blocks == 4);
	return 0;
}

static int test_overwrite_generation_and_liveness(void)
{
	const sv3_u32 original_pages[] = {0, 1, 2, 3, 4, 5, 6};
	const sv3_u32 overwritten[] = {0, 1, 2};
	struct sv3_tx first, second;
	struct sv3_map old;
	struct sv3_decoded decoded;
	const sv3_u8 *payload;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, original_pages, 7, 4, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(sv3_finish(&authority, &first, extent, 16384, 4, 0) == 0);
	memcpy(previous_extent, extent, 16384);
	old = maps[0];

	CHECK(sv3_stage(&authority, overwritten, 3, 2, &second) == 0);
	CHECK(second.start_block == 4 && second.sequence == 2);
	CHECK(second.records[0].generation == 2);
	CHECK(encode(&second) == 0);
	CHECK(sv3_finish(&authority, &second, extent, 8192, 2, 0) == 0);
	CHECK(live[0] == 4 && live[4] == 3);
	CHECK(classes[0] == 4 && classes[4] == 2);
	CHECK(maps[0].generation == 2 && maps[3].generation == 1);
	CHECK(sv3_read_authoritative(&authority, 0, &old,
				    previous_extent, 16384,
				    &decoded, &payload) == -ESTALE);
	CHECK(sv3_read_authoritative(&authority, 0, &maps[0],
				    extent, 8192, &decoded, &payload) == 0);
	CHECK(decoded.generation == 2 && decoded.logical_page == 0);
	CHECK(sv3_read_authoritative(&authority, 3, &maps[3],
				    previous_extent, 16384,
				    &decoded, &payload) == 0);
	return 0;
}

static int test_last_corrupt_sibling_prevents_all_publication(void)
{
	const sv3_u32 pages[] = {0, 1, 2};
	struct sv3_tx first, second;
	struct sv3_map snapshot[3];
	struct sv3_decoded decoded;
	const sv3_u8 *payload;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 3, 2, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(sv3_finish(&authority, &first, extent, 8192, 2, 0) == 0);
	memcpy(snapshot, maps, sizeof(snapshot));
	CHECK(sv3_stage(&authority, pages, 3, 2, &second) == 0);
	CHECK(encode(&second) == 0);
	CHECK(sv3_lookup(extent, 8192, 2, &decoded, &payload) == 0);
	extent[decoded.payload_offset] ^= 0x80; /* third record CRC failure */
	CHECK(sv3_finish(&authority, &second, extent, 8192, 2, 0) == -EBADMSG);
	CHECK(memcmp(snapshot, maps, sizeof(snapshot)) == 0);
	CHECK(live[0] == 3 && live[2] == 0);
	CHECK(authority.abandoned_blocks == 2 && !authority.in_flight);
	return 0;
}

static int test_header_corruption_and_wrong_sequence(void)
{
	const sv3_u32 pages[] = {0};
	struct sv3_tx first, second;
	struct sv3_map original;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 1, 1, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(sv3_finish(&authority, &first, extent, 4096, 1, 0) == 0);
	original = maps[0];

	CHECK(sv3_stage(&authority, pages, 1, 1, &second) == 0);
	CHECK(encode(&second) == 0);
	extent[8] ^= 0x40; /* metadata sequence, not payload */
	CHECK(sv3_finish(&authority, &second, extent, 4096, 1, 0) == -EBADMSG);
	CHECK(maps[0].generation == original.generation);
	CHECK(maps[0].start_block == original.start_block);
	CHECK(authority.abandoned_blocks == 1);
	return 0;
}

static int test_generation_overflow_and_duplicate_rejections(void)
{
	const sv3_u32 duplicate[] = {4, 4};
	const sv3_u32 good[] = {4};
	const sv3_u32 invalid[] = {128};
	struct sv3_tx tx;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, duplicate, 2, 2, &tx) == -EEXIST);
	CHECK(sv3_stage(&authority, invalid, 1, 2, &tx) == -ERANGE);
	CHECK(sv3_stage(&authority, good, 0, 2, &tx) == -EINVAL);
	CHECK(sv3_stage(&authority, good, 1, 3, &tx) == -EINVAL);
	maps[4].generation = UINT32_MAX;
	CHECK(sv3_stage(&authority, good, 1, 2, &tx) == -EOVERFLOW);
	CHECK(authority.next_block == 0 && authority.in_flight == 0);
	return 0;
}

static int test_allocator_reserve_exhaustion(void)
{
	struct sv3_tx tx;
	const sv3_u32 pages[] = {0};
	unsigned int i;

	CHECK(init() == 0);
	for (i = 0; i < 384; ++i) {
		CHECK(sv3_stage(&authority, pages, 1, 4, &tx) == 0);
		CHECK(tx.start_block == i * 4);
		CHECK(tx.start_block % 4 == 0);
		CHECK(tx.start_block % 256 <= 252);
		CHECK(sv3_abort(&authority, &tx) == 0);
	}
	CHECK(authority.next_block == 1536);
	CHECK(authority.reserve_blocks == 512);
	CHECK(authority.abandoned_blocks == 1536);
	CHECK(sv3_stage(&authority, pages, 1, 4, &tx) == -ENOSPC);
	CHECK(!authority.in_flight);
	return 0;
}

static int test_short_write_always_quarantines(void)
{
	const sv3_u32 pages[] = {9};
	struct sv3_tx tx;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 1, 4, &tx) == 0);
	CHECK(encode(&tx) == 0);
	CHECK(sv3_finish(&authority, &tx, extent, 16384, 3, 0) == -EIO);
	CHECK(!maps[9].valid && authority.abandoned_blocks == 4);
	CHECK(sv3_stage(&authority, pages, 1, 4, &tx) == 0);
	CHECK(tx.start_block == 4);
	CHECK(sv3_abort(&authority, &tx) == 0);
	return 0;
}

static int test_old_liveness_corruption_fail_closed(void)
{
	const sv3_u32 pages[] = {0};
	struct sv3_tx first, second;
	struct sv3_map old;

	CHECK(init() == 0);
	CHECK(sv3_stage(&authority, pages, 1, 1, &first) == 0);
	CHECK(encode(&first) == 0);
	CHECK(sv3_finish(&authority, &first, extent, 4096, 1, 0) == 0);
	old = maps[0];
	live[0] = 0; /* fault injection: corrupted runtime refcount */
	CHECK(sv3_stage(&authority, pages, 1, 1, &second) == 0);
	CHECK(encode(&second) == 0);
	CHECK(sv3_finish(&authority, &second, extent, 4096, 1, 0) == -EUCLEAN);
	CHECK(maps[0].start_block == old.start_block &&
	      maps[0].generation == old.generation);
	CHECK(live[1] == 0 && authority.abandoned_blocks == 1);
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_initial_rejects_unsafe_capacity() == 0); passed++;
	CHECK(test_full_publish_and_authoritative_reads() == 0); passed++;
	CHECK(test_peeked_authoritative_read_rechecks_payload_and_sequence() == 0); passed++;
	CHECK(test_torn_write_no_old_mapping_invalidation() == 0); passed++;
	CHECK(test_overwrite_generation_and_liveness() == 0); passed++;
	CHECK(test_last_corrupt_sibling_prevents_all_publication() == 0); passed++;
	CHECK(test_header_corruption_and_wrong_sequence() == 0); passed++;
	CHECK(test_generation_overflow_and_duplicate_rejections() == 0); passed++;
	CHECK(test_allocator_reserve_exhaustion() == 0); passed++;
	CHECK(test_short_write_always_quarantines() == 0); passed++;
	CHECK(test_old_liveness_corruption_fail_closed() == 0); passed++;
	printf("SV3_EXACT_AUTHORITY_TESTS_PASS=%d\n", passed);
	return 0;
}
