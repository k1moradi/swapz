#!/usr/bin/env python3
"""Production-C foreground generation/GC transaction contract, entirely rootless.

Extracts the exact production range, current-record, previous-generation and
foreground write functions. Replaces only non-pure kernel/IO callees with
bounded deterministic callbacks injecting nested GC and failure transitions.
This is not actual kernel, dm-io, LZ4 or device qualification.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "kernel" / "dm-swapz.c"
FUNCTIONS = ("swapz_checked_page_index", "swapz_stream_record_current",
             "swapz_page_has_uncommitted_generation",
             "swapz_commit_previous_generation", "swapz_process_write")


def extract(source: str, name: str) -> str:
    matches = list(re.finditer(
        r"\bstatic\s+(?:int|bool)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", source, re.DOTALL,
    ))
    if len(matches) != 1:
        raise AssertionError(f"missing or duplicated production function: {name}")
    begin = matches[0].start()
    brace = matches[0].end() - 1
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if not depth:
                return source[begin:i + 1]
    raise AssertionError(f"unterminated production C function: {name}")


def contract(source: str) -> None:
    write = extract(source, "swapz_process_write")
    previous = extract(source, "swapz_commit_previous_generation")
    gc_match = re.search(r"\bstatic\s+int\s+swapz_clean_segment\s*\([^;{}]*\)\s*\{",
                         source, re.DOTALL)
    if gc_match is None:
        raise AssertionError("GC entry missing")
    gc_part = source[gc_match.start():source.index("static int swapz_open_free_segment",
                                                  gc_match.start())]
    ordering = (
        "swapz_checked_page_index",
        "swapz_commit_previous_generation",
        "previous_generation = context->generations[logical_page]",
        "context->generations[logical_page] = generation",
        "swapz_copy_from_bio",
        "error = swapz_store_page",
        "context->generations[logical_page] = previous_generation",
    )
    offsets = [write.find(part) for part in ordering]
    if any(x < 0 for x in offsets) or offsets != sorted(offsets):
        raise AssertionError("foreground validation / prior commit / rollback order violated")
    if "if (error && context->generations[logical_page] == generation)" not in write:
        raise AssertionError("foreground write lacks conditional generation rollback")
    if "if (unlikely(!generation))" not in write or "generation++;" not in write:
        raise AssertionError("generation zero avoidance missing")
    if ("swapz_flush_pack" not in previous or
            "swapz_flush_write_batch" not in previous or
            previous.index("swapz_flush_pack") >=
            previous.index("swapz_flush_write_batch")):
        raise AssertionError("previous generation not fully committed before replacement")
    if "if (!swapz_page_has_uncommitted_generation(context, logical_page))" not in previous:
        raise AssertionError("previous generation uncommitted check missing")
    if not (gc_part.index("swapz_decode_loaded_mapping") <
            gc_part.index("error = swapz_store_page") <
            gc_part.index("swapz_flush_write_batch") <
            gc_part.index("context->segment_state[victim] = SWAPZ_SEGMENT_FREE")):
        raise AssertionError("GC relocate/flush/reclaim barriers missing")
    if ("context->generations[page]" not in gc_part or
            "context->gc_source_buffer" not in gc_part or
            "context->gc_compressed_buffer" not in gc_part):
        raise AssertionError("GC should preserve the current generation and isolated data")
    stale = extract(source, "swapz_stream_record_current")
    if "record->generation == context->generations[record->logical_page]" not in stale:
        raise AssertionError("stale stream record can be treated as current")
    queued = extract(source, "swapz_page_has_uncommitted_generation")
    if ("ref->valid && ref->generation == generation" not in queued or
            "pending->generation == generation" not in queued):
        raise AssertionError("previous-generation committed detection is incomplete")


PREFIX = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
typedef uint64_t sector_t;
#define SWAPZ_BLOCK_SECTORS 8ULL
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define unlikely(x) (x)
struct bio { struct { sector_t bi_sector; } bi_iter; u8 payload[4096]; };
struct swapz_staged_ref { u32 generation; u8 block_index, record_index, buffer_id, valid; };
struct swapz_pending_record {
    struct bio *bio; u32 logical_page, generation; u16 stored_length; u8 record_index;
};
struct swapz_write_batch_record { struct bio *bio; u32 logical_page, generation; };
struct swapz_context {
    u32 logical_pages;
    u32 generations[2];
    struct swapz_staged_ref staged_refs[2];
    unsigned int pack_record_count;
    struct swapz_pending_record pending[SWAPZ_MAX_PACKED_RECORDS];
    u8 write_page[SWAPZ_BLOCK_BYTES], compressed_page[SWAPZ_BLOCK_BYTES];
    void *write_buffer, *write_compressed_buffer;
    struct { uint64_t logical_write_bytes; } stats;
    u8 old_mapping_value, pending_write_value, relocated_gc_value;
    bool mapped, new_pending;
    u32 pending_write_generation, gc_record_generation;
    bool gc_trigger, fail_pack, fail_batch, fail_store;
    unsigned int gc_runs, copy_runs, store_runs, pack_runs, batch_runs;
    char trace[32]; unsigned int trace_len;
};
static void event(struct swapz_context *c, char ch) {
    if (c->trace_len < sizeof(c->trace) - 1) c->trace[c->trace_len++] = ch;
}
static int swapz_flush_pack(struct swapz_context *, bool, bool);
static int swapz_flush_write_batch(struct swapz_context *);
static void swapz_copy_from_bio(struct bio *, void *);
static int swapz_store_page(struct swapz_context *, struct bio *, u32, u32,
                            const void *, void *, bool, bool);
"""
SUFFIX = r"""
static int swapz_flush_pack(struct swapz_context *c, bool compact, bool rotate) {
    (void)compact; (void)rotate;
    c->pack_runs++; event(c, 'P');
    if (c->fail_pack) return -EIO;
    c->pack_record_count = 0;
    return 0;
}
static int swapz_flush_write_batch(struct swapz_context *c) {
    c->batch_runs++; event(c, 'B');
    if (c->fail_batch) return -EIO;
    c->staged_refs[0].valid = 0;
    return 0;
}
static void swapz_copy_from_bio(struct bio *bio, void *dst) {
    memcpy(dst, bio->payload, SWAPZ_BLOCK_BYTES);
}
static int swapz_store_page(struct swapz_context *c, struct bio *bio, u32 page, u32 gen,
                            const void *payload, void *compressed, bool compact,
                            bool rotate) {
    (void)bio; (void)compressed; (void)compact; (void)rotate;
    c->store_runs++; event(c, 'S');
    if (c->gc_trigger) {
        /*
         * A deterministic nested GC callback while the foreground write has
         * tentatively advanced its generation. Real GC flushes the relocated
         * old mapping before the foreground record can be staged.
         */
        c->gc_runs++; event(c, 'G');
        c->gc_record_generation = c->generations[page];
        c->relocated_gc_value = c->old_mapping_value;
        if (c->gc_record_generation != gen || !c->mapped) return -EUCLEAN;
    }
    if (c->fail_store) return -ENOSPC;
    c->new_pending = true;
    c->pending_write_generation = gen;
    c->pending_write_value = *(const u8 *)payload;
    return 0;
}
static struct swapz_context fresh(u32 gen) {
    struct swapz_context c;
    memset(&c, 0, sizeof(c));
    c.logical_pages = 1;
    c.generations[0] = gen;
    c.mapped = true;
    c.old_mapping_value = 'O';
    /* Set pointer fields only after copying fresh context to the caller. */
    return c;
}
static int run(int mode) {
    struct swapz_context c = fresh(mode == 8 || mode == 9 ? UINT32_MAX : 7);
    struct bio bio = {0};
    struct swapz_write_batch_record old = {.logical_page=0, .generation=c.generations[0]};
    u32 expected = c.generations[0] == UINT32_MAX ? 1 : c.generations[0] + 1;
    const u32 prior = c.generations[0];
    int rc;
    c.write_buffer = c.write_page;
    c.write_compressed_buffer = c.compressed_page;
    bio.payload[0] = 'N';
    switch (mode) {
        case 1: case 5: case 10:
            c.staged_refs[0].valid = 1;
            c.staged_refs[0].generation = prior;
            if (mode == 5 || mode == 10) c.gc_trigger = true;
            break;
        case 2:
            c.pending[0].logical_page = 0;
            c.pending[0].generation = prior;
            c.pack_record_count = 1;
            break;
        case 3:
            c.staged_refs[0].valid = 1;
            c.staged_refs[0].generation = prior;
            c.fail_pack = true;
            break;
        case 4:
            c.staged_refs[0].valid = 1;
            c.staged_refs[0].generation = prior;
            c.fail_batch = true;
            break;
        case 6: case 7: case 9: case 10:
            c.gc_trigger = true;
            break;
        default: break;
    }
    if (mode == 7 || mode == 9 || mode == 10) c.fail_store = true;
    if (mode == 9) c.generations[0] = UINT32_MAX;
    if (mode == 9) old.generation = UINT32_MAX;
    if (mode == 11) bio.bi_iter.bi_sector = 8; /* end-of-extent */
    if (mode == 12) bio.bi_iter.bi_sector = ((sector_t)1 << 32) * 8;
    if (mode == 13) bio.bi_iter.bi_sector = 7; /* misaligned */
    rc = swapz_process_write(&c, &bio);
    if (mode == 3 || mode == 4) {
        if (rc != -EIO || c.generations[0] != prior ||
            c.store_runs || c.copy_runs || c.new_pending ||
            c.old_mapping_value != 'O') return 30;
        if (mode == 3 && (c.pack_runs != 1 || c.batch_runs != 0)) return 31;
        if (mode == 4 && (c.pack_runs != 1 || c.batch_runs != 1)) return 32;
    } else if (mode == 7 || mode == 9 || mode == 10) {
        u32 orig = mode == 9 ? UINT32_MAX : prior;
        if (rc != -ENOSPC || c.generations[0] != orig ||
            c.new_pending || c.gc_runs != 1 || c.old_mapping_value != 'O' ||
            c.relocated_gc_value != 'O') return 33;
        if (mode == 9 && c.gc_record_generation != 1) return 34;
        if (mode == 10 && (c.pack_runs != 1 || c.batch_runs != 1)) return 35;
    } else if (mode == 11 || mode == 12 || mode == 13) {
        if (rc != (mode == 13 ? -EINVAL : -ERANGE) ||
            c.generations[0] != prior || c.store_runs != 0 ||
            c.pack_runs != 0 || c.batch_runs != 0) return 36;
    } else {
        if (rc || c.generations[0] != expected || !c.new_pending ||
            c.pending_write_generation != expected || c.pending_write_value != 'N' ||
            c.old_mapping_value != 'O') return 37;
        if ((mode == 1 || mode == 2 || mode == 5) &&
            (c.pack_runs != 1 || c.batch_runs != 1)) return 38;
        if ((mode == 0 || mode == 6 || mode == 8) &&
            (c.pack_runs || c.batch_runs)) return 39;
        if ((mode == 5 || mode == 6) &&
            (c.gc_runs != 1 || c.gc_record_generation != expected ||
             c.relocated_gc_value != 'O')) return 40;
        if (mode == 1 || mode == 2 || mode == 5) {
            const char *prefix = "PB";
            if (memcmp(c.trace, prefix, 2)) return 41;
        }
        if (swapz_stream_record_current(&c, &old)) return 42;
        /* Reap/publication of a fully accepted write must supersede GC's old bytes. */
        if (c.pending_write_generation == c.generations[0])
            c.old_mapping_value = c.pending_write_value;
        if (c.old_mapping_value != 'N') return 43;
    }
    printf("WRITE_GENERATION_TRANSACTION_%d_OK\n", mode);
    return 0;
}
int main(int argc, char **argv) {
    int mode = -1;
    if (argc != 2 || sscanf(argv[1], "%d", &mode) != 1 || mode < 0 || mode > 13)
        return 99;
    return run(mode);
}
"""


class ForegroundGenerationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = KERNEL.read_text(encoding="utf-8")
        contract(cls.source)
        cc = shutil.which("cc")
        if cc is None:
            raise AssertionError("C compiler required for production-C qualification")
        cls.tmp = tempfile.TemporaryDirectory(prefix="swapz-generation-rootless-")
        cls.binary = Path(cls.tmp.name) / "write-generation"
        program = Path(cls.tmp.name) / "write-generation.c"
        functions = "\n".join(extract(cls.source, name) for name in FUNCTIONS)
        program.write_text(PREFIX + functions + SUFFIX, encoding="utf-8")
        build = subprocess.run(
            [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-o", str(cls.binary), str(program)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if build.returncode:
            raise AssertionError("exact production C generation harness failed to compile: " + build.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def scenario(self, mode: int) -> None:
        result = subprocess.run([str(self.binary), str(mode)],
                                capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(result.returncode, 0,
                         f"case={mode} {result.stdout} {result.stderr}")
        self.assertIn(f"WRITE_GENERATION_TRANSACTION_{mode}_OK", result.stdout)

    def test_plain_staged_write_preserves_old_until_publication(self):
        self.scenario(0)

    def test_previous_staged_ref_flushed_before_generation_increment(self):
        self.scenario(1)

    def test_previous_pending_pack_flushed_before_generation_increment(self):
        self.scenario(2)

    def test_previous_pack_error_does_not_advance_generation(self):
        self.scenario(3)

    def test_previous_batch_error_does_not_advance_generation(self):
        self.scenario(4)

    def test_gc_nested_after_previous_generation_commit(self):
        self.scenario(5)

    def test_gc_nested_before_new_write_staged(self):
        self.scenario(6)

    def test_failed_new_store_rolls_back_after_nested_gc(self):
        self.scenario(7)

    def test_generation_wrap_skips_zero_and_stages_valid_one(self):
        self.scenario(8)

    def test_nested_gc_failure_with_generation_wrap_restores_max(self):
        self.scenario(9)

    def test_failed_store_after_previous_commit_and_nested_gc(self):
        self.scenario(10)

    def test_page_at_logical_end_rejected_without_side_effects(self):
        self.scenario(11)

    def test_u32_alias_sector_rejected_without_side_effects(self):
        self.scenario(12)

    def test_misaligned_sector_rejected_without_side_effects(self):
        self.scenario(13)

    def test_real_source_invariant_ordering(self):
        contract(self.source)

    def test_mutant_early_generation_advance_rejected(self):
        body = extract(self.source, "swapz_process_write")
        old = "error = swapz_commit_previous_generation(context, logical_page);"
        self.assertIn(old, body)
        mutated = self.source.replace(old, "error = 0;", 1)
        with self.assertRaisesRegex(AssertionError, "prior commit"):
            contract(mutated)

    def test_mutant_missing_generation_rollback_rejected(self):
        old = "if (error && context->generations[logical_page] == generation)"
        self.assertIn(old, self.source)
        mutated = self.source.replace(old, "if (false)", 1)
        with self.assertRaisesRegex(AssertionError, "conditional generation rollback"):
            contract(mutated)

    def test_mutant_stale_record_accepted_rejected(self):
        old = "record->generation == context->generations[record->logical_page]"
        self.assertIn(old, self.source)
        mutated = self.source.replace(old, "true", 1)
        with self.assertRaisesRegex(AssertionError, "stale stream record"):
            contract(mutated)

    def test_mutant_gc_generation_snapshot_removed_rejected(self):
        old = "context->generations[page],"
        self.assertIn(old, self.source)
        mutated = self.source.replace(old, "1, /* fabricated GC generation */", 1)
        with self.assertRaisesRegex(AssertionError, "GC should preserve"):
            contract(mutated)

    def test_mutant_previous_batch_flush_removed_rejected(self):
        old = "error = swapz_flush_write_batch(context);"
        body = extract(self.source, "swapz_commit_previous_generation")
        self.assertIn(old, body)
        mutated_body = body.replace(old, "error = 0;", 1)
        mutated = self.source.replace(body, mutated_body, 1)
        with self.assertRaisesRegex(AssertionError, "fully committed"):
            contract(mutated)

    def test_previous_gc_scratch_fixes_still_bound(self):
        body = extract(self.source, "swapz_clean_segment")
        self.assertIn("context->gc_source_buffer", body)
        self.assertIn("context->gc_compressed_buffer", body)
        self.assertNotIn("context->compressed_buffer", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
