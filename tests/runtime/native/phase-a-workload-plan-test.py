#!/usr/bin/env python3
"""Rootless actual matched mappings and synthetic v2 plan composition only."""
import copy
import contextlib
import io
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SOURCE = TOOLS / "phase-a-workload-plan.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


producer = load("producer", SOURCE)
ordinary = load("ordinary", TOOLS / "phase-a-ordinary-evidence.py")


def request(count=8, hot=3, touches=3, seed=42):
    return dict(schema="swapz-workload-plan-request", version=2,
                scope=dict(source="1" * 40, run_nonce="2" * 32,
                           area_epoch=41, swap_type=0, target=43),
                page_count=count, hot_page_count=hot, touch_count=touches, seed=seed,
                max_pages=16, max_operations=64)


def independent_page(seed, index, hot, touches):
    page = bytearray((b"\x00\x01" + hashlib.shake_256(struct.pack("<QQ", seed, index)).digest(510)) * 8)
    if hot:
        for _ in range(touches):
            page[0] ^= 1
    return bytes(page)


def envelope(commitment):
    # No invented witnesses/capture: only call the frozen plan validator.
    return dict(schema="swapz-ordinary-manifest", version=2, witnesses=[], **commitment)


def write_request(directory, value):
    path = Path(directory) / producer.REQUEST_NAME
    path.write_bytes(json.dumps(value).encode("utf-8"))
    path.chmod(0o600)
    return path


def fd_count():
    return len(os.listdir("/proc/self/fd"))


class WorkloadPlanTests(unittest.TestCase):
    def test_independent_canonical_and_bounds(self):
        value = request(2, 1, 3)
        commitment = producer.build_commitment(value)
        self.assertEqual(commitment["scope"]["workload_sha256"],
                         "315ab8037457f1752c7a6ea86ae9c9eb89851a824c3dbca2a80c041274c42d0e")
        expected = ordinary.committed_pages(envelope(commitment))
        self.assertEqual(list(expected), [1, 2, 3, 4])
        self.assertEqual(set(commitment), {"plan", "scope"})
        for n, page in expected.items():
            index = (n - 1) % 2
            self.assertTrue(page == independent_page(42, index, index == 0, 3))
        for count, hot, touches, seed in [(2, 1, 0, 0), (8, 7, 16, 2**64-1), (8, 3, 1, 42)]:
            value = request(count, hot, touches, seed)
            value.update(max_pages=2*count, max_operations=4*count)
            commitment = producer.build_commitment(value)
            self.assertEqual(len(ordinary.committed_pages(envelope(commitment))), 2*count)
            self.assertEqual(commitment, producer.build_commitment(value))

    def test_actual_mapping_parity_and_cleanup(self):
        for touches in (0, 1, 2, 3, 16):
            value = request(touches=touches)
            commitment = producer.build_commitment(value)
            before = fd_count()
            with tempfile.TemporaryFile(dir="/dev/shm") as backing:
                producer.verify_preparation(value, commitment, backing.fileno())
                self.assertEqual(os.fstat(backing.fileno()).st_size, 0)
                self.assertEqual(os.fstat(backing.fileno()).st_nlink, 0)
            self.assertEqual(fd_count(), before)
            expected = ordinary.committed_pages(envelope(commitment))
            for index in range(8):
                page = independent_page(42, index, index < 3, touches)
                self.assertTrue(expected[index + 1] == page == expected[index + 9])

    def test_wrong_seed_parity_and_independent_comparison(self):
        value = request()
        commitment = producer.build_commitment(value)
        for changed in (dict(value, seed=43), dict(value, touch_count=2), dict(value, hot_page_count=4)):
            with self.subTest(case="changed_spec"), tempfile.TemporaryFile(dir="/dev/shm") as backing:
                with self.assertRaisesRegex(producer.PlanError, "committed_page_mismatch"):
                    producer.verify_preparation(changed, commitment, backing.fileno())
                self.assertEqual(os.fstat(backing.fileno()).st_size, 0)
        # The helper could produce a wrong pattern and verify itself consistently;
        # the independent retained bytes must still fail comparison.
        with tempfile.TemporaryFile(dir="/dev/shm") as backing, patch.object(
                producer.pressure, "_cold_page", return_value=b"\x00" * 4096):
            with self.assertRaisesRegex(producer.PlanError, "committed_page_mismatch"):
                producer.verify_preparation(value, commitment, backing.fileno())
            self.assertEqual(os.fstat(backing.fileno()).st_size, 0)

    def test_invalid_requests(self):
        for key, bad in [("version", 1), ("version", True), ("version", 2.0),
                         ("schema", "wrong"), ("page_count", 1), ("page_count", 9),
                         ("page_count", True), ("hot_page_count", 0), ("hot_page_count", 8),
                         ("touch_count", -1), ("touch_count", 17), ("touch_count", False),
                         ("seed", -1), ("seed", 2**64), ("seed", False),
                         ("max_pages", 15), ("max_pages", 17), ("max_operations", 31),
                         ("max_operations", 65), ("max_operations", 64.0)]:
            with self.subTest(field=key):
                with self.assertRaises(producer.PlanError):
                    producer.build_commitment(dict(request(), **{key: bad}))
        for key, bad in [("source", "0"*40), ("source", "A"*40), ("source", "1"*39),
                         ("source", 1), ("run_nonce", "0"*32), ("run_nonce", "a"*31),
                         ("run_nonce", "A"*32), ("area_epoch", 0), ("area_epoch", True),
                         ("target", 2**64), ("swap_type", -1), ("swap_type", 256),
                         ("swap_type", False), ("workload_sha256", "3"*64)]:
            value = request()
            value["scope"][key] = bad
            with self.subTest(field=key), self.assertRaises(producer.PlanError):
                producer.build_commitment(value)
        for key in request():
            value = request()
            del value[key]
            with self.assertRaises(producer.PlanError):
                producer.build_commitment(value)
        with self.assertRaises(producer.PlanError):
            producer.build_commitment(dict(request(), witnesses=[]))

    def test_frozen_verifier_refuses_mutated_commitments(self):
        commitment = producer.build_commitment(request())
        for mutation in (lambda c: c["plan"].update(version=1),
                         lambda c: c["plan"].update(extra=1),
                         lambda c: c["plan"]["pages"].reverse(),
                         lambda c: c["plan"]["pages"][1].update(logical=1),
                         lambda c: c["plan"]["pages"][0].update(logical=True),
                         lambda c: c["plan"]["pages"][0].update(expected_page="00"*4095),
                         lambda c: c["scope"].update(target=99),
                         lambda c: c["scope"].update(workload_sha256="3"*64),
                         lambda c: c["plan"]["pages"][0].update(expected_page="00"*4096)):
            changed = copy.deepcopy(commitment)
            mutation(changed)
            with self.assertRaises(ordinary.Invalid):
                ordinary.committed_pages(envelope(changed))

    def test_private_cli_and_precommit_order(self):
        with tempfile.TemporaryDirectory() as directory:
            value = request()
            write_request(directory, value)
            artifact = Path(directory) / producer.ARTIFACT_NAME
            original = producer.pressure.prepare_matched_cold_workload
            calls = []

            def observe(**kwargs):
                calls.append(True)
                self.assertTrue(artifact.exists())
                self.assertTrue(json.loads(artifact.read_bytes()) == producer.build_commitment(value))
                self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
                self.assertEqual(artifact.stat().st_nlink, 1)
                return original(**kwargs)

            with producer.open_private_directory(directory) as fd, patch.object(
                    producer.pressure, "prepare_matched_cold_workload", side_effect=observe):
                summary = producer.retain_and_prepare(fd, value)
            self.assertEqual(len(calls), 1)
            self.assertEqual(summary["pages"], 16)
            self.assertEqual(summary["cohorts"], [dict(backing="anonymous", pages=8, hot=3, cold=5),
                                                  dict(backing="file-backed-tmpfs", pages=8, hot=3, cold=5)])
            self.assertEqual(summary["auth"], 0)
            saved = artifact.read_bytes()
            with producer.open_private_directory(directory) as fd, self.assertRaises(FileExistsError):
                producer.retain_and_prepare(fd, value)
            self.assertTrue(artifact.read_bytes() == saved)
            artifact.unlink()
            result = subprocess.run([sys.executable, "-B", str(SOURCE), directory], capture_output=True,
                                    text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            self.assertEqual(json.loads(result.stdout), summary)
            self.assertNotIn(value["scope"]["run_nonce"], result.stdout)
            self.assertNotIn(directory, result.stdout)
            self.assertTrue(artifact.read_bytes() == saved)

    def test_private_paths_and_json_refusals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_path = write_request(directory, request())
            artifact = root / producer.ARTIFACT_NAME

            def blocked(path=directory):
                result = subprocess.run([sys.executable, "-B", str(SOURCE), str(path)], capture_output=True,
                                        text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertEqual(report["auth"], 0)
                self.assertEqual(report["observation"], "UNKNOWN")
                self.assertNotIn(directory, result.stdout)
                self.assertNotIn("1"*40, result.stdout)
                self.assertNotIn("2"*32, result.stdout)

            root.chmod(0o755)
            blocked()
            root.chmod(0o700)
            input_path.chmod(0o644)
            blocked()
            input_path.chmod(0o600)
            for raw in (b"{", b'{"version":2,"version":2}', b'{"seed":NaN}', b"x"*4097, b"\xff"):
                input_path.write_bytes(raw)
                blocked()
            write_request(directory, request())
            link = root / "link"
            link.hardlink_to(input_path)
            blocked()
            input_path.unlink()
            input_path.symlink_to(link)
            blocked()
            input_path.unlink()
            os.mkfifo(input_path, 0o600)
            blocked()
            input_path.unlink()
            write_request(directory, request())
            real = root / "real"
            real.mkdir(mode=0o700)
            alias = root / "alias"
            alias.symlink_to(real, target_is_directory=True)
            blocked(alias)
            blocked(str(alias) + "/child")
            blocked(directory + "/../" + root.name)
            artifact.symlink_to(link)
            blocked()
            self.assertTrue(artifact.is_symlink())
            artifact.unlink()
            self.assertFalse(artifact.exists())

    def test_failure_cleanup_first_cause_and_no_fd_debt(self):
        with tempfile.TemporaryDirectory() as directory:
            value = request()
            path = Path(directory) / producer.ARTIFACT_NAME
            before = fd_count()
            with producer.open_private_directory(directory) as fd:
                with patch.object(producer, "verify_preparation", side_effect=producer.PlanError("first_failure")):
                    with self.assertRaisesRegex(producer.PlanError, "first_failure"):
                        producer.retain_and_prepare(fd, value)
                self.assertFalse(path.exists())
                with patch.object(producer.os, "write", side_effect=OSError("private path")):
                    with self.assertRaises(OSError):
                        producer.retain_and_prepare(fd, value)
                self.assertFalse(path.exists())
                with patch.object(producer, "verify_preparation", side_effect=producer.PlanError("first_failure")), \
                     patch.object(producer.os, "unlink", side_effect=OSError("private cleanup")):
                    with self.assertRaisesRegex(producer.PlanError, "first_failure") as caught:
                        producer.retain_and_prepare(fd, value)
                self.assertIn("artifact_cleanup_failed", caught.exception.__notes__)
                self.assertTrue(path.exists())
                path.unlink()
            write_request(directory, value)
            output = io.StringIO()
            with patch.object(producer, "verify_preparation", side_effect=producer.PlanError("first_failure")), \
                 patch.object(producer.os, "unlink", side_effect=OSError("private cleanup")), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(producer.main([directory]), 2)
            report = json.loads(output.getvalue())
            self.assertEqual(report["reason"], "first_failure")
            self.assertIs(report["cleanup_debt"], True)
            self.assertNotIn("private cleanup", output.getvalue())
            path.unlink()
            self.assertEqual(fd_count(), before)


if __name__ == "__main__":
    if os.geteuid() == 0:
        raise SystemExit("FAIL: workload plan tests require unprivileged execution")
    unittest.main(verbosity=2)
