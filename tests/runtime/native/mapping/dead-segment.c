// SPDX-License-Identifier: GPL-2.0-only
/*
 * Execute exact V3 kernel authority C in opt-in segment-reuse mode.
 * A still-referenced 4KiB block must NEVER be recycled, including when
 * its live_records count is fault-injected to zero.
 */
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "authority.h"
#include "gc-cost.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d FAIL: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

static struct swapz_authority a;
static struct swapz_map maps[32];
static swapz_u16 live[1280];
static swapz_u8 classes[1280];
static swapz_u8 roles[5];
static swapz_u32 mapped_pages[5];
static swapz_u32 program_counts[5];
static swapz_u32 gc_live_bytes[5];
static swapz_u32 gc_io_cost[5];
static swapz_u16 gc_min_live_blocks[5];
static swapz_u32 first_page[5];
static swapz_u32 last_page[5];
static swapz_u32 prev_page[32];
static swapz_u32 next_page[32];
static swapz_u8 bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 data[100];
static int recycle_hook_calls;
static swapz_u32 recycle_hook_last_segment;
static int recycle_hook_error;

/*
 * Compare the complete logical/physical ownership arrays, GC sidecars and
 * recycle-hook effects. Diagnostic probe counts and the intentionally consumed
 * in-flight extent are not ownership and may change on failed operations.
 */
struct authority_integrity_snapshot {
	struct swapz_map maps[32];
	swapz_u16 live[1280];
	swapz_u8 classes[1280];
	swapz_u8 roles[5];
	swapz_u32 mapped_pages[5];
	swapz_u32 program_counts[5];
	swapz_u32 gc_live_bytes[5];
	swapz_u32 gc_io_cost[5];
	swapz_u16 gc_min_live_blocks[5];
	swapz_u32 first_page[5];
	swapz_u32 last_page[5];
	swapz_u32 prev_page[32];
	swapz_u32 next_page[32];
	swapz_u32 next_block;
	swapz_u32 open_segment;
	swapz_u32 next_segment_probe;
	swapz_u32 recycled_dead_segments;
	swapz_u32 gc_destination;
	swapz_u32 gc_forbidden_open;
	swapz_u32 gc_forbidden_victim;
	swapz_u8 gc_allocation;
	int recycle_hook_calls;
	swapz_u32 recycle_hook_last_segment;
};

static struct authority_integrity_snapshot integrity_before;

static void snapshot_integrity(void)
{
	memcpy(integrity_before.maps, maps, sizeof(maps));
	memcpy(integrity_before.live, live, sizeof(live));
	memcpy(integrity_before.classes, classes, sizeof(classes));
	memcpy(integrity_before.roles, roles, sizeof(roles));
	memcpy(integrity_before.mapped_pages, mapped_pages,
	       sizeof(mapped_pages));
	memcpy(integrity_before.program_counts, program_counts,
	       sizeof(program_counts));
	memcpy(integrity_before.gc_live_bytes, gc_live_bytes,
	       sizeof(gc_live_bytes));
	memcpy(integrity_before.gc_io_cost, gc_io_cost, sizeof(gc_io_cost));
	memcpy(integrity_before.gc_min_live_blocks, gc_min_live_blocks,
	       sizeof(gc_min_live_blocks));
	memcpy(integrity_before.first_page, first_page, sizeof(first_page));
	memcpy(integrity_before.last_page, last_page, sizeof(last_page));
	memcpy(integrity_before.prev_page, prev_page, sizeof(prev_page));
	memcpy(integrity_before.next_page, next_page, sizeof(next_page));
	integrity_before.next_block = a.next_block;
	integrity_before.open_segment = a.open_segment;
	integrity_before.next_segment_probe = a.next_segment_probe;
	integrity_before.recycled_dead_segments = a.recycled_dead_segments;
	integrity_before.gc_destination = a.gc_destination;
	integrity_before.gc_forbidden_open = a.gc_forbidden_open;
	integrity_before.gc_forbidden_victim = a.gc_forbidden_victim;
	integrity_before.gc_allocation = a.gc_allocation;
	integrity_before.recycle_hook_calls = recycle_hook_calls;
	integrity_before.recycle_hook_last_segment = recycle_hook_last_segment;
}

static int integrity_unchanged(void)
{
	return !memcmp(integrity_before.maps, maps, sizeof(maps)) &&
	       !memcmp(integrity_before.live, live, sizeof(live)) &&
	       !memcmp(integrity_before.classes, classes, sizeof(classes)) &&
	       !memcmp(integrity_before.roles, roles, sizeof(roles)) &&
	       !memcmp(integrity_before.mapped_pages, mapped_pages,
		       sizeof(mapped_pages)) &&
	       !memcmp(integrity_before.program_counts, program_counts,
		       sizeof(program_counts)) &&
	       !memcmp(integrity_before.gc_live_bytes, gc_live_bytes,
		       sizeof(gc_live_bytes)) &&
	       !memcmp(integrity_before.gc_io_cost, gc_io_cost,
		       sizeof(gc_io_cost)) &&
	       !memcmp(integrity_before.gc_min_live_blocks, gc_min_live_blocks,
		       sizeof(gc_min_live_blocks)) &&
	       !memcmp(integrity_before.first_page, first_page,
		       sizeof(first_page)) &&
	       !memcmp(integrity_before.last_page, last_page,
		       sizeof(last_page)) &&
	       !memcmp(integrity_before.prev_page, prev_page,
		       sizeof(prev_page)) &&
	       !memcmp(integrity_before.next_page, next_page,
		       sizeof(next_page)) &&
	       integrity_before.next_block == a.next_block &&
	       integrity_before.open_segment == a.open_segment &&
	       integrity_before.next_segment_probe == a.next_segment_probe &&
	       integrity_before.recycled_dead_segments ==
		       a.recycled_dead_segments &&
	       integrity_before.gc_destination == a.gc_destination &&
	       integrity_before.gc_forbidden_open == a.gc_forbidden_open &&
	       integrity_before.gc_forbidden_victim == a.gc_forbidden_victim &&
	       integrity_before.gc_allocation == a.gc_allocation &&
	       integrity_before.recycle_hook_calls == recycle_hook_calls &&
	       integrity_before.recycle_hook_last_segment ==
		       recycle_hook_last_segment;
}

static int recycle_hook(void *opaque, swapz_u32 segment)
{
	struct swapz_authority *authority = opaque;
	swapz_u32 block;

	CHECK(authority == &a);
	CHECK(segment < 3);
	for (block = segment * SWAPZ_SEGMENT_BLOCKS;
	     block < (segment + 1U) * SWAPZ_SEGMENT_BLOCKS; ++block)
		CHECK(authority->live_records[block] == 0);
	recycle_hook_calls++;
	recycle_hook_last_segment = segment;
	return recycle_hook_error;
}

static int setup(void)
{
	int rc = swapz_authority_init(
		&a, maps, live, classes, 32, 4U * SWAPZ_SEGMENT_BLOCKS);

	if (rc)
		return rc;
	/*
	 * Geometry admission keeps one foreground COW headroom segment
	 * independently of the two-segment minimum GC reserve. This focused
	 * dead-recycle fixture intentionally needs one ordinary foreground
	 * segment, so conservatively reserve one additional segment only after
	 * validating an admissible four-segment authority.
	 */
	a.reserve_blocks = 3U * SWAPZ_SEGMENT_BLOCKS;
	recycle_hook_calls = 0;
	recycle_hook_last_segment = ~(swapz_u32)0;
	recycle_hook_error = 0;
	a.reuse_dead_segments = 1;
	a.dead_segment_recycle = recycle_hook;
	a.dead_segment_recycle_opaque = &a;
	return rc;
}

static int setup_indexed(swapz_u32 physical_blocks)
{
	swapz_u32 segments = physical_blocks / SWAPZ_SEGMENT_BLOCKS;
	int rc;

	rc = swapz_authority_init(&a, maps, live, classes, 32, physical_blocks);
	if (rc)
		return rc;
	rc = swapz_enable_segment_rotation(&a, roles, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_mapping_counts(&a, mapped_pages, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_program_counts(&a, program_counts, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_gc_accounting(
		&a, gc_live_bytes, gc_io_cost, gc_min_live_blocks, segments);
	if (rc)
		return rc;
	rc = swapz_enable_segment_page_lists(&a, first_page, last_page,
					      prev_page, next_page,
					      segments, 32);
	if (rc)
		return rc;
	recycle_hook_calls = 0;
	recycle_hook_last_segment = ~(swapz_u32)0;
	recycle_hook_error = 0;
	a.reuse_dead_segments = 1;
	a.dead_segment_recycle = recycle_hook;
	a.dead_segment_recycle_opaque = &a;
	return 0;
}

static int write_page(swapz_u32 logical)
{
	struct swapz_tx tx;
	struct swapz_builder builder;
	int rc;

	rc = swapz_stage(&a, &logical, 1, 1, &tx);
	if (rc)
		return rc;
	memset(data, logical + 1, sizeof(data));
	rc = swapz_begin(&builder, bytes, SWAPZ_BLOCK_BYTES, tx.sequence);
	if (!rc)
		rc = swapz_append(&builder, logical, tx.records[0].generation,
				data, sizeof(data));
	if (!rc)
		rc = swapz_seal(&builder);
	if (rc) {
		swapz_abort(&a, &tx);
		return rc;
	}
	return swapz_finish(&a, &tx, bytes, SWAPZ_BLOCK_BYTES, 1, 0);
}

static int test_recycle_wholly_dead_segment(void)
{
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_page(0) == 0);
	CHECK(a.next_block == 256);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(live[255] == 1);
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(live[255] == 0 && !maps[0].valid);
	CHECK(write_page(1) == 0);
	CHECK(a.recycled_dead_segments == 1);
	CHECK(recycle_hook_calls == 1 && recycle_hook_last_segment == 0);
	CHECK(a.next_block == 1 && a.open_segment == 0);
	CHECK(maps[1].start_block == 0 && maps[1].valid);
	CHECK(live[0] == 1 && classes[0] == 1);
	return 0;
}

static int test_recycle_hook_failure_preserves_dead_segment(void)
{
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_page(0) == 0);
	CHECK(swapz_discard_page(&a, 0) == 0);
	recycle_hook_error = -EIO;
	CHECK(write_page(1) == -EIO);
	CHECK(recycle_hook_calls == 1 && recycle_hook_last_segment == 0);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(a.next_block == 256 && a.open_segment == 0);
	CHECK(!maps[0].valid && !maps[1].valid);
	recycle_hook_error = 0;
	CHECK(write_page(1) == 0);
	CHECK(recycle_hook_calls == 2 && a.recycled_dead_segments == 1);
	return 0;
}

static int test_live_segment_is_never_overwritten(void)
{
	int i;

	CHECK(setup() == 0);
	CHECK(write_page(0) == 0); /* pinned live page in physical block 0 */
	for (i = 1; i < 256; ++i)
		CHECK(write_page(1) == 0);
	CHECK(a.next_block == 256);
	CHECK(maps[0].valid && maps[0].start_block == 0);
	CHECK(maps[1].valid && maps[1].start_block == 255);
	CHECK(write_page(2) == -ENOSPC);
	CHECK(a.recycled_dead_segments == 0);
	CHECK(maps[0].start_block == 0 && live[0] == 1);
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(write_page(2) == -ENOSPC); /* still-live page1 */
	CHECK(swapz_discard_page(&a, 1) == 0);
	CHECK(write_page(2) == 0);
	CHECK(a.recycled_dead_segments == 1);
	return 0;
}

static int test_corrupted_liveness_never_reclaims_live_map(void)
{
	int i;

	CHECK(setup() == 0);
	CHECK(write_page(0) == 0);
	for (i = 1; i < 256; ++i)
		CHECK(write_page(1) == 0);
	live[0] = 0; /* corrupt physical liveness count deliberately */
	live[255] = 0;
	CHECK(write_page(2) == -ENOSPC); /* second scan checks maps */
	CHECK(a.recycled_dead_segments == 0 && maps[0].start_block == 0);
	CHECK(maps[1].start_block == 255 && maps[0].valid);
	return 0;
}

static int test_dead_recycle_rejects_stale_gc_score(void)
{
	const swapz_u32 none = ~(swapz_u32)0;
	int i;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	for (i = 0; i < 256; ++i)
		CHECK(write_page(0) == 0);
	CHECK(a.open_segment == 0 && a.next_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(mapped_pages[0] == 0 && first_page[0] == none &&
	      last_page[0] == none);
	CHECK(!gc_live_bytes[0] && !gc_io_cost[0] && !gc_min_live_blocks[0]);

	/*
	 * Force the next allocation to inspect the previously written dead
	 * segment. A stale score contradicts the zero mapping/liveness views and
	 * must fail before the recycle hook or extent-class clearing.
	 */
	a.next_segment_probe = 0;
	gc_io_cost[0] = 1U;
	CHECK(write_page(1) == -EUCLEAN);
	CHECK(recycle_hook_calls == 0 && a.recycled_dead_segments == 0);
	CHECK(a.open_segment == 0 && a.next_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(classes[0] == 1U && !maps[1].valid);

	gc_io_cost[0] = 0U;
	CHECK(write_page(1) == 0);
	CHECK(recycle_hook_calls == 1 && recycle_hook_last_segment == 0U);
	CHECK(a.recycled_dead_segments == 1U);
	CHECK(maps[1].valid && maps[1].start_block == 0U);
	return 0;
}

/*
 * The primary logical map remains authoritative even when every indexed
 * zero/empty sidecar is fault-injected into mutual agreement. These tests
 * deliberately leave valid mapped extents and their class bytes intact.
 */
static void forge_false_empty_indexed_segment(void)
{
	const swapz_u32 none = ~(swapz_u32)0;

	mapped_pages[0] = 0;
	gc_live_bytes[0] = 0;
	gc_io_cost[0] = 0;
	gc_min_live_blocks[0] = 0;
	first_page[0] = none;
	last_page[0] = none;
	prev_page[0] = none;
	next_page[0] = none;
	prev_page[1] = none;
	next_page[1] = none;
	live[0] = 0;
	live[SWAPZ_SEGMENT_BLOCKS - 1U] = 0;
}

static int test_indexed_false_empty_reclaim_preserves_live_extents(void)
{
	swapz_u32 generation, start_block;
	int index;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(write_page(0) == 0);
	for (index = 1; index < (int)SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_page(1) == 0);
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(mapped_pages[0] == 2U && classes[0] == 1U &&
	      classes[SWAPZ_SEGMENT_BLOCKS - 1U] == 1U);
	generation = maps[0].generation;
	start_block = maps[0].start_block;
	forge_false_empty_indexed_segment();
	CHECK(program_counts[0] > 0U);
	/*
	 * The prior fix keyed its full-map proof on extent_classes. Losing those
	 * bytes together with the other zero sidecars must not turn a previously
	 * claimed live segment into a "virgin" overwrite candidate.
	 */
	classes[0] = 0U;
	classes[SWAPZ_SEGMENT_BLOCKS - 1U] = 0U;
	a.next_segment_probe = 0U;
	CHECK(write_page(2) == -EUCLEAN);
	CHECK(!recycle_hook_calls && !a.recycled_dead_segments);
	CHECK(a.open_segment == 0U && a.next_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(maps[0].valid && maps[0].start_block == start_block &&
	      maps[0].generation == generation);
	CHECK(maps[1].valid && maps[1].start_block ==
	      SWAPZ_SEGMENT_BLOCKS - 1U && !maps[2].valid);
	CHECK(!classes[0] && !classes[SWAPZ_SEGMENT_BLOCKS - 1U]);
	return 0;
}

static int test_indexed_false_empty_victim_cannot_exchange_gc_roles(void)
{
	struct swapz_tx tx;
	swapz_u32 extra_page = 3U, destination, next_block;
	swapz_u32 generation, start_block;
	int index;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(write_page(0) == 0);
	for (index = 1; index < (int)SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_page(1) == 0);
	CHECK(write_page(2) == 0);
	CHECK(a.open_segment == 1U);
	CHECK(swapz_gc_begin_rotation(&a, 0U) == 0);
	destination = a.gc_destination;
	CHECK(destination == 2U);
	CHECK(swapz_stage(&a, &extra_page, 1U, 1U, &tx) == 0);
	CHECK(swapz_abort(&a, &tx) == 0);
	next_block = a.next_block;
	generation = maps[0].generation;
	start_block = maps[0].start_block;
	forge_false_empty_indexed_segment();
	CHECK(swapz_gc_commit_rotation(&a, 0U) == -EUCLEAN);
	CHECK(a.gc_allocation && a.gc_forbidden_victim == 0U &&
	      a.gc_destination == destination);
	CHECK(roles[0] == 1U && roles[destination] == 0U);
	CHECK(a.open_segment == destination && a.next_block == next_block);
	CHECK(!recycle_hook_calls && !a.recycled_dead_segments);
	CHECK(maps[0].valid && maps[0].start_block == start_block &&
	      maps[0].generation == generation);
	CHECK(classes[start_block] == 1U && !maps[extra_page].valid);
	return 0;
}


/*
 * Claim history, extent classes, live counts, map counts, reverse links and
 * GC scores can ALL falsely report virgin. They cannot erase the primary
 * map's two live owners or permit a physical reuse/trim side effect.
 */
static int test_forged_virgin_witness_still_requires_full_map_proof(void)
{
	struct swapz_tx tx;
	swapz_u32 logical = 3U;
	int index;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(write_page(0) == 0);
	for (index = 1; index < (int)SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_page(1) == 0);
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS);
	forge_false_empty_indexed_segment();
	classes[0] = 0U;
	classes[SWAPZ_SEGMENT_BLOCKS - 1U] = 0U;
	program_counts[0] = 0U;
	a.next_segment_probe = 0U;
	snapshot_integrity();

	/* stage is before any lower media write: it MUST reject, not reserve. */
	CHECK(swapz_stage(&a, &logical, 1U, 1U, &tx) == -EUCLEAN);
	CHECK(integrity_unchanged());
	CHECK(a.in_flight == 0 && !maps[logical].valid);
	CHECK(a.alloc_probe_full_scans > 0U);
	/* A repeated attempt cannot gradually make a forged claim acceptable. */
	CHECK(swapz_stage(&a, &logical, 1U, 1U, &tx) == -EUCLEAN);
	CHECK(integrity_unchanged());
	return 0;
}

static void forge_segment0_single_mapping_view(swapz_u32 survivor,
					       swapz_u32 stale)
{
	const swapz_u32 none = ~(swapz_u32)0;
	const struct swapz_map *survivor_map = &maps[survivor];
	swapz_u32 stale_start = maps[stale].start_block;

	mapped_pages[0] = 1U;
	first_page[0] = survivor;
	last_page[0] = survivor;
	prev_page[survivor] = none;
	next_page[survivor] = none;
	prev_page[stale] = none;
	next_page[stale] = none;
	live[stale_start] = 0U;
	classes[stale_start] = 0U;
	gc_live_bytes[0] = swapz_gc_live_byte_cost(survivor_map);
	gc_io_cost[0] = swapz_gc_estimated_io_cost(survivor_map);
	gc_min_live_blocks[0] = swapz_gc_min_live_blocks(survivor_map);
}

static int test_false_final_mapping_discard_is_rejected(void)
{
	swapz_u32 generation, survivor_start, stale_start;
	int index;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(write_page(0) == 0);
	for (index = 1; index < (int)SWAPZ_SEGMENT_BLOCKS; ++index)
		CHECK(write_page(1) == 0);
	CHECK(write_page(2) == 0);
	CHECK(a.open_segment == 1U && mapped_pages[0] == 2U);
	generation = maps[0].generation;
	survivor_start = maps[0].start_block;
	stale_start = maps[1].start_block;
	CHECK(survivor_start == 0U &&
	      stale_start == SWAPZ_SEGMENT_BLOCKS - 1U);

	/*
	 * Forge every current-segment sidecar into the state that says page0 is
	 * the final mapping. The stale page1 map remains authoritative. A
	 * successful discard_page() here would make the DM early-TRIM path erase
	 * a still-mapped extent.
	 */
	forge_segment0_single_mapping_view(0U, 1U);
	snapshot_integrity();
	CHECK(swapz_discard_page(&a, 0U) == -EUCLEAN);
	CHECK(integrity_unchanged());
	CHECK(maps[0].valid && maps[0].generation == generation &&
	      maps[0].start_block == survivor_start);
	CHECK(maps[1].valid && maps[1].start_block == stale_start);
	CHECK(mapped_pages[0] == 1U);
	CHECK(live[survivor_start] == 1U && classes[survivor_start] == 1U);
	CHECK(!live[stale_start] && !classes[stale_start]);
	CHECK(first_page[0] == 0U && last_page[0] == 0U);
	return 0;
}

/*
 * An overwrite relocates its old physical mapping, unlike logical DISCARD.
 * When a forged mapped count says the source has one survivor but a second
 * valid map remains, neither RAW nor compressed publication may zero the
 * cached count and authorize the caller's closed-segment early-TRIM.
 */
/*
 * Full-map recovery validation must authenticate surviving maps outside the
 * segment being recycled too. Otherwise a corrupted extent-class or physical
 * liveness sidecar can coexist with an irreversible recycle/role transition,
 * hiding authority corruption until a later read or relocation.
 */
static int test_roll_forward_rejects_unrelated_map_sidecar_corruption(void)
{
	const swapz_u32 logical = 7U;
	int corruption;

	for (corruption = 0; corruption < 2; ++corruption) {
		swapz_u32 start, destination;

		CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
		a.next_segment_probe = 1U;
		CHECK(write_page(logical) == 0);
		start = maps[logical].start_block;
		CHECK(start / SWAPZ_SEGMENT_BLOCKS == 1U);
		CHECK(mapped_pages[0] == 0U && mapped_pages[1] == 1U);

		/* Victim 0 is already dead; reserve 2 becomes the owned destination. */
		CHECK(swapz_gc_begin_rotation(&a, 0U) == 0);
		destination = a.gc_destination;
		CHECK(destination == 2U && a.open_segment == destination);
		/* Model an exhausted destination after uncertain lower writes. */
		a.next_block = (destination + 1U) * SWAPZ_SEGMENT_BLOCKS;
		/* Force the old victim through the physical recycle callback. */
		program_counts[0] = 1U;

		if (corruption == 0)
			classes[start] = 0U;
		else
			live[start] = 0U;
		snapshot_integrity();

		CHECK(swapz_gc_roll_forward_rotation(&a, destination) == -EUCLEAN);
		CHECK(integrity_unchanged());
		CHECK(recycle_hook_calls == 0);
		CHECK(a.gc_allocation && a.gc_forbidden_victim == 0U &&
		      a.gc_destination == destination);
		CHECK(roles[0] == 1U && roles[destination] == 0U);
	}
	return 0;
}

static int test_false_final_mapping_overwrite_is_rejected(void)
{
	struct swapz_builder builder;
	struct swapz_tx tx;
	swapz_u32 logical = 0U;
	int encoding, retry, index, rc;

	for (encoding = 0; encoding < 2; ++encoding) {
		CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
		CHECK(write_page(0) == 0);
		for (index = 1; index < (int)SWAPZ_SEGMENT_BLOCKS; ++index)
			CHECK(write_page(1) == 0);
		CHECK(write_page(2) == 0);
		CHECK(a.open_segment == 1U && mapped_pages[0] == 2U);
		forge_segment0_single_mapping_view(0U, 1U);

		for (retry = 0; retry < 2; ++retry) {
			CHECK(swapz_stage(&a, &logical, 1U, 1U, &tx) == 0);
			if (encoding == 0) {
				memset(bytes, 0x5a, sizeof(bytes));
			} else {
				memset(data, 0x5a, sizeof(data));
				CHECK(swapz_begin(&builder, bytes,
						  SWAPZ_BLOCK_BYTES, tx.sequence) == 0);
				CHECK(swapz_append(&builder, logical,
						   tx.records[0].generation,
						   data, sizeof(data)) == 0);
				CHECK(swapz_seal(&builder) == 0);
			}
			snapshot_integrity();
			if (encoding == 0)
				rc = swapz_finish_raw(&a, &tx, bytes, 1U, 0);
			else
				rc = swapz_finish(&a, &tx, bytes,
						 SWAPZ_BLOCK_BYTES, 1U, 0);
			CHECK(rc == -EUCLEAN);
			CHECK(integrity_unchanged());
			CHECK(!a.in_flight);
			CHECK(maps[0].valid && maps[0].start_block == 0U &&
			      maps[0].generation == 1U);
			CHECK(maps[1].valid &&
			      maps[1].start_block == SWAPZ_SEGMENT_BLOCKS - 1U);
			CHECK(mapped_pages[0] == 1U && !recycle_hook_calls);
		}
	}
	return 0;
}

static int test_two_block_class_respects_segment_edges(void)
{
	swapz_u32 logical = 0;
	struct swapz_tx tx;
	int i;

	CHECK(setup() == 0);
	for (i = 0; i < 254; ++i)
		CHECK(write_page(0) == 0);
	/* current NEXT offset is 254, last valid 2block extent 254-255 */
	CHECK(swapz_stage(&a, &logical, 1, 2, &tx) == 0);
	CHECK(tx.start_block == 254);
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(write_page(0) == -ENOSPC); /* page 0 remains live at 253 */
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(write_page(0) == 0);
	CHECK(maps[0].start_block == 0 && a.recycled_dead_segments == 1);
	return 0;
}

static int test_segment_page_lists_track_authority(void)
{
	const swapz_u32 none = ~(swapz_u32)0;

	CHECK(setup_indexed(4U * SWAPZ_SEGMENT_BLOCKS) == 0);
	CHECK(first_page[0] == none && last_page[0] == none);
	CHECK(write_page(0) == 0);
	CHECK(write_page(1) == 0);
	CHECK(mapped_pages[0] == 2);
	CHECK(first_page[0] == 0 && last_page[0] == 1);
	CHECK(prev_page[0] == none && next_page[0] == 1);
	CHECK(prev_page[1] == 0 && next_page[1] == none);

	/* Same-segment rewrite moves the logical page to the list tail. */
	CHECK(write_page(0) == 0);
	CHECK(mapped_pages[0] == 2);
	CHECK(first_page[0] == 1 && last_page[0] == 0);
	CHECK(prev_page[1] == none && next_page[1] == 0);
	CHECK(prev_page[0] == 1 && next_page[0] == none);

	CHECK(swapz_discard_page(&a, 1) == 0);
	CHECK(mapped_pages[0] == 1);
	CHECK(first_page[0] == 0 && last_page[0] == 0);
	CHECK(prev_page[0] == none && next_page[0] == none);

	/* Corrupt a valid local link: discard must fail before mutation. */
	next_page[0] = 7;
	CHECK(swapz_discard_page(&a, 0) == -EUCLEAN);
	CHECK(maps[0].valid && mapped_pages[0] == 1);
	next_page[0] = none;
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(!maps[0].valid && mapped_pages[0] == 0);
	CHECK(first_page[0] == none && last_page[0] == none);

	/* Invalid maps must also carry no stale membership links. */
	prev_page[0] = 1;
	CHECK(write_page(0) == -EUCLEAN);
	CHECK(!maps[0].valid && mapped_pages[0] == 0);
	return 0;
}

static int test_circular_allocator_fairness_probes_sequentially(void)
{
	struct swapz_tx tx;
	swapz_u32 logical = 0;

	CHECK(setup_indexed(1280) == 0);
	/* 32 logical pages => two reserve segments, three foreground segments. */
	CHECK(roles[0] == 1 && roles[1] == 1 && roles[2] == 1);
	a.next_segment_probe = 0;

	/* Probe 1 claims segment 0 and advances next_segment_probe to 1 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0U);
	CHECK(a.open_segment == 0 && a.next_segment_probe == 1);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 2 claims segment 1 and advances next_segment_probe to 2 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == SWAPZ_SEGMENT_BLOCKS);
	CHECK(a.open_segment == 1 && a.next_segment_probe == 2);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 3 claims segment 2 and sets next_segment_probe to 3 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 2U * SWAPZ_SEGMENT_BLOCKS);
	CHECK(a.open_segment == 2 && a.next_segment_probe == 3);
	CHECK(swapz_abort(&a, &tx) == 0);
	a.open_segment = ~(swapz_u32)0;

	/* Probe 4 skips reserve segments 3 and 4, wrapping back to claim segment 0 */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(tx.start_block == 0U);
	CHECK(a.open_segment == 0 && a.next_segment_probe == 1);
	CHECK(swapz_abort(&a, &tx) == 0);
	return 0;
}

static int test_circular_allocator_fairness_applies_to_gc_destination(void)
{
	CHECK(setup_indexed(1280) == 0);
	a.next_segment_probe = 3;
	CHECK(swapz_gc_begin_rotation(&a, 0) == 0);
	CHECK(a.gc_destination == 3 && a.open_segment == 3);
	CHECK(a.next_segment_probe == 4);
	return 0;
}

/*
 * ID175: an idle-lane submitter may stage inside ->map only when placement
 * provably reuses the open segment. Whenever the read-only proof holds, the
 * real stage path places at the cursor without picking/recycling a segment
 * (whose hook may issue a synchronous DISCARD); every other state refuses.
 */
static int test_open_segment_fit_proves_io_free_placement(void)
{
	struct swapz_authority before;
	swapz_u32 logical = 1, start;
	struct swapz_tx tx;
	int calls;

	CHECK(setup() == 0);
	CHECK(!swapz_open_segment_fits(&a, 1));	/* no open segment yet */
	CHECK(!swapz_open_segment_fits(NULL, 1));
	CHECK(write_page(0) == 0);
	CHECK(a.open_segment == 0 && recycle_hook_calls == 0);
	CHECK(swapz_open_segment_fits(&a, 1));
	CHECK(swapz_open_segment_fits(&a, SWAPZ_MAX_BLOCKS));
	CHECK(!swapz_open_segment_fits(&a, 0));
	CHECK(!swapz_open_segment_fits(&a, 3));	/* not an SWZ class */
	CHECK(!swapz_open_segment_fits(&a, SWAPZ_MAX_BLOCKS + 1U));
	/* A staged transaction owns the cursor: no second owner may plan. */
	CHECK(swapz_stage(&a, &logical, 1, 1, &tx) == 0);
	CHECK(!swapz_open_segment_fits(&a, 1));
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(swapz_open_segment_fits(&a, 1));
	while (a.next_block < SWAPZ_SEGMENT_BLOCKS - 3U)
		CHECK(write_page(0) == 0);
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS - 3U && a.open_segment == 0);
	/* Three blocks remain: classes 1/2 fit, the 4-block class does not. */
	memcpy(&before, &a, sizeof(before));
	CHECK(swapz_open_segment_fits(&a, 1));
	CHECK(swapz_open_segment_fits(&a, 2));
	CHECK(!swapz_open_segment_fits(&a, SWAPZ_MAX_BLOCKS));
	CHECK(!memcmp(&before, &a, sizeof(before)));	/* read-only proof */
	calls = recycle_hook_calls;
	start = a.next_block;
	CHECK(swapz_stage(&a, &logical, 1, 2, &tx) == 0);
	CHECK(tx.start_block == start && recycle_hook_calls == calls);
	CHECK(a.open_segment == 0);
	CHECK(swapz_abort(&a, &tx) == 0);
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS - 1U);
	CHECK(swapz_open_segment_fits(&a, 1) && !swapz_open_segment_fits(&a, 2));
	CHECK(write_page(0) == 0);
	CHECK(a.next_block == SWAPZ_SEGMENT_BLOCKS);
	/* The open segment is exhausted: the next stage must pick a segment. */
	CHECK(!swapz_open_segment_fits(&a, 1));
	CHECK(swapz_discard_page(&a, 0) == 0);
	CHECK(!swapz_open_segment_fits(&a, 1));
	CHECK(write_page(1) == 0);
	CHECK(recycle_hook_calls == calls + 1);	/* the refused case recycled */
	CHECK(swapz_open_segment_fits(&a, 1));
	/* GC allocation and a pending lower-write group are never I/O-free. */
	a.gc_allocation = 1;
	CHECK(!swapz_open_segment_fits(&a, 1));
	a.gc_allocation = 0;
	a.batch_pending = 1;
	CHECK(!swapz_open_segment_fits(&a, 1));
	a.batch_pending = 0;
	CHECK(swapz_open_segment_fits(&a, 1));
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_recycle_wholly_dead_segment() == 0); passed++;
	CHECK(test_recycle_hook_failure_preserves_dead_segment() == 0); passed++;
	CHECK(test_live_segment_is_never_overwritten() == 0); passed++;
	CHECK(test_corrupted_liveness_never_reclaims_live_map() == 0); passed++;
	CHECK(test_dead_recycle_rejects_stale_gc_score() == 0); passed++;
	CHECK(test_indexed_false_empty_reclaim_preserves_live_extents() == 0); passed++;
	CHECK(test_indexed_false_empty_victim_cannot_exchange_gc_roles() == 0); passed++;
	CHECK(test_forged_virgin_witness_still_requires_full_map_proof() == 0); passed++;
	CHECK(test_false_final_mapping_discard_is_rejected() == 0); passed++;
	CHECK(test_roll_forward_rejects_unrelated_map_sidecar_corruption() == 0); passed++;
	CHECK(test_false_final_mapping_overwrite_is_rejected() == 0); passed++;
	CHECK(test_two_block_class_respects_segment_edges() == 0); passed++;
	CHECK(test_segment_page_lists_track_authority() == 0); passed++;
	CHECK(test_circular_allocator_fairness_probes_sequentially() == 0); passed++;
	CHECK(test_circular_allocator_fairness_applies_to_gc_destination() == 0); passed++;
	CHECK(test_open_segment_fit_proves_io_free_placement() == 0); passed++;
	printf("SWAPZ_DEAD_SEGMENT_REUSE_TESTS_PASS=%d\n", passed);
	return 0;
}
