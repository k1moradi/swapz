#!/usr/bin/env python3
"""Hermetic rootless mock-DKMS installation and rollback tests."""
import os
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[3]
BASE = ROOT / "build/tests/package-sandbox"
VERSION = (ROOT / "src/kernel/VERSION").read_text().strip()
SCRIPT = ROOT / "packaging/package-dkms.sh"

class PackageLifecycle(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("package test requires nonroot (root test mode forbidden)")
        BASE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.home = pathlib.Path(self.temp.name).resolve()
        (self.home / "build").mkdir()
        self.build_info = self.home / "build/source-build-info.h"
        self.build_info.write_text(
            '#define SWAPZ_BUILD_SOURCE_SHA "'
            '0123456789abcdef0123456789abcdef01234567"\n'
            "#define SWAPZ_BUILD_SOURCE_CLEAN 1\n")
        self.module_artifact = self.home / "build/dm-swapz.ko"
        self.module_artifact.write_bytes(b"synthetic-qualified-dm-swapz-module\n")
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
                        SWAPZ_DKMS_LOG=str(self.log), SWAPZ_FAKE_FAIL_AT="never",
                        SWAPZ_TEST_BUILD_INFO=str(self.build_info),
                        SWAPZ_TEST_MODULE_ARTIFACT=str(self.module_artifact))
        self.env["PATH"] = str(self.home / "bin") + os.pathsep + self.env["PATH"]
        self.prefix = self.home / "usr/local"
        (ROOT / "build/userspace").mkdir(parents=True, exist_ok=True)
        (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-include", str(self.build_info),
                        '-DSWAPZ_VERSION="' + VERSION + '"',
                        str(ROOT / "src/userspace/swapzctl.c"),
                        str(ROOT / "src/userspace/swapz-primary.c"), "-o",
                        str(ROOT / "build/userspace/swapzctl")], check=True)
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/tools/device-roundtrip.c"), "-o",
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
        binary = self.prefix / "sbin/swapzctl"
        self.assertTrue(binary.is_file())
        module_snapshot = self.prefix / "libexec/swapz/dm-swapz.ko"
        self.assertEqual(module_snapshot.read_bytes(),
                         self.module_artifact.read_bytes())
        version = subprocess.run([binary, "version"], capture_output=True, text=True)
        self.assertIn(VERSION, version.stdout)
        self.assertEqual(subprocess.run([binary, "status"], capture_output=True).returncode, 0)
        installed_source = self.home / "usr/src" / ("swapz-" + VERSION)
        self.assertEqual((installed_source / "src/kernel/VERSION").read_text().strip(), VERSION)
        self.assertEqual(
            (installed_source / "src/kernel/swapz-build-info.h").read_bytes(),
            self.build_info.read_bytes())
        version_from_dkms = subprocess.run(
            ["bash", "-c", 'source "$1"; printf "%s" "$PACKAGE_VERSION"',
             "_", str(installed_source / "dkms.conf")],
            cwd=self.home, capture_output=True, text=True, check=True)
        self.assertEqual(version_from_dkms.stdout, VERSION)
        self.assertEqual(subprocess.run([binary, "start", "/dev/sda"],
                         capture_output=True).returncode, 2)
        primary_status = subprocess.run(
            [binary, "primary", "start"], capture_output=True, text=True)
        self.assertEqual(primary_status.returncode, 2)
        self.assertIn("remain disabled", primary_status.stderr)
        unit_dir = self.prefix / "lib/systemd/system"
        mapper_service = unit_dir / "swapz-primary-mapper.service"
        swap_unit = unit_dir / "dev-mapper-swapz\\x2dprimary.swap"
        self.assertTrue(mapper_service.is_file())
        self.assertTrue(swap_unit.is_file())
        service_text = mapper_service.read_text()
        swap_text = swap_unit.read_text()
        self.assertIn("RefuseManualStart=yes", service_text)
        self.assertIn("RefuseManualStop=yes", service_text)
        self.assertNotIn("dev-disk-by", service_text)
        self.assertNotIn("sda4", service_text)
        self.assertNotIn("7fb9401d-04", service_text)
        self.assertIn(
            "ConditionPathExists=/var/lib/swapz/physical-recovery/primary-state.json",
            service_text)
        self.assertIn("ExecStart=" + str(binary) + " primary start", service_text)
        self.assertIn("What=/dev/mapper/swapz-primary", swap_text)
        self.assertIn("Priority=-1", swap_text)
        self.assertNotIn("discard", swap_text.lower())
        self.assertFalse((self.prefix / "etc/systemd/system/swap.target.wants" /
                          swap_unit.name).exists())
        # Rootless safety: the format command rejects a regular file and
        # leaves its bytes untouched. No block-device formatting occurs here.
        regular = self.home / "not-a-block-device"
        regular.write_bytes(b"sentinel")
        before = regular.read_bytes()
        formatted = subprocess.run([binary, "format", regular],
                                   capture_output=True)
        self.assertEqual(formatted.returncode, 2)
        self.assertEqual(regular.read_bytes(), before)
        self.assertNotEqual(self.invoke("install").returncode, 0)
        r = self.invoke("uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(binary.exists())
        self.assertFalse(mapper_service.exists())
        self.assertFalse(swap_unit.exists())
        self.assertFalse(module_snapshot.exists())
        self.assertFalse((self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertEqual(self.log.read_text().splitlines(),
                         ["add", "build", "install", "status", "remove"])
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)

    def test_dkms_config_tracks_changed_canonical_version(self):
        # A future release updates VERSION only: DKMS must read that new
        # value without a matching hand-edit to dkms.conf or package code.
        other = self.home / "synthetic-release"
        (other / "src/kernel").mkdir(parents=True)
        (other / "dkms.conf").write_bytes((ROOT / "dkms.conf").read_bytes())
        (other / "src/kernel/VERSION").write_text("3.0.0-alpha.99\n")
        run = subprocess.run(
            ["bash", "-c", 'source "$1"; printf "%s" "$PACKAGE_VERSION"',
             "_", str(other / "dkms.conf")],
            cwd=self.home, capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout, "3.0.0-alpha.99")

    def test_tamper_and_dkms_failure_keep_owned_files(self):
        # SWAPZ_PACKAGE_TEST_ROOT is a hermetic fake-DKMS sandbox. A real
        # dm_swapz left loaded by an earlier privileged qualification must not
        # change this rootless package lifecycle.
        self.assertEqual(self.invoke("install").returncode, 0)
        binary = self.prefix / "sbin/swapzctl"
        original = binary.read_bytes()
        binary.write_bytes(b"tampered")
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)
        binary.write_bytes(original)
        module_snapshot = self.prefix / "libexec/swapz/dm-swapz.ko"
        original_module = module_snapshot.read_bytes()
        module_snapshot.write_bytes(b"tampered module")
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)
        module_snapshot.write_bytes(original_module)
        recovery = self.home / "var/lib/swapz/physical-recovery"
        recovery.mkdir(parents=True)
        primary_state = recovery / "primary-state.json"
        primary_state.write_text("preserve state\n")
        r = self.invoke("uninstall")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(primary_state.is_file())
        primary_state.unlink()
        primary_state.symlink_to("missing-primary-state")
        r = self.invoke("uninstall")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(primary_state.is_symlink())
        primary_state.unlink()
        primary_active = recovery / "partition-1234abcd-01.active"
        primary_active.write_text("active\n")
        r = self.invoke("uninstall")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(primary_active.is_file())
        primary_active.unlink()
        primary_active.symlink_to("missing-active-marker")
        r = self.invoke("uninstall")
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue(primary_active.is_symlink())
        primary_active.unlink()
        self.assertNotEqual(self.invoke("uninstall", {"SWAPZ_FAKE_FAIL_AT": "remove"}).returncode, 0)
        self.assertTrue(binary.exists())
        self.assertEqual(self.invoke("uninstall").returncode, 0)

    def test_failed_dkms_build_rolls_back(self):
        r = self.invoke("install", {"SWAPZ_FAKE_FAIL_AT": "build"})
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse((self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertIn("remove", self.log.read_text().splitlines())

    def test_bogus_prefix_rejected_before_disk_changes(self):
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)
        for prefix in ("/", "/tmp/../wrong", "/usr/local"):
            r = subprocess.run(["bash", str(SCRIPT), "install", prefix],
                               cwd=ROOT, env=self.env, capture_output=True)
            self.assertNotEqual(r.returncode, 0)
        self.assertNotEqual(
            self.invoke("install", {
                "SWAPZ_TEST_MODULE_ARTIFACT": str(self.home / "outside.ko")
            }).returncode, 0)
        self.assertNotEqual(self.invoke("invalid").returncode, 0)

if __name__ == "__main__":
    unittest.main()
