/* Deliberately host-only MM/DM stubs; injected helpers are exact kernel C. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define SWAPZ_ROUND064_ORIGINAL_SLOT_TARGET_TEST 1
#define SWAPZ_ROUND063_ORIGINAL_DM_OWNER_TEST 1
#define SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST 1
#define SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY 1
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND028_SLOT_EPOCH_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#define CONFIG_SWAP 1
#define PAGE_SIZE 4096U
#define SWAPZ_SECTORS 8U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 16U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 7U
#define SWP_BLKDEV 64U
#define EXPORT_SYMBOL_GPL(symbol)
#define IS_ERR_OR_NULL(pointer) (!(pointer))
typedef uint64_t u64;
typedef uint64_t sector_t;
typedef struct { unsigned long val; } swp_entry_t;
struct block_device { bool partition; };
struct folio { swp_entry_t swap; bool cache, writeback; unsigned int pages; };
struct page { struct folio *folio; };
struct bio_vec { struct page *bv_page; unsigned int bv_offset, bv_len; };
struct swapz_ci_owned_payload {
    unsigned int references;
    bool swapz_round056_budgeted, swapz_round056_sealed;
    bool round064_route_bound;
    u64 slot_epoch, source_swap_entry;
    struct block_device *round064_source_bdev;
    sector_t round064_source_sector;
    struct page *round064_source_page;
};
struct bio {
    struct block_device *bi_bdev;
    unsigned int bi_opf, bi_swap_origin;
    struct { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
    struct bio_vec *bi_io_vec;
    struct swapz_ci_owned_payload *owner;
};
struct swap_info_struct { struct block_device *bdev; unsigned int flags; };
struct gendisk { struct block_device *part0; };
struct mapped_device { struct gendisk *disk; };
struct dm_table { struct mapped_device *md; };
struct dm_target { struct dm_table *table; sector_t begin, len; };
struct swapz_dm { struct dm_target *target; sector_t logical_pages; };
struct swapz_bio_ref { struct swapz_ci_owned_payload *round063_owned_original; };
static struct swap_info_struct *active_area;
static u64 live_epoch;
static sector_t extent_sector;
static unsigned int area_refs, owner_puts;
static bool fail_get;
static void require(bool ok, unsigned int scenario, const char *phase)
{
    if (!ok) {
        fprintf(stderr, "ROUND064_FIRST_ERROR scenario=%u phase=%s\n", scenario, phase);
        exit(1);
    }
}
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 7U; }
static sector_t bio_sectors(const struct bio *bio) { return bio->bi_iter.bi_size / 512U; }
static struct folio *page_folio(struct page *page) { return page->folio; }
static bool folio_test_swapcache(struct folio *folio) { return folio->cache; }
static bool folio_test_writeback(struct folio *folio) { return folio->writeback; }
static unsigned int folio_nr_pages(struct folio *folio) { return folio->pages; }
static unsigned int refcount_read(const unsigned int *refs) { return *refs; }
static bool bdev_is_partition(struct block_device *device) { return device->partition; }
static struct swap_info_struct *get_swap_device(swp_entry_t slot)
{
    if (!slot.val || !active_area)
        return NULL;
    ++area_refs;
    return active_area;
}
static void put_swap_device(struct swap_info_struct *area)
{
    require(area == active_area && area_refs != 0U, 99U, "area-put");
    --area_refs;
}
static sector_t swap_folio_sector(struct folio *folio) { (void)folio; return extent_sector; }
u64 swapz_round028_slot_epoch(swp_entry_t slot) { return slot.val ? live_epoch : 0U; }
static struct mapped_device *dm_table_get_md(struct dm_table *table) { return table->md; }
static struct gendisk *dm_disk(struct mapped_device *md) { return md->disk; }
static struct swapz_ci_owned_payload *swapz_round063_original_dm_owner_get(struct bio *bio)
{
    if (fail_get || !bio->owner || !bio->owner->references)
        return NULL;
    ++bio->owner->references;
    return bio->owner;
}
static void swapz_round063_original_dm_owner_put(struct swapz_ci_owned_payload *owner)
{
    if (owner) {
        require(owner->references != 0U, 99U, "owner-double-put");
        --owner->references;
        ++owner_puts;
    }
}
/* ROUND064_INJECT_ORIGINAL */
/* ROUND064_INJECT_PRODUCT */
static void actual_map_acquire(struct dm_target *ti, struct swapz_dm *ctx,
        struct bio *bio, struct swapz_bio_ref *entry)
{
/* ROUND064_INJECT_MAP_ACQUIRE */
}
static void actual_map_reject(struct swapz_bio_ref *entry)
{
/* ROUND064_INJECT_MAP_REJECT */
}
static void actual_complete_put(struct swapz_bio_ref *entry)
{
/* ROUND064_INJECT_COMPLETE_PUT */
}
int main(void)
{
    for (unsigned int scenario = 0; scenario < 27U; ++scenario) {
        struct block_device device = {0}, wrong_device = {0};
        struct folio folio = { .swap = { .val = 42UL }, .cache = true, .writeback = true, .pages = 1U };
        struct page page = { .folio = &folio }, wrong_page = { .folio = &folio };
        struct bio_vec vector = { .bv_page = &page, .bv_len = 4096U };
        struct swapz_ci_owned_payload owner = { .references = 1U, .slot_epoch = 91U,
            .source_swap_entry = 42U, .swapz_round056_budgeted = true, .swapz_round056_sealed = true };
        struct bio bio = { .bi_bdev = &device, .bi_opf = REQ_OP_WRITE | REQ_SWAP,
            .bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
            .bi_iter = { .bi_sector = 80U, .bi_size = 4096U }, .bi_io_vec = &vector, .owner = &owner };
        struct swap_info_struct area = { .bdev = &device, .flags = SWP_BLKDEV }, other_area = area;
        struct gendisk disk = { .part0 = &device };
        struct mapped_device md = { .disk = &disk };
        struct dm_table table = { .md = &md };
        struct dm_target ti = { .table = &table, .len = 160U }, other_ti = ti;
        struct swapz_dm ctx = { .target = &ti, .logical_pages = 20U };
        struct swapz_bio_ref entry = {0};
        bool bind_ok = scenario != 1U && scenario != 2U && scenario != 3U && scenario != 4U &&
            scenario != 5U && scenario != 6U && scenario != 7U && scenario != 8U && scenario != 9U &&
            scenario != 10U && scenario != 11U;
        active_area = &area; live_epoch = 91U; extent_sector = 80U;
        area_refs = 0U; owner_puts = 0U; fail_get = false;
        switch (scenario) {
        case 1: live_epoch = 92U; break;
        case 2: active_area = &other_area; break;
        case 3: area.flags = 0U; break;
        case 4: device.partition = true; break;
        case 5: extent_sector = 88U; break;
        case 6: folio.writeback = false; break;
        case 7: folio.swap.val = 43UL; break;
        case 8: owner.references = 2U; break;
        case 9: owner.swapz_round056_sealed = false; break;
        case 10: bio.bi_swap_origin = 0U; break;
        case 11: bio.bi_opf = REQ_OP_WRITE; break;
        default: break;
        }
        require(swapz_round064_original_route_bind(&owner, &bio, &area) == bind_ok, scenario, "bind");
        require(area_refs == 0U, scenario, "bind-area-balanced");
        if (!bind_ok) {
            require(!owner.round064_route_bound, scenario, "no-publication-on-bind-failure");
            continue;
        }
        require(!swapz_round064_original_route_bind(&owner, &bio, &area), scenario, "immutable-route");
        owner.references = 2U; /* source BIO and cloned BIO */
        switch (scenario) {
        case 12: live_epoch = 92U; break; /* same slot/page address, different allocation */
        case 13: bio.bi_bdev = &wrong_device; break;
        case 14: bio.bi_iter.bi_sector = 88U; break;
        case 15: vector.bv_page = &wrong_page; break;
        case 16: ctx.target = &other_ti; break;
        case 17: ti.begin = 8U; break;
        case 18: ti.len = 80U; break;
        case 19: disk.part0 = &wrong_device; break;
        case 20: fail_get = true; break;
        case 21: bio.bi_iter.bi_size = 2048U; break;
        case 22: ctx.logical_pages = 10U; break;
        case 23: area.bdev = &wrong_device; break;
        case 24: folio.cache = false; break;
        default: break;
        }
        actual_map_acquire(&ti, &ctx, &bio, &entry);
        const bool accepted = scenario == 0U || scenario == 25U || scenario == 26U;
        require((entry.round063_owned_original != NULL) == accepted, scenario, "candidate");
        require(area_refs == 0U && owner.references == (accepted ? 3U : 2U), scenario, "candidate-balanced");
        if (accepted) {
            /* Simulate descriptor-owned rejection/requeue or normal/error
             * terminal completion. Actual product map/complete call these
             * helpers; this test does not execute kernel DM scheduling.
             */
            if (scenario == 25U)
                actual_map_reject(&entry);
            else
                actual_complete_put(&entry);
            require(!entry.round063_owned_original && owner.references == 2U && owner_puts == 1U,
                scenario, "descriptor-put-before-endio");
            swapz_round064_current_owner_put(&entry);
            require(owner.references == 2U && owner_puts == 1U, scenario, "no-double-put");
        }
    }
    puts("ROUND064_SLOT_ROUTE_HOST_PASS scenarios=27 NO_AUTH");
    return 0;
}
