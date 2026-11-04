#!/usr/bin/env python3
"""Rootless adversarial publication test for the primary systemd generator.

Only private output directories and stubbed commands are used. No systemctl,
block devices, module, mapper, swap operation, or reboot is performed.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
GENERATOR = ROOT / "packaging/swapz-primary-generator"
MAPPER_SERVICE = ROOT / "packaging/swapz-primary-mapper.service"
PASSIVE_SWAP = ROOT / "packaging/swapz-primary.swap"
SELECTED = "01234567-89abcdef"
CHANGED = "fedcba98-76543210"


def identities(partuuid: str) -> tuple[str, str]:
    escaped = partuuid.replace("-", r"\x2d")
    base = r"dev-disk-by\x2dpartuuid-" + escaped
    return base + ".device", base + ".swap"


class GeneratorPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory(prefix="swapz-generator-transaction-")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.sbin = self.root / "sbin"
        self.commands = self.root / "commands"
        self.sbin.mkdir()
        self.commands.mkdir()
        self.selector = self.root / "protected-selector"
        self.set_selector(SELECTED)
        manager = self.sbin / "swapzctl"
        manager.write_text(textwrap.dedent(r"""
            #!/usr/bin/env python3
            import os
            import re
            import stat
            import sys
            from pathlib import Path

            if "MOCK_STATUS" in os.environ:
                sys.stdout.write(os.environ.get("MOCK_UNITS", ""))
                sys.exit(int(os.environ["MOCK_STATUS"]))
            if "MOCK_UNITS" in os.environ:
                sys.stdout.write(os.environ["MOCK_UNITS"])
                sys.exit(0)
            selector = Path(os.environ["MOCK_SELECTOR"])
            try:
                mode = selector.lstat()
                lines = selector.read_text(encoding="ascii").splitlines(keepends=True)
                if (not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.geteuid()
                        or stat.S_IMODE(mode.st_mode) != 0o600 or len(lines) != 1):
                    sys.exit(24)
                match = re.fullmatch(r"PARTUUID=([0-9a-f]+(?:-[0-9a-f]+)*)\n", lines[0])
                if not match or not 8 <= len(match.group(1)) <= 64:
                    sys.exit(24)
                partuuid = match.group(1).replace("-", r"\x2d")
                base = r"dev-disk-by\x2dpartuuid-" + partuuid
                sys.stdout.write(base + ".device " + base + ".swap\n")
            except (OSError, UnicodeError):
                sys.exit(24)
            """).lstrip("\n"), encoding="utf-8")
        manager.chmod(0o755)
        copied = GENERATOR.read_text(encoding="utf-8").replace("@SWAPZ_SBINDIR@", str(self.sbin))
        self.generator = self.root / "swapz-primary-generator"
        self.generator.write_text(copied, encoding="utf-8")
        self.generator.chmod(0o755)
        self.normal = self.root / "normal"
        self.early = self.root / "early"
        self.late = self.root / "late"
        for directory in (self.normal, self.early, self.late):
            directory.mkdir()
        self.environment = os.environ.copy()
        self.environment["MOCK_SELECTOR"] = str(self.selector)
        self.environment["PATH"] = f"{self.commands}:{os.environ['PATH']}"

    def set_selector(self, partuuid: str) -> None:
        self.selector.write_text(f"PARTUUID={partuuid}\n", encoding="ascii")
        self.selector.chmod(0o600)

    def run_generator(self, **updates: str) -> subprocess.CompletedProcess[str]:
        environment = self.environment | updates
        return subprocess.run(
            [str(self.generator), str(self.normal), str(self.early), str(self.late)],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )

    def mask(self) -> Path:
        return self.early / "swapz-primary-mapper.service"

    def mapper_dropin(self) -> Path:
        return self.normal / "swapz-primary-mapper.service.d/50-selected-target.conf"

    def device_dropin(self, partuuid: str) -> Path:
        return self.normal / (identities(partuuid)[0] + ".d") / "50-swapz-timeout.conf"

    def assert_blocked(self, result: subprocess.CompletedProcess[str], phase: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.mask()), "/dev/null")
        self.assertFalse(self.mapper_dropin().exists())
        self.assertRegex(result.stderr, rf"phase={re.escape(phase)}\b")
        self.assertRegex(result.stderr, r"source=[a-z-]+ validation=[a-z-]+ status=\d+ withheld=.*mapper-active-job")
        self.assertNotIn("PARTUUID=", result.stderr)
        self.assertFalse(list(self.normal.glob(".swapz-primary-generator.*")))

    def test_valid_selected_ordering_exclusive_raw_conflict_and_repeat(self) -> None:
        device, raw = identities(SELECTED)
        for _ in range(2):
            result = self.run_generator()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertFalse(self.mask().exists())
            self.assertFalse(self.mask().is_symlink())
            self.assertEqual(self.mapper_dropin().read_text(),
                "[Unit]\n" + f"Requires={device}\nAfter={device}\n"
                + f"Conflicts={raw}\nBefore={raw}\n"
                + "JobTimeoutSec=300s\nJobTimeoutAction=none\n")
            self.assertEqual(self.device_dropin(SELECTED).read_text(),
                "[Unit]\nJobTimeoutSec=30s\nJobTimeoutAction=none\n")
        service = MAPPER_SERVICE.read_text()
        passive = PASSIVE_SWAP.read_text()
        self.assertIn("RequiresMountsFor=/var/lib/swapz/physical-recovery", service)
        self.assertNotIn("BindsTo=", service)
        self.assertIn("WantedBy=swap.target", service)
        self.assertIn("RefuseManualStart=yes", passive)
        self.assertNotIn("WantedBy=swap.target", passive)
        self.assertNotIn("/dev/sda1", self.generator.read_text())

    def test_changed_partuuid_removes_old_ordering_and_new_failure_masks_it(self) -> None:
        self.assertEqual(self.run_generator().returncode, 0)
        self.set_selector(CHANGED)
        self.assertEqual(self.run_generator().returncode, 0)
        self.assertFalse(self.device_dropin(SELECTED).exists())
        self.assertTrue(self.device_dropin(CHANGED).exists())
        self.assertIn(identities(CHANGED)[0], self.mapper_dropin().read_text())
        result = self.run_generator(MOCK_UNITS="", MOCK_STATUS="39")
        self.assert_blocked(result, "selection")
        self.assertIn("source=protected-selector", result.stderr)
        self.assertIn("status=39", result.stderr)
        self.assertFalse(self.device_dropin(CHANGED).exists())

    def test_missing_ambiguous_or_unsafe_selector_refuses_any_mapper(self) -> None:
        for contents, mode in (("", 0o600), ("PARTUUID=11111111\nPARTUUID=22222222\n", 0o600),
                               ("PARTUUID=INVALID\n", 0o600), (f"PARTUUID={SELECTED}\n", 0o644)):
            with self.subTest(contents=contents, mode=mode):
                self.selector.write_text(contents, encoding="ascii")
                self.selector.chmod(mode)
                self.assert_blocked(self.run_generator(), "selection")
        self.selector.unlink()
        self.assert_blocked(self.run_generator(), "selection")
        self.selector.symlink_to(self.root / "other-selector")
        self.assert_blocked(self.run_generator(), "selection")

    def test_manager_response_mutants_and_wrong_aliases(self) -> None:
        device, raw = identities(SELECTED)
        mutants = (
            "", "garbage", f"{device} {raw} extra\n", f"{device}\n{raw}\n",
            f"{device} {identities(CHANGED)[1]}\n",
            f"{device} {raw} \n", f"{device}  {raw}\n",
            f"{device} dev-disk-by\\x2did-wrong.swap\n",
            f"dev-disk-by\\x2did-wrong.device {raw}\n",
            f"{device.upper()} {raw}\n",
            "dev-disk-by\\x2dpartuuid-12345678\\x2d.swap dev-disk-by\\x2dpartuuid-12345678\\x2d.device\n",
            "dev-disk-by\\x2dpartuuid-12345678\\x2d.swap dev-disk-by\\x2dpartuuid-12345678\\x2d.swap\n",
            "X" * 1500,
        )
        for response in mutants:
            with self.subTest(response=response[:75]):
                result = self.run_generator(MOCK_UNITS=response)
                self.assert_blocked(result, "selection")
                self.assertFalse(self.device_dropin(SELECTED).exists())
        self.assert_blocked(self.run_generator(MOCK_STATUS="47", MOCK_UNITS=f"{device} {raw}\n"), "selection")

    def test_output_failure_and_after_rename_partial_write_rollback(self) -> None:
        executable = self.commands / "mv"
        for failure in ("before", "after"):
            for leaf in ("50-selected-target.conf", "50-swapz-timeout.conf"):
                with self.subTest(failure=failure, leaf=leaf):
                    # A wrapper that moves the file then reports an error tests
                    # rollback of both an untouched and a published destination.
                    executable.write_text(
                        '#!/bin/sh\ncase "$*" in\n'
                        f'  *{leaf}*)\n'
                        '    if [ "$MOCK_MV_FAILURE" = after ]; then '
                        '/usr/bin/mv "$@" || exit $?; fi\n'
                        '    exit 71 ;;\n'
                        'esac\nexec /usr/bin/mv "$@"\n'
                    )
                    executable.chmod(0o755)
                    result = self.run_generator(MOCK_MV_FAILURE=failure)
                    self.assert_blocked(result, "publication")
                    self.assertFalse(self.device_dropin(SELECTED).exists())
        executable.unlink()

    def test_output_symlink_substitution_and_colliding_units_are_blocked(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "unchanged"
        sentinel.write_text("safe")
        for subpath in ("swapz-primary-mapper.service.d", "systemd-hibernate.service.d",
                        identities(SELECTED)[0] + ".d"):
            with self.subTest(subpath=subpath):
                candidate = self.normal / subpath
                candidate.symlink_to(outside, target_is_directory=True)
                self.assert_blocked(self.run_generator(), "cleanup" if "mapper" in subpath else (
                    "hibernation" if "hibernate" in subpath else "cleanup"))
                self.assertEqual(sentinel.read_text(), "safe")
                candidate.unlink()
        for output in (self.normal, self.early, self.late):
            for leaf in (identities(SELECTED)[0], identities(SELECTED)[1]):
                with self.subTest(output=output.name, leaf=leaf):
                    (output / leaf).write_text("[Unit]\n")
                    self.assert_blocked(self.run_generator(), "publication")
                    (output / leaf).unlink()
        self.assert_blocked(self.run_generator(MOCK_UNITS="", MOCK_STATUS="21"), "selection")

    def test_hibernation_guards_survive_refused_selector(self) -> None:
        result = self.run_generator(MOCK_UNITS="garbage")
        self.assert_blocked(result, "selection")
        for unit in ("systemd-hibernate", "systemd-hybrid-sleep", "systemd-suspend-then-hibernate"):
            guard = self.normal / f"{unit}.service.d/50-swapz-no-hibernate.conf"
            self.assertEqual(guard.read_text(), "[Service]\nExecStartPre=" + str(
                self.sbin / "swapz-primary-runtime-health") + " hibernate-guard\n")


if __name__ == "__main__":
    unittest.main()
