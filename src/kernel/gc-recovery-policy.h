/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_GC_RECOVERY_POLICY_H
#define SWAPZ_GC_RECOVERY_POLICY_H

/*
 * A synchronous lower WRITE -EIO is retryable only while an authenticated GC
 * rotation owns the destination. The failed reservation stays quarantined;
 * the next ordered attempt resumes the same token and rescans current maps.
 * READ failures, non-GC writes and errors other than -EIO remain terminal.
 */
static inline int swapz_gc_recovery_retryable_lower_write_error(
	int recovery_active, int is_write, int is_eio)
{
	return recovery_active && is_write && is_eio;
}

/*
 * Once that retryable lower error propagates above GC, outer WRITE owners must
 * not poison the target again. The token must still be active and no terminal
 * target failure may have been elected while the error was unwinding.
 */
static inline int swapz_gc_recovery_retryable_propagated_write_error(
	int recovery_active, int target_failed, int is_eio)
{
	return !target_failed &&
	       swapz_gc_recovery_retryable_lower_write_error(
		       recovery_active, 1, is_eio);
}

#endif
