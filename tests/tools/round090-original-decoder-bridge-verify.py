#!/usr/bin/env python3
"""Round090 exact pinned original LZ4/LZO1X bridge, strict HOST ONLY.

No upstream rewrite, production Kbuild, VM, fake source credential, or device.
The previous accepted isolated noDict transformations are reused by SHA;
only the NEW bridge/fixture is compiled and exercised in this lane.
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
PREVIOUS = ROOT / "tests/tools/round085-original-decode-verify.py"
BRIDGE = ROOT / "src/kernel/zswap-original-decoder-bridge.c"
HEADER = ROOT / "src/kernel/zswap-original-decoder-bridge.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round090-original-decoder-bridge.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run_one(compiler: str, original_linux: Path, workspace: Path,
            prior: dict, helpers: dict, staged_compressor: bytes,
            staged_decoder: bytes, output: Path) -> dict:
    compiler_name = Path(compiler).name
    checked = helpers["checked"]
    compile_object = helpers["compile_object"]
    run_command = helpers["run_command"]
    standard = helpers["compiler_standard"](compiler)
    state = {"standard": standard, "stage": "compile", "status": "NOT_RUN",
             "actual_checks": 0, "first_error": None}
    try:
        shim = prior["build_shim"](original_linux, workspace, helpers)
        staged = workspace / "staged"
        staged.mkdir()
        (staged / "lz4_compress.c").write_bytes(staged_compressor)
        (staged / "lz4_decompress.c").write_bytes(staged_decoder)
        (staged / "lz4defs.h").write_bytes((original_linux / "lib/lz4/lz4defs.h").read_bytes())
        require(blob((staged / "lz4_compress.c").read_bytes()) == prior["LZ4_POSTIMAGE"] and
                blob((staged / "lz4_decompress.c").read_bytes()) == prior["LZ4_DECODER_POSTIMAGE"],
                "staged compiler file hash changed")
        objects = []
        for part in ("lib/lzo/lzo1x_compress_safe.c",
                     "lib/lzo/lzo1x_decompress_safe.c",
                     "lib/lz4/lz4_compress.c",
                     "lib/lz4/lz4_decompress.c"):
            source = staged / Path(part).name if part.startswith("lib/lz4") else original_linux / part
            obj = workspace / ("original-" + Path(part).stem + ".o")
            state["stage"] = "compile-original-" + Path(part).name
            compile_object(compiler, "-std=gnu11", source, obj,
                           ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
            objects.append(obj)
        adapter = workspace / "original-compressor.c"
        adapter.write_text(prior["COMPRESS_ADAPTER"])
        product_flags = ["-I", str(shim), "-I", str(ROOT / "src/kernel"),
                         "-DSWAPZ_ORIGINAL_STORAGE_TEST=1",
                         "-DSWAPZ_ORIGINAL_EXTENT_TEST=1",
                         "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
                         "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1"]
        for source in (ROOT / "src/kernel/codec.c",
                       ROOT / "src/kernel/zswap-import-decoder-owner.c",
                       ROOT / "src/kernel/zswap-original-decode.c",
                       BRIDGE, FIXTURE, adapter):
            state["stage"] = "compile-product-" + source.name
            obj = workspace / ("product-" + source.stem + ".o")
            compile_object(compiler, standard, source, obj, product_flags)
            objects.append(obj)
        program = workspace / "bridge-host"
        state["stage"] = "link"
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                 *(str(item) for item in objects), "-pthread", "-lcrypto",
                 "-o", str(program)], "bridge link")
        state["stage"] = "execute"
        execution = run_command([str(program)], "bridge run", timeout=60)
        match = re.fullmatch(
            r"PASS ROUND090_AGENT7 checks=(\d+) tokens=(\d+) actual_original=2 AUTH0\n",
            execution.stdout)
        failure = prior["runtime_failure"](execution, None)
        if failure is not None or match is None or execution.returncode != 0 or execution.stderr:
            diagnostics = (execution.stderr or execution.stdout).splitlines()
            (output / (compiler_name + "-actual-stderr.txt")).write_text(
                "\n".join(diagnostics[:30])[:3000], encoding="utf-8")
            state["first_error"] = failure or {
                "kind": "fixture", "exit": execution.returncode,
                "location": next((line[:180] for line in diagnostics if "FIRST_ERROR" in line),
                                 "unavailable")}
            raise RuntimeError("actual source-linked bridge fixture rejected")
        state["actual_checks"] = int(match.group(1))
        require(state["actual_checks"] > 30000 and int(match.group(2)) == 64,
                "insufficient bridge regression checks")
        state["status"] = "PASS"
        state["stage"] = "complete"
        print(f"PASS ROUND090_AGENT7 {compiler_name} {standard} "
              f"actual_original_LZ4_LZO1X checks={state['actual_checks']} "
              f"lease_64 ABA_rejected close_no_reader_wait", file=sys.stderr)
        return state
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        if state["first_error"] is None:
            # Do not leak runner paths or raw child stderr to public logs.
            state["first_error"] = {"kind": type(error).__name__,
                                    "location": "unavailable", "stage": state["stage"],
                                    "reason": str(error).split("\n", 1)[0][-200:]}
        print(f"FIRST_ERROR ROUND090_AGENT7 {compiler_name} "
              + json.dumps(state["first_error"], sort_keys=True), file=sys.stderr)
        return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    directory = args.evidence_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {"round": "090", "agent": 7, "status": "FAIL",
              "linux_pin": PIN, "source_mapped_authenticated": 0,
              "phase_a": "BLOCKED", "direct_compressed_handoff": False,
              "forced_raw_bypass": False, "import_active": False,
              "compilers": {}, "first_error": None}
    linux = args.linux_root.resolve()
    try:
        prior = runpy.run_path(str(PREVIOUS))
        require(prior["PIN"] == PIN and prior["LZ4_POSTIMAGE"] ==
                "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                prior["LZ4_DECODER_POSTIMAGE"] ==
                "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                "unauthorized upstream staging pin")
        helpers = prior["verify_inputs"](linux)
        require(helpers["checked"](["git", "-C", str(linux), "rev-parse", "HEAD"],
                                   "exact original pin") == PIN,
                "original Linux checkout mismatch")
        require(not helpers["checked"](["git", "-C", str(linux), "status",
                                        "--porcelain", "--untracked-files=all"],
                                       "clean original"), "dirty original Linux")
        prior["stage_plan"](linux, helpers, report)
        for source in (BRIDGE, HEADER, FIXTURE):
            require(source.is_file() and source.stat().st_size > 300,
                    "missing new source: " + source.name)
        require("#define SWAPZ_ORIGINAL_DECODER_BRIDGE_ACTIVE 0U" in HEADER.read_text()
                and "SWAPZ_ORIGINAL_STORAGE_TEST" in BRIDGE.read_text(),
                "live production gate unexpectedly enabled")
        report["new_blobs"] = {str(path.relative_to(ROOT)): blob(path.read_bytes())
                               for path in (BRIDGE, HEADER, FIXTURE)}
        if args.preflight_only:
            report["status"] = "PASS_PREFLIGHT_ONLY"
            print("PASS ROUND090_AGENT7 preflight exact pins and nine negative stage controls",
                  file=sys.stderr)
            return 0
        with tempfile.TemporaryDirectory(prefix="round090-decoder-bridge-") as temporary:
            for compiler_name in ("gcc", "clang"):
                compiler = shutil.which(compiler_name)
                require(compiler is not None, f"missing compiler {compiler_name}")
                workspace = Path(temporary) / compiler_name
                workspace.mkdir()
                staged_compressor = prior["staged_bytes"](
                    (linux / prior["LZ4_SOURCE"]).read_bytes(), PIN, "")
                staged_decoder = prior["staged_decoder_bytes"](
                    (linux / prior["LZ4_DECODER_SOURCE"]).read_bytes(), PIN, "")
                state = run_one(compiler, linux, workspace, prior, helpers,
                                staged_compressor, staged_decoder, directory)
                report["compilers"][compiler_name] = state
                if state["status"] != "PASS":
                    report["first_error"] = {"compiler": compiler_name,
                                            **state["first_error"]}
                    return 1
        # Source immutability is part of the qualification result, not just
        # an artifact annotation: a changed pristine checkout must exit red.
        require(not helpers["checked"]([
            "git", "-C", str(linux), "status", "--porcelain",
            "--untracked-files=all"], "final pinned Linux clean"),
            "original Linux dirtied during qualification")
        report["status"] = "PASS_STAGED_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        report["first_error"] = {"kind": type(error).__name__, "location": "unavailable",
                                 "reason": str(error).split("\n", 1)[0][-200:]}
        print("FIRST_ERROR ROUND090_AGENT7 "
              + json.dumps(report["first_error"], sort_keys=True), file=sys.stderr)
        return 1
    finally:
        try:
            if linux.is_dir() and (linux / ".git").exists():
                actual_status = subprocess.run(["git", "-C", str(linux), "status",
                                                "--porcelain", "--untracked-files=all"],
                                               text=True, capture_output=True, check=False)
                if actual_status.returncode or actual_status.stdout.strip():
                    report["status"] = "FAIL_SOURCE_DIRTY"
                    report["first_error"] = {"kind": "pristine_revalidation"}
            (directory / "results.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report, indent=2))
        except OSError:
            print("FIRST_ERROR ROUND090_AGENT7 unable to retain private results", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
