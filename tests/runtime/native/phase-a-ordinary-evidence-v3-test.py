#!/usr/bin/env python3
"""Synthetic evidence only; independent frozen v2 fixture, never native capture."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/phase-a-ordinary-evidence-v3.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ordinary = load("ordinary_interleaved", PATH)
serial = load("ordinary_serial_test", Path(__file__).with_name("phase-a-ordinary-evidence-test.py"))


def renumber(events):
    """Fixture-side ordinals only. Do not repair causal references in mutants."""
    for ordinal, row in enumerate(events, 1):
        row["seq"] = ordinal


def fixture(count=3, schedule="round_robin", seed=0):
    manifest, capture = serial.fixture(count)
    manifest["version"] = capture["version"] = 3
    groups = [capture["events"][17*n:17*(n+1)] for n in range(count)]
    if schedule == "serial":
        rows = [row for group in reversed(groups) for row in group]
    elif schedule == "round_robin":
        rows = [group[stage] for stage in range(17) for group in reversed(groups)]
    elif schedule == "mixed":
        # One complete page while another is awaiting lower completion.
        rows = groups[0][:6] + groups[-1] + groups[0][6:] if count > 1 else groups[0]
        rows += [row for group in groups[1:-1] for row in group]
    else:
        rng = random.Random(seed)
        rows = []
        while groups:
            index = rng.randrange(len(groups))
            rows.append(groups[index].pop(0))
            if not groups[index]:
                groups.pop(index)
    rows += capture["events"][-2:]
    renumber(rows)
    publications = {}
    for row in rows:
        if row["stage"] == "write_commit":
            row["persistence"] = "UNPROVEN"
            publications[row["logical"]] = row["seq"]
        elif row["stage"] == "read_mm":
            row["commit_seq"] = publications[row["logical"]]
        elif row["stage"] == "dtr":
            row["cleanup_seq"] = rows[-2]["seq"]
    capture["events"] = rows
    return manifest, capture


def event(capture, stage, logical=None):
    return next(row for row in capture["events"] if row["stage"] == stage and
                (logical is None or row.get("logical") == logical))


def rehash(manifest, capture):
    digest = hashlib.sha256(json.dumps(manifest["plan"], sort_keys=True, separators=(",", ":"))
                            .encode("utf-8")).hexdigest()
    for scope in [manifest["scope"], capture["scope"], *(row["scope"] for row in manifest["witnesses"])]:
        scope["workload_sha256"] = digest


class InterleavedTests(unittest.TestCase):
    def gates(self, result):
        for key, value in dict(auth=0, phase_a="BLOCKED", native_qualification="BLOCKED",
                               observation="UNKNOWN", persistence="UNPROVEN", durable_qualification="BLOCKED",
                               logical_slot_binding="UNVERIFIED", compressed_handoff=False, forced_raw=False,
                               import_enabled=False, physical="NO_GO", authenticated=False,
                               actual_route="ORDINARY").items():
            self.assertEqual(result[key], value)

    def accept(self, pair, count):
        before = copy.deepcopy(pair)
        result = ordinary.validate(*pair)
        self.gates(result)
        self.assertEqual(result["status"], "CONSISTENT_INTERLEAVED_ORDINARY_CORRELATION_ONLY")
        self.assertEqual((result["pages"], result["operations"], result["bytes_compared"]),
                         (count, 2*count, 3*4096*count))
        self.assertTrue(pair == before, "validator modified capture")

    def reject(self, pair, reason=None):
        with self.assertRaises(ordinary.Invalid) as error:
            ordinary.validate(*pair)
        if reason is not None:
            self.assertEqual(str(error.exception), reason)

    def test_valid_interleavings(self):
        for count in (1, 2, 3, 16):
            for schedule in ("serial", "round_robin", "mixed", "random"):
                with self.subTest(count=count, schedule=schedule):
                    self.accept(fixture(count, schedule), count)
        for seed in range(24):
            self.accept(fixture(16, "random", seed), 16)
        manifest, capture = fixture(16)
        self.assertEqual(len(capture["events"]), 274)
        self.assertEqual(manifest["plan"]["max_operations"], 64)
        manifest["plan"]["max_operations"] = 32
        rehash(manifest, capture)
        self.accept((manifest, capture), 16)

    def test_every_same_page_boundary_and_global_order(self):
        original = fixture()
        for logical in (1, 2, 3):
            for boundary in range(16):
                with self.subTest(logical=logical, boundary=boundary):
                    pair = copy.deepcopy(original)
                    rows = pair[1]["events"]
                    indices = [i for i, row in enumerate(rows) if row.get("logical") == logical]
                    first, second = indices[boundary:boundary+2]
                    rows[first], rows[second] = rows[second], rows[first]
                    renumber(rows)
                    self.reject(pair, "event_order")
        for index in range(len(original[1]["events"])):
            for action in ("gap", "duplicate_ordinal", "remove", "duplicate"):
                with self.subTest(index=index, action=action):
                    pair = copy.deepcopy(original)
                    rows = pair[1]["events"]
                    if action == "gap":
                        rows[index]["seq"] += 1
                    elif action == "duplicate_ordinal":
                        rows[index]["seq"] -= 1
                    elif action == "remove":
                        rows.pop(index)
                        renumber(rows)
                    else:
                        rows.insert(index, copy.deepcopy(rows[index]))
                        renumber(rows)
                    self.reject(pair)

    def test_every_stage_shape_and_identity(self):
        original = fixture(2)
        for index, row in enumerate(original[1]["events"]):
            for field in row:
                pair = copy.deepcopy(original)
                del pair[1]["events"][index][field]
                self.reject(pair)
            pair = copy.deepcopy(original)
            pair[1]["events"][index]["unexpected"] = 0
            self.reject(pair, "event_shape")
            for field in ("logical", "slot", "store", "generation", "cookie", "target", "area_epoch", "swap_type"):
                if field not in row:
                    continue
                pair = copy.deepcopy(original)
                pair[1]["events"][index][field] = True
                self.reject(pair)
            if "status" in row:
                pair = copy.deepcopy(original)
                pair[1]["events"][index]["status"] = 1
                self.reject(pair)

    def test_cross_page_and_cross_role_tokens(self):
        original = fixture(2)
        first_use = [(f"{direction}_{stage}", field) for direction in ("write", "read")
                     for stage, field in (("mm", "operation"), ("bio", "bio"), ("dm", "dm"),
                                          ("lower_submit", "lower"))]
        # Round-robin fixture visits logical 2 first; all already issued tokens
        # (including across roles/directions) must be globally unique.
        for stage, field in first_use:
            for earlier_stage, earlier_field in first_use:
                if first_use.index((earlier_stage, earlier_field)) > first_use.index((stage, field)):
                    continue
                pair = copy.deepcopy(original)
                event(pair[1], stage, 1)[field] = event(pair[1], earlier_stage, 2)[earlier_field]
                self.reject(pair, "duplicate_attribution")
        for index, row in enumerate(original[1]["events"]):
            if row.get("logical") != 1:
                continue
            for field in ("operation", "bio", "dm", "lower", "slot", "store", "generation", "cookie"):
                if field not in row or (row["stage"], field) in first_use:
                    continue
                pair = copy.deepcopy(original)
                pair[1]["events"][index][field] = event(pair[1], row["stage"], 2)[field]
                self.reject(pair, "operation_binding" if field in ("operation", "bio", "dm", "lower")
                            else "stale_page_identity")
        for terminal in ("cleanup", "dtr"):
            for stage, field in first_use:
                pair = copy.deepcopy(original)
                event(pair[1], terminal)["receipt"] = event(pair[1], stage, 2)[field]
                self.reject(pair, "duplicate_attribution")
        pair = copy.deepcopy(original)
        event(pair[1], "dtr")["receipt"] = event(pair[1], "cleanup")["receipt"]
        self.reject(pair, "duplicate_attribution")

    def test_causal_bytes_durability_and_lengths(self):
        original = fixture(2)
        for logical in (1, 2):
            for stage, field, value, reason in (
                ("write_commit", "persistence", "PROVEN", "persistence_unproven_required"),
                ("write_commit", "persistence", False, "persistence_unproven_required"),
                ("read_mm", "commit_seq", event(original[1], "write_commit", 3-logical)["seq"], "read_commit_binding"),
                ("read_mm", "commit_seq", event(original[1], "read_upper", logical)["seq"], "read_commit_binding"),
                ("read_mm", "commit_seq", True, "read_commit_binding"),
                ("read_mm", "route", "typed", "read_commit_binding"),
                ("natural_evict", "cause", "forced", "not_natural_eviction"),
                ("write_bio", "logical_bytes", 4095, "logical_completion"),
                ("read_user", "logical_bytes", True, "logical_completion"),
                ("write_lower_complete", "bytes", 4096, "lower_completion"),
                ("read_lower_complete", "bytes", 8192, "lower_completion"),
                ("read_lower_submit", "bytes", 513, "lower_length"),
                ("write_lower_submit", "bytes", 16896, "lower_length"),
            ):
                pair = copy.deepcopy(original)
                event(pair[1], stage, logical)[field] = value
                self.reject(pair, reason)
            for stage in ("write_bio", "read_upper", "read_user"):
                for value, reason in (("00", "full_page_required"), ("AA"*4096, "full_page_required"),
                                      (event(original[1], stage, 3-logical)["page"], "independent_byte_mismatch")):
                    pair = copy.deepcopy(original)
                    event(pair[1], stage, logical)["page"] = value
                    self.reject(pair, reason)

    def test_terminal_and_scope(self):
        original = fixture(2)
        for field in ("maps", "bios", "pins", "reservations", "stores", "caps", "tickets", "quarantines", "status"):
            for value in (1, False):
                pair = copy.deepcopy(original)
                event(pair[1], "cleanup")[field] = value
                self.reject(pair, "cleanup_debt")
        for stage in ("cleanup", "dtr"):
            pair = copy.deepcopy(original)
            rows = pair[1]["events"]
            rows.insert(1, rows.pop(-2 if stage == "cleanup" else -1))
            renumber(rows)
            self.reject(pair, "early_or_duplicate_cleanup" if stage == "cleanup" else "early_dtr")
        for field in original[0]["scope"]:
            pair = copy.deepcopy(original)
            pair[1]["scope"][field] = ("a"*len(pair[0]["scope"][field]) if type(pair[0]["scope"][field]) is str
                                       else pair[0]["scope"][field]+1)
            self.reject(pair, "stale_scope")
        for loss in (1, False, -1, 0.0):
            pair = copy.deepcopy(original)
            pair[1]["loss"] = loss
            self.reject(pair, "capture_loss")
        for stage, field, value in (("cleanup", "issuer", "other"), ("dtr", "issuer", "other"),
                                    ("dtr", "cleanup_seq", 1), ("dtr", "status", False)):
            pair = copy.deepcopy(original)
            event(pair[1], stage)[field] = value
            self.reject(pair)

    def test_versions_plan_witness_and_equal_bytes(self):
        self.reject(serial.fixture(), "schema_version")
        for position in (0, 1):
            for version in (1, 2, 4, True, 3.0):
                pair = fixture()
                pair[position]["version"] = version
                self.reject(pair, "schema_version")
        pair = fixture()
        with self.assertRaises(serial.ordinary.Invalid):
            serial.ordinary.validate(*pair)
        pair[0]["plan"]["version"] = 3
        rehash(*pair)
        self.reject(pair, "plan_version")
        for max_pages, max_operations in ((17, 64), (16, 65), (False, 64), (16, 5)):
            pair = fixture()
            pair[0]["plan"].update(max_pages=max_pages, max_operations=max_operations)
            rehash(*pair)
            self.reject(pair)
        pair = fixture(17)
        self.reject(pair, "page_bounds")
        pair = fixture(16)
        pair[1]["events"].append(copy.deepcopy(pair[1]["events"][-1]))
        self.reject(pair, "event_bounds")
        for mutation in ("digest", "order", "witness_order", "witness_scope", "witness_cookie"):
            pair = fixture()
            if mutation == "digest":
                pair[0]["plan"]["pages"][0]["expected_page"] = "00"*4096
            elif mutation == "order":
                pair[0]["plan"]["pages"].reverse()
                rehash(*pair)
            elif mutation == "witness_order":
                pair[0]["witnesses"].reverse()
            elif mutation == "witness_scope":
                pair[0]["witnesses"][0]["scope"]["target"] += 1
            else:
                pair[0]["witnesses"][0]["cookie"] = pair[0]["witnesses"][1]["cookie"]
            self.reject(pair)
        # Equal bytes cannot distinguish actual mappings. Even coherent swapped
        # hypothetical identities are only structurally consistent, never binding.
        pair = fixture(2)
        value = pair[0]["plan"]["pages"][0]["expected_page"]
        pair[0]["plan"]["pages"][1]["expected_page"] = value
        for row in pair[1]["events"]:
            if "page" in row:
                row["page"] = value
        rehash(*pair)
        self.accept(pair, 2)
        for field in ("slot", "store", "generation", "cookie"):
            a, b = (row[field] for row in pair[0]["witnesses"])
            pair[0]["witnesses"][0][field], pair[0]["witnesses"][1][field] = b, a
            for row in pair[1]["events"]:
                if field in row:
                    row[field] = b if row["logical"] == 1 else a
        self.accept(pair, 2)
        event(pair[1], "read_user", 1)["cookie"] = a
        self.reject(pair, "stale_page_identity")

    def test_private_cli_redaction_and_input_limits(self):
        manifest, capture = fixture(16)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "manifest", root / "capture"]
            raw = [json.dumps(value).encode() for value in (manifest, capture)]
            for path, data in zip(paths, raw, strict=True):
                path.write_bytes(data)
                path.chmod(0o600)

            def run(code, reason=None, arguments=paths):
                proc = subprocess.run([sys.executable, "-B", str(PATH), *map(str, arguments)],
                                      capture_output=True, check=False, timeout=10)
                self.assertEqual(proc.returncode, code)
                self.assertFalse(proc.stderr)
                result = json.loads(proc.stdout)
                self.gates(result)
                self.assertEqual(result.get("reason"), reason)
                for secret in (str(root), manifest["scope"]["source"], manifest["scope"]["run_nonce"],
                               manifest["scope"]["workload_sha256"], manifest["plan"]["pages"][0]["expected_page"]):
                    self.assertFalse(secret.encode() in proc.stdout, "private value leaked")
                return result

            self.assertEqual(run(0)["operations"], 32)
            for index, limit in enumerate((256*1024, 1024*1024)):
                paths[index].write_bytes(raw[index] + b" "*(limit-len(raw[index])))
                run(0)
                with paths[index].open("ab") as stream:
                    stream.write(b" ")
                run(2, "input_bounds")
                paths[index].write_bytes(raw[index])
            for data, reason in ((b'{"version":3,"version":3}', "duplicate_json_key"),
                                 (b'{"version":NaN}', "invalid_json_constant"),
                                 (b'{"version":Infinity}', "invalid_json_constant"),
                                 (b'{"version":1234567890123456789012}', "integer_bounds"),
                                 (b'{', "input_bounds"), (b'\xff\xff', "invalid_input")):
                paths[0].write_bytes(data)
                run(2, reason)
            paths[0].write_bytes(raw[0])
            paths[0].chmod(0o644)
            run(2, "private_regular_file_required")
            paths[0].chmod(0o600)
            link = root / "link"
            link.symlink_to(paths[0])
            run(2, "private_regular_file_required", [link, paths[1]])
            link.unlink()
            link.hardlink_to(paths[0])
            run(2, "private_regular_file_required")
            link.unlink()
            import os
            os.mkfifo(link, 0o600)
            run(2, "private_regular_file_required", [link, paths[1]])
            root.chmod(0o755)
            run(2, "private_directory_required")
            root.chmod(0o700)
            run(2, "arguments", [])
            # First semantic error survives later malformed event.
            event(capture, "stored", 2)["status"] = 1
            event(capture, "dtr")["receipt"] = "private"*100
            paths[1].write_text(json.dumps(capture), encoding="utf-8")
            run(2, "failed_stage")


if __name__ == "__main__":
    unittest.main()
