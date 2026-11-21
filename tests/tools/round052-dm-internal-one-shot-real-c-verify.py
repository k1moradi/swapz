#!/usr/bin/env python3
"""Source-extract and execute actual guarded normal-BIO ticket C, not a toy."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round052-dm-internal-one-shot-host.c"
GUARD = "SWAPZ_ROUND052_DM_INTERNAL_ONE_SHOT_TEST"
DECL_BEGIN = "/* ROUND052_DM_INTERNAL_TICKET_DECL_START */"
DECL_END = "/* ROUND052_DM_INTERNAL_TICKET_DECL_END */"
HELPER_BEGIN = "/* ROUND052_DM_INTERNAL_TICKET_HELPER_START */"
HELPER_END = "/* ROUND052_DM_INTERNAL_TICKET_HELPER_END */"
MAP_BEGIN = "/* ROUND052_DM_INTERNAL_MAP_ACCEPTED_START */"
MAP_END = "/* ROUND052_DM_INTERNAL_MAP_ACCEPTED_END */"
PASS_MARKER = "ROUND052_REAL_PRODUCT_INTERNAL_TICKET_144_C_CASES_PASS"
MUTATIONS = (
    ("if (ticket->phase != SWAPZ_ROUND052_NOT_ACCEPTED)", "if (false)"),
    ("!(upper_bio->bi_opf & REQ_SWAP)", "false"),
    ("upper_bio->bi_iter.bi_size != SWAPZ_BLOCK_BYTES",
     "upper_bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES"),
    ("if (target->private != ctx || ctx->target != target ||",
     "if (false || false ||"),
    ("target_relative_sector % SWAPZ_SECTORS", "false"),
    ("if (lower_error < 0) {", "if (false) {"),
    ("if (lower_error || !lower_durable)",
     "if (lower_error && !lower_durable)"),
    ("ticket->phase = SWAPZ_ROUND052_LOWER_DONE;",
     "ticket->phase = SWAPZ_ROUND052_ACCEPTED;"),
    ("ticket->map_publications++;", "ticket->map_publications += 0U;"),
    ("ticket->upper_ack_attempts++;", "ticket->upper_ack_attempts += 0U;"),
    ("ticket->phase = SWAPZ_ROUND052_COMPLETED;",
     "ticket->phase = SWAPZ_ROUND052_PUBLISHED;"),
    ("ticket->map_generation != map_generation ||", "false ||"),
    ("ticket->gc_epoch != gc_epoch ||", "false ||"),
)


def extract_unique(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round052 source marker absent or not unique")
    start_index = source.index(begin) + len(begin)
    end_index = source.index(end)
    if start_index >= end_index:
        raise AssertionError("Round052 C marker order invalid")
    return source[start_index:end_index]


def replace_unique(source: str, old: str, new: str) -> str:
    if source.count(old) != 1 or old == new:
        raise AssertionError("Round052 genuine C source replacement not unique")
    return source.replace(old, new, 1)


def validate(source: str) -> tuple[str, str]:
    declaration = extract_unique(source, DECL_BEGIN, DECL_END)
    helper = extract_unique(source, HELPER_BEGIN, HELPER_END)
    call = extract_unique(source, MAP_BEGIN, MAP_END)
    map_start = source.index("static int swapz_map(struct dm_target *ti, struct bio *bio)")
    list_add = source.index("list_add_tail(&entry->list, &ctx->incoming);", map_start)
    next_prepare = source.index(
        "if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count)", list_add)
    complete = source.index("static void swapz_complete(struct bio *bio, int error)")
    if not (source.index(DECL_END) < source.index(HELPER_BEGIN) < map_start <
            list_add < source.index(MAP_BEGIN) < source.index(MAP_END) < next_prepare):
        raise AssertionError("Round052 probe not in accepted normal source BIO path")
    for begin, end in ((DECL_BEGIN, DECL_END), (HELPER_BEGIN, HELPER_END),
                       (MAP_BEGIN, MAP_END)):
        location = source.index(begin)
        if source.rfind("#if defined(" + GUARD + ")", 0, location) == -1:
            raise AssertionError("Round052 guard is not default undefined")
        if source.index("#endif /* " + GUARD + " */", location) < source.index(end):
            raise AssertionError("Round052 guard closes before region")
    if source.count("struct swapz_round052_internal_ticket round052_ticket;") != 1:
        raise AssertionError("Round052 per-clone test-only record absent")
    expected = (
        "static __used noinline int swapz_round052_internal_ticket_step(",
        "if (!ticket)", "if (ticket->phase != SWAPZ_ROUND052_NOT_ACCEPTED)",
        "bio_op(upper_bio) != REQ_OP_WRITE",
        "if (target->private != ctx || ctx->target != target ||",
        "!(upper_bio->bi_opf & REQ_SWAP)",
        "upper_bio->bi_iter.bi_size != SWAPZ_BLOCK_BYTES",
        "target_relative_sector % SWAPZ_SECTORS",
        "ticket->upper_bio = upper_bio;",
        "ticket->map_generation != map_generation ||",
        "ticket->gc_epoch != gc_epoch ||",
        "ticket->extent_start_block != extent_start_block ||",
        "if (lower_error < 0) {", "if (lower_error || !lower_durable)",
        "ticket->phase = SWAPZ_ROUND052_LOWER_DONE;",
        "ticket->map_publications++;", "ticket->upper_ack_attempts++;",
        "ticket->terminal_releases++;", "return -EALREADY;",
        "ticket->phase = SWAPZ_ROUND052_COMPLETED;",
        "ticket->phase = SWAPZ_ROUND052_ABORTED;",
    )
    for token in expected:
        if token not in helper:
            raise AssertionError("Round052 actual product C required negative anchor " + token)
    order = ("if (event == SWAPZ_ROUND052_ACCEPT) {",
             "ticket->phase = SWAPZ_ROUND052_ACCEPTED;",
             "if (event == SWAPZ_ROUND052_LOWER_COMPLETE) {",
             "ticket->phase = SWAPZ_ROUND052_LOWER_DONE;",
             "if (event == SWAPZ_ROUND052_PUBLISH) {",
             "ticket->phase = SWAPZ_ROUND052_PUBLISHED;",
             "if (event == SWAPZ_ROUND052_ACK) {",
             "ticket->phase = SWAPZ_ROUND052_COMPLETED;")
    if [helper.index(x) for x in order] != sorted(helper.index(x) for x in order):
        raise AssertionError("Round052 actual C completion order changed")
    executable = re.sub(r"/\*.*?\*/|//[^\n]*", "", helper + call, flags=re.DOTALL)
    for forbidden in ("bio_endio(", "submit_bio(", "dm_io(",
                      "swapz_lower_write(", "ctx->maps[", "return DM_MAPIO_",
                      "WRITE_ONCE(", "atomic_inc(", "schedule_work("):
        if forbidden in executable:
            raise AssertionError("Round052 test-only helper performs real I/O/ACK: " + forbidden)
    for required in ("&entry->round052_ticket", "SWAPZ_ROUND052_ACCEPT",
                     "bio_op(bio) == REQ_OP_WRITE", "count == SWAPZ_SECTORS",
                     "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES"):
        if required not in call:
            raise AssertionError("Round052 real accepted-path probe drift: " + required)
    for required in ("bio_endio(bio);", "static void swapz_async_lower_write_done(",
                     "complete(&inflight->lower_done);", "static int swapz_gc_relocate_one(",
                     "static void swapz_drain(", "drain_workqueue(ctx->workqueue);",
                     "return DM_MAPIO_SUBMITTED;"):
        if required not in source:
            raise AssertionError("Round052 inherited real callback/GC/dtr anchor absent: " + required)
    if complete >= map_start:
        raise AssertionError("Round052 actual original completion missing")
    return declaration, helper


def compose(source: str, *, allow_deliberate_mutation: bool = False) -> str:
    declaration = extract_unique(source, DECL_BEGIN, DECL_END)
    helper = extract_unique(source, HELPER_BEGIN, HELPER_END)
    if not allow_deliberate_mutation:
        validate(source)
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND052_INJECT_REAL_PRODUCT_TICKET_DECL */", declaration),
        ("/* ROUND052_INJECT_REAL_PRODUCT_TICKET_HELPER */", helper),
    ):
        fixture = replace_unique(fixture, marker, replacement)
    if PASS_MARKER not in fixture or "fault < 48U" not in fixture:
        raise AssertionError("Round052 host skips actual source C 144 cases")
    return fixture


def compile_and_run(compiler: str, source: str, directory: Path, name: str,
                    *, hostile: bool) -> None:
    input_path = directory / (name + ".c")
    binary_path = directory / name
    input_path.write_text(source, encoding="utf-8")
    arguments = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                 "-Wconversion", "-Wshadow", "-Werror",
                 "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-fno-omit-frame-pointer", "-o", str(binary_path), str(input_path)]
    built = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
    if built.returncode:
        raise AssertionError("FIRST Round052 actual product C compile failure " +
                             name + ":\n" + built.stderr[-8000:])
    run = subprocess.run([str(binary_path)], capture_output=True, text=True,
                         timeout=120,
                         env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                              "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    if hostile:
        if run.returncode == 0 or "FIRST Round052 actual product ticket C failure:" not in run.stderr:
            raise AssertionError("Round052 hostile changed product C escaped exact C oracle " +
                                 name + "\n" + run.stdout[-1000:] + run.stderr[-5000:])
    elif run.returncode or PASS_MARKER not in run.stdout:
        raise AssertionError("FIRST Round052 actual C host runtime failure " +
                             name + ":\n" + run.stdout[-2000:] + run.stderr[-8000:])


class Round052InternalTicket(unittest.TestCase):
    def test_genuine_product_source_scope_and_hostile_validators(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        declaration, helper = validate(source)
        self.assertIn("struct swapz_round052_internal_ticket", declaration)
        self.assertEqual(len(MUTATIONS), 13)
        for before, after in MUTATIONS:
            with self.subTest(mutant=before):
                self.assertEqual(helper.count(before), 1)
                changed = replace_unique(source, helper, helper.replace(before, after, 1))
                with self.assertRaises(AssertionError):
                    validate(changed)
        print("ROUND052_REAL_PRODUCT_13_HOSTILE_SOURCE_MUTANTS_REJECTED_PASS")

    def test_gcc_clang_real_product_C_ASAN_UBSAN(self) -> None:
        original = TARGET.read_text(encoding="utf-8")
        declaration, helper = validate(original)
        self.assertIn("struct swapz_round052_internal_ticket", declaration)
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        original_fixture = compose(original)
        completed_hostiles = 0
        with tempfile.TemporaryDirectory(prefix="round052-internal-dm-") as directory:
            output_directory = Path(directory)
            for compiler in ("gcc", "clang"):
                compile_and_run(compiler, original_fixture, output_directory,
                                compiler + "-actual", hostile=False)
                print("ROUND052_REAL_PRODUCT_TICKET_" + compiler.upper() +
                      "_144_STRICT_ASAN_UBSAN_PASS")
                for index, (before, after) in enumerate(MUTATIONS):
                    changed_helper = helper.replace(before, after, 1)
                    mutated_source = replace_unique(original, helper, changed_helper)
                    compile_and_run(compiler, compose(mutated_source, allow_deliberate_mutation=True),
                                    output_directory, compiler + "-mutant-" + str(index),
                                    hostile=True)
                    completed_hostiles += 1
        self.assertEqual(completed_hostiles, 2 * len(MUTATIONS))
        print("ROUND052_REAL_PRODUCT_13_HOSTILE_C_BINARIES_GCC_CLANG_REJECTED_PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test", "hostile-self-test"))
    choice = parser.parse_args().mode
    suite = unittest.TestSuite([Round052InternalTicket(
        "test_genuine_product_source_scope_and_hostile_validators")])
    if choice == "host-test":
        suite.addTest(Round052InternalTicket("test_gcc_clang_real_product_C_ASAN_UBSAN"))
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
