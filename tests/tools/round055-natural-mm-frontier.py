#!/usr/bin/env python3
"""Run finite-service comparative scheduler and actual named C mutant oracles."""
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/runtime/native/fixtures/round055-natural-mm-frontier.c'
# Reuse unmodified strict sanitizer compiler invocation and timeout contract.
HELPERS = runpy.run_path(str(ROOT / 'tests/tools/round054-natural-mm-coalescing.py'))
invoke = HELPERS['invoke']
compile_c = HELPERS['checked_compile']
MUTANTS = (
    ('decisions', 'count < 2U || count >= PACK', 'count < 1U || count >= PACK', 'singleton_now'),
    ('decisions', 'disk.active.active || fences || recent < 2U', 'disk.active.active || (fences & READ_FENCE) || recent < 2U', 'fence_now'),
    ('decisions', 'recent < 2U', 'recent < 1U', 'no_observed_burst'),
    ('decisions', 'free_foreground_blocks() <= 4U', 'free_foreground_blocks() < 4U', 'pressure_now'),
    ('decisions', 'disk.tick - disk.pending[0].arrival >= HOLD', 'disk.tick - disk.pending[0].arrival > HOLD', 'hard_deadline'),
    ('rollback', 'disk.tick < flight.due', 'disk.tick + 1U < flight.due', 'service_not_early'),
    ('rollback', 'if (durable) {', 'if (error == 0) {', 'durable_aborted_accounting'),
)


def validate(output):
    rows = {}
    lines = output.splitlines()
    if not lines or not re.fullmatch(r'PASS frontier scenarios=13 policies=3 pending_bytes=\d+ pending_metadata=\d+ NOT_AUTH=1 PHASE_A=BLOCKED', lines[-1]):
        raise RuntimeError('missing exact frontier baseline marker')
    for line in lines[:-1]:
        marker, name, *cells = line.split()
        if marker != 'TRACE':
            raise RuntimeError('unexpected baseline output')
        row = dict(cell.split('=', 1) for cell in cells)
        policy = int(row['policy'])
        key = (name, policy)
        if key in rows or policy not in (0, 1, 2):
            raise RuntimeError('invalid or duplicate scenario policy')
        rows[key] = row
        if int(row['hold_max']) > 2 or int(row['peak_payload']) > 32768:
            raise RuntimeError('unbounded modeled retention')
        if int(row['total_attempted_req']) < int(row['total_completed_req']):
            raise RuntimeError('lower request accounting mismatch')
    if len(rows) != 39:
        raise RuntimeError('missing scenario policy row')
    names = {name for name, _ in rows}
    matched = improved = 0
    for name in names:
        ready, adaptive = rows[name, 1], rows[name, 2]
        if len({rows[name, p]['arrivals'] for p in range(3)}) != 1:
            raise RuntimeError('nonidentical external workload')
        # Equal successful IDs, not just equal counts. Do not silently equate
        # unmatched workloads or ignore differences in acceptance/failures.
        if all(ready[k] == adaptive[k] for k in ('ids', 'accepted', 'failed', 'dropped')):
            matched += 1
            if int(adaptive['total_attempted_req']) < int(ready['total_attempted_req']) and int(adaptive['total_completed']) < int(ready['total_completed']):
                improved += 1
    if matched != len(names) or not improved:
        raise RuntimeError('matched useful-work or adaptive benefit witness changed')
    print(f'MATCHED ready_adaptive={matched} lower_requests_and_bytes={improved}')


def run():
    source = FIXTURE.read_text(encoding='utf-8')
    baseline = None
    with tempfile.TemporaryDirectory(prefix='swapz-frontier-') as directory:
        work = Path(directory)
        for name in ('gcc', 'clang'):
            compiler = shutil.which(name)
            if not compiler:
                raise RuntimeError(f'missing {name}')
            standard = next((flag for flag in ('-std=c23', '-std=c2x') if invoke(
                [compiler, flag, '-x', 'c', '-fsyntax-only', '-'],
                input_text='int main(void) { return 0; }\n').returncode == 0), None)
            if not standard:
                raise RuntimeError(f'{name} C23 unavailable')
            binary = work / name
            compile_c(compiler, standard, FIXTURE, binary)
            result = invoke([str(binary)])
            if result.returncode or result.stderr:
                raise RuntimeError(f'{name} baseline exit={result.returncode} {result.stderr[:240]}')
            if baseline is not None and baseline != result.stdout:
                raise RuntimeError('compiler frontier counter disagreement')
            baseline = result.stdout
            validate(baseline)
            print(f'{name} {standard} ASan+UBSan\n{baseline}', end='')
            for index, (case, original, replacement, oracle) in enumerate(MUTANTS):
                if source.count(original) != 1:
                    raise RuntimeError(f'ambiguous mutation: {oracle}')
                mutant = work / f'mutant-{index}.c'
                mutant.write_text(source.replace(original, replacement, 1), encoding='utf-8')
                compile_c(compiler, standard, mutant, binary)
                rejected = invoke([str(binary), case])
                if rejected.returncode != 1 or rejected.stdout or rejected.stderr != f'FIRST_ERROR {oracle}\n':
                    raise RuntimeError(f'{name} {oracle}: exit={rejected.returncode} {rejected.stderr[:200]}')
            print(f'{name} compiled_and_executed_semantic_mutants={len(MUTANTS)}')


if __name__ == '__main__':
    try:
        run()
    except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        print(f'FIRST_ERROR round055-frontier: {str(error)[:300]}', file=sys.stderr)
        sys.exit(1)
