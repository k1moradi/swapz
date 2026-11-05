// SPDX-License-Identifier: GPL-2.0-only
/* Execute the same small GC lower-error policy included by the DM target. */
#include <errno.h>
#include <stdio.h>
#include "gc-recovery-policy.h"

int main(void)
{
	static const int lower_errors[] = {
		-EIO, -ENOSPC, -EINVAL, -EUCLEAN,
		-EBADMSG, -EOVERFLOW, -EBUSY, 0
	};
	unsigned int recovery_active, is_write, error_index;
	unsigned int checked = 0;

	for (recovery_active = 0; recovery_active <= 1; ++recovery_active) {
		for (is_write = 0; is_write <= 1; ++is_write) {
			for (error_index = 0;
			     error_index < sizeof(lower_errors) / sizeof(lower_errors[0]);
			     ++error_index) {
				const int original_errno = lower_errors[error_index];
				const int is_eio = original_errno == -EIO;
				const int expected = recovery_active && is_write && is_eio;
				const int observed =
					swapz_gc_recovery_retryable_lower_write_error(
						recovery_active, is_write, is_eio);

				if (observed != expected) {
					fprintf(stderr,
						"GC_RECOVERY_POLICY_FAIL phase=lower_io_classification "
						"recovery=%u is_write=%u original_errno=%d "
						"expected_retry=%d observed_retry=%d\n",
						recovery_active, is_write, original_errno,
						expected, observed);
					return 1;
				}
				checked++;
			}
		}
	}
	printf("SWAPZ_GC_RECOVERY_POLICY_TESTS_PASS=%u\n", checked);
	return 0;
}
