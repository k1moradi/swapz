#!/usr/bin/env python3
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/physical-swap-probe.py"
SPEC = importlib.util.spec_from_file_location("physical_swap_probe", SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PhysicalSwapProbeTests(unittest.TestCase):
    def test_only_supported_4k_linux_swap_header_is_accepted(self):
        header = bytearray(probe.PAGE_BYTES)
        header[-len(probe.SWAP_SIGNATURE):] = probe.SWAP_SIGNATURE
        self.assertTrue(probe.swap_signature_valid(bytes(header)))
        self.assertFalse(probe.swap_signature_valid(bytes(header), 65536))
        self.assertFalse(probe.swap_signature_valid(bytes(header[:-1])))
        header[-1] ^= 1
        self.assertFalse(probe.swap_signature_valid(bytes(header)))

    def test_swap_inventory_requires_exact_header_and_numeric_fields(self):
        valid = (
            "Filename Type Size Used Priority\n"
            "/dev/test partition 16777212 0 -1\n"
        )
        self.assertEqual(probe.parse_swap_rows(valid)[0]["used_kib"], 0)
        self.assertEqual(probe.parse_swap_rows(valid)[0]["priority"], -1)
        with self.assertRaisesRegex(probe.ProbeError, "header"):
            probe.parse_swap_rows("Name Type Size Used Priority\n")
        with self.assertRaisesRegex(probe.ProbeError, "numeric"):
            probe.parse_swap_rows(
                "Filename Type Size Used Priority\n/dev/test partition x 0 -1\n")
        with self.assertRaisesRegex(probe.ProbeError, "capacity"):
            probe.parse_swap_rows(
                "Filename Type Size Used Priority\n/dev/test partition 10 -1 -1\n")

    def test_regular_files_are_never_block_devices(self):
        with tempfile.NamedTemporaryFile() as regular:
            with self.assertRaisesRegex(probe.ProbeError, "not a block device"):
                probe.block_identity(regular.name)

    def test_physical_target_requires_repeated_stable_uuid_path(self):
        with self.assertRaisesRegex(probe.ProbeError, "match exactly"):
            probe.inspect_target("/dev/disk/by-uuid/a", "/dev/disk/by-uuid/b")
        with self.assertRaisesRegex(probe.ProbeError, "by-uuid"):
            probe.inspect_target("/dev/sda4", "/dev/sda4")

    def test_review_record_is_bound_to_helper_source_and_device(self):
        evidence = {"source_sha": "a" * 40}
        target = {"major": 8, "minor": 4}
        review = {
            "approved": True,
            "reviewer": "independent-reviewer",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review))
            with mock.patch.dict(os.environ, {"SUDO_USER": "keivan", "USER": "root"}):
                self.assertEqual(
                    probe.validate_review(path, evidence, target),
                    "independent-reviewer")
                review["device_major_minor"] = "8:3"
                path.write_text(json.dumps(review))
                with self.assertRaisesRegex(probe.ProbeError, "does not match"):
                    probe.validate_review(path, evidence, target)

    def test_review_rejects_the_operator_as_reviewer(self):
        evidence = {"source_sha": "b" * 40}
        target = {"major": 8, "minor": 4}
        review = {
            "approved": True,
            "reviewer": "keivan",
            "scope": probe.EXPECTED_SCOPE,
            "source_sha": evidence["source_sha"],
            "device_major_minor": "8:4",
            "helper_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "review.json"
            path.write_text(json.dumps(review))
            with mock.patch.dict(os.environ, {"SUDO_USER": "keivan", "USER": "root"}):
                with self.assertRaisesRegex(probe.ProbeError, "separate"):
                    probe.validate_review(path, evidence, target)

    def test_recovery_refuses_a_different_confirmed_partition(self):
        state = {"device_arg": "/dev/disk/by-uuid/original"}
        with self.assertRaisesRegex(probe.ProbeError, "exact originally confirmed"):
            probe.inspect_target_identity_for_recovery(
                state, "/dev/disk/by-uuid/other", "/dev/disk/by-uuid/other")

    def test_recovery_only_accepts_its_generated_mapper_identity(self):
        token = "1234567890abcdef"
        probe._validate_owned_mapper_identity({
            "dm_name": f"swapz-demo-physical-{token}",
            "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
        })
        with self.assertRaisesRegex(probe.ProbeError, "owned mapper"):
            probe._validate_owned_mapper_identity({
                "dm_name": "unrelated-mapper",
                "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{token}",
            })
        with self.assertRaisesRegex(probe.ProbeError, "tokens"):
            probe._validate_owned_mapper_identity({
                "dm_name": f"swapz-demo-physical-{token}",
                "dm_uuid": f"SWAPZ-TEST-PHYSICAL-{'0' * 16}",
            })

    def test_probe_is_not_wired_into_make_test_and_never_swapons_mapper(self):
        runner = (ROOT / "tools/run-tests.py").read_text()
        makefile = (ROOT.parent / "Makefile").read_text()
        script = SCRIPT.read_text()
        self.assertNotIn("physical-swap-probe.py", runner)
        self.assertNotIn("physical-swap-probe.py", makefile)
        self.assertIn('["swapon", state["device"]]', script)
        self.assertNotIn('["swapon", mapper]', script)
        self.assertNotIn('"--force"', script)


if __name__ == "__main__":
    unittest.main()
