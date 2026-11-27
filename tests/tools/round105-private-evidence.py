#!/usr/bin/env python3
"""Read only a private sealed native bundle; no device or live capture API."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys

spec = importlib.util.spec_from_file_location(
    "correlation", Path(__file__).with_name("round103-private-byte-correlation.py"))
correlation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(correlation)
reference, oracle, legacy = correlation.reference, correlation.oracle, correlation.legacy
require = oracle.require
HEADER = struct.Struct("<8sIIII32s")
RECORD = struct.Struct("<11Q4I")
FIELDS = ("operation original clone descriptor pin accept_sequence pin_sequence "
          "copy_sequence release_sequence clone_sequence upper_sequence logical kind status page_kind").split()
MAX_BYTES = HEADER.size + legacy.MAX_BYTES + 64 * (RECORD.size + oracle.PAGE_BYTES) + 8
USER_FIELDS = correlation.USER_FIELDS | {"run_nonce", "scope_sha256"}


def unpack(data, scope):
    require(HEADER.size + 8 <= len(data) <= MAX_BYTES, "bundle_size")
    magic, version, wire_size, count, byte_size, digest = HEADER.unpack_from(data)
    require(magic == b"SWZPRV1\0" and version == 1 and
            legacy.HEADER.size + legacy.FOOTER.size <= wire_size <= legacy.MAX_BYTES and
            1 <= count <= 64 and count * RECORD.size <= byte_size <=
            count * (RECORD.size + oracle.PAGE_BYTES) and
            len(data) == HEADER.size + wire_size + byte_size + 8 and
            data[-8:] == b"SWZPEND\0", "bundle_frame")
    require(digest == legacy.scope_digest(scope), "bundle_scope")
    offset = HEADER.size + wire_size
    wire = data[HEADER.size:offset]
    require(legacy.HEADER.unpack_from(wire)[2] == digest, "bundle_wire_scope")
    end = offset + byte_size
    records = []
    for _ in range(count):
        require(offset + RECORD.size <= end, "bundle_record_bounds")
        record = dict(zip(FIELDS, RECORD.unpack_from(data, offset)))
        offset += RECORD.size
        page_kind = record.pop("page_kind")
        kind = record["kind"]
        require(kind in (1, 2, 3, 4, 5, 6) and
                page_kind == (2 if kind == 2 else 0 if kind == 5 else 1), "bundle_page_kind")
        page = None
        if page_kind:
            require(offset + oracle.PAGE_BYTES <= end, "bundle_page_bounds")
            page = data[offset:offset + oracle.PAGE_BYTES].hex()
            offset += oracle.PAGE_BYTES
        record["input_page"] = page if page_kind == 1 else None
        record["final_copy"] = page if page_kind == 2 else None
        records.append(record)
    require(offset == end, "bundle_trailing")
    return wire, records


def assemble(directory, source):
    scope, plan, actions = reference.load_plan(directory, source)
    raw = reference.read_private(directory, "native-evidence.bin", MAX_BYTES)
    wire, records = unpack(raw, scope)
    scope_hash = legacy.scope_digest(scope).hex()

    def read_user(index):
        user = reference.private_json(directory, f"user-{index}.json", 4096)
        require(type(user) is dict and set(user) == USER_FIELDS and
                user["run_nonce"] == scope["run_nonce"] and
                user["scope_sha256"] == scope_hash, "user_scope_binding")
        return {key: user[key] for key in correlation.USER_FIELDS}

    result, sidecar = correlation.correlate(
        scope, plan, actions, wire, records, source, read_user,
        lambda index: reference.user_bytes(directory, index))
    # One exclusive output, only after the full unchanged R099 validation.
    # No partial wire/collector files to confuse retries; the sealed bundle
    # remains the private materialization of both actual observations.
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
