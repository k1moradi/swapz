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
    "delivery", ROOT / "tests/tools/round106-private-delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)
private = delivery.private
correlation, reference, oracle, legacy = private.correlation, private.reference, private.oracle, private.legacy
source, binary = sys.argv[1:3]
mutant_mode = sys.argv[3] if len(sys.argv) == 4 else None
assert len(sys.argv) in (3, 4)
fixture_path = ROOT / "tests/runtime/native/independent-byte-oracle-test.py"
tree = ast.parse(fixture_path.read_text())
names = {"action", "fixture", "pack"}
helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in helpers} == names
namespace = dict(oracle=oracle, legacy=legacy, source=source,
                 seed="97" * 32, nonce="d" * 32)
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
    with tempfile.TemporaryDirectory(prefix="r106-private-") as temp:
        directory = reference.private_directory(temp)
        try:
            def put(name, content):
                reference.write_private(directory, name, content)

            def remove(name):
                os.unlink(name, dir_fd=directory)

            def observe(index, metadata, page):
                if page is None:
                    delivery.capture(directory, source, index, metadata, None)
                    return
                # Actual separate host workload buffer returned by a real pipe
                # readinto; no live device, expected bytes used only to seed
                # the synthetic sender, not by the capture implementation.
                read_fd, write_fd = os.pipe()
                try:
                    assert os.write(write_fd, page) == len(page)
                finally:
                    os.close(write_fd)
                actual = bytearray(oracle.PAGE_BYTES)
                with os.fdopen(read_fd, "rb") as reader:
                    assert reader.readinto(actual) == oracle.PAGE_BYTES
                delivery.capture(directory, source, index, metadata, actual)
                actual[:] = b"\0" * len(actual)

            def reject(reason, call):
                global checks
                try:
                    call()
                except legacy.Invalid as error:
                    assert str(error) == reason, "wrong refusal: " + str(error)
                else:
                    raise AssertionError("unexpected private acceptance")
                assert not (Path(temp) / "sidecar.json").exists()
                checks += 1

            put("scope.json", oracle.canonical(scope))
            put("plan.json", oracle.canonical(plan))
            transferred = bytearray(bundle)
            delivery.deliver(directory, source, transferred)
            transferred[:] = b"\0" * len(transferred)
            assert reference.read_private(directory, "native-evidence.bin", private.MAX_BYTES) == bundle
            for index, (user, page) in enumerate(zip(users, user_pages)):
                observe(index, user, page)
            if mode == "wrong_copy":
                reject("independent_byte_mismatch", lambda: delivery.assemble(directory, source))
                return
            result = delivery.assemble(directory, source)
            assert result["status"] == expected and result["auth"] == 0
            sidecar = reference.private_json(directory, "sidecar.json", oracle.MAX_SIDECAR_BYTES)
            assert len(sidecar["operations"]) == len(records)
            remove("sidecar.json")
            checks += 1
            if mode != "clean":
                return
            # Existing destination cannot be overwritten, including a symlink.
            for call in (lambda: delivery.deliver(directory, source, bundle),
                         lambda: observe(1, users[1], user_pages[1])):
                try:
                    call()
                except FileExistsError:
                    checks += 1
                else:
                    raise AssertionError("private destination replaced")
            for field, value, reason in (
                ("run_nonce", "e" * 32, "user_scope_binding"),
                ("scope_sha256", "1" * 64, "user_scope_binding"),
            ):
                reject(reason, lambda: observe(1, dict(users[1], **{field: value}), user_pages[1]))
            for field, value in (
                ("original", users[1]["operation"]),
                ("upper_sequence", users[1]["upper_sequence"] - 1),
                ("status", 5),
            ):
                remove("user-1.observation")
                observe(1, dict(users[1], **{field: value}), user_pages[1])
                reject("user_completion_binding", lambda: delivery.assemble(directory, source))
            remove("user-1.observation")
            changed = bytearray(user_pages[1])
            changed[-1] ^= 1
            observe(1, users[1], changed)
            reject("independent_byte_mismatch", lambda: delivery.assemble(directory, source))
            remove("user-1.observation")
            reject("full_page_required", lambda: delivery.capture(directory, source, 1, users[1], None))
            reject("full_page_required", lambda: delivery.capture(
                directory, source, 1, users[1], memoryview(user_pages[1])[::2]))
            reject("unexpected_user_page", lambda: delivery.capture(
                directory, source, 0, users[0], user_pages[1]))
            try:
                delivery.assemble(directory, source)
            except FileNotFoundError:
                checks += 1
            else:
                raise AssertionError("missing actual user bytes accepted")
            os.symlink("plan.json", "user-1.observation", dir_fd=directory)
            try:
                observe(1, users[1], user_pages[1])
            except FileExistsError:
                checks += 1
            else:
                raise AssertionError("symlink replaced")
            reject("regular_file_required", lambda: delivery.assemble(directory, source))
            remove("user-1.observation")
            observe(1, users[1], user_pages[1])
            os.link("user-1.observation", "alias", src_dir_fd=directory, dst_dir_fd=directory)
            reject("private_regular_file", lambda: delivery.assemble(directory, source))
            remove("alias")
            remove("native-evidence.bin")
            reject("bundle_frame", lambda: delivery.deliver(directory, source, bundle[:-1]))
            changed = bytearray(bundle)
            changed[24] ^= 1
            reject("bundle_scope", lambda: delivery.deliver(directory, source, changed))
            assert not (Path(temp) / "native-evidence.bin").exists()
            delivery.deliver(directory, source, bundle)
            assert delivery.assemble(directory, source)["status"] == expected
            assert not any(p.name.startswith(".pending-") for p in Path(temp).iterdir())
            checks += 1
        finally:
            os.close(directory)


clean = fixture()
error = fixture(True)
if mutant_mode:
    # Mutants must fail an actual assertion, not merely refuse a compiler
    # invocation or emit arbitrary failure output. Keep payloads private.
    proc = subprocess.run([binary, mutant_mode], input=clean[3],
                          capture_output=True, timeout=25)
    assert proc.returncode != 0 and b"Assertion" in proc.stderr, "surviving mutant: " + mutant_mode
    print("R108_MUTANT_REJECTED " + mutant_mode)
    sys.exit(0)
join("clean", clean, "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY")
# The historical oracle's claimed-error classification remains unchanged;
# the current strict terminal bridge must not export nonzero quarantine debt.
assert run("error", error) == b"R106_PRIVATE_REJECTED AUTH=0\n"
checks += 1
join("wrong_copy", clean, None)
for mode in ("actual-controller", "actual-write", "actual-read", "actual-ordinary",
             "actual-fallback", "actual-error", "actual-missing-candidate",
             "actual-missing-carrier", "actual-late-carrier", "actual-gc",
             "actual-interleave", "actual-zero", "actual-packed"):
    assert run(mode, clean) == b"R106_ACTUAL_TRANSITION_CHECK AUTH=0\n", mode
    checks += 1
for mode in ("absent_cleanup", "unforwarded_cleanup", "failed_join",
             "pending", "pending_finish", "pending_cancel", "unrepresented",
             "late_stage", "late_finish", "duplicate_cleanup", "quarantine_debt",
             "wrong_ordinal", "close_pending", "close_committed", "late_finish_internal"):
    assert run(mode, clean) == b"R106_PRIVATE_REJECTED AUTH=0\n", mode
    checks += 1
print(json.dumps(dict(status="R108_TERMINAL_BYTE_HOST_PASS", checks=checks,
                      native_capture=False, actual_transition_modes=13, auth=0), sort_keys=True))
