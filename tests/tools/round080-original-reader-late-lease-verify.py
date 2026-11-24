#!/usr/bin/env python3
"""Round080 test-only original decoder close/late-pin teardown regression.

Compiles actual unchanged product decoder-owner.c and the exact test-only
fixture close expectation with a typed codec stub (not an original codec or
original UML emulation). Native original KUnit separately proves BIO and GC.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
OWNER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
OWNER_HEADER = ROOT / "src/kernel/zswap-import-decoder-owner.h"

CODEC_SHIM = r'''
#ifndef SWAPZ_ZSWAP_IMPORT_CODEC_H
#define SWAPZ_ZSWAP_IMPORT_CODEC_H
#include <stdint.h>
typedef uint8_t swapz_u8;
typedef uint32_t swapz_u32;
#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U
#define SWAPZ_ZSWAP_IMPORT_VERSION 1U
#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U
#define SWAPZ_ZSWAP_IMPORT_LZO1X_VERSION 1U
struct swapz_zswap_import_record { swapz_u8 codec, version; };
struct swapz_zswap_import_read_authority { unsigned int unused; };
static inline int swapz_zswap_import_decode(
    const struct swapz_zswap_import_record *record,
    const struct swapz_zswap_import_read_authority *authority,
    const swapz_u8 *compressed, swapz_u32 compressed_capacity,
    swapz_u8 *scratch, swapz_u32 scratch_capacity,
    swapz_u8 *output, swapz_u32 output_capacity,
    const swapz_u8 *original)
{
    (void)record; (void)authority; (void)compressed;
    (void)compressed_capacity; (void)scratch; (void)scratch_capacity;
    (void)output; (void)output_capacity; (void)original;
    return 0;
}
#endif
'''

HARNESS = r'''
#define SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST 1
#include "zswap-import-decoder-owner.h"
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

ORIGINAL_CLOSE_HELPER

static struct swapz_zswap_import_decoder_owner owner;
static int close_result = -EINPROGRESS;

static void *close_worker(void *argument)
{
    (void)argument;
    close_result = swapz_zswap_import_decoder_owner_close_and_drain(&owner);
    return NULL;
}

static int semantic_failure(const char *phase)
{
    fprintf(stderr, "ROUND080_LATE_LEASE_SEMANTIC_KILL phase=%s\n", phase);
    return 17;
}

int main(void)
{
    struct swapz_zswap_import_decoder_lease original = {0};
    struct swapz_zswap_import_decoder_lease unexpected = {0};
    pthread_t closer;

    if (swapz_zswap_import_decoder_owner_init(&owner,
            SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION) ||
        swapz_zswap_import_decoder_owner_get(&owner, &original))
        return semantic_failure("init-primary");
    /* Deliberately GET before closer sets 'closing' to exercise the
     * previously unbalanced successful late-admission error path. */
    if (swapz_round073_expect_shutdown(&owner, &unexpected) != -EUCLEAN ||
        unexpected.owner || owner.active_readers != 1U)
        return semantic_failure("late-pin-leaked-before-close");
    /* Two actually held pins exercise the exact native failure cleanup. */
    if (swapz_zswap_import_decoder_owner_get(&owner, &unexpected) ||
        owner.active_readers != 2U)
        return semantic_failure("two-held-pins");
    if (swapz_round080_release_decoder_leases(&original, &unexpected) ||
        original.owner || unexpected.owner || owner.active_readers)
        return semantic_failure("shared-native-cleanup");
    if (swapz_round080_release_decoder_leases(&original, &unexpected) ||
        swapz_zswap_import_decoder_owner_get(&owner, &original))
        return semantic_failure("cleanup-idempotence");
    if (pthread_create(&closer, NULL, close_worker, NULL))
        return semantic_failure("start-close");
    int observed_close = 0;
    for (unsigned int iteration = 0; iteration < 1000000U; ++iteration) {
        if (pthread_mutex_lock(&owner.lock))
            return semantic_failure("lock");
        observed_close = owner.closing != 0U;
        (void)pthread_mutex_unlock(&owner.lock);
        if (observed_close)
            break;
        sched_yield();
    }
    if (!observed_close)
        return semantic_failure("close-not-observed");
    if (swapz_round073_expect_shutdown(&owner, &unexpected) ||
        unexpected.owner)
        return semantic_failure("get-after-close");
    if (swapz_round080_release_decoder_leases(&original, &unexpected) ||
        pthread_join(closer, NULL) || close_result || owner.active_readers)
        return semantic_failure("drain-join");
    (void)pthread_cond_destroy(&owner.drained);
    (void)pthread_mutex_destroy(&owner.lock);
    puts("ROUND080_LATE_LEASE_SAFE_DRAIN_PASS");
    return 0;
}
'''

def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)

def launch(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=40, check=False)

def source_body() -> str:
    fixture = FIXTURE.read_text()
    marker = "static int swapz_round073_expect_shutdown("
    require(fixture.count(marker) == 1, "missing-single-actual-native-close-helper")
    body = fixture.split(marker, 1)[1].split("\n}\n", 1)[0]
    cleanup_marker = "static int swapz_round080_release_decoder_leases("
    require(fixture.count(cleanup_marker) == 1, "missing-native-cleanup-helper")
    cleanup = fixture.split(cleanup_marker, 1)[1].split("\n}\n", 1)[0]
    return marker + body + "\n}\n" + cleanup_marker + cleanup + "\n}"

def run_compiler(compiler_name: str, directory: Path, body: str) -> None:
    compiler = shutil.which(compiler_name)
    require(compiler is not None, "missing-compiler:" + compiler_name)
    check = directory / "mode.c"
    check.write_text("int main(void) { return 0; }\n")
    mode = next((name for name in ("-std=c23", "-std=c2x") if
                 launch([compiler, name, "-fsyntax-only", str(check)]).returncode == 0),
                None)
    require(mode is not None, "C23-mode-not-supported:" + compiler_name)
    flags = [compiler, mode, "-O1", "-g", "-Wall", "-Wextra",
             "-Wconversion", "-Wshadow", "-Werror",
             "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
             "-pthread", "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1"]
    mutant_specs = [
        ("leaked-late-pin",
         "put_result = swapz_zswap_import_decoder_owner_put(late);",
         "put_result = 0;"),
        ("ignored-post-close-rejection",
         "return result == -ESHUTDOWN ? 0 : result;",
         "return result;"),
        ("missing-shared-late-put",
         "error = swapz_zswap_import_decoder_owner_put(late);",
         "error = 0;"),
        ("missing-shared-primary-put",
         "cleanup_error = swapz_zswap_import_decoder_owner_put(lease);",
         "cleanup_error = 0;"),
    ]
    for index, variant in enumerate([(None, None, None), *mutant_specs]):
        name, before, after = variant
        helper = body
        if name:
            require(helper.count(before) == 1,
                    "actual-native-helper-mutant-anchor:" + name)
            helper = helper.replace(before, after, 1)
        test_path = directory / (compiler_name + "-late-" + str(index) + ".c")
        executable = directory / (compiler_name + "-late-" + str(index))
        test_path.write_text(HARNESS.replace("ORIGINAL_CLOSE_HELPER", helper))
        build = launch([*flags, "-I", str(directory),
                        str(test_path), str(directory / "decoder-owner.c"),
                        "-o", str(executable)])
        require(build.returncode == 0,
                compiler_name + ":compile-" + str(index) + ":" +
                (build.stderr.splitlines() or ["unknown"])[0][:180])
        executed = launch([str(executable)])
        if name:
            require(executed.returncode == 17 and
                    "ROUND080_LATE_LEASE_SEMANTIC_KILL" in executed.stderr and
                    "AddressSanitizer" not in executed.stderr,
                    compiler_name + ":semantic-mutant-not-killed:" + name)
        else:
            require(executed.returncode == 0 and
                    "ROUND080_LATE_LEASE_SAFE_DRAIN_PASS" in executed.stdout and
                    not executed.stderr,
                    compiler_name + ":baseline-lifetime-execution")
    print("PASS ROUND080_READER_LATE_LEASE_" + compiler_name.upper() +
          " real_product_owner_source=YES fixture_helper_source=YES "
          "strict_ASan_UBSan=YES compiled_executed_semantic_mutants=4",
          flush=True)

def main() -> int:
    try:
        fixture = FIXTURE.read_text()
        require(fixture.count("KUNIT_CASE(swapz_round073_original_stale_crc_sha_codec)") == 1 and
                fixture.count("KUNIT_CASE(swapz_round073_original_decoder_retire_with_pin)") == 1 and
                "swapz_round080_release_decoder_leases(&lease, &late);" in fixture and
                "cancel_delayed_work_sync(&stall.delayed)" in fixture and
                "ROUND080_READER_NATIVE_FIRST_ERROR stalled_phase=" in fixture,
                "native-reader-KUnit-lifetime-guards")
        import runpy
        contract = runpy.run_path(str(Path(__file__).with_name(
            "round073-stage-original-reader-pin-gc.py")))
        try:
            contract["validate_reader_cleanup"](fixture.encode())
        except contract["StageFailure"] as failure:
            raise ValueError(str(failure)) from failure
        body = source_body()
        require(body.count("swapz_zswap_import_decoder_owner_get(owner, late)") == 1 and
                body.count("swapz_zswap_import_decoder_owner_put(late)") == 2 and
                body.count("return result == -ESHUTDOWN ? 0 : result;") == 1,
                "native-helper-exact-source-refcount-contract")
        with tempfile.TemporaryDirectory(prefix="swapz-round080-reader-") as folder:
            directory = Path(folder)
            (directory / "zswap-import-codec.h").write_text(CODEC_SHIM)
            (directory / "zswap-import-decoder-owner.h").write_bytes(
                OWNER_HEADER.read_bytes())
            (directory / "decoder-owner.c").write_bytes(OWNER.read_bytes())
            for name in ("gcc", "clang"):
                run_compiler(name, directory, body)
        print("PASS ROUND080_ORIGINAL_READER_LATE_PIN_NEGATIVES "
              "semantic_mutants=4_per_compiler source_AUTH=0 "
              "original_NATIVE_KUnit=SEPARATE_PINNED_UML", flush=True)
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as failure:
        print("ROUND080_READER_C_FIRST_ERROR " +
              str(failure).split("\n", 1)[0][:220], file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
