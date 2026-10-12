/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_V3_FLUSH_QUAL_H
#define SWAPZ_V3_FLUSH_QUAL_H

#ifdef __KERNEL__
#include <linux/errno.h>
#else
#include <errno.h>
#endif

/*
 * Synchronous lower-cache-flush completion accounting. This is not a
 * measure of hardware NAND operations: blkdev_issue_flush may complete
 * without sending a command on a queue without a write-back cache.
 *
 * fail_nth is a STRICTLY null_blk-only alpha fault-injection knob. A
 * synthetic -EIO is returned *before* invoking lower_flush; no successful
 * lower completion is fabricated, and the caller MUST fail the target
 * closed. Injection tests the upper propagation/ordering path; it does
 * not substitute for an independent device-originated flush failure.
 */
struct sv3_flush_meter {
	unsigned long long attempts;
	unsigned long long successes;
	unsigned long long failures;
	unsigned long long injected;
	unsigned int fail_nth;
};

static inline int sv3_flush_accounted(struct sv3_flush_meter *meter,
				     int (*lower_flush)(void *), void *opaque)
{
	int error;

	if (!meter || !lower_flush)
		return -EINVAL;
	++meter->attempts;
	if (meter->fail_nth && meter->attempts == meter->fail_nth) {
		++meter->injected;
		error = -EIO;
	} else {
		error = lower_flush(opaque);
	}
	if (error)
		++meter->failures;
	else
		++meter->successes;
	return error;
}

#endif
