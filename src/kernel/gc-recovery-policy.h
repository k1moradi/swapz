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

#endif
