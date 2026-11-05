#!/usr/bin/env python3
"""Rootless, no physical I/O. Reproduce same-UID replacement of a live AF_UNIX listener pathname."""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile

ATTACKER = r'''
import json, os, socket, sys
path = sys.argv[1]
os.unlink(path)  # same UID owns the directory, despite its 0700 mode
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
    server.bind(path)
    os.chmod(path, 0o600)
    server.listen(1)
    print("READY", flush=True)
    with server.accept()[0] as connection:
        request = json.loads(connection.recv(4096).decode("ascii"))
        response = {"schema": request["schema"], "status": "PASS",
                    "phase": request["phase"], "source_sha": request["source_sha"],
                    "nonce": request["nonce"], "oracle_sha256": "d" * 64}
        connection.sendall((json.dumps(response, separators=(",", ":")) + "\n").encode("ascii"))
'''

def probe():
    with tempfile.TemporaryDirectory(prefix="swapz-rootless-probe-") as directory:
        os.chmod(directory, 0o700)
        socket_path = Path(directory) / "source-admission.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as genuine:
            genuine.bind(str(socket_path))
            os.chmod(socket_path, 0o600)
            genuine.listen(1)
            original_inode = socket_path.lstat().st_ino
            impostor = subprocess.Popen(
                [sys.executable, "-I", "-c", ATTACKER, str(socket_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True)
            try:
                if impostor.stdout.readline().strip() != "READY":
                    raise AssertionError("impostor failed to start")
                before = socket_path.lstat()
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                    channel.connect(str(socket_path))
                    peer_pid, peer_uid, _gid = struct.unpack("3i", channel.getsockopt(
                        socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
                    after = socket_path.lstat()
                    before_identity = (before.st_dev, before.st_ino, before.st_uid,
                                       stat.S_IMODE(before.st_mode), before.st_nlink)
                    after_identity = (after.st_dev, after.st_ino, after.st_uid,
                                      stat.S_IMODE(after.st_mode), after.st_nlink)
                    # Exact credential / pathname predicates at helper lines 208-231.
                    assert stat.S_ISSOCK(before.st_mode) and before.st_uid == os.geteuid()
                    assert stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1
                    assert peer_uid == os.geteuid() and before_identity == after_identity
                    assert peer_pid == impostor.pid and peer_pid != os.getpid()
                    assert before.st_ino != original_inode
                    request = {"schema":"swapz-primary-real-swap-admission-v1",
                               "phase":"initial", "source_sha":"a"*40,
                               "nonce":"b"*32}
                    channel.sendall((json.dumps(request)+"\n").encode("ascii"))
                    response = b""
                    while not response.endswith(b"\n"):
                        piece = channel.recv(4096)
                        if not piece:
                            raise AssertionError("fake server closed before reply")
                        response += piece
                    parsed = json.loads(response.decode("ascii"))
                    # Exact response identity / status checks at helper lines 332-364.
                    assert set(parsed)=={"schema","status","phase","source_sha","nonce","oracle_sha256"}
                    assert parsed["status"] == "PASS"
                    assert all(parsed[k] == request[k] for k in ("schema","phase","source_sha","nonce"))
                    assert parsed["oracle_sha256"] == "d" * 64
                genuine.settimeout(0.02)
                try:
                    accepted, _ = genuine.accept()
                except socket.timeout:
                    pass
                else:
                    accepted.close()
                    raise AssertionError("original parent was contacted")
                assert impostor.wait(timeout=2) == 0, impostor.stderr.read()
                return True
            finally:
                if impostor.poll() is None:
                    impostor.kill()  # exact Popen handle, never guessed PID
                impostor.wait(timeout=2)
                impostor.stdout.close()
                impostor.stderr.close()

if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("rootless only")
    for number in range(12):
        assert probe(), number
    print(json.dumps({"runs":12, "substitution":12, "peer_uid_check":"accepted",
                      "path_identity_check":"accepted", "forged_pass":"syntactically accepted",
                      "genuine_parent_connections":0, "privileged_execution":False}, sort_keys=True))
