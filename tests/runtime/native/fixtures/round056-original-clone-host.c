/*
 * Rootless C negatives of the exact staged original block/bio.c ticket helper.
 * This stand-in is NOT the original block allocator/DM map, a physical device,
 * native swap_slot ownership, or real clone bio_endio. Genuine in-kernel C
 * clone calls are a separate CI gate, never inferred from this executable.
 */
#include <errno.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST 1
#define REQ_OP_WRITE 1U
#define REQ_OP_READ 0U
#define REQ_SWAP 16U
#define BIO_CLONED 1U
#define GFP_KERNEL 0

typedef uint64_t sector_t;
typedef atomic_int atomic_t;
typedef struct { atomic_uint value; } refcount_t;
#define ATOMIC_INIT(number) ATOMIC_VAR_INIT(number)
static void atomic_set(atomic_t *value, int count)
{
	atomic_store(value, count);
}
static int atomic_read(const atomic_t *value)
{
	return atomic_load(value);
}
static void atomic_inc(atomic_t *value)
{
	(void)atomic_fetch_add_explicit(value, 1, memory_order_relaxed);
}
static void refcount_set(refcount_t *reference, unsigned int value)
{
	atomic_store(&reference->value, value);
}
static bool refcount_inc_not_zero(refcount_t *reference)
{
	unsigned int current = atomic_load(&reference->value);
	while (current && current < UINT32_MAX) {
		if (atomic_compare_exchange_weak(&reference->value, &current, current + 1U))
			return true;
	}
	return false;
}
static bool refcount_dec_and_test(refcount_t *reference)
{
	return atomic_fetch_sub(&reference->value, 1U) == 1U;
}
static unsigned int refcount_read(const refcount_t *reference)
{
	return atomic_load(&reference->value);
}
static void *kzalloc(size_t length, int flags)
{
	(void)flags;
	return calloc(1U, length);
}
static void kfree(void *pointer)
{
	free(pointer);
}
struct block_device { unsigned int identity; };
struct bio_vec {
	void *bv_page;
	unsigned int bv_offset;
	unsigned int bv_len;
};
struct swapz_round056_clone_ticket;
struct bio {
	struct block_device *bi_bdev;
	unsigned int bi_opf;
	unsigned int bi_flags;
	struct bio_vec *bi_io_vec;
	struct {
		sector_t bi_sector;
		unsigned int bi_size;
		unsigned int bi_idx;
		unsigned int bi_offset;
	} bi_iter;
	unsigned short bi_vcnt;
	struct swapz_round056_clone_ticket *bi_round056_ticket;
	struct block_device *bi_round056_clone_device;
	bool bi_round056_candidate;
};
static unsigned int bio_op(const struct bio *bio)
{
	return bio->bi_opf & 7U;
}
static bool bio_flagged(const struct bio *bio, unsigned int flag)
{
	return (bio->bi_flags & (1U << flag)) != 0U;
}

/* ROUND056_INJECT_GUARDED_C */

struct fixture {
	struct bio source;
	struct bio clone;
	struct bio sibling;
	struct block_device source_device;
	struct block_device mapped_device;
	struct block_device alternate_device;
	struct bio_vec vector;
	struct bio_vec alien_vector;
	unsigned char original_page[SWAPZ_ROUND056_PAGE_BYTES];
};

static int fail(unsigned int case_number, unsigned int scenario, const char *stage)
{
	fprintf(stderr, "ROUND056_CLONE_FIRST_ERROR case=%u scenario=%u stage=%s\n",
		case_number, scenario, stage);
	fflush(stderr);
	_Exit(1);
}

static void set_up(struct fixture *state, unsigned int first_sector)
{
	memset(state, 0, sizeof(*state));
	state->vector = (struct bio_vec) {
		.bv_page = state->original_page, .bv_len = SWAPZ_ROUND056_PAGE_BYTES,
	};
	state->source_device.identity = 11U;
	state->mapped_device.identity = 13U;
	state->alternate_device.identity = 17U;
	state->source = (struct bio) {
		.bi_bdev = &state->source_device,
		.bi_opf = REQ_OP_WRITE | REQ_SWAP,
		.bi_io_vec = &state->vector,
		.bi_iter = {.bi_sector = first_sector,
			.bi_size = SWAPZ_ROUND056_PAGE_BYTES},
		.bi_vcnt = 1U,
	};
}

static void clone_initial(struct fixture *state, struct bio *clone)
{
	*clone = (struct bio) {
		.bi_bdev = &state->mapped_device,
		.bi_opf = state->source.bi_opf,
		.bi_flags = 1U << BIO_CLONED,
		.bi_io_vec = state->source.bi_io_vec,
		.bi_iter = state->source.bi_iter,
	};
	swapz_round056_propagate_full_clone(clone, &state->source);
}

static int run_one(unsigned int case_number, unsigned int scenario)
{
	struct fixture state;
	struct swapz_round056_clone_ticket *ticket;
	const int freed_before = atomic_load(&swapz_round056_ticket_frees);
	bool should_admit = true;

	set_up(&state, 8U * (case_number + 1U));
	if (scenario == 12U)
		state.source.bi_iter.bi_size = 4100U;
	if (scenario == 13U)
		state.vector.bv_len = SWAPZ_ROUND056_PAGE_BYTES - 1U;
	if (scenario == 14U)
		state.source.bi_flags |= 1U << BIO_CLONED;
	if (scenario == 15U)
		state.source.bi_opf &= ~REQ_SWAP;
	if (scenario == 16U)
		state.source.bi_iter.bi_sector++;
	if (scenario == 17U)
		state.source.bi_iter.bi_idx++;
	if (scenario == 18U)
		state.source.bi_iter.bi_offset++;
	if (scenario == 19U)
		state.source.bi_vcnt = 0U;
	if (scenario == 20U)
		state.vector.bv_page = NULL;
	if (scenario >= 12U && scenario <= 20U)
		should_admit = false;
	ticket = swapz_round056_attach_original(&state.source);
	if (!should_admit) {
		if (ticket || state.source.bi_round056_ticket)
			return fail(case_number, scenario, "invalid-source-admitted");
		if (atomic_load(&swapz_round056_ticket_frees) != freed_before)
			return fail(case_number, scenario, "invalid-source-freed");
		return 0;
	}
	if (!ticket || refcount_read(&ticket->references) != 1U)
		return fail(case_number, scenario, "initial-source-owner");
	if (scenario == 21U)
		swapz_round056_invalidate_clone(&state.source);
	clone_initial(&state, &state.clone);
	if (scenario == 21U) {
		if (state.clone.bi_round056_ticket)
			return fail(case_number, scenario, "invalid-source-propagated");
		swapz_round056_drop_clone_ticket(&state.source);
		return atomic_load(&swapz_round056_ticket_frees) == freed_before + 1 ?
			0 : fail(case_number, scenario, "failed-source-release");
	}
	if (!state.clone.bi_round056_ticket ||
	    refcount_read(&ticket->references) != 2U ||
	    !swapz_round056_complete_clone_view(&state.clone))
		return fail(case_number, scenario, "initial-full-clone");
	if (scenario == 1U)
		state.clone.bi_iter.bi_sector++;
	if (scenario == 2U)
		state.clone.bi_iter.bi_size = 4100U;
	if (scenario == 3U)
		state.clone.bi_io_vec = &state.alien_vector;
	if (scenario == 4U)
		state.clone.bi_bdev = &state.alternate_device;
	if (scenario == 5U)
		state.clone.bi_flags &= ~(1U << BIO_CLONED);
	if (scenario == 6U)
		swapz_round056_invalidate_clone(&state.clone);
	if (scenario == 7U)
		state.clone.bi_opf = REQ_OP_READ | REQ_SWAP;
	if (scenario == 8U)
		state.clone.bi_opf = REQ_OP_WRITE;
	if (scenario == 9U)
		state.clone.bi_iter.bi_idx++;
	if (scenario == 10U)
		state.clone.bi_iter.bi_offset++;
	if (scenario == 11U)
		ticket->sector++;
	if (scenario >= 1U && scenario <= 11U &&
	    swapz_round056_complete_clone_view(&state.clone))
		return fail(case_number, scenario, "changed-clone-still-eligible");
	if (scenario == 22U) {
		state.clone.bi_iter.bi_size = 2048U;
		swapz_round056_invalidate_clone(&state.clone);
		state.source.bi_iter.bi_sector += 4U;
		state.source.bi_iter.bi_size = 2048U;
		swapz_round056_invalidate_clone(&state.source);
		if (swapz_round056_complete_clone_view(&state.clone))
			return fail(case_number, scenario, "split-clone-eligible");
	}
	if (scenario == 23U) {
		clone_initial(&state, &state.sibling);
		if (!state.sibling.bi_round056_ticket ||
		    refcount_read(&ticket->references) != 3U)
			return fail(case_number, scenario, "sibling-ref-transfer");
		swapz_round056_drop_clone_ticket(&state.sibling);
	}
	if (scenario == 24U) {
		state.clone.bi_iter.bi_sector += 1U;
		swapz_round056_invalidate_clone(&state.clone); /* bio_prepare_reissue */
		state.clone.bi_iter.bi_sector--;
		if (swapz_round056_complete_clone_view(&state.clone))
			return fail(case_number, scenario, "requeue-resurrected");
	}
	if (scenario == 25U) {
		state.clone.bi_iter.bi_size = 3072U;
		swapz_round056_invalidate_clone(&state.clone); /* bio_trim */
		state.clone.bi_iter.bi_size = SWAPZ_ROUND056_PAGE_BYTES;
		if (swapz_round056_complete_clone_view(&state.clone))
			return fail(case_number, scenario, "trim-resurrected");
	}
	if (scenario == 26U) {
		/* A cloned BIO cannot create a transitive source-owner proof. */
		struct bio transitive = state.clone;
		transitive.bi_round056_ticket = NULL;
		transitive.bi_round056_candidate = false;
		swapz_round056_propagate_full_clone(&transitive, &state.clone);
		if (transitive.bi_round056_ticket)
			return fail(case_number, scenario, "nested-clone-propagated");
	}
	if (scenario == 27U) {
		/* Mirror fail-after-core-clone-before-ticket: no extra ref transfer. */
		atomic_store(&swapz_round056_fail_next_clone, 1);
		if (atomic_exchange(&swapz_round056_fail_next_clone, 0) != 1 ||
		    refcount_read(&ticket->references) != 2U)
			return fail(case_number, scenario, "failed-clone-incorrect-ref");
	}
	/* The kernel, not this fixture, controls actual callback and bvec lifetime. */
	swapz_round056_drop_clone_ticket(&state.source);
	if (swapz_round056_complete_clone_view(&state.clone))
		return fail(case_number, scenario, "retired-source-still-eligible");
	if (refcount_read(&ticket->references) != 1U)
		return fail(case_number, scenario, "early-parent-release");
	swapz_round056_drop_clone_ticket(&state.clone);
	swapz_round056_drop_clone_ticket(&state.clone);
	if (atomic_load(&swapz_round056_ticket_frees) != freed_before + 1)
		return fail(case_number, scenario, "terminal-exact-one-free");
	return 0;
}

int main(void)
{
	unsigned int executed = 0U;
	for (unsigned int case_number = 0U; case_number < 3U; ++case_number)
		for (unsigned int scenario = 0U; scenario < 28U; ++scenario) {
			if (run_one(case_number, scenario))
				return 1;
			executed++;
		}
	if (executed != 84U) {
		fputs("ROUND056_CLONE_FIRST_ERROR case=0 scenario=0 stage=missing-case\n", stderr);
		return 1;
	}
	printf("ROUND056_CLONE_HOST_C_PASS cases=%u\n", executed);
	puts("SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED");
	return 0;
}
