#!/usr/bin/env python3
"""Rootless regression fixture for swapz primary systemd packaging.

The official rootless stage invokes this fixture. It never invokes swapon,
swapoff, a real mapper, or reboot.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import shutil
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PRIMARY_MANAGER_SOURCE = REPO_ROOT / "src" / "userspace" / "swapz-primary.c"
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
                [ "${#partuuid}" -ge 8 ] && [ "${#partuuid}" -le 64 ] || exit 2
                printf '%s\n' "$partuuid" | grep -Eq '^[0-9a-f]+(-[0-9a-f]+)*$' || exit 2
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
            # Eight decoded characters do not imply eight hexadecimal digits.
            "dev-disk-by\\x2dpartuuid-1234\\x2d567.device dev-disk-by\\x2dpartuuid-1234\\x2d567.swap\n",
            # A manager response with duplicated or edge hyphens is invalid.
            "dev-disk-by\\x2dpartuuid-12345678\\x2d\\x2d90.device dev-disk-by\\x2dpartuuid-12345678\\x2d\\x2d90.swap\n",
            "dev-disk-by\\x2dpartuuid-\\x2d12345678.device dev-disk-by\\x2dpartuuid-\\x2d12345678.swap\n",
            "dev-disk-by\\x2dpartuuid-12345678\\x2d.device dev-disk-by\\x2dpartuuid-12345678\\x2d.swap\n",
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
        self.assertIn("RuntimeDirectory=swapz", service)
        self.assertIn("RuntimeDirectoryMode=0700", service)
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


class UnitSandboxContractTests(unittest.TestCase):
    """Static parser regression for sandbox and ownership-sensitive unit drift."""

    @staticmethod
    def directives(contents: str) -> dict[tuple[str, str], tuple[str, ...]]:
        parsed: dict[tuple[str, str], list[str]] = {}
        section = ""
        for original_line in contents.splitlines():
            line = original_line.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if not section or "=" not in line:
                raise ValueError(f"invalid unit directive: {line}")
            key, value = line.split("=", 1)
            parsed.setdefault((section, key), []).append(value)
        return {key: tuple(values) for key, values in parsed.items()}

    def assert_secure_units(
        self, *, mapper: str, verifier: str, health: str, passive_swap: str
    ) -> None:
        files = {
            "mapper": self.directives(mapper),
            "verifier": self.directives(verifier),
            "health": self.directives(health),
            "passive_swap": self.directives(passive_swap),
        }

        def require(unit: str, section: str, directive: str, value: str) -> None:
            self.assertEqual(
                files[unit].get((section, directive)),
                (value,),
                f"{unit}: {section}.{directive}",
            )

        require("mapper", "Unit", "DefaultDependencies", "no")
        require("mapper", "Unit", "Requires", "-.mount")
        require("mapper", "Unit", "RequiresMountsFor", "/var/lib/swapz/physical-recovery")
        require(
            "mapper", "Unit", "After",
            r"-.mount systemd-modules-load.service dev-mapper-swapz\x2dprimary.swap",
        )
        require("mapper", "Unit", "Before", "swap.target shutdown.target")
        require("mapper", "Unit", "Conflicts", "shutdown.target")
        require("mapper", "Unit", "RefuseManualStart", "yes")
        require("mapper", "Unit", "RefuseManualStop", "yes")
        require("mapper", "Service", "Type", "oneshot")
        require("mapper", "Service", "RemainAfterExit", "yes")
        require("mapper", "Service", "TimeoutStartSec", "120s")
        require("mapper", "Service", "TimeoutStopSec", "120s")
        require("mapper", "Service", "RuntimeDirectory", "swapz")
        require("mapper", "Service", "RuntimeDirectoryMode", "0700")
        require("mapper", "Install", "WantedBy", "swap.target")
        # The lifecycle needs CAP_SYS_ADMIN (DM/swapon/swapoff),
        # CAP_SYS_MODULE (finit_module/delete_module), and CAP_SYS_PTRACE so
        # hidepid cannot conceal another process's mount namespace inventory.
        require(
            "mapper", "Service", "CapabilityBoundingSet",
            "~CAP_NET_ADMIN CAP_NET_RAW CAP_NET_BIND_SERVICE "
            "CAP_SYS_BOOT CAP_SYS_TIME CAP_SYSLOG CAP_MAC_ADMIN "
            "CAP_MAC_OVERRIDE CAP_BPF CAP_PERFMON CAP_CHECKPOINT_RESTORE",
        )
        # ReadOnlyPaths binds would change the journal mount ID, which the
        # native manager deliberately checks against its parent.
        self.assertNotIn(("Service", "ReadOnlyPaths"), files["mapper"])
        for directive, value in (
            ("NoNewPrivileges", "yes"),
            ("ProtectSystem", "full"),
            ("ProtectHome", "yes"),
            ("LockPersonality", "yes"),
            ("RestrictRealtime", "yes"),
            ("RestrictSUIDSGID", "yes"),
            ("SystemCallArchitectures", "native"),
            ("SystemCallFilter", "~@mount"),
            ("SystemCallErrorNumber", "EPERM"),
        ):
            require("mapper", "Service", directive, value)
        self.assertNotIn(("Service", "ProtectKernelModules"), files["mapper"])
        self.assertNotIn(("Service", "PrivateDevices"), files["mapper"])
        # tmp.mount can be ordered after swap.target; early PrivateTmp would
        # introduce a boot cycle even when the rest of the sandbox is valid.
        self.assertNotIn(("Service", "PrivateTmp"), files["mapper"])

        for unit in ("verifier", "health"):
            require(unit, "Service", "NoNewPrivileges", "yes")
            # DM status ioctls can require CAP_SYS_ADMIN; neither observer
            # receives the mapper's CAP_SYS_MODULE.
            require(unit, "Service", "CapabilityBoundingSet", "CAP_SYS_ADMIN")
            require(unit, "Service", "ProtectHome", "yes")
            require(unit, "Service", "PrivateTmp", "yes")
            require(unit, "Service", "RestrictRealtime", "yes")
            require(unit, "Service", "LockPersonality", "yes")
            require(unit, "Service", "SystemCallArchitectures", "native")
            require(unit, "Service", "SystemCallErrorNumber", "EPERM")
            self.assertNotIn(("Unit", "Wants"), files[unit])
            self.assertNotIn(("Unit", "Requires"), files[unit])
        require(
            "verifier", "Unit", "After",
            r"swapz-primary-mapper.service dev-mapper-swapz\x2dprimary.swap",
        )
        require("verifier", "Service", "ProtectSystem", "full")
        require("verifier", "Service", "SystemCallFilter", "~@mount @module @swap")
        # The verifier authenticates /lib/modules, so ProtectKernelModules
        # would hide required evidence. Module mutation is blocked by both the
        # capability boundary and the @module syscall deny-list.
        self.assertNotIn(("Service", "ProtectKernelModules"), files["verifier"])
        # The read-only probe must not introduce bind mounts that appear as
        # forged recovery storage or package-journal mount substitution.
        self.assertNotIn(("Service", "ReadOnlyPaths"), files["verifier"])
        require("verifier", "Service", "TimeoutStartSec", "30s")
        require("verifier", "Install", "WantedBy", "multi-user.target")
        require("health", "Service", "ProtectSystem", "strict")
        require("health", "Service", "ProtectKernelModules", "yes")
        require("health", "Service", "SystemCallFilter", "~@mount @swap")
        require("health", "Service", "Restart", "on-failure")
        require("health", "Service", "TimeoutStopSec", "10s")
        require("health", "Unit", "ConditionPathExists", "/dev/mapper/swapz-primary")
        require("health", "Install", "WantedBy", "swap.target")

        require("passive_swap", "Unit", "RefuseManualStart", "yes")
        require("passive_swap", "Unit", "RefuseManualStop", "yes")
        require("passive_swap", "Swap", "What", "/dev/mapper/swapz-primary")
        for section in ("Unit", "Install"):
            for directive in ("Alias", "WantedBy", "RequiredBy", "Also"):
                self.assertNotIn((section, directive), files["passive_swap"])

    def test_units_enforce_sandbox_and_passive_ordering(self) -> None:
        self.assert_secure_units(
            mapper=read_text(MAPPER_SERVICE),
            verifier=read_text(BOOT_VERIFY_SERVICE),
            health=read_text(RUNTIME_HEALTH_SERVICE),
            passive_swap=read_text(PRIMARY_SWAP),
        )

    def test_observer_claim_path_is_not_native_activation_authority(self) -> None:
        primary_manager = read_text(PRIMARY_MANAGER_SOURCE)
        verifier_helper = read_text(BOOT_VERIFY)

        # The native gate accepts exactly the canonical record name and mode.
        # The observer's claimed file is deliberately outside that namespace,
        # so retaining it after a cleanup fault cannot authorize another start.
        self.assertIn(
            '#define SWAPZ_PRIMARY_EXECUTION_RECORD_NAME "primary-execution.env"',
            primary_manager,
        )
        self.assertIn(
            "openat(directory_fd, SWAPZ_PRIMARY_EXECUTION_RECORD_NAME",
            primary_manager,
        )
        self.assertIn("(before.st_mode & 0777U) != 0600U", primary_manager)
        self.assertNotIn(".primary-execution.observed.env", primary_manager)
        self.assertIn(
            "runtime_consumed_file=$runtime_base/.primary-execution.observed.env",
            verifier_helper,
        )

    def test_sandbox_matches_native_visibility_and_module_evidence(self) -> None:
        primary_manager = read_text(PRIMARY_MANAGER_SOURCE)
        verifier_helper = read_text(BOOT_VERIFY)
        mapper = self.directives(read_text(MAPPER_SERVICE))
        verifier = self.directives(read_text(BOOT_VERIFY_SERVICE))

        # The native manager deliberately audits every visible process mount
        # namespace, so CAP_SYS_PTRACE must remain outside the exclusion mask.
        self.assertIn('"/proc/%s/mountinfo"', primary_manager)
        mapper_bound = mapper[("Service", "CapabilityBoundingSet")][0]
        self.assertTrue(mapper_bound.startswith("~"))
        excluded_capabilities = set(mapper_bound[1:].split())
        self.assertNotIn("CAP_SYS_PTRACE", excluded_capabilities)

        # Mapper lifecycle owns module load/unload and swap activation; observers must not.
        self.assertIn("SYS_finit_module", primary_manager)
        self.assertIn("SYS_delete_module", primary_manager)
        self.assertIn("SYS_swapon", primary_manager)
        self.assertIn("SYS_swapoff", primary_manager)
        self.assertNotIn("CAP_SYS_MODULE", excluded_capabilities)
        self.assertNotIn(
            "@swap", mapper[("Service", "SystemCallFilter")][0].split()
        )

        # Cold-boot observation authenticates the installed module image.
        # Keep that path readable while denying module and swap mutation by syscall.
        self.assertIn(
            "installed_image=/lib/modules/$installed_kernel_release/"
            "updates/dkms/dm-swapz.ko",
            verifier_helper,
        )
        self.assertNotIn(("Service", "ProtectKernelModules"), verifier)
        self.assertEqual(
            verifier[("Service", "SystemCallFilter")],
            ("~@mount @module @swap",),
        )

    def test_unit_drift_is_rejected_without_systemd_or_root(self) -> None:
        original = {
            "mapper": read_text(MAPPER_SERVICE),
            "verifier": read_text(BOOT_VERIFY_SERVICE),
            "health": read_text(RUNTIME_HEALTH_SERVICE),
            "passive_swap": read_text(PRIMARY_SWAP),
        }
        mutations = (
            ("missing recovery mount", "mapper", "RequiresMountsFor=/var/lib/swapz/physical-recovery", "RequiresMountsFor="),
            ("lost root ordering", "mapper", "After=-.mount", "After=systemd-modules-load.service"),
            ("lost stop ordering", "mapper", "Before=swap.target shutdown.target", "Before=shutdown.target"),
            ("unbounded startup", "mapper", "TimeoutStartSec=120s", "TimeoutStartSec=infinity"),
            ("unbounded stop", "mapper", "TimeoutStopSec=120s", "TimeoutStopSec=infinity"),
            ("privilege escalation", "mapper", "NoNewPrivileges=yes", "NoNewPrivileges=no"),
            ("module capability excluded", "mapper", "CAP_NET_RAW", "CAP_SYS_MODULE"),
            ("cross-process visibility excluded", "mapper", "CAP_SYS_BOOT", "CAP_SYS_PTRACE CAP_SYS_BOOT"),
            ("module loading disabled", "mapper", "ProtectSystem=full", "ProtectKernelModules=yes"),
            ("mapper mount namespace mutable", "mapper", "SystemCallFilter=~@mount", "SystemCallFilter="),
            ("early tmp.mount ordering cycle", "mapper", "ProtectHome=yes", "ProtectHome=yes\nPrivateTmp=yes"),
            ("unprotected filesystem", "mapper", "ProtectSystem=full", "ProtectSystem=no"),
            ("journal mount substitution", "mapper", "ProtectSystem=full", "ProtectSystem=full\nReadOnlyPaths=-/var/lib/swapz-package-transactions"),
            ("verifier starts mapper", "verifier", "After=swapz-primary-mapper.service", "Wants=swapz-primary-mapper.service\nAfter=swapz-primary-mapper.service"),
            ("verifier recovery mount substitution", "verifier", "ProtectSystem=full", "ProtectSystem=full\nReadOnlyPaths=-/var/lib/swapz/physical-recovery"),
            ("verifier module evidence hidden", "verifier", "ProtectControlGroups=yes", "ProtectControlGroups=yes\nProtectKernelModules=yes"),
            ("verifier can load modules", "verifier", "CapabilityBoundingSet=CAP_SYS_ADMIN", "CapabilityBoundingSet=CAP_SYS_ADMIN CAP_SYS_MODULE"),
            ("verifier module syscall allowed", "verifier", "SystemCallFilter=~@mount @module @swap", "SystemCallFilter=~@mount @swap"),
            ("verifier swap syscall allowed", "verifier", "SystemCallFilter=~@mount @module @swap", "SystemCallFilter=~@mount @module"),
            ("health can load modules", "health", "CapabilityBoundingSet=CAP_SYS_ADMIN", "CapabilityBoundingSet=CAP_SYS_ADMIN CAP_SYS_MODULE"),
            ("health mount namespace mutable", "health", "SystemCallFilter=~@mount @swap", "SystemCallFilter=~@swap"),
            ("health swap syscall allowed", "health", "SystemCallFilter=~@mount @swap", "SystemCallFilter=~@mount"),
            ("health can edit filesystem", "health", "ProtectSystem=strict", "ProtectSystem=full"),
            ("health starts mapper", "health", "After=swapz-primary-mapper.service", "Requires=swapz-primary-mapper.service\nAfter=swapz-primary-mapper.service"),
            ("passive swap enabled", "passive_swap", "TimeoutSec=120s", "TimeoutSec=120s\n\n[Install]\nWantedBy=swap.target"),
            ("raw swap alias", "passive_swap", "TimeoutSec=120s", "TimeoutSec=120s\n\n[Install]\nAlias=dev-disk-by-partuuid-unsafe.swap"),
        )
        for name, file_key, old, new in mutations:
            with self.subTest(name=name):
                self.assertIn(old, original[file_key])
                changed = original.copy()
                changed[file_key] = original[file_key].replace(old, new, 1)
                with self.assertRaises(AssertionError, msg=name):
                    self.assert_secure_units(**changed)



class EffectiveUnitContractTests(unittest.TestCase):
    """Rootless model of effective systemd unit and drop-in security.

    Scalar settings are last-wins. Exec/filter/install lists honor their
    documented empty-assignment reset behavior. Unit dependency directives,
    including RequiresMountsFor= path dependencies, are additive in drop-ins:
    an empty assignment is a no-op and cannot remove the vendor edge.
    """

    ADDITIVE_UNIT_KEYS = frozenset(
        ("Unit", key)
        for key in (
            "After", "Before", "Requires", "RequiresMountsFor",
            "Wants", "WantsMountsFor", "Conflicts", "BindsTo", "PartOf",
            "Requisite", "OnFailure", "OnSuccess", "Upholds",
            "PropagatesReloadTo", "ReloadPropagatedFrom",
            "PropagatesStopTo", "StopPropagatedFrom", "JoinsNamespaceOf",
        )
    )
    INSTALL_LIST_KEYS = frozenset(
        ("Install", key)
        for key in ("WantedBy", "RequiredBy", "UpheldBy", "Alias", "Also")
    )
    COMMAND_KEYS = frozenset(
        ("Service", key) for key in (
            "ExecCondition", "ExecStartPre", "ExecStart", "ExecStartPost",
            "ExecStop", "ExecStopPost", "ExecReload",
        )
    )
    FILTER_KEYS = frozenset((
        ("Service", "CapabilityBoundingSet"),
        ("Service", "SystemCallFilter"),
    ))
    UNIT_PATHS = {
        "mapper": ("swapz-primary-mapper.service", MAPPER_SERVICE),
        "verifier": ("swapz-primary-boot-verify.service", BOOT_VERIFY_SERVICE),
        "health": ("swapz-primary-runtime-health.service", RUNTIME_HEALTH_SERVICE),
        "passive_swap": (r"dev-mapper-swapz\x2dprimary.swap", PRIMARY_SWAP),
    }
    SOURCE_PRIORITIES = {"generator": 0, "admin": 1}

    @classmethod
    def matching_dropin_scopes(cls, unit_filename: str) -> tuple[str, ...]:
        stem, unit_type = unit_filename.rsplit(".", 1)
        scopes = [f"{unit_type}.d"]
        for index, character in enumerate(stem):
            if character == "-":
                scopes.append(f"{stem[:index + 1]}.{unit_type}.d")
        scopes.append(f"{unit_filename}.d")
        # A malformed name could otherwise produce duplicate scope entries.
        return tuple(dict.fromkeys(scopes))

    @classmethod
    def resolve_dropins(
        cls,
        unit_filename: str,
        sources: dict[str, dict[str, dict[str, str]]],
    ) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
        scope_priority = {
            scope: index
            for index, scope in enumerate(cls.matching_dropin_scopes(unit_filename))
        }
        candidates: dict[str, list[tuple[int, int, str, str, str]]] = {}
        for source_name, scoped_fragments in sources.items():
            source_priority = cls.SOURCE_PRIORITIES[source_name]
            for scope, fragments in scoped_fragments.items():
                if scope not in scope_priority:
                    continue
                for filename, contents in fragments.items():
                    if not filename.endswith(".conf"):
                        continue
                    origin = f"{source_name}:{scope}/{filename}"
                    candidates.setdefault(filename, []).append(
                        (
                            scope_priority[scope],
                            source_priority,
                            source_name,
                            origin,
                            contents,
                        )
                    )

        selected: list[tuple[str, str, str]] = []
        shadowed_authorized: list[str] = []
        for filename, same_name_candidates in candidates.items():
            winner = max(
                same_name_candidates,
                key=lambda candidate: (candidate[0], candidate[1]),
            )
            selected.append((filename, winner[3], winner[4]))
            if winner[2] == "admin" and any(
                candidate[2] == "generator"
                for candidate in same_name_candidates
                if candidate is not winner
            ):
                shadowed_authorized.append(winner[3])

        selected.sort(key=lambda fragment: fragment[0])
        return (
            tuple((origin, contents) for _, origin, contents in selected),
            tuple(sorted(shadowed_authorized)),
        )

    @classmethod
    def merged_directives(
        cls,
        base: str,
        dropins: tuple[tuple[str, str], ...],
        *,
        base_origin: str = "vendor unit",
    ) -> tuple[dict[tuple[str, str], tuple[str, ...]], dict[tuple[str, str], str]]:
        values: dict[tuple[str, str], list[str]] = {}
        origins: dict[tuple[str, str], str] = {}
        for filename, contents in ((base_origin, base), *dropins):
            section = ""
            for original_line in contents.splitlines():
                line = original_line.strip()
                if not line or line.startswith(("#", ";")):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                    continue
                # Fixture assumption: one assignment per line. Fail closed on
                # line continuations rather than claiming to model them.
                if not section or "=" not in line or line.endswith("\\"):
                    raise ValueError(f"invalid effective unit fragment in {filename}")
                directive, value = line.split("=", 1)
                directive = directive.strip()
                value = value.strip()
                if not directive:
                    raise ValueError(f"invalid effective unit fragment in {filename}")
                key = (section, directive)
                origin = f"{filename}: {directive}={value}"

                if key in cls.ADDITIVE_UNIT_KEYS:
                    # systemd dependency entries cannot be removed by an
                    # empty drop-in assignment; only whole-unit replacement
                    # can discard dependencies from the main unit.
                    if not value:
                        continue
                    entries = values.setdefault(key, [])
                    changed = False
                    for item in value.split():
                        if item not in entries:
                            entries.append(item)
                            changed = True
                    if changed:
                        origins[key] = origin
                    continue

                if key in cls.INSTALL_LIST_KEYS:
                    if not value:
                        values[key] = []
                    else:
                        entries = values.setdefault(key, [])
                        for item in value.split():
                            if item not in entries:
                                entries.append(item)
                    origins[key] = origin
                    continue

                if key in cls.COMMAND_KEYS or key in cls.FILTER_KEYS:
                    if not value:
                        values[key] = []
                    else:
                        values.setdefault(key, []).append(value)
                    origins[key] = origin
                    continue

                values[key] = [value]
                origins[key] = origin
        return {key: tuple(value) for key, value in values.items()}, origins

    @staticmethod
    def authorized_dropins() -> tuple[dict[str, dict[str, str]], str, str]:
        encoded = PARTUUID.replace("-", r"\x2d")
        selected_device = f"dev-disk-by\\x2dpartuuid-{encoded}.device"
        selected_swap = f"dev-disk-by\\x2dpartuuid-{encoded}.swap"
        return (
            {
                "mapper": {
                    "50-selected-target.conf": (
                        "[Unit]\n"
                        f"Requires={selected_device}\nAfter={selected_device}\n"
                        f"Conflicts={selected_swap}\nBefore={selected_swap}\n"
                        "JobTimeoutSec=300s\nJobTimeoutAction=none\n"
                    ),
                },
                "device": {
                    "50-swapz-timeout.conf": (
                        "[Unit]\nJobTimeoutSec=30s\nJobTimeoutAction=none\n"
                    ),
                },
            },
            selected_device,
            selected_swap,
        )

    def dropin_sources(
        self,
        extra: dict[str, dict[str, str]] | None,
        shared_extra: dict[str, dict[str, str]] | None,
    ) -> tuple[dict[str, dict[str, dict[str, str]]], str, str]:
        authorized, selected_device, selected_swap = self.authorized_dropins()
        unit_filenames = {
            unit: filename for unit, (filename, _) in self.UNIT_PATHS.items()
        }
        unit_filenames["device"] = selected_device

        generator: dict[str, dict[str, str]] = {}
        for unit, fragments in authorized.items():
            generator[f"{unit_filenames[unit]}.d"] = dict(fragments)

        admin = {
            scope: dict(fragments)
            for scope, fragments in (shared_extra or {}).items()
        }
        for unit, fragments in (extra or {}).items():
            scope = f"{unit_filenames[unit]}.d"
            admin.setdefault(scope, {}).update(fragments)

        return {"generator": generator, "admin": admin}, selected_device, selected_swap

    def effective_fixture(
        self,
        extra: dict[str, dict[str, str]] | None = None,
        *,
        shared_extra: dict[str, dict[str, str]] | None = None,
        base_overrides: dict[str, str] | None = None,
    ) -> tuple[
        dict[str, dict[tuple[str, str], tuple[str, ...]]],
        dict[str, dict[tuple[str, str], str]],
        dict[str, tuple[str, ...]],
    ]:
        sources, selected_device, _ = self.dropin_sources(extra, shared_extra)
        effective = {}
        origins = {}
        shadows = {}
        base_overrides = base_overrides or {}

        for unit, (filename, path) in self.UNIT_PATHS.items():
            fragments, shadows[unit] = self.resolve_dropins(filename, sources)
            base_origin = "admin unit override" if unit in base_overrides else "vendor unit"
            effective[unit], origins[unit] = self.merged_directives(
                base_overrides.get(unit, read_text(path)),
                fragments,
                base_origin=base_origin,
            )

        fragments, shadows["device"] = self.resolve_dropins(
            selected_device, sources
        )
        # udev synthesizes the .device unit; only its generator/admin drop-ins
        # participate in this fixture.
        effective["device"], origins["device"] = self.merged_directives(
            "", fragments
        )
        return effective, origins, shadows

    @classmethod
    def safety_consequence(
        cls, unit: str, key: tuple[str, str]
    ) -> str:
        section, directive = key
        if unit == "passive_swap" and section == "Install":
            return "passive swap may become independently enabled and issue a second swapon"
        if key in cls.COMMAND_KEYS:
            return "lifecycle ownership or activation sequence changed"
        if key in cls.FILTER_KEYS or directive in {
            "NoNewPrivileges", "ProtectSystem", "ProtectHome",
            "ProtectKernelModules", "PrivateDevices", "PrivateTmp",
        }:
            return "sandbox privilege boundary or required mapper access changed"
        if directive in {"TimeoutStartSec", "TimeoutStopSec", "JobTimeoutSec"}:
            return "boot or shutdown work may escape its bounded deadline"
        if directive == "RequiresMountsFor":
            return "durable recovery storage may no longer gate lifecycle mutation"
        if section == "Unit":
            return "dependency or ordering graph changed around swap lifecycle ownership"
        return "required deployed unit contract changed"

    def assert_effective_security(
        self,
        extra: dict[str, dict[str, str]] | None = None,
        *,
        shared_extra: dict[str, dict[str, str]] | None = None,
        base_overrides: dict[str, str] | None = None,
    ) -> None:
        baseline, baseline_origins, _ = self.effective_fixture()
        actual, origins, shadows = self.effective_fixture(
            extra,
            shared_extra=shared_extra,
            base_overrides=base_overrides,
        )
        base_override_keys: dict[str, set[tuple[str, str]]] = {}
        for unit, replacement in (base_overrides or {}).items():
            _, path = self.UNIT_PATHS[unit]
            vendor_base, _ = self.merged_directives(read_text(path), ())
            replacement_base, _ = self.merged_directives(
                replacement, (), base_origin="admin unit override"
            )
            base_override_keys[unit] = {
                key
                for key in set(vendor_base) | set(replacement_base)
                if vendor_base.get(key) != replacement_base.get(key)
            }

        for unit in baseline:
            for key in sorted(set(baseline[unit]) | set(actual[unit])):
                if key == ("Unit", "Description"):
                    continue
                required = baseline[unit].get(key)
                observed = actual[unit].get(key)
                if required == observed:
                    continue

                baseline_origin = baseline_origins[unit].get(key, "")
                if key in base_override_keys.get(unit, set()):
                    # A generator may still add another value to an additive
                    # directive after an administrator replaced the main unit.
                    # Attribute the lost vendor contribution to the replacement,
                    # not to the surviving generator fragment.
                    origin = "admin unit override"
                elif baseline_origin.startswith("generator:") and shadows[unit]:
                    origin = ", ".join(shadows[unit])
                else:
                    origin = origins[unit].get(key, "missing")

                section, directive = key
                self.fail(
                    f"FAIL {unit} effective {section}.{directive}: "
                    f"required={required!r}; observed={observed!r}; "
                    f"override={origin}; "
                    f"safety={self.safety_consequence(unit, key)}"
                )

    def test_authorized_generator_dependencies_preserve_lifecycle(self) -> None:
        # An unchanged vendor unit is also checked by the static sandbox
        # contract, independently of our effective-drop-in comparison.
        UnitSandboxContractTests().assert_secure_units(
            mapper=read_text(MAPPER_SERVICE),
            verifier=read_text(BOOT_VERIFY_SERVICE),
            health=read_text(RUNTIME_HEALTH_SERVICE),
            passive_swap=read_text(PRIMARY_SWAP),
        )
        effective, _, _ = self.effective_fixture()
        _, device, raw_swap = self.authorized_dropins()
        mapper = effective["mapper"]
        self.assertEqual(mapper[("Unit", "Requires")], ("-.mount", device))
        self.assertEqual(
            mapper[("Unit", "After")],
            ("-.mount", "systemd-modules-load.service",
             r"dev-mapper-swapz\x2dprimary.swap", device),
        )
        self.assertEqual(
            mapper[("Unit", "Before")],
            ("swap.target", "shutdown.target", raw_swap),
        )
        self.assertEqual(
            mapper[("Unit", "Conflicts")], ("shutdown.target", raw_swap)
        )
        self.assertEqual(
            mapper[("Service", "ExecStartPre")],
            (
                "@SWAPZ_SBINDIR@/swapz-primary-runtime-health activation-guard",
                "@SWAPZ_SBINDIR@/swapz-primary-boot-verify preflight",
                "-@SWAPZ_SBINDIR@/swapzctl primary recover",
                "@SWAPZ_SBINDIR@/swapzctl primary prepare",
            ),
        )
        self.assertEqual(
            mapper[("Service", "ExecStart")],
            ("@SWAPZ_SBINDIR@/swapzctl primary start",),
        )
        self.assertEqual(
            mapper[("Service", "ExecStop")],
            ("@SWAPZ_SBINDIR@/swapzctl primary stop",),
        )
        self.assertEqual(
            mapper[("Service", "ExecStopPost")],
            ("-@SWAPZ_SBINDIR@/swapz-primary-runtime-health stop-observe",),
        )
        self.assertEqual(mapper[("Unit", "JobTimeoutSec")], ("300s",))
        self.assertEqual(mapper[("Unit", "JobTimeoutAction")], ("none",))
        self.assertEqual(effective["device"][("Unit", "JobTimeoutSec")], ("30s",))
        self.assertEqual(effective["device"][("Unit", "JobTimeoutAction")], ("none",))
        self.assert_effective_security()

    def test_scalar_and_resettable_list_semantics_use_effective_values(self) -> None:
        self.assert_effective_security({
            "mapper": {
                "60-temporary.conf": (
                    "[Service]\n"
                    "TimeoutStartSec=15s\n"
                    "SystemCallFilter=\n"
                    "[Unit]\n"
                    "Requires=\n"
                ),
                "90-restore.conf": (
                    "[Service]\n"
                    "TimeoutStartSec=120s\n"
                    "SystemCallFilter=~@mount\n"
                ),
            },
        })
        with self.assertRaisesRegex(AssertionError, "effective Service.TimeoutStartSec"):
            self.assert_effective_security({
                "mapper": {"90-unbounded.conf": "[Service]\nTimeoutStartSec=infinity\n"}
            })

    def test_empty_dependency_assignments_do_not_remove_required_edges(self) -> None:
        self.assert_effective_security({
            "mapper": {
                "90-empty-dependencies.conf": (
                    "[Unit]\n"
                    "Requires=\n"
                    "RequiresMountsFor=\n"
                    "After=\n"
                    "Before=\n"
                    "Conflicts=\n"
                ),
            },
        })

    def test_higher_priority_unit_override_cannot_remove_required_dependencies(self) -> None:
        mapper = read_text(MAPPER_SERVICE)
        cases = (
            (
                "RequiresMountsFor=/var/lib/swapz/physical-recovery\n",
                "mapper effective Unit.RequiresMountsFor",
                "durable recovery storage",
            ),
            (
                "Requires=-.mount\n",
                "mapper effective Unit.Requires",
                "dependency or ordering graph",
            ),
        )
        for removed, directive, consequence in cases:
            with self.subTest(removed=removed.rstrip()):
                self.assertIn(removed, mapper)
                replaced = mapper.replace(removed, "", 1)
                with self.assertRaises(AssertionError) as caught:
                    self.assert_effective_security(
                        base_overrides={"mapper": replaced}
                    )
                diagnostic = str(caught.exception)
                self.assertIn(directive, diagnostic)
                self.assertIn("override=admin unit override", diagnostic)
                self.assertIn(consequence, diagnostic)

    def test_dropin_scope_and_same_name_precedence_match_systemd(self) -> None:
        self.assertEqual(
            self.matching_dropin_scopes("swapz-primary-mapper.service"),
            (
                "service.d",
                "swapz-.service.d",
                "swapz-primary-.service.d",
                "swapz-primary-mapper.service.d",
            ),
        )

        sources, _, _ = self.dropin_sources(
            None,
            {
                "service.d": {
                    # The generator's exact-unit fragment with this same name
                    # has higher scope specificity and must win for the mapper.
                    "50-selected-target.conf": (
                        "[Service]\nNoNewPrivileges=no\n"
                    ),
                },
            },
        )
        fragments, shadows = self.resolve_dropins(
            "swapz-primary-mapper.service", sources
        )
        origins = tuple(origin for origin, _ in fragments)
        self.assertIn(
            "generator:swapz-primary-mapper.service.d/50-selected-target.conf",
            origins,
        )
        self.assertNotIn(
            "admin:service.d/50-selected-target.conf", origins
        )
        self.assertEqual(shadows, ())

        with self.assertRaises(AssertionError) as caught:
            self.assert_effective_security({
                "mapper": {
                    # Same scope and filename: /etc-style administrator
                    # configuration outranks normal generator output.
                    "50-selected-target.conf": (
                        "[Unit]\n"
                        "JobTimeoutSec=300s\n"
                        "JobTimeoutAction=none\n"
                    ),
                },
            })
        diagnostic = str(caught.exception)
        self.assertIn(
            "override=admin:swapz-primary-mapper.service.d/"
            "50-selected-target.conf",
            diagnostic,
        )
        self.assertIn("effective Unit.", diagnostic)

    def test_type_and_dash_prefix_dropins_are_security_relevant(self) -> None:
        cases = (
            (
                "service.d",
                "[Service]\nNoNewPrivileges=no\n",
                "mapper effective Service.NoNewPrivileges",
            ),
            (
                "swapz-primary-boot-.service.d",
                "[Service]\nCapabilityBoundingSet=CAP_SYS_ADMIN CAP_SYS_MODULE\n",
                "verifier effective Service.CapabilityBoundingSet",
            ),
            (
                "swap.d",
                "[Install]\nWantedBy=swap.target\n",
                "passive_swap effective Install.WantedBy",
            ),
        )
        for scope, fragment, expected in cases:
            with self.subTest(scope=scope):
                with self.assertRaises(AssertionError) as caught:
                    self.assert_effective_security(
                        shared_extra={
                            scope: {"99-untrusted.conf": fragment},
                        }
                    )
                diagnostic = str(caught.exception)
                self.assertIn(expected, diagnostic)
                self.assertIn(
                    f"admin:{scope}/99-untrusted.conf", diagnostic
                )

    def test_untrusted_dropins_cannot_override_security_or_ownership(self) -> None:
        mutations = (
            ("mapper", "[Unit]\nAfter=swap.target\n", "Unit.After"),
            ("mapper", "[Unit]\nBefore=systemd-modules-load.service\n", "Unit.Before"),
            ("mapper", "[Unit]\nConflicts=swap.target\n", "Unit.Conflicts"),
            ("mapper", "[Unit]\nRequires=dev-mapper-swapz\\x2dprimary.swap\n", "Unit.Requires"),
            ("mapper", "[Unit]\nBindsTo=dev-mapper-swapz\\x2dprimary.swap\n", "Unit.BindsTo"),
            ("mapper", "[Unit]\nJobTimeoutSec=infinity\n", "Unit.JobTimeoutSec"),
            ("device", "[Unit]\nJobTimeoutSec=infinity\n", "Unit.JobTimeoutSec"),
            ("mapper", "[Service]\nTimeoutStartSec=infinity\n", "Service.TimeoutStartSec"),
            ("mapper", "[Service]\nTimeoutStopSec=infinity\n", "Service.TimeoutStopSec"),
            ("mapper", "[Service]\nNoNewPrivileges=no\n", "Service.NoNewPrivileges"),
            ("mapper", "[Service]\nProtectSystem=no\n", "Service.ProtectSystem"),
            ("mapper", "[Service]\nProtectKernelModules=yes\n", "Service.ProtectKernelModules"),
            ("mapper", "[Service]\nPrivateDevices=yes\n", "Service.PrivateDevices"),
            ("mapper", "[Service]\nPrivateTmp=yes\n", "Service.PrivateTmp"),
            ("mapper", "[Service]\nCapabilityBoundingSet=\nCapabilityBoundingSet=CAP_SYS_ADMIN\n", "Service.CapabilityBoundingSet"),
            ("mapper", "[Service]\nSystemCallFilter=~@mount @swap\n", "Service.SystemCallFilter"),
            ("mapper", "[Service]\nSystemCallFilter=\n", "Service.SystemCallFilter"),
            ("mapper", "[Service]\nExecStartPre=\nExecStartPre=/usr/bin/true\n", "Service.ExecStartPre"),
            ("mapper", "[Service]\nExecStart=\nExecStart=/usr/bin/true\n", "Service.ExecStart"),
            ("mapper", "[Service]\nExecStop=\nExecStop=/usr/bin/true\n", "Service.ExecStop"),
            ("mapper", "[Service]\nExecStopPost=\nExecStopPost=@SWAPZ_SBINDIR@/swapzctl primary stop\n", "Service.ExecStopPost"),
            ("verifier", "[Service]\nProtectKernelModules=yes\n", "Service.ProtectKernelModules"),
            ("verifier", "[Service]\nSystemCallFilter=\nSystemCallFilter=~@mount @module\n", "Service.SystemCallFilter"),
            ("health", "[Service]\nSystemCallFilter=\nSystemCallFilter=~@mount\n", "Service.SystemCallFilter"),
            ("health", "[Service]\nCapabilityBoundingSet=CAP_SYS_MODULE\n", "Service.CapabilityBoundingSet"),
            ("health", "[Service]\nExecStop=@SWAPZ_SBINDIR@/swapzctl primary stop\n", "Service.ExecStop"),
            ("verifier", "[Service]\nExecStart=\nExecStart=@SWAPZ_SBINDIR@/swapzctl primary start\n", "Service.ExecStart"),
            ("verifier", "[Unit]\nRequires=swapz-primary-mapper.service\n", "Unit.Requires"),
            ("health", "[Unit]\nWants=swapz-primary-mapper.service\n", "Unit.Wants"),
            ("passive_swap", "[Install]\nWantedBy=swap.target\n", "Install.WantedBy"),
            ("passive_swap", "[Install]\nRequiredBy=swap.target\n", "Install.RequiredBy"),
            ("passive_swap", "[Unit]\nRefuseManualStart=no\n", "Unit.RefuseManualStart"),
        )
        for unit, fragment, directive in mutations:
            with self.subTest(unit=unit, directive=directive, fragment=fragment):
                with self.assertRaises(AssertionError) as caught:
                    self.assert_effective_security(
                        {unit: {"99-untrusted.conf": fragment}}
                    )
                diagnostic = str(caught.exception)
                self.assertIn(f"{unit} effective {directive}", diagnostic)
                self.assertIn("required=", diagnostic)
                self.assertIn("observed=", diagnostic)
                self.assertIn("99-untrusted.conf", diagnostic)
                self.assertIn("safety=", diagnostic)

    def test_unsupported_continuation_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid effective unit fragment"):
            self.merged_directives(
                "[Service]\nExecStart=/bin/true\n",
                ((
                    "admin:swapz-primary-mapper.service.d/99-unsupported.conf",
                    "[Service]\nExecStartPre=/bin/\\\n/usr/bin/true\n",
                ),),
            )

    def test_systemd_analyze_accepts_authorized_fixture_syntax_only(self) -> None:
        analyzer = shutil.which("systemd-analyze")
        if analyzer is None:
            self.skipTest("INCOMPLETE: systemd-analyze absent; contracts still run")
        dropins, selected_device, _ = self.authorized_dropins()
        with tempfile.TemporaryDirectory(prefix="swapz-effective-systemd-") as directory:
            unit_dir = Path(directory)
            units = []
            for unit, (filename, source) in self.UNIT_PATHS.items():
                installed = read_text(source).replace("@SWAPZ_SBINDIR@", "/usr/bin")
                # Existing helpers need not exist: no service is executed.
                for helper in ("swapzctl", "swapz-primary-boot-verify",
                               "swapz-primary-runtime-health"):
                    installed = installed.replace(f"/usr/bin/{helper}", "/usr/bin/true")
                unit_path = unit_dir / filename
                unit_path.write_text(installed, encoding="utf-8")
                units.append(str(unit_path))
                for dropin_name, contents in dropins.get(unit, {}).items():
                    destination = unit_dir / f"{filename}.d"
                    destination.mkdir(exist_ok=True)
                    (destination / dropin_name).write_text(contents, encoding="utf-8")
            device_dir = unit_dir / f"{selected_device}.d"
            device_dir.mkdir()
            for filename, contents in dropins["device"].items():
                (device_dir / filename).write_text(contents, encoding="utf-8")
            env = os.environ.copy()
            env["SYSTEMD_UNIT_PATH"] = f"{unit_dir}:/usr/lib/systemd/system:/lib/systemd/system"
            result = subprocess.run(
                [analyzer, "verify", *units], check=False,
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            # Syntax is not evidence that the actual kernel and systemd
            # support this sandbox with DM, module and swap syscalls.
            self.assert_effective_security()

    def test_systemd_analyze_confirms_dependency_reset_is_a_noop(self) -> None:
        analyzer = shutil.which("systemd-analyze")
        if analyzer is None:
            self.skipTest("INCOMPLETE: systemd-analyze absent; contracts still run")
        with tempfile.TemporaryDirectory(prefix="swapz-systemd-dependency-") as directory:
            unit_dir = Path(directory)
            unit = unit_dir / "swapz-dependency-reset.service"
            dropin_dir = unit_dir / "swapz-dependency-reset.service.d"
            dropin_dir.mkdir()
            unit.write_text(
                "[Unit]\n"
                "DefaultDependencies=no\n"
                "Requires=swapz-intentionally-missing.service\n"
                "After=swapz-intentionally-missing.service\n"
                "[Service]\n"
                "Type=oneshot\n"
                "ExecStart=/usr/bin/true\n",
                encoding="utf-8",
            )
            (dropin_dir / "90-empty.conf").write_text(
                "[Unit]\nRequires=\nAfter=\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["SYSTEMD_UNIT_PATH"] = str(unit_dir)
            result = subprocess.run(
                [analyzer, "verify", str(unit)],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("swapz-intentionally-missing.service", result.stderr)


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



    def test_activation_guard_refusal_blocks_all_mapper_operations(self) -> None:
        env = self.env.copy()
        env["MOCK_RUNTIME_STATUS"] = "1"
        self.assertNotEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["runtime:activation-guard"],
        )

    def test_cold_boot_preflight_refusal_blocks_recovery_prepare_and_start(self) -> None:
        env = self.env.copy()
        env["MOCK_PREFLIGHT_STATUS"] = "1"
        self.assertNotEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["runtime:activation-guard", "verify:preflight"],
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
        self.package_sources = self.root / "usr" / "src"
        self.package_transactions = self.root / "var" / "lib" / "swapz-package-transactions"
        self.installed_module = self.root / "lib" / "modules" / "mock" / "dm-swapz.ko"
        for directory in (self.sbin, self.libexec, self.bin, self.proc, self.sys,
                          self.dev, self.etc, self.report, self.recovery,
                          self.package_sources, self.package_transactions,
                          self.installed_module.parent):
            directory.mkdir(parents=True, exist_ok=True)
        self.report.chmod(0o700)
        self.recovery.chmod(0o700)
        self.package_transactions.chmod(0o700)
        (self.proc / "sys" / "kernel" / "random").mkdir(parents=True)
        # Model a readable running-kernel hibernation state with no resume
        # target configured. Individual tests override these files when they
        # exercise conflicting or unreadable resume configuration.
        (self.proc / "cmdline").write_text("quiet\n", encoding="ascii")
        (self.sys / "power").mkdir(parents=True)
        (self.sys / "power" / "resume").write_text("0:0\n", encoding="ascii")
        (self.sys / "module" / "dm_swapz" / "parameters").mkdir(parents=True)
        (self.sys / "dev" / "block" / "253:0" / "dm").mkdir(parents=True)
        (self.sys / "dev" / "block" / "253:0" / "dm" / "name").write_text("swapz-primary\n", encoding="ascii")
        (self.dev / "disk" / "by-partuuid").mkdir(parents=True)
        (self.dev / "disk" / "by-uuid").mkdir(parents=True)
        (self.dev / "mapper").mkdir(parents=True)
        (self.dev / "sda").touch()
        (self.dev / "mapper" / "swapz-primary").touch()
        for partuuid in (PARTUUID, OTHER_PARTUUID):
            (self.dev / "disk" / "by-partuuid" / partuuid).touch()
        (self.dev / "disk" / "by-uuid" / "target-uuid").touch()
        (self.libexec / "dm-swapz.ko").write_bytes(b"mock-module")
        self.installed_module.write_bytes(b"mock-module")
        (self.libexec / "dm-swapz.ko").chmod(0o644)
        self.installed_module.chmod(0o644)
        package_source = self.package_sources / "swapz-3.0.0-alpha.1"
        package_source.mkdir()
        self.qualification_marker = package_source / ".swapz-qualification"
        self.qualification_marker.write_text(
            "schema=swapz-package-v1\n"
            "version=3.0.0-alpha.1\n"
            f"kernel_release={os.uname().release}\n"
            f"source_sha={SOURCE_SHA}\n"
            f"qualification_report_sha256={'c' * 64}\n"
            f"swapzctl_sha256={'d' * 64}\n"
            f"module_sha256={MODULE_SHA}\n"
            f"oracle_sha256={'e' * 64}\n", encoding="ascii",
        )
        self.qualification_marker.chmod(0o644)
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
                "SWAPZ_PRIMARY_TEST_INSTALLED_MODULE": str(self.installed_module),
                "SWAPZ_PRIMARY_TEST_PACKAGE_SOURCES_ROOT": str(self.package_sources),
                "SWAPZ_PRIMARY_TEST_PACKAGE_TRANSACTIONS": str(self.package_transactions),
                "MOCK_MODULE_VERMAGIC": os.uname().release + " SMP",
                "MOCK_INSTALLED_MODULE_SHA": MODULE_SHA,
                "MOCK_PASSIVE_ENABLEMENT": "static",
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
            textwrap.dedent(
                """\
                #!/bin/sh
                if [ "$2" = "$SWAPZ_PRIMARY_TEST_INSTALLED_MODULE" ]; then
                    printf '%s  %s\\n' "$MOCK_INSTALLED_MODULE_SHA" "$2"
                else
                    printf '%s  %s\\n' "$MOCK_MODULE_SHA" "$2"
                fi
                """
            ),
        )
        write_executable(
            self.bin / "modinfo",
            textwrap.dedent(
                """\
                #!/bin/sh
                if [ "$1" = -n ]; then
                    printf '%s\\n' "$SWAPZ_PRIMARY_TEST_INSTALLED_MODULE"
                    exit 0
                fi
                [ "$1" = -F ] || exit 2
                case "$2" in
                swapz_build_source_sha) printf '%s\\n' "$MOCK_SOURCE_SHA" ;;
                swapz_build_source_clean) printf '1\\n' ;;
                vermagic) printf '%s\\n' "$MOCK_MODULE_VERMAGIC" ;;
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
                if [ "$1" = is-enabled ]; then
                    printf '%s\n' "$MOCK_PASSIVE_ENABLEMENT"
                    exit 0
                fi
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
                    if [ "$MOCK_DM_STATUS_OVERRIDE_SET" = 1 ]; then
                        printf '%s\\n' "$MOCK_DM_STATUS_OVERRIDE"
                    else
                        printf '0 216641536 swapz version=0 flush_err=0 segment_discards_failed=%s failed=%s error=0 upper_write_completed_err=0 endio_write_seen_err=0 endio_write_forced_err=0 gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 gc_reserve_segments_initial=2 gc_reserve_segments_current=2 gc_destination_advances=0 window_gc_pressure=0\\n' "$MOCK_DM_DISCARD_FAIL" "$MOCK_DM_STATUS_FAIL"
                    fi
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
        same_boot_runtime = self.report / "runtime" / "primary-execution.env"
        self.assertFalse(same_boot_runtime.exists())
        self.write_boot_id(BOOT_B)
        self.write_proc_swaps(active=True)
        self.write_active_transaction()
        # The mapper ExecStartPre always runs preflight before native start.
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)

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
        runtime_authorization = (
            self.report / "runtime" / "primary-execution.env")
        self.assertEqual(
            runtime_authorization.read_text(encoding="ascii"),
            "schema=swapz-primary-execution-v2\n"
            f"boot_id={BOOT_B}\n"
            f"source_sha={SOURCE_SHA}\n"
            f"partuuid={PARTUUID}\n"
            "target_device=8:1\n"
            f"target_size_bytes={TARGET_BYTES}\n")
        self.assertEqual(runtime_authorization.stat().st_mode & 0o777, 0o600)
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
        self.assertEqual(observed.stderr, "")

    def test_observation_claimed_token_cleanup_failure_never_restores_authority(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        consumed = self.report / "runtime" / ".primary-execution.observed.env"
        write_executable(
            self.bin / "rm",
            "#!/bin/sh\n"
            'if [ "${MOCK_REVOKE_UNLINK_EXIT:-0}" != 0 ] && '
            '[ "${3##*/}" = .primary-execution.observed.env ]; then\n'
            '    exit "$MOCK_REVOKE_UNLINK_EXIT"\n'
            "fi\n"
            'exec /usr/bin/rm "$@"\n',
        )
        failing_env = self.env.copy()
        failing_env["MOCK_REVOKE_UNLINK_EXIT"] = "73"
        failed = self.run_verifier("observe", env=failing_env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", failed.stdout)
        self.assertIn(
            "phase=token_revoke_consumed_unlink exit_status=73 reason=unlink_failed",
            failed.stderr,
        )
        self.assertNotIn(str(authorization), failed.stderr)
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("status=FAIL", report)
        self.assertIn("runtime_preflight_authorization_cleanup_failed", report)
        self.assertFalse(authorization.exists())
        self.assertTrue(consumed.is_file())
        self.assertEqual(consumed.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").is_file())
        self.assertTrue((self.report / f"report-{BOOT_B}.kernel-errors.log").is_file())

        # A retained claimed file is not activation authority. Preflight clears
        # it before minting a fresh canonical token for an explicit retry.
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertFalse(consumed.exists())
        self.assertTrue(authorization.is_file())
        retried = self.run_verifier("observe")
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertFalse(authorization.exists())
        self.assertFalse(consumed.exists())
        self.assertIn("status=PASS", (self.report / "latest.env").read_text())

    def test_observation_claim_sync_failure_refuses_pass_without_reusable_token(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        consumed = self.report / "runtime" / ".primary-execution.observed.env"
        sync_failed = self.root / "claim-sync-failed"
        write_executable(
            self.bin / "sync",
            "#!/bin/sh\n"
            'if [ "${MOCK_CLAIM_SYNC_EXIT:-0}" != 0 ] && '
            '[ "$1" = -f ] && '
            '[ "$2" = "$SWAPZ_PRIMARY_TEST_REPORT_BASE/runtime" ] && '
            '[ ! -e "$MOCK_CLAIM_SYNC_FAILED" ]; then\n'
            '    : > "$MOCK_CLAIM_SYNC_FAILED"\n'
            '    exit "$MOCK_CLAIM_SYNC_EXIT"\n'
            "fi\n"
            'exec /usr/bin/sync "$@"\n',
        )
        failing_env = self.env.copy()
        failing_env["MOCK_CLAIM_SYNC_EXIT"] = "74"
        failing_env["MOCK_CLAIM_SYNC_FAILED"] = str(sync_failed)
        failed = self.run_verifier("observe", env=failing_env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", failed.stdout)
        self.assertIn(
            "phase=token_claim_sync exit_status=74 reason=durability_sync_failed "
            "observed=authorization_claim_failed",
            failed.stderr,
        )
        self.assertNotIn(str(authorization), failed.stderr)
        self.assertTrue(sync_failed.is_file())
        self.assertFalse(authorization.exists())
        self.assertFalse(consumed.exists())
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("status=FAIL", report)
        self.assertIn("runtime_preflight_authorization_claim_failed", report)
        self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").is_file())

    def test_unexpected_observation_abort_revokes_preflight_authority(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        write_executable(
            self.bin / "mktemp",
            "#!/bin/sh\n"
            'case "$1" in\n'
            '*/.kernel-journal.XXXXXX) exit 75 ;;\n'
            'esac\n'
            'exec /usr/bin/mktemp "$@"\n',
        )
        aborted = self.run_verifier("observe")
        self.assertEqual(aborted.returncode, 1, aborted.stderr)
        self.assertIn("cannot create kernel-journal temporary", aborted.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", aborted.stdout)
        self.assertFalse(authorization.exists())
        self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").is_file())

    def test_interrupted_observation_consumes_preflight_authorization(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        journal_started = self.root / "observe-journal-started"
        journal_pid_file = self.root / "observe-journal-pid"
        write_executable(
            self.bin / "journalctl",
            "#!/bin/sh\n"
            '[ ! -e "$SWAPZ_PRIMARY_TEST_REPORT_BASE/runtime/primary-execution.env" ] || exit 91\n'
            '[ -f "$SWAPZ_PRIMARY_TEST_REPORT_BASE/runtime/.primary-execution.observed.env" ] || exit 92\n'
            'printf "%s\\n" "$$" > "$MOCK_OBSERVE_JOURNAL_PID"\n'
            'printf "started\\n" > "$MOCK_OBSERVE_JOURNAL_STARTED"\n'
            "exec sleep 15\n",
        )
        env = self.env.copy()
        env["MOCK_OBSERVE_JOURNAL_STARTED"] = str(journal_started)
        env["MOCK_OBSERVE_JOURNAL_PID"] = str(journal_pid_file)
        verifier = subprocess.Popen(
            [str(self.sbin / "swapz-primary-boot-verify"), "observe"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
        timeout_pid: int | None = None
        try:
            deadline = time.monotonic() + 4
            while (not journal_started.exists() and verifier.poll() is None
                   and time.monotonic() < deadline):
                time.sleep(0.02)
            self.assertTrue(journal_started.exists(), "fixture did not enter observe")
            journal_pid = int(journal_pid_file.read_text(encoding="ascii"))
            journal_status = Path(f"/proc/{journal_pid}/status").read_text(encoding="ascii")
            timeout_pid = int(next(
                line.split()[1] for line in journal_status.splitlines()
                if line.startswith("PPid:")
            ))
            # Timeout remains in the verifier process group and directly owns
            # the journal child. Only the verifier holds the capture-pipe writers.
            self.assertEqual(os.getpgid(verifier.pid), verifier.pid)
            self.assertEqual(os.getpgid(timeout_pid), verifier.pid)
            self.assertEqual(os.getpgid(journal_pid), verifier.pid)
            self.assertTrue(os.readlink(f"/proc/{verifier.pid}/fd/1").startswith("pipe:["))
            self.assertTrue(os.readlink(f"/proc/{verifier.pid}/fd/2").startswith("pipe:["))
            self.assertIn("/.kernel-journal.", os.readlink(f"/proc/{journal_pid}/fd/1"))
            self.assertEqual(os.readlink(f"/proc/{journal_pid}/fd/2"), "/dev/null")
            os.killpg(verifier.pid, signal.SIGTERM)
            stdout, stderr = verifier.communicate(timeout=4)
            self.assertEqual(verifier.returncode, 143, stderr)
            self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", stdout)
            self.assertIn(
                "phase=observe_signal observed=interrupted exit_status=143 "
                "evidence_retained=unknown action=inspect_cold_boot_report_before_rearming",
                stderr,
            )
            self.assertIn(
                "signal=TERM process_ownership=owned_timeout_child "
                "child_status=143 token_disposition=revoked",
                stderr,
            )
            self.assertFalse(Path(f"/proc/{timeout_pid}").exists())
            self.assertFalse(Path(f"/proc/{journal_pid}").exists())
            self.assertFalse(authorization.exists())
            self.assertFalse(
                (self.report / "runtime" / ".primary-execution.observed.env").exists()
            )
            self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").is_file())
        finally:
            if verifier.poll() is None:
                os.killpg(verifier.pid, signal.SIGKILL)
                verifier.communicate(timeout=5)

        # A second attempt cannot accept a token consumed by an interruption.
        write_executable(self.bin / "journalctl", "#!/bin/sh\nexit 0\n")
        repeated = self.run_verifier("observe")
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )

    def test_interrupted_observation_cleanup_failure_preserves_signal(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        consumed = self.report / "runtime" / ".primary-execution.observed.env"
        journal_started = self.root / "failed-cleanup-journal-started"
        journal_pid_file = self.root / "failed-cleanup-journal-pid"
        write_executable(
            self.bin / "journalctl",
            "#!/bin/sh\n"
            "trap '' TERM\n"
            'printf "%s\\n" "$$" > "$MOCK_OBSERVE_JOURNAL_PID"\n'
            'printf "started\\n" > "$MOCK_OBSERVE_JOURNAL_STARTED"\n'
            "exec sleep 15\n",
        )
        write_executable(
            self.bin / "rm",
            "#!/bin/sh\n"
            'case "$3" in */.primary-execution.observed.env) exit 73 ;; esac\n'
            'exec /usr/bin/rm "$@"\n',
        )
        env = self.env.copy()
        env["MOCK_OBSERVE_JOURNAL_STARTED"] = str(journal_started)
        env["MOCK_OBSERVE_JOURNAL_PID"] = str(journal_pid_file)
        verifier = subprocess.Popen(
            [str(self.sbin / "swapz-primary-boot-verify"), "observe"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
        timeout_pid: int | None = None
        try:
            deadline = time.monotonic() + 4
            while (not journal_started.exists() and verifier.poll() is None
                   and time.monotonic() < deadline):
                time.sleep(0.02)
            self.assertTrue(journal_started.exists(), "fixture did not enter observe")
            journal_pid = int(journal_pid_file.read_text(encoding="ascii"))
            journal_status = Path(f"/proc/{journal_pid}/status").read_text(encoding="ascii")
            timeout_pid = int(next(
                line.split()[1] for line in journal_status.splitlines()
                if line.startswith("PPid:")
            ))
            self.assertEqual(os.getpgid(timeout_pid), verifier.pid)
            self.assertEqual(os.getpgid(journal_pid), verifier.pid)
            os.killpg(verifier.pid, signal.SIGTERM)
            stdout, stderr = verifier.communicate(timeout=4)
            self.assertEqual(verifier.returncode, 143, stderr)
            self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", stdout)
            self.assertIn(
                "phase=observe_signal observed=interrupted exit_status=143", stderr
            )
            self.assertIn(
                "signal=TERM process_ownership=owned_timeout_child "
                "child_status=137",
                stderr,
            )
            self.assertIn(
                "token_disposition=unknown "
                "token_cleanup_phase=token_revoke_consumed_unlink "
                "token_cleanup_exit_status=73",
                stderr,
            )
            self.assertIn(
                "phase=token_revoke_consumed_unlink exit_status=73 reason=unlink_failed",
                stderr,
            )
            self.assertNotIn(str(authorization), stderr)
            self.assertFalse(Path(f"/proc/{timeout_pid}").exists())
            self.assertFalse(Path(f"/proc/{journal_pid}").exists())
            self.assertFalse(authorization.exists())
            self.assertTrue(consumed.is_file())
        finally:
            if verifier.poll() is None:
                os.killpg(verifier.pid, signal.SIGKILL)
                verifier.communicate(timeout=5)

        # Even a failed claimed-token unlink never restores canonical authority.
        write_executable(self.bin / "rm", '#!/bin/sh\nexec /usr/bin/rm "$@"\n')
        write_executable(self.bin / "journalctl", "#!/bin/sh\nexit 0\n")
        repeated = self.run_verifier("observe")
        self.assertEqual(repeated.returncode, 1, repeated.stderr)
        self.assertFalse(authorization.exists())
        self.assertFalse(consumed.exists())
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )

    def test_observation_claim_rename_failure_revokes_canonical_token(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        consumed = self.report / "runtime" / ".primary-execution.observed.env"
        write_executable(
            self.bin / "mv",
            "#!/bin/sh\n"
            'if [ "${3##*/}" = primary-execution.env ] && '
            '[ "${4##*/}" = .primary-execution.observed.env ]; then\n'
            "    exit 75\n"
            "fi\n"
            'exec /usr/bin/mv "$@"\n',
        )
        failed = self.run_verifier("observe")
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", failed.stdout)
        self.assertIn(
            "phase=token_claim_rename exit_status=75 reason=rename_failed "
            "observed=authorization_claim_failed",
            failed.stderr,
        )
        self.assertFalse(authorization.exists())
        self.assertFalse(consumed.exists())
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("runtime_preflight_authorization_missing_or_invalid", report)
        self.assertIn("runtime_preflight_authorization_claim_failed", report)

    def test_claim_and_unlink_failure_invalidates_canonical_authority(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        consumed = self.report / "runtime" / ".primary-execution.observed.env"
        write_executable(
            self.bin / "mv",
            "#!/bin/sh\n"
            'if [ "${MOCK_CLAIM_RENAME_EXIT:-0}" != 0 ] && '
            '[ "${3##*/}" = primary-execution.env ] && '
            '[ "${4##*/}" = .primary-execution.observed.env ]; then\n'
            '    exit "$MOCK_CLAIM_RENAME_EXIT"\n'
            "fi\n"
            'exec /usr/bin/mv "$@"\n',
        )
        write_executable(
            self.bin / "rm",
            "#!/bin/sh\n"
            'if [ "${MOCK_CANONICAL_UNLINK_EXIT:-0}" != 0 ] && '
            '[ "${3##*/}" = primary-execution.env ]; then\n'
            '    exit "$MOCK_CANONICAL_UNLINK_EXIT"\n'
            "fi\n"
            'exec /usr/bin/rm "$@"\n',
        )
        env = self.env.copy()
        env["MOCK_CLAIM_RENAME_EXIT"] = "75"
        env["MOCK_CANONICAL_UNLINK_EXIT"] = "73"
        failed = self.run_verifier("observe", env=env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", failed.stdout)
        self.assertIn(
            "phase=token_claim_rename exit_status=75 reason=rename_failed "
            "observed=authorization_claim_failed",
            failed.stderr,
        )
        self.assertIn(
            "phase=token_revoke_unlink exit_status=73 reason=unlink_failed "
            "observed=authorization_cleanup_failed",
            failed.stderr,
        )
        self.assertTrue(authorization.is_file())
        self.assertEqual(
            authorization.stat().st_mode & 0o777, 0,
            "canonical token remained manager-eligible after claim and unlink failure",
        )
        self.assertFalse(consumed.exists())
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("runtime_preflight_authorization_missing_or_invalid", report)
        self.assertIn("runtime_preflight_authorization_claim_failed", report)
        self.assertIn("runtime_preflight_authorization_cleanup_failed", report)

        # An explicit new preflight clears the invalid canonical file before
        # minting fresh authority; the mode-000 file is never reused.
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        self.assertEqual(authorization.stat().st_mode & 0o777, 0o600)

    def test_revocation_failure_keeps_abort_cleanup_retry_armed(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        first_failure_marker = self.root / "revocation-first-failure"
        write_executable(
            self.bin / "rm",
            "#!/bin/sh\n"
            'if [ "$3" = "$SWAPZ_PRIMARY_TEST_REPORT_BASE/runtime/.primary-execution.observed.env" ] && '
            '[ ! -e "$MOCK_REVOKE_FIRST_FAILURE_MARKER" ]; then\n'
            '    : > "$MOCK_REVOKE_FIRST_FAILURE_MARKER"\n'
            "    exit 73\n"
            "fi\n"
            'exec /usr/bin/rm "$@"\n',
        )
        write_executable(
            self.bin / "mktemp",
            "#!/bin/sh\n"
            'case "$1" in\n'
            '*/.boot-report.XXXXXX) exit 75 ;;\n'
            'esac\n'
            'exec /usr/bin/mktemp "$@"\n',
        )
        env = self.env.copy()
        env["MOCK_REVOKE_FIRST_FAILURE_MARKER"] = str(first_failure_marker)
        aborted = self.run_verifier("observe", env=env)
        self.assertEqual(aborted.returncode, 1, aborted.stderr)
        self.assertTrue(first_failure_marker.is_file())
        self.assertIn(
            "phase=token_revoke_consumed_unlink exit_status=73 reason=unlink_failed",
            aborted.stderr,
        )
        self.assertIn("cannot create boot report", aborted.stderr)
        self.assertNotIn("COLD_BOOT_OBSERVATION=PASS", aborted.stdout)
        self.assertFalse(
            authorization.exists(),
            "claimed authorization unexpectedly returned to the canonical path",
        )
        self.assertFalse(
            (self.report / "runtime" / ".primary-execution.observed.env").exists(),
            "EXIT cleanup did not retry claimed-token cleanup before aborting",
        )
        self.assertTrue((self.report / f"report-{BOOT_B}.dm-status.txt").is_file())
        self.assertTrue((self.report / f"report-{BOOT_B}.kernel-errors.log").is_file())

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

    def test_malformed_partuuid_structure_cannot_arm_cold_boot_harness(self) -> None:
        self.write_proc_swaps(active=False)
        for malformed in (
                "0123456--89abcdef",
                "-01234567-89abcdef",
                "01234567-89abcdef-",
                "0123--4567",
        ):
            with self.subTest(partuuid=malformed):
                (self.dev / "disk" / "by-partuuid" / malformed).touch(exist_ok=True)
                env = self.env.copy()
                env["MOCK_PARTUUID"] = malformed
                result = self.run_verifier("arm", env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("protected primary selector is invalid", result.stderr)

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

    def test_failed_repreflight_revokes_runtime_authorization(self) -> None:
        self.arm_then_reboot()
        first = self.run_verifier("preflight")
        self.assertEqual(first.returncode, 0, first.stderr)
        runtime_authorization = (
            self.report / "runtime" / "primary-execution.env")
        self.assertTrue(runtime_authorization.is_file())

        env = self.env.copy()
        env["MOCK_MODULE_SHA"] = "f" * 64
        rejected = self.run_verifier("preflight", env=env)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(
            "installed module bytes changed after arming", rejected.stderr)
        self.assertFalse(runtime_authorization.exists())


    def test_failed_cold_boot_observation_revokes_activation_token(self) -> None:
        self.arm_then_reboot()
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        runtime_authorization = (
            self.report / "runtime" / "primary-execution.env")
        self.assertTrue(runtime_authorization.is_file())

        env = self.env.copy()
        env["MOCK_DM_UUID"] = "SWAPZ-PRIMARY-" + "f" * 32
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertFalse(runtime_authorization.exists())
        report = (self.report / f"report-{BOOT_B}.env").read_text(
            encoding="utf-8")
        self.assertIn("status=FAIL", report)
        self.assertIn("mapper_uuid_not_bound_to_active_run", report)

    def test_missing_or_duplicated_one_use_preflight_authority_is_fail_closed(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        self.assertTrue(authorization.is_file())
        authorization.unlink()
        missing = self.run_verifier("observe")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )
        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        with authorization.open("a", encoding="ascii") as handle:
            handle.write(f"boot_id={BOOT_B}\n")
        duplicated = self.run_verifier("observe")
        self.assertEqual(duplicated.returncode, 1, duplicated.stderr)
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )
        self.assertFalse(authorization.exists())

        preflight = self.run_verifier("preflight")
        self.assertEqual(preflight.returncode, 0, preflight.stderr)
        authorization.write_text(
            authorization.read_text(encoding="ascii").replace(
                f"boot_id={BOOT_B}", f"boot_id={BOOT_A}"), encoding="ascii")
        stale = self.run_verifier("observe")
        self.assertEqual(stale.returncode, 1, stale.stderr)
        self.assertIn("runtime_preflight_authorization_missing_or_invalid",
                      (self.report / "latest.env").read_text())
        self.assertFalse(authorization.exists())

    def test_replaced_authorization_symlink_is_never_accepted_or_followed(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        sentinel = self.root / "protected-authorization-sentinel"
        sentinel.write_text("do-not-touch\n", encoding="ascii")
        sentinel.chmod(0o600)
        authorization.unlink()
        authorization.symlink_to(sentinel)
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )
        self.assertEqual(sentinel.read_text(encoding="ascii"), "do-not-touch\n")
        self.assertFalse(authorization.is_symlink())

    def test_successful_observation_revokes_one_use_preflight_token(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        self.assertTrue(authorization.is_file())
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertFalse(
            authorization.exists(),
            "FAIL: successful observer retained reusable preflight authorization",
        )
        self.assertFalse(
            (self.report / "runtime" / ".primary-execution.observed.env").exists()
        )
        repeat = self.run_verifier("observe")
        self.assertEqual(repeat.returncode, 1, repeat.stderr)
        self.assertIn(
            "runtime_preflight_authorization_missing_or_invalid",
            (self.report / "latest.env").read_text(encoding="utf-8"),
        )

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

    def test_malformed_distinct_partuuid_resume_blocks_arm(self) -> None:
        self.write_proc_swaps(active=False)
        (self.proc / "cmdline").write_text(
            "quiet resume=PARTUUID=1234---5678\n", encoding="ascii"
        )
        arm = self.run_verifier("arm")
        self.assertNotEqual(arm.returncode, 0, arm.stderr)
        self.assertIn("unsupported hibernation/resume configuration", arm.stderr)

    def test_hibernation_configuration_drift_prevents_cold_boot_pass(self) -> None:
        self.arm_then_reboot()
        config_dir = self.etc / "initramfs-tools" / "conf.d"
        config_dir.mkdir(parents=True)
        (config_dir / "resume").write_text("RESUME=auto\n", encoding="ascii")
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("hibernation_resume_configuration_conflict", report)



    def test_same_boot_observation_never_passes(self) -> None:
        self.write_proc_swaps(active=False)
        arm = self.run_verifier("arm")
        self.assertEqual(arm.returncode, 0, arm.stderr)
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 2, observed.stderr)
        report = (self.report / f"report-{BOOT_A}.env").read_text(encoding="utf-8")
        self.assertIn("cold_boot_observed=no", report)
        self.assertIn("owner_reboot_not_observed", report)
        self.assertNotIn("status=PASS", report)

    def test_durable_arm_record_mutations_never_authorize_activation(self) -> None:
        self.arm_then_reboot()
        arm_file = self.report / "armed.env"
        valid_arm = arm_file.read_text(encoding="ascii")
        mutations = (
            valid_arm.replace("schema=swapz-primary-boot-arm-v1", "schema=invalid"),
            valid_arm.replace(f"arm_boot_id={BOOT_A}", f"arm_boot_id={BOOT_B}"),
            valid_arm.replace(f"expected_module_sha256={MODULE_SHA}",
                              "expected_module_sha256=" + "f" * 64),
            valid_arm.replace(f"expected_module_source_sha={SOURCE_SHA}",
                              "expected_module_source_sha=" + "f" * 40),
            valid_arm.replace("expected_module_source_clean=1",
                              "expected_module_source_clean=0"),
            valid_arm.replace("expected_target_serial=", "expected_target_serial=\x00"),
            valid_arm.replace("expected_target_transport=", "expected_target_transport=\r"),
            valid_arm.replace("expected_target_size_bytes=",
                              "duplicate=1\nexpected_target_size_bytes="),
            valid_arm.replace(f"expected_partuuid={PARTUUID}\n", ""),
            valid_arm + "unexpected=value\n",
            valid_arm + "x" * 4096,
        )
        for mutation_index, malformed in enumerate(mutations):
            with self.subTest(mutation_index=mutation_index):
                self.assertNotEqual(
                    malformed, valid_arm, "mutation must change the arm record"
                )
                arm_file.write_text(malformed, encoding="ascii")
                arm_file.chmod(0o600)
                preflight = self.run_verifier("preflight")
                self.assertNotEqual(preflight.returncode, 0, preflight.stderr)
                self.assertFalse((self.report / "runtime" / "primary-execution.env").exists())
                observed = self.run_verifier("observe")
                self.assertNotEqual(observed.returncode, 0, observed.stderr)
                self.assertNotIn("status=PASS", (self.report / "latest.env").read_text())
        arm_file.write_text(valid_arm, encoding="ascii")
        arm_file.chmod(0o600)
        self.assertEqual(self.run_verifier("preflight").returncode, 0)

    def test_arm_file_symlink_hardlink_special_files_and_mode_are_rejected(self) -> None:
        import socket

        self.arm_then_reboot()
        arm_file = self.report / "armed.env"
        valid_arm = arm_file.read_bytes()
        outside = self.root / "outside-evidence"
        outside.write_bytes(valid_arm)
        outside.chmod(0o600)
        for kind in ("symlink", "hardlink", "fifo", "directory", "socket", "wrong-mode"):
            with self.subTest(kind=kind):
                arm_file.unlink()
                if kind == "symlink":
                    arm_file.symlink_to(outside)
                elif kind == "hardlink":
                    os.link(outside, arm_file)
                elif kind == "fifo":
                    os.mkfifo(arm_file)
                elif kind == "directory":
                    arm_file.mkdir()
                elif kind == "socket":
                    with socket.socket(socket.AF_UNIX) as connection:
                        connection.bind(str(arm_file))
                else:
                    arm_file.write_bytes(valid_arm)
                    arm_file.chmod(0o644)
                self.assertNotEqual(self.run_verifier("preflight").returncode, 0)
                self.assertFalse((self.report / "runtime" / "primary-execution.env").exists())
                observed = self.run_verifier("observe")
                self.assertNotEqual(observed.returncode, 0)
                self.assertNotIn("status=PASS", (self.report / "latest.env").read_text())
                self.assertEqual(outside.read_bytes(), valid_arm)
                if arm_file.is_dir() and not arm_file.is_symlink():
                    arm_file.rmdir()
                else:
                    arm_file.unlink()
                arm_file.write_bytes(valid_arm)
                arm_file.chmod(0o600)

    def test_wrong_owner_arm_file_is_rejected_without_root_privileges(self) -> None:
        # Override only the arm-record UID query. The rest of the system's
        # stat operations use the real tool, so this is a narrow rootless fault.
        self.arm_then_reboot()
        write_executable(
            self.bin / "stat",
            "#!/bin/sh\n"
            'if [ "$2" = "%u" ] && '
            '[ "$4" = "$SWAPZ_PRIMARY_TEST_REPORT_BASE/armed.env" ]; then\n'
            '    printf "%s\\n" "$MOCK_OTHER_OWNER_UID"\n'
            '    exit 0\n'
            'fi\n'
            'exec /usr/bin/stat "$@"\n',
        )
        env = self.env.copy()
        env["MOCK_OTHER_OWNER_UID"] = str(os.getuid() + 1)
        preflight = self.run_verifier("preflight", env=env)
        self.assertNotEqual(preflight.returncode, 0, preflight.stderr)
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("status=INCOMPLETE", (self.report / "latest.env").read_text())

    def test_unsafe_report_directory_mode_is_not_repaired_by_verifier(self) -> None:
        self.arm_then_reboot()
        authorization = self.report / "runtime" / "primary-execution.env"
        self.assertTrue(authorization.is_file())
        self.report.chmod(0o755)
        result = self.run_verifier("observe")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.report.stat().st_mode & 0o777, 0o755)
        self.assertFalse(authorization.exists())
        self.assertFalse(
            (self.report / "runtime" / ".primary-execution.observed.env").exists()
        )

    def test_empty_systemd_properties_are_incomplete_observations(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_MAPPER_ACTIVE"] = ""
        env["MOCK_MAPPER_RESULT"] = ""
        env["MOCK_SWAP_ACTIVE"] = ""
        env["MOCK_SWAP_RESULT"] = ""
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("status=INCOMPLETE", report)
        self.assertIn("mapper_service_state_unavailable", report)
        self.assertIn("primary_swap_unit_state_unavailable", report)

    def test_service_substate_contradictions_cannot_pass_observation(self) -> None:
        self.arm_then_reboot()
        for variable, value, status, reason in (
            ("MOCK_MAPPER_SUB", "dead", "FAIL", "mapper_service_sub_state_invalid"),
            ("MOCK_SWAP_SUB", "dead", "FAIL", "primary_swap_unit_sub_state_invalid"),
            ("MOCK_MAPPER_SUB", "", "INCOMPLETE", "mapper_service_sub_state_unavailable"),
            ("MOCK_SWAP_SUB", "", "INCOMPLETE", "primary_swap_unit_sub_state_unavailable"),
        ):
            with self.subTest(variable=variable, value=value):
                self.assertEqual(self.run_verifier("preflight").returncode, 0)
                env = self.env.copy()
                env[variable] = value
                observed = self.run_verifier("observe", env=env)
                self.assertEqual(observed.returncode, 1 if status == "FAIL" else 2,
                                 observed.stderr)
                report = (self.report / "latest.env").read_text(encoding="utf-8")
                self.assertIn(f"status={status}\n", report)
                self.assertIn(reason, report)
                self.assert_activation_revoked()

    def test_duplicate_and_missing_kernel_status_fields_are_incomplete(self) -> None:
        self.arm_then_reboot()
        valid = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0 window_gc_pressure=0"
        )
        for ambiguous in (
            valid.replace("swapz failed=0 ", "swapz failed=0 failed=1 "),
            valid.replace("error=0", "error=0 error=-5"),
            valid.replace("flush_err=0 ", ""),
            valid.replace("gc_destination_advances=0 ", ""),
            valid.replace("swapz failed=0 error=0 ",
                          "swapz failed=0 error=-2147483649 "),
            valid.replace("segment_discards_failed=0",
                          "segment_discards_failed=-1"),
            valid.replace("swapz failed=0 ", "swapz failed=1 failed=0 "),
            valid + "\nstatus=PASS",
            valid.replace("swapz", "linear", 1),
        ):
            with self.subTest(ambiguous=ambiguous[-55:]):
                env = self.env.copy()
                env["MOCK_DM_STATUS_OVERRIDE_SET"] = "1"
                env["MOCK_DM_STATUS_OVERRIDE"] = ambiguous
                # Every observation consumes/revokes the one-use preflight
                # authorization, including an INCOMPLETE result. Reissue it
                # before each independent malformed-status case.
                preflight = self.run_verifier("preflight")
                self.assertEqual(preflight.returncode, 0, preflight.stderr)
                observed = self.run_verifier("observe", env=env)
                self.assertEqual(observed.returncode, 2, observed.stderr)
                self.assertIn("status=INCOMPLETE", (self.report / "latest.env").read_text())
                self.assertFalse((self.report / "runtime" / "primary-execution.env").exists())
        env = self.env.copy()
        env["MOCK_DM_STATUS_OVERRIDE_SET"] = "1"
        env["MOCK_DM_STATUS_OVERRIDE"] = valid.replace("failed=0", "failed=1")
        failed = self.run_verifier("observe", env=env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("swapz_target_failed", (self.report / "latest.env").read_text())

    def test_sysfs_mapper_identity_must_match_boot_observation(self) -> None:
        self.arm_then_reboot()
        dm_name = self.sys / "dev" / "block" / "253:0" / "dm" / "name"
        dm_name.write_text("foreign-mapper\n", encoding="ascii")
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("mapper_sysfs_identity_mismatch", (self.report / "latest.env").read_text())

    def test_evidence_symlink_cannot_overwrite_or_leave_activation_token(self) -> None:
        self.arm_then_reboot()
        self.assertEqual(self.run_verifier("preflight").returncode, 0)
        activation_token = self.report / "runtime" / "primary-execution.env"
        self.assertTrue(activation_token.exists())
        sentinel = self.root / "outside-status"
        sentinel.write_text("protected\n", encoding="ascii")
        sentinel.chmod(0o600)
        destination = self.report / f"report-{BOOT_B}.dm-status.txt"
        destination.symlink_to(sentinel)
        rejected = self.run_verifier("observe")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(sentinel.read_text(encoding="ascii"), "protected\n")
        self.assertFalse(activation_token.exists())


    def assert_activation_revoked(self) -> None:
        """No failed admission or observation may retain execution authority."""
        for name in ("primary-execution.env", ".primary-execution.observed.env"):
            path = self.report / "runtime" / name
            self.assertFalse(
                path.exists() or path.is_symlink(),
                f"runtime authorization artifact was retained: {name}",
            )


    def test_interrupted_arming_cannot_leave_authority_or_arm_record(self) -> None:
        # Delay only a fake date command during the here-document build.
        # A private process group makes the injected signal strictly rootless.
        self.write_proc_swaps(active=False)
        date_started = self.root / "date-started"
        write_executable(
            self.bin / "date",
            "#!/bin/sh\n"
            'printf "started\\n" > "$MOCK_DATE_STARTED"\n'
            "exec sleep 15\n",
        )
        env = self.env.copy()
        env["MOCK_DATE_STARTED"] = str(date_started)
        verifier = subprocess.Popen(
            [str(self.sbin / "swapz-primary-boot-verify"), "arm"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 4
            while (not date_started.exists() and verifier.poll() is None
                   and time.monotonic() < deadline):
                time.sleep(0.02)
            self.assertTrue(date_started.exists(), "fixture did not enter arming")
            os.killpg(verifier.pid, signal.SIGTERM)
            stdout, stderr = verifier.communicate(timeout=5)
            self.assertNotEqual(verifier.returncode, 0, stderr)
            self.assertNotIn("COLD_BOOT_HARNESS=ARMED", stdout)
            self.assertFalse((self.report / "armed.env").exists())
            self.assert_activation_revoked()
        finally:
            if verifier.poll() is None:
                os.killpg(verifier.pid, signal.SIGKILL)
                verifier.communicate(timeout=5)

    def test_rearming_failure_revokes_previous_arm_and_runtime_token(self) -> None:
        self.arm_then_reboot()
        self.assertTrue((self.report / "runtime" / "primary-execution.env").exists())
        env = self.env.copy()
        env["MOCK_PLAN_STATUS"] = "1"
        rejected = self.run_verifier("arm", env=env)
        self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.assertIn("COLD_BOOT_HARNESS=BLOCKED", rejected.stderr)
        self.assertIn("cannot query read-only recovery storage plan", rejected.stderr)
        self.assertFalse((self.report / "armed.env").exists())
        self.assert_activation_revoked()
        # A staged arm record from an interrupted write has no authority.
        (self.report / ".armed.env.interrupted").write_text(
            "schema=swapz-primary-boot-arm-v1\n", encoding="ascii")
        unarmed = self.run_verifier("preflight")
        self.assertEqual(unarmed.returncode, 1, unarmed.stderr)
        self.assertIn("cold-boot harness is not securely armed", unarmed.stderr)
        self.assert_activation_revoked()

    def test_recovery_storage_unavailable_blocks_without_fallback(self) -> None:
        self.arm_then_reboot()
        self.recovery.rename(self.root / "disconnected-recovery")
        blocked = self.run_verifier("preflight")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("PRIMARY_BOOT_PREFLIGHT=BLOCKED", blocked.stderr)
        self.assertIn("primary recovery directory is unavailable", blocked.stderr)
        self.assert_activation_revoked()
        self.assertFalse((self.dev / "disk" / "by-partuuid" / OTHER_PARTUUID).is_symlink())

    def test_missing_recovery_storage_never_authorizes_observed_pass(self) -> None:
        self.arm_then_reboot()
        self.recovery.rename(self.root / "disconnected-recovery")
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        report = (self.report / "latest.env").read_text(encoding="utf-8")
        self.assertIn("status=FAIL\n", report)
        self.assertIn("recovery_storage_unavailable", report)
        self.assert_activation_revoked()

    def test_incomplete_package_journal_blocks_preflight_and_acceptance(self) -> None:
        self.arm_then_reboot()
        retained = self.package_transactions / "swapz-package.interrupted"
        retained.mkdir(mode=0o700)
        blocked = self.run_verifier("preflight")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("PRIMARY_BOOT_PREFLIGHT=BLOCKED", blocked.stderr)
        self.assertIn("incomplete package transaction", blocked.stderr)
        self.assert_activation_revoked()
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("incomplete_package_transaction",
                      (self.report / "latest.env").read_text())
        self.assert_activation_revoked()

    def test_module_qualification_and_running_kernel_are_independent_of_arm(self) -> None:
        for env_override, reason in (
            ({"MOCK_INSTALLED_MODULE_SHA": "f" * 64},
             "installed_module_hash_mismatch"),
            ({"MOCK_MODULE_VERMAGIC": "unqualified-kernel SMP"},
             "running kernel is unqualified"),
        ):
            with self.subTest(reason=reason):
                env = self.env.copy()
                env.update(env_override)
                self.write_proc_swaps(active=False)
                rejected = self.run_verifier("arm", env=env)
                self.assertEqual(rejected.returncode, 1, rejected.stderr)
                self.assertIn("COLD_BOOT_HARNESS=BLOCKED", rejected.stderr)
                self.assertIn(reason, rejected.stderr)
                self.assert_activation_revoked()

        # The root-owned marker must bind both source and kernel qualification.
        marker = self.qualification_marker.read_text(encoding="ascii")
        self.qualification_marker.write_text(
            marker.replace(f"source_sha={SOURCE_SHA}", "source_sha=" + "f" * 40),
            encoding="ascii",
        )
        self.write_proc_swaps(active=False)
        rejected = self.run_verifier("arm")
        self.assertEqual(rejected.returncode, 1, rejected.stderr)
        self.assertIn("qualified_package_marker_missing_or_invalid", rejected.stderr)
        self.assert_activation_revoked()

    def test_passive_mapper_swap_accidentally_enabled_blocks_all_admission(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_PASSIVE_ENABLEMENT"] = "enabled"
        blocked = self.run_verifier("preflight", env=env)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("passive mapper .swap is enabled", blocked.stderr)
        self.assertIn("PRIMARY_BOOT_PREFLIGHT=BLOCKED", blocked.stderr)
        self.assert_activation_revoked()
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("passive_swap_unit_enabled_or_uninspectable",
                      (self.report / "latest.env").read_text())
        self.assert_activation_revoked()

    def test_changed_selector_and_missing_media_never_pick_another_card(self) -> None:
        for scenario in ("selected_card_removed", "wrong_partuuid"):
            with self.subTest(scenario=scenario):
                self.write_boot_id(BOOT_A)
                self.arm_then_reboot()
                env = self.env.copy()
                if scenario == "selected_card_removed":
                    (self.dev / "disk" / "by-partuuid" / PARTUUID).unlink()
                    expected = "selected PARTUUID device is unavailable after reboot"
                else:
                    env["MOCK_PARTUUID"] = OTHER_PARTUUID
                    expected = "selected PARTUUID changed after arming"
                blocked = self.run_verifier("preflight", env=env)
                self.assertEqual(blocked.returncode, 1, blocked.stderr)
                self.assertIn(expected, blocked.stderr)
                self.assertIn("PRIMARY_BOOT_PREFLIGHT=BLOCKED", blocked.stderr)
                self.assert_activation_revoked()
                # Restore the same exact card fixture for the next subcase.
                if scenario == "selected_card_removed":
                    (self.dev / "disk" / "by-partuuid" / PARTUUID).touch()

    def test_forged_post_boot_pass_is_not_start_authorization(self) -> None:
        self.arm_then_reboot()
        self.assertTrue((self.report / "runtime" / "primary-execution.env").exists())
        (self.report / "runtime" / "primary-execution.env").unlink()
        # An attacker-controlled old report may say PASS but is never read as
        # an input to preflight or observation.
        (self.report / "latest.env").write_text(
            f"status=PASS\ncold_boot_observed=yes\nboot_id={BOOT_B}\n",
            encoding="ascii",
        )
        (self.report / "latest.env").chmod(0o600)
        observed = self.run_verifier("observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=FAIL", observed.stderr)
        self.assertIn("runtime_preflight_authorization_missing_or_invalid",
                      (self.report / "latest.env").read_text())
        self.assert_activation_revoked()

    def test_stale_mapper_geometry_uuid_and_missing_health_telemetry_deny_pass(self) -> None:
        scenarios = (
            ({"MOCK_DM_UUID": "SWAPZ-PRIMARY-" + "f" * 32},
             1, "mapper_uuid_not_bound_to_active_run"),
            ({"MOCK_DM_TABLE": "0 216641536 swapz 8:9 0 64 0 2 0 1 0 0"},
             1, "mapper_backing_identity_mismatch"),
            ({"MOCK_DM_STATUS_OVERRIDE_SET": "1",
              "MOCK_DM_STATUS_OVERRIDE": ""},
             2, "mapper_status_unavailable"),
        )
        for override, returncode, reason in scenarios:
            with self.subTest(reason=reason):
                self.write_boot_id(BOOT_A)
                self.arm_then_reboot()
                env = self.env.copy()
                env.update(override)
                observed = self.run_verifier("observe", env=env)
                self.assertEqual(observed.returncode, returncode, observed.stderr)
                self.assertIn(reason, (self.report / "latest.env").read_text())
                self.assert_activation_revoked()


    def test_preflight_refusal_revokes_activation_but_preserves_durable_evidence(self) -> None:
        self.arm_then_reboot()
        arm_file = self.report / "armed.env"
        saved_arm = arm_file.read_bytes()
        saved_records = {
            path.name: path.read_bytes()
            for path in self.recovery.iterdir()
            if path.is_file()
        }
        env = self.env.copy()
        env["MOCK_PARTUUID"] = OTHER_PARTUUID
        blocked = self.run_verifier("preflight", env=env)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("PRIMARY_BOOT_PREFLIGHT=BLOCKED", blocked.stderr)
        self.assertIn("selected PARTUUID changed after arming", blocked.stderr)
        self.assert_activation_revoked()
        self.assertEqual(arm_file.read_bytes(), saved_arm)
        self.assertEqual(
            {
                path.name: path.read_bytes()
                for path in self.recovery.iterdir()
                if path.is_file()
            },
            saved_records,
        )


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
                info)
                    if [ -n "${MOCK_DM_INFO_SEQUENCE_FILE:-}" ]; then
                        counter=0
                        if [ -f "$MOCK_DM_INFO_SEQUENCE_FILE" ]; then
                            IFS= read -r counter < "$MOCK_DM_INFO_SEQUENCE_FILE" || exit 2
                        fi
                        counter=$((counter + 1))
                        printf '%s\n' "$counter" > "$MOCK_DM_INFO_SEQUENCE_FILE" || exit 2
                        if [ "$counter" -eq 1 ]; then
                            printf ' \n'
                        else
                            printf 'SWAPZ-PRIMARY-bad\nsecond-line\n'
                        fi
                    else
                        printf '%s\n' "${MOCK_DM_UUID:-SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef}"
                    fi
                    exit "${MOCK_DM_INFO_EXIT_CODE:-0}"
                    ;;
                table) printf '0 216641536 swapz 8:1 0 64 0 2 0 1 0 0\n'; exit "${MOCK_DM_TABLE_EXIT_CODE:-0}" ;;
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
                    exit "${MOCK_DM_STATUS_EXIT_CODE:-0}"
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
                if [ "$1" = is-enabled ]; then
                    printf '%s\n' "${MOCK_PASSIVE_ENABLEMENT:-static}"
                    exit "${MOCK_PASSIVE_ENABLEMENT_EXIT:-0}"
                fi
                property=
                for argument in "$@"; do
                    case "$argument" in --property=*) property=${argument#--property=} ;; esac
                done
                case "$property" in
                LoadState) echo "${MOCK_SYSTEMD_LOAD_STATE:-loaded}" ;;
                ActiveState) echo "${MOCK_SYSTEMD_ACTIVE_STATE:-active}" ;;
                SubState)
                    case "$*" in
                    *swapz-primary-mapper.service)
                        [ "${MOCK_MAPPER_SUBSTATE_EXIT:-0}" = 0 ] || exit "$MOCK_MAPPER_SUBSTATE_EXIT"
                        echo "${MOCK_MAPPER_SUBSTATE:-exited}" ;;
                    *) echo "${MOCK_PASSIVE_SUBSTATE:-active}" ;;
                    esac ;;
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


    def test_enabled_passive_unit_is_failure_even_if_monitor_runs(self) -> None:
        env = self.env.copy()
        env["MOCK_PASSIVE_ENABLEMENT"] = "enabled"
        once = self.run_helper("once", env)
        self.assertEqual(once.returncode, 1, once.stderr)
        self.assertIn("passive_swap_unit_enabled", once.stderr)
        monitor = self.run_helper("monitor", env)
        self.assertEqual(monitor.returncode, 0, monitor.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", monitor.stderr)

    def test_failed_normal_swapoff_is_observed_without_a_retry(self) -> None:
        # A failed manager stop can leave /proc/swaps and the mapper alive;
        # no helper may invoke physical swapoff or synthesize a recovery.
        observed = self.run_helper("stop-observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_STOP=FAIL", observed.stderr)
        self.assertIn("reason=swap_or_mapper_still_present", observed.stderr)
        self.assertIn("action=none operator_next=inspect_failed_primary_stop_no_retry", observed.stderr)
        self.assertIn("mapper_present=1", observed.stderr)
        self.assertIn("active_swap=1", observed.stderr)
        helper = read_text(RUNTIME_HEALTH)
        self.assertNotRegex(helper, r"(^|[^A-Za-z])swapoff([^A-Za-z]|$)")
        self.assertNotIn("dmsetup remove", helper)

    def test_healthy_snapshot_reports_capacity_and_identity(self) -> None:
        result = self.run_helper("once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", result.stderr)
        self.assertIn("swap_remaining_kib=", result.stderr)
        self.assertIn(f"mapper_uuid=SWAPZ-PRIMARY-{ACTIVE_RUN_ID}", result.stderr)

    def test_contradictory_service_substates_are_failures(self) -> None:
        # ActiveState=active and Result=success cannot prove a live oneshot
        # mapper or a passive swap unit when their substates disagree.
        for variable, reason, phase in (
            ("MOCK_MAPPER_SUBSTATE", "mapper_service_substate_invalid", "mapper_service_substate"),
            ("MOCK_PASSIVE_SUBSTATE", "passive_swap_unit_substate_invalid", "passive_swap_unit_substate"),
        ):
            with self.subTest(variable=variable):
                env = self.env.copy()
                env[variable] = "dead"
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 1, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
                self.assertIn(reason, observed.stderr)
                self.assertIn(f"phase={phase} expected=", observed.stderr)
                self.assertIn("observed=incompatible_substate", observed.stderr)
                self.assertIn(
                    "command_status=0 identity_mismatch=none service_state=observed",
                    observed.stderr,
                )

    def test_malformed_substate_is_observed_incomplete_telemetry(self) -> None:
        for variable, value, reason, phase in (
            (
                "MOCK_MAPPER_SUBSTATE",
                "exited\nstale",
                "mapper_service_substate_telemetry_invalid",
                "mapper_service_substate",
            ),
            (
                "MOCK_PASSIVE_SUBSTATE",
                "active\nstale",
                "passive_swap_unit_substate_telemetry_invalid",
                "passive_swap_unit_substate",
            ),
        ):
            with self.subTest(variable=variable):
                env = self.env.copy()
                env[variable] = value
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 2, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
                self.assertIn(reason, observed.stderr)
                self.assertIn(f"phase={phase} expected=", observed.stderr)
                self.assertIn(
                    "observed=invalid_output command=systemctl_show command_status=0 "
                    "identity_mismatch=none service_state=observed",
                    observed.stderr,
                )

    def test_passive_enablement_state_must_match_systemctl_exit(self) -> None:
        # systemctl is-enabled intentionally returns 1 for "disabled", while
        # "static" returns 0. A mismatched pair is incomplete telemetry.
        disabled_env = self.env.copy()
        disabled_env["MOCK_PASSIVE_ENABLEMENT"] = "disabled"
        disabled_env["MOCK_PASSIVE_ENABLEMENT_EXIT"] = "1"
        disabled = self.run_helper("once", disabled_env)
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", disabled.stderr)

        for state, exit_code in (("static", "41"), ("disabled", "124")):
            with self.subTest(state=state, exit_code=exit_code):
                env = self.env.copy()
                env["MOCK_PASSIVE_ENABLEMENT"] = state
                env["MOCK_PASSIVE_ENABLEMENT_EXIT"] = exit_code
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 2, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
                self.assertIn("passive_swap_enablement_unavailable", observed.stderr)
                self.assertNotIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", observed.stderr)
                self.assertIn(
                    "phase=passive_swap_enablement expected=static_or_disabled "
                    "observed=inconsistent_or_invalid command=systemctl_is_enabled "
                    f"command_status={exit_code} identity_mismatch=none "
                    "service_state=observed",
                    observed.stderr,
                )

    def test_unavailable_substate_keeps_original_systemctl_exit(self) -> None:
        env = self.env.copy()
        env["MOCK_MAPPER_SUBSTATE_EXIT"] = "37"
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertIn("mapper_service_substate_unavailable", observed.stderr)
        self.assertIn(
            "phase=mapper_service_substate expected=exited observed=probe_failed",
            observed.stderr,
        )
        self.assertIn(
            "command_status=37 identity_mismatch=none service_state=inferred",
            observed.stderr,
        )

    def test_probe_output_after_nonzero_status_never_passes_as_healthy(self) -> None:
        # A plausible partial response followed by an error previously passed,
        # including through the old dmsetup info -> awk pipeline.
        for variable, phase, exit_code, verdict, reason in (
            ("MOCK_DM_INFO_EXIT_CODE", "mapper_info", "17", 2,
             "mapper_uuid_unavailable"),
            ("MOCK_DM_TABLE_EXIT_CODE", "mapper_table", "18", 2,
             "mapper_table_unavailable"),
            ("MOCK_DM_STATUS_EXIT_CODE", "mapper_status", "19", 2,
             "mapper_status_unavailable"),
        ):
            with self.subTest(phase=phase):
                env = self.env.copy()
                env[variable] = exit_code
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, verdict, observed.stderr)
                self.assertIn(reason, observed.stderr)
                self.assertNotIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", observed.stderr)
                self.assertIn(f"phase={phase} ", observed.stderr)
                self.assertIn(f"command_status={exit_code} ", observed.stderr)
                self.assertIn("next=inspect_dmsetup_", observed.stderr)
                if variable == "MOCK_DM_INFO_EXIT_CODE":
                    self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
                    self.assertNotIn("mapper_uuid_not_bound_to_active_run", observed.stderr)

    def test_empty_dm_info_is_incomplete_not_identity_failure(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_UUID"] = " "
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertIn("mapper_uuid_unavailable", observed.stderr)
        self.assertNotIn("mapper_uuid_not_bound_to_active_run", observed.stderr)
        self.assertIn("phase=mapper_info expected=run_bound_uuid observed=missing_uuid", observed.stderr)
        self.assertIn("command_status=0", observed.stderr)
        self.assertIn("next=inspect_dmsetup_info_read_only", observed.stderr)

    def test_literal_unavailable_dm_uuid_is_observed_identity_failure(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_UUID"] = "unavailable"
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
        self.assertIn("mapper_uuid_invalid", observed.stderr)
        self.assertIn("mapper_uuid_not_bound_to_active_run", observed.stderr)
        self.assertIn(
            "phase=mapper_identity expected=run_bound_uuid observed=mismatched_uuid "
            "command=dmsetup_info command_status=0",
            observed.stderr,
        )

    def test_multiline_dm_info_is_incomplete_not_identity_failure(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_UUID"] = "SWAPZ-PRIMARY-bad\nsecond-line"
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertIn("mapper_uuid_unavailable", observed.stderr)
        self.assertNotIn("mapper_uuid_invalid", observed.stderr)
        self.assertNotIn("mapper_uuid_not_bound_to_active_run", observed.stderr)
        self.assertIn(
            "phase=mapper_info expected=run_bound_uuid observed=invalid_output "
            "command=dmsetup_info command_status=0",
            observed.stderr,
        )
        self.assertIn("next=inspect_dmsetup_info_read_only", observed.stderr)

    def test_extra_raw_backing_swap_row_fails_runtime_health(self) -> None:
        # The expected mapper row cannot hide an active selected raw partition.
        with (self.proc / "swaps").open("a", encoding="ascii") as inventory:
            inventory.write(
                f"{self.dev / 'disk' / 'by-partuuid' / PARTUUID} "
                "partition 10000 12 -2\n"
            )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("raw_backing_swap_active", observed.stderr)
        self.assertIn("observed=raw_backing_active", observed.stderr)
        self.assertIn("command_status=0", observed.stderr)

    def test_extra_unresolved_block_swap_alias_degrades_runtime_health(self) -> None:
        # This second row was ignored even while the hibernation guard
        # correctly refused to use it as evidence of inactive swapz.
        with (self.proc / "swaps").open("a", encoding="ascii") as inventory:
            inventory.write("/dev/dm-7 partition 10000 12 -2\n")
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertIn("swap_block_identity_unavailable", observed.stderr)
        self.assertIn("phase=swap_inventory ", observed.stderr)
        self.assertIn("observed=unresolved_block_alias", observed.stderr)
        self.assertIn("command_status=1", observed.stderr)
        self.assertNotIn("/dev/dm-7", observed.stderr)
        self.assertEqual(self.run_helper("hibernate-guard").returncode, 1)

    def test_swap_alias_sysfs_identity_cannot_change_health_to_false_pass(self) -> None:
        write_executable(
            self.bin / "lsblk",
            "#!/bin/sh\n"
            '[ "$2" = MAJ:MIN ] || exit 1\n'
            'case "$4" in\n'
            '  */disk/by-partuuid/*) echo 8:1 ;;\n'
            '  */mapper/swapz-primary) echo 253:0 ;;\n'
            '  /dev/dm-7) echo 253:7 ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n',
        )
        with (self.proc / "swaps").open("a", encoding="ascii") as inventory:
            inventory.write("/dev/dm-7 partition 10000 12 -2\n")
        # A captured major:minor without inspectable sysfs remains incomplete.
        missing = self.run_helper("once")
        self.assertEqual(missing.returncode, 2, missing.stderr)
        self.assertIn("observed=uninspectable_dm_alias", missing.stderr)

        dm_name = self.sys / "dev" / "block" / "253:7" / "dm" / "name"
        dm_name.parent.mkdir(parents=True)
        dm_name.write_text("unrelated\n", encoding="ascii")
        unrelated = self.run_helper("once")
        self.assertEqual(unrelated.returncode, 0, unrelated.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", unrelated.stderr)

        dm_name.write_text("swapz-primary\n", encoding="ascii")
        conflicting = self.run_helper("once")
        self.assertEqual(conflicting.returncode, 1, conflicting.stderr)
        self.assertIn("conflicting_swap_mapper_identity", conflicting.stderr)
        self.assertIn("observed=conflicting_dm_identity", conflicting.stderr)

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

    def test_missing_target_terminal_state_is_not_reported_healthy(self) -> None:
        valid_status = (
            "0 216641536 swapz failed=0 error=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0"
        )
        for omitted_field in ("failed=0 ", "error=0 "):
            with self.subTest(omitted_field=omitted_field):
                env = self.env.copy()
                env["MOCK_DM_STATUS"] = valid_status.replace(omitted_field, "")
                result = self.run_helper("once", env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
                self.assertIn("target_failure_state_unavailable", result.stderr)

        for original, malformed_value in (
            ("failed=0", "failed=2"),
            ("failed=0", "failed=not-a-number"),
            ("error=0", "error=-0"),
            ("error=0", "error=1"),
            ("error=0", "error=2147483647"),
            ("error=0", "error=2147483648"),
            ("error=0", "error=-4096"),
            ("error=0", "error=-2147483649"),
            ("error=0", "error=12junk"),
            ("error=0", "error=not-a-number"),
        ):
            with self.subTest(malformed_value=malformed_value):
                env = self.env.copy()
                env["MOCK_DM_STATUS"] = valid_status.replace(
                    original, malformed_value
                )
                malformed = self.run_helper("once", env)
                self.assertEqual(malformed.returncode, 2, malformed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", malformed.stderr)
                self.assertIn("target_failure_state_invalid", malformed.stderr)
                self.assertNotIn("failures=target_failed", malformed.stderr)
                self.assertNotIn("failures=first_terminal_error", malformed.stderr)
                self.assertNotIn("phase=target_terminal ", malformed.stderr)

        env = self.env.copy()
        env["MOCK_DM_STATUS"] = valid_status.replace("failed=0", "failed=1")
        failed = self.run_helper("once", env)
        self.assertEqual(failed.returncode, 1, failed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", failed.stderr)
        self.assertIn("failures=target_failed", failed.stderr)
        self.assertIn("failed=1", failed.stderr)
        self.assertNotIn("phase=target_terminal ", failed.stderr)

        # swapz_fail_at() publishes canonical Linux errno values.
        for valid_error in ("-5", "-4095"):
            with self.subTest(valid_error=valid_error):
                env["MOCK_DM_STATUS"] = valid_status.replace(
                    "error=0", f"error={valid_error}"
                )
                terminal_error = self.run_helper("once", env)
                self.assertEqual(terminal_error.returncode, 1, terminal_error.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", terminal_error.stderr)
                self.assertIn("failures=first_terminal_error", terminal_error.stderr)
                self.assertIn(f"first_error={valid_error}", terminal_error.stderr)
                self.assertIn(
                    f"phase=target_terminal expected=first_error_zero "
                    f"observed={valid_error} command=dmsetup_status "
                    "command_status=0 identity_mismatch=none "
                    "service_state=observed "
                    "next=inspect_dmsetup_status_read_only check=first_error",
                    terminal_error.stderr,
                )

        env["MOCK_DM_STATUS"] = valid_status.replace(
            "failed=0 error=0", "failed=1 error=1"
        )
        contradictory = self.run_helper("once", env)
        self.assertEqual(contradictory.returncode, 1, contradictory.stderr)
        self.assertIn("failures=target_failed", contradictory.stderr)
        self.assertIn("target_failure_state_invalid", contradictory.stderr)
        self.assertNotIn("failures=first_terminal_error", contradictory.stderr)
        self.assertNotIn("phase=target_terminal ", contradictory.stderr)

    def test_mapper_device_alias_requires_the_expected_sysfs_dm_name(self) -> None:
        # A substituted mapper alias can match raw backing swap accounting,
        # while dmsetup still finds a different object by its mapper name.
        write_executable(
            self.bin / "lsblk",
            "#!/bin/sh\n"
            '[ "$2" = MAJ:MIN ] || exit 1\n'
            'case "$4" in\n'
            '  */disk/by-partuuid/*|*/mapper/swapz-primary) echo 8:1 ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n',
        )
        substituted = self.run_helper("once")
        self.assertEqual(substituted.returncode, 1, substituted.stderr)
        self.assertIn("mapper_device_identity_invalid", substituted.stderr)
        self.assertNotIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", substituted.stderr)

    def test_foreign_sysfs_dm_name_is_not_accepted(self) -> None:
        (self.sys / "dev" / "block" / "253:0" / "dm" / "name").write_text(
            "foreign-mapper\n", encoding="ascii"
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("mapper_device_identity_invalid", observed.stderr)

    def test_ambiguous_dm_status_is_incomplete_not_terminal(self) -> None:
        valid_status = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0 window_gc_pressure=0"
        )
        for malformed in (
            valid_status + "\n" + valid_status.replace("failed=0", "failed=1"),
            valid_status.replace("failed=0", "failed=0 failed=1"),
            valid_status.replace("error=0", "error=0 error=-5"),
            valid_status.replace("error=0", "error=0=corrupt"),
        ):
            with self.subTest(malformed=malformed):
                env = self.env.copy()
                env["MOCK_DM_STATUS"] = malformed
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 2, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
                self.assertIn("observation_errors=", observed.stderr)
                self.assertNotIn("failures=target_failed", observed.stderr)
                self.assertNotIn("failures=first_terminal_error", observed.stderr)

    def test_missing_gc_progress_is_incomplete(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS"] = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0"
        )
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("gc_progress_telemetry_unavailable", observed.stderr)

    def test_unavailable_systemd_state_is_incomplete_but_inactive_is_failure(self) -> None:
        write_executable(self.bin / "systemctl", "#!/bin/sh\nexit 1\n")
        incomplete = self.run_helper("once")
        self.assertEqual(incomplete.returncode, 2, incomplete.stderr)
        self.assertIn("mapper_service_state_unavailable", incomplete.stderr)
        self.assertNotIn("mapper_service_not_active", incomplete.stderr)

        write_executable(
            self.bin / "systemctl",
            '#!/bin/sh\n'
            'case "$*" in\n'
            '  *--property=ActiveState*) echo inactive ;;\n'
            '  *--property=SubState*) echo dead ;;\n'
            '  *--property=Result*) echo success ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n',
        )
        inactive = self.run_helper("once")
        self.assertEqual(inactive.returncode, 1, inactive.stderr)
        self.assertIn("mapper_service_not_active", inactive.stderr)

    def test_malformed_unsigned_status_counter_is_degraded(self) -> None:
        base_status = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0 window_gc_pressure=0"
        )
        for malformed_flush in ("flush_err=-1", "flush_err=12junk"):
            with self.subTest(malformed_flush=malformed_flush):
                env = self.env.copy()
                env["MOCK_DM_STATUS"] = base_status.replace(
                    "flush_err=0", malformed_flush
                )
                result = self.run_helper("once", env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", result.stderr)
                self.assertIn("dm_status_counter_invalid", result.stderr)

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

    def test_monitor_logs_dm_info_observation_shape_changes(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_INFO_SEQUENCE_FILE"] = str(self.root / "dm-info-sequence")
        env["SWAPZ_PRIMARY_TEST_MAX_POLLS"] = "2"
        result = self.run_helper("monitor", env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("SWAPZ_RUNTIME_HEALTH=DEGRADED"), 2)
        self.assertEqual(result.stderr.count("observed=missing_uuid"), 1)
        self.assertEqual(result.stderr.count("observed=invalid_output"), 1)

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



    def test_primary_swap_requires_partition_type_and_priority_minus_one(self) -> None:
        # The inventory parser accepts integer priorities; health must check
        # the manager's actual -1 activation contract, not just row presence.
        primary_path = self.dev / "mapper" / "swapz-primary"
        for swap_type, priority, reason, phase in (
            ("partition", "42", "mapper_swap_priority_invalid", "swap_inventory_priority"),
            ("file", "-1", "mapper_swap_type_invalid", "swap_inventory_type"),
        ):
            with self.subTest(swap_type=swap_type, priority=priority):
                (self.proc / "swaps").write_text(
                    "Filename Type Size Used Priority\n"
                    f"{primary_path} {swap_type} 108320764 1024 {priority}\n",
                    encoding="ascii",
                )
                observed = self.run_helper("once")
                self.assertEqual(observed.returncode, 1, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
                self.assertIn(reason, observed.stderr)
                self.assertIn(f"phase={phase} expected=", observed.stderr)
                self.assertIn("command=read_swap_inventory command_status=0", observed.stderr)
                self.assertIn("next=inspect_proc_swaps_read_only", observed.stderr)
                self.assertNotIn(str(self.recovery), observed.stderr)
                self.assertNotIn(str(self.etc), observed.stderr)

        # Unrelated host swapfiles are not subject to the primary priority.
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{primary_path} partition 108320764 1024 -1\n"
            "/swapfile file 10000 12 42\n",
            encoding="ascii",
        )
        healthy = self.run_helper("once")
        self.assertEqual(healthy.returncode, 0, healthy.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", healthy.stderr)

    def test_primary_swap_capacity_must_match_dm_geometry(self) -> None:
        # A complete-looking mapper row with the wrong usable size used to
        # report HEALTHY even though the DM table proved a different capacity.
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'} partition 10000 2000 -1\n",
            encoding="ascii",
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
        self.assertIn("mapper_swap_capacity_invalid", observed.stderr)
        self.assertIn(
            "phase=swap_inventory_capacity expected=dm_geometry_minus_4kib_header "
            "observed=unexpected_capacity command=read_swap_inventory "
            "command_status=0 identity_mismatch=none service_state=observed "
            "next=inspect_proc_swaps_and_dm_table_read_only",
            observed.stderr,
        )

    def test_wrong_primary_priority_survives_a_healthy_second_inventory_read(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'} partition 108320764 1024 42\n",
            encoding="ascii",
        )
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$2" = MAJ:MIN ] || exit 1
                case "$4" in
                */disk/by-partuuid/*) echo 8:1 ;;
                */mapper/swapz-primary)
                    count=0
                    counter_file="$SWAPZ_PRIMARY_TEST_PROC_ROOT/mapper-probe-count"
                    if [ -f "$counter_file" ]; then
                        IFS= read -r count < "$counter_file" || exit 2
                    fi
                    count=$((count + 1))
                    printf '%s\n' "$count" > "$counter_file" || exit 2
                    if [ "$count" -eq 2 ]; then
                        printf 'Filename Type Size Used Priority\n%s/mapper/swapz-primary partition 108320764 1024 -1\n' \
                            "$SWAPZ_PRIMARY_TEST_DEV_ROOT" > "$SWAPZ_PRIMARY_TEST_PROC_ROOT/swaps"
                    fi
                    echo 253:0
                    ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("mapper_swap_priority_invalid", observed.stderr)
        self.assertIn("swap_inventory_changed_during_observation", observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
        self.assertIn(
            "phase=swap_inventory_stability expected=stable_complete_inventory "
            "observed=changed_during_observation",
            observed.stderr,
        )
        self.assertIn(" 108320764 1024 -1\n", (self.proc / "swaps").read_text())

    def test_tab_delimited_swap_inventory_tracks_real_occupancy(self) -> None:
        # /proc/swaps uses tab-separated fields and may omit name padding
        # when the source pathname is long.
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'}\tpartition\t108320764\t2000\t-1\n",
            encoding="ascii",
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", observed.stderr)
        self.assertIn("swap_used_kib=2000", observed.stderr)
        self.assertIn("swap_remaining_kib=108318764", observed.stderr)
        self.assertEqual(self.run_helper("hibernate-guard").returncode, 1)

    def test_duplicate_or_impossible_unrelated_swap_rows_are_not_healthy(self) -> None:
        mapper_row = (
            f"{self.dev / 'mapper' / 'swapz-primary'} "
            "partition 108320764 1024 -1\n"
        )
        for extra_rows in (
            "/swapfile file 10000 12 -2\n/swapfile file 10000 12 -2\n",
            "/swapfile file 10000 10001 -2\n",
        ):
            with self.subTest(extra_rows=extra_rows):
                (self.proc / "swaps").write_text(
                    "Filename Type Size Used Priority\n" + mapper_row + extra_rows,
                    encoding="ascii",
                )
                observed = self.run_helper("once")
                self.assertEqual(observed.returncode, 2, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
                self.assertIn(
                    "swap_inventory_unavailable_or_invalid", observed.stderr
                )
                self.assertIn("phase=swap_inventory ", observed.stderr)
                self.assertIn("observed=unavailable_or_invalid", observed.stderr)
                self.assertIn("command_status=2 ", observed.stderr)

    def test_changing_swap_inventory_cannot_report_healthy(self) -> None:
        unrelated_sysfs = self.sys / "dev" / "block" / "8:7"
        unrelated_sysfs.mkdir(parents=True)
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'} "
            "partition 108320764 1024 -1\n"
            "/dev/disk/by-id/changing-swap partition 10000 12 -2\n",
            encoding="ascii",
        )
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$2" = MAJ:MIN ] || exit 1
                case "$4" in
                */disk/by-partuuid/*) echo 8:1 ;;
                */mapper/swapz-primary) echo 253:0 ;;
                /dev/disk/by-id/changing-swap)
                    printf 'Filename Type Size Used Priority\n%s/mapper/swapz-primary partition 108320764 1024 -1\n' \
                        "$SWAPZ_PRIMARY_TEST_DEV_ROOT" > "$SWAPZ_PRIMARY_TEST_PROC_ROOT/swaps"
                    echo 8:7
                    ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertIn("swap_inventory_changed_during_observation", observed.stderr)
        self.assertIn("phase=swap_inventory_stability ", observed.stderr)
        self.assertIn("observed=changed_during_observation", observed.stderr)
        self.assertIn("command_status=0 ", observed.stderr)
        self.assertIn("next=repeat_read_only_observation", observed.stderr)

    def test_swap_usage_change_during_observation_is_not_inventory_churn(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            f"{self.dev / 'mapper' / 'swapz-primary'} "
            "partition 108320764 1024 -1\n"
            "/swapfile file 10000 12 -2\n",
            encoding="ascii",
        )
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$2" = MAJ:MIN ] || exit 1
                case "$4" in
                */disk/by-partuuid/*) echo 8:1 ;;
                */mapper/swapz-primary) echo 253:0 ;;
                /swapfile)
                    printf 'Filename Type Size Used Priority\n%s/mapper/swapz-primary partition 108320764 2048 -1\n/swapfile file 10000 13 -2\n' \
                        "$SWAPZ_PRIMARY_TEST_DEV_ROOT" > "$SWAPZ_PRIMARY_TEST_PROC_ROOT/swaps"
                    exit 1
                    ;;
                *) exit 1 ;;
                esac
                """
            ),
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=HEALTHY", observed.stderr)
        self.assertNotIn("swap_inventory_changed_during_observation", observed.stderr)

    def test_changing_swap_inventory_cannot_prove_hibernation_inactive(self) -> None:
        (self.etc / "swapz" / "primary-target").unlink()
        (self.dev / "mapper" / "swapz-primary").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        unrelated_sysfs = self.sys / "dev" / "block" / "8:7"
        unrelated_sysfs.mkdir(parents=True)
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            "/dev/disk/by-id/changing-swap partition 10000 12 -2\n",
            encoding="ascii",
        )
        write_executable(
            self.bin / "lsblk",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$2" = MAJ:MIN ] || exit 1
                [ "$4" = /dev/disk/by-id/changing-swap ] || exit 1
                printf 'Filename Type Size Used Priority\n' \
                    > "$SWAPZ_PRIMARY_TEST_PROC_ROOT/swaps"
                echo 8:7
                """
            ),
        )
        blocked = self.run_helper("hibernate-guard")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("cannot prove swapz-primary inactive", blocked.stderr)

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

    def test_unconfigured_uninspectable_dm_alias_refuses_hibernate(self) -> None:
        # lsblk can resolve major:minor after a DM alias becomes uninspectable;
        # unavailable sysfs mapper-name evidence must not prove it unrelated.
        (self.etc / "swapz" / "primary-target").unlink()
        (self.dev / "mapper" / "swapz-primary").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        write_executable(
            self.bin / "lsblk",
            '#!/bin/sh\n[ "$2" = MAJ:MIN ] && [ "$4" = /dev/dm-7 ] && echo 253:7\n',
        )
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n"
            "/dev/dm-7\tpartition\t10000\t2000\t-1\n",
            encoding="ascii",
        )
        blocked = self.run_helper("hibernate-guard")
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("cannot prove swapz-primary inactive", blocked.stderr)

    def test_unconfigured_by_id_dm_alias_requires_inspectable_identity(self) -> None:
        (self.etc / "swapz" / "primary-target").unlink()
        (self.dev / "mapper" / "swapz-primary").unlink()
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        write_executable(
            self.bin / "lsblk",
            "#!/bin/sh\n"
            '[ "$2" = MAJ:MIN ] || exit 1\n'
            '[ "$4" = /dev/disk/by-id/opaque-swap ] || exit 1\n'
            'printf "%s\\n" "$MOCK_ALIAS_MAJOR_MINOR"\n',
        )
        (self.proc / "swaps").write_text(
            "Filename Type Size Used Priority\n"
            "/dev/disk/by-id/opaque-swap partition 10000 2000 -1\n",
            encoding="ascii",
        )
        env = self.env.copy()

        # Bind ambiguity to the captured 253:7 object. The alias itself is
        # never re-resolved to infer a later kernel name.
        dm_dir = self.sys / "dev" / "block" / "253:7" / "dm"
        dm_dir.mkdir(parents=True)
        env["MOCK_ALIAS_MAJOR_MINOR"] = "253:7"
        blocked = self.run_helper("hibernate-guard", env)
        self.assertEqual(blocked.returncode, 1, blocked.stderr)
        self.assertIn("cannot prove swapz-primary inactive", blocked.stderr)

        shutil.rmtree(self.sys / "dev" / "block" / "253:7")
        (self.sys / "dev" / "block" / "8:7").mkdir(parents=True)
        env["MOCK_ALIAS_MAJOR_MINOR"] = "8:7"
        allowed = self.run_helper("hibernate-guard", env)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

        # A resolved major:minor without its captured sysfs object is still
        # ambiguous and must never become hibernation-safe.
        shutil.rmtree(self.sys / "dev" / "block" / "8:7")
        ambiguous = self.run_helper("hibernate-guard", env)
        self.assertEqual(ambiguous.returncode, 1, ambiguous.stderr)

        # A dangling sysfs device link is not an existing captured identity.
        block_link = self.sys / "dev" / "block" / "8:7"
        block_link.symlink_to(self.root / "missing-sysfs-device")
        dangling = self.run_helper("hibernate-guard", env)
        self.assertEqual(dangling.returncode, 1, dangling.stderr)

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

        for malformed_partuuid in ("1234---5678", "1234-567"):
            (self.proc / "cmdline").write_text(
                f"quiet resume=PARTUUID={malformed_partuuid}\n", encoding="ascii"
            )
            malformed = self.run_helper("hibernation-config-check")
            self.assertEqual(malformed.returncode, 1, malformed.stderr)
            self.assertIn(
                f"unresolved:PARTUUID={malformed_partuuid}", malformed.stderr
            )

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
        self.assertIn("phase=mapper_status ", observed.stderr)
        self.assertIn("command_status=124 ", observed.stderr)

    def test_unreadable_kernel_cmdline_blocks_resume_admission(self) -> None:
        (self.proc / "swaps").write_text(
            "Filename\tType\tSize\tUsed\tPriority\n", encoding="ascii"
        )
        (self.proc / "cmdline").unlink()
        configured = self.run_helper("hibernation-config-check")
        self.assertEqual(configured.returncode, 1)
        self.assertIn("kernel-cmdline:unavailable", configured.stderr)
        self.assertEqual(self.run_helper("hibernate-guard").returncode, 1)

    def test_runtime_identity_rejects_noncanonical_manager_unit_encoding(self) -> None:
        write_executable(
            self.sbin / "swapzctl",
            "#!/bin/sh\n"
            "[ \"$1\" = primary ] && [ \"$2\" = systemd-units ] || exit 2\n"
            "printf '%s\\n' "
            "'dev-disk-by\\x2dpartuuid-01234567-89abcdef.device "
            "dev-disk-by\\x2dpartuuid-01234567-89abcdef.swap'\n",
        )
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("selected_target_identity_unavailable", observed.stderr)

    def test_live_mapper_without_selected_authority_is_failure(self) -> None:
        write_executable(self.sbin / "swapzctl", "#!/bin/sh\nexit 2\n")
        observed = self.run_helper("once")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("selected_target_identity_unavailable", observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)

    def test_kernel_diagnostic_does_not_print_private_journal_paths(self) -> None:
        env = self.env.copy()
        env["MOCK_JOURNAL"] = (
            "DM-SWAPZ: lower read error at "
            "/var/lib/swapz/physical-recovery/private-transaction "
            "/etc/swapz/primary-target\n"
        )
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=WARN", observed.stderr)
        self.assertIn("kernel_error_count=1", observed.stderr)
        self.assertIn(
            "phase=kernel_log expected=no_relevant_kernel_errors "
            "observed=relevant_kernel_errors command=journalctl command_status=0 "
            "identity_mismatch=none service_state=observed "
            "next=inspect_kernel_journal_read_only",
            observed.stderr,
        )
        self.assertNotIn("/var/lib/swapz/physical-recovery", observed.stderr)
        self.assertNotIn("/etc/swapz/primary-target", observed.stderr)
        self.assertNotIn("lower read error", observed.stderr)

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



    def test_full_dm_table_grammar_and_status_geometry_are_enforced(self) -> None:
        write_executable(
            self.bin / "dmsetup",
            "#!/bin/sh\n"
            'case "$1" in\n'
            'info) echo SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef ;;\n'
            'table) printf "%s\\n" "$MOCK_DM_TABLE" ;;\n'
            'status) printf "%s\\n" "$MOCK_DM_STATUS" ;;\n'
            '*) exit 2 ;;\n'
            'esac\n',
        )
        valid_status = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0 window_gc_pressure=0"
        )
        env = self.env.copy()
        env["MOCK_DM_STATUS"] = valid_status
        for malformed in (
            "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0 extra",
            "0 216641536 swapz 8:1 0 64 0 2 0 1 0 1",
        ):
            with self.subTest(table=malformed):
                env["MOCK_DM_TABLE"] = malformed
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 1, observed.stderr)
                self.assertIn("mapper_table_invalid", observed.stderr)
        env["MOCK_DM_TABLE"] = "0 216641536 swapz 8:1 0 64 0 2 0 1 0 0"
        env["MOCK_DM_STATUS"] = valid_status.replace(
            "0 216641536 swapz", "0 216641528 swapz", 1
        )
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
        self.assertIn("mapper_status_geometry_invalid", observed.stderr)
        self.assertIn("phase=mapper_status_geometry expected=matching_dm_table_geometry", observed.stderr)
        self.assertIn("observed=contradictory_geometry command=dmsetup_status command_status=0", observed.stderr)
        self.assertIn("next=inspect_dmsetup_table_and_status_read_only", observed.stderr)

    def test_complete_contradictory_dm_status_is_definite_failure(self) -> None:
        valid_status = (
            "0 216641536 swapz failed=0 error=0 flush_err=0 "
            "segment_discards_failed=0 upper_write_completed_err=0 "
            "endio_write_seen_err=0 endio_write_forced_err=0 "
            "gc_victims=5 gc_pages=20 gc_no_headroom_skips=0 "
            "gc_reserve_segments_initial=2 gc_reserve_segments_current=2 "
            "gc_destination_advances=0 window_gc_pressure=0"
        )
        for header, reason, phase in (
            ("1 216641536 swapz", "mapper_status_geometry_invalid", "mapper_status_geometry"),
            ("0 0 swapz", "mapper_status_geometry_invalid", "mapper_status_geometry"),
            ("0 216641536 linear", "mapper_status_target_invalid", "mapper_status_target"),
        ):
            with self.subTest(header=header):
                env = self.env.copy()
                env["MOCK_DM_STATUS"] = valid_status.replace("0 216641536 swapz", header, 1)
                observed = self.run_helper("once", env)
                self.assertEqual(observed.returncode, 1, observed.stderr)
                self.assertIn("SWAPZ_RUNTIME_HEALTH=FAIL", observed.stderr)
                self.assertIn(reason, observed.stderr)
                self.assertIn(f"phase={phase} expected=", observed.stderr)
                self.assertIn("command=dmsetup_status command_status=0", observed.stderr)
                self.assertIn("next=inspect_dmsetup_", observed.stderr)

    def test_missing_dm_status_is_degraded_not_terminal_failure(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS_UNAVAILABLE"] = "1"
        observed = self.run_helper("once", env)
        self.assertEqual(observed.returncode, 2, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", observed.stderr)
        self.assertNotIn("failures=target_failed", observed.stderr)


    def test_monitor_process_success_does_not_turn_missing_kernel_status_healthy(self) -> None:
        env = self.env.copy()
        env["MOCK_DM_STATUS_UNAVAILABLE"] = "1"
        # The monitor keeps reporting; its zero exit code only means the
        # bounded test loop completed, not that mapper telemetry is healthy.
        monitor = self.run_helper("monitor", env)
        self.assertEqual(monitor.returncode, 0, monitor.stderr)
        self.assertIn("SWAPZ_RUNTIME_HEALTH=DEGRADED", monitor.stderr)
        self.assertIn("mapper_status_unavailable", monitor.stderr)
        once = self.run_helper("once", env)
        self.assertEqual(once.returncode, 2, once.stderr)

    def test_failed_shutdown_with_unreadable_swap_inventory_never_claims_safe(self) -> None:
        (self.proc / "swaps").unlink()
        observed = self.run_helper("stop-observe")
        self.assertEqual(observed.returncode, 1, observed.stderr)
        self.assertIn("SWAPZ_RUNTIME_STOP=FAIL", observed.stderr)
        self.assertIn("reason=swap_or_mapper_still_present", observed.stderr)
        self.assertIn("action=none operator_next=inspect_failed_primary_stop_no_retry", observed.stderr)
        self.assertIn("mapper_present=1 active_swap=1", observed.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
