#!/usr/bin/env python3
"""Private round-closeout plots from committed ARM64/NEON owner reports.

This is descriptive history, not qualification or a cross-source causal A/B.
No devices, Git mutations, report publication or new public Make goal.
Matplotlib is imported only for rendering, outside rootless parser tests.
"""
import csv
import hashlib
import json
import math
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/history/arm64-neon"
TARGETS = {
    "sd_emulated": "Serial model · 10 MiB/s, 1 ms",
    "ssd_emulated": "Fast model · 80 MiB/s, 150 µs",
    "sd_card": "SD card envelope · 100 MiB/s, 500 µs",
    "sata_ssd": "SATA envelope · 500 MiB/s, 100 µs",
    "nvme_gen4": "NVMe Gen4 envelope · 6500 MiB/s, 25 µs",
    "nvme_gen5": "NVMe Gen5 envelope · 12000 MiB/s, 14 µs",
}


def host_matches(report, online_cpus=7):
    backends = report.get("evidence", {}).get("predictor", {}).get(
        "backend_benchmarks", []) or []
    cpus = {(arm.get("host_cpu") or {}).get("online_cpus")
            for session in report.get("benchmarks", {}).get("sessions", [])
            for arm in (session.get("arms") or {}).values()
            if (arm.get("host_cpu") or {}).get("online_cpus") is not None}
    return any(row.get("name") == "neon" for row in backends) and cpus == {online_cpus}


def number(value, allow_zero=False):
    return isinstance(value, (int, float)) and math.isfinite(value) and \
        (value >= 0 if allow_zero else value > 0)


def change(candidate, raw, lower_better=False):
    if not number(candidate, lower_better) or not number(raw):
        return None
    return 100 * (1 - candidate / raw if lower_better else candidate / raw - 1)


def paired_inputs_match(session, source):
    arms = session.get("arms") or {}
    raw, swapz = arms.get("off") or {}, arms.get("swapz") or {}
    return bool(source) and raw.get("source_sha") == source == swapz.get("source_sha") and \
        all(raw.get(key) and raw[key] == swapz.get(key)
            for key in ("fixture_sha256", "trace_sha256"))


def report_points(report):
    """Keep async mixed sessions by rescue policy; separate persistent WRITE QDs."""
    if report.get("overall") != "PASS":
        return []
    benchmarks = report.get("benchmarks", {})
    groups, metadata = defaultdict(list), {}
    source = report.get("tested_commit_sha") or report.get("source_sha")
    for session in benchmarks.get("sessions", []) + benchmarks.get(
            "storage_envelope_sessions", []):
        if session.get("status") != "PASS":
            continue
        envelope = session.get("envelope")
        if envelope:
            if session.get("delta64_rescue") != 0:
                continue
        elif session.get("async_prepare") != 1:
            continue
        arms = session.get("arms", {})
        raw, swapz = arms.get("off", {}), arms.get("swapz", {})
        # Delta64 policy is part of series identity: the production default
        # changed to rescue-on, so never join it to LZ4-only history.
        delta64 = (swapz.get("kernel_write_path") or {}).get("delta64_rescue")
        if delta64 not in (0, 1):
            continue
        target = envelope or session.get("regime")
        if target not in TARGETS:
            continue
        fixture, trace = raw.get("fixture_sha256"), raw.get("trace_sha256")
        if not paired_inputs_match(session, source):
            continue
        # Never join different device geometry, content, replay or kernels.
        identity = (session.get("device_model"), fixture, trace,
                    raw.get("replay_engine"), raw.get("replay_mode"),
                    report.get("kernel_release"), delta64)
        compatibility = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        groups[(target, compatibility)].append((raw, swapz))
        metadata[(target, compatibility)] = {
            "device_model": json.dumps(identity[0], sort_keys=True),
            "fixture_sha256": fixture, "trace_sha256": trace,
            "replay_engine": raw.get("replay_engine"), "replay_mode": raw.get("replay_mode"),
            "delta64_rescue": delta64}

    points = []
    fields = {
        "write_mbps": ("input_write_mbps", "input_write_mbps"),
        "read_mbps": ("swap_in_read_mbps", "input_read_mbps"),
        "read_p99_ms": ("swap_in_read_p99_ms", "read_p99_ms"),
        "write_p99_ms": ("write_p99_ms", "write_p99_ms"),
        "lower_write_bytes": ("lower_write_bytes", "lower_write_bytes"),
        "lower_write_requests": ("lower_write_requests", "lower_write_requests"),
    }
    for (target, compatibility), sessions in groups.items():
        delta64 = metadata[(target, compatibility)]["delta64_rescue"]
        point = {"target": target,
                 "workload": "mixed QD32, delta64 " + ("on" if delta64 else "off"),
                 "compatibility": compatibility, "observations": len(sessions),
                 **metadata[(target, compatibility)]}
        for metric, keys in fields.items():
            values = [(raw.get(keys[0], raw.get(keys[1])),
                       swapz.get(keys[0], swapz.get(keys[1])))
                      for raw, swapz in sessions]
            lower_better = metric not in ("write_mbps", "read_mbps")
            values = [(raw, swapz) for raw, swapz in values
                      if number(raw) and number(swapz, lower_better)]
            raw = statistics.mean(v[0] for v in values) if values else None
            swapz = statistics.mean(v[1] for v in values) if values else None
            point["raw_" + metric], point["swapz_" + metric] = raw, swapz
            point[metric + "_gain_pct"] = change(
                swapz, raw, lower_better)
        if point["write_mbps_gain_pct"] is not None:
            points.append(point)

    saturation = benchmarks.get("write_saturation", {})
    if saturation.get("replay_mode") == "persistent-write":
        for target, rows in saturation.get("regimes", {}).items():
            if target not in ("sd_emulated", "ssd_emulated"):
                continue
            for row in rows:
                if row.get("mode") != "async" or row.get("qd") not in (1, 4, 8, 32):
                    continue
                gain = change(row.get("swapz_write_mbps"), row.get("raw_write_mbps"))
                identities = {json.dumps((s.get("device_model"), s.get("fixture_sha256"),
                                          s.get("trace_sha256"), report.get("kernel_release"),
                                          (s.get("arms", {}).get("swapz", {}).get(
                                              "kernel_write_path") or {}).get("delta64_rescue")),
                                         sort_keys=True)
                              for s in benchmarks.get("write_saturation_sessions", [])
                              if s.get("status") == "PASS" and s.get("async_prepare") == 1 and
                              s.get("regime") == target and s.get("qd") == row["qd"] and
                              paired_inputs_match(s, source) and
                              (s.get("arms", {}).get("swapz", {}).get("kernel_write_path") or {}).get(
                                  "delta64_rescue") in (0, 1) and
                              all((s.get("arms", {}).get(arm) or {}).get("replay_mode") ==
                                  "persistent-write" for arm in ("off", "swapz"))}
                if gain is not None and len(identities) == 1:
                    points.append({"target": target, "workload": "persistent WRITE",
                                   "qd": row["qd"], "write_mbps_gain_pct": gain,
                                   "raw_write_mbps": row["raw_write_mbps"],
                                   "swapz_write_mbps": row["swapz_write_mbps"],
                                   "compatibility": hashlib.sha256(
                                       json.dumps(sorted(identities)).encode()).hexdigest(),
                                   "delta64_rescue": json.loads(next(iter(identities)))[-1],
                                   "observations": row.get("observations")})
    return points


def collect():
    history = subprocess.check_output(
        ["git", "log", "--reverse", "--format=%H %cI", "--", "test_results.json"],
        cwd=ROOT, text=True).splitlines()
    reports, points, excluded = [], [], Counter()
    for entry in history:
        sha, stamp = entry.split()
        try:
            report = json.loads(subprocess.check_output(
                ["git", "show", sha + ":test_results.json"], cwd=ROOT))
        except (ValueError, subprocess.CalledProcessError):
            excluded["unreadable report"] += 1
            continue
        if not host_matches(report):
            excluded["other or unproven host"] += 1
            continue
        if report.get("overall") != "PASS":
            excluded["ARM64 FAIL/BLOCKED"] += 1
            continue
        rows = report_points(report)
        if not rows:
            excluded["no comparable default-async sessions"] += 1
            continue
        metadata = {"sequence": len(reports) + 1, "report_sha": sha,
                    "source_sha": report.get("tested_commit_sha") or report.get("source_sha"),
                    "date": datetime.fromisoformat(stamp).astimezone(
                        ZoneInfo("America/Los_Angeles")).isoformat(),
                    "kernel": report.get("kernel_release")}
        reports.append(metadata)
        points.extend({**metadata, **row} for row in rows)
    return {"reports": reports, "points": points, "excluded": dict(excluded),
            "scope": "Historical descriptive ARM64/NEON seven-CPU VM owner PASS reports; "
                     "no quiet-window noise screen in old reports; no causal cross-report inference."}


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


def render(data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    charts = {
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
            rows = [r for r in data["points"] if r["target"] == target and r["workload"].startswith("mixed")]
            for metric, label, color, style in metrics:
                for policy in (0, 1):
                    selected = [r for r in rows if r["delta64_rescue"] == policy]
                    if selected:
                        draw_line(ax, selected, metric,
                                  label + " · delta64 " + ("on" if policy else "off"),
                                  color, style)
            ax.axhline(0, color="#888888", linewidth=.8)
            ax.set_title(name)
            ax.set_xlim(.5, total + 1)
            ax.grid(axis="y", alpha=.2)
            ax.legend(loc="best", fontsize=8)
            if rows:
                latest = rows[-1].get(metrics[0][0])
                if latest is not None:
                    ax.text(.98, .03, f"Latest {latest:+.1f}%", transform=ax.transAxes,
                            ha="right", color=metrics[0][2], fontweight="bold")
        fig.suptitle("ARM64 / NEON VM · " + title, fontsize=17, fontweight="bold")
        fig.text(.5, .935, f"{total} passing reports · {data['reports'][0]['date'][:10]} to "
                 f"{data['reports'][-1]['date'][:10]} · latest source {data['reports'][-1]['source_sha'][:7]}",
                 ha="center", fontsize=10, color="#555555")
        fig.supxlabel("Qualified report sequence · oldest to newest · source/report SHA mapping in CSV", y=.075)
        fig.text(.5, .025, "Async mixed; delta64 on/off shown separately · 0% = raw parity · positive = improvement\n"
                 "Ratios of matched-arm means; panel scales differ. READ is mixed-load service. Line breaks = kernel/model/workload changes.\n"
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
                    r["workload"] == "persistent WRITE" and r["qd"] == qd]
            for policy in (0, 1):
                selected = [r for r in rows if r["delta64_rescue"] == policy]
                if selected:
                    draw_line(ax, selected, "write_mbps_gain_pct",
                              "WRITE · delta64 " + ("on" if policy else "off"),
                              "#1764ad")
            ax.axhline(0, color="#888888", linewidth=.8)
            ax.set_title(("Serial" if row_index == 0 else "Fast") + f" · QD{qd}")
            ax.grid(axis="y", alpha=.2)
            ax.set_xlim(.5, total + 1)
            ax.legend(loc="best", fontsize=8)
    fig.suptitle("ARM64 / NEON VM · sustained WRITE gain versus raw (%)", fontsize=17, fontweight="bold")
    fig.text(.5, .935, f"{total} passing reports · {data['reports'][0]['date'][:10]} to "
             f"{data['reports'][-1]['date'][:10]} · latest source {data['reports'][-1]['source_sha'][:7]}",
             ha="center", fontsize=10, color="#555555")
    fig.supxlabel("Qualified report sequence · persistent lane-owned workers only; wave drivers excluded", y=.06)
    fig.text(.5, .015, "0% = raw parity · kernel changes break lines · descriptive history; host load is uncontrolled",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, .94))
    fig.savefig(OUT / "sustained-write.png", dpi=150)
    plt.close(fig)


def main():
    data = collect()
    if not data["reports"]:
        raise SystemExit("No proven seven-CPU ARM64/NEON PASS history")
    render(data)
    (OUT / "history.json").write_text(json.dumps(data, indent=2) + "\n")
    fields = sorted({key for point in data["points"] for key in point})
    with (OUT / "history.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data["points"])
    summary = ["# ARM64 / NEON VM performance history", "", data["scope"], "",
               f"{len(data['reports'])} passing report revisions; latest source "
               f"`{data['reports'][-1]['source_sha']}`. All points require NEON and the "
               "seven-CPU VM profile. Reports do not contain an immutable VM identifier.", "",
               "Each mixed point uses async sessions and its own raw controls; delta64-on and "
               "delta64-off policies have separate labels and lines. Modern envelope mixed controls "
               "remain LZ4-only; delta-positive write-only envelopes are a different workload and excluded. "
               "Rates are ratios of matched-arm arithmetic means, so rounded percentages may differ "
               "slightly from the official report's differently pooled raw column. Positive means "
               "improvement; zero is raw parity. p99 and lower I/O use percent reduction. "
               "Different kernels/models/content/replay break lines. These are descriptive history, "
               "not causal cross-source A/B or physical NAND-wear evidence. Missing data stays absent. "
               "Uncommitted fast_test trials are excluded.", "",
               "Latest default mixed observations (directional; no cross-report confidence claim):", "",
               "| Target | Useful WRITE vs raw | Useful READ vs raw | READ p99 reduction | Lower WRITE bytes saved | Lower WRITE requests saved |",
               "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for target, name in TARGETS.items():
        rows = [r for r in data["points"] if r["target"] == target and r["workload"].startswith("mixed")]
        if rows:
            latest = rows[-1]
            values = [latest.get(key) for key in ("write_mbps_gain_pct", "read_mbps_gain_pct",
                      "read_p99_ms_gain_pct", "lower_write_bytes_gain_pct", "lower_write_requests_gain_pct")]
            summary.append("| " + name + " | " + " | ".join(
                f"{value:+.1f}%" if value is not None else "unavailable" for value in values) + " |")
    summary.extend(["", "Plots and source data:", ""] +
                   [f"- [{name}]({OUT / name})" for name in
                    ("mixed-service.png", "mixed-latency.png", "lower-write-savings.png",
                     "sustained-write.png", "history.csv", "history.json")])
    (OUT / "index.md").write_text("\n".join(summary) + "\n")
    print(json.dumps({"reports": len(data["reports"]), "points": len(data["points"]),
                      "excluded": data["excluded"], "output": str(OUT)}))


if __name__ == "__main__":
    main()
