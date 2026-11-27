#!/usr/bin/env python3
"""Fresh R103 actual recorder ordinal/collector export and private join fixture."""
import ast
import copy
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
# Only frozen construction functions; never execute the historical corpus.
fixture_path = ROOT / "tests/runtime/native/independent-byte-oracle-test.py"
tree = ast.parse(fixture_path.read_text())
names = {"action", "fixture", "pack"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in helpers} == names
namespace = dict(oracle=oracle, legacy=legacy, source=source,
                 seed="b5" * 32, nonce="e6" * 16)
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(fixture_path), "exec"), namespace)
action = namespace["action"]
scope, plan, rows, high, _ = namespace["fixture"]([
    action("typed_write", 7, 1, 23, 1, 42),
    action("typed_read", 7, 1, 23, 1, 42)])
expected_wire = namespace["pack"](scope, rows, high)
checks = 0

with tempfile.TemporaryDirectory(prefix="r103-private-") as temp:
    directory = reference.private_directory(temp)

    def put(name, data):
        reference.write_private(directory, name, data)

    def replace(name, data):
        os.unlink(name, dir_fd=directory)
        put(name, data)

    def reject(reason):
        global checks
        try:
            correlation.assemble(directory, source)
        except legacy.Invalid as error:
            assert str(error) == reason, "wrong redacted refusal"
        else:
            raise AssertionError("unexpected correlation acceptance")
        assert not (Path(temp) / "sidecar.json").exists()
        checks += 1

    try:
        put("scope.json", oracle.canonical(scope))
        put("plan.json", oracle.canonical(plan))
        assert reference.execute("materialize", directory, source, 0)["status"] == "REFERENCE_MATERIALIZED"
        page = reference.read_private(directory, "reference-0.page", 4096)
        # Model buffers only, independently supplied to the C fixture and user join.
        final = bytes(bytearray(page))
        user = bytes(memoryview(page))
        payload = b"".join(legacy.RECORD.pack(*(0 if field == "sequence" else row[field]
                                                for field in legacy.FIELDS)) for row in rows)
        raw = struct.pack("<II", len(rows), high) + legacy.scope_digest(scope) + page + final + payload
        proc = subprocess.run([binary, "correlation"], input=raw, capture_output=True, timeout=15)
        assert proc.returncode == 0 and not proc.stderr, "actual fixture failed"
        wire = proc.stdout[:len(expected_wire)]
        assert wire == expected_wire, "actual selected recorder wire differs"
        records = json.loads(proc.stdout[len(expected_wire):])
        assert len(records) == 2 and all(set(r) == correlation.KERNEL_FIELDS for r in records)
        put("wire.bin", wire)
        put("kernel-collector.json", oracle.canonical(records))
        users = [dict(operation=r["operation"], original=r["original"],
                      upper_sequence=r["upper_sequence"], logical=a["logical"],
                      version=a["version"], status=0) for r, a in zip(records, plan["actions"])]
        for index, metadata in enumerate(users):
            put(f"user-{index}.json", oracle.canonical(metadata))
        put("user-1.page", user)
        assert correlation.assemble(directory, source)["status"] == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY"
        sidecar = reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES)
        assert sidecar["operations"][1]["user_page"] == user.hex()
        assert sidecar["operations"][1]["final_copy"] == final.hex()
        os.unlink("sidecar.json", dir_fd=directory)
        checks += 3
        # All six ordinals must point to their own event, not merely fall in range.
        for field in ("accept_sequence", "pin_sequence", "copy_sequence",
                      "release_sequence", "clone_sequence", "upper_sequence"):
            changed = copy.deepcopy(records)
            changed[1][field] += 1
            replace("kernel-collector.json", oracle.canonical(changed))
            reject("kernel_event_binding")
        changed = copy.deepcopy(records)
        changed[1]["pin_sequence"] = 0
        replace("kernel-collector.json", oracle.canonical(changed))
        reject("kernel_ordinal")
        changed = copy.deepcopy(records)
        changed[0]["status"] = 5
        replace("kernel-collector.json", oracle.canonical(changed))
        reject("kernel_identity")
        changed = copy.deepcopy(records)
        changed[1]["pin"] = records[0]["original"]
        replace("kernel-collector.json", oracle.canonical(changed))
        reject("kernel_event_binding")
        replace("kernel-collector.json", oracle.canonical(records))
        changed = dict(users[1], status=5)
        replace("user-1.json", oracle.canonical(changed))
        reject("user_completion_binding")
        changed = dict(users[1], upper_sequence=records[1]["clone_sequence"])
        replace("user-1.json", oracle.canonical(changed))
        reject("user_completion_binding")
        changed = dict(users[1], version=24)
        replace("user-1.json", oracle.canonical(changed))
        reject("user_completion_binding")
        replace("user-1.json", oracle.canonical(users[1]))
        replace("user-1.page", user[:-1] + bytes([user[-1] ^ 1]))
        reject("independent_byte_mismatch")
        replace("user-1.page", user)
        os.unlink("user-1.json", dir_fd=directory)
        try:
            correlation.assemble(directory, source)
        except FileNotFoundError:
            checks += 1
        else:
            raise AssertionError("missing user observation accepted")
        assert not (Path(temp) / "sidecar.json").exists()
    finally:
        os.close(directory)
print(json.dumps(dict(status="R103_PRIVATE_CORRELATION_HOST_PASS", checks=checks,
                      auth=0, native_capture=False), sort_keys=True))
