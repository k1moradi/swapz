#!/usr/bin/env python3
"""Fresh synthetic wire and actual C collector export; never native capture."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tests/tools/round102-private-byte-reference.py"
spec = importlib.util.spec_from_file_location("private_reference", TOOL)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
oracle = reference.oracle
source, binary = sys.argv[1:]
# Reuse only the pinned R099 fixture construction helpers, not its test
# module's executed corpus or any previous accepted wire.
fixture_path = ROOT / "tests/runtime/native/independent-byte-oracle-test.py"
tree = ast.parse(fixture_path.read_text())
names = {"action", "fixture", "pack"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in helpers} == names
namespace = dict(oracle=oracle, legacy=oracle.legacy, source=source,
                 seed="a7" * 32, nonce="d9" * 16)
exec(compile(ast.Module(body=helpers, type_ignores=[]), str(fixture_path), "exec"), namespace)
action = namespace["action"]
scope, plan, rows, high, _ = namespace["fixture"]([
    action("typed_write", 7, 1, 19, 2, 31),
    action("typed_read", 7, 1, 19, 2, 31)])
wire = namespace["pack"](scope, rows, high)
checks = 0

with tempfile.TemporaryDirectory(prefix="r102-private-") as temp:
    directory = reference.private_directory(temp)
    def put(name, data):
        reference.write_private(directory, name, data)
    def remove(name):
        os.unlink(name, dir_fd=directory)
    def call(mode, index=None):
        return reference.execute(mode, directory, source, index)
    def reject(mode, reason, index=None):
        global checks
        try:
            call(mode, index)
        except oracle.legacy.Invalid as error:
            assert str(error) == reason
        else:
            raise AssertionError("unexpected private acceptance")
        checks += 1
    def capture(input_page, final_page, user_page):
        # Model only: separate supplied byte arrays. Never print payloads.
        proc = subprocess.run([binary], input=input_page + final_page + user_page,
                              capture_output=True, timeout=10)
        assert proc.returncode == 0 and not proc.stderr, "collector fixture failed"
        assert len(proc.stdout) <= oracle.MAX_SIDECAR_BYTES
        return json.loads(proc.stdout)
    try:
        put("scope.json", oracle.canonical(scope))
        put("plan.json", oracle.canonical(plan))
        assert call("materialize", 0)["status"] == "REFERENCE_MATERIALIZED"
        page = reference.read_private(directory, "reference-0.page", 4096)
        assert len(page) == 4096
        checks += 1
        # Fresh synthetic model: output arrays are distinct buffers, with
        # test-controlled corruption below. No claim of physical provenance.
        final = bytes(bytearray(page))
        user = bytes(memoryview(page))
        put("wire.bin", wire)
        put("user-1.page", user)
        records = capture(page, final, user)
        put("collector.json", oracle.canonical(records))
        assert call("compare", 1)["status"] == "USER_BYTES_MATCH"
        result = call("assemble")
        assert result["status"] == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY"
        sidecar = reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES)
        assert sidecar["operations"] == records
        assert sidecar["operations"][1]["copy_sequence"] == 23
        checks += 3
        try:
            call("materialize", 0)
        except FileExistsError:
            checks += 1
        else:
            raise AssertionError("reference overwritten")
        remove("sidecar.json")
        remove("user-1.page")
        damaged = bytes([user[0] ^ 1]) + user[1:]
        put("user-1.page", damaged)
        reject("compare", "independent_byte_mismatch", 1)
        reject("assemble", "collector_user_mismatch")
        remove("collector.json")
        put("collector.json", oracle.canonical(capture(page, final, damaged)))
        reject("assemble", "independent_byte_mismatch")
        remove("user-1.page")
        put("user-1.page", user)
        remove("collector.json")
        put("collector.json", oracle.canonical(capture(page, damaged, user)))
        reject("assemble", "independent_byte_mismatch")
        remove("user-1.page")
        put("user-1.page", user[:-1])
        reject("compare", "full_page_required", 1)
        remove("user-1.page")
        put("user-1.page", user)
        os.chmod("user-1.page", 0o644, dir_fd=directory)
        reject("compare", "private_regular_file", 1)
        remove("user-1.page")
        os.symlink("reference-0.page", "user-1.page", dir_fd=directory)
        reject("compare", "regular_file_required", 1)
        remove("user-1.page")
        assert not (Path(temp) / "sidecar.json").exists()
        checks += 1
    finally:
        os.close(directory)
print(json.dumps(dict(status="PASS_SYNTHETIC_PRIVATE_COMPATIBILITY_ONLY",
                      checks=checks, auth=0, native_capture=False), sort_keys=True))
