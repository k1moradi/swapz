/* Host stubs; the imported .cfrag is verbatim staged original block/bio.c. */
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SWAPZ_ROUND063_ORIGINAL_DM_OWNER_TEST 1
#define SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST 1
#define SWAPZ_ROUND031_MM_BIO_SOURCE 1
#define SWAPZ_ROUND025_SIDEBAND_CI_ONLY 1
#define REQ_OP_WRITE 1U
#define REQ_OP_READ 0U
#define REQ_SWAP 16U
#define BIO_CLONED 1U
#define SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK 7U
#define EXPORT_SYMBOL_GPL(symbol)

struct swapz_ci_owned_payload { unsigned int references; bool valid; bool freed; };
struct bio_vec { void *bv_page; unsigned int bv_offset; unsigned int bv_len; };
struct bio {
    unsigned int bi_opf, bi_flags, bi_swap_origin;
    struct bio_vec *bi_io_vec;
    unsigned int bi_vcnt;
    struct { unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
    struct swapz_ci_owned_payload *bi_swapz_ci_sideband;
};
static __attribute__((unused)) unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 7U; }
static struct swapz_ci_owned_payload *swapz_ci_owned_get(struct swapz_ci_owned_payload *owner)
{
    if (!owner || !owner->references || owner->freed)
        return NULL;
    owner->references++;
    return owner;
}
static __attribute__((unused)) bool swapz_ci_owned_valid(const struct swapz_ci_owned_payload *owner)
{
    return owner && owner->valid && !owner->freed;
}
static void swapz_ci_owned_put(struct swapz_ci_owned_payload *owner)
{
    if (!owner)
        return;
    if (!owner->references) {
        fputs("ROUND063_OWNER_FIRST_ERROR double-put\n", stderr);
        _Exit(1);
    }
    if (--owner->references == 0U)
        owner->freed = true;
}
/* ROUND063_INJECT_SOURCE */

static void require(bool condition, unsigned int scenario, const char *label)
{
    if (!condition) {
        fprintf(stderr, "ROUND063_OWNER_FIRST_ERROR scenario=%u stage=%s\n", scenario, label);
        _Exit(1);
    }
}
int main(void)
{
    unsigned char page[4096] = { 0 };
    for (unsigned int scenario = 0U; scenario < 15U; ++scenario) {
        struct swapz_ci_owned_payload owner = { .references = 2U, .valid = true };
        struct bio_vec vector = { .bv_page = page, .bv_offset = 0U, .bv_len = 4096U };
        struct bio clone = {
            .bi_opf = REQ_OP_WRITE | REQ_SWAP,
            .bi_flags = 1U << BIO_CLONED,
            .bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
            .bi_io_vec = &vector,
            .bi_iter = { .bi_size = 4096U },
            .bi_swapz_ci_sideband = &owner,
        };
        struct swapz_ci_owned_payload *held;
        bool should_acquire = scenario == 0U || scenario == 14U;
        switch (scenario) {
        case 1: clone.bi_opf = REQ_OP_READ | REQ_SWAP; break;
        case 2: clone.bi_opf = REQ_OP_WRITE; break;
        case 3: clone.bi_flags = 0U; break;
        case 4: clone.bi_swap_origin = 0U; break;
        case 5: clone.bi_iter.bi_size = 2048U; break;
        case 6: clone.bi_iter.bi_idx = 1U; break;
        case 7: clone.bi_iter.bi_offset = 8U; break;
        case 8: clone.bi_vcnt = 1U; break;
        case 9: vector.bv_page = NULL; break;
        case 10: vector.bv_offset = 8U; break;
        case 11: vector.bv_len = 2048U; break;
        case 12: clone.bi_swapz_ci_sideband = NULL; break;
        case 13: owner.valid = false; break;
        default: break;
        }
        held = swapz_round063_original_dm_owner_get(&clone);
        require((held != NULL) == should_acquire, scenario, "accept-owning-clone-only");
        require(owner.references == (should_acquire ? 3U : 2U), scenario,
                "balanced-ref-acquisition");
        if (!should_acquire)
            continue;
        swapz_ci_owned_put(&owner); /* Original page_io BIO reference retired. */
        swapz_ci_owned_put(&owner); /* DM-owned clone reference retired/requeued. */
        require(owner.references == 1U && !owner.freed, scenario,
                "DM-ref-outlives-native-source-and-clone");
        /* The *actual* target must release its independently acquired ref. */
        swapz_round063_original_dm_owner_put(held);
        require(owner.references == 0U && owner.freed, scenario, "DM-terminal-put");
    }
    /* A dead previously retained source must never be reacquired. */
    {
        struct swapz_ci_owned_payload dead = { .references = 0U, .valid = true, .freed = true };
        struct bio_vec vector = { .bv_page = page, .bv_len = 4096U };
        struct bio clone = {
            .bi_opf = REQ_OP_WRITE | REQ_SWAP,
            .bi_flags = 1U << BIO_CLONED,
            .bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK,
            .bi_io_vec = &vector,
            .bi_iter = { .bi_size = 4096U },
            .bi_swapz_ci_sideband = &dead,
        };
        require(swapz_round063_original_dm_owner_get(&clone) == NULL && dead.references == 0U,
                15U, "reject-retired-original-owner");
    }
    fputs("ROUND063_ORIGINAL_DM_OWNER_HOST_PASS scenarios=16 NO_AUTH\n", stdout);
    return 0;
}
