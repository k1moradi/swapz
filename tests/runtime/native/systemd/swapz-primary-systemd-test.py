#!/usr/bin/env python3
"""Rootless regression fixture for swapz primary systemd packaging.

The official rootless stage invokes this fixture. It never invokes swapon,
swapoff, a real mapper, or reboot.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGING = REPO_ROOT / "packaging"
GENERATOR = PACKAGING / "swapz-primary-generator"
MAPPER_SERVICE = PACKAGING / "swapz-primary-mapper.service"
PRIMARY_SWAP = PACKAGING / "swapz-primary.swap"
BOOT_VERIFY = PACKAGING / "swapz-primary-boot-verify"
BOOT_VERIFY_SERVICE = PACKAGING / "swapz-primary-boot-verify.service"
RUNTIME_HEALTH = PACKAGING / "swapz-primary-runtime-health"
RUNTIME_HEALTH_SERVICE = PACKAGING / "swapz-primary-runtime-health.service"

PARTUUID = "01234567-89abcdef"
OTHER_PARTUUID = "fedcba98-76543210"
BOOT_A = "11111111-1111-4111-8111-111111111111"
BOOT_B = "22222222-2222-4222-8222-222222222222"
SOURCE_SHA = "a" * 40
MODULE_SHA = "b" * 64
ACTIVE_RUN_ID = "0123456789abcdef0123456789abcdef"
TARGET_BYTES = 124_787_884_032


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_executable(path: Path, body: str) -> None:
    # Raw triple-quoted shell fixtures preserve the leading backslash/newline;
    # normalize it and its indentation before executing a mock script.
    if body.startswith("\\" + "\n"):
        body = textwrap.dedent(body[2:])
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


class GeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="swapz-systemd-generator-")
        self.root = Path(self.temp_dir.name)
        self.sbin = self.root / "sbin"
        self.sbin.mkdir()
        self.selector = self.root / "primary-target"
        self.selector.write_text(f"PARTUUID={PARTUUID}\n", encoding="ascii")
        self.selector.chmod(0o600)
        mock = self.sbin / "swapzctl"
        write_executable(
            mock,
            textwrap.dedent(
                r"""\
                #!/bin/sh
                if [ "${MOCK_UNITS+x}" = x ]; then
                    printf '%s' "$MOCK_UNITS"
                    exit "${MOCK_STATUS:-0}"
                fi
                selector=$MOCK_SELECTOR
                [ ! -L "$selector" ] || exit 2
                [ "$(stat -c '%u' -- "$selector")" -eq "$(id -u)" ] || exit 2
                [ "$(stat -c '%a' -- "$selector")" = 600 ] || exit 2
                [ "$(wc -l < "$selector" | tr -d ' ')" -eq 1 ] || exit 2
                line=$(cat -- "$selector") || exit 2
                partuuid=${line#PARTUUID=}
                [ "$line" != "$partuuid" ] || exit 2
                printf '%s\n' "$partuuid" | grep -Eq '^[0-9a-f][0-9a-f-]{6,62}[0-9a-f]$' || exit 2
                encoded=$(printf '%s\n' "$partuuid" | sed 's/-/\\x2d/g')
                printf 'dev-disk-by\\x2dpartuuid-%s.device dev-disk-by\\x2dpartuuid-%s.swap\n' "$encoded" "$encoded"
                """
            ),
        )
        generator_text = read_text(GENERATOR).replace("@SWAPZ_SBINDIR@", str(self.sbin))
        self.generator = self.root / "swapz-primary-generator"
        write_executable(self.generator, generator_text)
        self.normal = self.root / "normal"
        self.early = self.root / "early"
        self.late = self.root / "late"
        self.normal.mkdir()
        self.early.mkdir()
        self.late.mkdir()
        self.env = os.environ.copy()
        self.env["MOCK_SELECTOR"] = str(self.selector)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_generator(self, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.generator), str(self.normal), str(self.early), str(self.late)],
            check=False,
            text=True,
            capture_output=True,
            env=env or self.env,
        )

    @property
    def dropin(self) -> Path:
        return self.normal / "swapz-primary-mapper.service.d" / "50-selected-target.conf"

    def test_valid_selector_emits_exact_bounded_dropin_and_is_idempotent(self) -> None:
        first = self.run_generator()
        self.assertEqual(first.returncode, 0, first.stderr)
        expected_encoded = PARTUUID.replace("-", r"\x2d")
        expected = (
            "[Unit]\n"
            f"Requires=dev-disk-by\\x2dpartuuid-{expected_encoded}.device\n"
            f"After=dev-disk-by\\x2dpartuuid-{expected_encoded}.device\n"
            f"Conflicts=dev-disk-by\\x2dpartuuid-{expected_encoded}.swap\n"
            f"Before=dev-disk-by\\x2dpartuuid-{expected_encoded}.swap\n"
            "JobTimeoutSec=300s\n"
            "JobTimeoutAction=none\n"
        )
        self.assertEqual(self.dropin.read_text(encoding="ascii"), expected)
        first_identity = self.dropin.stat().st_ino
        second = self.run_generator()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.dropin.read_text(encoding="ascii"), expected)
        self.assertNotEqual(first_identity, self.dropin.stat().st_ino)
        # The separate udev .device job must be bounded as well as the mapper job.
        device_dropin = (
            self.normal / f"dev-disk-by\\x2dpartuuid-{expected_encoded}.device.d" /
            "50-swapz-timeout.conf"
        )
        self.assertEqual(
            device_dropin.read_text(encoding="ascii"),
            "[Unit]\nJobTimeoutSec=30s\nJobTimeoutAction=none\n",
        )

    def test_invalid_synthetic_selectors_fail_without_target_dropin(self) -> None:
        cases = (
            (f"PARTUUID={PARTUUID}\nextra\n", 0o600),
            (f"PARTUUID={PARTUUID.upper()}\n", 0o600),
            (f"PARTUUID={PARTUUID}\n", 0o666),
        )
        for contents, permissions in cases:
            with self.subTest(contents=contents, permissions=oct(permissions)):
                if self.dropin.parent.exists():
                    shutil.rmtree(self.dropin.parent)
                self.selector.write_text(contents, encoding="ascii")
                self.selector.chmod(permissions)
                result = self.run_generator()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.dropin.exists())

    def test_malformed_manager_responses_are_rejected(self) -> None:
        malformed = (
            "garbage\n",
            "dev-disk-by\\x2dpartuuid-01234567.device extra.swap extra\n",
            "dev-disk-by\\x2dpartuuid-01234567.device dev-disk-by\\x2dpartuuid-76543210.swap\n",
            "dev-disk-by\\x2dpartuuid-0123\\xZZ67.device dev-disk-by\\x2dpartuuid-0123\\xZZ67.swap\n",
            "dev-disk-by\\x2dpartuuid-ABCDEF12.device dev-disk-by\\x2dpartuuid-ABCDEF12.swap\n",
        )
        for response in malformed:
            with self.subTest(response=response):
                if self.dropin.parent.exists():
                    shutil.rmtree(self.dropin.parent)
                env = self.env.copy()
                env["MOCK_UNITS"] = response
                result = self.run_generator(env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.dropin.exists())

    def test_symlinked_output_is_rejected(self) -> None:
        target = self.root / "outside"
        target.mkdir()
        (self.normal / "swapz-primary-mapper.service.d").symlink_to(target, target_is_directory=True)
        result = self.run_generator()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((target / "50-selected-target.conf").exists())

    def test_hibernation_guards_are_generated_independently_of_mapper_activation(self) -> None:
        expected_encoded = PARTUUID.replace("-", r"\x2d")
        result = self.run_generator()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = (
            "[Service]\n"
            "ExecStartPre=" + str(self.sbin / "swapz-primary-runtime-health") + " hibernate-guard\n"
        )
        for unit in (
            "systemd-hibernate.service",
            "systemd-hybrid-sleep.service",
            "systemd-suspend-then-hibernate.service",
        ):
            dropin = self.normal / f"{unit}.d" / "50-swapz-no-hibernate.conf"
            self.assertEqual(dropin.read_text(encoding="ascii"), expected)

        env = self.env.copy()
        # Exercise the mocked manager's failure branch explicitly. MOCK_STATUS
        # is only consumed when MOCK_UNITS is supplied.
        env["MOCK_UNITS"] = (
            f"dev-disk-by\\x2dpartuuid-{expected_encoded}.device "
            f"dev-disk-by\\x2dpartuuid-{expected_encoded}.swap\n"
        )
        env["MOCK_STATUS"] = "1"
        if self.dropin.parent.exists():
            shutil.rmtree(self.dropin.parent)
        failed = self.run_generator(env=env)
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse(self.dropin.exists())
        for unit in (
            "systemd-hibernate.service",
            "systemd-hybrid-sleep.service",
            "systemd-suspend-then-hibernate.service",
        ):
            self.assertTrue((self.normal / f"{unit}.d" / "50-swapz-no-hibernate.conf").exists())



class UnitContractTests(unittest.TestCase):
    def test_mapper_lifecycle_is_bounded_and_ordered(self) -> None:
        service = read_text(MAPPER_SERVICE)
        self.assertIn("RequiresMountsFor=/var/lib/swapz/physical-recovery", service)
        self.assertIn("RefuseManualStart=yes", service)
        self.assertIn("RefuseManualStop=yes", service)
        self.assertIn("RemainAfterExit=yes", service)
        self.assertNotIn("TimeoutStopSec=infinity", service)
        self.assertRegex(service, r"TimeoutStartSec=\d+s")
        self.assertRegex(service, r"TimeoutStopSec=\d+s")
        lifecycle = [line for line in service.splitlines() if line.startswith(("ExecStartPre=", "ExecStart=", "ExecStop="))]
        self.assertEqual(
            lifecycle,
            [
                "ExecStartPre=@SWAPZ_SBINDIR@/swapz-primary-runtime-health activation-guard",
                "ExecStartPre=@SWAPZ_SBINDIR@/swapz-primary-boot-verify preflight",
                "ExecStartPre=-@SWAPZ_SBINDIR@/swapzctl primary recover",
                "ExecStartPre=@SWAPZ_SBINDIR@/swapzctl primary prepare",
                "ExecStart=@SWAPZ_SBINDIR@/swapzctl primary start",
                "ExecStop=@SWAPZ_SBINDIR@/swapzctl primary stop",
            ],
        )
        self.assertIn("After=-.mount systemd-modules-load.service dev-mapper-swapz\\x2dprimary.swap", service)
        self.assertIn("Before=swap.target shutdown.target", service)
        self.assertIn("WantedBy=swap.target", service)
        self.assertNotIn("PartOf=dev-mapper", service)
        self.assertIn("Conflicts=shutdown.target", service)
        self.assertIn("ExecStopPost=-@SWAPZ_SBINDIR@/swapz-primary-runtime-health stop-observe", service)
        self.assertNotIn("Restart=", service)

    def test_swap_unit_is_passive_and_cannot_request_second_swapon(self) -> None:
        swap = read_text(PRIMARY_SWAP)
        self.assertIn("What=/dev/mapper/swapz-primary", swap)
        self.assertIn("Priority=-1", swap)
        self.assertRegex(swap, r"TimeoutSec=\d+s")
        self.assertIn("RefuseManualStart=yes", swap)
        self.assertIn("RefuseManualStop=yes", swap)
        self.assertNotIn("WantedBy=swap.target", swap)
        self.assertNotIn("BindsTo=swapz-primary-mapper.service", swap)
        self.assertNotIn("Alias=", swap)
        self.assertIn("WantedBy=swap.target", read_text(MAPPER_SERVICE))

    def test_boot_verifier_is_automatic_observer_not_an_activator(self) -> None:
        service = read_text(BOOT_VERIFY_SERVICE)
        self.assertIn("After=swapz-primary-mapper.service dev-mapper-swapz\\x2dprimary.swap", service)
        self.assertIn("ExecStart=@SWAPZ_SBINDIR@/swapz-primary-boot-verify observe", service)
        self.assertRegex(service, r"TimeoutStartSec=\d+s")
        self.assertIn("WantedBy=multi-user.target", service)
        self.assertNotIn("Wants=swapz-primary-mapper.service", service)
        self.assertNotIn("Requires=swapz-primary-mapper.service", service)

    def test_runtime_health_service_is_observer_only_and_restarts_only_its_process(self) -> None:
        service = read_text(RUNTIME_HEALTH_SERVICE)
        self.assertIn("ExecStart=@SWAPZ_SBINDIR@/swapz-primary-runtime-health monitor", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("RestartSec=30s", service)
        self.assertIn("ConditionPathExists=/dev/mapper/swapz-primary", service)
        self.assertIn("WantedBy=swap.target", service)
        for hardening in (
            "ProtectKernelModules=yes",
            "ProtectClock=yes",
            "ProtectHostname=yes",
            "RestrictRealtime=yes",
            "SystemCallArchitectures=native",
        ):
            self.assertIn(hardening, service)
        self.assertNotIn("Wants=swapz-primary-mapper.service", service)
        self.assertNotIn("Requires=swapz-primary-mapper.service", service)
        helper = read_text(RUNTIME_HEALTH)
        self.assertNotRegex(helper, r"(^|[^A-Za-z])(swapon|swapoff)([^A-Za-z]|$)")
        self.assertNotIn("dmsetup remove", helper)
        self.assertNotIn("swapzctl primary start", helper)
        self.assertNotIn("swapzctl primary stop", helper)
        self.assertIn("PATH=/usr/sbin:/usr/bin:/sbin:/bin", helper)
        self.assertIn("run_bounded()", helper)


    def test_raw_multiline_mock_has_real_shell_shebang(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-raw-shell-") as directory:
            mock = Path(directory) / "mock"
            write_executable(
                mock,
                textwrap.dedent(
                    r"""\
                    #!/bin/sh
                    printf 'mock-ok\n'
                    """
                ),
            )
            self.assertTrue(read_text(mock).startswith("#!/bin/sh\n"))
            result = subprocess.run(
                [str(mock)], check=False, text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "mock-ok\n")

    def test_systemd_analyze_accepts_static_units(self) -> None:
        analyzer = shutil.which("systemd-analyze")
        if analyzer is None:
            self.skipTest("systemd-analyze unavailable")
        with tempfile.TemporaryDirectory(prefix="swapz-unit-verify-") as temp:
            unit_dir = Path(temp)
            service = read_text(MAPPER_SERVICE)
            service = service.replace("@SWAPZ_SBINDIR@/swapz-primary-boot-verify", "/usr/bin/true")
            service = service.replace("@SWAPZ_SBINDIR@/swapzctl", "/usr/bin/true")
            service = service.replace("@SWAPZ_SBINDIR@/swapz-primary-runtime-health", "/usr/bin/true")
            (unit_dir / "swapz-primary-mapper.service").write_text(service, encoding="utf-8")
            (unit_dir / r"dev-mapper-swapz\x2dprimary.swap").write_text(read_text(PRIMARY_SWAP), encoding="utf-8")
            verifier = read_text(BOOT_VERIFY_SERVICE).replace(
                "@SWAPZ_SBINDIR@/swapz-primary-boot-verify", "/usr/bin/true"
            )
            (unit_dir / "swapz-primary-boot-verify.service").write_text(verifier, encoding="utf-8")
            runtime = read_text(RUNTIME_HEALTH_SERVICE).replace(
                "@SWAPZ_SBINDIR@/swapz-primary-runtime-health", "/usr/bin/true"
            )
            (unit_dir / "swapz-primary-runtime-health.service").write_text(runtime, encoding="utf-8")
            env = os.environ.copy()
            env["SYSTEMD_UNIT_PATH"] = f"{unit_dir}:/usr/lib/systemd/system:/lib/systemd/system"
            result = subprocess.run(
                [
                    analyzer,
                    "verify",
                    str(unit_dir / "swapz-primary-mapper.service"),
                    str(unit_dir / r"dev-mapper-swapz\x2dprimary.swap"),
                    str(unit_dir / "swapz-primary-boot-verify.service"),
                    str(unit_dir / "swapz-primary-runtime-health.service"),
                ],
                check=False,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


class ControlledLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="swapz-lifecycle-")
        self.root = Path(self.temp_dir.name)
        self.sbin = self.root / "sbin"
        self.sbin.mkdir()
        self.log = self.root / "calls.log"
        write_executable(
            self.sbin / "swapz-primary-boot-verify",
            textwrap.dedent(
                """\
                #!/bin/sh
                printf 'verify:%s\\n' "$1" >> "$MOCK_LIFECYCLE_LOG"
                exit "${MOCK_PREFLIGHT_STATUS:-0}"
                """
            ),
        )
        write_executable(
            self.sbin / "swapzctl",
            textwrap.dedent(
                """\
                #!/bin/sh
                action=$2
                printf 'swapzctl:%s\\n' "$action" >> "$MOCK_LIFECYCLE_LOG"
                case "$action" in
                recover) exit "${MOCK_RECOVER_STATUS:-0}" ;;
                prepare) exit "${MOCK_PREPARE_STATUS:-0}" ;;
                start) exit "${MOCK_START_STATUS:-0}" ;;
                stop) exit "${MOCK_STOP_STATUS:-0}" ;;
                *) exit 2 ;;
                esac
                """
            ),
        )
        write_executable(
            self.sbin / "swapz-primary-runtime-health",
            textwrap.dedent(
                """\
                #!/bin/sh
                printf 'runtime:%s\\n' "$1" >> "$MOCK_LIFECYCLE_LOG"
                exit "${MOCK_RUNTIME_STATUS:-0}"
                """
            ),
        )
        self.service = read_text(MAPPER_SERVICE).replace("@SWAPZ_SBINDIR@", str(self.sbin))
        self.env = os.environ.copy()
        self.env["MOCK_LIFECYCLE_LOG"] = str(self.log)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def execute_start_contract(self, env: dict[str, str]) -> int:
        for line in self.service.splitlines():
            if not line.startswith(("ExecStartPre=", "ExecStart=")):
                continue
            command = line.split("=", 1)[1]
            ignore_failure = command.startswith("-")
            if ignore_failure:
                command = command[1:]
            result = subprocess.run(shlex.split(command), check=False, env=env)
            if result.returncode and not ignore_failure:
                return result.returncode
        return 0

    def execute_stop_contract(self, env: dict[str, str]) -> int:
        line = next(line for line in self.service.splitlines() if line.startswith("ExecStop="))
        return subprocess.run(shlex.split(line.split("=", 1)[1]), check=False, env=env).returncode

    def execute_stop_post_contract(self, env: dict[str, str]) -> int:
        line = next(line for line in self.service.splitlines() if line.startswith("ExecStopPost="))
        command = line.split("=", 1)[1]
        if command.startswith("-"):
            command = command[1:]
        return subprocess.run(shlex.split(command), check=False, env=env).returncode

    def test_recovery_probe_may_fail_but_prepare_start_still_run(self) -> None:
        env = self.env.copy()
        env["MOCK_RECOVER_STATUS"] = "2"
        self.assertEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["runtime:activation-guard", "verify:preflight", "swapzctl:recover", "swapzctl:prepare", "swapzctl:start"],
        )
        self.assertEqual(self.execute_stop_contract(env), 0)
        self.assertEqual(self.log.read_text(encoding="ascii").splitlines()[-1], "swapzctl:stop")

    def test_prepare_failure_blocks_start(self) -> None:
        env = self.env.copy()
        env["MOCK_PREPARE_STATUS"] = "2"
        self.assertNotEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["runtime:activation-guard", "verify:preflight", "swapzctl:recover", "swapzctl:prepare"],
        )

    def test_stop_failure_is_not_retried_and_diagnostics_do_not_mask_it(self) -> None:
        env = self.env.copy()
        env["MOCK_STOP_STATUS"] = "5"
        env["MOCK_RUNTIME_STATUS"] = "7"
        self.assertEqual(self.execute_stop_contract(env), 5)
        self.assertEqual(self.execute_stop_post_contract(env), 7)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["swapzctl:stop", "runtime:stop-observe"],
        )



class BootVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="swapz-boot-verify-")
        self.root = Path(self.temp_dir.name)
        self.prefix = self.root / "usr" / "local"
        self.sbin = self.prefix / "sbin"
        self.libexec = self.prefix / "libexec" / "swapz"
        self.bin = self.root / "mock-bin"
        self.proc = self.root / "proc"
        self.sys = self.root / "sys"
        self.dev = self.root / "dev"
        self.etc = self.root / "etc"
        self.report = self.root / "var" / "lib" / "swapz" / "boot-acceptance"
        self.recovery = self.report.parent / "physical-recovery"
        for directory in (self.sbin, self.libexec, self.bin, self.proc, self.sys, self.dev, self.etc, self.report, self.recovery):
            directory.mkdir(parents=True, exist_ok=True)
        self.report.chmod(0o700)
        self.recovery.chmod(0o700)
        (self.proc / "sys" / "kernel" / "random").mkdir(parents=True)
        # Model a readable running-kernel hibernation state with no resume
        # target configured. Individual tests override these files when they
        # exercise conflicting or unreadable resume configuration.
        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        (self.sys / "power").mkdir(parents=True)
        (self.sys / "power" / "resume").write_text("0:0\n", encoding="ascii")
        (self.sys / "module" / "dm_swapz" / "parameters").mkdir(parents=True)
        (self.dev / "disk" / "by-partuuid").mkdir(parents=True)
        (self.dev / "disk" / "by-uuid").mkdir(parents=True)
        (self.dev / "mapper").mkdir(parents=True)
        (self.dev / "sda").touch()
        (self.dev / "mapper" / "swapz-primary").touch()
        for partuuid in (PARTUUID, OTHER_PARTUUID):
            (self.dev / "disk" / "by-partuuid" / partuuid).touch()
        (self.dev / "disk" / "by-uuid" / "target-uuid").touch()
        (self.libexec / "dm-swapz.ko").write_bytes(b"mock-module")
        shutil.copy2(BOOT_VERIFY, self.sbin / "swapz-primary-boot-verify")
        (self.sbin / "swapz-primary-boot-verify").chmod(0o755)
        shutil.copy2(RUNTIME_HEALTH, self.sbin / "swapz-primary-runtime-health")
        (self.sbin / "swapz-primary-runtime-health").chmod(0o755)
        write_executable(
            self.sbin / "swapzctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                if [ "$1" = primary ] && [ "$2" = plan ]; then
                    if [ "${MOCK_PLAN_BODY+x}" = x ]; then
                        printf '%s\n' "$MOCK_PLAN_BODY"
                    else
                        printf '%s\n' '{"schema":"swapz-primary-plan-v1","status":"BLOCKED","recovery_preflight_read":true,"recovery_filesystem_supported":true,"recovery_directly_not_target":true,"recovery_source_chain_checked":true,"recovery_same_physical_disk_as_target":false}'
                    fi
                    exit "${MOCK_PLAN_STATUS:-2}"
                fi
                [ "$1" = primary ] && [ "$2" = systemd-units ] || exit 2
                partuuid=${MOCK_PARTUUID:-01234567-89abcdef}
                encoded=$(printf '%s\n' "$partuuid" | sed 's/-/\\x2d/g')
                printf 'dev-disk-by\\x2dpartuuid-%s.device dev-disk-by\\x2dpartuuid-%s.swap\n' "$encoded" "$encoded"
                """
            ),
        )
        self.create_mocks()
        self.write_boot_id(BOOT_A)
        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        self.write_proc_swaps(active=True)
        (self.sys / "module" / "dm_swapz" / "parameters" / "build_source_sha").write_text(SOURCE_SHA + "\n", encoding="ascii")
        (self.sys / "module" / "dm_swapz" / "parameters" / "build_source_clean").write_text("1\n", encoding="ascii")
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{self.bin}:{self.env['PATH']}",
                "SWAPZ_PRIMARY_SYSTEMD_TESTING": "1",
                "SWAPZ_PRIMARY_TEST_PATH": f"{self.bin}:/usr/sbin:/usr/bin:/sbin:/bin",
                "SWAPZ_PRIMARY_TEST_COMMAND_TIMEOUT_SECONDS": "2",
                "SWAPZ_PRIMARY_TEST_PROC_ROOT": str(self.proc),
                "SWAPZ_PRIMARY_TEST_SYS_ROOT": str(self.sys),
                "SWAPZ_PRIMARY_TEST_DEV_ROOT": str(self.dev),
                "SWAPZ_PRIMARY_TEST_ETC_ROOT": str(self.etc),
                "SWAPZ_PRIMARY_TEST_REPORT_BASE": str(self.report),
                "SWAPZ_PRIMARY_TEST_RECOVERY_BASE": str(self.recovery),
                "SWAPZ_PRIMARY_TEST_MODULE_ARTIFACT": str(self.libexec / "dm-swapz.ko"),
                "MOCK_PARTUUID": PARTUUID,
                "MOCK_TARGET_BYTES": str(TARGET_BYTES),
                "MOCK_MODULE_SHA": MODULE_SHA,
                "MOCK_SOURCE_SHA": SOURCE_SHA,
                "MOCK_FSTAB_SOURCE": "",
                "MOCK_RAW_UNIT_WHAT": "",
                "MOCK_MAPPER_ACTIVE": "active",
                "MOCK_MAPPER_SUB": "exited",
                "MOCK_MAPPER_RESULT": "success",
                "MOCK_SWAP_ACTIVE": "active",
                "MOCK_SWAP_SUB": "active",
                "MOCK_SWAP_RESULT": "success",
                "MOCK_DM_STATUS_FAIL": "0",
                "MOCK_DM_DISCARD_FAIL": "0",
                "MOCK_JOURNAL_ERROR": "0",
            }
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def create_mocks(self) -> None:
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$1" = -dnro ] || exit 2
                field=$2
                path=$4
                case "$path" in
                */mapper/swapz-primary)
                    case "$field" in TYPE) echo lvm ;; MAJ:MIN) echo 253:0 ;; SIZE) echo 249000000000 ;; PKNAME) echo ;; *) echo ;; esac
                    ;;
                */disk/by-partuuid/*|*/disk/by-uuid/target-uuid)
                    case "$field" in TYPE) echo part ;; MAJ:MIN) echo 8:1 ;; SIZE) echo "$MOCK_TARGET_BYTES" ;; PKNAME) echo sda ;; *) echo ;; esac
                    ;;
                */sda)
                    case "$field" in MODEL) echo "${MOCK_READER_MODEL:-USB Multi-Card}" ;; SERIAL) echo "${MOCK_READER_SERIAL-reader-serial}" ;; WWN) echo "${MOCK_READER_WWN:-}" ;; TRAN) echo "${MOCK_READER_TRANSPORT:-usb}" ;; RM) echo "${MOCK_READER_REMOVABLE:-1}" ;; MAJ:MIN) echo 8:0 ;; TYPE) echo disk ;; PKNAME) echo ;; *) echo ;; esac
                    ;;
                */zram0)
                    case "$field" in TYPE) echo disk ;; MAJ:MIN) echo 254:0 ;; SIZE) echo 1024 ;; PKNAME) echo ;; *) echo ;; esac
                    ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "blockdev",
            "#!/bin/sh\nprintf '%s\\n' \"$MOCK_TARGET_BYTES\"\n",
        )
        write_executable(
            self.bin / "sha256sum",
            "#!/bin/sh\nprintf '%s  %s\\n' \"$MOCK_MODULE_SHA\" \"$2\"\n",
        )
        write_executable(
            self.bin / "modinfo",
            textwrap.dedent(
                """\
                #!/bin/sh
                case "$2" in
                swapz_build_source_sha) printf '%s\\n' "$MOCK_SOURCE_SHA" ;;
                swapz_build_source_clean) printf '1\\n' ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "findmnt",
            textwrap.dedent(
                """\
                #!/bin/sh
                if [ -n "${MOCK_FSTAB_SOURCE:-}" ]; then
                    printf '%s\\n' "$MOCK_FSTAB_SOURCE"
                    exit 0
                fi
                exit 1
                """
            ),
        )
        write_executable(
            self.bin / "systemctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                if [ "$1" = list-units ]; then
                    printf 'dev-mapper-swapz\\x2dprimary.swap loaded %s %s Primary swap\n' "${MOCK_SWAP_ACTIVE:-active}" "${MOCK_SWAP_SUB:-active}"
                    if [ -n "${MOCK_RAW_UNIT_WHAT:-}" ] || [ "${MOCK_RAW_UNIT_PRESENT:-0}" = 1 ]; then
                        printf 'raw-target.swap loaded inactive dead Raw target\n'
                    fi
                    exit 0
                fi
                if [ "$1" = show ]; then
                    property=
                    unit=
                    while [ "$#" -gt 0 ]; do
                        case "$1" in
                        --property=*) property=${1#--property=} ;;
                        --value) ;;
                        *) unit=$1 ;;
                        esac
                        shift
                    done
                    if [ "$property" = What ]; then
                        [ "$unit" = raw-target.swap ] && printf '%s\n' "$MOCK_RAW_UNIT_WHAT"
                        exit 0
                    fi
                    case "$unit:$property" in
                    swapz-primary-mapper.service:ActiveState) printf '%s\n' "$MOCK_MAPPER_ACTIVE" ;;
                    swapz-primary-mapper.service:SubState) printf '%s\n' "$MOCK_MAPPER_SUB" ;;
                    swapz-primary-mapper.service:Result) printf '%s\n' "$MOCK_MAPPER_RESULT" ;;
                    'dev-mapper-swapz\x2dprimary.swap':ActiveState) printf '%s\n' "$MOCK_SWAP_ACTIVE" ;;
                    'dev-mapper-swapz\x2dprimary.swap':SubState) printf '%s\n' "$MOCK_SWAP_SUB" ;;
                    'dev-mapper-swapz\x2dprimary.swap':Result) printf '%s\n' "$MOCK_SWAP_RESULT" ;;
                    *) exit 1 ;;
                    esac
                    exit 0
                fi
                exit 2
                """
            ),
        )
        write_executable(
            self.bin / "dmsetup",
            textwrap.dedent(
                """\
                #!/bin/sh
                case "$1" in
                info) printf '%s\\n' "${MOCK_DM_UUID:-SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef}" ;;
                table) printf '%s\\n' "${MOCK_DM_TABLE:-0 216641536 swapz 8:1 0 64 0 2 0 1 0 0}" ;;
                status)
                    printf '0 216641536 swapz version=0 flush_err=0 segment_discards_failed=%s failed=%s error=0 upper_write_completed_err=0 endio_write_seen_err=0 endio_write_forced_err=0\\n' "$MOCK_DM_DISCARD_FAIL" "$MOCK_DM_STATUS_FAIL"
                    ;;
                *) exit 2 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "sync",
            "#!/bin/sh\nexit 0\n",
        )
        write_executable(
            self.bin / "journalctl",
            textwrap.dedent(
                """\
                #!/bin/sh
                if [ "${MOCK_JOURNAL_UNAVAILABLE:-0}" = 1 ]; then exit 1; fi
                if [ "${MOCK_JOURNAL_ERROR:-0}" = 1 ]; then
                    printf '[1.0] kernel: dm-swapz: I/O error on swapz target\\n'
                fi
                exit 0
                """
            ),
        )

    def write_boot_id(self, boot_id: str) -> None:
        (self.proc / "sys" / "kernel" / "random" / "boot_id").write_text(boot_id + "\n", encoding="ascii")

    def write_proc_swaps(self, *, active: bool) -> None:
        lines = ["Filename Type Size Used Priority"]
        if active:
            lines.append(f"{self.dev / 'mapper' / 'swapz-primary'} partition 108320764 0 -1")
        (self.proc / "swaps").write_text("\n".join(lines) + "\n", encoding="ascii")

    def run_verifier(self, action: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.sbin / "swapz-primary-boot-verify"), action],
            check=False,
            text=True,
            capture_output=True,
            env=env or self.env,
        )

    def arm_then_reboot(self) -> None:
        self.write_proc_swaps(active=False)
        arm = self.run_verifier("arm")
        self.assertEqual(arm.returncode, 0, arm.stderr)
        self.assertIn("COLD_BOOT_HARNESS=ARMED", arm.stdout)
        self.assertIn("COLD_BOOT_OBSERVED=NO", arm.stdout)
        same_boot = self.run_verifier("preflight")
        self.assertNotEqual(same_boot.returncode, 0)
        self.assertIn("owner reboot has not occurred", same_boot.stderr)
        self.write_boot_id(BOOT_B)
        self.write_proc_swaps(active=True)
        self.write_active_transaction()

    def write_active_transaction(self) -> None:
        (self.recovery / "primary-state.json").write_text(
            f'{{"schema":"swapz-primary-state-v1","run_id":"{ACTIVE_RUN_ID}",'
            '"stage":"ACTIVE","recovery_previous_stage":null}\n',
            encoding="ascii",
        )
        claim = (
            f'{{"major":8,"minor":1,"partuuid":"{PARTUUID}",'
            f'"run_id":"{ACTIVE_RUN_ID}"}}\n'
        )
        (self.recovery / f"partition-{PARTUUID}.active").write_text(claim, encoding="ascii")
        (self.recovery / f"consumed-{ACTIVE_RUN_ID}.json").write_text(claim, encoding="ascii")
        for path in self.recovery.iterdir():
            path.chmod(0o600)

    def test_observe_without_arm_is_incomplete(self) -> None:
        result = self.run_verifier("observe")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=INCOMPLETE", result.stdout)
        latest = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("status=INCOMPLETE", latest)
        self.assertIn("harness_not_armed", latest)

    def test_arm_preflight_and_cross_boot_observation_pass(self) -> None:
        self.arm_then_reboot()
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertIn("PRIMARY_BOOT_PREFLIGHT=PASS", preflight.stdout)
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=PASS", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        required = (
            "status=PASS",
            f"boot_id={BOOT_B}",
            "kernel_release=",
            f"selected_partuuid={PARTUUID}",
            "selected_target_major_minor=8:1",
            "selected_target_model=USB Multi-Card",
            f"module_artifact_sha256={MODULE_SHA}",
            f"module_build_source_sha={SOURCE_SHA}",
            f"loaded_module_build_source_sha={SOURCE_SHA}",
            "dm_uuid=SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef",
            "expected_dm_logical_sectors=216641536",
            "dm_logical_bytes=110920466432",
            "swap_size_kib=108320764",
            "swap_mapper_entries=1",
            "swap_priority=-1",
            "mapper_service_active_state=active",
            "swap_unit_active_state=active",
            "swapz_failed=0",
            "swapz_flush_err=0",
            "kernel_error_count=0",
        )
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, report)
        self.assertTrue((self.report / f"report-{BOOT_B}.kernel-errors.log").exists())
        self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").exists())

    def test_read_only_plan_exit_two_is_accepted_for_persistence_proof(self) -> None:
        self.write_proc_swaps(active=False)
        arm = self.run_verifier("arm")
        self.assertEqual(arm.returncode, 0, arm.stderr)
        self.assertIn("COLD_BOOT_HARNESS=ARMED", arm.stdout)

    def test_unexpected_plan_status_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        env = self.env.copy()
        env["MOCK_PLAN_STATUS"] = "1"
        result = self.run_verifier("arm", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot query read-only recovery storage plan", result.stderr)

    def test_missing_plan_persistence_proof_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        env = self.env.copy()
        env["MOCK_PLAN_BODY"] = (
            '{"schema":"swapz-primary-plan-v1","status":"BLOCKED",'
            '"recovery_preflight_read":true,'
            '"recovery_filesystem_supported":true,'
            '"recovery_directly_not_target":true,'
            '"recovery_source_chain_checked":true,'
            '"recovery_same_physical_disk_as_target":true}'
        )
        result = self.run_verifier("arm", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot prove recovery and boot evidence", result.stderr)

    def test_raw_fstab_alias_blocks_preflight_without_swap_commands(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_FSTAB_SOURCE"] = str(self.dev / "disk" / "by-uuid" / "target-uuid")
        result = self.run_verifier("preflight", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fstab still configures selected partition as raw swap", result.stderr)
        script = read_text(BOOT_VERIFY)
        self.assertNotRegex(script, r"(^|[^A-Za-z])(swapoff|swapon)([^A-Za-z]|$)")

    def test_loaded_raw_alias_blocks_preflight(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_RAW_UNIT_WHAT"] = str(self.dev / "disk" / "by-uuid" / "target-uuid")
        result = self.run_verifier("preflight", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("loaded raw swap unit aliases selected partition", result.stderr)

    def test_duplicate_mapper_unit_is_rejected_by_resolved_identity(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_RAW_UNIT_WHAT"] = str(self.dev / "mapper" / "swapz-primary")
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("selected_target_raw_swap_alias_or_inventory_unavailable", report)
        self.assertIn("loaded swap unit duplicates primary mapper activation", observed.stderr)

    def test_uninspectable_loaded_swap_unit_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        env = self.env.copy()
        env["MOCK_RAW_UNIT_PRESENT"] = "1"
        observed = self.run_verifier("arm", env=env)
        self.assertNotEqual(observed.returncode, 0)
        self.assertIn("ambiguous What= of loaded swap unit", observed.stderr)

    def test_active_raw_alias_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        raw_path = self.dev / "disk" / "by-uuid" / "target-uuid"
        (self.proc / "swaps").write_text(
            f"Filename Type Size Used Priority\n{raw_path} partition 121863168 0 -1\n",
            encoding="ascii",
        )
        result = self.run_verifier("arm")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected partition is already active as raw swap", result.stderr)

    def test_unresolved_device_fstab_source_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        env = self.env.copy()
        env["MOCK_FSTAB_SOURCE"] = str(self.dev / "disk" / "by-uuid" / "missing")
        result = self.run_verifier("arm", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unresolved fstab block-device swap source", result.stderr)

    def test_substituted_selector_is_rejected_after_arm(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_PARTUUID"] = OTHER_PARTUUID
        result = self.run_verifier("preflight", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected PARTUUID changed", result.stderr)

    def test_missing_selected_media_is_rejected_after_arm(self) -> None:
        self.arm_then_reboot()
        (self.dev / "disk" / "by-partuuid" / PARTUUID).unlink()
        result = self.run_verifier("preflight")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected PARTUUID device is unavailable after reboot", result.stderr)

    def test_changed_module_bytes_are_rejected_after_arm(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_MODULE_SHA"] = "f" * 64
        result = self.run_verifier("preflight", env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("installed module bytes changed after arming", result.stderr)

    def test_foreign_mapper_uuid_with_valid_prefix_cannot_pass(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_DM_UUID"] = "SWAPZ-PRIMARY-" + "f" * 32
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("mapper_uuid_not_bound_to_active_run", report)
        self.assertIn(f"active_transaction_run_id={ACTIVE_RUN_ID}", report)

    def test_missing_active_transaction_record_cannot_pass(self) -> None:
        self.arm_then_reboot()
        (self.recovery / "primary-state.json").unlink()
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("primary_active_transaction_or_owner_claim_invalid", report)

    def test_stale_or_substituted_active_owner_claim_cannot_pass(self) -> None:
        self.arm_then_reboot()
        (self.recovery / f"partition-{PARTUUID}.active").write_text(
            f'{{"major":8,"minor":1,"partuuid":"{PARTUUID}","run_id":"' + 'f' * 32 + '"}\n',
            encoding="ascii",
        )
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("primary_active_transaction_or_owner_claim_invalid", report)

    def test_wrong_mapper_geometry_records_fail(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        # Exact retired zero-COW-headroom maximum must never pass boot verification.
        env["MOCK_DM_TABLE"] = "0 216643584 swapz 8:1 0 64 0 2 0 1 0 0"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=FAIL", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("mapper_logical_capacity_mismatch", report)

    def test_failed_mapper_observation_records_fail(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_MAPPER_ACTIVE"] = "failed"
        env["MOCK_MAPPER_RESULT"] = "exit-code"
        env["MOCK_DM_STATUS_FAIL"] = "1"
        env["MOCK_DM_DISCARD_FAIL"] = "1"
        env["MOCK_JOURNAL_ERROR"] = "1"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=FAIL", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("status=FAIL", report)
        self.assertIn("swapz_target_failed", report)
        self.assertIn("swapz_segment_discard_failures", report)
        self.assertIn("mapper_service_not_active", report)
        self.assertIn("relevant_kernel_errors", report)

    def test_unrelated_file_swap_is_allowed_but_primary_is_unique(self) -> None:
        self.arm_then_reboot()
        with (self.proc / "swaps").open("a", encoding="ascii") as swaps:
            swaps.write("/swapfile file 32768 0 -2\n")
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("status=PASS", report)
        self.assertIn("swap_total_entries=2", report)
        self.assertIn("swap_mapper_entries=1", report)

    def test_changed_parent_serial_cannot_pass_observation(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_READER_SERIAL"] = "substituted-reader"
        self.assertNotEqual(self.run_verifier("preflight", env=env).returncode, 0)
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("selected_parent_serial_mismatch", report)

    def test_parent_without_stable_serial_or_wwn_cannot_arm(self) -> None:
        self.write_proc_swaps(active=False)
        env = self.env.copy()
        env["MOCK_READER_SERIAL"] = ""
        observed = self.run_verifier("arm", env=env)
        self.assertNotEqual(observed.returncode, 0)
        self.assertIn("neither a stable serial nor WWN", observed.stderr)

    def test_raw_swap_alias_configured_after_arm_prevents_pass(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_FSTAB_SOURCE"] = str(self.dev / "disk" / "by-uuid" / "target-uuid")
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("selected_target_raw_swap_alias_or_inventory_unavailable", report)

    def test_unresolved_active_device_swap_is_rejected(self) -> None:
        self.write_proc_swaps(active=False)
        missing = self.dev / "disk" / "by-uuid" / "missing"
        (self.proc / "swaps").write_text(
            f"Filename Type Size Used Priority\n{missing} partition 4096 0 0\n",
            encoding="ascii",
        )
        observed = self.run_verifier("arm")
        self.assertNotEqual(observed.returncode, 0)
        self.assertIn("unresolved active block-device swap", observed.stderr)

    def test_oversized_mapper_length_produces_persistent_fail(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_DM_TABLE"] = "0 999999999999999999999999 swapz 8:1 0 64 0 2 0 1 0 0"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("mapper_table_invalid", report)

    def test_multiline_dm_table_cannot_inject_report_fields(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_DM_TABLE"] = "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0\nstatus=PASS"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertEqual(sum(line.startswith("status=") for line in report.splitlines()), 1)
        self.assertIn("status=FAIL", report)

    def test_early_kernel_mismatch_persists_fail_instead_of_exiting_unbound(self) -> None:
        self.arm_then_reboot()
        write_executable(
            self.bin / "uname",
            "#!/bin/sh\nif [ \"$1\" = -r ]; then echo unexpected-kernel; else exit 2; fi\n",
        )
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=FAIL", observed.stdout)
        latest = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("kernel_release_mismatch", latest)
        self.assertIn("status=FAIL", latest)

    def test_unavailable_kernel_log_is_incomplete_not_pass(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_JOURNAL_UNAVAILABLE"] = "1"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=INCOMPLETE", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("kernel_log_unavailable", report)


    def test_hibernation_resume_configuration_blocks_arm_and_preflight(self) -> None:
        self.write_proc_swaps(active=False)
        (self.proc / "cmdline").write_text(
            "quiet resume=/dev/mapper/swapz-primary\n", encoding="ascii"
        )
        arm = self.run_verifier("arm")
        self.assertNotEqual(arm.returncode, 0)
        self.assertIn("unsupported hibernation/resume configuration", arm.stderr)

        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        self.arm_then_reboot()
        (self.proc / "cmdline").write_text(
            f"quiet resume=PARTUUID={PARTUUID}\n", encoding="ascii"
        )
        preflight = self.run_verifier("preflight")
        self.assertNotEqual(preflight.returncode, 0)
        self.assertIn("unsupported hibernation/resume configuration", preflight.stderr)

    def test_hibernation_configuration_drift_prevents_cold_boot_pass(self) -> None:
        self.arm_then_reboot()
        config_dir = self.etc / "initramfs-tools" / "conf.d"
        config_dir.mkdir(parents=True)
        (config_dir / "resume").write_text("RESUME=auto\n", encoding="ascii")
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("hibernation_resume_configuration_conflict", report)


class RuntimeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="swapz-runtime-health-")
        self.root = Path(self.temp_dir.name)
        self.sbin = self.root / "sbin"
        self.bin = self.root / "bin"
        self.proc = self.root / "proc"
        self.sys = self.root / "sys"
        self.dev = self.root / "dev"
        self.etc = self.root / "etc"
        self.recovery = self.root / "recovery"
        for directory in (
            self.sbin, self.bin, self.proc, self.sys, self.dev, self.etc, self.recovery
        ):
            directory.mkdir(parents=True, exist_ok=True)
        (self.dev / "mapper").mkdir()
        (self.dev / "disk" / "by-partuuid").mkdir(parents=True)
        (self.etc / "swapz").mkdir()
        (self.etc / "swapz" / "primary-target").write_text(
            f"PARTUUID={PARTUUID}\n", encoding="ascii"
        )
        (self.etc / "swapz" / "primary-target").chmod(0o600)
        (self.dev / "mapper" / "swapz-primary").touch()
        (self.dev / "disk" / "by-partuuid" / PARTUUID).touch()
        (self.sys / "power").mkdir(parents=True)
        (self.sys / "power" / "resume").write_text("0:0\n", encoding="ascii")
        (self.sys / "dev" / "block" / "253:0" / "dm").mkdir(parents=True)
        (self.sys / "dev" / "block" / "253:0" / "dm" / "name").write_text(
            "swapz-primary\n", encoding="ascii"
        )
        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'} partition 108320764 1024 -1\n",
            encoding="ascii",
        )
        (self.recovery / "primary-state.json").write_text(
            f'{{"schema":"swapz-primary-state-v1","run_id":"{ACTIVE_RUN_ID}",'
            '"stage":"ACTIVE","recovery_previous_stage":null}\n',
            encoding="ascii",
        )
        (self.recovery / f"partition-{PARTUUID}.active").write_text(
            f'{{"major":8,"minor":1,"partuuid":"{PARTUUID}",'
            f'"run_id":"{ACTIVE_RUN_ID}"}}\n',
            encoding="ascii",
        )
        shutil.copy2(RUNTIME_HEALTH, self.sbin / "swapz-primary-runtime-health")
        (self.sbin / "swapz-primary-runtime-health").chmod(0o755)
        write_executable(
            self.sbin / "swapzctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$1" = primary ] && [ "$2" = systemd-units ] || exit 2
                printf 'dev-disk-by\x2dpartuuid-01234567\x2d89abcdef.device dev-disk-by\x2dpartuuid-01234567\x2d89abcdef.swap\n'
                """
            ),
        )
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                field=$2
                path=$4
                case "$path" in
                */disk/by-partuuid/*) [ "$field" = MAJ:MIN ] && echo 8:1 || exit 1 ;;
                */mapper/swapz-primary) [ "$field" = MAJ:MIN ] && echo 253:0 || exit 1 ;;
                */uuid-target) [ "$field" = MAJ:MIN ] && echo 8:1 || exit 1 ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "dmsetup",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                case "$1" in
                info) printf '%s\n' "${MOCK_DM_UUID:-SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef}" ;;
                table) printf '0 216641536 swapz 8:1 0 64 0 2 0 1 0 0\n' ;;
                status)
                    if [ "${MOCK_DM_STATUS_SLEEP:-0}" != 0 ]; then sleep "$MOCK_DM_STATUS_SLEEP"; fi
                    if [ "${MOCK_DM_STATUS_UNAVAILABLE:-0}" = 1 ]; then exit 1; fi
                    if [ -n "${MOCK_DM_STALL_COUNTER_FILE:-}" ]; then
                        counter=0
                        if [ -f "$MOCK_DM_STALL_COUNTER_FILE" ]; then
                            IFS= read -r counter < "$MOCK_DM_STALL_COUNTER_FILE" || exit 2
                        fi
                        counter=$((counter + 1))
                        printf '%s\n' "$counter" > "$MOCK_DM_STALL_COUNTER_FILE" || exit 2
                        printf '0 216641536 swapz failed=0 error=0 flush_err=0 segment_discards_failed=0 upper_write_completed_err=0 endio_write_seen_err=0 endio_write_forced_err=0 gc_victims=5 gc_pages=20 gc_no_headroom_skips=%s gc_reserve_segments_initial=2 gc_reserve_segments_current=2 gc_destination_advances=0 window_gc_pressure=%s\n' "$counter" "$counter"
                        exit 0
                    fi
                    printf '%s\n' "${MOCK_DM_STATUS:-0 216641536 swapz failed=0 error=0 flush_err=0 segment_discards_failed=0 upper_write_completed_err=0 endio_write_seen_err=0 endio_write_forced_err=0 gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 gc_reserve_segments_initial=2 gc_reserve_segments_current=2 gc_destination_advances=0 window_gc_pressure=0}"
                    ;;
                *) exit 2 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "systemctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                property=
                for argument in "$@"; do
                    case "$argument" in --property=*) property=${argument#--property=} ;; esac
                done
                case "$property" in
                LoadState) echo "${MOCK_SYSTEMD_LOAD_STATE:-loaded}" ;;
                ActiveState) echo "${MOCK_SYSTEMD_ACTIVE_STATE:-active}" ;;
                SubState) echo running ;;
                Result) echo success ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        write_executable(
            self.bin / "journalctl",
            "#!/bin/sh\nprintf '%s' \"${MOCK_JOURNAL:-}\"\n",
        )
        write_executable(
            self.bin / "blkid",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$1" = -o ] && [ "$2" = device ] && [ "$3" = -t ] || exit 2
                [ "$4" = UUID=target ] || exit 1
                printf '%s/uuid-target\n' "$SWAPZ_PRIMARY_TEST_DEV_ROOT"
                """
            ),
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{self.bin}:{self.env['PATH']}",
                "SWAPZ_PRIMARY_SYSTEMD_TESTING": "1",
                "SWAPZ_PRIMARY_TEST_PATH": f"{self.bin}:/usr/sbin:/usr/bin:/sbin:/bin",
                "SWAPZ_PRIMARY_TEST_COMMAND_TIMEOUT_SECONDS": "2",
                "SWAPZ_PRIMARY_TEST_PROC_ROOT": str(self.proc),
                "SWAPZ_PRIMARY_TEST_SYS_ROOT": str(self.sys),
                "SWAPZ_PRIMARY_TEST_DEV_ROOT": str(self.dev),
                "SWAPZ_PRIMARY_TEST_ETC_ROOT": str(self.etc),
                "SWAPZ_PRIMARY_TEST_RECOVERY_BASE": str(self.recovery),
                "SWAPZ_PRIMARY_TEST_POLL_SECONDS": "0",
                "SWAPZ_PRIMARY_TEST_MAX_POLLS": "1",
                "SWAPZ_PRIMARY_TEST_STALL_POLLS": "3",
            }
        )
        self.helper = self.sbin / "swapz-primary-runtime-health"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_helper(
        self,
        action: str,
        env: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.helper), action],
            check=False,
            text=True,
            capture_output=True,
            env=env or self.env,
            timeout=timeout,
        )

    def test_healthy_snapshot_reports_capacity_and_identity(self) -> None:
        result = self.run_helper("once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", result.stderr)
        self.assertIn("swap_remaining_kib=", result.stderr)
        self.assertIn(f"mapper_uuid=SWAPZ-PRIMARY-{ACTIVE_RUN_ID}", result.stderr)

    def test_backing_device_disappearance_is_failure_not_degraded(self) -> None:
        selected = self.dev / "disk" / "by-partuuid" / PARTUUID
        selected.unlink()
        result = self.run_helper("once")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", result.stderr)
        self.assertIn("backing_device_unavailable", result.stderr)
        self.assertNotIn("selected_target_identity_unavailable", result.stderr)

    def test_foreign_mapper_is_failure_but_monitor_keeps_observing(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_UUID"] = "SWAPZ-PRIMARY-" + "f" * 32
        once = self.run_helper("once", env)
        self.assertEqual(once.returncode, 1)
        self.assertIn("mapper_uuid_not_bound_to_active_run", once.stderr)
        monitor = self.run_helper("monitor", env)
        self.assertEqual(monitor.returncode, 0)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", monitor.stderr)

    def test_reserve_role_erosion_is_observable_and_exhaustion_fails(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS"] = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=1 "
            "gc_destination_advances=1 window_gc_pressure=1"
        )
        degraded = self.run_helper("once", env)
        self.assertEqual(degraded.returncode, 0, degraded.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=WARN", degraded.stderr)
        self.assertIn("gc_reserve_degraded", degraded.stderr)
        self.assertIn("gc_reserve_segments_current=1", degraded.stderr)
        self.assertIn("gc_destination_advances=1", degraded.stderr)

        env["MOCK_DM_STATUS"] = env["MOCK_DM_STATUS"].replace(
            "gc_reserve_segments_current=1", "gc_reserve_segments_current=0"
        )
        exhausted = self.run_helper("once", env)
        self.assertEqual(exhausted.returncode, 1, exhausted.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", exhausted.stderr)
        self.assertIn("gc_reserve_exhausted", exhausted.stderr)

    def test_missing_reserve_role_telemetry_is_degraded(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS"] = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "window_gc_pressure=0"
        )
        result = self.run_helper("once", env)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
        self.assertIn("gc_reserve_telemetry_unavailable", result.stderr)

    def test_monitoring_error_is_degraded_not_a_destructive_action(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS_UNAVAILABLE"] = "1"
        result = self.run_helper("once", env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
        self.assertIn("mapper_status_unavailable", result.stderr)

    def test_sustained_gc_stall_requires_normal_operator_stop(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STALL_COUNTER_FILE"] = str(self.root / "gc-stall-counter")
        env["SWAPZ_PRIMARY_TEST_MAX_POLLS"] = "4"
        env["SWAPZ_PRIMARY_TEST_STALL_POLLS"] = "3"
        result = self.run_helper("monitor", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", result.stderr)
        self.assertIn("failures=sustained_gc_stall", result.stderr)
        marker = (
            "SWAPZ_RUNTIME_STOP_REQUIRED=1 reason=sustained_gc_stall "
            "action=normal_primary_stop_required"
        )
        self.assertEqual(result.stderr.count(marker), 1)
        helper = read_text(RUNTIME_HEALTH)
        self.assertNotIn("swapzctl primary stop", helper)
        self.assertNotRegex(helper, r"(^|[^A-Za-z])swapoff([^A-Za-z]|$)")
        self.assertNotIn("dmsetup remove", helper)

    def test_unchanged_monitor_state_logs_only_once(self) -> None:
        env = self.env.copy()
        env["SWAPZ_PRIMARY_TEST_MAX_POLLS"] = "2"
        result = self.run_helper("monitor", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("SWAPZ_RUNTIME_HEALTH="), 1)

    def test_resume_configuration_and_hibernation_guard_fail_closed(self) -> None:
        (self.proc / "cmdline").write_text(
            "quiet resume=/dev/mapper/swapz-primary\n", encoding="ascii"
        )
        configured = self.run_helper("hibernation-config-check")
        self.assertEqual(configured.returncode, 1)
        self.assertIn("unsupported hibernation/resume target", configured.stderr)
        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        config_dir = self.etc / "initramfs-tools" / "conf.d"
        config_dir.mkdir(parents=True)
        (config_dir / "resume").write_text("RESUME=auto\n", encoding="ascii")
        self.assertNotEqual(self.run_helper("hibernation-config-check").returncode, 0)
        (config_dir / "resume").unlink()
        guard = self.run_helper("hibernate-guard")
        self.assertEqual(guard.returncode, 1)
        self.assertIn("hibernation is unsupported", guard.stderr)

    def test_uuid_resume_alias_and_stop_diagnostic_are_read_only(self) -> None:
        (self.proc / "cmdline").write_text("quiet resume=UUID=target\n", encoding="ascii")
        configured = self.run_helper("hibernation-config-check")
        self.assertEqual(configured.returncode, 1)
        stop = self.run_helper("stop-observe")
        self.assertEqual(stop.returncode, 1)
        self.assertIn("action=none", stop.stderr)



    def test_tab_delimited_swap_inventory_tracks_real_occupancy(self) -> None:
        # /proc/swaps uses tab-separated fields and may omit name padding
        # when the source pathname is long.
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'}\tpartition\t10000\t2000\t-1\n",
            encoding="ascii",
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", observed.stderr)
        self.assertIn("swap_used_kib=2000", observed.stderr)
        self.assertIn("swap_remaining_kib=8000", observed.stderr)
        self.assertEqual(self.run_helper("hibernate-guard").returncode, 1)

    def test_malformed_swap_inventory_degrades_runtime_observation(self) -> None:
        for content in (
            "",
            "garbled swap inventory\n",
            "Filename\tType\tSize\tUsed\tPriority\n"
            "/dev/mapper/swapz-primary\tpartition\tbad-size\t1\t-1\n",
        ):
            (self.proc / "swaps").write_text(content, encoding="ascii")
            observed = self.run_helper("once")
            self.assertEqual(observed.returncode, 2, (content, observed.stderr))
            self.assertIn("swap_inventory_unavailable_or_invalid", observed.stderr)

        (self.proc / "swaps").unlink()
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 2, observed.stderr)

    def test_malformed_swap_inventory_never_proves_hibernation_safe(self) -> None:
        (self.etc / "swapz" / "primary-target").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        for content in (
            "",
            "garbled swap inventory\n",
            "Filename\tType\tSize\tUsed\tPriority\n"
            "/dev/mapper/swapz-primary\tpartition\tbad-size\t1\t-1\n",
        ):
            (self.proc / "swaps").write_text(content, encoding="ascii")
            guard = self.run_helper("hibernate-guard")
            self.assertEqual(guard.returncode, 1, (content, guard.stderr))
            self.assertIn("cannot prove swapz-primary inactive", guard.stderr)

        (self.proc / "swaps").unlink()
        guard = self.run_helper("hibernate-guard")
        self.assertEqual(guard.returncode, 1, guard.stderr)
        self.assertIn("cannot prove swapz-primary inactive", guard.stderr)

    def test_configured_primary_target_blocks_hibernate_even_when_inactive(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="ascii"
        )
        blocked = self.run_helper("hibernate-guard")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("target is configured", blocked.stderr)

    def test_unconfigured_inactive_swapz_does_not_disable_unrelated_hibernate(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="ascii"
        )
        (self.etc / "swapz" / "primary-target").unlink()
        (self.dev / "mapper" / "swapz-primary").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        allowed = self.run_helper("hibernate-guard")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_unconfigured_ambiguous_live_block_swap_refuses_hibernate(self) -> None:
        # A valid inventory row is insufficient if its block identity cannot
        # be resolved. In particular, do not mistake a vanished DM alias for
        # proof that there are no live swapz pages.
        (self.etc / "swapz" / "primary-target").unlink()
        (self.dev / "mapper" / "swapz-primary").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n"
            "/dev/dm-unresolvable\tpartition\t10000\t2000\t-1\n",
            encoding="ascii",
        )
        blocked = self.run_helper("hibernate-guard")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("cannot prove swapz-primary inactive", blocked.stderr)

    def test_unresolved_resume_alias_blocks_when_selected_media_is_absent(self) -> None:
        (self.dev / "disk" / "by-partuuid" / PARTUUID).unlink()

        (self.proc / "cmdline").write_text(
            "quiet resume=/dev/disk/by-id/missing-resume\n", encoding="ascii"
        )
        unresolved_path = self.run_helper("hibernation-config-check")
        self.assertEqual(unresolved_path.returncode, 1, unresolved_path.stderr)
        self.assertIn("unresolved:/dev/disk/by-id/missing-resume", unresolved_path.stderr)

        (self.proc / "cmdline").write_text(
            "quiet resume=UUID=missing\n", encoding="ascii"
        )
        unresolved_uuid = self.run_helper("hibernation-config-check")
        self.assertEqual(unresolved_uuid.returncode, 1, unresolved_uuid.stderr)
        self.assertIn("unresolved:UUID=missing", unresolved_uuid.stderr)

        (self.proc / "cmdline").write_text(
            f"quiet resume=PARTUUID={OTHER_PARTUUID}\n", encoding="ascii"
        )
        distinct_partuuid = self.run_helper("hibernation-config-check")
        self.assertEqual(distinct_partuuid.returncode, 0, distinct_partuuid.stderr)

    def test_activation_guard_serializes_against_hibernation_units(self) -> None:
        blocked = self.run_helper("activation-guard")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("systemd-hibernate.service state is active", blocked.stderr)

        env = self.env.copy()
        env["MOCK_SYSTEMD_ACTIVE_STATE"] = "inactive"
        allowed = self.run_helper("activation-guard", env)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        env["MOCK_SYSTEMD_LOAD_STATE"] = "not-found"
        absent_units = self.run_helper("activation-guard", env)
        self.assertEqual(absent_units.returncode, 0, absent_units.stderr)

    def test_external_status_probe_is_time_bounded(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS_SLEEP"] = "2"
        env["SWAPZ_PRIMARY_TEST_COMMAND_TIMEOUT_SECONDS"] = "1"
        observed = self.run_helper("once", env, timeout=5)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("mapper_status_unavailable", observed.stderr)

    def test_unreadable_kernel_cmdline_blocks_resume_admission(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="ascii"
        )
        (self.proc / "cmdline").unlink()
        configured = self.run_helper("hibernation-config-check")
        self.assertEqual(configured.returncode, 1)
        self.assertIn("kernel-cmdline:unavailable", configured.stderr)
        self.assertEqual(self.run_helper("hibernate-guard").returncode, 1)

    def test_live_mapper_without_selected_authority_is_failure(self) -> None:
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("selected_target_identity_unavailable", observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)

    def test_kernel_error_tail_is_bounded_and_case_insensitive(self) -> None:
        write_executable(
            self.bin / "journalctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                bounded=0
                for argument do
                    [ "$argument" != --lines=256 ] || bounded=1
                done
                [ "$bounded" -eq 1 ] || exit 2
                printf 'DM-SWAPZ: lower I/O error\n'
                """
            ),
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=WARN", observed.stderr)
        self.assertIn("relevant_kernel_errors", observed.stderr)
        self.assertIn("kernel_error_count=1", observed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
