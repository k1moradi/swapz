#!/usr/bin/env python3
"""Verify immutable genuine source and exercise a SEPARATE C23 clone-debt model.

Product statements are compiled VERBATIM within minimal host stubs. Ownership,
unique token accounting, concurrency and upper ACK are HOST MODELS, not kernel
objects. A mutation counts only if compilation SUCCEEDS and the process RUNS
and prints its directed FIRST_ERROR invariant (not sanitizer/compiler death).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = ROOT / 'src/kernel/dm-target.c'
FIXTURE = ROOT / 'tests/runtime/native/fixtures/round081-actual-dm-bio-debt-ownership.c'
PINNED_LINUX = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
ORIGINAL_DM_BLOB = '1881d86111fb2e655893ad898cf21b88f0e4e7f3'
ORIGINAL_HEADER_BLOB = 'cd4faaf5d4275c038d06ccef4da3d77430154388'
PRODUCT_BLOB = 'f1cab252cd990190646c82da81378d1563475826'

# Mutations alter executable modeled transitions, never assertions or flags.
# Multiple distinct variants may affect the same anchor and are compiled
# independently from a fresh identical baseline, never cumulatively.
# (test-id, anchored line, replacement, first semantic invariant)
MUTANTS = (
    ('lost-admission-charge', 'ledger->outstanding += 1U;',
     'ledger->outstanding += 0U;', 'ledger.outstanding == 1U'),
    ('duplicate-admission-charge', 'ledger->outstanding += 1U;',
     'ledger->outstanding += 2U;', 'ledger.outstanding == 1U'),
    ('preaccept-requeue-owned', 'slot->accepted = false;',
     'slot->accepted = true;', 'rejected.accepted == false'),
    ('splice-premature-retires', 'slot->stage = LOCAL; return true;',
     'slot->stage = ACKED; return true;', 'slot->stage == LOCAL'),
    ('lost-prepared-transition', 'slot->stage = PREPARED;',
     'slot->stage = LOCAL;', 'slot->stage == PREPARED'),
    ('lost-prepared-charge', 'slot->prep_owned = true;',
     'slot->prep_owned = false;', 'slot->prep_owned'),
    ('prep-release-not-cleared', 'slot->prep_owned = false;',
     'slot->prep_owned = true;', '!slot->prep_owned'),
    ('batch-transition-lost', 'slot->stage = BATCH; return true;',
     'slot->stage = LOCAL; return true;', 'slot->stage == BATCH'),
    ('lower-start-flag-missing', 'slot->lower_pending = true;',
     'slot->lower_pending = false;', 'slot->lower_pending'),
    ('lower-stage-missing', 'slot->stage = LOWER_INFLIGHT;',
     'slot->stage = BATCH;', 'slot->stage == LOWER_INFLIGHT'),
    ('lower-count-double', 'ledger->lower_count += 1U;',
     'ledger->lower_count += 2U;', 'ledger.lower_count == 1U'),
    ('lower-finish-pending-leaks', 'slot->lower_pending = false;',
     'slot->lower_pending = true;', '!slot->lower_pending'),
    ('lower-error-falsely-success', 'slot->lower_success = !error;',
     'slot->lower_success = error ? true : !error;', '!failed->lower_success'),
    ('deferred-acks-too-early', 'slot->stage = DEFERRED_UPPER;',
     'slot->stage = ACKED;', 'slot->stage == DEFERRED_UPPER'),
    ('deferred-count-missing', 'ledger->deferred_count += 1U;',
     'ledger->deferred_count += 0U;', 'ledger.deferred_count == 1U'),
    ('terminal-uncharge-lost', 'ledger->outstanding -= 1U;',
     'ledger->outstanding -= 0U;', 'ledger.outstanding == 0U'),
    ('fabricated-double-ack', 'slot->ack_calls += 1U;',
     'slot->ack_calls += 2U;', 'slot->ack_calls == 1U'),
    ('terminal-state-not-acked', 'slot->stage = ACKED;',
     'slot->stage = DEFERRED_UPPER;', 'slot->stage == ACKED'),
    ('terminal-lower-error-hidden', 'slot->terminal_error = error;',
     'slot->terminal_error = (error == -5 ? 0 : error);', 'failed->terminal_error == -5'),
    ('closed-admission-reopens', 'ledger->accepting = false;',
     'ledger->accepting = true;', '!ledger.accepting'),
    ('read-priority-lost', 'slot->is_read = is_read;',
     'slot->is_read = !is_read;', 'ledger.tokens[1].is_read'),
    ('compressed-ticket-double-charge', 'ledger->ticket_count += 1U;',
     'ledger->ticket_count += 2U;', 'ledger.ticket_count == 1U'),
    ('compressed-byte-budget-drift', 'ledger->copy_bytes += bytes;',
     'ledger->copy_bytes += bytes + 1U;', 'ledger.copy_bytes == 3568U'),
    ('gc-reader-pin-vanishes', 'slot->gc_reader_pins += 1U;',
     'slot->gc_reader_pins += 0U;', 'original->gc_reader_pins == 1U'),
)


def require(value: bool, description: str) -> None:
    if not value:
        raise RuntimeError(description)


def source_bytes(path: Path, expected_sha: str) -> str:
    value = path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(value)).encode('ascii') + b'\0' + value).hexdigest()
    require(actual == expected_sha, f'{path}: full Git blob expected={expected_sha}, got={actual}')
    return value.decode('utf-8')


def function_body(source: str, signature: str) -> str:
    require(source.count(signature) == 1, f'nonunique source function signature {signature}')
    start = source.index(signature)
    begin = source.index('{', start)
    depth = 0
    for index in range(begin, len(source)):
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise RuntimeError('unbalanced source function ' + signature)


def compiled_fixture(dm_source: str, header_source: str, product_source: str) -> str:
    original_map = function_body(dm_source, 'static void __map_bio(struct bio *clone)')
    product_map = function_body(product_source, 'static int swapz_map(struct dm_target *ti, struct bio *bio)')
    product_worker = function_body(product_source, 'static void swapz_worker_pass(struct swapz_dm *ctx)')
    product_complete = function_body(product_source, 'static void swapz_complete(struct bio *bio, int error)')
    product_defer = function_body(product_source, 'static void swapz_defer_upper_completion(struct swapz_dm *ctx, struct bio *bio)')
    product_drain = function_body(product_source, 'static void swapz_drain(struct dm_target *ti)')
    originals = (
        'case DM_MAPIO_SUBMITTED:', '/* target has assumed ownership of this io */',
        'case DM_MAPIO_REQUEUE:', 'free_tio(clone);',
        'dm_io_dec_pending(io, BLK_STS_DM_REQUEUE);',
    )
    for fragment in originals:
        require(fragment in original_map, f'original DM core semantics drift: {fragment}')
    require('DM_TARGET_NOWAIT' in header_source and 'DM_MAPIO_SUBMITTED' in header_source,
            'original DM header feature/API drift')
    feature = '.features = (DM_TARGET_SINGLETON | DM_TARGET_ALWAYS_WRITEABLE),'
    require(product_source.count(feature) == 1, 'actual target features drift')
    anchors = (
        (product_map, 'list_add_tail(&entry->list, &ctx->incoming);'),
        (product_worker, 'list_splice_init(&ctx->incoming, &local);'),
        (product_complete, 'bio_endio(bio);'),
    )
    for body, fragment in anchors:
        require(body.count(fragment) == 1, f'product unique executable anchor drift: {fragment}')
    requirements = (
        (product_map, 'return DM_MAPIO_SUBMITTED;'),
        (product_map, 'if (!ctx->accepting)'),
        (product_worker, 'remaining = SWAPZ_WORK_QUANTUM_BIOS;'),
        (product_complete, 'swapz_release_prepared(bio);'),
        (product_defer, 'bio_list_add(&ctx->deferred_upper_completions, bio);'),
        (product_drain, 'WRITE_ONCE(ctx->accepting, false);'),
        (product_drain, 'drain_workqueue(ctx->workqueue);'),
    )
    for body, fragment in requirements:
        require(fragment in body, f'product lifecycle source drift: {fragment}')
    require('unlimited incoming BIOs' in product_source,
            'finite prep is not accepted-depth source anchor')
    require('#define SWAPZ_WORK_QUANTUM_BIOS 64U' in product_source,
            'worker quantum changed')
    replacements = dict(zip(('/* SOURCE_PRODUCT_ENQUEUE */',
                             '/* SOURCE_PRODUCT_SPLICE */',
                             '/* SOURCE_PRODUCT_ENDIO */'),
                            (value for _, value in anchors), strict=True))
    fixture = FIXTURE.read_text(encoding='utf-8')
    for tag, content in replacements.items():
        require(fixture.count(tag) == 1, f'missing/duplicate marker {tag}')
        fixture = fixture.replace(tag, content, 1)
    require('/* SOURCE_PRODUCT_' not in fixture, 'unexpanded source marker')
    return fixture


def standard_flag(compiler: str) -> str:
    for standard in ('-std=c23', '-std=c2x'):
        result = subprocess.run((compiler, standard, '-x', 'c', '-fsyntax-only', '-'),
                                input='int main(void) { return 0; }\n',
                                text=True, capture_output=True, check=False)
        if result.returncode == 0:
            return standard
    raise RuntimeError(f'{compiler}: missing C23 or C2x')


def first_error(result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout or 'no diagnostic').splitlines()
    return next((line.strip() for line in lines if 'error:' in line or 'FIRST_ERROR' in line),
                lines[0])[:450]


def compile_execute(compiler: str, standard: str, source: Path,
                    executable: Path) -> subprocess.CompletedProcess[str]:
    flags = (standard, '-O1', '-g', '-Wall', '-Wextra', '-Wshadow',
             '-Wconversion', '-Wsign-conversion', '-Werror', '-pedantic',
             '-pthread', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             '-fno-omit-frame-pointer', '-no-pie')
    compiled = subprocess.run((compiler, *flags, str(source), '-o', str(executable)),
                              text=True, capture_output=True, check=False)
    require(compiled.returncode == 0 and not compiled.stderr.strip(),
            f'{Path(compiler).name} COMPILATION_FAILED {source.name}: {first_error(compiled)}')
    return subprocess.run((str(executable),), text=True, capture_output=True,
                          timeout=20, check=False)


def verify(original_dm: Path, original_header: Path, output: Path) -> dict:
    dm_source = source_bytes(original_dm, ORIGINAL_DM_BLOB)
    header_source = source_bytes(original_header, ORIGINAL_HEADER_BLOB)
    product_source = source_bytes(PRODUCT, PRODUCT_BLOB)
    baseline = compiled_fixture(dm_source, header_source, product_source)
    require(len(MUTANTS) >= 16, 'insufficient semantic mutants')
    for name, anchor, replacement, _ in MUTANTS:
        require(anchor != replacement and baseline.count(anchor) == 1,
                f'mutant {name} source anchor missing/nonunique: {anchor}')
    compilers = {}
    with tempfile.TemporaryDirectory(prefix='round081-agent11-host-') as location:
        directory = Path(location)
        for name in ('gcc', 'clang'):
            compiler = shutil.which(name)
            require(compiler is not None, f'compiler missing: {name}')
            standard = standard_flag(compiler)
            baseline_source = directory / f'{name}-baseline.c'
            baseline_source.write_text(baseline, encoding='utf-8')
            result = compile_execute(compiler, standard, baseline_source,
                                     directory / f'{name}-baseline')
            require(result.returncode == 0 and
                    'PASS_HOST_ONLY ROUND081_AGENT11_ACTUAL_CLONE_DEBT_NO_AUTH' in result.stdout,
                    f'{name} BASELINE_FAILED: {first_error(result)}')
            qualified = []
            for index, (mutation_name, anchor, replacement, invariant) in enumerate(MUTANTS):
                changed = baseline.replace(anchor, replacement, 1)
                mutated_source = directory / f'{name}-mutant-{index:02d}.c'
                mutated_source.write_text(changed, encoding='utf-8')
                execution = compile_execute(compiler, standard, mutated_source,
                                             directory / f'{name}-mutant-{index:02d}')
                require(execution.returncode == 1 and
                        execution.stderr.startswith('FIRST_ERROR scenario=') and
                        f'invariant={invariant}' in execution.stderr and
                        'AddressSanitizer' not in execution.stderr and
                        'runtime error:' not in execution.stderr,
                        f'{name} MUTANT_{index:02d}_{mutation_name} missing executable '
                        f'semantic kill [{invariant}]: {first_error(execution)}')
                qualified.append(mutation_name)
            compilers[name] = {'standard': standard, 'baseline': 'PASS',
                               'mutants_compiled': len(qualified),
                               'mutants_executed': len(qualified),
                               'mutants_semantically_killed': len(qualified),
                               'mutants': qualified}
    result = {
        'status': 'PASS_HOST_SOURCE_LINKED_MODEL_ONLY',
        'pinned_linux_commit': PINNED_LINUX,
        'pinned_linux_dm_git_blob': ORIGINAL_DM_BLOB,
        'pinned_linux_dm_header_git_blob': ORIGINAL_HEADER_BLOB,
        'product_dm_target_git_blob': PRODUCT_BLOB,
        'product_source_lines': {'admission': 'swapz_map',
                                 'splice': 'swapz_worker_pass',
                                 'ack': 'swapz_complete',
                                 'deferred': 'swapz_defer_upper_completion',
                                 'drain': 'swapz_drain'},
        'execution_type': 'ROOTLESS_HOST_C23_MODEL_WITH_THREE_VERBATIM_PRODUCT_C_STATEMENTS',
        'actual_linux_native': 'NOT_RUN', 'actual_loaded_dm': 'NOT_RUN',
        'physical_durability': 'NOT_PROVEN', 'production_bio_budget': 'NOT_IMPLEMENTED',
        'legal_queue_full_requeue': 'NOT_PROVEN', 'source_mapped_authenticated': 0,
        'phase_a': 'BLOCKED', 'direct_handoff': 'DISABLED',
        'forced_raw_bypass': 'DISABLED', 'import_active': 0,
        'compilers': compilers,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n',
                      encoding='utf-8')
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pinned-dm', type=Path, required=True)
    parser.add_argument('--pinned-header', type=Path, required=True)
    parser.add_argument('--json', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        verified = verify(arguments.pinned_dm, arguments.pinned_header, arguments.json)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as failure:
        print('ROUND081_AGENT11_FIRST_ERROR ' + str(failure)[:700], file=sys.stderr)
        return 1
    count = len(MUTANTS)
    print(f'PASS_HOST_ONLY ROUND081_AGENT11 source pins+actual C fragments '
          f'GCC {count}/{count}, Clang {count}/{count} independently compiled '
          'AND EXECUTED semantic C mutants; no live DM/source auth')
    require(verified['phase_a'] == 'BLOCKED', 'unexpected state')
    return 0


if __name__ == '__main__':
    sys.exit(main())
