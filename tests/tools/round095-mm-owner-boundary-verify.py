#!/usr/bin/env python3
"""Source-linked MM/broker host boundary only; no native build or old corpus."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "ff972661a75ca7f8c3c0458c3feb8b603c185eb8"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MM = "mm/zswap.c"
BROKER = "src/kernel/zswap-original-ticket.c"
HEADER = "src/kernel/zswap-original-ticket.h"
OWNER = "src/kernel/zswap-original-broker-owner.inc"
PATCH = "tests/tools/round095-mm-capture-off.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round095-mm-owner-boundary.c"
SHIM = "tests/runtime/native/fixtures/round094-owner-shim.h"
MM_STAGES = [
    ("round089-original-mm-carrier.patch", "059d1bf29cf4990e22a2f608d5d552abeec3a8d1", "8bf7e885376c5ef521adf40b1ec736e062067bff"),
    ("round090-original-mm-lifetime.patch", "337f7ff29e72d955251de0c54a9349f20c2586ec", "cbf160877e8d8b584d6010c009a3e500f8b99f38"),
    ("round091-original-mm-eviction.patch", "94bb74549c54a614406b71f28a9e8e8c22527d6a", "a9a0201c29f177a37ec95a652e79e4ea2008167a"),
    ("round092-original-module-boundary.patch", "62db468c14f23b59e7adaae65a11dcb9969f02b3", "98a8a6a66858204b61875ad9b2e8cfb0ecf8980a"),
]
INPUTS = {
    BROKER: "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    HEADER: "0630f9e4fad26458ed0778ca6ae040150e28f078",
    OWNER: "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    SHIM: "bc49e924eeee826496264503d0af1b4f1fb8e611",
    "tests/runtime/native/fixtures/round092-module-shim.h": "79623955e77b0b35d17bd14f322412d8ee202c84",
    "tests/tools/round094-original-broker-owner.patch": "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd",
    "src/kernel/dm-target.c": "2400ad0ccaf72c2586c4fd1488edb9a00246e213",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(argv, cwd=ROOT):
    return subprocess.run(argv, cwd=cwd, capture_output=True, timeout=90, check=False)


def checked(argv, cwd=ROOT):
    result = run(argv, cwd)
    require(result.returncode == 0, "command failed: " + Path(argv[0]).name)
    return result.stdout


def pin(path, expected):
    data = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    require(actual == expected, "blob mismatch " + path.name)
    return data


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:bool|int|void) " + name + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    match = matches[0]
    depth = 1
    for index in range(match.end(), len(source)):
        depth += (source[index] == "{") - (source[index] == "}")
        if depth == 0:
            return source[match.start():index + 1] + "\n"
    raise RuntimeError("unclosed function " + name)


def ordered(source, markers):
    position = 0
    for marker in markers:
        found = source.find(marker, position)
        require(found >= 0, "source ordering: " + marker)
        position = found + len(marker)


def stage(directory, linux, report):
    require(checked(["git", "rev-parse", "HEAD"], linux).decode().strip() == LINUX,
            "original Linux commit")
    (directory / MM).parent.mkdir()
    (directory / MM).write_bytes(pin(linux / MM, "ae19e301fced7e357a4c7587dfdd6abb890b9163"))
    for path, expected in INPUTS.items():
        destination = directory / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(checked(["git", "show", FREEZE + ":" + path]))
        pin(destination, expected)
    command = ["git", "apply", "--unidiff-zero", "--whitespace=error"]
    for name, expected, after in MM_STAGES:
        path = directory / "tests/tools" / name
        path.write_bytes(checked(["git", "show", FREEZE + ":tests/tools/" + name]))
        pin(path, expected)
        args = ["--include=" + MM, str(path)]
        checked(command + ["--check"] + args, directory)
        checked(command + args, directory)
        pin(directory / MM, after)
    for name, before_c, before_h, after_c, after_h in [
        (MM_STAGES[-1][0], INPUTS[BROKER], INPUTS[HEADER],
         "634b38e52b3b1e6493d6b10a694065ccc4b698ad", "6afac83a0655e532ce1ef9b8f290a367e8aabfce"),
        ("round094-original-broker-owner.patch", "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
         "6afac83a0655e532ce1ef9b8f290a367e8aabfce", "ba5e891ef7f80bf0b3021ee6c676529cb72f1972",
         "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"),
    ]:
        pin(directory / BROKER, before_c)
        pin(directory / HEADER, before_h)
        args = ["--include=" + BROKER, "--include=" + HEADER, str(directory / "tests/tools" / name)]
        checked(command + ["--check"] + args, directory)
        checked(command + args, directory)
        pin(directory / BROKER, after_c)
        pin(directory / HEADER, after_h)
    args = [str(ROOT / PATCH)]
    checked(command + ["--check"] + args, directory)
    checked(command + args, directory)
    pin(directory / MM, "9278abca17077bf9c0e94885eb4d46cdbd9202bd")
    checked(command + ["--reverse", "--check"] + args, directory)
    report["stage"] = "PASS"
    return (directory / MM).read_text()


def extract(source, target):
    gate = function(source, "swapz_mm_capture_permitted")
    require("return false;" in gate, "hard false MM gate")
    require("return false;" in function(target, "swapz_round091_ordered_claim_permitted"),
            "hard false ordered claim")
    capture = function(source, "swapz_mm_capture")
    preerase = function(source, "swapz_mm_preerase")
    require(not any(token in capture for token in ("sha256(", "swapz_crc32c_bytes(", "swapz_mm_sources[")),
            "no per-store hash/cache")
    ordered(preerase, ["swapz_mm_route_try(", "zs_obj_read_sg_begin(", "sg_copy_to_buffer(",
                       "zs_obj_read_sg_end(", "swapz_mm_eviction_key(", "swapz_ticket_reserve(",
                       "swapz_ticket_seal(", "ctx->original = carrier"])
    ordered(function(source, "zswap_writeback_entry"),
            ["entry != xa_load(tree, offset)", "zswap_decompress(entry, folio)",
             "if (swapz_mm_capture_permitted())", "swapz_mm_preerase(entry, folio", "xa_erase(tree, offset)"])
    ordered(function(target, "swapz_round090_unpublish_target"),
            ["list_del_rcu(", "synchronize_rcu()", "ctx->original_retired_cap = ctx->original_cap",
             "queue_work(", "flush_work("])
    store = re.findall(r"(?m)^\tentry->original_cookie = 0;\n\tif \(!mapped && swapz_mm_capture_permitted\(\)\)\n\t\tswapz_mm_capture\(entry, folio, index, pool, acomp_ctx->req\);$", source)
    evict = re.findall(r"(?m)^\tif \(swapz_mm_capture_permitted\(\)\)\n\t\tswapz_mm_preerase\(entry, folio, swpentry, &ctx\);$", source)
    require(len(store) == len(evict) == 1, "exact capture call sites")
    require(source.count("swapz_mm_capture(entry,") == source.count("swapz_mm_preerase(entry,") == 1,
            "no unguarded producer call sites")
    names = ("swapz_mm_eligible", "swapz_mm_route_try", "swapz_mm_candidate_get", "swapz_mm_release_workfn")
    return gate + "\n".join(function(source, name) for name in names) + (
        "\nstatic void store_site(bool mapped, struct source_entry *entry)\n{\n" + store[0] +
        "\n}\nstatic void preerase_site(void)\n{\n" + evict[0] + "\n}\n")


def exercise(directory, evidence, extracted, report):
    kernel = directory / "src/kernel"
    (directory / "r095-broker.c").write_bytes((directory / BROKER).read_bytes())
    probe = directory / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    variants = [
        ("baseline", extracted, None),
        ("unguarded_store", extracted.replace("!mapped && swapz_mm_capture_permitted()", "!mapped", 1), "disabled_store"),
        ("unguarded_eviction", extracted.replace("if (swapz_mm_capture_permitted())", "if (true)", 1), "disabled_eviction"),
    ]
    for compiler in ("gcc", "clang"):
        standard = next((item for item in ("c23", "c2x")
                         if run([compiler, "-std=" + item, "-fsyntax-only", str(probe)]).returncode == 0), None)
        require(standard, "missing C23 compiler " + compiler)
        result = {"status": "IN_PROGRESS", "standard": standard, "mutants": {}}
        report[compiler] = result
        for name, text, witness in variants:
            (directory / "r095-mm-extracted.h").write_text(text)
            binary = directory / (compiler + "-" + name)
            compilation = run([compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                               "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                               "-pedantic", "-pthread", "-no-pie", "-fsanitize=address,undefined",
                               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                               "-DSWAPZ_ORIGINAL_TICKET_TEST=1", "-DSWAPZ_TICKET_MODULE_HOST_TEST=1",
                               "-DSWAPZ_TICKET_OWNER_HOST_TEST=1", "-include", str(directory / SHIM),
                               "-I", str(kernel), "-I", str(directory),
                               "-I", str((directory / SHIM).parent),
                               str(FIXTURE), str(kernel / "codec.c"), "-o", str(binary)])
            (evidence / (compiler + "-" + name + "-compile.log")).write_bytes(compilation.stdout + compilation.stderr)
            first = next((line for line in compilation.stderr.decode(errors="replace").splitlines()
                          if "error:" in line), "no compiler diagnostic")
            require(compilation.returncode == 0, compiler + "/" + name + " " + first[:200])
            execution = subprocess.run([str(binary)], capture_output=True, timeout=30, check=False,
                                       env={**os.environ, "ASAN_OPTIONS": "detect_leaks=" + ("1" if witness is None else "0")})
            (evidence / (compiler + "-" + name + "-run.log")).write_bytes(execution.stdout + execution.stderr)
            if witness is None:
                match = re.fullmatch(rb"PASS_HOST_ONLY R095 A11 checks=(\d+)\n", execution.stdout)
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline " + execution.stderr.decode(errors="replace")[:160])
                result["checks"] = int(match[1])
                print(compiler + " " + execution.stdout.decode().strip(), flush=True)
            else:
                require(execution.returncode == 77 and not execution.stdout and
                        re.fullmatch(rb"R095_A11_FIRST_ERROR " + witness.encode() + rb" line=\d+\n", execution.stderr),
                        compiler + "/" + name + " not semantic kill")
                result["mutants"][name] = "KILLED"
        result["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "tested_commit": checked(["git", "rev-parse", "HEAD"]).decode().strip(),
              "engineering_freeze": FREEZE, "source_authentication": 0, "phase_a": "BLOCKED",
              "direct_handoff": "DISABLED", "forced_raw": "DISABLED", "import": 0,
              "native": "NOT_RUN", "physical": "NOT_RUN", "host": {}, "first_error": None}
    try:
        with tempfile.TemporaryDirectory(prefix="r095-a11-") as temporary:
            directory = Path(temporary)
            source = stage(directory, args.linux, report)
            extracted = extract(source, (directory / "src/kernel/dm-target.c").read_text())
            exercise(directory, args.output, extracted, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R095_A11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
