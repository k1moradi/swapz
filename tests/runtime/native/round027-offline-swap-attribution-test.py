#!/usr/bin/env python3
"""Round027 original-source-executed OFFLINE attribution negative tests only."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tests/tools/round027-offline-swap-attribution.py"
spec = importlib.util.spec_from_file_location("round027_offline", TOOL)
assert spec and spec.loader
import types
MODULE = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = MODULE
spec.loader.exec_module(MODULE)

SOURCE_SHA = "ce68d2ada7a9e5eb41d64fd30a20ab1ef036a11c"
MEGABYTE = 1024 * 1024
MIN_BYTES = 128 * MEGABYTE
PHYSICAL_BYTES = 64 * MEGABYTE
ORIGINAL_PAGES = 384 * MEGABYTE // 4096


def observation(phase: str, time_us: int) -> dict:
    return {
        "phase": phase,
        "monotonic_us": time_us,
        "source_sha": SOURCE_SHA,
        "boot_key": "boot-redacted-A",
        "mapper_key": "mapper-redacted-A",
        "lower_key": "partition-redacted-A",
        "cgroup_key": "cgroup-redacted-A",
        "cgroup": {"swap_current": 0, "swap_peak": 0,
                   "swap_max": 384 * MEGABYTE, "oom": 0, "oom_kill": 0},
        "mapper": {"active": True, "used_kib": 0},
        "target": {"logical_write": 0, "physical_write": 0,
                   "logical_read": 0, "physical_read": 0,
                   "failed": 0, "error": 0},
        "lower": {"read_sectors": 0, "write_sectors": 0},
        "vm": {"pswpin": 0, "pswpout": 0},
    }


def sample() -> dict:
    baseline = observation("baseline", 1_000_000)
    fill = observation("after_fill", 2_000_000)
    fill["cgroup"]["swap_current"] = MIN_BYTES
    fill["cgroup"]["swap_peak"] = MIN_BYTES
    fill["mapper"]["used_kib"] = MIN_BYTES // 1024
    fill["target"]["logical_write"] = MIN_BYTES
    fill["target"]["physical_write"] = PHYSICAL_BYTES
    fill["lower"]["write_sectors"] = PHYSICAL_BYTES // 512
    fill["vm"]["pswpout"] = 256
    before = copy.deepcopy(fill)
    before["phase"] = "before_verify"
    before["monotonic_us"] = 3_000_000
    verified = copy.deepcopy(before)
    verified["phase"] = "after_verify"
    verified["monotonic_us"] = 4_000_000
    verified["target"]["logical_read"] = MIN_BYTES
    verified["target"]["physical_read"] = PHYSICAL_BYTES
    verified["lower"]["read_sectors"] = PHYSICAL_BYTES // 512
    verified["vm"]["pswpin"] = 256
    return {
        "schema": MODULE.SCHEMA,
        "evidence_class": "SYNTHETIC_TEST_ONLY",
        "source_sha": SOURCE_SHA,
        "boot_key": "boot-redacted-A",
        "mapper_key": "mapper-redacted-A",
        "lower_key": "partition-redacted-A",
        "cgroup_key": "cgroup-redacted-A",
        "min_swap_bytes": MIN_BYTES,
        "expected_verified_pages": ORIGINAL_PAGES,
        "ownership": {"source_loaded_matches": True, "boot_matches": True,
                      "mapper_matches": True, "lower_matches": True,
                      "cgroup_unique": True, "worker_identity": True,
                      "cleanup_completed": True, "oracle_exit_zero": True},
        "snapshots": [baseline, fill, before, verified],
        "attribution_rechecks": [], "recheck_complete": True,
        "oracle": {"verified_pages": ORIGINAL_PAGES,
                   "verified_bytes": ORIGINAL_PAGES * 4096,
                   "mismatches": 0, "digest": "a" * 64,
                   "expected_digest": "a" * 64,
                   "full_page_bytes": 4096},
    }


class Round027OfflinePhysicalEvidence(unittest.TestCase):
    def classify(self, values: dict) -> MODULE.Verdict:
        return MODULE.analyze(values, SOURCE_SHA)

    def test_exact_original_evaluator_code_is_executed_in_memory(self) -> None:
        evaluator = MODULE.load_original_evaluator()
        self.assertEqual(evaluator.__code__.co_filename,
                         "qualify-primary-real-swap.py")
        self.assertIn("SECTOR_BYTES", evaluator.__code__.co_names)
        self.assertIn("PAGE_BYTES", evaluator.__code__.co_names)
        self.assertIn("QualificationFailure", evaluator.__code__.co_names)
        self.assertEqual(self.classify(sample()).classification, MODULE.SYNTHETIC)

    def test_historical_absent_numbers_are_unproven_not_physical_pass(self) -> None:
        result = self.classify({})
        self.assertEqual(result.classification, MODULE.UNKNOWN)
        self.assertEqual(result.first_error, "historical_counters_missing")
        partial = {"schema": MODULE.SCHEMA, "source_sha": SOURCE_SHA}
        self.assertEqual(self.classify(partial).classification, MODULE.UNKNOWN)
        owner = sample()
        owner["evidence_class"] = "OWNER_REDACTED_OFFLINE"
        self.assertEqual(self.classify(owner).classification, MODULE.UNKNOWN)
        self.assertNotEqual(self.classify(owner).classification, MODULE.SYNTHETIC)

    def test_true_original_evaluator_first_failure_order(self) -> None:
        scenarios = (
            ("cgroup_swap_below_floor",
             lambda x: x["snapshots"][1]["cgroup"].update(
                 swap_current=MIN_BYTES-1024, swap_peak=MIN_BYTES-1024)),
            ("cgroup_oom",
             lambda x: x["snapshots"][3]["cgroup"].update(oom=1)),
            ("mapper_swap_below_floor",
             lambda x: x.update(min_swap_bytes=MIN_BYTES)),  # overridden below
            ("target_write_below_floor",
             lambda x: x["snapshots"][1]["target"].update(logical_write=0)),
            ("lower_write_absent",
             lambda x: x["snapshots"][1]["lower"].update(write_sectors=0)),
            ("lower_write_insufficient",
             lambda x: x["snapshots"][1]["lower"].update(write_sectors=1)),
            ("vmstat_swapout_absent",
             lambda x: x["snapshots"][1]["vm"].update(pswpout=0)),
            ("target_read_below_floor",
             lambda x: x["snapshots"][3]["target"].update(logical_read=0)),
            ("lower_read_absent",
             lambda x: x["snapshots"][3]["lower"].update(read_sectors=0)),
            ("lower_read_insufficient",
             lambda x: x["snapshots"][3]["lower"].update(read_sectors=1)),
            ("vmstat_swapin_absent",
             lambda x: x["snapshots"][3]["vm"].update(pswpin=0)),
            ("original_page_oracle_mismatch",
             lambda x: x["oracle"].update(mismatches=1)),
            ("target_failed",
             lambda x: x["snapshots"][3]["target"].update(failed=1)),
        )
        for expected, modify in scenarios:
            if expected in ("cgroup_swap_below_floor",
                            "mapper_swap_below_floor"):
                # Exact mapper equality is independently checked first.
                # The 128 MiB real floor cannot be altered in the fixture.
                continue
            with self.subTest(expected=expected):
                data = sample()
                modify(data)
                result = self.classify(data)
                self.assertEqual(result.classification, MODULE.FAIL)
                self.assertEqual(result.first_error, expected)

    def test_source_first_cgroup_floor_requires_real_128_mib(self) -> None:
        record = sample()
        record["min_swap_bytes"] = 1
        with self.assertRaisesRegex(MODULE.InvalidEvidence, "source_swap_floor"):
            self.classify(record)
        record = sample()
        record["snapshots"][1]["cgroup"]["swap_current"] = MIN_BYTES - 1024
        record["snapshots"][1]["cgroup"]["swap_peak"] = MIN_BYTES - 1024
        record["snapshots"][1]["mapper"]["used_kib"] -= 1
        self.assertEqual(self.classify(record).first_error,
                         "cgroup_swap_below_floor")

    def test_exact_non_atomic_recheck_requires_two_identical_samples(self) -> None:
        data = sample()
        data["snapshots"][1]["mapper"]["used_kib"] -= 1
        data["recheck_complete"] = False
        self.assertEqual(self.classify(data).classification, MODULE.UNKNOWN)
        data["recheck_complete"] = True
        self.assertEqual(self.classify(data).classification, MODULE.UNKNOWN)
        first = copy.deepcopy(data["snapshots"][1])
        first["phase"] = "attribution_recheck"
        first["monotonic_us"] = 2_050_000
        first["mapper"]["used_kib"] += 1
        data["attribution_rechecks"] = [first]
        self.assertEqual(self.classify(data).first_error,
                         "swap_attribution_unconfirmed_matching_pair")
        second = copy.deepcopy(first)
        second["monotonic_us"] = 2_100_000
        data["attribution_rechecks"].append(second)
        self.assertEqual(self.classify(data).classification, MODULE.SYNTHETIC)
        data["attribution_rechecks"][1]["monotonic_us"] = 6_000_000
        with self.assertRaisesRegex(MODULE.InvalidEvidence, "recheck_deadline"):
            self.classify(data)

    def test_stale_counter_identity_overflow_privacy_and_unsafe_claims(self) -> None:
        negatives = (
            ("snapshot_identity_mismatch",
             lambda x: x["snapshots"][2].update(boot_key="other-boot")),
            ("snapshot_identity_mismatch",
             lambda x: x["snapshots"][1].update(mapper_key="foreign-mapper")),
            ("snapshot_identity_mismatch",
             lambda x: x["snapshots"][3].update(lower_key="other-partition")),
            ("snapshot_time_order",
             lambda x: x["snapshots"][2].update(monotonic_us=1)),
            ("counter_regression",
             lambda x: x["snapshots"][3]["vm"].update(pswpout=0)),
            ("invalid_counter",
             lambda x: x["snapshots"][1]["lower"].update(write_sectors=-1)),
            ("invalid_counter",
             lambda x: x["snapshots"][1]["target"].update(logical_write=True)),
            ("invalid_counter",
             lambda x: x["snapshots"][1]["mapper"].update(used_kib=1 << 65)),
            ("oracle_digest",
             lambda x: x["oracle"].update(digest="invalid")),
            ("original_page_size",
             lambda x: x["oracle"].update(full_page_bytes=2048)),
            ("unredacted_or_invalid_identity",
             lambda x: x.update(lower_key="/dev/sda4")),
            ("unexpected_evidence_field",
             lambda x: x.update(physical_uuid="secret-value")),
            ("owner_or_cleanup_not_proven",
             lambda x: x["ownership"].update(cleanup_completed=False)),
            ("source_sha_mismatch",
             lambda x: x.update(source_sha="b"*40)),
            ("cgroup_peak_limit",
             lambda x: x["snapshots"][1]["cgroup"].update(swap_peak=0)),
            ("snapshot_order",
             lambda x: x["snapshots"].reverse()),
        )
        for category, modify in negatives:
            with self.subTest(category=category):
                data = sample()
                modify(data)
                with self.assertRaisesRegex(MODULE.InvalidEvidence, category):
                    self.classify(data)

    def test_strict_file_reader_and_cli_never_open_devices(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.json"
            source.write_text(json.dumps(sample()), encoding="utf-8")
            self.assertEqual(MODULE.analyze(MODULE.read_json(root, source.name),
                                             SOURCE_SHA).classification,
                             MODULE.SYNTHETIC)
            command = [sys.executable, "-B", str(TOOL),
                       "--evidence-root", str(root),
                       "--file", source.name,
                       "--expected-source-sha", SOURCE_SHA]
            result = subprocess.run(command, capture_output=True,
                                    text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(MODULE.SYNTHETIC, result.stdout)
            self.assertIn("PHYSICAL=NOT_RUN", result.stdout)
            source.write_text("{}", encoding="utf-8")
            result = subprocess.run(command, capture_output=True,
                                    text=True, timeout=15, check=False)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn(MODULE.UNKNOWN, result.stdout)
            for data in ('{"schema": 1, "schema": 2}',
                         '{"oracle": NaN}',
                         "{malformed",
                         " " * (MODULE.MAX_BYTES + 1)):
                source.write_text(data, encoding="utf-8")
                with self.assertRaises(MODULE.InvalidEvidence):
                    MODULE.read_json(root, source.name)
            source.unlink()
            source.symlink_to(root / "target.json")
            with self.assertRaisesRegex(MODULE.InvalidEvidence,
                                        "input_unavailable_or_unsafe"):
                MODULE.read_json(root, source.name)
            with self.assertRaisesRegex(MODULE.InvalidEvidence, "input_filename"):
                MODULE.read_json(root, "../etc/passwd")
            with self.assertRaisesRegex(MODULE.InvalidEvidence, "input_filename"):
                MODULE.read_json(root, "/proc/swaps")
            with self.assertRaisesRegex(MODULE.InvalidEvidence,
                                        "input_unavailable_or_unsafe"):
                MODULE.read_json(root, "missing.json")
            self.assertFalse((root / "target.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
