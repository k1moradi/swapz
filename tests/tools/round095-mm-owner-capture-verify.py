#!/usr/bin/env python3
"""Actual MM capture and built-in broker owner, source-linked host boundary only."""
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
FREEZE = "ff972661a75ca7f8c3c0458c3feb8b603c185eb8"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
OWNER = runpy.run_path(str(ROOT / "tests/tools/round094-real-broker-owner-verify.py"))
MM = runpy.run_path(str(ROOT / "tests/tools/round093-actual-raw-r092-compile-verify.py"))
require, pin, checked, run, once = (OWNER[name] for name in ("require", "pin", "checked", "run", "once"))
PATCH = ROOT / "tests/tools/round095-original-mm-observation-fence.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round095-mm-owner-capture.c"
SHIM = ROOT / "tests/runtime/native/fixtures/round094-owner-shim.h"
PINS = {str(PATCH.relative_to(ROOT)): "a93a962717c056aae808e57ab3401644f7897806",
        str(FIXTURE.relative_to(ROOT)): "538ad917b7c0fd8872906c11e28a9ea2ebd03aac",
        str(SHIM.relative_to(ROOT)): "bc49e924eeee826496264503d0af1b4f1fb8e611",
        "tests/tools/round094-real-broker-owner-verify.py": "d0207a8bc0021f12c8d11927b4dfbae4444e5c26",
        "tests/tools/round093-external-broker-owner-verify.py": "d26d5b6c645c90742d50b70e4c1e1f04f265053e",
        "tests/tools/round093-actual-raw-r092-compile-verify.py": "2aa197fe2d22446f27e6af5777eb3daf5cbed620"}
PATHS = ("mm/zswap.c", "mm/page_io.c", "include/linux/swapz_mm_carrier.h")
POST = "12865d0351ef8b149b9f7dc8de5a9d1d8089785e"


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:bool|u8|u64|int|void) (?:"
                               + name + r"|\(" + name + r"\))\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "actual function anchor " + name)
    depth = 1
    for index in range(matches[0].end(), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if not depth:
                return source[matches[0].start():index + 1] + "\n"
    raise RuntimeError("unclosed function " + name)


def ordered(source, tokens, label):
    cursor = 0
    for token in tokens:
        index = source.find(token, cursor)
        require(index >= 0, label + " missing/order " + token)
        cursor = index + len(token)


def apply(directory, patch, paths):
    command = ["git", "apply", "--unidiff-zero", *["--include=" + p for p in paths], str(patch)]
    checked(command[:2] + ["--check"] + command[2:], directory)
    checked(command, directory)
    checked(command[:2] + ["--reverse", "--check"] + command[2:], directory)


def stage(directory, linux):
    require(checked(["git", "rev-parse", "HEAD"], linux).decode().strip() == LINUX,
            "original Linux pin")
    require(not checked(["git", "status", "--porcelain", "--untracked-files=all"], linux), "dirty Linux")
    for path, expected in PINS.items():
        pin(ROOT / path, expected)
    OWNER["stage"](directory)  # staging only; no accepted R094 corpus execution
    for path in PATHS:
        expected = MM["IMAGES"][path][0]
        if expected:
            pin(linux / path, expected)
            destination = directory / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((linux / path).read_bytes())
    for name, expected in MM["PATCHES"].items():
        if "selected-clone" in name:
            continue
        pin(ROOT / name, expected)
        images = MM["PATCH_STAGES"][name]
        selected = [p for p in PATHS if p in images]
        apply(directory, ROOT / name, selected)
        for path in selected:
            pin(directory / path, images[path])
    name = MM["R092_OVERLAY"]
    pin(ROOT / name, MM["R092_OVERLAY_PIN"])
    apply(directory, ROOT / name, [PATHS[0], PATHS[2]])
    for path in PATHS:
        pin(directory / path, MM["final_raw_pin"](path))
    apply(directory, PATCH, [PATHS[0]])
    pin(directory / PATHS[0], POST)
    source = (directory / PATHS[0]).read_text()
    header = (directory / PATHS[2]).read_text()
    page = (directory / PATHS[1]).read_text()
    dm_path = "src/kernel/dm-target.c"
    dm = checked(["git", "show", FREEZE + ":" + dm_path]).decode()
    (directory / dm_path).write_text(dm)
    pin(directory / dm_path, "2400ad0ccaf72c2586c4fd1488edb9a00246e213")
    ordered(function(source, "zswap_writeback_entry"),
            ["entry != xa_load(tree, offset)", "zswap_decompress(entry, folio)",
             "swapz_mm_preerase(entry, folio", "xa_erase(tree, offset)"], "native preerase")
    ordered(function(source, "swapz_mm_preerase"),
            ["swapz_mm_capture_observation_enabled()", "__swap_entry_to_info", "swapz_mm_route_try",
             "zs_obj_read_sg_begin", "sg_copy_to_buffer", "zs_obj_read_sg_end",
             "swapz_mm_eviction_key", "swapz_ticket_reserve", "swapz_ticket_seal", "ctx->original = carrier"],
            "preerase source and lifetime")
    require("swapz_mm_sources[" not in source and "SWAPZ_MM_SOURCE_SLOTS" not in header,
            "no per-store sparse cache")
    require("swapz_mm_move(&sio->original, &ctx->original)" in page and
            "rcu_assign_pointer(bio->bi_swapz_original, sio->original)" in page and
            "swapz_mm_drop(&sio->original)" in page, "native page_io ownership mapping")
    ordered(dm, ["list_del_rcu(&ctx->original_registry)", "synchronize_rcu()",
                 "ctx->original_retired_cap = ctx->original_cap"], "target registry grace")
    require("Ordered claim remains hard-disabled in this trial." in dm and
            "SWAPZ_ROUND094_BROKER_SLOTS" in dm, "frozen speculative target")
    for include in ("#include <linux/blkdev.h>\n", "#include <linux/mm_types.h>\n", "#include <linux/module.h>\n"):
        header = once(header, include, "")
    (directory / "r095-carrier.h").write_text(header)
    names = ("swapz_mm_next", "swapz_mm_profile", "swapz_mm_pool_codec", "swapz_mm_eviction_key",
             "swapz_mm_register_provider", "swapz_mm_unregister_provider", "swapz_mm_eligible",
             "swapz_mm_route_try", "swapz_mm_capture_observation_enabled", "swapz_mm_capture",
             "swapz_mm_release_workfn", "swapz_mm_drop", "swapz_mm_candidate_get", "swapz_mm_preerase")
    return {name: function(source, name) for name in names}


def exercise(directory, evidence, parts, report):
    baseline = "\n".join(parts.values())
    def mutate(name, old, new):
        return "\n".join(once(value, old, new) if key == name else value for key, value in parts.items())
    gate = "\tif (!swapz_mm_capture_observation_enabled())\n\t\treturn;"
    variants = [
        ("disabled", baseline, False, None),
        ("observation", baseline, True, None),
        ("ignore_store_fence", mutate("swapz_mm_capture", gate, "\tif (false)\n\t\treturn;"), False, "disabled_store_zero"),
        ("ignore_eviction_fence", mutate("swapz_mm_preerase", gate, "\tif (false)\n\t\treturn;"), False, "disabled_eviction_zero"),
        ("ignore_candidate_fence", mutate("swapz_mm_candidate_get", "if (!swapz_mm_capture_observation_enabled())",
                                           "if (false)"), False, "disabled_candidate"),
        ("ignore_m3568", mutate("swapz_mm_capture", "entry->length > 3568", "entry->length > 4095"), True, "m3568_bound"),
        ("leak_declined_module_pin", mutate("swapz_mm_route_try", "else\n\t\t\t\tmodule_put(owner);",
                                             "else\n\t\t\t\t(void)owner;"), False, "late_cap_decline"),
    ]
    kernel = directory / "src/kernel"
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for compiler in ("gcc", "clang"):
        standard = next((s for s in ("c23", "c2x")
                         if run([compiler, "-std=" + s, "-fsyntax-only", str(probe)]).returncode == 0), None)
        require(standard, "missing C23 compiler " + compiler)
        entry = {"standard": standard, "version": checked([compiler, "--version"]).decode().splitlines()[0],
                 "baselines": {}, "mutants": {}}
        report[compiler] = entry
        for name, functions, observation, witness in variants:
            (directory / "r095-functions.h").write_text(functions)
            binary = directory / (compiler + "-" + name)
            command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror", "-Wshadow",
                       "-Wstrict-prototypes", "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread",
                       "-no-pie", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                       "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
                       "-include", str(SHIM), "-I", str(kernel), "-I", str(directory)]
            if observation:
                command += ["-DSWAPZ_ROUND095_MM_CAPTURE_OBSERVATION_TEST=1"]
            command += [str(FIXTURE), str(kernel / "zswap-original-ticket.c"),
                        str(kernel / "codec.c"), "-lcrypto", "-o", str(binary)]
            compilation = run(command)
            (evidence / (compiler + "-" + name + "-compile.log")).write_bytes(compilation.stdout + compilation.stderr)
            error = next((line for line in compilation.stderr.decode(errors="replace").splitlines() if "error:" in line),
                         "unclassified compiler diagnostic")
            require(compilation.returncode == 0, compiler + "/" + name + " " + error[:240])
            execution = subprocess.run([str(binary)], capture_output=True, timeout=30, check=False,
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=" + ("0" if witness else "1")})
            (evidence / (compiler + "-" + name + "-run.log")).write_bytes(execution.stdout + execution.stderr)
            if witness:
                marker = rb"R095_A11_FIRST_ERROR " + witness.encode() + rb" line=\d+\n"
                require(execution.returncode == 77 and not execution.stdout and re.fullmatch(marker, execution.stderr),
                        compiler + "/" + name + " not semantic kill")
                entry["mutants"][name] = "KILLED"
                print(compiler + " semantic kill " + name, flush=True)
            else:
                match = re.fullmatch(rb"PASS_HOST_ONLY R095 A11 checks=(\d+) observation=(\d+) sg=(\d+) hash=(\d+)\n", execution.stdout)
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + "/" + name + " " + execution.stderr.decode(errors="replace")[:160])
                entry["baselines"][name] = dict(zip(("checks", "observation", "sg_copies", "hashes"), map(int, match.groups())))
                print(compiler + " " + execution.stdout.decode().strip(), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "tested_commit": checked(["git", "rev-parse", "HEAD"]).decode().strip(),
              "engineering_freeze": FREEZE, "original_linux": LINUX, "host": {}, "first_error": None,
              "native": "NOT_RUN", "auth": 0, "phase_a": "BLOCKED", "compressed_handoff": False,
              "forced_raw_bypass": False, "import": False}
    try:
        with tempfile.TemporaryDirectory(prefix="r095-a11-mm-") as temporary:
            directory = Path(temporary)
            parts = stage(directory, args.linux)
            report["stage"] = "PASS"
            exercise(directory, args.output, parts, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:350]
        print("R095_A11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
