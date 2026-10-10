#!/usr/bin/env python3
"""Rootless IPC control service for the gated pidfd supervisor prototype.

This is test infrastructure only.  The wire API accepts a small worker
allowlist and opaque handles; it never accepts a PID, argv, path, or shell
command from the controller.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import select
import socket
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_MODULE_PATH = Path(__file__).with_name("test-child-supervisor.py")
_SPEC = importlib.util.spec_from_file_location("swapz_gated_pidfd_supervisor", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("could not import gated pidfd supervisor")
_SUPERVISOR_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SUPERVISOR_MODULE
_SPEC.loader.exec_module(_SUPERVISOR_MODULE)

_ALLOWLIST_PATH = Path(__file__).with_name("recall-dd-allowlist.py")
_ALLOWLIST_SPEC = importlib.util.spec_from_file_location("swapz_recall_dd_allowlist", _ALLOWLIST_PATH)
if _ALLOWLIST_SPEC is None or _ALLOWLIST_SPEC.loader is None:
    raise RuntimeError("could not import recall dd launch policy")
_ALLOWLIST_MODULE = importlib.util.module_from_spec(_ALLOWLIST_SPEC)
sys.modules[_ALLOWLIST_SPEC.name] = _ALLOWLIST_MODULE
_ALLOWLIST_SPEC.loader.exec_module(_ALLOWLIST_MODULE)

GatedPidfdSupervisor = _SUPERVISOR_MODULE.GatedPidfdSupervisor
PidfdUnavailable = _SUPERVISOR_MODULE.PidfdUnavailable
StopReport = _SUPERVISOR_MODULE.StopReport
SupervisorError = _SUPERVISOR_MODULE.SupervisorError
WorkerResult = _SUPERVISOR_MODULE.WorkerResult
DDPolicyDenied = _ALLOWLIST_MODULE.DDPolicyDenied
PinnedDDLaunch = _ALLOWLIST_MODULE.PinnedDDLaunch
RecallDDLaunchGate = _ALLOWLIST_MODULE.RecallDDLaunchGate

MAX_FRAME_BYTES = 4096
MAX_WORKERS = 16
DEFAULT_IO_TIMEOUT = 10.0
DEFAULT_CLIENT_TIMEOUT = 75.0
MAX_WAIT_MS = 60_000
MAX_SLEEP_MS = 5_000
_HEADER = struct.Struct("!I")
_WORKER_CODE = {
    "sleep": "import sys,time; time.sleep(int(sys.argv[1])/1000)",
    "exit": "import sys; raise SystemExit(int(sys.argv[1]))",
}


class ProtocolError(Exception):
    """Malformed, incomplete, oversized, or timed-out protocol input."""

    def __init__(self, message: str, *, request_id: int | None = None) -> None:
        super().__init__(message)
        self.request_id = request_id


class ChannelFailure(Exception):
    """The controller cannot establish a trustworthy service response."""


class ProtocolFailure(ChannelFailure):
    """The peer returned a malformed or contradictory protocol response."""


class SupervisorUnavailable(ChannelFailure):
    """The service disconnected, timed out, or failed before a response."""


@dataclass(frozen=True)
class ServiceOutcome:
    exit_code: int
    status: str
    all_reaped: bool
    cleanup_allowed: bool = False


def _remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("control channel deadline expired")
    return value


def _recv_exact(sock: socket.socket, size: int, deadline: float, *, allow_clean_eof: bool = False) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        try:
            remaining = _remaining(deadline)
            readable, _, _ = select.select([sock], [], [], remaining)
        except TimeoutError as exc:
            raise ProtocolError("control channel read timed out") from exc
        except (OSError, ValueError) as exc:
            raise ProtocolError(f"socket read inspection failed: {exc}") from exc
        if not readable:
            raise ProtocolError("control channel read timed out")
        try:
            data = sock.recv(size - len(chunks))
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as exc:
            raise ProtocolError(f"control channel read failed: {exc}") from exc
        if not data:
            if allow_clean_eof and not chunks:
                return None
            raise ProtocolError("truncated control frame")
        chunks.extend(data)
    return bytes(chunks)


def _send_all(sock: socket.socket, data: bytes, deadline: float) -> None:
    view = memoryview(data)
    offset = 0
    while offset < len(view):
        try:
            remaining = _remaining(deadline)
            _, writable, _ = select.select([], [sock], [], remaining)
        except TimeoutError as exc:
            raise ProtocolError("control channel write timed out") from exc
        except (OSError, ValueError) as exc:
            raise ProtocolError(f"socket write inspection failed: {exc}") from exc
        if not writable:
            raise ProtocolError("control channel write timed out")
        try:
            count = sock.send(view[offset:])
        except (BlockingIOError, InterruptedError):
            continue
        except OSError as exc:
            raise ProtocolError(f"control channel write failed: {exc}") from exc
        if count <= 0:
            raise ProtocolError("control channel short write")
        offset += count


def encode_frame(message: dict[str, Any]) -> bytes:
    """Encode one bounded JSON message with a four-byte network length."""
    try:
        payload = json.dumps(message, separators=(",", ":"), sort_keys=True,
                             ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not JSON encodable: {exc}") from exc
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("message exceeds protocol frame limit")
    return _HEADER.pack(len(payload)) + payload


def send_frame(sock: socket.socket, message: dict[str, Any], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    _send_all(sock, encode_frame(message), deadline)


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def recv_frame(sock: socket.socket, timeout: float, *, allow_clean_eof: bool = False) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    header = _recv_exact(sock, _HEADER.size, deadline, allow_clean_eof=allow_clean_eof)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise ProtocolError("invalid control frame length")
    payload = _recv_exact(sock, length, deadline)
    assert payload is not None
    try:
        message = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys,
                             parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolError(f"invalid control JSON: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("control message must be a JSON object")
    return message


def _bounded_text(value: object, maximum: int = 256) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")[:maximum]


def _valid_opaque_handle(value: object) -> bool:
    return (isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value))
            and not value.isdecimal())


def _result_dict(result: WorkerResult) -> dict[str, Any]:
    safe_handle = result.handle if _valid_opaque_handle(result.handle) else None
    errors = [_bounded_text(item, 160) for item in result.errors[:4]]
    if safe_handle is None:
        errors.append("invalid supervisor handle withheld")
    return {
        "handle": safe_handle,
        "reaped": result.reaped,
        "exit_code": result.exit_code,
        "escalated": result.escalated,
        "errors": errors,
    }


class SupervisorControlService:
    """Single-threaded, fail-closed request loop around GatedPidfdSupervisor."""

    def __init__(
        self,
        *,
        supervisor: Any | None = None,
        io_timeout: float = DEFAULT_IO_TIMEOUT,
        recall_dd_gate: Any | None = None,
        enable_direct_dd: bool = False,
    ) -> None:
        if not math.isfinite(io_timeout) or io_timeout <= 0:
            raise ValueError("io_timeout must be finite and positive")
        if type(enable_direct_dd) is not bool:
            raise ValueError("enable_direct_dd must be an explicit boolean")
        if enable_direct_dd and recall_dd_gate is None:
            raise ValueError("direct dd requires a trusted bootstrap launch gate")
        if recall_dd_gate is not None and not all(
            callable(getattr(recall_dd_gate, name, None))
            for name in ("admit", "close_admission", "close")
        ):
            raise ValueError("recall dd gate does not implement the trusted launch API")
        if recall_dd_gate is not None and not enable_direct_dd:
            close_error: str | None = None
            try:
                recall_dd_gate.close_admission()
                errors = recall_dd_gate.close()
                if errors:
                    close_error = "; ".join(_bounded_text(item) for item in errors)
            except Exception as exc:
                close_error = _bounded_text(exc)
            suffix = f"; gate descriptor close failed: {close_error}" if close_error else ""
            raise ValueError("a recall dd gate requires explicit direct-dd enablement" + suffix)
        self.supervisor = supervisor if supervisor is not None else GatedPidfdSupervisor(
            startup_timeout=2.0, term_grace=0.25, kill_grace=0.25, escalate=True
        )
        self.io_timeout = io_timeout
        self.recall_dd_gate = recall_dd_gate
        self.enable_direct_dd = enable_direct_dd
        self._recall_dd_close_attempted = False
        self.handles: list[str] = []
        self._launch_attempts = 0
        self._last_request_id = 0
        self._admission_closed = False
        self._sticky_failure = False
        self._unconfirmed_launch = False
        self._shutdown = False
        self._stop_all_attempted = False
        self._last_stop_all_reaped = False
        self._last_stop_all_clean = False

    def _response(
        self,
        request_id: int | None,
        *,
        status: str,
        ok: bool = False,
        cleanup_allowed: bool = False,
        all_reaped: bool = False,
        **fields: Any,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "id": request_id,
            "ok": ok,
            "status": status,
            "all_reaped": all_reaped,
            "cleanup_allowed": cleanup_allowed,
            "preserve_backing": not cleanup_allowed,
        }
        response.update(fields)
        return response

    def _validate_common(self, request: object) -> tuple[int, str, dict[str, Any]]:
        if not isinstance(request, dict):
            raise ProtocolError("request must be an object")
        request_id = request.get("id")
        if (isinstance(request_id, bool) or not isinstance(request_id, int)
                or not 0 < request_id <= (2**63 - 1)):
            raise ProtocolError("id must be a positive signed 64-bit integer")
        if request_id <= self._last_request_id:
            raise ProtocolError("request id is duplicate or out of order", request_id=request_id)
        self._last_request_id = request_id
        operation = request.get("op")
        if not isinstance(operation, str):
            raise ProtocolError("op must be a string", request_id=request_id)
        return request_id, operation, request

    @staticmethod
    def _exact_keys(request: dict[str, Any], required: set[str]) -> None:
        if set(request) != required:
            raise ProtocolError("request fields do not match operation", request_id=request.get("id"))

    @staticmethod
    def _bounded_integer(value: object, low: int, high: int, name: str,
                         request_id: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ProtocolError(f"{name} must be an integer in range", request_id=request_id)
        return value

    def _launch(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        if self._admission_closed:
            self._sticky_failure = True
            return self._response(request_id, status="admission_closed", error="launch admission is closed")
        if self._launch_attempts >= MAX_WORKERS:
            raise ProtocolError("worker limit reached", request_id=request_id)
        command = request.get("command")
        launch_options: dict[str, Any] = {}
        if command == "sleep":
            self._exact_keys(request, {"id", "op", "command", "duration_ms"})
            duration_ms = self._bounded_integer(
                request.get("duration_ms"), 0, MAX_SLEEP_MS, "duration_ms", request_id
            )
            argv = (sys.executable, "-c", _WORKER_CODE["sleep"], str(duration_ms))
            launch_options = {"strict_fds": True, "contain_process_tree": True}
        elif command == "exit":
            self._exact_keys(request, {"id", "op", "command", "code"})
            code = self._bounded_integer(request.get("code"), 0, 125, "code", request_id)
            argv = (sys.executable, "-c", _WORKER_CODE["exit"], str(code))
            launch_options = {"strict_fds": True, "contain_process_tree": True}
        elif command == "recall-dd":
            self._exact_keys(request, {"id", "op", "command", "role"})
            if not self.enable_direct_dd or self.recall_dd_gate is None:
                raise ProtocolError("direct dd role launch is disabled in this service")
            role = request.get("role")
            try:
                launch = self.recall_dd_gate.admit(role)
            except DDPolicyDenied as exc:
                self._sticky_failure = True
                try:
                    self.recall_dd_gate.close_admission()
                except Exception:
                    self._sticky_failure = True
                return self._response(
                    request_id, status="launch_failure", error=_bounded_text(exc),
                    preserve_required=True,
                )
            except Exception as exc:
                self._sticky_failure = True
                self._unconfirmed_launch = True
                try:
                    self.recall_dd_gate.close_admission()
                except Exception:
                    self._sticky_failure = True
                return self._response(
                    request_id, status="launch_failure",
                    error=f"recall role admission failed: {_bounded_text(exc)}",
                    preserve_required=True,
                )
            if not isinstance(launch, PinnedDDLaunch):
                self._sticky_failure = True
                self._unconfirmed_launch = True
                self.recall_dd_gate.close_admission()
                return self._response(
                    request_id, status="supervisor_contract_failure",
                    error="recall role gate returned an invalid launch descriptor",
                    preserve_required=True,
                )
            argv = launch.argv
            launch_options = {
                "executable": launch.executable,
                "executable_fd": launch.executable_fd,
                "pass_fds": launch.pass_fds,
                "strict_fds": True,
                "contain_process_tree": True,
            }
        else:
            raise ProtocolError("command is not in the test worker allowlist", request_id=request_id)
        self._launch_attempts += 1
        try:
            handle = self.supervisor.launch(
                argv, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"}, **launch_options
            )
        except SupervisorError as exc:
            self._sticky_failure = True
            if command == "recall-dd":
                try:
                    self.recall_dd_gate.close_admission()
                except Exception:
                    pass
            error_handle = exc.handle if _valid_opaque_handle(exc.handle) else None
            if error_handle is not None and error_handle not in self.handles:
                self.handles.append(error_handle)
            elif exc.handle is not None:
                self._unconfirmed_launch = True
            if (exc.preserve_required or exc.child_reaped is False) and exc.handle is None:
                self._unconfirmed_launch = True
            return self._response(
                request_id, status="launch_failure", error=_bounded_text(exc),
                handle=error_handle, child_reaped=exc.child_reaped,
                preserve_required=exc.preserve_required,
            )
        except Exception as exc:
            self._sticky_failure = True
            self._unconfirmed_launch = True
            if command == "recall-dd":
                try:
                    self.recall_dd_gate.close_admission()
                except Exception:
                    pass
            return self._response(request_id, status="launch_failure",
                                  error=f"supervisor launch failed: {_bounded_text(exc)}",
                                  preserve_required=True)
        if not _valid_opaque_handle(handle) or handle in self.handles:
            self._sticky_failure = True
            self._unconfirmed_launch = True
            if command == "recall-dd":
                try:
                    self.recall_dd_gate.close_admission()
                except Exception:
                    pass
            return self._response(request_id, status="supervisor_contract_failure",
                                  error="supervisor returned an invalid or duplicate handle",
                                  preserve_required=True)
        self.handles.append(handle)
        return self._response(request_id, status="ready", ok=True, handle=handle)

    def _close_recall_dd_descriptors(self) -> list[str]:
        if self.recall_dd_gate is None or self._recall_dd_close_attempted:
            return []
        self._recall_dd_close_attempted = True
        try:
            errors = self.recall_dd_gate.close()
        except Exception as exc:
            self._sticky_failure = True
            return [f"direct dd descriptor cleanup failed: {_bounded_text(exc)}"]
        if not isinstance(errors, (tuple, list)) or any(not isinstance(item, str) for item in errors):
            self._sticky_failure = True
            return ["direct dd descriptor cleanup returned an invalid report"]
        if errors:
            self._sticky_failure = True
            return [_bounded_text(item, 160) for item in errors[:8]]
        return []

    def _worker_reaped(self, handle: str) -> bool:
        try:
            return bool(self.supervisor.worker_for_test(handle).reaped)
        except Exception:
            return False

    def _all_reaped(self) -> bool:
        return not self._unconfirmed_launch and all(self._worker_reaped(handle) for handle in self.handles)

    def _wait(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        self._exact_keys(request, {"id", "op", "handle", "timeout_ms"})
        handle = request.get("handle")
        if not isinstance(handle, str) or not handle or len(handle) > 128 or handle not in self.handles:
            raise ProtocolError("unknown or invalid worker handle", request_id=request_id)
        timeout_ms = self._bounded_integer(
            request.get("timeout_ms"), 0, MAX_WAIT_MS, "timeout_ms", request_id
        )
        try:
            result = self.supervisor.wait(handle, timeout_ms / 1000.0)
        except Exception as exc:
            self._sticky_failure = True
            result = None
            error = _bounded_text(exc)
        else:
            error = None
        if result is None:
            self._sticky_failure = True
            return self._response(request_id, status="lifecycle_failure", error=error or "wait failed",
                                  worker=None, all_reaped=self._all_reaped())
        if result.errors:
            self._sticky_failure = True
        status = "reaped" if result.reaped and not result.errors else (
            "lifecycle_failure" if result.errors else "running"
        )
        return self._response(request_id, status=status, ok=status != "lifecycle_failure",
                              worker=_result_dict(result), all_reaped=self._all_reaped())

    def _stop_all(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        self._exact_keys(request, {"id", "op", "handles"})
        handles = request.get("handles")
        if not isinstance(handles, list) or len(handles) > MAX_WORKERS:
            raise ProtocolError("handles must be a bounded list", request_id=request_id)
        if any(not isinstance(item, str) or not item or len(item) > 128 for item in handles):
            raise ProtocolError("handles contain an invalid opaque handle", request_id=request_id)
        self._admission_closed = True
        repeated_stop = self._stop_all_attempted
        self._stop_all_attempted = True
        if repeated_stop:
            # A second report is not a new authorization attempt.  Still run
            # the supervisor's best-effort stop/reap pass, but latch failure.
            self._sticky_failure = True
        try:
            # The callback only returns an in-memory marker.  This service has
            # no device cleanup callback and cannot touch DM, loop, or swap.
            report, _ = self.supervisor.cleanup_after_stop(handles, lambda: "authorization-only")
        except Exception as exc:
            self._sticky_failure = True
            self._last_stop_all_reaped = False
            self._last_stop_all_clean = False
            return self._response(request_id, status="lifecycle_failure",
                                  error=f"stop_all failed: {_bounded_text(exc)}")
        descriptor_errors = self._close_recall_dd_descriptors() if self._all_reaped() else []
        self._last_stop_all_reaped = bool(report.all_reaped) and self._all_reaped()
        self._last_stop_all_clean = (
            bool(report.cleanup_allowed) and self._last_stop_all_reaped
            and not repeated_stop and not descriptor_errors
        )
        result_handles = [result.handle for result in report.results]
        if (any(not _valid_opaque_handle(handle) for handle in result_handles)
                or len(result_handles) != len(set(result_handles))
                or set(result_handles) != set(self.handles)):
            self._sticky_failure = True
        if report.errors or any(result.errors for result in report.results) or descriptor_errors:
            self._sticky_failure = True
        cleanup_allowed = self._last_stop_all_clean and not self._sticky_failure
        if not cleanup_allowed:
            self._sticky_failure = True
        results = [_result_dict(result) for result in report.results]
        response = self._response(
            request_id,
            status="complete" if cleanup_allowed else "lifecycle_failure",
            ok=cleanup_allowed,
            cleanup_allowed=cleanup_allowed,
            all_reaped=self._last_stop_all_reaped,
            workers=results,
            errors=[_bounded_text(item, 160)
                    for item in list(report.errors)[:max(0, 8 - len(descriptor_errors))]]
                    + descriptor_errors[:8],
        )
        if len(encode_frame(response)) > MAX_FRAME_BYTES:
            response = self._response(
                request_id, status="lifecycle_failure", all_reaped=self._last_stop_all_reaped,
                error="stop report exceeded protocol response limit",
            )
            self._sticky_failure = True
            self._last_stop_all_clean = False
        return response

    def _shutdown_request(self, request_id: int, request: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        self._exact_keys(request, {"id", "op"})
        if not self._all_reaped():
            # An out-of-order or unresolved shutdown attempt is sticky.  The
            # caller may still issue stop_all to reap children, but it can no
            # longer receive cleanup authorization from this session.
            self._sticky_failure = True
            return self._response(request_id, status="workers_unresolved", all_reaped=False,
                                  error="shutdown rejected while a worker is unconfirmed or unreaped"), False
        self._admission_closed = True
        self._shutdown = True
        clean = self._stop_all_attempted and self._last_stop_all_clean and not self._sticky_failure
        if not clean:
            self._sticky_failure = True
        status = "shutdown" if clean else "shutdown_with_lifecycle_failure"
        return self._response(request_id, status=status, ok=clean,
                              cleanup_allowed=clean, all_reaped=True), True

    def _dispatch(self, request: object) -> tuple[dict[str, Any], bool, int | None]:
        request_id: int | None = None
        try:
            request_id, operation, fields = self._validate_common(request)
            if operation == "launch":
                return self._launch(request_id, fields), False, None
            if operation == "wait":
                return self._wait(request_id, fields), False, None
            if operation == "stop_all":
                return self._stop_all(request_id, fields), False, None
            if operation == "shutdown":
                response, close_after = self._shutdown_request(request_id, fields)
                exit_code = 3 if self._sticky_failure else 0
                return response, close_after, exit_code if close_after else None
            raise ProtocolError("unsupported operation", request_id=request_id)
        except ProtocolError as exc:
            self._sticky_failure = True
            error_id = getattr(exc, "request_id", request_id)
            return self._response(error_id if isinstance(error_id, int) else None,
                                  status="protocol_error", error=_bounded_text(exc)), True, 2

    def _recover_workers(self, reason: str) -> ServiceOutcome:
        self._sticky_failure = True
        self._admission_closed = True
        try:
            report, _ = self.supervisor.cleanup_after_stop(tuple(self.handles), lambda: "authorization-only")
            all_reaped = bool(report.all_reaped) and self._all_reaped()
            descriptor_errors = self._close_recall_dd_descriptors() if self._all_reaped() else []
            # Even a successful internal recovery after transport loss cannot
            # authorize caller cleanup because no definitive response arrived.
            print(
                f"preserve_backing: {reason}; internal_all_reaped={str(all_reaped).lower()}; "
                f"descriptor_errors={len(descriptor_errors)}; external_cleanup_allowed=false",
                file=sys.stderr,
                flush=True,
            )
            return ServiceOutcome(2, "connection_lost", all_reaped, False)
        except Exception as exc:
            print(f"preserve_backing: {reason}; internal_stop_error={_bounded_text(exc)}; "
                  "external_cleanup_allowed=false", file=sys.stderr, flush=True)
            return ServiceOutcome(3, "lifecycle_failure", False, False)

    def serve(self, sock: socket.socket) -> ServiceOutcome:
        """Serve one inherited AF_UNIX stream; this method is single-threaded."""
        try:
            if sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
                return ServiceOutcome(2, "invalid_control_socket", False, False)
            # Popen/pass_fds may have made this descriptor inheritable.  The
            # worker must not keep the controller endpoint alive after the
            # supervisor exits or gain access to its control channel.
            sock.set_inheritable(False)
            sock.setblocking(False)
        except OSError:
            return ServiceOutcome(2, "invalid_control_socket", False, False)

        while True:
            try:
                request = recv_frame(sock, self.io_timeout, allow_clean_eof=True)
            except ProtocolError as exc:
                # Malformed, partial, oversized, and timed-out frames all deny
                # authorization and trigger best-effort direct-child cleanup.
                outcome = self._recover_workers(f"protocol failure: {exc}")
                response = self._response(None, status="protocol_error", error=_bounded_text(exc))
                try:
                    send_frame(sock, response, self.io_timeout)
                except ProtocolError:
                    pass
                return ServiceOutcome(2, "protocol_error", outcome.all_reaped, False)
            if request is None:
                return self._recover_workers("controller disconnected")

            response, close_after, exit_code = self._dispatch(request)
            if close_after and response.get("status") == "protocol_error":
                outcome = self._recover_workers("invalid controller request")
                response["all_reaped"] = outcome.all_reaped
            try:
                send_frame(sock, response, self.io_timeout)
            except ProtocolError as exc:
                return self._recover_workers(f"response delivery failed: {exc}")
            if close_after:
                if exit_code is None:
                    exit_code = 2
                return ServiceOutcome(exit_code, str(response.get("status")),
                                      self._all_reaped(), bool(response.get("cleanup_allowed")))


class SupervisorControlClient:
    """Client-side protocol with complete worker attestation and sticky denial.

    When available, ``service_process`` should be the Popen object used to
    launch this service.  Final authorization cross-checks the caller's waited
    exit code against that object.  Without a bound Popen, the caller must pass
    the exact result returned by waiting for this service process.
    """

    def __init__(
        self,
        sock: socket.socket,
        *,
        service_process: subprocess.Popen[Any] | None = None,
        timeout: float = DEFAULT_CLIENT_TIMEOUT,
    ) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise ValueError("control client requires an AF_UNIX stream socket")
        self.sock = sock
        self.service_process = service_process
        self.sock.setblocking(False)
        self.timeout = timeout
        self._next_id = 1
        self._transport_failed = False
        self._authorization_denied = False
        self._registered_handles: list[str] = []
        self._launch_attempts = 0
        self._stop_attempts = 0
        self._stop_authorized = False
        self._shutdown_acknowledged = False
        self._shutdown_attempts = 0
        self._finalized = False
        self.cleanup_authorized = False

    def _deny(self, *, transport: bool = False) -> None:
        """Latch a session failure; no later response can clear this state."""
        self._authorization_denied = True
        self.cleanup_authorized = False
        if transport:
            self._transport_failed = True
            self._stop_authorized = False
            self._shutdown_acknowledged = False

    def _protocol_failure(self, message: str) -> ProtocolFailure:
        self._deny(transport=True)
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        return ProtocolFailure(f"untrustworthy supervisor response: {message}; preserve backing")

    @staticmethod
    def _response_envelope(response: object, request_id: int) -> dict[str, Any]:
        if not isinstance(response, dict):
            raise ProtocolError("response must be an object")
        response_id = response.get("id")
        if isinstance(response_id, bool) or not isinstance(response_id, int) or response_id != request_id:
            raise ProtocolError("response request id mismatch")
        if not isinstance(response.get("status"), str):
            raise ProtocolError("response status is missing or invalid")
        for key in ("ok", "all_reaped", "cleanup_allowed", "preserve_backing"):
            if not isinstance(response.get(key), bool):
                raise ProtocolError(f"response field {key} is missing or invalid")
        if response["preserve_backing"] == response["cleanup_allowed"]:
            raise ProtocolError("response cleanup fields contradict")
        return response

    @staticmethod
    def _worker_row_shape(row: object) -> bool:
        if not isinstance(row, dict) or set(row) != {"handle", "reaped", "exit_code", "escalated", "errors"}:
            return False
        if not _valid_opaque_handle(row["handle"]):
            return False
        if not isinstance(row["reaped"], bool) or not isinstance(row["escalated"], bool):
            return False
        exit_code = row["exit_code"]
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int) or not 0 <= exit_code <= 255
        ):
            return False
        errors = row["errors"]
        return isinstance(errors, list) and all(isinstance(item, str) for item in errors)

    def _validate_stop_success(self, response: dict[str, Any]) -> bool:
        expected_keys = {
            "id", "ok", "status", "all_reaped", "cleanup_allowed", "preserve_backing", "workers", "errors"
        }
        if set(response) != expected_keys:
            raise ProtocolError("successful stop_all response has missing or unexpected fields")
        if not (
            response["status"] == "complete" and response["ok"] is True
            and response["all_reaped"] is True and response["cleanup_allowed"] is True
            and response["preserve_backing"] is False
        ):
            raise ProtocolError("successful stop_all verdict fields contradict")
        workers = response["workers"]
        errors = response["errors"]
        if not isinstance(workers, list) or len(workers) > MAX_WORKERS:
            raise ProtocolError("successful stop_all worker inventory is invalid")
        if not isinstance(errors, list) or any(not isinstance(item, str) for item in errors):
            raise ProtocolError("successful stop_all error inventory is invalid")
        if any(not self._worker_row_shape(row) for row in workers):
            raise ProtocolError("successful stop_all contains a malformed worker result")
        handles = [row["handle"] for row in workers]
        if len(handles) != len(set(handles)):
            raise ProtocolError("successful stop_all contains duplicate worker handles")
        if set(handles) != set(self._registered_handles) or len(handles) != len(self._registered_handles):
            raise ProtocolError("successful stop_all worker inventory does not match launch history")
        if any(row["reaped"] is not True or row["exit_code"] is None for row in workers):
            raise ProtocolError("successful stop_all contains an unreaped worker")
        if errors or any(row["errors"] for row in workers):
            return False
        return True

    def _validate_launch_response(self, response: dict[str, Any]) -> bool:
        if response.get("status") != "ready":
            self._deny()
            return False
        if self._stop_attempts:
            raise ProtocolError("service accepted launch after cleanup admission closed")
        expected_keys = {
            "id", "ok", "status", "all_reaped", "cleanup_allowed", "preserve_backing", "handle"
        }
        handle = response.get("handle")
        if (set(response) != expected_keys or response["ok"] is not True
                or response["all_reaped"] is not False or response["cleanup_allowed"] is not False
                or response["preserve_backing"] is not True or not _valid_opaque_handle(handle)
                or handle in self._registered_handles):
            raise ProtocolError("launch READY response is malformed or has a duplicate handle")
        self._registered_handles.append(handle)
        return True

    def _validate_wait_response(self, response: dict[str, Any], handle: object) -> None:
        status = response["status"]
        if status not in {"running", "reaped"}:
            self._deny()
            return
        if set(response) != {
            "id", "ok", "status", "all_reaped", "cleanup_allowed", "preserve_backing", "worker"
        }:
            raise ProtocolError("wait response has missing or unexpected fields")
        row = response["worker"]
        if not self._worker_row_shape(row) or row["handle"] != handle:
            raise ProtocolError("wait response worker does not match requested handle")
        if response["cleanup_allowed"] is not False or response["preserve_backing"] is not True:
            raise ProtocolError("wait response contains a cleanup verdict")
        if status == "running":
            if (response["ok"] is not True or row["reaped"] is not False
                    or row["exit_code"] is not None or row["errors"]):
                raise ProtocolError("running wait response has a contradictory worker result")
        elif (response["ok"] is not True or row["reaped"] is not True
              or row["exit_code"] != 0 or row["errors"]):
            raise ProtocolError("reaped wait response has a contradictory worker result")

    def _validate_shutdown_response(self, response: dict[str, Any]) -> bool:
        status = response["status"]
        if status == "workers_unresolved":
            self._deny()
            if (response["ok"] is not False or response["all_reaped"] is not False
                    or response["cleanup_allowed"] is not False or response["preserve_backing"] is not True
                    or not isinstance(response.get("error"), str)):
                raise ProtocolError("workers_unresolved response is malformed")
            return False
        if status != "shutdown":
            self._deny()
            return False
        expected_keys = {"id", "ok", "status", "all_reaped", "cleanup_allowed", "preserve_backing"}
        if (set(response) != expected_keys or response["ok"] is not True
                or response["all_reaped"] is not True or response["cleanup_allowed"] is not True
                or response["preserve_backing"] is not False):
            raise ProtocolError("successful shutdown response is incomplete or contradictory")
        return True

    def call(self, operation: str, **fields: Any) -> dict[str, Any]:
        if self._transport_failed or self._finalized or self._shutdown_acknowledged:
            self._deny()
            raise ChannelFailure("control session is no longer usable; preserve backing")
        if not isinstance(operation, str):
            self._deny()
            raise ValueError("operation must be a string")
        if "id" in fields or "op" in fields:
            self._deny()
            raise ValueError("id and op are reserved protocol fields")
        if operation not in {"launch", "wait", "stop_all", "shutdown"}:
            self._deny()
        denied_before_call = self._authorization_denied
        if operation in {"launch", "wait"} and self._stop_attempts:
            self._deny()
        if operation == "launch":
            if self._launch_attempts >= MAX_WORKERS:
                self._deny()
                raise ChannelFailure("client worker limit reached; preserve backing")
            self._launch_attempts += 1
            if denied_before_call and not self._stop_attempts:
                raise ChannelFailure("launch denied after an earlier session failure; preserve backing")
        if operation == "stop_all":
            self._stop_attempts += 1
            if self._stop_attempts > 1:
                self._deny()
            supplied = fields.get("handles")
            if supplied != self._registered_handles:
                self._deny()
        if operation == "shutdown":
            self._shutdown_attempts += 1
            if self._shutdown_attempts > 1 or not self._stop_authorized or self._authorization_denied:
                self._deny()
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, "op": operation, **fields}
        try:
            send_frame(self.sock, request, self.timeout)
            response = recv_frame(self.sock, self.timeout)
            if response is None:
                raise ProtocolError("supervisor closed without a response")
            response = self._response_envelope(response, request_id)
        except OSError as exc:
            self._deny(transport=True)
            raise SupervisorUnavailable(f"supervisor transport failed: {exc}; preserve backing") from exc
        except (ProtocolError, TimeoutError) as exc:
            self._deny(transport=True)
            message = str(exc)
            unavailable_markers = ("timed out", "read failed", "write failed", "truncated control frame",
                                   "short write")
            error_type = (SupervisorUnavailable if any(marker in message for marker in unavailable_markers)
                          else ProtocolFailure)
            raise error_type(f"untrustworthy supervisor response: {exc}; preserve backing") from exc

        try:
            if operation == "launch":
                if not self._validate_launch_response(response):
                    pass
            elif operation == "wait":
                self._validate_wait_response(response, fields.get("handle"))
            elif operation == "stop_all":
                if response["status"] == "complete":
                    report_clean = self._validate_stop_success(response)
                    self._stop_authorized = report_clean and not self._authorization_denied
                    if not report_clean:
                        self._deny()
                else:
                    self._stop_authorized = False
                    if (response["ok"] is not False or response["cleanup_allowed"] is not False
                            or response["preserve_backing"] is not True):
                        raise ProtocolError("failed stop_all response has a contradictory verdict")
                    self._deny()
            elif operation == "shutdown":
                response_clean = self._validate_shutdown_response(response)
                self._shutdown_acknowledged = response_clean and not self._authorization_denied
                if not response_clean:
                    self._deny()
            else:
                self._deny()
        except ProtocolError as exc:
            raise self._protocol_failure(str(exc)) from exc

        if operation in {"launch", "wait"} and response["cleanup_allowed"] is not False:
            raise self._protocol_failure(f"{operation} response unexpectedly grants cleanup")
        if response["status"] in {
            "protocol_error", "lifecycle_failure", "launch_failure", "supervisor_contract_failure", "admission_closed"
        }:
            self._deny(transport=response["status"] == "protocol_error")
        return response

    def confirm_service_exit(self, exit_code: object) -> bool:
        """Finalize after the caller has observed the service process exit.

        If a Popen object was bound at construction, its observed return code
        must match the caller's result.  Otherwise ``exit_code`` is the
        caller's attestation and must come directly from waiting for this
        session's service process.
        """
        if self._finalized:
            return self.cleanup_authorized
        self._finalized = True
        exit_observed = type(exit_code) is int and exit_code == 0
        if isinstance(self.service_process, subprocess.Popen):
            try:
                observed = self.service_process.poll()
                exit_observed = (
                    exit_observed and isinstance(observed, int) and not isinstance(observed, bool)
                    and observed == exit_code
                )
            except Exception:
                exit_observed = False
        self.cleanup_authorized = bool(
            not self._transport_failed and not self._authorization_denied
            and self._stop_authorized and self._shutdown_acknowledged and exit_observed
        )
        if not self.cleanup_authorized:
            self._deny()
        return self.cleanup_authorized

    def close(self) -> None:
        if not self.cleanup_authorized:
            self._deny(transport=True)
        try:
            self.sock.close()
        except OSError:
            self._deny(transport=True)


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fd", required=True, type=int, help="inherited private AF_UNIX stream socket fd")
    args = parser.parse_args()
    try:
        sock = socket.socket(fileno=args.fd)
    except OSError as exc:
        print(f"invalid inherited control socket: {exc}", file=sys.stderr)
        return 2
    try:
        outcome = SupervisorControlService().serve(sock)
        exit_code = outcome.exit_code
    finally:
        try:
            sock.close()
        except OSError as exc:
            print(f"control socket close failed: {exc}; preserve backing", file=sys.stderr)
            # Closing a controller socket is not a device cleanup operation;
            # the process status still becomes unsuccessful on close errors.
            exit_code = 3
    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ChannelFailure",
    "MAX_FRAME_BYTES",
    "ProtocolError",
    "ProtocolFailure",
    "ServiceOutcome",
    "SupervisorControlClient",
    "SupervisorControlService",
    "SupervisorUnavailable",
    "encode_frame",
    "recv_frame",
    "send_frame",
]
