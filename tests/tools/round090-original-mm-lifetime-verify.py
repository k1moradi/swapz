#!/usr/bin/env python3
"""Exact R089 stage + R090 producer lifetime overlay; focused host-only tests."""
import argparse
import json
from pathlib import Path
import re
import runpy
import sys
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BASE = runpy.run_path(str(ROOT / "tests/tools/round089-original-mm-carrier-verify.py"))
require, checked, run = (BASE[name] for name in ("require", "checked", "run"))
verify_pins, blob, function, ordered = (BASE[name] for name in
                                       ("verify_pins", "blob", "function", "ordered"))
OVERLAY = ROOT / "tests/tools/round090-original-mm-lifetime.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round090-original-mm-lifetime.c"
POST = {
    "mm/zswap.c": "cbf160877e8d8b584d6010c009a3e500f8b99f38",
    "include/linux/swap_ops.h": "a39a1921daf6f272e9812eb63b1aa64fec96c57f",
    "include/linux/blk_types.h": "50c94617b08e581021ba25fa6e182a5b88ecfa43",
    "include/linux/bio.h": "4079365b37690164f85ba962a0bd0918c85899cb",
    "block/bio.c": "38f24ee2e414107be390d3a01c6b907e06a9dca7",
    "mm/page_io.c": "c3bd481117dbd29edd821df452f74990d6d5f00a",
    "include/linux/swapz_mm_carrier.h": "f170d2c2ac63679adb0885f746585ed77c2746a5",
}
INPUTS = {
    "tests/tools/round089-original-mm-carrier-verify.py": "dce6b2417ea33b598eaf00accf7888730b2e4a54",
    "tests/tools/round090-original-mm-lifetime.patch": "337f7ff29e72d955251de0c54a9349f20c2586ec",
    "tests/runtime/native/fixtures/round090-original-mm-lifetime.c": "a6d761368ebbe6610ddf13bd5d176e6d64fa9ef5",
}


def host(staged, scratch, evidence, report):
    zswap = (staged / "mm/zswap.c").read_text()
    candidate = function(zswap, "swapz_mm_candidate_get")
    release = function(zswap, "swapz_mm_release_workfn")
    ordered(candidate, ["rcu_read_lock", "rcu_dereference", "swapz_mm_bio_matches",
                        "swapz_ticket_retain", "rcu_read_unlock"], "carrier reader")
    ordered(release, ["synchronize_rcu", "swapz_ticket_put",
                      "swapz_ticket_broker_put", "atomic_set_release"], "carrier release")
    ordered(function(zswap, "swapz_mm_route_try"),
            ["rcu_read_lock", "rcu_dereference", "provider->lookup",
             "swapz_ticket_broker_try_get", "rcu_read_unlock"], "provider capability")
    ordered(function(zswap, "swapz_mm_unregister_provider"),
            ["rcu_assign_pointer(swapz_mm_provider, NULL)", "synchronize_rcu", "mutex_unlock"],
            "provider grace")
    ordered(function(zswap, "swapz_mm_capture"),
            ["rcu_access_pointer", "swapz_mm_eligible", "atomic_cmpxchg_acquire",
             "swapz_crc32c_bytes", "sha256(original"], "eligible only hash")
    bio = (staged / "block/bio.c").read_text() + (staged / "include/linux/bio.h").read_text()
    require(bio.count("rcu_assign_pointer(bio->bi_swapz_original, NULL);") == 10 and
            bio.count("rcu_assign_pointer(parent->bi_swapz_original, NULL);") == 1 and
            "bi_swapz_original = " not in bio, "all borrow invalidation sites")
    page = (staged / "mm/page_io.c").read_text()
    ordered(function(page, "swap_bdev_submit_write"),
            ["rcu_assign_pointer(bio->bi_swapz_original, sio->original)", "submit_bio_wait"],
            "publish before submission")
    ordered(function(page, "end_swap_bio_write"), ["bio_uninit(bio)", "swap_write_end"],
            "clear before terminal owner drop")
    header = (staged / "include/linux/swapz_mm_carrier.h").read_text()
    for include in ("#include <linux/blkdev.h>\n", "#include <linux/mm_types.h>\n"):
        require(header.count(include) == 1, "shim header anchor")
        header = header.replace(include, "")
    (scratch / "r090-staged-carrier.h").write_text(header)
    extracted = candidate + release
    variants = {
        "baseline": extracted,
        "no_reader": extracted.replace("rcu_read_lock();", "if (origin == NULL) rcu_read_lock();"),
        "no_grace": extracted.replace("if (swapz_mm_carrier.bdev)", "if (!swapz_mm_carrier.bdev)"),
    }
    require(all(text != extracted for name, text in variants.items() if name != "baseline"),
            "mutation anchors")
    for compiler in ("gcc", "clang"):
        probe = scratch / "probe.c"
        probe.write_text("int main(void) { return 0; }\n")
        standard = next((std for std in ("c23", "c2x")
                         if run([compiler, "-std=" + std, "-fsyntax-only", str(probe)]).returncode == 0),
                        None)
        require(standard, "no C23 spelling " + compiler)
        result = {"standard": standard, "compiler_version": checked([compiler, "--version"]).splitlines()[0],
                  "status": "IN_PROGRESS", "mutants": {}}
        report[compiler] = result
        for name, body in variants.items():
            (scratch / "r090-staged-functions.h").write_text(body)
            binary = scratch / (compiler + "-" + name)
            command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                       "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                       "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-no-pie", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                       "-I", str(ROOT / "src/kernel"), "-I", str(scratch), str(FIXTURE),
                       str(ROOT / "src/kernel/zswap-original-ticket.c"),
                       str(ROOT / "src/kernel/codec.c"), "-o", str(binary)]
            build = run(command)
            (evidence / (compiler + "-" + name + "-compile.log")).write_text(build.stdout + build.stderr)
            diagnostic = next((line for line in build.stderr.splitlines() if "error:" in line),
                              "unclassified compile diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
            require(build.returncode == 0, compiler + "/" + name + " compile " + diagnostic[:180])
            execution = run([str(binary)], timeout=15)
            (evidence / (compiler + "-" + name + "-run.log")).write_text(execution.stdout + execution.stderr)
            if name == "baseline":
                match = re.fullmatch(r"PASS_HOST_ONLY R090 checks=(\d+) lifecycle_races=1 immediate=1024 "
                                     r"lag32=992 lag64=0 lag256=0 source=(\d+) carrier=(\d+) "
                                     r"broker=(\d+) trace_cpu_seconds=([0-9.]+)\n", execution.stdout)
                diagnostic = next((line for line in execution.stderr.splitlines()
                                   if re.search(r"R090_FIRST_ERROR|runtime error:|AddressSanitizer", line)),
                                  "unclassified execution diagnostic")
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline " + diagnostic[:180])
                result.update(checks=int(match[1]), lifecycle_races=1, trace_hits=[1024, 992, 0, 0],
                              sizes=dict(zip(("source", "carrier", "broker"), map(int, match.groups()[1:4]))),
                              trace_cpu_seconds=float(match[5]))
                print(compiler + " " + execution.stdout.strip(), flush=True)
            else:
                witness = "reader not protected" if name == "no_reader" else "atomic_load(&grace_calls) == 1U"
                require(execution.returncode == 77 and "R090_FIRST_ERROR" in execution.stderr and
                        witness in execution.stderr, compiler + "/" + name + " not semantic kill")
                result["mutants"][name] = "KILLED"
                print(compiler + " semantic kill " + name, flush=True)
        result["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "kernel_compile": "NOT_RUN",
              "native": "NOT_RUN", "physical": "NOT_RUN", "source_authentication": 0}
    try:
        require(checked(["git", "rev-parse", "HEAD"], args.linux).strip() == BASE["PIN"], "Linux pin")
        require(not checked(["git", "status", "--porcelain", "--untracked-files=all"], args.linux),
                "dirty Linux checkout")
        verify_pins(ROOT, BASE["PRODUCT"])
        verify_pins(ROOT, INPUTS)
        verify_pins(args.linux, BASE["PRISTINE"])
        report["pristine_pins"] = len(BASE["PRISTINE"])
        with tempfile.TemporaryDirectory(prefix="r090-") as temp:
            scratch = Path(temp)
            staged = scratch / "stage"
            for path in BASE["PRISTINE"]:
                destination = staged / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((args.linux / path).read_bytes())
            checked(["git", "apply", "--unidiff-zero", "--check", str(BASE["PATCH"])], staged)
            checked(["git", "apply", "--unidiff-zero", str(BASE["PATCH"])], staged)
            verify_pins(staged, BASE["POST"])
            report["baseline_postimage_pins"] = len(BASE["POST"])
            checked(["git", "apply", "--unidiff-zero", "--check", str(OVERLAY)], staged)
            checked(["git", "apply", "--unidiff-zero", str(OVERLAY)], staged)
            verify_pins(staged, POST)
            require(run(["git", "apply", "--unidiff-zero", "--check", str(OVERLAY)], staged).returncode != 0,
                    "duplicate overlay accepted")
            checked(["git", "apply", "--unidiff-zero", "--reverse", "--check", str(OVERLAY)], staged)
            for path in BASE["PRISTINE"].keys() - POST.keys():
                require(blob((staged / path).read_bytes()) == BASE["PRISTINE"][path],
                        "unexpected changed input " + path)
            report["overlay_postimage_pins"] = len(POST)
            report["stage"] = "PASS"
            report["host"] = {}
            host(staged, scratch, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        print("PASS_HOST_ONLY R090 staged producer lifetime + sparse trace; kernel NOT_RUN AUTH0")
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R090_AGENT11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
