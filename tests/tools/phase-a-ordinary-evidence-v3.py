#!/usr/bin/env python3
"""Interleaved ordinary-only diagnostic, v3 envelopes, unchanged v2 plan.

Reuse the sibling v2 contract's scope, canonical commitment, late witness,
field, private input and JSON checks; never dispatch to its serial validator.
Both envelopes require version 3; the embedded plan stays version 2 with
its original digest and 1..16 pages/2..64 planned operations. Late STORED
witnesses are hypothetical, not an independently verified logical-slot bind.

The v2 17-stage per-page chain remains exact except write_commit adds
persistence: 'UNPROVEN'. Here write_commit means same-boot authoritative map
publication after successful lower completion, not media persistence.
Evict_retired means joined actual erase/free and successful original ACK,
not the time of erase. Read_mm must reference that page's earlier publication
ordinal. No sorting: global contiguous seq, independent per-page cursors,
unique operation/BIO/DM/lower/receipt tokens across every chain. One write
and one read per page, <=32 actual operations, <=274 events. No split/merge,
retry, replacement, loss or same-page reordering. All three 4096-byte page
claims must equal the independent plan, even for identical-content pages.
Cleanup and dtr retain the v2 fields, follow ALL complete chains, require
zero debts and distinct receipts. Neither their provenance nor native slot
binding is authenticated; complete envelope replay is not prevented.

CLI reads only bounded private JSON files; never emits raw page bytes,
identities, paths or arbitrary errors. Structural consistency cannot prove
native capture, persistence, durable qualification or consent. AUTH=0,
Phase A BLOCKED, observation UNKNOWN; no I/O induced for evidence.
"""
import importlib.util
import json
from pathlib import Path
import sys

# A fixed sibling dependency, not a path supplied by the evidence.
_spec = importlib.util.spec_from_file_location(
    "ordinary_v2", Path(__file__).with_name("phase-a-ordinary-evidence.py"))
_v2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v2)
Invalid = _v2.Invalid
require, integer, shape = _v2.require, _v2.integer, _v2.shape
exact_fields, fresh = _v2.exact_fields, _v2.fresh
STAGES = tuple((stage, fields | ({"persistence"} if stage == "write_commit" else set()))
               for stage, fields in _v2.STAGES)
MAX_ACTUAL_OPERATIONS = 32
MAX_EVENTS = _v2.MAX_PAGES * len(STAGES) + 2
DEBTS = frozenset({"maps", "bios", "pins", "reservations", "stores", "caps", "tickets", "quarantines"})
GATES = dict(_v2.GATES, persistence="UNPROVEN", durable_qualification="BLOCKED",
             logical_slot_binding="UNVERIFIED", actual_route="ORDINARY")
STATUS = "CONSISTENT_INTERLEAVED_ORDINARY_CORRELATION_ONLY"


def envelope(value, schema, keys):
    require(type(value) is dict, "envelope_shape")
    require(value.get("schema") == schema and integer(value.get("version"), 3, 3), "schema_version")
    shape(value, keys | {"schema", "version", "scope"}, "envelope_shape")
    _v2.scope_valid(value["scope"])


class PageState:
    """One invocation owns the state; no global mutable ledger or concurrency."""
    __slots__ = ("identity", "reference", "cursor", "tokens", "lower_bytes", "commit_sequence")

    def __init__(self, identity, reference):
        self.identity = identity
        self.reference = reference
        self.cursor = 0
        self.tokens = {}
        self.lower_bytes = None
        self.commit_sequence = None

    def accept(self, row, seen_tokens):
        require(self.cursor < len(STAGES), "page_already_complete")
        stage, extra = STAGES[self.cursor]
        require(row["stage"] == stage, "event_order")
        shape(row, extra | _v2.IDENTITY_KEYS | _v2.AREA_KEYS | {"seq", "stage"}, "event_shape")
        _v2.identity_valid(row)
        exact_fields(row, self.identity, _v2.IDENTITY_KEYS, "stale_page_identity")
        if "status" in extra:
            require(integer(row["status"], 0, 0), "failed_stage")
        if stage == "natural_evict":
            require(row["cause"] == "native_reclaim", "not_natural_eviction")
        if stage == "write_commit":
            require(row["persistence"] == "UNPROVEN", "persistence_unproven_required")
            self.commit_sequence = row["seq"]
        if stage == "read_mm":
            require(self.commit_sequence is not None and self.commit_sequence < row["seq"] and
                    integer(row["commit_seq"], self.commit_sequence, self.commit_sequence) and
                    row["route"] == "ordinary_backing", "read_commit_binding")
        starts_operation = stage.endswith("_mm")
        if starts_operation:
            self.tokens.clear()
            self.lower_bytes = None
        for key in ("operation", "bio", "dm", "lower"):
            if key not in extra:
                continue
            if key not in self.tokens:
                fresh(row[key], seen_tokens)
                self.tokens[key] = row[key]
            else:
                exact_fields(row, self.tokens, {key}, "operation_binding")
        if "logical_bytes" in extra:
            require(integer(row["logical_bytes"], _v2.PAGE_BYTES, _v2.PAGE_BYTES), "logical_completion")
        if "bytes" in extra:
            require(integer(row["bytes"], 512, 16384) and row["bytes"] % 512 == 0, "lower_length")
            if stage.endswith("_submit"):
                self.lower_bytes = row["bytes"]
            else:
                require(row["bytes"] == self.lower_bytes, "lower_completion")
        if "page" in extra:
            require(_v2.hex_string(row["page"], _v2.PAGE_BYTES), "full_page_required")
            require(bytes.fromhex(row["page"]) == self.reference, "independent_byte_mismatch")
        self.cursor += 1
        return starts_operation


def validate(manifest, capture):
    """Consume exactly the supplied order, with bounded independent cursors."""
    envelope(manifest, "swapz-ordinary-manifest", {"plan", "witnesses"})
    expected = _v2.committed_pages(manifest)
    identities = _v2.stored_witnesses(manifest, expected)
    envelope(capture, "swapz-ordinary-capture", {"loss", "events"})
    scope = manifest["scope"]
    exact_fields(capture["scope"], scope, _v2.SCOPE_KEYS, "stale_scope")
    require(integer(capture["loss"], 0, 0), "capture_loss")
    events = capture["events"]
    require(type(events) is list and 2 < len(events) <= MAX_EVENTS, "event_bounds")
    states = {logical: PageState(identities[logical], reference) for logical, reference in expected.items()}
    seen_tokens = set()
    completed = operations = 0
    cleanup_sequence = None
    dtr_seen = False
    for ordinal, row in enumerate(events, 1):
        require(type(row) is dict and {"seq", "stage"} | _v2.AREA_KEYS <= row.keys(), "event_shape")
        require(integer(row["seq"], ordinal, ordinal), "event_sequence")
        exact_fields(row, scope, _v2.AREA_KEYS, "event_scope")
        stage = row["stage"]
        require(not dtr_seen, "trailing_event")
        if stage == "cleanup":
            require(completed == len(states) and cleanup_sequence is None, "early_or_duplicate_cleanup")
            shape(row, DEBTS | {"receipt", "status", "issuer", "seq", "stage"} | _v2.AREA_KEYS, "event_shape")
            require(row["issuer"] == "controller_census" and
                    all(integer(row[key], 0, 0) for key in DEBTS | {"status"}), "cleanup_debt")
            fresh(row["receipt"], seen_tokens)
            cleanup_sequence = ordinal
        elif stage == "dtr":
            require(cleanup_sequence is not None, "early_dtr")
            shape(row, {"receipt", "cleanup_seq", "status", "issuer", "seq", "stage"} | _v2.AREA_KEYS, "event_shape")
            fresh(row["receipt"], seen_tokens)
            require(row["issuer"] == "dm_target_dtr" and integer(row["status"], 0, 0) and
                    integer(row["cleanup_seq"], cleanup_sequence, cleanup_sequence), "dtr_binding")
            dtr_seen = True
        else:
            require(cleanup_sequence is None, "page_after_cleanup")
            require(integer(row.get("logical"), 1, _v2.U32) and row["logical"] in states, "page_coverage")
            state = states[row["logical"]]
            operations += state.accept(row, seen_tokens)
            require(operations <= min(MAX_ACTUAL_OPERATIONS, manifest["plan"]["max_operations"]),
                    "operation_bounds")
            completed += state.cursor == len(STAGES)
    require(completed == len(states) and operations == 2 * len(states), "incomplete_pages")
    require(dtr_seen, "missing_terminal")
    return dict(status=STATUS, pages=completed, operations=operations,
                bytes_compared=3 * _v2.PAGE_BYTES * completed, **GATES)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        require(len(argv) == 2, "arguments")
        result = validate(_v2.read_regular(argv[0], _v2.MAX_MANIFEST_BYTES),
                          _v2.read_regular(argv[1], _v2.MAX_CAPTURE_BYTES))
    except Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), **GATES)
    except (ValueError, TypeError, KeyError, OverflowError, OSError, RecursionError):
        result = dict(status="BLOCKED", reason="invalid_input", **GATES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == STATUS else 2


if __name__ == "__main__":
    raise SystemExit(main())
