#!/usr/bin/env python3
"""Read-only loaded-DM candidate evidence; NEVER a loaded trial authorization.

All JSON fields are UNTRUSTED claims even if their syntax and relationships
match. No input (including matching digests) permits module/mapper/swap/pressure
operations or Phase A PASS. A distinct owner-authorized runtime collector is
required to prove provenance, page lifetime, exclusive RAM and safe cleanup.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

PINNED_LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
# Fixed kernel pseudo-files only; no user-controlled host path or device access.
BOOT_ID_SOURCE = Path("/proc/sys/kernel/random/boot_id")
MODULE_SOURCE = Path("/sys/module/dm_swapz")
MODULE_NOTE_NAME = ".note.gnu.build-id"
MAX_MANIFEST_BYTES = 8192
MAX_HOST_OBSERVATION_BYTES = 16384
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
BOOT_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
KERNEL_RELEASE = re.compile(r"[A-Za-z0-9._+\-]{1,160}\Z")
OWNER_TAG = re.compile(r"[A-Za-z0-9_\-]{16,96}\Z")
REQUIRED = frozenset({
    "schema_version", "pinned_linux_source_sha", "booted_linux_source_sha",
    "boot_id", "boot_image_sha256", "measured_boot_image_sha256",
    "kernel_release", "swapz_source_sha", "module_source_sha",
    "module_disk_sha256", "loaded_module_sha256", "module_vermagic",
    "loaded_module_vermagic", "module_state", "origin_carrier_compiled",
    "ram_backing_kind", "ram_backing_exclusive", "ram_backing_owner_count",
    "ram_owner_token", "owner_permission", "cleanup_permission",
    "cleanup_verified", "deadline_seconds", "pressure_budget_mib",
    "page_generation", "source_record_identity", "original_page_sha256",
    "stored_entry_eviction_observed", "mm_req_swap_write_observed",
    "loaded_dm_commit_observed", "upper_ack_observed",
    "swapin_4096_observed",
})


class NotQualified(ValueError):
    """Safe bounded first-failure category without leaking host evidence."""


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise NotQualified(reason)


def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        require(key not in result, "duplicate_manifest_key")
        result[key] = value
    return result


def parse_manifest(raw: bytes) -> dict[str, object]:
    require(0 < len(raw) <= MAX_MANIFEST_BYTES, "manifest_size")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates,
                              parse_constant=lambda _: (_ for _ in ()).throw(
                                  NotQualified("invalid_manifest_number")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, NotQualified):
            raise
        raise NotQualified("manifest_parse") from None
    require(type(document) is dict and document.keys() == REQUIRED,
            "manifest_missing_or_extra_fields")
    return document


def check_candidate(raw: bytes, expected_swapz_sha: str) -> dict[str, object]:
    """Only check claimed relationships; NEVER authenticate source or owner."""
    require(SHA40.fullmatch(expected_swapz_sha) is not None,
            "expected_source_sha_invalid")
    claim = parse_manifest(raw)
    require(claim["schema_version"] == 1 and type(claim["schema_version"]) is int,
            "manifest_version")
    require(claim["pinned_linux_source_sha"] == PINNED_LINUX_SHA and
            claim["booted_linux_source_sha"] == PINNED_LINUX_SHA,
            "pinned_linux_source_mismatch")
    require(claim["swapz_source_sha"] == expected_swapz_sha and
            claim["module_source_sha"] == expected_swapz_sha,
            "module_source_mismatch")
    for key in ("boot_image_sha256", "measured_boot_image_sha256",
                "module_disk_sha256", "loaded_module_sha256",
                "original_page_sha256"):
        value = claim[key]
        require(type(value) is str and SHA256.fullmatch(value) is not None and
                value != "0" * 64, "invalid_digest_" + key)
    require(claim["boot_image_sha256"] == claim["measured_boot_image_sha256"],
            "boot_image_digest_mismatch")
    require(claim["module_disk_sha256"] == claim["loaded_module_sha256"],
            "loaded_module_digest_mismatch")
    require(type(claim["boot_id"]) is str and
            BOOT_ID.fullmatch(claim["boot_id"]) is not None,
            "boot_id_invalid")
    release = claim["kernel_release"]
    require(type(release) is str and KERNEL_RELEASE.fullmatch(release) is not None,
            "kernel_release_invalid")
    for key in ("module_vermagic", "loaded_module_vermagic"):
        value = claim[key]
        require(type(value) is str and len(value) <= 256 and
                value.split(" ", 1)[0] == release,
                "module_vermagic_mismatch")
    require(claim["loaded_module_vermagic"] == claim["module_vermagic"] and
            claim["module_state"] == "live", "module_not_identical_and_live")
    require(type(claim["origin_carrier_compiled"]) is int and
            claim["origin_carrier_compiled"] == 1, "carrier_not_compiled")
    require(claim["ram_backing_kind"] == "brd" and
            claim["ram_backing_exclusive"] is True and
            type(claim["ram_backing_owner_count"]) is int and
            claim["ram_backing_owner_count"] == 1, "ram_not_exclusively_owned")
    require(type(claim["ram_owner_token"]) is str and
            OWNER_TAG.fullmatch(claim["ram_owner_token"]) is not None,
            "owner_identity_invalid")
    require(claim["owner_permission"] is True and
            claim["cleanup_permission"] is True and
            claim["cleanup_verified"] is True,
            "owner_or_cleanup_authority_missing")
    for field, maximum in (("deadline_seconds", 120), ("pressure_budget_mib", 128),
                           ("page_generation", (1 << 64) - 1),
                           ("source_record_identity", (1 << 64) - 1)):
        value = claim[field]
        require(type(value) is int and 0 < value <= maximum,
                "invalid_bound_" + field)
    for event in ("stored_entry_eviction_observed", "mm_req_swap_write_observed",
                  "loaded_dm_commit_observed", "upper_ack_observed",
                  "swapin_4096_observed"):
        require(claim[event] is True, "event_unproven_" + event)
    return claim


def read_readonly_regular(path: Path) -> bytes:
    """Source candidate is a short ordinary file, never a block device or FIFO."""
    fd = -1
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC |
                     getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and
                0 < before.st_size <= MAX_MANIFEST_BYTES, "manifest_file_type_or_size")
        data = os.read(fd, MAX_MANIFEST_BYTES + 1)
        after = os.fstat(fd)
        require(len(data) == before.st_size and
                before.st_ino == after.st_ino and
                before.st_dev == after.st_dev and
                before.st_size == after.st_size and
                before.st_mtime_ns == after.st_mtime_ns,
                "manifest_changed_during_read")
        return data
    except OSError:
        raise NotQualified("manifest_file_unavailable") from None
    finally:
        if fd >= 0:
            os.close(fd)



def read_fixed_host_blob(path: Path, maximum_bytes: int, label: str) -> bytes:
    """Nofollow, bounded read from fixed proc/sysfs kernel evidence.

    procfs/sysfs files may advertise st_size=0 or PAGE_SIZE. Neither a
    pseudo-file inode nor a matching build ID authenticates loaded code bytes.
    """
    descriptor = -1
    try:
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC |
            getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and
                (before.st_size in (0, 4096) or
                 0 < before.st_size <= maximum_bytes),
                label + "_type_or_size")
        blob = os.read(descriptor, maximum_bytes + 1)
        after = os.fstat(descriptor)
        require(0 < len(blob) <= maximum_bytes and
                (before.st_size in (0, 4096) or
                 before.st_size == len(blob)) and
                (before.st_dev, before.st_ino, before.st_mode,
                 before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_mode,
                 after.st_size, after.st_mtime_ns),
                label + "_changed_or_oversize")
        return blob
    except OSError:
        raise NotQualified(label + "_unavailable") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_fixed_host_text(path: Path, maximum_bytes: int, label: str) -> str:
    """Reject non-ASCII, NUL and arbitrary whitespace from kernel metadata."""
    raw = read_fixed_host_blob(path, maximum_bytes, label)
    try:
        value = raw.decode("ascii", "strict")
    except UnicodeError:
        raise NotQualified(label + "_encoding") from None
    require("\x00" not in value and
            value == value.strip() + ("\n" if value.endswith("\n") else ""),
            label + "_malformed")
    return value.removesuffix("\n")


def parse_kernel_module_build_id_note(raw: bytes) -> str:
    """Validate a GNU ELF module note, never treat it as full module digest."""
    require(32 <= len(raw) <= 128, "module_build_id_invalid")
    name_size, digest_size, note_type = struct.unpack_from("=III", raw)
    padded_digest_size = (digest_size + 3) & ~3
    require(name_size == 4 and note_type == 3 and
            16 <= digest_size <= 64 and
            len(raw) == 16 + padded_digest_size and
            raw[12:16] == b"GNU\x00" and
            raw[16:16 + digest_size] != b"\x00" * digest_size,
            "module_build_id_invalid")
    return raw[16:16 + digest_size].hex()


def read_actual_module_metadata() -> bool:
    """Read only immutable sysfs-shaped host facts; no authorization result."""
    try:
        metadata = os.lstat(MODULE_SOURCE)
    except FileNotFoundError:
        return False
    except OSError:
        raise NotQualified("actual_module_identity_unavailable") from None
    require(stat.S_ISDIR(metadata.st_mode), "actual_module_directory_invalid")
    state = read_fixed_host_text(MODULE_SOURCE / "initstate", 32,
                                 "actual_module_initstate")
    require(state == "live", "actual_module_not_live")
    try:
        notes_metadata = os.lstat(MODULE_SOURCE / "notes")
    except OSError:
        raise NotQualified("actual_module_notes_unavailable") from None
    require(stat.S_ISDIR(notes_metadata.st_mode),
            "actual_module_notes_invalid")
    note = read_fixed_host_blob(MODULE_SOURCE / "notes" / MODULE_NOTE_NAME,
                                128, "actual_module_build_id")
    require(bool(parse_kernel_module_build_id_note(note)),
            "module_build_id_invalid")
    return True


def probe_claim_against_host(claim: dict[str, object],
                             observed_boot_id: str, observed_release: str,
                             observed_module_live: bool) -> None:
    """Read-only host discrepancies reject, but matches are NOT authentication."""
    require(claim["boot_id"] == observed_boot_id, "actual_boot_id_mismatch")
    require(claim["kernel_release"] == observed_release,
            "actual_kernel_release_mismatch")
    require(observed_module_live, "actual_module_not_loaded")


def read_actual_boot_identity() -> tuple[str, str, bool]:
    """Read actual boot and module metadata; never certify loaded bytes."""
    boot_id = read_fixed_host_text(BOOT_ID_SOURCE, 64, "actual_boot_id")
    try:
        release = os.uname().release
    except OSError:
        raise NotQualified("actual_kernel_release_unavailable") from None
    require(BOOT_ID.fullmatch(boot_id) is not None, "actual_boot_id_invalid")
    require(KERNEL_RELEASE.fullmatch(release) is not None,
            "actual_kernel_release_invalid")
    return boot_id, release, read_actual_module_metadata()


def refusal(reason: str) -> None:
    print("ENVIRONMENT_NOT_QUALIFIED first_cause=" + reason)
    print("LOADED_STORED_ENTRY=NOT_RUN")
    print("4096_READBACK=NOT_RUN")
    print("PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED")


class CandidateTests(unittest.TestCase):
    """Synthetic manifest tests: not kernel, loaded module or owner evidence."""

    def setUp(self) -> None:
        self.source_sha = "a" * 40
        self.fields: dict[str, object] = {
            "schema_version": 1,
            "pinned_linux_source_sha": PINNED_LINUX_SHA,
            "booted_linux_source_sha": PINNED_LINUX_SHA,
            "boot_id": "12345678-1234-1234-1234-123456789abc",
            "boot_image_sha256": "1" * 64,
            "measured_boot_image_sha256": "1" * 64,
            "kernel_release": "6.12.0-test",
            "swapz_source_sha": self.source_sha,
            "module_source_sha": self.source_sha,
            "module_disk_sha256": "2" * 64,
            "loaded_module_sha256": "2" * 64,
            "module_vermagic": "6.12.0-test SMP preempt",
            "loaded_module_vermagic": "6.12.0-test SMP preempt",
            "module_state": "live",
            "origin_carrier_compiled": 1,
            "ram_backing_kind": "brd",
            "ram_backing_exclusive": True,
            "ram_backing_owner_count": 1,
            "ram_owner_token": "test_owned_ephemeral_ram_1",
            "owner_permission": True,
            "cleanup_permission": True,
            "cleanup_verified": True,
            "deadline_seconds": 60,
            "pressure_budget_mib": 64,
            "page_generation": 5,
            "source_record_identity": 7,
            "original_page_sha256": "3" * 64,
            "stored_entry_eviction_observed": True,
            "mm_req_swap_write_observed": True,
            "loaded_dm_commit_observed": True,
            "upper_ack_observed": True,
            "swapin_4096_observed": True,
        }

    def raw(self) -> bytes:
        return json.dumps(self.fields, sort_keys=True).encode("ascii")

    def reject(self, field: str, value: object, first_cause: str) -> None:
        self.fields[field] = value
        with self.assertRaisesRegex(NotQualified, "^" + re.escape(first_cause) + "$"):
            check_candidate(self.raw(), self.source_sha)

    def test_self_consistent_claims_remain_untrusted(self) -> None:
        self.assertEqual(check_candidate(self.raw(), self.source_sha), self.fields)

    def test_wrong_pinned_sha(self) -> None:
        self.reject("booted_linux_source_sha", "0" * 40, "pinned_linux_source_mismatch")

    def test_wrong_module_source_sha(self) -> None:
        self.reject("module_source_sha", "0" * 40, "module_source_mismatch")

    def test_wrong_expected_source_sha(self) -> None:
        with self.assertRaisesRegex(NotQualified, "module_source_mismatch"):
            check_candidate(self.raw(), "b" * 40)

    def test_wrong_boot_digest(self) -> None:
        self.reject("measured_boot_image_sha256", "4" * 64,
                    "boot_image_digest_mismatch")

    def test_wrong_loaded_module_digest(self) -> None:
        self.reject("loaded_module_sha256", "4" * 64,
                    "loaded_module_digest_mismatch")

    def test_zero_digest(self) -> None:
        self.reject("original_page_sha256", "0" * 64,
                    "invalid_digest_original_page_sha256")

    def test_wrong_release(self) -> None:
        self.reject("kernel_release", "6.12.1", "module_vermagic_mismatch")

    def test_wrong_vermagic(self) -> None:
        self.reject("loaded_module_vermagic", "6.12.0-test other",
                    "module_not_identical_and_live")

    def test_not_live(self) -> None:
        self.reject("module_state", "loading", "module_not_identical_and_live")

    def test_no_origin_carrier(self) -> None:
        self.reject("origin_carrier_compiled", 0, "carrier_not_compiled")

    def test_boolean_as_origin_carrier(self) -> None:
        self.reject("origin_carrier_compiled", True, "carrier_not_compiled")

    def test_other_backing(self) -> None:
        self.reject("ram_backing_kind", "physical_partition", "ram_not_exclusively_owned")

    def test_shared_ram(self) -> None:
        self.reject("ram_backing_owner_count", 2, "ram_not_exclusively_owned")

    def test_claimed_owner_permission_missing(self) -> None:
        self.reject("owner_permission", False, "owner_or_cleanup_authority_missing")

    def test_cleanup_not_verified(self) -> None:
        self.reject("cleanup_verified", False, "owner_or_cleanup_authority_missing")

    def test_unbounded_deadline(self) -> None:
        self.reject("deadline_seconds", 1000, "invalid_bound_deadline_seconds")

    def test_unbounded_pressure(self) -> None:
        self.reject("pressure_budget_mib", 1024, "invalid_bound_pressure_budget_mib")

    def test_missing_page_generation(self) -> None:
        self.reject("page_generation", 0, "invalid_bound_page_generation")

    def test_stale_source_record(self) -> None:
        self.reject("source_record_identity", 0, "invalid_bound_source_record_identity")

    def test_fake_stored_entry_event(self) -> None:
        self.reject("stored_entry_eviction_observed", False,
                    "event_unproven_stored_entry_eviction_observed")

    def test_fake_req_swap_event(self) -> None:
        self.reject("mm_req_swap_write_observed", False,
                    "event_unproven_mm_req_swap_write_observed")

    def test_no_upper_ack(self) -> None:
        self.reject("upper_ack_observed", False, "event_unproven_upper_ack_observed")

    def test_no_swapin(self) -> None:
        self.reject("swapin_4096_observed", False, "event_unproven_swapin_4096_observed")

    def test_extra_fields(self) -> None:
        self.fields["pretend_approved"] = True
        with self.assertRaisesRegex(NotQualified, "manifest_missing_or_extra_fields"):
            check_candidate(self.raw(), self.source_sha)

    def test_missing_field(self) -> None:
        del self.fields["boot_id"]
        with self.assertRaisesRegex(NotQualified, "manifest_missing_or_extra_fields"):
            check_candidate(self.raw(), self.source_sha)

    def test_duplicate_key(self) -> None:
        raw = self.raw().rstrip()[:-1] + b', "boot_id": "forged"}'
        with self.assertRaisesRegex(NotQualified, "duplicate_manifest_key"):
            check_candidate(raw, self.source_sha)

    def test_symlink_manifest_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            regular = Path(temporary) / "manifest"
            regular.write_bytes(self.raw())
            link = Path(temporary) / "symlink"
            link.symlink_to(regular)
            with self.assertRaisesRegex(NotQualified, "manifest_file_unavailable"):
                read_readonly_regular(link)

    def test_fifo_manifest_refused_without_hanging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fifo = Path(temporary) / "fifo"
            os.mkfifo(fifo)
            with self.assertRaises(NotQualified):
                read_readonly_regular(fifo)

    def test_host_boot_mismatch(self) -> None:
        candidate = check_candidate(self.raw(), self.source_sha)
        with self.assertRaisesRegex(NotQualified, "actual_boot_id_mismatch"):
            probe_claim_against_host(candidate, "0" * 36, "6.12.0-test", True)

    def test_host_kernel_mismatch(self) -> None:
        candidate = check_candidate(self.raw(), self.source_sha)
        with self.assertRaisesRegex(NotQualified, "actual_kernel_release_mismatch"):
            probe_claim_against_host(candidate, self.fields["boot_id"], "6.11-test", True)

    def test_module_not_actually_loaded(self) -> None:
        candidate = check_candidate(self.raw(), self.source_sha)
        with self.assertRaisesRegex(NotQualified, "actual_module_not_loaded"):
            probe_claim_against_host(candidate, self.fields["boot_id"], "6.12.0-test", False)

    def test_oversize_input(self) -> None:
        with self.assertRaisesRegex(NotQualified, "manifest_size"):
            check_candidate(self.raw() + b" " * MAX_MANIFEST_BYTES, self.source_sha)



class HostReadOnlyTests(unittest.TestCase):
    """Disposable proc/sysfs-shaped fixtures; no loaded-kernel PASS."""

    @staticmethod
    def note_bytes():
        return (struct.pack("=III", 4, 20, 3) + b"GNU\x00" +
                bytes(range(1, 21)))

    def test_kernel_module_note_is_exact_and_nonempty(self) -> None:
        note = self.note_bytes()
        self.assertEqual(len(parse_kernel_module_build_id_note(note)), 40)
        for wrong in (note[:-1], note + b"x", note[:8], b"\x00" * len(note),
                      struct.pack("=III", 4, 20, 2) + note[12:]):
            with self.subTest(size=len(wrong)):
                with self.assertRaisesRegex(NotQualified, "module_build_id_invalid"):
                    parse_kernel_module_build_id_note(wrong)

    def test_host_regular_read_rejects_symlink_fifo_large_and_nul(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "page"
            page.write_bytes(b"live\n")
            link = root / "link"
            link.symlink_to(page)
            with self.assertRaisesRegex(NotQualified, "probe_unavailable"):
                read_fixed_host_blob(link, 32, "probe")
            fifo = root / "fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(NotQualified, "probe_type_or_size"):
                read_fixed_host_blob(fifo, 32, "probe")
            page.write_bytes(b"q" * 100)
            with self.assertRaises(NotQualified):
                read_fixed_host_blob(page, 32, "probe")
            page.write_bytes(b"live\x00\n")
            with self.assertRaisesRegex(NotQualified, "probe_malformed"):
                read_fixed_host_text(page, 32, "probe")
            page.write_bytes(b"live\n")
            self.assertEqual(read_fixed_host_text(page, 32, "probe"), "live")

    def test_independent_host_facts_are_not_authorizing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            boot = root / "boot_id"
            boot.write_text("12345678-1234-1234-1234-123456789abc\n",
                            encoding="ascii")
            module = root / "module"
            (module / "notes").mkdir(parents=True)
            (module / "initstate").write_text("live\n", encoding="ascii")
            (module / "notes" / MODULE_NOTE_NAME).write_bytes(self.note_bytes())
            with mock.patch.dict(globals(), {"BOOT_ID_SOURCE": boot,
                                             "MODULE_SOURCE": module}), \
                    mock.patch.object(os, "uname",
                                      return_value=SimpleNamespace(release="6.12.0-test")):
                boot_id, release, module_live = read_actual_boot_identity()
                self.assertTrue(module_live)
                self.assertEqual(release, "6.12.0-test")
                self.assertEqual(boot_id,
                                 "12345678-1234-1234-1234-123456789abc")
                console = io.StringIO()
                with mock.patch.object(sys, "argv", ["contract", "--inspect-host"]), \
                        contextlib.redirect_stdout(console):
                    self.assertEqual(main(), 2)
                self.assertIn("ENVIRONMENT_NOT_QUALIFIED", console.getvalue())
                self.assertIn("LOADED_STORED_ENTRY=NOT_RUN", console.getvalue())
                self.assertIn("4096_READBACK=NOT_RUN", console.getvalue())
                self.assertNotIn("PHASE_A=PASS", console.getvalue())

                (module / "initstate").write_text("coming\n", encoding="ascii")
                with self.assertRaisesRegex(NotQualified, "actual_module_not_live"):
                    read_actual_boot_identity()
                (module / "initstate").write_text("live\n", encoding="ascii")
                (module / "notes" / MODULE_NOTE_NAME).write_bytes(b"short")
                with self.assertRaisesRegex(NotQualified, "module_build_id_invalid"):
                    read_actual_boot_identity()
                (module / "notes" / MODULE_NOTE_NAME).write_bytes(self.note_bytes())
                boot.write_text("stale-boot\n", encoding="ascii")
                with self.assertRaisesRegex(NotQualified, "actual_boot_id_invalid"):
                    read_actual_boot_identity()
                boot.unlink()
                with self.assertRaisesRegex(NotQualified, "actual_boot_id_unavailable"):
                    read_actual_boot_identity()

    def test_module_absent_or_symlink_is_not_live(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = root / "missing"
            with mock.patch.dict(globals(), {"MODULE_SOURCE": module}):
                self.assertFalse(read_actual_module_metadata())
                real = root / "real"
                real.mkdir()
                module.symlink_to(real, target_is_directory=True)
                with self.assertRaisesRegex(NotQualified,
                                            "actual_module_directory_invalid"):
                    read_actual_module_metadata()

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--inspect-candidate", type=Path)
    mode.add_argument("--inspect-host", action="store_true")
    parser.add_argument("--expected-source-sha")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.TestSuite((
            unittest.defaultTestLoader.loadTestsFromTestCase(CandidateTests),
            unittest.defaultTestLoader.loadTestsFromTestCase(HostReadOnlyTests)))
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    try:
        if args.inspect_host:
            _, _, module_live = read_actual_boot_identity()
            require(module_live, "actual_module_not_loaded")
            # No sysfs evidence alone authenticates the booted Linux source,
            # immutable loaded module bytes or owned RAM swap-in session.
            raise NotQualified("host_metadata_not_boot_or_module_byte_attestation")
        require(bool(args.expected_source_sha), "expected_source_sha_missing")
        claim = check_candidate(read_readonly_regular(args.inspect_candidate),
                                args.expected_source_sha)
        observed_boot_id, observed_release, observed_loaded = read_actual_boot_identity()
        probe_claim_against_host(claim, observed_boot_id, observed_release,
                                 observed_loaded)
        # No public metadata, including a matching uname/sysfs, independently
        # authenticates the loaded module bytes or grants RAM/owner control.
        raise NotQualified("claims_do_not_prove_loaded_module_or_ram_ownership")
    except NotQualified as error:
        refusal(str(error))
        return 2


if __name__ == "__main__":
    sys.exit(main())
