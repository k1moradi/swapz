#!/usr/bin/env python3
"""Owner policy: only four user-visible root Make commands."""
import importlib.util
import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
MAKE = (ROOT / "Makefile").read_text()

class PublicMakeContract(unittest.TestCase):
    def test_exact_four_root_goals(self):
        targets = set()
        for line in MAKE.splitlines():
            if not line or line[0].isspace() or line.startswith("#") or line.startswith("."):
                continue
            m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):(?!=)", line)
            if m:
                targets.add(m.group(1))
        self.assertEqual(targets, {"all", "install", "uninstall", "test"})
        self.assertIn(".DEFAULT_GOAL := all", MAKE)
        self.assertIn("Only make, make install, make uninstall, make test", MAKE)
        self.assertNotIn("Only make -j2,", MAKE)
        self.assertIn(".PHONY: all install uninstall test", MAKE)
        self.assertNotIn(".NOTPARALLEL: test", MAKE)
        self.assertIn(".PHONY: build/kernel/experimental/dm-swapz.ko", MAKE)
        self.assertIn("all: build/kernel/experimental/dm-swapz.ko "
                      "build/tests/device-roundtrip build/userspace/swapzctl", MAKE)
        self.assertIn("@+python3 -B tests/tools/run-tests.py --kdir", MAKE)
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        for required in ("tests/tools/test-rootless.sh", "tests/tools/test-loaded.sh",
                         "W=1", "W=2", "test_results.json.xz",
                         "tested_commit_sha", "commit-tree", "mktree",
                         "GIT_TERMINAL_PROMPT", "SYNCED_GIT"):
            self.assertIn(required, reporter)
        self.assertNotIn("code_commit_sha", reporter)
        self.assertNotIn('"ls-remote"', reporter)
        self.assertNotIn('env["GIT_ASKPASS"] = "false"', reporter)
        self.assertNotIn('REPORT = ROOT / "build/test_results.json.xz"', reporter)
        self.assertIn("build/tests/device-roundtrip: tests/tools/device-roundtrip.c", MAKE)
        self.assertIn("build/userspace/swapzctl: src/userspace/swapzctl.c "
                      "src/kernel/VERSION", MAKE)
        staged = (ROOT / "src/kernel/Makefile").read_text()
        self.assertIn('cmp -s "$$src" "$$dst"', staged)
        self.assertIn("build/kernel/w1", staged)
        self.assertIn("build/kernel/w2", staged)
        self.assertNotIn('@cp -f "$(CURDIR)/Makefile"', staged)
        self.assertIn("MAKECMDGOALS", MAKE)
        multi = subprocess.run(["make", "-n", "install", "uninstall"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(multi.returncode, 0)
        for forbidden in ("all", "verify", "run", "deploy", "clean", "swapz",
                          "check", "test-codec", "bench-pair-medium"):
            p = subprocess.run(["make", "-n", "--no-print-directory", forbidden],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(p.returncode, 0, forbidden)

    def test_make_test_is_only_official_documented_test_command(self):
        canonical = ("docs/README.md", "docs/VISION.md",
                     "docs/coding_standards.md", "docs/testing_standards.md",
                     "docs/compile.md", "docs/benchmark.md")
        policy = "**Single official test command (read before every prompt):**"
        for document in canonical:
            with self.subTest(canonical=document):
                content = (ROOT / document).read_text()
                self.assertIn(policy, content)
                self.assertIn("Run `make test` at the repository root", content)
                self.assertIn("report BLOCKED (nonzero)", content)
                self.assertIn("Do not create, publish, recommend, or document "
                              "alternative test commands", content)

        testing = (ROOT / "docs/testing_standards.md").read_text()
        self.assertIn("~~~sh\nmake test\n~~~", testing)
        operator_docs = ("docs/README.md", "docs/testing_standards.md")
        for document in operator_docs:
            with self.subTest(official=document):
                content = (ROOT / document).read_text()
                for forbidden in ("make test-codec", "make test-mapping",
                                  "make test-gc", "make test-lower-io",
                                  "make -C tests/suites test-all",
                                  "sudo bash tests/tools/deploy-nullblk.sh",
                                  "sudo bash tests/tools/benchmark-owned-pair.sh"):
                    self.assertNotIn(forbidden, content,
                                     f"Nonofficial test instruction in {document}")
        self.assertIn("tests/tools/test-rootless.sh", (ROOT / "tests/tools/run-tests.py").read_text())
        self.assertIn("tests/tools/test-loaded.sh", (ROOT / "tests/tools/run-tests.py").read_text())

    def test_parallel_build_is_incremental_and_test_stages_stay_ordered(self):
        """Run the REAL root/extent Makefiles using a fake, unprivileged Kbuild.

        No module is inserted, no system files are changed, and all fake
        outputs remain inside build/. Re-running the full public command
        must not recompile byte-identical inputs.
        """
        import os
        import tempfile
        import time

        build_tests = ROOT / "build/tests"
        build_tests.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="make-incremental-",
                                         dir=build_tests) as directory:
            fixture = pathlib.Path(directory)
            for part in ("src/kernel", "src/userspace", "tests/tools",
                         "fake-headers"):
                (fixture / part).mkdir(parents=True, exist_ok=True)

            (fixture / "Makefile").write_text(MAKE)
            (fixture / "src/kernel/Makefile").write_text(
                (ROOT / "src/kernel/Makefile").read_text())
            (fixture / "src/kernel/VERSION").write_text(
                (ROOT / "src/kernel/VERSION").read_text())
            kernel_source = fixture / "src/kernel/dm-target.c"
            kernel_source.write_text("int fake_kernel_source = 1;\n")
            (fixture / "src/kernel/dummy.h").write_text(
                "#define FAKE_KERNEL_SOURCE 1\n")
            (fixture / "tests/tools/device-roundtrip.c").write_text(
                "int main(void) { return 0; }\n")
            cli = fixture / "src/userspace/swapzctl.c"
            cli.write_text("int main(void) { return 0; }\n")

            # This Kbuild substitute checks the staged source but
            # never compiles, loads, or inserts any kernel module.
            (fixture / "fake-headers/Makefile").write_text(
                ".PHONY: modules\n"
                "modules:\n"
                "\t@printf 'kbuild:%s\\n' '$(W)' >> '$(M)/../../order.log'\n"
                "\t@cat '$(M)/dm-target.c' '$(M)/swapz-version.h' > '$(M)/.module-candidate'\n"
                "\t@if ! cmp -s '$(M)/.module-candidate' '$(M)/dm-swapz.ko'; "
                "then cp '$(M)/.module-candidate' '$(M)/dm-swapz.ko'; fi\n"
                "\t@rm -f '$(M)/.module-candidate'\n")
            (fixture / "tests/tools/run-tests.py").write_text(
                (ROOT / "tests/tools/run-tests.py").read_text())
            (fixture / "tests/tools/test-rootless.sh").write_text(
                "#!/bin/bash\n"
                "set -eu\n"
                "test -f build/kernel/experimental/dm-swapz.ko\n"
                "test -x build/tests/device-roundtrip\n"
                "test -x build/userspace/swapzctl\n"
                "printf 'rootless\\n' >> build/order.log\n")
            # Synthetic records model eight latency-modeled RAM-only sessions;
            # mock Kbuild / loaded phase never touch actual host devices.
            import json
            # This is STILL an unprivileged mock; use a real Git checkout
            # commit identifier so the new source-provenance gate can
            # distinguish a valid same-revision fixture from a forged SHA.
            mocked_source_sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT,
                text=True, timeout=5).strip()
            runner_spec = importlib.util.spec_from_file_location(
                "swapz_fixture_runner", ROOT / "tests/tools/run-tests.py")
            runner_contract = importlib.util.module_from_spec(runner_spec)
            runner_spec.loader.exec_module(runner_contract)

            def mock_kernel_write(mode, target):
                record = {field: 0 for field in runner_contract.KERNEL_WRITE_FIELDS}
                record.update({
                    "physical_write_reqs": 5,
                    "lz4_wall_ns": 20000000,
                    "write_copy_wall_ns": 3000000,
                    "write_copy_bytes": 6000000,
                    "direct_lz4_input_pages": 3000,
                    "window_sort_wall_ns": 1000000,
                    "window_commit_wall_ns": 40000000,
                    "window_commit_nonio_wall_ns": 10000000,
                    "engine_plan_wall_ns": 1000000,
                    "engine_pack_wall_ns": 2000000,
                    "engine_publish_wall_ns": 3000000,
                    "engine_publish_crc_wall_ns": 1000000,
                    "engine_publish_auth_wall_ns": 2000000,
                    "engine_prehashed_records": 2500,
                    "batch_snapshot_crc_wall_ns": 250000,
                    "batch_pause_crc_wall_ns": 100000,
                    "batch_resume_crc_wall_ns": 150000,
                    "prep_crc_wall_ns": 700000,
                    "ordered_crc_wall_ns": 1300000,
                    "lower_write_wall_ns": 30000000,
                    "ordered_worker_wall_ns": 52000000,
                    "prep_worker_wall_ns": 5000000,
                    "ordered_worker_cpu_ns": 16000000,
                    "prep_worker_cpu_ns": 3000000,
                    "read_worker_cpu_ns": 1000000,
                    "prep_wait_wall_ns": 500000,
                    "prep_lower_write_overlap_ns": 5000000,
                    "prep_lower_write_samples": 5,
                    "prep_lower_write_start_queued": 4,
                    "prep_lower_write_start_nonempty": 3,
                    "prep_lower_write_end_queued": 1,
                    "prep_lower_write_end_nonempty": 1,
                    "pipeline_async_runs": 4 if mode else 0,
                    "pipeline_active_wall_ns": 800000000 if mode else 0,
                    "write_wait_le1ms": 2,
                    "write_wait_1to4ms": 2,
                    "write_wait_gt4ms": 1,
                    "retained_burst_target": target,
                    "windows": 20,
                    "one_page_windows": 4,
                    "win1": 4,
                    "win3_4": 8,
                    "win5_8": 8,
                    "close_idle": 4,
                    "close_deadline": 2,
                    "close_pack_ready": 14,
                    "pack_close_tail_target": 5,
                    "pack_close_tail_target_le4": 4,
                    "pack_close_burst_target": 6,
                    "pack_close_service_dry": 3,
                    "win1_idle": 1,
                    "win1_deadline": 2,
                    "win1_pack_ready": 1,
                    "win1_pack_tail_target": 1,
                    "win1_pack_read_bypass": 0,
                    "win1_pack_wave_interrupted": 0,
                    "single_tail_deferrals": 0,
                    "single_tail_companions": 0,
                    "win1_deadline_deferred_tail": 0,
                    "win1_idle_deferred_tail": 0,
                    "single_tail_other_clears": 0,
                    "deadline_before_bio": 1,
                    "deadline_worker_empty": 1,
                    "packed_early_commits": 8,
                    "single_pack_deferrals": 24,
                    "accepted_burst_extensions": 6,
                    "accepted_burst_tail_flushes": 5,
                    "accepted_burst_read_caps": 4,
                    "prep_lower_write_overlap_starts": 42 if mode else 0,
                    "prep_wave_kicks": 5 if mode else 0,
                    "prep_producer_head_claims": 2 if mode else 0,
                    "prep_producer_tail_claims": 3 if mode else 0,
                    "prep_ordered_inline": 4 if mode else 0,
                    "prep_ordered_handoffs": 3 if mode else 0,
                    "prep_ordered_waits": 1 if mode else 0,
                })
                return record

            def mock_lower_inflight(has_reads):
                read_mean = 0.25 if has_reads else 0.0
                return {
                    "target_interval_ns": 500000,
                    "samples": 4000,
                    "read_start": 0, "write_start": 0,
                    "read_end": 0, "write_end": 0,
                    "read_peak": 1 if has_reads else 0,
                    "write_peak": 1, "total_peak": 1,
                    "read_time_weighted": read_mean,
                    "write_time_weighted": 0.5,
                    "total_time_weighted": read_mean + 0.5,
                }

            def mock_arm(candidate, mode):
                is_swapz = candidate == "swapz"
                return json.dumps({
                    "candidate": candidate, "verdict": "PASS",
                    "source_sha": mocked_source_sha,
                    "fixture_sha256": "fake-fixture",
                    "trace_sha256": "fake-trace", "verified_pages": 1024,
                    "read_p95_ns": 4000000 if is_swapz else 8000000,
                    "read_p99_ns": 5000000 if is_swapz else 10000000,
                    "write_p99_ns": 3000000,
                    "seconds": 2,
                    "mixed_replay_cpu_user_s": 0.12,
                    "mixed_replay_cpu_system_s": 0.08,
                    "mixed_replay_peak_rss_kb": 10000,
                    "lower_inflight": mock_lower_inflight(True),
                    "kernel_write_path": (
                        mock_kernel_write(mode, 8) if is_swapz else None),
                    "packed_read": {
                        "logical_bytes": 4194304,
                        "logical_image_sha256": "m" * 64,
                        "packed_close_delta": 7 if is_swapz else None,
                        "passes": {
                            key: {
                                "logical_bytes": 4194304,
                                "verified_pages": 1024,
                                "verified_image_sha256": "m" * 64,
                                "seconds": 0.6 if is_swapz else 1.,
                                "useful_read_mbps": 7. if is_swapz else 4.,
                                "read_p99_ms": 3. if is_swapz else 4.,
                                "lower_io": {
                                    "lower_read_bytes": 4194304,
                                    "lower_read_requests": 1024,
                                },
                                # Mirror the loaded schema; rootless only
                                # fabricates counters for runner plumbing.
                                "kernel_read_path": ({
                                    "read_meta_reqs": 1024,
                                    "read_payload_reqs": 512,
                                    "read_payload_blocks": 512,
                                    "lower_read_wall_ns": 120000000,
                                    "decode_wall_ns": 20000000,
                                    "read_copy_wall_ns": 4000000,
                                    "read_copy_bytes": 4194304,
                                    "read_engine_nonio_wall_ns": 6000000,
                                    "read_meta_cache_hits": 128,
                    "read_meta_lru_hits": 100,
                    "read_full_extent_reqs": 200,
                    "read_full_cache_hits": 64,
                    "read_two_block_skips": 128,
                    "parallel_read_pairs": 128,
                    "parallel_read_same_extent_pairs": 64,
                    "read_worker_cpu_ns": 1000000,
                                } if is_swapz else None),
                            }
                            for key in ("sequential", "seeded_random")
                        },
                    },
                    "throughput_mbps": {
                        "logical_write_mbps": 20 if is_swapz else 14,
                        "lower_write_mbps": 12 if is_swapz else 14,
                        "logical_read_mbps": 6 if is_swapz else 4,
                        "logical_read_bytes": 4000,
                        "logical_write_bytes": 8000,
                    },
                    "lower_io": {
                        "lower_write_bytes": 5000 if is_swapz else 8000,
                        "lower_read_bytes": 4000,
                        "lower_write_requests": 5 if is_swapz else 8,
                        "lower_read_requests": 4
                    }
                }, sort_keys=True)
            def mock_parallel_arm(enabled):
                record = json.loads(mock_arm("swapz", 0))
                for phase in record["packed_read"]["passes"].values():
                    if not enabled:
                        phase["kernel_read_path"]["parallel_read_pairs"] = 0
                        phase["kernel_read_path"]["parallel_read_same_extent_pairs"] = 0
                return json.dumps(record, sort_keys=True)

            def mock_write_arm(candidate, qd, mode):
                is_swapz = candidate == "swapz"
                logical = 4096 * 4096
                lower = int(logical / 1.4) if is_swapz else logical
                return json.dumps({
                    "candidate": candidate, "verdict": "PASS",
                    "source_sha": mocked_source_sha,
                    "fixture_sha256": "fake-fixture",
                    "trace_sha256": ("f" * 60) + f"{qd:04x}",
                    "write_p99_ns": 3000000,
                    "seconds": 2,
                    "mixed_replay_cpu_user_s": 0.12,
                    "mixed_replay_cpu_system_s": 0.08,
                    "mixed_replay_peak_rss_kb": 10000,
                    "lower_inflight": mock_lower_inflight(False),
                    "kernel_write_path": (
                        mock_kernel_write(mode, max(4, qd))
                        if is_swapz else None),
                    "throughput_mbps": {
                        "logical_write_mbps": 20 if is_swapz else 14,
                        "lower_write_mbps": 12 if is_swapz else 14,
                        "logical_read_mbps": 0,
                        "logical_read_bytes": 0,
                        "logical_write_bytes": logical,
                    },
                    "lower_io": {
                        "lower_write_bytes": lower,
                        "lower_read_bytes": 0,
                        "lower_write_requests": 5 if is_swapz else 8,
                        "lower_read_requests": 0,
                    },
                }, sort_keys=True)

            records = [
                "PASS_LOADED_ORACLE_PROFILE=raw_pages:64 zero_pages:9 flush_calls:2",
                "PASS_LOADED_LIVE_GC=victims:12 rotations:12 pages:12 read_bytes:49152 write_bytes:49152 read_reqs:12 write_reqs:12 distinct:6 victim_min:1 victim_max:3 last:11->29 verified_pages:4096",
                "PASS_LOADED_SUSPEND_DRAIN=retain_ms:4 observed_open:1 verified_pages:128",
                "PASS_RETAINED_SYNTHETIC_WRITE_FAULT=retain_ms:2 injected:1 lower_write_delta:0",
                "PASS_RETAINED_SYNTHETIC_FLUSH_FAULT=retain_ms:2 injected:1 data_write_reached_lower:1",
            ]
            specs = (("sd_emulated", 10, 1000000, 2, 2, 1, 1),
                     ("ssd_emulated", 80, 150000, 2, 2, 1, 64))
            confirmation = (0, 1, 1, 0, 0, 1, 1, 0, 0, 1)
            for regime, cap, ns, irq, queue_mode, submit_queues, hw_depth in specs:
                records.append(f"START_OWNED_RAM_REGIME={regime}")
                modes = confirmation if regime == "ssd_emulated" else (0, 1, 1, 0)
                for i, mode in enumerate(modes):
                    records.extend((
                        f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                        "REPLAY_ORDER=swapz-first" if i % 2 else "REPLAY_ORDER=off-first",
                        f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                        "SWAPZ_STATUS_BEFORE=windows=0 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=0 close_pack_ready=0 burst_tail_flushes=0 packed_early_commits=0 single_pack_deferrals=0 accepted_burst_extensions=0 accepted_burst_tail_flushes=0 accepted_burst_read_caps=0 accepted_burst_cap_extra_blocks=0 accepted_burst_cap_extra_gt1_windows=0 accepted_burst_four_extents_avoided=0 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=0 accepted_burst_cap3_recovered_blocks=0 accepted_burst_cap3_full_recovery_windows=0 one_page_windows=0 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=0 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=0 win1_pack_ready=0 win1_pack_tail_target=0 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=0 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=0 prep_producer_head_claims=0 prep_producer_tail_claims=0 prep_ordered_inline=0 prep_ordered_handoffs=0 prep_ordered_waits=0 prep_lower_write_overlap_starts=0 prep_wave_kicks=0",
                        f"SWAPZ_STATUS_AFTER=windows=20 close_unknown=0 close_full=0 close_duplicate=0 close_zero=0 close_fua=0 close_raw=0 close_read_conflict=0 close_read_unrelated=0 close_discard=0 close_preflush=0 close_quantum=0 close_idle=0 close_shutdown=0 close_other=0 close_deadline=2 close_pack_ready=18 burst_tail_flushes=7 packed_early_commits=8 single_pack_deferrals=24 accepted_burst_extensions=6 accepted_burst_tail_flushes=5 accepted_burst_read_caps=4 accepted_burst_cap_extra_blocks=4 accepted_burst_cap_extra_gt1_windows=1 accepted_burst_four_extents_avoided=8 accepted_burst_plan_stats_failures=0 accepted_burst_cap3_pareto_candidates=1 accepted_burst_cap3_recovered_blocks=2 accepted_burst_cap3_full_recovery_windows=1 one_page_windows=4 gc_victims=0 gc_role_rotations=0 win1_unknown=0 win1_full=0 win1_duplicate=0 win1_zero=0 win1_fua=0 win1_raw=0 win1_read_conflict=0 win1_read_unrelated=1 win1_discard=0 win1_preflush=0 win1_quantum=0 win1_idle=0 win1_shutdown=0 win1_other=0 win1_deadline=2 win1_pack_ready=1 win1_pack_tail_target=1 win1_pack_read_bypass=0 win1_pack_wave_interrupted=0 single_tail_deferrals=0 single_tail_companions=0 win1_deadline_deferred_tail=0 win1_idle_deferred_tail=0 single_tail_other_clears=0 deadline_before_bio=1 deadline_after_read=0 deadline_worker_with_local=0 deadline_worker_empty=1 prep_producer_head_claims={2 if mode else 0} prep_producer_tail_claims={3 if mode else 0} prep_ordered_inline={4 if mode else 0} prep_ordered_handoffs={3 if mode else 0} prep_ordered_waits={1 if mode else 0} prep_lower_write_overlap_starts={42 if mode else 0} prep_wave_kicks={5 if mode else 0}",
                        mock_arm("swapz", mode) if i % 2 else mock_arm("off", mode),
                        mock_arm("off", mode) if i % 2 else mock_arm("swapz", mode),
                        f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                    ))
                records.append(f"PASS_OWNED_RAM_REGIME={regime}")
            cap, ns, irq, queue_mode, submit_queues, hw_depth = (80, 150000, 2, 2, 1, 64)
            for index, enabled in enumerate(confirmation):
                records.extend((
                    f"START_PARALLEL_READ_AB={enabled}",
                    "REPLAY_ORDER=swapz-first" if index % 2 else "REPLAY_ORDER=off-first",
                    f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                    mock_parallel_arm(enabled) if index % 2 else mock_arm("off", 0),
                    mock_arm("off", 0) if index % 2 else mock_parallel_arm(enabled),
                    f"PASS_PARALLEL_READ_AB={enabled}",
                ))
            for regime, cap, ns, irq, queue_mode, submit_queues, hw_depth in specs:
                records.append(f"START_WRITE_SATURATION_REGIME={regime}")
                index = 0
                for qd in (1, 4, 8, 32):
                    modes = (confirmation
                             if regime == "ssd_emulated" and qd == 8
                             else (0, 1))
                    for mode in modes:
                        records.extend((
                            f"START_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}",
                            "REPLAY_ORDER=swapz-first" if index % 2 else "REPLAY_ORDER=off-first",
                            f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq} QUEUE_MODE={queue_mode} SUBMIT_QUEUES={submit_queues} HW_QUEUE_DEPTH={hw_depth}",
                            "SWAPZ_STATUS_BEFORE=windows=0 one_page_windows=0 "
                            "win1=0 win2=0 win3_4=0 win5_8=0 win9_16=0 "
                            "win17_64=0 close_idle=0 close_deadline=0 "
                            "close_pack_ready=0 retained_burst_target=4 "
                            "prep_producer_head_claims=0 prep_producer_tail_claims=0 "
                            "prep_ordered_inline=0 prep_ordered_handoffs=0 "
                            "prep_ordered_waits=0 prep_lower_write_overlap_starts=0 "
                            "prep_wave_kicks=0",
                            "SWAPZ_STATUS_AFTER=windows=20 one_page_windows=4 "
                            "win1=4 win2=0 win3_4=8 win5_8=8 win9_16=0 "
                            "win17_64=0 close_idle=4 close_deadline=2 "
                            f"close_pack_ready=14 retained_burst_target={max(4, qd)} "
                            f"prep_producer_head_claims={2 if mode else 0} "
                            f"prep_producer_tail_claims={3 if mode else 0} "
                            f"prep_ordered_inline={4 if mode else 0} "
                            f"prep_ordered_handoffs={3 if mode else 0} "
                            f"prep_ordered_waits={1 if mode else 0} "
                            f"prep_lower_write_overlap_starts={42 if mode else 0} "
                            f"prep_wave_kicks={5 if mode else 0}",
                            mock_write_arm("swapz", qd, mode) if index % 2 else mock_write_arm("off", qd, mode),
                            mock_write_arm("off", qd, mode) if index % 2 else mock_write_arm("swapz", qd, mode),
                            f"PASS_WRITE_SATURATION_PAIR_QD={qd} ASYNC_PREPARE={mode}",
                        ))
                        index += 1
                records.append(f"PASS_WRITE_SATURATION_REGIME={regime}")
            script = ("#!/bin/bash\nset -eu\n"
                      "test \"$(tail -n 1 build/order.log)\" = 'kbuild:2'\n"
                      "printf 'loaded\\n' >> build/order.log\n"
                      "cat <<'MOCK_RECORDS'\n" + "\n".join(records) +
                      "\nMOCK_RECORDS\n")
            (fixture / "tests/tools/test-loaded.sh").write_text(script)

            env = os.environ.copy()
            env.pop("MAKEFLAGS", None)
            env.pop("MFLAGS", None)
            env.pop("W", None)

            def execute():
                proc = subprocess.run(
                    ["make", "-j2", "test",
                     f"KDIR={fixture / 'fake-headers'}"],
                    cwd=fixture, env=env, capture_output=True, text=True,
                    timeout=30)
                self.assertEqual(proc.returncode, 0,
                                 proc.stdout + "\n" + proc.stderr)
                order = (fixture / "build/order.log").read_text().splitlines()
                self.assertEqual(order[-5:],
                                 ["kbuild:", "rootless", "kbuild:1",
                                  "kbuild:2", "loaded"])

            module = fixture / "build/kernel/experimental/dm-swapz.ko"
            staged = fixture / "build/kernel/experimental/dm-target.c"
            staged_make = fixture / "build/kernel/experimental/Makefile"
            w1_module = fixture / "build/kernel/w1/dm-swapz.ko"
            w2_module = fixture / "build/kernel/w2/dm-swapz.ko"
            w1_staged = fixture / "build/kernel/w1/dm-target.c"
            w2_staged = fixture / "build/kernel/w2/dm-target.c"
            device = fixture / "build/tests/device-roundtrip"
            cli_out = fixture / "build/userspace/swapzctl"
            execute()
            tracked = (module, w1_module, w2_module, staged,
                       w1_staged, w2_staged, staged_make, device, cli_out)
            first = {p: p.stat().st_mtime_ns for p in tracked}
            execute()
            self.assertEqual(first,
                             {p: p.stat().st_mtime_ns for p in tracked},
                             "An unchanged make test -j2 must reuse binaries "
                             "and staged kernel sources")

            time.sleep(0.03)
            cli.write_text("int main(void) { return 1; }\n")
            execute()
            self.assertGreater(cli_out.stat().st_mtime_ns, first[cli_out])
            for p in (module, w1_module, w2_module, staged,
                      w1_staged, w2_staged, staged_make, device):
                self.assertEqual(first[p], p.stat().st_mtime_ns, str(p))

            second = {p: p.stat().st_mtime_ns for p in tracked}
            time.sleep(0.03)
            kernel_source.write_text("int fake_kernel_source = 2;\n")
            execute()
            self.assertEqual(staged.read_text(), kernel_source.read_text())
            self.assertGreater(staged.stat().st_mtime_ns, second[staged])
            for p in (module, w1_module, w2_module, w1_staged, w2_staged):
                self.assertGreater(p.stat().st_mtime_ns, second[p])
            for p in (staged_make, device, cli_out):
                self.assertEqual(second[p], p.stat().st_mtime_ns, str(p))

            # Changing only canonical VERSION must regenerate every kernel
            # staging header and dependent module, without editing Kbuild or C.
            from_version = fixture / "src/kernel/VERSION"
            to_version = "3.0.0-alpha.99\n"
            if from_version.read_text() == to_version:
                to_version = "3.0.0-alpha.100\n"
            headers = [fixture / "build/kernel" / kind / "swapz-version.h"
                       for kind in ("experimental", "w1", "w2")]
            before_version = [p.stat().st_mtime_ns for p in headers]
            before_module = [p.stat().st_mtime_ns
                             for p in (module, w1_module, w2_module)]
            time.sleep(0.03)
            from_version.write_text(to_version)
            execute()
            for p, old_mtime in zip(headers, before_version):
                self.assertGreater(p.stat().st_mtime_ns, old_mtime)
                self.assertIn(to_version.strip(), p.read_text())
            for p, old_mtime in zip(
                    (module, w1_module, w2_module), before_module):
                self.assertGreater(p.stat().st_mtime_ns, old_mtime)

    def test_packaging_and_loaded_tests_are_bounded(self):
        self.assertIn("packaging/package-dkms.sh install", MAKE)
        self.assertIn("packaging/package-dkms.sh uninstall", MAKE)
        self.assertIn("tests/tools/test-rootless.sh", (ROOT / "tests/tools/run-tests.py").read_text())
        rootless_test_recipe = MAKE.split("\ntest:\n", 1)[1]
        self.assertIn("tests/tools/run-tests.py", rootless_test_recipe)
        reporter = (ROOT / "tests/tools/run-tests.py").read_text()
        self.assertIn("tests/tools/test-rootless.sh", reporter)
        self.assertIn("tests/tools/test-loaded.sh", reporter)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        self.assertLess(reporter.index('"Native and rootless contracts"'),
                        reporter.index('"Kernel warnings W=1"'))
        self.assertLess(reporter.index('"Kernel warnings W=2"'),
                        reporter.index('"Owned RAM smoke + mixed/QD pilot"'))
        for privileged in ("sudo -v", "sudo bash", "modprobe", "dmsetup"):
            self.assertNotIn(privileged, rootless_test_recipe)
        loaded = (ROOT / "tests/tools/test-loaded.sh").read_text()
        self.assertIn("sudo -n true", loaded)
        self.assertIn("sudo -n bash", loaded)
        self.assertIn("BLOCKED_LOADED_QUALIFICATION", loaded)
        self.assertIn("tests/tools/deploy-nullblk.sh", loaded)
        self.assertIn("tests/tools/benchmark-owned-pair.sh", loaded)
        self.assertIn("--lower-mbps 10 --hw-queue-depth 1 --completion-nsec 1000000", loaded)
        self.assertIn("--lower-mbps 80 --hw-queue-depth 64 --completion-nsec 150000", loaded)
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertIn("--async-prepare", loaded)
        self.assertIn("confirmation_modes=(0 1 1 0 0 1 1 0 0 1)", loaded)
        self.assertIn('for async_prepare in "${modes[@]}"', loaded)
        self.assertIn('for parallel_reads in "${confirmation_modes[@]}"', loaded)
        self.assertIn("for qd in 1 4 8 32", loaded)
        self.assertIn("--write-only-qd", loaded)
        self.assertIn("START_WRITE_SATURATION_PAIR_QD=", loaded)
        self.assertLess(loaded.index("tests/tools/deploy-nullblk.sh"),
                        loaded.index("tests/tools/benchmark-owned-pair.sh"))
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertIn("--shared-plan", loaded)
        self.assertIn("--swapz-first", loaded)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        package = (ROOT / "packaging/package-dkms.sh").read_text()
        for token in ("AUTOINSTALL", '"$dkms_bin" add', '"$dkms_bin" build',
                      '"$dkms_bin" install', '"$dkms_bin" remove',
                      "swapz:", "/sys/module/dm_swapz"):
            self.assertIn(token, package)
        self.assertNotIn("swapon ", package)
        self.assertNotIn("swapoff ", package)
        self.assertIn("swapzctl", package)
        self.assertIn("src/userspace/swapzctl.c", MAKE)
        self.assertIn("tests/runtime/native/package-dkms-test.py", (ROOT / "tests/tools/test-rootless.sh").read_text())
        ci = (ROOT / ".github/workflows/project-goals.yml").read_text()
        self.assertIn("bash tests/tools/test-rootless.sh", ci)
        self.assertNotIn("make verify", ci)

if __name__ == "__main__":
    unittest.main()
