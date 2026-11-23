/* Round079 Agent11 — compile and EXECUTE immutable Linux dm.c fragments.
 * This is a rootless host ABI simulation; it is NOT a loaded DM target,
 * original Linux KUnit, a live zswap STORED source, or physical durability.
 * Python replaces SOURCE_* tags with VERBATIM source bytes after verifying
 * exact original pinned git blobs and actual product dm-target.c anchors.
 */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define unlikely(value) (value)
#define likely(value) (value)
#define noinline
#define GFP_NOWAIT 1
#define GFP_NOIO 2
#define REQ_SWAP (1U << 0)
#define REQ_NOWAIT (1U << 1)
#define REQ_PREFLUSH (1U << 2)
#define REQ_RAHEAD (1U << 3)
#define REQ_POLLED (1U << 4)
#define DM_TARGET_SINGLETON 0x00000001U
#define DM_TARGET_ALWAYS_WRITEABLE 0x00000002U
#define DMF_BLOCK_IO_FOR_SUSPEND 1
#define BLK_STS_OK 0
#define BLK_STS_AGAIN 1
#define BLK_STS_IOERR 2
#define BLK_STS_DM_REQUEUE 3
#define BLK_STS_NOTSUPP 4
#define DMCRIT(...) ((void)0)
#define BUG() ((void)0)
#define WARN_ON_ONCE(condition) (condition)
#define static_branch_unlikely(pointer) (*(pointer))
#define spin_lock_irqsave(lock, flags) ((void)(lock), (void)(flags))
#define spin_unlock_irqrestore(lock, flags) ((void)(lock), (void)(flags))
#define CHECK(condition) do { if (!(condition)) { \
    (void)fprintf(stderr, "FIRST_ERROR line=%d invariant=%s\n", \
                  __LINE__, #condition); return 1; \
} } while (0)

/* SOURCE_HEADER_NOWAIT */
/* SOURCE_HEADER_MAPIO */

struct bio;
struct dm_target;
struct mapped_device;
struct dm_io;
struct target_type {
    unsigned int features;
    int (*map)(struct dm_target *, struct bio *);
};
struct dm_target {
    struct target_type *type;
    bool accounts_remapped_io;
    bool limit_swap_bios;
};
struct semaphore { unsigned int operations; };
struct mapped_device {
    struct semaphore swap_bios_semaphore;
    int swap_bios;
    int deferred_lock;
    unsigned int flags;
    bool noflush_suspending;
};
struct bio {
    unsigned int bi_opf;
    int bi_status;
    struct { unsigned long long bi_sector; } bi_iter;
    void (*bi_end_io)(struct bio *);
    struct dm_target_io *tio;
};
struct dm_io {
    struct mapped_device *md;
    struct bio *orig_bio;
    int status;
    int lock;
};
struct dm_target_io {
    struct dm_target *ti;
    struct dm_io *io;
    unsigned long long old_sector;
};
struct clone_info {
    struct bio *bio;
    unsigned long long sector;
    unsigned int sector_count;
    struct dm_io *io;
};
struct source_counters {
    unsigned int returned_submitted;
    unsigned int map_calls;
    unsigned int freed_clones;
    unsigned int remapped;
    unsigned int accounted;
    unsigned int dec_pending;
    unsigned int up;
    unsigned int down;
    unsigned int nowait_allocs;
    unsigned int noio_allocs;
    unsigned int io_nowait_allocs;
    unsigned int io_noio_allocs;
    unsigned int wouldblock;
    unsigned int queued;
    unsigned int io_error;
    unsigned int requeue_added;
    unsigned int requeue_kicked;
    unsigned int polled_cleared;
    int last_dec_status;
};
static struct source_counters observations;
static struct mapped_device mapped_device;
static struct dm_io original_io;
static struct dm_target_io clone_owner;
static struct bio clone_storage;
static struct target_type mapped_type;
static struct dm_target target;
static struct bio original_bio;
static int swap_bios_enabled;
static int chosen_map_result;
static bool fail_clone_allocation;
static bool fail_io_allocation;

static struct dm_target_io *clone_to_tio(struct bio *clone) { return clone->tio; }
static void clone_endio(struct bio *clone) { (void)clone; }
static void free_tio(struct bio *clone) { (void)clone; ++observations.freed_clones; }
static void dm_io_dec_pending(struct dm_io *io, int status)
{ ++observations.dec_pending; observations.last_dec_status = status; io->status = status; }
static void dm_start_io_acct(struct dm_io *io, struct bio *clone)
{ (void)io; (void)clone; ++observations.accounted; }
static void dm_submit_bio_remap(struct bio *clone, struct bio *target_clone)
{ (void)clone; (void)target_clone; ++observations.remapped; }
static int fake_map(struct dm_target *ti, struct bio *clone)
{ (void)ti; (void)clone; ++observations.map_calls; return chosen_map_result; }
static int linear_map(struct dm_target *ti, struct bio *clone)
{ return fake_map(ti, clone); }
static int stripe_map(struct dm_target *ti, struct bio *clone)
{ return fake_map(ti, clone); }
static int get_swap_bios(void) { return mapped_device.swap_bios; }
static void __set_swap_bios_limit(struct mapped_device *md, int latch)
{ md->swap_bios = latch; }
static void down(struct semaphore *semaphore)
{ ++semaphore->operations; ++observations.down; }
static void up(struct semaphore *semaphore)
{ ++semaphore->operations; ++observations.up; }
static bool __noflush_suspending(const struct mapped_device *md)
{ return md->noflush_suspending; }
static bool dm_is_zone_write(struct mapped_device *md, struct bio *bio)
{ (void)md; (void)bio; return false; }
static void bio_clear_polled(struct bio *bio)
{ bio->bi_opf &= ~REQ_POLLED; ++observations.polled_cleared; }
static void dm_requeue_add_io(struct dm_io *io, bool first_stage)
{ (void)io; (void)first_stage; ++observations.requeue_added; }
static void dm_kick_requeue(struct mapped_device *md, bool first_stage)
{ (void)md; (void)first_stage; ++observations.requeue_kicked; }
static bool test_bit(unsigned int bit, const unsigned int *bits)
{ return (*bits & (1U << bit)) != 0U; }
static void bio_wouldblock_error(struct bio *bio)
{ bio->bi_status = BLK_STS_AGAIN; ++observations.wouldblock; }
static void bio_io_error(struct bio *bio)
{ bio->bi_status = BLK_STS_IOERR; ++observations.io_error; }
static void queue_io(struct mapped_device *md, struct bio *bio)
{ (void)md; (void)bio; ++observations.queued; }
static struct bio *alloc_tio(struct clone_info *ci, struct dm_target *ti,
                             int duplicate, unsigned int *len, int allocation_flags)
{
    (void)ti; (void)duplicate; (void)len;
    if (allocation_flags == GFP_NOWAIT) ++observations.nowait_allocs;
    else ++observations.noio_allocs;
    if (fail_clone_allocation) return NULL;
    clone_storage.bi_opf = ci->bio->bi_opf;
    clone_storage.bi_iter.bi_sector = ci->sector;
    return &clone_storage;
}
static struct dm_io *alloc_io(struct mapped_device *md, struct bio *bio,
                              int allocation_flags)
{
    (void)md; (void)bio;
    if (allocation_flags == GFP_NOWAIT) ++observations.io_nowait_allocs;
    else ++observations.io_noio_allocs;
    return fail_io_allocation ? NULL : &original_io;
}

/* SOURCE_SWAP_LIMIT */
/* SOURCE_MAP_BIO */
/* SOURCE_HANDLE_REQUEUE */

static int source_split_nowait(struct clone_info *ci, struct dm_target *ti,
                               unsigned int len)
{
    struct bio *clone;
    /* SOURCE_NOWAIT_ALLOC */
}
static void source_nowait_preflush(struct mapped_device *md, struct bio *bio,
                                   bool is_abnormal)
{
    struct dm_io *io;
    /* SOURCE_NOWAIT_PREFLUSH */
    (void)io;
}
static void source_suspend(struct mapped_device *md, struct bio *bio)
{
    /* SOURCE_SUSPEND */
out:
    return;
}

static void reset_case(void)
{
    (void)memset(&observations, 0, sizeof(observations));
    (void)memset(&mapped_device, 0, sizeof(mapped_device));
    (void)memset(&original_io, 0, sizeof(original_io));
    (void)memset(&clone_owner, 0, sizeof(clone_owner));
    (void)memset(&clone_storage, 0, sizeof(clone_storage));
    (void)memset(&original_bio, 0, sizeof(original_bio));
    (void)memset(&mapped_type, 0, sizeof(mapped_type));
    (void)memset(&target, 0, sizeof(target));
    swap_bios_enabled = 0;
    chosen_map_result = DM_MAPIO_SUBMITTED;
    fail_clone_allocation = false;
    fail_io_allocation = false;
    mapped_type.map = fake_map;
    mapped_type.features = DM_TARGET_NOWAIT;
    target.type = &mapped_type;
    original_io.md = &mapped_device;
    original_io.orig_bio = &original_bio;
    clone_owner.io = &original_io;
    clone_owner.ti = &target;
    clone_storage.tio = &clone_owner;
    original_bio.bi_iter.bi_sector = 8ULL;
}

static int validate_original_branches(void)
{
    struct clone_info clone_info;
    bool requeued;

    reset_case();
    chosen_map_result = DM_MAPIO_SUBMITTED;
    __map_bio(&clone_storage);
    CHECK(observations.map_calls == 1U);
    CHECK(observations.accounted == 1U);
    CHECK(observations.freed_clones == 0U);
    CHECK(observations.dec_pending == 0U);

    reset_case();
    target.accounts_remapped_io = true;
    __map_bio(&clone_storage);
    CHECK(observations.accounted == 0U);
    CHECK(observations.freed_clones == 0U);

    reset_case();
    chosen_map_result = DM_MAPIO_REQUEUE;
    __map_bio(&clone_storage);
    CHECK(observations.freed_clones == 1U);
    CHECK(observations.dec_pending == 1U);
    CHECK(observations.last_dec_status == BLK_STS_DM_REQUEUE);
    CHECK(observations.accounted == 0U);

    reset_case();
    chosen_map_result = DM_MAPIO_KILL;
    __map_bio(&clone_storage);
    CHECK(observations.freed_clones == 1U);
    CHECK(observations.last_dec_status == BLK_STS_IOERR);

    reset_case();
    chosen_map_result = DM_MAPIO_REMAPPED;
    __map_bio(&clone_storage);
    CHECK(observations.remapped == 1U);
    CHECK(observations.freed_clones == 0U);

    reset_case();
    swap_bios_enabled = 1;
    target.limit_swap_bios = true;
    clone_storage.bi_opf = REQ_SWAP;
    chosen_map_result = DM_MAPIO_REQUEUE;
    __map_bio(&clone_storage);
    CHECK(observations.down == 1U);
    CHECK(observations.up == 1U);

    reset_case();
    swap_bios_enabled = 1;
    clone_storage.bi_opf = REQ_SWAP;
    chosen_map_result = DM_MAPIO_SUBMITTED;
    __map_bio(&clone_storage);
    CHECK(observations.down == 0U);
    CHECK(observations.up == 0U);

    reset_case();
    original_bio.bi_opf = REQ_NOWAIT;
    clone_info = (struct clone_info){.bio = &original_bio, .sector = 8ULL,
                                     .sector_count = 8U};
    mapped_type.features = 0U;
    CHECK(source_split_nowait(&clone_info, &target, 8U) == BLK_STS_NOTSUPP);
    CHECK(observations.nowait_allocs == 0U);

    reset_case();
    original_bio.bi_opf = REQ_NOWAIT;
    clone_info = (struct clone_info){.bio = &original_bio, .sector = 8ULL,
                                     .sector_count = 8U};
    fail_clone_allocation = true;
    CHECK(source_split_nowait(&clone_info, &target, 8U) == BLK_STS_AGAIN);
    CHECK(observations.nowait_allocs == 1U);
    CHECK(observations.map_calls == 0U);

    reset_case();
    original_bio.bi_opf = REQ_NOWAIT;
    clone_info = (struct clone_info){.bio = &original_bio, .sector = 8ULL,
                                     .sector_count = 8U};
    CHECK(source_split_nowait(&clone_info, &target, 8U) == BLK_STS_OK);
    CHECK(observations.nowait_allocs == 1U);
    CHECK(observations.map_calls == 1U);
    CHECK(clone_info.sector == 16ULL);
    CHECK(clone_info.sector_count == 0U);

    reset_case();
    original_bio.bi_opf = REQ_PREFLUSH | REQ_NOWAIT;
    source_nowait_preflush(&mapped_device, &original_bio, false);
    CHECK(observations.wouldblock == 1U);
    CHECK(original_bio.bi_status == BLK_STS_AGAIN);
    CHECK(observations.io_nowait_allocs == 0U);

    reset_case();
    original_bio.bi_opf = REQ_NOWAIT;
    fail_io_allocation = true;
    source_nowait_preflush(&mapped_device, &original_bio, false);
    CHECK(observations.wouldblock == 1U);
    CHECK(observations.io_nowait_allocs == 1U);

    reset_case();
    mapped_device.flags = (1U << DMF_BLOCK_IO_FOR_SUSPEND);
    original_bio.bi_opf = REQ_NOWAIT;
    source_suspend(&mapped_device, &original_bio);
    CHECK(observations.wouldblock == 1U);
    CHECK(observations.queued == 0U);

    reset_case();
    mapped_device.flags = (1U << DMF_BLOCK_IO_FOR_SUSPEND);
    source_suspend(&mapped_device, &original_bio);
    CHECK(observations.queued == 1U);
    CHECK(observations.wouldblock == 0U);

    reset_case();
    mapped_device.flags = (1U << DMF_BLOCK_IO_FOR_SUSPEND);
    original_bio.bi_opf = REQ_RAHEAD;
    source_suspend(&mapped_device, &original_bio);
    CHECK(observations.io_error == 1U);

    reset_case();
    original_io.status = BLK_STS_DM_REQUEUE;
    mapped_device.noflush_suspending = true;
    requeued = dm_handle_requeue(&original_io, true);
    CHECK(requeued);
    CHECK(observations.requeue_added == 1U);
    CHECK(observations.requeue_kicked == 1U);
    CHECK(original_io.status == BLK_STS_DM_REQUEUE);

    reset_case();
    original_io.status = BLK_STS_DM_REQUEUE;
    mapped_device.noflush_suspending = true;
    requeued = dm_handle_requeue(&original_io, false);
    CHECK(requeued);
    CHECK(observations.requeue_added == 1U);

    reset_case();
    original_io.status = BLK_STS_DM_REQUEUE;
    requeued = dm_handle_requeue(&original_io, false);
    CHECK(!requeued);
    CHECK(original_io.status == BLK_STS_IOERR);

    reset_case();
    original_io.status = BLK_STS_AGAIN;
    original_bio.bi_opf = REQ_NOWAIT;
    requeued = dm_handle_requeue(&original_io, false);
    CHECK(!requeued);
    CHECK(original_io.status == BLK_STS_AGAIN);

    reset_case();
    original_io.status = BLK_STS_AGAIN;
    original_bio.bi_opf = REQ_POLLED;
    requeued = dm_handle_requeue(&original_io, false);
    CHECK(requeued);
    CHECK(observations.polled_cleared == 1U);
    CHECK((original_bio.bi_opf & REQ_POLLED) == 0U);
    CHECK(observations.requeue_added == 1U);

    reset_case();
    original_io.status = BLK_STS_DM_REQUEUE;
    requeued = dm_handle_requeue(&original_io, true);
    CHECK(requeued);
    CHECK(observations.requeue_added == 1U);

    reset_case();
    mapped_type.features = SOURCE_PRODUCT_TARGET_FEATURES;
    CHECK(!dm_target_supports_nowait(&mapped_type));
    /* The real product currently advertises SINGLETON|ALWAYS_WRITEABLE,
     * without DM_TARGET_NOWAIT. Source-derived macro is injected here. */
    CHECK((SOURCE_PRODUCT_TARGET_FEATURES & DM_TARGET_NOWAIT) == 0U);
    return 0;
}

int main(void)
{
    int result = validate_original_branches();
    if (!result)
        puts("PASS_HOST_ONLY ROUND079_AGENT11_DM_CORE_SOURCE_REQUEUE_NOWAIT");
    return result;
}
