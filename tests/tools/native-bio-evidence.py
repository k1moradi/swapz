#!/usr/bin/env python3
"""Bounded offline native observation validator. No capture or admission API."""
import hashlib
import json
import re
import sys
from collections import Counter, deque

SCHEMA = "swapz-native-bio-observation-v1"
MAPPING_SOURCE = "efd77858cd20650213559ceb9cb4d0362db32ea5"
LINUX_SOURCE = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MAX_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 8192
MAX_OPERATIONS = 1024
MAX_U64 = (1 << 64) - 1
MAX_U32 = (1 << 32) - 1
PAGE = 4096
SCOPE_HASHES = {"source": 40, "kernel_sha256": 64, "module_sha256": 64,
                "workload_sha256": 64, "run_nonce": 32, "target": 32}
SCOPE_NUMBERS = ("session", "epoch", "target_epoch", "registration_epoch",
                 "first_logical", "page_count")
KEY_IDS = ("descriptor", "bio", "original")
KEY_NUMBERS = ("logical", "swap_type", "slot", "area_epoch", "store", "generation")
KEY_FIELDS = KEY_IDS + KEY_NUMBERS
PAYLOAD_FIELDS = ("tag", "codec", "version", "dictionary", "length", "decoded_length", "sha256", "page_sha256")
GATES = {"source_mapped_authenticated": False, "actual_physical_io": False,
         "live_admission": False, "phase_a": "BLOCKED",
         "direct_compressed_handoff": False, "forced_raw_bypass": False,
         "import_active": False}


class InvalidEvidence(ValueError):
    """Only constant, non-sensitive categories cross the output boundary."""


def require(condition, reason):
    if not condition:
        raise InvalidEvidence(reason)


def fields(record, expected):
    require(type(record) is dict and set(record) == set(expected), "fields")


def number(value, minimum=0, maximum=MAX_U64):
    require(type(value) is int and minimum <= value <= maximum, "integer")
    return value


def hex_value(value, length):
    require(type(value) is str and len(value) == length and
            re.fullmatch(r"[0-9a-f]+", value) is not None and
            value != "0" * length, "opaque_id_or_digest")
    return value


def scope_digest(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True,
        separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def check_scope(scope, expected_digest):
    fields(scope, tuple(SCOPE_HASHES) + SCOPE_NUMBERS +
           ("linux_source", "mapping_source", "profile"))
    for key, length in SCOPE_HASHES.items():
        hex_value(scope[key], length)
    require(scope["linux_source"] == LINUX_SOURCE and
            scope["mapping_source"] == MAPPING_SOURCE and
            scope["profile"] == "M3568", "unmapped_profile")
    for key in SCOPE_NUMBERS[:4]:
        number(scope[key], 1)
    first = number(scope["first_logical"], 1, MAX_U32)
    count = number(scope["page_count"], 1, 4096)
    require(first + count - 1 <= MAX_U32, "logical_range")
    require(scope_digest(scope) == hex_value(expected_digest, 64), "scope_mismatch")


def check_key(key, scope):
    fields(key, KEY_FIELDS)
    for field in KEY_IDS:
        hex_value(key[field], 32)
    require(len({key[field] for field in KEY_IDS}) == len(KEY_IDS),
            "bio_identity_alias")
    number(key["logical"], scope["first_logical"],
           scope["first_logical"] + scope["page_count"] - 1)
    number(key["swap_type"], 0, 255)
    number(key["slot"], 1)
    number(key["area_epoch"], 1)
    number(key["store"], 1)
    number(key["generation"], 1, MAX_U32)


def typed_payload(data):
    fields(data, PAYLOAD_FIELDS)
    require(number(data["tag"]) == 0x5a and number(data["version"]) == 1 and
            number(data["codec"]) in (1, 2), "typed_codec")
    require(number(data["dictionary"]) == 0 and number(data["decoded_length"]) == PAGE,
            "typed_format")
    number(data["length"], 1, 3568)
    for field in ("sha256", "page_sha256"):
        hex_value(data[field], 64)
    return dict(data)


def raw_payload(digest):
    return {"tag": 0, "codec": 0, "version": 0, "dictionary": 0,
            "length": PAGE, "decoded_length": PAGE,
            "sha256": hex_value(digest, 64), "page_sha256": digest}


def same_source(left, right):
    return all(left[field] == right[field]
               for field in ("logical", "swap_type", "slot", "area_epoch", "store", "generation"))


class Validator:
    def __init__(self, scope):
        self.scope = scope
        self.operations = {}
        self.identities = set()
        self.lower_ids = set()
        self.extents = set()
        self.pin_ids = set()
        self.current = {}
        self.generations = {}
        self.active_pages = set()
        self.fifo = deque()
        self.credit = 0
        self.reservation = None
        self.counts = Counter()
        self.failed = False
        self.first_failure = None
        self.event_id = 0
        self.cleaned = False

    def mark_failed(self, reason):
        self.failed = True
        if self.first_failure is None:
            self.first_failure = {"event_id": self.event_id, "reason": reason}

    def new_operation(self, op, key, kind, state, payload=None):
        require(not self.failed and op not in self.operations and
                len(self.operations) < MAX_OPERATIONS, "operation_limit_or_reuse")
        if kind != "gc":
            ids = {key[field] for field in KEY_IDS}
            require(self.identities.isdisjoint(ids), "bio_identity_reuse")
            self.identities.update(ids)
        entry = {"key": dict(key), "kind": kind, "state": state,
                 "payload": payload, "extent": None, "lower": None}
        self.operations[op] = entry
        return entry

    def activate(self, op, entry):
        page = entry["key"]["logical"]
        require(page not in self.active_pages, "overlapping_logical_owner")
        self.active_pages.add(page)
        self.fifo.append(op)

    def head(self, op):
        require(self.fifo and self.fifo[0] == op, "ordered_head")

    def finish(self, op, entry):
        self.head(op)
        self.fifo.popleft()
        self.active_pages.remove(entry["key"]["logical"])
        entry["state"] = "done"

    def begin(self, event, op, key, data):
        require(not self.failed, "operation_after_failure")
        page = key["logical"]
        current = self.current.get(page)
        previous = self.generations.get(page, 0)
        if event == "evict":
            # Producer must bind the preerase copy to the actual original BIO
            # and accepted clone; the parser cannot authenticate that binding.
            require(key["generation"] == previous + 1, "generation")
            self.new_operation(op, key, "typed_write", "evicted", typed_payload(data))
            self.counts["evictions"] += 1
            return
        if event == "gc_begin":
            fields(data, ("old_extent", "gc_epoch"))
            require(current is not None and current["payload"]["tag"] == 0x5a
                    and key == current["key"] and key["generation"] < MAX_U32
                    and current["gc_epoch"] < MAX_U64 and data["old_extent"] == current["extent"]
                    and number(data["gc_epoch"], 1) == current["gc_epoch"],
                    "gc_authority")
            entry = self.new_operation(op, key, "gc", "ready", current["payload"])
            entry["old_extent"] = current["extent"]
            entry["gc_epoch"] = current["gc_epoch"]
            self.activate(op, entry)
            return
        fields(data, ("operation", "raw_sha256"))
        kind = data["operation"]
        require(kind in ("typed_write", "typed_read", "overwrite", "discard"),
                "operation_kind")
        if kind == "typed_write":
            entry = self.operations.get(op)
            require(entry is not None and entry["state"] == "evicted" and
                    entry["key"] == key and data["raw_sha256"] is None and
                    key["generation"] == previous + 1, "eviction_binding")
        elif kind == "typed_read":
            require(current is not None and current["payload"]["tag"] == 0x5a
                    and same_source(key, current["key"]) and
                    data["raw_sha256"] is None, "read_authority")
            entry = self.new_operation(op, key, kind, "ready", current["payload"])
            entry["extent"] = current["extent"]
        else:
            require(key["generation"] == previous + 1, "generation")
            if kind == "discard":
                require(current is not None and data["raw_sha256"] is None and
                        all(key[f] == current["key"][f]
                            for f in ("swap_type", "slot", "area_epoch", "store")), "discard_authority")
                payload = None
            else:
                payload = raw_payload(data["raw_sha256"])
            entry = self.new_operation(op, key, kind, "ready", payload)
        self.activate(op, entry)
        entry["state"] = "accepted" if kind == "typed_write" else "ready"
        self.counts["accepted_bios"] += 1

    def step(self, event, op, key, data):
        if event in ("evict", "accept", "gc_begin"):
            self.begin(event, op, key, data)
            return
        entry = self.operations.get(op)
        require(entry is not None and entry["key"] == key and
                entry["state"] not in ("done", "evicted"), "operation_binding")
        self.head(op)
        state, kind = entry["state"], entry["kind"]
        page = key["logical"]
        if event == "pin":
            fields(data, ("pin", "extent", "gc_epoch"))
            pin = hex_value(data["pin"], 32)
            current = self.current.get(page)
            require(kind in ("typed_read", "gc") and state == "ready" and
                    current is not None and pin not in self.pin_ids and
                    data["extent"] == current["extent"] and
                    number(data["gc_epoch"]) == current["gc_epoch"], "pin_authority")
            self.pin_ids.add(pin)
            entry.update(state="pinned", pin=pin)
            self.counts["pins"] += 1
        elif event == "reserve":
            fields(data, ("credit", "extent"))
            credit = number(data["credit"], 1, MAX_U32)
            extent = hex_value(data["extent"], 32)
            require(state == "accepted" and self.reservation is None and
                    credit > self.credit and extent not in self.extents, "reservation")
            self.credit, self.reservation = credit, op
            self.extents.add(extent)
            entry.update(state="reserved", extent=extent)
        elif event in ("claim", "cancel"):
            fields(data, ("credit",) if event == "claim" else ("credit", "tail_verified"))
            require(self.reservation == op and number(data["credit"], 1) == self.credit,
                    "reservation_binding")
            if event == "claim":
                require(state == "reserved", "claim_order")
                entry["state"] = "claimed"
                self.counts["claims"] += 1
            else:
                require(state == "refused_reserved" and data["tail_verified"] is True,
                        "cancel_order")
                self.reservation = None
                entry["state"] = "refused"
                entry["extent"] = None
                self.counts["cancels"] += 1
        elif event == "refuse":
            fields(data, ())
            require(state in ("accepted", "reserved"), "refusal_after_claim")
            entry["state"] = "refused_reserved" if state == "reserved" else "refused"
            self.counts["refusals"] += 1
        elif event == "fallback":
            fields(data, ())
            require(state == "refused" and self.reservation != op, "fallback_after_claim")
            entry.update(state="ready", payload=raw_payload(entry["payload"]["page_sha256"]),
                         fallback=True)
            self.counts["ordinary_fallbacks"] += 1
        elif event == "gc_read_submit":
            fields(data, ("lower", "extent", "requested_bytes"))
            lower = hex_value(data["lower"], 32)
            require(kind == "gc" and state == "pinned" and
                    lower not in self.lower_ids and data["extent"] == entry["old_extent"]
                    and number(data["requested_bytes"]) == PAGE, "gc_read_submit")
            self.lower_ids.add(lower)
            entry.update(state="gc_read_issued", lower=lower)
            self.counts["lower_reads"] += 1
        elif event == "gc_read_complete":
            fields(data, ("lower", "completed_bytes", "status", "payload_sha256"))
            completed = number(data["completed_bytes"], 0, PAGE)
            status = number(data["status"], 0, 255)
            require(kind == "gc" and state == "gc_read_issued" and
                    data["lower"] == entry["lower"], "gc_read_completion")
            if status or completed != PAGE:
                require(data["payload_sha256"] is None, "failed_payload")
                entry["state"] = "gc_read_error"
                self.mark_failed("lower_status" if status else "short_lower_completion")
            elif hex_value(data["payload_sha256"], 64) != entry["payload"]["sha256"]:
                entry["state"] = "gc_read_error"
                self.mark_failed("compressed_digest_mismatch")
            else:
                entry["state"] = "gc_read_verified"
        elif event == "lower_submit":
            fields(data, ("lower", "extent", "requested_bytes", "payload_length", "payload_sha256"))
            lower = hex_value(data["lower"], 32)
            extent = hex_value(data["extent"], 32)
            payload = entry["payload"]
            require(not self.failed and
                    ((state == "pinned" and kind == "typed_read") or
                     (state == "gc_read_verified" and kind == "gc") or
                     (state in ("claimed", "ready") and kind not in ("typed_read", "gc", "discard"))) and
                    (kind != "typed_write" or state == "claimed" or entry.get("fallback"))
                    and lower not in self.lower_ids and payload is not None and
                    number(data["requested_bytes"]) == PAGE and
                    number(data["payload_length"]) == payload["length"] and
                    data["payload_sha256"] == payload["sha256"], "lower_submit")
            if entry["extent"] is None:
                require(extent not in self.extents, "extent_reuse")
                self.extents.add(extent)
                entry["extent"] = extent
            require(extent == entry["extent"], "extent_binding")
            self.lower_ids.add(lower)
            entry.update(state="issued", lower=lower)
            self.counts["lower_reads" if kind == "typed_read" else "lower_writes"] += 1
        elif event == "lower_complete":
            fields(data, ("lower", "completed_bytes", "status", "payload_sha256"))
            completed = number(data["completed_bytes"], 0, PAGE)
            status = number(data["status"], 0, 255)
            require(state == "issued" and data["lower"] == entry["lower"], "lower_completion")
            if status or completed != PAGE:
                require(data["payload_sha256"] is None, "failed_payload")
                entry["state"] = "read_error" if kind == "typed_read" else "issued_error"
                self.mark_failed("lower_status" if status else "short_lower_completion")
            elif data["payload_sha256"] != entry["payload"]["sha256"]:
                require(kind == "typed_read", "lower_payload_mismatch")
                hex_value(data["payload_sha256"], 64)
                entry["state"] = "read_error"
                self.mark_failed("compressed_digest_mismatch")
            else:
                entry["state"] = "read_complete" if kind == "typed_read" else "written"
        elif event == "flush":
            fields(data, ("status",))
            require(state == "written", "flush_order")
            if number(data["status"], 0, 255):
                entry["state"] = "issued_error"
                self.mark_failed("flush_status")
            else:
                entry["state"] = "durable"
                self.counts["durable_flushes"] += 1
        elif event == "publish":
            fields(data, ("extent", "payload", "gc_epoch", "generation"))
            require(state == "durable" and not self.failed, "durable_publication")
            payload = entry["payload"]
            fields(data["payload"], PAYLOAD_FIELDS)
            if payload["tag"] == 0x5a:
                observed = typed_payload(data["payload"])
            else:
                observed = raw_payload(data["payload"]["sha256"])
                for field in ("tag", "codec", "version", "dictionary", "length", "decoded_length"):
                    number(data["payload"][field])
                require(observed == data["payload"], "raw_representation")
            expected_epoch = (entry["gc_epoch"] + 1 if kind == "gc" else
                              1 if payload["tag"] == 0x5a else 0)
            require(state == "durable" and data["extent"] == entry["extent"] and
                    observed == payload and number(data["gc_epoch"]) == expected_epoch,
                    "durable_publication")
            published_generation = number(data["generation"], 1, MAX_U32)
            require(published_generation == self.generations.get(page, 0) + 1 and
                    published_generation == key["generation"] + (kind == "gc"),
                    "generation")
            if kind == "gc":
                require(self.current[page]["extent"] == entry["old_extent"], "gc_authority")
            self.generations[page] = published_generation
            self.current[page] = {"key": dict(key, generation=published_generation), "extent": entry["extent"],
                                  "payload": payload, "gc_epoch": expected_epoch}
            if self.reservation == op:
                self.reservation = None
            entry["state"] = "published"
            self.counts["gc_publications" if kind == "gc" else "write_publications"] += 1
            if kind != "gc" and payload["tag"] == 0x5a:
                self.counts["typed_publications"] += 1
            if kind == "overwrite":
                self.counts["overwrites"] += 1
        elif event == "oracle":
            fields(data, ("decoded_bytes", "compared_bytes", "decoded_sha256",
                          "expected_sha256", "byte_equal", "decoder_status"))
            require(state == "read_complete" and kind == "typed_read", "oracle_order")
            decoded = number(data["decoded_bytes"], 0, PAGE)
            compared = number(data["compared_bytes"], 0, PAGE)
            status = number(data["decoder_status"], 0, 255)
            require(type(data["byte_equal"]) is bool and
                    data["expected_sha256"] == entry["payload"]["page_sha256"], "oracle_binding")
            digest = hex_value(data["decoded_sha256"], 64) if decoded else None
            require(decoded or data["decoded_sha256"] is None, "oracle_digest")
            if (not status and decoded == compared == PAGE and data["byte_equal"]
                    and digest == data["expected_sha256"]):
                entry["state"] = "verified"
                self.counts["verified_typed_reads"] += 1
            else:
                entry["state"] = "read_error"
                self.mark_failed("full_page_oracle")
        elif event == "pin_release":
            fields(data, ("pin", "status"))
            require(kind in ("typed_read", "gc") and
                    data["pin"] == entry.get("pin") and
                    number(data["status"], 0, 255) == 0 and
                    ((kind == "typed_read" and state in ("verified", "read_error")) or
                     (kind == "gc" and state in ("published", "quarantined", "gc_read_error"))),
                    "pin_release_order")
            entry["state"] = state + "_released"
            self.counts["pin_releases"] += 1
        elif event == "discard":
            fields(data, ())
            require(not self.failed and kind == "discard" and state == "ready" and page in self.current
                    and key["generation"] == self.generations[page] + 1, "discard_order")
            del self.current[page]
            self.generations[page] = key["generation"]
            entry["state"] = "discarded"
            self.counts["discards"] += 1
        elif event == "quarantine":
            fields(data, ("extent",))
            require(state == "issued_error" and data["extent"] == entry["extent"],
                    "quarantine_order")
            if self.reservation == op:
                self.reservation = None
            entry["state"] = "quarantined"
            self.counts["quarantines"] += 1
        elif event == "ack":
            fields(data, ("status",))
            status = number(data["status"], 0, 255)
            require(kind != "gc" and
                    ((not self.failed and state in ("published", "verified_released", "discarded") and status == 0) or
                     (state in ("read_error_released", "quarantined") and status != 0)), "upper_ack")
            entry["state"] = "acked"
            self.counts["upper_acks"] += 1
            self.counts["error_acks"] += bool(status)
        elif event == "release":
            fields(data, ())
            require(state == "acked" or
                    (kind == "gc" and state in ("published_released", "quarantined_released",
                                                "gc_read_error_released")), "release_order")
            self.finish(op, entry)
            self.counts["operation_releases"] += 1
        else:
            raise InvalidEvidence("unknown_event")

    def cleanup(self, data):
        fields(data, ("route_revoked", "rcu_drained", "worker_drained", "caps",
                      "tickets", "decoder_pins", "reservations", "pending_bios",
                      "live_maps", "quarantined_extents"))
        require(not self.fifo and not self.active_pages and self.reservation is None
                and all(entry["state"] == "done" for entry in self.operations.values())
                and self.counts["accepted_bios"] == self.counts["upper_acks"]
                and self.counts["pins"] == self.counts["pin_releases"],
                "incomplete_operations")
        for field in ("route_revoked", "rcu_drained", "worker_drained"):
            require(data[field] is True, "cleanup_fence")
        for field in ("caps", "tickets", "decoder_pins", "reservations",
                      "pending_bios", "live_maps"):
            require(number(data[field]) == 0, "cleanup_debt")
        require(number(data["quarantined_extents"]) == self.counts["quarantines"],
                "quarantine_debt")
        # Map destruction is a producer assertion, not physical cleanup proof.
        self.cleaned = True


def validate(capture, expected_digest):
    fields(capture, ("schema", "scope", "initial", "events", "footer"))
    require(capture["schema"] == SCHEMA, "schema")
    scope = capture["scope"]
    check_scope(scope, expected_digest)
    fields(capture["initial"], ("empty", "generation"))
    require(capture["initial"]["empty"] is True and
            number(capture["initial"]["generation"]) == 0, "initial_baseline")
    events = capture["events"]
    require(type(events) is list and 1 <= len(events) <= MAX_EVENTS, "event_limit")
    footer = capture["footer"]
    fields(footer, ("records", "last_id", "lost", "overflow", "truncated"))
    require(number(footer["records"]) == len(events) == number(footer["last_id"])
            and number(footer["lost"]) == 0 and footer["overflow"] is False
            and footer["truncated"] is False, "loss_or_truncation")
    validator = Validator(scope)
    for index, record in enumerate(events, 1):
        fields(record, ("id", "scope_sha256", "event", "op", "key", "data"))
        require(number(record["id"], 1) == index and
                record["scope_sha256"] == expected_digest, "sequence_or_scope")
        event = record["event"]
        require(type(event) is str and not validator.cleaned, "event_after_cleanup")
        if event == "cleanup":
            require(number(record["op"]) == 0 and record["key"] is None and
                    index == len(events), "cleanup_order")
            validator.cleanup(record["data"])
        else:
            op = number(record["op"], 1)
            check_key(record["key"], scope)
            validator.event_id = index
            try:
                validator.step(event, op, record["key"], record["data"])
            except InvalidEvidence as error:
                error.event_id = index
                raise
    require(validator.cleaned and validator.counts["accepted_bios"] > 0,
            "missing_cleanup_or_bios")
    return {"status": ("OBSERVED_FAILURE_BLOCKED" if validator.failed else
                       "CONSISTENT_OBSERVATIONS_ONLY"),
            "counts": dict(validator.counts), "records": len(events),
            "first_failure": validator.first_failure,
            "mapping_source": MAPPING_SOURCE, **GATES}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def invalid_constant(_value):
    raise InvalidEvidence("invalid_json_constant")


def main():
    try:
        require(len(sys.argv) == 2, "expected_scope_digest_required")
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        require(0 < len(raw) <= MAX_BYTES, "input_size")
        capture = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                             parse_constant=invalid_constant)
        result = validate(capture, sys.argv[1])
    except InvalidEvidence as error:
        result = {"status": "BLOCKED", "reason": str(error),
                  "event_id": getattr(error, "event_id", None), **GATES}
    except (ValueError, TypeError, KeyError, IndexError, RecursionError, OSError):
        result = {"status": "BLOCKED", "reason": "invalid_input", **GATES}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_OBSERVATIONS_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
