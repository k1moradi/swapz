#!/usr/bin/env python3
"""Strict host checks of the actual C original-source refusal predicate.

Native original get_swap_device()/folio_matches_swap_entry() are separate KUnit
calls; host guard flags never serve as source authentication.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FRAGMENT = ROOT / "runtime/native/fixtures/round072-original-swapcache-provenance.cfrag"
BEGIN = "/* ROUND072_SOURCE_BOUNDARY_COMMON_BEGIN */"
END = "/* ROUND072_SOURCE_BOUNDARY_COMMON_END */"

MUTATIONS = (
    ("missing-slot", "!lease->selected_swap_entry"),
    ("wrong-slot", "lease->selected_swap_entry != lease->observed_swap_entry"),
    ("missing-epoch", "!lease->selected_epoch"),
    ("reissued-epoch", "lease->selected_epoch != lease->observed_epoch"),
    ("not-original-store", "!lease->original_store_published"),
    ("erased-xarray", "!lease->current_stored_xarray_entry"),
    ("unlocked-folio", "!lease->original_folio_locked"),
    ("ordinary-folio", "!lease->original_folio_swapcache"),
    ("no-original-device-ref", "!lease->original_swap_device_ref"),
    ("post-erase-window", "!lease->pre_erase_copy_window"),
    ("retired-pool", "!lease->original_pool_ref"),
    ("unknown-original-codec", "!lease->original_codec_identified"),
    ("borrowed-bytes", "!lease->immutable_owned_bytes"),
    ("no-selected-dm-owner", "!lease->selected_dm_source_ref"),
)

C_TEST = r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef uint64_t u64;
/* INSERT_ORIGINAL_C */
static struct swapz_round072_source_lease valid_inputs(void)
{
    return (struct swapz_round072_source_lease) {
        .selected_swap_entry=1, .observed_swap_entry=1,
        .selected_epoch=17, .observed_epoch=17,
        .original_store_published=true, .current_stored_xarray_entry=true,
        .original_folio_locked=true, .original_folio_swapcache=true,
        .original_swap_device_ref=true, .pre_erase_copy_window=true,
        .original_pool_ref=true, .original_codec_identified=true,
        .immutable_owned_bytes=true, .selected_dm_source_ref=true
    };
}
#define CHECK_STATUS(CASE, EXPECTED) do { \
    int actual = swapz_round072_source_lease_refuse(&lease); \
    if (actual != (EXPECTED)) { \
        fprintf(stderr, "semantic-failure case=%s actual=%d expected=%d\n", \
                (CASE), actual, (EXPECTED)); \
        return 3; \
    } \
} while (0)
int main(void)
{
    struct swapz_round072_source_lease lease=valid_inputs();
    if (swapz_round072_source_lease_refuse(NULL) != -ESTALE) {
        fputs("semantic-failure case=null\n", stderr);
        return 3;
    }
    CHECK_STATUS("all-asserted-still-noauth", -EACCES);
    lease=valid_inputs(); lease.selected_swap_entry=0; lease.observed_swap_entry=0;
    CHECK_STATUS("missing-slot", -ESTALE);
    lease=valid_inputs(); lease.observed_swap_entry=2;
    CHECK_STATUS("wrong-slot", -ESTALE);
    lease=valid_inputs(); lease.selected_epoch=0; lease.observed_epoch=0;
    CHECK_STATUS("missing-epoch", -ESTALE);
    lease=valid_inputs(); lease.observed_epoch=18;
    CHECK_STATUS("reissued-epoch", -ESTALE);
    lease=valid_inputs(); lease.original_store_published=false;
    CHECK_STATUS("not-original-store", -ENODATA);
    lease=valid_inputs(); lease.current_stored_xarray_entry=false;
    CHECK_STATUS("erased-xarray", -ESTALE);
    lease=valid_inputs(); lease.original_folio_locked=false;
    CHECK_STATUS("unlocked-folio", -EPERM);
    lease=valid_inputs(); lease.original_folio_swapcache=false;
    CHECK_STATUS("ordinary-folio", -ENODEV);
    lease=valid_inputs(); lease.original_swap_device_ref=false;
    CHECK_STATUS("no-original-device-ref", -ENODEV);
    lease=valid_inputs(); lease.pre_erase_copy_window=false;
    CHECK_STATUS("post-erase-window", -ESTALE);
    lease=valid_inputs(); lease.original_pool_ref=false;
    CHECK_STATUS("retired-pool", -EOPNOTSUPP);
    lease=valid_inputs(); lease.original_codec_identified=false;
    CHECK_STATUS("unknown-original-codec", -EOPNOTSUPP);
    lease=valid_inputs(); lease.immutable_owned_bytes=false;
    CHECK_STATUS("borrowed-bytes", -ENOBUFS);
    lease=valid_inputs(); lease.selected_dm_source_ref=false;
    CHECK_STATUS("no-selected-dm-owner", -ENOTCONN);
    return 0;
}
'''

def fail(message: str) -> None:
    raise SystemExit("ROUND072_ORIGINAL_SWAPCACHE_HOST_FIRST_ERROR " + message)

def run(compiler: str, source_code: str, label: str, mutant: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="round072-original-source-") as directory:
        c_path = Path(directory) / "source.c"
        binary_path = Path(directory) / "source"
        c_path.write_text(C_TEST.replace("/* INSERT_ORIGINAL_C */", source_code))
        try:
            compiled = subprocess.run([
                compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                "-Wconversion", "-Wshadow", "-Werror", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                str(c_path), "-o", str(binary_path),
            ], capture_output=True, text=True, timeout=60, check=False)
            if compiled.returncode:
                fail(f"{compiler}:{label}:compile-not-semantic:"
                     + compiled.stderr.splitlines()[0][:160])
            environment = dict(os.environ, ASAN_OPTIONS="halt_on_error=1:detect_leaks=1",
                               UBSAN_OPTIONS="halt_on_error=1")
            executed = subprocess.run([str(binary_path)], capture_output=True,
                                      text=True, timeout=30, check=False,
                                      env=environment)
        except (OSError, subprocess.TimeoutExpired):
            fail(f"{compiler}:{label}:tool-failure")
        if executed.returncode < 0 or "AddressSanitizer" in executed.stderr or \
           "runtime error:" in executed.stderr:
            fail(f"{compiler}:{label}:sanitizer-not-semantic")
        if mutant:
            if executed.returncode != 3 or \
               "semantic-failure case=" not in executed.stderr:
                fail(f"{compiler}:{label}:mutant-survived")
        elif executed.returncode:
            fail(f"{compiler}:{label}:baseline-unexpected-failure")

def main() -> None:
    fixture = FRAGMENT.read_text()
    if fixture.count(BEGIN) != 1 or fixture.count(END) != 1:
        fail("pinned-source-extraction-markers")
    common = fixture.split(BEGIN, 1)[1].split(END, 1)[0]
    for compiler in ("gcc", "clang"):
        run(compiler, common, "baseline", False)
        for label, expression in MUTATIONS:
            if common.count(expression) != 1:
                fail("guard-mutation-anchor:" + label)
            run(compiler, common.replace(expression, "false", 1), label, True)
        print(f"ROUND072_{compiler.upper()}_ORIGINAL_SWAPCACHE_ASAN_UBSAN_PASS "
              f"scenarios=16 compiled_executed_semantic_mutants={len(MUTATIONS)} "
              "source_auth=0 true_swapcache=NOT_AUTHENTICATED")


if __name__ == "__main__":
    main()
