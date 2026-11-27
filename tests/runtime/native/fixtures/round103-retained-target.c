/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual extracted target lifecycle; serial model for file/MM/DM/locks. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <errno.h>
typedef uint64_t u64;
typedef uint64_t sector_t;
typedef uint32_t u32;
typedef uint8_t u8;
#define U32_MAX UINT32_MAX
#define MAX_SWAPFILES 32U
#define SWAPZ_SECTORS 8U
#define SWAPZ_ROUND094_GENERATION_PAGES 16U
#define SWAPZ_TICKET_LZ4 1U
#define SWAPZ_ROUND088_SELECTED_DM_CANDIDATE_TEST
#define SWAPZ_ROUND098_SCOPED_TARGET_TEST
#define SWAPZ_ROUND102_CONTROLLER_TEST
#define SWAPZ_ROUND094_TARGET_OWNER_TEST
#define SWAPZ_ROUND097_GATED_TARGET_TEST
#define __maybe_unused
#define __used
#define noinline
struct block_device { sector_t sectors; bool partition; };
struct inode { int i_mode; };
struct file { struct inode inode; struct block_device *bdev; unsigned refs; };
struct swapz_ticket_cap { void *broker; u64 session, epoch; };
struct swapz_mm_trial_scope {
	struct block_device *bdev; void *broker;
	u64 identity, session, table_epoch, target_epoch, area_epoch;
	sector_t first_sector, sector_count; u32 swap_type;
};
struct swapz_mm_route { void *broker; u64 target_session, table_epoch, target_epoch, logical_page, dm_generation; };
struct swapz_round089_route { u64 broker_session, table_epoch, target_epoch, registration_epoch; };
struct work_struct { int placeholder; };
struct dm_target;
#include "actual-retained-type.h"
struct swapz_dm {
	struct dm_target *target;
	int queue_lock, ordered_owner, original_registry;
	struct swapz_mm_trial_scope original_scope;
	struct swapz_trial_retained_scope original_retained_scope;
	struct file *original_scope_file;
	struct swapz_round089_route original_route;
	struct swapz_ticket_cap original_cap, original_retired_cap;
	u64 original_scope_used_session, original_snapshot_epoch, original_owner_session, original_owner_epoch;
	u32 original_generations[16]; u64 logical_pages, io_failures;
	int original_scope_stop_error, original_teardown_error, last_error, original_release_busy;
	bool original_scope_capture_stopped, accepting, failed, original_trial, original_storage_ready;
	bool original_target_drained, original_owner_closing, original_listed;
	struct work_struct original_cap_release_work, original_teardown_work;
};
struct dm_target { struct swapz_dm *private; };
static struct swapz_dm *live;
static unsigned checks, calls, loss, close_calls, work_calls;
static bool mm_stopped, route_live = true, mm_matches = true;
static u64 mm_identity = 43;
static int mm_error;
static int swapz_round090_registry_mutex;
#define CHECK(condition) do { ++checks; assert(condition); } while (0)
#define spin_lock_irqsave(lock, flags) do { CHECK(!*(lock)); *(lock)=1; (flags)=0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { CHECK(*(lock)); *(lock)=0; (void)(flags); } while (0)
#define lockdep_assert_held(lock) CHECK(*(lock))
#define WRITE_ONCE(dst, src) ((dst)=(src))
#define smp_store_release(dst, src) (*(dst)=(src))
#define DMERR(...) do { if (0) printf(__VA_ARGS__); } while (0)
#define container_of(ptr, type, member) ((type *)((char *)(ptr)-offsetof(type,member)))
#define atomic_read(ptr) (*(ptr))
#define mutex_lock(ptr) do { CHECK(!*(ptr)); *(ptr)=1; } while (0)
#define mutex_unlock(ptr) do { CHECK(*(ptr)); *(ptr)=0; } while (0)
#define list_del_rcu(ptr) ((void)(ptr))
#define INIT_LIST_HEAD(ptr) ((void)(ptr))
#define synchronize_rcu() CHECK(!live->queue_lock)
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
#define S_ISBLK(mode) ((mode)==1)
#define system_unbound_wq 0
static struct inode *file_inode(struct file *file) { return &file->inode; }
static struct block_device *file_bdev(struct file *file) { return file->bdev; }
static bool bdev_is_partition(struct block_device *bdev) { return bdev->partition; }
static sector_t bdev_nr_sectors(struct block_device *bdev) { return bdev->sectors; }
static void get_file(struct file *file) { CHECK(!live->queue_lock); ++file->refs; }
static void fput(struct file *file) { CHECK(!live->queue_lock && file->refs>0); --file->refs; }
static bool dm_swapz_round090_route_live(struct dm_target *target, struct block_device *bdev, sector_t sector)
{ return route_live && target==live->target && bdev && sector==8; }
static bool swapz_mm_trial_scope_matches_route(struct block_device *bdev, sector_t sector, u64 area, u32 type, u8 codec, u32 length, const struct swapz_mm_route *route)
{ return mm_matches && bdev && sector==8 && area==9 && type==1 && codec==1 && length==1 && route->target_session==7 && route->table_epoch==7 && route->target_epoch==8 && route->logical_page==1 && route->dm_generation==1; }
static int swapz_mm_trial_scope_stop_capture(u64 identity)
{
	++calls;
	CHECK(!live->queue_lock && live->original_scope_capture_stopped);
	if (identity!=mm_identity) return -ESTALE;
	if (mm_error) return mm_error;
	if (mm_stopped) return -EALREADY;
	mm_stopped=true;
	return 0;
}
static void swapz_scope_observe_invalid(void) { ++loss; }
static bool swapz_round097_target_debt_free(const struct swapz_dm *ctx) { return !ctx->original_cap.broker && !ctx->original_retired_cap.broker; }
static int swapz_round094_close_owner(struct swapz_dm *ctx, struct swapz_ticket_cap *cap, bool finish)
{ (void)ctx; (void)cap; (void)finish; ++close_calls; return -EIO; }
static int swapz_round094_close_storage(struct swapz_dm *ctx) { (void)ctx; ++close_calls; return -EIO; }
static int swapz_round097_finish_owner(struct swapz_dm *ctx) { (void)ctx; ++close_calls; return -EIO; }
static void queue_work(int queue, struct work_struct *work) { (void)queue; (void)work; ++work_calls; }
static void flush_work(struct work_struct *work) { (void)work; }
#include "actual-retained-lifecycle.h"
int main(int argc, char **argv)
{
	struct block_device device = {.sectors=128}, other = {.sectors=128};
	struct file mapper = {.inode={1}, .bdev=&device, .refs=1};
	struct swapz_dm ctx = {.accepting=true,.original_trial=true,.original_storage_ready=true,
		.original_route={7,7,8,11},.original_snapshot_epoch=11,.logical_pages=17,
		.original_cap={&device,7,7},.original_owner_session=7,.original_owner_epoch=7};
	struct dm_target ti = {.private=&ctx};
	struct swapz_mm_trial_scope scope = {.bdev=&device,.broker=&device,.identity=43,
		.session=7,.table_epoch=7,.target_epoch=8,.area_epoch=9,.first_sector=8,.sector_count=8,.swap_type=1};
	ctx.target=&ti; live=&ctx;
	CHECK(swapz_trial_controller_stop_capture(0)==-EINVAL);
	swapz_presuspend(&ti);
	CHECK(calls==0 && !swapz_scope_external_join_missing(&ctx));
	mapper.bdev=&other;
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==-EINVAL && mapper.refs==1);
	mapper.bdev=&device;
	mm_matches=false;
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==-ESTALE && mapper.refs==1);
	CHECK(!ctx.original_retained_scope.identity && !ctx.original_scope_file);
	mm_matches=true;
	scope.target_epoch=99;
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==-ESTALE && mapper.refs==1);
	scope.target_epoch=8;
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==0 && mapper.refs==2);
	CHECK(ctx.original_retained_scope.identity==43 && ctx.original_retained_scope.session==7 &&
	      ctx.original_retained_scope.epoch==7 && ctx.original_retained_scope.target_epoch==8 &&
	      ctx.original_retained_scope.registration_epoch==11 && ctx.original_scope_file==&mapper);
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==-ESTALE && mapper.refs==2);
	/* Real failure/revoke erases routing snapshot. The previous R102
	 * teardown gate then falsely succeeded. Now it must retain debt. */
	if (argc>1 && argv[1][0]=='f')
		swapz_fail_at(&ctx,-EIO,"test","lower","fail");
	else {
		unsigned long flags;
		spin_lock_irqsave(&ctx.queue_lock,flags);
		swapz_round089_revoke_route_locked(&ctx);
		spin_unlock_irqrestore(&ctx.queue_lock,flags);
	}
	CHECK(!ctx.original_scope.identity && !ctx.original_route.registration_epoch);
	CHECK(ctx.original_retained_scope.identity==43 && mapper.refs==2);
	CHECK(swapz_scope_external_join_missing(&ctx));
	mm_error=-EBUSY; swapz_presuspend(&ti);
	CHECK(calls==1 && loss==1 && ctx.original_scope_stop_error==-EBUSY);
	mm_error=0; mm_identity=44; swapz_scope_stop_capture(&ctx);
	CHECK(calls==2 && loss==2 && ctx.original_scope_stop_error==-EBUSY);
	mm_identity=43; swapz_scope_stop_capture(&ctx);
	swapz_scope_stop_capture(&ctx);
	CHECK(calls==4 && mm_stopped && loss==2 && ctx.original_scope_stop_error==-EBUSY);
	ctx.original_listed=true;
	swapz_round090_unpublish_target(&ctx);
	CHECK(!ctx.original_listed && ctx.original_cap.broker==&device && !work_calls);
	ctx.original_target_drained=true;
	swapz_round094_teardown_work(&ctx.original_teardown_work);
	CHECK(!close_calls && ctx.original_teardown_error==-EBUSY);
	CHECK(!swapz_round096_target_can_free(&ctx,false));
	CHECK(swapz_scope_external_join_missing(&ctx));
	CHECK(swapz_scope_install(&ctx,&scope,&mapper)==-ESTALE && mapper.refs==2);
	printf("R103_A3_RETAINED_HOST_ONLY checks=%u AUTH=0\n",checks);
	return 0;
}
