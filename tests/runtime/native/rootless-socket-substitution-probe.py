#!/usr/bin/env python3
"""Rootless proof that the actual client blocks same-UID source-listener substitution."""

import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
SPEC = importlib.util.spec_from_file_location(
    "swapz_rootless_source_admission_client", HELPER)
helper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = helper
SPEC.loader.exec_module(helper)

SOURCE = "a" * 40
HELPER_DIGEST = "8" * 64
ORACLE_DIGEST = "d" * 64
CONTROL_HASHES = {
    path: "c" * 64 for path in helper.PHYSICAL_CONTROL_INPUT_PATHS
}

ATTACKER = r"""
import json
import os
import socket
import sys

path = sys.argv[1]
os.unlink(path)  # Same UID owns the parent-created 0700 directory.
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(1)
    print("READY", flush=True)
    with server.accept()[0] as connection:
        request_bytes = bytearray()
        while b"\n" not in request_bytes:
            chunk = connection.recv(4096)
            if not chunk:
                # A correctly authenticated client rejects before sending any
                # admission request to this unrelated same-UID listener.
                sys.exit(0)
            request_bytes.extend(chunk)
            if len(request_bytes) > 4096:
                raise RuntimeError("request exceeded admission line limit")
        request_line, _, trailing = request_bytes.partition(b"\n")
        if trailing:
            raise RuntimeError("unexpected trailing request bytes")
        request = json.loads(request_line.decode("ascii"))
        response = {
            "schema": request["schema"],
            "status": "PASS",
            "phase": request["phase"],
            "source_sha": request["source_sha"],
            "nonce": request["nonce"],
            "oracle_sha256": "d" * 64,
        }
        connection.sendall(
            (json.dumps(response, separators=(",", ":")) + "\n").encode("ascii"))
"""

def probe() -> bool:
    with tempfile.TemporaryDirectory(
            prefix="swapz-rootless-probe-") as directory:
        os.chmod(directory, 0o700)
        socket_path = Path(directory) / "source-admission.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as genuine:
            genuine.bind(os.fspath(socket_path))
            os.chmod(socket_path, 0o600)
            genuine.listen(1)
            original_inode = socket_path.lstat().st_ino

            impostor = subprocess.Popen(
                [sys.executable, "-I", "-c", ATTACKER, os.fspath(socket_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            client = None
            try:
                if impostor.stdout is None or \
                        impostor.stdout.readline().strip() != "READY":
                    diagnostic = (
                        impostor.stderr.read() if impostor.stderr is not None else "")
                    raise AssertionError(
                        f"impostor failed to start: {diagnostic}")

                replacement_inode = socket_path.lstat().st_ino
                assert replacement_inode != original_inode

                # This is the production client implementation, not a duplicate
                # of its UID/path/response predicates.
                rejection = None
                try:
                    client = helper.SourceAdmissionClient(
                        os.fspath(socket_path), os.geteuid(), SOURCE)
                except helper.Blocked as error:
                    rejection = str(error)
                if client is not None:
                    # Still exercise the published synthetic-PASS attack path
                    # if connection-time authentication unexpectedly regresses.
                    credentials = client._channel.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED,
                        struct.calcsize("3i"))
                    peer_pid, peer_uid, _peer_gid = struct.unpack(
                        "3i", credentials)
                    assert peer_pid == impostor.pid
                    assert peer_uid == os.geteuid()
                    client.bind_physical_control_inputs(CONTROL_HASHES)
                    client.bind_executed_helper_sha256(HELPER_DIGEST)
                    try:
                        client.require("initial")
                    except helper.Blocked as error:
                        rejection = str(error)
                    else:
                        raise AssertionError("unrelated listener forged PASS")
                assert rejection is not None
                for field in (
                        "phase=connect", "check=parent_ancestry",
                        "expected=live_ancestor_pid_starttime_uid_socket_inode_reply_sender",
                        "observed=unrelated_peer_run", "errno=none",
                        "authorization=BLOCKED",
                        "next=inspect_parent_identity_read_only"):
                    assert field in rejection, (field, rejection)
                if client is not None:
                    client.close()
                    client = None

                genuine.settimeout(0.02)
                try:
                    accepted, _address = genuine.accept()
                except socket.timeout:
                    pass
                else:
                    accepted.close()
                    raise AssertionError("original parent was contacted")

                assert impostor.wait(timeout=2) == 0, (
                    impostor.stderr.read() if impostor.stderr is not None else "")
                return True
            finally:
                if client is not None:
                    try:
                        client.close()
                    except OSError:
                        pass
                if impostor.poll() is None:
                    impostor.kill()  # Exact Popen handle, never a guessed PID.
                impostor.wait(timeout=2)
                if impostor.stdout is not None:
                    impostor.stdout.close()
                if impostor.stderr is not None:
                    impostor.stderr.close()


if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("rootless only")
    for number in range(12):
        assert probe(), number
    print(json.dumps({
        "runs": 12,
        "substitution": 12,
        "actual_source_admission_client": "blocked_unrelated_listener",
        "authenticated_peer_class": "unrelated_same_uid_process",
        "genuine_parent_connections": 0,
        "first_failed_authenticity_invariant": "parent_ancestry",
        "privileged_execution": False,
    }, sort_keys=True))
