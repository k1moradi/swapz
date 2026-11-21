#!/usr/bin/env python3
"""Compile and execute the comparative synthetic model and named C mutants."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round054-natural-mm-coalescing.c"
MUTANTS = (
    ("queue", "disk.count >= QUEUE", "disk.count >= QUEUE - 1U", "queue_capacity"),
    ("deadline", "disk.tick - disk.pending[0].arrival >= WAIT",
     "disk.tick - disk.pending[0].arrival > WAIT", "deadline_retire"),
    ("fifo", "if (!disk.coalesce || payload_length(first)",
     "if (false || payload_length(first)", "fifo_single"),
    ("reserve", "!disk.used[start + i] && !reserved(start + i)",
     "!disk.used[start + i] && (!reserved(start + i) || !disk.coalesce)", "reserve_capacity"),
    ("callback", "!ticket.active || token != ticket.token",
     "!ticket.active || (token != ticket.token && token != ticket.token - 1U)", "callback_late"),
    ("callback", "bool valid = durable && ticket.epoch == disk.epoch;",
     "bool valid = (durable || ticket.active) && ticket.epoch == disk.epoch;", "callback_eio"),
    ("gc", "event->epoch == disk.epoch", "event->epoch <= disk.epoch", "gc_stale"),
    ("input", "event->bytes != SWAPZ_BLOCK_BYTES", "event->bytes > SWAPZ_BLOCK_BYTES", "raw_size"),
    ("cancel", "!disk.closed && !event->cancel && event->epoch",
     "!disk.closed && (!event->cancel || event->native) && event->epoch", "cancel_swapoff"),
    ("padding", "while (blocks > count)", "while (blocks > count && count > 3U)", "padding_no_amplification"),
)


def invoke(command, *, input_text=None):
    return subprocess.run(command, input=input_text, capture_output=True, text=True,
                          check=False, timeout=90, env={**os.environ,
                          "ASAN_OPTIONS": "halt_on_error=1", "UBSAN_OPTIONS": "halt_on_error=1"})


def checked_compile(compiler, standard, source, binary):
    result = invoke([compiler, standard, "-O1", "-g", "-Wall", "-Wextra", "-Wconversion",
                     "-Wshadow", "-Werror", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                     "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-I", str(FIXTURE.parent),
                     str(source), "-o", str(binary)])
    if result.returncode:
        raise RuntimeError("compile failed: " + (result.stderr.splitlines() or ["no diagnostic"])[0])


def run():
    source = FIXTURE.read_text(encoding="utf-8")
    header = (ROOT / "src/kernel/codec.h").read_text(encoding="utf-8")
    for anchor in ("#define SWAPZ_BLOCK_BYTES 4096U", "#define SWAPZ_MAX_BLOCKS 4U",
                   "#define SWAPZ_MAX_COMPRESSED 3568U"):
        if anchor not in header:
            raise RuntimeError("changed product geometry")
    for anchor in ("#define SOURCE_MAPPED_AUTHENTICATED 0", "#define DIRECT_COMPRESSED_HANDOFF 0",
                   "#define FORCED_RAW_BYPASS 0"):
        if anchor not in source:
            raise RuntimeError("changed no-auth invariant")
    baseline = None
    with tempfile.TemporaryDirectory(prefix="swapz-coalescing-") as temporary:
        work = Path(temporary)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError(f"missing {name}")
            standard = next((flag for flag in ("-std=c23", "-std=c2x") if invoke(
                [compiler, flag, "-x", "c", "-fsyntax-only", "-"],
                input_text="int main(void) { return 0; }\n").returncode == 0), None)
            if not standard:
                raise RuntimeError(f"{name} C23 unavailable")
            binary = work / name
            checked_compile(compiler, standard, FIXTURE, binary)
            result = invoke([str(binary)])
            if result.returncode or result.stderr or not re.fullmatch(
                    r"PASS traces=48 directed=9 [^\n]+ NOT_AUTH=1 PHASE_A=BLOCKED\nMATCHED [^\n]+\n", result.stdout):
                raise RuntimeError(f"{name} baseline: {result.returncode} {result.stderr[:240]}")
            if baseline is not None and baseline != result.stdout:
                raise RuntimeError("compiler counter disagreement")
            baseline = result.stdout
            print(f"{name} {standard} ASan+UBSan {baseline}", end="")
            for index, (case, original, replacement, oracle) in enumerate(MUTANTS):
                if source.count(original) != 1:
                    raise RuntimeError(f"ambiguous mutation {index}: {oracle}")
                mutant = work / f"mutant-{index}.c"
                mutant.write_text(source.replace(original, replacement, 1), encoding="utf-8")
                checked_compile(compiler, standard, mutant, binary)
                rejected = invoke([str(binary), case])
                if rejected.returncode != 1 or rejected.stdout or rejected.stderr != f"FIRST_ERROR {oracle}\n":
                    raise RuntimeError(f"{name} mutant {index} {oracle}: unexpected exit={rejected.returncode} "
                                       f"diagnostic={rejected.stderr[:200]}")
            print(f"{name} compiled_and_executed_semantic_mutants={len(MUTANTS)}")


if __name__ == "__main__":
    try:
        run()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"FIRST_ERROR round054-coalescing: {str(error)[:300]}", file=sys.stderr)
        sys.exit(1)
