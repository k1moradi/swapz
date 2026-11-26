#!/usr/bin/env python3
"""Private, rootless, offline byte oracle layered on unchanged SWZOBS2.

Inputs are independently retained expected scope/plan and untrusted capture
wire/sidecar. This checks consistency, not collection provenance or admission.
Never emits seeds, payloads, keys, paths, or digests in diagnostics.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys

_spec = importlib.util.spec_from_file_location(
    "current_observation", Path(__file__).with_name("native-observation-current-export.py"))
current = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(current)
legacy = current.legacy
require = legacy.require
PAGE_BYTES = 4096
MAX_PAGES = 16
MAX_OPERATIONS = 64
MAX_PLAN_BYTES = 65536
MAX_SIDECAR_BYTES = 2 * 1024 * 1024
SCHEMA = "swapz-independent-byte-oracle-v1"
KINDS = {"typed_write": 1, "fallback": 1, "claimed_error": 1,
         "typed_read": 2, "ordinary_write": 3, "discard": 4}
TYPED = {"typed_write", "fallback", "claimed_error", "typed_read"}
WRITES = {"typed_write", "fallback", "claimed_error", "ordinary_write"}
KEY_FIELDS = ("swap_type", "slot", "area_epoch", "store")
ACTION_FIELDS = {"kind", "logical", "generation", "version", "status", "codec", *KEY_FIELDS}
WITNESS_FIELDS = {"operation", "original", "clone", "descriptor", "accept_sequence",
                  "upper_sequence", "pin", "copy_sequence", "input_page",
                  "final_copy", "user_page", "user_status"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("ascii")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def hex_value(value, size):
    return (type(value) is str and len(value) == 2 * size and
            re.fullmatch("[0-9a-f]+", value) is not None)


def reference_page(seed, nonce, logical, version):
    """Independent compressible page: 64 independently derived 64-byte repeated blocks.

    Each 64-byte block repeats an independently derived 8-byte word eight
    times. Page/version/nonce domain separation prevents stale-page aliasing.
    No decoder, recorder, observed digest or observed byte is an input.
    """
    require(hex_value(seed, 32) and hex_value(nonce, 16) and
            integer(logical, 1, (1 << 32) - 1) and
            integer(version, 1, (1 << 64) - 1), "reference_input")
    prefix = (b"swapz-private-page-v1\0" + bytes.fromhex(seed) +
              bytes.fromhex(nonce) + struct.pack("<IQ", logical, version))
    return b"".join(hashlib.sha256(prefix + struct.pack("<I", index)).digest()[:8] * 8
                    for index in range(PAGE_BYTES // 64))


def validate_plan(plan, scope):
    require(type(plan) is dict and set(plan) == {"schema", "seed", "nonce", "actions"} and
            plan["schema"] == SCHEMA and hex_value(plan["seed"], 32) and
            plan["seed"] != "0" * 64 and plan["nonce"] == scope["run_nonce"], "plan_shape")
    actions = plan["actions"]
    require(type(actions) is list and 0 < len(actions) <= MAX_OPERATIONS and
            scope["page_count"] <= MAX_PAGES, "plan_bounds")
    require(digest(canonical(plan)) == scope["workload_sha256"], "plan_commitment")
    for action in actions:
        require(type(action) is dict and set(action) == ACTION_FIELDS and
                type(action["kind"]) is str and action["kind"] in KINDS, "action_shape")
        require(integer(action["logical"], scope["first_logical"],
                        scope["first_logical"] + scope["page_count"] - 1) and
                integer(action["generation"], 1, (1 << 32) - 1) and
                integer(action["version"], 0, (1 << 64) - 1) and
                integer(action["status"], 0, 255), "action_bounds")
        kind = action["kind"]
        require((action["status"] > 0) == (kind == "claimed_error") and
                (action["version"] == 0) == (kind == "discard"), "action_status_version")
        if kind in TYPED:
            require(integer(action["codec"], 1, 2) and
                    integer(action["swap_type"], 0, 255) and
                    all(integer(action[key], 1, (1 << 64) - 1)
                        for key in KEY_FIELDS[1:]), "action_source_key")
        else:
            # V2 noncapture ACCEPT carries logical only. Do not fabricate
            # a slot/area/store/codec identity for ordinary/discard.
            require(all(integer(action[key], 0, 0) for key in (*KEY_FIELDS, "codec")),
                    "noncapture_key_unsupported")
    return actions


def exactly(events, name):
    items = events.get(name, [])
    require(len(items) == 1, "event_cardinality")
    return items[0]


def absent(events, *names):
    require(not any(events.get(name) for name in names), "unsupported_event_shape")


def compare_page(value, expected):
    require(hex_value(value, PAGE_BYTES), "full_page_required")
    observed = bytes.fromhex(value)
    # Full bytes, not hash equality. A fixed diagnostic leaks no mismatch
    # offset, content, identity, or reference material.
    require(observed == expected, "independent_byte_mismatch")


def source_matches(row, action):
    return all(row[key] == action[key] for key in
               ("logical", "generation", *KEY_FIELDS))


def validate(wire, scope, expected_source, plan, sidecar):
    require(type(wire) is bytes, "wire_type")
    # Preserve every original wire restriction, including failure status.
    prior = current.validate_current(wire, scope, expected_source)
    actions = validate_plan(plan, scope)
    require(type(sidecar) is dict and set(sidecar) ==
            {"schema", "scope_sha256", "wire_sha256", "operations"} and
            sidecar["schema"] == SCHEMA and
            sidecar["scope_sha256"] == legacy.scope_digest(scope).hex() and
            sidecar["wire_sha256"] == digest(wire), "sidecar_binding")
    witnesses = sidecar["operations"]
    require(type(witnesses) is list and len(witnesses) == len(actions), "sidecar_count")
    events_by_operation = {}
    accepts = []
    for index in range(prior["records"]):
        row = dict(zip(legacy.FIELDS, legacy.RECORD.unpack_from(
            wire, legacy.HEADER.size + index * legacy.RECORD.size)))
        name = legacy.EVENTS[row["event"] - 1]
        # Deliberately narrow first workload: all operations must correspond
        # to the independent plan, no natural GC or prebind capture drops yet.
        require(name not in ("gc_begin", "gc_end", "capture_drop"),
                "unsupported_gc_or_drop")
        if name == "cleanup":
            continue
        events_by_operation.setdefault(row["operation"], {}).setdefault(name, []).append(row)
        if name == "accept":
            accepts.append(row)
    require(len(accepts) == len(actions) == len(events_by_operation), "plan_coverage")
    maps = {}
    generations = {}
    last_version = {}
    slot_owner = {}
    slot_store = {}
    pending_error = False
    typed_unread = set()
    scope_area = None
    page_slot = {}
    compared_pages = 0
    read_pairs = 0
    previous_upper = 0
    for action, witness, accept in zip(actions, witnesses, accepts):
        kind = action["kind"]
        page = action["logical"]
        generation = action["generation"]
        status = action["status"]
        events = events_by_operation[accept["operation"]]
        upper = exactly(events, "upper_endio")
        clone = exactly(events, "clone_endio")
        # Single-flight bounded reference workload. No claims about concurrent
        # or split BIO workload lineage; reject overlapping accepted operations.
        require(accept["sequence"] > previous_upper, "unsupported_overlap")
        prior_upper = previous_upper
        previous_upper = upper["sequence"]
        require(accept["operation_kind"] == KINDS[kind] and accept["logical"] == page and
                upper["status"] == clone["status"] == status, "plan_ack_binding")
        require(type(witness) is dict and set(witness) == WITNESS_FIELDS and
                all(integer(witness[key], 1, (1 << 64) - 1) and
                    witness[key] == accept[key] for key in
                    ("operation", "original", "clone", "descriptor")) and
                integer(witness["accept_sequence"], 1, legacy.MAX_RECORDS) and
                witness["accept_sequence"] == accept["sequence"] and
                integer(witness["upper_sequence"], 1, legacy.MAX_RECORDS) and
                witness["upper_sequence"] == upper["sequence"] and
                integer(witness["user_status"], 0, 255) and
                witness["user_status"] == status, "witness_ack_binding")
        if kind != "typed_read":
            require(integer(witness["pin"], 0, 0) and
                    integer(witness["copy_sequence"], 0, 0) and
                    witness["final_copy"] is None and witness["user_page"] is None,
                    "unexpected_copy_witness")
        else:
            require(witness["input_page"] is None, "unexpected_input_witness")
        if kind in TYPED:
            area = (action["area_epoch"], action["swap_type"])
            if scope_area is None:
                scope_area = area
            require(area == scope_area and page_slot.setdefault(page, action["slot"]) ==
                    action["slot"], "scope_area_or_slot")
        if kind in WRITES:
            require(page not in typed_unread, "missing_read_before_overwrite")
            require(generation == generations.get(page, 0) + 1 and
                    action["version"] > last_version.get(page, 0), "write_generation_version")
            last_version[page] = action["version"]
            reference = reference_page(plan["seed"], plan["nonce"], page, action["version"])
            reference_digest = hashlib.sha256(reference).digest()
            compare_page(witness["input_page"], reference)
            compared_pages += 1
            if kind in TYPED:
                capture = exactly(events, "capture")
                require(source_matches(capture, action) and source_matches(accept, action) and
                        capture["codec"] == action["codec"] and
                        capture["page_sha256"] == reference_digest, "capture_reference")
                require(capture["sequence"] > prior_upper, "unsupported_capture_overlap")
                # Exact key cannot be reused or alias a different logical page.
                slot = tuple(action[key] for key in ("area_epoch", "swap_type", "slot"))
                require(slot_owner.setdefault(slot, page) == page and
                        action["store"] > slot_store.get(slot, 0), "stale_or_aliased_store")
                slot_store[slot] = action["store"]
                require(accept["flags"] == 1 and
                        len(events.get("bind", [])) == len(events.get("candidate_release", [])) ==
                        len(events.get("carrier_release", [])) == 1, "typed_lifetime")
                require(events["carrier_release"][0]["sequence"] > upper["sequence"],
                        "carrier_before_original_ack")
                prep = events.get("preparation", [])
                expected_flags = [1, 2] if kind == "fallback" else [1, 2, 4]
                require([row["flags"] for row in prep] == expected_flags and
                        prep[0]["sequence"] < accept["sequence"] < prep[1]["sequence"],
                        "preparation_witness")
                if kind == "fallback":
                    exactly(events, "refuse")
                    exactly(events, "fallback")
                    require(bool(events.get("reserve")) == bool(events.get("cancel")),
                            "fallback_cancel_witness")
                    absent(events, "claim", "quarantine")
                else:
                    exactly(events, "reserve")
                    claim = exactly(events, "claim")
                    require(prep[-1]["sequence"] > claim["sequence"], "preparation_discard_order")
                    absent(events, "refuse", "cancel", "fallback")
            else:
                absent(events, "capture", "claim", "fallback", "quarantine")
            submit = exactly(events, "lower_submit")
            completion = exactly(events, "lower_complete")
            require(submit["flags"] == 2 and submit["requested"] == PAGE_BYTES,
                    "unsupported_write_extent")
            if kind == "claimed_error":
                pending_error = True
                absent(events, "publish")
                quarantine = exactly(events, "quarantine")
                require(quarantine["extent"] == submit["extent"] and
                        (completion["status"] > 0 or completion["completed"] != PAGE_BYTES or
                         any(row["status"] > 0 for row in events.get("flush", []))),
                        "claimed_error_witness")
                # First trial stops on any error; no later operation may mask it.
                require(accept is accepts[-1], "operation_after_claimed_error")
                continue
            publish = exactly(events, "publish")
            exactly(events, "flush")
            require(publish["new_generation"] == generation and
                    publish["page_sha256"] == reference_digest, "publish_reference")
            if kind in ("ordinary_write", "fallback"):
                # Narrow ordinary qualification: full original RAW only.
                require(publish["tag"] == 0 and submit["compressed_length"] == PAGE_BYTES and
                        submit["compressed_sha256"] == reference_digest and
                        completion["observed_sha256"] == reference_digest, "ordinary_raw_reference")
            generations[page] = generation
            maps[page] = action.copy()
            if kind == "typed_write":
                typed_unread.add(page)
        elif kind == "typed_read":
            previous = maps.get(page)
            require(previous is not None and previous["kind"] == "typed_write" and
                    all(previous[key] == action[key] for key in
                        ("generation", "version", "codec", *KEY_FIELDS)), "stale_read_reference")
            pin = exactly(events, "pin")
            oracle = exactly(events, "oracle")
            release = exactly(events, "pin_release")
            require(source_matches(pin, action) and
                    integer(witness["pin"], 1, (1 << 64) - 1) and
                    witness["pin"] == pin["pin"] == oracle["pin"] == release["pin"] and
                    integer(witness["copy_sequence"], 1, legacy.MAX_RECORDS) and
                    witness["copy_sequence"] == oracle["sequence"] and
                    pin["sequence"] < oracle["sequence"] < release["sequence"] <
                    clone["sequence"] < upper["sequence"], "final_copy_pin_binding")
            reference = reference_page(plan["seed"], plan["nonce"], page, action["version"])
            compare_page(witness["final_copy"], reference)
            compare_page(witness["user_page"], reference)
            reference_digest = hashlib.sha256(reference).digest()
            require(oracle["page_sha256"] == oracle["observed_sha256"] == reference_digest,
                    "oracle_reference")
            compared_pages += 2
            read_pairs += 1
            typed_unread.discard(page)
        else:
            require(page not in typed_unread and witness["input_page"] is None and page in maps and
                    generation == generations.get(page, 0) + 1 and
                    exactly(events, "discard")["new_generation"] == generation,
                    "discard_reference")
            del maps[page]
            generations[page] = generation
    require(not typed_unread and (read_pairs > 0 or pending_error),
            "missing_independent_read")
    require(prior["status"] == ("OBSERVED_FAILURE_BLOCKED" if pending_error else
            "CONSISTENT_RECORDER_OBSERVATIONS_ONLY"), "recorder_result")
    return dict(status=("OBSERVED_CLAIMED_ERROR_BLOCKED" if pending_error else
                        "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY"),
                operations=len(actions), full_pages_compared=compared_pages,
                bytes_compared=compared_pages * PAGE_BYTES, read_pairs=read_pairs,
                first_failure=prior["first_failure"], auth=0, **legacy.GATES)


def read_regular(path, limit):
    # Offline private regular files only. No symlink/device/FIFO access.
    require(stat.S_ISREG(os.lstat(path).st_mode), "regular_file_required")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "file_bounds")
        data = stream.read(limit + 1)
        require(len(data) <= limit, "file_bounds")
        return data


def read_json(path, limit):
    return json.loads(read_regular(path, limit), object_pairs_hook=legacy.unique_object)


def main():
    try:
        require(len(sys.argv) == 6, "arguments")
        expected_source, scope_path, plan_path, wire_path, sidecar_path = sys.argv[1:]
        result = validate(read_regular(wire_path, legacy.MAX_BYTES),
                          read_json(scope_path, 4096), expected_source,
                          read_json(plan_path, MAX_PLAN_BYTES),
                          read_json(sidecar_path, MAX_SIDECAR_BYTES))
    except legacy.Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), auth=0, **legacy.GATES)
    except (ValueError, TypeError, KeyError, OverflowError, OSError, RecursionError, struct.error):
        result = dict(status="BLOCKED", reason="invalid_input", auth=0, **legacy.GATES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
