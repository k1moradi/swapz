#!/usr/bin/env python3
"""Round060 authentic original x86 GPL decoder export and module-link gate.

No boot, insmod, real source pool, physical I/O, source-map AUTH, or external
module lease is proven. Run only in rootless GitHub Actions against exact
pristine torvalds/linux@c339f4010dea8b0d754f84ace70cd1b089878ef8.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "include/linux/lzo.h": "4d30e3624acd237290dbfeaefdb9c710e4f85f56",
    "include/linux/lz4.h": "ad6042a718b5428792b795db7a8d4ad44c24a985",
    "include/crypto/sha2.h": "22fbc37ae840796ecbafd5eadf23373e51741f9e",
    "lib/lzo/lzo1x_decompress_safe.c": "318abb82c63d2c27c0d5497b7cf4e21d87d13154",
    "lib/lz4/lz4_decompress.c": "3a2cd9acada4a09ef70a344090d48167c46088a1",
    "lib/lzo/Makefile": "fc7b2b7ef4b20ee7719a7efc0518387f82f11c3f",
    "lib/lz4/Makefile": "5b42242afaa20deb165d8a2f0b1c0c842dfcdc39",
    "lib/Kconfig": "1e42f5167c68bc6c734ed7ad69a9eef906af54b9",
    "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
    "crypto/lz4.c": "57b713516aefac823f2af9481c828027b42490dd",
    "lib/crypto/sha256.c": "e8c346f563c5e642541673ec0fb5a15ae1d25264",
}
SYMBOLS = {
    "lzo1x_decompress_safe": ("EXPORT_SYMBOL_GPL", "LZO_DECOMPRESS",
                               "lzo_decompress"),
    "LZ4_decompress_safe": ("EXPORT_SYMBOL", "LZ4_DECOMPRESS",
                            "lz4_decompress"),
    "sha256": ("EXPORT_SYMBOL", None, None),
}
FIXTURE = ROOT / "tests/runtime/native/fixtures/round060-original-decoder-module.c"
HEADER = ROOT / "src/kernel/zswap-import-codec.h"
CODEC = ROOT / "src/kernel/codec.c"
CODEC_HEADER = ROOT / "src/kernel/codec.h"


def require(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError("ROUND060_DECODER_FIRST_ERROR " + detail)


def run_checked(command: list[str], label: str) -> str:
    completed = subprocess.run(command, capture_output=True, text=True,
                               check=False, timeout=80)
    if completed.returncode != 0 or completed.stderr:
        # Do not leak arbitrary subprocess errors or host paths into output.
        raise AssertionError("ROUND060_DECODER_FIRST_ERROR " + label +
                             " command_failure=" + str(completed.returncode))
    return completed.stdout.strip()


def validate_original(linux: Path) -> None:
    require(run_checked(["git", "-C", str(linux), "rev-parse", "HEAD"],
                        "original git HEAD") == PIN, "pinned Linux HEAD drift")
    require(not run_checked(["git", "-C", str(linux), "status", "--porcelain",
                             "--untracked-files=all"], "original clean tree"),
            "original Linux tree is modified")
    for relative_path, expected in ORIGINAL_BLOBS.items():
        actual = run_checked(
            ["git", "-C", str(linux), "hash-object",
             str(linux / relative_path)], relative_path)
        require(actual == expected, "original Git blob drift " + relative_path)
    source = {key: (linux / key).read_text()
              for key in ORIGINAL_BLOBS}
    for name, expected in (
        ("lib/lzo/lzo1x_decompress_safe.c",
         "EXPORT_SYMBOL_GPL(lzo1x_decompress_safe);"),
        ("lib/lz4/lz4_decompress.c",
         "EXPORT_SYMBOL(LZ4_decompress_safe);"),
        ("lib/crypto/sha256.c", "EXPORT_SYMBOL(sha256);"),
        ("crypto/lzo.c", 'cra_driver_name = "lzo-scomp"'),
        ("crypto/lz4.c", 'cra_driver_name = "lz4-scomp"'),
        ("crypto/lzo.c", "lzo1x_decompress_safe(src, slen, dst, &tmp_len);"),
        ("crypto/lz4.c", "LZ4_decompress_safe(src, dst, slen, *dlen)"),
        ("lib/lzo/Makefile",
         "obj-$(CONFIG_LZO_DECOMPRESS) += lzo_decompress.o"),
        ("lib/lz4/Makefile",
         "obj-$(CONFIG_LZ4_DECOMPRESS) += lz4_decompress.o"),
        ("lib/Kconfig", "config LZO_DECOMPRESS"),
        ("lib/Kconfig", "config LZ4_DECOMPRESS"),
    ):
        require(expected in source[name], f"original {name} missing {expected}")
    header = HEADER.read_text()
    require("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in header,
            "import source unexpectedly active")
    for anchor in ("SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
                   "SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
                   "lzo1x_decompress_safe(compressed_bytes",
                   "LZ4_decompress_safe((const char *)compressed_bytes"):
        require(anchor in header, "actual dormant product codec drift: " + anchor)
    require("swapz_zswap_import_decode(" in FIXTURE.read_text(),
            "kernel module fixture does not reference actual imported reader")
    require("round060_unavailable_original_decoder_export" in FIXTURE.read_text(),
            "module negative missing-export probe missing")
    require(CODEC.is_file() and CODEC_HEADER.is_file(),
            "real product CRC32C translation unit unavailable")


def effective_config(path: Path) -> dict[str, str]:
    require(path.is_file(), "missing effective original kernel .config")
    config: dict[str, str] = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"CONFIG_([A-Z0-9_]+)=(y|m|n)", line)
        if match:
            config[match.group(1)] = match.group(2)
        disabled = re.fullmatch(r"# CONFIG_([A-Z0-9_]+) is not set", line)
        if disabled:
            config[disabled.group(1)] = "n"
    return config


def parse_original_symvers(content: str) -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for line in content.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[1] not in SYMBOLS:
            continue
        symbol = fields[1]
        require(symbol not in found, "duplicate original export " + symbol)
        require(re.fullmatch(r"0x[0-9a-fA-F]{8}", fields[0]) is not None,
                "malformed original symbol CRC " + symbol)
        found[symbol] = (fields[2], fields[3])
    return found


def verify_provider(symbols: dict[str, tuple[str, str]],
                    config: dict[str, str], zswap: str) -> dict[str, str]:
    require(config.get("ZSWAP") == zswap, "kernel ZSWAP matrix mismatch")
    require(config.get("MODULES") == "y", "kernel modules not enabled")
    result: dict[str, str] = {}
    for symbol, (export_kind, option, module_name) in SYMBOLS.items():
        require(symbol in symbols,
                "missing originally selected decoder export " + symbol)
        provider, actual_kind = symbols[symbol]
        require(actual_kind == export_kind,
                "original GPL export kind mismatch " + symbol)
        if option:
            mode = config.get(option, "n")
            require(mode in ("m", "y"),
                    "selected decoder configuration unavailable " + option)
            expected_provider = ("vmlinux" if mode == "y"
                                 else "lib/" + ("lzo" if "LZO" in option else "lz4")
                                 + "/" + module_name)
            require(provider == expected_provider,
                    "decoder original Module.symvers provider mismatch " +
                    symbol + " actual=" + provider)
            result[symbol] = mode
        else:
            require(provider != "", "original sha256 missing provider")
            result[symbol] = "symbol"
    return result


def check_module(module: Path, config: dict[str, str],
                 providers: dict[str, str], kernel_release: str) -> None:
    require(module.is_file() and module.stat().st_size > 0,
            "no compiled genuine GPL original decoder .ko")
    require(shutil.which("nm") is not None and
            shutil.which("readelf") is not None,
            "missing original module binutils")
    undefined = run_checked(["nm", "-u", str(module)], "original module ELF nm")
    for name in SYMBOLS:
        require(re.search(r"(?m)^\s+U\s+" + re.escape(name) + r"$",
                          undefined) is not None,
                "compiled module did not retain original decoder link " + name)
    require("swapz_crc32c_bytes" not in undefined,
            "real product CRC32C not linked into module")
    # Read the real ELF .modinfo section with preinstalled GNU binutils.
    # Avoid a dependence on optional kmod/modinfo binaries on rootless CI.
    section = run_checked(["readelf", "-p", ".modinfo", str(module)],
                          "original kernel module ELF .modinfo")
    metadata: dict[str, str] = {}
    for line in section.splitlines():
        field = re.match(r"^\s*\[\s*[0-9a-fA-F]+\]\s+([^=\s]+)=(.*)$",
                         line)
        if field:
            metadata[field.group(1)] = field.group(2).strip()
    require(metadata.get("license") == "GPL",
            "module cannot consume GPL-only LZO export")
    require(metadata.get("vermagic", "").split(maxsplit=1)[0] ==
            kernel_release, "original kernel release mismatch")
    dependency_set = set(filter(None, metadata.get("depends", "").split(",")))
    for name, (_, option, module_name) in SYMBOLS.items():
        if option and providers[name] == "m":
            require(module_name in dependency_set,
                    "original decoder module dependency not retained " +
                    module_name)
    require(config.get("ZSWAP") in ("y", "n"), "unknown ZSWAP matrix")
    print("ROUND060_PINNED_ORIGINAL_DECODER_GPL_MODULE_PASS "
          f"zswap={config['ZSWAP']} "
          f"lzo={providers['lzo1x_decompress_safe']} "
          f"lz4={providers['LZ4_decompress_safe']} "
          "original_exports=2 crc_sha256=LINKED kernel_gpl_modpost=PASS "
          "source_authenticated=0 active=0 loaded=0 physical_io=0",
          flush=True)


def prepare_module(destination: Path) -> None:
    require(not destination.exists() or not any(destination.iterdir()),
            "probe module staging path must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIXTURE, destination / "round060-original-decoder-module.c")
    shutil.copy2(HEADER, destination / HEADER.name)
    shutil.copy2(CODEC_HEADER, destination / CODEC_HEADER.name)
    shutil.copy2(CODEC, destination / CODEC.name)
    # No changed original Linux C and no fake product decoder function.
    (destination / "Makefile").write_text(
        "obj-m := round060-decoder-noauth.o\n"
        "round060-decoder-noauth-y := round060-original-decoder-module.o codec.o\n")
    print("ROUND060_ORIGINAL_DECODER_MODULE_STAGED actual_product_crc=YES "
          "source_authenticated=0 phase_a=BLOCKED", flush=True)


def self_test() -> None:
    original = {
        "lzo1x_decompress_safe":
            ("lib/lzo/lzo_decompress", "EXPORT_SYMBOL_GPL"),
        "LZ4_decompress_safe":
            ("lib/lz4/lz4_decompress", "EXPORT_SYMBOL"),
        "sha256": ("vmlinux", "EXPORT_SYMBOL"),
    }
    effective = {"ZSWAP": "n", "MODULES": "y",
                 "LZO_DECOMPRESS": "m", "LZ4_DECOMPRESS": "m"}
    require(len(verify_provider(original, effective, "n")) == 3,
            "original provider verifier baseline failed")
    mutations = [
        ("lzo-symbol", {k: v for k, v in original.items()
                        if k != "lzo1x_decompress_safe"}, effective),
        ("lz4-symbol", {k: v for k, v in original.items()
                        if k != "LZ4_decompress_safe"}, effective),
        ("lzo-no-config", original, {**effective, "LZO_DECOMPRESS": "n"}),
        ("lz4-no-config", original, {**effective, "LZ4_DECOMPRESS": "n"}),
        ("lzo-export-type", {**original,
                             "lzo1x_decompress_safe":
                             ("lib/lzo/lzo_decompress", "EXPORT_SYMBOL")},
         effective),
        ("wrong-provider", {**original,
                            "LZ4_decompress_safe":
                            ("vmlinux", "EXPORT_SYMBOL")}, effective),
        ("wrong-zswap", original, {**effective, "ZSWAP": "y"}),
    ]
    for label, symbols, config in mutations:
        try:
            verify_provider(symbols, config, "n")
        except AssertionError as error:
            require("ROUND060_DECODER_FIRST_ERROR" in str(error),
                    "mutant rejected without named gate " + label)
        else:
            raise AssertionError(
                "ROUND060_DECODER_FIRST_ERROR unsupported symbol/config "
                "mutation was accepted " + label)
        print("ROUND060_PINNED_MODULE_PROVIDER_MUTANT_REJECTED name=" +
              label, flush=True)
    with tempfile.TemporaryDirectory(prefix="round060-negative-symvers-") as d:
        fake_lines = ("\t".join((f"0x{index+1:08x}", symbol, module, kind))
                      for index, (symbol, (module, kind))
                      in enumerate(original.items()))
        parsed = parse_original_symvers("\n".join(fake_lines))
        require(parsed == original, "Module.symvers format parser drift")
    print("ROUND060_PINNED_PROVIDER_GATES_PASS semantic_mutants=7 "
          "source_authenticated=0 phase_a=BLOCKED", flush=True)


def verify_missing_export_modpost(log: Path) -> None:
    require(log.is_file(), "missing real kernel negative modpost log")
    lines = log.read_text(errors="replace").splitlines()
    # Fail closed if the module was rejected at an unrelated compiler,
    # linker, missing-header or invalid-configuration error.
    failure_lines = [line for line in lines
                     if ("ERROR: modpost:" in line and
                         "round060_unavailable_original_decoder_export" in line
                         and "undefined" in line)]
    require(len(failure_lines) == 1,
            "missing genuine original Linux modpost undefined decoder first cause")
    print("ROUND060_ORIGINAL_KBUILD_NEGATIVE_MISSING_EXPORT_REJECTED "
          "original_modpost=YES auth=0", flush=True)


def report_original_first_error(log: Path, phase: str, exit_code: int) -> None:
    require(log.is_file(), "missing private original Kbuild failure log")
    require(re.fullmatch(r"[a-z0-9-]{1,60}", phase) is not None,
            "invalid original build phase")
    for line in log.read_text(errors="replace").splitlines():
        if not re.search(r"(?i)(?:fatal error:|error:|modpost:.*undefined|no rule to make target)", line):
            continue
        # Print only bounded compiler diagnostics: redact absolute runner
        # paths, ANSI controls, assignment-like values and anything off-source.
        diagnostic = re.sub(
            r"/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+",
            "[original-or-probe-file]", line)
        diagnostic = re.sub(
            r"(?i)(?:token|secret|password|authorization)\s*[:=]\s*\S+",
            "[redacted]", diagnostic)
        diagnostic = re.sub(r"[^\x20-\x7e]", "?", diagnostic)[:240]
        print("::error::ROUND060_DECODER_FIRST_ERROR "
              f"phase={phase} exit={exit_code} first={diagnostic}", flush=True)
        return
    print("::error::ROUND060_DECODER_FIRST_ERROR "
          f"phase={phase} exit={exit_code} no_recognized_source_error",
          flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    check = sub.add_parser("original")
    check.add_argument("--linux-root", required=True, type=Path)
    prep = sub.add_parser("prepare")
    prep.add_argument("--destination", required=True, type=Path)
    native = sub.add_parser("verify-module")
    native.add_argument("--original-config", required=True, type=Path)
    native.add_argument("--symvers", required=True, type=Path)
    native.add_argument("--module", required=True, type=Path)
    native.add_argument("--zswap", required=True, choices=("y", "n"))
    native.add_argument("--kernel-release", required=True)
    first = sub.add_parser("first-error")
    first.add_argument("--log", required=True, type=Path)
    first.add_argument("--phase", required=True)
    first.add_argument("--exit-code", required=True, type=int)
    negative = sub.add_parser("verify-negative")
    negative.add_argument("--log", required=True, type=Path)
    sub.add_parser("self-test")
    arguments = parser.parse_args()
    if arguments.action == "original":
        validate_original(arguments.linux_root.resolve())
        print("ROUND060_ORIGINAL_LINUX_EXACT_BLOBS_AND_CRYPTO_DRIVER_PASS "
              f"pin={PIN} blobs={len(ORIGINAL_BLOBS)}", flush=True)
    elif arguments.action == "prepare":
        prepare_module(arguments.destination.resolve())
    elif arguments.action == "verify-module":
        config = effective_config(arguments.original_config)
        require(arguments.symvers.is_file(),
                "missing compiled original kernel Module.symvers")
        original_symbols = parse_original_symvers(
            arguments.symvers.read_text())
        providers = verify_provider(original_symbols, config, arguments.zswap)
        check_module(arguments.module, config, providers,
                     arguments.kernel_release)
    elif arguments.action == "first-error":
        report_original_first_error(
            arguments.log, arguments.phase, arguments.exit_code)
    elif arguments.action == "verify-negative":
        verify_missing_export_modpost(arguments.log)
    elif arguments.action == "self-test":
        self_test()


if __name__ == "__main__":
    main()
