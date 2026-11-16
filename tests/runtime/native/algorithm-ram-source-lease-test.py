#!/usr/bin/env python3
"""Rootless source-bound RAM lease and zero-physical-selector regression.

The imported module is the tracked production qualification driver; every
Git call, artifact read, remote observation and physical selector is mocked.
"""

from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
DRIVER = ROOT / "tests/tools/run-tests.py"
TESTED = "a" * 40
ADVANCED = "b" * 40
ARCHIVE = "c" * 40
RESTORED = "d" * 40
ARCHIVE_PARENT = "e" * 40
DIGEST = "f" * 64


def load_driver():
    spec = importlib.util.spec_from_file_location(
        "round013_real_make_test_driver", DRIVER)
    if spec is None or spec.loader is None:
        raise AssertionError("tracked make test driver unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


runner = load_driver()


def completed(command, *, output=b"", exit_code=0):
    return subprocess.CompletedProcess(command, exit_code, output, b"")


def ram_result():
    artifacts = {
        "status": "AVAILABLE",
        "formatter_sha256": DIGEST,
        "module_sha256": DIGEST,
        "oracle_sha256": DIGEST,
    }
    return {
        "source_sha": TESTED,
        "tested_commit_sha": TESTED,
        "stages": [{"name": name, "status": "PASS", "exit_code": 0}
                   for name in runner.OFFICIAL_STAGE_NAMES],
        "qualified_artifacts": artifacts,
        "overall": "INCOMPLETE",
        "physical_qualification": {"overall": "NOT_RUN"},
    }


class SourceLeaseTests(unittest.TestCase):
    def setUp(self):
        self.head = TESTED
        self.tracking = TESTED
        self.source = TESTED
        self.remote = TESTED
        self.dirty = None
        self.branch = b"main\n"
        self.race = False
        self.remote_error = False
        self.selector = mock.Mock(return_value=completed(
            ["mocked-selector"], exit_code=2))
        self.patches = []

        def git_command(*args, **_kwargs):
            if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
                return completed(args, output=self.branch)
            if args == ("ls-remote", "--exit-code", "origin",
                        "refs/heads/main"):
                if self.remote_error:
                    return completed(args, exit_code=128)
                return completed(args, output=(
                    self.remote + "\trefs/heads/main\n").encode("ascii"))
            raise AssertionError("unexpected Git call: " + repr(args))

        def git_head(_run, reference):
            if reference == "HEAD":
                if self.race:
                    self.race = False
                    return ADVANCED
                return self.head
            if reference == "refs/remotes/origin/main":
                return self.tracking
            raise AssertionError("unexpected Git ref: " + reference)

        self.patch(runner, "_sync_git_runner", return_value=git_command)
        self.patch(runner, "_git_head", side_effect=git_head)
        self.patch(runner, "_remote_origin_url",
                   return_value="https://github.com/k1moradi/swapz.git")
        self.patch(runner, "git_sha", side_effect=lambda: self.source)
        self.patch(runner, "tracked_source_checkout_preflight",
                   side_effect=lambda: self.dirty)
        self.patch(runner.subprocess, "run", self.selector)

    def patch(self, obj, name, *args, **kwargs):
        patcher = mock.patch.object(obj, name, *args, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)

    def launch(self):
        return runner.run_algorithm_physical_selector_if_leased(
            TESTED, {"SWAPZ_ALGORITHM_RAM_NONCE": "not-a-real-nonce"},
            io.StringIO())

    def test_clean_stable_source_reaches_only_mocked_selector(self):
        completed_trial, refusal, attempted = self.launch()
        self.assertIsNone(refusal)
        self.assertTrue(attempted)
        self.assertEqual(completed_trial.returncode, 2)
        self.selector.assert_called_once()
        self.assertIn("algorithm-physical.py",
                      self.selector.call_args.args[0][-1])

    def test_five_pass_ram_stages_do_not_override_advanced_source(self):
        self.assertEqual(len(ram_result()["stages"]), 5)
        self.source = ADVANCED
        self.assertEqual(self.launch()[1], "source_advanced_after_ram")
        self.selector.assert_not_called()

    def test_local_main_advanced_without_source_stamp_change(self):
        self.head = ADVANCED
        self.assertEqual(self.launch()[1], "main_not_aligned")
        self.selector.assert_not_called()

    def test_remote_main_advanced_after_last_fetch(self):
        self.remote = ADVANCED
        self.assertEqual(self.launch()[1], "canonical_source_advanced")
        self.selector.assert_not_called()

    def test_dirty_tracked_checkout_refused(self):
        self.dirty = {"reason": "uncommitted_tracked_source",
                      "changed_paths": ["src/kernel/dm-target.c"]}
        self.assertEqual(self.launch()[1], "tracked_source_dirty")
        self.selector.assert_not_called()

    def test_checkout_not_main_or_missing_source(self):
        self.branch = b"detached\n"
        self.assertEqual(self.launch()[1], "checkout_not_on_main")
        self.branch = b"main\n"
        self.source = "unknown"
        self.assertEqual(self.launch()[1], "source_advanced_after_ram")
        self.selector.assert_not_called()

    def test_source_race_during_second_identity_read(self):
        original = runner._git_head
        count = 0

        def raced(run, reference):
            nonlocal count
            if reference == "HEAD":
                count += 1
                if count == 2:
                    return ADVANCED
            return original(run, reference)

        self.patch(runner, "_git_head", side_effect=raced)
        self.assertEqual(self.launch()[1], "source_raced_after_ram")
        self.selector.assert_not_called()

    def test_remote_ref_unavailable_and_invalid_sha(self):
        self.remote_error = True
        self.assertEqual(self.launch()[1], "canonical_source_unavailable")
        self.remote_error = False
        self.assertEqual(
            runner.algorithm_ram_source_lease_refusal("invalid"),
            "invalid_tested_source")
        self.selector.assert_not_called()

    def test_selector_execution_error_is_not_misreported_as_no_invocation(self):
        self.selector.side_effect = OSError("synthetic failed spawn")
        trial, reason, attempted = self.launch()
        self.assertIsNone(trial)
        self.assertEqual(reason, "physical_selector_execution_unavailable")
        self.assertTrue(attempted)
        self.selector.assert_called_once()


class EvidencePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.result = ram_result()
        self.patches = []
        self.patch(runner, "ROOT", self.root)
        self.patch(runner, "git_result", return_value=completed(
            ["git", "rev-parse", "HEAD"], output=(TESTED+"\n").encode()))
        self.patch(runner, "git_sha", return_value=TESTED)
        # Freeze the observed final digest snapshot independently of the
        # mutable report under test; a later report edit must not move it.
        self.patch(runner, "qualification_artifact_digests",
                   return_value=dict(self.result["qualified_artifacts"]))
        self.patch(runner, "algorithm_ram_source_lease_refusal",
                   return_value=None)

    def patch(self, obj, name, *args, **kwargs):
        patcher = mock.patch.object(obj, name, *args, **kwargs)
        patcher.start()
        self.addCleanup(patcher.stop)
        return patcher

    def test_private_create_only_evidence_and_noncandidate_metadata(self):
        evidence, nonce = runner.write_algorithm_ram_development_evidence(
            self.result)
        self.assertEqual(len(nonce), 32)
        self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)
        record = json.loads(evidence.read_text())
        self.assertEqual(record["schema"],
                         "swapz-algorithm-ram-development-evidence-v1")
        self.assertEqual(record["source_sha"], TESTED)
        self.assertEqual(len(record["stages"]), 5)
        self.assertEqual(record["artifact_sha256"]["module_sha256"], DIGEST)
        self.assertEqual(record["nonce"], nonce)
        self.assertEqual(record["head"], TESTED)
        self.assertEqual([p for p in evidence.parent.iterdir()
                          if p.name.startswith(".algorithm-ram-evidence.")],
                         [])
        evidence.unlink()

    def test_missing_or_malformed_artifact_refused_without_file(self):
        for artifact in ({"status": "UNAVAILABLE"},
                         {**self.result["qualified_artifacts"],
                          "module_sha256": "not-a-hash"}):
            with self.subTest(artifact=artifact):
                self.result["qualified_artifacts"] = artifact
                with self.assertRaises(ValueError):
                    runner.write_algorithm_ram_development_evidence(
                        self.result)
                self.assertFalse(
                    (self.root / "build/tests/algorithm-ram-evidence.json").exists())

    def test_digest_drift_after_ram_stage_refused(self):
        self.result["qualified_artifacts"]["module_sha256"] = "1" * 64
        with self.assertRaisesRegex(ValueError, "artifact digests changed"):
            runner.write_algorithm_ram_development_evidence(self.result)
        self.assertFalse(
            (self.root / "build/tests/algorithm-ram-evidence.json").exists())

    def test_invalid_nonce_refused_without_evidence(self):
        self.patch(runner.os, "urandom", return_value=b"")
        with self.assertRaisesRegex(ValueError, "nonce unavailable"):
            runner.write_algorithm_ram_development_evidence(self.result)
        self.assertFalse(
            (self.root / "build/tests/algorithm-ram-evidence.json").exists())

    def test_source_changed_while_evidence_prepared(self):
        self.patch(runner, "algorithm_ram_source_lease_refusal",
                   return_value="source_advanced_after_ram")
        with self.assertRaisesRegex(ValueError, "source lease refused"):
            runner.write_algorithm_ram_development_evidence(self.result)
        self.assertFalse(
            (self.root / "build/tests/algorithm-ram-evidence.json").exists())

    def test_source_races_between_evidence_publication_and_selector(self):
        self.patch(runner, "algorithm_ram_source_lease_refusal",
                   side_effect=(None, "canonical_source_advanced"))
        evidence, _ = runner.write_algorithm_ram_development_evidence(
            self.result)
        selector = mock.Mock()
        try:
            with mock.patch.object(runner.subprocess, "run", selector):
                trial, refusal, attempted = (
                    runner.run_algorithm_physical_selector_if_leased(
                        TESTED, {"SWAPZ_ALGORITHM_RAM_NONCE": "synthetic"},
                        io.StringIO()))
            self.assertIsNone(trial)
            self.assertEqual(refusal, "canonical_source_advanced")
            self.assertFalse(attempted)
            selector.assert_not_called()
        finally:
            evidence.unlink()

    def test_boolean_exit_code_is_not_an_integer_zero_stage(self):
        self.result["stages"][0]["exit_code"] = False
        with self.assertRaisesRegex(ValueError, "five exact PASS stages"):
            runner.write_algorithm_ram_development_evidence(self.result)

    def test_atomic_replace_exception_never_leaks_temporary(self):
        original_report = self.root / "build/tests/algorithm-ram-evidence.json"
        original_report.parent.mkdir(parents=True)
        original_report.write_text("prior complete record\n")
        self.patch(runner.os, "replace",
                   side_effect=OSError("synthetic publication failed"))
        with self.assertRaises(OSError):
            runner.write_algorithm_ram_development_evidence(self.result)
        self.assertEqual(original_report.read_text(), "prior complete record\n")
        self.assertEqual([p for p in original_report.parent.iterdir()
                          if p.name.startswith(".algorithm-ram-evidence.")],
                         [])

    def test_source_git_unavailable_never_creates_evidence(self):
        self.patch(runner, "git_result", return_value=None)
        with self.assertRaisesRegex(ValueError, "cannot identify current HEAD"):
            runner.write_algorithm_ram_development_evidence(self.result)
        self.assertFalse(
            (self.root / "build/tests/algorithm-ram-evidence.json").exists())


class ReportArchiveTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.restored_tree = ARCHIVE_PARENT
        self.archived_blob = ADVANCED
        self.archive_parents = (ARCHIVE + " " + ARCHIVE_PARENT).encode() + b"\n"
        self.restore_parents = (RESTORED + " " + ARCHIVE).encode() + b"\n"
        self.notice = (
            "ARCHIVED_GIT: https://github.com/k1moradi/swapz/blob/" +
            ARCHIVE + "/test_results.json (report_commit=" + ARCHIVE +
            "; main_commit=" + RESTORED + "; tested=" + TESTED +
            "; canonical test_results.json unchanged)")
        subject = ("test: latest run for " + TESTED[:12] +
                   " [skip ci]").encode()

        def git_head(_run, ref):
            records = {
                "HEAD": RESTORED,
                "refs/remotes/origin/main": RESTORED,
                ARCHIVE + "^": ARCHIVE_PARENT,
                RESTORED + "^": ARCHIVE,
                ARCHIVE + ":test_results.json": self.archived_blob,
                RESTORED + "^{tree}": self.restored_tree,
                ARCHIVE_PARENT + "^{tree}": ARCHIVE_PARENT,
            }
            return records.get(ref)

        def run(*args):
            self.calls.append(args)
            if args[:3] == ("rev-list", "--parents", "-n"):
                return completed(args, output=(
                    self.archive_parents if args[-1] == ARCHIVE else
                    self.restore_parents))
            if args[:2] == ("diff-tree", "--no-commit-id"):
                return completed(args, output=b"test_results.json\n")
            if args[:3] == ("show", "-s", "--format=%B"):
                content = subject if args[-1] == ARCHIVE else (
                    subject + b"\n\nswapz-canonical-restore: true")
                return completed(args, output=content+b"\n")
            raise AssertionError("unexpected archive command")

        for name, patched in (
                ("_sync_git_runner", mock.Mock(return_value=run)),
                ("_git_head", mock.Mock(side_effect=git_head)),
                ("_is_git_ancestor", mock.Mock(return_value=True)),
                ("tracked_source_checkout_preflight", mock.Mock(
                    return_value=None))):
            patcher = mock.patch.object(runner, name, patched)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_exact_report_only_archive_and_restoration_are_reviewable(self):
        self.assertIsNone(runner.archived_pretrial_checkpoint_refusal(
            self.notice, TESTED, ADVANCED))
        self.assertGreaterEqual(len(self.calls), 5)

    def test_wrong_restoration_tree_blocks_physical_checkpoint(self):
        self.restored_tree = "9" * 40
        self.assertEqual(runner.archived_pretrial_checkpoint_refusal(
            self.notice, TESTED, ADVANCED),
            "archive_blob_or_restoration_mismatch")

    def test_malformed_receipt_and_wrong_blob_rejected(self):
        self.assertEqual(runner.archived_pretrial_checkpoint_refusal(
            "untrusted archive", TESTED, ADVANCED),
            "invalid_archive_receipt")
        self.assertEqual(runner.archived_pretrial_checkpoint_refusal(
            self.notice, TESTED, DIGEST[:40]),
            "archive_blob_or_restoration_mismatch")


if __name__ == "__main__":
    unittest.main(verbosity=2)
