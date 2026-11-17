/* SPDX-License-Identifier: GPL-2.0-only */
/* Round026 host stand-ins, compiling EXACT source extracted from dm-target.c.
 * This is a real code-path test, not an authenticated MM/BIO transport.
 */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t swapz_u8;
typedef uint16_t swapz_u16;
typedef uint32_t swapz_u32;
typedef uint64_t swapz_u64;
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_COMPRESSED 3568U
#define SWAPZ_SEGMENT_BLOCKS 256U
#define REQ_OP_READ 0U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 0x100U
#define bio_op(bio) ((bio)->bi_opf & 0xffU)
#define __used __attribute__((__used__))
#define noinline __attribute__((__noinline__))
#define smp_load_acquire(p) (*(p))
struct mutex { bool held; };
#define lockdep_assert_held(mutex) assert((mutex)->held)
struct swapz_map {
    swapz_u32 start_block, generation, payload_offset, payload_crc32c;
    swapz_u16 payload_length;
    swapz_u8 record_index, extent_blocks;
    unsigned raw:1, valid:1;
};
struct swapz_authority {
    struct swapz_map *maps;
    swapz_u32 logical_pages, physical_blocks;
    swapz_u32 gc_destination, gc_forbidden_victim;
    swapz_u32 extent_sequence;
    swapz_u8 gc_allocation;
    int sequence_error;
};
struct swapz_gc_recovery { bool active; };
struct swapz_dm {
    struct swapz_authority authority;
    struct swapz_map *maps;
    struct swapz_gc_recovery gc_recovery;
    struct mutex ordered_owner;
    bool accepting, failed;
};
struct bio {
    unsigned bi_opf;
    struct { unsigned bi_size; } bi_iter;
};
enum swapz_zswap_admission_phase {
    SWAPZ_ZSWAP_ADMISSION_EMPTY, SWAPZ_ZSWAP_ADMISSION_PREPARED,
    SWAPZ_ZSWAP_ADMISSION_DURABLE, SWAPZ_ZSWAP_ADMISSION_MAPPED,
    SWAPZ_ZSWAP_ADMISSION_ACKED
};
struct swapz_zswap_import_record {
    swapz_u64 logical_page;
    swapz_u32 generation, compressed_crc32c, compressed_length;
};
struct swapz_zswap_admission_transaction {
    struct swapz_zswap_import_record record;
    enum swapz_zswap_admission_phase phase;
    swapz_u8 upper_write_ack_count, teardown_started;
};
static int swapz_extent_sequence_lookup(
    const struct swapz_authority *authority, swapz_u32 start_block,
    swapz_u32 *sequence)
{
    (void)start_block;
    if (authority->sequence_error)
        return authority->sequence_error;
    *sequence = authority->extent_sequence;
    return 0;
}
/* ROUND026_DM_EXACT_FUNCTIONS */
int main(void)
{
    struct swapz_map maps[8] = {{0}};
    struct swapz_dm dm = {
        .authority = { .maps = maps, .logical_pages = 8,
            .physical_blocks = 4096, .extent_sequence = 49,
            .gc_destination = UINT32_MAX,
            .gc_forbidden_victim = UINT32_MAX },
        .maps = maps,
        .ordered_owner = { .held = true },
        .accepting = true
    };
    struct swapz_zswap_admission_transaction transaction = {
        .record = { .logical_page = 2, .generation = 7,
            .compressed_crc32c = 0x1234U, .compressed_length = 100 },
        .phase = SWAPZ_ZSWAP_ADMISSION_ACKED,
        .upper_write_ack_count = 1
    };
    struct bio upper = { .bi_opf = REQ_OP_READ | REQ_SWAP,
                         .bi_iter = { .bi_size = SWAPZ_BLOCK_BYTES } };
    struct swapz_round026_dm_read_snapshot baseline = {};
    struct swapz_round026_dm_read_snapshot invalid;
    unsigned char canary[4096];
    int error;
    maps[2] = (struct swapz_map) {
        .start_block = 256, .generation = 7, .payload_offset = 250,
        .payload_crc32c = 0x1234U, .payload_length = 100,
        .record_index = 2, .extent_blocks = 1, .valid = 1 };
    memset(canary, 0xa5, sizeof(canary));
#define CAPTURE() swapz_round026_dm_capture_read_snapshot(&dm, 2, &baseline)
#define REFUSE() swapz_round026_dm_revalidate_and_refuse( \
    &dm, &baseline, &upper, &transaction, 0, 4096)
    assert(CAPTURE() == 0);
    assert(baseline.logical_page == 2);
    assert(baseline.extent_sequence == 49);
    assert(REFUSE() == -EOPNOTSUPP); /* Stable is STILL no source proof. */
    maps[2].generation = 8; assert(REFUSE() == -ESTALE);
    maps[2].generation = 7;
    maps[2].start_block = 257; assert(REFUSE() == -ESTALE);
    maps[2].start_block = 256;
    maps[2].payload_offset++; assert(REFUSE() == -ESTALE);
    maps[2].payload_offset--;
    maps[2].payload_crc32c++; assert(REFUSE() == -ESTALE);
    maps[2].payload_crc32c--;
    maps[2].record_index++; assert(REFUSE() == -ESTALE);
    maps[2].record_index--;
    maps[2].payload_length++; assert(REFUSE() == -ESTALE);
    maps[2].payload_length--;
    dm.authority.extent_sequence++; assert(REFUSE() == -ESTALE);
    dm.authority.extent_sequence--;
    dm.authority.gc_destination = 16; assert(REFUSE() == -ESTALE);
    dm.authority.gc_destination = UINT32_MAX;
    dm.authority.gc_forbidden_victim = 22; assert(REFUSE() == -ESTALE);
    dm.authority.gc_forbidden_victim = UINT32_MAX;
    dm.authority.gc_allocation = 1; assert(REFUSE() == -ESTALE);
    dm.authority.gc_allocation = 0;
    dm.gc_recovery.active = true; assert(REFUSE() == -ESTALE);
    dm.gc_recovery.active = false;
    maps[2].valid = 0; assert(REFUSE() == -ESTALE);
    maps[2].valid = 1;
    maps[2].raw = 1; assert(REFUSE() == -EOPNOTSUPP);
    maps[2].raw = 0;
    transaction.record.generation = 6; assert(REFUSE() == -ESTALE);
    transaction.record.generation = 7;
    transaction.record.logical_page = 3; assert(REFUSE() == -ESTALE);
    transaction.record.logical_page = 2;
    transaction.upper_write_ack_count = 0; assert(REFUSE() == -EOPNOTSUPP);
    transaction.upper_write_ack_count = 2; assert(REFUSE() == -EOPNOTSUPP);
    transaction.upper_write_ack_count = 1;
    transaction.phase = SWAPZ_ZSWAP_ADMISSION_DURABLE;
    assert(REFUSE() == -EOPNOTSUPP);
    transaction.phase = SWAPZ_ZSWAP_ADMISSION_ACKED;
    transaction.teardown_started = 1; assert(REFUSE() == -EOPNOTSUPP);
    transaction.teardown_started = 0;
    upper.bi_iter.bi_size = 2048; assert(REFUSE() == -EOPNOTSUPP);
    upper.bi_iter.bi_size = 4096;
    upper.bi_opf = REQ_OP_WRITE | REQ_SWAP;
    assert(REFUSE() == -EOPNOTSUPP);
    upper.bi_opf = REQ_OP_READ | REQ_SWAP;
    assert(swapz_round026_dm_revalidate_and_refuse(
        &dm, &baseline, &upper, &transaction, -EIO, 4096) == -EIO);
    assert(swapz_round026_dm_revalidate_and_refuse(
        &dm, &baseline, &upper, &transaction, 0, 4095) == -EIO);
    transaction.record.compressed_crc32c++; assert(REFUSE() == -EBADMSG);
    transaction.record.compressed_crc32c--;
    transaction.record.compressed_length++; assert(REFUSE() == -EBADMSG);
    transaction.record.compressed_length--;
    dm.accepting = false; assert(REFUSE() == -ESHUTDOWN);
    dm.accepting = true;
    dm.failed = true; assert(REFUSE() == -ESHUTDOWN);
    dm.failed = false;
    dm.authority.sequence_error = -EUCLEAN; assert(REFUSE() == -EUCLEAN);
    dm.authority.sequence_error = 0;
    memset(&invalid, 0xa5, sizeof(invalid));
    error = swapz_round026_dm_capture_read_snapshot(&dm, 99, &invalid);
    assert(error == -EOPNOTSUPP);
    for (size_t index = 0; index < sizeof(invalid); ++index)
        assert(((const unsigned char *)&invalid)[index] == 0);
    maps[2].payload_length = 0;
    assert(CAPTURE() == -EUCLEAN);
    maps[2].payload_length = 100;
    maps[2].payload_offset = 4096;
    assert(CAPTURE() == -EUCLEAN);
    maps[2].payload_offset = 250;
    maps[2].start_block = 4096;
    assert(CAPTURE() == -EUCLEAN);
    maps[2].start_block = 256;
    assert(CAPTURE() == 0);
    /* Source slot reuse/GC can restore byte-identical map scalars.
     * Even this ABA case MUST remain NO_GO for compressed admission.
     */
    assert(REFUSE() == -EOPNOTSUPP);
    for (size_t index = 0; index < sizeof(canary); ++index)
        assert(canary[index] == 0xa5);
    puts("ROUND026_DM_EXACT_SNAPSHOT_STALE_AND_NO_GO_PASS");
    return 0;
}
