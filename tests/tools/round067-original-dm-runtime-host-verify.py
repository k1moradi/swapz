#!/usr/bin/env python3
"""Compile/execute exact new native table predicate with two strict sanitizers.

This is additional source-C mutant coverage, not evidence of native DM execution.
The separate pinned original UML KUnit exercises the actual core callback chain.
"""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / 'tests/runtime/native/fixtures/round067-original-dm-dispatch-runtime.cfrag'
BEGIN, END = '/* ROUND067_COMMON_BEGIN */', '/* ROUND067_COMMON_END */'
MUTANTS = (
    ('first-zero', 'first_incarnation != 0', 'first_incarnation == 0'),
    ('next-zero', 'next_incarnation != 0', 'next_incarnation == 0'),
    ('equal-generation', 'next_incarnation > first_incarnation',
     'next_incarnation >= first_incarnation'),
    ('old-generation', 'next_incarnation > first_incarnation',
     'next_incarnation < first_incarnation'),
    ('nonmonotone', 'next_incarnation > first_incarnation',
     'next_incarnation != first_incarnation'),
    ('zero-geometry', 'first_sectors > 0', 'first_sectors == 0'),
    ('changed-geometry', 'first_sectors == next_sectors',
     'first_sectors != next_sectors'),
    ('ignore-geometry', 'first_sectors == next_sectors',
     '((void)next_sectors, true)'),
)
TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
typedef uint64_t u64;
typedef uint64_t sector_t;
/* SOURCE_INSERT */
struct scenario {
    u64 first, next;
    sector_t first_sectors, next_sectors;
    bool accepted;
};
static const struct scenario scenarios[] = {
    {1, 2, 64, 64, true},
    {1, 1, 64, 64, false},
    {0, 2, 64, 64, false},
    {1, 0, 64, 64, false},
    {2, 1, 64, 64, false},
    {1, 2, 64, 128, false},
    {1, 2, 0, 0, false},
    {UINT64_MAX - 1, UINT64_MAX, 64, 64, true},
    {UINT64_MAX, 1, 64, 64, false},
    {6, 7, 64, 64, true}
};
int main(void)
{
    for (unsigned int index = 0; index < sizeof(scenarios)/sizeof(scenarios[0]); ++index) {
        const struct scenario *scenario = &scenarios[index];
        bool actual = swapz_round067_replacement_is_distinct(scenario->first,
            scenario->next, scenario->first_sectors, scenario->next_sectors);
        if (actual != scenario->accepted) {
            fprintf(stderr, "semantic-failure case=%u\n", index);
            return 3;
        }
    }
    return 0;
}
'''


def fail(phase: str) -> None:
    raise SystemExit('ROUND067_HOST_FIRST_ERROR ' + phase)


def check(compiler: str, source: str, label: str, mutation: bool) -> None:
    with tempfile.TemporaryDirectory(prefix='round067-native-dm-host-') as directory:
        source_path = Path(directory) / 'runtime.c'
        executable_path = Path(directory) / 'runtime'
        source_path.write_text(TEST.replace('/* SOURCE_INSERT */', source))
        compile_result = subprocess.run([
            compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
            '-Wconversion', '-Wshadow', '-Werror', '-fsanitize=address,undefined',
            '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
            str(source_path), '-o', str(executable_path)
        ], capture_output=True, text=True, timeout=60)
        if compile_result.returncode:
            fail(compiler + ':' + label + ':compile-not-semantic')
        env = os.environ.copy()
        env['ASAN_OPTIONS'] = 'halt_on_error=1:detect_leaks=1'
        run_result = subprocess.run([str(executable_path)], capture_output=True,
                                    text=True, timeout=30, env=env)
        if run_result.returncode < 0 or 'AddressSanitizer' in run_result.stderr or \
           'runtime error:' in run_result.stderr:
            fail(compiler + ':' + label + ':sanitizer-or-crash-not-semantic')
        if mutation and (run_result.returncode != 3 or
                         'semantic-failure case=' not in run_result.stderr):
            fail(compiler + ':' + label + ':mutant-survived-or-wrong-exit')
        if not mutation and run_result.returncode:
            fail(compiler + ':' + label + ':baseline-case')


def main() -> None:
    raw = FRAGMENT.read_text()
    if raw.count(BEGIN) != 1 or raw.count(END) != 1:
        fail('common-fragment-markers')
    common = raw.split(BEGIN, 1)[1].split(END, 1)[0]
    for compiler in ('gcc', 'clang'):
        check(compiler, common, 'baseline', False)
        for name, old, new in MUTANTS:
            if common.count(old) != 1:
                fail('mutation-anchor:' + name)
            check(compiler, common.replace(old, new, 1), name, True)
        print('ROUND067_' + compiler.upper() + '_GNU11_ASAN_UBSAN_PASS ' +
              'scenarios=10 semantic_changed_C_mutants=' + str(len(MUTANTS)) +
              ' native_dm_execution=SEPARATE_KUNIT')


if __name__ == '__main__':
    main()
