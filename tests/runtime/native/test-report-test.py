#!/usr/bin/env python3
"""Rootless contract tests for the sole make test plain JSON reporting pipeline."""
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import time
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("swapz_private_test_runner",
                                               ROOT / "tests/tools/run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@contextlib.contextmanager
def mocked_main_sync(source_sha):
    patcher = mock.patch.multiple(
        runner,
        acquire_make_test_lock=mock.DEFAULT,
        sync_main_before_test=mock.DEFAULT,
        sync_main_after_test=mock.DEFAULT,
        source_checkout_stability=mock.DEFAULT)
    replacements = patcher.start()
    replacements["acquire_make_test_lock"].return_value = (None, None, None)
    replacements["sync_main_before_test"].return_value = {
        "status": "PASS", "reason": "fixture",
        "source_sha": source_sha, "head_sha": source_sha}
    replacements["sync_main_after_test"].return_value = {
        "status": "PASS", "reason": "fixture"}
    replacements["source_checkout_stability"].return_value = {
        "stable": True, "reason": "fixture"}
    try:
        yield
    finally:
        patcher.stop()


policy_spec = importlib.util.spec_from_file_location(
    "swapz_rootless_resource_policy",
    ROOT / "tests/tools/rootless-resource-policy.py")
resource_policy = importlib.util.module_from_spec(policy_spec)
policy_spec.loader.exec_module(resource_policy)


class RootlessResourceInventoryContract(unittest.TestCase):
    """Fail closed before any worker scheduler is introduced."""

    def test_all_full_tier_phases_are_classified_exactly_once(self):
        source = (ROOT / "tests/tools/test-rootless.sh").read_text(
            encoding="utf-8")
        claims = resource_policy.audit_harness(source)
        syntax_labels = {
            "bash syntax " + Path(path).name
            for path in resource_policy.SYNTAX_SCRIPTS
        }
        self.assertEqual(len(claims), 57)
        self.assertEqual(len(claims) - len(resource_policy.FULL_ONLY_PHASES), 54)
        self.assertTrue(all(
            claims[phase].classification == "serial"
            for phase in resource_policy.FULL_ONLY_PHASES))
        self.assertEqual(
            set(claims), set(runner.ROOTLESS_SUITE_DISPLAY_NAMES) | syntax_labels)
        self.assertEqual(
            set(runner.ROOTLESS_SUITE_DISPLAY_NAMES),
            runner.rootless_phase_names())
        self.assertTrue(resource_policy.ROOTLESS_PARALLEL_EXECUTION_ENABLED)

    def test_unreviewed_or_changed_phase_fails_closed(self):
        source = (ROOT / "tests/tools/test-rootless.sh").read_text(
            encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "inventory/harness drift"):
            resource_policy.audit_harness(
                source + "\nrootless_phase='unreviewed fixture'\n")
        with self.assertRaisesRegex(ValueError, "duplicate literal"):
            resource_policy.audit_harness(
                source + "\nrootless_phase='rootless initialization'\n")
        # Change a token inside the genuine loop without breaking its grammar;
        # reject the new script by source identity rather than shell formatting.
        original = "for script in tests/tools/test-rootless.sh"
        self.assertIn(original, source)
        with self.assertRaisesRegex(ValueError, "unreviewed rootless syntax"):
            resource_policy.audit_harness(source.replace(
                original, "for script in tests/tools/unknown-check.sh", 1))

    def test_duplicate_resource_classifications_fail_closed(self):
        from unittest import mock

        original = "tests/Makefile native and metadata"
        with mock.patch.dict(
                resource_policy.READ_ONLY_PHASES,
                {original: "incorrectly declared read-only"}):
            with self.assertRaisesRegex(ValueError, "duplicate or unreviewed"):
                resource_policy.resource_claims()

    def test_serial_build_and_process_hazards_block_overlap(self):
        claims = resource_policy.resource_claims()
        build = "tests/Makefile native and metadata"
        source = "tests/runtime/native/source-contract-test.py"
        replay = "tests/runtime/benchmark/io-replay-test.py"
        lifecycle = "tests/runtime/native/primary-lifecycle-audit-test.py"
        for serial in (build, replay, lifecycle,
                       "tests/runtime/native/make-interface-test.py",
                       "tests/runtime/native/test-report-test.py",
                       "x86_64 native SIMD disassembly contracts"):
            self.assertEqual(claims[serial].classification, "serial")
            self.assertEqual(
                resource_policy.potential_conflicts(serial, source),
                ("serial-barrier",))
        with self.assertRaisesRegex(ValueError, "unclassified"):
            resource_policy.potential_conflicts("unknown suite", source)
        self.assertEqual(
            resource_policy.potential_conflicts(source, source),
            ("same-phase",))

    def test_provisional_readonly_and_private_scopes_are_disjoint(self):
        claims = resource_policy.resource_claims()
        source = "tests/runtime/native/source-contract-test.py"
        readiness = "tests/runtime/native/production-readiness-test.py"
        syntax = "bash syntax test-loaded.sh"
        self.assertEqual(claims[syntax].classification, "read-only")
        self.assertEqual(claims[source].classification, "private-fixtures")
        self.assertFalse(claims[syntax].writes)
        self.assertNotEqual(claims[source].writes, claims[readiness].writes)
        self.assertEqual(resource_policy.potential_conflicts(source, readiness), ())
        self.assertEqual(resource_policy.potential_conflicts(source, syntax), ())
        self.assertTrue(resource_policy.ROOTLESS_PARALLEL_EXECUTION_ENABLED)
        for label, claim in claims.items():
            with self.subTest(label=label):
                self.assertTrue(claim.review)
                self.assertTrue(claim.reads)
                if claim.classification == "read-only":
                    self.assertFalse(claim.writes)
                elif claim.classification == "private-fixtures":
                    self.assertEqual(claim.writes, {f"private:{label}"})
                else:
                    self.assertEqual(claim.classification, "serial")
                    self.assertTrue(claim.writes)

    def test_claimed_disjointness_does_not_hide_shared_write_conflicts(self):
        resource = "native-artifacts"
        writer = "writer fixture"
        reader = "reader fixture"
        profiles = {
            writer: resource_policy.PhaseResources(
                "private-fixtures", frozenset({"checkout"}),
                frozenset({resource}), "synthetic writer"),
            reader: resource_policy.PhaseResources(
                "read-only", frozenset({resource}), frozenset(),
                "synthetic reader"),
        }
        self.assertEqual(
            resource_policy.potential_conflicts(writer, reader, profiles),
            ("shared:native-artifacts",))


parallel_spec = importlib.util.spec_from_file_location(
    "swapz_rootless_parallel_pilot", ROOT / "tests/tools/rootless-parallel.py")
parallel_runner = importlib.util.module_from_spec(parallel_spec)
parallel_spec.loader.exec_module(parallel_runner)


class RootlessParallelPilotContract(unittest.TestCase):
    """Hermetic worker/concurrency regressions; never open a block device."""

    def test_only_source_reviewed_adjacent_nonconflicting_groups(self):
        source = (ROOT / "tests/tools/test-rootless.sh").read_text(
            encoding="utf-8")
        for group, expected_count in (("initial", 2), ("readiness", 2),
                                      ("syntax", 19)):
            tasks = parallel_runner.validated_group(group, source)
            self.assertEqual(len(tasks), expected_count)
            if group == "syntax":
                self.assertIn(f"syntax) rootless_parallel_size={expected_count} ;;", source)
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            parallel_runner.validated_group("unknown", source)
        self.assertIn("case ${SWAPZ_ROOTLESS_JOBS:-auto} in", source)
        self.assertIn("rootless_parallel_collect", source)
        self.assertIn('rootless_parallel_run_group initial', source)
        self.assertIn('rootless_parallel_run_group readiness', source)
        self.assertIn('rootless_parallel_run_group syntax', source)
        self.assertIn('bash -n "$script"', source)
        self.assertIn('rootless_parallel_cleanup || :', source)
        reporter = (ROOT / "tests/tools/run-tests.py").read_text(
            encoding="utf-8")
        self.assertIn('Rootless: automatic CPU-aware groups; hardware benchmarks sequential.', reporter)
        self.assertIn('loaded qualification stays sequential', reporter)
        self.assertIn('python3 -B tests/runtime/native/source-contract-test.py -v',
                      source)

    def test_automatic_cpu_budget_observes_affinity_quota_and_single_core(self):
        with mock.patch.object(parallel_runner.os, "sched_getaffinity",
                               return_value=set(range(8)), create=True):
            with mock.patch.object(parallel_runner, "_cpu_quota_limit",
                                   return_value=3):
                self.assertEqual(parallel_runner.automatic_worker_count(), 3)
            with mock.patch.object(parallel_runner, "_cpu_quota_limit",
                                   return_value=1):
                self.assertEqual(parallel_runner.automatic_worker_count(), 1)
            with mock.patch.object(parallel_runner, "_cpu_quota_limit",
                                   return_value=None):
                self.assertEqual(parallel_runner.automatic_worker_count(), 8)
        with mock.patch.object(parallel_runner.os, "sched_getaffinity",
                               side_effect=OSError, create=True):
            with mock.patch.object(parallel_runner.os, "cpu_count",
                                   return_value=4):
                with mock.patch.object(parallel_runner, "_cpu_quota_limit",
                                       return_value=None):
                    self.assertEqual(parallel_runner.automatic_worker_count(), 4)

    def test_four_independent_workers_can_overlap_with_private_outputs(self):
        with tempfile.TemporaryDirectory(prefix="swapz-auto-parallel-") as name:
            directory = Path(name)
            source = (
                "import pathlib,sys,time; "
                "root=pathlib.Path(sys.argv[1]); "
                "(root/('ready-'+sys.argv[2])).write_text('ready'); "
                "deadline=time.monotonic()+5; "
                "exec('while len(list(root.glob(\"ready-*\"))) < 4 and "
                "time.monotonic()<deadline: time.sleep(0.01)'); "
                "sys.exit(0 if len(list(root.glob(\"ready-*\")))==4 else 36)"
            )
            tasks = tuple(
                (f"isolated-{index}", (sys.executable, "-B", "-c", source,
                                       str(directory), str(index)))
                for index in range(4))
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=4, timeout_seconds=7,
                poll_seconds=0.01), 0)
            for index in range(4):
                self.assertEqual((directory / f"worker-{index}.result")
                                 .read_text().split()[0], "0")
                for suffix in ("stdout", "stderr", "result"):
                    self.assertEqual(
                        (directory / f"worker-{index}.{suffix}").stat().st_mode
                        & 0o777, 0o600)

    def test_single_worker_fallback_keeps_original_test_sequence(self):
        with tempfile.TemporaryDirectory(prefix="swapz-serial-fallback-") as name:
            directory = Path(name)
            tasks = (
                ("first", (sys.executable, "-B", "-c", "pass")),
                ("second", (sys.executable, "-B", "-c", "pass")),
            )
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=1, timeout_seconds=5), 0)

    def test_two_workers_execute_simultaneously_with_private_outputs(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-pilot-") as name:
            directory = Path(name)
            # Each task requires the other to have entered its process; a
            # serial scheduler would time out without reaching both starts.
            script = (
                "import os,pathlib,sys,time; "
                "assert os.environ.get('PYTHONDONTWRITEBYTECODE')=='1'; "
                "own=pathlib.Path(sys.argv[1]); "
                "other=pathlib.Path(sys.argv[2]); own.write_text('started'); "
                "deadline=time.monotonic()+3; "
                "exec('while not other.exists() and time.monotonic()<deadline: "
                "time.sleep(0.01)'); "
                "sys.exit(0 if other.exists() else 34)"
            )
            first, second = directory / "first", directory / "second"
            tasks = (
                ("first", (sys.executable, "-B", "-c", script,
                           str(first), str(second))),
                ("second", (sys.executable, "-B", "-c", script,
                            str(second), str(first))),
            )
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=2, timeout_seconds=5,
                poll_seconds=0.01), 0)
            for index in (0, 1):
                self.assertEqual(
                    (directory / f"worker-{index}.result").read_text()
                    .split()[0], "0")
                for suffix in ("stdout", "stderr", "result"):
                    path = directory / f"worker-{index}.{suffix}"
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(first.is_file() and second.is_file())

    def test_failure_stops_dispatch_and_drains_active_workers(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-failure-") as name:
            directory = Path(name)
            never_started = directory / "third"
            tasks = (
                ("first", (sys.executable, "-B", "-c",
                           "import sys; print('private_failure', file=sys.stderr); "
                           "sys.exit(37)")),
                ("second", (sys.executable, "-B", "-c",
                            "import time; time.sleep(0.4)")),
                ("third", (sys.executable, "-B", "-c",
                           "from pathlib import Path; "
                           "Path(" + repr(str(never_started)) + ").touch()")),
            )
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=2, timeout_seconds=5,
                poll_seconds=0.01), 1)
            self.assertEqual(
                (directory / "worker-0.result").read_text().split()[0], "37")
            self.assertEqual(
                (directory / "worker-1.result").read_text().split()[0], "0")
            self.assertFalse((directory / "worker-2.result").exists())
            self.assertFalse(never_started.exists())
            self.assertIn(
                "private_failure",
                (directory / "worker-0.stderr").read_text())

    def test_timeout_is_bounded_and_child_is_reaped(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-timeout-") as name:
            directory = Path(name)
            tasks = (
                ("slow", (sys.executable, "-B", "-c",
                          "import time; time.sleep(10)")),
                ("fast", (sys.executable, "-B", "-c", "pass")),
            )
            started = time.monotonic()
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=2, timeout_seconds=0.25,
                poll_seconds=0.01), 1)
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(
                (directory / "worker-0.result").read_text().split()[0], "124")
            self.assertEqual(
                (directory / "worker-1.result").read_text().split()[0], "0")
            with self.assertRaisesRegex(ValueError, "invalid bounded"):
                parallel_runner.execute_group(directory, tasks, jobs=0)
            with self.assertRaisesRegex(ValueError, "invalid bounded"):
                parallel_runner.execute_group(
                    directory, tasks, jobs=len(resource_policy.SYNTAX_SCRIPTS) + 1)


    def test_zero_exit_with_live_descendant_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-descendant-") as name:
            directory = Path(name)
            marker = directory / "descendant-ready"
            descendant_source = (
                "import os,pathlib,signal,sys,time; "
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); "
                "pathlib.Path(sys.argv[1]).write_text(str(os.getpgrp())); "
                "time.sleep(30)")
            worker_source = (
                "import pathlib,subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-B','-c',sys.argv[2],sys.argv[1]], "
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); "
                "marker=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+5; "
                "exec('while not marker.exists() and time.monotonic()<deadline: "
                "time.sleep(0.01)'); "
                "sys.exit(0 if marker.exists() else 36)")
            tasks = (
                ("leaking-worker", (sys.executable, "-B", "-c",
                                    worker_source, str(marker), descendant_source)),
                ("ordinary-worker", (sys.executable, "-B", "-c", "pass")),
            )
            try:
                self.assertEqual(parallel_runner.execute_group(
                    directory, tasks, jobs=2, timeout_seconds=8,
                    poll_seconds=0.01), 1)
                self.assertEqual(
                    (directory / "worker-0.result").read_text().split()[0], "125")
                self.assertEqual(
                    (directory / "worker-0.result").read_text().split()[2], "1")
                self.assertEqual(
                    (directory / "worker-1.result").read_text().split()[0], "0")
            finally:
                # Even an old/defective runner must not strand this fixture's
                # deliberately orphaned process-group descendant.
                if marker.is_file():
                    try:
                        os.killpg(int(marker.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_real_worker_exit_125_keeps_original_failure(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-exit-") as name:
            directory = Path(name)
            tasks = (
                ("exit-125", (sys.executable, "-B", "-c",
                              "import sys; sys.exit(125)")),
                ("normal", (sys.executable, "-B", "-c", "pass")),
            )
            self.assertEqual(parallel_runner.execute_group(
                directory, tasks, jobs=2, timeout_seconds=5,
                poll_seconds=0.01), 1)
            self.assertEqual(
                (directory / "worker-0.result").read_text().split()[0], "125")
            self.assertEqual(
                (directory / "worker-0.result").read_text().split()[2], "0")

    def test_stop_escalates_when_leader_exits_before_descendant(self):
        with tempfile.TemporaryDirectory(prefix="swapz-parallel-group-") as name:
            directory = Path(name)
            marker = directory / "descendant-ready"
            descendant_source = (
                "import pathlib,signal,sys,time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "pathlib.Path(sys.argv[1]).write_text('ready'); "
                "time.sleep(30)")
            worker_source = (
                "import pathlib,subprocess,sys,time; "
                "subprocess.Popen([sys.executable,'-B','-c',sys.argv[2],sys.argv[1]], "
                "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); "
                "marker=pathlib.Path(sys.argv[1]); deadline=time.monotonic()+5; "
                "exec('while not marker.exists() and time.monotonic()<deadline: "
                "time.sleep(0.01)'); "
                "exec('while True: time.sleep(1)')")
            worker = subprocess.Popen(
                (sys.executable, "-B", "-c", worker_source,
                 str(marker), descendant_source),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True)
            observed_signals = []
            original_killpg = os.killpg

            def record_signal(group_id, signal_number):
                observed_signals.append(signal_number)
                return original_killpg(group_id, signal_number)

            try:
                deadline = time.monotonic() + 7
                while not marker.exists() and time.monotonic() < deadline:
                    self.assertIsNone(worker.poll())
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                with mock.patch.object(parallel_runner.os, "killpg",
                                       side_effect=record_signal):
                    parallel_runner._stop_owned_worker(worker)
                self.assertIn(signal.SIGKILL, observed_signals)
                self.assertIsNotNone(worker.poll())
            finally:
                # The fixture must clean up even when the asserted behavior
                # regresses: no test may leave its synthetic child running.
                try:
                    original_killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                if worker.poll() is None:
                    worker.kill()
                worker.wait(timeout=5)


class MainSynchronizationContract(unittest.TestCase):
    """Exercise test-time main synchronization with isolated local Git remotes."""

    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp(
            prefix="main-sync-", dir=ROOT / "build/tests"))
        self.origin = self.sandbox / "origin.git"
        self.checkout = self.sandbox / "checkout"
        self._git(self.sandbox, "init", "--quiet", "--bare",
                  "--object-format=sha1", str(self.origin))
        self._git(self.sandbox, "init", "--quiet", "--initial-branch=main",
                  "--object-format=sha1", str(self.checkout))
        self._git(self.checkout, "config", "user.name", "main sync test")
        self._git(self.checkout, "config", "user.email", "test@example.invalid")
        (self.checkout / "source.c").write_text(
            "int source(void) { return 1; }\n", encoding="utf-8")
        (self.checkout / runner.GIT_RESULT).write_text(
            '{"overall":"NOT_RUN"}\n', encoding="utf-8")
        self._git(self.checkout, "add", "source.c", runner.GIT_RESULT)
        self._git(self.checkout, "commit", "--quiet", "-m", "initial source")
        self._git(self.checkout, "remote", "add", "origin", str(self.origin))
        self._git(self.checkout, "push", "--quiet", "origin", "main:main")

        self.old_root, self.old_report = runner.ROOT, runner.REPORT
        runner.ROOT = self.checkout
        runner.REPORT = self.checkout / runner.GIT_RESULT
        self.remote_patch = mock.patch.object(
            runner, "_remote_origin_url",
            return_value="https://github.com/k1moradi/swapz.git")
        self.remote_patch.start()

    def tearDown(self):
        self.remote_patch.stop()
        runner.ROOT, runner.REPORT = self.old_root, self.old_report
        import shutil
        shutil.rmtree(self.sandbox)

    @staticmethod
    def _git(cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True,
            text=True, timeout=15)

    def _advance_remote(self, *, source=False, report=False, extra_file=None):
        writer = self.sandbox / "writer"
        self._git(self.sandbox, "clone", "--quiet", "--branch", "main",
                  str(self.origin), str(writer))
        self._git(writer, "config", "user.name", "remote writer")
        self._git(writer, "config", "user.email", "test@example.invalid")
        if source:
            (writer / "source.c").write_text(
                "int source(void) { return 2; }\n", encoding="utf-8")
        if report:
            (writer / runner.GIT_RESULT).write_text(
                '{"overall":"INCOMPLETE","writer":"remote"}\n',
                encoding="utf-8")
        if extra_file is not None:
            (writer / extra_file).write_text("remote file\n", encoding="utf-8")
        self._git(writer, "add", ".")
        message = "remote advance"
        if report and not source and extra_file is None:
            message = f"test: latest run for {runner.git_sha()[:12]} [skip ci]"
        self._git(writer, "commit", "--quiet", "-m", message)
        self._git(writer, "push", "--quiet", "origin", "main:main")
        return self._git(writer, "rev-parse", "HEAD").stdout.strip()

    def test_pretest_fast_forward_preserves_staged_and_worktree_report(self):
        report = self.checkout / runner.GIT_RESULT
        report.write_text('{"overall":"STAGED"}\n', encoding="utf-8")
        self._git(self.checkout, "add", runner.GIT_RESULT)
        report.write_text('{"overall":"WORKTREE"}\n', encoding="utf-8")
        expected_remote = self._advance_remote(source=True)

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["reason"], "fast_forwarded")
        self.assertTrue(result["source_changed"])
        self.assertEqual(result["head_sha"], expected_remote)
        self.assertEqual(runner.git_sha(), result["source_sha"])
        self.assertEqual(report.read_text(encoding="utf-8"),
                         '{"overall":"NOT_RUN"}\n')
        snapshot = self.checkout / result["report_snapshot"]
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o700)
        self.assertEqual((snapshot / "index.json").stat().st_mode & 0o777,
                         0o600)
        self.assertEqual((snapshot / "worktree.json").stat().st_mode & 0o777,
                         0o600)
        self.assertEqual((snapshot / "index.json").read_text(),
                         '{"overall":"STAGED"}\n')
        self.assertEqual((snapshot / "worktree.json").read_text(),
                         '{"overall":"WORKTREE"}\n')
        self.assertIsNone(runner.tracked_source_checkout_preflight())

    def test_report_only_remote_advance_does_not_request_make_reexec(self):
        expected_remote = self._advance_remote(report=True)

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["head_sha"], expected_remote)
        self.assertFalse(result["source_changed"])
        self.assertEqual(runner.git_sha(), result["source_sha"])

    def test_uncommitted_source_blocks_and_dirty_report_is_preserved(self):
        source = self.checkout / "source.c"
        source.write_text("unpublished source edit\n", encoding="utf-8")
        report = self.checkout / runner.GIT_RESULT
        report.write_text('{"overall":"LOCAL"}\n', encoding="utf-8")

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "uncommitted_tracked_source")
        self.assertEqual(source.read_text(encoding="utf-8"),
                         "unpublished source edit\n")
        snapshot = self.checkout / result["report_snapshot"]
        self.assertEqual((snapshot / "worktree.json").read_text(),
                         '{"overall":"LOCAL"}\n')

    def test_untracked_path_collision_blocks_without_replacing_local_file(self):
        local_file = self.checkout / "new-source.c"
        local_file.write_text("local untracked bytes\n", encoding="utf-8")
        old_head = self._git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        expected_remote = self._advance_remote(extra_file="new-source.c")

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"],
                         "untracked_paths_overlap_remote_changes")
        self.assertEqual(result["collision_count"], 1)
        self.assertEqual(local_file.read_text(encoding="utf-8"),
                         "local untracked bytes\n")
        self.assertEqual(self._git(self.checkout, "rev-parse", "HEAD")
                         .stdout.strip(), old_head)
        self.assertNotEqual(old_head, expected_remote)

    def test_local_ahead_and_diverged_main_are_not_rewritten(self):
        local_file = self.checkout / "local.c"
        local_file.write_text("local commit\n", encoding="utf-8")
        self._git(self.checkout, "add", "local.c")
        self._git(self.checkout, "commit", "--quiet", "-m", "local commit")
        local_head = self._git(self.checkout, "rev-parse", "HEAD").stdout.strip()

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "local_main_ahead_of_remote")
        self.assertEqual(self._git(self.checkout, "rev-parse", "HEAD")
                         .stdout.strip(), local_head)

    def test_diverged_main_blocks_without_resetting_either_history(self):
        local_file = self.checkout / "local.c"
        local_file.write_text("local commit\n", encoding="utf-8")
        self._git(self.checkout, "add", "local.c")
        self._git(self.checkout, "commit", "--quiet", "-m", "local commit")
        local_head = self._git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        remote_head = self._advance_remote(source=True)

        result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "local_main_diverged_from_remote")
        self.assertEqual(self._git(self.checkout, "rev-parse", "HEAD")
                         .stdout.strip(), local_head)
        self.assertNotEqual(local_head, remote_head)

    def test_second_source_advance_after_reexec_is_blocked(self):
        expected_source = runner.git_sha()
        remote_head = self._advance_remote(source=True)

        result = runner.sync_main_before_test(expected_source)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"],
                         "source_advanced_again_before_test_start")
        self.assertEqual(result["head_sha"], remote_head)
        self.assertEqual(self._git(self.checkout, "rev-parse", "HEAD")
                         .stdout.strip(), remote_head)

    def test_fetch_authentication_failure_is_bounded_and_redacted(self):
        private_message = b"Authentication failed SECRET private/path"
        failed_fetch = subprocess.CompletedProcess(
            ["git", "fetch"], 1, b"", private_message)
        with mock.patch.object(
                runner, "git_command_with_credential_fallback",
                return_value=failed_fetch):
            result = runner.sync_main_before_test()

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"],
                         "fetch_credentials_or_repository_access")
        self.assertNotIn("SECRET", str(result))
        self.assertNotIn("private/path", str(result))

    def test_posttest_sync_fast_forwards_and_preserves_new_report(self):
        report = self.checkout / runner.GIT_RESULT
        report.write_text('{"overall":"TEST RUN"}\n', encoding="utf-8")
        expected_remote = self._advance_remote(source=True)

        result = runner.sync_main_after_test()

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["reason"], "fast_forwarded")
        self.assertEqual(result["head_sha"], expected_remote)
        snapshot = self.checkout / result["report_snapshot"]
        self.assertEqual((snapshot / "worktree.json").read_text(),
                         '{"overall":"TEST RUN"}\n')
        self.assertEqual(report.read_text(encoding="utf-8"),
                         '{"overall":"NOT_RUN"}\n')

    def test_main_test_lock_is_exclusive_and_mode_private(self):
        first_fd, expected, error = runner.acquire_make_test_lock()
        self.assertIsNone(expected)
        self.assertIsNone(error)
        try:
            self.assertEqual(os.fstat(first_fd).st_mode & 0o777, 0o600)
            second_fd, _, second_error = runner.acquire_make_test_lock()
            self.assertIsNone(second_fd)
            self.assertEqual(second_error, "another_official_test_is_running")
        finally:
            os.close(first_fd)
        third_fd, _, third_error = runner.acquire_make_test_lock()
        self.assertIsNone(third_error)
        os.close(third_fd)

    def test_make_jobserver_pipe_descriptors_are_preserved(self):
        read_fd, write_fd = os.pipe()
        previous_flags = (os.get_inheritable(read_fd),
                          os.get_inheritable(write_fd))
        try:
            os.set_inheritable(read_fd, False)
            os.set_inheritable(write_fd, False)
            with mock.patch.dict(os.environ, {
                    "MAKEFLAGS": f"--jobserver-auth={read_fd},{write_fd}"}):
                changed = runner.preserve_make_jobserver_fds()
            self.assertEqual(changed, [(read_fd, False), (write_fd, False)])
            self.assertTrue(os.get_inheritable(read_fd))
            self.assertTrue(os.get_inheritable(write_fd))
        finally:
            os.set_inheritable(read_fd, previous_flags[0])
            os.set_inheritable(write_fd, previous_flags[1])
            os.close(read_fd)
            os.close(write_fd)

    def test_reexec_passes_lock_and_jobserver_through_process_exec(self):
        read_fd, write_fd = os.pipe()
        try:
            fake_make = self.sandbox / "fake-make"
            result_path = self.sandbox / "reexec.json"
            child_path = self.sandbox / "reexec-child.py"
            fake_make.write_text(
                "#!/usr/bin/python3\n"
                "import fcntl, json, os, stat, sys\n"
                "lock=int(os.environ['SWAPZ_MAKE_TEST_LOCK_FD'])\n"
                "read_fd, write_fd=map(int, os.environ['TEST_JOBSERVER'].split(','))\n"
                "lock_stat=os.fstat(lock)\n"
                "assert stat.S_ISREG(lock_stat.st_mode)\n"
                "assert lock_stat.st_mode & 0o777 == 0o600\n"
                "fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "os.fstat(read_fd); os.fstat(write_fd)\n"
                "assert os.environ['SWAPZ_MAKE_TEST_SYNC_REEXEC'] == '1'\n"
                "assert os.environ['SWAPZ_MAKE_TEST_EXPECTED_SOURCE'] == 'a' * 40\n"
                "assert sys.argv[1:] == ['--no-print-directory', 'test', 'KDIR=/test-kernel']\n"
                "open(os.environ['TEST_RESULT'], 'w').write('pass')\n",
                encoding="utf-8")
            fake_make.chmod(0o755)
            child_path.write_text(
                "import fcntl, importlib.util, os\n"
                "from types import SimpleNamespace\n"
                f"spec=importlib.util.spec_from_file_location('runner', {str(ROOT / 'tests/tools/run-tests.py')!r})\n"
                "runner=importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)\n"
                "fd=os.open(os.environ['TEST_LOCK'], os.O_RDWR | os.O_CREAT, 0o600)\n"
                "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
                "reason=runner.reexecute_make_after_source_sync(\n"
                "SimpleNamespace(tier='algorithm', kdir='/test-kernel'), fd, 'a' * 40)\n"
                "raise SystemExit(88 if reason is None else 89)\n",
                encoding="utf-8")
            lock_path = self.sandbox / "reexec.lock"
            environment = os.environ.copy()
            environment.update({
                "MAKE": str(fake_make),
                "MAKEFLAGS": f"--jobserver-auth={read_fd},{write_fd}",
                "TEST_JOBSERVER": f"{read_fd},{write_fd}",
                "TEST_LOCK": str(lock_path),
                "TEST_RESULT": str(result_path),
                "SWAPZ_MAKE_TEST_REEXEC": "",
                "SWAPZ_MAKE_TEST_LOCK_FD": "",
                "SWAPZ_MAKE_TEST_EXPECTED_SOURCE": "",
            })
            completed = subprocess.run(
                [sys.executable, str(child_path)], env=environment,
                pass_fds=(read_fd, write_fd), capture_output=True,
                text=True, timeout=15, check=False)
            self.assertEqual(completed.returncode, 0,
                             completed.stderr or completed.stdout)
            self.assertEqual(result_path.read_text(encoding="utf-8"), "pass")
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_reexec_failure_preserves_lock_and_make_context(self):
        lock_fd, _, error = runner.acquire_make_test_lock()
        self.assertIsNone(error)
        try:
            with mock.patch.object(runner, "preserve_make_jobserver_fds",
                                   return_value=[]), \
                    mock.patch.object(runner.os, "execvpe",
                                      side_effect=OSError("exec failure")) as run:
                reason = runner.reexecute_make_after_source_sync(
                    mock.Mock(tier="algorithm", kdir="/test-kernel"),
                    lock_fd, "a" * 40)
            self.assertEqual(reason, "make_reexec_failed")
            self.assertEqual(run.call_args.args[0], "make")
            self.assertEqual(run.call_args.args[1][2], "test")
            self.assertIn("KDIR=/test-kernel", run.call_args.args[1])
            self.assertEqual(run.call_args.args[2][runner.MAIN_SYNC_REEXEC], "1")
            self.assertEqual(os.get_inheritable(lock_fd), False)
        finally:
            os.close(lock_fd)


class NativeTimingContract(unittest.TestCase):
    def test_algorithm_scope_cannot_replace_same_source_full_evidence(self):
        source = "a" * 40
        new_report = {
            "schema": "swapz-test-results-v1",
            "qualification": "RAM_BACKED_NULL_BLK_ONLY",
            "qualification_tier": "ALGORITHM_PHYSICAL_PENDING",
            "tested_commit_sha": source, "source_sha": source,
            "overall": "INCOMPLETE",
        }
        full = {
            **new_report, "qualification_tier": "FULL_INTEGRATION_RAM_ONLY",
            "overall": "PASS",
        }
        self.assertTrue(runner.stronger_published_qualification_scope(
            full, new_report))
        for state in ("FAIL", "BLOCKED", "INCOMPLETE"):
            with self.subTest(state=state):
                self.assertTrue(
                    runner.stronger_published_qualification_scope(
                        {**full, "overall": state}, new_report))
        self.assertTrue(runner.stronger_published_qualification_scope(
            {key: value for key, value in full.items()
             if key != "qualification_tier"}, new_report))
        self.assertFalse(runner.stronger_published_qualification_scope(
            {**full, "source_sha": "b" * 40}, new_report))
        self.assertFalse(runner.stronger_published_qualification_scope(
            {**full, "qualification_tier": "ALGORITHM_PHYSICAL_PENDING"},
            new_report))
        self.assertFalse(runner.stronger_published_qualification_scope(
            new_report, {**new_report, "qualification_tier":
                         "FULL_INTEGRATION_RAM_ONLY"}))
        self.assertEqual(
            runner.official_pass_binding_refusal(
                {**new_report, "overall": "PASS"}, source),
            "physical_admission_not_qualified")

    def test_tracked_source_preflight_blocks_uncommitted_tests(self):
        """The generated report can change; source edits must block early."""
        with tempfile.TemporaryDirectory(
                prefix="source-preflight-", dir=ROOT / "build/tests") as name:
            checkout = Path(name)
            def git(*args):
                return subprocess.run(
                    ["git", *args], cwd=checkout, check=True,
                    capture_output=True, timeout=12)
            git("init", "--quiet", "--initial-branch=main",
                "--object-format=sha1")
            git("config", "user.name", "test-report CI")
            git("config", "user.email", "test@example.invalid")
            (checkout / "source.c").write_text("int source(void) { return 1; }\n")
            (checkout / runner.GIT_RESULT).write_text('{"overall":"NOT_RUN"}\n')
            git("add", "source.c", runner.GIT_RESULT)
            git("commit", "--quiet", "-m", "Test source")
            previous_root = runner.ROOT
            runner.ROOT = checkout
            try:
                self.assertIsNone(runner.tracked_source_checkout_preflight())
                (checkout / runner.GIT_RESULT).write_text('{"overall":"FAIL"}\n')
                self.assertIsNone(runner.tracked_source_checkout_preflight())
                (checkout / "source.c").write_text("modified source\n")
                refusal = runner.tracked_source_checkout_preflight()
                self.assertEqual(refusal["reason"], "uncommitted_tracked_source")
                self.assertEqual(refusal["changed_paths"], ["source.c"])
                git("add", "source.c")
                self.assertEqual(
                    runner.tracked_source_checkout_preflight()["changed_paths"],
                    ["source.c"])
            finally:
                runner.ROOT = previous_root

    def test_source_preflight_refusal_skips_every_expensive_stage(self):
        preflight = {
            "reason": "uncommitted_tracked_source",
            "changed_paths": ["tests/runtime/native/algorithm-pageout-oracle-test.py"],
            "total_changed_paths": 1,
        }
        written = []
        with mock.patch.object(
                runner.argparse.ArgumentParser, "parse_args",
                return_value=mock.Mock(kdir="/unused", tier="full")), \
             mock.patch.object(runner, "report_host_identity",
                               return_value={"status": "UNAVAILABLE"}), \
             mock.patch.object(runner, "git_sha", return_value="a" * 40), \
             mock.patch.object(runner, "make_invocation",
                               return_value=(["make"], "fixture")), \
             mocked_main_sync("a" * 40), \
             mock.patch.object(runner, "tracked_source_checkout_preflight",
                               return_value=preflight), \
             mock.patch.object(runner, "run_stage") as run_stage, \
             mock.patch.object(runner, "write_report",
                               side_effect=lambda report: written.append(
                                   json.loads(json.dumps(report)))), \
             mock.patch.object(runner, "print_bench"), \
             mock.patch.object(runner, "publish",
                               return_value="SKIPPED_GIT_SYNC: tracked source/index is not clean"), \
             mock.patch.object(runner, "write_failure_diagnostic",
                               return_value=None), \
             mock.patch.object(runner, "refresh_history",
                               return_value="NOT UPDATED: fixture"), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(runner.main(), 2)
        run_stage.assert_not_called()
        self.assertEqual(written[0]["overall"], "BLOCKED")
        self.assertEqual(written[0]["stages"], [])
        self.assertEqual(written[0]["checkout_preflight"], preflight)
        self.assertIn("qualification stages not started", output.getvalue())
        self.assertIn("algorithm-pageout-oracle-test.py", output.getvalue())
        self.assertIn("NOT RUN", output.getvalue())

    def test_tier_routing_cannot_promote_ram_only_to_physical_pass(self):
        from unittest import mock

        source_sha = "a" * 40
        for tier, expected_overall, expected_exit in (
                ("algorithm", "INCOMPLETE", 2),
                ("full", "PASS", 0)):
            with self.subTest(tier=tier):
                observed_commands = []
                report_snapshots = []

                def synthetic_stage(title, command, result, **options):
                    observed_commands.append((title, tuple(command), options))
                    result["stages"].append({
                        "name": title, "status": "PASS",
                        "elapsed_s": 0.0, "exit_code": 0,
                    })
                    if options.get("parse_bench"):
                        result["benchmarks"]["delta64_prepare"] = {
                            "overall": "NOT_RUN"}
                    return 0

                with mock.patch.object(
                        runner.argparse.ArgumentParser, "parse_args",
                        return_value=mock.Mock(kdir="/unused", tier=tier)), \
                        mock.patch.object(
                            runner, "report_host_identity",
                            return_value={"status": "AVAILABLE"}), \
                        mock.patch.object(
                            runner, "git_sha", return_value=source_sha), \
                        mock.patch.object(
                            runner, "make_invocation",
                            return_value=(["make"], "fixture")), \
                        mocked_main_sync(source_sha), \
                        mock.patch.object(
                            runner, "tracked_source_checkout_preflight",
                            return_value=None), \
                        mock.patch.object(
                            runner, "run_stage", side_effect=synthetic_stage), \
                        mock.patch.object(
                            runner, "qualification_artifact_digests",
                            return_value={"status": "AVAILABLE"}), \
                        mock.patch.object(
                            runner, "owner_qualification_artifacts_available",
                            return_value=True), \
                        mock.patch.object(
                            runner, "required_benchmark_gates_pass",
                            return_value=True), \
                        mock.patch.object(
                            runner, "official_pass_binding_refusal",
                            return_value=None), \
                        mock.patch.object(
                            runner, "lane_gap_attribution_rows",
                            return_value=[]), \
                        mock.patch.object(
                            runner, "goal_scorecard",
                            return_value={"overall": "UNAVAILABLE"}), \
                        mock.patch.object(
                            runner, "write_report",
                            side_effect=lambda report: report_snapshots.append(
                                json.loads(json.dumps(report)))), \
                        mock.patch.object(runner, "print_bench"), \
                        mock.patch.object(
                            runner, "publish", return_value="fixture"), \
                        mock.patch.object(
                            runner, "refresh_history",
                            return_value="NOT UPDATED: fixture"), \
                        contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(runner.main(), expected_exit)

                self.assertEqual(len(observed_commands), 5)
                rootless_command = observed_commands[1][1]
                self.assertEqual(rootless_command[-1:] == ("--algorithm",),
                                 tier == "algorithm")
                self.assertEqual(report_snapshots[0]["overall"],
                                 expected_overall)
                if tier == "algorithm":
                    self.assertEqual(
                        report_snapshots[0]["physical_qualification"],
                        {"overall": "NOT_RUN",
                         "reason": "physical_source_admission_protocol_not_qualified"})
                else:
                    self.assertNotIn("physical_qualification",
                                     report_snapshots[0])

    def test_unified_progress_table_has_one_header_and_global_ids(self):
        captured = io.StringIO()
        stages = [(name, ["unused"]) for name in runner.OFFICIAL_STAGE_NAMES]
        with contextlib.redirect_stdout(captured):
            table = runner.QualificationProgressTable()
            table.complete("Rootless", "Native build and metadata", "PASS", "4s")
            table.complete("Loaded", "SD mixed workloads", "FAIL", "5.2s")
            runner.print_stage_results(
                stages, [{"status": "PASS", "elapsed_s": 2.5}],
                progress_table=table)
            runner.print_physical_trial_result(
                "NOT RUN", "-", progress_table=table)
        output = captured.getvalue()
        self.assertEqual(output.count("ID | Suite"), 1)
        for obsolete_header in (
                "Rootless suite results:", "Qualification stage results:",
                "loaded qualification progress:"):
            self.assertNotIn(obsolete_header, output)
        rows = [line for line in output.splitlines() if
                re.match(r"^\s+[1-9][0-9]* \| ", line)]
        self.assertEqual(len(rows), 8)
        self.assertEqual(
            [int(re.match(r"^\s+([0-9]+)", row).group(1)) for row in rows],
            list(range(1, 9)))
        self.assertIn("Rootless | Native build and metadata", output)
        self.assertIn("Loaded   | SD mixed workloads", output)
        self.assertIn("Physical | Authorized physical swap trial (dev)", output)
        self.assertEqual(output.count("NOT RUN"), 5)

    def test_rootless_substage_timing_does_not_interrupt_unified_rows(self):
        """Keep rootless -> loaded rows adjacent; print timing only afterward."""
        transcript = (
            "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_TIMING native_make_s=0 remaining_contracts_s=0\n")
        result = {"stages": [], "benchmarks": {}}
        captured = io.StringIO()
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript)), \
                mock.patch.object(
                    runner, "rootless_phase_names",
                    return_value=frozenset({"rootless initialization"})), \
                mock.patch.object(
                    runner, "parse_predictor_evidence", return_value={}), \
                mock.patch.object(
                    runner, "parse_gc_scan_scale_evidence", return_value={}), \
                mock.patch.object(
                    runner, "parse_extent_geometry_evidence", return_value={}), \
                contextlib.redirect_stdout(captured):
            progress_table = runner.QualificationProgressTable()
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["unused"], result,
                stream_rootless_progress=True,
                progress_table=progress_table), 0)
            progress_table.complete(
                "Loaded", "Loaded host preflight", "DONE", "0.231s")
            runner.print_stage_results(
                [(name, ["unused"]) for name in runner.OFFICIAL_STAGE_NAMES],
                result["stages"], progress_table)
            runner.print_rootless_timing_summary(result["stages"])

        output = captured.getvalue()
        self.assertEqual(result["stages"][0]["substage_elapsed_s"], {
            "native_make_s": 0, "remaining_contracts_s": 0})
        self.assertEqual(output.count("ID | Suite"), 1)
        self.assertRegex(
            output,
            r"(?m)^\s*1 \| Rootless \| Rootless initialization\s+\| "
            r"PASS\s+\|\s+0s\n"
            r"\s*2 \| Loaded\s+\| Loaded host preflight\s+\| "
            r"DONE\s+\|\s+0[.]231s$")
        self.assertEqual(output.count("Rootless stage timing"), 1)
        self.assertLess(
            output.index("  7 | Stage"),
            output.index("  Rootless stage timing (observational only):"))
        self.assertIn(
            "native make=0s; remaining contracts=0s", output)
        self.assertNotIn("\r", output)

    def test_unified_rootless_failure_keeps_original_exit_and_one_header(self):
        transcript = (
            "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=0 elapsed_s=1 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=START index=1 elapsed_s=0 "
            "label=tests/Makefile native and metadata\n")
        result = {"stages": [], "benchmarks": {}}
        captured = io.StringIO()
        # This fixture tests the stream and original failure handling. The
        # independently tested source inventory must not affect its markers.
        declared_phases = frozenset({
            "rootless initialization", "tests/Makefile native and metadata",
        })
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=1)), \
                mock.patch.object(
                    runner, "rootless_phase_names",
                    return_value=declared_phases), \
                mock.patch.object(
                    runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(captured):
            table = runner.QualificationProgressTable()
            self.assertNotEqual(
                runner.run_stage(
                    "Native and rootless contracts", ["unused"], result,
                    stream_rootless_progress=True, progress_table=table), 0)
        output = captured.getvalue()
        self.assertEqual(output.count("ID | Suite"), 1)
        self.assertEqual(output.count("Rootless initialization"), 1,
                         f"Source-controlled synthetic progress: {output!r}")
        self.assertEqual(output.count("Native build and metadata"), 1,
                         f"Source-controlled synthetic progress: {output!r}")
        self.assertRegex(
            output, r"(?m)^\s*2 \| Rootless \|.*\| FAIL\s+\|")
        self.assertNotIn("\r", output)
        self.assertEqual(result["stages"][-1]["status"], "FAIL")

    def test_rootless_progress_rejects_unsafe_and_invalid_records(self):
        allowed = runner.rootless_phase_names()
        self.assertEqual(
            runner.rootless_phase_progress(
                "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
                "label=rootless initialization\n", allowed),
            ("START", 0, 0, "rootless initialization"))
        self.assertEqual(
            runner.rootless_phase_progress(
                "ROOTLESS_PHASE_PROGRESS state=PASS index=1 elapsed_s=12 "
                "label=tests/Makefile native and metadata\n", allowed),
            ("PASS", 1, 12, "tests/Makefile native and metadata"))
        self.assertIsNone(runner.rootless_phase_progress(
            "ROOTLESS_PHASE_PROGRESS state=PASS index=2 elapsed_s=1 "
            "label=/private/user/device", allowed))
        self.assertIsNone(runner.rootless_phase_progress(
            "ROOTLESS_PHASE_PROGRESS state=PASS index=02 elapsed_s=1 "
            "label=tests/Makefile native and metadata", allowed))
        self.assertIsNone(runner.rootless_phase_progress(
            "ROOTLESS_PHASE_PROGRESS state=PASS index=2 elapsed_s=01 "
            "label=tests/Makefile native and metadata", allowed))
        self.assertIsNone(runner.rootless_phase_progress(
            "ROOTLESS_PHASE_PROGRESS state=SKIP index=2 elapsed_s=1 "
            "label=tests/Makefile native and metadata", allowed))

    def test_streamed_rootless_progress_preserves_original_failure(self):
        from unittest import mock

        transcript = (
            "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=START index=1 elapsed_s=0 "
            "label=tests/Makefile native and metadata\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=1 elapsed_s=4 "
            "label=tests/Makefile native and metadata\n"
            "ROOTLESS_PHASE_PROGRESS state=START index=2 elapsed_s=0 "
            "label=tests/runtime/native/source-contract-test.py\n"
            # Untrusted output cannot spoof a suite name or skip an index.
            "ROOTLESS_PHASE_PROGRESS state=PASS index=2 elapsed_s=3 "
            "label=/private/secret\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=4 elapsed_s=3 "
            "label=tests/runtime/native/source-contract-test.py\n")
        result = {"stages": [], "benchmarks": {}}
        stream = io.StringIO()
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=1)), \
                mock.patch.object(
                    runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(stream):
            self.assertNotEqual(runner.run_stage(
                "Native and rootless contracts", ["unused"], result,
                stream_rootless_progress=True), 0)
        text = stream.getvalue()
        self.assertIn("ID | Name", text)
        self.assertIn(
            runner.rootless_suite_table_row(
                0, "rootless initialization", "PASS", "0s"), text)
        self.assertIn(
            runner.rootless_suite_table_row(
                1, "tests/Makefile native and metadata", "PASS", "4s"),
            text)
        self.assertRegex(
            text,
            r"(?m)^\s*3 \| Source code and safety checks\s+\| FAIL\s+\| +[0-9.]+s$")
        self.assertEqual(text.count("Source code and safety checks"), 1)
        self.assertNotIn("/private/secret", text)
        self.assertNotIn("Start   ", text)
        self.assertNotIn("Test    ", text)
        self.assertEqual(result["stages"][-1]["status"], "FAIL")

    def test_rootless_table_names_are_short_unique_and_source_controlled(self):
        names = runner.rootless_phase_names()
        self.assertEqual(set(runner.ROOTLESS_SUITE_DISPLAY_NAMES), names)
        display_names = [runner.rootless_suite_display_name(name)
                         for name in names]
        self.assertEqual(len(display_names), len(set(display_names)))
        self.assertTrue(all(len(name) <= runner.ROOTLESS_NAME_WIDTH
                            and not name.startswith("tests/")
                            for name in display_names))
        self.assertEqual(
            runner.rootless_suite_display_name("bash syntax check.sh"),
            "Bash syntax: check.sh")

    def test_rootless_tty_rewrites_running_row_in_place(self):
        from unittest import mock

        class TerminalOutput(io.StringIO):
            def isatty(self):
                return True

        transcript = (
            "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=0 elapsed_s=2 "
            "label=rootless initialization\n")
        terminal = TerminalOutput()
        result = {"stages": [], "benchmarks": {}}
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript)), \
                contextlib.redirect_stdout(terminal):
            runner.run_stage("Native and rootless contracts", ["unused"],
                             result, stream_rootless_progress=True)
        output = terminal.getvalue()
        self.assertIn("\r" + runner.rootless_suite_table_row(
            0, "rootless initialization", "RUNNING", "-"), output)
        self.assertIn("\r" + runner.rootless_suite_table_row(
            0, "rootless initialization", "PASS", "2s") + "\n", output)
        self.assertEqual(output.count("\r"), 2)
        self.assertNotIn("Start   1:", output)

    def test_per_suite_rootless_timings_reject_spoofed_and_duplicate_records(self):
        valid = (
            "ROOTLESS_PHASE_TIMING index=0 elapsed_s=0 label=rootless initialization\n"
            "ROOTLESS_PHASE_TIMING index=1 elapsed_s=12 label=tests/Makefile native and metadata\n"
            "ROOTLESS_PHASE_TIMING index=2 elapsed_s=34 label=tests/runtime/native/source-contract-test.py\n"
            "ROOTLESS_PHASE_TIMING index=3 elapsed_s=2 label=bash syntax swapz-primary-boot-verify\n")
        self.assertEqual(runner.parse_rootless_phase_timings(valid), [
            {"name": "rootless initialization", "elapsed_s": 0},
            {"name": "tests/Makefile native and metadata", "elapsed_s": 12},
            {"name": "tests/runtime/native/source-contract-test.py", "elapsed_s": 34},
            {"name": "bash syntax swapz-primary-boot-verify", "elapsed_s": 2}])
        self.assertIsNone(runner.parse_rootless_phase_timings(""))
        self.assertIsNone(runner.parse_rootless_phase_timings(valid + valid))
        self.assertIsNone(runner.parse_rootless_phase_timings(
            valid.replace("index=1", "index=2")))
        self.assertIsNone(runner.parse_rootless_phase_timings(
            valid.replace("index=2 elapsed_s=34", "index=2 elapsed_s=-1")))
        self.assertIsNone(runner.parse_rootless_phase_timings(
            valid.replace("source-contract-test.py", "/private/secret")))

    def test_owned_pair_phase_timings_are_ordered_and_never_gates(self):
        records = (
            "OWNED_PAIR_PHASE_TIMING phase=setup elapsed_ms=120\n"
            "OWNED_PAIR_PHASE_TIMING phase=fixture elapsed_ms=45\n"
            "OWNED_PAIR_PHASE_TIMING phase=replay elapsed_ms=12000\n"
            "OWNED_PAIR_PHASE_TIMING phase=verification elapsed_ms=30\n"
            "OWNED_PAIR_PHASE_TIMING phase=teardown elapsed_ms=190\n")
        self.assertEqual(runner.parse_owned_pair_phase_timings(records), [{
            "pair_index": 0,
            "phase_elapsed_ms": [
                {"phase": phase, "elapsed_ms": duration}
                for phase, duration in (
                    ("setup", 120), ("fixture", 45), ("replay", 12000),
                    ("verification", 30), ("teardown", 190))]}])
        self.assertEqual(runner.parse_owned_pair_phase_timings(
            records + "OWNED_PAIR_PHASE_TIMING phase=setup elapsed_ms=1\n"),
            runner.parse_owned_pair_phase_timings(records))
        for malformed in (
                records.replace("phase=replay", "phase=teardown"),
                records.replace("elapsed_ms=45", "elapsed_ms=04"),
                records.replace("phase=fixture", "phase=/private/name"),
                records * 161):
            with self.subTest(malformed=malformed[:40]):
                self.assertIsNone(
                    runner.parse_owned_pair_phase_timings(malformed))

    def test_loaded_mapper_inventory_failure_preserves_source_category(self):
        for source, status in (("dmsetup", 2), ("record_parser", 2)):
            observation = (f"LOADED_MAPPER_INVENTORY_SOURCE={source} "
                           f"status={status}\n")
            self.assertEqual(
                runner.parse_loaded_mapper_inventory_failure(observation),
                {"source": source, "exit_code": status})
        for invalid in (
                "",
                "LOADED_MAPPER_INVENTORY_SOURCE=dmsetup status=0\n",
                "LOADED_MAPPER_INVENTORY_SOURCE=dmsetup status=002\n",
                "LOADED_MAPPER_INVENTORY_SOURCE=dmsetup status=256\n",
                "LOADED_MAPPER_INVENTORY_SOURCE=arbitrary status=2\n",
                "LOADED_MAPPER_INVENTORY_SOURCE=dmsetup status=2 "
                "device=/private/path\n",
                "LOADED_MAPPER_INVENTORY_SOURCE=dmsetup status=2\n" * 2):
            with self.subTest(invalid=invalid[:40]):
                self.assertIsNone(
                    runner.parse_loaded_mapper_inventory_failure(invalid))

    def test_primary_lifecycle_case_timings_require_source_allowlist(self):
        first = (
            "PRIMARY_LIFECYCLE_CASE_TIMING index=0 elapsed_ms=21 "
            "class=PrimaryLifecycleBehaviorTest "
            "method=test_active_requires_exact_kernel_inventory_proof\n")
        second = (
            "PRIMARY_LIFECYCLE_CASE_TIMING index=1 elapsed_ms=1300 "
            "class=PrimaryLifecycleBehaviorTest "
            "method=test_duplicate_start_is_rejected\n")
        expected = [
            {"class": "PrimaryLifecycleBehaviorTest",
             "method": "test_active_requires_exact_kernel_inventory_proof",
             "elapsed_ms": 21},
            {"class": "PrimaryLifecycleBehaviorTest",
             "method": "test_duplicate_start_is_rejected",
             "elapsed_ms": 1300},
        ]
        self.assertEqual(
            runner.parse_primary_lifecycle_case_timings(first + second),
            expected)
        self.assertIsNone(runner.parse_primary_lifecycle_case_timings(""))
        for malformed in (
                first + first,
                first + first.replace("index=0", "index=1"),
                second,
                first.replace("elapsed_ms=21", "elapsed_ms=021"),
                first.replace("class=PrimaryLifecycleBehaviorTest",
                              "class=private_path"),
                first.replace(
                    "method=test_active_requires_exact_kernel_inventory_proof",
                    "method=test_not_in_source"),
                (first + second) * 1025):
            with self.subTest(malformed=malformed[:54]):
                self.assertIsNone(
                    runner.parse_primary_lifecycle_case_timings(malformed))

    def test_primary_lifecycle_timing_coverage_distinguishes_missing_and_partial(self):
        methods = runner.primary_lifecycle_source_case_methods()
        self.assertIsNotNone(methods)
        self.assertGreater(len(methods), 2)
        label = ("class=PrimaryLifecycleBehaviorTest "
                 "method=test_active_requires_exact_kernel_inventory_proof")
        first = "PRIMARY_LIFECYCLE_CASE_TIMING index=0 elapsed_ms=10 " + label + "\n"
        self.assertEqual(
            runner.primary_lifecycle_case_timing_coverage("", None)["status"],
            "MISSING")
        self.assertEqual(
            runner.primary_lifecycle_case_timing_coverage(first, None)["status"],
            "REJECTED")
        partial = runner.parse_primary_lifecycle_case_timings(first)
        self.assertEqual(
            runner.primary_lifecycle_case_timing_coverage(
                first, partial)["status"], "PARTIAL")
        complete = "".join(
            f"PRIMARY_LIFECYCLE_CASE_TIMING index={index} elapsed_ms=2 "
            f"class={class_name} method={method_name}\n"
            for index, (class_name, method_name)
            in enumerate(sorted(methods)))
        captured = runner.parse_primary_lifecycle_case_timings(complete)
        self.assertEqual(len(captured), len(methods))
        self.assertEqual(
            runner.primary_lifecycle_case_timing_coverage(
                complete, captured)["status"], "COMPLETE")

    def test_primary_lifecycle_case_timing_writer_survives_stdout_redirection(self):
        import sys
        from unittest import mock

        audit_path = ROOT / "tests/runtime/native/primary-lifecycle-audit-test.py"
        audit_spec = importlib.util.spec_from_file_location(
            "swapz_rootless_audit_timing_fixture", audit_path)
        audit = importlib.util.module_from_spec(audit_spec)
        with mock.patch.dict(sys.modules, {audit_spec.name: audit}):
            audit_spec.loader.exec_module(audit)

        class FastCase(unittest.TestCase):
            def test_fast(self):
                pass

            def test_redirected(self):
                with contextlib.redirect_stdout(io.StringIO()):
                    pass

        test_suite = unittest.TestSuite([
            FastCase("test_fast"), FastCase("test_redirected")])
        progress_stream = io.StringIO()
        with mock.patch.object(audit.os, "write",
                               side_effect=AssertionError("unexpected fd write")), \
                contextlib.redirect_stdout(io.StringIO()):
            completed = audit.PrimaryLifecycleTimingRunner(
                stream=progress_stream, verbosity=2).run(test_suite)
        self.assertTrue(completed.wasSuccessful())
        progress_lines = progress_stream.getvalue().splitlines()
        markers = [line for line in progress_lines
                   if line.startswith("PRIMARY_LIFECYCLE_CASE_TIMING ")]
        self.assertEqual(len(markers), 2)
        for index, marker in enumerate(markers):
            self.assertRegex(
                marker,
                rf"^PRIMARY_LIFECYCLE_CASE_TIMING index={index} "
                r"elapsed_ms=[0-9]+ class=FastCase "
                rf"method=test_{'fast' if index == 0 else 'redirected'}$")
            marker_position = progress_lines.index(marker)
            self.assertTrue(
                progress_lines[marker_position - 1].endswith(" ... ok"))

        source_cases = frozenset({
            ("FastCase", "test_fast"), ("FastCase", "test_redirected")})
        with mock.patch.object(runner, "primary_lifecycle_source_case_methods",
                               return_value=source_cases):
            timings = runner.parse_primary_lifecycle_case_timings(
                progress_stream.getvalue())
            self.assertEqual(len(timings), 2)
            self.assertEqual(
                runner.primary_lifecycle_case_timing_coverage(
                    progress_stream.getvalue(), timings)["status"], "COMPLETE")

    def test_owned_pair_phase_coverage_handles_redirection_and_rejection(self):
        records = "".join(
            f"OWNED_PAIR_PHASE_TIMING phase={phase} elapsed_ms={index + 3}\n"
            for index, phase in enumerate(
                ("setup", "fixture", "replay", "verification", "teardown")))
        parsed = runner.parse_owned_pair_phase_timings(records * 2)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["pair_index"], 0)
        self.assertEqual(parsed[1]["pair_index"], 1)

    def test_rootless_audit_case_marker_reaches_stage_evidence(self):
        from unittest import mock

        phase = "tests/runtime/native/primary-lifecycle-audit-test.py"
        marker = (
            "PRIMARY_LIFECYCLE_CASE_TIMING index=0 elapsed_ms=17 "
            "class=PrimaryLifecycleBehaviorTest "
            "method=test_active_requires_exact_kernel_inventory_proof\n")
        transcript = (
            "ROOTLESS_PHASE_PROGRESS state=START index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            "ROOTLESS_PHASE_PROGRESS state=PASS index=0 elapsed_s=0 "
            "label=rootless initialization\n"
            f"ROOTLESS_PHASE_PROGRESS state=START index=1 elapsed_s=0 "
            f"label={phase}\n" +
            marker +
            f"ROOTLESS_PHASE_PROGRESS state=PASS index=1 elapsed_s=1 "
            f"label={phase}\n")
        result = {"stages": [], "benchmarks": {}}
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript)), \
                contextlib.redirect_stdout(io.StringIO()):
            runner.run_stage(
                "Native and rootless contracts", ["unused"], result,
                stream_rootless_progress=True)
        stage = result["stages"][-1]
        self.assertEqual(
            stage["primary_lifecycle_case_elapsed_ms"],
            [{"class": "PrimaryLifecycleBehaviorTest",
              "method": "test_active_requires_exact_kernel_inventory_proof",
              "elapsed_ms": 17}])
        self.assertEqual(
            stage["primary_lifecycle_case_timing_coverage"]["status"],
            "PARTIAL")
        self.assertEqual(
            stage["primary_lifecycle_case_timing_coverage"]["observed_records"],
            1)

    def test_loaded_timing_boundaries_do_not_use_child_supplied_labels(self):
        self.assertEqual(runner.loaded_timing_phase(
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"), "primary-lifecycle")
        self.assertEqual(runner.loaded_timing_phase(
            "START_STORAGE_ENVELOPE=nvme_gen5\n"), "storage-nvme-gen5")
        self.assertEqual(runner.loaded_timing_phase(
            "PASS_WRITE_SATURATION_REGIME=ssd_emulated\n"), "id36-pressure")
        self.assertIsNone(runner.loaded_timing_phase(
            "ROOTLESS_PHASE_TIMING index=1 label=/private/secret"))
        self.assertIsNone(runner.loaded_timing_phase(
            "START_LOADED_PRIMARY_NULLBLK_NEGATIVE=stale-run-id"))

    def test_failed_loaded_phase_timing_never_grants_qualification(self):
        from unittest import mock

        transcript = (
            "LOADED_QUALIFICATION_SOURCE=" + "a" * 40 + "\n"
            "START_LOADED_MAXIMUM_CAPACITY\n"
            "START_LOADED_GC_ROLL_FORWARD_RECOVERY\n"
            "FAIL: synthetic qualification failure\n")
        result = {"tested_commit_sha": "a" * 40, "stages": [],
                  "benchmarks": {}}
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=1)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertNotEqual(
                runner.run_stage("Owned RAM smoke + mixed/QD pilot", ["unused"],
                                 result, parse_bench=True), 0)
        stage = result["stages"][-1]
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(
            [phase["name"] for phase in stage["phase_elapsed_s"]],
            ["preflight", "kernel-debug-config", "maximum-capacity",
             "gc-roll-forward"])
        self.assertLessEqual(
            sum(phase["elapsed_s"] for phase in stage["phase_elapsed_s"]),
            stage["elapsed_s"] + 0.005)

    def test_rootless_timing_is_observational_and_rejects_ambiguous_records(self):
        valid = "ROOTLESS_TIMING native_make_s=12 remaining_contracts_s=34\n"
        self.assertEqual(
            runner.parse_rootless_timing(valid),
            {"native_make_s": 12, "remaining_contracts_s": 34})
        self.assertIsNone(runner.parse_rootless_timing(""))
        self.assertIsNone(runner.parse_rootless_timing(valid + valid))
        self.assertIsNone(runner.parse_rootless_timing(
            "ROOTLESS_TIMING native_make_s=-1 remaining_contracts_s=34\n"))
        self.assertIsNone(runner.parse_rootless_timing(
            "ROOTLESS_TIMING native_make_s=01 remaining_contracts_s=34\n"))


class FakeStreamingProcess:
    """Minimal Popen-compatible process for streamed loaded-stage tests."""

    def __init__(self, output: str, returncode: int = 0):
        self.stdout = io.StringIO(output)
        self.returncode = returncode

    def wait(self):
        return self.returncode


def predictor_evidence():
    thresholds = []
    profile_pages = {"zero": 32, "repeat": 32,
                     "entropy": 64, "mixed": 64, "medium": 64}
    for threshold in runner.PREDICTOR_THRESHOLDS:
        profiles = []
        for name in runner.PREDICTOR_NEGATIVE_PROFILES:
            eligible = 0 if name in ("zero", "repeat") else profile_pages[name]
            profiles.append({
                "name": name, "pages": profile_pages[name],
                "eligible": eligible, "calls": 0, "useful": 0,
            })
        thresholds.append({
            "threshold": threshold,
            "negative_eligible": sum(item["eligible"] for item in profiles),
            "negative_calls": 0,
            "negative_useful": 0,
            "structured_eligible": 77,
            "structured_calls": 70,
            "structured_useful": 60,
            "routed_baseline_blocks": 200,
            "routed_candidate_blocks": 165,
            "routed_blocks_saved": 35,
            "routed_baseline_extents": 100,
            "routed_candidate_extents": 85,
            "routed_extents_saved": 15,
            "routed_cpu_ns_total": 2500000,
            "routed_cpu_ns_per_page": 4340,
            "ns_per_saved_block": 71428,
            "negative_profiles": profiles,
        })
    transforms = []
    for index, name in enumerate(runner.PREDICTOR_TRANSFORM_NAMES):
        transforms.append({
            "name": name,
            "adopted": 80 - index,
            "raw_rescued": 20 - index,
            "cliff_2024": 30 - index,
            "saved_payload_bytes": 100000 - index * 1000,
            "baseline_blocks": 200,
            "candidate_blocks": 160 + index,
            "planner_blocks_saved": 40 - index,
            "baseline_extents": 100,
            "candidate_extents": 80 + index,
            "planner_extents_saved": 20 - index,
            "transform_backend": "avx2",
            "inverse_backend": "sse2",
            "transform_ns_per_page": 1000 + index * 100,
            "inverse_ns_per_page": 900 + index * 100,
            "scalar_transform_ns_per_page": 1400 + index * 100,
            "scalar_inverse_ns_per_page": 1300 + index * 100,
            "second_lz4_ns_per_page": 5000 + index * 100,
        })
    return {
        "scope": "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY",
        "negative_pages": sum(profile_pages.values()),
        "structured_pages": 320,
        "classifier": {
            "candidate": "delta64",
            "backend": "scalar",
            "sample_pairs": 32,
            "stage1_pairs": 8,
            "stage1_min_score": 2,
            "eligible_pages": 269,
            "early_abort_pages": 120,
            "benchmark_repeats": 256,
            "benchmark_calls": 68864,
            "ns_per_page": 55,
            "scalar_ns_per_page": 70,
        },
        "lz4_acceleration_sweep": [
            {
                "acceleration": acceleration,
                "wall_ns_per_page": 1000 // acceleration,
                "accepted_payload_bytes": 10000 + acceleration,
                "raw_pages": 12,
                "planner_blocks": 20,
                "planner_extents": 16,
            }
            for acceleration in runner.LZ4_ACCELERATIONS
        ],
        "sampling_controls": [
            {"name": "repeated_512b_headers", "score": 32,
             "minimum_score": 24},
            {"name": "lane1_only_signal", "score": 32,
             "minimum_score": 16},
        ],
        "backend_benchmarks": [
            {"name": "scalar", "transform_ns_per_page": 700,
             "inverse_ns_per_page": 650},
            {"name": "sse2", "transform_ns_per_page": 430,
             "inverse_ns_per_page": 550},
            {"name": "avx2", "transform_ns_per_page": 300,
             "inverse_ns_per_page": 600},
        ],
        "sse2_forward_ab": {
            "scope": "SAME_HOST_NATIVE_BASELINE_VS_PROMOTED_PRODUCTION",
            "pages": 576,
            "repeats_per_arm": 64,
            "pairs": [
                {
                    "order": "unrolled_first" if index % 2 else "baseline_first",
                    "baseline_ns_per_page": 300 + index,
                    "unrolled_ns_per_page": 287 + index,
                }
                for index in range(5)
            ],
        },
        "io_model_block_ns": {"sd_emulated": 390625, "ssd_emulated": 48828},
        "thresholds": thresholds,
        "transforms": transforms,
        "production_route": {
            "scope": "OFFLINE_NATIVE_ONLY_NOT_KERNEL_POLICY",
            "general_threshold": 24,
            "packing_threshold": 16,
            "eligible_pages": 269,
            "packing_eligible_pages": 20,
            "classifier_passes": 100,
            "candidate_attempts": 100,
            "adopted_pages": 80,
            "raw_rescues": 20,
            "lz4_rescues": 60,
            "packing_adoptions": 10,
            "payload_bytes_saved": 10000,
            "baseline_blocks": 400,
            "candidate_blocks": 350,
            "blocks_saved": 50,
            "baseline_extents": 200,
            "candidate_extents": 180,
            "extents_saved": 20,
            "modeled_wall_ns_total": 2500000,
            "modeled_wall_ns_per_page": 4340,
            "ns_per_saved_block": 50000,
        },
    }


def gc_scan_scale_evidence():
    return {
        "scope": "OFFLINE_NATIVE_GC_SCALE_ONLY",
        "rows": [
            {
                "logical_pages": 262144, "segments": 1024,
                "legacy_score_scan_ns": 2000000,
                "incremental_select_ns": 20000,
                "relocation_scan_ns": 800000,
                "relocation_list_ns": 4000,
                "legacy_dead_probe_ns": 700000,
                "mapped_dead_probe_ns": 12000,
                "victim_records": 256,
            },
            {
                "logical_pages": 1048576, "segments": 4096,
                "legacy_score_scan_ns": 8000000,
                "incremental_select_ns": 80000,
                "relocation_scan_ns": 3200000,
                "relocation_list_ns": 4500,
                "legacy_dead_probe_ns": 2800000,
                "mapped_dead_probe_ns": 15000,
                "victim_records": 256,
            },
            {
                "logical_pages": 4194304, "segments": 16384,
                "legacy_score_scan_ns": 32000000,
                "incremental_select_ns": 320000,
                "relocation_scan_ns": 12800000,
                "relocation_list_ns": 4600,
                "legacy_dead_probe_ns": 11200000,
                "mapped_dead_probe_ns": 60000,
                "victim_records": 256,
            },
            {
                "logical_pages": 27080192, "segments": 105782,
                "legacy_score_scan_ns": 200000000,
                "incremental_select_ns": 2000000,
                "relocation_scan_ns": 80000000,
                "relocation_list_ns": 5000,
                "legacy_dead_probe_ns": 70000000,
                "mapped_dead_probe_ns": 100000,
                "victim_records": 256,
            },
        ],
    }


def extent_geometry_evidence():
    return {
        "scope": "OFFLINE_NATIVE_GEOMETRY_ONLY_NOT_FORMAT_POLICY",
        "logical_pages": 1024,
        "normal_windows": 64,
        "rows": [
            {"name": "aligned_1_2_4", "physical_blocks": 320,
             "waste_blocks": 24, "write_runs": 80,
             "cold_read_blocks_x1000": 1800, "seq_4m_requests": 1500},
            {"name": "packed_1_2_4", "physical_blocks": 320,
             "waste_blocks": 4, "write_runs": 60,
             "cold_read_blocks_x1000": 1800, "seq_4m_requests": 1500},
            {"name": "packed_1_2_3_4", "physical_blocks": 300,
             "waste_blocks": 3, "write_runs": 55,
             "cold_read_blocks_x1000": 1750, "seq_4m_requests": 1450},
            {"name": "packed_1_2_4_8", "physical_blocks": 292,
             "waste_blocks": 2, "write_runs": 48,
             "cold_read_blocks_x1000": 1900, "seq_4m_requests": 1300},
            {"name": "packed_1_2_4_8_16", "physical_blocks": 288,
             "waste_blocks": 1, "write_runs": 44,
             "cold_read_blocks_x1000": 2150, "seq_4m_requests": 1200},
        ],
    }


def lower_inflight(*, has_reads):
    read_peak = 1 if has_reads else 0
    read_mean = 0.25 if has_reads else 0.0
    write_mean = 0.50
    return {
        "target_interval_ns": 500000,
        "samples": 4000,
        "read_start": 0,
        "write_start": 0,
        "read_end": 0,
        "write_end": 0,
        "read_peak": read_peak,
        "write_peak": 1,
        "total_peak": 1,
        "read_time_weighted": read_mean,
        "write_time_weighted": write_mean,
        "total_time_weighted": read_mean + write_mean,
    }


def timed_kernel_write(*, mode, target=8):
    record = {field: 0 for field in runner.KERNEL_WRITE_FIELDS}
    record.update({
        "physical_write_reqs": 5,
        "lz4_acceleration": 1,
        "delta64_lz4_acceleration": runner.PRODUCTION_DELTA64_LZ4_ACCELERATION,
        "delta64_prepare_workers": 1,
        "write_pipeline_depth": 1,
        "pipeline_active_max": 1 if mode else 0,
        "k1_allow_after_read_bypass": 0,
        "read_coalesce_max_blocks": 8,
        "invalidate_cache_on_write_admit": 0,
        "work_conserving_hand_records":
            runner.PRODUCTION_WORK_CONSERVING_HAND_RECORDS,
        "delta64_rescue": 1,
        "delta64_eligible": 10,
        "delta64_classifier_pass": 5,
        "delta64_attempts": 5,
        "delta64_adopted": 3,
        "delta64_raw_rescues": 1,
        "delta64_lz4_rescues": 2,
        "delta64_pack_eligible": 4,
        "delta64_pack_attempts": 1,
        "delta64_pack_cliff_crossings": 1,
        "delta64_pack_adopted": 1,
        "delta64_score_0_7": 2,
        "delta64_score_8_15": 2,
        "delta64_score_16_23": 2,
        "delta64_score_ge24": 4,
        "delta64_raw_payload_bytes_saved": 1000,
        "delta64_lz4_payload_bytes_saved": 200,
        "delta64_payload_bytes_saved": 1200,
        "delta64_wall_ns": 50000,
        "lz4_wall_ns": 20000000,
        "ordered_lz4_wall_ns": 15000000,
        "prep_lz4_wall_ns": 5000000,
        "write_copy_wall_ns": 3000000,
        "write_copy_bytes": 6000000,
        "ordered_write_copy_wall_ns": 2000000,
        "prep_write_copy_wall_ns": 1000000,
        "direct_lz4_input_pages": 3000,
        "mapped_snapshot_input_pages": 1000,
        "window_sort_wall_ns": 1000000,
        "window_commit_wall_ns": 40000000,
        "window_commit_nonio_wall_ns": 10000000,
        "engine_plan_wall_ns": 1000000,
        "engine_pack_wall_ns": 2000000,
        "engine_publish_wall_ns": 3000000,
        "engine_publish_crc_wall_ns": 1000000,
        "engine_publish_auth_wall_ns": 2000000,
        "engine_prehashed_records": 2500,
        "batch_snapshot_crc_wall_ns": 250000,
        "batch_pause_crc_wall_ns": 100000,
        "batch_resume_crc_wall_ns": 150000,
        "prep_crc_wall_ns": 700000,
        "ordered_crc_wall_ns": 1300000,
        "lower_write_wall_ns": 30000000,
        "ordered_worker_wall_ns": 52000000,
        "prep_worker_wall_ns": 5000000,
        "ordered_worker_cpu_ns": 16000000,
        "prep_worker_cpu_ns": 3000000,
        "read_worker_cpu_ns": 1000000,
        "prep_wait_wall_ns": 500000,
        "prep_lower_write_overlap_ns": 5000000,
        "prep_lower_read_overlap_ns": 0,
        "prep_lower_write_samples": 5,
        "prep_lower_write_start_queued": 4,
        "prep_lower_write_start_nonempty": 3,
        "prep_lower_write_end_queued": 1,
        "prep_lower_write_end_nonempty": 1,
        "pipeline_async_runs": 4 if mode else 0,
        "pipeline_read_bypass_skips": 3 if mode else 0,
        "pipeline_active_wall_ns": 800000000 if mode else 0,
        "pipeline_post_lower_wall_ns": 8000000 if mode else 0,
        "pipeline_finalize_wait_wall_ns": 5000000 if mode else 0,
        "k1_ready_wait_windows": 2 if mode else 0,
        "k1_ready_wait_records": 12 if mode else 0,
        "k1_ready_wait_wall_ns": 4000000 if mode else 0,
        "k1_ready_wait_max_records": 8 if mode else 0,
        "k1_ready_wait_pack_ready": 2 if mode else 0,
        "write_wait_le1ms": 2,
        "write_wait_1to4ms": 2,
        "write_wait_gt4ms": 1,
        "retained_burst_target": target,
        "windows": 20,
        "one_page_windows": 4,
        "win1": 4,
        "win3_4": 8,
        "win5_8": 8,
        "close_idle": 4,
        "close_deadline": 2,
        "close_pack_ready": 14,
        "pack_close_tail_target": 5,
        "pack_close_tail_target_le4": 4,
        "pack_close_burst_target": 6,
        "pack_close_service_dry": 3,
        "pack_close_burst_admission": 4,
        "pack_close_burst_worker": 2,
        "pack_close_burst_target_le4": 2,
        "pack_close_burst_target_5_8": 4,
        "pack_close_burst_count_le4": 1,
        "pack_close_burst_count_5_8": 5,
        "pack_close_burst_overshoot": 1,
        "pack_tail_samples": 6,
        "pack_tail_zero_inflight": 2 if mode else 0,
        "pack_tail_zero_idle": 1 if mode else 2,
        "pack_tail_one_inflight": 1 if mode else 0,
        "pack_tail_one_idle": 0 if mode else 1,
        "pack_tail_many_inflight": 1 if mode else 0,
        "pack_tail_many_idle": 1 if mode else 3,
        "burst_target_grows": 3 if mode else 2,
        "burst_target_shrinks": 2 if mode else 1,
        "burst_shrink_inflight_zero_skips": 2 if mode else 0,
        "burst_shrink_after_inflight_zero": 0,
        "burst_shrink_after_read_bypass": 0,
        "burst_shrink_other": 2 if mode else 1,
        "burst_shrink_target_le8": 1 if mode else 0,
        "burst_shrink_target_9_32": 1,
        "burst_shrink_target_gt32": 0,
        "win1_idle": 1,
        "win1_deadline": 2,
        "win1_pack_ready": 1,
        "win1_pack_tail_target": 1,
        "win1_pack_read_bypass": 0,
        "win1_pack_wave_interrupted": 0,
        "deadline_before_bio": 1,
        "deadline_worker_empty": 1,
        "packed_early_commits": 8,
        "single_pack_deferrals": 24,
        "accepted_burst_extensions": 6,
        "accepted_burst_tail_flushes": 5,
        "accepted_burst_read_caps": 4,
        "prep_lower_write_overlap_starts": 42 if mode else 0,
        "prep_lower_read_overlap_starts": 0,
        "prep_wave_kicks": 5 if mode else 0,
        "prep_producer_head_claims": 2 if mode else 0,
        "prep_producer_tail_claims": 3 if mode else 0,
        "prep_ordered_inline": 4 if mode else 0,
        "prep_ordered_handoffs": 3 if mode else 0,
        "prep_ordered_waits": 1 if mode else 0,
    })
    return record


def standard_kernel_write(*, mode, target=8):
    """Standard loaded benchmark policy: LZ4 accel 1, production delta64 default."""
    record = timed_kernel_write(mode=mode, target=target)
    record["delta64_rescue"] = runner.PRODUCTION_DELTA64_RESCUE
    for field in runner.DELTA64_FIELDS:
        record[field] = 0
    return record


def arm(candidate, *, mode, regime):
    swapz = candidate == "swapz"
    raw_mbps = 14 if regime == "sd_emulated" else 32
    cand_mbps = (20 if mode == 0 else 20.01) if regime == "sd_emulated" else (
        24 if mode == 0 else 24.01)
    raw_read_time = 1.0
    packed = {
        "logical_bytes": 4194304,
        "logical_image_sha256": "d" * 64,
        "packed_close_delta": 4 if swapz else None,
        "qualification": ("OWNED_PACK_READY_AND_VERIFIED_4MIB_READ" if swapz
                          else "ROOTLESS_NO_PACK_PROOF"),
        "passes": {
            key: {
                "logical_bytes": 4194304,
                "verified_pages": 1024,
                "verified_image_sha256": "d" * 64,
                "seconds": raw_read_time * (0.9 if swapz else 1.),
                "useful_read_mbps": 4.19 if not swapz else 4.65,
                "read_p99_ms": 2 if swapz else 3,
                "lower_io": {
                    "lower_read_bytes": 6291456 if swapz else 4194304,
                    "lower_read_requests": 1536 if swapz else 1024,
                },
                "kernel_read_path": ({
                    "read_meta_reqs": 1024,
                    "read_payload_reqs": 512,
                    "read_payload_blocks": 512,
                    "lower_read_wall_ns": 120000000,
                    "decode_wall_ns": 20000000,
                    "read_copy_wall_ns": 4000000,
                    "read_copy_bytes": 4194304,
                    "read_engine_nonio_wall_ns": 6000000,
                    "read_meta_cache_hits": 128,
                    "read_meta_lru_hits": 100,
                    "read_meta_set_lookups": 1024,
                    "read_meta_set_hits": 100,
                    "read_meta_primary_hits": 80,
                    "read_meta_secondary_hits": 20,
                    "read_meta_set_probes": 7700,
                    "read_meta_set_replacements": 12,
                    "read_meta_copy_bytes": 207200,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                    "parallel_read_pairs": 128,
                    "parallel_read_same_extent_pairs": 64,
                    "parallel_read_async_batches": 32,
                    "parallel_read_async_slots": 64,
                    "parallel_read_distinct_extent_pairs": 64,
                    "parallel_read_adjacent_extent_pairs": 24,
                    "parallel_read_adjacent_extent_blocks": 144,
                    "parallel_read_adjacent_chain_3plus": 0,
                    "parallel_read_adjacent_chain_extent_max": 0,
                    "parallel_read_adjacent_chain_blocks_max": 0,
                    "parallel_read_coalesced_pairs": 20,
                    "parallel_read_coalesced_reqs_saved": 20,
                    "parallel_read_coalesced_blocks": 80,
                    "parallel_read_coalesce_extra_blocks": 0,
                    "parallel_read_coalesce_skip_cached": 1,
                    "parallel_read_coalesce_skip_noncontig_slot": 2,
                    "parallel_read_coalesce_skip_gap": 1,
                    "parallel_read_coalesce_skip_other": 0,
                    "read_worker_cpu_ns": 1000000,
                    "read_coalesce_max_blocks": 8,
                } if swapz else None),
                "replay_cpu_user_s": .15,
                "replay_cpu_system_s": .12,
                "replay_peak_rss_kb": 12000,
            }
            for key in ("sequential", "seeded_random")
        },
    }
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64, "trace_sha256": "c" * 64,
        "device_identity": {"device": "PRIVATE_DEVICE_MUST_NOT_ESCAPE"},
        "throughput_mbps": {
            "logical_write_mbps": cand_mbps if swapz else raw_mbps,
            "lower_write_mbps": 12 if swapz else 14,
            "logical_read_mbps": 7 if swapz else 4,
            "logical_write_bytes": 8000, "logical_read_bytes": 4000,
        },
        "lower_io": {
            "lower_write_bytes": 5000 if swapz else 8000,
            "lower_read_bytes": 4000,
            "lower_write_requests": 5 if swapz else 8,
            "lower_read_requests": 4,
        },
        "read_p95_ns": 4000000 if swapz else 8000000,
        "read_p99_ns": 5000000 if swapz else 10000000,
        "write_p99_ns": 2000000,
        "seconds": 2, "verified_pages": 1024,
        "mixed_replay_cpu_user_s": .12,
        "mixed_replay_cpu_system_s": .08,
        "mixed_replay_peak_rss_kb": 12000,
        "host_cpu": {
            "status": "AVAILABLE", "wall_ns": 2_000_000_000,
            "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
            "busy_fraction": 0.50, "steal_fraction": 0.0,
            "pressure_some_fraction": 0.10,
        },
        "lower_inflight": lower_inflight(has_reads=True),
        "workload_opportunity": {
            "scope": "TRACE_FIXTURE_OPPORTUNITY_ONLY_NOT_KERNEL_SAVINGS",
            "measured_write_ops": 100,
            "measured_unique_write_payloads": 20,
            "nonzero_same_filled_write_ops": 5,
            "same_page_rewrite_ops": 7,
            "resident_duplicate_write_ops": 30,
            "final_live_unique_payloads": 18,
            "final_live_duplicate_pages": 40,
            "final_live_nonzero_same_filled_pages": 3,
        },
        "packed_read": packed,
        "kernel_write_path": (standard_kernel_write(mode=mode, target=8)
                              if swapz else None),
        "kernel_read_path": (
            dict(packed["passes"]["sequential"]["kernel_read_path"])
            if swapz else None),
    }



def parallel_arm(enabled, regime="ssd_emulated"):
    record = arm("swapz", mode=0, regime=regime)
    for phase in record["packed_read"]["passes"].values():
        kernel = phase["kernel_read_path"]
        if regime == "sd_emulated":
            kernel["read_worker_cpu_ns"] = 0
        if not enabled:
            for field in (
                    "parallel_read_pairs", "parallel_read_same_extent_pairs",
                    "parallel_read_async_batches", "parallel_read_async_slots",
                    "parallel_read_distinct_extent_pairs",
                    "parallel_read_adjacent_extent_pairs",
                    "parallel_read_adjacent_extent_blocks"):
                kernel[field] = 0
        else:
            kernel["parallel_read_pairs"] = 128
            kernel["parallel_read_same_extent_pairs"] = 64
            kernel["parallel_read_async_batches"] = 32
            kernel["parallel_read_async_slots"] = 64
        for field in (
                "parallel_read_coalesced_pairs",
                "parallel_read_coalesced_reqs_saved",
                "parallel_read_coalesced_blocks",
                "parallel_read_coalesce_extra_blocks",
                "parallel_read_coalesce_skip_cached",
                "parallel_read_coalesce_skip_noncontig_slot",
                "parallel_read_coalesce_skip_gap",
                "parallel_read_coalesce_skip_other"):
            kernel[field] = 0
    return record


def fanout_arm(enabled):
    record = parallel_arm(enabled, regime="ssd_emulated")
    mixed_kernel = record["kernel_read_path"]
    source_kernel = record["packed_read"]["passes"]["sequential"]["kernel_read_path"]
    mixed_kernel.clear()
    mixed_kernel.update(source_kernel)

    # This final decision forces ID63 off. Preserve independent fan-out only.
    coalesce_fields = (
        "parallel_read_adjacent_extent_pairs",
        "parallel_read_adjacent_extent_blocks",
        "parallel_read_adjacent_chain_3plus",
        "parallel_read_adjacent_chain_extent_max",
        "parallel_read_adjacent_chain_blocks_max",
        "parallel_read_coalesced_pairs",
        "parallel_read_coalesced_reqs_saved",
        "parallel_read_coalesced_blocks",
        "parallel_read_coalesce_extra_blocks",
        "parallel_read_coalesce_skip_cached",
        "parallel_read_coalesce_skip_noncontig_slot",
        "parallel_read_coalesce_skip_gap",
        "parallel_read_coalesce_skip_other",
    )
    for kernel in [mixed_kernel] + [
            phase["kernel_read_path"]
            for phase in record["packed_read"]["passes"].values()]:
        for field in coalesce_fields:
            kernel[field] = 0

    if enabled:
        mixed_kernel["parallel_read_pairs"] = 96
        mixed_kernel["parallel_read_same_extent_pairs"] = 0
        mixed_kernel["parallel_read_async_batches"] = 48
        mixed_kernel["parallel_read_async_slots"] = 144
        mixed_kernel["parallel_read_distinct_extent_pairs"] = 96
        record["throughput_mbps"]["logical_write_mbps"] = 25.0
        record["throughput_mbps"]["logical_read_mbps"] = 7.8
        record["read_p99_ns"] = 4_000_000
        record["lower_io"]["lower_read_requests"] = 3
        for phase in record["packed_read"]["passes"].values():
            phase["useful_read_mbps"] *= 1.05
            phase["read_p99_ms"] *= .95
    else:
        for field in ("parallel_read_pairs", "parallel_read_same_extent_pairs",
                      "parallel_read_async_batches", "parallel_read_async_slots",
                      "parallel_read_distinct_extent_pairs"):
            mixed_kernel[field] = 0
        record["throughput_mbps"]["logical_write_mbps"] = 24.0
        record["throughput_mbps"]["logical_read_mbps"] = 7.0
        record["read_p99_ns"] = 5_000_000
        record["lower_io"]["lower_read_requests"] = 4
    return record


def coalesce_arm(enabled, regime="ssd_emulated"):
    record = parallel_arm(enabled, regime=regime)
    for mode, phase in record["packed_read"]["passes"].items():
        kernel = phase["kernel_read_path"]
        if enabled:
            kernel["parallel_read_coalesced_pairs"] = (
                20 if mode == "sequential" else 2)
            kernel["parallel_read_coalesced_reqs_saved"] = (
                kernel["parallel_read_coalesced_pairs"])
            kernel["parallel_read_coalesced_blocks"] = (
                80 if mode == "sequential" else 8)
            if mode == "sequential":
                kernel["parallel_read_coalesce_skip_cached"] = 1
                kernel["parallel_read_coalesce_skip_noncontig_slot"] = 2
                kernel["parallel_read_coalesce_skip_gap"] = 1
            else:
                kernel["parallel_read_coalesce_skip_cached"] = 8
                kernel["parallel_read_coalesce_skip_noncontig_slot"] = 10
                kernel["parallel_read_coalesce_skip_gap"] = 4
            phase["lower_io"]["lower_read_requests"] -= (
                kernel["parallel_read_coalesced_reqs_saved"])
            phase["read_p99_ms"] *= .95
    return record


def k1_read_bypass_arm(allow, regime):
    record = arm("swapz", mode=1, regime=regime)
    kernel = record["kernel_write_path"]
    kernel["k1_allow_after_read_bypass"] = allow
    kernel["read_coalesce_max_blocks"] = 8
    kernel["invalidate_cache_on_write_admit"] = 0
    kernel["pipeline_read_bypass_skips"] = 3 if not allow else 0
    record["fixture_sha256"] = "1" * 64
    record["trace_sha256"] = "2" * 64
    return record


def read_coalesce_cap_arm(cap, regime):
    record = coalesce_arm(True, regime=regime)
    for phase in record["packed_read"]["passes"].values():
        phase["kernel_read_path"]["read_coalesce_max_blocks"] = cap
    record["fixture_sha256"] = "3" * 64
    record["trace_sha256"] = "4" * 64
    return record


def write_arm(candidate, *, qd, regime, mode):
    swapz = candidate == "swapz"
    raw = 8.0 if regime == "sd_emulated" else 20.0
    swapz_rate = raw * (0.72 + qd / 200.0)
    logical = 4096 * 4096
    lower = int(logical / 1.40) if swapz else logical
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64,
        "trace_sha256": (f"{qd:x}" * 64)[:64],
        "replay_mode": "persistent-write",
        "throughput_mbps": {
            "logical_write_mbps": swapz_rate if swapz else raw,
            "lower_write_mbps": (swapz_rate / 1.40) if swapz else raw,
            "logical_read_mbps": 0.0,
            "logical_write_bytes": logical,
            "logical_read_bytes": 0,
        },
        "lower_io": {
            "lower_write_bytes": lower,
            "lower_write_requests": 1600 if swapz else 4096,
            "lower_read_bytes": 0,
            "lower_read_requests": 0,
        },
        "write_p99_ns": 2500000 if swapz else 1500000,
        "seconds": 2.0,
        "mixed_replay_cpu_user_s": .12,
        "mixed_replay_cpu_system_s": .08,
        "mixed_replay_peak_rss_kb": 12000,
        "host_cpu": {
            "status": "AVAILABLE", "wall_ns": 2_000_000_000,
            "online_cpus": 4, "affinity_cpus": 4, "tick_hz": 100,
            "busy_fraction": 0.50, "steal_fraction": 0.0,
            "pressure_some_fraction": 0.10,
        },
        "lower_inflight": lower_inflight(has_reads=False),
        "kernel_write_path": (standard_kernel_write(
            mode=mode, target=max(4, qd)) if swapz else None),
    }

def delta64_prepare_arm(workers):
    record = write_arm("swapz", qd=32, regime="ssd_emulated", mode=1)
    kernel = record["kernel_write_path"]
    kernel.update({
        "delta64_rescue": 1,
        "delta64_prepare_workers": workers,
        "delta64_prepare_active_max": workers,
        "delta64_prepare_pages": 100,
        "delta64_prepare_parallel_starts": 0 if workers == 1 else 20,
        "delta64_eligible": 100,
        "delta64_classifier_pass": 100,
        "delta64_attempts": 100,
        "delta64_adopted": 100,
        "delta64_raw_rescues": 0,
        "delta64_lz4_rescues": 100,
        "delta64_pack_eligible": 0,
        "delta64_pack_attempts": 0,
        "delta64_pack_cliff_crossings": 0,
        "delta64_pack_adopted": 0,
        "delta64_score_0_7": 0,
        "delta64_score_8_15": 0,
        "delta64_score_16_23": 0,
        "delta64_score_ge24": 100,
        "delta64_payload_bytes_saved": 100000,
        "delta64_raw_payload_bytes_saved": 0,
        "delta64_lz4_payload_bytes_saved": 100000,
        "delta64_transform_calls": 100,
        "delta64_transform_wall_ns": 100000,
        "delta64_wall_ns": 1500000,
    })
    record["throughput_mbps"]["logical_write_mbps"] = 18 + workers
    record["fixture_sha256"] = "e" * 64
    record["trace_sha256"] = "f" * 64
    return record


def write_pipeline_arm(depth):
    record = write_arm("swapz", qd=32, regime="ssd_emulated", mode=1)
    kernel = record["kernel_write_path"]
    kernel["delta64_rescue"] = runner.PRODUCTION_DELTA64_RESCUE
    kernel["write_pipeline_depth"] = depth
    kernel["pipeline_active_max"] = depth
    if depth == 2:
        record["throughput_mbps"]["logical_write_mbps"] *= 1.10
        record["write_p99_ns"] = int(record["write_p99_ns"] * .90)
        record["lower_io"]["lower_write_requests"] = 1500
    record["fixture_sha256"] = "7" * 64
    record["trace_sha256"] = "8" * 64
    return record


def storage_envelope_arm(candidate, *, envelope):
    swapz = candidate == "swapz"
    spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
    cap = spec["cap_mib_s"]
    raw = min(cap, 50.0)
    swapz_rate = raw * 1.1
    logical = 4096 * 4096
    lower = int(logical / 1.5) if swapz else logical
    record = {
        "candidate": candidate,
        "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64,
        "trace_sha256": "c" * 64,
        "replay_engine": "native-c",
        "seconds": 2.0,
        "throughput_mbps": {
            "logical_write_mbps": swapz_rate if swapz else raw,
            "logical_read_mbps": 0.0,
            "logical_write_bytes": logical,
            "logical_read_bytes": 0,
        },
        "lower_io": {
            "lower_write_bytes": lower,
            "lower_write_requests": 1500 if swapz else 4096,
            "lower_read_bytes": 0,
            "lower_read_requests": 0,
        },
        "lower_inflight": {
            "write_peak": 4,
            "write_time_weighted": 2.5,
        },
        "write_p99_ns": 2000000,
    }
    if swapz:
        record["kernel_write_path"] = {
            field: 0 for field in runner.KERNEL_WRITE_FIELDS
        }
        record["kernel_write_path"].update({
            "delta64_rescue": runner.PRODUCTION_DELTA64_RESCUE,
            "delta64_lz4_acceleration":
                runner.PRODUCTION_DELTA64_LZ4_ACCELERATION,
            "lz4_acceleration": 1,
            "work_conserving_hand_records":
                runner.PRODUCTION_WORK_CONSERVING_HAND_RECORDS,
            "prep_lower_write_samples": 10,
            "prep_lower_write_start_queued": 2,
            "prep_lower_write_end_queued": 2,
            "prep_lower_write_start_nonempty": 3,
            "prep_lower_write_end_nonempty": 3,
            "k1_ready_wait_windows": 1,
            "k1_ready_wait_records": 1,
            "k1_ready_wait_max_records": 1,
            "k1_ready_wait_wall_ns": 1000,
            "pipeline_finalize_wait_wall_ns": 2000,
            "pipeline_active_wall_ns": 5000,
            "pipeline_post_lower_wall_ns": 1000,
            "prep_wait_wall_ns": 500,
            "window_commit_nonio_wall_ns": 500,
            "engine_plan_wall_ns": 500,
            "pack_wall_ns": 500,
            "publish_wall_ns": 500,
            "publish_crc32c_wall_ns": 500,
        })
    return record


def lz4_acceleration_log():
    out = []
    spec = runner.MODEL_SPECS["ssd_emulated"]
    sequence = [4 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
    for index, acceleration in enumerate(sequence):
        out.append(f"START_LZ4_ACCELERATION={acceleration}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = arm("off", mode=1, regime="ssd_emulated")
        swapz = arm("swapz", mode=1, regime="ssd_emulated")
        off["throughput_mbps"]["logical_write_mbps"] = 28.0
        swapz["throughput_mbps"]["logical_write_mbps"] = (
            26.0 if acceleration == 1 else 27.0)
        swapz["write_p99_ns"] = 4_000_000 if acceleration == 1 else 3_800_000
        kernel = swapz["kernel_write_path"]
        kernel["delta64_rescue"] = runner.PRODUCTION_DELTA64_RESCUE
        kernel["lz4_acceleration"] = acceleration
        kernel["lz4_wall_ns"] = 1_000_000 if acceleration == 1 else 800_000
        kernel["ordered_lz4_wall_ns"] = (
            700_000 if acceleration == 1 else 560_000)
        kernel["prep_lz4_wall_ns"] = (
            300_000 if acceleration == 1 else 240_000)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_LZ4_ACCELERATION={acceleration}")
    return out


def synthetic_log():
    out = ["HOST_SWAPS_BEFORE:", "/private/system/swapfile",
           "SOURCE_HEAD=a" + "a" * 39,
           "KERNEL_DEBUG_FEATURES=kasan:1 kcsan:0 lockdep:1 config:boot",
           "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:0 swapz_reports:0",
           "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0",
           "PASS_LOADED_MAXIMUM_CAPACITY=logical_pages:3727616 logical_bytes:15268315136 lower_bytes:17178820608 physical_blocks:4194048 segments:16383 initial_mapper_read_bytes:4096 constructor_lower_io_delta:0 boundary_pages:2 boundary_page_bytes:4096 boundary_lower_read_bytes:8192 boundary_lower_write_bytes:8192",
           "PASS_LOADED_GC_ROLL_FORWARD_RECOVERY=foreground_writes:768 fault_nth:769 injected:1 retry_attempts:2 roll_forwards:1 destination_advances:0 reserve_initial:2 reserve_current:2 relocated_pages:510 verified_pages:512",
           "PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:2048 async_batches:64 lower_read_reqs:512",
                "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 flush_calls:2",
                "PASS_LOADED_DELTA64_POSITIVE=pages:128 classifier_pass:128 adopted:128",
           "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 distinct:6 victim_min:1 victim_max:3 last:11->29 discards:12 discard_sectors:24576 discard_unsupported:0 discard_failed:0 verified_pages:4096",
           "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 baseline_p99_ns:1000000 pressure_p99_ns:5000000 gc_wall_ns:200000000 gc_fraction_ppm:200000 choose_wall_ns:20000000 choose_calls:12 choose_map_entries:0 choose_segment_entries:768 relocation_map_entries:12 no_headroom_skips:3 alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 alloc_probe_segments:1024 alloc_probe_full_scans:16 alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 segment_program_sum:80 segment_program_max:4 segment_program_segments:32",
           "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 immediate_sectors:2048 reuse_skips:2 verified_pages:4096",
           "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 holes:0 run_splits:0 failed:0",
           "PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 verified_pages:128",
           "PASS_LOADED_COMPLETION_HANDOFF=offloaded:4 verified_pages:128 completed_writes:16512 active_after:0 fault_offloaded:2 fault_injected:1 post_failure_eio:1",
           "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 syscall_errno:EIO lower_write_delta:0",
           "PASS_LOADED_SYNTHETIC_READ_FAULT=page:3072 injected:1 syscall_errno:EIO lower_read_delta:0 submitted_delta:0",
           "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
           "PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 inline_lower_write_delta:0 submitter_lower_write_delta:0 background_error_completions:8",
           "PASS_ID36_RESOURCE_PRESSURE=memory_high_events:8 memory_peak_bytes:734003200 cpu_some_usec:250000 cpu_workers:8 pressure_mib:576 oom:0 oom_kill:0",
           "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=run_id:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa partuuid:01234567-89abcdef device:251:1 prepare:READY start:ACTIVE swapon:true stop:COMPLETE recovery_required:false",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-starting",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-header-verified",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-module-inserted",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-module-loaded",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mapper-inactive",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mapper-resumed",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-mkswap",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-swapon",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-stopping",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-swapoff",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-mapper-removed",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-module-unloaded",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=stop-restored",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-recovering",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-swapoff",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-mapper-removed",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-module-unloaded",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-restored",
           "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18 fresh_process:true host_swap_identity:preserved repeat_recovery:safe",
           "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:13 ambiguous_syscall:true inventory_failure:true definite_io_error:true wrong_mapper:true failed_swapoff:true stale_run:true fsync_failure:true lost_provenance:true repeat_recovery:safe host_swap_identity:preserved",
           "PASS_LOADED_OWNED_NULLBLK_SMOKE"]
    negative_aggregate_index = next(
        index for index, line in enumerate(out)
        if line.startswith("PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY="))
    negative_details = []
    for case_index, (case_name, contract) in enumerate(
            runner.PRIMARY_NEGATIVE_CASE_REFUSALS.items()):
        negative_details.append(
            "START_LOADED_PRIMARY_NULLBLK_NEGATIVE="
            f"{case_name} run_id:{case_index + 1:032x}")
        if contract is not None:
            operation, error_text = contract
            negative_details.append(
                f"BLOCKED: primary-swap {operation} failed: {error_text}")
    out[negative_aggregate_index:negative_aggregate_index] = negative_details
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_OWNED_RAM_REGIME={regime}")
        modes = (runner.CONFIRMATION_SEQUENCE
                 if regime == "ssd_emulated" else (0, 1, 1, 0))
        for i, mode in enumerate(modes):
            out.append(f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
            out.append("REPLAY_ORDER=swapz-first" if i % 2 else "REPLAY_ORDER=off-first")
            out.append("PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
            out.append("SWAPZ_STATUS_BEFORE=windows=0 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=0 close_pack_ready=0 packed_early_commits=0 single_pack_deferrals=0 accepted_burst_extensions=0 accepted_burst_tail_flushes=0 accepted_burst_read_caps=0 retained_burst_target=4 one_page_windows=0 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=0 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=0 win1_pack_ready=0 win1_pack_tail_target=0 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=0 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=0 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0")
            out.append("SWAPZ_STATUS_AFTER=windows=20 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=2 close_pack_ready=18 packed_early_commits=8 single_pack_deferrals=24 accepted_burst_extensions=6 accepted_burst_tail_flushes=5 accepted_burst_read_caps=4 retained_burst_target=8 one_page_windows=4 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=1 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=2 win1_pack_ready=1 win1_pack_tail_target=1 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=1 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=1 prep_producer_head_claims=2 prep_producer_tail_claims=3 prep_ordered_inline=4 prep_ordered_handoffs=3 prep_ordered_waits=1 prep_lower_write_overlap_starts=42 prep_wave_kicks=5")
            for candidate in (("swapz", "off") if i % 2 else ("off", "swapz")):
                out.append(json.dumps(arm(candidate, mode=mode, regime=regime)))
            if mode:
                out.append("PASS_ASYNC_LOWER_IO_OVERLAP_STARTS=42")
            out.append(f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
        out.append(f"PASS_OWNED_RAM_REGIME={regime}")
    for envelope in runner.STORAGE_ENVELOPE_ORDER:
        envelope_spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
        out.append(f"START_STORAGE_ENVELOPE={envelope}")
        out.append("REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**envelope_spec))
        off = storage_envelope_arm("off", envelope=envelope)
        swapz = storage_envelope_arm("swapz", envelope=envelope)
        out.append(json.dumps(off))
        out.append(json.dumps(swapz))
        out.append(f"PASS_STORAGE_ENVELOPE={envelope}")
    out.extend(lz4_acceleration_log())
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_READ_COALESCE_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=0, regime="ssd_emulated")
        swapz = coalesce_arm(enabled)
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_READ_COALESCE_AB={enabled}")
    spec = runner.MODEL_SPECS["sd_emulated"]
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_SD_READ_COALESCE_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=0, regime="sd_emulated")
        swapz = coalesce_arm(enabled, regime="sd_emulated")
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_SD_READ_COALESCE_AB={enabled}")

    spec = runner.MODEL_SPECS["ssd_emulated"]
    for index, enabled in enumerate(runner.CONFIRMATION_SEQUENCE):
        out.append(f"START_PARALLEL_READ_AB={enabled}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        raw = arm("off", mode=1, regime="ssd_emulated")
        swapz = fanout_arm(enabled)
        for record in ((swapz, raw) if index % 2 else (raw, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_PARALLEL_READ_AB={enabled}")

    for regime in runner.MODEL_ORDER:
        policy_spec = runner.MODEL_SPECS[regime]
        for index, allow in enumerate(runner.CONFIRMATION_SEQUENCE):
            out.append(f"START_K1_READ_BYPASS_AB={regime}:{allow}")
            out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                       "REPLAY_ORDER=off-first")
            out.append(
                "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                "HW_QUEUE_DEPTH={hw_queue_depth}".format(**policy_spec))
            raw = arm("off", mode=1, regime=regime)
            swapz = k1_read_bypass_arm(allow, regime)
            for record in ((swapz, raw) if index % 2 else (raw, swapz)):
                out.append(json.dumps(record))
            out.append(f"PASS_K1_READ_BYPASS_AB={regime}:{allow}")
        for index, read_cap in enumerate(runner.READ_COALESCE_CAP_SEQUENCE):
            out.append(f"START_READ_COALESCE_CAP_AB={regime}:{read_cap}")
            out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                       "REPLAY_ORDER=off-first")
            out.append(
                "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                "HW_QUEUE_DEPTH={hw_queue_depth}".format(**policy_spec))
            raw = arm("off", mode=0, regime=regime)
            swapz = read_coalesce_cap_arm(read_cap, regime)
            for record in ((swapz, raw) if index % 2 else (raw, swapz)):
                out.append(json.dumps(record))
            out.append(f"PASS_READ_COALESCE_CAP_AB={regime}:{read_cap}")
    spec = runner.MODEL_SPECS["ssd_emulated"]
    delta64_sequence = [2 if bit else 1
                        for bit in runner.CONFIRMATION_SEQUENCE]
    for index, workers in enumerate(delta64_sequence):
        out.append(f"START_DELTA64_PREPARE_WORKERS={workers}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = write_arm("off", qd=32, regime="ssd_emulated", mode=0)
        off["fixture_sha256"] = "e" * 64
        off["trace_sha256"] = "f" * 64
        swapz = delta64_prepare_arm(workers)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_DELTA64_PREPARE_WORKERS={workers}")
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_WRITE_SATURATION_REGIME={regime}")
        index = 0
        for qd in (1, 4, 8, 32):
            modes = (runner.CONFIRMATION_SEQUENCE
                     if ((regime == "ssd_emulated" and qd in (4, 8, 32)) or
                         (regime == "sd_emulated" and qd == 32))
                     else (0, 1))
            for mode in modes:
                out.append(
                    f"START_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}")
                out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                           "REPLAY_ORDER=off-first")
                out.append(
                    "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
                    "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
                    "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
                    "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
                out.append(
                    "SWAPZ_STATUS_BEFORE=windows=0 one_page_windows=0 "
                    "win1=0 win2=0 win3_4=0 win5_8=0 win9_16=0 "
                    "win17_64=0 close_idle=0 close_deadline=0 "
                    "close_pack_ready=0 retained_burst_target=4 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0")
                out.append(
                    "SWAPZ_STATUS_AFTER=windows=20 one_page_windows=4 "
                    "win1=4 win2=0 win3_4=8 win5_8=8 win9_16=0 "
                    "win17_64=0 close_idle=4 close_deadline=2 "
                    f"close_pack_ready=14 retained_burst_target={max(4, qd)} prep_producer_head_claims=2 prep_producer_tail_claims=3 prep_ordered_inline=4 prep_ordered_handoffs=3 prep_ordered_waits=1 prep_lower_write_overlap_starts=42 prep_wave_kicks=5")
                for candidate in (("swapz", "off") if index % 2 else ("off", "swapz")):
                    out.append(json.dumps(write_arm(
                        candidate, qd=qd, regime=regime, mode=mode)))
                out.append(
                    f"PASS_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}")
                index += 1
        out.append(f"PASS_WRITE_SATURATION_REGIME={regime}")
    spec = runner.MODEL_SPECS["ssd_emulated"]
    depth_sequence = [2 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
    for index, depth in enumerate(depth_sequence):
        out.append(f"START_WRITE_PIPELINE_DEPTH={depth}")
        out.append("REPLAY_ORDER=swapz-first" if index % 2 else
                   "REPLAY_ORDER=off-first")
        out.append(
            "PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} "
            "COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode} "
            "QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} "
            "HW_QUEUE_DEPTH={hw_queue_depth}".format(**spec))
        off = write_arm("off", qd=32, regime="ssd_emulated", mode=1)
        off["fixture_sha256"] = "7" * 64
        off["trace_sha256"] = "8" * 64
        swapz = write_pipeline_arm(depth)
        for record in ((swapz, off) if index % 2 else (off, swapz)):
            out.append(json.dumps(record))
        out.append(f"PASS_WRITE_PIPELINE_DEPTH={depth}")
    out.append("PASS_LOADED_TEST_EXECUTION: synthetic full gate completed")
    return "\n".join(out) + "\n"


class ReportContract(unittest.TestCase):
    def test_loaded_failure_console_retains_bounded_private_child_output(self):
        source_sha = "a" * 40
        private_path = "/home/private-host/owned-ram-trace.py"
        transcript = (
            "PASS_LOADED_OWNED_NULLBLK_SMOKE=fixture\n"
            "START_LOADED_OWNED_RAM_RECOVERY\n"
            "BLOCKED: owned RAM recovery helper class=OSError errno=22; "
            "retain evidence\n"
            "Traceback (most recent call last):\n"
            f'  File "{private_path}", line 17, in unused\n'
            "OSError: [Errno 22] Invalid argument\n")

        class FakeChild:
            def __init__(self, *_args, **_kwargs):
                self.stdout = io.StringIO(transcript)

            @staticmethod
            def wait():
                return 1

        previous_root = runner.ROOT
        try:
            with tempfile.TemporaryDirectory(prefix="loaded-report-") as name:
                runner.ROOT = Path(name)
                report = {
                    "tested_commit_sha": source_sha,
                    "stages": [],
                    "benchmarks": {},
                }
                console = io.StringIO()
                with mock.patch.object(
                        runner.subprocess, "Popen", FakeChild), \
                        contextlib.redirect_stdout(console):
                    exit_status = runner.run_stage(
                        "Owned RAM smoke + mixed/QD pilot", ["fixture"],
                        report, parse_bench=True,
                        retain_private_failure_output=True)

                self.assertEqual(exit_status, 1)
                self.assertEqual(len(report["stages"]), 1)
                stage = report["stages"][0]
                self.assertEqual(stage["status"], "BLOCKED")
                self.assertEqual(
                    stage["failed_phase"],
                    "owned RAM interrupted-resource recovery")
                public_text = console.getvalue() + json.dumps(report)
                self.assertNotIn(private_path, public_text)
                self.assertNotIn("Traceback", public_text)
                self.assertIn("Private stage log (mode 0600): ",
                              console.getvalue())
                match = re.search(
                    r"Private stage log \(mode 0600\): "
                    r"(build/tests/stage-failure-[A-Za-z0-9_-]+"
                    r"[.]private[.]log)", console.getvalue())
                self.assertIsNotNone(match, console.getvalue())
                retained_path = Path(name) / match.group(1)
                self.assertEqual(retained_path.stat().st_mode & 0o777, 0o600)
                retained = retained_path.read_text(encoding="utf-8")
                self.assertIn(f"source_sha={source_sha}", retained)
                self.assertIn(private_path, retained)
                self.assertIn("Traceback", retained)
                self.assertLessEqual(
                    retained_path.stat().st_size,
                    runner.MAX_PRIVATE_STAGE_OUTPUT_BYTES)
        finally:
            runner.ROOT = previous_root

    def test_private_stage_output_truncation_keeps_both_ends_within_bound(self):
        source_sha = "b" * 40
        original_root = runner.ROOT
        try:
            with tempfile.TemporaryDirectory(prefix="stage-log-") as name:
                runner.ROOT = Path(name)
                output = ("first-cause\n" +
                          "x" * (runner.MAX_PRIVATE_STAGE_OUTPUT_BYTES + 4096) +
                          "\nlast-context")
                relative = runner.retain_private_stage_output(
                    output, source_sha, "Owned RAM smoke")
                self.assertIsNotNone(relative)
                path = runner.ROOT / relative
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertLessEqual(
                    path.stat().st_size,
                    runner.MAX_PRIVATE_STAGE_OUTPUT_BYTES)
                retained = path.read_text(encoding="utf-8")
                self.assertIn("first-cause", retained)
                self.assertIn("child output truncated", retained)
                self.assertIn("last-context", retained)
        finally:
            runner.ROOT = original_root

    def test_constructor_failure_cleanup_evidence_is_mandatory(self):
        marker = "PASS_LOADED_CONSTRUCTOR_FAILURE_CLEANUP=stages:8 lower_io_delta:0"
        output = synthetic_log()
        evidence = runner.parse_loaded_correctness(output)
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["constructor_cleanup_stages"], 8)
        self.assertEqual(evidence["constructor_cleanup_lower_io_delta"], 0)
        self.assertEqual(
            runner.parse_loaded_correctness(output.replace(marker, ""))["overall"],
            "INCOMPLETE")
        for replacement in (
                marker.replace("stages:8", "stages:7"),
                marker.replace("lower_io_delta:0", "lower_io_delta:1")):
            with self.subTest(invalid_constructor_cleanup=replacement):
                result = runner.parse_loaded_correctness(
                    output.replace(marker, replacement))
                self.assertEqual(result["overall"], "INCOMPLETE")

    def test_loaded_kernel_debug_evidence_is_explicit_and_fail_closed(self):
        output = synthetic_log()
        evidence = runner.parse_kernel_debug_evidence(output)
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["kasan"], "1")
        self.assertEqual(evidence["lockdep"], "1")

        disabled = output.replace(
            "KERNEL_DEBUG_FEATURES=kasan:1 kcsan:0 lockdep:1 config:boot",
            "KERNEL_DEBUG_FEATURES=kasan:0 kcsan:0 lockdep:0 config:boot")
        self.assertEqual(runner.parse_kernel_debug_evidence(disabled)["overall"],
                         "NOT_ENABLED")

        unavailable = output.replace(
            "KERNEL_DEBUG_FEATURES=kasan:1 kcsan:0 lockdep:1 config:boot",
            "KERNEL_DEBUG_FEATURES=kasan:unknown kcsan:unknown lockdep:unknown config:unavailable")
        self.assertEqual(runner.parse_kernel_debug_evidence(unavailable)["overall"],
                         "UNAVAILABLE")

        unstable = output.replace(
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:0 swapz_reports:0",
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:0 reports:0 swapz_reports:0")
        self.assertEqual(runner.parse_kernel_debug_evidence(unstable)["overall"],
                         "INCOMPLETE")

        unrelated = output.replace(
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:0 swapz_reports:0",
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:1 swapz_reports:0")
        self.assertEqual(runner.parse_kernel_debug_evidence(unrelated)["overall"],
                         "INCOMPLETE")

        implicated = output.replace(
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:0 swapz_reports:0",
            "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:1 swapz_reports:1")
        self.assertEqual(runner.parse_kernel_debug_evidence(implicated)["overall"],
                         "FAIL")

        for malformed_marker in (
                "KERNEL_DEBUG_FEATURES=kasan:1 kcsan:0 lockdep:1 config:bogus",
                "KERNEL_DEBUG_OBSERVATION=checked:1 baseline_stable:1 reports:x swapz_reports:0"):
            with self.subTest(malformed_marker=malformed_marker):
                malformed = output + malformed_marker + "\n"
                verdict = runner.parse_kernel_debug_evidence(malformed)
                self.assertEqual(verdict["overall"], "INCOMPLETE")
                self.assertIn("malformed", verdict["reason"])

    def test_loaded_maximum_capacity_constructor_evidence_is_mandatory(self):
        marker = ("PASS_LOADED_MAXIMUM_CAPACITY=logical_pages:3727616 "
                  "logical_bytes:15268315136 lower_bytes:17178820608 "
                  "physical_blocks:4194048 segments:16383 "
                  "initial_mapper_read_bytes:4096 "
                  "constructor_lower_io_delta:0 boundary_pages:2 "
                  "boundary_page_bytes:4096 boundary_lower_read_bytes:8192 "
                  "boundary_lower_write_bytes:8192")
        output = synthetic_log()
        result = runner.parse_loaded_correctness(output)
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["maximum_logical_pages"], 3727616)
        self.assertEqual(result["maximum_mapper_bytes"], 15268315136)
        self.assertEqual(result["maximum_lower_bytes"], 17178820608)
        self.assertEqual(result["maximum_mapper_read_bytes"], 4096)
        self.assertEqual(result["maximum_lower_io_delta"], 0)
        self.assertEqual(result["maximum_boundary_pages"], 2)
        self.assertEqual(result["maximum_boundary_page_bytes"], 4096)
        self.assertEqual(result["maximum_boundary_lower_read_bytes"], 8192)
        self.assertEqual(result["maximum_boundary_lower_write_bytes"], 8192)
        self.assertEqual(runner.parse_loaded_correctness(
            output.replace(marker, ""))["overall"], "INCOMPLETE")
        for before, after in (
                ("logical_pages:3727616", "logical_pages:3355135"),
                ("logical_bytes:15268315136", "logical_bytes:13742637055"),
                ("lower_bytes:17178820608", "lower_bytes:67108864"),
                ("physical_blocks:4194048", "physical_blocks:4194047"),
                ("segments:16383", "segments:16382"),
                ("initial_mapper_read_bytes:4096", "initial_mapper_read_bytes:invalid"),
                ("constructor_lower_io_delta:0", "constructor_lower_io_delta:1"),
                ("boundary_pages:2", "boundary_pages:1"),
                ("boundary_page_bytes:4096", "boundary_page_bytes:4095"),
                ("boundary_lower_read_bytes:8192", "boundary_lower_read_bytes:0"),
                ("boundary_lower_write_bytes:8192", "boundary_lower_write_bytes:0")):
            bad = output.replace(marker, marker.replace(before, after))
            self.assertEqual(runner.parse_loaded_correctness(bad)["overall"],
                             "INCOMPLETE")

    def test_primary_lifecycle_recovery_evidence_is_mandatory(self):
        output = synthetic_log()
        evidence = runner.parse_loaded_correctness(output)
        self.assertEqual(evidence["overall"], "PASS")
        self.assertEqual(evidence["primary_lifecycle"], "PASS")
        self.assertEqual(evidence["primary_lifecycle_interruptions"], 18)
        self.assertEqual(evidence["primary_lifecycle_negative_cases"], 13)

        required_markers = (
            "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=",
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=",
            "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=",
        )
        for marker in required_markers:
            with self.subTest(missing=marker):
                lines = [
                    line for line in output.splitlines()
                    if not line.startswith(marker)
                ]
                result = runner.parse_loaded_correctness("\n".join(lines) + "\n")
                self.assertEqual(result["overall"], "INCOMPLETE")

        interruption = (
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-module-loaded")
        result = runner.parse_loaded_correctness(
            output.replace(interruption + "\n", ""))
        self.assertEqual(result["overall"], "INCOMPLETE")
        self.assertIn("interruption recovery", result["reason"])

        duplicated = output.replace(
            interruption + "\n",
            interruption + "\n" + interruption + "\n")
        result = runner.parse_loaded_correctness(duplicated)
        self.assertEqual(result["overall"], "INCOMPLETE")

        malformed_interruption = (
            output + "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION=INVALID\n")
        result = runner.parse_loaded_correctness(malformed_interruption)
        self.assertEqual(result["overall"], "INCOMPLETE")
        self.assertIn("malformed primary lifecycle interruption", result["reason"])

        # The three primary aggregate PASS records must each occur once.
        for marker in required_markers:
            with self.subTest(duplicated=marker):
                original_line = next(
                    line for line in output.splitlines()
                    if line.startswith(marker))
                duplicated_aggregate = output.replace(
                    original_line + "\n",
                    original_line + "\n" + original_line + "\n", 1)
                result = runner.parse_loaded_correctness(duplicated_aggregate)
                self.assertEqual(result["overall"], "INCOMPLETE")
                self.assertIn("duplicate primary", result["reason"])

    def test_repeated_loaded_fault_and_resource_markers_are_incomplete(self):
        output = synthetic_log()
        for prefix in (
                "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=",
                "PASS_ID36_RESOURCE_PRESSURE="):
            with self.subTest(marker=prefix):
                marker = next(
                    line for line in output.splitlines()
                    if line.startswith(prefix))
                repeated = output.replace(
                    marker + "\n", marker + "\n" + marker + "\n", 1)
                verdict = runner.parse_loaded_correctness(repeated)
                self.assertEqual(verdict["overall"], "INCOMPLETE")
                self.assertIn("duplicate loaded correctness", verdict["reason"])

                malformed = output + prefix + "malformed\n"
                verdict = runner.parse_loaded_correctness(malformed)
                self.assertEqual(verdict["overall"], "INCOMPLETE")
                self.assertIn("malformed loaded correctness", verdict["reason"])

    def test_raw_read_fanout_evidence_is_mandatory(self):
        marker = ("PASS_LOADED_RAW_READ_FANOUT=profiles:2 verified_pages:2048 "
                  "async_batches:64 lower_read_reqs:512")
        output = synthetic_log()
        self.assertEqual(runner.parse_loaded_correctness(output)["overall"], "PASS")
        self.assertEqual(runner.parse_loaded_correctness(
            output.replace(marker, ""))["overall"], "INCOMPLETE")
        for before, after in (("profiles:2", "profiles:1"),
                              ("verified_pages:2048", "verified_pages:1024"),
                              ("async_batches:64", "async_batches:0"),
                              ("lower_read_reqs:512", "lower_read_reqs:0")):
            self.assertEqual(runner.parse_loaded_correctness(output.replace(
                marker, marker.replace(before, after)))["overall"], "INCOMPLETE")

    def test_vm_history_excludes_unqualified_other_host_and_mismatched_inputs(self):
        import copy

        spec = importlib.util.spec_from_file_location(
            "swapz_history_plot", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        raw = {"source_sha": "source", "fixture_sha256": "fixture",
               "trace_sha256": "trace", "host_cpu": {"online_cpus": 7},
               "input_write_mbps": 100, "swap_in_read_mbps": 40,
               "swap_in_read_p99_ms": 4, "write_p99_ms": 8,
               "lower_write_bytes": 1000, "lower_write_requests": 100}
        swapz = {**raw, "input_write_mbps": 150, "swap_in_read_mbps": 60,
                 "swap_in_read_p99_ms": 2, "write_p99_ms": 4,
                 "lower_write_bytes": 700, "lower_write_requests": 20,
                 "kernel_write_path": {"delta64_rescue": 1}}
        session = {"status": "PASS", "async_prepare": 1, "regime": "sd_emulated",
                   "device_model": {"cap_mib_s": 10}, "arms": {"off": raw, "swapz": swapz}}
        report = {"overall": "PASS", "tested_commit_sha": "source", "kernel_release": "kernel",
                  "evidence": {"predictor": {"backend_benchmarks": [{"name": "neon"}]}},
                  "benchmarks": {"sessions": [session]}}
        self.assertTrue(history.host_matches(report))
        points = history.report_points(report)
        self.assertEqual(len(points), 1)
        ram_only = {**report, "overall": "INCOMPLETE",
                    "stages": [{"status": "PASS"}] * 5}
        self.assertEqual(history.report_points(ram_only), [])
        self.assertEqual(
            history.report_points(ram_only, include_incomplete_ram=True), points)
        for invalid in (
                {**ram_only, "stages": [{"status": "PASS"}] * 4},
                {**ram_only, "stages": [{"status": "PASS"}] * 4
                 + [{"status": "NOT_RUN"}]},
                {**ram_only, "overall": "FAIL"},
                {**ram_only, "overall": "BLOCKED"}):
            self.assertEqual(
                history.report_points(invalid, include_incomplete_ram=True), [])
        for metric in ("write_mbps_gain_pct", "read_mbps_gain_pct", "read_p99_ms_gain_pct"):
            self.assertAlmostEqual(points[0][metric], 50)
        self.assertAlmostEqual(points[0]["lower_write_bytes_gain_pct"], 30)
        self.assertAlmostEqual(points[0]["lower_write_requests_gain_pct"], 80)
        self.assertEqual(history.change(0, 100, True), 100)
        self.assertIsNone(history.change(1, 0))
        for key, value in (("source_sha", "other"), ("fixture_sha256", "other"),
                           ("trace_sha256", "other"), ("kernel_write_path", None)):
            bad = copy.deepcopy(report)
            bad["benchmarks"]["sessions"][0]["arms"]["swapz"][key] = value
            self.assertEqual(history.report_points(bad), [])
        for state in ("FAIL", "BLOCKED"):
            self.assertEqual(history.report_points({**report, "overall": state}), [])
        self.assertFalse(history.host_matches({**report, "evidence": {}}))
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["arms"]["off"]["host_cpu"] = {"online_cpus": 8}
        self.assertFalse(history.host_matches(bad))
        bad = copy.deepcopy(report)
        bad["kernel_release"] = "another kernel"
        self.assertNotEqual(history.report_points(bad)[0]["compatibility"], points[0]["compatibility"])
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["async_prepare"] = 0
        self.assertEqual(history.report_points(bad), [])
        self.assertEqual(points[0]["workload"], "mixed QD32")
        off_policy = copy.deepcopy(report)
        off_policy["benchmarks"]["sessions"][0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 0
        self.assertEqual(history.report_points(off_policy), [])
        bad = copy.deepcopy(report)
        bad["benchmarks"]["sessions"][0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = None
        self.assertEqual(history.report_points(bad), [])
        # Historical envelope rescue-on rows replayed the write-only
        # delta64-positive fixture; they must never become mixed points.
        envelope = {"status": "PASS", "envelope": "sata_ssd",
                    "device_model": {"cap_mib_s": 500},
                    "arms": {"off": {**raw, "input_read_mbps": 0.0},
                             "swapz": {**swapz, "input_read_mbps": 0.0}}}
        legacy = copy.deepcopy(report)
        legacy["benchmarks"]["storage_envelope_sessions"] = [envelope]
        self.assertEqual([p for p in history.report_points(legacy)
                          if p["target"] == "sata_ssd"], [])
        mixed_envelope = copy.deepcopy(envelope)
        for arm in mixed_envelope["arms"].values():
            arm["input_read_mbps"] = 30.0
        current = copy.deepcopy(report)
        current["benchmarks"]["storage_envelope_sessions"] = [mixed_envelope]
        self.assertEqual(len([p for p in history.report_points(current)
                              if p["target"] == "sata_ssd"]), 1)
        sustained = copy.deepcopy(report)
        write_session = copy.deepcopy(session)
        write_session["qd"] = 4
        for arm in write_session["arms"].values():
            arm["replay_mode"] = "persistent-write"
        sustained["benchmarks"]["write_saturation"] = {
            "replay_mode": "persistent-write", "regimes": {"sd_emulated": [
                {"mode": "async", "qd": 4, "raw_write_mbps": 100,
                 "swapz_write_mbps": 150, "observations": 1}]}}
        sustained["benchmarks"]["write_saturation_sessions"] = [write_session]
        self.assertEqual(len(history.report_points(sustained)), 2)
        sustained["benchmarks"]["write_saturation"]["replay_mode"] = "qd-waves"
        self.assertEqual(len(history.report_points(sustained)), 1)
        sustained["benchmarks"]["write_saturation"]["replay_mode"] = "persistent-write"
        production_write = history.report_points(sustained)[-1]
        self.assertEqual(production_write["workload"], "persistent WRITE")
        off_policy_write = copy.deepcopy(sustained)
        off_policy_write["benchmarks"]["write_saturation_sessions"][0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 0
        self.assertEqual(len(history.report_points(off_policy_write)), 1)

    def test_x86_history_requires_audited_reports_and_separate_isa_profile(self):
        import copy

        spec = importlib.util.spec_from_file_location(
            "swapz_x86_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        sha = "a" * 40
        profile = {"id": "x86-i7-avx512", "title": "x86 AVX-512 host",
                   "online_cpus": 8, "host_id_sha256": "b" * 64,
                   "report_shas": [sha]}
        self.assertEqual(history.validate_host_profile(profile), profile)
        report = {"overall": "PASS", "stages": [{"status": "PASS"}] * 5,
                  "evidence": {"predictor": {"backend_benchmarks": [
                      {"name": name} for name in ("scalar", "sse2", "avx2", "avx512")]}},
                  "benchmarks": {"sessions": [{"arms": {
                      arm: {"host_cpu": {"online_cpus": 8}} for arm in ("off", "swapz")}}]}}
        self.assertTrue(history.selected_host_report(report, sha, profile))
        self.assertTrue(history.selected_host_report(
            {**report, "overall": "INCOMPLETE"}, sha, profile))
        self.assertFalse(history.selected_host_report(report, "c" * 40, profile))
        self.assertFalse(history.selected_host_report(report, sha))
        for mutate in (lambda r: r.update(overall="BLOCKED"),
                       lambda r: r["stages"].pop(),
                       lambda r: r["evidence"]["predictor"]["backend_benchmarks"].pop(),
                       lambda r: r["benchmarks"]["sessions"][0]["arms"]["off"].update(
                           host_cpu={"online_cpus": 4}),
                       lambda r: r["benchmarks"]["sessions"][0]["arms"]["off"].pop("host_cpu")):
            bad = copy.deepcopy(report)
            mutate(bad)
            self.assertFalse(history.selected_host_report(bad, sha, profile))
        for changes in ({"id": "../arm64-neon"}, {"report_shas": []},
                        {"report_shas": ["HEAD"]}, {"host_id_sha256": ""}):
            with self.assertRaises(ValueError):
                history.validate_host_profile({**profile, **changes})

    def test_history_snapshots_preserve_report_specific_artifacts(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_history_snapshots", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        with tempfile.TemporaryDirectory() as directory:
            history.OUT = Path(directory)
            names = ("mixed-service.png", "mixed-throughput.png", "mixed-latency.png",
                     "lower-write-savings.png", "sustained-write.png", "history.csv", "history.json")
            for name in names:
                (history.OUT / name).write_bytes(b"first report")
            data = {"reports": [{"report_sha": "a" * 40}]}
            first = history.snapshot_history(data)
            for name in names:
                self.assertEqual((first / name).read_bytes(), b"first report")
                (history.OUT / name).write_bytes(b"next report")
            self.assertEqual(history.snapshot_history(data), first)
            self.assertEqual((first / names[0]).read_bytes(), b"first report")
            second = history.snapshot_history({"reports": [{"report_sha": "b" * 40}]})
            self.assertNotEqual(second, first)
            self.assertEqual((second / names[0]).read_bytes(), b"next report")

    def test_computer_history_rejects_other_and_unidentified_hosts(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_computer_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        report = {"host_identity": identity, "overall": "PASS",
                  "stages": [{"status": "PASS"}] * 5}
        self.assertTrue(history.same_computer_report(report, identity))
        self.assertTrue(history.same_computer_report(
            {**report, "overall": "INCOMPLETE"}, identity))
        self.assertFalse(history.same_computer_report(
            {**report, "overall": "INCOMPLETE",
             "stages": [{"status": "PASS"}] * 4 + [{"status": "FAIL"}]},
            identity))
        for different in ({**identity, "id_sha256": "b" * 64},
                          {**identity, "architecture": "aarch64"}, {},
                          {**identity, "schema": "unknown"}):
            self.assertFalse(history.same_computer_report(report, different))
        self.assertFalse(history.same_computer_report(
            {**report, "overall": "BLOCKED"}, identity))
        self.assertFalse(history.same_computer_report(
            {**report, "stages": [{"status": "PASS"}] * 4}, identity))

    def test_history_collects_only_matching_computer_from_shared_git_reports(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location(
            "swapz_shared_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        reports = {}
        for index, host in enumerate((identity, {**identity, "id_sha256": "b" * 64},
                                      {**identity, "id_sha256": "c" * 64}, None,
                                      identity), 1):
            reports[f"{index:040x}"] = {"host_identity": host, "overall": "PASS",
                "stages": [{"status": "PASS"}] * 5, "tested_commit_sha": "f" * 40}
        # A canonical restoration is an additional Git commit, not a second
        # execution of the earlier host report.
        restored_sha = f"{6:040x}"
        reports[restored_sha] = reports[f"{1:040x}"]
        reports[f"{7:040x}"] = {
            **reports[f"{1:040x}"], "overall": "INCOMPLETE"}
        reports[f"{8:040x}"] = {
            **reports[f"{1:040x}"], "overall": "INCOMPLETE",
            "stages": [{"status": "PASS"}] * 4 + [{"status": "BLOCKED"}]}
        reports[f"{9:040x}"] = {
            **reports[f"{1:040x}"], "overall": "FAIL"}
        def git_output(command, **kwargs):
            if command[1] == "log":
                return "\n".join(
                    sha + " 2026-10-30T12:00:00-07:00" +
                    (" true" if sha == restored_sha else "")
                    for sha in reports)
            return json.dumps(reports[command[2].split(":")[0]]).encode()
        with patch.object(history.subprocess, "check_output", side_effect=git_output), \
                patch.object(history, "report_points", return_value=[{"target": "ssd_emulated"}]):
            data = history.collect(computer=identity)
        self.assertEqual([r["report_sha"] for r in data["reports"]],
                         [f"{1:040x}", f"{5:040x}", f"{7:040x}"])
        self.assertEqual(data["reports"][-1]["overall_verdict"], "INCOMPLETE")
        self.assertEqual(data["reports"][-1]["ram_stage_evidence"], "FIVE_STAGE_PASS")
        self.assertEqual(data["excluded"]["other or unproven host"], 5)

    def test_host_identity_matches_production_sha256_vectors(self):
        from unittest.mock import call, patch

        dmi_path = "/sys/class/dmi/id/product_uuid"
        machine_path = "/etc/machine-id"
        # Literal digests pin the C prefix (including NUL), UUID layout,
        # lowercase normalization, and both identifier lengths.
        vectors = (
            (b"00112233-4455-6677-8899-aabbccddeeff\n",
             b"0123456789abcdef0123456789abcdef\n",
             "43ff3a146c6a1c8eb61716358170b7d765f7db44f86fc38e18dd449dd2e36d1f"),
            (b"ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB", b"A" * 32,
             "5077d1acbef3f04e0452c028e378ab9baf65fc9c6f3b89e2a86aa9e9b76f6795"),
            (b"00112233-4455-6677-8899-aabbccddeeff", b"f" * 32,
             "154683b7b7fb6965af8954ac2f23cda3a220ae2a53ef295dc3935e15767568eb"),
            (b"00000001-0000-0000-0000-000000000000",
             b"0123456789abcdef0123456789abcdef",
             "fc5848ac1b8a9297e969045c0f8c443a8be6de839ba99c649bb8b0a70b574516"),
        )
        identities = []
        for product_uuid, machine_id, expected_digest in vectors:
            with self.subTest(expected_digest=expected_digest):
                records = {dmi_path: product_uuid, machine_path: machine_id}
                with patch.object(runner, "_read_host_identity_record",
                                  side_effect=lambda path, limit: records[path]) as reader:
                    identity = runner.report_host_identity()
                self.assertEqual(reader.call_args_list,
                                 [call(dmi_path, 40), call(machine_path, 64)])
                self.assertEqual(identity, {
                    "schema": "swapz-host-v1",
                    "architecture": runner.os.uname().machine,
                    "id_sha256": expected_digest})
                self.assertNotIn(product_uuid.decode("ascii"), json.dumps(identity))
                self.assertNotIn(machine_id.decode("ascii"), json.dumps(identity))
                identities.append(identity)
        self.assertEqual(len({identity["id_sha256"] for identity in identities}), 4)
        self.assertNotEqual(identities[0]["id_sha256"], hashlib.sha256(
            b"swapz-host\0" + b"0123456789abcdef0123456789abcdef").hexdigest())

        spec = importlib.util.spec_from_file_location(
            "swapz_identity_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        report = {"host_identity": identities[0], "overall": "PASS",
                  "stages": [{"status": "PASS"}] * 5}
        self.assertTrue(history.same_computer_report(report, identities[0]))
        for different_host in identities[1:]:
            self.assertFalse(history.same_computer_report(report, different_host))

    def test_host_identity_missing_or_invalid_fails_closed(self):
        from unittest.mock import patch

        dmi_path = "/sys/class/dmi/id/product_uuid"
        machine_path = "/etc/machine-id"
        records = {dmi_path: b"00112233-4455-6677-8899-aabbccddeeff\n",
                   machine_path: b"0123456789abcdef0123456789abcdef\n"}
        expected_classes = {
            dmi_path: "root_owned_regular_dmi_uuid_36_hex_hyphens_optional_lf",
            machine_path: "root_owned_regular_machine_id_32_hex_optional_lf",
        }
        malformed = (
            (dmi_path, b""), (dmi_path, b"00000000-0000-0000-0000-000000000000"),
            (dmi_path, b"00112233445566778899aabbccddeeff"),
            (dmi_path, b"00112233-4455-6677-8899-aabbccddeezz"),
            (dmi_path, records[dmi_path] + b"\n"),
            (dmi_path, records[dmi_path].replace(b"\n", b"\r\n")),
            (machine_path, b""), (machine_path, b"0" * 32),
            (machine_path, b"not-a-machine-id"), (machine_path, b"\xff" * 32),
            (machine_path, records[machine_path] + b"\n"),
            (machine_path, records[machine_path].replace(b"\n", b"\r\n")),
        )
        for path, value in malformed:
            with self.subTest(path=path, invalid_length=len(value)):
                supplied = {**records, path: value}
                with patch.object(runner, "_read_host_identity_record",
                                  side_effect=lambda name, limit: supplied[name]):
                    result = runner.report_host_identity()
                self.assertEqual(result, {
                    "schema": "swapz-host-v1", "status": "UNAVAILABLE",
                    "phase": "host_identity", "expected_input_class": expected_classes[path],
                    "observed_validity_class": "malformed",
                    "refusal_reason": "invalid_format_or_zero"})
                self.assertNotIn(records[dmi_path].decode().strip(), json.dumps(result))
                self.assertNotIn(records[machine_path].decode().strip(), json.dumps(result))

        errors = ((FileNotFoundError("private missing input"), "missing", "file_missing"),
                  (PermissionError("private permission detail"), "unreadable", "read_failed"),
                  (ValueError("untrusted_metadata"), "untrusted", "untrusted_metadata"),
                  (ValueError("changed_during_read"), "changed", "changed_during_read"),
                  (ValueError("oversized_file"), "malformed", "oversized_file"))
        for path in (dmi_path, machine_path):
            for error, observed, reason in errors:
                with self.subTest(path=path, reason=reason):
                    def read_selected(name, limit):
                        if name == path:
                            raise error
                        return records[name]

                    with patch.object(runner, "_read_host_identity_record",
                                      side_effect=read_selected):
                        result = runner.report_host_identity()
                    self.assertEqual(result, {
                        "schema": "swapz-host-v1", "status": "UNAVAILABLE",
                        "phase": "host_identity", "expected_input_class": expected_classes[path],
                        "observed_validity_class": observed, "refusal_reason": reason})
                    self.assertNotIn("private", json.dumps(result))


    def test_host_identity_permission_denial_uses_only_protected_fallback(self):
        from unittest.mock import patch

        path = "/sys/class/dmi/id/product_uuid"
        record = b"00112233-4455-6677-8899-aabbccddeeff\n"
        with patch.object(runner.os, "open",
                          side_effect=PermissionError(13, "private detail")), \
                patch.object(runner, "_read_host_identity_record_privileged",
                             return_value=record) as privileged:
            self.assertEqual(runner._read_host_identity_record(path, 40), record)
        privileged.assert_called_once_with(path, 40)

        with patch.object(runner.os, "open",
                          side_effect=FileNotFoundError("missing")), \
                patch.object(runner, "_read_host_identity_record_privileged") as privileged:
            with self.assertRaises(FileNotFoundError):
                runner._read_host_identity_record(path, 40)
        privileged.assert_not_called()

    def test_privileged_host_identity_reader_pins_and_bounds_both_inputs(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        metadata = SimpleNamespace(
            st_mode=runner.stat.S_IFREG | 0o400, st_uid=0, st_gid=0,
            st_nlink=1, st_dev=1, st_ino=2, st_size=37,
            st_mtime_ns=3, st_ctime_ns=4)
        records = (
            ("/sys/class/dmi/id/product_uuid", 40,
             b"00112233-4455-6677-8899-aabbccddeeff\n"),
            ("/etc/machine-id", 64, b"0123456789abcdef0123456789abcdef\n"),
        )
        for path, byte_limit, record in records:
            with self.subTest(path=path):
                completed = runner.subprocess.CompletedProcess(
                    [], 0, stdout=record)
                with patch.object(runner.os, "open", return_value=42) as opened, \
                        patch.object(runner.os, "fstat",
                                     return_value=metadata) as checked, \
                        patch.object(runner.os, "close") as closed, \
                        patch.object(runner.subprocess, "run",
                                     return_value=completed) as command:
                    actual = runner._read_host_identity_record_privileged(
                        path, byte_limit)
                self.assertEqual(actual, record)
                opened.assert_called_once_with(
                    path, runner.os.O_PATH | runner.os.O_NOFOLLOW |
                    runner.os.O_CLOEXEC)
                self.assertEqual(checked.call_count, 2)
                closed.assert_called_once_with(42)
                arguments, options = command.call_args
                self.assertEqual(arguments[0], [
                    "/usr/bin/sudo", "-n", "--", "/usr/bin/head", "-c",
                    str(byte_limit), "--", f"/proc/{runner.os.getpid()}/fd/42"])
                self.assertEqual(options, {
                    "stdin": runner.subprocess.DEVNULL,
                    "stdout": runner.subprocess.PIPE,
                    "stderr": runner.subprocess.DEVNULL,
                    "timeout": 8, "check": False})
                self.assertNotIn(record.decode().strip(), str(arguments))

    def test_privileged_host_identity_reader_fails_closed_and_closes_fd(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        path = "/sys/class/dmi/id/product_uuid"
        record = b"00112233-4455-6677-8899-aabbccddeeff\n"
        metadata = SimpleNamespace(
            st_mode=runner.stat.S_IFREG | 0o400, st_uid=0, st_gid=0,
            st_nlink=1, st_dev=1, st_ino=2, st_size=37,
            st_mtime_ns=3, st_ctime_ns=4)
        changed = SimpleNamespace(**{**vars(metadata), "st_mtime_ns": 5})
        untrusted = SimpleNamespace(**{**vars(metadata),
                                       "st_mode": runner.stat.S_IFLNK | 0o777})
        cases = (
            ("missing sudo authorization", [metadata, metadata],
             runner.subprocess.CompletedProcess([], 1, stdout=record),
             None, PermissionError, True),
            ("timeout", [metadata, metadata], None,
             runner.subprocess.TimeoutExpired([], 8), PermissionError, True),
            ("oversized record", [metadata, metadata],
             runner.subprocess.CompletedProcess([], 0, stdout=b"x" * 40),
             None, ValueError, True),
            ("changed inode", [metadata, changed],
             runner.subprocess.CompletedProcess([], 0, stdout=record),
             None, ValueError, True),
            ("symlink", [untrusted], None,
             None, ValueError, False),
        )
        for name, snapshots, result, failure, exception, invoked in cases:
            with self.subTest(case=name):
                with patch.object(runner.os, "open", return_value=42), \
                        patch.object(runner.os, "fstat",
                                     side_effect=snapshots), \
                        patch.object(runner.os, "close") as closed, \
                        patch.object(runner.subprocess, "run",
                                     return_value=result,
                                     side_effect=failure) as command:
                    with self.assertRaises(exception):
                        runner._read_host_identity_record_privileged(path, 40)
                closed.assert_called_once_with(42)
                self.assertEqual(command.called, invoked)

        with patch.object(runner.os, "open") as opened:
            with self.assertRaises(PermissionError):
                runner._read_host_identity_record_privileged("/tmp/unsafe", 40)
        opened.assert_not_called()

        with patch.object(runner.os, "open",
                          side_effect=PermissionError("private OS details")), \
                patch.object(runner, "_read_host_identity_record_privileged",
                             side_effect=PermissionError("private sudo details")):
            identity = runner.report_host_identity()
        self.assertEqual(identity, {
            "schema": "swapz-host-v1", "status": "UNAVAILABLE",
            "phase": "host_identity",
            "expected_input_class":
                "root_owned_regular_dmi_uuid_36_hex_hyphens_optional_lf",
            "observed_validity_class": "unreadable",
            "refusal_reason": "read_failed"})
        self.assertNotIn("private", json.dumps(identity))

    def test_host_identity_architecture_lookup_failure_is_sanitized(self):
        from unittest.mock import patch

        records = {
            "/sys/class/dmi/id/product_uuid":
                b"00112233-4455-6677-8899-aabbccddeeff\n",
            "/etc/machine-id": b"0123456789abcdef0123456789abcdef\n",
        }
        with patch.object(
                runner, "_read_host_identity_record",
                side_effect=lambda path, limit: records[path]), \
                patch.object(
                    runner.os, "uname",
                    side_effect=OSError("private runtime architecture detail")):
            result = runner.report_host_identity()

        self.assertEqual(result, {
            "schema": "swapz-host-v1", "status": "UNAVAILABLE",
            "phase": "host_identity",
            "expected_input_class": "runtime_architecture",
            "observed_validity_class": "unavailable",
            "refusal_reason": "uname_failed"})
        serialized = json.dumps(result)
        self.assertNotIn("private", serialized)
        for record in records.values():
            self.assertNotIn(record.decode("ascii").strip(), serialized)

    def test_host_identity_reader_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            private_record = Path(directory) / "record"
            private_record.write_bytes(b"0" * 32)
            symlink = Path(directory) / "symlink"
            symlink.symlink_to(private_record)
            with self.assertRaises(OSError):
                runner._read_host_identity_record(str(symlink), 64)

    def test_history_refresh_executes_after_publication_without_changing_verdicts(self):
        from unittest.mock import patch
        identity = {"schema": "swapz-host-v1", "architecture": "x86_64",
                    "id_sha256": "a" * 64}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "tests/tools/plot-history.py"
            helper.parent.mkdir(parents=True)
            helper.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                "Path('build/history/marker').write_text(json.dumps(sys.argv))\n"
                "print('{\"reports\": 3, \"latest_source\": \"abcdef0123456789\"}')\n")
            with patch.object(runner, "ROOT", root):
                result = runner.refresh_history(identity)
                self.assertIn("UPDATED: 3 this-computer RAM-backed reports", result)
                self.assertIn("abcdef012345", result)
                marker = root / "build/history/marker"
                command = json.loads(marker.read_text())
                self.assertEqual(command[1:], ["--host-id", "a" * 64,
                                               "--host-architecture", "x86_64"])
                helper.write_text("raise SystemExit('matplotlib unavailable')\n")
                self.assertTrue(runner.refresh_history(identity).startswith("NOT UPDATED:"))
                log = root / "build/history" / ("x86_64-" + "a" * 64) / "refresh.log"
                self.assertIn("matplotlib unavailable", log.read_text())
                helper.write_text(
                    "raise SystemExit('No eligible RAM-backed history for the selected host profile')\n")
                self.assertEqual(
                    runner.refresh_history(identity),
                    "NOT UPDATED: no comparable RAM-backed history for this "
                    "computer (host and five-stage RAM evidence required)")
                self.assertIn("No eligible RAM-backed history for the selected host profile",
                              log.read_text())
                helper.write_text("print('invalid summary')\n")
                self.assertTrue(runner.refresh_history(identity).startswith("NOT UPDATED:"))
                marker.unlink()
                self.assertIn("stable host identity unavailable", runner.refresh_history({}))
                self.assertFalse(marker.exists())
        qualification = (ROOT / "tests/tools/run-tests.py").read_text().split(
            "def _run_qualification(args, sync_result):", 1)[1]
        self.assertLess(qualification.index("notice = publish("),
                        qualification.index("refresh_history("))

    def test_vm_history_lines_break_at_workload_changes_and_missing_reports(self):
        spec = importlib.util.spec_from_file_location(
            "swapz_history_lines", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)

        class Axes:
            def __init__(self):
                self.chunks = []

            def plot(self, x, y, *args, **kwargs):
                self.chunks.append(x)

        axes = Axes()
        history.draw_line(axes, [
            {"sequence": 1, "compatibility": "a", "gain": 1},
            {"sequence": 2, "compatibility": "a", "gain": 2},
            {"sequence": 3, "compatibility": "b", "gain": 3},
            {"sequence": 5, "compatibility": "b", "gain": 4},
        ], "gain", "gain", "blue")
        self.assertEqual(axes.chunks, [[1, 2], [3], [5]])

    def test_per_device_class_goals_classify_targets_and_guards(self):
        """ID174: one shared, descriptive scorecard for reporter and plots."""
        import contextlib
        import copy
        import io

        spec = importlib.util.spec_from_file_location(
            "swapz_goal_history", ROOT / "tests/tools/plot-history.py")
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        goals = runner.product_goals
        self.assertEqual(goals.GUARD_FLOOR_PCT, -5.0)
        self.assertEqual(len(goals.GOALS), 14)
        self.assertEqual(len({(g["target"], g["workload"], g["qd"])
                              for g in goals.GOALS}), 14)
        self.assertEqual(goals.goal_for("nvme_gen5", goals.MIXED)["bound"],
                         goals.HOST_BOUND)
        self.assertEqual(goals.goal_for("ssd_emulated", goals.PERSISTENT, 4)["bound"],
                         goals.LATENCY_BOUND)
        self.assertEqual(goals.goal_for("ssd_emulated", goals.PERSISTENT, 8)["bound"],
                         goals.DEVICE_BOUND)
        self.assertIsNone(goals.goal_for("ssd_emulated", goals.PERSISTENT, 2))

        def point(target, workload, qd, gain, saved_bytes, saved_requests):
            return {"target": target, "workload": workload, "qd": qd,
                    "write_mbps_gain_pct": gain,
                    "lower_write_bytes_gain_pct": saved_bytes,
                    "lower_write_requests_gain_pct": saved_requests}

        points = [
            point("sd_emulated", goals.MIXED, None, 0.1, 1, 1),        # MET
            point("ssd_emulated", goals.MIXED, None, 0.0, 30, 70),     # parity: MISSED
            point("sd_card", goals.MIXED, None, 50, 0.0, 10),          # no byte save
            point("nvme_gen4", goals.MIXED, None, -5.0, 0.0, 0.0),     # guard edge: MET
            point("nvme_gen5", goals.MIXED, None, -5.01, 20, 80),      # below floor
            point("sd_emulated", goals.PERSISTENT, 1, -1, 0.0, 0.0),   # guard: MET
            point("ssd_emulated", goals.PERSISTENT, 1, -1, -0.5, 0.0), # adds bytes
            point("ssd_emulated", goals.PERSISTENT, 4, -1, None, 1),   # unavailable
            point("ssd_emulated", goals.PERSISTENT, 8, -9, 1, 1),      # stale point
            point("ssd_emulated", goals.PERSISTENT, 8, 9, 1, 1),       # latest wins
        ]
        rows = {row["label"]: row for row in goals.scorecard(points)}
        expected = {"Serial mixed": "MET", "Fast mixed": "MISSED",
                    "SD card mixed": "MISSED", "NVMe4 mixed": "MET",
                    "NVMe5 mixed": "MISSED", "Serial QD1": "MET",
                    "Fast QD1": "MISSED", "Fast QD4": "UNAVAILABLE",
                    "Fast QD8": "MET", "SATA mixed": "UNAVAILABLE",
                    "Fast QD32": "UNAVAILABLE"}
        for label, status in expected.items():
            self.assertEqual(rows[label]["status"], status, label)
        self.assertEqual(rows["Fast QD8"]["write_gain_pct"], 9)
        self.assertEqual(rows["NVMe4 mixed"]["service_floor_pct"], -5.0)
        self.assertEqual(rows["Serial mixed"]["service_floor_pct"], 0.0)
        self.assertEqual(goals.scorecard([])[0]["status"], "UNAVAILABLE")

        # Persistent WRITE points carry exact lower-WRITE savings for the scorecard.
        raw = {"source_sha": "source", "fixture_sha256": "fixture",
               "trace_sha256": "trace", "replay_mode": "persistent-write"}
        swapz = {**raw, "kernel_write_path": {"delta64_rescue": 1}}
        report = {"overall": "PASS", "tested_commit_sha": "source",
                  "kernel_release": "kernel", "benchmarks": {
                      "write_saturation": {"replay_mode": "persistent-write", "regimes": {
                          "ssd_emulated": [{"mode": "async", "qd": 8, "raw_write_mbps": 100,
                                            "swapz_write_mbps": 125,
                                            "swapz_logical_to_lower_ratio": 4 / 3,
                                            "raw_lower_write_requests": 400,
                                            "swapz_lower_write_requests": 100,
                                            "observations": 5}]}},
                      "write_saturation_sessions": [{
                          "status": "PASS", "async_prepare": 1, "regime": "ssd_emulated",
                          "qd": 8, "device_model": {"cap_mib_s": 80},
                          "arms": {"off": raw, "swapz": swapz}}]}}
        sustained = goals.report_points(report)
        self.assertEqual(len(sustained), 1)
        self.assertAlmostEqual(sustained[0]["write_mbps_gain_pct"], 25)
        self.assertAlmostEqual(sustained[0]["lower_write_bytes_gain_pct"], 25)
        self.assertAlmostEqual(sustained[0]["lower_write_requests_gain_pct"], 75)
        broken = copy.deepcopy(report)
        broken["benchmarks"]["write_saturation"]["regimes"]["ssd_emulated"][0][
            "swapz_logical_to_lower_ratio"] = 0
        self.assertIsNone(goals.report_points(broken)[0]["lower_write_bytes_gain_pct"])

        # The reporter stores it as descriptive evidence and renders a valid table.
        scored = runner.goal_scorecard(report)
        self.assertEqual(scored["overall"], "DESCRIPTIVE")
        self.assertEqual(
            {row["label"]: row["status"] for row in scored["rows"]}["Fast QD8"], "MET")
        self.assertEqual(runner.goal_scorecard({"overall": "FAIL"})["overall"], "UNAVAILABLE")
        self.assertNotIn("goal_scorecard", inspect.getsource(runner.required_benchmark_gates_pass))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            runner.print_table(
                "Per-device-class product goals versus raw",
                ("class", "bound", "goal", "W vs raw", "bytes saved", "req saved", "status"),
                [("Fast QD8", "device-bound", ">0%", "+25.0%", "+25.0%", "+75.0%", "MET"),
                 ("Fast QD1", "latency-bound", ">=-5%", "-25.0%", "+0.0%", "+0.0%",
                  "MISSED")])
        text = buffer.getvalue()
        flat = " ".join(text.split())
        self.assertIn("1 of 2 classes met their goal", flat)
        self.assertIn("missed: Fast QD1", flat)
        self.assertIn("Verdict: DESCRIPTIVE SCORECARD", flat)
        self.assertTrue(all(len(line) < 96 for line in text.splitlines()))
        self.assertTrue(text.rstrip().endswith("---"))

        # Plots name each class goal and draw the floor only on guard panels.
        self.assertIn("Target: beat raw (>0%)", history.goal_title(
            "Fast QD8", goals.goal_for("ssd_emulated", goals.PERSISTENT, 8)))
        self.assertIn("Guard: within 5% of raw (latency-bound)", history.goal_title(
            "Fast QD1", goals.goal_for("ssd_emulated", goals.PERSISTENT, 1)))
        self.assertEqual(history.goal_title("Other", None), "Other")

        class Axes:
            def __init__(self):
                self.lines = []

            def axhline(self, value, **kwargs):
                self.lines.append(value)

        axes = Axes()
        history.draw_goal(axes, goals.goal_for("ssd_emulated", goals.PERSISTENT, 8))
        history.draw_goal(axes, None)
        self.assertEqual(axes.lines, [])
        history.draw_goal(axes, goals.goal_for("nvme_gen5", goals.MIXED))
        self.assertEqual(axes.lines, [-5.0])

    def test_qualification_stage_table_shows_completed_and_not_run_once(self):
        captured = io.StringIO()
        stages = [(name, ["unused"]) for name in (
            "Build module and helpers",
            "Native and rootless contracts",
            "Kernel warnings W=1",
            "Kernel warnings W=2",
            "Owned RAM smoke + mixed/QD pilot")]
        result = [
            {"status": "PASS", "elapsed_s": 2.5},
            {"status": "FAIL", "elapsed_s": 4.25},
        ]
        with contextlib.redirect_stdout(captured):
            runner.print_stage_results(stages, result)
        output = captured.getvalue()
        self.assertIn("ID | Name", output)
        for index, (name, _) in enumerate(stages):
            self.assertEqual(output.count(name), 1)
            expected_verdict = ("PASS" if index == 0 else
                                "FAIL" if index == 1 else "NOT RUN")
            self.assertIn(runner.progress_table_row(
                index, name, expected_verdict,
                ("2.50s" if index == 0 else
                 "4.25s" if index == 1 else "-")), output)
        self.assertNotIn("/5  ", output)

    def test_physical_trial_table_has_a_single_dev_scoped_row(self):
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            runner.print_physical_trial_result("NOT RUN", "0.03s")
        output = captured.getvalue()
        self.assertIn("ID | Name", output)
        self.assertEqual(
            output.count("Authorized physical swap trial (dev)"), 1)
        self.assertIn(runner.progress_table_row(
            0, "Authorized physical swap trial (dev)",
            "NOT RUN", "0.03s"), output)

    def test_loaded_progress_table_labels_and_success_markers(self):
        phases = {"preflight"} | {
            phase for _, phase in runner.LOADED_TIMING_BOUNDARIES
        }
        self.assertEqual(set(runner.LOADED_PHASE_DISPLAY_NAMES), phases)
        names = list(runner.LOADED_PHASE_DISPLAY_NAMES.values())
        self.assertEqual(
            runner.LOADED_PHASE_DISPLAY_NAMES["id36-pressure"],
            "Low-memory + heavy-CPU stress test")
        self.assertNotIn("ID36 constrained resource pressure", names)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(len(name) <= runner.ROOTLESS_NAME_WIDTH
                            and not name.startswith("tests/") for name in names))
        self.assertFalse(runner.loaded_phase_has_success_marker(
            "maximum-capacity", "PASS_LOADED_MAXIMUM_CAPACITY_FORGED\n"))
        self.assertTrue(runner.loaded_phase_has_success_marker(
            "maximum-capacity", "PASS_LOADED_MAXIMUM_CAPACITY\n"))
        self.assertFalse(runner.loaded_phase_has_success_marker(
            "plan-fixture", "PASS_LOADED_MAXIMUM_CAPACITY\n"))

    def test_loaded_progress_table_preserves_failure_and_hides_raw_markers(self):
        from unittest import mock

        transcript = (
            "LOADED_QUALIFICATION_SOURCE=ready\n"
            "START_LOADED_MAXIMUM_CAPACITY\n"
            "PASS_LOADED_MAXIMUM_CAPACITY\n"
            "START_LOADED_GC_ROLL_FORWARD_RECOVERY\n"
            "PASS_LOADED_GC_ROLL_FORWARD_RECOVERY\n"
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
            "BLOCKED: private/path must not leak\n")
        captured = io.StringIO()
        result = {"stages": [], "benchmarks": {}}
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=1)), \
                contextlib.redirect_stdout(captured):
            runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                             ["unused"], result, parse_bench=True)
        printed = captured.getvalue()
        self.assertIn("ID | Name", printed)
        for label in ("Loaded host preflight", "Maximum swap capacity",
                      "GC roll-forward recovery",
                      "Owned RAM null_blk correctness"):
            self.assertEqual(printed.count(label), 1)
        self.assertTrue(any(
            "GC roll-forward recovery" in line and "| PASS" in line
            for line in printed.splitlines()))
        self.assertIn("BLOCKED", printed)
        self.assertNotIn("START_LOADED", printed)
        self.assertNotIn("PASS_LOADED", printed)
        self.assertNotIn("START_OWNED_RAM_PAIR", printed)
        self.assertNotIn("private/path", printed)
        self.assertEqual(result["stages"][-1]["status"], "BLOCKED")

    def test_loaded_table_preflight_block_is_one_safe_row(self):
        from unittest import mock

        result = {"stages": [], "benchmarks": {}}
        output = io.StringIO()
        transcript = "BLOCKED_LOADED_QUALIFICATION: /private/host/path\n"
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=2)), \
                contextlib.redirect_stdout(output):
            runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                             ["unused"], result, parse_bench=True)
        printed = output.getvalue()
        self.assertIn("Loaded host preflight", printed)
        self.assertIn("| BLOCKED", printed)
        self.assertNotIn("/private", printed)
        self.assertEqual(result["stages"][-1]["status"], "BLOCKED")

    def test_loaded_progress_table_updates_terminal_row_in_place(self):
        from unittest import mock

        class TerminalOutput(io.StringIO):
            def isatty(self):
                return True

        transcript = (
            "START_LOADED_MAXIMUM_CAPACITY\n"
            "PASS_LOADED_MAXIMUM_CAPACITY\n"
            "START_LOADED_GC_ROLL_FORWARD_RECOVERY\n")
        output = TerminalOutput()
        result = {"stages": [], "benchmarks": {}}
        with mock.patch.object(
                runner.subprocess, "Popen",
                return_value=FakeStreamingProcess(transcript, returncode=1)), \
                contextlib.redirect_stdout(output):
            runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                             ["unused"], result, parse_bench=True)
        printed = output.getvalue()
        self.assertIn("\r" + runner.loaded_phase_table_row(
            0, "preflight", "RUNNING", "-"), printed)
        self.assertIn("\r" + runner.loaded_phase_table_row(
            1, "maximum-capacity", "RUNNING", "-"), printed)
        self.assertEqual(printed.count("\r"), 6)
        self.assertNotIn("START_LOADED", printed)

    def test_loaded_progress_stream_hides_bulk_evidence_but_keeps_phase_and_failure(self):
        self.assertIsNone(runner.loaded_progress_line(
            "TARGET_STATUS_AFTER=0 8192 swapz physical_write=123456"))
        self.assertIsNone(runner.loaded_progress_line(
            '{"candidate":"swapz","verdict":"PASS","throughput_mbps":{}}'))
        self.assertEqual(
            runner.loaded_progress_line("START_OWNED_RAM_PAIR_ASYNC_PREPARE=1"),
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1")
        self.assertEqual(
            runner.loaded_progress_line(
                "PASS_LOADED_LIVE_GC=victims:20 rotations:20 pages:20"),
            "PASS_LOADED_LIVE_GC")
        self.assertEqual(
            runner.loaded_progress_line(
                "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1"),
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT")
        self.assertEqual(
            runner.loaded_progress_line(
                "START_ID36_RESOURCE_PRESSURE=memory_high:1 pressure_mib:576"),
            "START_ID36_RESOURCE_PRESSURE")
        self.assertEqual(
            runner.loaded_progress_line("FAIL: owned RAM pair timed out"),
            "FAIL: diagnostic retained for stage summary")
        for marker in ("FAIL: /home/private/child-secret",
                       "BLOCKED: /home/private/child-secret"):
            self.assertNotIn("/home/private",
                             runner.loaded_progress_line(marker))

    def test_host_cpu_record_keeps_aggregate_counters_and_missing_status(self):
        raw = {"status": "AVAILABLE", "wall_ns": 1000000000,
               "online_cpus": 4, "affinity_cpus": 2, "tick_hz": 100,
               "busy_fraction": .7, "steal_fraction": 0.,
               "pressure_some_fraction": .25, "processes": "SECRET"}
        observed = runner.host_cpu_record({"host_cpu": raw})
        self.assertNotIn("SECRET", json.dumps(observed))
        self.assertEqual(observed["busy_fraction"], .7)
        self.assertEqual(runner.host_cpu_record({}), {"status": "NOT_COLLECTED"})
        self.assertEqual(runner.host_cpu_record({"host_cpu": {
            **raw, "busy_fraction": float("nan")}}), {"status": "INVALID"})
        partial = runner.host_cpu_record({"host_cpu": {
            **raw, "status": "PARTIAL", "pressure_some_fraction": None}})
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertIsNone(partial["pressure_some_fraction"])

    def test_unsupported_owned_storage_delay_tuples_fail_before_privilege(self):
        """Reject arbitrary timer or cap input BEFORE touching host devices."""
        import subprocess
        script = ROOT / "tests/tools/benchmark-owned-pair.sh"
        common = ["bash", str(script), "--run-owned-ram-pair",
                  "--profile", "medium", "--retain-ms", "2", "--unpaced"]
        forbidden = (
            ("--lower-mbps", "80", "--completion-nsec", "1000000"),
            ("--lower-mbps", "10", "--completion-nsec", "150000"),
            ("--lower-mbps", "80", "--completion-nsec", "5"),
            ("--lower-mbps", "999", "--completion-nsec", "150000"),
            ("--completion-nsec", "1000000"),
            ("--lower-mbps", "12"),
            ("--lower-mbps", "20"),
            ("--lower-mbps", "0"),
            ("--lower-mbps", "10"),
        )
        for option in forbidden:
            with self.subTest(option=option):
                run = subprocess.run(common + list(option), text=True,
                                     capture_output=True, timeout=4)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("BLOCKED", run.stderr)
        source = script.read_text()
        for key in ('"$config/mbps"', '"$config/irqmode"',
                    '"$config/completion_nsec"', '"$config/memory_backed"'):
            self.assertIn(key, source)
        self.assertIn('PASS_RAM_MODEL_LOWER_MBPS=', source)
        # The deleted shell preflight was redundant with this rootless
        # Python contract. Preserve teardown/ownership/swap guard checks.
        for gate in ("SWAPS=", "nullb-swapz-", "memory_backed",
                     "dmsetup remove", "QUARANTINE=0",
                     "READY_COUNT=0", "COUNT != READY_COUNT",
                     "--expected-dm-uuid", "timeout --signal=TERM"):
            self.assertIn(gate, source)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        self.assertIn("git diff --cached --quiet -- . ':(exclude)test_results.json'", loaded)
        self.assertIn("git diff --cached --name-only -- . ':(exclude)test_results.json'", loaded)
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertIn("for envelope in sd_card sata_ssd nvme_gen4 nvme_gen5", loaded)
        self.assertIn("START_STORAGE_ENVELOPE=", loaded)
        self.assertIn("--submit-queues", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["sd_card"]["cap_mib_s"], 100)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["sata_ssd"]["cap_mib_s"], 500)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen4"]["submit_queues"], 4)
        self.assertEqual(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen5"]["submit_queues"], 4)
        nvme_limits = runner.device_model_limits(
            runner.STORAGE_ENVELOPE_SPECS["nvme_gen5"], offered_qd=32)
        self.assertEqual(nvme_limits["effective_queue_depth"], 32)
        self.assertNotIn("START_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("PASS_PARALLEL_READ_AB=", loaded)
        self.assertNotIn("START_SD_READ_GROUPING_AB=", loaded)
        self.assertNotIn("--parallel-reads", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertNotIn("/dev/sdb", loaded)

    def test_storage_envelopes_report_capture_and_qd_limited_ceiling(self):
        import copy

        lines = []
        for envelope in runner.STORAGE_ENVELOPE_ORDER:
            spec = runner.STORAGE_ENVELOPE_SPECS[envelope]
            raw = arm("off", mode=1, regime="ssd_emulated")
            swapz = arm("swapz", mode=1, regime="ssd_emulated")
            raw["replay_engine"] = "native-c"
            swapz["replay_engine"] = "native-c"
            kernel = swapz["kernel_write_path"]
            kernel["delta64_rescue"] = runner.PRODUCTION_DELTA64_RESCUE
            kernel["delta64_lz4_acceleration"] = runner.PRODUCTION_DELTA64_LZ4_ACCELERATION
            kernel["lz4_acceleration"] = 1
            lines.extend((
                f"START_STORAGE_ENVELOPE={envelope}",
                "PASS_RAM_MODEL_LOWER_MBPS="
                f"{spec['cap_mib_s']} COMPLETION_NSEC={spec['completion_nsec']} "
                f"IRQMODE={spec['irqmode']} QUEUE_MODE={spec['queue_mode']} "
                f"SUBMIT_QUEUES={spec['submit_queues']} "
                f"HW_QUEUE_DEPTH={spec['hw_queue_depth']}",
                json.dumps(raw),
                json.dumps(swapz),
                f"PASS_STORAGE_ENVELOPE={envelope}",
            ))
        sessions = runner.parse_storage_envelope_sessions("\n".join(lines))
        self.assertEqual(len(sessions), 4)
        verdict = runner.storage_envelope_verdict(sessions)
        self.assertEqual(
            verdict["overall"], "PASS_DIRECTIONAL_STORAGE_ENVELOPES")
        self.assertEqual(len(verdict["rows"]), 4)
        for row in verdict["rows"]:
            spec = runner.STORAGE_ENVELOPE_SPECS[row["envelope"]]
            self.assertEqual(
                row["device_limits"]["effective_queue_depth"],
                min(32, spec["submit_queues"] * spec["hw_queue_depth"]))
            self.assertAlmostEqual(row["byte_speedup"], 1.6)
            self.assertAlmostEqual(row["request_speedup"], 1.6)
            self.assertLess(
                row["bandwidth_opportunity_capture_fraction"], 0.0)
            self.assertAlmostEqual(row["post_lower_hold_fraction"], 0.004)
            self.assertEqual(row["replay_engine"], "native-c")
            self.assertEqual(row["delta64_rescue"], 1)

        bad = [dict(session) for session in sessions]
        bad[0] = dict(bad[0], arms={
            name: dict(arm_record) for name, arm_record in bad[0]["arms"].items()
        })
        bad[0]["arms"]["off"]["replay_engine"] = "python-threaded"
        self.assertEqual(
            runner.storage_envelope_verdict(bad)["overall"], "INCONCLUSIVE")

        wrong_policy = copy.deepcopy(sessions)
        wrong_policy[0]["arms"]["swapz"]["kernel_write_path"]["delta64_rescue"] = 0
        self.assertEqual(
            runner.storage_envelope_verdict(wrong_policy)["overall"], "INCONCLUSIVE")

    def test_predictor_evidence_is_sanitized(self):
        raw = predictor_evidence()
        parsed = runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed, raw)
        broken = json.loads(json.dumps(raw))
        broken["sse2_forward_ab"]["pairs"][2]["order"] = "unrolled_first"
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = json.loads(json.dumps(raw))
        broken["sse2_forward_ab"]["pairs"][0]["unrolled_ns_per_page"] = 0
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = json.loads(json.dumps(raw))
        broken["thresholds"][2]["negative_calls"] = 65
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["thresholds"][2]["routed_blocks_saved"] += 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["sampling_controls"][0]["score"] = 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        broken = predictor_evidence()
        broken["production_route"]["candidate_attempts"] -= 1
        self.assertIsNone(runner.parse_predictor_evidence(
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(broken) + "\n"))
        duplicate = (
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n" +
            "SWAPZ_PREDICTOR_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertIsNone(runner.parse_predictor_evidence(duplicate))

    def test_gc_scan_scale_evidence_is_sanitized(self):
        raw = gc_scan_scale_evidence()
        parsed = runner.parse_gc_scan_scale_evidence(
            "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed["rows"][1]["logical_pages"], 1048576)
        self.assertEqual(parsed["rows"][1]["relocation_list_ns"], 4500)
        self.assertEqual(parsed["rows"][3]["logical_pages"], 27080192)
        truncated = json.loads(json.dumps(raw))
        truncated["rows"].pop()
        self.assertIsNone(runner.parse_gc_scan_scale_evidence(
            "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" + json.dumps(truncated) + "\n"))
        broken = json.loads(json.dumps(raw))
        broken["rows"][1]["victim_records"] = 255
        self.assertIsNone(runner.parse_gc_scan_scale_evidence(
            "SWAPZ_GC_SCAN_SCALE_EVIDENCE=" + json.dumps(broken) + "\n"))

    def test_extent_geometry_evidence_is_sanitized(self):
        raw = extent_geometry_evidence()
        parsed = runner.parse_extent_geometry_evidence(
            "SWAPZ_EXTENT_GEOMETRY_EVIDENCE=" + json.dumps(raw) + "\n")
        self.assertEqual(parsed["rows"][1]["name"], "packed_1_2_4")
        self.assertEqual(parsed["rows"][4]["seq_4m_requests"], 1200)
        broken = json.loads(json.dumps(raw))
        broken["rows"][2]["name"] = "packed_1_4"
        self.assertIsNone(runner.parse_extent_geometry_evidence(
            "SWAPZ_EXTENT_GEOMETRY_EVIDENCE=" + json.dumps(broken) + "\n"))

    def test_loaded_lifecycle_markers_are_strict_and_sanitized(self):
        loaded = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(loaded["overall"], "PASS")
        self.assertEqual(loaded["raw_pages"], 64)
        self.assertEqual(loaded["gc_victims"], 12)
        self.assertEqual(loaded["gc_rotations"], 12)
        self.assertEqual(loaded["gc_distinct_victims"], 6)
        self.assertEqual(loaded["gc_victim_min_evictions"], 1)
        self.assertEqual(loaded["gc_victim_max_evictions"], 3)
        self.assertEqual(loaded["gc_verified_pages"], 4096)
        self.assertEqual(loaded["gc_segment_discards"], 12)
        self.assertEqual(loaded["gc_segment_discard_sectors"], 24576)
        self.assertEqual(loaded["gc_pressure_rounds"], 5)
        self.assertEqual(loaded["gc_fraction_ppm"], 200000)
        self.assertEqual(loaded["gc_baseline_p99_ns"], 1000000)
        self.assertEqual(loaded["gc_pressure_p99_ns"], 5000000)
        self.assertEqual(loaded["gc_choose_map_entries"], 0)
        self.assertEqual(loaded["gc_relocation_map_entries"], 12)
        self.assertEqual(loaded["gc_no_headroom_skips"], 3)
        self.assertEqual(loaded["alignment_hole_blocks_foreground"], 4)
        self.assertEqual(loaded["segment_tail_waste_blocks_foreground"], 4)
        self.assertEqual(loaded["segment_tail_waste_blocks_gc"], 1)
        self.assertEqual(loaded["run_splits_by_hole"], 0)
        self.assertEqual(loaded["segment_discards_skipped_already_trimmed"], 6)
        self.assertEqual(loaded["segment_program_max"], 4)
        self.assertEqual(loaded["discard_trim_immediate"], 1)
        self.assertEqual(loaded["discard_trim_reuse_skips"], 2)
        self.assertEqual(loaded["packed_placement_enabled"], 1)
        self.assertEqual(loaded["packed_placement_holes"], 0)
        self.assertEqual(loaded["packed_placement_run_splits"], 0)
        self.assertEqual(loaded["alignment_hole_blocks_foreground"],
                         loaded["segment_tail_waste_blocks_foreground"])
        self.assertEqual(loaded["alignment_hole_blocks_gc"],
                         loaded["segment_tail_waste_blocks_gc"])
        self.assertEqual(loaded["run_splits_by_hole"], 0)
        # The null_blk lifecycle oracle alone uses 64 ms for slow observers;
        # the production retained-window ceiling remains 4 ms.
        self.assertEqual(loaded["suspend_retain_ms"], 64)
        self.assertEqual(loaded["suspend_observed_open"], 1)
        self.assertEqual(loaded["suspend_verified_pages"], 128)
        self.assertIn("PRE_SUBMISSION", loaded["retained_write_fault"])

        missing_gc = synthetic_log().replace(
            "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 "
            "read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 "
            "distinct:6 victim_min:1 victim_max:3 last:11->29 "
            "discards:12 discard_sectors:24576 discard_unsupported:0 "
            "discard_failed:0 verified_pages:4096\n", "")
        self.assertEqual(runner.parse_loaded_correctness(missing_gc)["overall"],
                         "INCOMPLETE")

        missing_pressure = synthetic_log().replace(
            "PASS_LOADED_GC_PRESSURE=rounds:5 write_wall_ns:1000000000 "
            "baseline_p99_ns:1000000 pressure_p99_ns:5000000 "
            "gc_wall_ns:200000000 gc_fraction_ppm:200000 "
            "choose_wall_ns:20000000 choose_calls:12 "
            "choose_map_entries:0 choose_segment_entries:768 "
            "relocation_map_entries:12 no_headroom_skips:3 "
            "alignment_hole_fg:4 alignment_hole_gc:1 tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0 "
            "alloc_probe_segments:1024 alloc_probe_full_scans:16 "
            "alloc_probe_wall_ns:50000 trim_skipped:6 segment_program_min:0 "
            "segment_program_sum:80 segment_program_max:4 "
            "segment_program_segments:32\n", "")
        self.assertEqual(
            runner.parse_loaded_correctness(missing_pressure)["overall"],
            "INCOMPLETE")

        missing_trim = synthetic_log().replace(
            "PASS_LOADED_DISCARD_TRIM=pages:256 immediate_discards:1 "
            "immediate_sectors:2048 reuse_skips:2 verified_pages:4096\n", "")
        self.assertEqual(
            runner.parse_loaded_correctness(missing_trim)["overall"],
            "INCOMPLETE")

        bad_packed_hole = synthetic_log().replace(
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:0 failed:0",
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:1 run_splits:0 failed:0")
        self.assertEqual(
            runner.parse_loaded_correctness(bad_packed_hole)["overall"],
            "INCOMPLETE")

        bad_packed_split = synthetic_log().replace(
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:0 failed:0",
            "PASS_LOADED_PACKED_PLACEMENT=enabled:1 verified_pages:128 "
            "holes:0 run_splits:1 failed:0")
        self.assertEqual(
            runner.parse_loaded_correctness(bad_packed_split)["overall"],
            "INCOMPLETE")

        bad_gc_internal_hole = synthetic_log().replace(
            "alignment_hole_fg:4 alignment_hole_gc:1 "
            "tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0",
            "alignment_hole_fg:5 alignment_hole_gc:1 "
            "tail_waste_fg:4 tail_waste_gc:1 run_splits_by_hole:0", 1)
        self.assertEqual(
            runner.parse_loaded_correctness(bad_gc_internal_hole)["overall"],
            "INCOMPLETE")

        missing = synthetic_log().replace(
            "PASS_LOADED_SUSPEND_DRAIN=retain_ms:64 observed_open:1 "
            "verified_pages:128\n", "")
        self.assertEqual(runner.parse_loaded_correctness(missing)["overall"],
                         "INCOMPLETE")

        handoff = ("PASS_LOADED_COMPLETION_HANDOFF=offloaded:4 verified_pages:128 "
                   "completed_writes:16512 active_after:0 fault_offloaded:2 "
                   "fault_injected:1 post_failure_eio:1")
        for replacement in (
                "", handoff.replace("offloaded:4", "offloaded:0"),
                handoff.replace("verified_pages:128", "verified_pages:127"),
                handoff.replace("completed_writes:16512", "completed_writes:16511"),
                handoff.replace("active_after:0", "active_after:1"),
                handoff.replace("fault_injected:1", "fault_injected:0"),
                handoff.replace("post_failure_eio:1", "post_failure_eio:0")):
            self.assertEqual(runner.parse_loaded_correctness(
                synthetic_log().replace(handoff, replacement))["overall"],
                "INCOMPLETE")

        # The fault mapping is independent of the preceding live handoff gate;
        # zero fault-session offloads are valid when all failure invariants pass.
        zero_fault_offload = handoff.replace(
            "fault_offloaded:2", "fault_offloaded:0")
        self.assertEqual(runner.parse_loaded_correctness(
            synthetic_log().replace(handoff, zero_fault_offload))["overall"],
            "PASS")

        # The production delta64 + DELTA64_SHUF8 + LZ4 positive path must be
        # emitted by the owner script, persisted in the report and fail closed.
        delta64 = ("PASS_LOADED_DELTA64_POSITIVE=pages:128 "
                   "classifier_pass:128 adopted:128")
        self.assertIn(
            'note "PASS_LOADED_DELTA64_POSITIVE=pages:128 '
            'classifier_pass:$delta64_pass adopted:$delta64_adopted"',
            (ROOT / "tests/tools/deploy-nullblk.sh").read_text())
        self.assertIn(delta64, (
            ROOT / "tests/runtime/native/make-interface-test.py").read_text())
        loaded = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(loaded["delta64_positive_pages"], 128)
        self.assertEqual(loaded["delta64_positive_classifier_pass"], 128)
        self.assertEqual(loaded["delta64_positive_adopted"], 128)
        for replacement in (
                "", delta64.replace("pages:128", "pages:64"),
                delta64.replace("classifier_pass:128", "classifier_pass:127"),
                delta64.replace("adopted:128", "adopted:127")):
            with self.subTest(invalid_delta64_marker=replacement):
                result = runner.parse_loaded_correctness(
                    synthetic_log().replace(delta64, replacement))
                self.assertEqual(result["overall"], "INCOMPLETE")

        # The exact loaded test now proves an aligned O_DIRECT pwrite(2)
        # returned -1/EIO, not just that the kernel injected a fault.
        # Missing, wrong or reordered syscall evidence must fail closed.
        marker = (
            "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 "
            "syscall_errno:EIO lower_write_delta:0")
        # Prevent a future contract drift: the rootless fixture must match
        # the exact marker the privileged owner script actually emits.
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        make_interface = (
            ROOT / "tests/runtime/native/make-interface-test.py").read_text()
        self.assertIn('note "' + marker + '"', deploy)
        self.assertIn(marker, make_interface)
        self.assertIn(marker, synthetic_log())
        for replacement in (
            marker.replace("syscall_errno:EIO ", ""),
            marker.replace("syscall_errno:EIO", "syscall_errno:ENOSPC"),
            marker.replace("syscall_errno:EIO", "syscall_errno:0"),
            marker.replace("syscall_errno:EIO lower_write_delta:0",
                           "lower_write_delta:0 syscall_errno:EIO"),
            marker.replace("lower_write_delta:0", "lower_write_delta:1"),
            marker.replace("injected:1", "injected:0"),
            marker.replace("retain_ms:2", "retain_ms:0"),
        ):
            with self.subTest(invalid_write_fault_marker=replacement):
                bad = synthetic_log().replace(marker, replacement)
                result = runner.parse_loaded_correctness(bad)
                self.assertEqual(result["overall"], "INCOMPLETE")
                self.assertRegex(result["reason"], r"^[A-Za-z0-9 _:-]{1,128}$")


    def test_loaded_gc_roll_forward_recovery_is_mandatory(self):
        marker = (
            "PASS_LOADED_GC_ROLL_FORWARD_RECOVERY=foreground_writes:768 "
            "fault_nth:769 injected:1 retry_attempts:2 roll_forwards:1 "
            "destination_advances:0 reserve_initial:2 reserve_current:2 "
            "relocated_pages:510 verified_pages:512")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        oracle = (ROOT / "tests/tools/device-roundtrip.c").read_text()
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        make_interface = (
            ROOT / "tests/runtime/native/make-interface-test.py").read_text()
        self.assertIn(
            '--table "0 $GC_LOGICAL_SECTORS swapz $LOWER '
            '0 1 0 2 0 0 $GC_FAULT_WRITE 0"', deploy)
        self.assertIn(
            "GC_ROLL_FORWARD_FAULT_ORACLE=foreground_writes:768 "
            "fault_write:769 retry_attempts:2 verified_pages:512", deploy)
        self.assertIn(
            "foreground_writes != GC_RECOVERY_FOREGROUND_WRITES", oracle)
        self.assertIn("errno == ENOSPC", oracle)
        self.assertIn("FAIL: GC recovery retry=", oracle)
        self.assertIn(
            "PASS_LOADED_GC_ROLL_FORWARD_RECOVERY=foreground_writes:"
            "$GC_FOREGROUND_WRITES", deploy)
        self.assertIn("--gc-recovery-fault-probe", loaded)
        self.assertIn(marker, make_interface)
        self.assertIn(marker, synthetic_log())

        evidence = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["gc_roll_forwards"], 1)
        self.assertEqual(evidence["gc_roll_forward_retry_attempts"], 2)
        self.assertEqual(evidence["gc_roll_forward_relocated_pages"], 510)
        self.assertEqual(evidence["gc_roll_forward_verified_pages"], 512)

        for replacement in (
                "",
                marker.replace("injected:1", "injected:0"),
                marker.replace("retry_attempts:2", "retry_attempts:3"),
                marker.replace("roll_forwards:1", "roll_forwards:0"),
                marker.replace(
                    "destination_advances:0", "destination_advances:1"),
                marker.replace("reserve_current:2", "reserve_current:1"),
                marker.replace("relocated_pages:510", "relocated_pages:509"),
                marker.replace("verified_pages:512", "verified_pages:511"),
        ):
            with self.subTest(invalid_gc_roll_forward_marker=replacement):
                result = runner.parse_loaded_correctness(
                    synthetic_log().replace(marker, replacement))
                self.assertEqual(result["overall"], "INCOMPLETE")
                self.assertIn("roll-forward", result["reason"].lower())

    def test_loaded_read_fault_evidence_is_mandatory_and_pre_submission(self):
        marker = (
            "PASS_LOADED_SYNTHETIC_READ_FAULT=page:3072 injected:1 "
            "syscall_errno:EIO lower_read_delta:0 submitted_delta:0")
        deploy = (ROOT / "tests/tools/deploy-nullblk.sh").read_text()
        make_interface = (
            ROOT / "tests/runtime/native/make-interface-test.py").read_text()
        self.assertIn(
            'read_fault_submitted_delta=$((read_fault_submitted_after - '
            'read_fault_submitted_before))', deploy)
        self.assertIn(
            '(( read_fault_submitted_delta == 0 )) ||', deploy)
        self.assertIn(
            'PASS_LOADED_SYNTHETIC_READ_FAULT=page:$read_fault_seed_page injected:1 '
            'syscall_errno:EIO lower_read_delta:0 '
            'submitted_delta:$read_fault_submitted_delta',
            deploy)
        self.assertIn('"$READ_PROBE" "/dev/mapper/$DMNAME" "$read_fault_seed_page"', deploy)
        self.assertIn('--write-page "$read_fault_seed_page" 73', deploy)
        self.assertIn("read_fault_probe_rc", deploy)
        self.assertIn(marker, make_interface)
        self.assertIn(marker, synthetic_log())

        evidence = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(
            evidence["retained_read_fault"],
            "PRE_SUBMISSION_EIO_ZERO_LOWER_READ")
        self.assertEqual(evidence["retained_read_fault_page"], 3072)
        self.assertEqual(evidence["retained_read_fault_submitted_delta"], 0)

        for replacement in (
                "",
                marker.replace("page:3072", "page:0"),
                marker.replace("page:3072", "page:4096"),
                marker.replace("injected:1", "injected:0"),
                marker.replace("syscall_errno:EIO", "syscall_errno:0"),
                marker.replace("syscall_errno:EIO", "syscall_errno:ENOSPC"),
                marker.replace("lower_read_delta:0", "lower_read_delta:1"),
                marker.replace("submitted_delta:0", "submitted_delta:1"),
                marker.replace(
                    "lower_read_delta:0 submitted_delta:0",
                    "submitted_delta:0 lower_read_delta:0"),
        ):
            with self.subTest(invalid_read_fault_marker=replacement):
                result = runner.parse_loaded_correctness(
                    synthetic_log().replace(marker, replacement))
                self.assertEqual(result["overall"], "INCOMPLETE")
                self.assertRegex(result["reason"], r"^[A-Za-z0-9 _:-]{1,128}$")

    def test_mixed_sessions_end_before_later_benchmark_families(self):
        log = synthetic_log()
        sessions = runner.parse_sessions(log)
        self.assertEqual(len(sessions), 14)
        self.assertTrue(all(
            row["arms"]["swapz"]["kernel_write_path"][
                "lz4_acceleration"] == 1 and
            row["arms"]["swapz"]["kernel_write_path"][
                "delta64_rescue"] == runner.PRODUCTION_DELTA64_RESCUE
            for row in sessions))

        lz4_start = log.index("START_LZ4_ACCELERATION=")
        self.assertEqual(
            sessions,
            runner.parse_sessions(log[:lz4_start]))

        # An incomplete mixed pair remains incomplete when the next family
        # starts; its later JSON must never be attached to that pair.
        unfinished = "\n".join((
            "START_OWNED_RAM_REGIME=ssd_emulated",
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1",
            json.dumps(arm("swapz", mode=1, regime="ssd_emulated")),
            "START_LZ4_ACCELERATION=1",
            json.dumps(arm("off", mode=1, regime="ssd_emulated")),
        ))
        incomplete = runner.parse_sessions(unfinished)
        self.assertEqual(len(incomplete), 1)
        self.assertEqual(incomplete[0]["status"], "INCOMPLETE")
        self.assertEqual(set(incomplete[0]["arms"]), {"swapz"})

        for field, value in (("lz4_acceleration", 4),
                             ("delta64_rescue",
                              1 - runner.PRODUCTION_DELTA64_RESCUE)):
            mixed = runner.parse_sessions(log)
            mixed[-1]["arms"]["swapz"]["kernel_write_path"][field] = value
            with self.subTest(mixed_policy=field):
                self.assertEqual(
                    runner.benchmark_verdicts(mixed)["overall"],
                    "INCOMPLETE")

    def test_loaded_lz4_acceleration_sweep_is_separate_and_fail_closed(self):
        log = synthetic_log()
        sessions = runner.parse_lz4_acceleration(log)
        expected = [4 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE]
        self.assertEqual([row["lz4_acceleration"] for row in sessions], expected)
        verdict = runner.lz4_acceleration_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_LZ4_ACCELERATION_AB", verdict)
        self.assertEqual(verdict["matched_pairs"], 5)
        self.assertEqual(verdict["modes"]["1"]["observations"], 5)
        self.assertEqual(verdict["modes"]["4"]["observations"], 5)
        self.assertLess(
            verdict["paired"]["lz4_wall_change_fraction"]["high"], 0)
        self.assertGreater(
            verdict["paired"]["throughput_change_fraction"]["low"], 0)

        incomplete_log = log.replace("PASS_LZ4_ACCELERATION=4\n", "", 1)
        incomplete = runner.parse_lz4_acceleration(incomplete_log)
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(incomplete)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        duplicate = sessions + [sessions[0]]
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(duplicate)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        changed = runner.parse_lz4_acceleration(log)
        changed[1]["arms"]["swapz"]["kernel_write_path"]["lz4_acceleration"] = 1
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

        changed = runner.parse_lz4_acceleration(log)
        changed[2]["arms"]["off"]["trace_sha256"] = "d" * 64
        self.assertEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "INCONCLUSIVE")

        changed = runner.parse_lz4_acceleration(log)
        changed[0]["arms"]["off"]["lower_write_requests"] = True
        self.assertNotEqual(
            runner.lz4_acceleration_verdict(changed)["overall"],
            "PASS_LZ4_ACCELERATION_AB")

    def test_official_algorithm_tier_promotes_only_verified_physical_debug(self):
        """Exercise the real make-test runner boundary without device access."""
        source_sha = "a" * 40
        report_snapshots = []
        error_context = {
            "schema": "swapz-algorithm-pageout-diagnostic-v1",
            "phase": "anonymous_pageout",
            "gate": "mapper_usage",
            "mapper_used_kib": 0,
            "lower_write_bytes": 0,
            "zswap_enabled": "YES",
            "host_global_vmstat_delta": {
                "pswpout": 1, "pswpin": None, "zswpout": 1, "zswpwb": None},
        }

        class OperatorConsole(io.StringIO):
            def isatty(self):
                return True

        def synthetic_stage(title, command, result, **options):
            result["stages"].append({
                "name": title, "status": "PASS",
                "elapsed_s": 0.0, "exit_code": 0,
            })
            if options.get("parse_bench"):
                # The official runner reads this verdict even when all fake
                # loaded-stage telemetry is deliberately omitted.
                result["benchmarks"]["delta64_prepare"] = {
                    "overall": "NOT_RUN"}
            return 0

        def simulated_physical_probe(command, **options):
            self.assertEqual(Path(command[-1]).name, "algorithm-physical.py")
            self.assertIsNone(options.get("stdout"))
            error_stream = options["stderr"]
            # A privileged helper's raw identity-bearing stderr is private.
            error_stream.write("private_root_identity=NEVER_EXPORT\n")
            error_stream.write("PHYSICAL_ALGORITHM_DEBUG=" +
                               json.dumps(error_context) + "\n")
            return subprocess.CompletedProcess(command, 3)

        with mock.patch.object(
                runner, "report_host_identity",
                return_value={"status": "AVAILABLE"}), \
             mock.patch.object(runner, "git_sha", return_value=source_sha), \
             mock.patch.object(runner, "make_invocation",
                               return_value=(["make"], "fixture")), \
             mock.patch.object(runner, "tracked_source_checkout_preflight",
                               return_value=None), \
             mock.patch.object(runner, "run_stage",
                               side_effect=synthetic_stage), \
             mock.patch.object(runner, "qualification_artifact_digests",
                               return_value={"status": "AVAILABLE"}), \
             mock.patch.object(runner, "owner_qualification_artifacts_available",
                               return_value=True), \
             mock.patch.object(runner, "required_benchmark_gates_pass",
                               return_value=True), \
             mock.patch.object(runner, "official_pass_binding_refusal",
                               return_value=None), \
             mock.patch.object(runner, "lane_gap_attribution_rows",
                               return_value=[]), \
             mock.patch.object(runner, "goal_scorecard",
                               return_value={"overall": "UNAVAILABLE"}), \
             mock.patch.object(runner, "write_algorithm_ram_development_evidence",
                               return_value=(ROOT / "build/tests/nonexistent-private-fixture",
                                             "a" * 32)), \
             mock.patch.object(runner.subprocess, "run",
                               side_effect=simulated_physical_probe), \
             mock.patch.object(runner, "write_report",
                               side_effect=lambda report: report_snapshots.append(
                                   json.loads(json.dumps(report)))), \
             mock.patch.multiple(
                 runner,
                 print_bench=mock.Mock(),
                 publish=mock.Mock(return_value="fixture"),
                 write_failure_diagnostic=mock.Mock(return_value=None),
                 refresh_history=mock.Mock(
                     return_value="NOT UPDATED: fixture")), \
             mock.patch.object(runner.sys, "stdin",
                               mock.Mock(isatty=lambda: True)), \
             mocked_main_sync(source_sha), \
             contextlib.redirect_stdout(OperatorConsole()) as output:
            self.assertEqual(runner._run_qualification(
                mock.Mock(kdir="/unused", tier="algorithm"),
                {"status": "PASS", "reason": "fixture",
                 "source_sha": source_sha, "head_sha": source_sha}), 3)
            console = output.getvalue()

        self.assertEqual(report_snapshots[0]["overall"], "FAIL")
        self.assertEqual(report_snapshots[0]["algorithm_real_swap"][
            "diagnostic"], error_context)
        self.assertIn("gate=mapper_usage", console)
        self.assertIn("zswap_enabled=YES", console)
        self.assertNotIn("NEVER_EXPORT", console)
        self.assertIn("Physical trial cleanup:", console)
        self.assertIn("Overall qualification: FAIL", console)

    def test_source_admission_diagnostic_rejects_untrusted_privileged_output(self):
        prefix = "PHYSICAL_ALGORITHM_SOURCE_ADMISSION="
        reason = "canonical_source_advanced"
        expected = {
            "schema": "swapz-algorithm-source-admission-v1",
            "phase": "before_consent",
            "reason": reason,
        }
        self.assertEqual(runner.parse_algorithm_source_admission_diagnostic(
            "private_host=NEVER_EXPORT\n" + prefix + reason), expected)
        for accepted in (
                "canonical_source_raced", "local_checkout_not_main",
                "local_tracking_main_mismatch",
                "canonical_source_verification_unavailable",
                "local_checkout_changed_kind_generated_report",
                "local_checkout_changed_kind_tracked_source_generated_report_untracked"):
            with self.subTest(accepted=accepted):
                self.assertEqual(
                    runner.parse_algorithm_source_admission_diagnostic(
                        prefix + accepted)["reason"], accepted)
        for invalid in (
                prefix + reason + "\n" + prefix + reason,
                prefix + reason + "\n" + prefix + "no_sudo",
                prefix + "canonical_source_advanced /private/path",
                prefix + "local_checkout_changed_kind_private_path",
                prefix + "local_checkout_changed_kind_tracked_source_unclassified",
                prefix + "", prefix + "unknown", "no source-owned marker",
                "P" * 32769 + "\n" + prefix + reason):
            with self.subTest(invalid=invalid[:85]):
                self.assertIsNone(
                    runner.parse_algorithm_source_admission_diagnostic(invalid))

    def test_official_algorithm_tier_publishes_source_admission_refusal(self):
        """A blocked physical pre-consent run retains its cause in JSON."""
        source_sha = "a" * 40
        reports = []

        class OperatorConsole(io.StringIO):
            def isatty(self):
                return True

        def stage_pass(title, command, report, **options):
            report["stages"].append({
                "name": title, "status": "PASS",
                "elapsed_s": 0.0, "exit_code": 0,
            })
            if options.get("parse_bench"):
                report["benchmarks"]["delta64_prepare"] = {
                    "overall": "NOT_RUN"}
            return 0

        def early_refusal(command, **options):
            self.assertEqual(Path(command[-1]).name, "algorithm-physical.py")
            self.assertIsNone(options.get("stdout"))
            self.assertIsNotNone(options.get("stderr"))
            options["stderr"].write("private_host=NEVER_EXPORT\n")
            options["stderr"].write(
                "PHYSICAL_ALGORITHM_SOURCE_ADMISSION=canonical_source_advanced\n")
            return subprocess.CompletedProcess(command, 2)

        patches = (
            mock.patch.object(runner, "report_host_identity",
                              return_value={"status": "AVAILABLE"}),
            mock.patch.object(runner, "git_sha", return_value=source_sha),
            mock.patch.object(runner, "make_invocation",
                              return_value=(["make"], "fixture")),
            mock.patch.object(runner, "tracked_source_checkout_preflight",
                              return_value=None),
            mock.patch.object(runner, "run_stage", side_effect=stage_pass),
            mock.patch.object(runner, "qualification_artifact_digests",
                              return_value={"status": "AVAILABLE"}),
            mock.patch.object(runner, "owner_qualification_artifacts_available",
                              return_value=True),
            mock.patch.object(runner, "required_benchmark_gates_pass",
                              return_value=True),
            mock.patch.object(runner, "lane_gap_attribution_rows",
                              return_value=[]),
            mock.patch.object(runner, "goal_scorecard",
                              return_value={"overall": "UNAVAILABLE"}),
            mock.patch.object(runner, "write_algorithm_ram_development_evidence",
                              return_value=(
                                  ROOT / "build/tests/nonexistent-private-fixture",
                                  "a" * 32)),
            mock.patch.object(runner.subprocess, "run",
                              side_effect=early_refusal),
            mock.patch.object(runner, "write_report",
                              side_effect=lambda report: reports.append(
                                  json.loads(json.dumps(report)))),
            mock.patch.multiple(
                runner,
                print_bench=mock.Mock(),
                publish=mock.Mock(return_value="fixture"),
                write_failure_diagnostic=mock.Mock(return_value=None),
                refresh_history=mock.Mock(return_value="NOT UPDATED: fixture")),
            mock.patch.object(runner.sys, "stdin",
                              mock.Mock(isatty=lambda: True)),
        )
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(mocked_main_sync(source_sha))
            output = stack.enter_context(
                contextlib.redirect_stdout(OperatorConsole()))
            self.assertEqual(runner._run_qualification(
                mock.Mock(kdir="/unused", tier="algorithm"),
                {"status": "PASS", "reason": "fixture",
                 "source_sha": source_sha, "head_sha": source_sha}), 2)
            console = output.getvalue()
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["overall"], "INCOMPLETE")
        self.assertEqual(reports[0]["algorithm_real_swap"], {
            "overall": "NOT_RUN",
            "reason": "canonical_source_advanced",
            "diagnostic": {
                "schema": "swapz-algorithm-source-admission-v1",
                "phase": "before_consent",
                "reason": "canonical_source_advanced",
            },
        })
        self.assertEqual([stage["status"] for stage in reports[0]["stages"]],
                         ["PASS"] * 5)
        self.assertIn("phase=before_consent reason=canonical_source_advanced",
                      console)
        self.assertNotIn("NEVER_EXPORT", console)
        self.assertIn("Tested Git commit:", console)

    def test_physical_pageout_debug_is_source_validated_and_redacted(self):
        report = {
            "schema": "swapz-algorithm-pageout-diagnostic-v1",
            "phase": "anonymous_pageout",
            "gate": "lower_write",
            "mapper_used_kib": 8192,
            "lower_write_bytes": 0,
            "zswap_enabled": "YES",
            "host_global_vmstat_delta": {
                "pswpout": 8, "pswpin": 0, "zswpout": 8, "zswpwb": None},
        }
        prefix = "PHYSICAL_ALGORITHM_DEBUG="
        marker = prefix + json.dumps(report, separators=(",", ":"))
        private_path = "/PRIVATE/HOST/KEEP_PRIVATE"
        self.assertEqual(runner.parse_algorithm_pageout_diagnostic(
            private_path + "\n" + marker), report)
        self.assertNotIn(private_path, json.dumps(
            runner.parse_algorithm_pageout_diagnostic(
                private_path + "\n" + marker)))
        invalid = [
            marker + "\n" + marker,
            prefix + '{"schema":"a","schema":"b"}',
            prefix + '{"schema":"wrong"}',
            prefix + json.dumps({**report, "gate": "mapper_usage"}),
            prefix + json.dumps({**report, "mapper_used_kib": True}),
            prefix + json.dumps({**report, "lower_write_bytes": -1}),
            prefix + json.dumps({**report, "zswap_enabled": private_path}),
            prefix + json.dumps({**report,
                                 "host_global_vmstat_delta": {
                                     **report["host_global_vmstat_delta"],
                                     "private_path": private_path}}),
            prefix + json.dumps({**report, "secret": private_path}),
            "random stderr without an authenticated marker",
            "X" * 32769 + "\n" + marker,
        ]
        for output in invalid:
            with self.subTest(output=output[:70]):
                self.assertIsNone(
                    runner.parse_algorithm_pageout_diagnostic(output))
        missing_swap = {
            **report, "gate": "mapper_usage", "mapper_used_kib": 0,
            "lower_write_bytes": 4096,
        }
        self.assertEqual(runner.parse_algorithm_pageout_diagnostic(
            prefix + json.dumps(missing_swap)), missing_swap)

    def test_failure_diagnostic_collects_read_rounds_privately(self):
        fast_sessions = runner.parse_read_coalesce_ab(synthetic_log())
        serial_sessions = runner.parse_sd_read_coalesce_ab(synthetic_log())
        self.assertEqual(len(fast_sessions), 10)
        self.assertEqual(len(serial_sessions), 10)
        source_sha = "a" * 40
        result = {
            "overall": "FAIL",
            "source_sha": source_sha,
            "tested_commit_sha": source_sha,
            "host_identity": {
                "architecture": "fixture-architecture",
                "private_host": "NEVER_EXPORT",
            },
            "kernel_release": "fixture-kernel",
            "algorithm_real_swap": {
                "overall": "FAIL",
                "reason": "physical_oracle_or_cleanup_failure",
            },
            "stages": [{
                "name": "Owned RAM smoke + mixed/QD pilot",
                "status": "FAIL",
                "failed_phase": "adjacent READ coalescing A/B evidence",
                "diagnostic": "merge-on arm executed no sequential READ coalescing",
            }],
            "benchmarks": {
                "read_coalesce_ab_sessions": fast_sessions,
                "sd_read_coalesce_ab_sessions": serial_sessions,
                "read_coalesce_ab": {"overall": "INCOMPLETE"},
                "sd_read_coalesce_ab": {"overall": "PASS"},
            },
        }
        with tempfile.TemporaryDirectory(
                prefix="report-private-failure-",
                dir=ROOT / "build/tests") as sandbox:
            original_root = runner.ROOT
            runner.ROOT = Path(sandbox)
            try:
                filename = runner.write_failure_diagnostic(
                    result, "GIT_SYNC_FAILED: phase=push "
                    "reason=remote_advanced")
                self.assertIsNotNone(filename)
                path = runner.ROOT / filename
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                saved = json.loads(path.read_text())
                self.assertEqual(saved["tested_commit_sha"], source_sha)
                self.assertEqual(saved["architecture"], "fixture-architecture")
                self.assertEqual(saved["kernel_release"], "fixture-kernel")
                self.assertEqual(saved["physical_trial"]["overall"], "FAIL")
                self.assertEqual(len(saved["fast_sessions"]), 10)
                self.assertEqual(len(saved["serial_sessions"]), 10)
                self.assertEqual(saved["fast_sessions"][1]["read_coalesce"], 1)
                kernel = saved["fast_sessions"][1]["passes"]["sequential"][
                    "kernel_read_path"]
                self.assertIn("parallel_read_coalesce_skip_gap", kernel)
                self.assertIn("host_cpu",
                              saved["fast_sessions"][1]["passes"]["sequential"])
                self.assertNotIn("NEVER_EXPORT", path.read_text())
                self.assertNotIn("host_identity", saved)
                # A physical admission refusal can leave all five RAM stages
                # PASS while the overall result remains INCOMPLETE.
                incomplete = {
                    **result,
                    "overall": "INCOMPLETE",
                    "stages": [
                        {"name": name, "status": "PASS"}
                        for name in runner.OFFICIAL_STAGE_NAMES
                    ],
                    "algorithm_real_swap": {
                        "overall": "NOT_RUN",
                        "reason": "physical_trial_declined_or_blocked",
                    },
                }
                incomplete_path = runner.write_failure_diagnostic(
                    incomplete, "ARCHIVED_GIT: history-only")
                self.assertIsNotNone(incomplete_path)
                incomplete_saved = json.loads(
                    (runner.ROOT / incomplete_path).read_text())
                self.assertEqual(incomplete_saved["overall"], "INCOMPLETE")
                self.assertEqual(incomplete_saved["stages"], [])
                self.assertEqual(
                    incomplete_saved["physical_trial"]["overall"], "NOT_RUN")
                self.assertIsNone(runner.write_failure_diagnostic(
                    {**result, "overall": "PASS"}, "SYNCED_GIT"))
            finally:
                runner.ROOT = original_root

    def test_missing_sequential_coalescing_reports_measured_counters(self):
        # The real Lubuntu failure can have adjacent/parallel candidates
        # while one merge-on round coalesces nothing. Keep the mandatory
        # failure gate and retain its measured attribution in the report.
        sessions = runner.parse_read_coalesce_ab(synthetic_log())
        failing_index = next(
            index for index, session in enumerate(sessions)
            if session["read_coalesce"] == 1)
        kernel = sessions[failing_index]["swapz"]["passes"][
            "sequential"]["kernel_read_path"]
        kernel["parallel_read_coalesced_pairs"] = 0
        kernel["parallel_read_coalesced_reqs_saved"] = 0
        kernel["parallel_read_coalesced_blocks"] = 0
        kernel["parallel_read_coalesce_skip_gap"] = 29
        verdict = runner.read_coalesce_ab_verdict(sessions)
        self.assertEqual(verdict["overall"], "INCOMPLETE")
        self.assertIn("merge-on arm executed no sequential READ coalescing",
                      verdict["reason"])
        self.assertIn(f"round={failing_index + 1}", verdict["reason"])
        self.assertIn("gap=29", verdict["reason"])
        self.assertIn("adjacent=", verdict["reason"])
        rounds = runner.read_coalesce_failure_rounds(sessions)
        self.assertEqual(len(rounds), 30)
        self.assertIn(
            f"round={failing_index + 1} seq: gap=29",
            "\n".join(rounds))
        self.assertTrue(all(len(line) <= 96 for line in rounds))
        invalid = runner.read_coalesce_failure_rounds([{
            "read_coalesce": 1, "swapz": {"passes": {
                "sequential": {"kernel_read_path": {
                    "parallel_read_pairs": "/private/SECRET"}},
                "seeded_random": {"kernel_read_path": {}},
            }},
        }])
        self.assertEqual(invalid, [
            "        round=1 seq: counters=unavailable",
            "        round=1 rand: counters=unavailable",
        ])

    def test_coalesce_failure_prints_all_measured_rounds_not_just_first(self):
        lines = synthetic_log().splitlines()
        in_fast_on_arm = False
        modified = False
        for index, line in enumerate(lines):
            if line == "START_READ_COALESCE_AB=1" and not modified:
                in_fast_on_arm = True
            elif in_fast_on_arm and line.startswith("{"):
                evidence = json.loads(line)
                if evidence.get("candidate") != "swapz":
                    continue
                sequential = evidence["packed_read"]["passes"][
                    "sequential"]["kernel_read_path"]
                sequential["parallel_read_coalesced_pairs"] = 0
                sequential["parallel_read_coalesced_reqs_saved"] = 0
                sequential["parallel_read_coalesced_blocks"] = 0
                sequential["parallel_read_coalesce_skip_gap"] = 30
                lines[index] = json.dumps(evidence, separators=(",", ":"))
                modified = True
                break
        self.assertTrue(modified)
        transcript = "\n".join(lines) + "\n"
        report = {"stages": [], "benchmarks": {"sessions": [],
                 "verdicts": {}}}
        fake_process = FakeStreamingProcess(transcript)
        with mock.patch.object(
                runner.subprocess, "Popen", return_value=fake_process), \
             contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertEqual(
                runner.run_stage(
                    "Owned RAM smoke + mixed/QD pilot", ["unused"],
                    report, parse_bench=True), 1)
        stage = report["stages"][-1]
        self.assertEqual(
            stage["failed_phase"], "adjacent READ coalescing A/B evidence")
        shown = console.getvalue()
        self.assertIn("Merge-on round evidence (kernel counters;", shown)
        self.assertIn("seq: gap=30", shown)
        self.assertIn("noncontig=", shown)
        self.assertIn("rand: chain3=", shown)
        self.assertIn("Safe next step: retain the failed gate", shown)
        self.assertEqual(
            stage["diagnostic"],
            report["benchmarks"]["read_coalesce_ab"]["reason"])
        self.assertNotIn("/private/", shown)

    def test_immutable_inputs_and_alternating_arm_order(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(len(sessions), 14)
        coalesce = runner.parse_read_coalesce_ab(synthetic_log())
        self.assertEqual([row["read_coalesce"] for row in coalesce],
                         list(runner.CONFIRMATION_SEQUENCE))
        coalesce_diag = runner.read_coalesce_ab_verdict(coalesce)
        self.assertEqual(coalesce_diag["overall"],
                         "PASS_READ_COALESCE_AB_CONFIRMATION")
        self.assertEqual(coalesce_diag["matched_pairs"], 5)
        self.assertEqual(
            coalesce_diag["modes"]["0"]["sequential"][
                "parallel_read_coalesced_pairs"], 0)
        self.assertGreater(
            coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesced_reqs_saved"], 0)
        self.assertEqual(
            coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesce_skip_other"], 0)

        parallel_read = runner.parse_parallel_read_ab(synthetic_log())
        self.assertEqual([row["parallel_reads"] for row in parallel_read],
                         list(runner.CONFIRMATION_SEQUENCE))
        parallel_diag = runner.parallel_read_ab_verdict(parallel_read)
        self.assertEqual(parallel_diag["overall"],
                         "PASS_PARALLEL_READ_AB_EVIDENCE", parallel_diag)
        self.assertEqual(parallel_diag["matched_pairs"], 5)
        self.assertEqual(
            parallel_diag["modes"]["0"]["mixed"]["async_batches"], 0)
        self.assertGreater(
            parallel_diag["modes"]["1"]["mixed"]["async_batches"], 0)
        self.assertIn("write_mbps", parallel_diag["paired"]["mixed"])
        self.assertIn("sequential", parallel_diag["paired"]["packed"])

        sd_coalesce = runner.parse_sd_read_coalesce_ab(synthetic_log())
        self.assertEqual([row["read_coalesce"] for row in sd_coalesce],
                         list(runner.CONFIRMATION_SEQUENCE))
        sd_coalesce_diag = runner.sd_read_coalesce_ab_verdict(sd_coalesce)
        self.assertEqual(sd_coalesce_diag["overall"],
                         "PASS_SD_READ_COALESCE_AB_CONFIRMATION")
        self.assertEqual(sd_coalesce_diag["matched_pairs"], 5)
        self.assertGreater(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesced_reqs_saved"], 0)
        self.assertEqual(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "read_worker_cpu_ns"], 0)
        self.assertEqual(
            sd_coalesce_diag["modes"]["1"]["sequential"][
                "parallel_read_coalesce_skip_other"], 0)

        write_depth = runner.parse_write_pipeline_depth(synthetic_log())
        self.assertEqual(
            [row["write_pipeline_depth"] for row in write_depth],
            [2 if bit else 1 for bit in runner.CONFIRMATION_SEQUENCE])
        depth_diag = runner.write_pipeline_depth_verdict(write_depth)
        self.assertEqual(depth_diag["overall"],
                         "PASS_WRITE_PIPELINE_DEPTH_EVIDENCE", depth_diag)
        self.assertEqual(depth_diag["matched_pairs"], 5)
        self.assertEqual(depth_diag["modes"]["2"]["pipeline_active_max"], 2)

        delta64_pilot = runner.parse_delta64_prepare_sessions(synthetic_log())
        expected_workers = [2 if bit else 1
                            for bit in runner.CONFIRMATION_SEQUENCE]
        self.assertEqual([row["workers"] for row in delta64_pilot],
                         expected_workers)
        delta64_diag = runner.delta64_prepare_verdict(delta64_pilot)
        self.assertEqual(delta64_diag["overall"],
                         "PASS_DELTA64_PREPARE_AB", delta64_diag)
        self.assertEqual(delta64_diag["matched_pairs"], 5)
        self.assertEqual(delta64_diag["modes"]["1"]["prepare_parallel_starts"], 0)
        self.assertGreater(
            delta64_diag["modes"]["2"]["prepare_parallel_starts"], 0)
        self.assertGreater(
            delta64_diag["modes"]["2"]["prepare_active_max"], 1)
        self.assertIn("throughput_change_fraction", delta64_diag["paired"])

        self.assertEqual(
            [s["async_prepare"] for s in sessions],
            [0, 1, 1, 0] + list(runner.CONFIRMATION_SEQUENCE))
        self.assertEqual(
            [s["regime"] for s in sessions],
            ["sd_emulated"] * 4 + ["ssd_emulated"] * 10)
        self.assertEqual([s["order"] for s in sessions],
                         ["off-first", "swapz-first"] * 7)
        self.assertTrue(all(s["status"] == "PASS" for s in sessions))
        for j, session in enumerate(sessions):
            self.assertEqual(session["device_model"],
                             {k: runner.MODEL_SPECS[session["regime"]][k]
                              for k in ("cap_mib_s", "completion_nsec", "irqmode",
                                        "queue_mode", "submit_queues",
                                        "hw_queue_depth")})
            if session["async_prepare"]:
                self.assertEqual(session["overlap_starts"], 42)
            else:
                self.assertNotIn("overlap_starts", session)
        self.assertNotIn("device_identity", json.dumps(sessions))
        self.assertNotIn("PRIVATE_DEVICE_MUST_NOT_ESCAPE", json.dumps(sessions))
        self.assertTrue(all("kernel_status" not in session for session in sessions))

    def test_write_saturation_evidence_repeats_fast_qd4_qd8_and_qd32(self):
        sessions = runner.parse_write_saturation(synthetic_log())
        self.assertEqual(len(sessions), 48)
        verdict = runner.write_saturation_verdict(sessions)
        self.assertEqual(verdict["overall"], "PASS_WRITE_SATURATION_EVIDENCE")
        self.assertAlmostEqual(
            verdict["model_limits"]["sd_emulated"]["effective_4k_model_ceiling_mbps"],
            4.096, places=3)
        self.assertAlmostEqual(
            verdict["model_limits"]["ssd_emulated"]["cap_decimal_mbps"],
            80 * (1 << 20) / 1_000_000.0, places=3)
        self.assertEqual(verdict["serial_qd32_matched_pairs"], 5)
        self.assertEqual(verdict["fast_qd8_matched_pairs"], 5)
        self.assertEqual(verdict["fast_qd32_matched_pairs"], 5)
        self.assertEqual(
            verdict["serial_qd32_paired"]["throughput_change_fraction"]["n"], 5)
        self.assertEqual(
            verdict["fast_qd8_paired"]["throughput_change_fraction"]["n"], 5)
        self.assertEqual(
            verdict["fast_qd32_paired"]["throughput_change_fraction"]["n"], 5)
        self.assertIn("PAIRED_95PCT_CI", verdict["confidence"])
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["retained_burst_target"], 4)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][4]["retained_burst_target"], 8)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["window_delta"]["win3_4"], 8)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["timed_window_delta"]
            ["win1_pack_ready"], 1)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][2]["timed_window_delta"]
            ["deadline_worker_empty"], 1)
        self.assertEqual(
            verdict["regimes"]["sd_emulated"][3]["preparation_delta"]
            ["prep_producer_tail_claims"], 3)
        self.assertEqual(
            [(p["qd"], p["mode"]) for p in verdict["regimes"]["sd_emulated"]],
            [(1, "sync"), (1, "async"), (4, "sync"), (4, "async"),
             (8, "sync"), (8, "async"), (32, "sync"), (32, "async")])
        serial_qd32 = [p for p in verdict["regimes"]["sd_emulated"]
                       if p["qd"] == 32]
        self.assertEqual([p["observations"] for p in serial_qd32], [5, 5])
        fast_qd4 = [p for p in verdict["regimes"]["ssd_emulated"]
                    if p["qd"] == 4]
        fast_qd8 = [p for p in verdict["regimes"]["ssd_emulated"]
                    if p["qd"] == 8]
        fast_qd32 = [p for p in verdict["regimes"]["ssd_emulated"]
                     if p["qd"] == 32]
        self.assertEqual([p["observations"] for p in fast_qd4], [5, 5])
        self.assertEqual([p["observations"] for p in fast_qd8], [5, 5])
        self.assertEqual([p["observations"] for p in fast_qd32], [5, 5])
        broken = runner.parse_write_saturation(synthetic_log())
        broken[0]["arms"]["off"]["logical_read_bytes"] = 4096
        self.assertEqual(runner.write_saturation_verdict(broken)["overall"],
                         "INCOMPLETE")
        broken = runner.parse_write_saturation(synthetic_log())
        broken[0]["arms"]["off"]["replay_mode"] = "qd-waves"
        self.assertEqual(runner.write_saturation_verdict(broken)["overall"],
                         "INCOMPLETE")
        for field, bad_value in (
                ("source_sha", "b" * 40),
                ("fixture_sha256", "c" * 64),
                ("trace_sha256", "d" * 64)):
            with self.subTest(provenance=field):
                broken = runner.parse_write_saturation(synthetic_log())
                broken[0]["arms"]["off"][field] = bad_value
                self.assertEqual(
                    runner.write_saturation_verdict(broken)["overall"],
                    "INCONCLUSIVE")

    def test_standard_write_only_policy_is_pinned(self):
        for field, value in (("lz4_acceleration", 2),
                              ("delta64_lz4_acceleration", 2),
                              ("write_pipeline_depth", 2),
                             ("delta64_rescue",
                              1 - runner.PRODUCTION_DELTA64_RESCUE)):
            sessions = runner.parse_write_saturation(synthetic_log())
            sessions[0]["arms"]["swapz"]["kernel_write_path"][field] = value
            with self.subTest(policy=field):
                self.assertEqual(
                    runner.write_saturation_verdict(sessions)["overall"],
                    "INCOMPLETE")

    def test_paired_benchmark_provenance_mismatch_is_inconclusive(self):
        for field, bad_value in (
                ("source_sha", "b" * 40),
                ("fixture_sha256", "c" * 64),
                ("trace_sha256", "d" * 64)):
            with self.subTest(provenance=field):
                sessions = runner.parse_sessions(synthetic_log())
                sessions[0]["arms"]["off"][field] = bad_value
                self.assertEqual(
                    runner.benchmark_verdicts(sessions)["overall"],
                    "INCONCLUSIVE")

    def test_slow_model_gain_and_fast_model_loss_are_both_visible(self):
        data = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        self.assertEqual(data["overall"], "PASS_BOUNDED_RAM_MATRIX")
        slow = data["regimes"]["sd_emulated"]
        fast = data["regimes"]["ssd_emulated"]
        self.assertEqual(slow["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_GAIN_PRELIMINARY")
        self.assertEqual(fast["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_LOSS_PRELIMINARY")
        self.assertEqual(fast["interpretation"],
                         "SYNTHETIC_RAM_MODEL_ONLY_NOT_PHYSICAL_MEDIA")
        self.assertEqual(data["regimes"]["sd_emulated"]["device_model"]["completion_nsec"],
                         1000000)
        self.assertEqual(data["regimes"]["ssd_emulated"]["device_model"]["cap_mib_s"],
                         80)
        self.assertEqual(
            data["workload_opportunity"]["resident_duplicate_write_ops"], 30)
        self.assertEqual(
            data["workload_opportunity"]["nonzero_same_filled_write_ops"], 5)
        self.assertAlmostEqual(
            slow["criteria"]["sync"]["lower_write_saved_fraction"], .375)
        self.assertEqual(
            slow["criteria"]["async_vs_sync"]["write_throughput"],
            "NO_SIGNIFICANT_ASYNC_GAIN")
        self.assertAlmostEqual(
            slow["columns"]["sync"]["sequential_4mib_s"], .9)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_reqs"], 1024)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_payload_reqs"], 512)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_copy_wall_ns"], 4000000)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_copy_bytes"], 4194304)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_engine_nonio_wall_ns"], 6000000)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_cache_hits"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_lru_hits"], 100)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_lookups"], 1024)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_hits"], 100)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_primary_hits"], 80)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_secondary_hits"], 20)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_probes"], 7700)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_set_replacements"], 12)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_copy_bytes"], 207200)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_full_extent_reqs"], 200)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_full_cache_hits"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_two_block_skips"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_pairs"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_same_extent_pairs"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_async_batches"], 32)
        self.assertEqual(slow["columns"]["sync"]["sequential_parallel_read_async_slots"], 64)
        self.assertEqual(slow["columns"]["sync"]["mixed_physical_write_reqs"], 5)
        self.assertEqual(slow["columns"]["async"]["mixed_write_wait_gt4ms"], 1)
        self.assertEqual(slow["columns"]["sync"]["mixed_write_copy_wall_ns"], 3000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_ordered_lz4_wall_ns"], 15000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lz4_wall_ns"], 5000000)
        self.assertEqual(slow["columns"]["async"]["mixed_ordered_write_copy_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_write_copy_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["async"]["mixed_write_copy_bytes"], 6000000)
        self.assertEqual(slow["columns"]["async"]["mixed_direct_lz4_input_pages"], 3000)
        self.assertEqual(slow["columns"]["sync"]["mixed_window_commit_nonio_wall_ns"], 10000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_plan_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_pack_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_wall_ns"], 3000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_crc_wall_ns"], 1000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_engine_publish_auth_wall_ns"], 2000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_samples"], 5)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_start_queued"], 4)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_lower_write_end_queued"], 1)
        self.assertEqual(
            slow["columns"]["async"]["lower_inflight_write_time_weighted"], .5)
        self.assertEqual(slow["columns"]["async"]["lower_inflight_write_peak"], 1)
        self.assertEqual(slow["columns"]["async"]["mixed_pipeline_active_mean"], .4)
        self.assertEqual(slow["columns"]["async"]["mixed_pipeline_active_peak"], 1)
        self.assertEqual(slow["columns"]["sync"]["mixed_pipeline_active_mean"], 0)
        self.assertEqual(slow["columns"]["sync"]["mixed_lower_write_wall_ns"], 30000000)
        self.assertEqual(slow["columns"]["sync"]["mixed_ordered_worker_wall_ns"], 52000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_worker_wall_ns"], 5000000)
        self.assertEqual(slow["columns"]["async"]["mixed_ordered_worker_cpu_ns"], 16000000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_worker_cpu_ns"], 3000000)
        self.assertEqual(slow["columns"]["async"]["mixed_read_worker_cpu_ns"], 1000000)
        self.assertEqual(slow["columns"]["async"]["mixed_engine_prehashed_records"], 2500)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_snapshot_crc_wall_ns"], 250000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_pause_crc_wall_ns"], 100000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_batch_resume_crc_wall_ns"], 150000)
        self.assertEqual(slow["columns"]["async"]["mixed_prep_wait_wall_ns"], 500000)
        self.assertEqual(
            slow["columns"]["async"]["mixed_prep_lower_write_overlap_ns"], 5000000)
        self.assertEqual(slow["preparation_counters"]["prep_wave_kicks"], 5)
        self.assertEqual(slow["kernel_counters"]["single_pack_deferrals"], 24)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_extensions"], 6)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_tail_flushes"], 5)
        self.assertEqual(slow["kernel_counters"]["accepted_burst_read_caps"], 4)
        self.assertEqual(slow["kernel_counters"]["windows"], 20)
        self.assertEqual(slow["kernel_counters"]["close_pack_ready"], 14)
        self.assertEqual(slow["kernel_counters"]["pack_close_tail_target"], 5)
        self.assertEqual(slow["kernel_counters"]["pack_close_tail_target_le4"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target"], 6)
        self.assertEqual(slow["kernel_counters"]["pack_close_service_dry"], 3)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_admission"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_worker"], 2)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target_le4"], 2)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_target_5_8"], 4)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_count_le4"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_count_5_8"], 5)
        self.assertEqual(slow["kernel_counters"]["pack_close_burst_overshoot"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_tail_samples"], 6)
        self.assertEqual(slow["kernel_counters"]["pack_tail_zero_inflight"], 1)
        self.assertEqual(slow["kernel_counters"]["pack_tail_zero_idle"], 1.5)
        self.assertEqual(slow["kernel_counters"]["burst_target_grows"], 2.5)
        self.assertEqual(slow["kernel_counters"]["burst_target_shrinks"], 1.5)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_windows"], 1)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_records"], 6)
        self.assertEqual(slow["kernel_counters"]["k1_ready_wait_pack_ready"], 1)
        self.assertEqual(slow["kernel_counters"]["close_idle"], 4)
        self.assertEqual(slow["kernel_counters"]["close_deadline"], 2)
        self.assertEqual(slow["kernel_counters"]["win1_deadline"], 2)
        self.assertEqual(slow["kernel_counters"]["win1_pack_ready"], 1)
        self.assertEqual(slow["kernel_counters"]["win1_pack_tail_target"], 1)
        self.assertEqual(slow["kernel_counters"]["win1_pack_read_bypass"], 0)
        self.assertEqual(slow["kernel_counters"]["win1_pack_wave_interrupted"], 0)
        self.assertEqual(slow["kernel_counters"]["win1_idle"], 1)
        self.assertEqual(slow["kernel_counters"]["deadline_before_bio"], 1)
        self.assertEqual(slow["kernel_counters"]["deadline_worker_empty"], 1)
        self.assertEqual(slow["kernel_gauges"]["retained_burst_target"], 8)
        self.assertEqual(data["gc"], "SEPARATE_LOADED_EVIDENCE_REQUIRED")
        self.assertEqual(data["physical_media"], "NOT_TESTED")
        self.assertIn("scheduler-accounted", data["cpu_scope"])
        self.assertIn("PROXY_ONLY", data["endurance"])

    def test_two_choice_metadata_accounting_is_fail_closed(self):
        record = {"read_meta_set_lookups": 1024, "read_meta_set_hits": 100,
                  "read_meta_set_probes": 7700, "read_meta_primary_hits": 80,
                  "read_meta_secondary_hits": 20}
        self.assertTrue(runner.read_metadata_counters_consistent(record))
        for change in ({"read_meta_secondary_hits": 21}, {"read_meta_primary_hits": -1},
                       {"read_meta_set_hits": 1025}, {"read_meta_set_probes": 1800},
                       {"read_meta_set_probes": 8200}):
            self.assertFalse(runner.read_metadata_counters_consistent(dict(record, **change)))
        del record["read_meta_secondary_hits"]
        self.assertFalse(runner.read_metadata_counters_consistent(record))

    def test_submitter_preparation_accounting_is_fail_closed(self):
        record = timed_kernel_write(mode=1)
        record.update({
            "submitter_prepare": 1,
            "submitter_prepare_lanes": 8,
            "submitter_prepare_active": 0,
            "submitter_prepare_active_max": 4,
            "submitter_prepare_claims": 100,
            "submitter_prepare_lane_misses": 3,
            "submitter_prepare_page_misses": 2,
            "submitter_owner_deferrals": 7,
            "submitter_prepare_pages": 80,
            "submitter_prepare_wall_ns": 3000000,
            "submitter_prepare_cpu_ns": 2000000,
            "submitter_lz4_wall_ns": 1000000,
            "submitter_copy_wall_ns": 500000,
            "submitter_copy_bytes": 80 * 4096,
            "submitter_crc_wall_ns": 200000,
            "lz4_wall_ns": 21000000,
            "write_copy_wall_ns": 3500000,
        })
        self.assertIsNone(runner.timed_window_error(record))
        for invalid in (
                {"submitter_prepare": 0},
                {"submitter_prepare_lanes": 0},
                {"submitter_prepare_lanes": 9},
                {"submitter_prepare_active": 1},
                {"submitter_prepare_active_max": 9},
                {"submitter_prepare_pages": 101},
                {"submitter_copy_bytes": 1},
                {"submitter_prepare_wall_ns": 1000000},
                {"lz4_wall_ns": 20000000},
                {"write_copy_wall_ns": 3000000},
                {"work_conserving_hand_records": 0},
                {"work_conserving_hand_records": 16},
                {"work_conserving_hand_records": 64}):
            with self.subTest(invalid=invalid):
                self.assertIsNotNone(
                    runner.timed_window_error({**record, **invalid}))

        disabled = timed_kernel_write(mode=1)
        self.assertEqual(disabled["submitter_prepare"], 0)
        self.assertIsNone(runner.timed_window_error(disabled))
        disabled["submitter_prepare_claims"] = 1
        self.assertIsNotNone(runner.timed_window_error(disabled))

    def test_delta64_accounting_and_interpretation_are_fail_closed(self):
        record = timed_kernel_write(mode=1)
        self.assertIsNone(runner.timed_window_error(record))
        zero = {**record, **dict.fromkeys(runner.DELTA64_FIELDS, 0)}
        self.assertIsNone(runner.timed_window_error(zero))
        invalid_records = [
            {"delta64_classifier_pass": 11}, {"delta64_attempts": 6},
            {"delta64_adopted": 6}, {"delta64_raw_rescues": 2},
            {"delta64_payload_bytes_saved": 1201},
            {"delta64_raw_payload_bytes_saved": 527, "delta64_payload_bytes_saved": 727},
            {"delta64_lz4_payload_bytes_saved": 7135, "delta64_payload_bytes_saved": 8135},
            {"delta64_pack_attempts": 5}, {"delta64_pack_adopted": 2},
            {"delta64_pack_cliff_crossings": 6},
            {"delta64_score_0_7": 3},
            {"delta64_score_ge24": 6},
            {"delta64_wall_ns": -1}, {"delta64_eligible": True},
            {"delta64_rescue": 0}, {"delta64_rescue": 2},
        ]
        for invalid in invalid_records:
            with self.subTest(invalid=invalid):
                self.assertIsNotNone(runner.timed_window_error({**record, **invalid}))
        for field in runner.DELTA64_FIELDS:
            missing = dict(record)
            del missing[field]
            self.assertIsNotNone(runner.timed_window_error(missing))
        zero["delta64_rescue"] = 0
        self.assertIsNotNone(runner.timed_window_error(zero))
        missing = dict(zero)
        del missing["delta64_rescue"]
        self.assertIsNotNone(runner.timed_window_error(missing))
        headers = ("mode", "eligible", "passed", "attempts", "adopted", "RAW+", "LZ4+")
        interpretation = runner._table_interpretation(
            headers, [("async", "10", "0", "0", "0", "0", "0")])
        self.assertIn("No delta64 payload was adopted", interpretation)
        self.assertIn("no loaded delta64 savings evidence", interpretation)
        self.assertIn("not committed mappings", runner._table_interpretation(
            headers, [("async", "10", "5", "5", "3", "1", "2")]))

    def test_product_interpretations_compare_against_raw(self):
        headers = ("mode", "W", "lower W", "W req", "R", "R p99")
        aligned = runner._table_interpretation(headers, [
            ("off", "10", "10", "100", "5", "2"),
            ("sync", "11", "7", "80", "5.2", "1.9"),
            ("async", "12", "7", "70", "5.5", "1.8"),
        ])
        self.assertIn("Directional project view vs raw: ALIGNED", aligned)
        self.assertIn("backing WRITE bytes/useful byte", aligned)
        self.assertIn("lower WRITE requests", aligned)
        tradeoff = runner._table_interpretation(headers, [
            ("off", "10", "10", "100", "5", "2"),
            ("sync", "10", "8", "90", "5", "2"),
            ("async", "9", "6", "70", "5.2", "1.8"),
        ])
        self.assertIn("Directional project view vs raw: TRADE-OFF", tradeoff)

        reads = runner._table_interpretation(
            ("read", "lower KiB", "req", "p99"),
            [("seq-off", "4096", "1024", "5"),
             ("seq-async", "3000", "800", "4"),
             ("rnd-off", "4096", "1024", "6"),
             ("rnd-async", "3500", "900", "5.5")])
        self.assertIn("Directional project view vs raw: ALIGNED", reads)
        self.assertIn("lower READ bytes", reads)

        sustained = runner._table_interpretation(
            ("QD", "raw", "sync", "async", "A/S", "A req"),
            [("4", "20", "15", "18", "+20%", "500"),
             ("8", "30", "20", "25", "+25%", "400")])
        self.assertIn("Directional performance view vs raw: NOT ALIGNED", sustained)
        self.assertIn("cannot turn a swapz result that still trails raw into a product win",
                      sustained)

        aligned_reasoning = runner._table_project_reasoning(
            "Fast QD32 mixed I/O throughput and latency",
            headers,
            [("off", "10", "10", "100", "5", "2"),
             ("sync", "11", "7", "80", "5.2", "1.9"),
             ("async", "12", "7", "70", "5.5", "1.8")],
            aligned)
        self.assertIn("Verdict: ALIGNED", aligned_reasoning)
        self.assertIn("host-write endurance proxy", aligned_reasoning)

        native_reasoning = runner._table_project_reasoning(
            "Ordinary LZ4 acceleration CPU and planner geometry — native corpus",
            ("accel", "ns/page"), [("1", "2400"), ("4", "2100")],
            "Acceleration 4 is faster natively.")
        self.assertIn("Verdict: SUPPORTING ONLY", native_reasoning)

        diagnostic_reasoning = runner._table_project_reasoning(
            "Fast mixed-I/O async pipeline wall-time attribution",
            ("stage", "busy ms"), [("LZ4", "5.0")],
            "LZ4=5 ms.")
        self.assertIn("Verdict: DIAGNOSTIC ONLY", diagnostic_reasoning)

        ci_reasoning = runner._table_project_reasoning(
            "Candidate paired 95% confidence intervals",
            ("metric", "mean", "low", "high"),
            [("W %", "+5", "+1", "+9"),
             ("lower req %", "-4", "-8", "-1")],
            "Project evidence from 95% intervals.")
        self.assertIn("Verdict: ALIGNED", ci_reasoning)

        limits_reasoning = runner._table_project_reasoning(
            "Qualification scope and evidence limitations",
            ("scope", "value"), [("media", "synthetic RAM only")],
            "Synthetic RAM only.")
        self.assertIn("Verdict: CLAIM BOUNDARY", limits_reasoning)

    def test_unqualified_console_does_not_bury_the_blocking_gate(self):
        report = {
            "overall": "BLOCKED",
            "stages": [
                {"status": "PASS"} for _ in range(4)
            ] + [{"status": "BLOCKED"}],
            "benchmarks": {"verdicts": {
                "overall": "INCOMPLETE",
                "reason": "sd_emulated: required counterbalanced sessions missing",
            }},
            "evidence": {
                "predictor": predictor_evidence(),
                "gc_scan_scale": gc_scan_scale_evidence(),
                "extent_geometry": extent_geometry_evidence(),
            },
        }
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report)
        rendered = output.getvalue()
        self.assertIn("Stages passed: 4/5", rendered)
        self.assertIn("loaded service: NOT QUALIFIED", rendered)
        self.assertIn("sd_emulated: required counterbalanced sessions missing", rendered)
        self.assertIn("No new byte-exact loaded mixed/QD comparison", rendered)
        self.assertIn("Native diagnostics captured", rendered)
        self.assertNotIn("Predictive transform compression", rendered)
        self.assertNotIn("Simulated extent placement geometry", rendered)
        self.assertLess(len(rendered.splitlines()), 16)

    def test_benchmark_console_is_compact_and_keeps_sync_control(self):
        verdicts = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        saturation = runner.write_saturation_verdict(
            runner.parse_write_saturation(synthetic_log()))
        report = {"overall": "PASS",
                  "qualified_artifacts": {
                      "status": "AVAILABLE", "formatter_sha256": "a" * 64,
                      "module_sha256": "b" * 64, "oracle_sha256": "c" * 64},
                  "evidence": {"predictor": predictor_evidence(),
                                "gc_scan_scale": gc_scan_scale_evidence(),
                                "extent_geometry": extent_geometry_evidence()},
                  "benchmarks": {
            "verdicts": verdicts,
            "parallel_read_ab": runner.parallel_read_ab_verdict(
                runner.parse_parallel_read_ab(synthetic_log())),
            "read_coalesce_ab": runner.read_coalesce_ab_verdict(
                runner.parse_read_coalesce_ab(synthetic_log())),
            "sd_read_coalesce_ab": runner.sd_read_coalesce_ab_verdict(
                runner.parse_sd_read_coalesce_ab(synthetic_log())),
            "lz4_acceleration": runner.lz4_acceleration_verdict(
                runner.parse_lz4_acceleration(synthetic_log())),
            "delta64_rescue": {
                "overall": "NOT_RUN",
                "reason": "retired; production delta64+DELTA64_SHUF8+LZ4 is fixed on",
            },
            "delta64_prepare": runner.delta64_prepare_verdict(
                runner.parse_delta64_prepare_sessions(synthetic_log())),
            "write_saturation": saturation,
            "loaded_correctness": runner.parse_loaded_correctness(synthetic_log()),
        }}
        # The operator view is short and puts the product control first.
        with contextlib.redirect_stdout(io.StringIO()) as summary:
            runner.print_bench(report)
        operator = summary.getvalue()
        self.assertIn("Product decision snapshot", operator)
        self.assertIn("Sustained lane-owned WRITE", operator)
        self.assertIn("accepted-work lower-idle", operator)
        self.assertIn("A/raw", operator)
        self.assertNotIn("Negative classifier profile breakdown", operator)
        self.assertIn("Directional performance view vs raw", operator)
        self.assertLess(len(operator.splitlines()), 160)

        # The diagnostic renderer stays under the existing strict Markdown contract.
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report, detailed=True)
        rendered = output.getvalue()
        self.assertIn("Predictive-compression screening", rendered)
        self.assertIn("LZ4 acceleration 1 vs 4", rendered)
        self.assertIn("Acceleration 4 minus 1 paired 95% confidence intervals",
                      rendered)
        self.assertNotIn("Delta64 rescue off vs on", rendered)
        self.assertNotIn("Rescue on minus off paired 95% confidence intervals",
                         rendered)
        self.assertIn("Delta64 preparation K=1 vs K=2", rendered)
        self.assertIn("K=2 minus K=1 paired 95% confidence intervals",
                      rendered)
        self.assertIn("native corpus; not loaded attribution", rendered)
        self.assertIn("Production delta64 during mixed I/O", rendered)
        self.assertIn("payload KiB", rendered)
        self.assertIn("RAW+ KiB", rendered)
        self.assertIn("rescue ms", rendered)
        # Standard mixed sessions now run the production delta64 default; the
        # synthetic ordinary content adopts nothing, which must read as such.
        self.assertNotIn("Delta64 rescue is disabled", rendered)
        self.assertIn("No delta64 payload was adopted in these measured intervals",
                      rendered)
        self.assertNotIn("not kernel policy", rendered)
        self.assertIn("Garbage-collection map-scan scaling", rendered)
        self.assertIn("Simulated extent geometry", rendered)
        self.assertNotIn("ID69 PACKED PLACEMENT A/B", rendered)
        self.assertIn("placement waste", rendered)
        self.assertIn("packed smoke", rendered)
        self.assertIn("packed_1_2_4_8_16", rendered)
        self.assertIn("upper DISCARD TRIM", rendered)
        self.assertIn("packed smoke", rendered)
        self.assertIn("1048576", rendered)
        self.assertIn("Sampled delta64 classifier", rendered)
        self.assertIn("classifier sampling regressions", rendered)
        self.assertIn("shared production-route screening", rendered)
        self.assertIn("no loaded I/O proof", rendered)
        self.assertIn("Negative classifier profile breakdown", rendered)
        self.assertIn("delta64", rendered)
        self.assertIn("pack eligible", rendered)
        self.assertIn("score 0-7", rendered)
        readable = " ".join(rendered.split())
        for column in ("pack eligible", "pack try", "cliff", "pack+", "score 0-7",
                       "8-15", "16-23", "24+", "lookups", "set hit %",
                       "probes/lookup", "repl", "meta copy KiB", "primary %", "secondary %"):
            self.assertNotIn(f"literal column: {column}", readable)
        self.assertIn("excludes cache insertion copies", readable)
        self.assertIn("threshold 16", readable)
        self.assertIn("Secondary hits show use of the second choice", readable)
        self.assertIn("classifier=scalar", rendered)
        self.assertRegex(rendered, r"\|\s*mode\s*\|\s*W\s*\|")
        self.assertIn("| sync", rendered)
        self.assertIn("Lower queue", rendered)
        self.assertIn("K=1 run slot", rendered)
        self.assertIn("Async pipeline", rendered)
        self.assertIn("wave kicks", rendered)
        self.assertIn("scheduling", rendered)
        self.assertIn("Verified 4MiB packed reads", rendered)
        self.assertIn("Packed-read C attribution", rendered)
        self.assertIn("Metadata-cache locality", rendered)
        self.assertIn("probes/lookup", rendered)
        self.assertIn("meta copy KiB", rendered)
        self.assertIn("RAM copies", rendered)
        self.assertIn("commit non-I/O", rendered)
        self.assertIn("engine plan", rendered)
        self.assertIn("engine pack", rendered)
        self.assertIn("engine publish", rendered)
        self.assertIn("publish CRC", rendered)
        self.assertIn("publish authority", rendered)
        self.assertIn("batch snapshot CRC", rendered)
        self.assertIn("engine residual", rendered)
        self.assertIn("payload CRC prep", rendered)
        self.assertIn("ordered callback", rendered)
        self.assertIn("prep callback", rendered)
        self.assertIn("lower-W queue start/end", rendered)
        self.assertIn("lower-W nonempty start/end", rendered)
        self.assertIn("deferred tail D/C/DL/I/O", rendered)
        self.assertIn("Workload content opportunity", rendered)
        self.assertIn("resident-dup", rendered)
        self.assertIn("Mixed PACK_READY causes", rendered)
        self.assertIn("Mixed burst-close split", rendered)
        self.assertIn("Mixed post-PACK tail samples", rendered)
        self.assertIn("Mixed burst-target shrink attribution", rendered)
        self.assertIn("skip-I0", rendered)
        self.assertIn("after-I0", rendered)
        self.assertIn("segment TRIM", rendered)
        self.assertIn("Independent lower-READ fan-out", rendered)
        self.assertIn("Fan-out on minus off paired 95% confidence intervals",
                      rendered)
        self.assertIn("Fan-out experiment raw-control drift", rendered)
        self.assertIn("Adjacent-range READ coalescing", rendered)
        self.assertNotIn("ID39 SAME-CACHE PARALLEL READ", rendered)
        self.assertNotIn("SD ID60 SAME-EXTENT GROUPING", rendered)
        self.assertIn("Merged-range accounting", rendered)
        self.assertIn("Reasons adjacent READs were not merged", rendered)
        self.assertIn("noncontig", rendered)
        self.assertIn("Serial-depth adjacent-range READ coalescing", rendered)
        self.assertIn("Serial-depth merged-range attribution", rendered)
        self.assertIn("saved", rendered)
        self.assertIn("K=1 ready wait win/records/ms", rendered)
        self.assertIn("K=1 ready wait P/F/D/X/O", rendered)
        self.assertIn("Fast mixed burst-close async-sync paired 95% CI", rendered)
        self.assertIn("async-sync", rendered)
        self.assertIn("Fast mixed async-sync paired 95% CI", rendered)
        self.assertIn("ordered phase wall", rendered)
        self.assertIn("prep phase wall", rendered)
        self.assertIn("deferred C >1ms <=1.25/1.50/1.75/>", rendered)
        self.assertIn("CPU", rendered)
        self.assertIn("deferred C age <=250/500/1000/>", rendered)
        self.assertIn("deferred DL service L/R/B", rendered)
        self.assertIn("Mixed window bins; close=P/D/I", rendered)
        self.assertIn("Routed delta64 CPU economics", rendered)
        self.assertIn("elapsed-time model", rendered)
        self.assertIn("not a demonstrated speedup", rendered)
        self.assertIn("Delta64 selected backends", rendered)
        self.assertIn("LZ4 ns", rendered)
        self.assertNotIn("LZ4-2 ns", rendered)
        self.assertIn("Directional project view vs raw", rendered)
        self.assertIn("backing WRITE bytes/useful byte", rendered)
        self.assertIn("Directional performance view vs raw", rendered)
        self.assertIn("Project evidence from 95% intervals", rendered)
        self.assertNotIn("dry-close followups", rendered)
        self.assertIn("direct LZ4 input", rendered)
        self.assertIn("Lifecycle", rendered)
        self.assertIn("max capacity", rendered)
        self.assertIn("primary lifecycle", rendered)
        self.assertIn("18 process-death recoveries; 13 negative cases", rendered)
        self.assertIn("2 edge pages verified", rendered)
        self.assertIn("lower I/O checked", rendered)
        self.assertIn("retained WRITE/FLUSH failed closed", rendered)
        self.assertIn("WRITE-ONLY SUSTAINED-QD EVIDENCE", rendered)
        self.assertIn("Persistent lane workers", rendered)
        self.assertIn("Serial QD32 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD4 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD8 A/S paired 95% CI", rendered)
        self.assertIn("Fast QD32 A/S paired 95% CI", rendered)
        self.assertIn(
            "five pairs at fast QD4/8/32 and serial QD32; QD1 is directional",
            rendered)
        self.assertIn("QD1 remains a directional control.", rendered)
        self.assertIn("DEVICE MODEL LIMITS", rendered)
        self.assertIn("4K latency MB/s", rendered)
        self.assertIn("Async preparation", rendered)
        self.assertIn("Async windows; close=P/D/I", rendered)
        self.assertIn("Full telemetry", rendered)
        self.assertIn("test_results.json", rendered)
        self.assertIn("Async useful WRITE throughput is", rendered)
        self.assertIn("95% intervals", rendered)
        self.assertIn("overlap zero for", rendered)
        self.assertIn("Merge-on means versus merge-off", rendered)
        self.assertIn("Read each criterion separately", rendered)
        self.assertNotRegex(rendered, r"(?m)^\s*(?:SD\s+)?ID\d+\b")
        self.assertNotIn("ID63 active", rendered)
        self.assertNotIn("All-window close reasons per-pair mean", rendered)
        self.assertNotIn("Timed 4MiB", rendered)
        self.assertNotIn("QD4 sync windows:", rendered)
        # Every stdout table must be directly copy/pasteable as Markdown:
        # a bold self-contained title, unindented GFM pipe syntax, explicit
        # left alignment with >=3 separator dashes per column, then the legend,
        # interpretation, and a literal horizontal rule.
        lines = rendered.splitlines()

        def is_left_aligned_separator(cell):
            cell = cell.strip()
            return (cell.startswith(":") and len(cell[1:]) >= 3 and
                    set(cell[1:]) <= {"-"})

        table_starts = [
            index for index in range(len(lines) - 1)
            if lines[index].startswith("| ") and
            lines[index + 1].startswith("| ") and
            all(is_left_aligned_separator(cell)
                for cell in lines[index + 1].strip("|").split("|"))
        ]
        self.assertGreater(len(table_starts), 10)
        self.assertEqual(rendered.count("  Legend:"), len(table_starts))
        self.assertEqual(rendered.count("  Interpretation:"), len(table_starts))
        self.assertEqual(rendered.count("  Project reasoning:"), len(table_starts))
        self.assertIn("  Goal chain:", rendered)
        self.assertIn("  Endurance scope:", rendered)
        self.assertIn("host-I/O endurance proxy", rendered)
        self.assertEqual(
            sum(line.startswith("**") and line.endswith("**") for line in lines),
            len(table_starts))
        for start in table_starts:
            self.assertGreater(start, 0)
            self.assertRegex(lines[start - 1], r"^\*\*\S.+\S\*\*$")
            # GFM alignment cells are at least four characters wide (:---).
            # Keep every divider pipe at the same terminal column as the
            # header, including narrow columns such as W, R, 1 and 2.
            header_pipes = [pos for pos, char in enumerate(lines[start])
                            if char == "|"]
            divider_pipes = [pos for pos, char in enumerate(lines[start + 1])
                             if char == "|"]
            self.assertEqual(divider_pipes, header_pipes)
            index = start + 2
            while index < len(lines) and lines[index].startswith("| "):
                index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Legend:"))
            legend_lines = [lines[index]]
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                legend_lines.append(lines[index])
                index += 1
            legend_text = " ".join(line.strip() for line in legend_lines)
            headers = [cell.strip() for cell in lines[start].strip("|").split("|")]
            for header in headers:
                self.assertIn(f"{header}:", legend_text)
                goal = runner.TABLE_HEADER_GOAL.get(header)
                if goal:
                    self.assertIn(f"[{goal}]", legend_text)
            self.assertNotIn("goal:", legend_text)
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Interpretation:"))
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                index += 1
            self.assertLess(index, len(lines))
            self.assertTrue(lines[index].startswith("  Project reasoning:"))
            reasoning_lines = [lines[index]]
            index += 1
            while index < len(lines) and lines[index].startswith("    "):
                reasoning_lines.append(lines[index])
                index += 1
            reasoning_text = " ".join(line.strip() for line in reasoning_lines)
            self.assertIn("Evidence:", reasoning_text)
            self.assertIn("Goal implication:", reasoning_text)
            self.assertIn("Verdict:", reasoning_text)
            self.assertLess(index, len(lines))
            self.assertEqual(lines[index], "---")
        self.assertNotRegex(rendered, r"(?m)^  \|")
        longest = max(lines, key=len)
        self.assertLess(len(longest), 96, longest)

    def test_mixed_write_diagnostics_missing_or_inconsistent_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"] = None
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[3]["arms"]["swapz"]["kernel_write_path"]["write_wait_gt4ms"] = 2
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"]["lz4_wall_ns"] = -1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "window_commit_nonio_wall_ns"] = 50000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "engine_publish_wall_ns"] = 11000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "engine_publish_crc_wall_ns"] = 2000000
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["swapz"]["kernel_write_path"][
            "prep_lower_write_start_nonempty"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_tail_flushes"] = 7
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_read_caps"] = 7
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "pack_tail_zero_idle"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["arms"]["swapz"]["kernel_write_path"][
            "k1_ready_wait_full"] = 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_close_and_deadline_accounting_fail_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"]["close_zero"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"]["win1_deadline"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["swapz"]["kernel_write_path"][
            "deadline_worker_empty"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
    def test_incomplete_mismatch_or_forged_packed_result_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(runner.benchmark_verdicts(sessions[:7])["overall"],
                         "INCOMPLETE")
        sessions[1]["source_sha"] = "different-source"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["trace_sha256"] = "tampered-trace"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["swapz"]["packed_read"]["packed_close_delta"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["swapz"]["packed_read"]["passes"]["sequential"][
            "logical_bytes"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[5]["device_model"]["completion_nsec"] = 1234
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions.pop()
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_report_replaced_and_not_raw_json_to_terminal(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "test_results.json"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                fake = ["python3", "-c",
                        "print('{\"candidate\":\"off\", \"device\": \"SECRET\"}')"]
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.run_stage("fake safe", fake, report), 0)
                self.assertNotIn('"candidate"', output.getvalue())
                self.assertNotIn("SECRET", output.getvalue())
                self.assertEqual(report["stages"][0]["status"], "PASS")
                path = runner.REPORT
                self.assertFalse(path.exists())
                runner.write_report(report)
                first = path.read_text(encoding="utf-8")
                self.assertNotIn("SECRET", first)
                report["overall"] = "FAIL"
                runner.write_report(report)
                second = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(second["overall"], "FAIL")
                self.assertEqual({item.name for item in runner.ROOT.iterdir()},
                                 {runner.GIT_RESULT})
                self.assertEqual(path.name, "test_results.json")
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_report_write_preserves_primary_error_over_cleanup_failure(self):
        from unittest import mock

        with tempfile.TemporaryDirectory(
                prefix="report-write-failure-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                runner.REPORT.write_text(
                    '{"overall":"PASS"}\n', encoding="utf-8")
                previous = runner.REPORT.read_bytes()
                with mock.patch.object(
                        runner.os, "replace",
                        side_effect=OSError(5, "private primary failure")), \
                     mock.patch.object(
                         Path, "unlink",
                         side_effect=OSError(13, "private cleanup failure")):
                    with self.assertRaises(OSError) as captured:
                        runner.write_report({"overall": "FAIL"})
                self.assertEqual(captured.exception.errno, 5)
                self.assertEqual(runner.REPORT.read_bytes(), previous)
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_terminal_report_failure_blocks_publish_and_preserves_exit(self):
        from unittest import mock

        source_sha = "a" * 40
        available_artifacts = {
            "status": "AVAILABLE",
            "formatter_sha256": "b" * 64,
            "module_sha256": "c" * 64,
            "oracle_sha256": "d" * 64,
        }

        def stage_runner(first_exit):
            def run(title, command, result, *, parse_bench=False,
                    stream_rootless_progress=False, progress_table=None,
                    retain_private_failure_output=False):
                # Observational display does not affect qualification fixture.
                del progress_table
                del retain_private_failure_output
                del command
                if first_exit and not result["stages"]:
                    result["stages"].append({
                        "name": title, "status": "FAIL",
                        "elapsed_s": 0.0, "exit_code": first_exit,
                    })
                    return first_exit
                result["stages"].append({
                    "name": title, "status": "PASS",
                    "elapsed_s": 0.0, "exit_code": 0,
                })
                if parse_bench:
                    benchmarks = result["benchmarks"]
                    benchmarks["verdicts"] = {
                        "overall": "PASS_BOUNDED_RAM_MATRIX"}
                    benchmarks["write_saturation"] = {
                        "overall": "PASS_WRITE_SATURATION_EVIDENCE"}
                    benchmarks["delta64_prepare"] = {"overall": "NOT_RUN"}
                return 0
            return run

        scenarios = (
            ("report-write", OSError(28, "private /home/secret"), 0, 1,
             "observed=os-error errno=28", "INCOMPLETE"),
            ("report-interrupt", KeyboardInterrupt(), 0, 130,
             "observed=interrupted errno=unavailable", "INCOMPLETE"),
            ("prior-test-failure", OSError(28, "private /home/secret"), 7, 7,
             "observed=os-error errno=28", "FAIL"),
        )
        for name, report_error, first_exit, expected_exit, detail, overall in scenarios:
            with self.subTest(name=name):
                with mock.patch.object(
                        runner.argparse.ArgumentParser, "parse_args",
                        return_value=mock.Mock(kdir="/unused")), \
                     mock.patch.object(
                         runner, "report_host_identity",
                         return_value={"schema": "swapz-host-v1",
                                       "status": "UNAVAILABLE"}), \
                     mock.patch.object(runner, "git_sha",
                                       return_value=source_sha), \
                     mock.patch.object(
                         runner, "make_invocation",
                         return_value=(["make"], "fixture")), \
                     mocked_main_sync(source_sha), \
                     mock.patch.object(
                         runner, "tracked_source_checkout_preflight",
                         return_value=None), \
                     mock.patch.object(
                         runner, "run_stage",
                         side_effect=stage_runner(first_exit)), \
                     mock.patch.object(
                         runner, "qualification_artifact_digests",
                         return_value=available_artifacts), \
                     mock.patch.object(
                         runner, "official_pass_binding_refusal",
                         return_value=None), \
                     mock.patch.object(runner, "lane_gap_attribution_rows",
                                       return_value=[]), \
                     mock.patch.object(
                         runner, "goal_scorecard",
                         return_value={"overall": "UNAVAILABLE", "rows": []}), \
                     mock.patch.object(
                         runner, "write_report", side_effect=report_error), \
                     mock.patch.object(runner, "print_bench") as print_bench, \
                     mock.patch.object(runner, "publish") as publish, \
                     mock.patch.object(runner, "refresh_history") as history, \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.main(), expected_exit)
                rendered = output.getvalue()
                self.assertIn(
                    f"Overall qualification: {overall}", rendered)
                self.assertIn(
                    "Report integrity: FAIL classification=NOT_PUBLISHED",
                    rendered)
                self.assertIn(
                    "stage=report-write expected=current-json", rendered)
                self.assertIn(detail, rendered)
                self.assertNotIn("/home/secret", rendered)
                self.assertNotIn("Traceback", rendered)
                self.assertTrue(
                    all(len(line) <= 96 for line in rendered.splitlines()),
                    rendered)
                print_bench.assert_not_called()
                publish.assert_not_called()
                history.assert_not_called()

    def test_qualification_report_hashes_exact_final_artifact_bytes(self):
        previous_root = runner.ROOT
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner.ROOT = Path(directory)
                expected = {}
                sources = {}
                for index, (key, relative_path, executable) in enumerate(
                        runner.QUALIFIED_ARTIFACTS, start=1):
                    source = runner.ROOT / relative_path
                    source.parent.mkdir(parents=True, exist_ok=True)
                    payload = (f"qualified-{index}-{key}").encode()
                    source.write_bytes(payload)
                    source.chmod(0o700 if executable else 0o600)
                    sources[key] = source
                    expected[key] = hashlib.sha256(payload).hexdigest()
                self.assertEqual(
                    runner.qualification_artifact_digests(),
                    {"status": "AVAILABLE", **expected})

                sources["module_sha256"].write_bytes(b"replacement")
                changed = runner.qualification_artifact_digests()
                self.assertEqual(changed["status"], "AVAILABLE")
                self.assertNotEqual(
                    changed["module_sha256"], expected["module_sha256"])

                sources["module_sha256"].unlink()
                sources["module_sha256"].symlink_to(
                    sources["formatter_sha256"])
                unavailable = runner.qualification_artifact_digests()
                self.assertEqual(unavailable["status"], "UNAVAILABLE")
                self.assertEqual(
                    unavailable["reason"], "module_sha256 unavailable")
        finally:
            runner.ROOT = previous_root

    def test_retired_lz4_ab_does_not_gate_overall_qualification(self):
        benchmarks = {
            "verdicts": {"overall": "PASS_BOUNDED_RAM_MATRIX"},
            "write_saturation": {"overall": "PASS_WRITE_SATURATION_EVIDENCE"},
            "lz4_acceleration": {
                "overall": "NOT_RUN",
                "reason": "retired; ordinary LZ4 is fixed at acceleration 1",
            },
        }
        self.assertTrue(runner.required_benchmark_gates_pass(benchmarks))
        benchmarks["verdicts"]["overall"] = "INCONCLUSIVE"
        self.assertFalse(runner.required_benchmark_gates_pass(benchmarks))
        benchmarks["verdicts"]["overall"] = "PASS_BOUNDED_RAM_MATRIX"
        benchmarks["write_saturation"]["overall"] = "INCOMPLETE"
        self.assertFalse(runner.required_benchmark_gates_pass(benchmarks))
        benchmarks["write_saturation"]["overall"] = "PASS_WRITE_SATURATION_EVIDENCE"

    def test_overall_status_follows_stage_semantics_not_raw_exit_code(self):
        stages = [
            {"name": name, "status": "PASS", "exit_code": 0}
            for name in runner.OFFICIAL_STAGE_NAMES
        ]
        self.assertEqual(runner.qualification_overall(0, stages), "PASS")
        self.assertEqual(runner.qualification_overall(0, stages[:-1]),
                         "INCOMPLETE")
        self.assertEqual(runner.qualification_overall(0, stages[::-1]),
                         "INCOMPLETE")
        self.assertEqual(runner.qualification_overall(0, [
            {**stages[0], "exit_code": True}, *stages[1:]]), "INCOMPLETE")
        self.assertEqual(runner.qualification_overall(0, [
            {**stages[0], "status": "FAIL"}, *stages[1:]]), "FAIL")
        self.assertEqual(runner.qualification_overall(2, [{"status": "FAIL"}]),
                         "FAIL")
        self.assertEqual(runner.qualification_overall(
            2, [{"status": "BLOCKED"}]), "BLOCKED")

    def test_failure_console_details_are_fail_only_bounded_and_private(self):
        # The first real failing subtest, not an earlier synthetic negative,
        # must own the diagnostic. Never print the actual document or host path.
        stage_output = (
            "FAIL: test_fake (__main__.Fixture.test_fake)\n"
            "test_separate_target_and_release_metadata "
            "(__main__.SwapzProductionSourceQualification."
            "test_separate_target_and_release_metadata) "
            "(naming_policy='docs/README.md') ... FAIL\n"
            "======================================================================\n"
            "FAIL: test_separate_target_and_release_metadata "
            "(__main__.SwapzProductionSourceQualification."
            "test_separate_target_and_release_metadata) "
            "(naming_policy='docs/README.md')\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            "  File \"/home/private/secret/source-contract-test.py\", line 1274, "
            "in test_separate_target_and_release_metadata\n"
            "AssertionError: 'Immutable naming policy "
            "(read before every prompt)' not found in \"PRIVATE_DOC_BYTES\"\n"
            "----------------------------------------------------------------------\n"
            "Ran 138 tests in 11.621s\n"
            "FAILED (failures=1)\n"
            "FAIL: rootless phase=source-contract-test.py "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=11 stage_s=20 line=99 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        details = runner.first_unittest_failure_details(stage_output)
        self.assertEqual(details, [
            "First failing unittest: test_separate_target_and_release_metadata "
            "[naming_policy=docs/README.md]",
            "Location: source-contract-test.py:1274",
            "Exception: AssertionError",
            "Missing expected text: Immutable naming policy "
            "(read before every prompt)",
        ])
        self.assertNotIn("/home/private", " ".join(details))
        self.assertNotIn("PRIVATE_DOC_BYTES", " ".join(details))
        self.assertNotIn("test_fake", " ".join(details))
        self.assertEqual(runner.first_unittest_failure_details(
            stage_output.replace("FAILED (failures=1)", "OK")), [])
        self.assertEqual(runner.first_unittest_failure_details(
            stage_output.replace("FAIL: rootless phase=", "PASS: rootless phase=")), [])
        self.assertEqual(runner.first_unittest_failure_details(
            "Ran 1 test in 0.001s\nOK\n"), [])
        self.assertEqual(runner.first_compiler_failure_location(
            "/home/private/kernel/dm-target.c:42:7: error: secret device\n"),
            ["Compiler location: dm-target.c:42:7"])
        self.assertEqual(runner.first_compiler_failure_location("PASS: clean\n"), [])

    def test_package_timeout_is_reported_automatically_without_private_text(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        method = "test_dkms_status_nonzero_with_matching_stdout_cannot_authenticate"
        marker = (
            "FAIL: rootless phase=package-dkms-test.py "
            f"subtest=unavailable test={method} exit=1 "
            "reason=unittest_timeout phase_s=15 stage_s=1613 line=690 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log")
        timeout_line = (
            "PackageInvocationTimeout: SWAPZ_PACKAGE_TEST_TIMEOUT "
            "codec_variant=uncompressed operation=install "
            "elapsed_seconds=15.086 budget_seconds=15 "
            "budget_reason=ordinary_fixture_watchdog "
            "final_process_disposition=reaped_exit_-9 "
            "original_process_exit_status=still_running "
            "fixture_phase=command_watchdog "
            "recovery_disposition=journal_not_assessed "
            "first_cause=fixture_watchdog_expired")
        transcript = (
            "FAIL: test_expected (__main__.NegativeFixture.test_expected)\n"
            f"{method} (__main__.PackageLifecycle.{method}) ... ERROR\n"
            "test_later (__main__.PackageLifecycle.test_later) ... ERROR\n"
            "======================================================================\n"
            f"ERROR: {method} (__main__.PackageLifecycle.{method})\n"
            "Traceback (most recent call last):\n"
            f'  File "/private/SECRET/package-dkms-test.py", line 901, in {method}\n'
            f"{timeout_line}\n"
            "======================================================================\n"
            "ERROR: test_later (__main__.PackageLifecycle.test_later)\n"
            "RuntimeError: PRIVATE_LATER_FAILURE\n"
            "======================================================================\n"
            "FAILED (errors=2)\n"
            f"{marker}\n")
        expected = (
            "Package fixture watchdog: action=install elapsed=15.086s "
            "budget=15s codec=uncompressed "
            "budget_reason=ordinary_fixture_watchdog "
            "process_disposition=reaped_exit_-9 "
            "phase=command_watchdog first_cause=fixture_watchdog_expired "
            "original_status=still_running recovery=journal_not_assessed")
        details = runner.first_unittest_failure_details(transcript)
        self.assertIn("Exception: PackageInvocationTimeout", details)
        self.assertIn(expected, details)
        self.assertEqual(details[0], "First failing unittest: " + method)
        for private in ("/private/SECRET", "PRIVATE_LATER_FAILURE",
                        "NegativeFixture"):
            self.assertNotIn(private, "\n".join(details))

        # Exercise the actual operator output, not just the parser's return.
        stages = {"stages": []}
        console = io.StringIO()
        with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(
                stdout=transcript, returncode=1)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(console):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"], stages), 1)
        self.assertIn("        " + expected, console.getvalue())
        self.assertEqual(stages["stages"][0]["status"], "FAIL")
        self.assertEqual(stages["stages"][0]["exit_code"], 1)
        self.assertNotIn(expected, stages["stages"][0]["diagnostic"])
        self.assertNotIn("/private/SECRET", console.getvalue())

        # Untrusted exceptions, mismatched marker identity, and incomplete
        # failure summaries must never print a synthetic watchdog payload.
        for unsafe in (
                transcript.replace("codec_variant=uncompressed",
                                   "codec_variant=/private/SECRET"),
                transcript.replace(" test=" + method,
                                   " test=test_different"),
                transcript.replace("reason=unittest_timeout",
                                   "reason=nonzero_exit"),
                transcript.replace("FAILED (errors=2)", "OK"),
                transcript.replace(
                    "original_process_exit_status=still_running",
                    "original_process_exit_status=74"),
                transcript.replace(
                    "fixture_phase=command_watchdog",
                    "fixture_phase=pipe_drain"),
                transcript.replace(
                    "recovery_disposition=journal_not_assessed",
                    "recovery_disposition=PRIVATE_OVERRIDDEN"),
                transcript.replace(
                    "first_cause=fixture_watchdog_expired",
                    "first_cause=PRIVATE_OVERRIDDEN")):
            with self.subTest(unsafe=unsafe[-120:]):
                self.assertNotIn(
                    "Package fixture watchdog:",
                    "\n".join(runner.first_unittest_failure_details(unsafe)))

    def test_failure_console_reports_safe_markers_and_crash_context(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        fixed_mismatch = (
            "AssertionError: 'FAIL: unittest identity withheld' != "
            "'RuntimeError: [private exception detail omitted]'")
        self.assertEqual(runner.safe_assertion_details(fixed_mismatch), [
            "Assertion mismatch: observed FAIL: unittest identity withheld; "
            "expected RuntimeError: [private exception detail omitted]"])
        self.assertEqual(runner.safe_assertion_details(
            "AssertionError: 'PRIVATE_HOST_VALUE' != "
            "'RuntimeError: [private exception detail omitted]'"), [])

        method = "test_real_sigkill_phases_block_both_commands_not_cleanup"
        phase = "primary-lifecycle-audit-test.py"
        context = "(action='uninstall', phase='dkms-removed')"
        crash = (
            f"{method} (__main__.PackageCrashToPrimaryAdmissionTest.{method}) "
            f"{context} ... ERROR\n"
            "======================================================================\n"
            f"ERROR: {method} "
            f"(__main__.PackageCrashToPrimaryAdmissionTest.{method}) "
            f"{context}\n"
            "Traceback (most recent call last):\n"
            f'  File "/PRIVATE/{phase}", line 1722, in {method}\n'
            "subprocess.TimeoutExpired: PRIVATE_SUBPROCESS_COMMAND\n"
            "----------------------------------------------------------------------\n"
            "Ran 4 tests in 10s\n"
            "FAILED (errors=1)\n"
            f"FAIL: rootless phase={phase} subtest=unavailable test={method} "
            "exit=1 reason=unittest_error phase_s=10 stage_s=16 line=90 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        expected = [
            "First failing unittest: " + method,
            "Subtest: action=uninstall phase=dkms-removed",
            "Location: primary-lifecycle-audit-test.py:1722",
            "Exception: subprocess.TimeoutExpired",
        ]
        self.assertEqual(runner.first_unittest_failure_details(crash), expected)

        diagnostic_method = (
            "test_unstructured_exceptions_and_hostile_unittest_names_stay_private")
        diagnostic_phase = "ci-failure-diagnostics-test.py"
        private = (
            f"{diagnostic_method} "
            f"(__main__.FirstFailureDelivery.{diagnostic_method}) ... FAIL\n"
            "======================================================================\n"
            f"FAIL: {diagnostic_method} "
            f"(__main__.FirstFailureDelivery.{diagnostic_method})\n"
            "Traceback (most recent call last):\n"
            f'  File "/PRIVATE/{diagnostic_phase}", line 205, '
            f'in {diagnostic_method}\n'
            + fixed_mismatch + "\n"
            "----------------------------------------------------------------------\n"
            "Ran 20 tests in 1s\n"
            "FAILED (failures=1)\n"
            f"FAIL: rootless phase={diagnostic_phase} "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=1 stage_s=2 line=12 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        self.assertIn(
            "Assertion mismatch: observed FAIL: unittest identity withheld; "
            "expected RuntimeError: [private exception detail omitted]",
            runner.first_unittest_failure_details(private))
        for transcript, expected_detail in (
            (crash, "Subtest: action=uninstall phase=dkms-removed"),
            (private, "Assertion mismatch: observed FAIL: unittest identity withheld; "
             "expected RuntimeError: [private exception detail omitted]"),
        ):
            with self.subTest(expected_detail=expected_detail):
                console = io.StringIO()
                with patch.object(runner.subprocess, "run",
                                  return_value=SimpleNamespace(
                                      stdout=transcript, returncode=1)), \
                        patch.object(runner,
                                     "retain_direct_rootless_first_failure"), \
                        contextlib.redirect_stdout(console):
                    self.assertEqual(runner.run_stage(
                        "Native and rootless contracts", ["synthetic"],
                        {"stages": []}), 1)
                self.assertIn("        " + expected_detail,
                              console.getvalue())
                self.assertNotIn("/PRIVATE/", console.getvalue())
                self.assertNotIn("PRIVATE_SUBPROCESS_COMMAND",
                                 console.getvalue())

    def test_nested_pageout_oracle_failure_is_printed_without_private_stderr(self):
        method = "test_algorithm_pageout_oracle_unit_contracts"
        nested_test = "test_madvise_refusal_cannot_print_success"
        transcript = (
            f"{method} (__main__.PhysicalSwapProbeTests.{method}) ... FAIL\n"
            "======================================================================\n"
            f"FAIL: {method} (__main__.PhysicalSwapProbeTests.{method})\n"
            "Traceback (most recent call last):\n"
            f'  File "/PRIVATE/host/physical-swap-probe-test.py", line 346, '
            f'in {method}\n'
            f"AssertionError: Nested pageout oracle failure: "
            f"test={nested_test} kind=FAIL observed=0 expected=1\n"
            "----------------------------------------------------------------------\n"
            "Ran 124 tests in 2s\n"
            "FAILED (failures=1)\n"
            "FAIL: rootless phase=physical-swap-probe-test.py "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=2 stage_s=200 line=754 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        expected = [
            f"First failing unittest: {method}",
            "Location: physical-swap-probe-test.py:346",
            "Exception: AssertionError",
            f"Nested pageout oracle: test={nested_test} kind=FAIL",
            "Nested assertion: observed 0; expected 1",
        ]
        self.assertEqual(
            runner.first_unittest_failure_details(transcript), expected)
        from types import SimpleNamespace
        with mock.patch.object(
                runner.subprocess, "run", return_value=SimpleNamespace(
                    stdout=transcript, returncode=1)), \
             mock.patch.object(runner, "retain_direct_rootless_first_failure"), \
             contextlib.redirect_stdout(io.StringIO()) as console:
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"],
                {"stages": []}), 1)
        for item in expected:
            self.assertIn(item, console.getvalue())
        self.assertNotIn("/PRIVATE/host", console.getvalue())

        hostile = transcript.replace(
            f"test={nested_test}",
            "test=private_device_token")
        details = runner.first_unittest_failure_details(hostile)
        self.assertNotIn("private_device_token", " ".join(details))
        self.assertIn(
            "Nested pageout oracle: cause unavailable; private failure log retained",
            details)

    def test_physical_probe_reports_first_cause_after_bounded_trailer(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        phase = "physical-swap-probe-test.py"
        method = "test_development_oracle_outcome_requires_executed_comparison"
        prefix = (
            f"{method} (__main__.PhysicalSwapProbeTests.{method}) ... FAIL\n"
            "======================================================================\n"
            f"FAIL: {method} (__main__.PhysicalSwapProbeTests.{method})\n"
            "Traceback (most recent call last):\n"
            f'  File "/private/host/tests/runtime/native/{phase}", '
            f'line 3336, in {method}\n'
            "AssertionError: 'MAPPED' != 'RECOVERY_REQUIRED'\n"
            "----------------------------------------------------------------------\n"
            "Ran 124 tests in 2s\n"
            "FAILED (failures=1)\n"
        )
        marker = (
            f"FAIL: rootless phase={phase} subtest=unavailable "
            "test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=2 stage_s=200 line=754 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        # A large post-footer data-path diagnostic must not suppress the
        # source-authenticated first failure or leak its private contents.
        transcript = (
            prefix
            + "PHYSICAL_RESULTS=/private/host/" + ("secret-data-" * 320) + "\n"
            + marker
        )
        expected = [
            f"First failing unittest: {method}",
            f"Location: {phase}:3336",
            "Exception: AssertionError",
            "Recovery state mismatch: observed MAPPED; expected RECOVERY_REQUIRED",
        ]
        self.assertEqual(
            runner.first_unittest_failure_details(transcript), expected)
        console = io.StringIO()
        with patch.object(
                runner.subprocess, "run", return_value=SimpleNamespace(
                    stdout=transcript, returncode=1)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(console):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"],
                {"stages": []}), 1)
        for fact in expected:
            self.assertIn("        " + fact, console.getvalue())
        self.assertNotIn("/private/host", console.getvalue())
        self.assertNotIn("secret-data", console.getvalue())

        # An unrelated source phase cannot exploit the larger bounded
        # physical-specific footer window to borrow a stale fixture failure.
        unrelated = transcript.replace(
            "phase=physical-swap-probe-test.py subtest=",
            "phase=source-contract-test.py subtest=")
        self.assertEqual(runner.first_unittest_failure_details(unrelated), [])

    def test_failure_console_reports_source_bound_recovery_error(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        method = "test_claimed_pre_mutation_recovery_uses_immutable_pair_binding"
        phase = "physical-swap-probe-test.py"
        transcript = (
            f"{method} (__main__.PhysicalSwapProbeTests.{method}) ... ERROR\n"
            "======================================================================\n"
            f"ERROR: {method} (__main__.PhysicalSwapProbeTests.{method})\n"
            "Traceback (most recent call last):\n"
            f'  File "/private/HOST/tests/runtime/native/{phase}", line 435, '
            f'in {method}\n'
            '  File "/private/HOST/tests/tools/physical-swap-probe.py", '
            'line 2504, in recover\n'
            '  File "/private/HOST/tests/tools/physical-swap-probe.py", '
            'line 2368, in _require_recovery_results_binding\n'
            "physical_swap_probe.ProbeError: saved physical results/state "
            "binding mismatch: run_id; "
            "safe_next_step=inspect_records_read_only\n"
            "----------------------------------------------------------------------\n"
            "Ran 20 tests in 2s\n"
            "FAILED (errors=1)\n"
            f"FAIL: rootless phase={phase} subtest=unavailable "
            "test=unavailable exit=1 reason=nonzero_exit phase_s=2 stage_s=8 "
            "line=731 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        expected = [
            f"First failing unittest: {method}",
            f"Location: {phase}:435",
            "Cause location: physical-swap-probe.py:2368",
            "Exception: physical_swap_probe.ProbeError",
            "Recovery binding mismatch: run_id; action=inspect_records_read_only",
        ]
        self.assertEqual(
            runner.first_unittest_failure_details(transcript), expected)
        console = io.StringIO()
        with patch.object(
                runner.subprocess, "run", return_value=SimpleNamespace(
                    stdout=transcript, returncode=1)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(console):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"],
                {"stages": []}), 1)
        for fact in expected:
            self.assertIn("        " + fact, console.getvalue())
        self.assertNotIn("/private/HOST", console.getvalue())
        hostile = transcript.replace(
            "binding mismatch: run_id;",
            "binding mismatch: secret_private_token;")
        safe = runner.first_unittest_failure_details(hostile)
        self.assertNotIn("secret_private_token", "\n".join(safe))
        self.assertNotIn("Recovery binding mismatch:", "\n".join(safe))

    def test_nullblk_failure_console_reports_safe_case_and_native_cause(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        fixture = (
            "FAIL: phase=volatile_owned_read "
            "expected_proof=pinned_creator_config_directory_and_canonical_attributes "
            "observed_proof=stable_directory_rejected original_errno=unavailable "
            "original_exit=1 ownership=retained\n"
            "FAIL: rootless nullblk fixture case=native_creator_source_proof "
            "line=1198 reason=command_exit status=1\n"
            "FAIL: rootless phase=nullblk-identity-test.sh "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=12 stage_s=80 line=776 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n")
        expected = [
            "First failing null_blk fixture: native_creator_source_proof",
            "Location: nullblk-identity-test.sh:1198",
            "Cause: command_exit (child_exit=1)",
            "Native configfs proof: phase=volatile_owned_read "
            "observed=stable_directory_rejected original_exit=1 "
            "ownership=retained",
        ]
        self.assertEqual(
            runner.first_nullblk_fixture_failure_details(fixture), expected)
        printed = io.StringIO()
        with patch.object(runner.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout=fixture, returncode=1)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(printed):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"],
                {"stages": []}), 1)
        for detail in expected:
            self.assertIn("        " + detail, printed.getvalue())
        self.assertNotIn("rootless-failure.ABC12345", printed.getvalue().split(
            "First failing null_blk fixture:")[1])
        for hostile in (
            fixture.replace("case=native_creator_source_proof",
                            "case=private_host_name"),
            fixture.replace("phase=nullblk-identity-test.sh",
                            "phase=other-suite.sh"),
            fixture.replace("status=1", "status=3"),
        ):
            self.assertEqual(
                runner.first_nullblk_fixture_failure_details(hostile), [])

    def test_imported_package_watchdog_explains_lifecycle_setup_failure(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        method = "test_real_sigkill_phases_block_both_commands_not_cleanup"
        phase = "primary-lifecycle-audit-test.py"
        envelope = (
            "swapz_package_crash_tests.PackageInvocationTimeout: "
            "SWAPZ_PACKAGE_TEST_TIMEOUT codec_variant=uncompressed "
            "operation=install elapsed_seconds=15.086 budget_seconds=15 "
            "budget_reason=ordinary_fixture_watchdog "
            "final_process_disposition=reaped_exit_-9 "
            "original_process_exit_status=still_running "
            "fixture_phase=command_watchdog "
            "recovery_disposition=journal_not_assessed "
            "first_cause=fixture_watchdog_expired")
        fixture = (
            f"{method} (__main__.PackageCrashToPrimaryAdmissionTest.{method}) "
            "(action='uninstall', phase='dkms-removed') ... ERROR\n"
            "======================================================================\n"
            f"ERROR: {method} "
            f"(__main__.PackageCrashToPrimaryAdmissionTest.{method}) "
            "(action='uninstall', phase='dkms-removed')\n"
            "Traceback (most recent call last):\n"
            f'  File "/private/HOST/{phase}", line 1726, in {method}\n'
            + envelope + "\n"
            "----------------------------------------------------------------------\n"
            "Ran 5 tests in 16s\n"
            "FAILED (errors=1)\n"
            f"FAIL: rootless phase={phase} subtest=unavailable "
            f"test={method} exit=1 reason=unittest_error "
            "phase_s=16 stage_s=40 line=690 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n")
        expected = [
            f"First failing unittest: {method}",
            "Subtest: action=uninstall phase=dkms-removed",
            f"Location: {phase}:1726",
            "Exception: PackageInvocationTimeout",
            "Package watchdog: action=install codec=uncompressed "
            "elapsed=15.086s budget=15s "
            "first_cause=fixture_watchdog_expired "
            "budget_reason=ordinary_fixture_watchdog "
            "process_disposition=reaped_exit_-9 "
            "recovery=journal_not_assessed",
        ]
        self.assertEqual(runner.first_unittest_failure_details(fixture),
                         expected)
        printed = io.StringIO()
        with patch.object(runner.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout=fixture, returncode=1)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(printed):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"],
                {"stages": []}), 1)
        for detail in expected:
            self.assertIn("        " + detail, printed.getvalue())
        self.assertNotIn("/private/HOST", printed.getvalue())
        untrusted = fixture.replace(
            "codec_variant=uncompressed", "codec_variant=PRIVATE_DEVICE")
        self.assertFalse(any(
            "Package watchdog:" in detail
            for detail in runner.first_unittest_failure_details(untrusted)))

    def test_native_lower_io_make_recipe_preserves_shell_variables(self):
        # Execute the real Makefile recipe against disposable fake binaries,
        # not the native kernel fixtures or any real block device.
        import subprocess

        test_programs = (
            "flush-ordering", "lower-write-aggregation", "window-policy",
            "preparation-slots", "preparation-codec-result",
            "preparation-publication-lifetime", "lane-gap",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            # This fixture tests the existing lower-I/O shell recipe, not C
            # compilation. Seed the real configuration stamp and harmless
            # object prerequisites before creating newer fake executables.
            configured = subprocess.run(
                ["make", "--no-print-directory", "-s",
                 "-f", str(ROOT / "tests/suites/Makefile"),
                 str(output / "native-compiler-configuration"),
                 f"OUT={output}"],
                cwd=ROOT / "tests/suites", capture_output=True, text=True,
                check=False, timeout=10)
            self.assertEqual(configured.returncode, 0, configured.stderr)
            for production_source in ("codec", "authority", "engine"):
                (output / f"production-{production_source}.o").touch()
            for program_name in test_programs:
                executable = output / program_name
                return_code = 7 if program_name == "lower-write-aggregation" else 0
                executable.write_text(
                    "#!/bin/sh\n"
                    f"printf 'invoked {program_name}\\n'\n"
                    f"exit {return_code}\n",
                    encoding="ascii")
                executable.chmod(0o700)
            result = subprocess.run(
                ["make", "--no-print-directory", "-s",
                 "-f", str(ROOT / "tests/suites/Makefile"),
                 "test-lower-io", f"OUT={output}"],
                cwd=ROOT / "tests/suites", capture_output=True, text=True,
                check=False, timeout=10)
            # Make itself exits 2, but the failure marker preserves the
            # original binary's exit 7 and prevents later programs running.
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "invoked flush-ordering",
                "invoked lower-write-aggregation",
            ])
            self.assertIn(
                "FAIL: native test-lower-io "
                "binary=lower-write-aggregation exit=7", result.stderr)
            self.assertNotIn("ative_test", result.stderr)
            self.assertNotIn("Illegal number", result.stderr)

    def test_native_lower_io_console_reports_failing_binary_and_source(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        transcript = (
            "FAIL: lower-write-aggregation.c:14 expression=PRIVATE_EXPRESSION\n"
            "FAIL: native test-lower-io binary=lower-write-aggregation exit=1\n"
            "make[2]: *** [Makefile:156: test-lower-io] Error 1\n"
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=test-lower-io test=unavailable "
            "exit=2 reason=nonzero_exit phase_s=11 stage_s=16 line=603 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        expected = [
            "First failing native test: lower-write-aggregation (exit=1)",
            "Native assertion location: lower-write-aggregation.c:14",
        ]
        self.assertEqual(
            runner.first_native_lower_io_failure_details(transcript), expected)
        console = io.StringIO()
        result = {"stages": []}
        with patch.object(runner.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout=transcript, returncode=2)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(console):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"], result), 2)
        for detail in expected:
            self.assertIn("        " + detail, console.getvalue())
            self.assertIn(detail, result["stages"][-1]["diagnostic"])
        self.assertNotIn("PRIVATE_EXPRESSION", console.getvalue())
        self.assertNotIn("/PRIVATE/host", console.getvalue())
        self.assertNotIn("PRIVATE_EXPRESSION",
                         result["stages"][-1]["diagnostic"])
        self.assertNotIn("/PRIVATE/host",
                         result["stages"][-1]["diagnostic"])

        for malicious in (
            transcript.replace("binary=lower-write-aggregation",
                               "binary=private-host-value"),
            transcript.replace("subtest=test-lower-io", "subtest=test-gc"),
            transcript.replace("Error 1\n", "Error 2\n"),
            transcript.replace("exit=2 reason=nonzero_exit",
                               "exit=1 reason=nonzero_exit"),
        ):
            self.assertEqual(
                runner.first_native_lower_io_failure_details(malicious), [])

    def test_native_userspace_make_recipe_preserves_failing_binary(self):
        # Execute only disposable fake userspace binaries. A failure must stop
        # before the later native binary and Python late-race regression.
        import subprocess

        test_programs = (
            "swapzctl-status", "swapz-primary-policy",
            "swapz-primary-mount-namespace",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory)
            configured = subprocess.run(
                ["make", "--no-print-directory", "-s",
                 "-f", str(ROOT / "tests/suites/Makefile"),
                 str(output / "native-compiler-configuration"),
                 f"OUT={output}"],
                cwd=ROOT / "tests/suites", capture_output=True, text=True,
                check=False, timeout=10)
            self.assertEqual(configured.returncode, 0, configured.stderr)
            for program_name in test_programs:
                executable = output / program_name
                return_code = 7 if program_name == "swapz-primary-policy" else 0
                executable.write_text(
                    "#!/bin/sh\n"
                    f"printf 'invoked {program_name}\\n'\n"
                    f"exit {return_code}\n",
                    encoding="ascii")
                executable.chmod(0o700)
            result = subprocess.run(
                ["make", "--no-print-directory", "-s",
                 "-f", str(ROOT / "tests/suites/Makefile"),
                 "test-userspace", f"OUT={output}"],
                cwd=ROOT / "tests/suites", capture_output=True, text=True,
                check=False, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [
                "invoked swapzctl-status",
                "invoked swapz-primary-policy",
            ])
            self.assertIn(
                "FAIL: native test-userspace "
                "binary=swapz-primary-policy exit=7", result.stderr)
            self.assertNotIn("invoked swapz-primary-mount-namespace",
                             result.stdout)
            self.assertNotIn("ative_test", result.stderr)
            self.assertNotIn("Illegal number", result.stderr)

    def test_native_userspace_console_reports_failing_binary_and_source(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        transcript = (
            "/PRIVATE/host/tests/runtime/native/userspace/"
            "swapz-primary-policy.c:3530 expression=PRIVATE_EXPRESSION\n"
            "FAIL: native test-userspace binary=swapz-primary-policy exit=134\n"
            "make[2]: *** [Makefile:205: test-userspace] Error 134\n"
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=test-userspace test=unavailable "
            "exit=2 reason=nonzero_exit phase_s=12 stage_s=18 line=611 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        expected = [
            "First failing native test: swapz-primary-policy (exit=134)",
            "Native assertion location: swapz-primary-policy.c:3530",
        ]
        self.assertEqual(
            runner.first_native_userspace_failure_details(transcript), expected)
        console = io.StringIO()
        result = {"stages": []}
        with patch.object(runner.subprocess, "run",
                          return_value=SimpleNamespace(
                              stdout=transcript, returncode=2)), \
                patch.object(runner, "retain_direct_rootless_first_failure"), \
                contextlib.redirect_stdout(console):
            self.assertEqual(runner.run_stage(
                "Native and rootless contracts", ["synthetic"], result), 2)
        for detail in expected:
            self.assertIn("        " + detail, console.getvalue())
            self.assertIn(detail, result["stages"][-1]["diagnostic"])
        self.assertNotIn("PRIVATE_EXPRESSION", console.getvalue())
        self.assertNotIn("/PRIVATE/host", console.getvalue())
        self.assertNotIn("PRIVATE_EXPRESSION",
                         result["stages"][-1]["diagnostic"])
        self.assertNotIn("/PRIVATE/host",
                         result["stages"][-1]["diagnostic"])

        for malicious in (
            transcript.replace("binary=swapz-primary-policy",
                               "binary=private-host-value"),
            transcript.replace("subtest=test-userspace", "subtest=test-gc"),
            transcript.replace("Error 134\n", "Error 133\n"),
            transcript.replace("exit=2 reason=nonzero_exit",
                               "exit=1 reason=nonzero_exit"),
        ):
            self.assertEqual(
                runner.first_native_userspace_failure_details(malicious), [])

    def test_failure_console_assertions_show_safe_expected_and_observed(self):
        # Reproduce the originally hidden nullblk fixture nounset failure.
        # The actual stderr may contain private paths and keys.
        transcript = (
            "test_rootless_failed_owned_partition_write_is_fail "
            "(__main__.PrimaryLifecycleQualification."
            "test_rootless_failed_owned_partition_write_is_fail) ... FAIL\n"
            "======================================================================\n"
            "FAIL: test_rootless_failed_owned_partition_write_is_fail "
            "(__main__.PrimaryLifecycleQualification."
            "test_rootless_failed_owned_partition_write_is_fail)\n"
            "----------------------------------------------------------------------\n"
            "Traceback (most recent call last):\n"
            "  File \"/home/private/primary-lifecycle-nullblk-qualifier-test.py\", "
            "line 2826, in test_rootless_failed_owned_partition_write_is_fail\n"
            "AssertionError: 'phase=partition-table-write' not found in "
            "'bash: line 20: DISK_ID: unbound variable\\n"
            "SECRET_TOKEN=/home/private/hidden-device'\n"
            "----------------------------------------------------------------------\n"
            "Ran 138 tests in 10.1s\n"
            "FAILED (failures=1)\n"
            "FAIL: rootless phase=primary-lifecycle-nullblk-qualifier-test.py "
            "subtest=unavailable test=unavailable exit=1 reason=nonzero_exit "
            "phase_s=12 stage_s=16 line=99 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        details = runner.first_unittest_failure_details(transcript)
        self.assertEqual(details, [
            "First failing unittest: test_rootless_failed_owned_partition_write_is_fail",
            "Location: primary-lifecycle-nullblk-qualifier-test.py:2826",
            "Exception: AssertionError",
            "Missing expected marker: phase=partition-table-write",
            "Observed shell error: unset variable (set -u)",
        ])
        public_details = "\n".join(details)
        for private_value in ("SECRET_TOKEN", "/home/private", "hidden-device",
                              "DISK_ID"):
            self.assertNotIn(private_value, public_details)

        for error, expected in (
            ("AssertionError: 'ownership=claimed' unexpectedly found in "
             "'PRIVATE_ACTUAL'\n", ["Unexpected marker: ownership=claimed"]),
            ("AssertionError: 'FAIL' != 'PASS'\n",
             ["Assertion mismatch: observed FAIL; expected PASS"]),
            ("AssertionError: 1 != 0\n",
             ["Assertion mismatch: observed 1; expected 0"]),
            ("AssertionError: False is not true\n",
             ["Assertion mismatch: observed false; expected true"]),
            ("AssertionError: 'phase=abcdef123456789secret' not found in "
             "'/private/device token=0123456789secret'\n",
             ["Assertion detail: expected value withheld; inspect private log"]),
            ("AssertionError: 123456789 != 123456780\n", []),
            ("AssertionError: /private/device token=secret\n", []),
        ):
            with self.subTest(error_category=expected):
                self.assertEqual(runner.safe_assertion_details(error), expected)
        self.assertEqual(runner.first_unittest_failure_details(
            transcript.replace("FAILED (failures=1)", "OK")), [])
        self.assertEqual(runner.first_unittest_failure_details(
            transcript.replace("FAIL: rootless phase=", "PASS: rootless phase=")), [])

    def test_rootless_unittest_failure_names_safe_test(self):
        phase, reason = runner.failure_context(
            "FAIL: test_fixture_schema (__main__.Contract.test_fixture_schema)\n"
            "AssertionError\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(reason, "Unit test failed: test_fixture_schema")

    def test_rootless_failure_marker_binds_unittest_to_failing_phase(self):
        earlier_expected = (
            "FAIL: test_expected_negative "
            "(__main__.EarlierFixture.test_expected_negative)\n"
        )
        classified = (
            earlier_expected
            + "FAIL: test_oracle_first "
            "(__main__.PrimaryRealSwapContracts.test_oracle_first)\n"
            + "ERROR: test_teardown "
            "(__main__.PrimaryRealSwapContracts.test_teardown)\n"
            + "FAIL: rootless phase=primary-real-swap-test.py "
            "subtest=unavailable test=test_oracle_first exit=37 "
            "reason=unittest_assertion phase_s=1 stage_s=2 line=332 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
            + "Failed during: tests/runtime/native/primary-real-swap-test.py\n"
            + "Reason: exit=37 reason=unittest_assertion subtest=unavailable "
            "phase_wall_s=1 stage_wall_s=2 line=332 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
        )
        phase, reason = runner.failure_context(
            classified, loaded=False,
            default_phase="Native and rootless contracts")
        self.assertEqual(phase, "primary-real-swap-test.py")
        self.assertIn("Unit test failed: test_oracle_first", reason)
        self.assertIn("child_exit=37", reason)
        self.assertIn("log=build/tests/rootless-failure.ABC12345/diagnostic.log",
                      reason)
        self.assertNotIn("test_expected_negative", reason)
        self.assertNotIn("test_teardown", reason)

        marker_only = (
            earlier_expected
            + "FAIL: rootless phase=C syntax: physical lifecycle seam "
            "subtest=unavailable test=unavailable exit=1 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=389 "
            "log=unavailable\n"
            + "Failed during: C syntax: physical lifecycle seam\n"
            + "Reason: exit=1 reason=nonzero_exit subtest=unavailable "
            "phase_wall_s=1 stage_wall_s=2 line=389 log=unavailable\n"
        )
        phase, reason = runner.failure_context(
            marker_only, loaded=False,
            default_phase="Native and rootless contracts")
        self.assertEqual(phase, "C syntax: physical lifecycle seam")
        self.assertNotIn("test_expected_negative", reason)
        self.assertIn("child_exit=1", reason)

        malformed_marker = (
            earlier_expected
            + "FAIL: rootless phase=package-dkms-test.py "
            "subtest=preflight test=test_expected_negative exit=37 "
            "reason=unittest_assertion phase_s=1 stage_s=1 line=357 "
            "log=build/tests/rootless-failure.ABC12345/diagnostic.log\n"
            + "FAIL: rootless phase=make-interface-test.py "
            "subtest=unavailable test=not-allowlisted exit=1 "
            "reason=nonzero_exit phase_s=1 stage_s=2 line=347 "
            "log=unavailable\n"
        )
        phase, reason = runner.failure_context(
            malformed_marker, loaded=False,
            default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertNotIn("test_expected_negative", reason)
        self.assertNotIn("make-interface-test.py", reason)
        self.assertIn("malformed or unverified", reason)

    def test_rootless_marker_cannot_reattribute_other_official_stage(self):
        """Only the native/rootless aggregate may authenticate rootless markers."""
        from types import SimpleNamespace
        from unittest.mock import patch

        output = (
            "src/kernel/foo.c:19:3: error: incompatible pointer type\n"
            "FAIL: rootless phase=package-dkms-test.py "
            "subtest=rollback-check test=test_cleanup exit=2 "
            "reason=unittest_error phase_s=1 stage_s=2 line=315 "
            "log=build/tests/rootless-failure.Abc123xy/diagnostic.log\n"
        )
        report = {"stages": []}
        with patch.object(
                runner.subprocess, "run",
                return_value=SimpleNamespace(stdout=output, returncode=2)), \
                contextlib.redirect_stdout(io.StringIO()):
            observed_exit = runner.run_stage(
                "Build module and helpers", ["unused"], report)

        stage = report["stages"][0]
        self.assertEqual(observed_exit, 2)
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["exit_code"], 2)
        self.assertEqual(stage["failed_phase"], "Build module and helpers")
        self.assertEqual(
            stage["diagnostic"],
            "Native build error: incompatible pointer type")
        public_json = json.dumps(stage)
        self.assertNotIn("package-dkms-test.py", public_json)
        self.assertNotIn("test_cleanup", public_json)
        self.assertNotIn("rootless-failure.Abc123xy", public_json)

    def test_rootless_first_failure_preserves_exact_marker_and_redaction(self):
        """Only the final status-matched Bash marker can supply test identity."""
        from types import SimpleNamespace
        from unittest.mock import patch

        source_sha = "f" * 40
        private_path = "/private/device/SECRET_RESOURCE"
        diagnostic_log = (
            "build/tests/rootless-failure.Abc123xy/diagnostic.log")
        # These transcripts are synthetic: native stderr never proves a
        # nested test name, errno or later cleanup as the first failed child.
        cases = (
            ("nested Make Error 134",
             "make[2]: *** [Makefile:120: test-userspace] Error 134\n"
             "make: *** [Makefile:15: test] Error 2\n",
             "Makefile native and metadata", "test-userspace",
             "unavailable", "nonzero_exit", 2, "99"),
            ("native assertion",
             "FAIL: test_wrong (__main__.Unrelated.test_wrong)\n"
             "AssertionError: " + private_path + "\n",
             "Makefile native and metadata", "unavailable",
             "unavailable", "nonzero_exit", 2, "99"),
            ("silent nonzero", "", "C syntax: physical lifecycle seam",
             "unavailable", "unavailable", "nonzero_exit", 43, "unavailable"),
            ("authenticated compiler error",
             "private.c:12: error: " + private_path + "\n",
             "Makefile native and metadata", "compile",
             "swapz-primary-late-race-test.py", "native_compile", 2, "99"),
            ("unproven compiler error",
             "private.c:12: error: " + private_path + "\n",
             "Makefile native and metadata", "unavailable",
             "unavailable", "nonzero_exit", 2, "99"),
            ("truncated transcript", "x" * 300000 + "\n",
             "Makefile native and metadata", "unavailable",
             "unavailable", "nonzero_exit", 2, "99"),
            ("relay failure", "stderr relay incomplete\n",
             "package-dkms-test.py", "unavailable",
             "unavailable", "stderr_relay_failure", 37, "99"),
            ("malformed JSON", '{"private":"' + private_path + '"}\n',
             "test-report-test.py", "unavailable",
             "unavailable", "nonzero_exit", 1, "99"),
            ("multiple failures",
             "FAIL: test_expected_negative "
             "(__main__.PassingFixture.test_expected_negative)\n"
             "FAIL: test_first (__main__.Other.test_first)\n"
             "ERROR: test_later (__main__.Other.test_later)\n",
             "primary-real-swap-test.py", "preflight",
             "test_first", "unittest_assertion", 52, "99"),
        )
        for (label, transcript, failing_phase, subtest, reported_test,
             reason, child_exit, source_line) in cases:
            with self.subTest(case=label):
                marker = (
                    f"FAIL: rootless phase={failing_phase} "
                    f"subtest={subtest} test={reported_test} exit={child_exit} "
                    f"reason={reason} phase_s=1 stage_s=2 line={source_line} "
                    f"log={diagnostic_log}\n")
                report = {"tested_commit_sha": source_sha, "stages": []}
                with patch.object(
                        runner.subprocess, "run",
                        return_value=SimpleNamespace(
                            stdout=transcript + marker,
                            returncode=child_exit)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    observed_exit = runner.run_stage(
                        "Native and rootless contracts", ["unused"], report)
                stage = report["stages"][0]
                self.assertEqual(observed_exit, child_exit)
                self.assertEqual(report["tested_commit_sha"], source_sha)
                self.assertEqual(stage["status"], "FAIL")
                self.assertEqual(stage["exit_code"], child_exit)
                self.assertEqual(stage["failed_phase"], failing_phase)
                for token in (
                        f"child_exit={child_exit}", f"reason={reason}",
                        f"subtest={subtest}", f"test={reported_test}",
                        f"log={diagnostic_log}"):
                    self.assertIn(token, stage["diagnostic"])
                if reported_test.startswith("test_"):
                    self.assertIn(
                        "Unit test failed: " + reported_test,
                        stage["diagnostic"])
                else:
                    self.assertNotIn(
                        "Unit test failed:", stage["diagnostic"])
                public_json = json.dumps(report)
                self.assertNotIn(private_path, public_json)
                self.assertNotIn("test_expected_negative", public_json)
                self.assertNotIn("test_wrong", public_json)
                self.assertNotIn("test_later", public_json)
                self.assertNotIn("Error 134", public_json)

        # A marker with a wrong child status or malformed log location cannot
        # authenticate a preceding, apparently precise unittest traceback.
        forged = (
            "FAIL: test_earlier (__main__.Earlier.test_earlier)\n"
            "FAIL: rootless phase=Makefile native and metadata "
            "subtest=compile test=test_earlier exit=2 "
            "reason=unittest_assertion phase_s=1 stage_s=2 line=99 "
            f"log={diagnostic_log}\n")
        for label, output in (
                ("exit mismatch", forged),
                ("malformed marker",
                 forged.replace(f"log={diagnostic_log}",
                                "log=/private/invalid"))):
            with self.subTest(case=label):
                report = {"stages": []}
                with patch.object(
                        runner.subprocess, "run",
                        return_value=SimpleNamespace(
                            stdout=output, returncode=1)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    runner.run_stage(
                        "Native and rootless contracts", ["unused"], report)
                stage = report["stages"][0]
                self.assertEqual(stage["exit_code"], 1)
                self.assertEqual(stage["failed_phase"],
                                 "Native and rootless contracts")
                self.assertNotIn("test_earlier", json.dumps(stage))
                self.assertNotIn(diagnostic_log, json.dumps(stage))
                self.assertIn("malformed or unverified", stage["diagnostic"])

    def test_tmp_cleanup_official_failure_retains_private_first_unittest(self):
        """Rootless negative controls for the unwrapped failing source suite."""
        from types import SimpleNamespace
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="report-tmp-cleanup-") as name:
            old_root = runner.ROOT
            runner.ROOT = Path(name)
            try:
                directory = (runner.ROOT / "build/tests" /
                             "rootless-failure.ABC12345")
                directory.mkdir(parents=True, mode=0o700)
                log_file = directory / "diagnostic.log"
                log_name = ("build/tests/rootless-failure.ABC12345/"
                            "diagnostic.log")

                def fail(transcript, exit_code=1, reason="nonzero_exit",
                         log=log_name, available=True, after_marker="",
                         initial_log_size=None):
                    log_file.unlink(missing_ok=True)
                    if available:
                        initial = (
                            "--- swapz rootless attribution ---\n"
                            f"exit_code={exit_code}\n").encode()
                        if initial_log_size is not None:
                            self.assertGreaterEqual(initial_log_size, len(initial))
                            initial += b"x" * (initial_log_size - len(initial))
                        log_file.write_bytes(initial)
                        log_file.chmod(0o600)
                    marker = (
                        "FAIL: rootless phase=tmp-cleanup-test.py "
                        "subtest=unavailable test=unavailable "
                        f"exit={exit_code} reason={reason} phase_s=1 stage_s=2 "
                        f"line=496 log={log}\n"
                        "Failed during: tests/runtime/native/tmp-cleanup-test.py\n"
                        f"Reason: exit={exit_code} reason={reason} "
                        "subtest=unavailable\n")
                    result = {"stages": []}
                    with patch.object(
                            runner.subprocess, "run",
                            return_value=SimpleNamespace(
                                stdout=transcript + marker + after_marker,
                                returncode=exit_code)), \
                            contextlib.redirect_stdout(io.StringIO()):
                        status = runner.run_stage(
                            "Native and rootless contracts",
                            ["python3", "-c", "pass"], result)
                    evidence = (log_file.read_text() if log_file.exists() else "")
                    return status, result["stages"][0], evidence

                # The detailed summary places a later teardown ERROR first;
                # the earlier verbose FAIL remains causal despite Make noise.
                output = (
                    "FAIL: test_expected_negative "
                    "(__main__.EarlierFixture.test_expected_negative)\n"
                    "make: *** [Makefile:40: concurrent] Error 9\n"
                    "test_first (__main__.OwnedTemporaryCleanupTests.test_first)"
                    " ... FAIL\n"
                    "test_cleanup (__main__.OwnedTemporaryCleanupTests.test_cleanup)"
                    " ... ERROR\n"
                    "======================================================================\n"
                    "ERROR: test_cleanup "
                    "(__main__.OwnedTemporaryCleanupTests.test_cleanup)\n"
                    "Traceback (most recent call last):\n"
                    "RuntimeError: LATER CLEANUP\n"
                    "======================================================================\n"
                    "FAIL: test_first (__main__.OwnedTemporaryCleanupTests.test_first)\n"
                    "Traceback (most recent call last):\n"
                    "  File \"/private/secret.py\", line 19, in test_first\n"
                    "AssertionError: FIRST CAUSE\n"
                    "----------------------------------------------------------------------\n"
                    "Ran 2 tests in 0.1s\nFAILED (failures=1, errors=1)\n"
                    + "x" * 300000 + "\n")
                status, stage, evidence = fail(output)
                self.assertEqual((status, stage["exit_code"], stage["status"]),
                                 (1, 1, "FAIL"))
                self.assertEqual(stage["failed_phase"], "tmp-cleanup-test.py")
                self.assertIn("reason=nonzero_exit", stage["diagnostic"])
                self.assertIn("subtest=unavailable test=unavailable",
                              stage["diagnostic"])
                self.assertIn("log=" + log_name, stage["diagnostic"])
                self.assertNotIn("/private/secret.py", stage["diagnostic"])
                self.assertNotIn("test_first", stage["diagnostic"])
                self.assertNotIn("test_expected_negative", stage["diagnostic"])
                self.assertIn("AssertionError: FIRST CAUSE", evidence)
                self.assertIn("/private/secret.py", evidence)
                self.assertLessEqual(log_file.stat().st_size, 262144)
                self.assertEqual(log_file.stat().st_mode & 0o777, 0o600)

                # A marker from an earlier child is not authoritative if
                # another rootless phase failed later in the same stage.
                later_marker = (
                    "FAIL: rootless phase=another-suite.py "
                    "subtest=unavailable test=unavailable exit=1 "
                    "reason=nonzero_exit phase_s=2 stage_s=3 "
                    "line=123 log=unavailable\n")
                _, _, ignored = fail(output, after_marker=later_marker)
                self.assertNotIn("first matched tmp-cleanup", ignored)

                exception = (
                    "test_first (__main__.OwnedTemporaryCleanupTests.test_first)"
                    " ... ERROR\n"
                    "ERROR: test_first "
                    "(__main__.OwnedTemporaryCleanupTests.test_first)\n"
                    "Traceback (most recent call last):\n"
                    "ValueError: ORIGINAL EXCEPTION\n")
                _, stage, evidence = fail(exception)
                self.assertIn("ValueError: ORIGINAL EXCEPTION", evidence)
                self.assertNotIn("test_first", stage["diagnostic"])

                # Unknown stderr remains private context only; it cannot be
                # upgraded into a matched unittest traceback or public identity.
                unknown = "unexpected child stderr without unittest framing\n"
                _, stage, evidence = fail(unknown)
                self.assertIn("private context only", evidence)
                self.assertIn(unknown.strip(), evidence)
                self.assertNotIn("first matched tmp-cleanup", evidence)
                self.assertIn("test=unavailable", stage["diagnostic"])

                # Exercise the cap edge where exactly one byte remains after
                # the two matched-traceback labels. Python's data[-0:] is the
                # whole buffer, so zero-budget slicing must be guarded.
                matched_label_bytes = 90 + 65
                initial_size = 262144 - matched_label_bytes - 1
                _, _, _ = fail(
                    exception, initial_log_size=initial_size)
                self.assertEqual(log_file.stat().st_size, 262144)

                # Silent nonzero, lost evidence, failed relay and timeout must
                # preserve the process exit without inventing a nested test.
                for case in (
                        {"transcript": "", "exit_code": 1},
                        {"transcript": "", "exit_code": 1,
                         "log": "unavailable", "available": False},
                        {"transcript": "", "exit_code": 1,
                         "reason": "stderr_relay_failure"},
                        {"transcript": "", "exit_code": 124,
                         "reason": "timeout_or_exit_124"}):
                    with self.subTest(case=case):
                        status, stage, evidence = fail(**case)
                        self.assertEqual(status, case["exit_code"])
                        self.assertEqual(stage["exit_code"], case["exit_code"])
                        self.assertEqual(stage["failed_phase"],
                                         "tmp-cleanup-test.py")
                        self.assertIn("test=unavailable", stage["diagnostic"])
                        self.assertIn("reason=" +
                                      case.get("reason", "nonzero_exit"),
                                      stage["diagnostic"])
                        self.assertNotIn("first matched tmp-cleanup", evidence)
            finally:
                runner.ROOT = old_root

    def test_randomized_native_failure_reports_safe_source_and_line(self):
        phase, reason = runner.failure_context(
            "FAIL: randomized-authority.c:188 expression=result == 0\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(
            reason,
            "FAIL: randomized-authority.c:188 expression=result == 0")

    def test_lower_write_aggregation_failure_reports_fixed_source_and_line(self):
        phase, reason = runner.failure_context(
            "FAIL: lower-write-aggregation.c:490 expression=maps[0].extent_blocks == 2\n",
            loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(
            reason,
            "FAIL: lower-write-aggregation.c:490 expression=maps[0].extent_blocks == 2")

    def test_exit_two_is_fail_before_loaded_stage_and_blocked_only_when_marked(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "test_results.json"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                rootless = [
                    "python3", "-c",
                    "import sys; print('/private/native.c:155: FAIL: extents == 3'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Native and rootless contracts",
                                         rootless, report), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "FAIL")
                self.assertEqual(stage["failed_phase"],
                                 "Native and rootless contracts")
                self.assertIn("extents == 3", stage["diagnostic"])
                self.assertNotIn("/private", stage["diagnostic"])
                self.assertNotIn("administrator", stage["failed_phase"])

                loaded = [
                    "python3", "-c",
                    "import sys; print('BLOCKED_LOADED_QUALIFICATION: no root'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Owned RAM smoke and 8 pairs",
                                         loaded, report, parse_bench=True), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "BLOCKED")
                self.assertIn("administrator authorization",
                              stage["failed_phase"])
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_loaded_codec_error_owner_paths_are_required_and_fail_closed(self):
        marker = (
            "PASS_LOADED_CODEC_ERROR_PATHS=owners:3 injected:3 "
            "inline_lower_write_delta:0 submitter_lower_write_delta:0 "
            "background_error_completions:8")
        output = synthetic_log()
        evidence = runner.parse_loaded_correctness(output)
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["codec_error_owners"], 3)
        self.assertEqual(evidence["codec_error_injected"], 3)
        self.assertEqual(evidence["codec_inline_lower_write_delta"], 0)
        self.assertEqual(evidence["codec_submitter_lower_write_delta"], 0)
        self.assertGreater(evidence["codec_background_error_completions"], 0)

        missing = runner.parse_loaded_correctness(output.replace(marker, "", 1))
        self.assertEqual(missing["overall"], "INCOMPLETE")
        self.assertIn("codec-errors", missing["reason"])

        for before, after in (
                ("owners:3", "owners:2"),
                ("injected:3", "injected:2"),
                ("inline_lower_write_delta:0", "inline_lower_write_delta:8"),
                ("submitter_lower_write_delta:0",
                 "submitter_lower_write_delta:8"),
                ("background_error_completions:8",
                 "background_error_completions:0")):
            bad = runner.parse_loaded_correctness(
                output.replace(marker, marker.replace(before, after), 1))
            self.assertEqual(bad["overall"], "INCOMPLETE")
            self.assertIn("codec-error", bad["reason"])

    def test_id36_resource_pressure_is_required_and_fail_closed(self):
        evidence = runner.parse_loaded_correctness(synthetic_log())
        self.assertEqual(evidence["overall"], "PASS", evidence)
        self.assertEqual(evidence["id36_pressure_mib"], 576)
        self.assertGreater(evidence["id36_memory_high_events"], 0)
        self.assertGreater(evidence["id36_cpu_some_usec"], 0)

        missing = synthetic_log().replace(
            "PASS_ID36_RESOURCE_PRESSURE=memory_high_events:8 "
            "memory_peak_bytes:734003200 cpu_some_usec:250000 cpu_workers:8 "
            "pressure_mib:576 oom:0 oom_kill:0\n", "", 1)
        diagnostic = runner.parse_loaded_correctness(missing)
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("id36", diagnostic["reason"].lower())

        oom = synthetic_log().replace(
            "pressure_mib:576 oom:0 oom_kill:0",
            "pressure_mib:576 oom:1 oom_kill:0", 1)
        diagnostic = runner.parse_loaded_correctness(oom)
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("ID36", diagnostic["reason"])

    def test_retired_parallel_read_diagnostic_is_observational(self):
        broken = synthetic_log().replace("PASS_PARALLEL_READ_AB=1\n", "", 1)
        fake_process = FakeStreamingProcess(broken)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke and pairs",
                                     ["unused"], report, parse_bench=True), 0)
        finally:
            runner.subprocess.Popen = original_popen
        self.assertTrue(fake_process.stdout.closed,
                        "streamed child stdout must be released")
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "PASS")
        diagnostic = report["benchmarks"]["parallel_read_ab"]
        self.assertEqual(diagnostic["overall"], "INCOMPLETE")
        self.assertIn("five counterbalanced matched rounds",
                      diagnostic["reason"])

    def test_incomplete_kernel_debug_evidence_fails_loaded_stage(self):
        marker = (
            "KERNEL_DEBUG_FEATURES=kasan:1 kcsan:0 lockdep:1 config:boot\n")
        broken = synthetic_log().replace(marker, "", 1)
        fake_process = FakeStreamingProcess(broken)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                                     ["unused"], report, parse_bench=True), 1)
        finally:
            runner.subprocess.Popen = original_popen
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["failed_phase"], "loaded kernel debug evidence")
        self.assertIn("missing or duplicated", stage["diagnostic"])

    def test_read_coalesce_diagnostic_failure_reports_its_own_reason(self):
        broken = synthetic_log().replace("PASS_READ_COALESCE_AB=1\n", "", 1)
        fake_process = FakeStreamingProcess(broken)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke and 8 pairs",
                                     ["unused"], report, parse_bench=True), 1)
        finally:
            runner.subprocess.Popen = original_popen
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["failed_phase"],
                         "adjacent READ coalescing A/B evidence")
        self.assertIn("confirmation", stage["diagnostic"])

    def test_expected_negative_recovery_refusals_do_not_mask_real_blocks(self):
        from unittest import mock

        # The live negative-recovery oracle prints command BLOCKED lines
        # before validating all 13 cases. A successful complete matrix may
        # authenticate exactly one source-controlled refusal in each case
        # whose injected fault is expected to return a refusal.
        refusals = runner.PRIMARY_NEGATIVE_CASE_REFUSALS
        self.assertEqual(len(refusals), 13)
        negative_lines = []
        for case_index, (case_name, contract) in enumerate(refusals.items()):
            negative_lines.append(
                "START_LOADED_PRIMARY_NULLBLK_NEGATIVE="
                f"{case_name} run_id:{case_index + 1:032x}")
            if contract is not None:
                operation, error_text = contract
                negative_lines.append(
                    f"BLOCKED: primary-swap {operation} failed: "
                    f"{error_text}")
        completion = (
            "PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY=cases:13 "
            "ambiguous_syscall:true inventory_failure:true "
            "definite_io_error:true wrong_mapper:true failed_swapoff:true "
            "stale_run:true fsync_failure:true lost_provenance:true "
            "repeat_recovery:safe host_swap_identity:preserved")
        full_log = synthetic_log()
        correctness = runner.parse_loaded_correctness(full_log)
        self.assertEqual(correctness["overall"], "PASS")
        expected_refusals = runner.authenticated_primary_negative_refusal_indices(
            full_log.splitlines(), correctness, 0)
        self.assertIsNotNone(expected_refusals)
        self.assertEqual(len(expected_refusals), 11)
        self.assertEqual(
            runner.loaded_progress_line(
                "BLOCKED: primary-swap stop failed: Device or resource busy",
                negative_case="swapoff-ebusy-noeffect"),
            "OBSERVED_PRIMARY_NEGATIVE_REFUSAL")
        self.assertEqual(
            runner.loaded_progress_line(
                "BLOCKED: primary-swap stop failed: Operation not permitted",
                negative_case="swapoff-ebusy-noeffect"),
            "BLOCKED: diagnostic retained for stage summary")
        self.assertEqual(
            runner.loaded_progress_line(
                "BLOCKED: primary-swap recovery failed: Operation not permitted",
                negative_case="swapon-eintr-applied"),
            "BLOCKED: diagnostic retained for stage summary")

        def run_synthetic(transcript, child_exit=0):
            report = {"schema": "swapz-test-results-v1", "stages": [],
                      "benchmarks": {"sessions": [], "verdicts": {}}}
            with mock.patch.object(
                    runner.subprocess, "Popen",
                    return_value=FakeStreamingProcess(
                        transcript, returncode=child_exit)), \
                    contextlib.redirect_stdout(io.StringIO()) as console:
                code = runner.run_stage(
                    "Owned RAM smoke + mixed/QD pilot", ["unused"],
                    report, parse_bench=True)
            return code, report["stages"][-1], console.getvalue()

        code, stage, output = run_synthetic(full_log)
        self.assertEqual((code, stage["status"]), (0, "PASS"), stage)
        self.assertNotIn("observed_exit=0", output)
        self.assertNotIn("BLOCKED: diagnostic retained", output)
        self.assertNotIn("OBSERVED_PRIMARY_NEGATIVE_REFUSAL", output)
        self.assertIn("ID | Name", output)
        self.assertNotIn("START_LOADED_PRIMARY_NULLBLK_NEGATIVE=", output)

        # The complete negative-recovery prefix is still valid if a later
        # raw-read owned pair fails. Do not relabel that failure as an
        # earlier negative-recovery authentication failure.
        complete_negative_index = next(
            index for index, line in enumerate(full_log.splitlines())
            if line.startswith("PASS_LOADED_PRIMARY_NULLBLK_NEGATIVE_RECOVERY="))
        completed_prefix = [
            line for line in full_log.splitlines()[:complete_negative_index + 1]
            if not line.startswith("PASS_LOADED_RAW_READ_FANOUT=")]
        raw_failure = ("BLOCKED: raw-read fanout profile=entropy "
                       "child_exit=2 cause=BLOCKED: owned RAM replay refused")
        partial_log = ("\n".join(completed_prefix + [
            "START_LOADED_RAW_READ_FANOUT", raw_failure]) + "\n")
        partial_correctness = runner.parse_loaded_correctness(partial_log)
        self.assertEqual(partial_correctness["overall"], "INCOMPLETE")
        self.assertEqual(len(runner.authenticated_primary_negative_refusal_indices(
            partial_log.splitlines(), partial_correctness, 2,
            allow_completed_prefix=True)), 11)
        code, stage, output = run_synthetic(partial_log, child_exit=2)
        self.assertEqual(code, 2)
        self.assertEqual(stage["status"], "BLOCKED")
        self.assertEqual(stage["failed_phase"],
                         "owned RAM raw-read fanout verification")
        self.assertIn("raw-read fanout profile=entropy", stage["diagnostic"])
        self.assertNotIn("negative recovery", stage["diagnostic"])
        self.assertIn("Raw read fanout verification", output)

        # An incomplete or invalid negative prefix cannot be authenticated
        # simply because the later raw-read START marker was observed.
        broken_partial = partial_log.replace(
            "BLOCKED: primary-swap start failed: Interrupted system call",
            "BLOCKED: primary-swap start failed: Operation not permitted", 1)
        code, stage, _ = run_synthetic(broken_partial, child_exit=2)
        self.assertEqual(code, 2)
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["failed_phase"],
                         "owned RAM primary lifecycle negative recovery")
        self.assertIn("failed authentication", stage["diagnostic"])

        original_block = ("BLOCKED: primary-swap start failed: "
                          "Interrupted system call")
        # Authentication failures are FAIL; independent explicit FAIL/BLOCKED
        # evidence keeps its own established stage semantics.
        adversarial = (
            ("unrelated after terminal", full_log +
             "BLOCKED: unexpected admission refusal\n", 0, "BLOCKED"),
            ("unrelated incomplete loaded gate", full_log.replace(
                "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 "
                "flush_calls:2\n", "", 1), 0, "FAIL"),
            ("wrong operation", full_log.replace(
                original_block,
                "BLOCKED: primary-swap recovery failed: "
                "Interrupted system call", 1), 0, "FAIL"),
            ("wrong cause", full_log.replace(
                original_block,
                "BLOCKED: primary-swap start failed: Operation not permitted",
                1), 0, "FAIL"),
            ("duplicated refusal", full_log.replace(
                original_block, original_block + "\n" + original_block,
                1), 0, "FAIL"),
            ("missing refusal", full_log.replace(
                original_block + "\n", "", 1), 0, "FAIL"),
            ("private data", full_log.replace(
                original_block, original_block + " path=/private/SECRET",
                1), 0, "FAIL"),
            ("untrusted case", full_log.replace(
                "NEGATIVE=swapon-eintr-noeffect",
                "NEGATIVE=unexpected-case", 1), 0, "FAIL"),
            ("incomplete matrix", full_log.replace(
                completion + "\n", "", 1), 0, "FAIL"),
            ("aggregate-only matrix", full_log.replace(
                "\n".join(negative_lines) + "\n", "", 1), 0, "FAIL"),
            ("nonzero child", full_log, 2, "FAIL"),
            ("genuine failure", full_log.replace(
                original_block,
                original_block + "\nFAIL: unanticipated fault", 1),
             0, "FAIL"),
            ("privilege block", full_log.replace(
                original_block,
                original_block + "\n"
                "BLOCKED_LOADED_QUALIFICATION: root unavailable", 1),
             0, "BLOCKED"),
        )
        authentication_failures = {
            "wrong operation", "wrong cause", "duplicated refusal",
            "missing refusal", "private data", "untrusted case",
            "incomplete matrix", "aggregate-only matrix", "nonzero child",
        }
        for title, transcript, child_exit, status in adversarial:
            with self.subTest(title=title):
                actual, stage, output = run_synthetic(transcript, child_exit)
                self.assertNotEqual(actual, 0, stage)
                self.assertEqual(stage["status"], status)
                if title == "private data":
                    self.assertNotIn("/private/SECRET", output)
                    self.assertNotIn("/private/SECRET", json.dumps(stage))
                if title in authentication_failures:
                    self.assertEqual(
                        stage["failed_phase"],
                        "owned RAM primary lifecycle negative recovery")
                    self.assertIn("failed authentication",
                                  stage["diagnostic"])
                else:
                    self.assertNotEqual(
                        stage.get("failed_phase"),
                        "owned RAM primary lifecycle negative recovery")
                    self.assertNotIn(
                        "failed authentication", stage.get("diagnostic", ""))

    def test_zero_exit_with_loaded_failure_evidence_stays_nonpass(self):
        from unittest import mock

        # A complete PASS transcript must not override later explicit
        # failure evidence even if the child wrongly reports exit 0.
        passing = synthetic_log()
        self.assertEqual(runner.parse_loaded_correctness(passing)["overall"],
                         "PASS")
        for marker, expected_status in (
                ("BLOCKED: /home/private/blocked", "BLOCKED"),
                ("FAIL: /home/private/failed", "FAIL"),
                ("FAIL_PRIMARY_NULLBLK_LIFECYCLE: failed", "FAIL")):
            with self.subTest(marker=marker.split(":", 1)[0]):
                log = (passing +
                       "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=stop\n" +
                       marker + "\n")
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                process = FakeStreamingProcess(log, returncode=0)
                with mock.patch.object(runner.subprocess, "Popen",
                                       return_value=process), \
                     contextlib.redirect_stdout(io.StringIO()) as output:
                    observed_exit = runner.run_stage(
                        "Owned RAM smoke + mixed/QD pilot", ["unused"],
                        report, parse_bench=True)
                self.assertEqual(observed_exit, 1)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], expected_status)
                self.assertEqual(stage["exit_code"], 1)
                self.assertEqual(stage["child_exit_code"], 0)
                self.assertEqual(stage["failed_phase"],
                                 "owned RAM primary lifecycle stop")
                self.assertIn("expected=nonzero observed_exit=0",
                              stage["diagnostic"])
                self.assertIn("evidence=recognized-failure-marker",
                              stage["diagnostic"])
                self.assertNotIn("/home/private", stage["diagnostic"])
                self.assertNotIn("/home/private", output.getvalue())

    def test_direct_nested_unittest_diagnostic_redacts_private_paths(self):
        log = (
            "FAIL: test_nested (__main__.Contract.test_nested)\n"
            "Failed during: /home/private/phase\n"
            "Reason: /home/private/trace failed\n"
        )
        phase, reason = runner.failure_context(
            log, loaded=False,
            default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertIn("Unit test failed: test_nested", reason)
        self.assertIn("nested [path]: [path] failed", reason)
        self.assertNotIn("/home/private", reason)

    def test_loaded_mount_inventory_eagain_reports_only_fixed_read_step(self):
        transcript = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
            "step=init-root errno=11 reason=process-root-device-mismatch "
            "peer_root=matches-process\n"
            "PRIMARY_PREPARE=FAILED phase=cross-namespace-mount-inventory "
            "errno=11 error=Resource temporarily unavailable\n"
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: preparation blocked\n"
        )
        phase, reason = runner.failure_context(transcript)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertIn("mount_step=init-root", reason)
        self.assertIn("mount_cause=process-root-device-mismatch", reason)
        self.assertIn("peer_root=matches-process", reason)
        self.assertIn("errno=11", reason)
        other_peer = transcript.replace(
            "peer_root=matches-process", "peer_root=differs-process")
        self.assertIn(
            "peer_root=differs-process",
            runner.failure_context(other_peer)[1])
        for unsafe in (
                transcript.replace("step=init-root", "step=/proc/SECRET"),
                transcript.replace("step=init-root errno=11",
                                   "step=init-root errno=11 host=SECRET"),
                transcript.replace("reason=process-root-device-mismatch",
                                   "reason=PRIVATE_OVERRIDDEN"),
                transcript.replace("step=init-root", "step=root-walk"),
                transcript.replace("peer_root=matches-process",
                                   "peer_root=private-identity"),
                transcript.replace("reason=process-root-device-mismatch",
                                   "reason=root-inode-mismatch"),
                transcript.replace("errno=11 error=Resource",
                                   "errno=1 error=Resource")):
            with self.subTest(unsafe=unsafe[-100:]):
                _, safe_reason = runner.failure_context(unsafe)
                self.assertNotIn("mount_step=", safe_reason)
                self.assertNotIn("mount_cause=", safe_reason)
                self.assertNotIn("peer_root=", safe_reason)
                self.assertNotIn("SECRET", safe_reason)

    def test_mountinfo_table_overflow_reports_bounded_read_cause(self):
        for step, cause in (
                ("mountinfo-read", "per-table-byte-limit"),
                ("mountinfo-read", "read-overflow"),
                ("mountinfo-aggregate", "aggregate-byte-limit")):
            with self.subTest(step=step, cause=cause):
                transcript = (
                    "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
                    "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
                    f"step={step} errno=75 reason={cause}\n"
                    "PRIMARY_PREPARE=FAILED "
                    "phase=cross-namespace-mount-inventory "
                    "errno=75 error=Value too large for defined data type\n"
                    "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: "
                    "preparation blocked\n"
                )
                phase, reason = runner.failure_context(transcript)
                self.assertEqual(phase, "owned RAM primary lifecycle prepare")
                self.assertIn(f"mount_step={step}", reason)
                self.assertIn(f"mount_cause={cause}", reason)
                invalid = transcript.replace(f"step={step}",
                                             "step=init-root")
                _, rejected = runner.failure_context(invalid)
                self.assertNotIn("mount_step=", rejected)
                self.assertNotIn("mount_cause=", rejected)
                self.assertNotIn("/proc/", reason)

    def test_mount_inventory_overflow_reports_fixed_operation_and_cause(self):
        transcript = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
            "step=root-walk errno=75 reason=statmount-buffer-too-small\n"
            "PRIMARY_PREPARE=FAILED phase=cross-namespace-mount-inventory "
            "errno=75 error=Value too large for defined data type\n"
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: preparation blocked\n"
        )
        phase, reason = runner.failure_context(transcript)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertIn("errno=75", reason)
        self.assertIn("mount_step=root-walk", reason)
        self.assertIn("mount_cause=statmount-buffer-too-small", reason)
        for unsafe in (
                transcript.replace("step=root-walk", "step=init-root"),
                transcript.replace("reason=statmount-buffer-too-small",
                                   "reason=PRIVATE"),
                transcript.replace("errno=75 error=Value",
                                   "errno=11 error=Value")):
            with self.subTest(unsafe=unsafe[-100:]):
                _, rejected = runner.failure_context(unsafe)
                self.assertNotIn("mount_step=", rejected)
                self.assertNotIn("mount_cause=", rejected)

    def test_root_superblock_mismatch_retains_first_fail_closed_diagnostic(self):
        transcript = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
            "step=root-walk errno=11 reason=root-superblock-device-mismatch\n"
            "PRIMARY_PREPARE=FAILED phase=cross-namespace-mount-inventory "
            "errno=11 error=Resource temporarily unavailable\n"
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: preparation blocked\n"
        )
        phase, reason = runner.failure_context(transcript)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertIn("mount_step=root-walk", reason)
        self.assertIn("mount_cause=root-superblock-device-mismatch", reason)
        for invalid_step in ("init-root", "mount-list", "listed-mount"):
            with self.subTest(step=invalid_step):
                _, rejected = runner.failure_context(
                    transcript.replace("step=root-walk", f"step={invalid_step}"))
                self.assertNotIn("mount_step=", rejected)
                self.assertNotIn("mount_cause=", rejected)

    def test_loaded_root_device_disagreement_explains_safe_read_only_next_step(self):
        from unittest import mock

        header = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "SWAPZ_PRIMARY_MOUNT_INVENTORY_FAILURE "
            "step=init-root errno=11 reason=process-root-device-mismatch "
            "peer_root={}\n"
            "PRIMARY_PREPARE=FAILED phase=cross-namespace-mount-inventory "
            "errno=11 error=Resource temporarily unavailable\n"
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: preparation blocked\n"
        )
        for peer_root in ("matches-process", "differs-process"):
            with self.subTest(peer_root=peer_root):
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                fake_process = FakeStreamingProcess(
                    header.format(peer_root), returncode=2)
                with mock.patch.object(runner.subprocess, "Popen",
                                       return_value=fake_process), \
                     contextlib.redirect_stdout(io.StringIO()) as console:
                    self.assertEqual(
                        runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                                         ["unused"], report, parse_bench=True),
                        2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "BLOCKED")
                self.assertIn(f"peer_root={peer_root}", stage["diagnostic"])
                output = console.getvalue()
                self.assertIn("Reason: BLOCKED_PRIMARY_NULLBLK_LIFECYCLE",
                              output)
                self.assertEqual(
                    "Root comparison:" in output,
                    peer_root == "matches-process")
                self.assertEqual(
                    "Safe next step:" in output,
                    peer_root == "matches-process")
                self.assertNotIn("/proc/", output)

    def test_loaded_failure_diagnostic_stays_with_current_phase(self):
        log = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "FAIL: expected negative from completed phase\n"
            "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_SHARED_BENCHMARK_PLAN=trace\n"
            "opaque child failure\n"
        )
        phase, reason = runner.failure_context(log)
        self.assertEqual(phase, "shared fixture preparation trace")
        self.assertEqual(
            reason, "Shared benchmark plan trace step returned nonzero")
        self.assertNotIn("expected negative", reason)

    def test_loaded_cleanup_epilogue_never_replaces_specific_failure(self):
        for child_exit in (1, 124, 137, 143):
            with self.subTest(child_exit=child_exit):
                phase, reason = runner.failure_context(
                    "START_LOADED_SUSPEND_DRAIN\n"
                    "FAIL: retained lifecycle errno=5\n"
                    f"FAIL: test exit {child_exit}; safe teardown attempted\n")
                self.assertEqual(phase, "owned RAM retained suspend/drain")
                self.assertEqual(reason, "FAIL: retained lifecycle errno=5")

    def test_loaded_kernel_debug_failure_owns_its_phase(self):
        fake_process = FakeStreamingProcess(
            synthetic_log() +
            "FAIL: loaded kernel debug diagnostics implicated swapz\n",
            returncode=1)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                                     ["unused"], report, parse_bench=True), 1)
        finally:
            runner.subprocess.Popen = original_popen
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "FAIL")
        self.assertEqual(stage["failed_phase"], "loaded kernel debug evidence")
        self.assertEqual(
            stage["diagnostic"],
            "FAIL: loaded kernel debug diagnostics implicated swapz")

    def test_primary_lifecycle_blocked_marker_classifies_loaded_stage_blocked(self):
        log = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=setup\n"
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: owned null_blk unavailable\n"
        )
        fake_process = FakeStreamingProcess(log, returncode=2)
        original_popen = runner.subprocess.Popen
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        try:
            runner.subprocess.Popen = lambda *args, **kwargs: fake_process
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    runner.run_stage("Owned RAM smoke + mixed/QD pilot",
                                     ["unused"], report, parse_bench=True), 2)
        finally:
            runner.subprocess.Popen = original_popen
        stage = report["stages"][-1]
        self.assertEqual(stage["status"], "BLOCKED")
        self.assertEqual(stage["failed_phase"],
                         "owned RAM primary lifecycle setup")
        self.assertIn("BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:",
                      stage["diagnostic"])

    def test_primary_lifecycle_failure_overrides_prior_blocked_line(self):
        log = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=start\n"
            "BLOCKED: primary-swap start failed: No such file or directory\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator start failed\n"
        )
        report = {"schema": "swapz-test-results-v1", "stages": [],
                  "benchmarks": {"sessions": [], "verdicts": {}}}
        original_popen = runner.subprocess.Popen
        try:
            for child_exit in (1, 0):
                runner.subprocess.Popen = lambda *args, **kwargs: (
                    FakeStreamingProcess(log, returncode=child_exit))
                with contextlib.redirect_stdout(io.StringIO()):
                    actual_exit = runner.run_stage(
                        "Owned RAM smoke + mixed/QD pilot", ["unused"],
                        report, parse_bench=True)
                self.assertEqual(actual_exit, 1)
                self.assertEqual(report["stages"][-1]["status"], "FAIL")
                self.assertEqual(report["stages"][-1]["failed_phase"],
                                 "owned RAM primary lifecycle start")
                expected_diagnostic = (
                    "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator start: "
                    "No such file or directory")
                if child_exit == 0:
                    expected_diagnostic += (
                        "; expected=nonzero observed_exit=0 "
                        "evidence=recognized-failure-marker")
                    self.assertEqual(
                        report["stages"][-1]["child_exit_code"], 0)
                else:
                    self.assertNotIn("child_exit_code",
                                     report["stages"][-1])
                self.assertEqual(
                    report["stages"][-1]["diagnostic"],
                    expected_diagnostic)
        finally:
            runner.subprocess.Popen = original_popen

    def test_primary_negative_refusal_does_not_mask_later_case_failure(self):
        run_id = "a" * 32
        log = (
            "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=recover-restored "
            f"run_id:{run_id}\n"
            "PASS_LOADED_PRIMARY_NULLBLK_INTERRUPTION_RECOVERY=cases:18\n"
            "START_LOADED_PRIMARY_NULLBLK_NEGATIVE="
            f"swapoff-ebusy-noeffect run_id:{run_id}\n"
            "BLOCKED: primary-swap stop failed: Device or resource busy\n"
            "START_LOADED_PRIMARY_NULLBLK_NEGATIVE="
            f"stale-run-id run_id:{run_id}\n"
            "BLOCKED: primary-swap recovery failed: Operation not permitted\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: stale-run-id "
            "expected=canonical-refusal-lines:2 observed_lines=3\n"
        )

        phase, reason = runner.failure_context(log)
        self.assertEqual(
            phase,
            "owned RAM primary lifecycle negative stale-run-id")
        self.assertEqual(
            reason,
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: stale-run-id "
            "expected=canonical-refusal-lines:2 observed_lines=3")

    def test_owner_artifact_digests_required(self):
        hashes = {"status": "AVAILABLE", "formatter_sha256": "a" * 64,
                  "module_sha256": "b" * 64, "oracle_sha256": "c" * 64}
        self.assertTrue(runner.owner_qualification_artifacts_available(hashes))
        for invalid in ({**hashes, "status": "UNAVAILABLE"},
                        {**hashes, "module_sha256": "b" * 63},
                        {**hashes, "extra": True}):
            self.assertFalse(runner.owner_qualification_artifacts_available(invalid))

    def test_failure_phase_tracks_latest_benchmark_subphase_without_growth(self):
        log = (
            "START_STORAGE_ENVELOPE=nvme_gen5\n" +
            ("BENCH_IO_PHASE=off:prefill\n"
             "BENCH_IO_PHASE=off:mixed\n"
             "BENCH_IO_PHASE=swapz:packed_read\n") * 200 +
            "BLOCKED: ID36 host lacks 1 GiB MemAvailable safety headroom\n"
        )
        phase, reason = runner.failure_context(log)
        self.assertEqual(
            phase, "nvme_gen5 synthetic service envelope [swapz packed_read]")
        self.assertLessEqual(len(phase), 96)
        self.assertIn("ID36 host lacks", reason)

    def test_loaded_failure_identifies_failed_phase_without_private_paths(self):
        # This was a real regression: privileged benchmarks created
        # build/benchmark/ (mode 0700), then a non-root user attempted
        # mktemp in the same root-owned directory.
        log = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
               "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
               "mktemp: failed to create directory via template "
               "'/home/secret/swapz/build/benchmark/shared.XXXXXXXX': "
               "Permission denied\n")
        phase, reason = runner.failure_context(log)
        self.assertIn("shared fixture", phase)
        self.assertIn("not writable", reason)
        self.assertNotIn("/home/secret", reason)

        for step in ("allocation", "fixture", "trace", "write-plans", "verify"):
            with self.subTest(shared_plan_step=step):
                phase, reason = runner.failure_context(
                    "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
                    f"START_LOADED_SHARED_BENCHMARK_PLAN={step}\n"
                    "/home/private/path must not leak\n")
                self.assertIn(step, phase)
                self.assertEqual(
                    reason,
                    f"Shared benchmark plan {step} step returned nonzero")
                self.assertNotIn("/home/private", reason)

        blocked = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
                   "BLOCKED: backing mismatch: "
                   "/home/private/dev/nullb-swapz-abcdef0123456789\n")
        phase, reason = runner.failure_context(blocked)
        self.assertIn("owned RAM kernel smoke", phase)
        self.assertIn("BLOCKED:", reason)
        self.assertNotIn("/home/private", reason)
        self.assertNotIn("swapz", reason)
        self.assertNotIn("abcdef0123456789", reason)

        pair = ("PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
                "FAIL: independent backing lower I/O mismatch\n")
        phase, reason = runner.failure_context(pair)
        self.assertIn("comparison 2/8 (async)", phase)
        self.assertIn("backing lower I/O mismatch", reason)
        lifecycle = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_SUSPEND_DRAIN\n"
            "FAIL: retained lifecycle bytes changed\n"
        )
        phase, reason = runner.failure_context(lifecycle)
        self.assertIn("suspend/drain", phase)
        self.assertIn("retained lifecycle bytes changed", reason)

        primary_lifecycle = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: recovery failed for "
            "/var/lib/private/run-0123456789abcdef0123456789abcdef\n"
        )
        phase, reason = runner.failure_context(primary_lifecycle)
        self.assertIn("primary", phase.lower())
        self.assertIn("FAIL_PRIMARY_NULLBLK_LIFECYCLE:", reason)
        self.assertIn("recovery failed", reason)
        self.assertNotIn("/var/lib/private", reason)
        self.assertNotIn("0123456789abcdef0123456789abcdef", reason)
        self.assertIn("FAIL_PRIMARY_NULLBLK_LIFECYCLE",
                      runner.safe_lines(primary_lifecycle))
        self.assertEqual(
            runner.loaded_progress_line(
                "FAIL_PRIMARY_NULLBLK_LIFECYCLE: private detail"),
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE")

        start_subphase = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=start\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator start failed\n"
        )
        phase, reason = runner.failure_context(start_subphase)
        self.assertEqual(phase, "owned RAM primary lifecycle start")
        self.assertIn("coordinator start failed", reason)

        start_command_failure = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=start\n"
            "BLOCKED: primary-swap start failed: Operation not permitted\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: "
            "production coordinator start failed on owned null_blk\n"
        )
        phase, reason = runner.failure_context(start_command_failure)
        self.assertEqual(phase, "owned RAM primary lifecycle start")
        self.assertEqual(
            reason,
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator start: "
            "Operation not permitted")

        unsafe_command_failure = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "BLOCKED: primary-swap preparation failed: /private/device/path\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: prepare failed\n"
        )
        phase, reason = runner.failure_context(unsafe_command_failure)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertEqual(
            reason, "FAIL_PRIMARY_NULLBLK_LIFECYCLE: prepare failed")
        self.assertNotIn("/private", reason)

        prepare_gate_failure = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "PRIMARY_PREPARE=FAILED phase=qualification-report-read "
            "errno=1 error=Operation not permitted "
            "run_id=0123456789abcdef0123456789abcdef "
            "claim=retained target_unchanged=true\n"
            "BLOCKED: primary-swap preparation failed: "
            "Operation not permitted\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: prepare failed\n"
        )
        phase, reason = runner.failure_context(prepare_gate_failure)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertEqual(
            reason,
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator preparation "
            "phase=qualification-report-read errno=1 "
            "error=Operation not permitted")
        self.assertNotIn("0123456789abcdef", reason)

        # The owned-nullblk helper re-emits the validated phase record but
        # intentionally does not expose its captured command wrapper. Preserve
        # the actionable sub-check without requiring that wrapper line.
        prepare_gate_without_wrapper = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE=prepare\n"
            "PRIMARY_PREPARE=FAILED phase=qualification-report-read "
            "errno=13 error=Permission denied "
            "run_id=0123456789abcdef0123456789abcdef "
            "claim=none\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: "
            "production coordinator prepare failed on owned null_blk\n"
        )
        phase, reason = runner.failure_context(prepare_gate_without_wrapper)
        self.assertEqual(phase, "owned RAM primary lifecycle prepare")
        self.assertEqual(
            reason,
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: coordinator preparation "
            "phase=qualification-report-read errno=13 error=Permission denied")
        self.assertNotIn("0123456789abcdef", reason)

        interrupted = (
            "START_LOADED_PRIMARY_NULLBLK_LIFECYCLE\n"
            "PASS_LOADED_PRIMARY_NULLBLK_LIFECYCLE=run_id:redacted\n"
            "START_LOADED_PRIMARY_NULLBLK_INTERRUPTION=start-swapon run_id=redacted\n"
            "FAIL_PRIMARY_NULLBLK_LIFECYCLE: unexpected kernel facts\n"
        )
        phase, reason = runner.failure_context(interrupted)
        self.assertIn("primary lifecycle interruption start-swapon", phase)
        self.assertIn("unexpected kernel facts", reason)

        blocked_primary = (
            "BLOCKED_PRIMARY_NULLBLK_LIFECYCLE: prior evidence at "
            "/var/lib/private/0123456789abcdef0123456789abcdef\n"
        )
        _, reason = runner.failure_context(blocked_primary)
        self.assertIn("BLOCKED_PRIMARY_NULLBLK_LIFECYCLE:", reason)
        self.assertNotIn("/var/lib/private", reason)
        self.assertNotIn("0123456789abcdef0123456789abcdef", reason)

        discard_trim = (
            "START_LOADED_OWNED_NULLBLK_SMOKE\n"
            "START_LOADED_DISCARD_TRIM\n"
            "FAIL: owned upper DISCARD failed\n"
        )
        phase, reason = runner.failure_context(discard_trim)
        self.assertIn("discard-time TRIM reclamation", phase)
        self.assertIn("owned upper DISCARD failed", reason)

        loaded_subphase = (
            "START_OWNED_RAM_REGIME=sd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
            "BENCH_IO_PHASE=swapz:packed_read\n"
            "FAIL: verified fixed volume was not returned\n"
        )
        phase, reason = runner.failure_context(loaded_subphase)
        self.assertIn("sd_emulated comparison 1/8 (sync)", phase)
        self.assertIn("[swapz packed_read]", phase)
        self.assertIn("verified fixed volume", reason)

        replay_detail = (
            "START_OWNED_RAM_REGIME=ssd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
            "BENCH_IO_PHASE=swapz:packed_read\n"
            "BLOCKED/FAIL: short or mismatched packed swap-in page\n"
            "BLOCKED: swapz replay rejected\n"
        )
        phase, reason = runner.failure_context(replay_detail)
        self.assertIn("ssd_emulated comparison 1/8 (async)", phase)
        self.assertIn("[swapz packed_read]", phase)
        self.assertEqual(reason, "FAIL: short or mismatched packed swap-in page")

    def test_loaded_quarantine_reports_specific_sanitized_reason(self):
        log = (
            "START_OWNED_RAM_REGIME=sd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
            "QUARANTINED: owned DM removal failed open:1->1\n"
            "BLOCKED: retain all remaining resources for read-only investigation\n"
        )
        phase, reason = runner.failure_context(log)
        self.assertIn("sd_emulated comparison 1/8 (sync)", phase)
        self.assertEqual(
            reason, "Safety quarantine: owned DM removal failed open:1->1")

    def test_native_failure_identifies_sanitized_helper_error(self):
        log = "predictor sampling/route control failed: -117\n"
        phase, reason = runner.failure_context(
            log, loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(phase, "Native and rootless contracts")
        self.assertEqual(reason,
                         "Native helper: predictor sampling/route control failed: -117")

        compiler = "/home/private/build/predictor.c:10: error: signedness mismatch\n"
        _, reason = runner.failure_context(
            compiler, loaded=False, default_phase="Native and rootless contracts")
        self.assertEqual(reason, "Native build error: signedness mismatch")

    def test_non_root_fixture_never_uses_privileged_evidence_directory(self):
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        private = (ROOT / "tests/tools/benchmark-owned-pair.sh").read_text()
        self.assertIn('mkdir -p "$ROOT/build/tests"', loaded)
        self.assertIn('mktemp -d "$ROOT/build/tests/benchmark-plan.XXXXXXXX"', loaded)
        self.assertIn(
            "START_LOADED_SHARED_BENCHMARK_PLAN=allocation", loaded)
        self.assertIn(
            "PASS_LOADED_SHARED_BENCHMARK_PLAN", loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', private)
        self.assertNotIn('mktemp -d "$ROOT/build/benchmark/', loaded)
        # Simulate the historical mode-0700 benchmark log directory without
        # any privilege or actual device. A fixture can still be created.
        import os
        with tempfile.TemporaryDirectory(prefix="fixture-permissions-",
                                         dir=ROOT / "build/tests") as folder:
            root = Path(folder)
            evidence = root / "benchmark"
            evidence.mkdir()
            evidence.chmod(0o500)
            scratch = root / "tests"
            scratch.mkdir()
            try:
                import tempfile as temporary
                owned = Path(temporary.mkdtemp(prefix="benchmark-plan.",
                                              dir=scratch))
                self.assertTrue(owned.is_dir())
                (owned / "fixture.bin").write_bytes(b"safe")
                self.assertEqual((owned / "fixture.bin").read_bytes(), b"safe")
            finally:
                evidence.chmod(0o700)




    def test_algorithm_ram_development_evidence_is_private_and_exact_source(self):
        source = "a" * 40
        stages = [
            {"name": name, "status": "PASS", "exit_code": 0, "elapsed_s": 1.0}
            for name in runner.OFFICIAL_STAGE_NAMES
        ]
        artifacts = {
            "status": "AVAILABLE",
            "formatter_sha256": "b" * 64,
            "module_sha256": "c" * 64,
            "oracle_sha256": "d" * 64,
        }
        result = {
            "source_sha": source,
            "tested_commit_sha": source,
            "stages": stages,
            "qualified_artifacts": artifacts,
        }
        with tempfile.TemporaryDirectory() as directory:
            old_root = runner.ROOT
            runner.ROOT = Path(directory)
            head = "e" * 40
            completed = subprocess.CompletedProcess(
                ["git", "rev-parse", "HEAD"], 0,
                stdout=(head + "\n").encode("ascii"), stderr=b"")
            try:
                with mock.patch.object(runner, "git_result",
                                       return_value=completed), \
                     mock.patch.object(runner, "git_sha", return_value=source):
                    path, nonce = runner.write_algorithm_ram_development_evidence(
                        result)
                self.assertEqual(path.parent, runner.ROOT / "build/tests")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    record["schema"],
                    "swapz-algorithm-ram-development-evidence-v1")
                self.assertEqual(record["head"], head)
                self.assertEqual(record["source_sha"], source)
                self.assertEqual(record["nonce"], nonce)
                self.assertEqual(
                    record["artifact_sha256"],
                    {key: artifacts[key] for key in (
                        "formatter_sha256", "module_sha256", "oracle_sha256")})
                broken = dict(result)
                broken["stages"] = stages[:-1]
                with self.assertRaisesRegex(ValueError, "five exact PASS"):
                    runner.write_algorithm_ram_development_evidence(broken)
            finally:
                runner.ROOT = old_root

    def test_git_only_report_sync_updates_main_and_keeps_one_report_file(self):
        """Exercise real Git plumbing against a local bare remote."""
        import os
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-git-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin = sandbox / "checkout", sandbox / "origin.git"
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("int source(void){return 7;}\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Testable source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    original = {
                        "schema": "swapz-test-results-v1",
                        "qualification": "RAM_BACKED_NULL_BLK_ONLY",
                        "source_sha": source_sha,
                        "tested_commit_sha": source_sha,
                        "overall": "BLOCKED",
                    }
                    runner.write_report({**original, "overall": "PASS"})
                    self.assertIn(
                        "phase=report-admission reason=incomplete_or_failed_stages",
                        runner.publish(source_sha))
                    runner.write_report(original)
                    # A staged previous/generated report is not a source edit.
                    # Publication must replace it without masking real C changes.
                    git("add", runner.GIT_RESULT, cwd=checkout)
                    first = runner.publish(source_sha)
                    self.assertIn("SYNCED_GIT", first)
                    first_head = git("rev-parse", "HEAD",
                                     cwd=checkout).stdout.strip()
                    first_remote = git("--git-dir", str(origin), "rev-parse",
                                       "refs/heads/main",
                                       cwd=sandbox).stdout.strip()
                    self.assertEqual(first_head, first_remote)
                    self.assertNotEqual(source_sha, first_head)
                    self.assertIn(
                        f"/blob/{first_head}/{runner.GIT_RESULT}", first)
                    self.assertIn(f"report_commit={first_head}", first)
                    self.assertEqual(git("status", "--porcelain",
                                         cwd=checkout).stdout, "")
                    self.assertEqual(
                        json.loads((checkout / runner.GIT_RESULT).read_text(
                            encoding="utf-8")),
                        original)

                    self.assertEqual(runner.git_sha(), source_sha)
                    updated = dict(original, overall="FAIL")
                    runner.write_report(updated)
                    second = runner.publish(source_sha)
                    self.assertIn("SYNCED_GIT", second)
                    second_head = git("rev-parse", "HEAD",
                                      cwd=checkout).stdout.strip()
                    self.assertNotEqual(first_head, second_head)
                    self.assertIn(
                        f"/blob/{second_head}/{runner.GIT_RESULT}", second)
                    self.assertIn(f"report_commit={second_head}", second)
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        second_head)
                    self.assertEqual(
                        json.loads((checkout / runner.GIT_RESULT).read_text(
                            encoding="utf-8")),
                        updated)
                    self.assertEqual(len(list(checkout.glob("*.json"))), 1)

                    (checkout / "source.c").write_text("unsaved owner change\n")
                    blocked = dict(updated, overall="BLOCKED")
                    runner.write_report(blocked)
                    before = git("--git-dir", str(origin), "rev-parse",
                                 "refs/heads/main", cwd=sandbox).stdout.strip()
                    self.assertIn("not clean", runner.publish(source_sha))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        before)

                    # A staged source edit is still dirty, unlike a staged
                    # generated report. A later clean source commit is stale
                    # relative to the already tested revision.
                    git("add", "source.c", cwd=checkout)
                    self.assertIn("not clean", runner.publish(source_sha))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        before)
                    git("commit", "-m", "Change source after test", cwd=checkout)
                    self.assertIn("checkout changed", runner.publish(source_sha))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        before)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report


    def test_git_sha_walks_report_only_chains_beyond_32_commits(self):
        """Repeated qualifications never turn a report commit into source."""
        import subprocess

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-chain-", dir=ROOT / "build/tests") as name:
            checkout = Path(name)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

            for index in range(40):
                (checkout / runner.GIT_RESULT).write_text(
                    json.dumps({"run": index}), encoding="utf-8")
                git("add", runner.GIT_RESULT, cwd=checkout)
                git("commit", "-m",
                    f"test: latest run for {source_sha[:12]} [skip ci]",
                    cwd=checkout)

            old_root = runner.ROOT
            runner.ROOT = checkout
            try:
                self.assertEqual(runner.git_sha(), source_sha)
                self.assertEqual(
                    git("log", "-1", "--format=%H", "HEAD", "--", ".",
                        ":(exclude)test_results.json",
                        cwd=checkout).stdout.strip(), source_sha)
                (checkout / "source.c").write_text("changed source\n")
                git("add", "source.c", cwd=checkout)
                git("commit", "-m", "Later executable source", cwd=checkout)
                changed_sha = git("rev-parse", "HEAD",
                                  cwd=checkout).stdout.strip()
                self.assertNotEqual(changed_sha, source_sha)
                self.assertEqual(runner.git_sha(), changed_sha)
                self.assertEqual(
                    git("log", "-1", "--format=%H", "HEAD", "--", ".",
                        ":(exclude)test_results.json",
                        cwd=checkout).stdout.strip(), changed_sha)
            finally:
                runner.ROOT = old_root

    def test_git_sync_retries_after_concurrent_main_advance(self):
        """Delayed older-source evidence is archived, never made canonical."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-race-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("old source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "concurrent writer", cwd=peer)
            git("config", "user.email", "writer@example.invalid", cwd=peer)
            (peer / "source.c").write_text("newer source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Concurrent source", cwd=peer)
            concurrent_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()
            # Populate the private bare remote without host pre-push hooks.
            # The publisher's own push behavior is exercised separately.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(peer), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    failed = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": source_sha,
                        "tested_commit_sha": source_sha,
                        "overall": "FAIL",
                    }
                    runner.write_report(failed)
                    notice = runner.publish(source_sha)
                    self.assertIn("ARCHIVED_GIT", notice)

                    remote_head = git("--git-dir", str(origin), "rev-parse",
                                      "refs/heads/main",
                                      cwd=sandbox).stdout.strip()
                    archived_head = git(
                        "--git-dir", str(origin), "rev-parse",
                        f"{remote_head}^", cwd=sandbox).stdout.strip()
                    self.assertIn(
                        f"/blob/{archived_head}/{runner.GIT_RESULT}", notice)
                    self.assertIn(f"report_commit={archived_head}", notice)
                    self.assertIn(f"main_commit={remote_head}", notice)
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            f"{archived_head}^", cwd=sandbox).stdout.strip(),
                        concurrent_sha)
                    self.assertEqual(
                        git("--git-dir", str(origin), "show",
                            f"{remote_head}:source.c", cwd=sandbox).stdout,
                        "newer source\n")
                    # The restoration commit keeps the newer main tree's
                    # canonical report; the delayed report is history-only.
                    self.assertEqual(
                        git("--git-dir", str(origin), "show",
                            f"{remote_head}:{runner.GIT_RESULT}",
                            cwd=sandbox).stdout,
                        '{"overall":"NOT_RUN"}\n')
                    self.assertEqual(
                        json.loads(git(
                            "--git-dir", str(origin), "show",
                            f"{archived_head}:{runner.GIT_RESULT}",
                            cwd=sandbox).stdout),
                        failed)
                    self.assertEqual(
                        git("rev-parse", "HEAD", cwd=checkout).stdout.strip(),
                        source_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_declines_concurrent_same_source_report_update(self):
        """A delayed same-source result cannot overwrite newer report evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-same-source-race-",
                dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("same source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "concurrent tester", cwd=peer)
            git("config", "user.email", "tester@example.invalid", cwd=peer)
            newer = {
                "schema": "swapz-test-results-v1",
                "source_sha": source_sha,
                "tested_commit_sha": source_sha,
                "overall": "FAIL",
                "synthetic_run": "newer",
            }
            (peer / runner.GIT_RESULT).write_text(
                json.dumps(newer) + "\n", encoding="utf-8")
            git("add", runner.GIT_RESULT, cwd=peer)
            git("commit", "-m",
                f"test: latest run for {source_sha[:12]} [skip ci]",
                cwd=peer)
            peer_report_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()
            # Populate the private bare remote without host pre-push hooks.
            # The publisher's own push behavior is exercised separately.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(peer), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT
            comparison_errors = {"remaining": 1}

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                if (command == [
                        "diff", "--quiet", source_sha, peer_report_sha,
                        "--", runner.GIT_RESULT] and
                        comparison_errors["remaining"]):
                    comparison_errors["remaining"] -= 1
                    return subprocess.CompletedProcess(
                        command, 128, stdout=b"",
                        stderr=b"simulated private git failure")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                delayed = {
                    "schema": "swapz-test-results-v1",
                    "source_sha": source_sha,
                    "tested_commit_sha": source_sha,
                    "overall": "FAIL",
                    "synthetic_run": "older",
                }
                runner.write_report(delayed)
                with mock.patch.object(
                        runner, "git_result", side_effect=intercept), \
                     mock.patch.object(runner.time, "sleep"):
                    self.assertEqual(
                        runner.publish(source_sha),
                        "GIT_SYNC_FAILED: could not compare concurrent "
                        "qualification evidence")
                    second_notice = runner.publish(source_sha)
                    self.assertIn("ARCHIVED_GIT", second_notice)

                remote_head = git("--git-dir", str(origin), "rev-parse",
                                  "refs/heads/main", cwd=sandbox).stdout.strip()
                self.assertNotEqual(remote_head, peer_report_sha)
                remote_report = json.loads(
                    git("--git-dir", str(origin), "show",
                        f"{remote_head}:{runner.GIT_RESULT}",
                        cwd=sandbox).stdout)
                self.assertEqual(remote_report, newer)
                archived_sha = git(
                    "--git-dir", str(origin), "rev-parse",
                    f"{remote_head}^", cwd=sandbox).stdout.strip()
                archived_report = json.loads(git(
                    "--git-dir", str(origin), "show",
                    f"{archived_sha}:{runner.GIT_RESULT}",
                    cwd=sandbox).stdout)
                self.assertEqual(archived_report, delayed)
                self.assertEqual(git(
                    "--git-dir", str(origin), "rev-parse",
                    f"{archived_sha}^", cwd=sandbox
                ).stdout.strip(), peer_report_sha)
                self.assertEqual(
                    git("--git-dir", str(origin), "show", "-s",
                        "--format=%s", remote_head,
                        cwd=sandbox).stdout.strip(),
                    f"test: latest run for {source_sha[:12]} "
                    "[skip ci]")
                self.assertIn(
                    "swapz-canonical-restore: true",
                    git("--git-dir", str(origin), "show", "-s",
                        "--format=%b", remote_head,
                        cwd=sandbox).stdout)
                self.assertEqual(
                    git("rev-parse", "HEAD", cwd=checkout).stdout.strip(),
                    source_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report


    def test_git_sync_declines_older_source_when_newer_evidence_published(self):
        """Do not overwrite origin/main when it already carries newer qualification evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v1 source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "newer tester", cwd=peer)
            git("config", "user.email", "tester@example.invalid", cwd=peer)
            (peer / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Newer source C2", cwd=peer)
            c2_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()

            newer_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c2_sha,
                "tested_commit_sha": c2_sha,
                "overall": "PASS",
            }
            (peer / runner.GIT_RESULT).write_text(
                json.dumps(newer_report) + "\n", encoding="utf-8")
            git("add", runner.GIT_RESULT, cwd=peer)
            git("commit", "-m", f"test: latest run for {c2_sha[:12]} [skip ci]",
                cwd=peer)
            peer_report_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()
            # Populate the private bare remote without host pre-push hooks.
            # The publisher's own push behavior is exercised separately.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(peer), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    older_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c1_sha,
                        "tested_commit_sha": c1_sha,
                        "overall": "FAIL",
                    }
                    runner.write_report(older_report)
                    notice = runner.publish(c1_sha)
                    self.assertEqual(
                        notice,
                        f"SKIPPED_GIT_SYNC: newer-source qualification evidence "
                        f"already published ({c2_sha[:12]})")

                    remote_head = git("--git-dir", str(origin), "rev-parse",
                                      "refs/heads/main",
                                      cwd=sandbox).stdout.strip()
                    self.assertEqual(remote_head, peer_report_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_fails_closed_when_merge_base_errors(self):
        """Fail closed when git merge-base encounters an error checking remote evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-error-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v1 source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "newer tester", cwd=peer)
            git("config", "user.email", "tester@example.invalid", cwd=peer)
            (peer / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=peer)
            git("commit", "-m", "Newer source C2", cwd=peer)
            c2_sha = git("rev-parse", "HEAD", cwd=peer).stdout.strip()

            newer_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c2_sha,
                "tested_commit_sha": c2_sha,
                "overall": "PASS",
            }
            (peer / runner.GIT_RESULT).write_text(
                json.dumps(newer_report) + "\n", encoding="utf-8")
            git("add", runner.GIT_RESULT, cwd=peer)
            git("commit", "-m", f"test: latest run for {c2_sha[:12]} [skip ci]",
                cwd=peer)
            # Populate the private bare remote without host pre-push hooks.
            # The publisher's own push behavior is exercised separately.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(peer), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                if len(command) == 4 and command[:2] == ["merge-base", "--is-ancestor"] and command[3] == c2_sha:
                    return subprocess.CompletedProcess(
                        command, 128,
                        stdout=b"",
                        stderr=b"fatal: simulated git merge-base error")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    older_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c1_sha,
                        "tested_commit_sha": c1_sha,
                        "overall": "FAIL",
                    }
                    runner.write_report(older_report)
                    notice = runner.publish(c1_sha)
                    self.assertEqual(
                        notice,
                        "GIT_SYNC_FAILED: git merge-base failed while "
                        "evaluating remote qualification evidence")
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_allows_newer_source_over_older_evidence(self):
        """Allow publishing newer qualification evidence over older published evidence."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-monotonic-newer-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin, peer = (
                sandbox / "checkout", sandbox / "origin.git", sandbox / "peer")
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("v0 source\n")
            git("add", "source.c", cwd=checkout)
            git("commit", "-m", "Base source C0", cwd=checkout)
            c0_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

            (checkout / "source.c").write_text("v1 source\n")
            older_report = {
                "schema": "swapz-test-results-v1",
                "source_sha": c0_sha,
                "tested_commit_sha": c0_sha,
                "overall": "PASS",
            }
            (checkout / runner.GIT_RESULT).write_text(
                json.dumps(older_report) + "\n", encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Older source C1 with old report", cwd=checkout)
            c1_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            # Checkout advances to C2 (tested commit)
            (checkout / "source.c").write_text("v2 source\n")
            git("add", "source.c", cwd=checkout)
            git("commit", "-m", "Newer source C2", cwd=checkout)
            c2_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            # Peer clones and adds a concurrent docs commit C3 on top of C2
            git("clone", "-b", "main", str(origin), str(peer), cwd=sandbox)
            git("config", "user.name", "concurrent committer", cwd=peer)
            git("config", "user.email", "committer@example.invalid", cwd=peer)
            (peer / "README.md").write_text("concurrent doc\n")
            git("add", "README.md", cwd=peer)
            git("commit", "-m", "Concurrent doc commit C3", cwd=peer)
            # Populate the private bare remote without host pre-push hooks.
            # The publisher's own push behavior is exercised separately.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(peer), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    newer_report = {
                        "schema": "swapz-test-results-v1",
                        "source_sha": c2_sha,
                        "tested_commit_sha": c2_sha,
                        "overall": "FAIL",
                    }
                    runner.write_report(newer_report)
                    notice = runner.publish(c2_sha)
                    self.assertIn("SYNCED_GIT", notice)

                    remote_report = json.loads(
                        git("--git-dir", str(origin), "show",
                            f"refs/heads/main:{runner.GIT_RESULT}",
                            cwd=sandbox).stdout)
                    self.assertEqual(remote_report["tested_commit_sha"], c2_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_retries_transient_push_and_fetch_failure(self):
        """Retry transient publication failures even when main did not move."""
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-retry-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin = sandbox / "checkout", sandbox / "origin.git"
            checkout.mkdir()
            git("init", "--object-format=sha1", "--bare", str(origin), cwd=sandbox)
            git("init", "--object-format=sha1", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("source\n")
            (checkout / runner.GIT_RESULT).write_text(
                '{"overall":"NOT_RUN"}\n', encoding="utf-8")
            git("add", "source.c", runner.GIT_RESULT, cwd=checkout)
            git("commit", "-m", "Tested source", cwd=checkout)
            source_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            # Seed the local bare remote without invoking host pre-push hooks.
            git("--git-dir", str(origin), "fetch", "--no-tags",
                str(checkout), "main:refs/heads/main", cwd=sandbox)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / runner.GIT_RESULT
            failures = {"push": 3, "fetch": 2}

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                if command[:2] == ["push", "origin"] and failures["push"]:
                    failures["push"] -= 1
                    return subprocess.CompletedProcess(
                        command, 1, stdout=b"", stderr=b"transient push")
                if command[:3] == ["fetch", "--no-tags", "origin"] and \
                        failures["fetch"]:
                    failures["fetch"] -= 1
                    return subprocess.CompletedProcess(
                        command, 1, stdout=b"", stderr=b"transient fetch")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                result = {
                    "schema": "swapz-test-results-v1",
                    "source_sha": source_sha,
                    "tested_commit_sha": source_sha,
                    "overall": "FAIL",
                }
                runner.write_report(result)
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept), \
                     mock.patch.object(
                         runner, "_publication_retry_sleep") as sleep:
                    notice = runner.publish(source_sha)
                self.assertIn("SYNCED_GIT", notice)
                self.assertEqual(failures, {"push": 0, "fetch": 0})
                self.assertEqual(sleep.call_count, 5)
                self.assertEqual(runner.git_sha(), source_sha)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_publication_failure_causes_are_fixed_and_private(self):
        cases = (
            (b"Authentication failed for 'https://SECRET@github.com/'",
             "credentials_or_repository_access"),
            (b"fatal: Permission denied (publickey).",
             "credentials_or_repository_access"),
            (b"remote: GH006: Protected branch update failed for refs/heads/main",
             "remote_permission_or_policy"),
            (b"! [rejected] main -> main (non-fast-forward)",
             "remote_advanced"),
            (b"fatal: Could not resolve host: github.com",
             "network_or_transport"),
            (b"unknown SECRET Git failure", "git_command_failed"),
        )
        for stderr, reason in cases:
            with self.subTest(reason=reason):
                failure = subprocess.CompletedProcess(
                    ["push", "origin"], 1, b"", stderr)
                classified = runner.git_publication_failure_reason(failure)
                self.assertEqual(classified, reason)
                self.assertNotIn("SECRET", classified)
        self.assertEqual(
            runner.git_publication_failure_reason(None),
            "git_command_unavailable_or_timed_out")

    def test_git_cli_fallback_is_noninteractive_and_preserves_first_cause(self):
        commands = []
        cli_authenticated = True

        def git_run(*command, **kwargs):
            commands.append(command)
            success = command[0] == "-c" and cli_authenticated
            return subprocess.CompletedProcess(
                command, 0 if success else 1, b"",
                b"" if success else b"Authentication failed")

        result = runner.git_push_with_credential_fallback(
            git_run, "https://github.com/k1moradi/swapz.git", "a" * 40)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][:2], ("push", "origin"))
        self.assertEqual(commands[1][:2], ("-c", "credential.helper="))
        self.assertIn("credential.helper=!gh auth git-credential",
                      commands[1])
        cli_authenticated = False
        commands.clear()
        result = runner.git_push_with_credential_fallback(
            git_run, "https://github.com/k1moradi/swapz.git", "a" * 40)
        self.assertEqual(
            runner.git_publication_failure_reason(result),
            "credentials_or_repository_access")
        self.assertEqual(len(commands), 2)
        commands.clear()
        runner.git_push_with_credential_fallback(
            git_run, "git@github.com:k1moradi/swapz.git", "a" * 40)
        self.assertEqual(len(commands), 1)

    def test_publisher_preserves_configured_git_credentials(self):
        source = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn('env["GIT_TERMINAL_PROMPT"] = "0"', source)
        self.assertNotIn('env["GIT_ASKPASS"] = "false"', source)
        self.assertNotIn('env["GCM_INTERACTIVE"] = "never"', source)
        self.assertNotIn('"ls-remote"', source)

    def test_git_sync_declines_invalid_source(self):
        with tempfile.TemporaryDirectory(
                prefix="publish-", dir=ROOT / "build/tests") as name:
            previous_root, previous_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                runner.write_report({"source_sha": "unknown",
                                     "overall": "BLOCKED"})
                self.assertIn("unavailable", runner.publish("unknown"))
            finally:
                runner.ROOT, runner.REPORT = previous_root, previous_report

    def test_git_sync_rejects_invalid_json_before_git_access(self):
        from unittest import mock

        source_sha = "a" * 40
        invalid_reports = (
            (b"{broken", "JSON report is unreadable"),
            (b"\xff", "JSON report is unreadable"),
            (b"[]", "does not match tested Git commit"),
            (b"null", "does not match tested Git commit"),
            (b'{"source_sha":"wrong"}', "does not match tested Git commit"),
        )
        with tempfile.TemporaryDirectory(
                prefix="publish-json-", dir=ROOT / "build/tests") as name:
            previous_root, previous_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                with mock.patch.object(runner, "git_result") as git:
                    for payload, reason in invalid_reports:
                        with self.subTest(payload=payload):
                            runner.REPORT.write_bytes(payload)
                            self.assertIn(reason, runner.publish(source_sha))
                    git.assert_not_called()
            finally:
                runner.ROOT, runner.REPORT = previous_root, previous_report



class QualificationReportEvidenceBoundaryTest(unittest.TestCase):
    """Rootless admission fixtures; no synthetic row represents loaded evidence."""

    SOURCE_SHA = "a" * 40
    KERNEL_RELEASE = "fixture-kernel"

    def passing_report(self):
        return {
            "schema": "swapz-test-results-v1",
            "source_sha": self.SOURCE_SHA,
            "tested_commit_sha": self.SOURCE_SHA,
            "kernel_release": self.KERNEL_RELEASE,
            "qualification": "RAM_BACKED_NULL_BLK_ONLY",
            "overall": "PASS",
            "stages": [
                {"name": name, "status": "PASS", "exit_code": 0}
                for name in runner.OFFICIAL_STAGE_NAMES
            ],
            "qualified_artifacts": {
                "status": "AVAILABLE",
                "formatter_sha256": "b" * 64,
                "module_sha256": "c" * 64,
                "oracle_sha256": "d" * 64,
            },
        }

    def package_report_gate(self, report=None, *, kernel_release=None,
                            raw_payload=None):
        """Execute only the actual package report-parser here-doc, not packaging."""
        import subprocess
        import sys

        source = (ROOT / "packaging/package-dkms.sh").read_text()
        marker = (
            'qualification_output="$(python3 - "$qualification_report" '
            '"$kernel_release" <<\'PY\'\n'
        )
        self.assertEqual(source.count(marker), 1)
        parser = source.split(marker, 1)[1].split("\nPY\n", 1)[0]
        if raw_payload is None:
            raw_payload = json.dumps(report)
        with tempfile.TemporaryDirectory(prefix="report-admission-") as name:
            report_path = Path(name) / "synthetic-report.json"
            report_path.write_text(raw_payload, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-c", parser, str(report_path),
                 kernel_release or self.KERNEL_RELEASE],
                capture_output=True, text=True, check=False, timeout=10)

    def test_official_stage_states_never_promote_unexecuted_work(self):
        completed = self.passing_report()["stages"]
        self.assertEqual(runner.qualification_overall(0, completed), "PASS")

        for outcome, executed, exit_code, expected in (
                ("stage_2_failed", completed[:1] + [
                    {**completed[1], "status": "FAIL", "exit_code": 1}],
                 1, "FAIL"),
                ("stage_5_blocked", completed[:4] + [
                    {**completed[4], "status": "BLOCKED", "exit_code": 2}],
                 2, "BLOCKED"),
                ("aborted", completed[:1], 1, "FAIL"),
                ("incomplete", completed[:1], 0, "INCOMPLETE")):
            with self.subTest(outcome=outcome):
                observed = runner.qualification_overall(exit_code, executed)
                self.assertEqual(
                    observed, expected,
                    f"field=stages source={self.SOURCE_SHA} "
                    f"expected={expected} observed={observed}; "
                    "next=inspect the first recorded stage and rerun make test")
                # Missing stages have no recorded PASS; NOT_RUN is only a view.
                states = [stage["status"] for stage in executed] + [
                    "NOT_RUN"] * (len(completed) - len(executed))
                self.assertNotIn("PASS", states[len(executed):])
                self.assertEqual(len(states), len(runner.OFFICIAL_STAGE_NAMES))

        for status in ("NOT_RUN", "UNAVAILABLE", "BLOCKED", "FAIL"):
            with self.subTest(recorded_status=status):
                stages = [dict(stage) for stage in completed]
                stages[4]["status"] = status
                expected = ("FAIL" if status == "FAIL" else
                            "BLOCKED" if status == "BLOCKED" else
                            "INCOMPLETE")
                self.assertEqual(runner.qualification_overall(0, stages),
                                 expected)
        self.assertFalse(runner.owner_qualification_artifacts_available(
            {"status": "UNAVAILABLE"}))
        self.assertFalse(runner.required_benchmark_gates_pass({
            "verdicts": {"overall": "NOT_RUN"},
            "write_saturation": {"overall": "UNAVAILABLE"},
        }))

    def test_synthetic_report_admission_rejects_false_passes(self):
        import copy

        passing = self.passing_report()
        accepted = self.package_report_gate(passing)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertEqual(accepted.stdout.splitlines(), [
            self.SOURCE_SHA, "b" * 64, "c" * 64, "d" * 64])

        scenarios = (
            ("schema", "swapz-test-results-v1", "other-report-type",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report.update(schema="other-report-type")),
            ("stages[2].name", "Kernel warnings W=1",
             "Native and rootless contracts",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report["stages"][2].update(
                 name=report["stages"][1]["name"])),
            ("stages", "5-canonical-stages", "<dict>",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report.update(stages={})),
            ("tested_commit_sha", self.SOURCE_SHA, "e" * 40,
             "rerun-make-test-for-exact-clean-source",
             lambda report: report.update(tested_commit_sha="e" * 40)),
            ("source_sha", "40-lower-hex", "wrong",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report.update(source_sha="wrong")),
            ("kernel_release", self.KERNEL_RELEASE, "other-kernel",
             "rerun-make-test-on-running-kernel",
             lambda report: report.update(kernel_release="other-kernel")),
            ("stages[1].status", "PASS", "FAIL",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report["stages"][1].update(
                 status="FAIL", exit_code=1)),
            ("stages[4].status", "PASS", "BLOCKED",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report["stages"][4].update(
                 status="BLOCKED", exit_code=2)),
            ("stages[4].status", "PASS", "NOT_RUN",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report["stages"][4].update(status="NOT_RUN")),
            ("stages[4].status", "PASS", "UNAVAILABLE",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report["stages"][4].update(status="UNAVAILABLE")),
            ("stages", "5-canonical-stages", "2",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report["stages"].__delitem__(slice(2, None))),
            ("stages[0].exit_code", "integer-0", "false(bool)",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report["stages"][0].update(exit_code=False)),
            ("stages[0].exit_code", "integer-0", "<float>",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report["stages"][0].update(exit_code=0.0)),
            ("stages[0].exit_code", "integer-0", "<int>",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report["stages"][0].update(exit_code=10 ** 500)),
            ("qualified_artifacts.module_sha256",
             "64-lower-hex-sha256", "missing",
             "rerun-make-test-and-rebuild-qualified-artifacts",
             lambda report: report["qualified_artifacts"].pop(
                 "module_sha256")),
            ("qualified_artifacts.keys",
             "status+formatter_sha256+module_sha256+oracle_sha256",
             "noncanonical-fields",
             "rerun-make-test-and-rebuild-qualified-artifacts",
             lambda report: report["qualified_artifacts"].update(
                 unexpected="e" * 64)),
            ("qualified_artifacts.status", "AVAILABLE", "UNAVAILABLE",
             "rerun-make-test-and-rebuild-qualified-artifacts",
             lambda report: report["qualified_artifacts"].update(
                 status="UNAVAILABLE")),
            ("overall", "PASS", "FAIL",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report.update(overall="FAIL")),
            ("overall", "PASS", "BLOCKED",
             "inspect-first-non-PASS-stage-and-rerun-make-test",
             lambda report: report.update(overall="BLOCKED")),
            ("qualification", "RAM_BACKED_NULL_BLK_ONLY", "ROOTLESS_ONLY",
             "rerun-make-test-for-exact-clean-source",
             lambda report: report.update(qualification="ROOTLESS_ONLY")),
        )
        for field, expected, observed, next_step, mutate in scenarios:
            with self.subTest(field=field, observed=observed):
                report = copy.deepcopy(passing)
                mutate(report)
                if field == "overall":
                    # Populated, well-formed hashes do not promote a failed run.
                    self.assertTrue(
                        runner.owner_qualification_artifacts_available(
                            report["qualified_artifacts"]))
                outcome = self.package_report_gate(report)
                diagnostic = outcome.stderr.strip()
                message = (
                    f"field={field} tested_source={self.SOURCE_SHA} "
                    f"expected=BLOCKED observed={report.get('overall')}; "
                    "next=inspect the invalid report field and rerun make test")
                self.assertNotEqual(outcome.returncode, 0, message)
                self.assertIn(f"field={field}", diagnostic, message)
                self.assertIn("source_sha=", diagnostic, message)
                self.assertIn("tested_commit_sha=", diagnostic, message)
                self.assertIn(f"expected={expected}", diagnostic, message)
                self.assertIn(f"observed={observed}", diagnostic, message)
                self.assertIn(f"next={next_step}", diagnostic, message)
                for private_prefix in ("/home/", "/tmp/", "/var/", "/mnt/"):
                    self.assertNotIn(private_prefix, diagnostic, message)

        # Runner and package admission both reject non-canonical artifact
        # identity rather than treating the presence of three digests as enough.
        for field in ("formatter_sha256", "module_sha256", "oracle_sha256"):
            with self.subTest(missing_digest=field):
                hashes = copy.deepcopy(passing["qualified_artifacts"])
                hashes.pop(field)
                self.assertFalse(
                    runner.owner_qualification_artifacts_available(hashes))
        extra = copy.deepcopy(passing["qualified_artifacts"])
        extra["unqualified"] = "e" * 64
        self.assertFalse(runner.owner_qualification_artifacts_available(extra))

    def test_package_report_parser_sanitizes_unreadable_documents(self):
        for raw_payload in ("{broken", "9" * 5000):
            with self.subTest(payload_length=len(raw_payload)):
                outcome = self.package_report_gate(raw_payload=raw_payload)
                diagnostic = outcome.stderr.strip()
                self.assertNotEqual(outcome.returncode, 0)
                self.assertIn("field=document", diagnostic)
                self.assertIn("source_sha=unavailable", diagnostic)
                self.assertIn("tested_commit_sha=unavailable", diagnostic)
                self.assertIn("expected=UTF-8-JSON-object", diagnostic)
                self.assertIn("observed=unreadable", diagnostic)
                self.assertIn(
                    "next=rerun-make-test-for-exact-clean-source", diagnostic)
                self.assertNotIn("Traceback", diagnostic)
                for private_prefix in ("/home/", "/tmp/", "/var/", "/mnt/"):
                    self.assertNotIn(private_prefix, diagnostic)

    def test_publisher_rejects_stale_or_divergent_report_before_git(self):
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="report-provenance-") as name:
            old_root, old_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                with mock.patch.object(runner, "git_result") as git:
                    for field in ("source_sha", "tested_commit_sha"):
                        with self.subTest(field=field):
                            report = self.passing_report()
                            report[field] = "e" * 40
                            runner.write_report(report)
                            observed = runner.publish(self.SOURCE_SHA)
                            self.assertIn(
                                "report does not match tested Git commit",
                                observed,
                                f"field={field} tested_source={self.SOURCE_SHA} "
                                f"expected=SKIPPED observed={observed}; "
                                "next=rerun make test for the exact source")
                    git.assert_not_called()
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_pass_publication_requires_actual_source_artifact_and_host_binding(self):
        """Synthetic PASS rows cannot become official Git evidence."""
        import copy
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix="publish-binding-") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / runner.GIT_RESULT
                header = runner.ROOT / "build/source-build-info.h"
                header.parent.mkdir()
                expected_header = (
                    f'#define SWAPZ_BUILD_SOURCE_SHA "{self.SOURCE_SHA}"\n'
                    '#define SWAPZ_BUILD_SOURCE_CLEAN 1\n'
                    '#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n')
                header.write_text(expected_header, encoding="ascii")
                identity = {
                    "schema": "swapz-host-v1",
                    "architecture": runner.os.uname().machine,
                    "id_sha256": "f" * 64,
                }
                baseline = self.passing_report()
                baseline["kernel_release"] = runner.os.uname().release
                baseline["host_identity"] = identity

                scenarios = (
                    ("missing_stage", "incomplete_or_failed_stages",
                     lambda report: report["stages"].pop()),
                    ("failed_stage", "incomplete_or_failed_stages",
                     lambda report: report["stages"][1].update(
                         status="FAIL", exit_code=7)),
                    ("contradictory_exit", "incomplete_or_failed_stages",
                     lambda report: report["stages"][1].update(exit_code=1)),
                    ("missing_hash", "unavailable_artifact_digests",
                     lambda report: report["qualified_artifacts"].pop(
                         "module_sha256")),
                    ("wrong_hash", "artifact_digest_mismatch_or_unavailable",
                     lambda report: report["qualified_artifacts"].update(
                         module_sha256="e" * 64)),
                    ("other_host", "host_identity_mismatch_or_unavailable",
                     lambda report: report["host_identity"].update(
                         id_sha256="e" * 64)),
                    ("malformed_host", "host_identity_mismatch_or_unavailable",
                     lambda report: report["host_identity"].update(
                         id_sha256="NOT-A-DIGEST")),
                    ("wrong_kernel", "kernel_release_mismatch",
                     lambda report: report.update(kernel_release="other-kernel")),
                )
                with mock.patch.object(
                        runner, "report_host_identity", return_value=identity), \
                     mock.patch.object(
                         runner, "qualification_artifact_digests",
                         return_value=baseline["qualified_artifacts"]), \
                     mock.patch.object(runner, "git_result") as git:
                    runner.write_report(baseline)
                    # Valid in-memory fixture reaches checkout admission,
                    # which is unavailable in this isolated directory.
                    self.assertIn(
                        "not an authenticated Git checkout",
                        runner.publish(self.SOURCE_SHA))
                    self.assertTrue(git.called)

                    for label, reason, mutate in scenarios:
                        with self.subTest(case=label):
                            report = copy.deepcopy(baseline)
                            mutate(report)
                            runner.write_report(report)
                            git.reset_mock()
                            self.assertEqual(
                                runner.publish(self.SOURCE_SHA),
                                "SKIPPED_GIT_SYNC: phase=report-admission "
                                f"reason={reason}")
                            git.assert_not_called()

                    runner.write_report(baseline)
                    header.write_text(expected_header.replace(
                        "SWAPZ_BUILD_SOURCE_CLEAN 1",
                        "SWAPZ_BUILD_SOURCE_CLEAN 0"), encoding="ascii")
                    git.reset_mock()
                    self.assertEqual(
                        runner.publish(self.SOURCE_SHA),
                        "SKIPPED_GIT_SYNC: phase=report-admission "
                        "reason=build_provenance_mismatch")
                    git.assert_not_called()
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_qualified_artifact_digest_guard_checks_actual_bytes(self):
        """Execute the package hash gate against isolated artifact bytes."""
        import os
        import subprocess

        source = (ROOT / "packaging/package-dkms.sh").read_text()
        start = source.find("\nhash_file() {")
        end = source.find("\nquery_dkms_status() {", start)
        self.assertGreaterEqual(start, 0, "missing package hash helper")
        self.assertGreater(end, start, "missing package hash guard boundary")
        helpers = source[start:end]
        script = (
            "set -Eeuo pipefail\n" + helpers + "\n"
            'report_qualified_digest "$1" "$2" "$3" qualified_report\n')

        for artifact_name in (
                "qualified_swapzctl", "qualified_dm-swapz.ko",
                "qualified_roundtrip_oracle"):
            with self.subTest(artifact=artifact_name):
                with tempfile.TemporaryDirectory(
                        prefix="report-artifact-") as name:
                    artifact = Path(name) / "artifact"
                    artifact.write_bytes(b"qualified-final-artifact")
                    expected_hash = hashlib.sha256(
                        artifact.read_bytes()).hexdigest()

                    def check():
                        return subprocess.run(
                            ["bash", "-c", script, "bash", artifact_name,
                             expected_hash, str(artifact)],
                            env=os.environ.copy(), capture_output=True,
                            text=True, check=False, timeout=5)

                    accepted = check()
                    self.assertEqual(accepted.returncode, 0, accepted.stderr)
                    self.assertEqual(accepted.stderr, "")

                    artifact.write_bytes(b"stale-or-rebuilt-artifact")
                    changed = check()
                    self.assertEqual(changed.returncode, 1)
                    diagnostic = changed.stderr.strip()
                    self.assertIn(
                        f"artifact={artifact_name} check=sha256 "
                        "provenance=qualified_report", diagnostic)
                    self.assertIn(f"expected_sha256={expected_hash}", diagnostic)
                    self.assertIn(
                        "observed_sha256=" + hashlib.sha256(
                            artifact.read_bytes()).hexdigest(), diagnostic)
                    self.assertIn(
                        "next=inspect_qualification_and_artifact_bytes_read_only "
                        "retained_state=unchanged", diagnostic)
                    self.assertNotIn(str(artifact), diagnostic)

                    artifact.unlink()
                    missing = check()
                    self.assertEqual(missing.returncode, 1)
                    self.assertIn("observed_sha256=missing_or_unsafe",
                                  missing.stderr)
                    self.assertNotIn(str(artifact), missing.stderr)

    def test_kernel_header_source_clean_guard_rejects_mismatched_identity(self):
        """Execute the production guard and its diagnostics, not a fake exit."""
        import os
        import subprocess

        source = (ROOT / "packaging/package-dkms.sh").read_text()
        admission_start = source.find("qualification_output=")
        self.assertGreaterEqual(
            admission_start, 0, "missing package qualification admission")
        guard_start = source.find(
            '\nbuild_source_sha="$(sed -n ', admission_start)
        guard_end = source.find(
            '\nif [[ -z "$test_root" ]]; then', guard_start)
        self.assertGreaterEqual(
            guard_start, 0, "missing executable build identity extraction")
        self.assertGreater(
            guard_end, guard_start, "missing executable build guard boundary")
        # Preserve the real printf/blocked branch. Only replace blocked()'s
        # privileged orchestration with the same exit classification.
        script = (
            "set -Eeuo pipefail\n"
            'blocked() { printf "BLOCKED: %s\\n" "$*" >&2; exit 2; }\n'
            + source[guard_start:guard_end] + "\n")

        for header_sha, clean_bit, expected_source, expected_clean in (
                (self.SOURCE_SHA, "1", None, None),
                ("e" * 40, "1", "e" * 40, "1"),
                (self.SOURCE_SHA, "0", self.SOURCE_SHA, "0"),
                ("A" * 40, "1", "unavailable", "1"),
                (self.SOURCE_SHA, "2", self.SOURCE_SHA, "unavailable"),
                (None, None, "unavailable", "unavailable")):
            with self.subTest(header_sha=header_sha, clean_bit=clean_bit):
                with tempfile.TemporaryDirectory(
                        prefix="report-build-header-") as name:
                    build_info = Path(name) / "source-build-info.h"
                    header_lines = []
                    if header_sha is not None:
                        header_lines.append(
                            f'#define SWAPZ_BUILD_SOURCE_SHA "{header_sha}"')
                    if clean_bit is not None:
                        header_lines.append(
                            f"#define SWAPZ_BUILD_SOURCE_CLEAN {clean_bit}")
                    build_info.write_text(
                        "\n".join(header_lines) + "\n", encoding="utf-8")
                    environment = {
                        **os.environ,
                        "build_info": str(build_info),
                        "qualified_source_sha": self.SOURCE_SHA,
                    }
                    outcome = subprocess.run(
                        ["bash", "-c", script], env=environment,
                        capture_output=True, text=True, check=False, timeout=5)
                if expected_source is None:
                    self.assertEqual(outcome.returncode, 0, outcome.stderr)
                    self.assertEqual(outcome.stderr, "")
                    continue

                diagnostic = outcome.stderr.strip()
                self.assertEqual(
                    outcome.returncode, 2,
                    f"field=build/source-build-info.h source={self.SOURCE_SHA} "
                    f"expected=BLOCKED observed=exit-{outcome.returncode}; "
                    "next=rebuild exact clean qualified artifacts")
                self.assertIn(
                    "artifact=qualified_kernel_build_info "
                    "check=source_provenance", diagnostic)
                self.assertIn(
                    f"expected_source_sha={self.SOURCE_SHA}", diagnostic)
                self.assertIn(
                    f"observed_source_sha={expected_source}", diagnostic)
                self.assertIn("expected_clean=1", diagnostic)
                self.assertIn(
                    f"observed_clean={expected_clean}", diagnostic)
                self.assertIn(
                    "next=inspect_qualification_and_build_info_read_only "
                    "retained_state=unchanged", diagnostic)
                self.assertIn(
                    "BLOCKED: build provenance does not match the "
                    "qualified clean source", diagnostic)
                self.assertNotIn(str(build_info), diagnostic)

    def test_private_first_failure_survives_later_error_without_public_paths(self):
        import stat
        import subprocess

        source = (ROOT / "tests/tools/test-rootless.sh").read_text()
        start = source.index("begin_rootless_private_stderr_capture() {")
        end = source.index("\nreport_rootless_failure() {", start)
        capture_functions = source[start:end]
        fixture_script = (
            "set -Eeuo pipefail\n"
            'ROOT="$1"\n'
            "rootless_phase='tests/runtime/native/package-dkms-test.py'\n"
            "rootless_capture_directory=\nrootless_capture_path=\n"
            "rootless_capture_input_fd=2\nrootless_capture_pid=\n"
            "rootless_private_diagnostic_path=\n"
            "rootless_private_diagnostic_log=\n"
            "rootless_classified_reason=nonzero_exit\n"
            "rootless_classified_subtest=unavailable\n"
            + capture_functions + "\n"
            "begin_rootless_private_stderr_capture\n"
            "printf '%s\\n' "
            "\"FAIL: test_first (__main__.PackageLifecycle.test_first) "
            "(phase='first-check')\" "
            "'AssertionError: first checkpoint' "
            "'======================================================================' "
            "\"ERROR: test_second (__main__.PackageLifecycle.test_second) "
            "(phase='second-check')\" "
            "'subprocess.TimeoutExpired: later checkpoint' "
            ">&\"$rootless_capture_input_fd\"\n"
            "finish_rootless_private_stderr_capture 1\n"
            'classify_rootless_private_unittest_failure '
            '"$rootless_private_diagnostic_path"\n'
            'printf "reason=%s subtest=%s\\n" '
            '"$rootless_classified_reason" "$rootless_classified_subtest"\n'
        )
        with tempfile.TemporaryDirectory(prefix="report-first-failure-") as name:
            root = Path(name)
            process = subprocess.run(
                ["bash", "-c", fixture_script, "bash", str(root)],
                capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(
                process.stdout.strip(),
                "reason=unittest_assertion subtest=first-check")
            self.assertNotIn(str(root), process.stdout)
            self.assertNotIn("second-check", process.stdout)
            logs = list((root / "build/tests").glob(
                "rootless-failure.*/diagnostic.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(stat.S_IMODE(logs[0].parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(logs[0].stat().st_mode), 0o600)
            self.assertIn("first checkpoint", logs[0].read_text())
            self.assertIn("later checkpoint", logs[0].read_text())



class ProductionReadinessEvidenceTest(unittest.TestCase):
    SOURCE_SHA = "a" * 40
    DIGEST = "b" * 64
    OBSERVED_AT = "2026-11-03T00:00:00Z"

    def passing_snapshot(self):
        common = {
            "status": "PASS", "current": True,
            "source_sha": self.SOURCE_SHA,
            "observed_at_utc": self.OBSERVED_AT,
        }
        hashes = {
            "formatter_sha256": self.DIGEST,
            "module_sha256": "c" * 64,
            "oracle_sha256": "d" * 64,
        }
        acceptance_manifest_sha256 = (
            runner.production_acceptance_manifest_sha256())
        self.assertIsNotNone(acceptance_manifest_sha256)
        target = {
            "partuuid": "f13428f6-01",
            "device_bytes": 124787884032,
        }
        evidence = {
            "production_source": dict(common),
            "clean_build_state": {**common, "clean": True},
            "qualified_artifact_hashes": {
                **common, "qualified": True, "hashes": dict(hashes)},
            "required_ci": {
                **common,
                "runs": [
                    {"workflow": workflow, "head_sha": self.SOURCE_SHA,
                     "result": "PASS", "status": "completed",
                     "conclusion": "success", "run_id": str(index + 1)}
                    for index, workflow in enumerate(
                        runner.PRODUCTION_READINESS_REQUIRED_CI)
                ],
            },
            "exact_source_owner_make_test": {
                **common, "overall": "PASS",
                "tested_source_sha": self.SOURCE_SHA,
                "report_sha256": self.DIGEST,
                "hashes": dict(hashes)},
            "owned_nullblk_qualification": {
                **common, "overall": "PASS",
                "evidence_sha256": self.DIGEST,
                "hashes": dict(hashes)},
            "unresolved_critical_issues": {
                **common, "count": 0, "issues": []},
            "authorized_target_identity": {
                **common, "authorized": True, "target": dict(target)},
            "real_linux_swap": {
                **common, "overall": "PASS", "swap_out_in": "PASS",
                "target": dict(target),
                "acceptance_manifest_sha256": acceptance_manifest_sha256,
                "qualified_installed_artifacts": dict(hashes),
                "physical_execution_control_sha256": "e" * 64,
                "installed_control_privileged_execution_enabled": False,
                "evidence_sha256": self.DIGEST},
            "maximum_capacity_and_ram": {
                **common, "overall": "PASS", "incompressible": "PASS",
                "target": dict(target),
                "logical_capacity_bytes": 4096, "peak_ram_bytes": 8192,
                "acceptance_manifest_sha256": acceptance_manifest_sha256,
                "evidence_sha256": self.DIGEST},
            "sustained_physical_performance": {
                **common, "overall": "PASS", "sustained": "PASS",
                "target": dict(target),
                "acceptance_manifest_sha256": acceptance_manifest_sha256,
                "evidence_sha256": self.DIGEST},
            "lifecycle_deployment_state": {
                **common, "overall": "PASS", "lifecycle": "PASS",
                "deployment": "PASS", "target": dict(target),
                "evidence_sha256": self.DIGEST},
            "installed_artifact_identity": {
                **common, "installed": True, "hashes": dict(hashes)},
            "cold_boot_harness": {
                **common, "armed": True, "target": dict(target),
                "evidence_sha256": self.DIGEST},
            "owner_observed_reboot": {
                **common, "observed": True, "overall": "PASS",
                "target": dict(target),
                "evidence_sha256": self.DIGEST},
        }
        return {
            "schema": runner.PRODUCTION_READINESS_SCHEMA,
            "snapshot_kind": "CURRENT",
            "release_evidence": evidence,
        }

    def test_summary_only_physical_evidence_cannot_pass_release(self):
        verdict = runner.evaluate_production_readiness(
            self.passing_snapshot(), self.SOURCE_SHA)
        for evidence_name in runner.PRODUCTION_READINESS_PERSISTENT_EVIDENCE:
            self.assertEqual(
                verdict["evidence_statuses"][evidence_name], "BLOCKED")
            self.assertIn(
                "canonical persistent-evidence evaluation",
                verdict["reasons"][evidence_name])
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(verdict["DEPLOYMENT_PRODUCTION_READY"], "PASS")
        self.assertEqual(
            verdict["PRODUCTION_READY_FOR_OWNER_REBOOT"], "BLOCKED")
        self.assertEqual(verdict["COLD_BOOT_HARNESS"], "PASS")
        self.assertEqual(verdict["COLD_BOOT_OBSERVED"], "PASS")
        self.assertEqual(verdict["release_verdict"], "BLOCKED")

    def test_missing_or_stale_required_evidence_never_passes(self):
        for name in runner.PRODUCTION_READINESS_REQUIRED_EVIDENCE:
            with self.subTest(missing=name):
                snapshot = self.passing_snapshot()
                del snapshot["release_evidence"][name]
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertNotEqual(verdict["release_verdict"], "PASS")
            with self.subTest(stale=name):
                snapshot = self.passing_snapshot()
                snapshot["release_evidence"][name]["current"] = False
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertNotEqual(verdict["release_verdict"], "PASS")

    def test_fail_and_in_progress_remain_distinct(self):
        # Summary-only PASS is intentionally BLOCKED for persistent physical
        # evidence. Put every persistent gate in a genuine in-progress state
        # first so this test isolates status precedence rather than accidentally
        # depending on unqualified synthetic PASS payloads.
        progressing = self.passing_snapshot()
        for evidence_name in runner.PRODUCTION_READINESS_PERSISTENT_EVIDENCE:
            progressing["release_evidence"][evidence_name]["status"] = (
                "IN_PROGRESS")

        verdict = runner.evaluate_production_readiness(
            progressing, self.SOURCE_SHA)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "IN_PROGRESS")
        self.assertEqual(verdict["release_verdict"], "IN_PROGRESS")

        failed = self.passing_snapshot()
        for evidence_name in runner.PRODUCTION_READINESS_PERSISTENT_EVIDENCE:
            failed["release_evidence"][evidence_name]["status"] = "IN_PROGRESS"
        failed["release_evidence"]["real_linux_swap"]["status"] = "FAIL"
        verdict = runner.evaluate_production_readiness(failed, self.SOURCE_SHA)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "FAIL")
        self.assertEqual(verdict["release_verdict"], "FAIL")

    def test_unresolved_critical_issues_block_code_readiness(self):
        snapshot = self.passing_snapshot()
        snapshot["release_evidence"]["unresolved_critical_issues"]["count"] = 1
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["unresolved_critical_issues"],
            "BLOCKED")
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED")
        self.assertEqual(verdict["release_verdict"], "BLOCKED")

    def test_zero_critical_count_requires_empty_issue_list(self):
        snapshot = self.passing_snapshot()
        critical = snapshot["release_evidence"]["unresolved_critical_issues"]
        critical["issues"] = ["publication race"]
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["unresolved_critical_issues"],
            "BLOCKED")
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_pass_requires_qualified_hashes_and_current_ci(self):
        missing_hash = self.passing_snapshot()
        del missing_hash["release_evidence"]["qualified_artifact_hashes"][
            "hashes"]["module_sha256"]
        verdict = runner.evaluate_production_readiness(
            missing_hash, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["qualified_artifact_hashes"],
            "BLOCKED")

        stale_ci = self.passing_snapshot()
        stale_ci["release_evidence"]["required_ci"]["runs"][0][
            "head_sha"] = "e" * 40
        verdict = runner.evaluate_production_readiness(
            stale_ci, self.SOURCE_SHA)
        self.assertEqual(verdict["evidence_statuses"]["required_ci"], "BLOCKED")

        missing_package_ci = self.passing_snapshot()
        missing_package_ci["release_evidence"]["required_ci"]["runs"] = [
            run for run in
            missing_package_ci["release_evidence"]["required_ci"]["runs"]
            if run["workflow"] != "Systemd and package production-readiness"
        ]
        verdict = runner.evaluate_production_readiness(
            missing_package_ci, self.SOURCE_SHA)
        self.assertEqual(verdict["evidence_statuses"]["required_ci"], "BLOCKED")

    def test_stale_ci_and_old_owner_report_cannot_qualify_new_build(self):
        old_source = "e" * 40

        # Old green CI is not current-source evidence even when every recorded
        # workflow otherwise has the exact canonical completed-success shape.
        stale_ci = self.passing_snapshot()
        for run in stale_ci["release_evidence"]["required_ci"]["runs"]:
            run["head_sha"] = old_source
        verdict = runner.evaluate_production_readiness(
            stale_ci, self.SOURCE_SHA)
        message = (
            f"gate=required_ci expected_source={self.SOURCE_SHA} "
            f"observed_source={old_source}; "
            "next=run required CI for the exact current source")
        self.assertEqual(
            verdict["evidence_statuses"]["required_ci"], "BLOCKED", message)
        self.assertNotEqual(verdict["release_verdict"], "PASS", message)

        # A current release-evidence wrapper cannot relabel a saved owner
        # make-test result from an older source as current qualification.
        relabeled_owner = self.passing_snapshot()
        owner = relabeled_owner["release_evidence"]["exact_source_owner_make_test"]
        self.assertEqual(owner["source_sha"], self.SOURCE_SHA)
        self.assertTrue(runner._readiness_artifact_hashes_valid(owner["hashes"]))
        owner["tested_source_sha"] = old_source
        verdict = runner.evaluate_production_readiness(
            relabeled_owner, self.SOURCE_SHA)
        message = (
            f"gate=exact_source_owner_make_test "
            f"wrapper_source={self.SOURCE_SHA} tested_source={old_source}; "
            "next=reject relabeled stale owner evidence and rerun make test")
        self.assertEqual(
            verdict["evidence_statuses"]["exact_source_owner_make_test"],
            "BLOCKED", message)
        self.assertEqual(
            verdict["reasons"]["exact_source_owner_make_test"],
            "PASS payload is incomplete or unqualified", message)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED", message)
        self.assertNotEqual(verdict["release_verdict"], "PASS", message)

        # Model an actually stale owner result: both the evidence record and
        # the make-test payload identify the prior source.
        stale_owner = self.passing_snapshot()
        owner = stale_owner["release_evidence"]["exact_source_owner_make_test"]
        owner["source_sha"] = old_source
        owner["tested_source_sha"] = old_source
        verdict = runner.evaluate_production_readiness(
            stale_owner, self.SOURCE_SHA)
        message = (
            f"gate=exact_source_owner_make_test "
            f"expected_source={self.SOURCE_SHA} observed_source={old_source}; "
            "next=recapture owner make test on the exact current source")
        self.assertEqual(
            verdict["evidence_statuses"]["exact_source_owner_make_test"],
            "BLOCKED", message)
        self.assertEqual(
            verdict["reasons"]["exact_source_owner_make_test"],
            "evidence is historical or source-unbound", message)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED", message)
        self.assertNotEqual(verdict["release_verdict"], "PASS", message)

    def test_failed_owner_report_with_populated_hashes_stays_failed(self):
        # A false PASS wrapper must not hide the inner make-test FAIL merely
        # because all three qualified artifact hashes are populated and valid.
        false_pass = self.passing_snapshot()
        owner = false_pass["release_evidence"]["exact_source_owner_make_test"]
        self.assertTrue(runner._readiness_artifact_hashes_valid(
            owner["hashes"]))
        owner["overall"] = "FAIL"
        verdict = runner.evaluate_production_readiness(
            false_pass, self.SOURCE_SHA)
        message = (
            "gate=exact_source_owner_make_test expected_overall=PASS "
            "observed_overall=FAIL; next=inspect the first failed make-test "
            "stage and recapture owner qualification")
        self.assertEqual(
            verdict["evidence_statuses"]["exact_source_owner_make_test"],
            "BLOCKED", message)
        self.assertEqual(
            verdict["reasons"]["exact_source_owner_make_test"],
            "PASS payload is incomplete or unqualified", message)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED", message)
        self.assertNotEqual(verdict["release_verdict"], "PASS", message)

        # When the evidence status itself records the current failure, preserve
        # FAIL rather than weakening the first failed gate into BLOCKED.
        explicit_fail = self.passing_snapshot()
        owner = explicit_fail["release_evidence"]["exact_source_owner_make_test"]
        owner["overall"] = "FAIL"
        owner["status"] = "FAIL"
        verdict = runner.evaluate_production_readiness(
            explicit_fail, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["exact_source_owner_make_test"],
            "FAIL", message)
        self.assertEqual(verdict["CODE_PRODUCTION_READY"], "FAIL", message)
        self.assertEqual(verdict["release_verdict"], "FAIL", message)

    def test_required_ci_requires_completed_success_and_concrete_run_id(self):
        for field, value in (
                ("status", "queued"),
                ("status", "in_progress"),
                ("status", "cancelled"),
                ("status", "skipped"),
                ("status", "failure"),
                ("status", None),
                ("conclusion", "cancelled"),
                ("conclusion", "failure"),
                ("conclusion", "skipped"),
                ("conclusion", "neutral"),
                ("conclusion", "timed_out"),
                ("conclusion", None),
                ("result", "FAIL"),
                ("result", "BLOCKED"),
                ("result", "NOT_RUN"),
                ("head_sha", "e" * 40),
                ("head_sha", None),
                ("run_id", False),
                ("run_id", 0),
                ("run_id", -1),
                ("run_id", "0"),
                ("run_id", "01"),
                ("run_id", "١"),
                ("run_id", "0" * 5000),
                ("run_id", "9" * 5000),
                ("run_id", 1 << 63),
                ("run_id", "9223372036854775808"),
                ("run_id", "not-a-run-id")):
            with self.subTest(field=field, value=value):
                snapshot = self.passing_snapshot()
                snapshot["release_evidence"]["required_ci"]["runs"][0][
                    field] = value
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertEqual(
                    verdict["evidence_statuses"]["required_ci"], "BLOCKED")
                self.assertEqual(
                    verdict["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_required_ci_rejects_duplicate_run_ids_and_extra_rows(self):
        for mutation in ("shared_run_id", "extra_workflow", "malformed_row",
                         "duplicate_workflow", "missing_workflow"):
            with self.subTest(mutation=mutation):
                snapshot = self.passing_snapshot()
                runs = snapshot["release_evidence"]["required_ci"]["runs"]
                if mutation == "shared_run_id":
                    # int and canonical decimal text denote the same Actions run.
                    runs[1]["run_id"] = 1
                elif mutation == "extra_workflow":
                    runs.append({
                        "workflow": "Optional unrelated workflow",
                        "head_sha": self.SOURCE_SHA, "result": "PASS",
                        "status": "completed", "conclusion": "success",
                        "run_id": "4",
                    })
                elif mutation == "duplicate_workflow":
                    # A duplicate green row cannot replace a missing workflow.
                    runs[1] = dict(runs[0])
                    runs[1]["run_id"] = "8"
                elif mutation == "missing_workflow":
                    runs.pop(1)
                else:
                    runs.append(None)
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertEqual(
                    verdict["evidence_statuses"]["required_ci"], "BLOCKED")
                self.assertEqual(verdict["CODE_PRODUCTION_READY"], "BLOCKED")

    def test_qualified_artifact_hashes_reject_extra_fields(self):
        snapshot = self.passing_snapshot()
        snapshot["release_evidence"]["qualified_artifact_hashes"]["hashes"][
            "unverified_sha256"] = self.DIGEST
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["qualified_artifact_hashes"],
            "BLOCKED")

    def test_release_hashes_are_cross_bound(self):
        owner_mismatch = self.passing_snapshot()
        owner_mismatch["release_evidence"]["exact_source_owner_make_test"][
            "hashes"]["module_sha256"] = "e" * 64
        verdict = runner.evaluate_production_readiness(
            owner_mismatch, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["exact_source_owner_make_test"],
            "BLOCKED")

        nullblk_private_formatter = self.passing_snapshot()
        nullblk_private_formatter["release_evidence"][
            "owned_nullblk_qualification"]["hashes"]["formatter_sha256"] = (
                "e" * 64)
        verdict = runner.evaluate_production_readiness(
            nullblk_private_formatter, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["owned_nullblk_qualification"],
            "PASS")

        nullblk_module_mismatch = self.passing_snapshot()
        nullblk_module_mismatch["release_evidence"][
            "owned_nullblk_qualification"]["hashes"]["module_sha256"] = (
                "e" * 64)
        verdict = runner.evaluate_production_readiness(
            nullblk_module_mismatch, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["owned_nullblk_qualification"],
            "BLOCKED")

        real_swap_mismatch = self.passing_snapshot()
        real_swap_mismatch["release_evidence"]["real_linux_swap"][
            "qualified_installed_artifacts"]["module_sha256"] = "e" * 64
        verdict = runner.evaluate_production_readiness(
            real_swap_mismatch, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["real_linux_swap"], "BLOCKED")

        missing_execution_control = self.passing_snapshot()
        del missing_execution_control["release_evidence"]["real_linux_swap"][
            "physical_execution_control_sha256"]
        verdict = runner.evaluate_production_readiness(
            missing_execution_control, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["real_linux_swap"], "BLOCKED")

        aliased_execution_control = self.passing_snapshot()
        aliased_execution_control["release_evidence"]["real_linux_swap"][
            "physical_execution_control_sha256"] = (
                aliased_execution_control["release_evidence"][
                    "real_linux_swap"]["qualified_installed_artifacts"][
                        "formatter_sha256"])
        verdict = runner.evaluate_production_readiness(
            aliased_execution_control, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["real_linux_swap"], "BLOCKED")

        armed_installed_control = self.passing_snapshot()
        armed_installed_control["release_evidence"]["real_linux_swap"][
            "installed_control_privileged_execution_enabled"] = True
        verdict = runner.evaluate_production_readiness(
            armed_installed_control, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["real_linux_swap"], "BLOCKED")

        installed_mismatch = self.passing_snapshot()
        installed_mismatch["release_evidence"]["installed_artifact_identity"][
            "hashes"]["oracle_sha256"] = "e" * 64
        verdict = runner.evaluate_production_readiness(
            installed_mismatch, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["installed_artifact_identity"],
            "BLOCKED")

    def test_release_acceptance_manifest_is_canonical_and_duplicate_free(self):
        previous_root = runner.ROOT
        try:
            with tempfile.TemporaryDirectory() as directory:
                runner.ROOT = Path(directory)
                docs = runner.ROOT / "docs"
                docs.mkdir()
                manifest_path = docs / "production-acceptance.json"

                valid = {
                    "schema": "swapz-production-acceptance-v1",
                    "status": "FROZEN",
                    "primary_real_swap": {},
                    "physical_qualification": {
                        "schema": "swapz-performance-qualification-v1",
                        "prospective": True,
                    },
                }
                payload = (
                    json.dumps(valid, sort_keys=True, separators=(",", ":")) +
                    "\n").encode()
                manifest_path.write_bytes(payload)
                self.assertEqual(
                    runner.production_acceptance_manifest_sha256(),
                    hashlib.sha256(payload).hexdigest())

                manifest_path.write_text(
                    '{"schema":"swapz-production-acceptance-v1",'
                    '"status":"FROZEN","status":"FROZEN",'
                    '"primary_real_swap":{},'
                    '"physical_qualification":{'
                    '"schema":"swapz-performance-qualification-v1",'
                    '"prospective":true}}',
                    encoding="utf-8")
                self.assertIsNone(
                    runner.production_acceptance_manifest_sha256())

                invalid = dict(valid)
                invalid["unexpected"] = True
                manifest_path.write_text(
                    json.dumps(invalid), encoding="utf-8")
                self.assertIsNone(
                    runner.production_acceptance_manifest_sha256())

                invalid = dict(valid)
                invalid["physical_qualification"] = {
                    "schema": "wrong", "prospective": True}
                manifest_path.write_text(
                    json.dumps(invalid), encoding="utf-8")
                self.assertIsNone(
                    runner.production_acceptance_manifest_sha256())
        finally:
            runner.ROOT = previous_root

    def test_physical_passes_bind_frozen_acceptance_manifest(self):
        for evidence_name in (
                "real_linux_swap", "maximum_capacity_and_ram",
                "sustained_physical_performance"):
            with self.subTest(evidence=evidence_name):
                snapshot = self.passing_snapshot()
                snapshot["release_evidence"][evidence_name][
                    "acceptance_manifest_sha256"] = "e" * 64
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertEqual(
                    verdict["evidence_statuses"][evidence_name], "BLOCKED")
                self.assertNotEqual(verdict["release_verdict"], "PASS")

    def test_authorized_target_identity_is_required_and_cross_bound(self):
        malformed = self.passing_snapshot()
        malformed["release_evidence"]["authorized_target_identity"]["target"][
            "partuuid"] = "F13428F6-01"
        verdict = runner.evaluate_production_readiness(
            malformed, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["authorized_target_identity"],
            "BLOCKED")

        weak = self.passing_snapshot()
        weak["release_evidence"]["authorized_target_identity"]["target"][
            "partuuid"] = "a-b-c-d-e"
        verdict = runner.evaluate_production_readiness(weak, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["authorized_target_identity"],
            "BLOCKED")

        for evidence_name in (
                "real_linux_swap", "maximum_capacity_and_ram",
                "sustained_physical_performance",
                "lifecycle_deployment_state", "cold_boot_harness",
                "owner_observed_reboot"):
            with self.subTest(evidence=evidence_name):
                snapshot = self.passing_snapshot()
                snapshot["release_evidence"][evidence_name]["target"] = {
                    "partuuid": "9abc8def-02",
                    "device_bytes": 124787884032,
                }
                verdict = runner.evaluate_production_readiness(
                    snapshot, self.SOURCE_SHA)
                self.assertEqual(
                    verdict["evidence_statuses"][evidence_name], "BLOCKED")
                self.assertNotEqual(verdict["release_verdict"], "PASS")

    def test_authorized_target_accepts_partial_page_device_tail(self):
        # BLKGETSIZE64 identity is byte-exact; only geometry floors to 4KiB.
        device_bytes = 124787884032 + 4095
        target = {"partuuid": "f13428f6-01", "device_bytes": device_bytes}
        self.assertEqual(
            runner._readiness_target_key(target),
            (target["partuuid"], device_bytes))
        for invalid_bytes in (0, 4096, 4097, 8191, -1, True, 8192.0):
            with self.subTest(invalid_bytes=invalid_bytes):
                self.assertIsNone(runner._readiness_target_key({
                    **target, "device_bytes": invalid_bytes}))

        snapshot = self.passing_snapshot()
        evidence = snapshot["release_evidence"]
        names = (
            "authorized_target_identity", "real_linux_swap",
            "maximum_capacity_and_ram", "sustained_physical_performance",
            "lifecycle_deployment_state", "cold_boot_harness",
            "owner_observed_reboot",
        )
        for name in names:
            evidence[name]["target"]["device_bytes"] = device_bytes
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["authorized_target_identity"], "PASS")
        self.assertEqual(verdict["DEPLOYMENT_PRODUCTION_READY"], "PASS")

        # Exact identity still rejects a one-byte mismatch between witnesses.
        evidence["lifecycle_deployment_state"]["target"]["device_bytes"] -= 1
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["evidence_statuses"]["lifecycle_deployment_state"],
            "BLOCKED")

    def test_ready_for_owner_reboot_does_not_forge_reboot_observation(self):
        snapshot = self.passing_snapshot()
        reboot = snapshot["release_evidence"]["owner_observed_reboot"]
        reboot.update({"status": "BLOCKED", "observed": False})
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(
            verdict["PRODUCTION_READY_FOR_OWNER_REBOOT"], "BLOCKED")
        self.assertEqual(verdict["COLD_BOOT_OBSERVED"], "BLOCKED")
        self.assertEqual(verdict["release_verdict"], "BLOCKED")

    def test_historical_snapshot_is_never_current_release_evidence(self):
        snapshot = self.passing_snapshot()
        snapshot["snapshot_kind"] = "HISTORICAL"
        verdict = runner.evaluate_production_readiness(
            snapshot, self.SOURCE_SHA)
        self.assertEqual(verdict["release_verdict"], "BLOCKED")

    def test_committed_handoff_snapshot_is_historical_and_blocked(self):
        snapshot = json.loads(
            (ROOT / "docs/handoff/production-readiness.json").read_text(
                encoding="utf-8"))
        self.assertEqual(snapshot["snapshot_kind"], "HISTORICAL")
        verdict = runner.evaluate_production_readiness(
            snapshot, runner.git_sha())
        self.assertEqual(verdict["release_verdict"], "BLOCKED")
        self.assertNotEqual(verdict["CODE_PRODUCTION_READY"], "PASS")
        self.assertNotEqual(verdict["DEPLOYMENT_PRODUCTION_READY"], "PASS")


class OptimizationPhase5ValidationContract(unittest.TestCase):
    """Hermetic three-host comparison; no Git, make, swap, or physical I/O."""

    BASELINE_SOURCE = "1" * 40
    CANDIDATE_SOURCE = "2" * 40
    HOSTS = (("x86_64-v2", "x86_64", "a" * 64),
             ("x86_64-v4", "x86_64", "b" * 64),
             ("aarch64", "aarch64", "c" * 64))

    @classmethod
    def setUpClass(cls):
        validation_spec = importlib.util.spec_from_file_location(
            "swapz_optimization_validation",
            ROOT / "tests/tools/validate-optimization.py")
        cls.validation = importlib.util.module_from_spec(validation_spec)
        validation_spec.loader.exec_module(cls.validation)

    def make_report(self, source, architecture, host_id, total_seconds):
        stages = []
        for index, name in enumerate(self.validation.STAGE_NAMES):
            stage = {"name": name, "status": "PASS", "exit_code": 0,
                     "elapsed_s": total_seconds / 5}
            if index == 1:
                stage["phase_elapsed_s"] = [
                    {"name": f"rootless-{i}", "elapsed_s": 0}
                    for i in range(52)]
                stage["primary_lifecycle_case_timing_coverage"] = {
                    "status": "COMPLETE", "expected_cases": 50,
                    "accepted_cases": 50, "observed_records": 50}
                stage["primary_lifecycle_case_elapsed_ms"] = [
                    {"class": "LifecycleTest", "method": f"test_{i}",
                     "elapsed_ms": 1} for i in range(50)]
            if index == 4:
                stage["phase_elapsed_s"] = [
                    {"name": f"loaded-{i}", "elapsed_s": 0}
                    for i in range(25)]
            stages.append(stage)
        pairs = [
            {"pair_index": index, "phase_elapsed_ms": [
                {"phase": phase, "elapsed_ms": index + 1}
                for phase in self.validation.PAIR_PHASES]}
            for index in range(89)]
        sample = {
            "status": "PASS", "source_sha": source,
            "regime": "ssd_emulated", "order": "off-first",
            "fixture_sha256": "d" * 64, "trace_sha256": "e" * 64,
            "device_model": {"hw_queue_depth": 1},
            "arms": {"off": {
                "source_sha": source, "mixed_replay_peak_rss_kb": 128,
                "host_cpu": {"status": "AVAILABLE", "busy_fraction": 0.3,
                             "pressure_some_fraction": 0.01}}},
        }
        return {
            "schema": self.validation.REPORT_SCHEMA,
            "kernel_release": "6.9.1", "tested_commit_sha": source,
            "source_sha": source, "overall": "INCOMPLETE",
            "qualification": "RAM_BACKED_NULL_BLK_ONLY",
            "host_identity": {"schema": "swapz-host-v1",
                              "architecture": architecture,
                              "id_sha256": host_id},
            "stages": stages,
            "qualified_artifacts": {"status": "AVAILABLE"},
            "benchmarks": {
                "loaded_correctness": {"overall": "PASS",
                                       "id36_memory_peak_bytes": 1000},
                "verdicts": {"overall": "PASS_BOUNDED_RAM_MATRIX"},
                "write_saturation": {
                    "overall": "PASS_WRITE_SATURATION_EVIDENCE"},
                "owned_pair_timing_coverage": {
                    "status": "COLLECTED", "complete_pairs": 89,
                    "observed_records": 445},
                "owned_pair_phase_timings": pairs,
                "sessions": [sample],
                "storage_envelope_sessions": [sample],
                "write_saturation_sessions": [sample],
            },
        }

    def create_manifest(self, directory, *, repeats=5, savings=10,
                        mutate_candidate=None):
        manifest = {
            "schema": self.validation.MANIFEST_SCHEMA,
            "baseline_sha": self.BASELINE_SOURCE,
            "candidate_sha": self.CANDIDATE_SOURCE,
            "hosts": [],
        }
        for profile, architecture, host_id in self.HOSTS:
            host = {"profile": profile, "host_id_sha256": host_id,
                    "pairs": []}
            for index in range(repeats):
                entry = {}
                for arm, source, seconds in (
                        ("baseline", self.BASELINE_SOURCE, 100 + index),
                        ("candidate", self.CANDIDATE_SOURCE,
                         100 + index - savings)):
                    report = self.make_report(
                        source, architecture, host_id, seconds)
                    if (mutate_candidate and profile == "x86_64-v2"
                            and index == 0 and arm == "candidate"):
                        mutate_candidate(report)
                    name = f"{profile}-{index}-{arm}.json"
                    (directory / name).write_text(json.dumps(report))
                    entry[arm] = name
                host["pairs"].append(entry)
            manifest["hosts"].append(host)
        path = directory / "manifest.json"
        path.write_text(json.dumps(manifest))
        return path

    def test_five_pair_reduction_is_a_signal_not_physical_pass(self):
        with tempfile.TemporaryDirectory() as directory_name:
            path = self.create_manifest(Path(directory_name))
            result = self.validation.compare(path)
            self.assertEqual(result["status"], "CONSISTENT_REDUCTION_SIGNAL")
            self.assertEqual(result["hosts"][0]["one_sided_sign_p"], 1 / 32)
            self.assertEqual(result["hosts"][0]["paired_median_saved_s"], 10)
            self.assertIn("NOT_FULL_MAKE_TEST", result["scope"])

    def test_insufficient_repeats_and_regression_remain_unqualified(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.assertEqual(
                self.validation.compare(self.create_manifest(
                    directory, repeats=3))["status"], "INSUFFICIENT_REPEATS")
            self.assertEqual(
                self.validation.compare(self.create_manifest(
                    directory, savings=-1))["status"],
                "REDUCTION_NOT_DEMONSTRATED")

    def test_source_host_coverage_scope_and_failure_mismatches_reject(self):
        def changes(report):
            return (
                lambda: report.__setitem__("tested_commit_sha", "3" * 40),
                lambda: report["host_identity"].__setitem__(
                    "id_sha256", "f" * 64),
                lambda: report["benchmarks"]["owned_pair_phase_timings"].pop(),
                lambda: report["benchmarks"]["sessions"][0].__setitem__(
                    "fixture_sha256", "f" * 64),
                lambda: report.__setitem__("overall", "FAIL"),
                lambda: report["stages"][4].__setitem__("status", "FAIL"),
            )
        for mutation_index in range(6):
            with self.subTest(case=mutation_index), \
                    tempfile.TemporaryDirectory() as directory_name:
                def mutate(report):
                    changes(report)[mutation_index]()
                path = self.create_manifest(
                    Path(directory_name), mutate_candidate=mutate)
                with self.assertRaises(self.validation.InvalidEvidence):
                    self.validation.compare(path)

    def test_gnu_time_sidecars_are_paired_and_invalid_values_rejected(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            manifest_path = self.create_manifest(directory)
            manifest = json.loads(manifest_path.read_text())
            # The sidecar records optional whole-make wall/CPU/RSS values.
            sample = (
                "User time (seconds): 24.5\n"
                "System time (seconds): 6.2\n"
                "Elapsed (wall clock) time (h:mm:ss or m:ss): 1:04.50\n"
                "Maximum resident set size (kbytes): 17232\n"
                "Exit status: 2\n")
            for host in manifest["hosts"]:
                for index, pair in enumerate(host["pairs"]):
                    for arm in ("baseline", "candidate"):
                        name = f"{host['profile']}-{index}-{arm}.time"
                        (directory / name).write_text(sample)
                        pair[f"{arm}_time"] = name
            manifest_path.write_text(json.dumps(manifest))
            result = self.validation.compare(manifest_path)
            self.assertEqual(result["hosts"][0]
                             ["whole_make_test_gnu_time"]["wall_s"]
                             ["baseline_median"], 64.5)
            broken = directory / manifest["hosts"][0]["pairs"][0]["baseline_time"]
            broken.write_text(sample.replace("17232", "not-a-number"))
            with self.assertRaises(self.validation.InvalidEvidence):
                self.validation.compare(manifest_path)

    def test_exact_paired_sign_probability_and_ties(self):
        self.assertEqual(self.validation.one_sided_sign_probability(
            [0, 0]), 1.0)
        self.assertEqual(self.validation.one_sided_sign_probability(
            [1] * 5), 1 / 32)




if __name__ == "__main__":
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    unittest.main()
