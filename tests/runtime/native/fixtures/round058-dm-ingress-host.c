/* Rootless stand-in types; the injected helpers are verbatim production C. */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SWAPZ_ROUND058_DM_INGRESS_LIFETIME_TEST 1
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_SECTORS 8U
#define REQ_OP_WRITE 1U
#define REQ_OP_READ 0U
#define REQ_SWAP 16U
#define BIO_CLONED 1U
#define READ_ONCE(value) (value)
#define smp_load_acquire(pointer) (*(pointer))
#define __used __attribute__((used))
#define noinline __attribute__((noinline))
typedef uint64_t sector_t;
struct dm_target { const void *private; sector_t len; };
struct block_device { unsigned int id; };
struct bio_vec { void *bv_page; unsigned int bv_offset, bv_len; };
struct bio {
    const struct block_device *bi_bdev;
    unsigned int bi_opf, bi_flags;
    struct bio_vec *bi_io_vec;
    unsigned short bi_vcnt;
    struct { sector_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;
};
struct swapz_dm {
    const struct dm_target *target;
    const void *maps;
    struct { const void *maps; } authority;
    uint32_t logical_pages;
    bool accepting, failed;
};
static unsigned int bio_op(const struct bio *bio) { return bio->bi_opf & 7U; }
static sector_t bio_sectors(const struct bio *bio) { return bio->bi_iter.bi_size / 512U; }
#define bio_iter_iovec(bio, iterator) ((bio)->bi_io_vec[(iterator).bi_idx])

/* ROUND058_INJECT_TYPES */
/* ROUND058_INJECT_HELPERS */

struct scenario {
    struct swapz_dm context, other_context;
    struct dm_target target, other_target;
    struct block_device device, other_device;
    struct bio_vec vector;
    struct bio upper_bio;
    struct swapz_round058_dm_observation observation;
    unsigned char page[SWAPZ_BLOCK_BYTES];
    int map_identity;
};
static void setup(struct scenario *scenario)
{
    memset(scenario, 0, sizeof(*scenario));
    scenario->context.maps = &scenario->map_identity;
    scenario->context.authority.maps = scenario->context.maps;
    scenario->context.logical_pages = 16U;
    scenario->context.accepting = true;
    scenario->target.private = &scenario->context;
    scenario->target.len = 16U * SWAPZ_SECTORS;
    scenario->context.target = &scenario->target;
    scenario->other_target.private = &scenario->context;
    scenario->other_target.len = scenario->target.len;
    scenario->device.id = 7U;
    scenario->other_device.id = 8U;
    scenario->vector.bv_page = scenario->page;
    scenario->vector.bv_len = SWAPZ_BLOCK_BYTES;
    scenario->upper_bio.bi_bdev = &scenario->device;
    scenario->upper_bio.bi_flags = 1U << BIO_CLONED;
    scenario->upper_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
    scenario->upper_bio.bi_vcnt = 1U;
    scenario->upper_bio.bi_io_vec = &scenario->vector;
    scenario->upper_bio.bi_iter.bi_sector = 8U;
    scenario->upper_bio.bi_iter.bi_size = SWAPZ_BLOCK_BYTES;
}
static void require(bool ok, unsigned int number, const char *stage)
{
    if (!ok) {
        fprintf(stderr, "ROUND058_DM_FIRST_ERROR case=%u stage=%s\n", number, stage);
        fflush(stderr);
        _Exit(1);
    }
}
int main(void)
{
    for (unsigned int scenario_number = 0; scenario_number < 22U; ++scenario_number) {
        struct scenario scenario;
        int observed;
        bool source_is_valid = scenario_number >= 14U;
        setup(&scenario);
        switch (scenario_number) {
        case 0: scenario.upper_bio.bi_flags = 0; break;
        case 1: scenario.upper_bio.bi_iter.bi_sector = 9U; break;
        case 2: scenario.upper_bio.bi_iter.bi_sector = 128U; break;
        case 3: scenario.upper_bio.bi_iter.bi_size = 2048U; break;
        case 4: scenario.upper_bio.bi_opf = REQ_OP_READ | REQ_SWAP; break;
        case 5: scenario.upper_bio.bi_opf = REQ_OP_WRITE; break;
        case 6: scenario.upper_bio.bi_iter.bi_idx = 1U; break;
        case 7: scenario.upper_bio.bi_iter.bi_offset = 8U; break;
        case 8: scenario.upper_bio.bi_vcnt = 2U; break;
        case 9: scenario.vector.bv_offset = 128U; break;
        case 10: scenario.vector.bv_len = SWAPZ_BLOCK_BYTES - 1U; break;
        case 11: scenario.upper_bio.bi_bdev = NULL; break;
        case 12: scenario.context.failed = true; break;
        case 13: scenario.target.private = &scenario.other_context; break;
        default: break;
        }
        observed = swapz_round058_dm_ingress_refuse(
            &scenario.target, &scenario.context, &scenario.upper_bio, &scenario.observation);
        require(observed < 0, scenario_number, "no-compressed-auth");
        require(scenario.observation.shape_observed == source_is_valid,
                scenario_number, "strict-native-clone-shape");
        if (!source_is_valid)
            continue;
        if (scenario_number == 15U)
            scenario.upper_bio.bi_bdev = &scenario.other_device;
        if (scenario_number == 16U)
            scenario.upper_bio.bi_iter.bi_sector += SWAPZ_SECTORS;
        if (scenario_number == 17U)
            scenario.context.target = &scenario.other_target;
        if (scenario_number == 18U)
            scenario.context.accepting = false; /* accepted pre-suspend */
        if (scenario_number == 19U)
            scenario.context.failed = true;
        observed = swapz_round058_dm_terminal_refuse(
            &scenario.context, &scenario.upper_bio, &scenario.observation);
        require(observed == ((scenario_number == 15U || scenario_number == 16U ||
                              scenario_number == 17U) ? -ESTALE :
                             (scenario_number == 19U ? -ESHUTDOWN : -EOPNOTSUPP)),
                scenario_number, "terminal-revalidate-no-ack");
        require(scenario.observation.terminal, scenario_number, "terminal-monotonic");
        require(swapz_round058_dm_terminal_refuse(
                    &scenario.context, &scenario.upper_bio, &scenario.observation) == -EALREADY,
                scenario_number, "terminal-exactly-once");
        if (scenario_number == 20U)
            scenario.target.private = &scenario.other_context;
        observed = swapz_round058_dm_endio_refuse(
            &scenario.target, &scenario.upper_bio, &scenario.observation);
        require(observed == ((scenario_number == 15U || scenario_number == 16U ||
                              scenario_number == 17U || scenario_number == 19U ||
                              scenario_number == 20U) ? -ESTALE : -EOPNOTSUPP),
                scenario_number, "native-endio-no-auth");
        require(scenario.observation.endio_seen, scenario_number, "endio-monotonic");
        require(swapz_round058_dm_endio_refuse(
                    &scenario.target, &scenario.upper_bio, &scenario.observation) == -EALREADY,
                scenario_number, "endio-exactly-once");
    }
    /* Post-admission reissue, trim and replacement must make terminal
     * invalidation monotonic despite later restoration of identical scalars. */
    for (unsigned int mutation = 0; mutation < 5U; ++mutation) {
        struct scenario scenario;
        struct bio_vec replacement_vector;
        setup(&scenario);
        replacement_vector = scenario.vector;
        require(swapz_round058_dm_ingress_refuse(
                    &scenario.target, &scenario.context, &scenario.upper_bio,
                    &scenario.observation) == -EOPNOTSUPP &&
                scenario.observation.shape_observed,
                mutation, "clone-ingress-observed");
        switch (mutation) {
        case 0: scenario.upper_bio.bi_flags = 0U; break;
        case 1: scenario.upper_bio.bi_opf &= ~REQ_SWAP; break;
        case 2: scenario.upper_bio.bi_io_vec = &replacement_vector; break;
        case 3: scenario.upper_bio.bi_iter.bi_idx = 1U; break;
        default: scenario.upper_bio.bi_vcnt = 2U; break;
        }
        require(swapz_round058_dm_terminal_refuse(
                    &scenario.context, &scenario.upper_bio,
                    &scenario.observation) == -ESTALE,
                mutation, "stale-transaction-terminal-rejected");
        require(!scenario.observation.terminal_shape_preserved,
                mutation, "terminal-not-resurrectable");
        /* Restoring all old fields cannot revalidate a retired witness. */
        scenario.upper_bio.bi_flags = 1U << BIO_CLONED;
        scenario.upper_bio.bi_opf = REQ_OP_WRITE | REQ_SWAP;
        scenario.upper_bio.bi_io_vec = &scenario.vector;
        scenario.upper_bio.bi_iter.bi_idx = 0U;
        scenario.upper_bio.bi_vcnt = 1U;
        require(swapz_round058_dm_endio_refuse(
                    &scenario.target, &scenario.upper_bio,
                    &scenario.observation) == -ESTALE,
                mutation, "restored-fields-still-refused");
        require(swapz_round058_dm_endio_refuse(
                    &scenario.target, &scenario.upper_bio,
                    &scenario.observation) == -EALREADY,
                mutation, "one-endio-only");
    }
    /* A valid terminal snapshot cannot override the real changed callback. */
    for (unsigned int mutation = 0; mutation < 4U; ++mutation) {
        struct scenario scenario;
        struct bio_vec replacement_vector;
        setup(&scenario);
        replacement_vector = scenario.vector;
        require(swapz_round058_dm_ingress_refuse(
                    &scenario.target, &scenario.context, &scenario.upper_bio,
                    &scenario.observation) == -EOPNOTSUPP,
                mutation, "endio-initial-ingress");
        require(swapz_round058_dm_terminal_refuse(
                    &scenario.context, &scenario.upper_bio,
                    &scenario.observation) == -EOPNOTSUPP &&
                scenario.observation.terminal_shape_preserved,
                mutation, "endio-valid-terminal-observation");
        if (mutation == 0U)
            scenario.upper_bio.bi_flags = 0U;
        else if (mutation == 1U)
            scenario.upper_bio.bi_io_vec = &replacement_vector;
        else if (mutation == 2U)
            scenario.upper_bio.bi_iter.bi_offset = 8U;
        else
            scenario.upper_bio.bi_opf = REQ_OP_READ | REQ_SWAP;
        require(swapz_round058_dm_endio_refuse(
                    &scenario.target, &scenario.upper_bio,
                    &scenario.observation) == -ESTALE,
                mutation, "changed-endio-bio-refused");
    }
    /* Same ctx/target pointer does NOT preserve table geometry or map tenure.
     * The real callbacks own these objects only until they return. */
    for (unsigned int callback_stage = 0; callback_stage < 2U; ++callback_stage) {
        for (unsigned int mutation = 0; mutation < 5U; ++mutation) {
            struct scenario scenario;
            setup(&scenario);
            require(swapz_round058_dm_ingress_refuse(
                        &scenario.target, &scenario.context, &scenario.upper_bio,
                        &scenario.observation) == -EOPNOTSUPP,
                    mutation, "original-table-ingress");
            if (callback_stage == 1U)
                require(swapz_round058_dm_terminal_refuse(
                            &scenario.context, &scenario.upper_bio,
                            &scenario.observation) == -EOPNOTSUPP &&
                        scenario.observation.terminal_shape_preserved,
                        mutation, "valid-before-table-reload");
            switch (mutation) {
            case 0:
                scenario.target.len -= SWAPZ_SECTORS;
                scenario.context.logical_pages--;
                break;
            case 1: scenario.context.maps = &scenario.other_context; break;
            case 2: scenario.context.authority.maps = &scenario.other_context; break;
            case 3:
                scenario.context.maps = &scenario.other_context;
                scenario.context.authority.maps = scenario.context.maps;
                break;
            default: scenario.context.logical_pages--; break;
            }
            if (callback_stage == 0U) {
                require(swapz_round058_dm_terminal_refuse(
                            &scenario.context, &scenario.upper_bio,
                            &scenario.observation) == -ESTALE,
                        mutation, "stale-table-before-ack-rejected");
                require(!scenario.observation.terminal_shape_preserved,
                        mutation, "failed-table-terminal-sticky");
                /* Reissue may restore the old values, but not old tenure. */
                scenario.target.len = 16U * SWAPZ_SECTORS;
                scenario.context.logical_pages = 16U;
                scenario.context.maps = &scenario.map_identity;
                scenario.context.authority.maps = scenario.context.maps;
            }
            require(swapz_round058_dm_endio_refuse(
                        &scenario.target, &scenario.upper_bio,
                        &scenario.observation) == -ESTALE,
                    mutation, "stale-table-endio-rejected");
        }
    }
    puts("ROUND060_DM_TABLE_HOST_PASS inherited=22 changed_stage=2 changed_table=5 NO_AUTH=1 PHASE_A=BLOCKED");
    return 0;
}
