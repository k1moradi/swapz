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


def ram_stages_pass(report):
    """Prove all five RAM stages passed without requiring physical admission."""
    stages = report.get("stages")
    return isinstance(stages, list) and len(stages) == 5 and all(
        isinstance(stage, dict) and stage.get("status") == "PASS"
        for stage in stages)


def report_points(report, *, include_incomplete_ram=False):
    """Keep comparable production-on async mixed and persistent WRITE QDs.

    The history plotter may include overall INCOMPLETE after all RAM stages
    pass. Normal report qualification decisions remain unchanged.
    """
    if report.get("overall") != "PASS" and not (
            include_incomplete_ram and report.get("overall") == "INCOMPLETE"
            and ram_stages_pass(report)):
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


# CI diagnostics are observational; they do not qualify a device or replace
# the official, sequential make test command.
def _ci_safe_line(line):
    """Redact credentials and private roots before retaining any output."""
    import os
    import re
    from pathlib import Path

    # The bounded reader's witness must outlive exception-detail redaction.
    # Preserve only the fixed truncation fact, never private child bytes.
    bounded_input_truncated = line.endswith(" [line truncated]\n")
    line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
    for name, replacement in (("GITHUB_WORKSPACE", "<workspace>"),
                              ("RUNNER_TEMP", "<runner-temp>"),
                              ("HOME", "<home>")):
        directory = os.environ.get(name)
        if directory and directory != "/":
            line = line.replace(directory, replacement)
    line = line.replace(str(Path(__file__).resolve().parents[2]), "<workspace>")
    line = re.sub(
        r"(?i)\b((?:authorization:\s*(?:bearer|basic)\s+)|"
        r"(?:(?:access[_-]?)?token(?:[_-]?path)?|password|secret|api[_-]?key|"
        r"private[_-]?key|(?:part)?uuid|serial|wwn|campaign(?:[_-]?id)?|"
        r"device[_-]?id)\s*[:=]\s*)[^\s]+",
        r"\1<redacted>", line)
    line = re.sub(r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]{12,}",
                  "<redacted>", line)
    # Child-supplied structured diagnostic values are private, but source
    # syntax in a traceback is repository-controlled context and must remain
    # intact (for example, mapping["category"] is not a JSON array).
    json_string = r'"(?:\\.|[^"\\])*"'
    json_scalar = (
        json_string + r"|"
        r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|"
        r"true|false|null"
    )
    json_array = (
        r"\[(?:\s*(?:" + json_scalar + r")"
        + r"(?:\s*,\s*(?:" + json_scalar + r"))*\s*)\]"
    )
    json_object = r"\{[^\r\n]*\}"
    structured_value = (
        r"(?:" + json_object + r"|" + json_array + r"|" + json_string + r")"
    )
    # Expected/actual numeric counters are safe and diagnostically necessary.
    line = re.sub(
        r"(?i)\b((?:actual|observed)\s*[:=]\s*)" + structured_value,
        r"\1<structured-evidence-redacted>", line)
    line = re.sub(
        r"(?i)\b((?:payload|response|json)\s*[:=]\s*)"
        r"(?:" + json_object + r"|" + json_array + r"|" + json_scalar + r")",
        r"\1<structured-evidence-redacted>", line)
    exception_prefix = (
        r"^(?:E\s+)?(?:AssertionError|RuntimeError|ValueError|TypeError|"
        r"KeyError|IndexError|AttributeError|OSError|TimeoutError|"
        r"FileNotFoundError|PermissionError|SystemExit):"
    )
    if re.match(exception_prefix, line):
        line = re.sub(
            json_object + r"|" + json_array,
            "<structured-evidence-redacted>", line)
    # Preserve only the two source-controlled contract-suite basenames so
    # failure classification survives redaction of their containing host root.
    line = re.sub(
        r"(?<![A-Za-z0-9_./])/(?:[^/\s\x27\x22,;:)\]}]+/)*"
        r"(source-contract|make-interface)-test\.py\b",
        r"<private-path>/\1-test.py", line)
    line = re.sub(r"(?<![A-Za-z0-9_./>])\/[^\s\x27\x22,;:)\]}]+",
                  "<private-path>", line)
    # Keep the assertion operand, not a potentially huge source literal.
    line = re.sub(
        r"(AssertionError: .*? (?:not |unexpectedly )?found in ).*",
        r"\1<source excerpt omitted>", line)
    line = re.sub(r"(?<!\w)/(?:tmp|var/tmp)/[^\s\x27\x22:]+",
                  "<temporary-path>", line)
    clean_line = re.sub(r"[\x00-\x1f\x7f]", " ", line).strip()
    # Exception messages are child-owned; only bounded numerical evidence and
    # already-redacted operands may enter public CI logs or annotations.
    exception_match = re.match(
        r"^(?:E\s+)?(?:[A-Za-z_][A-Za-z0-9_.]{0,95}"
        r"(?:Error|Exception|Timeout)|SystemExit|"
        r"subprocess\.(?:TimeoutExpired|CalledProcessError)):", clean_line)
    if exception_match:
        safe_operand = (
            r"(?:expected|actual|observed)="
            r"(?:[0-9]{1,12}|<private-path>|<structured-evidence-redacted>)"
        )
        exception_detail = clean_line[exception_match.end():].strip()
        safe_assertion = (
            exception_match.group(0) == "AssertionError:" and
            re.fullmatch(safe_operand + r"(?: " + safe_operand + r"){0,3}",
                         exception_detail) is not None
        )
        if not safe_assertion and clean_line != "ValueError: substring not found":
            clean_line = (exception_match.group(0) +
                          " [private exception detail omitted]")
    # A child can also forge a unittest heading with private identifiers or
    # extra trailing context. Keep only a bounded, dotted Python identity.
    if re.match(r"^(?:FAIL|ERROR):\s+(?:test_|setUp|tearDown)", clean_line):
        unittest_heading = re.match(
            r"^(FAIL|ERROR):\s+(\S+)\s+\(([^)]*)\)", clean_line)
        if (unittest_heading is not None and
                re.fullmatch(
                    r"test_[A-Za-z0-9_]{1,96}|(?:setUp|tearDown)"
                    r"(?:Class|Module)?", unittest_heading.group(2)) and
                re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]{0,95}"
                    r"(?:\.[A-Za-z_][A-Za-z0-9_]{0,95}){1,8}",
                    unittest_heading.group(3))):
            clean_line = unittest_heading.group(0)
        else:
            clean_line = clean_line.split(":", 1)[0] + ": unittest identity withheld"
    if len(clean_line) > 320 or bounded_input_truncated:
        return clean_line[:306] + " [truncated]"
    return clean_line


def _ci_record_lines(record, maximum_bytes=4096):
    """Yield at most one bounded prefix for each logical captured-output line."""
    while True:
        raw_line = record.readline(maximum_bytes)
        if not raw_line:
            return
        truncated = len(raw_line) == maximum_bytes and not raw_line.endswith(b"\n")
        if truncated:
            # Drain the remainder without retaining or exposing it. Besides
            # bounding memory/log size, this prevents a secret suffix on an
            # enormous line from bypassing prefix-based redaction.
            while True:
                remainder = record.readline(maximum_bytes)
                if not remainder or remainder.endswith(b"\n"):
                    break
        line = raw_line.decode("utf-8", errors="replace")
        if truncated:
            line = line.rstrip("\r\n") + " [line truncated]\n"
        yield line


def _ci_unittest_name(method_name, context):
    """Normalize unittest's short and fully-qualified failure headers."""
    suffix = "." + method_name
    return context if context.endswith(suffix) else context + suffix


def _ci_make_recipe_owner(line_number):
    """Return the source-controlled target owning one Make recipe line."""
    import re
    from pathlib import Path

    owner = None
    makefile = Path(__file__).resolve().parents[1] / "suites/Makefile"
    try:
        with makefile.open(encoding="utf-8") as source:
            for current_line_number, source_line in enumerate(source, 1):
                target_match = re.match(r"^([A-Za-z0-9_.-]+):", source_line)
                if target_match:
                    owner = target_match.group(1)
                if current_line_number == line_number:
                    return owner if source_line.startswith("\t") else None
                if current_line_number > line_number:
                    return None
    except OSError:
        return None
    return None


def _ci_failure_category(line, contract_suite):
    """Classify one already-sanitized causal candidate, or return None."""
    import re

    # A rejected unittest identity is a privacy fallback, not an authenticated
    # causal failure. Allow a later redacted exception class to identify the
    # first cause; a header alone still fails with UNKNOWN_FAILURE.
    if line in ("FAIL: unittest identity withheld",
                "ERROR: unittest identity withheld"):
        return None

    if re.search(
            r"(?i)source.sha.*mismatch|source.contract.mismatch|"
            r"contract violation|standards.cochange|SOURCE_CONTRACT_MISMATCH",
            line):
        return "SOURCE_CONTRACT"
    if re.search(
            r"(?i)(?:\.[ch](?::\d+){1,2}|\.cpp(?::\d+){1,2}|"
            r"cc1(?:plus)?):\s*(?:fatal )?error:|"
            r"undefined reference to|linker command failed|collect2: error:",
            line):
        return "NATIVE_COMPILE"
    if re.search(
            r"(?i)^INFRASTRUCTURE: cannot start test:|"
            r"no space left on device|temporary failure resolving|"
            r"could not resolve host|failed to fetch|network is unreachable|"
            r"connection timed out|unable to locate package|runner image",
            line):
        return "INFRASTRUCTURE"
    if re.search(
            r"(?i)(?:^|\b)PermissionError:|"
            r"^(?:FAIL:|ERROR:|BLOCKED:|sudo:|bash:).*(?:"
            r"operation not permitted|permission denied|"
            r"insufficient permissions|BLOCKED_LOADED_QUALIFICATION|password)|"
            r"^BLOCKED_LOADED_QUALIFICATION",
            line):
        return "HOST_PERMISSION"
    if re.search(
            r"(?i)AssertionError:|^E\s+AssertionError|"
            r"(?:RuntimeError|ValueError|TypeError|KeyError|IndexError|"
            r"AttributeError|OSError|TimeoutError|FileNotFoundError|"
            r"(?:subprocess\.)?(?:CalledProcessError|TimeoutExpired)|"
            r"SystemExit):|"
            r"AddressSanitizer|UndefinedBehaviorSanitizer|runtime error:|"
            r"Assertion .* failed|Aborted(?: \(core dumped\))?|SIGABRT|"
            r"terminate called after throwing|"
            r"make(?:\[\d+\])?: \*\*\* \[[^\]]+\] Error (?:134|139)\b",
            line):
        return "SOURCE_CONTRACT" if contract_suite else "RUNTIME_ASSERTION"
    if re.search(r"^FAIL:(?!\s+test_)\s+|^BLOCKED:\s+", line):
        return "SOURCE_CONTRACT" if contract_suite else "RUNTIME_ASSERTION"
    return None


def diagnose_ci_failure(lines, exit_code, suite):
    """Keep the originating failure and its first trustworthy diagnostic together.

    exit_code belongs to the wrapped process. A validated native-rootless
    marker may additionally report an earlier child status; neither replaces
    the other. Malformed or out-of-suite marker-shaped child output is never
    promoted into public attribution.
    """
    import re
    import signal

    first_error = None
    first_category = None
    recent_error = None
    recent_category = None
    fallback = None
    failing_test = None
    unittest_header = None
    unittest_error = None
    unittest_category = None
    first_unittest_active = False
    unittest_contract_context = False
    make_target = None
    first_make_failure = None
    rootless_failure = None
    rootless_detail = None
    rootless_marker_seen = False
    contract_suite = any(name in suite for name in
                         ("contract", "policy", "interface", "layout"))
    # test-rootless.sh emits only the basename of its source-controlled phase.
    # Exclude path separators so arbitrary child output cannot promote a path.
    rootless_pattern = re.compile(
        r"^FAIL: rootless phase=(?P<phase>[A-Za-z0-9_.: -]{1,128}) "
        r"subtest=(?P<subtest>[a-z0-9-]{1,64}|unavailable) "
        r"test=(?P<test>test_[A-Za-z0-9_]{1,96}|"
        r"swapz-primary-late-race-test[.]py|"
        r"swapzctl-trial-ownership-test[.]py|"
        r"swapzctl-status|swapzctl-watch|swapz-primary-policy|"
        r"swapz-primary-mount-namespace|unavailable) "
        r"exit=(?P<exit>[0-9]{1,3}) "
        r"reason=(?P<reason>nonzero_exit|native_compile|timeout_or_exit_124|"
        r"signal_or_child_exit|received_TERM|received_INT|"
        r"unittest_assertion|unittest_error|unittest_timeout|"
        r"stderr_relay_failure|stderr_relay_cleanup_failure) "
        r"phase_s=[0-9]+ stage_s=[0-9]+ "
        r"line=(?:[0-9]+|unavailable) "
        r"log=(?P<log>unavailable|build/tests/rootless-failure\."
        r"[A-Za-z0-9]{8}/diagnostic\.log)$")
    rootless_detail_pattern = re.compile(
        r"^Reason: exit=(?P<exit>[0-9]{1,3}) "
        r"reason=(?P<reason>nonzero_exit|native_compile|timeout_or_exit_124|"
        r"signal_or_child_exit|received_TERM|received_INT|"
        r"unittest_assertion|unittest_error|unittest_timeout|"
        r"stderr_relay_failure|stderr_relay_cleanup_failure) "
        r"subtest=(?P<subtest>[a-z0-9-]{1,64}|unavailable) "
        r"phase_wall_s=[0-9]+ stage_wall_s=[0-9]+ "
        r"line=(?:[0-9]+|unavailable) "
        r"log=(?P<log>unavailable|build/tests/rootless-failure\."
        r"[A-Za-z0-9]{8}/diagnostic\.log) "
        r"first_errno=(?P<errno>[1-9][0-9]{0,3}|unavailable) "
        r"cleanup=(?P<cleanup>not_independently_verified|"
        r"relay_incomplete|relay_cleanup_failed)$")

    for raw_line in lines:
        safe_line = _ci_safe_line(raw_line)
        if not safe_line:
            continue

        unittest_match = re.search(
            r"^(?:FAIL|ERROR):\s+"
            r"(test_[A-Za-z0-9_]+|setUp(?:Class|Module)?|"
            r"tearDown(?:Class|Module)?)\s+\(([^)]+)\)",
            safe_line)
        if unittest_match:
            # A later teardown heading cannot borrow an exception already
            # observed after a rejected first unittest identity. Standalone
            # teardown failures with no earlier cause remain attributable.
            if (failing_test is None and not (
                    first_error is not None and
                    unittest_match.group(1).startswith("tearDown"))):
                failing_test = _ci_unittest_name(
                    unittest_match.group(1), unittest_match.group(2))
                unittest_header = safe_line
                first_unittest_active = True
            else:
                # Later unittest blocks (including teardown) cannot donate
                # their exception to the first failed test.
                first_unittest_active = False
            continue

        if first_unittest_active and re.search(
                r"(?:^|[/\\])(?:source-contract|make-interface)-test\.py\b",
                safe_line):
            unittest_contract_context = True

        rootless_match = (
            rootless_pattern.fullmatch(safe_line)
            if suite == "native-rootless" else None)
        if rootless_match is not None and rootless_match.group("test") in (
                "swapzctl-status", "swapzctl-watch",
                "swapz-primary-policy",
                "swapz-primary-mount-namespace",
                "swapzctl-trial-ownership-test.py"):
            # The producer verifies these fixed binaries or the rootless
            # ownership fixture against its test-userspace Make recipe.
            # Reject cross-phase identity claims.
            if not (rootless_match.group("phase") ==
                    "Makefile native and metadata" and
                    rootless_match.group("subtest") == "test-userspace" and
                    rootless_match.group("reason") == "nonzero_exit" and
                    rootless_match.group("exit") == "2"):
                rootless_match = None
        if safe_line.startswith("FAIL: rootless "):
            # The final marker owns the failing-suite boundary. An invalid
            # final marker must also revoke any earlier valid attribution.
            # Marker-shaped child output is never a causal FAIL line.
            if suite == "native-rootless":
                rootless_marker_seen = True
            rootless_failure = (
                rootless_match.groupdict() if rootless_match else None)
            rootless_detail = None
            continue

        rootless_detail_match = (
            rootless_detail_pattern.fullmatch(safe_line)
            if suite == "native-rootless" and rootless_failure is not None
            else None)
        if rootless_detail_match:
            candidate_detail = rootless_detail_match.groupdict()
            if all(candidate_detail[key] == rootless_failure[key]
                   for key in ("exit", "reason", "subtest", "log")):
                errno_value = candidate_detail["errno"]
                if (errno_value == "unavailable" or
                        int(errno_value) <= 4095):
                    rootless_detail = candidate_detail
            continue

        if (first_make_failure is None and suite == "native-rootless"
                and safe_line.startswith("make")):
            make_failure_match = re.fullmatch(
                r"make(?:\[\d+\])?: \*\*\* "
                r"\[Makefile:([0-9]+): ([a-z0-9-]{1,64})\] Error [0-9]+",
                safe_line)
            if (make_failure_match and
                    _ci_make_recipe_owner(
                        int(make_failure_match.group(1))) ==
                    make_failure_match.group(2)):
                first_make_failure = (
                    safe_line, make_failure_match.group(2))

        if make_target is None:
            make_match = re.search(
                r"make(?:\[\d+\])?: \*\*\* "
                r"\[[^:\]]+:\d+:\s*([^\]]+)\] Error \d+",
                safe_line)
            if make_match:
                make_target = "make:" + make_match.group(1).strip()

        if fallback is None and re.search(
                r"(?i)\b(?:FAIL|ERROR|BLOCKED):|"
                r"make(?:\[\d+\])?: \*\*\*|FAILED \(",
                safe_line):
            fallback = safe_line

        category = _ci_failure_category(
            safe_line, contract_suite or
            (first_unittest_active and unittest_contract_context))
        if first_unittest_active and unittest_error is None and category:
            unittest_error = safe_line
            unittest_category = category
        if category:
            if first_error is None:
                first_error = safe_line
                first_category = category
            recent_error = safe_line
            recent_category = category

    child_exit_code = (int(rootless_failure["exit"])
                       if rootless_failure is not None else None)
    effective_exit_code = (child_exit_code if child_exit_code is not None
                           else exit_code)
    rootless_reason = (rootless_failure["reason"]
                       if rootless_failure is not None else None)
    rootless_test = (
        rootless_failure["test"]
        if rootless_failure is not None and
        rootless_failure["test"] != "unavailable" else None)
    phase = rootless_failure["phase"] if rootless_failure else suite
    rootless_marker_invalid = (
        suite == "native-rootless" and rootless_marker_seen and
        rootless_failure is None)
    if rootless_marker_invalid:
        # Once the aggregate runner emits an invalid final marker, no raw child
        # unittest or Make-shaped line may donate public failure identity.
        failing_test = None
        unittest_header = None
        unittest_error = None
        unittest_category = None
        make_target = None
    if rootless_failure is not None:
        # A validated rootless marker is authoritative for unittest identity.
        # Do not let reordered detailed blocks or partial relay bytes donate a
        # different test/exception to the public CI diagnostic.
        failing_test = None
        unittest_header = None
        unittest_error = None
        unittest_category = None
    compile_phase = (
        phase == "Makefile native and metadata" or phase.startswith("C syntax:"))
    rootless_late_race_identity = (
        rootless_failure is not None and
        rootless_failure["test"] == "swapz-primary-late-race-test.py")
    rootless_native_compile = (
        rootless_late_race_identity and rootless_reason == "native_compile"
        and child_exit_code == 2
        and phase == "Makefile native and metadata"
        and rootless_failure["subtest"] == "compile")
    rootless_invalid_late_race_identity = (
        rootless_late_race_identity and not rootless_native_compile)
    if rootless_invalid_late_race_identity:
        # The filename is public only as part of the exact authenticated
        # generated-C compile envelope.
        rootless_test = None
    # The producer runs bash -n for this fixed phase family. A status-two
    # failure identifies that source check, not a test assertion or parser
    # detail. Syntax-loop phases never carry unittest or nested-subtest identity.
    rootless_shell_syntax_check_failed = (
        rootless_failure is not None and rootless_reason == "nonzero_exit"
        and child_exit_code == 2
        and rootless_failure["subtest"] == "unavailable"
        and rootless_failure["test"] == "unavailable"
        and re.fullmatch(r"bash syntax [A-Za-z0-9_.-]{1,64}", phase)
        is not None)

    if rootless_marker_invalid:
        causal_error = "rootless failure marker malformed or unverified"
        category = "UNKNOWN_FAILURE"
    elif failing_test is not None:
        causal_error = unittest_error or unittest_header
        category = unittest_category or (
            "SOURCE_CONTRACT" if contract_suite or unittest_contract_context
            else "UNKNOWN_FAILURE")
        if unittest_error is None and rootless_reason == "unittest_assertion":
            category = "RUNTIME_ASSERTION"
        elif unittest_error is None and rootless_reason == "unittest_timeout":
            category = "INFRASTRUCTURE"
    elif rootless_failure is not None:
        # The outer runner gives us an exact phase. For a generic nonzero
        # child, accept only a diagnostic adjacent to that final marker, except
        # that a compile phase keeps its first compiler error even if verbose
        # compiler output separates it from the marker. This prevents expected
        # negative output from an earlier passing suite becoming the cause.
        if rootless_invalid_late_race_identity:
            # Invalid late-race identity cannot borrow an earlier Make or
            # compiler error, even under a generic failure reason.
            causal_error = None
            category = None
        elif rootless_shell_syntax_check_failed:
            # Earlier passing suites may have printed expected FAIL/BLOCKED
            # diagnostics mentioning this script. The validated phase wins.
            causal_error = None
            category = None
        elif (rootless_reason == "nonzero_exit" and
              phase == "Makefile native and metadata" and
              rootless_failure["subtest"] != "unavailable"):
            # A later parallel Make or compiler error cannot override the
            # first nested target authenticated by the rootless marker.
            if (first_make_failure is not None and
                    first_make_failure[1] == rootless_failure["subtest"]):
                causal_error = first_make_failure[0]
                category = _ci_failure_category(causal_error, contract_suite)
            else:
                causal_error = None
                category = None
        elif (rootless_reason == "nonzero_exit" and
                first_category == "NATIVE_COMPILE" and compile_phase):
            causal_error = first_error
            category = first_category
        elif (rootless_reason == "nonzero_exit" and
              phase == "Makefile native and metadata"):
            # No target was authenticated; raw child Make text is not a cause.
            causal_error = None
            category = None
        elif (rootless_reason == "nonzero_exit" and
              phase == "test-report-test.py"):
            # This suite runs outside the private rootless unittest classifier.
            # A matching basename in raw child stderr cannot authenticate
            # the assertion or override the generic final failure marker.
            causal_error = None
            category = None
        elif rootless_reason == "nonzero_exit" and recent_error is not None:
            generic_phase_terms = {
                "assertions", "bash", "contract", "executable", "interface",
                "metadata", "native", "runner", "single", "source", "static",
                "syntax", "test", "tests",
            }
            phase_terms = [
                term.lower() for term in
                re.findall(r"[A-Za-z0-9_.-]{5,}", phase)
                if term.lower() not in generic_phase_terms
            ]
            if any(term in recent_error.lower() for term in phase_terms):
                causal_error = recent_error
                category = recent_category
            else:
                causal_error = None
                category = None
        else:
            causal_error = None
            category = None
    else:
        causal_error = first_error or fallback
        category = first_category

    if rootless_test is not None:
        test_name = rootless_test
    elif failing_test is not None:
        test_name = failing_test
    elif rootless_failure:
        test_name = phase
        if (not rootless_invalid_late_race_identity and
                rootless_failure["subtest"] != "unavailable"):
            test_name += "[" + rootless_failure["subtest"] + "]"
    else:
        test_name = make_target or suite

    termination = None
    if exit_code < 0:
        try:
            termination = "signal " + signal.Signals(-exit_code).name
        except ValueError:
            termination = "signal " + str(-exit_code)

    if rootless_failure is not None and causal_error is None:
        marker_reason = ("rootless phase=" + phase + " reason=" +
                         rootless_reason + " child_exit=" +
                         str(child_exit_code))
        if rootless_test is not None:
            marker_reason += " test=" + rootless_test
        marker_reason += " log=" + rootless_failure["log"]
        if rootless_invalid_late_race_identity:
            status, category = "FAIL", "UNKNOWN_FAILURE"
            reason = (marker_reason +
                      " (late-race attribution fields did not authenticate)")
        elif rootless_shell_syntax_check_failed:
            status, category = "FAIL", "SOURCE_CONTRACT"
            reason = (marker_reason +
                      " (bash -n source check exited 2; inspect private "
                      "log for the exact cause)")
        elif rootless_reason == "timeout_or_exit_124":
            status, category = "FAIL", "INFRASTRUCTURE"
            reason = (marker_reason +
                      " (124 is timeout-or-child-exit; watchdog not proven)")
        elif rootless_reason == "signal_or_child_exit":
            status, category = "FAIL", "UNKNOWN_FAILURE"
            reason = (marker_reason +
                      " (signal-style shell status and explicit child exit "
                      "are indistinguishable)")
        elif rootless_reason in ("received_TERM", "received_INT"):
            status, category = "CANCELLED", "CANCELLATION"
            reason = (marker_reason +
                      " (runner received an interrupt; origin not proven)")
        elif rootless_native_compile:
            status, category = "FAIL", "NATIVE_COMPILE"
            reason = marker_reason
        elif rootless_reason == "native_compile":
            status, category = "FAIL", "UNKNOWN_FAILURE"
            reason = (marker_reason +
                      " (native compile attribution fields did not authenticate)")
        elif rootless_reason in ("unittest_assertion", "unittest_error"):
            status = "FAIL"
            category = ("SOURCE_CONTRACT"
                        if phase in ("source-contract-test.py",
                                     "make-interface-test.py")
                        else "RUNTIME_ASSERTION")
            reason = marker_reason
        elif rootless_reason == "unittest_timeout":
            status, category = "FAIL", "RUNTIME_ASSERTION"
            reason = marker_reason
        elif rootless_reason in (
                "stderr_relay_failure", "stderr_relay_cleanup_failure"):
            status, category = "FAIL", "INFRASTRUCTURE"
            reason = marker_reason
        else:
            status = "FAIL"
            category = "SOURCE_CONTRACT" if contract_suite else "UNKNOWN_FAILURE"
            reason = marker_reason
        causal_error = reason
    elif causal_error:
        status = "FAIL"
        reason = causal_error
        category = category or (
            "SOURCE_CONTRACT" if contract_suite else "UNKNOWN_FAILURE")
    elif effective_exit_code in (130, 143, -2, -15):
        # Preserve existing top-level cancellation classification where no
        # rootless marker can disambiguate shell 128+signal-style statuses.
        status, category = "CANCELLED", "CANCELLATION"
        reason = "execution interrupted; cancellation cause not proven"
        causal_error = reason
    elif effective_exit_code == 124:
        status, category = "FAIL", "INFRASTRUCTURE"
        reason = "command timed out or child returned 124; watchdog not proven"
        causal_error = reason
    elif effective_exit_code == 127:
        status, category = "FAIL", "INFRASTRUCTURE"
        reason = "executable could not start or child returned 127"
        causal_error = reason
    elif termination:
        status = "FAIL"
        category = ("RUNTIME_ASSERTION" if -exit_code in (6, 7, 8, 11)
                    else "UNKNOWN_FAILURE")
        reason = "child terminated by " + termination
        causal_error = reason
    else:
        status = "FAIL"
        category = "SOURCE_CONTRACT" if contract_suite else "UNKNOWN_FAILURE"
        reason = "command exited without a recognizable causal diagnostic"
        causal_error = reason

    expected_contract = {
        "NATIVE_COMPILE": "native source compiles and links",
        "SOURCE_CONTRACT": "source and policy contracts hold",
        "RUNTIME_ASSERTION": "test assertions and runtime contracts hold",
        "HOST_PERMISSION": "required rootless access is available",
        "INFRASTRUCTURE": "required runner tools and execution complete",
        "CANCELLATION": "test runs to an uninterrupted conclusion",
    }.get(category, "test command completes successfully")

    if rootless_shell_syntax_check_failed:
        expected_contract = "source-controlled shell script passes bash -n"

    # A child can print plausible OSError or launch-error text. Only the
    # runner's caught OSError or matching private rootless detail proves errno.
    first_errno = None
    cleanup_disposition = {
        "stderr_relay_failure": "relay_incomplete",
        "stderr_relay_cleanup_failure": "relay_cleanup_failed",
    }.get(rootless_reason, "not_independently_verified")
    if rootless_detail is not None:
        cleanup_disposition = rootless_detail["cleanup"]
        if rootless_detail["errno"] != "unavailable":
            first_errno = int(rootless_detail["errno"])
    result = {
        "status": status, "category": category,
        "test": test_name, "phase": phase,
        "first_error": causal_error, "reason": reason,
        "expected_contract": expected_contract, "observed": causal_error,
        "exit_code": exit_code, "first_exit_code": effective_exit_code,
        "first_errno": first_errno,
        "cleanup_disposition": cleanup_disposition,
        "prerequisite": {
            "NATIVE_COMPILE": "hosted Ubuntu compiler, headers, liblz4",
            "HOST_PERMISSION": "unprivileged host filesystem/capability access",
            "INFRASTRUCTURE": "hosted runner, network, disk and tooling",
            "CANCELLATION": "uninterrupted exact-SHA GitHub Actions run",
            "SOURCE_CONTRACT": "direct source, Make and policy consistency",
            "RUNTIME_ASSERTION": "rootless runtime fixture and assertions",
        }.get(category, "inspect the retained failure log"),
    }
    if child_exit_code is not None:
        result["child_exit_code"] = child_exit_code
        result["rootless_reason"] = rootless_reason
        # Keep Bash's validated, relative mode-0600 pointer independent of
        # which sanitized line becomes first_error (including Make Error 134).
        if rootless_failure["log"] != "unavailable":
            result["rootless_private_log"] = rootless_failure["log"]
    if termination:
        result["termination"] = termination
    return result


def _ci_retain_log(record, destination, diagnostic):
    """Save bounded sanitized failure evidence plus its exact-SHA diagnosis."""
    import re
    from collections import deque

    record.seek(0)
    beginning, recent, errors = [], deque(maxlen=96), []
    first_bytes = 0
    for raw_line in _ci_record_lines(record):
        line = _ci_safe_line(raw_line)
        if not line:
            continue
        if first_bytes < 12000:
            beginning.append(line)
            first_bytes += len(line) + 1
        recent.append(line)
        if len(errors) < 16 and re.search(
                r"(?i)error:|assertionerror|FAIL:|BLOCKED:|"
                r"permission denied|operation not permitted|"
                r"source.contract.mismatch", line):
            errors.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output:
        output.write("SWAPZ_CI_FAILURE=" +
                     json.dumps(diagnostic, sort_keys=True) + "\n")
        for label, lines in (("FIRST", beginning), ("FIRST ERRORS", errors),
                             ("LAST", recent)):
            output.write("=== " + label + " (sanitized, bounded) ===\n")
            for line in lines:
                output.write(line + "\n")


def _ci_rootless_success_timing_summary(record, harness_source):
    """Return five slowest trusted rootless phases; never report child text.

    The suite is already successful. Only numeric durations and phase labels
    derived from the tested source are publishable; everything else stays
    in the CI-only temporary capture. This is observational, not a PASS gate.
    """
    import re

    allowed_labels = set(re.findall(
        r"(?m)^rootless_phase='([^'\r\n]{1,120})'$", harness_source))
    # The Bash syntax loop derives its labels from literal, source-controlled
    # relative filenames. Do not admit arbitrary child-provided identifiers.
    syntax_block = harness_source.split("for script in ", 1)
    if len(syntax_block) == 2:
        source_paths = syntax_block[1].split("; do", 1)[0]
        allowed_labels.update(
            "bash syntax " + path.rsplit("/", 1)[-1]
            for path in re.findall(
                r"(?:tests|packaging)/[A-Za-z0-9_.-]+"
                r"(?:/[A-Za-z0-9_.-]+)*", source_paths))
    if not allowed_labels:
        return ()

    pattern = re.compile(
        r"ROOTLESS_PHASE_TIMING index=(0|[1-9][0-9]{0,2}) "
        r"elapsed_s=(0|[1-9][0-9]{0,5}) label=(.+)")
    timings = []
    completed = False
    record.seek(0)
    for line in _ci_record_lines(record):
        line = line.rstrip("\r\n")
        if line == ("PASS: rootless C tests, source contracts, Make policy "
                    "and owned-device preflights"):
            completed = True
        if not line.startswith("ROOTLESS_PHASE_TIMING "):
            continue
        if completed:
            return ()
        match = pattern.fullmatch(line)
        if match is None:
            return ()
        index, elapsed = int(match.group(1)), int(match.group(2))
        label = match.group(3)
        if (index != len(timings) or index >= 128 or
                elapsed > 86400 or label not in allowed_labels):
            return ()
        timings.append((index, elapsed, label))
    if not completed or not timings:
        return ()
    return tuple(sorted(timings, key=lambda entry: (-entry[1], entry[0]))[:5])


def _ci_run(argv):
    """Run one rootless CI command, printing only actionable failures."""
    import argparse
    import os
    from pathlib import Path
    import re
    import subprocess
    import tempfile

    parser = argparse.ArgumentParser(description="CI-only rootless diagnostics")
    parser.add_argument("--suite", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", arguments.suite):
        parser.error("invalid suite identifier")
    command = arguments.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command")

    root = Path(__file__).resolve().parents[2]
    tested_sha = os.environ.get("GITHUB_SHA", "")
    job = os.environ.get("GITHUB_JOB", "local-synthetic")
    actual_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
        text=True, check=False).stdout.strip()
    matches_head = (re.fullmatch(r"[0-9a-f]{40}", tested_sha) is not None
                    and actual_sha == tested_sha)
    artifact = os.environ.get(
        "SWAPZ_CI_ARTIFACT_NAME",
        f"project-goals-{job}-{arguments.suite}-{tested_sha}")
    destination = root / "build/ci-logs" / f"{arguments.suite}.log"
    with tempfile.TemporaryFile() as record:
        launch_errno = None
        if not matches_head:
            record.write(b"SOURCE_CONTRACT_MISMATCH: HEAD differs from GITHUB_SHA\n")
            return_code = 1
        else:
            try:
                return_code = subprocess.run(
                    command, cwd=root, stdout=record,
                    stderr=subprocess.STDOUT, check=False).returncode
            except OSError as error:
                # Preserve errno but never publish the executable/path from
                # OSError's repr; command strings are not public diagnostics.
                launch_errno = error.errno
                launch_error = error.strerror or "operating system error"
                record.write((
                    "INFRASTRUCTURE: cannot start test: errno=" +
                    str(launch_errno) + " " + _ci_safe_line(launch_error) +
                    "\n").encode())
                return_code = 127
        if return_code == 0:
            if arguments.suite == "native-rootless":
                # Success output is otherwise private. Publish ONLY a small
                # source-verified timing ranking to identify bottlenecks.
                # A missing/invalid diagnostic must not change the test PASS.
                try:
                    harness = (root / "tests/tools/test-rootless.sh").read_text(
                        encoding="utf-8")
                    timings = _ci_rootless_success_timing_summary(record, harness)
                except (OSError, UnicodeError):
                    timings = ()
                for rank, (index, seconds, label) in enumerate(timings, 1):
                    print(
                        f"SWAPZ_CI_ROOTLESS_SLOW_PHASE rank={rank} "
                        f"index={index} elapsed_s={seconds} label={label}")
            return 0
        record.seek(0)
        result = diagnose_ci_failure(
            _ci_record_lines(record), return_code, arguments.suite)
        result.update({
            "schema": "swapz-ci-diagnostic-v1", "tested_sha": tested_sha,
            "job": job, "suite": arguments.suite, "artifact": artifact,
            "log": f"build/ci-logs/{arguments.suite}.log",
            "run_url": ("https://github.com/k1moradi/swapz/actions/runs/" +
                        os.environ.get("GITHUB_RUN_ID", "unknown")),
        })
        if launch_errno is not None:
            result["launch_errno"] = launch_errno
            result["first_errno"] = launch_errno
        try:
            _ci_retain_log(record, destination, result)
        except OSError as error:
            # A secondary log write cannot replace the original test status.
            result["log"] = "unavailable"
            result["diagnostic_errno"] = error.errno
        message = result["first_error"].replace("%", "%25").replace(
            "\r", "%0D").replace("\n", "%0A")
        print(f"::error title={result['category']} {arguments.suite}::{message}")
        print("SWAPZ_CI_FAILURE=" + json.dumps(result, sort_keys=True))
        return return_code if return_code > 0 else 1


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != "ci-run":
        raise SystemExit("CI-only tool: expected ci-run")
    raise SystemExit(_ci_run(sys.argv[2:]))
