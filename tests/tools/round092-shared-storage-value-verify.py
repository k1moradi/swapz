#!/usr/bin/env python3
"""Exact-source actual shared storage/authority, frozen value ABI, modeled provider."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
SOURCE = KERNEL / "zswap-original-storage-value.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round092-shared-storage-value.c"
PINS = {
    "src/kernel/authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "src/kernel/authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "src/kernel/zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "src/kernel/zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "src/kernel/zswap-original-decode.h": "a247d1aaf9865de71f97cd980be806b8d8c7c20e",
    "src/kernel/zswap-original-decoder-handles.h": "0f103783aee10d18df5c502fdf553f7ac6a0035d",
    "src/kernel/zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "src/kernel/zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "src/kernel/zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "src/kernel/zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "tests/runtime/native/repository-policy-test.py": "b200e0ca3e20d4c1f37e350ac9ef1c6426179817"
}
MUTANTS = [
    [
        "missing_retention",
        "zswap-original-storage-value.c",
        "slot->active = 1;",
        "slot->active = 0;"
    ],
    [
        "skip_put",
        "zswap-original-storage-value.c",
        "if (storage->ops.decoder_put(storage->ops.context, &slot->handle)) {",
        "if (0) {"
    ],
    [
        "generation_aba",
        "zswap-original-storage-value.c",
        "handle.generation <= storage->last_generation[handle.slot_index]",
        "handle.generation < storage->last_generation[handle.slot_index]"
    ],
    [
        "epoch_aba",
        "zswap-original-storage-value.c",
        "(storage->lifecycle_epoch && handle.lifecycle_epoch != storage->lifecycle_epoch) ||",
        "0 ||"
    ],
    [
        "snapshot_value",
        "zswap-original-storage-value.c",
        "result.snapshot.handle = slot->handle;",
        "result.snapshot.handle = (struct swapz_original_decoder_value_handle){0};"
    ],
    [
        "provider_error",
        "zswap-original-storage-value.c",
        "return error == -EAGAIN && storage->get_error ? storage->get_error : error;",
        "return storage->get_error == 0 ? error : -EAGAIN;"
    ],
    [
        "fault_refusal",
        "zswap-original-storage-value.c",
        "return !attached(storage) ? -EINVAL : storage->faulted ? -EUCLEAN : 0;",
        "return !attached(storage) ? -EINVAL : 0;"
    ],
    [
        "put_quarantine",
        "zswap-original-storage-value.c",
        "storage->faulted = 1;\n\t\treturn;\n\t}\n\tmemset(slot, 0, sizeof(*slot));",
        "storage->faulted = 0;\n\t\treturn;\n\t}\n\tmemset(slot, 0, sizeof(*slot));"
    ],
    [
        "early_record_release",
        "authority.c",
        "if (!record->is_current && !record->pins && record->decoder)",
        "if (!record->is_current && record->decoder)"
    ],
    [
        "read_wrong_handle",
        "zswap-original-storage-value.c",
        "snapshot.handle = result.snapshot.handle;",
        "snapshot.handle = result.snapshot.handle; ++snapshot.handle.generation;"
    ],
    [
        "read_wrong_crc",
        "zswap-original-storage-value.c",
        "snapshot.record.compressed_crc32c = result.snapshot.spec.compressed_crc32c;",
        "snapshot.record.compressed_crc32c = result.snapshot.spec.compressed_crc32c ^ 1U;"
    ],
    [
        "read_swallow_error",
        "zswap-original-storage-value.c",
        "return error > 0 ? -EIO : error;",
        "return error > 0 ? -EIO : 0;"
    ],
    [
        "read_alias",
        "zswap-original-storage-value.c",
        "if (!spans_disjoint(buffers[index], capacity, buffers[prior], capacity))",
        "if (0)"
    ]
]
REPORT = {"round": "093", "agent": 5, "compilers": {}, "first_error": None,
          "source_mapped_authenticated": 0, "phase_a": "BLOCKED", "import_active": 0,
          "physical_io": False, "native": "NOT_RUN", "provider": "MODELED_FROZEN_VALUE_ABI"}
MODES = (("normal", ()), ("stale_generation", ("1",)),
         ("foreign_epoch", ("2",)), ("put_failure", ("3",)))
PASS = re.compile(r"PASS ROUND093_AGENT5 checks=(\d+) storage_bytes=(\d+) legacy_bytes=(\d+) map_bytes=(\d+) sidecar_bytes=(\d+) slot_bytes=(\d+) handle_bytes=(\d+)\n")
SEMANTIC = re.compile(r"SEMANTIC_FAIL line=\d+ [^\n]+\n")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


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


def first_failure(work, result, label):
    (work / "first-child-error.log").write_text(result.stderr + result.stdout)
    raise RuntimeError(label + ": exit=" + str(result.returncode))


def preflight(work):
    sha = git("rev-parse", "HEAD").decode().strip()
    REPORT["tested_commit"] = sha
    before = os.environ.get("SWAPZ_PUSH_BEFORE_SHA", "")
    require(re.fullmatch(r"[0-9a-f]{40}", before) and before != "0" * 40,
            "invalid actual push before")
    require(sha == os.environ.get("GITHUB_SHA") and
            os.environ.get("GITHUB_EVENT_NAME") == "push" and
            os.environ.get("GITHUB_REF") == "refs/heads/main" and
            git("symbolic-ref", "--short", "HEAD").strip() == b"main", "exact main push")
    parents = [line[7:] for line in git("cat-file", "-p", "HEAD").decode().split("\n\n", 1)[0].splitlines()
               if line.startswith("parent ")]
    require(parents == [before] and git("rev-parse", "HEAD^").decode().strip() == before,
            "push before not sole parent")
    REPORT["parent"] = before
    require(git("rev-parse", "--is-shallow-repository").strip() == b"false", "full history")
    require(not git("status", "--porcelain", "--untracked-files=all"), "dirty checkout")
    require(not git("diff", "--check", before, sha, "--"), "diff whitespace")
    for path, expected in PINS.items():
        require(git("hash-object", path).decode().strip() == expected, "frozen input mismatch " + path)
    REPORT["source_blobs"] = PINS | {
        str(path.relative_to(ROOT)): git("hash-object", str(path.relative_to(ROOT))).decode().strip()
        for path in (SOURCE, SOURCE.with_suffix(".h"), FIXTURE, Path(__file__).resolve())}
    prior = git("show", before + ":docs/testing_standards.md")
    current = (ROOT / "docs/testing_standards.md").read_bytes()
    require(current.startswith(prior) and len(current) > len(prior), "full standards prefix")
    policy = run([sys.executable, "-B", "tests/runtime/native/repository-policy-test.py", "--enforce"])
    if policy.returncode:
        first_failure(work, policy, "canonical policy")
    REPORT["preflight"] = "PASS"


def compile_source(compiler, standard, paths, binary, label, work):
    command = [compiler, "-std=" + standard, "-O1", "-g", "-Wall", "-Wextra",
               "-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
               "-fno-pie", "-no-pie", "-pthread", "-Dcurrent=get_current()",
               "-DSWAPZ_ORIGINAL_STORAGE_TEST", "-DSWAPZ_ORIGINAL_EXTENT_TEST",
               "-DSWAPZ_ROUND066_IMPORT_DISK_TEST", "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
               "-DSWAPZ_SHARED_ORIGINAL_TEST", "-DSWAPZ_SHARED_STORAGE_VALUE_TEST",
               "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST", "-I", str(KERNEL),
               *(str(path) for path in paths), str(FIXTURE),
               str(KERNEL / "zswap-original-storage.c"),
               str(KERNEL / "zswap-original-extent.c"), str(KERNEL / "codec.c"),
               "-o", str(binary)]
    compiled = run(command)
    if compiled.returncode:
        first_failure(work, compiled, compiler + "/" + label + "/compile")


def baseline_run(binary, compiler, work):
    counts = {}
    sizes = None
    for mode, arguments in MODES:
        result = run([str(binary), *arguments])
        match = PASS.fullmatch(result.stdout)
        if result.returncode or result.stderr or not match:
            first_failure(work, result, compiler + "/" + mode + "/baseline")
        values = list(map(int, match.groups()))
        require(values[0] > 0 and values[3] == 20, "invalid baseline count/map")
        require(sizes is None or sizes == values[1:], "inconsistent layout")
        sizes = values[1:]
        counts[mode] = values[0]
    names = ("storage_bytes", "legacy_bytes", "map_bytes", "sidecar_bytes", "slot_bytes", "handle_bytes")
    return {"checks": counts, **dict(zip(names, sizes)), "overhead_bytes": sizes[0] - sizes[1], "mutants": []}


def main(work):
    preflight(work)
    sources = [KERNEL / "authority.c", SOURCE]
    originals = {path.name: path.read_text() for path in sources}
    require(len({item[0] for item in MUTANTS}) == len(MUTANTS), "mutation identities")
    for name, filename, old, new in MUTANTS:
        require(originals[filename].count(old) == 1 and old != new, "mutation anchor " + name)
    with tempfile.TemporaryDirectory(prefix="swapz-value-storage-") as temporary:
        directory = Path(temporary)
        binary = directory / "test"
        for compiler, standard in (("gcc", "c2x"), ("clang", "c23")):
            compile_source(compiler, standard, sources, binary, "baseline", work)
            result = baseline_run(binary, compiler, work)
            REPORT["compilers"][compiler] = result
            for name, filename, old, new in MUTANTS:
                mutant = directory / filename
                mutant.write_text(originals[filename].replace(old, new, 1))
                paths = [mutant if path.name == filename else path for path in sources]
                compile_source(compiler, standard, paths, binary, name, work)
                for mode, arguments in MODES:
                    executed = run([str(binary), *arguments])
                    if executed.returncode == 77 and not executed.stdout and SEMANTIC.fullmatch(executed.stderr):
                        result["mutants"].append({"name": name, "mode": mode, "assertion": executed.stderr.strip()})
                        break
                    if executed.returncode or executed.stderr or not PASS.fullmatch(executed.stdout):
                        first_failure(work, executed, compiler + "/" + name + "/" + mode + "/not semantic")
                else:
                    raise RuntimeError(compiler + "/" + name + ": mutant survived")
            print(f"PASS {compiler} checks={sum(result['checks'].values())} "
                  f"storage={result['storage_bytes']} overhead={result['overhead_bytes']} "
                  f"map={result['map_bytes']} semantic_mutants={len(result['mutants'])}", flush=True)
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
            print("ROUND093_AGENT5_FIRST_ERROR " + REPORT["first_error"], file=sys.stderr)
            print("Inspect private first-child-error.log if present; fix exact source, no unchanged rerun.", file=sys.stderr)
    raise SystemExit(status)
