#!/usr/bin/env python3
"""Remove only completed, positively owned swapz benchmark scratch sessions.

Private qualification helper. Directory descriptors pin traversal; no path below the
validated temporary root is followed through a symlink or another mount.
"""

import errno
import os
import re
import stat
import sys
from dataclasses import dataclass


SESSION_NAME = re.compile(r"swapz-benchmark\.[A-Za-z0-9]{8}\Z")
OWNER_RECORD = re.compile(rb"pid=([1-9][0-9]*)\nsource_sha=([0-9a-f]{40})\n\Z")
OWNER_FILE = ".swapz-benchmark-owner"
COMPLETE_FILE = ".swapz-benchmark-complete"
EVIDENCE_FILE = "session.log"
EVIDENCE_WINDOW = 4096
MAX_ROOT_ENTRIES = 100_000
MAX_SESSIONS = 256
MAX_TOTAL_OBJECTS = 65_536
MAX_SESSION_OBJECTS = 8_192
MAX_DEPTH = 8
MAX_TOTAL_BYTES = 64 * 1024**3
MAX_PROCESSES = 131_072
MAX_PROCESS_REFERENCES = 1_048_576
OPEN_FLAGS = os.O_CLOEXEC | os.O_NOFOLLOW


class CleanupBlocked(Exception):
    """A cleanup safety invariant was not proved."""

    def __init__(self, diagnostic: str, category: str = "safety-invariant"):
        super().__init__(diagnostic)
        self.category = category


def directory_identity(file_stat) -> tuple[int, int, int, int]:
    """Return metadata that must remain stable for a pinned directory."""
    return (file_stat.st_dev, file_stat.st_ino, file_stat.st_mode, file_stat.st_uid)


def regular_file_identity(file_stat) -> tuple[int, int, int, int, int, int, int, int]:
    """Return bounded-file metadata that must remain stable through cleanup."""
    return (file_stat.st_dev, file_stat.st_ino, file_stat.st_mode, file_stat.st_uid,
            file_stat.st_nlink, file_stat.st_size, file_stat.st_ctime_ns,
            file_stat.st_mtime_ns)


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
    owner_uid: int
    link_count: int
    size: int
    ctime_ns: int
    mtime_ns: int
    children: list["Entry"] | None


@dataclass
class CleanupState:
    phase: str = "invocation"
    removed: int = 0
    retained: int = 0
    reclaimed_logical_bytes: int = 0
    retained_unproved: int = 0
    retained_identity: int = 0
    retained_active: int = 0
    partial: bool = False


def require(condition: bool, diagnostic: str, category: str = "safety-invariant") -> None:
    if not condition:
        raise CleanupBlocked(diagnostic, category)


def entry_identity_matches(file_stat, entry: Entry) -> bool:
    if directory_identity(file_stat) != (
            entry.device, entry.inode, entry.mode, entry.owner_uid):
        return False
    if entry.children is not None:
        return True
    return (file_stat.st_nlink, file_stat.st_size, file_stat.st_ctime_ns,
            file_stat.st_mtime_ns) == (
                entry.link_count, entry.size, entry.ctime_ns, entry.mtime_ns)


def close_preserving_first_error(descriptor: int) -> None:
    # Closing an already-pinned fd may fail, but it must not hide an earlier
    # ownership refusal or failed unlink/rmdir (the actionable first error).
    original_error = sys.exc_info()[1]
    try:
        os.close(descriptor)
    except OSError:
        if original_error is None:
            raise


def mount_id(descriptor: int) -> str:
    # Detect bind mounts too: st_dev alone is insufficient on a shared device.
    with open(f"/proc/self/fdinfo/{descriptor}", encoding="ascii") as info:
        matches = [line.split()[1] for line in info if line.startswith("mnt_id:")]
    require(len(matches) == 1 and matches[0].isdigit(), "mount identity unavailable", "mount-identity")
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
        if (regular_file_identity(opened) != regular_file_identity(file_stat)
                or mount_id(descriptor) != expected_mount):
            return None
        contents = os.read(descriptor, 129)
        after = os.fstat(descriptor)
        if regular_file_identity(after) != regular_file_identity(opened):
            return None
        return contents if len(contents) == opened.st_size else None
    finally:
        close_preserving_first_error(descriptor)


def completed_evidence(directory: int, owner_uid: int, expected_mount: str,
                       source_sha: bytes) -> bool:
    """Require bounded producer PASS evidence as well as matching PID markers.

    This is private same-UID provenance, not cryptographic attestation against a
    privileged actor that can forge the producer's files.
    """
    try:
        before = os.stat(EVIDENCE_FILE, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not (stat.S_ISREG(before.st_mode) and before.st_uid == owner_uid
            and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1):
        return False
    descriptor = os.open(EVIDENCE_FILE, os.O_RDONLY | OPEN_FLAGS | os.O_NONBLOCK,
                         dir_fd=directory)
    try:
        opened = os.fstat(descriptor)
        if (regular_file_identity(opened) != regular_file_identity(before)
                or mount_id(descriptor) != expected_mount):
            return False
        # Read only the beginning and end; an unbounded benchmark log must
        # never create an unbounded cleanup I/O request or memory allocation.
        beginning = os.pread(descriptor, EVIDENCE_WINDOW, 0)
        ending = os.pread(descriptor, EVIDENCE_WINDOW,
                          max(0, opened.st_size - EVIDENCE_WINDOW))
        after = os.fstat(descriptor)
        if regular_file_identity(after) != regular_file_identity(opened):
            return False
        directory_path = os.readlink(os.fsencode(f"/proc/self/fd/{directory}"))
        expected_evidence = (b"EVIDENCE=" + os.path.join(
            directory_path, os.fsencode(EVIDENCE_FILE)) + b"\n")
        return (b"\nSOURCE_HEAD=" + source_sha + b" " in b"\n" + beginning
                and b"\nPASS: isolated pair and ordinary teardown\n" in b"\n" + ending
                and ending.endswith(expected_evidence))
    finally:
        close_preserving_first_error(descriptor)


def owned_complete(directory: int, owner_uid: int, expected_mount: str) -> bool:
    owner = read_marker(directory, OWNER_FILE, owner_uid, expected_mount)
    complete = read_marker(directory, COMPLETE_FILE, owner_uid, expected_mount)
    if owner is None or owner != complete:
        return False
    match = OWNER_RECORD.fullmatch(owner)
    if match is None or not completed_evidence(directory, owner_uid, expected_mount, match.group(2)):
        return False
    process_id = int(match.group(1))
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return True
    except (OverflowError, PermissionError):
        return False  # Unobservable or malformed PID is not deletion proof.
    return False


def inspect(directory: int, expected_mount: str, owner_uid: int,
            budget: Budget, session_objects: list[int], depth: int) -> list[Entry]:
    require(depth <= MAX_DEPTH, "session nesting exceeds cleanup bound", "bound")
    entries = []
    with os.scandir(directory) as iterator:
        for directory_entry in iterator:
            session_objects[0] += 1
            budget.objects += 1
            require(session_objects[0] <= MAX_SESSION_OBJECTS
                    and budget.objects <= MAX_TOTAL_OBJECTS,
                    "session entry count exceeds cleanup bound", "bound")
            name = directory_entry.name
            before = os.stat(name, dir_fd=directory, follow_symlinks=False)
            require(before.st_uid == owner_uid, "foreign-owned session entry", "foreign-ownership")
            is_directory = stat.S_ISDIR(before.st_mode)
            require(is_directory or stat.S_ISREG(before.st_mode),
                    "symlink or special session entry", "unsafe-type")
            require(stat.S_IMODE(before.st_mode) & 0o077 == 0,
                    "session entry permissions are not private", "privacy")
            if not is_directory:
                require(before.st_nlink == 1, "hard-linked session file", "hardlink")
                budget.bytes += before.st_size
                require(budget.bytes <= MAX_TOTAL_BYTES,
                        "session bytes exceed cleanup bound", "bound")
            flags = os.O_DIRECTORY if is_directory else os.O_PATH
            child = os.open(name, flags | OPEN_FLAGS, dir_fd=directory)
            try:
                opened = os.fstat(child)
                unchanged = (directory_identity(opened) == directory_identity(before)
                             if is_directory else
                             regular_file_identity(opened) == regular_file_identity(before))
                require(unchanged, "session entry changed", "substitution")
                require(mount_id(child) == expected_mount,
                        "nested mount in owned session", "mount-identity")
                children = (inspect(child, expected_mount, owner_uid,
                                    budget, session_objects, depth + 1)
                            if is_directory else None)
            finally:
                close_preserving_first_error(child)
            entries.append(Entry(name, before.st_dev, before.st_ino,
                                 before.st_mode, before.st_uid, before.st_nlink,
                                 before.st_size, before.st_ctime_ns,
                                 before.st_mtime_ns, children))
    return entries


def session_object_identities(session_stat, entries: list[Entry]) -> set[tuple[int, int]]:
    """Return the inspected session objects that an active process could retain."""
    identities = {(session_stat.st_dev, session_stat.st_ino)}
    pending = list(entries)
    while pending:
        entry = pending.pop()
        identities.add((entry.device, entry.inode))
        if entry.children is not None:
            pending.extend(entry.children)
    return identities


def session_referenced_by_same_owner_process(owner_uid: int, session_stat,
                                             entries: list[Entry]) -> bool:
    """Return whether a same-owner process still references inspected session state."""
    identities = session_object_identities(session_stat, entries)
    mapped_identities = {(os.major(device), os.minor(device), inode)
                         for device, inode in identities}
    process_count = 0
    reference_count = 0

    def scan_reference_view(reference_path: str,
                            scan_mappings: bool) -> tuple[bool, int]:
        nonlocal reference_count
        for reference_name in ("cwd", "root"):
            reference_count += 1
            require(reference_count <= MAX_PROCESS_REFERENCES,
                    "same-owner process references exceed cleanup bound", "bound")
            try:
                current = os.stat(os.path.join(reference_path, reference_name))
            except FileNotFoundError:
                continue
            if (current.st_dev, current.st_ino) in identities:
                return True, 0
        try:
            with os.scandir(os.path.join(reference_path, "fd")) as descriptors:
                for descriptor in descriptors:
                    reference_count += 1
                    require(reference_count <= MAX_PROCESS_REFERENCES,
                            "same-owner process references exceed cleanup bound", "bound")
                    try:
                        current = descriptor.stat(follow_symlinks=True)
                    except FileNotFoundError:
                        continue
                    if (current.st_dev, current.st_ino) in identities:
                        return True, 0
        except FileNotFoundError:
            pass

        mapping_rows = 0
        if scan_mappings:
            try:
                with open(os.path.join(reference_path, "maps"), "rb") as mappings:
                    for mapping in mappings:
                        mapping_rows += 1
                        reference_count += 1
                        require(reference_count <= MAX_PROCESS_REFERENCES,
                                "same-owner process references exceed cleanup bound", "bound")
                        fields = mapping.split(None, 5)
                        require(len(fields) >= 5,
                                "same-owner process mapping is malformed", "process-visibility")
                        device_numbers = fields[3].split(b":", 1)
                        require(len(device_numbers) == 2,
                                "same-owner process mapping device is malformed",
                                "process-visibility")
                        try:
                            mapping_identity = (int(device_numbers[0], 16),
                                                int(device_numbers[1], 16), int(fields[4]))
                        except ValueError as error:
                            raise CleanupBlocked(
                                "same-owner process mapping identity is malformed",
                                "process-visibility") from error
                        if mapping_identity in mapped_identities:
                            return True, mapping_rows
            except FileNotFoundError:
                pass
        return False, mapping_rows

    # The cleanup process intentionally owns root/session descriptors, so do
    # not scan its fd table. Its inherited cwd/root are not cleanup-owned and
    # can keep an otherwise completed session live after parent-name removal.
    for current in (os.stat("."), os.stat("/")):
        reference_count += 1
        require(reference_count <= MAX_PROCESS_REFERENCES,
                "same-owner process references exceed cleanup bound", "bound")
        if (current.st_dev, current.st_ino) in identities:
            return True
    with os.scandir("/proc") as iterator:
        for process in iterator:
            if not process.name.isdecimal():
                continue
            try:
                process_stat = process.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue  # Process exited before ownership could be checked.
            if process_stat.st_uid != owner_uid or int(process.name) == os.getpid():
                continue
            process_count += 1
            require(process_count <= MAX_PROCESSES,
                    "same-owner process inventory exceeds cleanup bound", "bound")
            process_path = os.path.join("/proc", process.name)
            referenced, mapping_rows = scan_reference_view(process_path, True)
            if referenced:
                return True

            # Linux can leave the thread-group leader visible as a zombie while
            # live workers retain per-task cwd/root/fd state. In that state the
            # leader's procfs fd and maps views can be empty, so scan every
            # non-leader task before treating the process as inactive.
            mapping_inventory_visible = mapping_rows > 0
            try:
                with os.scandir(os.path.join(process_path, "task")) as tasks:
                    for task in tasks:
                        if not task.name.isdecimal() or task.name == process.name:
                            continue
                        reference_count += 1
                        require(reference_count <= MAX_PROCESS_REFERENCES,
                                "same-owner process references exceed cleanup bound", "bound")
                        try:
                            task_stat = task.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        require(task_stat.st_uid == owner_uid,
                                "same-owner process task ownership changed",
                                "process-visibility")
                        task_path = os.path.join(process_path, "task", task.name)
                        referenced, task_mapping_rows = scan_reference_view(
                            task_path, not mapping_inventory_visible)
                        if referenced:
                            return True
                        if task_mapping_rows > 0:
                            mapping_inventory_visible = True
            except FileNotFoundError:
                continue  # Process exited during task inventory.
    return False


def verify_entry(directory: int, entry: Entry, expected_mount: str) -> int:
    current = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
    require(entry_identity_matches(current, entry),
            "session entry replaced during cleanup", "substitution")
    descriptor = os.open(entry.name,
                         (os.O_DIRECTORY if entry.children is not None else os.O_PATH)
                         | OPEN_FLAGS, dir_fd=directory)
    try:
        opened = os.fstat(descriptor)
        require(entry_identity_matches(opened, entry)
                and mount_id(descriptor) == expected_mount,
                "session entry or mount changed during cleanup", "substitution")
    except BaseException:
        close_preserving_first_error(descriptor)
        raise
    return descriptor


def remove_tree(directory: int, entries: list[Entry], expected_mount: str,
                preserve_markers: bool = False) -> None:
    # Keep the bounded teardown log and completion records until scratch data
    # is gone. A failure after proof removal leaves a non-resumable partial
    # session; never claim proof survives every interruption.
    ordinary = [entry for entry in entries if not preserve_markers or
                entry.name not in (EVIDENCE_FILE, OWNER_FILE, COMPLETE_FILE)]
    markers = ([entry for name in (EVIDENCE_FILE, COMPLETE_FILE, OWNER_FILE)
                for entry in entries if entry.name == name]
               if preserve_markers else [])
    for entry in ordinary + markers:
        descriptor = verify_entry(directory, entry, expected_mount)
        try:
            if entry.children is not None:
                remove_tree(descriptor, entry.children, expected_mount)
        finally:
            close_preserving_first_error(descriptor)
        # No non-root user can change a root-owned private directory. Still
        # recheck the directory entry before name-based unlink/rmdir.
        current = os.stat(entry.name, dir_fd=directory, follow_symlinks=False)
        require(entry_identity_matches(current, entry),
                "session entry changed before removal", "substitution")
        if entry.children is None:
            os.unlink(entry.name, dir_fd=directory)
        else:
            os.rmdir(entry.name, dir_fd=directory)


def cleanup(root_path: str, owner_uid: int, root_mode: int,
            state: CleanupState | None = None) -> int:
    state = state if state is not None else CleanupState()
    state.phase = "root-validation"
    root_before = os.lstat(root_path)
    require(stat.S_ISDIR(root_before.st_mode) and root_before.st_uid == owner_uid
            and stat.S_IMODE(root_before.st_mode) == root_mode,
            "temporary root ownership or mode is unsafe", "root-identity")
    root = os.open(root_path, os.O_DIRECTORY | OPEN_FLAGS)
    try:
        root_stat = os.fstat(root)
        require(directory_identity(root_stat) == directory_identity(root_before),
                "temporary root was substituted or changed", "substitution")
        expected_mount = mount_id(root)
        budget = Budget()
        state.phase = "root-inventory"
        with os.scandir(root) as iterator:
            for directory_entry in iterator:
                budget.root_entries += 1
                require(budget.root_entries <= MAX_ROOT_ENTRIES,
                        "too many temporary root entries", "bound")
                name = directory_entry.name
                if SESSION_NAME.fullmatch(name) is None:
                    continue
                state.phase = "session-identity"
                candidate_stat = os.stat(name, dir_fd=root, follow_symlinks=False)
                if not (stat.S_ISDIR(candidate_stat.st_mode) and
                        candidate_stat.st_uid == owner_uid and
                        stat.S_IMODE(candidate_stat.st_mode) == 0o700):
                    state.retained += 1
                    state.retained_identity += 1
                    state.phase = "root-inventory"
                    continue  # Unproved or foreign data must survive.
                candidate = os.open(name, os.O_DIRECTORY | OPEN_FLAGS, dir_fd=root)
                try:
                    opened = os.fstat(candidate)
                    require(directory_identity(opened) == directory_identity(candidate_stat),
                            "session directory changed", "substitution")
                    require(mount_id(candidate) == expected_mount,
                            "session is a separate mount", "mount-identity")
                    state.phase = "session-provenance"
                    if not owned_complete(candidate, owner_uid, expected_mount):
                        state.retained += 1
                        state.retained_unproved += 1
                        continue  # Incomplete/quarantined/live benchmark.
                    budget.sessions += 1
                    require(budget.sessions <= MAX_SESSIONS,
                            "too many completed sessions", "bound")
                    state.phase = "session-inspection"
                    previous_inspected_bytes = budget.bytes
                    entries = inspect(candidate, expected_mount, owner_uid,
                                      budget, [0], 0)
                    # Inspection may outlive the original path binding. Refuse
                    # to delete through a renamed directory descriptor.
                    state.phase = "session-removal"
                    require(directory_identity(os.lstat(root_path)) == directory_identity(root_stat),
                            "temporary root changed before session removal", "substitution")
                    current = os.stat(name, dir_fd=root, follow_symlinks=False)
                    require(directory_identity(current) == directory_identity(candidate_stat),
                            "session directory substituted before removal", "substitution")
                    rebound = os.open(name, os.O_DIRECTORY | OPEN_FLAGS, dir_fd=root)
                    try:
                        require(directory_identity(os.fstat(rebound)) ==
                                directory_identity(candidate_stat) and
                                mount_id(rebound) == expected_mount,
                                "session directory or mount changed before removal", "substitution")
                    finally:
                        close_preserving_first_error(rebound)
                    state.phase = "session-activity"
                    if session_referenced_by_same_owner_process(
                            owner_uid, candidate_stat, entries):
                        state.retained += 1
                        state.retained_active += 1
                        state.phase = "root-inventory"
                        continue
                    state.phase = "session-removal"
                    state.partial = True  # An unlink may succeed before a later error.
                    remove_tree(candidate, entries, expected_mount, preserve_markers=True)
                finally:
                    close_preserving_first_error(candidate)
                state.phase = "session-finalization"
                check = os.stat(name, dir_fd=root, follow_symlinks=False)
                require(directory_identity(check) == directory_identity(candidate_stat),
                        "session directory substituted or changed before removal",
                        "substitution")
                os.rmdir(name, dir_fd=root)
                state.removed += 1
                # Logical bytes unlinked, not a claim of immediate tmpfs RAM release.
                state.reclaimed_logical_bytes += budget.bytes - previous_inspected_bytes
                state.partial = False
                state.phase = "root-inventory"
        state.phase = "root-recheck"
        root_after = os.lstat(root_path)
        require(directory_identity(root_after) == directory_identity(root_stat),
                "temporary root changed during cleanup", "substitution")
        return state.removed
    finally:
        close_preserving_first_error(root)


def main() -> int:
    state = CleanupState()
    if len(sys.argv) != 4:
        print("BLOCKED: tmp-cleanup phase=invocation category=invalid-arguments "
              "original_errno=none observed_uncertainty=invalid-input exit_code=2 "
              "retained=unexamined removed=0 session_class=swapz-benchmark "
              "ownership_identity=unproved-or-unexamined "
              "safe_next_action=verify-arguments-read-only", file=sys.stderr)
        return 2
    try:
        owner_uid = int(sys.argv[2])
        root_mode = int(sys.argv[3], 8)
        removed = cleanup(sys.argv[1], owner_uid, root_mode, state)
    except (OSError, ValueError, CleanupBlocked, KeyboardInterrupt) as error:
        if isinstance(error, CleanupBlocked):
            category = error.category
        elif isinstance(error, OSError):
            category = "filesystem-error"
        elif isinstance(error, KeyboardInterrupt):
            category = "interrupted"
        else:
            category = "invalid-arguments"
        original_errno = (f"{errno.errorcode.get(error.errno, 'UNKNOWN')}({error.errno})"
                          if isinstance(error, OSError) and error.errno is not None else "none")
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 2
        retained = "partial-or-uncertain" if state.partial else "unexamined-or-unproved"
        observed_uncertainty = (
            "partial-removal" if state.partial else
            "same-owner-process-activity-unproved" if state.phase == "session-activity"
            else "validation-incomplete")
        ownership_identity = ("proven" if state.phase in (
            "session-inspection", "session-activity", "session-removal",
            "session-finalization") else "unproved-or-unexamined")
        safe_next_action = ("verify-arguments-read-only" if category == "invalid-arguments"
                            else "inspect-retained-evidence-read-only")
        print(f"BLOCKED: tmp-cleanup phase={state.phase} category={category} "
              f"original_errno={original_errno} observed_uncertainty={observed_uncertainty} "
              f"exit_code={exit_code} retained={retained} removed={state.removed} "
              f"session_class=swapz-benchmark ownership_identity={ownership_identity} "
              f"safe_next_action={safe_next_action}", file=sys.stderr)
        return exit_code
    print(f"SWAPZ_TMP_CLEANUP=completed-owned-only removed:{removed} retained:{state.retained} "
          f"reclaimed_logical_bytes:{state.reclaimed_logical_bytes} "
          f"retained_unproved:{state.retained_unproved} "
          f"retained_identity:{state.retained_identity} "
          f"retained_active:{state.retained_active}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
