#!/usr/bin/env python3
"""Rootless production C compressed-pack staging / GC scratch-alias contract.

Compiles the exact swapz_add_compressed_record() body from kernel/dm-swapz.c
with deterministic stand-in batch callbacks. No device or kernel operation.
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


def extract(source: str, function: str) -> str:
    found = list(re.finditer(
        r"\bstatic\s+int\s+" + re.escape(function) +
        r"\s*\([^;{}]*\)\s*\{", source, re.DOTALL,
    ))
    if len(found) != 1:
        raise AssertionError(f"expected exactly one production definition {function}")
    start = found[0].start()
    brace = found[0].end() - 1
    level = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            level += 1
        elif source[index] == "}":
            level -= 1
            if level == 0:
                return source[start:index + 1]
    raise AssertionError(f"unterminated production function {function}")


def enforce_source(source: str) -> None:
    gc = extract(source, "swapz_clean_segment")
    add = extract(source, "swapz_add_compressed_record")
    compactor_match = re.search(
        r"static void swapz_compact_fill_buffer\s*\([^;{}]*\)\s*\{",
        source, re.DOTALL,
    )
    if compactor_match is None:
        raise AssertionError("batch compaction source missing")
    source_tail = source[compactor_match.start():source.index(
        "static void swapz_complete_buffer_bios", compactor_match.start())]
    bound = re.search(
        r"swapz_store_page\s*\(\s*context\s*,\s*NULL\s*,\s*page\s*,"
        r"\s*context->generations\[page\]\s*,\s*context->input_buffer\s*,"
        r"\s*context->gc_compressed_buffer\s*,\s*true\s*,\s*false\s*\)", gc,
    )
    if bound is None:
        raise AssertionError("GC relocation is not bound to its private compressed page")
    if "context->compressed_buffer" not in source_tail:
        raise AssertionError("batch compactor shared compression scratch changed")
    if not (add.index("swapz_ensure_physical_block") <
            add.index("memcpy((u8 *)context->pack_buffer")):
        raise AssertionError("staging order changed: reassess nested scratch lifetime")
    ctx = source.split("struct swapz_context {", 1)[1].split("};", 1)[0]
    if "void *gc_compressed_buffer;" not in ctx:
        raise AssertionError("GC compressed output is not owned by context")
    ctor = extract(source, "swapz_ctr")
    dtor = re.search(r"static void swapz_free_context\s*\([^;{}]*\)\s*\{", source)
    if dtor is None:
        raise AssertionError("context free definition missing")
    free_context = source[dtor.start():source.index("static void swapz_dtr(", dtor.start())]
    alloc = re.search(
        r"context->gc_compressed_buffer\s*=\s*\(void \*\)"
        r"__get_free_page\(GFP_KERNEL\)", ctor,
    )
    if (alloc is None or "!context->gc_compressed_buffer" not in ctor):
        raise AssertionError("GC compression scratch must be preallocated fail-closed")
    if "free_page((unsigned long)context->gc_compressed_buffer)" not in free_context:
        raise AssertionError("GC compression scratch must be freed")
    if "gc_compressed_buffer" not in gc or "gc_compressed_buffer" in add:
        raise AssertionError("compressed pack accepts explicit caller-owned source")
    if "__get_free_page" in gc or "kmalloc(" in gc:
        raise AssertionError("GC hot path must not allocate scratch")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>

typedef uint32_t u32;
typedef uint16_t u16;
typedef uint8_t u8;
#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define unlikely(x) (x)
#define cpu_to_le16(x) (x)
#define cpu_to_le32(x) (x)
struct bio { int unused; };
struct swapz_record_disk {
    u32 logical_page;
    u16 offset, length;
} __attribute__((packed));
struct swapz_container_disk {
    u32 magic;
    u16 version, record_count;
    u8 data[];
} __attribute__((packed));
struct swapz_pending_record {
    struct bio *bio;
    u32 logical_page;
    u32 generation;
    u16 stored_length;
    u8 record_index;
};
struct swapz_context {
    unsigned int pack_record_count;
    unsigned int pack_payload_start;
    u8 pack_buffer[SWAPZ_BLOCK_BYTES];
    struct swapz_pending_record pending[SWAPZ_MAX_PACKED_RECORDS];
    struct {
        unsigned long long compressed_payload_bytes, compressed_pages;
    } stats;
    u8 compressed_buffer[SWAPZ_BLOCK_BYTES];
    u8 gc_compressed_buffer[SWAPZ_BLOCK_BYTES];
    int ensure_calls, flush_calls, fail_ensure;
};
static inline struct swapz_record_disk *
swapz_container_record(void *buffer, unsigned int index) {
    return (struct swapz_record_disk *)((u8 *)buffer +
        sizeof(struct swapz_container_disk) + index * sizeof(struct swapz_record_disk));
}
static int swapz_pack_can_fit(const struct swapz_context *c, unsigned int length) {
    return c->pack_record_count < SWAPZ_MAX_PACKED_RECORDS &&
           length <= c->pack_payload_start &&
           sizeof(struct swapz_container_disk) +
               (c->pack_record_count + 1) * sizeof(struct swapz_record_disk)
               <= c->pack_payload_start - length;
}
static int swapz_ensure_physical_block(struct swapz_context *c, bool rotate) {
    (void)rotate;
    c->ensure_calls++;
    /* Adversarial nested write-batch compaction clobbers its own scratch. */
    memset(c->compressed_buffer, 'X', SWAPZ_BLOCK_BYTES);
    return c->fail_ensure ? -EIO : 0;
}
static bool swapz_pack_bios_match(struct swapz_context *c) {
    (void)c;return true; /* Scratch-isolation fixture has no upper BIOs. */
}
static void swapz_set_failed(struct swapz_context *c,int error) {
    (void)c;(void)error;
}
static void swapz_register_pending_bio(struct swapz_context *c,
                                        struct bio *bio,u8 index) {
    (void)c;(void)bio;(void)index;
}
static int swapz_flush_pack(struct swapz_context *c, bool compact, bool rotate) {
    (void)compact;
    (void)rotate;
    c->flush_calls++;
    memset(c->compressed_buffer, 'X', SWAPZ_BLOCK_BYTES);
    c->pack_record_count = 0;
    c->pack_payload_start = SWAPZ_BLOCK_BYTES;
    return 0;
}
"""
SUFFIX = r"""
static int check_one(int mode, bool dedicated, bool fail) {
    struct swapz_context c;
    const u8 *data;
    struct swapz_record_disk *out;
    int error;
    memset(&c, 0, sizeof(c));
    c.pack_payload_start = mode ? 16U : SWAPZ_BLOCK_BYTES;
    c.pack_record_count = mode ? 1U : 0U;
    c.fail_ensure = fail;
    memset(c.gc_compressed_buffer, 'R', sizeof(c.gc_compressed_buffer));
    memset(c.compressed_buffer, 'R', sizeof(c.compressed_buffer));
    data = dedicated ? c.gc_compressed_buffer : c.compressed_buffer;
    error = swapz_add_compressed_record(&c, NULL, 17, 9, data, 4, true, false);
    if (fail) {
        if (error != -EIO || c.pack_record_count != 0 ||
            c.stats.compressed_pages != 0) return 20;
        return 0;
    }
    if (error || c.pack_record_count != 1 || c.ensure_calls != 1 ||
        c.flush_calls != (mode ? 1 : 0)) return 21;
    out = swapz_container_record(c.pack_buffer, 0);
    if (out->logical_page != 17 || out->length != 4 ||
        c.pending[0].generation != 9 || c.pending[0].logical_page != 17)
        return 22;
    if (c.pack_buffer[out->offset] != (dedicated ? 'R' : 'X'))
        return 23;
    if (c.gc_compressed_buffer[0] != 'R' ||
        c.compressed_buffer[0] != 'X') return 24;
    return 0;
}
int main(int argc, char **argv) {
    int result;
    if (argc != 2) return 60;
    if (!strcmp(argv[1], "first_dedicated")) {
        result = check_one(0, true, false);
        if (!result) puts("DEDICATED_FIRST_PACK_OK");
    } else if (!strcmp(argv[1], "first_aliased")) {
        result = check_one(0, false, false);
        if (!result) puts("OLD_FIRST_PACK_ALIAS_REPRODUCED");
    } else if (!strcmp(argv[1], "full_dedicated")) {
        result = check_one(1, true, false);
        if (!result) puts("DEDICATED_PACK_ROLLOVER_OK");
    } else if (!strcmp(argv[1], "full_aliased")) {
        result = check_one(1, false, false);
        if (!result) puts("OLD_PACK_ROLLOVER_ALIAS_REPRODUCED");
    } else if (!strcmp(argv[1], "io_error")) {
        result = check_one(0, true, true);
        if (!result) puts("FAILED_ENSURE_DOES_NOT_PUBLISH");
    } else {
        return 61;
    }
    return result;
}
"""


class GCCompressedAliasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = KERNEL.read_text(encoding="utf-8")
        enforce_source(cls.source)
        cc = shutil.which("cc")
        if cc is None:
            raise AssertionError("mandatory C compiler unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="swapz-gc-compressed-")
        cls.binary = Path(cls.temp.name) / "gc-compressed-c-contract"
        path = Path(cls.temp.name) / "gc-compressed-c-contract.c"
        body = extract(cls.source, "swapz_add_compressed_record")
        path.write_text(PREFIX + "\n" + body + "\n" + SUFFIX, encoding="utf-8")
        compiled = subprocess.run(
            [cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-o", str(cls.binary), str(path)],
            capture_output=True, text=True, timeout=12, check=False,
        )
        if compiled.returncode:
            raise AssertionError("production C staging failed compilation: " + compiled.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def exercise(self, mode: str, output: str) -> None:
        done = subprocess.run([str(self.binary), mode], capture_output=True,
                              text=True, timeout=4, check=False)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn(output, done.stdout)

    def test_dedicated_first_pack_preserves_compressed_payload(self):
        self.exercise("first_dedicated", "DEDICATED_FIRST_PACK_OK")

    def test_old_first_pack_alias_overwrites_payload(self):
        self.exercise("first_aliased", "OLD_FIRST_PACK_ALIAS_REPRODUCED")

    def test_dedicated_pack_rollover_preserves_payload(self):
        self.exercise("full_dedicated", "DEDICATED_PACK_ROLLOVER_OK")

    def test_old_full_pack_rollover_overwrites_payload(self):
        self.exercise("full_aliased", "OLD_PACK_ROLLOVER_ALIAS_REPRODUCED")

    def test_lower_reservation_error_does_not_publish(self):
        self.exercise("io_error", "FAILED_ENSURE_DOES_NOT_PUBLISH")

    def test_exact_gc_compression_source_isolation(self):
        enforce_source(self.source)

    def test_mutated_gc_passes_shared_compaction_scratch(self):
        old = "context->gc_compressed_buffer, true, false);"
        self.assertEqual(self.source.count(old), 1)
        bad = self.source.replace(old, "context->compressed_buffer, true, false);", 1)
        with self.assertRaisesRegex(AssertionError, "private compressed page"):
            enforce_source(bad)

    def test_missing_gc_compression_page_allocation_rejected(self):
        old = "context->gc_compressed_buffer = (void *)__get_free_page(GFP_KERNEL);"
        self.assertEqual(self.source.count(old), 1)
        bad = self.source.replace(old, "context->gc_compressed_buffer = NULL;", 1)
        with self.assertRaisesRegex(AssertionError, "preallocated"):
            enforce_source(bad)

    def test_missing_allocation_fail_closed_check_rejected(self):
        old = "!context->gc_compressed_buffer"
        self.assertGreaterEqual(self.source.count(old), 1)
        bad = self.source.replace(old, "true", 1)
        with self.assertRaisesRegex(AssertionError, "preallocated"):
            enforce_source(bad)

    def test_missing_page_cleanup_rejected(self):
        old = "free_page((unsigned long)context->gc_compressed_buffer);"
        self.assertEqual(self.source.count(old), 1)
        bad = self.source.replace(old, "/* missing cleanup */", 1)
        with self.assertRaisesRegex(AssertionError, "must be freed"):
            enforce_source(bad)

    def test_source_is_preallocated_not_hot_path(self):
        body = extract(self.source, "swapz_clean_segment")
        self.assertNotIn("__get_free_page", body)
        self.assertNotIn("kmalloc(", body)

    def test_foreground_compression_scratch_remains_separate(self):
        body = extract(self.source, "swapz_process_write")
        self.assertIn("context->write_compressed_buffer", body)
        self.assertNotIn("context->gc_compressed_buffer", body)

    def test_compactor_has_its_own_compressed_payload_scratch(self):
        self.assertIn("memcpy(context->compressed_buffer", self.source)
        self.assertIn("memcpy((u8 *)context->repack_buffer", self.source)
        self.assertIn("context->gc_compressed_buffer", self.source)

    def test_gc_source_snapshot_remains_independent(self):
        body = extract(self.source, "swapz_clean_segment")
        self.assertIn("context->gc_source_buffer", body)
        self.assertIn("context->gc_compressed_buffer", body)
        self.assertNotIn("context->compressed_buffer", body)

    def test_old_source_alias_guard_coexists(self):
        guard = ROOT / "tests" / "runtime" / "swapz-gc-source-contract-test.py"
        self.assertTrue(guard.is_file())
        self.assertIn("context->gc_source_buffer", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
