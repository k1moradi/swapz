#!/usr/bin/env python3
"""Persistent, *test-only* Bash-to-pidfd IPC bridge.

This is a rootless source-qualification tool; it never executes device dd, DM,
loop, NBD, swap, shell commands or PID signals. Its sole admitted workers are
the IPC service's fixed sleep/exit tests. Bash receives opaque handles only.

Input/output: one bounded JSON line per request/response. The final synthetic
cleanup verdict is available ONLY from FINALIZE, after a complete stop,
shutdown and observed service-process exit. EOF/invalid input preserves backing.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Any


MAX_LINE_BYTES = 2048
MAX_REQUESTS = 64
SERVICE_PATH = Path(__file__).with_name("test-child-supervisor-service.py")
ADAPTER_PATH = Path(__file__).with_name("recall-ipc-adapter.py")


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("missing IPC bridge dependency")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


service_module = _load("recall_bridge_service", SERVICE_PATH)
adapter_module = _load("recall_bridge_adapter", ADAPTER_PATH)


class BridgeError(Exception):
    """An invalid bridge or service result requires backing preservation."""


class PersistentRecallBridge:
    """Own exactly one service process, one socket and all opaque handles."""

    def __init__(self) -> None:
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(SERVICE_PATH), "--fd", str(child.fileno())],
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                # Retain child error diagnostics on this bridge's stderr.
                stderr=None,
                close_fds=True,
            )
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        try:
            self.client = service_module.SupervisorControlClient(
                parent, service_process=self.process, timeout=10.0,
            )
            self.adapter = adapter_module.RecallIPCAdapter(
                self.client, self.process, exit_timeout=10.0,
            )
        except BaseException:
            parent.close()
            # The owned service exits on socket EOF; do not signal any PID.
            try:
                self.process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                pass
            raise
        self.failed = False
        self.finalized = False
        self.request_count = 0
        self.last_id = 0
        self.finished = False

    @staticmethod
    def _reply(request_id: int | None, status: str, *,
               cleanup_allowed: bool = False, **data: Any) -> dict[str, Any]:
        return {
            "id": request_id,
            "status": status,
            "cleanup_allowed": cleanup_allowed,
            "preserve_backing": not cleanup_allowed,
            **data,
        }

    @staticmethod
    def _fields(message: dict[str, Any], expected: set[str]) -> None:
        if set(message) != expected:
            raise BridgeError("unknown or missing request fields")

    def dispatch(self, message: Any) -> dict[str, Any]:
        if self.failed or self.finalized:
            raise BridgeError("bridge session closed after failure or finalization")
        if not isinstance(message, dict):
            raise BridgeError("bridge request is not an object")
        request_id = message.get("id")
        if (type(request_id) is not int or not self.last_id < request_id <= 2**63 - 1):
            raise BridgeError("bridge request id must increase monotonically")
        self.last_id = request_id
        self.request_count += 1
        if self.request_count > MAX_REQUESTS:
            raise BridgeError("bridge request budget exceeded")
        op = message.get("op")
        if op == "LAUNCH_TEST":
            command = message.get("command")
            if command == "sleep":
                self._fields(message, {"id", "op", "command", "duration_ms"})
                handle = self.adapter.launch_test("sleep", duration_ms=message["duration_ms"])
            elif command == "exit":
                self._fields(message, {"id", "op", "command", "code"})
                handle = self.adapter.launch_test("exit", code=message["code"])
            else:
                raise BridgeError("test worker command not allowlisted")
            return self._reply(request_id, "ready", handle=handle)
        if op == "LAUNCH_ROLE":
            # This branch is never reachable from the public CLI instance.
            # Only a trusted, rootless, in-process test fixture can inject
            # an opt-in role adapter. Never accept device/argv paths in JSON.
            if not getattr(self, "_rootless_role_test", False):
                raise BridgeError("direct recall roles are disabled in the normal bridge")
            self._fields(message, {"id", "op", "role"})
            handle = self.adapter.launch_role(message["role"])
            return self._reply(request_id, "ready", handle=handle)
        if op == "WAIT":
            self._fields(message, {"id", "op", "handle", "timeout_ms"})
            result = self.adapter.wait_reaped(message["handle"], timeout_ms=message["timeout_ms"])
            return self._reply(request_id, "reaped", handle=result.handle,
                               reaped=result.reaped, exit_code=result.exit_code)
        if op == "STOP_ALL":
            self._fields(message, {"id", "op"})
            report = self.adapter.stop_all()
            return self._reply(request_id, "stopped", all_reaped=report.all_reaped,
                               workers=[{"handle": row.handle, "reaped": row.reaped}
                                        for row in report.results])
        if op == "SHUTDOWN":
            self._fields(message, {"id", "op"})
            self.adapter.shutdown_and_confirm_exit()
            # Not authorized to remove synthetic backing until explicit FINALIZE.
            return self._reply(request_id, "shutdown_verified", service_exit=0)
        if op == "FINALIZE":
            self._fields(message, {"id", "op"})
            if not self.adapter.cleanup_authorized:
                raise BridgeError("service exit or stop confirmation is missing")
            # Close the already-exited service's control descriptor *before*
            # issuing the sole positive cleanup verdict. The lower-level
            # client latches descriptor-close errors as permanent denial.
            self.client.close()
            if self.client.cleanup_authorized is not True:
                raise BridgeError("service control descriptor did not close cleanly")
            self.finalized = True
            self.finished = True
            return self._reply(request_id, "cleanup_authorized", cleanup_allowed=True)
        raise BridgeError("unsupported bridge operation")

    def best_effort_preserve(self) -> None:
        """Close a failed bridge; never assume best-effort reap allows cleanup."""
        self.failed = True
        self.finalized = False
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=10.0)
        except (subprocess.TimeoutExpired, OSError):
            print("BRIDGE_PRESERVE: service exit not confirmed; retain all backing", file=sys.stderr)
        self.finished = True


class RootlessRoleBridge(PersistentRecallBridge):
    """Trusted-injection-only test bridge; not exposed by main() or service CLI.

    The caller already owns a synthetic service, its control client, exact
    process object and an adapter with an identity-bound readback verifier.
    This class creates no process and cannot enable live mapper operations.
    """

    def __init__(self, *, client: Any, process: Any,
                 adapter: Any) -> None:
        if not isinstance(adapter, adapter_module.RecallRoleIPCAdapter):
            raise ValueError("rootless role bridge requires an explicit role adapter")
        if adapter.client is not client or adapter.process is not process:
            raise ValueError("rootless bridge client and service identity do not match")
        self.client = client
        self.process = process
        self.adapter = adapter
        self._rootless_role_test = True
        self.failed = False
        self.finalized = False
        self.request_count = 0
        self.last_id = 0
        self.finished = False

def _decode(raw: bytes) -> Any:
    if not raw or len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
        raise BridgeError("missing, oversized, or unterminated request line")
    try:
        def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            out: dict[str, Any] = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate JSON key")
                out[key] = value
            return out
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise BridgeError(f"invalid request JSON: {exc}") from exc


def _print_reply(reply: dict[str, Any]) -> None:
    print(json.dumps(reply, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)


def main() -> int:
    if len(sys.argv) != 1:
        print("BRIDGE_PRESERVE: bridge does not accept file paths or argv", file=sys.stderr)
        return 2
    try:
        bridge = PersistentRecallBridge()
    except Exception as exc:
        print(f"BRIDGE_PRESERVE: IPC startup failed: {exc}", file=sys.stderr)
        return 2

    try:
        _print_reply(bridge._reply(None, "bridge_ready"))
        while not bridge.finished:
            raw = sys.stdin.buffer.readline(MAX_LINE_BYTES + 1)
            if not raw:
                print("BRIDGE_PRESERVE: controller disconnected without FINALIZE", file=sys.stderr)
                return 2
            request = None  # A malformed frame never inherits a previous id.
            try:
                request = _decode(raw)
                reply = bridge.dispatch(request)
            except Exception as exc:
                bridge.failed = True
                print(f"BRIDGE_PRESERVE: {str(exc)[:200]}", file=sys.stderr)
                error_id = (request.get("id") if isinstance(request, dict)
                            and type(request.get("id")) is int else None)
                _print_reply(bridge._reply(
                    error_id, "preserve_backing",
                    error="bridge or worker safety gate failed",
                ))
                return 2
            _print_reply(reply)
        return 0 if bridge.finalized and not bridge.failed else 2
    except (OSError, BrokenPipeError, ValueError) as exc:
        print(f"BRIDGE_PRESERVE: controller channel failed: {exc}", file=sys.stderr)
        return 2
    finally:
        if not bridge.finalized or bridge.failed:
            bridge.best_effort_preserve()


if __name__ == "__main__":
    raise SystemExit(main())
