#!/usr/bin/env python3
"""Rootless regression fixture for swapz primary systemd packaging.

This is intentionally not wired into the public test runner here; Agent 10 owns
that integration. It never invokes swapon/swapoff, a real mapper, or reboot.
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

PARTUUID = "01234567-89abcdef"
OTHER_PARTUUID = "fedcba98-76543210"
BOOT_A = "11111111-1111-4111-8111-111111111111"
BOOT_B = "22222222-2222-4222-8222-222222222222"
SOURCE_SHA = "a" * 40
MODULE_SHA = "b" * 64
TARGET_BYTES = 124_787_884_032


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_executable(path: Path, body: str) -> None:
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
            "JobTimeoutSec=30s\n"
            "JobTimeoutAction=none\n"
        )
        self.assertEqual(self.dropin.read_text(encoding="ascii"), expected)
        first_identity = self.dropin.stat().st_ino
        second = self.run_generator()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.dropin.read_text(encoding="ascii"), expected)
        self.assertNotEqual(first_identity, self.dropin.stat().st_ino)

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
                "ExecStartPre=@SWAPZ_SBINDIR@/swapz-primary-boot-verify preflight",
                "ExecStartPre=-@SWAPZ_SBINDIR@/swapzctl primary recover",
                "ExecStartPre=@SWAPZ_SBINDIR@/swapzctl primary prepare",
                "ExecStart=@SWAPZ_SBINDIR@/swapzctl primary start",
                "ExecStop=@SWAPZ_SBINDIR@/swapzctl primary stop",
            ],
        )
        self.assertIn("Before=dev-mapper-swapz\\x2dprimary.swap shutdown.target", service)
        self.assertIn("Conflicts=shutdown.target", service)

    def test_swap_unit_has_bounded_swapoff_and_no_install_side_effect(self) -> None:
        swap = read_text(PRIMARY_SWAP)
        self.assertIn("After=swapz-primary-mapper.service", swap)
        self.assertIn("BindsTo=swapz-primary-mapper.service", swap)
        self.assertIn("What=/dev/mapper/swapz-primary", swap)
        self.assertIn("Priority=-1", swap)
        self.assertRegex(swap, r"TimeoutSec=\d+s")
        self.assertIn("WantedBy=swap.target", swap)
        self.assertNotIn("Alias=", swap)

    def test_boot_verifier_is_automatic_observer_not_an_activator(self) -> None:
        service = read_text(BOOT_VERIFY_SERVICE)
        self.assertIn("After=swapz-primary-mapper.service dev-mapper-swapz\\x2dprimary.swap", service)
        self.assertIn("ExecStart=@SWAPZ_SBINDIR@/swapz-primary-boot-verify observe", service)
        self.assertRegex(service, r"TimeoutStartSec=\d+s")
        self.assertIn("WantedBy=multi-user.target", service)
        self.assertNotIn("Wants=swapz-primary-mapper.service", service)
        self.assertNotIn("Requires=swapz-primary-mapper.service", service)

    def test_systemd_analyze_accepts_static_units(self) -> None:
        analyzer = shutil.which("systemd-analyze")
        if analyzer is None:
            self.skipTest("systemd-analyze unavailable")
        with tempfile.TemporaryDirectory(prefix="swapz-unit-verify-") as temp:
            unit_dir = Path(temp)
            service = read_text(MAPPER_SERVICE)
            service = service.replace("@SWAPZ_SBINDIR@/swapz-primary-boot-verify", "/usr/bin/true")
            service = service.replace("@SWAPZ_SBINDIR@/swapzctl", "/usr/bin/true")
            (unit_dir / "swapz-primary-mapper.service").write_text(service, encoding="utf-8")
            (unit_dir / r"dev-mapper-swapz\x2dprimary.swap").write_text(read_text(PRIMARY_SWAP), encoding="utf-8")
            verifier = read_text(BOOT_VERIFY_SERVICE).replace(
                "@SWAPZ_SBINDIR@/swapz-primary-boot-verify", "/usr/bin/true"
            )
            (unit_dir / "swapz-primary-boot-verify.service").write_text(verifier, encoding="utf-8")
            env = os.environ.copy()
            env["SYSTEMD_UNIT_PATH"] = f"{unit_dir}:/usr/lib/systemd/system:/lib/systemd/system"
            result = subprocess.run(
                [
                    analyzer,
                    "verify",
                    str(unit_dir / "swapz-primary-mapper.service"),
                    str(unit_dir / r"dev-mapper-swapz\x2dprimary.swap"),
                    str(unit_dir / "swapz-primary-boot-verify.service"),
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

    def test_recovery_probe_may_fail_but_prepare_start_still_run(self) -> None:
        env = self.env.copy()
        env["MOCK_RECOVER_STATUS"] = "2"
        self.assertEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["verify:preflight", "swapzctl:recover", "swapzctl:prepare", "swapzctl:start"],
        )
        self.assertEqual(self.execute_stop_contract(env), 0)
        self.assertEqual(self.log.read_text(encoding="ascii").splitlines()[-1], "swapzctl:stop")

    def test_prepare_failure_blocks_start(self) -> None:
        env = self.env.copy()
        env["MOCK_PREPARE_STATUS"] = "2"
        self.assertNotEqual(self.execute_start_contract(env), 0)
        self.assertEqual(
            self.log.read_text(encoding="ascii").splitlines(),
            ["verify:preflight", "swapzctl:recover", "swapzctl:prepare"],
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
        self.report = self.root / "var" / "lib" / "swapz" / "boot-acceptance"
        for directory in (self.sbin, self.libexec, self.bin, self.proc, self.sys, self.dev, self.report):
            directory.mkdir(parents=True, exist_ok=True)
        self.report.chmod(0o700)
        (self.proc / "sys" / "kernel" / "random").mkdir(parents=True)
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
        write_executable(
            self.sbin / "swapzctl",
            textwrap.dedent(
                r"""\
                #!/bin/sh
                [ "$1" = primary ] && [ "$2" = systemd-units ] || exit 2
                partuuid=${MOCK_PARTUUID:-01234567-89abcdef}
                encoded=$(printf '%s\n' "$partuuid" | sed 's/-/\\x2d/g')
                printf 'dev-disk-by\\x2dpartuuid-%s.device dev-disk-by\\x2dpartuuid-%s.swap\n' "$encoded" "$encoded"
                """
            ),
        )
        self.create_mocks()
        self.write_boot_id(BOOT_A)
        self.write_proc_swaps(active=True)
        (self.sys / "module" / "dm_swapz" / "parameters" / "build_source_sha").write_text(SOURCE_SHA + "\n", encoding="ascii")
        (self.sys / "module" / "dm_swapz" / "parameters" / "build_source_clean").write_text("1\n", encoding="ascii")
        self.env = os.environ.copy()
        self.env.update(
            {
                "PATH": f"{self.bin}:{self.env['PATH']}",
                "SWAPZ_PRIMARY_SYSTEMD_TESTING": "1",
                "SWAPZ_PRIMARY_TEST_PROC_ROOT": str(self.proc),
                "SWAPZ_PRIMARY_TEST_SYS_ROOT": str(self.sys),
                "SWAPZ_PRIMARY_TEST_DEV_ROOT": str(self.dev),
                "SWAPZ_PRIMARY_TEST_REPORT_BASE": str(self.report),
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
                    case "$field" in MODEL) echo 'USB Multi-Card' ;; SERIAL) echo reader-serial ;; WWN) echo ;; TRAN) echo usb ;; RM) echo 1 ;; MAJ:MIN) echo 8:0 ;; TYPE) echo disk ;; PKNAME) echo ;; *) echo ;; esac
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
                    if [ -n "${MOCK_RAW_UNIT_WHAT:-}" ]; then
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
                info) printf 'SWAPZ-PRIMARY-0123456789abcdef0123456789abcdef\\n' ;;
                table) printf '%s\\n' "${MOCK_DM_TABLE:-0 216643584 swapz 8:1 0 64 0 2 0 1 0 0}" ;;
                status)
                    printf '0 216643584 swapz version=0 flush_err=0 segment_discards_failed=%s failed=%s error=0 upper_write_completed_err=0 endio_write_seen_err=0 endio_write_forced_err=0\\n' "$MOCK_DM_DISCARD_FAIL" "$MOCK_DM_STATUS_FAIL"
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
            lines.append(f"{self.dev / 'mapper' / 'swapz-primary'} partition 108321788 0 -1")
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

    def test_observe_without_arm_is_incomplete(self) -> None:
        result = self.run_verifier("observe")
        self.assertEqual(result.returncode, 0, result.stderr)
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
            "expected_dm_logical_sectors=216643584",
            "dm_logical_bytes=110921515008",
            "swap_size_kib=108321788",
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

    def test_wrong_mapper_geometry_records_fail(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_DM_TABLE"] = "0 216643576 swapz 8:1 0 64 0 2 0 1 0 0"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 0, observed.stderr)
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
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=FAIL", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("status=FAIL", report)
        self.assertIn("swapz_target_failed", report)
        self.assertIn("swapz_segment_discard_failures", report)
        self.assertIn("mapper_service_not_active", report)
        self.assertIn("relevant_kernel_errors", report)

    def test_unavailable_kernel_log_is_incomplete_not_pass(self) -> None:
        self.arm_then_reboot()
        env = self.env.copy()
        env["MOCK_JOURNAL_UNAVAILABLE"] = "1"
        observed = self.run_verifier("observe", env=env)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        self.assertIn("COLD_BOOT_OBSERVATION=INCOMPLETE", observed.stdout)
        report = (self.report / f"report-{BOOT_B}.env").read_text(encoding="utf-8")
        self.assertIn("kernel_log_unavailable", report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
