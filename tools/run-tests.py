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
CLOSE_REASON_LABELS = (
    ("close_unknown", "unknown"), ("close_full", "full"),
    ("close_duplicate", "duplicate"), ("close_zero", "zero"),
    ("close_fua", "fua"), ("close_raw", "raw"),
    ("close_read_conflict", "read-conflict"),
    ("close_read_unrelated", "read-unrelated"),
    ("close_discard", "discard"), ("close_preflush", "preflush"),
    ("close_quantum", "quantum"), ("close_idle", "idle"),
    ("close_shutdown", "shutdown"), ("close_other", "other"),
    ("close_deadline", "deadline"), ("close_pack_ready", "pack-ready"),
)
CLOSE_REASON_FIELDS = tuple(field for field, _ in CLOSE_REASON_LABELS)
ONE_PAGE_CLOSE_LABELS = (
    ("win1_unknown", "unknown"), ("win1_full", "full"),
    ("win1_duplicate", "duplicate"), ("win1_zero", "zero"),
    ("win1_fua", "fua"), ("win1_raw", "raw"),
    ("win1_read_conflict", "read-conflict"),
    ("win1_read_unrelated", "read-unrelated"),
    ("win1_discard", "discard"), ("win1_preflush", "preflush"),
    ("win1_quantum", "quantum"), ("win1_idle", "idle"),
    ("win1_shutdown", "shutdown"), ("win1_other", "other"),
    ("win1_deadline", "deadline"), ("win1_pack_ready", "pack-ready"),
)
ONE_PAGE_CLOSE_FIELDS = tuple(field for field, _ in ONE_PAGE_CLOSE_LABELS)
DEADLINE_CONTEXT_LABELS = (
    ("deadline_before_bio", "before-bio"),
    ("deadline_after_read", "after-read"),
    ("deadline_worker_with_local", "worker-local"),
    ("deadline_worker_empty", "worker-empty"),
)
DEADLINE_CONTEXT_FIELDS = tuple(field for field, _ in DEADLINE_CONTEXT_LABELS)
KERNEL_READ_FIELDS = ("read_meta_reqs", "read_payload_reqs",
                      "read_payload_blocks", "lower_read_wall_ns",
                      "decode_wall_ns", "read_meta_cache_hits",
                      "read_meta_lru_hits",
                      "read_full_extent_reqs", "read_full_cache_hits",
                      "read_two_block_skips")
KERNEL_WRITE_FIELDS = ("physical_write_reqs", "lz4_wall_ns",
                       "window_sort_wall_ns", "window_commit_wall_ns",
                       "lower_write_wall_ns", "windows",
                       "write_wait_le1ms", "write_wait_1to4ms",
                       "write_wait_gt4ms")
WRITE_WAIT_BINS = ("write_wait_le1ms", "write_wait_1to4ms",
                   "write_wait_gt4ms")
BENCHMARK_PROVENANCE_FIELDS = ("source_sha", "fixture_sha256", "trace_sha256")



def git_sha():
    cmd = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         text=True, capture_output=True, check=False)
    return cmd.stdout.strip() if cmd.returncode == 0 else "unknown"


def paired_provenance_error(row, label):
    """Require exact source/fixture/trace identity within every off/V3 pair."""
    arms = row.get("arms", {})
    for field in BENCHMARK_PROVENANCE_FIELDS:
        values = [arms.get(candidate, {}).get(field)
                  for candidate in ("off", "v3")]
        if (any(not isinstance(value, str) or not value for value in values) or
                len(set(values)) != 1):
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{label}: {field} missing or differs within pair"}
        agreed_value = values[0]
        if row.get(field) is not None and row[field] != agreed_value:
            return {"overall": "INCONCLUSIVE",
                    "reason": f"{label}: {field} aggregate differs from paired arms"}
        # Preserve the existing pair-level shape only after both arms agree.
        row[field] = agreed_value
    return None


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


def parse_loaded_correctness(output):
    """Parse fixed, non-identifying owned-RAM correctness evidence."""
    patterns = {
        "oracle": re.compile(
            r"PASS_LOADED_ORACLE_PROFILE=raw_pages:(\d+) zero_pages:(\d+) "
            r"flush_calls:(\d+)$"),
        "suspend": re.compile(
            r"PASS_LOADED_SUSPEND_DRAIN=retain_ms:(\d+) "
            r"shutdown_windows:(\d+) verified_pages:(\d+)$"),
        "write_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) lower_write_delta:(\d+)$"),
        "flush_fault": re.compile(
            r"PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:(\d+) "
            r"injected:(\d+) data_write_reached_lower:(\d+)$"),
    }
    found = {}
    for line in output.splitlines():
        text = line.strip()
        for name, pattern in patterns.items():
            match = pattern.fullmatch(text)
            if match:
                found[name] = tuple(int(value) for value in match.groups())
    missing = [name for name in patterns if name not in found]
    if missing:
        return {"overall": "INCOMPLETE",
                "reason": "missing loaded correctness markers: " + ",".join(missing)}

    raw_pages, zero_pages, flush_calls = found["oracle"]
    suspend_retain, shutdown_windows, verified_pages = found["suspend"]
    write_retain, write_injected, write_lower_delta = found["write_fault"]
    flush_retain, flush_injected, flush_data_lower = found["flush_fault"]
    if raw_pages != 64 or zero_pages != 9 or flush_calls < 2:
        return {"overall": "INCOMPLETE",
                "reason": "loaded RAW/zero/flush oracle counters are inconsistent"}
    if suspend_retain != 4 or shutdown_windows < 1 or verified_pages != 128:
        return {"overall": "INCOMPLETE",
                "reason": "loaded suspend/drain evidence is incomplete"}
    if write_retain != 2 or write_injected != 1 or write_lower_delta != 0:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained WRITE fault contract failed"}
    if flush_retain != 2 or flush_injected != 1 or flush_data_lower != 1:
        return {"overall": "INCOMPLETE",
                "reason": "synthetic retained FLUSH fault contract failed"}
    return {
        "overall": "PASS",
        "raw_pages": raw_pages,
        "zero_pages": zero_pages,
        "flush_calls": flush_calls,
        "suspend_retain_ms": suspend_retain,
        "suspend_shutdown_windows": shutdown_windows,
        "suspend_verified_pages": verified_pages,
        "retained_write_fault": "PRE_SUBMISSION_EIO_ZERO_LOWER_WRITE",
        "retained_flush_fault": "PRE_SUBMISSION_FLUSH_EIO_AFTER_DATA_WRITE",
        "scope": "OWNED_RAM_NULL_BLK_SYNTHETIC_FAILURE_ONLY",
    }


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


def failure_context(output, *, loaded=True, default_phase=None):
    """Return a sanitized failure phase/reason without leaking host details.

    Loaded diagnostics track the last named owned-device phase. Earlier
    build/rootless stages retain their own stage name and must never be
    mislabeled as administrator-authorization failures.
    """
    phase = default_phase or "preflight / administrator authorization"
    pair_number = 0
    regime = None
    if loaded:
        for line in output.splitlines():
            if line.startswith("START_LOADED_OWNED_NULLBLK_SMOKE"):
                phase = "owned RAM kernel smoke"
            elif line.startswith("START_LOADED_SUSPEND_DRAIN"):
                phase = "owned RAM retained suspend/drain"
            elif line.startswith("START_LOADED_RETAINED_WRITE_FAULT"):
                phase = "owned RAM retained synthetic WRITE fault"
            elif line.startswith("START_LOADED_RETAINED_FLUSH_FAULT"):
                phase = "owned RAM retained synthetic FLUSH fault"
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

    if loaded and "BLOCKED_LOADED_QUALIFICATION" in output:
        reason = "Noninteractive root/sudo authorization is unavailable"
    elif loaded and "QUARANTINED:" in output:
        reason = "Safety quarantine: owned device or swap identity could not be safely released"
    elif loaded and any("mktemp:" in line and "Permission denied" in line
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
            if ": FAIL:" in candidate:
                msg = candidate.rsplit(": FAIL:", 1)[1].strip()
                msg = re.sub(r"[^A-Za-z0-9 .,:;()_+=/\-\[\]]", "?", msg)
                reason = f"FAIL: {msg[:155]}"
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
            reason = (("Child returned nonzero; inspect the latest local owned-device "
                       "diagnostic session under build/") if loaded else
                      "Child returned nonzero in this non-privileged stage")
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
    loaded_correctness = parse_loaded_correctness(output) if parse_bench else None
    marker_failure = (parse_bench and rc == 0 and
                      loaded_correctness.get("overall") != "PASS")
    if marker_failure:
        rc = 1
    blocked_marker = parse_bench and any(
        line.startswith(("BLOCKED:", "BLOCKED_LOADED_QUALIFICATION"))
        for line in output.splitlines())
    status = ("PASS" if rc == 0 else "BLOCKED" if blocked_marker else "FAIL")
    record = {"name": title, "status": status, "elapsed_s":
              round(time.monotonic() - start, 3), "exit_code": rc}
    if rc:
        record["signals"] = safe_lines(output)
        # The sanitized report may be published via Git only.
        # Do not publish an untrusted last log line: it can contain a host
        # path, swap inventory, block-device identity or local username.
        if marker_failure:
            record["failed_phase"] = "owned RAM lifecycle evidence"
            record["diagnostic"] = loaded_correctness["reason"]
        else:
            record["failed_phase"], record["diagnostic"] = failure_context(
                output, loaded=parse_bench,
                default_phase=None if parse_bench else title)
    result["stages"].append(record)
    if parse_bench:
        result["benchmarks"]["loaded_correctness"] = loaded_correctness
        result["benchmarks"]["sessions"] = parse_sessions(output)
        result["benchmarks"]["verdicts"] = benchmark_verdicts(
            result["benchmarks"]["sessions"])
        result["benchmarks"]["write_saturation_sessions"] = parse_write_saturation(output)
        result["benchmarks"]["write_saturation"] = write_saturation_verdict(
            result["benchmarks"]["write_saturation_sessions"])
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
        elif line.startswith("START_WRITE_SATURATION_REGIME="):
            current = None
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
                       "accepted_burst_tail_flushes", "accepted_burst_read_caps",
                       "accepted_burst_cap_extra_blocks",
                       "accepted_burst_cap_extra_gt1_windows",
                       "accepted_burst_four_extents_avoided",
                       "accepted_burst_plan_stats_failures",
                       "accepted_burst_cap3_pareto_candidates",
                       "accepted_burst_cap3_recovered_blocks",
                       "accepted_burst_cap3_full_recovery_windows",
                       "windows", "one_page_windows", "gc_victims",
                       "gc_role_rotations") + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS + DEADLINE_CONTEXT_FIELDS
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
                    "source_sha": obj.get("source_sha"),
                    "fixture_sha256": obj.get("fixture_sha256"),
                    "trace_sha256": obj.get("trace_sha256"),
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



def parse_write_saturation(output):
    """Parse only the bounded write-only QD pilot; never mix it into QD32."""
    sessions, current, regime = [], None, None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_WRITE_SATURATION_REGIME="):
            regime = line.partition("=")[2]
            current = None
        elif line.startswith("START_WRITE_SATURATION_PAIR_QD="):
            match = re.fullmatch(
                r"START_WRITE_SATURATION_PAIR_QD=(1|4|8|32) ASYNC_PREPARE=([01])",
                line)
            if not match:
                continue
            current = {
                "regime": regime, "qd": int(match.group(1)),
                "async_prepare": int(match.group(2)),
                "status": "INCOMPLETE", "order": "unknown",
                "device_model": None, "arms": {},
            }
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
        elif current is not None and line.startswith("{"):
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if obj.get("candidate") not in ("off", "v3") or obj.get("verdict") != "PASS":
                continue
            candidate = obj["candidate"]
            rates = obj.get("throughput_mbps") or {}
            lower = obj.get("lower_io") or {}
            current["arms"][candidate] = {
                "source_sha": obj.get("source_sha"),
                "fixture_sha256": obj.get("fixture_sha256"),
                "trace_sha256": obj.get("trace_sha256"),
                "input_write_mbps": rates.get("logical_write_mbps"),
                "output_lower_write_mbps": rates.get("lower_write_mbps"),
                "logical_write_bytes": rates.get("logical_write_bytes"),
                "logical_read_bytes": rates.get("logical_read_bytes"),
                "lower_write_bytes": lower.get("lower_write_bytes"),
                "lower_write_requests": lower.get("lower_write_requests"),
                "lower_read_bytes": lower.get("lower_read_bytes"),
                "lower_read_requests": lower.get("lower_read_requests"),
                "write_p99_ms": obj.get("write_p99_ns", 0) / 1e6,
                "seconds": obj.get("seconds"),
                "cpu_user_s": obj.get("mixed_replay_cpu_user_s"),
                "cpu_system_s": obj.get("mixed_replay_cpu_system_s"),
                "peak_rss_kb": obj.get("mixed_replay_peak_rss_kb"),
            }
            for field in ("source_sha", "fixture_sha256", "trace_sha256"):
                if obj.get(field):
                    current[field] = obj[field]
        elif current is not None and line.startswith("PASS_WRITE_SATURATION_PAIR_QD="):
            match = re.fullmatch(
                r"PASS_WRITE_SATURATION_PAIR_QD=(1|4|8|32) ASYNC_PREPARE=([01])",
                line)
            if match and int(match.group(1)) == current["qd"] and \
                    int(match.group(2)) == current["async_prepare"]:
                current["status"] = "PASS"
                current = None
    return sessions


def write_saturation_verdict(sessions):
    """Validate the one-pair-per-point pilot without claiming confidence."""
    expected_shape = [(qd, mode) for qd in (1, 4, 8, 32) for mode in (0, 1)]
    regimes = {}
    for regime in MODEL_ORDER:
        rows = [row for row in sessions if row.get("regime") == regime]
        shape = [(row.get("qd"), row.get("async_prepare")) for row in rows]
        if shape != expected_shape:
            return {"overall": "INCOMPLETE",
                    "reason": f"{regime}: QD1/4/8/32 sync+async pilot required"}
        expected = MODEL_SPECS[regime]
        for index, row in enumerate(rows):
            if row.get("status") != "PASS" or set(row.get("arms", {})) != {"off", "v3"}:
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: incomplete write-only pair"}
            provenance_error = paired_provenance_error(row, f"{regime}: write-only")
            if provenance_error is not None:
                return provenance_error
            if row.get("order") != ("v3-first" if index % 2 else "off-first"):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: write-only replay order mismatch"}
            model = row.get("device_model")
            if not isinstance(model, dict) or any(
                    model.get(key) != expected[key]
                    for key in ("cap_mib_s", "completion_nsec", "irqmode")):
                return {"overall": "INCOMPLETE",
                        "reason": f"{regime}: write-only device model mismatch"}
            for arm in row["arms"].values():
                required = ("input_write_mbps", "output_lower_write_mbps",
                            "logical_write_bytes", "logical_read_bytes",
                            "lower_write_bytes", "lower_write_requests",
                            "write_p99_ms", "seconds")
                if any(not isinstance(arm.get(key), (int, float)) for key in required):
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: write-only metrics missing"}
                if arm["logical_read_bytes"] != 0:
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: write-only trace contained logical reads"}
                if arm["logical_write_bytes"] <= 0 or arm["lower_write_bytes"] <= 0:
                    return {"overall": "INCOMPLETE",
                            "reason": f"{regime}: write-only byte accounting invalid"}
            if not re.fullmatch(r"[0-9a-f]{40}", row.get("source_sha", "")):
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: write-only source SHA unavailable"}
        regimes[regime] = rows
    if len(sessions) != len(MODEL_ORDER) * 8:
        return {"overall": "INCOMPLETE",
                "reason": "exactly sixteen write-only pilot pairs required"}
    if len({row["source_sha"] for row in sessions}) != 1 or \
            len({row.get("fixture_sha256") for row in sessions}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": "write-only source/fixture differs across pilot"}
    for regime, rows in regimes.items():
        for qd in (1, 4, 8, 32):
            traces = {row.get("trace_sha256") for row in rows if row["qd"] == qd}
            if None in traces or len(traces) != 1:
                return {"overall": "INCONCLUSIVE",
                        "reason": f"{regime}: QD{qd} write-only trace mismatch"}
    return {
        "overall": "PASS_WRITE_SATURATION_PILOT",
        "pairs_per_mode_qd": 1,
        "confidence": "NOT_ESTABLISHED_ONE_PAIR_PER_MODE_QD",
        "regimes": {
            regime: [{
                "qd": row["qd"],
                "mode": "async" if row["async_prepare"] else "sync",
                "raw_write_mbps": row["arms"]["off"]["input_write_mbps"],
                "v3_write_mbps": row["arms"]["v3"]["input_write_mbps"],
                "v3_to_raw_write_ratio": (
                    row["arms"]["v3"]["input_write_mbps"] /
                    row["arms"]["off"]["input_write_mbps"]),
                "v3_logical_to_lower_ratio": (
                    row["arms"]["v3"]["logical_write_bytes"] /
                    row["arms"]["v3"]["lower_write_bytes"]),
                "raw_lower_write_requests": row["arms"]["off"]["lower_write_requests"],
                "v3_lower_write_requests": row["arms"]["v3"]["lower_write_requests"],
                "raw_write_p99_ms": row["arms"]["off"]["write_p99_ms"],
                "v3_write_p99_ms": row["arms"]["v3"]["write_p99_ms"],
            } for row in rows]
            for regime, rows in regimes.items()
        },
        "interpretation": "SYNTHETIC_RAM_QD_DIRECTION_ONLY_NOT_CONFIRMATORY",
    }

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
            provenance_error = paired_provenance_error(row, f"{regime}: benchmark")
            if provenance_error is not None:
                return provenance_error
        regimes[regime] = rows
    if len(sessions) != len(MODEL_ORDER) * 4:
        return {"overall": "INCOMPLETE", "reason": "exactly eight modeled RAM-only pairs required"}
    all_rows = [row for regime in MODEL_ORDER for row in regimes[regime]]
    for row in all_rows:
        status = row.get("kernel_status", {})
        for field in ("burst_tail_flushes", "packed_early_commits",
                      "single_pack_deferrals", "accepted_burst_extensions",
                       "accepted_burst_tail_flushes", "accepted_burst_read_caps",
                       "accepted_burst_cap_extra_blocks",
                       "accepted_burst_cap_extra_gt1_windows",
                       "accepted_burst_four_extents_avoided",
                       "accepted_burst_plan_stats_failures",
                       "accepted_burst_cap3_pareto_candidates",
                       "accepted_burst_cap3_recovered_blocks",
                       "accepted_burst_cap3_full_recovery_windows",
                       "windows",
                      "one_page_windows", "gc_victims") + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS + DEADLINE_CONTEXT_FIELDS:
            before = status.get("before", {}).get(field)
            after = status.get("after", {}).get(field)
            if not isinstance(before, int) or not isinstance(after, int) or after < before:
                return {"overall": "INCOMPLETE",
                        "reason": "missing or invalid kernel packed/GC counters"}
        row["kernel_counter_delta"] = {
            key: status["after"][key] - status["before"][key]
            for key in ("burst_tail_flushes", "packed_early_commits",
                        "single_pack_deferrals", "accepted_burst_extensions",
                        "accepted_burst_tail_flushes", "accepted_burst_read_caps",
                        "accepted_burst_cap_extra_blocks",
                        "accepted_burst_cap_extra_gt1_windows",
                        "accepted_burst_four_extents_avoided",
                        "accepted_burst_plan_stats_failures",
                        "accepted_burst_cap3_pareto_candidates",
                        "accepted_burst_cap3_recovered_blocks",
                        "accepted_burst_cap3_full_recovery_windows",
                        "windows",
                        "one_page_windows", "gc_victims") + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS + DEADLINE_CONTEXT_FIELDS
        }
        if sum(row["kernel_counter_delta"][field]
               for field in CLOSE_REASON_FIELDS) != \
                row["kernel_counter_delta"]["windows"]:
            return {"overall": "INCOMPLETE",
                    "reason": "window close-reason accounting is inconsistent"}
        if sum(row["kernel_counter_delta"][field]
               for field in ONE_PAGE_CLOSE_FIELDS) != \
                row["kernel_counter_delta"]["one_page_windows"]:
            return {"overall": "INCOMPLETE",
                    "reason": "one-page close-reason accounting is inconsistent"}
        if sum(row["kernel_counter_delta"][field]
               for field in DEADLINE_CONTEXT_FIELDS) != \
                row["kernel_counter_delta"]["close_deadline"]:
            return {"overall": "INCOMPLETE",
                    "reason": "deadline-context accounting is inconsistent"}
        if (row["kernel_counter_delta"]["accepted_burst_tail_flushes"] >
                row["kernel_counter_delta"]["accepted_burst_extensions"]):
            return {"overall": "INCOMPLETE",
                    "reason": "accepted-burst tail closes exceed extensions"}
        if (row["kernel_counter_delta"]["accepted_burst_read_caps"] >
                row["kernel_counter_delta"]["accepted_burst_extensions"]):
            return {"overall": "INCOMPLETE",
                    "reason": "accepted-burst read caps exceed extensions"}
        if (row["kernel_counter_delta"]["accepted_burst_cap_extra_gt1_windows"] >
                row["kernel_counter_delta"]["accepted_burst_read_caps"]):
            return {"overall": "INCOMPLETE",
                    "reason": "accepted-burst >1-block windows exceed capped windows"}
        if row["kernel_counter_delta"]["accepted_burst_plan_stats_failures"]:
            return {"overall": "INCOMPLETE",
                    "reason": "accepted-burst planner telemetry failed"}
        cap3_recovered = row["kernel_counter_delta"]["accepted_burst_cap3_recovered_blocks"]
        cap3_full = row["kernel_counter_delta"]["accepted_burst_cap3_full_recovery_windows"]
        cap3_candidates = row["kernel_counter_delta"]["accepted_burst_cap3_pareto_candidates"]
        expensive = row["kernel_counter_delta"]["accepted_burst_cap_extra_gt1_windows"]
        if cap3_full > expensive:
            return {"overall": "INCOMPLETE",
                    "reason": "cap=3 full-recovery windows exceed expensive cap=2 tail"}
        if cap3_candidates > cap3_full:
            return {"overall": "INCOMPLETE",
                    "reason": "cap=3 Pareto candidates exceed full-recovery windows"}
        if cap3_recovered < 2 * cap3_full or \
                cap3_recovered > row["kernel_counter_delta"]["accepted_burst_cap_extra_blocks"]:
            return {"overall": "INCOMPLETE",
                    "reason": "cap=3 recovered-block accounting is inconsistent"}
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
                columns[name][f"{mode}_lower_read_requests"] = statistics.mean(
                    item["lower_read_requests"] for item in reads)
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
                            "accepted_burst_tail_flushes", "accepted_burst_read_caps",
                            "accepted_burst_cap_extra_blocks",
                            "accepted_burst_cap_extra_gt1_windows",
                            "accepted_burst_four_extents_avoided",
                            "accepted_burst_plan_stats_failures",
                            "accepted_burst_cap3_pareto_candidates",
                            "accepted_burst_cap3_recovered_blocks",
                            "accepted_burst_cap3_full_recovery_windows",
                            "windows",
                            "one_page_windows", "gc_victims") + CLOSE_REASON_FIELDS + ONE_PAGE_CLOSE_FIELDS + DEADLINE_CONTEXT_FIELDS
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
        print(f"  {'Metric':<37} {'Raw off':>12} {'swapz sync':>12} {'swapz async':>12}")
        print("  " + "-" * 76)
        for title, key in [
            ("Useful WRITE throughput (MB/s)", "input_write_mbps"),
            ("Backing WRITE throughput (MB/s)", "output_lower_write_mbps"),
            ("Logical/backing WRITE ratio (x)", "write_input_per_lower_byte"),
            ("Backing WRITE requests", "lower_write_requests"),
            ("Mixed READ throughput (MB/s)", "swap_in_read_mbps"),
            ("Mixed READ p99 (ms)", "swap_in_read_p99_ms"),
            ("Verified 4MiB sequential READ (s)", "sequential_4mib_s"),
            ("Verified 4MiB random READ (s)", "seeded_random_4mib_s"),
            ("Packed sequential READ p99 (ms)", "sequential_read_p99_ms"),
            ("Packed random READ p99 (ms)", "seeded_random_read_p99_ms"),
            ("4MiB sequential lower READ (bytes)", "sequential_lower_read_bytes"),
            ("4MiB random lower READ (bytes)", "seeded_random_lower_read_bytes"),
            ("4MiB sequential lower READ requests", "sequential_lower_read_requests"),
            ("4MiB random lower READ requests", "seeded_random_lower_read_requests"),
            ("Replay process CPU user (s)", "mixed_replay_cpu_user_s"),
            ("Replay process CPU system (s)", "mixed_replay_cpu_system_s"),
            ("Replay process peak RSS (KiB)", "mixed_replay_peak_rss_kb"),
        ]:
            fields = []
            for mode in COLUMNS:
                val = columns[mode].get(key)
                fields.append(f"{val:.2f}" if val is not None else "n/a")
            print(f"  {title:<37} {fields[0]:>12} {fields[1]:>12} {fields[2]:>12}")
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
                  f"LRU64 reused={sync[f'{read_mode}_read_meta_lru_hits']:.1f}/"
                  f"{asynchronous[f'{read_mode}_read_meta_lru_hits']:.1f}, "
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
              f"read-capped accepted windows={kc['accepted_burst_read_caps']:.1f}, "
              f"cap extra 4KiB blocks={kc['accepted_burst_cap_extra_blocks']:.1f}, "
              f"cap >1-block windows={kc['accepted_burst_cap_extra_gt1_windows']:.1f}, "
              f"16KiB extents avoided={kc['accepted_burst_four_extents_avoided']:.1f}, "
              f"cap3 recovered blocks={kc['accepted_burst_cap3_recovered_blocks']:.1f}, "
              f"cap3 full-recovery windows={kc['accepted_burst_cap3_full_recovery_windows']:.1f}, "
              f"cap3 Pareto candidates={kc['accepted_burst_cap3_pareto_candidates']:.1f}, "
              f"early pack closes={kc['close_pack_ready']:.1f}, "
              f"burst tails={kc['burst_tail_flushes']:.1f}, "
              f"one-page windows={kc['one_page_windows']:.1f}, "
              f"GC victims={kc['gc_victims']:.1f}")
        closes = ", ".join(
            f"{label}={kc[field]:.1f}"
            for field, label in CLOSE_REASON_LABELS if kc[field])
        print("  All-window close reasons per-pair mean: " + (closes or "none"))
        win1 = ", ".join(
            f"{label}={kc[field]:.1f}"
            for field, label in ONE_PAGE_CLOSE_LABELS if kc[field])
        print("  One-page close reasons per-pair mean: " + (win1 or "none"))
        deadline = ", ".join(
            f"{label}={kc[field]:.1f}"
            for field, label in DEADLINE_CONTEXT_LABELS if kc[field])
        print("  Deadline closure contexts per-pair mean: " +
              (deadline or "none"))
    loaded = result["benchmarks"].get("loaded_correctness", {})
    if loaded.get("overall") == "PASS":
        print("\n  Loaded lifecycle: "
              f"RAW={loaded['raw_pages']}, zero={loaded['zero_pages']}, "
              f"flushes={loaded['flush_calls']}; retain="
              f"{loaded['suspend_retain_ms']}ms suspend/drain closed "
              f"{loaded['suspend_shutdown_windows']} window(s) and verified "
              f"{loaded['suspend_verified_pages']} pages; retained synthetic "
              "WRITE/FLUSH faults failed closed.")

    print("\n  LIMITATIONS: timer-delayed RAM models are synthetic; no physical-media claim. "
          "Two pairs per mode, no confidence interval; replay CPU"
          " excludes kernel workers; 4MiB RAM read is NOT cold SSD swap-in; "
          "live GC NOT EXERCISED.")

    saturation = result["benchmarks"].get("write_saturation", {})
    if saturation.get("overall") == "PASS_WRITE_SATURATION_PILOT":
        print("\n  WRITE-ONLY SATURATION PILOT — one pair per mode/QD; NOT confirmatory")
        for regime in MODEL_ORDER:
            cfg = MODEL_SPECS[regime]
            print(f"  {regime.upper()} cap={cfg['cap_mib_s']} MiB/s "
                  f"completion={cfg['completion_nsec']} ns")
            print("  QD  mode    raw MB/s    V3 MB/s   V3/raw  logical/lower  "
                  "raw reqs  V3 reqs  raw p99ms  V3 p99ms")
            for point in saturation["regimes"][regime]:
                print(f"  {point['qd']:>2}  {point['mode']:<5} "
                      f"{point['raw_write_mbps']:>10.2f} "
                      f"{point['v3_write_mbps']:>10.2f} "
                      f"{point['v3_to_raw_write_ratio']:>8.3f} "
                      f"{point['v3_logical_to_lower_ratio']:>14.3f} "
                      f"{point['raw_lower_write_requests']:>9.0f} "
                      f"{point['v3_lower_write_requests']:>8.0f} "
                      f"{point['raw_write_p99_ms']:>10.2f} "
                      f"{point['v3_write_p99_ms']:>9.2f}")
        print("  PILOT LIMITATION: one pair per mode/QD; no confidence interval "
              "and no confirmatory performance verdict.")
    else:
        print("\n  Write-only saturation pilot: NOT QUALIFIED "
              f"({saturation.get('reason', saturation.get('overall', 'NOT_RUN'))})")



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
        "benchmarks": {"sessions": [], "verdicts": {"overall": "NOT_RUN"},
                       "loaded_correctness": {"overall": "NOT_RUN"},
                       "write_saturation_sessions": [],
                       "write_saturation": {"overall": "NOT_RUN"}},
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
        ("Owned RAM smoke + mixed/QD pilot", ["bash", "tools/test-loaded.sh"])
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
        saturation = result["benchmarks"]["write_saturation"]
        if saturation.get("overall") == "PASS_WRITE_SATURATION_PILOT" and \
                re.fullmatch(r"[0-9a-f]{40}", result["tested_commit_sha"]):
            if any(session.get("source_sha") != result["tested_commit_sha"]
                   for session in result["benchmarks"]["write_saturation_sessions"]):
                saturation["overall"] = "INCONCLUSIVE"
                saturation["reason"] = "Write-only pilot source Git ID mismatched tested checkout"
        if benchmark.get("overall") != "PASS_BOUNDED_RAM_MATRIX" or \
                saturation.get("overall") != "PASS_WRITE_SATURATION_PILOT":
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
