/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual staged MM control functions; explicit host lock/RCU/file/broker
 * substitutes. Seeding old retained debt below is not an admission grant. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>

typedef uint64_t u64;
typedef uint32_t u32;
typedef u64 sector_t;
#define MAX_SWAPFILES 32U
#define U32_MAX UINT32_MAX
#define SWAPZ_ROUND103_EXTERNAL_JOIN_TEST 1
#define SWAPZ_ROUND106_ADMITTED_OWNER_TEST 1
static unsigned checks, locks, mutexes, grace_count, file_gets, file_puts, area_queries, cap_gets, cap_puts;
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R106_A11_FIRST_ERROR line=%d %s\n", __LINE__, #condition); \
		exit(77); \
	} \
} while (0)
#define spin_lock_irqsave(lock, flags) do { CHECK(!*(lock)); (flags) = 0; *(lock) = 1; ++locks; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); CHECK(*(lock) && locks); *(lock) = 0; --locks; } while (0)
#define rcu_access_pointer(pointer) (pointer)
#define rcu_assign_pointer(pointer, value) ((pointer) = (value))
static void mutex_lock(int *lock) { CHECK(!*lock && !locks); *lock = 1; ++mutexes; }
static void mutex_unlock(int *lock) { CHECK(*lock && mutexes && !locks); *lock = 0; --mutexes; }
static void (*grace_hook)(void);
static void synchronize_rcu(void)
{
	CHECK(!locks && !mutexes);
	++grace_count;
	if (grace_hook) {
		void (*hook)(void) = grace_hook;
		grace_hook = NULL;
		hook();
	}
}
static u64 atomic64_read(const u64 *value) { return *value; }
static int atomic_read_acquire(const int *value) { return *value; }
struct block_device { sector_t sectors; bool partition; };
struct inode { unsigned i_mode; };
struct file { struct inode inode; struct block_device *bdev; unsigned refs; };
struct swapz_mm_trial_scope {
	u64 identity, session, table_epoch, target_epoch, area_epoch;
	struct block_device *bdev;
	void *broker;
	u32 swap_type;
	sector_t first_sector, sector_count;
};
static struct inode *file_inode(struct file *file) { return &file->inode; }
static struct block_device *file_bdev(struct file *file) { return file->bdev; }
static bool bdev_is_partition(struct block_device *bdev) { return bdev->partition; }
static sector_t bdev_nr_sectors(struct block_device *bdev) { return bdev->sectors; }
static void get_file(struct file *file) { CHECK(file->refs); ++file->refs; ++file_gets; }
static void fput(struct file *file) { CHECK(!locks && !mutexes && file->refs); --file->refs; ++file_puts; }
static struct block_device mapper = {256, false}, foreign = {256, false};
static struct file opened = {{S_IFBLK}, &mapper, 1}, area = {{S_IFBLK}, &mapper, 1};
static struct file wrong = {{S_IFBLK}, &foreign, 1};
static unsigned broker;
static int swapz_mm_scope_lock, swapz_mm_terminal_gate, swapz_mm_busy;
static u64 swapz_mm_area_epochs[MAX_SWAPFILES];
static struct swapz_mm_trial_scope swapz_mm_scope_storage;
static const struct swapz_mm_trial_scope *swapz_mm_scope, *swapz_mm_capture_scope;
static struct file *swapz_mm_scope_file, *swapz_mm_area_file;
static bool swapz_mm_scope_used, swapz_mm_scope_transition, swapz_mm_scope_capture_stopped;
static bool swapz_mm_scope_files_detached, swapz_mm_area_drained, swapz_mm_terminal_closed, swapz_mm_terminal_joined;
static struct { bool fault; unsigned count; } swapz_mm_terminal_debt;
static unsigned swapz_mm_scope_cap;
static bool fail_put;
static int swapz_mm_trial_area_get(struct file *file, sector_t first, sector_t count,
	u32 *type, u64 *epoch, struct file **retained)
{
	++area_queries;
	CHECK(file == &opened && first == 56 && count == 16 && !locks && !mutexes);
	*type = 2;
	*epoch = swapz_mm_area_epochs[2];
	get_file(&area);
	*retained = &area;
	return 0;
}
static int swapz_ticket_broker_try_get(void *requested, u64 session, u64 epoch, unsigned *cap)
{
	++cap_gets;
	CHECK(!locks && requested == &broker && session == 11 && epoch == 12 && !*cap);
	++*cap;
	return 0;
}
static int swapz_ticket_broker_put(unsigned *cap)
{
	++cap_puts;
	CHECK(!locks && *cap == 1);
	if (fail_put)
		return -EIO;
	--*cap;
	return 0;
}
#include "actual-terminal-helpers.h"
#include "actual-scope-control.h"

static struct swapz_mm_trial_scope candidate(void)
{
	return (struct swapz_mm_trial_scope){.identity = 17, .session = 11,
		.table_epoch = 12, .target_epoch = 13, .area_epoch = 19,
		.bdev = &mapper, .broker = &broker, .swap_type = 2,
		.first_sector = 56, .sector_count = 16};
}
static void denied(void)
{
	struct swapz_mm_trial_scope scope = candidate();
	swapz_mm_area_epochs[2] = 19;
	CHECK(swapz_mm_trial_scope_publish(&scope, &opened) == -EACCES);
	CHECK(swapz_mm_trial_scope_publish(NULL, NULL) == -EACCES);
	CHECK(swapz_mm_trial_scope_publish(&scope, &wrong) == -EACCES);
	++scope.area_epoch;
	CHECK(swapz_mm_trial_scope_publish(&scope, &opened) == -EACCES);
	--scope.area_epoch;
	++scope.target_epoch;
	CHECK(swapz_mm_trial_scope_publish(&scope, &opened) == -EACCES);
	CHECK(!area_queries && !cap_gets && !file_gets && !file_puts && !cap_puts && !grace_count);
	CHECK(!swapz_mm_scope_used && !swapz_mm_scope_file && !swapz_mm_area_file && !swapz_mm_scope_cap);
	CHECK(!swapz_mm_scope && !swapz_mm_capture_scope && opened.refs == 1 && area.refs == 1);
}
static void seed_retained(void)
{
	/* Model only an already-retained R105 scope; never use publication. */
	swapz_mm_scope_storage = candidate();
	swapz_mm_scope_used = true;
	swapz_mm_scope = &swapz_mm_scope_storage;
	swapz_mm_scope_file = &opened;
	swapz_mm_area_file = &area;
	swapz_mm_scope_cap = 1;
	swapz_mm_scope_capture_stopped = true;
	swapz_mm_area_drained = swapz_mm_terminal_closed = swapz_mm_terminal_joined = true;
}
static void preserve(void)
{
	CHECK(!swapz_mm_scope_transition && !swapz_mm_scope && swapz_mm_scope_file == &opened);
	CHECK(swapz_mm_area_file == &area && opened.refs == 1 && area.refs == 1);
	CHECK(swapz_mm_scope_cap == 1 && !file_puts && !cap_puts);
}
static void reentry(void)
{
	CHECK(swapz_mm_scope_transition);
	CHECK(swapz_mm_trial_scope_revoke(17) == -EBUSY);
	CHECK(swapz_mm_trial_scope_stop_capture(17) == -EBUSY);
}
static void late_fault(void) { reentry(); swapz_mm_terminal_debt.fault = true; }
static void late_debt(void) { reentry(); ++swapz_mm_terminal_debt.count; }
static void late_carrier(void) { reentry(); swapz_mm_busy = 1; }
static void late_unjoin(void) { reentry(); swapz_mm_terminal_joined = false; }
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	if (!strcmp(argv[1], "denied")) {
		denied();
	} else {
		seed_retained();
		CHECK(swapz_mm_trial_scope_revoke(18) == -ESTALE && !cap_puts);
		if (!strcmp(argv[1], "late-fault")) {
			grace_hook = late_fault;
			CHECK(swapz_mm_trial_scope_revoke(17) == -EUCLEAN);
			preserve();
		} else if (!strcmp(argv[1], "late-debt")) {
			grace_hook = late_debt;
			CHECK(swapz_mm_trial_scope_revoke(17) == -EBUSY);
			preserve();
		} else if (!strcmp(argv[1], "late-carrier")) {
			grace_hook = late_carrier;
			CHECK(swapz_mm_trial_scope_revoke(17) == -EBUSY);
			preserve();
		} else if (!strcmp(argv[1], "late-unjoin")) {
			grace_hook = late_unjoin;
			CHECK(swapz_mm_trial_scope_revoke(17) == -EBUSY);
			preserve();
		} else if (!strcmp(argv[1], "retry")) {
			grace_hook = reentry;
			fail_put = true;
			CHECK(swapz_mm_trial_scope_revoke(17) == -EIO);
			CHECK(swapz_mm_scope_cap == 1 && cap_puts == 1 && !file_puts);
			fail_put = false;
			CHECK(!swapz_mm_trial_scope_revoke(17));
			CHECK(cap_puts == 2 && file_puts == 2 && !swapz_mm_scope_cap);
			CHECK(!opened.refs && !area.refs && !swapz_mm_scope_file && !swapz_mm_area_file);
			CHECK(swapz_mm_trial_scope_revoke(17) == -ESTALE);
		} else if (!strcmp(argv[1], "detached")) {
			swapz_mm_scope = NULL;
			swapz_mm_scope_file = swapz_mm_area_file = NULL;
			swapz_mm_scope_files_detached = true;
			swapz_mm_scope_storage.bdev = NULL;
			CHECK(!swapz_mm_trial_scope_revoke(17));
			CHECK(!file_puts && cap_puts == 1 && !swapz_mm_scope_cap && !swapz_mm_scope_files_detached);
			CHECK(swapz_mm_trial_scope_revoke(17) == -ESTALE);
		} else {
			CHECK(false);
		}
	}
	CHECK(!locks && !mutexes && !swapz_mm_scope_transition);
	printf("R106_A11_HOST_ONLY mode=%s checks=%u AUTH0\n", argv[1], checks);
	return 0;
}
