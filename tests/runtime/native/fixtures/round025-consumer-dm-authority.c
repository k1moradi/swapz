/* SPDX-License-Identifier: GPL-2.0-only */
/* Exact Round025 DM function is inserted from dm-target.c by Python test.
 * Host structures are deliberately synthetic; only matched module Kbuild
 * proves the function also compiles against actual swapz kernel sources.
 */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
typedef uint64_t swapz_u64;
typedef uint32_t swapz_u32;
typedef uint8_t swapz_u8;
#define SWAPZ_BLOCK_BYTES 4096U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 0x100U
#define bio_op(bio) ((bio)->bi_opf & 0xffU)
#define __used __attribute__((__used__))
#define noinline __attribute__((__noinline__))
enum swapz_zswap_admission_phase {
    SWAPZ_ZSWAP_ADMISSION_EMPTY, SWAPZ_ZSWAP_ADMISSION_PREPARED,
    SWAPZ_ZSWAP_ADMISSION_DURABLE, SWAPZ_ZSWAP_ADMISSION_MAPPED,
    SWAPZ_ZSWAP_ADMISSION_ACKED
};
struct swapz_map {
    swapz_u32 generation, payload_crc32c;
    uint16_t payload_length;
    unsigned raw:1, valid:1;
};
struct swapz_authority {
    struct swapz_map *maps;
    swapz_u32 logical_pages;
};
struct swapz_dm { struct swapz_authority authority; };
struct bio {
    unsigned bi_opf;
    struct { unsigned bi_size; } bi_iter;
};
struct swapz_zswap_import_record {
    swapz_u64 logical_page, gc_epoch;
    swapz_u32 generation, compressed_crc32c, compressed_length;
};
struct swapz_zswap_admission_transaction {
    struct swapz_zswap_import_record record;
    enum swapz_zswap_admission_phase phase;
    swapz_u32 physical_extent_bytes;
    swapz_u8 upper_write_ack_count, teardown_started;
};
/* ROUND025_EXACT_DM_PROBE_SOURCE */
int main(void)
{
    struct swapz_map maps[4] = {{0}};
    struct swapz_dm dm = {
        .authority = { .maps = maps, .logical_pages = 4 }
    };
    struct bio upper = {
        .bi_opf = REQ_OP_WRITE | REQ_SWAP,
        .bi_iter = { .bi_size = 4096 }
    };
    struct swapz_zswap_admission_transaction transaction = {
        .record = { .logical_page = 2, .generation = 7,
            .gc_epoch = 11, .compressed_crc32c = 19,
            .compressed_length = 100 },
        .phase = SWAPZ_ZSWAP_ADMISSION_DURABLE,
        .physical_extent_bytes = 4096
    };
    maps[2] = (struct swapz_map) {
        .generation = 7, .payload_crc32c = 19,
        .payload_length = 100, .valid = 1
    };
#define EXPECT_REFUSAL() assert(swapz_round025_dm_authority_kbuild_probe( \
    &dm, &upper, &transaction, 11, 0, 4096) < 0)
    EXPECT_REFUSAL();
    transaction.upper_write_ack_count = 1; EXPECT_REFUSAL();
    transaction.upper_write_ack_count = 0;
    transaction.teardown_started = 1; EXPECT_REFUSAL();
    transaction.teardown_started = 0;
    transaction.record.generation = 8; EXPECT_REFUSAL();
    transaction.record.generation = 7;
    transaction.record.gc_epoch = 12; EXPECT_REFUSAL();
    transaction.record.gc_epoch = 11;
    maps[2].raw = 1; EXPECT_REFUSAL(); maps[2].raw = 0;
    maps[2].valid = 0; EXPECT_REFUSAL(); maps[2].valid = 1;
    maps[2].payload_length = 99; EXPECT_REFUSAL();
    maps[2].payload_length = 100;
    maps[2].payload_crc32c = 0; EXPECT_REFUSAL();
    maps[2].payload_crc32c = 19;
    upper.bi_iter.bi_size = 3568; EXPECT_REFUSAL();
    upper.bi_iter.bi_size = 4096;
    assert(swapz_round025_dm_authority_kbuild_probe(
        &dm, &upper, &transaction, 11, -EIO, 4096) < 0);
    assert(swapz_round025_dm_authority_kbuild_probe(
        &dm, &upper, &transaction, 11, 0, 4095) < 0);
    transaction.record.logical_page = 0; EXPECT_REFUSAL();
    transaction.record.logical_page = 2;
    assert(swapz_round025_dm_authority_kbuild_probe(
        NULL, &upper, &transaction, 11, 0, 4096) < 0);
    puts("ROUND025_REAL_DM_SOURCE_NEGATIVE_ONLY_PASS");
    return 0;
}
