#!/usr/bin/env python3
"""R094 actual staged built-in broker owner; host primitives only, no loader."""
import argparse
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIOR = runpy.run_path(str(ROOT / "tests/tools/round093-external-broker-owner-verify.py"))
FREEZE = "efd77858cd20650213559ceb9cb4d0362db32ea5"
BROKER = PRIOR["BROKER"]
HEADER = PRIOR["HEADER"]
OWNER = "src/kernel/zswap-original-broker-owner.inc"
PATCH = "tests/tools/round094-original-broker-owner.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round094-real-broker-owner.c"
SHIM = ROOT / "tests/runtime/native/fixtures/round094-owner-shim.h"
PINS = {
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    PATCH: "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
    str(FIXTURE.relative_to(ROOT)): "0cef169c8b39aaf0c140141f1fe8969e55b26259",
    str(SHIM.relative_to(ROOT)): "bc49e924eeee826496264503d0af1b4f1fb8e611",
}
POST = {BROKER: "ba5e891ef7f80bf0b3021ee6c676529cb72f1972",
        HEADER: "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"}
require, run, checked, pin, once = (PRIOR[name] for name in ("require", "run", "checked", "pin", "once"))


def stage(directory):
    # Reuse staging only, never the accepted R093 execution corpus.
    PRIOR["stage"](directory)
    for name, expected in PINS.items():
        pin(ROOT / name, expected)
    (directory / OWNER).write_bytes((ROOT / OWNER).read_bytes())
    patch = ROOT / PATCH
    command = ["git", "apply", "--unidiff-zero", str(patch)]
    checked(command[:2] + ["--check"] + command[2:], directory)
    checked(command, directory)
    for name, expected in POST.items():
        pin(directory / name, expected)
    checked(command[:2] + ["--reverse", "--check"] + command[2:], directory)
    source = (directory / OWNER).read_text()
    require(set(re.findall(r"EXPORT_SYMBOL_GPL\((\w+)\);", source)) == {
        "swapz_mm_broker_owner_open", "swapz_mm_broker_owner_begin_close",
        "swapz_mm_broker_owner_finish_close"}, "owner export inventory")
    require("EXPORT_SYMBOL(" not in source and "try_module_get(" not in source,
            "unrestricted export or owner self pin")


def exercise(directory, evidence, report):
    kernel = directory / "src/kernel"
    source = (directory / OWNER).read_text()
    variants = [
        ("baseline", source, None),
        ("ignore_paused_entrant", once(source, "!owner_accepting && !owner_entrants",
                                       "!owner_accepting"), "paused_entrant_fence"),
        ("ignore_close_identity", source.replace(
            "if (!owner_broker.initialized || session != owner_session || epoch != owner_epoch)",
            "if (!owner_broker.initialized || !session || !epoch)", 1),
         "wrong_begin_identity"),
        ("ignore_wrap", once(source, "if (owner_last_identity == ~(swapz_u64)0)",
                             "if (false)"), "identity_wrap"),
        ("ignore_unwind", once(source, "owner_free(payload);", "(void)payload;"),
         "allocation_unwind"),
        ("ignore_second_open", once(source, "if (owner_broker.initialized || owner_quarantined) {",
                                   "if (owner_quarantined) {"), "second_open_refused"),
        ("ignore_revoked_epoch", once(source, "if (owner_broker.epoch > owner_last_identity)",
                                    "if (false)"), "revoked_epoch_nonreuse"),
    ]
    # Baseline has leak detection; mutants must fail by exact semantic witness,
    # not incidental allocator/ASan diagnostics from deliberate early exit.
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    (directory / "r094-broker.c").write_bytes((directory / BROKER).read_bytes())
    for compiler in ("gcc", "clang"):
        standard = next((s for s in ("c23", "c2x")
                         if run([compiler, "-std=" + s, "-fsyntax-only", str(probe)]).returncode == 0), None)
        require(standard, "missing C23 compiler " + compiler)
        entry = {"version": checked([compiler, "--version"]).decode().splitlines()[0],
                 "standard": standard, "status": "IN_PROGRESS", "mutants": {}}
        report[compiler] = entry
        for name, actual_owner, witness in variants:
            (directory / OWNER).write_text(actual_owner)
            binary = directory / (compiler + "-" + name)
            command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                       "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                       "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread", "-no-pie",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                       "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
                       "-include", str(SHIM), "-I", str(kernel), "-I", str(directory),
                       str(FIXTURE), str(kernel / "codec.c"), "-o", str(binary)]
            compilation = run(command)
            (evidence / (compiler + "-" + name + "-compile.log")).write_bytes(
                compilation.stdout + compilation.stderr)
            diagnostic = next((line for line in compilation.stderr.decode(errors="replace").splitlines()
                               if "error:" in line), "unclassified compile diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
            require(compilation.returncode == 0, compiler + "/" + name + " compile " + diagnostic[:180])
            execution = subprocess.run([str(binary)], capture_output=True, timeout=30, check=False,
                                       env={**os.environ, "ASAN_OPTIONS": "detect_leaks=" + ("1" if witness is None else "0")})
            (evidence / (compiler + "-" + name + "-run.log")).write_bytes(
                execution.stdout + execution.stderr)
            if witness is None:
                match = re.fullmatch(rb"PASS_HOST_ONLY R094 A11 checks=(\d+) scenarios=5\n", execution.stdout)
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline failure " + execution.stderr.decode(errors="replace")[:120])
                entry.update(checks=int(match[1]), scenarios=5)
                print(compiler + " " + execution.stdout.decode().strip(), flush=True)
            else:
                marker = rb"R094_A11_FIRST_ERROR " + witness.encode() + rb" line=\d+\n"
                require(execution.returncode == 77 and not execution.stdout and re.fullmatch(marker, execution.stderr),
                        compiler + "/" + name + " not semantic kill")
                entry["mutants"][name] = {"status": "KILLED", "witness": witness}
                print(compiler + " semantic kill " + name, flush=True)
        entry["status"] = "PASS"
    (directory / OWNER).write_text(source)
    pin(directory / OWNER, PINS[OWNER])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "tested_commit": checked(["git", "rev-parse", "HEAD"]).decode().strip(),
              "engineering_freeze": FREEZE, "source_authentication": 0, "phase_a": "BLOCKED",
              "direct_handoff": "DISABLED", "forced_raw": "DISABLED", "import": 0,
              "native_owner": "NOT_RUN", "kernel_rcu": "NOT_RUN", "module_load": "NOT_RUN",
              "physical": "NOT_RUN", "host": {}, "first_error": None}
    try:
        with tempfile.TemporaryDirectory(prefix="r094-a11-owner-") as temporary:
            directory = Path(temporary)
            stage(directory)
            report["stage"] = "PASS"
            exercise(directory, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R094_A11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
