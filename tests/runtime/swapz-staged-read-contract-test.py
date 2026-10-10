#!/usr/bin/env python3
"""Rootless exact-production-C staged-read metadata admission regression.

Extracts swapz_read_staged() and its generation helper without substituting
their bodies. Models LZ4 decode with a bounded deterministic stub; no kernel,
block device, swap, module, NBD, privileged operation, or network is used.
"""

from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "kernel" / "dm-swapz.c"
FLAG_GUARD = (
    "\tif (record->flags != 0 && record->flags != SWAPZ_MAP_COMPRESSED)\n"
    "\t\treturn -EUCLEAN;\n"
)
COUNT_GUARD = (
    "\t\t    le16_to_cpu(container->record_count) > SWAPZ_MAX_PACKED_RECORDS ||\n"
)
MAPPING_FLAG_GUARD = (
    "\tif (mapping->flags != SWAPZ_MAP_VALID &&\n"
    "\t    mapping->flags != (SWAPZ_MAP_VALID | SWAPZ_MAP_COMPRESSED))\n"
    "\t\treturn -EIO;\n"
)


def exact_function(source: str, name: str) -> str:
    definitions = list(re.finditer(
        r"\bstatic\s+(?:bool|int)\s+" + re.escape(name) +
        r"\s*\([^;{}]*\)\s*\{", source, flags=re.DOTALL))
    if len(definitions) != 1:
        raise AssertionError(f"exactly one production definition required: {name}")
    beginning = definitions[0].start()
    depth = 0
    for position in range(definitions[0].end() - 1, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[beginning:position + 1]
    raise AssertionError(f"unterminated production function {name}")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_MAP_VALID 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define SWAPZ_MAX_COMPRESSED_BYTES (SWAPZ_BLOCK_BYTES -     sizeof(struct swapz_container_disk) - sizeof(struct swapz_record_disk) - 512U)
#define SWAPZ_CONTAINER_BASE_BYTES ((unsigned int)sizeof(struct swapz_container_disk))
#define ARRAY_SIZE(array) (sizeof(array) / sizeof((array)[0]))
#define le32_to_cpu(value) (value)
#define le16_to_cpu(value) (value)

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

struct swapz_write_batch_record {
    void *bio;
    u32 logical_page;
    u32 generation;
    u16 stored_length;
    u8 record_index;
    u8 flags;
    bool upper_completed;
};

struct swapz_write_batch_block {
    u8 record_count;
    bool compaction;
    struct swapz_write_batch_record records[SWAPZ_MAX_PACKED_RECORDS];
};

struct swapz_stream_buffer {
    void *data;
    struct swapz_write_batch_block *blocks;
    u32 block_count;
    u8 id;
};

struct swapz_staged_ref {
    u32 generation;
    u8 block_index;
    u8 record_index;
    u8 buffer_id;
    u8 valid;
};

struct swapz_context {
    bool failed;
    struct swapz_staged_ref staged_refs[1];
    u32 generations[1];
    struct swapz_stream_buffer stream_buffers[2];
    u32 max_batch_blocks;
    struct { u64 staged_read_hits; } stats;
};

static inline const struct swapz_record_disk *
swapz_container_record_const(const void *block, unsigned int index)
{
    return (const struct swapz_record_disk *)((const u8 *)block +
        SWAPZ_CONTAINER_BASE_BYTES + index * sizeof(struct swapz_record_disk));
}

static int decode_calls;

static int LZ4_decompress_safe(const char *input, char *destination,
                              int length, int capacity)
{
    ++decode_calls;
    if (length != 4 || capacity != SWAPZ_BLOCK_BYTES || input[0] != 'Q')
        return -1;
    memset(destination, 'Z', SWAPZ_BLOCK_BYTES);
    return SWAPZ_BLOCK_BYTES;
}
"""

SUFFIX = r"""
static int run_mapping_case(unsigned int scenario, bool old_count_mutant)
{
    struct swapz_mapping mapping = {
        .physical_block = 0, .stored_length = 4, .record_index = 0,
        .flags = SWAPZ_MAP_VALID | SWAPZ_MAP_COMPRESSED
    };
    u8 block_data[SWAPZ_BLOCK_BYTES] = {0};
    u8 destination[SWAPZ_BLOCK_BYTES];
    struct swapz_container_disk *container = (void *)block_data;
    struct swapz_record_disk *disk_record = (void *)(
        block_data + SWAPZ_CONTAINER_BASE_BYTES);
    int result;

    if (scenario >= 13) {
        mapping.flags = scenario == 13 ? SWAPZ_MAP_VALID | 4 :
                        SWAPZ_MAP_VALID;
        mapping.stored_length = scenario == 14 ? 4 : SWAPZ_BLOCK_BYTES;
        mapping.record_index = scenario == 16 ? 1 : 0;
    }
    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = scenario == 11 ? 65 : (scenario == 12 ? 0 : 1);
    disk_record->logical_page = 0;
    disk_record->offset = SWAPZ_BLOCK_BYTES - 4;
    disk_record->length = 4;
    memcpy(block_data + SWAPZ_BLOCK_BYTES - 4, "QQQQ", 4);
    memset(destination, 'X', sizeof(destination));
    decode_calls = 0;
    result = swapz_decode_loaded_mapping(0, &mapping, block_data, destination);

    if (old_count_mutant) {
        if (scenario == 11) {
            if (result || decode_calls != 1 || destination[0] != 'Z')
                return 70;
            puts("OLD_OVERSIZED_DISK_RECORD_COUNT_ACCEPTED");
            return 0;
        }
        if (scenario == 13) {
            if (result || decode_calls ||
                memcmp(destination, block_data, SWAPZ_BLOCK_BYTES))
                return 70;
            puts("OLD_UNKNOWN_MAPPING_FLAGS_ACCEPTED_AS_RAW");
            return 0;
        }
        return 75;
    }
    if (scenario == 10) {
        if (result || decode_calls != 1 || destination[0] != 'Z')
            return 71;
        return 0;
    }
    if (scenario == 15) {
        if (result || decode_calls ||
            memcmp(destination, block_data, SWAPZ_BLOCK_BYTES))
            return 73;
        return 0;
    }
    if (result != -EIO || decode_calls || destination[0] != 'X')
        return 72;
    return 0;
}

static int run_case(unsigned int scenario, bool old_flags_mutant)
{
    struct swapz_context context = {0};
    struct swapz_write_batch_block blocks[1] = {0};
    u8 block_data[SWAPZ_BLOCK_BYTES] = {0};
    u8 destination[SWAPZ_BLOCK_BYTES];
    struct swapz_container_disk *container = (void *)block_data;
    struct swapz_record_disk *disk_record;
    struct swapz_write_batch_record *record = &blocks[0].records[0];
    int result;

    context.generations[0] = 1;
    context.max_batch_blocks = 1;
    context.staged_refs[0] = (struct swapz_staged_ref) {
        .generation=1, .valid=1, .block_index=0, .record_index=0, .buffer_id=0
    };
    context.stream_buffers[0].data = block_data;
    context.stream_buffers[0].blocks = blocks;
    context.stream_buffers[0].block_count = 1;
    blocks[0].record_count = 1;
    record->logical_page = 0;
    record->generation = 1;
    record->record_index = 0;
    record->stored_length = 4;
    record->flags = SWAPZ_MAP_COMPRESSED;

    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = 1;
    disk_record = (void *)(block_data + SWAPZ_CONTAINER_BASE_BYTES);
    disk_record->logical_page = 0;
    disk_record->offset = SWAPZ_BLOCK_BYTES - 4;
    disk_record->length = 4;
    memcpy(block_data + SWAPZ_BLOCK_BYTES - 4, "QQQQ", 4);
    memset(destination, 'X', sizeof(destination));
    decode_calls = 0;

    switch (scenario) {
    case 0: break; /* Valid packed record. */
    case 1: /* Corrupt physical descriptor index 64 and disk count 65. */
        record->record_index = 64;
        container->record_count = 65;
        disk_record = (void *)(block_data + SWAPZ_CONTAINER_BASE_BYTES +
                               64 * sizeof(struct swapz_record_disk));
        disk_record->logical_page = 0;
        disk_record->offset = SWAPZ_BLOCK_BYTES - 4;
        disk_record->length = 4;
        break;
    case 2:
        /* A raw-shaped record with unknown flag bits used to read as raw. */
        record->flags = 4;
        record->stored_length = SWAPZ_BLOCK_BYTES;
        break;
    case 3: container->record_count = 2; break; /* Disk/memory count mismatch. */
    case 4: /* Valid raw page. */
        record->flags = 0;
        record->stored_length = SWAPZ_BLOCK_BYTES;
        memset(block_data, 'R', sizeof(block_data));
        break;
    case 5: /* Raw block with wrong in-memory count. */
        record->flags = 0;
        record->stored_length = SWAPZ_BLOCK_BYTES;
        blocks[0].record_count = 2;
        break;
    case 6: /* Raw record with wrong stored byte length. */
        record->flags = 0;
        record->stored_length = 4;
        break;
    case 7: /* In-memory record index 1 does not match staged slot 0. */
        record->record_index = 1;
        container->record_count = 2;
        disk_record = (void *)(block_data + SWAPZ_CONTAINER_BASE_BYTES +
                               sizeof(struct swapz_record_disk));
        disk_record->logical_page = 0;
        disk_record->offset = SWAPZ_BLOCK_BYTES - 4;
        disk_record->length = 4;
        break;
    case 8: context.staged_refs[0].valid = 0; break; /* Missing staged ref. */
    case 9: record->flags = 6; break; /* Compressed plus unknown flag. */
    case 17: context.failed = true; break; /* Unacknowledged, fail closed. */
    case 18:
        context.failed = true;
        record->upper_completed = true; /* Acknowledged staged readback. */
        break;
    default: return 80;
    }

    result = swapz_read_staged(&context, 0, destination);
    if (old_flags_mutant) {
        if (scenario != 2 || result || decode_calls ||
            memcmp(destination, block_data, SWAPZ_BLOCK_BYTES))
            return 81;
        puts("OLD_UNKNOWN_FLAGS_ACCEPTED_AS_RAW");
        return 0;
    }

    if (scenario == 0 || scenario == 4 || scenario == 18) {
        if (result || context.stats.staged_read_hits != 1 ||
            ((scenario == 0 || scenario == 18) &&
             (decode_calls != 1 || destination[0] != 'Z')) ||
            (scenario == 4 && (decode_calls || destination[0] != 'R')))
            return 82;
        return 0;
    }
    if (scenario == 8 || scenario == 17) {
        if (result != -ENOENT || context.stats.staged_read_hits || decode_calls)
            return 83;
        return 0;
    }
    if ((result != -EUCLEAN && result != -EIO) ||
        context.stats.staged_read_hits || decode_calls ||
        destination[0] != 'X')
        return 84;
    return 0;
}

int main(int argc, char **argv)
{
    char *end = NULL;
    unsigned long scenario;
    int result;

    if (argc != 3) return 85;
    scenario = strtoul(argv[1], &end, 10);
    if (end == argv[1] || *end || scenario > 18) return 86;
    if (scenario >= 10 && scenario <= 16)
        result = run_mapping_case((unsigned int)scenario, argv[2][0] == 'm');
    else
        result = run_case((unsigned int)scenario, argv[2][0] == 'm');
    if (!result) printf("STAGED_READ_CASE_%lu_OK\n", scenario);
    return result;
}
"""


class StagedReadMetadataContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        compiler = shutil.which("cc")
        if not compiler:
            raise AssertionError("mandatory C compiler unavailable")
        read_staged = exact_function(source, "swapz_read_staged")
        read_mapping = exact_function(source, "swapz_decode_loaded_mapping")
        helper = exact_function(source, "swapz_stream_record_current")
        if read_staged.count(FLAG_GUARD) != 1:
            raise AssertionError("production staged-read flag guard missing")
        if read_mapping.count(COUNT_GUARD) != 1:
            raise AssertionError("committed mapping count guard missing")
        if read_mapping.count(MAPPING_FLAG_GUARD) != 1:
            raise AssertionError("committed mapping flags guard missing")
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix="swapz-staged-read-exact-c-")
        directory = Path(cls.temporary_directory.name)

        def compile_case(filename: str, staged_body: str,
                         mapping_body: str) -> Path:
            path = directory / (filename + ".c")
            executable = directory / filename
            path.write_text(PREFIX + "\n" + helper + "\n" + staged_body +
                            "\n" + mapping_body + "\n" + SUFFIX,
                            encoding="utf-8")
            command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra",
                       "-Werror", "-o", str(executable), str(path)]
            result = subprocess.run(command, capture_output=True,
                                    text=True, check=False, timeout=15)
            if result.returncode:
                raise AssertionError("production C compilation failed: " + result.stderr)
            return executable

        cls.production = compile_case("production-staged-read", read_staged,
                                      read_mapping)
        mutant_staged = read_staged.replace(FLAG_GUARD, "", 1)
        mutant_mapping = read_mapping.replace(COUNT_GUARD, "", 1).replace(
            MAPPING_FLAG_GUARD, "", 1)
        cls.unknown_flags_mutant = compile_case(
            "unknown-flags-mutant", mutant_staged, mutant_mapping)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def execute(self, scenario: int, mutant: bool = False) -> None:
        executable = self.unknown_flags_mutant if mutant else self.production
        process = subprocess.run(
            [str(executable), str(scenario), "mutant" if mutant else "production"],
            capture_output=True, text=True, check=False, timeout=4)
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        self.assertIn(f"STAGED_READ_CASE_{scenario}_OK", process.stdout)
        if mutant:
            marker = ("OLD_OVERSIZED_DISK_RECORD_COUNT_ACCEPTED"
                      if scenario == 11 else
                      "OLD_UNKNOWN_MAPPING_FLAGS_ACCEPTED_AS_RAW"
                      if scenario == 13 else
                      "OLD_UNKNOWN_FLAGS_ACCEPTED_AS_RAW")
            self.assertIn(marker, process.stdout)

    def test_failed_target_allows_only_early_acknowledged_staged_readback(self):
        self.execute(17)
        self.execute(18)

    def test_valid_compressed_and_raw_staged_reads(self):
        for scenario in (0, 4, 8):
            with self.subTest(scenario=scenario):
                self.execute(scenario)

    def test_corrupt_index_count_flags_and_raw_record_denied(self):
        for scenario in (1, 2, 3, 5, 6, 7, 9):
            with self.subTest(scenario=scenario):
                self.execute(scenario)

    def test_unknown_flags_old_behavior_is_executable(self):
        self.execute(2, mutant=True)

    def test_loaded_mapping_record_count_is_bounded(self):
        for scenario in (10, 11, 12, 13, 14, 15, 16):
            with self.subTest(scenario=scenario):
                self.execute(scenario)

    def test_old_mapping_decoder_accepted_oversized_count(self):
        self.execute(11, mutant=True)

    def test_old_mapping_decoder_accepted_unknown_mapping_flags(self):
        self.execute(13, mutant=True)

    def test_source_flags_guard_is_required(self):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(exact_function(source, "swapz_read_staged").count(
            FLAG_GUARD), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
