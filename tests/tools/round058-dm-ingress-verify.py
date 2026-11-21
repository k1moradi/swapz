#!/usr/bin/env python3
"""Compile the exact guarded production dm-target.c ingress C and semantic mutants.

The host fixture supplies only kernel type/API stand-ins; it does not create a
current DM table lease, a native BIO, lower durability, or an imported ACK.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = ROOT / 'src/kernel/dm-target.c'
FIXTURE = ROOT / 'tests/runtime/native/fixtures/round058-dm-ingress-host.c'
FIRST_ERROR = 'ROUND058_DM_FIRST_ERROR'
PASS = ('ROUND058_DM_INGRESS_HOST_PASS cases=22 '
        'SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED')
MUTANTS = (
    ('cloned_required', '!(upper_bio->bi_flags & (1U << BIO_CLONED))', 'false'),
    ('target_relative_alignment', 'relative_sector % SWAPZ_SECTORS ||', 'false ||'),
    ('accepted_target_private', 'if (target->private != ctx || ctx->target != target ||',
     'if (false || ctx->target != target ||'),
    ('terminal_bdev_identity',
     'observation->device != upper_bio->bi_bdev ||\n\t    observation->target_relative_sector != upper_bio->bi_iter.bi_sector ||\n\t    upper_bio->bi_iter.bi_size',
     'false ||\n\t    observation->target_relative_sector != upper_bio->bi_iter.bi_sector ||\n\t    upper_bio->bi_iter.bi_size'),
    ('terminal_current_target', 'observation->target != ctx->target ||', 'false ||'),
    ('terminal_exactly_once', 'if (observation->terminal)', 'if (false)'),
    ('endio_exactly_once', 'if (observation->endio_seen)', 'if (false)'),
)


class EvidenceError(RuntimeError):
    """First source/compile/runtime mismatch, without credentials or host paths."""


def require(value: bool, label: str) -> None:
    if not value:
        raise EvidenceError('first_error=' + label)


def extract(source: str, start: str, end: str) -> str:
    require(source.count(start) == 1 and source.count(end) == 1,
            'nonunique-product-C-marker:' + start)
    first = source.index(start)
    last = source.index(end) + len(end)
    require(first < last, 'reversed-marker:' + start)
    return source[first:last] + '\n'


def source_sections() -> tuple[str, str]:
    product = PRODUCT.read_text()
    types = extract(product, '/* ROUND058_DM_INGRESS_TYPES_START */',
                    '/* ROUND058_DM_INGRESS_TYPES_END */')
    helpers = extract(product, '/* ROUND058_DM_INGRESS_HELPERS_START */',
                      '/* ROUND058_DM_INGRESS_HELPERS_END */')
    for marker in ('SWAPZ_ROUND058_DM_INGRESS_LIFETIME_TEST',
                   'swapz_round058_dm_ingress_refuse',
                   'swapz_round058_dm_terminal_refuse',
                   'swapz_round058_dm_endio_refuse',
                   'observation->shape_observed = true;',
                   'return -EOPNOTSUPP;'):
        require(marker in helpers, 'missing-source-C:' + marker)
    for marker in (
        'struct swapz_round058_dm_observation round058_observation;',
        'swapz_round058_dm_ingress_refuse(ti, ctx, bio,',
        'swapz_round058_dm_terminal_refuse(ctx, bio,',
        'swapz_round058_dm_endio_refuse(ti, bio,',
        '#if defined(SWAPZ_ROUND058_DM_INGRESS_LIFETIME_TEST)',
        'return DM_MAPIO_SUBMITTED;',
        'bio_endio(bio);',
        'WRITE_ONCE(ctx->accepting, false);',
        'return READ_ONCE(ctx->failed) ? DM_MAPIO_KILL : DM_MAPIO_REQUEUE;',
        'if (upper_bio->bi_flags & (1U << BIO_CLONED))\n\t\treturn -EOPNOTSUPP;',
    ):
        require(marker in product, 'missing-lifetime-callsite:' + marker)
    map_entry = product.split('static int swapz_map(', 1)[1].split('static void swapz_drain(', 1)[0]
    require(map_entry.index('entry = dm_per_bio_data(') <
            map_entry.index('swapz_round058_dm_ingress_refuse(ti, ctx, bio,') <
            map_entry.index('list_add_tail(&entry->list, &ctx->incoming);'),
            'guard-must-precede-real-incoming-publication')
    completion = product.split('static void swapz_complete(', 1)[1].split('static void swapz_defer_upper_completion(', 1)[0]
    require(completion.index('swapz_round058_dm_terminal_refuse(ctx, bio,') <
            completion.index('bio_endio(bio);'), 'terminal-after-bio-release')
    require('#define SWAPZ_ZSWAP_IMPORT_ADMISSION_ACTIVE 0U' in
            (ROOT / 'src/kernel/zswap-import-admission.h').read_text(),
            'active-import-authorization')
    require('#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U' in
            (ROOT / 'src/kernel/zswap-import-codec.h').read_text(),
            'active-import-decoder')
    return types, helpers


def compile_and_run(compiler: str, program: str, directory: Path,
                    label: str, hostile: bool) -> None:
    source_path = directory / (label + '.c')
    binary_path = directory / label
    source_path.write_text(program)
    arguments = [compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                 '-Wconversion', '-Wshadow', '-Werror',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                 str(source_path), '-o', str(binary_path)]
    compilation = subprocess.run(arguments, capture_output=True, text=True, timeout=90)
    require(compilation.returncode == 0,
            'compiler:' + label + ':' + (compilation.stderr.splitlines() or ['unknown'])[0][:220])
    execution = subprocess.run([str(binary_path)], capture_output=True, text=True,
                               timeout=90, env={**os.environ,
                               'ASAN_OPTIONS': 'halt_on_error=1:detect_leaks=1',
                               'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'})
    if hostile:
        require(execution.returncode == 1 and FIRST_ERROR in execution.stderr and
                'AddressSanitizer' not in execution.stderr and
                'runtime error:' not in execution.stderr,
                'nonsemantic-mutant:' + label + ':exit=' + str(execution.returncode) +
                ':' + execution.stderr[:160])
    else:
        require(execution.returncode == 0 and execution.stdout.strip() == PASS and
                not execution.stderr,
                'baseline:' + label + ':exit=' + str(execution.returncode) + ':' +
                (execution.stderr or execution.stdout)[:200])


def main() -> None:
    types, helpers = source_sections()
    fixture = FIXTURE.read_text()
    require(fixture.count('/* ROUND058_INJECT_TYPES */') == 1 and
            fixture.count('/* ROUND058_INJECT_HELPERS */') == 1,
            'missing-host-injection-point')
    def compose(changed_helpers: str) -> str:
        return fixture.replace('/* ROUND058_INJECT_TYPES */', types).replace(
            '/* ROUND058_INJECT_HELPERS */', changed_helpers)
    for name, original, changed in MUTANTS:
        require(helpers.count(original) == 1, 'mutation-anchor:' + name)
        require(original != changed, 'inert-mutation:' + name)
    with tempfile.TemporaryDirectory(prefix='round058-exact-dm-C-') as temporary:
        directory = Path(temporary)
        for compiler in ('gcc', 'clang'):
            require(shutil.which(compiler) is not None, 'missing-compiler:' + compiler)
            compile_and_run(compiler, compose(helpers), directory, compiler + '-original', False)
            print('ROUND058_ACTUAL_PRODUCT_DM_' + compiler.upper() +
                  '_22_GNU11_ASAN_UBSAN_CASES_PASS')
            for name, original, changed in MUTANTS:
                compile_and_run(compiler, compose(helpers.replace(original, changed, 1)),
                                directory, compiler + '-' + name, True)
            print('ROUND058_ACTUAL_PRODUCT_DM_' + compiler.upper() +
                  '_7_CHANGED_SOURCE_C_MUTANTS_SEMANTIC_PASS')
    print('ROUND058_DM_PRODUCT_INGRESS_NO_AUTH PASS exact_source=dm-target.c '
          'SOURCE_MAPPED_AUTHENTICATED=0 PHASE_A=BLOCKED')


if __name__ == '__main__':
    try:
        main()
    except (EvidenceError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print('ROUND058_DM_FIRST_ERROR ' + str(error)[:370], file=sys.stderr)
        sys.exit(2)
