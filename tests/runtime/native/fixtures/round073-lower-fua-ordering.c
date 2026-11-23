/* Round073 Agent8: deterministic SOURCE-ANCHORED HOST MODEL, not production DM.
 * The verifier checks the pinned src/kernel/dm-target.c git-blob digest and
 * named lower/flush/finalize statements before running this independent model.
 * No actual bio, block device, dm_io(), durability, or kernel execution.
 * All callback invocations are serialized by the fixture; real IRQ/worker
 * interleavings and lifetime must be qualified separately on original Linux.
 */
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#ifndef MUTANT_ID
#define MUTANT_ID 0
#endif

struct transaction {
    unsigned blocks;
    unsigned completed_blocks;
    unsigned generation;
    unsigned expected_generation;
    unsigned reader_pins;
    bool preflush_required;
    bool preflush_complete;
    bool fua_required;
    bool lower_submitted;
    bool lower_complete;
    bool flush_complete;
    bool published;
    bool stopped;
    bool terminal;
    bool old_extent_reclaimed;
    bool predecessor_pending;
    unsigned acknowledgement_count;
    int acknowledgement_error;
    int first_error;
};

static void record_failure(struct transaction *transaction, int error)
{
#if MUTANT_ID == 9
    transaction->first_error = error;
#else
    if (transaction->first_error == 0)
        transaction->first_error = error;
#endif
}

static void acknowledge(struct transaction *transaction, int error)
{
#if MUTANT_ID == 5
    /* Broken duplicate notification can acknowledge the upper BIO twice. */
#else
    if (transaction->acknowledgement_count != 0)
        return;
#endif
    transaction->acknowledgement_count++;
    transaction->acknowledgement_error = error;
}

static void fail_transaction(struct transaction *transaction, int error)
{
    record_failure(transaction, error);
    transaction->terminal = true;
    acknowledge(transaction, transaction->first_error);
}

static bool admit(struct transaction *transaction, unsigned blocks,
                  bool preflush_required, bool fua_required)
{
#if MUTANT_ID == 11
    bool size_valid = blocks != 0;
#else
    bool size_valid = blocks == 1U || blocks == 2U || blocks == 4U;
#endif
    if (!size_valid || transaction->stopped)
        return false;
    transaction->blocks = blocks;
    transaction->generation = 7;
    transaction->expected_generation = 7;
    transaction->preflush_required = preflush_required;
    transaction->preflush_complete = !preflush_required;
    transaction->fua_required = fua_required;
    return true;
}

static void complete_preflush(struct transaction *transaction, int error)
{
    if (transaction->terminal || !transaction->preflush_required)
        return;
    if (error != 0) {
        fail_transaction(transaction, error);
        return;
    }
    transaction->preflush_complete = true;
}

static bool submit_lower_write(struct transaction *transaction)
{
#if MUTANT_ID == 10
    bool barrier_ready = true;
#else
    bool barrier_ready = transaction->preflush_complete;
#endif
    if (transaction->terminal || transaction->stopped || !barrier_ready)
        return false;
    transaction->lower_submitted = true;
#if MUTANT_ID == 1
    acknowledge(transaction, 0);
#endif
    return true;
}

static void maybe_publish(struct transaction *transaction)
{
    if (transaction->terminal || !transaction->lower_complete)
        return;
#if MUTANT_ID == 2
    bool flush_ready = true;
#else
    bool flush_ready = !transaction->fua_required || transaction->flush_complete;
#endif
#if MUTANT_ID == 7
    bool generation_valid = true;
#else
    bool generation_valid =
        transaction->generation == transaction->expected_generation;
#endif
#if MUTANT_ID == 14
    bool predecessor_complete = true;
#else
    bool predecessor_complete = !transaction->predecessor_pending;
#endif
    if (!flush_ready || !predecessor_complete)
        return;
    if (!generation_valid) {
        fail_transaction(transaction, -ESTALE);
        return;
    }
    transaction->published = true;
    acknowledge(transaction, 0);
}

static void complete_lower_write(struct transaction *transaction, int error,
                                 unsigned completed_blocks)
{
#if MUTANT_ID == 6
    if (!transaction->lower_submitted ||
        (transaction->lower_complete && !transaction->terminal))
#else
    if (transaction->terminal || !transaction->lower_submitted ||
        transaction->lower_complete)
#endif
        return;
    if (transaction->stopped) {
#if MUTANT_ID == 6
        transaction->published = true; /* Late callback after teardown. */
#else
        fail_transaction(transaction, -ESHUTDOWN);
#endif
        return;
    }
#if MUTANT_ID == 3
    error = 0;
#endif
    if (error != 0) {
        fail_transaction(transaction, error);
        return;
    }
#if MUTANT_ID == 12
    bool complete = completed_blocks != 0U;
#else
    bool complete = completed_blocks == transaction->blocks;
#endif
    if (!complete) {
        fail_transaction(transaction, -EIO);
        return;
    }
    transaction->completed_blocks = completed_blocks;
    transaction->lower_complete = true;
    maybe_publish(transaction);
}

static void complete_fua_flush(struct transaction *transaction, int error)
{
#if MUTANT_ID == 13
    if (transaction->terminal || !transaction->fua_required)
        return;
    transaction->lower_complete = true; /* Accepts flush before WRITE. */
#else
    if (transaction->terminal || !transaction->lower_complete ||
        !transaction->fua_required)
        return;
#endif
    if (error != 0) {
#if MUTANT_ID == 4
        transaction->flush_complete = true;
        maybe_publish(transaction);
#else
#if MUTANT_ID == 15
        fail_transaction(transaction, -EUCLEAN); /* Masks flush errno. */
#else
        fail_transaction(transaction, error);
#endif
#endif
        return;
    }
    transaction->flush_complete = true;
    maybe_publish(transaction);
}

static void finish_predecessor(struct transaction *transaction)
{
    transaction->predecessor_pending = false;
    maybe_publish(transaction);
}

static void stop_target(struct transaction *transaction)
{
    transaction->stopped = true;
    if (!transaction->terminal && transaction->lower_submitted &&
        !transaction->published)
        fail_transaction(transaction, -ESHUTDOWN);
}

static void release_reader(struct transaction *transaction)
{
    if (transaction->reader_pins != 0)
        transaction->reader_pins--;
#if MUTANT_ID == 8
    if (transaction->published)
#else
    if (transaction->published && transaction->reader_pins == 0)
#endif
        transaction->old_extent_reclaimed = true;
}

#define REQUIRE(condition, scenario) do {                                      \
    if (!(condition)) {                                                        \
        fprintf(stderr, "NEGATIVE_DETECTED mutant=%d case=%s line=%d\n",     \
                MUTANT_ID, scenario, __LINE__);                                \
        return 1;                                                              \
    }                                                                          \
} while (0)

static int test_ordered_fua_and_sizes(void)
{
    static const unsigned sizes[] = {1U, 2U, 4U};
    for (unsigned index = 0; index < 3U; index++) {
        struct transaction transaction = {0};
        REQUIRE(admit(&transaction, sizes[index], false, true), "valid-size");
        REQUIRE(submit_lower_write(&transaction), "submit");
        REQUIRE(transaction.acknowledgement_count == 0U, "no-early-ack");
        complete_lower_write(&transaction, 0, sizes[index]);
        REQUIRE(!transaction.published && !transaction.acknowledgement_count,
                "write-before-fua");
        complete_fua_flush(&transaction, 0);
        REQUIRE(transaction.published && transaction.acknowledgement_count == 1U &&
                transaction.acknowledgement_error == 0, "fua-before-publish");
    }
    return 0;
}

static int test_lower_error(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 2U, false, true), "error-admit");
    REQUIRE(submit_lower_write(&transaction), "error-submit");
    complete_lower_write(&transaction, -EIO, 2U);
    REQUIRE(transaction.terminal && !transaction.published &&
            transaction.acknowledgement_count == 1U &&
            transaction.acknowledgement_error == -EIO, "lower-eio-terminal");
    complete_fua_flush(&transaction, 0);
    REQUIRE(!transaction.published, "no-publish-after-eio");
    return 0;
}

static int test_fua_failure(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 4U, false, true), "failed-fua-admit");
    REQUIRE(submit_lower_write(&transaction), "failed-fua-submit");
    complete_lower_write(&transaction, 0, 4U);
    complete_fua_flush(&transaction, -EIO);
    REQUIRE(transaction.terminal && !transaction.published &&
            transaction.acknowledgement_count == 1U &&
            transaction.acknowledgement_error == -EIO, "failed-fua-no-map");
    return 0;
}

static int test_duplicate_callback(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 1U, false, false), "duplicate-admit");
    REQUIRE(submit_lower_write(&transaction), "duplicate-submit");
    complete_lower_write(&transaction, 0, 1U);
    complete_lower_write(&transaction, -EIO, 0U);
#if MUTANT_ID == 5
    acknowledge(&transaction, 0); /* Duplicate upper completion mutant. */
#endif
    REQUIRE(transaction.acknowledgement_count == 1U &&
            transaction.acknowledgement_error == 0, "duplicate-exactly-once");
    return 0;
}

static int test_stopped_late_completion(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 1U, false, false), "stop-admit");
    REQUIRE(submit_lower_write(&transaction), "stop-submit");
    stop_target(&transaction);
    complete_lower_write(&transaction, 0, 1U);
    REQUIRE(!transaction.published && transaction.acknowledgement_count == 1U &&
            transaction.acknowledgement_error == -ESHUTDOWN, "stop-late-ignored");
    return 0;
}

static int test_stale_generation(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 2U, false, false), "stale-admit");
    REQUIRE(submit_lower_write(&transaction), "stale-submit");
    transaction.generation++;
    complete_lower_write(&transaction, 0, 2U);
    REQUIRE(!transaction.published && transaction.terminal &&
            transaction.acknowledgement_error == -ESTALE, "stale-abort");
    return 0;
}

static int test_gc_reader_pins(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 2U, false, false), "gc-admit");
    transaction.reader_pins = 2;
    REQUIRE(submit_lower_write(&transaction), "gc-submit");
    complete_lower_write(&transaction, 0, 2U);
    REQUIRE(transaction.published, "gc-published");
    release_reader(&transaction);
    REQUIRE(!transaction.old_extent_reclaimed, "gc-pinned-old-extent");
    release_reader(&transaction);
    REQUIRE(transaction.old_extent_reclaimed, "gc-reclaim-after-last-unpin");
    return 0;
}

static int test_first_failure_precedence(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 1U, false, true), "first-error-admit");
    REQUIRE(submit_lower_write(&transaction), "first-error-submit");
    complete_lower_write(&transaction, -EIO, 0U);
    record_failure(&transaction, -EUCLEAN);
    REQUIRE(transaction.first_error == -EIO && transaction.acknowledgement_error == -EIO,
            "lower-error-wins-cleanup");
    return 0;
}

static int test_preflush_gate(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 1U, true, false), "preflush-admit");
    REQUIRE(!submit_lower_write(&transaction), "no-write-before-preflush");
    complete_preflush(&transaction, 0);
    REQUIRE(submit_lower_write(&transaction), "write-after-preflush");
    complete_lower_write(&transaction, 0, 1U);
    REQUIRE(transaction.published && transaction.acknowledgement_count == 1U,
            "preflush-success");
    return 0;
}

static int test_capacity_and_partial(void)
{
    struct transaction invalid = {0};
    struct transaction transaction = {0};
    REQUIRE(!admit(&invalid, 3U, false, false), "reject-nonextent-size");
    REQUIRE(!admit(&invalid, 0U, false, false), "reject-zero-size");
    REQUIRE(admit(&transaction, 4U, false, false), "partial-admit");
    REQUIRE(submit_lower_write(&transaction), "partial-submit");
    complete_lower_write(&transaction, 0, 2U);
    REQUIRE(!transaction.published && transaction.terminal &&
            transaction.acknowledgement_error == -EIO, "partial-lower-abort");
    return 0;
}

static int test_predecessor_order(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 4U, false, false), "order-admit");
    transaction.predecessor_pending = true;
    REQUIRE(submit_lower_write(&transaction), "order-submit");
    complete_lower_write(&transaction, 0, 4U);
    REQUIRE(!transaction.published, "older-must-finish-first");
    finish_predecessor(&transaction);
    REQUIRE(transaction.published && transaction.acknowledgement_count == 1U,
            "ordered-commit");
    return 0;
}

static int test_no_early_flush(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 1U, false, true), "early-flush-admit");
    REQUIRE(submit_lower_write(&transaction), "early-flush-submit");
    complete_fua_flush(&transaction, 0);
    REQUIRE(!transaction.lower_complete && !transaction.published &&
            !transaction.acknowledgement_count, "flush-before-write-ignored");
    complete_lower_write(&transaction, 0, 1U);
    REQUIRE(!transaction.published, "fua-needs-write-then-flush");
    complete_fua_flush(&transaction, 0);
    REQUIRE(transaction.published, "fua-after-write");
    return 0;
}

static int test_flush_failure_precedence(void)
{
    struct transaction transaction = {0};
    REQUIRE(admit(&transaction, 2U, false, true), "flush-error-admit");
    REQUIRE(submit_lower_write(&transaction), "flush-error-submit");
    complete_lower_write(&transaction, 0, 2U);
    complete_fua_flush(&transaction, -EIO);
    REQUIRE(transaction.first_error == -EIO && transaction.acknowledgement_error == -EIO,
            "flush-error-wins-cleanup");
    return 0;
}

int main(void)
{
    /* Deterministic logical ordering, no sleeping and no host/block I/O. */
    if (test_ordered_fua_and_sizes() || test_lower_error() ||
        test_fua_failure() || test_duplicate_callback() ||
        test_stopped_late_completion() || test_stale_generation() ||
        test_gc_reader_pins() || test_first_failure_precedence() ||
        test_preflush_gate() || test_capacity_and_partial() ||
        test_predecessor_order() || test_no_early_flush() ||
        test_flush_failure_precedence())
        return 1;
    if (MUTANT_ID != 0) {
        fprintf(stderr, "MUTANT_SURVIVED mutant=%d\n", MUTANT_ID);
        return 2;
    }
    puts("PASS model lower-write/FUA/preflush/GC/teardown (not physical durability)");
    return 0;
}
