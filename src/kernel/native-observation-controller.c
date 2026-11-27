/* SPDX-License-Identifier: GPL-2.0-only */
#include "native-observation-controller.h"
#include <linux/bio.h>
#include <linux/blkdev.h>
#include <linux/errno.h>
#include <linux/export.h>
#include <linux/swapz_mm_carrier.h>

#if defined(MODULE) || !defined(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) || !defined(SWAPZ_ROUND098_SCOPED_PRODUCER_TEST)
#error "Controller stop requires built-in staged MM"
#endif

/* Only a one-shot negative control operation crosses the module boundary.
 * No caller assertion may publish scope, revoke retained observation, or
 * certify retirement. The MM API validates the exact identity itself. */
int swapz_trial_controller_stop_capture(u64 identity)
{
	int error;

	if (!identity)
		return -EINVAL;
	error = swapz_mm_trial_scope_stop_capture(identity);
	return error == -EALREADY ? 0 : error;
}
EXPORT_SYMBOL_GPL(swapz_trial_controller_stop_capture);
