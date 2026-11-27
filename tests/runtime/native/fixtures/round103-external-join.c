/* SPDX-License-Identifier: GPL-2.0-only */
/* Real staged area/scope/debt functions with serial lock, RCU, BIO and
 * swap allocator models. This is not native concurrent kernel execution. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

typedef uint64_t u64;
typedef int64_t s64;
typedef uint32_t u32;
typedef uint64_t sector_t;
typedef s64 atomic64_t;
typedef int atomic_t;
#define MAX_SWAPFILES 32U
#define S64_MAX INT64_MAX
#define U32_MAX UINT32_MAX
#define PAGE_SIZE 4096
#define SWP_WRITEOK 1U
#define SWAPZ_ROUND103_EXTERNAL_JOIN_TEST 1
#define SWAPZ_TERMINAL_HOST_TEST 1

static unsigned checks, spin_depth, mutex_depth, readers, grace_count;
static void (*grace_hook)(void);
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R103_A11_FIRST_ERROR line=%d: %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)
#define DEFINE_SPINLOCK(name) int name
#define DEFINE_MUTEX(name) int name
static void spin_lock(int *lock)
{
	CHECK(!*lock);
	*lock = 1;
	++spin_depth;
}
static void spin_unlock(int *lock)
{
	CHECK(*lock && spin_depth);
	*lock = 0;
	--spin_depth;
}
#define spin_lock_irqsave(lock, flags) do { (flags) = 0; spin_lock(lock); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); spin_unlock(lock); } while (0)
static void mutex_lock(int *lock)
{
	CHECK(!*lock && !spin_depth);
	*lock = 1;
	++mutex_depth;
}
static void mutex_unlock(int *lock)
{
	CHECK(*lock && mutex_depth && !spin_depth);
	*lock = 0;
	--mutex_depth;
}
#define rcu_access_pointer(pointer) (pointer)
#define rcu_dereference(pointer) (pointer)
#define rcu_assign_pointer(pointer, value) ((pointer) = (value))
static void rcu_read_lock(void) { ++readers; }
static void rcu_read_unlock(void) { CHECK(readers); --readers; }
static void synchronize_rcu(void)
{
	CHECK(!spin_depth && !mutex_depth && !readers);
	++grace_count;
	if (grace_hook) {
		void (*hook)(void) = grace_hook;
		grace_hook = NULL;
		hook();
	}
}
static u64 atomic64_read(const atomic64_t *counter) { return (u64)*counter; }
static void atomic64_set(atomic64_t *counter, u64 value) { *counter = (s64)value; }
static bool atomic64_try_cmpxchg(atomic64_t *counter, s64 *previous, s64 next)
{
	if (*counter != *previous) {
		*previous = *counter;
		return false;
	}
	*counter = next;
	return true;
}
static int atomic_read_acquire(const atomic_t *counter) { return *counter; }

struct block_device { sector_t sectors; bool partition; };
struct inode { unsigned int i_mode; };
struct file {
	struct inode inode;
	struct block_device *bdev;
	void *f_mapping;
	unsigned refs;
};
static struct inode *file_inode(struct file *file) { return &file->inode; }
static struct block_device *file_bdev(struct file *file) { return file->bdev; }
static bool bdev_is_partition(struct block_device *bdev) { return bdev->partition; }
static sector_t bdev_nr_sectors(struct block_device *bdev) { return bdev->sectors; }
static void get_file(struct file *file) { CHECK(file->refs); ++file->refs; }
static void fput(struct file *file) { CHECK(file->refs && !spin_depth); --file->refs; }

struct swapz_ticket_broker { u64 session, epoch; unsigned refs; };
struct swapz_ticket_cap { struct swapz_ticket_broker *broker; u64 session, epoch; };
static bool fail_put, race_offline;
static void swapz_mm_trial_area_offline_model(void);
static int swapz_ticket_broker_try_get(struct swapz_ticket_broker *broker,
	u64 session, u64 epoch, struct swapz_ticket_cap *cap)
{
	CHECK(!spin_depth);
	if (session != broker->session || epoch != broker->epoch)
		return -ESTALE;
	++broker->refs;
	*cap = (struct swapz_ticket_cap){broker, session, epoch};
	if (race_offline)
		swapz_mm_trial_area_offline_model();
	return 0;
}
static int swapz_ticket_broker_put(struct swapz_ticket_cap *cap)
{
	CHECK(!spin_depth && cap->broker && cap->broker->refs);
	if (fail_put)
		return -EIO;
	--cap->broker->refs;
	*cap = (struct swapz_ticket_cap){0};
	return 0;
}

struct bio {
	struct block_device *bi_bdev;
	void (*bi_end_io)(struct bio *);
	unsigned flags;
	void *private;
};
enum { BIO_CLONED = 1U, BIO_REMAPPED = 2U };
static bool bio_flagged(const struct bio *bio, unsigned flag) { return !!(bio->flags & flag); }
static const int swap_bdev_ops;
struct swap_info_struct {
	unsigned flags, type, max;
	struct block_device *bdev;
	struct file *swap_file;
	const int *ops;
};
static struct swap_info_struct *swap_active_head[2];
static DEFINE_SPINLOCK(swap_lock);
#define plist_for_each_entry(item, head, member) \
	for (unsigned loop_index = 0; loop_index < 2 && \
	     ((item) = (*(head))[loop_index]); ++loop_index)
static atomic64_t swapz_mm_area_epochs[MAX_SWAPFILES], swapz_mm_area_sequence;
static atomic_t swapz_mm_busy;
#include "actual-scope-type.h"
static DEFINE_MUTEX(swapz_mm_scope_lock);
static struct swapz_mm_trial_scope swapz_mm_scope_storage;
static const struct swapz_mm_trial_scope *swapz_mm_scope, *swapz_mm_capture_scope;
static struct swapz_ticket_cap swapz_mm_scope_cap;
static struct file *swapz_mm_scope_file;
static bool swapz_mm_scope_transition, swapz_mm_scope_capture_stopped, swapz_mm_scope_used;
#include "actual-area-declarations.h"
#include "actual-next.h"
#include "swapz-trial-terminal.inc"
#include "actual-scope-control.h"

static struct block_device mapper = {256, false}, foreign = {256, false};
static unsigned mapping, unrelated_mapping;
static struct file area = {{S_IFBLK}, &mapper, &mapping, 1};
static struct file opened = {{S_IFBLK}, &mapper, &mapping, 1};
static struct file wrong_file = {{S_IFBLK}, &mapper, &unrelated_mapping, 1};
static struct swap_info_struct si = {SWP_WRITEOK, 2, 32, &mapper, &area, &swap_bdev_ops};
static struct swapz_ticket_broker broker = {11, 12, 1};
static unsigned callback_count, sio_key;
static bool check_callback_join;

static void swapz_mm_trial_area_offline_model(void)
{
	spin_lock(&swap_lock);
	swapz_mm_trial_area_offline(si.type);
	si.flags = 0;
	spin_unlock(&swap_lock);
}
static void online(void)
{
	spin_lock(&swap_lock);
	si.flags = SWP_WRITEOK;
	swapz_mm_trial_area_online(si.type);
	spin_unlock(&swap_lock);
}
static void retire(void)
{
	swapz_mm_trial_area_offline_model();
	/* The real swapoff call site is statically checked after users/work
	 * and zswap retirement. This model advances only that explicit hook. */
	swapz_mm_trial_area_retired(si.type);
}
static int join(void) { return swapz_mm_trial_scope_join_external(17, 11, 12, 13); }
static void original_endio(struct bio *bio)
{
	CHECK(bio->bi_end_io == original_endio && bio->private == &callback_count);
	CHECK(!spin_depth && !mutex_depth);
	++callback_count;
	if (check_callback_join)
		CHECK(join() == -EBUSY);
}
static void late_entrant(void)
{
	struct bio late = {&mapper, original_endio, 0, &callback_count};
	CHECK(!swapz_mm_trial_dm_enter(&late));
	CHECK(late.bi_end_io == original_endio);
}
static struct swapz_mm_trial_scope prepare(void)
{
	struct file *retained = NULL;
	u32 type = 99;
	u64 epoch = 99;
	struct bio idle = {&mapper, original_endio, 0, &callback_count};
	swap_active_head[0] = &si;
	CHECK(!swapz_mm_trial_dm_enter(&idle) && idle.bi_end_io == original_endio);
	swapz_mm_trial_mm_enter(&mapper, 2, &sio_key);
	CHECK(!swapz_mm_trial_mm_take(&sio_key));
	CHECK(swapz_mm_trial_area_get(&opened, 56, 16, &type, &epoch, &retained) == -ESTALE);
	online();
	CHECK(!swapz_mm_trial_area_get(&opened, 56, 16, &type, &epoch, &retained));
	CHECK(type == 2 && epoch && retained == &area && area.refs == 2);
	fput(retained);
	CHECK(area.refs == 1);
	CHECK(swapz_mm_trial_area_get(&wrong_file, 56, 16, &type, &epoch, &retained) == -ESTALE);
	CHECK(swapz_mm_trial_area_get(&opened, 248, 16, &type, &epoch, &retained) == -ESTALE);
	CHECK(swapz_mm_trial_area_get(&opened, 0, 16, &type, &epoch, &retained) == -EINVAL);
	return (struct swapz_mm_trial_scope){
		.bdev = &mapper, .broker = &broker, .identity = 17, .session = 11,
		.table_epoch = 12, .target_epoch = 13, .area_epoch = swapz_mm_trial_area_epoch(2),
		.first_sector = 56, .sector_count = 16, .swap_type = 2
	};
}
static void normal(void)
{
	struct swapz_mm_trial_scope requested = prepare(), wrong = requested;
	wrong.area_epoch++;
	CHECK(swapz_mm_trial_scope_publish(&wrong, &opened) != 0);
	wrong = requested;
	wrong.session++;
	CHECK(swapz_mm_trial_scope_publish(&wrong, &opened) == -ESTALE);
	wrong = requested;
	wrong.swap_type = 3;
	CHECK(swapz_mm_trial_scope_publish(&wrong, &opened) != 0);
	CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
	CHECK(opened.refs == 2 && area.refs == 2 && broker.refs == 2);
	CHECK(swapz_mm_trial_scope_join_external(18, 11, 12, 13) == -ESTALE);
	CHECK(swapz_mm_trial_scope_join_external(17, 12, 12, 13) == -ESTALE);
	CHECK(swapz_mm_trial_scope_join_external(17, 11, 13, 13) == -ESTALE);
	CHECK(swapz_mm_trial_scope_join_external(17, 11, 12, 14) == -ESTALE);

	struct bio unrelated = {&foreign, original_endio, 0, &callback_count};
	CHECK(!swapz_mm_trial_dm_enter(&unrelated));
	swapz_mm_trial_mm_enter(&mapper, 3, &sio_key);
	CHECK(!swapz_mm_trial_mm_take(&sio_key));
	swapz_mm_trial_mm_enter(&mapper, 2, &sio_key);
	u64 old_ticket = swapz_mm_trial_mm_take(&sio_key);
	CHECK(old_ticket && swapz_mm_terminal_debt.count == 1);
	/* The same freed address can be reused before the old completion
	 * returns; releasing the old ticket cannot consume the newer debt. */
	swapz_mm_trial_mm_enter(&mapper, 2, &sio_key);
	swapz_mm_trial_mm_put(old_ticket);
	CHECK(swapz_mm_terminal_debt.count == 1);
	struct bio original = {&mapper, original_endio, 0, &callback_count};
	u64 entrant = swapz_mm_trial_dm_enter(&original);
	CHECK(entrant && original.bi_end_io != original_endio && swapz_mm_terminal_debt.count == 3);
	CHECK(!swapz_mm_trial_dm_origin(&original, 72));
	CHECK(swapz_mm_trial_dm_origin(&original, 56));
	CHECK(!swapz_mm_trial_dm_origin(&original, 56));
	swapz_mm_trial_dm_leave(entrant);
	CHECK(!swapz_mm_trial_scope_stop_capture(17));
	CHECK(swapz_mm_scope && !swapz_mm_capture_scope);
	CHECK(join() == -EBUSY);
	swapz_mm_trial_area_offline_model();
	CHECK(!swapz_mm_trial_area_epoch(2) && swapz_mm_scope);
	CHECK(join() == -EBUSY);
	swapz_mm_trial_area_retired(2);
	CHECK(join() == -EBUSY && swapz_mm_terminal_closed);
	CHECK(swapz_mm_trial_scope_revoke(17) == -EBUSY);
	CHECK(opened.refs == 2 && area.refs == 2 && broker.refs == 2);
	/* Actual original reissue retains original completion, no new ordinal. */
	entrant = swapz_mm_trial_dm_enter(&original);
	CHECK(entrant && !swapz_mm_trial_dm_origin(&original, 56));
	check_callback_join = true;
	original.bi_end_io(&original);
	CHECK(callback_count == 1 && original.bi_end_io == original_endio);
	CHECK(join() == -EBUSY); /* submission still owns the pre-reference entrant */
	swapz_mm_trial_dm_leave(entrant);
	u64 mm_ticket = swapz_mm_trial_mm_take(&sio_key);
	CHECK(mm_ticket && mm_ticket != old_ticket && join() == -EBUSY);
	swapz_mm_trial_mm_put(mm_ticket);
	swapz_mm_busy = 1;
	CHECK(join() == -EBUSY);
	swapz_mm_busy = 0;
	CHECK(!join() && swapz_mm_terminal_joined && swapz_mm_scope);
	CHECK(!swapz_mm_trial_scope_revoke(17));
	CHECK(opened.refs == 1 && area.refs == 1 && broker.refs == 1 && !swapz_mm_scope);
	CHECK(join() == -ESTALE && swapz_mm_trial_scope_revoke(17) == -ESTALE);
}

static void negative(const char *mode)
{
	struct swapz_mm_trial_scope requested = prepare();
	if (!strcmp(mode, "publish-race") || !strcmp(mode, "publish-quarantine")) {
		race_offline = true;
		fail_put = !strcmp(mode, "publish-quarantine");
		CHECK(swapz_mm_trial_scope_publish(&requested, &opened) == (fail_put ? -EIO : -ESTALE));
		CHECK(!swapz_mm_scope && !swapz_mm_capture_scope);
		CHECK(opened.refs == (fail_put ? 2U : 1U));
		CHECK(area.refs == (fail_put ? 2U : 1U));
		CHECK(broker.refs == (fail_put ? 2U : 1U));
		if (fail_put)
			CHECK(swapz_mm_terminal_debt.fault && swapz_mm_scope_file == &opened);
		return;
	}
	CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
	CHECK(!swapz_mm_trial_scope_stop_capture(17));
	if (!strcmp(mode, "reopen")) {
		swapz_mm_trial_area_offline_model();
		online();
		CHECK(swapz_mm_trial_area_epoch(2) != requested.area_epoch);
		swapz_mm_trial_area_retired(2);
	} else if (!strcmp(mode, "wrong-completion")) {
		swapz_mm_trial_mm_enter(&mapper, 2, &sio_key);
		u64 ticket = swapz_mm_trial_mm_take(&sio_key);
		CHECK(ticket);
		swapz_mm_trial_dm_leave(ticket);
		CHECK(swapz_mm_terminal_debt.count == 1);
		swapz_mm_trial_mm_put(ticket);
		swapz_mm_trial_mm_put(ticket);
		retire();
	} else if (!strcmp(mode, "split")) {
		struct bio parent = {&mapper, original_endio, 0, &callback_count};
		u64 entrant = swapz_mm_trial_dm_enter(&parent);
		CHECK(entrant);
		struct bio split = {&mapper, original_endio, BIO_CLONED, &callback_count};
		CHECK(!swapz_mm_trial_dm_enter(&split) && split.bi_end_io == original_endio);
		parent.bi_end_io(&parent);
		swapz_mm_trial_dm_leave(entrant);
		CHECK(callback_count == 1);
		retire();
	} else if (!strcmp(mode, "late")) {
		retire();
		grace_hook = late_entrant;
	} else if (!strcmp(mode, "overflow")) {
		for (unsigned index = 0; index < SWAPZ_TRIAL_DEBT_SLOTS; ++index)
			CHECK(swapz_trial_debt_retain(&swapz_mm_terminal_debt, NULL, SWAPZ_TRIAL_ENTRY, NULL));
		CHECK(!swapz_trial_debt_retain(&swapz_mm_terminal_debt, NULL, SWAPZ_TRIAL_ENTRY, NULL));
		for (u64 ticket = 1; ticket <= SWAPZ_TRIAL_DEBT_SLOTS; ++ticket)
			swapz_mm_trial_dm_leave(ticket);
		CHECK(!swapz_mm_terminal_debt.count);
		retire();
	} else {
		CHECK(false);
	}
	CHECK(join() == -EUCLEAN);
	CHECK(swapz_mm_trial_scope_revoke(17) == -EUCLEAN);
	CHECK(swapz_mm_scope && opened.refs == 2 && area.refs == 2 && broker.refs == 2);
}

int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	if (!strcmp(argv[1], "normal"))
		normal();
	else
		negative(argv[1]);
	CHECK(!spin_depth && !mutex_depth && !readers);
	printf("R103_A11_HOST_ONLY mode=%s checks=%u grace=%u AUTH0\n", argv[1], checks, grace_count);
	return 0;
}
