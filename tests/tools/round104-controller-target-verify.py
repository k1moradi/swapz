#!/usr/bin/env python3
"""R104 A3 actual controller/target host transitions and directed objects only."""
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
FREEZE = "a9094f96e3fb2841ed0fa553102d98699950221d"
TASK = "3ec158e2870170bd58fc13dfc340722a89f51cae"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGE = "tests/tools/round103-external-join-verify.py"
STAGE_PIN = "11ae07a68761d11160b649a3503af64eecd3ec4a"
FIXTURE = "tests/runtime/native/fixtures/round104-controller-target.c"
FIXTURE_PIN = "df72cfec8c871e14b7364d80d0395f20f8f63283"
SOURCE = {
    "dm-target.c": "8a84ac4d395e2f635ae3e4216bade471c03618de",
    "native-observation-controller.c": "46ab3317c8160bfd8716360d281a7f46609fb6a3",
    "native-observation-controller.h": "3e917194fda1b1163ed047656a814350448b2523",
    "native-observation-integration.h": "e3bca3367459c7f79960105f63e9ddef4e95b4d6",
}
RECORDER = {
    "native-observation-adapter.c": "00700206f1c6df7e0494cdbfe9da86ec209b5ce3",
    "native-observation-adapter.h": "ffa547fbecad79b3fabf0ded4bb182c201e4a33d",
    "native-observation-owner.c": "e99ffb797f02b355b23358d663339fc8d3a49d03",
    "native-observation-owner.h": "9e44829f3920167829fc364fdb6a95bfa0930805",
}

def require(value, reason):
    if not value:
        raise RuntimeError(reason)

def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])

def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def pin(path, expected):
    require(path.is_file() and not path.is_symlink() and blob(path.read_bytes()) == expected,
            "blob mismatch " + str(path))

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:(?:__maybe_unused|__used|noinline) )*(?:bool|int|void|u64) " +
        re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    return source[matches[0].start():source.index("\n}", matches[0].end()) + 2] + "\n"

def ordered(code, *anchors):
    offsets = [code.index(anchor) for anchor in anchors]
    require(offsets == sorted(set(offsets)), "ordering " + repr(anchors))

def host(helper, state, evidence, scratch, source, controller, header):
    pin(ROOT / FIXTURE, FIXTURE_PIN)
    ordered(function(source, "swapz_scope_finish_retained"), "ctx->original_target_drained",
            "record->decoder", "swapz_trial_controller_revoke_joined", "ctx->original_scope_mm_revoked = true",
            "swapz_round090_unpublish_target(ctx)", "flush_work(&ctx->original_teardown_work)",
            "swapz_round097_target_debt_free(ctx)", "swapz_trial_controller_finish",
            "ctx->original_retained_scope = (struct swapz_trial_retained_scope){}", "fput(mapper)")
    ordered(function(source, "swapz_drain"), "swapz_scope_stop_capture(ctx)", "WRITE_ONCE(ctx->accepting, false)",
            "swapz_round090_unpublish_target(ctx)", "flush_work(&ctx->original_release_work)",
            "swapz_issue_flush(ctx)", "swapz_scope_finish_retained(ctx)")
    ordered(function(source, "swapz_round097_read_original_pinned"), "swapz_shared_original_pin",
            "swapz_scope_observe_read_pin", "swapz_shared_storage_decoder_read", "swapz_shared_original_put")
    ordered(function(source, "swapz_round090_storage_read"), "SWAPZ_OBS_LOWER_SUBMIT",
            "swapz_lower_read(opaque", "SWAPZ_OBS_LOWER_COMPLETE")
    ordered(function(source, "swapz_read"), "swapz_copy_bio_accounted", "swapz_scope_observe_read_copy",
            "swapz_shared_original_put", "swapz_scope_observe_read_release")
    copy = function(source, "swapz_scope_observe_read_copy")
    ordered(copy, "swapz_shared_original_view", "swapz_map_single_bio_input(bio", "sha256(bytes",
            "memcmp(bytes, ctx->read_page", "swapz_scope_observe_event(&record, bytes", "kunmap_local")
    require("swapz_mm_trial_scope_matches_exact(scope, mapper_file)" in
            function(source, "swapz_scope_install_locked"), "exact target query")
    require("EXPORT_SYMBOL_GPL(swapz_trial_controller_begin)" not in controller, "positive control export")
    retained = re.search(r"(?ms)^struct swapz_trial_retained_scope \{.*?^\};", header)
    require(retained is not None, "retained type")
    (scratch / "actual-retained-type.h").write_text(retained[0] + "\n")
    # Real source functions, with explicitly modeled serial dependencies.
    control_names = ("swapz_trial_controller_begin", "swapz_controller_matches_locked",
        "swapz_controller_record_error", "swapz_controller_join_locked",
        "swapz_trial_controller_join_external", "swapz_trial_controller_revoke_joined",
        "swapz_controller_recorder_join", "swapz_trial_controller_finish")
    target_names = ("swapz_scope_observe_invalid", "swapz_scope_observe_event",
        "swapz_round089_revoke_route_locked", "swapz_fail_at", "swapz_scope_install_locked",
        "swapz_scope_install", "swapz_scope_install_controller", "swapz_scope_stop_capture",
        "swapz_presuspend", "swapz_round090_cap_release_work", "swapz_round090_unpublish_target",
        "swapz_round094_teardown_work", "swapz_scope_external_join_missing",
        "swapz_scope_finish_retained", "swapz_round096_target_can_free")
    actual = function(controller, "swapz_trial_controller_stop_capture") + controller[
        controller.index("static DEFINE_MUTEX(swapz_controller_lock)"):
        controller.index("int swapz_trial_controller_begin")] + "".join(
            function(controller, name) for name in control_names) + "".join(
            function(source, name) for name in target_names)
    mutants = {
        "skip-exact": (actual.replace("swapz_mm_trial_scope_matches_exact(scope, mapper_file) &&",
                                     "true &&", 1), "rollback"),
        "wrong-ordinal": (actual.replace("swapz_trial_byte_event(record, sequence, bytes, length)",
                                         "swapz_trial_byte_event(record, sequence + 1, bytes, length)", 1), "normal"),
        "skip-external": (actual.replace("error = swapz_mm_trial_scope_join_external(retained->identity,\n\t\t\tretained->session, retained->epoch, retained->target_epoch);",
                                        "error = (swapz_mm_trial_scope_join_external(retained->identity,\n\t\t\tretained->session, retained->epoch, retained->target_epoch), 0);", 1), "normal"),
        "clear-retained": (actual.replace("ctx->original_scope = (struct swapz_mm_trial_scope){};",
                                         "ctx->original_scope = (struct swapz_mm_trial_scope){}; ctx->original_retained_scope.identity = 0;", 1), "normal"),
    }
    require(all(code != actual for code, _ in mutants.values()), "mutant anchor")
    modes = ("normal", "bind-failure", "rollback", "typed-debt", "wrong-key", "retirement-busy", "failure")
    state["host"] = {}
    for cc in ("gcc", "clang"):
        state["host"][cc] = {"version": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
                              "cases": {}, "mutants": {}}
        for variant, (code, selected) in {"actual": (actual, None), **mutants}.items():
            binary = scratch / (cc + "-" + variant)
            (scratch / "actual-controller-target.h").write_text(code)
            helper.step(state, evidence, cc + "-" + variant + "-compile",
                        [cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                         "-fno-pie", "-no-pie", "-fsanitize=address,undefined",
                         "-fno-sanitize-recover=all", "-I" + str(scratch), str(ROOT / FIXTURE),
                         "-o", str(binary)], timeout=90)
            for mode in modes if selected is None else (selected,):
                label = cc + "-" + variant + "-" + mode
                result = subprocess.run([str(binary), mode], capture_output=True, timeout=30)
                (evidence / (label + ".log")).write_bytes(result.stdout + result.stderr)
                if selected is None:
                    match = re.fullmatch(rb"R104_A3_HOST_ONLY mode=" + mode.encode() +
                                         rb" checks=(\d+) AUTH=0\n", result.stdout)
                    require(result.returncode == 0 and match and not result.stderr, label)
                    state["host"][cc]["cases"][mode] = int(match[1])
                    print(label, result.stdout.decode().strip(), flush=True)
                else:
                    require(result.returncode != 0 and b"Assertion" in result.stderr, "surviving mutant " + label)
                    state["host"][cc]["mutants"][variant] = "KILLED"
                    print(label, "KILLED", flush=True)

def native(stage, helper, state, evidence, scratch, frozen, baseline, linux):
    stage.stage_source(helper, state, evidence, frozen, baseline, linux)
    manifest = json.loads((evidence / "unified-base-manifest.json").read_text())["authoritative_manifest"]
    module = scratch / "module"
    module.mkdir()
    glue = linux / helper.GLUE_DIR
    for name, metadata in manifest["module_final"].items():
        if name == "Makefile":
            makefile = (baseline / "src/kernel" / name).read_text()
            anchor = "dm-swapz-y := dm-target.o codec.o authority.o engine.o predictor.o\n"
            require(makefile.count(anchor) == 1, "module makefile")
            (module / name).write_text(makefile.replace(anchor, anchor + "dm-swapz-y += " +
                " ".join(helper.EXTRA_MODULE) + "\nccflags-y += -I$(src)\n", 1))
        elif name == "swapz-version.h":
            version = (baseline / "src/kernel/VERSION").read_text().strip()
            (module / name).write_text(f'#define SWAPZ_ALPHA_VERSION "{version}"\n')
        elif name == "dm-target.c":
            shutil.copyfile(frozen / "src/kernel" / name, module / name)
        elif name in (*helper.BROKER_INPUTS, helper.OWNER_INC):
            shutil.copyfile(linux / "src/kernel" / name, module / name)
        else:
            shutil.copyfile(baseline / "src/kernel" / name, module / name)
        pin(module / name, metadata["blob"])
    for name, expected in RECORDER.items():
        data = git("show", FREEZE + ":src/kernel/" + name)
        require(blob(data) == expected, "frozen recorder " + name)
        (glue / name).write_bytes(data)
        pin(glue / name, expected)
    for name, expected in SOURCE.items():
        src = ROOT / "src/kernel" / name
        pin(src, expected)
        if name == "dm-target.c":
            shutil.copyfile(src, module / name)
        else:
            shutil.copyfile(src, glue / name)
            pin(glue / name, expected)
            if name.endswith(".h"):
                shutil.copyfile(src, module / name)
    require(blob(git("show", TASK + ":src/kernel/native-observation-integration.h")) ==
            SOURCE["native-observation-integration.h"], "task header")
    with (glue / "Makefile").open("a") as stream:
        stream.write("obj-y += native-observation-controller.o\n")
    helper.prerequisites(state, evidence)
    extra = " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND102_CONTROLLER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST -DSWAPZ_ROUND104_INTEGRATION_TEST"
    guards = helper.GUARDS + helper.OBSERVATION_GUARDS + extra + " -I" + str(glue)
    module_guards = helper.MODULE_GUARDS + helper.OBSERVATION_GUARDS + extra + " -DSWAPZ_ROUND098_SCOPED_TARGET_TEST -I" + str(glue)
    out = scratch / "build"
    out.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64", "CC=gcc"]
    helper.step(state, evidence, "allnoconfig", make + ["KCFLAGS=" + guards, "allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for key in helper.REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
                "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "set-config", config)
    helper.step(state, evidence, "olddefconfig", make + ["KCFLAGS=" + guards, "olddefconfig"], timeout=120)
    effective = (out / ".config").read_text().splitlines()
    require(all("CONFIG_" + key + "=y" in effective for key in helper.REQUIRED) and
            "CONFIG_NR_CPUS=4" in effective and "CONFIG_TINY_RCU=y" not in effective and
            "CONFIG_ZSWAP_DEFAULT_ON=y" not in effective and "CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=y" not in effective,
            "SMP TREE_RCU/default-off config")
    shutil.copyfile(out / ".config", evidence / "effective.config")
    state["config"] = helper.image(out / ".config")
    state["controller_guards"], state["module_guards"] = guards, module_guards
    helper.step(state, evidence, "prepare", make + ["KCFLAGS=" + guards, "modules_prepare"], timeout=900)
    controller_object = helper.GLUE_DIR + "/native-observation-controller.o"
    helper.step(state, evidence, "controller-object", make + ["KCFLAGS=" + guards, "-j2", controller_object], timeout=900)
    helper.step(state, evidence, "target-object", make + ["KCFLAGS=" + module_guards,
               "M=" + str(module), "-j2", "dm-target.o"], timeout=900)
    state["objects"] = {}
    required = {
        out / controller_object: ("swapz_mm_trial_area_get", "swapz_mm_trial_scope_publish",
            "swapz_mm_trial_scope_matches_exact", "swapz_mm_trial_scope_join_external",
            "swapz_mm_trial_scope_revoke", "swapz_mm_broker_owner_retired",
            "swapz_trial_observation_start", "swapz_trial_observation_stop", "swapz_trial_byte_bind_scope"),
        module / "dm-target.o": ("swapz_mm_trial_scope_matches_exact", "swapz_trial_observation_append_sequence",
            "swapz_trial_byte_event", "swapz_trial_controller_revoke_joined", "swapz_trial_controller_finish"),
    }
    for obj, names in required.items():
        imports = subprocess.check_output(["nm", "-u", str(obj)], text=True)
        require(all(re.search(r"\b" + name + r"\b", imports) for name in names), "missing actual imports " + obj.name)
        (evidence / (obj.name + ".imports")).write_text(imports)
        shutil.copyfile(obj, evidence / obj.name)
        state["objects"][obj.name] = helper.image(obj)
        print("R104_A3_OBJECT", obj.name, state["objects"][obj.name], flush=True)
    require(not (out / "vmlinux").exists() and not (out / "Module.symvers").exists(), "unexpected full link")
    state["native"] = "PASS_DIRECTED_ONLY_UNRESOLVED_PEER_SYMBOLS"

def main():
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"round": 104, "agent": 3, "source": git("rev-parse", "HEAD").decode().strip(),
             "parent": git("rev-parse", "HEAD^").decode().strip(),
             "freeze": FREEZE, "task": TASK, "linux": LINUX, "AUTH": 0,
             "phase_a": "BLOCKED", "full_link": "NOT_RUN", "native": "NOT_RUN",
             "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        pin(ROOT / STAGE, STAGE_PIN)
        stage = load(ROOT / STAGE, "r103_exact_stage")
        helper = stage.load_helper()
        for name, expected in SOURCE.items():
            pin(ROOT / "src/kernel" / name, expected)
        with tempfile.TemporaryDirectory(prefix="r104-controller-") as directory:
            scratch = Path(directory)
            first_error = None
            try:
                host(helper, state, evidence, scratch,
                     (ROOT / "src/kernel/dm-target.c").read_text(),
                     (ROOT / "src/kernel/native-observation-controller.c").read_text(),
                     (ROOT / "src/kernel/native-observation-controller.h").read_text())
            except Exception as error:
                first_error = str(error)
            try:
                native(stage, helper, state, evidence, scratch, frozen, baseline, linux)
            except Exception as error:
                state["native_error"] = str(error)[:400]
                if first_error is None:
                    first_error = str(error)
            if first_error:
                raise RuntimeError(first_error)
        state["status"] = "PASS_HOST_AND_DIRECTED_ONLY"
        print("R104_A3_PASS AUTH0 DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)[:400]
        print("R104_A3_FIRST_ERROR", state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    sys.exit(main())
