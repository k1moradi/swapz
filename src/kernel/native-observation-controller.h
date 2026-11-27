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
struct swapz_observation_record;
struct swapz_ticket_broker;

/* Read-only route snapshot: no authority, pointer, reference or grant.
 * Caller independently owns the live target/table, opened mapper, optional
 * expected broker identity and lifecycle exclusion throughout the query.
 * A later install must independently revalidate every identity. */
struct swapz_trial_target_preflight {
	u64 session, table_epoch, target_epoch, registration_epoch;
	sector_t first_sector, sector_count;
};

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
	int (*query)(void *context, struct file *mapper_file,
		const struct swapz_ticket_broker *expected_broker,
		sector_t first_sector, sector_t sector_count,
		struct swapz_trial_target_preflight *result);
	swapz_trial_target_install validate;
	swapz_trial_target_install install;
	/* Both callbacks run synchronously under the registry and live-table
	 * lifetime. Preflight is read-only; final retirement transfers the
	 * target's counted mapper reference to the unlocked caller. */
	int (*validate_retire)(void *context, const struct swapz_trial_retained_scope *retained);
	int (*retire)(void *context, const struct swapz_trial_retained_scope *retained,
		      struct file **released_mapper);
};
int swapz_trial_target_register(const struct swapz_trial_target_ops *ops);
int swapz_trial_target_unregister(const struct swapz_trial_target_ops *ops);
/* Private built-in cold query; clears non-NULL output on any failure.
 * No caller is installed and neither query nor registration grants admission. */
int swapz_trial_controller_query_registered(struct dm_target *target,
		struct file *mapper_file,
		const struct swapz_ticket_broker *expected_broker,
		sector_t first_sector, sector_t sector_count,
		struct swapz_trial_target_preflight *result);
int swapz_trial_controller_begin_registered(const struct swapz_mm_trial_scope *scope,
		const struct swapz_trial_observation_scope *observation,
		struct file *mapper_file, size_t capacity, struct dm_target *target);
/* Only for an independently retained, already drained final table, before
 * destruction can be blocked by the retained mapper file. Not normal suspend.
 * Must enter without controller, target or DM locks that conflict with file
 * release; the caller independently fences the live table and lifecycle.
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
/* Only the registered target's actual terminal census is accepted; NULL
 * denotes an uninstalled or incomplete witness, never a clean trace. */
int swapz_trial_controller_finish(const struct swapz_trial_retained_scope *retained,
		const struct swapz_observation_record *terminal);
#endif

#endif
