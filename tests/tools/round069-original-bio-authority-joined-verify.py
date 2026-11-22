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
    "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
}


def blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()



def verify_real_owned_retired_fallthrough(source: str) -> None:
    """Strict real authority.c close/reader-pin source warning + mutant."""
    import shutil

    annotated = (
        "\t\tcase SWAPZ_IMPORT_DISK_OWNED:\n"
        "\t\t\trecord->state = SWAPZ_IMPORT_DISK_RETIRED;\n"
        "\t\t\t/* Preserve the intentional OWNED-to-RETIRED close transition. */\n"
        "\t\t\t/* fall through */\n"
        "\t\t\t__attribute__((__fallthrough__));\n"
        "\t\tcase SWAPZ_IMPORT_DISK_RETIRED:"
    )
    if source.count(annotated) != 1:
        raise ValueError("real-authority-retired-transition-not-unique")
    missing = annotated.replace(
        "\t\t\t/* fall through */\n"
        "\t\t\t__attribute__((__fallthrough__));\n",
        "\t\t\t/* deliberately unannotated temporary warning negative */\n")
    broken = annotated.replace(
        "\t\t\t__attribute__((__fallthrough__));",
        "\t\t\tbreak; /* temporary semantic mutation: skip reader accounting */")
    if missing == annotated or broken == annotated:
        raise ValueError("actual-source-fallthrough-mutants-not-applied")
    kernel = ROOT / "src/kernel"
    fixture = ROOT / "tests/runtime/native/fixtures/round067-import-disk-payload-read.c"
    if not fixture.is_file():
        raise ValueError("existing-real-allocator-close-fixture-missing")
    with tempfile.TemporaryDirectory(prefix="swapz-real-retired-") as root:
        temporary = Path(root)
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            if not compiler:
                raise RuntimeError("strict-source-compiler-missing:" + compiler_name)
            actual = temporary / ("authority-" + compiler_name + ".c")
            executable = temporary / ("close-" + compiler_name)
            flags = [
                "-std=gnu11", "-O1", "-g",
                "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
                "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
                "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST",
                "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
                "-Werror=implicit-fallthrough",
                ("-Wimplicit-fallthrough=5" if compiler_name == "gcc"
                 else "-Wimplicit-fallthrough"),
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                "-I", str(kernel)
            ]

            def compile_real(text: str) -> subprocess.CompletedProcess[str]:
                actual.write_text(text)
                return subprocess.run(
                    [compiler, *flags, str(fixture), str(actual),
                     str(kernel / "codec.c"), "-o", str(executable),
                     "-llzo2", "-llz4", "-lcrypto"],
                    cwd=ROOT, capture_output=True, text=True,
                    timeout=100, check=False)

            baseline = compile_real(source)
            if baseline.returncode:
                first = next((line for line in baseline.stderr.splitlines()
                              if "error:" in line), "compiler diagnostic absent")
                raise RuntimeError("strict-actual-authority-compile-" +
                                   compiler_name + ":" + first[-180:])
            environment = {
                **os.environ,
                "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"
            }
            original = subprocess.run(
                [str(executable), "exhausted_and_normal_raw"],
                cwd=ROOT, env=environment, capture_output=True,
                text=True, timeout=75, check=False)
            if original.returncode or original.stdout or original.stderr:
                raise RuntimeError("strict-actual-authority-close-" +
                                   compiler_name + ":exit=" +
                                   str(original.returncode))

            # Only temp compiler-negative C loses the old comment; real C
            # retains all existing comments and the new kernel annotation.
            negative = compile_real(source.replace(annotated, missing, 1))
            if negative.returncode == 0 or "implicit-fallthrough" not in negative.stderr:
                raise RuntimeError("missing-fallthrough-compiler-negative-" +
                                   compiler_name + "-not-rejected")

            semantic = compile_real(source.replace(annotated, broken, 1))
            if semantic.returncode:
                first = next((line for line in semantic.stderr.splitlines()
                              if "error:" in line), "compiler diagnostic absent")
                raise RuntimeError("semantic-close-source-compile-" +
                                   compiler_name + ":" + first[-180:])
            observed = subprocess.run(
                [str(executable), "exhausted_and_normal_raw"],
                cwd=ROOT, env=environment, capture_output=True,
                text=True, timeout=75, check=False)
            if (observed.returncode != 1 or observed.stdout or
                    observed.stderr != "FIRST_ERROR exhausted_and_normal_raw\n"):
                raise RuntimeError("compiled-executed-close-semantic-" +
                                   compiler_name + "-escaped:exit=" +
                                   str(observed.returncode))
            print("PASS " + compiler_name +
                  " genuine_authority_owned_retired_strict_ASAN_UBSAN=1 "
                  "fallthrough_compiler_negative=1 "
                  "compiled_executed_changed_real_C_mutants=1",
                  flush=True)


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

    verify_real_owned_retired_fallthrough(REAL_AUTHORITY.read_text())


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
