#!/usr/bin/env python3
"""Round058: compile/execute dormant imported LZO1X/LZ4 read against original C.

ROOTLESS ONLY. These synthetic volatile authority fields do not own native
zswap STORED entries, accepted DM clone, pool/tfm/module refs or durable BIO.
No physical or loaded-kernel test and no product activation is performed.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL_PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
IMPORT_HEADER = ROOT / "src/kernel/zswap-import-codec.h"
PRODUCT_CODEC = ROOT / "src/kernel/codec.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round058-original-codec-read.c"
ORIGINAL_HOST_SHIM = ROOT / "tests/tools/round056-codec-profile-verify.py"

# Every hostile mutation changes actual imported-read C logic and must compile
# AND execute to a fixture CHECK, never just fail compiler or sanitizer startup.
SOURCE_MUTANTS = (
    ("original-lzo-dispatch",
     "if (original_lzo1x) {", "if (!original_lzo1x) {"),
    ("payload-crc-polarity",
     "swapz_crc32c_bytes(compressed_bytes, record->compressed_length) !=",
     "swapz_crc32c_bytes(compressed_bytes, record->compressed_length) =="),
    ("full-original-sha",
     "if (digest_difference || (independent_original_page &&",
     "if ((digest_difference && 0U) || (independent_original_page &&"),
    ("compressed-length-cap",
     "record->compressed_length > SWAPZ_MAX_COMPRESSED ||",
     "record->compressed_length > SWAPZ_BLOCK_BYTES ||"),
    ("dictionary-rejection",
     "record->dictionary_id != 0U || !record->stored_eviction ||",
     "record->dictionary_id == 0U || !record->stored_eviction ||"),
    ("one-upper-write-ack",
     "authority->upper_write_ack_count != 1U ||",
     "authority->upper_write_ack_count != 2U ||"),
    ("lzo-trailing-input",
     "if (result != LZO_E_OK ||",
     "if (result == -999 ||"),
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError(f"ROUND058_IMPORT_CODEC_FIRST_ERROR {reason}")


def run_checked(command: list[str], label: str, *,
                semantic_mutant: bool = False) -> str:
    process = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=120,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )
    sanitizer = any(fragment in process.stderr for fragment in (
        "AddressSanitizer", "UndefinedBehaviorSanitizer", "LeakSanitizer",
        "runtime error:",
    ))
    oracle_rejected = (process.returncode == 1 and
                       "ROUND058_IMPORT_CODEC_FIRST_ERROR line=" in process.stderr and
                       not sanitizer)
    success = (oracle_rejected if semantic_mutant
               else process.returncode == 0 and not process.stderr and not sanitizer)
    if not success:
        lines = (process.stdout + "\n" + process.stderr).splitlines()
        raise AssertionError(
            f"ROUND058_IMPORT_CODEC_FIRST_ERROR {label} "
            f"exit={process.returncode} semantic={oracle_rejected} "
            f"sanitizer={sanitizer}\n" + "\n".join(lines[-35:])
        )
    return process.stdout.strip()


def original_host_adapter():
    spec = importlib.util.spec_from_file_location(
        "round056_original_lzo_host_shim", ORIGINAL_HOST_SHIM)
    require(spec is not None and spec.loader is not None, "missing frozen host shim")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_original(linux: Path, host_adapter) -> None:
    require(run_checked(["git", "-C", str(linux), "rev-parse", "HEAD"],
                        "pinned Linux HEAD") == ORIGINAL_PIN, "wrong original Linux pin")
    require(not run_checked(["git", "-C", str(linux), "status", "--porcelain"],
                            "pinned Linux clean"), "dirty original checkout")
    for relative_path, expected_blob_sha in host_adapter.ORIGINAL_BLOBS.items():
        path = linux / relative_path
        actual_blob_sha = run_checked(
            ["git", "-C", str(linux), "hash-object", str(path)],
            f"original SHA {relative_path}")
        require(actual_blob_sha == expected_blob_sha,
                f"original blob drift {relative_path} {actual_blob_sha}")
    original_crypto = (linux / "crypto/lzo.c").read_text()
    for evidence in (
        'lzo1x_1_compress_safe(src, slen, dst, &tmp_len, ctx);',
        'lzo1x_decompress_safe(src, slen, dst, &tmp_len);',
        '.cra_driver_name = "lzo-scomp"',
    ):
        require(evidence in original_crypto, f"original crypto/lzo.c {evidence}")
    original_compressor = (linux / "lib/lzo/lzo1x_compress.c").read_text()
    original_decompressor = (linux / "lib/lzo/lzo1x_decompress_safe.c").read_text()
    require("COPY8(op, ii);" in original_compressor,
            "original compressor unaligned COPY8 ABI missing")
    require("LZO_E_INPUT_NOT_CONSUMED" in original_decompressor,
            "original decoder trailing-input return missing")


def build_header_variant(original_header: str, mutant_name: str,
                         before: str, after: str) -> str:
    function_start = original_header.find(
        "static inline int swapz_zswap_import_decode(")
    require(function_start >= 0, "missing actual dormant source decoder")
    prefix, function = (original_header[:function_start],
                        original_header[function_start:])
    require(function.count(before) == 1 and before != after,
            f"nonunique/nonsemantic changed source mutant {mutant_name}")
    return prefix + function.replace(before, after, 1)


def test_compiler(compiler: str, scratch: Path, linux: Path,
                  header: str, host_adapter) -> None:
    case_root = scratch / compiler
    case_root.mkdir(parents=True)
    common = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
              "-Werror", "-fsanitize=address,undefined",
              "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
              "-I", str(scratch / "host-shim"), "-I", str(linux / "lib/lzo"),
              "-I", str(ROOT / "src/kernel")]
    upstream = (
        linux / "lib/lzo/lzo1x_compress_safe.c",
        linux / "lib/lzo/lzo1x_decompress_safe.c",
    )
    shared_objects = []
    for component, path, project_warnings in (
        ("real-product-codec", PRODUCT_CODEC, ("-Wconversion", "-Wshadow")),
        ("pinned-original-lzo-compressor", upstream[0], ()),
        ("pinned-original-lzo-decompressor", upstream[1], ()),
    ):
        object_path = case_root / (component + ".o")
        run_checked([*common, *project_warnings, "-c", str(path),
                     "-o", str(object_path)],
                    f"{compiler}/compile/{component}")
        shared_objects.append(str(object_path))

    variants = [("baseline", header, False)]
    variants.extend((name, build_header_variant(header, name, before, after), True)
                    for name, before, after in SOURCE_MUTANTS)
    for variant_name, contents, hostile in variants:
        variant_root = case_root / variant_name
        variant_root.mkdir()
        (variant_root / IMPORT_HEADER.name).write_text(contents)
        object_path = variant_root / "import-read-test.o"
        binary_path = variant_root / "source-read"
        run_checked(
            [common[0], "-I", str(variant_root), *common.slice(1),
             "-Wconversion", "-Wshadow", "-c", str(FIXTURE),
             "-o", str(object_path)],
            f"{compiler}/{variant_name}/compile/imported-source-read")
        run_checked(
            [compiler, str(object_path), *shared_objects,
             "-fsanitize=address,undefined", "-llz4", "-lcrypto",
             "-o", str(binary_path)],
            f"{compiler}/{variant_name}/link")
        marker = run_checked([str(binary_path)],
                             f"{compiler}/{variant_name}/C-execution",
                             semantic_mutant=hostile)
        if hostile:
            print(f"ROUND058_IMPORT_CODEC_MUTANT_KILLED compiler={compiler} "
                  f"name={variant_name}", flush=True)
        else:
            require("ROUND058_ORIGINAL_IMPORTED_READ_4096_PASS" in marker,
                    f"{compiler} missing compiled/executed full original read")
            print(f"ROUND058_IMPORT_CODEC_BASELINE compiler={compiler} "
                  f"{marker}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", required=True, type=Path)
    linux = parser.parse_args().linux_root.resolve()
    for compiler in ("gcc", "clang"):
        require(shutil.which(compiler) is not None, f"missing compiler {compiler}")
    host_adapter = original_host_adapter()
    verify_original(linux, host_adapter)
    source = IMPORT_HEADER.read_text()
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in source,
            "dormant source guard altered")
    require("lzo1x_decompress_safe(compressed_bytes" in source,
            "not using actual original LZO1X decoder")
    require("LZ4_decompress_safe((const char *)compressed_bytes" in source,
            "existing raw LZ4 decoder missing")
    require(FIXTURE.is_file() and PRODUCT_CODEC.is_file(),
            "missing actual source or fixture")
    with tempfile.TemporaryDirectory(prefix="round058-import-read-") as temp_dir:
        scratch = Path(temp_dir)
        host_include = scratch / "host-shim" / "linux"
        host_include.mkdir(parents=True)
        (host_include / "kernel.h").write_text(host_adapter.KERNEL)
        (host_include / "module.h").write_text(host_adapter.MODULE)
        (host_include / "unaligned.h").write_text(host_adapter.UNALIGNED)
        (host_include / "lzo.h").write_text(
            "#include <stddef.h>\n" +
            (linux / "include/linux/lzo.h").read_text())
        for compiler in ("gcc", "clang"):
            test_compiler(compiler, scratch, linux, source, host_adapter)
    print("ROUND058_IMPORTED_ORIGINAL_CODEC_C_PASS baselines=2 "
          "semantically_rejected_executed_mutants=14 "
          "pin=" + ORIGINAL_PIN +
          " source_authenticated=0 phase_a=BLOCKED "
          "direct_compressed_handoff=DISABLED", flush=True)


if __name__ == "__main__":
    main()
