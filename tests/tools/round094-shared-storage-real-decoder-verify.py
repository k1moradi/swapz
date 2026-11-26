#!/usr/bin/env python3
"""Join actual frozen storage and original bounded decoder handles; RAM lower only."""
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
KERNEL = ROOT / "src/kernel"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MODEL = ROOT / "tests/tools/round092-shared-storage-value-verify.py"
STAGING = ROOT / "tests/tools/round085-original-decode-verify.py"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round094-shared-storage-real-decoder.c"
PINS = {
    str(MODEL.relative_to(ROOT)): "db1b01812451f45a766d74872d40983a0141052a",
    str(STAGING.relative_to(ROOT)): "6beb60c0c42662e11c3fc827dcbdacb1c6167370",
    str(FIXTURE.relative_to(ROOT)): "b5c1a61e9f1f40b321673c7fe3befbe35631ee50",
    "tests/tools/round080-original-lzo1x-independent-decoder-verify.py": "c2bd6a4d35bc8261e94743f92166b7c436d3c1f2",
    "src/kernel/zswap-original-decoder-handles.c": "c01c056fdd7f9f8aa68c7083a9e4e3ca2cdc8d6d",
    "src/kernel/zswap-original-decode.c": "eb1cd7f90d5edade9640e1ffe9dac3c8fe774644",
    "src/kernel/zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
}
PASS = re.compile(r"PASS ROUND094_AGENT5_REAL codec=(\d+) checks=(\d+) gets=(\d+) puts=(\d+) reads=(\d+) transient_gets=(\d+) transient_puts=(\d+) map=(\d+) storage=(\d+) legacy=(\d+) owner=(\d+) handle=(\d+)")
REPORT = {"round": "094", "agent": 5, "provider": "ACTUAL_FROZEN_BOUNDED_DECODER",
          "lower": "MODELED_RAM_ONLY", "source_mapped_authenticated": 0,
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


def compile_join(compiler, standard, linux, directory, work, previous, helpers):
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
             "-DSWAPZ_SHARED_ORIGINAL_TEST", "-DSWAPZ_SHARED_STORAGE_VALUE_TEST",
             "-I", str(shim), "-I", str(KERNEL)]
    for source in (KERNEL / "authority.c", KERNEL / "codec.c",
                   KERNEL / "zswap-original-storage.c", KERNEL / "zswap-original-extent.c",
                   KERNEL / "zswap-original-storage-value.c",
                   KERNEL / "zswap-import-decoder-owner.c", KERNEL / "zswap-original-decode.c",
                   KERNEL / "zswap-original-decoder-handles.c", FIXTURE, adapter):
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
        codec, checks, gets, puts, reads, read_gets, read_puts, map_bytes, storage, legacy, owner, handle = map(int, match.groups())
        require(codec == expected and checks > 0 and gets == puts and gets > 0 and
                reads == read_gets == read_puts == 5 and map_bytes == 20 and handle == 24 and
                storage > legacy and owner > 0, compiler + "/ownership or layout verdict")
        results[str(codec)] = {"checks": checks, "record_gets": gets, "record_puts": puts,
                               "read_calls": reads, "transient_gets": read_gets,
                               "transient_puts": read_puts, "map_bytes": map_bytes,
                               "storage_bytes": storage, "legacy_bytes": legacy,
                               "overhead_bytes": storage - legacy, "owner_bytes": owner,
                               "handle_bytes": handle}
        print(line, flush=True)
    return results


def main(linux, work):
    for relative, expected in PINS.items():
        actual = run_checked(["git", "hash-object", relative], work, "pin " + relative).strip()
        require(actual == expected, "frozen input mismatch " + relative)
    model = runpy.run_path(str(MODEL))
    model["preflight"](work)
    REPORT["tested_commit"] = model["REPORT"]["tested_commit"]
    REPORT["parent"] = model["REPORT"]["parent"]
    REPORT["source_blobs"] = model["PINS"] | PINS
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
    with tempfile.TemporaryDirectory(prefix="swapz-real-value-") as temporary:
        for compiler in ("gcc", "clang"):
            directory = Path(temporary) / compiler
            directory.mkdir()
            standard = helpers["compiler_standard"](compiler)
            REPORT["compilers"][compiler] = {"standard": standard, "codecs": compile_join(
                compiler, standard, linux, directory, work, previous, helpers)}
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
            print("ROUND094_AGENT5_REAL_FIRST_ERROR " + REPORT["first_error"], file=sys.stderr)
    raise SystemExit(status)
