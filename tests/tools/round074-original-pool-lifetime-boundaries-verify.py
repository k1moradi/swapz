#!/usr/bin/env python3
"""Round074 source-anchored pool lifetime host-only qualification.

The pinned original mm/zswap.c is checked byte-for-byte and the inherited
Round071/072 stage is rendered read-only. Only the separate pthread lifetime
model is compiled/executed on host; this is NOT a kernel pool runtime test.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "tests/runtime/native/fixtures/round074-original-pool-lifetime-boundaries.c"
STAGER = ROOT / "tests/tools/round071-stage-original-pool-retirement.py"
OLD_FIXTURE = ROOT / "tests/runtime/native/fixtures/round071-original-pool-retirement-kunit.cfrag"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
MUTANT_COUNT = 10


class FirstError(Exception):
    pass


def require(condition: bool, name: str) -> None:
    if not condition:
        raise FirstError(name)


def check_original_source(original: bytes, staged: bytes, fixture: bytes) -> None:
    """Structural real-original and deterministic staged postimage contract."""
    def one(haystack: bytes, needle: bytes, cause: str) -> int:
        require(haystack.count(needle) == 1, cause)
        return haystack.index(needle)

    one(original, b"static void zswap_pool_destroy(struct zswap_pool *pool)",
        "missing-single-original-destructor")
    destructor_start = original.index(b"static void zswap_pool_destroy(struct zswap_pool *pool)")
    release_original_start = original.index(b"static void __zswap_pool_release(struct work_struct *work)")
    release_original_end = original.index(b"static void __zswap_pool_empty(struct percpu_ref *ref)\n{")
    destructor = original[destructor_start:release_original_start]
    original_release = original[release_original_start:release_original_end]
    for needle, cause in (
        (b"cpuhp_state_remove_instance(CPUHP_MM_ZSWP_POOL_PREPARE, &pool->node);", "hotplug"),
        (b"free_percpu(pool->acomp_ctx);", "percpu-tfm"),
        (b"zs_destroy_pool(pool->zs_pool);", "zsmalloc"),
        (b"kfree(pool);", "original-pool-free"),
    ):
        one(destructor, needle, "missing-original-destructor-" + cause)
    one(original_release, b"percpu_ref_exit(&pool->ref);",
        "missing-original-rcu-release-percpu-ref-exit")
    one(original, b"xa_erase_bh(&zswap_pools, pool->idx);", "missing-original-pool-xarray-erase")
    one(original, b"queue_rcu_work(system_percpu_wq, &pool->release_rwork);",
        "missing-original-rcu-worker")
    one(staged, b"static DECLARE_COMPLETION(swapz_round072_target_pool_released);",
        "missing-private-target-completion")
    one(staged, b"const unsigned long released_pool_address = (unsigned long)pool;",
        "missing-pre-destroy-address-capture")
    one(staged, b"if (cmpxchg(&swapz_round072_target_pool_address,",
        "missing-target-only-rcu-identity")
    one(staged, b"complete_all(&swapz_round072_target_pool_released);",
        "missing-after-destructor-private-wake")
    one(staged, b"atomic_inc(&swapz_round071_destroy_complete);",
        "missing-after-destroy-count")
    release_start = one(staged,
                        b"static void __zswap_pool_release(struct work_struct *work)",
                        "missing-single-staged-rcu-callback")
    release_end = one(staged,
                      b"static void __zswap_pool_empty(struct percpu_ref *ref)\n{",
                      "missing-single-original-empty-callback")
    release = staged[release_start:release_end]
    order = [release.find(needle) for needle in (
        b"const unsigned long released_pool_address",
        b"percpu_ref_exit(&pool->ref);",
        b"zswap_pool_destroy(pool);",
        b"cmpxchg(&swapz_round072_target_pool_address,",
        b"complete_all(&swapz_round072_target_pool_released);",
    )]
    require(all(position >= 0 for position in order) and order == sorted(order),
            "callback-wake-must-follow-original-destruction")
    empty = staged[release_end:]
    require(empty.find(b"xa_erase_bh(&zswap_pools, pool->idx);") >= 0 and
            empty.find(b"queue_rcu_work(system_percpu_wq, &pool->release_rwork);") >
            empty.find(b"xa_erase_bh(&zswap_pools, pool->idx);"),
            "original-empty-erase-before-RCU-queue")
    for needle, cause in (
        (b"percpu_ref_kill(&pool->ref);", "missing-fixture-ref-kill"),
        (b"wait_for_completion_timeout(\n        &swapz_round072_target_pool_released,", "missing-private-wait"),
        (b"swapz_zswap_import_decoder_owner_get(&owner, &lease)", "missing-reader-get"),
        (b"swapz_zswap_import_decoder_owner_decode(&lease,", "missing-original-decoder"),
        (b"swapz_zswap_import_decoder_owner_put(&lease)", "missing-reader-put"),
        (b"swapz_zswap_import_decoder_owner_close_and_drain(&owner)", "missing-owner-close"),
        (b"SWAPZ_R071_CLOSE_CYCLES 24U", "missing-48-close-cycles"),
    ):
        require(needle in fixture, cause)
    require(b"flush_workqueue(system_percpu_wq)" not in fixture and
            b"flush_workqueue(system_percpu_wq)" not in staged,
            "forbidden-systemwide-worker-flush")


def source_negatives(original: bytes, staged: bytes, fixture: bytes) -> int:
    def replace_last(source: bytes, needle: bytes, replacement: bytes) -> bytes:
        before, separator, after = source.rpartition(needle)
        require(bool(separator), "missing-negative-original-anchor")
        return before + replacement + after

    scenarios = (
        ("original-xarray-erase", original.replace(
            b"xa_erase_bh(&zswap_pools, pool->idx);", b"/* lost erase */", 1), staged, fixture),
        ("original-rcu-queue", original.replace(
            b"queue_rcu_work(system_percpu_wq, &pool->release_rwork);", b"/* lost RCU */", 1), staged, fixture),
        ("original-percpu-exit", replace_last(
            original, b"percpu_ref_exit(&pool->ref);", b"/* lost ref exit */"), staged, fixture),
        ("original-pool-free", replace_last(
            original, b"zs_destroy_pool(pool->zs_pool);", b"/* lost pool death */"), staged, fixture),
        ("post-destroy-private-wake", original, staged.replace(
            b"complete_all(&swapz_round072_target_pool_released);", b"/* missing wake */", 1), fixture),
        ("RCU-before-destructor", original, staged.replace(
            b"zswap_pool_destroy(pool);\n\t/* Test-only:",
            b"/* missing original destroy */\n\t/* Test-only:", 1), fixture),
        ("lost-reader-get", original, staged, fixture.replace(
            b"swapz_zswap_import_decoder_owner_get(&owner, &lease)", b"/* lost get */", 1)),
        ("lost-reader-put", original, staged, fixture.replace(
            b"swapz_zswap_import_decoder_owner_put(&lease)", b"/* lost put */")),
        ("forbidden-global-flush", original, staged, fixture + b"\nflush_workqueue(system_percpu_wq);"),
    )
    rejected = 0
    for label, source_mutant, staged_mutant, fixture_mutant in scenarios:
        require((source_mutant, staged_mutant, fixture_mutant) != (original, staged, fixture),
                "source-mutant-was-not-applied:" + label)
        try:
            check_original_source(source_mutant, staged_mutant, fixture_mutant)
        except FirstError:
            rejected += 1
        else:
            raise FirstError("source-semantic-mutant-accepted:" + label)
    require(rejected == len(scenarios), "source-negative-count")
    return rejected


def require_pinned_original(revision: str, original: bytes) -> None:
    require(revision == PIN, "original-linux-pin-mismatch")
    git_blob = hashlib.sha1(b"blob " + str(len(original)).encode() + b"\0" + original)
    require(git_blob.hexdigest() == ORIGINAL_BLOB, "original-mm-zswap-git-blob-drift")


def validate_original(linux_root: Path) -> int:
    require(STAGER.is_file() and OLD_FIXTURE.is_file(), "missing-previous-source-stage")
    rev = subprocess.run(["git", "-C", str(linux_root), "rev-parse", "HEAD"],
                         text=True, capture_output=True, check=True, timeout=20).stdout.strip()
    original = subprocess.run(["git", "-C", str(linux_root), "show", "HEAD:mm/zswap.c"],
                              capture_output=True, check=True, timeout=20).stdout
    require((linux_root / "mm/zswap.c").read_bytes() == original,
            "working-original-mm-not-pristine")
    require_pinned_original(rev, original)
    for mismatch_revision, mismatch_content in (("f" * 40, original),
                                                (rev, original + b"\n/* blob drift */\n")):
        try:
            require_pinned_original(mismatch_revision, mismatch_content)
        except FirstError:
            continue
        raise FirstError("original-source-pin-or-blob-negative-accepted")
    fixture = OLD_FIXTURE.read_bytes()
    stager = runpy.run_path(str(STAGER))
    require(stager["PIN"] == PIN and stager["ORIGINAL_ZSWAP_BLOB"] == ORIGINAL_BLOB,
            "read-only-original-stager-pin-drift")
    staged = stager["render"](original, fixture)
    require(staged != original and staged.endswith(fixture), "not-real-staged-postimage")
    check_original_source(original, staged, fixture)
    rejected = source_negatives(original, staged, fixture)
    print("ROUND074_POOL_ORIGINAL_SOURCE_ANCHOR_PASS pinned_original_blob=YES "
          "rendered_original_KUnit_postimage_sha256=" +
          hashlib.sha256(staged).hexdigest() +
          " rejected_source_mutants=" + str(rejected) +
          " rejected_pin_blob_mutants=2 runtime_claim=NONE")
    return rejected


def run_model() -> tuple[int, int]:
    require(SOURCE.is_file(), "missing-model-C")
    compiled_executed = 0
    with tempfile.TemporaryDirectory(prefix="round074-pool-host-") as directory:
        for compiler in ("gcc", "clang"):
            for mutant in range(MUTANT_COUNT + 1):
                output = Path(directory) / f"{compiler}-{mutant}"
                command = [compiler, "-std=c2x", "-Wall", "-Wextra", "-Wconversion",
                           "-Wshadow", "-Wpedantic", "-Wstrict-prototypes", "-Werror",
                           "-O1", "-g", "-fno-omit-frame-pointer", "-pthread",
                           "-fsanitize=address,undefined", f"-DROUND074_MUTANT={mutant}",
                           str(SOURCE), "-o", str(output)]
                build = subprocess.run(command, text=True, capture_output=True,
                                       check=False, timeout=40)
                require(build.returncode == 0,
                        f"compile:{compiler}:mutant={mutant}:" + build.stderr[-500:])
                environment = os.environ.copy()
                environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
                environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                execution = subprocess.run([str(output)], text=True, capture_output=True,
                                           check=False, env=environment, timeout=25)
                if mutant == 0:
                    require(execution.returncode == 0 and
                            "ROUND074_POOL_HOST_BASELINE_PASS" in execution.stdout,
                            f"baseline:{compiler}:" + execution.stderr[-350:])
                else:
                    require(execution.returncode != 0 and
                            f"ROUND074_POOL_HOST_FIRST_ERROR mutant={mutant} " in
                            execution.stderr and
                            "ERROR: AddressSanitizer" not in execution.stderr,
                            f"compiled-C-semantic-mutant-not-detected:{compiler}:{mutant}:" +
                            execution.stderr[-350:])
                    compiled_executed += 1
                print(f"ROUND074_POOL_C_CASE_PASS compiler={compiler} mutant={mutant} "
                      "asan_ubsan=YES")
    require(compiled_executed == 2 * MUTANT_COUNT, "compiled-semantic-mutant-count")
    print(f"ROUND074_POOL_HOST_GCC_CLANG_ASAN_UBSAN_PASS baselines=2 "
          f"compiled_executed_C_semantic_mutants={compiled_executed} "
          "model_only=YES source_auth=0 phase_a=BLOCKED")
    return 2, compiled_executed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("self-test", "qualify"))
    parser.add_argument("--linux-root", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.mode == "qualify":
            require(arguments.linux_root is not None, "missing-linux-root")
            validate_original(arguments.linux_root)
        run_model()
        return 0
    except (FirstError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("ROUND074_POOL_HOST_FIRST_ERROR " + str(error)[:750], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
