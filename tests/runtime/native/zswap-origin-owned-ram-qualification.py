#!/usr/bin/env python3
"""Read-only Phase A owned-RAM admission and byte-exact evidence guard.

This executable does NOT activate a mapper, zswap, swap or memory pressure.
Caller-supplied status/page samples are untrusted offline consistency evidence,
not proof of a stored zswap entry or a loaded matching module. The production
loaded-trial gate remains closed until independently verified owner authority.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import os
from pathlib import Path
import re
import stat
import sys
import unittest

PAGE_BYTES = 4096
MAX_STATUS_BYTES = 32768
MAX_SAMPLE_BYTES = PAGE_BYTES
UINT64_MAX = (1 << 64) - 1
OBSERVED_COUNTERS = (
    "verified_zswap_origin_admitted",
    "foreground_committed_verified_zswap_writeback",
    "upper_write_completed_ok",
    "upper_write_completed_err",
    "endio_write_seen_err",
    "endio_write_forced_err",
)
REQUIRED_ORIGIN = "origin_carrier_compiled"


class NotQualified(ValueError):
    """A bounded, non-sensitive first cause; never an exception traceback."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise NotQualified(reason)


def read_readonly_regular(path: Path, limit: int, label: str) -> bytes:
    """Read at most limit bytes; never follow symlinks, FIFOs or devices."""
    descriptor = -1
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC |
                             getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        require(stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= limit,
                label + "_type_or_size")
        value = os.read(descriptor, limit + 1)
        require(len(value) == metadata.st_size and len(value) <= limit,
                label + "_changed_during_read")
        return value
    except (OSError, ValueError) as error:
        if isinstance(error, NotQualified):
            raise
        raise NotQualified(label + "_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def parse_status(raw: bytes) -> dict[str, int]:
    require(0 < len(raw) <= MAX_STATUS_BYTES, "status_size")
    try:
        text = raw.decode("ascii", "strict")
    except UnicodeError:
        raise NotQualified("status_encoding") from None
    fields: dict[str, int] = {}
    for field in (*OBSERVED_COUNTERS, REQUIRED_ORIGIN):
        matches = re.findall(r"(?<![\w])" + re.escape(field) +
                             r"=([^\s]+)", text)
        require(len(matches) == 1, "status_missing_or_duplicated_" + field)
        value = matches[0]
        require(re.fullmatch(r"(?:0|[1-9][0-9]*)", value) is not None,
                "status_noncanonical_" + field)
        number = int(value)
        require(number <= UINT64_MAX, "status_overflow_" + field)
        fields[field] = number
    require(fields[REQUIRED_ORIGIN] == 1, "origin_carrier_not_compiled")
    return fields


def compare_offline_samples(before: bytes, after: bytes,
                            original_page: bytes, readback_page: bytes,
                            independent_digest: str) -> None:
    """Never certifies an actual zswap eviction or grants runtime permission."""
    require(len(original_page) == PAGE_BYTES and
            len(readback_page) == PAGE_BYTES, "page_not_exact_4096")
    require(re.fullmatch(r"[0-9a-f]{64}", independent_digest) is not None,
            "original_digest_invalid")
    require(hmac.compare_digest(hashlib.sha256(original_page).hexdigest(),
                                independent_digest), "original_digest_mismatch")
    earlier, later = parse_status(before), parse_status(after)
    for field in OBSERVED_COUNTERS:
        require(later[field] >= earlier[field], "counter_regressed_" + field)
    require(later["verified_zswap_origin_admitted"] -
            earlier["verified_zswap_origin_admitted"] == 1,
            "not_one_authenticated_admission")
    require(later["foreground_committed_verified_zswap_writeback"] -
            earlier["foreground_committed_verified_zswap_writeback"] == 1,
            "not_one_foreground_commit")
    require(later["endio_write_seen_err"] == earlier["endio_write_seen_err"] and
            later["endio_write_forced_err"] == earlier["endio_write_forced_err"] and
            later["upper_write_completed_err"] ==
            earlier["upper_write_completed_err"], "unexpected_error_delta")
    # An upper ACK is an independent observation, never implied by commit.
    require(later["upper_write_completed_ok"] -
            earlier["upper_write_completed_ok"] == 1,
            "not_exactly_one_upper_success")
    require(hmac.compare_digest(original_page, readback_page),
            "readback_bytes_differ")


def environment_preflight() -> None:
    """No privileged action exists in this program; do not infer owner assent.

    The runtime cannot independently prove the current *loaded* module bytes,
    modified booted kernel source SHA, exclusive ram-device ownership, cleanup
    capability or permission. Until a separate authorized owner-run backend
    provides that proof, block even if uname or /proc superficially matches.
    """
    require(Path("/proc/sys/kernel/random/boot_id").is_file(),
            "boot_identity_unavailable")
    require(Path("/sys/module/dm_swapz").is_dir(),
            "matched_module_not_loaded")
    raise NotQualified("loaded_source_ram_ownership_not_authenticated")


def print_refusal(reason: str) -> None:
    # Never display user paths, host identity, raw statuses or page contents.
    print("ENVIRONMENT_NOT_QUALIFIED first_cause=" + reason)
    print("LOADED_STORED_ENTRY=NOT_RUN")
    print("4096_READBACK=NOT_RUN")
    print("PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED")


class RootlessEvidenceTests(unittest.TestCase):
    """Untrusted fixture tests; no live kernel, module or device mutation."""

    @staticmethod
    def status(admitted: int = 3, committed: int = 2, upper_ok: int = 2,
               upper_err: int = 0, errors: int = 0, forced: int = 0,
               carrier: int = 1) -> bytes:
        return (f"verified_zswap_origin_admitted={admitted} "
                f"foreground_committed_verified_zswap_writeback={committed} "
                f"upper_write_completed_ok={upper_ok} "
                f"upper_write_completed_err={upper_err} "
                f"endio_write_seen_err={errors} endio_write_forced_err={forced} "
                f"origin_carrier_compiled={carrier}\n").encode("ascii")

    def setUp(self) -> None:
        self.original = bytes((index * 19 + 7) & 0xff for index in range(PAGE_BYTES))
        self.digest = hashlib.sha256(self.original).hexdigest()
        self.before = self.status()
        self.after = self.status(admitted=4, committed=3, upper_ok=3)

    def check(self, **replace: object) -> None:
        data = {"before": self.before, "after": self.after,
                "original_page": self.original, "readback_page": self.original,
                "independent_digest": self.digest}
        data.update(replace)
        compare_offline_samples(**data)

    def reject(self, reason: str, **replace: object) -> None:
        with self.assertRaisesRegex(NotQualified, "^" + re.escape(reason) + "$"):
            self.check(**replace)

    def test_exact_4096_samples_are_only_offline_consistent(self) -> None:
        self.check()

    def test_readback_changed_byte(self) -> None:
        altered = bytearray(self.original)
        altered[4095] ^= 1
        self.reject("readback_bytes_differ", readback_page=bytes(altered))

    def test_readback_truncated(self) -> None:
        self.reject("page_not_exact_4096", readback_page=self.original[:-1])

    def test_original_truncated(self) -> None:
        self.reject("page_not_exact_4096", original_page=self.original[:-1])

    def test_wrong_independent_digest(self) -> None:
        self.reject("original_digest_mismatch", independent_digest="0" * 64)

    def test_noncanonical_digest(self) -> None:
        self.reject("original_digest_invalid", independent_digest="F" * 64)

    def test_no_authenticated_admission(self) -> None:
        self.reject("not_one_authenticated_admission",
                    after=self.status(admitted=3, committed=3, upper_ok=3))

    def test_double_admission(self) -> None:
        self.reject("not_one_authenticated_admission",
                    after=self.status(admitted=5, committed=3, upper_ok=3))

    def test_no_authoritative_commit(self) -> None:
        self.reject("not_one_foreground_commit",
                    after=self.status(admitted=4, committed=2, upper_ok=3))

    def test_double_commit(self) -> None:
        self.reject("not_one_foreground_commit",
                    after=self.status(admitted=4, committed=4, upper_ok=3))

    def test_upper_error_after_committed_authority(self) -> None:
        self.reject("unexpected_error_delta",
                    after=self.status(admitted=4, committed=3, upper_ok=3,
                                      upper_err=1))

    def test_no_upper_ack_even_after_commit(self) -> None:
        self.reject("not_exactly_one_upper_success",
                    after=self.status(admitted=4, committed=3, upper_ok=2))

    def test_double_upper_ack_even_after_single_commit(self) -> None:
        self.reject("not_exactly_one_upper_success",
                    after=self.status(admitted=4, committed=3, upper_ok=4))

    def test_io_failure_after_commit(self) -> None:
        self.reject("unexpected_error_delta",
                    after=self.status(admitted=4, committed=3, upper_ok=3,
                                      errors=1))

    def test_forced_endio_after_commit(self) -> None:
        self.reject("unexpected_error_delta",
                    after=self.status(admitted=4, committed=3, upper_ok=3,
                                      forced=1))

    def test_counter_regressed(self) -> None:
        self.reject("counter_regressed_verified_zswap_origin_admitted",
                    after=self.status(admitted=2, committed=3, upper_ok=3))

    def test_missing_origin_carrier(self) -> None:
        self.reject("origin_carrier_not_compiled",
                    after=self.status(admitted=4, committed=3, upper_ok=3,
                                      carrier=0))

    def test_missing_status_field(self) -> None:
        self.reject("status_missing_or_duplicated_origin_carrier_compiled",
                    after=self.after.replace(b"origin_carrier_compiled=1", b"missing=1"))

    def test_repeated_status_field(self) -> None:
        self.reject("status_missing_or_duplicated_origin_carrier_compiled",
                    after=self.after + b"origin_carrier_compiled=1\n")

    def test_noncanonical_status_integer(self) -> None:
        self.reject("status_noncanonical_upper_write_completed_ok",
                    after=self.after.replace(b"upper_write_completed_ok=3",
                                             b"upper_write_completed_ok=03"))

    def test_status_uint64_overflow(self) -> None:
        self.reject("status_overflow_upper_write_completed_ok",
                    after=self.after.replace(b"upper_write_completed_ok=3",
                                             b"upper_write_completed_ok=18446744073709551616"))

    def test_status_too_large(self) -> None:
        self.reject("status_size", after=self.after + b" " * MAX_STATUS_BYTES)

    def test_status_non_ascii(self) -> None:
        self.reject("status_encoding", after=self.after + b"\xff")

    def test_readonly_regular_rejects_symlink(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            backing = Path(temporary) / "page"
            backing.write_bytes(self.original)
            link = Path(temporary) / "link"
            link.symlink_to(backing)
            with self.assertRaisesRegex(NotQualified, "^sample_unavailable$"):
                read_readonly_regular(link, MAX_SAMPLE_BYTES, "sample")

    def test_readonly_regular_rejects_fifo(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(NotQualified, "^sample_type_or_size$"):
                read_readonly_regular(fifo, MAX_SAMPLE_BYTES, "sample")

    def test_preflight_never_activates_environment(self) -> None:
        with self.assertRaises(NotQualified):
            environment_preflight()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--offline-compare", action="store_true")
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--original", type=Path)
    parser.add_argument("--readback", type=Path)
    parser.add_argument("--original-sha256", type=str)
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(RootlessEvidenceTests)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1
    try:
        if args.offline_compare:
            require(all((args.before, args.after, args.original, args.readback,
                         args.original_sha256)), "offline_inputs_missing")
            compare_offline_samples(
                read_readonly_regular(args.before, MAX_STATUS_BYTES, "before"),
                read_readonly_regular(args.after, MAX_STATUS_BYTES, "after"),
                read_readonly_regular(args.original, MAX_SAMPLE_BYTES, "original"),
                read_readonly_regular(args.readback, MAX_SAMPLE_BYTES, "readback"),
                args.original_sha256)
            # Even identical samples can be fabricated: no loaded qualification.
            raise NotQualified("offline_samples_cannot_prove_loaded_origin")
        environment_preflight()
    except NotQualified as failure:
        print_refusal(str(failure))
        return 2
    print_refusal("no_authorized_mutating_backend")
    return 2


if __name__ == "__main__":
    sys.exit(main())
