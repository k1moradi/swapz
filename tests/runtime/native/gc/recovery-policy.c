// SPDX-License-Identifier: GPL-2.0-only
/* Execute the same small GC lower-error policy included by the DM target. */
#include <stdio.h>
#include "gc-recovery-policy.h"

#define CHECK(x) do { if (!(x)) { \
	fprintf(stderr, "%s:%d failed %s\n", __FILE__, __LINE__, #x); \
	return 1; \
} } while (0)

int main(void)
{
	CHECK(swapz_gc_recovery_retryable_lower_write_error(1, 1, 1));
	CHECK(!swapz_gc_recovery_retryable_lower_write_error(0, 1, 1));
	CHECK(!swapz_gc_recovery_retryable_lower_write_error(1, 0, 1));
	CHECK(!swapz_gc_recovery_retryable_lower_write_error(1, 1, 0));
	puts("SWAPZ_GC_RECOVERY_POLICY_TESTS_PASS=4");
	return 0;
}
