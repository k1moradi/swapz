#!/usr/bin/env python3
"""Rootless C23 sanitizer oracle for synthetic, already MM-origin swap arrivals.

No kernel module, swap partition, true pressure, DM activation or external I/O.
The compiled model never authenticates the source-to-DM compressed bridge.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round052-natural-pressure-scheduling.c"
CODEC = ROOT / "src/kernel/codec.h"
EXPECTED = re.compile(r"PASS events=(\d+) hostile=(\d+) capacity_blocks=16,32,64 "
                      r"NOT_AUTH=1 PHASE_A=BLOCKED synthetic_only=1\Z")


def invoke(command: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True,
                              check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"bounded command unavailable: {command[0]}") from error


def check_source_contract() -> None:
    header = CODEC.read_text(encoding="utf-8")
    source = FIXTURE.read_text(encoding="utf-8")
    anchors = ("#define SWAPZ_BLOCK_BYTES 4096U",
               "#define SWAPZ_MAX_BLOCKS 4U",
               "#define SWAPZ_MAX_COMPRESSED 3568U")
    if any(anchor not in header for anchor in anchors):
        raise RuntimeError("actual swapz codec bounds are no longer the modeled contract")
    for anchor in ("#define SOURCE_MAPPED_AUTHENTICATED 0",
                   "#define DIRECT_COMPRESSED_HANDOFF 0",
                   "#define FORCED_RAW_BYPASS 0",
                   "static int test_hostile_future_gates(void)"):
        if anchor not in source:
            raise RuntimeError("synthetic safety contract changed")


def compiler_standard(compiler: str) -> str:
    for standard in ("-std=c23", "-std=c2x"):
        candidate = subprocess.run([compiler, standard, "-x", "c", "-fsyntax-only", "-"],
                                   input="int main(void) { return 0; }\n",
                                   capture_output=True, text=True, check=False, timeout=10)
        if candidate.returncode == 0:
            return standard
    raise RuntimeError("compiler lacks C23 language support")


def run_both_compilers() -> None:
    with tempfile.TemporaryDirectory(prefix="swapz-round052-model-") as location:
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if compiler is None:
                raise RuntimeError(f"required compiler unavailable: {name}")
            binary = str(Path(location) / f"fixture-{name}")
            standard = compiler_standard(compiler)
            compile_result = invoke([
                compiler, standard, "-O1", "-g", "-Wall", "-Wextra",
                "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", str(FIXTURE), "-o", binary,
            ])
            if compile_result.returncode:
                raise RuntimeError(f"{name} strict sanitizer compile failed: " +
                                   compile_result.stderr[:1200].splitlines()[0])
            test_result = invoke([binary], timeout=30)
            if test_result.returncode:
                details = (test_result.stderr or test_result.stdout).splitlines()
                raise RuntimeError(f"{name} sanitizer execution failed: " +
                                   (details[0][:200] if details else "no output"))
            match = EXPECTED.fullmatch(test_result.stdout.strip())
            if match is None or int(match.group(1)) < 120 or int(match.group(2)) < 10:
                raise RuntimeError(f"{name} did not prove bounded 120+ events/10+ violations")
            print(f"PASS {name} C23 ASan+UBSan {test_result.stdout.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", required=True)
    parser.parse_args()
    try:
        check_source_contract()
        run_both_compilers()
    except (RuntimeError, UnicodeError, OSError) as error:
        print(f"FIRST_ERROR round052-natural-pressure: {str(error)[:300]}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
