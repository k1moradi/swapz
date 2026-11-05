#!/usr/bin/env python3
"""Rootless Linux pathname-provenance regression for active-swap admission.

This test never calls swapon/swapoff, opens a block device, or mutates the host
mount namespace.  It uses an unprivileged user+mount namespace and ordinary
files to demonstrate the specific provenance gap in resolving a kernel-rendered
pathname back through the caller's current mount view.

Linux /proc/self/fd/N readlink and seq_file_path() both render a retained
``struct path`` via d_path().  The overmount case therefore exercises the VFS
property relevant to /proc/swaps without claiming that it activates swap or
reproduces a live swap race.
"""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


MS_BIND = 4096
MS_REC = 16384
MS_PRIVATE = 1 << 18
MNT_DETACH = 2
SKIP_EXIT = 77
CHILD_MARKER = "SWAPZ_PROVENANCE_CHILD_STARTED"


def _mount(source: str | None, target: Path, fs_type: str | None, flags: int,
           data: str | None = None) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    mount = libc.mount
    mount.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                      ctypes.c_ulong, ctypes.c_char_p]
    mount.restype = ctypes.c_int

    def encoded(value: str | None) -> bytes | None:
        return None if value is None else os.fsencode(value)

    if mount(encoded(source), os.fsencode(target), encoded(fs_type), flags,
             encoded(data)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def _umount(target: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    umount2 = libc.umount2
    umount2.argtypes = [ctypes.c_char_p, ctypes.c_int]
    umount2.restype = ctypes.c_int
    if umount2(os.fsencode(target), MNT_DETACH) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def _child_bind_overmount() -> int:
    """Run after `unshare --user --map-root-user --mount`.

    A retained ordinary-file descriptor stands in only for the kernel-held
    swap ``struct file``.  The test proves a VFS pathname-rendering property,
    not actual swap ownership.
    """
    print(CHILD_MARKER, file=sys.stderr, flush=True)
    try:
        # Prevent any mount made by this child from propagating to a peer
        # namespace even if the host's root mount is shared.
        _mount(None, Path("/"), None, MS_REC | MS_PRIVATE)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES, errno.EINVAL, errno.ENOSYS}:
            print(f"SKIP: private mount namespace unavailable: errno={exc.errno}",
                  file=sys.stderr)
            return SKIP_EXIT
        raise

    with tempfile.TemporaryDirectory(prefix="swapz-provenance-") as root_text:
        root = Path(root_text)
        visible_directory = root / "visible"
        replacement_source = root / "replacement-source"
        visible_directory.mkdir()
        replacement_source.mkdir()
        original_path = visible_directory / "swapfile"
        original_path.write_bytes(b"original ordinary fixture\n")

        descriptor = os.open(original_path, os.O_RDONLY | os.O_CLOEXEC)
        replacement_mounted = False
        bind_mounted = False
        try:
            proc_descriptor = Path(f"/proc/self/fd/{descriptor}")
            rendered_before = os.readlink(proc_descriptor)
            held_before = os.fstat(descriptor)

            try:
                _mount("tmpfs", replacement_source, "tmpfs", 0,
                       "size=1m,mode=700")
                replacement_mounted = True
                replacement = replacement_source / "swapfile"
                replacement.write_bytes(b"replacement ordinary fixture\n")
                _mount(os.fspath(replacement_source), visible_directory, None,
                       MS_BIND)
                bind_mounted = True
            except OSError as exc:
                if exc.errno in {
                    errno.EPERM, errno.EACCES, errno.EINVAL, errno.ENODEV,
                    errno.ENOSYS,
                }:
                    print(
                        f"SKIP: rootless bind-overmount unavailable: errno={exc.errno}",
                        file=sys.stderr,
                    )
                    return SKIP_EXIT
                raise

            rendered_after = os.readlink(proc_descriptor)
            held_after = os.fstat(descriptor)
            current = os.lstat(original_path)

            selected_device = held_before.st_dev
            parent_device = selected_device + 1
            while parent_device in {selected_device, current.st_dev}:
                parent_device += 1
            result = {
                "reported_path": os.fspath(original_path),
                "rendered_before": rendered_before,
                "rendered_after": rendered_after,
                "held_before": [held_before.st_dev, held_before.st_ino],
                "held_after": [held_after.st_dev, held_after.st_ino],
                "current": [current.st_dev, current.st_ino],
                "current_is_regular": stat.S_ISREG(current.st_mode),
                "current_is_symlink": stat.S_ISLNK(current.st_mode),
                "selected_device": selected_device,
                "parent_device": parent_device,
                # Countermodel the proposed regular-file exclusion exactly:
                # the retained object conflicts with the modeled selected
                # filesystem, while the current lookup appears unrelated to
                # both the selected partition and its distinct parent.
                "proposed_current_path_admits": current.st_dev not in {
                    selected_device, parent_device
                },
                "retained_backing_conflicts": held_after.st_dev == selected_device,
            }
            print(json.dumps(result, sort_keys=True))
            return 0
        finally:
            if bind_mounted:
                _umount(visible_directory)
            if replacement_mounted:
                _umount(replacement_source)
            os.close(descriptor)


class ActiveSwapProvenanceModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if sys.platform != "linux" or not Path("/proc/self/fd").is_dir():
            raise unittest.SkipTest("Linux procfs is required")

    def test_retained_path_tracks_rename_and_marks_unlink(self) -> None:
        """Correct the earlier model: d_path is not a frozen swapon pathname."""
        with tempfile.TemporaryDirectory(prefix="swapz-provenance-") as root_text:
            root = Path(root_text)
            original = root / "swapfile"
            renamed = root / "renamed-swapfile"
            original.write_bytes(b"ordinary fixture\n")
            descriptor = os.open(original, os.O_RDONLY | os.O_CLOEXEC)
            try:
                proc_descriptor = f"/proc/self/fd/{descriptor}"
                self.assertEqual(os.readlink(proc_descriptor), os.fspath(original))
                original.rename(renamed)
                self.assertEqual(os.readlink(proc_descriptor), os.fspath(renamed))
                renamed.unlink()
                self.assertEqual(
                    os.readlink(proc_descriptor), f"{renamed} (deleted)"
                )
            finally:
                os.close(descriptor)

    def test_bind_overmount_can_diverge_rendered_name_from_lookup(self) -> None:
        """A covered retained mount can print a name that resolves elsewhere."""
        unshare = shutil.which("unshare")
        if unshare is None:
            self.skipTest("util-linux unshare is unavailable")

        result = subprocess.run(
            [
                unshare,
                "--user",
                "--map-root-user",
                "--mount",
                sys.executable,
                "-B",
                os.path.abspath(__file__),
                "--child-bind-overmount",
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        child_started = CHILD_MARKER in result.stderr
        if not child_started:
            self.skipTest(
                result.stderr.strip() or "unprivileged user/mount namespaces unavailable"
            )
        if result.returncode == SKIP_EXIT:
            self.skipTest(result.stderr.strip() or "rootless mount unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, result.stdout)
        observed = json.loads(lines[0])

        self.assertEqual(observed["rendered_before"], observed["reported_path"])
        self.assertEqual(observed["rendered_after"], observed["reported_path"])
        self.assertEqual(observed["held_before"], observed["held_after"])
        self.assertNotEqual(observed["held_after"], observed["current"])
        self.assertNotEqual(observed["held_after"][0], observed["current"][0])
        self.assertTrue(observed["current_is_regular"])
        self.assertFalse(observed["current_is_symlink"])
        self.assertTrue(observed["proposed_current_path_admits"])
        self.assertTrue(observed["retained_backing_conflicts"])


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--child-bind-overmount":
        raise SystemExit(_child_bind_overmount())
    unittest.main(verbosity=2)
