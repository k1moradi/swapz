#!/usr/bin/env python3
"""Actual shared provider host qualification; no replay of R093 corpus."""
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
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
SOURCE = ROOT / "src/kernel/zswap-original-decoder-shared.c"
HEADER = SOURCE.with_suffix(".h")
FIXTURE = ROOT / "tests/runtime/native/fixtures/round094-decoder-shared-provider.c"
MUTANTS = (
    ("epoch", "expected->lifecycle_epoch != owner->epoch ||", "0 ||",
     "epoch_before_lookup"),
    ("generation", "snapshot.handle.generation != expected->generation ||", "0 ||",
     "wrong_generation"),
    ("index", "snapshot.handle.slot_index != expected->slot_index ||", "0 ||",
     "wrong_pin_index"),
    ("admission", "if (owner->state != SHARED_OPEN)", "if (owner->state == SHARED_FAULTED)",
     "closing_refuses"),
    ("read_release", "release_result = swapz_zswap_import_decoder_owner_put(&lease);",
     "release_result = 0;", "constant_refs"),
)

def require(ok, label):
    if not ok:
        raise RuntimeError(label)

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()

def compiler_run(compiler, linux, directory, previous, helpers, evidence, state):
    compile_object = helpers["compile_object"]
    checked = helpers["checked"]
    run = helpers["run_command"]
    standard = helpers["compiler_standard"](compiler)
    state["standard"] = standard
    shim = previous["build_shim"](linux, directory, helpers)
    staged = directory / "staged"
    staged.mkdir()
    compressor = previous["staged_bytes"]((linux / previous["LZ4_SOURCE"]).read_bytes(), PIN, "")
    decompressor = previous["staged_decoder_bytes"]((linux / previous["LZ4_DECODER_SOURCE"]).read_bytes(), PIN, "")
    require(blob(compressor) == previous["LZ4_POSTIMAGE"] and
            blob(decompressor) == previous["LZ4_DECODER_POSTIMAGE"], "staged codec identity")
    (staged / "lz4_compress.c").write_bytes(compressor)
    (staged / "lz4_decompress.c").write_bytes(decompressor)
    (staged / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    objects = []
    for relative in ("lib/lzo/lzo1x_compress_safe.c", "lib/lzo/lzo1x_decompress_safe.c",
                     "lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c"):
        name = Path(relative).name
        state["stage"] = "compile-original-" + name
        obj = directory / (name + ".o")
        compile_object(compiler, "-std=gnu11",
                       staged / name if relative.startswith("lib/lz4") else linux / relative,
                       obj, ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
        objects.append(obj)
    adapter = directory / "original-compressor.c"
    adapter.write_text(previous["COMPRESS_ADAPTER"])
    flags = ["-I", str(shim), "-I", str(ROOT / "src/kernel"),
             "-DSWAPZ_ORIGINAL_STORAGE_TEST=1", "-DSWAPZ_ORIGINAL_DECODER_SHARED_TEST=1",
             "-DSWAPZ_ORIGINAL_EXTENT_TEST=1", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
             "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1"]
    for source in (ROOT / "src/kernel/codec.c", ROOT / "src/kernel/zswap-import-decoder-owner.c",
                   ROOT / "src/kernel/zswap-original-decode.c", FIXTURE, adapter):
        state["stage"] = "compile-" + source.name
        obj = directory / (source.stem + ".o")
        compile_object(compiler, standard, source, obj, flags)
        objects.append(obj)
    original = SOURCE.read_text()
    for case in (None, *MUTANTS):
        name = case[0] if case else "baseline"
        source = SOURCE
        if case:
            _, old, new, expected = case
            require(original.count(old) == 1 and old != new, "mutation anchor " + name)
            source = directory / (name + ".c")
            source.write_text(original.replace(old, new, 1))
        state["stage"] = "compile-" + name
        obj = directory / (name + ".o")
        compile_object(compiler, standard, source, obj, flags)
        if case:
            state["mutants_compiled"] += 1
        binary = directory / name
        state["stage"] = "link-" + name
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                 str(obj), *(str(item) for item in objects), "-pthread", "-lcrypto",
                 "-o", str(binary)], name + " link")
        state["stage"] = "execute-" + name
        observed = run([str(binary)], name, timeout=65)
        failure = previous["runtime_failure"](observed, None)
        if case:
            state["mutants_executed"] += 1
            matched = re.fullmatch(r"FIRST_ERROR round094-agent7 " + re.escape(expected) +
                                   r" line=[1-9][0-9]*\n", observed.stderr)
            if (observed.returncode != 77 or observed.stdout or not matched or
                    (failure and failure["kind"] == "sanitizer")):
                state["first_error"] = failure or {"kind": "mutant_not_killed", "name": name}
                (evidence / (Path(compiler).name + "-" + name + ".stderr")).write_text(observed.stderr[:3600])
                raise RuntimeError("semantic mutant not killed: " + name)
            state["mutants_killed"].append(name)
        else:
            matched = re.fullmatch(r"PASS ROUND094_AGENT7 checks=(\d+) records=(\d+) sidecar=(\d+) owner=(\d+) handle=(\d+) codecs=2 AUTH0\n", observed.stdout)
            if failure or not matched:
                state["first_error"] = failure or {"kind": "baseline_output"}
                (evidence / (Path(compiler).name + "-baseline.stderr")).write_text(observed.stderr[:3600])
                raise RuntimeError("baseline rejected")
            checks, records, sidecar, owner, handle = map(int, matched.groups())
            require(checks > 2048 and records == 1024 and sidecar == 16 and handle == 24,
                    "incomplete actual provider coverage")
            state.update(checks=checks, simultaneous_records=records,
                         sidecar_bytes=sidecar, owner_bytes=owner, handle_bytes=handle)
    state.update(status="PASS", stage="complete")
    print("PASS ROUND094_AGENT7 " + Path(compiler).name, file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    linux = args.linux_root.resolve()
    report = {"round": "094", "agent": 7, "status": "FAIL", "linux_pin": PIN,
              "compilers": {}, "first_error": None, "source_authenticated": 0,
              "phase_a": "BLOCKED", "direct_compressed_handoff": False,
              "forced_raw_bypass": False, "import_active": False, "native": "NOT_RUN"}
    state = None
    try:
        previous = runpy.run_path(str(ROOT / "tests/tools/round085-original-decode-verify.py"))
        require(previous["PIN"] == PIN, "Linux pin drift")
        helpers = previous["verify_inputs"](linux)
        checked = helpers["checked"]
        require(checked(["git", "-C", str(linux), "rev-parse", "HEAD"], "Linux pin") == PIN,
                "Linux source drift")
        require(not checked(["git", "-C", str(linux), "status", "--porcelain", "--untracked-files=all"], "pristine Linux"), "dirty Linux")
        previous["stage_plan"](linux, helpers, report)
        parent = subprocess.check_output(["git", "-C", str(ROOT), "show", "HEAD^:docs/testing_standards.md"])
        current = (ROOT / "docs/testing_standards.md").read_bytes()
        require(current.startswith(parent), "complete parent standards prefix")
        report["standards"] = {"parent_blob": blob(parent), "parent_bytes": len(parent),
                               "current_blob": blob(current), "current_bytes": len(current)}
        require("#define SWAPZ_ORIGINAL_DECODER_SHARED_ACTIVE 0U" in HEADER.read_text(), "activation drift")
        report["source_blobs"] = {str(path.relative_to(ROOT)): blob(path.read_bytes())
                                  for path in (SOURCE, HEADER, FIXTURE, Path(__file__))}
        with tempfile.TemporaryDirectory(prefix="round094-shared-provider-") as temporary:
            for name in ("gcc", "clang"):
                state = {"status": "FAIL", "stage": "init", "first_error": None,
                         "mutants_compiled": 0, "mutants_executed": 0, "mutants_killed": []}
                report["compilers"][name] = state
                compiler = shutil.which(name)
                require(compiler is not None, "missing compiler " + name)
                directory = Path(temporary) / name
                directory.mkdir()
                compiler_run(compiler, linux, directory, previous, helpers, evidence, state)
        require(not checked(["git", "-C", str(linux), "status", "--porcelain", "--untracked-files=all"], "final pristine Linux"), "Linux changed")
        report["status"] = "PASS_ACTUAL_SHARED_PROVIDER_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        first = state["first_error"] if state else None
        first = first or {"kind": type(error).__name__, "location": "unavailable",
                          "reason": str(error).split("\n", 1)[0][:350]}
        if state is not None:
            state["first_error"] = first
        report["first_error"] = first
        print("FIRST_ERROR ROUND094_AGENT7 " + json.dumps(first, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    raise SystemExit(main())
