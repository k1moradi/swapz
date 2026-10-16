#!/usr/bin/env python3
"""Rootless contract tests for the sole make test JSON/XZ reporting pipeline."""
import contextlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("swapz_private_test_runner",
                                               ROOT / "tools/run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def arm(candidate, *, mode, regime):
    v3 = candidate == "v3"
    raw_mbps = 14 if regime == "sd_emulated" else 32
    cand_mbps = (20 if mode == 0 else 20.01) if regime == "sd_emulated" else (
        24 if mode == 0 else 24.01)
    raw_read_time = 1.0
    packed = {
        "logical_bytes": 4194304,
        "logical_image_sha256": "d" * 64,
        "packed_close_delta": 4 if v3 else None,
        "qualification": ("OWNED_PACK_READY_AND_VERIFIED_4MIB_READ" if v3
                          else "ROOTLESS_NO_PACK_PROOF"),
        "passes": {
            key: {
                "logical_bytes": 4194304,
                "verified_pages": 1024,
                "verified_image_sha256": "d" * 64,
                "seconds": raw_read_time * (0.9 if v3 else 1.),
                "useful_read_mbps": 4.19 if not v3 else 4.65,
                "read_p99_ms": 2 if v3 else 3,
                "lower_io": {
                    "lower_read_bytes": 6291456 if v3 else 4194304,
                    "lower_read_requests": 1536 if v3 else 1024,
                },
                "kernel_read_path": ({
                    "read_meta_reqs": 1024,
                    "read_payload_reqs": 512,
                    "read_payload_blocks": 512,
                    "lower_read_wall_ns": 120000000,
                    "decode_wall_ns": 20000000,
                    "read_meta_cache_hits": 128,
                    "read_meta_lru_hits": 100,
                    "read_shadow_hits_4": 160,
                    "read_shadow_hits_16": 240,
                    "read_shadow_hits_64": 300,
                    "read_block_shadow_hits": 200,
                    "read_block_shadow_misses": 900,
                    "read_block_shadow_reqs": 700,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                } if v3 else None),
                "replay_cpu_user_s": .15,
                "replay_cpu_system_s": .12,
                "replay_peak_rss_kb": 12000,
            }
            for key in ("sequential", "seeded_random")
        },
    }
    return {
        "candidate": candidate, "verdict": "PASS",
        "source_sha": "a" * 40,
        "fixture_sha256": "b" * 64, "trace_sha256": "c" * 64,
        "device_identity": {"device": "PRIVATE_DEVICE_MUST_NOT_ESCAPE"},
        "throughput_mbps": {
            "logical_write_mbps": cand_mbps if v3 else raw_mbps,
            "lower_write_mbps": 12 if v3 else 14,
            "logical_read_mbps": 7 if v3 else 4,
            "logical_write_bytes": 8000, "logical_read_bytes": 4000,
        },
        "lower_io": {
            "lower_write_bytes": 5000 if v3 else 8000,
            "lower_read_bytes": 4000,
            "lower_write_requests": 5 if v3 else 8,
            "lower_read_requests": 4,
        },
        "read_p95_ns": 4000000 if v3 else 8000000,
        "read_p99_ns": 5000000 if v3 else 10000000,
        "write_p99_ns": 2000000,
        "seconds": 2, "verified_pages": 1024,
        "mixed_replay_cpu_user_s": .12,
        "mixed_replay_cpu_system_s": .08,
        "mixed_replay_peak_rss_kb": 12000,
        "packed_read": packed,
        "kernel_write_path": ({
            "physical_write_reqs": 5,
            "lz4_wall_ns": 20000000,
            "window_sort_wall_ns": 1000000,
            "window_commit_wall_ns": 40000000,
            "lower_write_wall_ns": 30000000,
            "windows": 4,
            "write_wait_le1ms": 2,
            "write_wait_1to4ms": 2,
            "write_wait_gt4ms": 1,
        } if v3 else None),
    }


def synthetic_log():
    out = ["HOST_SWAPS_BEFORE:", "/private/system/swapfile",
           "SOURCE_HEAD=a" + "a" * 39, "PASS_LOADED_OWNED_NULLBLK_SMOKE"]
    for regime in runner.MODEL_ORDER:
        spec = runner.MODEL_SPECS[regime]
        out.append(f"START_OWNED_RAM_REGIME={regime}")
        for i, mode in enumerate((0, 1, 1, 0)):
            out.append(f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
            out.append("REPLAY_ORDER=v3-first" if i % 2 else "REPLAY_ORDER=off-first")
            out.append("PASS_RAM_MODEL_LOWER_MBPS={cap_mib_s} COMPLETION_NSEC={completion_nsec} IRQMODE={irqmode}".format(**spec))
            out.append("V3_STATUS_BEFORE=close_pack_ready=0 burst_tail_flushes=0 packed_early_commits=0 single_pack_deferrals=0 accepted_burst_extensions=0 accepted_burst_tail_flushes=0 accepted_burst_read_caps=0 accepted_burst_cap_extra_blocks=0 accepted_burst_cap_extra_gt1_windows=0 accepted_burst_four_extents_avoided=0 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=0 accepted_burst_cap3_recovered_blocks=0 accepted_burst_cap3_full_recovery_windows=0 one_page_windows=0 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=0 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=0 win1_pack_ready=0")
            out.append("V3_STATUS_AFTER=close_pack_ready=18 burst_tail_flushes=7 packed_early_commits=8 single_pack_deferrals=24 accepted_burst_extensions=6 accepted_burst_tail_flushes=5 accepted_burst_read_caps=4 accepted_burst_cap_extra_blocks=4 accepted_burst_cap_extra_gt1_windows=1 accepted_burst_four_extents_avoided=8 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=1 accepted_burst_cap3_recovered_blocks=2 accepted_burst_cap3_full_recovery_windows=1 one_page_windows=4 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=1 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=2 win1_pack_ready=1")
            for candidate in (("v3", "off") if i % 2 else ("off", "v3")):
                out.append(json.dumps(arm(candidate, mode=mode, regime=regime)))
            if mode:
                out.append("PASS_ASYNC_LOWER_IO_OVERLAP_STARTS=42")
            out.append(f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}")
        out.append(f"PASS_OWNED_RAM_REGIME={regime}")
    return "\n".join(out) + "\n"


class ReportContract(unittest.TestCase):
    def test_unsupported_owned_storage_delay_tuples_fail_before_privilege(self):
        """Reject arbitrary timer or cap input BEFORE touching host devices."""
        import subprocess
        script = ROOT / "tools/benchmark-owned-pair.sh"
        common = ["bash", str(script), "--run-owned-ram-pair",
                  "--profile", "medium", "--retain-ms", "2", "--unpaced"]
        forbidden = (
            ("--lower-mbps", "80", "--completion-nsec", "1000000"),
            ("--lower-mbps", "10", "--completion-nsec", "150000"),
            ("--lower-mbps", "80", "--completion-nsec", "5"),
            ("--lower-mbps", "999", "--completion-nsec", "150000"),
            ("--completion-nsec", "1000000"),
            ("--lower-mbps", "12"),
            ("--lower-mbps", "20"),
            ("--lower-mbps", "0"),
            ("--lower-mbps", "10"),
        )
        for option in forbidden:
            with self.subTest(option=option):
                run = subprocess.run(common + list(option), text=True,
                                     capture_output=True, timeout=4)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("BLOCKED", run.stderr)
        source = script.read_text()
        for key in ('"$config/mbps"', '"$config/irqmode"',
                    '"$config/completion_nsec"', '"$config/memory_backed"'):
            self.assertIn(key, source)
        self.assertIn('PASS_RAM_MODEL_LOWER_MBPS=', source)
        # The deleted shell preflight was redundant with this rootless
        # Python contract. Preserve teardown/ownership/swap guard checks.
        for gate in ("SWAPS=", "nullb-swapz-", "memory_backed",
                     "dmsetup remove", "QUARANTINE=0",
                     "READY_COUNT=0", "COUNT != READY_COUNT",
                     "--expected-dm-uuid", "timeout --signal=TERM"):
            self.assertIn(gate, source)
        loaded = (ROOT / "tools/test-loaded.sh").read_text()
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertNotIn("/dev/sdb", loaded)

    def test_immutable_inputs_and_alternating_arm_order(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(len(sessions), 8)
        self.assertEqual([s["async_prepare"] for s in sessions],
                         [0, 1, 1, 0] * 2)
        self.assertEqual([s["regime"] for s in sessions],
                         [regime for regime in runner.MODEL_ORDER for _ in range(4)])
        self.assertEqual([s["order"] for s in sessions],
                         ["off-first", "v3-first"] * 4)
        self.assertTrue(all(s["status"] == "PASS" for s in sessions))
        for j, session in enumerate(sessions):
            self.assertEqual(session["device_model"],
                             {k: runner.MODEL_SPECS[session["regime"]][k]
                              for k in ("cap_mib_s", "completion_nsec", "irqmode")})
            if j % 4 in (1, 2):
                self.assertEqual(session["overlap_starts"], 42)
            else:
                self.assertNotIn("overlap_starts", session)
        self.assertNotIn("device_identity", json.dumps(sessions))
        self.assertNotIn("PRIVATE_DEVICE_MUST_NOT_ESCAPE", json.dumps(sessions))

    def test_slow_model_gain_and_fast_model_loss_are_both_visible(self):
        data = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        self.assertEqual(data["overall"], "PASS_BOUNDED_RAM_MATRIX")
        slow = data["regimes"]["sd_emulated"]
        fast = data["regimes"]["ssd_emulated"]
        self.assertEqual(slow["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_GAIN_PRELIMINARY")
        self.assertEqual(fast["criteria"]["sync"]["throughput_vs_raw"],
                         "MATERIAL_LOSS_PRELIMINARY")
        self.assertEqual(fast["interpretation"],
                         "SYNTHETIC_RAM_MODEL_ONLY_NOT_PHYSICAL_MEDIA")
        self.assertEqual(data["regimes"]["sd_emulated"]["device_model"]["completion_nsec"],
                         1000000)
        self.assertEqual(data["regimes"]["ssd_emulated"]["device_model"]["cap_mib_s"],
                         80)
        self.assertAlmostEqual(
            slow["criteria"]["sync"]["lower_write_saved_fraction"], .375)
        self.assertEqual(
            slow["criteria"]["async_vs_sync"]["write_throughput"],
            "NO_SIGNIFICANT_ASYNC_GAIN")
        self.assertAlmostEqual(
            slow["columns"]["sync"]["sequential_4mib_s"], .9)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_reqs"], 1024)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_payload_reqs"], 512)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_cache_hits"], 128)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_meta_lru_hits"], 100)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_shadow_hits_4"], 160)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_shadow_hits_16"], 240)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_shadow_hits_64"], 300)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_block_shadow_hits"], 200)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_block_shadow_misses"], 900)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_block_shadow_reqs"], 700)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_full_extent_reqs"], 200)
        self.assertEqual(slow["columns"]["async"]["seeded_random_read_full_cache_hits"], 64)
        self.assertEqual(slow["columns"]["sync"]["sequential_read_two_block_skips"], 128)
        self.assertEqual(slow["columns"]["sync"]["mixed_physical_write_reqs"], 5)
        self.assertEqual(slow["columns"]["async"]["mixed_write_wait_gt4ms"], 1)
        self.assertEqual(slow["columns"]["sync"]["mixed_lower_write_wall_ns"], 30000000)
        self.assertEqual(slow["alpha22_kernel_counters"]["single_pack_deferrals"], 24)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_extensions"], 6)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_tail_flushes"], 5)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_read_caps"], 4)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_cap_extra_blocks"], 4)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_cap_extra_gt1_windows"], 1)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_four_extents_avoided"], 8)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_plan_stats_failures"], 0)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_cap3_pareto_candidates"], 1)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_cap3_recovered_blocks"], 2)
        self.assertEqual(slow["alpha22_kernel_counters"]["accepted_burst_cap3_full_recovery_windows"], 1)
        self.assertEqual(slow["alpha22_kernel_counters"]["close_pack_ready"], 18)
        self.assertEqual(slow["alpha22_kernel_counters"]["win1_deadline"], 2)
        self.assertEqual(slow["alpha22_kernel_counters"]["win1_pack_ready"], 1)
        self.assertEqual(slow["alpha22_kernel_counters"]["win1_read_unrelated"], 1)
        self.assertEqual(data["gc"][:13], "NOT_EXERCISED")
        self.assertEqual(data["physical_media"], "NOT_TESTED")
        self.assertIn("kernel DM workers", data["cpu_scope"])
        self.assertIn("PROXY_ONLY", data["endurance"])

    def test_benchmark_table_places_units_in_metric_column_once(self):
        verdicts = runner.benchmark_verdicts(runner.parse_sessions(synthetic_log()))
        report = {"benchmarks": {"verdicts": verdicts}}
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.print_bench(report)
        rendered = output.getvalue()
        self.assertIn("LRU64 reused=", rendered)
        self.assertIn("block-LRU64 simulation", rendered)
        self.assertIn("shadow metadata LRU hits", rendered)
        self.assertIn("One-page close reasons per-pair mean", rendered)
        self.assertIn("4MiB random lower READ requests", rendered)
        lines = rendered.splitlines()
        cases = (
            ("Useful WRITE throughput (MB/s)", "MB/s"),
            ("Mixed READ p99 (ms)", "ms"),
            ("4MiB sequential lower READ (bytes)", "bytes"),
            ("Replay process peak RSS (KiB)", "KiB"),
        )
        for metric, unit in cases:
            with self.subTest(metric=metric):
                line = next(item for item in lines if metric in item)
                self.assertEqual(line.count(unit), 1)

    def test_mixed_write_diagnostics_missing_or_inconsistent_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["arms"]["v3"]["kernel_write_path"] = None
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[3]["arms"]["v3"]["kernel_write_path"]["write_wait_gt4ms"] = 2
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[2]["arms"]["v3"]["kernel_write_path"]["lz4_wall_ns"] = -1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_tail_flushes"] = 7
        sessions[0]["kernel_status"]["after"]["accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_read_caps"] = 7
        sessions[0]["kernel_status"]["after"]["accepted_burst_extensions"] = 6
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_cap_extra_gt1_windows"] = 5
        sessions[0]["kernel_status"]["after"]["accepted_burst_read_caps"] = 4
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_plan_stats_failures"] = 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_cap3_pareto_candidates"] = 2
        sessions[0]["kernel_status"]["after"]["accepted_burst_cap_extra_gt1_windows"] = 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_cap3_recovered_blocks"] = 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["accepted_burst_cap3_full_recovery_windows"] = 2
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_shadow_read_diagnostics_fail_closed_when_not_nested(self):
        sessions = runner.parse_sessions(synthetic_log())
        path = sessions[0]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "kernel_read_path"]
        path["read_shadow_hits_4"] = path["read_meta_cache_hits"] - 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        path = sessions[0]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "kernel_read_path"]
        path["read_shadow_hits_4"] = path["read_shadow_hits_16"] + 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        path = sessions[0]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "kernel_read_path"]
        path["read_shadow_hits_16"] = path["read_shadow_hits_64"] + 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        path = sessions[0]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "kernel_read_path"]
        path["read_meta_lru_hits"] = (
            path["read_shadow_hits_64"] - path["read_meta_cache_hits"] + 1)
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        path = sessions[0]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "kernel_read_path"]
        path["read_block_shadow_reqs"] = path["read_block_shadow_misses"] + 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[0]["kernel_status"]["after"]["win1_deadline"] += 1
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_incomplete_mismatch_or_forged_packed_result_fails_closed(self):
        sessions = runner.parse_sessions(synthetic_log())
        self.assertEqual(runner.benchmark_verdicts(sessions[:7])["overall"],
                         "INCOMPLETE")
        sessions[1]["source_sha"] = "different-source"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[1]["trace_sha256"] = "tampered-trace"
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCONCLUSIVE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["v3"]["packed_read"]["packed_close_delta"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions[6]["arms"]["v3"]["packed_read"]["passes"]["sequential"][
            "logical_bytes"] = 0
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

        sessions = runner.parse_sessions(synthetic_log())
        sessions[5]["device_model"]["completion_nsec"] = 1234
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")
        sessions = runner.parse_sessions(synthetic_log())
        sessions.pop()
        self.assertEqual(runner.benchmark_verdicts(sessions)["overall"],
                         "INCOMPLETE")

    def test_report_replaced_and_not_raw_json_to_terminal(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "build/test_results.json.xz"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                fake = ["python3", "-c",
                        "print('{\"candidate\":\"off\", \"device\": \"SECRET\"}')"]
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(runner.run_stage("fake safe", fake, report), 0)
                self.assertNotIn('"candidate"', output.getvalue())
                self.assertNotIn("SECRET", output.getvalue())
                self.assertEqual(report["stages"][0]["status"], "PASS")
                path = runner.REPORT
                first = lzma.open(path, "rt").read()
                self.assertNotIn("SECRET", first)
                report["overall"] = "FAIL"
                runner.write_report(report)
                second = json.loads(lzma.open(path, "rt").read())
                self.assertEqual(second["overall"], "FAIL")
                self.assertEqual(len(list((runner.ROOT / "build").glob("*.xz"))), 1)
                self.assertIn("test_results.json.xz", str(path))
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_exit_two_is_fail_before_loaded_stage_and_blocked_only_when_marked(self):
        with tempfile.TemporaryDirectory(prefix="report-", dir=ROOT / "build/tests") as name:
            original_root, original_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "build/test_results.json.xz"
                report = {"schema": "swapz-test-results-v1", "stages": [],
                          "benchmarks": {"sessions": [], "verdicts": {}}}
                rootless = [
                    "python3", "-c",
                    "import sys; print('/private/native.c:155: FAIL: extents == 3'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Native and rootless contracts",
                                         rootless, report), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "FAIL")
                self.assertEqual(stage["failed_phase"],
                                 "Native and rootless contracts")
                self.assertIn("extents == 3", stage["diagnostic"])
                self.assertNotIn("/private", stage["diagnostic"])
                self.assertNotIn("administrator", stage["failed_phase"])

                loaded = [
                    "python3", "-c",
                    "import sys; print('BLOCKED_LOADED_QUALIFICATION: no root'); sys.exit(2)",
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        runner.run_stage("Owned RAM smoke and 8 pairs",
                                         loaded, report, parse_bench=True), 2)
                stage = report["stages"][-1]
                self.assertEqual(stage["status"], "BLOCKED")
                self.assertIn("administrator authorization",
                              stage["failed_phase"])
            finally:
                runner.ROOT, runner.REPORT = original_root, original_report

    def test_loaded_failure_identifies_failed_phase_without_private_paths(self):
        # This was a real regression: privileged benchmarks created
        # build/benchmark/ (mode 0700), then a non-root user attempted
        # mktemp in the same root-owned directory.
        log = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
               "PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
               "mktemp: failed to create directory via template "
               "'/home/secret/swapz/build/benchmark/shared.XXXXXXXX': "
               "Permission denied\n")
        phase, reason = runner.failure_context(log)
        self.assertIn("shared fixture", phase)
        self.assertIn("not writable", reason)
        self.assertNotIn("/home/secret", reason)

        blocked = ("START_LOADED_OWNED_NULLBLK_SMOKE\n"
                   "BLOCKED: backing mismatch: "
                   "/home/private/dev/nullb-swapz-abcdef0123456789\n")
        phase, reason = runner.failure_context(blocked)
        self.assertIn("owned RAM kernel smoke", phase)
        self.assertIn("BLOCKED:", reason)
        self.assertNotIn("/home/private", reason)
        self.assertNotIn("swapz", reason)
        self.assertNotIn("abcdef0123456789", reason)

        pair = ("PASS_LOADED_OWNED_NULLBLK_SMOKE\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "PASS_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
                "START_OWNED_RAM_PAIR_ASYNC_PREPARE=1\n"
                "FAIL: independent backing lower I/O mismatch\n")
        phase, reason = runner.failure_context(pair)
        self.assertIn("comparison 2/8 (async)", phase)
        self.assertIn("backing lower I/O mismatch", reason)
        loaded_subphase = (
            "START_OWNED_RAM_REGIME=sd_emulated\n"
            "START_OWNED_RAM_PAIR_ASYNC_PREPARE=0\n"
            "BENCH_IO_PHASE=v3:packed_read\n"
            "FAIL: verified fixed volume was not returned\n"
        )
        phase, reason = runner.failure_context(loaded_subphase)
        self.assertIn("sd_emulated comparison 1/8 (sync)", phase)
        self.assertIn("[v3 packed_read]", phase)
        self.assertIn("verified fixed volume", reason)

    def test_non_root_fixture_never_uses_privileged_evidence_directory(self):
        loaded = (ROOT / "tools/test-loaded.sh").read_text()
        private = (ROOT / "tools/benchmark-owned-pair.sh").read_text()
        self.assertIn('mkdir -p "$ROOT/build/tests"', loaded)
        self.assertIn('mktemp -d "$ROOT/build/tests/benchmark-plan.XXXXXXXX"', loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', loaded)
        self.assertIn('"$ROOT/build/tests/benchmark-plan."*', private)
        self.assertNotIn('mktemp -d "$ROOT/build/benchmark/', loaded)
        # Simulate the historical mode-0700 benchmark log directory without
        # any privilege or actual device. A fixture can still be created.
        import os
        with tempfile.TemporaryDirectory(prefix="fixture-permissions-",
                                         dir=ROOT / "build/tests") as folder:
            root = Path(folder)
            evidence = root / "benchmark"
            evidence.mkdir()
            evidence.chmod(0o500)
            scratch = root / "tests"
            scratch.mkdir()
            try:
                import tempfile as temporary
                owned = Path(temporary.mkdtemp(prefix="benchmark-plan.",
                                              dir=scratch))
                self.assertTrue(owned.is_dir())
                (owned / "fixture.bin").write_bytes(b"safe")
                self.assertEqual((owned / "fixture.bin").read_bytes(), b"safe")
            finally:
                evidence.chmod(0o700)

    def test_git_only_report_sync_tracks_exact_tested_commit(self):
        """Exercise actual Git plumbing with a LOCAL bare remote, not GitHub.

        No hardware, external API, subprocess identity leakage or GitHub
        pushes. Only the remote-URL query is mocked to enforce the safety
        allowlist while all commits/fast-forward operations are genuine.
        """
        import os
        import subprocess
        from unittest import mock

        def git(*args, cwd, check=True):
            return subprocess.run(["git", *args], cwd=cwd, check=check,
                                  capture_output=True, text=True, timeout=12)

        with tempfile.TemporaryDirectory(
                prefix="report-git-", dir=ROOT / "build/tests") as name:
            sandbox = Path(name)
            checkout, origin = sandbox / "checkout", sandbox / "origin.git"
            checkout.mkdir()
            git("init", "--bare", str(origin), cwd=sandbox)
            git("init", cwd=checkout)
            git("checkout", "-b", "main", cwd=checkout)
            git("config", "user.name", "test-report CI", cwd=checkout)
            git("config", "user.email", "test@example.invalid", cwd=checkout)
            (checkout / "source.c").write_text("int source(void){return 7;}\n")
            git("add", "source.c", cwd=checkout)
            git("commit", "-m", "Testable source", cwd=checkout)
            code_sha = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
            git("remote", "add", "origin", str(origin), cwd=checkout)
            git("push", "origin", "main", cwd=checkout)

            old_root, old_report, old_git_result = (
                runner.ROOT, runner.REPORT, runner.git_result)
            runner.ROOT = checkout
            runner.REPORT = checkout / "build/test_results.json.xz"
            runner.REPORT.parent.mkdir(parents=True)

            def intercept(command, *, data=None, timeout=15, env=None):
                if command == ["remote", "get-url", "--push", "origin"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        stdout=b"git@github.com:k1moradi/swapz.git",
                        stderr=b"")
                return old_git_result(command, data=data, timeout=timeout,
                                      env=env)

            try:
                with mock.patch.object(runner, "git_result",
                                       side_effect=intercept):
                    self.assertEqual(runner.code_sha(), code_sha)
                    original = {
                        "source_sha": code_sha,
                        "tested_commit_sha": code_sha,
                        "code_commit_sha": code_sha,
                        "overall": "BLOCKED",
                    }
                    runner.write_report(original)
                    first = runner.publish(code_sha)
                    self.assertIn("SYNCED_GIT", first)

                    # Plumbing publishes to remote without modifying checkout.
                    self.assertEqual(git("rev-parse", "HEAD",
                                         cwd=checkout).stdout.strip(), code_sha)
                    self.assertFalse((checkout / runner.GIT_RESULT).exists())
                    first_remote = git("--git-dir", str(origin), "rev-parse",
                                       "refs/heads/main", cwd=sandbox).stdout.strip()
                    self.assertNotEqual(code_sha, first_remote)
                    contents = subprocess.run(
                        ["git", "--git-dir", str(origin), "show",
                         f"{first_remote}:{runner.GIT_RESULT}"],
                        cwd=sandbox, capture_output=True, check=True).stdout
                    self.assertEqual(json.loads(lzma.decompress(contents)), original)

                    # Stale checkout must not append an unrelated result.
                    self.assertIn("changed since testing", runner.publish(code_sha))

                    git("pull", "--ff-only", "origin", "main", cwd=checkout)
                    self.assertEqual(runner.code_sha(), code_sha)
                    next_parent = git("rev-parse", "HEAD",
                                      cwd=checkout).stdout.strip()
                    updated = dict(original,
                                   source_sha=next_parent,
                                   tested_commit_sha=next_parent,
                                   overall="PASS")
                    runner.write_report(updated)
                    result = runner.publish(next_parent)
                    self.assertIn("SYNCED_GIT", result)
                    after = git("--git-dir", str(origin), "rev-parse",
                                "refs/heads/main", cwd=sandbox).stdout.strip()
                    self.assertNotEqual(after, first_remote)
                    final_contents = subprocess.run(
                        ["git", "--git-dir", str(origin), "show",
                         f"{after}:{runner.GIT_RESULT}"],
                        cwd=sandbox, capture_output=True, check=True).stdout
                    self.assertEqual(json.loads(lzma.decompress(final_contents)),
                                     updated)
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-list", "--count",
                            "main", "--", runner.GIT_RESULT,
                            cwd=sandbox).stdout.strip(), "2")
                    self.assertEqual(
                        git("--git-dir", str(origin), "show",
                            f"{after}:source.c", cwd=sandbox).stdout,
                        "int source(void){return 7;}\n")
                    self.assertEqual(
                        git("rev-parse", "HEAD", cwd=checkout).stdout.strip(),
                        next_parent)
                    self.assertIn("changed since testing",
                                  runner.publish(next_parent))

                    # A dirty user checkout must not be auto-committed/pushed.
                    git("pull", "--ff-only", "origin", "main", cwd=checkout)
                    current = git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
                    (checkout / "source.c").write_text("unsaved owner change\n")
                    runner.write_report({"source_sha": current,
                                         "tested_commit_sha": current,
                                         "overall": "FAIL"})
                    self.assertIn("not clean", runner.publish(current))
                    self.assertEqual(
                        git("--git-dir", str(origin), "rev-parse",
                            "refs/heads/main", cwd=sandbox).stdout.strip(),
                        after)
            finally:
                runner.ROOT, runner.REPORT = old_root, old_report

    def test_git_sync_declines_sandbox_and_invalid_source(self):
        with tempfile.TemporaryDirectory(
                prefix="publish-", dir=ROOT / "build/tests") as name:
            previous_root, previous_report = runner.ROOT, runner.REPORT
            try:
                runner.ROOT = Path(name)
                runner.REPORT = runner.ROOT / "build/test_results.json.xz"
                runner.write_report({"source_sha": "unknown",
                                     "overall": "BLOCKED"})
                self.assertIn("unavailable", runner.publish("unknown"))
                runner.write_report({"source_sha": "a" * 40,
                                     "tested_commit_sha": "a" * 40,
                                     "overall": "BLOCKED"})
                self.assertIn("checkout", runner.publish("a" * 40))
            finally:
                runner.ROOT, runner.REPORT = previous_root, previous_report


if __name__ == "__main__":
    (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
    unittest.main()
