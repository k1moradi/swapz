#!/usr/bin/env python3
"""Rootless adversarial process/run binding for the physical source parent."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
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


if __name__ == "__main__":
    unittest.main()
