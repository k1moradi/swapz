#!/usr/bin/env python3
"""Exact pinned original Linux LZO1X/raw LZ4 + dormant typed decoder HOST ONLY.

Run from a clean exact source snapshot:
  python3 -B tests/tools/round085-original-decode-verify.py --linux-root /path/to/pin
No network, native build, device access or fake durability/ACK. The runner
uses exact upstream byte blobs and the existing R080 host compiler helpers,
not the old R080 mutation suite. Original GNU11 objects get the same narrow
upstream warning model; candidate, fixture and product stay strict C23/C2x.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import runpy
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests/tools/round080-original-lzo1x-independent-decoder-verify.py"
CANDIDATE = ROOT / "src/kernel/zswap-original-decode.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round085-original-decode.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PRODUCT = {
    "tests/tools/round080-original-lzo1x-independent-decoder-verify.py": "c2bd6a4d35bc8261e94743f92166b7c436d3c1f2",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "src/kernel/zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
}
ORIGINAL = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
    "crypto/lz4.c": "57b713516aefac823f2af9481c828027b42490dd",
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
    "lib/lzo/lzo1x_compress_safe.c": "371c9f849492814afed88a443acb2262dcf35dfe",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lzo/lzodefs.h": "b60851fcf6ce54b57e87d04e917deaa2b6cf62cc",
    "include/linux/lz4.h": "ad6042a718b5428792b795db7a8d4ad44c24a985",
    "lib/lz4/lz4_compress.c": "2a397bb2c661d9c2e4a7a67d5f50f06bfd42f1f2",
    "lib/lz4/lz4_decompress.c": "3a2cd9acada4a09ef70a344090d48167c46088a1",
    "lib/lz4/lz4defs.h": "17277ec16919f3a554afc7d91ad515c493d745ca",
}
# Each mutant changes one real candidate C guard; named first runtime failure
# is mandatory. No compile rejection, sanitizer fault, or generic exit counts.
MUTANTS = (
    ("geometry_ceiling", "ceiling == SWAPZ_ORIGINAL_DECODE_M3568 ||\n\t\tceiling == SWAPZ_ORIGINAL_DECODE_M4095", "ceiling != 0U"),
    ("geometry_zero", "length != 0U && length <= ceiling", "length <= ceiling"),
    ("geometry_cap", "length <= ceiling;", "length < SWAPZ_BLOCK_BYTES;"),
    ("representation", "record->representation != SWAPZ_ZSWAP_IMPORT_REPRESENTATION", "0"),
    ("codec", "(record->codec != SWAPZ_ZSWAP_IMPORT_LZ4_CODEC &&\n\t     record->codec != SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC)", "0"),
    ("version", "record->version != SWAPZ_ZSWAP_IMPORT_VERSION", "0"),
    ("dictionary", "record->dictionary_id != 0U", "0"),
    ("decoded_size", "record->decoded_length != SWAPZ_BLOCK_BYTES", "0"),
    ("input_capacity", "input_capacity < record->compressed_length", "input_capacity < record->compressed_length - 1U"),
    ("scratch_capacity", "scratch_capacity != SWAPZ_BLOCK_BYTES", "scratch_capacity < SWAPZ_BLOCK_BYTES - 1U"),
    ("output_capacity", "output_capacity != SWAPZ_BLOCK_BYTES", "output_capacity < SWAPZ_BLOCK_BYTES - 1U"),
    ("unretained", "if (!lease->owner)", "if (0 && !lease->owner)"),
    ("lease_codec", "lease->codec != record->codec || lease->version != record->version", "lease->version != record->version"),
    ("crc", "if (swapz_crc32c_bytes(input, record->compressed_length) != record->compressed_crc32c)", "if (0 && swapz_crc32c_bytes(input, record->compressed_length) != record->compressed_crc32c)"),
    ("sha", "if (difference)", "if (0 && difference)"),
    ("alias", "if (!swapz_original_decode_disjoint(lease, record, input, scratch, output))", "if (0 && !swapz_original_decode_disjoint(lease, record, input, scratch, output))"),
    ("lzo_trailing", "if (result != LZO_E_OK)", "if (0 && result != LZO_E_OK)"),
    ("lzo_short_output", "if (decoded_length != SWAPZ_BLOCK_BYTES)", "if (0 && decoded_length != SWAPZ_BLOCK_BYTES)"),
    ("lz4_short_output", "if (result != (int)SWAPZ_BLOCK_BYTES)", "if (0 && result != (int)SWAPZ_BLOCK_BYTES)"),
)

# Exactly the original compressor signatures, never a production compressor.
COMPRESS_ADAPTER = r'''#include "zswap-original-decode.h"
#include <stddef.h>
int round085_compress(swapz_u8 codec, const swapz_u8 *page, swapz_u32 length,
    swapz_u8 *compressed, swapz_u32 capacity, swapz_u32 *written)
{
    static union { max_align_t alignment; unsigned char bytes[LZO1X_1_MEM_COMPRESS]; } lzo;
    static union { max_align_t alignment; unsigned char bytes[LZ4_MEM_COMPRESS]; } lz4;
    if (codec == SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC) {
        size_t actual = capacity;
        int result = lzo1x_1_compress_safe(page, length, compressed, &actual, lzo.bytes);
        if (result != LZO_E_OK || actual > capacity)
            return -EIO;
        *written = (swapz_u32)actual;
        return 0;
    }
    int result = LZ4_compress_default((const char *)page, (char *)compressed,
        (int)length, (int)capacity, lz4.bytes);
    if (result <= 0)
        return -EIO;
    *written = (swapz_u32)result;
    return 0;
}
'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def git_blob(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_inputs(linux: Path) -> dict:
    # Verify the existing helper itself before executing its Python definitions.
    for root, files in ((ROOT, PRODUCT), (linux, ORIGINAL)):
        for relative, expected in files.items():
            path = root / relative
            require(path.is_file() and git_blob(path.read_bytes()) == expected,
                    f"whole Git blob mismatch: {relative} expected={expected}")
    helpers = runpy.run_path(str(HELPER))
    # Accept an immutable connector-exported source tree without .git only
    # because every dependency (including source headers) is whole-blob pinned.
    if (linux / ".git").exists():
        require(helpers["checked"](["git", "-C", str(linux), "rev-parse", "HEAD"], "Linux pin") == PIN,
                "original checkout SHA mismatch")
        require(not helpers["checked"](["git", "-C", str(linux), "status", "--porcelain", "--untracked-files=all"], "Linux clean"),
                "dirty original checkout")
    source = CANDIDATE.read_text()
    for name, old, new in MUTANTS:
        require(source.count(old) == 1 and old != new, f"nonunique/vacuous C mutant: {name}")
    return helpers


def build_shim(linux: Path, workspace: Path, helpers: dict) -> Path:
    shim = workspace / "shim"
    entries = dict(helpers["SHIM"])
    # R080's promoted typeof expression is not suitable for LZ4 u16 reads.
    # Use an exact-width union backed by memcpy, avoiding unaligned dereference.
    original = entries["linux/unaligned.h"]
    pattern = r"^#define get_unaligned\(pointer\).*?$"
    replacement = "#define get_unaligned(pointer) ({ union { __typeof__(*(pointer)) value; unsigned char bytes[sizeof(*(pointer))]; } aligned; memcpy(aligned.bytes, (const void *)(pointer), sizeof(aligned.bytes)); aligned.value; })"
    entries["linux/unaligned.h"], count = re.subn(pattern, replacement, original, flags=re.M)
    require(count == 1, "upstream host shim anchor drift")
    entries["linux/unaligned.h"] += "\nstatic inline void put_unaligned_le16(uint16_t value, void *pointer) { memcpy(pointer, &value, sizeof(value)); }\n"
    entries["linux/module.h"] += "\n#define EXPORT_SYMBOL(...)\n"
    entries.update({
        "linux/types.h": "#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\n#include <linux/kernel.h>\n#ifndef __always_inline\n#define __always_inline inline __attribute__((always_inline))\n#endif\n",
        "linux/string.h": "#pragma once\n#include <string.h>\n",
        "linux/init.h": "#pragma once\n",
        "linux/bitops.h": "#pragma once\n#include <linux/kernel.h>\nstatic inline unsigned int __ffs(unsigned long value) { return (unsigned int)__builtin_ctzl(value); }\n",
        "lz4.h": "#pragma once\n#include <linux/lz4.h>\n",
    })
    for relative, content in entries.items():
        path = shim / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relative in ("linux/lzo.h", "linux/lz4.h"):
        (shim / relative).write_bytes((linux / "include" / relative).read_bytes())
    return shim


def execute(compiler: str, linux: Path, workspace: Path, helpers: dict) -> dict:
    standard = helpers["compiler_standard"](compiler)
    compiler_name = Path(compiler).name
    compile_object = helpers["compile_object"]
    checked = helpers["checked"]
    run = helpers["run_command"]
    shim = build_shim(linux, workspace, helpers)
    includes = ["-I", str(shim), "-I", str(ROOT / "src/kernel")]
    fixed = []
    # Only original upstream TUs use GNU11 and the already documented narrower
    # original warning model; all candidate/product/test TUs use strict C23/C2x.
    for relative in ("lib/lzo/lzo1x_compress_safe.c", "lib/lzo/lzo1x_decompress_safe.c",
                     "lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c"):
        obj = workspace / (Path(relative).stem + ".o")
        compile_object(compiler, "-std=gnu11", linux / relative, obj,
                       ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
        fixed.append(obj)
    adapter = workspace / "original-compressor.c"
    adapter.write_text(COMPRESS_ADAPTER)
    for source in (ROOT / "src/kernel/codec.c", ROOT / "src/kernel/zswap-import-decoder-owner.c",
                   FIXTURE, adapter):
        obj = workspace / (source.stem + ".o")
        compile_object(compiler, standard, source, obj, includes)
        fixed.append(obj)
    original = CANDIDATE.read_text()
    cases = [("baseline", original)] + [(name, original.replace(old, new, 1)) for name, old, new in MUTANTS]
    profiles = []
    killed = []
    for index, (name, source) in enumerate(cases):
        unit = workspace / f"case-{index:02d}.c"
        unit.write_text(source)
        obj = unit.with_suffix(".o")
        executable = unit.with_suffix("")
        compile_object(compiler, standard, unit, obj, includes)
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(obj),
                 *(str(path) for path in fixed), "-pthread", "-lcrypto", "-o", str(executable)], f"link {name}")
        execution = run([str(executable)], name, timeout=30)
        require(not any(token in execution.stderr for token in helpers["SANITIZER"]), f"{name}: sanitizer failure (not a kill)")
        if index == 0:
            match = re.fullmatch(r"PROFILE codec=1 small=(\d+) large=(\d+)\nPROFILE codec=2 small=(\d+) large=(\d+)\nPASS round085-original-decode AUTH=0 PHASE_A=BLOCKED\n", execution.stdout)
            require(execution.returncode == 0 and not execution.stderr and match is not None,
                    f"baseline: {helpers['first_diagnostic'](execution)}")
            for codec, offset in ((1, 1), (2, 3)):
                small, large = int(match.group(offset)), int(match.group(offset + 1))
                require(0 < small <= 3568 < large <= 4095, "invalid real corpus lengths")
                profiles.append({"codec": codec, "small": small, "large": large})
            print(f"PASS {compiler_name} {standard} actual pinned original LZ4/LZO1X + product baseline "
                  f"LZ4={profiles[0]['small']}/{profiles[0]['large']} "
                  f"LZO1X={profiles[1]['small']}/{profiles[1]['large']}", file=sys.stderr, flush=True)
        else:
            require(execution.returncode == 1 and not execution.stdout and execution.stderr == f"FIRST_ERROR {name}\n",
                    f"{name}: survived/wrong first error: {helpers['first_diagnostic'](execution)}")
            killed.append(name)
            print(f"PASS {compiler_name} executed_semantic_mutant={name} count={len(killed)}/{len(MUTANTS)}",
                  file=sys.stderr, flush=True)
    return {"standard": standard, "baseline": "PASS", "profiles": profiles,
            "mutants_compiled_executed_killed": len(killed), "mutants": killed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    try:
        linux = args.linux_root.resolve()
        helpers = verify_inputs(linux)
        if args.preflight_only:
            print(f"PASS original/product whole blobs={len(ORIGINAL) + len(PRODUCT)}; "
                  f"candidate unique semantic anchors={len(MUTANTS)}")
            return 0
        results = {}
        with tempfile.TemporaryDirectory(prefix="swapz-round085-original-decode-") as temporary:
            for name in ("gcc", "clang"):
                compiler = shutil.which(name)
                require(compiler is not None, f"missing compiler {name}")
                workspace = Path(temporary) / name
                workspace.mkdir()
                results[name] = execute(compiler, linux, workspace, helpers)
        print(json.dumps({"status": "PASS_HOST_ONLY", "linux_pin": PIN,
                          "candidate_blobs": {str(path.relative_to(ROOT)): git_blob(path.read_bytes())
                              for path in (CANDIDATE, CANDIDATE.with_suffix(".h"), FIXTURE, Path(__file__).resolve())},
                          "compilers": results, "source_mapped_authenticated": 0,
                          "phase_a": "BLOCKED", "import_active": 0}, indent=2))
        return 0
    except (RuntimeError, OSError, ValueError) as error:
        print(f"FIRST_ERROR round085-agent7 {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
