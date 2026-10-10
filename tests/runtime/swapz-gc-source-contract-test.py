#!/usr/bin/env python3
"""Unprivileged audit of actual production C GC decoding and generation guards.

This extracts selected pure functions verbatim from kernel/dm-swapz.c,
compiles only those functions against tiny userspace stand-ins, and
simulates overwriting the shared write-compaction scratch page.
No kernel module, block device, swap, or privileged syscall is used.
"""

from __future__ import annotations

import errno
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
KERNEL_SOURCE = ROOT / "kernel" / "dm-swapz.c"

def extract_function(source: str, name: str) -> str:
    matches = list(re.finditer(
        r"\bstatic\s+(?:int|bool|void)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", source, re.DOTALL,
    ))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name} production C function")
    start, brace = matches[0].start(), matches[0].end() - 1
    level = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            level += 1
        elif source[index] == "}":
            level -= 1
            if level == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated {name} C definition")


def gc_contract(source: str) -> None:
    """Fail when the dedicated GC source buffer is removed or aliased."""
    cleaned = extract_function(source, "swapz_clean_segment")
    decoded = extract_function(source, "swapz_decode_loaded_mapping")
    repacker = extract_function(source, "swapz_compact_fill_buffer")
    reader = extract_function(source, "swapz_read_mapping")
    ctor = extract_function(source, "swapz_ctr")
    destructor = extract_function(source, "swapz_free_context")

    if "gc_source_buffer" not in source.split("struct swapz_context {", 1)[1].split("};", 1)[0]:
        raise AssertionError("GC source snapshot is not a context-owned buffer")
    read_call = re.search(
        r"swapz_read_block\s*\(\s*context\s*,\s*physical_block\s*,\s*"
        r"context->gc_source_buffer\s*\)", cleaned,
    )
    decode_call = re.search(
        r"swapz_decode_loaded_mapping\s*\(\s*page\s*,\s*&mapping\s*,\s*"
        r"context->gc_source_buffer\s*,\s*context->input_buffer\s*\)", cleaned,
    )
    if not read_call or not decode_call or read_call.start() >= decode_call.start():
        raise AssertionError("GC must read and decode the same dedicated source snapshot")
    if not (cleaned.index("swapz_read_block") <
            cleaned.index("for (record_index = 0; record_index < record_count") <
            cleaned.index("swapz_decode_loaded_mapping") <
            cleaned.index("swapz_store_page")):
        raise AssertionError("GC source decode/store order changed")
    if "context->io_buffer" in cleaned:
        raise AssertionError("GC must not reload or decode a source from compaction scratch")
    if "context->io_buffer" not in repacker:
        raise AssertionError("compactor's scratch aliasing assumption needs review")
    if "context->gc_source_buffer" not in ctor or \
            "__get_free_page(GFP_KERNEL)" not in ctor or \
            "!context->gc_source_buffer" not in ctor:
        raise AssertionError("GC snapshot lacks owned preallocation and fail-closed allocation")
    if "free_page((unsigned long)context->gc_source_buffer)" not in destructor:
        raise AssertionError("GC snapshot is not freed on teardown/failure unwind")
    if "context->io_buffer" not in reader:
        raise AssertionError("ordinary reads must retain independent io_buffer handling")

    if "const void *source_block" not in decoded:
        raise AssertionError("decoder does not accept an explicitly pinned source block")
    if "context->io_buffer" in decoded:
        raise AssertionError("decoder accesses shared scratch instead of source_block")
    if decoded.count("source_block") < 4:
        raise AssertionError("raw and compressed paths must both use source_block")
    if "context->io_buffer" not in source:
        raise AssertionError("unexpected removal of ordinary shared scratch")


C_PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define SWAPZ_BLOCK_BYTES 4096
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_MAX_PACKED_RECORDS 64
#define SWAPZ_MAP_COMPRESSED 2
#define SWAPZ_CONTAINER_BASE_BYTES ((unsigned int)sizeof(struct swapz_container_disk))
#define le32_to_cpu(x) (x)
#define le16_to_cpu(x) (x)
struct swapz_mapping {
    uint32_t physical_block;
    uint16_t stored_length;
    uint8_t record_index;
    uint8_t flags;
};
struct swapz_record_disk {
    uint32_t logical_page;
    uint16_t offset;
    uint16_t length;
} __attribute__((packed));
struct swapz_container_disk {
    uint32_t magic;
    uint16_t version;
    uint16_t record_count;
    unsigned char data[];
} __attribute__((packed));
static const struct swapz_record_disk *
swapz_container_record_const(const void *buffer, unsigned int i) {
    return (const struct swapz_record_disk *)(
        (const unsigned char *)buffer + sizeof(struct swapz_container_disk) +
        i * sizeof(struct swapz_record_disk));
}
static int LZ4_decompress_safe(const char *src, char *dst, int n, int max_len) {
    /* Minimal deterministic stub: the full kernel LZ4 path is NOT tested. */
    if (n != 4 || max_len != 4096 || src[0] == '\0') return -1;
    memset(dst, (unsigned char)src[0], 4096);
    return 4096;
}
struct swapz_write_batch_record {
    uint32_t logical_page;
    uint32_t generation;
};
struct swapz_context { uint32_t *generations; };
"""
C_SUFFIX = r"""
static void prepare(unsigned char *memory) {
    struct swapz_container_disk *container = (void *)memory;
    struct swapz_record_disk *r = (void *)(memory + sizeof(*container));
    memset(memory, 0, SWAPZ_BLOCK_BYTES);
    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = 2;
    r[0].logical_page = 0;
    r[0].offset = 100;
    r[0].length = 4;
    r[1].logical_page = 1;
    r[1].offset = 200;
    r[1].length = 4;
    memory[100] = 'A';
    memory[200] = 'B';
}
int main(int argc, char **argv) {
    unsigned char gc_source[4096], shared_io[4096], decoded[4096];
    struct swapz_mapping first = {.stored_length=4, .record_index=0,
                                   .flags=SWAPZ_MAP_COMPRESSED};
    struct swapz_mapping second = {.stored_length=4, .record_index=1,
                                    .flags=SWAPZ_MAP_COMPRESSED};
    u32 generation = 8;
    struct swapz_context state = {.generations=&generation};
    struct swapz_write_batch_record pending = {.logical_page=0, .generation=8};
    int error;
    if (argc != 2) return 60;
    prepare(gc_source);
    prepare(shared_io);
    if (!strcmp(argv[1], "stable")) {
        if (swapz_decode_loaded_mapping(0, &first, gc_source, decoded) != 0 ||
            decoded[0] != 'A') return 11;
        /* Simulate swapz_compact_fill_buffer() overwriting io_buffer mid-GC. */
        memset(shared_io, 0xef, 4096);
        error = swapz_decode_loaded_mapping(1, &second, gc_source, decoded);
        if (error || decoded[0] != 'B') return 12;
        puts("INDEPENDENT_GC_SOURCE_OK");
    } else if (!strcmp(argv[1], "aliased")) {
        if (swapz_decode_loaded_mapping(0, &first, shared_io, decoded) != 0 ||
            decoded[0] != 'A') return 13;
        memset(shared_io, 0xef, 4096);
        error = swapz_decode_loaded_mapping(1, &second, shared_io, decoded);
        if (error != -EIO) return 14;
        puts("OLD_SHARED_SCRATCH_FAILED");
    } else if (!strcmp(argv[1], "raw")) {
        struct swapz_mapping raw = {.stored_length=4096, .flags=0};
        memset(shared_io, 0xff, 4096);
        error = swapz_decode_loaded_mapping(0, &raw, gc_source, decoded);
        if (error || decoded[100] != 'A') return 15;
        puts("RAW_DECODE_SOURCE_OK");
    } else if (!strcmp(argv[1], "corrupt")) {
        gc_source[200] = 0;
        error = swapz_decode_loaded_mapping(1, &second, gc_source, decoded);
        if (error != -EIO) return 16;
        puts("INVALID_COMPRESSED_RECORD_DENIED");
    } else if (!strcmp(argv[1], "mismatch")) {
        error = swapz_decode_loaded_mapping(0, &second, gc_source, decoded);
        if (error != -EIO) return 17;
        puts("FOREIGN_LOGICAL_PAGE_DENIED");
    } else if (!strcmp(argv[1], "live_generation")) {
        if (!swapz_stream_record_current(&state, &pending)) return 18;
        generation = 9;
        if (swapz_stream_record_current(&state, &pending)) return 19;
        puts("STALE_GENERATION_NOT_PUBLISHED");
    } else if (!strcmp(argv[1], "wrapped_generation")) {
        generation = 1;
        pending.generation = UINT32_MAX;
        if (swapz_stream_record_current(&state, &pending)) return 20;
        pending.generation = 1;
        if (!swapz_stream_record_current(&state, &pending)) return 21;
        puts("WRAPPED_STALE_GENERATION_NOT_PUBLISHED");
    } else {
        return 61;
    }
    return 0;
}
"""


class GCSourceSnapshotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = KERNEL_SOURCE.read_text(encoding="utf-8")
        gc_contract(cls.source)
        decoder = extract_function(cls.source, "swapz_decode_loaded_mapping")
        generation = extract_function(cls.source, "swapz_stream_record_current")
        cc = shutil.which("cc")
        if cc is None:
            raise AssertionError("rootless C compiler unavailable")
        cls.folder = tempfile.TemporaryDirectory(prefix="swapz-gc-c-audit-")
        cls.binary = Path(cls.folder.name) / "gc-pure-functions"
        source = Path(cls.folder.name) / "gc-pure-functions.c"
        source.write_text(C_PREFIX + decoder + "\n" + generation + "\n" + C_SUFFIX)
        cmd = [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
               "-o", str(cls.binary), str(source)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise AssertionError("production C decode compilation failed: " + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def run_case(self, name: str, expected: str) -> None:
        completed = subprocess.run([str(self.binary), name],
                                   capture_output=True, text=True, timeout=3)
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        self.assertIn(expected, completed.stdout)

    def test_compressed_second_record_survives_scratch_reuse(self):
        self.run_case("stable", "INDEPENDENT_GC_SOURCE_OK")

    def test_alias_reproduces_old_shared_scratch_failure(self):
        self.run_case("aliased", "OLD_SHARED_SCRATCH_FAILED")

    def test_raw_page_reads_explicit_source(self):
        self.run_case("raw", "RAW_DECODE_SOURCE_OK")

    def test_corrupt_compressed_payload_rejected(self):
        self.run_case("corrupt", "INVALID_COMPRESSED_RECORD_DENIED")

    def test_foreign_logical_page_rejected(self):
        self.run_case("mismatch", "FOREIGN_LOGICAL_PAGE_DENIED")

    def test_matching_generation_current(self):
        self.run_case("live_generation", "STALE_GENERATION_NOT_PUBLISHED")

    def test_wrap_boundary_stale_generation(self):
        self.run_case("wrapped_generation", "WRAPPED_STALE_GENERATION_NOT_PUBLISHED")

    def test_gc_reads_dedicated_source_before_first_live_record(self):
        gc_contract(self.source)

    def test_mutated_gc_read_to_shared_scratch_is_rejected(self):
        mutated = self.source.replace(
            "error = swapz_read_block(context, physical_block,\n"
            "\t\t\t\t\t context->gc_source_buffer);",
            "error = swapz_read_block(context, physical_block, context->io_buffer);", 1)
        self.assertNotEqual(mutated, self.source)
        with self.assertRaisesRegex(AssertionError, "dedicated source"):
            gc_contract(mutated)

    def test_mutated_gc_decode_to_shared_scratch_is_rejected(self):
        mutated = self.source.replace(
            "context->gc_source_buffer,\n"
            "\t\t\t\t\t\t\t context->input_buffer);",
            "context->io_buffer, context->input_buffer);", 1)
        self.assertNotEqual(mutated, self.source)
        with self.assertRaisesRegex(AssertionError, "dedicated source"):
            gc_contract(mutated)

    def test_mutated_snapshot_allocation_removed_is_rejected(self):
        mutated = self.source.replace(
            "context->gc_source_buffer = (void *)__get_free_page(GFP_KERNEL);",
            "context->gc_source_buffer = NULL;", 1)
        self.assertNotEqual(mutated, self.source)
        with self.assertRaisesRegex(AssertionError, "preallocation"):
            gc_contract(mutated)

    def test_mutated_snapshot_free_removed_is_rejected(self):
        mutated = self.source.replace(
            "free_page((unsigned long)context->gc_source_buffer);",
            "/* deliberately removed */", 1)
        self.assertNotEqual(mutated, self.source)
        with self.assertRaisesRegex(AssertionError, "not freed"):
            gc_contract(mutated)

    def test_gc_victim_freed_only_after_drain_and_zero_live(self):
        gc = extract_function(self.source, "swapz_clean_segment")
        self.assertLess(gc.index("swapz_flush_write_batch"),
                        gc.index("context->segment_live_blocks[victim] != 0"))
        self.assertLess(gc.index("context->segment_live_blocks[victim] != 0"),
                        gc.index("context->segment_state[victim] = SWAPZ_SEGMENT_FREE"))
        self.assertIn("context->segment_state[victim] = SWAPZ_SEGMENT_CLOSED;", gc)
        self.assertIn("swapz_set_failed(context, error)", gc)

    def test_foreground_write_previous_generation_flushes_before_increment(self):
        body = extract_function(self.source, "swapz_process_write")
        self.assertLess(body.index("swapz_commit_previous_generation"),
                        body.index("generation = previous_generation + 1"))
        self.assertIn("context->generations[logical_page] = previous_generation", body)

    def test_async_write_failure_keeps_early_completed_staged_data(self):
        body = extract_function(self.source, "swapz_finalize_stream_buffer")
        self.assertIn("record->upper_completed &&", body)
        self.assertIn("swapz_stream_record_current(context, record)", body)
        self.assertIn("buffer->state = SWAPZ_BUFFER_INFLIGHT;", body)
        self.assertLess(body.index("if (retain) {"),
                        body.index("swapz_reset_stream_buffer(context, buffer, SWAPZ_BUFFER_FREE);"))

    def test_full_flush_barrier_before_clean_victim_reclaim(self):
        body = extract_function(self.source, "swapz_clean_segment")
        self.assertLess(body.index("swapz_flush_write_batch"), body.index("swapz_try_discard_segment"))
        self.assertLess(body.index("swapz_try_discard_segment"), body.index("segment_high_water[victim] = 0"))

    def test_gc_source_allocated_only_at_constructor(self):
        body = extract_function(self.source, "swapz_clean_segment")
        self.assertNotIn("__get_free_page", body)
        self.assertNotIn("GFP_KERNEL", body)
        self.assertNotIn("kmalloc", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
