#!/usr/bin/env python3
"""Rootless adapter for test-only pidfd supervisor IPC, not production recall.

The only admitted workers are fixed sleep and exit test commands. No arbitrary
argv, direct dd, device access, numeric PID signals or real cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Callable, Protocol


_HANDLE = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class RecallIPCError(RuntimeError):
    """Unconfirmed supervision requires preserving backing."""


class IPCClient(Protocol):
    def call(self, operation: str, **fields: Any) -> dict[str, Any]: ...
    def confirm_service_exit(self, exit_code: int) -> bool: ...


class ServiceProcess(Protocol):
    def wait(self, timeout: float | None = None) -> int: ...
    def poll(self) -> int | None: ...


@dataclass(frozen=True)
class WorkerOutcome:
    handle: str
    reaped: bool
    exit_code: int | None
    errors: tuple[str, ...]
    escalated: bool


@dataclass(frozen=True)
class StopAttestation:
    results: tuple[WorkerOutcome, ...]
    errors: tuple[str, ...]
    all_reaped: bool
    cleanup_allowed: bool


class RecallIPCAdapter:
    """Validate every IPC report and make cleanup denial permanently sticky."""

    def __init__(self, client: IPCClient, process: ServiceProcess, *,
                 exit_timeout: float = 8.0) -> None:
        if not math.isfinite(exit_timeout) or not 0 < exit_timeout <= 60:
            raise ValueError("exit_timeout must be positive, finite and bounded")
        self.client = client
        self.process = process
        self.exit_timeout = exit_timeout
        self.handles: list[str] = []
        self._denied = False
        self._stopped = False
        self._shutdown = False
        self._exited = False
        self._attestation: StopAttestation | None = None

    @property
    def cleanup_authorized(self) -> bool:
        return bool(self._exited and self._shutdown and self._stopped
                    and not self._denied)

    def _reject(self, reason: str) -> None:
        self._denied = True
        raise RecallIPCError(f"{reason}; preserve backing")

    def _call(self, operation: str, **fields: Any) -> dict[str, Any]:
        try:
            response = self.client.call(operation, **fields)
        except Exception as exc:
            self._reject(f"{operation} channel failed: {exc}")
        if not isinstance(response, dict):
            self._reject(f"{operation} returned a non-object")
        if (type(response.get("cleanup_allowed")) is not bool or
                type(response.get("preserve_backing")) is not bool or
                response["cleanup_allowed"] == response["preserve_backing"]):
            self._reject(f"{operation} cleanup verdict contradicts")
        return response

    @staticmethod
    def _valid_handle(value: object) -> bool:
        return (isinstance(value, str) and _HANDLE.fullmatch(value) is not None
                and not value.isdecimal())

    @staticmethod
    def _errors(value: object) -> tuple[str, ...]:
        if (not isinstance(value, list) or
                any(not isinstance(item, str) or not item or len(item) > 256
                    for item in value)):
            raise ValueError("invalid worker/report errors")
        return tuple(value)

    def _worker(self, value: object) -> WorkerOutcome:
        if (not isinstance(value, dict) or
                set(value) != {"handle", "reaped", "exit_code", "escalated", "errors"}):
            raise ValueError("worker result has incorrect fields")
        if not self._valid_handle(value["handle"]):
            raise ValueError("invalid worker handle")
        if type(value["reaped"]) is not bool or type(value["escalated"]) is not bool:
            raise ValueError("invalid worker boolean fields")
        exit_code = value["exit_code"]
        if exit_code is not None and type(exit_code) is not int:
            raise ValueError("invalid worker exit_code")
        return WorkerOutcome(value["handle"], value["reaped"], exit_code,
                             self._errors(value["errors"]), value["escalated"])

    def launch_test(self, command: str, *, duration_ms: int | None = None,
                    code: int | None = None) -> str:
        if self._denied or self._stopped or self._shutdown:
            self._reject("launch admission closed")
        if (command == "sleep" and type(duration_ms) is int
                and 0 <= duration_ms <= 5000 and code is None):
            fields: dict[str, Any] = {"command": "sleep", "duration_ms": duration_ms}
        elif (command == "exit" and type(code) is int and
              0 <= code <= 125 and duration_ms is None):
            fields = {"command": "exit", "code": code}
        else:
            self._reject("test worker command not allowlisted")
        response = self._call("launch", **fields)
        handle = response.get("handle")
        if (response.get("status") != "ready" or response.get("ok") is not True
                or response.get("cleanup_allowed") is not False
                or not self._valid_handle(handle) or handle in self.handles):
            self._reject("ambiguous or duplicate test worker launch")
        self.handles.append(handle)
        return handle

    def wait_reaped(self, handle: str, *, timeout_ms: int = 2000) -> WorkerOutcome:
        if self._denied or self._stopped or handle not in self.handles:
            self._reject("wait handle unknown or session closed")
        if type(timeout_ms) is not int or not 0 <= timeout_ms <= 60000:
            self._reject("invalid worker wait deadline")
        response = self._call("wait", handle=handle, timeout_ms=timeout_ms)
        try:
            result = self._worker(response["worker"])
        except (KeyError, ValueError, TypeError) as exc:
            self._reject(f"untrusted wait worker: {exc}")
        if (response.get("status") != "reaped" or response.get("ok") is not True
                or result.handle != handle or result.reaped is not True
                or result.errors or result.exit_code != 0):
            self._reject("worker was not safely reaped with successful exit")
        return result

    def stop_all(self) -> StopAttestation:
        if self._denied or self._stopped or self._shutdown:
            self._reject("stop_all denied after earlier failure")
        self._stopped = True
        response = self._call("stop_all", handles=list(self.handles))
        try:
            items = response["workers"]
            if not isinstance(items, list):
                raise ValueError("workers not a list")
            results = tuple(self._worker(item) for item in items)
            errors = self._errors(response["errors"])
            identifiers = [item.handle for item in results]
            complete = (len(identifiers) == len(self.handles)
                        and len(set(identifiers)) == len(identifiers)
                        and set(identifiers) == set(self.handles))
        except (KeyError, ValueError, TypeError) as exc:
            self._reject(f"untrusted stop report: {exc}")
        if (response.get("status") != "complete" or response.get("ok") is not True
                or response.get("all_reaped") is not True
                or response.get("cleanup_allowed") is not True
                or response.get("preserve_backing") is not False or
                not complete or errors or
                not all(item.reaped is True and not item.errors for item in results)):
            self._reject("stop report omitted or contradicted worker attestation")
        self._attestation = StopAttestation(results, errors, True, True)
        return self._attestation

    def shutdown_and_confirm_exit(self) -> bool:
        if self._denied or not self._stopped or self._attestation is None or self._shutdown:
            self._reject("shutdown before complete stop attestation")
        response = self._call("shutdown")
        if (response.get("status") != "shutdown" or response.get("ok") is not True
                or response.get("all_reaped") is not True
                or response.get("cleanup_allowed") is not True
                or response.get("preserve_backing") is not False):
            self._reject("shutdown response did not establish quiescence")
        self._shutdown = True
        try:
            code = self.process.wait(timeout=self.exit_timeout)
            observed = self.process.poll()
            approved = self.client.confirm_service_exit(code)
        except Exception as exc:
            self._reject(f"service exit not confirmed: {exc}")
        if type(code) is not int or code != 0 or observed != 0 or approved is not True:
            self._reject("service exit or client authorization failed")
        self._exited = True
        return True

    def run_synthetic_cleanup(self, callback: Callable[[], Any]) -> Any:
        if not self.cleanup_authorized:
            self._reject("synthetic cleanup before final service exit")
        return callback()


__all__ = ["RecallIPCAdapter", "RecallIPCError", "WorkerOutcome", "StopAttestation"]
