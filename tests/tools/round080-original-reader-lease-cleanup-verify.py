#!/usr/bin/env python3
"""Round080 test-only reader/GC native close cleanup source-linked host proof.

Compiles the actual helper extracted from the original pinned test-only KUnit
fragment and the real dormant decoder-owner C, under GCC/Clang C23 sanitizer
flags. The two binaries execute independently: pristine and leaked-late-pin
semantic mutant. No privileged kernel, hardware, swapon, or product activation.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
DECODER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
DECODER_HEADER = ROOT / "src/kernel/zswap-import-decoder-owner.h"
BEGIN = "/* ROUND080_READER_LEASE_CLEANUP_BEGIN"
END = "/* ROUND080_READER_LEASE_CLEANUP_END */"
RELEASE = "cleanup_error = swapz_zswap_import_decoder_owner_put(late);"
LEAK_MUTATION = "cleanup_error = 0; /* mutated: leaked late pin */"


class Failure(Exception):
    pass


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise Failure(detail)


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, text=True, capture_output=True,
                          timeout=60, check=False)


def compiler_mode(compiler: str, directory: Path) -> str:
    candidate = directory / "probe.c"
    candidate.write_text("int main(void) { return 0; }\n")
    for standard in ("-std=c23", "-std=c2x"):
        if run([compiler, standard, "-fsyntax-only", str(candidate)]).returncode == 0:
            return standard
    raise Failure("compiler-no-C23-mode:" + compiler)


def main() -> int:
    try:
        contents = FIXTURE.read_text()
        require(contents.count(BEGIN) == 1 and contents.count(END) == 1,
                "original-native-fixture-cleanup-source-markers")
        start = contents.index("static int swapz_round080_release_decoder_leases(", contents.index(BEGIN))
        stop = contents.index(END, start)
        helper = contents[start:stop]
        require(helper.count(RELEASE) == 1 and
                helper.count("swapz_zswap_import_decoder_owner_put(lease);") == 1 and
                "if (late->owner)" in helper and
                contents.index("swapz_round080_release_decoder_leases(&lease, &late);") <
                contents.index("kthread_stop(closer_task);"),
                "native-close-late-pin-release-before-worker-join")
        require("wait_for_completion(&closer.returned);" not in contents and
                "if (!wait_for_completion_timeout(&closer.returned," in contents,
                "native-unbounded-close-join-not-corrected")
        product = DECODER.read_text()
        header = DECODER_HEADER.read_text()
        require("swapz_zswap_import_decoder_owner_close_and_drain(" in product and
                "wait_event(owner->drained" in product and
                "struct swapz_zswap_import_decoder_lease" in header and
                "swapz_zswap_import_decoder_owner_put(" in product,
                "product-original-decoder-owner-source-not-linked")
        # The only emulated symbol is the unused codec checksum routine:
        # reader ownership and close/drain come from actual product C.
        harness = (
            "#define SWAPZ_ZSWAP_IMPORT_HOST_TEST 1\n"
            "#define SWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST 1\n"
            "#include <pthread.h>\n#include <time.h>\n#include <stdio.h>\n"
            "#include \"codec.h\"\n"
            "swapz_u32 swapz_crc32c_bytes(const void *bytes, swapz_u32 length)\n"
            "{ (void)bytes; (void)length; return 0U; }\n"
            "#include \"zswap-import-decoder-owner.c\"\n"
        )
        checks = r"""
struct close_worker {
    struct swapz_zswap_import_decoder_owner *owner;
    int result;
};
static void *close_worker_run(void *context)
{
    struct close_worker *worker = context;
    worker->result = swapz_zswap_import_decoder_owner_close_and_drain(worker->owner);
    return NULL;
}
static int check_release_with_active_closer(void)
{
    struct swapz_zswap_import_decoder_owner owner = {};
    struct swapz_zswap_import_decoder_lease lease = {}, late = {};
    struct close_worker worker = {};
    struct timespec pause = { .tv_sec = 0, .tv_nsec = 1000000L };
    pthread_t thread;
    unsigned int iteration;
    int closed = 0;
    int result;

    if (swapz_zswap_import_decoder_owner_init(&owner,
            SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION))
        return 2;
    if (swapz_zswap_import_decoder_owner_get(&owner, &lease) ||
        swapz_zswap_import_decoder_owner_get(&owner, &late))
        return 3;
    worker.owner = &owner;
    worker.result = -1;
    if (pthread_create(&thread, NULL, close_worker_run, &worker))
        return 4;
    for (iteration = 0; iteration < 1000U; ++iteration) {
        if (pthread_mutex_lock(&owner.lock))
            return 5;
        closed = owner.closing != 0U;
        pthread_mutex_unlock(&owner.lock);
        if (closed)
            break;
        nanosleep(&pause, NULL);
    }
    /* Never join while either reader pin is held, even on timeout. */
    result = swapz_round080_release_decoder_leases(&lease, &late);
    pthread_join(thread, NULL);
    if (!closed || result || worker.result || lease.owner ||
        late.owner || owner.active_readers != 0U || !owner.closing)
        return 6;
    if (swapz_round080_release_decoder_leases(&lease, &late))
        return 7;
    return 0;
}
static int check_late_lease_leak_negative(void)
{
    struct swapz_zswap_import_decoder_owner owner = {};
    struct swapz_zswap_import_decoder_lease lease = {}, late = {};
    int result;

    if (swapz_zswap_import_decoder_owner_init(&owner,
            SWAPZ_ZSWAP_IMPORT_LZ4_CODEC, SWAPZ_ZSWAP_IMPORT_VERSION))
        return 2;
    if (swapz_zswap_import_decoder_owner_get(&owner, &lease) ||
        swapz_zswap_import_decoder_owner_get(&owner, &late))
        return 3;
    result = swapz_round080_release_decoder_leases(&lease, &late);
    if (result || late.owner || lease.owner || owner.active_readers != 0U) {
        /* Deterministic exit after independently COMPILED mutation RUNS. */
        fputs("ROUND080_MUTANT_KILLED_LEAKED_LATE_PIN\n", stderr);
        if (late.owner)
            swapz_zswap_import_decoder_owner_put(&late);
        if (lease.owner)
            swapz_zswap_import_decoder_owner_put(&lease);
        return 17;
    }
    if (swapz_zswap_import_decoder_owner_close_and_drain(&owner))
        return 4;
    return 0;
}
int main(void)
{
    int result = check_late_lease_leak_negative();
    if (result)
        return result;
    return check_release_with_active_closer();
}
"""
        with tempfile.TemporaryDirectory(prefix="round080-reader-close-") as folder:
            directory = Path(folder)
            for compiler_name in ("gcc", "clang"):
                compiler = shutil.which(compiler_name)
                require(compiler is not None, "missing-compiler:" + compiler_name)
                mode = compiler_mode(compiler, directory)
                flags = [compiler, mode, "-O1", "-g", "-Wall", "-Wextra",
                         "-Wconversion", "-Wshadow", "-Werror",
                         "-Werror=implicit-function-declaration",
                         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                         "-pthread", "-I", str(ROOT / "src/kernel")]
                for variant, source, expected in (
                    ("pristine", helper, 0),
                    ("leak-late", helper.replace(RELEASE, LEAK_MUTATION), 17),
                ):
                    require(variant != "leak-late" or source != helper,
                            "semantic-mutation-source-not-changed")
                    path = directory / (compiler_name + "-" + variant + ".c")
                    executable = directory / (compiler_name + "-" + variant)
                    path.write_text(harness + "\n" + source + "\n" + checks)
                    built = run([*flags, str(path), "-llz4", "-lcrypto",
                                 "-o", str(executable)])
                    require(built.returncode == 0,
                            compiler_name + ":" + variant + ":compile-first-error:" +
                            (built.stderr.splitlines() or ["unknown"])[0][:150])
                    executed = run([str(executable)])
                    require(executed.returncode == expected,
                            compiler_name + ":" + variant + ":executed-exit:" +
                            str(executed.returncode) + ":" +
                            (executed.stderr.splitlines() or ["unknown"])[0][:100])
                    if expected:
                        require("ROUND080_MUTANT_KILLED_LEAKED_LATE_PIN" in
                                executed.stderr,
                                compiler_name + ":wrong-late-pin-mutation-kill")
                print("PASS ROUND080_READER_CLEANUP_" + compiler_name.upper() +
                      " real_decoder_owner_C=COMPILED_AND_EXECUTED "
                      "native_fixture_cleanup_C=COMPILED_AND_EXECUTED "
                      "semantic_late_pin_leak_mutant_compiled_executed=1 "
                      "strict_C23_ASan_UBSan=YES", flush=True)
        print("PASS ROUND080_READER_CLEANUP_TOTAL gcc_mutants=1 clang_mutants=1 "
              "real_product_owner_source=YES fixture_cleanup_source=YES "
              "AUTH0 PHASE_A=BLOCKED native_UML=SEPARATE_JOB", flush=True)
        return 0
    except (Failure, OSError, ValueError, subprocess.TimeoutExpired) as failure:
        print("ROUND080_READER_CLEANUP_FIRST_ERROR " +
              str(failure)[:220], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
