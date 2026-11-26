#!/usr/bin/env python3
"""Actual extracted ordered transaction and typed READ; frozen product + Linux.
Synthetic selected provenance, RAM lower callbacks; never native DM or AUTH.
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
BASE = "2499405464110e6a97f054db5527de54b8aafb3a"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
SHARED_FIXTURE = "tests/runtime/native/fixtures/round089-shared-original-storage.c"
ORDERED_FIXTURE = "tests/runtime/native/fixtures/round091-selected-dm-ordered.c"
OLD_BASE = "e8a3f08000f81dcc3b1bda74b407b9e523ed3bab"
STAGE_PATHS = ("src/kernel", "tests/tools/round085-original-decode-verify.py",
               "tests/tools/round080-original-lzo1x-independent-decoder-verify.py",
               SHARED_FIXTURE)
PINS = {
    "src/kernel/zswap-original-ticket.h": "0630f9e4fad26458ed0778ca6ae040150e28f078",
    "src/kernel/zswap-original-ticket.c": "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    "src/kernel/zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "src/kernel/zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "src/kernel/zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "src/kernel/zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "src/kernel/authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "src/kernel/authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "src/kernel/engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "tests/runtime/native/fixtures/round089-shared-original-storage.c": "95cee696fe99b3438f387ff1bf45cb4634f70fab",
}
MUTANTS = (
    ("ignore_claim_refusal", "if (try_claim(context, credit)) {",
     "if (try_claim(context, credit) == 12345) {"),
    ("leak_canceled_credit", "*error = swapz_shared_storage_cancel_reserved(storage, credit);",
     "*error = credit ? 0 : -EINVAL;"),
    ("fallback_after_commit_failure",
     "*error = swapz_shared_storage_commit_reserved(storage, credit);\n\treturn true;",
     "*error = swapz_shared_storage_commit_reserved(storage, credit);\n\treturn *error == 0;"),
    ("leak_read_pin", "release_error = swapz_shared_original_put(authority, pin);",
     "release_error = pin ? 0 : -EINVAL;"),
)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "--no-replace-objects", *args], cwd=ROOT)


def verify_stage(stage):
    # Every archived file, including transitive quoted includes and helpers.
    entries = git("ls-tree", "-r", "-z", BASE, "--", *STAGE_PATHS).split(b"\0")
    expected = {}
    for entry in filter(None, entries):
        metadata, name = entry.split(b"\t", 1)
        mode, kind, digest = metadata.decode().split()
        require(kind == "blob" and mode in ("100644", "100755"), "nonregular staged input")
        expected[name.decode()] = digest
    actual = {str(path.relative_to(stage)) for path in stage.rglob("*") if path.is_file()}
    require(actual == set(expected), "staged file inventory")
    for path, digest in expected.items():
        require(git_blob((stage / path).read_bytes()) == digest, "staged blob " + path)
    return len(expected)


def verify_fixture(path, expected):
    require(git_blob(path.read_bytes()) == expected, "mixed-version fixture rejected")


def isolate_fixture(stage, work):
    # Compile from scratch, not the current source-relative include directory.
    fixture = work / "ordered-fixture.c"
    current = git("show", "HEAD:" + ORDERED_FIXTURE)
    require(current == (ROOT / ORDERED_FIXTURE).read_bytes(), "current ordered fixture drift")
    fixture.write_bytes(current)
    shared = work / "frozen-round089-shared-original-storage.c"
    shared.write_bytes((stage / SHARED_FIXTURE).read_bytes())
    verify_fixture(shared, PINS[SHARED_FIXTURE])
    return fixture, shared


def fragment(source, name):
    begin, end = f"/* ROUND091_{name}_BEGIN */", f"/* ROUND091_{name}_END */"
    require(source.count(begin) == source.count(end) == 1, "fragment " + name)
    return source.split(begin, 1)[1].split(end, 1)[0]


def static_checks(source, patch):
    anchor = "list_add_tail(&entry->list, &ctx->incoming);"
    require(source.count(anchor) == 1, "canonical FIFO")
    mapping = source.split("static int swapz_map(struct dm_target *ti, struct bio *bio)", 1)[1].split("static void swapz_drain(", 1)[0]
    require(mapping.index("swapz_round090_candidate_get(ti, bio,") <
            mapping.index("spin_lock_irqsave(&ctx->queue_lock, flags)") <
            mapping.index("swapz_round091_retain_candidate_locked(ctx, entry,") <
            mapping.index(anchor) < mapping.index("if (original_retained)"),
            "retention before canonical FIFO")
    require("swapz_ticket_claim_under_queue_lock" not in mapping and
            "swapz_shared_storage_reserve" not in mapping, "map claims/reserves")
    retain = fragment(source, "RETAIN")
    require("swapz_ticket_claim" not in retain and "entry->original_candidate = *ref;" in retain,
            "retention is unclaimed")
    require(source.count("swapz_process(ctx, entry->bio)") == 1, "ordinary process bypass")
    require(source.index("wait_for_completion(&entry->preparation_snapshot_ready)") <
            source.index("swapz_process(ctx, entry->bio)"), "ordinary preparation wait")
    require("swapz_round091_ordered_claim_permitted(void)\n{\n\treturn false;\n}" in source,
            "frozen live claim guard")
    claim = source.split("static int swapz_round091_claim_reserved(", 1)[1].split("static bool swapz_round091_process_candidate(", 1)[0]
    require(claim.count("swapz_ticket_claim_under_queue_lock(") == 1 and
            claim.index("spin_lock_irqsave") < claim.index("dm_swapz_round091_accepted_clone_matches") <
            claim.index("swapz_ticket_claim_under_queue_lock") < claim.index("entry->original_claimed = true") <
            claim.index("spin_unlock_irqrestore") and "list_add" not in claim and
            "swapz_shared_storage_" not in claim, "ordered claim lock gate")
    require("map_scope && (!tio->len_ptr || *tio->len_ptr != 8U)" in patch and
            "tio->io->orig_bio, false)" in patch, "accepted clone transient length guard")
    require("swapz_shared_original_segment_pinned(a, segment)" in source and
            "swapz_shared_storage_relocate(ctx->original_storage" in source, "GC and TRIM guard")
    read = source.split("static int swapz_read(struct swapz_dm *ctx, struct bio *bio)", 1)[1].split("static void swapz_read_slot_prepare(", 1)[0]
    # R096 transfers the authoritative pin to the actual READ caller.
    # Keep the original typed-before-cache assertion and prove the new
    # release point is after the final upper BIO copy.
    typed_call = "swapz_round096_read_original_pinned("
    release = "swapz_shared_original_put(&ctx->authority, original_pin)"
    require(typed_call in read and release in read,
            "typed READ retained pin call/release")
    require(read.index("SWAPZ_MAP_ORIGINAL") < read.index(typed_call) <
            read.index("swapz_engine_read_page(") < read.index("swapz_copy_bio_accounted(") <
            read.index(release),
            "typed READ precedes ordinary cache and retains pin through upper copy")
    require("bi_bvec_done" not in source, "obsolete bvec member")


def run_command(args, evidence, label, expected=0):
    env = {key: value for key, value in os.environ.items() if key not in
           ("CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "OBJC_INCLUDE_PATH")}
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180,
                            env=env | {"ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                       "UBSAN_OPTIONS": "halt_on_error=1"})
    if result.returncode != expected:
        (evidence / "first-child-error.log").write_text((result.stderr + result.stdout)[:12000])
        raise RuntimeError(f"{label}: exit {result.returncode}, expected {expected}")
    return result


def run_compiler(compiler, stage, linux, work, prior, helpers, fragments, evidence):
    standard = helpers["compiler_standard"](compiler)
    shim = prior["build_shim"](linux, work, helpers)
    staged = work / "staged"
    staged.mkdir()
    (staged / "lz4_compress.c").write_bytes(
        prior["staged_bytes"]((linux / prior["LZ4_SOURCE"]).read_bytes(), LINUX, ""))
    (staged / "lz4_decompress.c").write_bytes(
        prior["staged_decoder_bytes"]((linux / prior["LZ4_DECODER_SOURCE"]).read_bytes(), LINUX, ""))
    (staged / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    objects = []
    for part in ("lib/lzo/lzo1x_compress_safe.c", "lib/lzo/lzo1x_decompress_safe.c",
                 "lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c"):
        path = staged / Path(part).name if part.startswith("lib/lz4") else linux / part
        obj = work / ("original-" + path.stem + ".o")
        helpers["compile_object"](compiler, "-std=gnu11", path, obj,
                                  ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
        objects.append(obj)
    kernel = stage / "src/kernel"
    adapter = work / "original-compressor.c"
    adapter.write_text(prior["COMPRESS_ADAPTER"])
    flags = ["-I", str(shim), "-I", str(kernel), "-I", str(work),
             "-I", str(stage / "tests/runtime/native/fixtures"),
             "-DSWAPZ_ORIGINAL_TICKET_TEST=1", "-DSWAPZ_ORIGINAL_STORAGE_TEST=1",
             "-DSWAPZ_ORIGINAL_EXTENT_TEST=1", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST=1",
             "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST=1", "-DSWAPZ_SHARED_ORIGINAL_TEST=1"]
    host_flags = [standard, "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                  "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-fno-omit-frame-pointer", "-fno-pie",
                  "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
                  "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
                  "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
                  "-D_POSIX_C_SOURCE=200809L", "-D__maybe_unused=__attribute__((unused))",
                  "-include", "stddef.h"]
    for name in ("authority.c", "engine.c", "codec.c", "zswap-original-storage.c",
                 "zswap-original-extent.c", "zswap-original-ticket.c",
                 "zswap-import-decoder-owner.c", "zswap-original-decode.c",
                 "zswap-original-decoder-bridge.c"):
        path = kernel / name
        obj = work / ("product-" + path.stem + ".o")
        run_command([compiler, *host_flags, *flags, "-c", str(path), "-o", str(obj)],
                    evidence, "compile " + name)
        objects.append(obj)
    obj = work / "original-compressor.o"
    run_command([compiler, *host_flags, *flags, "-c", str(adapter), "-o", str(obj)],
                evidence, "compile original adapter")
    objects.append(obj)
    fixture, shared = isolate_fixture(stage, work)
    result = {}
    for name, old, new in (("baseline", "", ""), *MUTANTS):
        code = fragments
        if old:
            require(code.count(old) == 1, "mutation anchor " + name)
            code = code.replace(old, new, 1)
        (work / "ordered-fragments.h").write_text(code)
        program = work / "ordered-host"
        verify_fixture(shared, PINS[SHARED_FIXTURE])
        run_command([compiler, *host_flags, *flags, str(fixture),
                     *(str(item) for item in objects), "-pthread", "-lcrypto", "-no-pie",
                     "-o", str(program)], evidence, "fixture " + name)
        execution = run_command([str(program)], evidence, "run " + name, 77 if old else 0)
        if old:
            require(execution.stderr.startswith("SEMANTIC_FAIL line=") and not execution.stdout,
                    "not a semantic kill " + name)
            result["mutants"].append(name)
        else:
            match = re.fullmatch(r"PASS ROUND091_ORDERED checks=(\d+) claims=5 refusals=3 typed_reads=2 terminal_owners=5 AUTH0\n",
                                 execution.stdout)
            require(match and not execution.stderr, "baseline counts or sanitizer")
            result = {"checks": int(match.group(1)), "claims": 5, "refusals": 3,
                      "typed_reads": 2, "modeled_terminal_owners": 5, "mutants": []}
    print(Path(compiler).name, json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    evidence = args.evidence_dir.resolve()
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = {"round": "092", "agent": 3, "tested_commit": git("rev-parse", "HEAD").decode().strip(),
              "frozen_product": BASE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
              "physical_io": False, "native_dm": "NOT_RUN", "compilers": {},
              "first_error": None, "conclusion": "FAIL"}
    try:
        source = (ROOT / "src/kernel/dm-target.c").read_text()
        patch = (ROOT / "tests/tools/round088-original-dm-selected-clone.patch").read_text()
        static_checks(source, patch)
        fragments = fragment(source, "TRANSACTION") + fragment(source, "TYPED_READ")
        report["fragment_sha256"] = hashlib.sha256(fragments.encode()).hexdigest()
        linux = args.linux_root.resolve()
        require(subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"]).decode().strip() ==
                LINUX, "original Linux pin")
        with tempfile.TemporaryDirectory(prefix="round091-ordered-") as temp:
            workspace = Path(temp)
            stage = workspace / "frozen"
            stage.mkdir()
            archive = git("archive", BASE, *STAGE_PATHS)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(stage, filter="data")
            report["frozen_inventory_count"] = verify_stage(stage)
            mixed = workspace / "mixed-version-fixture.c"
            mixed.write_bytes(git("show", OLD_BASE + ":" + SHARED_FIXTURE))
            try:
                verify_fixture(mixed, PINS[SHARED_FIXTURE])
            except RuntimeError as error:
                require(str(error) == "mixed-version fixture rejected", "wrong negative cause")
            else:
                raise RuntimeError("mixed-version fixture was accepted")
            report["mixed_version_negative"] = "PASS"
            for path, pin in PINS.items():
                require(git_blob((stage / path).read_bytes()) == pin, "frozen pin " + path)
            prior = runpy.run_path(str(stage / "tests/tools/round085-original-decode-verify.py"))
            require(prior["PIN"] == LINUX and
                    prior["LZ4_POSTIMAGE"] == "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
                    prior["LZ4_DECODER_POSTIMAGE"] == "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
                    "frozen isolated codec pins")
            helpers = prior["verify_inputs"](linux)
            for compiler in ("gcc", "clang"):
                work = workspace / compiler
                work.mkdir()
                report["compilers"][compiler] = run_compiler(
                    compiler, stage, linux, work, prior, helpers, fragments, evidence)
        report["conclusion"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, AssertionError, ValueError) as error:
        report["first_error"] = str(error).split("\n", 1)[0][:220]
        print("ROUND091_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
