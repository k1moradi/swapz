#!/usr/bin/env python3
"""Agent8: source-digest-locked, rootless DM lower ordering HOST MODEL gate.

The production kernel DM body cannot be compiled in this C23 userspace test.
The sha-1 Git blob check makes the modeled source relationship explicit and
fails closed on source changes. The fixture never makes physical durability
or kernel bio_endio claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SOURCE_BLOB_SHA = "f1cab252cd990190646c82da81378d1563475826"
MUTANTS = range(1, 16)
COMPILERS = ("gcc", "clang")
SCENARIOS = {
    1: "no-early-ack",
    2: "write-before-fua",
    3: "lower-eio-terminal",
    4: "failed-fua-no-map",
    5: "duplicate-exactly-once",
    6: "stop-late-ignored",
    7: "stale-abort",
    8: "gc-pinned-old-extent",
    9: "lower-error-wins-cleanup",
    10: "no-write-before-preflush",
    11: "reject-nonextent-size",
    12: "partial-lower-abort",
    13: "flush-before-write-ignored",
    14: "older-must-finish-first",
    15: "failed-fua-no-map",
}

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/dm-target.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-lower-fua-ordering.c"


def require_source_identity() -> None:
    source_bytes = SOURCE.read_bytes()
    git_object = b"blob " + str(len(source_bytes)).encode("ascii") + b"\0" + source_bytes
    actual_digest = hashlib.sha1(git_object).hexdigest()
    if actual_digest != SOURCE_BLOB_SHA:
        raise RuntimeError(
            "production source drift: src/kernel/dm-target.c git blob "
            f"{actual_digest}, expected {SOURCE_BLOB_SHA}; requalify instead of assuming"
        )
    source_text = source_bytes.decode("utf-8")
    # Exact-body excerpts plus the digest anchor the model's boundaries to
    # the real source rather than an independent fake DM table/API.
    anchors = (
        "static void swapz_async_lower_write_done(",
        "lower_error = error ? -EIO : 0;",
        "WRITE_ONCE(inflight->lower_error, lower_error);",
        "complete(&inflight->lower_done);",
        "static int swapz_submit_inflight_write(",
        ".bi_opf = REQ_OP_WRITE | REQ_SWAP,",
        "error = swapz_dm_io(&req, &region, NULL);",
        "static int swapz_finalize_inflight_write(",
        "lower_error = READ_ONCE(inflight->lower_error);",
        "swapz_engine_complete_batched_run(",
        "if (error || committed != inflight->count)",
        "static noinline int swapz_lower(",
        "error = swapz_dm_io(&req, &region, &bitmap);",
        "static int swapz_kernel_lower_flush(void *opaque)",
        "return blkdev_issue_flush(ctx->backing->bdev);",
        "static int swapz_issue_flush(void *opaque)",
        "swapz_flush_accounted(&ctx->flush_meter,",
        "static int swapz_lower_write(void *opaque,",
        "swapz_write_flush_before_publish(error, ctx->prepublication_fua,",
        "static int swapz_gc_flush(struct swapz_dm *ctx)",
        "static int swapz_gc_move_raw(struct swapz_dm *ctx,",
        "ctx->prepublication_fua = !!(bio->bi_opf & REQ_FUA);",
        "error = swapz_issue_flush(ctx);",
        "if (bio->bi_opf & REQ_PREFLUSH) {",
        "swapz_complete(bio, error);",
    )
    for anchor in anchors:
        if anchor not in source_text:
            raise RuntimeError(f"source anchor absent: {anchor}")


def bounded_failure(message: str) -> None:
    # Fail-only first diagnostic; no raw child stderr or private paths.
    print(f"FAIL round073-agent8: {message}", file=sys.stderr)


def execute(compilers: tuple[str, ...], report_path: Path | None) -> int:
    tested = {}
    with tempfile.TemporaryDirectory(prefix="round073-agent8-") as temp_dir:
        for compiler in compilers:
            baseline_count = 0
            rejected = 0
            for mutant in (0, *MUTANTS):
                executable = Path(temp_dir) / f"{compiler}-mutant{mutant}"
                command = [compiler, "-std=c2x", "-O1", "-g", "-Wall", "-Wextra",
                           "-Wpedantic", "-Wconversion", "-Wshadow", "-Werror",
                           "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                           f"-DMUTANT_ID={mutant}", str(FIXTURE), "-o", str(executable)]
                compiled = subprocess.run(command, capture_output=True, text=True, check=False)
                if compiled.returncode != 0:
                    bounded_failure(f"{compiler} mutant={mutant} compilation rc={compiled.returncode} "
                                    f"first={compiled.stderr.splitlines()[0] if compiled.stderr else 'no diagnostic'}")
                    return 1
                environment = os.environ.copy()
                environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
                environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=0"
                completed = subprocess.run([str(executable)], capture_output=True,
                                           text=True, check=False, env=environment)
                if mutant == 0:
                    if completed.returncode != 0 or not completed.stdout.startswith("PASS model"):
                        bounded_failure(f"{compiler} baseline rc={completed.returncode} "
                                        f"first={(completed.stderr or completed.stdout).splitlines()[:1]}")
                        return 1
                    baseline_count += 1
                else:
                    expected = f"NEGATIVE_DETECTED mutant={mutant} case={SCENARIOS[mutant]} "
                    if completed.returncode != 1 or expected not in completed.stderr or "Sanitizer" in completed.stderr:
                        bounded_failure(f"{compiler} mutant={mutant} survived or crashed "
                                        f"rc={completed.returncode} first={completed.stderr.splitlines()[:1]}")
                        return 1
                    rejected += 1
            tested[compiler] = {"baseline_executed_pass": baseline_count,
                                "semantic_mutants_compiled_executed_rejected": rejected,
                                "asan_ubsan": True, "c_standard": "c2x", "warnings_as_errors": True}
    report = {"source_anchor": "src/kernel/dm-target.c", "source_git_blob_sha": SOURCE_BLOB_SHA,
              "mode": "userspace deterministic source-locked model; no native original kernel",
              "compilers": tested, "total_mutants_per_compiler": len(MUTANTS),
              "physical_io": False, "native_kernel_executed": False}
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = ", ".join(
        f"{compiler} {data['semantic_mutants_compiled_executed_rejected']}/15"
        for compiler, data in tested.items()
    )
    print(f"PASS agent8 source-locked HOST MODEL: {summary}; "
          "ASan+UBSan; no physical durability assertion")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    parser.add_argument("--compiler", action="append", choices=COMPILERS)
    arguments = parser.parse_args()
    try:
        require_source_identity()
    except (OSError, RuntimeError, UnicodeError) as error:
        bounded_failure(str(error))
        return 1
    return execute(tuple(arguments.compiler or COMPILERS), arguments.report)


if __name__ == "__main__":
    sys.exit(main())
