#!/usr/bin/env python3
"""Rootless adversarial process/run binding for the physical source parent."""

import contextlib
import errno
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

    def run_exchange(self, peer_pid, requests, *, child=None,
                     git_check=None, peer_uid=0,
                     peer_credentials_error=None, peer_pidfd_error=None,
                     peer_pidfd_exited=False):
        stream = self.Stream(requests)
        connection = mock.MagicMock()
        # Kernel-returned peer identity is modeled, not spoofed on a live
        # socket. A pipe supplies only pidfd-like poll lifetime semantics.
        peer_pidfd, peer_liveness_writer = os.pipe()
        if peer_pidfd_exited:
            os.close(peer_liveness_writer)
            peer_liveness_writer = None
        peer_pidfd_handed_off = False

        def get_socket_option(level, option, *_args):
            nonlocal peer_pidfd_handed_off
            self.assertEqual(level, socket.SOL_SOCKET)
            if option == socket.SO_PEERCRED:
                if peer_credentials_error is not None:
                    raise peer_credentials_error
                return struct.pack("3i", peer_pid, peer_uid, 0)
            if option == parent.SO_PEERPIDFD:
                if peer_pidfd_error is not None:
                    raise peer_pidfd_error
                peer_pidfd_handed_off = True
                return peer_pidfd
            raise AssertionError(f"unexpected socket option {option}")

        connection.getsockopt.side_effect = get_socket_option
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = connection, None
        if child is None:
            child = mock.Mock()
            child.pid = os.getpid()
            child.poll.return_value = None
            child.wait.return_value = 2
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr), mock.patch.object(
                    parent, "_check_git_source", side_effect=git_check) as check:
                try:
                    result = parent._serve_admission(
                        server, child, self.SOURCE, "/usr/bin/git",
                        self.ORACLE_DIGEST, self.source_hashes,
                        self.HELPER_DIGEST, 2)
                except parent.Blocked:
                    result = 2
        finally:
            if peer_liveness_writer is not None:
                os.close(peer_liveness_writer)
            if peer_pidfd_handed_off:
                with self.assertRaises(OSError) as closed:
                    os.fstat(peer_pidfd)
                self.assertEqual(closed.exception.errno, errno.EBADF)
            else:
                os.close(peer_pidfd)
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

    def test_matching_historical_device_labels_do_not_authorize_another_card(self):
        # Two different synthetic card/reader pairs intentionally collide on
        # every historical display field. The current wire schema has no field
        # that can distinguish them, so both source requests are identical.
        historical_display = {
            "partuuid": "a1b2c3d4", "major_minor": "8:1",
            "size_bytes": 32 * 1024**3, "model": "synthetic-reader-model",
        }
        synthetic_devices = (
            {"card": "synthetic-card-A", "reader": "synthetic-reader-A",
             "historical": historical_display},
            {"card": "synthetic-card-B", "reader": "synthetic-reader-B",
             "historical": dict(historical_display)},
        )
        self.assertEqual(
            synthetic_devices[0]["historical"],
            synthetic_devices[1]["historical"])
        self.assertNotEqual(
            (synthetic_devices[0]["card"], synthetic_devices[0]["reader"]),
            (synthetic_devices[1]["card"], synthetic_devices[1]["reader"]))

        source_requests = (
            self.request("initial", "1" * 32),
            self.request("initial", "1" * 32),
        )
        self.assertEqual(source_requests[0], source_requests[1])
        self.assertEqual(
            set(source_requests[0]),
            {"schema", "source_sha", "phase", "nonce",
             "physical_control_inputs_sha256", "executed_helper_sha256"})
        for forbidden_field in (
                "partuuid", "major_minor", "size_bytes", "model",
                "card_identity", "reader_identity",
                "owner_authorization_material"):
            self.assertNotIn(forbidden_field, source_requests[0])

        for device, request in zip(synthetic_devices, source_requests):
            with self.subTest(card=device["card"], reader=device["reader"]):
                result, responses, diagnostic, child, check = self.run_exchange(
                    os.getpid(), [request])
                self.assertEqual(result, 2)
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["status"], "BLOCKED")
                self.assertEqual(
                    responses[0]["reason"], "physical_admission_identity_missing")
                self.assertIn("physical_admission_identity:phase=initial",
                              diagnostic)
                self.assertIn(
                    "expected=source_exact_sender_run_phase_target_required_evidence",
                    diagnostic)
                self.assertIn(
                    "observed=source_connection_peer_phase_control_inputs_only",
                    diagnostic)
                self.assertIn("request_writer_identity=UNPROVEN", diagnostic)
                self.assertIn("owner_authorization_material=missing", diagnostic)
                self.assertIn("fresh_card_reader_identity=missing", diagnostic)
                self.assertIn("card_reader_identity=UNPROVEN", diagnostic)
                self.assertIn("physical=BLOCKED", diagnostic)
                self.assertIn("errno=none", diagnostic)
                self.assertIn("authorization=BLOCKED", diagnostic)
                self.assertNotIn("synthetic-card-", diagnostic)
                self.assertNotIn("synthetic-reader-", diagnostic)
                child.terminate.assert_called_once_with()
                self.assertEqual(check.call_count, 1)

    def test_untrusted_child_card_claim_fails_at_request_gate(self):
        # Child-supplied selectors, invented reader IDs and stale "tokens"
        # cannot extend the exact source-only wire schema into authorization.
        historical_display = {
            "partuuid": "a1b2c3d4", "major_minor": "8:1",
            "size_bytes": 32 * 1024**3, "model": "synthetic-reader-model",
        }
        untrusted_claims = (
            {"selected_device": dict(historical_display)},
            {"reader_serial": "synthetic-invented-serial"},
            {"reader_serial": "unknown"},
            {"immutable_authorization_token": "synthetic-stale-token"},
        )
        for claim in untrusted_claims:
            with self.subTest(field=next(iter(claim))):
                request = self.request("initial")
                request.update(claim)
                result, responses, diagnostic, _child, check = self.run_exchange(
                    os.getpid(), [request])
                self.assertEqual(result, 2)
                self.assertFalse(responses)
                self.assertIn("source admission request identity is invalid",
                              diagnostic)
                for field in (
                        "phase=request", "check=request_identity",
                        "expected=exact_source_only_schema",
                        "observed=mismatched_or_untrusted_request_identity",
                        "errno=none", "authorization=BLOCKED",
                        "next=inspect_source_admission_protocol_read_only"):
                    self.assertIn(field, diagnostic)
                self.assertNotIn("physical_admission_identity:", diagnostic)
                self.assertNotIn("synthetic-", diagnostic)
                check.assert_not_called()

    def test_untrusted_peer_uid_fails_before_source_request(self):
        result, responses, diagnostic, child, check = self.run_exchange(
            os.getpid(), [self.request("initial")], peer_uid=1000)
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        self.assertIn("source admission peer is not privileged", diagnostic)
        for field in (
                "phase=authenticated_channel", "check=peer_credentials",
                "expected=uid_0", "observed=nonprivileged_peer_uid",
                "errno=none", "authorization=BLOCKED",
                "next=inspect_child_ownership_read_only"):
            self.assertIn(field, diagnostic)
        self.assertNotIn("physical_admission_identity:", diagnostic)
        child.terminate.assert_called_once_with()
        check.assert_not_called()

    def test_peer_credential_read_error_preserves_original_errno(self):
        private_error = "private-synthetic-peer-credential-location"
        result, responses, diagnostic, child, check = self.run_exchange(
            os.getpid(), [self.request("initial")],
            peer_credentials_error=OSError(errno.EBADF, private_error))
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        for field in (
                "cannot authenticate privileged source admission peer",
                "phase=authenticated_channel", "check=peer_credentials",
                "expected=kernel_peer_credentials",
                "observed=unavailable_or_malformed_peer_credentials",
                f"errno={errno.EBADF}", "authorization=BLOCKED",
                "next=inspect_child_ownership_read_only"):
            self.assertIn(field, diagnostic)
        self.assertNotIn(private_error, diagnostic)
        self.assertNotIn("physical_admission_identity:", diagnostic)
        child.terminate.assert_called_once_with()
        check.assert_not_called()

    def test_peer_pidfd_error_preserves_original_errno(self):
        private_error = "private-synthetic-peer-pidfd-location"
        result, responses, diagnostic, child, check = self.run_exchange(
            os.getpid(), [self.request("initial")],
            peer_pidfd_error=OSError(errno.ENOPROTOOPT, private_error))
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        for field in (
                "source_admission_peer_identity:phase=authenticated_channel",
                "observed=unavailable_connection_peer_pidfd",
                f"errno={errno.ENOPROTOOPT}", "authorization=BLOCKED",
                "next=inspect_child_ownership_read_only"):
            self.assertIn(field, diagnostic)
        self.assertNotIn(private_error, diagnostic)
        child.terminate.assert_called_once_with()
        check.assert_not_called()

    def test_stale_so_peercred_pid_cannot_rebind_live_replacement(self):
        # The numeric PID and /proc lineage still look live, modeling reuse
        # after the original connection peer exited. The peer pidfd must win.
        result, responses, diagnostic, child, check = self.run_exchange(
            os.getpid(), [self.request("initial")],
            peer_pidfd_exited=True)
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        for field in (
                "source_admission_peer_identity:phase=authenticated_channel",
                "observed=exited_connection_peer", "errno=none",
                "authorization=BLOCKED",
                "next=inspect_child_ownership_read_only"):
            self.assertIn(field, diagnostic)
        child.terminate.assert_called_once_with()
        check.assert_not_called()

    def test_unavailable_peer_identity_preserves_original_errno(self):
        private_error = "private-synthetic-process-location"
        with mock.patch.object(
                parent.Path, "read_text",
                side_effect=FileNotFoundError(2, private_error)):
            result, responses, diagnostic, _child, check = self.run_exchange(
                os.getpid(), [self.request("initial")])
        self.assertEqual(result, 2)
        self.assertFalse(responses)
        self.assertIn(
            "source_admission_peer_identity:phase=authenticated_channel",
            diagnostic)
        self.assertIn("observed=unavailable_process_identity:errno=2",
                      diagnostic)
        self.assertIn("authorization=BLOCKED", diagnostic)
        self.assertNotIn(private_error, diagnostic)
        check.assert_not_called()

    def test_exited_peer_lineage_is_rejected(self):
        # A descriptor may survive its creator: cached SO_PEERCRED must not
        # authenticate an exited process, even with unchanged start ticks.
        launched_process_id = 32101
        peer_process_id = 32102
        launched_child = mock.Mock()
        launched_child.pid = launched_process_id
        launched_child.poll.return_value = None

        def process_stat(process_id, parent_process_id, state):
            stat_fields = (
                [state, str(parent_process_id), "0", str(launched_process_id)] +
                ["0"] * 15 + ["12345"])
            return f"{process_id} (synthetic-process) " + " ".join(stat_fields)

        launched_stat = process_stat(
            launched_process_id, os.getpid(), "S")

        def read_process_stat(path, encoding=None, errors=None):
            self.assertEqual(encoding, "ascii")
            self.assertIsNone(errors)
            return (
                launched_stat if path.parent.name == str(launched_process_id)
                else process_stat(
                    peer_process_id, launched_process_id, peer_state))

        for peer_state in ("S", "Z", "X", "x"):
            with self.subTest(peer_state=peer_state), mock.patch.object(
                    parent.Path, "read_text", autospec=True,
                    side_effect=read_process_stat):
                if peer_state == "S":
                    lineage = parent._owned_peer_process_lineage(
                        launched_child, peer_process_id, "initial")
                    self.assertEqual(
                        [process_id for process_id, _, _ in lineage],
                        [peer_process_id, launched_process_id])
                else:
                    with self.assertRaises(parent.Blocked) as refusal:
                        parent._owned_peer_process_lineage(
                            launched_child, peer_process_id, "initial")
                    for detail in (
                            "phase=initial", "observed=exited_peer_process",
                            "errno=none", "authorization=BLOCKED"):
                        self.assertIn(detail, str(refusal.exception))

        peer_state = "S"
        for launched_state in ("Z", "X", "x"):
            launched_stat = process_stat(
                launched_process_id, os.getpid(), launched_state)
            with self.subTest(launched_state=launched_state), mock.patch.object(
                    parent.Path, "read_text", autospec=True,
                    side_effect=read_process_stat):
                with self.assertRaises(parent.Blocked) as refusal:
                    parent._owned_peer_process_lineage(
                        launched_child, peer_process_id, "initial")
                self.assertIn("observed=exited_peer_process",
                              str(refusal.exception))

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

    @unittest.skipIf(os.geteuid() == 0, "rootless session proof requires non-root")
    @unittest.skipUnless(
        hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
        "safe detached-peer cleanup requires Linux pidfd support")
    def test_detached_descendant_session_cannot_authenticate_owned_run(self):
        child_source = (
            "import subprocess,sys,time\n"
            "peer = subprocess.Popen([sys.executable, '-I', '-c', "
            "\"import time; time.sleep(60)\"], start_new_session=True, "
            "stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\n"
            "print(peer.pid, flush=True)\n"
            "time.sleep(60)\n"
        )
        child = subprocess.Popen(
            [sys.executable, "-I", "-c", child_source],
            start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True)
        setattr(child, "_swapz_owned_process_group", child.pid)
        peer_pidfd = None
        try:
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            peer_pid = int(child.stdout.readline().strip())
            peer_pidfd = os.pidfd_open(peer_pid)
            self.assertEqual(os.getsid(child.pid), child.pid)
            self.assertEqual(os.getsid(peer_pid), peer_pid)
            self.assertNotEqual(os.getsid(peer_pid), os.getsid(child.pid))
            with self.assertRaises(parent.Blocked) as refusal:
                parent._owned_peer_process_lineage(
                    child, peer_pid, "initial")
            for detail in (
                    "phase=initial", "expected=owned_live_child_run",
                    "observed=wrong_session", "errno=none",
                    "authorization=BLOCKED",
                    "next=inspect_child_ownership_read_only"):
                self.assertIn(detail, str(refusal.exception))
        finally:
            if peer_pidfd is not None:
                try:
                    signal.pidfd_send_signal(
                        peer_pidfd, signal.SIGKILL, None, 0)
                except ProcessLookupError:
                    pass
                finally:
                    os.close(peer_pidfd)
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdout.close()

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
        # The test targets malformed request cleanup, not peer-pidfd
        # acquisition. Provide a real disposable fd for the synthetic peer;
        # the parent must acquire and close it before any cleanup can pass.
        peer_pidfd, peer_liveness_writer = os.pipe()
        peer_pidfd_handed_off = False

        def get_socket_option(level, option, *_arguments):
            nonlocal peer_pidfd_handed_off
            self.assertEqual(level, socket.SOL_SOCKET)
            if option == socket.SO_PEERCRED:
                return struct.pack("3i", child.pid, 0, 0)
            if option == parent.SO_PEERPIDFD:
                peer_pidfd_handed_off = True
                return peer_pidfd
            self.fail("unexpected socket option")

        connection.getsockopt.side_effect = get_socket_option
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = connection, None
        diagnostics = io.StringIO()
        try:
            with contextlib.redirect_stderr(diagnostics), mock.patch.object(
                    parent, "_check_git_source") as check, mock.patch.object(
                    parent, "_owned_live_connection_peer_lineage",
                    return_value=((child.pid, os.getpid(), 1),)) as lineage:
                result = parent._serve_admission(
                    server, child, self.SOURCE, "/usr/bin/git",
                    self.ORACLE_DIGEST, self.source_hashes,
                    self.HELPER_DIGEST, 2)
            self.assertEqual(result, 2)
            self.assertTrue(peer_pidfd_handed_off)
            lineage.assert_called_once()
            self.assertFalse(stream.responses())
            self.assertIsNotNone(child.poll())
            self.assertIn("source admission request is malformed",
                          diagnostics.getvalue())
            self.assertIn("owned_cleanup=complete", diagnostics.getvalue())
            self.assertNotIn(private_marker, diagnostics.getvalue())
            check.assert_not_called()
            with self.assertRaises(OSError) as closed:
                os.fstat(peer_pidfd)
            self.assertEqual(closed.exception.errno, errno.EBADF)
        finally:
            os.close(peer_liveness_writer)
            # The parent owns the handed-off fd; reclaim it on a failing
            # assertion without hiding the earlier cleanup failure.
            if not peer_pidfd_handed_off:
                os.close(peer_pidfd)
            else:
                try:
                    os.close(peer_pidfd)
                except OSError as error:
                    if error.errno != errno.EBADF:
                        raise
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
                    os.getpid(), 123456,
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
        sys.argv[1], os.geteuid(), int(sys.argv[4]), int(sys.argv[5]),
        "a" * 40)
    print("CONNECTED", flush=True)
    if sys.stdin.readline() != "GO\n":
        raise RuntimeError("missing synthetic gate")
    client.bind_physical_control_inputs({
        name: "c" * 64 for name in helper.PHYSICAL_CONTROL_INPUT_PATHS})
    client.bind_executed_helper_sha256("8" * 64)
    if sys.argv[3] == "changed_start":
        genuine_ancestors = helper._source_parent_ancestors
        def changed_start_time(phase, parent_uid):
            current = list(genuine_ancestors(phase, parent_uid))
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

    @staticmethod
    def _process_start_ticks(process_id):
        process_stat = (
            Path("/proc") / str(process_id) / "stat"
        ).read_text(encoding="ascii")
        closing_parenthesis = process_stat.rfind(") ")
        fields = process_stat[closing_parenthesis + 2:].split()
        if len(fields) < 20:
            raise AssertionError("truncated test process identity")
        return int(fields[19])

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
        parent_process_id = os.getpid()
        parent_start_ticks = self._process_start_ticks(parent_process_id)
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", self.CLIENT,
             os.fspath(self.socket_path), os.fspath(CLIENT_HELPER), mode,
             str(parent_process_id), str(parent_start_ticks)],
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

    def test_higher_same_uid_ancestor_cannot_impersonate_listener_parent(self):
        # This test process owns the listener, but an intermediary launches
        # the client. Our PID appears in its ancestry, yet we did not create it.
        intermediary_script = r"""
import os
import subprocess
import sys

process_stat = open("/proc/self/stat", encoding="ascii").read()
fields = process_stat[process_stat.rfind(") ") + 2:].split()
result = subprocess.run(
    [sys.executable, "-I", "-B", "-c", sys.argv[1],
     sys.argv[2], sys.argv[3], "normal", str(os.getpid()), fields[19]],
    input="GO\n", text=True, capture_output=True, timeout=5)
if result.returncode:
    raise SystemExit(result.stderr or "nested client fixture failed")
print(result.stdout.strip(), flush=True)
"""
        for repetition in range(3):
            with self.subTest(repetition=repetition):
                intermediary = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-c", intermediary_script,
                     self.CLIENT, os.fspath(self.socket_path),
                     os.fspath(CLIENT_HELPER)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True)
                self.addCleanup(self._reap, intermediary)
                with self.server.accept()[0] as connection:
                    connection.settimeout(5)
                    # The non-creator grandparent must receive no admission
                    # request, even though SO_PEERCRED lists it as an ancestor.
                    self.assertEqual(connection.recv(1), b"")
                stdout, stderr = intermediary.communicate(timeout=8)
                self.assertEqual(intermediary.returncode, 0, stderr[:300])
                self._assert_refusal(
                    stdout.strip(), "connect",
                    "parent_ancestry", "unrelated_peer_run")

    def test_stale_expected_parent_cannot_rebind_before_connect(self):
        stale_parent = subprocess.Popen(
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
        try:
            stale_start_ticks = self._process_start_ticks(stale_parent.pid)
            stale_process_id = stale_parent.pid
            stale_parent.terminate()
            stale_parent.wait(timeout=5)

            child = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", self.CLIENT,
                 os.fspath(self.socket_path), os.fspath(CLIENT_HELPER),
                 "normal", str(stale_process_id), str(stale_start_ticks)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1)
            self.addCleanup(self._reap, child)
            self.assertTrue(select.select([child.stdout], [], [], 5)[0])
            result = child.stdout.readline().strip()
            self._assert_refusal(
                result, "connect", "parent_ancestry",
                "stale_or_replaced_parent")
            self.assertEqual(child.wait(timeout=5), 0)
            self.server.settimeout(0.1)
            with self.assertRaises(socket.timeout):
                self.server.accept()
        finally:
            if stale_parent.poll() is None:
                stale_parent.kill()
            stale_parent.wait(timeout=5)

    def test_parent_lineage_stops_at_authorized_parent(self):
        parent_process_id = 32101
        higher_process_id = 32102
        start_ticks = 654321
        parent_uid = os.geteuid()
        stat_fields = (
            ["S", str(higher_process_id)] + ["0"] * 17 + [str(start_ticks)])
        process_stat = (
            f"{parent_process_id} (source-parent) " + " ".join(stat_fields))
        process_status = (
            "Name:\tsource-parent\n"
            f"Uid:\t{parent_uid}\t{parent_uid}\t{parent_uid}\t{parent_uid}\n")
        stat_path = Path("/proc") / str(parent_process_id) / "stat"
        status_path = Path("/proc") / str(parent_process_id) / "status"

        def read_parent_identity(path, encoding=None, errors=None):
            del encoding, errors
            if path == stat_path:
                return process_stat
            if path == status_path:
                return process_status
            raise AssertionError(
                f"walked above authenticated parent: {path.name}")

        with mock.patch.object(
                client_helper.os, "getppid", return_value=parent_process_id), \
             mock.patch.object(
                 client_helper.Path, "read_text", autospec=True,
                 side_effect=read_parent_identity):
            observed = client_helper._source_parent_ancestors(
                "connect", parent_uid)
        self.assertEqual(len(observed), 1)
        observed_process_id, _upstream_process_id, observed_start_ticks = observed[0]
        self.assertEqual(observed_process_id, parent_process_id)
        self.assertEqual(observed_start_ticks, start_ticks)


    def test_terminal_parent_upstream_ppid_is_not_lineage_authority(self):
        pinned = ((31001, 31002, 11), (31002, 31003, 12),
                  (31003, 32000, 13))
        reparented = ((31001, 31002, 11), (31002, 31003, 12),
                      (31003, 1, 13))
        matches = client_helper._source_parent_lineage_matches
        self.assertTrue(matches(pinned, pinned))
        self.assertTrue(matches(pinned, reparented))
        for changed in (
                (),
                reparented[:-1],
                ((31001, 31002, 11), (31002, 31003, 12),
                 (31003, 1, 14)),  # Authorized PID reuse / changed start ticks.
                ((31001, 31002, 11), (31002, 31003, 12),
                 (31004, 1, 13)),  # Different terminal parent.
                ((31001, 31002, 11), (31002, 31004, 12),
                 (31003, 1, 13)),  # Broken intermediate parent link.
                ((31001, 31002, 11), (31004, 31003, 12),
                 (31003, 1, 13)),  # Replaced intermediate process.
                ((31001, 31002, 12), (31002, 31003, 12),
                 (31003, 1, 13)),  # Reused intermediate PID.
        ):
            with self.subTest(changed=changed):
                self.assertFalse(matches(pinned, changed))


    def test_missing_process_identity_remains_blocked(self):
        # A saved terminal PID/start time cannot authorize missing live /proc.
        with mock.patch.object(
                client_helper.os, "getppid", return_value=31001), \
             mock.patch.object(
                 client_helper.Path, "read_text", autospec=True,
                 side_effect=FileNotFoundError(2, "identity unavailable")):
            with self.assertRaises(client_helper.Blocked) as refusal:
                client_helper._source_parent_ancestors("initial", os.geteuid())
        for detail in (
                "phase=initial", "check=process_lineage",
                "observed=unavailable_process_identity", "errno=2",
                "authorization=BLOCKED",
                "next=inspect_parent_identity_read_only"):
            self.assertIn(detail, str(refusal.exception))

    @unittest.skipUnless(
        hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"),
        "orphaned parent cleanup requires Linux pidfd support")
    def test_live_authorized_parent_upstream_reparenting_allows_approval(self):
        # Three real processes: intermediary -> listener creator -> client.
        # The intermediary exits after the client pins the creator, before
        # approval. Only the creator's upstream PPID may change.
        source_parent_program = r"""
import json
import os
import select
import socket
import subprocess
import sys

socket_path, helper_path, client_hex, event_fd, control_fd = sys.argv[1:]
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
    listener.bind(socket_path)
    os.chmod(socket_path, 0o600)
    listener.listen(1)
    listener.settimeout(5)
    process_stat = open("/proc/self/stat", encoding="ascii").read()
    fields = process_stat[process_stat.rfind(") ") + 2:].split()
    client = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c",
         bytes.fromhex(client_hex).decode("ascii"),
         socket_path, helper_path, "normal",
         str(os.getpid()), fields[19]],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        with listener.accept()[0] as connection:
            connection.settimeout(5)
            if not select.select([client.stdout], [], [], 5)[0]:
                raise RuntimeError("client connect timed out")
            if client.stdout.readline().strip() != "CONNECTED":
                raise RuntimeError("client did not pin creator")
            os.write(int(event_fd), b"CONNECTED\n")
            if os.read(int(control_fd), 1) != b"G":
                raise RuntimeError("missing orphan gate")
            client.stdin.write("GO\n")
            client.stdin.flush()
            request_bytes = bytearray()
            while b"\n" not in request_bytes:
                fragment = connection.recv(4096)
                if not fragment:
                    raise RuntimeError("client closed before request")
                request_bytes.extend(fragment)
                if len(request_bytes) > 4096:
                    raise RuntimeError("oversized request")
            request_line, _, remainder = request_bytes.partition(b"\n")
            if remainder:
                raise RuntimeError("unexpected extra request bytes")
            request = json.loads(request_line.decode("ascii"))
            response = {
                "schema": request["schema"], "status": "PASS",
                "phase": request["phase"], "nonce": request["nonce"],
                "source_sha": request["source_sha"],
                "oracle_sha256": "d" * 64}
            connection.sendall((json.dumps(response) + "\n").encode("ascii"))
            if not select.select([client.stdout], [], [], 5)[0]:
                raise RuntimeError("client reply timed out")
            outcome = client.stdout.readline().strip()
            if client.wait(timeout=5):
                raise RuntimeError("client exited abnormally")
            os.write(int(event_fd), outcome.encode("ascii") + b"\n")
    finally:
        if client.poll() is None:
            client.kill()
        client.wait(timeout=5)
        for stream in (client.stdin, client.stdout, client.stderr):
            if stream is not None:
                stream.close()
"""
        intermediary_program = r"""
import os
import subprocess
import sys

source_parent_program, socket_path, helper_path, client_hex, event_fd, control_fd = sys.argv[1:]
source_parent = subprocess.Popen(
    [sys.executable, "-I", "-B", "-c", source_parent_program,
     socket_path, helper_path, client_hex, event_fd, control_fd],
    pass_fds=(int(event_fd), int(control_fd)),
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL)
print(source_parent.pid, flush=True)
if sys.stdin.readline() != "ORPHAN\n":
    raise RuntimeError("missing intermediate exit gate")
"""
        with tempfile.TemporaryDirectory(
                prefix="swapz-live-source-reparent-") as directory:
            event_read, event_write = os.pipe()
            control_read, control_write = os.pipe()
            intermediary = None
            source_parent_pidfd = None
            try:
                intermediary = subprocess.Popen(
                    [sys.executable, "-I", "-B", "-c",
                     intermediary_program, source_parent_program,
                     os.fspath(Path(directory) / "source.sock"),
                     os.fspath(CLIENT_HELPER),
                     self.CLIENT.encode("ascii").hex(),
                     str(event_write), str(control_read)],
                    pass_fds=(event_write, control_read),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, bufsize=1)
                os.close(event_write)
                event_write = None
                os.close(control_read)
                control_read = None

                self.assertTrue(select.select([intermediary.stdout], [], [], 5)[0])
                source_parent_pid = int(intermediary.stdout.readline().strip())
                source_parent_pidfd = os.pidfd_open(source_parent_pid)
                self.assertTrue(select.select([event_read], [], [], 5)[0])
                self.assertEqual(os.read(event_read, 128), b"CONNECTED\n")

                def source_parent_identity():
                    process_stat = (
                        Path("/proc") / str(source_parent_pid) / "stat"
                    ).read_text(encoding="ascii")
                    closing_parenthesis = process_stat.rfind(") ")
                    self.assertGreaterEqual(closing_parenthesis, 0)
                    fields = process_stat[closing_parenthesis + 2:].split()
                    self.assertGreaterEqual(len(fields), 20)
                    return int(fields[1]), int(fields[19])

                before_parent_pid, before_start_ticks = source_parent_identity()
                self.assertEqual(before_parent_pid, intermediary.pid)
                intermediary.stdin.write("ORPHAN\n")
                intermediary.stdin.flush()
                self.assertEqual(intermediary.wait(timeout=5), 0)

                deadline = time.monotonic() + 5
                after_parent_pid, after_start_ticks = source_parent_identity()
                while (after_parent_pid == before_parent_pid and
                       time.monotonic() < deadline):
                    time.sleep(0.01)
                    after_parent_pid, after_start_ticks = source_parent_identity()
                self.assertNotEqual(after_parent_pid, before_parent_pid)
                self.assertEqual(after_start_ticks, before_start_ticks)

                os.write(control_write, b"G")
                self.assertTrue(select.select([event_read], [], [], 5)[0])
                self.assertEqual(
                    os.read(event_read, 256).strip(), b"SYNTHETIC_APPROVED")
            finally:
                if source_parent_pidfd is not None:
                    try:
                        poller = select.poll()
                        poller.register(source_parent_pidfd, select.POLLIN)
                        if not poller.poll(0):
                            signal.pidfd_send_signal(
                                source_parent_pidfd, signal.SIGKILL, None, 0)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(source_parent_pidfd)
                if intermediary is not None:
                    if intermediary.poll() is None:
                        intermediary.kill()
                    intermediary.wait(timeout=5)
                    for stream in (intermediary.stdin, intermediary.stdout,
                                   intermediary.stderr):
                        if stream is not None:
                            stream.close()
                for descriptor in (
                        event_read, event_write, control_read, control_write):
                    if descriptor is not None:
                        os.close(descriptor)

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

    def test_same_uid_grandparent_cannot_replace_creation_parent_listener(self):
        # Unlike an ordinary sibling substitute, this attacker's PID is in
        # the child's real ancestry; only the nearest authorized UID may reply.
        parent_source = r"""
import os
import socket
import subprocess
import sys

socket_path, helper_path, client_hex = sys.argv[1:]
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as source_listener:
    source_listener.bind(socket_path)
    os.chmod(socket_path, 0o600)
    source_listener.listen(1)
    print("READY", flush=True)
    if sys.stdin.readline() != "REPLACED\n":
        raise RuntimeError("missing substitution gate")
    process_stat = open("/proc/self/stat", encoding="ascii").read()
    fields = process_stat[process_stat.rfind(") ") + 2:].split()
    client = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c",
         bytes.fromhex(client_hex).decode("ascii"),
         socket_path, helper_path, "normal",
         str(os.getpid()), fields[19]],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        outcome = client.stdout.readline().strip()
        if outcome == "CONNECTED":
            client.stdin.write("GO\n")
            client.stdin.flush()
            outcome = client.stdout.readline().strip()
        print(outcome, flush=True)
        if client.wait(timeout=5) != 0:
            raise RuntimeError("source admission client did not exit normally")
    finally:
        if client.poll() is None:
            client.kill()
        client.wait(timeout=5)
        for stream in (client.stdin, client.stdout, client.stderr):
            if stream is not None:
                stream.close()
"""
        for repetition in range(3):
            with self.subTest(repetition=repetition):
                with tempfile.TemporaryDirectory(
                        prefix="swapz-ancestor-substitution-") as directory:
                    socket_path = Path(directory) / "source.sock"
                    creator = subprocess.Popen(
                        [sys.executable, "-I", "-B", "-c", parent_source,
                         os.fspath(socket_path), os.fspath(CLIENT_HELPER),
                         self.CLIENT.encode("ascii").hex()],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, text=True, bufsize=1)
                    try:
                        self.assertTrue(
                            select.select([creator.stdout], [], [], 5)[0])
                        self.assertEqual(creator.stdout.readline().strip(), "READY")
                        socket_path.unlink()  # Grandparent swaps the original P inode.
                        with socket.socket(
                                socket.AF_UNIX, socket.SOCK_STREAM) as forged:
                            forged.bind(os.fspath(socket_path))
                            os.chmod(socket_path, 0o600)
                            forged.listen(1)
                            forged.settimeout(5)
                            creator.stdin.write("REPLACED\n")
                            creator.stdin.flush()
                            with forged.accept()[0] as connection:
                                connection.settimeout(5)
                                received = connection.recv(4096)
                                if received:
                                    # A former any-ancestor implementation sent
                                    # source data here and admitted forged PASS.
                                    request = json.loads(
                                        received.split(b"\n", 1)[0].decode("ascii"))
                                    connection.sendall(
                                        (json.dumps(self._response(request)) +
                                         "\n").encode("ascii"))
                            self.assertEqual(received, b"",
                                             "grandparent received source request")
                        self._assert_refusal(
                            self._finish(creator), "connect",
                            "parent_ancestry", "unrelated_peer_run")
                    finally:
                        self._reap(creator)

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

    def test_partial_reply_eof_blocks(self):
        child = self._start_client()
        with self.server.accept()[0] as connection:
            connection.settimeout(5)
            child.stdin.write("GO\n")
            child.stdin.flush()
            self._read_request(connection)
            connection.sendall(b'{"status":"PASS"')
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
