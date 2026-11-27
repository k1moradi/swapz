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
struct module;
struct dm_target;
struct swapz_mm_trial_scope;
struct swapz_trial_observation_scope;

/* Built-in private cold transaction, no exported positive control symbol.
 * Trusted caller must own the independent live mapper/table/target references
 * and serialize target lifecycle. Callback is synchronous, never retained.
 * No authorization or device activation is supplied by this API. */
typedef int (*swapz_trial_target_install)(void *context,
		const struct swapz_mm_trial_scope *scope, struct file *mapper_file,
		u64 registration_epoch);
/* A single module-lifetime registration, never a target pointer or module
 * self-pin. Withdrawal synchronously fences calls. The positive built-in
 * entry requires independent live table/target refs and lifecycle exclusion;
 * registration alone grants no admission. No userspace caller is supplied.
 */
struct swapz_trial_target_ops {
	struct module *owner;
	/* Read-only local preflight before recorder/MM publication. */
	swapz_trial_target_install validate;
	swapz_trial_target_install install;
	int (*retire)(void *context, const struct swapz_trial_retained_scope *retained);
};
int swapz_trial_target_register(const struct swapz_trial_target_ops *ops);
int swapz_trial_target_unregister(const struct swapz_trial_target_ops *ops);
int swapz_trial_controller_begin_registered(const struct swapz_mm_trial_scope *scope,
		const struct swapz_trial_observation_scope *observation,
		struct file *mapper_file, size_t capacity, struct dm_target *target);
/* Only for an independently retained, already drained final table, before
 * destruction can be blocked by the retained mapper file. Not normal suspend.
 */
int swapz_trial_controller_retire_registered(struct dm_target *target,
		const struct swapz_trial_retained_scope *retained);
/* Exact post-publication failed install only; no target was installed.
 * Independent actual MM join and old-owner retirement remain required.
 * Ambiguous/failed MM publication is not recoverable by this entry.
 */
int swapz_trial_controller_recover_uninstalled(const struct swapz_trial_retained_scope *retained);
/* Exact external witness only, not target debt, revoke or retirement. */
int swapz_trial_controller_join_external(const struct swapz_trial_retained_scope *retained);
/* Negative-only exact transitions. Caller has closed target admission and
 * joined map/provider/work before revoke; before finish it has also closed
 * storage/decoder and relinquished its target cap. No success on ESTALE. */
int swapz_trial_controller_revoke_joined(const struct swapz_trial_retained_scope *retained);
int swapz_trial_controller_finish(const struct swapz_trial_retained_scope *retained);
#endif

#endif
