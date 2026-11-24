#!/usr/bin/env python3
"""Exact pinned original Linux LZO1X/raw LZ4 + dormant typed decoder HOST ONLY.

Run from a clean exact source snapshot:
  python3 -B tests/tools/round085-original-decode-verify.py --linux-root /path/to/pin --evidence-dir /private/new-directory
No network, native build, device access or fake durability/ACK. The runner
uses exact upstream byte blobs and the existing R080 host compiler helpers,
not the old R080 mutation suite. Original GNU11 objects get the same narrow
upstream warning model; candidate, fixture and product stay strict C23/C2x.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
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
        # The pinned kernel-only LZ4_compressBound(size_t) inline returns
        # LZ4_COMPRESSBOUND(size_t) as int. It is not called by this fixture.
        # Isolate its conversion diagnostic only while parsing the pristine
        # upstream header; never relax warnings on candidate/product code.
        "lz4.h": ("#pragma once\n#pragma GCC diagnostic push\n"
                  "#pragma GCC diagnostic ignored \"-Wconversion\"\n"
                  "#include <linux/lz4.h>\n#pragma GCC diagnostic pop\n"),
    })
    for relative, content in entries.items():
        path = shim / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    for relative in ("linux/lzo.h", "linux/lz4.h"):
        (shim / relative).write_bytes((linux / "include" / relative).read_bytes())
    return shim


def runtime_failure(execution, expected):
    """Classify actual child output before accepting any semantic kill."""
    stderr = execution.stderr
    sanitizer = None
    category = "unknown"
    for line in stderr.splitlines():
        if "runtime error:" in line or "UndefinedBehaviorSanitizer" in line:
            sanitizer = "UBSan"
            for reason in ("applying zero offset to null pointer", "applying non-zero offset to null pointer",
                           "pointer index expression", "addition of unsigned offset", "subtraction of unsigned offset",
                           "signed integer overflow", "division by zero", "shift exponent", "left shift",
                           "misaligned address", "out of bounds", "null pointer", "insufficient space"):
                if reason in line:
                    category = reason
                    break
            break
        if "AddressSanitizer" in line or "LeakSanitizer" in line:
            sanitizer = "LSan" if "LeakSanitizer" in line else "ASan"
            for reason in ("heap-buffer-overflow", "stack-buffer-overflow", "global-buffer-overflow",
                           "stack-use-after-return", "stack-use-after-scope", "heap-use-after-free",
                           "double-free", "SEGV", "DEADLYSIGNAL", "detected memory leaks"):
                if reason in line:
                    category = reason
                    break
            break
    if sanitizer:
        # Only known source basenames and numeric locations can reach console/JSON.
        names = ("lzo1x_compress.c", "lzo1x_compress_safe.c", "lzo1x_decompress_safe.c",
                 "lz4_compress.c", "lz4_decompress.c", "lz4defs.h", "lzodefs.h", "lz4.h", "lzo.h",
                 "unaligned.h", "kernel.h", "bitops.h", "codec.c", "codec.h", "zswap-import-codec.h",
                 "zswap-import-decoder-owner.c", "zswap-import-decoder-owner.h", "zswap-original-decode.h",
                 "round085-original-decode.c", "original-compressor.c", "diagnostic-probe.c")
        pattern = r"(?:^|[/\s])(" + "|".join(map(re.escape, names)) + r"|case-[0-9]{2}\.c):(\d{1,8})(?::(\d{1,5}))?"
        match = re.search(pattern, stderr, re.M)
        location = ":".join(part for part in match.groups() if part) if match else "unavailable"
        return {"kind": "sanitizer", "sanitizer": sanitizer, "category": category,
                "location": location, "exit": execution.returncode}
    if expected is None:
        if execution.returncode == 0 and not stderr:
            return None
    elif execution.returncode == 1 and not execution.stdout and stderr == f"FIRST_ERROR {expected}\n":
        return None
    return {"kind": "unexpected_execution", "exit": execution.returncode,
            "location": "unavailable"}


def record_execution(state, execution, expected):
    if expected is not None:
        state["mutants_executed"] += 1
    failure = runtime_failure(execution, expected)
    if failure is not None:
        if expected is None:
            state["baseline"] = "FAIL"
        return failure
    if expected is not None:
        state["mutants"].append(expected)
        state["mutants_compiled_executed_killed"] = len(state["mutants"])
    return None


def retain_private(evidence, name, value):
    # Never print the raw child diagnostic. Exclusive private artifact file.
    with os.fdopen(os.open(evidence / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        stream.write(value)


def diagnostic_regression():
    """Real UBSan child, ordinary child failure, exact kill, mixed failure."""
    with tempfile.TemporaryDirectory(prefix="swapz-r087-diagnostic-") as temporary:
        directory = Path(temporary)
        source = directory / "diagnostic-probe.c"
        source.write_text("int main(void) { volatile int zero = 0; return 1 / zero; }\n")
        for compiler in ("gcc", "clang"):
            executable = directory / compiler
            compiled = subprocess.run([compiler, "-std=c2x", "-Wall", "-Wextra", "-Werror",
                                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                                       "-fno-pie", "-no-pie", str(source), "-o", str(executable)],
                                      capture_output=True, text=True, timeout=30)
            require(compiled.returncode == 0 and not compiled.stderr, f"{compiler} diagnostic probe compile")
            actual = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            state = {"baseline": "PENDING", "mutants_executed": 0, "mutants": [],
                     "mutants_compiled_executed_killed": 0}
            failure = record_execution(state, actual, None)
            require(failure is not None and failure["kind"] == "sanitizer" and
                    failure["sanitizer"] == "UBSan" and failure["category"] == "division by zero" and
                    failure["location"].startswith("diagnostic-probe.c:1") and failure["exit"] != 0 and
                    state["baseline"] == "FAIL", f"{compiler} real diagnostic classification")
            ordinary = subprocess.run([sys.executable, "-c", "import sys; sys.stderr.write('private path /tmp/secret\\n'); sys.exit(3)"],
                                      capture_output=True, text=True, timeout=30)
            require(record_execution(state, ordinary, "crc")["kind"] == "unexpected_execution",
                    f"{compiler} ordinary failure classification")
            exact = subprocess.run([sys.executable, "-c", "import sys; sys.stderr.write('FIRST_ERROR crc\\n'); sys.exit(1)"],
                                   capture_output=True, text=True, timeout=30)
            require(record_execution(state, exact, "crc") is None, f"{compiler} exact kill")
            mixed = subprocess.CompletedProcess([], 1, "", exact.stderr + actual.stderr)
            require(record_execution(state, mixed, "sha")["kind"] == "sanitizer" and
                    state["mutants_executed"] == 3 and state["mutants"] == ["crc"] and
                    state["mutants_compiled_executed_killed"] == 1, f"{compiler} sanitizer not counted as kill")
            retain_private(directory, compiler + ".stderr", actual.stderr)
            require((directory / (compiler + ".stderr")).stat().st_mode & 0o777 == 0o600 and
                    (directory / (compiler + ".stderr")).read_text() == actual.stderr,
                    f"{compiler} private diagnostic retention")
            print(f"PASS {compiler} diagnostic regression: real UBSan, ordinary failure, exact kill, mixed failure, private retention", file=sys.stderr)


def execute(compiler: str, linux: Path, workspace: Path, helpers: dict, state: dict, evidence: Path) -> None:
    state["stage"] = "compiler-standard"
    standard = helpers["compiler_standard"](compiler)
    state["standard"] = standard
    compiler_name = Path(compiler).name
    compile_object = helpers["compile_object"]
    checked = helpers["checked"]
    run = helpers["run_command"]
    state["stage"] = "header-scope"
    shim = build_shim(linux, workspace, helpers)
    includes = ["-I", str(shim), "-I", str(ROOT / "src/kernel")]
    # Prove the exact header compiles and its diagnostic scope ends at the
    # include boundary. This negative compile is NOT a semantic mutant.
    strict = [compiler, standard, "-Wall", "-Wextra", "-Wpedantic",
              "-Wconversion", "-Wshadow", "-Werror", *includes,
              "-x", "c", "-fsyntax-only", "-"]
    header_only = run(strict, "upstream header scope",
                      stdin="#include <lz4.h>\nint main(void) { return 0; }\n")
    require(header_only.returncode == 0 and not header_only.stderr,
            f"{compiler_name} pinned LZ4 header: {helpers['first_diagnostic'](header_only)}")
    product_narrowing = run(strict, "strict warning negative",
                            stdin="#include <lz4.h>\nint product_narrowing(size_t length) { return length; }\n")
    require(product_narrowing.returncode != 0 and
            ("-Werror=conversion" in product_narrowing.stderr or
             "-Wshorten-64-to-32" in product_narrowing.stderr),
            f"{compiler_name} header scope leaked or wrong negative diagnostic")
    print(f"PASS {compiler_name} pinned upstream header scope; product narrowing rejected",
          file=sys.stderr, flush=True)
    fixed = []
    # Only original upstream TUs use GNU11 and the already documented narrower
    # original warning model; all candidate/product/test TUs use strict C23/C2x.
    for relative in ("lib/lzo/lzo1x_compress_safe.c", "lib/lzo/lzo1x_decompress_safe.c",
                     "lib/lz4/lz4_compress.c", "lib/lz4/lz4_decompress.c"):
        state["stage"] = "compile-original-" + Path(relative).name
        obj = workspace / (Path(relative).stem + ".o")
        compile_object(compiler, "-std=gnu11", linux / relative, obj,
                       ["-I", str(shim), "-DCONFIG_64BIT=1"], original=True)
        fixed.append(obj)
    adapter = workspace / "original-compressor.c"
    adapter.write_text(COMPRESS_ADAPTER)
    for source in (ROOT / "src/kernel/codec.c", ROOT / "src/kernel/zswap-import-decoder-owner.c",
                   FIXTURE, adapter):
        state["stage"] = "compile-product-" + source.name
        obj = workspace / (source.stem + ".o")
        compile_object(compiler, standard, source, obj, includes)
        fixed.append(obj)
    original = CANDIDATE.read_text()
    cases = [("baseline", original)] + [(name, original.replace(old, new, 1)) for name, old, new in MUTANTS]
    profiles = state["profiles"]
    killed = state["mutants"]
    for index, (name, source) in enumerate(cases):
        unit = workspace / f"case-{index:02d}.c"
        unit.write_text(source)
        obj = unit.with_suffix(".o")
        executable = unit.with_suffix("")
        state["stage"] = "compile-" + name
        compile_object(compiler, standard, unit, obj, includes)
        if index:
            state["mutants_compiled"] += 1
        state["stage"] = "link-" + name
        checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie", str(obj),
                 *(str(path) for path in fixed), "-pthread", "-lcrypto", "-o", str(executable)], f"link {name}")
        state["stage"] = "execute-" + name
        execution = run([str(executable)], name, timeout=30)
        failure = record_execution(state, execution, name if index else None)
        if failure is not None:
            state["first_error"] = failure
            retain_private(evidence, compiler_name + "-" + name + ".stderr", execution.stderr)
            retain_private(evidence, compiler_name + "-" + name + ".stdout", execution.stdout)
            raise RuntimeError("child execution rejected")
        if index == 0:
            match = re.fullmatch(r"PROFILE codec=1 small=(\d+) large=(\d+)\nPROFILE codec=2 small=(\d+) large=(\d+)\nPASS round085-original-decode AUTH=0 PHASE_A=BLOCKED\n", execution.stdout)
            if match is None:
                state["first_error"] = {"kind": "invalid_baseline_output", "exit": execution.returncode}
                retain_private(evidence, compiler_name + "-baseline.stdout", execution.stdout)
                raise RuntimeError("invalid baseline output")
            for codec, offset in ((1, 1), (2, 3)):
                small, large = int(match.group(offset)), int(match.group(offset + 1))
                require(0 < small <= 3568 < large <= 4095, "invalid real corpus lengths")
                profiles.append({"codec": codec, "small": small, "large": large})
            state["baseline"] = "PASS"
            print(f"PASS {compiler_name} {standard} actual pinned original LZ4/LZO1X + product baseline "
                  f"LZ4={profiles[0]['small']}/{profiles[0]['large']} "
                  f"LZO1X={profiles[1]['small']}/{profiles[1]['large']}", file=sys.stderr, flush=True)
        else:
            print(f"PASS {compiler_name} executed_semantic_mutant={name} count={len(killed)}/{len(MUTANTS)}",
                  file=sys.stderr, flush=True)
    state["stage"] = "complete"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--diagnostic-regression", action="store_true")
    parser.add_argument("--evidence-dir", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.diagnostic_regression:
        diagnostic_regression()
        return 0
    if args.linux_root is None or (not args.preflight_only and args.evidence_dir is None):
        parser.error("linux-root and (for qualification) evidence-dir are required")
    results = {name: {"baseline": "NOT_RUN", "stage": "not-started", "profiles": [],
                      "mutants_compiled": 0, "mutants_executed": 0,
                      "mutants_compiled_executed_killed": 0, "mutants": [], "first_error": None}
               for name in ("gcc", "clang")}
    report = {"status": "FAIL", "linux_pin": PIN, "compilers": results,
              "source_mapped_authenticated": 0, "phase_a": "BLOCKED", "import_active": 0}
    active = None
    try:
        linux = args.linux_root.resolve()
        helpers = verify_inputs(linux)
        if args.preflight_only:
            print(f"PASS original/product whole blobs={len(ORIGINAL) + len(PRODUCT)}; "
                  f"candidate unique semantic anchors={len(MUTANTS)}")
            return 0
        evidence = args.evidence_dir.resolve()
        evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
        report["candidate_blobs"] = {str(path.relative_to(ROOT)): git_blob(path.read_bytes())
                                     for path in (CANDIDATE, CANDIDATE.with_suffix(".h"), FIXTURE, Path(__file__).resolve())}
        with tempfile.TemporaryDirectory(prefix="swapz-round085-original-decode-") as temporary:
            for name in ("gcc", "clang"):
                active = name
                compiler = shutil.which(name)
                require(compiler is not None, f"missing compiler {name}")
                workspace = Path(temporary) / name
                workspace.mkdir()
                execute(compiler, linux, workspace, helpers, results[name], evidence)
        report["status"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        state = results[active] if active else None
        failure = state["first_error"] if state else None
        if failure is None:
            failure = {"kind": type(error).__name__, "location": "unavailable"}
            if state is not None:
                state["first_error"] = failure
        if state is not None and state["stage"] == "execute-baseline" and state["baseline"] != "PASS":
            state["baseline"] = "FAIL"
        if args.evidence_dir is not None:
            try:
                args.evidence_dir.resolve().mkdir(mode=0o700, parents=True, exist_ok=True)
                retain_private(args.evidence_dir.resolve(), "exception.stderr", str(error))
                if isinstance(error, subprocess.TimeoutExpired):
                    for label, value in (("stdout", error.stdout), ("stderr", error.stderr)):
                        if value:
                            retain_private(args.evidence_dir.resolve(), "timeout." + label,
                                           value.decode(errors="replace") if isinstance(value, bytes) else value)
            except OSError:
                print("FIRST_ERROR_RETENTION_FAILED private artifact unavailable", file=sys.stderr)
        report["first_error"] = {"compiler": active, "stage": state["stage"] if state else "preflight", **failure}
        print("FIRST_ERROR round085-agent7 " + json.dumps(report["first_error"], sort_keys=True), file=sys.stderr)
        return 1
    finally:
        if not args.preflight_only:
            print(json.dumps(report, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
