#!/usr/bin/env python3
"""Distinct R093 owner-gate tests; actual frozen broker, modeled owner/module."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea"
BROKER = "src/kernel/zswap-original-ticket.c"
HEADER = "src/kernel/zswap-original-ticket.h"
PATCH = "tests/tools/round092-original-module-boundary.patch"
SHIM = "tests/runtime/native/fixtures/round092-module-shim.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round093-external-broker-owner.c"
PINS = {
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    PATCH: "62db468c14f23b59e7adaae65a11dcb9969f02b3",
    SHIM: "79623955e77b0b35d17bd14f322412d8ee202c84",
}
POST = {BROKER: "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
        HEADER: "6afac83a0655e532ce1ef9b8f290a367e8aabfce"}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(command, cwd=ROOT, timeout=60):
    return subprocess.run(command, cwd=cwd, capture_output=True, timeout=timeout, check=False)


def checked(command, cwd=ROOT):
    result = run(command, cwd)
    require(result.returncode == 0, "command failed: " + Path(command[0]).name)
    return result.stdout


def pin(path, expected):
    require(checked(["git", "hash-object", str(path)]).decode().strip() == expected,
            "blob pin " + path.name)


def once(source, old, new):
    require(source.count(old) == 1, "nonunique mutation anchor")
    return source.replace(old, new, 1)


def stage(directory):
    for name, expected in PINS.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(checked(["git", "show", FREEZE + ":" + name]))
        pin(path, expected)
    command = ["git", "apply", "--unidiff-zero",
               "--include=" + BROKER, "--include=" + HEADER, str(directory / PATCH)]
    checked(command[:2] + ["--check"] + command[2:], directory)
    checked(command, directory)
    for name, expected in POST.items():
        pin(directory / name, expected)


def exercise(directory, evidence, report):
    original = (directory / BROKER).read_text()
    fixture = FIXTURE.read_text()
    variants = [
        ("baseline", fixture, original, None, None),
        ("ignore_external_entrants",
         once(fixture, "gate->accepting || gate->entrants != 0U", "gate->accepting"),
         original, "pre_reference_entrant_fence", "modeled_owner"),
        ("ignore_cap_destroy", fixture,
         once(original, "broker->used_bytes ||\n\t    broker->capability_refs)",
              "broker->used_bytes)"), "cap_only_destroy_busy", "actual_broker"),
        ("ignore_close_claim", fixture,
         once(original, "return !broker->closing && slot->key.table_epoch == broker->epoch &&",
              "return slot->key.table_epoch == broker->epoch &&"),
         "closed_claim_refusal", "actual_broker"),
        ("ignore_revoke_claim", fixture,
         once(original, "slot->key.table_epoch == broker->epoch &&",
              "true &&"), "claimed_then_revoked_refusal", "actual_broker"),
    ]
    # The first revoke mutant witness is the claimed-then-revoked exact
    # stale result. Baseline also checks revoke before an unclaimed ticket.
    kernel = directory / "src/kernel"
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for compiler in ("gcc", "clang"):
        standard = next((s for s in ("c23", "c2x")
                         if run([compiler, "-std=" + s, "-fsyntax-only", str(probe)]).returncode == 0), None)
        require(standard, "no C23 compiler " + compiler)
        entry = {"version": checked([compiler, "--version"]).decode().splitlines()[0],
                 "standard": standard, "status": "IN_PROGRESS", "mutants": {}}
        report[compiler] = entry
        for name, fixture_text, broker_text, witness, kind in variants:
            source = directory / "fixture.c"
            broker = directory / "broker.c"
            binary = directory / (compiler + "-" + name)
            source.write_text(fixture_text)
            broker.write_text(broker_text)
            command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                       "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                       "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread", "-no-pie",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                       "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-include", str(directory / SHIM),
                       "-I", str(kernel), "-I", str((directory / SHIM).parent),
                       str(source), str(broker), str(kernel / "codec.c"), "-o", str(binary)]
            compilation = run(command)
            (evidence / (compiler + "-" + name + "-compile.log")).write_bytes(
                compilation.stdout + compilation.stderr)
            require(compilation.returncode == 0, compiler + "/" + name + " compile failure")
            execution = run([str(binary)], timeout=30)
            (evidence / (compiler + "-" + name + "-run.log")).write_bytes(
                execution.stdout + execution.stderr)
            if witness is None:
                match = re.fullmatch(rb"PASS_HOST_ONLY R093 A11 checks=(\d+) scenarios=5\n",
                                     execution.stdout)
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline failure")
                entry.update(checks=int(match[1]), scenarios=5)
                print(compiler + " " + execution.stdout.decode().strip(), flush=True)
            else:
                marker = rb"R093_A11_FIRST_ERROR " + witness.encode() + rb" line=\d+\n"
                require(execution.returncode == 77 and not execution.stdout and
                        re.fullmatch(marker, execution.stderr), compiler + "/" + name + " not semantic kill")
                entry["mutants"][name] = {"status": "KILLED", "kind": kind, "witness": witness}
                print(compiler + " semantic kill " + name, flush=True)
        entry["status"] = "PASS"


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
        with tempfile.TemporaryDirectory(prefix="r093-a11-owner-") as temporary:
            directory = Path(temporary)
            stage(directory)
            report["stage"] = "PASS"
            exercise(directory, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:200]
        print("R093_A11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
