/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact extracted native query and historical reference acquisition.
 * Only external kernel mechanisms are modeled. No admission or real I/O. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <sys/stat.h>

typedef uint32_t u32;
typedef uint64_t u64, sector_t;
#define PAGE_SIZE 4096
#define FMODE_PATH (1U << 14)
#define SWP_WRITEOK 2U
#define READ_ONCE(value) (value)
static unsigned checks, locks, unlocks, epoch_reads, file_reads, gets, puts_count;
static int swap_lock;
#define CHECK(x) do { ++checks; if (!(x)) { \
	fprintf(stderr, "R109_A11_FIRST_ERROR line=%d %s\n", __LINE__, #x); exit(77); \
} } while (0)
struct inode { unsigned i_mode; };
struct block_device { sector_t bd_nr_sectors; bool partition, read_only; };
struct file_operations { int unused; };
static const struct file_operations def_blk_fops = {0};
static int swap_bdev_ops;
#ifdef SWAPZ_ROUND109_AREA_PREFLIGHT_TEST
static const struct file_operations other_fops = {1};
static int other_ops;
#endif
struct file {
	struct inode inode;
	struct block_device *bdev;
	const struct file_operations *f_op;
	unsigned f_mode;
	const void *f_mapping;
	unsigned references;
};
struct swap_info_struct {
	unsigned flags;
	const void *ops;
	struct block_device *bdev;
	struct file *swap_file;
	unsigned long max;
	u32 type;
};
static struct block_device device, foreign;
static struct file mapper, area, alternate;
static struct swap_info_struct entries[3];
static u64 epochs[3];
static unsigned swap_active_head;
static void (*before_lock)(void), (*after_unlock)(void);
static void spin_lock(int *lock)
{
	CHECK(lock == &swap_lock && !*lock);
	if (before_lock)
		before_lock();
	*lock = 1;
	++locks;
}
static void spin_unlock(int *lock)
{
	CHECK(lock == &swap_lock && *lock);
	*lock = 0;
	++unlocks;
	if (after_unlock)
		after_unlock();
}
#define plist_for_each_entry(si, head, member) \
	for (CHECK_LIST(head), (si) = entries; (si) < entries + *(head); ++(si))
static void CHECK_LIST(const unsigned *head) { CHECK(swap_lock && head == &swap_active_head && *head <= 3); }
static struct inode *file_inode(struct file *file) { CHECK(file); return &file->inode; }
static struct block_device *file_bdev(struct file *file)
{
	CHECK(file && file->f_op == &def_blk_fops && !(file->f_mode & FMODE_PATH));
	++file_reads;
	return file->bdev;
}
static bool bdev_is_partition(struct block_device *bdev) { CHECK(bdev); return bdev->partition; }
static __attribute__((unused)) bool bdev_read_only(struct block_device *bdev)
{
	CHECK(swap_lock);
	return bdev->read_only;
}
static u64 swapz_mm_trial_area_epoch(u32 type)
{
	CHECK(swap_lock && type < 3);
	++epoch_reads;
	return epochs[type];
}
static void get_file(struct file *file) { CHECK(swap_lock && file); ++file->references; ++gets; }
static void fput(struct file *file) { CHECK(!swap_lock && file->references > 1); --file->references; ++puts_count; }

#include "actual-area.h"

static void reset(void)
{
	CHECK(!swap_lock);
	device = (struct block_device){1024, false, false};
	foreign = device;
	mapper = (struct file){{S_IFBLK}, &device, &def_blk_fops, 0, &device, 1};
	area = mapper;
	alternate = (struct file){{S_IFBLK}, &foreign, &def_blk_fops, 0, &foreign, 1};
	entries[0] = (struct swap_info_struct){SWP_WRITEOK, &swap_bdev_ops, &device, &area, 128, 0};
	entries[1] = (struct swap_info_struct){SWP_WRITEOK, &swap_bdev_ops, &foreign, &alternate, 128, 1};
	entries[2] = entries[0];
	epochs[0] = 41;
	epochs[1] = 91;
	epochs[2] = 101;
	swap_active_head = 1;
	before_lock = after_unlock = NULL;
}
static void historical(void)
{
	u32 type = 99;
	u64 epoch = 99;
	struct file *owned = NULL;
	unsigned before = gets, released = puts_count;
	CHECK(!swapz_mm_trial_area_get(&mapper, 8, 128, &type, &epoch, &owned));
	CHECK(type == 0 && epoch == 41 && owned == &area);
	CHECK(gets == before + 1 && area.references == 2);
	fput(owned);
	CHECK(puts_count == released + 1 && area.references == 1);
	entries[0].flags = 0;
	CHECK(swapz_mm_trial_area_get(&mapper, 8, 128, &type, &epoch, &owned) == -ESTALE);
	CHECK(gets == before + 1 && area.references == 1 && !swap_lock);
}
#ifdef SWAPZ_ROUND109_AREA_PREFLIGHT_TEST
static void query(struct file *file, sector_t first, sector_t count, int expected, u32 type, u64 epoch)
{
	struct swapz_mm_trial_area_identity identity = {99, 999};
	unsigned before = gets, released = puts_count;
	CHECK(swapz_mm_trial_area_preflight(file, first, count, &identity) == expected);
	CHECK(identity.swap_type == type && identity.area_epoch == epoch);
	CHECK(!swap_lock && locks == unlocks);
	CHECK(gets == before && puts_count == released);
	CHECK(mapper.references == 1 && area.references == 1 && alternate.references == 1);
}
static void invalid(void)
{
	unsigned reads = file_reads, before = locks;
	query(NULL, 8, 8, -EINVAL, 0, 0);
	CHECK(swapz_mm_trial_area_preflight(&mapper, 8, 8, NULL) == -EINVAL);
	mapper.inode.i_mode = S_IFREG;
	query(&mapper, 8, 8, -EINVAL, 0, 0);
	mapper.inode.i_mode = S_IFBLK;
	mapper.f_op = &other_fops;
	query(&mapper, 8, 8, -EINVAL, 0, 0);
	mapper.f_op = &def_blk_fops;
	mapper.f_mode = FMODE_PATH;
	query(&mapper, 8, 8, -EINVAL, 0, 0);
	mapper.f_mode = 0;
	query(&mapper, 0, 8, -EINVAL, 0, 0);
	query(&mapper, 1, 8, -EINVAL, 0, 0);
	query(&mapper, 8, 0, -EINVAL, 0, 0);
	query(&mapper, 8, 7, -EINVAL, 0, 0);
	query(&mapper, 8, 136, -EINVAL, 0, 0);
	query(&mapper, UINT64_MAX - 7, 8, -EINVAL, 0, 0);
	CHECK(reads == file_reads && before == locks);
	device.partition = true;
	query(&mapper, 8, 8, -EINVAL, 0, 0);
	device.partition = false;
	mapper.bdev = NULL;
	query(&mapper, 8, 8, -EINVAL, 0, 0);
	CHECK(before == locks);
}
static void range(void)
{
	query(&mapper, 8, 128, 0, 0, 41);
	query(&mapper, 896, 128, 0, 0, 41);
	query(&mapper, 904, 128, -ESTALE, 0, 0);
	query(&mapper, 1024, 8, -ESTALE, 0, 0);
	device.bd_nr_sectors = 80;
	query(&mapper, 72, 8, 0, 0, 41);
	query(&mapper, 72, 16, -ESTALE, 0, 0);
	query(&mapper, 80, 8, -ESTALE, 0, 0);
	device.bd_nr_sectors = 0;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	device.bd_nr_sectors = 1024;
	entries[0].max = 4;
	query(&mapper, 24, 8, 0, 0, 41);
	query(&mapper, 24, 16, -ESTALE, 0, 0);
	query(&mapper, 32, 8, -ESTALE, 0, 0);
}
static void mismatch(void)
{
	device.read_only = true;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	device.read_only = false;
	entries[0].ops = &other_ops;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	entries[0].ops = &swap_bdev_ops;
	entries[0].bdev = &foreign;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	entries[0].bdev = &device;
	entries[0].swap_file = NULL;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	entries[0].swap_file = &area;
	area.inode.i_mode = S_IFREG;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	area.inode.i_mode = S_IFBLK;
	area.f_op = &other_fops;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	area.f_op = &def_blk_fops;
	area.f_mapping = &foreign;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	area.f_mapping = &device;
	entries[0].flags = 0;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	entries[0].flags = SWP_WRITEOK;
	epochs[0] = 0;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	epochs[0] = 42;
	swap_active_head = 0;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	swap_active_head = 2;
	entries[0] = entries[1];
	entries[1] = entries[2];
	entries[1].type = 2;
	query(&mapper, 8, 8, 0, 2, 101);
}
static void offline(void)
{
	CHECK(!swap_lock);
	entries[0].flags = 0;
	epochs[0] = 0;
	swap_active_head = 0;
}
static void races(void)
{
	before_lock = offline;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	reset();
	after_unlock = offline;
	query(&mapper, 8, 8, 0, 0, 41);
	CHECK(!epochs[0] && !swap_active_head);
	after_unlock = NULL;
	query(&mapper, 8, 8, -ESTALE, 0, 0);
	reset();
	epochs[0] = 42;
	query(&mapper, 8, 8, 0, 0, 42);
}
#endif
int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	reset();
	if (!strcmp(argv[1], "historical"))
		historical();
#ifdef SWAPZ_ROUND109_AREA_PREFLIGHT_TEST
	else if (!strcmp(argv[1], "invalid"))
		invalid();
	else if (!strcmp(argv[1], "range"))
		range();
	else if (!strcmp(argv[1], "mismatch"))
		mismatch();
	else if (!strcmp(argv[1], "races"))
		races();
#endif
	else
		return 2;
	CHECK(!swap_lock && locks == unlocks && gets == puts_count);
	printf("R109_A11_HOST_ONLY mode=%s checks=%u AUTH0\n", argv[1], checks);
	return 0;
}
