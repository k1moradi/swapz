/*
 * Round053 host compiles source-extracted, default-undefined production DM C.
 * Scalar stand-ins CANNOT retain a real DM table, GC target, original Linux
 * counted slot, lower device, completion callback, or actual upper bio_endio.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint64_t sector_t;
typedef uint32_t swapz_u32;
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define READ_ONCE(value) (value)
#define smp_load_acquire(pointer) (*(pointer))
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_SECTORS 8U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 16U
struct dm_target {
	void *private;
	sector_t begin;
	sector_t len;
};
struct swapz_dm {
	struct dm_target *target;
	bool accepting;
	bool failed;
	swapz_u32 logical_pages;
	swapz_u32 physical_blocks;
	swapz_u32 *maps;
	struct {
		swapz_u32 *maps;
	} authority;
};
struct bio {
	unsigned int bi_opf;
	struct {
		sector_t bi_sector;
		unsigned int bi_size;
	} bi_iter;
};
static unsigned int bio_op(const struct bio *upper_bio)
{
	return upper_bio->bi_opf & 7U;
}
static sector_t bio_sectors(const struct bio *upper_bio)
{
	return (sector_t)upper_bio->bi_iter.bi_size / 512U;
}

/* ROUND053_INJECT_REAL_PRODUCT_RECEIPT_DECL */
/* ROUND053_INJECT_REAL_PRODUCT_RECEIPT_HELPER */

struct host {
	struct dm_target target;
	struct dm_target alien_target;
	struct swapz_dm context;
	struct bio upper_bio;
	struct bio alien_bio;
	struct swapz_round053_internal_observation observation;
	struct swapz_round053_internal_receipt receipt;
	swapz_u32 maps[32];
};

static void check(const struct host *state, int actual, int expected,
		unsigned int extent_blocks, unsigned int fault, const char *stage)
{
	if (actual != expected) {
		fprintf(stderr, "FIRST Round053 real DM lifecycle C failure: "
			"blocks=%u fault=%u stage=%s actual=%d expected=%d "
			"phase=%u lower=%u maps=%u ack=%u releases=%u\n",
			extent_blocks, fault, stage, actual, expected,
			(unsigned int)state->receipt.phase,
			state->receipt.lower_callbacks,
			state->receipt.map_publications,
			state->receipt.upper_ack_attempts,
			state->receipt.terminal_releases);
		abort();
	}
}

static void invariant(const struct host *state, bool condition,
		unsigned int extent_blocks, unsigned int fault, const char *stage)
{
	if (!condition) {
		fprintf(stderr, "FIRST Round053 real DM lifecycle C failure: "
			"blocks=%u fault=%u stage=%s invariant "
			"phase=%u lower=%u maps=%u ack=%u releases=%u\n",
			extent_blocks, fault, stage,
			(unsigned int)state->receipt.phase,
			state->receipt.lower_callbacks,
			state->receipt.map_publications,
			state->receipt.upper_ack_attempts,
			state->receipt.terminal_releases);
		abort();
	}
}

static int step(struct host *state, enum swapz_round053_internal_event event,
		bool durable, int error)
{
	return swapz_round053_internal_receipt_step(&state->receipt,
		&state->observation, event, durable, error);
}

static void complete(struct host *state, unsigned int blocks, unsigned int fault)
{
	if (state->receipt.phase == SWAPZ_ROUND053_LOWER_PENDING)
		check(state, step(state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			0, blocks, fault, "durable-completion");
	if (state->receipt.phase == SWAPZ_ROUND053_DURABLE)
		check(state, step(state, SWAPZ_ROUND053_PUBLISH, true, 0),
			0, blocks, fault, "single-publication");
	if (state->receipt.phase == SWAPZ_ROUND053_MAPPED)
		check(state, step(state, SWAPZ_ROUND053_ACK, true, 0),
			0, blocks, fault, "single-synthetic-ack");
}

static void run_case(unsigned int blocks, unsigned int fault)
{
	struct host state = {
		.context = {.accepting = true, .logical_pages = 32U,
			.physical_blocks = 512U},
		.upper_bio = {.bi_opf = REQ_OP_WRITE | REQ_SWAP,
			.bi_iter = {.bi_sector = SWAPZ_SECTORS,
				.bi_size = SWAPZ_BLOCK_BYTES}},
	};
	struct swapz_round053_internal_observation *view = &state.observation;
	int expected = 0;
	int actual;

	state.target.begin = 4096U; /* Nonlinear/absolute lower sector NOT BIO sector. */
	state.target.len = 32U * SWAPZ_SECTORS;
	state.target.private = &state.context;
	state.context.target = &state.target;
	state.context.maps = state.maps;
	state.context.authority.maps = state.maps;
	*view = (struct swapz_round053_internal_observation) {
		.target = &state.target, .context = &state.context,
		.upper_bio = &state.upper_bio,
		.target_relative_sector = SWAPZ_SECTORS,
		.map_generation = 7U, .gc_epoch = 9U,
		.extent_start_block = 16U, .extent_blocks = blocks,
		.synthetic_lease_token = 19U,
		.original_uncompressed_bytes = SWAPZ_BLOCK_BYTES,
		.synthetic_live_lease = true, .worker_owns_bio = true,
	};
	if (fault >= 1U && fault <= 22U) {
		switch (fault) {
		case 1U: state.context.accepting = false; expected = -ESHUTDOWN; break;
		case 2U: state.context.failed = true; expected = -ESHUTDOWN; break;
		case 3U: state.target.private = NULL; expected = -ESTALE; break;
		case 4U: state.context.target = NULL; expected = -ESTALE; break;
		case 5U: state.context.maps = NULL; expected = -ESTALE; break;
		case 6U: state.context.authority.maps = NULL; expected = -ESTALE; break;
		case 7U: state.upper_bio.bi_opf = REQ_OP_WRITE; expected = -ERANGE; break;
		case 8U: state.upper_bio.bi_opf = REQ_OP_READ | REQ_SWAP; expected = -ERANGE; break;
		case 9U: state.upper_bio.bi_iter.bi_size = 4100U; expected = -ERANGE; break;
		case 10U: state.upper_bio.bi_iter.bi_sector = 1U; expected = -ERANGE; break;
		case 11U: state.upper_bio.bi_iter.bi_sector = state.target.len; expected = -ERANGE; break;
		case 12U: view->original_uncompressed_bytes = 3568U; expected = -EOPNOTSUPP; break;
		case 13U: view->external_stored = true; expected = -EOPNOTSUPP; break;
		case 14U: view->synthetic_live_lease = false; expected = -ESTALE; break;
		case 15U: view->target_relative_sector = state.target.begin + SWAPZ_SECTORS; expected = -ERANGE; break;
		case 16U: view->map_generation = 0U; expected = -ERANGE; break;
		case 17U: view->gc_epoch = 0U; expected = -ERANGE; break;
		case 18U: view->extent_start_block = state.context.physical_blocks; expected = -ERANGE; break;
		case 19U: view->extent_blocks = 3U; expected = -ERANGE; break;
		case 20U: view->worker_owns_bio = false; expected = -ESTALE; break;
		case 21U: state.target.len--; expected = -ESTALE; break;
		case 22U: view->synthetic_lease_token = 0U; expected = -ESTALE; break;
		default: abort();
		}
		check(&state, step(&state, SWAPZ_ROUND053_ACCEPT, false, 0),
			expected, blocks, fault, "refuse-unaccepted");
		invariant(&state, state.receipt.phase == SWAPZ_ROUND053_NOT_ACCEPTED &&
			state.receipt.lower_callbacks == 0U &&
			state.receipt.map_publications == 0U &&
			state.receipt.upper_ack_attempts == 0U &&
			state.receipt.terminal_releases == 0U,
			blocks, fault, "zero-unaccepted-effects");
		return;
	}
	check(&state, step(&state, SWAPZ_ROUND053_ACCEPT, false, 0),
		0, blocks, fault, "real-source-accept");
	switch (fault) {
	case 23U:
		check(&state, step(&state, SWAPZ_ROUND053_ACCEPT, false, 0),
			-EALREADY, blocks, fault, "double-accept");
		break;
	case 24U:
		check(&state, step(&state, SWAPZ_ROUND053_PUBLISH, true, 0),
			-EAGAIN, blocks, fault, "map-before-durable");
		break;
	case 25U:
		check(&state, step(&state, SWAPZ_ROUND053_ACK, true, 0),
			-EAGAIN, blocks, fault, "ack-before-durable");
		break;
	case 26U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, false, 0),
			-EAGAIN, blocks, fault, "non-durable-lower");
		break;
	case 27U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, -EIO),
			-EIO, blocks, fault, "lower-eio-abort");
		break;
	case 28U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, -ENOSPC),
			-ENOSPC, blocks, fault, "lower-enospc-abort");
		break;
	case 29U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 1),
			-EAGAIN, blocks, fault, "positive-lower-error-refused");
		break;
	case 30U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			0, blocks, fault, "first-durable");
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			-EALREADY, blocks, fault, "duplicate-lower-callback");
		break;
	case 31U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			0, blocks, fault, "durable-for-double-map");
		check(&state, step(&state, SWAPZ_ROUND053_PUBLISH, true, 0),
			0, blocks, fault, "first-map");
		check(&state, step(&state, SWAPZ_ROUND053_PUBLISH, true, 0),
			-EAGAIN, blocks, fault, "duplicate-map");
		break;
	case 32U:
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			0, blocks, fault, "durable-before-ack");
		check(&state, step(&state, SWAPZ_ROUND053_ACK, true, 0),
			-EAGAIN, blocks, fault, "ack-before-map");
		break;
	case 33U:
		complete(&state, blocks, fault);
		check(&state, step(&state, SWAPZ_ROUND053_ACK, true, 0),
			-EALREADY, blocks, fault, "duplicate-upper-ack");
		break;
	case 34U: case 35U:
		check(&state, step(&state, SWAPZ_ROUND053_ABORT, false, -ECANCELED),
			-ECANCELED, blocks, fault, "abort-before-callback");
		check(&state, step(&state,
			fault == 34U ? SWAPZ_ROUND053_LOWER_COMPLETE : SWAPZ_ROUND053_ACK,
			true, 0), -EALREADY, blocks, fault, "late-after-abort");
		break;
	case 36U:
		complete(&state, blocks, fault);
		check(&state, step(&state, SWAPZ_ROUND053_ABORT, false, -EIO),
			-EALREADY, blocks, fault, "abort-after-success");
		break;
	case 37U: case 38U: case 39U:
		state.context.accepting = false;
		if (fault == 38U) {
			check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
				0, blocks, fault, "accepted-worker-after-close");
		}
		if (fault == 39U) {
			struct swapz_round053_internal_receipt later = {0};
			check(&state, swapz_round053_internal_receipt_step(&later,
				view, SWAPZ_ROUND053_ACCEPT, false, 0),
				-ESHUTDOWN, blocks, fault, "new-admission-after-close");
		}
		break;
	case 40U:
		state.context.accepting = false;
		state.context.failed = true;
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			-ESHUTDOWN, blocks, fault, "failed-target-refuse");
		break;
	case 41U:
		view->dtr_started = true;
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			-ESHUTDOWN, blocks, fault, "dtr-callback-refuse");
		break;
	case 42U:
		view->synthetic_live_lease = false;
		check(&state, step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			-ESHUTDOWN, blocks, fault, "lease-dropped-callback-refuse");
		break;
	case 43U:
		view->worker_owns_bio = false; expected = -ESTALE; break;
	case 44U:
		view->gc_epoch++; expected = -ESTALE; break;
	case 45U:
		view->map_generation++; expected = -ESTALE; break;
	case 46U:
		view->target_relative_sector = state.target.begin + SWAPZ_SECTORS;
		expected = -ESTALE; break;
	case 47U:
		view->upper_bio = &state.alien_bio; expected = -ESTALE; break;
	case 48U:
		view->target = &state.alien_target; expected = -ESTALE; break;
	case 49U:
		state.context.authority.maps = NULL; expected = -ESTALE; break;
	case 50U:
		view->extent_start_block++; expected = -ESTALE; break;
	case 51U:
		view->synthetic_lease_token++; expected = -ESTALE; break;
	case 52U:
		view->extent_blocks = blocks == 1U ? 2U : 1U;
		expected = -ESTALE; break;
	case 53U:
		check(&state, swapz_round053_internal_receipt_step(NULL, view,
			SWAPZ_ROUND053_LOWER_COMPLETE, true, 0),
			-EINVAL, blocks, fault, "missing-receipt");
		break;
	default: break;
	}
	if (fault >= 43U && fault <= 52U) {
		actual = step(&state, SWAPZ_ROUND053_LOWER_COMPLETE, true, 0);
		check(&state, actual, expected, blocks, fault, "stale-callback");
	}
	if (fault >= 40U && fault <= 52U) {
		/* Abort checks ticket only: never dereference freed ctx/bio. */
		check(&state, swapz_round053_internal_receipt_step(
			&state.receipt, NULL, SWAPZ_ROUND053_ABORT, false,
			-ECANCELED), -ECANCELED, blocks, fault, "safe-abort");
	}
	if (state.receipt.phase != SWAPZ_ROUND053_COMPLETED &&
	    state.receipt.phase != SWAPZ_ROUND053_ABORTED)
		complete(&state, blocks, fault);
	if (state.receipt.phase == SWAPZ_ROUND053_COMPLETED)
		invariant(&state, state.receipt.lower_callbacks == 1U &&
			state.receipt.map_publications == 1U &&
			state.receipt.upper_ack_attempts == 1U &&
			state.receipt.terminal_releases == 1U,
			blocks, fault, "one-terminal-upper-success");
	else
		invariant(&state, state.receipt.upper_ack_attempts == 0U &&
			state.receipt.map_publications == 0U &&
			state.receipt.terminal_releases == 1U,
			blocks, fault, "single-terminal-abort-no-map");
}

int main(void)
{
	unsigned int cases = 0U;

	for (unsigned int extent_blocks = 1U; extent_blocks <= 4U;
	     extent_blocks *= 2U) {
		for (unsigned int fault = 0U; fault < 54U; ++fault) {
			run_case(extent_blocks, fault);
			++cases;
		}
	}
	if (cases != 162U) {
		fputs("FIRST Round053 real DM lifecycle C failure: missing case\n", stderr);
		return 1;
	}
	puts("ROUND053_REAL_PRODUCT_DM_162_LIFECYCLE_C_CASES_PASS");
	puts("SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED");
	return 0;
}
