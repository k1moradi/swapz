#!/usr/bin/env python3
"""Rootless original Linux Kconfig dependency and exact effective-diff verifier.

The legacy original UML KUnit request directly set hidden compression/CRC32
library symbols. Prove the real original Kconfig provider-selection contracts
and compare the actual generated .config, never a guessed negative result.
"""
from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_KCONFIG = {
    "crypto/Kconfig": "981d5dc422d4c89c743b5724aeacd6aa5120c009",
    "lib/Kconfig": "1e42f5167c68bc6c734ed7ad69a9eef906af54b9",
    "lib/crc/Kconfig": "927fc6a6b2b9d32fc78bf6f21d113c78c53894ab",
    "lib/crypto/Kconfig": "56f308dd027311f69959e7b3166ec9213ccb85fc",
    "mm/Kconfig": "afff1b25b5438756f15e464f63dabdbd5ec6102c",
}
HIDDEN_ORIGINAL_LIBRARIES = (
    "LZO_COMPRESS", "LZO_DECOMPRESS", "LZ4_COMPRESS",
    "LZ4_DECOMPRESS", "CRC32", "CRYPTO_LIB_SHA256",
)
VISIBLE_ORIGINAL_PROVIDERS = (
    ("CRYPTO_LZO", ("LZO_COMPRESS", "LZO_DECOMPRESS")),
    ("CRYPTO_LZ4", ("LZ4_COMPRESS", "LZ4_DECOMPRESS")),
    ("CRYPTO_CRC32C", ("CRC32",)),
    ("CRYPTO_SHA256", ("CRYPTO_LIB_SHA256",)),
)
ENTRY = re.compile(r"^(?:CONFIG_([A-Z0-9_]+)=([ymn0-9]+)|# CONFIG_([A-Z0-9_]+) is not set)$")


class ConfigurationError(Exception):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ConfigurationError(reason)


def parse_config(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = ENTRY.fullmatch(line)
        if not match:
            continue
        name = match.group(1) or match.group(3)
        value = match.group(2) or "n"
        require(name not in values, "duplicate-Kconfig-key:" + name)
        values[name] = value
    return values


def mismatches(request_text: str, effective_text: str) -> list[tuple[str, str, str]]:
    requested = parse_config(request_text)
    generated = parse_config(effective_text)
    require(bool(requested) and bool(generated), "empty-request-or-effective")
    return [(name, requested[name], generated.get(name, "n"))
            for name in sorted(requested)
            if requested[name] != generated.get(name, "n")]


def compare(request: Path, effective: Path, mode: str) -> None:
    require(request.is_file(), "missing-original-request")
    require(effective.is_file(), "missing-original-generated-config")
    differences = mismatches(request.read_text(), effective.read_text())
    if mode == "legacy-negative":
        require(bool(differences), "original-legacy-invalid-Kconfig-accepted")
        for name, requested, generated in differences:
            print("ROUND069_ORIGINAL_LEGACY_KCONFIG_REJECTED "
                  f"key=CONFIG_{name} requested={requested} effective={generated}",
                  flush=True)
        print(f"ROUND069_ORIGINAL_LEGACY_NEGATIVE_PASS exact_missing={len(differences)}",
              flush=True)
    else:
        for name, requested, generated in differences:
            print("::error::ROUND069_ORIGINAL_NATIVE_KCONFIG_FIRST_ERROR "
                  f"key=CONFIG_{name} requested={requested} effective={generated}",
                  file=sys.stderr, flush=True)
        require(not differences, "corrected-original-Kconfig-not-effective")
        print("ROUND069_ORIGINAL_NATIVE_EFFECTIVE_CONFIG_PASS "
              "hidden_lzo_lz4_crc32_sha_selected=YES "
              "original_kernel_PINNED=YES", flush=True)


def verify_original_kconfig(linux: Path) -> None:
    # git -C changes the subprocess cwd. A relative linux/Kconfig pathname
    # would then resolve as linux/linux/... and disguise a valid pin as drift.
    linux = linux.resolve(strict=True)
    command = subprocess.run(
        ["git", "-C", str(linux), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=False, timeout=30)
    require(command.returncode == 0 and command.stdout.strip() == PIN,
            "actual-original-pin")
    sources: dict[str, str] = {}
    for path, sha in ORIGINAL_KCONFIG.items():
        source = linux / path
        require(source.is_file(), "missing-original-Kconfig:" + path)
        command = subprocess.run(
            ["git", "-C", str(linux), "hash-object", str(source)],
            text=True, capture_output=True, check=False, timeout=30)
        require(command.returncode == 0 and command.stdout.strip() == sha,
                "original-Kconfig-blob:" + path)
        sources[path] = source.read_text()
    generic = sources["lib/Kconfig"]
    for name in HIDDEN_ORIGINAL_LIBRARIES:
        text = (sources["lib/crc/Kconfig"] if name == "CRC32" else
                sources["lib/crypto/Kconfig"] if name.startswith("CRYPTO_") else
                generic)
        require(re.search(r"(?m)^config " + name + r"\n\ttristate\n", text) is not None,
                "original-hidden-library-contract:" + name)
    crypto = sources["crypto/Kconfig"]
    for visible, selected in VISIBLE_ORIGINAL_PROVIDERS:
        match = re.search(r"(?m)^config " + visible +
                          r"\n(.*?)(?=^config |\Z)", crypto, re.DOTALL)
        require(match is not None and
                all("\tselect " + name in match.group(1).splitlines()
                    for name in selected),
                "original-provider-does-not-select:" + visible)
    mm = sources["mm/Kconfig"]
    require("config ZSWAP\n\tbool \"Compressed cache for swap pages\"" in mm and
            "select ZSMALLOC" in mm,
            "original-zswap-Kconfig-drift")
    print("ROUND069_ORIGINAL_KCONFIG_PINNED_BLOBS_PASS "
          "count=5 hidden_codec_libraries=6 real_selectors=4",
          flush=True)


def self_test() -> None:
    """Do not count string/config mutants as compiled-and-executed C mutants."""
    fixed = """CONFIG_KUNIT=y
CONFIG_SWAP=y
CONFIG_ZSWAP=y
CONFIG_CRYPTO_SHA256=y
CONFIG_CRYPTO_LZO=y
CONFIG_CRYPTO_LZ4=y
CONFIG_CRYPTO_CRC32C=y
CONFIG_LZO_COMPRESS=y
CONFIG_LZO_DECOMPRESS=y
CONFIG_LZ4_COMPRESS=y
CONFIG_LZ4_DECOMPRESS=y
CONFIG_CRC32=y
CONFIG_CRYPTO_LIB_SHA256=y
# CONFIG_CGROUPS is not set
# CONFIG_KUNIT_ALL_TESTS is not set
"""
    require(not mismatches(fixed, fixed), "fixed-config-baseline-not-accepted")
    rejected = 0
    for label in ("LZO_COMPRESS", "LZO_DECOMPRESS", "LZ4_COMPRESS",
                  "LZ4_DECOMPRESS", "CRC32", "CRYPTO_LIB_SHA256",
                  "CRYPTO_LZ4", "CRYPTO_CRC32C", "ZSWAP", "KUNIT"):
        damaged = fixed.replace(f"CONFIG_{label}=y", f"# CONFIG_{label} is not set")
        changes = mismatches(fixed, damaged)
        require(changes == [(label, "y", "n")],
                "not-attributed-exact-native-missing:" + label)
        rejected += 1
    require(mismatches(fixed, fixed.replace("# CONFIG_CGROUPS is not set",
                                           "CONFIG_CGROUPS=y")) ==
            [("CGROUPS", "n", "y")], "negative-config-not-enforced")
    with tempfile.TemporaryDirectory(prefix="round069-config-") as folder:
        path = Path(folder)
        (path / "requested").write_text(fixed)
        (path / "effective").write_text(fixed)
        compare(path / "requested", path / "effective", "corrected")
        (path / "effective").write_text(
            fixed.replace("CONFIG_LZ4_COMPRESS=y", "# CONFIG_LZ4_COMPRESS is not set"))
        compare(path / "requested", path / "effective", "legacy-negative")
        diagnostic = io.StringIO()
        try:
            # Expected semantic negative: suppress its GitHub ::error
            # annotation, but assert that its exact key was captured.
            with contextlib.redirect_stderr(diagnostic):
                compare(path / "requested", path / "effective", "corrected")
        except ConfigurationError as error:
            require(str(error) == "corrected-original-Kconfig-not-effective" and
                    "key=CONFIG_LZ4_COMPRESS requested=y effective=n"
                    in diagnostic.getvalue(),
                    "wrong-original-Kconfig-first-error")
        else:
            raise ConfigurationError("missing-native-option-was-not-rejected")
    print("ROUND069_ORIGINAL_KCONFIG_VERIFIER_SELFTEST_PASS "
          f"baseline=1 exact_missing_mutants={rejected} negative_cgroups=1 "
          "genuine_baseline_Kconfig_only_in_native_job=YES",
          flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("original")
    check.add_argument("--linux-root", required=True, type=Path)
    validation = sub.add_parser("compare")
    validation.add_argument("--request", required=True, type=Path)
    validation.add_argument("--effective", required=True, type=Path)
    validation.add_argument("--mode", choices=("legacy-negative", "corrected"),
                            required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.command == "original":
            verify_original_kconfig(args.linux_root)
        elif args.command == "compare":
            compare(args.request, args.effective, args.mode)
        else:
            self_test()
        return 0
    except (ConfigurationError, OSError, subprocess.TimeoutExpired) as error:
        cause = str(error) if isinstance(error, ConfigurationError) \
            else type(error).__name__
        print("::error::ROUND069_ORIGINAL_NATIVE_CONFIG_FIRST_ERROR "
              f"phase={args.command} cause={cause[:128]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
