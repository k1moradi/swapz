#!/usr/bin/env python3
"""Rootless exact-production-C compressed-container compaction contract.

Compile the production preflight and repacker/compactor functions with bounded,
ordinary-memory stand-ins. Exercise mutated resident metadata, including a
late invalid container whose rejection must leave earlier staged data intact.
No kernel, mapper, loop, NBD, device, or privileged operation is performed.
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

FUNCTIONS = (
    "swapz_stream_record_current",
    "swapz_repack_can_fit",
    "swapz_update_repacked_ref",
    "swapz_emit_repack_container",
    "swapz_compact_fill_buffer",
    "swapz_complete_buffer_bios",
)
VALIDATOR = "swapz_validate_compact_fill_buffer"
VALIDATOR_CALL = (
    "\terror = swapz_validate_compact_fill_buffer(context, buffer);\n"
    "\tif (error)\n"
    "\t\tgoto fail;\n"
)


def exact_function(source: str, name: str) -> str:
    pattern = (r"\bstatic\s+(?:inline\s+)?(?:int|void|bool)\s+" +
               re.escape(name) + r"\s*\([^;{}]*\)\s*\{")
    matches = list(re.finditer(pattern, source, flags=re.DOTALL))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one production definition: {name}")
    depth = 0
    for position in range(matches[0].end() - 1, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                return source[matches[0].start():position + 1]
    raise AssertionError(f"unclosed function: {name}")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <stddef.h>

typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_MAX_PACKED_RECORDS 64U
#define SWAPZ_CONTAINER_MAGIC 0x5a575053U
#define SWAPZ_CONTAINER_VERSION 1U
#define SWAPZ_MAP_COMPRESSED 2U
#define SWAPZ_MIN_COMPRESS_SAVING 512U
#define SWAPZ_CONTAINER_BASE_BYTES ((unsigned int)sizeof(struct swapz_container_disk))
#define SWAPZ_MAX_COMPRESSED_BYTES (SWAPZ_BLOCK_BYTES - \
        SWAPZ_CONTAINER_BASE_BYTES - sizeof(struct swapz_record_disk) - \
        SWAPZ_MIN_COMPRESS_SAVING)
#define cpu_to_le16(value) (value)
#define cpu_to_le32(value) (value)
#define le16_to_cpu(value) (value)
#define le32_to_cpu(value) (value)
#define WARN_ON_ONCE(condition) (condition)
#define min(left, right) ((left) < (right) ? (left) : (right))
#define min_t(type, left, right) ((type)(left) < (type)(right) ? (type)(left) : (type)(right))
#define likely(condition) (condition)
#define unlikely(condition) (condition)

struct list_head { struct list_head *next, *prev; };
#define INIT_LIST_HEAD(item) do { (item)->next=(item); (item)->prev=(item); } while(0)
#define list_empty(head) ((head)->next==(head))
#define list_first_entry(head,type,member) \
    ((type *)((char *)(head)->next - offsetof(type,member)))
static void list_add_tail(struct list_head *item, struct list_head *head) {
    item->prev=head->prev;item->next=head;
    head->prev->next=item;head->prev=item;
}
static void list_del_init(struct list_head *item) {
    item->prev->next=item->next;item->next->prev=item->prev;
    INIT_LIST_HEAD(item);
}
struct bio;
struct swapz_per_bio { struct list_head list; struct bio *bio; };
struct bio { struct swapz_per_bio entry; int completions; int last_error; };
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
    struct bio *bio;
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
struct swapz_staged_ref {
    u32 generation;
    u8 block_index;
    u8 record_index;
    u8 buffer_id;
    u8 valid;
};
struct swapz_stream_buffer {
    struct list_head owned_bios;
    void *data;
    struct swapz_write_batch_block *blocks;
    u32 block_count;
    u8 id;
};
struct swapz_context {
    u32 logical_pages;
    u32 generations[SWAPZ_MAX_PACKED_RECORDS];
    struct swapz_staged_ref staged_refs[SWAPZ_MAX_PACKED_RECORDS];
    u32 max_batch_blocks;
    u32 segment_write_block;
    bool failed;
    /* Production scratch fields are void pointers, not byte arrays. */
    void *repack_buffer;
    u8 repack_storage[SWAPZ_BLOCK_BYTES];
    struct swapz_write_batch_block repack_block;
    struct swapz_write_batch_block compact_source_block;
    void *io_buffer;
    u8 io_storage[SWAPZ_BLOCK_BYTES];
    void *compressed_buffer;
    u8 compressed_storage[SWAPZ_BLOCK_BYTES];
    struct {
        u64 staged_cancellations;
        u64 staged_cancelled_blocks;
        u64 io_errors;
    } stats;
};
static inline struct swapz_record_disk *
swapz_container_record(void *buffer, unsigned int index)
{
    return (struct swapz_record_disk *)((u8 *)buffer +
        SWAPZ_CONTAINER_BASE_BYTES + index * sizeof(struct swapz_record_disk));
}
static inline const struct swapz_record_disk *
swapz_container_record_const(const void *buffer, unsigned int index)
{
    return (const struct swapz_record_disk *)((const u8 *)buffer +
        SWAPZ_CONTAINER_BASE_BYTES + index * sizeof(struct swapz_record_disk));
}
static void swapz_set_failed(struct swapz_context *context, int error)
{
    (void)error;
    context->failed = true;
    context->stats.io_errors++;
}
static void swapz_complete_bio(struct bio *bio, int error)
{
    list_del_init(&bio->entry.list);
    bio->completions++;
    bio->last_error = error;
}
static void swapz_clear_staged_ref(struct swapz_context *context,
                                   u32 logical_page, u32 generation,
                                   u8 buffer_id, u8 block_index,
                                   u8 record_index)
{
    struct swapz_staged_ref *ref = &context->staged_refs[logical_page];
    if (ref->valid && ref->generation == generation &&
        ref->buffer_id == buffer_id && ref->block_index == block_index &&
        ref->record_index == record_index)
        memset(ref, 0, sizeof(*ref));
}
"""

SUFFIX = r"""
static void prepare_block(struct swapz_stream_buffer *buffer,
                          unsigned int block_index, u32 logical_page)
{
    u8 *block_data = (u8 *)buffer->data + block_index * SWAPZ_BLOCK_BYTES;
    struct swapz_container_disk *container = (void *)block_data;
    struct swapz_record_disk *disk_record = swapz_container_record(block_data, 0);
    struct swapz_write_batch_record *record = &buffer->blocks[block_index].records[0];

    buffer->blocks[block_index].record_count = 1;
    record->logical_page = logical_page;
    record->generation = 1;
    record->record_index = 0;
    record->stored_length = 4;
    record->flags = SWAPZ_MAP_COMPRESSED;

    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = 1;
    disk_record->logical_page = logical_page;
    disk_record->offset = SWAPZ_BLOCK_BYTES - 4;
    disk_record->length = 4;
    memcpy(block_data + SWAPZ_BLOCK_BYTES - 4, "ABCD", 4);
}

static void prepare_overlapping_block(struct swapz_stream_buffer *buffer,
                                      bool partial)
{
    u8 *block_data = buffer->data;
    struct swapz_container_disk *container = (void *)block_data;
    unsigned int record_index;
    unsigned int payload_start = SWAPZ_CONTAINER_BASE_BYTES +
        SWAPZ_MAX_PACKED_RECORDS * sizeof(struct swapz_record_disk);
    unsigned int length = SWAPZ_MAX_COMPRESSED_BYTES -
        (partial ? SWAPZ_MAX_PACKED_RECORDS : 0);

    memset(block_data, 0, SWAPZ_BLOCK_BYTES);
    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = SWAPZ_MAX_PACKED_RECORDS;
    memset(block_data + payload_start, 0xa5, SWAPZ_BLOCK_BYTES - payload_start);
    for (record_index = 0; record_index < SWAPZ_MAX_PACKED_RECORDS;
         ++record_index) {
        struct swapz_record_disk *disk_record =
            swapz_container_record(block_data, record_index);
        struct swapz_write_batch_record *record =
            &buffer->blocks[0].records[record_index];

        record->logical_page = record_index;
        record->generation = 1;
        record->record_index = record_index;
        record->stored_length = length;
        record->flags = SWAPZ_MAP_COMPRESSED;
        disk_record->logical_page = record_index;
        disk_record->offset = payload_start + (partial ? record_index : 0);
        disk_record->length = length;
    }
    buffer->blocks[0].record_count = SWAPZ_MAX_PACKED_RECORDS;
}

static void prepare_adjacent_block(struct swapz_stream_buffer *buffer)
{
    u8 *block_data = buffer->data;
    struct swapz_container_disk *container = (void *)block_data;
    unsigned int record_index;

    memset(block_data, 0, SWAPZ_BLOCK_BYTES);
    container->magic = SWAPZ_CONTAINER_MAGIC;
    container->version = SWAPZ_CONTAINER_VERSION;
    container->record_count = 2;
    buffer->blocks[0].record_count = 2;
    for (record_index = 0; record_index < 2; ++record_index) {
        struct swapz_record_disk *disk_record =
            swapz_container_record(block_data, record_index);
        struct swapz_write_batch_record *record =
            &buffer->blocks[0].records[record_index];
        u16 offset = SWAPZ_BLOCK_BYTES - (record_index + 1) * 4;

        record->logical_page = record_index;
        record->generation = 1;
        record->record_index = record_index;
        record->stored_length = 4;
        record->flags = SWAPZ_MAP_COMPRESSED;
        disk_record->logical_page = record_index;
        disk_record->offset = offset;
        disk_record->length = 4;
        memset(block_data + offset, 'A' + record_index, 4);
    }
}

static int run_case(unsigned int scenario, bool mutant)
{
    struct swapz_context context = {0};
    struct bio pending_bio = {0};
    struct swapz_stream_buffer buffer = {0};
    struct swapz_write_batch_block blocks[SWAPZ_MAX_PACKED_RECORDS] = {0};
    struct swapz_write_batch_block original_blocks[SWAPZ_MAX_PACKED_RECORDS];
    u8 data[SWAPZ_MAX_PACKED_RECORDS * SWAPZ_BLOCK_BYTES] = {0};
    u8 original_data[sizeof(data)];
    struct swapz_staged_ref original_refs[SWAPZ_MAX_PACKED_RECORDS];
    struct swapz_container_disk *container;
    struct swapz_record_disk *disk_record;
    struct swapz_write_batch_record *record;
    unsigned int corrupt_block = scenario == 11 ? 1 : 0;
    unsigned int record_index;

    context.repack_buffer = context.repack_storage;
    context.io_buffer = context.io_storage;
    context.compressed_buffer = context.compressed_storage;
    context.logical_pages = (scenario == 19 || scenario == 20) ?
        SWAPZ_MAX_PACKED_RECORDS : 4;
    context.generations[0] = 1;
    context.generations[1] = 1;
    context.max_batch_blocks = (scenario == 19 || scenario == 20) ?
        SWAPZ_MAX_PACKED_RECORDS : 2;
    context.segment_write_block = (scenario == 19 || scenario == 20) ? 1 : 2;
    buffer.data = data;
    buffer.blocks = blocks;
    INIT_LIST_HEAD(&buffer.owned_bios);
    buffer.block_count = scenario == 18 ? 3 : (scenario == 11 ? 2 : 1);
    prepare_block(&buffer, 0, 0);
    if (buffer.block_count >= 2)
        prepare_block(&buffer, 1, 1);

    if (scenario == 19 || scenario == 20) {
        prepare_overlapping_block(&buffer, scenario == 20);
        for (record_index = 0; record_index < SWAPZ_MAX_PACKED_RECORDS;
             ++record_index) {
            context.generations[record_index] = 1;
            context.staged_refs[record_index] = (struct swapz_staged_ref){
                .generation=1, .buffer_id=0, .block_index=0,
                .record_index=record_index, .valid=1};
        }
    } else if (scenario == 21 || scenario == 22) {
        prepare_adjacent_block(&buffer);
        if (scenario == 22) {
            /* Reversed descriptor extents are non-overlapping but never
             * emitted by the append-from-end packer or repacker. */
            struct swapz_record_disk *first =
                swapz_container_record(data, 0);
            struct swapz_record_disk *second =
                swapz_container_record(data, 1);
            u16 previous_offset = first->offset;
            first->offset = second->offset;
            second->offset = previous_offset;
        }
        context.staged_refs[0] = (struct swapz_staged_ref){
            .generation=1, .buffer_id=0, .block_index=0,
            .record_index=0, .valid=1};
        context.staged_refs[1] = (struct swapz_staged_ref){
            .generation=1, .buffer_id=0, .block_index=0,
            .record_index=1, .valid=1};
    }

    if (scenario != 19 && scenario != 20 && scenario != 21 && scenario != 22) {
        context.staged_refs[0] = (struct swapz_staged_ref){
            .generation=1, .buffer_id=0, .block_index=0,
            .record_index=0, .valid=1};
        context.staged_refs[1] = (struct swapz_staged_ref){
            .generation=1, .buffer_id=0, .block_index=1, .record_index=0,
            .valid=buffer.block_count >= 2};
    }

    container = (void *)(data + corrupt_block * SWAPZ_BLOCK_BYTES);
    disk_record = swapz_container_record(container, 0);
    record = &blocks[corrupt_block].records[0];

    switch (scenario) {
    case 0: break; /* Valid compressed record. */
    case 1: container->version = 2; break;
    case 2: container->record_count = 2; break;
    case 3: disk_record->offset = SWAPZ_CONTAINER_BASE_BYTES; break;
    case 4: disk_record->length = record->stored_length = 0; break;
    case 5: disk_record->length = 3; break;
    case 6: disk_record->offset = SWAPZ_BLOCK_BYTES - 2; break;
    case 7: blocks[corrupt_block].record_count = 65; break;
    case 8: record->record_index = 2; break;
    case 9: record->flags = 0; break;
    case 10: record->logical_page = 4; break;
    case 11: container->version = 2; break; /* Later malformed block. */
    case 12: disk_record->length = record->stored_length = 3600; break;
    case 13: /* Valid raw block. */
        record->flags = 0;
        record->stored_length = SWAPZ_BLOCK_BYTES;
        memset(data, 'Q', SWAPZ_BLOCK_BYTES);
        break;
    case 14:
        record->flags = 0;
        record->stored_length = SWAPZ_BLOCK_BYTES;
        blocks[0].record_count = 2;
        break;
    case 15: blocks[0].record_count = 0; break;
    case 16: container->record_count = 65; break;
    case 17: record->flags |= 4; break;
    case 18: break; /* Resident block count exceeds allocated capacity. */
    case 19: break; /* 64 compressed records alias the same payload extent. */
    case 20: break; /* 64 compressed extents overlap pairwise. */
    case 21: break; /* Adjacent payload ranges remain valid. */
    case 22: break; /* Reversed, non-overlapping extents are noncanonical. */
    default: return 60;
    }

    /* Exercise failure fanout with one incomplete BIO on adversarial records. */
    if (scenario == 7 || scenario == 10) {
        record->bio = &pending_bio;
        pending_bio.entry.bio = &pending_bio;
        INIT_LIST_HEAD(&pending_bio.entry.list);
        list_add_tail(&pending_bio.entry.list, &buffer.owned_bios);
    }

    memcpy(original_data, data, sizeof(data));
    memcpy(original_blocks, blocks, sizeof(blocks));
    memcpy(original_refs, context.staged_refs, sizeof(original_refs));
    swapz_compact_fill_buffer(&context, &buffer);

    if (mutant) {
        if (scenario == 1) {
            /* Demonstrate the removed preflight silently repacks bad version 2. */
            if (context.failed ||
                ((struct swapz_container_disk *)data)->version != 1)
                return 70;
            puts("OLD_VERSION_REPACKING_COUNTEREXAMPLE");
            return 0;
        }
        if (scenario == 19 || scenario == 20) {
            /* Overlap duplicates one payload into 64 unreserved output blocks. */
            if (context.failed ||
                buffer.block_count != SWAPZ_MAX_PACKED_RECORDS ||
                context.segment_write_block != 1 ||
                !memcmp(data, original_data, sizeof(data)) ||
                context.staged_refs[63].block_index != 63 ||
                context.staged_refs[63].record_index != 0)
                return 70;
            puts("OLD_OVERLAP_EXPANSION_COUNTEREXAMPLE");
            return 0;
        }
        return 71;
    }

    if (scenario == 0 || scenario == 13 || scenario == 21) {
        if (context.failed || buffer.block_count != 1 ||
            context.staged_refs[0].valid != 1)
            return 71;
        if (scenario == 0 && (memcmp(data + SWAPZ_BLOCK_BYTES - 4, "ABCD", 4) ||
            ((struct swapz_container_disk *)data)->version != 1))
            return 72;
        if (scenario == 13 && data[0] != 'Q')
            return 73;
        if (scenario == 21 &&
            (blocks[0].record_count != 2 ||
             data[SWAPZ_BLOCK_BYTES - 4] != 'A' ||
             data[SWAPZ_BLOCK_BYTES - 8] != 'B' ||
             context.staged_refs[1].record_index != 1))
            return 74;
        return 0;
    }

    if (!context.failed || context.stats.io_errors != 1 ||
        buffer.block_count != (scenario == 18 ? 3U : (scenario == 11 ? 2U : 1U)) ||
        memcmp(data, original_data, sizeof(data)) ||
        memcmp(blocks, original_blocks, sizeof(blocks)) ||
        memcmp(context.staged_refs, original_refs, sizeof(original_refs)))
        return 74;
    if (scenario == 7 || scenario == 10) {
        swapz_complete_buffer_bios(&context, &buffer, -EIO);
        if (pending_bio.completions != 1 || pending_bio.last_error != -EIO ||
            record->bio != NULL || !context.failed)
            return 75;
    }
    return 0;
}

int main(int argc, char **argv)
{
    char *end = NULL;
    unsigned long scenario;
    int error;

    if (argc != 3)
        return 80;
    scenario = strtoul(argv[1], &end, 10);
    if (!end || *end || scenario > 22)
        return 81;
    error = run_case((unsigned int)scenario, argv[2][0] == 'm');
    if (!error)
        printf("COMPACTION_CASE_%lu_OK\n", scenario);
    return error;
}
"""


class CompactionContainerContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = KERNEL.read_text(encoding="utf-8")
        compiler = shutil.which("cc")
        if not compiler:
            raise AssertionError("mandatory C compiler unavailable")
        cls.temporary_directory = tempfile.TemporaryDirectory(
            prefix="swapz-compaction-container-")
        directory = Path(cls.temporary_directory.name)
        compactor = exact_function(cls.source, "swapz_compact_fill_buffer")
        preflight = exact_function(cls.source, VALIDATOR)
        if compactor.count(VALIDATOR_CALL) != 1:
            raise AssertionError("compactor must call complete preflight exactly once")
        functions = [exact_function(cls.source, name) for name in FUNCTIONS]
        functions.insert(FUNCTIONS.index("swapz_compact_fill_buffer"), preflight)

        def compile_contract(name: str, bodies: list[str]) -> Path:
            path = directory / (name + ".c")
            binary = directory / name
            path.write_text(PREFIX + "\n" + "\n\n".join(bodies) +
                            "\n" + SUFFIX, encoding="utf-8")
            result = subprocess.run(
                [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-o", str(binary), str(path)],
                capture_output=True, text=True, check=False, timeout=15)
            if result.returncode:
                raise AssertionError(f"{name} compile failed:\n{result.stderr}")
            return binary

        cls.binary = compile_contract("production-compactor", functions)
        broken = compactor.replace(VALIDATOR_CALL, "", 1)
        mutant_functions = [
            exact_function(cls.source, name)
            if name != "swapz_compact_fill_buffer" else broken
            for name in FUNCTIONS
        ]
        cls.mutant_binary = compile_contract("no-preflight-mutant", mutant_functions)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def run_contract(self, scenario: int, mutant: bool = False) -> None:
        binary = self.mutant_binary if mutant else self.binary
        result = subprocess.run([str(binary), str(scenario),
                                 "mutant" if mutant else "production"],
                                capture_output=True, text=True,
                                check=False, timeout=4)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn(f"COMPACTION_CASE_{scenario}_OK", result.stdout)
        if mutant:
            marker = ("OLD_OVERLAP_EXPANSION_COUNTEREXAMPLE"
                      if scenario in (19, 20)
                      else "OLD_VERSION_REPACKING_COUNTEREXAMPLE")
            self.assertIn(marker, result.stdout)

    def test_valid_compressed_and_raw_records(self):
        for scenario in (0, 13):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_corrupted_metadata_rejected_without_partial_repack(self):
        for scenario in (*range(1, 13), 14, 15, 16, 17, 18, 19, 20, 22):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario)

    def test_unchecked_production_compactor_accepts_corrupt_version(self):
        self.run_contract(1, mutant=True)

    def test_unchecked_compactor_expands_overlapping_payloads(self):
        for scenario in (19, 20):
            with self.subTest(scenario=scenario):
                self.run_contract(scenario, mutant=True)

    def test_adjacent_nonoverlapping_payloads_remain_valid(self):
        self.run_contract(21)

    def test_missing_preflight_call_is_rejected(self):
        compactor = exact_function(self.source, "swapz_compact_fill_buffer")
        self.assertEqual(compactor.count(VALIDATOR_CALL), 1)
        broken = compactor.replace(VALIDATOR_CALL, "", 1)
        self.assertNotIn("swapz_validate_compact_fill_buffer(context, buffer)", broken)

    def test_preflight_contains_no_dynamic_allocations_or_lower_io(self):
        preflight = exact_function(self.source, VALIDATOR)
        for forbidden in ("kmalloc(", "__get_free_page(", "dm_io(", "LZ4_",
                          "swapz_install_mapping(", "swapz_set_staged_ref("):
            self.assertNotIn(forbidden, preflight)


if __name__ == "__main__":
    unittest.main(verbosity=2)
