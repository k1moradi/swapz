/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual extracted controller/target transitions; serial dependency model only. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
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
#define SWAPZ_ROUND104_INTEGRATION_TEST
#define SWAPZ_OBSERVATION_MAX_RECORDS 8192U
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_SHARED_ORIGINAL_CAPACITY 8U
#define EXPORT_SYMBOL_GPL(name)
#define DEFINE_MUTEX(name) int name
#define WARN_ON_ONCE(expr) ((void)(expr))
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
struct target_type { unsigned unused; };
struct module { unsigned refs; bool going; };
struct swapz_shared_original_record {
	void *decoder;
	unsigned pins;
	bool is_current;
	struct { u32 logical_page; } spec;
};
struct fake_storage_owner {
	struct swapz_shared_original_record records[8];
	struct { u64 id; } pins[8];
};
struct swapz_shared_storage_decoder {
	struct { struct fake_storage_owner owner; void *pending_decoder; } storage;
};
struct swapz_trial_observation_scope {
	u64 session, epoch, target_epoch, registration_epoch;
	u32 first_logical, page_count;
};
struct swapz_observation_record { u64 sequence; u32 event; };
typedef int (*swapz_trial_target_install)(void *, const struct swapz_mm_trial_scope *, struct file *, u64);
typedef bool (*swapz_trial_observation_join)(void *);
#include "actual-retained-type.h"
struct swapz_dm {
	struct dm_target *target;
	int queue_lock, ordered_owner, original_registry;
	struct swapz_mm_trial_scope original_scope;
	struct swapz_trial_retained_scope original_retained_scope;
	struct file *original_scope_file;
	bool original_scope_mm_revoked, original_scope_final_retirement;
	int original_scope_finish_error;
	struct swapz_shared_storage_decoder *original_gated_storage;
	struct { void *original; bool gc_allocation, in_flight, batch_pending; } authority;
	struct { bool active; } gc_recovery;
	struct swapz_ticket_cap original_release_ref;
	struct swapz_round089_route original_route;
	struct swapz_ticket_cap original_cap, original_retired_cap;
	u64 original_scope_used_session, original_snapshot_epoch, original_owner_session, original_owner_epoch;
	u32 original_generations[16]; u64 logical_pages, io_failures;
	int original_scope_stop_error, original_teardown_error, last_error, original_release_busy;
	bool original_scope_capture_stopped, accepting, failed, original_trial, original_storage_ready;
	bool original_target_drained, original_owner_closing, original_listed;
	struct work_struct original_cap_release_work, original_teardown_work;
};
struct dm_target { struct swapz_dm *private; struct target_type *type; };
static struct module module_owner;
#define THIS_MODULE (&module_owner)
static struct swapz_dm *live;
static unsigned record_retire_calls;
static int record_retire_error;
static unsigned checks, calls, loss, byte_loss, close_calls, work_calls, sequence_calls, byte_calls, recorder_starts, binds, publishes, joins, revokes, retires, seals;
static bool mm_stopped, route_live = true, mm_matches = true, mm_published, recorder_active, external_ready, owner_retired, exact_match = true, byte_bind_ok = true;
static bool byte_result = true, append_result = true, retire_result = true;
static u64 appended_sequence = 71, received_sequence;
static u8 copied[SWAPZ_BLOCK_BYTES];
static struct file *published_mapper;
static struct swapz_mm_trial_scope published_scope;
static unsigned exact_calls, fail_exact_at;
static struct file *actual_area;
static u64 actual_epoch=9;
static u64 mm_identity = 43;
static int mm_error;
static int swapz_round090_registry_mutex;
#define CHECK(condition) do { ++checks; assert(condition); } while (0)
static bool try_module_get(struct module *owner)
{
	if (!owner || owner->going) return false;
	++owner->refs;
	return true;
}
static void module_put(struct module *owner)
{
	CHECK(owner && owner->refs == 1);
	--owner->refs;
}
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
	CHECK(!live->queue_lock);
	if (identity!=mm_identity) return -ESTALE;
	if (mm_error) return mm_error;
	if (mm_stopped) return -EALREADY;
	mm_stopped=true;
	return 0;
}
static bool swapz_trial_observation_active(void) { return recorder_active; }
static bool swapz_trial_observation_append(const struct swapz_observation_record *record)
{ CHECK(!record); ++loss; return false; }
static u64 swapz_trial_observation_append_sequence(const struct swapz_observation_record *record)
{ CHECK(record && !record->sequence); ++sequence_calls; return append_result ? appended_sequence : 0; }
static bool swapz_trial_byte_event(const struct swapz_observation_record *record, u64 sequence, const void *bytes, size_t length)
{
	CHECK(record && !record->sequence);
	++byte_calls; received_sequence=sequence;
	if (bytes) { CHECK(length==sizeof(copied)); memcpy(copied, bytes, length); }
	else CHECK(!length);
	return byte_result;
}
static void swapz_trial_byte_invalidate(void) { ++byte_loss; }
static int swapz_mm_trial_area_get(struct file *file, sector_t first, sector_t count,
		u32 *type, u64 *epoch, struct file **area)
{
	CHECK(!live->queue_lock && file && first==8 && count==8);
	*type=1; *epoch=actual_epoch; *area=actual_area; get_file(*area); return 0;
}
static bool swapz_trial_observation_start(const struct swapz_trial_observation_scope *scope, size_t capacity)
{ CHECK(!live->queue_lock && scope && capacity==64 && !recorder_active); ++recorder_starts; recorder_active=true; return true; }
static bool swapz_trial_byte_bind_scope(u64 identity, u32 type, u64 epoch)
{ CHECK(recorder_active && !mm_published && identity==43 && type==1 && epoch==9); ++binds; return byte_bind_ok; }
static int swapz_mm_trial_scope_publish(const struct swapz_mm_trial_scope *scope, struct file *mapper)
{ CHECK(binds==1 && recorder_active && !mm_published); ++publishes; mm_published=true; published_scope=*scope; published_mapper=mapper; get_file(mapper); return 0; }
static bool swapz_mm_trial_scope_matches_exact(const struct swapz_mm_trial_scope *scope, const struct file *mapper)
{
	++exact_calls;
	return exact_match && exact_calls!=fail_exact_at && mm_published && !mm_stopped &&
		scope->identity==published_scope.identity && scope->session==published_scope.session &&
		scope->table_epoch==published_scope.table_epoch && scope->target_epoch==published_scope.target_epoch &&
		scope->area_epoch==published_scope.area_epoch && scope->swap_type==published_scope.swap_type &&
		scope->first_sector==published_scope.first_sector && scope->sector_count==published_scope.sector_count &&
		scope->broker==published_scope.broker && scope->bdev==published_scope.bdev && mapper==published_mapper;
}
static int swapz_mm_trial_scope_join_external(u64 identity, u64 session, u64 epoch, u64 target_epoch)
{
	++joins; CHECK(mm_stopped && recorder_active && !live->queue_lock);
	if (identity!=43 || session!=7 || epoch!=7 || target_epoch!=8) return -ESTALE;
	return external_ready ? 0 : -EBUSY;
}
static int swapz_mm_trial_scope_revoke(u64 identity)
{
	CHECK(external_ready && mm_stopped && mm_published && identity==43 && recorder_active);
	++revokes; mm_published=false; fput(published_mapper); published_mapper=NULL; return 0;
}
static int swapz_mm_broker_owner_retired(u64 session, u64 epoch)
{
	++retires; CHECK(!mm_published && session==7 && epoch==7);
	return !live->original_cap.broker && owner_retired && retire_result ? 0 : -EBUSY;
}
static bool swapz_trial_observation_stop(swapz_trial_observation_join join, void *context)
{ CHECK(recorder_active && !mm_published && !live->original_cap.broker); ++seals; if (!join(context)) return false; recorder_active=false; return true; }
static bool swapz_round097_target_debt_free(const struct swapz_dm *ctx) { return !ctx->original_cap.broker && !ctx->original_retired_cap.broker && !ctx->original_gated_storage; }
static int swapz_round094_close_owner(struct swapz_dm *ctx, struct swapz_ticket_cap *cap, bool finish)
{ CHECK(!live->queue_lock && !mm_published && !finish); ++close_calls; ctx->original_owner_closing=true; *cap=(struct swapz_ticket_cap){}; return 0; }
static int swapz_round094_close_storage(struct swapz_dm *ctx)
{
	CHECK(ctx->ordered_owner);
	if (ctx->original_gated_storage) {
		for (unsigned i=0;i<8;++i)
			if (ctx->original_gated_storage->storage.owner.records[i].decoder)
				return -EBUSY;
	}
	++close_calls; ctx->original_gated_storage=NULL; ctx->original_storage_ready=false; ctx->authority.original=NULL; return 0;
}
/* Authority mutation substitute. Real target retirement function checks
 * every record/pin and calls these only after exact external join/revoke. */
static int swapz_prevalidate_discard_range(void *authority, u32 logical, u32 count)
{
	CHECK(authority==&live->authority && live->ordered_owner && external_ready &&
	      !mm_published && live->original_scope_mm_revoked &&
	      live->original_scope_final_retirement && logical==1 && count==1);
	return record_retire_error;
}
static int swapz_discard_page(void *authority, u32 logical)
{
	CHECK(authority==&live->authority && live->ordered_owner && !mm_published &&
	      live->original_scope_final_retirement && logical==1);
	++record_retire_calls;
	live->original_gated_storage->storage.owner.records[0]=(struct swapz_shared_original_record){0};
	return 0;
}
static int swapz_round097_finish_owner(struct swapz_dm *ctx) { CHECK(!ctx->original_cap.broker && !ctx->original_retired_cap.broker); ++close_calls; ctx->original_owner_session=0; ctx->original_owner_epoch=0; ctx->original_owner_closing=false; owner_retired=true; return 0; }
static void swapz_round090_cap_release_work(struct work_struct *);
static void swapz_round094_teardown_work(struct work_struct *);
static int swapz_ticket_broker_put(struct swapz_ticket_cap *cap) { *cap=(struct swapz_ticket_cap){}; return 0; }
static void queue_work(int queue, struct work_struct *work)
{
	(void)queue; ++work_calls; CHECK(!live->queue_lock);
	if (work==&live->original_cap_release_work) swapz_round090_cap_release_work(work);
	else { CHECK(work==&live->original_teardown_work); swapz_round094_teardown_work(work); }
}
static void flush_work(struct work_struct *work) { (void)work; }
#include "actual-controller-target.h"
int main(int argc, char **argv)
{
	struct block_device device={.sectors=128};
	struct file mapper={.inode={1},.bdev=&device,.refs=1}, area={.inode={1},.bdev=&device,.refs=1};
	struct swapz_shared_storage_decoder storage={0};
	struct swapz_dm ctx={.accepting=true,.original_trial=true,.original_storage_ready=true,
		.original_route={7,7,8,11},.original_snapshot_epoch=11,.logical_pages=17,
		.original_cap={&device,7,7},.original_owner_session=7,.original_owner_epoch=7,
		.original_gated_storage=&storage,.authority.original=&storage.storage.owner};
	struct dm_target ti={.private=&ctx,.type=&swapz_target};
	struct swapz_trial_target_ops wrong_ops=swapz_scope_target_ops;
	struct swapz_trial_retained_scope key={43,7,7,8,11};
	struct swapz_mm_trial_scope scope={.bdev=&device,.broker=&device,.identity=43,
		.session=7,.table_epoch=7,.target_epoch=8,.area_epoch=9,.first_sector=8,.sector_count=8,.swap_type=1};
	struct swapz_trial_observation_scope observation={7,7,8,11,1,1};
	const struct swapz_observation_record event={.event=3};
	u8 input[SWAPZ_BLOCK_BYTES];
	unsigned long flags;
	const char *mode=argc>1 ? argv[1] : "normal";
	ctx.target=&ti; live=&ctx; actual_area=&area;
	CHECK(swapz_trial_controller_stop_capture(0)==-EINVAL);
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ENODEV);
	CHECK(swapz_trial_target_register(NULL)==-EINVAL);
	CHECK(swapz_trial_target_register(&swapz_scope_target_ops)==0);
	CHECK(swapz_trial_target_register(&swapz_scope_target_ops)==-EBUSY);
	CHECK(swapz_trial_target_unregister(&wrong_ops)==-ESTALE);
	module_owner.going=true;
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ENODEV);
	module_owner.going=false;
	ti.type=NULL;
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-EINVAL);
	ti.type=&swapz_target;
	CHECK(!module_owner.refs && !recorder_starts && mapper.refs==1);
	actual_epoch=10;
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ESTALE);
	CHECK(mapper.refs==1 && area.refs==1 && !recorder_starts);
	actual_epoch=9;
	if (!strcmp(mode,"bind-failure")) byte_bind_ok=false;
	if (!strcmp(mode,"rollback") || !strcmp(mode,"rollback-recover")) fail_exact_at=2;
	int begin=swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti);
	CHECK(!module_owner.refs);
	CHECK(area.refs==1 && recorder_starts==1 && binds==1);
	if (!strcmp(mode,"bind-failure")) {
		CHECK(begin==-EIO && mapper.refs==2 && !publishes && !ctx.original_retained_scope.identity);
		CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-EALREADY);
		goto done;
	}
	if (!strcmp(mode,"rollback") || !strcmp(mode,"rollback-recover")) {
		CHECK(begin==-ESTALE && mapper.refs==3 && mm_stopped && mm_published);
		CHECK(!ctx.original_scope_file && !ctx.original_retained_scope.identity && !revokes && !seals);
		if (!strcmp(mode,"rollback-recover")) {
			CHECK(swapz_trial_controller_recover_uninstalled(&key)==-EBUSY && !revokes);
			external_ready=true;
			CHECK(swapz_trial_controller_recover_uninstalled(&key)==-EBUSY && revokes==1);
			CHECK(mapper.refs==2 && !mm_published && !seals);
			ctx.accepting=false; ctx.original_target_drained=true;
			ctx.original_snapshot_epoch=0; ctx.original_route=(struct swapz_round089_route){0};
			swapz_round090_unpublish_target(&ctx);
			queue_work(system_unbound_wq,&ctx.original_teardown_work);
			CHECK(swapz_trial_controller_recover_uninstalled(&key)==0 && mapper.refs==1 && seals==1);
		}
		goto done;
	}
	CHECK(begin==0 && mapper.refs==4 && exact_calls==2 && publishes==1);
	CHECK(ctx.original_retained_scope.identity==43 && ctx.original_scope_file==&mapper);
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ESTALE);
	memset(input,0x5a,sizeof(input));
	swapz_scope_observe_event(&event,input,sizeof(input));
	CHECK(sequence_calls==1 && byte_calls==1 && received_sequence==71 && !memcmp(input,copied,sizeof(input)));
	append_result=false;
	swapz_scope_observe_event(&event,NULL,0);
	CHECK(sequence_calls==2 && byte_calls==1 && byte_loss==1);
	append_result=true;
	byte_result=false;
	swapz_scope_observe_event(&event,NULL,0);
	CHECK(sequence_calls==3 && byte_calls==2 && byte_loss==2);
	byte_result=true;
	swapz_presuspend(&ti);
	CHECK(mm_stopped && calls==1 && ctx.original_scope_capture_stopped);
	spin_lock_irqsave(&ctx.queue_lock,flags);
	ctx.accepting=false;
	swapz_round089_revoke_route_locked(&ctx);
	ctx.original_snapshot_epoch=0;
	spin_unlock_irqrestore(&ctx.queue_lock,flags);
	CHECK(!ctx.original_scope.identity && ctx.original_retained_scope.identity==43);
	if (!strcmp(mode,"failure")) {
		swapz_fail_at(&ctx,-EIO,"test","lower","failure");
		swapz_fail_at(&ctx,-ENOMEM,"test","resource","repeat");
		CHECK(ctx.failed && ctx.last_error==-EIO && ctx.io_failures==1);
		CHECK(ctx.original_retained_scope.identity==43 && swapz_scope_finish_retained(&ctx)==-EBUSY);
		goto done;
	}
	ctx.original_listed=true;
	swapz_round090_unpublish_target(&ctx);
	CHECK(!ctx.original_listed && ctx.original_cap.broker && !work_calls);
	CHECK(swapz_scope_external_join_missing(&ctx) && !swapz_round096_target_can_free(&ctx,false));
	ctx.original_target_drained=true;
	CHECK(swapz_scope_finish_retained(&ctx)==-EBUSY && !revokes && !close_calls);
	CHECK(ctx.original_retained_scope.identity==43 && mapper.refs==4);
	if (!strcmp(mode,"final-live") || !strcmp(mode,"final-pinned") || !strcmp(mode,"final-error")) {
		struct swapz_trial_retained_scope stale=key;
		storage.storage.owner.records[0].decoder=&device;
		storage.storage.owner.records[0].is_current=true;
		storage.storage.owner.records[0].spec.logical_page=1;
		CHECK(swapz_scope_finish_retained(&ctx)==-EBUSY && !revokes && !record_retire_calls);
		stale.registration_epoch++;
		CHECK(swapz_trial_controller_retire_registered(&ti,&stale)==-ESTALE && !revokes);
		ti.type=NULL;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-ESTALE && !revokes);
		ti.type=&swapz_target;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && !revokes &&
		      !record_retire_calls && !ctx.original_scope_final_retirement);
		external_ready=true;
		ctx.original_target_drained=false;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && !revokes);
		ctx.original_target_drained=true;
		if (!strcmp(mode,"final-error")) record_retire_error=-EUCLEAN;
		if (!strcmp(mode,"final-pinned")) storage.storage.owner.records[0].pins=1;
		int retired=swapz_trial_controller_retire_registered(&ti,&key);
		CHECK(revokes==1 && ctx.original_scope_final_retirement && !module_owner.refs);
		if (!strcmp(mode,"final-error")) {
			CHECK(retired==-EUCLEAN && !record_retire_calls && !seals && ctx.original_cap.broker &&
			      ctx.original_retained_scope.identity==43 && ctx.original_scope_finish_error==-EUCLEAN);
			record_retire_error=0;
			CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EUCLEAN && !record_retire_calls);
			goto done;
		}
		if (!strcmp(mode,"final-pinned")) {
			CHECK(retired==-EBUSY && !record_retire_calls && !seals && ctx.original_cap.broker);
			CHECK(swapz_scope_finish_retained(&ctx)==-EBUSY && ctx.original_cap.broker);
			storage.storage.owner.records[0].pins=0;
			retired=swapz_trial_controller_retire_registered(&ti,&key);
		}
		CHECK(retired==0 && record_retire_calls==1 && mapper.refs==1 && seals==1 &&
		      swapz_round096_target_can_free(&ctx,false));
		goto done;
	}
	external_ready=true;
	if (!strcmp(mode,"typed-debt")) {
		storage.storage.owner.records[0].decoder=&device;
		CHECK(swapz_scope_finish_retained(&ctx)==-EBUSY && !revokes && !close_calls);
		CHECK(ctx.original_retained_scope.identity==43 && mapper.refs==4);
		goto done;
	}
	if (!strcmp(mode,"wrong-key")) {
		struct swapz_trial_retained_scope wrong=ctx.original_retained_scope;
		wrong.registration_epoch++;
		CHECK(swapz_trial_controller_join_external(&wrong)==-ESTALE && !revokes);
	}
	if (!strcmp(mode,"retirement-busy")) retire_result=false;
	int finish=swapz_scope_finish_retained(&ctx);
	CHECK(revokes==1 && !mm_published && !ctx.original_cap.broker && owner_retired);
	if (!strcmp(mode,"retirement-busy")) {
		CHECK(finish==-EBUSY && ctx.original_scope_mm_revoked && mapper.refs==3 && !seals);
		CHECK(ctx.original_retained_scope.identity==43 && !swapz_round096_target_can_free(&ctx,false));
		retire_result=true;
		finish=swapz_scope_finish_retained(&ctx);
	}
	CHECK(finish==0 && seals==1 && mapper.refs==1 && !recorder_active);
	CHECK(!ctx.original_retained_scope.identity && !ctx.original_scope_file && ctx.original_scope_used_session==7);
	CHECK(swapz_round096_target_can_free(&ctx,false));
done:
	CHECK(!module_owner.refs);
	CHECK(swapz_trial_target_unregister(&swapz_scope_target_ops)==0);
	CHECK(swapz_trial_target_unregister(&swapz_scope_target_ops)==-ESTALE);
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ENODEV);
	CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-ENODEV);
	printf("R105_A3_HOST_ONLY mode=%s checks=%u AUTH=0\n",mode,checks);
	return 0;
}
