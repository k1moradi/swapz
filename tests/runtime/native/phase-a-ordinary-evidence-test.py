#!/usr/bin/env python3
"""Synthetic independent expected pages and capture claims; never native evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[2] / "tools/phase-a-ordinary-evidence.py"
spec = importlib.util.spec_from_file_location("ordinary", PATH)
ordinary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ordinary)


def fixture(count=2):
    # Expected bytes are generated from a deterministic independent workload,
    # not extracted from captured bytes or a captured digest.
    scope = dict(source="1" * 40, run_nonce="2" * 32, workload_sha256="3" * 64,
                 area_epoch=41, swap_type=0, target=43)
    pages = [dict(logical=n, slot=n+100, store=n+200, generation=n+300,
                  cookie=n+400, expected_page=bytes((n*17+i*3) % 256
                                                    for i in range(4096)).hex())
             for n in range(1, count+1)]
    manifest = dict(schema="swapz-ordinary-manifest", version=1, scope=scope, pages=pages)
    area = dict(area_epoch=41, swap_type=0, target=43)
    events = []

    def emit(stage, **fields):
        events.append(dict(seq=len(events)+1, stage=stage, **area, **fields))
        return len(events)

    for n in range(1, count+1):
        # Separate fixture emitter: independently specified actual-page claim.
        observed = bytes((3*i+17*n) & 255 for i in range(4096)).hex()
        key = dict(logical=n, slot=100+n, store=200+n, generation=300+n, cookie=400+n)
        write = dict(operation=1000+n*10, bio=1001+n*10, dm=1002+n*10)
        read = dict(operation=1004+n*10, bio=1005+n*10, dm=1006+n*10)
        emit("stored", **key, status=0)
        emit("natural_evict", **key, cause="native_reclaim")
        emit("write_mm", **key, operation=write["operation"])
        emit("write_bio", **key, operation=write["operation"], bio=write["bio"],
             logical_bytes=4096, page=observed)
        emit("write_dm", **key, **write)
        emit("write_lower_submit", **key, **write, lower=1003+n*10, bytes=8192)
        emit("write_lower_complete", **key, **write, lower=1003+n*10, bytes=8192, status=0)
        commit = emit("write_commit", **key, **write, logical_bytes=4096, status=0)
        emit("write_upper", **key, **write, logical_bytes=4096, status=0)
        emit("evict_retired", **key, operation=write["operation"], status=0)
        emit("read_mm", **key, operation=read["operation"], commit_seq=commit, route="ordinary_backing")
        emit("read_bio", **key, operation=read["operation"], bio=read["bio"], logical_bytes=4096)
        emit("read_dm", **key, **read)
        emit("read_lower_submit", **key, **read, lower=1007+n*10, bytes=4096)
        emit("read_lower_complete", **key, **read, lower=1007+n*10, bytes=4096, status=0)
        emit("read_upper", **key, **read, logical_bytes=4096, status=0, page=observed)
        emit("read_user", **key, operation=read["operation"], bio=read["bio"],
             logical_bytes=4096, status=0, page=observed)
    cleanup = emit("cleanup", receipt=9991, issuer="controller_census", status=0,
                   maps=0, bios=0, pins=0, reservations=0, stores=0, caps=0, tickets=0, quarantines=0)
    emit("dtr", receipt=9992, cleanup_seq=cleanup, issuer="dm_target_dtr", status=0)
    return manifest, dict(schema="swapz-ordinary-capture", version=1, scope=copy.deepcopy(scope),
                          loss=0, events=events)


class OrdinaryTests(unittest.TestCase):
    def assert_gates(self, result):
        for key, value in ordinary.GATES.items():
            self.assertEqual(result[key], value)

    def test_synthetic_only(self):
        for count in (1, 2, 16):
            with self.subTest(count=count):
                result = ordinary.validate(*fixture(count))
                self.assert_gates(result)
                self.assertEqual(result["status"], "CONSISTENT_ORDINARY_CORRELATION_ONLY")
                self.assertEqual(result["operations"], 2*count)
                self.assertEqual(result["bytes_compared"], 3*4096*count)

    def test_mutated_events(self):
        cases = [
            ("stored", "status", 1, "failed_stage"),
            ("stored", "stage", "initial_rejection", "event_order"),
            ("natural_evict", "cause", "forced", "not_natural_eviction"),
            ("write_mm", "operation", True, "duplicate_attribution"),
            ("write_bio", "logical_bytes", 4095, "logical_completion"),
            ("write_bio", "page", "00"*4096, "independent_byte_mismatch"),
            ("write_dm", "bio", 1, "operation_binding"),
            ("write_lower_complete", "bytes", 4096, "lower_completion"),
            ("write_lower_complete", "status", 5, "failed_stage"),
            ("write_commit", "generation", 1, "stale_page_identity"),
            ("write_commit", "status", 1, "failed_stage"),
            ("write_upper", "logical_bytes", 0, "logical_completion"),
            ("evict_retired", "status", 1, "failed_stage"),
            ("read_mm", "commit_seq", 1, "read_commit_binding"),
            ("read_mm", "route", "typed", "read_commit_binding"),
            ("read_bio", "slot", 1, "stale_page_identity"),
            ("read_dm", "store", 1, "stale_page_identity"),
            ("read_dm", "cookie", 1, "stale_page_identity"),
            ("read_lower_submit", "bytes", 511, "lower_length"),
            ("read_lower_complete", "status", 2, "failed_stage"),
            ("read_lower_complete", "bytes", 2048, "lower_completion"),
            ("read_upper", "page", "00", "full_page_required"),
            ("read_upper", "page", "00"*4097, "full_page_required"),
            ("read_upper", "status", 1, "failed_stage"),
            ("read_user", "area_epoch", 1, "event_scope"),
            ("read_user", "swap_type", False, "event_scope"),
            ("read_user", "page", "00"*4096, "independent_byte_mismatch"),
            ("cleanup", "maps", 1, "cleanup_debt"),
            ("cleanup", "issuer", "dtr", "cleanup_debt"),
            ("dtr", "cleanup_seq", 1, "dtr_binding"),
            ("dtr", "receipt", 9991, "duplicate_attribution"),
            ("dtr", "status", 1, "dtr_binding"),
        ]
        for stage, field, value, reason in cases:
            with self.subTest(stage=stage, field=field, reason=reason):
                manifest, capture = fixture()
                row = next(row for row in capture["events"] if row["stage"] == stage)
                row[field] = value
                with self.assertRaisesRegex(ordinary.Invalid, "^" + reason + "$"):
                    ordinary.validate(manifest, capture)

    def test_missing_duplicate_and_reordered_events(self):
        for index in range(len(fixture()[1]["events"])):
            for action in ("missing", "duplicate", "reorder"):
                with self.subTest(index=index, action=action):
                    manifest, capture = fixture()
                    events = capture["events"]
                    if action == "missing":
                        events.pop(index)
                    elif action == "duplicate":
                        events.insert(index, copy.deepcopy(events[index]))
                    else:
                        other = (index+1) % len(events)
                        events[index], events[other] = events[other], events[index]
                    # Even an attacker who renumbers all events cannot repair semantics.
                    for seq, row in enumerate(events, 1):
                        row["seq"] = seq
                    with self.assertRaises(ordinary.Invalid):
                        ordinary.validate(manifest, capture)

    def test_scope_loss_replay_and_shape(self):
        for key, value in (("source", "a"*40), ("run_nonce", "b"*32),
                           ("workload_sha256", "c"*64), ("area_epoch", 2), ("swap_type", 1), ("target", 2)):
            with self.subTest(key=key):
                manifest, capture = fixture()
                capture["scope"][key] = value
                with self.assertRaisesRegex(ordinary.Invalid, "^stale_scope$"):
                    ordinary.validate(manifest, capture)
        for loss in (1, False, -1):
            manifest, capture = fixture()
            capture["loss"] = loss
            with self.assertRaisesRegex(ordinary.Invalid, "^capture_loss$"):
                ordinary.validate(manifest, capture)
        manifest, capture = fixture()
        capture["events"][3]["typed"] = False
        with self.assertRaisesRegex(ordinary.Invalid, "^event_shape$"):
            ordinary.validate(manifest, capture)
        manifest, capture = fixture()
        capture["events"][17:34] = copy.deepcopy(capture["events"][:17])
        for seq, row in enumerate(capture["events"], 1):
            row["seq"] = seq
        with self.assertRaisesRegex(ordinary.Invalid, "^page_coverage$"):
            ordinary.validate(manifest, capture)
        manifest, capture = fixture()
        capture["events"][19]["operation"] = capture["events"][2]["operation"]
        with self.assertRaisesRegex(ordinary.Invalid, "^duplicate_attribution$"):
            ordinary.validate(manifest, capture)

    def test_bounds_and_json(self):
        for count in (0, 17):
            with self.assertRaisesRegex(ordinary.Invalid, "^page_bounds$"):
                ordinary.validate(*fixture(count))
        for limit in (ordinary.MAX_MANIFEST_BYTES, ordinary.MAX_CAPTURE_BYTES):
            self.assertEqual(ordinary.parse(b"{}" + b" "*(limit-2), limit), {})
            for raw in (b"", b"{", b"{}" + b" "*(limit-1)):
                with self.assertRaisesRegex(ordinary.Invalid, "^input_bounds$"):
                    ordinary.parse(raw, limit)
        for raw in (b'{"a":1,"a":2}', b'{"nested":{"a":1,"a":2}}', b'{"a":NaN}',
                    b'{"a":999999999999999999999999999999}', b'{"a":', b'\xff\xff'):
            with self.assertRaises(ValueError):
                ordinary.parse(raw, 1000)
        manifest, capture = fixture(16)
        capture["events"].append(copy.deepcopy(capture["events"][-1]))
        with self.assertRaisesRegex(ordinary.Invalid, "^event_bounds$"):
            ordinary.validate(manifest, capture)

    def test_swapped_pages_and_manifest_aliases(self):
        manifest, capture = fixture()
        capture["events"][15]["page"] = manifest["pages"][1]["expected_page"]
        with self.assertRaisesRegex(ordinary.Invalid, "^independent_byte_mismatch$"):
            ordinary.validate(manifest, capture)
        for field in ("slot", "store", "cookie", "logical"):
            manifest, capture = fixture()
            manifest["pages"][1][field] = manifest["pages"][0][field]
            with self.assertRaises(ordinary.Invalid):
                ordinary.validate(manifest, capture)
        manifest, capture = fixture()
        manifest["scope"]["run_nonce"] = "0"*32
        with self.assertRaisesRegex(ordinary.Invalid, "^scope_digest$"):
            ordinary.validate(manifest, capture)

    def test_cli_private_inputs_and_redacted_first_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            manifest_path, capture_path = directory/"manifest", directory/"capture"
            manifest, capture = fixture()
            for path, obj in ((manifest_path, manifest), (capture_path, capture)):
                path.touch(mode=0o600)
                path.write_text(json.dumps(obj), encoding="utf-8")

            def run(expected, first=None, paths=(manifest_path, capture_path)):
                result = subprocess.run([sys.executable, "-B", str(PATH), *map(str, paths)],
                                        capture_output=True, check=False)
                self.assertEqual(result.returncode, expected)
                self.assertEqual(result.stderr, b"")
                output = json.loads(result.stdout)
                self.assert_gates(output)
                self.assertEqual(output.get("reason"), first)
                for secret in (manifest["scope"]["run_nonce"], manifest["pages"][0]["expected_page"],
                               str(directory)):
                    self.assertNotIn(secret.encode(), result.stdout)

            run(0)
            capture["events"][0]["status"] = 1
            capture["events"][15]["page"] = "bad"
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            run(2, "failed_stage")
            capture_path.write_text('{"a":1,"a":2}', encoding="utf-8")
            run(2, "duplicate_json_key")
            capture_path.write_bytes(b"x"*(ordinary.MAX_CAPTURE_BYTES+1))
            run(2, "input_bounds")
            capture_path.chmod(0o644)
            run(2, "private_regular_file_required")
            capture_path.chmod(0o600)
            link = directory/"link"
            link.symlink_to(capture_path)
            run(2, "private_regular_file_required", (manifest_path, link))
            link.unlink()
            link.hardlink_to(capture_path)
            run(2, "private_regular_file_required")
            link.unlink()
            directory.chmod(0o755)
            run(2, "private_directory_required")
            directory.chmod(0o700)


if __name__ == "__main__":
    unittest.main()
