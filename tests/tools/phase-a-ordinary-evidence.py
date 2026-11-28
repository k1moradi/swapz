#!/usr/bin/env python3
"""Prospective ordinary-only evidence contract, version 1; NOT a native producer.

Two independent UTF-8 JSON objects, no duplicate/unknown keys or nonfinite
numbers. Manifest: {schema: 'swapz-ordinary-manifest', version: 1, scope,
 pages: [{logical, slot, store, generation, cookie, expected_page}]}.
Scope: {source (40 lowercase hex Git commit), run_nonce (32 lowercase hex),
 workload_sha256 (64 lowercase hex), area_epoch, swap_type, target}.
Hex identities must be nonzero; expected_page is exactly 8192 lowercase hex
characters. All numbers are JSON integers (not booleans); swap_type 0..255,
 logical/generation 1..2**32-1, other identities 1..2**64-1. Manifest
 pages are independently retained, including prior store identity, not
 reconstructed from the capture. 1..16 pages, at most 64 I/O operations;
 this first profile permits exactly one serial write/read pair per page.

Capture: {schema: 'swapz-ordinary-capture', version: 1, scope, loss: 0,
 events: [...]}. Scope must equal manifest. Contiguous seq from 1; no
 interleaving, replacement, retry, dropped or extra events. Per-page event
 base: {seq, stage, logical, slot, store, generation, cookie, area_epoch,
 swap_type, target}. Stages and exact additional fields in order:
 stored {status:0}; natural_evict {cause:'native_reclaim'};
 Here natural_evict denotes selection for natural eviction, not retirement.
 write_mm {operation}; write_bio {operation,bio,logical_bytes:4096,page};
 write_dm {operation,bio,dm}; write_lower_submit {operation,bio,dm,lower,bytes};
 write_lower_complete {operation,bio,dm,lower,bytes,status:0};
 write_commit {operation,bio,dm,logical_bytes:4096,status:0};
 write_upper {operation,bio,dm,logical_bytes:4096,status:0};
 evict_retired {operation,status:0};
 read_mm {operation,commit_seq,route:'ordinary_backing'}; read_bio {operation,bio,logical_bytes:4096};
 read_dm {operation,bio,dm}; read_lower_submit {operation,bio,dm,lower,bytes};
 read_lower_complete {operation,bio,dm,lower,bytes,status:0};
 read_upper {operation,bio,dm,logical_bytes:4096,status:0,page};
 read_user {operation,bio,logical_bytes:4096,status:0,page}.
 Operation/BIO/DM/lower tokens are nonzero and globally unique on first use;
 subsequent stages repeat exact tokens. Lower bytes: 512..16384, multiple
 of 512, completion exactly equals submission. Logical bytes are separate:
 no RAW, typed, compression or decoder claim. All three page fields must
 match the independent expected full page, not just a digest.

 Terminal events (no page identity): {seq,stage:'cleanup',target,area_epoch,
 swap_type,receipt,issuer:'controller_census',status:0,maps:0,bios:0,
 pins:0,reservations:0,stores:0,caps:0,tickets:0,quarantines:0},
 then {seq,stage:'dtr',target,area_epoch,swap_type,receipt,cleanup_seq,
 issuer:'dm_target_dtr',status:0}. Distinct nonzero receipt tokens, exact
 scope, terminal order.
 Receipts are claims requiring future independent actual capture; no caller
 field, digest, boolean or consistency result authenticates anything.
 JSON caps: manifest 256 KiB, capture 1 MiB; CLI takes two private regular
 files (owner mode0600, single link, parent owner mode0700), never emits
 page bytes, paths, identifiers or arbitrary exceptions.
 All results retain AUTH=0, native qualification BLOCKED, observation UNKNOWN.
 No native producer, trust root, runtime action, or physical permission.
"""
import json
import os
import re
import stat
import sys

PAGE_BYTES = 4096
MAX_PAGES = 16
MAX_OPERATIONS = 64
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CAPTURE_BYTES = 1024 * 1024
U64 = (1 << 64) - 1
U32 = (1 << 32) - 1
SCOPE_KEYS = {"source", "run_nonce", "workload_sha256", "area_epoch", "swap_type", "target"}
IDENTITY_KEYS = {"logical", "slot", "store", "generation", "cookie"}
AREA_KEYS = {"area_epoch", "swap_type", "target"}
STAGES = (
    ("stored", {"status"}), ("natural_evict", {"cause"}),
    ("write_mm", {"operation"}),
    ("write_bio", {"operation", "bio", "logical_bytes", "page"}),
    ("write_dm", {"operation", "bio", "dm"}),
    ("write_lower_submit", {"operation", "bio", "dm", "lower", "bytes"}),
    ("write_lower_complete", {"operation", "bio", "dm", "lower", "bytes", "status"}),
    ("write_commit", {"operation", "bio", "dm", "logical_bytes", "status"}),
    ("write_upper", {"operation", "bio", "dm", "logical_bytes", "status"}),
    ("evict_retired", {"operation", "status"}),
    ("read_mm", {"operation", "commit_seq", "route"}),
    ("read_bio", {"operation", "bio", "logical_bytes"}),
    ("read_dm", {"operation", "bio", "dm"}),
    ("read_lower_submit", {"operation", "bio", "dm", "lower", "bytes"}),
    ("read_lower_complete", {"operation", "bio", "dm", "lower", "bytes", "status"}),
    ("read_upper", {"operation", "bio", "dm", "logical_bytes", "status", "page"}),
    ("read_user", {"operation", "bio", "logical_bytes", "status", "page"}),
)
MAX_EVENTS = MAX_PAGES * len(STAGES) + 2
GATES = dict(auth=0, native_qualification="BLOCKED", phase_a="BLOCKED",
             observation="UNKNOWN", compressed_handoff=False, forced_raw=False,
             import_enabled=False, physical="NO_GO", authenticated=False)


class Invalid(ValueError):
    """Only fixed, non-sensitive reason codes may be raised."""


def require(condition, reason):
    if not condition:
        raise Invalid(reason)


def integer(value, low=1, high=U64):
    return type(value) is int and low <= value <= high


def hex_string(value, size):
    return (type(value) is str and len(value) == size * 2 and
            re.fullmatch(r"[0-9a-f]+", value) is not None)


def shape(value, keys, reason):
    require(type(value) is dict and value.keys() == keys, reason)


def scope_valid(scope):
    shape(scope, SCOPE_KEYS, "scope_shape")
    for key, size in (("source", 20), ("run_nonce", 16), ("workload_sha256", 32)):
        require(hex_string(scope[key], size) and scope[key] != "0" * (size * 2), "scope_digest")
    require(integer(scope["area_epoch"]) and integer(scope["target"]) and
            integer(scope["swap_type"], 0, 255), "scope_identity")


def identity_valid(row):
    require(all(integer(row[key], 1, U32 if key in ("logical", "generation") else U64)
                for key in IDENTITY_KEYS), "page_identity")


def envelope(value, schema, keys):
    shape(value, keys | {"schema", "version", "scope"}, "envelope_shape")
    require(value["schema"] == schema and integer(value["version"], 1, 1), "schema_version")
    scope_valid(value["scope"])


def exact_fields(row, expected, keys, reason):
    # Python bool compares equal to int; strict type checking is mandatory.
    require(all(type(row[key]) is type(expected[key]) and row[key] == expected[key]
                for key in keys), reason)


def fresh(value, seen):
    require(integer(value) and value not in seen, "duplicate_attribution")
    seen.add(value)


def validate(manifest, capture):
    """Return structural correlation only. All invalid inputs raise Invalid."""
    envelope(manifest, "swapz-ordinary-manifest", {"pages"})
    pages = manifest["pages"]
    require(type(pages) is list and 1 <= len(pages) <= MAX_PAGES and
            2 * len(pages) <= MAX_OPERATIONS, "page_bounds")
    expected = {}
    slots, stores, cookies = set(), set(), set()
    for page in pages:
        shape(page, IDENTITY_KEYS | {"expected_page"}, "manifest_page_shape")
        identity_valid(page)
        require(page["logical"] not in expected, "duplicate_logical")
        for key, seen in (("slot", slots), ("store", stores), ("cookie", cookies)):
            fresh(page[key], seen)
        require(hex_string(page["expected_page"], PAGE_BYTES), "expected_page_length")
        expected[page["logical"]] = page
    envelope(capture, "swapz-ordinary-capture", {"loss", "events"})
    scope = manifest["scope"]
    exact_fields(capture["scope"], scope, SCOPE_KEYS, "stale_scope")
    require(integer(capture["loss"], 0, 0), "capture_loss")
    events = capture["events"]
    require(type(events) is list and 2 < len(events) <= MAX_EVENTS, "event_bounds")
    index = 0
    seen_tokens, seen_pages = set(), set()

    def next_event(stage, keys):
        nonlocal index
        require(index < len(events), "missing_event")
        row = events[index]
        shape(row, keys | {"seq", "stage"} | AREA_KEYS, "event_shape")
        require(integer(row["seq"], index + 1, index + 1), "event_sequence")
        require(row["stage"] == stage, "event_order")
        exact_fields(row, scope, AREA_KEYS, "event_scope")
        index += 1
        return row

    for _ in pages:
        identity = None
        tokens = {}
        lower_bytes = None
        commit_sequence = None
        for stage, extra in STAGES:
            row = next_event(stage, IDENTITY_KEYS | extra)
            identity_valid(row)
            if stage == "stored":
                logical = row["logical"]
                require(logical in expected and logical not in seen_pages, "page_coverage")
                seen_pages.add(logical)
                identity = expected[logical]
                reference = bytes.fromhex(identity["expected_page"])
            exact_fields(row, identity, IDENTITY_KEYS, "stale_page_identity")
            if "status" in extra:
                require(integer(row["status"], 0, 0), "failed_stage")
            if "cause" in extra:
                require(row["cause"] == "native_reclaim", "not_natural_eviction")
            if stage == "write_commit":
                commit_sequence = row["seq"]
            if stage == "read_mm":
                require(integer(row["commit_seq"], commit_sequence, commit_sequence) and
                        row["route"] == "ordinary_backing", "read_commit_binding")
            if stage.endswith("_mm"):
                tokens = {}
                lower_bytes = None
            for key in ("operation", "bio", "dm", "lower"):
                if key not in extra:
                    continue
                if key not in tokens:
                    fresh(row[key], seen_tokens)
                    tokens[key] = row[key]
                else:
                    exact_fields(row, tokens, {key}, "operation_binding")
            if "logical_bytes" in extra:
                require(integer(row["logical_bytes"], PAGE_BYTES, PAGE_BYTES), "logical_completion")
            if "bytes" in extra:
                require(integer(row["bytes"], 512, 16384) and row["bytes"] % 512 == 0,
                        "lower_length")
                if stage.endswith("_submit"):
                    lower_bytes = row["bytes"]
                else:
                    require(row["bytes"] == lower_bytes, "lower_completion")
            if "page" in extra:
                require(hex_string(row["page"], PAGE_BYTES), "full_page_required")
                require(bytes.fromhex(row["page"]) == reference, "independent_byte_mismatch")
    debts = {"maps", "bios", "pins", "reservations", "stores", "caps", "tickets", "quarantines"}
    cleanup = next_event("cleanup", debts | {"receipt", "status", "issuer"})
    require(cleanup["issuer"] == "controller_census" and
            all(integer(cleanup[key], 0, 0) for key in debts | {"status"}), "cleanup_debt")
    fresh(cleanup["receipt"], seen_tokens)
    dtr = next_event("dtr", {"receipt", "cleanup_seq", "status", "issuer"})
    fresh(dtr["receipt"], seen_tokens)
    require(dtr["issuer"] == "dm_target_dtr" and integer(dtr["status"], 0, 0) and
            integer(dtr["cleanup_seq"], cleanup["seq"], cleanup["seq"]), "dtr_binding")
    require(index == len(events), "trailing_event")
    return dict(status="CONSISTENT_ORDINARY_CORRELATION_ONLY", pages=len(pages),
                operations=2 * len(pages), bytes_compared=3 * PAGE_BYTES * len(pages), **GATES)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def bounded_integer(value):
    require(len(value) <= 21, "integer_bounds")
    return int(value)


def reject_constant(_):
    raise Invalid("invalid_json_constant")


def parse(raw, limit):
    require(type(raw) is bytes and 2 <= len(raw) <= limit, "input_bounds")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                      parse_int=bounded_integer, parse_constant=reject_constant)


def private_file(info):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
            stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def read_regular(path, limit):
    parent, name = os.path.split(path)
    directory = os.open(parent or ".", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "private_directory_required")
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        require(private_file(before), "private_regular_file_required")
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as stream:
            info = os.fstat(stream.fileno())
            require(private_file(info) and (info.st_dev, info.st_ino) ==
                    (before.st_dev, before.st_ino), "file_changed")
            require(2 <= info.st_size <= limit, "input_bounds")
            raw = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            require(len(raw) == info.st_size and private_file(after) and
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                    (info.st_size, info.st_mtime_ns, info.st_ctime_ns), "file_changed")
            return parse(raw, limit)
    finally:
        os.close(directory)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        require(len(argv) == 2, "arguments")
        result = validate(read_regular(argv[0], MAX_MANIFEST_BYTES),
                          read_regular(argv[1], MAX_CAPTURE_BYTES))
    except Invalid as error:
        result = dict(status="BLOCKED", reason=str(error), **GATES)
    except (ValueError, TypeError, KeyError, OverflowError, OSError, RecursionError):
        result = dict(status="BLOCKED", reason="invalid_input", **GATES)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "CONSISTENT_ORDINARY_CORRELATION_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
