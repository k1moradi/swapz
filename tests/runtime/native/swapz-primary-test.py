#!/usr/bin/env python3
"""Rootless policy tests for the disabled primary-swap boot manager."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "src/userspace/swapz-primary.py"
SPEC = importlib.util.spec_from_file_location("swapz_primary", SCRIPT)
primary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(primary)


class PrimaryPolicy(unittest.TestCase):
    def test_maximum_geometry_obeys_reserve_and_segment_alignment(self):
        blocks = ((primary.DEVICE_BYTES // primary.BLOCK_BYTES - 1) //
                  primary.SEGMENT_BLOCKS) * primary.SEGMENT_BLOCKS
        pages = primary.maximum_logical_pages(blocks)
        reserve = (pages + 7) // 8
        admitted_blocks = ((blocks - reserve) // primary.SEGMENT_BLOCKS) * \
            primary.SEGMENT_BLOCKS
        next_reserve = (pages + 1 + 7) // 8
        next_admitted = ((blocks - next_reserve) //
                         primary.SEGMENT_BLOCKS) * primary.SEGMENT_BLOCKS
        self.assertEqual(pages, 3_727_872)
        self.assertLessEqual(pages, admitted_blocks)
        self.assertGreater(pages + 1, next_admitted)
        self.assertEqual(primary.LOGICAL_BYTES, 15_269_363_712)
        self.assertEqual(primary.LOGICAL_BYTES // 1024 - 4, 14_911_484)

    def test_dm_info_accepts_empty_and_both_host_record_delimiters(self):
        self.assertEqual(primary.parse_dm_info("No devices found\n"), [])
        self.assertEqual(primary.parse_dm_info("swapz-primary:SWAPZ-PRIMARY:252:0:0\n"),
                         [("swapz-primary", "SWAPZ-PRIMARY", 252, 0, 0)])
        self.assertEqual(primary.parse_dm_info("swapz-primary SWAPZ-PRIMARY 252 0 0\n"),
                         [("swapz-primary", "SWAPZ-PRIMARY", 252, 0, 0)])

    def test_dm_info_rejects_ambiguous_or_malformed_output(self):
        for value in (
                "", "diagnostic only", "No devices found\nswapz-primary:U:252:0:0",
                "swapz-primary:U:not-a-major:0:0", "swapz-primary:U:252:0",
                "swapz-primary:U:252:0:0\nmalformed"):
            with self.subTest(value=value), self.assertRaises(primary.ManagerError):
                primary.parse_dm_info(value)

    def test_table_is_bound_to_exact_maximum_and_lower_partition(self):
        good = " ".join(primary.expected_table())
        self.assertTrue(primary.validate_table(good))
        for bad in (
                good.replace(str(primary.LOGICAL_SECTORS),
                             str(primary.LOGICAL_SECTORS - 8), 1),
                good.replace("/dev/sda4", "/dev/sda3", 1),
                good.replace("0 64 0 2 0 1 0 0", "0 64 0 2 0 1 0 1", 1)):
            with self.subTest(table=bad), self.assertRaises(primary.ManagerError):
                primary.validate_table(bad)

    def test_swap_inventory_parser_preserves_identity_and_usage(self):
        rows = primary.parse_swaps(
            "Filename Type Size Used Priority\n"
            "/dev/sda4 partition 16777212 0 -1\n")
        self.assertEqual(rows, [{
            "path": "/dev/sda4", "type": "partition", "size_kib": 16777212,
            "used_kib": 0, "priority": -1,
        }])
        with self.assertRaises(primary.ManagerError):
            primary.parse_swaps("Filename Type Size Used Priority\n/dev/sda4 partition x 0 -1\n")

    def test_header_parser_requires_exact_swz_identity_shape(self):
        header = bytearray(primary.PAGE_BYTES)
        header[:8] = primary.SWAPZ_MAGIC
        header[8:12] = (1).to_bytes(4, "little")
        header[12:16] = primary.PAGE_BYTES.to_bytes(4, "little")
        header[16:24] = primary.DEVICE_BYTES.to_bytes(8, "little")
        header[24:40] = bytes.fromhex("00112233445566778899aabbccddeeff")
        self.assertTrue(primary.valid_swz_header(bytes(header)))
        header[40] = 1
        self.assertFalse(primary.valid_swz_header(bytes(header)))

    def test_stop_requires_same_boot_service_ownership_and_exact_mapper_dev(self):
        state = {"stage": "MAPPER_READY", "module_loaded_by_service": True,
                 "dm_major": 252, "dm_minor": 0}
        row = ("swapz-primary", "SWAPZ-PRIMARY", 252, 0, 0)
        primary.require_owned_mapper_for_stop(state, row)
        for bad_state, bad_row in (
                ({**state, "module_loaded_by_service": False}, row),
                ({**state, "stage": "REQUIRES_REVIEW"}, row),
                (state, (row[0], row[1], 252, 1, 0)),
                (state, (row[0], row[1], 252, 0)),
        ):
            with self.subTest(state=bad_state, row=bad_row), \
                    self.assertRaises(primary.ManagerError):
                primary.require_owned_mapper_for_stop(bad_state, bad_row)

    def test_privileged_lifecycle_remains_disabled_until_full_qualification(self):
        self.assertFalse(primary.PRIMARY_EXECUTION_ENABLED)
        self.assertEqual(primary.LOCK_PATH,
                         Path("/var/lib/swapz/physical-recovery/"
                              "partition-7fb9401d-04.lock"))
        manager = primary.PrimaryManager(ops=object())
        with self.assertRaisesRegex(primary.ManagerError, "remains disabled"):
            manager.start()
        with self.assertRaisesRegex(primary.ManagerError, "remains disabled"):
            manager.stop()

    def test_absent_mapper_cannot_erase_review_state_or_live_module(self):
        primary.require_stopped_state_is_unambiguous(
            {"stage": "MAPPER_REMOVED"}, False, [])
        for state, loaded, rows in (
                ({"stage": "REQUIRES_REVIEW"}, False, []),
                ({"stage": "MAPPER_REMOVED"}, True, []),
                ({"stage": "MAPPER_REMOVED"}, False, [{"used_kib": 1}])):
            with self.subTest(state=state, loaded=loaded, rows=rows), \
                    self.assertRaises(primary.ManagerError):
                primary.require_stopped_state_is_unambiguous(state, loaded, rows)

    def test_active_partition_marker_is_bound_to_unique_run_and_device(self):
        state = {"run_id": "d" * 32}
        good = {"run_id": "d" * 32, "partuuid": "7fb9401d-04",
                "major": 8, "minor": 4}
        primary.validate_active_marker(good, state)
        for bad in (
                {**good, "run_id": "e" * 32},
                {**good, "major": 8, "minor": 3},
                {**good, "partuuid": "7fb9401d-05"},
                {**good, "extra": True},
        ):
            with self.subTest(marker=bad), self.assertRaises(primary.ManagerError):
                primary.validate_active_marker(bad, state)

    def test_privileged_directory_validation_rejects_symlink(self):
        with tempfile.TemporaryDirectory(prefix="swapz-primary-path-") as temp:
            target = Path(temp) / "target"
            target.mkdir(mode=0o700)
            link = Path(temp) / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(primary.ManagerError):
                primary.validate_root_directory(link, 0o700)


if __name__ == "__main__":
    unittest.main()
