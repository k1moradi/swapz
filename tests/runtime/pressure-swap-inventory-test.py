#!/usr/bin/env python3
"""Offline negative/positive tests for the production /proc/swaps parser."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "pressure_swap_inventory", ROOT / "pressure-swap-inventory.py")
assert spec is not None and spec.loader is not None
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

DEVICE = "/dev/swapz-mocked-dm-93"
HEADER = "Filename Type Size Used Priority\n"
TARGET = f"{DEVICE} partition 65536 512 100\n"
OTHER = "/swapfile file 32768 0 -1\n"


class SwapInventoryTests(unittest.TestCase):
    def assert_rejected(self, text: str, reason: str) -> None:
        with self.assertRaisesRegex(ValueError, reason):
            inventory.read_test_swap_used(text, DEVICE)

    def test_valid_target_and_unrelated_swap(self) -> None:
        self.assertEqual(inventory.read_test_swap_used(
            HEADER + OTHER + TARGET, DEVICE), 512)

    def test_target_present_before_unrelated_row(self) -> None:
        self.assertEqual(inventory.read_test_swap_used(
            HEADER + TARGET + OTHER, DEVICE), 512)

    def test_valid_zero_used_for_filled_only(self) -> None:
        self.assertEqual(inventory.read_test_swap_used(
            HEADER + f"{DEVICE} partition 65536 0 100\n", DEVICE), 0)

    def test_negative_priority_and_spaces(self) -> None:
        text = ("Filename\tType\tSize\tUsed\tPriority\n"
                f"{DEVICE}\tpartition\t65536\t99\t-100\n")
        self.assertEqual(inventory.read_test_swap_used(text, DEVICE), 99)

    def test_missing_target_fails(self) -> None:
        self.assert_rejected(HEADER + OTHER, "missing or duplicated")

    def test_duplicated_target_fails(self) -> None:
        self.assert_rejected(HEADER + TARGET + TARGET, "missing or duplicated")

    def test_unrelated_malformed_row_fails(self) -> None:
        self.assert_rejected(
            HEADER + TARGET + "/swapfile file 32768 junk -1\n", "numeric")

    def test_malformed_header_fails(self) -> None:
        self.assert_rejected("Filename Wrong Size Used Priority\n" + TARGET,
                             "header")

    def test_short_row_fails(self) -> None:
        self.assert_rejected(HEADER + TARGET + "/swapfile file 8\n", "row")

    def test_blank_row_fails(self) -> None:
        self.assert_rejected(HEADER + TARGET + "\n", "row")

    def test_no_final_newline_fails(self) -> None:
        self.assert_rejected((HEADER + TARGET).rstrip("\n"), "truncated")

    def test_used_nonnumeric_suffix_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 65536 512oops 100\n", "numeric")

    def test_negative_used_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 65536 -1 100\n", "numeric")

    def test_unicode_digits_fail(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 65536 ５ 100\n", "numeric")

    def test_used_larger_than_size_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 1024 2048 100\n", "impossible")

    def test_zero_size_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 0 0 100\n", "impossible")

    def test_negative_size_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition -512 1 100\n", "numeric")

    def test_oversized_numeric_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition {'9' * 200} 512 100\n", "numeric")

    def test_nonabsolute_path_fails(self) -> None:
        self.assert_rejected(
            HEADER + TARGET + "swapfile file 512 0 -1\n", "path or type")

    def test_invalid_type_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} bogus 65536 512 100\n", "path or type")

    def test_bad_priority_fails(self) -> None:
        self.assert_rejected(
            HEADER + f"{DEVICE} partition 65536 512 -1garbage\n", "numeric")

    def test_valid_symlink_alias_identifies_same_target(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            base = Path(work)
            target = base / "swapz-dm"
            target.write_bytes(b"")
            alias = base / "swapz-alias"
            alias.symlink_to(target)
            text = HEADER + f"{alias} partition 65536 400 100\n"
            self.assertEqual(
                inventory.read_test_swap_used(text, str(target)), 400)
            self.assert_rejected(HEADER + TARGET + TARGET, "missing or duplicated")

    def test_cli_success_and_rejects_corrupt_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            fixture = Path(work) / "swaps"
            args = [sys.executable, str(ROOT / "pressure-swap-inventory.py"),
                    DEVICE, "--fixture", str(fixture)]
            fixture.write_text(HEADER + TARGET, encoding="utf-8")
            run = subprocess.run(args, capture_output=True, text=True,
                                 timeout=3, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(run.stdout.strip(), "512")
            fixture.write_text(HEADER + OTHER, encoding="utf-8")
            run = subprocess.run(args, capture_output=True, text=True,
                                 timeout=3, check=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("missing or duplicated", run.stderr)


if __name__ == "__main__":
    unittest.main()
