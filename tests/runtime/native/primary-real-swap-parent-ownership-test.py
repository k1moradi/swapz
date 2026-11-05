#!/usr/bin/env python3
"""Rootless adversarial process/run binding for the physical source parent."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import struct
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "tests/tools/qualify-primary-real-swap-parent.py"
SPEC = importlib.util.spec_from_file_location("swapz_source_parent_ownership", PARENT)
parent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parent
SPEC.loader.exec_module(parent)
CLIENT_HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
CLIENT_SPEC = importlib.util.spec_from_file_location(
    "swapz_source_child_ownership", CLIENT_HELPER)
client_helper = importlib.util.module_from_spec(CLIENT_SPEC)
sys.modules[CLIENT_SPEC.name] = client_helper
CLIENT_SPEC.loader.exec_module(client_helper)


class SourceAdmissionPeerOwnership(unittest.TestCase):
    SOURCE = "a" * 40
    HELPER_DIGEST = "8" * 64
    ORACLE_DIGEST = "d" * 64

    class Stream:
        def __init__(self, requests):
            self.input = io.BytesIO(b"".join(
                json.dumps(record, sort_keys=True).encode("ascii") + b"\n"
                for record in requests))
            self.output = io.BytesIO()

        def readline(self, limit):
            return self.input.readline(limit)

        def write(self, data):
            return self.output.write(data)

        def flush(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def responses(self):
            return [json.loads(record) for record in self.output.getvalue().splitlines()]

    def setUp(self):
        self.source_hashes = {
            path: "c" * 64 for path in parent.PHYSICAL_CONTROL_INPUT_PATHS
        }

    def request(self, phase, nonce="b" * 32):
        return {
            "schema": parent.SOURCE_ADMISSION_SCHEMA,
            "source_sha": self.SOURCE,
            "phase": phase,
            "nonce": nonce,
            "physical_control_inputs_sha256": self.source_hashes,
            "executed_helper_sha256": self.HELPER_DIGEST,
        }

    def run_exchange(self, peer_pid, requests, *, child=None, git_check=None):
        stream = self.Stream(requests)
        connection = mock.MagicMock()
        # Kernel-returned SO_PEERCRED is modeled, not spoofed on a live socket.
        # No real root peer or privileged operation is ever created.
        connection.getsockopt.return_value = struct.pack("3i", peer_pid, 0, 0)
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = connection, None
        if child is None:
            child = mock.Mock()
            child.pid = os.getpid()
            child.poll.return_value = None
            child.wait.return_value = 2
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), mock.patch.object(
                parent, "_check_git_source", side_effect=git_check) as check:
            try:
                result = parent._serve_admission(
                    server, child, self.SOURCE, "/usr/bin/git",
                    self.ORACLE_DIGEST, self.source_hashes,
                    self.HELPER_DIGEST, 2)
            except parent.Blocked:
                result = 2
        return result, stream.responses(), stderr.getvalue(), child, check

    def test_unrelated_root_uid_peer_cannot_receive_initial_approval(self):
        result, responses, diagnostic, child, check = self.run_exchange(
            os.getppid(), [self.request("initial")])
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        check.assert_not_called()
        child.terminate.assert_called_once_with()
        self.assertIn("observed=unrelated_peer_run", diagnostic)

    def test_source_only_initial_request_is_not_authorization(self):
        result, responses, diagnostic, _child, check = self.run_exchange(
            os.getpid(), [self.request("initial", "1" * 32)])
        self.assertEqual(result, 2)
        self.assertEqual([response["status"] for response in responses],
                         ["BLOCKED"])
        self.assertEqual(responses[0]["reason"],
                         "physical_admission_identity_missing")
        self.assertIn(
            "observed=source_connection_peer_phase_control_inputs_only",
            diagnostic)
        self.assertIn("authorization=BLOCKED", diagnostic)
        self.assertEqual(check.call_count, 1)

    def test_source_change_precedes_identity_missing_refusal(self):
        result, responses, diagnostic, _child, check = self.run_exchange(
            os.getpid(), [self.request("initial")],
            git_check=parent.Blocked("production source tree is not clean"))
        self.assertEqual(result, 2)
        self.assertEqual([response["status"] for response in responses],
                         ["BLOCKED"])
        self.assertEqual(
            responses[0]["reason"], "production source tree is not clean")
        self.assertNotIn("physical_admission_identity:", diagnostic)
        self.assertEqual(check.call_count, 1)

    def test_reordered_phase_is_rejected(self):
        result, responses, _diagnostic, _child, check = self.run_exchange(
            os.getpid(), [self.request("cycle-1")])
        self.assertEqual(result, 2)
        self.assertEqual([response["status"] for response in responses],
                         ["BLOCKED"])
        check.assert_not_called()

    def test_delayed_git_query_cannot_approve_exited_owned_child(self):
        child = mock.Mock()
        child.pid = os.getpid()
        child.poll.return_value = None
        child.wait.return_value = 2

        def child_exits_during_git(*_args):
            child.poll.return_value = 7

        result, responses, diagnostic, _child, check = self.run_exchange(
            os.getpid(), [self.request("initial")],
            child=child, git_check=child_exits_during_git)
        self.assertEqual(result, 2)
        self.assertEqual(check.call_count, 1)
        self.assertEqual([response["status"] for response in responses],
                         ["BLOCKED"])
        self.assertIn("observed=launched_child_exited", diagnostic)
        self.assertIn("child_exit=7", diagnostic)

    def test_peer_process_identity_change_during_git_query_blocks(self):
        owned_lineage = ((os.getpid(), os.getppid(), 100),)
        replacement_lineage = ((os.getpid(), os.getppid(), 101),)
        with mock.patch.object(parent, "_owned_peer_process_lineage",
                               side_effect=[owned_lineage, owned_lineage,
                                            replacement_lineage]):
            result, responses, diagnostic, _child, check = self.run_exchange(
                os.getpid(), [self.request("initial")])
        self.assertEqual(result, 2)
        self.assertEqual(check.call_count, 1)
        self.assertEqual([response["status"] for response in responses],
                         ["BLOCKED"])
        self.assertIn("observed=changed_peer_run", diagnostic)

    @unittest.skipIf(os.geteuid() == 0, "real root peer forbidden")
    def test_unix_socket_peer_credential_is_kernel_provided(self):
        # SO_PEERCRED identifies the connection peer; it is not proof that the
        # same process later writes through a transferred/shared descriptor.
        first, second = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with first, second:
            credentials = second.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            process_id, peer_uid, _peer_gid = struct.unpack("3i", credentials)
        self.assertEqual(process_id, os.getpid())
        self.assertEqual(peer_uid, os.geteuid())


    @unittest.skipIf(os.geteuid() == 0, "rootless process proof requires non-root")
    def test_live_owned_subprocess_lineage_and_exited_run_refusal(self):
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            observed = parent._owned_peer_process_lineage(
                child, child.pid, "initial")
            self.assertEqual(observed[0][0], child.pid)
            self.assertEqual(observed[0][1], os.getpid())
            self.assertGreater(observed[0][2], 0)
            self.assertEqual(
                parent._owned_peer_process_lineage(child, child.pid, "initial"),
                observed)
            child.terminate()
            child.wait(timeout=5)
            with self.assertRaisesRegex(
                    parent.Blocked, "observed=launched_child_exited"):
                parent._owned_peer_process_lineage(child, child.pid, "initial")
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    @unittest.skipIf(os.geteuid() == 0, "rootless socket proof requires non-root")
    def test_shared_socket_descriptor_does_not_authenticate_message_writer(self):
        # This models an inherited/shared fd, not forged UID-0 credentials.
        # SO_PEERCRED names the socketpair creator after a different PID writes.
        connector, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with connector, receiver:
            credential_size = struct.calcsize("3i")
            credentials_before = receiver.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, credential_size)
            writer = subprocess.Popen(
                [sys.executable, "-I", "-c",
                 "import socket,sys; "
                 "socket.socket(fileno=int(sys.argv[1])).sendall(b'foreign-writer')",
                 str(connector.fileno())],
                pass_fds=(connector.fileno(),),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            try:
                receiver.settimeout(5)
                self.assertEqual(receiver.recv(32), b"foreign-writer")
                self.assertEqual(writer.wait(timeout=5), 0)
            finally:
                if writer.poll() is None:
                    writer.kill()
                writer.wait(timeout=5)
            credentials_after = receiver.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, credential_size)
            authenticated_pid, authenticated_uid, _gid = struct.unpack(
                "3i", credentials_after)
            self.assertEqual(credentials_after, credentials_before)
            self.assertEqual(authenticated_pid, os.getpid())
            self.assertEqual(authenticated_uid, os.geteuid())
            self.assertNotEqual(authenticated_pid, writer.pid)

    @unittest.skipIf(os.geteuid() == 0, "rootless cleanup proof requires non-root")
    def test_closed_listener_reaps_owned_subprocess_without_admission(self):
        # Closing the listener after launch makes settimeout fail with EBADF.
        # The original exception must survive successful bounded child cleanup.
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.close()
        try:
            with self.assertRaisesRegex(
                    parent.Blocked,
                    "source admission socket failed before privileged peer admission"):
                parent._serve_admission(
                    listener, child, self.SOURCE, "/usr/bin/git",
                    self.ORACLE_DIGEST, self.source_hashes,
                    self.HELPER_DIGEST, 2)
            self.assertIsNotNone(child.poll())
            self.assertIsInstance(child.wait(timeout=5), int)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    @unittest.skipIf(os.geteuid() == 0, "rootless cleanup proof requires non-root")
    def test_malformed_private_message_reaps_real_child_and_redacts_payload(self):
        # The fake UID-0 credential only isolates parser/cleanup behavior; it
        # does not simulate privileged peer authentication on a live socket.
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        private_marker = "private-channel-content-must-not-escape"
        stream = self.Stream([])
        stream.input = io.BytesIO(
            ('{"private":"' + private_marker + '","private":"duplicate"}\n'
             ).encode("ascii"))
        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", child.pid, 0, 0)
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = connection, None
        diagnostics = io.StringIO()
        try:
            with contextlib.redirect_stderr(diagnostics), mock.patch.object(
                    parent, "_check_git_source") as check:
                result = parent._serve_admission(
                    server, child, self.SOURCE, "/usr/bin/git",
                    self.ORACLE_DIGEST, self.source_hashes,
                    self.HELPER_DIGEST, 2)
            self.assertEqual(result, 2)
            self.assertFalse(stream.responses())
            self.assertIsNotNone(child.poll())
            self.assertIn("source admission request is malformed",
                          diagnostics.getvalue())
            self.assertIn("owned_cleanup=complete", diagnostics.getvalue())
            self.assertNotIn(private_marker, diagnostics.getvalue())
            check.assert_not_called()
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    @unittest.skipIf(os.geteuid() == 0, "rootless cleanup proof requires non-root")
    def test_bounded_kill_fallback_reaps_actual_sigterm_resistant_child(self):
        child = subprocess.Popen(
            [sys.executable, "-I", "-c",
             "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
             "print('ready',flush=True); time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        real_wait = child.wait
        observed_timeouts = []

        def bounded_wait(*, timeout):
            observed_timeouts.append(timeout)
            if timeout == 10:
                # Force the timeout edge without making the rootless suite
                # spend ten seconds waiting for the ignored SIGTERM.
                raise subprocess.TimeoutExpired(child.args, timeout)
            return real_wait(timeout=timeout)

        try:
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            self.assertEqual(child.stdout.readline(), b"ready\n")
            with mock.patch.object(child, "wait", side_effect=bounded_wait):
                parent._stop_unadmitted_child(child)
            self.assertEqual(observed_timeouts, [10, 5])
            self.assertEqual(child.returncode, -signal.SIGKILL)
        finally:
            if child.poll() is None:
                child.kill()
            real_wait(timeout=5)
            child.stdout.close()

    @unittest.skipIf(os.geteuid() == 0, "rootless process proof requires non-root")
    def test_marked_child_exit_observation_preserves_group_leader_until_cleanup(self):
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import sys; sys.exit(7)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        setattr(child, "_swapz_owned_process_group", child.pid)
        try:
            deadline = time.monotonic() + 5
            observed = None
            while observed is None and time.monotonic() < deadline:
                observed = parent._child_exit_status(child)
                if observed is None:
                    time.sleep(0.01)
            self.assertEqual(observed, 7)
            self.assertIsNone(child.returncode)
            self.assertTrue(Path(f"/proc/{child.pid}").exists())
            parent._stop_unadmitted_child(child)
            self.assertEqual(child.returncode, 7)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)

    @unittest.skipIf(os.geteuid() == 0, "rootless cleanup proof requires non-root")
    @unittest.skipUnless(
        hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
        "safe descendant cleanup requires Linux pidfd support")
    def test_owned_process_group_cleanup_reaps_descendant(self):
        child_source = (
            "import subprocess,sys,time\n"
            "descendant = subprocess.Popen([sys.executable, '-I', '-c', "
            "\"import signal,time; signal.signal(signal.SIGTERM, "
            "signal.SIG_IGN); print('ready', flush=True); time.sleep(60)\"], "
            "stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, "
            "stderr=subprocess.DEVNULL, text=True)\n"
            "assert descendant.stdout.readline() == 'ready\\n'\n"
            "print(descendant.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", child_source],
            start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        setattr(child, "_swapz_owned_process_group", child.pid)
        descendant_pidfd = None
        try:
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            descendant_pid = int(child.stdout.readline().strip())
            self.assertIsNone(child.poll())
            self.assertEqual(os.getpgid(descendant_pid), child.pid)
            # Keep an ownership-bound kernel reference before production cleanup
            # can reap the session leader. The finalizer must never signal a
            # possibly recycled numeric PID or process-group ID.
            descendant_pidfd = os.pidfd_open(descendant_pid)
            parent._stop_unadmitted_child(child)
            self.assertIsNotNone(child.returncode)
            self.assertFalse(Path(f"/proc/{descendant_pid}").exists())
            with self.assertRaises(ProcessLookupError):
                os.killpg(child.pid, 0)
        finally:
            # Group signaling is safe only while the actual session leader is
            # still live and therefore reserves the process-group number.
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if descendant_pidfd is not None:
                try:
                    signal.pidfd_send_signal(
                        descendant_pidfd, signal.SIGKILL, None, 0)
                except ProcessLookupError:
                    pass
                finally:
                    os.close(descendant_pidfd)
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdout.close()

    def test_privileged_child_launch_creates_private_session(self):
        arguments = parent._build_parser().parse_args([
            "--validated-source", self.SOURCE,
            "--qualification-report", "/tmp/report.json",
        ])
        read_descriptor, write_descriptor = os.pipe()
        source_pipe = os.fdopen(write_descriptor, "wb", buffering=0)
        child = mock.Mock(stdin=source_pipe)
        child.poll.return_value = None
        try:
            with mock.patch.object(
                    parent.subprocess, "Popen", return_value=child) as popen:
                observed = parent._start_privileged_child(
                    "/usr/bin/sudo", "/usr/bin/python3", arguments,
                    Path("/tmp/admission.sock"), 1000,
                    b"x", self.HELPER_DIGEST)
            self.assertIs(observed, child)
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            self.assertEqual(os.read(read_descriptor, 2), b"x")
        finally:
            os.close(read_descriptor)

    def test_replayed_initial_nonce_cannot_reuse_source_observation(self):
        repeated = self.request("initial", "1" * 32)
        result, responses, diagnostics, _child, check = self.run_exchange(
            os.getpid(), [repeated, repeated])
        self.assertEqual(result, 2)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["phase"], "initial")
        self.assertEqual(responses[0]["nonce"], repeated["nonce"])
        self.assertEqual(responses[0]["status"], "BLOCKED")
        self.assertEqual(responses[0]["reason"],
                         "physical_admission_identity_missing")
        self.assertIn("authorization=BLOCKED", diagnostics)
        self.assertEqual(check.call_count, 1)


@unittest.skipIf(os.geteuid() == 0, "live AF_UNIX parent proof requires non-root")
class SourceAdmissionClientPeerProof(unittest.TestCase):
    """Real, unprivileged kernel credentials; no simulated root or swap I/O."""

    SOURCE = "a" * 40
    ORACLE = "d" * 64
    CLIENT = r"""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("swapz_client_proof", sys.argv[2])
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)
client = None
try:
    client = helper.SourceAdmissionClient(
        sys.argv[1], os.geteuid(), "a" * 40)
    print("CONNECTED", flush=True)
    if sys.stdin.readline() != "GO\n":
        raise RuntimeError("missing synthetic gate")
    client.bind_physical_control_inputs({
        name: "c" * 64 for name in helper.PHYSICAL_CONTROL_INPUT_PATHS})
    client.bind_executed_helper_sha256("8" * 64)
    if sys.argv[3] == "changed_start":
        genuine_ancestors = helper._source_parent_ancestors
        def changed_start_time(phase):
            current = list(genuine_ancestors(phase))
            process_id, parent_id, ticks = current[0]
            current[0] = process_id, parent_id, ticks + 1
            return tuple(current)
        helper._source_parent_ancestors = changed_start_time
    try:
        digest = client.require("initial")
        print("SYNTHETIC_APPROVED" if digest == "d" * 64
              else "WRONG_ORACLE", flush=True)
    except helper.Blocked as exc:
        print("BLOCKED=" + str(exc), flush=True)
except helper.Blocked as exc:
    print("BLOCKED=" + str(exc), flush=True)
finally:
    if client is not None:
        client.close()
"""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="swapz-parent-peer-")
        self.addCleanup(temporary.cleanup)
        self.socket_path = Path(temporary.name) / "source-admission.sock"
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(self.server.close)
        self.server.bind(os.fspath(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        self.server.listen(1)
        self.server.settimeout(5)

    @staticmethod
    def _reap(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                stream.close()

    def _start_client(self, mode="normal"):
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", self.CLIENT,
             os.fspath(self.socket_path), os.fspath(CLIENT_HELPER), mode],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self.addCleanup(self._reap, child)
        self.assertTrue(select.select([child.stdout], [], [], 5)[0])
        self.assertEqual(child.stdout.readline().strip(), "CONNECTED")
        return child

    def _read_request(self, connection):
        request = bytearray()
        while b"\n" not in request:
            fragment = connection.recv(4096)
            self.assertTrue(fragment, "client exited before request")
            request.extend(fragment)
            self.assertLessEqual(len(request), 4096)
        request_line, separator, remainder = request.partition(b"\n")
        self.assertEqual(separator, b"\n")
        self.assertFalse(remainder)
        return json.loads(request_line.decode("ascii"))

    def _response(self, request):
        return {
            "schema": request["schema"], "status": "PASS",
            "phase": request["phase"], "nonce": request["nonce"],
            "source_sha": request["source_sha"],
            "oracle_sha256": self.ORACLE,
        }

    @staticmethod
    def _finish(child):
        assert select.select([child.stdout], [], [], 5)[0]
        line = child.stdout.readline().strip()
        assert child.wait(timeout=5) == 0, "unexpected client process failure"
        return line

    def _assert_refusal(self, result, phase, check, observed):
        self.assertTrue(result.startswith("BLOCKED="), result)
        for field in (
                f"phase={phase}", f"check={check}",
                "expected=live_ancestor_pid_starttime_uid_socket_inode_reply_sender",
                f"observed={observed}", "errno=none", "authorization=BLOCKED",
                "next=inspect_parent_identity_read_only"):
            self.assertIn(field, result)

    def test_published_source_bound_substitution_reproducer(self):
        probe_path = ROOT / (
            "tests/runtime/native/rootless-socket-substitution-probe.py")
        result = subprocess.run(
            [sys.executable, "-B", os.fspath(probe_path)],
            stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[:300])
        summary = json.loads(result.stdout)
        self.assertEqual(summary["runs"], 12)
        self.assertEqual(summary["substitution"], 12)
        self.assertEqual(
            summary["first_failed_authenticity_invariant"], "parent_ancestry")
        self.assertEqual(summary["genuine_parent_connections"], 0)

    def test_real_parent_can_send_nonce_bound_synthetic_approval(self):
        for _ in range(3):
            with self.subTest(repetition=_):
                # One client per socket connection; a successful response is
                # source-only test data, never physical run authorization.
                child = self._start_client()
                with self.server.accept()[0] as connection:
                    connection.settimeout(5)
                    child.stdin.write("GO\n")
                    child.stdin.flush()
                    request = self._read_request(connection)
                    self.assertEqual(request["phase"], "initial")
                    response = self._response(request)
                    connection.sendall(
                        (json.dumps(response) + "\n").encode("ascii"))
                    self.assertEqual(self._finish(child), "SYNTHETIC_APPROVED")

    def test_shared_fd_foreign_writer_cannot_authorize(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            original_credentials = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            child.stdin.write("GO\n")
            child.stdin.flush()
            request = self._read_request(connection)
            response = (json.dumps(self._response(request)) + "\n").encode("ascii")
            writer = subprocess.Popen(
                [sys.executable, "-I", "-c",
                 "import socket,sys; socket.socket(fileno=int(sys.argv[1]))"
                 ".sendall(bytes.fromhex(sys.argv[2]))",
                 str(connection.fileno()), response.hex()],
                pass_fds=(connection.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertEqual(writer.wait(timeout=5), 0)
            finally:
                if writer.poll() is None:
                    writer.kill()
                writer.wait(timeout=5)
            self.assertEqual(
                connection.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED,
                    struct.calcsize("3i")), original_credentials)
            self._assert_refusal(
                self._finish(child), "initial",
                "reply_sender", "foreign_message_sender")

    def test_exchanged_socket_inode_blocks_before_request(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            self.socket_path.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as swapped:
                swapped.bind(os.fspath(self.socket_path))
                os.chmod(self.socket_path, 0o600)
                swapped.listen(1)
                child.stdin.write("GO\n")
                child.stdin.flush()
                self._assert_refusal(
                    self._finish(child), "initial",
                    "socket_identity", "exchanged_socket_inode")
                self.assertEqual(connection.recv(1), b"")

    def test_malformed_authorization_reply_blocks(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            child.stdin.write("GO\n")
            child.stdin.flush()
            self._read_request(connection)
            connection.sendall(b'{"status":"PASS","status":"PASS"}\n')
            self._assert_refusal(
                self._finish(child), "initial",
                "reply_parser", "malformed_authorization_reply")

    def test_wrong_nonce_cannot_authorize(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            child.stdin.write("GO\n")
            child.stdin.flush()
            request = self._read_request(connection)
            response = self._response(request)
            response["nonce"] = "f" * 32
            connection.sendall(
                (json.dumps(response) + "\n").encode("ascii"))
            self._assert_refusal(
                self._finish(child), "initial",
                "reply_fields", "mismatched_authorization_reply")

    def test_parent_start_time_change_blocks(self):
        child = self._start_client(mode="changed_start")
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            child.stdin.write("GO\n")
            child.stdin.flush()
            self._assert_refusal(
                self._finish(child), "initial",
                "parent_ancestry", "changed_parent_process")
            self.assertEqual(connection.recv(1), b"")

    def test_reply_eof_blocks(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            child.stdin.write("GO\n")
            child.stdin.flush()
            self._read_request(connection)
            connection.shutdown(socket.SHUT_WR)
            self._assert_refusal(
                self._finish(child), "initial",
                "reply_transport", "parent_disconnected")

    def test_closed_pinned_parent_pidfd_blocks_reused_pid(self):
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            pidfd = os.pidfd_open(child.pid)
            try:
                child.terminate()
                child.wait(timeout=5)
                with self.assertRaises(client_helper.Blocked) as refusal:
                    client_helper._source_parent_pidfd_alive(pidfd, "initial")
                self.assertIn("check=parent_liveness", str(refusal.exception))
                self.assertIn("observed=exited_parent_process",
                              str(refusal.exception))
                self.assertIn("authorization=BLOCKED",
                              str(refusal.exception))
            finally:
                os.close(pidfd)
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
