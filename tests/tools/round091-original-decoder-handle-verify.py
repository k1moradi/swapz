#!/usr/bin/env python3
"""Round091 independent original decoder reusable value-handle HOST qualification.

Exact original Linux c339f4010dea8b0d754f84ace70cd1b089878ef8.
Only original LZ4 noDict compressor/decompressor corrections are staged in
private temporary compiler copies; no upstream or production adoption.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tests/tools/round085-original-decode-verify.py"
HANDLES_C = ROOT / "src/kernel/zswap-original-decoder-handles.c"
HANDLES_H = ROOT / "src/kernel/zswap-original-decoder-handles.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round091-original-decoder-handles.c"
SCALE_FIXTURE = ROOT / "tests/runtime/native/fixtures/round093-decoder-shared-provider.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
EXPECTED_PREFIX = "# Testing Standards\n"
MUTANTS = (
    ("epoch", "handle->lifecycle_epoch != owner->lifecycle_epoch ||",
     "0 ||", "wrong_epoch"),
    ("generation", "slot->last_generation != handle->generation ||",
     "", "retired_not_revived"),
    ("saturation", "if (candidate->last_generation == ~(swapz_u64)0)",
     "if (candidate->last_generation == ~(swapz_u64)0 && candidate->active)",
     "saturated_slot_skipped"),
)


def blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()


def require(yes: bool, description: str) -> None:
    if not yes:
        raise RuntimeError(description)


def semantic_failure(execution, expected, classify):
    """R093: preserve sanitizer precedence, credit only the exact exit-77 sentinel."""
    failure = classify(execution, None)
    if failure is not None and failure["kind"] == "sanitizer":
        return failure
    semantic = re.fullmatch(
        r"FIRST_ERROR round091-agent7 " + re.escape(expected) +
        r" line=[1-9][0-9]*\n", execution.stderr)
    if execution.returncode == 77 and not execution.stdout and semantic:
        return None
    return {"kind": "mutant_not_killed", "exit": execution.returncode,
            "location": "unavailable"}


def classifier_regression(classify):
    sentinel = "FIRST_ERROR round091-agent7 wrong_epoch line=61\n"
    cases = (
        (77, "", sentinel, None),
        (1, "", sentinel, "mutant_not_killed"),
        (0, "", sentinel, "mutant_not_killed"),
        (77, "extra\n", sentinel, "mutant_not_killed"),
        (77, "", sentinel + "extra\n", "mutant_not_killed"),
        (77, "", sentinel.replace("wrong_epoch", "wrong_generation"), "mutant_not_killed"),
        (77, "", sentinel.replace("61", "0"), "mutant_not_killed"),
        (77, "", sentinel + "ERROR: AddressSanitizer: heap-use-after-free\n", "sanitizer"),
        (77, "", sentinel + "runtime error: division by zero\n", "sanitizer"),
        (77, "", sentinel + "ERROR: LeakSanitizer: detected memory leaks\n", "sanitizer"),
    )
    for code, stdout, stderr, expected in cases:
        actual = semantic_failure(subprocess.CompletedProcess([], code, stdout, stderr),
                                  "wrong_epoch", classify)
        require((actual["kind"] if actual else None) == expected,
                "semantic diagnostic classifier regression")
    return len(cases)


def run_compiler(compiler: str, linux: Path, directory: Path, previous: dict,
                 helpers: dict, compressor: bytes, decompressor: bytes,
                 evidence: Path) -> dict:
    state = {"compiler": compiler, "status": "NOT_RUN", "stage": "init",
             "checks": 0, "churn": 0, "races": None, "first_error": None}
    checked = helpers["checked"]
    compile_object = helpers["compile_object"]
    run_command = helpers["run_command"]
    standard = helpers["compiler_standard"](compiler)
    state["standard"] = standard
    try:
        shim = previous["build_shim"](linux, directory, helpers)
        staged = directory / "staged"
        staged.mkdir()
        (staged / "lz4_compress.c").write_bytes(compressor)
        (staged / "lz4_decompress.c").write_bytes(decompressor)
        (staged / "lz4defs.h").write_bytes(
            (linux / "lib/lz4/lz4defs.h").read_bytes())
        require(blob(compressor) == previous["LZ4_POSTIMAGE"] and
                blob(decompressor) == previous["LZ4_DECODER_POSTIMAGE"],
                "isolated original LZ4 postimage differs from pinned correction")
        objects = []
        for relative in ("lib/lzo/lzo1x_compress_safe.c",
                         "lib/lzo/lzo1x_decompress_safe.c",
                         "lib/lz4/lz4_compress.c",
                         "lib/lz4/lz4_decompress.c"):
            name = Path(relative).name
            source = staged / name if relative.startswith("lib/lz4") else linux / relative
            obj = directory / ("original-" + Path(relative).stem + ".o")
            state["stage"] = "compile-pinned-" + name
            compile_object(compiler, "-std=gnu11", source, obj,
                           ["-I", str(shim), "-DCONFIG_64BIT=1"],
                           original=True)
            objects.append(obj)
        adapter = directory / "original-compressor.c"
        adapter.write_text(previous["COMPRESS_ADAPTER"])
        flags = ["-I", str(shim), "-I", str(ROOT / "src/kernel"),
                 "-DSWAPZ_ORIGINAL_STORAGE_TEST=1",
                 "-DSWAPZ_ORIGINAL_EXTENT_TEST=1",
                 "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
                 "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1"]
        for source in (ROOT / "src/kernel/codec.c",
                       ROOT / "src/kernel/zswap-import-decoder-owner.c",
                       ROOT / "src/kernel/zswap-original-decode.c",
                       HANDLES_C, FIXTURE, adapter):
            obj = directory / ("candidate-" + source.stem + ".o")
            state["stage"] = "compile-candidate-" + source.name
            compile_object(compiler, standard, source, obj, flags)
            objects.append(obj)
        binary = directory / "decoder-handle-host"
        state["stage"] = "link"
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie",
                 "-no-pie", *(str(path) for path in objects),
                 "-pthread", "-lcrypto", "-o", str(binary)],
                "reusable decoder handle source-linked host link")
        state["stage"] = "execute"
        observed = run_command([str(binary)], "reusable decoder handle test",
                               timeout=65)
        detected = re.fullmatch(
            r"PASS ROUND091_AGENT7 checks=(\d+) churn=(\d+) codecs=2 "
            r"races=(\d+)/(\d+) epoch=2 handle=(\d+) slot=(\d+) owner=(\d+) AUTH0\n",
            observed.stdout)
        first = previous["runtime_failure"](observed, None)
        if observed.returncode or observed.stderr or first or not detected:
            diagnostics = (observed.stderr or observed.stdout).splitlines()
            (evidence / (compiler + "-stderr.txt")).write_text(
                "\n".join(diagnostics[:32])[:3600], encoding="utf-8")
            state["first_error"] = first or {
                "kind": "fixture",
                "exit": observed.returncode,
                "location": next((item[:180] for item in diagnostics
                                  if "FIRST_ERROR" in item), "unavailable"),
            }
            raise RuntimeError("original decoder value-handle execution rejected")
        checks, churn, wins, declines, handle_bytes, slot_bytes, owner_bytes = map(int, detected.groups())
        require(checks > 50000 and churn == 24000 and
                wins + declines == 4, "incomplete value-handle coverage")
        require(handle_bytes >= 22 and owner_bytes >= 64 * slot_bytes,
                "invalid measured layout")
        state.update(checks=checks, churn=churn,
                     races={"successful": wins, "declined": declines},
                     layout={"handle_bytes": handle_bytes, "slot_bytes": slot_bytes,
                             "owner_bytes": owner_bytes, "live_record_slots": 64},
                     mutants_compiled=0, mutants_executed=0, mutants_killed=[])
        state["stage"] = "scale-compile"
        scale_object = directory / "scale.o"
        compile_object(compiler, standard, SCALE_FIXTURE, scale_object, flags)
        scale_binary = directory / "scale"
        scale_fixed = [obj for obj in objects if obj.name != "candidate-" + FIXTURE.stem + ".o"]
        require(len(scale_fixed) + 1 == len(objects), "scale fixture inventory")
        state["stage"] = "scale-link"
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                 str(scale_object), *(str(obj) for obj in scale_fixed),
                 "-pthread", "-lcrypto", "-o", str(scale_binary)], "shared provider model link")
        state["stage"] = "scale-execute"
        scale = run_command([str(scale_binary)], "shared provider model", timeout=65)
        scale_match = re.fullmatch(
            r"PASS ROUND093_AGENT7 scale checks=(\d+) records=(\d+) sidecar=(\d+) providers=(\d+) codecs=2 AUTH0\n",
            scale.stdout)
        scale_failure = previous["runtime_failure"](scale, None)
        if scale_failure or not scale_match:
            (evidence / (Path(compiler).name + "-scale-stderr.txt")).write_text(
                scale.stderr[:3600], encoding="utf-8")
            state["first_error"] = scale_failure or {"kind": "scale_output", "location": "unavailable"}
            raise RuntimeError("shared provider model execution rejected")
        scale_checks, scale_records, sidecar_bytes, provider_bytes = map(int, scale_match.groups())
        require(scale_checks > 2048 and scale_records == 1024 and sidecar_bytes <= 16,
                "incomplete shared provider scale coverage")
        state["scale"] = {"status": "PASS_HOST_MODEL", "checks": scale_checks,
                          "simultaneous_records": scale_records, "sidecar_bytes": sidecar_bytes,
                          "shared_provider_bytes": provider_bytes, "native": "NOT_RUN"}
        original = HANDLES_C.read_text()
        fixed = [obj for obj in objects if obj.name !=
                 "candidate-" + HANDLES_C.stem + ".o"]
        require(len(fixed) + 1 == len(objects), "handle object inventory mismatch")
        for name, old, new, expected in MUTANTS:
            state["stage"] = "mutant-compile-" + name
            require(original.count(old) == 1 and old != new, "mutant anchor: " + name)
            mutant = directory / ("mutant-" + name + ".c")
            mutant.write_text(original.replace(old, new, 1))
            mutant_object = mutant.with_suffix(".o")
            compile_object(compiler, standard, mutant, mutant_object, flags)
            state["mutants_compiled"] += 1
            state["stage"] = "mutant-link-" + name
            executable = mutant.with_suffix("")
            checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                     str(mutant_object), *(str(obj) for obj in fixed),
                     "-pthread", "-lcrypto", "-o", str(executable)], name + " link")
            state["stage"] = "mutant-execute-" + name
            execution = run_command([str(executable)], name, timeout=65)
            state["mutants_executed"] += 1
            failure = semantic_failure(execution, expected, previous["runtime_failure"])
            if failure is not None:
                (evidence / (Path(compiler).name + "-" + name + "-stderr.txt")).write_text(
                    execution.stderr[:3600], encoding="utf-8")
                state["first_error"] = {**failure, "name": name}
                raise RuntimeError("semantic mutant not killed: " + name)
            state["mutants_killed"].append(name)
        state.update(status="PASS", stage="complete")
        print(f"PASS ROUND091_AGENT7 {compiler} {standard} "
              f"checks={checks} churn={churn} races={wins}/{declines} "
              "original_LZ4_LZO1X", file=sys.stderr)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        state["status"] = "FAIL"
        if state["first_error"] is None:
            state["first_error"] = {
                "kind": type(error).__name__,
                "stage": state["stage"], "location": "unavailable",
                "reason": str(error).split("\n", 1)[0][:600],
            }
        print("FIRST_ERROR ROUND091_AGENT7 " + json.dumps(
            state["first_error"], sort_keys=True), file=sys.stderr)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    linux = args.linux_root.resolve()
    report = {
        "round": "091", "agent": 7, "status": "FAIL",
        "linux_pin": PIN, "source_authenticated": 0,
        "phase_a": "BLOCKED", "direct_compressed_handoff": False,
        "forced_raw_bypass": False, "import_active": False,
        "compilers": {}, "first_error": None,
    }
    exit_code = 1
    try:
        previous = runpy.run_path(str(ORIGINAL))
        require(previous["PIN"] == PIN and
                previous["LZ4_POSTIMAGE"] ==
                "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                previous["LZ4_DECODER_POSTIMAGE"] ==
                "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                "unapproved original LZ4 staging profile")
        helpers = previous["verify_inputs"](linux)
        checked = helpers["checked"]
        require(checked(["git", "-C", str(linux), "rev-parse", "HEAD"],
                        "pinned original source") == PIN,
                "original Linux source drift")
        require(not checked(["git", "-C", str(linux), "status",
                             "--porcelain", "--untracked-files=all"],
                            "pristine original"), "dirty original checkout")
        previous["stage_plan"](linux, helpers, report)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            parent = subprocess.check_output(
                ["git", "-C", str(ROOT), "show", "HEAD^:docs/testing_standards.md"])
            current = (ROOT / "docs/testing_standards.md").read_bytes()
            require(current.startswith(parent), "complete actual parent standards prefix changed")
            report["standards_prefix"] = {"parent_bytes": len(parent),
                "current_bytes": len(current), "parent_blob": blob(parent),
                "current_blob": blob(current)}
        report["qualification_round"] = "093"
        report["classifier_cases"] = classifier_regression(previous["runtime_failure"])
        for source in (HANDLES_C, HANDLES_H, FIXTURE, SCALE_FIXTURE):
            require(source.is_file() and source.stat().st_size > 500,
                    "missing handle bridge source: " + source.name)
        require("#define SWAPZ_ORIGINAL_DECODER_HANDLES_ACTIVE 0U" in
                HANDLES_H.read_text(), "decoder handle activation guard changed")
        report["source_blobs"] = {
            str(path.relative_to(ROOT)): blob(path.read_bytes())
            for path in (HANDLES_C, HANDLES_H, FIXTURE, SCALE_FIXTURE, Path(__file__))
        }
        if args.preflight_only:
            report["status"] = "PASS_PREFLIGHT_ONLY"
            exit_code = 0
            print("PASS ROUND091_AGENT7 pinned source and noDict stage negatives",
                  file=sys.stderr)
        else:
            with tempfile.TemporaryDirectory(
                    prefix="round091-original-value-handle-") as temp:
                for name in ("gcc", "clang"):
                    compiler = shutil.which(name)
                    require(compiler is not None, "missing compiler " + name)
                    workspace = Path(temp) / name
                    workspace.mkdir()
                    compressor = previous["staged_bytes"](
                        (linux / previous["LZ4_SOURCE"]).read_bytes(), PIN, "")
                    decompressor = previous["staged_decoder_bytes"](
                        (linux / previous["LZ4_DECODER_SOURCE"]).read_bytes(),
                        PIN, "")
                    result = run_compiler(compiler, linux, workspace,
                                          previous, helpers, compressor,
                                          decompressor, evidence)
                    report["compilers"][name] = result
                    if result["status"] != "PASS":
                        report["first_error"] = {"compiler": name,
                                                  **result["first_error"]}
                        break
            if report["first_error"] is None:
                require(not checked(["git", "-C", str(linux), "status",
                                     "--porcelain", "--untracked-files=all"],
                                    "final original clean"),
                        "original Linux was changed by host qualification")
                report["status"] = "PASS_STAGED_HOST_ONLY"
                exit_code = 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        report["first_error"] = {
            "kind": type(error).__name__, "location": "unavailable",
            "reason": str(error).split("\n", 1)[0][-200:],
        }
        print("FIRST_ERROR ROUND091_AGENT7 " + json.dumps(
            report["first_error"], sort_keys=True), file=sys.stderr)
    finally:
        try:
            (evidence / "results.json").write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n",
                encoding="utf-8")
        except OSError:
            print("FIRST_ERROR ROUND091_AGENT7 result retention failed",
                  file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
