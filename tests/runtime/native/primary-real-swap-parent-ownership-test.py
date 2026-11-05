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
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "tests/tools/qualify-primary-real-swap-parent.py"
SPEC = importlib.util.spec_from_file_location("swapz_source_parent_ownership", PARENT)
parent = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = parent
SPEC.loader.exec_module(parent)


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

if __name__ == "__main__":
    unittest.main()
