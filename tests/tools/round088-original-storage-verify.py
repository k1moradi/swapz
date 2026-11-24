#!/usr/bin/env python3
"""Actual isolated extent + allocator + storage adapter host qualification."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
SOURCE = KERNEL / "zswap-original-storage.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round088-original-storage.c"
PINS = {
    "src/kernel/authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/engine.c": "20e91329fc1a1b713cb6638236c001e7d5e3f815",
    "src/kernel/engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "src/kernel/gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "src/kernel/zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "src/kernel/zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "tests/runtime/native/repository-policy-test.py": "b200e0ca3e20d4c1f37e350ac9ef1c6426179817"
}
MUTANTS = [
    [
        "skip_flush",
        "flush_completed = !error;",
        "flush_completed = 0;"
    ],
    [
        "ignore_flush_error",
        "error = storage->ops.flush(storage->ops.context);",
        "error = storage->ops.flush(storage->ops.context);\n\t\tif (error) error = 0;"
    ],
    [
        "generation",
        "input->generation != authority->maps[spec->logical_page].generation + 1U ||",
        "input->generation < authority->maps[spec->logical_page].generation + 1U ||"
    ],
    [
        "rotation",
        "!authority->reuse_dead_segments &&",
        "authority->reuse_dead_segments <= 1U &&"
    ],
    [
        "decoder_retire",
        "storage->disk.records[index].state == SWAPZ_IMPORT_DISK_EMPTY)",
        "storage->disk.records[index].state != SWAPZ_IMPORT_DISK_OWNED)"
    ],
    [
        "skip_decoder_release",
        "storage->ops.decoder_put(storage->ops.context,\n\t\t\t\t\t\t storage->decoder[index]);",
        "(void)storage->decoder[index];"
    ],
    [
        "premature_publish",
        "error = storage->ops.flush(storage->ops.context);",
        "error = -EIO;"
    ],
    [
        "no_seal",
        "error = swapz_original_extent_seal(&storage->extent);",
        "error = 0;"
    ]
]
REPORT = {"compilers": {}, "first_error": None, "phase_a": "BLOCKED",
          "source_mapped_authenticated": 0, "import_active": 0,
          "physical_io": False, "native": "NOT_RUN"}

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def git(*args):
    result = subprocess.run(["git", "--no-replace-objects", *args], cwd=ROOT,
                            capture_output=True, timeout=60)
    require(result.returncode == 0, "git metadata: " + args[0])
    return result.stdout

def run(args, timeout=120):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout, env=os.environ | {
                              "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                              "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})

def compile_run(compiler, standard, source, binary, label, work):
    command = [compiler, "-std=" + standard, "-O1", "-g", "-Wall", "-Wextra",
               "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-fno-pie", "-no-pie", "-DSWAPZ_ORIGINAL_STORAGE_TEST",
               "-DSWAPZ_ORIGINAL_EXTENT_TEST", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
               "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST", "-I", str(KERNEL),
               str(source), str(FIXTURE), str(KERNEL / "zswap-original-extent.c"),
               str(KERNEL / "authority.c"), str(KERNEL / "codec.c"), "-o", str(binary)]
    compiled = run(command)
    if compiled.returncode:
        (work / "first-child-error.log").write_text(compiled.stderr)
        raise RuntimeError(f"{compiler}/{label}: compile failed (exit={compiled.returncode})")
    return run([str(binary)])

def main(work):
    sha = git("rev-parse", "HEAD").decode().strip()
    REPORT["tested_commit"] = sha
    before = os.environ.get("SWAPZ_PUSH_BEFORE_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", before) and before != "0" * 40,
            "missing/invalid push before SHA")
    require(sha == os.environ.get("GITHUB_SHA") and
            os.environ.get("GITHUB_EVENT_NAME") == "push" and
            os.environ.get("GITHUB_REF") == "refs/heads/main" and
            git("symbolic-ref", "--short", "HEAD").strip() == b"main", "exact main push")
    parents = [l[7:] for l in git("cat-file", "-p", "HEAD").decode().split("\n\n", 1)[0].splitlines()
               if l.startswith("parent ")]
    require(parents == [before] and git("rev-parse", "HEAD^").decode().strip() == before,
            "event before not exact sole parent")
    REPORT["parent"] = before
    require(not git("status", "--porcelain", "--untracked-files=all"), "dirty checkout")
    require(not git("diff", "--check", before, sha, "--"), "diff whitespace")
    for path, expected in PINS.items():
        require(git("hash-object", path).decode().strip() == expected, "blob mismatch " + path)
    REPORT["source_blobs"] = PINS | {
        str(p.relative_to(ROOT)): git("hash-object", str(p.relative_to(ROOT))).decode().strip()
        for p in (SOURCE, SOURCE.with_suffix(".h"), FIXTURE, Path(__file__).resolve())}
    prior = git("show", before + ":docs/testing_standards.md")
    current = (ROOT / "docs/testing_standards.md").read_bytes()
    require(current.startswith(prior) and len(current) > len(prior), "standards append")
    policy = run([sys.executable, "-B", "tests/runtime/native/repository-policy-test.py", "--enforce"])
    require(policy.returncode == 0, "canonical policy rejected exact push")
    original = SOURCE.read_text()
    require(len({m[0] for m in MUTANTS}) == len(MUTANTS), "mutation identities")
    for name, old, new in MUTANTS:
        require(original.count(old) == 1 and old != new, "mutation anchor " + name)
    REPORT["preflight"] = "PASS"
    with tempfile.TemporaryDirectory(prefix="swapz-storage-") as tmp:
        tmp = Path(tmp)
        binary = tmp / "test"
        mutant = tmp / SOURCE.name
        for compiler, standard in (("gcc", "c2x"), ("clang", "c23")):
            baseline = compile_run(compiler, standard, SOURCE, binary, "baseline", work)
            match = re.fullmatch(r"PASS ROUND088_AGENT5 checks=(\d+) storage_bytes=(\d+) map_bytes=(\d+)\n",
                                 baseline.stdout)
            if baseline.returncode or not match or baseline.stderr:
                (work / "first-child-error.log").write_text(baseline.stderr + baseline.stdout)
                raise RuntimeError(f"{compiler}/baseline: execution failed (exit={baseline.returncode})")
            counts = list(map(int, match.groups()))
            results = {"checks": counts[0], "storage_bytes": counts[1],
                       "map_bytes": counts[2], "mutants": []}
            REPORT["compilers"][compiler] = results
            for name, old, new in MUTANTS:
                mutant.write_text(original.replace(old, new, 1))
                result = compile_run(compiler, standard, mutant, binary, name, work)
                if (result.returncode != 77 or result.stdout or
                    not re.fullmatch(r"SEMANTIC_FAIL line=\d+ [^\n]+\n", result.stderr)):
                    (work / "first-child-error.log").write_text(result.stderr + result.stdout)
                    raise RuntimeError(f"{compiler}/{name}: not semantic kill (exit={result.returncode})")
                results["mutants"].append({"name": name, "assertion": result.stderr.strip()})
            print(f"PASS {compiler} checks={counts[0]} storage={counts[1]} map={counts[2]} semantic_mutants={len(MUTANTS)}", flush=True)
    require(not git("status", "--porcelain", "--untracked-files=all"), "test modified checkout")

if __name__ == "__main__":
    os.umask(0o077)
    work = Path(sys.argv[1])
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    status = 0
    try:
        main(work)
    except RuntimeError as error:
        REPORT["first_error"] = str(error)[:320]
        status = 1
    except (OSError, subprocess.SubprocessError, UnicodeError):
        REPORT["first_error"] = "required operation unavailable"
        status = 1
    finally:
        REPORT["conclusion"] = "FAIL" if status else "PASS"
        (work / "results.json").write_text(json.dumps(REPORT, indent=2) + "\n")
        if status:
            print("ROUND088_AGENT5_FIRST_ERROR " + REPORT["first_error"], file=sys.stderr)
            print("Inspect private first-child-error.log if present; repair exact source, no unchanged rerun.", file=sys.stderr)
    raise SystemExit(status)
