#!/usr/bin/env python3
"""Round043: extract and execute the REAL swapz_map() v1 ingress C callsite.

The host provider is deliberately fake: it proves negative mechanics, not
source allocation incarnation, authentic GPL ownership, real DM lifetime or
IO. Actual original pinned Linux GPL export and DM matched modpost are a
separate required workflow step, never replaced by this host-only stub.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
PREVIOUS = ROOT / "tests/tools/round041-dm-target-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round043-dm-real-ingress-host.c"
GUARD = "SWAPZ_ROUND043_DM_REAL_MAP_INGRESS_OBSERVATION_TEST"
HELPER_BEGIN = "/* ROUND043_DM_REAL_MAP_INGRESS_EXACT_START */"
HELPER_END = "/* ROUND043_DM_REAL_MAP_INGRESS_EXACT_END */"
CALL_BEGIN = "/* ROUND043_DM_REAL_MAP_CALLSITE_EXACT_START */"
CALL_END = "/* ROUND043_DM_REAL_MAP_CALLSITE_EXACT_END */"
EXPECTED = "ROUND043_REAL_PRODUCT_MAP_INGRESS_90_NO_AUTHORITY_PASS"


def replace_unique(content: str, old: str, new: str) -> str:
    if content.count(old) != 1:
        raise AssertionError("Round043 real source/fixture layout drift: " +
                             old[:96])
    return content.replace(old, new, 1)


def extract_unique(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("Round043 exact genuine production C markers drift")
    return source.split(begin, 1)[1].split(end, 1)[0]


def validate_real_map_ingress(source: str) -> tuple[str, str]:
    helper = extract_unique(source, HELPER_BEGIN, HELPER_END)
    callsite = extract_unique(source, CALL_BEGIN, CALL_END)
    map_start = source.find("static int swapz_map(struct dm_target *ti, struct bio *bio)")
    entry = source.find("entry = dm_per_bio_data(bio, sizeof(*entry));", map_start)
    if map_start < 0 or entry < 0:
        raise AssertionError("Round043 actual product swapz_map missing")
    if not (map_start < source.index(CALL_BEGIN) <
            source.index(CALL_END) < entry):
        raise AssertionError("Round043 witness is NOT in REAL map before admission")
    previous_geometry = source.find("return DM_MAPIO_KILL;", map_start)
    if not (map_start < previous_geometry < source.index(CALL_BEGIN)):
        raise AssertionError("Round043 callsite precedes real BIO geometry validation")
    beginning_of_helper = source.rfind("#if defined(" + GUARD + ")",
                                       0, source.index(HELPER_BEGIN))
    beginning_of_call = source.rfind("#if defined(" + GUARD + ")",
                                     0, source.index(CALL_BEGIN))
    for start, marker in ((beginning_of_helper, HELPER_BEGIN),
                          (beginning_of_call, CALL_BEGIN)):
        if start < 0:
            raise AssertionError("Round043 default-off real ingress guard absent")
        conditions = source[start:source.index(marker)]
        for required in (
            "defined(" + GUARD + ")",
            "defined(SWAPZ_ROUND041_DM_TARGET_INTERVAL_MAP_NONAUTHORITY_TEST)",
            "defined(SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST)",
            "defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY)",
        ):
            if required not in conditions:
                raise AssertionError("Round043 source guard not nested: " + required)
    for required in (
        "static __used noinline int swapz_round043_dm_observe_real_map_v1(",
        "target->private != ctx",
        "ctx->target != target",
        "bio_sectors(upper_bio) != SWAPZ_SECTORS",
        "upper_bio->bi_flags & (1U << BIO_CLONED)",
        "target_relative_sector = upper_bio->bi_iter.bi_sector",
        "target_relative_sector >= target->len",
        "target_relative_sector / SWAPZ_SECTORS >= ctx->logical_pages",
        "kmalloc(SWAPZ_MAX_COMPRESSED, GFP_ATOMIC)",
        "swapz_ci_bio_snapshot_lz4_v1(",
        "private_compressed_bytes",
        "source_view.source_slot_epoch",
        "source_view.stored_entry_identity",
        "source_view.original_sha256",
        "swapz_crc32c_bytes(private_compressed_bytes,",
        "error = -EOPNOTSUPP;\n\nscrub_private:",
        "memzero_explicit(private_compressed_bytes, SWAPZ_MAX_COMPRESSED);",
        "kfree(private_compressed_bytes);",
        "memzero_explicit(&source_view, sizeof(source_view));",
    ):
        if required not in helper:
            raise AssertionError("Round043 real helper missing negative check: " +
                                 required)
    if not (callsite.count(
            "(void)swapz_round043_dm_observe_real_map_v1(ti, ctx, bio);") == 1 and
            "bio_op(bio) == REQ_OP_WRITE" in callsite and
            "count == SWAPZ_SECTORS" in callsite and
            "bio->bi_iter.bi_size == SWAPZ_BLOCK_BYTES" in callsite):
        raise AssertionError("Round043 true map callsite changed ordinary admission")
    # Check executable tokens only. The REAL C explanatory comment
    # correctly says "swapz_map() uses target-relative sectors"; matching
    # that comment caused the first historical false-positive RED before
    # either GCC or Clang source compilation. Never weaken the real-I/O ban.
    executable = re.sub(r"/\*.*?\*/|//[^\n]*", "",
                        helper + "\n" + callsite, flags=re.DOTALL)
    for forbidden in (
        "return DM_MAPIO_", "bio_endio(", "submit_bio(",
        "swapz_lower_write(", "swapz_lower_read(",
        "swapz_map(", "entry->", "ctx->authority.maps[",
        "ctx->authority.gc_destination =", "swapz_gc(",
    ):
        if forbidden in executable:
            raise AssertionError("Round043 witness mutates mapped product: " +
                                 forbidden)
    if source.count("SWAPZ_ROUND043_SOURCE_MAPPED_AUTHENTICATED 0U") != 1:
        raise AssertionError("Round043 source authentication accidentally enabled")
    return helper, callsite


# Round030's exact C fixture retains its textual main under
# "#define main swapz_round030_fixture_main". The separately compiled and
# already-passing Round041 fixture owns the second textual main, which calls
# the complete Round040 predecessor. Rename only THIS function definition.
ROUND041_EXECUTABLE_ENTRY = (
    "int main(void)\n"
    "{\n"
    "\tunsigned int extent_blocks, fault;\n"
    "\n"
    "\tassert(round040_fixture_main() == 0);"
)


def rename_inherited_round041_entrypoint(inherited: str) -> str:
    """Preserve the Round030 macro wrapper and every prior executable suite."""
    round030_rename = "#define main swapz_round030_fixture_main\n"
    round030_end = "#undef main\n"
    if inherited.count("int main(void)") != 2:
        raise AssertionError("Round045 nested Round030/041 textual mains drift")
    for token in (
        round030_rename, round030_end, ROUND041_EXECUTABLE_ENTRY,
        "int round040_fixture_main(void)",
        "round040_test_reissue(extent_blocks, fault);",
        "round041_target_negative_case(extent_blocks, fault);",
        "fault <= 51U", "fault < 50U",
        "ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS",
        "ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS",
    ):
        if inherited.count(token) != 1:
            raise AssertionError("Round045 inherited real C suite drift: " + token)
    macro_start = inherited.index(round030_rename)
    first_textual_main = inherited.index("int main(void)")
    macro_end = inherited.index(round030_end)
    actual_round041_main = inherited.index(ROUND041_EXECUTABLE_ENTRY)
    if not (macro_start < first_textual_main < macro_end <
            actual_round041_main):
        raise AssertionError("Round045 Round030 macro ownership/main order drift")
    renamed = replace_unique(
        inherited, ROUND041_EXECUTABLE_ENTRY,
        ROUND041_EXECUTABLE_ENTRY.replace(
            "int main(void)", "int round041_fixture_main(void)", 1))
    if (renamed.count("int main(void)") != 1 or
            renamed.count("int round041_fixture_main(void)") != 1 or
            renamed.count("round040_fixture_main() == 0") != 1):
        raise AssertionError("Round045 predecessor test dispatch lost")
    return renamed


def compose_actual_production_c() -> str:
    source = TARGET.read_text(encoding="utf-8")
    helper, callsite = validate_real_map_ingress(source)
    previous = runpy.run_path(str(PREVIOUS),
                              run_name="round041_fixture_import")
    prior_compose = previous["compose_actual_production_c"]
    inherited = rename_inherited_round041_entrypoint(prior_compose())
    # Only adapt HOST layout to exact original kernel C field shape. The real
    # Kbuild uses its actual kernel include/linux/bio.h and dm_target.
    inherited = replace_unique(
        inherited,
        "\tunsigned int bi_vcnt, bi_opf, bi_swap_origin;",
        "\tunsigned int bi_vcnt, bi_opf, bi_swap_origin, bi_flags;"
    )
    inherited = replace_unique(
        inherited,
        "struct swapz_dm {\n\tstruct dm_target *target;\n",
        "struct swapz_dm {\n\tstruct dm_target *target;\n"
        "\tswapz_u32 logical_pages;\n"
    )
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, replacement in (
        ("/* ROUND043_INHERIT_REAL_PRIOR_SOURCE */", inherited),
        ("/* ROUND043_EXTRACT_ACTUAL_DM_INGRESS_HELPER */", helper),
        ("/* ROUND043_EXTRACT_ACTUAL_SWAPZ_MAP_CALLSITE */", callsite),
    ):
        fixture = replace_unique(fixture, marker, replacement)
    # The first raw C main is protected by the inherited Round030
    # macro. The final unguarded main belongs ONLY to the new Round043
    # fixture, and must dispatch the complete Round041 predecessor chain.
    if (fixture.count("int main(void)") != 2 or
            fixture.count("int round041_fixture_main(void)") != 1 or
            fixture.count("assert(round041_fixture_main() == 0);") != 1):
        raise AssertionError("Round045 actual C executable main chain drift")
    for required in ("fault < 30U", "round041_fixture_main()",
                     "ROUND043_REAL_PRODUCT_MAP_INGRESS_90_NO_AUTHORITY_PASS",
                     "assert(round043_real_map_observation_calls ==",
                     "memzero_explicit(source_lz4_bytes,",
                     "assert(!memcmp(header_before, mock_physical_header,"):
        if required not in fixture:
            raise AssertionError("Round043 host weakened original/no-I/O checks: " +
                                 required)
    return fixture


class ActualOriginalDmIngressTests(unittest.TestCase):
    def test_nested_round030_round041_main_chain_mutations_fail_closed(self) -> None:
        """Reject executable-main/call-chain drops, not the valid macro main."""
        previous = runpy.run_path(str(PREVIOUS), run_name="round041_main_import")
        inherited = previous["compose_actual_production_c"]()
        renamed = rename_inherited_round041_entrypoint(inherited)
        self.assertEqual(inherited.count("int main(void)"), 2)
        self.assertEqual(renamed.count("int main(void)"), 1)
        self.assertIn("int round041_fixture_main(void)", renamed)
        self.assertIn("assert(round040_fixture_main() == 0);", renamed)
        hostile_mutations = (
            ("#define main swapz_round030_fixture_main",
             "#define main"),
            ("#undef main", "#undef unrelated_entry"),
            ("assert(round040_fixture_main() == 0);",
             "assert(1);"),
            ("fault < 50U", "fault < 1U"),
            ("fault <= 51U", "fault <= 1U"),
            ("ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS",
             "ROUND040_OLD_CHAIN_SKIPPED"),
            ("ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS",
             "ROUND041_OLD_MATRIX_SKIPPED"),
            ("int main(void)", "int omitted_round030_main(void)"),
        )
        for original, hostile in hostile_mutations:
            with self.subTest(mutation=hostile):
                self.assertEqual(inherited.count(original), 1 if
                                 original != "int main(void)" else 2)
                mutant = inherited.replace(original, hostile, 1)
                with self.assertRaisesRegex(AssertionError, "Round045"):
                    rename_inherited_round041_entrypoint(mutant)
        with self.assertRaisesRegex(AssertionError, "Round045"):
            rename_inherited_round041_entrypoint(
                inherited + "\nint main(void) { return 0; }\n")
        print("ROUND045_NESTED_REAL_ROUND030_040_041_ENTRYPOINT_9_MUTANTS_REJECTED_PASS")

    def test_hostile_real_map_source_mutations_fail_closed(self) -> None:
        real_source = TARGET.read_text(encoding="utf-8")
        validate_real_map_ingress(real_source)
        for original, hostile in (
            ("kmalloc(SWAPZ_MAX_COMPRESSED, GFP_ATOMIC)",
             "kmalloc(SWAPZ_MAX_COMPRESSED, GFP_KERNEL)"),
            ("upper_bio->bi_flags & (1U << BIO_CLONED)",
             "upper_bio->bi_flags & 0U"),
            ("error = -EOPNOTSUPP;\n\nscrub_private:",
             "error = 0;\n\nscrub_private:"),
            ("memzero_explicit(private_compressed_bytes, SWAPZ_MAX_COMPRESSED);",
             "/* forgotten private scrub */"),
            ("(void)swapz_round043_dm_observe_real_map_v1(ti, ctx, bio);",
             "return swapz_round043_dm_observe_real_map_v1(ti, ctx, bio);"),
            ("target_relative_sector = upper_bio->bi_iter.bi_sector",
             "target_relative_sector = target->begin + upper_bio->bi_iter.bi_sector"),
            (CALL_END, "swapz_map(ti, bio);\n" + CALL_END),
        ):
            with self.subTest(mutant=hostile):
                self.assertEqual(real_source.count(original), 1)
                mutant = real_source.replace(original, hostile, 1)
                with self.assertRaisesRegex(AssertionError, "Round043"):
                    validate_real_map_ingress(mutant)
        print("ROUND043_REAL_MAP_CALLSITE_HOSTILE_7_MUTANTS_REJECTED_PASS")

    def test_genuine_product_map_ingress_gcc_clang_asan_ubsan(self) -> None:
        source = compose_actual_production_c()
        for compiler in ("gcc", "clang"):
            self.assertIsNotNone(shutil.which(compiler), compiler)
        with tempfile.TemporaryDirectory(prefix="round043-dm-map-source-") as directory:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    c_file = Path(directory) / (compiler + ".c")
                    codec_object = Path(directory) / (compiler + "-codec.o")
                    executable = Path(directory) / compiler
                    c_file.write_text(source, encoding="utf-8")
                    flags = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                        "-pthread", "-I", str(CODEC.parent),
                    ]
                    codec = subprocess.run(
                        [*flags, "-Wno-conversion", "-c", str(CODEC),
                         "-o", str(codec_object)],
                        capture_output=True, text=True, timeout=90)
                    self.assertEqual(
                        codec.returncode, 0,
                        "FIRST inherited codec compiler error:\n" +
                        codec.stderr[-12000:])
                    built = subprocess.run(
                        [*flags, str(c_file), str(codec_object),
                         "-llz4", "-lcrypto", "-o", str(executable)],
                        capture_output=True, text=True, timeout=150)
                    self.assertEqual(
                        built.returncode, 0,
                        "FIRST ACTUAL production swapz_map C compiler error:\n" +
                        built.stderr[-18000:])
                    ran = subprocess.run(
                        [str(executable)],
                        capture_output=True, text=True, timeout=180,
                        env={**os.environ,
                             "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        ran.returncode, 0,
                        "FIRST Round043 real C sanitizer/assertion error:\n" +
                        ran.stdout[-6000:] + ran.stderr[-18000:])
                    for expected in (
                        "ROUND040_ACTUAL_DM_SAME_SLOT_REISSUE_2_SOURCE_SHA_GC_READ_NO_GO_PASS",
                        "ROUND041_ACTUAL_DM_TARGET_INTERVAL_TABLE_GC_TEARDOWN_150_NO_AUTHORITY_PASS",
                        EXPECTED,
                    ):
                        self.assertIn(expected, ran.stdout)
                    print("ROUND043_REAL_PRODUCT_MAP_INGRESS_" +
                          compiler.upper() + "_STRICT_ASAN_UBSAN_PASS")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("host-test", "hostile-self-test"))
    mode = parser.parse_args().mode
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        ActualOriginalDmIngressTests)
    if mode == "hostile-self-test":
        suite = unittest.TestSuite([
            ActualOriginalDmIngressTests(
                "test_hostile_real_map_source_mutations_fail_closed"),
            ActualOriginalDmIngressTests(
                "test_nested_round030_round041_main_chain_mutations_fail_closed"),
        ])
    raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(
        suite).wasSuccessful() else 1)
