#!/usr/bin/env python3
"""Hermetic rootless mock-DKMS installation and rollback tests."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / "build/tests/package-sandbox"
VERSION = (ROOT / "kernel/extent-v3/VERSION").read_text().strip()
SCRIPT = ROOT / "tools/package-dkms.sh"

class PackageLifecycle(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("package test requires nonroot (root test mode forbidden)")
        BASE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name).resolve()
        (self.home / "bin").mkdir()
        dkms = self.home / "bin/dkms"
        dkms.write_text("""#!/usr/bin/env bash
set -eu
printf '%s\\n' "$1" >> "$SWAPZ_DKMS_LOG"
[[ "$1" != "$SWAPZ_FAKE_FAIL_AT" ]] || exit 44
if [[ "$1" == status ]]; then echo 'swapz fake: installed'; fi
""")
        dkms.chmod(0o755)
        self.log = self.home / "dkms.log"
        self.env = dict(os.environ, SWAPZ_PACKAGE_TEST_ROOT=str(self.home),
                        SWAPZ_DKMS_LOG=str(self.log), SWAPZ_FAKE_FAIL_AT="never")
        self.env["PATH"] = str(self.home / "bin") + os.pathsep + self.env["PATH"]
        self.prefix = self.home / "usr/local"
        (ROOT / "build/userspace").mkdir(parents=True, exist_ok=True)
        (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        '-DSWAPZ_VERSION="' + VERSION + '"',
                        str(ROOT / "userspace/swapz3ctl.c"), "-o",
                        str(ROOT / "build/userspace/swapz3ctl")], check=True)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tools/device-roundtrip.c"), "-o",
                        str(ROOT / "build/tests/device-roundtrip")], check=True)

    def invoke(self, command, extra=None):
        env = dict(self.env)
        if extra:
            env.update(extra)
        return subprocess.run(["bash", str(SCRIPT), command, str(self.prefix)],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    def test_install_uninstall_versions_and_safe_cli(self):
        r = self.invoke("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        binary = self.prefix / "sbin/swapz3ctl"
        self.assertTrue(binary.is_file())
        version = subprocess.run([binary, "version"], capture_output=True, text=True)
        self.assertIn(VERSION, version.stdout)
        self.assertEqual(subprocess.run([binary, "status"], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run([binary, "start", "/dev/sda"],
                         capture_output=True).returncode, 2)
        self.assertNotEqual(self.invoke("install").returncode, 0)
        r = self.invoke("uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(binary.exists())
        self.assertFalse((self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertEqual(self.log.read_text().splitlines(),
                         ["add", "build", "install", "status", "remove"])
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)

    def test_tamper_and_dkms_failure_keep_owned_files(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        binary = self.prefix / "sbin/swapz3ctl"
        original = binary.read_bytes()
        binary.write_bytes(b"tampered")
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)
        binary.write_bytes(original)
        self.assertNotEqual(self.invoke("uninstall", {"SWAPZ_FAKE_FAIL_AT": "remove"}).returncode, 0)
        self.assertTrue(binary.exists())
        self.assertEqual(self.invoke("uninstall").returncode, 0)

    def test_failed_dkms_build_rolls_back(self):
        r = self.invoke("install", {"SWAPZ_FAKE_FAIL_AT": "build"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.prefix / "sbin/swapz3ctl").exists())
        self.assertFalse((self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertIn("remove", self.log.read_text().splitlines())

    def test_bogus_prefix_rejected_before_disk_changes(self):
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)
        for prefix in ("/", "/tmp/../wrong", "/usr/local"):
            r = subprocess.run(["bash", str(SCRIPT), "install", prefix],
                               cwd=ROOT, env=self.env, capture_output=True)
            self.assertNotEqual(r.returncode, 0)
        self.assertNotEqual(self.invoke("invalid").returncode, 0)

if __name__ == "__main__":
    unittest.main()
