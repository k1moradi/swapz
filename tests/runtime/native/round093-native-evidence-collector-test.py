#!/usr/bin/env python3
"""Source-shaped, fabricated status records only; no host device operations."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/round093-native-evidence-collector.py"
SPEC = importlib.util.spec_from_file_location("collector", PATH)
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


def fixture():
    scope = {key: "a" * length for key, length in COLLECTOR.SCOPE_LENGTHS.items()}
    scope.update(source=COLLECTOR.MAPPING_SOURCE, linux_source=COLLECTOR.LINUX_SOURCE)
    def sample(time, value):
        fields = {"version": "test", "mode": "alpha-live-gc",
                  "origin_carrier_compiled": 1}
        fields.update(dict.fromkeys(COLLECTOR.COUNTERS, value))
        fields.update(dict.fromkeys(COLLECTOR.GAUGES, 4096))
        return {"scope": copy.deepcopy(scope), "monotonic_ns": time,
                "dm_info": " ".join(f"{key}={value}" for key, value in fields.items())}
    return {"expected_scope": scope, "before": sample(1, 10), "after": sample(2, 20)}


class NativeEvidenceCollector(unittest.TestCase):
    def test_observations_not_admission(self):
        record = fixture()
        result = COLLECTOR.collect(**record)
        self.assertEqual(result["counter_deltas"], dict.fromkeys(COLLECTOR.COUNTERS, 10))
        self.assertEqual(result["interval_ns"], 1)
        self.assertEqual(result["phase_a"], "BLOCKED")
        self.assertFalse(result["live_admission"])
        self.assertFalse(result["actual_physical_io"])
        self.assertFalse(result["source_mapped_authenticated"])
        self.assertEqual(len(result["missing_native_proof"]), 10)
        self.assertNotIn("handoffs", result["counter_deltas"])
        self.assertNotIn("upper_ack", result["counter_deltas"])

    def test_fail_closed(self):
        def edit_status(record, before, after):
            record["after"]["dm_info"] = record["after"]["dm_info"].replace(before, after)
        cases = [
            ("mixed_scope", lambda r: r["after"]["scope"].update(module_sha256="b" * 64)),
            ("mixed_scope", lambda r: r["after"]["scope"].update(device_scope_sha256="b" * 64)),
            ("unmapped_source", lambda r: r["after"]["scope"].update(source="b" * 40)),
            ("scope_format", lambda r: r["expected_scope"].update(boot_sha256=None)),
            ("sample_order", lambda r: r["after"].update(monotonic_ns=1)),
            ("sample_time", lambda r: r["after"].update(monotonic_ns=True)),
            ("missing_status_field", lambda r: edit_status(r, "physical_write=20", "")),
            ("duplicate_or_malformed_field", lambda r: edit_status(r, "physical_write=20", "physical_write=20 physical_write=20")),
            ("counter_regressed", lambda r: edit_status(r, "physical_write=20", "physical_write=9")),
            ("counter_format", lambda r: edit_status(r, "physical_write=20", "physical_write=-1")),
            ("counter_overflow", lambda r: edit_status(r, "physical_write=20", "physical_write=18446744073709551616")),
            ("status_identity_changed", lambda r: edit_status(r, "origin_carrier_compiled=1", "origin_carrier_compiled=0")),
            ("producer_snapshot_error", lambda r: edit_status(r, "version=test", "status_snapshot_error=-12 version=test")),
            ("status_record", lambda r: edit_status(r, "version=test", "version=test\n")),
            ("status_size_or_encoding", lambda r: r["after"].update(dm_info="x" * 65537)),
        ]
        for category, mutate in cases:
            with self.subTest(category=category):
                record = fixture()
                mutate(record)
                with self.assertRaisesRegex(COLLECTOR.InvalidSnapshot, "^" + category + "$"):
                    COLLECTOR.collect(**record)
        print("R093_COLLECTOR_NEGATIVES=" + str(len(cases)))

    def test_cli_duplicate_json_and_valid_snapshot(self):
        valid = subprocess.run([sys.executable, "-B", str(PATH)], input=json.dumps(fixture()),
                               capture_output=True, text=True, timeout=3, check=True)
        self.assertFalse(json.loads(valid.stdout)["live_admission"])
        invalid = subprocess.run([sys.executable, "-B", str(PATH)], input='{"before":1,"before":2}',
                                 capture_output=True, text=True, timeout=3, check=False)
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)["reason"], "duplicate_json_key")
        self.assertFalse(json.loads(invalid.stdout)["live_admission"])


if __name__ == "__main__":
    unittest.main()
