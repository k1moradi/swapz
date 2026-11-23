#!/usr/bin/env python3
"""Original pinned Linux DM core vs real product map: HOST ABI executable proof.

Every mutant must compile with zero warnings and execute with a named directed
FIRST_ERROR invariant. This host stub is NOT a genuine Linux build/DM test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'tests/runtime/native/fixtures/round079-original-dm-core-nowait-requeue.c'
PRODUCT = ROOT / 'src/kernel/dm-target.c'
PIN = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
DM_BLOB = '1881d86111fb2e655893ad898cf21b88f0e4e7f3'
HEADER_BLOB = 'cd4faaf5d4275c038d06ccef4da3d77430154388'
PRODUCT_BLOB = 'f1cab252cd990190646c82da81378d1563475826'

# (name, unique source anchor, semantic change, expected C-directed invariant)
# Never qualify a mutant by a compiler diagnostic or by ASan abort alone.
MUTANTS = (
    ('submitted-accounting-lost', 'if (!ti->accounts_remapped_io)',
     'if (false && !ti->accounts_remapped_io)', 'observations.accounted == 1U'),
    ('clone-not-freed-on-requeue', 'free_tio(clone);',
     'if (false) free_tio(clone);', 'observations.freed_clones == 1U'),
    ('requeue-mislabeled-ioerr', 'dm_io_dec_pending(io, BLK_STS_DM_REQUEUE);',
     'dm_io_dec_pending(io, BLK_STS_IOERR);',
     'observations.last_dec_status == BLK_STS_DM_REQUEUE'),
    ('kill-mislabeled-requeue', 'dm_io_dec_pending(io, BLK_STS_IOERR);',
     'dm_io_dec_pending(io, BLK_STS_DM_REQUEUE);',
     'observations.last_dec_status == BLK_STS_IOERR'),
    ('requeue-forgets-swap-release', 'up(&md->swap_bios_semaphore);',
     'if (false) up(&md->swap_bios_semaphore);', 'observations.up == 1U'),
    ('swap-throttle-skips-acquire', 'down(&md->swap_bios_semaphore);',
     'if (false) down(&md->swap_bios_semaphore);', 'observations.down == 1U'),
    ('swap-throttle-ignores-feature',
     'return unlikely((bio->bi_opf & REQ_SWAP) != 0) && unlikely(ti->limit_swap_bios);',
     'return unlikely((bio->bi_opf & REQ_SWAP) != 0) && '
     '(unlikely(ti->limit_swap_bios) || true);', 'observations.down == 0U'),
    ('nowait-unsupported-silently-accepted', 'return BLK_STS_NOTSUPP;',
     'return BLK_STS_OK;', 'source_split_nowait(&clone_info, &target, 8U) == BLK_STS_NOTSUPP'),
    ('nowait-clone-uses-sleep-allocator', 'clone = alloc_tio(ci, ti, 0, &len, GFP_NOWAIT);',
     'clone = alloc_tio(ci, ti, 0, &len, GFP_NOIO);', 'observations.nowait_allocs == 1U'),
    ('nowait-allocation-fault-not-retryable', 'return BLK_STS_AGAIN;',
     'return BLK_STS_IOERR;', 'source_split_nowait(&clone_info, &target, 8U) == BLK_STS_AGAIN'),
    ('nowait-preflush-blocks-instead-of-refusal',
     'bio_wouldblock_error(bio);', 'bio_io_error(bio);',
     'observations.wouldblock == 1U', 0),
    ('nowait-dm-io-oom-misreported',
     'bio_wouldblock_error(bio);', 'bio_io_error(bio);',
     'observations.wouldblock == 1U', 1),
    ('nowait-suspend-misreported',
     'bio_wouldblock_error(bio);', 'bio_io_error(bio);',
     'observations.wouldblock == 1U', 2),
    ('suspend-ordinary-io-rejected-not-queued', 'queue_io(md, bio);',
     'if (false) queue_io(md, bio);', 'observations.queued == 1U'),
    ('requeue-noflush-acceptance-lost', '__noflush_suspending(md) &&',
     'false && __noflush_suspending(md) &&', 'requeued'),
    ('requeue-illegal-path-not-ioerr', 'io->status = BLK_STS_IOERR;',
     'io->status = BLK_STS_DM_REQUEUE;', 'original_io.status == BLK_STS_IOERR'),
    ('ordinary-dm-requeue-disabled', 'if (handle_requeue || handle_polled_eagain)',
     'if ((false && handle_requeue) || handle_polled_eagain)', 'requeued'),
    ('requeue-io-not-added', 'dm_requeue_add_io(io, first_stage);',
     'if (false) dm_requeue_add_io(io, first_stage);', 'observations.requeue_added == 1U'),
    ('requeue-wakeup-lost', 'dm_kick_requeue(md, first_stage);',
     'if (false) dm_kick_requeue(md, first_stage);', 'observations.requeue_kicked == 1U'),
    ('polled-requeue-loses-clear', 'bio_clear_polled(bio);',
     'if (false) bio_clear_polled(bio);', 'observations.polled_cleared == 1U'),
)


def require(condition: bool, diagnostic: str) -> None:
    if not condition:
        raise RuntimeError(diagnostic)


def source_text(path: Path, expected_blob: str) -> str:
    data = path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') +
                          b'\0' + data).hexdigest()
    require(actual == expected_blob,
            f'{path.name}: pinned git blob drift expected={expected_blob} actual={actual}')
    return data.decode('utf-8')


def exact_function(source: str, signature: str) -> str:
    require(source.count(signature) == 1,
            f'original function signature count changed: {signature}')
    start = source.index(signature)
    opening = source.index('{', start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise RuntimeError(f'unbalanced original function: {signature}')


def exact_block(source: str, begin: str, finish: str) -> str:
    require(source.count(begin) == 1,
            f'original fragment start changed/nonunique: {begin[:65]}')
    start = source.index(begin)
    finish_at = source.find(finish, start)
    require(finish_at >= start and finish_at - start < 2400,
            f'original source fragment end changed: {begin[:65]}')
    end = source.index("\n", finish_at + len(finish))
    return source[start:end]


def compiled_source(original_dm: str, original_header: str,
                    product_dm: str) -> str:
    require('list_add_tail(&entry->list, &ctx->incoming);' in product_dm and
            'return DM_MAPIO_SUBMITTED;' in product_dm and
            'if (!ctx->accepting)' in product_dm and
            'SWAPZ_WORK_QUANTUM_BIOS 64U' in product_dm and
            'unlimited incoming BIOs' in product_dm and
            'ti->limit_swap_bios = true;' in product_dm,
            'current production target admission/queue source drift')
    header_nowait = exact_block(original_header, '#define DM_TARGET_NOWAIT',
                                '#define dm_target_supports_nowait(type) ((type)->features & DM_TARGET_NOWAIT)')
    header_map = exact_block(original_header, '#define DM_ENDIO_DONE',
                             '#define DM_MAPIO_KILL')
    require('DM_MAPIO_REQUEUE\tDM_ENDIO_REQUEUE' in header_map and
            'DM_MAPIO_SUBMITTED' in header_map,
            'pristine original DM map enum mismatch')
    # Explicit original target features: *no* DM_TARGET_NOWAIT advertised.
    features_pattern = re.compile(r'\.features = (DM_TARGET_SINGLETON \| DM_TARGET_ALWAYS_WRITEABLE),')
    features = features_pattern.findall(product_dm)
    require(len(features) == 1 and 'DM_TARGET_NOWAIT' not in features[0],
            'product target features no longer match original expected source')
    pieces = {
        '/* SOURCE_HEADER_NOWAIT */': header_nowait,
        '/* SOURCE_HEADER_MAPIO */': header_map,
        '/* SOURCE_SWAP_LIMIT */': exact_function(original_dm,
                                                     'static bool swap_bios_limit(struct dm_target *ti, struct bio *bio)'),
        '/* SOURCE_MAP_BIO */': exact_function(original_dm,
                                                 'static void __map_bio(struct bio *clone)'),
        '/* SOURCE_HANDLE_REQUEUE */': exact_function(original_dm,
                                                        'static bool dm_handle_requeue(struct dm_io *io, bool first_stage)'),
        '/* SOURCE_NOWAIT_ALLOC */': exact_block(original_dm,
            'if (unlikely(ci->bio->bi_opf & REQ_NOWAIT)) {',
            '\treturn BLK_STS_OK;'),
        '/* SOURCE_NOWAIT_PREFLUSH */': exact_block(original_dm,
            '/* Only support nowait for normal IO */',
            '\t\tio = alloc_io(md, bio, GFP_NOIO);\n\t}'),
        '/* SOURCE_SUSPEND */': exact_block(original_dm,
            'if (unlikely(test_bit(DMF_BLOCK_IO_FOR_SUSPEND, &md->flags))) {',
            '\t\tgoto out;\n\t}'),
    }
    source = TEMPLATE.read_text(encoding='utf-8')
    require(source.endswith('\n'), 'fixture missing final newline')
    for tag, replacement in pieces.items():
        require(source.count(tag) == 1, f'fixture source expansion marker drift: {tag}')
        source = source.replace(tag, replacement, 1)
    source = source.replace('SOURCE_PRODUCT_TARGET_FEATURES', '(' + features[0] + ')')
    require('/* SOURCE_' not in source and 'SOURCE_PRODUCT_TARGET_FEATURES' not in source,
            'unexpanded original marker')
    return source


def standard_flag(compiler: str) -> str:
    for flag in ('-std=c23', '-std=c2x'):
        attempt = subprocess.run([compiler, flag, '-x', 'c', '-fsyntax-only', '-'],
                                 input='int main(void) { return 0; }\n',
                                 text=True, capture_output=True)
        if attempt.returncode == 0:
            return flag
    raise RuntimeError(f'{Path(compiler).name}: no C23 or C2x mode')


def build_and_run(compiler: str, std: str, source: Path, executable: Path) -> subprocess.CompletedProcess[str]:
    flags = [std, '-O1', '-g', '-Wall', '-Wextra', '-Wconversion', '-Wshadow',
             '-Werror', '-pedantic', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-no-pie']
    build = subprocess.run([compiler, *flags, str(source), '-o', str(executable)],
                           capture_output=True, text=True)
    require(build.returncode == 0, f'{Path(compiler).name} COMPILE_FAILED '
            f'{source.name}: {first_error(build)}')
    require(build.stderr.strip() == '', f'{Path(compiler).name} compiler diagnostic '
            f'{source.name}: {first_error(build)}')
    result = subprocess.run([str(executable)], capture_output=True,
                            text=True, timeout=30)
    return result


def first_error(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout or 'no diagnostics').splitlines()
    return next((line.strip()[:350] for line in lines if 'error:' in line),
                lines[0][:350])


def mutate(source: str, item: tuple) -> str:
    name, anchor, replacement, _, *rest = item
    occurrences = source.count(anchor)
    requested = rest[0] if rest else 0
    require(requested < occurrences and (occurrences == 1 or len(rest) == 1),
            f'{name}: expected scoped source anchor, count={occurrences}')
    if occurrences == 1:
        return source.replace(anchor, replacement, 1)
    segments = source.split(anchor)
    # Restore all but the selected nth instance without modifying source bytes.
    rebuilt = segments[0]
    for i in range(occurrences):
        rebuilt += (replacement if i == requested else anchor) + segments[i + 1]
    return rebuilt


def verify(dm: Path, header: Path, results_path: Path) -> dict:
    original_dm = source_text(dm, DM_BLOB)
    original_header = source_text(header, HEADER_BLOB)
    product_dm = source_text(PRODUCT, PRODUCT_BLOB)
    generated = compiled_source(original_dm, original_header, product_dm)
    require(len(MUTANTS) >= 12, 'insufficient independent C semantic mutants')
    compilers = {}
    with tempfile.TemporaryDirectory(prefix='swapz-r079-a11-dmcore-') as scratch_name:
        scratch = Path(scratch_name)
        for compiler_name in ('gcc', 'clang'):
            compiler = shutil.which(compiler_name)
            require(compiler is not None, f'missing independent compiler: {compiler_name}')
            std = standard_flag(compiler)
            baseline_source = scratch / f'baseline-{compiler_name}.c'
            baseline_source.write_text(generated, encoding='utf-8')
            baseline = build_and_run(compiler, std, baseline_source,
                                     scratch / f'baseline-{compiler_name}')
            require(baseline.returncode == 0 and
                    'PASS_HOST_ONLY ROUND079_AGENT11_DM_CORE_SOURCE_REQUEUE_NOWAIT'
                    in baseline.stdout,
                    f'{compiler_name} BASELINE_FAILED: {first_error(baseline)}')
            killed = []
            for index, mutation in enumerate(MUTANTS):
                name, _, _, expected, *_ = mutation
                mutated = mutate(generated, mutation)
                mutation_source = scratch / f'mutant-{compiler_name}-{index:02d}.c'
                mutation_source.write_text(mutated, encoding='utf-8')
                execution = build_and_run(compiler, std, mutation_source,
                                          scratch / f'mutant-{compiler_name}-{index:02d}')
                require(execution.returncode == 1 and
                        execution.stderr.startswith('FIRST_ERROR line=') and
                        f'invariant={expected}' in execution.stderr,
                        f'{compiler_name} MUTANT_{index:02d}_{name} semantic kill '
                        f'not executed with expected assertion: {first_error(execution)}')
                killed.append(name)
            compilers[compiler_name] = {
                'standard':std,'baseline':'PASS_HOST_ABI_ONLY',
                'mutants_compiled':len(killed),'mutants_executed':len(killed),
                'semantic_mutants_killed':len(killed),'names':killed,
            }
    result = {
        'status':'PASS_HOST_ABI_ONLY','pinned_linux_commit':PIN,
        'pinned_dm_blob':DM_BLOB,'pinned_dm_header_blob':HEADER_BLOB,
        'product_dm_blob':PRODUCT_BLOB,'compilers':compilers,
        'upstream_map_source':'drivers/md/dm.c:1406-1461',
        'upstream_nowait_source':'drivers/md/dm.c:1759-1774,1991-2010,2088-2096',
        'upstream_requeue_source':'drivers/md/dm.c:903-948',
        'actual_original_linux_native':'NOT_RUN',
        'actual_loaded_dm':'NOT_RUN',
        'real_upper_queue_cap':'NOT_PROVEN',
        'product_target_supports_nowait':False,
        'source_mapped_authenticated':0,'phase_a':'BLOCKED',
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n',
                            encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pinned-dm', type=Path, required=True)
    parser.add_argument('--pinned-header', type=Path, required=True)
    parser.add_argument('--json', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = verify(arguments.pinned_dm, arguments.pinned_header, arguments.json)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as failure:
        print('ROUND079_AGENT11_FIRST_ERROR ' + str(failure)[:700], file=sys.stderr)
        return 1
    count = len(MUTANTS)
    print(f'PASS_HOST_ABI_ONLY pinned DM blob+header+product verified; '
          f'GCC {count}/{count} + Clang {count}/{count} compiled AND executed '
          'C semantic mutants; NO_AUTH; PHASE_A=BLOCKED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
