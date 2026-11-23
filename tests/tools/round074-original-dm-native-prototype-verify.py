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


def actual_source() -> tuple[str, str]:
    fragment = FRAGMENT.read_text()
    for marker in (OWNER_BEGIN, OWNER_END, TEST_BEGIN, TEST_END, NATIVE_CASE):
        if fragment.count(marker) != 1:
            fail('source-marker:' + marker)
    owner = fragment.split(OWNER_BEGIN, 1)[1].split(OWNER_END, 1)[0]
    native = fragment.split(TEST_BEGIN, 1)[1].split(TEST_END, 1)[0]
    native = TEST_BEGIN + native
    if len(re.findall(r'^static void swapz_round07[12]_native_.*_kunit\(', native,
                      flags=re.MULTILINE)) != 3:
        fail('native-case-count')
    selected = native.split(NATIVE_CASE, 1)[1]
    if re.search(r'\bcurrent\b', selected) or selected.count('active_table') < 10:
        fail('kernel-current-macro-collision-or-drift')
    return owner, native


def check(compiler: str, owner: str, native: str) -> None:
    with tempfile.TemporaryDirectory(prefix='round074-dm-native-prototype-') as temporary:
        source_file = Path(temporary) / 'actual.c'
        binary = Path(temporary) / 'actual'
        args = [compiler, '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra',
                '-Wconversion', '-Wshadow', '-Wstrict-prototypes', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                str(source_file), '-o', str(binary)]
        source_file.write_text(HEADER + owner + native + MAIN)
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
        # Actual old identifier collides with the pinned kernel current macro.
        before, selected = native.split(NATIVE_CASE, 1)
        old_decl = re.sub(r'\bactive_table\b', 'current', selected)
        if old_decl == selected or 'struct dm_table current =' not in old_decl:
            fail('negative-identifier-mutation-drift')
        source_file.write_text(HEADER + owner + before + NATIVE_CASE + old_decl + MAIN)
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
              ' old_kernel_current_macro_collision_rejected=1 source_AUTH=0')


def main() -> None:
    owner, native = actual_source()
    for compiler in ('gcc', 'clang'):
        if not shutil.which(compiler):
            fail('missing-compiler:' + compiler)
        check(compiler, owner, native)


if __name__ == '__main__':
    main()
