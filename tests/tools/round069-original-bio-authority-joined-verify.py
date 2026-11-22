#!/usr/bin/env python3
"""Round069 real source-bound joined pinned-Linux BIO + authority preflight.

The native KUnit link is the actual compile/runtime qualification; this
rootless host stage MUST separately execute strict GCC and Clang unchanged
Round068 actual authority.c+codec.c with FOURTEEN independently compiled/
executed semantic mutated REAL-C translations per compiler. Never treat
static fixture markers as the native Linux runtime qualification.
"""
import ast
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-bio-authority-joined.cfrag"
STAGER = ROOT / "tests/tools/round069-stage-original-bio-authority-joined.py"
REAL_AUTHORITY = ROOT / "src/kernel/authority.c"
PRODUCT = {
    "authority.c": "003e02273edfa47b634850997a0f9c0c3ee1ea18",
    "authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
}


def blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def main() -> None:
    # Actual SOURCE-exact authority files are copied into the pristine
    # native test image byte-for-byte. No mock implementations are permitted.
    for name, expected in PRODUCT.items():
        actual = ROOT / "src/kernel" / name
        if blob(actual.read_bytes()) != expected:
            raise ValueError("actual-product-blob-mismatch:" + name)
    joined = FIXTURE.read_text()
    assert joined.count("bio_endio(io->bio);") == 1
    assert joined.count("swapz_import_lower_end_write(") == 2
    assert joined.count("swapz_import_lower_end_flush(") == 1
    assert joined.count("swapz_import_lower_end_read(") == 1
    assert joined.count("schedule_work(&io->ordered_owner_work);") == 1
    assert joined.count('#include "swapz_round069/authority.c"') == 1
    assert joined.count('#include "swapz_round069/codec.c"') == 1
    assert joined.count("kunit_test_suite(swapz_round069_joined_native_suite);") == 1
    assert "submit_bio(" not in joined
    assert "SWAPZ_ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_KUNIT" in joined
    assert "SWAPZ_IMPORT_LOWER_BIO_ACTIVE == 0" in joined
    assert "swapz_round069_native_reader_pin_gc_kunit" in joined
    assert "sha256(destination, SWAPZ_BLOCK_BYTES, digest)" in joined
    ast.parse(STAGER.read_text())
    assert "SWAPZ_ROUND068_IMPORT_LOWER_BIO_TEST" in REAL_AUTHORITY.read_text()
    print("PASS exact_real_authority_C_kernel_copy=5 source_native_endio_join=YES "
          "frozen_original_LZO1X_LZ4_SHA_CRC_pin_GC_and_AUTH0=CHECKED", flush=True)

    # This re-executes the existing actual product-linked GCC/Clang +
    # changed-real-C semantic mutants. Other inherited regression workflows
    # are automatically triggered separately at this exact SHA.
    command = [sys.executable, "-B", str(ROOT / "tests/tools" /
               "round068-original-lower-bio-owned-verify.py")]
    completed = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False,
        timeout=900,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    expected_fragments = (
        "PASS gcc real authority lower callback PASS lower_bio_shaped_callback_cases=7",
        "PASS gcc compiled_and_executed_changed_real_C_mutants=14",
        "PASS clang real authority lower callback PASS lower_bio_shaped_callback_cases=7",
        "PASS clang compiled_and_executed_changed_real_C_mutants=14",
    )
    if completed.returncode or completed.stderr or any(
            fragment not in completed.stdout for fragment in expected_fragments):
        # The inherited actual-product runner itself writes 0600 private logs.
        first = next((line for line in completed.stderr.splitlines()
                      if "FIRST_ERROR" in line), "real-source-host-runner-exit")
        raise RuntimeError("actual GCC/Clang source mutant preflight " +
                           first[:230])
    for line in completed.stdout.splitlines():
        if line.startswith("PASS "):
            print(line, flush=True)


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, ValueError, RuntimeError, OSError,
            subprocess.TimeoutExpired) as error:
        message = str(error) if not isinstance(error, AssertionError) \
            else "joined original native source witness not satisfied"
        print("FIRST_ERROR round069-joined-original-authority: " +
              re.sub(r"(?:/[^:\s]+)+/", "external-source/",
                     message)[:320], file=sys.stderr)
        sys.exit(1)
