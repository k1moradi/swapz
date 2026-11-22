#!/usr/bin/env python3
"""Round068 actual product authority.c guarded lower callback byte/read proof.

Strict GCC and Clang compile ACTUAL authority.c+codec.c and execute seven
real linked source-bound scenarios plus independently compiled/executed
semantic changed-C mutants. The host lower uses a deliberate BIO-shaped
callback FAKE; pinned Linux original real bio/bvec/KUnit is a separate job.
Neither proves physical FUA nor emits any upper BIO ACK.
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
SOURCE = KERNEL / "authority.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round068-original-lower-bio-owned.c"

MUTANTS = (
    ("callback_token_mismatch",
     "owner->pending.token == observed->token &&",
     "owner->pending.token != observed->token &&",
     "write_fua_read_both_codecs_and_classes"),
    ("callback_sector_mismatch",
     "owner->pending.sector == observed->sector &&",
     "owner->pending.sector != observed->sector &&",
     "write_fua_read_both_codecs_and_classes"),
    ("callback_op_mismatch",
     "owner->pending.opf == observed->opf &&",
     "owner->pending.opf != observed->opf &&",
     "write_fua_read_both_codecs_and_classes"),
    ("callback_length_mismatch",
     "owner->pending.bytes == observed->bytes;",
     "owner->pending.bytes != observed->bytes;",
     "write_fua_read_both_codecs_and_classes"),
    ("direct_fua_missing",
     "if (owner->direct_fua) {",
     "if (!owner->direct_fua) {",
     "write_fua_read_both_codecs_and_classes"),
    ("premature_fallback_publication",
     "owner->phase = SWAPZ_IMPORT_LOWER_POSTFLUSH_PENDING;",
     "owner->phase = SWAPZ_IMPORT_LOWER_TERMINAL;",
     "fallback_postwrite_flush_and_duplicate"),
    ("wrong_postflush_opcode",
     "SWAPZ_IMPORT_LOWER_OP_FLUSH |\n\t\t\t\t\tSWAPZ_IMPORT_LOWER_REQ_PREFLUSH",
     "SWAPZ_IMPORT_LOWER_OP_READ |\n\t\t\t\t\tSWAPZ_IMPORT_LOWER_REQ_PREFLUSH",
     "fallback_postwrite_flush_and_duplicate"),
    ("missing_retained_read_pin",
     "owner->has_pin = 1U; /* round068_read_pin_before_lower */",
     "owner->has_pin = 0U; /* round068_read_pin_before_lower */",
     "held_old_read_during_gc_and_read_failure"),
    ("read_partial_completion_accepted",
     "completed_bytes != owner->pending.bytes ? -EIO :",
     "completed_bytes == owner->pending.bytes ? -EIO :",
     "held_old_read_during_gc_and_read_failure"),
    ("close_fence_missing",
     "owner->closing = 1U; /* round068_close_fence */",
     "owner->closing = 0U; /* round068_close_fence */",
     "flush_failure_and_close_submitted"),
    ("incorrect_first_token_exhaustion",
     "if (owner->next_token == ~(swapz_u64)0)",
     "if (owner->next_token != ~(swapz_u64)0)",
     "write_fua_read_both_codecs_and_classes"),
    ("missing_postwrite_flush_gate",
     "return -EINPROGRESS; /* round068_flush_barrier */",
     "return 0; /* round068_flush_barrier */",
     "fallback_postwrite_flush_and_duplicate"),
    ("physical_first_header_violated",
     "SWAPZ_LINUX_SWAP_HEADER_BLOCKS) *\n\t\t  SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK",
     "0U) *\n\t\t  SWAPZ_IMPORT_LOWER_SECTORS_PER_BLOCK",
     "write_fua_read_both_codecs_and_classes"),
    ("direct_fua_receipt_missing",
     "owner->transaction.extent_blocks,\n\t\t\t\t1); /* round068_write_fua_required */",
     "owner->transaction.extent_blocks,\n\t\t\t\t0); /* round068_write_fua_required */",
     "write_fua_read_both_codecs_and_classes"),
)


def execute(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, timeout=75, check=False,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def private_failure(details: str, label: str) -> str:
    private = ROOT / ".private"
    if private.is_symlink():
        return "private-evidence-unavailable"
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink():
        return "private-evidence-unavailable"
    private.chmod(0o700)
    safe_label = re.sub(r"[^a-z0-9-]", "-", label)[:40]
    with tempfile.NamedTemporaryFile(
            dir=private, prefix="round068-bio-" + safe_label + "-",
            suffix=".log", delete=False, encoding="utf-8",
            mode="w") as evidence:
        os.fchmod(evidence.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        evidence.write(details[:65536])
        evidence.flush()
        return Path(evidence.name).relative_to(ROOT).as_posix()


def compile_product(compiler: str, source: Path, output: Path, label: str) -> None:
    command = [
        compiler, "-std=gnu11", "-O1", "-g",
        "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
        "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
        "-DSWAPZ_ROUND068_IMPORT_LOWER_BIO_TEST",
        "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST",
        "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-I", str(KERNEL), str(FIXTURE), str(source),
        str(KERNEL / "codec.c"), "-o", str(output),
        "-llzo2", "-llz4", "-lcrypto",
    ]
    result = execute(command)
    if result.returncode:
        evidence = private_failure(result.stdout + "\n" + result.stderr, label)
        first = next((line.strip() for line in result.stderr.splitlines()
                      if re.search(r":\d+(?::\d+)?: (?:fatal )?error:", line)),
                     "source compiler exited without source diagnostic")
        first = re.sub(r"(?:/[^:\s]+)+/", "external-source/", first)
        raise RuntimeError("compiler " + label + " exit=" +
                           str(result.returncode) + " first=" + first[:190] +
                           " evidence=" + evidence)


def main() -> None:
    real_source = SOURCE.read_text()
    real_header = (KERNEL / "authority.h").read_text()
    for required in (
        "#define SWAPZ_IMPORT_LOWER_BIO_ACTIVE 0U",
        "swapz_import_lower_end_write(",
        "swapz_import_lower_end_read(",
        "swapz_import_disk_complete_payload(",
        "swapz_import_disk_read_pinned(",
        "return -EOPNOTSUPP; /* imported_map_publication_UNAVAILABLE */",
        "_Static_assert(sizeof(struct swapz_map) == 20,",
    ):
        if required not in real_source and required not in real_header:
            raise RuntimeError("original guarded C source contract missing")
    if "swapz_zswap_import_decode(" in FIXTURE.read_text():
        raise RuntimeError("ACK-dependent original decoder was not authorized")
    for name, before, after, test_case in MUTANTS:
        if real_source.count(before) != 1:
            raise RuntimeError("nonunique changed-real-C mutant " + name)
    expected = None
    with tempfile.TemporaryDirectory(prefix="swapz-round068-bio-") as temporary:
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError("required compiler unavailable " + name)
            directory = Path(temporary) / name
            directory.mkdir(mode=0o700)
            binary = directory / "lower-owned"
            compile_product(compiler, SOURCE, binary, name + "-baseline")
            result = execute([str(binary)])
            pattern = (r"PASS lower_bio_shaped_callback_cases=7 "
                       r"profiles=2 classes=1,2,4 original_decoded=4096 "
                       r"map_bytes=20 pool_bytes=\d+ real_allocator=YES "
                       r"bio_kernel_execution=SEPARATE_KUNIT memory_fua=MODELED "
                       r"PHASE_A=BLOCKED\n")
            if result.returncode or result.stderr or not re.fullmatch(
                    pattern, result.stdout):
                evidence = private_failure(result.stdout + "\n" + result.stderr,
                                           name + "-baseline")
                raise RuntimeError("source baseline failed " + name +
                                   " exit=" + str(result.returncode) +
                                   " evidence=" + evidence)
            if expected is not None and expected != result.stdout:
                raise RuntimeError("two compiler ABI/source results differ")
            expected = result.stdout
            print("PASS " + name + " real authority lower callback " +
                  result.stdout.strip(), flush=True)
            for index, (mutation, before, after, case) in enumerate(MUTANTS):
                changed_source = directory / ("changed-" + str(index) + ".c")
                changed_source.write_text(real_source.replace(before, after, 1))
                compile_product(compiler, changed_source, binary,
                                name + "-" + mutation)
                observed = execute([str(binary), case])
                if (observed.returncode != 1 or observed.stdout or
                        observed.stderr != "FIRST_ERROR " + case + "\n"):
                    evidence = private_failure(
                        observed.stdout + "\n" + observed.stderr,
                        name + "-" + mutation)
                    raise RuntimeError(
                        "real semantic mutant escaped " + name + " " + mutation +
                        " exit=" + str(observed.returncode) +
                        " evidence=" + evidence)
            print("PASS " + name + " compiled_and_executed_changed_real_C_mutants=" +
                  str(len(MUTANTS)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("FIRST_ERROR round068-import-lower-bio: " +
              re.sub(r"(?:/[^:\s]+)+", "[host-path]",
                     str(error))[:420], file=sys.stderr)
        sys.exit(1)
