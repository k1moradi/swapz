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

#if defined(SWAPZ_ROUND104_INTEGRATION_TEST)
#ifndef SWAPZ_ROUND103_EXTERNAL_JOIN_TEST
#error "Cold controller requires exact staged external join"
#endif
#include "native-observation-owner.h"
#include "native-observation-integration.h"
#include "zswap-original-ticket.h"
#include <linux/file.h>
#include <linux/fs.h>
#include <linux/mutex.h>
#include <linux/module.h>

/* Built-in lifetime, serialized control, one shot. No retained callback,
 * target/module/table pointer or caller-owned scope pointer. After recorder
 * publication a failed startup is retained; an absent or failed external
 * witness is never evidence that rollback is safe. */
static DEFINE_MUTEX(swapz_controller_lock);
static struct swapz_mm_trial_scope swapz_controller_scope;
static struct file *swapz_controller_mapper;
static u64 swapz_controller_registration;
static bool swapz_controller_used, swapz_controller_published;
static bool swapz_controller_installed;
static bool swapz_controller_external_joined, swapz_controller_mm_revoked;
static bool swapz_controller_detaching, swapz_controller_files_detached;
static bool swapz_controller_broker_retired, swapz_controller_finished;
static bool swapz_controller_registered_retiring;
static struct swapz_mm_trial_terminal_snapshot swapz_controller_mm_terminal;
static int swapz_controller_first_error;

static int swapz_trial_controller_begin(const struct swapz_mm_trial_scope *scope,
		const struct swapz_trial_observation_scope *observation,
		struct file *mapper_file, size_t capacity,
		swapz_trial_target_install install, void *context)
{
	struct swapz_mm_trial_scope selected;
	struct file *area_file = NULL;
	u32 type;
	u64 epoch;
	int error;

	if (!scope || !observation || !mapper_file || !install ||
	    !scope->identity || !scope->broker || !scope->session ||
	    !scope->table_epoch || !scope->target_epoch || !scope->bdev ||
	    !S_ISBLK(file_inode(mapper_file)->i_mode) ||
	    file_bdev(mapper_file) != scope->bdev || bdev_is_partition(scope->bdev) ||
	    !scope->first_sector || scope->first_sector % 8 ||
	    !scope->sector_count || scope->sector_count % 8 ||
	    scope->sector_count > 16 * 8 ||
	    scope->first_sector > bdev_nr_sectors(scope->bdev) ||
	    scope->sector_count > bdev_nr_sectors(scope->bdev) - scope->first_sector ||
	    scope->session != observation->session ||
	    scope->table_epoch != observation->epoch ||
	    scope->target_epoch != observation->target_epoch ||
	    !observation->registration_epoch ||
	    scope->first_sector / 8 != observation->first_logical ||
	    scope->sector_count / 8 != observation->page_count ||
	    !capacity || capacity > SWAPZ_OBSERVATION_MAX_RECORDS)
		return -EINVAL;
	selected = *scope;
	mutex_lock(&swapz_controller_lock);
	if (swapz_controller_used) {
		error = -EALREADY;
		goto unlock;
	}
	error = swapz_mm_trial_area_get(mapper_file, selected.first_sector,
		selected.sector_count, &type, &epoch, &area_file);
	if (error)
		goto unlock;
	if (selected.swap_type != type || selected.area_epoch != epoch) {
		error = -ESTALE;
		goto put_area;
	}
	/* No MM capture can precede byte-gate bind. MM publish independently
	 * revalidates and retains the actual area and mapper references. */
	if (!swapz_trial_observation_start(observation, capacity)) {
		error = -EBUSY;
		goto put_area;
	}
	swapz_controller_used = true;
	swapz_controller_scope = selected;
	swapz_controller_registration = observation->registration_epoch;
	get_file(mapper_file);
	swapz_controller_mapper = mapper_file;
	if (!swapz_trial_byte_bind_scope(selected.identity, type, epoch)) {
		error = -EIO;
		goto retain;
	}
	error = swapz_mm_trial_scope_publish(&selected, mapper_file);
	if (error)
		goto retain;
	swapz_controller_published = true;
	if (!swapz_mm_trial_scope_matches_exact(&selected, mapper_file)) {
		error = -ESTALE;
		goto retain;
	}
	error = install(context, &selected, mapper_file, observation->registration_epoch);
	if (!error) {
		swapz_controller_installed = true;
		goto put_area;
	}
retain:
	if (!swapz_controller_first_error)
		swapz_controller_first_error = error;
	swapz_trial_byte_invalidate();
	(void)swapz_trial_observation_append(NULL);
	if (swapz_controller_published)
		(void)swapz_trial_controller_stop_capture(selected.identity);
	/* A failed publish can itself retain MM debt. No forced revoke or
	 * recorder free; retain the exact identity and counted mapper. */
put_area:
unlock:
	mutex_unlock(&swapz_controller_lock);
	if (area_file)
		fput(area_file);
	return error;
}

/* Registration is distinct from the controller's one-shot lock. Only the
 * synchronous rendezvous takes both, registration -> controller. The caller
 * already owns the live table and lifecycle, not any controller/target spinlock.
 * No table/target/file is kept by the registry; a module ref lasts only across
 * each callback. Registration cannot start a scope.
 */
static DEFINE_MUTEX(swapz_target_ops_lock);
static const struct swapz_trial_target_ops *swapz_target_ops;

int swapz_trial_target_register(const struct swapz_trial_target_ops *ops)
{
	int error = -EBUSY;

	if (!ops || !ops->validate || !ops->install || !ops->validate_retire || !ops->retire)
		return -EINVAL;
	mutex_lock(&swapz_target_ops_lock);
	if (!swapz_target_ops) {
		swapz_target_ops = ops;
		error = 0;
	}
	mutex_unlock(&swapz_target_ops_lock);
	return error;
}
EXPORT_SYMBOL_GPL(swapz_trial_target_register);

int swapz_trial_target_unregister(const struct swapz_trial_target_ops *ops)
{
	int error = -ESTALE;

	mutex_lock(&swapz_target_ops_lock);
	if (ops && swapz_target_ops == ops) {
		swapz_target_ops = NULL;
		error = 0;
	}
	mutex_unlock(&swapz_target_ops_lock);
	return error;
}
EXPORT_SYMBOL_GPL(swapz_trial_target_unregister);

/* Private built-in rendezvous; no exported positive entry. The original
 * caller still must acquire independent admission and live target/table refs.
 */
int swapz_trial_controller_begin_registered(const struct swapz_mm_trial_scope *scope,
		const struct swapz_trial_observation_scope *observation,
		struct file *mapper_file, size_t capacity, struct dm_target *target)
{
	const struct swapz_trial_target_ops *ops;
	struct module *owner = NULL;
	int error = -ENODEV;

	if (!target || !scope || !observation || !mapper_file)
		return -EINVAL;
	mutex_lock(&swapz_target_ops_lock);
	ops = swapz_target_ops;
	if (ops && try_module_get(ops->owner)) {
		owner = ops->owner;
		error = ops->validate(target, scope, mapper_file,
				observation->registration_epoch);
		if (!error)
			error = swapz_trial_controller_begin(scope, observation, mapper_file,
					capacity, ops->install, target);
	}
	mutex_unlock(&swapz_target_ops_lock);
	if (owner)
		module_put(owner);
	return error;
}

static int swapz_controller_detach(const struct swapz_trial_retained_scope *retained);

int swapz_trial_controller_retire_registered(struct dm_target *target,
		const struct swapz_trial_retained_scope *retained)
{
	const struct swapz_trial_target_ops *ops;
	struct module *owner = NULL;
	struct file *released_mapper = NULL;
	int error = -ENODEV;

	if (!target || !retained || !retained->identity)
		return -EINVAL;
	mutex_lock(&swapz_target_ops_lock);
	ops = swapz_target_ops;
	if (ops && try_module_get(ops->owner)) {
		owner = ops->owner;
		error = ops->validate_retire(target, retained);
	}
	mutex_unlock(&swapz_target_ops_lock);
	/* The caller keeps the actual table alive and lifecycle fenced.
	 * Never run MM file detachment or either fput under registry/control
	 * locks. The transient module reference spans both callbacks. */
	if (!error)
		error = swapz_controller_detach(retained);
	if (!error) {
		mutex_lock(&swapz_target_ops_lock);
		if (swapz_target_ops == ops) {
			mutex_lock(&swapz_controller_lock);
			swapz_controller_registered_retiring = true;
			mutex_unlock(&swapz_controller_lock);
			error = ops->retire(target, retained, &released_mapper);
			mutex_lock(&swapz_controller_lock);
			swapz_controller_registered_retiring = false;
			mutex_unlock(&swapz_controller_lock);
		} else {
			error = -ESTALE;
		}
		mutex_unlock(&swapz_target_ops_lock);
	}
	if (released_mapper)
		fput(released_mapper);
	if (owner)
		module_put(owner);
	return error;
}

/* All control callers hold the same cold serialization lock. No caller
 * boolean can substitute for the actual MM/core and old-owner witnesses. */
static bool swapz_controller_matches_locked(const struct swapz_trial_retained_scope *retained)
{
	lockdep_assert_held(&swapz_controller_lock);
	return retained && retained->identity && swapz_controller_published &&
	       (swapz_controller_mapper || swapz_controller_files_detached ||
		swapz_controller_detaching) &&
	       retained->identity == swapz_controller_scope.identity &&
	       retained->session == swapz_controller_scope.session &&
	       retained->epoch == swapz_controller_scope.table_epoch &&
	       retained->target_epoch == swapz_controller_scope.target_epoch &&
	       retained->registration_epoch == swapz_controller_registration;
}

static void swapz_controller_record_error(int error)
{
	lockdep_assert_held(&swapz_controller_lock);
	if (error && error != -EBUSY) {
		if (!swapz_controller_first_error)
			swapz_controller_first_error = error;
		swapz_trial_byte_invalidate();
		(void)swapz_trial_observation_append(NULL);
	}
}

/* Exact MM witness is sampled before revoke destroys the retained key.
 * The MM gate counts tickets, not owner pointers, including detached callbacks. */
static int swapz_controller_snapshot_locked(const struct swapz_trial_retained_scope *retained,
		struct swapz_mm_trial_terminal_snapshot *snapshot)
{
	int error;

	lockdep_assert_held(&swapz_controller_lock);
	error = swapz_mm_trial_scope_terminal_snapshot(retained->identity,
		retained->session, retained->epoch, retained->target_epoch, snapshot);
	if (error)
		return error;
	if (snapshot->area_epoch != swapz_controller_scope.area_epoch)
		return -ESTALE;
	if (snapshot->fault)
		return -EUCLEAN;
	if (!snapshot->capture_stopped || !snapshot->area_retired ||
	    !snapshot->terminal_closed || !snapshot->terminal_joined ||
	    snapshot->carrier_busy || snapshot->mm_callbacks ||
	    snapshot->dm_callbacks || snapshot->dm_entrants)
		return -EBUSY;
	return 0;
}

static int swapz_controller_join_locked(const struct swapz_trial_retained_scope *retained)
{
	struct swapz_mm_trial_terminal_snapshot snapshot;
	int error;

	lockdep_assert_held(&swapz_controller_lock);
	if (!swapz_controller_matches_locked(retained))
		return -ESTALE;
	if (swapz_controller_detaching)
		return -EBUSY;
	if (swapz_controller_external_joined)
		return 0;
	error = swapz_trial_controller_stop_capture(retained->identity);
	if (!error)
		error = swapz_mm_trial_scope_join_external(retained->identity,
			retained->session, retained->epoch, retained->target_epoch);
	if (!error)
		error = swapz_controller_snapshot_locked(retained, &snapshot);
	if (!error) {
		swapz_controller_mm_terminal = snapshot;
		swapz_controller_external_joined = true;
	}
	return error;
}

/* Only the registered final-retirement path (or exact uninstalled recovery)
 * enters here. Keep the scalar key while dropping independent open files.
 * No target/DM lock may be held by the caller; fput is relinquishment, not
 * a synchronous device-close or table-destruction witness. */
static int swapz_controller_detach(const struct swapz_trial_retained_scope *retained)
{
	struct swapz_mm_trial_terminal_snapshot snapshot;
	struct file *mapper = NULL;
	int error;

	mutex_lock(&swapz_controller_lock);
	error = swapz_controller_join_locked(retained);
	if (error || swapz_controller_files_detached)
		goto unlock;
	swapz_controller_detaching = true;
	mutex_unlock(&swapz_controller_lock);

	error = swapz_mm_trial_scope_detach_files(retained->identity,
		retained->session, retained->epoch, retained->target_epoch);

	mutex_lock(&swapz_controller_lock);
	if (!error)
		error = swapz_controller_snapshot_locked(retained, &snapshot);
	if (!error && !snapshot.files_detached)
		error = -EUCLEAN;
	if (!error) {
		swapz_controller_mm_terminal = snapshot;
		mapper = swapz_controller_mapper;
		swapz_controller_mapper = NULL;
		swapz_controller_scope.bdev = NULL;
	}
	mutex_unlock(&swapz_controller_lock);
	if (mapper)
		fput(mapper);
	mutex_lock(&swapz_controller_lock);
	if (!error)
		swapz_controller_files_detached = true;
	swapz_controller_detaching = false;
unlock:
	swapz_controller_record_error(error);
	mutex_unlock(&swapz_controller_lock);
	return error;
}

/* Genuine external MM/core witness only; no target or broker debt proof. */
int swapz_trial_controller_join_external(const struct swapz_trial_retained_scope *retained)
{
	int error;

	mutex_lock(&swapz_controller_lock);
	error = swapz_controller_join_locked(retained);
	swapz_controller_record_error(error);
	mutex_unlock(&swapz_controller_lock);
	return error;
}

/* Actual target drain calls this only after local ingress/provider/worker/
 * candidate and lower joins. MM independently proves retired area and
 * terminal completion. Keep the recorder available for all terminal events.
 * This negative-only interface never starts or reopens a scope. */
int swapz_trial_controller_revoke_joined(const struct swapz_trial_retained_scope *retained)
{
	int error;

	mutex_lock(&swapz_controller_lock);
	error = swapz_controller_join_locked(retained);
	if (!error && !swapz_controller_files_detached)
		error = -EBUSY;
	if (!error && !swapz_controller_mm_revoked) {
		error = swapz_mm_trial_scope_revoke(retained->identity);
		if (!error) {
			swapz_controller_mm_revoked = true;
			swapz_controller_scope.broker = NULL;
		}
	}
	swapz_controller_record_error(error);
	mutex_unlock(&swapz_controller_lock);
	return error;
}
EXPORT_SYMBOL_GPL(swapz_trial_controller_revoke_joined);

/* Called by the recorder stop owner synchronously under both cold locks;
 * do not acquire either lock again. The exact old-owner witness was joined
 * before the terminal record; it cannot be replaced by a caller assertion. */
static bool swapz_controller_recorder_join(void *context)
{
	const struct swapz_trial_retained_scope *retained = context;

	lockdep_assert_held(&swapz_controller_lock);
	return swapz_controller_matches_locked(retained) &&
	       swapz_controller_external_joined && swapz_controller_files_detached &&
	       swapz_controller_mm_revoked && swapz_controller_broker_retired;
}

int swapz_trial_controller_finish(const struct swapz_trial_retained_scope *retained,
		const struct swapz_observation_record *terminal)
{
	struct swapz_observation_record cleanup;
	u64 sequence;
	int error = -ESTALE;

	mutex_lock(&swapz_controller_lock);
	if (!swapz_controller_matches_locked(retained) ||
	    (swapz_controller_installed && !swapz_controller_registered_retiring))
		goto unlock;
	if (swapz_controller_finished) {
		error = 0;
		goto unlock;
	}
	error = -EBUSY;
	if (!swapz_controller_external_joined || !swapz_controller_files_detached ||
	    !swapz_controller_mm_revoked || swapz_controller_detaching)
		goto unlock;
	error = swapz_mm_broker_owner_retired(retained->session, retained->epoch);
	if (error)
		goto unlock;
	swapz_controller_broker_retired = true;
	/* The actual target terminal census is produced only after its drain,
	 * final authority retirement and storage/cap teardown. MM's preserved
	 * exact snapshot and the old broker witness independently prove their
	 * respective debts. Do not publish flags7 on an incomplete witness. */
	if (swapz_controller_installed && terminal &&
	    terminal->event == SWAPZ_OBS_CLEANUP && !terminal->flags &&
	    !terminal->caps && !terminal->tickets && !terminal->pins &&
	    !terminal->reservations && !terminal->bios && !terminal->maps &&
	    !terminal->quarantines && !swapz_controller_first_error &&
	    swapz_controller_mm_terminal.files_detached) {
		/* Copy only the proven census, not arbitrary caller wire fields. */
		cleanup = (struct swapz_observation_record){
			.event = SWAPZ_OBS_CLEANUP, .flags = 7,
			.caps = terminal->caps, .tickets = terminal->tickets,
			.pins = terminal->pins, .reservations = terminal->reservations,
			.bios = terminal->bios, .maps = terminal->maps,
			.quarantines = terminal->quarantines,
		};
		sequence = swapz_trial_observation_append_sequence(&cleanup);
		if (!sequence || !swapz_trial_byte_event(&cleanup, sequence, NULL, 0))
			swapz_controller_record_error(-EUCLEAN);
	} else {
		swapz_controller_record_error(-EUCLEAN);
	}
	/* Evidence loss does not retain otherwise genuinely retired target
	 * ownership. Once attempted, never append CLEANUP again, even if
	 * the recorder cannot seal its incomplete transport. */
	if (!swapz_trial_observation_stop(swapz_controller_recorder_join, (void *)retained))
		swapz_controller_record_error(-EUCLEAN);
	swapz_controller_finished = true;
	error = 0;
unlock:
	swapz_controller_record_error(error);
	mutex_unlock(&swapz_controller_lock);
	return error;
}
EXPORT_SYMBOL_GPL(swapz_trial_controller_finish);

/* Recovery of the precisely known failed target installation. No target
 * pointer is retained and a successful install can never use this path.
 * A failed/ambiguous MM publish is deliberately left retained. */
int swapz_trial_controller_recover_uninstalled(const struct swapz_trial_retained_scope *retained)
{
	int error = -ESTALE;

	mutex_lock(&swapz_controller_lock);
	if (!swapz_controller_installed && swapz_controller_matches_locked(retained))
		error = 0;
	swapz_controller_record_error(error);
	mutex_unlock(&swapz_controller_lock);
	if (!error)
		error = swapz_controller_detach(retained);
	if (!error)
		error = swapz_trial_controller_revoke_joined(retained);
	/* No target was installed. Its independently closed old owner, not
	 * this failed startup, must prove that all target cap debt is gone. */
	return error ? error : swapz_trial_controller_finish(retained, NULL);
}
#endif
