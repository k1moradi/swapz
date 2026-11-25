#!/usr/bin/env python3
"""Compile actual disabled extent + pinned ordinary codec; kill semantic mutants."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/zswap-original-extent.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round084-original-extent.c"
HISTORICAL_COMMIT = "1095acd05fff26c9da3941d62a12e179dcaeb808"
PINS = {
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "src/kernel/authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "src/kernel/engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "src/kernel/engine.c": "20e91329fc1a1b713cb6638236c001e7d5e3f815",
    "src/kernel/dm-target.c": "f1cab252cd990190646c82da81378d1563475826",
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "src/kernel/zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "src/kernel/zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "tests/runtime/native/fixtures/round084-original-extent.c": "473389e30b193626d8c33dba1cf1aad4c738fd8a",
    "tests/runtime/native/repository-policy-test.py": "b200e0ca3e20d4c1f37e350ac9ef1c6426179817",
}
# These are the actual current extent translation inputs that must retain
# their original exact identity. The current authority header is separately
# compiled by the fixture (including its 20-byte map assertion); unrelated
# authority/engine/DM bodies are historical context, not extent host inputs.
CURRENT_EXTENT_PINS = (
    "src/kernel/codec.h", "src/kernel/codec.c",
    "src/kernel/zswap-original-extent.h", "src/kernel/zswap-original-extent.c",
    "tests/runtime/native/fixtures/round084-original-extent.c",
)
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
PREFIX = "ROUND086_AGENT5_FIRST_ERROR"
SHA = re.compile(r"[0-9a-f]{40}\Z")
POLICY = ROOT / "tests/runtime/native/repository-policy-test.py"
REPORT = {"compilers": {}, "preflight": {}, "first_error": None,
          "source_mapped_authenticated": 0,
          "phase_a": "BLOCKED", "import_active": 0, "native": "NOT_RUN"}

def git_bytes(*args):
    try:
        result = subprocess.run(["git", "--no-replace-objects", *args], cwd=ROOT,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("Git metadata unavailable: " + args[0]) from None
    require(result.returncode == 0, "Git metadata command failed: " + args[0])
    return result.stdout


def git(*args):
    return git_bytes(*args).decode().strip()

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

def validate_push_base(environment, parent):
    """Require the real event's before SHA, never derive a replacement."""
    before = environment.get("SWAPZ_PUSH_BEFORE_SHA", "")
    require(SHA.fullmatch(before) is not None and before != "0" * 40,
            "push base SHA unavailable or invalid")
    require(before == parent, "push base SHA differs from exact first parent")
    require(git("rev-parse", "--verify", before + "^{commit}") == before,
            "push base commit unavailable")
    return before


def check_event_base_regressions(environment, checked_out, parent):
    # Exercise the same production preflight check against real checkout
    # metadata, with copied environments. No mutation of the live push env.
    ancestor = git("rev-parse", "--verify", parent + "^1^{commit}")
    cases = (
        ("missing", None, "push base SHA unavailable or invalid"),
        ("malformed", "not-a-sha", "push base SHA unavailable or invalid"),
        ("zero", "0" * 40, "push base SHA unavailable or invalid"),
        ("self", checked_out, "push base SHA differs from exact first parent"),
        ("older_ancestor", ancestor, "push base SHA differs from exact first parent"),
    )
    results = REPORT["preflight"]["event_base_regressions"] = {}
    for name, value, expected in cases:
        modified = environment.copy()
        if value is None:
            modified.pop("SWAPZ_PUSH_BEFORE_SHA", None)
        else:
            modified["SWAPZ_PUSH_BEFORE_SHA"] = value
        try:
            validate_push_base(modified, parent)
        except RuntimeError as error:
            require(str(error) == expected, "wrong preflight rejection: " + name)
        else:
            raise RuntimeError("preflight accepted invalid event base: " + name)
        results[name] = "REJECTED"
    require(validate_push_base(environment, parent) == parent,
            "valid event base rejected")
    results["exact_valid"] = "ACCEPTED"


def preflight():
    sha = git("rev-parse", "HEAD")
    REPORT["tested_commit"] = sha
    require(SHA.fullmatch(sha) is not None and sha == os.environ.get("GITHUB_SHA"),
            "exact GITHUB_SHA mismatch or missing")
    require(os.environ.get("GITHUB_EVENT_NAME") == "push" and
            os.environ.get("GITHUB_REF") == "refs/heads/main" and
            git("symbolic-ref", "--quiet", "--short", "HEAD") == "main",
            "not an exact main push checkout")
    require(git("rev-parse", "--is-shallow-repository") == "false",
            "full checkout history required")
    require(not git("status", "--porcelain", "--untracked-files=all"), "dirty checkout")
    raw = git("cat-file", "-p", "HEAD").split("\n\n", 1)[0]
    parents = [line[7:] for line in raw.splitlines() if line.startswith("parent ")]
    require(len(parents) == 1 and SHA.fullmatch(parents[0]) is not None and
            git("rev-parse", "--verify", "HEAD^1^{commit}") == parents[0],
            "single parent unavailable/mismatch")
    parent = parents[0]
    REPORT["parent"] = parent
    before = validate_push_base(os.environ, parent)
    REPORT["push_before_sha"] = before
    git("merge-base", "--is-ancestor", before, sha)
    require(not git("diff", "--check", before, sha, "--"), "diff whitespace")
    # Frozen historical provenance and current compiled inputs are distinct.
    # Never replace a historical hash with a moving checkout identity.
    for path, expected in PINS.items():
        require(git("rev-parse", HISTORICAL_COMMIT + ":" + path) == expected,
                "historical pinned blob mismatch " + path)
        require(git("cat-file", "-t", expected) == "blob",
                "historical pinned object unavailable " + path)
    current = {path: git("hash-object", path) for path in PINS}
    for path in CURRENT_EXTENT_PINS:
        require(current[path] == PINS[path], "current extent input mismatch " + path)
    REPORT["historical_commit"] = HISTORICAL_COMMIT
    REPORT["historical_source_blobs"] = PINS
    REPORT["source_blobs"] = current | {
        str(Path(__file__).resolve().relative_to(ROOT)):
            git("hash-object", str(Path(__file__).resolve().relative_to(ROOT)))}
    REPORT["current_authority_scope"] = "header compiled; authority C not linked"
    before_standard = git_bytes("show", before + ":docs/testing_standards.md")
    after = (ROOT / "docs/testing_standards.md").read_bytes()
    require(after.startswith(before_standard) and len(after) > len(before_standard),
            "standards not append-only")
    check_event_base_regressions(os.environ, sha, parent)
    # Use the unchanged canonical policy with the untouched real event env.
    policy = subprocess.run([sys.executable, "-B", str(POLICY), "--enforce"],
                            cwd=ROOT, capture_output=True, text=True,
                            timeout=90, check=False)
    if policy.returncode:
        first = next((line for line in policy.stderr.splitlines()
                      if line.startswith("SOURCE_CONTRACT_MISMATCH:") and
                      "first_error=" in line), "canonical repository policy failed")
        raise RuntimeError(first[:320])
    REPORT["preflight"]["canonical_policy"] = "PASS"
    for tool in ("gcc", "clang"):
        require(shutil.which(tool) is not None, "missing compiler: " + tool)


def main():
    preflight()
    original = SOURCE.read_text()
    require(len(MUTANTS) == 24 and len({m[0] for m in MUTANTS}) == len(MUTANTS),
            "mutation identities")
    for name, old, new in MUTANTS:
        require(original.count(old) == 1 and old != new, "mutation anchor " + name)
    # Preflight rejects missing and duplicate anchors before any compilation.
    first = MUTANTS[0][1]
    require(original.replace(first, "").count(first) == 0, "missing anchor negative")
    require((original + first).count(first) == 2, "duplicate anchor negative")
    REPORT["preflight"]["mutation_anchors"] = len(MUTANTS)
    REPORT["preflight"]["status"] = "PASS"
    print("PASS ROUND086_AGENT5 preflight event_base=5 rejected + 1 accepted "
          "canonical_policy=PASS mutation_anchors=24", flush=True)
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
    os.umask(0o077)
    exit_code = 0
    try:
        main()
    except RuntimeError as error:
        REPORT["first_error"] = str(error)[:500]
        exit_code = 1
    except (OSError, subprocess.SubprocessError, UnicodeError):
        # No child command, runner pathname, or raw stderr in preflight output.
        REPORT["first_error"] = "required preflight/test operation unavailable"
        exit_code = 1
    finally:
        if exit_code:
            if REPORT["preflight"].get("status") != "PASS":
                REPORT["preflight"]["status"] = "FAIL"
            print(f"{PREFIX} {REPORT['first_error']}", file=sys.stderr)
            print("Corrective action: inspect exact push metadata and source pins "
                  "or the named failing host case; publish a focused source fix "
                  "on main, never bypass policy or rerun unchanged failure.",
                  file=sys.stderr)
        REPORT["conclusion"] = "FAIL" if exit_code else "PASS"
        Path(sys.argv[1]).write_text(json.dumps(REPORT, indent=2) + "\n")
    raise SystemExit(exit_code)
