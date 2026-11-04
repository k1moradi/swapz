#!/usr/bin/env python3
"""Remove only completed, positively owned swapz benchmark scratch sessions.

Private qualification helper. Directory descriptors pin traversal; no path below the
validated temporary root is followed through a symlink or another mount.
"""

import os
import re
import stat
import sys
from dataclasses import dataclass


SESSION_NAME = re.compile(r"swapz-benchmark\.[A-Za-z0-9]{8}\Z")
OWNER_RECORD = re.compile(rb"pid=([1-9][0-9]*)\nsource_sha=([0-9a-f]{40})\n\Z")
OWNER_FILE = ".swapz-benchmark-owner"
COMPLETE_FILE = ".swapz-benchmark-complete"
MAX_ROOT_ENTRIES = 100_000
MAX_SESSIONS = 256
MAX_TOTAL_OBJECTS = 65_536
MAX_SESSION_OBJECTS = 8_192
MAX_DEPTH = 8
MAX_TOTAL_BYTES = 64 * 1024**3
OPEN_FLAGS = os.O_CLOEXEC | os.O_NOFOLLOW


class CleanupBlocked(Exception):
    """A cleanup safety invariant was not proved."""


@dataclass
class Budget:
    root_entries: int = 0
    sessions: int = 0
    objects: int = 0
    bytes: int = 0


@dataclass
class Entry:
    name: str
    device: int
    inode: int
    mode: int
    children: list["Entry"] | None


def require(condition: bool, diagnostic: str) -> None:
    if not condition:
        raise CleanupBlocked(diagnostic)


def mount_id(descriptor: int) -> str:
    # Detect bind mounts too: st_dev alone is insufficient on a shared device.
    with open(f"/proc/self/fdinfo/{descriptor}", encoding="ascii") as info:
        matches = [line.split()[1] for line in info if line.startswith("mnt_id:")]
    require(len(matches) == 1 and matches[0].isdigit(), "mount identity unavailable")
    return matches[0]


def read_marker(directory: int, name: str, owner_uid: int, expected_mount: str) -> bytes | None:
    try:
        file_stat = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    # A hard link, a symlink, or a non-private marker is not ownership proof.
    if not (stat.S_ISREG(file_stat.st_mode) and file_stat.st_uid == owner_uid
            and stat.S_IMODE(file_stat.st_mode) == 0o600
            and file_stat.st_nlink == 1 and file_stat.st_size <= 128):
        return None
    descriptor = os.open(name, os.O_RDONLY | OPEN_FLAGS | os.O_NONBLOCK, dir_fd=directory)
    try:
        opened = os.fstat(descriptor)
        if ((opened.st_dev, opened.st_ino) != (file_stat.st_dev, file_stat.st_ino)
                or mount_id(descriptor) != expected_mount):
            return None
        contents = os.read(descriptor, 129)
        return contents if len(contents) <= 128 else None
    finally:
        os.close(descriptor)


def owned_complete(directory: int, owner_uid: int, expected_mount: str) -> bool:
    owner = read_marker(directory, OWNER_FILE, owner_uid, expected_mount)
    complete = read_marker(directory, COMPLETE_FILE, owner_uid, expected_mount)
    if owner is None or owner != complete:
        return False
    match = OWNER_RECORD.fullmatch(owner)
    if match is None:
        return False
    process_id = int(match.group(1))
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass  # Not proven dead; preserve it.
    return False


def inspect(directory: int, expected_mount: str, owner_uid: int,
            budget: Budget, session_objects: list[int], depth: int) -> list[Entry]:
    require(depth <= MAX_DEPTH, "session nesting exceeds cleanup bound")
    entries = []
    with os.scandir(directory) as iterator:
        for directory_entry in iterator:
            session_objects[0] += 1
            budget.objects += 1
            require(session_objects[0] <= MAX_SESSION_OBJECTS
                    and budget.objects <= MAX_TOTAL_OBJECTS,
                    "session entry count exceeds cleanup bound")
            name = directory_entry.name
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            require(before.st_uid == owner_uid, "foreign-owned session entry")
            is_directory = stat.S_ISDIR(before.st_mode)
            require(is_directory or stat.S_ISREG(before.st_mode),
                    "symlink or special session entry")
            require(stat.S_IMODE(before.st_mode) & 0o077 == 0,
                    "session entry permissions are not private")
            if not is_directory:
                require(before.st_nlink == 1, "hard-linked session file")
                budget.bytes += before.st_size
                require(budget.bytes <= MAX_TOTAL_BYTES,
                        "session bytes exceed cleanup bound")
            flags = os.O_DIRECTORY if is_directory else os.O_PATH
            child = os.open(name, flags | OPEN_FLAGS, dir_fd=directory)
            try:
                opened = os.fstat(child)
                require((before.st_dev, before.st_ino) ==
                        (opened.st_dev, opened.st_ino), "session entry changed")
                require(mount_id(child) == expected_mount,
                        "nested mount in owned session")
                children = (inspect(child, expected_mount, owner_uid,
                                    budget, session_objects, depth + 1)
                            if is_directory else None)
            finally:
                os.close(child)
            entries.append(Entry(name, before.st_dev, before.st_ino,
                                 before.st_mode, children))
    return entries


def verify_entry(directory: int, entry: Entry, expected_mount: str) -> int:
    current = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
    require((current.st_dev, current.st_ino, current.st_mode) ==
            (entry.device, entry.inode, entry.mode),
            "session entry replaced during cleanup")
    descriptor = os.open(entry.name,
                         (os.O_DIRECTORY if entry.children is not None else os.O_PATH)
                         | OPEN_FLAGS, dir_fd=directory)
    opened = os.fstat(descriptor)
    if ((opened.st_dev, opened.st_ino, opened.st_mode) !=
            (entry.device, entry.inode, entry.mode)
            or mount_id(descriptor) != expected_mount):
        os.close(descriptor)
        raise CleanupBlocked("session entry or mount changed during cleanup")
    return descriptor


def remove_tree(directory: int, entries: list[Entry], expected_mount: str,
                preserve_markers: bool = False) -> None:
    # Completion records are deleted last, after all scratch data. An interrupted
    # removal can be safely recognized and resumed by the next invocation.
    ordinary = [entry for entry in entries if not preserve_markers or
                entry.name not in (OWNER_FILE, COMPLETE_FILE)]
    markers = ([entry for name in (COMPLETE_FILE, OWNER_FILE)
                for entry in entries if entry.name == name]
               if preserve_markers else [])
    for entry in ordinary + markers:
        descriptor = verify_entry(directory, entry, expected_mount)
        try:
            if entry.children is not None:
                remove_tree(descriptor, entry.children, expected_mount)
        finally:
            os.close(descriptor)
        # No non-root user can change a root-owned private directory. Still
        # recheck the directory entry before name-based unlink/rmdir.
        current = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
        require((current.st_dev, current.st_ino, current.st_mode) ==
                (entry.device, entry.inode, entry.mode),
                "session entry changed before removal")
        if entry.children is None:
            os.unlink(entry.name, dir_fd=directory)
        else:
            os.rmdir(entry.name, dir_fd=directory)


def cleanup(root_path: str, owner_uid: int, root_mode: int) -> int:
    root_before = os.lstat(root_path)
    require(stat.S_ISDIR(root_before.st_mode) and root_before.st_uid == owner_uid
            and stat.S_IMODE(root_before.st_mode) == root_mode,
            "temporary root ownership or mode is unsafe")
    root = os.open(root_path, os.O_DIRECTORY | OPEN_FLAGS)
    removed = 0
    try:
        root_stat = os.fstat(root)
        require((root_stat.st_dev, root_stat.st_ino) ==
                (root_before.st_dev, root_before.st_ino),
                "temporary root was substituted")
        expected_mount = mount_id(root)
        budget = Budget()
        with os.scandir(root) as iterator:
            for directory_entry in iterator:
                budget.root_entries += 1
                require(budget.root_entries <= MAX_ROOT_ENTRIES,
                        "too many temporary root entries")
                name = directory_entry.name
                if SESSION_NAME.fullmatch(name) is None:
                    continue
                candidate_stat = os.stat(name, dir_fd=root, follow_symlinks=False)
                if not (stat.S_ISDIR(candidate_stat.st_mode) and
                        candidate_stat.st_uid == owner_uid and
                        stat.S_IMODE(candidate_stat.st_mode) == 0o700):
                    continue  # Unproved or foreign data must survive.
                candidate = os.open(name, os.O_DIRECTORY | OPEN_FLAGS, dir_fd=root)
                try:
                    opened = os.fstat(candidate)
                    require((opened.st_dev, opened.st_ino) ==
                            (candidate_stat.st_dev, candidate_stat.st_ino),
                            "session directory changed")
                    require(mount_id(candidate) == expected_mount,
                            "session is a separate mount")
                    if not owned_complete(candidate, owner_uid, expected_mount):
                        continue  # Incomplete/quarantined/live benchmark.
                    budget.sessions += 1
                    require(budget.sessions <= MAX_SESSIONS,
                            "too many completed sessions")
                    entries = inspect(candidate, expected_mount, owner_uid,
                                      budget, [0], 0)
                    remove_tree(candidate, entries, expected_mount, preserve_markers=True)
                finally:
                    os.close(candidate)
                check = os.stat(name, dir_fd=root, follow_symlinks=False)
                require((check.st_dev, check.st_ino) ==
                        (candidate_stat.st_dev, candidate_stat.st_ino),
                        "session directory substituted before removal")
                os.rmdir(name, dir_fd=root)
                removed += 1
        root_after = os.lstat(root_path)
        require((root_after.st_dev, root_after.st_ino) ==
                (root_stat.st_dev, root_stat.st_ino),
                "temporary root changed during cleanup")
        return removed
    finally:
        os.close(root)


def main() -> int:
    if len(sys.argv) != 4:
        print("BLOCKED: invalid private temporary cleanup invocation", file=sys.stderr)
        return 2
    try:
        owner_uid = int(sys.argv[2])
        root_mode = int(sys.argv[3], 8)
        removed = cleanup(sys.argv[1], owner_uid, root_mode)
    except (OSError, ValueError, CleanupBlocked) as error:
        print(f"BLOCKED: verified-owned temporary cleanup: {error}", file=sys.stderr)
        return 2
    print(f"SWAPZ_TMP_CLEANUP=completed-owned-only removed:{removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
