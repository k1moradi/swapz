#!/usr/bin/env python3
"""Rootless ROUND078 Agent9 pinned-upstream and product-source length test.

Actual original source C *expressions* from the immutable Linux commit are
compiled inside a controlled host wrapper. Actual unmodified product headers
and codec.c are independently compiled; every mutant changes only a temporary
copy of one product source function, macro or upstream-derived C expression.
A compiler error, sanitizer abort or source mismatch FAILS rather than kills.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINNED_URL = f"https://raw.githubusercontent.com/torvalds/linux/{PIN}/mm/zswap.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round078-original-zswap-length-admission.c"
FILES = {
    "codec.h": ROOT / "src/kernel/codec.h",
    "codec.c": ROOT / "src/kernel/codec.c",
    "zswap-import-codec.h": ROOT / "src/kernel/zswap-import-codec.h",
    "zswap-import-admission.h": ROOT / "src/kernel/zswap-import-admission.h",
    "superblock.h": ROOT / "src/kernel/superblock.h",
    "authority.h": ROOT / "src/kernel/authority.h",
}
SOURCE_BLOBS = {
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "zswap-import-admission.h": "a411da35437cbf9a43c88083d830dc9280f108e8",
}
UPSTREAM_COMPRESSION_MARKER = "/* ROUND078_UPSTREAM_COMPRESSION_CONDITION */"
UPSTREAM_READ_MARKER = "/* ROUND078_UPSTREAM_RAW_READ_CONDITION */"
IMPORT_BEGIN = "static inline int swapz_zswap_admission_begin_mock("
IMPORT_LIVE = "static inline int swapz_zswap_admission_try_live("
IMPORT_WRITE = "static inline int swapz_zswap_admission_lower_write_done("
IMPORT_ACK = "static inline int swapz_zswap_admission_upper_write_ack("
IMPORT_DECODE = "static inline int swapz_zswap_import_decode("

# Each mutation changes a different specific semantic guard in C. All
# compiled and executed with both independent compilers; no syntax mutants.
# Tuple = label, owned source file, exact function signature (None=whole
# source), original text, changed text. Source files are never written.
MUTANTS = (
    ("compressed-limit-permissive", "codec.h", None,
     "#define SWAPZ_MAX_COMPRESSED 3568U",
     "#define SWAPZ_MAX_COMPRESSED 4095U"),
    ("compressed-limit-overstrict", "codec.h", None,
     "#define SWAPZ_MAX_COMPRESSED 3568U",
     "#define SWAPZ_MAX_COMPRESSED 3567U"),
    ("admission-3569-incorrect-accept", "zswap-import-admission.h", IMPORT_BEGIN,
     "record->compressed_length > SWAPZ_MAX_COMPRESSED",
     "record->compressed_length > SWAPZ_BLOCK_BYTES"),
    ("admission-short-buffer", "zswap-import-admission.h", IMPORT_BEGIN,
     "compressed_capacity < record->compressed_length",
     "compressed_capacity > record->compressed_length"),
    ("admission-wrong-decoded-length", "zswap-import-admission.h", IMPORT_BEGIN,
     "record->decoded_length != SWAPZ_BLOCK_BYTES",
     "record->decoded_length == SWAPZ_BLOCK_BYTES"),
    ("admission-header-authorization", "zswap-import-admission.h", IMPORT_BEGIN,
     "!mapping->post_header_extent_authorized", "0"),
    ("admission-original-codec-mismatch", "zswap-import-admission.h",
     IMPORT_BEGIN,
     "record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC",
     "record->codec == SWAPZ_ZSWAP_IMPORT_LZ4_CODEC"),
    ("no-live-carrier", "zswap-import-admission.h", IMPORT_LIVE,
     "return -EOPNOTSUPP;", "return 0;"),
    ("decoder-3569-incorrect-accept", "zswap-import-codec.h", IMPORT_DECODE,
     "record->compressed_length > SWAPZ_MAX_COMPRESSED",
     "record->compressed_length > SWAPZ_BLOCK_BYTES"),
    ("decoder-short-buffer-overread-guard", "zswap-import-codec.h",
     IMPORT_DECODE,
     "compressed_capacity < record->compressed_length",
     "compressed_capacity > record->compressed_length"),
    ("decoder-borrowed-source-lifetime", "zswap-import-codec.h", IMPORT_DECODE,
     "!record->immutable_owned_copy", "0"),
    ("decoder-retired-ram-session", "zswap-import-codec.h", IMPORT_DECODE,
     "!authority->current_owned_ram_session", "0"),
    ("decoder-once-only-upper-ack", "zswap-import-codec.h", IMPORT_DECODE,
     "authority->upper_write_ack_count != 1U",
     "authority->upper_write_ack_count != 2U"),
    ("decoder-partial-lower-read", "zswap-import-codec.h", IMPORT_DECODE,
     "authority->actual_lower_read_bytes != record->compressed_length",
     "authority->actual_lower_read_bytes == record->compressed_length"),
    ("decoder-original-codec-identity", "zswap-import-codec.h", IMPORT_DECODE,
     "record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC && !original_lzo1x",
     "record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC && original_lzo1x"),
    ("decoder-independent-original-sha", "zswap-import-codec.h",
     IMPORT_DECODE,
     "record->original_sha256[offset];",
     "calculated_sha256[offset];"),
    ("decoder-exact-4096-output", "zswap-import-codec.h", IMPORT_DECODE,
     "memcpy(output, scratch, SWAPZ_BLOCK_BYTES);",
     "memcpy(output, scratch, SWAPZ_BLOCK_BYTES - 1U);"),
    ("decoder-genuine-lz4-length", "zswap-import-codec.h", IMPORT_DECODE,
     "if (decoded_bytes != (int)SWAPZ_BLOCK_BYTES)",
     "if (decoded_bytes == (int)SWAPZ_BLOCK_BYTES)"),
    ("mock-lower-partial-write", "zswap-import-admission.h", IMPORT_WRITE,
     "if (lower_error || actual_written_bytes !=",
     "if (lower_error && actual_written_bytes !="),
    ("mock-once-only-ack-phase", "zswap-import-admission.h", IMPORT_ACK,
     "transaction->phase != SWAPZ_ZSWAP_ADMISSION_MAPPED",
     "transaction->phase == SWAPZ_ZSWAP_ADMISSION_MAPPED"),
    ("pinned-original-page-size-branch", "fixture.c", None,
     "comp_ret || !dlen || dlen >= PAGE_SIZE",
     "comp_ret || !dlen || dlen > PAGE_SIZE"),
    ("pinned-original-raw-read-branch", "fixture.c", None,
     "entry->length == PAGE_SIZE",
     "entry->length > PAGE_SIZE"),
)


def fail(reason: str) -> None:
    raise RuntimeError("ROUND078_LENGTH_FIRST_ERROR " + reason)


def source_function(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        fail("source-function-not-unique:" + signature)
    start = source.index(signature)
    opening = source.find("{", start)
    if opening < 0:
        fail("source-function-no-body:" + signature)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    fail("source-function-unbalanced:" + signature)
    raise AssertionError("unreachable")


def exact_replace(source: str, original: str, changed: str,
                  signature: str | None, label: str) -> str:
    if original == changed:
        fail("identity-mutant:" + label)
    scope = source_function(source, signature) if signature else source
    if scope.count(original) != 1:
        fail("missing-or-nonunique-mutant-anchor:" + label)
    if source.count(scope) != 1:
        fail("nonunique-mutant-function:" + label)
    altered = scope.replace(original, changed, 1)
    if altered == scope:
        fail("no-semantic-mutant:" + label)
    return source.replace(scope, altered, 1)


def upstream_expressions(path: Path) -> tuple[str, str, str]:
    source = path.read_text()
    compress = source_function(source, "static bool zswap_compress(")
    decompress = source_function(source, "static bool zswap_decompress(")
    for anchor in (
        "unsigned int dlen = PAGE_SIZE;",
        "comp_ret = crypto_wait_req(crypto_acomp_compress(",
        "dlen = acomp_ctx->req->dlen;",
        "if (!mem_cgroup_zswap_writeback_enabled(folio_memcg(folio)))",
        "dlen = PAGE_SIZE;",
        "dst = kmap_local_folio(folio, index * PAGE_SIZE);",
        "entry->length = dlen;",
    ):
        if anchor not in compress:
            fail("upstream-pinned-compression-guard-drift:" + anchor)
    for anchor in (
        "/* zswap entries of length PAGE_SIZE are not compressed. */",
        "memcpy_from_sglist(dst, input, 0, PAGE_SIZE);",
        "acomp_request_set_params(acomp_ctx->req, input, &output,",
    ):
        if anchor not in decompress:
            fail("upstream-pinned-original-raw-read-drift:" + anchor)
    compression_pattern = re.compile(
        r"\bif \((comp_ret \|\| !dlen \|\| dlen >= PAGE_SIZE)\) \{")
    raw_pattern = re.compile(r"\bif \((entry->length == PAGE_SIZE)\) \{")
    compression = compression_pattern.findall(compress)
    raw = raw_pattern.findall(decompress)
    if len(compression) != 1 or len(raw) != 1:
        fail("upstream-pinned-boundary-not-unique")
    return compression[0], raw[0], hashlib.sha256(path.read_bytes()).hexdigest()


def source_blobs() -> dict[str, str]:
    files = {name: path.read_text() for name, path in FILES.items()}
    for name, digest in SOURCE_BLOBS.items():
        raw = FILES[name].read_bytes()
        actual = hashlib.sha1(
            f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()
        if actual != digest:
            fail("original-product-source-blob-drift:" + name + ":" + actual)
    if "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U" not in files["codec.h"] or \
            "#define SWAPZ_BLOCK_BYTES 4096U" not in files["codec.h"] or \
            "#define SWAPZ_MAX_BLOCKS 4U" not in files["codec.h"] or \
            "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" not in files["zswap-import-codec.h"] or \
            "#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U" not in files["zswap-import-admission.h"] or \
            "_Static_assert(sizeof(struct swapz_map) == 20" not in files["authority.h"] or \
            "#define SWAPZ_LINUX_SWAP_UUID_OFFSET 1036U" not in files["superblock.h"]:
        fail("current-production-header-contract-drift")
    if len({label for label, *_ in MUTANTS}) != len(MUTANTS):
        fail("duplicate-semantic-mutant-label")
    return files


def compile_and_execute(compiler: str, label: str, sources: dict[str, str],
                        fixture: str, mutant: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="round078-original-length-") as temp:
        directory = Path(temp)
        for name, content in sources.items():
            (directory / name).write_text(content)
        test = directory / "fixture.c"
        test.write_text(fixture)
        executable = directory / "fixture"
        command = [compiler, "-std=c2x", "-O1", "-g",
                   "-Wall", "-Wextra", "-Wpedantic", "-Wconversion",
                   "-Wshadow", "-Wstrict-prototypes", "-Werror",
                   "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                   "-fno-pie", "-no-pie", "-I", str(directory),
                   str(test), str(directory / "codec.c"),
                   "-llz4", "-lcrypto", "-o", str(executable)]
        compiled = subprocess.run(command, capture_output=True, text=True,
                                  timeout=120, check=False)
        if compiled.returncode != 0:
            first_error = next((line.strip() for line in compiled.stderr.splitlines()
                                if "error:" in line),
                               compiled.stderr.strip().splitlines()[0]
                               if compiled.stderr.strip() else "unknown")
            fail(f"{compiler}:{label}:compile:{first_error[:300]}")
        environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                           UBSAN_OPTIONS="halt_on_error=1")
        executed = subprocess.run([str(executable)], capture_output=True,
                                  text=True, timeout=60, check=False,
                                  env=environment)
        if executed.returncode < 0 or "AddressSanitizer" in executed.stderr or \
                "runtime error:" in executed.stderr:
            first_error = executed.stderr.splitlines()[0] if executed.stderr else \
                f"signal-exit={executed.returncode}"
            fail(f"{compiler}:{label}:sanitizer:{first_error[:300]}")
        if mutant:
            if executed.returncode != 3 or \
                    "ROUND078_LENGTH_SEMANTIC_FAILURE case=" not in executed.stderr:
                fail(f"{compiler}:{label}:semantic-mutant-survived:"
                     f"exit={executed.returncode}:"
                     f"{executed.stderr.strip()[:160]}")
        elif executed.returncode != 0 or \
                "ROUND078_LENGTH_SOURCE_C_PASS" not in executed.stdout:
            fail(f"{compiler}:baseline:unexpected-exit={executed.returncode}:"
                 f"{executed.stderr.strip()[:200]}")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "--pinned-linux":
        fail("usage: verifier --pinned-linux PATH (exact original source)")
    original_linux = Path(sys.argv[2])
    if not original_linux.is_file():
        fail("pinned-linux-source-missing")
    for compiler in ("gcc", "clang"):
        if shutil.which(compiler) is None:
            fail("compiler-missing:" + compiler)
    upstream_compression, upstream_raw, original_digest = \
        upstream_expressions(original_linux)
    sources = source_blobs()
    fixture = FIXTURE.read_text()
    if fixture.count(UPSTREAM_COMPRESSION_MARKER) != 1 or \
            fixture.count(UPSTREAM_READ_MARKER) != 1:
        fail("unique-upstream-injection-marker-required")
    fixture = fixture.replace(UPSTREAM_COMPRESSION_MARKER,
                              upstream_compression)
    fixture = fixture.replace(UPSTREAM_READ_MARKER, upstream_raw)
    # Deterministic guard also prevents a compile-only "mutant kill".
    for label, target, signature, old, new in MUTANTS:
        checked = fixture if target == "fixture.c" else sources[target]
        modified = exact_replace(checked, old, new, signature, label)
        if modified == checked:
            fail("no-changed-source-C:" + label)
    for compiler in ("gcc", "clang"):
        compile_and_execute(compiler, "baseline", sources, fixture, False)
        count = 0
        for label, target, signature, old, new in MUTANTS:
            mutated_sources = dict(sources)
            mutated_fixture = fixture
            if target == "fixture.c":
                mutated_fixture = exact_replace(
                    mutated_fixture, old, new, signature, label)
            else:
                mutated_sources[target] = exact_replace(
                    mutated_sources[target], old, new, signature, label)
            compile_and_execute(compiler, label, mutated_sources,
                                mutated_fixture, True)
            count += 1
        print(f"ROUND078_LENGTH_{compiler.upper()}_C23_ASAN_UBSAN_PASS "
              f"baseline_compiled_executed=1 "
              f"independent_semantic_C_mutants_compiled_executed_killed={count} "
              "real_original_native=0 original_lzo1x_decode=NOT_COVERED "
              "physical_io=0 source_auth=0", flush=True)
    print(f"ROUND078_ORIGINAL_PIN torvalds/linux@{PIN} "
          f"mm/zswap.c sha256={original_digest}")
    for name, path in FILES.items():
        print(f"ROUND078_SOURCE_SHA256 {path.relative_to(ROOT)} "
              f"{hashlib.sha256(path.read_bytes()).hexdigest()}")
    print("ROUND078_LENGTH_FIRST_ERROR none")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        first = str(error)
        print(first if first.startswith("ROUND078_LENGTH_FIRST_ERROR ") else
              "ROUND078_LENGTH_FIRST_ERROR " + first[:360],
              file=sys.stderr)
        raise SystemExit(1) from None
