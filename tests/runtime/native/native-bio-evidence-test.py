#!/usr/bin/env python3
"""Fabricated per-BIO records only. No kernel, trace, device or host discovery."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/native-bio-evidence.py"
SPEC = importlib.util.spec_from_file_location("native_bio_evidence", PATH)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def opaque(value):
    return format(value, "032x")


def typed(codec=1, length=3568):
    return {"tag": 90, "codec": codec, "version": 1, "dictionary": 0, "length": length, "decoded_length": P.PAGE,
            "sha256": "a" * 64, "page_sha256": "b" * 64}


class Fixture:
    def __init__(self):
        self.scope = {key: "c" * length for key, length in P.SCOPE_HASHES.items()}
        self.scope.update(source=P.MAPPING_SOURCE, linux_source=P.LINUX_SOURCE,
                          mapping_source=P.MAPPING_SOURCE, profile="M3568",
                          session=1, epoch=2, target_epoch=3, registration_epoch=4,
                          first_logical=1, page_count=16)
        self.digest = P.scope_digest(self.scope)
        self.events = []

    def key(self, op, page, generation, store=1):
        return dict(descriptor=opaque(3 * op), bio=opaque(3 * op + 1),
                    original=opaque(3 * op + 2), logical=page, swap_type=0, slot=page,
                    area_epoch=1, store=store, generation=generation)

    def emit(self, event, op, key, **data):
        self.events.append(dict(id=len(self.events) + 1, scope_sha256=self.digest,
                                event=event, op=op, key=copy.deepcopy(key),
                                data=copy.deepcopy(data)))

    def accept(self, op, key, kind, raw=None):
        self.emit("accept", op, key, operation=kind, raw_sha256=raw)

    def begin_write(self, op, key, payload, refusal=None):
        self.emit("evict", op, key, **payload)
        self.accept(op, key, "typed_write")
        extent = opaque(1000 + op)
        if refusal != "before":
            self.emit("reserve", op, key, credit=op, extent=extent)
        if refusal:
            self.emit("refuse", op, key)
            if refusal == "reserved":
                self.emit("cancel", op, key, credit=op, tail_verified=True)
            self.emit("fallback", op, key)
            return P.raw_payload(payload["page_sha256"]), opaque(2000 + op)
        self.emit("claim", op, key, credit=op)
        return payload, extent

    def lower(self, op, key, payload, extent, failure=None):
        lower = opaque(3000 + op)
        self.emit("lower_submit", op, key, lower=lower, extent=extent,
                  requested_bytes=P.PAGE, payload_length=payload["length"],
                  payload_sha256=payload["sha256"])
        self.emit("lower_complete", op, key, lower=lower,
                  completed_bytes=2048 if failure == "short" else P.PAGE,
                  status=5 if failure == "status" else 0,
                  payload_sha256=None if failure in ("short", "status") else
                  "f" * 64 if failure == "digest" else payload["sha256"])

    def ack_release(self, op, key, status=0):
        self.emit("ack", op, key, status=status)
        self.emit("release", op, key)

    def write(self, op, key, payload, refusal=None, failure=None):
        payload, extent = self.begin_write(op, key, payload, refusal)
        self.lower(op, key, payload, extent, failure)
        if failure not in ("short", "status"):
            self.emit("flush", op, key, status=5 if failure == "flush" else 0)
        if failure:
            self.emit("quarantine", op, key, extent=extent)
        else:
            self.emit("publish", op, key, extent=extent, payload=payload,
                      gc_epoch=1 if payload["tag"] == 90 else 0, generation=key["generation"])
        self.ack_release(op, key, 5 if failure else 0)
        return extent

    def read(self, op, key, payload, extent, epoch, failure=None):
        self.accept(op, key, "typed_read")
        pin = opaque(4000 + op)
        self.emit("pin", op, key, pin=pin, extent=extent, gc_epoch=epoch)
        self.lower(op, key, payload, extent, failure)
        if failure not in ("short", "status", "digest"):
            self.emit("oracle", op, key, decoded_bytes=P.PAGE, compared_bytes=P.PAGE,
                      decoded_sha256="f" * 64 if failure else payload["page_sha256"],
                      expected_sha256=payload["page_sha256"], byte_equal=not failure,
                      decoder_status=0)
        self.emit("pin_release", op, key, pin=pin, status=0)
        self.ack_release(op, key, 5 if failure else 0)

    def gc(self, op, key, payload, old_extent, failure=None):
        self.emit("gc_begin", op, key, old_extent=old_extent, gc_epoch=1)
        pin, extent = opaque(4000 + op), opaque(1000 + op)
        self.emit("pin", op, key, pin=pin, extent=old_extent, gc_epoch=1)
        lower = opaque(5000 + op)
        self.emit("gc_read_submit", op, key, lower=lower, extent=old_extent, requested_bytes=P.PAGE)
        self.emit("gc_read_complete", op, key, lower=lower, completed_bytes=P.PAGE, status=0,
                  payload_sha256=payload["sha256"])
        self.lower(op, key, payload, extent, failure)
        if failure not in ("short", "status"):
            self.emit("flush", op, key, status=0)
        if failure:
            self.emit("quarantine", op, key, extent=extent)
        else:
            self.emit("publish", op, key, extent=extent, payload=payload, gc_epoch=2, generation=key["generation"] + 1)
        self.emit("pin_release", op, key, pin=pin, status=0)
        self.emit("release", op, key)
        return extent

    def overwrite(self, op, key):
        payload, extent = P.raw_payload("d" * 64), opaque(1000 + op)
        self.accept(op, key, "overwrite", payload["sha256"])
        self.lower(op, key, payload, extent)
        self.emit("flush", op, key, status=0)
        self.emit("publish", op, key, extent=extent, payload=payload, gc_epoch=0, generation=key["generation"])
        self.ack_release(op, key)

    def discard(self, op, key):
        self.accept(op, key, "discard")
        self.emit("discard", op, key)
        self.ack_release(op, key)

    def capture(self, quarantines=0):
        self.emit("cleanup", 0, None, route_revoked=True, rcu_drained=True,
                  worker_drained=True, caps=0, tickets=0, decoder_pins=0,
                  reservations=0, pending_bios=0, live_maps=0,
                  quarantined_extents=quarantines)
        return dict(schema=P.SCHEMA, scope=self.scope, initial={"empty": True, "generation": 0},
                    events=self.events, footer=dict(records=len(self.events),
                    last_id=len(self.events), lost=0, overflow=False, truncated=False))


def complete_fixture():
    f = Fixture()
    payload = typed()
    first = f.key(1, 1, 1)
    old = f.write(1, first, payload)
    f.read(2, f.key(2, 1, 1), payload, old, 1)
    moved = f.gc(3, first, payload, old)
    f.read(4, f.key(4, 1, 2), payload, moved, 2)
    f.overwrite(5, f.key(5, 1, 3, 2))
    f.discard(6, f.key(6, 1, 4, 2))
    second_payload = typed(2, 100)
    second = f.write(7, f.key(7, 2, 1), second_payload)
    f.read(8, f.key(8, 2, 1), second_payload, second, 1)
    f.write(9, f.key(9, 3, 1), payload, refusal="reserved")
    f.write(10, f.key(10, 4, 1), payload, refusal="before")
    return f.capture(), f.digest


def event(record, name, op):
    return next(row for row in record["events"] if row["event"] == name and row["op"] == op)


def renumber(record):
    for index, row in enumerate(record["events"], 1):
        row["id"] = index
    record["footer"].update(records=len(record["events"]), last_id=len(record["events"]))


def drop(record, name, op):
    record["events"].remove(event(record, name, op))
    renumber(record)


class NativeBioEvidence(unittest.TestCase):
    def test_complete_fabricated_stream(self):
        capture, digest = complete_fixture()
        result = P.validate(capture, digest)
        self.assertEqual(result["status"], "CONSISTENT_OBSERVATIONS_ONLY")
        self.assertIsNone(result["first_failure"])
        expected = dict(accepted_bios=9, upper_acks=9, error_acks=0, evictions=4,
                        claims=2, refusals=2, cancels=1, ordinary_fallbacks=2,
                        lower_reads=4, lower_writes=6, durable_flushes=6,
                        typed_publications=2, write_publications=5, gc_publications=1,
                        verified_typed_reads=3, pins=4, pin_releases=4,
                        overwrites=1, discards=1, operation_releases=10)
        for key, value in expected.items():
            self.assertEqual(result["counts"].get(key, 0), value, key)
        self.assertEqual({key: result[key] for key in P.GATES}, P.GATES)
        print("FABRICATED_BASELINE=" + json.dumps(
            {"records": result["records"], "counts": result["counts"]}, sort_keys=True))

    def test_semantic_negatives(self):
        def update(name, op, **changes):
            return lambda r: event(r, name, op)["data"].update(changes)

        def key_update(name, op, **changes):
            return lambda r: event(r, name, op)["key"].update(changes)

        def duplicate_ack(r):
            row = copy.deepcopy(event(r, "ack", 1))
            r["events"].insert(r["events"].index(event(r, "release", 1)), row)
            renumber(r)

        cases = [
            ("loss_or_truncation", lambda r: r["footer"].update(lost=1)),
            ("loss_or_truncation", lambda r: r["footer"].update(overflow=True)),
            ("loss_or_truncation", lambda r: r["footer"].update(truncated=True)),
            ("loss_or_truncation", lambda r: r["footer"].update(records=0)),
            ("sequence_or_scope", lambda r: r["events"][1].update(id=1)),
            ("sequence_or_scope", lambda r: r["events"][1].update(scope_sha256="e" * 64)),
            ("scope_mismatch", lambda r: r["scope"].update(session=99)),
            ("unmapped_profile", lambda r: r["scope"].update(profile="M4095")),
            ("initial_baseline", lambda r: r["initial"].update(empty=False)),
            ("integer", lambda r: r["events"][0].update(id=True)),
            ("typed_codec", update("evict", 1, codec=3)),
            ("typed_codec", update("evict", 1, tag=0)),
            ("typed_codec", update("evict", 1, version=2)),
            ("integer", update("evict", 1, length=3569)),
            ("integer", update("evict", 1, length=True)),
            ("opaque_id_or_digest", update("evict", 1, sha256="bad")),
            ("fields", update("evict", 1, pointer="do-not-echo")),
            ("bio_identity_alias", key_update("evict", 1, bio=opaque(3))),
            ("eviction_binding", key_update("accept", 1, original=opaque(999))),
            ("operation_binding", key_update("claim", 1, store=2)),
            ("reservation_binding", update("claim", 1, credit=99)),
            ("lower_submit", lambda r: drop(r, "claim", 1)),
            ("lower_submit", update("lower_submit", 1, requested_bytes=3568)),
            ("lower_submit", update("lower_submit", 1, payload_length=100)),
            ("lower_submit", update("lower_submit", 1, payload_sha256="c" * 64)),
            ("extent_binding", update("lower_submit", 1, extent=opaque(999))),
            ("lower_completion", update("lower_complete", 1, lower=opaque(999))),
            ("flush_order", lambda r: drop(r, "lower_complete", 1)),
            ("durable_publication", lambda r: drop(r, "flush", 1)),
            ("durable_publication", update("publish", 1, gc_epoch=2)),
            ("upper_ack", lambda r: drop(r, "publish", 1)),
            ("upper_ack", duplicate_ack),
            ("pin_authority", update("pin", 2, extent=opaque(999))),
            ("lower_submit", lambda r: drop(r, "pin", 2)),
            ("oracle_binding", update("oracle", 2, expected_sha256="c" * 64)),
            ("upper_ack", update("oracle", 2, compared_bytes=4095)),
            ("upper_ack", lambda r: drop(r, "pin_release", 2)),
            ("pin_release_order", update("pin_release", 2, pin=opaque(999))),
            ("gc_authority", update("gc_begin", 3, gc_epoch=2)),
            ("lower_submit", lambda r: drop(r, "gc_read_complete", 3)),
            ("generation", update("publish", 3, generation=1)),
            ("typed_format", update("evict", 1, dictionary=1)),
            ("typed_format", update("evict", 1, decoded_length=4095)),
            ("durable_publication", update("publish", 3, gc_epoch=1)),
            ("read_authority", key_update("accept", 4, generation=1)),
            ("pin_authority", update("pin", 4, extent=opaque(1001))),
            ("generation", key_update("accept", 5, generation=1)),
            ("generation", key_update("accept", 6, generation=5)),
            ("fallback_after_claim", lambda r: drop(r, "cancel", 9)),
            ("cancel_order", update("cancel", 9, tail_verified=False)),
            ("cleanup_debt", update("cleanup", 0, decoder_pins=1)),
            ("cleanup_fence", update("cleanup", 0, rcu_drained=False)),
            ("quarantine_debt", update("cleanup", 0, quarantined_extents=1)),
            ("missing_cleanup_or_bios", lambda r: drop(r, "cleanup", 0)),
            ("incomplete_operations", lambda r: drop(r, "release", 10)),
        ]
        for reason, mutate in cases:
            with self.subTest(reason=reason):
                record, digest = complete_fixture()
                mutate(record)
                with self.assertRaisesRegex(P.InvalidEvidence, "^" + reason + "$"):
                    P.validate(record, digest)
        print("SEMANTIC_NEGATIVES=" + str(len(cases)))

    def test_reported_failures_never_qualify(self):
        cases = [
            ("write", "short", "short_lower_completion"),
            ("write", "status", "lower_status"),
            ("write", "flush", "flush_status"),
            ("read", "short", "short_lower_completion"),
            ("read", "digest", "compressed_digest_mismatch"),
            ("read", "oracle", "full_page_oracle"),
            ("gc", "status", "lower_status"),
        ]
        for operation, failure, reason in cases:
            with self.subTest(operation=operation, failure=failure):
                f = Fixture()
                payload = typed()
                key = f.key(1, 1, 1)
                if operation == "write":
                    f.write(1, key, payload, failure=failure)
                else:
                    extent = f.write(1, key, payload)
                    if operation == "read":
                        f.read(2, f.key(2, 1, 1), payload, extent, 1, failure)
                    else:
                        f.gc(2, key, payload, extent, failure)
                record = f.capture(quarantines=int(operation != "read"))
                result = P.validate(record, f.digest)
                self.assertEqual(result["status"], "OBSERVED_FAILURE_BLOCKED")
                self.assertEqual(result["first_failure"]["reason"], reason)
                self.assertGreater(result["first_failure"]["event_id"], 0)
                self.assertEqual(result["counts"].get("quarantines", 0), int(operation != "read"))
                self.assertEqual({key: result[key] for key in P.GATES}, P.GATES)
        print("OBSERVED_FAILURE_CASES=" + str(len(cases)))

    def test_cli_bounded_input_and_no_echo(self):
        capture, digest = complete_fixture()
        valid = json.dumps(capture).encode()
        cases = [
            (b'{"private":"DO-NOT-ECHO","private":1}', "duplicate_json_key"),
            (b'{"private":NaN}', "invalid_json_constant"),
            (b'\xff', "invalid_input"),
            (valid[:-1], "invalid_input"),
            (b'[' * 2000, "invalid_input"),
            (b' ' * (P.MAX_BYTES + 1), "input_size"),
            (b'{"private":"DO-NOT-ECHO"}', "fields"),
        ]
        for raw, reason in cases:
            with self.subTest(reason=reason):
                result = subprocess.run([sys.executable, "-B", str(PATH), digest],
                    input=raw, capture_output=True, timeout=5, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(result.stderr)
                self.assertNotIn(b"DO-NOT-ECHO", result.stdout)
                output = json.loads(result.stdout)
                self.assertEqual(output["reason"], reason)
                self.assertEqual({key: output[key] for key in P.GATES}, P.GATES)
        ok = subprocess.run([sys.executable, "-B", str(PATH), digest],
                            input=valid, capture_output=True, timeout=5, check=True)
        self.assertFalse(json.loads(ok.stdout)["live_admission"])
        self.assertNotIn(digest.encode(), ok.stdout)
        bad = subprocess.run([sys.executable, "-B", str(PATH), "d" * 64],
                             input=valid, capture_output=True, timeout=5, check=False)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)["reason"], "scope_mismatch")
        print("CLI_NEGATIVES=" + str(len(cases) + 1))


if __name__ == "__main__":
    unittest.main()
