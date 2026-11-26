#!/usr/bin/env python3
"""R098 A11 actual producer/core events + scope; no R097 test replay/native build."""
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
PINS = {
    "src/kernel/native-observation-adapter.c": "f94371ff06ba8296e292ccec9e28dd230ded5bbd",
    "src/kernel/native-observation-adapter.h": "27f1140f4dcc510662fbb1f4519f7be4236e1b10",
    "src/kernel/native-observation-owner.c": "69bd5c018bf4cc502c14c1c3f1cc02c1959c1673",
    "src/kernel/native-observation-owner.h": "e266f0e0c2dec0d399cc863da329e44f38b0c536",
    "tests/runtime/native/fixtures/native-observation-owner-host-model.h": "47042c1c9f388f29e2989492c15ef479573b1019",
    "tests/runtime/native/fixtures/native-observation-adapter-host-model.h": "3dac25d2edb2d7475af3231c98af753f09e4063f",
    "tests/tools/native-observation-export.py": "0c97be31dce2d7a049335189e114b2c73cd0074c",
    "tests/tools/native-observation-current-export.py": "bf653586a76d507d2d70f04292faff3df8a00f3c",
    "tests/tools/round088-original-dm-selected-clone.patch": "5c8587c3d8205fc1ab346011c092601f2113a45a",
}
MM_PATCH = "tests/tools/round098-original-mm-scope-events.patch"
CORE_PATCH = "tests/tools/round098-original-dm-upper-observation.patch"
DM = "drivers/md/dm.c"
DM_HEADER = "drivers/md/dm-core.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round098-mm-scope-events.c"

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def command(args, cwd=ROOT, timeout=90):
    return subprocess.run(args, cwd=cwd, capture_output=True, timeout=timeout, check=False)

def checked(args, cwd=ROOT):
    result = command(args, cwd)
    require(result.returncode == 0, "command failed: " + str(args[0]) + " " +
            result.stderr.decode(errors="replace").split("\n")[0][:200])
    return result.stdout

def stage(directory, linux):
    # Only import the exact previous stage machinery, never run its corpus.
    path = ROOT / "tests/tools/round097-mm-producer-verify.py"
    require(checked(["git", "hash-object", str(path)]).decode().strip() ==
            "dad98ce49b64ce7bb3f6d48ba4a9395299a2da5e", "R097 staging verifier pin")
    spec = importlib.util.spec_from_file_location("r097_stage", path)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    previous.stage(directory, linux, {})
    pin = previous.pin
    for path, sha in PINS.items():
        dest = directory / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(checked(["git", "show", FREEZE + ":" + path]))
        pin(dest, sha)
    (directory / DM).parent.mkdir(parents=True)
    (directory / DM).write_bytes(pin(linux / DM, "1881d86111fb2e655893ad898cf21b88f0e4e7f3"))
    (directory / DM_HEADER).write_bytes(pin(linux / DM_HEADER, "a3b8ad6e1c42def591694cb304994c2b8d5ca301"))
    apply = ["git", "apply", "--unidiff-zero", "--whitespace=error"]
    args = [str(directory / "tests/tools/round088-original-dm-selected-clone.patch")]
    checked(apply + ["--check"] + args, directory)
    checked(apply + args, directory)
    pin(directory / DM, "e51af0d14465e92323970a84c1d62df3a8eb61c3")
    for patch, expected in (
        (MM_PATCH, "3832b6aa76b783f3790b869cf40512b114d66cd6"),
        (CORE_PATCH, "5b0b0a3582b16e54046f1f11355e6814c9ca4e1f"),
    ):
        pin(ROOT / patch, expected)
        args = [str(ROOT / patch)]
        checked(apply + ["--check"] + args, directory)
        checked(apply + args, directory)
        checked(apply + ["--reverse", "--check"] + args, directory)
    for path, sha in (
        (previous.MM, "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0"),
        (previous.CARRIER, "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a"),
        (previous.PAGE_IO, "08c11d2f9a16a322093b305afa10ba011f67fc2b"),
        (DM, "f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b"),
        (DM_HEADER, "a010598cb4e884a78f06ab66ab4488a1a7f9c418"),
    ):
        pin(directory / path, sha)
    mm = (directory / previous.MM).read_text()
    core = (directory / DM).read_text()
    fn = previous.function
    ordered = previous.ordered
    # These are source inventory/ordering checks, not actual native execution.
    ordered(fn(mm, "swapz_mm_capture"), ["swapz_mm_eligible(", "entry->original_cookie =",
                                         "entry->original_scope = scope_identity"])
    ordered(fn(mm, "swapz_mm_route_try"), ["rcu_read_lock()", "rcu_dereference(swapz_mm_scope)",
        "scope->identity == scope_identity", "swapz_mm_scope_matches(", "swapz_ticket_broker_try_get("])
    ordered(fn(mm, "swapz_mm_preerase"), ["entry->original_scope", "swapz_mm_route_try(",
        "zs_obj_read_sg_begin(", "zs_obj_read_sg_end(", "swapz_ticket_seal(",
        "swapz_mm_observation_capture("])
    ordered(fn(mm, "swapz_mm_release_workfn"), ["swapz_ticket_put(", "swapz_ticket_broker_put(",
        "module_put(owner)", "swapz_mm_observation_release(", "atomic_set_release("])
    ordered(fn(core, "dm_swapz_trial_observation_origin"), ["rcu_access_pointer(bio->bi_swapz_original)",
        "swapz_trial_observation_mint()", "io->swapz_observation_operation = op_id"])
    ordered(fn(core, "__dm_io_complete"), ["dm_swapz_original_observation_endio(io, true",
        "dm_handle_requeue(", "if (!requeued", "dm_swapz_original_observation_endio(io, false",
        "free_io(io)", "bio_endio(bio)"])
    header = (directory / previous.CARRIER).read_text()
    types = ""
    for name in ("swapz_mm_route", "swapz_mm_trial_scope", "swapz_mm_carrier"):
        match = re.search(r"(?ms)^struct " + name + r" \{.*?^\};", header)
        require(match is not None, "type " + name)
        types += match[0] + "\n"
    (directory / "r098-types.h").write_text(types)
    declarations = mm[mm.index("static DEFINE_MUTEX(swapz_mm_scope_lock)"):
                      mm.index("#else\nstatic const struct swapz_mm_trial_scope swapz_mm_scope;")]
    names = ("swapz_mm_scope_matches", "swapz_mm_scope_valid", "swapz_mm_trial_scope_publish",
             "swapz_mm_trial_scope_revoke", "swapz_mm_trial_scope_matches_route",
             "swapz_mm_trial_scope_matches_origin", "swapz_mm_capture_permitted", "swapz_mm_observation_capture",
             "swapz_mm_observation_bind", "swapz_mm_observation_endio",
             "swapz_mm_observation_release", "swapz_mm_candidate_get",
             "swapz_mm_candidate_observation")
    # function() matches definition, not declaration; core helper has one definition.
    extracted = declarations + "\n".join(fn(mm, name) for name in names) + \
        fn(core, "dm_swapz_original_observation_endio")
    (directory / "r098-extracted.h").write_text(extracted)
    return previous

def exercise(directory, output, source, previous):
    kernel = directory / "src/kernel"
    fixtures = directory / "tests/runtime/native/fixtures"
    includes = directory / "include"
    for subdir, headers in (("linux", "types atomic rcupdate build_bug limits string export kernel mutex slab vmalloc"),
                            ("crypto", "sha2")):
        dest = includes / subdir
        dest.mkdir(parents=True, exist_ok=True)
        for name in headers.split():
            (dest / (name + ".h")).write_text('#include "native-observation-owner-host-model.h"\n')
    common = ["-std=c2x", "-D_DEFAULT_SOURCE", "-D_POSIX_C_SOURCE=200809L",
              "-DSWAPZ_NATIVE_OBSERVATION_ADAPTER", "-DSWAPZ_TRIAL_OBSERVATION",
              "-DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST", "-DSWAPZ_ORIGINAL_TICKET_TEST=1",
              "-DSWAPZ_TICKET_MODULE_HOST_TEST=1", "-DSWAPZ_TICKET_OWNER_HOST_TEST=1",
              '-DSWAPZ_OBSERVATION_BUILD_SOURCE="' + source + '"',
              "-O2", "-g", "-Wall", "-Wextra", "-Wconversion", "-Wsign-conversion", "-Wshadow",
              "-Wpedantic", "-Werror", "-fsanitize=address,undefined",
              "-fno-omit-frame-pointer", "-fno-pie", "-pthread",
              "-I" + str(includes), "-I" + str(kernel), "-I" + str(fixtures), "-I" + str(directory)]
    scope = dict(source=source, mapping_source="ff972661a75ca7f8c3c0458c3feb8b603c185eb8",
        linux_source=previous.LINUX, kernel_sha256="1"*64, module_sha256="2"*64,
        workload_sha256="3"*64, run_nonce="4"*32, target="5"*32, session=11, epoch=12,
        target_epoch=13, registration_epoch=14, first_logical=7, page_count=2, profile="M3568")
    parser = directory / "tests/tools/native-observation-current-export.py"
    result = {}
    for compiler in ("gcc", "clang"):
        broker = directory / (compiler + "-broker.o")
        build = command([compiler, *common, "-include", str(directory / previous.SHIM),
            "-c", str(directory / previous.BROKER), "-o", str(broker)])
        (output / (compiler + "-broker.log")).write_bytes(build.stdout + build.stderr)
        require(build.returncode == 0, compiler + " broker compile " +
                next((line for line in build.stderr.decode(errors="replace").splitlines()
                      if "error:" in line), "unknown")[:200])
        binary = directory / (compiler + "-producer")
        build = command([compiler, *common, "-no-pie", str(kernel / "native-observation-adapter.c"),
            str(kernel / "native-observation-owner.c"), str(kernel / "codec.c"), str(FIXTURE),
            str(broker), "-lcrypto", "-o", str(binary)])
        (output / (compiler + "-compile.log")).write_bytes(build.stdout + build.stderr)
        require(build.returncode == 0, compiler + " compile " +
                next((line for line in build.stderr.decode(errors="replace").splitlines()
                      if "error:" in line), "unknown")[:200])
        result[compiler] = {}
        for mode in ("drop", "bound"):
            wire = directory / (compiler + "-" + mode + ".wire")
            execution = subprocess.run([str(binary), mode, str(wire)], capture_output=True,
                timeout=30, check=False, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                                            "UBSAN_OPTIONS": "halt_on_error=1"})
            (output / (compiler + "-" + mode + ".log")).write_bytes(execution.stdout + execution.stderr)
            match = re.fullmatch(rb"R098_A11_HOST_ONLY mode=" + mode.encode() + rb" checks=(\d+)\n", execution.stdout)
            require(execution.returncode == 0 and not execution.stderr and match,
                    compiler + "/" + mode + " " + execution.stderr.decode(errors="replace")[:160])
            raw = wire.read_bytes()
            count = struct.unpack_from("<Q", raw, 80)[0]
            loss = struct.unpack_from("<I", raw, len(raw)-8)[0]
            require(loss == 0, compiler + "/" + mode + " actual recorder loss")
            events = [struct.unpack_from("<I", raw, 104 + i*296 + 104)[0] for i in range(count)]
            expected = [1, 5, 26, 21, 3, 4, 22, 18, 19, 27] if mode == "drop" else [1, 5, 2, 19, 21, 3, 4, 22, 18, 19, 27]
            require(events == expected, compiler + "/" + mode + " actual wire event sequence " + str(events))
            parsed = subprocess.run([sys.executable, "-B", str(parser), source, json.dumps(scope)],
                input=raw, capture_output=True, timeout=15, check=False)
            (output / (compiler + "-" + mode + "-parser.json")).write_bytes(parsed.stdout)
            report = json.loads(parsed.stdout)
            if mode == "drop":
                require(parsed.returncode == 0 and report["status"] == "CONSISTENT_RECORDER_OBSERVATIONS_ONLY",
                        "offline drop " + str(report))
            else:
                require(parsed.returncode == 2 and report["reason"] == "upper_endio",
                        "offline incomplete bound " + str(report))
            require(not report["source_mapped_authenticated"], "unexpected AUTH")
            result[compiler][mode] = dict(checks=int(match[1]), records=count, loss=loss, parser=report["status"])
            print(compiler, execution.stdout.decode().strip(), "records", count, "loss", loss,
                  "parser", report["status"], flush=True)
    return result

def main():
    linux = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = checked(["git", "rev-parse", "HEAD"]).decode().strip()
    report = dict(source=source, freeze=FREEZE, status="FAIL", first_error=None,
                  auth=0, phase_a="BLOCKED", native="NOT_RUN", physical="NOT_RUN")
    try:
        with tempfile.TemporaryDirectory(prefix="r098-a11-") as temporary:
            directory = Path(temporary)
            previous = stage(directory, linux)
            report["stage"] = "PASS"
            report["host"] = exercise(directory, output, source, previous)
        report["status"] = "PASS_ACTUAL_RECORDER_HOST_ONLY"
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["first_error"] = str(error)[:240]
        print("R098_A11_FIRST_ERROR", report["first_error"], file=sys.stderr)
        return 2
    finally:
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")

if __name__ == "__main__":
    sys.exit(main())
