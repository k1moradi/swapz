// SPDX-License-Identifier: GPL-2.0-only
/*
 * Direct actual-C zero page predicate and authoritative zero overwrite.
 * No Python simulator, module loading, physical device or system swap.
 */
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "engine.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)
#define PHYSICAL 1024U

static struct swapz_authority authority;
static struct swapz_map mapping[32];
static swapz_u16 live[PHYSICAL];
static swapz_u8 classes[PHYSICAL];
static swapz_u8 bytes[SWAPZ_BLOCK_BYTES];
static swapz_u8 unaligned_bytes[SWAPZ_BLOCK_BYTES + 1U];

static int test_byte_exact_zero_detection(void)
{
	static const swapz_u32 positions[] = { 0, 1, 31, 2048, 4095 };
	swapz_u32 i;

	memset(bytes, 0, sizeof(bytes));
	CHECK(!swapz_page_is_zero(NULL));
	CHECK(swapz_page_is_zero(bytes));
	for (i = 0; i < sizeof(positions) / sizeof(positions[0]); ++i) {
		bytes[positions[i]] = 1;
		CHECK(!swapz_page_is_zero(bytes));
		bytes[positions[i]] = 0;
		CHECK(swapz_page_is_zero(bytes));
	}
	memset(bytes, 0x7f, sizeof(bytes));
	CHECK(!swapz_page_is_zero(bytes));

	/* The production predicate is also used by portable native tests and
	 * must not assume naturally aligned input or read outside one page. */
	memset(unaligned_bytes, 0, sizeof(unaligned_bytes));
	unaligned_bytes[0] = 0x5a;
	CHECK(swapz_page_is_zero(unaligned_bytes + 1));
	unaligned_bytes[1 + 4095] = 1;
	CHECK(!swapz_page_is_zero(unaligned_bytes + 1));
	unaligned_bytes[1 + 4095] = 0;
	CHECK(swapz_page_is_zero(unaligned_bytes + 1));
	return 0;
}

static int test_zero_replaces_committed_raw_mapping(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 3;
	swapz_u32 first_block;

	CHECK(swapz_authority_init(&authority, mapping, live, classes,
				32, PHYSICAL) == 0);
	memset(bytes, 0x9e, sizeof(bytes));
	CHECK(swapz_stage(&authority, &page, 1, 1, &tx) == 0);
	first_block = tx.start_block;
	CHECK(swapz_finish_raw(&authority, &tx, bytes, 1, 0) == 0);
	CHECK(mapping[page].valid && mapping[page].generation == 1);
	CHECK(live[first_block] == 1);
	/* This is the same logical transition used by the kernel zero path:
	 * first check every byte, then atomically invalidate the mapping. */
	memset(bytes, 0, sizeof(bytes));
	CHECK(swapz_page_is_zero(bytes));
	CHECK(swapz_discard_page(&authority, page) == 0);
	CHECK(!mapping[page].valid && mapping[page].generation == 2);
	CHECK(!live[first_block]);
	CHECK(swapz_discard_page(&authority, page) == 0);
	CHECK(!mapping[page].valid && mapping[page].generation == 3);
	/* The next nonzero write must derive authority from generation 3. */
	memset(bytes, 0x52, sizeof(bytes));
	CHECK(!swapz_page_is_zero(bytes));
	CHECK(swapz_stage(&authority, &page, 1, 1, &tx) == 0);
	CHECK(tx.records[0].generation == 4);
	CHECK(swapz_finish_raw(&authority, &tx, bytes, 1, 0) == 0);
	CHECK(mapping[page].valid && mapping[page].generation == 4);
	return 0;
}

static int test_zero_overwrite_refuses_inflight_or_wrap(void)
{
	struct swapz_tx tx;
	swapz_u32 page = 4;

	CHECK(swapz_authority_init(&authority, mapping, live, classes,
				32, PHYSICAL) == 0);
	CHECK(swapz_stage(&authority, &page, 1, 1, &tx) == 0);
	CHECK(swapz_discard_page(&authority, page) == -EBUSY);
	CHECK(!mapping[page].valid && mapping[page].generation == 0);
	CHECK(swapz_abort(&authority, &tx) == 0);
	mapping[page].generation = UINT32_MAX;
	CHECK(swapz_discard_page(&authority, page) == -EOVERFLOW);
	CHECK(!mapping[page].valid && mapping[page].generation == UINT32_MAX);
	return 0;
}

int main(void)
{
	CHECK(test_byte_exact_zero_detection() == 0);
	CHECK(test_zero_replaces_committed_raw_mapping() == 0);
	CHECK(test_zero_overwrite_refuses_inflight_or_wrap() == 0);
	puts("SWAPZ_ZERO_PAGE_ELISION_TESTS_PASS=3");
	return 0;
}
