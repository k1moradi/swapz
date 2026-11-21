#!/usr/bin/env python3
"""Compile and execute original guarded production DM receipt C (no device I/O)."""
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round053-dm-accepted-normal-bio-host.c"
GUARD = "SWAPZ_ROUND053_DM_ACCEPTED_BIO_LIFECYCLE_TEST"
DECL_BEGIN = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_DECL_START */"
DECL_END = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_DECL_END */"
HELPER_BEGIN = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_HELPER_START */"
HELPER_END = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_HELPER_END */"
MAP_BEGIN = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_MAP_START */"
MAP_END = "/* ROUND053_DM_ACCEPTED_LIFECYCLE_MAP_END */"
PASS_MARKER = "ROUND053_REAL_PRODUCT_DM_162_LIFECYCLE_C_CASES_PASS"
FIRST_ERROR = "FIRST Round053 real DM lifecycle C failure:"

# Each mutation changes the original extracted C function, not a Python model.
MUTATIONS = (
    ("!READ_ONCE(ctx->accepting)", "false"),
    ("observation->external_stored ||", "false ||"),
    ("observation->original_uncompressed_bytes != SWAPZ_BLOCK_BYTES", "false"),
    ("!(upper_bio->bi_opf & REQ_SWAP)", "false"),
    ("upper_bio->bi_iter.bi_size != SWAPZ_BLOCK_BYTES", "false"),
    ("observation->target_relative_sector !=\n\t\t\t    upper_bio->bi_iter.bi_sector", "false"),
    ("receipt->gc_epoch != observation->gc_epoch", "false"),
    ("receipt->map_generation != observation->map_generation", "false"),
    ("observation->synthetic_lease_token != receipt->synthetic_lease_token", "false"),
    ("!observation->synthetic_live_lease || observation->dtr_started", "false"),
    ("if (lower_error < 0) {", "if (false) {"),
    ("if (lower_error || !lower_durable)", "if (lower_error && !lower_durable)"),
    ("if (receipt->phase != SWAPZ_ROUND053_DURABLE)", "if (false)"),
    ("receipt->lower_callbacks++;", "receipt->lower_callbacks += 0U;"),
    ("receipt->map_publications++;", "receipt->map_publications += 0U;"),
    ("receipt->upper_ack_attempts++;", "receipt->upper_ack_attempts += 0U;"),
    ("receipt->phase = SWAPZ_ROUND053_COMPLETED;",
     "receipt->phase = SWAPZ_ROUND053_MAPPED;"),
)


def region(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH: missing/duplicate original C anchors")
    start = source.index(begin) + len(begin)
    finish = source.index(end)
    if start >= finish:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH: original C anchor order")
    return source[start:finish]


def verify_actual_production_source(source: str) -> tuple[str, str]:
    declaration = region(source, DECL_BEGIN, DECL_END)
    helper = region(source, HELPER_BEGIN, HELPER_END)
    observer = region(source, MAP_BEGIN, MAP_END)
    map_start = source.index("static int swapz_map(struct dm_target *ti, struct bio *bio)")
    list_add = source.index("list_add_tail(&entry->list, &ctx->incoming);", map_start)
    next_prepare = source.index(
        "if (ctx->async_prepare && bio_op(bio) == REQ_OP_WRITE && count)", list_add)
    if not (source.index(DECL_END) < source.index(HELPER_BEGIN) < map_start <
            list_add < source.index(MAP_BEGIN) < source.index(MAP_END) < next_prepare):
        raise AssertionError("SOURCE_CONTRACT_MISMATCH: receipt is not post-admission")
    if source.count("struct swapz_round053_internal_receipt round053_receipt;") != 1:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH: no per-clone receipt")
    for begin, end in ((DECL_BEGIN, DECL_END), (HELPER_BEGIN, HELPER_END),
                       (MAP_BEGIN, MAP_END)):
        if source.rfind("#if defined(" + GUARD + ")", 0, source.index(begin)) == -1:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: helper not default-off")
        if source.index("#endif /* " + GUARD + " */", source.index(begin)) < source.index(end):
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: guard prematurely closed")
    for required in (
        "static __used noinline int swapz_round053_internal_receipt_step(",
        "SWAPZ_ROUND053_LOWER_PENDING", "SWAPZ_ROUND053_DURABLE",
        "SWAPZ_ROUND053_MAPPED", "SWAPZ_ROUND053_COMPLETED",
        "SWAPZ_ROUND053_ABORTED", "receipt->terminal_releases++;",
        "observation->external_stored", "observation->original_uncompressed_bytes",
        "if (lower_error < 0) {", "if (lower_error || !lower_durable)",
        "receipt->gc_epoch != observation->gc_epoch",
        "receipt->synthetic_lease_token", "!observation->synthetic_live_lease",
        "receipt->upper_ack_attempts++;", "receipt->map_publications++;",
    ):
        if required not in helper:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: changed C guard " + required)
    for required in ("&entry->round053_receipt", "SWAPZ_ROUND053_ACCEPT",
                     "bio_op(bio) == REQ_OP_WRITE", "count == SWAPZ_SECTORS",
                     "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES"):
        if required not in observer:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: production admission anchor " + required)
    executable = re.sub(r"/\*.*?\*/|//[^\n]*", "", helper + observer, flags=re.DOTALL)
    for forbidden in ("bio_endio(", "submit_bio(", "dm_io(",
                      "swapz_lower_write(", "ctx->maps[", "WRITE_ONCE(",
                      "schedule_work(", "return DM_MAPIO_"):
        if forbidden in executable:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: test helper gained real I/O " + forbidden)
    for anchor in ("static void swapz_async_lower_write_done(",
                   "complete(&inflight->lower_done);", "static void swapz_complete(",
                   "bio_endio(bio);", "static int swapz_gc_relocate_one(",
                   "static void swapz_drain(", "drain_workqueue(ctx->workqueue);",
                   "static void swapz_dtr(", "swapz_drain(ti);",
                   "return DM_MAPIO_SUBMITTED;"):
        if anchor not in source:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: real source lifecycle anchor " + anchor)
    return declaration, helper


def compose(actual_source: str, *, changed_helper: str | None = None) -> str:
    declaration, helper = verify_actual_production_source(actual_source)
    if changed_helper is not None:
        helper = changed_helper
    fixture = FIXTURE.read_text(encoding="utf-8")
    for anchor, value in (
        ("/* ROUND053_INJECT_REAL_PRODUCT_RECEIPT_DECL */", declaration),
        ("/* ROUND053_INJECT_REAL_PRODUCT_RECEIPT_HELPER */", helper),
    ):
        if fixture.count(anchor) != 1:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH: fixture injection failed")
        fixture = fixture.replace(anchor, value, 1)
    if PASS_MARKER not in fixture or "fault < 54U" not in fixture:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH: fixture omitted C cases")
    return fixture


def compile_and_execute(compiler: str, code: str, path: Path, label: str,
                        *, expect_hostile: bool) -> None:
    source_file = path / (label + ".c")
    binary_file = path / label
    source_file.write_text(code, encoding="utf-8")
    command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
               "-Wconversion", "-Wshadow", "-Werror",
               "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-omit-frame-pointer", "-no-pie", "-o", str(binary_file),
               str(source_file)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise AssertionError("FIRST Round053 product C compile failure " + label +
                             ": " + result.stderr[-5000:])
    executed = subprocess.run([str(binary_file)], text=True, capture_output=True,
                              timeout=90, env={**os.environ,
                              "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                              "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    if expect_hostile:
        if executed.returncode == 0 or FIRST_ERROR not in executed.stderr:
            raise AssertionError("FIRST Round053 hostile actual C mutant escaped " +
                                 label + ": " + executed.stderr[-3000:] +
                                 executed.stdout[-1000:])
    elif executed.returncode or PASS_MARKER not in executed.stdout:
        raise AssertionError("FIRST Round053 actual product C runtime failure " +
                             label + ": " + executed.stderr[-5000:] +
                             executed.stdout[-2000:])


class Round053RealSource(unittest.TestCase):
    def test_real_source_and_mutation_anchors(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        declaration, helper = verify_actual_production_source(source)
        self.assertIn("struct swapz_round053_internal_receipt", declaration)
        self.assertGreaterEqual(len(MUTATIONS), 10)
        for old, new in MUTATIONS:
            with self.subTest(source_mutation=old):
                self.assertEqual(helper.count(old), 1)
                self.assertNotEqual(old, new)
        print("ROUND053_REAL_DM_17_CHANGED_ORIGINAL_C_MUTATION_ANCHORS_PASS")

    def test_gcc_clang_source_extracted_strict_sanitized_execution(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        _, original_helper = verify_actual_production_source(source)
        actual_code = compose(source)
        with tempfile.TemporaryDirectory(prefix="round053-dm-source-c-") as scratch:
            output = Path(scratch)
            for compiler in ("gcc", "clang"):
                if shutil.which(compiler) is None:
                    self.fail("required compiler unavailable: " + compiler)
                compile_and_execute(compiler, actual_code, output,
                                    compiler + "-actual-dm", expect_hostile=False)
                print("ROUND053_DM_" + compiler.upper() + "_162_REAL_SOURCE_C_ASAN_UBSAN_PASS")
                for index, (old, new) in enumerate(MUTATIONS):
                    mutated_helper = original_helper.replace(old, new, 1)
                    compile_and_execute(compiler, compose(source, changed_helper=mutated_helper),
                                        output, compiler + "-hostile-" + str(index),
                                        expect_hostile=True)
                print("ROUND053_DM_" + compiler.upper() + "_17_EXECUTED_SOURCE_MUTANT_C_PASS")


if __name__ == "__main__":
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("mode", choices=("host-test", "hostile-self-test"))
    requested = argument_parser.parse_args().mode
    suite = unittest.TestSuite([Round053RealSource("test_real_source_and_mutation_anchors")])
    if requested == "host-test":
        suite.addTest(Round053RealSource(
            "test_gcc_clang_source_extracted_strict_sanitized_execution"))
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
