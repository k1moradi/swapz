#!/usr/bin/env python3
"""Execute the actual guarded DM receipt with reversed callbacks and stale aborts."""
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIOR = runpy.run_path(str(ROOT / "tests/tools/round053-dm-accepted-normal-bio-real-c-verify.py"))
FIXTURE = ROOT / "tests/runtime/native/fixtures/round054-dm-reissue-host.c"
MUTATIONS = (
    "observation->target_relative_sector != receipt->target_relative_sector",
    "observation->map_generation != receipt->map_generation",
    "observation->gc_epoch != receipt->gc_epoch",
    "observation->extent_start_block != receipt->extent_start_block",
    "observation->extent_blocks != receipt->extent_blocks",
    "receipt->synthetic_lease_token != observation->synthetic_lease_token",
)
FLAGS = (
    "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
    "-Wshadow", "-Werror", "-fsanitize=address,undefined",
    "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
)
PASS_MARKER = "ROUND054_DM_24_REISSUE_C_CASES_PASS AUTH0 PHASE_A=BLOCKED"


def main():
    source = PRIOR["TARGET"].read_text(encoding="utf-8")
    declaration, helper = PRIOR["verify_actual_production_source"](source)
    # Use precisely the existing host scalar definitions, not a second product model.
    prior_fixture = PRIOR["FIXTURE"].read_text(encoding="utf-8")
    marker = "/* ROUND053_INJECT_REAL_PRODUCT_RECEIPT_DECL */"
    if prior_fixture.count(marker) != 1:
        raise AssertionError("Round054 inherited host prefix not unique")
    prefix = prior_fixture.split(marker, 1)[0] + declaration
    suffix = FIXTURE.read_text(encoding="utf-8")
    abort_begin = helper.index("if (event == SWAPZ_ROUND053_ABORT) {")
    abort_end = helper.index("if (!observation ||", abort_begin)
    abort_body = helper[abort_begin:abort_end]
    for field in MUTATIONS:
        if abort_body.count(field) != 1 or helper.count(field) != 1:
            raise AssertionError("Round054 actual abort mutation not unique: " + field)
    variants = [("baseline", helper, None)]
    for fault, field in enumerate(MUTATIONS):
        variants.append(("mutant-" + str(fault), helper.replace(field, "false", 1), fault))
    with tempfile.TemporaryDirectory(prefix="round054-dm-") as directory:
        output = Path(directory)
        for compiler in ("gcc", "clang"):
            if shutil.which(compiler) is None:
                raise AssertionError("Round054 missing compiler " + compiler)
            for label, actual, fault in variants:
                source_file = output / (compiler + "-" + label + ".c")
                executable = source_file.with_suffix("")
                source_file.write_text(prefix + actual + suffix, encoding="utf-8")
                built = subprocess.run([compiler, *FLAGS, str(source_file), "-o",
                                        str(executable)], capture_output=True, text=True,
                                       timeout=90)
                if built.returncode:
                    raise AssertionError("ROUND054_DM_FIRST_COMPILE_ERROR " +
                                         compiler + " " + label + ": " + built.stderr[-4000:])
                executed = subprocess.run([str(executable)], capture_output=True,
                                          text=True, timeout=90, env={**os.environ,
                                          "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                          "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
                if fault is None:
                    valid = executed.returncode == 0 and executed.stdout.strip() == PASS_MARKER and not executed.stderr
                else:
                    expected = "ROUND054_DM_FIRST_ERROR blocks=1 fault=" + str(fault) + " stage=stale-abort"
                    valid = executed.returncode == 1 and executed.stderr.strip() == expected and not executed.stdout
                if not valid:
                    raise AssertionError("ROUND054_DM_FIRST_EXECUTION_ERROR " +
                                         compiler + " " + label + " exit=" +
                                         str(executed.returncode) + ": " +
                                         executed.stdout[-1000:] + executed.stderr[-4000:])
            print("ROUND054_DM_" + compiler.upper() +
                  "_24_REAL_HELPER_C_6_SEMANTIC_MUTANT_BINARIES_PASS AUTH0 PHASE_A=BLOCKED")


if __name__ == "__main__":
    main()
