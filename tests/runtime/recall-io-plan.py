#!/usr/bin/env python3
"""Fixture-neutral V2.2 recall I/O plan; never opens a mapper or starts workers.

The injected supervisor must own *direct* dd children by opaque handles.
Production recall integration is separate: buffer-recall.sh remains unchanged.
This module only prepares expected data, builds dd argv, orders launches/waits
and checks synthetic or supplied output files after confirmed worker reap.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import time
from typing import Callable, Protocol, Sequence


PAGE_SIZE = 4096
PAGE_COUNT = 9
_LABEL = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,40}\Z")


class RecallPlanError(RuntimeError):
    """A recall step failed; never infer cleanup permission from this error."""


class WorkerResultLike(Protocol):
    handle: str
    reaped: bool
    exit_code: int | None
    errors: Sequence[str]


class StopReportLike(Protocol):
    all_reaped: bool
    cleanup_allowed: bool


class RecallSupervisor(Protocol):
    def launch(self, argv: Sequence[str]) -> str: ...
    def wait(self, handle: str, timeout: float) -> WorkerResultLike: ...
    def stop_all(self, handles: Sequence[str]) -> StopReportLike: ...


@dataclass(frozen=True)
class ReadResult:
    label: str
    page: int
    handle: str
    elapsed_ns: int


class RecallIOPlan:
    """Direct-worker plan without background Bash wrappers or PID signaling.

    Every successfully returned opaque handle is retained, including after a
    successful wait. Any failed/ambiguous launch, wait, comparison or cleanup
    check denies the caller's cleanup callback. Teardown is a separate,
    explicit decision, not something a read method performs automatically.
    """

    def __init__(
        self,
        *,
        source: Path,
        output_dir: Path,
        mapper: str,
        supervisor: RecallSupervisor,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        wait_timeout: float = 10.0,
    ) -> None:
        if not math.isfinite(wait_timeout) or wait_timeout <= 0:
            raise ValueError("wait_timeout must be positive and finite")
        if not isinstance(mapper, str) or not mapper.startswith("/dev/mapper/"):
            raise ValueError("mapper must be an explicit /dev/mapper path")
        if not mapper.split("/")[-1] or "\x00" in mapper:
            raise ValueError("invalid mapper path")
        self.source = Path(source)
        self.output_dir = Path(output_dir)
        self.mapper = mapper
        self.supervisor = supervisor
        self.clock_ns = clock_ns
        self.wait_timeout = wait_timeout
        self.handles: list[str] = []
        self.failure = False
        self._closed = False
        self.writer_handle: str | None = None

    def _check_open(self) -> None:
        if self._closed or self.failure:
            raise RecallPlanError("recall plan admission is closed after a failure")

    def _launch_direct(self, argv: tuple[str, ...]) -> str:
        self._check_open()
        # Deliberately no shell=True, bash -c or background Bash functions.
        if not argv or argv[0] != "dd":
            self.failure = True
            raise RecallPlanError("recall worker must be a direct dd command")
        try:
            handle = self.supervisor.launch(argv)
        except Exception as exc:
            # A failed launch with no confirmed handle may have left a worker.
            self.failure = True
            possible = getattr(exc, "handle", None)
            if isinstance(possible, str) and possible and possible not in self.handles:
                self.handles.append(possible)
            raise RecallPlanError(f"supervisor launch was not confirmed: {exc}") from exc
        if (not isinstance(handle, str) or not handle or handle.isdecimal()
                or handle in self.handles):
            self.failure = True
            raise RecallPlanError("supervisor returned an invalid or duplicate handle")
        self.handles.append(handle)
        return handle

    def _wait_success(self, handle: str) -> None:
        try:
            result = self.supervisor.wait(handle, timeout=self.wait_timeout)
        except Exception as exc:
            self.failure = True
            raise RecallPlanError(f"supervisor wait failed: {exc}") from exc
        if (getattr(result, "handle", None) != handle
                or getattr(result, "reaped", None) is not True
                or getattr(result, "exit_code", None) != 0
                or getattr(result, "errors", ())):
            self.failure = True
            raise RecallPlanError(f"direct worker {handle} did not exit and reap cleanly")

    def launch_writer(self) -> str:
        """Nine-page direct writer; wait only at the original recall checkpoint."""
        self._check_open()
        if self.writer_handle is not None:
            raise RecallPlanError("writer already started")
        argv = (
            "dd", f"if={self.source}", f"of={self.mapper}", "bs=4096",
            "count=9", "oflag=direct", "conv=notrunc", "status=none",
        )
        handle = self._launch_direct(argv)
        self.writer_handle = handle
        return handle

    def wait_writer(self) -> None:
        if self.writer_handle is None:
            raise RecallPlanError("writer was not started")
        self._wait_success(self.writer_handle)

    def prepare_expected(self, page: int, label: str) -> tuple[Path, Path]:
        self._check_open()
        if not isinstance(page, int) or isinstance(page, bool) or not 0 <= page < PAGE_COUNT:
            raise ValueError("page index must be one of the nine fixture pages")
        if not isinstance(label, str) or _LABEL.fullmatch(label) is None:
            raise ValueError("invalid recall output label")
        expected = self.output_dir / f"expected-{label}"
        output = self.output_dir / f"read-{label}"
        with self.source.open("rb") as f:
            f.seek(page * PAGE_SIZE)
            contents = f.read(PAGE_SIZE)
        if len(contents) != PAGE_SIZE:
            self.failure = True
            raise RecallPlanError("source page is truncated")
        if expected.exists() or output.exists():
            self.failure = True
            raise RecallPlanError("recall output/expected path already exists")
        expected.write_bytes(contents)
        return expected, output

    def _read_argv(self, page: int, output: Path) -> tuple[str, ...]:
        return (
            "dd", f"if={self.mapper}", f"of={output}", "bs=4096",
            f"skip={page}", "count=1", "iflag=direct", "status=none",
        )

    def _compare(self, expected: Path, output: Path) -> None:
        try:
            source_page = expected.read_bytes()
            result_page = output.read_bytes()
        except OSError as exc:
            self.failure = True
            raise RecallPlanError(f"cannot compare readback: {exc}") from exc
        if len(source_page) != PAGE_SIZE or result_page != source_page:
            self.failure = True
            raise RecallPlanError("direct read data did not match the expected 4096 bytes")

    def read_one(self, page: int, label: str) -> ReadResult:
        expected, output = self.prepare_expected(page, label)
        start = self.clock_ns()
        handle = self._launch_direct(self._read_argv(page, output))
        self._wait_success(handle)
        elapsed = self.clock_ns() - start
        if elapsed < 0:
            self.failure = True
            raise RecallPlanError("non-monotonic test clock")
        self._compare(expected, output)
        return ReadResult(label=label, page=page, handle=handle, elapsed_ns=elapsed)

    def read_both(self, first: tuple[int, str], second: tuple[int, str]) -> int:
        """Launch BOTH direct reads first, then wait both, then compare results.

        Even if one wait fails, attempt the other for diagnostic completeness.
        Keep every successful handle for later mandatory stop_all. No direct
        worker is created by a nested shell function or a cmp descendant.
        """
        self._check_open()
        first_paths = self.prepare_expected(*first)
        second_paths = self.prepare_expected(*second)
        start = self.clock_ns()
        first_handle = self._launch_direct(self._read_argv(first[0], first_paths[1]))
        second_handle = self._launch_direct(self._read_argv(second[0], second_paths[1]))
        failures: list[str] = []
        for handle in (first_handle, second_handle):
            try:
                self._wait_success(handle)
            except RecallPlanError as exc:
                failures.append(str(exc))
        elapsed = self.clock_ns() - start
        if failures:
            self.failure = True
            raise RecallPlanError("; ".join(failures))
        if elapsed < 0:
            self.failure = True
            raise RecallPlanError("non-monotonic test clock")
        # Both are reaped before synchronous comparison starts.
        self._compare(*first_paths)
        self._compare(*second_paths)
        return elapsed

    def cleanup_after_stop(self, callback: Callable[[], object]) -> tuple[StopReportLike, object | None]:
        """Never run the callback unless every known worker was safely reaped."""
        self._closed = True
        try:
            report = self.supervisor.stop_all(tuple(self.handles))
        except Exception as exc:
            self.failure = True
            raise RecallPlanError(f"cannot confirm stop/reap: {exc}") from exc
        if (self.failure or getattr(report, "cleanup_allowed", None) is not True
                or getattr(report, "all_reaped", None) is not True):
            return report, None
        return report, callback()
