#!/usr/bin/env python3
"""Private, rootless kernel debug preflight, sparse gate and owned-run verifier.

This is not the official make test interface. Nothing here loads modules,
modifies storage, changes the host kernel or enables kernel fault injection.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import time
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
DEFAULT_MODULE = Path("build/kernel/experimental/dm-swapz.ko")
MAX_RUNTIME_AGE_NS = 20 * 60 * 1_000_000_000
MAX_RUNTIME_SNAPSHOT_CHARS = 16 * 1024
MAX_CMDLINE_CHARS = 64 * 1024
MAX_CONFIG_CHARS = 4 * 1024 * 1024
MAX_DMESG_BYTES = 64 * 1024 * 1024
MAX_EXECUTION_BYTES = 16 * 1024 * 1024
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

REQUIRED_RECORD_KEYS = {
    "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP": (
        "stages", "lower_io_delta",
    ),
    "PASS_LOADED_COMPOUND_BIO": (
        "written_pages", "verified_pages", "segs_gt1", "segs_max",
        "nonzero_off", "compound_pages", "copy_fallbacks", "failed",
    ),
    "PASS_LOADED_LIVE_GC": (
        "victims", "rotations", "pages", "read_bytes", "write_bytes",
        "read_reqs", "write_reqs", "distinct", "victim_min", "victim_max",
        "last", "discards", "discard_sectors", "discard_unsupported",
        "discard_failed", "verified_pages",
    ),
    "PASS_LOADED_DISCARD_TRIM": (
        "pages", "immediate_discards", "immediate_sectors", "reuse_skips",
        "verified_pages",
    ),
    "PASS_LOADED_SUSPEND_DRAIN": (
        "retain_ms", "observed_open", "verified_pages",
    ),
    "PASS_RETAINED_SYNTHETIC_WRITE_FAULT": (
        "retain_ms", "injected", "syscall_errno", "lower_write_delta",
    ),
    "PASS_LOADED_SYNTHETIC_READ_FAULT": (
        "page", "injected", "syscall_errno", "lower_read_delta",
        "submitted_delta",
    ),
    "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT": (
        "retain_ms", "injected", "data_write_reached_lower",
    ),
    "PASS_LOADED_CODEC_ERROR_PATHS": (
        "owners", "injected", "inline_lower_write_delta",
        "submitter_lower_write_delta", "background_error_completions",
    ),
    "PASS_LOADED_COMPLETION_HANDOFF": (
        "offloaded", "verified_pages", "completed_writes", "active_after",
        "fault_offloaded", "fault_injected", "post_failure_eio",
    ),
}
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
                contents = source.read(MAX_CONFIG_CHARS + 1)
        else:
            with path.open("r", encoding="utf-8") as source:
                contents = source.read(MAX_CONFIG_CHARS + 1)
    except (OSError, UnicodeError) as error:
        raise ValueError(
            f"kernel configuration unreadable ({type(error).__name__}); "
            "next: supply a readable configuration for the running kernel"
        ) from error
    if len(contents) > MAX_CONFIG_CHARS:
        raise ValueError(
            "kernel configuration exceeds bounded parser input; "
            "next: supply a complete running-kernel configuration"
        )
    values: dict[str, str] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Z0-9_]+)=(y|m|n)", line)
        if match:
            symbol, value = match.groups()
        else:
            match = re.fullmatch(r"# (CONFIG_[A-Z0-9_]+) is not set", line)
            if match is None:
                continue
            symbol, value = match.group(1), "n"
        if symbol in values:
            raise ValueError(f"kernel configuration has duplicate symbol: {symbol}")
        values[symbol] = value
    return values


def running_kernel_release() -> str:
    try:
        result = subprocess.run(
            ["uname", "-r"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace", timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError(f"running kernel release unavailable: {error}") from error
    release = result.stdout.strip()
    if result.returncode != 0 or not release or any(
            character.isspace() for character in release):
        raise ValueError(
            f"running kernel release unavailable (exit={result.returncode})")
    return release


def host_config_path() -> Path | None:
    release = running_kernel_release()
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
        with cmdline_path.open("r", encoding="utf-8") as source:
            cmdline_contents = source.read(MAX_CMDLINE_CHARS + 1)
        if len(cmdline_contents) > MAX_CMDLINE_CHARS:
            raise ValueError("kernel command line exceeds bounded parser input")
        cmdline = cmdline_contents.split()
    except (OSError, UnicodeError, ValueError):
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


def incomplete_loaded_lane_reason(required: tuple[str, ...]) -> str | None:
    """Reject partial debug lanes independently of a feature-only probe."""
    if required in (("kasan", "lockdep"), ("kcsan",)):
        return None
    observed = ",".join(required) or "<none>"
    return (
        "required instrumentation lane incomplete: expected kasan,lockdep or "
        f"kcsan; observed {observed}; next: collect the full active pre/post "
        "lane and matching instrumented module evidence"
    )


def check_features(features: dict[str, str], required: tuple[str, ...]) -> bool:
    return all(features[name] == "DETECTED" for name in required)


def _read_runtime_text(path: Path, description: str) -> str:
    try:
        with path.open("r", encoding="utf-8") as source:
            contents = source.read(MAX_RUNTIME_SNAPSHOT_CHARS + 1)
    except (OSError, UnicodeError) as error:
        raise ValueError(
            f"{description} unreadable ({type(error).__name__}); "
            "next: capture the required live runtime evidence"
        ) from error
    if len(contents) > MAX_RUNTIME_SNAPSHOT_CHARS:
        raise ValueError(
            f"{description} exceeds bounded parser input; "
            "next: capture a complete bounded runtime snapshot"
        )
    return contents


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
            safe_key = key if re.fullmatch(r"[a-z_]{1,64}", key) else "<invalid-field>"
            raise ValueError(f"runtime snapshot has duplicate JSON key: {safe_key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"runtime snapshot contains invalid JSON constant: {value}")


def parse_runtime_snapshot(
    contents: str, required: tuple[str, ...],
) -> dict[str, object]:
    if len(contents) > MAX_RUNTIME_SNAPSHOT_CHARS:
        raise ValueError(
            "runtime snapshot exceeds bounded parser input; "
            "next: capture a complete bounded runtime snapshot"
        )
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


def _record_shape_matches(line: str, marker: str) -> bool:
    expected_keys = REQUIRED_RECORD_KEYS.get(marker)
    if expected_keys is None:
        return True
    prefix = marker + "="
    if not line.startswith(prefix):
        return False
    keys: list[str] = []
    for token in line[len(prefix):].split():
        match = re.fullmatch(r"([a-z][a-z0-9_]*):\S+", token)
        if match is None:
            return False
        keys.append(match.group(1))
    return tuple(keys) == expected_keys


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
        elif re.match(
                r"dm-swapz-\S*[ \t]*(?::=|\+=|\?=|=)", line):
            # Do not silently omit a source selected through a Kbuild form this
            # small evaluator does not understand (for example, foo-$(CONFIG)).
            # A recognized false branch cannot affect this configured build.
            if active_conditions[-1] is not False:
                raise ValueError(
                    "module Kbuild source selection is unsupported")
    else:
        raise ValueError("module Kbuild external-module section is unterminated")
    if len(active_conditions) != 1 or assignments == 0:
        raise ValueError("module Kbuild source selection is incomplete")
    if not {"dm-target.c", "codec.c", "authority.c", "engine.c",
            "predictor.c"}.issubset(sources):
        raise ValueError("module Kbuild core source selection is incomplete")
    return sources


def _checked_stage_source(
    record: str, root: Path, kdir: Path, stage_directory: Path,
) -> str | None:
    recorded = Path(record)
    source_name = recorded.name
    expected = (stage_directory / source_name).resolve()
    if recorded.is_absolute():
        candidates = (recorded,)
    else:
        # Kbuild versions differ in whether CHECK paths are relative to the
        # caller, the external-module directory, or the kernel build directory.
        candidates = (
            root / recorded,
            root / "src/kernel" / recorded,
            kdir / recorded,
            stage_directory / recorded,
        )
    return source_name if any(candidate.resolve() == expected
                              for candidate in candidates) else None


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
        print(f"BLOCKED_KERNEL_STATIC_{analyzer.upper()}: {error}", file=sys.stderr)
        return "BLOCKED", 0, {}
    check_records = CHECK_RECORD.findall(result.stdout)
    check_count, warnings = scan_static(result.stdout)
    stage_directory = (root / "build/kernel/w1").resolve()
    checked_names: list[str] = []
    unresolved_records: list[str] = []
    for record in check_records:
        source_name = _checked_stage_source(
            record, root, kdir, stage_directory)
        if source_name is None:
            unresolved_records.append(record)
        else:
            checked_names.append(source_name)
    checked_sources = set(checked_names)
    duplicated_sources = {
        name for name in checked_sources if checked_names.count(name) != 1
    }
    diagnostics = [
        line for line in result.stdout.splitlines()
        if SOURCE_DIAGNOSTIC.search(line)
    ]
    if diagnostics:
        # Source diagnostics are defects even if a separate Kbuild/tooling
        # problem also prevents a complete translation-unit inventory.
        for line in diagnostics[:16]:
            print(line, file=sys.stderr)
        if len(diagnostics) > 16:
            print(
                f"KERNEL_STATIC_DIAGNOSTICS_SUPPRESSED={len(diagnostics) - 16}",
                file=sys.stderr,
            )
    try:
        required_sources = static_required_sources(kdir)
    except ValueError as error:
        if warnings:
            print(
                f"FAIL_KERNEL_STATIC_{analyzer.upper()}: "
                f"source_diagnostics={sum(warnings.values())} "
                f"inventory_unavailable={error}",
                file=sys.stderr,
            )
            return "FAIL", check_count, warnings
        print(f"BLOCKED_KERNEL_STATIC_{analyzer.upper()}: {error}", file=sys.stderr)
        return "BLOCKED", check_count, warnings

    missing_sources = required_sources - checked_sources
    unexpected_sources = checked_sources - required_sources
    unresolved_sources = sorted({
        Path(record).name for record in unresolved_records
    })
    if warnings:
        print(
            f"FAIL_KERNEL_STATIC_{analyzer.upper()}: exit={result.returncode} "
            f"checked={sorted(checked_sources)} "
            f"missing={sorted(missing_sources)} "
            f"unexpected={sorted(unexpected_sources)} "
            f"duplicate={sorted(duplicated_sources)} "
            f"unresolved={unresolved_sources}",
            file=sys.stderr,
        )
        return "FAIL", check_count, warnings
    if (result.returncode != 0 or missing_sources or unexpected_sources or
            duplicated_sources or unresolved_records):
        print(
            f"BLOCKED_KERNEL_STATIC_{analyzer.upper()}: exit={result.returncode} "
            f"checked={sorted(checked_sources)} "
            f"missing={sorted(missing_sources)} "
            f"unexpected={sorted(unexpected_sources)} "
            f"duplicate={sorted(duplicated_sources)} "
            f"unresolved={unresolved_sources}",
            file=sys.stderr,
        )
        if result.returncode != 0 or not check_count:
            print("KERNEL_STATIC_BUILD_TAIL_BEGIN", file=sys.stderr)
            print("\n".join(result.stdout.splitlines()[-45:]), file=sys.stderr)
            print("KERNEL_STATIC_BUILD_TAIL_END", file=sys.stderr)
        return "BLOCKED", check_count, warnings
    return "PASS", check_count, warnings

def missing_debug_feature_reason(
    required: tuple[str, ...], features: dict[str, str],
    configuration: dict[str, str] | None = None,
) -> str:
    """Name the missing lane, Kconfig symbols and observable boot disable."""
    if not required:
        return "no running-kernel debug instrumentation lane selected"
    missing = []
    for feature in required:
        state = features.get(feature, "UNKNOWN")
        if state == "DETECTED":
            continue
        if state == "DISABLED_AT_BOOT":
            missing.append(f"{feature}: disabled by kasan=off on kernel command line")
            continue
        symbols = FEATURE_SYMBOLS[feature]
        unverified = [
            f"{symbol}={configuration.get(symbol, 'unknown') if configuration is not None else 'unknown'}"
            for symbol in symbols
            if configuration is None or configuration.get(symbol) != "y"
        ]
        if unverified:
            missing.append(
                f"{feature}: {state} (need "
                + ", ".join(f"{symbol}=y" for symbol in symbols)
                + "; observed " + ", ".join(unverified) + ")")
        else:
            missing.append(
                f"{feature}: {state} despite configured support; "
                "check readable boot command line and live instrumentation")
    return "; ".join(missing)


def inactive_runtime_reason(
    snapshot: dict[str, object], required: tuple[str, ...],
) -> str | None:
    """Describe each runtime switch required to make a loaded run meaningful."""
    inactive = []
    if "kcsan" in required:
        if snapshot["kcsan_enabled"] is not True:
            inactive.append("KCSAN debugfs enabled=0")
        if snapshot["kcsan_filter_default"] is not True:
            inactive.append("KCSAN blacklisted functions is not none")
    if "lockdep" in required:
        if snapshot["lockdep_debug_locks"] is not True:
            inactive.append("lockdep debug_locks=0")
        if snapshot["lockdep_prove_locking"] is not True:
            inactive.append("lockdep prove_locking=0")
    return ", ".join(inactive) if inactive else None


def _module_sha256(module: Path) -> str:
    digest = hashlib.sha256()
    with module.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_module_provenance(module: Path) -> dict[str, str]:
    """Read the actual built module, without loading it or claiming host evidence."""
    if not module.is_file():
        return {"error": "module artifact missing: expected clean-source dm-swapz.ko; "
                         "next: build and inspect the matching module"}
    evidence: dict[str, str] = {}
    try:
        evidence["sha256"] = _module_sha256(module)
    except OSError as error:
        return {"error": f"module artifact unreadable ({type(error).__name__}); "
                         "next: inspect the matching module"}
    commands = (
        ("source_sha", ("modinfo", "-F", "swapz_build_source_sha", str(module))),
        ("source_clean", ("modinfo", "-F", "swapz_build_source_clean", str(module))),
        ("vermagic", ("modinfo", "-F", "vermagic", str(module))),
        ("symbols", ("nm", "-u", str(module))),
    )
    for field, command in commands:
        if shutil.which(command[0]) is None:
            return {"error": f"module provenance tool unavailable: {command[0]}"}
        try:
            result = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                encoding="utf-8", errors="replace", timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return {"error": f"module provenance {field} unreadable "
                             f"({type(error).__name__}); next: rerun the query"}
        if result.returncode != 0:
            return {
                "error": f"module provenance {field} query failed "
                         f"(exit={result.returncode})"
            }
        evidence[field] = result.stdout.strip()
    try:
        final_sha256 = _module_sha256(module)
    except OSError as error:
        return {"error": "module artifact unreadable after provenance inspection "
                         f"({type(error).__name__}); next: recheck module bytes"}
    if final_sha256 != evidence["sha256"]:
        return {"error": "module artifact changed during provenance inspection"}
    return evidence


def kernel_diagnostic_category(line: str) -> str:
    """Report a fixed safe category, never arbitrary private dmesg content."""
    lower = line.lower()
    if "kasan:" in lower:
        return "KASAN"
    if "kcsan:" in lower:
        return "KCSAN"
    if ("locking dependency" in lower or "lock state" in lower or
            "lock freed" in lower):
        return "lockdep"
    if "warning:" in lower:
        return "WARNING"
    if "oops:" in lower or "bug:" in lower:
        return "BUG/Oops"
    return "kernel diagnostic"


def verify_owned_run(
    required: tuple[str, ...], features: dict[str, str],
    baseline: str, final: str, execution: str | None,
    runtime_before: str, runtime_after: str, source_sha: str,
    module_evidence: dict[str, str] | None = None,
    configuration: dict[str, str] | None = None,
    kernel_release: str | None = None,
    preflight_block_reason: str | None = None,
) -> tuple[str, str]:
    # Defect evidence is monotonic only when its observation is attributable
    # to this bounded run. A missing/truncated dmesg baseline is incomplete
    # evidence, not proof that an arbitrary historical warning happened here.
    # A partial baseline can match the prefix of a different final record.
    # dmesg emits complete newline-terminated records; never trust fragments.
    dmesg_contiguous = bool(
        baseline and final and baseline.endswith("\n")
        and final.startswith(baseline))
    if dmesg_contiguous:
        delta = final[len(baseline):]
        for line in delta.splitlines():
            diagnostic = KERNEL_DIAGNOSTIC.search(line)
            if diagnostic:
                # A verified in-interval kernel defect outranks later evidence
                # gaps: never demote a real splat to BLOCKED.
                return "FAIL", (
                    "kernel diagnostic in bounded dmesg: "
                    f"{kernel_diagnostic_category(line)} (content withheld); "
                    "next: investigate the authorized host kernel warning"
                )

    execution_lines = execution.splitlines() if execution is not None else []
    explicit_failures = [
        line.strip() for line in execution_lines
        if re.match(r"^[ \t]*FAIL(?::|_)", line)
    ]
    if explicit_failures:
        return "FAIL", (
            "owned lower reported FAIL: helper defect (details withheld); "
            "next: investigate the bounded owned-I/O failure"
        )

    # Parse runtime state before returning any ordinary BLOCKED reason so a
    # verified transition from active instrumentation to disabled state keeps
    # FAIL precedence even when another evidence artifact is incomplete.
    before_state: dict[str, object] | None = None
    after_state: dict[str, object] | None = None
    runtime_block_reason: str | None = None
    try:
        before_state = parse_runtime_snapshot(runtime_before, required)
    except ValueError as error:
        runtime_block_reason = f"runtime-before: {error}"
    if runtime_block_reason is None:
        try:
            after_state = parse_runtime_snapshot(runtime_after, required)
        except ValueError as error:
            runtime_block_reason = f"runtime-after: {error}"
    if runtime_block_reason is None:
        try:
            current_boot_id = _read_runtime_text(
                DEFAULT_BOOT_ID, "kernel boot identity").strip()
        except ValueError as error:
            runtime_block_reason = str(error)
    if runtime_block_reason is None:
        assert before_state is not None and after_state is not None
        if before_state["boot_id"] != current_boot_id:
            runtime_block_reason = (
                f"runtime-before boot mismatch: expected current boot {current_boot_id}, "
                "observed different valid boot ID; next: recapture the pre/post "
                "runtime snapshots and execution on one boot")
        elif after_state["boot_id"] != current_boot_id:
            runtime_block_reason = (
                f"runtime-after boot mismatch: expected current boot {current_boot_id}, "
                "observed different valid boot ID; next: recapture the pre/post "
                "runtime snapshots and execution on one boot")
        else:
            now = time.monotonic_ns()
            before_time = before_state["observed_monotonic_ns"]
            after_time = after_state["observed_monotonic_ns"]
            if not 0 < before_time < after_time <= now:
                runtime_block_reason = (
                    "runtime snapshot times are reversed, equal or in the future")
            elif now - before_time > MAX_RUNTIME_AGE_NS:
                runtime_block_reason = "runtime-before snapshot is stale (>20 minutes)"
    if runtime_block_reason is None:
        assert before_state is not None and after_state is not None
        before_inactive = inactive_runtime_reason(before_state, required)
        after_inactive = inactive_runtime_reason(after_state, required)
        if before_inactive is None and after_inactive is not None:
            return "FAIL", (
                f"debug instrumentation disabled during I/O: {after_inactive}")
    else:
        before_inactive = None
        after_inactive = None

    blocked_lines = [
        line.strip() for line in execution_lines
        if re.match(r"^[ \t]*BLOCKED(?::|_)", line)
    ]
    quarantined_lines = [
        line.strip() for line in execution_lines
        if re.match(r"^[ \t]*QUARANTINED(?::|_)", line)
    ]
    if blocked_lines:
        return "BLOCKED", (
            "owned lower reported BLOCKED: prerequisite unavailable "
            "(details withheld); next: restore the owned-helper prerequisite"
        )
    if quarantined_lines:
        return "BLOCKED", (
            "owned lower reported QUARANTINED: teardown uncertain "
            "(details withheld); next: verify clean teardown on the owner host"
        )

    # Configuration/kernel identity preflight can be unavailable while the
    # bounded artifacts still independently prove a kernel/helper failure.
    # Defer that BLOCKED reason until all independently verifiable FAIL paths
    # above have had a chance to win.
    lane_reason = incomplete_loaded_lane_reason(required)
    if lane_reason is not None:
        return "BLOCKED", lane_reason
    if preflight_block_reason is not None:
        return "BLOCKED", preflight_block_reason

    if not required or not check_features(features, required):
        return "BLOCKED", missing_debug_feature_reason(
            required, features, configuration)
    if runtime_block_reason is not None:
        return "BLOCKED", runtime_block_reason
    if before_inactive is not None:
        return "BLOCKED", (
            f"debug instrumentation inactive before I/O: {before_inactive}")
    if after_inactive is not None:
        # Both snapshots were inactive; this is missing instrumentation rather
        # than evidence that an active checker failed during the owned run.
        return "BLOCKED", (
            f"debug instrumentation inactive after I/O: {after_inactive}")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        return "BLOCKED", "validated source SHA is malformed (expected 40 hex digits)"
    if execution is None:
        return "BLOCKED", "owned execution log missing or unreadable"
    # The producer publishes its terminal BOOT_ID/PASS pair with printf.
    # A complete-looking PASS without the final newline may be a torn log.
    if not execution.endswith("\n"):
        return "BLOCKED", (
            "execution field=terminal newline phase=publication "
            "expected=complete newline-terminated log observed=truncated "
            "or unterminated; next: recapture one complete owned session")
    if kernel_release is None:
        return "BLOCKED", "running kernel release unavailable for evidence binding"

    assert before_state is not None
    expected_boot_id = str(before_state["boot_id"])
    boot_markers = [
        line for line in execution_lines
        if line.lstrip().startswith("BOOT_ID")
    ]
    expected_boot_marker = f"BOOT_ID={expected_boot_id}"
    if not boot_markers:
        return "BLOCKED", (
            f"missing execution boot marker: expected {expected_boot_marker}; "
            "observed missing; next: record the helper execution boot ID from "
            "the same boot as both runtime snapshots")
    if len(boot_markers) != 1:
        return "BLOCKED", (
            f"contradictory execution boot marker: expected {expected_boot_marker}; "
            "observed duplicate markers; next: recapture one bounded owned session")
    if boot_markers[0] != expected_boot_marker:
        observed_boot = boot_markers[0].removeprefix("BOOT_ID=")
        observed_category = (
            "different valid boot ID"
            if re.fullmatch(
                r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}",
                observed_boot,
            )
            else "missing/malformed boot ID"
        )
        return "BLOCKED", (
            f"execution boot marker mismatch: expected {expected_boot_marker}; "
            f"observed {observed_category}; next: rerun the owned helper and "
            "runtime snapshots on one boot")

    source_markers = [
        line for line in execution_lines
        if line.lstrip().startswith("SOURCE_HEAD")
    ]
    if not source_markers:
        return "BLOCKED", f"missing source run marker: SOURCE_HEAD={source_sha}"
    if len(source_markers) != 1:
        return "BLOCKED", "duplicated SOURCE_HEAD run marker"
    if source_markers[0] != f"SOURCE_HEAD={source_sha}":
        observed_source = source_markers[0].removeprefix("SOURCE_HEAD=")
        observed_category = (
            "different SHA" if re.fullmatch(r"[0-9a-f]{40}", observed_source)
            else "missing/malformed SHA"
        )
        return "BLOCKED", (
            f"source run marker mismatch: expected SOURCE_HEAD={source_sha}, "
            f"observed {observed_category}; next: rerun the validated source")

    kernel_markers = [
        line for line in execution_lines
        if line.lstrip().startswith("RUNNING_KERNEL")
    ]
    expected_kernel_marker = f"RUNNING_KERNEL={kernel_release}"
    if not kernel_markers:
        return "BLOCKED", f"missing running-kernel marker: {expected_kernel_marker}"
    if len(kernel_markers) != 1:
        return "BLOCKED", "duplicated RUNNING_KERNEL marker"
    if kernel_markers[0] != expected_kernel_marker:
        return "BLOCKED", (
            f"running-kernel marker mismatch: expected {expected_kernel_marker}, "
            "observed different/malformed release; "
            "next: rerun on the matching running kernel")

    module_hash_markers = [
        line for line in execution_lines
        if line.lstrip().startswith("MODULE_SHA256")
    ]
    if not module_hash_markers:
        return "BLOCKED", "missing module SHA256 run marker"
    if len(module_hash_markers) != 1:
        return "BLOCKED", "duplicated MODULE_SHA256 run marker"
    module_hash_match = re.fullmatch(
        r"MODULE_SHA256=([0-9a-f]{64})[ \t]+\S.*",
        module_hash_markers[0],
    )
    if module_hash_match is None:
        return "BLOCKED", "malformed MODULE_SHA256 run marker"
    executed_module_sha256 = module_hash_match.group(1)

    # Preserve the helper's explicit FAIL precedence above. An unrecognized
    # outcome/control marker is ambiguous evidence, never a clean teardown.
    # Do not inspect arbitrary stderr payloads or echo them in the result.
    unknown_failure = any(
        not line.lstrip().startswith("PASS_") and re.match(
            r"^[ \t]*(?:[A-Z][A-Z0-9_]*_)?"
            r"(?:FAIL(?:ED|URE)?|ERROR|ABORTED)(?=$|[:=_ \t])",
            line, re.IGNORECASE,
        )
        for line in execution_lines
    )
    if unknown_failure:
        return "BLOCKED", (
            "execution field=outcome phase=teardown expected=clean "
            "observed=unknown failure marker (content withheld); "
            f"source=SOURCE_HEAD:{source_sha} artifact=MODULE_SHA256:"
            f"{executed_module_sha256}; next: inspect teardown and recapture "
            "one complete owned session")

    record_positions: list[int] = []
    for record in REQUIRED_RECORDS:
        marker = record.split("=", 1)[0]
        candidates = [
            line for line in execution_lines if line.lstrip().startswith(marker)
        ]
        if not candidates:
            return "BLOCKED", f"missing loaded run marker: {marker}"
        if len(candidates) != 1:
            return "BLOCKED", f"duplicated loaded run marker: {marker}"
        if (re.fullmatch(record, candidates[0]) is None or
                not _record_shape_matches(candidates[0], marker)):
            return "BLOCKED", f"malformed loaded run marker: {marker}"
        record_positions.append(execution_lines.index(candidates[0]))

    # Match the real producer's single-session publication order: validated
    # source/kernel/module, all loaded records, then the terminal BOOT_ID/PASS
    # pair. Only the optional retained EVIDENCE locator may follow the pair.
    publication_positions = [
        execution_lines.index(source_markers[0]),
        execution_lines.index(kernel_markers[0]),
        execution_lines.index(module_hash_markers[0]),
        *record_positions[:-1],
        execution_lines.index(boot_markers[0]),
        record_positions[-1],
    ]
    terminal_position = publication_positions[-1]
    terminal_tail = execution_lines[terminal_position + 1:]
    if (publication_positions != sorted(publication_positions) or
            publication_positions[-2] + 1 != terminal_position):
        return "BLOCKED", (
            "execution field=marker order phase=publication "
            "expected=SOURCE_HEAD/RUNNING_KERNEL/MODULE_SHA256, ordered "
            "loaded records, terminal BOOT_ID/PASS pair "
            "observed=reordered or combined-session markers; "
            f"source=SOURCE_HEAD:{source_sha} artifact=MODULE_SHA256:"
            f"{executed_module_sha256}; next: capture one intact owned run")
    if terminal_tail and not (
            len(terminal_tail) == 1 and
            re.fullmatch(r"EVIDENCE=.+/session\.log", terminal_tail[0])):
        return "BLOCKED", (
            "execution field=terminal tail phase=publication "
            "expected=clean PASS followed only by optional EVIDENCE locator "
            "observed=unexpected post-publication record (content withheld); "
            f"source=SOURCE_HEAD:{source_sha} artifact=MODULE_SHA256:"
            f"{executed_module_sha256}; next: inspect teardown and recapture "
            "one intact owned run")

    if not dmesg_contiguous:
        if not baseline:
            return "BLOCKED", "dmesg baseline missing or unreadable"
        if not final:
            return "BLOCKED", "dmesg final snapshot missing or unreadable"
        return "BLOCKED", "dmesg truncated or overwritten: final lacks baseline prefix"
    if not final.endswith("\n"):
        return "BLOCKED", "dmesg final snapshot truncated mid-line"

    # The caller's validated source marker is not a substitute for modinfo,
    # exact module bytes or observable sanitizer references.
    if module_evidence is None:
        return "BLOCKED", "module provenance missing: modinfo, hash and nm evidence required"
    if "error" in module_evidence:
        return "BLOCKED", module_evidence["error"]
    observed_sha = module_evidence.get("source_sha", "<missing>")
    if observed_sha != source_sha:
        observed_category = (
            "different SHA" if isinstance(observed_sha, str) and
            re.fullmatch(r"[0-9a-f]{40}", observed_sha)
            else "missing/malformed SHA"
        )
        return "BLOCKED", (
            f"module source SHA mismatch: expected {source_sha}, "
            f"observed {observed_category}; "
            "next: inspect a clean module built from the validated source")
    if module_evidence.get("source_clean") != "1":
        return "BLOCKED", (
            "module provenance lacks clean validated source "
            "(modinfo source_clean != 1)")
    observed_module_sha256 = module_evidence.get("sha256", "<missing>")
    if observed_module_sha256 != executed_module_sha256:
        observed_category = (
            "different valid SHA256"
            if isinstance(observed_module_sha256, str) and
            re.fullmatch(r"[0-9a-f]{64}", observed_module_sha256)
            else "missing/malformed SHA256"
        )
        return "BLOCKED", (
            f"module SHA256 mismatch: expected executed module {executed_module_sha256}, "
            f"observed {observed_category}; "
            "next: inspect the exact executed module bytes")
    vermagic = module_evidence.get("vermagic", "")
    vermagic_fields = vermagic.split()
    if not vermagic_fields or vermagic_fields[0] != kernel_release:
        observed_category = (
            "different kernel release" if vermagic_fields
            else "missing kernel release"
        )
        return "BLOCKED", (
            f"module vermagic kernel mismatch: expected {kernel_release}, "
            f"observed {observed_category}; next: build the clean module for "
            "the running kernel")
    symbols = module_evidence.get("symbols", "")
    if "kasan" in required and re.search(
            r"(__asan_|__hwasan_|kasan_report)", symbols) is None:
        return "BLOCKED", "module lacks observable KASAN instrumentation references"
    if "kcsan" in required and re.search(
            r"(__tsan_|__kcsan_)", symbols) is None:
        return "BLOCKED", "module lacks observable KCSAN instrumentation references"
    return "PASS", (
        "owned RAM lower executed; runtime instrumentation remained active, "
        "module bytes/source verified and bounded dmesg clean")

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
    snapshot_parser = subcommands.add_parser("snapshot-check")
    snapshot_parser.add_argument("--require", required=True)
    snapshot_parser.add_argument("--snapshot", type=Path, required=True)
    verify_parser = subcommands.add_parser("verify")
    verify_parser.add_argument("--config", type=Path)
    verify_parser.add_argument("--cmdline", type=Path, default=Path("/proc/cmdline"))
    verify_parser.add_argument("--require", required=True)
    verify_parser.add_argument("--source-sha", required=True)
    verify_parser.add_argument("--module", type=Path, default=DEFAULT_MODULE)
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
            if (statuses["sparse"]["status"] != "PASS" or
                    statuses["smatch"]["status"] == "BLOCKED"):
                return 2
            return 0
        required = required_features(arguments.require)
        if arguments.action in {"runtime-snapshot", "snapshot-check"}:
            lane_reason = incomplete_loaded_lane_reason(required)
            if lane_reason is not None:
                raise ValueError(lane_reason)
        if arguments.action == "runtime-snapshot":
            snapshot = capture_runtime_snapshot(required)
            print(json.dumps(snapshot, sort_keys=True, separators=(",", ":")))
            return 0
        if arguments.action == "snapshot-check":
            # Reject inactive instrumentation before helper admission, not
            # merely after an otherwise clean I/O session has finished.
            snapshot = parse_runtime_snapshot(
                _read_runtime_text(
                    arguments.snapshot, "runtime-before snapshot"),
                required,
            )
            current_boot_id = _read_runtime_text(
                DEFAULT_BOOT_ID, "kernel boot identity").strip()
            if snapshot["boot_id"] != current_boot_id:
                raise ValueError("runtime-before boot mismatch")
            age = time.monotonic_ns() - snapshot["observed_monotonic_ns"]
            if not 0 <= age <= MAX_RUNTIME_AGE_NS:
                raise ValueError("runtime-before snapshot stale or in the future")
            inactive = inactive_runtime_reason(snapshot, required)
            if inactive is not None:
                print(f"BLOCKED_KERNEL_DEBUG_RUNTIME: {inactive}", file=sys.stderr)
                return 2
            return 0
        if arguments.action == "probe":
            config_path = arguments.config or host_config_path()
            features = probe(config_path, arguments.cmdline)
            print("KERNEL_DEBUG_PROBE=" + json.dumps(features, sort_keys=True))
            return 0 if check_features(features, required) else 2

        # Read independently before fallible host preflight. A real bounded
        # kernel/helper failure must remain FAIL even when Kconfig, uname or a
        # later provenance query is unavailable.
        oversized_evidence: list[str] = []

        def read_optional(path: Path, limit: int, field: str) -> str | None:
            try:
                with path.open("rb") as evidence:
                    contents = evidence.read(limit + 1)
                if len(contents) > limit:
                    oversized_evidence.append(
                        f"{field} exceeds bounded evidence input; "
                        "next: recapture the complete owned session")
                    return None
                return contents.decode("utf-8")
            except (OSError, UnicodeError):
                return None

        baseline = read_optional(arguments.baseline, MAX_DMESG_BYTES, "dmesg baseline") or ""
        final = read_optional(arguments.final, MAX_DMESG_BYTES, "dmesg final") or ""
        execution = read_optional(arguments.execution, MAX_EXECUTION_BYTES, "owned execution")
        runtime_before = read_optional(
            arguments.runtime_before, MAX_RUNTIME_SNAPSHOT_CHARS, "runtime-before") or ""
        runtime_after = read_optional(
            arguments.runtime_after, MAX_RUNTIME_SNAPSHOT_CHARS, "runtime-after") or ""

        preflight_reasons: list[str] = oversized_evidence.copy()
        config_path = arguments.config
        if config_path is None:
            try:
                config_path = host_config_path()
            except ValueError as error:
                preflight_reasons.append(str(error))
        configuration: dict[str, str] | None = None
        features = {feature: "UNKNOWN" for feature in FEATURE_SYMBOLS}
        if config_path is None:
            preflight_reasons.append(
                "running-kernel configuration unavailable")
        else:
            try:
                configuration = load_config(config_path)
                features = probe(config_path, arguments.cmdline)
            except ValueError as error:
                preflight_reasons.append(str(error))
        print("KERNEL_DEBUG_PROBE=" + json.dumps(features, sort_keys=True))

        kernel_release: str | None = None
        try:
            kernel_release = running_kernel_release()
        except ValueError as error:
            preflight_reasons.append(str(error))
        # Preserve the first actionable blocker and avoid duplicate text when
        # host_config_path() and the explicit release probe fail identically.
        preflight_block_reason = next(
            iter(dict.fromkeys(preflight_reasons)), None)

        status, reason = verify_owned_run(
            required, features, baseline, final, execution,
            runtime_before, runtime_after, arguments.source_sha,
            module_evidence=inspect_module_provenance(arguments.module),
            configuration=configuration,
            kernel_release=kernel_release,
            preflight_block_reason=preflight_block_reason,
        )
        print(f"{status}_KERNEL_DEBUG_OWNED=features:{','.join(required)} reason:{reason}")
        return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[status]
    except (ValueError, OSError, UnicodeError) as error:
        print(f"BLOCKED_KERNEL_DEBUG: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
