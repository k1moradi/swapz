#!/usr/bin/env python3
"""Private, rootless kernel debug preflight, sparse gate and owned-run verifier.

This is not the official make test interface. Nothing here loads modules,
modifies storage, changes the host kernel or enables kernel fault injection.
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
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
KASAN_BOOT_DISABLE = ("kasan=off",)
RUNTIME_SCHEMA = "swapz-kernel-debug-runtime-v2"
DEFAULT_KCSAN_STATUS = Path("/sys/kernel/debug/kcsan")
DEFAULT_LOCKDEP_STATS = Path("/proc/lockdep_stats")
DEFAULT_PROVE_LOCKING = Path("/proc/sys/kernel/prove_locking")
DEFAULT_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
MAX_RUNTIME_AGE_NS = 20 * 60 * 1_000_000_000
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
    r"\bBUG:|\bOops:|\bWARNING:|\bKASAN:|\bKCSAN:|"
    r"\b(?:UBSAN|KFENCE|KMSAN):|"
    r"kernel BUG at|general protection fault|kernel panic|"
    r"possible (?:circular locking dependency|recursive locking) detected|"
    r"inconsistent lock state|held lock freed|"
    r"sleeping function called from invalid context|"
    r"\brefcount(?:_t|_warn_saturate)?:|"
    r"use-after-free|double.free|"
    r"workqueue:.*(?:swapz|dm_swapz)|BUG: workqueue|"
    r"(?:INFO: )?task .* blocked for more than|hung.task|"
    r"rcu: .*detected stalls",
    re.IGNORECASE,
)
SOURCE_DIAGNOSTIC = re.compile(
    r"^.*\.(?:c|h):[0-9]+(?::[0-9]+)?:\s*(?:warn|warning|error):",
    re.IGNORECASE,
)
CHECK_RECORD = re.compile(r"(?m)^[ \t]*CHECK[ \t]+(\S+\.c)[ \t]*$")


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
        elif "unknown" in states:
            result[feature] = "UNKNOWN"
        elif feature == "kasan" and cmdline is None:
            # Only KASAN has a supported boot-time global disable in the
            # configurations this lane can observe. KCSAN/lockdep activity is
            # proved from their live runtime interfaces before and after I/O.
            result[feature] = "UNKNOWN"
        elif feature == "kasan" and any(
                option in cmdline for option in KASAN_BOOT_DISABLE):
            result[feature] = "DISABLED_AT_BOOT"
        else:
            result[feature] = "DETECTED"
    return result


def check_features(features: dict[str, str], required: tuple[str, ...]) -> bool:
    return all(features[name] == "DETECTED" for name in required)


def _read_runtime_text(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"{description} unreadable: {error}") from error


def capture_runtime_snapshot(
    required: tuple[str, ...],
    kcsan_status_path: Path = DEFAULT_KCSAN_STATUS,
    lockdep_stats_path: Path = DEFAULT_LOCKDEP_STATS,
    prove_locking_path: Path = DEFAULT_PROVE_LOCKING,
) -> dict[str, object]:
    if not required:
        raise ValueError("runtime snapshot requires at least one debug feature")
    snapshot: dict[str, object] = {
        "schema": RUNTIME_SCHEMA,
        "required": list(required),
    }
    if "kcsan" in required:
        status = _read_runtime_text(kcsan_status_path, "KCSAN debugfs status")
        enabled = re.findall(r"(?m)^[ \t]*enabled:[^\n]*$", status)
        blacklist = re.findall(r"(?m)^[ \t]*blacklisted functions:[^\n]*$", status)
        if len(enabled) != 1 or not re.fullmatch(
                r"[ \t]*enabled:[ \t]*[01][ \t]*", enabled[0]):
            raise ValueError("KCSAN debugfs status has no unique enabled state")
        if len(blacklist) != 1:
            raise ValueError("KCSAN debugfs status has no unique blacklist state")
        snapshot["kcsan_enabled"] = enabled[0].split(":", 1)[1].strip() == "1"
        snapshot["kcsan_filter_default"] = (
            blacklist[0].split(":", 1)[1].strip() == "none")
    if "lockdep" in required:
        stats = _read_runtime_text(lockdep_stats_path, "lockdep statistics")
        debug_locks = re.findall(
            r"(?m)^[ \t]*debug_locks:[^\n]*$", stats)
        if len(debug_locks) != 1 or not re.fullmatch(
                r"[ \t]*debug_locks:[ \t]*[01][ \t]*", debug_locks[0]):
            raise ValueError("lockdep statistics have no unique debug_locks state")
        prove_locking = _read_runtime_text(
            prove_locking_path, "lockdep prove_locking sysctl").strip()
        if prove_locking not in {"0", "1"}:
            raise ValueError("lockdep prove_locking sysctl is not boolean")
        snapshot["lockdep_debug_locks"] = debug_locks[0].split(":", 1)[1].strip() == "1"
        snapshot["lockdep_prove_locking"] = prove_locking == "1"
    boot_id = _read_runtime_text(DEFAULT_BOOT_ID, "kernel boot identity").strip()
    if not re.fullmatch(
            r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", boot_id):
        raise ValueError("kernel boot identity is malformed")
    snapshot["boot_id"] = boot_id
    snapshot["observed_monotonic_ns"] = time.monotonic_ns()
    return snapshot


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"runtime snapshot has duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"runtime snapshot contains invalid JSON constant: {value}")


def parse_runtime_snapshot(
    contents: str, required: tuple[str, ...],
) -> dict[str, object]:
    try:
        snapshot = json.loads(
            contents, object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"runtime snapshot is invalid JSON: {error}") from error
    if not isinstance(snapshot, dict) or snapshot.get("schema") != RUNTIME_SCHEMA:
        raise ValueError("runtime snapshot schema mismatch")
    if snapshot.get("required") != list(required):
        raise ValueError("runtime snapshot feature set mismatch")
    expected_keys = {
        "schema", "required", "boot_id", "observed_monotonic_ns",
    }
    if "kcsan" in required:
        expected_keys.update(("kcsan_enabled", "kcsan_filter_default"))
        if not isinstance(snapshot.get("kcsan_enabled"), bool):
            raise ValueError("runtime snapshot lacks KCSAN enabled state")
        if not isinstance(snapshot.get("kcsan_filter_default"), bool):
            raise ValueError("runtime snapshot lacks KCSAN report-filter state")
    if "lockdep" in required:
        expected_keys.update(("lockdep_debug_locks", "lockdep_prove_locking"))
        if not isinstance(snapshot.get("lockdep_debug_locks"), bool):
            raise ValueError("runtime snapshot lacks lockdep debug_locks state")
        if not isinstance(snapshot.get("lockdep_prove_locking"), bool):
            raise ValueError("runtime snapshot lacks lockdep prove_locking state")
    if set(snapshot) != expected_keys:
        raise ValueError("runtime snapshot has missing or unexpected fields")
    if not isinstance(snapshot["boot_id"], str) or not re.fullmatch(
            r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",
            snapshot["boot_id"]):
        raise ValueError("runtime snapshot boot identity is malformed")
    monotonic = snapshot["observed_monotonic_ns"]
    if type(monotonic) is not int or monotonic <= 0:
        raise ValueError("runtime snapshot observation time is invalid")
    return snapshot


def runtime_features_active(
    snapshot: dict[str, object], required: tuple[str, ...],
) -> bool:
    if "kcsan" in required and (
            snapshot["kcsan_enabled"] is not True or
            snapshot["kcsan_filter_default"] is not True):
        return False
    if "lockdep" in required and (
            snapshot["lockdep_debug_locks"] is not True or
            snapshot["lockdep_prove_locking"] is not True):
        return False
    return True


def classify_warning(line: str) -> str:
    lower = line.lower()
    if (re.search(r"predictor-shuffle\.h:[0-9]+:[0-9]+: error:",
                  lower) and
            "undefined identifier '__builtin_shuffle'" in lower):
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


def static_required_sources(
    kdir: Path, module_makefile: Path | None = None,
) -> set[str]:
    # Kbuild consumes auto.conf, not necessarily the (possibly stale) .config.
    # Reject contradictory architecture state rather than silently omitting SIMD.
    configurations = [
        candidate for candidate in (
            kdir / "include/config/auto.conf", kdir / ".config",
        ) if candidate.is_file()
    ]
    if not configurations:
        raise ValueError("kernel build configuration unavailable for static source set")
    config = load_config(configurations[0])
    architecture_symbols = (
        "CONFIG_X86_64", "CONFIG_ARM64", "CONFIG_KERNEL_MODE_NEON",
    )
    for secondary in configurations[1:]:
        other_config = load_config(secondary)
        if any(config.get(symbol, "n") != other_config.get(symbol, "n")
               for symbol in architecture_symbols):
            raise ValueError("kernel build configurations contradict Kbuild architecture")
    known_architectures = (
        "CONFIG_X86_64", "CONFIG_ARM64", "CONFIG_X86_32", "CONFIG_ARM",
        "CONFIG_RISCV", "CONFIG_PPC", "CONFIG_PPC64", "CONFIG_S390",
        "CONFIG_MIPS", "CONFIG_LOONGARCH",
    )
    if sum(config.get(symbol) == "y" for symbol in known_architectures) == 0:
        raise ValueError("kernel architecture is not identifiable")
    if config.get("CONFIG_X86_64") == "y" and config.get("CONFIG_ARM64") == "y":
        raise ValueError("kernel build selects contradictory SIMD architectures")

    makefile = module_makefile or (
        Path(__file__).resolve().parents[2] / "src/kernel/Makefile")
    try:
        lines = makefile.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise ValueError(f"module Kbuild unreadable: {error}") from error
    # Evaluate only the external-module branch, and only its CONFIG_*
    # conditions. A new unrecognized source-selection expression blocks the
    # inventory until the analyzer knows how to evaluate it.
    if len(lines) < 2 or lines[1].strip() != "ifneq ($(KERNELRELEASE),)":
        raise ValueError("module Kbuild selection has changed")
    active_conditions: list[bool | None] = [True]
    sources: set[str] = set()
    assignments = 0
    for raw_line in lines[2:]:
        line = raw_line.strip()
        if line == "else" and len(active_conditions) == 1:
            break
        if line.startswith(("ifeq ", "ifneq ")):
            match = re.fullmatch(
                r"ifeq \(\$\(CONFIG_([A-Z0-9_]+)\),y\)", line)
            active_conditions.append(
                active_conditions[-1] and
                config.get(f"CONFIG_{match.group(1)}") == "y"
                if match and active_conditions[-1] is not None else None
            )
        elif line == "endif":
            if len(active_conditions) <= 1:
                raise ValueError("module Kbuild has unbalanced conditionals")
            active_conditions.pop()
        elif line == "else":
            if len(active_conditions) <= 1:
                raise ValueError("module Kbuild has unexpected else")
            parent = active_conditions[-2]
            current = active_conditions[-1]
            active_conditions[-1] = parent and not current if (
                parent is not None and current is not None) else None
        elif line.startswith("dm-swapz-y"):
            match = re.fullmatch(r"dm-swapz-y[ \t]*(:=|\+=)[ \t]*(.*)", line)
            if match is None or active_conditions[-1] is None:
                raise ValueError("module Kbuild source selection is unsupported")
            if active_conditions[-1]:
                assignments += 1
                for object_name in match.group(2).split():
                    if not re.fullmatch(r"[a-z0-9-]+\.o", object_name):
                        raise ValueError("module Kbuild has an invalid object")
                    source_name = object_name[:-2] + ".c"
                    if source_name in sources:
                        raise ValueError("module Kbuild selects a duplicate source")
                    sources.add(source_name)
    else:
        raise ValueError("module Kbuild external-module section is unterminated")
    if len(active_conditions) != 1 or assignments == 0:
        raise ValueError("module Kbuild source selection is incomplete")
    if not {"dm-target.c", "codec.c", "authority.c", "engine.c",
            "predictor.c"}.issubset(sources):
        raise ValueError("module Kbuild core source selection is incomplete")
    return sources


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
    stage_directory = (root / "build/kernel/w1").resolve()
    # A CHECK for another directory or a different copy of the same basename
    # does not prove that Kbuild scanned the translation unit being linked.
    checked_names = [
        Path(path).name for path in CHECK_RECORD.findall(result.stdout)
        if (Path(path) if Path(path).is_absolute()
            else root / path).resolve().parent == stage_directory
    ]
    checked_sources = set(checked_names)
    duplicated_sources = {
        name for name in checked_sources if checked_names.count(name) != 1
    }
    try:
        required_sources = static_required_sources(kdir)
    except ValueError as error:
        print(f"FAIL_KERNEL_STATIC_{analyzer.upper()}: {error}", file=sys.stderr)
        return "FAIL", check_count, warnings
    diagnostics = [line for line in result.stdout.splitlines() if SOURCE_DIAGNOSTIC.search(line)]
    if diagnostics:
        # Bounded fail-only logging: emit a representative sample and exact
        # counts without flooding CI with repeated SIMD parser errors.
        for line in diagnostics[:16]:
            print(line, file=sys.stderr)
        if len(diagnostics) > 16:
            print(f"KERNEL_STATIC_DIAGNOSTICS_SUPPRESSED={len(diagnostics) - 16}", file=sys.stderr)
    if (result.returncode != 0 or not required_sources.issubset(checked_sources)
            or duplicated_sources or warnings):
        print(
            f"FAIL_KERNEL_STATIC_{analyzer.upper()}: exit={result.returncode} "
            f"checked={sorted(checked_sources)} "
            f"missing={sorted(required_sources - checked_sources)} "
            f"duplicate={sorted(duplicated_sources)}",
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
    baseline: str, final: str, execution: str | None,
    runtime_before: str, runtime_after: str, source_sha: str,
) -> tuple[str, str]:
    # Defect evidence is monotonic: read what is available before any feature,
    # provenance or log-continuity condition can return BLOCKED.
    delta = final[len(baseline):] if baseline and final.startswith(baseline) else final
    if KERNEL_DIAGNOSTIC.search(delta):
        return "FAIL", "kernel diagnostic appeared in bounded evidence"
    if execution is not None and re.search(
            r"(?m)^[ \t]*(?:FAIL|BLOCKED|QUARANTINED)(?::|_)", execution):
        return "FAIL", "owned lower reported a failure or quarantine"
    if not required or not check_features(features, required):
        return "BLOCKED", "required running-kernel debug features unavailable"
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        return "BLOCKED", "validated source SHA is malformed"
    if not baseline or not final or not final.startswith(baseline):
        return "BLOCKED", "dmesg baseline missing, overwritten or unreadable"
    if execution is None:
        return "BLOCKED", "owned execution log unreadable"

    lines = execution.splitlines()
    source_markers = [
        line for line in lines if line.lstrip().startswith("SOURCE_HEAD")
    ]
    if source_markers != [f"SOURCE_HEAD={source_sha}"]:
        return "FAIL", "owned lower source marker is missing, duplicated or mismatched"
    for record in REQUIRED_RECORDS:
        marker = record.split("=", 1)[0]
        candidates = [line for line in lines if line.lstrip().startswith(marker)]
        if len(candidates) != 1 or re.fullmatch(record, candidates[0]) is None:
            return "FAIL", f"missing, repeated or malformed loaded evidence: {marker}"

    try:
        before_state = parse_runtime_snapshot(runtime_before, required)
        after_state = parse_runtime_snapshot(runtime_after, required)
    except ValueError as error:
        return "BLOCKED", str(error)
    if not runtime_features_active(before_state, required):
        return "BLOCKED", "required debug feature was inactive before owned I/O"
    if not runtime_features_active(after_state, required):
        return "FAIL", "required debug feature became inactive during owned I/O"
    try:
        current_boot_id = _read_runtime_text(
            DEFAULT_BOOT_ID, "kernel boot identity").strip()
    except ValueError as error:
        return "BLOCKED", str(error)
    now = time.monotonic_ns()
    before_time = before_state["observed_monotonic_ns"]
    after_time = after_state["observed_monotonic_ns"]
    if (before_state["boot_id"] != current_boot_id or
            after_state["boot_id"] != current_boot_id or
            not 0 < before_time < after_time <= now or
            now - before_time > MAX_RUNTIME_AGE_NS):
        return "BLOCKED", "runtime snapshots have stale or inconsistent identity/order"
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
    runtime_parser = subcommands.add_parser("runtime-snapshot")
    runtime_parser.add_argument("--require", required=True)
    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--config", type=Path)
    verify_parser.add_argument("--cmdline", type=Path, default=Path("/proc/cmdline"))
    verify_parser.add_argument("--require", required=True)
    verify_parser.add_argument("--source-sha", required=True)
    verify_parser.add_argument("--baseline", type=Path, required=True)
    verify_parser.add_argument("--final", type=Path, required=True)
    verify_parser.add_argument("--execution", type=Path, required=True)
    verify_parser.add_argument("--runtime-before", type=Path, required=True)
    verify_parser.add_argument("--runtime-after", type=Path, required=True)
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
            if "FAIL" in (statuses["sparse"]["status"], statuses["smatch"]["status"]):
                return 1
            return 0 if statuses["sparse"]["status"] == "PASS" else 2
        required = required_features(arguments.require)
        if arguments.action == "runtime-snapshot":
            snapshot = capture_runtime_snapshot(required)
            print(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
            return 0
        features = probe(arguments.config or host_config_path(), arguments.cmdline)
        print("KERNEL_DEBUG_PROBE=" + json.dumps(features, sort_keys=True))
        if arguments.action == "probe":
            return 0 if check_features(features, required) else 2
        # Read independently: missing late observations cannot hide a failure
        # already recorded in another evidence file.
        def read_optional(path: Path) -> str | None:
            try:
                return path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return None

        baseline = read_optional(arguments.baseline) or ""
        final = read_optional(arguments.final) or ""
        execution = read_optional(arguments.execution)
        runtime_before = read_optional(arguments.runtime_before) or ""
        runtime_after = read_optional(arguments.runtime_after) or ""
        status, reason = verify_owned_run(
            required, features, baseline, final, execution,
            runtime_before, runtime_after, arguments.source_sha,
        )
        print(f"{status}_KERNEL_DEBUG_OWNED=features:{','.join(required)} reason:{reason}")
        return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]
    except (ValueError, OSError, UnicodeError) as error:
        print(f"BLOCKED_KERNEL_DEBUG: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
