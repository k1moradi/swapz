#!/usr/bin/env python3
"""New scoped candidate/claim and selected recorder correlation only.
Actual frozen MM accessor, gated storage, broker, codecs and recorder owner.
Linux/DM/lower/core/scope controller are explicit host boundaries. No activation.
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
FREEZE = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
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
FIXTURE = "tests/runtime/native/fixtures/round098-scoped-target.c"
HELPER = "tests/tools/round085-original-decode-verify.py"
HELPER80 = "tests/tools/round080-original-lzo1x-independent-decoder-verify.py"
OBS_SHIM = "tests/runtime/native/fixtures/native-observation-owner-host-model.h"
OBS_BASE_SHIM = "tests/runtime/native/fixtures/native-observation-adapter-host-model.h"
STAGE_PATHS = ("src/kernel", PATCH92, PATCH94, PATCH96, SHIM, MODULE_SHIM, HELPER, HELPER80,
               OBS_SHIM, OBS_BASE_SHIM)
PINS = {
    DM: "f1922cc26caf7bfa097c1f561f8719744c3a4e75",
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    PATCH92: "62db468c14f23b59e7adaae65a11dcb9969f02b3",
    PATCH94: "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
    PATCH96: "6ee63e6515dd2f0337c49d1a868f39435b93119c",
    OBS_SHIM: "47042c1c9f388f29e2989492c15ef479573b1019",
    OBS_BASE_SHIM: "3dac25d2edb2d7475af3231c98af753f09e4063f",
    "src/kernel/native-observation-adapter.c": "f94371ff06ba8296e292ccec9e28dd230ded5bbd",
    "src/kernel/native-observation-adapter.h": "27f1140f4dcc510662fbb1f4519f7be4236e1b10",
    "src/kernel/native-observation-owner.c": "69bd5c018bf4cc502c14c1c3f1cc02c1959c1673",
    "src/kernel/native-observation-owner.h": "e266f0e0c2dec0d399cc863da329e44f38b0c536",
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
TARGET_POST = "aaff4d782323f9f17046cb2ba4fabcc0069e51e6"
FIXTURE_POST = "b5e6cfc88236d2ba713bafd3dd6570c07d10f6aa"
RECORDER_FIXTURE = "tests/runtime/native/fixtures/round098-scoped-recorder.c"
RECORDER_FIXTURE_POST = "8cc691fa72331881151061c80007a9a265823cb5"
MM_RUNNER = "tests/tools/round097-mm-producer-verify.py"
MM_RUNNER_PIN = "dad98ce49b64ce7bb3f6d48ba4a9395299a2da5e"
MUTANTS = (
    ("ignore_mm_scope_revocation", "revoked",
     "key->swap_type, key->codec, key->length, &route);",
     "key->swap_type, key->codec, key->length, &route) || true;"),
    ("ignore_producer_slot", "connected",
     "producer->slot != key->slot_offset ||",
     "(producer->slot != key->slot_offset && false) ||"),
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
        fragment(source, "OBSERVATION", "098"),
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
        fragment(source, "SCOPE", "098"),
        function(source, "static void swapz_round090_candidate_get("),
        function(source, "static bool swapz_round091_retain_candidate_locked("),
        function(source, "static bool swapz_round091_ordered_claim_permitted(void)\n{"),
        claim_context,
        function(source, "static int swapz_round091_claim_reserved("),
        fragment(source, "SCOPE", "097"),
        fragment(source, "TRANSACTION", "098"),
        function(source, "static bool swapz_round091_process_candidate("),
        fragment(source, "TARGET_RELEASE", "096"),
    ]
    return record, "\n".join(fragments)


def source_checks(source):
    require("swapz_round091_ordered_claim_permitted(void)\n{\n\treturn false;\n}" in source,
            "legacy live gate changed")
    require("ctx->original_trial = is_nullb && !ctx->physical_backing;" in source, "physical guard")
    require(source.count("swapz_scope_install_locked(") == 1, "unexpected native controller caller")
    candidate = function(source, "static void swapz_round090_candidate_get(")
    require(candidate.index("swapz_mm_candidate_get(origin, ref)") <
            candidate.index("swapz_mm_candidate_observation(origin, ref, &producer)") <
            candidate.index("swapz_scope_observation_bind(entry, &producer, &view->key)"),
            "same origin/ref observation")
    claim = function(source, "static int swapz_round091_claim_reserved(")
    require(claim.index("swapz_scope_key_matches_locked(") <
            claim.index("swapz_ticket_claim_under_queue_lock("), "scope before claim")
    read = function(source, "static int swapz_read(struct swapz_dm *ctx, struct bio *bio)\n{")
    require(read.index("swapz_round097_read_original_pinned(") <
            read.index("swapz_copy_bio_accounted(") <
            read.index("swapz_shared_original_put(&ctx->authority, original_pin)"), "pin through copy")
    require(source.count("list_add_tail(&entry->list, &ctx->incoming);") == 1, "canonical FIFO")


def stage_producer(workspace, linux):
    raw = git("show", FREEZE + ":" + MM_RUNNER)
    require(blob(raw) == MM_RUNNER_PIN, "producer staging runner pin")
    namespace = {"__file__": str(ROOT / MM_RUNNER), "__name__": "frozen_mm_stage"}
    exec(compile(raw, str(ROOT / MM_RUNNER), "exec"), namespace)
    # Frozen R097 producer stage reads three overlays from ROOT; supply exact
    # freeze copies rather than any concurrently changed worktree path.
    pinned = workspace / "producer-inputs"
    for path in (namespace["PATCH"], namespace["RETRY"], namespace["PRODUCER"]):
        target = pinned / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git("show", FREEZE + ":" + path))
    namespace["ROOT"] = pinned
    directory = workspace / "producer"
    directory.mkdir()
    report = {}
    source = namespace["stage"](directory, linux, report)
    require(report.get("stage") == "PASS", "actual producer raw stage")
    header = (directory / namespace["CARRIER"]).read_text()
    obs = (directory / namespace["OBSERVATION"]).read_text()
    types = obs[obs.index("#define SWAPZ_OBSERVATION_DIGEST_BYTES"):
                obs.index("struct swapz_observation_recorder {")]
    for name in ("swapz_mm_route", "swapz_mm_trial_scope", "swapz_mm_carrier"):
        match = re.search(r"(?ms)^struct " + name + r" \\{.*?^\\};", header)
        require(match is not None, "carrier type " + name)
        types += match[0] + "\n"
    actual = "\n".join(namespace["function"](source, name) for name in
                       ("swapz_mm_scope_matches", "swapz_mm_candidate_get", "swapz_mm_candidate_observation"))
    return types, actual


def compile_and_run(compiler, stage, linux, work, evidence, prior, helpers, record, fragments, mm_types, mm_actual):
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
    (work / "r098-types.h").write_text(mm_types)
    (work / "r098-mm.h").write_text(mm_actual)
    obs_include = work / "observation-include"
    (obs_include / "linux").mkdir(parents=True)
    (obs_include / "crypto").mkdir()
    for header in ("types", "atomic", "rcupdate", "build_bug", "limits", "string",
                   "export", "kernel", "mutex", "slab", "vmalloc"):
        (obs_include / "linux" / (header + ".h")).write_text('#include "native-observation-owner-host-model.h"\n')
    (obs_include / "crypto/sha2.h").write_text('#include "native-observation-owner-host-model.h"\n')
    pin(ROOT / RECORDER_FIXTURE, RECORDER_FIXTURE_POST)
    build_source = git("rev-parse", "HEAD").decode().strip()
    obs_flags = [standard, *flags, "-pthread", "-D_POSIX_C_SOURCE=200809L",
                 "-DSWAPZ_NATIVE_OBSERVATION_ADAPTER", "-DSWAPZ_TRIAL_OBSERVATION",
                 '-DSWAPZ_OBSERVATION_BUILD_SOURCE="' + build_source + '"',
                 "-I", str(obs_include), "-I", str(kernel), "-I", str((stage / OBS_SHIM).parent)]
    for path in (kernel / "native-observation-adapter.c", kernel / "native-observation-owner.c",
                 ROOT / RECORDER_FIXTURE):
        obj = work / ("recorder-" + path.stem + ".o")
        execute([compiler, *obs_flags, "-c", str(path), "-o", str(obj)], evidence,
                compiler + " actual recorder " + path.name)
        objects.append(obj)
    fixture = work / "composed.c"
    fixture.write_bytes((ROOT / FIXTURE).read_bytes())
    pin(fixture, FIXTURE_POST)
    result = {"standard": standard, "mutants": [], "scenarios": {}}
    for name, mode, old, new in (("baseline", "connected", "", ""), *MUTANTS):
        code = fragments
        if old:
            require(code.count(old) == 1, "mutation anchor " + name)
            code = code.replace(old, new, 1)
        (work / "target-fragments.h").write_text(code)
        binary = work / "scoped-host"
        execute([compiler, *host, "-Wconversion", "-Wshadow", str(fixture),
                 *(str(obj) for obj in objects), "-lcrypto", "-no-pie", "-o", str(binary)],
                evidence, compiler + " compile fixture " + name)
        for scenario in ((mode,) if old else ("connected", "revoked")):
            run = execute([str(binary), scenario], evidence, compiler + " run " + name + "/" + scenario,
                          expected=77 if old else 0, mutant=bool(old))
            if old:
                require(not run.stdout and re.fullmatch(r"R098_SEMANTIC_FAIL line=\\d+ [^\\n]+\\n", run.stderr),
                        "not a semantic kill " + name)
                result["mutants"].append({"name": name, "witness": run.stderr.strip()})
            else:
                match = re.fullmatch(r"PASS R098_SCOPED mode=(\\w+) checks=(\\d+) claims=(\\d+) fallbacks=(\\d+) events=(\\d+) loss=(\\d+) AUTH0\\n", run.stdout)
                require(match and match[1] == scenario, "actual scenario counts")
                result["scenarios"][scenario] = dict(zip(("checks", "claims", "fallbacks", "events", "loss"),
                                                          map(int, match.groups()[1:]), strict=True))
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
    report = {"round": "098", "agent": 3, "tested_commit": git("rev-parse", "HEAD").decode().strip(),
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
        with tempfile.TemporaryDirectory(prefix="r098-scoped-") as directory:
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
            mm_types, mm_actual = stage_producer(workspace, linux)
            report["producer_stage"] = "PASS_EXACT_POSTIMAGES"
            for compiler in ("gcc", "clang"):
                work = workspace / compiler
                work.mkdir()
                report["compilers"][compiler] = compile_and_run(
                    compiler, stage, linux, work, evidence, prior, helpers, record, fragments, mm_types, mm_actual)
        report["conclusion"] = "PASS_SCOPED_TARGET_ACTUAL_ACCESSOR_RECORDER_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        report["first_error"] = str(error).split("\n", 1)[0][:320]
        print("R098_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
