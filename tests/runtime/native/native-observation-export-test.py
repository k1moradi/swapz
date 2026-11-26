#!/usr/bin/env python3
"""Test actual C recorder exports with fabricated producers only."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

PARSER_PATH = Path(__file__).resolve().parents[2] / "tools/native-observation-export.py"
SPEC = importlib.util.spec_from_file_location("observation_export", PARSER_PATH)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
BINARY = sys.argv.pop(1)
SCOPE = dict(source=P.MAPPING_SOURCE, mapping_source=P.MAPPING_SOURCE,
             linux_source=P.LINUX_SOURCE, kernel_sha256="a" * 64,
             module_sha256="b" * 64, workload_sha256="c" * 64,
             run_nonce="d" * 32, target="e" * 32, session=1, epoch=2,
             target_epoch=3, registration_epoch=4, first_logical=1,
             page_count=16, profile="M3568")
DIGEST = P.scope_digest(SCOPE).hex()


def run_fixture(mode):
    return subprocess.run([BINARY, mode, DIGEST], capture_output=True, timeout=10,
                          check=True).stdout


def unpack(raw):
    header = list(P.HEADER.unpack_from(raw))
    footer = list(P.FOOTER.unpack_from(raw, len(raw) - P.FOOTER.size))
    rows = [dict(zip(P.FIELDS, P.RECORD.unpack_from(raw, P.HEADER.size + i * P.RECORD.size)))
            for i in range(header[3])]
    return header, rows, footer


def repack(header, rows, footer, renumber=False):
    if renumber:
        header[3] = footer[1] = len(rows)
        for i, row in enumerate(rows, 1):
            row["sequence"] = i
    return P.HEADER.pack(*header) + b"".join(
        P.RECORD.pack(*(row[name] for name in P.FIELDS)) for row in rows) + P.FOOTER.pack(*footer)


def event(rows, name, occurrence=0):
    return [row for row in rows if row["event"] == P.EVENTS.index(name) + 1][occurrence]


class RecorderExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = run_fixture("fixture")

    def test_interleaved_actual_c_export(self):
        result = P.validate(self.raw, SCOPE)
        self.assertEqual(result["status"], "CONSISTENT_RECORDER_OBSERVATIONS_ONLY")
        self.assertEqual({k: result[k] for k in P.GATES}, P.GATES)
        self.assertEqual(result["records"], 53)
        expected = {"accepted_bios": 4, "claims": 2, "publications": 2,
                    "lower_submissions": 4, "lower_completions": 4,
                    "clone_acks": 4, "upper_acks": 4, "verified_oracles": 2,
                    "candidate_release": 2, "carrier_release": 2,
                    "mm_decode": 2, "ordinary_prepared": 2, "preparation_discarded": 2}
        for field, value in expected.items():
            self.assertEqual(result["counts"][field], value, field)
        _, rows, _ = unpack(self.raw)
        self.assertLess(event(rows, "candidate_release")["sequence"],
                        event(rows, "clone_endio")["sequence"])
        self.assertGreater(event(rows, "candidate_release", 1)["sequence"],
                           event(rows, "upper_endio", 1)["sequence"])
        self.assertEqual(event(rows, "lower_complete", 2)["operation"],
                         event(rows, "lower_submit", 3)["operation"])
        self.assertEqual(event(rows, "lower_complete", 3)["operation"],
                         event(rows, "lower_submit", 2)["operation"])
        print("INTERLEAVED_EXPORT=" + json.dumps(
            {"records": result["records"], "counts": result["counts"]}, sort_keys=True))

    def test_hostile_transport(self):
        h, rows, f = unpack(self.raw)
        cases = [
            ("input_size", b""),
            ("input_size", b"x" * (P.MAX_BYTES + 1)),
            ("truncated_or_extra", self.raw[:-1]),
            ("truncated_or_extra", self.raw + b"x"),
            ("header_scope", repack([b"invalid!", *h[1:]], rows, f)),
            ("header_scope", repack([h[0], b"f" * 40, *h[2:]], rows, f)),
            ("header_scope", repack([*h[:2], b"x" * 32, *h[3:]], rows, f)),
            ("header_bounds", repack([*h[:3], 8193, *h[4:]], rows, f)),
            ("header_bounds", repack([*h[:4], 0, *h[5:]], rows, f)),
            ("header_bounds", repack([*h[:5], 8193, h[6]], rows, f)),
            ("header_bounds", repack([*h[:6], P.RECORD.size - 1], rows, f)),
            ("footer", repack(h, rows, [b"invalid!", *f[1:]])),
            ("footer", repack(h, rows, [f[0], f[1] + 1, *f[2:]])),
            ("footer", repack(h, rows, [*f[:3], 1])),
            ("recorder_loss", repack(h, rows, [*f[:2], 1, 0])),
            ("recorder_loss", run_fixture("loss")),
        ]
        for reason, raw in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(P.Invalid, "^" + reason + "$"):
                    P.validate(raw, SCOPE)
        with self.assertRaisesRegex(P.Invalid, "^header_scope$"):
            P.validate(self.raw, dict(SCOPE, session=5))
        with self.assertRaisesRegex(P.Invalid, "^scope_profile$"):
            P.validate(self.raw, dict(SCOPE, profile="M4095"))
        with self.assertRaisesRegex(P.Invalid, "^scope_number$"):
            P.validate(self.raw, dict(SCOPE, session=True))
        print("TRANSPORT_NEGATIVES=" + str(len(cases) + 3))

    def test_hostile_concurrent_lifetimes(self):
        def update(name, occurrence=0, **changes):
            return lambda rows: event(rows, name, occurrence).update(changes)

        def drop(name, occurrence=0):
            return lambda rows: rows.remove(event(rows, name, occurrence))

        def duplicate(name, occurrence=0):
            def mutate(rows):
                row = event(rows, name, occurrence)
                rows.insert(rows.index(row) + 1, copy.deepcopy(row))
            return mutate

        def cross_completion(rows):
            event(rows, "lower_complete", 2)["operation"] = event(rows, "lower_submit", 2)["operation"]

        def early_upper(rows):
            row = event(rows, "upper_endio")
            rows.remove(row)
            rows.insert(rows.index(event(rows, "clone_endio")), row)

        cases = [
            ("event_fields", update("capture", event=999)),
            ("event_fields", update("capture", descriptor=(1 << 64) - 1)),
            ("event_fields", update("lower_complete", status=256)),
            ("unexpected_field", update("bind", slot=1)),
            ("unexpected_field", update("candidate_release", observed_sha256=b"x" * 32)),
            ("typed_payload", update("capture", dictionary=1)),
            ("typed_payload", update("capture", compressed_length=3569)),
            ("source_key", update("capture", store=0)),
            ("capture_binding", update("accept", generation=2)),
            ("token_role_or_reuse", lambda rows: event(rows, "accept").update(
                clone=event(rows, "accept")["descriptor"])),
            ("preparation_order", update("preparation", flags=8)),
            ("missing_dispatch", drop("dispatch")),
            ("claim_order", update("claim", credit=2)),
            ("lower_before_claim", drop("claim")),
            ("lower_payload", update("lower_submit", compressed_length=99)),
            ("lower_completion", cross_completion),
            ("lower_completion", duplicate("lower_complete", 2)),
            ("flush_order", drop("lower_complete")),
            ("publish_order", drop("flush")),
            ("publish_order", update("publish", new_generation=2)),
            ("publish_epoch", update("publish", gc_epoch=2)),
            ("early_success_ack", drop("publish")),
            ("upper_endio", early_upper),
            ("upper_endio", duplicate("upper_endio")),
            ("post_completion_or_unaccepted", duplicate("clone_endio")),
            ("candidate_release", duplicate("candidate_release", 1)),
            ("carrier_release", duplicate("carrier_release", 1)),
            ("incomplete_lifetime", drop("candidate_release", 1)),
            ("incomplete_lifetime", drop("carrier_release", 1)),
            ("incomplete_lifetime", drop("upper_endio", 3)),
            ("pin_authority", update("pin", generation=2)),
            ("lower_pin", drop("pin")),
            ("oracle_order", drop("lower_complete", 2)),
            ("pin_release", drop("oracle")),
            ("early_success_ack", update("oracle", compared=4095)),
            ("clone_endio", drop("pin_release")),
            ("cleanup_debt", update("cleanup", pins=1)),
            ("cleanup_debt", update("cleanup", flags=3)),
            ("missing_cleanup", drop("cleanup")),
            ("sequence", duplicate("cleanup")),
        ]
        for reason, mutate in cases:
            with self.subTest(reason=reason):
                h, rows, f = unpack(self.raw)
                mutate(rows)
                with self.assertRaisesRegex(P.Invalid, "^" + reason + "$"):
                    P.validate(repack(h, rows, f, True), SCOPE)
        h, rows, f = unpack(self.raw)
        rows[1]["sequence"] = 1
        with self.assertRaisesRegex(P.Invalid, "^sequence$"):
            P.validate(repack(h, rows, f), SCOPE)
        print("CONCURRENT_NEGATIVES=" + str(len(cases) + 1))

    def test_observed_failure_preserves_other_parallel_read(self):
        h, rows, f = unpack(self.raw)
        oracle = event(rows, "oracle")
        op = oracle["operation"]
        oracle["compared"] = 4095
        for row in rows:
            if row["operation"] == op and row["event"] in (
                    P.EVENTS.index("clone_endio") + 1, P.EVENTS.index("upper_endio") + 1):
                row["status"] = 5
        result = P.validate(repack(h, rows, f), SCOPE)
        self.assertEqual(result["status"], "OBSERVED_FAILURE_BLOCKED")
        self.assertEqual(result["first_failure"], {"event_id": oracle["sequence"],
                                                   "reason": "oracle_mismatch"})
        self.assertEqual(result["counts"]["verified_oracles"], 1)
        self.assertEqual(result["counts"]["upper_acks"], 4)
        self.assertEqual({k: result[k] for k in P.GATES}, P.GATES)

    def test_cli_no_identity_echo(self):
        scope_text = json.dumps(SCOPE)
        command = [sys.executable, "-B", str(PARSER_PATH), scope_text]
        good = subprocess.run(command, input=self.raw, capture_output=True, timeout=5, check=True)
        self.assertEqual(json.loads(good.stdout)["status"], "CONSISTENT_RECORDER_OBSERVATIONS_ONLY")
        self.assertNotIn(SCOPE["run_nonce"].encode(), good.stdout)
        h, rows, f = unpack(self.raw)
        event(rows, "bind")["observed_sha256"] = b"DO-NOT-ECHO".ljust(32, b"x")
        bad = subprocess.run(command, input=repack(h, rows, f), capture_output=True,
                             timeout=5, check=False)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(bad.stderr)
        self.assertNotIn(b"DO-NOT-ECHO", bad.stdout)
        self.assertEqual(json.loads(bad.stdout)["reason"], "unexpected_field")
        print("CLI_NEGATIVES=1")


if __name__ == "__main__":
    unittest.main()
