/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * Round073 Agent9: rootless source-compiled geometry and first-page sentinel.
 * authority.h, codec.h and superblock.h are exact current source; the verifier
 * injects both unchanged dm-target.c range/sector functions at the marker.
 * No physical I/O; stage() is an explicit RAM-only lower-copy model.
 */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include "authority.h"
#include "superblock.h"

_Static_assert(sizeof(struct swapz_map) == 20, "RAM map must remain 20 bytes");
_Static_assert(offsetof(struct swapz_map, payload_length) == 16, "map layout changed");
_Static_assert(SWAPZ_CODEC_METADATA_ON_MEDIA == 0U, "no persistent descriptors");
_Static_assert(SWAPZ_BLOCK_BYTES == 4096U, "exactly one Linux page");
_Static_assert(SWAPZ_SEGMENT_BLOCKS == 256U, "1MiB segment");
_Static_assert(SWAPZ_LINUX_SWAP_HEADER_BLOCKS == 1U, "one protected first page");
typedef uint64_t sector_t;
#define SWAPZ_SECTORS (SWAPZ_BLOCK_BYTES / 512U)
struct swapz_dm {
    swapz_u32 physical_blocks;
    swapz_u32 data_start_block;
    swapz_u32 *segment_backing_pages;
};
/* ROUND073_DM_BOUNDARY */
#define CHECK(ok, label) do { \
    if (!(ok)) { \
        fprintf(stderr, "ROUND073_GEOMETRY_SEMANTIC_FAILURE case=%s line=%d\n", \
                (label), __LINE__); \
        return 3; \
    } \
} while (0)

static uint8_t backing[(1U + 4U * SWAPZ_SEGMENT_BLOCKS) * SWAPZ_BLOCK_BYTES];
static uint8_t header_before[SWAPZ_SUPERBLOCK_BYTES];
static uint8_t partition_table[512];
static uint8_t partition_before[512];

static void put_u32(uint8_t *target, uint32_t number, bool byte_swapped)
{
    if (byte_swapped) {
        target[0] = (uint8_t)(number >> 24);
        target[1] = (uint8_t)(number >> 16);
        target[2] = (uint8_t)(number >> 8);
        target[3] = (uint8_t)number;
    } else {
        target[0] = (uint8_t)number;
        target[1] = (uint8_t)(number >> 8);
        target[2] = (uint8_t)(number >> 16);
        target[3] = (uint8_t)(number >> 24);
    }
}

static void header(uint32_t last_page, uint32_t bad_pages, bool swapped)
{
    static const char signature[] = "SWAPSPACE2";
    memset(backing, 0, SWAPZ_SUPERBLOCK_BYTES);
    put_u32(backing + SWAPZ_LINUX_SWAP_VERSION_OFFSET, 1U, swapped);
    put_u32(backing + SWAPZ_LINUX_SWAP_LAST_PAGE_OFFSET, last_page, swapped);
    put_u32(backing + SWAPZ_LINUX_SWAP_BAD_PAGES_OFFSET, bad_pages, swapped);
    for (unsigned int index = 0; index < SWAPZ_LINUX_SWAP_UUID_BYTES; ++index)
        backing[SWAPZ_LINUX_SWAP_UUID_OFFSET + index] = (uint8_t)(0xa0U + index);
    memcpy(backing + SWAPZ_SUPERBLOCK_BYTES - sizeof(signature) + 1U,
           signature, sizeof(signature) - 1U);
}

static int capacity(void)
{
    swapz_u32 reserve = 0xdeadbeefU;
    CHECK(!swapz_authority_capacity_window(0U, 1024U, &reserve), "logical-zero");
    CHECK(reserve == 0xdeadbeefU, "failure-leaves-reserve-untouched");
    CHECK(!swapz_authority_capacity_window(1U, 512U, &reserve), "two-gc-segments");
    CHECK(!swapz_authority_capacity_window(1U, 768U, &reserve), "cow-headroom");
    CHECK(!swapz_authority_capacity_window(256U, 1023U, &reserve), "segment-floor");
    CHECK(swapz_authority_capacity_window(256U, 1024U, &reserve), "four-segment-max");
    CHECK(reserve == 512U, "two-segment-reserve-exact");
    /* The minimum COMPARISON must still apply if ceil(pages/8) lies
     * between one and two segments. Mutation of the separate assignment
     * cannot be used to cover this independent threshold condition. */
    CHECK(swapz_authority_capacity_window(2048U, 3328U, &reserve),
          "gc-minimum-threshold-admission");
    CHECK(reserve == 512U, "gc-minimum-threshold-exact");
    CHECK(!swapz_authority_capacity_window(257U, 1024U, &reserve), "raw-overfill");
    CHECK(reserve == 512U, "reserve-no-write-on-failure");
    CHECK(swapz_authority_capacity_window(4097U, 6145U, &reserve), "ceil-reserve");
    CHECK(reserve == 513U, "ceil-reserve-exact");
    CHECK(!swapz_authority_capacity_window(UINT32_MAX, UINT32_MAX, &reserve),
          "u32-near-overflow");
    CHECK(!swapz_authority_capacity_window(UINT32_MAX - 256U, UINT32_MAX,
                                            &reserve), "u32-near-overflow2");
    CHECK(swapz_authority_capacity_window(512U, 1280U, &reserve), "five-segment-max");
    CHECK(!swapz_authority_capacity_window(513U, 1280U, &reserve), "five-segment-overfill");
    return 0;
}

static int linux_header(void)
{
    struct swapz_linux_swap_layout layout = {0};
    header(1024U, 0U, false);
    CHECK(swapz_linux_swap_header_parse(backing, sizeof(backing), &layout), "linux-v1");
    /* The on-disk Linux UUID position is independently fixed at offset
     * 1036; deriving this expectation from a mutated source constant
     * would make an off-by-one bug invisible to the host fixture. */
    for (unsigned int index = 0; index < 16U; ++index)
        CHECK(backing[1036U + index] == (uint8_t)(0xa0U + index),
              "fixed-swapspace2-uuid-offset");
    CHECK(layout.last_page == 1024U && layout.bad_pages == 0U &&
          layout.byte_swapped == 0U, "header-fields");
    CHECK(swapz_linux_swap_clean_segment_count(backing, &layout, 256U) == 4U,
          "four-clean-segments");
    header(1024U, 0U, true);
    CHECK(swapz_linux_swap_header_parse(backing, sizeof(backing), &layout) &&
          layout.byte_swapped == 1U, "byte-swapped-v1");
    header(1025U, 0U, false);
    CHECK(!swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "last-page-outside-device");
    header(1024U, 0U, false);
    backing[SWAPZ_SUPERBLOCK_BYTES - 1U] = 'X';
    CHECK(!swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "invalid-signature");
    header(1024U, 1U, false);
    CHECK(!swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "bad-page-zero");
    put_u32(backing + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET, 1U, false);
    CHECK(swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "one-bad-page");
    CHECK(swapz_linux_swap_clean_segment_count(backing, &layout, 256U) == 3U,
          "bad-whole-segment-elided");
    header(1024U, 2U, false);
    put_u32(backing + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET, 1U, false);
    put_u32(backing + SWAPZ_LINUX_SWAP_BAD_PAGE_LIST_OFFSET + 4U, 2U, false);
    CHECK(swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "two-bad-pages-same-segment");
    CHECK(swapz_linux_swap_clean_segment_count(backing, &layout, 256U) == 3U,
          "bad-segment-count-deduplicated");
    header(1024U, 0U, false);
    CHECK(!swapz_linux_swap_header_parse(backing, 0U, &layout), "zero-device");
    CHECK(!swapz_linux_swap_header_parse(backing, SWAPZ_SUPERBLOCK_BYTES,
                                         &layout), "single-page-device");
    return 0;
}

static int backing_address_and_padding(void)
{
    struct swapz_dm context = {.physical_blocks = 1024U,
                               .data_start_block = 1U,
                               .segment_backing_pages = NULL};
    const unsigned int block_counts[] = {1U, 2U, 4U};
    /* Runtime checks (not compile-time failures) catch a changed current
     * source extent limit; every semantic mutant must compile and execute. */
    static uint8_t original[SWAPZ_BLOCK_BYTES];
    struct swapz_linux_swap_layout layout = {0};

    CHECK(swapz_backing_range_valid(&context, 0U, 1U), "first-data-block");
    CHECK(!swapz_backing_range_valid(&context, 0U, 0U), "zero-extent");
    CHECK(!swapz_backing_range_valid(&context, 255U, 2U), "segment-boundary");
    CHECK(!swapz_backing_range_valid(&context, 1023U, 2U), "device-boundary");
    CHECK(swapz_backing_range_valid(&context, 1023U, 1U), "exact-end");
    CHECK(swapz_backing_data_sector(&context, 0U) == 8U, "protected-page-skipped");
    CHECK(swapz_backing_data_sector(&context, 1023U) == 1024U * 8U,
          "last-sector");

    header(1024U, 0U, false);
    CHECK(swapz_linux_swap_header_parse(backing, sizeof(backing), &layout),
          "pre-write-header-admission");
    CHECK(swapz_linux_swap_clean_segment_count(backing, &layout, 256U) == 4U,
          "pre-write-layout-admission");
    CHECK(swapz_authority_capacity_window(256U, 1024U, NULL),
          "pre-write-capacity-admission");
    memcpy(header_before, backing, sizeof(header_before));
    memset(partition_table, 0x5a, sizeof(partition_table));
    memcpy(partition_before, partition_table, sizeof(partition_before));
    for (unsigned int index = 0; index < SWAPZ_BLOCK_BYTES; ++index)
        original[index] = (uint8_t)((index * 17U + 1U) & 255U);
    for (unsigned int extent = 0; extent < 3U; ++extent) {
        const unsigned int blocks = block_counts[extent];
        CHECK(blocks <= SWAPZ_MAX_BLOCKS, "source-extent-class-bounds");
        const unsigned int start = extent * 4U;
        const size_t physical_bytes = (size_t)blocks * SWAPZ_BLOCK_BYTES;
        const size_t payload_bytes = extent == 0U ? SWAPZ_BLOCK_BYTES :
                                     (extent == 1U ? 1300U : 2700U);
        const sector_t sector = swapz_backing_data_sector(&context, start);
        const size_t offset = (size_t)sector * 512U;
        CHECK(swapz_backing_range_valid(&context, start, (swapz_u16)blocks),
              "bounded-extent");
        CHECK(offset >= SWAPZ_SUPERBLOCK_BYTES &&
              offset <= sizeof(backing) - physical_bytes, "physical-bound");
        /* Modeled RAM-only lower store. The real DM owner remains read-only. */
        memset(backing + offset, 0, physical_bytes);
        memcpy(backing + offset, original, payload_bytes);
        CHECK(!memcmp(backing + offset, original, payload_bytes), "payload-only");
        for (size_t i = payload_bytes; i < physical_bytes; ++i)
            CHECK(backing[offset + i] == 0U, "deterministic-zero-padding");
        CHECK(!memcmp(header_before, backing, sizeof(header_before)),
              "immutable-first4096-uuid-signature");
        CHECK(!memcmp(partition_before, partition_table, sizeof(partition_before)),
              "partition-table-sentinel");
    }
    {
        swapz_u32 sparse_pages[] = {257U, 513U, 769U};
        context.segment_backing_pages = sparse_pages;
        context.physical_blocks = 3U * SWAPZ_SEGMENT_BLOCKS;
        CHECK(swapz_backing_data_sector(&context, 0U) == 257U * 8U,
              "sparse-segment-skip");
        CHECK(swapz_backing_data_sector(&context, 256U + 9U) ==
              (513U + 9U) * 8U, "sparse-offset");
        CHECK(!swapz_backing_range_valid(&context, 255U, 4U),
              "sparse-discontinuity-guard");
        CHECK(swapz_backing_range_valid(&context, 767U, 1U),
              "sparse-exact-end");
    }
    return 0;
}
int main(void)
{
    int status = capacity();
    if (status) return status;
    status = linux_header();
    if (status) return status;
    status = backing_address_and_padding();
    if (status) return status;
    puts("ROUND073_GEOMETRY_SOURCE_LINKED_PASS header=4096 map=20 "
         "extent_kib=4,8,16 source_auth=0 physical_io=0");
    return 0;
}
