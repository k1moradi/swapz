/* Real new staged C compiled against explicit host-only native API stubs. */
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>

typedef uint64_t u64;
typedef int64_t s64;
typedef uint64_t sector_t;
typedef _Atomic(s64) atomic64_t;
#define S64_MAX INT64_MAX
#define ATOMIC64_INIT(value) (value)
#define READ_ONCE(value) (value)
#define EXPORT_SYMBOL_GPL(symbol)
#define BIO_CLONED 1U
#define REQ_PREFLUSH 16U
#define DM_IO_WAS_SPLIT 1U
struct bio;
/* INJECT_STATE */
struct swapz_ci_owned_payload { struct swapz_round065_table_state round065_table; unsigned int references; };
struct dm_target_io;
struct bio {
    unsigned int bi_flags, bi_opf;
    void (*bi_end_io)(struct bio *);
    struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
    const void *bi_bdev, *bi_io_vec;
    struct { unsigned int bi_size; sector_t bi_sector; } bi_iter;
    struct dm_target_io *tio;
};
struct mapped_device { int unused; };
struct dm_target;
struct dm_table { struct mapped_device *md; u64 swapz_round065_incarnation; struct dm_target *selected; };
struct dm_target { struct dm_table *table; };
struct dm_io { struct mapped_device *md; struct bio *orig_bio; unsigned int flags; };
struct dm_target_io { struct dm_io *io; struct dm_target *ti; unsigned int target_bio_nr; bool normal; sector_t old_sector; };
static bool route_valid = true;
static unsigned int current_scenario;
static void require(bool ok, const char *phase)
{
    if (!ok) { fprintf(stderr, "ROUND065_FIRST_ERROR scenario=%u phase=%s\n", current_scenario, phase); exit(1); }
}
static s64 atomic64_read(const atomic64_t *value) { return atomic_load(value); }
static bool atomic64_try_cmpxchg(atomic64_t *value, s64 *old, s64 desired)
{ return atomic_compare_exchange_strong(value, old, desired); }
static void clone_endio(struct bio *bio) { (void)bio; }
static struct dm_target_io *clone_to_tio(struct bio *bio) { return bio->tio; }
static bool dm_tio_is_normal(struct dm_target_io *tio) { return tio->normal; }
static bool dm_io_flagged(struct dm_io *io, unsigned int flag) { return (io->flags & flag) != 0U; }
static struct dm_target *dm_table_find_target(struct dm_table *table, sector_t sector)
{ (void)sector; return table->selected; }
static bool swapz_round064_original_route_matches(const struct swapz_ci_owned_payload *owner, const struct bio *bio)
{ (void)owner; (void)bio; return route_valid; }
/* INJECT_OWNER */
/* INJECT_CORE */
/* Only the marked table gate is actual product C. The ref stub below does
 * not execute Linux refcount or the complete swapz_map/complete scheduler.
 */
static void swapz_round063_original_dm_owner_put(struct swapz_ci_owned_payload *owner)
{
    require(owner->references != 0U, "double-put");
    --owner->references;
}
static struct swapz_ci_owned_payload *product_candidate(struct dm_target *ti,
        struct bio *bio, struct swapz_ci_owned_payload *owner)
{
    ++owner->references; /* preceding Round064 acquisition */
/* INJECT_PRODUCT */
    return owner;
}
static void check_candidate(struct dm_target *ti, struct bio *bio,
        struct swapz_ci_owned_payload *owner, bool accepted)
{
    require(owner->references == 1U, "initial-reference");
    struct swapz_ci_owned_payload *held = product_candidate(ti, bio, owner);
    require((held != NULL) == accepted, "product-table-gate");
    require(owner->references == (accepted ? 2U : 1U), "ref-balance");
    if (held) swapz_round063_original_dm_owner_put(held);
    require(owner->references == 1U, "terminal-reference");
}

int main(void)
{
    struct mapped_device md = {0}, other_md = {0};
    int bdev = 0, other_bdev = 0, bvec = 0, other_bvec = 0;
    u64 first = swapz_round065_next_incarnation();
    u64 second = swapz_round065_next_incarnation();
    require(first == 1U && second == 2U, "generation-mint");
    atomic_store(&swapz_round065_table_sequence, S64_MAX);
    require(swapz_round065_next_incarnation() == 0U && swapz_round065_next_incarnation() == 0U,
            "generation-exhaustion");
    for (current_scenario = 0; current_scenario < 24U; ++current_scenario) {
        struct bio parent = { .bi_bdev = &bdev, .bi_io_vec = &bvec, .bi_iter = {4096U, 80U} };
        struct swapz_ci_owned_payload owner = { .round065_table = { .parent = &parent }, .references = 1U }, other_owner = {0};
        struct bio clone = parent, other_parent = parent;
        struct dm_table table = { .md = &md, .swapz_round065_incarnation = first };
        struct dm_target ti = { .table = &table }, other_ti = ti;
        struct dm_io io = { .md = &md, .orig_bio = &parent };
        struct dm_target_io tio = { .io = &io, .ti = &ti, .normal = true, .old_sector = 80U };
        parent.bi_swapz_ci_sideband = &owner;
        clone.bi_swapz_ci_sideband = &owner;
        clone.bi_flags = 1U << BIO_CLONED;
        clone.bi_end_io = clone_endio;
        clone.tio = &tio;
        other_parent.bi_swapz_ci_sideband = &owner;
        table.selected = &ti;
        route_valid = true;
        require(!swapz_round065_dm_owner_matches(&ti, &clone, &owner), "before-selection");
        check_candidate(&ti, &clone, &owner, false);
        if (current_scenario == 1U) route_valid = false;
        if (current_scenario == 2U) parent.bi_flags = 1U << BIO_CLONED;
        if (current_scenario == 3U) parent.bi_opf = REQ_PREFLUSH;
        swapz_round065_original_table_select(&parent, current_scenario == 4U ? 0U : first);
        if (current_scenario >= 1U && current_scenario <= 4U) {
            route_valid = true; parent.bi_flags = 0U; parent.bi_opf = 0U;
            swapz_round065_original_table_select(&parent, first);
            require(!swapz_round065_dm_owner_matches(&ti, &clone, &owner), "permanent-refusal");
            check_candidate(&ti, &clone, &owner, false);
            continue;
        }
        require(swapz_round065_dm_owner_matches(&ti, &clone, &owner), "first-selection");
        switch (current_scenario) {
        case 5: /* same table requeue: genuine original parent, same generation */
            swapz_round065_original_table_select(&parent, first); break;
        case 6: /* identical table pointer and geometry, new publication */
            table.swapz_round065_incarnation = second;
            swapz_round065_original_table_select(&parent, second); break;
        case 7: /* changed publication then old one reinstalled, cannot revive */
            swapz_round065_original_table_select(&parent, second);
            swapz_round065_original_table_select(&parent, first); break;
        case 8: /* unrelated parent may not overwrite source owner state */
            swapz_round065_original_table_select(&other_parent, second);
            io.orig_bio = &other_parent; break;
        case 9: clone.bi_end_io = NULL; break;
        case 10: tio.ti = &other_ti; break;
        case 11: tio.normal = false; break;
        case 12: io.flags = DM_IO_WAS_SPLIT; break;
        case 13: tio.target_bio_nr = 1U; break;
        case 14: table.md = &other_md; break;
        case 15: parent.bi_bdev = &other_bdev; break;
        case 16: parent.bi_iter.bi_sector = 88U; break;
        case 17: clone.bi_iter.bi_size = 2048U; break;
        case 18: tio.old_sector = 88U; break;
        case 19: parent.bi_io_vec = &other_bvec; break;
        case 20: table.selected = &other_ti; break;
        case 21: clone.bi_swapz_ci_sideband = &other_owner; break;
        case 22: parent.bi_swapz_ci_sideband = &other_owner; break;
        case 23: table.swapz_round065_incarnation = second; break;
        default: break;
        }
        require(swapz_round065_dm_owner_matches(&ti, &clone, &owner) ==
                (current_scenario == 0U || current_scenario == 5U), "current-table");
        check_candidate(&ti, &clone, &owner, current_scenario == 0U || current_scenario == 5U);
    }
    puts("ROUND065_HOST_PASS scenarios=24 NO_AUTH");
    return 0;
}
