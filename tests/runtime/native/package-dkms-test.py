#!/usr/bin/env python3
"""Hermetic rootless swapz package transaction and provenance tests."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
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


def copy_safe_package_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    shutil.copyfile(source, destination)
    destination.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)


def copy_safe_package_source(source, destination):
    """Build a hermetic package input tree with Git's safe file modes."""
    destination.mkdir(parents=True, exist_ok=True, mode=0o755)
    destination.chmod(0o755)
    for path in source.iterdir():
        if path.is_file() and not path.is_symlink():
            copy_safe_package_file(path, destination / path.name)


class PackageLifecycle(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("package test requires nonroot (root test mode forbidden)")
        original_umask = os.umask(0o022)
        self.addCleanup(os.umask, original_umask)
        BASE.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        temp_root = Path(self.temp.name).resolve()
        self.repo_root = temp_root / "repository"
        self.repo_root.mkdir(mode=0o700)
        copy_safe_package_file(ROOT / "dkms.conf", self.repo_root / "dkms.conf")
        copy_safe_package_source(ROOT / "packaging", self.repo_root / "packaging")
        source_root = self.repo_root / "src"
        source_root.mkdir(mode=0o755)
        source_root.chmod(0o755)
        copy_safe_package_source(ROOT / "src/kernel", self.repo_root / "src/kernel")
        self.script = self.repo_root / "packaging/package-dkms.sh"
        self.home = (self.repo_root / "build/tests/package-sandbox" /
                     temp_root.name)
        self.home.mkdir(parents=True, mode=0o700)
        self.build = self.home / "build"
        self.bin = self.home / "bin"
        self.build.mkdir()
        self.bin.mkdir()
        self.kernel_release = "6.12.0-swapz-test"
        modules_root = self.home / "lib/modules"
        modules_root.mkdir(parents=True, mode=0o755)
        modules_root.chmod(0o755)
        kernel_tree = modules_root / self.kernel_release
        kernel_tree.mkdir(mode=0o755)
        kernel_tree.chmod(0o755)
        headers = kernel_tree / "build"
        headers.mkdir(mode=0o755)
        headers.chmod(0o755)
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
        self.build_info.chmod(0o600)
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
        self.module.chmod(0o600)
        self.report = self.home / "qualification.json"
        self.write_report()

        self.dkms_state = self.home / "dkms.state"
        self.dkms_log = self.home / "dkms.log"
        self.fail_marker = self.home / "fail.once"
        self.tamper_marker = self.home / "tamper.once"
        self.depmod_fail_marker = self.home / "depmod-fail.once"
        self.systemctl_fail_marker = self.home / "systemctl-fail.once"
        self.systemctl_log = self.home / "systemctl.log"
        self.remove_sleep_marker = self.home / "remove-sleep.once"
        self.module_lookup_saw_cli_marker = self.home / "module-lookup-saw-cli"
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
            SWAPZ_DEPMOD_FAIL_MARKER=str(self.depmod_fail_marker),
            SWAPZ_SYSTEMCTL_FAIL_MARKER=str(self.systemctl_fail_marker),
            SWAPZ_SYSTEMCTL_LOG=str(self.systemctl_log),
            SWAPZ_REMOVE_SLEEP_MARKER=str(self.remove_sleep_marker),
            SWAPZ_TEST_INSTALLED_MODULE=str(self.installed_module),
            SWAPZ_TEST_INSTALLED_CLI=str(self.home / "usr/local/sbin/swapzctl"),
            SWAPZ_MODULE_LOOKUP_SAW_CLI_MARKER=str(
                self.module_lookup_saw_cli_marker),
            SWAPZ_FAKE_MODULE_LOOKUP_FAIL_AFTER_BUILDS="0",
            SWAPZ_FAKE_DKMS_MODULE_SUFFIX="",
            SWAPZ_FAKE_STATUS_FAIL_AFTER_BUILDS="0",
            SWAPZ_TEST_FAIL_TRANSACTION_PHASE="never",
            SWAPZ_FAKE_FAIL_AT="never",
            SWAPZ_FAKE_BUILD_SLEEP="0",
            SWAPZ_FAKE_REMOVE_SLEEP="0",
            SWAPZ_FAKE_DEPMOD_FAIL_ONCE="0",
            SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE="0",
            SWAPZ_FAKE_TAMPER_INSTALLED="0",
            SWAPZ_FAKE_SECURE_BOOT="disabled",
            SWAPZ_FAKE_MOK_ENROLLED="1",
            SWAPZ_FAKE_SIGNATURE_VALID="1",
            SWAPZ_FAKE_SIG_KEY="ABCD",
            SWAPZ_FAKE_VERMAGIC=self.kernel_release,
            SWAPZ_MOK_CERT=str(self.cert),
        )

    def write_report(self):
        self.report.write_text(json.dumps({
            "schema": "swapz-test-results-v1",
            "kernel_release": self.kernel_release,
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
        # These are synthetic trusted package inputs. Keep their mode safe
        # even when the test runner inherits a group-writable umask.
        self.report.chmod(0o600)

    def write_synthetic_signed_module(self):
        signature = b"synthetic-cms-signature"
        signature_header = bytes((0, 0, 2, 0, 0, 0, 0, 0))
        signature_header += len(signature).to_bytes(4, "big")
        self.module.write_bytes(
            b"synthetic-qualified-dm-swapz-module\n" +
            signature + signature_header +
            b"~Module signature appended~\n")
        self.module.chmod(0o600)
        self.write_report()

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
if [[ "$cmd" == remove && "$SWAPZ_FAKE_REMOVE_SLEEP" != 0 &&
      ! -e "$SWAPZ_REMOVE_SLEEP_MARKER" ]]; then
  : > "$SWAPZ_REMOVE_SLEEP_MARKER"
  sleep "$SWAPZ_FAKE_REMOVE_SLEEP"
fi
case "$cmd" in
  status)
    status_threshold="${SWAPZ_FAKE_STATUS_FAIL_AFTER_BUILDS:-0}"
    if [[ "$status_threshold" != 0 ]]; then
      build_count="$(grep -c '^build$' "$SWAPZ_DKMS_LOG" 2>/dev/null || true)"
      (( build_count < status_threshold )) || exit 62
    fi
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
    module_path="$SWAPZ_TEST_INSTALLED_MODULE${SWAPZ_FAKE_DKMS_MODULE_SUFFIX:-}"
    mkdir -p "$(dirname "$module_path")"
    printf 'dkms-rebuilt-not-qualified\n' > "$module_path"
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
if [[ "$SWAPZ_FAKE_DEPMOD_FAIL_ONCE" == 1 && ! -e "$SWAPZ_DEPMOD_FAIL_MARKER" ]]; then
  : > "$SWAPZ_DEPMOD_FAIL_MARKER"
  exit 45
fi
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
  threshold="${SWAPZ_FAKE_MODULE_LOOKUP_FAIL_AFTER_BUILDS:-0}"
  if [[ "$threshold" != 0 ]]; then
    build_count="$(grep -c '^build$' "$SWAPZ_DKMS_LOG" 2>/dev/null || true)"
    if (( build_count >= threshold )); then
      if [[ -e "$SWAPZ_TEST_INSTALLED_CLI" ]]; then
        : > "$SWAPZ_MODULE_LOOKUP_SAW_CLI_MARKER"
      fi
      exit 61
    fi
  fi
  printf '%s\n' "${SWAPZ_FAKE_MODULE_LOOKUP:-$SWAPZ_TEST_INSTALLED_MODULE}"
else
  exit 1
fi
''')
        self.tool("mokutil", r'''#!/usr/bin/env bash
set -eu
case "${1:-}" in
  --sb-state)
    case "$SWAPZ_FAKE_SECURE_BOOT" in
      enabled) echo 'SecureBoot enabled';;
      disabled) echo 'SecureBoot disabled';;
      *) echo 'unknown'; exit 1;;
    esac
    ;;
  --test-key)
    [[ "$SWAPZ_FAKE_MOK_ENROLLED" == 1 ]]
    ;;
  *) exit 2 ;;
esac
''')
        self.tool("openssl", r'''#!/usr/bin/env bash
set -eu
case "${1:-}" in
  x509)
    output=""
    while (( $# > 0 )); do
      if [[ "$1" == -out ]]; then
        output="$2"
        shift 2
      else
        shift
      fi
    done
    if [[ -n "$output" ]]; then
      printf '%s\n' '-----BEGIN CERTIFICATE-----' 'synthetic' \
        '-----END CERTIFICATE-----' > "$output"
    else
      printf '%s\n' '-----BEGIN CERTIFICATE-----' 'synthetic' \
        '-----END CERTIFICATE-----'
    fi
    ;;
  cms)
    [[ "${SWAPZ_FAKE_SIGNATURE_VALID:-0}" == 1 ]] || exit 47
    ;;
  *) exit 2 ;;
esac
''')
        self.tool("kmodsign", "#!/bin/sh\nexit 77\n")
        self.tool("sudo", "#!/bin/sh\n[ \"$1\" = -n ] && shift\nexec \"$@\"\n")
        self.tool("systemctl", r'''#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$SWAPZ_SYSTEMCTL_LOG"
case "${1:-}" in
  daemon-reload)
    if [[ "$SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE" == 1 &&
          ! -e "$SWAPZ_SYSTEMCTL_FAIL_MARKER" ]]; then
      : > "$SWAPZ_SYSTEMCTL_FAIL_MARKER"
      exit 46
    fi
    if [[ "${SWAPZ_TEST_ASSERT_CLI_ABSENT_AT_RELOAD:-0}" == 1 &&
          -e "$SWAPZ_TEST_INSTALLED_CLI" ]]; then
      exit 57
    fi
    ;;
  is-active)
    [[ "${SWAPZ_FAKE_SYSTEMCTL_QUERY_FAILURE:-0}" != 1 ]] || exit 48
    if [[ "${SWAPZ_FAKE_ACTIVE_SYSTEMD_UNIT:-}" == "${2:-}" ]]; then
      printf 'active\n'
      exit 0
    fi
    printf 'inactive\n'
    exit 3
    ;;
  is-enabled)
    [[ "${SWAPZ_FAKE_SYSTEMCTL_QUERY_FAILURE:-0}" != 1 ]] || exit 49
    if [[ "${SWAPZ_FAKE_ENABLED_SYSTEMD_UNIT:-}" == "${2:-}" ]]; then
      printf 'enabled\n'
      exit 0
    fi
    case "${2:-}" in
      *.swap) printf 'static\n'; exit 0 ;;
      *) printf 'disabled\n'; exit 1 ;;
    esac
    ;;
  *) exit 2 ;;
esac
''')
        self.tool(
            "systemd-escape",
            "#!/bin/sh\nprintf '%s\\n' 'dev-mapper-swapz\\x2dprimary.swap'\n")

    def invoke(self, action, extra=None, timeout=15):
        env = dict(self.env)
        if extra:
            env.update(extra)
        return subprocess.run(
            ["bash", str(self.script), action, str(self.prefix)],
            cwd=self.repo_root, env=env, capture_output=True, text=True,
            timeout=timeout)

    def assert_absent(self):
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse((self.prefix / "sbin/swapz-primary-runtime-health").exists())
        self.assertFalse((self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service").exists())
        self.assertFalse(
            (self.home / "usr/src" / ("swapz-" + VERSION)).exists())
        self.assertFalse(self.installed_module.exists())

    def assert_installed_exact(self):
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(),
            self.cli.read_bytes())
        self.assertEqual(
            (self.prefix / "sbin/swapz-primary-runtime-health").read_bytes(),
            (self.repo_root / "packaging/swapz-primary-runtime-health").read_bytes())
        self.assertEqual(
            (self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service").read_text(),
            (self.repo_root / "packaging/swapz-primary-runtime-health.service").read_text().replace(
                "@SWAPZ_SBINDIR@", str(self.prefix / "sbin")))
        self.assertEqual(
            (self.prefix / "libexec/swapz/device-roundtrip").read_bytes(),
            self.oracle.read_bytes())
        self.assertEqual(
            (self.prefix / "libexec/swapz/dm-swapz.ko").read_bytes(),
            self.module.read_bytes())
        self.assertEqual(
            self.installed_module.read_bytes(), self.module.read_bytes())

    def uninstall_transactions(self):
        transaction_parent = self.home / "transactions"
        if not transaction_parent.exists():
            return []
        return sorted(transaction_parent.glob("swapz-uninstall.*"))

    def test_package_lock_refuses_parallel_mutation(self):
        package_lock = self.home / "package.lock"
        package_lock.touch(mode=0o600)
        package_lock.chmod(0o600)
        with package_lock.open("r+", encoding="ascii") as held:
            fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.invoke("install")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "another swapz package operation is active", result.stderr)
            self.assert_absent()

    def test_package_lock_metadata_is_fail_closed(self):
        package_lock = self.home / "package.lock"

        package_lock.touch(mode=0o600)
        package_lock.chmod(0o666)
        unsafe_mode = self.invoke("install")
        self.assertNotEqual(unsafe_mode.returncode, 0)
        self.assertIn("unsafe package lock file", unsafe_mode.stderr)
        self.assertEqual(package_lock.stat().st_mode & 0o777, 0o666)
        package_lock.unlink()

        package_lock.touch(mode=0o600)
        package_lock.chmod(0o600)
        hardlink = self.home / "package.lock.hardlink"
        os.link(package_lock, hardlink)
        hardlinked = self.invoke("install")
        self.assertNotEqual(hardlinked.returncode, 0)
        self.assertIn("unsafe package lock file", hardlinked.stderr)
        hardlink.unlink()
        package_lock.unlink()

        self.home.chmod(0o777)
        try:
            unsafe_directory = self.invoke("install")
            self.assertNotEqual(unsafe_directory.returncode, 0)
            self.assertIn("unsafe package lock directory",
                          unsafe_directory.stderr)
        finally:
            self.home.chmod(0o700)
        self.assert_absent()

    def test_package_lock_inode_swap_during_flock_is_refused(self):
        # The descriptor still refers to the original lock after the pathname
        # is replaced; no package mutation may use that obsolete lock inode.
        flock_binary = shutil.which("flock")
        self.assertIsNotNone(flock_binary)
        package_lock = self.home / "package.lock"
        package_lock.touch(mode=0o600)
        package_lock.chmod(0o600)
        self.tool("flock", f"""#!/usr/bin/env bash
set -eu
mv -- "$SWAPZ_PACKAGE_TEST_ROOT/package.lock" "$SWAPZ_PACKAGE_TEST_ROOT/old.package.lock"
(umask 077; : > "$SWAPZ_PACKAGE_TEST_ROOT/package.lock")
exec "{flock_binary}" "$@"
""")
        refused = self.invoke("install")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("package lock path changed while locked", refused.stderr)
        self.assert_absent()

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
        self.assert_installed_exact()
        health_unit = self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service"
        self.assertIn("Restart=on-failure", health_unit.read_text())
        self.assertIn("What=/dev/mapper/swapz-primary", swap_unit.read_text())

        removed = self.invoke("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assert_absent()
        self.assertEqual(self.invoke("install").returncode, 0)
        removed_again = self.invoke("uninstall")
        self.assertEqual(removed_again.returncode, 0, removed_again.stderr)
        self.assert_absent()
        self.assertEqual(self.invoke("install").returncode, 0)

    def test_qualification_kernel_and_dkms_state_must_be_exact(self):
        report = json.loads(self.report.read_text())
        report["kernel_release"] = self.kernel_release + "-foreign"
        self.report.write_text(json.dumps(report, sort_keys=True) + "\n")
        self.report.chmod(0o600)
        wrong_kernel = self.invoke("install")
        self.assertNotEqual(wrong_kernel.returncode, 0)
        self.assertIn("qualification report is invalid", wrong_kernel.stderr)
        self.assert_absent()

        self.write_report()
        status_failure = self.invoke(
            "install", {"SWAPZ_FAKE_FAIL_AT": "status"})
        self.assertNotEqual(status_failure.returncode, 0)
        self.assertIn("cannot inspect current-kernel DKMS state",
                      status_failure.stderr)
        self.assert_absent()

        self.fail_marker.unlink(missing_ok=True)
        self.assertEqual(self.invoke("install").returncode, 0)
        self.dkms_state.unlink()
        missing_state = self.invoke("install")
        self.assertNotEqual(missing_state.returncode, 0)
        self.assertIn("does not have an installed current-kernel DKMS state",
                      missing_state.stderr)
        self.assert_installed_exact()

        missing_state_uninstall = self.invoke("uninstall")
        self.assertNotEqual(missing_state_uninstall.returncode, 0)
        self.assertIn("does not have an installed current-kernel DKMS state",
                      missing_state_uninstall.stderr)
        self.assert_installed_exact()

    def test_uninstall_dkms_status_query_failure_preserves_package(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        failed = self.invoke("uninstall", {"SWAPZ_FAKE_FAIL_AT": "status"})
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("cannot inspect current-kernel DKMS state before package removal",
                      failed.stderr)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

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
            "install", {
                "SWAPZ_FAKE_SECURE_BOOT": "enabled",
                "SWAPZ_FAKE_MOK_ENROLLED": "0",
            })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not enrolled", result.stderr)
        self.assert_absent()

        # Matching signer metadata is deliberately insufficient. The synthetic
        # appended signature must also validate against the configured cert.
        self.write_synthetic_signed_module()
        result = self.invoke(
            "install", {
                "SWAPZ_FAKE_SECURE_BOOT": "enabled",
                "SWAPZ_FAKE_SIGNATURE_VALID": "0",
            })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not cryptographically valid", result.stderr)
        self.assert_absent()

        result = self.invoke(
            "install", {"SWAPZ_FAKE_SECURE_BOOT": "enabled"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cryptographic signature verified", result.stdout)
        self.assertEqual(self.invoke("uninstall").returncode, 0)

        result = self.invoke(
            "install", {"SWAPZ_FAKE_VERMAGIC": "other-kernel"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the running kernel", result.stderr)
        self.assert_absent()

    def test_secure_boot_verifies_real_detached_cms_payload(self):
        openssl = shutil.which("openssl")
        self.assertIsNotNone(openssl)
        crypto_bin = self.home / "crypto-bin"
        crypto_bin.mkdir()
        mokutil = crypto_bin / "mokutil"
        mokutil.write_text(
            "#!/bin/sh\n"
            "case \"$1\" in\n"
            "  --sb-state) echo 'SecureBoot enabled';;\n"
            "  --test-key) exit 0;;\n"
            "  *) exit 2;;\n"
            "esac\n")
        mokutil.chmod(0o755)

        private_key = self.home / "crypto-test.key"
        certificate_pem = self.home / "crypto-test.pem"
        certificate_der = self.home / "crypto-test.der"
        payload = self.home / "crypto-module.payload"
        signature = self.home / "crypto-module.p7s"
        signed_module = self.home / "crypto-dm-swapz.ko"
        payload.write_bytes(b"exact swapz module payload for CMS verification\n")

        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(private_key), "-out", str(certificate_pem),
             "-subj", "/CN=swapz-package-test", "-days", "1"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            [openssl, "x509", "-in", str(certificate_pem), "-outform", "DER",
             "-out", str(certificate_der)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            [openssl, "cms", "-sign", "-binary", "-in", str(payload),
             "-signer", str(certificate_pem), "-inkey", str(private_key),
             "-outform", "DER", "-out", str(signature), "-nocerts", "-noattr",
             "-md", "sha512"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        signature_bytes = signature.read_bytes()
        signature_header = bytes((0, 0, 2, 0, 0, 0, 0, 0))
        signature_header += len(signature_bytes).to_bytes(4, "big")
        signed_module.write_bytes(
            payload.read_bytes() + signature_bytes + signature_header +
            b"~Module signature appended~\n")

        verify_env = dict(
            os.environ,
            PATH=str(crypto_bin) + os.pathsep + os.path.dirname(openssl) +
                 os.pathsep + "/usr/bin:/bin",
            SWAPZ_SIGN_TEST_ROOT=str(self.home),
            SWAPZ_MOK_CERT=str(certificate_der),
        )
        verified = subprocess.run(
            ["bash", str(ROOT / "packaging/sign-module.sh"),
             "--verify", str(signed_module)],
            cwd=ROOT, env=verify_env, capture_output=True, text=True)
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertIn("cryptographic signature verified", verified.stdout)

        tampered = bytearray(signed_module.read_bytes())
        tampered[0] ^= 1
        signed_module.write_bytes(tampered)
        rejected = subprocess.run(
            ["bash", str(ROOT / "packaging/sign-module.sh"),
             "--verify", str(signed_module)],
            cwd=ROOT, env=verify_env, capture_output=True, text=True)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("not cryptographically valid", rejected.stderr)

        # An embedded foreign signer certificate must not be treated as the
        # configured enrolled MOK merely because OpenSSL can validate it.
        foreign_key = self.home / "foreign-test.key"
        foreign_certificate = self.home / "foreign-test.pem"
        foreign_signature = self.home / "foreign-module.p7s"
        subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(foreign_key), "-out", str(foreign_certificate),
             "-subj", "/CN=foreign-unenrolled-test", "-days", "1"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            [openssl, "cms", "-sign", "-binary", "-in", str(payload),
             "-signer", str(foreign_certificate), "-inkey", str(foreign_key),
             "-outform", "DER", "-out", str(foreign_signature),
             "-noattr", "-md", "sha512"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        foreign_bytes = foreign_signature.read_bytes()
        foreign_header = bytes((0, 0, 2, 0, 0, 0, 0, 0))
        foreign_header += len(foreign_bytes).to_bytes(4, "big")
        signed_module.write_bytes(
            payload.read_bytes() + foreign_bytes + foreign_header +
            b"~Module signature appended~\n")
        foreign_result = subprocess.run(
            ["bash", str(ROOT / "packaging/sign-module.sh"),
             "--verify", str(signed_module)],
            cwd=ROOT, env=verify_env, capture_output=True, text=True)
        self.assertEqual(foreign_result.returncode, 2, foreign_result.stdout)
        self.assertIn("not cryptographically valid", foreign_result.stderr)

    def test_kernel_upgrade_requires_new_qualified_module(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        old_module = self.installed_module.read_bytes()
        next_release = self.kernel_release + "-next"
        next_headers = (
            self.home / "lib/modules" / next_release / "build")
        next_headers.mkdir(parents=True)
        (next_headers / "Makefile").write_text("all:\n\t@:\n")
        report = json.loads(self.report.read_text())
        report["kernel_release"] = next_release
        self.report.write_text(json.dumps(report, sort_keys=True) + "\n")
        self.report.chmod(0o600)
        result = self.invoke(
            "install", {"SWAPZ_TEST_KERNEL_RELEASE": next_release})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not match the running kernel", result.stderr)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        self.assertFalse(
            (self.home / "lib/modules" / next_release /
             "updates/dkms/dm-swapz.ko").exists())

    def test_production_transaction_storage_is_private(self):
        content = SCRIPT.read_text()
        self.assertIn(
            'transaction_parent="/var/lib/swapz-package-transactions"',
            content)
        self.assertNotIn('transaction_parent="/var/tmp"', content)

    def test_runtime_health_dependencies_are_admitted_before_install(self):
        content = SCRIPT.read_text()
        required = (
            "timeout", "lsblk", "dmsetup", "journalctl", "blkid",
            "tr", "cut", "dirname", "sleep", "cat",
        )
        required_line = next(
            line for line in content.splitlines()
            if line.startswith("for required_command in "))
        for command in required:
            with self.subTest(command=command):
                self.assertIn(f" {command}", required_line)

    def test_unexpected_paths_and_symlinks_refuse(self):
        for prefix in ("/", "/tmp/../wrong", "/usr/local"):
            result = subprocess.run(
                ["bash", str(self.script), "install", prefix],
                cwd=self.repo_root, env=self.env, capture_output=True,
                text=True)
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

    def test_foreign_module_writable_destination_and_tool_symlink_refuse(self):
        self.installed_module.parent.mkdir(parents=True, exist_ok=True)
        self.installed_module.write_bytes(b"foreign-module\n")
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertEqual(
            self.installed_module.read_bytes(), b"foreign-module\n")
        self.installed_module.unlink()

        self.prefix.mkdir(parents=True, exist_ok=True)
        self.prefix.chmod(0o777)
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("writable package destination directory", result.stderr)
        self.prefix.chmod(0o755)

        dkms = self.bin / "dkms"
        real_dkms = self.bin / "dkms.real"
        dkms.rename(real_dkms)
        dkms.symlink_to(real_dkms.name)
        try:
            result = self.invoke("install")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no trusted DKMS executable", result.stderr)
        finally:
            dkms.unlink()
            real_dkms.rename(dkms)

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

        self.tamper_marker.unlink(missing_ok=True)
        self.depmod_fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "install", {"SWAPZ_FAKE_DEPMOD_FAIL_ONCE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback", result.stderr)
        self.assert_absent()

        self.systemctl_fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "install", {"SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rollback", result.stderr)
        self.assert_absent()
        self.assertEqual(self.uninstall_transactions(), [])

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

        # A stale file matching the accidental historical literal temp name
        # must not prevent PID-scoped atomic CLI restoration.
        stale_cli_restore = self.prefix / "sbin/.swapzctl.restore.$"
        stale_cli_restore.write_text("foreign stale rollback temp\n")
        self.systemctl_fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "install", {"SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(), old_binary)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        self.assertEqual(
            stale_cli_restore.read_text(), "foreign stale rollback temp\n")
        self.assertIn("daemon-reload", self.systemctl_log.read_text())

        # Deliberate failure after the old CLI is restored must revoke it
        # rather than retain an activatable incomplete upgrade.
        self.systemctl_fail_marker.unlink(missing_ok=True)
        failed_verify = self.invoke("install", {
            "SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1",
            "SWAPZ_TEST_UPGRADE_ROLLBACK_VERIFY_FAILURE": "1",
        })
        self.assertNotEqual(failed_verify.returncode, 0)
        self.assertIn("previous package restoration failed", failed_verify.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse(
            (self.prefix / "lib/systemd/system/swapz-primary-mapper.service").exists())
        transactions = list((self.home / "transactions").glob("swapz-package.*"))
        self.assertEqual(len(transactions), 1)
        blocked = self.invoke("install")
        self.assertIn("incomplete package transaction retained", blocked.stderr)

    def test_upgrade_all_mutation_checkpoints_restore_exact_old_package(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        installed_cli = self.prefix / "sbin/swapzctl"
        old_cli = installed_cli.read_bytes()
        old_module = self.installed_module.read_bytes()
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()

        # Fail after every backend and activation publication boundary.
        phases = (
            "activation-files-removed", "dkms-removed", "source-removed",
            "source-created", "dkms-added", "dkms-built", "dkms-installed",
            "module-promoted", "depmod-complete", "package-files-published",
            "systemd-reload-complete", "cli-published",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                result = self.invoke(
                    "install", {"SWAPZ_TEST_INSTALL_FAIL_AFTER": phase})
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("attempting transaction rollback", result.stderr)
                self.assertEqual(installed_cli.read_bytes(), old_cli)
                self.assertEqual(self.installed_module.read_bytes(), old_module)
                self.assertFalse(
                    list((self.home / "transactions").glob("swapz-package.*")))

    def test_compressed_dkms_image_is_normalized_during_rollbacks(self):
        compressed_module = Path(str(self.installed_module) + ".zst")
        compressed_env = {"SWAPZ_FAKE_DKMS_MODULE_SUFFIX": ".zst"}

        first = self.invoke("install", compressed_env)
        self.assertEqual(first.returncode, 0, first.stderr)
        old_cli = (self.prefix / "sbin/swapzctl").read_bytes()
        old_module = self.installed_module.read_bytes()
        self.assertFalse(compressed_module.exists())

        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        failed_upgrade = self.invoke("install", {
            **compressed_env,
            "SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1",
        })
        self.assertNotEqual(failed_upgrade.returncode, 0)
        self.assertIn("attempting transaction rollback", failed_upgrade.stderr)
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(), old_cli)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        self.assertFalse(compressed_module.exists())
        self.assertFalse(
            list((self.home / "transactions").glob("swapz-package.*")))

        failed_uninstall = self.invoke("uninstall", {
            **compressed_env,
            "SWAPZ_TEST_UNINSTALL_FAIL_AFTER": "dkms-removed",
        })
        self.assertNotEqual(failed_uninstall.returncode, 0)
        self.assertIn("attempting transaction rollback", failed_uninstall.stderr)
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(), old_cli)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        self.assertFalse(compressed_module.exists())
        self.assertEqual(self.uninstall_transactions(), [])

    def test_install_cli_only_published_after_systemd_reload(self):
        gated = {"SWAPZ_TEST_ASSERT_CLI_ABSENT_AT_RELOAD": "1"}
        first = self.invoke("install", gated)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assert_installed_exact()
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        upgraded = self.invoke("install", gated)
        self.assertEqual(upgraded.returncode, 0, upgraded.stderr)
        self.assert_installed_exact()

    def interrupt_upgrade_with_snapshot(
            self, corrupt_backup, corrupt_metadata=False,
            corrupt_journal_metadata=False, collide_journal_temp=False):
        self.assertEqual(self.invoke("install").returncode, 0)
        old_module = self.installed_module.read_bytes()
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        environment = dict(self.env, SWAPZ_FAKE_REMOVE_SLEEP="30")
        process = subprocess.Popen(
            ["bash", str(self.script), "install", str(self.prefix)],
            cwd=self.repo_root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if self.remove_sleep_marker.exists():
                    break
                time.sleep(0.05)
            else:
                self.fail("upgrade DKMS removal did not start")

            transactions = list(
                (self.home / "transactions").glob("swapz-package.*"))
            self.assertEqual(len(transactions), 1)
            transaction = transactions[0]
            state_path = transaction / "state.json"
            self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
            state = json.loads(state_path.read_text())
            self.assertEqual(state["schema"], "swapz-package-install-v1")
            self.assertEqual(state["phase"], "removing-dkms")
            self.assertTrue(state["backup_files"])
            for entry in state["backup_files"]:
                self.assertEqual(
                    sha256(transaction / "backup" / entry["path"]),
                    entry["sha256"])
            # The old CLI is revoked before DKMS begins replacing its module.
            self.assertFalse((self.prefix / "sbin/swapzctl").exists())
            if corrupt_backup:
                (transaction / "backup/source/dkms.conf").write_bytes(
                    b"corrupted-rollback-snapshot\n")
            if corrupt_metadata:
                # Byte-exact content is insufficient if snapshot permissions
                # have changed since the prepared journal checkpoint.
                (transaction / "backup/source/dkms.conf").chmod(0o666)
            if corrupt_journal_metadata:
                state_path.chmod(0o666)
            journal_temp_sentinel = None
            if collide_journal_temp:
                journal_temp_sentinel = self.home / "journal-temp-sentinel"
                journal_temp_sentinel.write_bytes(b"must-not-change\n")
                (transaction / "state.json.tmp").symlink_to(
                    journal_temp_sentinel)

            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 143, stdout + "\n" + stderr)
            if collide_journal_temp:
                self.assertIn("cannot journal install rollback", stderr)
                self.assertEqual(
                    journal_temp_sentinel.read_bytes(), b"must-not-change\n")
                self.assertFalse((self.prefix / "sbin/swapzctl").exists())
                self.assertEqual(
                    len(list((self.home / "transactions").glob(
                        "swapz-package.*"))), 1)
                refused = self.invoke("install")
                self.assertIn("incomplete package transaction retained",
                              refused.stderr)
            elif corrupt_backup or corrupt_metadata or corrupt_journal_metadata:
                self.assertIn("rollback snapshot invalid", stderr)
                self.assertFalse((self.prefix / "sbin/swapzctl").exists())
                self.assertEqual(
                    len(list((self.home / "transactions").glob(
                        "swapz-package.*"))), 1)
                refused = self.invoke("install")
                self.assertIn("incomplete package transaction retained",
                              refused.stderr)
            else:
                self.assertEqual(
                    self.installed_module.read_bytes(), old_module)
                self.assertTrue((self.prefix / "sbin/swapzctl").exists())
                self.assertFalse(
                    list((self.home / "transactions").glob("swapz-package.*")))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=8)

    def test_interrupted_upgrade_restores_journaled_snapshot(self):
        self.interrupt_upgrade_with_snapshot(corrupt_backup=False)

    def test_corrupt_upgrade_snapshot_quarantines_activation(self):
        self.interrupt_upgrade_with_snapshot(corrupt_backup=True)

    def test_upgrade_snapshot_metadata_tamper_quarantines_activation(self):
        self.interrupt_upgrade_with_snapshot(
            corrupt_backup=False, corrupt_metadata=True)

    def test_upgrade_journal_metadata_tamper_quarantines_activation(self):
        self.interrupt_upgrade_with_snapshot(
            corrupt_backup=False, corrupt_journal_metadata=True)

    def test_transaction_journal_mode_is_durable_before_publish(self):
        source = self.script.read_text()
        start = source.index("temporary_flags = (os.O_WRONLY | os.O_CREAT")
        end = source.index("os.replace(temporary, final)", start)
        journal_write = source[start:end]
        self.assertIn("os.O_EXCL", journal_write)
        self.assertIn("os.O_NOFOLLOW", journal_write)
        mode_set = journal_write.index("os.fchmod(stream.fileno(), 0o600)")
        durable_write = journal_write.index("os.fsync(stream.fileno())")
        self.assertLess(mode_set, durable_write)
        self.assertNotIn('temporary.open("w"', journal_write)

    def test_stale_journal_temp_symlink_is_never_followed(self):
        self.interrupt_upgrade_with_snapshot(
            corrupt_backup=False, collide_journal_temp=True)

    def test_upgrade_rollback_dkms_status_uncertainty_revokes_activation(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        failed = self.invoke("install", {
            "SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1",
            "SWAPZ_FAKE_STATUS_FAIL_AFTER_BUILDS": "3",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("previous package restoration failed", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        transactions = list(
            (self.home / "transactions").glob("swapz-package.*"))
        self.assertEqual(len(transactions), 1)
        state = json.loads((transactions[0] / "state.json").read_text())
        self.assertEqual(state["phase"], "rollback-incomplete")

    def test_uninstall_rollback_dkms_status_uncertainty_revokes_activation(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        failed = self.invoke("uninstall", {
            "SWAPZ_TEST_UNINSTALL_FAIL_AFTER": "dkms-removed",
            "SWAPZ_FAKE_STATUS_FAIL_AFTER_BUILDS": "2",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("rollback incomplete", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        transactions = self.uninstall_transactions()
        self.assertEqual(len(transactions), 1)
        state = json.loads((transactions[0] / "state.json").read_text())
        self.assertEqual(state["phase"], "rollback-incomplete")

    def test_upgrade_rollback_resolves_module_before_restoring_cli(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        self.systemctl_fail_marker.unlink(missing_ok=True)

        failed = self.invoke("install", {
            "SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1",
            "SWAPZ_FAKE_MODULE_LOOKUP_FAIL_AFTER_BUILDS": "3",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("previous package restoration failed", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse(self.module_lookup_saw_cli_marker.exists())
        transactions = list(
            (self.home / "transactions").glob("swapz-package.*"))
        self.assertEqual(len(transactions), 1)

    def test_uninstall_rollback_resolves_module_before_restoring_cli(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        failed = self.invoke("uninstall", {
            "SWAPZ_TEST_UNINSTALL_FAIL_AFTER": "dkms-removed",
            "SWAPZ_FAKE_MODULE_LOOKUP_FAIL_AFTER_BUILDS": "2",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("rollback incomplete", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse(self.module_lookup_saw_cli_marker.exists())
        transactions = self.uninstall_transactions()
        self.assertEqual(len(transactions), 1)

    def test_upgrade_refuses_primary_recovery_authority(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        old_binary = (self.prefix / "sbin/swapzctl").read_bytes()
        old_module = self.installed_module.read_bytes()

        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        recovery = self.home / "var/lib/swapz/physical-recovery"
        recovery.mkdir(parents=True)

        state = recovery / "primary-state.json"
        state.write_text('{"schema":"synthetic-recovery"}\n')
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("primary recovery state exists", result.stderr)
        self.assertEqual((self.prefix / "sbin/swapzctl").read_bytes(), old_binary)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        state.unlink()

        marker = recovery / "partition-f13428f6-01.active"
        marker.write_text("synthetic ownership marker\n")
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("primary partition ownership marker exists", result.stderr)
        self.assertEqual((self.prefix / "sbin/swapzctl").read_bytes(), old_binary)
        self.assertEqual(self.installed_module.read_bytes(), old_module)
        marker.unlink()

        # An exact repeat install is a byte-for-byte no-op and may return before
        # the mutation guard because it cannot invalidate recovery ownership.
        self.module.write_bytes(old_module)
        self.write_report()
        state.write_text('{"schema":"synthetic-recovery"}\n')
        repeated = self.invoke("install")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("already matches", repeated.stdout)

    def test_foreign_monitor_payload_refuses_admission(self):
        health = self.prefix / "sbin/swapz-primary-runtime-health"
        health.parent.mkdir(parents=True, exist_ok=True)
        health.write_bytes(b"foreign-runtime-health\n")
        health.chmod(0o755)
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertEqual(health.read_bytes(), b"foreign-runtime-health\n")
        self.assertFalse(self.installed_module.exists())

    def test_foreign_module_resolution_refuses_uninstall(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        foreign = self.home / "foreign-module-resolution.ko"
        foreign.write_bytes(b"foreign module\n")
        failed = self.invoke(
            "uninstall", {"SWAPZ_FAKE_MODULE_LOOKUP": str(foreign)})
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("foreign, absent or modified", failed.stderr)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

    def test_qualified_digest_cannot_be_rebased_by_binary_manifest(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        source = self.home / "usr/src" / ("swapz-" + VERSION)
        binary = self.prefix / "sbin/swapzctl"
        binary.write_bytes(b"tampered-userspace-with-rebased-manifest\n")
        binary.chmod(0o755)

        manifest = source / ".swapz-binaries.sha256"
        rewritten = []
        replaced = False
        for line in manifest.read_text().splitlines():
            digest, path = line.split(None, 1)
            if path == str(binary):
                digest = sha256(binary)
                replaced = True
            rewritten.append(f"{digest}  {path}\n")
        self.assertTrue(replaced)
        manifest.write_text("".join(rewritten))
        manifest.chmod(0o644)

        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertEqual(
            binary.read_bytes(),
            b"tampered-userspace-with-rebased-manifest\n")

    def test_metadata_tamper_cannot_enter_legacy_upgrade_path(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        source = self.home / "usr/src" / ("swapz-" + VERSION)
        for path, original_mode in (
            (self.prefix / "sbin/swapzctl", 0o755),
            (self.prefix / "sbin/swapz-primary-runtime-health", 0o755),
            (self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service", 0o644),
            (self.installed_module, 0o644),
            (source / ".swapz-qualification", 0o644),
        ):
            with self.subTest(path=path.name):
                path.chmod(0o666)
                try:
                    log_before = self.dkms_log.read_text()
                    result = self.invoke("install")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("partial, foreign, or modified", result.stderr)
                    self.assertEqual(self.dkms_log.read_text(), log_before)
                    self.assertEqual(path.stat().st_mode & 0o777, 0o666)
                finally:
                    path.chmod(original_mode)

    def test_legacy_upgrade_failure_restores_verified_legacy_install(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        original_cli = (self.prefix / "sbin/swapzctl").read_bytes()
        original_module = self.installed_module.read_bytes()
        source = self.home / "usr/src" / ("swapz-" + VERSION)
        (source / ".swapz-qualification").unlink()
        # Represent a verified installation from before Agent 9 added the
        # observer: neither monitoring artifact nor manifest line exists.
        (self.prefix / "sbin/swapz-primary-runtime-health").unlink()
        (self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service").unlink()
        binary_manifest = source / ".swapz-binaries.sha256"
        binary_manifest.write_text("".join(
            line for line in binary_manifest.read_text().splitlines(keepends=True)
            if "swapz-primary-runtime-health" not in line))
        manifest = source / ".swapz-sources.sha256"
        manifest.write_text("".join(
            line for line in manifest.read_text().splitlines(keepends=True)
            if ".swapz-qualification" not in line))

        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        result = self.invoke("install", {"SWAPZ_FAKE_FAIL_AT": "build"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attempting transaction rollback", result.stderr)
        self.assertEqual(
            (self.prefix / "sbin/swapzctl").read_bytes(), original_cli)
        self.assertEqual(self.installed_module.read_bytes(), original_module)
        self.assertFalse((source / ".swapz-qualification").exists())
        self.assertFalse((self.prefix / "sbin/swapz-primary-runtime-health").exists())
        self.assertFalse((self.prefix / "lib/systemd/system/swapz-primary-runtime-health.service").exists())
        self.assertFalse(list((self.home / "transactions").glob("swapz-package.*")))

    def test_uninstall_failed_reverification_revokes_activation(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        failed = self.invoke("uninstall", {
            "SWAPZ_TEST_UNINSTALL_FAIL_AFTER": "dkms-removed",
            "SWAPZ_TEST_UNINSTALL_ROLLBACK_VERIFY_FAILURE": "1",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("rollback incomplete", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        self.assertFalse(
            (self.prefix / "lib/systemd/system/swapz-primary-mapper.service").exists())
        transactions = self.uninstall_transactions()
        self.assertEqual(len(transactions), 1)
        state = json.loads((transactions[0] / "state.json").read_text())
        self.assertEqual(state["phase"], "rollback-incomplete")
        for entry in state["backup_files"]:
            self.assertEqual(
                sha256(transactions[0] / "backup" / entry["path"]),
                entry["sha256"])
        blocked = self.invoke("install")
        self.assertIn("incomplete package transaction retained", blocked.stderr)
        self.assertFalse((self.prefix / "sbin/swapz-primary-runtime-health").exists())

    def test_upgrade_terminal_rollback_journal_failure_quarantines(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        failed = self.invoke("install", {
            "SWAPZ_TEST_INSTALL_FAIL_AFTER": "dkms-removed",
            "SWAPZ_TEST_FAIL_TRANSACTION_PHASE": "rolled-back",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("previous package restoration failed", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        transactions = list((self.home / "transactions").glob("swapz-package.*"))
        self.assertEqual(len(transactions), 1)
        state = json.loads((transactions[0] / "state.json").read_text())
        self.assertEqual(state["phase"], "rollback-incomplete")
        for entry in state["backup_files"]:
            self.assertEqual(
                sha256(transactions[0] / "backup" / entry["path"]),
                entry["sha256"])
        refused = self.invoke("uninstall")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("incomplete package transaction retained", refused.stderr)

    def test_uninstall_terminal_rollback_journal_failure_quarantines(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        failed = self.invoke("uninstall", {
            "SWAPZ_TEST_UNINSTALL_FAIL_AFTER": "dkms-removed",
            "SWAPZ_TEST_FAIL_TRANSACTION_PHASE": "rolled-back",
        })
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("rollback incomplete", failed.stderr)
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        transactions = self.uninstall_transactions()
        self.assertEqual(len(transactions), 1)
        state = json.loads((transactions[0] / "state.json").read_text())
        self.assertEqual(state["phase"], "rollback-incomplete")

    def test_uninstall_unit_queries_distinguish_static_and_fail_closed(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        # systemctl is-enabled returns success for a static passive .swap
        # unit even though it cannot be enabled through an [Install] link.
        for overrides, expected in (
            ({"SWAPZ_FAKE_ACTIVE_SYSTEMD_UNIT":
              "swapz-primary-runtime-health.service"}, "is active"),
            ({"SWAPZ_FAKE_ENABLED_SYSTEMD_UNIT":
              "swapz-primary-runtime-health.service"}, "is enabled"),
            ({"SWAPZ_FAKE_SYSTEMCTL_QUERY_FAILURE": "1"}, "cannot verify"),
        ):
            with self.subTest(overrides=overrides):
                result = self.invoke("uninstall", overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assert_installed_exact()
                self.assertEqual(self.uninstall_transactions(), [])

        removed = self.invoke("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assert_absent()

    def test_uninstall_refuses_active_mapping_or_module(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        for flag in ("SWAPZ_TEST_MAPPING_ACTIVE", "SWAPZ_TEST_MODULE_ACTIVE"):
            result = self.invoke("uninstall", {flag: "1"})
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((self.prefix / "sbin/swapzctl").exists())
            self.assertTrue(self.installed_module.exists())

    def test_uninstall_every_destructive_transition_rolls_back(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        phases = (
            "activation-files-removed",
            "dkms-removed",
            "source-removed",
            "installed-module-removed",
            "depmod-complete",
            "systemd-reload-complete",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                result = self.invoke(
                    "uninstall", {"SWAPZ_TEST_UNINSTALL_FAIL_AFTER": phase})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("attempting transaction rollback", result.stderr)
                self.assert_installed_exact()
                self.assertEqual(self.uninstall_transactions(), [])

        self.fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "uninstall", {"SWAPZ_FAKE_FAIL_AT": "remove"})
        self.assertNotEqual(result.returncode, 0)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

    def test_uninstall_depmod_and_daemon_reload_failures_restore(self):
        self.assertEqual(self.invoke("install").returncode, 0)

        result = self.invoke(
            "uninstall", {"SWAPZ_FAKE_DEPMOD_FAIL_ONCE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attempting transaction rollback", result.stderr)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

        self.systemctl_fail_marker.unlink(missing_ok=True)
        result = self.invoke(
            "uninstall", {"SWAPZ_FAKE_SYSTEMCTL_FAIL_ONCE": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("attempting transaction rollback", result.stderr)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

        removed = self.invoke("uninstall")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assert_absent()

    def test_interrupt_during_uninstall_rolls_back(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        env = dict(self.env, SWAPZ_FAKE_REMOVE_SLEEP="30")
        process = subprocess.Popen(
            ["bash", str(self.script), "uninstall", str(self.prefix)],
            cwd=self.repo_root, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.remove_sleep_marker.exists():
                break
            time.sleep(0.05)
        else:
            process.kill()
            self.fail("mock DKMS remove did not start")
        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 143, stdout + "\n" + stderr)
        self.assertIn("interruption", stderr)
        self.assert_installed_exact()
        self.assertEqual(self.uninstall_transactions(), [])

    def test_interrupted_uninstall_rollback_retains_verifiable_state(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        build_count = self.dkms_log.read_text().splitlines().count("build")
        env = dict(
            self.env,
            SWAPZ_FAKE_DEPMOD_FAIL_ONCE="1",
            SWAPZ_FAKE_BUILD_SLEEP="30",
        )
        process = subprocess.Popen(
            ["bash", str(self.script), "uninstall", str(self.prefix)],
            cwd=self.repo_root, env=env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            lines = self.dkms_log.read_text().splitlines()
            if lines.count("build") > build_count:
                break
            time.sleep(0.05)
        else:
            process.kill()
            self.fail("uninstall rollback DKMS build did not start")

        os.killpg(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        self.assertIn(
            process.returncode,
            (-signal.SIGTERM, 128 + signal.SIGTERM),
            stdout + "\n" + stderr)
        transactions = self.uninstall_transactions()
        self.assertEqual(len(transactions), 1)
        transaction = transactions[0]
        state_path = transaction / "state.json"
        self.assertEqual(state_path.stat().st_mode & 0o777, 0o600)
        state = json.loads(state_path.read_text())
        self.assertEqual(state["schema"], "swapz-package-uninstall-v1")
        self.assertEqual(state["phase"], "rollback-started")
        self.assertGreater(len(state["backup_files"]), 0)
        for entry in state["backup_files"]:
            backup = transaction / "backup" / entry["path"]
            self.assertTrue(backup.is_file())
            self.assertEqual(sha256(backup), entry["sha256"])

        # Rollback restores the CLI only after DKMS, the exact module, depmod,
        # the other package files and systemd reload are valid again.
        self.assertFalse((self.prefix / "sbin/swapzctl").exists())
        blocked = self.invoke("install")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("incomplete package transaction retained", blocked.stderr)

    def test_installed_source_symlink_is_not_silently_accepted(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        source_version = (
            self.home / "usr/src" / ("swapz-" + VERSION) /
            "src/kernel/VERSION")
        source_version.unlink()
        source_version.symlink_to(ROOT / "src/kernel/VERSION")
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertTrue(source_version.is_symlink())
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)

    def test_installed_userspace_digest_mismatch_is_not_silently_repaired(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        binary = self.prefix / "sbin/swapzctl"
        binary.write_bytes(b"tampered-userspace\n")
        result = self.invoke("install")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("partial, foreign, or modified", result.stderr)
        self.assertEqual(binary.read_bytes(), b"tampered-userspace\n")
        self.assertNotEqual(self.invoke("uninstall").returncode, 0)

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
            ["bash", str(self.script), "install", str(self.prefix)],
            cwd=self.repo_root, env=env, stdout=subprocess.PIPE,
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

    def test_interrupted_upgrade_rollback_retains_verifiable_state(self):
        self.assertEqual(self.invoke("install").returncode, 0)
        build_count = self.dkms_log.read_text().splitlines().count("build")
        self.module.write_bytes(b"replacement-qualified-module\n")
        self.write_report()
        environment = dict(
            self.env,
            SWAPZ_FAKE_FAIL_AT="build",
            SWAPZ_FAKE_BUILD_SLEEP="30",
        )
        process = subprocess.Popen(
            ["bash", str(self.script), "install", str(self.prefix)],
            cwd=self.repo_root, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                lines = self.dkms_log.read_text().splitlines()
                if lines.count("build") >= build_count + 2:
                    break
                time.sleep(0.05)
            else:
                self.fail("upgrade rollback DKMS build did not start")

            transactions = list(
                (self.home / "transactions").glob("swapz-package.*"))
            self.assertEqual(len(transactions), 1)
            transaction = transactions[0]
            state = json.loads((transaction / "state.json").read_text())
            self.assertEqual(state["schema"], "swapz-package-install-v1")
            self.assertEqual(state["phase"], "rollback-started")

            os.killpg(process.pid, signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=8)
            self.assertIn(
                process.returncode,
                (-signal.SIGTERM, 128 + signal.SIGTERM),
                stdout + "\n" + stderr)
            self.assertFalse((self.prefix / "sbin/swapzctl").exists())
            for entry in state["backup_files"]:
                self.assertEqual(
                    sha256(transaction / "backup" / entry["path"]),
                    entry["sha256"])

            refused = self.invoke("install")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("incomplete package transaction retained",
                          refused.stderr)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=8)

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
