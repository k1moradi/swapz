/* SPDX-License-Identifier: GPL-2.0-only */
/* Actual extracted target and frozen core functions; only host primitives
 * model Linux queue locking, BIOs, recorder transport and authority pin.
 * No controller, physical I/O, native concurrency or source AUTH.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
typedef uint64_t u64;
typedef uint32_t u32;
typedef u64 sector_t;
typedef unsigned int blk_status_t;
#define SWAPZ_SCOPED_TARGET_OBSERVATION 1
#define SWAPZ_SECTORS 8U
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_OBS_ACCEPT 3U
#define SWAPZ_OBS_CLONE_ENDIO 18U
#define SWAPZ_OBS_UPPER_ENDIO 19U
#define SWAPZ_OBS_ORDINARY_WRITE 3U
#define SWAPZ_OBS_DISCARD_BIO 4U
#define EXPORT_SYMBOL_GPL(symbol)
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_OP_DISCARD 3U
#define REQ_PREFLUSH (1U<<8)
#define REQ_FUA (1U<<9)
#define REQ_NOWAIT (1U<<10)
#define REQ_POLLED (1U<<11)
#define REQ_ATOMIC (1U<<12)
#define BIO_CLONED 1U
#define BIO_REMAPPED 2U
#define DM_TIO_MAGIC 0x1234U
#define DM_IO_MAGIC 0x5678U
#define DM_IO_WAS_SPLIT 1
#define DM_ENDIO_DONE 0
#define READ_ONCE(x) (x)
#define smp_load_acquire(x) (*(x))
#define atomic64_inc(x) (++*(x))
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
#define rcu_access_pointer(x) (x)
static unsigned checks, loss, core_calls, minted, mint_limit, records, serial;
static unsigned copy_order, loss_order, put_order;
static bool recorder_active = true;
#define CHECK(x) do { ++checks; if (!(x)) { \
    fprintf(stderr,"FIRST_ERROR line=%d: %s\n",__LINE__,#x); exit(77); } } while (0)
#define lockdep_assert_held(x) CHECK(*(x))
#define spin_lock_irqsave(lock, flags) do { CHECK(!*(lock)); *(lock) = true; (flags) = 0; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { CHECK(*(lock)); *(lock) = false; (void)(flags); } while (0)
struct block_device { unsigned int id; };
struct bio {
    struct { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
    struct block_device *bi_bdev;
    unsigned int bi_opf, flags;
    const void *bi_swapz_original;
    void (*bi_end_io)(struct bio *);
    void *descriptor;
};
struct dm_target { void *private; struct block_device *bdev; bool live; };
struct dm_io {
    u64 swapz_observation_operation, swapz_observation_original;
    bool requeue_flush_with_data, split;
    unsigned int magic;
    struct bio *orig_bio;
};
struct dm_target_io {
    struct bio clone;
    unsigned int magic, target_bio_nr;
    bool normal;
    struct dm_target *ti;
    struct dm_io *io;
    unsigned int *len_ptr;
};
struct swapz_mm_trial_scope {
    struct block_device *bdev;
    const void *broker;
    u64 identity, session, table_epoch, target_epoch, area_epoch;
    sector_t first_sector, sector_count;
    u32 swap_type;
};
struct swapz_bio_ref {
    struct bio *bio;
    u64 observation_operation, observation_original, observation_clone;
    u64 observation_descriptor, observation_extent;
};
struct swapz_observation_record {
    u64 operation, original, clone, descriptor, slot, area_epoch, store;
    u32 event, operation_kind, logical, swap_type, generation, flags, status;
};
struct swapz_round089_route { u64 registration_epoch, broker_session, table_epoch, target_epoch; };
struct swapz_dm {
    struct dm_target *target;
    bool queue_lock, accepting, failed, original_trial, original_storage_ready;
    struct swapz_mm_trial_scope original_scope;
    struct swapz_round089_route original_route;
    struct { const void *broker; u64 session, epoch; } original_cap;
    unsigned int endio_write_seen_err, endio_write_seen_ok, endio_write_forced_err;
    int last_error, authority;
    unsigned char read_page[4096];
    u64 read_copy_wall_ns, read_copy_bytes;
};
static struct swapz_observation_record trace[16];
static bool swapz_trial_observation_active(void) { return recorder_active; }
static u64 swapz_trial_observation_mint(void)
{
    return minted < mint_limit ? ++minted : 0;
}
static bool swapz_trial_observation_append(const struct swapz_observation_record *record)
{
    if (!record) { ++loss; loss_order = ++serial; return false; }
    CHECK(records < 16U);
    trace[records++] = *record;
    return true;
}
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 255U; }
static sector_t bio_sectors(const struct bio *bio) { return bio->bi_iter.bi_size / 512U; }
static bool bio_flagged(const struct bio *bio, unsigned int flag) { return (bio->flags & flag) != 0; }
static void clone_endio(struct bio *bio) { (void)bio; }
static struct dm_target_io *clone_to_tio(struct bio *clone)
{ return (struct dm_target_io *)((char *)clone - offsetof(struct dm_target_io, clone)); }
static bool dm_tio_is_normal(const struct dm_target_io *tio) { return tio->normal; }
static bool dm_io_flagged(struct dm_io *io, unsigned int flag) { (void)flag; return io->split; }
static bool dm_swapz_round090_route_live(struct dm_target *ti, struct block_device *bdev, sector_t sector)
{ ++core_calls; return ti->live && ti->bdev == bdev && sector == 56U; }
static bool swapz_mm_trial_scope_matches_origin(struct block_device *bdev, sector_t sector)
{ return bdev && bdev->id == 1U && sector == 56U; }
static int blk_status_to_errno(blk_status_t status) { return status ? -EIO : 0; }
static blk_status_t errno_to_blk_status(int error) { return error ? 1U : 0U; }
static void *dm_per_bio_data(struct bio *bio, size_t bytes)
{ CHECK(bytes == sizeof(struct swapz_bio_ref)); return bio->descriptor; }
static int copy_error, put_error;
static int swapz_copy_bio_accounted(struct bio *bio, void *buffer, bool to_bio,
                                    u64 *wall, u64 *bytes)
{
    CHECK(bio && buffer && to_bio && wall && bytes && !put_order);
    copy_order = ++serial;
    return copy_error;
}
static int swapz_shared_original_put(int *authority, u64 pin)
{
    CHECK(*authority == 1 && pin == 19U && copy_order && loss_order > copy_order);
    put_order = ++serial;
    *authority = 0;
    return put_error;
}
#include "actual-target-core.h"

static void run_case(unsigned int op, unsigned int variant)
{
    struct block_device bdev = {1}, other = {2};
    struct dm_target ti = {.bdev = &bdev, .live = true};
    struct bio original = {.bi_iter = {56,4096,0,0}, .bi_bdev = &bdev, .bi_opf = op};
    struct dm_io io = {.magic = DM_IO_MAGIC, .orig_bio = &original};
    unsigned int len = 8;
    struct dm_target_io tio = {.clone = original, .magic = DM_TIO_MAGIC,
        .normal = true, .ti = &ti, .io = &io, .len_ptr = &len};
    struct swapz_bio_ref entry = {.bio = &tio.clone};
    struct swapz_dm ctx = {.target=&ti,.queue_lock=true,.accepting=true,
        .original_trial=true,.original_storage_ready=true,
        .original_scope={.bdev=&bdev,.broker=&ctx,.identity=17,.session=11,
            .table_epoch=12,.target_epoch=13,.area_epoch=4,.first_sector=56,.sector_count=16},
        .original_route={.registration_epoch=14,.broker_session=11,.table_epoch=12,.target_epoch=13},
        .original_cap={.broker=&ctx,.session=11,.epoch=12}};
    ti.private = &ctx;
    tio.clone.bi_end_io = clone_endio;
    tio.clone.descriptor = &entry;
    records = loss = minted = core_calls = 0;
    mint_limit = 32;
    recorder_active = true;
    bool rejected = false;
    switch (variant) {
    case 1: original.bi_swapz_original = &ctx; break;
    case 2: io.split = true; break;
    case 3: len = 16; break;
    case 4: ctx.accepting = false; break;
    case 5: original.bi_opf |= REQ_FUA; tio.clone.bi_opf |= REQ_FUA; break;
    case 6: mint_limit = 1; break;
    case 7: recorder_active = false; break;
    case 8: tio.clone.bi_bdev = &other; break;
    case 9: rejected = true; break;
    case 10: entry.observation_operation = 31; break;
    case 11: io.swapz_observation_operation = 25; break;
    default: break;
    }
    swapz_scope_observe_plain_accept_locked(&ctx,&entry,rejected);
    if (variant) {
        CHECK(!entry.observation_operation && !records);
        CHECK(loss == ((variant == 7 || variant == 8) ? 0U : 1U));
        CHECK(io.swapz_observation_operation == (variant == 11 ? 25U : 0U));
        if (variant == 6 || variant == 7 || variant == 8 || variant == 9 || variant == 10)
            CHECK(!core_calls);
        return;
    }
    CHECK(entry.observation_operation && entry.observation_original &&
          entry.observation_clone && entry.observation_descriptor);
    CHECK(io.swapz_observation_operation == entry.observation_operation);
    CHECK(io.swapz_observation_original == entry.observation_original && loss == 1);
    unsigned int accept_count = op == REQ_OP_READ ? 0U : 1U;
    CHECK(records == accept_count);
    if (accept_count) {
        CHECK(trace[0].event == SWAPZ_OBS_ACCEPT && trace[0].logical == 7U);
        CHECK(trace[0].operation_kind == (op == REQ_OP_WRITE ? SWAPZ_OBS_ORDINARY_WRITE : SWAPZ_OBS_DISCARD_BIO));
        CHECK(!trace[0].flags && !trace[0].slot && !trace[0].area_epoch && !trace[0].store && !trace[0].generation);
    }
    u64 operation = entry.observation_operation;
    u64 original_id = entry.observation_original;
    blk_status_t status = 0;
    if (op == REQ_OP_WRITE) { ctx.failed = true; ctx.last_error = -EIO; }
    CHECK(swapz_end_io(&ti,&tio.clone,&status) == DM_ENDIO_DONE);
    CHECK(records == accept_count + 1U && !entry.observation_operation);
    CHECK(trace[accept_count].event == SWAPZ_OBS_CLONE_ENDIO && trace[accept_count].operation == operation);
    CHECK(trace[accept_count].status == (op == REQ_OP_WRITE ? EIO : 0));
    CHECK(swapz_end_io(&ti,&tio.clone,&status) == DM_ENDIO_DONE && records == accept_count + 1U);
    dm_swapz_original_observation_endio(&io,false,status);
    CHECK(records == accept_count + 2U && trace[accept_count+1U].event == SWAPZ_OBS_UPPER_ENDIO);
    CHECK(trace[accept_count+1U].operation == operation && trace[accept_count+1U].original == original_id);
    CHECK(!io.swapz_observation_operation && !io.swapz_observation_original);
    dm_swapz_original_observation_endio(&io,false,status);
    CHECK(records == accept_count + 2U);
}

static void refusal_cases(void)
{
    struct block_device mapper = {1}, foreign = {2};
    struct swapz_dm ctx = {.original_scope = {.bdev=&mapper,.identity=17,
        .first_sector=56,.sector_count=16}};
    struct bio bio = {.bi_bdev=&mapper,.bi_iter={56,4096,0,0}};
    loss = records = core_calls = minted = 0;
    recorder_active = true;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 1 && !ctx.queue_lock);
    bio.bi_iter.bi_sector = 55;
    bio.bi_iter.bi_size = 1024;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 2 && !ctx.queue_lock);
    bio.bi_iter.bi_size = 512;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 2 && !ctx.queue_lock);
    bio.bi_iter.bi_sector = 72;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 2 && !ctx.queue_lock);
    bio.bi_iter.bi_sector = 56;
    bio.bi_bdev = &foreign;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 2 && !ctx.queue_lock);
    bio.bi_bdev = &mapper;
    recorder_active = false;
    swapz_scope_observe_map_refusal(&ctx,&bio);
    CHECK(loss == 2 && !ctx.queue_lock && !records && !core_calls && !minted);
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1],"refusal") == 0) {
        refusal_cases();
        printf("PASS refusal-only serial host checks=%u AUTH=0\n",checks);
        return 0;
    }
    CHECK(argc == 1);
    for (unsigned int variant=0; variant<=11; ++variant)
        run_case(REQ_OP_WRITE,variant);
    run_case(REQ_OP_READ,0);
    run_case(REQ_OP_DISCARD,0);
    for (unsigned int scenario=0; scenario<3; ++scenario) {
        struct swapz_dm ctx = {.authority=1};
        struct bio bio = {0};
        serial = copy_order = loss_order = put_order = loss = 0;
        recorder_active = true;
        copy_error = scenario == 1 ? -EINVAL : 0;
        put_error = scenario ? -EIO : 0;
        int error = actual_final_copy(&ctx,&bio,19);
        CHECK(copy_order < loss_order && loss_order < put_order && !ctx.authority);
        CHECK(loss == 1 && error == (copy_error ? copy_error : put_error));
    }
    printf("PASS target/core serial host checks=%u AUTH=0\n",checks);
    return 0;
}
