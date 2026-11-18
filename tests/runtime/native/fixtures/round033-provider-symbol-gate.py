#!/usr/bin/env python3
"""Round033 original vmlinux GPL export byte-exact verifier.

Read the REAL original pinned Linux generated Module.symvers, not nm/grep,
a synthetic temporary .symvers, or the original C source. Explicit trailing
empty namespace and exactly one GPL-only vmlinux owner are mandatory.
The independent ORIGINAL Kbuild modpost probe is a SECOND required gate.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

SYMBOL = b"swapz_ci_bio_snapshot_lz4_v1"
EXPECTED_EXPORT_TYPE = b"EXPORT_SYMBOL_GPL"
EXPECTED_MODULE = b"vmlinux"
ORIGINAL_LINUX_ROW_FIELDS = 5
MAX_ROW_BYTES = 16384


class OriginalGPLSymbolError(ValueError):
    """First genuine original source Module.symvers format/owner mismatch."""


def verify_original_gpl_export(path: Path) -> tuple[bytes, str]:
    """Fail closed on any row referring to this symbol except one exact row.

    Return the original REAL raw row and SHA256 of the complete original file.
    Never create, rewrite, deduplicate or forge the kernel's symbol table.
    """
    file_sha256 = hashlib.sha256()
    actual_export_row: bytes | None = None
    matches = 0
    with path.open("rb") as symvers:
        for line_number, raw_line in enumerate(symvers, 1):
            file_sha256.update(raw_line)
            if len(raw_line) > MAX_ROW_BYTES:
                raise OriginalGPLSymbolError(
                    f"line={line_number} overlong-source-row bytes={len(raw_line)}")
            # Ignore other genuine exports, but the exported target symbol
            # MUST NOT be accidentally hidden by separators or column shifts.
            if SYMBOL not in raw_line:
                continue
            record = raw_line.removesuffix(b"\n")
            fields = record.split(b"\t")
            if len(fields) != ORIGINAL_LINUX_ROW_FIELDS:
                raise OriginalGPLSymbolError(
                    f"line={line_number} exact-field-count-required=5 "
                    f"actual={len(fields)} raw_hex={record[:160].hex()}")
            crc, exported_symbol, module, export_type, namespace = fields
            if exported_symbol != SYMBOL:
                raise OriginalGPLSymbolError(
                    f"line={line_number} symbol-column-mismatch "
                    f"raw_hex={record[:160].hex()}")
            if re.fullmatch(rb"0x[0-9a-fA-F]{8}", crc) is None:
                raise OriginalGPLSymbolError(
                    f"line={line_number} invalid-CRC-token "
                    f"raw_hex={record[:160].hex()}")
            if module != EXPECTED_MODULE or export_type != EXPECTED_EXPORT_TYPE:
                raise OriginalGPLSymbolError(
                    f"line={line_number} invalid-owner-or-GPL-type "
                    f"module_hex={module.hex()} type_hex={export_type.hex()} "
                    f"raw_hex={record[:160].hex()}")
            if namespace != b"":
                raise OriginalGPLSymbolError(
                    f"line={line_number} nonempty-export-namespace "
                    f"namespace_hex={namespace.hex()} "
                    f"raw_hex={record[:160].hex()}")
            matches += 1
            if matches != 1:
                raise OriginalGPLSymbolError(
                    f"line={line_number} duplicate-valid-GPL-export "
                    f"count={matches} raw_hex={record[:160].hex()}")
            actual_export_row = record
    if matches != 1 or actual_export_row is None:
        raise OriginalGPLSymbolError(
            f"original-vmlinux-GPL-export-missing count={matches}")
    return actual_export_row, file_sha256.hexdigest()


class OriginalGPLSymbolGateTests(unittest.TestCase):
    """Actual byte fixtures, not an imagined awk regex or fake modpost."""

    def verify_bytes(self, payload: bytes) -> tuple[bytes, str]:
        with tempfile.TemporaryDirectory(prefix="round033-provider-symvers-") as tmp:
            target = Path(tmp) / "Module.symvers"
            target.write_bytes(payload)
            return verify_original_gpl_export(target)

    def test_one_exact_real_pinned_linux_row_and_unrelated_exports(self):
        actual = (b"0x00000000\t" + SYMBOL +
                  b"\tvmlinux\tEXPORT_SYMBOL_GPL\t\n")
        irrelevant = b"0x01234567\tgeneric_export\tvmlinux\tEXPORT_SYMBOL\t\n"
        row, digest = self.verify_bytes(irrelevant + actual)
        self.assertEqual(row, actual.rstrip(b"\n"))
        self.assertEqual(digest,
                         hashlib.sha256(irrelevant + actual).hexdigest())
        self.assertEqual(row.split(b"\t"), [
            b"0x00000000", SYMBOL, EXPECTED_MODULE,
            EXPECTED_EXPORT_TYPE, b""])

    def test_reject_duplicate_absent_and_wrong_owner(self):
        actual = b"0x00000000\t" + SYMBOL + b"\tvmlinux\tEXPORT_SYMBOL_GPL\t\n"
        for label, source, reason in [
            ("absent", b"", "missing"),
            ("duplicate", actual + actual, "duplicate"),
            ("module", actual.replace(b"vmlinux", b"dm-swapz"), "owner"),
            ("nongpl", actual.replace(b"EXPORT_SYMBOL_GPL",
                                      b"EXPORT_SYMBOL"), "GPL-type"),
        ]:
            with self.subTest(label=label):
                with self.assertRaisesRegex(OriginalGPLSymbolError, reason):
                    self.verify_bytes(source)

    def test_reject_separator_field_count_crc_namespace_or_crlf(self):
        actual = b"0x00000000\t" + SYMBOL + b"\tvmlinux\tEXPORT_SYMBOL_GPL\t\n"
        for label, source, reason in [
            ("four-fields", actual[:-2] + b"\n", "field-count"),
            ("spaces", actual.replace(b"\t", b" "), "field-count"),
            ("literal-backslash-t", actual.replace(b"\t", b"\\t"),
             "field-count"),
            ("swapped-columns", actual.replace(
                b"\tvmlinux\t", b"\tEXPORT_SYMBOL_GPL\t"), "owner-or-GPL"),
            ("bad-crc", actual.replace(b"0x00000000", b"none"),
             "CRC-token"),
            ("nonempty-namespace", actual.rstrip(b"\n") + b"priv\n",
             "namespace"),
            ("crlf", actual.replace(b"\n", b"\r\n"), "namespace"),
            ("suffix-symbol", actual.replace(SYMBOL, SYMBOL + b"_fake"),
             "column-mismatch"),
        ]:
            with self.subTest(label=label):
                with self.assertRaisesRegex(OriginalGPLSymbolError, reason):
                    self.verify_bytes(source)

    def test_reproduce_historical_awk_newline_unconditional_count_failure(self):
        """Old awk printed only the target row but counted every row.

        Round032 log printed apparently valid exact export yet failed because
        { found++ } started a NEW awk rule on the following line. This is
        repro with precisely the historical script layout and two REAL row
        shapes. The fixed byte validator must pass the SAME two rows.
        """
        expected = b"0x00000000\t" + SYMBOL + b"\tvmlinux\tEXPORT_SYMBOL_GPL\t\n"
        other = b"0x12345678\tunrelated_kernel_export\tvmlinux\tEXPORT_SYMBOL_GPL\t\n"
        old_script = (
            '$2 == "swapz_ci_bio_snapshot_lz4_v1" &&\n'
            '  $3 == "vmlinux" && $4 == "EXPORT_SYMBOL_GPL"\n'
            '  { found++ } END { exit(found != 1) }'
        )
        old = subprocess.run(
            ["awk", "-F", r"\t", old_script],
            input=expected + other, capture_output=True, check=False)
        self.assertEqual(old.returncode, 1)
        self.assertEqual(old.stdout, expected)
        self.assertEqual(self.verify_bytes(expected + other)[0],
                         expected.rstrip(b"\n"))

    def test_reject_oversize_raw_original_row(self):
        with self.assertRaisesRegex(OriginalGPLSymbolError, "overlong"):
            self.verify_bytes(b"x" * (MAX_ROW_BYTES + 1) + b"\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symvers", type=Path,
                        help="Genuine same original Linux full Kernel Module.symvers")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(
            OriginalGPLSymbolGateTests)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    if args.symvers is None:
        parser.error("--symvers is required unless --self-test")
    try:
        row, digest = verify_original_gpl_export(args.symvers)
    except (OriginalGPLSymbolError, OSError) as error:
        print(f"ROUND033_ORIGINAL_GPL_EXPORT_FAIL: {error}", file=sys.stderr)
        return 3
    # Hex ensures tabs, real trailing empty namespace, and exact checksum are
    # auditable even when GitHub log presentation collapses whitespace.
    print(f"ROUND033_ORIGINAL_GPL_EXPORT_PASS count=1 "
          f"row_bytes={len(row)} row_hex={row.hex()} "
          f"symvers_sha256={digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
