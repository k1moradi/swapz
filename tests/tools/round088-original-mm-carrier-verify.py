#!/usr/bin/env python3
"""R088 exact scratch-stage patch and source-linked rootless helper checks."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PATCH = ROOT / "tests/tools/round088-original-mm-carrier.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round088-original-mm-carrier.c"
PRISTINE = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
    "include/linux/swap_ops.h": "57ac6c703f685883d3a15ebc1a5c7f6c298deb1b",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
    "mm/zsmalloc.c": "7ef80e0da6267661cea4d48a4a615444724782e7",
    "mm/swapfile.c": "254ce86fa923e6b5f1fefda88c39315c4cc00642",
    "mm/swap.h": "d5bf21f517dceae58eb94fb0ce5f4e1fdc679409",
    "include/linux/swap.h": "4f686709d71f005dc43b2f751012b5f61d6b007a",
    "include/linux/bvec.h": "b63914ff56e33df302055fabf2a84ba490bc8d2c",
    "include/linux/blkdev.h": "2d5c30823aab9be31d881be1de8ae60feb7a5c57",
    "include/linux/workqueue.h": "c8a36423cb3465ba8c00735b2ca152eb7122a97a",
    "include/crypto/acompress.h": "5d5358dfab73458fc4bc345fe00650e938fe36c6",
    "include/crypto/sha2.h": "22fbc37ae840796ecbafd5eadf23373e51741f9e",
}
POST = {
    "mm/zswap.c": "e3caa72ca37a7a3cdb3ed51639d9507b22fe4e51",
    "mm/page_io.c": "0b0fe917fa3af5deaef8263274edffbf1a62eedb",
    "include/linux/swap_ops.h": "a39a1921daf6f272e9812eb63b1aa64fec96c57f",
    "include/linux/blk_types.h": "0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c",
    "include/linux/bio.h": "f4c5f1730514cf1816ffd5e9787562439dfae236",
    "block/bio.c": "3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e",
    "include/linux/swapz_mm_carrier.h": "7ac3fe204983aa7ba5a291aa756d37e235f8508f",
}
PRODUCT = {
    "src/kernel/zswap-original-ticket.h": "b772cc28755a68719f4dcdabefeefe57b5efea67",
    "src/kernel/zswap-original-ticket.c": "dcea7cbc40094fed2997d6704c712ac47aa164a1",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "tests/tools/round088-original-mm-carrier.patch": "b9a10044c7cd750d908730b5a95a4e945883ec45",
    "tests/runtime/native/fixtures/round088-original-mm-carrier.c": "d173ef985b801ba34815754d9d9918eeace3ec06",
}


def require(condition, error):
    if not condition:
        raise RuntimeError(error)


def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def run(args, cwd=None, timeout=60):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def checked(args, cwd=None):
    result = run(args, cwd)
    require(result.returncode == 0, "command failure: " + " ".join(args[:2]))
    return result.stdout


def verify_pins(root, pins):
    for path, expected in pins.items():
        require(blob((root / path).read_bytes()) == expected, "blob drift " + path)


def function(source, name):
    # Exact source fragment, not a replacement model. These functions have
    # no preprocessor branches; brace scan handles nested blocks.
    match = list(re.finditer(r"(?m)^(?:static )?(?:bool|u8|int|void) " +
                             re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(match) == 1, "function anchor " + name)
    start = match[0].start()
    depth = 1
    for index in range(match[0].end(), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1] + "\n"
    raise RuntimeError("unterminated function " + name)


def ordered(source, tokens, label):
    cursor = 0
    for token in tokens:
        index = source.find(token, cursor)
        require(index >= 0, label + " missing/order " + token)
        cursor = index + len(token)


def source_checks(staged):
    zswap = (staged / "mm/zswap.c").read_text()
    page = (staged / "mm/page_io.c").read_text()
    block = (staged / "block/bio.c").read_text()
    preerase = function(zswap, "swapz_mm_preerase")
    writeback = function(zswap, "zswap_writeback_entry")
    ordered(writeback, ["entry != xa_load(tree, offset)", "zswap_decompress(entry, folio)",
                        "swapz_mm_preerase(entry, folio", "xa_erase(tree, offset)",
                        "zswap_entry_free(entry)", "folio_put(folio)",
                        "__swap_writeout(&ctx, folio)", "swap_write_submit(&ctx)"],
            "original writeback")
    ordered(preerase, ["swapz_mm_route_try(si, sector, &route)", "atomic_cmpxchg_acquire",
                       "swapz_ticket_reserve", "zs_obj_read_sg_begin",
                       "sg_copy_to_buffer", "zs_obj_read_sg_end", "sha256(decoded",
                       "swapz_ticket_seal", "ctx->original = carrier", "decline:",
                       "swapz_mm_drop(&carrier)"], "producer")
    pin_span = preerase.split("zs_obj_read_sg_begin", 1)[1].split("zs_obj_read_sg_end", 1)[0]
    require(not re.search(r"\b(?:swapz_ticket_\w+|sha256|mutex_lock|kmalloc|queue_work)\s*\(",
                          pin_span), "SG critical section widened")
    require("return false;" in function(zswap, "swapz_mm_route_try"), "route must refuse")
    ordered(function(zswap, "zswap_compress"),
            ["zs_obj_write", "entry->length = dlen", "memset(&entry->original",
             "if (!mapped)", "swapz_mm_capture"], "store capture")
    ordered(function(page, "swap_add_folio"),
            ["mempool_alloc", "sio->original = NULL", "swapz_mm_move",
             "bvec_set_folio", "++sio->nr_bvecs", "swap_write_submit(ctx)"], "sio move")
    ordered(function(page, "swap_bdev_submit_write"),
            ["bio_init", "bio->bi_iter.bi_size = sio->len", "swap_folio_sector",
             "swapz_mm_bio_matches", "bio->bi_swapz_original = sio->original",
             "submit_bio_wait(bio)", "end_swap_bio_write(bio)", "submit_bio(bio)"],
            "full native BIO")
    ordered(function(page, "end_swap_bio_write"), ["bio_uninit(bio)", "swap_write_end"],
            "terminal borrow")
    ordered(function(page, "swap_write_end"), ["folio_mark_dirty", "folio_clear_reclaim",
            "folio_end_writeback", "swapz_mm_drop", "mempool_free"], "terminal owner")
    for name in ("bio_uninit", "bio_prepare_reissue", "__bio_clone", "bio_endio", "bio_trim"):
        require("bi_swapz_original = NULL" in function(block, name), "BIO invalidate " + name)
    require("bio_uninit(bio)" in function(block, "bio_reset"), "reset invalidate")
    require("bio_reset(bio" in function(block, "bio_reuse"), "reuse invalidate")
    drop = function(zswap, "swapz_mm_drop")
    require("swapz_ticket_put" not in drop and "queue_work" in drop, "deferred release")
    # No kernel compilation, execution, or authentication implied.
    return zswap


def host(staged, scratch, evidence, results):
    source = source_checks(staged)
    header = (staged / "include/linux/swapz_mm_carrier.h").read_text()
    for include in ("#include <linux/blkdev.h>\n", "#include <linux/mm_types.h>\n"):
        require(header.count(include) == 1, "shim include anchor")
        header = header.replace(include, "")
    (scratch / "r088-staged-carrier.h").write_text(header)
    (scratch / "r088-staged-functions.h").write_text(
        function(source, "swapz_mm_profile") + function(source, "swapz_mm_candidate_get"))
    for compiler in ("gcc", "clang"):
        # Probe supported standard spelling, not the actual source.
        probe = scratch / "probe.c"
        probe.write_text("int main(void) { return 0; }\n")
        standard = next((std for std in ("c23", "c2x")
                         if run([compiler, "-std=" + std, "-fsyntax-only", str(probe)]).returncode == 0),
                        None)
        require(standard, "no C23 spelling " + compiler)
        binary = scratch / compiler
        command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                   "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                   "-pedantic", "-pthread", "-fsanitize=address,undefined",
                   "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
                   "-DSWAPZ_ORIGINAL_TICKET_TEST=1", "-I", str(ROOT / "src/kernel"),
                   "-I", str(scratch), str(FIXTURE), str(ROOT / "src/kernel/zswap-original-ticket.c"),
                   str(ROOT / "src/kernel/codec.c"), "-o", str(binary)]
        results[compiler] = {"standard": standard, "status": "COMPILE_PENDING"}
        build = run(command)
        (evidence / (compiler + "-compile.log")).write_text(build.stdout + build.stderr)
        if build.returncode:
            results[compiler]["status"] = "COMPILE_FAIL"
            diagnostic = next((line for line in build.stderr.splitlines() if "error:" in line),
                              "no classified compiler diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
            raise RuntimeError(compiler + " " + diagnostic[:180])
        execution = run([str(binary)])
        (evidence / (compiler + "-run.log")).write_text(execution.stdout + execution.stderr)
        if execution.returncode or execution.stderr:
            results[compiler]["status"] = "EXECUTION_FAIL"
            diagnostic = next((line for line in execution.stderr.splitlines()
                               if re.search(r"R088_FIRST_ERROR|runtime error:|AddressSanitizer", line)),
                              "no classified runtime diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
            raise RuntimeError(compiler + " " + diagnostic[:180])
        match = re.fullmatch(r"PASS_HOST_ONLY R088 actual staged carrier helpers checks=(\d+)\n",
                             execution.stdout)
        require(match and int(match[1]) >= 50, "host count/marker " + compiler)
        results[compiler] = {"standard": standard, "checks": int(match[1]), "status": "PASS"}
        print(compiler + " " + execution.stdout.strip(), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "source_authentication": 0,
              "kernel_compile": "NOT_RUN", "native": "NOT_RUN", "physical": "NOT_RUN"}
    try:
        require(checked(["git", "rev-parse", "HEAD"], args.linux).strip() == PIN, "Linux pin")
        require(not checked(["git", "status", "--porcelain", "--untracked-files=all"], args.linux),
                "dirty Linux checkout")
        verify_pins(ROOT, PRODUCT)
        verify_pins(args.linux, PRISTINE)
        report["pristine_pins"] = len(PRISTINE)
        with tempfile.TemporaryDirectory(prefix="r088-") as tmp:
            scratch = Path(tmp)
            # Scratch-only copy of the pinned files, never mutate Linux checkout.
            staged = scratch / "stage"
            staged.mkdir()
            for path in PRISTINE:
                dst = staged / path
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes((args.linux / path).read_bytes())
            checked(["git", "apply", "--unidiff-zero", "--check", str(PATCH)], staged)
            checked(["git", "apply", "--unidiff-zero", str(PATCH)], staged)
            verify_pins(staged, POST)
            for path in PRISTINE.keys() - POST.keys():
                require(blob((staged / path).read_bytes()) == PRISTINE[path], "unexpected change " + path)
            report["postimage_pins"] = len(POST)
            # Reapply and reverse-check rejection/acceptance on real patch.
            require(run(["git", "apply", "--unidiff-zero", "--check", str(PATCH)], staged).returncode != 0,
                    "duplicate stage accepted")
            checked(["git", "apply", "--unidiff-zero", "--reverse", "--check", str(PATCH)], staged)
            report["stage"] = "PASS"
            report["host"] = {}
            host(staged, scratch, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        print("PASS_HOST_ONLY R088 exact stage + actual extracted C helpers; kernel NOT_RUN AUTH0", flush=True)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R088_AGENT11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
