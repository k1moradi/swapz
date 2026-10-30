#!/usr/bin/env python3
"""Development-only quick decision loop behind `make fast_test`.

It builds the working tree, runs the window-policy native checks and a small
single-pair subset of the owned null_blk benchmark matrix, then prints one
compact raw-versus-swapz table. Dirty trees are allowed so a policy change can
be measured before it is committed.

`make fast_test` never qualifies a source revision, never writes or publishes
test_results.json and never replaces `make test`. Its numbers are single,
unpaired observations; promotion still requires the full owner matrix.
"""
import argparse
import json
import os
import re
import runpy
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Reuse the measured replay's counter parsing/reset checks; no polling worker.
HOST_CPU = runpy.run_path(str(ROOT / "tests/runtime/benchmark/io-replay.py"))
OUT_DIR = ROOT / "build/tests/fast-test"
PAIR = "tests/tools/benchmark-owned-pair.sh"
PREFLIGHT = "tests/tools/loaded-preflight.sh"
COMMON = ["--run-owned-ram-pair", "--profile", "medium", "--retain-ms", "2",
          "--unpaced"]
# Exact device models from tests/tools/test-loaded.sh, in the bounded suffix
# order that benchmark-owned-pair.sh peels from the tail.
MODELS = {
    "sd": ["--lower-mbps", "10", "--hw-queue-depth", "1",
           "--completion-nsec", "1000000"],
    "fast": ["--lower-mbps", "80", "--hw-queue-depth", "64",
             "--completion-nsec", "150000"],
    "sdcard": ["--lower-mbps", "100", "--submit-queues", "1",
               "--hw-queue-depth", "4", "--completion-nsec", "500000"],
    "sata": ["--lower-mbps", "500", "--submit-queues", "1",
             "--hw-queue-depth", "32", "--completion-nsec", "100000"],
    "nvme4": ["--lower-mbps", "6500", "--submit-queues", "4",
              "--hw-queue-depth", "64", "--completion-nsec", "25000"],
    "nvme5": ["--lower-mbps", "12000", "--submit-queues", "4",
              "--hw-queue-depth", "64", "--completion-nsec", "14000"],
}
CONTENT_WEIGHTS = {"medium": "medium=100", "entropy": "entropy=100",
                   "balanced": "medium=50,entropy=50"}
DEFAULT_SCENARIOS = (
    "sata-mixed", "nvme4-mixed", "fast-mixed", "fast-w4", "fast-w8",
)


def quiet_host_sample():
    before = HOST_CPU["host_cpu_snapshot"]()
    time.sleep(0.2)
    return HOST_CPU["host_cpu_delta"](before, HOST_CPU["host_cpu_snapshot"]())


def performance_validity(before, after, arms):
    """Conservative development screen, not proof of an idle host or causality."""
    reasons, missing = [], False
    for label, sample in (("pre", before), ("post", after)):
        if sample.get("status") != "AVAILABLE":
            missing = True
        for field, limit, name in (("busy_fraction", .25, "busy"),
                                   ("pressure_some_fraction", .05, "CPU PSI"),
                                   ("steal_fraction", .01, "steal")):
            value = sample.get(field)
            if value is None:
                missing = True
            elif value > limit:
                reasons.append(f"{label} {name} {value:.1%}")
    # Timed CPU/PSI includes the benchmark itself; only steal is unambiguous
    # external service loss. Do not mistake target saturation for host noise.
    for label, arm in arms.items():
        sample = arm.get("host_cpu") or {}
        if sample.get("status") != "AVAILABLE":
            missing = True
        steal = sample.get("steal_fraction")
        if steal is None:
            missing = True
        elif steal > .01:
            reasons.append(f"{label} timed steal {steal:.1%}")
    noisy = bool(reasons)
    if missing:
        reasons.append("host counters unavailable")
    status = "NOISY" if noisy else "UNKNOWN" if missing else "SCREENED"
    return {"status": status, "performance_usable": status == "SCREENED",
            "reasons": reasons, "quiet_before": before, "quiet_after": after}


def reject_raw_drift(rows):
    groups = {}
    for row in rows:
        if "error" not in row:
            groups.setdefault(row["scenario"].split("#")[0], []).append(row)
    for group in groups.values():
        rates = [row["raw_w"] for row in group]
        if min(rates) <= 0:
            for row in group:
                validity = row["performance_validity"]
                if validity["status"] != "NOISY":
                    validity["status"] = "UNKNOWN"
                validity["performance_usable"] = False
                validity["reasons"].append("raw control unavailable")
            continue
        if len(rates) < 2:
            continue
        spread = max(rates) / min(rates) - 1
        if spread <= .10:
            continue
        for row in group:
            validity = row["performance_validity"]
            validity.update(status="NOISY", performance_usable=False)
            validity["reasons"].append(f"raw repeat spread {spread:.1%}")


def scenario_arguments(name, plan, delta64=1):
    model, _, kind = name.partition("-")
    if model not in MODELS or not kind:
        raise ValueError(f"unknown scenario {name!r}")
    arguments = [*COMMON, *MODELS[model]]
    if kind.startswith("w") and kind[1:] in ("1", "4", "8", "32"):
        arguments += ["--write-only-qd", kind[1:]]
    elif kind in ("mixed-lanes", "mixed-lanes-waves"):
        arguments += ["--mixed-lanes", "persistent" if kind == "mixed-lanes" else "waves"]
    elif kind != "mixed":
        raise ValueError(f"unknown scenario {name!r}")
    arguments.append("--async-prepare")
    if not delta64:
        # Suffix order of benchmark-owned-pair.sh: rescue sits after async.
        arguments.append("--no-delta64-rescue")
    return arguments + ["--shared-plan", str(plan)]


def run(command, **kwargs):
    return subprocess.run(command, cwd=ROOT, check=True, **kwargs)


def build():
    jobs = f"-j{max(1, min(os.cpu_count() or 1, 16))}"
    run(["make", jobs, "--no-print-directory"], stdout=subprocess.DEVNULL)
    run(["make", jobs, "--no-print-directory", "-C", "tests/suites",
         "test-replay-helper", "test-lower-io"], stdout=subprocess.DEVNULL)


def prepare_plan(content="medium"):
    weights = CONTENT_WEIGHTS[content]
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    plan = Path(tempfile.mkdtemp(prefix="benchmark-plan.",
                                 dir=ROOT / "build/tests"))
    replay = ["python3", "-B", "tests/runtime/benchmark/io-replay.py",
              "prepare", "--fixture", str(plan / "fixture.bin"),
              "--logical-pages", "1024", "--writer-pages", "256",
              "--reader-start", "512", "--reader-pages", "256"]
    quiet = {"stdout": subprocess.DEVNULL}
    run(["python3", "-B", "tests/runtime/benchmark/anon-page-fixture.py",
         "--output-prefix", str(plan / "fixture"), "--pages", "128",
         "--seed", "0x51a0a9", "--weights", weights], **quiet)
    run([*replay, "--output-dir", str(plan / "plan"), "--qd", "32",
         "--read-pct", "25", "--warmup-ops", "1024", "--measure-ops",
         "16384", "--iops", "0"], **quiet)
    for mode in ("waves", "persistent"):
        run([*replay, "--output-dir", str(plan / f"plan-mixed-lanes-{mode}"),
             "--qd", "32", "--read-pct", "25", "--warmup-ops", "1024",
             "--measure-ops", "16384", "--iops", "0", "--mixed-lanes", mode], **quiet)
    for qd in (1, 4, 8, 32):
        run([*replay, "--output-dir", str(plan / f"plan-write-qd{qd}"),
             "--qd", str(qd), "--read-pct", "0", "--warmup-ops", "256",
             "--measure-ops", "4096", "--iops", "0", "--sustained-write"],
            **quiet)
    return plan


def privileged(seconds, script, *arguments):
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
    return subprocess.run(
        [*prefix, "bash", "-c",
         'limit="$1"; shift; exec timeout --signal=TERM --kill-after=10s '
         '"${limit}s" bash "$@"', "swapz-fast-test", str(seconds), script,
         *arguments],
        cwd=ROOT, capture_output=True, text=True)


def parse_arms(output):
    arms = {}
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if obj.get("candidate") in ("off", "swapz") and \
                obj.get("verdict") == "PASS":
            arms[obj["candidate"]] = obj
    return arms


def summarize(name, arms, seconds):
    off, swapz = arms["off"], arms["swapz"]

    def rate(arm, key):
        return (arm.get("throughput_mbps") or {}).get(key) or 0.0

    def lower(arm, key):
        return (arm.get("lower_io") or {}).get(key) or 0

    def ms(arm, key):
        value = arm.get(key)
        return value / 1e6 if isinstance(value, (int, float)) else 0.0

    kernel = swapz.get("kernel_write_path") or {}
    windows = kernel.get("windows") or 0
    return {
        "scenario": name,
        "raw_w": rate(off, "logical_write_mbps"),
        "swapz_w": rate(swapz, "logical_write_mbps"),
        "raw_r": rate(off, "logical_read_mbps"),
        "swapz_r": rate(swapz, "logical_read_mbps"),
        "raw_lw_bytes": lower(off, "lower_write_bytes"),
        "swapz_lw_bytes": lower(swapz, "lower_write_bytes"),
        "raw_lw_reqs": lower(off, "lower_write_requests"),
        "swapz_lw_reqs": lower(swapz, "lower_write_requests"),
        "raw_r_p99": ms(off, "read_p99_ns"),
        "swapz_r_p99": ms(swapz, "read_p99_ns"),
        "raw_w_p99": ms(off, "write_p99_ns"),
        "swapz_w_p99": ms(swapz, "write_p99_ns"),
        "windows": windows,
        "deadline": kernel.get("close_deadline") or 0,
        "idle_bound": kernel.get("idle_bound_closes") or 0,
        "service_us": (kernel.get("lower_write_service_ewma_ns") or 0) / 1e3,
        "idle_ms": (kernel.get("accepted_work_lower_idle_ns") or 0) / 1e6,
        "lw_busy_ms": (kernel.get("lower_write_wall_ns") or 0) / 1e6,
        "admit_samples": kernel.get("write_admit_worker_samples") or 0,
        "admit_ms": (kernel.get("write_admit_worker_wall_ns") or 0) / 1e6,
        "worker_wall_ms": (kernel.get("ordered_worker_wall_ns") or 0) / 1e6,
        "worker_cpu_ms": (kernel.get("ordered_worker_cpu_ns") or 0) / 1e6,
        "idle_unsched_ms":
            (kernel.get("accepted_work_lower_idle_worker_unscheduled_ns") or 0) / 1e6,
        "prepare_copy_ms": sum((kernel.get(key) or 0) for key in (
            "ordered_lz4_wall_ns", "prep_lz4_wall_ns",
            "ordered_write_copy_wall_ns", "prep_write_copy_wall_ns")) / 1e6,
        "order_plan_ms": sum((kernel.get(key) or 0) for key in (
            "window_sort_wall_ns", "engine_plan_wall_ns")) / 1e6,
        "pack_crc_ms": sum((kernel.get(key) or 0) for key in (
            "engine_pack_wall_ns", "ordered_crc_wall_ns", "prep_crc_wall_ns")) / 1e6,
        "publish_ms": (kernel.get("engine_publish_wall_ns") or 0) / 1e6,
        "post_lower_ms": (kernel.get("pipeline_post_lower_wall_ns") or 0) / 1e6,
        "sync4_windows": kernel.get("sync4_windows") or 0,
        "sync4_wall_ms": (kernel.get("sync4_wall_ns") or 0) / 1e6,
        "sync4_lower_ms": (kernel.get("sync4_lower_write_ns") or 0) / 1e6,
        "sync4_nonio_ms": (kernel.get("sync4_nonio_ns") or 0) / 1e6,
        "sync4_reissue_samples": kernel.get("sync4_reissue_samples") or 0,
        "sync4_reissue_ms": (kernel.get("sync4_reissue_gap_ns") or 0) / 1e6,
        "wall_s": swapz.get("seconds") or 0.0,
        "pair_s": seconds,
    }


def pct(candidate, baseline):
    if not baseline:
        return "   n/a"
    return f"{(candidate / baseline - 1.0) * 100.0:+6.1f}%"


def print_table(rows):
    header = (f"{'scenario':<12} {'raw W':>7} {'swapz W':>8} {'dW':>7} "
              f"{'raw R':>6} {'swapz R':>7} {'lowW B':>7} {'reqs raw>swapz':>15} "
              f"{'R p99 raw>swapz':>16} {'W p99 raw>swapz':>16} "
              f"{'win':>5} {'dl':>4} {'ib':>4} {'idle':>6} {'lwbusy':>7} "
              f"{'svc':>6} {'wall':>6} {'quality':>8}")
    print(header)
    print("-" * len(header))
    for row in rows:
        if "error" in row:
            print(f"{row['scenario']:<12} ERROR: {row['error']}")
            continue
        bytes_ratio = (row["swapz_lw_bytes"] / row["raw_lw_bytes"]
                       if row["raw_lw_bytes"] else 0.0)
        reqs = f"{row['raw_lw_reqs']}>{row['swapz_lw_reqs']}"
        rp99 = f"{row['raw_r_p99']:.2f}>{row['swapz_r_p99']:.2f}"
        wp99 = f"{row['raw_w_p99']:.2f}>{row['swapz_w_p99']:.2f}"
        print(f"{row['scenario']:<12} {row['raw_w']:7.2f} {row['swapz_w']:8.2f} "
              f"{pct(row['swapz_w'], row['raw_w']):>7} {row['raw_r']:6.2f} "
              f"{row['swapz_r']:7.2f} {bytes_ratio:7.3f} {reqs:>15} "
              f"{rp99:>16} {wp99:>16} {row['windows']:5d} "
              f"{row['deadline']:4d} {row['idle_bound']:4d} {row['idle_ms']:6.1f} "
              f"{row['lw_busy_ms']:7.1f} {row['service_us']:6.0f} "
              f"{row['wall_s']:6.3f} {row['performance_validity']['status']:>8}")
        if row["performance_validity"]["reasons"]:
            print("  excluded: " + "; ".join(row["performance_validity"]["reasons"]))
    print("Legend: W/R useful MB/s; dW swapz vs raw useful WRITE; lowW B "
          "swapz/raw lower WRITE bytes (endurance proxy, lower is better);\n"
          "        reqs lower WRITE requests; p99 in ms; win/dl/ib swapz windows, "
          "deadline closes and idle-bound closes among them;\n"
          "        idle accepted-work lower-idle ms; lwbusy lower-WRITE service ms; "
          "svc lower-WRITE service EWMA us;\n"
          "        wall swapz measured seconds. "
          "Single unpaired observations; only make test qualifies.\n"
          "        quality: SCREENED passes the noise screen; NOISY/UNKNOWN "
          "excludes performance inference, not correctness.\n"
          "        200ms pre/post: busy >25%, CPU PSI >5%, steal >1%; "
          "timed steal >1% or raw-repeat spread >10% also excludes.\n"
          "        This heuristic can miss noise between samples; "
          "SCREENED does not establish an idle host.")


def print_profile(rows):
    """Compact ID114 summary; detailed per-run reports stay in latest.json."""
    groups = {}
    for row in rows:
        if "error" in row:
            continue
        groups.setdefault(row["scenario"].split("#")[0], []).append(row)

    print("\nK=1 critical-path profile (SCREENED repeats only)")
    header = (f"{'scenario':<12} {'n':>3} {'admit us':>9} {'sched diag':>10} "
              f"{'idle sched':>10} {'prep/copy':>10} {'ord/plan':>9} "
              f"{'pack/crc':>9} {'lower':>9} {'publish':>9} {'post':>8}")
    print(header)
    print("-" * len(header))
    for name, group in groups.items():
        usable = [row for row in group
                  if row["performance_validity"]["performance_usable"]]
        if not usable:
            print(f"{name:<12} {0:>3} {'excluded':>9}")
            continue

        def mean(field):
            return statistics.mean(row[field] for row in usable)

        admit_samples = sum(row["admit_samples"] for row in usable)
        admit_ms = sum(row["admit_ms"] for row in usable)
        admit_us = admit_ms * 1000.0 / admit_samples if admit_samples else 0.0
        print(f"{name:<12} {len(usable):3d} {admit_us:9.2f} "
              f"{mean('worker_cpu_ms'):10.2f} {mean('idle_unsched_ms'):10.2f} "
              f"{mean('prepare_copy_ms'):10.2f} {mean('order_plan_ms'):9.2f} "
              f"{mean('pack_crc_ms'):9.2f} {mean('lw_busy_ms'):9.2f} "
              f"{mean('publish_ms'):9.2f} {mean('post_lower_ms'):8.2f}")
    print("  admit us = accepted WRITE -> first ordered-worker ownership; "
          "idle sched = accepted lower-idle after a wake until worker entry.")
    print("  sched diag = scheduler-updated runtime deltas; pending execution may be "
          "missed or earlier execution charged at callback boundaries.")
    print("  ACK helper execution is outside these worker counters. Phase rows are partial wall time, can overlap and include preemption; "
          "neither these rows nor sched diag establishes total worker CPU.")

    sync_groups = []
    for name, group in groups.items():
        usable = [row for row in group
                  if row["performance_validity"]["performance_usable"]]
        windows = sum(row["sync4_windows"] for row in usable)
        if windows:
            sync_groups.append((name, usable, windows))
    if sync_groups:
        print("\nSynchronous four-record cycle")
        header = (f"{'scenario':<12} {'win':>6} {'cycle us':>10} "
                  f"{'lower us':>10} {'nonio us':>10} {'reissue us':>11}")
        print(header)
        print("-" * len(header))
        for name, usable, windows in sync_groups:
            wall = sum(row["sync4_wall_ms"] for row in usable)
            lower = sum(row["sync4_lower_ms"] for row in usable)
            nonio = sum(row["sync4_nonio_ms"] for row in usable)
            samples = sum(row["sync4_reissue_samples"] for row in usable)
            gaps = sum(row["sync4_reissue_ms"] for row in usable)
            print(f"{name:<12} {windows:6d} {wall * 1000.0 / windows:10.2f} "
                  f"{lower * 1000.0 / windows:10.2f} "
                  f"{nonio * 1000.0 / windows:10.2f} "
                  f"{(gaps * 1000.0 / samples if samples else 0.0):11.2f}")
        print("  reissue = previous successful synchronous four-record completion "
              "to the next successful four-record commit start.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenarios", default=os.environ.get("SCENARIOS", ""))
    parser.add_argument("--repeat", type=int,
                        default=int(os.environ.get("REPEAT", "3") or 3))
    # Delta64 rescue is the production default; DELTA64=0 measures LZ4-only.
    parser.add_argument("--delta64", type=int, choices=(0, 1),
                        default=int(os.environ.get("DELTA64", "1") or 1))
    parser.add_argument("--content", choices=tuple(CONTENT_WEIGHTS),
                        default=os.environ.get("CONTENT", "medium"))
    args = parser.parse_args()
    scenarios = [item for item in re.split(r"[,\s]+", args.scenarios) if item] \
        or list(DEFAULT_SCENARIOS)
    if not 1 <= args.repeat <= 10:
        parser.error("REPEAT must be 1..10")
    if args.content not in CONTENT_WEIGHTS:
        parser.error("CONTENT must be medium, entropy or balanced")
    for name in scenarios:
        scenario_arguments(name, "/dev/null")

    if os.geteuid() != 0 and subprocess.run(
            ["sudo", "-n", "true"], capture_output=True).returncode:
        print("BLOCKED: make fast_test needs noninteractive sudo for owned null_blk",
              file=sys.stderr)
        return 2
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "tests"],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"swapz fast_test (development only; not qualification) "
          f"content={args.content} HEAD={head[:12]}{' +dirty' if dirty else ''}")
    started = time.monotonic()
    build()
    print(f"  build + window-policy native checks: PASS "
          f"({time.monotonic() - started:.1f}s)", flush=True)
    preflight = privileged(60, PREFLIGHT)
    if preflight.returncode:
        print(preflight.stdout + preflight.stderr, file=sys.stderr)
        print("BLOCKED: loaded preflight failed", file=sys.stderr)
        return 2
    plan = prepare_plan(args.content)
    fixture = json.loads((plan / "fixture.json").read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, raw_reports = [], []
    status = 0
    try:
        for name in scenarios:
            for attempt in range(args.repeat):
                label = name if args.repeat == 1 else f"{name}#{attempt + 1}"
                quiet_before = quiet_host_sample()
                begin = time.monotonic()
                proc = privileged(720, PAIR, "--validated-source", head,
                                  *scenario_arguments(name, plan, args.delta64))
                elapsed = time.monotonic() - begin
                quiet_after = quiet_host_sample()
                arms = parse_arms(proc.stdout)
                if proc.returncode or set(arms) != {"off", "swapz"}:
                    status = 1
                    tail = (proc.stdout + proc.stderr).strip().splitlines()[-12:]
                    rows.append({"scenario": label,
                                 "error": f"pair failed rc={proc.returncode}"})
                    print(f"  {label}: FAIL ({elapsed:.1f}s)\n    " +
                          "\n    ".join(tail), flush=True)
                    continue
                row = summarize(label, arms, elapsed)
                row["performance_validity"] = performance_validity(
                    quiet_before, quiet_after, arms)
                rows.append(row)
                raw_reports.append({"scenario": label, "arms": arms})
                print(f"  {label}: raw W {row['raw_w']:.2f} swapz W "
                      f"{row['swapz_w']:.2f} ({pct(row['swapz_w'], row['raw_w']).strip()}) "
                      f"[{elapsed:.1f}s]", flush=True)
    finally:
        shutil.rmtree(plan, ignore_errors=True)
    reject_raw_drift(rows)
    (OUT_DIR / "latest.json").write_text(
        json.dumps({"head": head, "dirty": bool(dirty),
                    "delta64_rescue": args.delta64,
                    "content_profile": args.content, "fixture": fixture, "rows": rows,
                    "reports": raw_reports}, sort_keys=True) + "\n")
    print()
    print_table(rows)
    print_profile(rows)
    print(f"\n  Detailed telemetry: {(OUT_DIR / 'latest.json').relative_to(ROOT)} "
          f"(total {time.monotonic() - started:.0f}s)")
    return status


if __name__ == "__main__":
    sys.exit(main())
