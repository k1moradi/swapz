#!/usr/bin/env python3
"""Unprivileged admission parent for private physical real-swap qualification.

This parent owns every Git/remote-main source decision. It performs no block,
Device Mapper, swap, module, or lifecycle mutation. The privileged child must
request a fresh authenticated approval immediately before each physical cycle
and again before a PASS can be emitted.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIVILEGED_HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
DEFAULT_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
SOURCE_ADMISSION_SCHEMA = "swapz-primary-real-swap-admission-v1"
MAX_LINE_BYTES = 4096
MAX_CYCLES = 4


class Blocked(RuntimeError):
    pass


def _run(command: list[str], *, check: bool = True,
         timeout: int = 30) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, cwd=ROOT, text=True, capture_output=True,
        check=False, timeout=timeout)
    if check and result.returncode != 0:
        raise Blocked(f"source admission command failed: {command[0]}")
    return result


def _check_git_source(validated_source: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
        raise Blocked("validated source must be one full lowercase SHA")
    head = _run(["git", "rev-parse", "HEAD"], timeout=10).stdout.strip()
    branch = _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        timeout=10).stdout.strip()
    origin_main = _run(
        ["git", "rev-parse", "--verify", "refs/remotes/origin/main"],
        timeout=10).stdout.strip()
    if head != validated_source:
        raise Blocked(
            f"checkout HEAD {head} differs from validated source "
            f"{validated_source}")
    if branch != "main" or origin_main != validated_source:
        raise Blocked(
            "physical qualification requires main == origin/main == "
            "validated source")
    remote_main = _run(
        ["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"],
        check=False, timeout=30)
    if remote_main.returncode != 0:
        raise Blocked(
            "cannot verify the current remote main for physical qualification")
    if remote_main.stdout.strip() != (
            f"{validated_source}\trefs/heads/main"):
        raise Blocked("current remote main differs from the validated source")
    if _run(["git", "status", "--porcelain"], timeout=10).stdout:
        raise Blocked("production source tree is not clean")


def _trusted_executable(name: str) -> str:
    candidate = shutil.which(name)
    if not candidate:
        raise Blocked(f"missing required command {name}")
    resolved = Path(candidate).resolve()
    try:
        info = resolved.stat()
    except OSError as exc:
        raise Blocked(f"cannot inspect required command {name}") from exc
    if (not resolved.is_absolute() or not stat.S_ISREG(info.st_mode) or
            info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022 or
            not os.access(resolved, os.X_OK)):
        raise Blocked(f"unsafe required command {name}")
    return os.fspath(resolved)


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def _read_request(stream, validated_source: str) -> dict:
    line = stream.readline(MAX_LINE_BYTES + 2)
    if not line:
        raise EOFError
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise Blocked("source admission request is malformed")
    try:
        request = json.loads(
            line[:-1].decode("ascii"),
            object_pairs_hook=_unique_json_object)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise Blocked("source admission request is malformed") from exc
    required = {"schema", "phase", "source_sha", "nonce"}
    if (not isinstance(request, dict) or set(request) != required or
            request.get("schema") != SOURCE_ADMISSION_SCHEMA or
            request.get("source_sha") != validated_source or
            not re.fullmatch(
                r"[0-9a-f]{32}", str(request.get("nonce", ""))) or
            not re.fullmatch(
                r"(?:initial|final|cycle-[1-4])",
                str(request.get("phase", "")))):
        raise Blocked("source admission request identity is invalid")
    return request


def _reply(stream, request: dict, status: str) -> None:
    response = {
        "schema": SOURCE_ADMISSION_SCHEMA,
        "status": status,
        "phase": request["phase"],
        "source_sha": request["source_sha"],
        "nonce": request["nonce"],
    }
    stream.write(
        json.dumps(
            response, sort_keys=True, separators=(",", ":")).encode("ascii") +
        b"\n")
    stream.flush()


def _stop_unadmitted_child(child: subprocess.Popen) -> None:
    if child.poll() is not None:
        return
    child.terminate()
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()


def _serve_admission(server: socket.socket,
                     child: subprocess.Popen,
                     validated_source: str,
                     cycles: int) -> int:
    expected_phases = (
        ["initial"] +
        [f"cycle-{index}" for index in range(1, cycles + 1)] +
        ["final"])
    passed_phases: list[str] = []
    server.settimeout(30)
    try:
        connection, _address = server.accept()
    except socket.timeout as exc:
        _stop_unadmitted_child(child)
        raise Blocked(
            "privileged qualifier did not establish source admission channel"
        ) from exc

    with connection:
        credentials = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
        if peer_uid != 0:
            _stop_unadmitted_child(child)
            raise Blocked("source admission peer is not privileged")
        with connection.makefile("rwb", buffering=0) as stream:
            while True:
                try:
                    request = _read_request(stream, validated_source)
                except EOFError:
                    break
                except Blocked as exc:
                    print(
                        "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
                        file=sys.stderr)
                    break
                expected_phase = (
                    expected_phases[len(passed_phases)]
                    if len(passed_phases) < len(expected_phases) else None)
                if request["phase"] != expected_phase:
                    _reply(stream, request, "BLOCKED")
                    print(
                        "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
                        "unexpected_source_admission_phase",
                        file=sys.stderr)
                    break
                try:
                    _check_git_source(validated_source)
                except Blocked as exc:
                    _reply(stream, request, "BLOCKED")
                    print(
                        "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
                        file=sys.stderr)
                    break
                _reply(stream, request, "PASS")
                passed_phases.append(request["phase"])

    result = child.wait()
    if result == 0 and passed_phases != expected_phases:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "privileged_child_skipped_source_admission",
            file=sys.stderr)
        return 2
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validated-source", required=True)
    parser.add_argument("--qualification-report", required=True)
    parser.add_argument("--swapzctl", default="/usr/local/sbin/swapzctl")
    parser.add_argument("--oracle", default=os.fspath(DEFAULT_ORACLE))
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--workload-mib", type=int, default=384)
    parser.add_argument("--resident-mib", type=int, default=128)
    parser.add_argument("--swap-limit-mib", type=int, default=384)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    return parser


def _child_arguments(arguments: argparse.Namespace,
                     socket_path: Path,
                     parent_uid: int,
                     python3: str) -> list[str]:
    return [
        python3, "-B", os.fspath(PRIVILEGED_HELPER),
        "--validated-source", arguments.validated_source,
        "--qualification-report", arguments.qualification_report,
        "--swapzctl", arguments.swapzctl,
        "--oracle", arguments.oracle,
        "--cycles", str(arguments.cycles),
        "--workload-mib", str(arguments.workload_mib),
        "--resident-mib", str(arguments.resident_mib),
        "--swap-limit-mib", str(arguments.swap_limit_mib),
        "--timeout-seconds", str(arguments.timeout_seconds),
        "--source-admission-socket", os.fspath(socket_path),
        "--source-admission-parent-uid", str(parent_uid),
    ]


def main() -> int:
    arguments = _build_parser().parse_args()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=GitHub-hosted_CI",
            file=sys.stderr)
        return 2
    if os.geteuid() == 0:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "source_admission_parent_must_be_unprivileged",
            file=sys.stderr)
        return 2
    if not 2 <= arguments.cycles <= MAX_CYCLES:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=cycles_must_be_2_to_4",
            file=sys.stderr)
        return 2
    if not 60 <= arguments.timeout_seconds <= 600:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "timeout_must_be_60_to_600_seconds",
            file=sys.stderr)
        return 2

    try:
        _check_git_source(arguments.validated_source)
        sudo = _trusted_executable("sudo")
        python3 = _trusted_executable("python3")
        true = _trusted_executable("true")
        probe = subprocess.run(
            [sudo, "-n", "--", true],
            cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10)
        if probe.returncode != 0:
            raise Blocked(
                "noninteractive root privilege is unavailable")
        with tempfile.TemporaryDirectory(
                prefix="swapz-real-swap-admission-") as directory:
            parent_uid = os.geteuid()
            admission_directory = Path(directory)
            os.chmod(admission_directory, 0o700)
            socket_path = admission_directory / "source-admission.sock"
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(os.fspath(socket_path))
                os.chmod(socket_path, 0o600)
                server.listen(1)
                child = subprocess.Popen(
                    [sudo, "-n", "--", *_child_arguments(
                        arguments, socket_path, parent_uid, python3)],
                    cwd=ROOT)
                return _serve_admission(
                    server, child, arguments.validated_source,
                    arguments.cycles)
    except Blocked as exc:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
            file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            f"admission_runtime_error:{type(exc).__name__}",
            file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
