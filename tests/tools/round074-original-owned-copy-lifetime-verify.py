#!/usr/bin/env python3
"""Round074 Agent5 source-linked compressed-copy ownership host qualification.

Compile actual unchanged src/kernel/authority.c + codec.c and execute the
new source→owned→queued-BIO-model→guarded-real-authority→pinned-read tests
under GCC and Clang strict ASan/UBSan, then independently compile/execute
ten semantic changes to the NEW owner fixture and three changes to the
ACTUAL product authority.c. Only runtime semantic rejection counts as a
mutant kill. Nothing claims authentic MM source, physical durability or ACK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
FIXTURES = ROOT / "tests/runtime/native/fixtures"
OWNED = FIXTURES / "round074-original-owned-copy-lifetime.c"
ACTUAL_AUTHORITY = KERNEL / "authority.c"
ACTUAL_CODEC = KERNEL / "codec.c"
ORIGINAL_HARNESS = FIXTURES / "round067-import-disk-payload-read.c"
ORIGINAL_HEADER = KERNEL / "zswap-import-codec.h"

HISTORICAL_COMMIT = "22fbdd0090e302bd17b3811145395ceb0a814a6c"
HISTORICAL_BLOBS = {
    "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
}
# Current C differs by reviewed Round089 publication/guard changes. Retain
# historical pins and run all original semantic negatives on CURRENT C.
PINNED_BLOBS = HISTORICAL_BLOBS | {
    "authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
}

FIXTURE_MUTANTS = (
    ("source-lease-auth", "if (!lease_held)", "if (lease_held)"),
    ("short-copy-guard",
     "if (available_bytes < spec->compressed_length)",
     "if (available_bytes > spec->compressed_length)"),
    ("copy-exact-compressed-original",
     "memcpy(owned->bytes, source, spec->compressed_length);",
     "memcpy(owned->bytes, source + 1, spec->compressed_length);"),
    ("verify-owned-crc",
     "if (owned->compressed_crc32c != spec->compressed_crc32c)",
     "if (owned->compressed_crc32c == spec->compressed_crc32c)"),
    ("seal-original-ownership",
     "owned->owns_bytes = true;", "owned->owns_bytes = false;"),
    ("reject-borrowed",
     "if (!owned->owns_bytes)", "if (owned->owns_bytes)"),
    ("reject-stale-source-generation",
     "if (owned->store_generation != spec->source_store_generation ||",
     "if (owned->store_generation == spec->source_store_generation ||"),
    ("reject-short-queued-payload",
     "if (owned->length != spec->compressed_length)",
     "if (owned->length == spec->compressed_length)"),
    ("queue-must-own-not-borrow",
     "memcpy(queued->bytes, owned->bytes, owned->length);",
     "memcpy(queued->bytes, source_bytes, owned->length);"),
    ("callback-must-use-bio-not-erased-source",
     "memcpy(destination, queued->bytes, queued->extent_bytes);",
     "memcpy(destination, source_bytes, queued->extent_bytes);"),
    ("once-only-lower-callback",
     "if (queued->complete)", "if (!queued->complete)"),
)

REAL_C_MUTANTS = (
    ("actual-source-write-compressed-crc",
     "record->spec.compressed_crc32c)\n\t\t\terror = -EBADMSG; /* round067_write_compressed_crc */",
     "record->spec.compressed_crc32c)\n\t\t\terror = 0; /* round067_write_compressed_crc */"),
    ("actual-source-original-codec-GC-identity",
     "previous->spec.codec != spec->codec ||",
     "previous->spec.codec == spec->codec ||"),
    ("actual-read-GC-epoch-identity",
     "expected->gc_epoch != observed->gc_epoch || /* round067_gc_epoch */",
     "expected->gc_epoch == observed->gc_epoch || /* round067_gc_epoch */"),
)

EXPECTED_CASES = (
    "original_lz4_owned_after_erase",
    "original_lzo1x_owned_after_erase",
    "borrowed_and_short_source_rejected",
    "cross_epoch_and_tampered_queue_rejected",
    "short_lower_and_duplicate_callback_rejected",
    "original_lz4_GC_byte_identity_reader_pin",
)
EXPECTED_SUMMARY = (
    "PASS round074_ownership_source_linked_cases=6 "
    "actual_authority_C=YES codecs=original_LZO1X_LZ4 "
    "full_original_bytes=4096 owned_bio_bytes=MODEL "
    "source_erase_before_completion=YES gc_byte_identity=YES "
    "reader_pin_last_put=YES upper_ACK=NONE physical=NONE "
    "import_ACTIVE0=YES AUTH0 PHASE_A=BLOCKED"
)

class SourceFailure(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise SourceFailure(reason)


def blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data
    ).hexdigest()


def one_mutation(source: str, old: str, new: str, name: str) -> str:
    require(source.count(old) == 1, "mutation-anchor-drift:" + name)
    return source.replace(old, new, 1)


def check_source_baseline(fixture: str, actual: str) -> None:
    require(
        fixture.count('#include "round067-import-disk-payload-read.c"') == 1,
        "source-linked-actual-product-harness-absent")
    require(
        fixture.count("round074_lower_complete_once(") >= 4,
        "modeled-lower-ownership-not-exercised")
    require("memset(source_bytes, 0xc3, sizeof(source_bytes));" in fixture,
            "source-erase-before-completion-not-tested")
    require("memset(owned.bytes, 0xa6, sizeof(owned.bytes));" in fixture,
            "owned-scratch-erase-before-completion-not-tested")
    require("swapz_import_disk_pin(&pool, original_ticket," in fixture,
            "actual-authority-old-reader-pin-not-used")
    require("swapz_import_disk_put(&pool, original_ticket)" in fixture,
            "last-pin-retirement-not-verified")
    require("swapz_import_disk_stage(&pool" in ORIGINAL_HARNESS.read_text(),
            "genuine-dormant-product-allocator-not-used")
    require("swapz_import_disk_complete_payload" in actual,
            "actual-product-lower-completion-source-missing")
    require("swapz_import_disk_read_pinned" in actual,
            "actual-product-pinned-GC-read-source-missing")
    require(len(EXPECTED_CASES) == 6 and
            all(fixture.count('"' + name + '"') == 1
                for name in EXPECTED_CASES), "case-set-drift")
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in
            ORIGINAL_HEADER.read_text(), "real-original-source-activation-drift")
    require("#define SWAPZ_IMPORT_DISK_ACTIVE 0U" in
            (KERNEL / "authority.h").read_text(),
            "real-import-activation-drift")
    for file_name, expected in HISTORICAL_BLOBS.items():
        result = subprocess.run(["git", "--no-replace-objects", "show",
                                 HISTORICAL_COMMIT + ":src/kernel/" + file_name],
                                cwd=ROOT, capture_output=True, timeout=60, check=False)
        require(result.returncode == 0 and blob(result.stdout) == expected,
                "historical-product-blob:" + file_name)
    for file_name, expected in PINNED_BLOBS.items():
        require(blob((KERNEL / file_name).read_bytes()) == expected,
                "unmodified-real-product-blob:" + file_name)
    for name, old, new in FIXTURE_MUTANTS:
        one_mutation(fixture, old, new, name)
    for name, old, new in REAL_C_MUTANTS:
        one_mutation(actual, old, new, name)


def compile_fixture(compiler: str, source: str, authority: str,
                    directory: Path, variant: str) -> Path:
    compiler_path = shutil.which(compiler)
    require(compiler_path is not None,
            "compiler-unavailable:" + compiler)
    fixture_path = directory / "round074-original-owned-copy-lifetime.c"
    actual_authority_path = directory / "authority.c"
    executable = directory / (compiler + "-" + variant)
    fixture_path.write_text(source)
    actual_authority_path.write_text(authority)
    flags = [
        "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
        "-Wshadow", "-Werror", "-Werror=implicit-fallthrough",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
        "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
        "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST",
        "-I", str(FIXTURES), "-I", str(KERNEL),
    ]
    process = subprocess.run(
        [compiler_path, *flags, str(fixture_path), str(actual_authority_path),
         str(ACTUAL_CODEC), "-o", str(executable),
         "-llzo2", "-llz4", "-lcrypto"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
        check=False)
    if process.returncode:
        diagnostic = next((line for line in process.stderr.splitlines()
                           if "error:" in line), process.stderr[:220])
        raise SourceFailure(
            "actual-source-compile:" + compiler + ":" + variant +
            ":" + re.sub(r"(?:/[^:\s]+)+/", "src/", diagnostic)[:240])
    return executable


def execute(executable: Path, compiler: str, variant: str,
            expect_mutant: bool) -> None:
    environment = {
        **os.environ,
        "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
    }
    result = subprocess.run(
        [str(executable)], cwd=ROOT, env=environment,
        capture_output=True, text=True, timeout=60, check=False)
    require(result.returncode >= 0 and
            "AddressSanitizer" not in result.stderr and
            "runtime error:" not in result.stderr,
            "sanitizer-or-signal:" + compiler + ":" + variant)
    if expect_mutant:
        require(result.returncode == 3 and
                "ROUND074_FIRST_ERROR case=" in result.stderr and
                not result.stdout,
                "compiled-executed-semantic-mutant-survived:" +
                compiler + ":" + variant +
                ":exit=" + str(result.returncode))
    else:
        require(result.returncode == 0 and
                result.stdout.strip() == EXPECTED_SUMMARY and
                not result.stderr,
                "baseline-real-authority-case-failed:" + compiler +
                ":exit=" + str(result.returncode) +
                ":first=" + result.stderr[:160])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None,
                        help="Optional bounded exact-source machine report")
    args = parser.parse_args()
    source = OWNED.read_text()
    authority = ACTUAL_AUTHORITY.read_text()
    check_source_baseline(source, authority)
    report: dict[str, object] = {
        "source": "round074-current-actual-authority-src-kernel-reviewed-round089",
        "historical_commit": HISTORICAL_COMMIT,
        "historical_blobs": HISTORICAL_BLOBS,
        "current_blobs": PINNED_BLOBS,
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "native_original_uml": "NOT_EXECUTED",
        "actual_physical_fua": False,
        "actual_upper_ack": False,
        "model_only_source_lease_and_bio_queue": True,
        "cases_per_compiler": len(EXPECTED_CASES),
        "mutants_per_compiler": len(FIXTURE_MUTANTS) + len(REAL_C_MUTANTS),
        "compilers": {},
    }
    with tempfile.TemporaryDirectory(prefix="swapz-round074-owned-source-") as name:
        temporary = Path(name)
        for compiler in ("gcc", "clang"):
            directory = temporary / compiler
            directory.mkdir()
            binary = compile_fixture(
                compiler, source, authority, directory, "baseline")
            execute(binary, compiler, "baseline", False)
            print("PASS " + compiler + " " + EXPECTED_SUMMARY, flush=True)
            count = 0
            for mutant, old, new in FIXTURE_MUTANTS:
                variant = one_mutation(source, old, new, mutant)
                executable = compile_fixture(
                    compiler, variant, authority, directory, mutant)
                execute(executable, compiler, mutant, True)
                count += 1
            for mutant, old, new in REAL_C_MUTANTS:
                variant = one_mutation(authority, old, new, mutant)
                executable = compile_fixture(
                    compiler, source, variant, directory, mutant)
                execute(executable, compiler, mutant, True)
                count += 1
            require(count == 14, "mutant-count-not-14:" + compiler)
            print("PASS " + compiler +
                  " round074_ownership_strict_ASAN_UBSAN=YES "
                  "original_profile_cases=6 actual_product_linked=YES "
                  "executed_semantic_mutants=14 real_product_C_mutants=3 "
                  "native_uml=NOT_EXECUTED AUTH0", flush=True)
            report["compilers"][compiler] = {
                "status": "PASS", "cases": 6, "semantic_mutants_killed": 14,
                "actual_product_C_mutants_killed": 3,
                "sanitizers": ["address", "undefined"],
            }
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS round074_ownership_source_exact_GCC_Clang "
          "host_cases=12 compiled_executed_C_mutants=28 "
          "real_product_mutants=6 actual_native_UML=NOT_EXECUTED "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (SourceFailure, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print("ROUND074_HOST_FIRST_ERROR " + str(error)[:360], file=sys.stderr)
        sys.exit(1)
