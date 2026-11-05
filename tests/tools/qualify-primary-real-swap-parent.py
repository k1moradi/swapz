#!/usr/bin/env python3
"""Unprivileged admission parent for private physical real-swap qualification.

This parent owns every Git/remote-main source decision. It performs no block,
Device Mapper, swap, module, or lifecycle mutation. The privileged child must
request a fresh authenticated approval immediately before each physical cycle
and again before a PASS can be emitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PRIVILEGED_HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
DEFAULT_ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"
CANONICAL_REMOTE_URL = "https://github.com/k1moradi/swapz.git"
SOURCE_ADMISSION_SCHEMA = "swapz-primary-real-swap-admission-v1"
PHYSICAL_CONTROL_INPUT_PATHS = (
    "src/kernel/VERSION",
    "src/kernel/authority.h",
    "src/kernel/codec.h",
    "src/kernel/superblock.h",
    "src/kernel/swapz-build-info.h",
    "src/userspace/swapz-primary.h",
    "src/userspace/swapz-primary.c",
    "src/userspace/swapzctl.c",
    "docs/production-acceptance.json",
    "docs/handoff/production-readiness.json",
)
MAX_LINE_BYTES = 4096
MAX_COMMIT_SOURCE_INPUT_BYTES = 16 * 1024 * 1024
MAX_CYCLES = 4
SAFE_COMMAND_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
PRIVILEGED_HELPER_BOOTSTRAP = (
    "import sys\n"
    "path = sys.argv[1]\n"
    "source_root = sys.argv[2]\n"
    "sys.argv = [path, *sys.argv[3:]]\n"
    "source = sys.stdin.buffer.read()\n"
    "namespace = {"
    "'__name__': '__main__', '__file__': path, "
    "'__package__': None, '__cached__': None, "
    "'__swapz_source_root__': source_root}\n"
    "exec(compile(source, path, 'exec'), namespace, namespace)\n"
)


class Blocked(RuntimeError):
    pass


def _source_command_environment() -> dict[str, str]:
    return {
        "LC_ALL": "C",
        "LANG": "C",
        "PATH": SAFE_COMMAND_PATH,
        "HOME": "/",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def _run(command: list[str], *, check: bool = True,
         timeout: int = 30, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True,
        check=False, timeout=timeout, env=_source_command_environment())
    if check and result.returncode != 0:
        raise Blocked(
            "source admission command failed:"
            f"command={Path(command[0]).name}:exit_status={result.returncode}:"
            "next=verify_source_provenance_and_retry")
    return result


def _check_git_source(validated_source: str, git: str | None = None) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", validated_source):
        raise Blocked("validated source must be one full lowercase SHA")
    git = _trusted_executable("git") if git is None else git
    head = _run([git, "rev-parse", "HEAD"], timeout=10).stdout.strip()
    branch = _run(
        [git, "rev-parse", "--abbrev-ref", "HEAD"],
        timeout=10).stdout.strip()
    origin_main = _run(
        [git, "rev-parse", "--verify", "refs/remotes/origin/main"],
        timeout=10).stdout.strip()
    if head != validated_source:
        raise Blocked(
            f"checkout HEAD {head} differs from validated source "
            f"{validated_source}")
    if branch != "main" or origin_main != validated_source:
        raise Blocked(
            "physical qualification requires main == origin/main == "
            "validated source")
    if _run([git, "status", "--porcelain"], timeout=10).stdout:
        raise Blocked("production source tree is not clean")
    remote_main = _run(
        [git, "ls-remote", "--exit-code",
         CANONICAL_REMOTE_URL, "refs/heads/main"],
        check=False, timeout=30, cwd=Path("/"))
    if remote_main.returncode != 0:
        raise Blocked(
            "cannot verify the current remote main for physical qualification:"
            f"exit_status={remote_main.returncode}:next=check_remote_and_retry")
    expected_remote_main = f"{validated_source}\trefs/heads/main"
    observed_remote_output = remote_main.stdout.strip()
    if observed_remote_output != expected_remote_main:
        remote_match = re.fullmatch(
            r"([0-9a-f]{40})\trefs/heads/main", observed_remote_output)
        observed_remote = remote_match.group(1) if remote_match else "invalid"
        raise Blocked(
            "current remote main differs from the validated source:"
            f"expected={validated_source}:observed={observed_remote}:"
            "next=sync_main_and_retry")

    # The remote query can be the longest source probe. Re-read local identity
    # afterwards so movement while that query is in flight cannot be admitted.
    final_head = _run([git, "rev-parse", "HEAD"], timeout=10).stdout.strip()
    final_branch = _run(
        [git, "rev-parse", "--abbrev-ref", "HEAD"],
        timeout=10).stdout.strip()
    final_origin_main = _run(
        [git, "rev-parse", "--verify", "refs/remotes/origin/main"],
        timeout=10).stdout.strip()
    if (final_head != validated_source or final_branch != "main" or
            final_origin_main != validated_source):
        observed_head = (
            final_head if re.fullmatch(r"[0-9a-f]{40}", final_head) else "invalid")
        observed_origin_main = (
            final_origin_main if re.fullmatch(r"[0-9a-f]{40}", final_origin_main)
            else "invalid")
        raise Blocked(
            "source_local_identity_changed:boundary=post_remote:"
            f"expected={validated_source}:head={observed_head}:"
            f"branch={'main' if final_branch == 'main' else 'other'}:"
            f"origin_main={observed_origin_main}:next=sync_main_and_retry")


def _git_file_bytes(validated_source: str, path: Path,
                    git: str | None = None) -> bytes:
    """Read exact file bytes from the validated commit object."""
    try:
        relative_path = path.relative_to(ROOT)
    except ValueError as exc:
        raise Blocked("source admission file is outside the repository") from exc
    if not relative_path.parts or any(
            part in {"", ".", ".."} for part in relative_path.parts):
        raise Blocked("source admission file path is not canonical")
    relative = relative_path.as_posix()
    git = _trusted_executable("git") if git is None else git
    object_spec = f"{validated_source}:{relative}"
    try:
        size_result = subprocess.run(
            [git, "cat-file", "-s", object_spec],
            cwd=ROOT, capture_output=True, check=False, timeout=10,
            env=_source_command_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise Blocked(
            "cannot inspect source admission file in validated commit") from exc
    if size_result.returncode != 0:
        raise Blocked("validated commit lacks required source admission file")
    try:
        size_text = size_result.stdout.decode("ascii").strip()
        expected_size = int(size_text, 10)
    except (UnicodeError, ValueError) as exc:
        raise Blocked("validated commit source admission size is malformed") from exc
    if expected_size < 0 or expected_size > MAX_COMMIT_SOURCE_INPUT_BYTES:
        raise Blocked("validated commit source admission input exceeds size boundary")
    try:
        result = subprocess.run(
            [git, "show", object_spec],
            cwd=ROOT, capture_output=True, check=False, timeout=10,
            env=_source_command_environment())
    except (OSError, subprocess.SubprocessError) as exc:
        raise Blocked("cannot read source admission file from validated commit") from exc
    if result.returncode != 0 or len(result.stdout) != expected_size:
        raise Blocked(
            "validated commit source admission file changed or read was incomplete")
    return result.stdout


def _git_file_sha256(validated_source: str, path: Path,
                     git: str | None = None) -> str:
    """Hash exact bytes from the validated commit, not the mutable worktree."""
    return hashlib.sha256(
        _git_file_bytes(validated_source, path, git)
    ).hexdigest()


def _trusted_executable(name: str) -> str:
    candidate = shutil.which(name, path=SAFE_COMMAND_PATH)
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


def _read_request(
        stream, validated_source: str,
        expected_physical_control_inputs_sha256: dict[str, str],
        expected_helper_sha256: str) -> dict:
    line = stream.readline(MAX_LINE_BYTES + 2)
    if not line:
        raise EOFError
    if len(line) > MAX_LINE_BYTES or not line.endswith(b"\n"):
        raise Blocked("source admission request is malformed")
    try:
        request = json.loads(
            line[:-1].decode("ascii"),
            object_pairs_hook=_unique_json_object)
    except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
        raise Blocked("source admission request is malformed") from exc
    required = {
        "schema", "phase", "source_sha", "nonce",
        "physical_control_inputs_sha256", "executed_helper_sha256",
    }
    source_hashes = (
        request.get("physical_control_inputs_sha256")
        if isinstance(request, dict) else None)
    hashes_valid = (
        isinstance(source_hashes, dict) and
        set(source_hashes) == set(PHYSICAL_CONTROL_INPUT_PATHS) and
        all(isinstance(source_hashes.get(path), str) and
            re.fullmatch(r"[0-9a-f]{64}", source_hashes[path]) is not None
            for path in PHYSICAL_CONTROL_INPUT_PATHS))
    nonce = request.get("nonce") if isinstance(request, dict) else None
    phase = request.get("phase") if isinstance(request, dict) else None
    if (not isinstance(request, dict) or set(request) != required or
            request.get("schema") != SOURCE_ADMISSION_SCHEMA or
            request.get("source_sha") != validated_source or
            not hashes_valid or
            source_hashes != expected_physical_control_inputs_sha256 or
            request.get("executed_helper_sha256") != expected_helper_sha256 or
            not isinstance(nonce, str) or
            re.fullmatch(r"[0-9a-f]{32}", nonce) is None or
            not isinstance(phase, str) or
            re.fullmatch(r"(?:initial|final|cycle-[1-4])", phase) is None):
        raise Blocked("source admission request identity is invalid")
    return request


def _reply(stream, request: dict, status: str,
           oracle_sha256: str, reason: str | None = None) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", oracle_sha256):
        raise Blocked("source admission oracle digest is malformed")
    response = {
        "schema": SOURCE_ADMISSION_SCHEMA,
        "status": status,
        "phase": request["phase"],
        "source_sha": request["source_sha"],
        "nonce": request["nonce"],
        "oracle_sha256": oracle_sha256,
    }
    if status == "BLOCKED":
        if not reason or not reason.isascii() or len(reason) > 256 or \
                any(ord(character) < 0x20 for character in reason):
            reason = "source_provenance_revalidation_failed"
        response["reason"] = reason
    stream.write(
        json.dumps(
            response, sort_keys=True, separators=(",", ":")).encode("ascii") +
        b"\n")
    stream.flush()


def _stop_unadmitted_child(child: subprocess.Popen) -> None:
    """Bound cleanup of a child that has not received initial admission."""
    if child.poll() is not None:
        return
    try:
        child.terminate()
    except ProcessLookupError:
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired as exc:
            raise Blocked(
                "unadmitted privileged qualifier could not be reaped") from exc
        return
    except OSError as exc:
        raise Blocked(
            "cannot terminate unadmitted privileged qualifier") from exc
    try:
        child.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        child.kill()
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise Blocked(
            "cannot kill unadmitted privileged qualifier") from exc
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise Blocked(
            "unadmitted privileged qualifier did not terminate after kill"
        ) from exc


def _stop_unadmitted_child_preserving(
        child: subprocess.Popen, original: Blocked) -> None:
    try:
        _stop_unadmitted_child(child)
    except Blocked as cleanup_error:
        raise Blocked(
            f"{original}; privileged child cleanup also failed: "
            f"{cleanup_error}") from cleanup_error


def _serve_admission(server: socket.socket,
                     child: subprocess.Popen,
                     validated_source: str,
                     git: str,
                     oracle_sha256: str,
                     physical_control_inputs_sha256: dict[str, str],
                     helper_sha256: str,
                     cycles: int) -> int:
    expected_phases = (
        ["initial"] +
        [f"cycle-{index}" for index in range(1, cycles + 1)] +
        ["final"])
    passed_phases: list[str] = []
    parent_rejected = False
    if re.fullmatch(r"[0-9a-f]{64}", oracle_sha256) is None:
        failure = Blocked("source admission oracle digest is malformed")
        _stop_unadmitted_child_preserving(child, failure)
        raise failure
    server.settimeout(30)
    try:
        connection, _address = server.accept()
    except socket.timeout as exc:
        failure = Blocked(
            "privileged qualifier did not establish source admission channel")
        _stop_unadmitted_child_preserving(child, failure)
        raise failure from exc
    except OSError as exc:
        failure = Blocked(
            "source admission socket failed before privileged peer admission")
        _stop_unadmitted_child_preserving(child, failure)
        raise failure from exc

    admission_boundary = "authenticated_channel"
    try:
        with connection:
            try:
                credentials = connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _peer_pid, peer_uid, _peer_gid = struct.unpack("3i", credentials)
            except (OSError, struct.error) as exc:
                failure = Blocked(
                    "cannot authenticate privileged source admission peer")
                _stop_unadmitted_child_preserving(child, failure)
                raise failure from exc
            if peer_uid != 0:
                failure = Blocked("source admission peer is not privileged")
                _stop_unadmitted_child_preserving(child, failure)
                raise failure
            try:
                stream_context = connection.makefile("rwb", buffering=0)
            except OSError as exc:
                failure = Blocked(
                    "cannot establish privileged source admission stream")
                _stop_unadmitted_child_preserving(child, failure)
                raise failure from exc
            with stream_context as stream:
                while True:
                    expected_phase = (
                        expected_phases[len(passed_phases)]
                        if len(passed_phases) < len(expected_phases) else None)
                    admission_boundary = expected_phase or "post-final"
                    try:
                        request = _read_request(
                            stream, validated_source,
                            physical_control_inputs_sha256, helper_sha256)
                    except EOFError:
                        break
                    except Blocked as exc:
                        parent_rejected = True
                        print(
                            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
                            file=sys.stderr)
                        break
                    if request["phase"] != expected_phase:
                        parent_rejected = True
                        _reply(stream, request, "BLOCKED", oracle_sha256,
                               "unexpected_source_admission_phase")
                        print(
                            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
                            "unexpected_source_admission_phase",
                            file=sys.stderr)
                        break
                    try:
                        _check_git_source(validated_source, git)
                    except Blocked as exc:
                        parent_rejected = True
                        _reply(stream, request, "BLOCKED", oracle_sha256, str(exc))
                        print(
                            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
                            file=sys.stderr)
                        break
                    _reply(stream, request, "PASS", oracle_sha256)
                    passed_phases.append(request["phase"])
    except (OSError, subprocess.SubprocessError) as exc:
        parent_rejected = True
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            f"source_admission_runtime_error:{admission_boundary}:"
            f"{type(exc).__name__}:"
            f"errno={exc.errno if isinstance(exc, OSError) and exc.errno is not None else 'none'}",
            file=sys.stderr)

    parent_stopped_child = False
    if not passed_phases and child.poll() is None:
        _stop_unadmitted_child(child)
        parent_stopped_child = True
    try:
        # Once the admission channel closes, no further phase can succeed.
        # Bound a stuck child so the parent does not lose terminal diagnostics.
        result = child.wait(timeout=45)
    except subprocess.TimeoutExpired as exc:
        failure = Blocked(
            "privileged qualifier abnormal teardown: child did not exit "
            "after source admission channel closed")
        _stop_unadmitted_child_preserving(child, failure)
        raise failure from exc
    if not parent_stopped_child and result not in {0, 1, 2}:
        detail = (
            f"terminated_by_signal:{-result}" if result < 0 else
            f"unexpected_exit_status:{result}")
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            f"privileged_qualifier_abnormal_teardown:{detail}",
            file=sys.stderr)
        return 2
    if parent_rejected:
        # A parent-owned source refusal is BLOCKED even when the child exits 1.
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            f"admission_refused:phase={admission_boundary}:child_exit={result}:"
            f"owned_cleanup={'complete' if parent_stopped_child else 'not_required'}",
            file=sys.stderr)
        return 2
    if not passed_phases:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "privileged_child_skipped_source_admission:"
            f"phase=initial:child_exit={result}:"
            f"owned_cleanup={'complete' if parent_stopped_child else 'not_required'}",
            file=sys.stderr)
        return 2
    cycle_admitted = any(phase.startswith("cycle-") for phase in passed_phases)
    if result == 1 and not cycle_admitted:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "privileged_qualifier_abnormal_teardown:"
            "failed_before_first_cycle_source_admission",
            file=sys.stderr)
        return 2
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
                     helper_sha256: str) -> list[str]:
    return [
        os.fspath(PRIVILEGED_HELPER),
        os.fspath(ROOT),
        "--validated-source", arguments.validated_source,
        "--executed-helper-sha256", helper_sha256,
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


def _start_privileged_child(
        sudo: str, python3: str, arguments: argparse.Namespace,
        socket_path: Path, parent_uid: int,
        helper_payload: bytes, helper_sha256: str) -> subprocess.Popen:
    command = [
        sudo, "-n", "--", python3, "-I", "-B", "-c",
        PRIVILEGED_HELPER_BOOTSTRAP,
        *_child_arguments(
            arguments, socket_path, parent_uid, helper_sha256),
    ]
    try:
        child = subprocess.Popen(
            command, cwd=ROOT, stdin=subprocess.PIPE,
            env=_source_command_environment())
    except OSError as exc:
        raise Blocked("cannot start commit-bound privileged qualifier") from exc
    if child.stdin is None:
        failure = Blocked("privileged qualifier source pipe is unavailable")
        _stop_unadmitted_child_preserving(child, failure)
        raise failure
    descriptor = child.stdin.fileno()
    deadline = time.monotonic() + 10.0
    offset = 0
    try:
        os.set_blocking(descriptor, False)
        while offset < len(helper_payload):
            if child.poll() is not None:
                raise OSError("privileged qualifier exited before source transfer")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    "privileged qualifier source transfer timed out")
            _readable, writable, _exceptional = select.select(
                [], [descriptor], [], min(0.1, remaining))
            if not writable:
                continue
            try:
                written = os.write(descriptor, helper_payload[offset:])
            except BlockingIOError:
                continue
            if written <= 0:
                raise OSError("short privileged qualifier source transfer")
            offset += written
        child.stdin.close()
    except (OSError, TimeoutError) as exc:
        # Do not disclose helper bytes, private argv or paths in a refusal.
        child_exit = child.poll()
        error_number = (
            exc.errno if isinstance(exc, OSError) and exc.errno is not None
            else "none")
        cause = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        failure = Blocked(
            "cannot stream commit-bound privileged qualifier source:"
            f"phase=helper_source_transfer:cause={cause}:"
            f"errno={error_number}:"
            f"child_exit={child_exit if child_exit is not None else 'running'}")
        try:
            child.stdin.close()
        except OSError:
            pass
        _stop_unadmitted_child_preserving(child, failure)
        raise Blocked(f"{failure}:owned_cleanup=complete") from exc
    return child


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
        git = _trusted_executable("git")
        _check_git_source(arguments.validated_source, git)
        helper_payload = _git_file_bytes(
            arguments.validated_source, PRIVILEGED_HELPER, git)
        helper_sha256 = hashlib.sha256(helper_payload).hexdigest()
        oracle_sha256 = _git_file_sha256(
            arguments.validated_source, DEFAULT_ORACLE, git)
        physical_control_inputs_sha256 = {
            relative: _git_file_sha256(
                arguments.validated_source, ROOT / relative, git)
            for relative in PHYSICAL_CONTROL_INPUT_PATHS
        }
        sudo = _trusted_executable("sudo")
        python3 = _trusted_executable("python3")
        true = _trusted_executable("true")
        probe = subprocess.run(
            [sudo, "-n", "--", true],
            cwd=ROOT, check=False, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10,
            env=_source_command_environment())
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
                child = _start_privileged_child(
                    sudo, python3, arguments, socket_path, parent_uid,
                    helper_payload, helper_sha256)
                return _serve_admission(
                    server, child, arguments.validated_source,
                    git, oracle_sha256, physical_control_inputs_sha256,
                    helper_sha256, arguments.cycles)
    except Blocked as exc:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=" + str(exc),
            file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            f"admission_runtime_error:{type(exc).__name__}:"
            f"errno={exc.errno if isinstance(exc, OSError) and exc.errno is not None else 'none'}:"
            "next=verify_source_admission_prerequisites",
            file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
