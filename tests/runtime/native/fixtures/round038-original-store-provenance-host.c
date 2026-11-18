/*
 * Host-only exact extracted original mm/zswap.c private provenance check.
 * These are synthetic stimulus values, never original active zswap STORE.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

typedef uint64_t u64;
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define SHA256_DIGEST_SIZE 32U

/* ROUND038_EXACT_ORIGINAL_STORE_PROVENANCE_C */

int main(void)
{
    struct swapz_round038_store_observation accepted = {
        .source_swap_entry = 0x1000000000025ULL,
        .allocation_epoch = 17U,
        .stored_identity = 23U,
        .compressed_crc32c = 0x13579bdfU,
        .compressed_length = 288U,
        .decoded_length = 4096U,
        .representation_version = 1U,
        .codec = 1U,
        .original_sha256 = { 1U, 2U, 3U },
        .stored_in_original_tree = true,
        .source_owner_live = true,
        .folio_locked = true,
        .original_bio_full_4096 = true,
    };
    struct swapz_round038_store_observation consumed = accepted;
    struct swapz_round038_store_observation unchanged = consumed;
#define CHECK(expected) \
    assert(swapz_round038_store_observation_check(&accepted, &consumed) == (expected))
    CHECK(-EOPNOTSUPP);
    consumed.current_slot_ref_held = true;
    consumed.current_dm_gc_ref_held = true;
    CHECK(-EOPNOTSUPP);
    consumed = accepted;
    consumed.allocation_epoch++;
    CHECK(-ESTALE);
    consumed = accepted;
    consumed.stored_identity++;
    CHECK(-ESTALE);
    consumed = accepted;
    consumed.source_swap_entry++;
    CHECK(-ESTALE);
    consumed = accepted;
    consumed.compressed_crc32c ^= 1U;
    CHECK(-EBADMSG);
    consumed = accepted;
    consumed.original_sha256[1] ^= 1U;
    CHECK(-EBADMSG);
    consumed = accepted;
    consumed.compressed_length = 0;
    CHECK(-EOPNOTSUPP);
    consumed.compressed_length = 3569U;
    CHECK(-EOPNOTSUPP);
    consumed = accepted;
    consumed.codec = 2U;
    CHECK(-EOPNOTSUPP);
    consumed = accepted;
    consumed.source_owner_live = false;
    CHECK(-ESTALE);
    consumed = accepted;
    consumed.folio_locked = false;
    CHECK(-ESTALE);
    consumed = accepted;
    consumed.original_bio_full_4096 = false;
    CHECK(-EOPNOTSUPP);
    consumed = accepted;
    assert(memcmp(&consumed, &unchanged, sizeof(unchanged)) == 0);
    assert(swapz_round038_store_observation_check(NULL, &consumed) == -EINVAL);
    puts("ROUND038_ORIGINAL_STORE_PROVENANCE_EXTRACTED_C_HOST_PASS");
    return 0;
}
