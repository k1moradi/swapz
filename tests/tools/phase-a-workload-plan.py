#!/usr/bin/env python3
"""Private, rootless ordinary-v2 pre-run commitment; not an admission tool.

CLI: phase-a-workload-plan.py PRIVATE_DIRECTORY. Read request.json (0600),
retain workload-plan.json (0600, exclusive creation) before preparing maps,
then verify and close both mappings. The artifact contains only plan and scope;
no witness, capture, signature or actual authority. Directory owner must have
exclusive control, including no concurrent mutation or renaming. No page bytes,
identities, digest or paths are emitted to stdout. IDs 1..N name anonymous
pages and N+1..2N name matched file-backed tmpfs pages, not native swap slots.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from contextlib import contextmanager

PAGE_BYTES = 4096
MAX_PAGES = 16
MAX_OPERATIONS = 64
MAX_TOUCHES = 16
MAX_REQUEST_BYTES = 4096
MAX_ARTIFACT_BYTES = 256 * 1024
U64 = (1 << 64) - 1
REQUEST_NAME = "request.json"
ARTIFACT_NAME = "workload-plan.json"
SCOPE_KEYS = {"source", "run_nonce", "area_epoch", "swap_type", "target"}
REQUEST_KEYS = {"schema", "version", "scope", "page_count", "hot_page_count",
                "touch_count", "seed", "max_pages", "max_operations"}
GATES = dict(auth=0, phase_a="BLOCKED", native_qualification="BLOCKED",
             observation="UNKNOWN", compressed_handoff=False, forced_raw=False,
             import_enabled=False, physical="NO_GO", actual_route="ORDINARY",
             authenticated=False)

HELPER_PATH = Path(__file__).resolve().parents[1] / "runtime/benchmark/resource-pressure.py"
SPEC = importlib.util.spec_from_file_location("resource_pressure", HELPER_PATH)
pressure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pressure)


class PlanError(ValueError):
    """Fixed, redacted reason codes only."""


def require(condition, reason):
    if not condition:
        raise PlanError(reason)


def integer(value, low, high):
    return type(value) is int and low <= value <= high


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def reject_constant(_):
    raise PlanError("nonfinite_json")


def validate_request(request):
    require(type(request) is dict and request.keys() == REQUEST_KEYS, "request_shape")
    require(request["schema"] == "swapz-workload-plan-request" and
            integer(request["version"], 2, 2), "request_version")
    scope = request["scope"]
    require(type(scope) is dict and scope.keys() == SCOPE_KEYS, "scope_shape")
    for key, size in (("source", 40), ("run_nonce", 32)):
        value = scope[key]
        require(type(value) is str and len(value) == size and
                re.fullmatch(r"[0-9a-f]+", value) is not None and
                value != "0" * size, "scope_digest")
    require(integer(scope["area_epoch"], 1, U64) and integer(scope["target"], 1, U64) and
            integer(scope["swap_type"], 0, 255), "scope_identity")
    count = request["page_count"]
    require(integer(count, 2, MAX_PAGES // 2) and
            integer(request["hot_page_count"], 1, count - 1) and
            integer(request["touch_count"], 0, MAX_TOUCHES) and
            integer(request["seed"], 0, U64), "workload_bounds")
    require(integer(request["max_pages"], 2 * count, MAX_PAGES) and
            integer(request["max_operations"], 4 * count, MAX_OPERATIONS), "plan_bounds")


def expected_page(seed, index, hot, touches):
    # Independently implement the frozen pattern specification, not _cold_page,
    # a capture, a mapping read or the helper's internal touch counter.
    material = seed.to_bytes(8, "little") + index.to_bytes(8, "little")
    block = bytes([0, 1]) + hashlib.shake_256(material).digest(510)
    page = block * 8
    return bytes([touches & 1]) + page[1:] if hot else page


def build_commitment(request):
    """Generate all expected bytes and digest before any preparation/touch."""
    validate_request(request)
    count = request["page_count"]
    expected = [expected_page(request["seed"], index,
                              index < request["hot_page_count"], request["touch_count"]).hex()
                for index in range(count)]
    plan = dict(schema="swapz-ordinary-plan", version=2, **request["scope"],
                max_pages=request["max_pages"], max_operations=request["max_operations"],
                pages=[dict(logical=logical, expected_page=expected[(logical - 1) % count])
                       for logical in range(1, 2 * count + 1)])
    scope = dict(request["scope"], workload_sha256=hashlib.sha256(canonical(plan)).hexdigest())
    return dict(plan=plan, scope=scope)


def verify_preparation(request, commitment, tmpfs_fd):
    """Exclusive caller-owned fd; helper owns duplicate and both mappings.

    Only called after retention. No cold access after population until final
    verification, which is not a residency/temperature observation. The frozen
    helper exposes no public byte accessor; bounded slices of its two private
    maps are compared in-context to the retained plan, no views escape.
    """
    count, hot = request["page_count"], request["hot_page_count"]
    with pressure.prepare_matched_cold_workload(page_count=count, hot_page_count=hot,
                                               seed=request["seed"], tmpfs_fd=tmpfs_fd) as work:
        require(work.backing_kind == "file-backed-tmpfs" and
                work.logical_bytes_per_mapping == count * PAGE_BYTES and
                work.hot_pages == range(hot) and work.cold_pages == range(hot, count),
                "cohort_mismatch")
        for _ in range(request["touch_count"]):
            work.touch_hot()
        work.verify()
        for cohort, mapping in enumerate((work._anonymous, work._shmem)):
            for index in range(count):
                offset = index * PAGE_BYTES
                expected = bytes.fromhex(commitment["plan"]["pages"][cohort * count + index]["expected_page"])
                require(mapping[offset:offset + PAGE_BYTES] == expected, "committed_page_mismatch")
    require(work._anonymous.closed and work._shmem.closed and
            os.fstat(tmpfs_fd).st_size == 0, "mapping_cleanup")


def private_regular(info):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
            stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def private_dir(info):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
            stat.S_IMODE(info.st_mode) == 0o700)


def identity(info):
    return info.st_dev, info.st_ino


@contextmanager
def open_private_directory(path):
    # Walk every component relative to an already opened directory. No
    # symlink or traversal, including intermediate components; no mkdir.
    require(type(path) is str and path and "\x00" not in path, "directory_path")
    parts = path.split("/")
    absolute = path.startswith("/")
    if absolute:
        parts = parts[1:]
    require(parts and all(part not in ("", ".", "..") for part in parts), "directory_path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/" if absolute else ".", flags)
    first_error = None
    try:
        for part in parts:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            previous, descriptor = descriptor, next_descriptor
            os.close(previous)
        require(private_dir(os.fstat(descriptor)), "private_directory_required")
        yield descriptor
    except BaseException as error:
        first_error = error
        raise
    finally:
        try:
            os.close(descriptor)
        except OSError:
            if first_error is None:
                raise
            first_error.add_note("directory_close_failed")


def read_request(directory):
    fd = os.open(REQUEST_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(private_regular(before), "private_request_required")
        require(2 <= before.st_size <= MAX_REQUEST_BYTES, "request_size")
        raw = stream.read(MAX_REQUEST_BYTES + 1)
        after = os.fstat(stream.fileno())
        require(private_regular(after) and len(raw) == before.st_size and
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "request_changed")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)


def retain_and_prepare(directory, request):
    """Create exactly one private artifact; remove only our inode on failure."""
    commitment = build_commitment(request)
    encoded = canonical(commitment) + b"\n"
    require(len(encoded) <= MAX_ARTIFACT_BYTES, "artifact_size")
    require(private_dir(os.fstat(directory)), "private_directory_required")
    fd = os.open(ARTIFACT_NAME, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory)
    created = None
    try:
        created = identity(os.fstat(fd))
        os.fchmod(fd, 0o600)
        require(private_regular(os.fstat(fd)), "private_artifact_required")
        offset = 0
        while offset < len(encoded):
            written = os.write(fd, memoryview(encoded)[offset:])
            require(written > 0, "artifact_write")
            offset += written
        os.fsync(fd)
        os.fsync(directory)
        # Retention precedes even opening the tmpfs backing file.
        with tempfile.TemporaryFile(dir="/dev/shm") as backing:
            verify_preparation(request, commitment, backing.fileno())
        info = os.fstat(fd)
        named = os.stat(ARTIFACT_NAME, dir_fd=directory, follow_symlinks=False)
        require(private_dir(os.fstat(directory)) and private_regular(info) and
                private_regular(named) and identity(named) == created and
                os.pread(fd, len(encoded) + 1, 0) == encoded, "artifact_changed")
        closed, fd = fd, None
        os.close(closed)
    except BaseException as first:
        # Preserve the first error, never remove an unrelated replacement.
        try:
            if created is None:
                first.add_note("artifact_cleanup_failed")
            else:
                named = os.stat(ARTIFACT_NAME, dir_fd=directory, follow_symlinks=False)
                require(identity(named) == created, "artifact_replaced")
                os.unlink(ARTIFACT_NAME, dir_fd=directory)
                os.fsync(directory)
        except (OSError, PlanError):
            first.add_note("artifact_cleanup_failed")
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    first.add_note("artifact_close_failed")
        raise
    count, hot = request["page_count"], request["hot_page_count"]
    return dict(status="ROOTLESS_PREPARATION_ONLY", pages=2 * count,
                cohorts=[dict(backing="anonymous", pages=count, hot=hot, cold=count - hot),
                         dict(backing="file-backed-tmpfs", pages=count, hot=hot, cold=count - hot)],
                hot_touches=request["touch_count"], byte_exact=True,
                precommit_retained=True, mapping_cleanup=True, **GATES)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        require(os.geteuid() != 0, "unprivileged_required")
        require(len(argv) == 1, "arguments")
        with open_private_directory(argv[0]) as directory:
            request = read_request(directory)
            result = retain_and_prepare(directory, request)
    except (PlanError, pressure.ColdWorkloadError, OSError, ValueError, TypeError,
            KeyError, OverflowError, BufferError, MemoryError, RecursionError) as error:
        if isinstance(error, PlanError):
            reason = str(error)
        elif isinstance(error, pressure.ColdWorkloadError):
            reason = "matched_preparation_failed"
        else:
            reason = "private_io_or_input_failed"
        # Notes are emitted only by the owned cleanup paths. Never echo them.
        cleanup_debt = bool(getattr(error, "__notes__", ())) or (
            isinstance(error, pressure.ColdWorkloadError) and
            str(error).startswith("matched workload cleanup failed"))
        result = dict(status="BLOCKED", reason=reason, cleanup_debt=cleanup_debt, **GATES)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "ROOTLESS_PREPARATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
