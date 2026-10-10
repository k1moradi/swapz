#!/usr/bin/env python3
"""Rootless exact-production-C published mapping lower-read bounds contract.

The only lower read is a deterministic in-memory stand-in. The production
mapping-validation, decoder and read functions are extracted without edits.
No privileged operations, kernel loading, DM, swap, loop, NBD or devices.
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
GUARD = (
    "\tif (unlikely(mapping.physical_block >= context->physical_blocks))\n"
    "\t\treturn -EUCLEAN;\n"
)


def exact_function(source: str, name: str) -> str:
    pattern = (r"\bstatic\s+(?:inline\s+)?(?:bool|int)\s+" +
               re.escape(name) + r"\s*\([^;{}]*\)\s*\{")
    found = list(re.finditer(pattern, source, flags=re.DOTALL))
    if len(found) != 1:
        raise AssertionError(f"expected exactly one production function {name}")
    level = 0
    for index in range(found[0].end() - 1, len(source)):
        if source[index] == "{":
            level += 1
        elif source[index] == "}":
            level -= 1
            if level == 0:
                return source[found[0].start():index + 1]
    raise AssertionError(f"unterminated function {name}")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAP_VALID 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_CONTAINER_BASE_BYTES ((unsigned int)sizeof(struct swapz_container_disk))
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define le32_to_cpu(v) (v)
#define le16_to_cpu(v) (v)
#define unlikely(v) (v)

struct swapz_mapping {
    u32 physical_block;
    u16 stored_length;
    u8 record_index;
    u8 flags;
};
struct swapz_record_disk {
    u32 logical_page;
    u16 offset;
    u16 length;
} __attribute__((packed));
struct swapz_container_disk {
    u32 magic;
    u16 version;
    u16 record_count;
    u8 data[];
} __attribute__((packed));
struct swapz_context {
    struct swapz_mapping mappings[1];
    u32 physical_blocks;
    void *io_buffer;
    struct { u64 compaction_read_bytes; } stats;
};

static const struct swapz_record_disk *
swapz_container_record_const(const void *block, unsigned int index)
{
    return (const struct swapz_record_disk *)(
        (const u8 *)block + SWAPZ_CONTAINER_BASE_BYTES +
        index * sizeof(struct swapz_record_disk));
}

static unsigned int lower_read_calls;
static u32 lower_read_last;
static bool mock_compressed;
static bool mock_io_error;

static int swapz_read_block(struct swapz_context *context,
                            u32 physical_block, void *destination)
{
    (void)context;
    lower_read_calls++;
    lower_read_last = physical_block;
    if (mock_io_error)
        return -EIO;
    memset(destination, 'R', SWAPZ_BLOCK_BYTES);
    if (mock_compressed) {
        struct swapz_container_disk *container = destination;
        struct swapz_record_disk *disk = (void *)((u8 *)destination +
                                                SWAPZ_CONTAINER_BASE_BYTES);
        container->magic = SWAPZ_CONTAINER_MAGIC;
        container->version = SWAPZ_CONTAINER_VERSION;
        container->record_count = 1;
        disk->logical_page = 0;
        disk->offset = SWAPZ_BLOCK_BYTES - 4;
        disk->length = 4;
        memcpy((u8 *)destination + SWAPZ_BLOCK_BYTES - 4, "QQQQ", 4);
    }
    return 0;
}

static int LZ4_decompress_safe(const char *source, char *destination,
                               int compressed, int uncompressed)
{
    if (compressed != 4 || uncompressed != SWAPZ_BLOCK_BYTES ||
        source[0] != 'Q')
        return -1;
    memset(destination, 'Z', SWAPZ_BLOCK_BYTES);
    return SWAPZ_BLOCK_BYTES;
}
"""

SUFFIX = r"""
static int run_case(unsigned int scenario, bool mutant)
{
    struct swapz_context context = {0};
    u8 backing_data[SWAPZ_BLOCK_BYTES] = {0};
    u8 destination[SWAPZ_BLOCK_BYTES];
    struct swapz_mapping *mapping = &context.mappings[0];
    int result;
    bool compaction = scenario == 8;

    context.io_buffer = backing_data;
    context.physical_blocks = 3;
    mapping->physical_block = 1;
    mapping->stored_length = SWAPZ_BLOCK_BYTES;
    mapping->flags = SWAPZ_MAP_VALID;
    lower_read_calls = 0;
    lower_read_last = UINT32_MAX;
    mock_compressed = false;
    mock_io_error = false;
    memset(destination, 'X', sizeof(destination));

    switch (scenario) {
    case 0: mapping->flags = 0; break; /* Unmapped: zero fill, no disk read. */
    case 1: mapping->physical_block = 0; break; /* Lower bound inclusive. */
    case 2: mapping->physical_block = 2; break; /* Upper bound inclusive. */
    case 3: mapping->physical_block = 3; break; /* First invalid sector. */
    case 4: mapping->physical_block = UINT32_MAX; break;
    case 5: /* Invalid compressed mapping must not reach lower IO either. */
        mapping->physical_block = 3;
        mapping->stored_length = 4;
        mapping->flags |= SWAPZ_MAP_COMPRESSED;
        mock_compressed = true;
        break;
    case 6: /* Valid compressed mapping still decodes. */
        mapping->stored_length = 4;
        mapping->flags |= SWAPZ_MAP_COMPRESSED;
        mock_compressed = true;
        break;
    case 7: mock_io_error = true; break; /* Existing lower failure propagation. */
    case 8: break; /* GC read counter must only count real lower reads. */
    default: return 60;
    }

    result = swapz_read_mapping(&context, 0, destination, compaction);
    if (mutant) {
        if ((scenario != 3 && scenario != 4) || result ||
            lower_read_calls != 1 || lower_read_last != mapping->physical_block ||
            destination[0] != 'R')
            return 61;
        puts("OLD_PUBLISHED_MAP_OUT_OF_RANGE_LOWER_READ");
        return 0;
    }

    if (scenario == 0) {
        if (result || lower_read_calls || destination[0] != 0 ||
            context.stats.compaction_read_bytes)
            return 62;
        return 0;
    }
    if (scenario == 3 || scenario == 4 || scenario == 5) {
        if (result != -EUCLEAN || lower_read_calls ||
            destination[0] != 'X' || context.stats.compaction_read_bytes)
            return 63;
        return 0;
    }
    if (scenario == 7) {
        if (result != -EIO || lower_read_calls != 1 ||
            destination[0] != 'X' || context.stats.compaction_read_bytes)
            return 64;
        return 0;
    }
    if (result || lower_read_calls != 1 ||
        lower_read_last != mapping->physical_block ||
        destination[0] != (scenario == 6 ? 'Z' : 'R') ||
        context.stats.compaction_read_bytes !=
            (scenario == 8 ? SWAPZ_BLOCK_BYTES : 0))
        return 65;
    return 0;
}

int main(int argc, char **argv)
{
    char *end = NULL;
    unsigned long scenario;
    int result;

    if (argc != 3)
        return 70;
    scenario = strtoul(argv[1], &end, 10);
    if (end == argv[1] || *end || scenario > 8)
        return 71;
    result = run_case((unsigned int)scenario, argv[2][0] == 'm');
    if (!result)
        printf("PUBLISHED_READ_BOUNDS_CASE_%lu_OK\n", scenario);
    return result;
}
"""


class PublishedReadBoundsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = KERNEL.read_text(encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise AssertionError("mandatory C compiler is unavailable")

        read = exact_function(source, "swapz_read_mapping")
        if read.count(GUARD) != 1:
            raise AssertionError("mandatory production pre-I/O extent guard missing")
        if read.index(GUARD) > read.index("swapz_read_block(context,"):
            raise AssertionError("extent guard must precede every lower read")

        functions = [exact_function(source, name) for name in (
            "swapz_mapping_valid", "swapz_decode_loaded_mapping")]
        cls.tmp = tempfile.TemporaryDirectory(
            prefix="swapz-published-read-exact-c-")
        root = Path(cls.tmp.name)

        def compile_binary(label: str, read_body: str) -> Path:
            path = root / f"{label}.c"
            exe = root / label
            path.write_text(PREFIX + "\n" + "\n".join(functions) + "\n" +
                            read_body + "\n" + SUFFIX, encoding="utf-8")
            result = subprocess.run(
                [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-o", str(exe), str(path)],
                capture_output=True, text=True, timeout=15, check=False)
            if result.returncode:
                raise AssertionError(f"{label} compile failed: {result.stderr}")
            return exe

        cls.production = compile_binary("production", read)
        cls.no_guard = compile_binary("removed-bound-guard",
                                      read.replace(GUARD, "", 1))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_case(self, scenario: int, mutant: bool = False) -> None:
        executable = self.no_guard if mutant else self.production
        result = subprocess.run(
            [str(executable), str(scenario), "mutant" if mutant else "production"],
            capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"PUBLISHED_READ_BOUNDS_CASE_{scenario}_OK", result.stdout)
        if mutant:
            self.assertIn("OLD_PUBLISHED_MAP_OUT_OF_RANGE_LOWER_READ",
                          result.stdout)

    def test_valid_and_unmapped_read_matrix(self):
        for scenario in (0, 1, 2, 6, 7, 8):
            with self.subTest(scenario=scenario):
                self.run_case(scenario)

    def test_out_of_range_published_mapping_never_reaches_lower_read(self):
        for scenario in (3, 4, 5):
            with self.subTest(scenario=scenario):
                self.run_case(scenario)

    def test_removed_guard_exposes_outside_target_read(self):
        for scenario in (3, 4):
            with self.subTest(scenario=scenario):
                self.run_case(scenario, mutant=True)

    def test_read_guard_before_io_is_mandatory(self):
        body = exact_function(KERNEL.read_text(encoding="utf-8"),
                              "swapz_read_mapping")
        self.assertEqual(body.count(GUARD), 1)
        self.assertLess(body.index(GUARD),
                        body.index("swapz_read_block(context,"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
