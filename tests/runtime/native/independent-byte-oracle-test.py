#!/usr/bin/env python3
"""New private witness cases. Synthetic wire, never native capture or device I/O."""
import copy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

path = Path(__file__).resolve().parents[2] / "tools/native-observation-byte-oracle.py"
spec = importlib.util.spec_from_file_location("oracle", path)
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
legacy = oracle.legacy
source = sys.argv[1]
seed = "ab" * 32
nonce = "cd" * 16
checks = 0


def action(kind, logical, generation, version, codec=0, store=0, status=0):
    return dict(kind=kind, logical=logical, generation=generation, version=version,
                codec=codec, store=store, status=status, slot=logical if codec else 0,
                area_epoch=13 if codec else 0, swap_type=2 if codec else 0)


def fixture(actions):
    plan = dict(schema=oracle.SCHEMA, seed=seed, nonce=nonce, actions=actions)
    scope = dict(source=source, mapping_source=legacy.MAPPING_SOURCE,
                 linux_source=legacy.LINUX_SOURCE, kernel_sha256="1"*64,
                 module_sha256="2"*64, workload_sha256=oracle.digest(oracle.canonical(plan)),
                 run_nonce=nonce, target="3"*32, session=11, epoch=12,
                 target_epoch=13, registration_epoch=14, first_logical=7,
                 page_count=4, profile="M3568")
    rows, witnesses, maps = [], [], {}
    high = credit = quarantines = 0

    def mint():
        nonlocal high
        high += 1
        return high

    def emit(name, **fields):
        row = dict.fromkeys(legacy.U64 + legacy.U32, 0)
        row.update(dict.fromkeys(legacy.DIGESTS, legacy.ZERO))
        row.update(sequence=len(rows)+1, event=legacy.EVENTS.index(name)+1, **fields)
        rows.append(row)
        return row["sequence"]

    for a in actions:
        kind, page, generation = a["kind"], a["logical"], a["generation"]
        operation, original, clone, descriptor = (mint() for _ in range(4))
        status = a["status"]
        source_key = {key: a[key] for key in ("logical", "generation", *oracle.KEY_FIELDS)}
        reference = (oracle.reference_page(seed, nonce, page, a["version"])
                     if a["version"] else None)
        reference_hash = bytes.fromhex(oracle.digest(reference)) if reference else legacy.ZERO
        payload = dict(compressed_length=32, decoded_length=4096, codec=a["codec"],
                       tag=90, version=1, dictionary=0, compressed_sha256=bytes([page])*32,
                       page_sha256=reference_hash)
        pin = copy_sequence = 0
        input_page = final_copy = user_page = None
        if kind in oracle.WRITES:
            input_page = reference.hex()
        if oracle.KINDS[kind] == 1:
            emit("capture", operation=operation, operation_kind=1, **source_key, **payload)
            emit("preparation", operation=operation, flags=1)
            emit("bind", operation=operation, original=original)
        accept = emit("accept", operation=operation, operation_kind=oracle.KINDS[kind],
                      original=original, clone=clone, descriptor=descriptor,
                      **(dict(flags=1, **source_key) if oracle.KINDS[kind] == 1
                         else dict(logical=page)))
        if oracle.KINDS[kind] == 1:
            emit("preparation", operation=operation, flags=2)
        emit("dispatch", operation=operation, flags=2 if kind == "typed_read" else 1)
        if kind in oracle.WRITES:
            extent, lower = mint(), mint()
            if oracle.KINDS[kind] == 1:
                credit += 1
                emit("reserve", operation=operation, credit=credit, extent=extent)
                if kind == "fallback":
                    emit("refuse", operation=operation, status=95)
                    emit("cancel", operation=operation, credit=credit, flags=1)
                    emit("fallback", operation=operation)
                    extent = mint()
                else:
                    emit("claim", operation=operation, credit=credit, descriptor=descriptor)
                    emit("preparation", operation=operation, flags=4)
            ordinary = kind in ("ordinary_write", "fallback")
            if ordinary:
                payload = dict(compressed_length=4096, decoded_length=4096, codec=0,
                               tag=0, version=0, dictionary=0,
                               compressed_sha256=reference_hash, page_sha256=reference_hash)
            compressed_hash = payload["compressed_sha256"]
            emit("lower_submit", operation=operation, lower=lower, extent=extent,
                 flags=2, requested=4096, compressed_length=payload["compressed_length"],
                 compressed_sha256=compressed_hash)
            emit("lower_complete", operation=operation, lower=lower,
                 completed=0 if status else 4096, status=status,
                 observed_sha256=legacy.ZERO if status else compressed_hash)
            if status:
                emit("quarantine", operation=operation, extent=extent)
                quarantines += 1
            else:
                emit("flush", operation=operation, extent=extent)
                emit("publish", operation=operation, extent=extent,
                     new_generation=generation, gc_epoch=0 if ordinary else 1, **payload)
                maps[page] = extent
        elif kind == "typed_read":
            extent, lower, pin = maps[page], mint(), mint()
            emit("pin", operation=operation, extent=extent, pin=pin,
                 gc_epoch=1, **source_key)
            emit("lower_submit", operation=operation, lower=lower, extent=extent,
                 flags=1, requested=4096, compressed_length=payload["compressed_length"],
                 compressed_sha256=payload["compressed_sha256"])
            emit("lower_complete", operation=operation, lower=lower, completed=4096,
                 observed_sha256=payload["compressed_sha256"])
            # Fixture only: independent arrays from a mock input and a copy
            # of the full returned page. No real native page or actual decode.
            final_copy = bytes(bytearray(reference)).hex()
            user_page = bytes(memoryview(reference)).hex()
            copy_sequence = emit("oracle", operation=operation, pin=pin, decoded_length=4096,
                                 compared=4096, flags=1, page_sha256=reference_hash,
                                 observed_sha256=reference_hash)
            emit("pin_release", operation=operation, pin=pin)
        else:
            emit("discard", operation=operation, new_generation=generation)
        emit("clone_endio", operation=operation, clone=clone, descriptor=descriptor, status=status)
        upper = emit("upper_endio", operation=operation, original=original, status=status)
        if oracle.KINDS[kind] == 1:
            emit("candidate_release", operation=operation, descriptor=descriptor)
            emit("carrier_release", operation=operation, original=original)
        witnesses.append(dict(operation=operation, original=original, clone=clone,
                              descriptor=descriptor, accept_sequence=accept, upper_sequence=upper,
                              pin=pin, copy_sequence=copy_sequence, input_page=input_page,
                              final_copy=final_copy, user_page=user_page, user_status=status))
    emit("cleanup", flags=7, quarantines=quarantines)
    sidecar = dict(schema=oracle.SCHEMA, scope_sha256=legacy.scope_digest(scope).hex(),
                   wire_sha256="", operations=witnesses)
    return scope, plan, rows, high, sidecar


def pack(scope, rows, high, loss=0):
    capacity = 256
    header = legacy.HEADER.pack(b"SWZOBS2\0", legacy.MAPPING_SOURCE.encode(),
                                legacy.scope_digest(scope), len(rows), high,
                                capacity, legacy.RECORD.size)
    body = b"".join(legacy.RECORD.pack(*(index if field == "sequence" else row[field]
                                       for field in legacy.FIELDS))
                    for index, row in enumerate(rows, 1))
    return header + body + legacy.FOOTER.pack(b"SWZEND2\0", len(rows), loss, 0)


def run(data, *, loss=0, rebind=True, recommit=False):
    scope, plan, rows, high, sidecar = data
    if recommit:
        scope["workload_sha256"] = oracle.digest(oracle.canonical(plan))
    wire = pack(scope, rows, high, loss)
    if rebind:
        sidecar["wire_sha256"] = oracle.digest(wire)
        sidecar["scope_sha256"] = legacy.scope_digest(scope).hex()
    return oracle.validate(wire, scope, source, plan, sidecar)


actions = [action("typed_write", 7, 1, 1, 1, 11),
           action("typed_read", 7, 1, 1, 1, 11),
           action("typed_write", 8, 1, 2, 2, 12),
           action("typed_read", 8, 1, 2, 2, 12),
           action("fallback", 7, 2, 3, 1, 13),
           action("ordinary_write", 9, 1, 4),
           action("discard", 9, 2, 0)]
clean = fixture(actions)
result = run(clean)
assert result["status"] == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY", result
assert result["operations"] == 7 and result["full_pages_compared"] == 8
assert result["bytes_compared"] == 32768 and result["read_pairs"] == 2
assert result["auth"] == 0 and not result["native_capture"] and not result["semantic_qualification"]
checks += 1
error = fixture(actions + [action("claimed_error", 10, 1, 5, 2, 14, 5)])
result_error = run(error)
assert result_error["status"] == "OBSERVED_CLAIMED_ERROR_BLOCKED", result_error
assert result_error["operations"] == 8 and result_error["full_pages_compared"] == 9
assert result_error["first_failure"]["reason"] == "lower_error_or_digest"
checks += 1


def reject(name, mutate, reason, data=clean, **options):
    global checks
    changed = copy.deepcopy(data)
    mutate(changed)
    try:
        run(changed, **options)
    except legacy.Invalid as exc:
        assert str(exc) == reason, (name, reason, str(exc))
    else:
        raise AssertionError(name + " accepted")
    checks += 1
    print(json.dumps(dict(case=name, refusal=reason), sort_keys=True))


def witness(data, index):
    return data[4]["operations"][index]


def event(data, name, ordinal=0):
    return [row for row in data[2] if row["event"] == legacy.EVENTS.index(name)+1][ordinal]


def damage(value, offset):
    index = offset * 2
    return value[:index] + ("01" if value[index:index+2] == "00" else "00") + value[index+2:]


# Every byte position tested with true independent reference, unchanged trace
# digest and same witness identity. No old accepted wire corpus replay.
expected = oracle.reference_page(seed, nonce, 7, 1)
for position in range(4096):
    try:
        oracle.compare_page(damage(witness(clean, 1)["final_copy"], position),
                            expected)
    except legacy.Invalid as exc:
        assert str(exc) == "independent_byte_mismatch"
    else:
        raise AssertionError("byte mutation accepted")
checks += 4096
reject("last_final_copy_byte", lambda d: witness(d, 1).update(
       final_copy=damage(witness(d, 1)["final_copy"], 4095)), "independent_byte_mismatch")
reject("user_visible_corruption", lambda d: witness(d, 1).update(
       user_page=damage(witness(d, 1)["user_page"], 0)), "independent_byte_mismatch")
reject("source_input_corruption", lambda d: witness(d, 0).update(
       input_page=damage(witness(d, 0)["input_page"], 2048)), "independent_byte_mismatch")
reject("digest_only", lambda d: witness(d, 1).update(
       final_copy=oracle.digest(bytes.fromhex(witness(d, 1)["final_copy"]))), "full_page_required")
reject("missing_final_copy", lambda d: witness(d, 1).update(final_copy=None), "full_page_required")
reject("missing_user_page", lambda d: witness(d, 1).update(user_page=None), "full_page_required")
reject("wrong_full_page", lambda d: witness(d, 1).update(
       final_copy=witness(d, 3)["final_copy"]), "independent_byte_mismatch")
reject("stale_seed", lambda d: d[1].update(seed="ef"*32), "plan_commitment")
reject("recommitted_wrong_seed", lambda d: d[1].update(seed="ef"*32),
       "independent_byte_mismatch", recommit=True)
reject("cross_run_nonce", lambda d: d[1].update(nonce="ef"*16), "plan_shape", recommit=True)
reject("stale_sidecar_wire", lambda d: d[4].update(wire_sha256="ff"*32),
       "sidecar_binding", rebind=False)
reject("stale_sidecar_scope", lambda d: d[4].update(scope_sha256="ff"*32),
       "sidecar_binding", rebind=False)
reject("omitted_workload_operation", lambda d: d[4]["operations"].pop(), "sidecar_count")
reject("foreign_original_token", lambda d: witness(d, 1).update(
       original=witness(d, 0)["original"]), "witness_ack_binding")
reject("clone_as_original", lambda d: witness(d, 1).update(
       original=witness(d, 1)["clone"]), "witness_ack_binding")
reject("stale_descriptor", lambda d: witness(d, 1).update(
       descriptor=witness(d, 0)["descriptor"]), "witness_ack_binding")
reject("stale_pin", lambda d: witness(d, 1).update(pin=witness(d, 3)["pin"]),
       "final_copy_pin_binding")
reject("copy_after_release", lambda d: witness(d, 1).update(
       copy_sequence=event(d, "pin_release")["sequence"]), "final_copy_pin_binding")
reject("clone_ack_as_user_result", lambda d: witness(d, 1).update(
       upper_sequence=event(d, "clone_endio", 1)["sequence"]), "witness_ack_binding")
reject("unexpected_user_error", lambda d: witness(d, 1).update(user_status=5), "witness_ack_binding")
reject("wrong_independent_codec", lambda d: d[1]["actions"][0].update(codec=2),
       "capture_reference", recommit=True)
reject("wrong_store", lambda d: d[1]["actions"][0].update(store=99),
       "capture_reference", recommit=True)
reject("wrong_read_generation", lambda d: d[1]["actions"][1].update(generation=2),
       "stale_read_reference", recommit=True)
reject("stale_read_version", lambda d: d[1]["actions"][1].update(version=2),
       "stale_read_reference", recommit=True)
reject("ordinary_fake_slot", lambda d: d[1]["actions"][5].update(slot=9),
       "noncapture_key_unsupported", recommit=True)
reject("boolean_token", lambda d: witness(d, 0).update(operation=True), "witness_ack_binding")
reject("nonzero_debt", lambda d: event(d, "cleanup").update(caps=1), "cleanup_debt")
reject("sticky_loss", lambda d: None, "recorder_loss", loss=4)
reject("error_masked_as_success", lambda d: witness(d, 7).update(user_status=0),
       "witness_ack_binding", data=error)
reject("error_unverified_input", lambda d: witness(d, 7).update(input_page=None),
       "full_page_required", data=error)
reject("unsupported_scope_size", lambda d: d[0].update(page_count=17), "plan_bounds")
# Mutate wire and independently rebind its digest; old parser must still refuse.
reject("missing_upper_ack", lambda d: d[2].remove(event(d, "upper_endio", 1)),
       "incomplete_lifetime")
reject("missing_fallback", lambda d: d[2].remove(event(d, "fallback")), "lower_before_claim")
reject("missing_cancel", lambda d: d[2].remove(event(d, "cancel")), "fallback_order")
reject("missing_discarded_preparation", lambda d: event(d, "preparation", 2).update(flags=2),
       "preparation_witness")
# Actual independently specified plans with stale source identities, not just
# mismatched sidecar. The unchanged legacy parser can accept these traces.
aliased = copy.deepcopy(actions)
aliased[2]["slot"] = aliased[3]["slot"] = 7
reject("aliased_slot", lambda d: None, "stale_or_aliased_store", data=fixture(aliased))
reused = copy.deepcopy(actions)
reused[4]["store"] = 11
reject("reused_store", lambda d: None, "stale_or_aliased_store", data=fixture(reused))
changed_area = copy.deepcopy(actions)
changed_area[2]["area_epoch"] = changed_area[3]["area_epoch"] = 99
reject("cross_area", lambda d: None, "scope_area_or_slot", data=fixture(changed_area))
unread = [actions[0], actions[2], actions[3], actions[5], actions[6]]
reject("unread_typed_page", lambda d: None, "missing_independent_read", data=fixture(unread))
# CLI tests use only ephemeral regular files; no sidecar or plan uploaded.
with tempfile.TemporaryDirectory() as directory:
    directory = Path(directory)
    scope, plan, rows, high, sidecar = clean
    paths = [directory / name for name in ("scope", "plan", "wire", "sidecar")]
    for item, content in zip(paths, (oracle.canonical(scope), oracle.canonical(plan),
                                    pack(scope, rows, high), oracle.canonical(sidecar))):
        item.write_bytes(content)
    def cli(expected, *args):
        global checks
        proc = subprocess.run([sys.executable, "-B", str(path), source,
                               *map(str, args or paths)], capture_output=True, check=False)
        result = json.loads(proc.stdout)
        assert result.get("reason", result["status"]) == expected, result
        assert proc.returncode == (0 if expected == "CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY" else 2)
        assert not proc.stderr and seed not in proc.stdout.decode() and nonce not in proc.stdout.decode()
        checks += 1
    cli("CONSISTENT_PRIVATE_BYTE_WITNESSES_ONLY")
    for item, content in zip(paths, (oracle.canonical(error[0]), oracle.canonical(error[1]),
                                    pack(error[0], error[2], error[3]), oracle.canonical(error[4]))):
        item.write_bytes(content)
    cli("OBSERVED_CLAIMED_ERROR_BLOCKED")
    paths[3].write_bytes(b'{"schema":1,"schema":2}')
    cli("scope_duplicate")
    paths[3].write_bytes(b"x" * (oracle.MAX_SIDECAR_BYTES + 1))
    cli("file_bounds")
    link = directory / "link"
    link.symlink_to(paths[0])
    cli("regular_file_required", link, *paths[1:])
    cli("invalid_input", directory / "missing", *paths[1:])
print(json.dumps(dict(checks=checks, exhaustive_byte_mutations=4096,
                      clean_operations=7, clean_pages=8, clean_bytes=32768,
                      error_operations=8, error_pages=9, error_bytes=36864,
                      native_capture=False, auth=0), sort_keys=True))
