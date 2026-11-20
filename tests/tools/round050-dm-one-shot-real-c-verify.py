#!/usr/bin/env python3
"""Round050: strict real production-C executable one-shot NO_AUTH negatives.

The helper and ->map callsite are extracted exactly from src/kernel/dm-target.c
and compiled, not recreated in Python. All reports are host synthetic:
no real counted source slot, live DM table reference, lower I/O, map or ACK.
"""
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round050-dm-one-shot-host.c"
GUARD = "SWAPZ_ROUND050_DM_ONE_SHOT_NEGATIVE_TEST"
BEGIN = "/* ROUND050_DM_ONE_SHOT_NEGATIVE_HELPER_START */"
END = "/* ROUND050_DM_ONE_SHOT_NEGATIVE_HELPER_END */"
CALL_BEGIN = "/* ROUND050_DM_ONE_SHOT_MAP_CALLSITE_START */"
CALL_END = "/* ROUND050_DM_ONE_SHOT_MAP_CALLSITE_END */"
EXPECTED = "ROUND050_REAL_PRODUCT_ONE_SHOT_159_NEGATIVE_C_CASES_PASS"

# Distinct *genuine* C guard mutations. Every one changes exactly one
# occurrence in the marked, product-owned helper function, not another helper
# from one of the inherited audits. Runtime exact-errno assertions also fail
# for these when compiled, even though all unchanged baseline cases refuse.
MUTATIONS = (
    ("if (submitted->teardown_started || observed->teardown_started)",
     "if (false)"),
    ("!READ_ONCE(ctx->accepting)", "false"),
    ("smp_load_acquire(&ctx->failed)", "false"),
    ("target->private != ctx", "false"),
    ("ctx->authority.maps != ctx->maps", "false"),
    ("target_relative_sector = upper_bio->bi_iter.bi_sector;",
     "target_relative_sector = submitted->original_physical_sector;"),
    ("submitted->table_epoch != observed->table_epoch", "false"),
    ("submitted->callback_ticket != observed->callback_ticket", "false"),
    ("submitted->map_generation != observed->map_generation", "false"),
    ("submitted->gc_epoch != observed->gc_epoch", "false"),
    ("submitted->extent_start_block != observed->extent_start_block", "false"),
    ("submitted->original_physical_sector != observed->original_physical_sector",
     "false"),
    ("submitted->extent_blocks != 4U", "submitted->extent_blocks != 3U"),
    ("!submitted->compressed_crc_valid", "false"),
    ("submitted->upper_ack_attempts ||", "false ||"),
    ("observed->upper_ack_attempts ||", "false ||"),
    ("submitted->lower_completion_count > 1U", "false"),
    ("!submitted->lower_write_durable", "false"),
    ("observed->lower_write_bytes != submitted->lower_write_bytes", "false"),
    ("submitted->lower_error ||", "false ||"),
    ("submitted->map_publications != 1U", "false"),
    ("return -EOPNOTSUPP;\n}", "return 0;\n}"),
)
REQUIRED = (
    "#define SWAPZ_ROUND050_SOURCE_MAPPED_AUTHENTICATED 0U",
    "struct swapz_round050_dm_pending_report {",
    "static __used noinline int swapz_round050_dm_one_shot_refuse(",
    "if (!target || !ctx || !upper_bio)",
    "if (!submitted || !observed)",
    "if (submitted->teardown_started || observed->teardown_started)",
    "!READ_ONCE(ctx->accepting)",
    "smp_load_acquire(&ctx->failed)",
    "target->private != ctx",
    "ctx->target != target",
    "ctx->authority.maps != ctx->maps",
    "bio_sectors(upper_bio) != SWAPZ_SECTORS",
    "target_relative_sector = upper_bio->bi_iter.bi_sector;",
    "target_relative_sector % SWAPZ_SECTORS",
    "SWAPZ_SECTORS > target->len - target_relative_sector",
    "submitted->target_relative_sector != target_relative_sector",
    "observed->target_relative_sector != target_relative_sector",
    "submitted->table_epoch != observed->table_epoch",
    "submitted->callback_ticket != observed->callback_ticket",
    "submitted->map_generation != observed->map_generation",
    "submitted->gc_epoch != observed->gc_epoch",
    "submitted->extent_start_block != observed->extent_start_block",
    "submitted->original_bdev_cookie != observed->original_bdev_cookie",
    "submitted->original_physical_sector != observed->original_physical_sector",
    "submitted->extent_blocks != 1U",
    "submitted->extent_blocks != 2U",
    "submitted->extent_blocks != 4U",
    "submitted->compressed_length > SWAPZ_MAX_COMPRESSED",
    "submitted->compressed_length >\n\t\t    submitted->extent_blocks * SWAPZ_BLOCK_BYTES",
    "!submitted->compressed_crc_valid",
    "submitted->upper_ack_attempts ||",
    "observed->upper_ack_attempts ||",
    "submitted->lower_completion_count > 1U",
    "observed->lower_completion_count > 1U",
    "!submitted->lower_write_durable",
    "!observed->lower_write_durable",
    "submitted->lower_write_bytes !=",
    "observed->lower_write_bytes != submitted->lower_write_bytes",
    "submitted->lower_error ||",
    "submitted->map_publications != 1U",
    "observed->map_publications != 1U",
    "return -EOPNOTSUPP;\n}",
)
ORDER = (
    "if (submitted->teardown_started || observed->teardown_started)",
    "!READ_ONCE(ctx->accepting)",
    "target->private != ctx",
    "target_relative_sector = upper_bio->bi_iter.bi_sector;",
    "submitted->table_epoch != observed->table_epoch",
    "submitted->map_generation != observed->map_generation",
    "submitted->gc_epoch != observed->gc_epoch",
    "submitted->upper_ack_attempts ||",
    "!submitted->lower_write_durable",
    "submitted->map_publications != 1U",
    "return -EOPNOTSUPP;\n}",
)


def extract_unique(text: str, start: str, stop: str) -> str:
    if text.count(start) != 1 or text.count(stop) != 1:
        raise AssertionError("Round050 real production markers missing/nonunique")
    if text.index(start) >= text.index(stop):
        raise AssertionError("Round050 real production marker order reversed")
    return text.split(start, 1)[1].split(stop, 1)[0]


def replace_unique(text: str, before: str, after: str) -> str:
    if text.count(before) != 1 or before == after:
        raise AssertionError("Round050 non-unique or no-op genuine source replacement")
    return text.replace(before, after, 1)


def validate(source: str) -> tuple[str, str]:
    helper = extract_unique(source, BEGIN, END)
    call = extract_unique(source, CALL_BEGIN, CALL_END)
    signature = "static int swapz_map(struct dm_target *ti, struct bio *bio)"
    if source.count(signature) != 1:
        raise AssertionError("Round050 real product map entry missing")
    map_start = source.index(signature)
    map_entry = source.index("entry = dm_per_bio_data(bio, sizeof(*entry));",
                             map_start)
    if not (source.index(BEGIN) < source.index(END) < map_start <
            source.index(CALL_BEGIN) < source.index(CALL_END) < map_entry):
        raise AssertionError("Round050 observer outside actual target map")
    for start, stop in ((BEGIN, END), (CALL_BEGIN, CALL_END)):
        start_index = source.index(start)
        preprocessor = source.rfind("#if defined(" + GUARD + ")", 0, start_index)
        if preprocessor == -1 or source.count(
                "#endif /* " + GUARD + " */",
                start_index, source.index(stop) + len(stop) + 80) != 1:
            raise AssertionError("Round050 source-only guard not default undefined")
        if source.index("#endif /* " + GUARD + " */", start_index) < source.index(stop):
            raise AssertionError("Round050 guard closed before source region")
    for literal in REQUIRED:
        if helper.count(literal) != 1:
            raise AssertionError("Round050 lost exact original C negative anchor " +
                                 literal)
    offsets = [helper.index(literal) for literal in ORDER]
    if offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
        raise AssertionError("Round050 real negative-phase progression reordered")
    expected_call = "(void)swapz_round050_dm_one_shot_refuse(ti, ctx, bio, NULL, NULL);"
    if call.count(expected_call) != 1:
        raise AssertionError("Round050 no-auth source reports made non-NULL at real map")
    for literal in ("bio_op(bio) == REQ_OP_WRITE",
                    "count == SWAPZ_SECTORS",
                    "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES"):
        if call.count(literal) != 1:
            raise AssertionError("Round050 real in-band call geometry drift")
    executable = re.sub(r"/\*.*?\*/|//[^\n]*", "",
                        helper + "\n" + call, flags=re.DOTALL)
    for forbidden in ("return 0;", "bio_endio(", "submit_bio(",
                      "dm_io(", "swapz_lower_write(", "ctx->maps[",
                      "ctx->authority.maps[", "return DM_MAPIO_",
                      "WRITE_ONCE(", "atomic_inc(", "atomic_set("):
        if forbidden in executable:
            raise AssertionError("Round050 negative real helper performs I/O/ACK " +
                                 forbidden)
    if executable.count("return -EOPNOTSUPP;") != 2:
        raise AssertionError("Round050 synthetic reports are no longer unconditional refusal")
    # Ground this compiled helper in the genuine normal existing callback
    # lifetime and completion path; these are NOT compiled by the host shim.
    for token in ("static void swapz_async_lower_write_done(",
                  "complete(&inflight->lower_done);",
                  "static void swapz_complete(",
                  "bio_endio(bio);",
                  "static void swapz_gc_relocate_one(",
                  "snapshot = ctx->maps[logical];",
                  "static void swapz_dtr(",
                  "swapz_drain(ti);",
                  "static bool swapz_try_completion_handoff(",
                  "atomic_cmpxchg(&ctx->completion_active, 0, 1)"):
        if token not in source:
            raise AssertionError("Round050 actual product callback/ACK anchor absent " +
                                 token)
    return helper, call


def compose(source: str) -> str:
    helper, call = validate(source)
    fixture = FIXTURE.read_text(encoding="utf-8")
    fixture = replace_unique(
        fixture, "/* ROUND050_INJECT_REAL_PRODUCT_NEGATIVE_HELPER */", helper)
    fixture = replace_unique(
        fixture, "/* ROUND050_INJECT_REAL_PRODUCT_MAP_CALLSITE */", call)
    if (EXPECTED not in fixture or "negative_cases == 159U" not in fixture or
            fixture.count("int main(void)") != 1):
        raise AssertionError("Round050 host fixture would skip 159 original C cases")
    return fixture


def compile_and_execute(
        compiler: str, source: str, directory: Path, stem: str,
        *, expected_failure: bool) -> None:
    input_path = directory / (stem + ".c")
    executable = directory / stem
    input_path.write_text(source, encoding="utf-8")
    command = [
        compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
        "-Wconversion", "-Wshadow", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-o", str(executable), str(input_path),
    ]
    built = subprocess.run(
        command, text=True, capture_output=True, timeout=90)
    if built.returncode != 0:
        raise AssertionError("FIRST Round050 actual source C " + compiler +
                             " compile failure " + stem + ":\n" +
                             built.stderr[-12000:])
    run = subprocess.run(
        [str(executable)], text=True, capture_output=True, timeout=120,
        env={**os.environ,
             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    if not expected_failure:
        if run.returncode != 0:
            raise AssertionError("FIRST Round050 actual source C " + compiler +
                                 " sanitizer/assertion failure:\n" +
                                 run.stdout[-4000:] + run.stderr[-12000:])
        if EXPECTED not in run.stdout:
            raise AssertionError("Round050 did not execute 159 original C negatives")
    else:
        if run.returncode == 0 or (
                "FIRST Round050 actual product negative C failure:" not in
                run.stderr):
            raise AssertionError(
                "Round050 mutated product C was not rejected by exact C oracle " +
                stem + " stdout:\n" + run.stdout[-3000:] +
                "\nstderr:\n" + run.stderr[-6000:])


class RealProductionGuardTests(unittest.TestCase):
    def test_original_product_guard_hostile_source_scope(self) -> None:
        original = TARGET.read_text(encoding="utf-8")
        helper, call = validate(original)
        self.assertEqual(len(MUTATIONS), 22)
        seen = set()
        for before, after in MUTATIONS:
            with self.subTest(before=before):
                self.assertNotIn((before, after), seen)
                seen.add((before, after))
                self.assertEqual(helper.count(before), 1)
                altered = helper.replace(before, after, 1)
                self.assertNotEqual(altered, helper)
                mutant = replace_unique(original, helper, altered)
                # Every mutation must be scoped to this exact actual
                # product helper and preserve the actual real-map call.
                self.assertEqual(extract_unique(mutant, CALL_BEGIN, CALL_END),
                                 call)
                with self.assertRaisesRegex(AssertionError, "Round050"):
                    validate(mutant)
        print("ROUND050_REAL_PRODUCT_ONE_SHOT_22_HOSTILE_SOURCE_MUTANTS_REJECTED_PASS")

    def test_strict_gcc_clang_actual_C_ASAN_UBSAN(self) -> None:
        source = TARGET.read_text(encoding="utf-8")
        base_fixture = compose(source)
        helper, _ = validate(source)
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round050-product-negative-") as directory:
            root = Path(directory)
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    compile_and_execute(
                        compiler, base_fixture, root, compiler + "-original",
                        expected_failure=False)
                    print("ROUND050_REAL_PRODUCT_ONE_SHOT_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")
                    for index, (before, after) in enumerate(MUTATIONS):
                        mutated = replace_unique(
                            source, helper, helper.replace(before, after, 1))
                        mutant_fixture = compose_without_validation(mutated)
                        compile_and_execute(
                            compiler, mutant_fixture, root,
                            compiler + "-hostile-" + str(index),
                            expected_failure=True)
            print("ROUND050_REAL_PRODUCT_22_HOSTILE_C_BINARIES_GCC_CLANG_REJECTED_PASS")


def compose_without_validation(source: str) -> str:
    """Compile a deliberately broken real-C helper after source validator RED."""
    helper = extract_unique(source, BEGIN, END)
    call = extract_unique(source, CALL_BEGIN, CALL_END)
    fixture = FIXTURE.read_text(encoding="utf-8")
    return replace_unique(
        replace_unique(
            fixture, "/* ROUND050_INJECT_REAL_PRODUCT_NEGATIVE_HELPER */",
            helper),
        "/* ROUND050_INJECT_REAL_PRODUCT_MAP_CALLSITE */", call)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test", "hostile-self-test"))
    chosen = parser.parse_args().mode
    suite = unittest.TestSuite([
        RealProductionGuardTests("test_original_product_guard_hostile_source_scope"),
    ])
    if chosen == "host-test":
        suite.addTest(RealProductionGuardTests(
            "test_strict_gcc_clang_actual_C_ASAN_UBSAN"))
    raise SystemExit(0 if unittest.TextTestRunner(
        verbosity=2).run(suite).wasSuccessful() else 1)
