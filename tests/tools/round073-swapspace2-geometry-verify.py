#!/usr/bin/env python3
"""Rootless source-compiled SWAPSPACE2 geometry/header and semantic mutants.

Compile exact current authority.h/superblock.h; extract two current
dm-target.c address helpers by balanced C braces. Mutants alter temporary
copies of those C sources, never repository sources or physical devices.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-swapspace2-geometry.c"
AUTHORITY = ROOT / "src/kernel/authority.h"
SUPERBLOCK = ROOT / "src/kernel/superblock.h"
CODEC = ROOT / "src/kernel/codec.h"
DM_TARGET = ROOT / "src/kernel/dm-target.c"

# A compiler error, sanitizer abort or regex-only kill is NOT a mutant kill.
MUTANTS = (
    ("logical-zero", "authority", "if (!logical_pages)", "if (0)"),
    ("reserve-ceiling", "authority", "(logical_pages % 8U != 0U)", "0U"),
    ("two-gc-reserves", "authority", "2U * SWAPZ_SEGMENT_BLOCKS",
     "1U * SWAPZ_SEGMENT_BLOCKS"),
    ("cow-headroom", "authority",
     "#define SWAPZ_FOREGROUND_HEADROOM_BLOCKS SWAPZ_SEGMENT_BLOCKS",
     "#define SWAPZ_FOREGROUND_HEADROOM_BLOCKS 0U"),
    ("u32-addition-wrap", "authority", "(swapz_u64)logical_pages +",
     "(swapz_u32)logical_pages +"),
    ("segment-floor", "authority",
     "SWAPZ_SEGMENT_BLOCKS) * SWAPZ_SEGMENT_BLOCKS;",
     "SWAPZ_SEGMENT_BLOCKS) * 1U;"),
    ("swap-signature", "superblock",
     "'S', 'W', 'A', 'P', 'S', 'P', 'A', 'C', 'E', '2'",
     "'S', 'W', 'A', 'P', 'S', 'P', 'A', 'C', 'E', '9'"),
    ("linux-v1-version", "superblock", "raw_version == 1U",
     "raw_version == 2U"),
    ("swap-last-page-bound", "superblock",
     "parsed.last_page >= complete_pages", "parsed.last_page > complete_pages"),
    ("bad-page-zero", "superblock",
     "if (!bad_page || bad_page > parsed.last_page)",
     "if (bad_page > parsed.last_page)"),
    ("byte-swapped-v1", "superblock",
     "swapz_sb_bswap_u32(raw_version) == 1U",
     "swapz_sb_bswap_u32(raw_version) == 2U"),
    ("physical-range-overrun", "dm",
     "blocks > ctx->physical_blocks - data_block",
     "blocks == ctx->physical_blocks - data_block"),
    ("segment-cross-boundary", "dm",
     "==\n\t       last_block / SWAPZ_SEGMENT_BLOCKS",
     "!=\n\t       last_block / SWAPZ_SEGMENT_BLOCKS"),
    ("protected-header-offset", "dm",
     "ctx->data_start_block + data_block", "data_block"),
    ("bad-segment-offset", "dm",
     "ctx->segment_backing_pages[segment] + offset",
     "ctx->segment_backing_pages[segment] + offset + 1U"),
)


def fail(reason: str) -> None:
    raise RuntimeError("ROUND073_GEOMETRY_FIRST_ERROR " + reason)


def extract_function(source: str, signature: str) -> str:
    if source.count(signature) != 1:
        fail("source-anchor-not-unique:" + signature)
    start = source.index(signature)
    opening = source.find("{", start)
    if opening < 0:
        fail("source-body-missing:" + signature)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    fail("source-unbalanced:" + signature)
    raise AssertionError("unreachable")


def assert_source_invariants(authority: str, superblock: str,
                             codec: str, dm_target: str) -> None:
    anchors = (
        (authority, "_Static_assert(sizeof(struct swapz_map) == 20"),
        (authority, "#define SWAPZ_LINUX_SWAP_HEADER_BLOCKS 1U"),
        (authority, "SWAPZ_FOREGROUND_HEADROOM_BLOCKS"),
        (codec, "#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U"),
        (superblock, "SWAPZ_LINUX_SWAP_UUID_OFFSET 1036U"),
        (superblock, "swapz_linux_swap_header_parse("),
        (dm_target, "static int swapz_validate_linux_swap_header("),
        (dm_target, "region.sector = 0;"),
        (dm_target, "REQ_OP_READ | REQ_SYNC"),
        (dm_target, "ctx->data_start_block = 1U;"),
        (dm_target, "physical = ctx->backing_layout_blocks;"),
        (dm_target, "swapz_authority_validate_geometry("),
        (dm_target, "ctx->segment_backing_pages[clean_index++] ="),
    )
    for source, anchor in anchors:
        if anchor not in source:
            fail("source-contract-anchor-missing:" + anchor)
    if "SWAPZ_CODEC_METADATA_ON_MEDIA 1U" in codec:
        fail("persistent-metadata-guard-reintroduced")


def run_one(compiler: str, label: str, sources: dict[str, str],
            dm_boundary: str, fixture: str, mutant: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="round073-geometry-") as directory:
        root = Path(directory)
        for name, key in (("authority.h", "authority"),
                          ("superblock.h", "superblock"),
                          ("codec.h", "codec")):
            (root / name).write_text(sources[key])
        source_path = root / "test.c"
        source_path.write_text(fixture.replace("/* ROUND073_DM_BOUNDARY */",
                                              dm_boundary))
        binary = root / "test"
        command = (compiler, "-std=c2x", "-O1", "-g",
                   "-Wall", "-Wextra", "-Wpedantic", "-Wconversion",
                   "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-I", str(root), str(source_path), "-o", str(binary))
        compiled = subprocess.run(command, capture_output=True, text=True,
                                  timeout=60, check=False)
        if compiled.returncode:
            first = next((line.strip() for line in compiled.stderr.splitlines()
                          if "error:" in line), compiled.stderr.strip()[:200])
            fail(f"{compiler}:{label}:compile:{first[:240]}")
        env = dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1",
                   UBSAN_OPTIONS="halt_on_error=1")
        executed = subprocess.run((str(binary),), capture_output=True, text=True,
                                  timeout=30, check=False, env=env)
        if executed.returncode < 0 or "AddressSanitizer" in executed.stderr or \
                "runtime error:" in executed.stderr:
            fail(f"{compiler}:{label}:sanitizer:{executed.stderr.splitlines()[:1]}")
        if mutant:
            if executed.returncode != 3 or \
                    "ROUND073_GEOMETRY_SEMANTIC_FAILURE case=" not in executed.stderr:
                fail(f"{compiler}:{label}:semantic-mutant-survived:exit={executed.returncode}")
        elif executed.returncode or \
                "ROUND073_GEOMETRY_SOURCE_LINKED_PASS" not in executed.stdout:
            fail(f"{compiler}:baseline:unexpected-exit={executed.returncode}:"
                 + executed.stderr.strip()[:200])


def main() -> None:
    for compiler in ("gcc", "clang"):
        if not shutil.which(compiler):
            fail("compiler-not-available:" + compiler)
    sources = {
        "authority": AUTHORITY.read_text(),
        "superblock": SUPERBLOCK.read_text(),
        "codec": CODEC.read_text(),
    }
    dm_source = DM_TARGET.read_text()
    fixture = FIXTURE.read_text()
    if fixture.count("/* ROUND073_DM_BOUNDARY */") != 1:
        fail("fixture-extraction-marker")
    assert_source_invariants(sources["authority"], sources["superblock"],
                             sources["codec"], dm_source)
    dm_boundary = "\n\n".join((
        extract_function(dm_source, "static inline bool swapz_backing_range_valid("),
        extract_function(dm_source, "static inline sector_t swapz_backing_data_sector("),
    ))
    for compiler in ("gcc", "clang"):
        run_one(compiler, "baseline", sources, dm_boundary, fixture, False)
        count = 0
        for label, target, anchor, mutation in MUTANTS:
            originals = dict(sources)
            modified_dm = dm_boundary
            if target == "dm":
                if dm_boundary.count(anchor) != 1:
                    fail("nonunique-dm-mutant-anchor:" + label)
                modified_dm = dm_boundary.replace(anchor, mutation, 1)
            else:
                if originals[target].count(anchor) != 1:
                    fail("nonunique-header-mutant-anchor:" + label)
                originals[target] = originals[target].replace(anchor, mutation, 1)
            run_one(compiler, label, originals, modified_dm, fixture, True)
            count += 1
        print(f"ROUND073_GEOMETRY_{compiler.upper()}_ASAN_UBSAN_PASS "
              f"baseline=1 semantic_mutants_compiled_executed_killed={count} "
              "native_original=NOT_APPLICABLE physical_io=0 source_auth=0")
    for file in (AUTHORITY, SUPERBLOCK, CODEC, DM_TARGET):
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        print(f"ROUND073_SOURCE_SHA256 {file.relative_to(ROOT)} {digest}")
    print("ROUND073_GEOMETRY_FIRST_ERROR none")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as error:
        print(str(error) if str(error).startswith("ROUND073_GEOMETRY_FIRST_ERROR ")
              else "ROUND073_GEOMETRY_FIRST_ERROR " + str(error)[:240],
              file=sys.stderr)
        raise SystemExit(1) from None
