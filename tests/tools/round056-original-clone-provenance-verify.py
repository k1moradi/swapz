#!/usr/bin/env python3
"""Rootless compile/execution of immutable, pristine Linux BIO C fragments.

This host fixture exercises actual original clone/reset C with stubbed allocators.
It does NOT create a genuine DM accepted IO, MM folio, source slot or ACK.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round056-original-clone-owner.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
EXPECTED = {
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
    "drivers/md/dm.c": "1881d86111fb2e655893ad898cf21b88f0e4e7f3",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
}
FUNCTIONS = (
    ("bio_reset", "void bio_reset("),
    ("__bio_clone", "static int __bio_clone("),
    ("bio_alloc_clone", "struct bio *bio_alloc_clone("),
    ("bio_init_clone", "int bio_init_clone("),
)
INJECTIONS = (
    "/* ROUND056_EXTRACT_RESET */",
    "/* ROUND056_EXTRACT_PRIVATE_CLONE */",
    "/* ROUND056_EXTRACT_ALLOC_CLONE */",
    "/* ROUND056_EXTRACT_INIT_CLONE */",
)
MUTATIONS = (
    ("bio_set_flag(bio, BIO_CLONED);",
     "bio_set_flag(bio, BIO_REMAPPED);"),
    ("bio->bi_iter = bio_src->bi_iter;",
     "bio->bi_iter.bi_size = bio_src->bi_iter.bi_size;"),
    ("bio->bi_io_vec = bio_src->bi_io_vec;",
     "bio->bi_io_vec = NULL;"),
    ("memset(bio, 0, BIO_RESET_BYTES);",
     "memset(bio, 0, 0U);"),
)
FIRST_ERROR = "ROUND056_CLONE_FIRST_ERROR stage="


def original_blob(path: Path, name: str) -> str:
    data = path.read_bytes()
    digest = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") +
                          b"\0" + data).hexdigest()
    if digest != EXPECTED[name]:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH pinned " + name +
                             " expected=" + EXPECTED[name] + " actual=" + digest)
    return data.decode("utf-8")


def original_function(source: str, name: str, declaration: str) -> str:
    if source.count(declaration) != 1:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH function " + name)
    begin = source.index(declaration)
    opening = source.find("{", begin + len(declaration))
    if opening < 0 or source.find(";", begin + len(declaration), opening) >= 0:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH function body " + name)
    depth = 0
    for position in range(opening, len(source)):
        character = source[position]
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[begin:position + 1]
    raise AssertionError("SOURCE_CONTRACT_MISMATCH unterminated " + name)


def check_pinned_core(dm_source: str, page_io_source: str) -> None:
    dm_anchors = (
        "clone = bio_alloc_clone(NULL, bio, gfp_mask, &md->mempools->io_bs);",
        "atomic_set(&io->io_count, 2);",
        "this_cpu_inc(*md->pending_io);",
        "clone->bi_end_io = clone_endio;",
        "case DM_MAPIO_SUBMITTED:",
        "free_tio(bio);",
        "dm_io_dec_pending(io, error);",
        "requeued = dm_handle_requeue(io, first_stage);",
        "if (requeued)",
        "bio_endio(bio);",
        "clone->bi_iter.bi_size = to_bytes(*len);",
    )
    for anchor in dm_anchors:
        if anchor not in dm_source:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH original DM: " + anchor)
    for anchor in ("static void end_swap_bio_write(",
                   "folio_end_writeback(", "bio_uninit(bio);",
                   "mempool_free(sio,", "void swap_write_submit("):
        if anchor not in page_io_source:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH original MM: " + anchor)


def composed_source(bio_source: str, mutation: tuple[str, str] | None = None) -> str:
    functions = [original_function(bio_source, name, declaration)
                 for name, declaration in FUNCTIONS]
    if mutation is not None:
        old, new = mutation
        matches = [name for name, function in zip(FUNCTIONS, functions)
                   if function.count(old) == 1]
        if len(matches) != 1:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH mutation " + old)
        functions = [function.replace(old, new, 1) if old in function else function
                     for function in functions]
    fixture = FIXTURE.read_text(encoding="utf-8")
    for marker, function in zip(INJECTIONS, functions):
        if fixture.count(marker) != 1:
            raise AssertionError("SOURCE_CONTRACT_MISMATCH fixture marker " + marker)
        fixture = fixture.replace(marker, function, 1)
    if FIRST_ERROR not in fixture or "SOURCE_MAPPED_AUTHENTICATED=0" not in fixture:
        raise AssertionError("SOURCE_CONTRACT_MISMATCH safety oracle")
    return fixture


def run_binary(compiler: str, code: str, folder: Path, label: str,
               hostile: bool) -> None:
    source = folder / (label + ".c")
    binary = folder / label
    source.write_text(code, encoding="utf-8")
    command = [compiler, "-std=gnu11", "-O1", "-g",
               "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
               "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-fno-omit-frame-pointer", "-no-pie",
               "-o", str(binary), str(source)]
    built = subprocess.run(command, text=True, capture_output=True, timeout=90)
    if built.returncode != 0:
        raise AssertionError("ROUND056_CLONE_FIRST_ERROR stage=compile-" +
                             label + " " + built.stderr[-4500:])
    executed = subprocess.run([str(binary)], capture_output=True, text=True,
                              timeout=90, env={
                                  **os.environ,
                                  "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                  "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                              })
    if hostile:
        if (executed.returncode != 1 or FIRST_ERROR not in executed.stderr or
                "AddressSanitizer" in executed.stderr or
                "runtime error:" in executed.stderr):
            raise AssertionError("ROUND056_CLONE_FIRST_ERROR stage=mutant-" +
                                 label + " exit=" + str(executed.returncode) +
                                 " " + executed.stderr[-3500:])
    elif (executed.returncode or
          "ROUND056_REAL_ORIGINAL_CLONE_FRAGMENT_C_PASS" not in executed.stdout):
        raise AssertionError("ROUND056_CLONE_FIRST_ERROR stage=baseline-" +
                             label + " exit=" + str(executed.returncode) +
                             " " + executed.stderr[-3500:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kernel-root", type=Path, required=True)
    args = parser.parse_args()
    bio = original_blob(args.kernel_root / "block/bio.c", "block/bio.c")
    dm = original_blob(args.kernel_root / "drivers/md/dm.c", "drivers/md/dm.c")
    mm = original_blob(args.kernel_root / "mm/page_io.c", "mm/page_io.c")
    check_pinned_core(dm, mm)
    for name, declaration in FUNCTIONS:
        original_function(bio, name, declaration)
    with tempfile.TemporaryDirectory(prefix="round056-original-bio-") as temp:
        folder = Path(temp)
        for compiler in ("gcc", "clang"):
            if shutil.which(compiler) is None:
                raise AssertionError("ROUND056_CLONE_FIRST_ERROR missing " + compiler)
            run_binary(compiler, composed_source(bio), folder,
                       compiler + "-baseline", False)
            for index, mutation in enumerate(MUTATIONS):
                run_binary(compiler, composed_source(bio, mutation), folder,
                           compiler + "-mutant-" + str(index), True)
            print("ROUND056_PINNED_ORIGINAL_BIO_" + compiler.upper() +
                  "_STRICT_ASAN_UBSAN_4_SOURCE_MUTANTS_PASS")
    print("SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(str(error)) from None
