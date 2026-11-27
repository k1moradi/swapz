/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef SWAPZ_NATIVE_OBSERVATION_CONTROLLER_H
#define SWAPZ_NATIVE_OBSERVATION_CONTROLLER_H

#ifndef SWAPZ_ROUND102_CONTROLLER_TEST
#error "Observation controller requires explicit development staging"
#endif
#include <linux/types.h>

/* Value-only ownership key; never embeds a target/table pointer. Zero
 * identity means no successful target-local installation. Routing snapshots
 * may be withdrawn without changing this key. */
struct swapz_trial_retained_scope {
	u64 identity, session, epoch, target_epoch, registration_epoch;
};

/* Exact identity stop only; no publication, activation, or join authority.
 * Sleepable; caller holds target lifecycle, not producer locks. */
int swapz_trial_controller_stop_capture(u64 identity);

#endif
