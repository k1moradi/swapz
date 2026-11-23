#!/usr/bin/env python3
"""Round080 actual dormant decoder-owner C: bounded cleanup and leaked reader pin.

Rootless GCC/Clang strict sanitizer host adapter. Does NOT replace pinned Linux
UML KUnit, validate live STORED authority, or mutate production decoder C/H.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
OWNER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
HEADER = ROOT / "src/kernel/zswap-import-decoder-owner.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
EXPECTED = {
    OWNER: "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    HEADER: "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
}

C_TEST = r"""
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "zswap-import-decoder-owner.h"

static atomic_int closer_finished = 0;
static int closer_error = -EINPROGRESS;

static void *close_worker(void *parameter)
{
    struct swapz_zswap_import_decoder_owner *owner = parameter;
    closer_error = swapz_zswap_import_decoder_owner_close_and_drain(owner);
    atomic_store_explicit(&closer_finished, 1, memory_order_release);
    return NULL;
}

int main(void)
{
    struct swapz_zswap_import_decoder_owner owner = {0};
    struct swapz_zswap_import_decoder_lease old_reader = {0};
    struct swapz_zswap_import_decoder_lease late_reader = {0};
    struct swapz_zswap_import_decoder_lease rejected_reader = {0};
    pthread_t close_thread;
    unsigned int leaked_count = 0;
    int closing = 0;
    int joined = 0;

    if (swapz_zswap_import_decoder_owner_init(
            &owner, SWAPZ_ZSWAP_IMPORT_LZ4_CODEC,
            SWAPZ_ZSWAP_IMPORT_VERSION) ||
        swapz_zswap_import_decoder_owner_get(&owner, &old_reader) ||
        swapz_zswap_import_decoder_owner_get(&owner, &late_reader) ||
        pthread_create(&close_thread, NULL, close_worker, &owner))
        return 3;
    for (unsigned int iteration = 0; iteration < 1000000U; ++iteration) {
        if (pthread_mutex_lock(&owner.lock))
            return 3;
        closing = owner.closing != 0U;
        (void)pthread_mutex_unlock(&owner.lock);
        if (closing)
            break;
        sched_yield();
    }
    if (!closing ||
        swapz_zswap_import_decoder_owner_get(&owner, &rejected_reader)
            != -ESHUTDOWN ||
        atomic_load_explicit(&closer_finished, memory_order_acquire))
        return 3;

    /* ROUND080_PUT_OLD */
    if (swapz_zswap_import_decoder_owner_put(&old_reader))
        return 3;
    if (atomic_load_explicit(&closer_finished, memory_order_acquire))
        return 3;
    /* ROUND080_PUT_LATE */
    if (swapz_zswap_import_decoder_owner_put(&late_reader))
        return 3;
    if (pthread_mutex_lock(&owner.lock))
        return 3;
    leaked_count = owner.active_readers;
    (void)pthread_mutex_unlock(&owner.lock);

    /* All borrowed decoder ownership is released before join. A mutant's
     * leaked pin is diagnosed without hanging indefinitely; the fixture
     * then releases it solely so that the test thread can terminate. */
    if (old_reader.owner)
        (void)swapz_zswap_import_decoder_owner_put(&old_reader);
    if (late_reader.owner)
        (void)swapz_zswap_import_decoder_owner_put(&late_reader);
    joined = pthread_join(close_thread, NULL);
    if (joined || closer_error ||
        !atomic_load_explicit(&closer_finished, memory_order_acquire))
        return 3;
    if (leaked_count != 0U) {
        fputs("ROUND080_READER_LEAK_SEMANTIC_KILL\n", stderr);
        return 17;
    }
    if (old_reader.owner || late_reader.owner ||
        swapz_zswap_import_decoder_owner_get(&owner, &rejected_reader)
            != -ESHUTDOWN)
        return 3;
    (void)pthread_cond_destroy(&owner.drained);
    (void)pthread_mutex_destroy(&owner.lock);
    puts("ROUND080_READER_CLOSE_SOURCE_BASELINE_PASS");
    return 0;
}
"""

MUTANTS = (
    ("missing-old-reader-put",
     "    /* ROUND080_PUT_OLD */\n"
     "    if (swapz_zswap_import_decoder_owner_put(&old_reader))\n"
     "        return 3;\n",
     "    /* ROUND080_PUT_OLD */\n"),
    ("missing-late-reader-put",
     "    /* ROUND080_PUT_LATE */\n"
     "    if (swapz_zswap_import_decoder_owner_put(&late_reader))\n"
     "        return 3;\n",
     "    /* ROUND080_PUT_LATE */\n"),
)


class Failure(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise Failure(message)


def blob_sha(contents: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(contents)).encode() + b"\0" + contents).hexdigest()


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True,
                          timeout=30, check=False)


def mode(compiler: str, directory: Path) -> str:
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for selected in ("-std=c23", "-std=c2x"):
        if execute([compiler, selected, "-fsyntax-only", str(probe)]).returncode == 0:
            return selected
    raise Failure("no-strict-C23-mode:" + compiler)


def main() -> int:
    try:
        for path, expected in EXPECTED.items():
            require(blob_sha(path.read_bytes()) == expected,
                    "actual-dormant-decoder-product-source-pin:" + path.name)
        fixture = FIXTURE.read_text()
        for anchor in ("/* ROUND073_ORIGINAL_READER_PIN_GC_BEGIN",
                       "KUNIT_CASE(swapz_round073_original_stale_crc_sha_codec)",
                       "KUNIT_CASE(swapz_round073_original_decoder_retire_with_pin)",
                       "if (late.owner)",
                       "swapz_zswap_import_decoder_owner_put(&late);",
                       "swapz_zswap_import_decoder_owner_put(&lease);",
                       "wait_for_completion_timeout(&closer->returned",
                       "ROUND080_READER_STALL_FIRST_ERROR"):
            require(anchor in fixture, "real-original-test-cleanup-anchor:" + anchor)
        require("wait_for_completion(&closer->returned)" not in fixture,
                "unbounded-close-drain-KUnit-test-regression")
        with tempfile.TemporaryDirectory(prefix="round080-reader-lease-") as temp:
            path = Path(temp)
            for compiler_name in ("gcc", "clang"):
                compiler = shutil.which(compiler_name)
                require(compiler is not None, "missing-compiler:" + compiler_name)
                flags = [compiler, mode(compiler, path), "-O1", "-g", "-Wall",
                         "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
                         "-fsanitize=address,undefined",
                         "-fno-sanitize-recover=all",
                         "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                         "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
                         "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1", "-pthread",
                         "-I", str(ROOT / "src/kernel")]
                for name, needle, replacement in (
                        ("baseline", "", ""), *MUTANTS):
                    require(not needle or C_TEST.count(needle) == 1,
                            "mutant-source-anchor:" + name)
                    source = path / (compiler_name + "-" + name + ".c")
                    binary = path / (compiler_name + "-" + name)
                    source.write_text(
                        C_TEST if not needle else C_TEST.replace(needle, replacement))
                    compiled = execute(
                        [*flags, str(OWNER), str(ROOT / "src/kernel/codec.c"),
                         str(source), "-llz4", "-lcrypto",
                         "-o", str(binary)])
                    require(compiled.returncode == 0,
                            compiler_name + ":" + name + ":compile:" +
                            (compiled.stderr.splitlines() or ["unknown"])[0][:200])
                    finished = execute([str(binary)])
                    if not needle:
                        require(finished.returncode == 0 and
                                "ROUND080_READER_CLOSE_SOURCE_BASELINE_PASS"
                                in finished.stdout and not finished.stderr,
                                compiler_name + ":baseline-not-executed")
                    else:
                        require(finished.returncode == 17 and
                                "ROUND080_READER_LEAK_SEMANTIC_KILL"
                                in finished.stderr and
                                "AddressSanitizer" not in finished.stderr and
                                "runtime error:" not in finished.stderr,
                                compiler_name + ":" + name +
                                ":compiled-C-mutant-survived")
                print("PASS ROUND080_READER_" + compiler_name.upper() +
                      "_C23_ASAN_UBSAN product_owner_C=EXACT "
                      "baseline_executed=1 "
                      "compiled_executed_leaked_reader_semantic_mutants=2 "
                      "KUnit_real_native=SEPARATE_JOB AUTH0", flush=True)
        return 0
    except (Failure, OSError, subprocess.TimeoutExpired) as error:
        message = str(error) if isinstance(error, Failure) else type(error).__name__
        print("ROUND080_READER_HOST_FIRST_ERROR " + message[:230],
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
