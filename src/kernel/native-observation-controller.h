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

#if defined(SWAPZ_ROUND104_INTEGRATION_TEST)
struct file;
struct swapz_mm_trial_scope;
struct swapz_trial_observation_scope;

/* Built-in private cold transaction, no exported positive control symbol.
 * Trusted caller must own the independent live mapper/table/target references
 * and serialize target lifecycle. Callback is synchronous, never retained.
 * No authorization or device activation is supplied by this API. */
typedef int (*swapz_trial_target_install)(void *context,
		const struct swapz_mm_trial_scope *scope, struct file *mapper_file,
		u64 registration_epoch);
int swapz_trial_controller_begin(const struct swapz_mm_trial_scope *scope,
		const struct swapz_trial_observation_scope *observation,
		struct file *mapper_file, size_t capacity,
		swapz_trial_target_install install, void *context);
/* Exact external witness only, not target debt, revoke or retirement. */
int swapz_trial_controller_join_external(const struct swapz_trial_retained_scope *retained);
/* Negative-only exact transitions. Caller has closed target admission and
 * joined map/provider/work before revoke; before finish it has also closed
 * storage/decoder and relinquished its target cap. No success on ESTALE. */
int swapz_trial_controller_revoke_joined(const struct swapz_trial_retained_scope *retained);
int swapz_trial_controller_finish(const struct swapz_trial_retained_scope *retained);
#endif

#endif
