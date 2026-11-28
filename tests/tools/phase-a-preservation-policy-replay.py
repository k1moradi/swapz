#!/usr/bin/env python3
"""Pure offline counterfactual replay, never a routing/admission implementation.

The pinned R114 host report or its exact, separately pinned lossless projection
of optimized cases is accepted. Projection omits unrelated lanes/micro statistics.
All timings are whole-case paired CPU batches, never page latencies. No training
or held-out claim: thresholds are exploratory, not selected by the replay.
The selector sees only synthetic predecision metadata; outcome labels are used
only after selection. No actual STORED, authority, residency or queue is proven.
"""
import hashlib
import json
import os
import stat
import statistics
import sys

SOURCE_BLOB = "ca98c75e68a92ba456cd450aaaaab60b02995783"
PROJECTION_BLOB = "911bb1be7f5d13991a88d6021c76440bce1d2767"
MAX_INPUT = 256 * 1024
PAGE = 4096
CAP = 3568
CLASSES = (4096, 8192, 16384)
GRID = (512, 768, 1024, 1536, 2048, 2560, CAP)
DEFAULT_LIMIT = 768
CATEGORIES = ("zero", "same", "random", "repeated", "structured", "mixed", "pattern512")
GATES = dict(auth=0, phase_a="BLOCKED", native_qualification="BLOCKED",
             observation="UNKNOWN", compressed_handoff=False, forced_raw=False,
             import_enabled=False, physical="NO_GO", actual_route="ORDINARY",
             actual_preserve_permission=False)
IDENTITY = dict(round=114, agent=4, source_commit="b867fbdcd669c625a5b1e645d4e86d0b8943661f",
                job_id=140868873612, status="TERMINAL_HOST_ATTRIBUTION_PASS",
                optimized="PASS", byte_exact="PASS", auth=0, phase_a="BLOCKED",
                observation="UNKNOWN", compressed_handoff=False, forced_raw=False,
                physical="NO_GO", columns=["logical_id", "original_bytes", "ordinary_bytes", "eligible"],
                categories=list(CATEGORIES), lane_status="PASS")
IDENTITY["import"] = False
CASE_KEYS = {"codec", "stratum", "name", "pages", "eligible", "payload", "byte_exact", "rows", "pairs"}
META_KEYS = {"codec", "length", "version", "dictionary", "stored", "compatible", "hypothetical_authority"}
STATE_KEYS = {"pressure", "read_likelihood", "queue_depth", "packing_budget"}


class Invalid(ValueError):
    """Fixed, non-sensitive reason codes only."""


def require(condition, reason):
    if not condition:
        raise Invalid(reason)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def shape(value, keys):
    return type(value) is dict and value.keys() == keys


def strict_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(right) is dict:
        return left.keys() == right.keys() and all(strict_equal(left[k], v) for k, v in right.items())
    if type(right) is list:
        return len(left) == len(right) and all(strict_equal(a, b) for a, b in zip(left, right))
    return left == right


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_key")
        result[key] = value
    return result


def reject_constant(_):
    raise Invalid("nonfinite_json")


def git_blob(raw):
    return hashlib.sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def project(report):
    """Extract every optimized row and inclusive pair, without changing values."""
    measurements = report["measurements"]
    lane = measurements["results"]["gcc-optimized"]
    identity = {k: report[k] for k in IDENTITY if k not in ("columns", "categories", "lane_status")}
    identity.update(columns=measurements["page_sizes_columns"], categories=measurements["category_order"],
                    lane_status=lane["status"])
    cases = [dict(codec=c["codec"], stratum=c["stratum"], name=c["stratum_name"],
                  pages=c["pages"], eligible=c["eligible"], payload=c["payload_bytes"],
                  byte_exact=c["byte_exact"], rows=c["page_sizes"], pairs=c["pairs"])
             for c in lane["cases"]]
    return dict(source_blob=SOURCE_BLOB, identity=identity, cases=cases)


def load(raw):
    require(type(raw) is bytes and 2 <= len(raw) <= MAX_INPUT, "input_bounds")
    digest = git_blob(raw)
    require(digest in (SOURCE_BLOB, PROJECTION_BLOB), "input_identity")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)
    projection = project(data) if digest == SOURCE_BLOB else data
    return validate(projection), digest


def validate(data):
    require(shape(data, {"source_blob", "identity", "cases"}) and
            data["source_blob"] == SOURCE_BLOB and strict_equal(data["identity"], IDENTITY), "dataset_identity")
    cases = data["cases"]
    require(type(cases) is list and len(cases) == 16, "case_count")
    indexed = {}
    for case in cases:
        require(shape(case, CASE_KEYS), "case_shape")
        codec, stratum = case["codec"], case["stratum"]
        require(integer(codec, 1, 2) and integer(stratum, -1, 6), "case_key")
        key = (codec, stratum)
        require(key not in indexed, "duplicate_case")
        count = 192 if stratum == -1 else 32
        name = "r112_shared" if stratum == -1 else CATEGORIES[stratum]
        require(case["name"] == name and integer(case["pages"], count, count) and
                case["byte_exact"] is True, "case_identity")
        rows = case["rows"]
        require(type(rows) is list and len(rows) == count, "row_count")
        seen = set()
        totals = [0, 0]
        eligible = 0
        for row in rows:
            require(type(row) is list and len(row) == 4, "row_shape")
            logical, original, ordinary, label = row
            require(integer(logical, 0, 223) and integer(original, 1, 8192) and
                    integer(ordinary, 0, PAGE) and integer(label, 0, 1), "row_bounds")
            require(logical not in seen, "duplicate_page")
            seen.add(logical)
            require(not label or (original <= CAP and 0 < ordinary <= PAGE), "eligible_bounds")
            if label:
                eligible += 1
                totals[0] += ordinary
                totals[1] += original
        require(integer(case["eligible"], eligible, eligible) and strict_equal(case["payload"], totals), "case_totals")
        pairs = case["pairs"]
        require(type(pairs) is list and len(pairs) == (20 if eligible else 0), "pair_count")
        require(all(type(pair) is list and len(pair) == 4 and
                    all(integer(n, 1, 10**12) for n in pair) for pair in pairs), "pair_bounds")
        indexed[key] = case
    for codec in (1, 2):
        aggregate = indexed[codec, -1]["rows"]
        shared = [row for s in range(6) for row in indexed[codec, s]["rows"]]
        extra = indexed[codec, 6]["rows"]
        require(sorted(shared) == sorted(aggregate) and
                sorted(r[0] for r in shared) == list(range(192)) and
                sorted(r[0] for r in extra) == list(range(192, 224)), "aggregate_coverage")
    require(sorted((r[0], r[2]) for s in range(7) for r in indexed[1, s]["rows"]) ==
            sorted((r[0], r[2]) for s in range(7) for r in indexed[2, s]["rows"]), "ordinary_cross_codec")
    return indexed


def eligibility(meta, state):
    """Synthetic safety prerequisites, not actual admission or trust."""
    if not shape(meta, META_KEYS) or not shape(state, STATE_KEYS):
        return "unknown_signal"
    if not (integer(meta["codec"], 1, 2) and integer(meta["length"], 1, CAP) and
            integer(meta["version"], 1, 1) and integer(meta["dictionary"], 0, 0)):
        return "unsupported_payload"
    if not all(meta[k] is True for k in ("stored", "compatible", "hypothetical_authority")):
        return "missing_prerequisite"
    if not (integer(state["pressure"], 0, 1000) and integer(state["read_likelihood"], 0, 1000) and
            integer(state["queue_depth"], 0, 64) and integer(state["packing_budget"], 0, 64 * PAGE)):
        return "invalid_state"
    if state["queue_depth"] >= 48 or state["packing_budget"] < PAGE:
        return "backpressure"
    return None


def select(meta, state, limit=DEFAULT_LIMIT):
    """Only predecision inputs. Return hypothetical choice and fixed reason."""
    reason = eligibility(meta, state)
    if reason is not None:
        return False, reason
    if not integer(limit, 128, CAP):
        return False, "invalid_threshold"
    if (meta["codec"] != 1 or not 128 <= meta["length"] <= limit or
            state["pressure"] < 750 or state["read_likelihood"] > 100 or state["queue_depth"] > 16):
        return False, "conservative_default"
    return True, "counterfactual_only"


def pack(lengths, extent):
    """Fixed-class next-fit model, zero skipped, RAW_4096 separate, max64 records."""
    require(extent in CLASSES and type(extent) is int and len(lengths) <= 224, "packing_bounds")
    used = records = allocated = 0
    for length in lengths:
        require(integer(length, 0, PAGE), "packing_length")
        if length == 0:
            continue
        if length == PAGE:
            allocated += PAGE
            continue
        if not records or records == 64 or used + length > extent:
            allocated += extent
            used = records = 0
        used += length
        records += 1
    return allocated


def state(pressure, read_likelihood, queue_depth, packing_budget):
    return dict(pressure=pressure, read_likelihood=read_likelihood,
                queue_depth=queue_depth, packing_budget=packing_budget)


SCENARIOS = {"cold": state(850, 50, 8, 16384), "hot": state(850, 800, 8, 16384),
             "low_pressure": state(300, 50, 8, 16384), "busy": state(850, 50, 32, 16384),
             "congested": state(850, 50, 48, 16384), "tight_budget": state(850, 50, 8, 4095)}


def evaluate(rows, scenario, mode, limit=DEFAULT_LIMIT):
    """Rows are evaluation-only (codec, stratum, logical, original, ordinary, label)."""
    require(mode in ("ordinary", "eligible_always", "conservative") and len(rows) <= 224, "replay_bounds")
    # An external state sequence may be replayed without deriving signals from outcomes.
    states = scenario if type(scenario) is tuple else (scenario,) * len(rows)
    require(len(states) == len(rows), "schedule_length")
    lengths = []
    result = dict(pages=len(rows), selected=0, attempted=0, fallback=0, fallback_bytes=0,
                  ordinary_pages=0, ordinary_bytes=0, payload_bytes=0, baseline_bytes=0,
                  selected_payload_delta=0, selected_ordinary_bytes=0, false_selections=0,
                  byte_regret=0, declined_savings=0, diagnostic_ineligible_attempts=0)
    strata = {s: 0 for s in range(7)}
    selected_by_stratum = {s: 0 for s in range(7)}
    for (codec, stratum, _logical, original, ordinary, label), current_state in zip(rows, states, strict=True):
        meta = dict(codec=codec, length=original, version=1, dictionary=0, stored=True,
                    compatible=True, hypothetical_authority=True)
        # Baseline uses diagnostic eligibility only as an evaluation oracle;
        # the conservative selector never sees it or the ordinary outcome.
        attempt = (mode == "eligible_always" and label == 1 and eligibility(meta, current_state) is None or
                   mode == "conservative" and select(meta, current_state, limit)[0])
        selected = attempt and label == 1
        if attempt:
            result["attempted"] += 1
            if not selected:
                result["diagnostic_ineligible_attempts"] += 1
        if selected:
            result["selected"] += 1
            selected_by_stratum[stratum] += 1
            result["selected_payload_delta"] += original - ordinary
            result["selected_ordinary_bytes"] += ordinary
            result["false_selections"] += int(original > ordinary)
        else:
            result["ordinary_pages"] += 1
            result["ordinary_bytes"] += ordinary
            if mode != "ordinary":
                result["fallback"] += 1
                result["fallback_bytes"] += ordinary
            if label and original < ordinary:
                result["declined_savings"] += ordinary - original
        length = original if selected else ordinary
        lengths.append(length)
        result["baseline_bytes"] += ordinary
        result["payload_bytes"] += length
        regret = length - (min(original, ordinary) if label else ordinary)
        result["byte_regret"] += regret
        strata[stratum] += regret
    result["worst_stratum"] = max(strata.values(), default=0)
    result["selected_by_stratum"] = {CATEGORIES[k]: v for k, v in selected_by_stratum.items()}
    result["selected_payload_inflation_ppm"] = (
        result["selected_payload_delta"] * 10**6 // result["selected_ordinary_bytes"]
        if result["selected_ordinary_bytes"] else None)
    result["regret_by_stratum"] = {CATEGORIES[k]: v for k, v in strata.items()}
    result["fixed_class_bytes"] = [pack(lengths, extent) for extent in CLASSES]
    return result


def whole_case(case):
    """All eligible pages in the case together; one write batch, weighted read batch."""
    pairs = case["pairs"]
    if not pairs:
        return None
    return {"eligible": case["eligible"], "paired_write_batch_delta_ns": statistics.median(p[2]-p[0] for p in pairs),
            "paired_read_batch_delta_ns": statistics.median(p[3]-p[1] for p in pairs),
            "read_weighted_batch_delta_ns": {name: statistics.median(
                ((p[2]-p[0])*1000 + s["read_likelihood"]*(p[3]-p[1])) for p in pairs)/1000
                for name, s in SCENARIOS.items() if name in ("cold", "hot")}}


def replay(indexed):
    results = {}
    # Seven equal external windows; no modeled arrivals/reclaim, timers or feedback.
    windows = ("cold", "hot", "cold", "busy", "congested", "tight_budget", "low_pressure")
    schedule = tuple(SCENARIOS[name] for name in windows for _ in range(32))
    matched = {}
    for codec in (1, 2):
        rows = sorted([(codec, s, *r) for s in range(7) for r in indexed[codec, s]["rows"]], key=lambda r: r[2])
        scenarios = {name: {mode: evaluate(rows, scenario, mode) for mode in
                            ("ordinary", "eligible_always", "conservative")} for name, scenario in SCENARIOS.items()}
        scheduled = {mode: evaluate(rows, schedule, mode) for mode in
                     ("ordinary", "eligible_always", "conservative")}
        # Independently run the same predecision state schedule for the matched twin.
        twin = {mode: evaluate(rows, schedule, mode) for mode in scheduled}
        matched[str(codec)] = strict_equal(scheduled, twin)
        results[str(codec)] = dict(scenarios=scenarios, scheduled=scheduled,
            threshold_grid={str(limit): evaluate(rows, SCENARIOS["cold"], "conservative", limit) for limit in GRID},
            whole_case_cpu={indexed[codec, s]["name"]: whole_case(indexed[codec, s]) for s in range(-1, 7)})
    # Matched anonymous and file-backed shmem get identical scenario metadata;
    # never infer coldness or use backing type as a feature. Do not sum twins.
    return dict(status="OFFLINE_MODEL_ONLY", verdict="NO_GO", generalization="NONE_EXPLORATORY_ONLY",
                policy_limit=DEFAULT_LIMIT, grid=list(GRID), scenario_states=SCENARIOS,
                backing_types=["anonymous", "file_backed_shmem"], schedule_windows=list(windows),
                window_pages=32, matched_backing_results_identical=all(matched.values()),
                results=results, **GATES)


def read_input(path):
    # Only bounded regular files; refuse symlinks, FIFOs and devices.
    before = os.lstat(path)
    require(stat.S_ISREG(before.st_mode), "regular_file_required")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) ==
                (before.st_dev, before.st_ino) and 2 <= info.st_size <= MAX_INPUT, "input_bounds")
        raw = stream.read(MAX_INPUT+1)
        after = os.fstat(stream.fileno())
        require(len(raw) == info.st_size and (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (info.st_size, info.st_mtime_ns, info.st_ctime_ns), "input_changed")
        return raw


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        require(len(argv) == 1, "arguments")
        raw = read_input(argv[0])
        indexed, digest = load(raw)
        result = replay(indexed)
        result.update(input_git_blob=digest, source_report_git_blob=SOURCE_BLOB,
                      input_sha256=hashlib.sha256(raw).hexdigest(),
                      input_kind="full_report" if digest == SOURCE_BLOB else "exact_optimized_projection")
    except Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), **GATES)
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        result = dict(status="BLOCKED", reason="invalid_input", **GATES)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "OFFLINE_MODEL_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
