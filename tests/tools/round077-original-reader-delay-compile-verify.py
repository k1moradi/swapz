#!/usr/bin/env python3
"""Round077 original pinned usleep_range declaration regression (host only).

Do not confuse this targeted source-extracted compile/runtime check with the
full original Linux UML KUnit. The native job independently builds and boots
the actual pinned mm/zswap.c with -Werror and validates exact JSON/KTAP.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
UPSTREAM_ZSWAP_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
UPSTREAM_DELAY_BLOB = "82409e55b6aedc39132d2adc60c028ada12a603b"
INCLUDE = "#include <linux/delay.h>"
CALL = "usleep_range(1000, 2000);"
GUARD = "#if defined(SWAPZ_ROUND073_ORIGINAL_READER_PIN_GC_KUNIT) && IS_ENABLED(CONFIG_KUNIT)"
CASE = "KUNIT_CASE(swapz_round073_original_decoder_retire_with_pin)"
SUITE = "kunit_test_suite(swapz_round073_original_reader_suite);"
ORIGINAL_INLINE = (
    "static inline void usleep_range(unsigned long min, unsigned long max)\n"
    "{\n"
    "\tusleep_range_state(min, max, TASK_UNINTERRUPTIBLE);\n"
    "}"
)


class FirstError(Exception):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise FirstError(reason)


def git_blob(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def check_declaration(pin: str, original: bytes, delay: bytes,
                      fixture: str) -> None:
    require(pin == PIN, "original-kernel-pin-mismatch")
    require(git_blob(original) == UPSTREAM_ZSWAP_BLOB,
            "original-mm-zswap-blob-mismatch")
    require(git_blob(delay) == UPSTREAM_DELAY_BLOB,
            "original-linux-delay-header-blob-mismatch")
    delay_text = delay.decode("utf-8")
    require(delay_text.count(ORIGINAL_INLINE) == 1,
            "original-usleep_range-inline-implementation-missing")
    require("void usleep_range_state(unsigned long min, unsigned long max," in
            delay_text, "original-usleep_range_state-declaration-missing")
    require("usleep_range(" not in original.decode("utf-8"),
            "pristine-original-zswap-unexpected-delay-definition")
    require(fixture.count("/* ROUND073_ORIGINAL_READER_PIN_GC_BEGIN") == 1 and
            fixture.count("/* ROUND073_ORIGINAL_READER_PIN_GC_END */") == 1,
            "original-reader-fixture-markers")
    require(fixture.count(GUARD) == 1 and fixture.count(SUITE) == 1 and
            fixture.count(CASE) == 1, "original-reader-KUnit-suite-invalid")
    require(fixture.count(INCLUDE) == 1 and fixture.count(CALL) == 1,
            "original-reader-delay-include-or-call-invalid")
    require(fixture.index(GUARD) < fixture.index(INCLUDE) <
            fixture.index(CALL), "original-reader-delay-declaration-context")
    require("for (iteration = 0; iteration < 1500U &&" in fixture and
            "msecs_to_jiffies(1500U)" in fixture,
            "original-reader-bounded-drain-wait-changed")
    require("-Wno-error" not in fixture and
            "usleep_range(1000, 2000)" in fixture,
            "original-reader-warning-suppression-or-busy-spin")


def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, text=True, capture_output=True,
                          timeout=45, check=False)


def compiler_mode(compiler: str, directory: Path) -> str:
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for mode in ("-std=c23", "-std=c2x"):
        if run([compiler, mode, "-fsyntax-only", str(probe)]).returncode == 0:
            return mode
    raise FirstError("compiler-no-C23-mode:" + compiler)


def compiler_check(compiler_name: str, header: str) -> None:
    compiler = shutil.which(compiler_name)
    require(compiler is not None, "missing-compiler:" + compiler_name)
    with tempfile.TemporaryDirectory(prefix="swapz-round077-delay-") as folder:
        directory = Path(folder)
        mode = compiler_mode(compiler, directory)
        # The exact original inline body and exact original fixture call are
        # compiled, not a replacement delay function or a mocked zswap tree.
        common = (
            "#include <stdio.h>\n"
            "static unsigned int calls;\n"
            "static unsigned long observed_min, observed_max;\n"
            "#define TASK_UNINTERRUPTIBLE 2U\n"
            "void usleep_range_state(unsigned long min, unsigned long max,\n"
            "                         unsigned int state)\n"
            "{\n"
            "    if (state != TASK_UNINTERRUPTIBLE) { calls = 999U; return; }\n"
            "    ++calls; observed_min = min; observed_max = max;\n"
            "}\n"
        )
        main = (
            "\nint main(void)\n{\n"
            "    " + CALL + "\n"
            "    if (calls != 1U || observed_min != 1000UL ||\n"
            "        observed_max != 2000UL)\n"
            '        { fputs("FIRST_ERROR original-delay-call\\n", stderr); return 3; }\n'
            "    return 0;\n"
            "}\n"
        )
        flags = [
            compiler, mode, "-O1", "-g", "-Wall", "-Wextra",
            "-Wconversion", "-Wshadow", "-Werror",
            "-Werror=implicit-function-declaration",
            "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        ]
        positive = directory / "positive.c"
        executable = directory / "positive"
        positive.write_text(common + "\n" + header + "\n" + main)
        compiled = run([*flags, str(positive), "-o", str(executable)])
        require(compiled.returncode == 0,
                compiler_name + ":real-inline-positive-compile:" +
                (compiled.stderr.splitlines() or ["unknown"])[0][:160])
        executed = run([str(executable)])
        require(executed.returncode == 0 and not executed.stderr,
                compiler_name + ":real-inline-execution:" +
                (executed.stderr.splitlines() or ["unknown"])[0][:160])
        # Missing declaration MUST fail in the compiler due to usleep_range,
        # not because the positive test's other symbols are unresolved.
        negative = directory / "missing-declaration.c"
        negative.write_text(common + main)
        rejected = run([*flags, "-fsyntax-only", str(negative)])
        require(rejected.returncode != 0 and
                "usleep_range" in rejected.stderr and
                re.search(r"implicit declaration|undeclared function",
                          rejected.stderr, re.IGNORECASE) is not None,
                compiler_name + ":missing-original-declaration-not-rejected")
        print("PASS ROUND077_ORIGINAL_DELAY_" + compiler_name.upper() +
              " original_pinned_inline_compiled_executed=1 "
              "missing_declaration_Werror_compile_negative=1 "
              "strict_ASan_UBSan=YES", flush=True)


def main() -> int:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument("--linux-root", required=True, type=Path)
    arguments = argument_parser.parse_args()
    try:
        linux = arguments.linux_root
        git = run(["git", "-C", str(linux), "rev-parse", "HEAD"])
        require(git.returncode == 0 and not git.stderr,
                "original-source-git-ref")
        original = (linux / "mm/zswap.c").read_bytes()
        delay = (linux / "include/linux/delay.h").read_bytes()
        fixture = FIXTURE.read_text(encoding="utf-8")
        check_declaration(git.stdout.strip(), original, delay, fixture)
        # Source-accurate parser negatives. No changes to pristine Linux.
        negatives = (
            (PIN[:-1] + "0", original, delay, fixture),
            (PIN, original + b"tamper", delay, fixture),
            (PIN, original, delay + b"tamper", fixture),
            (PIN, original, delay, fixture.replace(INCLUDE, "/* missing */")),
            (PIN, original, delay, fixture.replace(SUITE, "/* missing */")),
            (PIN, original, delay, fixture.replace(CASE, "/* missing */")),
            (PIN, original, delay, fixture.replace(
                "/* ROUND073_ORIGINAL_READER_PIN_GC_BEGIN", "/* missing")),
            (PIN, original, delay, fixture.replace(CALL, "/* no call */")),
        )
        for index, row in enumerate(negatives):
            try:
                check_declaration(*row)
            except FirstError:
                continue
            raise FirstError("original-header-source-mutant-survived:" + str(index))
        for name in ("gcc", "clang"):
            compiler_check(name, ORIGINAL_INLINE)
        print("PASS ROUND077_ORIGINAL_DELAY_SOURCE_PIN=YES "
              "original_linux_header_blob=YES negative_source_provenance=8 "
              "gcc_clang_executed=2 missing_include_compile_negatives=2 "
              "AUTH0 PHASE_A=BLOCKED native_KUnit=SEPARATE_JOB", flush=True)
        return 0
    except (FirstError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, FirstError) else type(error).__name__
        print("ROUND077_ORIGINAL_DELAY_FIRST_ERROR " + reason[:225],
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
