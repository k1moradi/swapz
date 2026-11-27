/* SPDX-License-Identifier: GPL-2.0-only */
/* R107 actual extracted cold preflight and R106 terminal regressions; serial dependency model only. */
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
#define SWAPZ_OBS_CLEANUP 27U
struct swapz_observation_record {
	u64 sequence;
	u32 event, flags, caps, tickets, pins, reservations, bios, maps, quarantines;
};
#include "actual-mm-terminal-type.h"
typedef int (*swapz_trial_target_install)(void *, const struct swapz_mm_trial_scope *, struct file *, u64);
typedef bool (*swapz_trial_observation_join)(void *);
#include "actual-retained-type.h"
struct swapz_dm {
	void *original_storage;
	struct dm_target *target;
	int queue_lock, ordered_owner, original_registry;
	struct swapz_mm_trial_scope original_scope;
	struct swapz_trial_retained_scope original_retained_scope;
	struct file *original_scope_file;
	bool original_scope_mm_revoked, original_scope_final_retirement;
	u32 original_scope_first_logical, original_scope_page_count;
	int original_scope_finish_error;
	struct swapz_shared_storage_decoder *original_gated_storage;
	struct { void *original; bool gc_allocation, in_flight, batch_pending; unsigned abandoned_blocks; } authority;
	struct { bool valid; } maps[17];
	void *observation_commit;
	u64 observation_release_operation, observation_release_descriptor, observation_read_operation, observation_read_extent;
	bool submitter_dispatch_active;
	unsigned batch_count;
	int lower_write_active, completion_active;
	int deferred_upper_completions, completion_bios;
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
static struct block_device *live_route_bdev;
static sector_t missing_route_sector;
static unsigned module_gets, module_puts, route_queries, area_gets, file_gets, file_puts;
static unsigned record_retire_calls, detaches, snapshots, cleanup_attempts, cleanup_forwarded;
static bool mm_detached, seal_fail;
static int detach_error;
static struct file *retired_mapper;
static struct swapz_mm_trial_terminal_snapshot observed_mm;
static int swapz_controller_lock, swapz_target_ops_lock;
#define bio_list_empty(list) (!*(list))
static bool swapz_has_inflight(const struct swapz_dm *ctx) { return ctx->authority.in_flight; }
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
	++module_gets;
	return true;
}
static void module_put(struct module *owner)
{
	CHECK(owner && owner->refs == 1);
	--owner->refs;
	++module_puts;
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
static void get_file(struct file *file) { CHECK(!live->queue_lock); ++file_gets; ++file->refs; }
static void fput(struct file *file)
{
	CHECK(!live->queue_lock && file->refs>0);
	if (mm_detached && file == retired_mapper)
		CHECK(!swapz_controller_lock && !swapz_target_ops_lock && !live->ordered_owner);
	++file_puts;
	--file->refs;
}
static bool dm_swapz_round090_route_live(struct dm_target *target, struct block_device *bdev, sector_t sector)
{
	++route_queries;
	CHECK(live->queue_lock);
	return route_live && target==live->target && bdev==live_route_bdev &&
	       sector && !(sector%SWAPZ_SECTORS) && sector<bdev->sectors &&
	       sector!=missing_route_sector;
}
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
{
	CHECK(record && !record->sequence);
	++sequence_calls;
	if (record->event == SWAPZ_OBS_CLEANUP) {
		CHECK(!cleanup_attempts && mm_detached && revokes==1 && owner_retired && !live->original_cap.broker);
		CHECK(record->flags==7 && !record->caps && !record->tickets && !record->pins &&
		      !record->reservations && !record->bios && !record->maps && !record->quarantines);
		++cleanup_attempts;
	}
	return append_result ? appended_sequence : 0;
}
static bool swapz_trial_byte_event(const struct swapz_observation_record *record, u64 sequence, const void *bytes, size_t length)
{
	CHECK(record && !record->sequence);
	++byte_calls; received_sequence=sequence;
	if (record->event == SWAPZ_OBS_CLEANUP) { CHECK(cleanup_attempts==1 && !cleanup_forwarded && sequence==appended_sequence); ++cleanup_forwarded; }
	if (bytes) { CHECK(length==sizeof(copied)); memcpy(copied, bytes, length); }
	else CHECK(!length);
	return byte_result;
}
static void swapz_trial_byte_invalidate(void) { ++byte_loss; }
static int swapz_mm_trial_area_get(struct file *file, sector_t first, sector_t count,
		u32 *type, u64 *epoch, struct file **area)
{
	++area_gets;
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
static int swapz_mm_trial_scope_terminal_snapshot(u64 identity, u64 session, u64 epoch,
		u64 target_epoch, struct swapz_mm_trial_terminal_snapshot *snapshot)
{
	CHECK(swapz_controller_lock && mm_published && recorder_active);
	++snapshots;
	if (identity!=43 || session!=7 || epoch!=7 || target_epoch!=8)
		return -ESTALE;
	*snapshot = observed_mm;
	snapshot->files_detached = mm_detached;
	return 0;
}
static int swapz_mm_trial_scope_detach_files(u64 identity, u64 session, u64 epoch, u64 target_epoch)
{
	CHECK(!swapz_controller_lock && !swapz_target_ops_lock && !live->queue_lock &&
	      !live->ordered_owner && module_owner.refs==1);
	CHECK(identity==43 && session==7 && epoch==7 && target_epoch==8 && mm_published && external_ready);
	++detaches;
	if (detach_error) return detach_error;
	if (!mm_detached) {
		retired_mapper=published_mapper;
		mm_detached=true;
		fput(published_mapper);
	}
	return 0;
}
static int swapz_mm_trial_scope_revoke(u64 identity)
{
	CHECK(external_ready && mm_stopped && mm_published && mm_detached && identity==43 && recorder_active);
	++revokes; mm_published=false; published_mapper=NULL; return 0;
}
static int swapz_mm_broker_owner_retired(u64 session, u64 epoch)
{
	++retires; CHECK(!mm_published && session==7 && epoch==7);
	return !live->original_cap.broker && owner_retired && retire_result ? 0 : -EBUSY;
}
static bool swapz_trial_observation_stop(swapz_trial_observation_join join, void *context)
{
	CHECK(recorder_active && !mm_published && !live->original_cap.broker && mm_detached);
	++seals;
	if (!join(context)) return false;
	recorder_active=false;
	return !seal_fail;
}
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
	live->maps[logical].valid=false;
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
	struct block_device device={.sectors=136};
	struct file mapper={.inode={1},.bdev=&device,.refs=1}, area={.inode={1},.bdev=&device,.refs=1};
	struct swapz_shared_storage_decoder storage={0};
	struct swapz_dm ctx={.accepting=true,.original_trial=true,.original_storage_ready=true,
		.original_route={7,7,8,11},.original_snapshot_epoch=11,.logical_pages=17,
		.original_cap={&device,7,7},.original_owner_session=7,.original_owner_epoch=7,
		.original_gated_storage=&storage,.original_storage=&storage,.original_listed=true,
		.authority.original=&storage.storage.owner};
	struct dm_target ti={.private=&ctx,.type=&swapz_target};
	struct swapz_trial_target_ops wrong_ops=swapz_scope_target_ops;
	struct swapz_trial_retained_scope key={43,7,7,8,11};
	struct swapz_mm_trial_scope scope={.bdev=&device,.broker=&device,.identity=43,
		.session=7,.table_epoch=7,.target_epoch=8,.area_epoch=9,.first_sector=8,.sector_count=8,.swap_type=1};
	struct swapz_trial_observation_scope observation={7,7,8,11,1,1};
	const struct swapz_observation_record event={.event=3};
	struct file *early_mapper=NULL;
	unsigned long flags;
	const char *mode=argc>1 ? argv[1] : "clean";
	ctx.target=&ti; live=&ctx; actual_area=&area; live_route_bdev=&device;
	observed_mm=(struct swapz_mm_trial_terminal_snapshot){
		.area_epoch=9, .capture_stopped=true, .area_retired=true,
		.terminal_closed=true, .terminal_joined=true,
	};
	if (!strncmp(mode,"query-",6) || !strcmp(mode,"denied") || !strcmp(mode,"denied-invalid")) {
		struct swapz_trial_target_preflight result, zero={0};
		struct swapz_trial_target_ops missing_query=swapz_scope_target_ops;
		struct block_device wrong_device={.sectors=136};
		struct file wrong_mapper={.inode={1},.bdev=&wrong_device,.refs=1};
		struct file *selected_mapper=&mapper;
		struct dm_target *selected_target=&ti;
		const struct swapz_ticket_broker *expected=scope.broker;
		sector_t first=8, count=8;
		int expected_error=0;
		bool registered=false;
		missing_query.query=NULL;
		CHECK(swapz_trial_target_register(&missing_query)==-EINVAL);
		if (strcmp(mode,"query-unregistered")) {
			CHECK(swapz_trial_target_register(&swapz_scope_target_ops)==0);
			registered=true;
		}
		if (!strcmp(mode,"denied") || !strcmp(mode,"denied-invalid")) {
			/* Guard-on calls only: both valid-shaped and NULL arguments
			 * must be denied before any lock, module or reference use. */
			if (!strcmp(mode,"denied-invalid"))
				CHECK(swapz_trial_controller_begin_registered(NULL,NULL,NULL,0,NULL)==-EACCES);
			else
				CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-EACCES);
			CHECK(!module_gets && !module_puts && !route_queries && !area_gets);
		} else {
			if (!strcmp(mode,"query-unregistered")) expected_error=-ENODEV;
			if (!strcmp(mode,"query-unloading")) { module_owner.going=true; expected_error=-ENODEV; }
			if (!strcmp(mode,"query-null-target")) { selected_target=NULL; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-null-mapper")) { selected_mapper=NULL; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-wrong-target")) { ti.type=NULL; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-no-private")) { ti.private=NULL; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-wrong-context")) { ctx.target=NULL; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-no-table")) { route_live=false; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-wrong-mapper")) { selected_mapper=&wrong_mapper; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-partition")) { device.partition=true; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-nonblock")) { mapper.inode.i_mode=0; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-zero")) { count=0; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-unaligned")) { first=9; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-overflow")) { first=UINT64_MAX-7; expected_error=-EINVAL; }
			if (!strcmp(mode,"query-out-of-range")) { count=136; expected_error=-ERANGE; }
			if (!strcmp(mode,"query-logical-limit")) { ctx.logical_pages=1; expected_error=-ERANGE; }
			if (!strcmp(mode,"query-trial-limit")) { device.sectors=256; ctx.logical_pages=32; count=136; expected_error=-ERANGE; }
			if (!strcmp(mode,"query-stale-registration")) { ctx.original_route.registration_epoch++; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-stale-snapshot")) { ctx.original_snapshot_epoch++; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-stale-session")) { ctx.original_cap.session++; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-stale-cap")) { ctx.original_cap.epoch++; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-stale-route")) { ctx.original_route.table_epoch++; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-zero-target-epoch")) { ctx.original_route.target_epoch=0; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-zero-registration")) { ctx.original_route.registration_epoch=0; ctx.original_snapshot_epoch=0; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-wrong-broker")) { expected=(const struct swapz_ticket_broker *)(void *)&wrong_device; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-no-broker-hint")) expected=NULL;
			if (!strcmp(mode,"query-no-storage")) { ctx.original_storage=NULL; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-not-listed")) { ctx.original_listed=false; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-not-accepting")) { ctx.accepting=false; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-failed")) { ctx.failed=true; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-installed")) { ctx.original_scope.identity=43; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-consumed")) { ctx.original_scope_used_session=7; expected_error=-ESTALE; }
			if (!strcmp(mode,"query-full-range")) count=128;
			if (!strcmp(mode,"query-wrong-route")) { count=16; missing_route_sector=16; expected_error=-ESTALE; }
			memset(&result,0xa5,sizeof(result));
			CHECK(swapz_trial_controller_query_registered(selected_target,selected_mapper,expected,first,count,&result)==expected_error);
			if (expected_error)
				CHECK(!memcmp(&result,&zero,sizeof(result)));
			else {
				CHECK(result.session==7 && result.table_epoch==7 && result.target_epoch==8 &&
				      result.registration_epoch==11 && result.first_sector==first && result.sector_count==count);
				CHECK(route_queries==count/SWAPZ_SECTORS);
			}
			CHECK(module_gets==module_puts && !module_owner.refs);
			if (!strcmp(mode,"query-stale-install")) {
				/* Historical guard-off model: a successful snapshot cannot
				 * bypass actual validation after a route epoch change. */
				ctx.original_route.registration_epoch++;
				ctx.original_snapshot_epoch++;
				CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ESTALE);
			}
		}
		CHECK(!module_owner.refs && mapper.refs==1 && area.refs==1 && wrong_mapper.refs==1);
		CHECK(!file_gets && !file_puts && !area_gets && !recorder_starts && !binds && !publishes &&
		      !sequence_calls && !byte_calls && !loss && !byte_loss && !recorder_active &&
		      !swapz_controller_used && !swapz_controller_mapper && !swapz_controller_published &&
		      !swapz_controller_installed && !swapz_controller_registration && !swapz_controller_scope.identity);
		CHECK(!ctx.original_scope_file && !ctx.original_retained_scope.identity && !work_calls);
		if (registered)
			CHECK(swapz_trial_target_unregister(&swapz_scope_target_ops)==0);
		printf("R107_A3_HOST_ONLY mode=%s checks=%u AUTH=0\n",mode,checks);
		return 0;
	}
	CHECK(swapz_trial_controller_stop_capture(0)==-EINVAL);
	CHECK(swapz_trial_target_register(NULL)==-EINVAL);
	CHECK(swapz_trial_target_register(&swapz_scope_target_ops)==0);
	CHECK(swapz_trial_target_unregister(&wrong_ops)==-ESTALE);
	module_owner.going=true;
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==-ENODEV);
	module_owner.going=false;
	CHECK(swapz_trial_controller_begin_registered(&scope,&observation,&mapper,64,&ti)==0);
	CHECK(!module_owner.refs && mapper.refs==4 && area.refs==1);
	CHECK(ctx.original_retained_scope.identity==43 && ctx.original_scope_file==&mapper);
	swapz_scope_observe_event(&event,NULL,0);
	CHECK(sequence_calls==1 && byte_calls==1);
	swapz_presuspend(&ti);
	CHECK(mm_stopped && ctx.original_scope_capture_stopped);
	spin_lock_irqsave(&ctx.queue_lock,flags);
	ctx.accepting=false;
	swapz_round089_revoke_route_locked(&ctx);
	ctx.original_snapshot_epoch=0;
	spin_unlock_irqrestore(&ctx.queue_lock,flags);
	ctx.original_listed=true;
	swapz_round090_unpublish_target(&ctx);
	ctx.original_target_drained=true;
	CHECK(!ctx.original_scope.identity && ctx.original_cap.broker && !work_calls);
	CHECK(swapz_scope_external_join_missing(&ctx) && !swapz_round096_target_can_free(&ctx,false));
	CHECK(swapz_scope_finish_retained(&ctx,&early_mapper)==-EBUSY && !early_mapper);
	CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && !detaches && !revokes && !cleanup_attempts);
	external_ready=true;
	if (!strcmp(mode,"wrong-key")) {
		struct swapz_trial_retained_scope wrong=key;
		wrong.registration_epoch++;
		CHECK(swapz_trial_controller_retire_registered(&ti,&wrong)==-ESTALE && !detaches && !revokes);
	}
	if (!strcmp(mode,"wrong-area") || !strcmp(mode,"mm-fault")) {
		if (!strcmp(mode,"wrong-area")) observed_mm.area_epoch++;
		else observed_mm.fault=true;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==
		      (!strcmp(mode,"wrong-area") ? -ESTALE : -EUCLEAN));
		CHECK(!detaches && !revokes && !cleanup_attempts && mapper.refs==4 && byte_loss);
		goto done;
	}
	if (!strcmp(mode,"failed-target")) {
		swapz_fail_at(&ctx,-EIO,"test","lower","failure");
		swapz_fail_at(&ctx,-ENOMEM,"test","resource","repeat");
		CHECK(ctx.failed && ctx.last_error==-EIO && ctx.io_failures==1);
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && !detaches && !revokes);
		goto done;
	}
	if (!strcmp(mode,"mm-debt")) observed_mm.mm_callbacks=1;
	if (!strcmp(mode,"dm-debt")) observed_mm.dm_callbacks=1;
	if (!strcmp(mode,"entrant-debt")) observed_mm.dm_entrants=1;
	if (!strcmp(mode,"carrier-debt")) observed_mm.carrier_busy=true;
	if (!strcmp(mode,"area-busy")) observed_mm.area_retired=false;
	if (!strcmp(mode,"mm-debt") || !strcmp(mode,"dm-debt") ||
	    !strcmp(mode,"entrant-debt") || !strcmp(mode,"carrier-debt") || !strcmp(mode,"area-busy")) {
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY);
		CHECK(!detaches && !revokes && !cleanup_attempts && mapper.refs==4);
		observed_mm.mm_callbacks=observed_mm.dm_callbacks=observed_mm.dm_entrants=0;
		observed_mm.carrier_busy=false; observed_mm.area_retired=true;
	}
	if (!strcmp(mode,"detach-busy")) {
		detach_error=-EBUSY;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && detaches==1 && !revokes && mapper.refs==4);
		detach_error=0;
	}
	if (!strcmp(mode,"target-debt")) {
		ctx.authority.batch_pending=true;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && !detaches && !revokes);
		ctx.authority.batch_pending=false;
	}
	if (!strcmp(mode,"final-live") || !strcmp(mode,"final-pinned")) {
		storage.storage.owner.records[0].decoder=&device;
		storage.storage.owner.records[0].is_current=true;
		storage.storage.owner.records[0].spec.logical_page=1;
		ctx.maps[1].valid=true;
	}
	if (!strcmp(mode,"final-pinned")) {
		storage.storage.owner.records[0].pins=1;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && revokes==1 &&
		      mapper.refs==2 && !cleanup_attempts && !record_retire_calls && ctx.original_scope_final_retirement);
		storage.storage.owner.records[0].pins=0;
	}
	if (!strcmp(mode,"broker-busy") || !strcmp(mode,"early-finish")) {
		retire_result=false;
		CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-EBUSY && revokes==1 &&
		      mapper.refs==2 && !cleanup_attempts && !seals && !ctx.original_cap.broker);
		retire_result=true;
		if (!strcmp(mode,"early-finish")) {
			const struct swapz_observation_record forged={.event=SWAPZ_OBS_CLEANUP};
			CHECK(swapz_trial_controller_finish(&key,&forged)==-ESTALE && !cleanup_attempts);
		}
	}
	if (!strcmp(mode,"ordinary-map")) ctx.maps[1].valid=true;
	if (!strcmp(mode,"pending-event")) ctx.observation_release_operation=77;
	if (!strcmp(mode,"seal-failure")) seal_fail=true;
	if (!strcmp(mode,"append-failure")) append_result=false;
	if (!strcmp(mode,"bridge-failure")) byte_result=false;
	CHECK(swapz_trial_controller_retire_registered(&ti,&key)==0);
	CHECK(mm_detached && revokes==1 && snapshots>=2 && mapper.refs==1 && seals==1 && !recorder_active);
	CHECK(!ctx.original_retained_scope.identity && !ctx.original_scope_file && ctx.original_scope_final_retirement);
	CHECK(swapz_round096_target_can_free(&ctx,false));
	if (!strcmp(mode,"final-live") || !strcmp(mode,"final-pinned"))
		CHECK(record_retire_calls==1 && !ctx.maps[1].valid);
	if (!strcmp(mode,"ordinary-map") || !strcmp(mode,"pending-event") || !strcmp(mode,"early-finish"))
		CHECK(!cleanup_attempts && !cleanup_forwarded && byte_loss);
	else {
		CHECK(cleanup_attempts==1);
		if (!strcmp(mode,"append-failure")) CHECK(!cleanup_forwarded && byte_loss);
		else CHECK(cleanup_forwarded==1);
		if (!strcmp(mode,"bridge-failure") || !strcmp(mode,"seal-failure")) CHECK(byte_loss);
	}
	CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-ESTALE && seals==1);
done:
	CHECK(!module_owner.refs);
	CHECK(swapz_trial_target_unregister(&swapz_scope_target_ops)==0);
	CHECK(swapz_trial_target_unregister(&swapz_scope_target_ops)==-ESTALE);
	CHECK(swapz_trial_controller_retire_registered(&ti,&key)==-ENODEV);
	printf("R107_A3_HOST_ONLY mode=%s checks=%u AUTH=0\n",mode,checks);
	return 0;
}
