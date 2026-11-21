#!/usr/bin/env python3
"""Fail-closed original Linux native libelf header/link prerequisite.

This probes the actual build host only; no kernel module is loaded, no Linux
source is altered, and no device is touched. Self-test uses synthetic header
files only to test the prerequisite gate, never to qualify native linkage.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

REQUIRED_HEADERS = ("elf.h", "gelf.h", "libelf.h")
LIBELF_PROBE = """\
#include <elf.h>
#include <gelf.h>
#include <libelf.h>
int main(void)
{
    GElf_Ehdr header = {0};
    return elf_version(EV_CURRENT) == EV_NONE || sizeof(header) < EI_NIDENT;
}
"""


class PrerequisiteError(Exception):
    """One bounded, host-path-free prerequisite failure."""


def check_headers(include_directory: Path) -> None:
    for header in REQUIRED_HEADERS:
        if not (include_directory / header).is_file():
            raise PrerequisiteError("missing development header " + header)


def compiler_command(executable: str, output: Path, *, link_libelf: bool) -> list[str]:
    # Clang rejects an unneeded "-x none" after the final stdin source under
    # -Werror,-Wunused-command-line-argument. Library flags are linker inputs,
    # not language-selected C source files, so no language reset is needed.
    arguments = [executable, "-std=c11", "-Wall", "-Wextra", "-Wconversion",
                 "-Wshadow", "-Werror", "-x", "c", "-", "-o", str(output)]
    if link_libelf:
        arguments.append("-lelf")
    return arguments


def compiler_command_self_test() -> None:
    # Genuine GCC and Clang source compiles and program executions here;
    # synthetic-only headers below never qualify the original Linux module.
    with tempfile.TemporaryDirectory(prefix="swapz-original-compiler-") as directory:
        compiler_paths: dict[str, str] = {}
        for compiler in ("gcc", "clang"):
            executable = shutil.which(compiler)
            if executable is None:
                raise PrerequisiteError("missing compiler " + compiler)
            compiler_paths[compiler] = executable
            output = Path(directory) / ("strict-stdin-" + compiler)
            command = compiler_command(executable, output, link_libelf=False)
            compiled = subprocess.run(
                command, input="int main(void) { return 0; }\n",
                capture_output=True, text=True, check=False, timeout=30)
            if compiled.returncode or compiled.stderr:
                raise PrerequisiteError(compiler + " strict stdin compile/link regression")
            executed = subprocess.run([str(output)], capture_output=True,
                                      check=False, timeout=15)
            if executed.returncode:
                raise PrerequisiteError(compiler + " strict stdin execution regression")
        # The original failure reproduces as a real Clang -Werror diagnostic.
        # This is a negative compiler-command test, not a simulated modpost.
        clang = compiler_paths["clang"]
        bad_output = Path(directory) / "legacy-language-reset"
        bad_command = compiler_command(clang, bad_output, link_libelf=False)
        bad_command[bad_command.index("-o"):bad_command.index("-o")] = ["-x", "none"]
        rejected = subprocess.run(
            bad_command, input="int main(void) { return 0; }\n",
            capture_output=True, text=True, check=False, timeout=30)
        if rejected.returncode == 0 or "unused-command-line-argument" not in rejected.stderr:
            raise PrerequisiteError("Clang failed to reject original redundant -x none")
    print("ROUND062_GCC_CLANG_STRICT_STDIN_COMPILER_ARGUMENTS_PASS "
          "actual_compiles=2 actual_executions=2 original_clang_negative=1",
          flush=True)


def check_native_libelf() -> None:
    check_headers(Path("/usr/include"))
    with tempfile.TemporaryDirectory(prefix="swapz-original-libelf-") as directory:
        for compiler in ("gcc", "clang"):
            executable = shutil.which(compiler)
            if executable is None:
                raise PrerequisiteError("missing compiler " + compiler)
            output = Path(directory) / ("libelf-" + compiler)
            try:
                compiled = subprocess.run(
                    compiler_command(executable, output, link_libelf=True),
                    input=LIBELF_PROBE, capture_output=True, text=True,
                    check=False, timeout=30)
                if compiled.returncode:
                    raise PrerequisiteError(compiler + " real libelf compile/link failed")
                checked = subprocess.run([str(output)], capture_output=True,
                                         check=False, timeout=15)
                if checked.returncode:
                    raise PrerequisiteError(compiler + " real libelf execution failed")
            except (OSError, subprocess.TimeoutExpired) as error:
                raise PrerequisiteError(compiler + " libelf probe unavailable") from error
    print("ROUND061_REAL_GCC_CLANG_ELF_GELF_LIBELF_COMPILE_LINK_EXEC_PASS",
          flush=True)


def self_test() -> None:
    compiler_command_self_test()
    with tempfile.TemporaryDirectory(prefix="swapz-original-header-gate-") as directory:
        root = Path(directory)
        (root / "elf.h").write_text("/* synthetic header gate fixture */\n")
        try:
            check_headers(root)
        except PrerequisiteError as error:
            if str(error) != "missing development header gelf.h":
                raise AssertionError("wrong first missing-header error") from error
        else:
            raise AssertionError("missing gelf.h was accepted")
        (root / "gelf.h").write_text("/* synthetic gate fixture, NOT Kbuild */\n")
        try:
            check_headers(root)
        except PrerequisiteError as error:
            if str(error) != "missing development header libelf.h":
                raise AssertionError("wrong missing-libelf error") from error
        else:
            raise AssertionError("missing libelf.h was accepted")
        (root / "libelf.h").write_text("/* synthetic gate fixture, NOT Kbuild */\n")
        check_headers(root)
        (root / "elf.h").unlink()
        try:
            check_headers(root)
        except PrerequisiteError as error:
            if str(error) != "missing development header elf.h":
                raise AssertionError("wrong missing-elf error") from error
        else:
            raise AssertionError("missing elf.h was accepted")
    print("ROUND061_GELF_HEADER_FIRST_CAUSE_NEGATIVE_GATES_PASS synthetic_only=1",
          flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("check", "self-test"))
    arguments = parser.parse_args()
    try:
        if arguments.action == "check":
            check_native_libelf()
        else:
            self_test()
    except PrerequisiteError as error:
        parser.exit(3, "ROUND061_DECODER_FIRST_ERROR " + str(error) + "\n")


if __name__ == "__main__":
    main()
