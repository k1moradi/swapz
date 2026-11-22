#!/usr/bin/env python3
"""Host strict changed-C predicate coverage; native original kernel is separate."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "runtime/native/fixtures/round069-original-zswap-stored-source.cfrag"
BEGIN, END = "/* ROUND069_COMMON_BEGIN */", "/* ROUND069_COMMON_END */"
MUTANTS = (
    ("empty-swap-slot", "expected_swp != 0", "expected_swp == 0"),
    ("wrong-swap-slot", "expected_swp == entry_swp", "expected_swp != entry_swp"),
    ("uninitialized-epoch", "expected_epoch != 0", "expected_epoch == 0"),
    ("old-slot-epoch", "expected_epoch == entry_epoch", "expected_epoch >= entry_epoch"),
    ("wrong-slot-epoch", "expected_epoch == entry_epoch", "expected_epoch != entry_epoch"),
    ("empty-compressed", "compressed_length != 0", "compressed_length == 0"),
    ("oversized-compressed", "compressed_length <= 3568U", "compressed_length > 3568U"),
    ("insufficient-capacity", "compressed_length <= output_capacity",
     "compressed_length > output_capacity"),
    ("no-original-pool", "selected_pool_idx != 0", "selected_pool_idx == 0"),
    ("wrong-original-pool", "selected_pool_idx == entry_pool_idx",
     "selected_pool_idx != entry_pool_idx"),
)
C_TEST = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
typedef uint64_t u64;
/* INSERT_SOURCE */
struct scenario {
    u64 slot, entry, epoch, entry_epoch;
    unsigned int length, capacity, selected_pool, entry_pool;
    bool expected;
};
static const struct scenario cases[] = {
    {1, 1, 17, 17, 20, 20, 253, 253, true},
    {0, 0, 17, 17, 20, 20, 253, 253, false},
    {1, 2, 17, 17, 20, 20, 253, 253, false},
    {1, 1, 0, 17, 20, 20, 253, 253, false},
    {1, 1, 17, 18, 20, 20, 253, 253, false},
    {1, 1, 18, 17, 20, 20, 253, 253, false},
    {1, 1, 17, 17, 0, 20, 253, 253, false},
    {1, 1, 17, 17, 3569, 4096, 253, 253, false},
    {1, 1, 17, 17, 20, 19, 253, 253, false},
    {1, 1, 17, 17, 20, 20, 0, 0, false},
    {1, 1, 17, 17, 20, 20, 253, 252, false},
    {1, 1, 17, 17, 3568, 3568, 253, 253, true},
    {UINT64_MAX, UINT64_MAX, UINT64_MAX, UINT64_MAX, 1, 1, 255, 255, true},
    {1, 1, 17, 17, 4096, 4096, 253, 253, false},
    {1, 1, 17, 17, 1, 1, 1, 1, true},
    {1, 1, 17, 17, 20, 4096, 253, 253, true},
};
int main(void)
{
    for (unsigned int index = 0; index < sizeof(cases)/sizeof(cases[0]); ++index) {
        const struct scenario *scenario = &cases[index];
        bool actual = swapz_round069_slot_identity_matches(scenario->slot,
            scenario->entry, scenario->epoch, scenario->entry_epoch,
            scenario->length, scenario->capacity, scenario->selected_pool,
            scenario->entry_pool);
        if (actual != scenario->expected) {
            fprintf(stderr, "semantic-failure case=%u\n", index);
            return 3;
        }
    }
    return 0;
}
'''

def fail(reason: str) -> None:
    raise SystemExit("ROUND069_HOST_FIRST_ERROR " + reason)

def check(compiler: str, snippet: str, label: str, mutation: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="round069-original-mm-") as directory:
        source = Path(directory) / "source.c"
        binary = Path(directory) / "source"
        source.write_text(C_TEST.replace("/* INSERT_SOURCE */", snippet))
        built = subprocess.run([
            compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
            "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(source),
            "-o", str(binary)
        ], capture_output=True, text=True, timeout=60)
        if built.returncode:
            fail(compiler + ":" + label + ":compile-not-semantic")
        environment = os.environ.copy()
        environment["ASAN_OPTIONS"] = "halt_on_error=1:detect_leaks=1"
        result = subprocess.run([str(binary)], capture_output=True, text=True,
                                timeout=30, env=environment)
        if result.returncode < 0 or "AddressSanitizer" in result.stderr or \
           "runtime error:" in result.stderr:
            fail(compiler + ":" + label + ":sanitizer-not-semantic")
        if mutation and (result.returncode != 3 or
                         "semantic-failure case=" not in result.stderr):
            fail(compiler + ":" + label + ":mutation-survived")
        if not mutation and result.returncode:
            fail(compiler + ":" + label + ":baseline-mismatch")

def main() -> None:
    fixture = FRAGMENT.read_text()
    if fixture.count(BEGIN) != 1 or fixture.count(END) != 1:
        fail("original-source-markers")
    common = fixture.split(BEGIN, 1)[1].split(END, 1)[0]
    for compiler in ("gcc", "clang"):
        check(compiler, common, "baseline", False)
        for name, old, new in MUTANTS:
            if common.count(old) != 1:
                fail("changed-source-mutation-anchor:" + name)
            check(compiler, common.replace(old, new, 1), name, True)
        print("ROUND069_" + compiler.upper() +
              "_SOURCE_ASAN_UBSAN_PASS scenarios=16 compiled_executed_C_semantic_mutants=10" +
              " native_original_execution=SEPARATE_KUNIT")

if __name__ == "__main__":
    main()
