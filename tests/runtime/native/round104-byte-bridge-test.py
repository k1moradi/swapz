#!/usr/bin/env python3
"""Actual guarded bridge + owner host fixture, independent synthetic user observations."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "correlation", ROOT / "tests/tools/round103-private-byte-correlation.py")
correlation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(correlation)
reference, oracle, legacy = correlation.reference, correlation.oracle, correlation.legacy
source, binary = sys.argv[1:]
fixture_path = ROOT / "tests/runtime/native/independent-byte-oracle-test.py"
tree = ast.parse(fixture_path.read_text())
names = {"action", "fixture", "pack"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in helpers} == names
namespace = dict(oracle=oracle, legacy=legacy, source=source,
                 seed="b9" * 32, nonce="d" * 32)
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(fixture_path), "exec"), namespace)
action = namespace["action"]
actions = [
    action("typed_write", 7, 1, 11, 1, 31),
    action("typed_read", 7, 1, 11, 1, 31),
    action("typed_write", 8, 1, 12, 2, 32),
    action("typed_read", 8, 1, 12, 2, 32),
    action("fallback", 7, 2, 13, 1, 33),
    action("ordinary_write", 9, 1, 14),
    action("discard", 9, 2, 0),
]
checks = 0


def fixture(error=False):
    selected = actions + ([action("claimed_error", 10, 1, 15, 2, 34, 5)] if error else [])
    scope, plan, rows, high, _ = namespace["fixture"](selected)
    wire = namespace["pack"](scope, rows, high)
    pages = [oracle.reference_page(plan["seed"], plan["nonce"], a["logical"], a["version"])
             if a["version"] else None for a in selected]
    accepts = {row["operation"]: index for index, row in enumerate(
        row for row in rows if row["event"] == legacy.EVENTS.index("accept") + 1)}
    payload = bytearray(struct.pack("<II", len(rows), high) + scope["workload_sha256"].encode("ascii"))
    for row in rows:
        payload.extend(legacy.RECORD.pack(*(0 if field == "sequence" else row[field]
                                           for field in legacy.FIELDS)))
        name = legacy.EVENTS[row["event"] - 1]
        if name in ("capture", "oracle") or (name == "accept" and row["operation_kind"] == 3):
            payload.extend(pages[accepts[row["operation"]]])
    return scope, plan, wire, bytes(payload), pages


def run(mode, data):
    proc = subprocess.run([binary, mode], input=data[3], capture_output=True, timeout=25)
    # Do not emit private child output even on failure.
    assert proc.returncode == 0 and not proc.stderr, "actual bridge fixture failed: " + mode
    assert len(proc.stdout) <= legacy.MAX_BYTES + oracle.MAX_SIDECAR_BYTES
    return proc.stdout


def join(mode, data, expected):
    global checks
    scope, plan, wire, _, pages = data
    output = run(mode, data)
    assert output[:len(wire)] == wire, "actual selected recorder wire differs"
    records = json.loads(output[len(wire):])
    assert len(records) == len(plan["actions"])
    assert all(set(r) == correlation.KERNEL_FIELDS for r in records)
    assert [r["kind"] for r in records] == [correlation.KINDS[a["kind"]] for a in plan["actions"]]
    with tempfile.TemporaryDirectory(prefix="r104-private-") as temp:
        directory = reference.private_directory(temp)
        try:
            def put(name, data):
                reference.write_private(directory, name, data)
            put("scope.json", oracle.canonical(scope))
            put("plan.json", oracle.canonical(plan))
            put("wire.bin", wire)
            put("kernel-collector.json", oracle.canonical(records))
            for index, (record, a) in enumerate(zip(records, plan["actions"])):
                # Separate synthetic user-process inputs: no kernel user page/status
                # input and no user pointer in the guarded bridge.
                metadata = dict(operation=record["operation"], original=record["original"],
                                upper_sequence=record["upper_sequence"], logical=a["logical"],
                                version=a["version"], status=a["status"])
                put(f"user-{index}.json", oracle.canonical(metadata))
                if a["kind"] == "typed_read":
                    put(f"user-{index}.page", bytes(bytearray(pages[index])))
            if mode == "wrong_copy":
                try:
                    correlation.assemble(directory, source)
                except legacy.Invalid as error:
                    assert str(error) == "independent_byte_mismatch"
                else:
                    raise AssertionError("corrupt final byte accepted")
                assert not (Path(temp) / "sidecar.json").exists()
            else:
                result = correlation.assemble(directory, source)
                assert result["status"] == expected and result["auth"] == 0
                sidecar = reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES)
                assert len(sidecar["operations"]) == len(records)
            checks += 1
        finally:
            os.close(directory)


clean = fixture()
error = fixture(True)
join("clean", clean, "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY")
join("error", error, "OBSERVED_CLAIMED_ERROR_BLOCKED")
join("wrong_copy", clean, None)
for mode in ("aborted", "stale", "duplicate_finish", "wrong_scope", "capacity", "race",
             "zero", "wrong_ordinal", "wrong_record", "missing_copy", "duplicate",
             "bad_status", "pending", "failed_join"):
    assert run(mode, clean) == b"R104_BRIDGE_REJECTED AUTH=0\n", "expected sticky loss: " + mode
    checks += 1
print(json.dumps(dict(status="R104_BRIDGE_HOST_PASS", checks=checks,
                      clean_operations=7, claimed_error_operations=8,
                      native_capture=False, auth=0), sort_keys=True))
