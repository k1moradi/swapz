#!/usr/bin/env python3
"""Round046: strictly negative CURRENT genuine DM ->map/GC/dtr lifetime C proof.

Compile the actual guarded helper and real ->map callsite extracted from
src/kernel/dm-target.c. Inherit and execute all Round030/040/041/043 C cases.
Host reports are intentionally FAKE; passing never authenticates the original
MM swap-slot incarnation, current dm_table, map or GC lifetime.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
PREVIOUS = ROOT / "tests/tools/round043-dm-real-ingress-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round046-dm-lifetime-host.c"
GUARD = "SWAPZ_ROUND046_DM_LIFETIME_NONAUTHORITY_TEST"
HELPER_BEGIN = "/* ROUND046_DM_LIFETIME_HELPER_EXACT_START */"
HELPER_END = "/* ROUND046_DM_LIFETIME_HELPER_EXACT_END */"
CALL_BEGIN = "/* ROUND046_DM_LIFETIME_MAP_CALLSITE_EXACT_START */"
CALL_END = "/* ROUND046_DM_LIFETIME_MAP_CALLSITE_EXACT_END */"
EXPECTED = "ROUND046_ACTUAL_DM_MAP_TABLE_GC_DTR_90_NO_AUTHORITY_PASS"


def extract_unique(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round046 actual product source markers drift")
    return source.split(begin, 1)[1].split(end, 1)[0]


def replace_unique(content: str, old: str, new: str) -> str:
    if content.count(old) != 1:
        raise AssertionError("Round046 source fixture insertion drift: " + old[:90])
    return content.replace(old, new, 1)


def validate_real_lifetime(source: str) -> tuple[str, str]:
    helper = extract_unique(source, HELPER_BEGIN, HELPER_END)
    callsite = extract_unique(source, CALL_BEGIN, CALL_END)
    map_start = source.find("static int swapz_map(struct dm_target *ti, struct bio *bio)")
    entry = source.find("entry = dm_per_bio_data(bio, sizeof(*entry));", map_start)
    if map_start < 0 or entry < 0:
        raise AssertionError("Round046 genuine swapz_map() missing")
    if not (source.index(HELPER_BEGIN) < map_start <
            source.index(CALL_BEGIN) < source.index(CALL_END) < entry):
        raise AssertionError("Round046 must observe REAL ->map before per-BIO admission")
    for marker in (HELPER_BEGIN, CALL_BEGIN):
        preprocessor = source.rfind("#if defined(" + GUARD + ")", 0,
                                    source.index(marker))
        if preprocessor < 0:
            raise AssertionError("Round046 default-undefined guard missing")
        guard_text = source[preprocessor:source.index(marker)]
        for name in (GUARD, "SWAPZ_ROUND043_DM_REAL_MAP_INGRESS_OBSERVATION_TEST",
                     "SWAPZ_ROUND041_DM_TARGET_INTERVAL_MAP_NONAUTHORITY_TEST",
                     "SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST",
                     "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY"):
            if "defined(" + name + ")" not in guard_text:
                raise AssertionError("Round046 missing nested original guard: " + name)
    for required in (
        "#define SWAPZ_ROUND046_SOURCE_MAPPED_AUTHENTICATED 0U",
        "static __used noinline int swapz_round046_dm_lifetime_refuse(",
        "target->private != ctx", "ctx->target != target",
        "!READ_ONCE(ctx->accepting)", "ctx->authority.maps != ctx->maps",
        "bio_sectors(upper_bio) != SWAPZ_SECTORS",
        "target_relative_sector = upper_bio->bi_iter.bi_sector",
        "target_relative_sector % SWAPZ_SECTORS",
        "target_relative_sector >= target->len",
        "SWAPZ_SECTORS > target->len - target_relative_sector",
        "submitted->target_identity != (unsigned long)target",
        "submitted->context_identity != (unsigned long)ctx",
        "submitted->target_relative_sector != target_relative_sector",
        "submitted->table_epoch != observed->table_epoch",
        "submitted->callback_ticket != observed->callback_ticket",
        "submitted->map_generation != observed->map_generation",
        "submitted->extent_start_block != observed->extent_start_block",
        "submitted->gc_destination != observed->gc_destination",
        "submitted->original_bdev_cookie != observed->original_bdev_cookie",
        "submitted->original_physical_sector != observed->original_physical_sector",
        "return -ESTALE;", "return -ERANGE;",
        "return -EOPNOTSUPP;\n}",
    ):
        if required not in helper:
            raise AssertionError("Round046 source guard missing: " + required)
    if callsite.count(
            "(void)swapz_round046_dm_lifetime_refuse(ti, ctx, bio, NULL, NULL);") != 1:
        raise AssertionError("Round046 real callsite not pure refusal")
    for required in ("bio_op(bio) == REQ_OP_WRITE",
                     "count == SWAPZ_SECTORS",
                     "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES"):
        if required not in callsite:
            raise AssertionError("Round046 real callsite geometry drift: " + required)
    executable = re.sub(r"/\*.*?\*/|//[^\n]*", "", helper + "\n" + callsite,
                        flags=re.DOTALL)
    for forbidden in (
        "return 0;", "return DM_MAPIO_", "bio_endio(", "submit_bio(",
        "swapz_lower_write(", "swapz_lower_read(",
        "ctx->maps[", "ctx->authority.maps[",
        "swapz_gc(", "entry->", "bio->bi_status",
    ):
        if forbidden in executable:
            raise AssertionError("Round046 attempted actual map/ACK/GC mutation: " +
                                 forbidden)
    # Static source anchors are part of the live teardown and GC analysis;
    # passing is not an asynchronously retained table/extent reference.
    for required in ("static int swapz_ctr(", "static void swapz_dtr(",
                     "ctx->gc_recovery.active", "swapz_backing_data_sector("):
        if required not in source:
            raise AssertionError("Round046 real ctr/dtr/GC source anchor missing: " +
                                 required)
    return helper, callsite


def compose_actual_production_c() -> str:
    source = TARGET.read_text(encoding="utf-8")
    helper, callsite = validate_real_lifetime(source)
    inherited = runpy.run_path(str(PREVIOUS),
                               run_name="round046_real_predecessor")[
                                   "compose_actual_production_c"]()
    # The earliest textual main belongs to Round030 under #define main;
    # the LAST main is Round043 and must run first in the new executable.
    old_main = "\nint main(void)\n{"
    old_index = inherited.rfind(old_main)
    if old_index < 0 or inherited.count(old_main) != 2:
        raise AssertionError("Round046 inherited Round030/043 main chain drift")
    inherited = inherited[:old_index] + inherited[old_index:].replace(
        old_main, "\nint round043_fixture_main(void)\n{", 1)
    if inherited.count(old_main) != 1 or inherited.count(
            "int round043_fixture_main(void)") != 1:
        raise AssertionError("Round046 lost inherited executable main chain")
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, value in (
        ("/* ROUND046_INHERIT_REAL_ROUND043_SOURCE */", inherited),
        ("/* ROUND046_EXTRACT_ACTUAL_LIFETIME_HELPER */", helper),
        ("/* ROUND046_EXTRACT_ACTUAL_LIFETIME_CALLSITE */", callsite),
    ):
        fixture = replace_unique(fixture, marker, value)
    if fixture.count("int main(void)") != 2 or (
            "assert(round043_fixture_main() == 0);" not in fixture or
            "fault < 30U" not in fixture or EXPECTED not in fixture):
        raise AssertionError("Round046 new fixture skipped old/new executable cases")
    return fixture


class RealDmLifetimeTests(unittest.TestCase):
    def test_hostile_real_product_guard_and_callsite_fail_closed(self) -> None:
        original = TARGET.read_text(encoding="utf-8")
        helper, callsite = validate_real_lifetime(original)
        mutations = (
            ("target->private != ctx", "0"),
            ("ctx->target != target", "0"),
            ("!READ_ONCE(ctx->accepting)", "false"),
            ("ctx->authority.maps != ctx->maps", "false"),
            ("submitted->target_identity != (unsigned long)target", "false"),
            ("submitted->table_epoch != observed->table_epoch", "false"),
            ("submitted->callback_ticket != observed->callback_ticket", "false"),
            ("submitted->map_generation != observed->map_generation", "false"),
            ("submitted->original_bdev_cookie != observed->original_bdev_cookie", "false"),
            ("target_relative_sector = upper_bio->bi_iter.bi_sector",
             "target_relative_sector = target->begin + upper_bio->bi_iter.bi_sector"),
            ("return -EOPNOTSUPP;\n}", "return 0;\n}"),
        )
        for before, after in mutations:
            with self.subTest(before=before):
                self.assertEqual(helper.count(before), 1)
                modified = helper.replace(before, after, 1)
                self.assertNotEqual(modified, helper)
                mutant = replace_unique(original, helper, modified)
                with self.assertRaisesRegex(AssertionError, "Round046"):
                    validate_real_lifetime(mutant)
        self.assertEqual(
            callsite.count("(void)swapz_round046_dm_lifetime_refuse(ti, ctx, bio, NULL, NULL);"), 1)
        broken_callsite = callsite.replace(
            "(void)swapz_round046_dm_lifetime_refuse(ti, ctx, bio, NULL, NULL);",
            "return DM_MAPIO_KILL;", 1)
        with self.assertRaisesRegex(AssertionError, "Round046"):
            validate_real_lifetime(
                replace_unique(original, callsite, broken_callsite))
        print("ROUND046_LIVE_DM_LIFETIME_12_HOSTILE_SOURCE_MUTANTS_REJECTED_PASS")

    def test_genuine_map_lifetime_gcc_clang_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round046-current-dm-lifetime-") as path:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    folder = Path(path)
                    c_path = folder / (compiler + ".c")
                    codec_object = folder / (compiler + "-codec.o")
                    executable = folder / compiler
                    c_path.write_text(source, encoding="utf-8")
                    flags = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-pthread", "-I", str(CODEC.parent),
                    ]
                    compiled_codec = subprocess.run(
                        [*flags, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)], capture_output=True,
                        text=True, timeout=90)
                    self.assertEqual(
                        compiled_codec.returncode, 0,
                        "FIRST inherited codec compiler error:\n" +
                        compiled_codec.stderr[-12000:])
                    built = subprocess.run(
                        [*flags, str(c_path), str(codec_object), "-llz4",
                         "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=150)
                    self.assertEqual(
                        built.returncode, 0,
                        "FIRST actual source-extracted lifetime C compiler error:\n" +
                        built.stderr[-18000:])
                    executed = subprocess.run(
                        [str(executable)], capture_output=True, text=True,
                        timeout=180,
                        env={**os.environ,
                             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        executed.returncode, 0,
                        "FIRST actual DM lifetime C sanitizer/assertion failure:\n" +
                        executed.stdout[-6000:] + executed.stderr[-18000:])
                    for marker in (
                        "ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS",
                        "ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS",
                        "ROUND043_REAL_PRODUCT_MAP_INGRESS_90_NO_AUTHORITY_PASS",
                        EXPECTED,
                    ):
                        self.assertIn(marker, executed.stdout)
                    print("ROUND046_REAL_DM_MAP_GC_DTR_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse

    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "mode", choices=("host-test", "hostile-self-test"))
    requested_mode = argument_parser.parse_args().mode
    suite = unittest.TestSuite([
        RealDmLifetimeTests(
            "test_hostile_real_product_guard_and_callsite_fail_closed")
    ])
    if requested_mode == "host-test":
        suite.addTest(RealDmLifetimeTests(
            "test_genuine_map_lifetime_gcc_clang_asan_ubsan"))
    raise SystemExit(
        0 if unittest.TextTestRunner(verbosity=2).run(
            suite).wasSuccessful() else 1)
