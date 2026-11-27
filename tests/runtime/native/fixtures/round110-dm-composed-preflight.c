/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact extracted DM seam; external kernel lifetime/lock/callback substitutes.
 * No real device, admission, controller behavior or concurrent kernel proof. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
typedef uint32_t u32;
typedef uint64_t u64, sector_t;
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
#define SWAPZ_ROUND107_FINAL_REMOVAL_TEST 1
#define SWAPZ_ROUND109_AREA_PREFLIGHT_TEST 1
#define SWAPZ_ROUND103_EXTERNAL_JOIN_TEST 1
#define SWAPZ_ROUND098_SCOPED_PRODUCER_TEST 1
#define FMODE_PATH 1
#define DMF_FREEING 0
#define DMF_DELETING 1
#define DMF_DEFERRED_REMOVE 2
#define DMF_BLOCK_IO_FOR_SUSPEND 3
#define DMF_POST_SUSPENDING 4
#define DMF_NOFLUSH_SUSPENDING 5
#define DMF_SUSPENDED 6
#define DMF_SUSPENDED_INTERNALLY 7
static unsigned checks, mutexes, spins, borrows, releases, mm_calls, target_calls;
static int _minor_lock;
#define CHECK(x) do { ++checks; if (!(x)) { \
	fprintf(stderr, "R110_A11_FIRST_ERROR line=%d %s\n", __LINE__, #x); exit(77); \
} } while (0)
struct mapped_device;
struct dm_table;
struct block_device;
struct file_operations { int unused; };
static const struct file_operations def_blk_fops = {0}, other_fops = {1};
struct block_device_operations { int unused; };
static const struct block_device_operations dm_blk_dops = {0}, other_dops = {1};
struct gendisk {
	struct block_device *part0;
	const struct block_device_operations *fops;
	void *private_data;
	bool live;
};
struct block_device { struct gendisk *bd_disk; bool partition; };
struct inode { unsigned i_mode; };
struct file {
	struct inode inode;
	const struct file_operations *f_op;
	unsigned f_mode, references;
	struct block_device *bdev;
};
struct target_type { const char *name; };
struct dm_target {
	struct dm_table *table;
	struct target_type *type;
	sector_t begin, len;
};
struct dm_table {
	struct mapped_device *md;
	unsigned num_targets;
	struct dm_target *target;
	sector_t size;
};
struct mapped_device {
	struct gendisk *disk;
	int suspend_lock, open_count;
	unsigned long flags;
	bool request_based;
	struct dm_table *map;
	unsigned holders, srcu;
};
struct swapz_mm_trial_area_identity { u32 swap_type; u64 area_epoch; };
struct swapz_trial_target_preflight {
	u64 session, table_epoch, target_epoch, registration_epoch;
	sector_t first_sector, sector_count;
};
static struct { struct mapped_device *md; } dm_swapz_final;
static struct mapped_device md, foreign_md;
static struct gendisk disk, foreign_disk;
static struct block_device bdev, foreign_bdev;
static struct file mapper;
static struct dm_table table, foreign_table;
static struct dm_target target;
static struct target_type swapz_type = {"swapz"}, wrong_type = {"linear"};
static int mm_first_error, mm_second_error, target_error;
static struct swapz_mm_trial_area_identity mm_first, mm_second;
static struct swapz_trial_target_preflight target_result;
static void (*during_target)(void);
static void mutex_lock(int *lock)
{
	CHECK(lock == &md.suspend_lock && !*lock && !spins && !md.srcu);
	*lock = 1;
	++mutexes;
}
static void mutex_unlock(int *lock)
{
	CHECK(lock == &md.suspend_lock && *lock && mutexes == 1 && !spins && !md.srcu);
	*lock = 0;
	--mutexes;
}
static void spin_lock(int *lock)
{
	CHECK(lock == &_minor_lock && !*lock && mutexes == 1 && !spins);
	*lock = 1;
	++spins;
}
static void spin_unlock(int *lock)
{
	CHECK(lock == &_minor_lock && *lock && spins == 1);
	*lock = 0;
	--spins;
}
#define lockdep_assert_held(lock) CHECK(*(lock))
#define lockdep_assert_not_held(lock) CHECK(!*(lock))
#define lockdep_is_held(lock) (*(lock))
#define rcu_dereference_protected(pointer, held) ((void)(held), (pointer))
static bool test_bit(unsigned bit, const unsigned long *flags) { return (*flags >> bit) & 1U; }
static int dm_open_count(struct mapped_device *device) { CHECK(_minor_lock); return device->open_count; }
static bool dm_deleting_md(struct mapped_device *device) { return test_bit(DMF_DELETING, &device->flags); }
static __attribute__((unused)) bool dm_suspended_md(struct mapped_device *device) { return test_bit(DMF_SUSPENDED, &device->flags); }
static bool dm_suspended_internally_md(struct mapped_device *device) { return test_bit(DMF_SUSPENDED_INTERNALLY, &device->flags); }
static bool dm_request_based(struct mapped_device *device) { return device->request_based; }
static bool disk_live(struct gendisk *device) { CHECK(!spins && device); return device->live; }
static struct inode *file_inode(struct file *file) { CHECK(file); return &file->inode; }
static struct block_device *file_bdev(struct file *file)
{
	CHECK(file && file->references == 1 && file->f_op == &def_blk_fops && !(file->f_mode & FMODE_PATH));
	return file->bdev;
}
static __attribute__((unused)) bool bdev_is_partition(struct block_device *device) { return device->partition; }
static struct dm_table *dm_get_live_table(struct mapped_device *device, int *index)
{
	CHECK(device == &md && mutexes == 1 && !spins && !device->srcu);
	*index = 7;
	++device->srcu;
	++borrows;
	return device->map;
}
static void dm_put_live_table(struct mapped_device *device, int index)
{
	CHECK(device == &md && index == 7 && mutexes == 1 && !spins && device->srcu == 1);
	--device->srcu;
	++releases;
}
static __attribute__((unused)) struct mapped_device *dm_table_get_md(struct dm_table *value) { CHECK(md.srcu); return value->md; }
static struct dm_target *dm_table_get_target(struct dm_table *value, unsigned index)
{
	CHECK(md.srcu && value->num_targets == 1 && index == 0);
	return value->target;
}
static sector_t dm_table_get_size(struct dm_table *value) { CHECK(md.srcu); return value->size; }
static int swapz_mm_trial_area_preflight(struct file *file, sector_t first, sector_t count,
				       struct swapz_mm_trial_area_identity *result)
{
	CHECK(file == &mapper && first && count && mutexes == 1 && !spins && md.srcu == 1);
	++mm_calls;
	CHECK(mm_calls <= 2);
	if (mm_calls == 1) {
		CHECK(!target_calls);
		*result = mm_first;
		return mm_first_error;
	}
	CHECK(target_calls == 1);
	*result = mm_second;
	return mm_second_error;
}
static int swapz_trial_controller_query_registered(struct dm_target *value, struct file *file,
		const void *broker, sector_t first, sector_t count,
		struct swapz_trial_target_preflight *result)
{
	CHECK(value == &target && file == &mapper && !broker && first == 8 && count == 128);
	CHECK(mutexes == 1 && !spins && md.srcu == 1 && mm_calls == 1 && !target_calls);
	++target_calls;
	if (during_target)
		during_target();
	*result = target_result;
	return target_error;
}
#include "actual-composed.h"

static void reset(void)
{
	CHECK(!mutexes && !spins && !md.srcu && borrows == releases);
	md = (struct mapped_device){.disk = &disk, .open_count = 1, .map = &table, .holders = 2};
	disk = (struct gendisk){&bdev, &dm_blk_dops, &md, true};
	foreign_disk = (struct gendisk){&foreign_bdev, &dm_blk_dops, &foreign_md, true};
	bdev = (struct block_device){&disk, false};
	foreign_bdev = (struct block_device){&foreign_disk, false};
	mapper = (struct file){{S_IFBLK}, &def_blk_fops, 0, 1, &bdev};
	table = (struct dm_table){&md, 1, &target, 1024};
	foreign_table = table;
	target = (struct dm_target){&table, &swapz_type, 0, 1024};
	dm_swapz_final.md = NULL;
	mm_first = mm_second = (struct swapz_mm_trial_area_identity){0, 21};
	target_result = (struct swapz_trial_target_preflight){31, 32, 33, 34, 8, 128};
	mm_first_error = mm_second_error = target_error = 0;
	mm_calls = target_calls = 0;
	during_target = NULL;
}
static void query(struct mapped_device *device, struct file *file, sector_t first, sector_t count,
		  int expected, unsigned expected_mm, unsigned expected_target, unsigned expected_borrow)
{
	struct dm_swapz_preflight result = {99, 99, 99, 99, 99, 99, 99, 99};
	unsigned old_borrows = borrows, old_releases = releases;
	CHECK(dm_swapz_combined_preflight(device, file, first, count, &result) == expected);
	CHECK(!mutexes && !spins && !md.srcu && mapper.references == 1 && md.holders == 2);
	CHECK(borrows == old_borrows + expected_borrow && releases == old_releases + expected_borrow);
	CHECK(mm_calls == expected_mm && target_calls == expected_target);
	if (expected) {
		CHECK(!result.swap_type && !result.area_epoch && !result.session && !result.table_epoch &&
		      !result.target_epoch && !result.registration_epoch && !result.first_sector && !result.sector_count);
	} else {
		CHECK(result.swap_type == mm_second.swap_type && result.area_epoch == mm_second.area_epoch);
		CHECK(result.session == 31 && result.table_epoch == 32 && result.target_epoch == 33 &&
		      result.registration_epoch == 34 && result.first_sector == first && result.sector_count == count);
	}
}
#define RUN(error, mm, target_count, borrow) query(&md, &mapper, 8, 128, error, mm, target_count, borrow)
static void invalid(void)
{
	query(NULL, &mapper, 8, 128, -EINVAL, 0, 0, 0);
	query(&md, NULL, 8, 128, -EINVAL, 0, 0, 0);
	CHECK(dm_swapz_combined_preflight(&md, &mapper, 8, 128, NULL) == -EINVAL);
	mapper.inode.i_mode = S_IFREG;
	RUN(-EINVAL, 0, 0, 0);
	reset();
	mapper.f_op = &other_fops;
	RUN(-EINVAL, 0, 0, 0);
	reset();
	mapper.f_mode = FMODE_PATH;
	RUN(-EINVAL, 0, 0, 0);
	reset();
	bdev.partition = true;
	RUN(-EINVAL, 0, 0, 0);
	reset();
	mapper.bdev = NULL;
	RUN(-EINVAL, 0, 0, 0);
	reset();
	query(&md, &mapper, 0, 128, -EINVAL, 0, 0, 0);
	query(&md, &mapper, 1, 128, -EINVAL, 0, 0, 0);
	query(&md, &mapper, 8, 0, -EINVAL, 0, 0, 0);
	query(&md, &mapper, 8, 7, -EINVAL, 0, 0, 0);
	query(&md, &mapper, 8, 136, -EINVAL, 0, 0, 0);
	query(&md, &mapper, UINT64_MAX - 7, 8, -EINVAL, 0, 0, 0);
}
static void lifecycle(void)
{
	for (unsigned bit = 0; bit <= DMF_SUSPENDED_INTERNALLY; ++bit) {
		reset();
		md.flags = 1UL << bit;
		RUN(-ESTALE, 0, 0, 0);
	}
	reset();
	dm_swapz_final.md = &md;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	md.open_count = 0;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	md.request_based = true;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	disk.live = false;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	disk.private_data = &foreign_md;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	disk.fops = &other_dops;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	mapper.bdev = &foreign_bdev;
	RUN(-ESTALE, 0, 0, 0);
	reset();
	disk.part0 = &foreign_bdev;
	RUN(-ESTALE, 0, 0, 0);
}
static void topology(void)
{
	md.map = NULL;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	table.md = &foreign_md;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	table.num_targets = 2;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	table.target = NULL;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	target.table = &foreign_table;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	target.type = NULL;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	target.type = &wrong_type;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	target.begin = 8;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	target.len = 512;
	RUN(-ESTALE, 0, 0, 1);
	reset();
	query(&md, &mapper, 1024, 8, -ESTALE, 0, 0, 1);
	query(&md, &mapper, 1016, 16, -ESTALE, 0, 0, 1);
}
static void failures(void)
{
	mm_first_error = -EINVAL;
	RUN(-EINVAL, 1, 0, 1);
	reset();
	target_error = -ENODEV;
	RUN(-ENODEV, 1, 1, 1);
	reset();
	mm_second_error = -ESTALE;
	RUN(-ESTALE, 2, 1, 1);
	reset();
	mm_first.area_epoch = mm_second.area_epoch = 0;
	RUN(-ESTALE, 2, 1, 1);
	reset();
	target_result.session = 0;
	RUN(-ESTALE, 1, 1, 1);
	reset();
	target_result.table_epoch = 0;
	RUN(-ESTALE, 1, 1, 1);
	reset();
	target_result.target_epoch = 0;
	RUN(-ESTALE, 1, 1, 1);
	reset();
	target_result.registration_epoch = 0;
	RUN(-ESTALE, 1, 1, 1);
	reset();
	target_result.first_sector = 16;
	RUN(-ESTALE, 1, 1, 1);
	reset();
	target_result.sector_count = 8;
	RUN(-ESTALE, 1, 1, 1);
}
static void late_delete(void) { md.flags |= 1UL << DMF_DEFERRED_REMOVE; }
static void late_table(void) { md.map = &foreign_table; }
static void races(void)
{
	mm_second.area_epoch++;
	RUN(-ESTALE, 2, 1, 1);
	reset();
	mm_second.swap_type++;
	RUN(-ESTALE, 2, 1, 1);
	reset();
	during_target = late_delete;
	RUN(-ESTALE, 2, 1, 1);
	reset();
	during_target = late_table; /* impossible under real suspend_lock; fault injection */
	RUN(-ESTALE, 2, 1, 1);
}
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	reset();
	if (!strcmp(argv[1], "success")) {
		RUN(0, 2, 1, 1);
		reset();
		mm_first.swap_type = mm_second.swap_type = 2;
		RUN(0, 2, 1, 1);
	} else if (!strcmp(argv[1], "invalid"))
		invalid();
	else if (!strcmp(argv[1], "lifecycle"))
		lifecycle();
	else if (!strcmp(argv[1], "topology"))
		topology();
	else if (!strcmp(argv[1], "failures"))
		failures();
	else if (!strcmp(argv[1], "races"))
		races();
	else
		return 2;
	CHECK(!mutexes && !spins && !md.srcu && borrows == releases);
	printf("R110_A11_HOST_ONLY mode=%s checks=%u AUTH0\n", argv[1], checks);
	return 0;
}
