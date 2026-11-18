/*
 * Exact Round036 original mm/page_io.c C extracted into a host-only test.
 * These structs/addresses are fake bounded examples; no real MM allocation,
 * swapoff, original zswap pressure eviction, DM mapping or physical IO.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>

typedef uint64_t u64;
typedef uint64_t sector_t;
typedef struct { unsigned long val; } swp_entry_t;
#define PAGE_SIZE 4096U
#define MAX_SWAPFILES 32U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 0x100U
#define BIO_CLONED 4U
#define bio_op(source_bio) ((source_bio)->bi_opf & 0xffU)
#define bio_sectors(source_bio) ((source_bio)->bi_iter.bi_size >> 9U)
static inline swp_entry_t swp_entry(unsigned int type, unsigned long offset)
{
    return (swp_entry_t){ .val = ((unsigned long)type << 48U) | offset };
}
static inline unsigned int swp_type(swp_entry_t slot)
{
    return (unsigned int)(slot.val >> 48U);
}
struct page { unsigned int opaque; };
struct block_device { unsigned int opaque; };
struct bio_vec {
    struct page *bv_page;
    unsigned int bv_len;
    unsigned int bv_offset;
};
struct bvec_iter {
    sector_t bi_sector;
    unsigned int bi_size, bi_idx, bi_offset;
};
struct bio {
    struct block_device *bi_bdev;
    struct bvec_iter bi_iter;
    struct bio_vec *bi_io_vec;
    unsigned int bi_opf, bi_flags, bi_vcnt;
};

struct swap_info_struct { struct block_device *bdev; };
/* ROUND037_EXACT_ORIGINAL_MM_SCOPE_C */

int main(void)
{
    struct block_device area_device = {}, replacement_device = {};
    struct swap_info_struct area = { .bdev = &area_device };
    struct page original_page = {};
    struct bio_vec original_vector = {
        .bv_page = &original_page, .bv_len = PAGE_SIZE,
    };
    struct bio original_bio = {
        .bi_bdev = &area_device,
        .bi_io_vec = &original_vector,
        .bi_opf = REQ_OP_WRITE | REQ_SWAP,
        .bi_iter = { .bi_sector = 4096U, .bi_size = 4096U },
    };
    struct swapz_round037_mm_owner_scope observation = {
        .original_slot = swp_entry(1U, 37U),
        .initial_epoch = 17U,
        .final_epoch = 17U,
        .active_area = &area,
        .source_device = &area_device,
        .original_sector = 4096U,
        .area_ref_held = true,
        .source_bio_live = true,
        .owner_live = true,
        .folio_unlocked = true,
    };
#define CHECK(expected, slot, epoch, lower_sector, owner, lease, gc) \
    assert(swapz_round037_mm_scope_check( \
        &observation, &original_bio, slot, epoch, &area, \
        lower_sector, owner, lease, gc) == (expected))
    CHECK(-EOPNOTSUPP, observation.original_slot, 17U, 4096U,
          true, false, false);
    CHECK(-EOPNOTSUPP, observation.original_slot, 17U, 4096U,
          true, true, true);
    observation.final_epoch++;
    CHECK(-ESTALE, observation.original_slot, 17U, 4096U,
          true, true, true);
    observation.final_epoch--;
    CHECK(-ESTALE, swp_entry(2U, 37U), 17U, 4096U,
          true, true, true);
    area.bdev = &replacement_device;
    CHECK(-ESTALE, observation.original_slot, 17U, 4096U,
          true, true, true);
    area.bdev = &area_device;
    CHECK(-ESTALE, observation.original_slot, 17U, 296U,
          true, true, true);
    CHECK(-ERANGE, observation.original_slot, 17U, 0U,
          true, true, true);
    original_bio.bi_iter.bi_size = 2048U;
    CHECK(-EOPNOTSUPP, observation.original_slot, 17U, 4096U,
          true, true, true);
    original_bio.bi_iter.bi_size = 4096U;
    observation.source_bio_live = false;
    CHECK(-ESTALE, observation.original_slot, 17U, 4096U,
          true, true, true);
    observation.source_bio_live = true;
    CHECK(-ESTALE, observation.original_slot, 17U, 4096U,
          false, true, true);
    assert(swapz_round037_mm_scope_detach(&observation) == &area);
    assert(swapz_round037_mm_scope_detach(&observation) == NULL);
    CHECK(-ESTALE, observation.original_slot, 17U, 4096U,
          true, true, true);
    puts("ROUND031_REAL_ROUND037_ORIGINAL_MM_SCOPE_HOST_PASS");
    return 0;
}
