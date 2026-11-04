#!/usr/bin/env python3
"""Private, rootless kernel debug preflight, sparse gate and owned-run verifier.

This is not the official make test interface. Nothing here loads modules,
modifies storage, changes the host kernel or enables kernel fault injection.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


FEATURE_SYMBOLS = {
    "kasan": ("CONFIG_KASAN",),
    "kcsan": ("CONFIG_KCSAN",),
    "lockdep": ("CONFIG_PROVE_LOCKING", "CONFIG_LOCKDEP", "CONFIG_DEBUG_LOCK_ALLOC"),
}
BOOT_DISABLE = {
    "kasan": ("kasan=off",),
    "kcsan": ("kcsan.enabled=0",),
    "lockdep": ("lockdep=off",),
}
# These are exact observed records from the existing, privately owned RAM
# lower-device oracle. Each must occur exactly once, not merely as a substring.
REQUIRED_RECORDS = (
    r"PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0",
    r"PASS_LOADED_COMPOUND_BIO=written_pages:384 verified_pages:384 .* failed:0",
    r"PASS_LOADED_LIVE_GC=victims:[1-9][0-9]* .* verified_pages:4096",
    r"PASS_LOADED_DISCARD_TRIM=pages:256 .* verified_pages:4096",
    r"PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 .* verified_pages:128",
    r"PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0",
    r"PASS_LOADED_SYNTHETIC_READ_FAULT=page:[0-9]+ injected:1 syscall_errno:EIO lower_read_delta:0 submitted_delta:0",
    r"PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
    r"PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 .*",
    r"PASS_LOADED_COMPLETION_HANDOFF=offloaded:[1-9][0-9]* verified_pages:128 completed_writes:16512 active_after:0 fault_offloaded:[1-9][0-9]* fault_injected:1 post_failure_eio:1",
    r"PASS: loaded isolated swapz byte-exact I/O, clean teardown",
)
# All kernel diagnostics in the bounded session fail the gate, not just those
# attributed to swapz: an unrelated issue makes the evidence ambiguous.
KERNEL_DIAGNOSTIC = re.compile(
    r"BUG: (?:KASAN|KCSAN|unable to handle kernel)|"
    r"KASAN:.*(?:use-after-free|out-of-bounds)|"
    r"KCSAN:.*data-race|"
    r"possible (?:circular locking dependency|recursive locking) detected|"
    r"inconsistent lock state|held lock freed|"
    r"sleeping function called from invalid context|"
    r"refcount_t: (?:underflow|overflow)|"
    r"WARNING:|kernel BUG at|general protection fault|"
    r"workqueue:.*(?:swapz|dm_swapz)|"
    r"BUG: workqueue|INFO: task .* blocked for more than",
    re.IGNORECASE,
)
SOURCE_DIAGNOSTIC = re.compile(
    r"^.*\.(?:c|h):[0-9]+(?::[0-9]+)?:\s*(?:warn|warning|error):",
    re.IGNORECASE,
)
CHECK_RECORD = re.compile(r"\bCHECK\s+(\S+\.c)\b")


def load_config(path: Path) -> dict[str, str]:
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as source:
                contents = source.read()
        else:
            contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"kernel configuration unreadable: {error}") from error
    values: dict[str, str] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(y|m|n)", line)
        if match:
            values[match.group(1)] = match.group(2)
        match = re.fullmatch(r"# (CONFIG_[A-Z0-9_]+) is not set", line)
        if match:
            values[match.group(1)] = "n"
    return values


def host_config_path() -> Path | None:
    release = subprocess.check_output(["uname", "-r"], text=True).strip()
    candidates = (
        Path("/proc/config.gz"),
        Path(f"/boot/config-{release}"),
        Path(f"/lib/modules/{release}/build/.config"),
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def required_features(argument: str) -> tuple[str, ...]:
    names = tuple(name for name in argument.split(",") if name)
    if len(set(names)) != len(names) or any(name not in FEATURE_SYMBOLS for name in names):
        raise ValueError("required features must be unique: kasan,lockdep or kcsan")
    if "kcsan" in names and len(names) != 1:
        raise ValueError("KCSAN runs as a separate lane")
    return names


def probe(config_path: Path | None, cmdline_path: Path) -> dict[str, str]:
    if config_path is None:
        return {feature: "UNKNOWN" for feature in FEATURE_SYMBOLS}
    config = load_config(config_path)
    try:
        cmdline = cmdline_path.read_text(encoding="utf-8").split()
    except (OSError, UnicodeError):
        cmdline = None
    result = {}
    for feature, symbols in FEATURE_SYMBOLS.items():
        states = [config.get(symbol, "unknown") for symbol in symbols]
        if "n" in states or "m" in states:
            result[feature] = "UNAVAILABLE"
        elif "unknown" in states or cmdline is None:
            result[feature] = "UNKNOWN"
        elif any(option in cmdline for option in BOOT_DISABLE[feature]):
            result[feature] = "DISABLED_AT_BOOT"
        else:
            result[feature] = "DETECTED"
    return result


def check_features(features: dict[str, str], required: tuple[str, ...]) -> bool:
    return all(features[name] == "DETECTED" for name in required)


def classify_warning(line: str) -> str:
    lower = line.lower()
    if "undefined identifier '__builtin_shuffle'" in lower:
        return "unsupported_simd_builtin"
    if re.search(r"predictor-(?:sse2|avx2|avx512)\.c:[0-9]+:[0-9]+: error: invalid initializer", lower):
        return "simd_initializer"
    if "context imbalance" in lower or "incorrect type in argument" in lower:
        return "locking_or_type"
    if "__user" in lower or "address space" in lower:
        return "address_space"
    if "restricted " in lower or "__le" in lower or "__be" in lower:
        return "endian_or_bitwise"
    if "uninitialized" in lower:
        return "uninitialized"
    return "other"


def scan_static(output: str) -> tuple[int, dict[str, int]]:
    counts: dict[str, int] = {}
    for line in output.splitlines():
        if SOURCE_DIAGNOSTIC.search(line):
            category = classify_warning(line)
            counts[category] = counts.get(category, 0) + 1
    return len(CHECK_RECORD.findall(output)), counts


def run_static(root: Path, kdir: Path, analyzer: str) -> tuple[str, int, dict[str, int]]:
    if shutil.which(analyzer) is None:
        return "UNAVAILABLE", 0, {}
    command = [
        "make", "-C", str(root / "src/kernel"), f"KDIR={kdir}",
        "W=1", "C=2", f"CHECK={analyzer}", "all",
    ]
    try:
        result = subprocess.run(
            command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=900, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"FAIL_KERNEL_STATIC_{analyzer.upper()}: {error}", file=sys.stderr)
        return "FAIL", 0, {}
    check_count, warnings = scan_static(result.stdout)
    checked_sources = {Path(path).name for path in CHECK_RECORD.findall(result.stdout)}
    required_sources = {"dm-target.c", "codec.c", "authority.c", "engine.c", "predictor.c"}
    diagnostics = [line for line in result.stdout.splitlines() if SOURCE_DIAGNOSTIC.search(line)]
    if diagnostics:
        # Bounded fail-only logging: emit a representative sample and exact
        # counts without flooding CI with repeated SIMD parser errors.
        for line in diagnostics[:16]:
            print(line, file=sys.stderr)
        if len(diagnostics) > 16:
            print(f"KERNEL_STATIC_DIAGNOSTICS_SUPPRESSED={len(diagnostics) - 16}", file=sys.stderr)
    if result.returncode != 0 or not required_sources.issubset(checked_sources) or warnings:
        print(
            f"FAIL_KERNEL_STATIC_{analyzer.upper()}: exit={result.returncode} "
            f"checked={sorted(checked_sources)} "
            f"missing={sorted(required_sources - checked_sources)}",
            file=sys.stderr,
        )
        if result.returncode != 0 or not check_count:
            print("KERNEL_STATIC_BUILD_TAIL_BEGIN", file=sys.stderr)
            print("\n".join(result.stdout.splitlines()[-45:]), file=sys.stderr)
            print("KERNEL_STATIC_BUILD_TAIL_END", file=sys.stderr)
        return "FAIL", check_count, warnings
    return "PASS", check_count, warnings


def verify_owned_run(
    required: tuple[str, ...], features: dict[str, str],
    baseline: str, final: str, execution: str,
) -> tuple[str, str]:
    if not required or not check_features(features, required):
        return "BLOCKED", "required running-kernel debug features unavailable"
    if not baseline or not final or not final.startswith(baseline):
        return "BLOCKED", "dmesg baseline missing, overwritten or unreadable"
    delta = final[len(baseline):]
    if KERNEL_DIAGNOSTIC.search(delta):
        return "FAIL", "kernel diagnostic appeared during owned run"
    if re.search(r"(?m)^(?:FAIL|BLOCKED|QUARANTINED)(?::|_)", execution):
        return "FAIL", "owned lower reported a failure or quarantine"
    lines = execution.splitlines()
    for record in REQUIRED_RECORDS:
        expression = re.compile(r"^" + record + r"$")
        if sum(bool(expression.fullmatch(line)) for line in lines) != 1:
            return "FAIL", f"missing, repeated or malformed loaded evidence: {record.split('=')[0]}"
    return "PASS", "private RAM lower completed and kernel diagnostics were clean"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    features_parser = subcommands.add_parser("probe")
    features_parser.add_argument("--config", type=Path)
    features_parser.add_argument("--cmdline", type=Path, default=Path("/proc/cmdline"))
    features_parser.add_argument("--require", default="")
    static_parser = subcommands.add_parser("static")
    static_parser.add_argument("--kdir", type=Path, required=True)
    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--config", type=Path)
    verify_parser.add_argument("--cmdline", type=Path, default=Path("/proc/cmdline"))
    verify_parser.add_argument("--require", required=True)
    verify_parser.add_argument("--baseline", type=Path, required=True)
    verify_parser.add_argument("--final", type=Path, required=True)
    verify_parser.add_argument("--execution", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.action == "static":
            root = Path(__file__).resolve().parents[2]
            if not (arguments.kdir / "Makefile").is_file():
                print("BLOCKED_KERNEL_STATIC: kernel Kbuild headers unavailable", file=sys.stderr)
                return 2
            statuses = {}
            for analyzer in ("sparse", "smatch"):
                status, checks, warnings = run_static(root, arguments.kdir.resolve(), analyzer)
                statuses[analyzer] = {"status": status, "checks": checks, "warnings": warnings}
            print("KERNEL_STATIC=" + json.dumps(statuses, sort_keys=True))
            return 0 if statuses["sparse"]["status"] == "PASS" and statuses["smatch"]["status"] != "FAIL" else 2
        required = required_features(arguments.require)
        features = probe(arguments.config or host_config_path(), arguments.cmdline)
        print("KERNEL_DEBUG_PROBE=" + json.dumps(features, sort_keys=True))
        if arguments.action == "probe":
            return 0 if check_features(features, required) else 2
        baseline = arguments.baseline.read_text(encoding="utf-8")
        final = arguments.final.read_text(encoding="utf-8")
        execution = arguments.execution.read_text(encoding="utf-8")
        status, reason = verify_owned_run(required, features, baseline, final, execution)
        print(f"{status}_KERNEL_DEBUG_OWNED=features:{','.join(required)} reason:{reason}")
        return 0 if status == "PASS" else 2
    except (ValueError, OSError, UnicodeError) as error:
        print(f"BLOCKED_KERNEL_DEBUG: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
