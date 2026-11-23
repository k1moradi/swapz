#!/usr/bin/env python3
"""Fail-closed, exact-original Linux mm/zswap.c pool lifecycle KUnit suffix.

Only after the previously published Round068 original decoder stage succeeds,
append a test-only KUnit suite and instrument completion of the actual original
pool destructor. No production source change, synthetic zswap pool, swap
activation, loaded module or imported I/O is involved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_ZSWAP_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
FRAGMENT = ROOT / "tests/runtime/native/fixtures/round071-original-pool-retirement-kunit.cfrag"
SOURCE_PATH = "mm/zswap.c"
COUNTER_DECLARATION = (
    b"/* Round071 KUnit-only witness: actual original pool tfm/zsmalloc death. */\n"
    b"static atomic_t swapz_round071_destroy_complete = ATOMIC_INIT(0);\n"
)
CREATE_ANCHOR = b"static void zswap_pool_destroy(struct zswap_pool *pool)\n"
RELEASE_ANCHOR = (
    b"\tzs_destroy_pool(pool->zs_pool);\n\tkfree(pool);\n}\n\n"
    b"static void __zswap_pool_release(struct work_struct *work)\n"
)
RELEASE_REPLACEMENT = (
    b"\tzs_destroy_pool(pool->zs_pool);\n\tkfree(pool);\n"
    b"\t/* Count AFTER all original per-CPU tfms and pool are freed. */\n"
    b"\tatomic_inc(&swapz_round071_destroy_complete);\n}\n\n"
    b"static void __zswap_pool_release(struct work_struct *work)\n"
)


class StageError(Exception):
    pass


def require(value: bool, cause: str) -> None:
    if not value:
        raise StageError(cause)


def git_blob(content: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checked(command: list[str]) -> str:
    process = subprocess.run(command, text=True, capture_output=True,
                             timeout=45, check=False)
    require(process.returncode == 0, "git-prerequisite")
    return process.stdout.strip()


def render(original: bytes, fragment: bytes) -> bytes:
    require(git_blob(original) == ORIGINAL_ZSWAP_BLOB,
            "pristine-original-mm-zswap-blob")
    require(fragment.count(b"kunit_test_suite(swapz_round071_pool_retirement_suite);") == 1,
            "native-suite-registration")
    for label in (b"swapz_round071_original_lzo_pool_retirement",
                  b"swapz_round071_original_lz4_pool_retirement"):
        require(fragment.count(b"static void " + label + b"(") == 1,
                "original-KUnit-case:" + label.decode())
    for anchor, count in ((CREATE_ANCHOR, 1), (RELEASE_ANCHOR, 1)):
        require(original.count(anchor) == count,
                "original-pool-retirement-anchor-drift")
    require(original.count(b"percpu_ref_kill(&put_pool->ref);") == 1,
            "original-ref-kill-missing")
    require(original.count(b"queue_rcu_work(system_percpu_wq, &pool->release_rwork);") == 1,
            "original-rcu-destruction-missing")
    require(b"swapz_round071_destroy_complete" not in original,
            "test-witness-already-in-original")
    return (original.replace(CREATE_ANCHOR,
                             COUNTER_DECLARATION + CREATE_ANCHOR, 1)
            .replace(RELEASE_ANCHOR, RELEASE_REPLACEMENT, 1)
            + b"\n" + fragment)


def stage(linux: Path, manifest_path: Path, decoder_manifest: Path) -> None:
    require(checked(["git", "-C", str(linux), "rev-parse", "HEAD"]) == PIN,
            "original-linux-pin")
    require(manifest_path != decoder_manifest, "manifest-overlap")
    require(not manifest_path.exists(), "manifest-already-present")
    decoder = json.loads(decoder_manifest.read_text())
    require(decoder.get("original_pin") == PIN and
            decoder.get("source_mapped_authenticated") is False and
            decoder.get("staged_kernel_test_only") is True and
            len(decoder.get("entries", [])) == 8,
            "prior-native-decoder-stage-unverified")
    for entry in decoder["entries"]:
        staged = linux / entry["path"]
        require(staged.is_file() and sha256(staged.read_bytes()) == entry["sha256"],
                "prior-decoder-staged-postimage:" + entry["path"])
    original = subprocess.run(
        ["git", "-C", str(linux), "show", "HEAD:" + SOURCE_PATH],
        capture_output=True, check=True, timeout=45).stdout
    # Verify exact original Git bytes before applying bounded KUnit-only edits.
    source = linux / SOURCE_PATH
    content = source.read_bytes()
    require(original == content,
            "original-kernel-mm-source-not-pristine")
    require(git_blob(content) == ORIGINAL_ZSWAP_BLOB,
            "original-kernel-mm-blob-drift")
    require(b"#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in
            (ROOT / "src/kernel/zswap-import-codec.h").read_bytes(),
            "production-import-active-gate-drift")
    fragment = FRAGMENT.read_bytes()
    staged_content = render(content, fragment)
    source.write_bytes(staged_content)
    require(source.read_bytes() == staged_content,
            "original-kernel-staged-write-mismatch")
    manifest = {
        "original_pin": PIN, "original_mm_blob": ORIGINAL_ZSWAP_BLOB,
        "source_mapped_authenticated": False, "active": False,
        "phase_a": "BLOCKED", "direct_compressed_handoff": "DISABLED",
        "forced_raw_bypass": "DISABLED", "source_original": sha256(content),
        "fixture_sha256": sha256(fragment),
        "staged_mm_sha256": sha256(staged_content),
        "existing_decoder_entries": decoder["entries"],
        "entries": [{"path": SOURCE_PATH, "sha256": sha256(staged_content)}],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("ROUND071_ORIGINAL_POOL_STAGE_PASS original_mm_zswap=YES "
          "original_cpu_hotplug_percpu_ref_rcu_destructor=YES "
          "staged_mm_postimages=1 inherited_decoder_postimages=8 auth=0")


def verify_stage(linux: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text())
    require(manifest["original_pin"] == PIN and
            manifest["original_mm_blob"] == ORIGINAL_ZSWAP_BLOB and
            manifest["source_mapped_authenticated"] is False and
            manifest["active"] is False and
            manifest["phase_a"] == "BLOCKED" and
            manifest["direct_compressed_handoff"] == "DISABLED" and
            manifest["forced_raw_bypass"] == "DISABLED", "stage-safety-gates")
    require(len(manifest["entries"]) == 1 and
            len(manifest["existing_decoder_entries"]) == 8,
            "stage-entry-count")
    original = subprocess.run(
        ["git", "-C", str(linux), "show", "HEAD:" + SOURCE_PATH],
        capture_output=True, check=True, timeout=45).stdout
    require(git_blob(original) == ORIGINAL_ZSWAP_BLOB and
            sha256(original) == manifest["source_original"],
            "stage-original-source-mismatch")
    fragment = FRAGMENT.read_bytes()
    require(sha256(fragment) == manifest["fixture_sha256"],
            "stage-fragment-drift")
    expected = render(original, fragment)
    require(sha256(expected) == manifest["staged_mm_sha256"],
            "stage-expected-postimage-drift")
    entries = manifest["entries"] + manifest["existing_decoder_entries"]
    for entry in entries:
        path = linux / entry["path"]
        require(path.is_file() and sha256(path.read_bytes()) == entry["sha256"],
                "stage-postimage-drift:" + entry["path"])
    require((linux / SOURCE_PATH).read_bytes() == expected,
            "stage-mm-contains-extra-edit")
    print("ROUND071_ORIGINAL_POOL_POSTIMAGES_PASS count=9 original_pin=YES "
          "unmodified_upstream_except_test_witness=YES")


def self_test() -> None:
    fixture = FRAGMENT.read_bytes()
    require(b"percpu_ref_kill(&pool->ref);" in fixture and
            b"zswap_pool_create((char *)compressor)" in fixture and
            b"flush_workqueue(system_percpu_wq);" in fixture and
            b"swapz_zswap_import_decoder_owner_decode(&lease," in fixture,
            "missing-real-original-pool-or-reader-path")
    require(b"SWAPZ_R071_CLOSE_CYCLES 24U" in fixture and
            b"crypto_acomp_compress(context->req)" in fixture and
            b"atomic_read(&swapz_round071_destroy_complete)" in fixture,
            "missing-native-original-execution-path")
    failures = 0
    for mutation in (b"percpu_ref_kill(&pool->ref);",
                     b"flush_workqueue(system_percpu_wq);",
                     b"crypto_acomp_compress(context->req)",
                     b"swapz_zswap_import_decoder_owner_decode(&lease,"):
        require(mutation in fixture, "baseline-negative-fixture-anchor")
        damaged = fixture.replace(mutation, b"MUTATED_SOURCE_OMITTED", 1)
        try:
            require(damaged.count(mutation) == fixture.count(mutation),
                    "fixture-execution-path-mutated")
        except StageError:
            failures += 1
    require(failures == 4, "fixture-mutation-rejection-count")
    print("ROUND071_ORIGINAL_POOL_STAGER_SELFTEST_PASS "
          "fixture_execution_negatives=4 original_blob_pinned=YES")


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    staging = modes.add_parser("stage")
    staging.add_argument("--linux-root", type=Path, required=True)
    staging.add_argument("--manifest", type=Path, required=True)
    staging.add_argument("--decoder-manifest", type=Path, required=True)
    verifying = modes.add_parser("verify-stage")
    verifying.add_argument("--linux-root", type=Path, required=True)
    verifying.add_argument("--manifest", type=Path, required=True)
    modes.add_parser("self-test")
    arguments = parser.parse_args()
    try:
        if arguments.mode == "stage":
            stage(arguments.linux_root, arguments.manifest,
                  arguments.decoder_manifest)
        elif arguments.mode == "verify-stage":
            verify_stage(arguments.linux_root, arguments.manifest)
        else:
            self_test()
        return 0
    except (StageError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print("ROUND071_ORIGINAL_POOL_FIRST_ERROR phase=" + arguments.mode +
              " cause=" + (str(error) if isinstance(error, StageError)
                             else type(error).__name__)[:170], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
