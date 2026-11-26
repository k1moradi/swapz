#!/usr/bin/env python3
"""Actual R097 gated DM transaction and R096 autonomous retry overlay.
Only Linux/DM/lower/upper primitives and the proposed observation wrapper are
substitutes. No native build, load, physical I/O or activation.
"""
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
FREEZE = "f7cb6969db189c03d592a89cae43e5464946c716"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
DM = "src/kernel/dm-target.c"
BROKER = "src/kernel/zswap-original-ticket.c"
HEADER = "src/kernel/zswap-original-ticket.h"
OWNER = "src/kernel/zswap-original-broker-owner.inc"
PATCH92 = "tests/tools/round092-original-module-boundary.patch"
PATCH94 = "tests/tools/round094-original-broker-owner.patch"
PATCH96 = "tests/tools/round096-original-owner-retry.patch"
SHIM = "tests/runtime/native/fixtures/round094-owner-shim.h"
MODULE_SHIM = "tests/runtime/native/fixtures/round092-module-shim.h"
FIXTURE = "tests/runtime/native/fixtures/round097-connected-target.c"
HELPER = "tests/tools/round085-original-decode-verify.py"
HELPER80 = "tests/tools/round080-original-lzo1x-independent-decoder-verify.py"
STAGE_PATHS = ("src/kernel", PATCH92, PATCH94, PATCH96, SHIM, MODULE_SHIM, HELPER, HELPER80)
PINS = {
    DM: "c60433fd6c482df9b80376ebd6326db3e56977fa",
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    PATCH92: "62db468c14f23b59e7adaae65a11dcb9969f02b3",
    PATCH94: "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
    PATCH96: "6ee63e6515dd2f0337c49d1a868f39435b93119c",
    "src/kernel/zswap-original-storage-shared-decoder.c": "c59cdf4d4e203a9a40d09e9048d3eba786d2e0cc",
    "src/kernel/zswap-original-storage-shared-decoder.h": "6b1e3dc0230740be0d5f0e038b270d4984b5277d",
    "src/kernel/zswap-original-decoder-shared.c": "3b48a4f6f31ef9c45034db7e0509efe92583e404",
    "src/kernel/zswap-original-decoder-shared.h": "19bce03addcee7a2eeb0983ea360d4e2a5df0912",
    SHIM: "bc49e924eeee826496264503d0af1b4f1fb8e611",
    MODULE_SHIM: "79623955e77b0b35d17bd14f322412d8ee202c84",
    HELPER: "6beb60c0c42662e11c3fc827dcbdacb1c6167370",
    HELPER80: "c2bd6a4d35bc8261e94743f92166b7c436d3c1f2",
    "src/kernel/zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "src/kernel/zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "src/kernel/zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "src/kernel/zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "src/kernel/authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "src/kernel/authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
}
POST92 = {BROKER: "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
          HEADER: "6afac83a0655e532ce1ef9b8f290a367e8aabfce"}
POST94 = {BROKER: "ba5e891ef7f80bf0b3021ee6c676529cb72f1972",
          HEADER: "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"}
POST96 = {BROKER: "70109f2c2ce9f60681649bd4807382248d0a41a2",
          OWNER: "278a93a3fd3fd260444aebc55d4a87112e56f704", HEADER: POST94[HEADER]}
TARGET_POST = "f1922cc26caf7bfa097c1f561f8719744c3a4e75"
FIXTURE_POST = "e4b428e7c1ec6ff581d83482c6e30134ed66d260"
MUTANTS = (
    ("no_retry_transfer", "if (error == -EBUSY && ctx->original_target_drained) {",
     "if (false && error == -EBUSY && ctx->original_target_drained) {"),
    ("wrong_read_epoch", "swapz_shared_storage_decoder_read(storage, epoch, pin, compressed,",
     "swapz_shared_storage_decoder_read(storage, epoch + 1U, pin, compressed,"),
    ("ignore_gated_scope", "if (!swapz_round097_scope_ready(ctx) || !key->logical_page ||",
     "if ((!swapz_round097_scope_ready(ctx) && false) || !key->logical_page ||"),
    ("ignore_missing_observation", "if (swapz_trial_observation_active())",
     "if (swapz_trial_observation_active() && false)"),
)


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(blob(path.read_bytes()) == expected, "whole blob mismatch " + path.name)


def execute(command, evidence, label, cwd=ROOT, expected=0, mutant=False):
    env = {key: value for key, value in os.environ.items()
           if key not in ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH")}
    env.update(ASAN_OPTIONS="halt_on_error=1:detect_leaks=" + ("0" if mutant else "1"),
               UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=180)
    if result.returncode != expected or (expected == 0 and result.stderr):
        (evidence / "first-child-error.log").write_text((result.stderr + result.stdout)[:16000])
        diagnostic = next((line for line in result.stderr.splitlines() if "error:" in line), "")
        raise RuntimeError(label + ": exit=" + str(result.returncode) + " " + diagnostic[:200])
    return result


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
    for patch, post in ((PATCH92, POST92), (PATCH94, POST94), (PATCH96, POST96)):
        command = ["git", "apply", "--unidiff-zero", "--include=" + BROKER,
                   "--include=" + HEADER, "--include=" + OWNER, str(stage / patch)]
        execute(command[:2] + ["--check"] + command[2:], evidence, "patch preflight " + patch, cwd=stage)
        execute(command, evidence, "patch " + patch, cwd=stage)
        for name, digest in post.items():
            pin(stage / name, digest)
        execute(command[:2] + ["--reverse", "--check"] + command[2:],
                evidence, "reverse preflight " + patch, cwd=stage)
    pin(stage / OWNER, POST96[OWNER])
    return len(expected)


def function(source, anchor):
    # Actual definitions at column zero; nested braces remain indented.
    # The first full unindented closing brace is the function/struct boundary.
    require(source.count(anchor) == 1, "nonunique function " + anchor)
    tail = source.split(anchor, 1)[1]
    require("\n}\n" in tail, "missing function end " + anchor)
    return anchor + tail.split("\n}\n", 1)[0] + "\n}\n"


def fragment(source, name, round_number):
    begin, end = f"/* ROUND{round_number}_{name}_BEGIN */", f"/* ROUND{round_number}_{name}_END */"
    require(source.count(begin) == source.count(end) == 1, "fragment " + name)
    return source.split(begin, 1)[1].split(end, 1)[0]


def extract_target(source):
    record = source.split("struct swapz_round089_route {", 1)[1].split("};", 1)[0]
    record = "struct swapz_round089_route {" + record + "};\n"
    claim_context = source.split("struct swapz_round091_claim_context {", 1)[1].split("};", 1)[0]
    claim_context = "struct swapz_round091_claim_context {" + claim_context + "};\n"
    fragments = [
        function(source, "static void swapz_round089_revoke_route_locked(struct swapz_dm *ctx)\n{"),
        function(source, "static __maybe_unused int swapz_round089_register_route("),
        function(source, "static bool swapz_round089_route_matches_locked("),
        function(source, "static __maybe_unused int swapz_round090_storage_write("),
        function(source, "static __maybe_unused int swapz_round090_storage_read("),
        function(source, "static __maybe_unused int swapz_round090_storage_flush("),
        fragment(source, "GENERATION", "094"),
        function(source, "static void swapz_round090_publish_target(struct swapz_dm *ctx)\n{"),
        fragment(source, "OWNER_CLOSE", "094"),
        function(source, "static void swapz_round090_cap_release_work(struct work_struct *work)\n{"),
        function(source, "static void swapz_round090_unpublish_target(struct swapz_dm *ctx)\n{"),
        fragment(source, "SETUP", "094"),
        function(source, "static void swapz_round094_setup_work(struct work_struct *work)\n{"),
        function(source, "static void swapz_round094_teardown_work(struct work_struct *work)\n{"),
        function(source, "static void swapz_round090_release_work(struct work_struct *work)\n{"),
        function(source, "static void swapz_round091_release_candidate("),
        function(source, "static bool swapz_round091_retain_candidate_locked("),
        fragment(source, "TRANSACTION", "091"),
        fragment(source, "TYPED_READ", "091"),
        function(source, "static bool swapz_round091_ordered_claim_permitted(void)\n{"),
        claim_context,
        function(source, "static int swapz_round091_claim_reserved("),
        fragment(source, "SCOPE", "097"),
        function(source, "static bool swapz_round091_process_candidate("),
        fragment(source, "TARGET_RELEASE", "096"),
    ]
    return record, "\n".join(fragments)


def source_checks(source):
    require("swapz_round091_ordered_claim_permitted(void)\n{\n\treturn false;\n}" in source,
            "live guard changed")
    require(source.count("swapz_round091_process_candidate(") == 2 and
            "swapz_round091_process_candidate(ctx, entry,\n\t\t\t\t\tswapz_round091_ordered_claim_permitted())" in source,
            "unexpected native positive entry")
    for anchor in ("static bool swapz_round090_provider_lookup(", "static void swapz_round090_candidate_get("):
        body = function(source, anchor)
        require("if (!swapz_round091_ordered_claim_permitted())" in body,
                "capture must decline while live gate false")
    require(source.count("list_add_tail(&entry->list, &ctx->incoming);") == 1, "canonical FIFO")
    require("ctx->original_trial = is_nullb && !ctx->physical_backing;" in source, "physical guard")
    require("swapz_drain(ti);" in source and "flush_work(&ctx->original_release_work);" in source,
            "drain lifetime")
    read = function(source, "static int swapz_read(struct swapz_dm *ctx, struct bio *bio)\n{")
    require(read.index("swapz_round097_read_original_pinned(") <
            read.index("swapz_copy_bio_accounted(") <
            read.index("swapz_shared_original_put(&ctx->authority, original_pin)"),
            "native typed pin must span final copy")
    dtr = function(source, "static void swapz_dtr(struct dm_target *ti)\n{")
    require(dtr.index("swapz_drain(ti);") <
            dtr.index("swapz_round097_retire_target_records(ctx)") <
            dtr.index("swapz_round096_target_can_free(ctx, false)") <
            dtr.index("swapz_free(ctx);"), "native close must not assume retry")
    setup = function(source, "static int swapz_round094_setup(struct swapz_dm *ctx)\n{")
    require(setup.index("swapz_mm_broker_owner_open(") < setup.index("swapz_round094_open_storage(ctx)") <
            setup.index("swapz_round094_install_owner(ctx, &ctx->original_retired_cap)"), "fresh cap before gate")


def compile_and_run(compiler, stage, linux, work, evidence, prior, helpers, record, fragments):
    standard = helpers["compiler_standard"](compiler)
    shim = prior["build_shim"](linux, work, helpers)
    original = work / "original"
    original.mkdir()
    (original / "lz4_compress.c").write_bytes(prior["staged_bytes"](
        (linux / prior["LZ4_SOURCE"]).read_bytes(), LINUX, ""))
    (original / "lz4_decompress.c").write_bytes(prior["staged_decoder_bytes"](
        (linux / prior["LZ4_DECODER_SOURCE"]).read_bytes(), LINUX, ""))
    (original / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    kernel = stage / "src/kernel"
    flags = ["-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie"]
    objects = []
    for path in (linux / "lib/lzo/lzo1x_compress_safe.c", linux / "lib/lzo/lzo1x_decompress_safe.c",
                 original / "lz4_compress.c", original / "lz4_decompress.c"):
        obj = work / ("original-" + path.stem + ".o")
        execute([compiler, "-std=gnu11", *flags, "-I", str(shim), "-DCONFIG_64BIT=1",
                 "-c", str(path), "-o", str(obj)], evidence, compiler + " original " + path.name)
        objects.append(obj)
    adapter = work / "original-compressor.c"
    adapter.write_text(prior["COMPRESS_ADAPTER"])
    host = [standard, *flags, "-pthread", "-D_POSIX_C_SOURCE=200809L", "-include", "stddef.h",
            "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1", "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
            "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
            "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
            "-DSWAPZ_ORIGINAL_STORAGE_TEST=1", "-DSWAPZ_ORIGINAL_EXTENT_TEST=1",
            "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1", "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1",
            "-DSWAPZ_SHARED_ORIGINAL_TEST=1", "-DSWAPZ_SHARED_STORAGE_DECODER_TEST=1",
            "-DSWAPZ_ORIGINAL_DECODER_SHARED_TEST=1",
            "-I", str(shim), "-I", str(kernel), "-I", str(work),
            "-I", str((stage / SHIM).parent)]
    broker_wrapper = work / "r097-broker.c"
    broker_wrapper.write_text('#include "zswap-original-ticket.c"\nvoid r097_run_builtin_retry(void) { owner_retry_run(); }\n')
    for path in [kernel / name for name in ("authority.c", "engine.c", "codec.c",
                "zswap-original-storage.c", "zswap-original-extent.c",
                "zswap-import-decoder-owner.c", "zswap-original-decoder-shared.c",
                "zswap-original-storage-shared-decoder.c",
                "zswap-original-decode.c", "zswap-original-decoder-bridge.c")] + [adapter, broker_wrapper]:
        obj = work / ("product-" + path.stem + ".o")
        extra = ["-include", str(stage / SHIM)] if path == broker_wrapper else []
        execute([compiler, *host, *extra, "-c", str(path), "-o", str(obj)],
                evidence, compiler + " product " + path.name)
        objects.append(obj)
    (work / "route-record.h").write_text(record)
    fixture = work / "composed.c"
    fixture.write_bytes((ROOT / FIXTURE).read_bytes())
    pin(fixture, FIXTURE_POST)
    result = {"standard": standard, "mutants": []}
    for name, old, new in (("baseline", "", ""), *MUTANTS):
        code = fragments
        if old:
            require(code.count(old) == 1, "mutation anchor " + name)
            code = code.replace(old, new, 1)
        (work / "target-fragments.h").write_text(code)
        binary = work / "composed-host"
        execute([compiler, *host, "-Wconversion", "-Wshadow", str(fixture),
                 *(str(obj) for obj in objects), "-lcrypto", "-no-pie", "-o", str(binary)],
                evidence, compiler + " compile fixture " + name)
        run = execute([str(binary)], evidence, compiler + " run " + name,
                      expected=77 if old else 0, mutant=bool(old))
        if old:
            require(not run.stdout and re.fullmatch(r"R097_SEMANTIC_FAIL line=\d+ [^\n]+\n", run.stderr),
                    "not a semantic kill " + name)
            result["mutants"].append({"name": name, "witness": run.stderr.strip()})
        else:
            match = re.fullmatch(r"PASS R097_CONNECTED checks=(\d+) claims=3 errors=1 reads=2 fallbacks=2 preparations=2 reopens=5 retries=5 observation_losses=3 AUTH0\n",
                                 run.stdout)
            require(match, "baseline counts")
            result.update(checks=int(match[1]), claims=3, claimed_errors=1, typed_reads=2,
                          modeled_fallbacks=2, modeled_preparations=2, reopens=5, retries=5, observation_losses=3)
            print(compiler, run.stdout.strip(), flush=True)
    print(compiler, json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"round": "097", "agent": 3, "tested_commit": git("rev-parse", "HEAD").decode().strip(),
              "freeze": FREEZE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
              "native": "NOT_RUN", "physical": False, "compilers": {}, "first_error": None,
              "conclusion": "FAIL"}
    try:
        pin(ROOT / DM, TARGET_POST)
        pin(ROOT / FIXTURE, FIXTURE_POST)
        source = (ROOT / DM).read_text()
        source_checks(source)
        record, fragments = extract_target(source)
        report["fragment_sha256"] = hashlib.sha256(fragments.encode()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="r097-connected-") as directory:
            workspace = Path(directory)
            stage = workspace / "frozen"
            stage.mkdir()
            report["frozen_inventory_count"] = stage_frozen(stage, evidence)
            prior = runpy.run_path(str(stage / HELPER))
            require(prior["PIN"] == LINUX and
                    prior["LZ4_POSTIMAGE"] == "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                    prior["LZ4_DECODER_POSTIMAGE"] == "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                    "original codec staging pin")
            linux = args.linux_root.resolve()
            helpers = prior["verify_inputs"](linux)
            for compiler in ("gcc", "clang"):
                work = workspace / compiler
                work.mkdir()
                report["compilers"][compiler] = compile_and_run(
                    compiler, stage, linux, work, evidence, prior, helpers, record, fragments)
        report["conclusion"] = "PASS_ACTUAL_GATED_TARGET_RETRY_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        report["first_error"] = str(error).split("\n", 1)[0][:320]
        print("R097_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
