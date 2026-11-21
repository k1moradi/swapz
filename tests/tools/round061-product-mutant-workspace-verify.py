#!/usr/bin/env python3
"""Round061: exercise the genuine runner's GCC/Clang workspace control flow.

C subprocesses are stubbed ONLY in this unit regression. The unchanged
Round057 runner separately compiles/executes real product C and 10 mutants.
"""
import contextlib
import errno
import importlib.util
import io
from pathlib import Path
import stat
import subprocess
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/tools/round057-transaction-product.py"
BASELINE = ("PASS product_raw_authority=7 map_bytes=20 import_record_bytes=96 "
            "descriptor_limit=8 staging_limit=2 NOT_AUTH=1 PHASE_A=BLOCKED\n")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError("ROUND061_MUTANT_WORKSPACE_FIRST_ERROR " + message)


def main() -> None:
    specification = importlib.util.spec_from_file_location(
        "round057_transaction_product", RUNNER)
    check(specification is not None and specification.loader is not None,
          "real runner import unavailable")
    runner = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(runner)
    with tempfile.TemporaryDirectory(prefix="round061-mutant-workspace-") as temp:
        fixture_root = Path(temp)
        kernel = fixture_root / "src/kernel"
        kernel.mkdir(parents=True)
        source_fragments: dict[str, list[str]] = {}
        for name, path, original, replacement, case in runner.MUTANTS:
            source_fragments.setdefault(path, []).append(original)
        for path, fragments in source_fragments.items():
            (kernel / path).write_text("\n\n".join(fragments) + "\n")
        runner.KERNEL = kernel
        runner.source_boundaries = lambda: None

        compiled = []
        executed = []
        mutated_workspaces = set()
        mutant_lookup = {name: (replacement, path)
                         for name, path, original, replacement, case in runner.MUTANTS}

        def record_build(compiler, name, binary, *, altered_source=None,
                         altered_header=None):
            compiler_name = binary.parent.name
            check(compiler_name in ("gcc", "clang") and
                  Path(compiler).name in ("gcc", "clang"),
                  "compiler or binary escaped isolated directory")
            check(binary.name == "spine", "unexpected binary")
            if name == compiler_name:
                check(altered_source is None and altered_header is None,
                      "baseline source incorrectly mutated")
            else:
                check(name in mutant_lookup, "unknown semantic mutant")
                altered = altered_source or altered_header
                check(altered is not None, "mutant missing altered source copy")
                workspace = Path(altered).parent
                check(workspace.parent == binary.parent and
                      workspace.name.startswith("mutant-"),
                      "mutant escaped compiler-owned directory")
                check((compiler_name, workspace.name) not in mutated_workspaces,
                      "reused compiler mutant directory")
                mutated_workspaces.add((compiler_name, workspace.name))
                replacement, original_path = mutant_lookup[name]
                altered_file = (Path(altered_source) if altered_source else
                                Path(altered_header) / Path(original_path).name)
                check(replacement in altered_file.read_text(),
                      "mutated actual-source anchor not copied")
            compiled.append((compiler_name, name))

        def record_execution(command, *, stdin=None):
            binary = Path(command[0])
            check(binary.name == "spine" and binary.parent.name in ("gcc", "clang"),
                  "execution escaped compiler binary")
            executed.append((binary.parent.name, tuple(command[1:])))
            if len(command) == 1:
                return SimpleNamespace(returncode=0, stdout=BASELINE, stderr="")
            check(len(command) == 2 and
                  command[1] in [mutant[-1] for mutant in runner.MUTANTS],
                  "unknown mutant execution")
            return SimpleNamespace(returncode=1, stdout="",
                                   stderr="FIRST_ERROR " + command[1] + "\n")

        runner.build = record_build
        runner.execute = record_execution
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            runner.main()
        check(len(compiled) == 12 and len(executed) == 12,
              "two baseline and ten mutant executions not reached")
        check(len(mutated_workspaces) == 10, "GCC/Clang mutant scratch collided")
        for compiler_name in ("gcc", "clang"):
            for index in range(5):
                check((compiler_name, "mutant-" + str(index)) in mutated_workspaces,
                      "compiler-specific mutant directory absent")
            check("PASS " + compiler_name + " actual-source semantic mutants=5" in
                  output.getvalue(), "compiler loop truncated")

        runner.ROOT = fixture_root
        private_name = str(fixture_root / "untrusted-host-path" / "mutant-0")
        exception = FileExistsError(errno.EEXIST, "File exists", private_name)
        first_error = runner.safe_external_failure(exception)
        check("host I/O failure errno=17 evidence=.private/" in first_error,
              "host collision lacked safe first cause")
        check(private_name not in first_error and str(fixture_root) not in first_error,
              "absolute temporary host path leaked")
        saved = fixture_root / first_error.split(" evidence=", 1)[1]
        check(saved.is_file() and stat.S_IMODE(saved.stat().st_mode) == 0o600,
              "host exception not retained privately mode 0600")
        check(stat.S_IMODE(saved.parent.stat().st_mode) == 0o700 and
              private_name in saved.read_text(),
              "private evidence permissions or contents incorrect")
        timeout_error = runner.safe_external_failure(
            subprocess.TimeoutExpired([private_name], timeout=1))
        check("child command timeout evidence=.private/" in timeout_error and
              private_name not in timeout_error and
              str(fixture_root) not in timeout_error,
              "timeout command leaked absolute path")
    print("PASS Round061 compiler_workspaces=2 numbered_mutants=10 "
          "baseline_and_mutant_runs=12 host_path_leak=NO private_mode=0600 "
          "real_C_suite=SEPARATE")


if __name__ == "__main__":
    main()
