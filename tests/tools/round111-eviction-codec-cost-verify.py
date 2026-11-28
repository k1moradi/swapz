#!/usr/bin/env python3
"""Round111 diagnostic: actual production decision, pinned original wrappers.
Linux LZO C is compiled; LZ4 uses the explicitly disclosed R052 host backend.
No runtime-selected pool, kernel execution, lower I/O, admission or activation.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import hashlib
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
PIN = "4345f21b1da720e6c8d685c7b232bfcebe635d50"
TREE = "98cb27a3f57d6482d859a260526edb5614ec7994"
RECOVERY_PIN = "7911cb6873ea4bd7158c9fa06ac615eee1d4d2f1"
RECOVERY_TREE = "5a9553a2a7c9a66bd0080fcf073bef2a4f672fe0"
PRODUCT_TREE = "880d169f92383f438513d55e5fa2652bb3d9e0ae"
ATTRIBUTION_PIN = "c87f9f92fc656db5670d9bfd75c7fcf826aa9bbf"
ATTRIBUTION_TREE = "7b6fe1478215a0485bb054c30a2a2f51711ddf45"
R112_REPORT = "docs/handoff/zswapz/round112/agent4-results.json"
R112_REPORT_BLOB = "b8e676ee4fc4889fb66b3b528c39e1e8dc7600d9"
CRC_PIN = "308f3b57774b42e20f295a13139655a10b25539d"
CRC_TREE = "80538948801519c0c3c17440cc64edf77443a896"
R114_REPORT = "docs/handoff/zswapz/round114/agent4-results.json"
R114_REPORT_BLOB = "ca98c75e68a92ba456cd450aaaaab60b02995783"
CRC_LENGTHS = (0, 1, 2, 3, 4, 7, 8, 9, 15, 16, 17, 31, 32, 63, 64, 65,
               127, 128, 255, 256, 511, 512, 513, 1023, 1024, 2047, 2048,
               3567, 3568, 3569, 4095, 4096)
STRATA = ["zero", "same", "random", "repeated", "structured", "mixed", "pattern512"]
MICRO_NAMES = ["empty_batch", "original_decode", "ordinary_decode_with_inverse", "ordinary_crc",
               "preserve_crc", "ordinary_payload_copy", "preserve_payload_copy",
               "two_monotonic_clocks_and_score_note_proxy", "inverse_only"]
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
FIXTURE = ROOT / "tests/runtime/native/codec/round111-eviction-codec-cost.c"
KERNEL = ROOT / "src/kernel"
PINS = {
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/dm-target.c": "5ecc477dc6c795d89e2a67ad2f6424a94d314b2d",
    "src/kernel/engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "src/kernel/predictor.c": "b1ce85ef0fb6a20d720dfba562d3a9a3588f127c",
    "tests/tools/round052-zswap-swapz-codec-verify.py": "041d91a6ee496dd8d9c46c1c3fde2c3ea95e4d61",
    "tests/tools/round056-codec-profile-verify.py": "a417dbf8d3a76844c81e147e1060f4c3b07d15ad",
}

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def run(command, label):
    completed = subprocess.run(command, capture_output=True, text=True,
                               timeout=180, check=False,
                               env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                    "UBSAN_OPTIONS": "halt_on_error=1"})
    if completed.returncode or completed.stderr:
        # Do not print arbitrary child stderr to the console.
        detail = PRIVATE / "first-error.log"
        detail.write_text(completed.stdout + "\n" + completed.stderr)
        detail.chmod(0o600)
        diagnostic = next((kind for kind in ("-Werror=shadow", "AddressSanitizer",
                           "UndefinedBehaviorSanitizer", "runtime error:", "ROUND111_CODEC_FIRST_ERROR")
                           if kind in completed.stderr), "child diagnostic retained")
        raise RuntimeError(f"{label}: exit={completed.returncode}; {diagnostic}; private first-error.log")
    return completed.stdout.strip()

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests/tools" / (name + ".py"))
    require(spec is not None and spec.loader is not None, "adapter unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def block(source, anchor):
    start = source.index(anchor)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if not depth:
                return source[start:index + 1]
    raise RuntimeError("source extraction unterminated")

def quantile(values, q):
    return sorted(values)[math.ceil(len(values) * q) - 1]

def stats(values):
    require(len(values) == 20, "missing batch samples")
    return {"median": statistics.median(values), "p95": quantile(values, .95),
            "p99": quantile(values, .99), "stdev": statistics.stdev(values)}

def summarize(case):
    count = case["eligible"]
    stratum = case["stratum"]
    require(-1 <= stratum < len(STRATA), "invalid stratum")
    case["stratum_name"] = "r112_shared" if stratum == -1 else STRATA[stratum]
    require(case["byte_exact"] and case["pages"] == (192 if stratum == -1 else 32), "missing correctness")
    require(sum(case["category_counts"]) == case["pages"], "corpus count")
    require(sum(case["eligible_by_category"]) == count, "eligible count")
    require(count + case["zero"] + case["same"] + case["over_cap"] +
            case["unsupported_control"] == case["pages"], "partition count")
    require(len(case["pairs"]) == (20 if count else 0), "exact paired batch count")
    require(all(len(pair) == 4 and min(pair) > 0 for pair in case["pairs"]), "invalid pair columns")
    require(all(sum(bins) == count for bins in case["size_bins"]), "payload histogram count")
    require(case["preserve_copy_bytes"] == case["payload_bytes"][1], "preserve copy count")
    require(case["ordinary_actual_planner_bytes"] >= case["payload_bytes"][0], "ordinary packing size")
    expected_ids = list(range(192)) if stratum == -1 else (
        list(range(stratum, 192, 6)) if stratum < 6 else list(range(192, 224)))
    sizes = case["page_sizes"]
    require([row[0] for row in sizes] == expected_ids, "page IDs differ")
    require(all(len(row) == 4 and 0 < row[1] <= 8192 and 0 <= row[2] <= 4096
                and row[3] in (0, 1) and (not row[3] or row[1] <= 3568)
                for row in sizes), "page size or eligibility")
    require(sum(row[3] for row in sizes) == count, "eligible IDs count")
    require([sum(row[column] for row in sizes if row[3]) for column in (2, 1)] ==
            case["payload_bytes"], "eligible payload totals")
    crcs = case["page_crcs"]
    require([row[0] for row in crcs] == expected_ids and all(
        len(row) == 5 and all(type(value) is int and 0 <= value <= 0xffffffff for value in row[1:])
        for row in crcs), "invalid page CRC census")
    require(all(crc[4] == (crc[2] if size[3] else crc[3]) for size, crc in zip(sizes, crcs)),
            "preserved/fallback CRC mismatch")
    case["eligibility_rate"] = count / case["pages"]
    case["timing_ns_per_page_batch_statistics"] = {}
    case["paired_preserve_minus_ordinary_ns_per_page"] = {}
    case["micro_ns_per_page_batch_statistics"] = {}
    case["micro_paired_preserve_minus_ordinary_ns_per_page"] = {}
    case["fixed_class_model_padding_bytes"] = [
        [size - case["payload_bytes"][arm] for size in sizes]
        for arm, sizes in enumerate(case["fixed_class_model_bytes"])]
    require(all(padding >= 0 for arm in case["fixed_class_model_padding_bytes"] for padding in arm),
            "negative model padding")
    require(0 <= case["inverse_pages"] <= count, "inverse count")
    require(len(case["micro_pairs"]) == (20 if count else 0), "missing micro batches")
    if not count:
        return case
    for index, name in enumerate(("ordinary_write", "ordinary_read", "preserve_write", "preserve_read")):
        case["timing_ns_per_page_batch_statistics"][name] = stats([pair[index] / count for pair in case["pairs"]])
    for index, name in enumerate(("write", "read")):
        values = [(pair[index + 2] - pair[index]) / count for pair in case["pairs"]]
        case["paired_preserve_minus_ordinary_ns_per_page"][name] = {
            **stats(values), "preserve_faster_pairs": sum(value < 0 for value in values)}
    require(all(len(pair) == len(MICRO_NAMES) and min(pair[:-1]) > 0 and
                (pair[-1] > 0 if case["inverse_pages"] else pair[-1] == 0)
                for pair in case["micro_pairs"]), "invalid micro batch")
    for index, name in enumerate(MICRO_NAMES):
        denominator = case["inverse_pages"] if name == "inverse_only" else count
        case["micro_ns_per_page_batch_statistics"][name] = (
            stats([pair[index] / denominator for pair in case["micro_pairs"]]) if denominator else None)
    for left, right, name in ((3, 4, "crc"), (5, 6, "payload_copy")):
        case["micro_paired_preserve_minus_ordinary_ns_per_page"][name] = stats(
            [(pair[right] - pair[left]) / count for pair in case["micro_pairs"]])
    return case

def main():
    global PRIVATE
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    linux = args.linux_root.resolve()
    PRIVATE = args.output.resolve().parent
    os.umask(0o077)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    require(os.geteuid() != 0, "rootless execution required")
    require(run(["git", "-C", str(ROOT), "rev-parse", PIN + "^{tree}"], "frozen tree") == TREE,
            "wrong frozen tree")
    require(run(["git", "-C", str(ROOT), "rev-parse", RECOVERY_PIN + "^{tree}"], "recovery tree") == RECOVERY_TREE,
            "wrong recovery tree")
    require(run(["git", "-C", str(ROOT), "rev-parse", ATTRIBUTION_PIN + "^{tree}"], "attribution tree") == ATTRIBUTION_TREE,
            "wrong attribution tree")
    require(run(["git", "hash-object", str(ROOT / R112_REPORT)], "R112 evidence pin") == R112_REPORT_BLOB,
            "R112 evidence drift")
    prior_cases = json.loads((ROOT / R112_REPORT).read_text())["measurements"]["results"]["gcc-optimized"]["cases"]
    require(run(["git", "-C", str(ROOT), "rev-parse", CRC_PIN + "^{tree}"], "CRC freeze tree") == CRC_TREE,
            "wrong CRC freeze tree")
    require(run(["git", "hash-object", str(ROOT / R114_REPORT)], "R114 evidence pin") == R114_REPORT_BLOB,
            "R114 evidence drift")
    r114_cases = json.loads((ROOT / R114_REPORT).read_text())["measurements"]["results"]["gcc-optimized"]["cases"]
    for revision in (PIN, RECOVERY_PIN, ATTRIBUTION_PIN, CRC_PIN, "HEAD"):
        require(run(["git", "-C", str(ROOT), "rev-parse", revision + ":src/kernel"], "product subtree") == PRODUCT_TREE,
                "product subtree differs from freeze")
    require(not run(["git", "-C", str(ROOT), "status", "--porcelain"], "product clean"), "dirty checkout")
    require(not run(["git", "-C", str(ROOT), "diff", "--name-only", PIN, "--", "src/kernel"], "product drift"),
            "product differs from freeze")
    for relative, expected in PINS.items():
        require(run(["git", "hash-object", str(ROOT / relative)], "source pin " + relative) == expected,
                "source drift " + relative)
    adapter52 = load("round052-zswap-swapz-codec-verify")
    adapter56 = load("round056-codec-profile-verify")
    original_lzo = adapter56.verify_pristine_original(linux)
    original_lz4 = adapter52.original_lz4_wrapper(linux)
    original_files = set(adapter56.ORIGINAL_BLOBS) | {
        "crypto/lz4.c", "crypto/acompress.c", "mm/zswap.c", "mm/Kconfig"}
    original_hashes = {name: run(["git", "-C", str(linux), "hash-object", str(linux / name)], name)
                       for name in sorted(original_files)}
    for name, actual in original_hashes.items():
        require(run(["git", "-C", str(linux), "rev-parse", LINUX + ":" + name], "Linux blob") == actual,
                "Linux source drift")
    for name, anchor in (("zswap-direct-handoff.h", "SWAPZ_DIRECT_ZSWAP_ZSTD = 2,"),
                         ("zswap-import-codec.h", "#define SWAPZ_ZSWAP_IMPORT_LZO1X_CODEC 2U"),
                         ("zswap-import-codec.h", "#define SWAPZ_ZSWAP_IMPORT_LZ4_CODEC 1U")):
        require(anchor in (KERNEL / name).read_text(), "codec namespace drift")
    dm = (KERNEL / "dm-target.c").read_text()
    with tempfile.TemporaryDirectory(prefix="round111-codec-") as temporary:
        scratch = Path(temporary)
        adapter56.prepare_host_shim(scratch, linux, original_lzo)
        (scratch / "round052-original-crypto-lz4-extracted.inc").write_text(original_lz4)
        stats = block(dm, "struct swapz_delta64_stats {") + ";\n"
        ordinary = block(dm, "static void swapz_delta64_note_score(") + "\n" + block(dm, "static int swapz_compress_page(")
        (scratch / "ordinary-extracted.inc").write_text(stats + ordinary + "\n")
        # Pin only this diagnostic process and its children to one allowed CPU.
        # Baseline CPUID probe must execute before any SSE4.2-linked binary.
        require(platform.machine() == "x86_64", "existing diagnostic requires x86_64")
        allowed_cpus = os.sched_getaffinity(0)
        require(bool(allowed_cpus), "empty CPU affinity")
        os.sched_setaffinity(0, {min(allowed_cpus)})
        probe_source = scratch / "crc-cpu-probe.c"
        probe_source.write_text(
            '#include <stdio.h>\nint main(void) { __builtin_cpu_init(); '
            'puts(__builtin_cpu_supports("sse4.2") ? "supported" : "unsupported"); return 0; }\n')
        probe_binary = scratch / "crc-cpu-probe"
        run(["gcc", "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-mno-sse4.2",
             str(probe_source), "-o", str(probe_binary)], "baseline CPUID probe compile")
        probe = run([str(probe_binary)], "baseline CPUID probe")
        require(probe in ("supported", "unsupported"), "invalid CPUID probe")
        hardware_supported = probe == "supported"
        backends = ("software", "sse42") if hardware_supported else ("software",)
        results = {}
        execution_order = []
        crc_vectors = None
        for compiler, optimized in (("gcc", False), ("clang", False), ("gcc", True)):
            base_label = compiler + ("-optimized" if optimized else "-asan-ubsan")
            flags = ["-std=gnu11", "-Wall", "-Wextra", "-Werror", "-ffunction-sections", "-fdata-sections"]
            flags += ["-O3"] if optimized else ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
            common = [compiler, *flags, "-I", str(scratch), "-I", str(scratch / "host-shim"),
                      "-I", str(linux / "lib/lzo"), "-I", str(KERNEL)]
            sources = [(FIXTURE, ["-Wconversion", "-Wshadow"]),
                       (KERNEL / "engine.c", []), (KERNEL / "predictor.c", []),
                       (KERNEL / "predictor-sse2.c", ["-msse2"]),
                       (KERNEL / "predictor-avx2.c", ["-mavx2"]),
                       (KERNEL / "predictor-avx512.c", ["-mavx512f"]),
                       (linux / "lib/lzo/lzo1x_compress_safe.c", []),
                       (linux / "lib/lzo/lzo1x_decompress_safe.c", [])]
            objects = []
            for index, (source, extra) in enumerate(sources):
                obj = scratch / f"{base_label}-{index}.o"
                run([*common, *extra, "-c", str(source), "-o", str(obj)], base_label + "/" + source.name)
                objects.append(str(obj))
            # Exact common object bytes reused across CRC backends.
            common_hashes = [hashlib.sha256(Path(obj).read_bytes()).hexdigest() for obj in objects]
            binaries = {}
            for backend in backends:
                label = base_label + "-" + backend
                crc_flag = "-msse4.2" if backend == "sse42" else "-mno-sse4.2"
                crc_flags = [*common, "-Wconversion", "-Wshadow", crc_flag]
                macros = run([*crc_flags, "-dM", "-E", str(KERNEL / "codec.c")], label + "/macros")
                macro_enabled = bool(re.search(r"^#define __SSE4_2__ 1$", macros, re.M))
                require(macro_enabled == (backend == "sse42") and
                        not re.search(r"^#define __KERNEL__\b", macros, re.M), "CRC macro mismatch")
                crc_object = scratch / f"{label}-codec.o"
                run([*crc_flags, "-c", str(KERNEL / "codec.c"), "-o", str(crc_object)], label + "/codec.c")
                disassembly = run(["objdump", "-d", str(crc_object)], label + "/objdump")
                instructions = re.findall(r"^\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)+\s*(crc32[bwlq]?)\b",
                                          disassembly, re.M)
                require(bool(instructions) == (backend == "sse42"), "CRC object opcode mismatch")
                binary = scratch / label
                run([compiler, *flags, *objects, str(crc_object), "-Wl,--gc-sections",
                     "-llz4", "-o", str(binary)], label + "/link")
                binaries[backend] = binary
                results[label] = {
                    "status": "PASS", "compiler": run([compiler, "--version"], "compiler version").splitlines()[0],
                    "flags": flags, "crc_backend": backend, "codec_only_flag": crc_flag,
                    "sse42_macro": macro_enabled, "crc_instruction_count": len(instructions),
                    "crc_instruction_mnemonics": sorted(set(instructions)),
                    "codec_object_sha256": hashlib.sha256(crc_object.read_bytes()).hexdigest(),
                    "common_object_sha256": common_hashes, "cases": []}
            # AB for codec 1, BA for codec 2 (reverse initial order for Clang).
            # Separate binaries/processes, same host/CPU; not per-pair interleaving.
            for codec in (1, 2):
                order = backends[::-1] if ((codec == 2) != (compiler == "clang")) else backends
                for backend in order:
                    label = base_label + "-" + backend
                    execution_order.append([label, codec])
                    output = run([str(binaries[backend]), str(codec)], label + f"/codec-{codec}").splitlines()
                    require(len(output) == 9, "missing CRC oracle or case records")
                    oracle = json.loads(output[0])
                    require(oracle["crc_known"] == 0xe3069283 and oracle["crc_empty"] == 0 and
                            [row[:2] for row in oracle["crc_vectors"]] ==
                            [[offset, length] for offset in range(8) for length in CRC_LENGTHS],
                            "CRC oracle coverage")
                    require(all(len(row) == 3 and type(row[2]) is int and 0 <= row[2] <= 0xffffffff
                                for row in oracle["crc_vectors"]), "CRC oracle values")
                    if crc_vectors is None:
                        crc_vectors = oracle
                    require(oracle == crc_vectors, "CRC oracle backend/compiler disagreement")
                    cases = [summarize(json.loads(line)) for line in output[1:]]
                    require([(case["codec"], case["stratum"]) for case in cases] ==
                            [(codec, stratum) for stratum in range(-1, len(STRATA))],
                            "missing codec or stratum coverage")
                    results[label]["cases"].extend(cases)
        require(crc_vectors is not None, "no CRC oracle execution")
        # Cross-compiler, sanitized and optimized runs must agree on all non-timing evidence.
        stable_keys = ("pages", "eligible", "zero", "same", "over_cap", "unsupported_control",
                       "category_counts", "eligible_by_category", "payload_bytes", "ordinary_raw_pages",
                       "preserve_copy_bytes", "ordinary_raw_copy_bytes", "ordinary_actual_planner_bytes",
                       "size_bins", "fixed_class_model_bytes", "byte_exact", "page_sizes", "inverse_pages",
                       "stratum", "stratum_name", "page_crcs")
        for index, reference in enumerate(results["gcc-asan-ubsan-software"]["cases"]):
            for result in results.values():
                require(all(reference[key] == result["cases"][index][key] for key in stable_keys),
                        "compiler/optimization correctness disagreement")
        # Every R114 size/eligibility/packing field must match, not its timings.
        require(len(r114_cases) == 16, "R114 case count")
        for index, reference in enumerate(r114_cases):
            case = results["gcc-optimized-software"]["cases"][index]
            require(case["codec"] == reference["codec"] and all(
                case[key] == reference[key] for key in stable_keys if key != "page_crcs"),
                "R114 non-timing drift")
        # The shared corpus must reproduce R112 non-timing totals exactly.
        for reference in prior_cases:
            case = next(c for c in results["gcc-optimized-software"]["cases"]
                        if c["codec"] == reference["codec"] and c["stratum"] == -1)
            for key in ("pages", "eligible", "zero", "same", "over_cap", "unsupported_control",
                        "payload_bytes", "size_bins", "ordinary_raw_pages",
                        "ordinary_actual_planner_bytes", "fixed_class_model_bytes"):
                require(case[key] == reference[key], "R112 shared corpus drift: " + key)
            require(case["category_counts"][:-1] == reference["category_counts"] and
                    case["eligible_by_category"][:-1] == reference["eligible_by_category"], "R112 category drift")
            joined = sorted((row for c in results["gcc-optimized-software"]["cases"]
                             if c["codec"] == reference["codec"] and 0 <= c["stratum"] < 6
                             for row in c["page_sizes"]))
            require(joined == case["page_sizes"], "strata differ from shared page sizes")
        # Sanitized timings are explicitly not performance evidence.
        backend_comparison = []
        if hardware_supported:
            for software, hardware in zip(results["gcc-optimized-software"]["cases"],
                                          results["gcc-optimized-sse42"]["cases"]):
                if not software["eligible"]:
                    continue
                # Differences of separate-run medians, not cross-backend paired samples.
                comparison = {"codec": software["codec"], "stratum": software["stratum_name"]}
                for key in ("timing_ns_per_page_batch_statistics",
                            "paired_preserve_minus_ordinary_ns_per_page",
                            "micro_ns_per_page_batch_statistics",
                            "micro_paired_preserve_minus_ordinary_ns_per_page"):
                    comparison[key] = {
                        name: {"software": value["median"], "sse42": hardware[key][name]["median"]}
                        for name, value in software[key].items() if value is not None}
                backend_comparison.append(comparison)
        for backend in backends:
            for case in results["gcc-optimized-" + backend]["cases"]:
                if not case["eligible"]:
                    continue
                timing = case["timing_ns_per_page_batch_statistics"]
                print(f"backend={backend} codec={case['codec']} stratum={case['stratum_name']} "
                      f"write ordinary/preserve={timing['ordinary_write']['median']:.1f}/"
                      f"{timing['preserve_write']['median']:.1f} "
                      f"read ordinary/preserve={timing['ordinary_read']['median']:.1f}/"
                      f"{timing['preserve_read']['median']:.1f} ns/page")
        report = {"frozen": PIN, "tree": TREE, "source_commit": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], "source HEAD"),
                  "recovery_frozen": RECOVERY_PIN, "recovery_tree": RECOVERY_TREE,
                  "attribution_frozen": ATTRIBUTION_PIN, "attribution_tree": ATTRIBUTION_TREE,
                  "r112_reference_blob": R112_REPORT_BLOB, "r112_shared_non_timing_match": True,
                  "crc_frozen": CRC_PIN, "crc_tree": CRC_TREE, "r114_reference_blob": R114_REPORT_BLOB,
                  "r114_non_timing_match": True, "cpu_probe": probe, "hardware_status": "PASS" if hardware_supported else "NOT_RUN_UNSUPPORTED",
                  "affinity": "one allowed logical CPU, inherited by probe and all binaries",
                  "execution_order": execution_order, "crc_oracle": crc_vectors,
                  "page_crcs_columns": ["logical_id", "page_crc", "original_crc", "ordinary_crc", "preserved_or_fallback_crc"],
                  "backend_comparison": backend_comparison,
                  "backend_comparison_method": "separate binaries, alternating backend order by codec; differences of medians not cross-backend paired samples; no additive attribution or kernel dispatch equivalence",
                  "product_subtree": PRODUCT_TREE,
                  "linux": LINUX, "linux_blobs": original_hashes, "product_blobs": PINS,
                  "machine": platform.machine(), "processor": platform.processor(),
                  "cpu_count": os.cpu_count(), "lz4_backend": "host liblz4, pinned Linux wrapper",
                  "predictor_backend": "scalar", "lzo_backend": "pinned Linux C conservative unaligned shim",
                  "pair_order": "AB/BA alternating", "timing": "thread CPU ns, batch totals divided by eligible pages",
                  "instrumentation": "ordinary verbatim production monotonic wall-clock calls and stats included; preserve has no such calls; both compute and verify CRC; original source generation, packing and final memcmp outside timed regions; not an isolated pure-codec delta",
                  "packing_model": "fixed class 4/8/16 KiB next-fit, max64, raw separate; not lower IO",
                  "category_order": STRATA, "page_sizes_columns": ["logical_id", "original_bytes", "ordinary_bytes", "eligible"],
                  "micro_order": MICRO_NAMES, "micro_design": "independent alternating forward/reverse batches; same selected IDs, actual per-arm lengths; inverse subset denominator and selection loop included; clock-score proxy is two monotonic calls and actual score note with precomputed score; no timer subtraction, no additive decomposition",
                  "corpus": "R112 192 shared unchanged; additional 32 synthetic repeated 512-byte patterns; content strata not residency or temperature",
                  "size_bins_upper_bytes": [512, 1024, 2048, 3568, 4096],
                  "auth": 0, "phase_a": "BLOCKED", "compressed_handoff": False,
                  "forced_raw": False, "import": False, "physical": "NO_GO", "results": results}
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        # Bounded structured evidence in the job log as well as the private artifact.
        # Only emit after all supported mandatory executions and equality gates passed.
        meta = {key: value for key, value in report.items() if key != "results"}
        meta["compiler_lanes"] = {name: {key: value for key, value in lane.items() if key != "cases"}
                                  for name, lane in results.items()}
        print("ROUND115_CODEC_META " + json.dumps(meta, separators=(",", ":")), flush=True)
        for name, lane in results.items():
            for case in lane["cases"]:
                print("ROUND115_CODEC_CASE " + json.dumps({"lane": name, "case": case}, separators=(",", ":")), flush=True)
        print("Legend: paired eligible generated pages; payload bytes exclude packing; ns/page is batch CPU.")
        print("Interpretation: compare write, read and payload independently; fixed-class packing is a model.")
        print("Evidence -> Goal implication -> Verdict: byte-exact host diagnostic -> quantify codec trade-offs -> diagnostic-only.")

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit("ROUND111_CODEC_FIRST_ERROR " + str(error)) from None
