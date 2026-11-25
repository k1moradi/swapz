#!/usr/bin/env python3
"""Read-only adapter for supplied frozen R092 DM INFO snapshots.

No device discovery, subprocess, sysfs, trace activation or privileged access.
Scope is caller-provided, not authenticated. This adapter can report aggregate
observations only; no input can grant integrated physical admission.
"""
import json
import re
import sys

MAPPING_SOURCE = "78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea"
DM_BLOB = "420751247bdfd0be9c7271b180ee5cfcc7ca5d92"
MM_OVERLAY_BLOB = "62db468c14f23b59e7adaae65a11dcb9969f02b3"
MAX_STATUS_BYTES = 65536
MAX_INPUT_BYTES = 256 * 1024
MAX_U64 = (1 << 64) - 1
SCOPE_LENGTHS = {
    "source": 40, "linux_source": 40, "kernel_sha256": 64,
    "module_sha256": 64, "host_scope_sha256": 64,
    "device_scope_sha256": 64, "boot_sha256": 64,
    "target_scope_sha256": 64, "run_nonce": 32, "workload_sha256": 64,
}
LINUX_SOURCE = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
COUNTERS = (
    "logical_write", "logical_read", "physical_write", "physical_write_reqs",
    "physical_read", "physical_read_reqs", "compressed", "raw", "zero_elided",
    "discarded", "lz4_attempts", "lz4_accepted_bytes",
    "verified_zswap_origin_admitted",
    "foreground_committed_verified_zswap_writeback",
)
GAUGES = ("authority_metadata_ram", "read_payload_cache_ram")
MISSING_NATIVE_PROOF = (
    "authenticated_capture_scope",
    "natural_mm_eviction_and_selected_clone_same_bio",
    "original_credential_and_retained_compressed_bytes",
    "independent_4096_byte_oracle_and_decode",
    "same_descriptor_reserve_claim_cancel",
    "actual_lower_completion_and_fua_or_flush",
    "map_publication_and_exactly_once_upper_ack",
    "read_gc_relocation_overwrite_discard_and_fallback",
    "protected_header_uuid_table_and_safe_cleanup",
    "matched_cpu_ram_capacity_and_handoff_attribution",
)


class InvalidSnapshot(ValueError):
    """Only bounded error categories, never caller-supplied details."""


def require(condition, category):
    if not condition:
        raise InvalidSnapshot(category)


def exact_fields(record, fields):
    require(type(record) is dict and set(record) == set(fields), "fields")


def scope_checked(scope):
    exact_fields(scope, SCOPE_LENGTHS)
    for key, length in SCOPE_LENGTHS.items():
        require(type(scope[key]) is str and len(scope[key]) == length
                and re.fullmatch(r"[0-9a-f]+", scope[key]), "scope_format")
    require(scope["source"] == MAPPING_SOURCE and
            scope["linux_source"] == LINUX_SOURCE, "unmapped_source")


def parse_status(status):
    """Extract only explicitly mapped DM INFO fields; ignore other counters."""
    require(type(status) is str and 0 < len(status) <= MAX_STATUS_BYTES
            and status.isascii(), "status_size_or_encoding")
    require("\n" not in status.rstrip("\n") and "\r" not in status
            and "\0" not in status and not status.endswith("\n\n"),
            "status_record")
    selected = {}
    wanted = set(COUNTERS + GAUGES + ("mode", "version", "origin_carrier_compiled"))
    for token in status.split():
        key, separator, value = token.partition("=")
        require(key != "status_snapshot_error", "producer_snapshot_error")
        if key not in wanted:
            continue
        require(separator and key not in selected, "duplicate_or_malformed_field")
        if key in ("mode", "version"):
            require(re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value), "status_metadata")
            selected[key] = value
        else:
            require(re.fullmatch(r"0|[1-9][0-9]{0,19}", value), "counter_format")
            number = int(value)
            require(number <= MAX_U64, "counter_overflow")
            selected[key] = number
    require(set(selected) == wanted, "missing_status_field")
    require(selected["mode"] == "alpha-live-gc" and
            selected["origin_carrier_compiled"] in (0, 1), "status_mode")
    return selected


def collect(expected_scope, before, after):
    scope_checked(expected_scope)
    samples = []
    times = []
    for sample in (before, after):
        exact_fields(sample, ("scope", "monotonic_ns", "dm_info"))
        scope_checked(sample["scope"])
        require(sample["scope"] == expected_scope, "mixed_scope")
        timestamp = sample["monotonic_ns"]
        require(type(timestamp) is int and 0 < timestamp <= MAX_U64, "sample_time")
        times.append(timestamp)
        samples.append(parse_status(sample["dm_info"]))
    require(times[0] < times[1], "sample_order")
    first, last = samples
    for key in ("version", "mode", "origin_carrier_compiled"):
        require(first[key] == last[key], "status_identity_changed")
    deltas = {}
    for key in COUNTERS:
        require(last[key] >= first[key], "counter_regressed")
        deltas[key] = last[key] - first[key]
    # Do not equate verified origin/foreground counters to typed handoffs or
    # upper ACKs: ordinary writes also contribute, and snapshots are advisory.
    return {
        "status": "AGGREGATE_OBSERVATIONS_ONLY",
        "mapping_source": MAPPING_SOURCE,
        "dm_blob": DM_BLOB, "mm_overlay_blob": MM_OVERLAY_BLOB,
        "interval_ns": times[1] - times[0],
        "origin_carrier_compiled": last["origin_carrier_compiled"],
        "counter_deltas": deltas,
        "ram_gauges_before": {key: first[key] for key in GAUGES},
        "ram_gauges_after": {key: last[key] for key in GAUGES},
        "missing_native_proof": list(MISSING_NATIVE_PROOF),
        "source_mapped_authenticated": False, "actual_physical_io": False,
        "live_admission": False, "phase_a": "BLOCKED",
    }


def unique_object(pairs):
    record = {}
    for key, value in pairs:
        require(key not in record, "duplicate_json_key")
        record[key] = value
    return record


def main():
    # The only input is an explicitly supplied capture on stdin. Never open a
    # device or infer scope from the host. No raw status or identity is echoed.
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        require(len(raw) <= MAX_INPUT_BYTES, "input_size")
        record = json.loads(raw, object_pairs_hook=unique_object)
        exact_fields(record, ("expected_scope", "before", "after"))
        result = collect(record["expected_scope"], record["before"], record["after"])
    except InvalidSnapshot as error:
        print(json.dumps({"status": "BLOCKED", "reason": str(error),
                          "live_admission": False, "phase_a": "BLOCKED"}))
        return 2
    except (ValueError, RecursionError, OSError):
        print('{"status":"BLOCKED","reason":"invalid_input","live_admission":false,"phase_a":"BLOCKED"}')
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
