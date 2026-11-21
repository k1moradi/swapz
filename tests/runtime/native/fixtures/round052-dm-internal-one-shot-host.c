/*
 * Round050: execute the ACTUAL default-off production C negative observer.
 * This host supplies only scalar stand-ins for real Linux types. It cannot
 * create a genuine original counted swap slot, DM table lease or lower IO.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint64_t sector_t;
typedef uint64_t swapz_u64;
typedef uint32_t swapz_u32;

#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define READ_ONCE(value) (value)
#define smp_load_acquire(pointer) (*(pointer))
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_SECTORS 8U
#define SWAPZ_MAX_COMPRESSED 3568U
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

static unsigned int bio_op(const struct bio *bio)
{
	return bio->bi_opf & 7U;
}

static sector_t bio_sectors(const struct bio *bio)
{
	return (sector_t)bio->bi_iter.bi_size / 512U;
}

/* These two source regions come byte-exactly from src/kernel/dm-target.c. */
/* ROUND052_INJECT_REAL_PRODUCT_TICKET_DECL */
/* ROUND052_INJECT_REAL_PRODUCT_TICKET_HELPER */

#include <stdlib.h>

struct round052_host {
	struct dm_target target;
	struct dm_target alien_target;
	struct swapz_dm context;
	struct bio upper_bio;
	struct bio alien_bio;
	struct swapz_round052_internal_ticket ticket;
	swapz_u32 maps[32];
	swapz_u32 generation;
	swapz_u32 gc_epoch;
	swapz_u32 extent_start;
	swapz_u32 extent_blocks;
};

static void round052_check(int actual, int expected,
		unsigned int extent_blocks, unsigned int fault,
		const char *stage)
{
	if (actual != expected) {
		fprintf(stderr,
			"FIRST Round052 actual product ticket C failure: "
			"extent_blocks=%u fault=%u stage=%s actual=%d expected=%d\n",
			extent_blocks, fault, stage, actual, expected);
		abort();
	}
}

static void round052_invariant(bool valid, unsigned int extent_blocks,
		unsigned int fault, const char *stage)
{
	if (!valid) {
		fprintf(stderr,
			"FIRST Round052 actual product ticket C failure: "
			"extent_blocks=%u fault=%u stage=%s invariant\n",
			extent_blocks, fault, stage);
		abort();
	}
}

static int round052_step(struct round052_host *host,
		enum swapz_round052_internal_event event,
		bool lower_durable, int lower_error)
{
	return swapz_round052_internal_ticket_step(
		&host->target, &host->context, &host->upper_bio,
		&host->ticket, event, host->generation, host->gc_epoch,
		host->extent_start, host->extent_blocks,
		lower_durable, lower_error);
}

static void round052_advance(struct round052_host *host,
		unsigned int extent_blocks, unsigned int fault,
		enum swapz_round052_internal_phase target_phase)
{
	if (host->ticket.phase < SWAPZ_ROUND052_LOWER_DONE &&
	    target_phase >= SWAPZ_ROUND052_LOWER_DONE)
		round052_check(round052_step(host, SWAPZ_ROUND052_LOWER_COMPLETE,
				true, 0), 0, extent_blocks, fault, "lower-complete");
	if (host->ticket.phase < SWAPZ_ROUND052_PUBLISHED &&
	    target_phase >= SWAPZ_ROUND052_PUBLISHED)
		round052_check(round052_step(host, SWAPZ_ROUND052_PUBLISH,
				true, 0), 0, extent_blocks, fault, "published");
	if (host->ticket.phase < SWAPZ_ROUND052_COMPLETED &&
	    target_phase >= SWAPZ_ROUND052_COMPLETED)
		round052_check(round052_step(host, SWAPZ_ROUND052_ACK,
				true, 0), 0, extent_blocks, fault, "simulated-ack");
}

static void round052_run_case(unsigned int extent_blocks, unsigned int fault)
{
	struct round052_host host = {
		.context = { .accepting = true, .logical_pages = 32U,
			.physical_blocks = 512U },
		.upper_bio = { .bi_opf = REQ_OP_WRITE | REQ_SWAP,
			.bi_iter = { .bi_sector = SWAPZ_SECTORS,
				.bi_size = SWAPZ_BLOCK_BYTES } },
		.generation = 7U,
		.gc_epoch = 9U,
		.extent_start = 16U,
		.extent_blocks = extent_blocks,
	};
	int expected = 0;
	int status;

	host.context.maps = host.maps;
	host.context.authority.maps = host.maps;
	host.context.target = &host.target;
	host.target.private = &host.context;
	host.target.len = 32U * SWAPZ_SECTORS;
	if (fault >= 2U && fault <= 16U) {
		switch (fault) {
		case 2U: host.upper_bio.bi_opf = REQ_OP_WRITE; expected = -ERANGE; break;
		case 3U: host.upper_bio.bi_opf = REQ_OP_READ | REQ_SWAP; expected = -ERANGE; break;
		case 4U: host.upper_bio.bi_iter.bi_size -= 512U; expected = -ERANGE; break;
		case 5U: host.upper_bio.bi_iter.bi_size += 512U; expected = -ERANGE; break;
		case 6U: host.upper_bio.bi_iter.bi_sector = 1U; expected = -ERANGE; break;
		case 7U: host.upper_bio.bi_iter.bi_sector = host.target.len; expected = -ERANGE; break;
		case 8U: host.target.private = NULL; expected = -ESTALE; break;
		case 9U: host.context.target = NULL; expected = -ESTALE; break;
		case 10U: host.context.authority.maps = NULL; expected = -ESTALE; break;
		case 11U: host.context.maps = NULL; expected = -ESTALE; break;
		case 12U: host.context.accepting = false; expected = -ESHUTDOWN; break;
		case 13U: host.context.failed = true; expected = -ESHUTDOWN; break;
		case 14U: host.generation = 0U; expected = -ERANGE; break;
		case 15U: host.gc_epoch = 0U; expected = -ERANGE; break;
		case 16U: host.extent_blocks = 3U; expected = -ERANGE; break;
		default: assert(0 && "invalid before-accept case");
		}
		status = round052_step(&host, SWAPZ_ROUND052_ACCEPT, false, 0);
		round052_check(status, expected, extent_blocks, fault, "admission-refuse");
		round052_invariant(host.ticket.phase == SWAPZ_ROUND052_NOT_ACCEPTED &&
			host.ticket.terminal_releases == 0U &&
			host.ticket.upper_ack_attempts == 0U,
			extent_blocks, fault, "no-admission-side-effect");
		return;
	}
	if (fault >= 17U && fault <= 20U) {
		enum swapz_round052_internal_event event =
			fault == 17U ? SWAPZ_ROUND052_LOWER_COMPLETE :
			fault == 18U ? SWAPZ_ROUND052_PUBLISH :
			fault == 19U ? SWAPZ_ROUND052_ACK : SWAPZ_ROUND052_ABORT;
		expected = fault == 20U ? -ENOENT : -EPERM;
		round052_check(round052_step(&host, event, true, -EIO), expected,
			extent_blocks, fault, "event-before-admission");
		round052_invariant(host.ticket.phase == SWAPZ_ROUND052_NOT_ACCEPTED,
			extent_blocks, fault, "unaccepted-retained");
		return;
	}
	round052_check(round052_step(&host, SWAPZ_ROUND052_ACCEPT, false, 0), 0,
		extent_blocks, fault, "accepted");
	if (fault == 1U) {
		round052_check(round052_step(&host, SWAPZ_ROUND052_ACCEPT, false, 0),
			-EALREADY, extent_blocks, fault, "duplicate-admission");
	}
	if (fault == 21U) {
		round052_check(round052_step(&host, SWAPZ_ROUND052_LOWER_COMPLETE,
			false, 0), -EAGAIN, extent_blocks, fault, "pending-lower");
		round052_invariant(host.ticket.phase == SWAPZ_ROUND052_ACCEPTED &&
			host.ticket.lower_callbacks == 0U, extent_blocks, fault,
			"no-premature-callback");
	} else if (fault == 22U) {
		round052_check(round052_step(&host, SWAPZ_ROUND052_LOWER_COMPLETE,
			true, -EIO), -EIO, extent_blocks, fault, "lower-error-abort");
	} else if (fault == 23U) {
		round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_LOWER_DONE);
		round052_check(round052_step(&host, SWAPZ_ROUND052_LOWER_COMPLETE,
			true, 0), -EALREADY, extent_blocks, fault, "duplicate-callback");
	} else if (fault == 24U) {
		round052_check(round052_step(&host, SWAPZ_ROUND052_PUBLISH,
			true, 0), -EAGAIN, extent_blocks, fault, "premature-publish");
	} else if (fault == 25U) {
		round052_check(round052_step(&host, SWAPZ_ROUND052_ACK,
			true, 0), -EAGAIN, extent_blocks, fault, "premature-ack");
	} else if (fault == 26U) {
		round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_PUBLISHED);
		round052_check(round052_step(&host, SWAPZ_ROUND052_PUBLISH,
			true, 0), -EAGAIN, extent_blocks, fault, "duplicate-publish");
	} else if (fault == 27U) {
		round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_LOWER_DONE);
		round052_check(round052_step(&host, SWAPZ_ROUND052_ACK,
			true, 0), -EAGAIN, extent_blocks, fault, "ack-before-map");
	} else if (fault >= 28U && fault <= 31U) {
		round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_COMPLETED);
		if (fault == 28U) status = round052_step(&host, SWAPZ_ROUND052_ACK, true, 0);
		else if (fault == 29U) status = round052_step(&host, SWAPZ_ROUND052_ABORT, true, -EIO);
		else if (fault == 30U) status = round052_step(&host, SWAPZ_ROUND052_LOWER_COMPLETE, true, 0);
		else status = round052_step(&host, SWAPZ_ROUND052_ACCEPT, true, 0);
		round052_check(status, -EALREADY, extent_blocks, fault, "late-terminal-event");
	} else if (fault == 32U || fault == 33U) {
		if (fault == 32U) host.context.accepting = false;
		else host.context.failed = true;
		round052_check(round052_step(&host, SWAPZ_ROUND052_LOWER_COMPLETE,
			true, 0), -ESHUTDOWN, extent_blocks, fault, "closed-target");
		/* The explicit abort never dereferences a potentially draining target. */
		round052_check(round052_step(&host, SWAPZ_ROUND052_ABORT,
			false, -ECANCELED), -ECANCELED, extent_blocks, fault, "closed-abort");
	} else if (fault >= 34U && fault <= 41U) {
		const struct bio *wrong_bio = &host.upper_bio;
		const struct dm_target *wrong_target = &host.target;
		if (fault == 34U) host.upper_bio.bi_iter.bi_sector += SWAPZ_SECTORS;
		if (fault == 35U) wrong_bio = &host.alien_bio;
		if (fault == 36U) wrong_target = &host.alien_target;
		if (fault == 37U) host.context.authority.maps = NULL;
		if (fault == 38U) host.generation++;
		if (fault == 39U) host.gc_epoch++;
		if (fault == 40U) host.extent_start++;
		if (fault == 41U) host.extent_blocks = extent_blocks == 1U ? 2U : 1U;
		status = swapz_round052_internal_ticket_step(
			wrong_target, &host.context, wrong_bio, &host.ticket,
			SWAPZ_ROUND052_LOWER_COMPLETE, host.generation,
			host.gc_epoch, host.extent_start, host.extent_blocks,
			true, 0);
		round052_check(status, -ESTALE, extent_blocks, fault, "reissue-gc-aba");
		round052_invariant(host.ticket.phase == SWAPZ_ROUND052_ACCEPTED &&
			host.ticket.terminal_releases == 0U,
			extent_blocks, fault, "stale-callback-must-not-mutate");
		/* Restore the test snapshot before final synchronous release. */
		host.upper_bio.bi_iter.bi_sector = SWAPZ_SECTORS;
		host.context.authority.maps = host.maps;
		host.generation = 7U;
		host.gc_epoch = 9U;
		host.extent_start = 16U;
		host.extent_blocks = extent_blocks;
		round052_check(round052_step(&host, SWAPZ_ROUND052_ABORT,
			false, -ECANCELED), -ECANCELED, extent_blocks, fault, "stale-abort");
	} else if (fault >= 42U && fault <= 47U) {
		if (fault == 43U) round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_LOWER_DONE);
		if (fault == 44U) round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_PUBLISHED);
		round052_check(round052_step(&host, SWAPZ_ROUND052_ABORT,
			false, -ECANCELED), -ECANCELED, extent_blocks, fault, "terminal-abort");
		if (fault >= 45U) {
			enum swapz_round052_internal_event event =
				fault == 45U ? SWAPZ_ROUND052_LOWER_COMPLETE :
				fault == 46U ? SWAPZ_ROUND052_ACK : SWAPZ_ROUND052_ABORT;
			round052_check(round052_step(&host, event, true, 0), -EALREADY,
				extent_blocks, fault, "event-after-abort");
		}
	}
	/* Every accepted ordinary BIO has one and only one terminal release. */
	if (host.ticket.phase != SWAPZ_ROUND052_ABORTED &&
	    host.ticket.phase != SWAPZ_ROUND052_COMPLETED)
		round052_advance(&host, extent_blocks, fault, SWAPZ_ROUND052_COMPLETED);
	if (host.ticket.phase == SWAPZ_ROUND052_COMPLETED)
		round052_invariant(host.ticket.lower_callbacks == 1U &&
			host.ticket.map_publications == 1U &&
			host.ticket.upper_ack_attempts == 1U &&
			host.ticket.terminal_releases == 1U,
			extent_blocks, fault, "exact-single-completion");
	else
		round052_invariant(host.ticket.upper_ack_attempts == 0U &&
			host.ticket.terminal_releases == 1U,
			extent_blocks, fault, "exact-single-abort-release");
}

int main(void)
{
	unsigned int extent_blocks;
	unsigned int fault;
	unsigned int executed_cases = 0U;

	for (extent_blocks = 1U; extent_blocks <= 4U; extent_blocks *= 2U) {
		for (fault = 0U; fault < 48U; ++fault) {
			round052_run_case(extent_blocks, fault);
			++executed_cases;
		}
	}
	round052_invariant(executed_cases == 144U, 0U, 0U,
		"required-144-real-source-cases");
	puts("ROUND052_REAL_PRODUCT_INTERNAL_TICKET_144_C_CASES_PASS");
	puts("ROUND052_SOURCE_MAPPED_AUTHENTICATED=0");
	return 0;
}
