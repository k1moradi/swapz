#!/usr/bin/env python3
"""Rootless contracts for the private primary real-swap qualification helper."""

from dataclasses import replace
from types import SimpleNamespace
import builtins
import errno
import contextlib
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import struct
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
PARENT = ROOT / "tests/tools/qualify-primary-real-swap-parent.py"
ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"

SPEC = importlib.util.spec_from_file_location("qualify_primary_real_swap", HELPER)
qualify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualify
SPEC.loader.exec_module(qualify)
PARENT_SPEC = importlib.util.spec_from_file_location(
    "qualify_primary_real_swap_parent", PARENT)
parent = importlib.util.module_from_spec(PARENT_SPEC)
sys.modules[PARENT_SPEC.name] = parent
PARENT_SPEC.loader.exec_module(parent)
ORACLE_SPEC = importlib.util.spec_from_file_location("primary_real_swap_oracle", ORACLE)
oracle = importlib.util.module_from_spec(ORACLE_SPEC)
sys.modules[ORACLE_SPEC.name] = oracle
ORACLE_SPEC.loader.exec_module(oracle)


class FakeStat:
    def __init__(self, major=252, minor=1, block=True):
        self.st_mode = stat.S_IFBLK | 0o600 if block else stat.S_IFREG | 0o600
        self.st_rdev = os.makedev(major, minor) if block else 0


class PrimaryRealSwapContracts(unittest.TestCase):
    @contextlib.contextmanager
    def _mock_owned_admission_peer(self):
        # These tests exercise admission sequencing with an in-memory child;
        # the real /proc ancestry contract has dedicated live-process tests.
        with mock.patch.object(
                parent, "_owned_peer_process_lineage",
                return_value=((123, 456, 789),)):
            yield

    @staticmethod
    def physical_dependency_output(source_root: Path) -> str:
        dependencies = sorted(
            qualify._physical_control_expected_dependencies(source_root),
            key=os.fspath)
        joined = " ".join(os.fspath(path) for path in dependencies)
        second_source = source_root / "src/userspace/swapz-primary.c"
        return (
            f"swapzctl.o: {joined}\n"
            f"swapz-primary.o: {second_source}\n"
        )

    def test_oracle_page_pattern_is_full_page_deterministic_and_page_specific(self):
        first = oracle.page_pattern("01" * 16, 7)
        again = oracle.page_pattern("01" * 16, 7)
        other = oracle.page_pattern("01" * 16, 8)
        self.assertEqual(len(first), qualify.PAGE_BYTES)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_oracle_page_stream_distinguishes_intra_page_positions(self):
        page = oracle.page_pattern("ab" * 16, 3)
        chunks = [page[index:index + 32] for index in range(0, len(page), 32)]
        self.assertEqual(len(set(chunks)), qualify.PAGE_BYTES // 32)
        self.assertNotEqual(page, oracle.page_pattern("cd" * 16, 3))

    def test_oracle_counts_all_corrupted_bytes_without_misreporting_clean_data(self):
        class MemoryFixture:
            def __init__(self):
                self.contents = bytearray(oracle.PAGE_BYTES)
                self.closed = False

            def __getitem__(self, key):
                return self.contents[key]

            def __setitem__(self, key, value):
                self.contents[key] = value

            def close(self):
                self.closed = True

        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                allocation = MemoryFixture()
                output = io.StringIO()
                commands = iter(("FILL", "VERIFY"))

                def command():
                    value = next(commands)
                    if corrupt and value == "VERIFY":
                        allocation.contents[9] ^= 1
                        allocation.contents[20] ^= 2
                    return value

                with mock.patch.object(oracle, "MIB", oracle.PAGE_BYTES), \
                        mock.patch.object(oracle, "MIN_MIB", 1), \
                        mock.patch.object(oracle, "MAX_MIB", 1), \
                        mock.patch.object(oracle, "_disable_dumps"), \
                        mock.patch.object(oracle, "_read_command", side_effect=command), \
                        mock.patch.object(oracle.mmap, "mmap", return_value=allocation), \
                        contextlib.redirect_stdout(output):
                    status = oracle.run_workload("12" * 16, 1)
                verified = [
                    json.loads(line[len("ORACLE_VERIFIED="):])
                    for line in output.getvalue().splitlines()
                    if line.startswith("ORACLE_VERIFIED=")
                ][0]
                self.assertEqual(status, 1 if corrupt else 0)
                self.assertEqual(verified["mismatches"], 2 if corrupt else 0)
                self.assertEqual(len(verified["mismatch_samples"]), 1 if corrupt else 0)
                self.assertTrue(allocation.closed)

    def test_oracle_allocation_cleanup_failure_forces_failure_without_masking_workload(self):
        class MemoryFixture:
            def __init__(self):
                self.contents = bytearray(oracle.PAGE_BYTES)

            def __getitem__(self, key):
                return self.contents[key]

            def __setitem__(self, key, value):
                self.contents[key] = value

            def close(self):
                raise BufferError("synthetic allocation cleanup failure")

        allocation = MemoryFixture()
        commands = iter(("FILL", "VERIFY"))
        stderr = io.StringIO()
        with mock.patch.object(oracle, "MIB", oracle.PAGE_BYTES), \
                mock.patch.object(oracle, "MIN_MIB", 1), \
                mock.patch.object(oracle, "MAX_MIB", 1), \
                mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_read_command",
                                  side_effect=lambda: next(commands)), \
                mock.patch.object(oracle.mmap, "mmap", return_value=allocation), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            status = oracle.run_workload("34" * 16, 1)
        self.assertEqual(status, 1)
        self.assertIn(
            "FAIL: oracle allocation cleanup failed: "
            "synthetic allocation cleanup failure",
            stderr.getvalue())

        commands = iter(("FILL", "WRONG"))
        stderr = io.StringIO()
        with mock.patch.object(oracle, "MIB", oracle.PAGE_BYTES), \
                mock.patch.object(oracle, "MIN_MIB", 1), \
                mock.patch.object(oracle, "MAX_MIB", 1), \
                mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_read_command",
                                  side_effect=lambda: next(commands)), \
                mock.patch.object(oracle.mmap, "mmap", return_value=allocation), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(stderr):
            status = oracle.run_workload("34" * 16, 1)
        self.assertEqual(status, 1)
        self.assertIn("FAIL: oracle workload failed: expected VERIFY command",
                      stderr.getvalue())
        self.assertIn("FAIL: oracle allocation cleanup failed",
                      stderr.getvalue())

    def test_oracle_rejects_malformed_seed_and_negative_page(self):
        for seed in ("", "a" * 31, "A" * 32, "g" * 32):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                oracle.page_pattern(seed, 0)
        with self.assertRaises(ValueError):
            oracle.page_pattern("a" * 32, -1)

    def test_strict_json_object_parser_rejects_duplicates_and_nonfinite_numbers(self):
        self.assertEqual(
            qualify._load_unique_json('{"value":1}', "fixture"),
            {"value": 1})
        for payload in (
                '{"value":1,"value":2}',
                '{"value":NaN}',
                '{"value":Infinity}',
                '{"value":-Infinity}'):
            with self.subTest(payload=payload), \
                    self.assertRaises(qualify.Blocked):
                qualify._load_unique_json(payload, "fixture")

    def test_json_parser_recursion_is_blocked_before_provenance_use(self):
        with mock.patch.object(
                qualify.json, "loads", side_effect=RecursionError("nested JSON")), \
                self.assertRaisesRegex(qualify.Blocked, "cannot parse fixture"):
            qualify._load_unique_json('{"value":1}', "fixture")

    def test_selector_is_exact_single_partuuid_line(self):
        self.assertEqual(
            qualify.parse_selector("PARTUUID=f13428f6-01\n"),
            "f13428f6-01")
        self.assertEqual(
            qualify.parse_selector(
                "PARTUUID=550E8400-E29B-41D4-A716-446655440000\n"),
            "550e8400-e29b-41d4-a716-446655440000")
        for text in (
                "", "PARTUUID=x\n", "PARTUUID=--------\n",
                "PARTUUID=-f13428f6\n", "PARTUUID=f13428f6-\n",
                "PARTUUID=f13428f6--01\n", "PARTUUID=1234-567\n",
                "PARTUUID=deadbeef-01\nextra\n", "UUID=deadbeef-01\n"):
            with self.subTest(text=text), self.assertRaises(qualify.Blocked):
                qualify.parse_selector(text)


    @staticmethod
    def _root_owned_selector_stat(info, *, owner_uid=0):
        # Only the stat report is synthetic; the on-disk fixture stays rootless.
        return SimpleNamespace(
            st_dev=info.st_dev, st_ino=info.st_ino, st_mode=info.st_mode,
            st_uid=owner_uid, st_nlink=info.st_nlink, st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)

    @contextlib.contextmanager
    def _selector_fixture(self, selector_path, *, after_inspection=None,
                          after_open=None, descriptor_owner_uid=0):
        inspections = 0

        class SyntheticSelectorPath:
            def __fspath__(self):
                return os.fspath(selector_path)

            def lstat(self):
                nonlocal inspections
                inspected = selector_path.lstat()
                if inspections == 0 and after_inspection is not None:
                    after_inspection()
                inspections += 1
                return PrimaryRealSwapContracts._root_owned_selector_stat(inspected)

        original_fstat = os.fstat
        descriptor_inspections = 0

        def descriptor_stat(file_descriptor):
            nonlocal descriptor_inspections
            inspected = original_fstat(file_descriptor)
            if descriptor_inspections == 0 and after_open is not None:
                after_open()
            descriptor_inspections += 1
            return self._root_owned_selector_stat(
                inspected, owner_uid=descriptor_owner_uid)

        with mock.patch.object(qualify, "SELECTOR", SyntheticSelectorPath()), \
                mock.patch.object(qualify.os, "fstat", side_effect=descriptor_stat):
            yield

    def test_selector_unchanged_descriptor_reads_only_pinned_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            selector.write_bytes(b"PARTUUID=AAAAAAAA\n")
            selector.chmod(0o600)
            original_open = os.open
            flags_seen = []

            def capture_open(path, flags, *args):
                flags_seen.append(flags)
                return original_open(path, flags, *args)

            with self._selector_fixture(selector), \
                    mock.patch.object(qualify.os, "open", side_effect=capture_open):
                evidence = qualify._read_selector_evidence()
                self.assertEqual(qualify._read_selector(), "aaaaaaaa")
            self.assertEqual(evidence.partuuid, "aaaaaaaa")
            self.assertEqual(len(flags_seen), 2)
            for flags in flags_seen:
                self.assertTrue(flags & os.O_NOFOLLOW)
                self.assertTrue(flags & os.O_CLOEXEC)
                self.assertTrue(flags & os.O_NONBLOCK)

    def test_selector_symlink_and_hard_link_block(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            real_file = Path(directory) / "target"
            real_file.write_bytes(b"PARTUUID=aaaaaaaa\n")
            real_file.chmod(0o600)
            selector.symlink_to(real_file)
            with self._selector_fixture(selector), \
                    self.assertRaisesRegex(qualify.Blocked, "observed=nonregular"):
                qualify._read_selector()
            selector.unlink()
            os.link(real_file, selector)
            with self._selector_fixture(selector), \
                    self.assertRaisesRegex(qualify.Blocked, "observed=link-count-mismatch"):
                qualify._read_selector()

    def test_selector_replacement_between_inspection_and_open_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            replacement = Path(directory) / "replacement"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            replacement.write_bytes(b"PARTUUID=bbbbbbbb\n")
            selector.chmod(0o600)
            replacement.chmod(0o600)
            with self._selector_fixture(
                    selector, after_inspection=lambda: os.replace(
                        replacement, selector)), \
                    self.assertRaisesRegex(
                        qualify.Blocked, "phase=fstat.*observed=substituted-inode"):
                qualify._read_selector()

    def test_selector_path_replacement_after_open_blocks_even_with_same_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            replacement = Path(directory) / "replacement"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            replacement.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o600)
            replacement.chmod(0o600)
            with self._selector_fixture(
                    selector, after_open=lambda: os.replace(
                        replacement, selector)), \
                    self.assertRaisesRegex(
                        qualify.Blocked, "phase=revalidate.*replaced-selector-path"):
                qualify._read_selector()

    def test_selector_malformed_truncated_non_ascii_and_oversized_block(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            for payload in (
                    b"", b"PARTUUID=abc\n", b"PARTUUID=aaaaaaaa\nextra\n",
                    b"PARTUUID=aaaa\xffaaa\n",
                    b"PARTUUID=" + b"a" * 65 + b"\n"):
                with self.subTest(length=len(payload), payload_index=payload[:1]):
                    selector.write_bytes(payload)
                    selector.chmod(0o600)
                    with self._selector_fixture(selector), \
                            self.assertRaises(qualify.Blocked) as raised:
                        qualify._read_selector()
                    self.assertIn("phase=", str(raised.exception))
                    self.assertIn("action=BLOCK-before-prepare", str(raised.exception))
                    self.assertNotIn(os.fspath(selector), str(raised.exception))

    def test_selector_mode_and_owner_inconsistency_block(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o644)
            with self._selector_fixture(selector), \
                    self.assertRaisesRegex(qualify.Blocked, "observed=mode-mismatch"):
                qualify._read_selector()
            selector.chmod(0o600)
            with self._selector_fixture(selector, descriptor_owner_uid=1000), \
                    self.assertRaisesRegex(qualify.Blocked, "observed=owner-mismatch"):
                qualify._read_selector()

    def test_selector_read_error_and_in_place_truncation_block(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            original_open = builtins.open

            class InjectedRead:
                def __init__(self, stream, action):
                    self.stream = stream
                    self.action = action

                def __enter__(self):
                    return self

                def __exit__(self, exception_type, exception, traceback):
                    return self.stream.__exit__(
                        exception_type, exception, traceback)

                def fileno(self):
                    return self.stream.fileno()

                def read(self, limit):
                    self.action()
                    return self.stream.read(limit)

            for action, expected in (
                    (lambda: (_ for _ in ()).throw(
                        OSError(errno.EIO, "synthetic private path")),
                     "phase=read.*errno=5"),
                    (lambda: selector.write_bytes(b""),
                     "phase=read.*observed=truncated-or-changed")):
                selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
                selector.chmod(0o600)

                def fake_open(*args, **kwargs):
                    return InjectedRead(original_open(*args, **kwargs), action)

                with self._selector_fixture(selector), \
                        mock.patch.object(
                            qualify, "open", create=True, side_effect=fake_open), \
                        self.assertRaisesRegex(qualify.Blocked, expected) as raised:
                    qualify._read_selector()
                self.assertNotIn(os.fspath(selector), str(raised.exception))
                self.assertNotIn("synthetic private path", str(raised.exception))

    def test_selector_last_use_refuses_replacement_before_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            replacement = Path(directory) / "replacement"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o600)
            with self._selector_fixture(selector):
                admitted = qualify._read_selector_evidence()
            replacement.write_bytes(b"PARTUUID=aaaaaaaa\n")
            replacement.chmod(0o600)
            os.replace(replacement, selector)
            with self._selector_fixture(selector), \
                    mock.patch.object(
                        qualify, "verify_authorized_target") as verify, \
                    self.assertRaisesRegex(
                        qualify.Blocked, "phase=policy_use.*changed-selector-identity"):
                qualify._require_selector_at_policy_use(
                    admitted, {}, {}, (8, 1), (8, 0))
            verify.assert_not_called()

    def test_selector_last_use_command_failure_is_blocked_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o600)
            with self._selector_fixture(selector):
                admitted = qualify._read_selector_evidence()
                with mock.patch.object(
                        qualify, "verify_authorized_target",
                        side_effect=qualify.QualificationFailure(
                            "command failed rc=7: /private/lsblk: hidden")), \
                        self.assertRaisesRegex(
                            qualify.Blocked,
                            "phase=policy_use.*authorization-command-failed"
                            ".*errno=none.*status=7") as raised:
                    qualify._require_selector_at_policy_use(
                        admitted, {}, {}, (8, 1), (8, 0))
            self.assertNotIn("/private", str(raised.exception))
            self.assertNotIn("hidden", str(raised.exception))

    def test_selector_last_use_malformed_authorization_is_blocked_and_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o600)
            with self._selector_fixture(selector):
                admitted = qualify._read_selector_evidence()
                with mock.patch.object(
                        qualify, "verify_authorized_target",
                        side_effect=ValueError("/private/malformed")), \
                        self.assertRaisesRegex(
                            qualify.Blocked,
                            "phase=policy_use.*authorization-unavailable-or-mismatch"
                            ".*errno=none") as raised:
                    qualify._require_selector_at_policy_use(
                        admitted, {}, {}, (8, 1), (8, 0))
            self.assertNotIn("/private", str(raised.exception))

    def test_selector_last_use_requires_authorized_live_target_and_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            selector = Path(directory) / "selector"
            selector.write_bytes(b"PARTUUID=aaaaaaaa\n")
            selector.chmod(0o600)
            contract = {"authorized_target": {}}
            with self._selector_fixture(selector):
                admitted = qualify._read_selector_evidence()
                with mock.patch.object(
                        qualify, "verify_authorized_target",
                        return_value=(Path("/synthetic"), (8, 1), (8, 0))) as verify:
                    qualify._require_selector_at_policy_use(
                        admitted, {}, contract, (8, 1), (8, 0))
                    verify.assert_called_once_with({}, "aaaaaaaa", contract)
                with mock.patch.object(
                        qualify, "verify_authorized_target",
                        return_value=(Path("/synthetic"), (8, 2), (8, 0))), \
                        self.assertRaisesRegex(
                            qualify.Blocked, "phase=policy_use.*changed-target-or-parent"):
                    qualify._require_selector_at_policy_use(
                        admitted, {}, contract, (8, 1), (8, 0))

    def test_swap_inventory_resolves_block_identity_and_preserves_used_as_volatile(self):
        contents = (
            "Filename Type Size Used Priority\n"
            "/dev/dm-1 partition 1020 16 7\n"
            "/swapfile file 2048 8 -2\n"
        )
        def fake_stat(path):
            if path == "/dev/dm-1":
                return FakeStat(252, 1)
            return FakeStat(block=False)
        rows = qualify.parse_swap_rows(contents, fake_stat)
        self.assertEqual(rows[0].device, (252, 1))
        self.assertIsNone(rows[1].device)
        changed_used = [replace(rows[0], used_kib=64), replace(rows[1], used_kib=128)]
        self.assertEqual(qualify._swap_identity(rows), qualify._swap_identity(changed_used))

    def test_swap_inventory_rejects_duplicate_or_malformed_rows(self):
        bad = (
            "Filename Type Size Used Priority\n"
            "/dev/a partition 100 0 -1\n"
            "/dev/a partition 100 0 -1\n"
        )
        with self.assertRaises(qualify.Blocked):
            qualify.parse_swap_rows(bad, lambda _path: FakeStat())
        with self.assertRaises(qualify.Blocked):
            qualify.parse_swap_rows("Name Type Size Used Priority\n")
        with self.assertRaises(qualify.Blocked):
            qualify.parse_swap_rows("Filename Type Size Used Priority\n/dev/a partition 1 2 -1\n")

    def test_expected_swap_must_be_unique_highest_priority(self):
        expected = qualify.SwapRow("/dev/dm-1", "partition", 100, 0, 5, (252, 1))
        qualify.require_expected_swap_priority(
            expected, [qualify.SwapRow("/swapfile", "file", 100, 0, 4, None)])
        for priority in (5, 6):
            with self.subTest(priority=priority), self.assertRaises(qualify.Blocked):
                qualify.require_expected_swap_priority(
                    expected, [qualify.SwapRow("/swapfile", "file", 100, 0, priority, None)])

    def test_raw_swap_alias_rejects_target_partition_and_parent_disk(self):
        unrelated = qualify.SwapRow("/swapfile", "file", 100, 0, -2, None)
        qualify.require_no_conflicting_raw_swap_aliases(
            [unrelated], (8, 1), (8, 0))
        for alias in (
            qualify.SwapRow(
                "/dev/disk/by-uuid/target", "partition", 100, 0, -1, (8, 1)),
            qualify.SwapRow(
                "/dev/disk/by-id/parent", "partition", 100, 0, -1, (8, 0)),
        ):
            with self.subTest(alias=alias.path), self.assertRaisesRegex(
                    qualify.Blocked, "active swap through alias"):
                qualify.require_no_conflicting_raw_swap_aliases(
                    [unrelated, alias], (8, 1), (8, 0))

    def test_unresolved_active_block_swap_alias_blocks_admission(self):
        unresolved = qualify.SwapRow(
            "/dev/disk/by-id/missing", "partition", 100, 0, -1, None)
        with self.assertRaisesRegex(qualify.Blocked, "cannot resolve active block-swap alias"):
            qualify.require_no_conflicting_raw_swap_aliases(
                [unresolved], (8, 1), (8, 0))

    def test_plan_storage_separation_requires_explicit_false_current_keys(self):
        canonical = {
            "root_same_physical_disk_as_target": False,
            "recovery_same_physical_disk_as_target": False,
        }
        qualify.require_plan_storage_separation(canonical)
        for key in canonical:
            with self.subTest(key=key):
                mutant = dict(canonical)
                mutant[key] = True
                with self.assertRaises(qualify.Blocked):
                    qualify.require_plan_storage_separation(mutant)
                missing = dict(canonical)
                del missing[key]
                with self.assertRaises(qualify.Blocked):
                    qualify.require_plan_storage_separation(missing)

    def test_authorized_parent_requires_exact_sole_partition_topology(self):
        target = {"pkname": "sda"}
        parent = {
            "path": "/dev/sda",
            "children": [{"type": "part", "maj:min": "8:1"}],
        }
        qualify.require_sole_partition_topology(target, parent, "8:1")
        mutants = (
            ({}, parent),
            (target, {"path": "/dev/sda"}),
            (target, {"path": "/dev/sda", "children": [
                {"type": "part", "maj:min": "8:1"},
                {"type": "part", "maj:min": "8:2"},
            ]}),
            (target, {"path": "/dev/sdb", "children": [
                {"type": "part", "maj:min": "8:1"},
            ]}),
        )
        for mutant_target, mutant_parent in mutants:
            with self.subTest(target=mutant_target, parent=mutant_parent), \
                    self.assertRaises(qualify.Blocked):
                qualify.require_sole_partition_topology(
                    mutant_target, mutant_parent, "8:1")

    def test_provenance_independently_hashes_all_installed_qualified_artifacts(self):
        source_sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            swapzctl = prefix / "sbin/swapzctl"
            module = prefix / "libexec/swapz/dm-swapz.ko"
            device_oracle = prefix / "libexec/swapz/device-roundtrip"
            for path, contents in (
                (swapzctl, b"qualified swapzctl"),
                (module, b"qualified module"),
                (device_oracle, b"qualified device oracle"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
            hashes = {
                "formatter_sha256": hashlib.sha256(swapzctl.read_bytes()).hexdigest(),
                "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "oracle_sha256": hashlib.sha256(device_oracle.read_bytes()).hexdigest(),
            }
            report = {
                "schema": "swapz-test-results-v1",
                "source_sha": source_sha,
                "tested_commit_sha": source_sha,
                "overall": "PASS",
                "qualification": "RAM_BACKED_NULL_BLK_ONLY",
                "qualified_artifacts": {"status": "AVAILABLE", **hashes},
            }
            report_path = prefix / "qualification.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            report_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
            plan = {
                "control_build_source_clean": True,
                # Pre-start module provenance is unavailable by design because
                # the admitted cycle requires dm_swapz to be absent.
                "module_build_provenance_read": False,
                "module_build_source_clean": False,
                "control_module_source_matches": False,
                "qualification_report_valid": True,
                "qualification_source_matches_build": True,
                "live_artifact_hashes_read": True,
                "live_artifacts_match_qualification": True,
                "control_build_source_sha": source_sha,
                "module_build_source_sha": "unavailable",
                "qualification_report_sha256": report_digest,
                "qualified_swapzctl_sha256": hashes["formatter_sha256"],
                "live_swapzctl_sha256": hashes["formatter_sha256"],
                "qualified_module_sha256": hashes["module_sha256"],
                "live_module_sha256": hashes["module_sha256"],
                "qualified_oracle_sha256": hashes["oracle_sha256"],
                "live_oracle_sha256": hashes["oracle_sha256"],
                "privileged_execution_enabled": True,
                "module_mapper_inventory_read": True,
                "swapz_mapper_absent": True,
                "dm_swapz_module_loaded": False,
            }
            self.assertEqual(
                qualify.verify_provenance(plan, source_sha, report_path, swapzctl),
                hashes)
            module.write_bytes(b"substituted module")
            with self.assertRaisesRegex(qualify.Blocked, "installed module_sha256"):
                qualify.verify_provenance(plan, source_sha, report_path, swapzctl)

    def test_loaded_module_provenance_is_checked_only_after_start(self):
        source_sha = "a" * 40
        qualify.validate_loaded_module_provenance(source_sha, "1", "Y", source_sha)
        qualify.validate_loaded_module_provenance(source_sha, "1", "1", source_sha)
        for observed_source, clean, physical in (
            ("b" * 40, "1", "Y"),
            (source_sha, "0", "Y"),
            (source_sha, "1", "N"),
            (source_sha, "1", "0"),
        ):
            with self.subTest(source=observed_source, clean=clean, physical=physical), \
                    self.assertRaises(qualify.QualificationFailure):
                qualify.validate_loaded_module_provenance(
                    observed_source, clean, physical, source_sha)


    def test_mutated_worktree_inputs_cannot_pass_commit_hash_admission(self):
        # Synthetic source fixture: no tracked file, real swap or privilege touched.
        source_sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir()
            originals = {}
            for relative in qualify.PHYSICAL_CONTROL_INPUT_PATHS:
                path = worktree / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                data = f"trusted {relative}\n".encode("ascii")
                path.write_bytes(data)
                originals[relative] = data
            expected = {
                relative: hashlib.sha256(payload).hexdigest()
                for relative, payload in originals.items()
            }
            candidates = qualify.PHYSICAL_CONTROL_INPUT_PATHS
            with mock.patch.object(qualify, "ROOT", worktree):
                for index, relative in enumerate(candidates):
                    with self.subTest(input=relative):
                        source_path = worktree / relative
                        source_path.write_bytes(b"unauthorized changed bytes\n")
                        attempt = root / f"attempt-{index}"
                        attempt.mkdir()
                        try:
                            _, observed = qualify.pin_physical_control_inputs(attempt)
                            request = {
                                "schema": parent.SOURCE_ADMISSION_SCHEMA,
                                "phase": "initial",
                                "source_sha": source_sha,
                                "nonce": "b" * 32,
                                "physical_control_inputs_sha256": observed,
                                "executed_helper_sha256": "8" * 64,
                            }
                            encoded = (json.dumps(request) + "\n").encode("ascii")
                            with self.assertRaisesRegex(
                                    parent.Blocked,
                                    "source admission request identity is invalid"):
                                parent._read_request(
                                    io.BytesIO(encoded), source_sha, expected, "8" * 64)
                        finally:
                            source_path.write_bytes(originals[relative])


    def test_worktree_mutation_after_copy_cannot_enter_private_compile(self):
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            worktree.mkdir(mode=0o700)
            for relative in qualify.PHYSICAL_CONTROL_INPUT_PATHS:
                path = worktree / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = (
                    b"test-version\n"
                    if relative == "src/kernel/VERSION"
                    else b"/* trusted snapshot input */\n"
                )
                path.write_bytes(payload)

            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified installed control")
            private_parent = root / "private-parent"
            private_parent.mkdir(mode=0o700)

            with mock.patch.object(qualify, "ROOT", worktree):
                source_root, digests = qualify.pin_physical_control_inputs(
                    private_parent)
                for relative in qualify.PHYSICAL_CONTROL_INPUT_PATHS:
                    (worktree / relative).write_bytes(
                        b"unauthorized mutable worktree bytes\n")

                observed_sources = []

                def fake_compile(argv, **_kwargs):
                    if "-MM" in argv:
                        return completed(
                            args=argv, returncode=0,
                            stdout=self.physical_dependency_output(source_root),
                            stderr="")
                    observed_sources.extend(
                        argument for argument in argv if argument.endswith(".c"))
                    Path(argv[argv.index("-o") + 1]).write_bytes(
                        b"private physical control")
                    return completed(
                        args=argv, returncode=0, stdout="", stderr="")

                with mock.patch.object(
                        qualify, "_run", side_effect=fake_compile):
                    control, _digest = qualify.build_physical_execution_control(
                        "a" * 40, qualified, private_parent / "control",
                        source_root=source_root, expected_input_hashes=digests)

            self.assertTrue(control.is_file())
            self.assertEqual(len(observed_sources), 2)
            self.assertTrue(all(
                Path(source).is_relative_to(source_root)
                for source in observed_sources))
            self.assertTrue(all(
                not Path(source).is_relative_to(worktree)
                for source in observed_sources))

    def test_physical_source_snapshot_rejects_symlink_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            alternate = root / "alternate-kernel"
            (worktree / "src").mkdir(parents=True)
            alternate.mkdir()
            (alternate / "VERSION").write_text("test-version\n", encoding="ascii")
            (worktree / "src/kernel").symlink_to(
                alternate, target_is_directory=True)
            private_parent = root / "private"
            private_parent.mkdir(mode=0o700)
            with mock.patch.object(qualify, "ROOT", worktree), \
                    self.assertRaisesRegex(
                        qualify.Blocked, "physical control source"):
                qualify.pin_physical_control_inputs(private_parent)

    def test_private_source_hashes_reject_mutation_before_and_during_compile(self):
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified installed control")
            candidates = qualify.PHYSICAL_CONTROL_INPUT_PATHS
            for index, relative in enumerate(candidates):
                with self.subTest(input=relative, phase="before_compile"):
                    attempt = root / f"before-{index}"
                    attempt.mkdir(mode=0o700)
                    source_root, digests = qualify.pin_physical_control_inputs(attempt)
                    changed = source_root / relative
                    changed.chmod(0o600)
                    changed.write_bytes(b"changed after initial source admission\n")
                    changed.chmod(0o400)
                    with mock.patch.object(
                            qualify, "_run",
                            side_effect=AssertionError("compiler must not run")):
                        with self.assertRaisesRegex(
                                qualify.Blocked,
                                "differs from validated commit at before_compile:"):
                            qualify.build_physical_execution_control(
                                "a" * 40, qualified, attempt / "control",
                                source_root=source_root, expected_input_hashes=digests)

            for index, relative in enumerate(candidates):
                with self.subTest(input=relative, phase="during_compile"):
                    attempt = root / f"during-{index}"
                    attempt.mkdir(mode=0o700)
                    source_root, digests = qualify.pin_physical_control_inputs(attempt)

                    def modified_compile(argv, **kwargs):
                        self.assertEqual(kwargs["cwd"], attempt / "control")
                        if "-MM" in argv:
                            return completed(
                                args=argv, returncode=0,
                                stdout=self.physical_dependency_output(source_root),
                                stderr="")
                        changed = source_root / relative
                        changed.chmod(0o600)
                        changed.write_bytes(b"mutated while compiler is running\n")
                        changed.chmod(0o400)
                        Path(argv[argv.index("-o") + 1]).write_bytes(b"untrusted binary")
                        return completed(args=argv, returncode=0, stdout="", stderr="")

                    with mock.patch.object(
                            qualify, "_run", side_effect=modified_compile):
                        with self.assertRaisesRegex(
                                qualify.Blocked,
                                "differs from validated commit at after_compile:"):
                            qualify.build_physical_execution_control(
                                "a" * 40, qualified, attempt / "control",
                                source_root=source_root, expected_input_hashes=digests)


    def test_private_compile_dependency_scan_rejects_unpinned_path(self):
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified installed control")
            source_root, digests = qualify.pin_physical_control_inputs(root)
            unexpected = root / "mutable-worktree/header.h"

            def fake_dependency_scan(argv, **_kwargs):
                if "-MM" not in argv:
                    raise AssertionError("compile must not run after bad dependencies")
                output = (
                    self.physical_dependency_output(source_root) +
                    f"unexpected.o: {unexpected}\n"
                )
                return completed(
                    args=argv, returncode=0, stdout=output, stderr="")

            with mock.patch.object(
                    qualify, "_run", side_effect=fake_dependency_scan), \
                    self.assertRaisesRegex(
                        qualify.Blocked, "dependency closure differs"):
                qualify.build_physical_execution_control(
                    "a" * 40, qualified, root / "control",
                    source_root=source_root, expected_input_hashes=digests)

    def test_private_compile_rejects_worktree_root_and_unpinned_transitive_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_root, digests = qualify.pin_physical_control_inputs(root)
            private_control = root / "control"
            with self.assertRaisesRegex(qualify.Blocked, "not private"):
                qualify.require_pinned_physical_control_inputs(
                    ROOT, private_control, digests, "before_compile")
            changed = source_root / "src/kernel/codec.h"
            changed.chmod(0o600)
            changed.write_bytes(changed.read_bytes() + b'\n#include "untracked.h"\n')
            changed.chmod(0o400)
            digests["src/kernel/codec.h"] = hashlib.sha256(
                changed.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                    qualify.Blocked, "unpinned transitive header"):
                qualify.require_pinned_physical_control_inputs(
                    source_root, private_control, digests, "before_compile")

    def test_mutated_pinned_policy_and_readiness_are_blocked_at_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, verifier in (
                    ("docs/production-acceptance.json",
                     qualify._verify_acceptance_manifest_snapshot),
                    ("docs/handoff/production-readiness.json",
                     qualify._read_readiness_snapshot)):
                with self.subTest(document=relative):
                    original = (ROOT / relative).read_bytes()
                    expected = hashlib.sha256(original).hexdigest()
                    snapshot = root / Path(relative).name
                    snapshot.write_bytes(b'{"unauthorized":true}\n')
                    if relative.endswith("production-acceptance.json"):
                        with self.assertRaisesRegex(
                                qualify.Blocked, "validated commit at policy_use"):
                            verifier(
                                cycles=qualify.DEFAULT_CYCLES,
                                workload_mib=qualify.DEFAULT_WORKLOAD_MIB,
                                resident_mib=qualify.DEFAULT_RESIDENT_MIB,
                                swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
                                timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS,
                                path=snapshot, expected_sha256=expected)
                    else:
                        with self.assertRaisesRegex(
                                qualify.Blocked, "validated commit at policy_use"):
                            verifier(snapshot, expected_sha256=expected)

    def test_private_physical_control_build_binds_exact_source_and_installed_control(self):
        source_sha = "a" * 40
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified-installed-control")
            private_directory = root / "private"
            source_root, source_hashes = qualify.pin_physical_control_inputs(root)

            def fake_compile(argv, **_kwargs):
                if "-MM" in argv:
                    return completed(
                        args=argv, returncode=0,
                        stdout=self.physical_dependency_output(source_root),
                        stderr="")
                output = Path(argv[argv.index("-o") + 1])
                output.write_bytes(b"private-physical-control")
                return completed(args=argv, returncode=0, stdout="", stderr="")

            with mock.patch.object(qualify, "_run", side_effect=fake_compile) as run:
                control, digest = qualify.build_physical_execution_control(
                    source_sha, qualified, private_directory,
                    source_root=source_root, expected_input_hashes=source_hashes)

            dependency_argv = run.call_args_list[0].args[0]
            argv = run.call_args.args[0]
            self.assertEqual(run.call_args.kwargs["cwd"], private_directory)
            self.assertIn("-MM", dependency_argv)
            source_index = argv.index(
                str(source_root / "src/userspace/swapzctl.c"))
            self.assertEqual(
                dependency_argv[1:dependency_argv.index("-MM")],
                argv[1:source_index])
            self.assertNotIn("-I", argv)
            self.assertNotIn("-include", argv)
            self.assertIn("-DSWAPZ_PRIMARY_PHYSICAL_QUALIFICATION_TEST=1", argv)
            self.assertIn(
                f"-DSWAPZ_BUILD_SOURCE_SHA={json.dumps(source_sha)}", argv)
            self.assertIn(
                "-DSWAPZ_PRIMARY_PHYSICAL_QUALIFIED_CONTROL=" +
                json.dumps(str(qualified.resolve())), argv)
            self.assertEqual(control.read_bytes(), b"private-physical-control")
            self.assertEqual(
                digest, hashlib.sha256(b"private-physical-control").hexdigest())
            self.assertEqual(stat.S_IMODE(control.stat().st_mode), 0o700)

    def test_private_physical_control_compiles_and_reports_runtime_gate(self):
        source_sha = "a" * 40
        subprocess = __import__("subprocess")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified-installed-control")
            qualified.chmod(0o700)
            source_root, source_hashes = qualify.pin_physical_control_inputs(root)
            control, digest = qualify.build_physical_execution_control(
                source_sha, qualified, root / "private", source_root=source_root,
                expected_input_hashes=source_hashes)
            self.assertEqual(digest, hashlib.sha256(control.read_bytes()).hexdigest())

            unmarked_environment = dict(os.environ)
            unmarked_environment.pop(
                "SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION", None)
            unmarked = subprocess.run(
                [str(control), "primary", "plan"],
                text=True, capture_output=True, check=False,
                env=unmarked_environment)
            self.assertEqual(unmarked.returncode, 2)
            unmarked_plan = json.loads(unmarked.stdout)
            self.assertIs(unmarked_plan["privileged_execution_enabled"], False)
            self.assertEqual(
                unmarked_plan["control_build_source_sha"], source_sha)

            marked = subprocess.run(
                [str(control), "primary", "plan"],
                text=True, capture_output=True, check=False,
                env={**unmarked_environment,
                     **qualify._physical_control_environment()})
            self.assertEqual(marked.returncode, 2)
            marked_plan = json.loads(marked.stdout)
            self.assertIs(marked_plan["privileged_execution_enabled"], True)
            self.assertEqual(marked_plan["control_build_source_sha"], source_sha)


    def test_private_runtime_artifact_mutations_block_each_execution_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = root / "swapzctl"
            oracle_path = root / "oracle.py"
            control.write_bytes(b"trusted control")
            oracle_path.write_bytes(b"trusted oracle")
            expected_control = hashlib.sha256(control.read_bytes()).hexdigest()
            expected_oracle = hashlib.sha256(oracle_path.read_bytes()).hexdigest()
            for phase in ("before_qualification_import", "before_cycle-1",
                          "before_final_publication"):
                qualify.require_private_execution_artifact_identity(
                    control, oracle_path, expected_control, expected_oracle, phase)
                for label, path in (("coordinator", control), ("oracle", oracle_path)):
                    with self.subTest(phase=phase, artifact=label):
                        original = path.read_bytes()
                        path.write_bytes(b"unauthorized changed artifact")
                        try:
                            with self.assertRaisesRegex(
                                    qualify.Blocked,
                                    f"private {label} artifact changed at {phase}"):
                                qualify.require_private_execution_artifact_identity(
                                    control, oracle_path, expected_control,
                                    expected_oracle, phase)
                        finally:
                            path.write_bytes(original)

    def test_installed_control_plan_never_receives_private_runtime_marker(self):
        completed = __import__("subprocess").CompletedProcess
        result = completed(
            args=[], returncode=2,
            stdout='{"privileged_execution_enabled":false}\n', stderr="")
        with mock.patch.object(qualify, "_run", return_value=result) as run:
            plan = qualify._read_installed_plan(
                Path("/usr/local/sbin/swapzctl"))
        self.assertIs(plan["privileged_execution_enabled"], False)
        self.assertNotIn("extra_environment", run.call_args.kwargs)

    def test_private_control_invocations_receive_runtime_marker_only_as_child_env(self):
        completed = __import__("subprocess").CompletedProcess
        plan_result = completed(
            args=[], returncode=2,
            stdout='{"privileged_execution_enabled":true}\n', stderr="")
        with mock.patch.object(qualify, "_run", return_value=plan_result) as run:
            plan = qualify._read_plan(Path("/tmp/private-swapzctl"))
        self.assertIs(plan["privileged_execution_enabled"], True)
        self.assertEqual(
            run.call_args.kwargs["extra_environment"],
            {"SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION": "1"})

        primary_result = completed(args=[], returncode=0, stdout="", stderr="")
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("subprocess.run", return_value=primary_result) as run:
            qualify._primary(
                Path("/tmp/private-swapzctl"), "prepare", 60, admitted=True)
            self.assertNotIn("SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION", os.environ)
        child_environment = run.call_args.kwargs["env"]
        self.assertEqual(
            child_environment["SWAPZ_PRIMARY_PHYSICAL_QUALIFICATION"], "1")

    def test_source_admission_close_failure_remains_retryable(self):
        client = object.__new__(qualify.SourceAdmissionClient)
        channel = mock.Mock()
        channel.close.side_effect = [
            OSError("synthetic close failure"), None]
        client._channel = channel

        with self.assertRaisesRegex(OSError, "synthetic close failure"):
            client.close()
        self.assertIs(client._channel, channel)

        client.close()
        self.assertIsNone(client._channel)
        self.assertEqual(channel.close.call_count, 2)

    def test_owned_source_admission_close_preserves_original_failure(self):
        arguments = qualify.build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/synthetic/report.json",
            "--source-admission-socket", "/synthetic/socket",
            "--source-admission-parent-uid", "1000",
        ])
        channel = mock.Mock()
        channel.close.side_effect = OSError("synthetic close failure")
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch.object(qualify, "SourceAdmissionClient",
                                  return_value=channel), \
                mock.patch.object(qualify, "_execute_admitted",
                                  side_effect=qualify.Blocked("source proof failed")):
            with self.assertRaisesRegex(
                    qualify.Blocked,
                    "source proof failed; cleanup also failed: "
                    "source admission channel: synthetic close failure"):
                qualify.execute(arguments)
        channel.close.assert_called_once_with()

    def test_owned_source_admission_closes_before_success(self):
        arguments = qualify.build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/synthetic/report.json",
            "--source-admission-socket", "/synthetic/socket",
            "--source-admission-parent-uid", "1000",
        ])
        channel = mock.Mock()
        expected = {"status": "PASS"}

        def admitted(_arguments, _admission, *, terminal_cleanup):
            terminal_cleanup()
            return expected

        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(os, "geteuid", return_value=0), \
                mock.patch.object(
                    qualify, "SourceAdmissionClient", return_value=channel), \
                mock.patch.object(
                    qualify, "_execute_admitted", side_effect=admitted):
            self.assertIs(qualify.execute(arguments), expected)
        channel.close.assert_called_once_with()

    def test_private_workspace_is_cleaned_when_mode_hardening_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            report = root / "qualification.json"
            oracle_path = root / "oracle.py"
            for path, contents in (
                    (qualified, b"qualified"),
                    (report, b"{}"),
                    (oracle_path, b"#!/usr/bin/env python3\n")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
                path.chmod(0o700)

            workspace_path = root / "workspace"
            workspace_path.mkdir()
            cleanup_called = []

            class FakeWorkspace:
                name = str(workspace_path)

                def cleanup(self):
                    cleanup_called.append(True)

            args = qualify.build_parser().parse_args([
                "--validated-source", "a" * 40,
                "--qualification-report", str(report),
                "--swapzctl", str(qualified),
                "--oracle", str(oracle_path),
                "--executed-helper-sha256", "8" * 64,
            ])
            admission = mock.Mock()
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(os, "geteuid", return_value=0), \
                    mock.patch.object(os, "sysconf", return_value=qualify.PAGE_BYTES), \
                    mock.patch.object(qualify, "_ensure_commands"), \
                    mock.patch.object(
                        qualify.tempfile, "TemporaryDirectory",
                        return_value=FakeWorkspace()), \
                    mock.patch.object(
                        qualify.os, "chmod",
                        side_effect=OSError("synthetic chmod failure")):
                with self.assertRaisesRegex(
                        qualify.Blocked, "cannot secure private physical workspace"):
                    qualify.execute(args, admission=admission)

            admission.require.assert_not_called()
            self.assertEqual(cleanup_called, [True])

    def test_private_workspace_is_cleaned_when_admission_fails_before_evidence(self):
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            report = root / "qualification.json"
            oracle_path = root / "oracle.py"
            for path, contents in (
                    (qualified, b"qualified"),
                    (report, b"{}"),
                    (oracle_path, b"#!/usr/bin/env python3\n")):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(contents)
                path.chmod(0o700)

            workspace_path = root / "workspace"
            workspace_path.mkdir()
            cleanup_called = []

            class FakeWorkspace:
                name = str(workspace_path)

                def cleanup(self):
                    cleanup_called.append(True)

            args = qualify.build_parser().parse_args([
                "--validated-source", "a" * 40,
                "--qualification-report", str(report),
                "--swapzctl", str(qualified),
                "--oracle", str(oracle_path),
                "--executed-helper-sha256", "8" * 64,
            ])
            private_control = workspace_path / "control/swapzctl"
            private_control.parent.mkdir()
            private_control.write_bytes(b"private")
            private_control.chmod(0o700)

            admission = mock.Mock()
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(os, "geteuid", return_value=0), \
                    mock.patch.object(os, "sysconf", return_value=qualify.PAGE_BYTES), \
                    mock.patch.object(qualify, "_ensure_commands"), \
                    mock.patch.object(
                        qualify.tempfile, "TemporaryDirectory",
                        return_value=FakeWorkspace()), \
                    mock.patch.object(
                        qualify, "pin_physical_control_inputs",
                        return_value=(root, {
                            item: "7" * 64
                            for item in qualify.PHYSICAL_CONTROL_INPUT_PATHS
                        })), \
                    mock.patch.object(
                        qualify, "build_physical_execution_control",
                        return_value=(private_control, "1" * 64)), \
                    mock.patch.object(
                        qualify, "pin_real_swap_oracle",
                        return_value=(oracle_path, "2" * 64)), \
                    mock.patch.object(
                        qualify, "preflight_workload_environment",
                        side_effect=qualify.Blocked("synthetic preflight")):
                with self.assertRaisesRegex(qualify.Blocked, "synthetic preflight"):
                    qualify.execute(args, admission=admission)

            admission.require.assert_called_once_with("initial")
            self.assertEqual(cleanup_called, [True])

    def test_terminal_pass_waits_for_owned_cleanup(self):
        for failure_point in ("private workspace", "source admission channel",
                              "final source change"):
            with self.subTest(failure_point=failure_point), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                qualified = root / "prefix/sbin/swapzctl"
                report = root / "qualification.json"
                oracle_path = root / "oracle.py"
                for path, contents in (
                        (qualified, b"qualified"),
                        (report, b"{}"),
                        (oracle_path, b"#!/usr/bin/env python3\n")):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(contents)
                    path.chmod(0o700)

                workspace_path = root / "workspace"
                workspace_path.mkdir()
                private_control = workspace_path / "control/swapzctl"
                private_control.parent.mkdir()
                private_control.write_bytes(b"private")
                private_control.chmod(0o700)
                workspace_cleanup_calls = []

                class FakeWorkspace:
                    name = str(workspace_path)

                    def cleanup(self):
                        workspace_cleanup_calls.append(True)
                        if failure_point == "private workspace" and \
                                len(workspace_cleanup_calls) == 1:
                            raise OSError(
                                "synthetic terminal workspace cleanup failure")
                        shutil.rmtree(workspace_path)

                terminal_cleanup_calls = []

                def terminal_cleanup():
                    terminal_cleanup_calls.append(True)
                    if failure_point == "source admission channel":
                        raise qualify.QualificationFailure(
                            "source admission channel cleanup failed before "
                            "terminal PASS: synthetic close failure")

                evidence_instances = []

                class FakeEvidence:
                    def __init__(self, *_args, **_kwargs):
                        self.path = root / "evidence.json"
                        self.finish_calls = []
                        evidence_instances.append(self)

                    def update(self, *_args, **_kwargs):
                        pass

                    def finish(self, status_value, reason=None, **_fields):
                        self.finish_calls.append((status_value, reason))

                args = qualify.build_parser().parse_args([
                    "--validated-source", "a" * 40,
                    "--qualification-report", str(report),
                    "--swapzctl", str(qualified),
                    "--oracle", str(oracle_path),
                    "--executed-helper-sha256", "8" * 64,
                ])
                admission = mock.Mock()
                admission.require.side_effect = (
                    ["0" * 64,
                     qualify.Blocked(
                         "unprivileged source admission refused at final: "
                         "production source tree is not clean")]
                    if failure_point == "final source change"
                    else ["0" * 64] * 2)
                cycle_results = iter([
                    {"run_id": "1" * 32, "linux_swap_uuid": "1" * 32},
                    {"run_id": "2" * 32, "linux_swap_uuid": "2" * 32},
                ])

                def fake_cycle(index, **kwargs):
                    self.assertIn("0" * 32, kwargs["prior_run_ids"])
                    if index == 2:
                        self.assertIn("1" * 32, kwargs["prior_run_ids"])
                    return next(cycle_results)
                with contextlib.ExitStack() as stack:
                    stack.enter_context(
                        mock.patch.object(
                            os, "sysconf", return_value=qualify.PAGE_BYTES))
                    stack.enter_context(
                        mock.patch.object(qualify, "_ensure_commands"))
                    stack.enter_context(
                        mock.patch.object(
                            qualify.tempfile, "TemporaryDirectory",
                            return_value=FakeWorkspace()))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "pin_physical_control_inputs",
                            return_value=(root, {
                                item: "7" * 64
                                for item in qualify.PHYSICAL_CONTROL_INPUT_PATHS
                            })))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "build_physical_execution_control",
                            return_value=(private_control, "1" * 64)))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "pin_real_swap_oracle",
                            return_value=(oracle_path, "2" * 64)))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "preflight_workload_environment"))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_verify_acceptance_manifest_snapshot",
                            return_value=({}, "3" * 64)))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "acceptance_manifest_sha256",
                            return_value="3" * 64))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_kernel_log_snapshot", return_value=[]))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_import_qualification"))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_read_plan",
                            return_value={
                                "target_device_bytes":
                                    str(1024 * qualify.MIB),
                                "qualification_report_sha256": "6" * 64}))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "verify_provenance",
                            return_value={
                                "formatter_sha256": "4" * 64}))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_read_installed_plan",
                            return_value={
                                "privileged_execution_enabled": False}))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_read_selector_evidence",
                            return_value=qualify.SelectorEvidence(
                                "f13428f6-01", (1,))))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_read_readiness_snapshot",
                            return_value=(
                                {"authorized_target": {}}, "9" * 64)))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "verify_authorized_target",
                            return_value=(
                                Path("/synthetic"), (8, 1), (8, 0))))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "read_swap_rows", return_value=[]))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_validate_precycle_state",
                            return_value={
                                "stage": "COMPLETE",
                                "run_id": "0" * 32,
                            }))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_reject_relevant_kernel_errors"))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "_sha256_file",
                            side_effect=lambda path, **_kwargs: (
                                "1" * 64 if Path(path) == private_control else
                                "2" * 64)))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "PersistentEvidence", FakeEvidence))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "require_final_installed_artifact_identity"))
                    stack.enter_context(
                        mock.patch.object(
                            qualify, "run_cycle",
                            side_effect=fake_cycle))
                    stack.enter_context(
                        self.assertRaises(
                            qualify.Blocked if failure_point == "final source change"
                            else qualify.QualificationFailure))
                    qualify._execute_admitted(
                        args, admission, terminal_cleanup=terminal_cleanup)

                self.assertEqual(len(evidence_instances), 1)
                statuses = [
                    status for status, _reason
                    in evidence_instances[0].finish_calls]
                self.assertEqual(
                    statuses, ["BLOCKED"] if failure_point == "final source change"
                    else ["FAIL"])
                failure_reason = evidence_instances[0].finish_calls[-1][1]
                self.assertEqual(statuses[-1],
                                 "BLOCKED" if failure_point == "final source change"
                                 else "FAIL")
                if failure_point == "private workspace":
                    self.assertEqual(workspace_cleanup_calls, [True, True])
                    self.assertEqual(terminal_cleanup_calls, [])
                    self.assertIn(
                        "synthetic terminal workspace cleanup failure",
                        failure_reason)
                elif failure_point == "source admission channel":
                    self.assertEqual(workspace_cleanup_calls, [True])
                    self.assertEqual(terminal_cleanup_calls, [True])
                    self.assertIn("synthetic close failure", failure_reason)
                else:
                    self.assertEqual(workspace_cleanup_calls, [True])
                    self.assertEqual(terminal_cleanup_calls, [])
                    self.assertIn("at final", failure_reason)

    def test_terminal_pass_orders_cleanup_and_pins_verified_report_digest(self):
        source = HELPER.read_text(encoding="utf-8")
        execute_start = source.index("def _execute_admitted(")
        execute_end = source.index("\ndef execute(", execute_start)
        execute_source = source[execute_start:execute_end]

        cleanup_complete_index = execute_source.index(
            "workspace_cleanup_complete = True")
        cleanup_index = execute_source.rfind(
            "private_workspace.cleanup()", 0, cleanup_complete_index)
        self.assertGreaterEqual(cleanup_index, 0)
        result_index = execute_source.index('result = {', cleanup_complete_index)
        final_artifact_index = execute_source.index(
            "require_final_installed_artifact_identity(", result_index)
        pending_index = execute_source.index(
            'evidence.update("FINAL_PUBLICATION_PENDING"', final_artifact_index)
        final_admission_index = execute_source.index(
            'admission.require("final")', pending_index)
        close_index = execute_source.index(
            "terminal_cleanup()", final_admission_index)
        pass_index = execute_source.index(
            'evidence.finish("PASS"', final_admission_index)
        self.assertLess(cleanup_index, result_index)
        self.assertLess(result_index, final_artifact_index)
        self.assertLess(final_artifact_index, pending_index)
        self.assertLess(pending_index, final_admission_index)
        self.assertLess(final_admission_index, close_index)
        self.assertLess(close_index, pass_index)

        self.assertIn(
            'qualification_report_sha256 = '
            'plan["qualification_report_sha256"]',
            execute_source)
        self.assertIn(
            '"qualification_report_sha256": qualification_report_sha256',
            execute_source)
        self.assertNotIn(
            '"qualification_report_sha256": _sha256_file(report_path)',
            execute_source)

    def test_real_swap_oracle_is_canonical_and_pinned_before_use(self):
        with tempfile.TemporaryDirectory(prefix="swapz-real-oracle-") as directory:
            private = Path(directory)
            expected_digest = hashlib.sha256(ORACLE.read_bytes()).hexdigest()
            pinned, digest = qualify.pin_real_swap_oracle(
                ORACLE, private, expected_digest)
            self.assertEqual(pinned.parent, private)
            self.assertNotEqual(pinned, ORACLE)
            self.assertEqual(pinned.read_bytes(), ORACLE.read_bytes())
            self.assertEqual(
                digest, hashlib.sha256(ORACLE.read_bytes()).hexdigest())
            self.assertEqual(stat.S_IMODE(pinned.stat().st_mode), 0o500)

        with tempfile.TemporaryDirectory(prefix="swapz-wrong-oracle-digest-") as directory:
            with self.assertRaisesRegex(
                    qualify.Blocked, "validated source commit"):
                qualify.pin_real_swap_oracle(
                    ORACLE, Path(directory), "0" * 64)

        with tempfile.TemporaryDirectory(prefix="swapz-fake-oracle-") as directory:
            private = Path(directory)
            fake = private / "fake.py"
            fake.write_text("print('fabricated pass')\n", encoding="utf-8")
            fake.chmod(0o700)
            destination = private / "pinned"
            destination.mkdir()
            with self.assertRaisesRegex(
                    qualify.Blocked, "exact source-controlled oracle"):
                qualify.pin_real_swap_oracle(
                    fake, destination,
                    hashlib.sha256(ORACLE.read_bytes()).hexdigest())


    def test_real_swap_oracle_rejects_symlink_alias_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            alias = Path(directory) / "oracle.py"
            alias.symlink_to(ORACLE)
            destination = Path(directory) / "pinned"
            destination.mkdir()
            with self.assertRaisesRegex(
                    qualify.Blocked, "exact source-controlled oracle"):
                qualify.pin_real_swap_oracle(
                    alias, destination,
                    hashlib.sha256(ORACLE.read_bytes()).hexdigest())

    def test_oracle_pin_preserves_read_failure_when_descriptor_close_also_fails(self):
        real_close = os.close

        def close_then_fail(descriptor):
            real_close(descriptor)
            raise OSError("synthetic close failure")

        with tempfile.TemporaryDirectory(prefix="swapz-oracle-close-") as directory, \
                mock.patch.object(
                    qualify.os, "read",
                    side_effect=OSError("synthetic read failure")), \
                mock.patch.object(
                    qualify.os, "close", side_effect=close_then_fail), \
                self.assertRaisesRegex(
                    qualify.Blocked,
                    "cannot read real-swap oracle: synthetic read failure; "
                    "cleanup also failed: .*synthetic close failure"):
            qualify.pin_real_swap_oracle(
                ORACLE, Path(directory),
                hashlib.sha256(ORACLE.read_bytes()).hexdigest())

    def test_source_admission_binds_commit_oracle_digest(self):
        source_sha = "a" * 40
        oracle_digest = "b" * 64
        nonce_bytes = b"\x12" * 16
        client = object.__new__(qualify.SourceAdmissionClient)
        client._validated_source = source_sha
        client._oracle_sha256 = None
        client._executed_helper_sha256 = "8" * 64
        client._physical_control_inputs_sha256 = {
            item: "d" * 64
            for item in qualify.PHYSICAL_CONTROL_INPUT_PATHS
        }

        def channel_for(phase: str, digest: str):
            response = {
                "schema": qualify.SOURCE_ADMISSION_SCHEMA,
                "status": "PASS",
                "phase": phase,
                "source_sha": source_sha,
                "nonce": nonce_bytes.hex(),
                "oracle_sha256": digest,
            }
            encoded = (
                json.dumps(
                    response, sort_keys=True, separators=(",", ":")
                ).encode("ascii") + b"\n")
            channel = mock.Mock()
            channel.recv.side_effect = [bytes([value]) for value in encoded]
            return channel

        client._channel = channel_for("initial", oracle_digest)
        with mock.patch.object(qualify.os, "urandom", return_value=nonce_bytes):
            self.assertEqual(client.require("initial"), oracle_digest)
        self.assertEqual(client._oracle_sha256, oracle_digest)

        client._channel = channel_for("cycle-1", "c" * 64)
        with mock.patch.object(qualify.os, "urandom", return_value=nonce_bytes), \
                self.assertRaisesRegex(
                    qualify.Blocked, "oracle identity changed"):
            client.require("cycle-1")

        malformed = mock.Mock()
        malformed.recv.side_effect = [bytes([value]) for value in b"[]\n"]
        client._channel = malformed
        with mock.patch.object(qualify.os, "urandom", return_value=nonce_bytes), \
                self.assertRaisesRegex(
                    qualify.Blocked, "response identity mismatch"):
            client.require("cycle-1")


    def test_admission_client_requires_string_oracle_digest(self):
        client = object.__new__(qualify.SourceAdmissionClient)
        client._validated_source = "a" * 40
        client._oracle_sha256 = None
        client._executed_helper_sha256 = "8" * 64
        client._physical_control_inputs_sha256 = {
            item: "c" * 64 for item in qualify.PHYSICAL_CONTROL_INPUT_PATHS
        }
        response = {
            "schema": qualify.SOURCE_ADMISSION_SCHEMA,
            "status": "PASS",
            "phase": "initial",
            "source_sha": "a" * 40,
            "nonce": "b" * 32,
            "oracle_sha256": int("9" * 64),
        }
        wire = (json.dumps(response) + "\n").encode("ascii")
        channel = mock.Mock()
        channel.recv.side_effect = (bytes([value]) for value in wire)
        client._channel = channel
        with mock.patch.object(qualify.os, "urandom", return_value=b"\xbb" * 16), \
                self.assertRaisesRegex(
                    qualify.Blocked, "source admission response identity mismatch"):
            client.require("initial")
        self.assertIsNone(client._oracle_sha256)

        channel.recv.side_effect = (bytes([value]) for value in b"{}\n")
        with mock.patch.object(qualify.json, "loads",
                               side_effect=RecursionError("nested response")), \
                self.assertRaisesRegex(
                    qualify.Blocked, "source admission response is malformed"):
            client.require("initial")

    def test_parent_rejects_source_only_initial_before_publication(self):
        # Source-only phase messages are not sufficient to admit a physical
        # run; later synthetic phases must remain unconsumed after refusal.
        source_sha = "a" * 40
        hashes = {relative: "c" * 64
                  for relative in parent.PHYSICAL_CONTROL_INPUT_PATHS}
        records = []
        for phase in ("initial", "cycle-1", "cycle-2", "final"):
            records.append(
                (json.dumps({
                    "schema": parent.SOURCE_ADMISSION_SCHEMA,
                    "source_sha": source_sha,
                    "phase": phase,
                    "nonce": "b" * 32,
                    "physical_control_inputs_sha256": hashes,
                    "executed_helper_sha256": "8" * 64,
                }) + "\n").encode("ascii"))

        class FakeStream:
            def __init__(self):
                self.input = io.BytesIO(b"".join(records))
                self.output = io.BytesIO()

            def readline(self, limit):
                return self.input.readline(limit)

            def write(self, payload):
                return self.output.write(payload)

            def flush(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        stream = FakeStream()
        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = (connection, None)
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.return_value = 1
        with self._mock_owned_admission_peer(), mock.patch.object(
                parent, "_check_git_source") as check:
            result = parent._serve_admission(
                server, child, source_sha, "/usr/bin/git",
                "d" * 64, hashes, "8" * 64, 2)
        self.assertEqual(result, 2)
        self.assertEqual(check.call_count, 1)
        responses = [json.loads(line) for line in stream.output.getvalue().splitlines()]
        self.assertEqual([reply["status"] for reply in responses], ["BLOCKED"])
        self.assertEqual(responses[0]["phase"], "initial")
        self.assertEqual(
            responses[0]["reason"], "physical_admission_identity_missing")

    def test_missing_initial_parent_admission_blocks_even_on_child_failure(self):
        # A failed child cannot qualify or FAIL physical work before the first
        # authenticated source-admission phase has succeeded.
        class EarlyEofStream:
            def readline(self, _limit):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
        connection.makefile.return_value = EarlyEofStream()
        server = mock.Mock()
        server.accept.return_value = (connection, None)
        child = mock.Mock()
        child.poll.return_value = 1
        child.wait.return_value = 1
        stderr = io.StringIO()
        with self._mock_owned_admission_peer(), contextlib.redirect_stderr(stderr):
            result = parent._serve_admission(
                server, child, "a" * 40, "/usr/bin/git", "d" * 64,
                {path: "c" * 64
                 for path in parent.PHYSICAL_CONTROL_INPUT_PATHS},
                "8" * 64, 2)
        self.assertEqual(result, 2)
        self.assertIn(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "privileged_child_skipped_source_admission", stderr.getvalue())
        child.wait.assert_called_once_with(timeout=45)

        # If the parent must terminate a still-running child after EOF, the
        # resulting -SIGTERM is cleanup evidence, not a child-originated crash.
        connection.makefile.return_value = EarlyEofStream()
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = [-15, -15]
        stderr = io.StringIO()
        with self._mock_owned_admission_peer(), \
                contextlib.redirect_stderr(stderr):
            result = parent._serve_admission(
                server, child, "a" * 40, "/usr/bin/git", "d" * 64,
                {path: "c" * 64
                 for path in parent.PHYSICAL_CONTROL_INPUT_PATHS},
                "8" * 64, 2)
        self.assertEqual(result, 2)
        self.assertIn(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "privileged_child_skipped_source_admission", stderr.getvalue())
        self.assertNotIn("terminated_by_signal:15", stderr.getvalue())
        child.terminate.assert_called_once_with()
        self.assertEqual(
            child.wait.call_args_list,
            [mock.call(timeout=10), mock.call(timeout=45)])

    def test_parent_bounds_unadmitted_child_teardown_after_refusal(self):
        # A source-only request lacks physical target identity and must be
        # refused. If the privileged child then resists bounded cleanup, keep
        # that original refusal and the cleanup failure in the diagnostic.
        source_sha = "a" * 40
        hashes = {relative: "c" * 64
                  for relative in parent.PHYSICAL_CONTROL_INPUT_PATHS}
        request = {
            "schema": parent.SOURCE_ADMISSION_SCHEMA,
            "source_sha": source_sha,
            "phase": "initial",
            "nonce": "b" * 32,
            "physical_control_inputs_sha256": hashes,
            "executed_helper_sha256": "8" * 64,
        }

        class FakeStream:
            def __init__(self):
                self.input = io.BytesIO((json.dumps(request) + "\n").encode("ascii"))
                self.output = io.BytesIO()

            def readline(self, limit):
                return self.input.readline(limit)

            def write(self, payload):
                return self.output.write(payload)

            def flush(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        stream = FakeStream()
        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack(
            "3i", os.getpid(), 0, 0)
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = (connection, None)
        child = mock.Mock()
        child.pid = os.getpid()
        child.poll.return_value = None
        child.wait.side_effect = [
            subprocess.TimeoutExpired("qualifier", 10),
            subprocess.TimeoutExpired("qualifier", 5),
        ]
        stderr = io.StringIO()
        with mock.patch.object(parent, "_check_git_source"):
            with contextlib.redirect_stderr(stderr):
                with self.assertRaisesRegex(
                        parent.Blocked,
                        "unadmitted privileged qualifier did not terminate after kill"):
                    parent._serve_admission(
                        server, child, source_sha, "/usr/bin/git", "d" * 64,
                        hashes, "8" * 64, 2)
        self.assertEqual(
            child.wait.call_args_list,
            [mock.call(timeout=10), mock.call(timeout=5)])
        child.terminate.assert_called_once_with()
        child.kill.assert_called_once_with()
        response = json.loads(stream.output.getvalue().splitlines()[0])
        self.assertEqual(response["status"], "BLOCKED")
        self.assertEqual(response["reason"], "physical_admission_identity_missing")
        self.assertIn(
            "physical_admission_identity:phase=initial:", stderr.getvalue())

    def test_parent_runtime_channel_failure_reaps_unadmitted_child(self):
        source_sha = "a" * 40
        hashes = {relative: "c" * 64
                  for relative in parent.PHYSICAL_CONTROL_INPUT_PATHS}
        request = {
            "schema": parent.SOURCE_ADMISSION_SCHEMA,
            "source_sha": source_sha,
            "phase": "initial",
            "nonce": "b" * 32,
            "physical_control_inputs_sha256": hashes,
            "executed_helper_sha256": "8" * 64,
        }

        class FakeStream:
            def __init__(self):
                self.input = io.BytesIO((json.dumps(request) + "\n").encode("ascii"))

            def readline(self, limit):
                return self.input.readline(limit)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        stream = FakeStream()
        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
        connection.makefile.return_value = stream
        server = mock.Mock()
        server.accept.return_value = (connection, None)
        child = mock.Mock()
        child.poll.return_value = None
        # Real Popen.wait() reports -SIGTERM after the parent's intentional
        # cleanup; do not misclassify that parent-induced status as a crash.
        child.wait.side_effect = [-15, -15]
        stderr = io.StringIO()
        with self._mock_owned_admission_peer(), \
                mock.patch.object(parent, "_check_git_source"), \
                mock.patch.object(
                    parent, "_reply",
                    side_effect=BrokenPipeError("synthetic broken pipe")), \
                contextlib.redirect_stderr(stderr):
            result = parent._serve_admission(
                server, child, source_sha, "/usr/bin/git", "d" * 64,
                hashes, "8" * 64, 2)
        self.assertEqual(result, 2)
        self.assertIn(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT="
            "source_admission_runtime_error:initial:BrokenPipeError",
            stderr.getvalue())
        self.assertNotIn("terminated_by_signal:15", stderr.getvalue())
        child.terminate.assert_called_once_with()
        self.assertEqual(
            child.wait.call_args_list,
            [mock.call(timeout=10), mock.call(timeout=45)])

    def test_parent_keeps_source_only_admission_blocked_for_child_failures(self):
        source_sha = "a" * 40
        hashes = {relative: "c" * 64
                  for relative in parent.PHYSICAL_CONTROL_INPUT_PATHS}

        def record(phase):
            return (json.dumps({
                "schema": parent.SOURCE_ADMISSION_SCHEMA,
                "source_sha": source_sha,
                "phase": phase,
                "nonce": "b" * 32,
                "physical_control_inputs_sha256": hashes,
                "executed_helper_sha256": "8" * 64,
            }) + "\n").encode("ascii")

        class FakeStream:
            def __init__(self, phases):
                self.input = io.BytesIO(b"".join(record(phase) for phase in phases))
                self.output = io.BytesIO()

            def readline(self, limit):
                return self.input.readline(limit)

            def write(self, payload):
                return self.output.write(payload)

            def flush(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        def run(phases, returncode):
            stream = FakeStream(phases)
            connection = mock.MagicMock()
            connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
            connection.makefile.return_value = stream
            server = mock.Mock()
            server.accept.return_value = (connection, None)
            child = mock.Mock()
            child.poll.return_value = returncode
            child.wait.return_value = returncode
            stderr = io.StringIO()
            with self._mock_owned_admission_peer(), \
                    mock.patch.object(parent, "_check_git_source"), \
                    contextlib.redirect_stderr(stderr):
                result = parent._serve_admission(
                    server, child, source_sha, "/usr/bin/git", "d" * 64,
                    hashes, "8" * 64, 2)
            return result, stderr.getvalue()

        for returncode in (1, -9, 3):
            with self.subTest(returncode=returncode):
                result, stderr = run(["initial"], returncode)
                self.assertEqual(result, 2)
                self.assertIn("physical_admission_identity:", stderr)
                self.assertIn("authorization=BLOCKED", stderr)

    def test_parent_rejects_malformed_oracle_before_peer_admission(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.return_value = 2
        server = mock.Mock()
        with self.assertRaisesRegex(
                parent.Blocked, "source admission oracle digest is malformed"):
            parent._serve_admission(
                server, child, "a" * 40, "/usr/bin/git", "not-a-digest",
                {relative: "c" * 64
                 for relative in parent.PHYSICAL_CONTROL_INPUT_PATHS},
                "8" * 64, 2)
        server.accept.assert_not_called()
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=10)

    def test_client_reports_exact_blocked_provenance_boundary(self):
        source_sha = "a" * 40
        client = object.__new__(qualify.SourceAdmissionClient)
        client._validated_source = source_sha
        client._oracle_sha256 = None
        client._executed_helper_sha256 = "8" * 64
        client._physical_control_inputs_sha256 = {
            relative: "c" * 64 for relative in qualify.PHYSICAL_CONTROL_INPUT_PATHS
        }
        response = {
            "schema": qualify.SOURCE_ADMISSION_SCHEMA,
            "source_sha": source_sha,
            "phase": "final",
            "status": "BLOCKED",
            "nonce": "b" * 32,
            "oracle_sha256": "d" * 64,
            "reason": "current remote main differs from the validated source",
        }
        wire = (json.dumps(response) + "\n").encode("ascii")
        channel = mock.Mock()
        channel.recv.side_effect = [bytes([item]) for item in wire]
        client._channel = channel
        with mock.patch.object(qualify.os, "urandom", return_value=b"\xbb" * 16):
            with self.assertRaisesRegex(
                    qualify.Blocked,
                    "at final: current remote main differs"):
                client.require("final")

    def test_parent_hashes_oracle_from_validated_commit_object(self):
        source_sha = "a" * 40
        payload = b"exact committed oracle bytes\n"
        completed = __import__("subprocess").CompletedProcess
        size = completed(
            args=[], returncode=0,
            stdout=f"{len(payload)}\n".encode("ascii"), stderr=b"")
        contents = completed(
            args=[], returncode=0, stdout=payload, stderr=b"")
        with mock.patch.object(
                    parent.subprocess, "run",
                    side_effect=[size, contents]) as run:
            observed = parent._git_file_sha256(
                source_sha, ORACLE, "/usr/bin/git")
        self.assertEqual(observed, hashlib.sha256(payload).hexdigest())
        object_spec = (
            f"{source_sha}:tests/tools/primary-real-swap-oracle.py")
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["/usr/bin/git", "cat-file", "-s", object_spec])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/usr/bin/git", "show", object_spec])


    def test_parent_rejects_oversized_commit_input_before_buffering_blob(self):
        source_sha = "a" * 40
        completed = __import__("subprocess").CompletedProcess
        oversized = completed(
            args=[], returncode=0,
            stdout=f"{parent.MAX_COMMIT_SOURCE_INPUT_BYTES + 1}\n".encode("ascii"),
            stderr=b"")
        with mock.patch.object(
                parent.subprocess, "run", return_value=oversized) as run, \
                self.assertRaisesRegex(
                    parent.Blocked, "exceeds size boundary"):
            parent._git_file_bytes(source_sha, ORACLE, "/usr/bin/git")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(
            run.call_args.args[0][1:3], ["cat-file", "-s"])

    def test_unadmitted_privileged_child_cleanup_is_bounded(self):
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.side_effect = [
            __import__("subprocess").TimeoutExpired("qualifier", 10),
            __import__("subprocess").TimeoutExpired("qualifier", 5),
        ]
        with self.assertRaisesRegex(
                parent.Blocked, "did not terminate after kill"):
            parent._stop_unadmitted_child(child)
        child.terminate.assert_called_once_with()
        child.kill.assert_called_once_with()

    def test_unadmitted_child_cleanup_preserves_admission_failure(self):
        original = parent.Blocked("source admission timeout")
        with mock.patch.object(
                    parent, "_stop_unadmitted_child",
                    side_effect=parent.Blocked("synthetic child cleanup failure")), \
                self.assertRaisesRegex(
                    parent.Blocked,
                    "source admission timeout; privileged child cleanup also "
                    "failed: synthetic child cleanup failure"):
            parent._stop_unadmitted_child_preserving(mock.Mock(), original)

    def test_malformed_initial_admission_reaps_unadmitted_child(self):
        server = mock.Mock()
        connection = mock.MagicMock()
        server.accept.return_value = (connection, None)
        connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
        connection.makefile.return_value = io.BytesIO(b"not-json\n")
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.return_value = 1
        diagnostics = io.StringIO()

        with self._mock_owned_admission_peer(), mock.patch.object(
                    parent, "_stop_unadmitted_child") as stop_child, \
                contextlib.redirect_stderr(diagnostics):
            result = parent._serve_admission(
                server, child, "a" * 40, "/usr/bin/git", "b" * 64,
                {
                    item: "c" * 64
                    for item in parent.PHYSICAL_CONTROL_INPUT_PATHS
                },
                "8" * 64, 2)
        self.assertEqual(result, 2)
        self.assertIn(
            "BLOCKED_PRIMARY_REAL_SWAP_PARENT=source admission request is malformed",
            diagnostics.getvalue())
        stop_child.assert_called_once_with(child)

    def test_parent_parser_recursion_reaps_unadmitted_child(self):
        connection = mock.MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", 123, 0, 0)
        connection.makefile.return_value = io.BytesIO(b"{}\n")
        server = mock.Mock()
        server.accept.return_value = (connection, None)
        child = mock.Mock()
        child.poll.return_value = None
        child.wait.return_value = -15
        diagnostics = io.StringIO()
        with self._mock_owned_admission_peer(), mock.patch.object(parent.json, "loads",
                               side_effect=RecursionError("nested request")), \
                contextlib.redirect_stderr(diagnostics):
            result = parent._serve_admission(
                server, child, "a" * 40, "/usr/bin/git", "b" * 64,
                {item: "c" * 64 for item in parent.PHYSICAL_CONTROL_INPUT_PATHS},
                "8" * 64, 2)
        self.assertEqual(result, 2)
        child.terminate.assert_called_once_with()
        self.assertEqual(
            child.wait.call_args_list,
            [mock.call(timeout=10), mock.call(timeout=45)])
        self.assertIn("source admission request is malformed", diagnostics.getvalue())
        self.assertIn(
            "admission_refused:phase=initial:child_exit=-15:owned_cleanup=complete",
            diagnostics.getvalue())
        self.assertNotIn("nested request", diagnostics.getvalue())

    def test_parent_rejects_numeric_nonce_before_source_admission(self):
        hashes = {item: "c" * 64
                  for item in parent.PHYSICAL_CONTROL_INPUT_PATHS}
        request = {
            "schema": parent.SOURCE_ADMISSION_SCHEMA,
            "source_sha": "a" * 40,
            "phase": "initial",
            "nonce": int("1" * 32),
            "physical_control_inputs_sha256": hashes,
            "executed_helper_sha256": "8" * 64,
        }
        stream = io.BytesIO((json.dumps(request) + "\n").encode("ascii"))
        with self.assertRaisesRegex(parent.Blocked, "identity is invalid"):
            parent._read_request(stream, "a" * 40, hashes, "8" * 64)

    def test_default_control_path_uses_installed_package_layout(self):
        args = qualify.build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])
        self.assertEqual(args.swapzctl, "/usr/local/sbin/swapzctl")
        self.assertEqual(Path(args.oracle).resolve(), ORACLE.resolve())

    def test_physical_source_requires_main_equal_origin_main(self):
        source_sha = "a" * 40
        completed = __import__("subprocess").CompletedProcess
        good = [
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
            completed(args=[], returncode=0, stdout="main\n", stderr=""),
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
            completed(args=[], returncode=0, stdout="", stderr=""),
            completed(args=[], returncode=0,
                      stdout=source_sha + "\trefs/heads/main\n", stderr=""),
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
            completed(args=[], returncode=0, stdout="main\n", stderr=""),
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
        ]
        with mock.patch.object(parent, "_run", side_effect=good) as run:
            parent._check_git_source(source_sha, "/usr/bin/git")
        self.assertEqual(run.call_count, 8)
        remote_call = run.call_args_list[4]
        self.assertEqual(
            remote_call.args[0],
            ["/usr/bin/git", "ls-remote", "--exit-code",
             parent.CANONICAL_REMOTE_URL, "refs/heads/main"])
        self.assertEqual(remote_call.kwargs["cwd"], Path("/"))

        wrong_origin = list(good)
        wrong_origin[2] = completed(
            args=[], returncode=0, stdout="b" * 40 + "\n", stderr="")
        with mock.patch.object(parent, "_run", side_effect=wrong_origin), \
                self.assertRaisesRegex(parent.Blocked, "main == origin/main"):
            parent._check_git_source(source_sha, "/usr/bin/git")

        detached = list(good)
        detached[1] = completed(
            args=[], returncode=0, stdout="HEAD\n", stderr="")
        with mock.patch.object(parent, "_run", side_effect=detached), \
                self.assertRaisesRegex(parent.Blocked, "main == origin/main"):
            parent._check_git_source(source_sha, "/usr/bin/git")

        stale_remote = list(good)
        stale_remote[4] = completed(
            args=[], returncode=0, stdout="b" * 40 + "\trefs/heads/main\n", stderr="")
        with mock.patch.object(parent, "_run", side_effect=stale_remote), \
                self.assertRaisesRegex(parent.Blocked, "current remote main differs"):
            parent._check_git_source(source_sha, "/usr/bin/git")

        malformed_remote = list(good)
        malformed_remote[4] = completed(
            args=[], returncode=0,
            stdout=source_sha + "\trefs/heads/main\nextra\n", stderr="")
        with mock.patch.object(parent, "_run", side_effect=malformed_remote), \
                self.assertRaisesRegex(parent.Blocked, "observed=invalid"):
            parent._check_git_source(source_sha, "/usr/bin/git")

        unreachable_remote = list(good)
        unreachable_remote[4] = completed(
            args=[], returncode=128, stdout="", stderr="remote unavailable")
        with mock.patch.object(parent, "_run", side_effect=unreachable_remote), \
                self.assertRaisesRegex(parent.Blocked, "cannot verify the current remote"):
            parent._check_git_source(source_sha, "/usr/bin/git")

        # These final observations model local movement while the remote query
        # is in flight. The last local identity snapshot must reject it.
        for final_index, observed in (
                (5, "b" * 40 + "\n"),
                (6, "HEAD\n"),
                (7, "b" * 40 + "\n")):
            with self.subTest(final_index=final_index):
                concurrent_move = list(good)
                concurrent_move[final_index] = completed(
                    args=[], returncode=0, stdout=observed, stderr="")
                with mock.patch.object(
                        parent, "_run", side_effect=concurrent_move):
                    with self.assertRaisesRegex(
                            parent.Blocked,
                            "source_local_identity_changed:boundary=post_remote"):
                        parent._check_git_source(source_sha, "/usr/bin/git")

    def canonical_manifest(self):
        run_id = "1" * 32
        logical_pages = 1024
        logical_sectors = logical_pages * 8
        return (
            "schema=swapz-primary-manifest-v2\n"
            f"run_id={run_id}\n"
            f"source_sha={'2' * 40}\n"
            f"swapzctl_sha256={'3' * 64}\n"
            f"module_sha256={'4' * 64}\n"
            f"qualification_report_sha256={'5' * 64}\n"
            "device_major=8\n"
            "device_minor=1\n"
            "partuuid=f13428f6-01\n"
            "device_bytes=124787884032\n"
            f"original_header_sha256={'6' * 64}\n"
            f"logical_pages={logical_pages}\n"
            f"logical_sectors={logical_sectors}\n"
            "mapper_name=swapz-primary\n"
            f"mapper_uuid=SWAPZ-PRIMARY-{run_id}\n"
            f"dm_table=0 {logical_sectors} swapz 8:1 0 64 0 2 0 1 0 0\n"
        )

    def test_manifest_binds_run_mapper_source_artifacts_and_exact_table(self):
        parsed = qualify.parse_manifest(self.canonical_manifest())
        self.assertEqual(parsed["mapper_uuid"], "SWAPZ-PRIMARY-" + "1" * 32)
        self.assertEqual(parsed["logical_sectors_int"], 8192)
        self.assertEqual(parsed["device_major_int"], 8)

    def test_independent_primary_geometry_matches_safe_current_card(self):
        geometry = qualify.maximum_primary_geometry(124_787_884_032)
        self.assertEqual(geometry["physical_blocks"], 30_465_536)
        self.assertEqual(geometry["logical_pages"], 27_080_192)
        self.assertEqual(geometry["logical_sectors"], 216_641_536)
        self.assertEqual(geometry["logical_bytes"], 110_920_466_432)
        self.assertEqual(geometry["linux_swap_kib"], 108_320_764)
        self.assertEqual(geometry["gc_reserve_blocks"], 3_385_024)
        self.assertNotEqual(geometry["logical_pages"], 27_080_448)

        for invalid_bytes in (
                0,
                qualify.PAGE_BYTES + 1,
                (qualify.UINT32_MAX + 2) * qualify.PAGE_BYTES):
            with self.subTest(invalid_bytes=invalid_bytes), \
                    self.assertRaises(qualify.Blocked):
                qualify.maximum_primary_geometry(invalid_bytes)

    def test_prepared_manifest_capacity_must_match_independent_geometry(self):
        run_id = "1" * 32
        geometry = qualify.maximum_primary_geometry(124_787_884_032)
        text = (
            "schema=swapz-primary-manifest-v2\n"
            f"run_id={run_id}\n"
            f"source_sha={'2' * 40}\n"
            f"swapzctl_sha256={'3' * 64}\n"
            f"module_sha256={'4' * 64}\n"
            f"qualification_report_sha256={'5' * 64}\n"
            "device_major=8\n"
            "device_minor=1\n"
            "partuuid=f13428f6-01\n"
            "device_bytes=124787884032\n"
            f"original_header_sha256={'6' * 64}\n"
            f"logical_pages={geometry['logical_pages']}\n"
            f"logical_sectors={geometry['logical_sectors']}\n"
            "mapper_name=swapz-primary\n"
            f"mapper_uuid=SWAPZ-PRIMARY-{run_id}\n"
            f"dm_table=0 {geometry['logical_sectors']} swapz 8:1 0 64 0 2 0 1 0 0\n"
        )
        manifest = qualify.parse_manifest(text)
        plan = {
            "qualified_swapzctl_sha256": "3" * 64,
            "qualified_module_sha256": "4" * 64,
            "qualification_report_sha256": "5" * 64,
            "target_device_major": 8,
            "target_device_minor": 1,
            "target_device_bytes": 124_787_884_032,
            "logical_pages": geometry["logical_pages"],
            "logical_bytes": geometry["logical_bytes"],
            "linux_swap_kib": geometry["linux_swap_kib"],
            "gc_reserve_blocks": geometry["gc_reserve_blocks"],
        }
        qualify._validate_prepared_manifest(
            manifest, plan, "2" * 40, "f13428f6-01")

        stale = dict(plan)
        stale["logical_pages"] = 27_080_448
        with self.assertRaisesRegex(
                qualify.QualificationFailure, "production authority geometry"):
            qualify._validate_prepared_manifest(
                manifest, stale, "2" * 40, "f13428f6-01")

    def test_manifest_rejects_table_substitution_duplicate_and_bad_uuid(self):
        canonical = self.canonical_manifest()
        mutants = (
            canonical.replace("swapz 8:1", "swapz 8:2"),
            canonical + "run_id=" + "1" * 32 + "\n",
            canonical.replace("SWAPZ-PRIMARY-" + "1" * 32, "SWAPZ-PRIMARY-" + "7" * 32),
        )
        for mutant in mutants:
            with self.subTest(mutant=mutant[-100:]), self.assertRaises(qualify.Blocked):
                qualify.parse_manifest(mutant)

    def make_swap_header(self, logical_pages=1024, uuid_byte=1):
        header = bytearray(qualify.PAGE_BYTES)
        struct.pack_into("<I", header, qualify.SWAP_VERSION_OFFSET, 1)
        struct.pack_into("<I", header, qualify.SWAP_LAST_PAGE_OFFSET, logical_pages - 1)
        struct.pack_into("<I", header, qualify.SWAP_BAD_PAGES_OFFSET, 0)
        header[qualify.SWAP_UUID_OFFSET:qualify.SWAP_UUID_OFFSET + 16] = bytes([uuid_byte]) * 16
        header[-len(qualify.SWAP_MAGIC):] = qualify.SWAP_MAGIC
        return bytes(header)

    def test_linux_swap_header_requires_exact_manifest_geometry_and_nonzero_uuid(self):
        parsed = qualify.linux_swap_header(self.make_swap_header(), 1024)
        self.assertEqual(parsed["last_page"], 1023)
        self.assertEqual(
            parsed["uuid"], "01010101-0101-0101-0101-010101010101")
        for mutate in ("version", "last", "bad", "uuid", "magic"):
            header = bytearray(self.make_swap_header())
            if mutate == "version":
                struct.pack_into("<I", header, qualify.SWAP_VERSION_OFFSET, 2)
            elif mutate == "last":
                struct.pack_into("<I", header, qualify.SWAP_LAST_PAGE_OFFSET, 100)
            elif mutate == "bad":
                struct.pack_into("<I", header, qualify.SWAP_BAD_PAGES_OFFSET, 1)
            elif mutate == "uuid":
                header[qualify.SWAP_UUID_OFFSET:qualify.SWAP_UUID_OFFSET + 16] = bytes(16)
            else:
                header[-1] ^= 1
            with self.subTest(mutate=mutate), self.assertRaises(qualify.QualificationFailure):
                qualify.linux_swap_header(bytes(header), 1024)

    def test_dm_info_requires_one_exact_numeric_identity(self):
        identity = qualify.parse_dm_info("swapz-primary:SWAPZ-PRIMARY-abc:252:3:1\n")
        self.assertEqual(identity.major, 252)
        self.assertEqual(identity.open_count, 1)
        for text in ("", "a:b:c:d:e\n", "a:b:1:2:3\na:b:1:2:3\n"):
            with self.subTest(text=text), self.assertRaises(qualify.QualificationFailure):
                qualify.parse_dm_info(text)

    def test_dm_table_accepts_device_number_or_resolved_exact_backing(self):
        manifest = qualify.parse_manifest(self.canonical_manifest())
        direct = f"0 {manifest['logical_sectors_int']} swapz 8:1 0 64 0 2 0 1 0 0\n"
        self.assertEqual(qualify.parse_dm_table(direct, manifest)["backing_device"], (8, 1))

        def fake_stat(path):
            self.assertEqual(path, "/dev/sda1")
            return FakeStat(8, 1)

        named = direct.replace("8:1", "sda1")
        self.assertEqual(
            qualify.parse_dm_table(named, manifest, fake_stat)["backing_device"], (8, 1))

    def test_dm_identity_requires_independent_absence_when_dmsetup_fails(self):
        failed = __import__("subprocess").CompletedProcess(
            args=[], returncode=1, stdout="", stderr="query failed")
        with mock.patch.object(qualify, "_run", return_value=failed), \
                mock.patch.object(qualify, "_sysfs_dm_names", return_value=set()):
            self.assertIsNone(qualify._dm_identity())
        with mock.patch.object(qualify, "_run", return_value=failed), \
                mock.patch.object(
                    qualify, "_sysfs_dm_names",
                    return_value={qualify.MAPPER_NAME}), \
                self.assertRaisesRegex(
                    qualify.Blocked, "remains present in sysfs"):
            qualify._dm_identity()

    def test_lstat_errors_are_not_treated_as_path_absence(self):
        path = mock.Mock()
        path.lstat.side_effect = PermissionError("synthetic denial")
        with self.assertRaisesRegex(qualify.Blocked, "cannot inspect synthetic"):
            qualify._lstat_optional(path, "synthetic")

    def test_dm_table_rejects_substituted_backing_or_parameters(self):
        manifest = qualify.parse_manifest(self.canonical_manifest())
        canonical = f"0 {manifest['logical_sectors_int']} swapz 8:1 0 64 0 2 0 1 0 0\n"
        mutants = (
            canonical.replace("8:1", "8:2"),
            canonical.replace(" 64 ", " 32 "),
            canonical.replace(" swapz ", " linear "),
            canonical + canonical,
        )
        for mutant in mutants:
            with self.subTest(mutant=mutant), self.assertRaises(qualify.QualificationFailure):
                qualify.parse_dm_table(mutant, manifest)

    def test_status_requires_swapz_and_core_io_failure_tokens(self):
        status = qualify.parse_status(
            "0 8192 swapz version=1 logical_write=4096 logical_read=8192 "
            "physical_write=4096 physical_read=4096 failed=0 error=0\n")
        self.assertEqual(status["logical_read"], 8192)
        with self.assertRaises(qualify.QualificationFailure):
            qualify.parse_status("0 8192 linear logical_write=1 logical_read=1 physical_write=1 physical_read=1 failed=0 error=0")
        with self.assertRaises(qualify.QualificationFailure):
            qualify.parse_status("0 8192 swapz logical_write=1 logical_read=1 physical_write=1 failed=0 error=0")
        for malformed in (
            "0 8192 swapz logical_write=-1 logical_read=1 physical_write=1 "
            "physical_read=1 failed=0 error=0",
            "0 8192 swapz logical_write=1 logical_read=1 physical_write=1 "
            "physical_read=1 failed=2 error=0",
            "0 8192 swapz logical_write=bad logical_write=1 logical_read=1 "
            "physical_write=1 physical_read=1 failed=0 error=0",
        ):
            with self.subTest(malformed=malformed), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.parse_status(malformed)

    def test_vmstat_requires_both_kernel_swap_counters(self):
        with mock.patch.object(
                Path, "read_text",
                return_value="pswpin 7\npswpout 11\n"):
            self.assertEqual(
                qualify.read_vmstat(), {"pswpin": 7, "pswpout": 11})

        for payload in (
                "pswpin 7\n",
                "pswpout 11\n",
                "pswpin 7\npswpout 11\npswpout 12\n"):
            with self.subTest(payload=payload), \
                    mock.patch.object(Path, "read_text", return_value=payload), \
                    self.assertRaises(qualify.Blocked):
                qualify.read_vmstat()

    def test_block_geometry_preserves_ioctl_failure_when_close_also_fails(self):
        real_close = os.close

        def close_then_fail(descriptor):
            real_close(descriptor)
            raise OSError("synthetic close failure")

        with tempfile.NamedTemporaryFile() as temporary, \
                mock.patch.object(
                    qualify.fcntl, "ioctl",
                    side_effect=OSError("synthetic ioctl failure")), \
                mock.patch.object(
                    qualify.os, "close", side_effect=close_then_fail), \
                self.assertRaisesRegex(
                    qualify.Blocked,
                    "cannot verify block geometry.*synthetic ioctl failure; "
                    "cleanup also failed: .*synthetic close failure"):
            qualify._block_size(Path(temporary.name))

    def test_psi_and_memavailable_parsers_fail_closed_on_malformed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            pressure = Path(directory) / "memory.pressure"
            pressure.write_text(
                "some avg10=0.00 avg60=0.00 avg300=0.00 total=17\n"
                "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n",
                encoding="ascii")
            self.assertEqual(qualify._psi_total(pressure), 17)
            for payload in (
                    "some avg10=0 total=1 total=2\n",
                    "some avg10=0 total=1\nsome avg10=0 total=2\n",
                    "some avg10=0 total=bad\n"):
                with self.subTest(payload=payload):
                    pressure.write_text(payload, encoding="ascii")
                    with self.assertRaises(qualify.Blocked):
                        qualify._psi_total(pressure)

        for payload in (
                "MemAvailable: 1048576 MB\n",
                "MemAvailable: 1048576 kB\nMemAvailable: 1048576 kB\n",
                "MemAvailable: unavailable kB\n"):
            with self.subTest(payload=payload), \
                    mock.patch.object(Path, "read_text", return_value=payload), \
                    self.assertRaises(qualify.Blocked):
                qualify._mem_available_mib()

    def test_sustained_psi_window_detects_late_high_stall_period(self):
        window = qualify.PsiStallWindow(0.0, 0)
        # Ten quiet seconds must not dilute a later five-second high-stall
        # interval below the stop threshold.
        for second in range(1, 11):
            self.assertFalse(window.observe(float(second), 0))
        for second in range(11, 15):
            self.assertFalse(
                window.observe(float(second), (second - 10) * 900_000))
        self.assertTrue(window.observe(15.0, 4_500_000))

        with self.assertRaisesRegex(
                qualify.QualificationFailure, "PSI total regressed"):
            window.observe(16.0, 4_499_999)

    def positive_evidence(self):
        return dict(
            cgroup_swap_bytes=32 * qualify.MIB,
            cgroup_swap_peak=48 * qualify.MIB,
            min_swap_bytes=16 * qualify.MIB,
            expected_verified_pages=1024,
            oom_delta=0,
            oom_kill_delta=0,
            mapper_used_delta_kib=32 * 1024,
            fill_status_before={"logical_write": 0, "logical_read": 0, "physical_write": 0, "physical_read": 0, "failed": 0, "error": 0},
            fill_status_after={"logical_write": 32 * qualify.MIB, "logical_read": 0,
                               "physical_write": 8 * qualify.MIB, "physical_read": 0,
                               "failed": 0, "error": 0},
            verify_status_before={"logical_write": 32 * qualify.MIB, "logical_read": 0,
                                  "physical_write": 8 * qualify.MIB, "physical_read": 0,
                                  "failed": 0, "error": 0},
            verify_status_after={"logical_write": 32 * qualify.MIB,
                                 "logical_read": 32 * qualify.MIB,
                                 "physical_write": 8 * qualify.MIB,
                                 "physical_read": 8 * qualify.MIB,
                                 "failed": 0, "error": 0},
            lower_before=qualify.BlockStats(0, 0),
            lower_after_fill=qualify.BlockStats(0, 16 * 1024),
            lower_before_verify=qualify.BlockStats(0, 16 * 1024),
            lower_after_verify=qualify.BlockStats(16 * 1024, 16 * 1024),
            vm_before={"pswpin": 0, "pswpout": 0},
            vm_after_fill={"pswpin": 0, "pswpout": 10},
            vm_before_verify={"pswpin": 0, "pswpout": 10},
            vm_after_verify={"pswpin": 10, "pswpout": 10},
            oracle={"verified_pages": 1024, "verified_bytes": 1024 * qualify.PAGE_BYTES,
                    "mismatches": 0, "digest": "aa" * 32, "expected_digest": "aa" * 32},
        )

    def test_workload_pass_requires_swap_usage_target_write_read_lower_io_and_byte_oracle(self):
        qualify.evaluate_workload_evidence(**self.positive_evidence())

    def test_workload_mutants_each_fail_closed(self):
        base = self.positive_evidence()
        mutants = [
            {"cgroup_swap_bytes": 0},
            {"mapper_used_delta_kib": 0},
            {"mapper_used_delta_kib": 8 * 1024},
            {"oom_kill_delta": 1},
            {"fill_status_after": {**base["fill_status_after"], "logical_write": 0}},
            {"fill_status_after": {**base["fill_status_after"],
                                   "logical_write": 8 * qualify.MIB}},
            {"fill_status_after": {**base["fill_status_after"], "physical_write": 0}},
            {"verify_status_after": {**base["verify_status_after"], "logical_read": 0}},
            {"verify_status_after": {**base["verify_status_after"],
                                     "logical_read": 8 * qualify.MIB}},
            {"verify_status_after": {**base["verify_status_after"], "physical_read": 0}},
            {"lower_after_fill": qualify.BlockStats(0, 0)},
            {"lower_after_fill": qualify.BlockStats(0, 1)},
            {"lower_after_verify": qualify.BlockStats(0, 16 * 1024)},
            {"lower_after_verify": qualify.BlockStats(1, 16 * 1024)},
            {"vm_after_fill": {"pswpin": 0, "pswpout": 0}},
            {"vm_after_verify": {"pswpin": 0, "pswpout": 10}},
            {"oracle": {"verified_pages": 1024, "verified_bytes": 1024 * qualify.PAGE_BYTES,
                        "mismatches": 1, "digest": "aa", "expected_digest": "aa"}},
            {"oracle": {"verified_pages": 1024, "verified_bytes": 1024 * qualify.PAGE_BYTES,
                        "mismatches": 0, "digest": "aa", "expected_digest": "bb"}},
            {"oracle": {"verified_pages": 1023, "verified_bytes": 1024 * qualify.PAGE_BYTES,
                        "mismatches": 0, "digest": "aa", "expected_digest": "aa"}},
            {"oracle": {"verified_pages": 1024, "verified_bytes": 1023 * qualify.PAGE_BYTES,
                        "mismatches": 0, "digest": "aa", "expected_digest": "aa"}},
            {"verify_status_after": {**base["verify_status_after"], "failed": 1}},
        ]
        for mutant in mutants:
            evidence = dict(base)
            evidence.update(mutant)
            with self.subTest(mutant=mutant), self.assertRaises(qualify.QualificationFailure):
                qualify.evaluate_workload_evidence(**evidence)

    def test_stop_order_requires_active_then_inactive_mapper_then_absent(self):
        samples = [
            qualify.StopSample(1, True, True, True, True),
            qualify.StopSample(2, True, True, False, True),
            qualify.StopSample(3, False, False, False, True),
        ]
        result = qualify.evaluate_stop_samples(samples)
        self.assertTrue(result["swapoff_before_remove_witness"])

    def test_stop_order_tracker_is_constant_memory(self):
        tracker = qualify.StopOrderTracker()
        timestamp = 1
        for _ in range(10000):
            tracker.observe(
                qualify.StopSample(timestamp, True, True, True, True))
            timestamp += 1
        tracker.observe(
            qualify.StopSample(timestamp, True, True, False, True))
        timestamp += 1
        tracker.observe(
            qualify.StopSample(timestamp, False, False, False, True))
        evidence = tracker.result()
        self.assertEqual(evidence["samples"], 10002)
        self.assertFalse(hasattr(tracker, "samples"))

        sampler = qualify.StopSampler(
            (252, 1), "SWAPZ-PRIMARY-" + "1" * 32, "/dev/dm-1")
        self.assertFalse(hasattr(sampler, "samples"))

    def test_stop_order_rejects_out_of_order_and_regressing_witnesses(self):
        active = lambda timestamp: qualify.StopSample(
            timestamp, True, True, True, True)
        inactive = lambda timestamp: qualify.StopSample(
            timestamp, True, True, False, True)
        absent = lambda timestamp: qualify.StopSample(
            timestamp, False, False, False, True)
        for samples in (
            [inactive(1), active(2), absent(3)],
            [active(1), absent(2), inactive(3)],
            [active(1), inactive(2), absent(2)],
        ):
            with self.subTest(samples=samples), self.assertRaises(qualify.Blocked):
                qualify.evaluate_stop_samples(samples)
        for samples in (
            [active(1), inactive(2), active(3), absent(4)],
            [active(1), inactive(2), absent(3), inactive(4)],
        ):
            with self.subTest(samples=samples), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.evaluate_stop_samples(samples)

    def test_stop_order_rejects_mapper_absent_while_swap_inventory_still_active(self):
        samples = [
            qualify.StopSample(1, True, True, True, True),
            qualify.StopSample(2, False, False, True, True),
            qualify.StopSample(3, False, False, False, True),
        ]
        with self.assertRaisesRegex(qualify.QualificationFailure, "disappeared"):
            qualify.evaluate_stop_samples(samples)

    def test_stop_order_without_independent_inactive_present_witness_is_blocked(self):
        samples = [
            qualify.StopSample(1, True, True, True, True),
            qualify.StopSample(2, False, False, False, True),
        ]
        with self.assertRaisesRegex(qualify.Blocked, "swapoff before mapper removal"):
            qualify.evaluate_stop_samples(samples)

    def test_stop_order_rejects_identity_substitution(self):
        samples = [
            qualify.StopSample(1, True, True, True, False),
            qualify.StopSample(2, True, True, False, True),
            qualify.StopSample(3, False, False, False, True),
        ]
        with self.assertRaisesRegex(qualify.QualificationFailure, "identity changed"):
            qualify.evaluate_stop_samples(samples)

    def test_oracle_protocol_consumes_buffered_records_and_rejects_duplicates(self):
        read_fd, write_fd = os.pipe()
        pending = bytearray()
        try:
            with os.fdopen(read_fd, "rb", buffering=0) as output:
                process = mock.Mock(stdout=output)
                process.poll.return_value = None
                os.write(write_fd, (
                    b'ORACLE_WAITING={"pid":123}\n'
                    b'ORACLE_FILLED={"pages":4}\n'
                ))
                deadline = time.monotonic() + 1
                self.assertEqual(
                    qualify._oracle_event(process, "ORACLE_WAITING=",
                                          deadline, lambda: None, pending)["pid"], 123)
                self.assertEqual(
                    qualify._oracle_event(process, "ORACLE_FILLED=",
                                          deadline, lambda: None, pending)["pages"], 4)
                os.write(write_fd, b'ORACLE_VERIFIED={"mismatches":0,"mismatches":0}\n')
                with self.assertRaisesRegex(
                        qualify.QualificationFailure, "malformed JSON"):
                    qualify._oracle_event(process, "ORACLE_VERIFIED=",
                                          deadline, lambda: None, pending)
        finally:
            os.close(write_fd)

    def test_oracle_cleanup_handles_exit_races_without_waiting_for_other_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            (cgroup / "cgroup.procs").write_text("567\n", encoding="ascii")
            process = mock.Mock(pid=123)
            process.poll.return_value = None
            process.send_signal.side_effect = ProcessLookupError()
            process.wait.return_value = 0
            with mock.patch.object(qualify.time, "sleep",
                                   side_effect=AssertionError("waited for unrelated worker")):
                qualify._terminate_child(process, cgroup)
            process.wait.assert_called_once_with(timeout=5)

            timed_out = mock.Mock(pid=234)
            timed_out.poll.return_value = None
            timed_out.wait.side_effect = [
                __import__("subprocess").TimeoutExpired("oracle", 5), 0]
            timed_out.kill.side_effect = ProcessLookupError()
            with mock.patch.object(qualify.time, "sleep",
                                   side_effect=AssertionError("waited for unrelated worker")):
                qualify._terminate_child(timed_out, cgroup)
            self.assertEqual(timed_out.wait.call_count, 2)

    def test_cycle_telemetry_sampler_is_bounded_and_brackets_cycle(self):
        sampler = qualify.CycleTelemetrySampler()
        with mock.patch.object(
                    qualify, "_mem_available_mib", return_value=2048), \
                mock.patch.object(qualify, "_psi_total", return_value=100), \
                mock.patch.object(
                    qualify, "read_vmstat",
                    return_value={"pswpin": 7, "pswpout": 11}):
            sampler.start()
            evidence = sampler.stop()
        self.assertGreaterEqual(evidence["samples"], 1)
        self.assertGreater(
            evidence["ended_monotonic_ns"],
            evidence["started_monotonic_ns"])
        self.assertEqual(evidence["minimum_mem_available_mib"], 2048)
        self.assertEqual(evidence["memory_psi_some_usec_delta"], 0)
        self.assertEqual(evidence["pswpin_delta"], 0)
        self.assertEqual(evidence["pswpout_delta"], 0)
        self.assertFalse(hasattr(sampler, "samples_log"))

    def test_cycle_telemetry_start_interrupt_reaps_sampler_thread(self):
        sampler = qualify.CycleTelemetrySampler()
        fake_thread = mock.Mock()
        fake_thread.is_alive.return_value = False
        sampler._thread = fake_thread
        sampler._ready = mock.Mock()
        sampler._ready.wait.side_effect = KeyboardInterrupt()
        sampler._stop = mock.Mock()

        with self.assertRaises(KeyboardInterrupt):
            sampler.start()

        sampler._stop.set.assert_called_once_with()
        fake_thread.join.assert_called_once_with(
            timeout=qualify.CYCLE_TELEMETRY_THREAD_TIMEOUT_SECONDS)

    def test_cycle_telemetry_sampler_fails_closed_on_low_memavailable(self):
        sampler = qualify.CycleTelemetrySampler()
        with mock.patch.object(
                    qualify, "_mem_available_mib",
                    return_value=qualify.MIN_AVAILABLE_MIB - 1), \
                mock.patch.object(qualify, "_psi_total", return_value=100), \
                mock.patch.object(
                    qualify, "read_vmstat",
                    return_value={"pswpin": 7, "pswpout": 11}), \
                self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "MemAvailable crossed"):
            sampler.start()
        self.assertFalse(sampler._thread.is_alive())

    def test_stop_sampler_preserves_definite_failure_classification(self):
        sampler = qualify.StopSampler(
            (252, 1), "SWAPZ-PRIMARY-" + "1" * 32, "/dev/dm-1")
        sampler._stop = mock.Mock()
        sampler._thread = mock.Mock()
        sampler._thread.is_alive.return_value = False
        sampler.error = qualify.QualificationFailure("identity changed")
        with self.assertRaisesRegex(
                qualify.QualificationFailure,
                "stop sampler failed: identity changed"):
            sampler.stop()

    def test_stop_sampler_is_stopped_when_final_delay_is_interrupted(self):
        run_id = "1" * 32
        manifest = {"run_id": run_id}
        active = {
            "mapper_device": (252, 1),
            "mapper_uuid": "SWAPZ-PRIMARY-" + run_id,
            "swap_path": "/dev/dm-1",
        }
        stopped = __import__("subprocess").CompletedProcess(
            args=[], returncode=0,
            stdout=f"PRIMARY_STOP=COMPLETE run_id={run_id} swapoff=true\n",
            stderr="")
        sampler = mock.Mock()
        sampler.stop.return_value = {"normal": True}
        with mock.patch.object(qualify, "StopSampler", return_value=sampler), \
                mock.patch.object(qualify, "_primary", return_value=stopped), \
                mock.patch.object(qualify, "_post_stop_verify"), \
                mock.patch.object(
                    qualify.time, "sleep",
                    side_effect=[None, KeyboardInterrupt()]), \
                self.assertRaises(KeyboardInterrupt):
            qualify._normal_stop(
                Path("/synthetic/swapzctl"), manifest, active, set(),
                "f13428f6-01", 60)
        sampler.stop.assert_called_once_with()

    def test_interrupted_primary_stop_reconciles_through_recover(self):
        manifest = {"run_id": "1" * 32}
        interrupted = qualify.QualificationFailure("synthetic stop timeout")
        recovered = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(
                    qualify, "_primary", side_effect=[interrupted, recovered]) as primary, \
                mock.patch.object(qualify, "read_state", return_value={
                    "run_id": manifest["run_id"], "stage": "STOPPING"}), \
                mock.patch.object(qualify, "_verify_completed_cleanup") as verify, \
                self.assertRaisesRegex(
                    qualify.QualificationFailure, "synthetic stop timeout"):
            qualify._normal_stop(
                Path("/synthetic/swapzctl"), manifest, None, set(),
                "f13428f6-01", 60)
        self.assertEqual(
            [call.args[1] for call in primary.call_args_list],
            ["stop", "recover"])
        verify.assert_called_once()

    def test_definite_primary_stop_failure_is_not_masked_by_sampler_blocked(self):
        manifest = {"run_id": "1" * 32}
        active = {"mapper_device": (252, 1), "mapper_uuid": "SWAPZ-PRIMARY-" + "1" * 32,
                  "swap_path": "/dev/dm-1"}
        stopped = __import__("subprocess").CompletedProcess(
            args=[], returncode=2, stdout="", stderr="BLOCKED: swapoff failed")
        sampler = mock.Mock()
        sampler.stop.side_effect = qualify.Blocked("missed transition witness")
        with mock.patch.object(qualify, "StopSampler", return_value=sampler), \
                mock.patch.object(qualify, "_primary", return_value=stopped), \
                mock.patch.object(qualify.time, "sleep", return_value=None), \
                self.assertRaises(qualify.QualificationFailure) as raised:
            qualify._normal_stop(
                Path("/synthetic/swapzctl"), manifest, active, set(),
                "f13428f6-01", 60)
        message = str(raised.exception)
        self.assertIn("primary stop/swapoff failed rc=2", message)
        self.assertIn("no force cleanup attempted", message)
        self.assertIn(
            "stop sampler also failed: missed transition witness", message)

    def test_sampler_failure_does_not_skip_post_stop_verification(self):
        run_id = "1" * 32
        manifest = {"run_id": run_id}
        active = {
            "mapper_device": (252, 1),
            "mapper_uuid": "SWAPZ-PRIMARY-" + run_id,
            "swap_path": "/dev/dm-1",
        }
        stopped = __import__("subprocess").CompletedProcess(
            args=[], returncode=0,
            stdout=f"PRIMARY_STOP=COMPLETE run_id={run_id} swapoff=true\n",
            stderr="")
        sampler = mock.Mock()
        sampler.stop.side_effect = qualify.Blocked("sampler evidence missing")
        with mock.patch.object(qualify, "StopSampler", return_value=sampler), \
                mock.patch.object(qualify, "_primary", return_value=stopped), \
                mock.patch.object(qualify.time, "sleep", return_value=None), \
                mock.patch.object(
                    qualify, "_post_stop_verify",
                    side_effect=qualify.QualificationFailure(
                        "mapper cleanup incomplete")) as post_verify, \
                self.assertRaises(qualify.QualificationFailure) as raised:
            qualify._normal_stop(
                Path("/synthetic/swapzctl"), manifest, active, set(),
                "f13428f6-01", 60)
        post_verify.assert_called_once()
        self.assertIn("mapper cleanup incomplete", str(raised.exception))
        self.assertIn("sampler evidence missing", str(raised.exception))

    def test_run_cycle_requires_parent_revalidation_before_prepare(self):
        admission = mock.Mock()
        admission.require.side_effect = qualify.Blocked(
            "unprivileged source admission refused at cycle-1")
        primary = mock.Mock()
        with mock.patch.object(qualify, "read_swap_rows", return_value=[]), \
                mock.patch.object(
                    qualify, "_validate_precycle_state", return_value=None), \
                mock.patch.object(
                    qualify, "_kernel_log_snapshot", return_value=[]), \
                mock.patch.object(qualify, "_primary", primary), \
                self.assertRaisesRegex(
                    qualify.Blocked, "source admission refused"):
            qualify.run_cycle(
                1, swapzctl=Path("/synthetic/swapzctl"),
                oracle_path=Path("/synthetic/oracle"),
                validated_source="2" * 40,
                plan={}, selector_partuuid="f13428f6-01",
                selector_evidence=qualify.SelectorEvidence("f13428f6-01", (1,)),
                authorization_snapshot={},
                target_device=(8, 1), target_parent_device=(8, 0),
                workload_mib=384, resident_mib=128, swap_limit_mib=384,
                timeout_seconds=60, prior_run_ids=set(),
                prior_swap_uuids=set(), admission=admission)
        admission.require.assert_called_once_with("cycle-1")
        primary.assert_not_called()


    def test_run_cycle_selector_revalidation_blocks_before_any_primary_operation(self):
        admission = mock.Mock()
        primary = mock.Mock()
        with mock.patch.object(qualify, "read_swap_rows", return_value=[]), \
                mock.patch.object(qualify, "_validate_precycle_state"), \
                mock.patch.object(qualify, "_kernel_log_snapshot", return_value=[]), \
                mock.patch.object(
                    qualify, "_require_selector_at_policy_use",
                    side_effect=qualify.Blocked(
                        "primary selector phase=policy_use expected=pinned "
                        "observed=changed errno=none; action=BLOCK-before-prepare")
                ) as revalidate, \
                mock.patch.object(qualify, "_primary", primary), \
                self.assertRaisesRegex(qualify.Blocked, "phase=policy_use"):
            qualify.run_cycle(
                1, swapzctl=Path("/synthetic/swapzctl"),
                oracle_path=Path("/synthetic/oracle"),
                validated_source="2" * 40, plan={},
                selector_partuuid="f13428f6-01",
                selector_evidence=qualify.SelectorEvidence("f13428f6-01", (1,)),
                authorization_snapshot={}, target_device=(8, 1),
                target_parent_device=(8, 0),
                workload_mib=384, resident_mib=128, swap_limit_mib=384,
                timeout_seconds=60, prior_run_ids=set(), prior_swap_uuids=set(),
                admission=admission)
        admission.require.assert_called_once_with("cycle-1")
        revalidate.assert_called_once()
        primary.assert_not_called()

    def test_independent_active_verification_failure_still_requests_normal_stop(self):
        run_id = "1" * 32
        manifest = {"run_id": run_id}
        prepare = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout=f"PRIMARY_PREPARE=READY run_id={run_id} source={'2' * 40} logical_pages=1 logical_bytes=4096 swap_kib=0\n", stderr="")
        start = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout=f"PRIMARY_START=ACTIVE run_id={run_id} mapper=/dev/mapper/swapz-primary swapon=true\n", stderr="")
        normal_stop = mock.Mock(return_value=None)
        admission = mock.Mock()
        with mock.patch.object(qualify, "read_swap_rows", return_value=[]), \
                mock.patch.object(qualify, "_validate_precycle_state", return_value=None), \
                mock.patch.object(qualify, "_kernel_log_snapshot", return_value=[]), \
                mock.patch.object(qualify, "_reject_relevant_kernel_errors", return_value=None), \
                mock.patch.object(qualify, "_require_selector_at_policy_use"), \
                mock.patch.object(qualify, "_primary", side_effect=[prepare, start]), \
                mock.patch.object(qualify, "read_state", side_effect=[
                    {"run_id": run_id, "stage": "READY"},
                    {"run_id": run_id, "stage": "ACTIVE"},
                    {"run_id": run_id, "stage": "ACTIVE"},
                ]), \
                mock.patch.object(qualify, "read_manifest", return_value=manifest), \
                mock.patch.object(qualify, "_validate_prepared_manifest", return_value=None), \
                mock.patch.object(qualify, "verify_loaded_module_provenance",
                                  return_value={"build_source_sha": "2" * 40}), \
                mock.patch.object(qualify, "verify_active_mapper",
                                  side_effect=qualify.QualificationFailure("independent active proof failed")), \
                mock.patch.object(qualify, "_normal_stop", normal_stop), \
                self.assertRaisesRegex(qualify.QualificationFailure, "independent active proof failed"):
            qualify.run_cycle(
                1, swapzctl=Path("/synthetic/swapzctl"),
                oracle_path=Path("/synthetic/oracle"), validated_source="2" * 40,
                plan={}, selector_partuuid="f13428f6-01",
                selector_evidence=qualify.SelectorEvidence("f13428f6-01", (1,)),
                authorization_snapshot={}, target_device=(8, 1),
                target_parent_device=(8, 0),
                workload_mib=384, resident_mib=128, swap_limit_mib=384,
                timeout_seconds=60, prior_run_ids=set(), prior_swap_uuids=set(),
                admission=admission)
        admission.require.assert_called_once_with("cycle-1")
        normal_stop.assert_called_once()
        self.assertIsNone(normal_stop.call_args.args[2])

    def test_workload_keyboard_interrupt_still_requests_normal_stop(self):
        run_id = "1" * 32
        manifest = {"run_id": run_id}
        active = {
            "mapper_device": (252, 1),
            "mapper_uuid": "SWAPZ-PRIMARY-" + run_id,
            "swap_path": "/dev/dm-1",
            "swap_uuid": "2" * 32,
            "swap_priority": 5,
        }
        prepare = __import__("subprocess").CompletedProcess(
            args=[], returncode=0,
            stdout=f"PRIMARY_PREPARE=READY run_id={run_id} source={'2' * 40} "
                   "logical_pages=1 logical_bytes=4096 swap_kib=0\n",
            stderr="")
        start = __import__("subprocess").CompletedProcess(
            args=[], returncode=0,
            stdout=f"PRIMARY_START=ACTIVE run_id={run_id} "
                   "mapper=/dev/mapper/swapz-primary swapon=true\n",
            stderr="")
        normal_stop = mock.Mock(return_value={"normal": True})
        telemetry = mock.Mock()
        telemetry.stop.return_value = {
            "samples": 1,
            "started_monotonic_ns": 1,
            "ended_monotonic_ns": 2,
            "minimum_mem_available_mib": 2048,
            "memory_psi_some_usec_delta": 0,
            "pswpin_delta": 0,
            "pswpout_delta": 0,
        }
        admission = mock.Mock()
        with mock.patch.object(qualify, "read_swap_rows", return_value=[]), \
                mock.patch.object(qualify, "_validate_precycle_state"), \
                mock.patch.object(qualify, "_kernel_log_snapshot", return_value=[]), \
                mock.patch.object(qualify, "_reject_relevant_kernel_errors"), \
                mock.patch.object(qualify, "_require_selector_at_policy_use"), \
                mock.patch.object(qualify, "_primary", side_effect=[prepare, start]), \
                mock.patch.object(qualify, "read_state", side_effect=[
                    {"run_id": run_id, "stage": "READY"},
                    {"run_id": run_id, "stage": "ACTIVE"},
                ]), \
                mock.patch.object(qualify, "read_manifest", return_value=manifest), \
                mock.patch.object(qualify, "_validate_prepared_manifest"), \
                mock.patch.object(
                    qualify, "verify_loaded_module_provenance",
                    return_value={"build_source_sha": "2" * 40}), \
                mock.patch.object(
                    qualify, "verify_active_mapper", return_value=active), \
                mock.patch.object(
                    qualify, "_run_workload", side_effect=KeyboardInterrupt()), \
                mock.patch.object(
                    qualify, "CycleTelemetrySampler",
                    return_value=telemetry), \
                mock.patch.object(qualify, "_normal_stop", normal_stop), \
                self.assertRaises(KeyboardInterrupt):
            qualify.run_cycle(
                1, swapzctl=Path("/synthetic/swapzctl"),
                oracle_path=Path("/synthetic/oracle"),
                validated_source="2" * 40,
                plan={}, selector_partuuid="f13428f6-01",
                selector_evidence=qualify.SelectorEvidence("f13428f6-01", (1,)),
                authorization_snapshot={},
                target_device=(8, 1), target_parent_device=(8, 0),
                workload_mib=384, resident_mib=128, swap_limit_mib=384,
                timeout_seconds=60, prior_run_ids=set(),
                prior_swap_uuids=set(), admission=admission)
        telemetry.start.assert_called_once_with()
        telemetry.stop.assert_called_once_with()
        normal_stop.assert_called_once()
        self.assertEqual(normal_stop.call_args.args[2], active)

    def test_failed_start_in_recovery_state_uses_only_primary_recover(self):
        manifest = {"run_id": "1" * 32}
        recovered = __import__("subprocess").CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(qualify, "read_state", return_value={
                    "run_id": manifest["run_id"], "stage": "RECOVERY_REQUIRED"}), \
                mock.patch.object(qualify, "_primary", return_value=recovered) as primary, \
                mock.patch.object(qualify, "_verify_completed_cleanup", return_value=None), \
                self.assertRaisesRegex(qualify.QualificationFailure, "start failed"):
            qualify._cleanup_failed_start(
                Path("/synthetic/swapzctl"), manifest, set(), "f13428f6-01",
                60, "start failed")
        primary.assert_called_once_with(
            Path("/synthetic/swapzctl"), "recover", 60, admitted=True)

    def test_kernel_log_delta_fails_closed_on_ring_rewrite(self):
        self.assertEqual(qualify._kernel_log_delta(["a"], ["a", "b"]), ["b"])
        with self.assertRaises(qualify.Blocked):
            qualify._kernel_log_delta(["a", "b"], ["b", "c"])

    def test_relevant_kernel_errors_are_rejected(self):
        qualify._reject_relevant_kernel_errors(["unrelated harmless warning"])
        for line in ("dm_swapz: failed target", "BUG: unable to handle", "task foo blocked for more than 120 seconds hung task"):
            with self.subTest(line=line), self.assertRaises(qualify.QualificationFailure):
                qualify._reject_relevant_kernel_errors([line])

    def test_workload_bounds_require_128_mib_swap_opportunity(self):
        with self.assertRaisesRegex(qualify.Blocked, "at least 128 MiB"):
            qualify.preflight_workload_environment(192, 128, 192)
        with self.assertRaises(qualify.Blocked):
            qualify.preflight_workload_environment(384, 128, 200)

    def test_frozen_acceptance_manifest_binds_real_swap_parameters(self):
        manifest = json.loads(
            (ROOT / "docs/production-acceptance.json").read_text())
        accepted = qualify.validate_acceptance_manifest(
            manifest,
            cycles=qualify.DEFAULT_CYCLES,
            workload_mib=qualify.DEFAULT_WORKLOAD_MIB,
            resident_mib=qualify.DEFAULT_RESIDENT_MIB,
            swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
            timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(accepted["status"], "FROZEN")
        self.assertEqual(
            qualify.acceptance_manifest_sha256(),
            hashlib.sha256(
                (ROOT / "docs/production-acceptance.json").read_bytes()
            ).hexdigest())

        with self.assertRaisesRegex(qualify.Blocked, "workload_mib"):
            qualify.validate_acceptance_manifest(
                manifest,
                cycles=qualify.DEFAULT_CYCLES,
                workload_mib=qualify.DEFAULT_WORKLOAD_MIB - 1,
                resident_mib=qualify.DEFAULT_RESIDENT_MIB,
                swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
                timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS)

        weakened = json.loads(json.dumps(manifest))
        weakened["primary_real_swap"]["minimum_swap_traffic_mib"] -= 1
        with self.assertRaisesRegex(
                qualify.Blocked, "minimum_swap_traffic_mib"):
            qualify.validate_acceptance_manifest(
                weakened,
                cycles=qualify.DEFAULT_CYCLES,
                workload_mib=qualify.DEFAULT_WORKLOAD_MIB,
                resident_mib=qualify.DEFAULT_RESIDENT_MIB,
                swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
                timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS)

        unfrozen = json.loads(json.dumps(manifest))
        unfrozen["status"] = "DRAFT"
        with self.assertRaisesRegex(qualify.Blocked, "canonical and frozen"):
            qualify.validate_acceptance_manifest(
                unfrozen,
                cycles=qualify.DEFAULT_CYCLES,
                workload_mib=qualify.DEFAULT_WORKLOAD_MIB,
                resident_mib=qualify.DEFAULT_RESIDENT_MIB,
                swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
                timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS)

    def test_github_actions_is_always_blocked_before_physical_execution(self):
        args = qualify.build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}, clear=False), \
                self.assertRaisesRegex(qualify.Blocked, "GitHub-hosted CI"):
            qualify.execute(args)

    def test_source_admission_transport_failure_is_blocked(self):
        client = object.__new__(qualify.SourceAdmissionClient)
        client._validated_source = "a" * 40
        client._executed_helper_sha256 = "8" * 64
        client._physical_control_inputs_sha256 = {
            item: "d" * 64
            for item in qualify.PHYSICAL_CONTROL_INPUT_PATHS
        }
        client._channel = mock.Mock()
        client._channel.sendall.side_effect = BrokenPipeError()
        with self.assertRaisesRegex(
                qualify.Blocked, "source admission transport failed at cycle-1"):
            client.require("cycle-1")

    def test_privileged_helper_has_no_git_source_admission_path(self):
        source = HELPER.read_text(encoding="utf-8")
        admission_parent = PARENT.read_text(encoding="utf-8")
        self.assertNotIn("_check_git_source", source)
        self.assertNotIn('["git",', source)
        self.assertIn("SO_PEERCRED", source)
        self.assertIn('"oracle_sha256"', source)
        self.assertIn('admission.require(f"cycle-{index}")', source)
        self.assertIn('admission.require("final")', source)
        self.assertIn("def _check_git_source(", admission_parent)
        self.assertIn('_trusted_executable("git")', admission_parent)
        self.assertIn('"ls-remote"', admission_parent)
        self.assertIn("os.geteuid() == 0", admission_parent)
        self.assertIn("SO_PEERCRED", admission_parent)
        self.assertIn("def _git_file_sha256(", admission_parent)
        self.assertIn('"show"', admission_parent)
        self.assertIn('"oracle_sha256"', admission_parent)

    def test_helper_has_no_direct_swapoff_swapon_or_mapper_remove_command(self):
        source = HELPER.read_text(encoding="utf-8")
        self.assertNotIn('["swapoff"', source)
        self.assertNotIn('["swapon"', source)
        self.assertNotIn('["dmsetup", "remove"', source)
        self.assertIn('"primary", action', source)

    def test_private_helper_result_codes_are_distinct(self):
        self.assertIn("return 2", HELPER.read_text(encoding="utf-8"))
        self.assertIn("return 1", HELPER.read_text(encoding="utf-8"))
        self.assertIn("return 0", HELPER.read_text(encoding="utf-8"))
        self.assertIn("PASS_PRIMARY_REAL_SWAP=", HELPER.read_text(encoding="utf-8"))
        self.assertIn("FAIL_PRIMARY_REAL_SWAP=", HELPER.read_text(encoding="utf-8"))
        self.assertIn("BLOCKED_PRIMARY_REAL_SWAP=", HELPER.read_text(encoding="utf-8"))


    def test_production_status_uses_signed_error_token(self):
        status = qualify.parse_status(
            "0 8192 swapz logical_write=4096 logical_read=4096 "
            "physical_write=4096 physical_read=4096 failed=0 error=0\n")
        self.assertEqual(status["error"], 0)
        with self.assertRaisesRegex(qualify.QualificationFailure, "lacks numeric token error"):
            qualify.parse_status(
                "0 8192 swapz logical_write=4096 logical_read=4096 "
                "physical_write=4096 physical_read=4096 failed=0 last_error=0\n")

    def test_mapper_ownership_admission_rejects_preexisting_swapz_state(self):
        canonical = {
            "module_mapper_inventory_read": True,
            "swapz_mapper_absent": True,
            "dm_swapz_module_loaded": False,
        }
        qualify.require_clean_mapper_ownership(canonical)
        for mutant in (
            {**canonical, "module_mapper_inventory_read": False},
            {**canonical, "swapz_mapper_absent": False},
            {**canonical, "dm_swapz_module_loaded": True},
        ):
            with self.subTest(mutant=mutant), self.assertRaisesRegex(
                    qualify.Blocked, "unexpected swapz mapper/module ownership"):
                qualify.require_clean_mapper_ownership(mutant)

    def test_concurrent_workload_split_keeps_two_finite_workers(self):
        self.assertEqual(qualify.split_concurrent_workload_mib(384), (192, 192))
        self.assertEqual(qualify.split_concurrent_workload_mib(129), (64, 65))
        with self.assertRaises(qualify.Blocked):
            qualify.split_concurrent_workload_mib(127)

    def test_per_worker_oracle_geometry_cannot_hide_short_or_swapped_records(self):
        worker_memory_mib = (64, 65)
        records = [
            {"pages": 64 * qualify.MIB // qualify.PAGE_BYTES,
             "bytes": 64 * qualify.MIB},
            {"pages": 65 * qualify.MIB // qualify.PAGE_BYTES,
             "bytes": 65 * qualify.MIB},
        ]
        qualify.require_oracle_worker_geometry(
            records, worker_memory_mib, "pages", "bytes", "fill")
        for changed in (
            [records[1], records[0]],
            [dict(records[0], pages=records[0]["pages"] - 1), records[1]],
            [dict(records[0], bytes=records[0]["bytes"] - qualify.PAGE_BYTES),
             dict(records[1], bytes=records[1]["bytes"] + qualify.PAGE_BYTES)],
            [records[0]],
            [dict(records[0], pages=float(records[0]["pages"])), records[1]],
            [dict(records[0], bytes=str(records[0]["bytes"])), records[1]],
            [None, records[1]],
        ):
            with self.subTest(changed=changed), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.require_oracle_worker_geometry(
                    changed, worker_memory_mib, "pages", "bytes", "fill")

    def test_aggregate_oracle_verification_requires_both_full_workers(self):
        record = {
            "verified_pages": 16384,
            "verified_bytes": 16384 * qualify.PAGE_BYTES,
            "mismatches": 0,
            "digest": "11" * 32,
            "expected_digest": "11" * 32,
        }
        aggregated = qualify.aggregate_oracle_verification([record, record])
        self.assertEqual(aggregated["verified_pages"], 32768)
        self.assertEqual(aggregated["mismatches"], 0)
        self.assertEqual(aggregated["digest"], aggregated["expected_digest"])
        with self.assertRaises(qualify.QualificationFailure):
            qualify.aggregate_oracle_verification([record])

    def test_initial_telemetry_failure_removes_cgroup_and_preserves_cleanup_error(self):
        cgroup = Path("/synthetic/swapz-cgroup")
        with mock.patch.object(qualify, "_cgroup_create", return_value=cgroup), \
                mock.patch.object(qualify, "_memory_events",
                                  side_effect=qualify.Blocked("missing oom")), \
                mock.patch.object(qualify, "_remove_cgroup") as remove:
            with self.assertRaisesRegex(qualify.Blocked, "missing oom"):
                qualify._run_workload({}, {}, ORACLE, 384, 128, 384, 60)
            remove.assert_called_once_with(cgroup)

        with mock.patch.object(qualify, "_cgroup_create", return_value=cgroup), \
                mock.patch.object(qualify, "_memory_events",
                                  side_effect=qualify.Blocked("missing oom")), \
                mock.patch.object(qualify, "_remove_cgroup",
                                  side_effect=qualify.QualificationFailure("rmdir failed")):
            with self.assertRaisesRegex(
                    qualify.Blocked, "missing oom; cleanup also failed: .*rmdir failed"):
                qualify._run_workload({}, {}, ORACLE, 384, 128, 384, 60)

    def test_preflight_telemetry_failure_keeps_both_causes_when_rmdir_fails(self):
        with mock.patch.object(qualify, "_mem_available_mib", return_value=4096), \
                mock.patch.object(qualify, "_cgroup_create",
                                  return_value=Path("/synthetic/preflight")), \
                mock.patch.object(qualify, "_read_uint",
                                  side_effect=qualify.Blocked("missing swap.current")), \
                mock.patch.object(qualify, "_remove_cgroup",
                                  side_effect=qualify.QualificationFailure("rmdir refused")):
            with self.assertRaisesRegex(
                    qualify.Blocked, "missing swap.current; cleanup also failed: .*rmdir refused"):
                qualify.preflight_workload_environment(384, 128, 384)

    def test_worker_migration_failure_reaps_child_and_closes_every_pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            child = mock.Mock(pid=321)
            child.stdin, child.stdout, child.stderr = (
                io.StringIO(), io.StringIO(), io.StringIO())
            original_write_text = Path.write_text

            def deny_migration(path, *args, **kwargs):
                if path.name == "cgroup.procs":
                    raise OSError("synthetic migration refusal")
                return original_write_text(path, *args, **kwargs)

            expected = qualify.SwapRow("/dev/dm-1", "partition", 512000, 0, 5, (252, 1))
            with mock.patch.object(qualify, "_cgroup_create", return_value=cgroup), \
                    mock.patch.object(qualify, "_memory_events",
                                      return_value={"oom": 0, "oom_kill": 0}), \
                    mock.patch.object(qualify, "_psi_total", return_value=0), \
                    mock.patch.object(qualify, "_write_control"), \
                    mock.patch.object(qualify, "read_swap_rows", return_value=[expected]), \
                    mock.patch.object(qualify.subprocess, "Popen", return_value=child), \
                    mock.patch.object(qualify, "_terminate_child") as terminate, \
                    mock.patch.object(qualify, "_remove_cgroup") as remove, \
                    mock.patch.object(Path, "write_text", deny_migration):
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "cannot move admitted oracle into dedicated cgroup errno=none") as caught:
                    qualify._run_workload(
                        {"run_id": "a" * 32}, {"mapper_device": (252, 1)},
                        ORACLE, 384, 128, 384, 60)
            self.assertIsInstance(caught.exception.__cause__, OSError)
            self.assertEqual(str(caught.exception.__cause__),
                             "synthetic migration refusal")
            self.assertIsNone(caught.exception.__cause__.errno)
            terminate.assert_called_once_with(child, cgroup)
            remove.assert_called_once_with(cgroup)
            self.assertTrue(all(pipe.closed for pipe in
                                (child.stdin, child.stdout, child.stderr)))

    def test_worker_pipe_cleanup_failure_retains_outer_cleanup_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            child = mock.Mock(pid=322)
            original_write_text = Path.write_text

            def deny_migration(path, *args, **kwargs):
                if path.name == "cgroup.procs":
                    raise OSError("synthetic migration refusal")
                return original_write_text(path, *args, **kwargs)

            expected = qualify.SwapRow(
                "/dev/dm-1", "partition", 512000, 0, 5, (252, 1))
            terminate = mock.Mock()
            close_pipes = mock.Mock(side_effect=[
                qualify.QualificationFailure("synthetic pipe close failure"),
                None,
            ])
            with mock.patch.object(qualify, "_cgroup_create", return_value=cgroup), \
                    mock.patch.object(
                        qualify, "_memory_events",
                        return_value={"oom": 0, "oom_kill": 0}), \
                    mock.patch.object(qualify, "_psi_total", return_value=0), \
                    mock.patch.object(qualify, "_write_control"), \
                    mock.patch.object(
                        qualify, "read_swap_rows", return_value=[expected]), \
                    mock.patch.object(
                        qualify.subprocess, "Popen", return_value=child), \
                    mock.patch.object(
                        qualify, "_terminate_child", terminate), \
                    mock.patch.object(
                        qualify, "_close_oracle_pipes", close_pipes), \
                    mock.patch.object(qualify, "_remove_cgroup") as remove, \
                    mock.patch.object(Path, "write_text", deny_migration):
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "cannot move admitted oracle into dedicated cgroup "
                        "errno=none; cleanup also failed: oracle pid 322 pipes: "
                        "synthetic pipe close failure"):
                    qualify._run_workload(
                        {"run_id": "a" * 32}, {"mapper_device": (252, 1)},
                        ORACLE, 384, 128, 384, 60)

            self.assertEqual(
                terminate.call_args_list,
                [mock.call(child, cgroup), mock.call(child, cgroup)])
            self.assertEqual(
                close_pipes.call_args_list,
                [mock.call(child), mock.call(child)])
            remove.assert_called_once_with(cgroup)

    def test_partial_cgroup_configuration_reports_cleanup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(qualify, "CGROUP_ROOT", Path(directory)), \
                    mock.patch.object(qualify, "_cgroup_prerequisites"), \
                    mock.patch.object(Path, "rmdir",
                                      side_effect=OSError("synthetic rmdir failure")):
                with self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "dedicated cgroup lacks required control.*partial cgroup cleanup "
                        "also failed: .*synthetic rmdir failure"):
                    qualify._cgroup_create("test", 128, 384)

    def test_cgroup_membership_is_exact_before_and_after_oracle_fill(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            membership = cgroup / "cgroup.procs"
            workers = [mock.Mock(pid=501), mock.Mock(pid=502)]
            for worker in workers:
                worker.poll.return_value = None
            membership.write_text("501\n502\n", encoding="ascii")
            qualify.require_oracle_worker_cgroup_ownership(cgroup, workers)
            membership.write_text("501\n", encoding="ascii")
            workers[1].poll.return_value = None
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "live oracle worker"):
                qualify.require_oracle_worker_cgroup_ownership(
                    cgroup, workers, allow_worker_exit=True)
            workers[1].poll.return_value = 0
            qualify.require_oracle_worker_cgroup_ownership(
                cgroup, workers, allow_worker_exit=True)
            membership.write_text("501\n503\n", encoding="ascii")
            with self.assertRaises(qualify.QualificationFailure):
                qualify.require_oracle_worker_cgroup_ownership(
                    cgroup, workers, allow_worker_exit=True)
            for contents in (
                    "501\n", "501\n502\n503\n", "501\n501\n",
                    "501\ninvalid\n", "-1\n502\n"):
                with self.subTest(contents=contents):
                    membership.write_text(contents, encoding="ascii")
                    with self.assertRaises(qualify.QualificationFailure):
                        qualify.require_oracle_worker_cgroup_ownership(cgroup, workers)
            membership.unlink()
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "cannot read dedicated oracle cgroup"):
                qualify.require_oracle_worker_cgroup_ownership(cgroup, workers)

    def test_partial_cgroup_without_process_inventory_removes_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory) / "swapz-primary-real-swap-preflight"
            with mock.patch.object(qualify, "CGROUP_ROOT", Path(directory)), \
                    mock.patch.object(qualify, "_cgroup_prerequisites"):
                with self.assertRaisesRegex(
                        qualify.QualificationFailure, "cgroup was removed"):
                    qualify._cgroup_create("preflight", 128, 384, admitted=True)
            self.assertFalse(cgroup.exists())

    def test_persistent_evidence_failed_sync_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            base.chmod(0o700)
            evidence = qualify.PersistentEvidence(
                base, "e" * 32, {"source_sha": "a" * 40},
                expected_uid=os.geteuid())
            with mock.patch.object(qualify.os, "fsync",
                                   side_effect=OSError("synthetic sync failure")):
                with self.assertRaisesRegex(
                        qualify.QualificationFailure, "synthetic sync failure"):
                    evidence.update("FAULT_INJECTED")
            self.assertEqual(
                sorted(path.name for path in base.iterdir()),
                [evidence.path.name])
            self.assertEqual(
                json.loads(evidence.path.read_text())["phase"], "ADMITTED")

    def test_final_cgroup_cleanup_removes_empty_group_when_process_inventory_is_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory) / "empty-cgroup"
            cgroup.mkdir()
            with self.assertRaisesRegex(
                    qualify.QualificationFailure,
                    "process inventory was unreadable; empty cgroup was removed"):
                qualify._remove_cgroup(cgroup)
            self.assertFalse(cgroup.exists())

    def test_final_cgroup_cleanup_preserves_unreadable_inventory_and_rmdir_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory) / "empty-cgroup"
            cgroup.mkdir()
            with mock.patch.object(
                    Path, "rmdir",
                    side_effect=OSError("synthetic rmdir failure")), \
                    self.assertRaisesRegex(
                        qualify.QualificationFailure,
                        "cannot inspect dedicated real-swap cgroup processes: "
                        ".*empty-group removal also failed: synthetic rmdir failure"):
                qualify._remove_cgroup(cgroup)
            self.assertTrue(cgroup.exists())

    def test_missing_or_duplicate_cgroup_oom_evidence_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / "memory.events"
            for payload in ("max 2\n", "oom 0\noom 1\noom_kill 0\n",
                            "oom 0\noom_kill nope\n"):
                with self.subTest(payload=payload):
                    events.write_text(payload)
                    with self.assertRaises(qualify.Blocked):
                        qualify._memory_events(events)
            events.write_text("oom 0\noom_kill 0\n")
            self.assertEqual(qualify._memory_events(events),
                             {"oom": 0, "oom_kill": 0})

    def test_cgroup_oom_counters_reject_increase_and_regression(self):
        initial_events = {"oom": 2, "oom_kill": 1}
        qualify.require_no_cgroup_oom_events(initial_events, dict(initial_events))
        for counter in ("oom", "oom_kill"):
            for difference in (-1, 1):
                with self.subTest(counter=counter, difference=difference):
                    observed_events = dict(initial_events)
                    observed_events[counter] += difference
                    with self.assertRaisesRegex(
                            qualify.QualificationFailure, "OOM counters changed"):
                        qualify.require_no_cgroup_oom_events(
                            initial_events, observed_events)

    def test_final_cgroup_oom_is_rejected_after_last_release(self):
        # Zero rounds avoid physical workers while exercising the final sample
        # independently of the in-round guard and verification checks.
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(qualify, "_cgroup_create", return_value=Path(directory)), \
                mock.patch.object(qualify, "_remove_cgroup"), \
                mock.patch.object(qualify, "_memory_events", side_effect=[
                    {"oom": 0, "oom_kill": 0}, {"oom": 1, "oom_kill": 0}]), \
                mock.patch.object(qualify, "_psi_total", return_value=0), \
                mock.patch.object(qualify, "REUSE_ROUNDS", 0), \
                mock.patch.object(qualify, "evaluate_reuse_rounds",
                                  return_value={"slot_reuse_proven": True}):
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "OOM counters changed"):
                qualify._run_workload({}, {}, Path(directory), 384, 128, 384, 240)

    def test_slot_reuse_requires_full_release_then_second_concurrent_allocation(self):
        rounds = [
            {
                "concurrent_workers": 2,
                "mapper_used_start_kib": 0,
                "mapper_used_delta_kib": 131072,
                "release_swap_current_bytes": 0,
                "mapper_used_released_kib": 0,
            },
            {
                "concurrent_workers": 2,
                "mapper_used_start_kib": 0,
                "mapper_used_delta_kib": 131072,
                "release_swap_current_bytes": 0,
                "mapper_used_released_kib": 0,
            },
        ]
        self.assertTrue(qualify.evaluate_reuse_rounds(rounds)["slot_reuse_proven"])
        for mutant in (
            [dict(rounds[0], concurrent_workers=1), rounds[1]],
            [dict(rounds[0], mapper_used_released_kib=4), rounds[1]],
            [rounds[0], dict(rounds[1], mapper_used_delta_kib=0)],
        ):
            with self.subTest(mutant=mutant), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.evaluate_reuse_rounds(mutant)

    def test_persistent_real_swap_result_binds_exact_target_byte_size(self):
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            'target_size_bytes = int(plan["target_device_bytes"])', source)
        self.assertEqual(
            source.count('"target_size_bytes": target_size_bytes'), 2)
        self.assertLess(
            source.index("verify_authorized_target("),
            source.index('target_size_bytes = int(plan["target_device_bytes"])'))

    def test_persistent_evidence_starts_fail_closed_and_finishes_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            base.chmod(0o700)
            evidence = qualify.PersistentEvidence(
                base, "a" * 32, {"source_sha": "b" * 40}, expected_uid=os.geteuid())
            initial = json.loads(evidence.path.read_text(encoding="utf-8"))
            self.assertEqual(initial["status"], "FAIL")
            self.assertEqual(initial["reason"], "qualification_interrupted_or_incomplete")
            self.assertEqual(stat.S_IMODE(evidence.path.stat().st_mode), 0o600)
            evidence.update("SYNTHETIC_ACTIVE", run_id="c" * 32)
            active = json.loads(evidence.path.read_text(encoding="utf-8"))
            self.assertEqual(active["status"], "FAIL")
            self.assertEqual(active["phase"], "SYNTHETIC_ACTIVE")
            evidence.finish("BLOCKED", "synthetic evidence gap")
            final = json.loads(evidence.path.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "BLOCKED")
            self.assertEqual(final["reason"], "synthetic evidence gap")
            # Any later non-PASS correction must not retain a nested PASS
            # result from a prior terminal record.
            evidence.finish("PASS", result={"status": "PASS"})
            evidence.finish("BLOCKED", "source changed at final")
            revoked = json.loads(evidence.path.read_text(encoding="utf-8"))
            self.assertEqual(revoked["status"], "BLOCKED")
            self.assertNotIn("result", revoked)


    def test_exited_worker_pid_is_not_valid_live_cgroup_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup = Path(directory)
            membership = cgroup / "cgroup.procs"
            workers = [mock.Mock(pid=501), mock.Mock(pid=502)]
            workers[0].poll.return_value = None
            workers[1].poll.return_value = 0
            membership.write_text("501\n502\n", encoding="ascii")
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "exited oracle PID"):
                qualify.require_oracle_worker_cgroup_ownership(
                    cgroup, workers, allow_worker_exit=True)
            membership.write_text("501\n", encoding="ascii")
            qualify.require_oracle_worker_cgroup_ownership(
                cgroup, workers, allow_worker_exit=True)
            workers[1].poll.return_value = None
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "live oracle worker"):
                qualify.require_oracle_worker_cgroup_ownership(
                    cgroup, workers, allow_worker_exit=True)

    def test_oracle_short_read_fails_without_byte_exact_success(self):
        class ShortReadMemory:
            def __init__(self):
                self.contents = bytearray(oracle.PAGE_BYTES)
                self.closed = False

            def __getitem__(self, key):
                if isinstance(key, slice):
                    return self.contents[key][:-1]
                return self.contents[key]

            def __setitem__(self, key, value):
                self.contents[key] = value

            def close(self):
                self.closed = True

        allocation = ShortReadMemory()
        commands = iter(("FILL", "VERIFY"))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(oracle, "MIB", oracle.PAGE_BYTES), \
                mock.patch.object(oracle, "MIN_MIB", 1), \
                mock.patch.object(oracle, "MAX_MIB", 1), \
                mock.patch.object(oracle, "_disable_dumps"), \
                mock.patch.object(oracle, "_read_command", side_effect=lambda: next(commands)), \
                mock.patch.object(oracle.mmap, "mmap", return_value=allocation), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = oracle.run_workload("ab" * 16, 1)
        self.assertEqual(result, 1)
        self.assertTrue(allocation.closed)
        self.assertIn("short oracle page read", stderr.getvalue())
        self.assertNotIn("ORACLE_VERIFIED=", stdout.getvalue())

    def test_nonfinite_oracle_records_are_not_accepted_as_json(self):
        for malformed in (b'{"elapsed_seconds":NaN}', b'{"elapsed_seconds":1e999}'):
            with self.subTest(malformed=malformed):
                read_fd, write_fd = os.pipe()
                try:
                    with os.fdopen(read_fd, "rb", buffering=0) as output:
                        process = mock.Mock(stdout=output)
                        process.poll.return_value = None
                        os.write(write_fd, b"ORACLE_FILLED=" + malformed + b"\n")
                        with self.assertRaisesRegex(
                                qualify.QualificationFailure, "malformed JSON"):
                            qualify._oracle_event(
                                process, "ORACLE_FILLED=",
                                time.monotonic() + 1, lambda: None, bytearray())
                finally:
                    os.close(write_fd)

    def test_verified_digest_must_be_canonical_and_complete(self):
        valid_record = {
            "verified_pages": 16,
            "verified_bytes": 16 * qualify.PAGE_BYTES,
            "mismatches": 0,
            "digest": "ab" * 32,
            "expected_digest": "ab" * 32,
        }
        self.assertEqual(
            qualify.aggregate_oracle_verification([valid_record, valid_record])["mismatches"],
            0)
        for invalid in (
                {"verified_pages": 16.0},
                {"verified_bytes": str(16 * qualify.PAGE_BYTES)},
                {"mismatches": False},
                {"digest": ("AB" * 32)},
                {"expected_digest": "ab " * 32},
                {"digest": None},
                {"digest": "00" * 31}):
            with self.subTest(invalid=invalid), self.assertRaises(
                    qualify.QualificationFailure):
                qualify.aggregate_oracle_verification([
                    {**valid_record, **invalid}, valid_record])
        evidence = self.positive_evidence()
        evidence["oracle"] = {
            **evidence["oracle"], "digest": None, "expected_digest": None}
        with self.assertRaises(qualify.QualificationFailure):
            qualify.evaluate_workload_evidence(**evidence)

    def test_final_artifact_proof_rejects_stale_installed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            paths = {
                "formatter_sha256": prefix / "sbin/swapzctl",
                "module_sha256": prefix / "libexec/swapz/dm-swapz.ko",
                "oracle_sha256": prefix / "libexec/swapz/device-roundtrip",
            }
            for key, path in paths.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(key.encode("ascii"))
            hashes = {
                key: hashlib.sha256(path.read_bytes()).hexdigest()
                for key, path in paths.items()
            }
            qualify.require_final_installed_artifact_identity(
                paths["formatter_sha256"], hashes)
            for key, path in paths.items():
                with self.subTest(artifact=key):
                    original = path.read_bytes()
                    path.write_bytes(b"replaced artifact")
                    with self.assertRaisesRegex(
                            qualify.QualificationFailure, f"installed {key} bytes changed"):
                        qualify.require_final_installed_artifact_identity(
                            paths["formatter_sha256"], hashes)
                    path.write_bytes(original)
            with self.assertRaisesRegex(
                    qualify.QualificationFailure, "inventory is incomplete"):
                qualify.require_final_installed_artifact_identity(
                    paths["formatter_sha256"], {"formatter_sha256": hashes["formatter_sha256"]})

    def test_linux_swap_uuid_uses_wire_order_not_host_endianness(self):
        header = bytearray(self.make_swap_header())
        header[
            qualify.SWAP_UUID_OFFSET:qualify.SWAP_UUID_OFFSET + qualify.SWAP_UUID_BYTES
        ] = bytes(range(16))
        self.assertEqual(
            qualify.linux_swap_header(bytes(header), 1024)["uuid"],
            "00010203-0405-0607-0809-0a0b0c0d0e0f")

    def test_changed_qualification_report_cannot_pass_initial_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "qualified.json"
            source_sha = "a" * 40
            original = {
                "schema": "swapz-test-results-v1",
                "source_sha": source_sha,
                "tested_commit_sha": source_sha,
                "overall": "PASS",
                "qualification": "RAM_BACKED_NULL_BLK_ONLY",
                "qualified_artifacts": {
                    "status": "AVAILABLE",
                    "formatter_sha256": "1" * 64,
                    "module_sha256": "2" * 64,
                    "oracle_sha256": "3" * 64,
                },
            }
            report_path.write_text(json.dumps(original), encoding="utf-8")
            initial_digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
            modified = {**original, "overall": "FAIL"}
            report_path.write_text(json.dumps(modified), encoding="utf-8")
            with mock.patch.object(
                    qualify, "installed_artifact_paths",
                    side_effect=AssertionError("must reject report before installed reads")):
                with self.assertRaisesRegex(
                        qualify.Blocked, "imported qualification report digest"):
                    qualify.verify_provenance(
                        {
                            "control_build_source_clean": True,
                            "qualification_report_valid": True,
                            "qualification_source_matches_build": True,
                            "live_artifact_hashes_read": True,
                            "live_artifacts_match_qualification": True,
                            "module_mapper_inventory_read": True,
                            "swapz_mapper_absent": True,
                            "dm_swapz_module_loaded": False,
                            "control_build_source_sha": source_sha,
                            "qualification_report_sha256": initial_digest,
                        },
                        source_sha, report_path, Path(directory) / "sbin/swapzctl")


    def test_fresh_cgroup_must_not_hide_oom_in_initial_baseline(self):
        cgroup = Path("/synthetic/dedicated-real-swap-cgroup")
        for counter in ("oom", "oom_kill"):
            with self.subTest(counter=counter):
                events = {"oom": 0, "oom_kill": 0}
                events[counter] = 1
                with mock.patch.object(
                        qualify, "_cgroup_create", return_value=cgroup), \
                        mock.patch.object(
                            qualify, "_memory_events", return_value=events), \
                        mock.patch.object(qualify, "_remove_cgroup") as remove:
                    with self.assertRaisesRegex(
                            qualify.QualificationFailure,
                            "fresh dedicated oracle cgroup already recorded OOM events"):
                        qualify._run_workload(
                            {}, {}, ORACLE, 384, 128, 384, 60)
                    remove.assert_called_once_with(cgroup)

                with mock.patch.object(
                        qualify, "_mem_available_mib", return_value=4096), \
                        mock.patch.object(
                            qualify, "_cgroup_create", return_value=cgroup), \
                        mock.patch.object(qualify, "_read_uint", return_value=0), \
                        mock.patch.object(
                            qualify, "_memory_events", return_value=events), \
                        mock.patch.object(qualify, "_remove_cgroup") as remove:
                    with self.assertRaisesRegex(
                            qualify.Blocked, "fresh preflight cgroup has preexisting OOM events"):
                        qualify.preflight_workload_environment(384, 128, 384)
                    remove.assert_called_once_with(cgroup)



    def test_cgroup_exit_snapshot_race_rechecks_before_rejecting_valid_exit(self):
        workers = [mock.Mock(pid=501), mock.Mock(pid=502)]
        workers[0].poll.return_value = None
        workers[1].poll.return_value = 0
        with mock.patch.object(
                qualify, "_read_oracle_cgroup_members",
                side_effect=[{501, 502}, {501}]) as membership:
            qualify.require_oracle_worker_cgroup_ownership(
                Path("/synthetic/cgroup"), workers, allow_worker_exit=True)
        self.assertEqual(membership.call_count, 2)


        sequential = [mock.Mock(pid=601), mock.Mock(pid=602)]
        sequential[0].poll.side_effect = [None, 0, 0]
        sequential[1].poll.return_value = 0
        with mock.patch.object(
                qualify, "_read_oracle_cgroup_members",
                side_effect=[{601, 602}, {601}, set()]) as membership:
            qualify.require_oracle_worker_cgroup_ownership(
                Path("/synthetic/cgroup"), sequential,
                allow_worker_exit=True)
        self.assertEqual(membership.call_count, 3)

        with mock.patch.object(
                qualify, "_read_oracle_cgroup_members",
                side_effect=[{501, 502}, {501, 502}, {501, 502}]), \
                self.assertRaisesRegex(
                    qualify.QualificationFailure, "exited oracle PID"):
            qualify.require_oracle_worker_cgroup_ownership(
                Path("/synthetic/cgroup"), workers, allow_worker_exit=True)

    def test_private_control_inputs_are_root_private_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            private_parent = Path(directory)
            pinned_root, hashes = qualify.pin_physical_control_inputs(
                private_parent)
            self.assertEqual(
                set(hashes), set(qualify.PHYSICAL_CONTROL_INPUT_PATHS))
            for relative, digest in hashes.items():
                pinned = pinned_root / relative
                self.assertEqual(
                    hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
                self.assertEqual(stat.S_IMODE(pinned.stat().st_mode), 0o400)
                self.assertNotEqual(pinned.resolve(), (ROOT / relative).resolve())

    def test_private_control_build_uses_pinned_source_root(self):
        source_sha = "a" * 40
        completed = __import__("subprocess").CompletedProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            qualified = root / "prefix/sbin/swapzctl"
            qualified.parent.mkdir(parents=True)
            qualified.write_bytes(b"qualified")
            source_root, source_hashes = qualify.pin_physical_control_inputs(root)

            def fake_compile(argv, **_kwargs):
                if "-MM" in argv:
                    return completed(
                        args=argv, returncode=0,
                        stdout=self.physical_dependency_output(source_root),
                        stderr="")
                output = Path(argv[argv.index("-o") + 1])
                output.write_bytes(b"private")
                return completed(args=argv, returncode=0, stdout="", stderr="")

            with mock.patch.object(
                    qualify, "_run", side_effect=fake_compile) as run:
                qualify.build_physical_execution_control(
                    source_sha, qualified, root / "control",
                    source_root=source_root,
                    expected_input_hashes=source_hashes)
            argv = run.call_args.args[0]
            self.assertIn(
                str(source_root / "src/userspace/swapzctl.c"), argv)
            self.assertIn(
                str(source_root / "src/userspace/swapz-primary.c"), argv)
            self.assertNotIn(str(ROOT / "src/userspace/swapzctl.c"), argv)

    def test_parent_admission_requires_commit_bound_private_control_hashes(self):
        source_sha = "a" * 40
        expected = {
            item: hashlib.sha256(item.encode("ascii")).hexdigest()
            for item in parent.PHYSICAL_CONTROL_INPUT_PATHS
        }
        request = {
            "schema": parent.SOURCE_ADMISSION_SCHEMA,
            "phase": "initial",
            "source_sha": source_sha,
            "nonce": "1" * 32,
            "physical_control_inputs_sha256": dict(expected),
            "executed_helper_sha256": "8" * 64,
        }

        def read_request(value):
            return parent._read_request(
                io.BytesIO(
                    (json.dumps(
                        value, sort_keys=True, separators=(",", ":")) +
                     "\n").encode("ascii")),
                source_sha, expected, "8" * 64)

        self.assertEqual(read_request(request), request)
        changed = json.loads(json.dumps(request))
        changed["physical_control_inputs_sha256"][
            parent.PHYSICAL_CONTROL_INPUT_PATHS[0]] = "0" * 64
        with self.assertRaisesRegex(
                parent.Blocked, "request identity is invalid"):
            read_request(changed)

    def test_qualification_report_digest_and_artifacts_share_one_snapshot(self):
        source_sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "qualification.json"
            report = {
                "schema": "swapz-test-results-v1",
                "source_sha": source_sha,
                "tested_commit_sha": source_sha,
                "overall": "PASS",
                "qualification": "RAM_BACKED_NULL_BLK_ONLY",
                "qualified_artifacts": {
                    "status": "AVAILABLE",
                    "formatter_sha256": "1" * 64,
                    "module_sha256": "2" * 64,
                    "oracle_sha256": "3" * 64,
                },
            }
            report_path.write_text(json.dumps(report), encoding="utf-8")
            digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
            self.assertEqual(
                qualify.qualification_artifact_hashes(
                    report_path, source_sha, digest),
                {
                    "formatter_sha256": "1" * 64,
                    "module_sha256": "2" * 64,
                    "oracle_sha256": "3" * 64,
                })
            report["qualified_artifacts"]["module_sha256"] = "4" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(
                    qualify.Blocked, "imported qualification report digest"):
                qualify.qualification_artifact_hashes(
                    report_path, source_sha, digest)

    def test_stable_artifact_hash_rejects_symlink_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_bytes(b"qualified")
            alias = root / "alias"
            alias.symlink_to(target)
            with self.assertRaisesRegex(
                    qualify.Blocked, "not a regular file"):
                qualify._sha256_file(alias)

    def test_acceptance_digest_is_of_exact_validated_snapshot(self):
        manifest = json.loads(
            (ROOT / "docs/production-acceptance.json").read_text())
        payload = (
            json.dumps(manifest, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with mock.patch.object(
                qualify, "_read_stable_file_bytes", return_value=payload):
            accepted, digest = qualify._verify_acceptance_manifest_snapshot(
                cycles=qualify.DEFAULT_CYCLES,
                workload_mib=qualify.DEFAULT_WORKLOAD_MIB,
                resident_mib=qualify.DEFAULT_RESIDENT_MIB,
                swap_limit_mib=qualify.DEFAULT_SWAP_LIMIT_MIB,
                timeout_seconds=qualify.DEFAULT_TIMEOUT_SECONDS)
        self.assertEqual(accepted["status"], "FROZEN")
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())


    def test_privileged_external_commands_require_root_owned_nonwritable_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "dmsetup"
            fake.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            fake.chmod(0o777)
            with mock.patch.object(
                    qualify.shutil, "which", return_value=str(fake)) as which, \
                    self.assertRaisesRegex(
                        qualify.Blocked, "unsafe required command dmsetup"):
                qualify._trusted_executable("dmsetup")
            which.assert_called_once_with(
                "dmsetup", path=qualify.SAFE_CHILD_PATH)

    def test_required_command_execution_uses_trusted_resolved_path(self):
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout="", stderr="")
        with mock.patch.object(
                qualify, "_trusted_executable",
                return_value="/trusted/dmsetup") as trusted, \
                mock.patch.object(
                    qualify.subprocess, "run",
                    return_value=completed) as run:
            qualify._run(["dmsetup", "status", "swapz-primary"], check=False)
        trusted.assert_called_once_with("dmsetup")
        self.assertEqual(
            run.call_args.args[0],
            ["/trusted/dmsetup", "status", "swapz-primary"])

    def test_lsblk_topology_uses_strict_json_and_exact_container_types(self):
        valid = (
            '{"blockdevices":[{"maj:min":"8:0","children":'
            '[{"maj:min":"8:1"}]}]}')
        rows = qualify.parse_lsblk_topology(valid)
        self.assertEqual(
            [row["maj:min"] for row in rows], ["8:0", "8:1"])
        for malformed in (
                '{"blockdevices":[],"blockdevices":[]}',
                '{"blockdevices":[NaN]}',
                '{"blockdevices":[null]}',
                '{"blockdevices":{}}',
                '{"blockdevices":[{"children":{}}]}'):
            with self.subTest(malformed=malformed), self.assertRaises(
                    qualify.Blocked):
                qualify.parse_lsblk_topology(malformed)

    def test_stable_artifact_hash_streams_without_whole_file_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "artifact"
            artifact.write_bytes(b"x" * (2 * 1024 * 1024 + 17))
            expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
            with mock.patch.object(
                    qualify, "_read_stable_file_bytes",
                    side_effect=AssertionError(
                        "streaming hash must not buffer whole artifact")):
                self.assertEqual(qualify._sha256_file(artifact), expected)

    def test_physical_control_input_inventory_matches_admission_parent(self):
        self.assertEqual(
            qualify.PHYSICAL_CONTROL_INPUT_PATHS,
            parent.PHYSICAL_CONTROL_INPUT_PATHS)


    def test_privileged_child_environment_drops_compiler_and_loader_influence(self):
        poison = {
            "PATH": "/attacker/bin",
            "CPATH": "/attacker/include",
            "COMPILER_PATH": "/attacker/compiler",
            "GCC_EXEC_PREFIX": "/attacker/gcc",
            "LIBRARY_PATH": "/attacker/lib",
            "LD_PRELOAD": "/attacker/libhook.so",
            "PYTHONPATH": "/attacker/python",
        }
        completed = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout="", stderr="")
        with mock.patch.dict(os.environ, poison, clear=True), \
                mock.patch.object(
                    qualify, "_trusted_executable",
                    return_value="/usr/bin/cc"), \
                mock.patch.object(
                    qualify.subprocess, "run",
                    return_value=completed) as run:
            qualify._run(["cc", "--version"], check=False)
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["PATH"], qualify.SAFE_CHILD_PATH)
        self.assertEqual(environment["LC_ALL"], "C")
        for variable in poison:
            if variable != "PATH":
                self.assertNotIn(variable, environment)

    def test_parent_streams_commit_bound_helper_into_isolated_root_python(self):
        arguments = parent._build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])

        read_descriptor, write_descriptor = os.pipe()
        source_pipe = os.fdopen(write_descriptor, "wb", buffering=0)
        child = mock.Mock(stdin=source_pipe)
        child.poll.return_value = None
        helper_payload = b"print('commit-bound helper')\n"
        helper_digest = hashlib.sha256(helper_payload).hexdigest()
        try:
            with mock.patch.object(
                    parent.subprocess, "Popen", return_value=child) as popen:
                observed = parent._start_privileged_child(
                    "/usr/bin/sudo", "/usr/bin/python3", arguments,
                    Path("/tmp/admission.sock"), 1000,
                    os.getpid(), 123456,
                    helper_payload, helper_digest)
            self.assertIs(observed, child)
            self.assertEqual(
                os.read(read_descriptor, len(helper_payload) + 1),
                helper_payload)
            self.assertTrue(source_pipe.closed)
        finally:
            os.close(read_descriptor)
        command = popen.call_args.args[0]
        self.assertEqual(
            command[:7],
            ["/usr/bin/sudo", "-n", "--", "/usr/bin/python3",
             "-I", "-B", "-c"])
        self.assertEqual(command[7], parent.PRIVILEGED_HELPER_BOOTSTRAP)
        self.assertIn(os.fspath(parent.PRIVILEGED_HELPER), command)
        self.assertIn(os.fspath(parent.ROOT), command)
        self.assertIn("--executed-helper-sha256", command)
        self.assertIn(helper_digest, command)
        parent_pid_index = command.index("--source-admission-parent-process-id")
        self.assertEqual(command[parent_pid_index + 1], str(os.getpid()))
        parent_start_index = command.index("--source-admission-parent-start-ticks")
        self.assertEqual(command[parent_start_index + 1], "123456")


    def test_parent_reads_privileged_helper_from_validated_commit_object(self):
        source_sha = "a" * 40
        payload = b"exact committed privileged helper bytes\n"
        completed = __import__("subprocess").CompletedProcess
        size = completed(
            args=[], returncode=0,
            stdout=f"{len(payload)}\n".encode("ascii"), stderr=b"")
        contents = completed(
            args=[], returncode=0, stdout=payload, stderr=b"")
        with mock.patch.object(
                parent.subprocess, "run",
                side_effect=[size, contents]) as run:
            observed = parent._git_file_bytes(
                source_sha, parent.PRIVILEGED_HELPER, "/usr/bin/git")
        self.assertEqual(observed, payload)
        object_spec = (
            f"{source_sha}:tests/tools/qualify-primary-real-swap.py")
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["/usr/bin/git", "cat-file", "-s", object_spec])
        self.assertEqual(
            run.call_args_list[1].args[0],
            ["/usr/bin/git", "show", object_spec])

    def test_terminal_helper_identity_is_commit_bound_not_mutable_path_hash(self):
        source = HELPER.read_text(encoding="utf-8")
        execute_start = source.index("def _execute_admitted(")
        execute_end = source.index("\ndef execute(", execute_start)
        execute_source = source[execute_start:execute_end]
        self.assertIn(
            'helper_sha256 = getattr(arguments, "executed_helper_sha256", None)',
            execute_source)
        self.assertIn(
            "admission.bind_executed_helper_sha256(helper_sha256)",
            execute_source)
        self.assertNotIn("_sha256_file(Path(__file__))", execute_source)


    def test_parent_commit_bound_helper_transfer_is_bounded(self):
        arguments = parent._build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])
        read_descriptor, write_descriptor = os.pipe()
        source_pipe = os.fdopen(write_descriptor, "wb", buffering=0)
        child = mock.Mock(stdin=source_pipe)
        child.poll.return_value = None
        with mock.patch.object(
                parent.subprocess, "Popen", return_value=child), \
                mock.patch.object(
                    parent.select, "select", return_value=([], [], [])), \
                mock.patch.object(
                    parent.time, "monotonic", side_effect=[0.0, 0.0, 11.0]), \
                mock.patch.object(
                    parent, "_stop_unadmitted_child_preserving") as stop:
            with self.assertRaisesRegex(
                    parent.Blocked, "cannot stream commit-bound"):
                parent._start_privileged_child(
                    "/usr/bin/sudo", "/usr/bin/python3", arguments,
                    Path("/tmp/admission.sock"), 1000,
                    os.getpid(), 123456,
                    b"x" * 32, "8" * 64)
        stop.assert_called_once()
        os.close(read_descriptor)


    def test_parent_source_transfer_epipe_reaps_child_and_redacts_output(self):
        arguments = parent._build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])
        read_descriptor, write_descriptor = os.pipe()
        os.close(read_descriptor)
        source_pipe = os.fdopen(write_descriptor, "wb", buffering=0)
        child = mock.Mock(stdin=source_pipe)
        child.poll.return_value = None
        child.wait.return_value = -15
        with mock.patch.object(parent.subprocess, "Popen", return_value=child), \
                self.assertRaisesRegex(
                    parent.Blocked,
                    "phase=helper_source_transfer:cause=BrokenPipeError:"
                    "errno=32:child_exit=running:owned_cleanup=complete") as failure:
            parent._start_privileged_child(
                "/usr/bin/sudo", "/usr/bin/python3", arguments,
                Path("/tmp/admission.sock"), 1000,
                os.getpid(), 123456, b"private helper bytes", "8" * 64)
        self.assertTrue(source_pipe.closed)
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=10)
        self.assertNotIn("report.json", str(failure.exception))
        self.assertNotIn("private helper bytes", str(failure.exception))

    def test_streamed_helper_uses_parent_bound_source_root_not_mutable_file_resolution(self):
        helper_source = HELPER.read_text(encoding="utf-8")
        self.assertIn(
            'globals().get("__swapz_source_root__")', helper_source)
        self.assertIn(
            "'__swapz_source_root__': source_root",
            parent.PRIVILEGED_HELPER_BOOTSTRAP)


    def test_precycle_state_returns_prior_complete_run_for_freshness_seed(self):
        prior = {
            "schema": "swapz-primary-state-v1",
            "run_id": "a" * 32,
            "stage": "COMPLETE",
            "recovery_previous_stage": "NONE",
        }
        with mock.patch.object(qualify, "read_state", return_value=prior), \
                mock.patch.object(
                    qualify, "_path_present", return_value=False), \
                mock.patch.object(qualify, "_dm_identity", return_value=None):
            observed = qualify._validate_precycle_state(
                "f13428f6-01", (8, 1), (8, 0), [])
        self.assertIs(observed, prior)


    def test_policy_and_target_authorization_are_commit_bound_inputs(self):
        self.assertIn(
            "docs/production-acceptance.json",
            qualify.PHYSICAL_CONTROL_INPUT_PATHS)
        self.assertIn(
            "docs/handoff/production-readiness.json",
            qualify.PHYSICAL_CONTROL_INPUT_PATHS)
        self.assertEqual(
            qualify.PHYSICAL_CONTROL_INPUT_PATHS,
            parent.PHYSICAL_CONTROL_INPUT_PATHS)
        source = HELPER.read_text(encoding="utf-8")
        execute_start = source.index("def _execute_admitted(")
        execute_end = source.index("\ndef execute(", execute_start)
        execute_source = source[execute_start:execute_end]
        self.assertIn(
            'pinned_source_root / "docs/production-acceptance.json"',
            execute_source)
        self.assertIn(
            'pinned_source_root / "docs/handoff/production-readiness.json"',
            execute_source)
        self.assertIn(
            "verify_authorized_target(\n"
            "            plan, selector_partuuid, authorization_snapshot)",
            execute_source)
        self.assertNotIn("acceptance_manifest_sha256()", execute_source)

    def test_authorization_snapshot_digest_is_of_exact_parsed_bytes(self):
        snapshot = {
            "authorized_target": {
                "partuuid": "f13428f6-01",
                "size_bytes": 124787884032,
            }
        }
        payload = (
            json.dumps(snapshot, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        with mock.patch.object(
                qualify, "_read_stable_file_bytes", return_value=payload):
            observed, digest = qualify._read_readiness_snapshot(
                Path("/synthetic/commit-bound-readiness.json"))
        self.assertEqual(observed, snapshot)
        self.assertEqual(digest, hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
