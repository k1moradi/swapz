#!/usr/bin/env python3
"""R091 Agent11 actual pristine->R089->R090->R091 staged host-only qualification.

No original Linux checkout or product source is modified by this verifier.
Only the extracted actual changed functions run in a strict C host ABI shim.
"""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PRIOR = runpy.run_path(str(ROOT / "tests/tools/round090-original-mm-lifetime-verify.py"))
EARLIER = PRIOR["BASE"]
require, checked, run = (EARLIER[name] for name in ("require", "checked", "run"))
verify_pins, blob, ordered = (EARLIER[name] for name in
                             ("verify_pins", "blob", "ordered"))
PATCH = ROOT / "tests/tools/round091-original-mm-eviction.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round091-original-mm-eviction.c"
PREVIOUS = PRIOR["POST"]
POST = dict(PREVIOUS)
POST.update({
    "mm/zswap.c": "a9a0201c29f177a37ec95a652e79e4ea2008167a",
    "include/linux/swapz_mm_carrier.h": "a516cab0813a5ecb70054bf488d536b05dcd4c52",
})
PRODUCT = dict(EARLIER["PRODUCT"])
PRODUCT.update({
    "src/kernel/zswap-original-ticket.h": "0630f9e4fad26458ed0778ca6ae040150e28f078",
    "src/kernel/zswap-original-ticket.c": "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
})
INPUTS = {
    "tests/tools/round091-original-mm-eviction.patch": "94bb74549c54a614406b71f28a9e8e8c22527d6a",
    "tests/runtime/native/fixtures/round091-original-mm-eviction.c": "5bdf06888cc0cbeabe9726d6274b1e6433a07921",
    "tests/tools/round090-original-mm-lifetime.patch": "337f7ff29e72d955251de0c54a9349f20c2586ec",
    "tests/tools/round089-original-mm-carrier.patch": "059d1bf29cf4990e22a2f608d5d552abeec3a8d1",
}


def actual_function(source, name):
    # Original exported candidate_get is int, not static; retain exact one-definition match.
    pattern = re.compile(r"(?m)^(?:static )?(?:bool|u8|u64|int|void) " +
                         re.escape(name) + r"\([^;]+?\)\n\{")
    matches = list(pattern.finditer(source))
    require(len(matches) == 1, "original function anchor " + name)
    start = matches[0].start()
    depth = 1
    for index in range(matches[0].end(), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1] + "\n"
    raise RuntimeError("unclosed original function " + name)


def source_checks(staged):
    source = (staged / "mm/zswap.c").read_text()
    header = (staged / "include/linux/swapz_mm_carrier.h").read_text()
    broker = (ROOT / "src/kernel/zswap-original-ticket.h").read_text()
    capture = actual_function(source, "swapz_mm_capture")
    preerase = actual_function(source, "swapz_mm_preerase")
    eviction = actual_function(source, "swapz_mm_eviction_key")
    next_generation = actual_function(source, "swapz_mm_next")

    ordered(actual_function(source, "zswap_writeback_entry"),
            ["entry != xa_load(tree, offset)", "zswap_decompress(entry, folio)",
             "swapz_mm_preerase(entry, folio", "xa_erase(tree, offset)"],
            "native locked-folio decode/erase")
    require("entry->swpentry.val != slot.val" in preerase and
            "!entry->original_cookie" in preerase and
            "pool = zswap_entry_pool(entry)" in preerase and
            "swapz_mm_pool_codec(pool->tfm_name)" in preerase,
            "real entry/slot/pool provenance guards")
    ordered(capture, ["rcu_access_pointer(swapz_mm_provider)",
                      "crypto_acomp_alg_name(tfm)", "crypto_acomp_driver_name(tfm)",
                      "swapz_mm_eligible(", "swapz_mm_next("],
            "store-only eligible generation")
    require("sha256(" not in capture and "swapz_crc32c_bytes(" not in capture and
            "swapz_mm_sources" not in capture and
            "atomic_cmpxchg_acquire" not in capture,
            "store must not hash or occupy sparse cells")
    ordered(preerase, ["swapz_mm_pool_codec(", "swapz_mm_route_try(",
                      "zs_obj_read_sg_begin(", "sg_copy_to_buffer(",
                      "zs_obj_read_sg_end(", "swapz_mm_eviction_key(",
                      "swapz_ticket_reserve(", "swapz_ticket_seal(",
                      "ctx->original = carrier"],
            "route before original byte capture / credential before reserve")
    critical = preerase.split("zs_obj_read_sg_begin(", 1)[1].split(
        "zs_obj_read_sg_end(", 1)[0]
    require(not re.search(r"\b(?:sha256|swapz_crc32c_bytes|swapz_ticket_\w+|"
                          r"mutex_lock|kmalloc|queue_work)\s*\(", critical),
            "no slow work / broker operation in zsmalloc SG pin")
    require("sha256(decoded, 4096, key->sha256)" in eviction and
            "swapz_crc32c_bytes(compressed, length)" in eviction,
            "exact original byte CRC/full-page digest")
    require("previous == S64_MAX" in next_generation and
            "atomic64_try_cmpxchg" in next_generation,
            "generation one-try nonwrap")
    require("swapz_mm_sources[" not in source and
            "SWAPZ_MM_SOURCE_SLOTS" not in header and
            "struct swapz_mm_source" not in header,
            "eliminate fixed low-six-bit residency/cache")
    require("rcu_dereference(origin->bi_swapz_original)" in
            actual_function(source, "swapz_mm_candidate_get") and
            "synchronize_rcu()" in actual_function(source, "swapz_mm_release_workfn"),
            "preserve prior RCU retain/grace lifecycle")
    require("same already" in broker.lower() and
            "transfer ownership" in broker.lower() and
            "never enqueue a second" in broker.lower(),
            "revised ordered-head one-descriptor broker contract")
    return source


def run_host(staged, scratch, evidence, report):
    source = source_checks(staged)
    names = ("swapz_mm_profile", "swapz_mm_pool_codec",
             "swapz_mm_eviction_key", "swapz_mm_next")
    parts = {name: actual_function(source, name) for name in names}
    baseline = "\n".join(parts.values())
    def replace_once(original, old, replacement, label):
        require(original.count(old) == 1, "mutation anchor " + label)
        return original.replace(old, replacement, 1)

    mutations = {
        "no_generation": replace_once(
            baseline, "!key || !sequence || !area", "!key || !area", "no_generation"),
        "no_codec": replace_once(
            baseline, "(codec != SWAPZ_TICKET_LZ4 && codec != SWAPZ_TICKET_LZO1X)",
            "false", "no_codec"),
        "no_crc": replace_once(
            baseline, "key->crc = swapz_crc32c_bytes(compressed, length);",
            "key->crc = 0;", "no_crc"),
        "no_digest": replace_once(
            baseline, "sha256(decoded, 4096, key->sha256);",
            "memset(key->sha256, 0, sizeof(key->sha256));", "no_digest"),
        "no_pool": "\n".join([
            parts["swapz_mm_profile"],
            replace_once(parts["swapz_mm_pool_codec"], 'name, "lz4"',
                         'name, "unknown-lz4"', "no_pool"),
            parts["swapz_mm_eviction_key"], parts["swapz_mm_next"]]),
    }
    expected_witness = {
        "no_generation": "bad_sequence",
        "no_codec": "bad_codec",
        "no_crc": "crc_compare",
        "no_digest": "sha_compare",
        "no_pool": "pool_lz4",
    }
    require(all(mutated != baseline for mutated in mutations.values()),
            "must compile meaningful distinct mutants")
    probe = scratch / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for compiler in ("gcc", "clang"):
        standard = next((value for value in ("c23", "c2x")
                         if run([compiler, "-std=" + value, "-fsyntax-only",
                                 str(probe)]).returncode == 0), None)
        require(standard, "missing C23 compiler " + compiler)
        compiler_result = {
            "standard": standard,
            "compiler_version": checked([compiler, "--version"]).splitlines()[0],
            "status": "IN_PROGRESS", "mutants": {}
        }
        report[compiler] = compiler_result
        for variant, content in [("baseline", baseline), *mutations.items()]:
            (scratch / "r091-extracted-functions.h").write_text(content)
            binary = scratch / (compiler + "-" + variant)
            command = [
                compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread",
                "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-no-pie",
                "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                "-I", str(ROOT / "src/kernel"), "-I", str(scratch),
                str(FIXTURE), str(ROOT / "src/kernel/zswap-original-ticket.c"),
                str(ROOT / "src/kernel/codec.c"), "-lcrypto", "-o", str(binary)
            ]
            compilation = run(command, timeout=60)
            (evidence / (compiler + "-" + variant + "-compile.log")).write_text(
                compilation.stdout + compilation.stderr)
            diagnostic = next((line for line in compilation.stderr.splitlines()
                               if "error:" in line or "fatal" in line), "no classified diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)",
                                r"\1", diagnostic)
            require(compilation.returncode == 0,
                    compiler + " " + variant + " compile " + diagnostic[:180])
            execution = run([str(binary)], timeout=30)
            (evidence / (compiler + "-" + variant + "-run.log")).write_text(
                execution.stdout + execution.stderr)
            if variant == "baseline":
                match = re.fullmatch(
                    r"PASS_HOST_ONLY R091 checks=(\d+) lag64=960/960 "
                    r"lag256=768/768 lag1024=1024/1024 cookie=(\d+) "
                    r"broker=(\d+) trace_cpu_seconds=([0-9.]+)\n",
                    execution.stdout)
                cause = next((line for line in execution.stderr.splitlines()
                              if re.search(r"R091_FIRST_ERROR|runtime error:|AddressSanitizer",
                                           line)), "no classified execution diagnostic")
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline " + cause[:180])
                require(int(match[1]) >= 40 and int(match[2]) == 8,
                        "host proof count and compact cookie " + compiler)
                compiler_result.update(checks=int(match[1]), delayed_lag_hits={
                    "64": [960, 960], "256": [768, 768], "1024": [1024, 1024]},
                    cookie_bytes=int(match[2]), broker_bytes=int(match[3]),
                    trace_cpu_seconds=float(match[4]), race_threads=2)
                print(compiler + " " + execution.stdout.strip(), flush=True)
            else:
                require(execution.returncode == 77 and
                        "R091_FIRST_ERROR " + expected_witness[variant] in execution.stderr,
                        compiler + "/" + variant + " not semantic kill")
                compiler_result["mutants"][variant] = "KILLED"
                print(compiler + " semantic kill " + variant, flush=True)
        compiler_result["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "IN_PROGRESS", "kernel_compile": "NOT_RUN",
        "native": "NOT_RUN", "physical": "NOT_RUN", "source_authentication": 0,
        "phase_a": "BLOCKED", "direct_handoff": "DISABLED",
        "forced_raw": "DISABLED", "import": 0
    }
    try:
        require(checked(["git", "rev-parse", "HEAD"], args.linux).strip() ==
                EARLIER["PIN"], "original Linux commit pin")
        require(not checked(["git", "status", "--porcelain", "--untracked-files=all"],
                            args.linux), "dirty pristine Linux checkout")
        verify_pins(ROOT, PRODUCT)
        verify_pins(ROOT, INPUTS)
        verify_pins(args.linux, EARLIER["PRISTINE"])
        report["pristine_pins"] = len(EARLIER["PRISTINE"])
        with tempfile.TemporaryDirectory(prefix="r091-a11-") as temporary:
            scratch = Path(temporary)
            staged = scratch / "stage"
            for path in EARLIER["PRISTINE"]:
                destination = staged / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((args.linux / path).read_bytes())
            for patch, pins, label in (
                (EARLIER["PATCH"], EARLIER["POST"], "R089"),
                (PRIOR["OVERLAY"], PREVIOUS, "R090"),
                (PATCH, POST, "R091"),
            ):
                checked(["git", "apply", "--unidiff-zero", "--check", str(patch)], staged)
                checked(["git", "apply", "--unidiff-zero", str(patch)], staged)
                verify_pins(staged, pins)
                report[label + "_postimage_pins"] = len(pins)
            require(run(["git", "apply", "--unidiff-zero", "--check", str(PATCH)],
                        staged).returncode != 0, "duplicate R091 overlay accepted")
            checked(["git", "apply", "--unidiff-zero", "--reverse", "--check",
                     str(PATCH)], staged)
            for path in EARLIER["PRISTINE"].keys() - POST.keys():
                require(blob((staged / path).read_bytes()) ==
                        EARLIER["PRISTINE"][path], "unintended source drift " + path)
            report["stage"] = "PASS"
            report["host"] = {}
            run_host(staged, scratch, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        print("PASS_HOST_ONLY R091 exact original eviction provenance; kernel NOT_RUN AUTH0",
              flush=True)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R091_AGENT11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
