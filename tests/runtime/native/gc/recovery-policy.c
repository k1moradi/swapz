// SPDX-License-Identifier: GPL-2.0-only
/* Execute the same small GC lower-error policy included by the DM target. */
#include <stdio.h>
#include "gc-recovery-policy.h"

struct recovery_policy_case {
	int recovery_active;
	int is_write;
	int is_eio;
	int expected_retry;
};

struct propagated_write_policy_case {
	int recovery_active;
	int target_failed;
	int is_eio;
	int expected_retry;
};

int main(void)
{
	static const struct recovery_policy_case cases[] = {
		{ 0, 0, 0, 0 },
		{ 0, 0, 1, 0 },
		{ 0, 1, 0, 0 },
		{ 0, 1, 1, 0 },
		{ 1, 0, 0, 0 },
		{ 1, 0, 1, 0 },
		{ 1, 1, 0, 0 },
		{ 1, 1, 1, 1 },
	};
	static const struct propagated_write_policy_case propagated_cases[] = {
		{ 0, 0, 0, 0 },
		{ 0, 0, 1, 0 },
		{ 1, 0, 0, 0 },
		{ 1, 0, 1, 1 },
		{ 0, 1, 1, 0 },
		{ 1, 1, 1, 0 },
	};
	unsigned int index;

	for (index = 0; index < sizeof(cases) / sizeof(cases[0]); ++index) {
		const struct recovery_policy_case *test_case = &cases[index];
		const int observed_retry =
			swapz_gc_recovery_retryable_lower_write_error(
				test_case->recovery_active,
				test_case->is_write,
				test_case->is_eio);

		if (observed_retry != test_case->expected_retry) {
			fprintf(stderr,
				"GC_RECOVERY_POLICY_FAIL phase=lower_io_classification "
				"recovery=%d is_write=%d is_eio=%d "
				"expected_retry=%d observed_retry=%d\n",
				test_case->recovery_active, test_case->is_write,
				test_case->is_eio, test_case->expected_retry,
				observed_retry);
			return 1;
		}
	}
	for (index = 0;
	     index < sizeof(propagated_cases) / sizeof(propagated_cases[0]);
	     ++index) {
		const struct propagated_write_policy_case *test_case =
			&propagated_cases[index];
		const int observed_retry =
			swapz_gc_recovery_retryable_propagated_write_error(
				test_case->recovery_active,
				test_case->target_failed,
				test_case->is_eio);

		if (observed_retry != test_case->expected_retry) {
			fprintf(stderr,
				"GC_RECOVERY_POLICY_FAIL phase=propagated_write_classification "
				"recovery=%d target_failed=%d is_eio=%d "
				"expected_retry=%d observed_retry=%d\n",
				test_case->recovery_active, test_case->target_failed,
				test_case->is_eio, test_case->expected_retry,
				observed_retry);
			return 1;
		}
	}
	printf("SWAPZ_GC_RECOVERY_POLICY_TESTS_PASS=%zu\n",
	       sizeof(cases) / sizeof(cases[0]) +
	       sizeof(propagated_cases) / sizeof(propagated_cases[0]));
	return 0;
}
