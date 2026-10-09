#!/usr/bin/env python3
"""Adversarial, fully rootless tests for the offline CI metadata inventory."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_ci_evidence_inventory", HERE / "rootless-ci-evidence-inventory.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot import CI evidence inventory")
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)
REVISION = "a" * 40


def good_bundle():
    runs = []
    for index, (name, mandatory) in enumerate(checker.WORKFLOWS.items(), start=1):
        run_id = 1000 + index
        job_id = 2000 + index
        steps = [
            {"number": step_index, "name": step_name,
             "status": "completed", "conclusion": "success"}
            for step_index, step_name in enumerate(mandatory, start=1)
        ]
        runs.append({
            "id": run_id, "name": name, "head_sha": REVISION,
            "run_attempt": 1, "event": "push", "status": "completed",
            "conclusion": "success", "jobs": [{
                "id": job_id, "run_id": run_id, "head_sha": REVISION,
                "run_attempt": 1,
                "name": "one-revision" if index == 1 else "source-only",
                "status": "completed", "conclusion": "success", "steps": steps,
            }],
        })
    return {"schema": checker.SCHEMA, "repository": "k1moradi/swapz",
            "source_revision": REVISION, "runs": runs}


class CIInventoryTests(unittest.TestCase):
    def setUp(self):
        self.bundle = good_bundle()
        self.directory = tempfile.TemporaryDirectory(prefix="swapz-ci-evidence-")
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "input.json"

    def rejected(self, reason):
        with self.assertRaisesRegex(checker.EvidenceDenied, reason):
            checker.inventory(self.bundle)

    def test_positive_exact_source_and_mandatory_steps(self):
        report = checker.inventory(self.bundle)
        self.assertTrue(report["workflow_metadata_consistent"])
        self.assertEqual(len(report["workflows"]), 3)
        self.assertEqual(report["source_revision"], REVISION)
        self.assertEqual(report["v22_strategy_and_batch_winner"], "UNDETERMINED")
        self.assertFalse(report["source_authenticated"])
        self.assertFalse(report["step_execution_independently_attested"])
        self.assertFalse(report["repeat_counts_independently_attested"])
        self.assertEqual(set(report["qualification"]), set(checker.UNQUALIFIED_CLAIMS))
        self.assertFalse(any(report["qualification"].values()))

    def test_deterministic_regardless_of_run_order(self):
        expected = checker.inventory(self.bundle)
        self.bundle["runs"].reverse()
        self.assertEqual(expected, checker.inventory(self.bundle))

    def test_reject_missing_workflow(self):
        self.bundle["runs"].pop()
        self.rejected("exactly three")

    def test_reject_duplicate_workflow_name(self):
        self.bundle["runs"][1]["name"] = self.bundle["runs"][0]["name"]
        self.rejected("duplicate workflow")

    def test_reject_duplicate_workflow_run_id(self):
        self.bundle["runs"][1]["id"] = self.bundle["runs"][0]["id"]
        self.rejected("duplicate workflow run")

    def test_reject_duplicate_job_id(self):
        self.bundle["runs"][1]["jobs"][0]["id"] = self.bundle["runs"][0]["jobs"][0]["id"]
        self.rejected("duplicate job")

    def test_reject_stale_workflow_source_revision(self):
        self.bundle["runs"][0]["head_sha"] = "b" * 40
        self.rejected("source revision mismatch")

    def test_reject_stale_job_source_revision(self):
        self.bundle["runs"][0]["jobs"][0]["head_sha"] = "b" * 40
        self.rejected("job and workflow")

    def test_reject_mixed_attempts(self):
        self.bundle["runs"][0]["jobs"][0]["run_attempt"] = 2
        self.rejected("identity/attempt")

    def test_reject_skipped_mandatory_broker_test(self):
        steps = self.bundle["runs"][0]["jobs"][0]["steps"]
        step = next(value for value in steps if "broker and evidence producer" in value["name"])
        step["conclusion"] = "skipped"
        self.rejected("mandatory safety step")

    def test_reject_failed_independent_broker_test(self):
        steps = self.bundle["runs"][1]["jobs"][0]["steps"]
        step = next(value for value in steps if "Independent rootless" in value["name"])
        step["conclusion"] = "failure"
        self.rejected("failed or canceled")

    def test_reject_missing_workflow_contract_step(self):
        steps = self.bundle["runs"][1]["jobs"][0]["steps"]
        steps[:] = [row for row in steps if not row["name"].startswith("Guard rootless")]
        for index, row in enumerate(steps, start=1):
            row["number"] = index
        self.rejected("mandatory safety step")

    def test_reject_missing_nbd_stress_step(self):
        steps = self.bundle["runs"][2]["jobs"][0]["steps"]
        steps[:] = [row for row in steps if "25 times" not in row["name"]]
        for index, row in enumerate(steps, start=1):
            row["number"] = index
        self.rejected("mandatory safety step")

    def test_reject_false_success_text_in_unknown_step(self):
        steps = self.bundle["runs"][1]["jobs"][0]["steps"]
        target = next(row for row in steps if "Independent rootless" in row["name"])
        target["name"] = "echo 'Independent rootless five-role broker and ambiguous-child contracts: PASS'"
        self.rejected("mandatory safety step")

    def test_reject_job_run_id_mismatch(self):
        self.bundle["runs"][0]["jobs"][0]["run_id"] = 12
        self.rejected("identity/attempt")

    def test_reject_boolean_job_attempt(self):
        self.bundle["runs"][0]["jobs"][0]["run_attempt"] = True
        self.rejected("positive signed")

    def test_reject_boolean_job_run_id(self):
        self.bundle["runs"][0]["jobs"][0]["run_id"] = True
        self.rejected("positive signed")

    def test_reject_workflow_incomplete(self):
        self.bundle["runs"][0]["status"] = "in_progress"
        self.rejected("did not complete")

    def test_reject_failed_job(self):
        self.bundle["runs"][1]["jobs"][0]["conclusion"] = "failure"
        self.rejected("unsuccessful qualification job")

    def test_reject_partial_step_status(self):
        self.bundle["runs"][0]["jobs"][0]["steps"][0]["status"] = "in_progress"
        self.rejected("uncompleted job step")

    def test_reject_duplicate_step_name(self):
        rows = self.bundle["runs"][0]["jobs"][0]["steps"]
        rows[1]["name"] = rows[0]["name"]
        self.rejected("duplicate or malformed")

    def test_reject_missing_step_number(self):
        self.bundle["runs"][0]["jobs"][0]["steps"][0]["number"] = 3
        self.rejected("out of sequence")

    def test_reject_boolean_identity_instead_of_integer(self):
        self.bundle["runs"][0]["id"] = True
        self.rejected("positive signed")

    def test_reject_extra_claimed_qualification_flag(self):
        self.bundle["production_qualified"] = True
        self.rejected("exact fields")

    def test_reject_mixed_workflow_events(self):
        self.bundle["runs"][2]["event"] = "workflow_dispatch"
        self.rejected("mixed workflow events")

    def test_reject_noncanonical_sha(self):
        self.bundle["source_revision"] = "A" * 40
        self.rejected("lowercase hex")

    def _write(self, body):
        self.path.write_bytes(body)
        self.path.chmod(0o600)

    def test_read_valid_regular_json_file(self):
        self._write(json.dumps(self.bundle).encode())
        self.assertEqual(checker.inventory(checker.read_bundle(self.path))["source_revision"], REVISION)

    def test_read_reject_duplicate_json_keys(self):
        self._write(b'{"schema":1,"schema":2}')
        with self.assertRaisesRegex(checker.EvidenceDenied, "duplicate JSON key"):
            checker.read_bundle(self.path)

    def test_read_reject_invalid_json_and_nonfinite(self):
        for data in (b"not-json", b'{"value":NaN}', b"\xff"):
            with self.subTest(data=data):
                self._write(data)
                with self.assertRaises(checker.EvidenceDenied):
                    checker.read_bundle(self.path)

    def test_read_reject_size_bound(self):
        with self.path.open("wb") as stream:
            stream.truncate(checker.MAX_INPUT_BYTES + 1)
        with self.assertRaisesRegex(checker.EvidenceDenied, "bounded"):
            checker.read_bundle(self.path)

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires O_NOFOLLOW")
    def test_read_reject_symlink(self):
        actual = Path(self.directory.name) / "real.json"
        actual.write_text("{}", encoding="utf-8")
        self.path.symlink_to(actual)
        with self.assertRaises(OSError):
            checker.read_bundle(self.path)

    def test_cli_reports_success_but_never_authenticates(self):
        self._write(json.dumps(self.bundle).encode())
        result = subprocess.run(
            [sys.executable, "-B", str(HERE / "rootless-ci-evidence-inventory.py"),
             "--bundle", str(self.path)],
            check=False, capture_output=True, text=True, timeout=4,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["source_authenticated"])
        self.assertFalse(report["qualification"]["kernel_drain_proved"])

    def test_cli_failure_is_fail_only_on_stderr(self):
        self._write(b'{"schema":"bogus"}')
        result = subprocess.run(
            [sys.executable, "-B", str(HERE / "rootless-ci-evidence-inventory.py"),
             "--bundle", str(self.path)],
            check=False, capture_output=True, text=True, timeout=4,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertIn("CI_EVIDENCE_INVENTORY_DENIED:", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
