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
        self.assertIn(".PHONY: all install uninstall test", MAKE)
        self.assertIn(".NOTPARALLEL: test", MAKE)
        self.assertIn("MAKECMDGOALS", MAKE)
        multi = subprocess.run(["make", "-n", "install", "uninstall"],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(multi.returncode, 0)
        for forbidden in ("all", "verify", "run", "deploy", "clean", "v3",
                          "check", "test-codec", "bench-pair-medium"):
            p = subprocess.run(["make", "-n", "--no-print-directory", forbidden],
                               cwd=ROOT, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(p.returncode, 0, forbidden)

    def test_packaging_and_loaded_tests_are_bounded(self):
        self.assertIn("tools/package-dkms.sh install", MAKE)
        self.assertIn("tools/package-dkms.sh uninstall", MAKE)
        self.assertIn("tools/test-rootless.sh", MAKE)
        rootless_test_recipe = MAKE.split("\ntest: all\n", 1)[1]
        self.assertIn("tools/test-rootless.sh", rootless_test_recipe)
        self.assertIn("W=1 all", rootless_test_recipe)
        self.assertIn("W=2 all", rootless_test_recipe)
        # make test must execute the loaded test/benchmark or fail BLOCKED.
        # No sudo password prompt or device actions in the make recipe.
        self.assertIn("bash tools/test-loaded.sh", rootless_test_recipe)
        for privileged in ("sudo -v", "sudo bash", "modprobe", "dmsetup"):
            self.assertNotIn(privileged, rootless_test_recipe)
        loaded = (ROOT / "tools/test-loaded.sh").read_text()
        self.assertIn("sudo -n true", loaded)
        self.assertIn("sudo -n bash", loaded)
        self.assertIn("BLOCKED_LOADED_QUALIFICATION", loaded)
        self.assertIn("tools/deploy-nullblk.sh", loaded)
        self.assertIn("tools/benchmark-owned-pair.sh", loaded)
        self.assertIn("--lower-mbps 20", loaded)
        self.assertIn("--async-prepare", loaded)
        self.assertIn("for async_prepare in 0 1 1 0", loaded)
        self.assertLess(loaded.index("tools/deploy-nullblk.sh"),
                        loaded.index("tools/benchmark-owned-pair.sh"))
        self.assertNotIn("swapon ", loaded)
        self.assertNotIn("swapoff ", loaded)
        self.assertIn("W=1 all", MAKE)
        self.assertIn("W=2 all", MAKE)
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
