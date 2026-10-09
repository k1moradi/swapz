#!/usr/bin/env python3
"""Private, rootless-only *process* fixture for five pinned direct-dd roles.

This file is NOT a general supervisor CLI or trusted production bootstrap.
Its only launch target is an owned, exact-size regular-file synthetic mapper,
and the fixed local dd executable. The normal IPC service CLI is unchanged.

A specialized service attests pinned output bytes after its pidfd worker is
reaped. A specialized client validates a fixed receipt (role, handle, digest)
before the existing strict role adapter grants even synthetic finalization.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import socket
import stat
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
PAGE_SIZE = 4096
PAGES = {"a": 0, "b": 4, "a2": 0, "b2": 5}
TEST_MAPPER = "swapz-v22-rootless-regular-only"


def load_module(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError("fixture dependency unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


service = load_module("swapz_process_fixture_service", "test-child-supervisor-service.py")
readback = load_module("swapz_process_fixture_readback", "recall-readback-identity.py")


def reference_page(page: int) -> bytes:
    """Independent deterministic fixture reference; never read pages.bin."""
    return bytes(((page * 23 + index) % 256) for index in range(PAGE_SIZE))


def source_bytes() -> bytes:
    return b"".join(reference_page(page) for page in range(9))


def _regular_mapper_only(fd: int, name: str, ops: Any) -> bool:
    info = ops.fstat(fd)
    return (name == TEST_MAPPER and stat.S_ISREG(info.st_mode)
            and info.st_size == 9 * PAGE_SIZE
            and info.st_uid == os.geteuid() and info.st_nlink == 1
            and not (info.st_mode & 0o022))


class PinnedAttestingGate:
    """Capture the exact readback descriptor before the supervisor launches."""

    def __init__(self, gate: Any) -> None:
        self.gate = gate
        self.identities: dict[str, Any] = {}

    def admit(self, role: str) -> Any:
        launch = self.gate.admit(role)
        if role in PAGES:
            self.identities[role] = readback.capture_readback_identity(
                self.gate._directory_fd, self.gate._output_fds[role], role
            )
        return launch

    def verify(self, role: str) -> str:
        if role not in PAGES or role not in self.identities:
            raise RuntimeError("missing prelaunch role identity")
        data = reference_page(PAGES[role])
        readback.verify_readback(
            self.identities[role],
            directory_fd=self.gate._directory_fd,
            output_fd=self.gate._output_fds[role],
            expected_page=data,
        )
        return hashlib.sha256(data).hexdigest()

    def close_admission(self) -> None:
        self.gate.close_admission()

    def close(self) -> tuple[str, ...]:
        return self.gate.close()


class AttestingService(service.SupervisorControlService):
    """Service-owned descriptor verification; no path or fd IPC operation."""

    def __init__(self, gate: PinnedAttestingGate) -> None:
        super().__init__(recall_dd_gate=gate, enable_direct_dd=True, io_timeout=5.0)
        self.gate = gate
        self.roles: dict[str, str] = {}
        self.verified: set[str] = set()

    def _launch(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        response = super()._launch(request_id, request)
        if response.get("status") == "ready" and request.get("command") == "recall-dd":
            self.roles[response["handle"]] = request["role"]
        return response

    def _wait(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        response = super()._wait(request_id, request)
        handle = request.get("handle")
        if response.get("status") != "reaped" or response.get("ok") is not True:
            return response
        role = self.roles.get(handle)
        if role is None or handle in self.verified:
            self._sticky_failure = True
            return self._response(request_id, status="lifecycle_failure",
                                  error="untrusted role or duplicate successful wait")
        if response["worker"].get("exit_code") != 0:
            self._sticky_failure = True
            return self._response(request_id, status="lifecycle_failure",
                                  error="direct worker returned nonzero")
        try:
            digest = self.gate.verify(role) if role != "writer" else ""
        except Exception as exc:
            self._sticky_failure = True
            try:
                self.gate.close_admission()
            except Exception:
                pass
            return self._response(
                request_id, status="lifecycle_failure",
                error=f"pinned readback rejected: {str(exc)[:160]}"
            )
        self.verified.add(handle)
        response["attestation"] = {
            "role": role, "handle": handle, "verified": True, "sha256": digest
        }
        return response

    def _stop_all(self, request_id: int, request: dict[str, Any]) -> dict[str, Any]:
        if (set(self.roles) != self.verified or len(self.roles) != 5
                or set(self.roles.values()) != {"writer", *PAGES}):
            self._sticky_failure = True
        return super()._stop_all(request_id, request)


class AttestedClient(service.SupervisorControlClient):
    """Validate a strict fixed receipt *in addition to* the existing IPC checks."""

    def __init__(self, sock: socket.socket, *, service_process: Any,
                 timeout: float = 10.0):
        super().__init__(sock, service_process=service_process, timeout=timeout)
        self.roles: dict[str, str] = {}
        self.receipts: dict[str, str] = {}

    def call(self, operation: str, **fields: Any) -> dict[str, Any]:
        response = super().call(operation, **fields)
        if operation == "launch" and response.get("status") == "ready":
            if fields.get("command") != "recall-dd" or fields.get("role") not in {
                "writer", *PAGES
            }:
                raise self._protocol_failure("non-role launch in attested session")
            self.roles[response["handle"]] = fields["role"]
        return response

    def _validate_wait_response(self, response: dict[str, Any], handle: object) -> None:
        receipt = response.pop("attestation", None)
        super()._validate_wait_response(response, handle)
        if response.get("status") != "reaped":
            return
        role = self.roles.get(handle)
        if (role is None or not isinstance(receipt, dict)
                or set(receipt) != {"role", "handle", "verified", "sha256"}
                or receipt["role"] != role or receipt["handle"] != handle
                or receipt["verified"] is not True or role in self.receipts):
            raise service.ProtocolError("role/handle attestation missing, replayed or contradictory")
        expected = "" if role == "writer" else hashlib.sha256(
            reference_page(PAGES[role])
        ).hexdigest()
        if type(receipt["sha256"]) is not str or receipt["sha256"] != expected:
            raise service.ProtocolError("readback attestation digest does not match immutable reference")
        self.receipts[role] = handle

    def verified_role(self, role: str, handle: str) -> bool:
        return type(role) is str and self.receipts.get(role) == handle


def child_main(sock_fd: int, mapper_fd: int) -> int:
    if os.geteuid() == 0:
        print("ROOTLESS_PRESERVE: root execution prohibited", file=sys.stderr)
        return 2
    # fd validity and mapper verification happen BEFORE any worker launch.
    mapper_stat = os.fstat(mapper_fd)
    if not _regular_mapper_only(mapper_fd, TEST_MAPPER, os):
        print("ROOTLESS_PRESERVE: synthetic mapper must be a private regular file", file=sys.stderr)
        return 2
    os.set_inheritable(mapper_fd, False)
    fixture = Path.cwd()
    gate = service.RecallDDLaunchGate(
        fixture, TEST_MAPPER, mapper_fd=mapper_fd,
        executable_path=Path("/usr/bin/dd"),
        mapper_verifier=_regular_mapper_only,
    )
    pinned = PinnedAttestingGate(gate)
    try:
        sock = socket.socket(fileno=sock_fd)
        try:
            outcome = AttestingService(pinned).serve(sock)
            return outcome.exit_code
        finally:
            sock.close()
    finally:
        pinned.close()


def main() -> int:
    # Only two integer inherited fds are accepted; the fixture path is cwd.
    # No caller-provided mapper path, executable, argv or device type.
    if len(sys.argv) != 3 or any(not x.isdecimal() for x in sys.argv[1:]):
        print("ROOTLESS_PRESERVE: fixed inherited descriptors required", file=sys.stderr)
        return 2
    try:
        return child_main(int(sys.argv[1]), int(sys.argv[2]))
    except Exception as exc:
        print(f"ROOTLESS_PRESERVE: service startup/teardown failed: {str(exc)[:180]}",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
