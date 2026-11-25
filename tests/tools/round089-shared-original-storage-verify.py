#!/usr/bin/env python3
"""Round091 never-issued tail cancellation and kernel namespace regression."""
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round089-shared-original-storage.c"
PINS = {
    "src/kernel/authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "src/kernel/authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "src/kernel/engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "src/kernel/zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "src/kernel/zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "tests/runtime/native/fixtures/round089-shared-original-storage.c": "95cee696fe99b3438f387ff1bf45cb4634f70fab",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "src/kernel/gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "src/kernel/zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "src/kernel/zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "tests/runtime/native/repository-policy-test.py": "b200e0ca3e20d4c1f37e350ac9ef1c6426179817"
}
MUTANTS = [
    [
        "missing_marker",
        "authority.c",
        "new_map.state |= SWAPZ_MAP_ORIGINAL;",
        "new_map.state &= (swapz_u8)~SWAPZ_MAP_ORIGINAL;"
    ],
    [
        "retired_segment_pin",
        "authority.c",
        "if (record->pins &&\n\t\t    record->map.start_block / SWAPZ_SEGMENT_BLOCKS == segment)",
        "if (record->pins > SWAPZ_SHARED_ORIGINAL_CAPACITY &&\n\t\t    record->map.start_block / SWAPZ_SEGMENT_BLOCKS == segment)"
    ],
    [
        "generation",
        "authority.c",
        "if (generation != a->maps[spec->logical_page].generation + 1U)",
        "if (generation > a->maps[spec->logical_page].generation + 1U)"
    ],
    [
        "early_decoder_release",
        "authority.c",
        "if (!record->is_current && !record->pins && record->decoder)",
        "if (!record->is_current && record->decoder)"
    ],
    [
        "flush",
        "zswap-original-storage.c",
        "flushed = !error;",
        "flushed = 0;"
    ],
    [
        "ordinary_read",
        "engine.c",
        "if (observed.state & SWAPZ_MAP_ORIGINAL)\n\t\treturn -EOPNOTSUPP;",
        "if (observed.state & SWAPZ_MAP_ORIGINAL)\n\t\treturn -ESTALE;"
    ],
    ["credit_headroom","authority.c","if (!swapz_open_segment_fits(a, 1U))","if (0)"],
    ["credit_identity","zswap-original-storage.c","credit == storage->transaction.sequence &&\n\t       credit == a->active_sequence &&","storage->transaction.sequence == a->active_sequence &&"],
    ["credit_consume","zswap-original-storage.c","storage->pending_decoder = NULL;\n\terror = storage->ops.write","/* mutant: keep consumed lease */\n\terror = storage->ops.write"],
    ["cancel_abandon","zswap-original-storage.c","error = swapz_shared_original_cancel_unissued(storage->authority, &storage->transaction);","error = swapz_abort(storage->authority, &storage->transaction);"],
    ["cancel_noop","zswap-original-storage.c","error = swapz_shared_original_cancel_unissued(storage->authority, &storage->transaction);","error = 0;"],
    ["reservation_free","authority.c","a->live_records[a->next_block] || a->extent_classes[a->next_block]","a->live_records[a->next_block]"],
    ["cancel_tail","authority.c","a->next_block == start + 1U &&","1 &&"],
    ["cancel_cursor","authority.c","a->next_block = tx->start_block;","a->next_block = tx->start_block + 1U;"],
    ["cancel_throttle","authority.c","a->next_sequence == a->shared_cancelled_sequence + 1U","a->next_sequence == a->shared_cancelled_sequence"],
    ["cancel_sequence_budget","authority.c","remaining > 255U - sequence_delta","remaining > ~(swapz_u32)0 - sequence_delta"],
    ["issue_fence","authority.c","return -ESTALE;\n\ta->shared_unissued_sequence = 0;\n\treturn 0;","return -ESTALE;\n\treturn 0;"],
    ["mapped_count","authority.c","a->segment_mapped_pages[new_segment]++;","a->segment_mapped_pages[new_segment] += 0U;"],
    ["typed_sequence","authority.c","a->extent_sequence_delta[tx->start_block] = sequence_delta;","a->extent_sequence_delta[tx->start_block] = 0;"]
]
REPORT = {"round": "091", "prior_round090_commit": "a82a9263783f66222c84c349cc46e3b4262ef125", "prior_round089_commit": "8089093b8ac23d5430c4d8d6071a34d8692ee193",
          "compilers": {}, "first_error": None, "phase_a": "BLOCKED",
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

def compile_run(compiler, standard, sources, binary, label, work):
    command = [compiler, "-std=" + standard, "-O1", "-g", "-Wall", "-Wextra",
               "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-fno-pie", "-no-pie", "-Dcurrent=get_current()", "-DSWAPZ_ORIGINAL_STORAGE_TEST",
               "-DSWAPZ_ORIGINAL_EXTENT_TEST", "-DSWAPZ_ROUND066_IMPORT_DISK_TEST",
               "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST", "-DSWAPZ_SHARED_ORIGINAL_TEST",
               "-I", str(KERNEL), *(str(s) for s in sources), str(FIXTURE),
               str(KERNEL / "zswap-original-extent.c"), str(KERNEL / "codec.c"), "-o", str(binary)]
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
    if policy.returncode:
        (work / "first-child-error.log").write_text(policy.stderr + policy.stdout)
        raise RuntimeError("canonical policy rejected exact push")
    sources = [KERNEL / name for name in ("authority.c", "engine.c", SOURCE.name)]
    originals = {p.name: p.read_text() for p in sources}
    require(len({m[0] for m in MUTANTS}) == len(MUTANTS), "mutation identities")
    for name, filename, old, new in MUTANTS:
        require(originals[filename].count(old) == 1 and old != new, "mutation anchor " + name)
    REPORT["preflight"] = "PASS"
    with tempfile.TemporaryDirectory(prefix="swapz-storage-") as tmp:
        tmp = Path(tmp)
        binary = tmp / "test"
        for compiler, standard in (("gcc", "c2x"), ("clang", "c23")):
            baseline = compile_run(compiler, standard, sources, binary, "baseline", work)
            match = re.fullmatch(r"PASS ROUND091_AGENT5 checks=(\d+) storage_bytes=(\d+) map_bytes=(\d+) sidecar_bytes=(\d+)\n",
                                 baseline.stdout)
            if baseline.returncode or not match or baseline.stderr:
                (work / "first-child-error.log").write_text(baseline.stderr + baseline.stdout)
                raise RuntimeError(f"{compiler}/baseline: execution failed (exit={baseline.returncode})")
            counts = list(map(int, match.groups()))
            results = {"checks": counts[0], "storage_bytes": counts[1],
                       "map_bytes": counts[2], "sidecar_bytes": counts[3], "mutants": []}
            REPORT["compilers"][compiler] = results
            for name, filename, old, new in MUTANTS:
                mutant = tmp / filename
                mutant.write_text(originals[filename].replace(old, new, 1))
                mutated_sources = [mutant if p.name == filename else p for p in sources]
                result = compile_run(compiler, standard, mutated_sources, binary, name, work)
                if (result.returncode != 77 or result.stdout or
                    not re.fullmatch(r"SEMANTIC_FAIL line=\d+ [^\n]+\n", result.stderr)):
                    (work / "first-child-error.log").write_text(result.stderr + result.stdout)
                    raise RuntimeError(f"{compiler}/{name}: not semantic kill (exit={result.returncode})")
                results["mutants"].append({"name": name, "assertion": result.stderr.strip()})
            print(f"PASS {compiler} checks={counts[0]} storage={counts[1]} map={counts[2]} sidecar={counts[3]} semantic_mutants={len(MUTANTS)}", flush=True)
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
            print("ROUND091_AGENT5_FIRST_ERROR " + REPORT["first_error"], file=sys.stderr)
            print("Inspect private first-child-error.log if present; repair exact source, no unchanged rerun.", file=sys.stderr)
    raise SystemExit(status)
