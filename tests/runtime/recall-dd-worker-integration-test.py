#!/usr/bin/env python3
"""Rootless execution tests for pinned direct-dd recall workers.

Only privately owned temporary regular files are used.  The mapper verifier is
intentionally replaced for this test; no DM/loop/NBD device is opened or
modified.  This does not qualify production mapper identity or teardown.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    specification = importlib.util.spec_from_file_location(name, HERE / filename)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


policy_module = load_module("recall_dd_worker_integration_policy", "recall-dd-allowlist.py")
supervisor_module = load_module("recall_dd_worker_integration_supervisor", "test-child-supervisor.py")
RecallDDLaunchGate = policy_module.RecallDDLaunchGate
GatedPidfdSupervisor = supervisor_module.GatedPidfdSupervisor


class PinnedDDWorkerIntegrationTests(unittest.TestCase):
    """Execute the real allowlisted dd via retained pidfds, not a fake launcher."""

    def setUp(self) -> None:
        if not hasattr(os, "pidfd_open"):
            self.skipTest("Linux pidfd support is required")
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="swapz-recall-dd-rootless-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.fixture = self.base / "private-fixture"
        self.fixture.mkdir(mode=0o700)
        self.source = self.fixture / "pages.bin"
        self.expected = bytes(range(256)) * (9 * 4096 // 256)
        self.source.write_bytes(self.expected)
        self.source.chmod(0o600)
        self.synthetic_mapper = self.base / "synthetic-mapper-regular-file"
        self.synthetic_mapper.write_bytes(bytes(len(self.expected)))
        self.synthetic_mapper.chmod(0o600)
        self.mapper_name = "swapz-v22-recall-rootless-worker"
        mapper_fd = os.open(self.synthetic_mapper, os.O_RDWR | os.O_CLOEXEC)
        def verify_synthetic_mapper(descriptor, name, file_ops) -> bool:
            descriptor_stat = file_ops.fstat(descriptor)
            return (name == self.mapper_name
                    and stat.S_ISREG(descriptor_stat.st_mode)
                    and descriptor_stat.st_size == len(self.expected))

        try:
            self.gate = RecallDDLaunchGate(
                self.fixture,
                self.mapper_name,
                mapper_fd=mapper_fd,
                executable_path=Path("/usr/bin/dd"),
                mapper_verifier=verify_synthetic_mapper,
            )
        finally:
            os.close(mapper_fd)
        self.addCleanup(self._close_gate)
        self.supervisor = GatedPidfdSupervisor(
            startup_timeout=2.0, term_grace=0.25, kill_grace=0.25, escalate=True
        )
        self.handles: list[str] = []
        self.addCleanup(self._stop_workers)

    def _launch_approved(self, approved) -> str:
        handle = self.supervisor.launch(
            approved.argv,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            executable=approved.executable,
            executable_fd=approved.executable_fd,
            pass_fds=approved.pass_fds,
            strict_fds=True,
        )
        self.handles.append(handle)
        return handle

    def _launch(self, role: str) -> str:
        return self._launch_approved(self.gate.admit(role))

    def _wait_success(self, handle: str) -> None:
        result = self.supervisor.wait(handle, 5.0)
        self.assertTrue(result.reaped, result.errors)
        self.assertEqual(result.exit_code, 0, result.errors)
        self.assertFalse(result.errors)

    def _stop_workers(self) -> None:
        # Never signal by numeric PID, even when a preceding assertion fails.
        report = self.supervisor.stop_all(tuple(self.handles))
        self.assertTrue(report.all_reaped, report.errors)
        self.assertFalse(report.errors)

    def _close_gate(self) -> None:
        self.assertEqual(self.gate.close(), ())

    def test_real_pinned_dd_writer_and_all_four_reader_roles(self) -> None:
        self._wait_success(self._launch("writer"))
        self.assertEqual(self.synthetic_mapper.read_bytes(), self.expected)

        self._wait_success(self._launch("a"))
        self._wait_success(self._launch("b"))
        # Preserve launch-before-wait ordering of the concurrent-read phase.
        reader_a = self._launch("a2")
        reader_b = self._launch("b2")
        self._wait_success(reader_a)
        self._wait_success(reader_b)
        for role, page in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
            with self.subTest(role=role):
                self.assertEqual(
                    (self.fixture / f"read-{role}").read_bytes(),
                    self.expected[page * 4096:(page + 1) * 4096],
                )
        self.assertEqual(self.gate.roles_issued, ("writer", "a", "b", "a2", "b2"))

    def test_source_path_replacement_cannot_redirect_admitted_writer(self) -> None:
        # The writer is admitted before the directory entry is replaced.
        approved = self.gate.admit("writer")
        archived_source = self.fixture / "pinned-original-pages"
        self.source.rename(archived_source)
        replacement = bytes((255 - value) for value in self.expected)
        self.source.write_bytes(replacement)
        self.source.chmod(0o600)
        self._wait_success(self._launch_approved(approved))
        self.assertEqual(self.synthetic_mapper.read_bytes(), self.expected)
        self.assertNotEqual(self.synthetic_mapper.read_bytes(), replacement)

    def test_output_path_replacement_cannot_redirect_admitted_reader(self) -> None:
        self._wait_success(self._launch("writer"))
        approved = self.gate.admit("a")
        original_output = self.fixture / "read-a"
        archived_output = self.fixture / "pinned-read-a"
        original_output.rename(archived_output)
        sentinel = b"replacement-must-not-be-touched"
        original_output.write_bytes(sentinel)
        original_output.chmod(0o600)
        self._wait_success(self._launch_approved(approved))
        self.assertEqual(archived_output.read_bytes(), self.expected[:4096])
        self.assertEqual(original_output.read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
