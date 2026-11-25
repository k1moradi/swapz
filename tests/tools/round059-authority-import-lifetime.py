#!/usr/bin/env python3
"""Exact product C authority import lifetime: rootless strict GCC/Clang only.

Source under test: src/kernel/authority.c + codec.c with one dormant guard.
No imported codec header, no synthetic substitute for swapz_stage/finish_raw.
No real I/O, zswap source BIO, durable flush, or upper ACK is authorized.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round059-authority-import-lifetime.c"
MUTANTS = (
    ("unauthorized_publish",
     "return -EOPNOTSUPP; /* imported_map_publication_UNAVAILABLE */",
     "return 0; /* imported_map_publication_UNAVAILABLE */",
     "no_import_map_publication"),
    ("short_completion",
     "completed_blocks != record->extent_blocks || /* complete_extent */",
     "completed_blocks == record->extent_blocks || /* complete_extent */",
     "short_lower_write"),
    ("missing_fua",
     "(record->spec.requested_fua && !flush_completed)) { /* needs_fua */",
     "(record->spec.requested_fua && flush_completed)) { /* needs_fua */",
     "fua_observation_required"),
    ("duplicate_callback",
     "if (!record || record->state != SWAPZ_AUTHORITY_IMPORT_SUBMITTED)",
     "if (!record || record->state == SWAPZ_AUTHORITY_IMPORT_SUBMITTED)",
     "no_import_map_publication"),
    ("reader_gc_pin",
     "if (record->reader_pins)\n\t\treturn -EBUSY; /* immutable_reader_gc_fence */",
     "if (!record->reader_pins)\n\t\treturn -EBUSY; /* immutable_reader_gc_fence */",
     "reader_gc_and_teardown_fence"),
    ("teardown_retire_pin",
     "busy = 1; /* hold_descriptor_until_put */",
     "busy = 0; /* hold_descriptor_until_put */",
     "reader_gc_and_teardown_fence"),
    ("current_generation",
     "current_mapping->generation + 1U != record->generation)",
     "current_mapping->generation + 1U == record->generation)",
     "no_import_map_publication"),
    ("normal_extent_class_two",
     "tx->extent_blocks == 2U ? 2U : 4U,",
     "tx->extent_blocks == 2U ? 1U : 4U,",
     "actual_product_extent_classes"),
    ("normal_extent_class_four",
     "tx->extent_blocks == 2U ? 2U : 4U,",
     "tx->extent_blocks == 2U ? 2U : 1U,",
     "actual_product_extent_classes"),
    ("normal_compressed_read_crc",
     "if (swapz_crc32c_bytes(stored, current_map->payload_length) !=",
     "if (swapz_crc32c_bytes(stored, current_map->payload_length) ==",
     "actual_product_extent_classes"),
)


def execute(command):
    return subprocess.run(
        command, text=True, capture_output=True, check=False, timeout=50,
        env={**os.environ, "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
             "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})


def build(compiler, authority_source, output):
    command = [
        compiler, "-std=gnu11", "-DSWAPZ_ROUND059_AUTHORITY_IMPORT_LIFETIME_TEST",
        "-O1", "-g", "-Wall", "-Wextra", "-Wconversion", "-Wshadow", "-Werror",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
        "-I", str(KERNEL), str(FIXTURE), str(authority_source),
        str(KERNEL / "codec.c"), "-o", str(output), "-llz4", "-lcrypto",
    ]
    result = execute(command)
    if result.returncode:
        diagnostics = [
            line.strip().replace(str(ROOT) + "/", "")
            for line in result.stderr.splitlines()
            if re.search(r":\d+:\d+: (?:fatal )?error:", line)
        ]
        if not diagnostics:
            diagnostics = ["compiler exited nonzero without source-bound error"]
        # Bounded source-local diagnostics: first real error FIRST, then at most
        # four distinct additional actual errors, never arbitrary child stderr.
        unique_diagnostics = list(dict.fromkeys(diagnostics))[:5]
        raise RuntimeError("compiler " + Path(compiler).name + ": " +
                           " | ".join(unique_diagnostics)[:1000])


def main():
    base_c = (KERNEL / "authority.c").read_text()
    base_h = (KERNEL / "authority.h").read_text()
    for needle in (
        "#define SWAPZ_AUTHORITY_IMPORT_ACTIVE 0U",
        "#define SWAPZ_AUTHORITY_IMPORT_CAPACITY 8U",
        "#define SWAPZ_AUTHORITY_IMPORT_STAGING_LIMIT 2U",
        "#if defined(SWAPZ_ROUND059_AUTHORITY_IMPORT_LIFETIME_TEST)",
        "struct swapz_map",
        '_Static_assert(sizeof(struct swapz_map) == 20,',
    ):
        if needle not in base_h and needle not in base_c:
            raise RuntimeError("source_guard_missing " + needle)
    if base_c.count("/* imported_map_publication_UNAVAILABLE */") != 1:
        raise RuntimeError("live_import_commit_guard_changed")
    if "#include \"zswap-import-codec.h\"" in FIXTURE.read_text():
        raise RuntimeError("test_became_dependent_on_peer_codec_header")
    expected = None
    with tempfile.TemporaryDirectory(prefix="swapz-round059-import-") as temporary:
        work = Path(temporary)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError("missing compiler " + name)
            binary = work / "test"
            build(compiler, KERNEL / "authority.c", binary)
            result = execute([str(binary)])
            if result.returncode or result.stderr or not re.fullmatch(
                    r"PASS authority_actual_product_cases=9 map_bytes=20 "
                    r"descriptor_bytes=\d+ pool_bytes=\d+ capacity=8 staged=2 "
                    r"AUTH0 PHASE_A=BLOCKED\n", result.stdout):
                raise RuntimeError(name + " pristine baseline: " +
                                   (result.stderr or result.stdout)[:450])
            if expected is not None and expected != result.stdout:
                raise RuntimeError("compiler ABI or host behavior differs")
            expected = result.stdout
            print("PASS " + name + " strict ASan+UBSan actual " +
                  result.stdout.strip())
            for index, (mutation, before, after, case) in enumerate(MUTANTS):
                if base_c.count(before) != 1:
                    raise RuntimeError("nonunique actual source mutant " + mutation)
                changed = work / ("changed-" + str(index) + ".c")
                changed.write_text(base_c.replace(before, after, 1))
                build(compiler, changed, binary)
                killed = execute([str(binary), case])
                if (killed.returncode != 1 or killed.stdout or
                        killed.stderr != "FIRST_ERROR " + case + "\n"):
                    raise RuntimeError(
                        name + " semantic mutant " + mutation + " escaped: exit=" +
                        str(killed.returncode) + " first=" + killed.stderr[:180])
            print("PASS " + name + " changed-product-C semantic mutants=" +
                  str(len(MUTANTS)))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print("FIRST_ERROR round059-authority-import: " + str(error)[:550],
              file=sys.stderr)
        sys.exit(1)
