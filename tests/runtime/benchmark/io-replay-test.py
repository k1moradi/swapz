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

    def test_four_mib_verified_fixed_volume_read_rootless(self):
        # Identical direct replay path and oracle, but WITHOUT any real
        # Device Mapper loaded or claims about kernel packed extents.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / "fixture.bin"
            fixture.write_bytes(b"".join(bytes([i + 1]) * PAGE
                                         for i in range(32)))
            plan = root / "plan"
            self.run_cmd("prepare", "--fixture", fixture,
                         "--output-dir", plan, "--logical-pages", 1024,
                         "--writer-pages", 256, "--reader-start", 512,
                         "--reader-pages", 256, "--qd", 32,
                         "--warmup-ops", 32, "--measure-ops", 64,
                         "--read-pct", 25, "--iops", 0)
            reports = []
            for candidate in ("off", "v3"):
                device = root / f"swapz-replay-{candidate}.bin"
                with device.open("wb") as fd:
                    fd.truncate(1024 * PAGE)
                result = root / f"{candidate}.json"
                run = self.run_cmd("run", "--fixture", fixture,
                                   "--trace", plan / "trace.jsonl",
                                   "--manifest", plan / "manifest.json",
                                   "--device", device, "--candidate", candidate,
                                   "--source-sha", "rootless-no-module",
                                   "--regular-file-test", "--packed-read",
                                   "--result", result)
                for subphase in ("prefill", "mixed", "packed_read"):
                    self.assertIn(f"BENCH_IO_PHASE={candidate}:{subphase}",
                                  run.stderr)
                record = json.loads(result.read_text())
                read = record["packed_read"]
                self.assertIn("executor startup", record["mixed_timed_scope"])
                self.assertEqual(read["qualification"], "ROOTLESS_NO_PACK_PROOF")
                self.assertEqual(read["logical_bytes"], 4194304)
                self.assertIsNone(read["packed_close_delta"])
                for mode in ("sequential", "seeded_random"):
                    phase = read["passes"][mode]
                    self.assertEqual(phase["logical_bytes"], 4194304)
                    self.assertEqual(phase["verified_pages"], 1024)
                    self.assertEqual(phase["verified_image_sha256"],
                                     read["logical_image_sha256"])
                    self.assertGreater(phase["seconds"], 0)
                    self.assertIn("buffers and worker setup excluded", phase["timed_scope"])
                    self.assertGreater(phase["useful_read_mbps"], 0)
                    self.assertGreaterEqual(phase["replay_cpu_user_s"], 0)
                reports.append(result)
            self.run_cmd("compare", "--reports", *reports)
            wrong = json.loads(reports[0].read_text())
            wrong["packed_read"]["passes"]["sequential"]["verified_pages"] = 100
            reports[0].write_text(json.dumps(wrong))
            self.run_cmd("compare", "--reports", *reports, success=False)

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
                self.assertEqual(result["performance_qualification"],
                                 "ROOTLESS_NOT_DEVICE_EVIDENCE")
                self.assertTrue(all(
                    entry["throughput_mbps"]["lower_write_mbps"] is None
                    for entry in result["results"]
                ))
                expected = manifest["expected_post_sha256"]
                for report_path in reports:
                    record = json.loads(report_path.read_text())
                    self.assertEqual(record["verified_post_sha256"], expected)
                    self.assertEqual(record["write_ops"] + record["read_ops"], 128)
                    self.assertEqual(record["warmup_ops"], 32)
                    self.assertEqual(record["verified_pages"], 64)
                    self.assertEqual(record["verdict"], "PASS")
                    rates = record["throughput_mbps"]
                    self.assertGreater(rates["logical_total_mbps"], 0)
                    self.assertIsNone(rates["lower_write_mbps"])
                    self.assertIsNone(rates["write_input_per_lower_byte"])
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
        tokens = f"0 32768 swapz {lower} 0 64 0 2 0 0 1 0"
        self.assertEqual(module.validate_v3_table(tokens, 4096, lower, name)["window"], 64)
        self.assertEqual(module.validate_v3_table(tokens, 4096, lower, name)["retain_ms"], 0)
        self.assertEqual(module.validate_v3_table(
            tokens + " 2", 4096, lower, name
        )["retain_ms"], 2)
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
            tokens.replace("swapz", "linear"),
            tokens + "\n" + tokens,
            tokens + " 0 0",
            tokens + " 5",
            tokens + " -1",
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
                "seconds": 1.0,
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
            output = compare()
            self.assertEqual(output["performance_qualification"],
                             "MATCHED_LOAD_MEASUREMENT_ONLY")
            self.assertEqual(output["lower_write_bytes_saved_fraction"], 0)
            for entry in output["results"]:
                rates = entry["throughput_mbps"]
                self.assertAlmostEqual(rates["logical_write_mbps"], 0.2048)
                self.assertAlmostEqual(rates["logical_read_mbps"], 0.2048)
                self.assertAlmostEqual(rates["lower_write_mbps"], 0.2048)
                self.assertAlmostEqual(rates["lower_read_mbps"], 0.2048)
                self.assertEqual(rates["write_input_per_lower_byte"], 1.0)
            v3["lower_io"] = {**base["lower_io"],
                              "lower_write_bytes": 102400}
            candidate = compare()
            self.assertAlmostEqual(
                candidate["results"][1]["throughput_mbps"]["lower_write_mbps"],
                0.1024
            )
            self.assertAlmostEqual(
                candidate["results"][1]["throughput_mbps"]["write_input_per_lower_byte"],
                2.0
            )
            self.assertAlmostEqual(candidate["lower_write_bytes_saved_fraction"], 0.5)
            v3["lower_io"] = base["lower_io"]
            off["iops_requested"] = v3["iops_requested"] = 0
            v3["achieved_iops"] = 250
            v3["seconds"] = 0.4
            unpaced = compare()
            self.assertEqual(unpaced["rate_mode"], "unpaced")
            self.assertEqual(unpaced["performance_qualification"],
                             "UNPACED_THROUGHPUT_MEASUREMENT_ONLY")
            self.assertIsNone(unpaced["allowed_iops_difference_fraction"])
            self.assertAlmostEqual(
                unpaced["logical_write_mbps_ratio_v3_to_off"], 2.5)
            self.assertAlmostEqual(
                unpaced["lower_write_mbps_ratio_v3_to_off"], 2.5)
            off["iops_requested"] = v3["iops_requested"] = 500
            v3["seconds"] = 1.0
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

    def test_throughput_invalid_times_counts_and_lower_sectors_fail_closed(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("swapz_replay_rates", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        report = {
            "seconds": 2.0, "write_ops": 10, "read_ops": 2,
            "measure_ops": 12, "lower_io": {
                "lower_write_bytes": 20480, "lower_read_bytes": 8192,
            },
        }
        rates = module.measured_throughput(report, require_lower=True)
        self.assertAlmostEqual(rates["logical_write_mbps"], 0.02048)
        self.assertAlmostEqual(rates["lower_write_mbps"], 0.01024)
        self.assertAlmostEqual(rates["write_input_per_lower_byte"], 2)
        for seconds in (0, -1, float("nan"), float("inf"), None, True):
            with self.subTest(seconds=seconds):
                with self.assertRaisesRegex(ValueError, "elapsed time"):
                    module.measured_throughput({**report, "seconds": seconds})
        for count in (-1, 1.5, True, None):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, "logical operations"):
                    module.measured_throughput({**report, "write_ops": count})
        for lower_bytes in (-512, 513, True, None):
            with self.subTest(lower_bytes=lower_bytes):
                with self.assertRaisesRegex(ValueError, "lower sector bytes"):
                    module.measured_throughput({
                        **report, "lower_io": {**report["lower_io"],
                                               "lower_write_bytes": lower_bytes}
                    })
        with self.assertRaisesRegex(ValueError, "independent lower I/O"):
            module.measured_throughput({**report, "lower_io": None},
                                       require_lower=True)
        zero = module.measured_throughput({
            **report, "lower_io": {**report["lower_io"], "lower_write_bytes": 0}
        })
        self.assertIsNone(zero["write_input_per_lower_byte"])

    def test_nonzero_medium_pages_have_measured_lz4_in_2k_range(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "swapz_medium_fixture", SCRIPT.with_name("anon-page-fixture.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            compressor = module.lz4_compressor()
        except RuntimeError as error:
            self.skipTest(str(error))
        content, manifest = module.generate(
            0x51A0A9, 128, module.parse_weights("medium=100"), compressor
        )
        self.assertEqual(len(content), 128 * PAGE)
        self.assertEqual(manifest["profile_pages"], {"medium": 128})
        self.assertEqual(manifest["lz4_size_buckets"], {"2049_3072": 128})
        self.assertEqual(manifest["raw_pages"], 0)
        self.assertGreaterEqual(manifest["lz4_min_accepted_payload_bytes"], 2049)
        self.assertLessEqual(manifest["lz4_max_accepted_payload_bytes"], 2200)
        self.assertLessEqual(
            manifest["lz4_min_accepted_payload_bytes"],
            manifest["lz4_max_accepted_payload_bytes"]
        )
        for index in range(128):
            chunk = content[index * PAGE:(index + 1) * PAGE]
            self.assertNotEqual(chunk, bytes(PAGE))
            actual = module.measure(compressor, chunk)
            self.assertGreaterEqual(actual, 2049)
            self.assertLessEqual(actual, 2200)
        repeat, same_manifest = module.generate(
            0x51A0A9, 128, module.parse_weights("medium=100"), compressor
        )
        self.assertEqual(content, repeat)
        self.assertEqual(manifest, same_manifest)

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
