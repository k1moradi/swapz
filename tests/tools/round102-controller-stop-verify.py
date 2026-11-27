#!/usr/bin/env python3
"""R102 A3: frozen exact stage, actual stop functions, changed objects only."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TARGET = "src/kernel/dm-target.c"
TARGET_PIN = "087bec323ad59f365d77d3beaf1aa52907cfcfce"
CONTROLLER = "native-observation-controller"
CONTROLLER_PINS = {CONTROLLER + ".c": "daa9bfcb321b2cc378994717a12f87a2c67c9b28",
                   CONTROLLER + ".h": "5dc62a0c7c3abc3999b8e16836a84bdbc2d8e061"}
FIXTURE = "tests/runtime/native/fixtures/round102-controller-stop.c"
FIXTURE_PIN = "af049d5dbab32a1a5b62ed4b64e2a77242466445"
STAGE = "tests/tools/round098-smp-directed-native-compile-verify.py"
STAGE_PIN = "96e6750971c182dfe87e6e57eac048c7c3a529b6"
PATCHES = (
    ("round098-original-mm-scope-events.patch", "3832b6aa76b783f3790b869cf40512b114d66cd6", {
        "mm/zswap.c": "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0",
        "include/linux/swapz_mm_carrier.h": "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a"}),
    ("round098-original-dm-upper-observation.patch", "5b0b0a3582b16e54046f1f11355e6814c9ca4e1f", {
        "drivers/md/dm.c": "f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b",
        "drivers/md/dm-core.h": "a010598cb4e884a78f06ab66ab4488a1a7f9c418"}),
    ("round101-original-mm-retirement.patch", "4d34b0d771789c09967b38fdf84b0f2b6513cd60", {
        "mm/zswap.c": "fcb2f7487cb7ed02ae8ca9a8d486909f721a2ef6",
        "include/linux/swapz_mm_carrier.h": "f50911d4c1ff7f87b502cec042b90968ba3a282f",
        "src/kernel/zswap-original-ticket.c": "e605bb0b8fbf5e6411a4d5d6182cab1a44d48bea",
        "src/kernel/zswap-original-broker-owner.inc": "a6a025b1d56513919ac83f4367e9c306fa12c933",
        "src/kernel/zswap-original-ticket.h": "6c79e41cb18082b925311bf62d0cfbed45a9e53b"}),
)
R101_PRE = {
    "mm/zswap.c": "cad0d9ba05cd614b95b335ed0c7d70d9e69d00f0",
    "include/linux/swapz_mm_carrier.h": "5e11fe42a9dce147cdaf7f30c43b1c8b6feff59a",
    "src/kernel/zswap-original-ticket.c": "70109f2c2ce9f60681649bd4807382248d0a41a2",
    "src/kernel/zswap-original-broker-owner.inc": "278a93a3fd3fd260444aebc55d4a87112e56f704",
    "src/kernel/zswap-original-ticket.h": "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea",
}

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)

def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def frozen(relative, expected, destination):
    data = git("show", FREEZE + ":" + relative)
    require(blob(data) == expected, "frozen input " + relative)
    destination.write_bytes(data)

def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:bool|int|void) " + name +
                              r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    return source[matches[0].start():source.index("\n}", matches[0].end()) + 2] + "\n"

def ordered(source, *anchors):
    offsets = [source.index(anchor) for anchor in anchors]
    require(offsets == sorted(set(offsets)), "ordering: " + repr(anchors))

def host(stage, state, evidence, scratch, source, controller):
    stop = function(source, "swapz_scope_stop_capture")
    ordered(stop, "spin_lock_irqsave", "identity = ctx->original_scope.identity",
            "ctx->original_scope_capture_stopped = true", "spin_unlock_irqrestore",
            "swapz_trial_controller_stop_capture(identity)", "swapz_scope_observe_invalid")
    require("swapz_mm_trial_scope_revoke" not in controller and
            "swapz_trial_observation_start" not in controller, "unsupported admission/revocation")
    drain = function(source, "swapz_drain")
    ordered(drain, "swapz_scope_stop_capture(ctx)", "WRITE_ONCE(ctx->accepting, false)",
            "swapz_round090_unpublish_target(ctx)", "flush_work(&ctx->original_release_work)",
            "swapz_scope_external_join_missing(ctx)", "queue_work(system_unbound_wq, &ctx->original_teardown_work)")
    resume = function(source, "swapz_resume")
    ordered(resume, "WRITE_ONCE(ctx->accepting, true)", "!swapz_scope_external_join_missing(ctx)",
            "queue_work(system_unbound_wq, &ctx->original_setup_work)")
    dtr = function(source, "swapz_dtr")
    ordered(dtr, "swapz_drain(ti)", "!swapz_scope_external_join_missing(ctx)",
            "swapz_round097_retire_target_records(ctx)", "swapz_round096_target_can_free(ctx, false)",
            "swapz_free(ctx)")
    require("!ctx->original_scope.identity" in function(source, "swapz_round096_target_can_free"),
            "scope retained on destructor")
    for name in ("swapz_scope_key_matches_locked", "swapz_round090_candidate_get",
                 "swapz_round090_provider_lookup"):
        require("original_scope_capture_stopped" in function(source, name), "capture gate " + name)
    prior = git("show", FREEZE + ":" + TARGET)
    require(blob(prior) == "46c2cb832ff0071a028a27b35f63daa84f29914f", "frozen DM")
    for name in ("swapz_scope_route_ready_locked", "swapz_scope_observe_plain_accept_locked",
                 "swapz_end_io", "swapz_read", "swapz_map"):
        require(function(source, name) == function(prior.decode(), name), "ordinary path drift " + name)
    require(".presuspend = swapz_presuspend," in source, "actual registered hook")
    (scratch / "actual-controller-stop.h").write_text(
        function(controller, "swapz_trial_controller_stop_capture") + stop +
        function(source, "swapz_presuspend") + function(source, "swapz_scope_external_join_missing"))
    stage.pin(ROOT / FIXTURE, FIXTURE_PIN)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = scratch / compiler
        state["host"][compiler] = {"version": subprocess.check_output(
            [compiler, "--version"], text=True).splitlines()[0]}
        stage.step(state, evidence, compiler + "-host-compile",
                   [compiler, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wconversion",
                    "-Wshadow", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-fno-pie", "-no-pie", "-I" + str(scratch), str(ROOT / FIXTURE),
                    "-o", str(binary)], timeout=90)
        stage.step(state, evidence, compiler + "-host-execute", [str(binary)], timeout=30)
        output = (evidence / (compiler + "-host-execute.log")).read_text()
        match = re.fullmatch(r"R102_A3_STOP_HOST_ONLY checks=(\d+) AUTH=0\n", output)
        require(match is not None, "host evidence " + compiler)
        state["host"][compiler]["checks"] = int(match[1])
        print(compiler, output.strip(), flush=True)

def main():
    baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:4])
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"source": git("rev-parse", "HEAD").decode().strip(),
             "parent": git("rev-parse", "HEAD^").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "status": "FAIL",
             "completed_steps": [], "AUTH": 0, "phase_a": "BLOCKED",
             "full_link": "NOT_RUN", "first_error": None}
    try:
        with tempfile.TemporaryDirectory(prefix="r102-controller-") as directory:
            scratch = Path(directory)
            stage_file = scratch / "frozen-stage.py"
            frozen(STAGE, STAGE_PIN, stage_file)
            spec = importlib.util.spec_from_file_location("frozen_stage", stage_file)
            stage = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(stage)
            target = ROOT / TARGET
            stage.pin(target, TARGET_PIN)
            source = target.read_text()
            controller = ROOT / "src/kernel" / (CONTROLLER + ".c")
            stage.pin(controller, CONTROLLER_PINS[controller.name])
            host(stage, state, evidence, scratch, source, controller.read_text())
            module = scratch / "product-module"
            out = scratch / "x86-build"
            stage.stage(state, evidence, baseline, linux, module)
            apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
            for name, digest, post in PATCHES:
                patch = scratch / name
                frozen("tests/tools/" + name, digest, patch)
                if name.startswith("round101"):
                    for path, expected in R101_PRE.items():
                        stage.pin(linux / path, expected)
                stage.step(state, evidence, name + "-check", apply + ["--check", str(patch)], linux)
                stage.step(state, evidence, name + "-apply", apply + [str(patch)], linux)
                stage.step(state, evidence, name + "-reverse", apply + ["--reverse", "--check", str(patch)], linux)
                for path, expected in post.items():
                    stage.pin(linux / path, expected)
            stage.pin(linux / "mm/page_io.c", "08c11d2f9a16a322093b305afa10ba011f67fc2b")
            state["r101_postimages"] = {path: stage.image(linux / path) for path in PATCHES[-1][2]}
            state["r098_core_postimages"] = {path: stage.image(linux / path) for path in PATCHES[1][2]}
            glue = linux / stage.GLUE_DIR
            for path, expected in PATCHES[-1][2].items():
                if path.startswith("src/kernel/"):
                    for destination in (glue, module):
                        shutil.copyfile(linux / path, destination / Path(path).name)
                        stage.pin(destination / Path(path).name, expected)
            for name, expected in CONTROLLER_PINS.items():
                stage.pin(ROOT / "src/kernel" / name, expected)
                shutil.copyfile(ROOT / "src/kernel" / name, glue / name)
                stage.pin(glue / name, expected)
            shutil.copyfile(glue / (CONTROLLER + ".h"), module / (CONTROLLER + ".h"))
            with (glue / "Makefile").open("a") as stream:
                stream.write("obj-y += " + CONTROLLER + ".o\n")
            shutil.copyfile(target, module / "dm-target.c")
            stage.pin(module / "dm-target.c", TARGET_PIN)
            stage.prerequisites(state, evidence)
            extra = " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND102_CONTROLLER_TEST"
            guards = stage.GUARDS + stage.OBSERVATION_GUARDS + extra
            module_guards = stage.MODULE_GUARDS + stage.OBSERVATION_GUARDS + extra + " -DSWAPZ_ROUND098_SCOPED_TARGET_TEST"
            include = " -I" + str(glue)
            make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64", "CC=gcc"]
            out.mkdir()
            stage.step(state, evidence, "allnoconfig", make + ["KCFLAGS=" + guards + include, "allnoconfig"], timeout=120)
            config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
            for key in stage.REQUIRED:
                config += ["--enable", key]
            for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
                        "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
                config += ["--disable", key]
            config += ["--set-val", "NR_CPUS", "4"]
            stage.step(state, evidence, "set-config", config)
            stage.step(state, evidence, "olddefconfig", make + ["KCFLAGS=" + guards + include, "olddefconfig"], timeout=120)
            shutil.copyfile(out / ".config", evidence / "effective.config")
            effective = (out / ".config").read_text().splitlines()
            require(all("CONFIG_" + key + "=y" in effective for key in stage.REQUIRED), "required config")
            require("CONFIG_NR_CPUS=4" in effective and "CONFIG_TINY_RCU=y" not in effective and
                    "CONFIG_ZSWAP_DEFAULT_ON=y" not in effective, "SMP/RCU/default-off")
            state["config"] = stage.image(out / ".config")
            state["module_guards"] = module_guards
            state["controller_guards"] = guards
            stage.step(state, evidence, "prepare", make + ["KCFLAGS=" + guards + include, "modules_prepare"], timeout=900)
            controller_object = stage.GLUE_DIR + "/" + CONTROLLER + ".o"
            stage.step(state, evidence, "controller-object", make + ["KCFLAGS=" + guards + include,
                       "-j2", controller_object], timeout=900)
            stage.step(state, evidence, "target-object", make + ["KCFLAGS=" + module_guards + include,
                       "M=" + str(module), "-j2", "dm-target.o"], timeout=900)
            state["objects"] = {}
            for obj, expected in ((out / controller_object, "swapz_mm_trial_scope_stop_capture"),
                                  (module / "dm-target.o", "swapz_trial_controller_stop_capture")):
                require(obj.is_file(), "missing object " + obj.name)
                imports = subprocess.check_output(["nm", "-u", str(obj)], text=True)
                require(expected in imports, "missing actual import " + expected)
                (evidence / (obj.name + ".imports")).write_text(imports)
                state["objects"][obj.name] = stage.image(obj)
                shutil.copyfile(obj, evidence / obj.name)
                print("R102_A3_OBJECT", obj.name, state["objects"][obj.name], flush=True)
            defined = subprocess.check_output(["nm", "--defined-only", str(out / controller_object)], text=True)
            require("swapz_trial_controller_stop_capture" in defined, "missing bridge definition")
            require(not (out / "vmlinux").exists(), "unexpected full link")
        state["status"] = "PASS_STOP_SUBSET_HOST_AND_DIRECTED_OBJECTS_ONLY"
        return 0
    except Exception as error:
        state["first_error"] = str(error)[:400]
        print("R102_A3_FIRST_ERROR", state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    sys.exit(main())
