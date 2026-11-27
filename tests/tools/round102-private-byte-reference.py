#!/usr/bin/env python3
"""Offline private materialization, actual-buffer comparison and sidecar assembly.

The directory is caller-owned mode 0700, with independently retained scope
and plan, actual collector export and separately supplied user pages. This
does not collect native data, open devices, authorize or launch workloads.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys

spec = importlib.util.spec_from_file_location(
    "oracle", Path(__file__).with_name("native-observation-byte-oracle.py"))
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
require = oracle.require


def private_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "private_directory")
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_private(directory, name, limit):
    # Only fixed basenames, never paths supplied by untrusted JSON.
    require(re.fullmatch(r"[a-zA-Z0-9._-]+", name) is not None and
            name not in (".", ".."), "private_basename")
    before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    require(stat.S_ISREG(before.st_mode), "regular_file_required")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and
                stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and
                (info.st_dev, info.st_ino) == (before.st_dev, before.st_ino),
                "private_regular_file")
        require(0 <= info.st_size <= limit, "file_bounds")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        require(len(data) == info.st_size <= limit and
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (info.st_size, info.st_mtime_ns, info.st_ctime_ns), "file_changed")
        return data


def private_json(directory, name, limit):
    return json.loads(read_private(directory, name, limit),
                      object_pairs_hook=oracle.legacy.unique_object)


def write_private(directory, name, data):
    # No replacement; failed writes remove only this newly created file.
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            require(stream.write(data) == len(data), "short_private_write")
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.unlink(name, dir_fd=directory)
        raise


def load_plan(directory, source):
    scope = private_json(directory, "scope.json", 4096)
    plan = private_json(directory, "plan.json", oracle.MAX_PLAN_BYTES)
    oracle.legacy.check_scope(scope)
    require(oracle.hex_value(source, 20) and source != "0" * 40 and
            source != oracle.legacy.MAPPING_SOURCE and scope["source"] == source,
            "expected_build_source")
    actions = oracle.validate_plan(plan, scope)
    return scope, plan, actions


def reference(plan, action):
    return oracle.reference_page(plan["seed"], plan["nonce"],
                                 action["logical"], action["version"])


def user_bytes(directory, index):
    observed = read_private(directory, f"user-{index}.page", oracle.PAGE_BYTES)
    require(len(observed) == oracle.PAGE_BYTES, "full_page_required")
    return observed


def execute(mode, directory, source, index=None):
    scope, plan, actions = load_plan(directory, source)
    if mode in ("materialize", "compare"):
        require(oracle.integer(index, 0, len(actions) - 1), "action_index")
        action = actions[index]
        require(action["kind"] in (oracle.WRITES if mode == "materialize" else
                                   {"typed_read"}), "action_kind")
        expected = reference(plan, action)
        if mode == "materialize":
            write_private(directory, f"reference-{index}.page", expected)
        else:
            require(user_bytes(directory, index) == expected, "independent_byte_mismatch")
        return dict(status="REFERENCE_MATERIALIZED" if mode == "materialize" else
                    "USER_BYTES_MATCH", auth=0)
    require(mode == "assemble" and index is None, "arguments")
    wire = read_private(directory, "wire.bin", oracle.legacy.MAX_BYTES)
    records = private_json(directory, "collector.json", oracle.MAX_SIDECAR_BYTES)
    require(type(records) is list and len(records) == len(actions), "sidecar_count")
    witnesses = []
    for ordinal, (record, action) in enumerate(zip(records, actions)):
        require(type(record) is dict and set(record) == oracle.WITNESS_FIELDS,
                "witness_shape")
        # The collector export supplies real copied bytes, never plan bytes.
        # Independently acquired user bytes must agree with its separate copy.
        witness = record.copy()
        if action["kind"] == "typed_read":
            observed = user_bytes(directory, ordinal)
            require(oracle.hex_value(record["user_page"], oracle.PAGE_BYTES) and
                    bytes.fromhex(record["user_page"]) == observed,
                    "collector_user_mismatch")
            require(observed == reference(plan, action), "independent_byte_mismatch")
            witness["user_page"] = observed.hex()
        witnesses.append(witness)
    sidecar = dict(schema=oracle.SCHEMA, scope_sha256=oracle.legacy.scope_digest(scope).hex(),
                   wire_sha256=oracle.digest(wire), operations=witnesses)
    result = oracle.validate(wire, scope, source, plan, sidecar)
    write_private(directory, "sidecar.json", oracle.canonical(sidecar))
    # A claimed error remains blocked; retain consistent private evidence.
    return dict(status=result["status"], operations=result["operations"], auth=0)


def main():
    fd = None
    try:
        require(len(sys.argv) in (4, 5), "arguments")
        mode, source, directory = sys.argv[1:4]
        index = None
        if len(sys.argv) == 5:
            require(re.fullmatch(r"0|[1-9][0-9]?", sys.argv[4]) is not None, "action_index")
            index = int(sys.argv[4])
        fd = private_directory(directory)
        result = execute(mode, fd, source, index)
    except oracle.legacy.Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), auth=0)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError, struct.error):
        result = dict(status="BLOCKED", reason="invalid_private_input", auth=0)
    finally:
        if fd is not None:
            os.close(fd)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("REFERENCE_MATERIALIZED", "USER_BYTES_MATCH",
                                      "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY") else 2


if __name__ == "__main__":
    raise SystemExit(main())
