#!/usr/bin/env python3
"""R092 exact original-MM/broker module boundary; rootless ABI shim, not kernel runtime."""
import argparse
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
R091 = runpy.run_path(str(ROOT / "tests/tools/round091-original-mm-eviction-verify.py"))
R090 = R091["PRIOR"]
R089 = R091["EARLIER"]
require, checked, run = (R089[name] for name in ("require", "checked", "run"))
verify_pins, blob, ordered = (R089[name] for name in ("verify_pins", "blob", "ordered"))
BASELINE = "2499405464110e6a97f054db5527de54b8aafb3a"
PATCH = ROOT / "tests/tools/round092-original-module-boundary.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round092-original-module-boundary.c"
SHIM = ROOT / "tests/runtime/native/fixtures/round092-module-shim.h"
INPUTS = {
    str(PATCH.relative_to(ROOT)): "62db468c14f23b59e7adaae65a11dcb9969f02b3",
    str(FIXTURE.relative_to(ROOT)): "47698af8e60fe088de3fb5ab6f7725412816cea0",
    str(SHIM.relative_to(ROOT)): "79623955e77b0b35d17bd14f322412d8ee202c84",
    "tests/tools/round089-original-mm-carrier.patch": "059d1bf29cf4990e22a2f608d5d552abeec3a8d1",
    "tests/tools/round090-original-mm-lifetime.patch": "337f7ff29e72d955251de0c54a9349f20c2586ec",
    "tests/tools/round091-original-mm-eviction.patch": "94bb74549c54a614406b71f28a9e8e8c22527d6a",
    "tests/tools/round089-original-mm-carrier-verify.py": "dce6b2417ea33b598eaf00accf7888730b2e4a54",
    "tests/tools/round090-original-mm-lifetime-verify.py": "f0c32cc54fca7b875f80a2baf2906adaa7f03834",
    "tests/tools/round091-original-mm-eviction-verify.py": "1fea77c85ded3d08806b8626401b777b339c3089",
}
FROZEN = {
    "src/kernel/zswap-original-ticket.c": "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    "src/kernel/zswap-original-ticket.h": "0630f9e4fad26458ed0778ca6ae040150e28f078",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/dm-target.c": "6a98df348a2ffef12d8b51f857a12f7b00738fc6",
}
POST = dict(R091["POST"])
POST.update(FROZEN)
POST.update({
    "mm/zswap.c": "98a8a6a66858204b61875ad9b2e8cfb0ecf8980a",
    "include/linux/swapz_mm_carrier.h": "da1e7a367f4f5d16dc6854f33064631251acb153",
    "src/kernel/zswap-original-ticket.c": "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
    "src/kernel/zswap-original-ticket.h": "6afac83a0655e532ce1ef9b8f290a367e8aabfce",
})
EXPORTS = {
    "swapz_mm_register_provider", "swapz_mm_unregister_provider", "swapz_mm_candidate_get",
    "swapz_ticket_put", "swapz_ticket_view", "swapz_ticket_broker_put",
    "swapz_ticket_broker_try_get", "swapz_ticket_claim_under_queue_lock",
}


def frozen_file(path):
    result = subprocess.run(["git", "show", BASELINE + ":" + path], cwd=ROOT,
                            capture_output=True, check=False, timeout=60)
    require(result.returncode == 0, "frozen git show " + path)
    require(blob(result.stdout) == FROZEN[path], "frozen blob " + path)
    return result.stdout


def function(source, name):
    escaped = re.escape(name)
    matches = list(re.finditer(r"(?m)^(?:static )?(?:bool|int|void) " +
                               r"(?:" + escaped + r"|\(" + escaped + r"\))" +
                               r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "actual function anchor " + name)
    depth = 1
    for index in range(matches[0].end(), len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[matches[0].start():index + 1] + "\n"
    raise RuntimeError("unclosed function " + name)


def replace_once(source, old, replacement):
    require(source.count(old) == 1, "nonunique mutation " + old)
    return source.replace(old, replacement, 1)


def source_contract(staged, scratch):
    source = (staged / "mm/zswap.c").read_text()
    header = (staged / "include/linux/swapz_mm_carrier.h").read_text()
    broker = (staged / "src/kernel/zswap-original-ticket.c").read_text()
    dm = (staged / "src/kernel/dm-target.c").read_text()
    mm_exports = re.findall(r"EXPORT_SYMBOL_GPL\((swapz_mm_\w+)\);", source)
    broker_exports = re.findall(r"EXPORT_SYMBOL_GPL\((swapz_ticket_\w+)\);", broker)
    calls = set(re.findall(r"\b(swapz_(?:mm|ticket)_\w+)\s*\(", dm))
    require(len(mm_exports + broker_exports) == len(EXPORTS) and
            set(mm_exports + broker_exports) == EXPORTS == calls,
            "actual frozen consumer export inventory")
    require("#if defined(__KERNEL__) && defined(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST)\n"
            "/* Single built-in broker" in broker and
            "#ifdef SWAPZ_ORIGINAL_TICKET_TEST" in broker and
            "#ifdef CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST" in source,
            "guarded kernel-only exports")
    require(not re.search(r"EXPORT_SYMBOL\((?:swapz_mm|swapz_ticket)_", source + broker),
            "unrestricted export")
    names = ("swapz_mm_register_provider", "swapz_mm_unregister_provider",
             "swapz_mm_eligible", "swapz_mm_route_try",
             "swapz_mm_candidate_get", "swapz_mm_release_workfn")
    parts = {name: function(source, name) for name in names}
    ordered(parts[names[0]], ["mutex_lock", "WRITE_ONCE(swapz_mm_provider_owner, owner)",
                             "rcu_assign_pointer(swapz_mm_provider, provider)", "mutex_unlock"],
            "provider publish")
    require("try_module_get" not in parts[names[0]], "registration self pin")
    ordered(parts[names[1]], ["rcu_assign_pointer(swapz_mm_provider, NULL)",
                             "synchronize_rcu()", "WRITE_ONCE(swapz_mm_provider_owner, NULL)"],
            "unpublish before owner clear")
    ordered(parts[names[2]], ["rcu_read_lock", "rcu_dereference", "try_module_get(owner)",
                             "provider->eligible", "module_put(owner)", "rcu_read_unlock"],
            "callback pin")
    ordered(parts[names[3]], ["rcu_read_lock", "try_module_get(owner)", "provider->lookup",
                             "swapz_ticket_broker_try_get", "*owner_out = owner",
                             "module_put(owner)", "rcu_read_unlock"], "route cap pin")
    ordered(parts[names[4]], ["rcu_read_lock", "rcu_dereference", "try_module_get(owner)",
                             "swapz_ticket_retain", "out->provider_owner = owner",
                             "rcu_read_unlock"], "candidate pin")
    ordered(parts[names[5]], ["synchronize_rcu", "swapz_ticket_put", "swapz_ticket_broker_put",
                             "module_put(owner)", "atomic_set_release"], "carrier release order")
    ordered(function(broker, "swapz_ticket_retain"),
            ["try_module_get(ref->provider_owner)", "ticket_lock", "*out = *ref",
             "ticket_unlock", "module_put(ref->provider_owner)"], "retain pin")
    ordered(function(broker, "swapz_ticket_put"), ["owner = ref->provider_owner",
            "*ref =", "ticket_unlock", "module_put(owner)"], "put outside lock")
    ordered(function(source, "swapz_mm_preerase"), ["swapz_mm_route_try(",
            "&carrier->provider_owner", "zs_obj_read_sg_begin", "zs_obj_read_sg_end",
            "swapz_mm_eviction_key", "swapz_ticket_reserve", "swapz_ticket_seal"],
            "unchanged eligible source provenance")
    require("(swapz_mm_register_provider)((provider), THIS_MODULE)" in header,
            "caller module owner binding")
    for include in ("#include <linux/blkdev.h>\n", "#include <linux/mm_types.h>\n",
                    "#include <linux/module.h>\n"):
        header = replace_once(header, include, "")
    (scratch / "r092-staged-carrier.h").write_text(header)
    return parts, broker


def host(staged, scratch, evidence, report):
    parts, broker = source_contract(staged, scratch)
    baseline = "\n".join(parts.values())
    # Each negative changes real extracted/staged code; compile diagnostics are not kills.
    def mutate_part(name, old, new):
        return "\n".join(replace_once(value, old, new) if key == name else value
                         for key, value in parts.items())
    variants = [
        ("baseline", baseline, broker, None),
        ("no_callback_pin", mutate_part("swapz_mm_eligible", "if (try_module_get(owner))",
                                        "if (true)"), broker, "callback_without_module_pin"),
        ("no_candidate_pin", mutate_part("swapz_mm_candidate_get", "if (try_module_get(owner))",
                                         "if (true)"), broker, "candidate_pin_after_carrier_put"),
        ("no_carrier_put", mutate_part("swapz_mm_release_workfn", "module_put(owner);",
                                       "(void)owner;"), broker, "candidate_pin_after_carrier_put"),
        ("no_retain_pin", baseline, replace_once(broker, "if (!try_module_get(ref->provider_owner))",
                                                 "if (false)"), "duplicate_pin"),
        ("no_ticket_put", baseline, replace_once(broker, "module_put(owner);", "(void)owner;"),
         "first_put"),
    ]
    kernel = staged / "src/kernel"
    probe = scratch / "probe.c"
    probe.write_text("int main(void) { return 0; }\n")
    for compiler in ("gcc", "clang"):
        standard = next((value for value in ("c23", "c2x")
                         if run([compiler, "-std=" + value, "-fsyntax-only", str(probe)]).returncode == 0), None)
        require(standard, "missing C23 compiler " + compiler)
        result = {"compiler": checked([compiler, "--version"]).splitlines()[0],
                  "standard": standard, "status": "IN_PROGRESS", "mutants": {}}
        report[compiler] = result
        for name, funcs, actual_broker, witness in variants:
            (scratch / "r092-staged-functions.h").write_text(funcs)
            source = scratch / "broker.c"
            source.write_text(actual_broker)
            binary = scratch / (compiler + "-" + name)
            command = [compiler, "-std=" + standard, "-Wall", "-Wextra", "-Werror",
                       "-Wconversion", "-Wsign-conversion", "-Wshadow", "-Wstrict-prototypes",
                       "-pedantic", "-D_POSIX_C_SOURCE=200809L", "-pthread", "-no-pie",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       "-fno-omit-frame-pointer", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
                       "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-include", str(SHIM),
                       "-I", str(kernel), "-I", str(scratch), str(FIXTURE), str(source),
                       str(kernel / "codec.c"), "-o", str(binary)]
            compilation = run(command, timeout=60)
            (evidence / (compiler + "-" + name + "-compile.log")).write_text(
                compilation.stdout + compilation.stderr)
            diagnostic = next((line for line in compilation.stderr.splitlines()
                               if "error:" in line or "fatal" in line), "no classified diagnostic")
            diagnostic = re.sub(r"(?<!\w)/(?:[^\s:]+/)*([^\s:]+)", r"\1", diagnostic)
            require(compilation.returncode == 0, compiler + " " + name + " compile " + diagnostic[:180])
            execution = run([str(binary)], timeout=30)
            (evidence / (compiler + "-" + name + "-run.log")).write_text(
                execution.stdout + execution.stderr)
            if witness is None:
                match = re.fullmatch(r"PASS_HOST_ONLY R092 checks=(\d+) lifecycle_races=2 "
                                     r"carrier=(\d+) ref=(\d+) broker=(\d+)\n", execution.stdout)
                require(execution.returncode == 0 and not execution.stderr and match,
                        compiler + " baseline " + execution.stderr[:160])
                require(int(match[1]) >= 35, "baseline check count")
                result.update(checks=int(match[1]), lifecycle_races=2, carrier_bytes=int(match[2]),
                              ref_bytes=int(match[3]), broker_bytes=int(match[4]))
                print(compiler + " " + execution.stdout.strip(), flush=True)
            else:
                require(execution.returncode == 77 and "R092_FIRST_ERROR " + witness in execution.stderr,
                        compiler + "/" + name + " not semantic kill")
                result["mutants"][name] = "KILLED"
                print(compiler + " semantic kill " + name, flush=True)
        result["status"] = "PASS"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"status": "IN_PROGRESS", "source_authentication": 0, "phase_a": "BLOCKED",
              "direct_handoff": "DISABLED", "forced_raw": "DISABLED", "import": 0,
              "kernel_compile": "NOT_RUN", "module_link": "NOT_RUN", "native": "NOT_RUN",
              "physical": "NOT_RUN"}
    try:
        require(checked(["git", "rev-parse", "HEAD"], args.linux).strip() == R089["PIN"],
                "original Linux commit")
        require(not checked(["git", "status", "--porcelain", "--untracked-files=all"], args.linux),
                "dirty original Linux")
        verify_pins(ROOT, INPUTS)
        verify_pins(args.linux, R089["PRISTINE"])
        with tempfile.TemporaryDirectory(prefix="r092-a11-") as temporary:
            scratch = Path(temporary)
            staged = scratch / "stage"
            for path in R089["PRISTINE"]:
                destination = staged / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((args.linux / path).read_bytes())
            for path in FROZEN:
                destination = staged / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(frozen_file(path))
            for patch, pins, label in (
                (R089["PATCH"], R089["POST"], "R089"),
                (R090["OVERLAY"], R090["POST"], "R090"),
                (R091["PATCH"], R091["POST"], "R091"),
                (PATCH, POST, "R092"),
            ):
                checked(["git", "apply", "--unidiff-zero", "--check", str(patch)], staged)
                checked(["git", "apply", "--unidiff-zero", str(patch)], staged)
                verify_pins(staged, pins)
                report[label + "_postimage_pins"] = len(pins)
            require(run(["git", "apply", "--unidiff-zero", "--check", str(PATCH)], staged).returncode != 0,
                    "duplicate R092 overlay accepted")
            checked(["git", "apply", "--unidiff-zero", "--reverse", "--check", str(PATCH)], staged)
            for path in R089["PRISTINE"].keys() - POST.keys():
                require(blob((staged / path).read_bytes()) == R089["PRISTINE"][path],
                        "unintended source drift " + path)
            report["stage"] = "PASS"
            report["exports"] = sorted(EXPORTS)
            report["host"] = {}
            host(staged, scratch, args.output, report["host"])
        report["status"] = "PASS_HOST_ONLY"
        print("PASS_HOST_ONLY R092 actual module boundary helpers; kernel/modpost NOT_RUN AUTH0")
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "FAIL"
        report["first_error"] = str(error)[:240]
        print("R092_AGENT11_FIRST_ERROR " + report["first_error"], file=sys.stderr)
        return 2
    finally:
        (args.output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
