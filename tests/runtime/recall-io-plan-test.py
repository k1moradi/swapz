#!/usr/bin/env python3
"""Rootless direct recall plan tests: fake supervisor, private nine-page files.

Never launches dd, uses a device node, invokes dmsetup, or signals a PID.
"""

from __future__ import annotations

from dataclasses import dataclass
import ast
import importlib.util
from pathlib import Path
import random
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("recall_io_plan", HERE / "recall-io-plan.py")
assert SPEC is not None and SPEC.loader is not None
plan_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = plan_module
SPEC.loader.exec_module(plan_module)
RecallIOPlan = plan_module.RecallIOPlan
RecallPlanError = plan_module.RecallPlanError
PAGE_SIZE = plan_module.PAGE_SIZE
PAGE_COUNT = plan_module.PAGE_COUNT


@dataclass
class FakeResult:
    handle: str
    reaped: bool = True
    exit_code: int = 0
    errors: tuple[str, ...] = ()


@dataclass
class FakeReport:
    all_reaped: bool = True
    cleanup_allowed: bool = True


class FakeSupervisor:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.events: list[str] = []
        self.commands: dict[str, tuple[str, ...]] = {}
        self.counter = 0
        self.failed_launch: int | None = None
        self.failed_wait: str | None = None
        self.wait_nonzero: str | None = None
        self.wait_unreaped: str | None = None
        self.wait_wrong_handle: str | None = None
        self.return_duplicate = False
        self.corrupt_read = False
        self.report = FakeReport()
        self.raise_stop = False
        self.cleanup_handles: tuple[str, ...] | None = None

    def launch(self, argv: tuple[str, ...]) -> str:
        assert argv and argv[0] == "dd", argv
        assert not any(a.startswith("bash") or a.startswith("sh -c") for a in argv)
        self.counter += 1
        self.events.append(f"launch:{self.counter}")
        if self.failed_launch == self.counter:
            raise RuntimeError("injected launch failure")
        handle = "handle-1" if self.return_duplicate else f"handle-{self.counter}"
        self.commands[handle] = tuple(argv)
        return handle

    def wait(self, handle: str, timeout: float) -> FakeResult:
        assert timeout == 2.0
        self.events.append(f"wait:{handle}")
        if self.failed_wait == handle:
            raise TimeoutError("injected wait timeout")
        if self.wait_unreaped == handle:
            return FakeResult(handle, reaped=False)
        if self.wait_nonzero == handle:
            return FakeResult(handle, exit_code=7)
        if self.wait_wrong_handle == handle:
            return FakeResult("wrong-handle")
        argv = self.commands[handle]
        params = dict(arg.split("=", 1) for arg in argv[1:])
        if "skip" in params:
            assert params["if"] == "/dev/mapper/swapz-test-recall"
            page = int(params["skip"])
            result = self.source.read_bytes()[
                PAGE_SIZE * page: PAGE_SIZE * (page + 1)]
            if self.corrupt_read:
                result = bytes([result[0] ^ 1]) + result[1:]
            Path(params["of"]).write_bytes(result)
        return FakeResult(handle)

    def stop_all(self, handles: tuple[str, ...]) -> FakeReport:
        self.cleanup_handles = tuple(handles)
        self.events.append("stop_all")
        if self.raise_stop:
            raise RuntimeError("supervisor connection lost")
        return self.report


class RecallIOPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.source = self.directory / "pages.bin"
        rng = random.Random(0x5A7A2202)
        contents = bytearray()
        for page in range(PAGE_COUNT):
            random_half = bytes(rng.randrange(256) for _ in range(PAGE_SIZE // 2))
            repeat = bytes([(page * 17 + 3) & 255]) * (PAGE_SIZE // 2)
            contents += random_half + repeat
        self.source.write_bytes(contents)
        self.fake = FakeSupervisor(self.source)
        self.ticks = iter((i * 5_000_000 for i in range(100)))
        self.plan = RecallIOPlan(
            source=self.source, output_dir=self.directory,
            mapper="/dev/mapper/swapz-test-recall",
            supervisor=self.fake, clock_ns=lambda: next(self.ticks),
            wait_timeout=2.0,
        )

    def test_expected_page_is_exact_fixture_slice(self) -> None:
        expected, output = self.plan.prepare_expected(4, "b")
        self.assertEqual(expected.read_bytes(),
                         self.source.read_bytes()[4 * PAGE_SIZE:5 * PAGE_SIZE])
        self.assertFalse(output.exists())
        self.assertEqual(expected.stat().st_size, 4096)

    def test_writer_argv_is_direct_dd(self) -> None:
        handle = self.plan.launch_writer()
        self.assertEqual(self.fake.commands[handle], (
            "dd", f"if={self.source}", "of=/dev/mapper/swapz-test-recall",
            "bs=4096", "count=9", "oflag=direct", "conv=notrunc",
            "status=none",
        ))
        self.assertEqual(self.plan.handles, [handle])
        self.assertEqual(self.fake.events, ["launch:1"])

    def test_sequential_a_then_b_with_exact_page_comparison(self) -> None:
        first = self.plan.read_one(0, "a")
        second = self.plan.read_one(4, "b")
        self.assertEqual((first.page, second.page), (0, 4))
        self.assertEqual((first.elapsed_ns, second.elapsed_ns),
                         (5_000_000, 5_000_000))
        self.assertEqual(self.fake.events, [
            "launch:1", "wait:handle-1", "launch:2", "wait:handle-2",
        ])
        self.assertEqual(len(self.plan.handles), 2)

    def test_dual_launches_precede_any_wait(self) -> None:
        elapsed = self.plan.read_both((0, "a2"), (5, "b2"))
        self.assertEqual(elapsed, 5_000_000)
        self.assertEqual(self.fake.events, [
            "launch:1", "launch:2", "wait:handle-1", "wait:handle-2",
        ])
        self.assertEqual(len(self.plan.handles), 2)
        self.assertEqual((self.directory / "read-a2").read_bytes(),
                         (self.directory / "expected-a2").read_bytes())
        self.assertEqual((self.directory / "read-b2").read_bytes(),
                         (self.directory / "expected-b2").read_bytes())

    def test_writer_remains_active_through_buffer_reads(self) -> None:
        writer = self.plan.launch_writer()
        self.plan.read_one(0, "a")
        self.plan.read_one(4, "b")
        self.plan.read_both((0, "a2"), (5, "b2"))
        self.assertEqual(self.fake.events.count(f"wait:{writer}"), 0)
        self.plan.wait_writer()
        self.assertEqual(self.fake.events[-1], f"wait:{writer}")
        self.assertEqual(len(self.plan.handles), 5)

    def test_handle_kept_after_successful_wait(self) -> None:
        writer = self.plan.launch_writer()
        self.plan.wait_writer()
        self.assertEqual(self.plan.handles, [writer])

    def test_launch_error_denies_cleanup(self) -> None:
        self.fake.failed_launch = 1
        with self.assertRaisesRegex(RecallPlanError, "launch"):
            self.plan.read_one(0, "a")
        self.assertTrue(self.plan.failure)
        report, outcome = self.plan.cleanup_after_stop(lambda: "clean")
        self.assertIsNone(outcome)
        self.assertTrue(report.all_reaped)

    def test_second_dual_launch_failure_tracks_first_handle(self) -> None:
        self.fake.failed_launch = 2
        with self.assertRaisesRegex(RecallPlanError, "launch"):
            self.plan.read_both((0, "a2"), (5, "b2"))
        self.assertEqual(self.plan.handles, ["handle-1"])
        self.assertEqual(self.fake.events, ["launch:1", "launch:2"])
        self.plan.cleanup_after_stop(lambda: self.fail("must preserve backing"))
        self.assertEqual(self.fake.cleanup_handles, ("handle-1",))

    def test_first_wait_failure_still_checks_second_wait(self) -> None:
        self.fake.failed_wait = "handle-1"
        with self.assertRaisesRegex(RecallPlanError, "wait"):
            self.plan.read_both((0, "a2"), (5, "b2"))
        self.assertEqual(self.fake.events, [
            "launch:1", "launch:2", "wait:handle-1", "wait:handle-2",
        ])
        self.assertEqual(len(self.plan.handles), 2)

    def test_second_wait_failure_blocks_cleanup(self) -> None:
        self.fake.wait_nonzero = "handle-2"
        with self.assertRaisesRegex(RecallPlanError, "did not exit"):
            self.plan.read_both((0, "a2"), (5, "b2"))
        self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_unreaped_worker_blocks_cleanup(self) -> None:
        self.fake.wait_unreaped = "handle-1"
        with self.assertRaisesRegex(RecallPlanError, "did not exit"):
            self.plan.read_one(0, "a")
        self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_wrong_worker_handle_result_blocks_cleanup(self) -> None:
        self.fake.wait_wrong_handle = "handle-1"
        with self.assertRaisesRegex(RecallPlanError, "did not exit"):
            self.plan.read_one(0, "a")
        self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_corrupted_read_fails_comparison(self) -> None:
        self.fake.corrupt_read = True
        with self.assertRaisesRegex(RecallPlanError, "did not match"):
            self.plan.read_one(0, "a")
        self.assertTrue(self.plan.failure)
        self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_missing_output_detected_after_wait(self) -> None:
        def no_output(handle: str, timeout: float) -> FakeResult:
            self.fake.events.append(f"wait:{handle}")
            return FakeResult(handle)

        self.fake.wait = no_output
        with self.assertRaisesRegex(RecallPlanError, "cannot compare"):
            self.plan.read_one(0, "a")

    def test_duplicate_launch_handle_rejected(self) -> None:
        self.fake.return_duplicate = True
        self.plan.launch_writer()
        with self.assertRaisesRegex(RecallPlanError, "duplicate"):
            self.plan.read_one(0, "a")
        self.assertTrue(self.plan.failure)
        self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_cleanup_requires_all_reaped_report(self) -> None:
        self.plan.launch_writer()
        self.fake.report = FakeReport(all_reaped=False, cleanup_allowed=True)
        report, result = self.plan.cleanup_after_stop(
            lambda: self.fail("unsafe cleanup"))
        self.assertFalse(report.all_reaped)
        self.assertIsNone(result)

    def test_cleanup_denied_by_supervisor_errors(self) -> None:
        self.plan.launch_writer()
        self.fake.report = FakeReport(all_reaped=True, cleanup_allowed=False)
        report, result = self.plan.cleanup_after_stop(
            lambda: self.fail("unsafe cleanup"))
        self.assertFalse(report.cleanup_allowed)
        self.assertIsNone(result)

    def test_successful_cleanup_is_after_stop_all(self) -> None:
        self.plan.launch_writer()
        self.plan.read_both((0, "a2"), (5, "b2"))
        def checked_cleanup() -> str:
            self.assertEqual(self.fake.events[-1], "stop_all")
            self.assertEqual(self.fake.cleanup_handles,
                             ("handle-1", "handle-2", "handle-3"))
            return "clean"
        report, result = self.plan.cleanup_after_stop(checked_cleanup)
        self.assertTrue(report.cleanup_allowed)
        self.assertEqual(result, "clean")
        self.assertEqual(len(self.plan.handles), 3)

    def test_lost_supervisor_blocks_cleanup(self) -> None:
        self.plan.launch_writer()
        self.fake.raise_stop = True
        with self.assertRaisesRegex(RecallPlanError, "connection lost"):
            self.plan.cleanup_after_stop(lambda: self.fail("unsafe cleanup"))

    def test_after_cleanup_launches_are_denied(self) -> None:
        self.plan.cleanup_after_stop(lambda: "clean")
        with self.assertRaisesRegex(RecallPlanError, "closed"):
            self.plan.launch_writer()

    def test_invalid_page_and_label_cannot_escape_output_dir(self) -> None:
        for page, label in ((-1, "bad"), (PAGE_COUNT, "bad"), (0, "../unsafe"),
                            (0, "/tmp/out"), (0, ""), (True, "a")):
            with self.assertRaises(ValueError):
                self.plan.prepare_expected(page, label)

    def test_truncated_source_blocks_read(self) -> None:
        self.source.write_bytes(b"x" * 8000)
        with self.assertRaisesRegex(RecallPlanError, "truncated"):
            self.plan.prepare_expected(4, "a")
        self.assertTrue(self.plan.failure)

    def test_negative_clock_delta_fails(self) -> None:
        self.plan.clock_ns = iter([10, 1]).__next__
        with self.assertRaisesRegex(RecallPlanError, "non-monotonic"):
            self.plan.read_one(0, "a")

    def test_invalid_wait_timeout_rejected(self) -> None:
        for bad in (float("inf"), float("nan"), 0, -1):
            with self.assertRaises(ValueError):
                RecallIOPlan(source=self.source, output_dir=self.directory,
                             mapper="/dev/mapper/swapz-test-recall",
                             supervisor=self.fake, wait_timeout=bad)

    def test_plan_has_no_numeric_pid_or_process_spawn(self) -> None:
        source = (HERE / "recall-io-plan.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(alias.name == "subprocess" for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "subprocess")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    self.assertNotIn(
                        node.func.attr,
                        ("fork", "kill", "system", "Popen", "run", "call", "execv",
                         "execvp", "execvpe", "posix_spawn", "spawn"),
                    )
                self.assertFalse(any(
                    keyword.arg == "shell" and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True for keyword in node.keywords
                ))
        fixture = (HERE / "buffer-recall.sh").read_text()
        self.assertIn("swapz_test_stop_children_then_cleanup_stack", fixture)


if __name__ == "__main__":
    unittest.main()
