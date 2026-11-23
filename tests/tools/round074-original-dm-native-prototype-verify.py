#!/usr/bin/env python3
"""Compile and execute actual test-only native DM owner cases with the pinned
kernel current macro active; prove the previous declaration fails.

A host kernel-type adapter is NOT original Linux native KUnit, production DM
selection, source AUTH, durable I/O, or real upper bio_endio evidence.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FRAGMENT = ROOT / 'tests/runtime/native/fixtures/round071-original-dm-upper-owner.cfrag'
OWNER_BEGIN = '/* ROUND071_OWNER_COMMON_BEGIN */'
OWNER_END = '/* ROUND071_OWNER_COMMON_END */'
SELECTED_BEGIN = '/* ROUND072_SELECTED_SOURCE_BEGIN */'
SELECTED_END = '/* ROUND072_SELECTED_SOURCE_END */'
SELECTED_FUNCTION = 'static bool swapz_round072_current_selected_dm_owner('
TEST_BEGIN = 'static struct swapz_round071_owner swapz_round071_new_owner('
TEST_END = 'static struct kunit_case swapz_round071_native_upper_cases[] = {'
NATIVE_CASE = 'static void swapz_round072_native_current_table_negative_kunit(struct kunit *test)'

HEADER = r'''
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>

/* Kernel macro from pinned include/asm-generic/current.h. */
#define get_current() ((void *)0)
#define current get_current()
#define READ_ONCE(value) (value)
#define WRITE_ONCE(variable, value) ((variable) = (value))

/* Host type layout is only a compilation/execution adapter. */
struct bio { unsigned int unused; };
struct dm_table { unsigned long long swapz_round065_incarnation; };
struct dm_target { struct dm_table *table; };
struct kunit { unsigned int assertions, failures; };
#define CHECK(test, expression) do { \
    (test)->assertions++; \
    if (!(expression)) (test)->failures++; \
} while (0)
#define KUNIT_EXPECT_TRUE(test, expression) CHECK(test, expression)
#define KUNIT_EXPECT_FALSE(test, expression) CHECK(test, !(expression))
#define KUNIT_EXPECT_EQ(test, first, second) CHECK(test, (first) == (second))
#define KUNIT_ASSERT_TRUE(test, expression) do { \
    (test)->assertions++; \
    if (!(expression)) { (test)->failures++; return; } \
} while (0)
'''

MAIN = r'''
int main(void)
{
    struct kunit first = {}, second = {}, third = {};
    swapz_round071_native_upper_once_kunit(&first);
    swapz_round071_native_requeue_dtr_kunit(&second);
    swapz_round072_native_current_table_negative_kunit(&third);
    if (first.failures || second.failures || third.failures ||
        first.assertions < 8 || second.assertions < 8 ||
        third.assertions < 12) {
        fprintf(stderr,
                "ROUND074_NATIVE_BODY_FIRST_ERROR first=%u/%u second=%u/%u third=%u/%u\n",
                first.failures, first.assertions,
                second.failures, second.assertions,
                third.failures, third.assertions);
        return 3;
    }
    return 0;
}
'''


def fail(reason: str) -> None:
    raise SystemExit('ROUND074_DM_NATIVE_PROTOTYPE_FIRST_ERROR ' + reason)


def actual_source(fragment: str) -> tuple[str, str, str]:
    markers = (OWNER_BEGIN, OWNER_END, SELECTED_BEGIN, SELECTED_END,
               TEST_BEGIN, NATIVE_CASE, TEST_END)
    for marker in markers:
        if fragment.count(marker) != 1:
            fail('source-marker:' + marker)
    if tuple(fragment.index(marker) for marker in markers) != tuple(
            sorted(fragment.index(marker) for marker in markers)):
        fail('source-block-order')
    owner = fragment.split(OWNER_BEGIN, 1)[1].split(OWNER_END, 1)[0]
    selected_source = fragment.split(SELECTED_BEGIN, 1)[1].split(
        SELECTED_END, 1)[0]
    if selected_source.count(SELECTED_FUNCTION) != 1:
        fail('selected-function-identity')
    native = TEST_BEGIN + fragment.split(TEST_BEGIN, 1)[1].split(
        TEST_END, 1)[0]
    if len(re.findall(r'^static void swapz_round07[12]_native_.*_kunit\(', native,
                      flags=re.MULTILINE)) != 3:
        fail('native-case-count')
    selected_case = native.split(NATIVE_CASE, 1)[1]
    if re.search(r'\bcurrent\b', selected_case) or selected_case.count('active_table') < 10:
        fail('kernel-current-macro-collision-or-drift')
    return owner, selected_source, native


def check_source_boundaries(fragment: str) -> None:
    """Rejected source layouts must not silently turn into a modeled PASS."""
    selected_block = fragment.split(SELECTED_BEGIN, 1)[1].split(SELECTED_END, 1)[0]
    selected_block = SELECTED_BEGIN + selected_block + SELECTED_END
    malformed = (
        ('missing', fragment.replace(selected_block, '', 1)),
        ('misordered', fragment.replace(selected_block, '', 1).replace(
            TEST_END, selected_block + TEST_END, 1)),
        ('duplicated', fragment.replace(selected_block, selected_block * 2, 1)),
        ('wrong-function', fragment.replace(
            SELECTED_FUNCTION, 'static bool swapz_round072_wrong_dm_owner(', 1)),
    )
    for name, candidate in malformed:
        try:
            actual_source(candidate)
        except SystemExit as error:
            if not str(error).startswith('ROUND074_DM_NATIVE_PROTOTYPE_FIRST_ERROR '):
                raise
        else:
            fail('source-boundary-mutant-survived:' + name)


def check(compiler: str, owner: str, selected_source: str, native: str) -> None:
    with tempfile.TemporaryDirectory(prefix='round074-dm-native-prototype-') as temporary:
        source_file = Path(temporary) / 'actual.c'
        binary = Path(temporary) / 'actual'
        args = [compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                '-Wconversion', '-Wshadow', '-Wstrict-prototypes', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                str(source_file), '-o', str(binary)]
        source_file.write_text(HEADER + owner + selected_source + native + MAIN)
        baseline = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if baseline.returncode:
            fail(compiler + ':real-fixture-compile:' +
                 baseline.stderr[:300].replace('\n', ' '))
        executed = subprocess.run([str(binary)], capture_output=True, text=True,
                                  timeout=30, env={**os.environ,
                                                   'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                                   'UBSAN_OPTIONS': 'halt_on_error=1'})
        if executed.returncode or executed.stderr:
            fail(compiler + ':real-fixture-execute:' + executed.stderr[:240])
        # The old Round074 extractor must fail loudly when the selected block
        # is absent; -Werror=implicit-function-declaration remains mandatory.
        source_file.write_text(HEADER + owner + native + MAIN)
        missing = subprocess.run(args, capture_output=True, text=True, timeout=60)
        # GCC diagnoses an implicit declaration; Clang diagnoses an
        # undeclared function. Both must reject the missing definition.
        if (missing.returncode == 0 or
                'swapz_round072_current_selected_dm_owner' not in missing.stderr or
                not any(phrase in missing.stderr for phrase in
                        ('implicit declaration of function', 'undeclared function'))):
            fail(compiler + ':missing-selected-block-not-compile-rejected:' +
                 missing.stderr[:200].replace('\n', ' '))

        # A syntactically valid, wrong table selection must compile, execute,
        # and fail only the third native C test body, not count a build error.
        table_guard = 'selected_target->table == active_table'
        if selected_source.count(table_guard) != 1:
            fail('selected-table-predicate-anchor')
        altered = selected_source.replace(table_guard,
                                          'selected_target->table != NULL', 1)
        source_file.write_text(HEADER + owner + altered + native + MAIN)
        altered_build = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if altered_build.returncode:
            fail(compiler + ':altered-predicate-must-compile:' +
                 altered_build.stderr[:200].replace('\n', ' '))
        altered_result = subprocess.run(
            [str(binary)], capture_output=True, text=True, timeout=30,
            env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                 'UBSAN_OPTIONS': 'halt_on_error=1'})
        match = re.search(
            r'ROUND074_NATIVE_BODY_FIRST_ERROR first=(\d+)/(\d+) second=(\d+)/(\d+) third=(\d+)/(\d+)',
            altered_result.stderr)
        if (altered_result.returncode != 3 or not match or
                int(match.group(1)) or int(match.group(3)) or
                not int(match.group(5)) or
                'AddressSanitizer' in altered_result.stderr or
                'runtime error:' in altered_result.stderr):
            fail(compiler + ':altered-selected-table-not-runtime-rejected:' +
                 altered_result.stderr[:200].replace('\n', ' '))

        # Actual old identifier collides with the pinned kernel current macro.
        before, selected_case = native.split(NATIVE_CASE, 1)
        old_decl = re.sub(r'\bactive_table\b', 'current', selected_case)
        if old_decl == selected_case or 'struct dm_table current =' not in old_decl:
            fail('negative-identifier-mutation-drift')
        source_file.write_text(HEADER + owner + selected_source +
                               before + NATIVE_CASE + old_decl + MAIN)
        negative = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if negative.returncode == 0:
            fail(compiler + ':legacy-current-macro-clash-survived')
        if 'error:' not in negative.stderr or not any(
                phrase in negative.stderr for phrase in ('prototype', 'function',
                                                        'initializer', 'declarator',
                                                        'identifier')):
            fail(compiler + ':unexpected-negative-diagnostic:' +
                 negative.stderr[:200].replace('\n', ' '))
        print('ROUND074_DM_' + compiler.upper() +
              '_STRICT_PROTOTYPES_ASAN_UBSAN_PASS compiled_executed_native_C_case_bodies=3'
              ' missing_selected_compile_rejected=1 altered_selected_runtime_rejected=1'
              ' old_kernel_current_macro_collision_rejected=1 source_AUTH=0')


def main() -> None:
    fragment = FRAGMENT.read_text()
    owner, selected_source, native = actual_source(fragment)
    check_source_boundaries(fragment)
    for compiler in ('gcc', 'clang'):
        if not shutil.which(compiler):
            fail('missing-compiler:' + compiler)
        check(compiler, owner, selected_source, native)


if __name__ == '__main__':
    main()
