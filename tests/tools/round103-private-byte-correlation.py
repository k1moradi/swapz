#!/usr/bin/env python3
"""R103 private kernel-witness/user-observation join; no runtime authority."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys

spec = importlib.util.spec_from_file_location(
    "reference", Path(__file__).with_name("round102-private-byte-reference.py"))
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
oracle = reference.oracle
legacy = oracle.legacy
require = oracle.require

# Private export only, NOT a change to the R099 sidecar or v2 wire.
KERNEL_FIELDS = (oracle.WITNESS_FIELDS - {"user_page", "user_status"}) | {
    "logical", "kind", "status", "pin_sequence", "release_sequence", "clone_sequence"}
USER_FIELDS = {"operation", "original", "upper_sequence", "logical", "version", "status"}
KINDS = {"typed_write": 1, "typed_read": 2, "fallback": 3,
         "ordinary_write": 4, "discard": 5, "claimed_error": 6}


def assemble(directory, source):
    scope, plan, actions = reference.load_plan(directory, source)
    wire = reference.read_private(directory, "wire.bin", legacy.MAX_BYTES)
    records = reference.private_json(directory, "kernel-collector.json", oracle.MAX_SIDECAR_BYTES)
    result, sidecar = correlate(
        scope, plan, actions, wire, records, source,
        lambda index: reference.private_json(directory, f"user-{index}.json", 4096),
        lambda index: reference.user_bytes(directory, index))
    reference.write_private(directory, "sidecar.json", oracle.canonical(sidecar))
    return result


def correlate(scope, plan, actions, wire, records, source, read_user, read_page):
    """Shared pure correlation; caller controls private inputs and publication."""
    # Bounded random access into the fixed wire; full legacy semantics are
    # checked exactly once below before writing any output.
    require(len(wire) >= legacy.HEADER.size + legacy.FOOTER.size, "kernel_wire_size")
    count = legacy.HEADER.unpack_from(wire)[3]
    require(0 < count <= legacy.MAX_RECORDS and len(wire) ==
            legacy.HEADER.size + count * legacy.RECORD.size + legacy.FOOTER.size,
            "kernel_wire_size")
    require(type(records) is list and len(records) == len(actions), "kernel_count")
    witnesses = []

    def event(record, sequence_field, name, **fields):
        sequence = record[sequence_field]
        require(oracle.integer(sequence, 1, count), "kernel_ordinal")
        row = dict(zip(legacy.FIELDS, legacy.RECORD.unpack_from(
            wire, legacy.HEADER.size + (sequence - 1) * legacy.RECORD.size)))
        require(row["sequence"] == sequence and
                row["event"] == legacy.EVENTS.index(name) + 1 and
                row["operation"] == record["operation"] and
                all(row[key] == value for key, value in fields.items()), "kernel_event_binding")
        return row

    previous_upper = 0
    for index, (record, action) in enumerate(zip(records, actions)):
        require(type(record) is dict and set(record) == KERNEL_FIELDS, "kernel_shape")
        require(all(oracle.integer(record[key], 1, (1 << 64) - 1)
                    for key in ("operation", "original", "clone", "descriptor")) and
                oracle.integer(record["logical"], 1, (1 << 32) - 1) and
                oracle.integer(record["kind"], 1, 6) and
                oracle.integer(record["status"], 0, 255) and
                record["logical"] == action["logical"] and
                record["kind"] == KINDS[action["kind"]] and
                record["status"] == action["status"], "kernel_identity")
        accept = event(record, "accept_sequence", "accept",
                       original=record["original"], clone=record["clone"],
                       descriptor=record["descriptor"], logical=record["logical"],
                       operation_kind=oracle.KINDS[action["kind"]])
        clone = event(record, "clone_sequence", "clone_endio", clone=record["clone"],
                      descriptor=record["descriptor"], status=record["status"])
        upper = event(record, "upper_sequence", "upper_endio",
                      original=record["original"], status=record["status"])
        require(previous_upper < accept["sequence"] < clone["sequence"] < upper["sequence"],
                "kernel_order")
        previous_upper = upper["sequence"]
        read = action["kind"] == "typed_read"
        if read:
            require(oracle.integer(record["pin"], 1, (1 << 64) - 1), "kernel_pin")
            pin = event(record, "pin_sequence", "pin", pin=record["pin"],
                        logical=record["logical"], generation=action["generation"],
                        **{key: action[key] for key in oracle.KEY_FIELDS})
            copy = event(record, "copy_sequence", "oracle", pin=record["pin"],
                         decoded_length=oracle.PAGE_BYTES, compared=oracle.PAGE_BYTES,
                         status=0)
            release = event(record, "release_sequence", "pin_release", pin=record["pin"], status=0)
            require(accept["sequence"] < pin["sequence"] < copy["sequence"] <
                    release["sequence"] < clone["sequence"], "kernel_pin_order")
        else:
            require(all(oracle.integer(record[key], 0, 0) for key in
                        ("pin", "pin_sequence", "copy_sequence", "release_sequence")),
                    "kernel_unexpected_pin")
        # Separate actual user observation file for EVERY operation. Neither
        # expected plan nor kernel status is substituted for actual user status.
        user = read_user(index)
        require(type(user) is dict and set(user) == USER_FIELDS and
                all(oracle.integer(user[key], 1, (1 << 64) - 1) and
                    user[key] == record[key] for key in
                    ("operation", "original", "upper_sequence", "logical")) and
                oracle.integer(user["version"], 0, (1 << 64) - 1) and
                user["version"] == action["version"] and
                oracle.integer(user["status"], 0, 255) and
                user["status"] == record["status"], "user_completion_binding")
        witness = {key: record[key] for key in oracle.WITNESS_FIELDS
                   if key not in ("user_page", "user_status")}
        witness["user_status"] = user["status"]
        witness["user_page"] = read_page(index).hex() if read else None
        witnesses.append(witness)
    sidecar = dict(schema=oracle.SCHEMA, scope_sha256=legacy.scope_digest(scope).hex(),
                   wire_sha256=oracle.digest(wire), operations=witnesses)
    result = oracle.validate(wire, scope, source, plan, sidecar)
    return dict(status=result["status"], operations=result["operations"], auth=0), sidecar


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
