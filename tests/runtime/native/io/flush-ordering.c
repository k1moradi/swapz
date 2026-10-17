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
#include "flush-qual.h"
#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)
struct fake_lower {
	unsigned int called;
	int next_error;
};
static int lower_flush(void *p)
{
	struct fake_lower *ctx = p;

	ctx->called++;
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
static int test_null_argument_rejected(void)
{
	struct swapz_flush_meter s = { 0 };

	CHECK(swapz_flush_accounted(NULL, lower_flush, NULL) == -EINVAL);
	CHECK(swapz_flush_accounted(&s, NULL, NULL) == -EINVAL);
	CHECK(s.attempts == 0 && !s.successes && !s.failures);
	return 0;
}
int main(void)
{
	int passed = 0;

	CHECK(test_completed_success() == 0); passed++;
	CHECK(test_synthetic_failure_before_lower() == 0); passed++;
	CHECK(test_genuine_lower_error() == 0); passed++;
	CHECK(test_null_argument_rejected() == 0); passed++;
	printf("SWAPZ_FLUSH_ACCOUNTING_TESTS_PASS=%d\n", passed);
	return 0;
}
