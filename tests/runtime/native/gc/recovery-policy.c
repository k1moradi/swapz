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
	printf("SWAPZ_GC_RECOVERY_POLICY_TESTS_PASS=%zu\n",
	       sizeof(cases) / sizeof(cases[0]));
	return 0;
}
