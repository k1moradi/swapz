// SPDX-License-Identifier: GPL-2.0-only
/*
 * Tests the exact, production-included flush meter. A zero-length
 * REQ_OP_WRITE|REQ_PREFLUSH upper BIO is Linux's legitimate flush
 * request; REQ_OP_FLUSH is a request-only opcode and must never be
 * submitted as a BIO by the test harness.
 *
 * Tests distinguish test-injected EIO BEFORE submission from actual
 * lower callback -EIO, and never imply a physical cache command was
 * issued (a lower queue may have no volatile write cache).
 */
#include <stdio.h>
#include <errno.h>
#include <stdbool.h>
#include "flush-qual.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)
struct fake_lower {
	unsigned int called;
	int next_error;
	void (*on_call)(void *);
	void *on_call_opaque;
};
static int lower_flush(void *p)
{
	struct fake_lower *ctx = p;

	ctx->called++;
	if (ctx->on_call)
		ctx->on_call(ctx->on_call_opaque);
	return ctx->next_error;
}
static int test_completed_success(void)
{
	struct swapz_flush_meter s = { 0 };
	struct fake_lower lower = { 0 };

	CHECK(swapz_flush_accounted(&s, lower_flush, &lower) == 0);
	CHECK(s.attempts == 1 && s.successes == 1 && !s.failures);
	CHECK(!s.injected && lower.called == 1);
	return 0;
}
static int test_synthetic_failure_before_lower(void)
{
	struct swapz_flush_meter s = { .fail_nth = 2 };
	struct fake_lower lower = { 0 };

	CHECK(swapz_flush_accounted(&s, lower_flush, &lower) == 0);
	CHECK(swapz_flush_accounted(&s, lower_flush, &lower) == -EIO);
	CHECK(lower.called == 1 && s.attempts == 2);
	CHECK(s.failures == 1 && s.injected == 1 && s.successes == 1);
	CHECK(swapz_flush_accounted(&s, lower_flush, &lower) == 0);
	CHECK(lower.called == 2 && s.successes == 2 &&
	      s.failures == 1 && s.attempts == 3 && s.injected == 1);
	return 0;
}
static int test_genuine_lower_error(void)
{
	struct swapz_flush_meter s = { 0 };
	struct fake_lower lower = { .next_error = -EIO };

	CHECK(swapz_flush_accounted(&s, lower_flush, &lower) == -EIO);
	CHECK(s.attempts == 1 && s.failures == 1 && !s.successes);
	CHECK(!s.injected && lower.called == 1);
	return 0;
}
static int test_unsupported_lower_flush_retains_errno(void)
{
	struct swapz_flush_meter meter = { 0 };
	struct fake_lower lower = { .next_error = -EOPNOTSUPP };

	CHECK(swapz_flush_accounted(&meter, lower_flush, &lower) ==
	      -EOPNOTSUPP);
	CHECK(lower.called == 1 && meter.attempts == 1);
	CHECK(meter.failures == 1 && !meter.successes && !meter.injected);
	CHECK(swapz_write_flush_before_publish(0, 1, lower_flush, &lower)
	      == -EOPNOTSUPP);
	CHECK(lower.called == 2);
	return 0;
}

static int test_null_argument_rejected(void)
{
	struct swapz_flush_meter s = { 0 };

	CHECK(swapz_flush_accounted(NULL, lower_flush, NULL) == -EINVAL);
	CHECK(swapz_flush_accounted(&s, NULL, NULL) == -EINVAL);
	CHECK(s.attempts == 0 && !s.successes && !s.failures);
	return 0;
}
static int test_prepublication_fua_write_gate(void)
{
	struct fake_lower lower = { 0 };

	/* A lower WRITE failure cannot trigger a success-shaped FUA. */
	CHECK(swapz_write_flush_before_publish(-EIO, 1, lower_flush,
						 &lower) == -EIO);
	CHECK(lower.called == 0);
	/* Non-FUA writes do not gain an extra hardware flush. */
	CHECK(swapz_write_flush_before_publish(0, 0, lower_flush,
						 &lower) == 0);
	CHECK(lower.called == 0);
	CHECK(swapz_write_flush_before_publish(0, 1, lower_flush,
						 &lower) == 0);
	CHECK(lower.called == 1);
	lower.next_error = -EIO;
	CHECK(swapz_write_flush_before_publish(0, 1, lower_flush,
						 &lower) == -EIO);
	CHECK(lower.called == 2);
	CHECK(swapz_write_flush_before_publish(0, 1, NULL, &lower) == -EINVAL);
	CHECK(lower.called == 2);
	return 0;
}


/*
 * The ordered target's WRITE success can be acknowledged only after the
 * production prepublication FUA gate observes the real lower flush result.
 * This model has no block devices or synthetic successful completions.
 *
 * Negative control: compile with SWAPZ_TEST_BYPASS_FUA_GATE to publish the
 * generation BEFORE the gate. The failed-flush assertion must then fail.
 */
struct durable_upper {
	struct fake_lower flush;
	unsigned int generation;
	unsigned int success_acks;
	unsigned int lower_write_calls;
	int lower_write_error;
};

static int submit_durable_upper(struct durable_upper *upper, int fua)
{
	int error;

	upper->lower_write_calls++;
#ifdef SWAPZ_TEST_BYPASS_FUA_GATE
	/* Deliberately broken publication order; never used by production. */
	if (!upper->lower_write_error) {
		upper->generation++;
		upper->success_acks++;
	}
#endif
	error = swapz_write_flush_before_publish(upper->lower_write_error, fua,
						  lower_flush, &upper->flush);
#ifndef SWAPZ_TEST_BYPASS_FUA_GATE
	if (!error) {
		upper->generation++;
		upper->success_acks++;
	}
#endif
	return error;
}

static int test_no_ack_or_new_generation_before_fua(void)
{
	struct durable_upper upper = { 0 };

	CHECK(submit_durable_upper(&upper, 1) == 0);
	CHECK(upper.generation == 1 && upper.success_acks == 1);
	upper.flush.next_error = -EIO;
	CHECK(submit_durable_upper(&upper, 1) == -EIO);
	CHECK(upper.generation == 1 && upper.success_acks == 1);
	CHECK(upper.flush.called == 2);
	upper.flush.next_error = 0;
	upper.lower_write_error = -EIO;
	CHECK(submit_durable_upper(&upper, 1) == -EIO);
	CHECK(upper.flush.called == 2);
	CHECK(upper.generation == 1 && upper.success_acks == 1);
	upper.lower_write_error = 0;
	CHECK(submit_durable_upper(&upper, 1) == 0);
	CHECK(upper.flush.called == 3);
	CHECK(upper.generation == 2 && upper.success_acks == 2);
	CHECK(upper.lower_write_calls == 4);
	return 0;
}


/*
 * Rootless callback/drain scheduling model, not a loaded DM callback.
 * The final publication gate is the exact production FUA helper.
 * SWAPZ_TEST_BYPASS_LOWER_COMPLETION_FENCE is the negative control.
 */
struct lower_completion_fixture {
	struct durable_upper upper;
	unsigned int callbacks;
	unsigned int final_completions;
	bool callback_done;
	bool upper_done;
	int lower_error;
	int terminal_error;
	int final_error;
};

static void record_terminal_failure(struct lower_completion_fixture *fixture,
				    int error)
{
	if (error && !fixture->terminal_error)
		fixture->terminal_error = error;
}

static void lower_callback(struct lower_completion_fixture *fixture, int error)
{
	fixture->callbacks++;
	fixture->callback_done = true;
	fixture->lower_error = error;
	record_terminal_failure(fixture, error);
}

static int finalize_or_drain(struct lower_completion_fixture *fixture)
{
	int error;

	if (fixture->upper_done)
		return fixture->final_error;
#ifndef SWAPZ_TEST_BYPASS_LOWER_COMPLETION_FENCE
	if (!fixture->callback_done)
		return -EAGAIN;
#endif
	fixture->upper.lower_write_error = fixture->lower_error ?
		fixture->lower_error : fixture->terminal_error;
	error = submit_durable_upper(&fixture->upper, 1);
	fixture->upper_done = true;
	fixture->final_completions++;
	fixture->final_error = error;
	return error;
}

static int test_callback_before_or_after_drain(void)
{
	unsigned int order, error_case;

	for (order = 0; order < 2; ++order) {
		for (error_case = 0; error_case < 3; ++error_case) {
			struct lower_completion_fixture fixture = { 0 };
			int expected_error = error_case == 0 ? 0 :
				error_case == 1 ? -EIO : -EOPNOTSUPP;

			if (order == 0)
				lower_callback(&fixture, expected_error);
			else
				CHECK(finalize_or_drain(&fixture) == -EAGAIN);
			if (order != 0)
				lower_callback(&fixture, expected_error);
			CHECK(finalize_or_drain(&fixture) == expected_error);
			CHECK(finalize_or_drain(&fixture) == expected_error);
			CHECK(fixture.callbacks == 1 &&
			      fixture.final_completions == 1);
			CHECK(fixture.upper.lower_write_calls == 1);
			CHECK(fixture.upper.success_acks ==
			      (expected_error == 0 ? 1U : 0U));
			CHECK(fixture.upper.generation ==
			      (expected_error == 0 ? 1U : 0U));
			CHECK(fixture.upper.flush.called ==
			      (expected_error == 0 ? 1U : 0U));
		}
	}
	return 0;
}

static int test_first_terminal_error_and_no_late_success(void)
{
	struct lower_completion_fixture lower_first = { 0 };
	struct lower_completion_fixture generic_first = { 0 };
	struct lower_completion_fixture success_then_failure = { 0 };

	lower_callback(&lower_first, -EOPNOTSUPP);
	record_terminal_failure(&lower_first, -EIO);
	CHECK(lower_first.terminal_error == -EOPNOTSUPP);
	CHECK(finalize_or_drain(&lower_first) == -EOPNOTSUPP);
	CHECK(lower_first.final_completions == 1);
	CHECK(!lower_first.upper.success_acks && !lower_first.upper.generation);

	record_terminal_failure(&generic_first, -EIO);
	lower_callback(&generic_first, -EOPNOTSUPP);
	CHECK(generic_first.terminal_error == -EIO);
	/* The run reports its own lower errno but still cannot publish success. */
	CHECK(finalize_or_drain(&generic_first) == -EOPNOTSUPP);
	CHECK(generic_first.final_completions == 1);
	CHECK(!generic_first.upper.success_acks && !generic_first.upper.generation);

	lower_callback(&success_then_failure, 0);
	record_terminal_failure(&success_then_failure, -EIO);
	CHECK(success_then_failure.terminal_error == -EIO);
	CHECK(finalize_or_drain(&success_then_failure) == -EIO);
	CHECK(success_then_failure.final_completions == 1);
	CHECK(!success_then_failure.upper.success_acks &&
	      !success_then_failure.upper.generation);
	CHECK(success_then_failure.upper.flush.called == 0);
	return 0;
}

/*
 * Finite, rootless ordered-owner model: synchronous preflush and FUA use the
 * exact production helpers; only the data WRITE completion is scheduled.
 * Every modeled data callback refers to ONE submitted, owned lower BIO.
 * A duplicate notification is a protocol-invalid repeat of that callback,
 * not evidence of a second lower BIO or independent completion.
 * Empty flush cases model only zero-sector WRITE|PREFLUSH: without data,
 * Linux's flush state machine has no meaningful FUA data or postflush step.
 */
enum ordered_upper_kind {
	ORDERED_DATA_WRITE,
	ORDERED_EMPTY_PREFLUSH_WRITE,
};

struct ordered_scenario {
	const char *name;
	enum ordered_upper_kind kind;
	bool preflush;
	bool fua;
	int preflush_errno;
	int data_errno;
	int fua_errno;
	int expected_errno;
};

struct ordered_fixture {
	const struct ordered_scenario *scenario;
	struct swapz_flush_meter flush_meter;
	struct fake_lower lower;
	unsigned int generation;
	unsigned int authoritative_extent;
	unsigned int successful_acks;
	unsigned int durable_publications;
	unsigned int data_submissions;
	unsigned int data_completions;
	unsigned int callback_notifications;
	unsigned int duplicate_notifications;
	unsigned int upper_completions;
	unsigned int retry_upper_completions;
	unsigned int fua_gate_observations;
	unsigned int premature_fua_acks;
	bool drained;
	bool preflush_done;
	bool data_submitted;
	bool data_done;
	bool upper_done;
	int data_errno;
	int original_lower_errno;
	int terminal_errno;
	int upper_errno;
};

static int ordered_check(const struct ordered_fixture *fixture,
			 const char *phase, bool valid, int expected, int actual)
{
	if (valid)
		return 0;
	fprintf(stderr,
		"flush request=%s phase=%s original_lower_errno=%d "
		"expected_ack_errno=%d actual_ack_errno=%d "
		"expected=%d actual=%d acks=%u publications=%u generations=%u "
		"outstanding_lower_owners=%u outstanding_upper_owners=%u\n",
		fixture->scenario->name, phase, fixture->original_lower_errno,
		fixture->scenario->expected_errno, fixture->upper_done ?
		fixture->upper_errno : -EAGAIN, expected, actual,
		fixture->successful_acks, fixture->durable_publications,
		fixture->generation,
		fixture->data_submissions - fixture->data_completions,
		fixture->upper_done ? 0U : 1U);
	return 1;
}

#define ORDERED_CHECK(fixture, phase, condition, expected, actual) do { \
	if (ordered_check((fixture), (phase), (condition), (expected), (actual))) \
		return 1; \
} while (0)

static int ordered_account_flush(void *opaque)
{
	struct ordered_fixture *fixture = opaque;

	return swapz_flush_accounted(&fixture->flush_meter, lower_flush,
				     &fixture->lower);
}

static void ordered_record_terminal_failure(struct ordered_fixture *fixture,
					    int error)
{
	if (error && !fixture->terminal_errno)
		fixture->terminal_errno = error;
}

static int ordered_complete_upper(struct ordered_fixture *fixture, int error)
{
	if (fixture->upper_done)
		return fixture->upper_errno;
	fixture->upper_done = true;
	fixture->upper_completions++;
	fixture->upper_errno = error;
	if (error) {
		ordered_record_terminal_failure(fixture, error);
	} else {
		fixture->successful_acks++;
		if (fixture->scenario->kind == ORDERED_DATA_WRITE) {
			fixture->durable_publications++;
			fixture->generation++;
			fixture->authoritative_extent = 0x92U;
		}
	}
	return error;
}

static int ordered_advance(struct ordered_fixture *fixture)
{
	const struct ordered_scenario *scenario = fixture->scenario;
	int error;

	if (fixture->upper_done)
		return fixture->upper_errno;
	if (!fixture->drained)
		return -EAGAIN;
	if (scenario->preflush && !fixture->preflush_done) {
		fixture->lower.next_error = scenario->preflush_errno;
		error = ordered_account_flush(fixture);
		fixture->preflush_done = true;
		if (error) {
			fixture->original_lower_errno = error;
#ifndef SWAPZ_TEST_BYPASS_PREFLUSH_FENCE
			return ordered_complete_upper(fixture, error);
#endif
		}
	}
	if (scenario->kind == ORDERED_EMPTY_PREFLUSH_WRITE)
		return ordered_complete_upper(fixture, 0);
	if (!fixture->data_submitted) {
		fixture->data_submitted = true;
		fixture->data_submissions++;
		return -EAGAIN;
	}
	if (!fixture->data_done)
		return -EAGAIN;
	/*
	 * Detached asynchronous writes never carry FUA in production. If another
	 * terminal failure was elected while this non-FUA lower write was pending,
	 * a successful callback cannot publish or acknowledge success.
	 */
	if (!scenario->fua && !fixture->data_errno && fixture->terminal_errno)
		return ordered_complete_upper(fixture, fixture->terminal_errno);
	fixture->lower.next_error = scenario->fua_errno;
	error = swapz_write_flush_before_publish(fixture->data_errno,
						       scenario->fua,
						       ordered_account_flush,
						       fixture);
	if (error && !fixture->original_lower_errno)
		fixture->original_lower_errno = error;
	return ordered_complete_upper(fixture, error);
}

static void ordered_data_callback(struct ordered_fixture *fixture, int error)
{
	fixture->callback_notifications++;
	if (!fixture->data_submitted || fixture->data_done) {
		fixture->duplicate_notifications++;
		return;
	}
	/*
	 * Production async completion elects its lower errno before publishing
	 * lower_done. Model that order so drain/retry sees the same first-failure
	 * latch as swapz_async_lower_write_done().
	 */
	if (error) {
		if (!fixture->original_lower_errno)
			fixture->original_lower_errno = error;
		ordered_record_terminal_failure(fixture, error);
	}
	fixture->data_errno = error;
	fixture->data_done = true;
	fixture->data_completions++;
}

static int ordered_retry_after_failure(struct ordered_fixture *fixture)
{
	/*
	 * This is a fresh upper BIO completed from the latched terminal error.
	 * It is not another completion of the already-owned lower data BIO.
	 */
	if (!fixture->terminal_errno)
		return -EINVAL;
	fixture->retry_upper_completions++;
	return fixture->terminal_errno;
}

static int test_ordered_preflush_data_fua_matrix(void)
{
	static const struct ordered_scenario scenarios[] = {
		{ "WRITE|PREFLUSH|FUA", ORDERED_DATA_WRITE, true, true,
		  0, 0, 0, 0 },
		{ "WRITE|PREFLUSH preflush-failure", ORDERED_DATA_WRITE,
		  true, true, -EOPNOTSUPP, 0, 0, -EOPNOTSUPP },
		{ "WRITE|PREFLUSH data-failure", ORDERED_DATA_WRITE,
		  true, true, 0, -EIO, 0, -EIO },
		{ "WRITE|PREFLUSH FUA-failure", ORDERED_DATA_WRITE,
		  true, true, 0, 0, -EIO, -EIO },
		{ "WRITE|FUA FUA-failure", ORDERED_DATA_WRITE,
		  false, true, 0, 0, -EOPNOTSUPP, -EOPNOTSUPP },
		{ "WRITE|PREFLUSH without-FUA", ORDERED_DATA_WRITE,
		  true, false, 0, 0, 0, 0 },
		{ "empty WRITE|PREFLUSH", ORDERED_EMPTY_PREFLUSH_WRITE,
		  true, false, 0, 0, 0, 0 },
		{ "empty WRITE|PREFLUSH failure", ORDERED_EMPTY_PREFLUSH_WRITE,
		  true, false, -EIO, 0, 0, -EIO },
	};
	unsigned int index;

	for (index = 0; index < sizeof(scenarios) / sizeof(scenarios[0]);
	     ++index) {
		const struct ordered_scenario *scenario = &scenarios[index];
		const char *completion_phase = scenario->fua ?
			"data-fua-completion" : "data-completion";
		struct ordered_fixture fixture = {
			.scenario = scenario,
			.generation = 7,
			.authoritative_extent = 0x91U,
		};
		unsigned int expected_data = scenario->kind ==
			ORDERED_DATA_WRITE && !scenario->preflush_errno;
		unsigned int expected_flushes = scenario->preflush ? 1U : 0U;
		unsigned int expected_acks = !scenario->expected_errno;
		unsigned int expected_publications;
		unsigned int expected_failed_flushes;
		int result;

#ifdef SWAPZ_TEST_BYPASS_PREFLUSH_FENCE
		/*
		 * Drive the broken path through the delayed data completion and
		 * FUA so the mutant demonstrates a forbidden success ACK, rather
		 * than stopping merely because data submission became possible.
		 */
		if (scenario->kind == ORDERED_DATA_WRITE &&
		    scenario->preflush_errno)
			expected_data = 1U;
#endif
		expected_publications =
			expected_data && expected_acks ? 1U : 0U;

		/* Both previous work and this request are fenced by drain. */
		result = ordered_advance(&fixture);
		ORDERED_CHECK(&fixture, "pre-drain", result == -EAGAIN &&
			!fixture.flush_meter.attempts && !fixture.data_submissions,
			-EAGAIN, result);
		fixture.drained = true;
		result = ordered_advance(&fixture);
		if (!expected_data) {
			ORDERED_CHECK(&fixture, "preflush-completion",
				result == scenario->expected_errno,
				scenario->expected_errno, result);
		} else {
			ORDERED_CHECK(&fixture, "data-submission",
				result == -EAGAIN && fixture.data_submissions == 1,
				-EAGAIN, result);
			/* A drain before the delayed lower callback cannot ACK. */
			result = ordered_advance(&fixture);
			ORDERED_CHECK(&fixture, "delayed-data-completion",
				result == -EAGAIN && !fixture.upper_done,
				-EAGAIN, result);
			ordered_data_callback(&fixture, scenario->data_errno);
			/* Duplicate notification is NOT a second owned lower BIO. */
			ordered_data_callback(&fixture, scenario->data_errno);
			result = ordered_advance(&fixture);
			ORDERED_CHECK(&fixture, completion_phase,
				result == scenario->expected_errno,
				scenario->expected_errno, result);
			ordered_data_callback(&fixture, scenario->data_errno);
			ORDERED_CHECK(&fixture, "duplicate-terminal-callback",
				fixture.data_completions == 1 &&
				fixture.callback_notifications == 3 &&
				fixture.duplicate_notifications == 2 &&
				fixture.data_errno == scenario->data_errno,
				1, fixture.data_completions);
		}
		if (expected_data && scenario->fua && !scenario->data_errno)
			expected_flushes++;
		expected_failed_flushes = (scenario->preflush_errno != 0) +
			(scenario->fua_errno != 0 && expected_data &&
			 scenario->fua && !scenario->data_errno);
		ORDERED_CHECK(&fixture, "upper-completion",
			fixture.upper_done && fixture.upper_completions == 1 &&
			!fixture.retry_upper_completions &&
			fixture.successful_acks == expected_acks &&
			fixture.durable_publications == expected_publications &&
			fixture.generation == 7 + expected_publications &&
			fixture.authoritative_extent ==
				(expected_publications ? 0x92U : 0x91U) &&
			fixture.original_lower_errno == scenario->expected_errno &&
			fixture.data_submissions == expected_data &&
			fixture.data_completions == expected_data &&
			fixture.flush_meter.attempts == expected_flushes &&
			fixture.flush_meter.successes ==
				expected_flushes - expected_failed_flushes &&
			fixture.flush_meter.failures == expected_failed_flushes &&
			!fixture.flush_meter.injected &&
			fixture.lower.called == expected_flushes,
			(int)expected_acks, (int)fixture.successful_acks);
		/* Repeated drain cannot complete the same upper BIO again. */
		result = ordered_advance(&fixture);
		ORDERED_CHECK(&fixture, "drain-after-terminal",
			result == scenario->expected_errno &&
			fixture.upper_completions == 1 &&
			!fixture.retry_upper_completions &&
			fixture.successful_acks == expected_acks &&
			fixture.durable_publications == expected_publications &&
			fixture.data_submissions == expected_data &&
			fixture.data_completions == expected_data &&
			fixture.flush_meter.attempts == expected_flushes &&
			fixture.lower.called == expected_flushes,
			scenario->expected_errno, result);
		if (scenario->expected_errno) {
			result = ordered_retry_after_failure(&fixture);
			ORDERED_CHECK(&fixture, "retry-after-error",
				result == scenario->expected_errno &&
				fixture.retry_upper_completions == 1 &&
				fixture.upper_completions == 1 &&
				fixture.successful_acks == 0 &&
				fixture.durable_publications == 0 &&
				fixture.generation == 7 &&
				fixture.authoritative_extent == 0x91U &&
				fixture.data_submissions == expected_data &&
				fixture.data_completions == expected_data &&
				fixture.flush_meter.attempts == expected_flushes &&
				fixture.lower.called == expected_flushes,
				scenario->expected_errno, result);
		}
	}
	return 0;
}


/*
 * Rootless model of the production PREFLUSH boundary: older detached lower
 * WRITE ownership is joined before the current lower preflush can be issued.
 */
static int ordered_preflush_after_prior_lower(struct ordered_fixture *fixture)
{
	int error;

	if (fixture->upper_done)
		return fixture->upper_errno;
	if (!fixture->data_done)
		return -EAGAIN;
	if (fixture->data_errno)
		return ordered_complete_upper(fixture, fixture->data_errno);

	fixture->lower.next_error = fixture->scenario->preflush_errno;
	error = ordered_account_flush(fixture);
	fixture->preflush_done = true;
	if (error && !fixture->original_lower_errno)
		fixture->original_lower_errno = error;
	return ordered_complete_upper(fixture, error);
}

/*
 * A production PREFLUSH boundary first joins every older detached lower WRITE.
 * Therefore a callback failure discovered while draining prevents PREFLUSH
 * submission, while a PREFLUSH that is actually issued has no older callback
 * owner left to fail afterwards.
 */
static int test_preflush_barrier_owns_callback_precedence(void)
{
	const struct ordered_scenario callback_failure = {
		.name = "prior-callback-failure-before-PREFLUSH",
		.kind = ORDERED_EMPTY_PREFLUSH_WRITE, .preflush = true,
		.preflush_errno = -EIO, .expected_errno = -EOPNOTSUPP,
	};
	struct ordered_fixture callback_fixture = {
		.scenario = &callback_failure, .generation = 7,
		.authoritative_extent = 0x91U,
		.data_submitted = true, .data_submissions = 1,
	};
	const struct ordered_scenario preflush_failure = {
		.name = "PREFLUSH-failure-after-prior-callback-success",
		.kind = ORDERED_EMPTY_PREFLUSH_WRITE, .preflush = true,
		.preflush_errno = -EIO, .expected_errno = -EIO,
	};
	struct ordered_fixture preflush_fixture = {
		.scenario = &preflush_failure, .generation = 7,
		.authoritative_extent = 0x91U,
		.data_submitted = true, .data_submissions = 1,
	};
	int error;

	error = ordered_preflush_after_prior_lower(&callback_fixture);
	ORDERED_CHECK(&callback_fixture, "preflush-waits-prior-owner",
		error == -EAGAIN && !callback_fixture.upper_done &&
		!callback_fixture.flush_meter.attempts,
		-EAGAIN, error);
	ordered_data_callback(&callback_fixture, -EOPNOTSUPP);
	error = ordered_preflush_after_prior_lower(&callback_fixture);
	ORDERED_CHECK(&callback_fixture, "prior-callback-blocks-preflush",
		error == -EOPNOTSUPP &&
		callback_fixture.original_lower_errno == -EOPNOTSUPP &&
		callback_fixture.terminal_errno == -EOPNOTSUPP &&
		callback_fixture.data_completions == 1 &&
		callback_fixture.upper_completions == 1 &&
		!callback_fixture.flush_meter.attempts &&
		!callback_fixture.lower.called &&
		!callback_fixture.successful_acks &&
		!callback_fixture.durable_publications &&
		callback_fixture.generation == 7 &&
		callback_fixture.authoritative_extent == 0x91U,
		-EOPNOTSUPP, error);
	error = ordered_retry_after_failure(&callback_fixture);
	ORDERED_CHECK(&callback_fixture, "retry-after-prior-callback-failure",
		error == -EOPNOTSUPP &&
		callback_fixture.retry_upper_completions == 1 &&
		callback_fixture.upper_completions == 1 &&
		!callback_fixture.flush_meter.attempts &&
		!callback_fixture.lower.called,
		-EOPNOTSUPP, error);

	ordered_data_callback(&preflush_fixture, 0);
	error = ordered_preflush_after_prior_lower(&preflush_fixture);
	ORDERED_CHECK(&preflush_fixture, "preflush-fails-after-owner-drained",
		error == -EIO &&
		preflush_fixture.original_lower_errno == -EIO &&
		preflush_fixture.terminal_errno == -EIO &&
		preflush_fixture.data_completions == 1 &&
		preflush_fixture.data_submissions == 1 &&
		preflush_fixture.upper_completions == 1 &&
		preflush_fixture.flush_meter.attempts == 1 &&
		preflush_fixture.flush_meter.failures == 1 &&
		preflush_fixture.lower.called == 1 &&
		!preflush_fixture.successful_acks &&
		!preflush_fixture.durable_publications &&
		preflush_fixture.generation == 7 &&
		preflush_fixture.authoritative_extent == 0x91U,
		-EIO, error);
	return 0;
}

static void observe_delayed_fua_lower_call(void *opaque)
{
	struct ordered_fixture *fixture = opaque;

	/*
	 * This hook runs inside lower_flush(), before the synchronous FUA result
	 * returns to swapz_write_flush_before_publish().
	 */
	fixture->fua_gate_observations++;
	if (fixture->upper_done || fixture->successful_acks ||
	    fixture->durable_publications)
		fixture->premature_fua_acks++;
}

/*
 * A required FUA flush is synchronous in production. The lower-call hook
 * observes the request while that call is still outstanding and then returns
 * -EOPNOTSUPP, proving no ACK/publication can precede the lower evidence.
 */
static int test_unsupported_fua_still_owns_terminal_ack(void)
{
	const struct ordered_scenario scenario = {
		.name = "preflush-data-delayed-unsupported-FUA",
		.kind = ORDERED_DATA_WRITE, .preflush = true, .fua = true,
		.fua_errno = -EOPNOTSUPP, .expected_errno = -EOPNOTSUPP,
	};
	struct ordered_fixture fixture = {
		.scenario = &scenario, .generation = 7,
		.authoritative_extent = 0x91U, .drained = true,
	};
	int error = ordered_advance(&fixture);

	ORDERED_CHECK(&fixture, "data-awaiting-callback",
		error == -EAGAIN && fixture.data_submissions == 1 &&
		!fixture.data_completions && !fixture.upper_done &&
		fixture.flush_meter.attempts == 1,
		-EAGAIN, error);
	error = ordered_advance(&fixture);
	ORDERED_CHECK(&fixture, "lower-data-delayed",
		error == -EAGAIN && !fixture.upper_done &&
		!fixture.fua_gate_observations && !fixture.successful_acks,
		-EAGAIN, error);
	ordered_data_callback(&fixture, 0);
	fixture.lower.on_call = observe_delayed_fua_lower_call;
	fixture.lower.on_call_opaque = &fixture;
	error = ordered_advance(&fixture);
	ORDERED_CHECK(&fixture, "unsupported-FUA-return",
		error == -EOPNOTSUPP &&
		fixture.original_lower_errno == -EOPNOTSUPP &&
		fixture.terminal_errno == -EOPNOTSUPP &&
		fixture.fua_gate_observations == 1 &&
		!fixture.premature_fua_acks &&
		fixture.flush_meter.attempts == 2 &&
		fixture.flush_meter.successes == 1 &&
		fixture.flush_meter.failures == 1 &&
		fixture.data_completions == 1 &&
		fixture.upper_completions == 1 &&
		!fixture.successful_acks && !fixture.durable_publications &&
		fixture.generation == 7 && fixture.authoritative_extent == 0x91U,
		-EOPNOTSUPP, error);
	error = ordered_retry_after_failure(&fixture);
	ORDERED_CHECK(&fixture, "new-upper-after-unsupported-FUA",
		error == -EOPNOTSUPP &&
		fixture.retry_upper_completions == 1 &&
		fixture.upper_completions == 1 &&
		fixture.lower.called == 2 &&
		fixture.generation == 7 && !fixture.successful_acks,
		-EOPNOTSUPP, error);
	return 0;
}

/*
 * Detached lower WRITEs are non-FUA. A drain poll can overlap their final
 * callback, while an independent terminal failure may be elected before or
 * after that callback. The callback's own lower errno still completes its run;
 * a fresh upper retry observes the target's first latched terminal errno.
 */
static int test_terminal_failure_and_drain_cross_final_callback(void)
{
	static const int data_errors[] = { 0, -EIO, -EOPNOTSUPP };
	unsigned int order, fault;

	for (order = 0; order < 3; ++order) {
		for (fault = 0; fault < sizeof(data_errors) /
					   sizeof(data_errors[0]); ++fault) {
			const int data_error = data_errors[fault];
			const int generic_failure = -EUCLEAN;
			const int expected_ack = data_error ?
				data_error : generic_failure;
			const int expected_terminal = order == 1 && data_error ?
				data_error : generic_failure;
			const struct ordered_scenario scenario = {
				.name = "terminal-failure-during-owned-data-completion",
				.kind = ORDERED_DATA_WRITE, .preflush = false,
				.fua = false, .data_errno = data_error,
				.expected_errno = expected_ack,
			};
			struct ordered_fixture fixture = {
				.scenario = &scenario, .generation = 7,
				.authoritative_extent = 0x91U, .drained = true,
			};
			int error = ordered_advance(&fixture);

			ORDERED_CHECK(&fixture, "submit-before-terminal-overlap",
				error == -EAGAIN && fixture.data_submissions == 1 &&
				!fixture.flush_meter.attempts,
				-EAGAIN, error);
			if (order == 0) {
				ordered_record_terminal_failure(&fixture, generic_failure);
			} else if (order == 1) {
				ordered_data_callback(&fixture, data_error);
				ordered_record_terminal_failure(&fixture, generic_failure);
			} else {
				error = ordered_advance(&fixture);
				ORDERED_CHECK(&fixture, "drain-before-final-callback",
					error == -EAGAIN && !fixture.upper_done,
					-EAGAIN, error);
				ordered_record_terminal_failure(&fixture, generic_failure);
			}
			if (order != 1) {
				error = ordered_advance(&fixture);
				ORDERED_CHECK(&fixture, "terminal-drain-waits-lower-owner",
					error == -EAGAIN && !fixture.upper_done,
					-EAGAIN, error);
				ordered_data_callback(&fixture, data_error);
			}
			error = ordered_advance(&fixture);
			ORDERED_CHECK(&fixture, "terminal-final-owner",
				error == expected_ack &&
				fixture.upper_errno == expected_ack &&
				fixture.terminal_errno == expected_terminal &&
				fixture.original_lower_errno == data_error &&
				fixture.data_submissions == 1 &&
				fixture.data_completions == 1 &&
				fixture.upper_completions == 1 &&
				!fixture.flush_meter.attempts &&
				!fixture.lower.called &&
				!fixture.successful_acks &&
				!fixture.durable_publications &&
				fixture.generation == 7 &&
				fixture.authoritative_extent == 0x91U,
				expected_ack, error);
			error = ordered_advance(&fixture);
			ORDERED_CHECK(&fixture, "repeat-drain-after-terminal",
				error == expected_ack &&
				fixture.upper_completions == 1 &&
				fixture.data_completions == 1 &&
				!fixture.flush_meter.attempts,
				expected_ack, error);
			error = ordered_retry_after_failure(&fixture);
			ORDERED_CHECK(&fixture, "fresh-upper-after-terminal",
				error == expected_terminal &&
				fixture.retry_upper_completions == 1 &&
				fixture.upper_completions == 1 &&
				!fixture.flush_meter.attempts &&
				!fixture.lower.called,
				expected_terminal, error);
		}
	}
	return 0;
}

int main(void)
{
	int passed = 0;

	CHECK(test_completed_success() == 0); passed++;
	CHECK(test_synthetic_failure_before_lower() == 0); passed++;
	CHECK(test_genuine_lower_error() == 0); passed++;
	CHECK(test_unsupported_lower_flush_retains_errno() == 0); passed++;
	CHECK(test_null_argument_rejected() == 0); passed++;
	CHECK(test_prepublication_fua_write_gate() == 0); passed++;
	CHECK(test_no_ack_or_new_generation_before_fua() == 0); passed++;
	CHECK(test_callback_before_or_after_drain() == 0); passed++;
	CHECK(test_first_terminal_error_and_no_late_success() == 0); passed++;
	CHECK(test_ordered_preflush_data_fua_matrix() == 0); passed++;
	CHECK(test_preflush_barrier_owns_callback_precedence() == 0); passed++;
	CHECK(test_unsupported_fua_still_owns_terminal_ack() == 0); passed++;
	CHECK(test_terminal_failure_and_drain_cross_final_callback() == 0); passed++;
	printf("SWAPZ_FLUSH_ACCOUNTING_TESTS_PASS=%d\n", passed);
	return 0;
}
