/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual R104 scope, store call site, completion and recorder-ordinal code.
 * Kernel allocator, compressor, BIO, RCU and peer byte/recorder calls are
 * explicit host substitutes, not native execution or a connected link. */
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
#define SWAPZ_ROUND104_INTEGRATION_TEST 1
#define CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST 1
#define READ_ONCE(value) (value)
#define SWAPZ_TERMINAL_HOST_TEST 1

static unsigned checks, spin_depth, mutex_depth, readers, grace_count;
static void (*grace_hook)(void);
#define CHECK(condition) do { \
	++checks; \
	if (!(condition)) { \
		fprintf(stderr, "R104_A11_FIRST_ERROR line=%d: %s\n", __LINE__, #condition); \
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
	unsigned bi_status;
};
enum { BIO_CLONED = 1U, BIO_REMAPPED = 2U, BIO_CHAIN = 4U };
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
typedef unsigned blk_status_t;
#define blk_status_to_errno(status) (-(int)(status))
enum { SWAPZ_OBS_UPPER_ENDIO = 19, SWAPZ_OBS_BIND = 2 };
struct swapz_observation_record {
	u64 operation, original;
	u32 event, status;
};
static unsigned recorder_calls, bridge_calls, losses;
static u64 last_ordinal, last_operation, last_original;
static u32 last_status;
static bool fail_append, fail_bridge;
static bool swapz_trial_observation_active(void) { return true; }
static u64 swapz_trial_observation_append_sequence(const struct swapz_observation_record *record)
{
	CHECK(!spin_depth);
	if (!record || fail_append)
		return 0;
	++recorder_calls;
	last_operation = record->operation;
	last_original = record->original;
	last_status = record->status;
	return ++last_ordinal;
}
static bool swapz_trial_observation_append(const struct swapz_observation_record *record)
{
	CHECK(!record); /* only invalidation, no second valid append */
	++losses;
	return false;
}
static bool swapz_trial_byte_event(const struct swapz_observation_record *record,
	u64 sequence, const void *bytes, size_t length)
{
	CHECK(!spin_depth && record && sequence == last_ordinal && !bytes && !length);
	++bridge_calls;
	return !fail_bridge;
}
static void swapz_trial_byte_invalidate(void) { ++losses; }
static void bio_chain_endio(struct bio *bio) { (void)bio; abort(); }
#include "actual-chain.h"
#include "actual-emit.h"
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
	struct bio late = {&mapper, original_endio, 0, &callback_count, 0};
	CHECK(!swapz_mm_trial_dm_enter(&late));
	CHECK(late.bi_end_io == original_endio);
}
static struct swapz_mm_trial_scope prepare(void)
{
	struct file *retained = NULL;
	u32 type = 99;
	u64 epoch = 99;
	struct bio idle = {&mapper, original_endio, 0, &callback_count, 0};
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

/* Store-site substitutes: actual zswap_store_page and stage helper are
 * extracted from the exact postimage; only compressor/allocator modeled. */
typedef struct { u32 type; u64 offset; } swp_entry_t;
struct folio { unsigned order; swp_entry_t slot; sector_t sector; unsigned char bytes[4096]; };
struct zswap_pool { unsigned idx; void *zs_pool; };
struct obj_cgroup { unsigned unused; };
struct zswap_entry {
	unsigned pool_idx, length, handle;
	u64 original_cookie;
	swp_entry_t swpentry;
	struct obj_cgroup *objcg;
	bool referenced;
	int lru;
};
static struct zswap_entry entries[2], *stored;
static unsigned stage_calls, finish_calls, mapped, compress_calls;
static u64 finished_sequence, committed_cookie = 47;
static bool active_bytes = true, fail_compress, fail_store, lru_published;
static unsigned char staged_bytes[4096];
static unsigned zswap_reject_kmemcache_fail, zswap_reject_alloc_fail;
static unsigned zswap_stored_pages, zswap_stored_incompressible_pages;
#define GFP_KERNEL 0
#define WARN_ONCE(condition, ...) ((void)(condition))
#define INIT_LIST_HEAD(list) (*(list) = 0)
static bool swapz_trial_byte_active(void) { return active_bytes; }
static u32 swp_type(swp_entry_t slot) { return slot.type; }
static u64 swp_offset(swp_entry_t slot) { return slot.offset; }
static unsigned folio_order(struct folio *folio) { return folio->order; }
static swp_entry_t folio_swap_entry(struct folio *folio, long index)
{
	swp_entry_t slot = folio->slot;
	slot.offset += (u64)index;
	return slot;
}
static struct swap_info_struct *__swap_entry_to_info(swp_entry_t slot)
{
	return slot.type == si.type ? &si : NULL;
}
static sector_t swap_folio_sector(struct folio *folio) { return folio->sector; }
static void *kmap_local_folio(struct folio *folio, unsigned offset)
{
	CHECK(!offset && readers && !mapped);
	++mapped;
	return folio->bytes;
}
static void kunmap_local(void *source) { CHECK(source && mapped == 1); --mapped; }
static u64 swapz_trial_byte_stage_input(u64 identity, u32 type, u64 area_epoch,
	u64 slot, const void *bytes, size_t length)
{
	CHECK(mapped == 1 && readers && identity == 17 && type == 2 &&
	      area_epoch == swapz_mm_trial_area_epoch(2) && slot == 7 && length == 4096);
	CHECK(((const unsigned char *)bytes)[0] == 0xa5);
	memcpy(staged_bytes, bytes, length);
	++stage_calls;
	return 777;
}
static void swapz_trial_byte_finish_input(u64 token, u64 store_sequence)
{
	CHECK(token == 777 && !mapped && !lru_published);
	CHECK(!store_sequence || (stored && stored->original_cookie == store_sequence));
	++finish_calls;
	finished_sequence = store_sequence;
}
static unsigned folio_nid(struct folio *folio) { (void)folio; return 0; }
static struct zswap_entry *zswap_entry_cache_alloc(int flags, unsigned node)
{
	(void)flags; (void)node;
	return stored == &entries[0] ? &entries[1] : &entries[0];
}
static void zswap_entry_cache_free(struct zswap_entry *entry) { CHECK(entry); }
static bool zswap_compress(struct folio *folio, long index, struct zswap_entry *entry,
	struct zswap_pool *pool)
{
	(void)index; (void)pool;
	CHECK(!mapped);
	++compress_calls;
	/* This deliberately changes the input buffer after the staging point.
	 * An eviction/decoder/post-compression substitute cannot pass. */
	memset(folio->bytes, 0x33, sizeof(folio->bytes));
	entry->original_cookie = committed_cookie;
	entry->length = 64;
	return !fail_compress;
}
static void *swap_zswap_tree(swp_entry_t slot) { (void)slot; return &stored; }
static struct zswap_entry *xa_store(void *tree, u64 offset, struct zswap_entry *entry, int flags)
{
	(void)tree; (void)offset; (void)flags;
	if (fail_store)
		return (struct zswap_entry *)(uintptr_t)1;
	struct zswap_entry *old = stored;
	stored = entry;
	return old;
}
static bool xa_is_err(struct zswap_entry *entry) { return entry == (void *)(uintptr_t)1; }
static int xa_err(struct zswap_entry *entry) { CHECK(xa_is_err(entry)); return -ENOMEM; }
static void zswap_entry_free(struct zswap_entry *entry) { CHECK(entry && entry != stored); }
static void zs_free(void *pool, unsigned handle) { (void)pool; (void)handle; }
static void zswap_pool_get(struct zswap_pool *pool) { CHECK(pool); }
static void obj_cgroup_get(struct obj_cgroup *objcg) { CHECK(objcg); }
static void obj_cgroup_charge_zswap(struct obj_cgroup *objcg, unsigned length)
{ CHECK(objcg && length); }
static void atomic_long_inc(unsigned *counter) { ++*counter; }
static void zswap_lru_add(struct zswap_entry *entry)
{ CHECK(entry == stored); lru_published = true; }
#include "actual-store.h"

struct dm_io {
	struct bio *orig_bio;
	u64 swapz_observation_operation, swapz_observation_original;
	bool requeue_flush_with_data, split;
};
#define DM_IO_WAS_SPLIT 1
static bool dm_io_flagged(struct dm_io *io, int flag) { CHECK(flag == DM_IO_WAS_SPLIT); return io->split; }
#include "actual-dm-endio.h"
struct swapz_mm_carrier {
	struct swapz_observation_record observation;
	u64 observation_original;
};
#include "actual-mm-endio.h"

static void scope_checks(struct swapz_mm_trial_scope requested)
{
	CHECK(swapz_mm_trial_scope_matches_exact(&requested, &opened));
	CHECK(!swapz_mm_trial_scope_matches_exact(&requested, &area));
	CHECK(!swapz_mm_trial_scope_matches_exact(&requested, &wrong_file));
	CHECK(!swapz_mm_trial_scope_matches_exact(NULL, &opened));
	CHECK(!swapz_mm_trial_scope_matches_exact(&requested, NULL));
#define WRONG(field) do { \
	struct swapz_mm_trial_scope wrong = requested; \
	++wrong.field; \
	CHECK(!swapz_mm_trial_scope_matches_exact(&wrong, &opened)); \
} while (0)
	WRONG(identity); WRONG(session); WRONG(table_epoch); WRONG(target_epoch);
	WRONG(area_epoch); WRONG(swap_type); WRONG(first_sector); WRONG(sector_count);
#undef WRONG
	struct swapz_mm_trial_scope wrong = requested;
	wrong.bdev = &foreign;
	CHECK(!swapz_mm_trial_scope_matches_exact(&wrong, &opened));
	wrong = requested;
	wrong.broker = NULL;
	CHECK(!swapz_mm_trial_scope_matches_exact(&wrong, &opened));
	/* Query is legal under a modeled target queue lock; no sleeping. */
	spin_lock(&swap_lock);
	CHECK(swapz_mm_trial_scope_matches_exact(&requested, &opened));
	spin_unlock(&swap_lock);
}

static void input_checks(void)
{
	struct folio folio = {.slot = {2, 7}, .sector = 56};
	struct zswap_pool pool = {.idx = 9};
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	CHECK(zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 1 && finish_calls == 1 && compress_calls == 1);
	CHECK(finished_sequence == 47 && lru_published && staged_bytes[0] == 0xa5 &&
	      staged_bytes[4095] == 0xa5 && folio.bytes[0] == 0x33);
	lru_published = false;
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	fail_compress = true;
	CHECK(!zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 2 && finish_calls == 2 && !finished_sequence && !lru_published);
	fail_compress = false;
	fail_store = true;
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	CHECK(!zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 3 && finish_calls == 3 && !finished_sequence && !lru_published);
	fail_store = false;
	/* The substitute allocator never returns the still-published slab slot. */
	committed_cookie = 48;
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	CHECK(zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 4 && finish_calls == 4 && finished_sequence == 48);
	lru_published = false;
	committed_cookie = 0;
	memset(folio.bytes, 0xa5, sizeof(folio.bytes));
	CHECK(zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 5 && finish_calls == 5 && !finished_sequence);
	unsigned previous_losses = losses;
	lru_published = false;
	committed_cookie = 49;
	folio.slot.offset = 8; /* mismatch to actual sector */
	CHECK(zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 5 && finish_calls == 5 && losses == previous_losses + 1);
	lru_published = false;
	active_bytes = false;
	CHECK(zswap_store_page(&folio, 0, NULL, &pool));
	CHECK(stage_calls == 5 && finish_calls == 5 && losses == previous_losses + 1);
	active_bytes = true;
}

static void completion_checks(struct swapz_mm_trial_scope requested)
{
	struct bio original = {&mapper, original_endio, 0, &callback_count, EIO};
	u64 entrant = swapz_mm_trial_dm_enter(&original);
	CHECK(entrant && swapz_mm_trial_dm_origin(&original, 56));
	struct dm_io io = {&original, 31, 32, false, false};
	dm_swapz_original_observation_endio(&io, false, 0);
	CHECK(!io.swapz_observation_operation && !io.swapz_observation_original);
	CHECK(!recorder_calls && !bridge_calls); /* no early ACK */
	dm_swapz_original_observation_endio(&io, false, 0);
	CHECK(!recorder_calls);
	CHECK(!swapz_mm_trial_scope_stop_capture(17));
	CHECK(!swapz_mm_trial_scope_matches_exact(&requested, &opened));
	retire();
	CHECK(join() == -EBUSY);
	check_callback_join = true;
	original.bi_end_io(&original);
	CHECK(callback_count == 1 && recorder_calls == 1 && bridge_calls == 1 &&
	      last_operation == 31 && last_original == 32 && last_status == EIO);
	CHECK(join() == -EBUSY);
	swapz_mm_trial_dm_leave(entrant);
	CHECK(!join());
	CHECK(!swapz_mm_trial_scope_revoke(17));
	CHECK(opened.refs == 1 && area.refs == 1 && broker.refs == 1);
}

static void negative(const char *mode)
{
	struct swapz_mm_trial_scope requested = prepare();
	CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
	if (!strcmp(mode, "chain")) {
		struct bio child = {&mapper, bio_chain_endio, 0, &callback_count, 0};
		CHECK(!swapz_mm_trial_dm_enter(&child));
		CHECK(child.bi_end_io == bio_chain_endio && losses && !recorder_calls);
	} else if (!strcmp(mode, "chain-parent")) {
		struct bio parent = {&mapper, original_endio, BIO_CHAIN, &callback_count, 0};
		u64 entrant = swapz_mm_trial_dm_enter(&parent);
		CHECK(entrant && losses && !swapz_mm_trial_dm_origin(&parent, 56));
		CHECK(parent.bi_end_io != original_endio && !recorder_calls);
		/* Model final block remaining-count completion, not a child ACK. */
		parent.flags = 0;
		parent.bi_end_io(&parent);
		swapz_mm_trial_dm_leave(entrant);
		CHECK(callback_count == 1 && !recorder_calls && !bridge_calls);
	} else if (!strcmp(mode, "requeue")) {
		struct bio original = {&mapper, original_endio, 0, &callback_count, 0};
		u64 entrant = swapz_mm_trial_dm_enter(&original);
		CHECK(entrant && swapz_mm_trial_dm_origin(&original, 56));
		struct dm_io io = {&original, 31, 32, false, false};
		dm_swapz_original_observation_endio(&io, true, 0);
		CHECK(losses && !recorder_calls && !io.swapz_observation_operation);
		swapz_mm_trial_dm_leave(entrant);
		entrant = swapz_mm_trial_dm_enter(&original);
		CHECK(entrant && !swapz_mm_trial_dm_origin(&original, 56));
		original.bi_end_io(&original);
		swapz_mm_trial_dm_leave(entrant);
		CHECK(callback_count == 1 && !recorder_calls && !bridge_calls);
	} else if (!strcmp(mode, "late")) {
		CHECK(!swapz_mm_trial_scope_stop_capture(17));
		retire();
		grace_hook = late_entrant;
		CHECK(join() == -EUCLEAN && losses);
		CHECK(swapz_mm_trial_scope_revoke(17) == -EUCLEAN);
	} else if (!strcmp(mode, "ordinal")) {
		struct swapz_mm_carrier carrier = {.observation = {.operation = 31}, .observation_original = 32};
		swapz_mm_observation_endio(&carrier, EIO);
		CHECK(recorder_calls == 1 && bridge_calls == 1 && last_status == EIO);
		fail_bridge = true;
		swapz_mm_observation_endio(&carrier, 0);
		CHECK(recorder_calls == 2 && bridge_calls == 2 && losses == 1);
		fail_append = true;
		swapz_mm_observation_endio(&carrier, 0);
		CHECK(recorder_calls == 2 && bridge_calls == 2 && losses == 2);
	} else {
		CHECK(false);
	}
}

int main(int argc, char **argv)
{
	if (argc != 2)
		return 2;
	if (!strcmp(argv[1], "normal")) {
		struct swapz_mm_trial_scope requested = prepare();
		CHECK(!swapz_mm_trial_scope_matches_exact(&requested, &opened));
		CHECK(!swapz_mm_trial_scope_publish(&requested, &opened));
		scope_checks(requested);
		input_checks();
		completion_checks(requested);
	} else {
		negative(argv[1]);
	}
	CHECK(!spin_depth && !mutex_depth && !readers && !mapped);
	printf("R104_A11_HOST_ONLY mode=%s checks=%u grace=%u AUTH0\n", argv[1], checks, grace_count);
	return 0;
}
