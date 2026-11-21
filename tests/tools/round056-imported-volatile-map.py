#!/usr/bin/env python3
"""Rootless dual-C-compiler/semantic mutation proof for disabled imported-map C model."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round056-imported-volatile-map.c"
MUTANTS = (
    ("durability", "record->durable = fua_completed || explicit_flush_completed;",
     "(void)fua_completed; (void)explicit_flush_completed; record->durable = lower_ok;", "durability_required"),
    ("replay", "if (!record->reserved || record->published || state.closing ||",
     "if (!record->reserved || false || state.closing ||", "one_ack"),
    ("pin", "if (record->reader_pins)", "if (false)", "decoder_pinned"),
    ("crc", "if (crc32c(compressed, record->length) != record->compressed_crc)",
     "if (false)", "corruption_no_raw_fallback"),
    ("gc", "if (!durable || !commit_current || state.closing)",
     "(void)durable; if (false || !commit_current || state.closing)", "gc_durable"),
    ("tag", "record->representation != IMPORT_REPRESENTATION ||",
     "false ||", "import_tag_required"),
)


def execute(command, *, stdin=None):
    return subprocess.run(command, input=stdin, text=True, capture_output=True,
                          timeout=35, check=False,
                          env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                               "UBSAN_OPTIONS": "halt_on_error=1"})


def build(compiler, standard, source, output):
    result = execute([compiler, standard, "-O1", "-g", "-Wall", "-Wextra",
                      "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                      "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie",
                      "-no-pie", "-I", str(FIXTURE.parent), str(source), "-o", str(output), "-llz4", "-lcrypto"])
    if result.returncode:
        raise RuntimeError("strict compiler failure: " + (result.stderr.splitlines() or ["unknown"])[0])


def main():
    header = (ROOT / "src/kernel/codec.h").read_text()
    source = FIXTURE.read_text()
    for anchor in ("#define SWAPZ_BLOCK_BYTES 4096U", "#define SWAPZ_MAX_BLOCKS 4U",
                   "#define SWAPZ_MAX_COMPRESSED 3568U"):
        if anchor not in header:
            raise RuntimeError("production geometry changed")
    for anchor in ("#define SOURCE_MAPPED_AUTHENTICATED 0", "#define DIRECT_COMPRESSED_HANDOFF 0",
                   "#define FORCED_RAW_BYPASS 0"):
        if anchor not in source:
            raise RuntimeError("import activation invariant changed")
    expected = None
    with tempfile.TemporaryDirectory(prefix="swapz-imported-map-") as work:
        for compiler_name in ("gcc", "clang"):
            compiler = shutil.which(compiler_name)
            if not compiler:
                raise RuntimeError(f"missing required compiler {compiler_name}")
            standard = next((value for value in ("-std=c23", "-std=c2x") if
                             execute([compiler, value, "-x", "c", "-fsyntax-only", "-"],
                                     stdin="int main(void) { return 0; }\n").returncode == 0), None)
            if standard is None:
                raise RuntimeError(f"missing C23 mode for {compiler_name}")
            binary = Path(work) / "test"
            build(compiler, standard, FIXTURE, binary)
            result = execute([str(binary)])
            if result.returncode or result.stderr or not re.fullmatch(
                    r"PASS lifecycle=\d+ bounds=\d+ descriptor_bytes=\d+ map_bytes=\d+ "
                    r"live_limit=8 staging_limit=2 NOT_AUTH=1 PHASE_A=BLOCKED\n", result.stdout):
                raise RuntimeError(f"{compiler_name} baseline failure: {result.stderr[:250]}")
            if expected is not None and expected != result.stdout:
                raise RuntimeError("compiler ABI/counter disagreement")
            expected = result.stdout
            print(f"PASS {compiler_name} {standard} strict ASan+UBSan {result.stdout.strip()}")
            for i, (test, original, replacement, name) in enumerate(MUTANTS):
                if source.count(original) != 1:
                    raise RuntimeError(f"non-unique mutant anchor {name}")
                mutant = Path(work) / f"mutant-{i}.c"
                mutant.write_text(source.replace(original, replacement, 1))
                build(compiler, standard, mutant, binary)
                rejection = execute([str(binary), test])
                if rejection.returncode != 1 or rejection.stdout or rejection.stderr != f"FIRST_ERROR {name}\n":
                    raise RuntimeError(f"{compiler_name} mutation {name} not semantically killed: "
                                       f"exit={rejection.returncode} error={rejection.stderr[:150]}")
            print(f"PASS {compiler_name} semantic_mutations_compiled_and_executed={len(MUTANTS)}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR imported-map: {str(error)[:280]}", file=sys.stderr)
        sys.exit(1)
