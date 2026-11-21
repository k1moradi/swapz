#!/usr/bin/env python3
"""Round059: deterministic hostile GCC/Clang first source diagnostic reporting.

Never invokes owner Make, privileged commands, devices or real pressure.
Injects realistic failed compiler output into the ACTUAL Round057 build()
failure path, requiring actionable first source error and private 0600 logs.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
REPORTER = ROOT / "tests/tools/round057-transaction-product.py"


def check(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError("ROUND059_FIRST_ERROR_REPORTER_FIRST_ERROR " + reason)


def main() -> None:
    module_spec = importlib.util.spec_from_file_location(
        "round057_transaction_reporter", REPORTER)
    check(module_spec is not None and module_spec.loader is not None,
          "source reporter import missing")
    reporter = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(reporter)
    for compiler in ("gcc", "clang"):
        with tempfile.TemporaryDirectory(prefix="round059-diagnostic-") as temp:
            work = Path(temp)
            source = work / "src/kernel/zswap-import-codec.h"
            error_message = (
                "linux/lzo.h: No such file or directory" if compiler == "gcc"
                else "'linux/lzo.h' file not found"
            )
            stderr = (
                "In file included from /external/unsafe/build/source.h:12:\n"
                "authorization=PRIVATE_SECRET_DO_NOT_LOG token=CANARY\n" +
                str(source) + ":24:10: fatal error: " + error_message + "\n" +
                str(source) + ":1:1: error: later secondary error\n"
            )
            reporter.ROOT = work
            reporter.execute = lambda command, text=stderr: SimpleNamespace(
                returncode=1, stdout="", stderr=text)
            try:
                reporter.build(compiler, compiler, work / "spine")
            except RuntimeError as error:
                summary = str(error)
            else:
                raise AssertionError("ROUND059_FIRST_ERROR_REPORTER_FIRST_ERROR "
                                     "compiler failure was silently accepted")
            check("src/kernel/zswap-import-codec.h:24:10" in summary,
                  f"{compiler} missing first repository-relative source")
            check("fatal error: " + error_message in summary,
                  f"{compiler} true missing header hidden by included-from")
            check("later secondary error" not in summary,
                  f"{compiler} printed secondary diagnostic instead")
            check("PRIVATE_SECRET_DO_NOT_LOG" not in summary and
                  "CANARY" not in summary and
                  str(work) not in summary and "/external/" not in summary,
                  f"{compiler} leaked untrusted compiler text or absolute paths")
            check("evidence=.private/round057-transaction-" in summary,
                  f"{compiler} missing private evidence path")
            evidence = summary.split(" evidence=", 1)[1]
            check(not evidence.startswith("/") and ".." not in evidence,
                  f"{compiler} unsafe evidence path")
            details_file = work / evidence
            check(details_file.is_file() and
                  stat.S_IMODE(details_file.stat().st_mode) == 0o600,
                  f"{compiler} private log not owned mode 0600")
            check(stat.S_IMODE((work / ".private").stat().st_mode) == 0o700,
                  f"{compiler} private directory not 0700")
            check(details_file.read_text() == stderr,
                  f"{compiler} first full failure not kept privately")
            print("ROUND059_FIRST_CAUSE_REPORTER_HOSTILE_PASS compiler=" +
                  compiler + " first_source=src/kernel/zswap-import-codec.h:24:10 "
                  "private=0600 no_host_paths=YES no_secret=YES", flush=True)
    print("ROUND059_TRANSACTION_FIRST_CAUSE_C_PASS hostile_compilers=2 "
          "first_error_not_truncated=YES source_authenticated=0 physical_io=0",
          flush=True)


if __name__ == "__main__":
    main()
