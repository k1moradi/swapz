#!/usr/bin/env python3
"""Strict executed source-C tests; native DM callback evidence is separate."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / 'tests/runtime/native/fixtures/round071-original-dm-upper-owner.cfrag'
BEGIN = '/* ROUND071_OWNER_COMMON_BEGIN */'
END = '/* ROUND071_OWNER_COMMON_END */'
MUTANTS = (
    ('original-identity', 'owner->original_bio == original_bio', 'owner->original_bio != original_bio'),
    ('target-identity', 'owner->selected_target == target', 'owner->selected_target != target'),
    ('table-identity', 'owner->selected_table == table', 'owner->selected_table != table'),
    ('incarnation-identity', 'owner->generation == generation', 'owner->generation != generation'),
    ('generation-zero', 'generation != 0', 'generation == 0'),
    ('missing-bio', 'owner->original_bio &&', 'owner->original_bio == NULL &&'),
    ('unseen-claim', 'owner->phase != SWAPZ_ROUND071_UNSEEN', 'owner->phase == SWAPZ_ROUND071_UNSEEN'),
    ('requeue-claim', 'owner->phase != SWAPZ_ROUND071_REQUEUED', 'owner->phase == SWAPZ_ROUND071_REQUEUED'),
    ('requeue-guard', 'owner->phase != SWAPZ_ROUND071_OWNED)', 'owner->phase == SWAPZ_ROUND071_OWNED)'),
    ('success-durability', '(!durable && !error)', '(!durable)'),
    ('once-only', 'owner->upper_endio_attempts++;', 'owner->upper_endio_attempts += 2;'),
    ('auth-default-off', '#define SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE 0', '#define SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE 1'),
)
TEST = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
/* SOURCE */
static int fail(unsigned int step) {
    fprintf(stderr, "ROUND071_SEMANTIC_MUTANT_DETECTED step=%u\n", step);
    return 3;
}
int main(void) {
    int bio=1, other_bio=2, target=3, other_target=4, table=5, other_table=6;
    struct swapz_round071_owner owner = {
        .original_bio=&bio, .selected_target=&target, .selected_table=&table,
        .generation=7, .phase=SWAPZ_ROUND071_UNSEEN
    };
    if (swapz_round071_authenticated_handoff()) return fail(1);
    if (swapz_round071_claim(&owner,&other_bio,&target,&table,7)) return fail(2);
    if (swapz_round071_claim(&owner,&bio,&other_target,&table,7)) return fail(3);
    if (swapz_round071_claim(&owner,&bio,&target,&other_table,7)) return fail(4);
    if (swapz_round071_claim(&owner,&bio,&target,&table,8)) return fail(5);
    if (swapz_round071_claim(&owner,&bio,&target,&table,0)) return fail(6);
    if (!swapz_round071_claim(&owner,&bio,&target,&table,7)) return fail(7);
    if (swapz_round071_claim(&owner,&bio,&target,&table,7)) return fail(8);
    if (swapz_round071_terminal(&owner,&bio,&target,&table,7,false,0)) return fail(9);
    if (swapz_round071_requeue(&owner,&bio,&target,&table,8)) return fail(10);
    if (!swapz_round071_requeue(&owner,&bio,&target,&table,7)) return fail(11);
    if (swapz_round071_terminal(&owner,&bio,&target,&table,7,true,0)) return fail(12);
    if (!swapz_round071_claim(&owner,&bio,&target,&table,7)) return fail(13);
    if (!swapz_round071_terminal(&owner,&bio,&target,&table,7,true,0)) return fail(14);
    if (swapz_round071_terminal(&owner,&bio,&target,&table,7,true,-5)) return fail(15);
    if (swapz_round071_requeue(&owner,&bio,&target,&table,7)) return fail(16);
    if (owner.upper_endio_attempts!=1 || owner.final_error!=0) return fail(17);
    owner.original_bio=NULL;
    owner.phase=SWAPZ_ROUND071_UNSEEN;
    if (swapz_round071_claim(&owner,&bio,&target,&table,7)) return fail(18);
    owner.original_bio=&bio;
    owner.phase=SWAPZ_ROUND071_UNSEEN;
    if (!swapz_round071_claim(&owner,&bio,&target,&table,7)) return fail(19);
    if (!swapz_round071_dtr_fail(&owner,&bio,&target,&table,7)) return fail(20);
    if (swapz_round071_dtr_fail(&owner,&bio,&target,&table,7)) return fail(21);
    if (owner.final_error!=-5 || owner.upper_endio_attempts!=2) return fail(22);
    return 0;
}
'''


def first_error(reason: str) -> None:
    raise SystemExit('ROUND071_HOST_FIRST_ERROR ' + reason)


def compile_execute(compiler: str, source: str, label: str, mutant: bool) -> None:
    with tempfile.TemporaryDirectory(prefix='round071-dm-upper-') as temp:
        path = Path(temp) / 'test.c'
        output = Path(temp) / 'test'
        path.write_text(TEST.replace('/* SOURCE */', source))
        args = [compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Wconversion',
                '-Wshadow', '-Werror', '-fsanitize=address,undefined',
                '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                str(path), '-o', str(output)]
        compiled = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if compiled.returncode:
            first_error(compiler + ':' + label + ':compile:' + compiled.stderr[:240].replace('\n',' '))
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
               'UBSAN_OPTIONS': 'halt_on_error=1'}
        result = subprocess.run([str(output)], capture_output=True, text=True,
                                timeout=30, env=env)
        if ('AddressSanitizer' in result.stderr or 'runtime error:' in result.stderr or
                result.returncode < 0):
            first_error(compiler + ':' + label + ':sanitizer')
        if mutant and (result.returncode != 3 or
                       'ROUND071_SEMANTIC_MUTANT_DETECTED' not in result.stderr):
            first_error(compiler + ':' + label + ':mutant-survived')
        if not mutant and result.returncode:
            first_error(compiler + ':' + label + ':baseline')


def main() -> None:
    fragment = FRAGMENT.read_text()
    if fragment.count(BEGIN) != 1 or fragment.count(END) != 1:
        first_error('source-fragment-markers')
    source = fragment.split(BEGIN, 1)[1].split(END, 1)[0]
    for compiler in ('gcc', 'clang'):
        compile_execute(compiler, source, 'baseline', False)
        for label, before, after in MUTANTS:
            if source.count(before) != 1:
                first_error('mutation-anchor:' + label)
            compile_execute(compiler, source.replace(before, after, 1), label, True)
        print(f'ROUND071_{compiler.upper()}_GNU11_ASAN_UBSAN_PASS '
              f'compiled_executed_semantic_C_mutants={len(MUTANTS)} NO_AUTH')


if __name__ == '__main__':
    main()
