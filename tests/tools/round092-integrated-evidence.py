#!/usr/bin/env python3
"""Offline R092 M3568 trace consistency checks; never physical admission.

Only fabricated evidence is accepted. No host/device inspection, subprocess,
kernel interface, activation or trusted physical-evidence import exists here.
"""
import re

MAX_PAGES = 128
MAX_SEQUENCE = (1 << 64) - 1
SCOPE = ("source", "kernel", "module", "target", "host", "device",
         "parent", "geometry", "partition_table", "swap_uuid", "header",
         "boot", "oracle", "nonce", "workload")
PROTECTION = ("header", "swap_uuid", "partition_table", "parent", "geometry")
GUARDS = ("exact_private_preflight", "source_clean", "owner_scope",
          "exclusive_after_swapoff", "bare_metal", "page_4096",
          "headroom", "pressure_bounded", "no_foreign_traffic")
CLEANUP = ("workload_quiesced", "owned_mapper_drained", "owned_mapper_removed",
           "original_swap_restored", "other_swap_unchanged",
           "no_force", "journal_complete")
MEASURES = ("cpu_ns", "peak_ram_bytes", "physical_write_bytes",
            "logical_bytes", "handoffs", "ordinary_encodes", "capacity_bytes",
            "gc_bytes")


class InvalidEvidence(ValueError):
    """Bounded error category, never an echo of private trace data."""


def require(condition, category):
    if not condition:
        raise InvalidEvidence(category)


def exact(value, fields, category):
    require(type(value) is dict and set(value) == set(fields), category)


def integer(value, low=0, high=MAX_SEQUENCE):
    return type(value) is int and low <= value <= high


def digest(value, length=64):
    return type(value) is str and re.fullmatch(
        r"[0-9a-f]{" + str(length) + r"}", value) is not None


def bytes_hex(value, minimum, maximum):
    require(type(value) is str and minimum * 2 <= len(value) <= maximum * 2
            and len(value) % 2 == 0 and re.fullmatch(r"[0-9a-f]+", value),
            "payload_shape")
    return bytes.fromhex(value)


def checked_scope(scope):
    exact(scope, SCOPE, "scope_fields")
    for key in SCOPE:
        length = 40 if key in ("source", "kernel") else 32 if key == "nonce" else 64
        require(digest(scope[key], length), "scope_digest")


def live_admission(_scope=None, _record=None):
    """Deliberately unconditional refusal, even for a structurally valid trace."""
    return {"admitted": False, "auth": 0, "phase_a": "BLOCKED",
            "reason": "offline_only_no_native_admission"}


def _sequence(events, expected, identity, previous):
    require(type(events) is list and len(events) == len(expected), "event_count")
    for event, name in zip(events, expected):
        exact(event, ("step", "sequence", "identity"), "event_fields")
        require(event["step"] == name and event["identity"] == identity,
                "event_order_or_identity")
        require(integer(event["sequence"], previous + 1), "event_sequence")
        previous = event["sequence"]
    return previous


def _page(page, scope, previous, seen):
    fields = ("identity", "scope", "outcome", "codec", "version", "dictionary",
              "original_page", "original_compressed", "lower_payload",
              "read_payload", "gc_payload", "pagein", "events",
              "enqueue_count", "claim_count", "recompress_count", "ack_count",
              "lower_complete", "lower_durable", "map_published", "upper_success")
    exact(page, fields, "page_fields")
    require(page["scope"] == scope, "mixed_page_scope")
    identity = page["identity"]
    exact(identity, ("slot", "generation", "folio", "bio", "descriptor",
                     "route_epoch", "credential"), "identity_fields")
    for key in ("slot", "generation", "route_epoch"):
        require(integer(identity[key], 0 if key == "slot" else 1), "identity_number")
    for key in ("folio", "bio", "descriptor", "credential"):
        require(digest(identity[key]), "identity_digest")
    # No second accepted descriptor, repeated BIO or repeated source credential.
    for key in ("bio", "descriptor", "credential"):
        require(identity[key] not in seen[key], "duplicate_identity")
        seen[key].add(identity[key])
    slot_generation = (identity["slot"], identity["generation"])
    require(slot_generation not in seen["slot_generation"], "duplicate_generation")
    seen["slot_generation"].add(slot_generation)
    require(type(page["codec"]) is int and page["codec"] in (1, 2)
            and type(page["version"]) is int and page["version"] == 1
            and page["dictionary"] is False, "original_profile")
    full = bytes_hex(page["original_page"], 4096, 4096)
    compressed = bytes_hex(page["original_compressed"], 1, 3568)
    outcome = page["outcome"]
    prefix = ["eviction", "enqueue_unclaimed", "ordered_head", "reserve"]
    if outcome == "typed_success":
        steps = prefix + ["claim", "lower_complete", "lower_durable",
                          "map_publish", "upper_ack", "read", "gc_move",
                          "read_after_gc", "overwrite", "discard"]
        require(all(page[key] is True for key in
                    ("lower_complete", "lower_durable", "map_published",
                     "upper_success")), "durable_publication")
        for key in ("lower_payload", "read_payload", "gc_payload"):
            require(bytes_hex(page[key], 1, 3568) == compressed, "compressed_bytes")
        require(bytes_hex(page["pagein"], 4096, 4096) == full, "page_oracle")
        counts = (1, 1, 0, 1)
    elif outcome == "preclaim_decline":
        steps = prefix + ["claim_refused", "cancel", "ordinary_fallback",
                          "ordinary_lower_complete", "ordinary_lower_durable",
                          "ordinary_map_publish", "ordinary_upper_ack", "read"]
        require(all(page[key] is True for key in
                    ("lower_complete", "lower_durable", "map_published",
                     "upper_success")), "ordinary_durability")
        require(all(page[key] is None for key in
                    ("lower_payload", "read_payload", "gc_payload")), "decline_typed_payload")
        require(bytes_hex(page["pagein"], 4096, 4096) == full, "page_oracle")
        counts = (1, 0, 1, 1)
    elif outcome == "claimed_error":
        steps = prefix + ["claim", "lower_error", "quarantine", "upper_error_redirty"]
        require(all(page[key] is False for key in
                    ("lower_complete", "lower_durable", "map_published",
                     "upper_success")), "failed_claim_publication")
        require(all(page[key] is None for key in
                    ("lower_payload", "read_payload", "gc_payload", "pagein")),
                "failed_claim_payload")
        counts = (1, 1, 0, 1)
    else:
        raise InvalidEvidence("outcome")
    for key, expected in zip(("enqueue_count", "claim_count", "recompress_count",
                              "ack_count"), counts):
        require(type(page[key]) is int and page[key] == expected, "ownership_counts")
    return _sequence(page["events"], steps, identity, previous), outcome


def validate_model(record, expected_scope):
    """Check modeled trace consistency, not provenance or native behavior."""
    checked_scope(expected_scope)
    exact(record, ("schema", "mode", "proof_kind", "scope", "guards",
                   "preflight_kind", "protected_before", "protected_after",
                   "cleanup", "pages", "baseline", "integrated"), "record_fields")
    require(record["schema"] == "swapz-r092-integrated-model-v1"
            and record["mode"] == "integrated_natural_pressure", "mode")
    require(record["proof_kind"] == "fabricated_model_only", "untrusted_physical_claim")
    checked_scope(record["scope"])
    require(record["scope"] == expected_scope, "wrong_scope")
    exact(record["guards"], GUARDS, "guard_fields")
    require(all(record["guards"][key] is True for key in GUARDS), "guard_refused")
    require(record["preflight_kind"] in ("exact_private_reuse", "one_narrow_fast_test"),
            "preflight_kind")
    protected = {key: expected_scope[key] for key in PROTECTION}
    require(record["protected_before"] == protected
            and record["protected_after"] == protected, "protected_identity")
    exact(record["cleanup"], CLEANUP, "cleanup_fields")
    require(all(record["cleanup"][key] is True for key in CLEANUP), "cleanup_required")
    pages = record["pages"]
    require(type(pages) is list and 3 <= len(pages) <= MAX_PAGES, "page_count")
    seen = {key: set() for key in ("bio", "descriptor", "credential", "slot_generation")}
    previous = 0
    outcomes = {"typed_success": 0, "preclaim_decline": 0, "claimed_error": 0}
    for page in pages:
        previous, outcome = _page(page, expected_scope, previous, seen)
        outcomes[outcome] += 1
    require(all(outcomes.values()), "missing_outcome")
    for key in ("baseline", "integrated"):
        arm = record[key]
        exact(arm, ("scope", "handoff_enabled", "metrics"), "arm_fields")
        require(arm["scope"] == expected_scope
                and arm["handoff_enabled"] is (key == "integrated"), "arm_scope")
        exact(arm["metrics"], MEASURES, "metric_fields")
        require(all(integer(arm["metrics"][name]) for name in MEASURES), "metric_value")
        require(all(arm["metrics"][name] > 0 for name in
                    ("cpu_ns", "peak_ram_bytes", "physical_write_bytes",
                     "logical_bytes", "capacity_bytes")), "metric_missing")
    baseline, integrated = (record[key]["metrics"] for key in ("baseline", "integrated"))
    require(baseline["handoffs"] == 0
            and integrated["handoffs"] == outcomes["typed_success"]
            and integrated["ordinary_encodes"] == outcomes["preclaim_decline"]
            and baseline["logical_bytes"] == integrated["logical_bytes"]
            and baseline["capacity_bytes"] == integrated["capacity_bytes"],
            "metric_attribution")
    return {"status": "MODEL_CONSISTENT", "actual_physical_io": False,
            "source_mapped_authenticated": False, "live_admission": False,
            "phase_a": "BLOCKED", "outcomes": outcomes, "pages": len(pages)}
