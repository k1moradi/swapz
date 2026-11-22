#!/usr/bin/env python3
"""Round058 original Linux source BIO observation, no current DM authority.

Reuses the already frozen original 66 + four clone stager and verifier. Only
adds a guarded original block/BIO source witness at real MM dispatch and one
native KUnit of source-backed zero-vcnt and borrowed clone lifetime.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "runtime/native/fixtures"
SOURCE = FIXTURES / "round058-original-stored-bio-chain.cfrag"
KUNIT = FIXTURES / "round058-original-stored-bio-chain-kunit.cfrag"
HOST = FIXTURES / "round058-original-stored-bio-host.c"
PINNED = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
GUARD = "#if defined(SWAPZ_ROUND058_ORIGINAL_STORED_BIO_CHAIN_TEST) && \\\n    defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \\\n    defined(SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST) && \\\n    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \\\n    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \\\n    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \\\n    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY)"
SUITE = "swapz_round058_original_stored_bio_no_authority"
CASE = "swapz_round058_original_stored_bio_chain_kunit"
PASS = "ROUND058_CHAIN_HOST_ORIGINAL_SOURCE_C_PASS scenarios=23"
MUTANTS = (
    ("bio->bi_vcnt || !bio->bi_io_vec", "false || !bio->bi_io_vec"),
    ("bio->bi_iter.bi_size != 4096U", "false"),
    ("(bio->bi_flags & (1U << BIO_CLONED))", "false"),
    ("bio->bi_iter.bi_sector < 8U", "false"),
    ("bio->bi_iter.bi_sector % 8U", "false"),
    ("!memcmp(digest, owner->original_sha256, sizeof(digest))", "true"),
    ("!folio_test_swapcache(source_folio)", "(folio_test_swapcache(source_folio) && false)"),
    ("owner->source_swap_entry != source_folio->swap.val", "false"),
    ("!folio_test_uptodate(source_folio)", "(folio_test_uptodate(source_folio) && false)"),
    ("!folio_test_writeback(source_folio)", "(folio_test_writeback(source_folio) && false)"),
)


class FirstError(RuntimeError):
    pass


def replace_once(source: str, old: str, new: str, label: str) -> str:
    occurrences = source.count(old)
    if occurrences != 1:
        raise FirstError(f"first_error={label}:anchor_count={occurrences}")
    return source.replace(old, new, 1)


def verify_fixture(source: str, kunit: str) -> None:
    if source.count("/* ROUND058_ORIGINAL_STORED_BIO_CHAIN_BEGIN */") != 1 or \
       source.count("/* ROUND058_ORIGINAL_STORED_BIO_CHAIN_END */") != 1 or \
       kunit.count("/* ROUND058_ORIGINAL_STORED_BIO_KUNIT_BEGIN */") != 1 or \
       kunit.count("kunit_test_suite(swapz_round058_original_chain_suite);") != 1:
        raise FirstError("first_error=round058_original_fixture_drift")
    for required in ("bio->bi_vcnt ||", "sha256(original, 4096U, digest)",
                     "owner->original_sha256", "swapz_ci_owned_put(owner)",
                     "folio_test_swapcache(source_folio)",
                     "!folio_test_uptodate(source_folio)",
                     "!folio_test_writeback(source_folio)",
                     "owner->source_swap_entry != source_folio->swap.val",
                     "return -EOPNOTSUPP;", "bio->bi_iter.bi_sector % 8U"):
        if required not in (source + kunit):
            raise FirstError("first_error=source_safety_anchor_missing:" + required)


def stage(original: Path, manifest_path: Path) -> None:
    source = SOURCE.read_text(encoding="utf-8")
    kunit = KUNIT.read_text(encoding="utf-8")
    verify_fixture(source, kunit)
    # Existing stager verifies pristine original Git HEAD, individual Git blobs
    # and absence of dirty original Linux files before ANY source mutation.
    inherited = runpy.run_path(str(HERE / "round056-original-clone-stage.py"),
                               run_name="round058_reuse_native70_stager")
    inherited_path = manifest_path.with_name(manifest_path.stem + "-original70.json")
    inherited["stage"](original, inherited_path)
    previous = json.loads(inherited_path.read_text(encoding="utf-8"))
    if previous.get("original_sha") != PINNED or \
       previous.get("positive_source_target_authorization") is not False:
        raise FirstError("first_error=original70_inherited_manifest_drift")
    # Every inherited guarded change belongs in the aggregate manifest.
    inherited_owned = {"block/bio.c", "include/linux/bio.h",
                       "include/linux/blk_types.h", "drivers/md/dm.c"}
    if set(previous.get("own_changed_paths", [])) != inherited_owned or \
       previous.get("default_guard") != "SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST":
        raise FirstError("first_error=original70_owned_path_manifest_drift")
    for path, key in (
        ("block/bio.c", "original_block_bio_sha256"),
        ("include/linux/bio.h", "original_bio_header_sha256"),
        ("include/linux/blk_types.h", "original_blk_types_sha256"),
        ("drivers/md/dm.c", "original_dm_sha256"),
    ):
        if hashlib.sha256((original / path).read_bytes()).hexdigest() != previous.get(key):
            raise FirstError("first_error=original70_postimage_drift:" + path)

    bio_path = original / "block/bio.c"
    bio_header_path = original / "include/linux/bio.h"
    page_path = original / "mm/page_io.c"
    bio = bio_path.read_text(encoding="utf-8")
    header = bio_header_path.read_text(encoding="utf-8")
    page = page_path.read_text(encoding="utf-8")

    # Source function is compiled only in the original block/bio.c after the
    # inherited guarded owner functions. Its returned 0 is observational only.
    if bio.count("swapz_round056_owned_seal_source_v1") < 1 or \
       bio.count("swapz_round056_attach_original") < 1:
        raise FirstError("first_error=original70_source_owner_missing")
    bio = bio.rstrip("\n") + "\n\n" + source.rstrip("\n") + "\n\n" + kunit.rstrip("\n") + "\n"
    declaration = GUARD + "\nint swapz_round058_source_bio_observe(const struct bio *bio);\n#endif\n"
    header_anchor = "#endif /* __LINUX_BIO_H */"
    if header_anchor not in header:
        raise FirstError("first_error=original_bio_header_guard_drift")
    header = replace_once(header, header_anchor, declaration + header_anchor,
                          "original_bio_header_placement")

    write_start = page.find("static void swap_bdev_submit_write(struct swap_io_ctx *ctx)")
    read_start = page.find("static void swap_bdev_submit_read(struct swap_io_ctx *ctx)")
    if write_start < 0 or read_start <= write_start:
        raise FirstError("first_error=original_native_write_submit_missing")
    original_write = page[write_start:read_start]
    source_sector = "\tbio->bi_iter.bi_sector = swap_folio_sector(bio_first_folio_all(bio));\n"
    hook = (GUARD + "\n\t/* Observe the original uncompressed 4096-byte BIO only. No ACK. */\n"
            "\tif (bio->bi_swapz_ci_sideband)\n"
            "\t\t(void)swapz_round058_source_bio_observe(bio);\n#endif\n")
    changed_write = replace_once(original_write, source_sector,
                                 source_sector + hook,
                                 "original_source_only_after_bdev_sector")
    page = page[:write_start] + changed_write + page[read_start:]
    if "folio_start_writeback(folio);\n\tfolio_unlock(folio);" not in page or \
       "bio_uninit(bio);\n\tswap_write_end(sio, failed);" not in page:
        raise FirstError("first_error=original_pg_writeback_or_endio_lifetime_drift")
    for path, data in ((bio_path, bio), (bio_header_path, header), (page_path, page)):
        path.write_text(data, encoding="utf-8")
    changed_paths = sorted({entry["path"] for entry in
                            json.loads((manifest_path.with_name(manifest_path.stem + "-original70-inherited66.json")).read_text())["changed_paths"]}
                           | inherited_owned | {"mm/page_io.c"})
    manifest = {
        "original_sha": PINNED,
        "inherited70_manifest": str(inherited_path),
        "original_blobs_verified_by_inherited_stager": True,
        "guard_default_undefined": "SWAPZ_ROUND058_ORIGINAL_STORED_BIO_CHAIN_TEST",
        "changed_paths": [{"path": path, "sha256": hashlib.sha256(
            (original / path).read_bytes()).hexdigest()} for path in changed_paths],
        "native_original66_plus4_plus1": 71,
        "source_mapped_authenticated": False,
        "physical_or_loaded_kernel": False,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("ROUND058_ORIGINAL_PINNED_CHAIN_STAGED source=" + PINNED +
          " original_blob_manifest=VERIFIED default=OFF native_cases=71 AUTH0")


def compile_execute(compiler: str, fragment: str, template: str, scratch: Path,
                    index: int) -> None:
    staged = replace_once(template, "/* ROUND058_INJECT_SOURCE */",
                          fragment, "host_fragment_injection")
    source_path = scratch / f"{compiler}-{index}.c"
    binary_path = scratch / f"{compiler}-{index}"
    source_path.write_text(staged, encoding="utf-8")
    command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
               "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
               str(source_path), "-o", str(binary_path), "-lcrypto"]
    built = subprocess.run(command, capture_output=True, text=True, timeout=80)
    if built.returncode:
        raise FirstError(f"first_error=compiler:{compiler}:{index}:")
    run = subprocess.run([str(binary_path)], capture_output=True, text=True,
                         timeout=80, env={**os.environ,
                                          "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                          "UBSAN_OPTIONS": "halt_on_error=1"})
    if index == 0:
        if run.returncode or PASS not in run.stdout:
            raise FirstError(f"first_error=source_baseline:{compiler} exit={run.returncode} " + run.stderr[-800:])
    elif run.returncode != 1 or "ROUND058_CHAIN_FIRST_ERROR" not in run.stderr or \
         "AddressSanitizer" in run.stderr or "runtime error:" in run.stderr:
        raise FirstError(f"first_error=mutant_not_semantic:{compiler}:{index} exit={run.returncode} " + run.stderr[-800:])


def host_test() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    verify_fixture(source, KUNIT.read_text(encoding="utf-8"))
    template = HOST.read_text(encoding="utf-8")
    if template.count("/* ROUND058_INJECT_SOURCE */") != 1:
        raise FirstError("first_error=missing_original_C_host_fixture_hook")
    with tempfile.TemporaryDirectory(prefix="round058-original-source-bio-") as path:
        scratch = Path(path)
        for compiler in ("gcc", "clang"):
            if not shutil.which(compiler):
                raise FirstError("first_error=missing_compiler:" + compiler)
            compile_execute(compiler, source, template, scratch, 0)
            for index, (old, new) in enumerate(MUTANTS, start=1):
                mutated = replace_once(source, old, new, f"mutation_anchor_{index}")
                compile_execute(compiler, mutated, template, scratch, index)
            print(f"ROUND058_REAL_SOURCE_{compiler.upper()}_GNU11_ASAN_UBSAN_PASS "
                  f"scenarios=19 changed_C_mutants={len(MUTANTS)} AUTH0")


def kernel_verify(document: object, kernel_log: str) -> None:
    inherited = runpy.run_path(str(HERE / "round056-original-clone-verify.py"),
                               run_name="round058_inherited_native70_verifier")
    inherited["kernel_verify"](document, kernel_log)
    if not isinstance(document, dict) or \
       kernel_log.count("# Subtest: " + SUITE) != 1:
        raise FirstError("first_error=missing_new_original_KTAP_suite")
    pending = [document]
    matches = []
    while pending:
        group = pending.pop()
        if not isinstance(group, dict):
            raise FirstError("first_error=invalid_original_KUnit_JSON_group")
        if group.get("name") == SUITE:
            matches.append(group)
        children = group.get("sub_groups", [])
        if not isinstance(children, list):
            raise FirstError("first_error=invalid_original_KUnit_JSON_children")
        pending.extend(children)
    if len(matches) != 1:
        raise FirstError("first_error=missing_duplicate_new_actual_source_C_suite")
    cases = matches[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != 1 or \
       cases[0].get("name") != CASE or cases[0].get("status") != "PASS":
        raise FirstError("first_error=original_source_BIO_C_KUnit_not_PASS")
    misc = matches[0].get("misc", {})
    if any(type(misc.get(name)) is not int or misc[name] != value for name, value in
           (("tests", 1), ("passed", 1), ("failed", 0), ("skipped", 0),
            ("crashed", 0), ("errors", 0))):
        raise FirstError("first_error=original_source_BIO_native_C_KUnit_totals")
    matched_lines = [line for line in kernel_log.splitlines() if
                     re.search(r"\bok\s+\d+\s+(?:-\s+)?" + CASE + r"\b", line)]
    if len(matched_lines) != 1 or re.search(r"(?i)(Kernel panic|KASAN:|UBSAN:|not ok\s+\d+\s+swapz_round058)", kernel_log):
        raise FirstError("first_error=new_original_kernel_KTAP_negative_or_missing")


def verifier_self_test() -> None:
    inherited = runpy.run_path(str(HERE / "round056-original-clone-verify.py"),
                               run_name="round058_inherited_KTAP_sample")
    baseline_module = runpy.run_path(str(HERE / "round054-original-preunuse-kunit-verify.py"),
                                     run_name="round058_inherited_original66_sample")
    sample, log = baseline_module["sample"]()
    clone_new = sorted(inherited["NEW"])
    sample["sub_groups"].append({"name": inherited["SUITE"], "sub_groups": [],
                                "test_cases": [{"name": case, "status": "PASS"} for case in clone_new],
                                "misc": {"tests": 4, "passed": 4, "failed": 0, "skipped": 0, "crashed": 0, "errors": 0}})
    log += "# Subtest: " + inherited["SUITE"] + "\n"
    log += "".join(f"    ok {index} {name}\n" for index, name in enumerate(clone_new, 1))
    sample["sub_groups"].append({"name": SUITE, "sub_groups": [],
                                "test_cases": [{"name": CASE, "status": "PASS"}],
                                "misc": {"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "crashed": 0, "errors": 0}})
    log += "# Subtest: " + SUITE + "\n    ok 1 " + CASE + "\n"
    kernel_verify(sample, log)
    rejected = 0
    for index in range(4):
        changed = copy.deepcopy(sample)
        hostile_log = log
        if index == 0:
            changed["sub_groups"][-1]["test_cases"][0]["status"] = "FAIL"
        elif index == 1:
            changed["sub_groups"][-1]["misc"]["passed"] = 0
        elif index == 2:
            changed["sub_groups"].append(copy.deepcopy(changed["sub_groups"][-1]))
        else:
            hostile_log = hostile_log.replace("# Subtest: " + SUITE, "# Subtest: forged")
        try:
            kernel_verify(changed, hostile_log)
        except (FirstError, inherited["VerificationError"]):
            rejected += 1
        else:
            raise FirstError(f"first_error=forged_original_JSON_KTAP_accepted:{index}")
    print(f"ROUND058_ORIGINAL_71_JSON_KTAP_VERIFIER_SELFTEST_PASS forged={rejected}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("host-test", "stage", "kernel-verify", "verifier-self-test"))
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    options = parser.parse_args()
    try:
        if options.mode == "host-test":
            host_test()
        elif options.mode == "stage":
            if not options.linux_root or not options.manifest:
                parser.error("stage requires --linux-root and --manifest")
            stage(options.linux_root.resolve(strict=True), options.manifest.resolve())
        elif options.mode == "verifier-self-test":
            verifier_self_test()
        else:
            if not options.result or not options.kernel_log:
                parser.error("kernel-verify requires --result and --kernel-log")
            kernel_verify(json.loads(options.result.read_text()),
                          options.kernel_log.read_text())
            print("ROUND058_ORIGINAL_PINNED_NATIVE_71_C_KUNIT_JSON_KTAP_PASS AUTH0 PHASE_A=BLOCKED")
        return 0
    except (FirstError, OSError, ValueError, subprocess.TimeoutExpired,
            RuntimeError, KeyError, IndexError) as error:
        print("ROUND058_ORIGINAL_STORED_BIO_FIRST_ERROR reason=" + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
