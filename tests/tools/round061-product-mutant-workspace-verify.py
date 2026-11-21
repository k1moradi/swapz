#!/usr/bin/env python3
"""Round061: exercise the genuine runner's GCC/Clang workspace control flow.

C subprocesses are stubbed ONLY in this unit regression. The unchanged
Round057 runner separately compiles/executes real product C and 10 mutants.
"""
import contextlib
import errno
import importlib.util
import io
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tests/tools/round057-transaction-product.py"
BASELINE = ("PASS product_raw_authority=7 map_bytes=20 import_record_bytes=96 "
            "descriptor_limit=8 staging_limit=2 NOT_AUTH=1 PHASE_A=BLOCKED\n")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError("ROUND061_MUTANT_WORKSPACE_FIRST_ERROR " + message)




def require_owned_mutant_workspace(binary: Path, *,
                                   altered_source=None, altered_header=None) -> Path:
    """The C override is a file; the header override is already a directory."""
    check((altered_source is None) != (altered_header is None),
          "mutant source/header type ambiguous")
    if altered_source is not None:
        source_file = Path(altered_source)
        check(source_file.is_file(), "mutated C source is not a file")
        workspace = source_file.parent
    else:
        workspace = Path(altered_header)
        check(workspace.is_dir(), "mutated header override is not a directory")
    check(workspace.parent == binary.parent and
          workspace.name.startswith("mutant-") and
          workspace.resolve().parent == binary.parent.resolve(),
          "mutant escaped compiler-owned directory")
    return workspace


def safe_first_error(error: Exception, *, evidence_root: Path = ROOT) -> str:
    """Print finite failure metadata, retaining untrusted exception only privately."""
    evidence = "private-evidence-unavailable"
    try:
        evidence_directory = evidence_root / ".private"
        if not evidence_directory.is_symlink():
            evidence_directory.mkdir(mode=0o700, exist_ok=True)
            if (evidence_directory.is_dir() and
                    not evidence_directory.is_symlink()):
                evidence_directory.chmod(0o700)
                with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", dir=evidence_directory,
                        prefix="round062-workspace-", suffix=".log",
                        delete=False) as details:
                    os.fchmod(details.fileno(), stat.S_IRUSR | stat.S_IWUSR)
                    details.write((type(error).__name__ + ": " + str(error))[:65536])
                    details.flush()
                    evidence = Path(details.name).relative_to(evidence_root).as_posix()
    except OSError:
        pass
    return ("FIRST_ERROR round061-workspace: " + type(error).__name__ +
            " evidence=" + evidence)


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
                workspace = require_owned_mutant_workspace(
                    binary, altered_source=altered_source,
                    altered_header=altered_header)
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


        # Use the SAME path oracle as record_build: real source C is a FILE,
        # while the header override is a DIRECTORY that already owns its file.
        compiler_root = fixture_root / "gcc"
        compiler_root.mkdir()
        escaped_workspace = fixture_root / "escaped" / "mutant-0"
        escaped_workspace.mkdir(parents=True)
        (escaped_workspace / "authority.c").write_text(
            mutant_lookup["short_publish"][0])
        (escaped_workspace / "flush-qual.h").write_text(
            mutant_lookup["fua_error_ignored"][0])

        def require_escape_rejection(mutant_name, *, altered_source=None,
                                     altered_header=None):
            previously_compiled = len(compiled)
            try:
                record_build("gcc", mutant_name, compiler_root / "spine",
                             altered_source=altered_source,
                             altered_header=altered_header)
            except AssertionError as error:
                check(str(error) ==
                      "ROUND061_MUTANT_WORKSPACE_FIRST_ERROR "
                      "mutant escaped compiler-owned directory",
                      "incorrect negative workspace first error")
            else:
                check(False, "escaped mutation accepted")
            check(len(compiled) == previously_compiled,
                  "escaped mutation registered as compiled")

        require_escape_rejection(
            "short_publish",
            altered_source=escaped_workspace / "authority.c")
        require_escape_rejection(
            "fua_error_ignored", altered_header=escaped_workspace)
        # A lexical child path must not pass if its directory resolves outside.
        symlink_workspace = compiler_root / "mutant-escape"
        symlink_workspace.symlink_to(escaped_workspace, target_is_directory=True)
        require_escape_rejection(
            "fua_error_ignored", altered_header=symlink_workspace)

        # Real top-level failure output never echoes a host path or secret;
        # only the private mode-0600 file contains the detailed exception.
        secret_host_error = AssertionError(
            "untrusted /tmp/PRIVATE_TOKEN_HOST_PATH token=VERY_SECRET")
        safe_error = safe_first_error(secret_host_error, evidence_root=fixture_root)
        check(safe_error.startswith(
            "FIRST_ERROR round061-workspace: AssertionError evidence=.private/"),
            "test-first-error missing bounded evidence")
        check("PRIVATE_TOKEN_HOST_PATH" not in safe_error and
              "VERY_SECRET" not in safe_error and
              str(fixture_root) not in safe_error,
              "test-first-error leaked untrusted details")
        error_evidence = fixture_root / safe_error.split(" evidence=", 1)[1]
        check(error_evidence.is_file() and
              stat.S_IMODE(error_evidence.stat().st_mode) == 0o600 and
              stat.S_IMODE(error_evidence.parent.stat().st_mode) == 0o700,
              "test-first-error diagnostics not private")
        check("PRIVATE_TOKEN_HOST_PATH" in error_evidence.read_text(),
              "test-first-error private details not retained")

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
          "baseline_and_mutant_runs=12 escape_negatives=3 "
          "host_path_leak=NO private_mode=0600 real_C_suite=SEPARATE")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError, RuntimeError,
            subprocess.TimeoutExpired) as error:
        print(safe_first_error(error), file=sys.stderr)
        sys.exit(1)
