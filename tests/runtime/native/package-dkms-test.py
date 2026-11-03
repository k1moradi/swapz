#!/usr/bin/env python3
"""Hermetic rootless swapz package transaction and provenance tests."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "build/tests/package-sandbox"
VERSION = (ROOT / "src/kernel/VERSION").read_text().strip()
SCRIPT = ROOT / "packaging/package-dkms.sh"
SOURCE_SHA = "0123456789abcdef0123456789abcdef01234567"
STAGES = (
    "Build module and helpers",
    "Native and rootless contracts",
    "Kernel warnings W=1",
    "Kernel warnings W=2",
    "Owned RAM smoke + mixed/QD pilot",
)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PackageLifecycle(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("package test requires nonroot (root test mode forbidden)")
        BASE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.build = self.home / "build"
        self.bin = self.home / "bin"
        self.build.mkdir()
        self.bin.mkdir()
        self.kernel_release = "6.12.0-swapz-test"
        headers = self.home / "lib/modules" / self.kernel_release / "build"
        headers.mkdir(parents=True)
        (headers / "Makefile").write_text("all:\n\t@:\n")
        self.headers_makefile = headers / "Makefile"
        self.installed_module = (
            self.home / "lib/modules" / self.kernel_release /
            "updates/dkms/dm-swapz.ko")

        self.build_info = self.build / "source-build-info.h"
        self.build_info.write_text(
            f'#define SWAPZ_BUILD_SOURCE_SHA "{SOURCE_SHA}"\n'
            "#define SWAPZ_BUILD_SOURCE_CLEAN 1\n"
            '#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n')
        self.cli = self.build / "swapzctl"
        self.cli.write_text(
            "#!/bin/sh\n"
            "case \"$1:$2\" in\n"
            f"  version:) echo 'swapz {VERSION}';;\n"
            "  status:) exit 0;;\n"
            "  primary:start) echo 'BLOCKED: primary-swap provisioning, activation, teardown and recovery remain disabled pending qualification' >&2; exit 2;;\n"
            "  primary:systemd-units) printf '%s %s\\n' \"$SWAPZ_TEST_DEVICE_UNIT\" \"$SWAPZ_TEST_SWAP_UNIT\";;\n"
            "  format:*) exit 2;;\n"
            "  *) exit 2;;\n"
            "esac\n")
        self.cli.chmod(0o755)
        self.oracle = self.build / "device-roundtrip"
        self.oracle.write_text("#!/bin/sh\nexit 0\n")
        self.oracle.chmod(0o755)
        self.module = self.build / "dm-swapz.ko"
        self.module.write_bytes(b"synthetic-qualified-dm-swapz-module\n")
        self.report = self.home / "qualification.json"
        self.write_report()

        self.dkms_state = self.home / "dkms.state"
        self.dkms_log = self.home / "dkms.log"
        self.fail_marker = self.home / "fail.once"
        self.tamper_marker = self.home / "tamper.once"
        self.cert = self.home / "MOK.der"
        self.cert.write_text("certificate")
        self.write_fake_tools()

        self.prefix = self.home / "usr/local"
        self.env = dict(
            os.environ,
            PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            SWAPZ_PACKAGE_TEST_ROOT=str(self.home),
            SWAPZ_TEST_BUILD_INFO=str(self.build_info),
            SWAPZ_TEST_CLI_ARTIFACT=str(self.cli),
            SWAPZ_TEST_ORACLE_ARTIFACT=str(self.oracle),
            SWAPZ_TEST_MODULE_ARTIFACT=str(self.module),
            SWAPZ_TEST_QUALIFICATION_REPORT=str(self.report),
            SWAPZ_TEST_KERNEL_RELEASE=self.kernel_release,
            SWAPZ_DKMS_STATE=str(self.dkms_state),
            SWAPZ_DKMS_LOG=str(self.dkms_log),
            SWAPZ_DKMS_FAIL_MARKER=str(self.fail_marker),
            SWAPZ_DEPMOD_TAMPER_MARKER=str(self.tamper_marker),
            SWAPZ_TEST_INSTALLED_MODULE=str(self.installed_module),
            SWAPZ_FAKE_FAIL_AT="never",
            SWAPZ_FAKE_BUILD_SLEEP="0",
            SWAPZ_FAKE_TAMPER_INSTALLED="0",
            SWAPZ_FAKE_SECURE_BOOT="disabled",
            SWAPZ_FAKE_SIG_KEY="ABCD",
            SWAPZ_FAKE_VERMAGIC=self.kernel_release,
            SWAPZ_MOK_CERT=str(self.cert),
        )

    def write_report(self):
        self.report.write_text(json.dumps({
            "schema": "swapz-test-results-v1",
            "source_sha": SOURCE_SHA,
            "tested_commit_sha": SOURCE_SHA,
            "overall": "PASS",
            "qualification": "RAM_BACKED_NULL_BLK_ONLY",
            "stages": [{"name": name, "status": "PASS", "exit_code": 0}
                       for name in STAGES],
            "qualified_artifacts": {
                "status": "AVAILABLE",
                "formatter_sha256": sha256(self.cli),
                "module_sha256": sha256(self.module),
                "oracle_sha256": sha256(self.oracle),
            },
        }, sort_keys=True) + "\n")

    def tool(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def write_fake_tools(self):
        self.tool("dkms", r'''#!/usr/bin/env bash
set -eu
cmd=$1
printf '%s\n' "$cmd" >> "$SWAPZ_DKMS_LOG"
if [[ "$cmd" == "$SWAPZ_FAKE_FAIL_AT" && ! -e "$SWAPZ_DKMS_FAIL_MARKER" ]]; then
  : > "$SWAPZ_DKMS_FAIL_MARKER"
  exit 44
fi
case "$cmd" in
  status)
    if [[ -f "$SWAPZ_DKMS_STATE" ]]; then
      printf 'swapz, %s, x86_64: installed\n' "$SWAPZ_TEST_KERNEL_RELEASE"
    fi
    ;;
  add) printf 'added\n' > "$SWAPZ_DKMS_STATE" ;;
  build)
    [[ -f "$SWAPZ_DKMS_STATE" ]]
    if [[ "$SWAPZ_FAKE_BUILD_SLEEP" != 0 ]]; then sleep "$SWAPZ_FAKE_BUILD_SLEEP"; fi
    ;;
  install)
    [[ -f "$SWAPZ_DKMS_STATE" ]]
    mkdir -p "$(dirname "$SWAPZ_TEST_INSTALLED_MODULE")"
    printf 'dkms-rebuilt-not-qualified\n' > "$SWAPZ_TEST_INSTALLED_MODULE"
    ;;
  remove)
    rm -f "$SWAPZ_DKMS_STATE" "$SWAPZ_TEST_INSTALLED_MODULE"*
    ;;
  *) exit 2 ;;
esac
''')
        self.tool("depmod", r'''#!/usr/bin/env bash
set -eu
printf 'depmod\n' >> "$SWAPZ_DKMS_LOG"
if [[ "$SWAPZ_FAKE_TAMPER_INSTALLED" == 1 && ! -e "$SWAPZ_DEPMOD_TAMPER_MARKER" ]]; then
  : > "$SWAPZ_DEPMOD_TAMPER_MARKER"
  printf 'tampered-after-depmod\n' > "$SWAPZ_TEST_INSTALLED_MODULE"
fi
''')
        self.tool("modinfo", r'''#!/usr/bin/env bash
set -eu
if [[ "$1" == -F && "$2" == vermagic ]]; then
  printf '%s test SMP\n' "$SWAPZ_FAKE_VERMAGIC"
elif [[ "$1" == -F && "$2" == sig_key ]]; then
  printf '%s\n' "$SWAPZ_FAKE_SIG_KEY"
elif [[ "$1" == -n && "$2" == dm_swapz ]]; then
  [[ -f "$SWAPZ_TEST_INSTALLED_MODULE" ]] || exit 1
  printf '%s\n' "$SWAPZ_TEST_INSTALLED_MODULE"
else
  exit 1
fi
''')
        self.tool("mokutil", r'''#!/usr/bin/env bash
case "$SWAPZ_FAKE_SECURE_BOOT" in
  enabled) echo 'SecureBoot enabled';;
  disabled) echo 'SecureBoot disabled';;
  *) echo 'unknown'; exit 1;;
esac
''')
        self.tool("openssl", "#!/bin/sh\nprintf '%s\\n' 'serial=ABCD'\n")
        self.tool("kmodsign", "#!/bin/sh\nexit 77\n")
        self.tool("sudo", "#!/bin/sh\n[ \"$1\" = -n ] && shift\nexec \"$@\"\n")
        self.tool(
            "systemd-escape",
            "#!/bin/sh\nprintf '%s\\n' 'dev-mapper-swapz\\x2dprimary.swap'\n")

    def invoke(self, action, extra=None, timeout=15):
        env = dict(self.env)
        if extra:
            env.update(extra)
        return subprocess.run(
            ["bash", str(SCRIPT), action, str(self.prefix)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout)

    def assert_absent(self):
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse(
            (self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertFalse(self.installed_module.exists())

    def test_clean_repeat_uninstall_and_reinstall(self):
        first = self.invoke("install")
        self.assertEqual(first.returncode, 0, first.stderr)
        binary = self.prefix / "sbin/swapzctl"
        snapshot = self.prefix / "libexec/swapz/dm-swapz.ko"
        self.assertEqual(binary.read_bytes(), self.cli.read_bytes())
        self.assertEqual(snapshot.read_bytes(), self.module.read_bytes())
        self.assertEqual(self.installed_module.read_bytes(), self.module.read_bytes())
        self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.installed_module.stat().st_mode & 0o777, 0o644)
        source = self.home / "usr/src" / ("swapz-" + VERSION)
        self.assertEqual(
            (source / "src/kernel/swapz-build-info.h").read_bytes(),
            self.build_info.read_bytes())
        self.assertIn(
            "source_sha=" + SOURCE_SHA,
            (source / ".swapz-qualification").read_text())

        before = self.dkms_log.read_text().splitlines()
        repeated = self.invoke("install")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("already matches", repeated.stdout)
        self.assertEqual(
            self.dkms_log.read_text().splitlines(), before + ["status"])

        mapper = self.prefix / "lib/systemd/system/swapz-primary-mapper.service"
        verifier = self.prefix / "lib/systemd/system/swapz-primary-boot-verify.service"
        generator = self.prefix / "lib/systemd/system-generators/swapz-primary-generator"
        swap_unit = (
            self.prefix /
            "lib/systemd/system/dev-mapper-swapz\\x2dprimary.swap")
        self.assertIn("RefuseManualStart=yes", mapper.read_text())
        self.assertIn("observe", verifier.read_text())
        self.assertIn("primary systemd-units", generator.read_text())
        self.assertIn("What=/dev/mapper/swapz-primary", swap_unit.read_text())

        removed = self.invoke("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assert_absent()
        self.assertEqual(self.invoke("install").returncode, 0)

    def test_missing_headers_signing_and_vermagic_refuse(self):
        self.headers_makefile.unlink()
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kernel headers", result.stderr)
        self.assert_absent()
        self.headers_makefile.write_text("all:\n\t@:\n")

        self.cert.unlink()
        result = self.invoke(
            "install", {"SWAPZ_FAKE_SECURE_BOOT": "enabled"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signature verification", result.stderr)
        self.assert_absent()
        self.cert.write_text("certificate")

        result = self.invoke(
            "install", {"SWAPZ_FAKE_VERMAGIC": "other-kernel"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the running kernel", result.stderr)
        self.assert_absent()

    def test_unexpected_paths_and_symlinks_refuse(self):
        for prefix in ("/", "/tmp/../wrong", "/usr/local"):
            result = subprocess.run(
                ["bash", str(SCRIPT), "install", prefix],
                cwd=ROOT, env=self.env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
        outside = self.home.parent / "outside-module.ko"
        outside.write_bytes(b"outside")
        result = self.invoke(
            "install", {"SWAPZ_TEST_MODULE_ARTIFACT": str(outside)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside package sandbox", result.stderr)
        target = self.home / "foreign"
        target.mkdir()
        lib = self.prefix / "lib"
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.symlink_to(target, target_is_directory=True)
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlinked package destination", result.stderr)

    def test_partial_failure_and_digest_tamper_roll_back(self):
        result = self.invoke(
            "install", {"SWAPZ_FAKE_FAIL_AT": "build"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback", result.stderr)
        self.assert_absent()
        self.fail_marker.unlink(missing_ok=True)

        result = self.invoke(
            "install", {"SWAPZ_FAKE_TAMPER_INSTALLED": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed during depmod", result.stderr)
        self.assert_absent()

    def test_upgrade_active_refusal_and_failed_upgrade_restores(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        old_binary = (self.prefix / "sbin/swapzctl").read_bytes()
        old_module = self.installed_module.read_bytes()
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        for flag in ("SWAPZ_TEST_MODULE_ACTIVE", "SWAPZ_TEST_MAPPING_ACTIVE"):
            result = self.invoke("install", {flag: "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.installed_module.read_bytes(), old_module)

        self.fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "install", {"SWAPZ_FAKE_FAIL_AT": "build"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(), old_binary)
        self.assertEqual(self.installed_module.read_bytes(), old_module)

    def test_uninstall_refuses_active_mapping_or_module(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        for flag in ("SWAPZ_TEST_MAPPING_ACTIVE", "SWAPZ_TEST_MODULE_ACTIVE"):
            result = self.invoke("uninstall", {flag: "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((self.prefix / "sbin/swapzctl").exists())
            self.assertTrue(self.installed_module.exists())

    def test_installed_digest_mismatch_is_not_silently_repaired(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        self.installed_module.write_bytes(b"tampered-installed-module\n")
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertEqual(
            self.installed_module.read_bytes(),
            b"tampered-installed-module\n")
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)

    def test_interrupt_during_dkms_build_rolls_back(self):
        env = dict(self.env, SWAPZ_FAKE_BUILD_SLEEP="30")
        process = subprocess.Popen(
            ["bash", str(SCRIPT), "install", str(self.prefix)],
            cwd=ROOT, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if (self.dkms_log.exists() and
                    "build" in self.dkms_log.read_text().splitlines()):
                break
            time.sleep(0.05)
        else:
            process.kill()
            self.fail("mock DKMS build did not start")
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 143, stdout + "\n" + stderr)
        self.assertIn("interruption", stderr)
        self.assert_absent()

    def test_dkms_config_tracks_changed_canonical_version(self):
        other = self.home / "synthetic-release"
        (other / "src/kernel").mkdir(parents=True)
        (other / "dkms.conf").write_bytes((ROOT / "dkms.conf").read_bytes())
        (other / "src/kernel/VERSION").write_text("3.0.0-alpha.99\n")
        run = subprocess.run(
            ["bash", "-c",
             'source "$1"; printf "%s" "$PACKAGE_VERSION"',
             "_", str(other / "dkms.conf")],
            cwd=self.home, capture_output=True, text=True, check=True)
        self.assertEqual(run.stdout, "3.0.0-alpha.99")


if __name__ == "__main__":
    unittest.main()
