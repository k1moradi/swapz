#!/usr/bin/env python3
"""Round059 generic inherited LZ4 host source C (no original Linux LZO ABI).

GCC and Clang compile/link/execute actual dormant import header plus real
swapz codec.c CRC under ASan+UBSan, with changed header C semantic mutants.
This is NO_AUTH host-only proof, not a loaded/physical kernel assertion.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "src/kernel/zswap-import-codec.h"
CODEC = ROOT / "src/kernel/codec.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round059-codec-host-compat.c"

MUTANTS = (
    ("lzo-without-original-decoder",
     "/* No original Linux decoder was linked by generic LZ4 host tests. */\n"
     "\t\treturn -EOPNOTSUPP;",
     "/* Wrongly accepts missing original LZO decoder. */\n"
     "\t\treturn 0;"),
    ("compressed-crc",
     "swapz_crc32c_bytes(compressed_bytes, record->compressed_length) !=",
     "swapz_crc32c_bytes(compressed_bytes, record->compressed_length) =="),
    ("decoded-original-sha",
     "if (digest_difference || (independent_original_page &&",
     "if ((digest_difference && 0U) || (independent_original_page &&"),
    ("one-real-write-ack",
     "authority->upper_write_ack_count != 1U ||",
     "authority->upper_write_ack_count != 2U ||"),
    ("scratch-output-overlap",
     "swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,\n"
     "\t\t\toutput, SWAPZ_BLOCK_BYTES)",
     "(0 && swapz_zswap_import_ranges_overlap(scratch, SWAPZ_BLOCK_BYTES,\n"
     "\t\t\toutput, SWAPZ_BLOCK_BYTES))"),
)


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(f"ROUND059_CODEC_HOST_FIRST_ERROR {detail}")


def execute(command: list[str], label: str, hostile: bool = False) -> str:
    completed = subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=90,
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"},
    )
    sanitizer = any(marker in completed.stderr for marker in (
        "AddressSanitizer", "UndefinedBehaviorSanitizer",
        "LeakSanitizer", "runtime error:",
    ))
    oracle_reject = (completed.returncode == 1 and
                     "ROUND059_CODEC_HOST_FIRST_ERROR line=" in completed.stderr and
                     not sanitizer)
    success = oracle_reject if hostile else (
        completed.returncode == 0 and not completed.stderr and not sanitizer)
    if not success:
        excerpt = "\n".join((completed.stdout + "\n" +
                             completed.stderr).splitlines()[-25:])
        raise AssertionError(
            f"ROUND059_CODEC_HOST_FIRST_ERROR {label} "
            f"exit={completed.returncode} hostile={hostile} "
            f"semantic_oracle={oracle_reject} sanitizer={sanitizer}\n{excerpt}"
        )
    return completed.stdout


def changed_source(header: str, name: str, old: str, new: str) -> str:
    function_start = header.index("static inline int swapz_zswap_import_decode(")
    prefix, function = header[:function_start], header[function_start:]
    require(function.count(old) == 1 and new != old,
            f"{name} header C anchor drift")
    return prefix + function.replace(old, new, 1)


def main() -> None:
    source = HEADER.read_text()
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in source,
            "original codec header unexpectedly active")
    require("#ifdef SWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST" in source,
            "generic host still inherits original LZO header")
    require("#if !defined(SWAPZ_ZSWAP_IMPORT_HOST_TEST) ||" in source,
            "generic host still links original LZO symbol")
    require("selected_lzo_unsupported" in FIXTURE.read_text(),
            "generic fixture lost independent selected-LZO rejection")
    with tempfile.TemporaryDirectory(prefix="round059-lz4-only-source-") as folder:
        temporary = Path(folder)
        for compiler in ("gcc", "clang"):
            require(shutil.which(compiler) is not None, f"compiler {compiler} missing")
            variants = [("baseline", source, False)]
            variants.extend((name, changed_source(source, name, old, new), True)
                            for name, old, new in MUTANTS)
            for name, content, hostile in variants:
                variant = temporary / (compiler + "-" + name)
                variant.mkdir()
                (variant / HEADER.name).write_text(content)
                binary = variant / "real-source-C"
                execute(
                    [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                     "-Wconversion", "-Wshadow", "-Werror",
                     "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                     "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                     "-I", str(variant), "-I", str(HEADER.parent),
                     str(FIXTURE), str(CODEC), "-lcrypto", "-llz4",
                     "-o", str(binary)],
                    f"{compiler}/{name}/compile-and-link")
                undefined = execute(["nm", "-u", str(binary)],
                                    f"{compiler}/{name}/symbol-audit")
                require(not re.search(r"\blzo1x_", undefined),
                        f"{compiler}/{name} unresolved original LZO symbol")
                result = execute([str(binary)], f"{compiler}/{name}/execute",
                                 hostile=hostile)
                if hostile:
                    print(f"ROUND059_GENERIC_HOST_SOURCE_MUTANT_KILLED "
                          f"compiler={compiler} name={name}", flush=True)
                else:
                    require("ROUND059_GENERIC_LZ4_ONLY_HOST_PASS" in result,
                            f"{compiler} missing actual executed generic C")
                    print(f"ROUND059_GENERIC_HOST_BASELINE compiler={compiler} "
                          f"{result.strip()}", flush=True)
    print("ROUND059_GENERIC_LZ4_NO_LINUX_LZO_C_PASS baselines=2 "
          "executed_source_mutants=10 unsupported_lzo=EOPNOTSUPP "
          "linked_original_lzo_symbols=0 source_authenticated=0 "
          "phase_a=BLOCKED physical_io=0", flush=True)


if __name__ == "__main__":
    main()
