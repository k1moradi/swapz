#!/usr/bin/env python3
"""Compile actual target credit/claim fragments; no kernel, VM or device use."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def fragment(source, name):
    begin = f'/* ROUND090_{name}_BEGIN */'
    end = f'/* ROUND090_{name}_END */'
    if source.count(begin) != 1 or source.count(end) != 1:
        raise SystemExit('fragment marker drift: ' + name)
    return source.split(begin, 1)[1].split(end, 1)[0]


ADAPTER = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
typedef uint64_t u64;
typedef uint32_t swapz_u32;
typedef uint8_t swapz_u8;
#define SWAPZ_SECTORS 8U
#define SWAPZ_MAX_COMPRESSED 3568U
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_TICKET_ORIGINAL 0x5aU
#define SWAPZ_TICKET_LZ4 1U
#define SWAPZ_TICKET_LZO1X 2U
struct swapz_ticket_ref { void *broker; u64 session, generation; swapz_u32 index; };
struct swapz_ticket_cap { void *broker; u64 session, epoch; };
struct swapz_ticket_key {
    u64 target_session, table_epoch, target_epoch, logical_page, dm_generation;
    swapz_u32 length, decoded_length;
    swapz_u8 representation, codec, version, dictionary;
};
struct swapz_ticket_view { const swapz_u8 *bytes; struct swapz_ticket_key key; };
struct swapz_round089_route { u64 broker_session, table_epoch, target_epoch, registration_epoch; };
struct bio { struct { u64 bi_sector; } bi_iter; void *bi_bdev; };
struct swapz_bio_ref {
    bool list, preparation_list;
    void *prepared_page;
    struct bio *bio;
    struct swapz_ticket_ref original_claim;
    struct swapz_ticket_view original_view;
    u64 original_gc_epoch;
};
struct swapz_dm {
    bool queue_lock, accepting, failed;
    void *target, *original_storage;
    struct swapz_round089_route original_route;
    struct swapz_ticket_cap original_cap;
    int original_release_busy;
};
#define lockdep_assert_held(lock) assert(*(lock))
#define list_empty(list) (!*(list))
#define rcu_read_lock() ((void)0)
#define rcu_read_unlock() ((void)0)
static unsigned int broker_calls;
static bool dm_swapz_round090_selected_origin(void *target, struct bio *bio)
{ return target && bio; }
static bool dm_swapz_round090_route_live(void *target, void *bdev, u64 sector)
{ return target && bdev && sector; }
static int atomic_cmpxchg_acquire(int *value, int old, int next)
{ int prior = *value; if (prior == old) *value = next; return prior; }
static void atomic_set_release(int *value, int next) { *value = next; }
static int swapz_ticket_claim_under_queue_lock(const struct swapz_ticket_ref *ref,
                                              const struct swapz_ticket_key *key)
{ assert(ref && key); ++broker_calls; return -1; }
'''
TEST = r'''
#define CHECK(expr) do { if (!(expr)) { fprintf(stderr, "unsafe-claim line=%d\n", __LINE__); return 3; } } while (0)
int main(void)
{
    int broker = 0, other = 0, target = 0, storage = 0, bdev = 0;
    const swapz_u8 payload = 42;
    struct bio bio = { {8}, &bdev };
    const struct swapz_dm good_ctx = {
        .queue_lock = true, .accepting = true, .target = &target,
        .original_storage = &storage, .original_route = {1, 2, 3, 4},
        .original_cap = {&broker, 1, 2}
    };
    const struct swapz_bio_ref good_entry = { .bio = &bio };
    const struct swapz_ticket_ref good_ref = {&broker, 1, 9, 0};
    const struct swapz_ticket_view good_view = {&payload, {1, 2, 3, 1, 7, 1, 4096, 0x5a, 1, 1, 0}};
    for (unsigned int test = 0; test < 20; ++test) {
        struct swapz_dm ctx = good_ctx;
        struct swapz_bio_ref entry = good_entry;
        struct swapz_ticket_ref ref = good_ref;
        struct swapz_ticket_view view = good_view;
        switch (test) {
        case 1: ctx.accepting = false; break;
        case 2: ctx.failed = true; break;
        case 3: entry.list = true; break;
        case 4: entry.preparation_list = true; break;
        case 5: entry.prepared_page = &target; break;
        case 6: ctx.original_storage = NULL; break;
        case 7: ctx.original_route.registration_epoch = 0; break;
        case 8: ref.broker = &other; break;
        case 9: ref.session = 8; break;
        case 10: ctx.original_cap.epoch = 8; break;
        case 11: view.key.target_session = 8; break;
        case 12: view.key.table_epoch = 8; break;
        case 13: view.key.target_epoch = 8; break;
        case 14: view.key.logical_page = 2; break;
        case 15: view.bytes = NULL; break;
        case 16: view.key.length = 3569; break;
        case 17: view.key.decoded_length = 4095; break;
        case 18: view.key.representation = 2; break;
        case 19: view.key.dictionary = 1; break;
        default: break;
        }
        void *expected_broker = ref.broker;
        const u64 expected_session = ref.session;
        CHECK(!swapz_round090_claim_locked(&ctx, &entry, &ref, &view));
        CHECK(ref.broker == expected_broker && ref.session == expected_session &&
              !entry.original_claim.broker && !entry.original_gc_epoch &&
              !ctx.original_release_busy && !broker_calls);
    }
    puts("ROUND090_CLAIM_REFUSAL_PASS cases=20 broker_calls=0 AUTH=0");
    return 0;
}
'''


def main():
    source = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'src/kernel/dm-target.c').read_text()
    credit = fragment(source, 'DESTINATION_CREDIT')
    claim = fragment(source, 'ATOMIC_CLAIM')
    print('ROUND090_FRAGMENT_SHA256=' + hashlib.sha256((credit + claim).encode()).hexdigest())
    if len(sys.argv) == 1:
        anchor = 'list_add_tail(&entry->list, &ctx->incoming);'
        assert source.count(anchor) == 1
        assert 'bi_bvec_done' not in source
        mapping = source.split('static int swapz_map(struct dm_target *ti, struct bio *bio)', 1)[1].split('static void swapz_drain(', 1)[0]
        assert mapping.index('swapz_round090_candidate_get(ti, bio,') < mapping.index('spin_lock_irqsave(&ctx->queue_lock, flags)')
        assert mapping.index('original_claimed = swapz_round090_claim_locked') < mapping.index(anchor)
        assert mapping.index(anchor) < mapping.index('if (original_claimed)')
        assert 'swapz_shared_original_segment_pinned(a, segment)' in source
        assert source.count('SWAPZ_MAP_ORIGINAL') >= 4
        assert 'swapz_shared_storage_write(ctx->original_storage, &spec, &input)' in source
    original = '\t*generation = 0;\n\t*gc_epoch = 0;\n\treturn false;'
    assert credit.count(original) == 1
    mutant = credit.replace(original, '\t*generation = 7;\n\t*gc_epoch = 11;\n\treturn true;', 1)
    with tempfile.TemporaryDirectory(prefix='round090-claim-') as directory:
        program = Path(directory) / 'claim.c'
        executable = program.with_suffix('')
        for compiler in ('gcc', 'clang'):
            for name, code in (('baseline', credit), ('fake-credit-mutant', mutant)):
                program.write_text(ADAPTER + code + claim + TEST)
                subprocess.run([compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                                '-Wconversion', '-Wshadow', '-Werror', '-fsanitize=address,undefined',
                                '-fno-pie', '-no-pie', str(program), '-o', str(executable)], check=True, timeout=30)
                result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
                if name == 'baseline':
                    if result.returncode or result.stderr or 'cases=20 broker_calls=0' not in result.stdout:
                        raise SystemExit(f'{compiler} baseline: {result.returncode} {result.stderr[:200]}')
                    print(compiler, result.stdout.strip())
                elif result.returncode != 3 or not result.stderr.startswith('unsafe-claim line='):
                    raise SystemExit(f'{compiler} mutant: {result.returncode} {result.stderr[:200]}')
                else:
                    print(compiler, 'ROUND090_FAKE_CREDIT_MUTANT_REJECTED count=1 AUTH=0')


if __name__ == '__main__':
    main()
