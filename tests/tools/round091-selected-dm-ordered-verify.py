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
BASE = "e8a3f08000f81dcc3b1bda74b407b9e523ed3bab"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINS = {
    "src/kernel/zswap-original-ticket.h": "2f850b53708c8142ee95d330192c9db1f9ae9418",
    "src/kernel/zswap-original-ticket.c": "66df826d86dde1bbd5e1967daa0e62517b58ac8d",
    "src/kernel/zswap-original-storage.h": "0da04b61921e3dbc0544cb9c9c8168513628997b",
    "src/kernel/zswap-original-storage.c": "d4feaca4d114cfdb1877df65e68e8d6b52859126",
    "src/kernel/zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "src/kernel/zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "src/kernel/authority.h": "c320498ce530c0887bf498cc4d5b121765bb41f3",
    "src/kernel/authority.c": "73b3e2dc98c6a47315519d3ab650c3d3b0656de7",
    "src/kernel/engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "tests/runtime/native/fixtures/round089-shared-original-storage.c": "13ceb16b1e6cc68575c673aba273b534e593eb30",
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
    require(read.index("SWAPZ_MAP_ORIGINAL") < read.index("swapz_round091_read_original(") <
            read.index("swapz_engine_read_page(") < read.index("swapz_copy_bio_accounted("),
            "typed READ precedes ordinary cache and upper copy")
    require("bi_bvec_done" not in source, "obsolete bvec member")


def run_command(args, evidence, label, expected=0):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180,
                            env=os.environ | {"ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
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
                  "-D_POSIX_C_SOURCE=200809L", "-include", "stddef.h"]
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
    fixture = ROOT / "tests/runtime/native/fixtures/round091-selected-dm-ordered.c"
    result = {}
    for name, old, new in (("baseline", "", ""), *MUTANTS):
        code = fragments
        if old:
            require(code.count(old) == 1, "mutation anchor " + name)
            code = code.replace(old, new, 1)
        (work / "ordered-fragments.h").write_text(code)
        program = work / "ordered-host"
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
    report = {"round": "091", "agent": 3, "tested_commit": git("rev-parse", "HEAD").decode().strip(),
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
            archive = git("archive", BASE, "src/kernel", "tests/tools/round085-original-decode-verify.py",
                          "tests/tools/round080-original-lzo1x-independent-decoder-verify.py",
                          "tests/runtime/native/fixtures/round089-shared-original-storage.c")
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(stage, filter="data")
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
