#!/usr/bin/env python3
"""Compile actual opt-in staged-original C helper under host stubs; no mapped AUTH."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / "tests/runtime/native/fixtures/round063-original-dm-owner.cfrag"
HOST = ROOT / "tests/runtime/native/fixtures/round063-original-dm-owner-host.c"
PASS = "ROUND063_ORIGINAL_DM_OWNER_HOST_PASS scenarios=16 NO_AUTH"
FIRST_ERROR = "ROUND063_OWNER_FIRST_ERROR"
# Mutate ACTUAL compiled C, not the Python expected model or a compiler error.
MUTANTS = (
    ("read-op", "bio_op(clone) != REQ_OP_WRITE", "false"),
    ("swap-flag", "!(clone->bi_opf & REQ_SWAP)", "false"),
    ("clone-owned", "!(clone->bi_flags & (1U << BIO_CLONED))", "false"),
    ("original-origin", "clone->bi_swap_origin != SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK", "false"),
    ("exact-page", "clone->bi_iter.bi_size != 4096U", "false"),
    ("borrowed-bvec-index", "clone->bi_iter.bi_idx", "false"),
    ("clone-vcnt", "clone->bi_vcnt || !clone->bi_io_vec", "false || !clone->bi_io_vec"),
    ("vector-offset", "clone->bi_io_vec[0].bv_offset", "false"),
    ("short-vector", "clone->bi_io_vec[0].bv_len != 4096U", "false"),
    ("sealed-reference", "!swapz_ci_owned_valid(owner)", "false"),
)


def first_error(reason: str) -> None:
    raise RuntimeError("ROUND063_SOURCE_FIRST_ERROR " + reason)


def check(condition: bool, reason: str) -> None:
    if not condition:
        first_error(reason)


def compile_run(compiler: str, code: str, directory: Path, name: str, negative: bool) -> None:
    source_file = directory / (name + ".c")
    binary_file = directory / name
    source_file.write_text(code, encoding="utf-8")
    args = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
            "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
            str(source_file), "-o", str(binary_file)]
    built = subprocess.run(args, capture_output=True, text=True, timeout=90)
    check(built.returncode == 0, "compiler=" + compiler + " case=" + name +
          " exit=" + str(built.returncode))
    result = subprocess.run([str(binary_file)], capture_output=True, text=True,
                            timeout=60, env={**os.environ,
                            "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                            "UBSAN_OPTIONS": "halt_on_error=1"})
    if negative:
        check(result.returncode == 1 and FIRST_ERROR in result.stderr and
              "AddressSanitizer" not in result.stderr and "runtime error:" not in result.stderr,
              "nonsemantic-mutant=" + name + " exit=" + str(result.returncode))
    else:
        check(result.returncode == 0 and PASS in result.stdout and not result.stderr,
              "baseline=" + compiler + " exit=" + str(result.returncode))


def main() -> int:
    fragment = FRAGMENT.read_text(encoding="utf-8")
    host = HOST.read_text(encoding="utf-8")
    check(host.count("/* ROUND063_INJECT_SOURCE */") == 1, "host-marker")
    check(fragment.count("/* ROUND063_ORIGINAL_DM_OWNER_GET_BEGIN */") == 1 and
          fragment.count("/* ROUND063_ORIGINAL_DM_OWNER_GET_END */") == 1,
          "source-marker")
    check("return owner;" in fragment and "swapz_ci_owned_put(owner);" in fragment,
          "original-reference-ownership")
    for name, old, new in MUTANTS:
        check(fragment.count(old) == 1, "mutation-anchor=" + name)
        check(new != old, "inert-mutation=" + name)
    with tempfile.TemporaryDirectory(prefix="round063-original-dm-owner-") as temporary:
        directory = Path(temporary)
        for compiler in ("gcc", "clang"):
            check(shutil.which(compiler) is not None, "missing-compiler=" + compiler)
            compile_run(compiler, host.replace("/* ROUND063_INJECT_SOURCE */", fragment),
                        directory, compiler + "-base", False)
            for name, old, new in MUTANTS:
                changed = fragment.replace(old, new, 1)
                compile_run(compiler, host.replace("/* ROUND063_INJECT_SOURCE */", changed),
                            directory, compiler + "-" + name, True)
            print(f"ROUND063_SOURCE_{compiler.upper()}_GNU11_ASAN_UBSAN_PASS "
                  f"semantic_source_C_mutants={len(MUTANTS)} NO_AUTH")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(str(error)[:380], file=sys.stderr)
        raise SystemExit(2) from None
