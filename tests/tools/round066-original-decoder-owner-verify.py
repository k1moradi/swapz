#!/usr/bin/env python3
"""Genuine executed decoder-reader lease C, native original ABI compatibility.

Run on rootless hosted GCC/Clang with exact pinned original Linux lzo.h,
real product codec.c and dormant import decoder, real liblzo2/liblz4 payloads.
LZO userland ABI compatibility is NOT an executed original Linux module.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINNED_LZO_HEADER = "4d30e3624acd237290dbfeaefdb9c710e4f85f56"
OWNER = ROOT / "src/kernel/zswap-import-decoder-owner.c"
HEADER = ROOT / "src/kernel/zswap-import-decoder-owner.h"
PRODUCT = ROOT / "src/kernel/zswap-import-codec.h"
CODEC = ROOT / "src/kernel/codec.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round066-original-decoder-owner.c"

# Every mutant changes real owner C that is separately compiled and executed.
# All must be rejected by the runtime semantic oracle, not by compiler errors,
# sanitizer crashes, timeouts, or a mere synthetic string-search control.
MUTANTS = (
    ("close-refuses-new-reader", "if (owner->closing)\n", "if (owner->closing && 0U)\n"),
    ("overflow-refuses", "owner->active_readers == ~0U", "owner->active_readers == 0U"),
    ("double-get-refuses", "if (lease->owner)\n", "if (lease->owner && 0U)\n"),
    ("codec-profile-bound", "record->codec != lease->codec ||", "record->codec == lease->codec ||"),
    ("version-profile-bound", "record->version != lease->version)", "record->version == lease->version)"),
    ("clear-before-put", "lease->owner = NULL;", "lease->owner = owner;"),
    ("one-reader-per-put", "if (owner->active_readers == 0U) {", "if (owner->active_readers == 1U) {"),
    ("close-latches-permanently", "owner->closing = 1U;\n\twhile (owner->active_readers != 0U) {", "owner->closing = 0U;\n\twhile (owner->active_readers != 0U) {"),
    ("unsupported-profile", "if (!swapz_zswap_import_decoder_profile_valid(original_codec,", "if (0 && !swapz_zswap_import_decoder_profile_valid(original_codec,"),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError("ROUND066_DECODER_OWNER_FIRST_ERROR " + message)


def execute(command: list[str], label: str, *, input_text: str | None = None,
            negative: bool = False) -> str:
    process = subprocess.run(command, input=input_text, capture_output=True,
                             text=True, check=False, timeout=45,
                             env={**os.environ,
                                  "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                  "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    sanitizer = bool(re.search(
        r"AddressSanitizer|UndefinedBehaviorSanitizer|LeakSanitizer|runtime error:",
        process.stderr))
    semantic_failure = (process.returncode == 1 and
                        re.search(r"^ROUND066_DECODER_OWNER_FIRST_ERROR line=[0-9]+$",
                                  process.stderr.strip()) is not None)
    valid = (semantic_failure and not sanitizer) if negative else (
        process.returncode == 0 and process.stderr == "" and not sanitizer)
    require(valid, label + f" exit={process.returncode} semantic={int(semantic_failure)} sanitizer={int(sanitizer)}")
    return process.stdout


def check_pin(linux: Path) -> None:
    rev = execute(["git", "-C", str(linux), "rev-parse", "HEAD"],
                  "pinned original source rev").strip()
    require(rev == PIN, "original source pin mismatch")
    source = linux / "include/linux/lzo.h"
    require(source.is_file(), "missing exact original Linux LZO public ABI")
    blob = execute(["git", "-C", str(linux), "hash-object", str(source)],
                   "pinned original LZO header Git object").strip()
    require(blob == PINNED_LZO_HEADER, "original LZO header Git blob mismatch")
    header = source.read_text()
    for anchor in ("LZO_E_INPUT_NOT_CONSUMED", "lzo1x_decompress_safe",
                   "lzo1x_1_compress", "LZO1X_1_MEM_COMPRESS"):
        require(anchor in header, "original LZO ABI drift " + anchor)
    # Actual pinned original loader: a modular exported provider is retained
    # by a consumer-module dependency at resolution and released at unload.
    # A NULL provider is built-in and requires no fabricated module_get.
    loader = (linux / "kernel/module/main.c").read_text()
    for anchor in ("static int ref_module(struct module *a, struct module *b)",
                   "if (b == NULL || already_uses(a, b))",
                   "err = strong_try_module_get(b);",
                   "err = add_module_usage(a, b);",
                   "err = ref_module(mod, fsa.owner);",
                   "module_put(i);"):
        require(anchor in loader, "original loader dependency contract drift")
    product_header = PRODUCT.read_text()
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in product_header,
            "original import unexpectedly enabled")
    require("return swapz_zswap_import_decode(record, authority," in OWNER.read_text(),
            "real product decoder no longer consumed by independent owner")


def run_suite(linux: Path) -> None:
    owner_source = OWNER.read_text()
    with tempfile.TemporaryDirectory(prefix="round066-original-decoder-owner-") as directory:
        workspace = Path(directory)
        for compiler in ("gcc", "clang"):
            for name, old, replacement in (("baseline", "", ""), *MUTANTS):
                variant = workspace / (compiler + "-" + name)
                variant.mkdir(mode=0o700)
                require(not old or owner_source.count(old) == 1,
                        "actual changed C mutation anchor drift " + name)
                (variant / OWNER.name).write_text(
                    owner_source if not old else owner_source.replace(old, replacement, 1))
                binary = variant / "actual-decoder-owner"
                flags = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                         "-Wconversion", "-Wshadow", "-Werror",
                         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                         "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
                         "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
                         "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
                         "-I", str(ROOT / "src/kernel"), "-I", str(linux / "include"),
                         str(variant / OWNER.name), str(FIXTURE), str(CODEC),
                         "-pthread", "-llz4", "-llzo2", "-lcrypto", "-o", str(binary)]
                execute(flags, compiler + "/" + name + "/compile")
                output = execute([str(binary)], compiler + "/" + name + "/execute",
                                 negative=name != "baseline")
                if name == "baseline":
                    require("ROUND066_DECODER_OWNER_HOST_PASS profiles=2" in output,
                            compiler + " missing actual selected original decode")
                print(f"ROUND066_DECODER_OWNER_CASE_PASS compiler={compiler} case={name}", flush=True)
    print("ROUND066_DECODER_OWNER_GCC_CLANG_ASAN_UBSAN_PASS "
          f"executed_baselines=2 compiled_executed_semantic_mutants={2 * len(MUTANTS)} "
          "actual_original_lzo_abi=YES host_liblzo_abi_only=YES "
          "loaded_kernel=NO module_unload=NO auth=0", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        original_linux_root = arguments.linux_root.resolve()
        check_pin(original_linux_root)
        run_suite(original_linux_root)
    except (AssertionError, OSError, subprocess.TimeoutExpired) as error:
        detail = str(error) if isinstance(error, AssertionError) else type(error).__name__
        parser.exit(1, detail + "\n")


if __name__ == "__main__":
    main()
