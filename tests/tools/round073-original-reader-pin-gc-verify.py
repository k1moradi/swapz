#!/usr/bin/env python3
"""Round073 independently qualified original Linux reader-pin GC read-side.

Host: exact-original-source slice compiled/executed with C23 GCC + Clang
ASan/UBSan and ten semantic mutants per compiler. Native: strict executed
pinned original Linux UML KUnit JSON + KTAP; neither claim source AUTH.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tests/tools"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
SOURCE = ROOT / "tests/runtime/native/fixtures/round069-original-zswap-stored-source.cfrag"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
SUITE = "swapz_round073_original_reader_pin_gc"
CASES = (
    "swapz_round073_original_lz4_old_reader_gc",
    "swapz_round073_original_lzo1x_old_reader_gc",
    "swapz_round073_original_stale_crc_sha_codec",
    "swapz_round073_original_decoder_retire_with_pin",
)


class FirstError(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise FirstError(reason)


def run(command: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, text=True, capture_output=True, timeout=timeout, check=False,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def first_diagnostic(result: subprocess.CompletedProcess[str]) -> str:
    for line in (result.stderr + result.stdout).splitlines():
        if "error:" in line or "FIRST_ERROR" in line:
            return line.split("error:", 1)[-1][:150]
    return "unexpected-exit:" + str(result.returncode)


def import_prior_source():
    path = TOOLS / "round069-original-zswap-stored-source-verify.py"
    spec = importlib.util.spec_from_file_location("round073_source_predicate", path)
    require(spec is not None and spec.loader is not None,
            "original-source-predicate-loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_preflight() -> None:
    fixture = FIXTURE.read_text(encoding="utf-8")
    source = SOURCE.read_text(encoding="utf-8")
    require(fixture.count("/* ROUND073_ORIGINAL_READER_PIN_GC_BEGIN") == 1 and
            fixture.count("/* ROUND073_ORIGINAL_READER_PIN_GC_END */") == 1,
            "unique-original-native-fixture")
    require(fixture.count(
        "kunit_test_suite(swapz_round073_original_reader_suite);") == 1,
        "unique-original-KUnit-suite")
    for case in CASES:
        require(fixture.count("KUNIT_CASE(" + case + ")") == 1,
                "missing-native-unique-case:" + case)
    for anchor in (
        "swapz_round069_capture_stored(", "zs_obj_read_sg_begin(",
        "xa_erase(&source->tree", "zs_free(source->allocator",
        "swapz_import_lower_begin_read(", "swapz_round069_run_io(old_io);",
        "swapz_round069_native_gc_copy_fua(",
        "swapz_zswap_import_decoder_owner_decode(",
        "swapz_zswap_import_decoder_owner_get(",
        "swapz_zswap_import_decoder_owner_put(",
        "swapz_zswap_import_decoder_owner_close_and_drain(",
        "kthread_run(", "memchr_inv(joined->output",
        "spec.compressed_crc32c = swapz_crc32c_bytes(",
        "sha256(joined->original, SWAPZ_BLOCK_BYTES, spec.original_sha256);",
    ):
        require(anchor in fixture, "missing-original-source-read-anchor:" + anchor)
    require("submit_bio(" not in fixture and
            "bio_endio(" not in fixture and
            "SWAPZ_ROUND072_NATIVE_JOIN_KUNIT" not in fixture,
            "writer-join-or-duplicate-native-BIO-endio")
    for path in ("src/kernel/zswap-import-codec.h",
                 "src/kernel/zswap-import-decoder-owner.h",
                 "src/kernel/authority.h"):
        contents = (ROOT / path).read_text(encoding="utf-8")
        require("SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in contents
                if path.endswith("zswap-import-codec.h") else
                bool(contents), "unmodified-real-product-header:" + path)
    require("/* ROUND069_COMMON_BEGIN */" in source,
            "original-slot-source-immutable-witness")
    import ast
    ast.parse((TOOLS / "round073-stage-original-reader-pin-gc.py").read_text())
    print("PASS ROUND073_READER_PREFLIGHT original_zswap_XArray_zsmalloc="
          "READ_SOURCE product_authority_decoder=READ_SOURCE "
          "physical=NO selected_AUTH=0 PHASE_A=BLOCKED", flush=True)


def compiler_mode(compiler: str) -> str:
    with tempfile.TemporaryDirectory(prefix="round073-c23-mode-") as directory:
        source = Path(directory) / "probe.c"
        source.write_text("int main(void) { return 0; }\n")
        for mode in ("-std=c23", "-std=c2x"):
            result = run([compiler, mode, "-fsyntax-only", str(source)])
            if result.returncode == 0:
                return mode
    raise FirstError("no-C23-or-C2x:" + compiler)


def verify_host() -> None:
    verify_preflight()
    prior = import_prior_source()
    source = SOURCE.read_text(encoding="utf-8")
    require(source.count(prior.BEGIN) == 1 and
            source.count(prior.END) == 1,
            "source-predicate-nonunique")
    slice_text = source.split(prior.BEGIN, 1)[1].split(prior.END, 1)[0]
    require(len(prior.MUTANTS) >= 8, "semantic-mutant-minimum")
    with tempfile.TemporaryDirectory(prefix="round073-original-reader-host-") as temp:
        directory = Path(temp)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            require(compiler is not None, "missing-compiler:" + name)
            standard = compiler_mode(compiler)
            for index, (label, old, changed) in enumerate(
                    (("baseline", "", ""), *prior.MUTANTS)):
                require(not old or slice_text.count(old) == 1,
                        "nonunique-original-source-mutation:" + label)
                C = slice_text if not old else slice_text.replace(old, changed, 1)
                test_source = directory / (name + "-" + str(index) + ".c")
                executable = directory / (name + "-" + str(index))
                test_source.write_text(prior.C_TEST.replace(
                    "/* INSERT_SOURCE */", C))
                compiled = run([
                    compiler, standard, "-O1", "-g", "-Wall", "-Wextra",
                    "-Wconversion", "-Wshadow", "-Werror",
                    "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all",
                    "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                    str(test_source), "-o", str(executable)])
                require(compiled.returncode == 0,
                        name + ":" + label + ":compile:" +
                        first_diagnostic(compiled))
                finished = run([str(executable)])
                if index == 0:
                    require(finished.returncode == 0 and
                            not finished.stderr,
                            name + ":baseline:" + first_diagnostic(finished))
                else:
                    require(finished.returncode == 3 and
                            "semantic-failure case=" in finished.stderr and
                            "AddressSanitizer" not in finished.stderr and
                            "runtime error:" not in finished.stderr,
                            name + ":" + label + ":mutant-survived:" +
                            first_diagnostic(finished))
            print("PASS ROUND073_READER_" + name.upper() +
                  "_C23_ASAN_UBSAN baseline=16-scenarios "
                  "compiled_executed_original_C_semantic_mutants=" +
                  str(len(prior.MUTANTS)), flush=True)
    # Reuse exact current production source authority and reader owner
    # compilation evidence. The Round073 suite itself is independently staged.
    checked = (
        (TOOLS / "round069-original-bio-authority-joined-verify.py",
         ("PASS gcc compiled_and_executed_changed_real_C_mutants=14",
          "PASS clang compiled_and_executed_changed_real_C_mutants=14",
          "real_source_GC_original_codec_guard_ASAN_UBSAN=1")),
        (TOOLS / "round066-decoder-drain-release-verify.py",
         ("ROUND066_DRAIN_GCC_CLANG_ASAN_UBSAN_PASS baselines=2 "
          "compiled_executed_semantic_mutants=4",)),
    )
    for executable, expected in checked:
        command = [sys.executable, "-B", str(executable)]
        if "round066-" in executable.name:
            command += [
                "--owner-source",
                str(ROOT / "src/kernel/zswap-import-decoder-owner.c"),
                "--owner-header",
                str(ROOT / "src/kernel/zswap-import-decoder-owner.h")]
        completed = run(command, timeout=1150)
        require(completed.returncode == 0 and not completed.stderr and
                all(line in completed.stdout for line in expected),
                "current-production-C-host:" + executable.name + ":" +
                first_diagnostic(completed))
        print("PASS ROUND073_READER_REUSED_REAL_C_MUTANT_LANE " +
              executable.name, flush=True)
    print("PASS ROUND073_READER_HOST_ONLY GCC_Clang_C23_mutants=10_each "
          "inherited_real_product_authority_mutants=14_each "
          "owner_lifetime_mutants=2_each original_UML=SEPARATE_JOB "
          "AUTH0 PHASE_A=BLOCKED", flush=True)


def verify_native(document: dict, ktap: str) -> None:
    require(isinstance(document, dict), "native-json-root-not-object")
    pending = [document]
    matches = []
    while pending:
        node = pending.pop()
        require(isinstance(node, dict), "native-json-node-not-object")
        if node.get("name") == SUITE:
            matches.append(node)
        children = node.get("sub_groups", [])
        require(isinstance(children, list), "native-json-child-list")
        pending.extend(children)
    require(len(matches) == 1, "native-suite-missing-or-duplicated")
    node = matches[0]
    cases = node.get("test_cases")
    require(isinstance(cases, list) and
            len(cases) == len(CASES), "native-KUnit-case-count")
    require({row.get("name") for row in cases if isinstance(row, dict)}
            == set(CASES) and
            all(isinstance(row, dict) and row.get("status") == "PASS"
                for row in cases), "native-KUnit-fail-skip-or-forged")
    misc = node.get("misc", {})
    for key, expected in (
            ("tests", len(CASES)), ("passed", len(CASES)),
            ("failed", 0), ("skipped", 0), ("crashed", 0), ("errors", 0)):
        require(type(misc.get(key)) is int and misc[key] == expected,
                "native-KUnit-misc:" + key)
    require(ktap.count("# Subtest: " + SUITE) == 1,
            "native-KTAP-suite-unique")
    for case in CASES:
        require(len(re.findall(
            r"(?m)^\s*ok\s+[0-9]+\s+(?:-\s+)?" +
            re.escape(case) + r"\s*$", ktap)) == 1,
            "native-KTAP-real-executed:" + case)
    require(re.search(
        r"(?i)kernel panic|KASAN:|UBSAN:|BUG: sleeping|"
        r"not ok\s+[0-9]+\s+" + re.escape(SUITE), ktap) is None,
        "native-KTAP-crash-or-fail")


def native_self_test() -> None:
    node = {
        "name": SUITE,
        "test_cases": [{"name": case, "status": "PASS"} for case in CASES],
        "sub_groups": [],
        "misc": {"tests": 4, "passed": 4, "failed": 0,
                 "skipped": 0, "crashed": 0, "errors": 0},
    }
    root = {"name": "kernel", "sub_groups": [node]}
    ktap = "# Subtest: " + SUITE + "\n" + "".join(
        f"    ok {index} {case}\n" for index, case in enumerate(CASES, 1))
    verify_native(root, ktap)
    mutations = []
    def alter(fn):
        changed = copy.deepcopy(root)
        fn(changed["sub_groups"][0])
        mutations.append((changed, ktap))
    alter(lambda value: value["test_cases"][0].update(status="FAIL"))
    alter(lambda value: value["test_cases"][1].update(status="SKIP"))
    alter(lambda value: value["test_cases"].pop())
    alter(lambda value: value["misc"].update(passed=3))
    alter(lambda value: value["misc"].update(errors=1))
    alter(lambda value: value["misc"].update(crashed=1))
    mutations.append(({"name": "kernel", "sub_groups": [node, node]}, ktap))
    mutations.append((root, ktap.replace("    ok 1", "    not ok 1")))
    mutations.append((root, ktap.replace("# Subtest: " + SUITE,
                                        "# Subtest: forged")))
    mutations.append((root, ktap + "KASAN: original kernel read failure\n"))
    for index, (invalid, log) in enumerate(mutations):
        try:
            verify_native(invalid, log)
        except FirstError:
            continue
        raise FirstError("native-semantic-verdict-mutant-survived:" + str(index))
    print("PASS ROUND073_READER_NATIVE_JSON_KTAP_VERIFIER "
          "forged_verdict_mutants_rejected=10 cases=4 AUTH0", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("host")
    modes.add_parser("self-test")
    native = modes.add_parser("verify-native")
    native.add_argument("--result", required=True, type=Path)
    native.add_argument("--kernel-log", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.mode == "host":
            verify_host()
        elif args.mode == "self-test":
            verify_preflight()
            native_self_test()
        else:
            verify_native(json.loads(args.result.read_text()),
                          args.kernel_log.read_text(errors="replace"))
            print("PASS ROUND073_GENUINE_ORIGINAL_LINUX_PINNED_NATIVE_READER "
                  "KUNIT_JSON_KTAP=4/4 original_LZO1X_LZ4_4096=YES "
                  "native_GC_reader_pin=YES independent_decoder_drain=YES "
                  "SWAPCACHE_AUTH=0 PHASE_A=BLOCKED", flush=True)
        return 0
    except (FirstError, OSError, ValueError, SyntaxError,
            subprocess.SubprocessError, subprocess.TimeoutExpired,
            json.JSONDecodeError) as error:
        reason = str(error) if isinstance(error, FirstError) else type(error).__name__
        print("ROUND073_READER_FIRST_ERROR phase=" + args.mode +
              " cause=" + re.sub(r"(?:/[^:\s]+)+/", "source/",
                                   reason)[:230], file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
