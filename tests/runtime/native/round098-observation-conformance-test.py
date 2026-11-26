#!/usr/bin/env python3
"""Check actual emitted wire from frozen constructors and new event shapes."""
import importlib.util
import json
from pathlib import Path
import struct
import sys

source, directory = sys.argv[1:]
directory = Path(directory)
path = Path(__file__).resolve().parents[2] / "tools/native-observation-current-export.py"
spec = importlib.util.spec_from_file_location("current", path)
current = importlib.util.module_from_spec(spec)
spec.loader.exec_module(current)
legacy = current.legacy
scope = dict(source=source, mapping_source=legacy.MAPPING_SOURCE,
             linux_source=legacy.LINUX_SOURCE,
             kernel_sha256="1"*64, module_sha256="2"*64, workload_sha256="3"*64,
             run_nonce="4"*32, target="5"*32, session=11, epoch=12, target_epoch=13,
             registration_epoch=14, first_logical=7, page_count=2, profile="M3568")
checks = 0


def reject(raw, reason):
    global checks
    try:
        current.validate_current(raw, scope, source)
    except legacy.Invalid as error:
        assert str(error) == reason, (reason, str(error))
    else:
        raise AssertionError("unexpected acceptance: " + reason)
    checks += 1


def frame(raw, expected_count, expected_loss):
    global checks
    magic, mapping, digest, count, high, capacity, size = legacy.HEADER.unpack_from(raw)
    assert magic == b"SWZOBS2\0" and mapping == legacy.MAPPING_SOURCE.encode("ascii")
    assert digest == legacy.scope_digest(scope)
    assert count == expected_count and count <= capacity and high <= capacity * 8
    assert size == legacy.RECORD.size
    assert len(raw) == legacy.HEADER.size + count * size + legacy.FOOTER.size
    footer = legacy.FOOTER.unpack_from(raw, len(raw) - legacy.FOOTER.size)
    assert footer == (b"SWZEND2\0", count, expected_loss, 0), footer
    rows = [dict(zip(legacy.FIELDS, legacy.RECORD.unpack_from(raw, 104 + i*296)))
            for i in range(count)]
    for index, row in enumerate(rows, 1):
        assert row["sequence"] == index
    checks += 1
    return rows


def rewrite(raw, rows):
    # Preserve framing, current manifest and loss; change only event semantics.
    header = bytearray(raw[:104])
    struct.pack_into("<Q", header, 80, len(rows))
    records = []
    for sequence, row in enumerate(rows, 1):
        records.append(legacy.RECORD.pack(*(sequence if field == "sequence" else row[field]
                                            for field in legacy.FIELDS)))
    return bytes(header) + b"".join(records) + legacy.FOOTER.pack(b"SWZEND2\0", len(rows), 0, 0)


def event_index(rows, name, ordinal=0):
    return [i for i, row in enumerate(rows)
            if legacy.EVENTS[row["event"]-1] == name][ordinal]


for compiler in ("gcc", "clang"):
    def read(mode):
        return (directory / f"{compiler}-{mode}.wire").read_bytes()

    # Exact R097 extracted constructors: each malformed record is rejected
    # before reservation. CAPTURE and explicit fresh BIND setup remain.
    for mode, expected in {
        "frozen-preparation": ["capture"],
        "frozen-bind": ["capture"],
        "frozen-upper": ["capture", "bind"],
        "frozen-drop": ["capture"],
        "frozen-release": ["capture", "bind"],
        "frozen-dm": [],
    }.items():
        raw = read(mode)
        rows = frame(raw, len(expected), 4)
        assert [legacy.EVENTS[r["event"]-1] for r in rows] == expected
        # Zero records fails the legacy header-bounds check before footer;
        # do not rewrite the parser or claim loss is its first error.
        reject(raw, "recorder_loss" if expected else "header_bounds")

    raw = read("terminal-overflow")
    rows = frame(raw, 2, 10)
    assert [legacy.EVENTS[r["event"]-1] for r in rows] == ["capture", "capture_drop"]
    reject(raw, "recorder_loss")

    raw = read("clean")
    rows = frame(raw, 30, 0)
    result = current.validate_current(raw, scope, source)
    assert result["status"] == "CONSISTENT_RECORDER_OBSERVATIONS_ONLY", result
    assert not result["source_mapped_authenticated"] and not result["native_capture"]
    counts = result["counts"]
    for name, count in dict(mm_decode=1, ordinary_prepared=1, preparation_discarded=1,
                            claims=1, publications=1, clone_acks=2, upper_acks=2,
                            verified_oracles=1, capture_drop=1, candidate_release=1,
                            carrier_release=2).items():
        assert counts[name] == count, (name, counts)
    checks += 1

    # Only new semantic fault shapes, no accepted R097 corpus replay.
    mutated = [r.copy() for r in rows]
    mutated[event_index(rows, "accept")]["store"] += 1
    reject(rewrite(raw, mutated), "capture_binding")
    mutated = [r.copy() for r in rows]
    mutated[event_index(rows, "preparation")]["flags"] = 2
    reject(rewrite(raw, mutated), "preparation_order")
    mutated = rows.copy()
    a, b = event_index(rows, "flush"), event_index(rows, "publish")
    mutated[a], mutated[b] = mutated[b], mutated[a]
    reject(rewrite(raw, mutated), "publish_order")
    mutated = rows.copy()
    a, b = event_index(rows, "oracle"), event_index(rows, "pin_release")
    mutated[a], mutated[b] = mutated[b], mutated[a]
    reject(rewrite(raw, mutated), "pin_release")
    for event in ("candidate_release", "carrier_release", "capture_drop"):
        mutated = rows.copy()
        del mutated[event_index(rows, event)]
        reject(rewrite(raw, mutated), "incomplete_lifetime")
    print(json.dumps(dict(compiler=compiler, clean_records=30, frozen_modes=6,
                          rejected_frozen_appends=7, terminal_overflow_modes=1,
                          semantic_refusals=7, native_capture=False, auth=0),
                     sort_keys=True))
print(json.dumps(dict(frame_and_validation_checks=checks, compilers=2,
                      actual_adapter=True, auth=0), sort_keys=True))
