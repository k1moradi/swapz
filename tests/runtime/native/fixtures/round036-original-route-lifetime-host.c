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

/* ROUND036_REAL_ORIGINAL_SOURCE_LIFETIME_STRUCT_AND_HELPER */

int main(void)
{
    struct block_device first_area = {}, recycled_area = {}, new_mapper = {};
    struct page original_page = {};
    struct bio_vec original_vector = {
        .bv_page = &original_page, .bv_len = PAGE_SIZE,
    };
    struct bio original_bio = {
        .bi_bdev = &first_area,
        .bi_io_vec = &original_vector,
        .bi_opf = REQ_OP_WRITE | REQ_SWAP,
        .bi_iter = { .bi_sector = 4096U, .bi_size = PAGE_SIZE },
    };
    struct swapz_round036_route_lifetime source = {
        .source_slot = swp_entry(1U, 37U),
        .allocation_epoch = 17U,
        .stored_identity = 27U,
        .source_bdev = &first_area,
        .source_sector = 4096U,
        .target_generation = 31U,
        .extent_generation = 41U,
        .original_folio_unlocked = true,
        .writeback_in_flight = true,
        .original_bio_live = true,
        .original_owner_live = true,
    };
    struct swapz_round036_route_lifetime current = source;
#define CHECK(expected, area, slot, dm) \
    assert(swapz_round036_route_lifetime_check( \
        &source, &current, &original_bio, area, slot, dm) == (expected))

    /* No current original lifetime/DM authority, even if spoofed true. */
    CHECK(-EOPNOTSUPP, false, false, false);
    CHECK(-EOPNOTSUPP, true, false, true);
    CHECK(-EOPNOTSUPP, true, true, true);

    /* ABA same packed original source slot with a new allocator epoch. */
    current.allocation_epoch = 18U;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.source_slot = swp_entry(2U, 37U);
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.stored_identity = 28U;
    CHECK(-ESTALE, true, true, true);

    /* Swapoff + swapon same type to a distinct genuine original bdev. */
    current = source;
    current.source_bdev = &recycled_area;
    CHECK(-ESTALE, true, true, true);

    /* External target can remap even while a transient MM area ref exists. */
    current = source;
    current.target_bdev = &new_mapper;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.target_generation++;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.extent_generation++;
    CHECK(-ESTALE, true, true, true);

    /* Real original swapfile extent may NOT be swp_offset * 8. */
    current = source;
    current.source_sector = 37U * 8U;
    CHECK(-ESTALE, true, true, true);
    current.source_sector = 0U;
    CHECK(-ERANGE, true, true, true);
    current.source_sector = 9U;
    CHECK(-ERANGE, true, true, true);
    current.source_sector = UINT64_MAX;
    CHECK(-ERANGE, true, true, true);

    /* Original async BIO uninit, clone, split and folio unlock lifetime. */
    current = source;
    current.original_bio_live = false;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.original_owner_live = false;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.original_folio_unlocked = false;
    CHECK(-ESTALE, true, true, true);
    current = source;
    current.writeback_in_flight = false;
    CHECK(-ESTALE, true, true, true);
    current = source;
    original_bio.bi_flags |= (1U << BIO_CLONED);
    CHECK(-EOPNOTSUPP, true, true, true);
    original_bio.bi_flags = 0;
    original_bio.bi_iter.bi_size = 2048U;
    CHECK(-EOPNOTSUPP, true, true, true);
    original_bio.bi_iter.bi_size = PAGE_SIZE;
    original_bio.bi_vcnt = 1U;
    CHECK(-EOPNOTSUPP, true, true, true);
    original_bio.bi_vcnt = 0;
    original_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
    CHECK(-EOPNOTSUPP, true, true, true);

    /* All snapshots unchanged by repeated refusal; no authority output. */
    original_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
    CHECK(-EOPNOTSUPP, true, true, true);
    CHECK(-EOPNOTSUPP, true, true, true);
    assert(swapz_round036_route_lifetime_check(
        &source, &current, NULL, true, true, true) == -EINVAL);

    puts("ROUND031_REAL_ROUND036_ORIGINAL_ROUTE_LIFETIME_HOST_PASS");
    return 0;
}
