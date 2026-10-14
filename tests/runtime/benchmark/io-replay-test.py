#!/usr/bin/env python3
"""Rootless proof that both labels replay one exact immutable I/O plan.

This does NOT load V3 module: same regular-file replay code tests only
the trace contract, oracle, safety guard and fail-closed pair comparator.
"""
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PAGE = 4096
SCRIPT = Path(__file__).with_name("io-replay.py")


class PairReplayContract(unittest.TestCase):
    def run_cmd(self, *args, success=True):
        run = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                             capture_output=True, text=True, timeout=30)
        if success and run.returncode:
            self.fail(f"command {args}: rc={run.returncode}\n{run.stdout}\n{run.stderr}")
        if not success:
            self.assertNotEqual(run.returncode, 0, repr(args))
        return run

    def test_pair_exact_bytes_and_ordered_wave_oracle(self):
        for layout in ("disjoint", "same-region"):
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                fixture = root / "fixture.bin"
                rng = random.Random(119)
                pages = [
                    bytes([index]) * PAGE if index % 3 != 1
                    else rng.randbytes(PAGE) for index in range(16)
                ]
                fixture.write_bytes(b"".join(pages))
                plan = root / "plan"
                reader_start = 32 if layout == "disjoint" else 0
                self.run_cmd("prepare", "--fixture", fixture,
                             "--output-dir", plan, "--seed", "0xfeed123",
                             "--logical-pages", 64, "--writer-pages", 16,
                             "--reader-start", reader_start,
                             "--reader-pages", 16, "--layout", layout,
                             "--qd", 4, "--read-pct", 50,
                             "--warmup-ops", 32, "--measure-ops", 128,
                             "--iops", 0)
                manifest = json.loads((plan / "manifest.json").read_text())
                self.assertEqual(manifest["fixture_pages"], 16)
                self.assertEqual(manifest["measure_ops"], 128)
                reports = []
                for candidate in ("off", "v3"):
                    path = root / f"swapz-replay-{candidate}.bin"
                    with path.open("wb") as handle:
                        handle.truncate(64 * PAGE)
                    out = root / f"{candidate}.json"
                    self.run_cmd("run", "--fixture", fixture,
                                 "--trace", plan / "trace.jsonl",
                                 "--manifest", plan / "manifest.json",
                                 "--candidate", candidate,
                                 "--source-sha", "rootless-test-not-a-module",
                                 "--device", path,
                                 "--result", out, "--regular-file-test")
                    self.assertTrue(out.is_file())
                    reports.append(out)
                compare = self.run_cmd("compare", "--reports", *reports)
                result = json.loads(compare.stdout)
                self.assertEqual(result["verdict"], "PASS_IDENTICAL_LOGICAL_INPUT")
                self.assertEqual(result["fixture_sha256"], manifest["fixture_sha256"])
                self.assertEqual(result["trace_sha256"], manifest["trace_sha256"])
                self.assertEqual(len(result["results"]), 2)
                expected = manifest["expected_post_sha256"]
                for report_path in reports:
                    record = json.loads(report_path.read_text())
                    self.assertEqual(record["verified_post_sha256"], expected)
                    self.assertEqual(record["write_ops"] + record["read_ops"], 128)
                    self.assertEqual(record["warmup_ops"], 32)
                    self.assertEqual(record["verified_pages"], 64)
                    self.assertEqual(record["verdict"], "PASS")
                # Fail-closed: altered trace provenance makes pair invalid.
                tampered = json.loads(reports[0].read_text())
                tampered["write_payload_stream_sha256"] = "0" * 64
                reports[0].write_text(json.dumps(tampered) + "\n")
                self.run_cmd("compare", "--reports", *reports, success=False)
                # Fail-closed: altered fixture bytes are rejected before I/O.
                fixture.write_bytes(fixture.read_bytes()[:-PAGE] +
                                    b"Z" * PAGE)
                forbidden = root / "swapz-replay-refused.bin"
                with forbidden.open("wb") as handle:
                    handle.truncate(64 * PAGE)
                self.run_cmd("run", "--fixture", fixture,
                             "--trace", plan / "trace.jsonl",
                             "--manifest", plan / "manifest.json",
                             "--candidate", "off",
                             "--source-sha", "rootless-test",
                             "--device", forbidden,
                             "--result", root / "refused.json",
                             "--regular-file-test", success=False)
                self.assertFalse((root / "refused.json").exists())

    def test_owned_nullblk_modern_legacy_and_invalid_identities(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_replay", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_root = root / "config"
            block_root = root / "block"
            sysdev_root = root / "devblock"
            config_name = "nullb-swapz-0123456789abcdef"
            conf = config_root / config_name
            conf.mkdir(parents=True)
            sysdev_root.mkdir()
            for name, value in (("index", "7"), ("memory_backed", "1"),
                                ("power", "1")):
                (conf / name).write_text(value + "\n")
            proc = root / "devices"
            proc.write_text("Character devices:\n1 mem\nBlock devices:\n251 nullb\n")
            modern = block_root / config_name
            legacy = block_root / "nullb7"
            modern.mkdir(parents=True)
            legacy.mkdir(parents=True)
            (modern / "dev").write_text("251:7\n")
            marker = sysdev_root / "251:7"
            marker.symlink_to(modern, target_is_directory=True)

            def resolve(dev="251:7", name=config_name):
                return mod.resolve_owned_nullblk(
                    name, dev, config_root, block_root, sysdev_root, proc
                )

            self.assertEqual(resolve(), (config_name, "251:7"))
            (legacy / "dev").write_text("251:7\n")
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                resolve()
            (modern / "dev").unlink()
            marker.unlink()
            marker.symlink_to(legacy, target_is_directory=True)
            self.assertEqual(resolve(), ("nullb7", "251:7"))
            with self.assertRaisesRegex(ValueError, "non-owned"):
                resolve(name="nullb_swapz_old")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                resolve(dev="251:8")
            (legacy / "dev").write_text("252:7\n")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                resolve()
            (legacy / "dev").write_text("251:7\n")
            (conf / "memory_backed").write_text("0\n")
            with self.assertRaisesRegex(ValueError, "RAM-backed"):
                resolve()
            (conf / "memory_backed").write_text("1\n")
            (conf / "index").write_text("07\n")
            with self.assertRaisesRegex(ValueError, "index"):
                resolve()
            (conf / "index").write_text("7\n")
            marker.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                resolve()
            (legacy / "dev").unlink()
            with self.assertRaisesRegex(ValueError, "missing"):
                resolve()

    def test_exact_v3_table_accepts_only_owned_nonfaulting_backing(self):
        import importlib.util
        from unittest.mock import patch
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("swapz_replay_table", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lower = "251:7"
        name = "nullb-swapz-0123456789abcdef"
        tokens = f"0 32768 swapz3 {lower} 0 64 0 2 0 0 1 0"
        self.assertEqual(module.validate_v3_table(tokens, 4096, lower, name)["window"], 64)
        fake_block = SimpleNamespace(st_mode=__import__("stat").S_IFBLK,
                                     st_rdev=os.makedev(251, 7))
        with patch.object(module.Path, "stat", return_value=fake_block):
            path_table = tokens.replace(lower, "/dev/" + name)
            self.assertEqual(module.validate_v3_table(
                path_table, 4096, lower, name
            )["lower_bulk"], 1)
        for broken in (
            tokens.replace("251:7", "251:8"),
            tokens.replace("251:7", "/dev/sda1"),
            tokens.replace("32768", "32760"),
            tokens.replace("swapz3", "linear"),
            tokens + "\n" + tokens,
            tokens + " 0",
            tokens.replace(" 0 64 0 2 0 0 1 0", " 0 64 0 2 0 1 1 0"),
            tokens.replace(" 0 64 0 2 0 0 1 0", " 0 64 0 2 0 0 1 1"),
        ):
            with self.subTest(table=broken), self.assertRaises(ValueError):
                module.validate_v3_table(broken, 4096, lower, name)

    def test_loaded_pair_qualification_requires_distinct_backing_and_rate(self):
        import contextlib
        import importlib.util
        import io
        from types import SimpleNamespace
        spec = importlib.util.spec_from_file_location("swapz_replay_pair", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            base = {
                "fixture_sha256": "a" * 64, "trace_sha256": "b" * 64,
                "write_payload_stream_sha256": "c" * 64,
                "prefill_sha256": "d" * 64, "expected_post_sha256": "e" * 64,
                "manifest_sha256": "f" * 64, "qd": 4, "layout": "disjoint",
                "seed": 77, "iops_requested": 200, "warmup_ops": 20,
                "measure_ops": 100, "read_ops": 50, "write_ops": 50,
                "verified_pages": 32, "verified_post_sha256": "e" * 64,
                "verdict": "PASS", "source_sha": "1" * 40,
                "lower_io": {
                    "lower_read_requests": 50, "lower_read_bytes": 204800,
                    "lower_write_requests": 50, "lower_write_bytes": 204800,
                    "lower_flush_requests": 1,
                },
            }
            off = {**base, "candidate": "off", "achieved_iops": 190.0,
                   "device_identity": {"device": "251:0",
                                       "owned_disk": "nullb0",
                                       "lower_major_minor": "251:0",
                                       "dm_uuid": None}}
            v3 = {**base, "candidate": "v3", "achieved_iops": 188.0,
                  "device_identity": {"device": "253:0",
                                      "owned_disk": "nullb1",
                                      "lower_major_minor": "251:1",
                                      "dm_uuid": "SWZTEST-00001"}}
            paths = [directory / "off.json", directory / "v3.json"]
            def compare():
                for location, report in zip(paths, (off, v3)):
                    location.write_text(json.dumps(report))
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    module.compare(SimpleNamespace(reports=paths))
                return json.loads(output.getvalue())
            self.assertEqual(compare()["performance_qualification"],
                             "MATCHED_LOAD_MEASUREMENT_ONLY")
            v3["achieved_iops"] = 120
            self.assertEqual(compare()["performance_qualification"],
                             "INCONCLUSIVE_UNMATCHED_ACHIEVED_LOAD")
            v3["achieved_iops"] = 188
            v3["device_identity"]["lower_major_minor"] = "251:0"
            with self.assertRaisesRegex(ValueError, "not independent"):
                compare()
            v3["device_identity"]["lower_major_minor"] = "251:1"
            v3["lower_io"] = None
            with self.assertRaisesRegex(ValueError, "missing independent"):
                compare()
            v3["lower_io"] = base["lower_io"]
            v3["source_sha"] = "2" * 40
            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                compare()

    def test_owned_v3_uuid_matches_owned_pair_harness(self):
        self.assertIn('r"SWAPZ-TEST-[a-f0-9]{16}"', SCRIPT.read_text())
        script = SCRIPT.parents[3] / "tools/benchmark-owned-pair.sh"
        self.assertIn('DMUUID="SWAPZ-TEST-$token"', script.read_text())

    def test_protected_regular_file_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bad = root / "not-an-owned-benchmark-file.bin"
            bad.write_bytes(b"\0" * (PAGE * 8))
            # A regular file needs a distinctive name plus an explicit
            # rootless-test opt-in. Arbitrary file paths are never writable.
            sys.path.insert(0, str(SCRIPT.parent))
            import importlib.util
            spec = importlib.util.spec_from_file_location("threeway", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            class A: pass
            a = A()
            a.device = str(bad)
            a.regular_file_test = True
            with self.assertRaises(ValueError):
                mod.check_device(a, 8)
            a.device = str(root / "swapz-replay-allowed.bin")
            with (root / "swapz-replay-allowed.bin").open("wb") as file:
                file.truncate(8 * PAGE)
            a.regular_file_test = False
            with self.assertRaises(ValueError):
                mod.check_device(a, 8)

    def test_manifest_cannot_have_duplicate_inflight_slot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(bytes([1]) * PAGE * 16)
            plan = root / "plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--qd", 4,
                         "--logical-pages", 64, "--writer-pages", 16,
                         "--reader-start", 32, "--reader-pages", 16,
                         "--warmup-ops", 4, "--measure-ops", 8)
            import importlib.util
            spec = importlib.util.spec_from_file_location("threeway", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mf = json.loads((plan / "manifest.json").read_text())
            # Plan validation checks both SHA and in-wave independence.
            rows = [json.loads(line) for line in (plan / "trace.jsonl").read_text().splitlines()]
            rows[1]["page"] = rows[0]["page"]
            replacement = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                                  for r in rows).encode()
            (plan / "trace.jsonl").write_bytes(replacement)
            mf["trace_sha256"] = mod.sha(replacement)
            with self.assertRaisesRegex(ValueError, "same logical page"):
                mod.check_plan(plan / "trace.jsonl", mf, 16)


if __name__ == "__main__":
    unittest.main()
