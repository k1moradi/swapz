#!/usr/bin/env python3
"""Real pinned-block clone ticket: rootless C mutation tests and original UML KTAP.

Host fixture compiles the exact default-undefined C helper inserted into
original block/bio.c by the independent stager. Kernel mode additionally
requires the original 66 registered KUnit and four actual new C tests.
"""
from __future__ import annotations

import argparse
import copy
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
HOOKS_FILE = FIXTURES / "round056-original-clone-hooks.cfrag"
HOST_FILE = FIXTURES / "round056-original-clone-host.c"
FIRST_ERROR = "ROUND056_CLONE_FIRST_ERROR"
PASS = "ROUND056_CLONE_HOST_C_PASS cases=84"
SUITE = "swapz_round056_original_clone_ticket_only"
NEW = frozenset((
    "swapz_round056_actual_init_clone_endio_kunit",
    "swapz_round056_actual_split_trim_kunit",
    "swapz_round056_actual_requeue_reset_kunit",
    "swapz_round056_actual_clone_failure_kunit",
))
MUTATIONS = (
    ("source->bi_iter.bi_size != SWAPZ_ROUND056_PAGE_BYTES", "false"),
    ("vector->bv_len != SWAPZ_ROUND056_PAGE_BYTES", "false"),
    ("bio_flagged(source, BIO_CLONED) ||", "false ||"),
    ("!(source->bi_opf & REQ_SWAP) ||", "false ||"),
    ("source->bi_iter.bi_sector % SWAPZ_ROUND056_PAGE_SECTORS", "false"),
    ("clone->bi_io_vec == ticket->source_vectors", "true"),
    ("clone->bi_iter.bi_sector == ticket->sector", "true"),
    ("clone->bi_iter.bi_size == SWAPZ_ROUND056_PAGE_BYTES", "true"),
    ("clone->bi_round056_clone_device == clone->bi_bdev", "true"),
    ("!clone->bi_round056_candidate", "false"),
    ("!bio_flagged(clone, BIO_CLONED)", "false"),
    ("!clone->bi_iter.bi_idx", "true"),
    ("!clone->bi_iter.bi_offset", "true"),
    ("bio_op(clone) == REQ_OP_WRITE", "true"),
    ("(clone->bi_opf & REQ_SWAP);", "true;"),
    ("bio->bi_round056_candidate = false;\n}\n\nstatic struct swapz_round056_clone_ticket *",
     "bio->bi_round056_candidate = true;\n}\n\nstatic struct swapz_round056_clone_ticket *"),
)


class VerificationError(RuntimeError):
    """The first source-bound compiler, semantic oracle or kernel evidence failure."""


def read_hook() -> str:
    hooks = HOOKS_FILE.read_text()
    if hooks.count("/* ROUND056_ORIGINAL_CLONE_HOOKS_BEGIN */") != 1 or \
       hooks.count("/* ROUND056_ORIGINAL_CLONE_HOOKS_END */") != 1:
        raise VerificationError("first_error=missing_or_duplicate_guarded_source_markers")
    for marker in ("swapz_round056_drop_clone_ticket", "refcount_dec_and_test",
                   "swapz_round056_invalidate_clone", "swapz_round056_propagate_full_clone",
                   "swapz_round056_complete_clone_view", "SWAPZ_ROUND056_PAGE_BYTES 4096U",
                   "SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST"):
        if marker not in hooks:
            raise VerificationError("first_error=guarded_source_missing:" + marker)
    return hooks


def compose(hooks: str) -> str:
    fixture = HOST_FILE.read_text()
    if fixture.count("/* ROUND056_INJECT_GUARDED_C */") != 1 or \
       "scenario < 28U" not in fixture or "ROUND056_CLONE_HOST_C_PASS cases=%u" not in fixture:
        raise VerificationError("first_error=host_fixture_drift")
    return fixture.replace("/* ROUND056_INJECT_GUARDED_C */", hooks, 1)


def compile_execute(compiler: str, source: str, scratch: Path,
                    label: str, hostile: bool) -> None:
    source_path = scratch / (label + ".c")
    executable_path = scratch / label
    source_path.write_text(source)
    command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
               "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
               str(source_path), "-o", str(executable_path)]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=80)
    if compiled.returncode:
        raise VerificationError("first_error=compiler label=" + label +
                                " rc=" + str(compiled.returncode) +
                                " stderr=" + compiled.stderr[-3500:])
    env = {**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    executed = subprocess.run([str(executable_path)], capture_output=True, text=True,
                              timeout=80, env=env)
    if hostile:
        if executed.returncode != 1 or FIRST_ERROR not in executed.stderr or \
           "AddressSanitizer" in executed.stderr or "runtime error:" in executed.stderr:
            raise VerificationError("first_error=mutant_not_semantic label=" + label +
                                    " exit=" + str(executed.returncode) +
                                    " stderr=" + executed.stderr[-2500:])
    elif executed.returncode != 0 or PASS not in executed.stdout:
        raise VerificationError("first_error=baseline_runtime label=" + label +
                                " exit=" + str(executed.returncode) +
                                " stderr=" + executed.stderr[-3500:])


def host_test() -> None:
    original_hooks = read_hook()
    original = compose(original_hooks)
    for old, replacement in MUTATIONS:
        if old not in original_hooks or old == replacement:
            raise VerificationError("first_error=mutation_anchor_missing:" + old[:100])
    with tempfile.TemporaryDirectory(prefix="round056-real-clone-source-") as directory:
        scratch = Path(directory)
        for compiler in ("gcc", "clang"):
            if not shutil.which(compiler):
                raise VerificationError("first_error=missing_compiler:" + compiler)
            compile_execute(compiler, original, scratch, compiler + "-original", False)
            print("ROUND056_REAL_GUARDED_CLONE_" + compiler.upper() +
                  "_84_GNU11_ASAN_UBSAN_CASES_PASS")
            for number, (old, replacement) in enumerate(MUTATIONS):
                mutated = original_hooks.replace(old, replacement, 1)
                compile_execute(compiler, compose(mutated), scratch,
                                compiler + "-changed-actual-C-" + str(number), True)
            print("ROUND056_REAL_GUARDED_CLONE_" + compiler.upper() +
                  "_16_CHANGED_C_BINARIES_SEMANTIC_ORACLE_PASS")


def kernel_verify(document: object, kernel_log: str) -> None:
    inherited = runpy.run_path(str(HERE / "round054-original-preunuse-kunit-verify.py"),
                               run_name="round056_inherited66_kernel_verifier")
    try:
        inherited["verify"](document, kernel_log)
    except Exception as error:
        raise VerificationError("first_error=inherited_original66:" + str(error)) from error
    if not isinstance(document, dict) or kernel_log.count("# Subtest: " + SUITE) != 1:
        raise VerificationError("first_error=missing_duplicate_original_clone_KTAP_suite")
    groups = [document]
    matched = []
    visited = 0
    while groups:
        group = groups.pop()
        visited += 1
        if visited > 1200 or not isinstance(group, dict):
            raise VerificationError("first_error=invalid_original_JSON_group")
        if group.get("name") == SUITE:
            matched.append(group)
        children = group.get("sub_groups", [])
        if not isinstance(children, list) or len(children) > 250:
            raise VerificationError("first_error=invalid_original_JSON_children")
        groups.extend(children)
    if len(matched) != 1:
        raise VerificationError("first_error=missing_duplicate_new_original_suite")
    cases = matched[0].get("test_cases")
    if not isinstance(cases, list) or len(cases) != 4 or \
       {x.get("name") for x in cases if isinstance(x, dict)} != NEW or \
       any(not isinstance(x, dict) or x.get("status") != "PASS" for x in cases):
        raise VerificationError("first_error=actual_clone_C_KUnit_cases_not_all_pass")
    misc = matched[0].get("misc")
    if not isinstance(misc, dict):
        raise VerificationError("first_error=actual_clone_C_KUnit_totals_missing")
    for name, expected in (("tests", 4), ("passed", 4), ("failed", 0),
                           ("skipped", 0), ("crashed", 0), ("errors", 0)):
        if type(misc.get(name)) is not int or misc[name] != expected:
            raise VerificationError("first_error=actual_clone_KUnit_total:" + name)
    seen = []
    for raw in kernel_log.splitlines():
        cleaned = re.sub(r"^\[\s*\d+\.\d+\]\s*", "", raw).strip()
        matched_line = re.fullmatch(r"ok\s+\d+\s+(?:-\s+)?([A-Za-z0-9_]+)(?:\s+#.*)?", cleaned)
        if matched_line and matched_line.group(1) in NEW:
            seen.append(matched_line.group(1))
    if len(seen) != 4 or set(seen) != NEW or \
       re.search(r"(?i)(?:Kernel panic|KASAN:|UBSAN:|not ok\s+\d+\s+swapz_round056)", kernel_log):
        raise VerificationError("first_error=actual_clone_KTAP_negative_or_missing")


def verifier_self_test() -> None:
    inherited = runpy.run_path(str(HERE / "round054-original-preunuse-kunit-verify.py"),
                               run_name="round056_original66_negative_fixture")
    parent, parent_log = inherited["sample"]()
    cases = sorted(NEW)
    parent["sub_groups"].append({
        "name": SUITE, "sub_groups": [],
        "test_cases": [{"name": name, "status": "PASS"} for name in cases],
        "misc": {"tests": 4, "passed": 4, "failed": 0,
                 "skipped": 0, "crashed": 0, "errors": 0},
    })
    parent_log += "[    0.110] # Subtest: " + SUITE + "\n"
    parent_log += "".join(f"[    0.111]     ok {i} {name}\n"
                           for i, name in enumerate(cases, 1))
    kernel_verify(parent, parent_log)
    rejected = 0
    for mutation in range(10):
        bad = copy.deepcopy(parent)
        bad_log = parent_log
        if mutation < 4:
            bad["sub_groups"][-1]["test_cases"][mutation]["status"] = "FAIL"
        elif mutation < 6:
            bad["sub_groups"][-1]["misc"]["passed"] -= 1
        elif mutation == 6:
            bad["sub_groups"][-1]["test_cases"][0]["name"] = "fake"
        elif mutation == 7:
            bad["sub_groups"].append(copy.deepcopy(bad["sub_groups"][-1]))
        elif mutation == 8:
            bad_log = bad_log.replace("# Subtest: " + SUITE, "# Subtest: replaced", 1)
        else:
            bad_log += "[    0.111] not ok 4 swapz_round056_actual_clone_failure_kunit\n"
        try:
            kernel_verify(bad, bad_log)
        except VerificationError:
            rejected += 1
        else:
            raise VerificationError("first_error=forged_kernel_evidence_accepted:" + str(mutation))
    print("ROUND056_ORIGINAL_66_PLUS_4_JSON_KTAP_VERIFIER_10_NEGATIVES_PASS "
          "SYNTHETIC_SELFTEST_ONLY")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("host-test", "verifier-self-test", "kernel-verify"))
    parser.add_argument("--result", type=Path)
    parser.add_argument("--kernel-log", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.mode == "host-test":
            host_test()
        elif arguments.mode == "verifier-self-test":
            verifier_self_test()
        else:
            if not arguments.result or not arguments.kernel_log:
                parser.error("kernel-verify requires --result and --kernel-log")
            result = json.loads(arguments.result.read_text())
            log = arguments.kernel_log.read_text()
            kernel_verify(result, log)
            print("ROUND056_ORIGINAL_UML_66_INHERITED_PLUS_4_ACTUAL_BIO_CLONE_C_KUNIT_PASS "
                  "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")
        return 0
    except (VerificationError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print("ROUND056_ORIGINAL_CLONE_FIRST_ERROR phase=" + arguments.mode +
              " reason=" + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
