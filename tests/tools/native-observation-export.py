#!/usr/bin/env python3
"""Offline fixed-record recorder transport and partial-order validator.

No device/capture API. The source manifest and event contents are assertions,
not authentication. The old serial v1 collector is not used or replayed.
"""
import hashlib
import json
import re
import struct
import sys
from collections import Counter

MAPPING_SOURCE = "ff972661a75ca7f8c3c0458c3feb8b603c185eb8"
LINUX_SOURCE = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
HEADER = struct.Struct("<8s40s32sQQII")
RECORD = struct.Struct("<13Q24I32s32s32s")
FOOTER = struct.Struct("<8sQII")
MAX_RECORDS = 8192
MAX_BYTES = HEADER.size + MAX_RECORDS * RECORD.size + FOOTER.size
ZERO = bytes(32)
U64 = ("sequence operation descriptor clone original lower extent pin slot area_epoch "
       "store gc_epoch credit").split()
U32 = ("event operation_kind logical swap_type generation new_generation status requested "
       "completed compressed_length decoded_length compared codec tag version dictionary flags "
       "caps tickets pins reservations bios maps quarantines").split()
DIGESTS = ("compressed_sha256", "page_sha256", "observed_sha256")
FIELDS = U64 + U32 + list(DIGESTS)
TOKENS = ("operation", "descriptor", "clone", "original", "lower", "extent", "pin")
EVENTS = ("capture bind accept dispatch preparation reserve claim refuse cancel fallback "
          "lower_submit lower_complete flush publish pin oracle pin_release clone_endio "
          "upper_endio candidate_release carrier_release discard quarantine gc_begin gc_end "
          "capture_drop cleanup").split()
SOURCE_KEY = "logical swap_type slot area_epoch store generation"
PAYLOAD = "compressed_length decoded_length codec tag version dictionary compressed_sha256 page_sha256"
ALLOWED = {
    "capture": "operation_kind " + SOURCE_KEY + " " + PAYLOAD,
    "bind": "original",
    "accept": "operation_kind descriptor clone original flags " + SOURCE_KEY,
    "dispatch": "flags",
    "preparation": "flags",
    "reserve": "credit extent",
    "claim": "credit descriptor",
    "refuse": "status",
    "cancel": "credit flags",
    "fallback": "",
    "lower_submit": "lower extent flags requested compressed_length compressed_sha256",
    "lower_complete": "lower completed status observed_sha256",
    "flush": "extent status",
    "publish": "extent new_generation gc_epoch " + PAYLOAD,
    "pin": "pin extent gc_epoch " + SOURCE_KEY,
    "oracle": "pin decoded_length compared flags status page_sha256 observed_sha256",
    "pin_release": "pin status",
    "clone_endio": "descriptor clone status",
    "upper_endio": "original status",
    "candidate_release": "descriptor status",
    "carrier_release": "original status",
    "discard": "new_generation",
    "quarantine": "extent",
    "gc_begin": "operation_kind extent gc_epoch " + SOURCE_KEY,
    "gc_end": "status",
    "capture_drop": "status",
    "cleanup": "flags caps tickets pins reservations bios maps quarantines",
}
ALLOWED = {event: set(names.split()) | {"sequence", "event", "operation"}
           for event, names in ALLOWED.items()}
GATES = dict(source_mapped_authenticated=False, actual_physical_io=False,
             native_capture=False, live_admission=False, phase_a="BLOCKED",
             direct_compressed_handoff=False, forced_raw_bypass=False,
             import_active=False, semantic_qualification=False)


class Invalid(ValueError):
    """Only fixed categories and event ordinals reach diagnostics."""


def require(condition, reason):
    if not condition:
        raise Invalid(reason)


def scope_digest(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=True).encode("ascii")).digest()


def check_scope(scope):
    hashes = {"source": 40, "mapping_source": 40, "linux_source": 40,
              "kernel_sha256": 64, "module_sha256": 64, "workload_sha256": 64,
              "run_nonce": 32, "target": 32}
    nums = ("session", "epoch", "target_epoch", "registration_epoch",
            "first_logical", "page_count")
    require(type(scope) is dict and set(scope) == set(hashes) | set(nums) | {"profile"},
            "scope_fields")
    for key, length in hashes.items():
        value = scope[key]
        require(type(value) is str and len(value) == length and
                re.fullmatch("[0-9a-f]+", value) is not None and value != "0" * length,
                "scope_format")
    for key in nums:
        require(type(scope[key]) is int and 0 < scope[key] < 1 << 64, "scope_number")
    require(scope["mapping_source"] == MAPPING_SOURCE and scope["linux_source"] == LINUX_SOURCE
            and scope["profile"] == "M3568" and scope["page_count"] <= 4096 and
            scope["first_logical"] + scope["page_count"] - 1 < 1 << 32, "scope_profile")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "scope_duplicate")
        result[key] = value
    return result


def nonzero(value):
    return value != (ZERO if isinstance(value, bytes) else 0)


def key(row):
    return tuple(row[name] for name in SOURCE_KEY.split())


def payload(row):
    return tuple(row[name] for name in PAYLOAD.split())


def typed(row):
    require(row["tag"] == 90 and row["codec"] in (1, 2) and row["version"] == 1 and
            row["dictionary"] == 0 and 1 <= row["compressed_length"] <= 3568 and
            row["decoded_length"] == 4096 and nonzero(row["compressed_sha256"]) and
            nonzero(row["page_sha256"]), "typed_payload")
    return payload(row)


class Observation:
    def __init__(self, scope):
        self.scope = scope
        self.operations = {}
        self.pending_dispatch = []
        self.roles = {}
        self.lower = {}
        self.maps = {}
        self.generations = {}
        self.credit = 0
        self.reservation = None
        self.write_extents = set()
        self.counts = Counter()
        self.failure = None
        self.cleaned = False

    def failure_at(self, row, reason):
        if self.failure is None:
            self.failure = {"event_id": row["sequence"], "reason": reason}

    def token(self, value, role, fresh=True):
        require(value > 0 and (value not in self.roles if fresh else
                               self.roles.get(value) == role), "token_role_or_reuse")
        if fresh:
            self.roles[value] = role

    def logical(self, row):
        first = self.scope["first_logical"]
        require(first <= row["logical"] < first + self.scope["page_count"], "logical_scope")

    def source_key(self, row):
        self.logical(row)
        require(row["swap_type"] <= 255 and row["slot"] > 0 and row["area_epoch"] > 0
                and row["store"] > 0 and row["generation"] > 0, "source_key")
        return key(row)

    def new(self, row, kind):
        self.token(row["operation"], "operation")
        require(len(self.operations) < 1024, "operation_limit")
        entry = dict(kind=kind, logical=row["logical"], accepted=False, dispatched=False,
                     candidate=False, carrier=False, candidate_released=False,
                     carrier_released=False, clone_done=False, upper_done=False,
                     dropped=False, gc_done=False, reserve=0, claimed=False,
                     refused=False, cancelled=False, fallback=False, pins={},
                     lower=[], flushed=set(), flush_attempts=set(), published=False, discarded=False,
                     quarantined=set(), oracle=False, failure=False, source=None, payload=None)
        self.operations[row["operation"]] = entry
        return entry

    def apply(self, event, row):
        op = row["operation"]
        kind = row["operation_kind"]
        if event == "cleanup":
            require(op == 0 and row["flags"] == 7 and
                    not any(row[name] for name in ("caps", "tickets", "pins",
                                                   "reservations", "bios", "maps")) and
                    row["quarantines"] == self.counts["quarantines"] and
                    self.reservation is None and not self.pending_dispatch, "cleanup_debt")
            for entry in self.operations.values():
                require((entry["gc_done"] if entry["kind"] == 5 else
                         (entry["clone_done"] and entry["upper_done"] if entry["accepted"]
                          else entry["dropped"])) and
                        (not entry["candidate"] or entry["candidate_released"]) and
                        (not entry["carrier"] or entry["carrier_released"]) and
                        not entry["pins"] and all(self.lower[token]["done"]
                                                  for token in entry["lower"]), "incomplete_lifetime")
            require(self.counts["accepted_bios"] > 0, "missing_bios")
            self.cleaned = True
            return
        require(op > 0, "operation")
        if event == "capture":
            require(kind == 1, "capture_kind")
            source = self.source_key(row)
            content = typed(row)
            entry = self.new(row, kind)
            entry.update(source=source, payload=content, carrier=True, original=0)
            return
        if event == "gc_begin":
            require(kind == 5, "gc_kind")
            source = self.source_key(row)
            current = self.maps.get(row["logical"])
            require(current is not None and current["source"] == source and
                    current["extent"] == row["extent"] and current["epoch"] == row["gc_epoch"],
                    "gc_authority")
            entry = self.new(row, kind)
            entry.update(source=source, payload=current["payload"],
                         old_extent=row["extent"], old_epoch=row["gc_epoch"], dispatched=True,
                         ordered=True)
            return
        if event == "accept":
            self.logical(row)
            require(kind in (1, 2, 3, 4) and row["flags"] in (0, 1), "accept_kind")
            if kind == 1:
                entry = self.operations.get(op)
                require(entry is not None and entry["carrier"] and not entry["dropped"] and
                        not entry["accepted"] and entry["original"] == row["original"] and
                        row["original"] > 0 and entry["source"] == self.source_key(row),
                        "capture_binding")
            else:
                require(row["flags"] == 0 and not any(row[name] for name in
                        ("swap_type", "slot", "area_epoch", "store", "generation")),
                        "noncapture_source")
                entry = self.new(row, kind)
                self.token(row["original"], "original")
                entry["original"] = row["original"]
            self.token(row["descriptor"], "descriptor")
            self.token(row["clone"], "clone")
            entry.update(accepted=True, candidate=bool(row["flags"]),
                         descriptor=row["descriptor"], clone=row["clone"])
            self.pending_dispatch.append(op)
            self.counts["accepted_bios"] += 1
            return
        entry = self.operations.get(op)
        require(entry is not None and not entry["gc_done"], "operation_binding")
        if event == "bind":
            require(entry["carrier"] and not entry["accepted"] and not entry["dropped"] and
                    not entry["original"] and not entry["carrier_released"], "bind_order")
            self.token(row["original"], "original")
            entry["original"] = row["original"]
            return
        if event == "carrier_release":
            require(entry["carrier"] and not entry["carrier_released"] and
                    entry["original"] == row["original"] and row["status"] == 0,
                    "carrier_release")
            entry["carrier_released"] = True
            return
        if event == "capture_drop":
            require(entry["carrier"] and not entry["accepted"] and not entry["dropped"] and
                    row["status"] > 0, "capture_drop")
            entry["dropped"] = True
            return
        if event == "preparation":
            # MM decompression can precede acceptance. Ordinary preparation
            # may be done/discarded later; record observations, not inferred work.
            require(row["flags"] in (1, 2, 4) and not entry["dropped"] and
                    not entry["clone_done"] and (row["flags"] == 1 or entry["accepted"]),
                    "preparation_order")
            self.counts[("mm_decode" if row["flags"] == 1 else
                         "ordinary_prepared" if row["flags"] == 2 else "preparation_discarded")] += 1
            return
        if event == "candidate_release":
            require(entry["accepted"] and entry["candidate"] and not entry["candidate_released"]
                    and row["descriptor"] == entry["descriptor"] and row["status"] == 0,
                    "candidate_release")
            entry["candidate_released"] = True
            return
        if event == "upper_endio":
            require(entry["accepted"] and entry["clone_done"] and not entry["upper_done"] and
                    row["original"] == entry["original"] and
                    (not entry["clone_status"] or row["status"]), "upper_endio")
            entry["upper_done"] = True
            self.counts["upper_acks"] += 1
            if row["status"]:
                self.failure_at(row, "upper_status")
            return
        require((entry["accepted"] or entry["kind"] == 5) and not entry["clone_done"],
                "post_completion_or_unaccepted")
        if event == "dispatch":
            require(entry["accepted"] and not entry["dispatched"] and
                    (row["flags"] == 1 or (row["flags"] == 2 and entry["kind"] == 2)),
                    "dispatch_order")
            require(row["flags"] == 2 or self.pending_dispatch[0] == op, "ordered_dispatch")
            self.pending_dispatch.remove(op)
            entry.update(dispatched=True, ordered=row["flags"] == 1)
            return
        require(entry["dispatched"], "missing_dispatch")
        require(not (entry["published"] or entry["discarded"]) or
                event in ("pin_release", "clone_endio", "gc_end"), "post_publication")
        if event == "reserve":
            require(entry["kind"] == 1 and entry["ordered"] and entry["candidate"] and
                    not entry["candidate_released"] and not entry["reserve"] and
                    not entry["refused"] and self.reservation is None and
                    self.credit < row["credit"] < 1 << 32, "reserve_order")
            self.token(row["extent"], "extent")
            self.reservation = op
            self.credit = row["credit"]
            entry.update(reserve=row["credit"], reserved_extent=row["extent"])
        elif event == "claim":
            require(self.reservation == op and entry["reserve"] == row["credit"] and
                    not entry["claimed"] and not entry["refused"] and
                    not entry["candidate_released"] and row["descriptor"] == entry["descriptor"]
                    and entry["source"][-1] == self.generations.get(entry["logical"], 0) + 1,
                    "claim_order")
            entry["claimed"] = True
            self.counts["claims"] += 1
        elif event == "refuse":
            require(entry["kind"] == 1 and not entry["claimed"] and not entry["refused"]
                    and row["status"] > 0, "refuse_order")
            entry["refused"] = True
        elif event == "cancel":
            require(self.reservation == op and entry["refused"] and not entry["claimed"] and
                    not entry["cancelled"] and entry["reserve"] == row["credit"] and
                    row["flags"] == 1 and not entry["lower"], "cancel_order")
            self.reservation = None
            entry["cancelled"] = True
        elif event == "fallback":
            require(entry["refused"] and not entry["claimed"] and not entry["fallback"] and
                    (not entry["reserve"] or entry["cancelled"]), "fallback_order")
            entry["fallback"] = True
        elif event == "pin":
            source = self.source_key(row)
            current = self.maps.get(entry["logical"])
            require(entry["kind"] in (2, 5) and row["logical"] == entry["logical"] and
                    current is not None and current["source"] == source and
                    current["extent"] == row["extent"] and current["epoch"] == row["gc_epoch"]
                    and not entry["pins"], "pin_authority")
            if entry["kind"] == 5:
                require(source == entry["source"] and row["extent"] == entry["old_extent"],
                        "gc_pin_authority")
            self.token(row["pin"], "pin")
            entry["pins"][row["pin"]] = current.copy()
            entry["payload"] = current["payload"]
        elif event == "lower_submit":
            direction = row["flags"]
            require(direction in (1, 2) and 0 < row["requested"] <= 16384 and
                    0 <= row["compressed_length"] <= row["requested"], "lower_shape")
            if entry["kind"] == 1:
                require(direction == 2 and (entry["claimed"] or entry["fallback"]),
                        "lower_before_claim")
            self.token(row["lower"], "lower")
            if direction == 2:
                require(row["extent"] not in self.write_extents, "extent_write_reuse")
                if entry["kind"] == 1 and entry["claimed"]:
                    self.token(row["extent"], "extent", False)
                else:
                    self.token(row["extent"], "extent")
                self.write_extents.add(row["extent"])
            else:
                self.token(row["extent"], "extent", False)
            if entry["kind"] in (2, 5) and direction == 1:
                require(any(pin["extent"] == row["extent"] for pin in entry["pins"].values()),
                        "lower_pin")
            if entry["kind"] == 1 and entry["claimed"]:
                require(row["extent"] == entry["reserved_extent"], "reserved_extent")
            if entry["kind"] == 2:
                require(direction == 1, "read_direction")
            if entry["kind"] == 3:
                require(direction == 2, "write_direction")
            if entry["kind"] == 4:
                raise Invalid("discard_lower_unsupported")
            if entry["kind"] == 5 and direction == 2:
                require(entry["pins"] and any(self.lower[t]["direction"] == 1 and
                    self.lower[t]["good"] for t in entry["lower"]), "gc_source_read")
            if entry["kind"] in (1, 2, 5) and not entry["fallback"]:
                require(not any(self.lower[t]["direction"] == direction for t in entry["lower"]),
                        "dedicated_extent_count")
                require(entry["payload"] is not None and row["requested"] == 4096 and
                        row["compressed_length"] == entry["payload"][0] and
                        row["compressed_sha256"] == entry["payload"][-2], "lower_payload")
            self.lower[row["lower"]] = dict(op=op, direction=direction, extent=row["extent"],
                requested=row["requested"], digest=row["compressed_sha256"], done=False, good=False)
            entry["lower"].append(row["lower"])
            self.counts["lower_submissions"] += 1
        elif event == "lower_complete":
            lower = self.lower.get(row["lower"])
            require(lower is not None and lower["op"] == op and not lower["done"] and
                    row["completed"] <= lower["requested"], "lower_completion")
            require((not row["status"] and row["completed"] == lower["requested"]) or
                    not nonzero(row["observed_sha256"]), "failed_payload")
            lower["done"] = True
            lower["good"] = (row["status"] == 0 and row["completed"] == lower["requested"] and
                             nonzero(row["observed_sha256"]) and
                             (not nonzero(lower["digest"]) or row["observed_sha256"] == lower["digest"]))
            if not lower["good"]:
                entry["failure"] = True
                self.failure_at(row, "lower_error_or_digest")
            self.counts["lower_completions"] += 1
        elif event == "flush":
            require(row["extent"] not in entry["flush_attempts"] and
                    any(self.lower[t]["direction"] == 2 and self.lower[t]["extent"] == row["extent"]
                        and self.lower[t]["good"] for t in entry["lower"]), "flush_order")
            entry["flush_attempts"].add(row["extent"])
            if row["status"]:
                entry["failure"] = True
                self.failure_at(row, "flush_status")
            else:
                entry["flushed"].add(row["extent"])
        elif event == "publish":
            page = entry["logical"]
            require(entry["kind"] in (1, 3, 5) and not entry["published"] and
                    row["extent"] in entry["flushed"] and
                    not entry["failure"] and all(self.lower[t]["good"] for t in entry["lower"]) and
                    row["new_generation"] == self.generations.get(page, 0) + 1,
                    "publish_order")
            if entry["kind"] in (1, 5) and not entry["fallback"]:
                content = typed(row)
                require(content == entry["payload"] and (entry["claimed"] if entry["kind"] == 1
                        else entry["pins"] and any(self.lower[t]["direction"] == 1 and self.lower[t]["good"]
                                 for t in entry["lower"])), "publish_payload")
                old = self.maps.get(page)
                require((row["gc_epoch"] == 1 and row["new_generation"] == entry["source"][-1])
                        if entry["kind"] == 1 else
                        (old is not None and old["extent"] == entry["old_extent"] and
                         row["gc_epoch"] == entry["old_epoch"] + 1 and
                         row["extent"] != entry["old_extent"]), "publish_epoch")
                self.maps[page] = dict(source=entry["source"][:-1] + (row["new_generation"],),
                                       extent=row["extent"], epoch=row["gc_epoch"], payload=content)
            else:
                require(row["tag"] != 90 and row["gc_epoch"] == 0 and
                        any(self.lower[t]["direction"] == 2 and self.lower[t]["extent"] == row["extent"]
                            and self.lower[t]["digest"] == row["compressed_sha256"]
                            for t in entry["lower"]), "ordinary_not_typed")
                if entry["fallback"]:
                    require(row["page_sha256"] == entry["payload"][-1], "fallback_page")
                # Ordinary representation is recorded, never inferred as RAW.
                if row["tag"] == 0:
                    require(row["compressed_length"] == row["decoded_length"] == 4096 and
                            row["codec"] == row["version"] == row["dictionary"] == 0 and
                            nonzero(row["page_sha256"]) and
                            row["compressed_sha256"] == row["page_sha256"], "raw_payload")
                else:
                    require(0 < row["compressed_length"] < 4096 and row["decoded_length"] == 4096
                            and nonzero(row["compressed_sha256"]) and nonzero(row["page_sha256"]),
                            "ordinary_payload")
                self.maps.pop(page, None)
            self.generations[page] = row["new_generation"]
            entry["published"] = True
            if self.reservation == op:
                self.reservation = None
            self.counts["publications"] += 1
        elif event == "oracle":
            require(entry["kind"] == 2 and row["pin"] in entry["pins"] and
                    not entry["oracle"] and any(self.lower[t]["good"] and
                    self.lower[t]["direction"] == 1 for t in entry["lower"]), "oracle_order")
            expected = entry["pins"][row["pin"]]["payload"][-1]
            entry["oracle"] = (row["status"] == 0 and row["decoded_length"] == row["compared"] == 4096
                               and row["flags"] == 1 and row["page_sha256"] == expected and
                               row["observed_sha256"] == expected)
            if not entry["oracle"]:
                entry["failure"] = True
                self.failure_at(row, "oracle_mismatch")
            else:
                self.counts["verified_oracles"] += 1
        elif event == "pin_release":
            require(row["pin"] in entry["pins"] and row["status"] == 0 and
                    all(self.lower[t]["done"] for t in entry["lower"]) and
                    (entry["oracle"] or entry["failure"] if entry["kind"] == 2 else
                     entry["published"] or entry["quarantined"] or entry["failure"]),
                    "pin_release")
            del entry["pins"][row["pin"]]
        elif event == "discard":
            page = entry["logical"]
            require(entry["kind"] == 4 and not entry["discarded"] and
                    row["new_generation"] == self.generations.get(page, 0) + 1, "discard_order")
            self.maps.pop(page, None)
            self.generations[page] = row["new_generation"]
            entry["discarded"] = True
        elif event == "quarantine":
            require(not entry["published"] and row["extent"] not in entry["quarantined"] and
                    any(self.lower[t]["direction"] == 2 and self.lower[t]["extent"] == row["extent"]
                        and self.lower[t]["done"] for t in entry["lower"]), "quarantine_order")
            entry["quarantined"].add(row["extent"])
            if self.reservation == op:
                self.reservation = None
            self.counts["quarantines"] += 1
            entry["failure"] = True
            self.failure_at(row, "quarantined_extent")
        elif event == "clone_endio":
            require(entry["accepted"] and row["descriptor"] == entry["descriptor"] and
                    row["clone"] == entry["clone"] and not entry["pins"] and
                    all(self.lower[t]["done"] for t in entry["lower"]), "clone_endio")
            if row["status"] == 0:
                require(not entry["failure"] and (entry["oracle"] if entry["kind"] == 2 else
                         entry["discarded"] if entry["kind"] == 4 else entry["published"]),
                        "early_success_ack")
            else:
                require(not entry["claimed"] or entry["published"] or
                        (entry["quarantined"] and all(
                            self.lower[t]["extent"] in entry["quarantined"]
                            for t in entry["lower"] if self.lower[t]["direction"] == 2)),
                        "claimed_error_debt")
                self.failure_at(row, "clone_status")
            entry.update(clone_done=True, clone_status=row["status"])
            self.counts["clone_acks"] += 1
        elif event == "gc_end":
            require(entry["kind"] == 5 and not entry["pins"] and
                    all(self.lower[t]["done"] for t in entry["lower"]) and
                    (entry["published"] if not row["status"] else
                     bool(entry["quarantined"]) or not any(self.lower[t]["direction"] == 2
                                                          for t in entry["lower"])), "gc_end")
            if row["status"]:
                self.failure_at(row, "gc_status")
            entry["gc_done"] = True
        else:
            raise Invalid("unknown_event")


def validate(raw, scope):
    check_scope(scope)
    require(HEADER.size + FOOTER.size <= len(raw) <= MAX_BYTES, "input_size")
    magic, mapping, digest, count, high, capacity, size = HEADER.unpack_from(raw)
    require(magic == b"SWZOBS2\0" and mapping == MAPPING_SOURCE.encode("ascii") and
            digest == scope_digest(scope), "header_scope")
    require(0 < count <= capacity <= MAX_RECORDS and 0 < high <= capacity * 8 and
            size == RECORD.size, "header_bounds")
    require(len(raw) == HEADER.size + count * RECORD.size + FOOTER.size, "truncated_or_extra")
    magic, final_count, loss, reserved = FOOTER.unpack_from(raw, len(raw) - FOOTER.size)
    require(magic == b"SWZEND2\0" and final_count == count and reserved == 0, "footer")
    require(loss == 0, "recorder_loss")
    observation = Observation(scope)
    for index in range(count):
        row = dict(zip(FIELDS, RECORD.unpack_from(raw, HEADER.size + index * RECORD.size)))
        try:
            require(row["sequence"] == index + 1 and not observation.cleaned, "sequence")
            require(1 <= row["event"] <= len(EVENTS) and row["status"] <= 255 and
                    all(row[name] <= high for name in TOKENS), "event_fields")
            event = EVENTS[row["event"] - 1]
            require(not any(nonzero(value) for name, value in row.items()
                            if name not in ALLOWED[event]), "unexpected_field")
            observation.apply(event, row)
            observation.counts[event] += 1
        except Invalid as error:
            error.event_id = index + 1
            raise
    require(observation.cleaned, "missing_cleanup")
    return dict(status=("OBSERVED_FAILURE_BLOCKED" if observation.failure else
                        "CONSISTENT_RECORDER_OBSERVATIONS_ONLY"),
                records=count, counts=dict(observation.counts),
                first_failure=observation.failure, mapping_source=MAPPING_SOURCE, **GATES)


def main():
    try:
        require(len(sys.argv) == 2 and len(sys.argv[1]) <= 4096, "scope_argument")
        scope = json.loads(sys.argv[1], object_pairs_hook=unique_object)
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = validate(raw, scope)
    except Invalid as error:
        result = dict(status="BLOCKED", reason=str(error),
                      event_id=getattr(error, "event_id", None), **GATES)
    except (ValueError, TypeError, KeyError, RecursionError, OSError, struct.error):
        result = dict(status="BLOCKED", reason="invalid_input", **GATES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_RECORDER_OBSERVATIONS_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
