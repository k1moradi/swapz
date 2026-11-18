/*
 * Round035 actual source-extracted original Linux mm/page_io.c route helpers.
 * Compiler stubs are an UNTRUSTED host mechanism for exercising the exact C
 * expressions. No original swap area, sector mapping, or slot allocation is
 * created here. No device or swap operation, no fake success admission.
 */
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>

typedef uint8_t u8;
typedef uint64_t u64;
typedef uint64_t sector_t;
typedef struct { unsigned long val; } swp_entry_t;
#define PAGE_SIZE 4096U
#define MAX_SWAPFILES 32U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 0x100U
#define BIO_CLONED 4U
#define bio_op(bio) ((bio)->bi_opf & 0xffU)
#define bio_sectors(bio) ((bio)->bi_iter.bi_size >> 9U)
static inline swp_entry_t swp_entry(unsigned int type, unsigned long offset)
{
    return (swp_entry_t){ .val = ((unsigned long)type << 48U) | offset };
}
static inline unsigned int swp_type(swp_entry_t slot)
{
    return (unsigned int)(slot.val >> 48U);
}
static inline unsigned long swp_offset(swp_entry_t slot)
{
    return slot.val & ((1UL << 48U) - 1UL);
}
struct page { unsigned long dummy; };
struct block_device { int dummy; };
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

/* ROUND035_EXACT_REAL_ORIGINAL_ROUTE_IDENTITY_C */
/* ROUND035_EXACT_REAL_ORIGINAL_ROUTE_GEOMETRY_C */

int main(void)
{
    struct block_device first_device = {}, other_device = {};
    struct page page = {};
    struct bio_vec vector = { .bv_page = &page, .bv_len = PAGE_SIZE };
    struct swap_info_struct active = { .bdev = &first_device };
    struct bio original = {
        .bi_bdev = &first_device, .bi_io_vec = &vector,
        .bi_opf = REQ_OP_WRITE | REQ_SWAP,
        .bi_iter = { .bi_size = PAGE_SIZE, .bi_sector = 8U },
    };
    swp_entry_t source = swp_entry(1U, 37U);
    assert(swapz_round035_route_identity(source, source, 11U, 11U) == 0);
    assert(swapz_round035_route_identity(source, swp_entry(2U, 37U), 11U, 11U) == -ESTALE);
    assert(swapz_round035_route_identity(source, swp_entry(1U, 38U), 11U, 11U) == -ESTALE);
    assert(swapz_round035_route_identity(source, source, 11U, 12U) == -ESTALE);
    assert(swapz_round035_route_identity(source, source, 0U, 11U) == -ESTALE);
    assert(swapz_round035_route_identity(source, source, 11U, 0U) == -ESTALE);
    assert(swapz_round035_route_identity(source, swp_entry(MAX_SWAPFILES, 37U), 11U, 11U) == -ESTALE);
    assert(swapz_round035_route_geometry(&original, &active, 8U) == 0);
    original.bi_bdev = &other_device;
    assert(swapz_round035_route_geometry(&original, &active, 8U) == -ESTALE);
    original.bi_bdev = &first_device;
    assert(swapz_round035_route_geometry(&original, &active, 0U) == -ERANGE);
    assert(swapz_round035_route_geometry(&original, &active, 9U) == -ERANGE);
    assert(swapz_round035_route_geometry(&original, &active, UINT64_MAX) == -ERANGE);
    assert(swapz_round035_route_geometry(&original, &active, 16U) == -ERANGE);
    original.bi_iter.bi_sector = 16U;
    assert(swapz_round035_route_geometry(&original, &active, 16U) == 0);
    original.bi_iter.bi_size = PAGE_SIZE / 2U;
    assert(swapz_round035_route_geometry(&original, &active, 16U) == -EOPNOTSUPP);
    original.bi_iter.bi_size = PAGE_SIZE;
    original.bi_vcnt = 1U;
    assert(swapz_round035_route_geometry(&original, &active, 16U) == -EOPNOTSUPP);
    original.bi_vcnt = 0U;
    original.bi_opf = REQ_OP_READ | REQ_SWAP;
    assert(swapz_round035_route_geometry(&original, &active, 16U) == -EOPNOTSUPP);
    original.bi_opf = REQ_OP_WRITE | REQ_SWAP;
    vector.bv_offset = 1U;
    assert(swapz_round035_route_geometry(&original, &active, 16U) == -EOPNOTSUPP);
    puts("ROUND031_REAL_ROUND035_EXACT_SOURCE_ROUTE_HOST_PASS");
    return 0;
}
