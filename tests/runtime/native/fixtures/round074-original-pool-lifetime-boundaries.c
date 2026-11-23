/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Round074 host-only pool/RCU and decoder-lease lifetime MODEL.
 * Original mm/zswap.c is checked separately by the paired Python verifier.
 * This code neither runs nor substitutes the original kernel destructor.
 * SOURCE_MAPPED_AUTHENTICATED=0, PHASE_A=BLOCKED, import ACTIVE=0.
 */
#include <pthread.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef ROUND074_MUTANT
#define ROUND074_MUTANT 0
#endif

#define ORIGINAL_PAGE_SIZE 4096U
#define TEST_CYCLES 48U

struct reader_owner {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    unsigned int readers;
    bool closing;
    bool finished;
};

struct pool_boundary {
    uintptr_t target_pool_identity;
    unsigned int pool_refcount;
    unsigned int destructor_count;
    unsigned int callback_count;
    unsigned int witness_completion_count;
    bool rcu_queued;
    bool destroyed;
    bool source_live;
    unsigned char source[ORIGINAL_PAGE_SIZE];
    unsigned char owned[ORIGINAL_PAGE_SIZE];
    size_t owned_length;
};

struct close_worker {
    struct reader_owner *owner;
    bool started;
};

static int first_error(const char *reason)
{
    fprintf(stderr, "ROUND074_POOL_HOST_FIRST_ERROR mutant=%d reason=%s\n",
            ROUND074_MUTANT, reason);
    return 1;
}

static int owner_acquire(struct reader_owner *owner)
{
    int result = 0;
    (void)pthread_mutex_lock(&owner->mutex);
    if (owner->closing && ROUND074_MUTANT != 9)
        result = -1;
    else if (ROUND074_MUTANT != 2)
        ++owner->readers;
    (void)pthread_mutex_unlock(&owner->mutex);
    return result;
}

static void owner_release(struct reader_owner *owner)
{
    (void)pthread_mutex_lock(&owner->mutex);
    if (owner->readers > 0U)
        --owner->readers;
    (void)pthread_cond_broadcast(&owner->condition);
    (void)pthread_mutex_unlock(&owner->mutex);
}

static void *owner_close(void *argument)
{
    struct close_worker *worker = argument;
    struct reader_owner *owner = worker->owner;
    (void)pthread_mutex_lock(&owner->mutex);
    worker->started = true;
    owner->closing = true;
    (void)pthread_cond_broadcast(&owner->condition);
    if (ROUND074_MUTANT != 6) {
        while (owner->readers != 0U)
            (void)pthread_cond_wait(&owner->condition, &owner->mutex);
    }
    owner->finished = true;
    (void)pthread_cond_broadcast(&owner->condition);
    (void)pthread_mutex_unlock(&owner->mutex);
    return NULL;
}

static bool pool_access_allowed(const struct pool_boundary *boundary)
{
    /* Safe guard: model a forbidden retired-pool access without UAF. */
    return !boundary->destroyed || ROUND074_MUTANT == 1;
}

static void release_rcu_callback(struct pool_boundary *boundary,
                                 uintptr_t released_identity)
{
    /* Source has already left the original ref map and passed RCU grace. */
    if (ROUND074_MUTANT == 4)
        ++boundary->witness_completion_count; /* too early */
    boundary->destroyed = true;
    boundary->source_live = false;
    ++boundary->destructor_count;
    if (ROUND074_MUTANT == 3)
        ++boundary->destructor_count;
    ++boundary->callback_count;
    if (ROUND074_MUTANT == 5)
        released_identity ^= (uintptr_t)16U; /* unrelated callback */
    if (ROUND074_MUTANT == 8)
        boundary->target_pool_identity = 0U; /* lost unique witness */
    if (boundary->target_pool_identity == released_identity) {
        boundary->target_pool_identity = 0U;
        ++boundary->witness_completion_count;
    }
}

static int verify_one_cycle(unsigned int cycle)
{
    struct pool_boundary boundary = {0};
    struct reader_owner owner = {0};
    struct close_worker worker = {.owner = &owner};
    pthread_t closer;
    bool thread_created = false;
    int result = 0;
    const uintptr_t unique_identity = (uintptr_t)(cycle + 1U) << 8U;

    boundary.target_pool_identity = unique_identity;
    boundary.pool_refcount = 1U;
    boundary.source_live = true;
    boundary.owned_length = ORIGINAL_PAGE_SIZE;
    for (size_t offset = 0U; offset < ORIGINAL_PAGE_SIZE; ++offset)
        boundary.source[offset] = (unsigned char)((offset ^ (size_t)cycle) & 0xFFU);
    if (ROUND074_MUTANT == 7)
        boundary.source_live = false; /* erase before ownership transfer */
    if (boundary.source_live)
        memcpy(boundary.owned, boundary.source, ORIGINAL_PAGE_SIZE);
    if (ROUND074_MUTANT == 10)
        boundary.owned_length = ORIGINAL_PAGE_SIZE - 1U;

    /* Original-order model: source copy before reference kill and RCU queue. */
    boundary.pool_refcount = 0U;
    boundary.rcu_queued = true;
    release_rcu_callback(&boundary, unique_identity);
    if (!boundary.rcu_queued || boundary.pool_refcount != 0U ||
        boundary.callback_count != 1U || boundary.destructor_count != 1U ||
        boundary.target_pool_identity != 0U ||
        boundary.witness_completion_count != 1U)
        return first_error("original-pool-target-rcu-destructor-count-or-order");
    if (pool_access_allowed(&boundary))
        return first_error("retired-pool-dereference-permitted");
    if (boundary.owned_length != ORIGINAL_PAGE_SIZE)
        return first_error("original-full-page-ownership-length");
    for (size_t offset = 0U; offset < ORIGINAL_PAGE_SIZE; ++offset) {
        const unsigned char expected = (unsigned char)((offset ^ (size_t)cycle) & 0xFFU);
        if (boundary.owned[offset] != expected)
            return first_error("source-erased-before-immutable-copy");
    }

    if (pthread_mutex_init(&owner.mutex, NULL) != 0)
        return first_error("mutex-init");
    if (pthread_cond_init(&owner.condition, NULL) != 0) {
        (void)pthread_mutex_destroy(&owner.mutex);
        return first_error("condition-init");
    }
    if (owner_acquire(&owner) != 0 || owner.readers != 1U) {
        result = first_error("lost-original-reader-lease");
        goto cleanup;
    }
    if (pthread_create(&closer, NULL, owner_close, &worker) != 0) {
        result = first_error("close-worker-create");
        goto cleanup;
    }
    thread_created = true;
    (void)pthread_mutex_lock(&owner.mutex);
    while (!worker.started)
        (void)pthread_cond_wait(&owner.condition, &owner.mutex);
    if (!owner.closing || owner.finished || owner.readers != 1U)
        result = first_error("close-did-not-hold-live-reader");
    (void)pthread_mutex_unlock(&owner.mutex);
    if (result == 0 && owner_acquire(&owner) == 0) {
        owner_release(&owner);
        result = first_error("late-reader-acquired-after-close");
    }
    owner_release(&owner);
    if (thread_created) {
        (void)pthread_join(closer, NULL);
        thread_created = false;
    }
    if (result == 0 && (!owner.finished || owner.readers != 0U))
        result = first_error("close-final-release-wake-invariant");
cleanup:
    if (thread_created) {
        owner_release(&owner);
        (void)pthread_join(closer, NULL);
    }
    (void)pthread_cond_destroy(&owner.condition);
    (void)pthread_mutex_destroy(&owner.mutex);
    return result;
}

int main(void)
{
    for (unsigned int cycle = 0U; cycle < TEST_CYCLES; ++cycle) {
        if (verify_one_cycle(cycle) != 0)
            return EXIT_FAILURE;
    }
    if (ROUND074_MUTANT != 0)
        return first_error("semantic-mutant-not-detected");
    puts("ROUND074_POOL_HOST_BASELINE_PASS cycles=48 private_rcu_target=YES original_full4096_copy=YES reader_lease_close=YES model_only=YES auth=0");
    return EXIT_SUCCESS;
}
