#!/usr/bin/env python3
"""Rootless tests for the real pinned-GCC module build-info header producer.

These tests compile Linux-style MODULE_INFO definitions, not a loaded module
or a substitute for the exact-pinned Linux Kbuild hosted in GitHub Actions.
Only disposable temporary directories are written by this test.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/phase-a-linux-source-preflight.yml"
ROOT_MAKEFILE = REPOSITORY_ROOT / "Makefile"
FALLBACK_HEADER = REPOSITORY_ROOT / "src/kernel/swapz-build-info.h"
CONSUMER_SOURCE = REPOSITORY_ROOT / "src/kernel/dm-target.c"
SOURCE_SHA = "4063b88422dd62b1d4b1a990f0cfe9961e73277c"
ALTERNATIVE_SHA = "0123456789abcdef0123456789abcdef01234567"
REQUIRED_DEFINES = (
    "SWAPZ_BUILD_SOURCE_SHA",
    "SWAPZ_BUILD_SOURCE_CLEAN",
    "SWAPZ_BUILD_SOURCE_CLEAN_STRING",
)


class InvalidBuildInformation(ValueError):
    """Generated header does not establish canonical source provenance."""


def validate_build_info(header: str, expected_source_sha: str, expected_clean: int) -> None:
    """Reject missing, duplicated or inconsistent string/numeric metadata."""
    macros: dict[str, str] = {}
    for line in header.splitlines():
        match = re.fullmatch(r"#define (SWAPZ_BUILD_SOURCE_[A-Z_]+) (.+)", line)
        if match is None:
            if line.strip():
                raise InvalidBuildInformation("unexpected generated header content")
            continue
        name, value = match.groups()
        if name not in REQUIRED_DEFINES or name in macros:
            raise InvalidBuildInformation("unexpected or repeated build-info macro")
        macros[name] = value
    if set(macros) != set(REQUIRED_DEFINES):
        raise InvalidBuildInformation("missing source, numeric or string macro")
    if re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) is None:
        raise InvalidBuildInformation("expected source must be a canonical 40-digit SHA")
    if expected_clean not in (0, 1):
        raise InvalidBuildInformation("clean flag must be zero or one")
    if macros["SWAPZ_BUILD_SOURCE_SHA"] != f'"{expected_source_sha}"':
        raise InvalidBuildInformation("build source SHA does not match")
    if macros["SWAPZ_BUILD_SOURCE_CLEAN"] != str(expected_clean):
        raise InvalidBuildInformation("invalid numeric clean flag")
    if macros["SWAPZ_BUILD_SOURCE_CLEAN_STRING"] != f'"{expected_clean}"':
        raise InvalidBuildInformation("clean string differs from numeric state")


def workflow_build_info_script(workflow: str) -> str:
    """Extract, rather than reimplement, the actual pinned GCC producer."""
    gcc_job, boundary, clang_job = workflow.partition("\n  pinned-upstream-clang-objects:")
    if not boundary or not clang_job:
        raise InvalidBuildInformation("separate LLVM job missing")
    pattern = (
        r'(?ms)^          build_info_source="\$RUNNER_TEMP/swapz-module-build-info\.h"\n'
        r"(?P<producer>(?:^ {10,}[^\n]*\n)+?)"
        r"^          compiler_version=\"\$\(gcc --version"
    )
    matches = list(re.finditer(pattern, gcc_job))
    if len(matches) != 1:
        raise InvalidBuildInformation("missing or multiple GCC build-info producers")
    body = "\n".join(line[10:] for line in matches[0].group("producer").splitlines())
    if body.count("printf ") != 1 or "build_info_source=" in body or "build_info_source" not in body:
        raise InvalidBuildInformation("missing dedicated build-info printf")
    return 'build_info_source="$RUNNER_TEMP/swapz-module-build-info.h"\n' + body + "\n"


def generate_workflow_header(workflow: str, source_sha: str, destination: Path) -> str:
    producer = workflow_build_info_script(workflow)
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", 'swapz_sha="$TEST_SOURCE_SHA"\n' + producer],
        cwd=destination,
        env={"RUNNER_TEMP": str(destination), "TEST_SOURCE_SHA": source_sha, "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode:
        raise InvalidBuildInformation(f"workflow producer exit {result.returncode}")
    return (destination / "swapz-module-build-info.h").read_text(encoding="utf-8")


def generate_make_header(source_sha: str, clean: int, destination: Path) -> str:
    # The public root Makefile intentionally rejects internal target names.
    # Extract its exact existing internal recipe into a disposable Makefile,
    # keeping its producer bytes authoritative without running other targets.
    source = ROOT_MAKEFILE.read_text(encoding="utf-8")
    pattern = (r"(?m)^\.PHONY: build/source-build-info-force\n"
               r"build/source-build-info\.h: build/source-build-info-force\n"
               r"(?:\t[^\n]*\n)+")
    matches = re.findall(pattern, source)
    if len(matches) != 1:
        raise InvalidBuildInformation("root header producer missing or ambiguous")
    temporary_makefile = destination / "BuildInfoMakefile"
    temporary_makefile.write_text(matches[0], encoding="utf-8")
    result = subprocess.run(
        ["make", "-s", "--no-print-directory", "-C", str(destination),
         "-f", str(temporary_makefile), f"SWAPZ_BUILD_SOURCE_SHA={source_sha}",
         f"SWAPZ_BUILD_SOURCE_CLEAN={clean}", "build/source-build-info.h"],
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode:
        raise InvalidBuildInformation(f"root build-info producer exit {result.returncode}")
    return (destination / "build/source-build-info.h").read_text(encoding="utf-8")


def compile_module_info(header: str, compiler: str, output_dir: Path, clean: int, source_sha: str) -> subprocess.CompletedProcess[str]:
    """Use Linux MODULE_INFO's real string-concatenation and ELF section shape."""
    (output_dir / "swapz-build-info.h").write_text(header, encoding="utf-8")
    source = r'''
#define __swapz_stringify_1(x) #x
#define __swapz_stringify(x) __swapz_stringify_1(x)
#define MODULE_INFO(tag, info) \
    static const char __module_info_##tag[] __attribute__((used, section(".modinfo"), aligned(1))) = \
        __swapz_stringify(tag) "=" info
#include "swapz-build-info.h"
static char swapz_build_source_sha[] __attribute__((used)) = SWAPZ_BUILD_SOURCE_SHA;
static int swapz_build_source_clean __attribute__((used)) = SWAPZ_BUILD_SOURCE_CLEAN;
MODULE_INFO(swapz_build_source_sha, SWAPZ_BUILD_SOURCE_SHA);
MODULE_INFO(swapz_build_source_clean, SWAPZ_BUILD_SOURCE_CLEAN_STRING);
_Static_assert(sizeof(swapz_build_source_sha) == 41, "must embed a full 40-digit Git SHA");
'''
    result = subprocess.run(
        [compiler, "-x", "c", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror",
         "-c", "-", "-I", str(output_dir), "-o", str(output_dir / "module-info.o")],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    if result.returncode == 0:
        section = subprocess.run(
            ["readelf", "-p", ".modinfo", str(output_dir / "module-info.o")],
            text=True, capture_output=True, check=False, timeout=10,
        )
        if section.returncode or f"swapz_build_source_sha={source_sha}" not in section.stdout or \
           f"swapz_build_source_clean={clean}" not in section.stdout:
            raise AssertionError("compiler succeeded but ELF module metadata disagrees")
    return result


class PinnedGccBuildInfoSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.makefile = ROOT_MAKEFILE.read_text(encoding="utf-8")
        cls.fallback_header = FALLBACK_HEADER.read_text(encoding="utf-8")
        cls.consumer_source = CONSUMER_SOURCE.read_text(encoding="utf-8")
        cls.compilers = tuple(name for name in ("gcc", "clang") if shutil.which(name))
        if not cls.compilers:
            raise unittest.SkipTest("No C compiler available")
        if not shutil.which("readelf"):
            raise unittest.SkipTest("No readelf to verify emitted .modinfo")

    def test_source_producers_and_consumers_remain_authoritative(self) -> None:
        for name in REQUIRED_DEFINES:
            self.assertIn(name, self.makefile)
            self.assertIn(name, self.fallback_header)
            self.assertIn(name, self.consumer_source)
        self.assertIn("MODULE_INFO(swapz_build_source_clean, SWAPZ_BUILD_SOURCE_CLEAN_STRING);", self.consumer_source)
        self.assertIn('python3 -B swapz-consumer/tests/runtime/native/pinned-linux-artifact-integrity-test.py', self.workflow)
        self.assertLess(self.workflow.index("current_phase=verify_artifact_integrity"),
                        self.workflow.index("result=PASS", self.workflow.index("current_phase=verify_artifact_integrity")))
        self.assertEqual(self.workflow.count('build_info_source="$RUNNER_TEMP/swapz-module-build-info.h"'), 1)

    def test_real_clean_generated_headers_compile_with_elf_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            workflow_header = generate_workflow_header(self.workflow, SOURCE_SHA, directory)
            root_header = generate_make_header(SOURCE_SHA, 1, directory)
            self.assertEqual(workflow_header, root_header)
            validate_build_info(workflow_header, SOURCE_SHA, 1)
            for compiler in self.compilers:
                with self.subTest(compiler=compiler):
                    result = compile_module_info(workflow_header, compiler, directory, 1, SOURCE_SHA)
                    self.assertEqual(result.returncode, 0, result.stderr[-900:])

    def test_real_dirty_root_header_compiles_with_elf_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            root_header = generate_make_header(SOURCE_SHA, 0, directory)
            validate_build_info(root_header, SOURCE_SHA, 0)
            for compiler in self.compilers:
                with self.subTest(compiler=compiler):
                    result = compile_module_info(root_header, compiler, directory, 0, SOURCE_SHA)
                    self.assertEqual(result.returncode, 0, result.stderr[-900:])

    def test_workflow_uses_exact_requested_source_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            header = generate_workflow_header(self.workflow, ALTERNATIVE_SHA, directory)
            validate_build_info(header, ALTERNATIVE_SHA, 1)
            with self.assertRaises(InvalidBuildInformation):
                validate_build_info(header, SOURCE_SHA, 1)

    def test_missing_string_macro_reproduces_real_compile_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            original = generate_workflow_header(self.workflow, SOURCE_SHA, directory)
            missing = original.replace('#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n', "")
            self.assertNotEqual(missing, original)
            with self.assertRaises(InvalidBuildInformation):
                validate_build_info(missing, SOURCE_SHA, 1)
            for compiler in self.compilers:
                with self.subTest(compiler=compiler):
                    result = compile_module_info(missing, compiler, directory, 1, SOURCE_SHA)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("SWAPZ_BUILD_SOURCE_CLEAN_STRING", result.stderr)

    def test_fails_closed_on_inconsistent_or_malformed_headers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            original = generate_workflow_header(self.workflow, SOURCE_SHA, directory)
            mutation_cases = {
                "missing SHA": original.replace('#define SWAPZ_BUILD_SOURCE_SHA "' + SOURCE_SHA + '"\n', ""),
                "wrong SHA": original.replace(SOURCE_SHA, ALTERNATIVE_SHA),
                "short SHA": original.replace(SOURCE_SHA, SOURCE_SHA[:-1]),
                "uppercase SHA": original.replace(SOURCE_SHA, SOURCE_SHA.upper()),
                "unknown SHA": original.replace(SOURCE_SHA, "unknown"),
                "missing numeric flag": original.replace("#define SWAPZ_BUILD_SOURCE_CLEAN 1\n", ""),
                "missing quoted flag": original.replace('#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n', ""),
                "dirty numeric inconsistent": original.replace("#define SWAPZ_BUILD_SOURCE_CLEAN 1\n", "#define SWAPZ_BUILD_SOURCE_CLEAN 0\n"),
                "dirty string inconsistent": original.replace('SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"', 'SWAPZ_BUILD_SOURCE_CLEAN_STRING "0"'),
                "noncanonical numeric": original.replace("SWAPZ_BUILD_SOURCE_CLEAN 1", "SWAPZ_BUILD_SOURCE_CLEAN 01"),
                "unquoted metadata": original.replace('SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"', 'SWAPZ_BUILD_SOURCE_CLEAN_STRING 1'),
                "duplicate definition": original + '#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n',
                "extra unknown macro": original + '#define SWAPZ_BUILD_SOURCE_UNTRUSTED 1\n',
                "unexpected directive": original + "#undef SWAPZ_BUILD_SOURCE_CLEAN_STRING\n",
            }
            self.assertEqual(len(mutation_cases), 14)
            for description, mutated in mutation_cases.items():
                with self.subTest(mutation=description):
                    with self.assertRaises(InvalidBuildInformation):
                        validate_build_info(mutated, SOURCE_SHA, 1)

    def test_workflow_source_mutations_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swapz-build-info-") as root:
            directory = Path(root)
            originals = {
                "missing generated metadata": self.workflow.replace('SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"', 'SWAPZ_BUILD_SOURCE_CLEAN_STRING 1'),
                "missing dedicated producer": self.workflow.replace('build_info_source="$RUNNER_TEMP/swapz-module-build-info.h"', ''),
                "duplicate producer": self.workflow.replace('          compiler_version=', '          build_info_source="$RUNNER_TEMP/swapz-module-build-info.h"\n          compiler_version=', 1),
            }
            for description, mutated in originals.items():
                with self.subTest(mutation=description):
                    if description == "missing generated metadata":
                        header = generate_workflow_header(mutated, SOURCE_SHA, directory)
                        with self.assertRaises(InvalidBuildInformation):
                            validate_build_info(header, SOURCE_SHA, 1)
                    else:
                        with self.assertRaises(InvalidBuildInformation):
                            workflow_build_info_script(mutated)


if __name__ == "__main__":
    unittest.main()
