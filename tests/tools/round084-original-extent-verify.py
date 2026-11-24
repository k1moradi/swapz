#!/usr/bin/env python3
"""Compile actual disabled extent + pinned ordinary codec; kill semantic mutants."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/zswap-original-extent.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round084-original-extent.c"
PINS = {
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "src/kernel/authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "src/kernel/engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "src/kernel/engine.c": "20e91329fc1a1b713cb6638236c001e7d5e3f815",
    "src/kernel/dm-target.c": "f1cab252cd990190646c82da81378d1563475826",
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5"
}
MUTANTS = [
    [
        "capacity_init",
        "capacity > SWAPZ_MAX_RECORDS",
        "capacity > SWAPZ_MAX_RECORDS + 1U"
    ],
    [
        "ceiling_init",
        "ceiling != SWAPZ_ORIGINAL_EXTENT_EXPERIMENTAL)",
        "ceiling > SWAPZ_BLOCK_BYTES)"
    ],
    [
        "dedicated_class",
        "return bytes == SWAPZ_BLOCK_BYTES && capacity == 1U;",
        "return capacity == 1U;"
    ],
    [
        "dedicated_count",
        "return bytes == SWAPZ_BLOCK_BYTES && capacity == 1U;",
        "return bytes == SWAPZ_BLOCK_BYTES;"
    ],
    [
        "record_span",
        "record_bytes != capacity * sizeof(*records) ||",
        "record_bytes + 1U < capacity * sizeof(*records) ||"
    ],
    [
        "representation",
        "representation == SWAPZ_ORIGINAL_EXTENT_REPRESENTATION &&",
        "(representation == SWAPZ_ORIGINAL_EXTENT_REPRESENTATION || !representation) &&"
    ],
    [
        "codec",
        "codec == SWAPZ_ORIGINAL_EXTENT_LZO1X)",
        "codec == SWAPZ_ORIGINAL_EXTENT_LZO1X || codec == 3U)"
    ],
    [
        "version",
        "version == SWAPZ_ORIGINAL_EXTENT_VERSION;",
        "version >= SWAPZ_ORIGINAL_EXTENT_VERSION;"
    ],
    [
        "dictionary",
        "input->dictionary_id ||",
        "input->dictionary_id > 1U ||"
    ],
    [
        "decoded_length",
        "input->decoded_length != SWAPZ_BLOCK_BYTES",
        "input->decoded_length > SWAPZ_BLOCK_BYTES"
    ],
    [
        "generation",
        "!input->generation)",
        "input->generation == 99U)"
    ],
    [
        "ceiling",
        "input->length > extent->ceiling ||",
        "input->length > SWAPZ_ORIGINAL_EXTENT_EXPERIMENTAL ||"
    ],
    [
        "source_span",
        "input->bytes_available != input->length",
        "input->bytes_available > input->length"
    ],
    [
        "crc",
        "if (crc != input->crc32c)",
        "if (crc != input->crc32c && input->length == 99U)"
    ],
    [
        "duplicate",
        "extent->records[index].logical_page == input->logical_page",
        "extent->records[index].logical_page == input->logical_page + 1U"
    ],
    [
        "capacity_append",
        "extent->count >= extent->capacity ||",
        "extent->count > extent->capacity ||"
    ],
    [
        "byte_capacity",
        "input->length > extent->unused_bytes)",
        "input->length > extent->unused_bytes + 1U)"
    ],
    [
        "read_blocks",
        "(swapz_u8)(last - first + 1U)",
        "(swapz_u8)(last - first + 2U)"
    ],
    [
        "packed_padding",
        "memset(extent->image, 0, remaining);",
        "memset(extent->image, 0xa5, remaining);"
    ],
    [
        "dedicated_padding",
        "memset(extent->image + extent->occupied_bytes, 0, remaining);",
        "memset(extent->image + extent->occupied_bytes, 0xa5, remaining);"
    ],
    [
        "seal_crc",
        "record->crc32c)\n\t\t\treturn -EBADMSG;",
        "record->crc32c && record->length == 99U)\n\t\t\treturn -EBADMSG;"
    ],
    [
        "seal_offset",
        "record->offset != offset ||",
        "record->offset > offset + 1U ||"
    ],
    [
        "seal_cursor",
        "if (remaining != extent->unused_bytes)",
        "if (remaining > extent->unused_bytes)"
    ],
    [
        "seal_duplicate",
        "record->logical_page)\n\t\t\t\treturn -EUCLEAN;",
        "record->logical_page + 1U)\n\t\t\t\treturn -EUCLEAN;"
    ]
]
PREFIX = "ROUND084_AGENT5_FIRST_ERROR"
REPORT = {"compilers": {}, "first_error": None, "source_mapped_authenticated": 0,
          "phase_a": "BLOCKED", "import_active": 0, "native": "NOT_RUN"}

def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT,
                                   stderr=subprocess.PIPE, timeout=20).decode().strip()

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def run(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=60, check=False, env=os.environ | {
                              "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                              "UBSAN_OPTIONS": "halt_on_error=1"})

def compile_and_run(compiler, standard, source, binary, name):
    result = run([compiler, "-std=" + standard, "-O1", "-g", "-Wall", "-Wextra",
                  "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                  "-fno-pie", "-no-pie", "-DSWAPZ_ORIGINAL_EXTENT_TEST",
                  "-I", str(ROOT / "src/kernel"), str(source), str(FIXTURE),
                  str(ROOT / "src/kernel/codec.c"), "-o", str(binary)])
    if result.returncode:
        diagnostic = next((line for line in result.stderr.splitlines()
                           if "error:" in line), "compiler returned nonzero")
        raise RuntimeError(f"{compiler}/{name}: compile: {diagnostic[:240]}")
    return run([str(binary)])

def main():
    sha = git("rev-parse", "HEAD")
    REPORT["tested_commit"] = sha
    require(sha == os.environ.get("GITHUB_SHA", sha), "exact SHA")
    require(not git("status", "--porcelain", "--untracked-files=all"), "dirty checkout")
    raw = git("cat-file", "-p", "HEAD").split("\n\n", 1)[0]
    parents = [line[7:] for line in raw.splitlines() if line.startswith("parent ")]
    require(len(parents) == 1 and git("rev-parse", "HEAD^") == parents[0],
            "single parent unavailable/mismatch")
    REPORT["parent"] = parents[0]
    require(not git("diff", "--check", "HEAD^", "HEAD", "--"), "diff whitespace")
    for path, expected in PINS.items():
        require(git("hash-object", path) == expected, "pinned blob mismatch " + path)
    REPORT["source_blobs"] = PINS | {
        str(p.relative_to(ROOT)): git("hash-object", str(p.relative_to(ROOT)))
        for p in (SOURCE, SOURCE.with_suffix(".h"), FIXTURE, Path(__file__).resolve())}
    before = subprocess.check_output(["git", "show", "HEAD^:docs/testing_standards.md"], cwd=ROOT)
    after = (ROOT / "docs/testing_standards.md").read_bytes()
    require(after.startswith(before) and len(after) > len(before), "standards not append-only")
    original = SOURCE.read_text()
    require(len(MUTANTS) >= 16 and len({m[0] for m in MUTANTS}) == len(MUTANTS),
            "mutation identities")
    for name, old, new in MUTANTS:
        require(original.count(old) == 1 and old != new, "mutation anchor " + name)
    # Preflight rejects missing and duplicate anchors before any compilation.
    first = MUTANTS[0][1]
    require(original.replace(first, "").count(first) == 0, "missing anchor negative")
    require((original + first).count(first) == 2, "duplicate anchor negative")
    with tempfile.TemporaryDirectory(prefix="swapz-original-extent-") as work:
        work = Path(work)
        mutant = work / SOURCE.name
        binary = work / "test"
        for compiler, standard in (("gcc", "c2x"), ("clang", "c23")):
            result = compile_and_run(compiler, standard, SOURCE, binary, "baseline")
            match = re.fullmatch(r"PASS ROUND084_AGENT5 checks=(\d+) record_bytes=(\d+) builder_bytes=(\d+) map_bytes=(\d+)\n",
                                 result.stdout)
            require(result.returncode == 0 and match is not None and not result.stderr,
                    f"{compiler}/baseline: {result.stderr[:240]}")
            counts = list(map(int, match.groups()))
            report = {"baseline_checks": counts[0], "record_bytes": counts[1],
                      "builder_bytes": counts[2], "ordinary_map_bytes": counts[3],
                      "compiled_executed_killed": []}
            REPORT["compilers"][compiler] = report
            for name, old, new in MUTANTS:
                mutant.write_text(original.replace(old, new, 1))
                result = compile_and_run(compiler, standard, mutant, binary, name)
                require(result.returncode == 77 and not result.stdout and
                        re.fullmatch(r"SEMANTIC_FAIL line=\d+ [^\n]+\n", result.stderr) is not None,
                        f"{compiler}/{name}: not a semantic kill (exit={result.returncode}) {result.stderr[:200]}")
                report["compiled_executed_killed"].append(
                    {"name": name, "assertion": result.stderr.strip()})
            print(f"PASS {compiler} checks={counts[0]} record={counts[1]} builder={counts[2]} map={counts[3]} semantic_mutants={len(MUTANTS)}", flush=True)
    require(not git("status", "--porcelain", "--untracked-files=all"), "test modified checkout")

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        REPORT["first_error"] = str(error)[:500]
        print(f"{PREFIX} {REPORT['first_error']}", file=sys.stderr)
        sys.exit_code = 1
    else:
        sys.exit_code = 0
    finally:
        Path(sys.argv[1]).write_text(json.dumps(REPORT, indent=2) + "\n")
    raise SystemExit(sys.exit_code)
