#!/usr/bin/env python3
"""Private caller-owned delivery and actual workload-buffer observation.

No device opens, admission, activation, or kernel endpoint. A trusted future
transport supplies the immutable bundle, and the workload completion owner
supplies its own stable actual buffer and independently retained metadata.
Neither this code nor an offline match establishes native provenance.
"""
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import struct
import sys

spec = importlib.util.spec_from_file_location(
    "private", Path(__file__).with_name("round105-private-evidence.py"))
private = importlib.util.module_from_spec(spec)
spec.loader.exec_module(private)
reference, oracle, legacy = private.reference, private.oracle, private.legacy
require = oracle.require
USER_HEADER = struct.Struct("<8sII")
USER_MAX = USER_HEADER.size + 4096 + oracle.PAGE_BYTES


def publish(directory, name, data):
    # Caller-owned verified 0700 dirfd; fully write and fsync a new inode
    # before exclusive publication. link never replaces an existing name.
    # Same-UID processes with write access are outside the trust boundary.
    info = os.fstat(directory)
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and
            stat.S_IMODE(info.st_mode) == 0o700, "private_directory")
    require(name == "native-evidence.bin" or
            (name.startswith("user-") and name.endswith(".observation") and
             name[5:-12].isascii() and name[5:-12].isdigit()), "delivery_basename")
    temporary = ".pending-" + secrets.token_hex(16)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            require(stream.write(data) == len(data), "short_private_write")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                follow_symlinks=False)
    finally:
        os.unlink(temporary, dir_fd=directory)


def deliver(directory, source, actual_bundle):
    scope, _, _ = reference.load_plan(directory, source)
    # Copy caller-held stable bytes before validating/publishing; no plan
    # or kernel byte reconstruction, no direct native endpoint here.
    with memoryview(actual_bundle) as view:
        require(view.c_contiguous and 0 < view.nbytes <= private.MAX_BYTES,
                "delivery_bounds")
        data = view.tobytes()
    private.unpack(data, scope)
    publish(directory, "native-evidence.bin", data)


def metadata_valid(metadata, scope):
    return (type(metadata) is dict and set(metadata) == private.USER_FIELDS and
            metadata["run_nonce"] == scope["run_nonce"] and
            metadata["scope_sha256"] == legacy.scope_digest(scope).hex() and
            all(oracle.integer(metadata[key], 1, (1 << 64) - 1)
                for key in ("operation", "original", "upper_sequence")) and
            oracle.integer(metadata["logical"], 1, (1 << 32) - 1) and
            oracle.integer(metadata["version"], 0, (1 << 64) - 1) and
            oracle.integer(metadata["status"], 0, 255))


def capture(directory, source, index, metadata, actual_buffer):
    """Call synchronously at actual workload completion with stable memory.

    The workload owner serializes buffer access until return and supplies its
    observed status and pre-held correlation; no read from kernel bundle or
    expected reference. One complete exclusive file per operation, no split
    metadata/page publication. A missing read buffer never gets invented.
    """
    scope, _, actions = reference.load_plan(directory, source)
    require(oracle.integer(index, 0, len(actions) - 1), "action_index")
    action = actions[index]
    require(metadata_valid(metadata, scope) and metadata["logical"] == action["logical"] and
            metadata["version"] == action["version"], "user_scope_binding")
    read = action["kind"] == "typed_read"
    if read:
        require(actual_buffer is not None, "full_page_required")
        with memoryview(actual_buffer) as view:
            require(view.c_contiguous and view.nbytes == oracle.PAGE_BYTES,
                    "full_page_required")
            page = view.tobytes()
    else:
        require(actual_buffer is None, "unexpected_user_page")
        page = b""
    # Do not compare to plan status here: capture actual observed failure.
    encoded = oracle.canonical(metadata)
    require(len(encoded) <= 4096, "user_metadata_bounds")
    publish(directory, f"user-{index}.observation",
            USER_HEADER.pack(b"SWZUSR1\0", len(encoded), len(page)) + encoded + page)


def read_observation(directory, index, scope, read):
    raw = reference.read_private(directory, f"user-{index}.observation", USER_MAX)
    require(len(raw) >= USER_HEADER.size, "user_frame")
    magic, metadata_size, page_size = USER_HEADER.unpack_from(raw)
    require(magic == b"SWZUSR1\0" and 0 < metadata_size <= 4096 and
            page_size == (oracle.PAGE_BYTES if read else 0) and
            len(raw) == USER_HEADER.size + metadata_size + page_size, "user_frame")
    end = USER_HEADER.size + metadata_size
    metadata = json.loads(raw[USER_HEADER.size:end],
                          object_pairs_hook=legacy.unique_object)
    require(metadata_valid(metadata, scope), "user_scope_binding")
    return {key: metadata[key] for key in private.correlation.USER_FIELDS}, raw[end:]


def assemble(directory, source):
    scope, plan, actions = reference.load_plan(directory, source)
    wire, records = private.unpack(
        reference.read_private(directory, "native-evidence.bin", private.MAX_BYTES), scope)
    # Read each single-inode observation once; no independently raced page.
    observations = [read_observation(directory, index, scope, action["kind"] == "typed_read")
                    for index, action in enumerate(actions)]
    result, sidecar = private.correlation.correlate(
        scope, plan, actions, wire, records, source,
        lambda index: observations[index][0], lambda index: observations[index][1])
    reference.write_private(directory, "sidecar.json", oracle.canonical(sidecar))
    return result


def main():
    directory = None
    try:
        require(len(sys.argv) == 3, "arguments")
        directory = reference.private_directory(sys.argv[2])
        result = assemble(directory, sys.argv[1])
    except legacy.Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), auth=0)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, struct.error):
        result = dict(status="BLOCKED", reason="invalid_private_input", auth=0)
    finally:
        if directory is not None:
            os.close(directory)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
