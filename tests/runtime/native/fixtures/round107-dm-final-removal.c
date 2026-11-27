/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged DM functions. The owner, locks, table/holder lifetimes,
 * deferred fput and controller callback are deterministic host substitutes.
 * No positive admission, runtime device or native concurrency is modeled. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef uint64_t u64;
typedef unsigned blk_mode_t;
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define DMF_BLOCK_IO_FOR_SUSPEND 0
#define DMF_SUSPENDED 1
#define DMF_FREEING 3
#define DMF_DELETING 4
#define DMF_DEFERRED_REMOVE 6
#define DMF_SUSPENDED_INTERNALLY 7
#define DMF_POST_SUSPENDING 8
#define SINGLE_DEPTH_NESTING 1
#define TASK_INTERRUPTIBLE 1
#define MINOR_ALLOCED ((void *)-1)
#define ERR_PTR(error) ((struct dm_table *)(intptr_t)(error))
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R107_A11_FIRST_ERROR line=%d %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)

static unsigned checks, spinlocks, mutexes, gets, puts_count, srcu_gets, srcu_puts;
static unsigned callbacks, dtrs, frees, warnings, resumes, binds, dead_marks;
static int _minor_lock, _minor_idr;
struct swapz_trial_retained_scope { u64 identity, session, epoch, target_epoch, registration_epoch; };
struct mapped_device;
struct dm_table;
struct target_type { const char *name; };
struct dm_target { struct dm_table *table; struct target_type *type; };
struct dm_table {
	struct mapped_device *md;
	unsigned num_targets;
	struct dm_target *target;
};
struct gendisk { struct mapped_device *private_data; };
struct queue_limits { unsigned dummy; };
struct request_queue { struct queue_limits limits; };
struct mapped_device {
	int suspend_lock, deferred_lock, holders, open_count;
	unsigned long flags;
	struct dm_table *map;
	struct gendisk *disk;
	struct request_queue *queue;
	void *immutable_target, *requeue_list;
	bool deferred, inflight, request_based;
	unsigned srcu;
};
static struct mapped_device selected, other;
static struct dm_table live, replacement, foreign;
static struct dm_target target, replacement_target, foreign_target;
static struct target_type swapz_type = {"swapz"}, wrong_type = {"linear"};
static struct request_queue queue, other_queue;
static struct gendisk disk, other_disk;
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
static const struct swapz_trial_retained_scope exact = {17, 11, 12, 13, 19};
static int callback_error;
static void (*callback_hook)(void);
#endif

static void spin_lock(int *lock)
{
	CHECK(!*lock);
	if (lock == &_minor_lock)
		CHECK(!spinlocks);
	*lock = 1;
	++spinlocks;
}
static void spin_unlock(int *lock)
{
	CHECK(*lock && spinlocks);
	*lock = 0;
	--spinlocks;
}
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; spin_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); spin_unlock(lock); } while (0)
static void mutex_lock(int *lock)
{
	CHECK(!*lock && !spinlocks);
	*lock = 1;
	++mutexes;
}
static void mutex_unlock(int *lock)
{
	CHECK(*lock && mutexes && !spinlocks);
	*lock = 0;
	--mutexes;
}
#define mutex_lock_nested(lock, nesting) do { (void)(nesting); mutex_lock(lock); } while (0)
#define lockdep_assert_held(lock) CHECK(*(lock))
#define lockdep_assert_not_held(lock) CHECK(!*(lock))
#define lockdep_is_held(lock) (*(lock))
#define rcu_dereference_protected(pointer, held) ((void)(held), (pointer))
static __attribute__((unused)) bool warn_once(bool condition) { if (condition) ++warnings; return condition; }
#define WARN_ON_ONCE(condition) warn_once(condition)
static bool test_bit(unsigned bit, const unsigned long *flags) { return (*flags >> bit) & 1U; }
static void set_bit(unsigned bit, unsigned long *flags) { *flags |= 1UL << bit; }
static void clear_bit(unsigned bit, unsigned long *flags) { *flags &= ~(1UL << bit); }
static int atomic_read(const int *value) { return *value; }
static void atomic_inc(int *value) { ++*value; }
static __attribute__((unused)) bool bio_list_empty(const bool *list) { return !*list; }
static bool dm_suspended_md(struct mapped_device *md) { return test_bit(DMF_SUSPENDED, &md->flags); }
static bool dm_suspended_internally_md(struct mapped_device *md) { return test_bit(DMF_SUSPENDED_INTERNALLY, &md->flags); }
static bool dm_deleting_md(struct mapped_device *md) { return test_bit(DMF_DELETING, &md->flags); }
static bool dm_request_based(struct mapped_device *md) { return md->request_based; }
static __attribute__((unused)) bool dm_in_flight_bios(struct mapped_device *md) { CHECK(md->suspend_lock); return md->inflight; }
static int dm_open_count(struct mapped_device *md) { CHECK(_minor_lock); return md->open_count; }
static void dm_get(struct mapped_device *md) { CHECK(_minor_lock && !test_bit(DMF_FREEING, &md->flags)); ++md->holders; if (md == &selected) ++gets; }
static __attribute__((unused)) void dm_put(struct mapped_device *md) { CHECK(!spinlocks && !mutexes && md->holders > 0 && !md->srcu); --md->holders; ++puts_count; }
static struct dm_table *dm_get_live_table(struct mapped_device *md, int *index)
{
	CHECK(md->suspend_lock);
	*index = 1;
	++md->srcu;
	++srcu_gets;
	return md->map;
}
static void dm_put_live_table(struct mapped_device *md, int index)
{
	CHECK(index == 1 && md->srcu && !spinlocks);
	--md->srcu;
	++srcu_puts;
}
static __attribute__((unused)) struct mapped_device *dm_table_get_md(struct dm_table *table) { return table->md; }
static __attribute__((unused)) struct dm_target *dm_table_get_target(struct dm_table *table, unsigned index)
{
	CHECK(index == 0 && table->num_targets == 1);
	return table->target;
}
static unsigned dm_table_get_size(struct dm_table *table) { return table ? 128 : 0; }
static bool __noflush_suspending(struct mapped_device *md) { (void)md; return false; }
static bool dm_table_has_no_data_devices(struct dm_table *table) { (void)table; return false; }
static struct dm_table *dm_get_live_table_fast(struct mapped_device *md) { return md->map; }
static void dm_put_live_table_fast(struct mapped_device *md) { (void)md; }
static int dm_calculate_queue_limits(struct dm_table *table, struct queue_limits *limits)
{
	CHECK(table);
	limits->dummy = 0;
	return 0;
}
static struct dm_table *__bind(struct mapped_device *md, struct dm_table *table, struct queue_limits *limits)
{
	struct dm_table *old = md->map;
	(void)limits;
	CHECK(md->suspend_lock && !md->srcu);
	++binds;
	md->map = table;
	return old;
}
static void dm_issue_global_event(void) {}
static int wait_on_bit(unsigned long *flags, unsigned bit, int task)
{
	(void)flags; (void)bit; (void)task;
	CHECK(false);
	return -EINTR;
}
static int __dm_resume(struct mapped_device *md, struct dm_table *table)
{
	CHECK(md->suspend_lock && table);
	++resumes;
	clear_bit(DMF_BLOCK_IO_FOR_SUSPEND, &md->flags);
	return 0;
}
static void might_sleep(void) { CHECK(!spinlocks && !mutexes); }
static struct gendisk *dm_disk(struct mapped_device *md) { return md->disk; }
static unsigned disk_devt(struct gendisk *device) { CHECK(device); return 1; }
#define MINOR(value) (value)
static void idr_replace(int *idr, void *value, unsigned minor)
{
	CHECK(idr == &_minor_idr && value == MINOR_ALLOCED && minor == 1 && _minor_lock);
}
static void blk_mark_disk_dead(struct gendisk *device) { CHECK(device && !spinlocks && !mutexes); ++dead_marks; }
static void dm_table_presuspend_targets(struct dm_table *table) { CHECK(table); }
static void dm_table_postsuspend_targets(struct dm_table *table) { CHECK(table); }
static void fsleep(unsigned usec) { (void)usec; CHECK(false); }
#define DMWARN(...) CHECK(false)
static struct dm_table *__unbind(struct mapped_device *md)
{
	struct dm_table *table = md->map;
	CHECK(!md->holders && !md->srcu && !spinlocks && !mutexes);
	md->map = NULL;
	return table;
}
static void dm_table_destroy(struct dm_table *table);
static void free_dev(struct mapped_device *md);
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
static int swapz_trial_controller_retire_registered(
	struct dm_target *ti, const struct swapz_trial_retained_scope *key);
#endif

#include "actual-dm-final-removal.h"

static void dm_table_destroy(struct dm_table *table)
{
	CHECK(table && !spinlocks && !mutexes);
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
	if (dm_swapz_final.md == table->md) {
		CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_DELETING);
		CHECK(!dm_swapz_final.table);
	}
#endif
	++dtrs;
}
static void free_dev(struct mapped_device *md)
{
	CHECK(!md->map && !md->holders && !md->srcu && !spinlocks && !mutexes);
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
	CHECK(dm_swapz_final.md != md);
#endif
	++frees;
}
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
static int swapz_trial_controller_retire_registered(
	struct dm_target *ti, const struct swapz_trial_retained_scope *key)
{
	++callbacks;
	CHECK(!spinlocks && !mutexes && selected.srcu == 1 && selected.holders == 2 + selected.open_count);
	CHECK(ti == &target && ti->table == &live);
	if (key->identity != exact.identity || key->session != exact.session ||
	    key->epoch != exact.epoch || key->target_epoch != exact.target_epoch ||
	    key->registration_epoch != exact.registration_epoch)
		return -ESTALE;
	/* A successful callback may have called fput, but actual DM close
	 * is independently modeled later; never decrement open_count here. */
	if (callback_hook)
		callback_hook();
	return callback_error;
}
#endif

static void initialize(void)
{
	selected = (struct mapped_device){.holders = 1, .map = &live, .disk = &disk, .queue = &queue};
	other = (struct mapped_device){.holders = 1, .map = &foreign, .disk = &other_disk, .queue = &other_queue};
	disk.private_data = &selected;
	other_disk.private_data = &other;
	live = (struct dm_table){&selected, 1, &target};
	replacement = (struct dm_table){&selected, 1, &replacement_target};
	foreign = (struct dm_table){&other, 1, &foreign_target};
	target = (struct dm_target){&live, &swapz_type};
	replacement_target = (struct dm_target){&replacement, &swapz_type};
	foreign_target = (struct dm_target){&foreign, &wrong_type};
	set_bit(DMF_SUSPENDED, &selected.flags);
	set_bit(DMF_BLOCK_IO_FOR_SUSPEND, &selected.flags);
	set_bit(DMF_SUSPENDED, &other.flags);
	set_bit(DMF_BLOCK_IO_FOR_SUSPEND, &other.flags);
}
static void ordinary(void)
{
	CHECK(!dm_blk_open(&disk, 0) && selected.open_count == 1 && selected.holders == 2);
	CHECK(dm_lock_for_deletion(&selected, true, false) == -EBUSY);
	CHECK(test_bit(DMF_DEFERRED_REMOVE, &selected.flags) && !dm_deleting_md(&selected));
	CHECK(dm_swap_table(&selected, &replacement) == &live);
	CHECK(!dm_resume(&selected) && !dm_suspended_md(&selected));
	CHECK(binds == 1 && resumes == 1 && !callbacks);
	/* Native close is external here; ordinary counted open and holder. */
	--selected.open_count;
	--selected.holders;
	CHECK(!dm_lock_for_deletion(&selected, false, true) && dm_deleting_md(&selected));
	--selected.holders;
	__dm_destroy(&selected, true);
	CHECK(dtrs == 1 && frees == 1 && dead_marks == 1 && !callbacks);
}
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
static int retire(void) { return dm_swapz_retire_final_table(&selected, &live, &exact); }
static void retained(enum dm_swapz_final_phase phase, unsigned expected_callbacks)
{
	CHECK(dm_swapz_final.md == &selected && dm_swapz_final.table == &live);
	CHECK(dm_swapz_final.phase == phase && callbacks == expected_callbacks);
	CHECK(selected.holders == 2 + selected.open_count && gets == 1 && !puts_count && !selected.srcu);
	CHECK(!dm_deleting_md(&selected) && !dtrs && !frees);
	CHECK(dm_lock_for_deletion(&selected, true, false) == -EAGAIN);
	CHECK(!test_bit(DMF_DEFERRED_REMOVE, &selected.flags));
}
static void ready(unsigned expected_callbacks)
{
	CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_READY && callbacks == expected_callbacks);
	CHECK(selected.holders == 1 && gets == 1 && puts_count == 1 && !selected.srcu);
	CHECK(!dm_deleting_md(&selected) && !dtrs && !frees);
}
static void preflight(void)
{
	struct swapz_trial_retained_scope key = exact;
	key.registration_epoch = 0;
	CHECK(dm_swapz_retire_final_table(NULL, &live, &exact) == -EINVAL);
	CHECK(dm_swapz_retire_final_table(&selected, NULL, &exact) == -EINVAL);
	CHECK(dm_swapz_retire_final_table(&selected, &live, NULL) == -EINVAL);
	CHECK(dm_swapz_retire_final_table(&selected, &live, &key) == -EINVAL);
	CHECK(dm_swapz_retire_final_table(&selected, &replacement, &exact) == -ESTALE);
	target.type = &wrong_type;
	CHECK(retire() == -ESTALE);
	target.type = &swapz_type;
	target.table = &replacement;
	CHECK(retire() == -ESTALE);
	target.table = &live;
	live.num_targets = 2;
	CHECK(retire() == -ESTALE);
	live.num_targets = 1;
	clear_bit(DMF_SUSPENDED, &selected.flags);
	CHECK(retire() == -EBUSY);
	set_bit(DMF_SUSPENDED, &selected.flags);
	clear_bit(DMF_BLOCK_IO_FOR_SUSPEND, &selected.flags);
	CHECK(retire() == -EBUSY);
	set_bit(DMF_BLOCK_IO_FOR_SUSPEND, &selected.flags);
	set_bit(DMF_POST_SUSPENDING, &selected.flags);
	CHECK(retire() == -EBUSY);
	clear_bit(DMF_POST_SUSPENDING, &selected.flags);
	set_bit(DMF_SUSPENDED_INTERNALLY, &selected.flags);
	CHECK(retire() == -EBUSY);
	clear_bit(DMF_SUSPENDED_INTERNALLY, &selected.flags);
	selected.deferred = true;
	CHECK(retire() == -EBUSY);
	selected.deferred = false;
	selected.requeue_list = &target;
	CHECK(retire() == -EBUSY);
	selected.requeue_list = NULL;
	selected.inflight = true;
	CHECK(retire() == -EBUSY);
	selected.inflight = false;
	selected.request_based = true;
	CHECK(retire() == -EBUSY);
	selected.request_based = false;
	set_bit(DMF_DELETING, &selected.flags);
	CHECK(retire() == -EBUSY);
	clear_bit(DMF_DELETING, &selected.flags);
	CHECK(!callbacks && !gets && !puts_count && selected.holders == 1 && !selected.srcu);
	CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_IDLE && !dm_swapz_final.md);
	CHECK(!dm_resume(&selected) && resumes == 1 && !callbacks);
}
static void wrong_key(void)
{
	struct swapz_trial_retained_scope key = exact;
	++key.registration_epoch;
	CHECK(dm_swapz_retire_final_table(&selected, &live, &key) == -ESTALE);
}
static void competing(void)
{
	CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_RUNNING);
	CHECK(retire() == -EBUSY);
	wrong_key();
	CHECK(dm_blk_open(&disk, 0) == -ENXIO);
	CHECK(dm_lock_for_deletion(&selected, true, false) == -EAGAIN);
	CHECK(dm_resume(&selected) == -EBUSY);
	CHECK(dm_swap_table(&selected, &replacement) == ERR_PTR(-EBUSY));
	__dm_destroy(&selected, false);
	CHECK(warnings == 1 && !dead_marks && !dtrs && !frees);
	CHECK(dm_blk_open(&other_disk, 0) == 0 && other.open_count == 1);
	CHECK(dm_lock_for_deletion(&other, true, false) == -EBUSY);
	--other.open_count;
	--other.holders;
}
static void late_table(void) { selected.map = &replacement; }
static void late_pending(void) { selected.deferred = true; }
/* Model actual native close/open holder accounting independently of the
 * retirement callback. The adversarial positive count is a negative gate test. */
static void model_open_count(int count)
{
	CHECK(!spinlocks && !mutexes && count >= 0);
	selected.holders += count - selected.open_count;
	selected.open_count = count;
}
static void close_wait(void)
{
	model_open_count(2); /* preexisting open files, not new admission */
	CHECK(retire() == -EBUSY);
	retained(DM_SWAPZ_FINAL_RETIRED, 1);
	wrong_key();
	CHECK(dm_blk_open(&disk, 0) == -ENXIO);
	CHECK(retire() == -EBUSY);
	retained(DM_SWAPZ_FINAL_RETIRED, 1);
	model_open_count(0); /* independently observed close */
	CHECK(!retire());
	ready(1);
	CHECK(retire() == -EALREADY);
	model_open_count(1); /* adversarial recheck: no native bypass */
	CHECK(dm_lock_for_deletion(&selected, false, false) == -EBUSY);
	CHECK(!dm_deleting_md(&selected));
	model_open_count(0);
	selected.deferred = true;
	CHECK(dm_lock_for_deletion(&selected, false, false) == -EAGAIN);
	selected.deferred = false;
	CHECK(dm_lock_for_deletion(&selected, false, true) == -EEXIST);
	CHECK(!dm_lock_for_deletion(&selected, false, false));
	CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_DELETING && !dm_swapz_final.table);
	CHECK(dm_lock_for_deletion(&selected, false, false) == -EAGAIN);
	CHECK(dm_resume(&selected) == -EBUSY);
	CHECK(dm_swap_table(&selected, &replacement) == ERR_PTR(-EBUSY));
	--selected.holders; /* original independent owner drops its holder */
	__dm_destroy(&selected, true);
	CHECK(dm_swapz_final.phase == DM_SWAPZ_FINAL_DESTROYED && !dm_swapz_final.md);
	CHECK(!dm_swapz_final.table && callbacks == 1 && dtrs == 1 && frees == 1);
	foreign_target.type = &swapz_type;
	CHECK(dm_swapz_retire_final_table(&other, &foreign, &exact) == -EALREADY);
}
static void run_guarded(const char *mode)
{
	if (!strcmp(mode, "preflight")) {
		preflight();
	} else if (!strcmp(mode, "close-wait")) {
		close_wait();
	} else if (!strcmp(mode, "reentry")) {
		callback_hook = competing;
		CHECK(!retire());
		ready(1);
		CHECK(!binds && !resumes && !selected.open_count);
	} else if (!strcmp(mode, "retry")) {
		callback_error = -EBUSY;
		CHECK(retire() == -EBUSY);
		retained(DM_SWAPZ_FINAL_RETRY, 1);
		wrong_key();
		callback_error = 0;
		model_open_count(1);
		CHECK(retire() == -EBUSY);
		retained(DM_SWAPZ_FINAL_RETIRED, 2);
		model_open_count(0);
		CHECK(!retire());
		ready(2);
	} else if (!strcmp(mode, "quarantine")) {
		callback_error = -EIO;
		CHECK(retire() == -EIO);
		retained(DM_SWAPZ_FINAL_QUARANTINED, 1);
		CHECK(dm_swapz_final.first_error == -EIO);
		callback_error = 0;
		CHECK(retire() == -EIO);
		wrong_key();
		retained(DM_SWAPZ_FINAL_QUARANTINED, 1);
	} else if (!strcmp(mode, "stale-key")) {
		struct swapz_trial_retained_scope key = exact;
		++key.registration_epoch;
		CHECK(dm_swapz_retire_final_table(&selected, &live, &key) == -ESTALE);
		retained(DM_SWAPZ_FINAL_QUARANTINED, 1);
		CHECK(dm_swapz_final.first_error == -ESTALE);
		CHECK(retire() == -ESTALE && callbacks == 1);
	} else if (!strcmp(mode, "stale-after")) {
		callback_hook = late_table;
		CHECK(retire() == -ESTALE);
		retained(DM_SWAPZ_FINAL_QUARANTINED, 1);
		CHECK(dm_swapz_final.first_error == -ESTALE);
	} else if (!strcmp(mode, "late-pending")) {
		callback_hook = late_pending;
		CHECK(retire() == -EBUSY);
		retained(DM_SWAPZ_FINAL_RETIRED, 1);
		selected.deferred = false; /* host substitute, not native drain */
		CHECK(!retire());
		ready(1);
	} else {
		CHECK(false);
	}
}
#endif
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	initialize();
	if (!strcmp(argv[1], "ordinary")) {
		ordinary();
#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST
	} else {
		run_guarded(argv[1]);
#else
	} else {
		CHECK(false);
#endif
	}
	CHECK(!spinlocks && !mutexes && !selected.srcu && !other.srcu && srcu_gets == srcu_puts);
	printf("R107_A11_HOST_ONLY mode=%s checks=%u AUTH0\n", argv[1], checks);
	return 0;
}
