#!/usr/bin/env python3
"""Actual sealed private export, frozen producer shapes, and separate synthetic user observations."""
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
    "private", ROOT / "tests/tools/round105-private-evidence.py")
private = importlib.util.module_from_spec(spec)
spec.loader.exec_module(private)
correlation, reference, oracle, legacy = private.correlation, private.reference, private.oracle, private.legacy
source, binary = sys.argv[1:]
fixture_path = ROOT / "tests/runtime/native/independent-byte-oracle-test.py"
tree = ast.parse(fixture_path.read_text())
names = {"action", "fixture", "pack"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in helpers} == names
namespace = dict(oracle=oracle, legacy=legacy, source=source,
                 seed="a8" * 32, nonce="d" * 32)
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
    # Separate synthetic workload memory and pre-held correlation metadata,
    # constructed before invoking the recorder; never copy its export.
    users = []
    for row in rows:
        if row["event"] == legacy.EVENTS.index("upper_endio") + 1:
            index = accepts[row["operation"]]
            a = selected[index]
            users.append(dict(operation=row["operation"], original=row["original"],
                              upper_sequence=row["sequence"], logical=a["logical"],
                              version=a["version"], status=row["status"],
                              run_nonce=scope["run_nonce"],
                              scope_sha256=legacy.scope_digest(scope).hex()))
    user_pages = [bytearray(oracle.reference_page(plan["seed"], plan["nonce"],
                                                a["logical"], a["version"]))
                  if a["kind"] == "typed_read" else None for a in selected]
    return scope, plan, wire, bytes(payload), users, user_pages


def run(mode, data):
    proc = subprocess.run([binary, mode], input=data[3], capture_output=True, timeout=25)
    # Do not emit private child output even on failure.
    assert proc.returncode == 0 and not proc.stderr, "actual bridge fixture failed: " + mode
    assert len(proc.stdout) <= private.MAX_BYTES
    return proc.stdout


def join(mode, data, expected):
    global checks
    scope, plan, wire, _, users, user_pages = data
    bundle = run(mode, data)
    actual_wire, records = private.unpack(bundle, scope)
    assert actual_wire == wire, "actual recorder wire differs or extra append"
    assert len(records) == len(plan["actions"])
    assert all(set(r) == correlation.KERNEL_FIELDS for r in records)
    assert [r["kind"] for r in records] == [correlation.KINDS[a["kind"]] for a in plan["actions"]]
    with tempfile.TemporaryDirectory(prefix="r105-private-") as temp:
        directory = reference.private_directory(temp)
        try:
            def put(name, content):
                reference.write_private(directory, name, content)

            def replace(name, content):
                os.unlink(name, dir_fd=directory)
                put(name, content)

            def reject(reason):
                global checks
                try:
                    private.assemble(directory, source)
                except legacy.Invalid as error:
                    assert str(error) == reason, "wrong refusal: " + str(error)
                else:
                    raise AssertionError("unexpected private acceptance")
                assert not (Path(temp) / "sidecar.json").exists()
                checks += 1

            put("scope.json", oracle.canonical(scope))
            put("plan.json", oracle.canonical(plan))
            put("native-evidence.bin", bundle)
            for index, (user, page) in enumerate(zip(users, user_pages)):
                put(f"user-{index}.json", oracle.canonical(user))
                if page is not None:
                    put(f"user-{index}.page", page)
            if mode == "wrong_copy":
                reject("independent_byte_mismatch")
                return
            result = private.assemble(directory, source)
            assert result["status"] == expected and result["auth"] == 0
            sidecar = reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES)
            assert len(sidecar["operations"]) == len(records)
            try:
                private.assemble(directory, source)
            except FileExistsError:
                pass
            else:
                raise AssertionError("exclusive output overwritten")
            assert reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES) == sidecar
            os.unlink("sidecar.json", dir_fd=directory)
            checks += 2
            if mode != "clean":
                return
            for field, value, reason in (
                ("run_nonce", "e" * 32, "user_scope_binding"),
                ("scope_sha256", "1" * 64, "user_scope_binding"),
                ("original", users[1]["operation"], "user_completion_binding"),
                ("upper_sequence", users[1]["upper_sequence"] - 1, "user_completion_binding"),
                ("status", 5, "user_completion_binding"),
                ("version", users[1]["version"] + 1, "user_completion_binding"),
            ):
                replace("user-1.json", oracle.canonical(dict(users[1], **{field: value})))
                reject(reason)
            replace("user-1.json", oracle.canonical(users[1]))
            changed = bytearray(user_pages[1])
            changed[-1] ^= 1
            replace("user-1.page", changed)
            reject("independent_byte_mismatch")
            replace("user-1.page", user_pages[1])
            os.unlink("user-1.page", dir_fd=directory)
            try:
                private.assemble(directory, source)
            except FileNotFoundError:
                checks += 1
            else:
                raise AssertionError("missing actual user bytes accepted")
            assert not (Path(temp) / "sidecar.json").exists()
            put("user-1.page", user_pages[1])
            for offset, value, reason in (
                (0, 0, "bundle_frame"), (8, 2, "bundle_frame"),
                (16, 65, "bundle_frame"), (24, bundle[24] ^ 1, "bundle_scope"),
                (len(bundle) - 1, 1, "bundle_frame"),
                (private.HEADER.size + len(wire) + 100, 3, "bundle_page_kind"),
            ):
                changed = bytearray(bundle)
                changed[offset] = value
                replace("native-evidence.bin", changed)
                reject(reason)
            replace("native-evidence.bin", bundle[:-1])
            reject("bundle_frame")
            replace("native-evidence.bin", bundle + b"x")
            reject("bundle_frame")
            replace("native-evidence.bin", bundle)
            # Successful retry after all rejected private attempts.
            assert private.assemble(directory, source)["status"] == expected
            checks += 1
        finally:
            os.close(directory)


clean = fixture()
error = fixture(True)
join("clean", clean, "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY")
join("error", error, "OBSERVED_CLAIMED_ERROR_BLOCKED")
join("wrong_copy", clean, None)
for mode in ("absent_cleanup", "unforwarded_cleanup", "cleanup_debt", "trailing",
             "gap", "wrong_original", "wrong_ordinal", "missing_copy", "pending",
             "stale", "race", "failed_join"):
    assert run(mode, clean) == b"R105_PRIVATE_REJECTED AUTH=0\n", "expected sticky loss: " + mode
    checks += 1
print(json.dumps(dict(status="R105_PRIVATE_EXPORT_HOST_PASS", checks=checks,
                      clean_operations=7, claimed_error_operations=8,
                      native_capture=False, auth=0), sort_keys=True))
