#!/usr/bin/env python3
"""Private make test runner: one bounded, replace-in-place, sanitized report."""
import argparse
import json
import lzma
import os
import re
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build/test_results.json.xz"
GIT_RESULT = "test_results.json.xz"
REPO = "k1moradi/swapz"
COLUMNS = ("off", "sync", "async")
# Cap values are kernel null_blk MiB/s units; request delay is nanoseconds.
# Labels describe SYNTHETIC profiles, never a real SD/SSD device.
MODEL_SPECS = {
    "sd_emulated": {"cap_mib_s": 10, "completion_nsec": 1000000, "irqmode": 2,
                    "purpose": "SYNTHETIC_LOW_BANDWIDTH_HIGH_DELAY"},
    "ssd_emulated": {"cap_mib_s": 80, "completion_nsec": 150000, "irqmode": 2,
                     "purpose": "SYNTHETIC_HIGHER_BANDWIDTH_LOWER_DELAY"},
}
MODEL_ORDER = tuple(MODEL_SPECS)
KERNEL_READ_FIELDS = ("read_meta_reqs", "read_payload_reqs",
                      "read_payload_blocks", "lower_read_wall_ns",
                      "decode_wall_ns", "read_meta_cache_hits",
                      "read_full_extent_reqs", "read_full_cache_hits",
                      "read_two_block_skips")
KERNEL_WRITE_FIELDS = ("physical_write_reqs", "lz4_wall_ns",
                       "window_sort_wall_ns", "window_commit_wall_ns",
                       "lower_write_wall_ns", "windows",
                       "write_wait_le1ms", "write_wait_1to4ms",
                       "write_wait_gt4ms")
WRITE_WAIT_BINS = ("write_wait_le1ms", "write_wait_1to4ms",
                   "write_wait_gt4ms")



def git_sha():
    cmd = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         text=True, capture_output=True, check=False)
    return cmd.stdout.strip() if cmd.returncode == 0 else "unknown"


def safe_lines(log):
    """Never put arbitrary host paths, device identities or raw JSON in report."""
    found = []
    for line in log.splitlines():
        text = line.strip()
        if text.startswith(("PASS:", "FAIL:", "BLOCKED:", "QUARANTINED:",
                            "PASS_", "BLOCKED_LOADED_QUALIFICATION")):
            label = text.split("=", 1)[0].split(":", 1)[0]
            if len(label) <= 90 and label.replace("_", "").replace("-", "").isalnum():
                found.append(label)
    return list(dict.fromkeys(found))[-20:]


def write_report(result):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2,
                         allow_nan=False).encode("utf-8") + b"\n"
    temporary = REPORT.with_name(".test_results.json.xz.tmp")
    try:
        with lzma.open(temporary, "wb", preset=6) as out:
            out.write(payload)
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)


def jobserver_fds():
    """Pass GNU Make tokens through Python into its private child builds."""
    flags = os.environ.get("MAKEFLAGS", "")
    match = re.search(r"--jobserver-auth=(\d+),(\d+)", flags)
    if not match:
        return ()
    fds = tuple(map(int, match.groups()))
    try:
        for fd in fds:
            os.fstat(fd)
    except OSError:
        return ()
    return fds


def failure_context(output):
    """Sanitized and specific; never publish raw privileged host logs.

    The diagnostic states the last completed/started *named* phase,
    plus a vetted failure category or scrubbed BLOCKED/FAIL reason.
    Synthetic output and inaccessible paths are never echoed verbatim.
    """
    phase = "preflight / administrator authorization"
    pair_number = 0
    regime = None
    for line in output.splitlines():
        if line.startswith("START_LOADED_OWNED_NULLBLK_SMOKE"):
            phase = "owned RAM kernel smoke"
        elif line.startswith("PASS_LOADED_OWNED_NULLBLK_SMOKE"):
            phase = "shared fixture allocation and workload generation"
        elif line.startswith("START_OWNED_RAM_REGIME="):
            label = line.partition("=")[2]
            if label in MODEL_ORDER:
                regime = label
        elif line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            pair_number += 1
            mode = "async" if line.rstrip().endswith("=1") else "sync"
            where = (regime + " " if regime else "")
            phase = f"owned RAM {where}comparison {pair_number}/8 ({mode})"
        elif (match := re.fullmatch(
                r"BENCH_IO_PHASE=(off|v3):(prefill|mixed|packed_read)", line)):
            phase += f" [{match.group(1)} {match.group(2)}]"
        elif line.startswith("PASS_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            phase = f"after completed owned RAM comparison {pair_number}/8"

    if "BLOCKED_LOADED_QUALIFICATION" in output:
        reason = "Noninteractive root/sudo authorization is unavailable"
    elif "QUARANTINED:" in output:
        reason = "Safety quarantine: owned device or swap identity could not be safely released"
    elif any("mktemp:" in line and "Permission denied" in line
             for line in output.splitlines()):
        reason = ("Cannot allocate the shared fixture: directory is not writable "
                  "(check build/tests permissions)")
    else:
        # A deliberately small allowlist preserves actionable errors without
        # exposing paths, UUIDs, usernames, raw JSON or system swap entries.
        reason = None
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if candidate.startswith(("BLOCKED: ", "FAIL: ")):
                msg = candidate.partition(": ")[2]
                msg = re.sub(r"(?<![A-Za-z0-9])/[^\s'\"<>]+", "[path]", msg)
                msg = re.sub(r"\b(?:[a-f0-9]{16,}|[0-9a-f]{8}-[0-9a-f-]{18,})\b",
                             "[id]", msg, flags=re.I)
                msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?", msg)
                reason = f"{candidate.split(':', 1)[0]}: {msg[:155]}"
                break
            if "PermissionError:" in candidate or "Permission denied" in candidate:
                reason = "Filesystem permissions rejected the operation"
                break
            if "FileNotFoundError:" in candidate:
                reason = "A required generated file or helper was not found"
                break
            if "AssertionError" in candidate:
                reason = "A fixture, manifest or correctness assertion failed"
                break
            if "TimeoutExpired" in candidate or "timed out" in candidate:
                reason = "Operation exceeded its bounded timeout"
                break
        if reason is None:
            reason = ("Child returned nonzero; inspect the latest local owned-device "
                      "diagnostic session under build/")
    return phase, reason


def run_stage(title, command, result, *, parse_bench=False):
    start = time.monotonic()
    try:
        proc = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8",
                              errors="replace", stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, check=False,
                              pass_fds=jobserver_fds())
        output, rc = proc.stdout, proc.returncode
    except OSError as exc:
        output, rc = type(exc).__name__, 127
    status = ("PASS" if rc == 0 else
              "BLOCKED" if rc == 2 or "BLOCKED" in output else "FAIL")
    record = {"name": title, "status": status, "elapsed_s":
              round(time.monotonic() - start, 3), "exit_code": rc}
    if rc:
        record["signals"] = safe_lines(output)
        # The sanitized report may be published via Git only.
        # Do not publish an untrusted last log line: it can contain a host
        # path, swap inventory, block-device identity or local username.
        record["failed_phase"], record["diagnostic"] = failure_context(output)
    result["stages"].append(record)
    if parse_bench:
        result["benchmarks"]["sessions"] = parse_sessions(output)
        result["benchmarks"]["verdicts"] = benchmark_verdicts(
            result["benchmarks"]["sessions"])
    print(f"  {len(result['stages']):>2}/5  {title:<29} "
          f"{status:<8} {record['elapsed_s']:>8.2f}s", flush=True)
    if rc and "diagnostic" in record:
        print(f"        Failed during: {record['failed_phase']}", flush=True)
        print(f"        Reason: {record['diagnostic']}", flush=True)
    write_report(result)
    return rc


def parse_sessions(output):
    sessions, current, regime = [], None, None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_OWNED_RAM_REGIME="):
            regime = line.partition("=")[2]
        elif line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current = {"async_prepare": int(line.rsplit("=", 1)[-1]),
                       "regime": regime, "status": "INCOMPLETE", "arms": {},
                       "order": "unknown", "device_model": None}
            sessions.append(current)
        elif current is not None and line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
        elif current is not None and line.startswith("PASS_RAM_MODEL_LOWER_MBPS="):
            match = re.fullmatch(
                r"PASS_RAM_MODEL_LOWER_MBPS=(\d+) COMPLETION_NSEC=(\d+) IRQMODE=(\d+)",
                line)
            if match:
                current["device_model"] = {
                    "cap_mib_s": int(match.group(1)),
                    "completion_nsec": int(match.group(2)),
                    "irqmode": int(match.group(3)),
                }
        elif current is not None and line.startswith(("V3_STATUS_BEFORE=", "V3_STATUS_AFTER=")):
            name = "before" if line.startswith("V3_STATUS_BEFORE=") else "after"
            status_text = line.partition("=")[2]
            allowed = ("burst_tail_flushes", "packed_early_commits",
                       "single_pack_deferrals", "accepted_burst_extensions",
                      "accepted_burst_tail_flushes", "close_pack_ready",
                       "one_page_windows", "gc_victims",
                       "gc_role_rotations")
            current.setdefault("kernel_status", {})[name] = {
                key: int(match.group(1))
                for key in allowed
                if (match := re.search(r"(?:^|\s)" + key + r"=(\d+)(?:\s|$)", status_text))
            }
        elif current is not None and line.startswith(
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current["status"] = "PASS"
        elif current is not None and line.startswith(
                "PASS_ASYNC_LOWER_IO_OVERLAP_STARTS="):
            current["overlap_starts"] = int(line.rsplit("=", 1)[-1])
        elif current is not None and line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") in ("off", "v3") and \
                    obj.get("verdict") == "PASS":
                candidate = obj["candidate"]
                rates = obj.get("throughput_mbps") or {}
                lower = obj.get("lower_io") or {}
                # Only aggregate numeric values; exclude paths, host IDs,
                # UUIDs, device serials, mounted swap inventory and timing logs.
                current["arms"][candidate] = {
                    "input_write_mbps": rates.get("logical_write_mbps"),
                    "output_lower_write_mbps": rates.get("lower_write_mbps"),
                    "swap_in_read_mbps": rates.get("logical_read_mbps"),
                    "swap_in_read_p95_ms": obj.get("read_p95_ns", 0) / 1e6,
                    "swap_in_read_p99_ms": obj.get("read_p99_ns", 0) / 1e6,
                    "write_p99_ms": obj.get("write_p99_ns", 0) / 1e6,
                    "lower_write_bytes": lower.get("lower_write_bytes"),
                    "lower_write_requests": lower.get("lower_write_requests"),
                    "lower_read_bytes": lower.get("lower_read_bytes"),
                    "lower_read_requests": lower.get("lower_read_requests"),
                    "verified_pages": obj.get("verified_pages"),
                    "logical_read_bytes": rates.get("logical_read_bytes"),
                    "logical_write_bytes": rates.get("logical_write_bytes"),
                    "seconds": obj.get("seconds"),
                    "mixed_replay_cpu_user_s": obj.get("mixed_replay_cpu_user_s"),
                    "mixed_replay_cpu_system_s": obj.get("mixed_replay_cpu_system_s"),
                    "mixed_replay_peak_rss_kb": obj.get("mixed_replay_peak_rss_kb"),
                    "kernel_write_path": obj.get("kernel_write_path"),
                    "packed_read": None,
                }
                packed = obj.get("packed_read")
                if isinstance(packed, dict):
                    measures = {}
                    for mode in ("sequential", "seeded_random"):
                        phase = packed.get("passes", {}).get(mode) or {}
                        lower_read = phase.get("lower_io") or {}
                        measures[mode] = {
                            "logical_bytes": phase.get("logical_bytes"),
                            "verified_pages": phase.get("verified_pages"),
                            "verified_image_sha256": phase.get("verified_image_sha256"),
                            "seconds": phase.get("seconds"),
                            "useful_read_mbps": phase.get("useful_read_mbps"),
                            "read_p99_ms": phase.get("read_p99_ms"),
                            "lower_read_bytes": lower_read.get("lower_read_bytes"),
                            "lower_read_requests": lower_read.get("lower_read_requests"),
                            "kernel_read_path": phase.get("kernel_read_path"),
                            "replay_cpu_user_s": phase.get("replay_cpu_user_s"),
                            "replay_cpu_system_s": phase.get("replay_cpu_system_s"),
                            "replay_peak_rss_kb": phase.get("replay_peak_rss_kb")
                        }
                    current["arms"][candidate]["packed_read"] = {
                        "logical_bytes": packed.get("logical_bytes"),
                        "logical_image_sha256": packed.get("logical_image_sha256"),
                        "packed_close_delta": packed.get("packed_close_delta"),
                        "qualification": packed.get("qualification"),
                        "passes": measures,
                    }
                if obj.get("source_sha"):
                    current["source_sha"] = obj["source_sha"]
                if obj.get("fixture_sha256"):
                    current["fixture_sha256"] = obj["fixture_sha256"]
                if obj.get("trace_sha256"):
                    current["trace_sha256"] = obj["trace_sha256"]
    return sessions


def mean(items, key):
    vals = [arm[key] for arm in items if isinstance(arm.get(key), (int, float))]
    return statistics.mean(vals) if vals else None


def benchmark_verdicts(sessions):
    """Validate 8 loaded sessions; keep capped/uncapped conclusions separate."""
    regimes = {}
    for regime in MODEL_ORDER:
        rows = [s for s in sessions if s.get("regime") == regime]
        if len(rows) != 4 or [s.get("async_prepare") for s in rows] != [0, 1, 1, 0] \
                or any(s.get("status") != "PASS" or
                       set(s.get("arms", {})) != {"off", "v3"} or
                       s.get("order") != ("v3-first" if i % 2 else "off-first")
                       for i, s in enumerate(rows)):
            return {"overall": "INCOMPLETE",
                    "reason": f"{regime}: four valid ABBA/ABAB pairs required"}
        expected = MODEL_SPECS[regime]
        for row in rows:
            actual = row.get("device_model")
            if not isinstance(actual, dict) or any(
                    actual.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: exact owned-RAM bandwidth/timer model was not verified"}
        regimes[regime] = rows
    if len(sessions) != len(MODEL_ORDER) * 4:
        return {"overall": "INCOMPLETE", "reason": "exactly eight modeled RAM-only pairs required"}
    all_rows = [row for regime in MODEL_ORDER for row in regimes[regime]]
    for row in all_rows:
        status = row.get("kernel_status", {})
        for field in ("burst_tail_flushes", "packed_early_commits",
                      "single_pack_deferrals", "accepted_burst_extensions",
                       "accepted_burst_tail_flushes", "close_pack_ready",
                      "one_page_windows", "gc_victims"):
            before = status.get("before", {}).get(field)
            after = status.get("after", {}).get(field)
            if not isinstance(before, int) or not isinstance(after, int) or after < before:
                return {"overall": "INCOMPLETE",
                        "reason": "missing or invalid kernel packed/GC counters"}
        row["kernel_counter_delta"] = {
            key: status["after"][key] - status["before"][key]
            for key in ("burst_tail_flushes", "packed_early_commits",
                        "single_pack_deferrals", "accepted_burst_extensions",
                        "accepted_burst_tail_flushes", "close_pack_ready",
                        "one_page_windows", "gc_victims")
        }
        if (row["kernel_counter_delta"]["accepted_burst_tail_flushes"] >
                row["kernel_counter_delta"]["accepted_burst_extensions"]):
            return {"overall": "INCOMPLETE",
                    "reason": "accepted-burst tail closes exceed extensions"}
    for digest in ("source_sha", "fixture_sha256", "trace_sha256"):
        vals = [row.get(digest) for row in all_rows]
        if None in vals or len(set(vals)) != 1:
            return {"overall": "INCONCLUSIVE",
                    "reason": f"benchmark {digest} differs across regimes"}

    verdicts = {}
    for regime, rows in regimes.items():
        arms = {"off": [s["arms"]["off"] for s in rows],
                "sync": [s["arms"]["v3"] for s in rows if not s["async_prepare"]],
                "async": [s["arms"]["v3"] for s in rows if s["async_prepare"]]}
        columns = {}
        keys = ("input_write_mbps", "output_lower_write_mbps",
                "swap_in_read_mbps", "swap_in_read_p99_ms",
                "write_p99_ms", "lower_write_bytes", "lower_write_requests",
                "lower_read_bytes", "lower_read_requests",
                "mixed_replay_cpu_user_s", "mixed_replay_cpu_system_s",
                "mixed_replay_peak_rss_kb")
        for name, rows_for_arm in arms.items():
            columns[name] = {key: mean(rows_for_arm, key) for key in keys}
            input_bytes = mean(rows_for_arm, "logical_write_bytes")
            backing_bytes = columns[name]["lower_write_bytes"]
            columns[name]["write_input_per_lower_byte"] = (
                input_bytes / backing_bytes if input_bytes and backing_bytes else None)
            if name != "off":
                diagnostics = [arm.get("kernel_write_path") for arm in rows_for_arm]
                if any(not isinstance(record, dict) or
                       any(type(record.get(field)) is not int or
                           record[field] < 0 for field in KERNEL_WRITE_FIELDS) or
                       sum(record[field] for field in WRITE_WAIT_BINS) !=
                           record["physical_write_reqs"]
                       for record in diagnostics):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: missing/inconsistent timed V3 C write counters"}
                for field in KERNEL_WRITE_FIELDS:
                    columns[name][f"mixed_{field}"] = statistics.mean(
                        record[field] for record in diagnostics)
            for mode in ("sequential", "seeded_random"):
                reads = [(arm.get("packed_read") or {}).get("passes", {}).get(mode)
                         for arm in rows_for_arm]
                if any(not isinstance(item, dict) or
                       item.get("logical_bytes") != 4194304 or
                       item.get("verified_pages") != 1024 or
                       not item.get("verified_image_sha256") for item in reads):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: measured 4MiB {mode} read missing"}
                columns[name][f"{mode}_4mib_s"] = statistics.mean(
                    item["seconds"] for item in reads)
                columns[name][f"{mode}_read_p99_ms"] = statistics.mean(
                    item["read_p99_ms"] for item in reads)
                columns[name][f"{mode}_lower_read_bytes"] = statistics.mean(
                    item["lower_read_bytes"] for item in reads)
                if name != "off":
                    diagnostics = [item.get("kernel_read_path") for item in reads]
                    if any(not isinstance(record, dict) or
                           any(type(record.get(field)) is not int or
                               record[field] < 0 for field in KERNEL_READ_FIELDS)
                           for record in diagnostics):
                        return {"overall": "INCOMPLETE",
                                "reason": f"{regime}: missing measured V3 {mode} C read counters"}
                    for field in KERNEL_READ_FIELDS:
                        columns[name][f"{mode}_{field}"] = statistics.mean(
                            record[field] for record in diagnostics)
            if name != "off" and any(
                    not (arm["packed_read"].get("packed_close_delta") or 0) > 0
                    for arm in rows_for_arm):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: packed-write closure not demonstrated"}

        raw = columns["off"]
        criteria = {}
        for mode in ("sync", "async"):
            paired = [s for s in rows if s["async_prepare"] == (mode == "async")]
            change = [(s["arms"]["v3"]["input_write_mbps"] /
                       s["arms"]["off"]["input_write_mbps"] - 1)
                      for s in paired]
            def decision(vals):
                return ("MATERIAL_GAIN_PRELIMINARY" if all(v >= .05 for v in vals)
                        else "MATERIAL_LOSS_PRELIMINARY" if all(v <= -.05 for v in vals)
                        else "NO_ESTABLISHED_GAIN")
            criteria[mode] = {
                "throughput_vs_raw": decision(change),
                "paired_write_gain_fraction": change,
                "lower_write_saved_fraction": (
                    1 - columns[mode]["lower_write_bytes"] / raw["lower_write_bytes"]),
                "lower_write_savings": (
                    "PASS" if all(s["arms"]["v3"]["lower_write_bytes"] <
                                  s["arms"]["off"]["lower_write_bytes"]
                                  for s in paired) else "NO_GAIN"),
                "mixed_read_p99": (
                    "LOWER" if all(s["arms"]["v3"]["swap_in_read_p99_ms"] <
                                   s["arms"]["off"]["swap_in_read_p99_ms"]
                                   for s in paired) else "NOT_LOWER"),
                "packed_4mib_sequential": (
                    "FASTER" if all(
                        s["arms"]["v3"]["packed_read"]["passes"]["sequential"]["seconds"] <
                        s["arms"]["off"]["packed_read"]["passes"]["sequential"]["seconds"]
                        for s in paired) else "NOT_FASTER"),
            }
        delta = (columns["async"]["input_write_mbps"] /
                 columns["sync"]["input_write_mbps"] - 1)
        criteria["async_vs_sync"] = {
            "write_gain_fraction": delta,
            "write_throughput": (
                "PRELIMINARY_5PCT_GAIN" if delta >= .05 else
                "PRELIMINARY_5PCT_LOSS" if delta <= -.05 else
                "NO_SIGNIFICANT_ASYNC_GAIN"),
            "caution": "Only two observations per mode; no confidence interval",
        }
        verdicts[regime] = {
            "columns": columns, "criteria": criteria,
            "device_model": MODEL_SPECS[regime],
            "interpretation": "SYNTHETIC_RAM_MODEL_ONLY_NOT_PHYSICAL_MEDIA",
            "alpha22_kernel_counters": {
                key: statistics.mean(row["kernel_counter_delta"][key]
                                     for row in rows)
                for key in ("burst_tail_flushes", "packed_early_commits",
                            "single_pack_deferrals", "accepted_burst_extensions",
                            "accepted_burst_tail_flushes", "close_pack_ready",
                            "one_page_windows", "gc_victims")
            },
        }
    return {
        "overall": "PASS_BOUNDED_RAM_MATRIX",
        "regimes": verdicts,
        "endurance": "PROXY_ONLY: lower RAM device writes, no flash endurance",
        "packed_read": "MEASURED_4MIB_QD32_NO_COLD_CACHE_PROOF",
        "gc": "NOT_EXERCISED unless separate live-GC evidence exists",
        "cpu_scope": "replay userspace process and threads; kernel DM workers NOT ATTRIBUTED",
        "physical_media": "NOT_TESTED",
        "statistical_confidence": "EXPLORATORY: two pairs per mode/regime, materiality 5%, no CI",
        "real_swap_device": "NOT_AUTHORIZED_NOT_TESTED",
    }


def print_bench(result):
    verdict = result["benchmarks"]["verdicts"]
    if verdict.get("overall") != "PASS_BOUNDED_RAM_MATRIX":
        print("  Benchmark matrix: NOT QUALIFIED "
              f"({verdict.get('reason', verdict.get('overall', 'NOT_RUN'))})")
        return
    for regime in MODEL_ORDER:
        data = verdict["regimes"][regime]
        columns = data["columns"]
        cfg = data["device_model"]
        print(f"\n  {regime.upper()} QD32 — raw vs sync vs async (two pairs/mode)")
        print(f"  MODEL: RAM null_blk cap={cfg['cap_mib_s']} MiB/s, "
              f"irqmode={cfg['irqmode']}, "
              f"completion delay={cfg['completion_nsec']} ns")
        print(f"  SCOPE: {data['interpretation']}")
        print(f"  {'Metric':<33} {'Raw off':>12} {'swapz sync':>12} {'swapz async':>12}")
        print("  " + "-" * 73)
        for title, key, unit in [
            ("Useful WRITE throughput", "input_write_mbps", "MB/s"),
            ("Backing WRITE throughput", "output_lower_write_mbps", "MB/s"),
            ("Logical/backing WRITE ratio", "write_input_per_lower_byte", "x"),
            ("Backing WRITE requests", "lower_write_requests", ""),
            ("Mixed READ throughput", "swap_in_read_mbps", "MB/s"),
            ("Mixed READ p99", "swap_in_read_p99_ms", "ms"),
            ("Verified 4MiB sequential READ", "sequential_4mib_s", "s"),
            ("Verified 4MiB random READ", "seeded_random_4mib_s", "s"),
            ("Packed sequential READ p99", "sequential_read_p99_ms", "ms"),
            ("Packed random READ p99", "seeded_random_read_p99_ms", "ms"),
            ("4MiB sequential lower READ", "sequential_lower_read_bytes", "bytes"),
            ("4MiB random lower READ", "seeded_random_lower_read_bytes", "bytes"),
            ("Replay process CPU user", "mixed_replay_cpu_user_s", "s"),
            ("Replay process CPU system", "mixed_replay_cpu_system_s", "s"),
            ("Replay process peak RSS", "mixed_replay_peak_rss_kb", "KiB"),
        ]:
            fields = []
            for mode in COLUMNS:
                val = columns[mode].get(key)
                fields.append(f"{val:.2f} {unit}".strip() if val is not None else "n/a")
            print(f"  {title:<33} {fields[0]:>12} {fields[1]:>12} {fields[2]:>12}")
        for read_mode, label in (("sequential", "sequential"),
                                 ("seeded_random", "random")):
            sync = columns["sync"]
            asynchronous = columns["async"]
            print(f"  Timed 4MiB {label} V3 READ calls (sync/async): "
                  f"metadata={sync[f'{read_mode}_read_meta_reqs']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_meta_reqs']:.1f}, "
                  f"payload={sync[f'{read_mode}_read_payload_reqs']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_payload_reqs']:.1f}, "
                  f"metadata reused={sync[f'{read_mode}_read_meta_cache_hits']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_meta_cache_hits']:.1f}, "
                  f"full 8KiB fetch={sync[f'{read_mode}_read_full_extent_reqs']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_full_extent_reqs']:.1f}, "
                  f"full reuse={sync[f'{read_mode}_read_full_cache_hits']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_full_cache_hits']:.1f}, "
                  f"4KiB second-block skips={sync[f'{read_mode}_read_two_block_skips']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_two_block_skips']:.1f}")
        sync, asynchronous = columns["sync"], columns["async"]
        print("  Timed mixed V3 C WRITE (sync/async; overlapping wall ns): "
              f"LZ4={sync['mixed_lz4_wall_ns']/1e9:.2f}/"
              f"{asynchronous['mixed_lz4_wall_ns']/1e9:.2f}s, "
              f"commit={sync['mixed_window_commit_wall_ns']/1e9:.2f}/"
              f"{asynchronous['mixed_window_commit_wall_ns']/1e9:.2f}s, "
              f"lower wait={sync['mixed_lower_write_wall_ns']/1e9:.2f}/"
              f"{asynchronous['mixed_lower_write_wall_ns']/1e9:.2f}s")
        print("  Completed lower WRITE wait bins (sync/async; <=1ms / 1–4ms / >4ms): "
              + ", ".join(
                  f"{sync[f'mixed_{field}']:.1f}/"
                  f"{asynchronous[f'mixed_{field}']:.1f}"
                  for field in WRITE_WAIT_BINS))
        for mode in ("sync", "async"):
            crit = data["criteria"][mode]
            print(f"  {mode.upper():<6} vs raw: WRITE={crit['throughput_vs_raw']}, "
                  f"lower WRITE savings={crit['lower_write_savings']}, "
                  f"packed 4MiB read={crit['packed_4mib_sequential']}")
        print(f"  ASYNC vs SYNC: "
              f"{data['criteria']['async_vs_sync']['write_throughput']}")
        kc = data["alpha22_kernel_counters"]
        print(f"  Packed-window per-pair mean: deferred first packs="
              f"{kc['single_pack_deferrals']:.1f}, "
              f"accepted-burst extensions={kc['accepted_burst_extensions']:.1f}, "
              f"accepted-burst tail closes={kc['accepted_burst_tail_flushes']:.1f}, "
              f"early pack closes={kc['close_pack_ready']:.1f}, "
              f"burst tails={kc['burst_tail_flushes']:.1f}, "
              f"one-page windows={kc['one_page_windows']:.1f}, "
              f"GC victims={kc['gc_victims']:.1f}")
    print("\n  LIMITATIONS: timer-delayed RAM models are synthetic; no physical-media claim. "
          "Two pairs per mode, no confidence interval; replay CPU"
          " excludes kernel workers; 4MiB RAM read is NOT cold SSD swap-in; "
          "live GC NOT EXERCISED.")



def code_sha():
    """Latest commit changing something other than the published report.

    source_sha is always the exact checkout HEAD tested. This extra field
    keeps identifying the code commit after Git report-only commits.
    """
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", ".",
         f":(exclude){GIT_RESULT}"],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=8)
    value = proc.stdout.strip()
    return value if proc.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else git_sha()


def git_result(command, *, data=None, timeout=15, env=None):
    """Never print Git stderr: remote URLs/credential helpers may be private."""
    try:
        return subprocess.run(["git", *command], input=data, cwd=ROOT,
                              capture_output=True, check=False, timeout=timeout,
                              env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def publish(source_sha):
    """Git-only, fast-forward report commit without changing local HEAD/index.

    The parent MUST be the same checkout commit used by the benchmark.
    The push is nonforce and touches only a root-level results blob.
    Updating the current checkout/ref here would make the user's subsequent
    loaded safety probes compare against a never-tested commit.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        return "SKIPPED_GIT_SYNC: tested source commit unavailable"
    if REPORT != ROOT / "build/test_results.json.xz" or not REPORT.is_file():
        return "SKIPPED_GIT_SYNC: canonical local report missing"

    try:
        with lzma.open(REPORT, "rt", encoding="utf-8") as stream:
            contents = json.load(stream)
        if contents.get("tested_commit_sha") != source_sha or \
                contents.get("source_sha") != source_sha:
            return "SKIPPED_GIT_SYNC: report does not match tested Git commit"
    except (OSError, ValueError, lzma.LZMAError):
        return "SKIPPED_GIT_SYNC: local compressed result is unreadable"

    def run(*args, data=None, timeout=15):
        return git_result(list(args), data=data, env=env, timeout=timeout)

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["GIT_ASKPASS"] = "false"
    env["SSH_ASKPASS"] = "false"
    env["SSH_ASKPASS_REQUIRE"] = "never"
    if not env.get("GIT_SSH_COMMAND"):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes -o ConnectTimeout=8"

    location = run("rev-parse", "--show-toplevel")
    branch = run("symbolic-ref", "--quiet", "--short", "HEAD")
    head = run("rev-parse", "HEAD")
    if any(x is None or x.returncode for x in (location, branch, head)):
        return "SKIPPED_GIT_SYNC: not an authenticated Git checkout"
    if Path(os.fsdecode(location.stdout).strip()).resolve() != ROOT or \
            branch.stdout.strip() != b"main":
        return "SKIPPED_GIT_SYNC: only the canonical main checkout may publish"
    if head.stdout.decode("ascii").strip() != source_sha:
        return "SKIPPED_GIT_SYNC: checkout changed during testing"

    remote = run("remote", "get-url", "--push", "origin")
    if remote is None or remote.returncode:
        return "SKIPPED_GIT_SYNC: Git remote origin missing"
    url = os.fsdecode(remote.stdout).strip()
    if not re.fullmatch(
            r"(?:git@github[.]com:|ssh://git@github[.]com/|https://github[.]com/)"
            r"k1moradi/swapz(?:[.]git)?", url):
        return "SKIPPED_GIT_SYNC: origin is not k1moradi/swapz"

    tracked = run("status", "--porcelain", "--untracked-files=no")
    if tracked is None or tracked.returncode or tracked.stdout.strip():
        return "SKIPPED_GIT_SYNC: tracked working tree/index is not clean"
    # Never replace an untracked file in the checkout (no checkout writes
    # happen here anyway). Report-only publication is a separate Git tree.
    path_state = run("ls-files", "--error-unmatch", "--", GIT_RESULT)
    if (ROOT / GIT_RESULT).exists() and (
            path_state is None or path_state.returncode):
        return "SKIPPED_GIT_SYNC: untracked root result file needs owner review"

    # Check authorization and concurrency BEFORE constructing a commit.
    upstream = run("ls-remote", "--exit-code", "origin", "refs/heads/main",
                   timeout=20)
    if upstream is None or upstream.returncode:
        return ("SKIPPED_GIT_SYNC: origin/main unreachable or Git credentials "
                "are unavailable; existing git push access is required")
    refs = upstream.stdout.decode("utf-8", "replace").strip().split()
    if len(refs) != 2 or refs != [source_sha, "refs/heads/main"]:
        return ("SKIPPED_GIT_SYNC: origin/main changed since testing; "
                "pull the new commit before the next run")

    blob = run("hash-object", "-w", "--no-filters", str(REPORT))
    ls_tree = run("ls-tree", "-z", source_sha)
    if any(x is None or x.returncode for x in (blob, ls_tree)):
        return "GIT_SYNC_FAILED: could not prepare Git object"
    blob_id = blob.stdout.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", blob_id):
        return "GIT_SYNC_FAILED: invalid Git report object"

    entries = []
    for item in ls_tree.stdout.split(b"\0"):
        if not item:
            continue
        try:
            meta, name = item.split(b"\t", 1)
        except ValueError:
            return "GIT_SYNC_FAILED: malformed root Git tree"
        if name != GIT_RESULT.encode("ascii"):
            entries.append(item)
    entries.append(f"100644 blob {blob_id}\t{GIT_RESULT}".encode())
    entries.sort(key=lambda item: item.split(b"\t", 1)[1])
    tree = run("mktree", "-z", data=b"\0".join(entries) + b"\0")
    if tree is None or tree.returncode:
        return "GIT_SYNC_FAILED: could not assemble report-only tree"
    tree_id = tree.stdout.decode("ascii", "replace").strip()
    message = (f"test: latest run for {source_sha[:12]} "
               "[skip ci]").encode("utf-8")
    commit = run("commit-tree", tree_id, "-p", source_sha, data=message)
    if commit is None or commit.returncode:
        return ("SKIPPED_GIT_SYNC: Git commit identity unavailable "
                "(configure git user.name/user.email)")
    report_sha = commit.stdout.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", report_sha):
        return "GIT_SYNC_FAILED: invalid report commit"

    push = run("push", "origin", f"{report_sha}:refs/heads/main", timeout=60)
    if push is None or push.returncode:
        return ("GIT_SYNC_FAILED: nonforce push rejected or inaccessible; "
                "no local branch, index or source files were changed")

    return (f"SYNCED_GIT: https://github.com/{REPO}/blob/main/{GIT_RESULT} "
            f"(report commit {report_sha[:12]}; tested {source_sha[:12]})")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kdir", required=True)
    args = parser.parse_args()
    result = {
        "schema": "swapz-test-results-v1",
        "source_sha": git_sha(),
        "tested_commit_sha": git_sha(),
        "code_commit_sha": code_sha(),
        "kernel_release": os.uname().release,
        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
        "stages": [],
        "benchmarks": {"sessions": [], "verdicts": {"overall": "NOT_RUN"}},
        "overall": "INCOMPLETE"
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.unlink(missing_ok=True)
    print("swapz: full test and benchmark qualification")
    print("  Tests are sequential; independent compilation uses Make jobserver.")
    stages = [
        ("Build module and helpers", ["make"]),
        ("Native and rootless contracts", ["bash", "tools/test-rootless.sh"]),
        ("Kernel warnings W=1", ["make", "-C", "kernel/extent-v3",
                                 f"KDIR={args.kdir}", "W=1", "all"]),
        ("Kernel warnings W=2", ["make", "-C", "kernel/extent-v3",
                                 f"KDIR={args.kdir}", "W=2", "all"]),
        ("Owned RAM smoke and 8 pairs", ["bash", "tools/test-loaded.sh"])
    ]
    exit_code = 0
    for i, (title, command) in enumerate(stages):
        if i == 0:
            command = ["make", f"KDIR={args.kdir}"]
        code = run_stage(title, command, result, parse_bench=(i == 4))
        if code:
            exit_code = code
            break
    result["overall"] = ("PASS" if not exit_code else
                         "BLOCKED" if exit_code == 2 or
                         result["stages"][-1]["status"] == "BLOCKED" else "FAIL")
    if not exit_code:
        benchmark = result["benchmarks"]["verdicts"]
        if benchmark.get("overall") == "PASS_BOUNDED_RAM_MATRIX" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("source_sha") != result["tested_commit_sha"]
                   for session in result["benchmarks"]["sessions"]):
                benchmark["overall"] = "INCONCLUSIVE"
                benchmark["reason"] = "Loaded benchmark source Git ID mismatched tested checkout"
        if benchmark.get("overall") != "PASS_BOUNDED_RAM_MATRIX":
            result["overall"] = "FAIL"
            exit_code = 1
    write_report(result)
    print_bench(result)
    print(f"\n  Overall qualification: {result['overall']}")
    print(f"  Report: {REPORT.relative_to(ROOT)} (replaced on every run)")
    print(f"  Tested Git commit: {result['tested_commit_sha']}", flush=True)
    print(f"  Code revision: {result['code_commit_sha']}", flush=True)
    notice = publish(result["tested_commit_sha"])
    print(f"  Git result: {notice}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
