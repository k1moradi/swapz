#!/usr/bin/env python3
"""Exact-production-C lower-write submission extent and ownership contract.

Uses a deterministic dm_io() in-memory stub; never opens backing storage,
loads a module, mounts swap, creates a DM/loop/NBD device or performs IO.
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
BOUNDS_GUARD = (
    "\tif (unlikely(buffer->block_count > context->max_batch_blocks ||\n"
    "\t\t     buffer->start_block >= context->physical_blocks ||\n"
    "\t\t     buffer->block_count >\n"
    "\t\t\t     context->physical_blocks - buffer->start_block))\n"
    "\t\treturn -EUCLEAN;\n"
)


def exact_function(source: str, name: str) -> str:
    expression = (r"\bstatic\s+(?:inline\s+)?(?:sector_t|int)\s+" +
                  re.escape(name) + r"\s*\([^;{}]*\)\s*\{")
    found = list(re.finditer(expression, source, flags=re.DOTALL))
    if len(found) != 1:
        raise AssertionError(f"exactly one production definition required: {name}")
    level = 0
    for cursor in range(found[0].end() - 1, len(source)):
        if source[cursor] == "{":
            level += 1
        elif source[cursor] == "}":
            level -= 1
            if level == 0:
                return source[found[0].start():cursor + 1]
    raise AssertionError(f"unterminated production definition: {name}")


PREFIX = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef uint8_t u8;
typedef uint32_t u32;
typedef uint64_t u64;
typedef u64 sector_t;

#define SWAPZ_BLOCK_BYTES 4096U
#define SWAPZ_BLOCK_SECTORS 8U
#define SWAPZ_BUFFER_FILL 1U
#define SWAPZ_BUFFER_INFLIGHT 2U
#define REQ_OP_WRITE 1U
#define REQ_SWAP 8U
#define DM_IO_VMA 4
#define IOPRIO_DEFAULT 0
#define SWAPZ_ASYNC_WATCHDOG_MS 30000U
#define msecs_to_jiffies(x) (x)
#define WARN_ON_ONCE(x) (x)
#define unlikely(x) (x)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,y) ((x)=(y))

struct dm_io_region {
    void *bdev;
    sector_t sector;
    sector_t count;
};
struct dm_io_request {
    unsigned int bi_opf;
    struct {
        int type;
        unsigned int offset;
        struct { void *vma; } ptr;
    } mem;
    struct {
        void (*fn)(unsigned long, void *);
        void *context;
    } notify;
    void *client;
};
struct completion { int signals, reinits; };
struct delayed_work { int armed; };
struct work_struct { int queued; };
struct stub_queue { int queues; };
struct stub_atomic { int value; };
struct stub_wait { int wakes; };
struct dm_dev { void *bdev; };
struct swapz_stats { u64 stream_submit_bytes; };
struct swapz_context;
struct swapz_stream_buffer {
    struct swapz_context *context;
    struct completion completion;
    struct delayed_work watchdog_work;
    u32 start_block, block_count;
    unsigned int write_flags;
    void *data;
    int io_error;
    u8 state, id;
    bool watchdog_expired, watchdog_reported;
};
struct swapz_context {
    struct dm_dev *backing;
    void *io_client;
    struct stub_queue *workqueue, *watchdog_workqueue;
    struct stub_atomic async_callbacks;
    struct stub_wait async_callback_wait;
    struct work_struct io_work;
    struct swapz_stats stats;
    u32 physical_blocks, max_batch_blocks;
    int inflight_buffer_id;
    bool accepting_io;
};

static unsigned int mock_dm_io_calls, mock_armed, mock_queued;
static int mock_dm_io_error;
static struct dm_io_region submitted_region;
static struct dm_io_request submitted_request;

static void swapz_stream_io_complete(unsigned long errors, void *data)
{
    (void)errors;
    (void)data;
}
static void reinit_completion(struct completion *c)
{
    c->signals=0;
    c->reinits++;
}
static void complete(struct completion *c) { c->signals++; }
static void atomic_inc(struct stub_atomic *a) { a->value++; }
static int atomic_dec_and_test(struct stub_atomic *a)
{
    return --a->value == 0;
}
static void wake_up_all(struct stub_wait *w) { w->wakes++; }
static int mod_delayed_work(struct stub_queue *q, struct delayed_work *w,
                            unsigned long delay)
{
    (void)q;
    (void)delay;
    w->armed++;
    mock_armed++;
    return 1;
}
static void queue_work(struct stub_queue *q, struct work_struct *w)
{
    (void)w;
    q->queues++;
    mock_queued++;
}
static int dm_io(struct dm_io_request *req, unsigned int nr_regions,
                 struct dm_io_region *region, unsigned long *error_bits,
                 int ioprio)
{
    if (nr_regions != 1 || error_bits != NULL || ioprio != IOPRIO_DEFAULT)
        return -EINVAL;
    mock_dm_io_calls++;
    submitted_region = *region;
    submitted_request = *req;
    return mock_dm_io_error;
}
"""

SUFFIX = r"""
static int run_case(unsigned int case_id, bool mutant)
{
    struct swapz_context context = {0};
    struct swapz_stream_buffer buffer = {0};
    struct stub_queue worker_queue = {0}, watchdog_queue = {0};
    struct dm_dev backing = {0};
    u8 data[4 * SWAPZ_BLOCK_BYTES] = {0};
    int dummy_device = 1, dummy_client = 2;
    int result;
    int initial_inflight;

    context.physical_blocks = 16;
    context.max_batch_blocks = 4;
    context.inflight_buffer_id = -1;
    context.accepting_io = true;
    context.workqueue = &worker_queue;
    context.watchdog_workqueue = &watchdog_queue;
    context.backing = &backing;
    context.io_client = &dummy_client;
    backing.bdev = &dummy_device;
    buffer.context = &context;
    buffer.id = 0;
    buffer.state = SWAPZ_BUFFER_FILL;
    buffer.start_block = 4;
    buffer.block_count = 1;
    buffer.data = data;
    buffer.write_flags = 16;
    mock_dm_io_calls = mock_armed = mock_queued = 0;
    mock_dm_io_error = 0;
    memset(&submitted_region, 0, sizeof(submitted_region));
    memset(&submitted_request, 0, sizeof(submitted_request));

    switch (case_id) {
    case 0: buffer.block_count = 0; break;
    case 1: buffer.start_block = 0; break;
    case 2: buffer.start_block = 15; break;
    case 3: buffer.start_block = 12; buffer.block_count = 4; break;
    case 4: buffer.start_block = 15; buffer.block_count = 2; break;
    case 5: buffer.start_block = 16; break;
    case 6: buffer.start_block = UINT32_MAX; break;
    case 7: buffer.block_count = 5; break;
    case 8: mock_dm_io_error = -EIO; break;
    case 9: buffer.state = 0; break;
    case 10: context.inflight_buffer_id = 1; break;
    case 11: buffer.block_count = 4; break;
    case 12: context.physical_blocks = 0; break;
    default: return 60;
    }

    initial_inflight = context.inflight_buffer_id;
    result = swapz_submit_stream_buffer(&context, &buffer);
    if (mutant) {
        if (case_id < 4 || case_id > 7 || result ||
            mock_dm_io_calls != 1 ||
            submitted_region.sector != (sector_t)buffer.start_block *
                                       SWAPZ_BLOCK_SECTORS ||
            submitted_region.count != (sector_t)buffer.block_count *
                                       SWAPZ_BLOCK_SECTORS ||
            context.inflight_buffer_id != 0 ||
            buffer.state != SWAPZ_BUFFER_INFLIGHT)
            return 61;
        puts("OLD_SUBMIT_ISSUED_OUT_OF_EXTENT_LOWER_WRITE");
        return 0;
    }

    if (case_id == 0) {
        if (result || mock_dm_io_calls || mock_armed ||
            context.inflight_buffer_id != -1 || context.async_callbacks.value)
            return 62;
        return 0;
    }

    if (case_id == 4 || case_id == 5 || case_id == 6 ||
        case_id == 7 || case_id == 9 || case_id == 10 || case_id == 12) {
        if (result != -EUCLEAN || mock_dm_io_calls || mock_armed ||
            context.async_callbacks.value ||
            context.inflight_buffer_id != initial_inflight ||
            buffer.completion.reinits || buffer.completion.signals ||
            context.stats.stream_submit_bytes)
            return 63;
        return 0;
    }

    if (result || mock_dm_io_calls != 1 || mock_armed != 1 ||
        context.inflight_buffer_id != 0 ||
        buffer.state != SWAPZ_BUFFER_INFLIGHT ||
        submitted_region.bdev != backing.bdev ||
        submitted_region.sector != (sector_t)buffer.start_block *
                                   SWAPZ_BLOCK_SECTORS ||
        submitted_region.count != (sector_t)buffer.block_count *
                                  SWAPZ_BLOCK_SECTORS ||
        submitted_request.notify.fn != swapz_stream_io_complete ||
        submitted_request.notify.context != &buffer ||
        submitted_request.mem.ptr.vma != data ||
        submitted_request.client != &dummy_client ||
        submitted_request.mem.type != DM_IO_VMA ||
        submitted_request.bi_opf != (REQ_OP_WRITE | REQ_SWAP | buffer.write_flags) ||
        buffer.completion.reinits != 1)
        return 64;

    if (case_id == 8) {
        if (context.async_callbacks.value || buffer.completion.signals != 1 ||
            context.async_callback_wait.wakes != 1 ||
            mock_queued != 1 || buffer.io_error != -EIO ||
            context.stats.stream_submit_bytes)
            return 65;
    } else if (context.async_callbacks.value != 1 ||
               buffer.completion.signals ||
               context.stats.stream_submit_bytes !=
                   (u64)buffer.block_count * SWAPZ_BLOCK_BYTES ||
               mock_queued)
        return 66;

    return 0;
}

int main(int argc, char **argv)
{
    unsigned long case_id;
    char *end = NULL;
    int result;

    if (argc != 3)
        return 70;
    case_id = strtoul(argv[1], &end, 10);
    if (end == argv[1] || *end || case_id > 12)
        return 71;
    result = run_case((unsigned int)case_id, argv[2][0] == 'm');
    if (!result)
        printf("LOWER_SUBMIT_BOUNDS_CASE_%lu_OK\n", case_id);
    return result;
}
"""


class StreamSubmitBoundsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise AssertionError("mandatory C compiler unavailable")

        physical_sector = exact_function(source, "swapz_physical_sector")
        submit = exact_function(source, "swapz_submit_stream_buffer")
        if submit.count(BOUNDS_GUARD) != 1:
            raise AssertionError("production stream lower-extent guard missing")
        if submit.index(BOUNDS_GUARD) > submit.index("region.bdev"):
            raise AssertionError("physical extent must be checked before request setup")

        cls.tmp = tempfile.TemporaryDirectory(
            prefix="swapz-submit-extent-exact-c-")
        root = Path(cls.tmp.name)

        def compile_binary(label: str, body: str) -> Path:
            file = root / (label + ".c")
            output = root / label
            file.write_text(PREFIX + "\n" + physical_sector + "\n" +
                            body + "\n" + SUFFIX, encoding="utf-8")
            result = subprocess.run(
                [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                 "-o", str(output), str(file)],
                capture_output=True, text=True, timeout=15, check=False)
            if result.returncode:
                raise AssertionError(f"{label} compile failed: {result.stderr}")
            return output

        cls.production = compile_binary("production-submit", submit)
        cls.old_behavior = compile_binary(
            "removed-physical-extent-guard", submit.replace(BOUNDS_GUARD, "", 1))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_case(self, scenario: int, mutant: bool = False) -> None:
        process = subprocess.run(
            [str(self.old_behavior if mutant else self.production),
             str(scenario), "mutant" if mutant else "production"],
            capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(process.returncode, 0,
                         process.stdout + process.stderr)
        self.assertIn(f"LOWER_SUBMIT_BOUNDS_CASE_{scenario}_OK",
                      process.stdout)
        if mutant:
            self.assertIn("OLD_SUBMIT_ISSUED_OUT_OF_EXTENT_LOWER_WRITE",
                          process.stdout)

    def test_valid_submit_empty_buffer_and_synchronous_rejection(self):
        for scenario in (0, 1, 2, 3, 8, 11):
            with self.subTest(scenario=scenario):
                self.run_case(scenario)

    def test_invalid_physical_batch_stops_before_ownership_transfer(self):
        for scenario in (4, 5, 6, 7, 9, 10, 12):
            with self.subTest(scenario=scenario):
                self.run_case(scenario)

    def test_unbounded_old_submit_emits_invalid_lower_region(self):
        for scenario in (4, 5, 6, 7):
            with self.subTest(scenario=scenario):
                self.run_case(scenario, mutant=True)

    def test_guard_precedes_io_and_callback_bookkeeping(self):
        submit = exact_function(SOURCE.read_text(encoding="utf-8"),
                                "swapz_submit_stream_buffer")
        self.assertEqual(submit.count(BOUNDS_GUARD), 1)
        self.assertLess(submit.index(BOUNDS_GUARD),
                        submit.index("context->inflight_buffer_id = buffer->id"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
