#!/usr/bin/env python3
"""Round079 Agent5 exact original Linux source-linked preerase owner HOST test.

Reads unchanged pinned pristine Linux mm/zswap.c + mm/zsmalloc.c, verifies
their original Git blob identities and source order, then emits FOUR exact
branch predicates extracted from the original source into a generated header.
An independent SINGLE-THREADED C owner model compiles and EXECUTES under
GCC/Clang -std=c2x -Werror ASan+UBSan. Every one of 20 unique fail-closed
semantic mutants MUST compile and execute, failing a deterministic C runtime
assertion, NOT C compilation or an ASan/UBSan crash. No genuine Linux code is
executed here; original locked STORED swapcache remains UNPROVEN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round079-original-zswap-preerase-source-copy.c"
ORIGINAL_PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/zsmalloc.c": "7ef80e0da6267661cea4d48a4a615444724782e7",
}
PRODUCT_BLOB = "e89d316b9cf49f82df0b77648c1be1731607987d"
MODEL_CASES = 4
MUTANT_MACROS = (
    "GUARD_XARRAY", "GUARD_SLOT", "GUARD_GENERATION",
    "GUARD_FOLIO_LOCK", "GUARD_POOL_REFERENCE", "GUARD_HANDLE",
    "GUARD_PREERASE", "GUARD_ZERO_LENGTH", "GUARD_ABOVE_PAGE",
    "GUARD_IMPORT_LIMIT", "GUARD_RAW_FALLBACK", "GUARD_CODEC",
    "GUARD_DECODER_GENERATION", "GUARD_SG_END", "GUARD_EXACT_COPY",
    "GUARD_RETIRED_READER", "GUARD_LOWER_DURABILITY", "GUARD_ACK_ONCE",
    "GUARD_PUBLISH_ONCE", "GUARD_SHORT_CAPACITY",
)
EXPECTED_LINE = (
    "PASS round079 original_MM_decisions_extracted=4"
    " source_model_cases=4 original_zsmalloc_SG_lock=MODEL"
    " original_codec_tag=VOLATILE LZ4_LZO1X=IDENTITY_ONLY"
    " copied_exact_bytes=3568 original_length_3569_to_4095=BLOCKED"
    " ordinary_RAW_4096=FULL_UNCOMPRESSED"
    " modeled_FUA_ACK=ONLY original_KUnit=NOT_RUN AUTH0 PHASE_A=BLOCKED"
)


class QualificationFailure(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationFailure(message)


def git_blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def bounded_failure(message: str) -> str:
    return re.sub(r"(?:/[^:\s]+)+/", "source/", message)[:290]


def isolated_function(source: str, signature: str, after: str) -> str:
    require(source.count(signature) == 1, "original-signature-drift:" + signature)
    part = source.split(signature, 1)[1]
    require(after in part, "original-function-end-drift:" + signature)
    return part.split(after, 1)[0]


def exact_expression(function: str, expression: str, label: str) -> str:
    pattern = r"\bif\s*\(\s*" + re.escape(expression) + r"\s*\)"
    require(len(re.findall(pattern, function)) == 1,
            "original-branch-source-drift:" + label)
    return expression


def source_verified_header(linux: Path) -> tuple[str, dict[str, str]]:
    revision = subprocess.run(
        ["git", "-C", str(linux), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=30, check=False)
    require(revision.returncode == 0 and
            revision.stdout.strip() == ORIGINAL_PIN,
            "original-Linux-revision-not-pinned")
    source = {}
    for path, known_blob in ORIGINAL_BLOBS.items():
        source_path = linux / path
        require(source_path.is_file(), "original-source-file-missing:" + path)
        file_bytes = source_path.read_bytes()
        require(git_blob(file_bytes) == known_blob,
                "original-git-blob-mismatch:" + path)
        # A checkout worktree must equal its pristine pinned Git HEAD blob.
        original = subprocess.run(
            ["git", "-C", str(linux), "show", "HEAD:" + path],
            capture_output=True, timeout=60, check=False)
        require(original.returncode == 0 and original.stdout == file_bytes,
                "original-source-working-tree-not-pristine:" + path)
        source[path] = file_bytes.decode("utf-8")
    product = (ROOT / "src/kernel/codec.h").read_bytes()
    require(git_blob(product) == PRODUCT_BLOB,
            "actual-product-codec-blob-drift")
    require(product.count(b"#define SWAPZ_BLOCK_BYTES 4096U") == 1 and
            product.count(b"#define SWAPZ_MAX_COMPRESSED 3568U") == 1,
            "actual-product-import-bound-drift")
    zswap = source["mm/zswap.c"]
    zsmalloc = source["mm/zsmalloc.c"]
    compress = isolated_function(
        zswap, "static bool zswap_compress(", "static bool zswap_decompress(")
    decompress = isolated_function(
        zswap, "static bool zswap_decompress(", "static int zswap_writeback_entry(")
    writeback = isolated_function(
        zswap, "static int zswap_writeback_entry(", "static enum lru_status shrink_memcg_cb(")
    require(zswap.count("static struct zswap_pool *zswap_entry_pool(") == 1,
            "original-pool-source-drift")
    pool_source = isolated_function(
        zswap, "static struct zswap_pool *zswap_entry_pool(",
        "static struct xarray *zswap_trees")
    require("return xa_load(&zswap_pools, entry->pool_idx);" in pool_source,
            "original-pool-index-XArray-drift")
    from_original = {
        "R079_ORIGINAL_XARRAY_MISMATCH": exact_expression(
            writeback, "entry != xa_load(tree, offset)", "writeback-XArray"),
        "R079_ORIGINAL_UNCOMPRESSED": exact_expression(
            decompress, "entry->length == PAGE_SIZE", "decode-raw-original"),
        "R079_ORIGINAL_BAD_COMPRESS": exact_expression(
            compress, "comp_ret || !dlen || dlen >= PAGE_SIZE",
            "original-compressor-raw-fallback"),
        "R079_ORIGINAL_POOL_MISSING": "!pool",
    }
    require(decompress.count("if (WARN_ON_ONCE(!pool))") == 1,
            "original-pool-null-predicate-drift")
    events = (
        "si = get_swap_device(swpentry);",
        "folio = __swap_cache_alloc_folio(",
        "tree = swap_zswap_tree(swpentry);",
        "if (entry != xa_load(tree, offset))",
        "if (!zswap_decompress(entry, folio))",
        "xa_erase(tree, offset);",
        "zswap_entry_free(entry);",
        "__swap_writeout(&ctx, folio);",
        "swap_write_submit(&ctx);",
    )
    indices = [writeback.find(item) for item in events]
    require(all(index >= 0 for index in indices) and
            indices == sorted(indices) and len(indices) == len(set(indices)),
            "original-locked-folio-XArray-erase-free-writeout-order")
    require("folio is locked, and the swapcache is now secured" in writeback,
            "original-source-swapcache-folio-lifetime-comment-drift")
    decoder_events = (
        "struct zswap_pool *pool = zswap_entry_pool(entry);",
        "mutex_lock(&acomp_ctx->mutex);",
        "zs_obj_read_sg_begin(pool->zs_pool, entry->handle, input, entry->length);",
        "if (entry->length == PAGE_SIZE)",
        "zs_obj_read_sg_end(pool->zs_pool, entry->handle);",
        "mutex_unlock(&acomp_ctx->mutex);",
    )
    decoder_indices = [decompress.find(item) for item in decoder_events]
    require(all(index >= 0 for index in decoder_indices) and
            decoder_indices == sorted(decoder_indices) and
            len(decoder_indices) == len(set(decoder_indices)),
            "original-decoder-pool-SG-lock-order")
    require(zswap.count("percpu_ref_get(&pool->ref);") >= 1 and
            zswap.count("percpu_ref_put(&pool->ref);") >= 1 and
            "xa_erase_bh(&zswap_pools, pool->idx);" in zswap and
            "queue_rcu_work(system_percpu_wq, &pool->release_rwork);" in zswap,
            "original-pool-ref-RCU-teardown-source-drift")
    free = isolated_function(
        zswap, "static void zswap_entry_free(", "static int zswap_cpu_comp_prepare(")
    require("zs_free(pool->zs_pool, entry->handle);" in free and
            "zswap_pool_put(pool);" in free,
            "original-entry-handle-pool-free-order")
    sg_begin = isolated_function(
        zsmalloc, "void zs_obj_read_sg_begin(", "EXPORT_SYMBOL_GPL(zs_obj_read_sg_begin);")
    sg_end = isolated_function(
        zsmalloc, "void zs_obj_read_sg_end(", "EXPORT_SYMBOL_GPL(zs_obj_read_sg_end);")
    require("zspage_read_lock(zspage);" in sg_begin and
            "zspage_read_unlock(zspage);" in sg_end and
            "sg_init_table(sg, 2);" in sg_begin,
            "original-zsmalloc-SG-lock-two-page-drift")
    free_handle = isolated_function(
        zsmalloc, "void zs_free(", "EXPORT_SYMBOL_GPL(zs_free);")
    require("cache_free_handle(handle);" in free_handle,
            "original-zsmalloc-handle-release-source-drift")
    header = (
        "/* GENERATED from git-blob-verified original mm/zswap.c only. */\n"
        "#ifndef ROUND079_ORIGINAL_SOURCE_PREDICATES_H\n"
        "#define ROUND079_ORIGINAL_SOURCE_PREDICATES_H\n" +
        "".join("#define " + key + " (" + value + ")\n"
                for key, value in from_original.items()) +
        "#endif\n"
    )
    return header, {
        "original_linux_pin": ORIGINAL_PIN,
        "mm_zswap_git_blob": ORIGINAL_BLOBS["mm/zswap.c"],
        "mm_zsmalloc_git_blob": ORIGINAL_BLOBS["mm/zsmalloc.c"],
        "real_product_codec_blob": PRODUCT_BLOB,
        "original_predicates_compiled": 4,
        "writeback_order_seams_verified": len(events),
        "decoder_order_seams_verified": len(decoder_events),
        "live_original_mm_executed": False,
    }


def compile_model(compiler: str, content: str, directory: Path,
                  name: str) -> Path:
    available = shutil.which(compiler)
    require(available is not None, "strict-C-compiler-missing:" + compiler)
    source_path = directory / "round079-original-source-model.c"
    executable = directory / (compiler + "-" + name)
    source_path.write_text(content)
    flags = (
        "-std=c2x", "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
        "-Wshadow", "-Wpedantic", "-Wstrict-prototypes", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
    )
    result = subprocess.run(
        [available, *flags, str(source_path), "-o", str(executable)],
        cwd=ROOT, capture_output=True, text=True, timeout=75, check=False)
    if result.returncode:
        first = next((line for line in result.stderr.splitlines()
                      if "error:" in line), result.stderr[:250])
        raise QualificationFailure(
            "strict-C-compile:" + compiler + ":" + name + ":" +
            bounded_failure(first))
    return executable


def run_model(executable: Path, compiler: str, name: str,
              mutant: bool) -> None:
    environment = dict(
        os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run(
        [str(executable)], cwd=ROOT, capture_output=True, text=True,
        timeout=35, env=environment, check=False)
    require(result.returncode >= 0 and
            "AddressSanitizer" not in result.stderr and
            "runtime error:" not in result.stderr and
            "UndefinedBehaviorSanitizer" not in result.stderr,
            "source-C-sanitizer-or-signal:" + compiler + ":" + name +
            ":exit=" + str(result.returncode))
    if mutant:
        require(result.returncode == 3 and
                "ROUND079_FIRST_ERROR case=" in result.stderr and
                not result.stdout,
                "source-C-semantic-mutant-not-killed:" + compiler + ":" +
                name + ":exit=" + str(result.returncode))
    else:
        require(result.returncode == 0 and
                result.stdout.strip() == EXPECTED_LINE and
                not result.stderr,
                "source-C-baseline-failed:" + compiler + ":" +
                bounded_failure(result.stderr[:240]) + ":exit=" +
                str(result.returncode))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    header, provenance = source_verified_header(args.linux_root)
    fixture = FIXTURE.read_text()
    require(fixture.count("#include \"round079-original-source-predicates.h\"") == 1,
            "real-original-source-predicate-include-missing")
    for macro in MUTANT_MACROS:
        require(fixture.count("#define " + macro + " 1") == 1,
                "unique-independently-compiled-C-mutant-anchor:" + macro)
    report: dict[str, object] = {
        "round": "079", "agent": 5, "kind": "pinned-original-zswap-source-linked-HOST-MODEL",
        "status": "PASS", "source": provenance,
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED", "direct_handoff": "DISABLED",
        "forced_raw_bypass": "DISABLED", "import_active": False,
        "actual_stored_swapcache": False, "actual_original_linux_execution": False,
        "actual_physical_fua": False, "actual_upper_ack": False,
        "original_native_kunit": "NOT_REQUESTED",
        "compilers": {},
    }
    with tempfile.TemporaryDirectory(prefix="swapz-round079-original-preerase-") as temporary:
        working = Path(temporary)
        for compiler in ("gcc", "clang"):
            compiler_directory = working / compiler
            compiler_directory.mkdir()
            (compiler_directory / "round079-original-source-predicates.h").write_text(header)
            baseline = compile_model(compiler, fixture, compiler_directory, "baseline")
            run_model(baseline, compiler, "baseline", False)
            mutant_count = 0
            for macro in MUTANT_MACROS:
                target = "#define " + macro + " 1"
                mutant = fixture.replace(target, "#define " + macro + " 0", 1)
                executable = compile_model(compiler, mutant, compiler_directory,
                                           macro.lower())
                run_model(executable, compiler, macro.lower(), True)
                mutant_count += 1
            require(mutant_count == 20,
                    "missing-compiled-executed-semantic-C-mutant")
            report["compilers"][compiler] = {
                "status": "PASS", "baseline_cases": MODEL_CASES,
                "compiled_semantic_mutants": mutant_count,
                "executed_semantic_mutants": mutant_count,
                "killed_by_runtime_assertion": mutant_count,
                "sanitizers": ["address", "undefined"],
            }
            print("PASS " + compiler +
                  " original-source-linked-real-predicates=4 "
                  "host-model-baseline-cases=4 "
                  "independently_compiled_executed_C_semantic_mutants=20 "
                  "ASAN_UBSAN=YES original_native_KUnit=NOT_RUN AUTH0",
                  flush=True)
    if args.json is not None:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS ROUND079_AGENT5_EXACT_ORIGINAL_ZSWAP_ZSMALLOC_SOURCE "
          "pristine_git_blobs=2 real_product_bound=3568 "
          "host_model_cases=8 GCC_Clang_semantic_mutants=40 "
          "true_live_MM_STORED=UNPROVEN original_native_KUnit=NOT_RUN "
          "SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except (QualificationFailure, OSError, ValueError,
            subprocess.TimeoutExpired) as error:
        print("ROUND079_AGENT5_FIRST_ERROR " +
              bounded_failure(str(error)), file=sys.stderr)
        sys.exit(1)
