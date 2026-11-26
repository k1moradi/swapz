#!/usr/bin/env python3
"""Join frozen authoritative storage pins to actual shared decoder gate; RAM lower only."""
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile
import tarfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "cb38c5de310edc4842e77099b92fc709e1934322"
SOURCE = ROOT / "src/kernel/zswap-original-storage-shared-decoder.c"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MODEL = ROOT / "tests/tools/round092-shared-storage-value-verify.py"
STAGING = ROOT / "tests/tools/round085-original-decode-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round096-shared-storage-gated-decoder.c"
PINS = {
    str(MODEL.relative_to(ROOT)): "4dff860176f889507ed7ebb69358186c76fb7e9f",
    str(STAGING.relative_to(ROOT)): "6beb60c0c42662e11c3fc827dcbdacb1c6167370",
    str(FIXTURE.relative_to(ROOT)): "8b4d32092e335f444ee44b354f71ac39a210746c",
    "tests/tools/round080-original-lzo1x-independent-decoder-verify.py": "c2bd6a4d35bc8261e94743f92166b7c436d3c1f2",
    str(SOURCE.relative_to(ROOT)): "c59cdf4d4e203a9a40d09e9048d3eba786d2e0cc",
    str(SOURCE.with_suffix(".h").relative_to(ROOT)): "6b1e3dc0230740be0d5f0e038b270d4984b5277d",
}
FROZEN = {
    "authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "zswap-original-decoder-shared.c": "3b48a4f6f31ef9c45034db7e0509efe92583e404",
    "zswap-original-decoder-shared.h": "19bce03addcee7a2eeb0983ea360d4e2a5df0912",
    "zswap-original-storage-shared-decoder.c": "05fa6a716dcd5b5fd6a531a63908b2e9bb53cb8f",
    "zswap-original-storage-shared-decoder.h": "b18f05a0d326dfe594e6695f13f757e313a1c3d8",
    "zswap-original-decoder-handles.h": "0f103783aee10d18df5c502fdf553f7ac6a0035d",
    "zswap-original-decode.c": "eb1cd7f90d5edade9640e1ffe9dac3c8fe774644",
    "zswap-original-decode.h": "a247d1aaf9865de71f97cd980be806b8d8c7c20e",
    "zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
}
PASS = re.compile(r"PASS ROUND096_AGENT5 codec=(\d+) checks=(\d+) lower_reads=(\d+) lifetime_gets=(\d+) lifetime_puts=(\d+) transient_gets=(\d+) transient_puts=(\d+) map=(\d+) storage=(\d+) legacy=(\d+) provider=(\d+) sidecar=(\d+) handle=(\d+) gate=(\d+) exact_gc=(\d+)")
REPORT = {"round": "096", "agent": 5, "provider": "ACTUAL_FROZEN_SHARED_DECODER_GATE",
          "lower": "MODELED_RAM_ONLY", "epoch": "MODELED_FRESH_EXTERNAL_BROKER_CAP_PAIR",
          "engineering_freeze": FREEZE, "source_mapped_authenticated": 0,
          "phase_a": "BLOCKED", "import_active": 0, "physical_io": False,
          "native": "NOT_RUN", "compilers": {}, "first_error": None}


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def run_checked(command, work, label):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            timeout=180, env=os.environ | {
                                "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
    if result.returncode or result.stderr:
        (work / "first-child-error.log").write_text(result.stderr + result.stdout)
        raise RuntimeError(label + ": exit=" + str(result.returncode))
    return result.stdout


def compile_join(compiler, standard, linux, directory, work, previous, helpers, kernel):
    shim = previous["build_shim"](linux, directory, helpers)
    staged = directory / "staged"
    staged.mkdir()
    (staged / "lz4_compress.c").write_bytes(previous["staged_bytes"](
        (linux / previous["LZ4_SOURCE"]).read_bytes(), PIN, ""))
    (staged / "lz4_decompress.c").write_bytes(previous["staged_decoder_bytes"](
        (linux / previous["LZ4_DECODER_SOURCE"]).read_bytes(), PIN, ""))
    (staged / "lz4defs.h").write_bytes((linux / "lib/lz4/lz4defs.h").read_bytes())
    objects = []
    base = ["-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-fno-pie"]
    for source in (linux / "lib/lzo/lzo1x_compress_safe.c",
                   linux / "lib/lzo/lzo1x_decompress_safe.c",
                   staged / "lz4_compress.c", staged / "lz4_decompress.c"):
        obj = directory / (source.stem + ".o")
        run_checked([compiler, "-std=gnu11", *base, "-I", str(shim), "-DCONFIG_64BIT=1",
                     "-c", str(source), "-o", str(obj)], work,
                    compiler + "/original/" + source.name)
        objects.append(obj)
    adapter = directory / "original-compressor.c"
    adapter.write_text(previous["COMPRESS_ADAPTER"])
    flags = [standard, *base, "-pthread", "-Dcurrent=get_current()",
             "-D_POSIX_C_SOURCE=200809L", "-DSWAPZ_ZSWAP_IMPORT_HOST_TEST=1",
             "-DSWAPZ_ZSWAP_IMPORT_DECODER_HOST_TEST=1",
             "-DSWAPZ_ZSWAP_IMPORT_ORIGINAL_LZO_HOST_TEST=1",
             "-DSWAPZ_ORIGINAL_STORAGE_TEST", "-DSWAPZ_ORIGINAL_EXTENT_TEST",
             "-DSWAPZ_ROUND066_IMPORT_DISK_TEST", "-DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST",
             "-DSWAPZ_SHARED_ORIGINAL_TEST", "-DSWAPZ_SHARED_STORAGE_DECODER_TEST",
             "-DSWAPZ_ORIGINAL_DECODER_SHARED_TEST",
             "-I", str(shim), "-I", str(kernel)]
    for source in (kernel / "authority.c", kernel / "codec.c",
                   kernel / "zswap-original-storage.c", kernel / "zswap-original-extent.c",
                   kernel / "zswap-original-storage-shared-decoder.c",
                   kernel / "zswap-import-decoder-owner.c", kernel / "zswap-original-decode.c",
                   kernel / "zswap-original-decoder-shared.c", FIXTURE, adapter):
        obj = directory / (source.stem + ".o")
        run_checked([compiler, *flags, "-c", str(source), "-o", str(obj)], work,
                    compiler + "/candidate/" + source.name)
        objects.append(obj)
    binary = directory / "storage-real-decoder"
    run_checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                 *(str(obj) for obj in objects), "-pthread", "-lcrypto",
                 "-Wl,--wrap=swapz_zswap_import_decoder_owner_get",
                 "-Wl,--wrap=swapz_zswap_import_decoder_owner_put", "-o", str(binary)],
                work, compiler + "/link")
    output = run_checked([str(binary)], work, compiler + "/execute")
    lines = output.splitlines()
    require(len(lines) == 2, compiler + "/verdict inventory")
    results = {}
    for expected, line in enumerate(lines, 1):
        match = PASS.fullmatch(line)
        require(match is not None, compiler + "/verdict syntax")
        codec, checks, reads, gets, puts, read_gets, read_puts, map_bytes, storage, legacy, provider, sidecar, handle, gate, exact_gc = map(int, match.groups())
        require(codec == expected and checks > 0 and reads == 14 and gets == puts == 2 and
                read_gets == read_puts == 9 and exact_gc == 7 and gate > 0 and map_bytes == 20 and handle == 24 and
                storage > legacy and provider > 0 and sidecar > 0, compiler + "/ownership or layout verdict")
        results[str(codec)] = {"checks": checks, "lower_reads": reads,
                               "lifecycle_gets": gets, "lifecycle_puts": puts,
                               "transient_gets": read_gets, "transient_puts": read_puts,
                               "map_bytes": map_bytes, "storage_bytes": storage,
                               "legacy_bytes": legacy, "overhead_bytes": storage - legacy,
                               "provider_bytes": provider, "sidecar_bytes": sidecar,
                               "handle_bytes": handle, "gate_bytes": gate, "exact_compressed_comparisons": exact_gc}
        print(line, flush=True)
    # Compile only the changed adapter for semantic negatives, keeping the
    # same real authority, gate, original codecs and independent oracle.
    candidate = kernel / SOURCE.name
    original = candidate.read_text()
    original_object = directory / (candidate.stem + ".o")
    mutants = {
        "direct_provider_bypass": (
            "swapz_original_decoder_shared_gate_read(storage->ops.gate, epoch, pin, &expected,",
            "swapz_original_decoder_shared_read(&storage->provider, pin, &expected,"),
        "duplicate_lower_read": (
            "storage->scoped_pin = pin;",
            "error = swapz_shared_storage_read(&storage->storage, pin, compressed, capacity);\n"
            "\tif (error) return error;\n\tstorage->scoped_pin = pin;"),
        "gate_close_bypass": (
            "swapz_original_decoder_shared_gate_finish_close(storage->ops.gate, storage->epoch);",
            "swapz_original_decoder_shared_finish_close(&storage->provider, storage->epoch);"),
    }
    negative_results = {}
    for name, (before, after) in mutants.items():
        require(original.count(before) == 1, "mutant anchor " + name)
        mutant_source = directory / (name + ".c")
        mutant_source.write_text(original.replace(before, after))
        mutant_object = directory / (name + ".o")
        run_checked([compiler, *flags, "-c", str(mutant_source), "-o", str(mutant_object)],
                    work, compiler + "/" + name + "/compile")
        mutant_binary = directory / name
        run_checked([compiler, "-fsanitize=address,undefined", "-fno-pie", "-no-pie",
                     *(str(mutant_object if obj == original_object else obj) for obj in objects),
                     "-pthread", "-lcrypto", "-Wl,--wrap=swapz_zswap_import_decoder_owner_get",
                     "-Wl,--wrap=swapz_zswap_import_decoder_owner_put", "-o", str(mutant_binary)],
                    work, compiler + "/" + name + "/link")
        result = subprocess.run([str(mutant_binary)], cwd=ROOT, capture_output=True, text=True,
                                timeout=180, env=os.environ | {
                                    "ASAN_OPTIONS": "halt_on_error=1:detect_leaks=1",
                                    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
        if result.returncode != 77 or not re.fullmatch(r"SEMANTIC_FAIL line=\d+ [^\n]+\n", result.stderr):
            (work / "first-child-error.log").write_text(result.stderr + result.stdout)
            raise RuntimeError(compiler + "/" + name + "/semantic negative")
        negative_results[name] = result.stderr.strip()
    return {"codecs": results, "semantic_negatives": negative_results}


def main(linux, work):
    for relative, expected in PINS.items():
        actual = run_checked(["git", "hash-object", relative], work, "pin " + relative).strip()
        require(actual == expected, "frozen input mismatch " + relative)
    model = runpy.run_path(str(MODEL))
    model["preflight"](work)
    REPORT["tested_commit"] = model["REPORT"]["tested_commit"]
    REPORT["parent"] = model["REPORT"]["parent"]
    REPORT["source_blobs"] = model["PINS"] | PINS | {
        str(Path(__file__).resolve().relative_to(ROOT)): run_checked(
            ["git", "hash-object", str(Path(__file__).resolve())], work, "verifier blob").strip()}
    freeze_standards = subprocess.run(
        ["git", "show", FREEZE + ":docs/testing_standards.md"],
        cwd=ROOT, capture_output=True, timeout=60, check=True).stdout
    require(len(freeze_standards) == 1856114 and
            (ROOT / "docs/testing_standards.md").read_bytes().startswith(freeze_standards),
            "frozen full standards prefix")
    REPORT["frozen_kernel_blobs"] = FROZEN
    previous = runpy.run_path(str(STAGING))
    require(previous["PIN"] == PIN and
            previous["LZ4_POSTIMAGE"] == "63eb4be2e23caf770649af18f6a7b2b82d79a5e7" and
            previous["LZ4_DECODER_POSTIMAGE"] == "8ca9e57ea0d03918e85e4aabcf472fe906b6bc7f",
            "unapproved original staging")
    helpers = previous["verify_inputs"](linux)
    require(run_checked(["git", "-C", str(linux), "rev-parse", "HEAD"], work, "Linux pin").strip() == PIN,
            "wrong original commit")
    require(not run_checked(["git", "-C", str(linux), "status", "--porcelain", "--untracked-files=all"],
                            work, "Linux clean"), "dirty original checkout")
    REPORT["original_linux"] = PIN
    REPORT["original_blobs"] = previous["ORIGINAL"]
    REPORT["staged_lz4"] = [previous["LZ4_POSTIMAGE"], previous["LZ4_DECODER_POSTIMAGE"]]
    with tempfile.TemporaryDirectory(prefix="swapz-shared-storage-") as temporary:
        # Stage immutable engineering inputs, never same-round peer postimages.
        archive = subprocess.run(["git", "--no-replace-objects", "archive", FREEZE, "src/kernel"],
                                 cwd=ROOT, capture_output=True, timeout=60, check=True)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as stream:
            stream.extractall(temporary, filter="data")
        kernel = Path(temporary) / "src/kernel"
        for name, expected in FROZEN.items():
            require(run_checked(["git", "hash-object", str(kernel / name)], work, "frozen " + name).strip()
                    == expected, "frozen blob mismatch " + name)
        for source in (SOURCE, SOURCE.with_suffix(".h")):
            (kernel / source.name).write_bytes(source.read_bytes())
        for compiler in ("gcc", "clang"):
            directory = Path(temporary) / compiler
            directory.mkdir()
            standard = helpers["compiler_standard"](compiler)
            REPORT["compilers"][compiler] = {"standard": standard} | compile_join(
                compiler, standard, linux, directory, work, previous, helpers, kernel)
    require(not run_checked(["git", "status", "--porcelain", "--untracked-files=all"], work,
                            "product clean after join"), "product checkout changed")
    require(not run_checked(["git", "-C", str(linux), "status", "--porcelain", "--untracked-files=all"],
                            work, "Linux clean after join"), "original checkout changed")


if __name__ == "__main__":
    os.umask(0o077)
    work = Path(sys.argv[2]).resolve()
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    status = 0
    try:
        main(Path(sys.argv[1]).resolve(), work)
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
            print("ROUND096_AGENT5_FIRST_ERROR " + REPORT["first_error"], file=sys.stderr)
    raise SystemExit(status)
