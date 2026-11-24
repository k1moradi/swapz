#!/usr/bin/env python3
"""Compile actual dormant DM guard; no kernel/VM or device access."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BEGIN = '/* ROUND088_SELECTED_DM_GUARD_BEGIN */'
END = '/* ROUND088_SELECTED_DM_GUARD_END */'
MUTANTS = (
    ('!accepting', '(accepting && false)'), ('failed)', '(failed && false))'),
    ('!fresh_descriptor', '(fresh_descriptor && false)'),
    ('candidate->origin == candidate->clone', 'false'),
    ('candidate->origin != observed->origin', 'false'),
    ('candidate->clone != observed->clone', 'false'),
    ('candidate->target != observed->target', 'false'),
    ('candidate->table != observed->table', 'false'),
    ('!candidate->table_epoch', 'false'),
    ('candidate->table_epoch != observed->table_epoch', 'false'),
    ('!candidate->target_epoch', 'false'),
    ('candidate->target_epoch != observed->target_epoch', 'false'),
    ('!candidate->generation', 'false'),
    ('candidate->generation != observed->generation', 'false'),
    ('return -EOPNOTSUPP;\n}', 'return 0;\n}'),
)
HARNESS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef uint64_t u64;
/* INSERT */
#define CHECK(c, v, a, f, n, expected) do { \
    if (swapz_round088_claim_refuse((c),(v),(a),(f),(n)) != (expected)) { \
        fprintf(stderr,"semantic-failure line=%d\n", __LINE__); return 3; \
    } \
} while (0)
int main(void)
{
    int objects[5] = {0};
    const struct swapz_round088_candidate good = {
        &objects[0], &objects[1], &objects[2], &objects[3], 11, 23, 37
    };
    struct swapz_round088_candidate candidate = good, observed = good;
    CHECK(&candidate, &observed, true, false, true, -EOPNOTSUPP);
    CHECK(NULL, &observed, true, false, true, -EOPNOTSUPP);
    CHECK(&candidate, NULL, true, false, true, -EOPNOTSUPP);
    CHECK(&candidate, &observed, false, false, true, -ESHUTDOWN);
    CHECK(&candidate, &observed, true, true, true, -ESHUTDOWN);
    CHECK(&candidate, &observed, true, false, false, -EALREADY);
    candidate.origin = candidate.clone; observed.origin = observed.clone;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.origin = &objects[4];
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; candidate.clone = &objects[4];
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; candidate.target = &objects[4];
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; candidate.table = &objects[4];
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.table_epoch = observed.table_epoch = 0;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.table_epoch++;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.target_epoch = observed.target_epoch = 0;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.target_epoch++;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.generation = observed.generation = 0;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    candidate = good; observed = good; candidate.generation++;
    CHECK(&candidate, &observed, true, false, true, -ESTALE);
    return 0;
}
'''

def main():
    source = Path(sys.argv[1] if len(sys.argv) > 1 else
                  Path(__file__).resolve().parents[2] / 'src/kernel/dm-target.c').read_text()
    if source.count(BEGIN) != 1 or source.count(END) != 1:
        raise SystemExit('guard marker mismatch')
    guard = source.split(BEGIN, 1)[1].split(END, 1)[0]
    with tempfile.TemporaryDirectory(prefix='round088-dm-') as directory:
        path = Path(directory) / 'guard.c'
        binary = path.with_suffix('')
        for compiler in ('gcc', 'clang'):
            for index, mutation in enumerate((None, *MUTANTS)):
                changed = guard
                if mutation:
                    old, new = mutation
                    if guard.count(old) != 1:
                        raise SystemExit(f'mutation anchor {index}')
                    changed = guard.replace(old, new, 1)
                path.write_text(HARNESS.replace('/* INSERT */', changed))
                subprocess.run([compiler, '-std=c11', '-O1', '-g', '-Wall',
                                '-Wextra', '-Wconversion', '-Wshadow', '-Werror',
                                '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                                str(path), '-o', str(binary)], check=True, timeout=30)
                run = subprocess.run([str(binary)], capture_output=True, text=True,
                                     env=dict(os.environ, ASAN_OPTIONS='halt_on_error=1',
                                              UBSAN_OPTIONS='halt_on_error=1'), timeout=10)
                if mutation:
                    if run.returncode != 3 or not run.stderr.startswith('semantic-failure line='):
                        raise SystemExit(f'{compiler} mutant {index}: {run.returncode} {run.stderr[:200]}')
                elif run.returncode or run.stderr:
                    raise SystemExit(f'{compiler} baseline: {run.returncode} {run.stderr[:200]}')
            print(f'{compiler} PASS cases=17 semantic_mutants={len(MUTANTS)} AUTH=0')

if __name__ == '__main__':
    main()
