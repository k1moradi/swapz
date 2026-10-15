#!/usr/bin/env python3
"""Owner policy: only four user-visible root Make commands."""
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
                      "build/tests/device-roundtrip build/userspace/swapz3ctl", MAKE)
        self.assertIn("@+python3 -B tools/run-tests.py --kdir", MAKE)
        reporter = (ROOT / "tools/run-tests.py").read_text()
        for required in ("tools/test-rootless.sh", "tools/test-loaded.sh",
                         "W=1", "W=2", "build/test_results.json.xz",
                         "tested_commit_sha", "code_commit_sha",
                         "commit-tree", "mktree", "ls-remote", "push"):
            self.assertIn(required, reporter)
        self.assertIn("build/tests/device-roundtrip: tools/device-roundtrip.c", MAKE)
        self.assertIn("build/userspace/swapz3ctl: userspace/swapz3ctl.c "
                      "kernel/extent-v3/VERSION", MAKE)
        staged = (ROOT / "kernel/extent-v3/Makefile").read_text()
        self.assertIn('cmp -s "$$src" "$$dst"', staged)
        self.assertIn("build/kernel/w1", staged)
        self.assertIn("build/kernel/w2", staged)
        self.assertNotIn('@cp -f "$(CURDIR)/Makefile"', staged)
        self.assertIn("MAKECMDGOALS", MAKE)
        multi = subprocess.run(["make", "-n", "install", "uninstall"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(multi.returncode, 0)
        for forbidden in ("all", "verify", "run", "deploy", "clean", "v3",
                          "check", "test-codec", "bench-pair-medium"):
            p = subprocess.run(["make", "-n", "--no-print-directory", forbidden],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(p.returncode, 0, forbidden)

    def test_make_test_is_only_official_documented_test_command(self):
        canonical = ("AGENTS.md", "README.md", "VISION.md",
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
        operator_docs = ("README.md", "docs/testing_standards.md",
                         "tests/runtime/README.md", "tests/suites/README.md")
        for document in operator_docs:
            with self.subTest(official=document):
                content = (ROOT / document).read_text()
                for forbidden in ("make test-codec", "make test-mapping",
                                  "make test-gc", "make test-lower-io",
                                  "make -C tests/suites test-all",
                                  "sudo bash tools/deploy-nullblk.sh",
                                  "sudo bash tools/benchmark-owned-pair.sh"):
                    self.assertNotIn(forbidden, content,
                                     f"Nonofficial test instruction in {document}")
        self.assertIn("tools/test-rootless.sh", (ROOT / "tools/run-tests.py").read_text())
        self.assertIn("tools/test-loaded.sh", (ROOT / "tools/run-tests.py").read_text())

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
            for part in ("kernel/extent-v3", "tools", "userspace",
                         "fake-headers"):
                (fixture / part).mkdir(parents=True, exist_ok=True)

            (fixture / "Makefile").write_text(MAKE)
            (fixture / "kernel/extent-v3/Makefile").write_text(
                (ROOT / "kernel/extent-v3/Makefile").read_text())
            (fixture / "kernel/extent-v3/VERSION").write_text(
                (ROOT / "kernel/extent-v3/VERSION").read_text())
            kernel_source = fixture / "kernel/extent-v3/dm-target.c"
            kernel_source.write_text("int fake_kernel_source = 1;\n")
            (fixture / "kernel/extent-v3/dummy.h").write_text(
                "#define FAKE_KERNEL_SOURCE 1\n")
            (fixture / "tools/device-roundtrip.c").write_text(
                "int main(void) { return 0; }\n")
            cli = fixture / "userspace/swapz3ctl.c"
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
            (fixture / "tools/run-tests.py").write_text(
                (ROOT / "tools/run-tests.py").read_text())
            (fixture / "tools/test-rootless.sh").write_text(
                "#!/bin/bash\n"
                "set -eu\n"
                "test -f build/kernel/experimental/dm-swapz.ko\n"
                "test -x build/tests/device-roundtrip\n"
                "test -x build/userspace/swapz3ctl\n"
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
            def mock_arm(candidate):
                is_v3 = candidate == "v3"
                return json.dumps({
                    "candidate": candidate, "verdict": "PASS",
                    "source_sha": mocked_source_sha,
                    "fixture_sha256": "fake-fixture",
                    "trace_sha256": "fake-trace", "verified_pages": 1024,
                    "read_p95_ns": 4000000 if is_v3 else 8000000,
                    "read_p99_ns": 5000000 if is_v3 else 10000000,
                    "write_p99_ns": 3000000,
                    "seconds": 2,
                    "mixed_replay_cpu_user_s": 0.12,
                    "mixed_replay_cpu_system_s": 0.08,
                    "mixed_replay_peak_rss_kb": 10000,
                    "packed_read": {
                        "logical_bytes": 4194304,
                        "logical_image_sha256": "m" * 64,
                        "packed_close_delta": 7 if is_v3 else None,
                        "passes": {
                            key: {
                                "logical_bytes": 4194304,
                                "verified_pages": 1024,
                                "verified_image_sha256": "m" * 64,
                                "seconds": 0.6 if is_v3 else 1.,
                                "useful_read_mbps": 7. if is_v3 else 4.,
                                "read_p99_ms": 3. if is_v3 else 4.,
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
                                } if is_v3 else None),
                            }
                            for key in ("sequential", "seeded_random")
                        },
                    },
                    "throughput_mbps": {
                        "logical_write_mbps": 20 if is_v3 else 14,
                        "lower_write_mbps": 12 if is_v3 else 14,
                        "logical_read_mbps": 6 if is_v3 else 4,
                        "logical_read_bytes": 4000,
                        "logical_write_bytes": 8000,
                    },
                    "lower_io": {
                        "lower_write_bytes": 5000 if is_v3 else 8000,
                        "lower_read_bytes": 4000,
                        "lower_write_requests": 5 if is_v3 else 8,
                        "lower_read_requests": 4
                    }
                }, sort_keys=True)
            records = []
            specs = (("sd_emulated", 10, 1000000, 2),
                     ("ssd_emulated", 80, 150000, 2))
            for regime, cap, ns, irq in specs:
                records.append(f"START_OWNED_RAM_REGIME={regime}")
                for i, mode in enumerate((0, 1, 1, 0)):
                    records.extend((
                        f"START_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                        "REPLAY_ORDER=v3-first" if i % 2 else "REPLAY_ORDER=off-first",
                        f"PASS_RAM_MODEL_LOWER_MBPS={cap} COMPLETION_NSEC={ns} IRQMODE={irq}",
                        "V3_STATUS_BEFORE=close_pack_ready=0 burst_tail_flushes=0 packed_early_commits=0 one_page_windows=0 gc_victims=0 gc_role_rotations=0",
                        "V3_STATUS_AFTER=close_pack_ready=32 burst_tail_flushes=7 packed_early_commits=8 one_page_windows=4 gc_victims=0 gc_role_rotations=0",
                        mock_arm("v3") if i % 2 else mock_arm("off"),
                        mock_arm("off") if i % 2 else mock_arm("v3"),
                        f"PASS_OWNED_RAM_PAIR_ASYNC_PREPARE={mode}",
                    ))
                records.append(f"PASS_OWNED_RAM_REGIME={regime}")
            script = ("#!/bin/bash\nset -eu\n"
                      "test \"$(tail -n 1 build/order.log)\" = 'kbuild:2'\n"
                      "printf 'loaded\\n' >> build/order.log\n"
                      "cat <<'MOCK_RECORDS'\n" + "\n".join(records) +
                      "\nMOCK_RECORDS\n")
            (fixture / "tools/test-loaded.sh").write_text(script)

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
            cli_out = fixture / "build/userspace/swapz3ctl"
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
            from_version = fixture / "kernel/extent-v3/VERSION"
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
        self.assertIn("tools/package-dkms.sh install", MAKE)
        self.assertIn("tools/package-dkms.sh uninstall", MAKE)
        self.assertIn("tools/test-rootless.sh", (ROOT / "tools/run-tests.py").read_text())
        rootless_test_recipe = MAKE.split("\ntest:\n", 1)[1]
        self.assertIn("tools/run-tests.py", rootless_test_recipe)
        reporter = (ROOT / "tools/run-tests.py").read_text()
        self.assertIn("tools/test-rootless.sh", reporter)
        self.assertIn("tools/test-loaded.sh", reporter)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        self.assertLess(reporter.index('"Native and rootless contracts"'),
                        reporter.index('"Kernel warnings W=1"'))
        self.assertLess(reporter.index('"Kernel warnings W=2"'),
                        reporter.index('"Owned RAM smoke and 8 pairs"'))
        for privileged in ("sudo -v", "sudo bash", "modprobe", "dmsetup"):
            self.assertNotIn(privileged, rootless_test_recipe)
        loaded = (ROOT / "tools/test-loaded.sh").read_text()
        self.assertIn("sudo -n true", loaded)
        self.assertIn("sudo -n bash", loaded)
        self.assertIn("BLOCKED_LOADED_QUALIFICATION", loaded)
        self.assertIn("tools/deploy-nullblk.sh", loaded)
        self.assertIn("tools/benchmark-owned-pair.sh", loaded)
        self.assertIn("--lower-mbps 10 --completion-nsec 1000000", loaded)
        self.assertIn("--lower-mbps 80 --completion-nsec 150000", loaded)
        self.assertIn("for regime in sd_emulated ssd_emulated", loaded)
        self.assertIn("--async-prepare", loaded)
        self.assertIn("for async_prepare in 0 1 1 0", loaded)
        self.assertLess(loaded.index("tools/deploy-nullblk.sh"),
                        loaded.index("tools/benchmark-owned-pair.sh"))
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertIn("--shared-plan", loaded)
        self.assertIn("--v3-first", loaded)
        self.assertIn("W=1", reporter)
        self.assertIn("W=2", reporter)
        package = (ROOT / "tools/package-dkms.sh").read_text()
        for token in ("AUTOINSTALL", '"$dkms_bin" add', '"$dkms_bin" build',
                      '"$dkms_bin" install', '"$dkms_bin" remove',
                      "swapz-v3:", "/sys/module/dm_swapz"):
            self.assertIn(token, package)
        self.assertNotIn("swapon ", package)
        self.assertNotIn("swapoff ", package)
        self.assertIn("swapz3ctl", package)
        self.assertIn("userspace/swapz3ctl.c", MAKE)
        self.assertIn("tests/runtime/native/package-dkms-test.py", (ROOT / "tools/test-rootless.sh").read_text())
        ci = (ROOT / ".github/workflows/project-goals.yml").read_text()
        self.assertIn("bash tools/test-rootless.sh", ci)
        self.assertNotIn("make verify", ci)

if __name__ == "__main__":
    unittest.main()
