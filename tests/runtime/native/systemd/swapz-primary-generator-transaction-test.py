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
                if os.environ.get("MOCK_APPEND_NUL") == "1":
                    sys.stdout.write(chr(0))
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
        # CI uses PYTHONPYCACHEPREFIX; the generator file-size limit must not
        # apply to the Python stub's import-cache writes.
        self.environment["PYTHONDONTWRITEBYTECODE"] = "1"
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
        previous_inode: int | None = None
        for _ in range(2):
            result = self.run_generator()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertFalse(self.mask().exists())
            self.assertFalse(self.mask().is_symlink())
            current_inode = self.mapper_dropin().stat().st_ino
            if previous_inode is not None:
                self.assertNotEqual(previous_inode, current_inode)
            previous_inode = current_inode
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

    def test_manager_response_rejects_extra_bytes_and_missing_terminator(self) -> None:
        device, raw = identities(SELECTED)
        canonical = f"{device} {raw}\n"
        cases = (
            (canonical + "\n", "noncanonical-response"),
            (canonical + "\n\n", "noncanonical-response"),
            (canonical[:-1], "noncanonical-response"),
            # CRLF preserves the raw record but is not a valid unit identity.
            (canonical.replace("\n", "\r\n"), "invalid-raw-swap-unit"),
        )
        for response, validation in cases:
            with self.subTest(response=repr(response)):
                result = self.run_generator(MOCK_UNITS=response)
                self.assert_blocked(result, "selection")
                self.assertIn(f"validation={validation}", result.stderr)
        # Environment variables cannot contain NUL; the stub emits it itself.
        nul_result = self.run_generator(MOCK_UNITS=canonical, MOCK_APPEND_NUL="1")
        self.assert_blocked(nul_result, "selection")
        self.assertIn("validation=noncanonical-response", nul_result.stderr)

    def test_failed_publication_preserves_substituted_foreign_inode(self) -> None:
        outside = self.root / "foreign-original"
        outside.write_text("untouched", encoding="ascii")
        command = self.commands / "mv"
        for leaf, destination in (
            ("50-swapz-timeout.conf", self.device_dropin(SELECTED)),
            ("50-selected-target.conf", self.mapper_dropin()),
        ):
            with self.subTest(leaf=leaf):
                command.write_text(
                    '#!/bin/sh\ncase "$*" in\n'
                    f"  *{leaf}*)\n"
                    '    for output_path do :; done\n'
                    '    /usr/bin/ln -s "$MOCK_EXTERNAL" "$output_path" || exit $?\n'
                    '    exit 74 ;;\n'
                    'esac\nexec /usr/bin/mv "$@"\n',
                    encoding="ascii",
                )
                command.chmod(0o755)
                result = self.run_generator(MOCK_EXTERNAL=str(outside))
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("phase=publication", result.stderr)
                self.assertIn("status=74", result.stderr)
                self.assertEqual(os.readlink(self.mask()), "/dev/null")
                self.assertTrue(destination.is_symlink())
                self.assertEqual(destination.readlink(), outside)
                self.assertEqual(outside.read_text(encoding="ascii"), "untouched")
                if leaf == "50-selected-target.conf":
                    self.assertFalse(self.device_dropin(SELECTED).exists())
                self.assertFalse(list(self.normal.glob(".swapz-primary-generator.*")))
                destination.unlink()
        command.unlink()

    def test_symlinked_output_ancestor_and_directory_alias_fail_before_writes(self) -> None:
        outside = self.root / "foreign-directory"
        outside.mkdir()
        (outside / "normal").mkdir()
        alias = self.root / "aliased-parent"
        alias.symlink_to(outside, target_is_directory=True)
        for output_dir in (alias / "normal", self.normal / ".." / "normal"):
            with self.subTest(output_dir=output_dir):
                result = subprocess.run(
                    [str(self.generator), str(output_dir), str(self.early), str(self.late)],
                    env=self.environment, capture_output=True, text=True,
                    check=False, timeout=30,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("validation=unsafe-output-directory", result.stderr)
        self.assertFalse(list((outside / "normal").iterdir()))
        self.assertFalse(list(self.normal.iterdir()))

    def test_comparison_failure_preserves_original_status(self) -> None:
        compare = self.commands / "cmp"
        compare.write_text("#!/bin/sh\nexit 79\n", encoding="ascii")
        compare.chmod(0o755)
        result = self.run_generator()
        self.assert_blocked(result, "selection")
        self.assertIn("status=79", result.stderr)
        self.assertIn("validation=compare-response", result.stderr)
        compare.unlink()

    def test_successful_rename_does_not_overwrite_late_symlink(self) -> None:
        outside = self.root / "foreign-unit"
        outside.write_text("unchanged", encoding="ascii")
        command = self.commands / "mv"
        for leaf, destination in (
            ("50-swapz-timeout.conf", self.device_dropin(SELECTED)),
            ("50-selected-target.conf", self.mapper_dropin()),
        ):
            with self.subTest(leaf=leaf):
                command.write_text(
                    '#!/bin/sh\ncase "$*" in\n'
                    f"  *{leaf}*)\n"
                    '    for output_path do :; done\n'
                    '    /usr/bin/ln -s "$MOCK_EXTERNAL" "$output_path" || exit $?\n'
                    '    exec /usr/bin/mv "$@" ;;\n'
                    'esac\nexec /usr/bin/mv "$@"\n',
                    encoding="ascii",
                )
                command.chmod(0o755)
                result = self.run_generator(MOCK_EXTERNAL=str(outside))
                self.assertNotEqual(result.returncode, 0, result.stderr)
                self.assertIn("phase=publication", result.stderr)
                self.assertIn("status=1", result.stderr)
                self.assertEqual(os.readlink(self.mask()), "/dev/null")
                self.assertTrue(destination.is_symlink())
                self.assertEqual(destination.readlink(), outside)
                self.assertEqual(outside.read_text(encoding="ascii"), "unchanged")
                if leaf == "50-selected-target.conf":
                    self.assertFalse(self.device_dropin(SELECTED).exists())
                self.assertFalse(list(self.normal.glob(".swapz-primary-generator.*")))
                destination.unlink()
        command.unlink()

    def test_mask_release_error_rolls_back_published_files(self) -> None:
        command = self.commands / "rm"
        for failure in ("before", "after"):
            with self.subTest(failure=failure):
                # A command can unlink the early mask and still return an
                # error. Both owned drop-ins must roll back under the mask.
                command.write_text(
                    '#!/bin/sh\ncase "$*" in\n'
                    '*swapz-primary-mapper.service)\n'
                    '    if [ "$MOCK_RM_FAILURE" = after ]; then '
                    '/usr/bin/rm "$@" || exit $?; fi\n'
                    '    exit 83 ;;\n'
                    'esac\nexec /usr/bin/rm "$@"\n',
                    encoding="ascii",
                )
                command.chmod(0o755)
                result = self.run_generator(MOCK_RM_FAILURE=failure)
                self.assert_blocked(result, "publication")
                self.assertIn("validation=release-mask", result.stderr)
                self.assertIn("original_status=83", result.stderr)
                self.assertIn("rollback=complete", result.stderr)
                self.assertEqual(result.returncode, 83)
                self.assertFalse(self.device_dropin(SELECTED).exists())
        command.unlink()

    def test_mask_unlink_false_success_is_not_committed(self) -> None:
        command = self.commands / "rm"
        command.write_text(
            '#!/bin/sh\ncase "$*" in\n'
            '*swapz-primary-mapper.service) exit 0 ;;\n'
            'esac\nexec /usr/bin/rm "$@"\n',
            encoding="ascii",
        )
        command.chmod(0o755)
        result = self.run_generator()
        self.assert_blocked(result, "publication")
        self.assertIn("validation=mask-not-released", result.stderr)
        self.assertIn("rollback=complete", result.stderr)
        self.assertFalse(self.device_dropin(SELECTED).exists())

    def test_mask_restore_rename_failure_keeps_barrier(self) -> None:
        release_marker = self.root / "mask-release-observed"
        removal_command = self.commands / "rm"
        removal_command.write_text(
            '#!/bin/sh\ncase "$*" in\n'
            '*swapz-primary-mapper.service)\n'
            '    /usr/bin/rm "$@" || exit $?\n'
            '    : > "$MOCK_RELEASE_MARKER"\n'
            '    exit 86 ;;\n'
            'esac\nexec /usr/bin/rm "$@"\n',
            encoding="ascii",
        )
        removal_command.chmod(0o755)
        rename_command = self.commands / "mv"
        for failure in ("before", "after"):
            with self.subTest(failure=failure):
                rename_command.write_text(
                    '#!/bin/sh\ncase "$*" in\n'
                    '*swapz-primary-mapper.service)\n'
                    '    if [ -e "$MOCK_RELEASE_MARKER" ]; then\n'
                    '        if [ "$MOCK_RESTORE_FAILURE" = after ]; then '
                    '/usr/bin/mv "$@" || exit $?; fi\n'
                    '        exit 92\n'
                    '    fi ;;\n'
                    'esac\nexec /usr/bin/mv "$@"\n',
                    encoding="ascii",
                )
                rename_command.chmod(0o755)
                result = self.run_generator(
                    MOCK_RELEASE_MARKER=str(release_marker),
                    MOCK_RESTORE_FAILURE=failure,
                )
                self.assert_blocked(result, "publication")
                self.assertEqual(result.returncode, 86)
                self.assertIn("original_status=86", result.stderr)
                self.assertIn("rollback=complete", result.stderr)
                self.assertFalse(self.device_dropin(SELECTED).exists())
                release_marker.unlink()
        removal_command.unlink()
        rename_command.unlink()

    def test_foreign_mapper_symlink_after_mask_release_is_remasked(self) -> None:
        outside = self.root / "foreign-mapper-unit"
        outside.write_text("unchanged", encoding="ascii")
        command = self.commands / "rm"
        command.write_text(
            '#!/bin/sh\ncase "$*" in\n'
            '*swapz-primary-mapper.service)\n'
            '    for output_path do :; done\n'
            '    /usr/bin/rm "$@" || exit $?\n'
            '    /usr/bin/ln -s "$MOCK_EXTERNAL" "$output_path" || exit $?\n'
            '    exit "$MOCK_RELEASE_STATUS" ;;\n'
            'esac\nexec /usr/bin/rm "$@"\n',
            encoding="ascii",
        )
        command.chmod(0o755)
        for release_status, validation, expected_status in (
            ("86", "release-mask", 86),
            ("0", "mask-not-released", 1),
        ):
            with self.subTest(release_status=release_status):
                result = self.run_generator(
                    MOCK_EXTERNAL=str(outside),
                    MOCK_RELEASE_STATUS=release_status,
                )
                self.assert_blocked(result, "publication")
                self.assertEqual(result.returncode, expected_status)
                self.assertIn(f"validation={validation}", result.stderr)
                self.assertIn(f"original_status={expected_status}", result.stderr)
                self.assertIn("restore_status=0", result.stderr)
                self.assertIn("rollback=complete", result.stderr)
                self.assertEqual(outside.read_text(encoding="ascii"), "unchanged")
        command.unlink()

    def test_unrelated_generated_partuuid_swap_does_not_gate_mapper(self) -> None:
        unrelated_raw_swap = identities(CHANGED)[1]
        for output in (self.normal, self.early, self.late):
            for enabled_alias in (False, True):
                with self.subTest(output=output.name, enabled_alias=enabled_alias):
                    candidate = output / ("swap.target.wants" if enabled_alias else "") / unrelated_raw_swap
                    candidate.parent.mkdir(exist_ok=True)
                    if enabled_alias:
                        candidate.symlink_to("/nonexistent/unrelated-raw-swap")
                    else:
                        candidate.write_text("[Swap]\n", encoding="ascii")
                    result = self.run_generator()
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr, "")
                    self.assertTrue(self.mapper_dropin().exists())
                    self.assertFalse(self.mask().exists())
                    candidate.unlink()

    def test_hibernation_guards_survive_refused_selector(self) -> None:
        result = self.run_generator(MOCK_UNITS="garbage")
        self.assert_blocked(result, "selection")
        for unit in ("systemd-hibernate", "systemd-hybrid-sleep", "systemd-suspend-then-hibernate"):
            guard = self.normal / f"{unit}.service.d/50-swapz-no-hibernate.conf"
            self.assertEqual(guard.read_text(), "[Service]\nExecStartPre=" + str(
                self.sbin / "swapz-primary-runtime-health") + " hibernate-guard\n")


if __name__ == "__main__":
    unittest.main()
