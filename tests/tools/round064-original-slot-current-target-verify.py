#!/usr/bin/env python3
"""Compile actual original route helper and production DM candidate/put C under host stubs."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/runtime/native/fixtures'
ORIGINAL = FIXTURES / 'round064-original-slot-route.cfrag'
HOST = FIXTURES / 'round064-slot-route-host.c'
PRODUCT = ROOT / 'src/kernel/dm-target.c'
MUTANTS = (
    ('original', 'stale-epoch', 'swapz_round028_slot_epoch(folio->swap) == owner->slot_epoch', 'true'),
    ('original', 'wrong-area', '(!submitted_area || area == submitted_area)', '((void)submitted_area, true)'),
    ('original', 'swapfile', '(area->flags & SWP_BLKDEV)', 'true'),
    ('original', 'partition', '!bdev_is_partition(area->bdev)', '((void)bdev_is_partition(area->bdev), true)'),
    ('original', 'extent', 'swap_folio_sector(folio) == bio->bi_iter.bi_sector', '((void)swap_folio_sector(folio), true)'),
    ('original', 'writeback', '!folio_test_writeback(folio)', '((void)folio_test_writeback(folio), false)'),
    ('original', 'slot', 'folio->swap.val != owner->source_swap_entry', 'false'),
    ('original', 'private', 'refcount_read(&owner->references) != 1', '((void)refcount_read(&owner->references), false)'),
    ('original', 'page-identity', 'owner->round064_source_page == clone->bi_io_vec[0].bv_page', 'true'),
    ('product', 'target-instance', 'ctx->target != ti', 'false'),
    ('product', 'target-offset', 'ti->begin ||', 'false ||'),
    ('product', 'target-bound', 'sector > ti->len - SWAPZ_SECTORS', 'false'),
    ('product', 'target-bdev', 'dm_disk(md)->part0 != bio->bi_bdev', '((void)dm_disk(md), false)'),
    ('product', 'reject-ref', 'swapz_round063_original_dm_owner_put(owner);\n\t\treturn NULL;', '/* mutant: leak on rejection */\n\t\treturn NULL;'),
    ('product', 'terminal-clear', 'entry->round063_owned_original = NULL;', '/* mutant: stale descriptor ref */'),
    ('MAP_ACQUIRE', 'map-acquisition', 'swapz_round064_current_owner_get(ti, ctx, bio);',
        '((void)swapz_round064_current_owner_get, (void)ti, (void)ctx, (void)bio, (struct swapz_ci_owned_payload *)NULL);'),
    ('MAP_REJECT', 'map-reject-cleanup', 'swapz_round064_current_owner_put(entry);', '(void)entry;'),
    ('COMPLETE_PUT', 'completion-cleanup', 'swapz_round064_current_owner_put(entry);', '(void)entry;'),
)


def check(ok, phase, details=''):
    if not ok:
        logs = ROOT / 'build/tests'
        logs.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix='round064-route-failure-', dir=logs))
        log = directory / 'diagnostic.log'
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(phase + '\n' + details[:65536])
        raise RuntimeError('ROUND064_FIRST_ERROR ' + phase + ' log=' + str(log.relative_to(ROOT)))


def extract(text, begin, end):
    check(text.count(begin) == text.count(end) == 1, 'source-markers')
    return text.split(begin, 1)[1].split(end, 1)[0]


def main():
    original = ORIGINAL.read_text(encoding='utf-8')
    product_source = PRODUCT.read_text(encoding='utf-8')
    product = extract(product_source,
                      '/* ROUND064_CURRENT_TARGET_OWNER_BEGIN */',
                      '/* ROUND064_CURRENT_TARGET_OWNER_END */')
    callsites = {name: extract(product_source, f'/* ROUND064_{name}_BEGIN */',
                              f'/* ROUND064_{name}_END */')
                 for name in ('MAP_ACQUIRE', 'MAP_REJECT', 'COMPLETE_PUT')}
    sources = {'original': original, 'product': product, **callsites}
    host = HOST.read_text(encoding='utf-8')
    check(host.count('/* ROUND064_INJECT_ORIGINAL */') == 1 and
          host.count('/* ROUND064_INJECT_PRODUCT */') == 1, 'fixture-markers')
    for selected, name, old, new in MUTANTS:
        check(sources[selected].count(old) == 1,
              'mutant-anchor=' + name)
    with tempfile.TemporaryDirectory(prefix='round064-route-') as temporary:
        directory = Path(temporary)
        for compiler in ('gcc', 'clang'):
            for case in (None, *MUTANTS):
                changed = sources.copy()
                name = 'baseline'
                if case:
                    selected, name, old, new = case
                    changed[selected] = changed[selected].replace(old, new, 1)
                text = host.replace('/* ROUND064_INJECT_ORIGINAL */', changed['original']).replace(
                    '/* ROUND064_INJECT_PRODUCT */', changed['product'])
                for callsite in callsites:
                    text = text.replace(f'/* ROUND064_INJECT_{callsite} */', changed[callsite])
                path = directory / (name + '.c')
                binary = directory / name
                path.write_text(text, encoding='utf-8')
                build = subprocess.run([compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                    '-Wconversion', '-Wshadow', '-Werror', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie',
                    str(path), '-o', str(binary)], capture_output=True, text=True, timeout=90)
                check(build.returncode == 0, f'{compiler}:{name}:compile-exit={build.returncode}', build.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60,
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                         'UBSAN_OPTIONS': 'halt_on_error=1'})
                if case:
                    check(result.returncode == 1 and 'ROUND064_FIRST_ERROR scenario=' in result.stderr
                          and 'AddressSanitizer' not in result.stderr and 'runtime error:' not in result.stderr,
                          f'{compiler}:{name}:nonsemantic-exit={result.returncode}', result.stderr + result.stdout)
                else:
                    check(result.returncode == 0 and 'ROUND064_SLOT_ROUTE_HOST_PASS' in result.stdout
                          and not result.stderr, f'{compiler}:baseline-exit={result.returncode}', result.stderr + result.stdout)
            print(f'ROUND064_{compiler.upper()}_ASAN_UBSAN_PASS scenarios=27 semantic_C_mutants={len(MUTANTS)} NO_AUTH')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error)[:240])
        raise SystemExit(2) from None
