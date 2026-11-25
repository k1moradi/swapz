#!/usr/bin/env python3
"""Exact original-source joined native test preflight, strict C host evidence.

This checks pinned original fixture composition and executes existing GCC and
Clang ASan+UBSan compiled/executed source-C mutants for real product authority,
original source-slot predicate, and true independent decoder owner lifetime.
Native original mm/zswap and block/bio linked KUnit is a SEPARATE CI job.
"""
import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round072-original-mm-bio-authority-decoder-joined.cfrag"
STAGER = ROOT / "tests/tools/round072-stage-original-mm-bio-authority-decoder-joined.py"


def require(condition: bool, label: str) -> None:
    if not condition:
        raise RuntimeError("ROUND072_JOIN_FIRST_ERROR " + label)


def main() -> None:
    fixture = FIXTURE.read_text()
    require(fixture.count("kunit_test_suite(swapz_round072_native_joined_suite);") == 1,
            "joined-original-KUnit-not-unique")
    require(fixture.count('swapz_round069_capture_stored(') == 1,
            "original-LZ4-XArray-zsmalloc-not-reused")
    require("swapz_round072_capture_lzo_source" in fixture,
            "original-LZO-XArray-zsmalloc-not-reused")
    for name in (
            "swapz_round072_joined_original_lz4_kunit",
            "swapz_round072_joined_original_lzo1x_kunit",
            "swapz_round072_joined_original_gc_reader_kunit",
            "swapz_round072_joined_native_lower_errors_kunit",
            "swapz_round069_native_gc_copy_fua(",
            "swapz_round069_run_io(",
            "swapz_zswap_import_decoder_owner_decode(",
            "swapz_round072_erase_source(source, &owned);",
            "ROUND072_NATIVE_JOIN_FIRST_ERROR",
            "swapz_import_lower_end_read(",
            "model_authority.upper_write_ack_count = 1U; /* MODEL, not product ACK */",
            "zs_obj_read_sg_begin(",
            "zs_free(source->allocator, source->handle);",
    ):
        require(name in fixture, "missing-original-joined-boundary:" + name)
    require("submit_bio(" not in fixture, "real-physical-bio-forbidden")
    require("bio_endio(" not in fixture, "manual-second-native-endio-forbidden")
    for path in (
            "tests/tools/round072-stage-original-mm-bio-authority-decoder-joined.py",
            "tests/tools/round069-stage-original-zswap-stored-source.py",
            "tests/tools/round058-original-stored-bio-chain.py",
    ):
        ast.parse((ROOT / path).read_text())
    # Keep frozen native composition provenance separate from current actual
    # host execution; do not substitute a historical binary for the host test.
    actual = ROOT / "src/kernel"
    historical_commit = "22fbdd0090e302bd17b3811145395ceb0a814a6c"
    historical_pins = {
        "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
        "zswap-import-decoder-owner.c":
            "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    }
    for name, expected in historical_pins.items():
        result = subprocess.run(["git", "--no-replace-objects", "show",
                                 historical_commit + ":src/kernel/" + name],
                                cwd=ROOT, capture_output=True, timeout=60, check=False)
        require(result.returncode == 0, "historical-product-unavailable:" + name)
        content = result.stdout
        historical_blob = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") +
            b"\0" + content).hexdigest()
        require(historical_blob == expected, "historical-product-C-blob:" + name)
    pinned = historical_pins | {"authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3"}
    for name, expected in pinned.items():
        content = (actual / name).read_bytes()
        blob = hashlib.sha1(
            b"blob " + str(len(content)).encode("ascii") +
            b"\0" + content).hexdigest()
        require(blob == expected, "actual-product-C-blob:" + name)
    print("PASS round072_original_MM_XArray_zsmalloc_to_real_BIO_endio_"
          "historical_native_and_current_host_product_pins=CHECKED "
          "native=SEPARATE_KUNIT AUTH=0 PHASE_A=BLOCKED", flush=True)
    runs = (
        ("source",
         ["tests/tools/round069-original-zswap-stored-source-verify.py"],
         ("ROUND069_GCC_SOURCE_ASAN_UBSAN_PASS scenarios=16 "
          "compiled_executed_C_semantic_mutants=10",
          "ROUND069_CLANG_SOURCE_ASAN_UBSAN_PASS scenarios=16 "
          "compiled_executed_C_semantic_mutants=10")),
        ("authority",
         ["tests/tools/round069-original-bio-authority-joined-verify.py"],
         ("PASS gcc compiled_and_executed_changed_real_C_mutants=14",
          "PASS clang compiled_and_executed_changed_real_C_mutants=14",
          "PASS gcc real_source_GC_original_codec_guard_ASAN_UBSAN=1",
          "PASS clang real_source_GC_original_codec_guard_ASAN_UBSAN=1")),
        ("decoder",
         ["tests/tools/round066-decoder-drain-release-verify.py",
          "--owner-source", "src/kernel/zswap-import-decoder-owner.c",
          "--owner-header", "src/kernel/zswap-import-decoder-owner.h"],
         ("ROUND066_DRAIN_GCC_CLANG_ASAN_UBSAN_PASS baselines=2 "
          "compiled_executed_semantic_mutants=4",)),
    )
    for scope, command, expected_lines in runs:
        process = subprocess.run(
            [sys.executable, "-B", str(ROOT / command[0]), *command[1:]],
            cwd=ROOT, env={
                **os.environ,
                "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            }, text=True, capture_output=True, timeout=1200, check=False)
        if (process.returncode or process.stderr or
                any(expected not in process.stdout for expected in expected_lines)):
            first = next((line for line in process.stderr.splitlines()
                          if "FIRST_ERROR" in line or "error:" in line),
                         process.stderr[:120] or "missing-expected-host-evidence")
            raise RuntimeError("ROUND072_JOIN_FIRST_ERROR " + scope +
                               " exact-source-host exit=" +
                               str(process.returncode) + " first=" +
                               re.sub(r"(?:/[^:\s]+)+/", "source/",
                                      first)[:240])
        for line in process.stdout.splitlines():
            if ("PASS" in line and "ROUND066_DRAIN_CASE_PASS" not in line):
                print("PASS round072-inherited-" + scope + " " +
                      line[:240], flush=True)
    print("PASS round072_original_join_strict_GCC_Clang_ASAN_UBSAN "
          "original_source_mutants=10_each real_authority_mutants=16_each "
          "decoder_lifetime_mutants=2_each "
          "all_compiled_executed=YES pinned_original_KUnit=SEPARATE_JOB",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, SyntaxError,
            subprocess.TimeoutExpired) as error:
        print("FIRST_ERROR round072-original-native-join: " +
              str(error)[:350], file=sys.stderr)
        sys.exit(1)
