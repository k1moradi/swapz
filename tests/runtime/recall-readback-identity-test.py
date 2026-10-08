#!/usr/bin/env python3
"""Rootless adversarial tests for descriptor-pinned recall readback attestation."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_pinned_readback_identity", HERE / "recall-readback-identity.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)
capture = module.capture_readback_identity
verify = module.verify_readback
ReadbackIdentityError = module.ReadbackIdentityError
PAGE_SIZE = module.PAGE_SIZE


class ReadbackIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swapz-pinned-readback-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name) / "private-fixture"
        self.directory.mkdir(mode=0o700)
        self.directory_fd = os.open(
            self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        self.addCleanup(os.close, self.directory_fd)
        self.expected = bytes(range(256)) * (PAGE_SIZE // 256)
        self.outputs: list[int] = []
        self.addCleanup(self.close_outputs)

    def close_outputs(self) -> None:
        for descriptor in self.outputs:
            os.close(descriptor)

    def create_output(self, role="a"):
        descriptor = os.open(
            "read-" + role,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600, dir_fd=self.directory_fd,
        )
        self.outputs.append(descriptor)
        identity = capture(self.directory_fd, descriptor, role)
        return descriptor, identity

    def check(self, descriptor, identity, expected=None):
        verify(identity, directory_fd=self.directory_fd, output_fd=descriptor,
               expected_page=self.expected if expected is None else expected)

    def test_four_role_outputs_match_immutable_pages(self):
        for role, offset in (("a", 0), ("b", 4), ("a2", 0), ("b2", 5)):
            with self.subTest(role=role):
                descriptor, identity = self.create_output(role)
                page = bytes(((index + offset) % 256) for index in range(PAGE_SIZE))
                os.write(descriptor, page)
                self.check(descriptor, identity, page)

    def test_writer_descriptor_is_write_only_but_readback_can_be_verified(self):
        descriptor, identity = self.create_output()
        self.assertEqual(os.write(descriptor, self.expected), PAGE_SIZE)
        self.check(descriptor, identity)
        self.assertFalse(os.get_inheritable(descriptor))

    def test_replaced_path_with_identical_bytes_is_rejected(self):
        descriptor, identity = self.create_output()
        os.write(descriptor, self.expected)
        (self.directory / "read-a").rename(self.directory / "original-read-a")
        (self.directory / "read-a").write_bytes(self.expected)
        with self.assertRaisesRegex(ReadbackIdentityError, "pathname"):
            self.check(descriptor, identity)

    def test_symlink_substitution_is_rejected_without_following(self):
        descriptor, identity = self.create_output()
        os.write(descriptor, self.expected)
        (self.directory / "read-a").unlink()
        (self.directory / "read-a").symlink_to("nonexistent")
        with self.assertRaises(ReadbackIdentityError):
            self.check(descriptor, identity)

    def test_short_and_oversized_readbacks_are_rejected(self):
        for size in (0, PAGE_SIZE - 1, PAGE_SIZE + 1):
            with self.subTest(size=size):
                role = {0: "a", PAGE_SIZE - 1: "b", PAGE_SIZE + 1: "a2"}[size]
                descriptor, identity = self.create_output(role)
                os.write(descriptor, self.expected[:size] + b"x" * max(0, size - PAGE_SIZE))
                with self.assertRaisesRegex(ReadbackIdentityError, "size"):
                    self.check(descriptor, identity)

    def test_reference_and_output_identical_corruption_is_rejected(self):
        descriptor, identity = self.create_output()
        corrupted = bytes((255 - value) for value in self.expected)
        os.write(descriptor, corrupted)
        # A corrupt expected-on-disk file would make pathname cmp succeed;
        # this verifier compares only to independently retained bytes.
        (self.directory / "expected-a").write_bytes(corrupted)
        with self.assertRaisesRegex(ReadbackIdentityError, "match"):
            self.check(descriptor, identity)

    def test_changed_output_inode_cannot_reuse_stale_identity(self):
        descriptor, identity = self.create_output()
        os.write(descriptor, self.expected)
        other = os.open(
            "other-output", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
            0o600, dir_fd=self.directory_fd,
        )
        self.outputs.append(other)
        os.write(other, self.expected)
        with self.assertRaisesRegex(ReadbackIdentityError, "pinned"):
            self.check(other, identity)

    def test_duplicate_links_and_untrusted_directory_are_rejected(self):
        descriptor, identity = self.create_output()
        os.link(self.directory / "read-a", self.directory / "extra-link")
        with self.assertRaisesRegex(ReadbackIdentityError, "single-link"):
            self.check(descriptor, identity)
        (self.directory / "extra-link").unlink()
        self.directory.chmod(0o755)
        with self.assertRaisesRegex(ReadbackIdentityError, "private"):
            self.check(descriptor, identity)

    def test_malformed_descriptor_role_expected_bytes_and_initial_size(self):
        for invalid_role in ("writer", "../a", "", "x", 1, None):
            with self.subTest(role=invalid_role):
                with self.assertRaises(ReadbackIdentityError):
                    capture(self.directory_fd, self.directory_fd, invalid_role)
        descriptor, identity = self.create_output()
        with self.assertRaises(ReadbackIdentityError):
            self.check(descriptor, identity, b"short")
        os.write(descriptor, b"x")
        with self.assertRaises(ReadbackIdentityError):
            capture(self.directory_fd, descriptor, "a")

    def test_missing_entry_and_closed_descriptor_deny(self):
        descriptor, identity = self.create_output()
        os.write(descriptor, self.expected)
        (self.directory / "read-a").unlink()
        with self.assertRaises(ReadbackIdentityError):
            self.check(descriptor, identity)
        # The descriptor belongs to the fixture, never to this verifier.
        self.assertEqual(os.fstat(descriptor).st_size, PAGE_SIZE)


if __name__ == "__main__":
    unittest.main()
