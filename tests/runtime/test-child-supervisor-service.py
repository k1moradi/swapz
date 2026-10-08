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

GatedPidfdSupervisor = _SUPERVISOR_MODULE.GatedPidfdSupervisor
PidfdUnavailable = _SUPERVISOR_MODULE.PidfdUnavailable
StopReport = _SUPERVISOR_MODULE.StopReport
SupervisorError = _SUPERVISOR_MODULE.SupervisorError
WorkerResult = _SUPERVISOR_MODULE.WorkerResult

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

    def __init__(self, *, supervisor: Any | None = None, io_timeout: float = DEFAULT_IO_TIMEOUT) -> None:
        if not math.isfinite(io_timeout) or io_timeout <= 0:
            raise ValueError("io_timeout must be finite and positive")
        self.supervisor = supervisor if supervisor is not None else GatedPidfdSupervisor(
            startup_timeout=2.0, term_grace=0.25, kill_grace=0.25, escalate=True
        )
        self.io_timeout = io_timeout
        self.handles: list[str] = []
        self._launch_attempts = 0
        self._last_request_id = 0
        self._admission_closed = False
        self._sticky_failure = False
        self._unconfirmed_launch = False
        self._shutdown = False
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
        command = request.get("command")
        if command == "sleep":
            self._exact_keys(request, {"id", "op", "command", "duration_ms"})
            duration_ms = self._bounded_integer(
                request.get("duration_ms"), 0, MAX_SLEEP_MS, "duration_ms", request_id
            )
            argv = (sys.executable, "-c", _WORKER_CODE["sleep"], str(duration_ms))
        elif command == "exit":
            self._exact_keys(request, {"id", "op", "command", "code"})
            code = self._bounded_integer(request.get("code"), 0, 125, "code", request_id)
            argv = (sys.executable, "-c", _WORKER_CODE["exit"], str(code))
        else:
            raise ProtocolError("command is not in the test worker allowlist", request_id=request_id)
        if self._launch_attempts >= MAX_WORKERS:
            raise ProtocolError("worker limit reached", request_id=request_id)
        self._launch_attempts += 1
        try:
            handle = self.supervisor.launch(argv, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        except SupervisorError as exc:
            self._sticky_failure = True
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
            return self._response(request_id, status="launch_failure",
                                  error=f"supervisor launch failed: {_bounded_text(exc)}",
                                  preserve_required=True)
        if not _valid_opaque_handle(handle) or handle in self.handles:
            self._sticky_failure = True
            self._unconfirmed_launch = True
            return self._response(request_id, status="supervisor_contract_failure",
                                  error="supervisor returned an invalid or duplicate handle",
                                  preserve_required=True)
        self.handles.append(handle)
        return self._response(request_id, status="ready", ok=True, handle=handle)

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
        self._last_stop_all_reaped = bool(report.all_reaped) and self._all_reaped()
        self._last_stop_all_clean = bool(report.cleanup_allowed) and self._last_stop_all_reaped
        result_handles = [result.handle for result in report.results]
        if (any(not _valid_opaque_handle(handle) for handle in result_handles)
                or len(result_handles) != len(set(result_handles))
                or set(result_handles) != set(self.handles)):
            self._sticky_failure = True
        if report.errors or any(result.errors for result in report.results):
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
            errors=[_bounded_text(item, 160) for item in report.errors[:8]],
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
            return self._response(request_id, status="workers_unresolved", all_reaped=False,
                                  error="shutdown rejected while a worker is unconfirmed or unreaped"), False
        self._admission_closed = True
        self._shutdown = True
        clean = self._last_stop_all_clean and not self._sticky_failure
        status = "shutdown" if not self._sticky_failure else "shutdown_with_lifecycle_failure"
        return self._response(request_id, status=status, ok=True,
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
            # Even a successful internal recovery after transport loss cannot
            # authorize caller cleanup because no definitive response arrived.
            print(
                f"preserve_backing: {reason}; internal_all_reaped={str(all_reaped).lower()}; "
                "external_cleanup_allowed=false",
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
    """Small client-side protocol implementation with fail-closed authorization."""

    def __init__(self, sock: socket.socket, *, timeout: float = DEFAULT_CLIENT_TIMEOUT) -> None:
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise ValueError("control client requires an AF_UNIX stream socket")
        self.sock = sock
        self.sock.setblocking(False)
        self.timeout = timeout
        self._next_id = 1
        self._transport_failed = False
        self._authorization_denied = False
        self._stop_authorized = False
        self._shutdown_acknowledged = False
        self.cleanup_authorized = False

    def call(self, operation: str, **fields: Any) -> dict[str, Any]:
        if self._transport_failed:
            raise ChannelFailure("control session already failed; preserve backing")
        if "id" in fields or "op" in fields:
            self._authorization_denied = True
            raise ValueError("id and op are reserved protocol fields")
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, "op": operation, **fields}
        try:
            send_frame(self.sock, request, self.timeout)
            response = recv_frame(self.sock, self.timeout)
            if response is None or response.get("id") != request_id:
                raise ProtocolError("response request id mismatch")
            if not isinstance(response.get("cleanup_allowed"), bool) or not isinstance(response.get("preserve_backing"), bool):
                raise ProtocolError("response lacks explicit cleanup verdict")
            if response["preserve_backing"] == response["cleanup_allowed"]:
                raise ProtocolError("response cleanup fields contradict")
        except OSError as exc:
            self._transport_failed = True
            self._authorization_denied = True
            self.cleanup_authorized = False
            self._stop_authorized = False
            raise SupervisorUnavailable(f"supervisor transport failed: {exc}; preserve backing") from exc
        except (ProtocolError, TimeoutError) as exc:
            self._transport_failed = True
            self._authorization_denied = True
            self.cleanup_authorized = False
            self._stop_authorized = False
            message = str(exc)
            unavailable_markers = ("timed out", "read failed", "write failed", "truncated control frame",
                                   "short write")
            error_type = (SupervisorUnavailable if any(marker in message for marker in unavailable_markers)
                          else ProtocolFailure)
            raise error_type(f"untrustworthy supervisor response: {exc}; preserve backing") from exc

        if operation == "stop_all":
            self._stop_authorized = (
                response.get("status") == "complete"
                and response.get("ok") is True
                and response.get("all_reaped") is True
                and response.get("cleanup_allowed") is True
                and response.get("preserve_backing") is False
            )
            if not self._stop_authorized:
                self._authorization_denied = True
                self.cleanup_authorized = False
        elif operation == "shutdown":
            self._shutdown_acknowledged = (
                response.get("status") == "shutdown"
                and response.get("ok") is True
                and response.get("all_reaped") is True
            )
            if self._stop_authorized and (
                response.get("cleanup_allowed") is not True
                or response.get("preserve_backing") is not False
            ):
                self._shutdown_acknowledged = False
            if not self._shutdown_acknowledged:
                if response.get("status") != "workers_unresolved":
                    self._authorization_denied = True
                self.cleanup_authorized = False
        if response.get("status") in {"protocol_error", "lifecycle_failure", "launch_failure", "supervisor_contract_failure"}:
            self._authorization_denied = True
            self.cleanup_authorized = False
            if response.get("status") == "protocol_error":
                self._transport_failed = True
        if response.get("status") == "admission_closed":
            self._authorization_denied = True
            self.cleanup_authorized = False
        return response

    def confirm_service_exit(self, exit_code: int) -> bool:
        """Finalize only after a clean shutdown response and process exit."""
        self.cleanup_authorized = bool(
            not self._transport_failed and not self._authorization_denied
            and self._stop_authorized and self._shutdown_acknowledged and exit_code == 0
        )
        if not self.cleanup_authorized:
            self._authorization_denied = True
        return self.cleanup_authorized

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            self._transport_failed = True
            self._authorization_denied = True
            self.cleanup_authorized = False


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
