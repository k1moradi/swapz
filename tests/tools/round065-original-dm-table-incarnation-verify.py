#!/usr/bin/env python3
"""Rootless exact new original table state/owner/DM core C, host-only API stubs."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/runtime/native/fixtures'
MUTANTS = (
    ('STATE', 'stale-generation', 'state->incarnation && state->incarnation != incarnation', 'false'),
    ('STATE', 'revival', 'state->parent == parent && !state->refused &&', 'state->parent == parent &&'),
    ('STATE', 'parent-identity', 'state->parent == parent && !state->refused', '!state->refused'),
    ('STATE', 'unselected', 'incarnation && state->incarnation == incarnation', 'incarnation != 0U'),
    ('OWNER', 'bad-origin', '!(parent->bi_flags & (1U << BIO_CLONED)) &&\n\t\t', 'true &&\n\t\t'),
    ('OWNER', 'preflush', '!(parent->bi_opf & REQ_PREFLUSH)', 'true'),
    ('OWNER', 'route', 'swapz_round064_original_route_matches(owner, parent)', '((void)swapz_round064_original_route_matches, true)'),
    ('OWNER', 'clone-owner', 'clone->bi_swapz_ci_sideband == owner', 'true'),
    ('OWNER', 'parent-owner', 'parent->bi_swapz_ci_sideband == owner', 'true'),
    ('CORE', 'wrong-endio', 'clone->bi_end_io != clone_endio', 'false'),
    ('CORE', 'wrong-target', 'tio->ti != ti', 'false'),
    ('CORE', 'duplicate', '!dm_tio_is_normal(tio)', '((void)dm_tio_is_normal, false)'),
    ('CORE', 'split', 'dm_io_flagged(io, DM_IO_WAS_SPLIT)', '((void)dm_io_flagged, false)'),
    ('CORE', 'target-bio-nr', 'tio->target_bio_nr ||', 'false ||'),
    ('CORE', 'wrong-mapper', 'ti->table->md != io->md', 'false'),
    ('CORE', 'wrong-bdev', 'parent->bi_bdev != clone->bi_bdev', 'false'),
    ('CORE', 'wrong-sector', 'parent->bi_iter.bi_sector != clone->bi_iter.bi_sector', 'false'),
    ('CORE', 'short-clone', 'clone->bi_iter.bi_size != 4096U', 'false'),
    ('CORE', 'old-sector', 'tio->old_sector != clone->bi_iter.bi_sector', 'false'),
    ('CORE', 'bvec', 'parent->bi_io_vec != clone->bi_io_vec', 'false'),
    ('CORE', 'wrong-selected-target', 'dm_table_find_target(ti->table, clone->bi_iter.bi_sector) != ti', '((void)dm_table_find_target, false)'),
    ('PRODUCT', 'skip-table-gate', '!swapz_round065_dm_owner_matches(ti, bio, owner)', '((void)ti, (void)bio, false)'),
    ('PRODUCT', 'skip-rejection-put', 'swapz_round063_original_dm_owner_put(owner);', '(void)owner;'),
)


def fail(phase, diagnostic=''):
    directory = ROOT / 'build/tests'
    directory.mkdir(parents=True, exist_ok=True)
    private = Path(tempfile.mkdtemp(prefix='round065-table-failure-', dir=directory)) / 'diagnostic.log'
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(phase + '\n' + diagnostic[:65536])
    raise SystemExit('ROUND065_FIRST_ERROR ' + phase + ' log=' + str(private.relative_to(ROOT)))


def main():
    sources = {name: (FIXTURES / ('round065-original-' + file + '.cfrag')).read_text()
               for name, file in (('STATE', 'table-state'), ('OWNER', 'table-owner'), ('CORE', 'dm-core'))}
    product = (ROOT / 'src/kernel/dm-target.c').read_text()
    begin, end = '/* ROUND065_PRODUCT_TABLE_GATE_BEGIN */', '/* ROUND065_PRODUCT_TABLE_GATE_END */'
    if product.count(begin) != 1 or product.count(end) != 1:
        fail('actual-product-source-markers')
    sources['PRODUCT'] = product.split(begin, 1)[1].split(end, 1)[0]
    host = (FIXTURES / 'round065-original-table-host.c').read_text()
    with tempfile.TemporaryDirectory(prefix='round065-table-') as temporary:
        for compiler in ('gcc', 'clang'):
            for mutation in (None, *MUTANTS):
                selected = sources.copy()
                name = 'baseline'
                if mutation:
                    part, name, old, new = mutation
                    if selected[part].count(old) != 1:
                        fail('invalid-mutation-anchor ' + name)
                    selected[part] = selected[part].replace(old, new, 1)
                text = host
                for part, content in selected.items():
                    marker = '/* INJECT_' + part + ' */'
                    if text.count(marker) != 1:
                        fail('invalid-fixture-anchor ' + part)
                    text = text.replace(marker, content)
                source = Path(temporary) / (name + '.c')
                binary = Path(temporary) / name
                source.write_text(text)
                build = subprocess.run([compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                                        '-Wconversion', '-Wshadow', '-Werror', '-fsanitize=address,undefined',
                                        '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie',
                                        str(source), '-o', str(binary)], capture_output=True, text=True, timeout=90)
                if build.returncode:
                    fail(f'{compiler}:{name}:compile={build.returncode}', build.stderr)
                run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                          'UBSAN_OPTIONS': 'halt_on_error=1'})
                ok = (run.returncode == 1 and 'ROUND065_FIRST_ERROR scenario=' in run.stderr and
                      'AddressSanitizer' not in run.stderr and 'runtime error:' not in run.stderr) if mutation else (
                      run.returncode == 0 and not run.stderr and 'ROUND065_HOST_PASS' in run.stdout)
                if not ok:
                    fail(f'{compiler}:{name}:semantic={run.returncode}', run.stderr + run.stdout)
            print(f'ROUND065_{compiler.upper()}_ASAN_UBSAN_PASS scenarios=24 semantic_C_mutants={len(MUTANTS)} NO_AUTH')


if __name__ == '__main__':
    main()
