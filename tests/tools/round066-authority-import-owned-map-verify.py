#!/usr/bin/env python3
"""Round066 ROOTLESS real linked authority allocator/import record qualification.

Compiles original production authority.c + codec.c with only the test guard.
Each semantic mutant changes the REAL C implementation, must compile cleanly
under GCC/Clang ASan+UBSan and must execute the named first-error case.
No physical disk, native source BIO, module load or upper ACK.
"""
from pathlib import Path
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round066-import-disk-actual-authority.c"
SOURCE = KERNEL / "authority.c"

# A failed build is not a semantic-mutant kill. Each unique altered real-C
# source must compile and its own one-case runtime oracle must reject it.
MUTANTS = (
    ("physical_start_not_live",
     "authority->live_records[record->start_block] = 1U;",
     "authority->live_records[record->start_block] = 0U;",
     "before_durability_invisible"),
    ("lower_fua_ignored",
     "!flush_completed) ? -EIO : 0;",
     "flush_completed) ? -EIO : 0;",
     "failed_or_short_lower"),
    ("missing_reader_pin",
     "if (record->reader_pins == (swapz_u8)~0U)",
     "if (record->reader_pins == 0U)",
     "before_durability_invisible"),
    ("relocation_reclaims_pinned_old",
     "if (!previous->reader_pins) {",
     "if (previous->reader_pins) {",
     "reader_pinned_relocation"),
    ("old_extent_released_as_live",
     "pool->authority->live_records[record->start_block] = 0U;",
     "pool->authority->live_records[record->start_block] = 1U;",
     "reader_pinned_relocation"),
    ("missing_required_fua",
     "spec->codec_version != 1U || spec->requested_fua != 1U)",
     "spec->codec_version != 1U || spec->requested_fua == 1U)",
     "before_durability_invisible"),
    ("gc_epoch_accepts_future_only_wrong",
     "previous->spec.gc_epoch >= spec->gc_epoch)",
     "previous->spec.gc_epoch <= spec->gc_epoch)",
     "reader_pinned_relocation"),
    ("lost_capacity_guard",
     "if (!slot)\n\t\treturn -ENOSPC;",
     "if (slot)\n\t\treturn -ENOSPC;",
     "capacity_and_stale_ticket"),
    ("duplicate_terminal_callback",
     "record->state != SWAPZ_IMPORT_DISK_SUBMITTED)\n\t\treturn -ESTALE; /* one lower callback, including requeue/close */",
     "record->state == SWAPZ_IMPORT_DISK_SUBMITTED)\n\t\treturn -ESTALE; /* one lower callback, including requeue/close */",
     "before_durability_invisible"),
    ("closed_callback_cannot_abort",
     "error = pool->closing ? -ECANCELED : lower_error < 0 ? lower_error :",
     "error = pool->closing ? 0 : lower_error < 0 ? lower_error :",
     "closing_callback_and_pin"),
)


def run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=timeout,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def private_error(message: str, compiler: str) -> str:
    private = ROOT / ".private"
    if private.is_symlink():
        return "private-evidence-unavailable"
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink():
        return "private-evidence-unavailable"
    private.chmod(0o700)
    safe_compiler = re.sub(r"[^a-z0-9-]", "-", compiler)[:24]
    with tempfile.NamedTemporaryFile(
            dir=private, mode="w", encoding="utf-8",
            prefix="round066-import-disk-" + safe_compiler + "-",
            suffix=".log", delete=False) as output:
        os.fchmod(output.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        output.write(message[:65536])
        output.flush()
        return Path(output.name).relative_to(ROOT).as_posix()


def compile_actual(compiler: str, altered: Path, output: Path, label: str) -> None:
    command = [
        compiler, "-std=gnu11", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
        "-O1", "-g", "-Wall", "-Wextra", "-Wconversion", "-Wshadow",
        "-Werror", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-I", str(KERNEL), str(FIXTURE), str(altered),
        str(KERNEL / "codec.c"), "-o", str(output), "-llz4", "-lcrypto",
    ]
    result = run(command)
    if result.returncode:
        evidence = private_error(
            "compiler stdout:\n" + result.stdout +
            "\ncompiler stderr:\n" + result.stderr, label)
        errors = [
            line.strip() for line in result.stderr.splitlines()
            if re.search(r":\d+(?::\d+)?: (?:fatal )?error:", line)
        ]
        first_error = "compiler failed without source diagnostic"
        if errors:
            first_error = re.sub(r"(?:/[^:\s]+)+/", "external-source/",
                                 errors[0])[:180]
        raise RuntimeError("strict compiler failed " + label + " exit=" +
                           str(result.returncode) + " first=" +
                           first_error + " evidence=" + evidence)


def main() -> None:
    original = SOURCE.read_text()
    original_header = (KERNEL / "authority.h").read_text()
    for required in (
        "#define SWAPZ_IMPORT_DISK_ACTIVE 0U",
        "#define SWAPZ_AUTHORITY_IMPORT_ACTIVE 0U",
        "_Static_assert(sizeof(struct swapz_map) == 20,",
        "swapz_import_disk_stage(",
        "swapz_import_disk_complete(",
        "swapz_forget_active(authority, 1);",
        "authority->live_records[record->start_block] = 1U;",
        "return -EOPNOTSUPP; /* imported_map_publication_UNAVAILABLE */",
    ):
        if required not in original and required not in original_header:
            raise RuntimeError("required original source contract absent")
    if "zswap-import-codec.h" in FIXTURE.read_text():
        raise RuntimeError("unexpected dependency on future decoder bridge")
    for name, old, new, case in MUTANTS:
        if original.count(old) != 1:
            raise RuntimeError("nonunique original changed-C mutant " + name)

    expected = None
    with tempfile.TemporaryDirectory(prefix="swapz-round066-import-disk-") as temp:
        folder = Path(temp)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError("required compiler unavailable " + name)
            workspace = folder / name
            workspace.mkdir(mode=0o700)
            binary = workspace / "import-owner"
            compile_actual(compiler, SOURCE, binary, name + "-baseline")
            base_result = run([str(binary)])
            if base_result.returncode or base_result.stderr or not re.fullmatch(
                    r"PASS import_disk_owned_cases=6 map_bytes=20 "
                    r"pool_bytes=\d+ capacity=8 ACTIVE=0 PHASE_A=BLOCKED\n",
                    base_result.stdout):
                evidence = private_error(base_result.stdout + "\n" +
                                         base_result.stderr, name + "-baseline")
                raise RuntimeError("baseline oracle " + name + " exit=" +
                                   str(base_result.returncode) +
                                   " evidence=" + evidence)
            if expected is not None and expected != base_result.stdout:
                raise RuntimeError("GCC Clang ABI baseline mismatch")
            expected = base_result.stdout
            print("PASS " + name + " genuine linked authority " +
                  base_result.stdout.strip(), flush=True)
            for index, (mutation, before, after, case) in enumerate(MUTANTS):
                changed = workspace / ("mutant-" + str(index) + ".c")
                changed.write_text(original.replace(before, after, 1))
                compile_actual(compiler, changed, binary,
                               name + "-" + mutation)
                observed = run([str(binary), case])
                if (observed.returncode != 1 or observed.stdout or
                        observed.stderr != "FIRST_ERROR " + case + "\n"):
                    evidence = private_error(
                        observed.stdout + "\n" + observed.stderr,
                        name + "-" + mutation)
                    raise RuntimeError(
                        "semantic mutant survived " + name + " " + mutation +
                        " case=" + case + " exit=" +
                        str(observed.returncode) + " evidence=" + evidence)
            print("PASS " + name + " genuine changed-authority-C semantic mutants=" +
                  str(len(MUTANTS)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        # Fail-only; untrusted child stderr and absolute argv remain private.
        print("FIRST_ERROR round066-import-disk: " +
              re.sub(r"(?:/[^:\s]+)+", "[host-path]",
                     str(error))[:420], file=sys.stderr)
        sys.exit(1)
