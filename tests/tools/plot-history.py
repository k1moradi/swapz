#!/usr/bin/env python3
"""Private round-closeout plots from separately selected owner reports.

This is descriptive history, not qualification or a cross-source causal A/B.
No devices, Git mutations, report publication or new public Make goal.
Matplotlib is imported only for rendering, outside rootless parser tests.
"""
import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Shared with the make-test reporter; resolvable however this file is loaded.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from product_goals import (  # noqa: E402
    DEVICE_BOUND, GUARD_FLOOR_PCT, MIXED, PERSISTENT, TARGETS, change,
    goal_for, report_points, scorecard, service_floor_pct)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/history/arm64-neon"


def host_matches(report, online_cpus=7, backend="neon"):
    backends = report.get("evidence", {}).get("predictor", {}).get(
        "backend_benchmarks", []) or []
    cpus = {(arm.get("host_cpu") or {}).get("online_cpus")
            for session in report.get("benchmarks", {}).get("sessions", [])
            for arm in (session.get("arms") or {}).values()
            if (arm.get("host_cpu") or {}).get("online_cpus") is not None}
    return any(row.get("name") == backend for row in backends) and cpus == {online_cpus}


def validate_host_profile(profile):
    """x86 cohorts require an audited immutable report allowlist, not ISA guessing."""
    if not isinstance(profile, dict) or not re.fullmatch(
            r"x86-[a-z0-9-]+", str(profile.get("id", ""))) or \
            not isinstance(profile.get("title"), str) or \
            not profile["title"].strip() or "\n" in profile["title"] or \
            type(profile.get("online_cpus")) is not int or profile["online_cpus"] < 1 or \
            not re.fullmatch(r"[0-9a-f]{64}", str(profile.get("host_id_sha256", ""))) or \
            not isinstance(profile.get("report_shas"), list) or not profile["report_shas"] or \
            any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha)
                for sha in profile["report_shas"]):
        raise ValueError("x86 profile needs id/title, CPU count, host digest and full audited report SHAs")
    return profile


def selected_host_report(report, sha, profile=None):
    if profile is None:
        return host_matches(report)
    # An explicitly audited legacy report may predate stable host identity.
    # Never let a modern, differently identified report enter that allowlist.
    reported_host = report.get("host_identity")
    if reported_host is not None and (
            not isinstance(reported_host, dict) or
            reported_host.get("schema") != "swapz-host-v1" or
            reported_host.get("architecture") != "x86_64" or
            reported_host.get("id_sha256") != profile["host_id_sha256"]):
        return False
    backends = {row.get("name") for row in report.get("evidence", {}).get(
        "predictor", {}).get("backend_benchmarks", []) or []}
    stages = report.get("stages", [])
    return sha in profile["report_shas"] and \
        report.get("overall") == "PASS" and \
        host_matches(report, profile["online_cpus"], "avx512") and \
        all((arm.get("host_cpu") or {}).get("online_cpus") == profile["online_cpus"]
            for session in report.get("benchmarks", {}).get("sessions", [])
            for arm in (session.get("arms") or {}).values()) and \
        {"scalar", "sse2", "avx2", "avx512"}.issubset(backends) and \
        len(stages) == 5 and all(stage.get("status") == "PASS" for stage in stages)


def same_computer_report(report, identity):
    stages = report.get("stages", [])
    return report.get("host_identity") == identity and report.get("overall") == "PASS" and \
        len(stages) == 5 and all(stage.get("status") == "PASS" for stage in stages)


def collect(profile=None, computer=None):
    if profile is not None:
        validate_host_profile(profile)
    history = subprocess.check_output(
        ["git", "log", "--reverse", "--format=%H %cI", "--", "test_results.json"],
        cwd=ROOT, text=True).splitlines()
    reports, points, excluded = [], [], Counter()
    for entry in history:
        sha, stamp = entry.split()
        if profile is not None and sha not in profile["report_shas"]:
            excluded["outside audited host report allowlist"] += 1
            continue
        try:
            report = json.loads(subprocess.check_output(
                ["git", "show", sha + ":test_results.json"], cwd=ROOT))
        except (ValueError, subprocess.CalledProcessError):
            excluded["unreadable report"] += 1
            continue
        if not (same_computer_report(report, computer) if computer is not None
                else selected_host_report(report, sha, profile)):
            excluded["other or unproven host"] += 1
            continue
        if report.get("overall") != "PASS":
            excluded["selected host FAIL/BLOCKED"] += 1
            continue
        rows = report_points(report)
        if not rows:
            excluded["no comparable default-async sessions"] += 1
            continue
        metadata = {"sequence": len(reports) + 1, "report_sha": sha,
                    "source_sha": report.get("tested_commit_sha") or report.get("source_sha"),
                    "host_profile_id": computer["architecture"] + "-" + computer["id_sha256"] if computer else
                    (profile["id"] if profile else "arm64-neon"),
                    "host_id_sha256": computer["id_sha256"] if computer else
                    (profile["host_id_sha256"] if profile else None),
                    "date": datetime.fromisoformat(stamp).astimezone(
                        ZoneInfo("America/Los_Angeles")).isoformat(),
                    "kernel": report.get("kernel_release")}
        reports.append(metadata)
        points.extend({**metadata, **row} for row in rows)
    title = profile["title"] if profile else "ARM64 / NEON VM"
    identity = ("Explicit audited report allowlist for host digest " + profile["host_id_sha256"] +
                "; legacy reports without a host match stay separate."
                if profile else "NEON/seven-CPU VM cohort; old reports lack an immutable VM ID.")
    if computer is not None:
        title = computer["architecture"] + " · host " + computer["id_sha256"][:12]
        identity = "Exact OS installation identity and architecture; unidentified legacy reports excluded."
    return {"reports": reports, "points": points, "excluded": dict(excluded),
            "title": title, "host_profile": profile,
            "identity_note": identity,
            "scope": "Historical descriptive " + title + " owner PASS reports. " + identity +
                     " No quiet-window noise screen in official reports; no causal cross-report "
                     "inference or physical NVMe fidelity claim from configured RAM-model ceilings."}


def draw_line(ax, rows, metric, label, color, style="-"):
    chunks, chunk = [], []
    for row in rows:
        if row.get(metric) is None:
            if chunk:
                chunks.append(chunk)
                chunk = []
            continue
        if chunk and (row["sequence"] != chunk[-1]["sequence"] + 1 or
                      row["compatibility"] != chunk[-1]["compatibility"]):
            chunks.append(chunk)
            chunk = []
        chunk.append(row)
    if chunk:
        chunks.append(chunk)
    for index, part in enumerate(chunks):
        ax.plot([r["sequence"] for r in part], [r[metric] for r in part],
                style, marker="o", markersize=3, linewidth=1.6,
                color=color, label=label if index == 0 else None)


def goal_title(name, goal):
    """Name the owner-adopted class goal on every gain panel (ROADMAP ID174)."""
    if goal is None:
        return name
    if goal["bound"] == DEVICE_BOUND:
        return f"{name}\nTarget: beat raw (>0%)"
    return f"{name}\nGuard: within {abs(GUARD_FLOOR_PCT):g}% of raw ({goal['bound']})"


def draw_goal(ax, goal):
    """Raw parity is drawn everywhere; guard classes also show their floor."""
    if goal is not None and goal["bound"] != DEVICE_BOUND:
        ax.axhline(service_floor_pct(goal["bound"]), color="#b03030",
                   linewidth=1.0, linestyle=":", label="guard floor")


def render(data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    charts = {
        "mixed-throughput": ("Absolute useful WRITE service (decimal MB/s)",
                             [("raw_write_mbps", "Raw WRITE", "#777777", "--"),
                              ("swapz_write_mbps", "Swapz WRITE", "#1764ad", "-")]),
        "mixed-service": ("Useful mixed READ/WRITE gain versus raw (%)",
                          [("write_mbps_gain_pct", "Useful WRITE", "#1764ad", "-"),
                           ("read_mbps_gain_pct", "Useful READ", "#d67d18", "--")]),
        "mixed-latency": ("Mixed p99 latency reduction versus raw (%)",
                          [("read_p99_ms_gain_pct", "READ p99 reduction", "#177d60", "-"),
                           ("write_p99_ms_gain_pct", "WRITE p99 reduction", "#a34f90", "--")]),
        "lower-write-savings": ("Lower host-WRITE savings versus raw (%)",
                                [("lower_write_bytes_gain_pct", "Bytes saved", "#1764ad", "-"),
                                 ("lower_write_requests_gain_pct", "Requests saved", "#177d60", "--")]),
    }
    total = len(data["reports"])
    for filename, (title, metrics) in charts.items():
        fig, axes = plt.subplots(2, 3, figsize=(17, 9), sharex=True)
        for ax, (target, name) in zip(axes.flat, TARGETS.items()):
            rows = [r for r in data["points"] if r["target"] == target and r["workload"] == MIXED]
            for metric, label, color, style in metrics:
                draw_line(ax, rows, metric, label, color, style)
            ax.axhline(0, color="#888888", linewidth=.8)
            goal = goal_for(target, MIXED)
            if filename == "mixed-service":
                draw_goal(ax, goal)
                ax.set_title(goal_title(name, goal))
            elif filename == "lower-write-savings":
                ax.set_title(name + "\nTarget: fewer lower bytes and requests (>0%)")
            else:
                ax.set_title(name)
            ax.set_xlim(.5, total + 1)
            ax.grid(axis="y", alpha=.2)
            if ax.get_legend_handles_labels()[0]:  # empty panels stay quiet
                ax.legend(loc="best", fontsize=8)
            if rows:
                latest = rows[-1].get(metrics[0][0])
                if latest is not None:
                    caption = (f"Raw {rows[-1]['raw_write_mbps']:.1f}; "
                               f"swapz {rows[-1]['swapz_write_mbps']:.1f} MB/s"
                               if filename == "mixed-throughput" else f"Latest {latest:+.1f}%")
                    # Below the axes: never hides a plotted point.
                    ax.set_xlabel(caption, color=metrics[0][2],
                                  fontweight="bold", fontsize=9)
        fig.suptitle(data["title"] + " · " + title, fontsize=17, fontweight="bold")
        fig.text(.5, .935, f"{total} passing reports · {data['reports'][0]['date'][:10]} to "
                 f"{data['reports'][-1]['date'][:10]} · latest source {data['reports'][-1]['source_sha'][:7]}",
                 ha="center", fontsize=10, color="#555555")
        fig.supxlabel("Qualified report sequence · oldest to newest · source/report SHA mapping in CSV", y=.075)
        scale_note = ("Absolute decimal MB/s; higher is better for both raw and swapz"
                      if filename == "mixed-throughput" else
                      "0% = raw parity · positive = improvement")
        fig.text(.5, .025, "Async mixed; delta64 rescue on only (DELTA64_SHUF8 since 005592d; earlier points plain DELTA64) · " + scale_note + "\n"
                 "Matched-arm means; panel scales differ. READ is mixed-load service. Line breaks = kernel/model/workload changes. "
                 "Dotted red = guard floor.\n"
                 "Historical host load varies; ratios are descriptive, not causal gains or physical NAND wear evidence.",
                 ha="center", fontsize=9, color="#555555")
        fig.tight_layout(rect=(0, .10, 1, .94))
        fig.savefig(OUT / (filename + ".png"), dpi=150)
        plt.close(fig)

    fig, axes = plt.subplots(2, 4, figsize=(17, 8), sharex=True)
    for row_index, target in enumerate(("sd_emulated", "ssd_emulated")):
        for column, qd in enumerate((1, 4, 8, 32)):
            ax = axes[row_index, column]
            rows = [r for r in data["points"] if r["target"] == target and
                    r["workload"] == PERSISTENT and r["qd"] == qd]
            draw_line(ax, rows, "write_mbps_gain_pct", "WRITE", "#1764ad")
            ax.axhline(0, color="#888888", linewidth=.8)
            goal = goal_for(target, PERSISTENT, qd)
            draw_goal(ax, goal)
            ax.set_title(goal_title(("Serial" if row_index == 0 else "Fast") + f" · QD{qd}", goal))
            ax.grid(axis="y", alpha=.2)
            ax.set_xlim(.5, total + 1)
            if ax.get_legend_handles_labels()[0]:  # empty panels stay quiet
                ax.legend(loc="best", fontsize=8)
    fig.suptitle(data["title"] + " · sustained WRITE gain versus raw (%)", fontsize=17, fontweight="bold")
    fig.text(.5, .935, f"{total} passing reports · {data['reports'][0]['date'][:10]} to "
             f"{data['reports'][-1]['date'][:10]} · latest source {data['reports'][-1]['source_sha'][:7]}",
             ha="center", fontsize=10, color="#555555")
    fig.supxlabel("Qualified report sequence · persistent lane-owned workers only; wave drivers excluded", y=.06)
    fig.text(.5, .015, "0% = raw parity · dotted red = latency/host-bound guard floor · kernel changes "
             "break lines · descriptive history; host load is uncontrolled",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, .94))
    fig.savefig(OUT / "sustained-write.png", dpi=150)
    plt.close(fig)


def snapshot_history(data):
    """Keep report-specific images/data stable when the latest files refresh."""
    identity = hashlib.sha256(Path(__file__).read_bytes() +
                              json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    snapshot = OUT / "snapshots" / data["reports"][-1]["report_sha"] / identity
    snapshot.mkdir(parents=True, exist_ok=True)
    for name in ("mixed-service.png", "mixed-throughput.png", "mixed-latency.png",
                 "lower-write-savings.png", "sustained-write.png", "history.csv", "history.json"):
        target = snapshot / name
        if not target.exists():
            shutil.copyfile(OUT / name, target)
    return snapshot


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host-profile", type=Path,
                        help="audited x86 host JSON; omission preserves the ARM64 cohort")
    parser.add_argument("--host-id", help="exact report machine identity digest")
    parser.add_argument("--host-architecture", help="exact report architecture")
    args = parser.parse_args()
    computer = None
    if args.host_id or args.host_architecture:
        if args.host_profile or not re.fullmatch(r"[0-9a-f]{64}", args.host_id or "") or not re.fullmatch(r"[a-zA-Z0-9_-]+", args.host_architecture or ""):
            parser.error("computer selection needs a valid digest and architecture, without --host-profile")
        computer = {"schema": "swapz-host-v1", "id_sha256": args.host_id,
                    "architecture": args.host_architecture}
        OUT = ROOT / "build/history" / (args.host_architecture + "-" + args.host_id)
    profile = validate_host_profile(json.loads(args.host_profile.read_text())) \
        if args.host_profile else None
    if profile is not None:
        OUT = ROOT / "build/history" / profile["id"]
    data = collect(profile, computer)
    if not data["reports"]:
        raise SystemExit("No proven PASS history for the selected host profile")
    render(data)
    (OUT / "history.json").write_text(json.dumps(data, indent=2) + "\n")
    fields = sorted({key for point in data["points"] for key in point})
    with (OUT / "history.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data["points"])
    snapshot = snapshot_history(data)
    summary = ["# " + data["title"] + " performance history", "", data["scope"], "",
               f"{len(data['reports'])} passing report revisions; latest source "
               f"`{data['reports'][-1]['source_sha']}`. " + data["identity_note"], "",
               "Each mixed point uses async sessions and its own raw controls. Current history includes "
               "only delta64-rescue-on sessions; historical delta64-off sessions and the retired write-only "
               "delta64-positive envelope rows are intentionally excluded. Rescue-on points from sources "
               "before 005592d used plain DELTA64 rather than DELTA64_SHUF8; the medium fixture adopts "
               "neither, so those points are comparable but not evidence for the shuffle encoding. "
               "Rates are ratios of matched-arm arithmetic means, so rounded percentages may differ "
               "slightly from the official report's differently pooled raw column. Positive means "
               "improvement; zero is raw parity. p99 and lower I/O use percent reduction. "
               "Different kernels/models/content/replay break lines. These are descriptive history, "
               "not causal cross-source A/B or physical NAND-wear evidence. Missing data stays absent. "
               "Uncommitted fast_test trials are excluded.", "",
               "Latest default mixed observations (directional; no cross-report confidence claim):", "",
               "| Target | Useful WRITE vs raw | Useful READ vs raw | READ p99 reduction | Lower WRITE bytes saved | Lower WRITE requests saved |",
               "| :--- | ---: | ---: | ---: | ---: | ---: |"]
    for target, name in TARGETS.items():
        rows = [r for r in data["points"] if r["target"] == target and r["workload"].startswith("mixed")]
        if rows:
            latest = rows[-1]
            values = [latest.get(key) for key in ("write_mbps_gain_pct", "read_mbps_gain_pct",
                      "read_p99_ms_gain_pct", "lower_write_bytes_gain_pct", "lower_write_requests_gain_pct")]
            summary.append("| " + name + " | " + " | ".join(
                f"{value:+.1f}%" if value is not None else "unavailable" for value in values) + " |")
    latest_points = [point for point in data["points"]
                     if point["report_sha"] == data["reports"][-1]["report_sha"]]
    summary.extend(["", "Per-device-class goals for the latest report (ROADMAP ID174; descriptive, "
                    "not a qualification gate). Device-bound classes must beat raw useful WRITE "
                    "and save lower WRITE bytes and requests; latency/host-bound guards must stay "
                    f"within {abs(GUARD_FLOOR_PCT):g}% of raw without adding lower WRITE work.", "",
                    "| Class | Bound | Goal | Useful WRITE vs raw | Bytes saved | Requests saved | Status |",
                    "| :--- | :--- | :--- | ---: | ---: | ---: | :--- |"])
    for row in scorecard(latest_points):
        goal = (">0%" if row["bound"] == DEVICE_BOUND else
                f">={row['service_floor_pct']:g}%")
        cells = [f"{row[key]:+.1f}%" if row[key] is not None else "unavailable"
                 for key in ("write_gain_pct", "lower_write_bytes_saved_pct",
                             "lower_write_requests_saved_pct")]
        summary.append(f"| {row['label']} | {row['bound']} | {goal} | " +
                       " | ".join(cells) + f" | {row['status']} |")
    summary.extend(["", "Plots and source data:", ""] +
                   [f"- [{name}]({snapshot / name})" for name in
                    ("mixed-service.png", "mixed-throughput.png", "mixed-latency.png", "lower-write-savings.png",
                     "sustained-write.png", "history.csv", "history.json")])
    index = "\n".join(summary) + "\n"
    (OUT / "index.md").write_text(index)
    if not (snapshot / "index.md").exists():
        (snapshot / "index.md").write_text(index)
    print(json.dumps({"reports": len(data["reports"]), "points": len(data["points"]),
                      "excluded": data["excluded"], "output": str(OUT),
                      "latest_source": data["reports"][-1]["source_sha"],
                      "latest_report": data["reports"][-1]["report_sha"],
                      "snapshot": str(snapshot)}))


if __name__ == "__main__":
    main()
