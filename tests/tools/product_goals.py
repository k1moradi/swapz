"""Per-device-class product goals and comparable report points (ROADMAP ID174).

Shared by the private make-test reporter and the private history plotter so the
console scorecard, the saved report and the plots classify every row exactly
once. Descriptive only: no qualification gate reads these results. Imports no
third-party modules; matplotlib stays inside the plotter's renderer.
"""
import hashlib
import json
import math
import statistics
from collections import defaultdict

# Mixed QD32 targets in plot/report order, with their synthetic model labels.
TARGETS = {
    "sd_emulated": "Serial model · 10 MiB/s, 1 ms",
    "ssd_emulated": "Fast model · 80 MiB/s, 150 µs",
    "sd_card": "SD card envelope · 100 MiB/s, 500 µs",
    "sata_ssd": "SATA envelope · 500 MiB/s, 100 µs",
    "nvme_gen4": "NVMe Gen4 envelope · 6500 MiB/s, 25 µs",
    "nvme_gen5": "NVMe Gen5 envelope · 12000 MiB/s, 14 µs",
}
MIXED = "mixed QD32"
PERSISTENT = "persistent WRITE"
SUSTAINED_TARGETS = ("sd_emulated", "ssd_emulated")
SUSTAINED_QDS = (1, 4, 8, 32)

# Owner-adopted classes. Device-bound rows must beat raw useful WRITE and save
# lower WRITE bytes and requests. Latency- or host-bound rows are guards: they
# must stay within GUARD_FLOOR_PCT of raw and must not ADD lower WRITE bytes or
# requests (an isolated QD1 page occupies one 4KiB block either way).
DEVICE_BOUND = "device-bound"
LATENCY_BOUND = "latency-bound"
HOST_BOUND = "host-bound"
TARGET_FLOOR_PCT = 0.0
GUARD_FLOOR_PCT = -5.0
# Floating-point tolerance for "no added lower I/O" on exact-ratio guard rows.
LOWER_IO_EPSILON_PCT = 1e-9


def _goal(target, workload, qd, label, bound):
    return {"target": target, "workload": workload, "qd": qd,
            "label": label, "bound": bound}


GOALS = (
    _goal("sd_emulated", MIXED, None, "Serial mixed", DEVICE_BOUND),
    _goal("ssd_emulated", MIXED, None, "Fast mixed", DEVICE_BOUND),
    _goal("sd_card", MIXED, None, "SD card mixed", DEVICE_BOUND),
    _goal("sata_ssd", MIXED, None, "SATA mixed", DEVICE_BOUND),
    _goal("nvme_gen4", MIXED, None, "NVMe4 mixed", HOST_BOUND),
    _goal("nvme_gen5", MIXED, None, "NVMe5 mixed", HOST_BOUND),
    _goal("sd_emulated", PERSISTENT, 1, "Serial QD1", LATENCY_BOUND),
    _goal("sd_emulated", PERSISTENT, 4, "Serial QD4", DEVICE_BOUND),
    _goal("sd_emulated", PERSISTENT, 8, "Serial QD8", DEVICE_BOUND),
    _goal("sd_emulated", PERSISTENT, 32, "Serial QD32", DEVICE_BOUND),
    _goal("ssd_emulated", PERSISTENT, 1, "Fast QD1", LATENCY_BOUND),
    _goal("ssd_emulated", PERSISTENT, 4, "Fast QD4", LATENCY_BOUND),
    _goal("ssd_emulated", PERSISTENT, 8, "Fast QD8", DEVICE_BOUND),
    _goal("ssd_emulated", PERSISTENT, 32, "Fast QD32", DEVICE_BOUND),
)


def goal_for(target, workload, qd=None):
    for goal in GOALS:
        if goal["target"] == target and goal["workload"] == workload and \
                goal["qd"] == qd:
            return goal
    return None


def service_floor_pct(bound):
    """Useful-WRITE threshold: beat raw, or stay inside the parity guard."""
    return TARGET_FLOOR_PCT if bound == DEVICE_BOUND else GUARD_FLOOR_PCT


def number(value, allow_zero=False):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and \
        math.isfinite(value) and (value >= 0 if allow_zero else value > 0)


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
    """Keep only production-on async mixed sessions and persistent WRITE QDs."""
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
        if not envelope and session.get("async_prepare") != 1:
            continue
        arms = session.get("arms", {})
        raw, swapz = arms.get("off", {}), arms.get("swapz", {})
        # Current history intentionally excludes historical delta64-off runs.
        if (swapz.get("kernel_write_path") or {}).get("delta64_rescue") != 1:
            continue
        # Historical envelope rescue-on rows replayed the write-only
        # delta64-positive fixture, not the mixed workload; their arms carry
        # no replay_mode. A mixed QD32 point must show READ service on both
        # arms, so never draw a write-only row on the mixed panels.
        if envelope and not all(
                isinstance(arm.get("input_read_mbps"), (int, float)) and
                arm["input_read_mbps"] > 0 for arm in (raw, swapz)):
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
                    report.get("kernel_release"))
        compatibility = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        groups[(target, compatibility)].append((raw, swapz))
        metadata[(target, compatibility)] = {
            "device_model": json.dumps(identity[0], sort_keys=True),
            "fixture_sha256": fixture, "trace_sha256": trace,
            "replay_engine": raw.get("replay_engine"), "replay_mode": raw.get("replay_mode")}

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
        point = {"target": target,
                 "workload": MIXED,
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
            if target not in SUSTAINED_TARGETS:
                continue
            for row in rows:
                if row.get("mode") != "async" or row.get("qd") not in SUSTAINED_QDS:
                    continue
                gain = change(row.get("swapz_write_mbps"), row.get("raw_write_mbps"))
                identities = {json.dumps((s.get("device_model"), s.get("fixture_sha256"),
                                          s.get("trace_sha256"), report.get("kernel_release")),
                                         sort_keys=True)
                              for s in benchmarks.get("write_saturation_sessions", [])
                              if s.get("status") == "PASS" and s.get("async_prepare") == 1 and
                              s.get("regime") == target and s.get("qd") == row["qd"] and
                              paired_inputs_match(s, source) and
                              (s.get("arms", {}).get("swapz", {}).get("kernel_write_path") or {}).get(
                                  "delta64_rescue") == 1 and
                              all((s.get("arms", {}).get(arm) or {}).get("replay_mode") ==
                                  "persistent-write" for arm in ("off", "swapz"))}
                if gain is not None and len(identities) == 1:
                    # The raw arm writes exactly its logical bytes, so swapz
                    # lower bytes per raw byte is the inverse logical ratio.
                    ratio = row.get("swapz_logical_to_lower_ratio")
                    points.append({"target": target, "workload": PERSISTENT,
                                   "qd": row["qd"], "write_mbps_gain_pct": gain,
                                   "raw_write_mbps": row["raw_write_mbps"],
                                   "swapz_write_mbps": row["swapz_write_mbps"],
                                   "lower_write_bytes_gain_pct":
                                       100 * (1 - 1 / ratio) if number(ratio) else None,
                                   "lower_write_requests_gain_pct": change(
                                       row.get("swapz_lower_write_requests"),
                                       row.get("raw_lower_write_requests"), True),
                                   "compatibility": hashlib.sha256(
                                       json.dumps(sorted(identities)).encode()).hexdigest(),
                                   "observations": row.get("observations")})
    return points


def lower_io_goal_met(bound, saved_bytes_pct, saved_requests_pct):
    """Targets must save lower WRITE work; guards must merely not add any."""
    if bound == DEVICE_BOUND:
        return saved_bytes_pct > 0 and saved_requests_pct > 0
    return saved_bytes_pct >= -LOWER_IO_EPSILON_PCT and \
        saved_requests_pct >= -LOWER_IO_EPSILON_PCT


def scorecard(points):
    """Evaluate the latest comparable point of every goal class.

    MET needs the class service goal plus its lower-WRITE goal; any missing
    input stays UNAVAILABLE rather than being treated as zero.
    """
    rows = []
    for goal in GOALS:
        matches = [point for point in points
                   if point.get("target") == goal["target"] and
                   point.get("workload") == goal["workload"] and
                   point.get("qd") == goal["qd"]]
        point = matches[-1] if matches else {}
        gain = point.get("write_mbps_gain_pct")
        saved_bytes = point.get("lower_write_bytes_gain_pct")
        saved_requests = point.get("lower_write_requests_gain_pct")
        floor = service_floor_pct(goal["bound"])
        if gain is None or saved_bytes is None or saved_requests is None:
            status = "UNAVAILABLE"
        elif (gain > floor if goal["bound"] == DEVICE_BOUND else gain >= floor) and \
                lower_io_goal_met(goal["bound"], saved_bytes, saved_requests):
            status = "MET"
        else:
            status = "MISSED"
        rows.append({**goal, "service_floor_pct": floor,
                     "write_gain_pct": gain,
                     "lower_write_bytes_saved_pct": saved_bytes,
                     "lower_write_requests_saved_pct": saved_requests,
                     "status": status})
    return rows
