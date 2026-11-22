#!/usr/bin/env python3
"""Inspect actual pristine Kbuild artifacts; never load a module.

The source-host self-test checks the inspector with real compiler objects,
not kernel exports or decoder semantics. Only native Kbuild can qualify those.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

SYMBOLS = ("lzo1x_decompress_safe", "LZ4_decompress_safe", "sha256",
           "swapz_crc32c_bytes")
STEM = "round060-original-decoder-module"
MODULE = "round060-decoder-noauth"
ROOT = Path(__file__).resolve().parents[2]


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError("ROUND064_DECODER_FIRST_ERROR " + detail)


def private_write(path: Path, content: str) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600),
                   "w", encoding="utf-8") as stream:
        stream.write(content)


def command_output(arguments: list[str], evidence: Path) -> str:
    process = subprocess.run(arguments, capture_output=True, text=True,
                             errors="replace", timeout=80, check=False)
    private_write(evidence, process.stdout + "\n" + process.stderr)
    require(process.returncode == 0, "ELF tool failed " + arguments[0])
    return process.stdout


def symbol_types(table: str, name: str) -> set[str]:
    return {parts[-2] for line in table.splitlines()
            if len(parts := line.split()) >= 2 and parts[-1] == name}


def text_relocations(relocations: str, name: str) -> int:
    count = 0
    in_text = False
    for line in relocations.splitlines():
        section = re.match(r"Relocation section '([^']+)'", line)
        if section:
            in_text = section[1].startswith((".rela.text", ".rel.text"))
        elif in_text and re.match(r"\s*[0-9a-fA-F]+\s+[0-9a-fA-F]+\s+R_", line):
            count += int(name in line.split())
    return count


def inspect_object(path: Path, phase: str, evidence: Path) -> dict[str, tuple[bool, int, bool]]:
    require(path.is_file(), "missing object " + phase)
    table = command_output(["nm", "-a", str(path)], evidence / (phase + ".nm"))
    undefined = command_output(["nm", "-u", str(path)], evidence / (phase + ".undefined"))
    command_output(["readelf", "-Ws", str(path)], evidence / (phase + ".symbols"))
    relocations = command_output(["readelf", "-rW", str(path)], evidence / (phase + ".relocations"))
    command_output(["objdump", "-dr", str(path)], evidence / (phase + ".disassembly"))
    result = {}
    for name in SYMBOLS:
        types = symbol_types(table, name)
        result[name] = ("U" in symbol_types(undefined, name),
                        text_relocations(relocations, name),
                        bool(types - {"U", "w", "v"}))
        unresolved, count, defined = result[name]
        print(f"ROUND064_ELF phase={phase} symbol={name} "
              f"undefined={int(unresolved)} text_relocations={count} defined={int(defined)}",
              flush=True)
    return result


def selected_consumer_present(result: dict[str, tuple[bool, int, bool]]) -> bool:
    return all(result[name][0] and result[name][1] > 0 and not result[name][2]
               for name in SYMBOLS)


def inspect_native(probe: Path, original: Path, evidence: Path, zswap: str) -> None:
    evidence.mkdir(mode=0o700)
    # Save genuine .cmd and preprocessor output privately, never print paths/argv.
    for name, source in ((STEM + ".c", ROOT / "tests/runtime/native/fixtures" / (STEM + ".c")),
                         ("zswap-import-codec.h", ROOT / "src/kernel/zswap-import-codec.h"),
                         ("codec.c", ROOT / "src/kernel/codec.c"),
                         ("codec.h", ROOT / "src/kernel/codec.h")):
        require((probe / name).read_bytes() == source.read_bytes(), "staged source mismatch " + name)
        print(f"ROUND064_SOURCE name={name} sha256={hashlib.sha256(source.read_bytes()).hexdigest()}")
    saved = (probe / ("." + STEM + ".o.cmd")).read_text()
    private_write(evidence / "consumer.cmd", saved)
    compile_commands = [line for line in saved.splitlines()
                        if re.match(r"(?:savedcmd|cmd)_.*:=", line)]
    require(len(compile_commands) == 1, "missing unique saved compiler command")
    command = compile_commands[0].split(":=", 1)[1]
    flags = command.split()
    strict = "-Werror" in flags
    host_test = "SWAPZ_ZSWAP_IMPORT_HOST_TEST" in command
    print("ROUND064_COMPILE_COMMAND "
          f"sha256={hashlib.sha256(command.encode()).hexdigest()} "
          f"compile_only={int('-c' in flags)} werror={int(strict)} "
          f"host_test_macro={int(host_test)} "
          f"source_header_dependency={int('zswap-import-codec.h' in saved)} "
          f"original_lz4_header_dependency={int('include/linux/lz4.h' in saved)}")
    require(strict and "-c" in flags and not host_test, "unexpected native compile flags")
    preprocessed = (probe / (STEM + ".i")).read_text()
    private_write(evidence / "consumer.i", preprocessed)
    code = re.sub(r"(?m)^\s*#.*$", "", preprocessed)
    start = re.search(r"\bswapz_zswap_import_decode\s*\([^;{}]*\)\s*\{", code)
    require(start is not None, "missing preprocessed real decoder definition")
    # The source function has nested blocks; count only its body, not declarations.
    depth = 1
    end = start.end()
    while end < len(code) and depth:
        depth += int(code[end] == "{") - int(code[end] == "}")
        end += 1
    require(depth == 0, "unterminated preprocessed decoder")
    body = code[start.end():end]
    for name in SYMBOLS:
        count = len(re.findall(r"\b" + re.escape(name) + r"\s*\(", body))
        print(f"ROUND064_PREPROCESS symbol={name} calls_in_decoder={count}")
    for tag in (1, 2):
        present = re.search(r"record\s*->\s*codec\s*(?:==|!=)\s*" + str(tag) + r"[uU]?\b", body)
        print(f"ROUND064_PREPROCESS codec_tag={tag} compared={int(present is not None)}")
    config = (original / ".config").read_text()
    for name in ("ZSWAP", "LZO_DECOMPRESS", "LZ4_DECOMPRESS", "MODULES"):
        values = re.findall(r"(?m)^CONFIG_" + name + r"=([ymn])$", config)
        disabled = "# CONFIG_" + name + " is not set" in config.splitlines()
        value = values[0] if len(values) == 1 else "n" if disabled else "unset"
        print(f"ROUND064_CONFIG zswap={zswap} option={name} value={value}")
    symvers = (original / "Module.symvers").read_text().splitlines()
    for name in SYMBOLS[:3]:
        for line in symvers:
            fields = line.split()
            if len(fields) >= 4 and fields[1] == name:
                provider = fields[2] if fields[2] in ("vmlinux", "lib/lzo/lzo_decompress", "lib/lz4/lz4_decompress") else "other"
                export = fields[3] if fields[3] in ("EXPORT_SYMBOL", "EXPORT_SYMBOL_GPL") else "other"
                crc = fields[0] if re.fullmatch(r"0x[0-9a-fA-F]{8}", fields[0]) else "invalid"
                print(f"ROUND064_PROVIDER symbol={name} provider={provider} export={export} crc={crc}")
    consumer = inspect_object(probe / (STEM + ".o"), "consumer", evidence)
    codec = inspect_object(probe / "codec.o", "product-crc", evidence)
    combined = inspect_object(probe / (MODULE + ".o"), "combined", evidence)
    final = inspect_object(probe / (MODULE + ".ko"), "final", evidence)
    # Strengthen, not replace, the existing original GPL provider/ELF verifier.
    require(selected_consumer_present(consumer), "actual consumer missing original external text relocation")
    for stage in (combined, final):
        require(all(stage[name][0] and stage[name][1] > 0 and not stage[name][2]
                    for name in SYMBOLS[:3]), "linked decoder lost original external text relocation")
    require(codec[SYMBOLS[3]][2] and final[SYMBOLS[3]][2] and not final[SYMBOLS[3]][0],
            "actual product CRC not defined in final ELF")
    print("ROUND064_REAL_CONSUMER_ELF_RELOCATIONS_PASS loaded=0 auth=0", flush=True)


def stage_omission(probe: Path) -> None:
    # Modify ONLY the independently staged test copy, not the product header.
    header = probe / "zswap-import-codec.h"
    source = header.read_text()
    anchor = ("decoded_bytes = LZ4_decompress_safe((const char *)compressed_bytes,\n"
              "\t\t\t\t(char *)scratch, (int)record->compressed_length,\n"
              "\t\t\t\t(int)SWAPZ_BLOCK_BYTES);")
    require(source.count(anchor) == 1, "actual LZ4 consumer mutation anchor drift")
    header.write_text(source.replace(anchor, "decoded_bytes = -1;", 1))


def verify_omission(probe: Path, evidence: Path) -> None:
    evidence.mkdir(mode=0o700)
    consumer = inspect_object(probe / (STEM + ".o"), "omission-consumer", evidence)
    final = inspect_object(probe / (MODULE + ".ko"), "omission-final", evidence)
    require(not selected_consumer_present(consumer), "actual LZ4 branch omission accepted")
    for stage in (consumer, final):
        require(stage["LZ4_decompress_safe"] == (False, 0, False),
                "omitted actual LZ4 consumer still has its ELF symbol")
        require(all(stage[name][0] and stage[name][1] > 0 and not stage[name][2]
                    for name in ("lzo1x_decompress_safe", "sha256")),
                "actual omission mutant lost unrelated selected references")
    require(consumer["swapz_crc32c_bytes"][0] and final["swapz_crc32c_bytes"][2],
            "actual omission mutant lost linked product CRC")
    print("ROUND064_ACTUAL_LZ4_BRANCH_OMISSION_REJECTED baseline_success_separately_required=1", flush=True)


def self_test() -> None:
    # Real compiler/ELF regression for the diagnostic oracle, not actual decoders.
    source = """\
extern int lzo1x_decompress_safe(int);
extern int LZ4_decompress_safe(int);
extern int sha256(int);
extern int swapz_crc32c_bytes(int);
int probe(int mode, int value) {
    int decoded = mode ? lzo1x_decompress_safe(value) : LZ4_decompress_safe(value);
    return sha256(decoded) + swapz_crc32c_bytes(value);
}
"""
    with tempfile.TemporaryDirectory(prefix="round064-elf-oracle-") as directory:
        root = Path(directory)
        for compiler in ("gcc", "clang"):
            workspace = root / compiler
            workspace.mkdir(mode=0o700)
            for label, text in (("baseline", source), ("omitted-lz4", source.replace("LZ4_decompress_safe(value)", "value"))):
                artifact = workspace / (label + ".o")
                process = subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror", "-x", "c", "-c", "-", "-o", str(artifact)],
                                         input=text, capture_output=True, text=True, timeout=30, check=False)
                require(process.returncode == 0, compiler + " ELF oracle source compile failed")
                result = inspect_object(artifact, label, workspace)
                require(selected_consumer_present(result) == (label == "baseline"), compiler + " real object omission regression")
                if label != "baseline":
                    require(all(result[name][0] and result[name][1] > 0 for name in SYMBOLS if name != "LZ4_decompress_safe"), "negative removed unrelated consumers")
    print("ROUND064_REAL_GCC_CLANG_ELF_ORACLE_SELFTEST_PASS objects=4 omission_negatives=2 structural_only=1")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    native = sub.add_parser("native")
    for name in ("probe", "original", "evidence"):
        native.add_argument("--" + name, type=Path, required=True)
    native.add_argument("--zswap", choices=("y", "n"), required=True)
    stage = sub.add_parser("stage-omission")
    stage.add_argument("--probe", type=Path, required=True)
    omission = sub.add_parser("verify-omission")
    for name in ("probe", "evidence"):
        omission.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "self-test":
            self_test()
        elif args.action == "native":
            inspect_native(args.probe, args.original, args.evidence, args.zswap)
        elif args.action == "stage-omission":
            stage_omission(args.probe)
        else:
            verify_omission(args.probe, args.evidence)
    except (AssertionError, OSError, subprocess.TimeoutExpired) as error:
        # No exception traceback with runner-local paths or raw subprocess data.
        detail = str(error) if isinstance(error, AssertionError) else type(error).__name__
        parser.exit(1, detail + "\n")


if __name__ == "__main__":
    main()
