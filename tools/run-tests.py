#!/usr/bin/env python3
"""Private make test runner: one bounded, replace-in-place, sanitized report."""
import argparse
import hashlib
import json
import lzma
import os
import re
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "build/test_results.json.xz"
RELEASE = "test-results"
REPO = "k1moradi/swapz"
COLUMNS = ("off", "sync", "async")


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
        # The report is optionally published on a public GitHub Release.
        # Do not publish an untrusted last log line: it can contain a host
        # path, swap inventory, block-device identity or local username.
        record["diagnostic"] = (
            "Noninteractive privilege unavailable" if
            "BLOCKED_LOADED_QUALIFICATION" in output else
            "Private stage failed; review the local diagnostic session logs")
    result["stages"].append(record)
    if parse_bench:
        result["benchmarks"]["sessions"] = parse_sessions(output)
        result["benchmarks"]["verdicts"] = benchmark_verdicts(
            result["benchmarks"]["sessions"])
    print(f"  {len(result['stages']):>2}/5  {title:<29} "
          f"{status:<8} {record['elapsed_s']:>8.2f}s", flush=True)
    if rc and "diagnostic" in record:
        print(f"        {record['diagnostic']}", flush=True)
    write_report(result)
    return rc


def parse_sessions(output):
    sessions, current = [], None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("START_OWNED_RAM_PAIR_ASYNC_PREPARE="):
            current = {"async_prepare": int(line.rsplit("=", 1)[-1]),
                       "status": "INCOMPLETE", "arms": {},
                       "order": "unknown"}
            sessions.append(current)
        elif current is not None and line.startswith("REPLAY_ORDER="):
            current["order"] = line.partition("=")[2].strip()
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
    valid = [s for s in sessions if s.get("status") == "PASS" and
             set(s.get("arms", {})) == {"off", "v3"}]
    if len(valid) != 4 or [s["async_prepare"] for s in valid] != [0, 1, 1, 0]:
        return {"overall": "INCOMPLETE", "reason": "Four valid ABBA sessions required"}

    if len({s.get("source_sha") for s in valid}) != 1 or \
            len({s.get("fixture_sha256") for s in valid}) != 1 or \
            len({s.get("trace_sha256") for s in valid}) != 1:
        return {"overall": "INCONCLUSIVE",
                "reason": "Source, fixture or workload traces differ"}

    groups = {"off": [s["arms"]["off"] for s in valid],
              "sync": [s["arms"]["v3"] for s in valid if not s["async_prepare"]],
              "async": [s["arms"]["v3"] for s in valid if s["async_prepare"]]}
    cols = {}
    for group, arms in groups.items():
        cols[group] = {k: mean(arms, k) for k in (
            "input_write_mbps", "output_lower_write_mbps",
            "swap_in_read_mbps", "swap_in_read_p95_ms", "swap_in_read_p99_ms",
            "write_p99_ms", "lower_write_bytes", "lower_write_requests",
            "lower_read_bytes", "lower_read_requests")}
        rd = cols[group]["swap_in_read_mbps"]
        cols[group]["swap_in_100mb_estimate_s"] = (
            100.0 / rd if rd and rd > 0 else None)
        wr = cols[group]["input_write_mbps"]
        phy = cols[group]["lower_write_bytes"]
        inp = mean(arms, "logical_write_bytes")
        cols[group]["write_input_per_lower_byte"] = (
            inp / phy if phy and inp else None)

    base = cols["off"]
    verdicts = {}
    for key in ("sync", "async"):
        arm = cols[key]
        raw_matching = [s for s in valid if (s["async_prepare"] == (key == "async"))]
        verdicts[key] = {
            "write_throughput_vs_raw": "PASS" if all(
                s["arms"]["v3"]["input_write_mbps"] >
                s["arms"]["off"]["input_write_mbps"] for s in raw_matching) else "NO_GAIN",
            "lower_write_bytes_vs_raw": "PASS" if all(
                s["arms"]["v3"]["lower_write_bytes"] <
                s["arms"]["off"]["lower_write_bytes"] for s in raw_matching) else "NO_GAIN",
            "swap_in_p99_vs_raw": "PASS" if all(
                s["arms"]["v3"]["swap_in_read_p99_ms"] <
                s["arms"]["off"]["swap_in_read_p99_ms"] for s in raw_matching) else "NO_GAIN",
            "lower_write_saved_fraction": (
                1 - arm["lower_write_bytes"] / base["lower_write_bytes"]),
            "write_throughput_gain_fraction": (
                arm["input_write_mbps"] / base["input_write_mbps"] - 1),
        }
    verdicts["async_vs_sync"] = {
        "write_throughput": (
            "PASS" if cols["async"]["input_write_mbps"] >
            cols["sync"]["input_write_mbps"] else "NO_GAIN"),
        "swap_in_p99": (
            "PASS" if cols["async"]["swap_in_read_p99_ms"] <
            cols["sync"]["swap_in_read_p99_ms"] else "NO_GAIN"),
        "comparison_note": "Two sync and two async repetitions; not proof of significance",
    }
    return {
        "overall": "PASS_BOUNDED_RAM_PILOT",
        "columns": cols, "criteria": verdicts,
        "endurance": "PROXY_ONLY: reduced RAM-backed lower writes, not SSD endurance",
        "read_100mb": "Estimated under mixed 25%-read QD32 traffic, NOT a cold isolated swap-in test",
        "gc": "NOT_EXERCISED unless separately proven by loaded GC counters",
        "physical_media": "NOT_TESTED",
        "cpu_memory": "NOT_MEASURED",
    }


def print_bench(result):
    verdict = result["benchmarks"]["verdicts"]
    cols = verdict.get("columns")
    if not cols:
        print("  Benchmark comparison: NOT AVAILABLE "
              f"({verdict.get('overall', 'NOT_RUN')})")
        return
    print("\n  Benchmarks, averaged over four owned RAM-backed sessions")
    print(f"  {'Metric':<34} {'Raw off':>11} {'swapz sync':>12} {'swapz async':>12}")
    print("  " + "-" * 73)
    for title, key, unit in [
        ("Useful swap-out input", "input_write_mbps", "MB/s"),
        ("Backing write output", "output_lower_write_mbps", "MB/s"),
        ("Write input/backing ratio", "write_input_per_lower_byte", "x"),
        ("Lower write requests", "lower_write_requests", ""),
        ("Swap-in read throughput", "swap_in_read_mbps", "MB/s"),
        ("Estimated 100 MB swap-in time", "swap_in_100mb_estimate_s", "s"),
        ("Swap-in read p99", "swap_in_read_p99_ms", "ms"),
    ]:
        fields = []
        for name in COLUMNS:
            v = cols[name].get(key)
            fields.append(f"{v:.2f} {unit}".strip() if v is not None else "n/a")
        print(f"  {title:<34} {fields[0]:>11} {fields[1]:>12} {fields[2]:>12}")
    for mode in ("sync", "async"):
        v = verdict["criteria"][mode]
        print(f"  {mode.upper():<6} throughput/raw={v['write_throughput_vs_raw']} "
              f"lower-write-savings={v['lower_write_bytes_vs_raw']} "
              f"read-p99/raw={v['swap_in_p99_vs_raw']}")
    a = verdict["criteria"]["async_vs_sync"]
    print(f"  ASYNC vs SYNC: write throughput={a['write_throughput']}, "
          f"swap-in p99={a['swap_in_p99']}")
    print("  NOTE: 100 MB read times are mixed-load estimates; physical "
          "endurance, CPU and GC are NOT QUALIFIED.")


def publish():
    """Never change main/checkout. Replace one asset at a fixed Release URL."""
    origin = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    branch = subprocess.run(["git", "branch", "--show-current"],
                            cwd=ROOT, capture_output=True, text=True, check=False)
    if origin.returncode or Path(origin.stdout.strip()).resolve() != ROOT or \
            branch.stdout.strip() != "main":
        return "SKIPPED: not the canonical main checkout (sandbox protected)"
    if not shutil.which("gh"):
        return "SKIPPED: GitHub CLI not installed (no API authorization found)"
    auth = subprocess.run(["gh", "auth", "status"],
                          cwd=ROOT, capture_output=True, text=True, timeout=12)
    if auth.returncode:
        return "SKIPPED: no authenticated GitHub API session"
    env = os.environ.copy()
    env["GH_PROMPT_DISABLED"] = "1"
    common = ["--repo", REPO]
    try:
        check = subprocess.run(["gh", "release", "view", RELEASE, *common],
                               env=env, capture_output=True, text=True, timeout=20)
        if check.returncode:
            created = subprocess.run(
                ["gh", "release", "create", RELEASE, *common, "--target", "main",
                 "--title", "swapz latest test results",
                 "--notes", "Automatically overwritten latest owner-approved "
                            "RAM-only test report; not production qualification.",
                 "--latest=false"],
                env=env, capture_output=True, text=True, timeout=30)
            if created.returncode:
                return "UPLOAD_FAILED: could not create stable test-results release"
        upload = subprocess.run(
            ["gh", "release", "upload", RELEASE, str(REPORT), "--clobber", *common],
            env=env, capture_output=True, text=True, timeout=60)
        if upload.returncode:
            return "UPLOAD_FAILED: GitHub Release asset update rejected"
        return ("UPLOADED: https://github.com/" + REPO +
                "/releases/download/" + RELEASE + "/test_results.json.xz")
    except (OSError, subprocess.TimeoutExpired):
        return "UPLOAD_FAILED: GitHub authorization or network timed out"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kdir", required=True)
    args = parser.parse_args()
    result = {
        "schema": "swapz-test-results-v1",
        "source_sha": git_sha(),
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
        ("Owned RAM smoke and 4 pairs", ["bash", "tools/test-loaded.sh"])
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
        if benchmark.get("overall") != "PASS_BOUNDED_RAM_PILOT":
            result["overall"] = "FAIL"
            exit_code = 1
    write_report(result)
    print_bench(result)
    print(f"\n  Overall qualification: {result['overall']}")
    print(f"  Report: {REPORT.relative_to(ROOT)} (replaced on every run)")
    notice = publish()
    print(f"  GitHub report: {notice}", flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
