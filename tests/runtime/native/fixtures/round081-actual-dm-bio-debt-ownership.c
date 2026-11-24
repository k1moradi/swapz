/* Round081 Agent11: strict host-only C23 model, NOT a kernel/DM execution.
 * SOURCE_PRODUCT_* placeholders contain exact, git-blob-verified product C
 * statements. All debt fields/state machine are independently MODELED.
 * A token is unique per accepted upper clone, never per lower submission.
 * Source fragment list operations are modeled with fixed-size counters;
 * they are NOT the actual kernel list implementation. No production cap.
 */
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MAX_TEST_BIOS 128U
#define ORIGINAL_IMPORT_MAX_BYTES 3568U
#define CHECK_TAG(tag, condition) do { if (!(condition)) { \
    (void)fprintf(stderr, "FIRST_ERROR scenario=%s line=%d invariant=%s\n", \
                  tag, __LINE__, #condition); return 1; \
} } while (0)

enum stage { EMPTY, REJECTED_PRE_ADMISSION, INCOMING, LOCAL, PREPARED,
             BATCH, LOWER_INFLIGHT, DEFERRED_UPPER, ACKED };
struct test_bio { unsigned endio_count; bool alive; };
struct list_head { unsigned length; };
struct swapz_bio_ref { struct list_head list; };
struct swapz_dm { bool accepting; struct list_head incoming; };
static void list_add_tail(struct list_head *entry, struct list_head *head)
{ (void)entry; ++head->length; }
static void list_splice_init(struct list_head *source, struct list_head *destination)
{ destination->length += source->length; source->length = 0U; }
static void bio_endio(struct test_bio *bio)
{ ++bio->endio_count; bio->alive = false; }

/* Actual product expressions are substituted verbatim and compiled. */
static void product_admission_fragment(struct swapz_dm *ctx,
                                       struct swapz_bio_ref *entry)
{ /* SOURCE_PRODUCT_ENQUEUE */ }
static void product_worker_fragment(struct swapz_dm *ctx,
                                    struct list_head local)
{ /* SOURCE_PRODUCT_SPLICE */
  (void)local.length;
}
static void product_upper_endio_fragment(struct test_bio *bio)
{ /* SOURCE_PRODUCT_ENDIO */ }

typedef struct {
    enum stage stage;
    bool accepted;
    bool is_read;
    bool prep_owned;
    bool lower_pending;
    bool lower_success;
    unsigned ack_calls;
    unsigned releases;
    unsigned gc_reader_pins;
    int terminal_error;
    unsigned original_bytes;
} upper_token;
typedef struct {
    upper_token tokens[MAX_TEST_BIOS];
    unsigned outstanding;
    unsigned accepted_total;
    unsigned completed_total;
    unsigned preparation_count;
    unsigned lower_count;
    unsigned deferred_count;
    unsigned ticket_count;
    unsigned copy_bytes;
    bool accepting;
} debt_ledger;

static void reset_ledger(debt_ledger *ledger)
{ (void)memset(ledger, 0, sizeof(*ledger)); ledger->accepting = true; }
static void reject_pre_admission(upper_token *slot)
{ slot->stage = REJECTED_PRE_ADMISSION; slot->accepted = false; }
static bool admit(debt_ledger *ledger, unsigned index, bool is_read)
{
    if (index >= MAX_TEST_BIOS || !ledger->accepting ||
        ledger->tokens[index].stage != EMPTY) return false;
    upper_token *slot = &ledger->tokens[index];
    slot->stage = INCOMING;
    slot->is_read = is_read;
    slot->accepted = true;
    ledger->accepted_total += 1U;
    ledger->outstanding += 1U;
    return true;
}
static bool to_local(upper_token *slot)
{ if (slot->stage != INCOMING) return false;
  slot->stage = LOCAL; return true; }
static bool prepare(debt_ledger *ledger, upper_token *slot)
{ if (slot->stage != LOCAL) return false;
  slot->stage = PREPARED;
  slot->prep_owned = true;
  ++ledger->preparation_count; return true; }
static bool batch(debt_ledger *ledger, upper_token *slot)
{ if (slot->stage != PREPARED || !slot->prep_owned) return false;
  slot->prep_owned = false;
  --ledger->preparation_count;
  slot->stage = BATCH; return true; }
static bool lower_submit(debt_ledger *ledger, upper_token *slot)
{ if (slot->stage != BATCH) return false;
  slot->stage = LOWER_INFLIGHT;
  slot->lower_pending = true;
  ledger->lower_count += 1U; return true; }
static bool lower_finish(debt_ledger *ledger, upper_token *slot, bool error)
{ if (slot->stage != LOWER_INFLIGHT || !slot->lower_pending) return false;
  slot->lower_pending = false;
  --ledger->lower_count;
  slot->lower_success = !error; return true; }
static bool defer_upper(debt_ledger *ledger, upper_token *slot)
{ if (slot->stage != LOWER_INFLIGHT || slot->lower_pending ||
      !slot->lower_success) return false;
  slot->stage = DEFERRED_UPPER;
  ledger->deferred_count += 1U; return true; }
static bool original_copy_ticket(debt_ledger *ledger, upper_token *slot,
                                 unsigned bytes)
{ if (!slot->accepted || slot->original_bytes || bytes == 0U ||
      bytes > ORIGINAL_IMPORT_MAX_BYTES) return false;
  slot->original_bytes = bytes;
  ledger->ticket_count += 1U;
  ledger->copy_bytes += bytes; return true; }
static void pin_gc_reader(upper_token *slot)
{ slot->gc_reader_pins += 1U; }
static void close_admission(debt_ledger *ledger)
{ ledger->accepting = false; }
static bool upper_ack(debt_ledger *ledger, upper_token *slot, int error)
{
    if (!slot->accepted || slot->stage == ACKED || slot->ack_calls ||
        slot->lower_pending || slot->prep_owned ||
        (slot->stage != DEFERRED_UPPER && slot->stage != LOWER_INFLIGHT &&
         slot->stage != LOCAL && slot->stage != INCOMING)) return false;
    if (slot->stage == DEFERRED_UPPER) --ledger->deferred_count;
    if (slot->original_bytes) {
        --ledger->ticket_count;
        ledger->copy_bytes -= slot->original_bytes;
        slot->original_bytes = 0U;
    }
    slot->terminal_error = error;
    slot->ack_calls += 1U;
    slot->releases += 1U;
    ledger->outstanding -= 1U;
    ++ledger->completed_total;
    slot->stage = ACKED;
    return true;
}

static int verify_preaccept_and_admission(void)
{
    debt_ledger ledger; reset_ledger(&ledger);
    upper_token rejected = {0}; reject_pre_admission(&rejected);
    CHECK_TAG("preaccept", rejected.stage == REJECTED_PRE_ADMISSION);
    CHECK_TAG("preaccept", rejected.accepted == false);
    CHECK_TAG("preaccept", ledger.outstanding == 0U);
    CHECK_TAG("admission", admit(&ledger, 0U, false));
    CHECK_TAG("admission", ledger.outstanding == 1U);
    CHECK_TAG("admission", ledger.accepted_total == 1U);
    CHECK_TAG("admission", ledger.tokens[0].accepted);
    return 0;
}
static int verify_source_cloned_queue(void)
{
    struct swapz_dm ctx = {.accepting=true, .incoming={0}};
    struct swapz_bio_ref entry = {0};
    product_admission_fragment(&ctx, &entry);
    CHECK_TAG("source-enqueue", ctx.incoming.length == 1U);
    struct list_head local = {0};
    product_worker_fragment(&ctx, local);
    CHECK_TAG("source-splice", ctx.incoming.length == 0U);
    struct test_bio bio = {.alive=true};
    product_upper_endio_fragment(&bio);
    CHECK_TAG("source-ack", bio.endio_count == 1U);
    CHECK_TAG("source-ack", !bio.alive);
    return 0;
}
static int verify_preparation_lower_and_deferred(void)
{
    debt_ledger ledger; reset_ledger(&ledger);
    CHECK_TAG("admit", admit(&ledger, 0U, false));
    upper_token *slot = &ledger.tokens[0];
    CHECK_TAG("local", to_local(slot));
    CHECK_TAG("local", slot->stage == LOCAL);
    CHECK_TAG("transfer", ledger.outstanding == 1U);
    CHECK_TAG("prepare", prepare(&ledger, slot));
    CHECK_TAG("prepare", slot->stage == PREPARED);
    CHECK_TAG("prepare", slot->prep_owned);
    CHECK_TAG("prepare", ledger.preparation_count == 1U);
    CHECK_TAG("batch", batch(&ledger, slot));
    CHECK_TAG("batch", !slot->prep_owned);
    CHECK_TAG("batch", slot->stage == BATCH);
    CHECK_TAG("batch", ledger.preparation_count == 0U);
    CHECK_TAG("lower", lower_submit(&ledger, slot));
    CHECK_TAG("lower", slot->stage == LOWER_INFLIGHT);
    CHECK_TAG("lower", slot->lower_pending);
    CHECK_TAG("lower", ledger.lower_count == 1U);
    CHECK_TAG("lower", lower_finish(&ledger, slot, false));
    CHECK_TAG("lower", !slot->lower_pending);
    CHECK_TAG("lower", ledger.lower_count == 0U);
    CHECK_TAG("lower", slot->lower_success);
    CHECK_TAG("deferred", defer_upper(&ledger, slot));
    CHECK_TAG("deferred", slot->stage == DEFERRED_UPPER);
    CHECK_TAG("deferred", ledger.deferred_count == 1U);
    CHECK_TAG("deferred", ledger.outstanding == 1U);
    CHECK_TAG("ack", upper_ack(&ledger, slot, 0));
    CHECK_TAG("ack", slot->ack_calls == 1U);
    CHECK_TAG("ack", slot->releases == 1U);
    CHECK_TAG("ack", slot->stage == ACKED);
    CHECK_TAG("ack", ledger.outstanding == 0U);
    CHECK_TAG("ack", ledger.deferred_count == 0U);
    CHECK_TAG("ack", !upper_ack(&ledger, slot, 0));
    return 0;
}
static int verify_error_teardown_and_original(void)
{
    debt_ledger ledger; reset_ledger(&ledger);
    CHECK_TAG("failure", admit(&ledger, 0U, false));
    upper_token *failed = &ledger.tokens[0];
    CHECK_TAG("failure", to_local(failed));
    CHECK_TAG("failure", prepare(&ledger, failed));
    CHECK_TAG("failure", batch(&ledger, failed));
    CHECK_TAG("failure", lower_submit(&ledger, failed));
    CHECK_TAG("failure", lower_finish(&ledger, failed, true));
    CHECK_TAG("failure", !failed->lower_success);
    CHECK_TAG("failure", !defer_upper(&ledger, failed));
    CHECK_TAG("failure", upper_ack(&ledger, failed, -5));
    CHECK_TAG("failure", failed->terminal_error == -5);
    CHECK_TAG("failure", ledger.outstanding == 0U);
    CHECK_TAG("teardown", admit(&ledger, 1U, true));
    CHECK_TAG("teardown", ledger.tokens[1].is_read);
    close_admission(&ledger);
    CHECK_TAG("teardown", !ledger.accepting);
    CHECK_TAG("teardown", !admit(&ledger, 2U, false));
    CHECK_TAG("teardown", upper_ack(&ledger, &ledger.tokens[1], -5));
    CHECK_TAG("teardown", ledger.accepted_total == ledger.completed_total);
    CHECK_TAG("teardown", ledger.outstanding == 0U);

    reset_ledger(&ledger);
    CHECK_TAG("original", admit(&ledger, 0U, false));
    upper_token *original = &ledger.tokens[0];
    CHECK_TAG("original", !original_copy_ticket(&ledger, original, 3569U));
    CHECK_TAG("original", original_copy_ticket(&ledger, original, 3568U));
    CHECK_TAG("original", ledger.ticket_count == 1U);
    CHECK_TAG("original", ledger.copy_bytes == 3568U);
    pin_gc_reader(original);
    CHECK_TAG("original", original->gc_reader_pins == 1U);
    CHECK_TAG("original", ledger.outstanding == 1U);
    CHECK_TAG("original", upper_ack(&ledger, original, -5));
    CHECK_TAG("original", ledger.ticket_count == 0U);
    CHECK_TAG("original", ledger.copy_bytes == 0U);
    CHECK_TAG("original", ledger.outstanding == 0U);
    CHECK_TAG("original", original->gc_reader_pins == 1U);
    return 0;
}

/* Two submitters race one worker, but every ledger transaction is guarded
 * by one mutex. Barrier establishes an overlapping start; condition variable
 * prevents sleep/busy-loop and bounds the test. No kernel scheduling claim. */
struct concurrent_test {
    debt_ledger ledger;
    pthread_mutex_t mutex;
    pthread_cond_t ready;
    pthread_barrier_t barrier;
    unsigned finished_submitters;
};
struct submitter_args { struct concurrent_test *test; unsigned start_index; int error; };
static void *submitter(void *argument)
{
    struct submitter_args *arguments = argument;
    (void)pthread_barrier_wait(&arguments->test->barrier);
    for (unsigned index = arguments->start_index;
         index < arguments->start_index + 32U; ++index) {
        if (pthread_mutex_lock(&arguments->test->mutex) != 0) {
            arguments->error = 1; return NULL;
        }
        if (!admit(&arguments->test->ledger, index, index % 2U == 0U))
            arguments->error = 1;
        if (pthread_cond_signal(&arguments->test->ready) != 0)
            arguments->error = 1;
        if (pthread_mutex_unlock(&arguments->test->mutex) != 0)
            arguments->error = 1;
    }
    if (pthread_mutex_lock(&arguments->test->mutex) != 0) {
        arguments->error = 1; return NULL;
    }
    ++arguments->test->finished_submitters;
    if (pthread_cond_broadcast(&arguments->test->ready) != 0)
        arguments->error = 1;
    if (pthread_mutex_unlock(&arguments->test->mutex) != 0)
        arguments->error = 1;
    return NULL;
}
static int verify_two_submitters_worker(void)
{
    struct concurrent_test test = {0}; reset_ledger(&test.ledger);
    CHECK_TAG("threads", pthread_mutex_init(&test.mutex, NULL) == 0);
    CHECK_TAG("threads", pthread_cond_init(&test.ready, NULL) == 0);
    CHECK_TAG("threads", pthread_barrier_init(&test.barrier, NULL, 3U) == 0);
    struct submitter_args first = {.test=&test, .start_index=0U};
    struct submitter_args second = {.test=&test, .start_index=32U};
    pthread_t one, two;
    CHECK_TAG("threads", pthread_create(&one, NULL, submitter, &first) == 0);
    CHECK_TAG("threads", pthread_create(&two, NULL, submitter, &second) == 0);
    (void)pthread_barrier_wait(&test.barrier);
    unsigned processed = 0U;
    int worker_error = 0;
    for (unsigned index = 0U; index < 64U; ++index) {
        if (pthread_mutex_lock(&test.mutex) != 0) {
            worker_error = 1; break;
        }
        while (test.ledger.tokens[index].stage == EMPTY &&
               test.finished_submitters < 2U) {
            if (pthread_cond_wait(&test.ready, &test.mutex) != 0) {
                worker_error = 1; break;
            }
        }
        upper_token *slot = &test.ledger.tokens[index];
        if (worker_error || !to_local(slot) ||
            !upper_ack(&test.ledger, slot, 0))
            worker_error = 1;
        else
            ++processed;
        if (pthread_mutex_unlock(&test.mutex) != 0)
            worker_error = 1;
        if (worker_error) break;
    }
    CHECK_TAG("threads", pthread_join(one, NULL) == 0);
    CHECK_TAG("threads", pthread_join(two, NULL) == 0);
    CHECK_TAG("threads", worker_error == 0);
    CHECK_TAG("threads", first.error == 0 && second.error == 0);
    CHECK_TAG("threads", processed == 64U);
    CHECK_TAG("threads", test.ledger.outstanding == 0U);
    CHECK_TAG("threads", test.ledger.accepted_total == 64U);
    CHECK_TAG("threads", test.ledger.accepted_total == test.ledger.completed_total);
    CHECK_TAG("threads", pthread_barrier_destroy(&test.barrier) == 0);
    CHECK_TAG("threads", pthread_cond_destroy(&test.ready) == 0);
    CHECK_TAG("threads", pthread_mutex_destroy(&test.mutex) == 0);
    return 0;
}
int main(void)
{
    if (verify_preaccept_and_admission() || verify_source_cloned_queue() ||
        verify_preparation_lower_and_deferred() ||
        verify_error_teardown_and_original() || verify_two_submitters_worker())
        return 1;
    (void)puts("PASS_HOST_ONLY ROUND081_AGENT11_ACTUAL_CLONE_DEBT_NO_AUTH");
    return 0;
}
