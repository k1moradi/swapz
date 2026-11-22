#!/usr/bin/env python3
"""Execute the actual dormant decoder-owner C under deterministic mock kernel wait/spin semantics.

This is not a loaded kernel or original codec test. The separate original
pinned native y/n jobs and selected LZO/LZ4 source-host tests remain required.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

STUB_CODEC = r'''
#ifndef SWAPZ_ZSWAP_IMPORT_CODEC_H
#define SWAPZ_ZSWAP_IMPORT_CODEC_H
#include <stdint.h>
typedef uint8_t swapz_u8;
typedef uint32_t swapz_u32;
#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U
#define SWAPZ_ZSWAP_IMPORT_VERSION 1U
#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U
#define SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION 1U
struct swapz_zswap_import_record {swapz_u8 codec; swapz_u8 version;};
struct swapz_zswap_import_read_authority {unsigned int unused;};
static inline int swapz_zswap_import_decode(
    const struct swapz_zswap_import_record *record,
    const struct swapz_zswap_import_read_authority *authority,
    const swapz_u8 *compressed_bytes, swapz_u32 compressed_capacity,
    swapz_u8 *scratch, swapz_u32 scratch_capacity,
    swapz_u8 *output, swapz_u32 output_capacity,
    const swapz_u8 *independent_original_page)
{
    (void)record; (void)authority; (void)compressed_bytes;
    (void)compressed_capacity; (void)scratch; (void)scratch_capacity;
    (void)output; (void)output_capacity; (void)independent_original_page;
    return 0;
}
#endif
'''

STUB_SPIN = r'''
#ifndef SWAPZ_ROUND066_MOCK_SPIN_H
#define SWAPZ_ROUND066_MOCK_SPIN_H
#include <pthread.h>
typedef struct { pthread_mutex_t mutex; } spinlock_t;
#define spin_lock_init(lock) ((void)pthread_mutex_init(&(lock)->mutex, NULL))
#define spin_lock_irqsave(lock, flags) do { (flags) = 0UL; \
    (void)pthread_mutex_lock(&(lock)->mutex); } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); \
    (void)pthread_mutex_unlock(&(lock)->mutex); } while (0)
#endif
'''

STUB_WAIT = r'''
#ifndef SWAPZ_ROUND066_MOCK_WAIT_H
#define SWAPZ_ROUND066_MOCK_WAIT_H
#include <pthread.h>
typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
} wait_queue_head_t;
#define init_waitqueue_head(queue) do { \
    (void)pthread_mutex_init(&(queue)->mutex, NULL); \
    (void)pthread_cond_init(&(queue)->condition, NULL); \
} while (0)
extern void swapz_round066_mock_wake_all(wait_queue_head_t *queue);
#define wake_up_all(queue) swapz_round066_mock_wake_all(queue)
#define wait_event(queue, predicate) do { \
    (void)pthread_mutex_lock(&(queue).mutex); \
    while (!(predicate)) \
        (void)pthread_cond_wait(&(queue).condition, &(queue).mutex); \
    (void)pthread_mutex_unlock(&(queue).mutex); \
} while (0)
#endif
'''

FIXTURE = r'''
#include "zswap-import-decoder-owner.h"
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static atomic_int wake_entered = 0;
static atomic_int allow_wake_complete = 0;
static atomic_int close_returned = 0;
static atomic_int wake_after_close = 0;
static struct swapz_zswap_import_decoder_owner owner;
static struct swapz_zswap_import_decoder_lease lease = {0};
static int close_result = -1;
static int put_result = -1;

void swapz_round066_mock_wake_all(wait_queue_head_t *queue)
{
    /* Pause the final-reader wake while the kernel lock is still held.
     * Close must not return and authorize owner destruction here. */
    (void)pthread_mutex_lock(&queue->mutex);
    (void)pthread_cond_broadcast(&queue->condition);
    (void)pthread_mutex_unlock(&queue->mutex);
    atomic_store_explicit(&wake_entered, 1, memory_order_release);
    for (unsigned int iteration = 0;
         !atomic_load_explicit(&allow_wake_complete, memory_order_acquire) &&
             iteration < 20000000U; ++iteration)
        sched_yield();
    if (atomic_load_explicit(&close_returned, memory_order_acquire))
        atomic_store_explicit(&wake_after_close, 1, memory_order_release);
}

static void *close_thread(void *argument)
{
    (void)argument;
    close_result = swapz_zswap_import_decoder_owner_close_and_drain(&owner);
    atomic_store_explicit(&close_returned, 1, memory_order_release);
    return NULL;
}

static void *put_thread(void *argument)
{
    (void)argument;
    put_result = swapz_zswap_import_decoder_owner_put(&lease);
    return NULL;
}

static int wait_for_closing(void)
{
    for (unsigned int iteration = 0; iteration < 1000000U; ++iteration) {
        int closing;
        (void)pthread_mutex_lock(&owner.lock.mutex);
        closing = owner.closing;
        (void)pthread_mutex_unlock(&owner.lock.mutex);
        if (closing)
            return 0;
        sched_yield();
    }
    return -1;
}

int main(void)
{
    pthread_t closer;
    pthread_t reader;
    int returned_during_wake = 0;
    if (swapz_zswap_import_decoder_owner_init(&owner,
        SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION))
        return 2;
    if (swapz_zswap_import_decoder_owner_get(&owner, &lease))
        return 2;
    if (pthread_create(&closer, NULL, close_thread, NULL))
        return 2;
    if (wait_for_closing())
        return 2;
    if (pthread_create(&reader, NULL, put_thread, NULL))
        return 2;
    for (unsigned int iteration = 0; iteration < 1000000U; ++iteration) {
        if (atomic_load_explicit(&wake_entered, memory_order_acquire))
            break;
        sched_yield();
    }
    if (!atomic_load_explicit(&wake_entered, memory_order_acquire))
        return 2;
    /* Give a wake-blocked close thread a deterministic scheduling window.
     * With the corrected owner lock barrier, it cannot return early. */
    for (unsigned int iteration = 0; iteration < 100000U; ++iteration) {
        if (atomic_load_explicit(&close_returned, memory_order_acquire)) {
            returned_during_wake = 1;
            break;
        }
        sched_yield();
    }
    atomic_store_explicit(&allow_wake_complete, 1, memory_order_release);
    if (pthread_join(reader, NULL) || pthread_join(closer, NULL))
        return 2;
    if (returned_during_wake ||
        atomic_load_explicit(&wake_after_close, memory_order_acquire)) {
        fputs("ROUND066_DRAIN_SEMANTIC_EARLY_CLOSE\n", stderr);
        return 17;
    }
    if (close_result || put_result || lease.owner ||
        !atomic_load_explicit(&close_returned, memory_order_acquire))
        return 2;
    (void)pthread_mutex_destroy(&owner.lock.mutex);
    (void)pthread_mutex_destroy(&owner.drained.mutex);
    (void)pthread_cond_destroy(&owner.drained.condition);
    puts("ROUND066_DRAIN_KERNEL_MOCK_CLOSE_RELEASE_PASS");
    return 0;
}
'''

# Two true control-flow lifetime mutants, each actually compiled and executed.
# The expected failure is the semantic early-close detection, never a build
# error, sanitizer crash, timeout, or unrelated fixture failure.
MUTANTS = (
    ("wake-after-owner-unlock",
     "\tif (wake_drainer)\n\t\twake_up_all(&owner->drained);\n\tspin_unlock_irqrestore(&owner->lock, irq_flags);",
     "\tspin_unlock_irqrestore(&owner->lock, irq_flags);\n\tif (wake_drainer)\n\t\twake_up_all(&owner->drained);"),
    ("close-skips-final-put-barrier",
     "\twait_event(owner->drained, READ_ONCE(owner->active_readers) == 0U);\n\t/* READ_ONCE can see the final decrement while put still holds the\n\t * spinlock and uses the wait queue. Join that last wake before the\n\t * caller is permitted to release the owner and its wait queue. */\n\tspin_lock_irqsave(&owner->lock, irq_flags);\n\tspin_unlock_irqrestore(&owner->lock, irq_flags);",
     "\twait_event(owner->drained, READ_ONCE(owner->active_readers) == 0U);"),
)


def execute(command: list[str], expected_failure: bool) -> None:
    run = subprocess.run(command, text=True, capture_output=True, timeout=30,
                         check=False)
    if expected_failure:
        if run.returncode != 17 or "ROUND066_DRAIN_SEMANTIC_EARLY_CLOSE" not in run.stderr:
            raise RuntimeError("ROUND066_DRAIN_FIRST_ERROR compiled mutant not semantically rejected")
    elif run.returncode or "ROUND066_DRAIN_KERNEL_MOCK_CLOSE_RELEASE_PASS" not in run.stdout:
        raise RuntimeError("ROUND066_DRAIN_FIRST_ERROR baseline compile/execute failed: " +
                           (run.stderr or run.stdout)[-1200:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-source", type=Path, required=True)
    parser.add_argument("--owner-header", type=Path, required=True)
    arguments = parser.parse_args()
    source = arguments.owner_source.read_text()
    header = arguments.owner_header.read_text()
    with tempfile.TemporaryDirectory(prefix="round066-drain-") as temporary:
        root = Path(temporary)
        kernel_headers = root / "linux"
        kernel_headers.mkdir()
        for name, contents in (("zswap-import-codec.h", STUB_CODEC),
                               ("linux/spinlock.h", STUB_SPIN),
                               ("linux/wait.h", STUB_WAIT),
                               ("linux/compiler.h", "#define READ_ONCE(value) __atomic_load_n(&(value), __ATOMIC_ACQUIRE)\n"),
                               ("linux/errno.h", "#include_next <linux/errno.h>\n"),
                               ("linux/string.h", "#include <string.h>\n"),
                               ("zswap-import-decoder-owner.h", header),
                               ("lifetime-fixture.c", FIXTURE)):
            destination = root / name
            destination.write_text(contents)
        for compiler in ("gcc", "clang"):
            for name, old, replacement in (("baseline", "", ""), *MUTANTS):
                if old and source.count(old) != 1:
                    raise RuntimeError("ROUND066_DRAIN_FIRST_ERROR mutation anchor drift " + name)
                variant = root / (compiler + "-" + name + ".c")
                variant.write_text(source if not old else source.replace(old, replacement, 1))
                binary = root / (compiler + "-" + name)
                compile_command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall",
                                   "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
                                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                                   "-pthread", "-I", str(root), str(variant),
                                   str(root / "lifetime-fixture.c"), "-o", str(binary)]
                compilation = subprocess.run(compile_command, capture_output=True,
                                             text=True, timeout=30, check=False)
                if compilation.returncode:
                    raise RuntimeError("ROUND066_DRAIN_FIRST_ERROR C compile failed: " +
                                       compilation.stderr[-1200:])
                execute([str(binary)], expected_failure=name != "baseline")
                print(f"ROUND066_DRAIN_CASE_PASS compiler={compiler} case={name}", flush=True)
    print("ROUND066_DRAIN_GCC_CLANG_ASAN_UBSAN_PASS baselines=2 "
          "compiled_executed_semantic_mutants=4 loaded_kernel=NO auth=0", flush=True)


if __name__ == "__main__":
    main()
