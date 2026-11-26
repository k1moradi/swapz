#!/usr/bin/env python3
"""R096 A7: frozen real gate/broker/codec composition; host boundary only."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "cb38c5de310edc4842e77099b92fc709e1934322"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
BROKER = "src/kernel/zswap-original-ticket.c"
HEADER = "src/kernel/zswap-original-ticket.h"
OWNER = "src/kernel/zswap-original-broker-owner.inc"
PATCH92 = "tests/tools/round092-original-module-boundary.patch"
PATCH94 = "tests/tools/round094-original-broker-owner.patch"
SHIM = "tests/runtime/native/fixtures/round094-owner-shim.h"
MODULE_SHIM = "tests/runtime/native/fixtures/round092-module-shim.h"
HELPER = "tests/tools/round085-original-decode-verify.py"
HELPER80 = "tests/tools/round080-original-lzo1x-independent-decoder-verify.py"
FIXTURE = "tests/runtime/native/fixtures/round096-provider-broker-lifetime.c"
WORKFLOW = ".github/workflows/phase-a-round096-provider-broker-lifetime-host-noauth.yml"
STANDARDS = "docs/testing_standards.md"
STAGE_PATHS = ("src/kernel", PATCH92, PATCH94, SHIM, MODULE_SHIM, HELPER, HELPER80)
PINS = {
    "src/kernel/zswap-original-decoder-shared.c": "3b48a4f6f31ef9c45034db7e0509efe92583e404",
    "src/kernel/zswap-original-decoder-shared.h": "19bce03addcee7a2eeb0983ea360d4e2a5df0912",
    "src/kernel/zswap-original-storage-shared-decoder.c": "05fa6a716dcd5b5fd6a531a63908b2e9bb53cb8f",
    "src/kernel/zswap-original-storage-shared-decoder.h": "b18f05a0d326dfe594e6695f13f757e313a1c3d8",
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    PATCH92: "62db468c14f23b59e7adaae65a11dcb9969f02b3",
    PATCH94: "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
    SHIM: "bc49e924eeee826496264503d0af1b4f1fb8e611",
    MODULE_SHIM: "79623955e77b0b35d17bd14f322412d8ee202c84",
    HELPER: "6beb60c0c42662e11c3fc827dcbdacb1c6167370",
    HELPER80: "c2bd6a4d35bc8261e94743f92166b7c436d3c1f2",
    "src/kernel/dm-target.c": "5f87228daba905f6aa55f950177eecd5291c41e6",
}
POST92 = {BROKER: "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
          HEADER: "6afac83a0655e532ce1ef9b8f290a367e8aabfce"}
POST94 = {BROKER: "ba5e891ef7f80bf0b3021ee6c676529cb72f1972",
          HEADER: "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"}


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(blob(path.read_bytes()) == expected, "whole blob mismatch " + path.name)


def execute(command, evidence, label, cwd=ROOT):
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH")}
    env.update(ASAN_OPTIONS="halt_on_error=1:detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode or result.stderr:
        (evidence / "first-child-error.log").write_text((result.stderr + result.stdout)[:12000])
        diagnostic = next((line for line in result.stderr.splitlines()
                           if "error:" in line or "R096_A7_FIRST_ERROR" in line), "")
        diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
        raise RuntimeError(label + ": exit=" + str(result.returncode) + " " + diagnostic[:200])
    return result.stdout


def stage_frozen(stage, evidence):
    archive = git("archive", FREEZE, *STAGE_PATHS)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(stage, filter="data")
    expected = {}
    for entry in filter(None, git("ls-tree", "-r", "-z", FREEZE, "--", *STAGE_PATHS).split(b"\0")):
        metadata, name = entry.split(b"\t", 1)
        mode, kind, digest = metadata.decode().split()
        require(kind == "blob" and mode in ("100644", "100755"), "nonregular frozen dependency")
        expected[name.decode()] = digest
    require({str(path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()} == set(expected),
            "frozen inventory mismatch")
    for name, digest in expected.items():
        pin(stage / name, digest)
    for name, digest in PINS.items():
        pin(stage / name, digest)
    for patch, post in ((PATCH92, POST92), (PATCH94, POST94)):
        command = ["git", "apply", "--unidiff-zero", "--include=" + BROKER,
                   "--include=" + HEADER, str(stage / patch)]
        execute(command[:2] + ["--check"] + command[2:], evidence, "patch preflight " + patch, cwd=stage)
        execute(command, evidence, "patch " + patch, cwd=stage)
        for name, digest in post.items():
            pin(stage / name, digest)
        execute(command[:2] + ["--reverse", "--check"] + command[2:], evidence,
                "reverse preflight " + patch, cwd=stage)
    pin(stage / OWNER, PINS[OWNER])
    adapter = (stage / "src/kernel/zswap-original-storage-shared-decoder.c").read_text()
    require("swapz_original_decoder_shared_read(&storage->provider" in adapter and
            "swapz_original_decoder_shared_gate_read(" not in adapter,
            "frozen adapter audit changed")
    target = (stage / "src/kernel/dm-target.c").read_text()
    require("swapz_original_decoder_bridge_read(bridge" in target and
            "swapz_original_decoder_shared_gate_read(" not in target,
            "frozen target audit changed")
    return expected


def exercise(compiler, stage, linux, work, evidence, prior, helpers, entry):
    entry["standard"] = helpers["compiler_standard"](compiler)
    shim = prior["build_shim"](linux, work, helpers)
    original = work / "original"
    original.mkdir()
    compressor = prior["staged_bytes"]((linux / prior["LZ4_SOURCE"]).read_bytes(), LINUX, "")
    decompressor = prior["staged_decoder_bytes"]((linux / prior["LZ4_DECODER_SOURCE"]).read_bytes(), LINUX, "")
    require(blob(compressor) == prior["LZ4_POSTIMAGE"] and
            blob(decompressor) == prior["LZ4_DECODER_POSTIMAGE"], "staged LZ4 identity")
    (original / "lz4_compress.c").write_bytes(compressor)
    (original / "lz4_decompress.c").write_bytes(decompressor)
    (original / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    kernel = stage / "src/kernel"
    flags = ["-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie"]
    objects = []
    for path in (linux / "lib/lzo/lzo1x_compress_safe.c", linux / "lib/lzo/lzo1x_decompress_safe.c",
                 original / "lz4_compress.c", original / "lz4_decompress.c"):
        obj = work / ("original-" + path.stem + ".o")
        entry["stage"] = "compile-original-" + path.name
        execute([compiler, "-std=gnu11", *flags, "-I", str(shim), "-DCONFIG_64BIT=1",
                 "-c", str(path), "-o", str(obj)], evidence, entry["stage"])
        objects.append(obj)
    adapter = work / "original-compressor.c"
    adapter.write_text(prior["COMPRESS_ADAPTER"])
    host = [entry["standard"], *flags, "-pthread", "-D_POSIX_C_SOURCE=200809L", "-include", "stddef.h",
            "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1", "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
            "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
            "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
            "-DSWAPZ_ORIGINAL_STORAGE_TEST=1", "-DSWAPZ_ORIGINAL_DECODER_SHARED_TEST=1",
            "-DSWAPZ_ORIGINAL_EXTENT_TEST=1", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
            "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1",
            "-I", str(shim), "-I", str(kernel), "-I", str((stage / SHIM).parent)]
    for path in [kernel / name for name in ("codec.c", "zswap-original-ticket.c",
                "zswap-import-decoder-owner.c", "zswap-original-decode.c",
                "zswap-original-decoder-shared.c")] + [adapter, ROOT / FIXTURE]:
        obj = work / ("product-" + path.stem + ".o")
        extra = ["-include", str(stage / SHIM)] if path.name == "zswap-original-ticket.c" else []
        entry["stage"] = "compile-" + path.name
        execute([compiler, *host, "-Wconversion", "-Wshadow", "-Wpedantic", *extra,
                 "-c", str(path), "-o", str(obj)], evidence, entry["stage"])
        objects.append(obj)
    binary = work / "provider-broker-lifetime"
    entry["stage"] = "link"
    execute([compiler, *flags, "-pthread", "-no-pie", *(str(obj) for obj in objects),
             "-Wl,--wrap=swapz_zswap_import_decoder_owner_get", "-lcrypto", "-o", str(binary)],
            evidence, "link")
    entry["stage"] = "execute"
    output = execute([str(binary)], evidence, "source-linked lifetime")
    matched = re.fullmatch(r"PASS R096_A7 checks=(\d+) broker_sessions=3 codecs=2 external_pauses=2 AUTH0\n",
                           output)
    require(matched and int(matched[1]) >= 50, "missing exact runtime sentinel")
    entry.update(status="PASS", stage="complete", checks=int(matched[1]),
                 broker_sessions=3, codecs=2, external_pauses=2, mutants=0)
    print(compiler, output.strip(), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {"round": "096", "agent": 7, "freeze": FREEZE, "linux": LINUX,
              "AUTH": 0, "phase_a": "BLOCKED", "direct_compressed_handoff": False,
              "forced_raw_bypass": False, "import_active": False,
              "native": "NOT_RUN", "physical": False, "compilers": {},
              "first_error": None, "conclusion": "FAIL",
              "adapter_scope": "source audit only; frozen adapter is ungated",
              "host_boundaries": ["pthread/allocator/module ABI", "one-shot cap consumption",
                                  "external route join", "retained storage pin"]}
    entry = None
    try:
        report["tested_commit"] = git("rev-parse", "HEAD").decode().strip()
        report["parent"] = git("rev-parse", "HEAD^").decode().strip()
        require(report["parent"] == os.environ.get("SWAPZ_PUSH_BEFORE_SHA"), "push-before parent mismatch")
        require(git("branch", "--show-current").strip() == b"main", "not main")
        require(len(git("rev-list", "--parents", "-n1", "HEAD").split()) == 2, "not sole parent")
        require(not git("status", "--porcelain", "--untracked-files=all"), "dirty checkout")
        parent = git("show", "HEAD^:" + STANDARDS)
        frozen = git("show", FREEZE + ":" + STANDARDS)
        current = (ROOT / STANDARDS).read_bytes()
        require(blob(frozen) == "4152a1ce0c067ccb6b872f5f7aa0b89507ec8f2e" and
                len(frozen) == 1856114 and parent.startswith(frozen) and
                current.startswith(parent) and len(current) > len(parent), "historical byte prefix")
        report["standards"] = {"parent_blob": blob(parent), "parent_bytes": len(parent),
                               "current_blob": blob(current), "current_bytes": len(current)}
        report["test_blobs"] = {name: blob((ROOT / name).read_bytes()) for name in
                               (FIXTURE, WORKFLOW, str(Path(__file__).relative_to(ROOT)))}
        linux = args.linux_root.resolve()
        with tempfile.TemporaryDirectory(prefix="r096-a7-") as temporary:
            work = Path(temporary)
            stage = work / "frozen"
            stage.mkdir()
            report["frozen_inventory"] = stage_frozen(stage, evidence)
            report["broker_postimages"] = [POST92, POST94]
            prior = runpy.run_path(str(stage / HELPER))
            require(prior["PIN"] == LINUX and
                    prior["LZ4_POSTIMAGE"] == "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                    prior["LZ4_DECODER_POSTIMAGE"] == "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                    "original codec staging pin")
            report["original_blobs"] = prior["ORIGINAL"]
            helpers = prior["verify_inputs"](linux)
            for compiler in ("gcc", "clang"):
                entry = {"status": "FAIL", "stage": "init", "first_error": None}
                report["compilers"][compiler] = entry
                directory = work / compiler
                directory.mkdir()
                exercise(compiler, stage, linux, directory, evidence, prior, helpers, entry)
            require(not helpers["checked"](["git", "-C", str(linux), "status", "--porcelain",
                                            "--untracked-files=all"], "original clean after run"),
                    "original Linux changed")
        require(not git("status", "--porcelain", "--untracked-files=all"), "source changed")
        report["conclusion"] = "PASS_FROZEN_GATE_BROKER_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        report["first_error"] = str(error).split("\n", 1)[0][:320]
        if entry is not None and entry["status"] != "PASS":
            entry["first_error"] = report["first_error"]
        print("R096_A7_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
