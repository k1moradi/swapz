#!/usr/bin/env python3
"""Round067 real authority allocator + native selected codec memory lower READ.

Actually compile and execute src/kernel/authority.c + codec.c, not a copied
model. LZO1X_1 and raw LZ4 host ABI produce original-profile compressed
bytes; full output is independently decoded and SHA-256 compared. Only the
lower memory-backed/FUA receipt is MODELED; no product upper ACK.
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
FROZEN_CODEC = KERNEL / "zswap-import-codec.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round067-import-disk-payload-read.c"

# Each edit changes the ACTUAL production C translation unit. A valid mutant
# must compile with the SAME strict warnings/sanitizers and execute the exact
# named fixture to an isolated semantic FIRST_ERROR; compile errors never kill.
MUTANTS = (
    ("write_compressed_crc", "!=\n\t\t\t record->spec.compressed_crc32c)\n\t\t\terror = -EBADMSG; /* round067_write_compressed_crc */",
     "==\n\t\t\t record->spec.compressed_crc32c)\n\t\t\terror = -EBADMSG; /* round067_write_compressed_crc */",
     "original_lz4_classes"),
    ("write_zero_padding", "if (lower_extent[offset]) {\n\t\t\t\t\terror = -EBADMSG; /* round067_write_zero_pad */",
     "if (lower_extent[offset] == 0xffU) {\n\t\t\t\t\terror = -EBADMSG; /* round067_write_zero_pad */",
     "torn_write_and_completion"),
    ("read_compressed_crc", "expected->compressed_crc32c) /* round067_read_compressed_crc */",
     "(expected->compressed_crc32c + 1U)) /* round067_read_compressed_crc */",
     "original_lzo_classes"),
    ("read_zero_padding", "if (lower_extent[offset]) /* round067_read_zero_pad */",
     "if (lower_extent[offset] == 0xffU) /* round067_read_zero_pad */",
     "corrupt_lower_and_aba"),
    ("read_exact_full_extent", "actual_read_bytes != extent_bytes || /* round067_exact_lower_read */",
     "actual_read_bytes == extent_bytes || /* round067_exact_lower_read */",
     "original_lz4_classes"),
    ("read_exact_gc_epoch", "expected->gc_epoch != observed->gc_epoch || /* round067_gc_epoch */",
     "expected->gc_epoch == observed->gc_epoch || /* round067_gc_epoch */",
     "original_lzo_classes"),
    ("read_digest_ownership", "memcmp(expected->original_sha256, observed->original_sha256,",
     "!memcmp(expected->original_sha256, observed->original_sha256,",
     "corrupt_lower_and_aba"),
    ("read_exact_ticket", "record->ticket != view->ticket || /* round067_exact_reader_ticket */",
     "record->ticket == view->ticket || /* round067_exact_reader_ticket */",
     "original_lz4_classes"),
    ("write_exact_extent", "actual_extent_bytes != extent_bytes ||",
     "actual_extent_bytes == extent_bytes ||",
     "original_lzo_classes"),
    ("write_error_quarantine", "error ? error : lower_error,\n\t\t\t\t\t  completed_blocks, flush_completed);",
     "error ? lower_error : lower_error,\n\t\t\t\t\t  completed_blocks, flush_completed);",
     "torn_write_and_completion"),
)


def run(command: list[str], timeout: int = 75) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, capture_output=True, text=True, check=False, timeout=timeout,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def private_error(details: str, prefix: str) -> str:
    folder = ROOT / ".private"
    if folder.is_symlink():
        return "private-evidence-unavailable"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink():
        return "private-evidence-unavailable"
    folder.chmod(0o700)
    safe_prefix = re.sub(r"[^a-z0-9-]", "-", prefix)[:48]
    with tempfile.NamedTemporaryFile(
            dir=folder, mode="w", encoding="utf-8", delete=False,
            prefix="round067-disk-" + safe_prefix + "-", suffix=".log") as output:
        os.fchmod(output.fileno(), stat.S_IRUSR | stat.S_IWUSR)
        output.write(details[:65536])
        output.flush()
        return Path(output.name).relative_to(ROOT).as_posix()


def compile_actual(compiler: str, source: Path, binary: Path, label: str) -> None:
    command = [
        compiler, "-std=gnu11", "-O1", "-g",
        "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
        "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
        "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST",
        "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-I", str(KERNEL), str(FIXTURE), str(source),
        str(KERNEL / "codec.c"), "-o", str(binary), "-llzo2", "-llz4",
        "-lcrypto",
    ]
    result = run(command)
    if result.returncode:
        evidence = private_error(result.stdout + "\n" + result.stderr, label)
        first = next((line.strip() for line in result.stderr.splitlines()
                      if re.search(r":\d+(?::\d+)?: (?:fatal )?error:", line)),
                     "compiler did not emit a source-bound error")
        first = re.sub(r"(?:/[^:\s]+)+/", "external-source/", first)
        raise RuntimeError("compiler " + label + " exit=" +
                           str(result.returncode) + " first=" + first[:200] +
                           " evidence=" + evidence)


def main() -> None:
    original = SOURCE.read_text()
    header = (KERNEL / "authority.h").read_text()
    frozen = FROZEN_CODEC.read_text()
    for required in (
        "#define SWAPZ_IMPORT_DISK_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
        "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U",
        "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U",
        "SWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
        "swapz_import_disk_complete_payload(",
        "swapz_import_disk_read_pinned(",
        "return -EOPNOTSUPP; /* imported_map_publication_UNAVAILABLE */",
        "_Static_assert(sizeof(struct swapz_map) == 20,",
    ):
        if required not in original and required not in header and required not in frozen:
            raise RuntimeError("frozen original source guard missing " + required)
    # Source never claims native upper ACK, source authorization or actual FUA.
    if "swapz_zswap_import_decode(" in FIXTURE.read_text():
        raise RuntimeError("live ACK-dependent imported decode incorrectly used")
    for name, original_bytes, mutation_bytes, case in MUTANTS:
        if original.count(original_bytes) != 1:
            raise RuntimeError("nonunique real changed-C anchor " + name)

    baseline = None
    with tempfile.TemporaryDirectory(prefix="swapz-round067-disk-read-") as temp:
        folder = Path(temp)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError("missing strict compiler " + name)
            owned = folder / name
            owned.mkdir(mode=0o700)
            binary = owned / "native-disk-read"
            compile_actual(compiler, SOURCE, binary, name + "-baseline")
            result = run([str(binary)])
            expected = (r"PASS memory_lower_native_original_cases=6 "
                        r"profiles=2 full_decoded_bytes=4096 classes=1,2,4 "
                        r"map_bytes=20 pool_bytes=\d+ header=UNCHANGED "
                        r"modeled_receipt=ONLY AUTH=0 PHASE_A=BLOCKED\n")
            if result.returncode or result.stderr or not re.fullmatch(
                    expected, result.stdout):
                evidence = private_error(result.stdout + "\n" + result.stderr,
                                         name + "-baseline")
                raise RuntimeError("original profile baseline failed " + name +
                                   " exit=" + str(result.returncode) +
                                   " evidence=" + evidence)
            if baseline is not None and baseline != result.stdout:
                raise RuntimeError("GCC/Clang profile/authority ABI diverged")
            baseline = result.stdout
            print("PASS " + name + " actual original LZO1X/LZ4 lower " +
                  result.stdout.strip(), flush=True)
            for index, (mutation, before, after, case) in enumerate(MUTANTS):
                changed = owned / ("mutant-" + str(index) + ".c")
                changed.write_text(original.replace(before, after, 1))
                compile_actual(compiler, changed, binary, name + "-" + mutation)
                killed = run([str(binary), case])
                if (killed.returncode != 1 or killed.stdout or
                        killed.stderr != "FIRST_ERROR " + case + "\n"):
                    evidence = private_error(killed.stdout + "\n" +
                                             killed.stderr, name + "-" + mutation)
                    raise RuntimeError("real-C semantic mutant survived " +
                                       name + " " + mutation + " exit=" +
                                       str(killed.returncode) +
                                       " evidence=" + evidence)
            print("PASS " + name + " actual changed-authority-C "
                  "semantic mutants=" + str(len(MUTANTS)), flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("FIRST_ERROR round067-import-disk: " +
              re.sub(r"(?:/[^:\s]+)+", "[host-path]",
                     str(error))[:420], file=sys.stderr)
        sys.exit(1)
