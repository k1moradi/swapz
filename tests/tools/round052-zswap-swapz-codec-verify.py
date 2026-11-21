#!/usr/bin/env python3
"""Round052: original pinned crypto/lz4.c wrapper, host raw-LZ4 subset, real swapz codec.c.

NO real kernel-selected compressor, source slot, Device Mapper lifetime, physical I/O or auth.
Only separately tagged lower staging is considered; ordinary RAW_4096 remains ORIGINAL.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round052-zswap-swapz-codec.c"
CODEC = ROOT / "src/kernel/codec.c"
HEADER = ROOT / "src/kernel/codec.h"
DM = ROOT / "src/kernel/dm-target.c"
ORIGINAL_COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"

# Every mutation is within an ACTUAL production codec.c function and is
# compiled + executed in BOTH compilers, not just textual "mutant found".
MUTANTS = (
    ("extent-invalid-class", "swapz_valid_extent_bytes",
     "bytes_total == SWAPZ_BLOCK_BYTES", "bytes_total >= SWAPZ_BLOCK_BYTES"),
    ("append-3568-cap", "swapz_ram_extent_append_checked",
     "payload_length > SWAPZ_MAX_COMPRESSED", "payload_length > SWAPZ_BLOCK_BYTES"),
    ("append-unknown-encoding", "swapz_ram_extent_append_checked",
     "!swapz_encoding_valid(encoding)", "0"),
    ("append-over-capacity", "swapz_ram_extent_append_checked",
     "builder->count >= builder->record_capacity", "0"),
    ("seal-empty", "swapz_ram_extent_seal",
     "builder->sealed || !builder->count ||", "builder->sealed || 0 ||"),
    ("seal-cursor", "swapz_ram_extent_seal",
     "builder->last_record.payload_offset != builder->payload_start",
     "builder->last_record.payload_offset == builder->payload_start"),
    ("seal-zero-padding", "swapz_ram_extent_seal",
     "memset(builder->bytes, 0, builder->payload_start);",
     "memset(builder->bytes, 0x7f, builder->payload_start);"),
    ("read-3568-cap", "swapz_ram_extent_read",
     "record->payload_length > SWAPZ_MAX_COMPRESSED",
     "record->payload_length > SWAPZ_BLOCK_BYTES"),
    ("read-unknown-encoding", "swapz_ram_extent_read",
     "!swapz_encoding_valid(record->encoding)", "0"),
    ("read-outside-payload", "swapz_ram_extent_read",
     "record->payload_offset < builder->payload_start",
     "record->payload_offset > builder->payload_start"),
    ("read-no-generation", "swapz_ram_extent_read",
     "record->generation != generation || !generation ||",
     "record->generation != generation || 0 ||"),
    ("read-crc-invert", "swapz_ram_extent_read",
     "swapz_crc32c_bytes(stored, record->payload_length) !=",
     "swapz_crc32c_bytes(stored, record->payload_length) =="),
    ("crc32c-implementation", "swapz_crc32c_state",
     "0x105ec76fU", "0x105ec76eU"),
)


def require(source: str, anchor: str, context: str) -> None:
    if anchor not in source:
        raise AssertionError(f"SOURCE_DRIFT {context}: {anchor!r}")


def function_limits(source: str, name: str) -> tuple[int, int]:
    pattern = re.compile(r"(?:static\s+)?(?:inline\s+)?(?:int|swapz_u32)\s+" +
                         re.escape(name) + r"\s*\(")
    matches = list(pattern.finditer(source))
    if len(matches) != 1:
        raise AssertionError(f"SOURCE_DRIFT {name}: expected one definition, saw {len(matches)}")
    start = matches[0].start()
    opening = source.find("{", matches[0].end())
    if opening < 0:
        raise AssertionError(f"SOURCE_DRIFT {name}: missing body")
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return start, index + 1
    raise AssertionError(f"SOURCE_DRIFT {name}: unterminated body")


def mutate_real_function(source: str, name: str, before: str, after: str) -> str:
    start, end = function_limits(source, name)
    original = source[start:end]
    if original.count(before) != 1 or before == after:
        raise AssertionError(f"SOURCE_DRIFT {name}: nonunique or ineffective {before!r}")
    return source[:start] + original.replace(before, after, 1) + source[end:]


def original_lz4_wrapper(linux_root: Path) -> str:
    original = (linux_root / "crypto/lz4.c").read_text()
    mm = (linux_root / "mm/zswap.c").read_text()
    acomp = (linux_root / "crypto/acompress.c").read_text()
    kconfig = (linux_root / "mm/Kconfig").read_text()
    for anchor in (
        'strscpy(pool->tfm_name, compressor, sizeof(pool->tfm_name));',
        'crypto_alloc_acomp_node(pool->tfm_name, 0, 0, cpu_to_node(cpu))',
        'crypto_wait_req(crypto_acomp_compress(acomp_ctx->req)',
        'dlen = acomp_ctx->req->dlen;',
        'entry->length == PAGE_SIZE',
        'crypto_acomp_decompress(acomp_ctx->req)',
        'zswap_decompress(entry, folio)',
        'swap_writeout',
    ):
        require(mm, anchor, 'pristine original mm/zswap.c')
    require(kconfig, 'default ZSWAP_COMPRESSOR_DEFAULT_LZO', 'pristine mm/Kconfig')
    require(acomp, 'crypto_init_scomp_ops_async(tfm)', 'pristine crypto/acompress.c')
    for anchor in ('LZ4_compress_default(src, dst,',
                   'LZ4_decompress_safe(src, dst, slen, *dlen)',
                   '.cra_name\t= "lz4"'):
        require(original, anchor, 'pristine crypto/lz4.c')
    start, end = function_limits(original, '__lz4_compress_crypto')
    wrapper = original[start:end]
    require(wrapper, '*dlen = out_len;', 'pinned original LZ4 compress wrapper')
    return wrapper + '\n'


def validate_product() -> str:
    codec = CODEC.read_text()
    header = HEADER.read_text()
    dm = DM.read_text()
    for anchor in ('#define SWAPZ_MAX_COMPRESSED 3568U',
                   '#define SWAPZ_CODEC_METADATA_ON_MEDIA 0U',
                   '#define SWAPZ_ENCODING_LZ4 0U',
                   '#define SWAPZ_ENCODING_DELTA64 1U',
                   '#define SWAPZ_ENCODING_DELTA64_SHUF8 2U'):
        require(header, anchor, 'actual codec.h')
    for anchor in ('payload_length > SWAPZ_MAX_COMPRESSED',
                   '!swapz_encoding_valid(encoding)',
                   'swapz_crc32c_bytes(stored, record->payload_length) !=',
                   'memset(builder->bytes, 0, builder->payload_start);'):
        require(codec, anchor, 'actual codec.c')
    for anchor in ('decompressed = LZ4_decompress_safe(ctx->read_compressed,',
                   'if (decompressed != SWAPZ_BLOCK_BYTES)',
                   'swapz_unpredict_delta64_shuf8(ctx->predictor_page,',
                   'swapz_unpredict_delta64(ctx->predictor_page,'):
        require(dm, anchor, 'actual dm-target.c read')
    for _, function_name, before, after in MUTANTS:
        mutate_real_function(codec, function_name, before, after)
    return codec


def run_checked(command: list[str], *, expected_zero: bool, label: str) -> None:
    completed = subprocess.run(command, text=True, capture_output=True,
                               timeout=80, check=False)
    actual_zero = completed.returncode == 0
    if actual_zero != expected_zero:
        snippet = '\n'.join((completed.stdout + '\n' + completed.stderr).splitlines()[-22:])
        raise AssertionError(f"ROUND052_CODEC_FIRST_ERROR {label} exit={completed.returncode} "
                             f"expected_zero={expected_zero}\n{snippet}")
    if expected_zero:
        require(completed.stdout, 'ROUND052_HOST_RAW_LZ4_SUBSET_PASS', label)


def compile_and_execute(compiler: str, tempdir: Path, fixture: Path, codec: str,
                        name: str, expected_zero: bool) -> None:
    source_path = tempdir / f'{name}-codec.c'
    binary_path = tempdir / f'{name}-{compiler}'
    source_path.write_text(codec)
    flags = [compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
             '-Wconversion', '-Wshadow', '-Werror', '-fno-omit-frame-pointer',
             '-fsanitize=address,undefined', '-I', str(HEADER.parent),
             str(fixture), str(source_path), '-llz4', '-lcrypto', '-o', str(binary_path)]
    run_checked(flags, expected_zero=True, label=f'{name}/{compiler}/compile')
    run_checked([str(binary_path)], expected_zero=expected_zero,
                label=f'{name}/{compiler}/C-execution')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--linux-root', type=Path, required=True,
                        help='pristine torvalds/linux checkout pinned to c339f401...')
    args = parser.parse_args()
    linux_root: Path = args.linux_root.resolve()
    if not (linux_root / 'crypto/lz4.c').is_file():
        raise AssertionError('pinned ORIGINAL Linux crypto/lz4.c unavailable; no inferred PASS')
    actual_sha = subprocess.check_output(['git', '-C', str(linux_root), 'rev-parse', 'HEAD'],
                                         text=True).strip()
    if actual_sha != ORIGINAL_COMMIT:
        raise AssertionError(f'wrong original kernel SHA: {actual_sha}')
    if subprocess.check_output(['git', '-C', str(linux_root), 'status', '--porcelain'],
                               text=True).strip():
        raise AssertionError('pristine original Linux dirty')
    original_wrapper = original_lz4_wrapper(linux_root)
    actual_codec = validate_product()
    for compiler in ('gcc', 'clang'):
        if not shutil.which(compiler):
            raise AssertionError(f'missing mandatory compiler {compiler}')
    with tempfile.TemporaryDirectory(prefix='round052-codec-') as temporary:
        output = Path(temporary)
        (output / 'round052-original-crypto-lz4-extracted.inc').write_text(original_wrapper)
        # Always compile the pinned ORIGINAL crypto/lz4.c function body, not a
        # retyped or Python-simulated compressor. Only the liblz4 backend is HOST.
        fixture_copy = output / 'round052-zswap-swapz-codec.c'
        fixture_copy.write_text(FIXTURE.read_text())
        # Generated compilation scratch is outside the tracked checkout.
        for compiler in ('gcc', 'clang'):
            compile_and_execute(compiler, output, fixture_copy, actual_codec, 'baseline', True)
            for mutation_name, function, before, after in MUTANTS:
                mutant_source = mutate_real_function(actual_codec, function, before, after)
                compile_and_execute(compiler, output, fixture_copy, mutant_source, mutation_name, False)
                print(f'ROUND052_REAL_CODEC_C_MUTANT_KILLED compiler={compiler} '
                      f'name={mutation_name}', flush=True)
    print('ROUND052_CODEC_C_PASS baseline=2 real_source_mutants=26 '
          'host_subset=ONLY pinned_original_wrapper=COMPILED '
          'live_crypto_acomp_runtime=NOT_RUN source_authenticated=0', flush=True)


if __name__ == '__main__':
    main()
