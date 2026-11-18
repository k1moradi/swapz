#!/usr/bin/env python3
"""Round034: executable exact production DM slot preflight, no live authorization.

Host replaces only original BIO/mm swap-area/DM authority boundaries. The
real original same-kernel module, swp_type and swp_offset symbols/inline ABI
are separately verified by the true original-Kbuild GitHub Actions job.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "src/kernel/dm-target.c"
CODEC = ROOT / "src/kernel/codec.c"
PRIOR_HOST = ROOT / "tests/runtime/native/fixtures/round033-dm-original-import-host.c"
NEW_HOST = ROOT / "tests/runtime/native/fixtures/round034-dm-source-authority-host.c"
BEGIN_33 = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_START */"
END_33 = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_EXACT_END */"
BEGIN_34 = "/* ROUND034_DM_SOURCE_SLOT_AUTHORITY_EXACT_START */"
END_34 = "/* ROUND034_DM_SOURCE_SLOT_AUTHORITY_EXACT_END */"
GUARDS = (
    "SWAPZ_ROUND034_DM_SOURCE_SLOT_AUTHORITY_TEST",
    "SWAPZ_ROUND033_DM_ORIGINAL_BIO_GPL_LINK_TEST",
    "SWAPZ_ROUND032_DM_LZ4_VIEW_VALIDATE_TEST",
    "SWAPZ_ROUND031_DM_LZ4_SIDECAR_TEST",
    "SWAPZ_ROUND030_DM_COMPRESSED_COMMIT_TEST",
    "SWAPZ_ROUND028_DM_OWNED_READBACK_TEST",
    "SWAPZ_ROUND024_DM_IMPORT_KBUILD_PROBE",
    "SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY",
    "SWAPZ_ROUND031_MM_BIO_SOURCE",
    "SWAPZ_ROUND030_EVICTION_SNAPSHOT_SOURCE",
    "SWAPZ_ROUND028_SLOT_EPOCH_SOURCE",
    "SWAPZ_ROUND025_SIDEBAND_CI_ONLY",
)


def exact_source(source: str, begin: str, end: str) -> str:
    if source.count(begin) != 1 or source.count(end) != 1:
        raise AssertionError("exact guarded DM marker missing or duplicate")
    return source.split(begin, 1)[1].split(end, 1)[0]


def host_source() -> str:
    entire = TARGET.read_text(encoding="utf-8")
    original = exact_source(entire, BEGIN_33, END_33)
    current = exact_source(entire, BEGIN_34, END_34)
    preguard = entire.split(BEGIN_34, 1)[0]
    guard_start = preguard.rfind("#if defined(SWAPZ_ROUND034_DM_SOURCE_SLOT_AUTHORITY_TEST)")
    if guard_start == -1:
        raise AssertionError("round034 source not guarded")
    preconditions = preguard[guard_start:]
    for flag in GUARDS:
        if preconditions.count("defined(" + flag + ")") != 1:
            raise AssertionError("missing original/DM compile guard: " + flag)
    mandatory = (
        "swapz_round033_dm_copy_original_bio_v1_for_link(",
        "swapz_round034_dm_snapshot_candidate(",
        "swapz_round034_dm_source_mechanical_preflight(",
        "swapz_round034_dm_try_authenticate_source_slot(",
        "swp_type(original_entry)",
        "swp_offset(original_entry)",
        "swp_entry(source_type, source_offset)",
        "source_type >= MAX_SWAPFILES",
        "source_bio->bi_vcnt",
        "source_bio->bi_iter.bi_offset",
        "bio_iter_iovec(source_bio, source_bio->bi_iter)",
        "SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK",
        "ctx->target->len - source_sector",
        "candidate_page",
        "SWAPZ_ROUND034_SOURCE_COPY_MECHANICALLY_VALID",
        "SWAPZ_ROUND034_SOURCE_MAPPED_AUTHENTICATED",
        "return -EOPNOTSUPP;",
        "slot->descriptor.source_swap_slot != copied_view.source_swap_entry",
        "slot->descriptor.record.store_generation !=",
        "slot->descriptor.record.stored_entry_identity !=",
        "before.map_generation != after.map_generation",
        "before.extent_sequence != after.extent_sequence",
        "ctx->authority.batch_replaying",
        "ctx->gc_recovery.active",
        "sidecar->closed",
        "slot->descriptor.hypothetical_ack_count != 1U",
        "memzero_explicit(mechanical_candidate, SWAPZ_MAX_COMPRESSED);",
        "memzero_explicit(provider_copy, SWAPZ_MAX_COMPRESSED);",
    )
    for token in mandatory:
        if token not in current:
            raise AssertionError("missing production C source authority gate: " + token)
    for prohibited in ("bio_endio(", "swapz_lower_write(", "swapz_finish(",
                       "swapz_stage(", "get_swap_device("):
        # get_swap_device appears only as explanatory comment, not call.
        if prohibited == "get_swap_device(":
            if current.count(prohibited) != 1:
                raise AssertionError("unsafe original get_swap_device use")
        elif prohibited in current:
            raise AssertionError("live IO activated by Round034 source")
    if entire.count("swapz_round034_dm_try_authenticate_source_slot(") != 1:
        raise AssertionError("Round034 target normal path invokes authority")
    if "SWAPZ_ROUND034_SOURCE_MAPPED_AUTHENTICATED;" in current:
        raise AssertionError("unauthenticated candidate minted as authenticated")
    if '#include <linux/swapops.h>' not in entire:
        raise AssertionError("actual original kernel swp_type/swp_offset header missing")

    prior = PRIOR_HOST.read_text(encoding="utf-8")
    prior_placeholder = "/* ROUND033_DM_ORIGINAL_GPL_IMPORT_HOST_EXACT */"
    if prior.count(prior_placeholder) != 1:
        raise AssertionError("prior source host marker")
    prefix = prior.split(prior_placeholder, 1)[0]
    original_bio = ("struct bio {\n\tbool lifetime_pinned;\n"
                    "\tbool full_uncompressed_4096_swap_write;\n};")
    extended_bio = (
        "struct bio_vec;\n"
        "struct bio {\n"
        "\tbool lifetime_pinned;\n"
        "\tbool full_uncompressed_4096_swap_write;\n"
        "\tstruct { uint64_t bi_sector; unsigned int bi_size, bi_idx, bi_offset; } bi_iter;\n"
        "\tstruct bio_vec *bi_io_vec;\n"
        "\tvoid *bi_bdev;\n"
        "\tunsigned int bi_vcnt, bi_opf, bi_swap_origin;\n};")
    if prefix.count(original_bio) != 1:
        raise AssertionError("original BIO host boundary changed")
    prefix = prefix.replace(original_bio, extended_bio, 1)
    marker = "static int injected_provider_errno, provider_calls;"
    if prefix.count(marker) != 1:
        raise AssertionError("provider fake source changed")
    prefix = prefix.replace(
        marker, marker + "\nstatic void (*provider_after_copy)(void);", 1)
    insertion = "\t*view = original_provider_view;\n\treturn 0;"
    if prefix.count(insertion) != 1:
        raise AssertionError("faked boundary snapshot action changed")
    prefix = prefix.replace(
        insertion,
        "\t*view = original_provider_view;\n"
        "\tif (provider_after_copy)\n"
        "\t\tprovider_after_copy();\n\treturn 0;", 1)
    new_fixture = NEW_HOST.read_text(encoding="utf-8")
    new_marker = "/* ROUND034_EXACT_PRODUCTION_SOURCE */"
    if new_fixture.count(new_marker) != 1:
        raise AssertionError("new fixture source marker missing")
    return prefix + original + "\n" + new_fixture.replace(new_marker, current, 1)


class Round034SourceAuthorityTests(unittest.TestCase):
    def test_exact_original_linux_type_decoder_and_auth_unavailable(self) -> None:
        source = host_source()
        # Original swp_type/offset definitions are taken from the real kernel
        # during same-source production Kbuild; this synthetic host only checks
        # C behavior under a separately mocked swap type boundary.
        self.assertIn("source_type = swp_type(original_entry);", source)
        self.assertIn("source_offset = swp_offset(original_entry);", source)
        self.assertIn("return -EOPNOTSUPP;", source)

    def test_real_dm_c_preflight_gcc_clang_werror_asan_ubsan(self) -> None:
        content = host_source()
        self.assertTrue(shutil.which("gcc"))
        self.assertTrue(shutil.which("clang"))
        with tempfile.TemporaryDirectory(prefix="round034-source-slot-") as work:
            for compiler in ("gcc", "clang"):
                with self.subTest(compiler=compiler):
                    source = Path(work) / (compiler + "-source.c")
                    executable = Path(work) / (compiler + "-slot-test")
                    codec = Path(work) / (compiler + "-codec.o")
                    source.write_text(content, encoding="utf-8")
                    compiler_flags = [
                        compiler, "-std=gnu11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
                        "-Werror", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all",
                        "-fno-omit-frame-pointer", "-I", str(CODEC.parent)]
                    # Historical exception only in old codec.c.
                    old_codec = subprocess.run([
                        *compiler_flags, "-Wno-conversion", "-c",
                        str(CODEC), "-o", str(codec)], text=True,
                        capture_output=True, timeout=70)
                    self.assertEqual(old_codec.returncode, 0,
                                     old_codec.stderr[-7000:])
                    compiled = subprocess.run([
                        *compiler_flags, str(source), str(codec),
                        "-llz4", "-lcrypto", "-o", str(executable)],
                        text=True, capture_output=True, timeout=70)
                    self.assertEqual(
                        compiled.returncode, 0,
                        "First real Round034 source C compiler failure:\n"
                        + compiled.stderr[-9000:])
                    ran = subprocess.run(
                        [str(executable)], text=True, capture_output=True,
                        timeout=70, env={**os.environ,
                            "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                            "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                    self.assertEqual(
                        ran.returncode, 0,
                        "First real Round034 source C sanitizer/assert error:\n"
                        + ran.stderr[-9000:])
                    self.assertIn(
                        "ROUND034_ACTUAL_SOURCE_SLOT_SWP_TYPE_OFFSET_MECHANICAL_ONLY_AUTH_NO_GO_PASS",
                        ran.stdout)


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("host-test",))
    args = parser.parse_args()
    assert args.mode == "host-test"
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(
        Round034SourceAuthorityTests)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
