#!/usr/bin/env python3
"""Rootless contracts for the private primary real-swap qualification helper."""

from dataclasses import replace
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import struct
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "tests/tools/qualify-primary-real-swap.py"
ORACLE = ROOT / "tests/tools/primary-real-swap-oracle.py"

SPEC = importlib.util.spec_from_file_location("qualify_primary_real_swap", HELPER)
qualify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = qualify
SPEC.loader.exec_module(qualify)
ORACLE_SPEC = importlib.util.spec_from_file_location("primary_real_swap_oracle", ORACLE)
oracle = importlib.util.module_from_spec(ORACLE_SPEC)
sys.modules[ORACLE_SPEC.name] = oracle
ORACLE_SPEC.loader.exec_module(oracle)


class FakeStat:
    def __init__(self, major=252, minor=1, block=True):
        self.st_mode = stat.S_IFBLK | 0o600 if block else stat.S_IFREG | 0o600
        self.st_rdev = os.makedev(major, minor) if block else 0


class PrimaryRealSwapContracts(unittest.TestCase):
    def test_oracle_page_pattern_is_full_page_deterministic_and_page_specific(self):
        first = oracle.page_pattern("01" * 16, 7)
        again = oracle.page_pattern("01" * 16, 7)
        other = oracle.page_pattern("01" * 16, 8)
        self.assertEqual(len(first), qualify.PAGE_BYTES)
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_oracle_rejects_malformed_seed_and_negative_page(self):
        for seed in ("", "a" * 31, "A" * 32, "g" * 32):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                oracle.page_pattern(seed, 0)
        with self.assertRaises(ValueError):
            oracle.page_pattern("a" * 32, -1)

    def test_selector_is_exact_single_partuuid_line(self):
        self.assertEqual(qualify.parse_selector("PARTUUID=f13428f6-01\n"), "f13428f6-01")
        for text in ("", "PARTUUID=x\n", "PARTUUID=deadbeef-01\nextra\n", "UUID=deadbeef-01\n"):
            with self.subTest(text=text), self.assertRaises(qualify.Blocked):
                qualify.parse_selector(text)

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

    def test_default_control_path_uses_installed_package_layout(self):
        args = qualify.build_parser().parse_args([
            "--validated-source", "a" * 40,
            "--qualification-report", "/tmp/report.json",
        ])
        self.assertEqual(args.swapzctl, "/usr/local/sbin/swapzctl")

    def test_physical_source_requires_main_equal_origin_main(self):
        source_sha = "a" * 40
        completed = __import__("subprocess").CompletedProcess
        good = [
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
            completed(args=[], returncode=0, stdout="main\n", stderr=""),
            completed(args=[], returncode=0, stdout=source_sha + "\n", stderr=""),
            completed(args=[], returncode=0,
                      stdout=source_sha + "\trefs/heads/main\n", stderr=""),
            completed(args=[], returncode=0, stdout="", stderr=""),
        ]
        with mock.patch.object(qualify, "_run", side_effect=good):
            qualify._check_git_source(source_sha)

        wrong_origin = list(good)
        wrong_origin[2] = completed(
            args=[], returncode=0, stdout="b" * 40 + "\n", stderr="")
        with mock.patch.object(qualify, "_run", side_effect=wrong_origin), \
                self.assertRaisesRegex(qualify.Blocked, "main == origin/main"):
            qualify._check_git_source(source_sha)

        detached = list(good)
        detached[1] = completed(
            args=[], returncode=0, stdout="HEAD\n", stderr="")
        with mock.patch.object(qualify, "_run", side_effect=detached), \
                self.assertRaisesRegex(qualify.Blocked, "main == origin/main"):
            qualify._check_git_source(source_sha)

        stale_remote = list(good)
        stale_remote[3] = completed(
            args=[], returncode=0, stdout="b" * 40 + "\trefs/heads/main\n", stderr="")
        with mock.patch.object(qualify, "_run", side_effect=stale_remote), \
                self.assertRaisesRegex(qualify.Blocked, "current remote main differs"):
            qualify._check_git_source(source_sha)

        unreachable_remote = list(good)
        unreachable_remote[3] = completed(
            args=[], returncode=128, stdout="", stderr="remote unavailable")
        with mock.patch.object(qualify, "_run", side_effect=unreachable_remote), \
                self.assertRaisesRegex(qualify.Blocked, "cannot verify the current remote"):
            qualify._check_git_source(source_sha)

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
        self.assertEqual(parsed["uuid"], "01" * 16)
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
                    "mismatches": 0, "digest": "aa", "expected_digest": "aa"},
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
                self.assertRaisesRegex(qualify.QualificationFailure, "stop/swapoff failed"):
            qualify._normal_stop(
                Path("/synthetic/swapzctl"), manifest, active, set(),
                "f13428f6-01", 60)

    def test_independent_active_verification_failure_still_requests_normal_stop(self):
        run_id = "1" * 32
        manifest = {"run_id": run_id}
        prepare = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout=f"PRIMARY_PREPARE=READY run_id={run_id} source={'2' * 40} logical_pages=1 logical_bytes=4096 swap_kib=0\n", stderr="")
        start = __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout=f"PRIMARY_START=ACTIVE run_id={run_id} mapper=/dev/mapper/swapz-primary swapon=true\n", stderr="")
        normal_stop = mock.Mock(return_value=None)
        with mock.patch.object(qualify, "read_swap_rows", return_value=[]), \
                mock.patch.object(qualify, "_validate_precycle_state", return_value=None), \
                mock.patch.object(qualify, "_kernel_log_snapshot", return_value=[]), \
                mock.patch.object(qualify, "_reject_relevant_kernel_errors", return_value=None), \
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
                plan={}, selector_partuuid="f13428f6-01", target_device=(8, 1),
                target_parent_device=(8, 0),
                workload_mib=384, resident_mib=128, swap_limit_mib=384,
                timeout_seconds=60, prior_run_ids=set(), prior_swap_uuids=set())
        normal_stop.assert_called_once()
        self.assertIsNone(normal_stop.call_args.args[2])

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


if __name__ == "__main__":
    unittest.main()
