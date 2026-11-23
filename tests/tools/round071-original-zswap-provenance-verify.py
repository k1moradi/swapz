#!/usr/bin/env python3
"""Execute source-extracted negative identity guards under GCC/Clang ASan+UBSan."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "runtime/native/fixtures/round071-original-zswap-provenance.cfrag"
BEGIN, END = "/* ROUND071_PROVENANCE_COMMON_BEGIN */", "/* ROUND071_PROVENANCE_COMMON_END */"

# Each mutation removes one actual C guard, not a Python reimplementation.
MUTATIONS = (
    ("zero-slot", "!witness->selected_slot", "false"),
    ("slot-incarnation", "witness->selected_slot != witness->entry_slot", "false"),
    ("zero-epoch", "!witness->selected_epoch", "false"),
    ("epoch-reissue", "witness->selected_epoch != witness->entry_epoch", "false"),
    ("zero-identity", "!witness->selected_identity", "false"),
    ("identity-reissue", "witness->selected_identity != witness->entry_identity", "false"),
    ("xarray-erase", "!witness->xarray_points_to_entry", "false"),
    ("zero-pool", "!witness->selected_pool_idx", "false"),
    ("pool-reuse", "witness->selected_pool_idx != witness->entry_pool_idx", "false"),
    ("pool-retirement", "!witness->pool_live", "false"),
    ("unknown-codec", "!witness->codec_known", "false"),
    ("zero-length", "!witness->compressed_length", "false"),
    ("oversized", "witness->compressed_length > 3568U", "false"),
)

C_HARNESS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;
/* INSERT_ORIGINAL_C */
#define OK {77,77,23,23,91,91,253,253,64,true,true,true}
struct scenario {
    struct swapz_round071_provenance_witness witness;
    int expected;
};
static const struct scenario cases[] = {
    {OK,0},
    {{0,0,23,23,91,91,253,253,64,true,true,true},-ESTALE},
    {{77,78,23,23,91,91,253,253,64,true,true,true},-ESTALE},
    {{77,77,0,0,91,91,253,253,64,true,true,true},-ESTALE},
    {{77,77,23,24,91,91,253,253,64,true,true,true},-ESTALE},
    {{77,77,23,23,0,0,253,253,64,true,true,true},-ESTALE},
    {{77,77,23,23,91,92,253,253,64,true,true,true},-ESTALE},
    {{77,77,23,23,91,91,253,253,64,false,true,true},-ESTALE},
    {{77,77,23,23,91,91,0,0,64,true,true,true},-EOPNOTSUPP},
    {{77,77,23,23,91,91,253,252,64,true,true,true},-EOPNOTSUPP},
    {{77,77,23,23,91,91,253,253,64,true,true,false},-EOPNOTSUPP},
    {{77,77,23,23,91,91,253,253,64,true,false,true},-EOPNOTSUPP},
    {{77,77,23,23,91,91,253,253,0,true,true,true},-EMSGSIZE},
    {{77,77,23,23,91,91,253,253,3569,true,true,true},-EMSGSIZE},
    {{77,77,23,23,91,91,1,1,3568,true,true,true},0},
    {{UINT64_MAX,UINT64_MAX,UINT64_MAX,UINT64_MAX,UINT64_MAX,
      UINT64_MAX,255,255,1,true,true,true},0},
};
int main(void)
{
    if (swapz_round071_provenance_identity_guard(NULL) != -ESTALE)
        return 3;
    for (unsigned int index = 0; index <
         sizeof(cases) / sizeof(cases[0]); ++index) {
        if (swapz_round071_provenance_identity_guard(&cases[index].witness)
            != cases[index].expected) {
            fprintf(stderr, "semantic-failure case=%u\n", index);
            return 3;
        }
    }
    return 0;
}
'''

def fail(reason: str) -> None:
    raise SystemExit("ROUND071_ORIGINAL_PROVENANCE_HOST_FIRST_ERROR " + reason)

def execute(compiler: str, code: str, description: str, mutant: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="round071-source-provenance-") as directory:
        source, binary = Path(directory) / "guard.c", Path(directory) / "guard"
        source.write_text(C_HARNESS.replace("/* INSERT_ORIGINAL_C */", code))
        try:
            compiled = subprocess.run([
                compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", str(source),
                "-o", str(binary),
            ], capture_output=True, text=True, timeout=60, check=False)
            if compiled.returncode:
                fail(f"{compiler}:{description}:compile-not-semantic")
            environment = dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1",
                               UBSAN_OPTIONS="halt_on_error=1")
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    timeout=30, check=False, env=environment)
        except (OSError, subprocess.TimeoutExpired):
            fail(f"{compiler}:{description}:tool-failure")
        if result.returncode < 0 or "AddressSanitizer" in result.stderr or \
           "runtime error:" in result.stderr:
            fail(f"{compiler}:{description}:sanitizer-not-semantic")
        if mutant and (result.returncode != 3 or
                       "semantic-failure case=" not in result.stderr):
            fail(f"{compiler}:{description}:mutant-survived")
        if not mutant and result.returncode:
            fail(f"{compiler}:{description}:baseline-failed")

def main() -> None:
    fixture = FRAGMENT.read_text()
    if fixture.count(BEGIN) != 1 or fixture.count(END) != 1:
        fail("source-extraction-markers")
    common = fixture.split(BEGIN, 1)[1].split(END, 1)[0]
    for compiler in ("gcc", "clang"):
        execute(compiler, common, "baseline", False)
        for description, old, new in MUTATIONS:
            if common.count(old) != 1:
                fail("source-mutation-anchor:" + description)
            execute(compiler, common.replace(old, new, 1), description, True)
        print(f"ROUND071_{compiler.upper()}_ORIGINAL_PROVENANCE_ASAN_UBSAN_PASS "
              f"scenarios=16 compiled_executed_C_semantic_mutants={len(MUTATIONS)} "
              "source_auth=0 native_original=SEPARATE_KUNIT")

if __name__ == "__main__":
    main()
