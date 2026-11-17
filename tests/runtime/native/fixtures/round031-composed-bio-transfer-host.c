/* SPDX-License-Identifier: GPL-2.0-only */
/* Emitted REAL mm/page_io.c 4096 BIO transfer and real block/bio.c detach,
 * source-extracted from the single composed pinned source.
 * This is an untrusted HOST lower-BIO boundary, NOT a loaded Linux swap.
 */
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct swapz_ci_owned_payload {
	unsigned int references;
	uint8_t data[256];
};
struct bio {
	struct { size_t bi_size; } bi_iter;
	struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
};
struct swap_iocb { unsigned int nr_bvecs; };
struct swap_io_ctx {
	struct swapz_ci_owned_payload *swapz_round031_owned;
};
static unsigned int released, releases, acquisitions;
static struct swapz_ci_owned_payload *swapz_ci_owned_get(
	struct swapz_ci_owned_payload *owner)
{
	if (!owner || owner->references == 0U)
		return NULL;
	++owner->references;
	++acquisitions;
	return owner;
}
static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
	if (owner) {
		assert(owner->references > 0U);
		++releases;
		if (--owner->references == 0U) {
			++released;
			free(owner);
		}
	}
}
/* ROUND031_EXACT_REAL_BIO_DETACH_C */

static struct swapz_ci_owned_payload *new_owner(void)
{
	struct swapz_ci_owned_payload *owner = calloc(1U, sizeof(*owner));
	assert(owner);
	owner->references = 1U;
	memset(owner->data, 0x5a, sizeof(owner->data));
	return owner;
}
static void move_original_owner_into_block_bio(
	struct swap_io_ctx *ctx, struct swap_iocb *sio, struct bio *bio)
{
/* ROUND031_EXACT_REAL_BIO_MOVE_C */
}
int main(void)
{
	struct swap_io_ctx ctx = { 0 };
	struct swap_iocb write = { .nr_bvecs = 1U };
	struct bio parent = { .bi_iter.bi_size = 4096U };
	struct bio clone = { .bi_iter.bi_size = 4096U };
	struct swapz_ci_owned_payload *before;
	const unsigned int initial_releases = released;

	/* Owned source transfers once to 4096 original data BIO. */
	ctx.swapz_round031_owned = new_owner();
	before = ctx.swapz_round031_owned;
	move_original_owner_into_block_bio(&ctx, &write, &parent);
	assert(!ctx.swapz_round031_owned);
	assert(parent.bi_swapz_ci_sideband == before);
	assert(parent.bi_iter.bi_size == 4096U);
	/* Real same-owner clone requires separate ref and both final puts. */
	clone.bi_swapz_ci_sideband =
		swapz_ci_owned_get(parent.bi_swapz_ci_sideband);
	assert(clone.bi_swapz_ci_sideband == before);
	assert(before->references == 2U);
	swapz_ci_bio_detach(&clone);
	assert(clone.bi_swapz_ci_sideband == NULL);
	assert(before->references == 1U);
	swapz_ci_bio_detach(&clone);
	assert(before->references == 1U);
	swapz_ci_bio_detach(&parent);
	assert(parent.bi_swapz_ci_sideband == NULL);
	assert(released == 1U && released == initial_releases + 1U);
	swapz_ci_bio_detach(&parent);

	/* 8192, 2048, and multi-folio cannot silently become one 4096.
	 * Original MM fallback must release the still owned ctx ref.
	 */
	for (size_t index = 0; index < 3U; ++index) {
		const size_t sizes[3] = { 8192U, 2048U, 4096U };
		struct swap_iocb candidate = {
			.nr_bvecs = index == 2U ? 2U : 1U,
		};
		struct bio non_single = { .bi_iter.bi_size = sizes[index] };
		ctx.swapz_round031_owned = new_owner();
		before = ctx.swapz_round031_owned;
		move_original_owner_into_block_bio(&ctx, &candidate, &non_single);
		assert(ctx.swapz_round031_owned == before);
		assert(!non_single.bi_swapz_ci_sideband);
		swapz_ci_owned_put(ctx.swapz_round031_owned);
		ctx.swapz_round031_owned = NULL;
		assert(released == index + 2U);
	}

	/* Abort and no BIO must always put and must never publish owner. */
	ctx.swapz_round031_owned = new_owner();
	swapz_ci_owned_put(ctx.swapz_round031_owned);
	ctx.swapz_round031_owned = NULL;
	assert(released == 5U && acquisitions == 1U);
	assert(releases == 6U);
	puts("ROUND031_REAL_MM_PAGEIO_BIO_TRANSFER_AND_RELEASE_PASS");
	return 0;
}
