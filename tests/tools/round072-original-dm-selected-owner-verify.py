#!/usr/bin/env python3
"""Round072 strict source-linked DM table/target/BIO incarnation negatives.

Extracts the C predicate compiled by pinned-original Linux KUnit, using only
host scaffolding for Linux type layout. A green host test is NOT native DM
dispatch, source authentication, or actual upper BIO bio_endio evidence.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / 'tests/runtime/native/fixtures/round071-original-dm-upper-owner.cfrag'
COMMON_BEGIN = '/* ROUND071_OWNER_COMMON_BEGIN */'
COMMON_END = '/* ROUND071_OWNER_COMMON_END */'
SELECTED_BEGIN = '/* ROUND072_SELECTED_SOURCE_BEGIN */'
SELECTED_END = '/* ROUND072_SELECTED_SOURCE_END */'
MUTANTS = (
    ('selected-table-substitution',
     'selected_target->table == active_table',
     '(selected_target->table != NULL)'),
    ('stale-incarnation',
     'READ_ONCE(active_table->swapz_round065_incarnation)',
     'owner->generation'),
    ('requeued-accepted',
     'owner->phase == SWAPZ_ROUND071_OWNED',
     'owner->phase != SWAPZ_ROUND071_TERMINAL'),
    ('wrong-original',
     'swapz_round071_same_current_owner(owner, original_bio,',
     'swapz_round071_same_current_owner(owner, selected_target,'),
    ('missing-original',
     'owner && original_bio &&',
     'owner && !original_bio &&'),
    ('missing-active',
     'selected_target && active_table &&',
     'selected_target && !active_table &&'),
)
TEST = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

/* Host type adapter only; real original kernel types are used by KUnit. */
struct bio { unsigned int unused; };
struct dm_table { unsigned long long swapz_round065_incarnation; };
struct dm_target { struct dm_table *table; };
#define READ_ONCE(value) (value)
/* ORIGINAL_OWNER_SOURCE */
/* ORIGINAL_SELECTED_SOURCE */
static int detected(unsigned int step)
{
    fprintf(stderr, "ROUND072_SELECTED_DM_SEMANTIC_MUTANT_DETECTED step=%u\n", step);
    return 3;
}
#define EXPECT(condition) do { if (!(condition)) return detected(__LINE__); } while (0)
int main(void)
{
    struct bio original = {}, foreign = {};
    struct dm_table active = { .swapz_round065_incarnation = 7 };
    struct dm_table replacement = { .swapz_round065_incarnation = 8 };
    struct dm_target selected = { .table = &active };
    struct dm_target other = { .table = &replacement };
    struct swapz_round071_owner owner = {
        .original_bio = &original, .selected_target = &selected,
        .selected_table = &active, .generation = 7,
        .phase = SWAPZ_ROUND071_OWNED,
    };
    EXPECT(swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&foreign,&selected,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&other,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&replacement));
    selected.table = &replacement;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    selected.table = &active;
    active.swapz_round065_incarnation = 8;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    active.swapz_round065_incarnation = 0;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    active.swapz_round065_incarnation = 7;
    owner.phase = SWAPZ_ROUND071_REQUEUED;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    owner.phase = SWAPZ_ROUND071_TERMINAL;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    owner.phase = SWAPZ_ROUND071_OWNED;
    EXPECT(!swapz_round072_current_selected_dm_owner(NULL,&original,&selected,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,NULL,&selected,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,NULL,&active));
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,NULL));
    owner.selected_table = &replacement;
    EXPECT(!swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    owner.selected_table = &active;
    EXPECT(swapz_round072_current_selected_dm_owner(&owner,&original,&selected,&active));
    return 0;
}
'''


def first_error(label: str) -> None:
    raise SystemExit('ROUND072_AGENT2_HOST_FIRST_ERROR ' + label)


def compiled_executed(compiler: str, source: str, label: str, mutation: bool) -> None:
    with tempfile.TemporaryDirectory(prefix='round072-dm-selected-') as temp:
        source_path = Path(temp) / 'source.c'
        output_path = Path(temp) / 'source'
        source_path.write_text(source)
        build = subprocess.run([
            compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
            '-Wconversion', '-Wshadow', '-Werror', '-fsanitize=address,undefined',
            '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
            '-fno-pie', '-no-pie', str(source_path), '-o', str(output_path),
        ], capture_output=True, text=True, timeout=60)
        if build.returncode:
            first_error(compiler + ':' + label + ':compile:' +
                        build.stderr[:200].replace('\n', ' '))
        result = subprocess.run([str(output_path)], capture_output=True,
                                text=True, timeout=30, env={
                                    **os.environ,
                                    'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                    'UBSAN_OPTIONS': 'halt_on_error=1',
                                })
        if result.returncode < 0 or 'AddressSanitizer' in result.stderr or \
                'runtime error:' in result.stderr:
            first_error(compiler + ':' + label + ':sanitizer-or-crash')
        if mutation and (result.returncode != 3 or
                         'ROUND072_SELECTED_DM_SEMANTIC_MUTANT_DETECTED'
                         not in result.stderr):
            first_error(compiler + ':' + label + ':mutant-survived')
        if not mutation and (result.returncode != 0 or result.stderr):
            first_error(compiler + ':' + label + ':baseline')


def main() -> None:
    raw = FRAGMENT.read_text()
    for marker in (COMMON_BEGIN, COMMON_END, SELECTED_BEGIN, SELECTED_END):
        if raw.count(marker) != 1:
            first_error('fragment-marker:' + marker)
    common = raw.split(COMMON_BEGIN, 1)[1].split(COMMON_END, 1)[0]
    first = 'static bool swapz_round071_same_current_owner('
    after = 'static bool swapz_round071_claim('
    if common.count(first) != 1 or common.count(after) != 1:
        first_error('old-source-boundary')
    common = common.split(after, 1)[0]
    selected = raw.split(SELECTED_BEGIN, 1)[1].split(SELECTED_END, 1)[0]
    if selected.count('swapz_round072_current_selected_dm_owner(') != 1:
        first_error('new-source-boundary')
    template = TEST.replace('/* ORIGINAL_OWNER_SOURCE */', common)
    for compiler in ('gcc', 'clang'):
        if shutil.which(compiler) is None:
            first_error('missing-compiler:' + compiler)
        compiled_executed(compiler, template.replace(
            '/* ORIGINAL_SELECTED_SOURCE */', selected), 'baseline', False)
        for label, before, after in MUTANTS:
            if selected.count(before) != 1:
                first_error('mutant-anchor:' + label)
            altered = selected.replace(before, after, 1)
            compiled_executed(compiler, template.replace(
                '/* ORIGINAL_SELECTED_SOURCE */', altered), label, True)
        print('ROUND072_AGENT2_' + compiler.upper() +
              '_GNU11_ASAN_UBSAN_PASS compiled_executed_C_mutants=6'
              ' exact_selected_source=1 NO_AUTH')


if __name__ == '__main__':
    main()
