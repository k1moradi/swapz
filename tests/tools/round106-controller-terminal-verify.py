#!/usr/bin/env python3
"""R106 A3 exact R105 stage, actual controller/target host transitions and changed objects only."""
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
FREEZE = "8a83828717ea3000d102043ead78fd86ad0391a8"
TASK = "7eb880eb84474f75037acb9f33b95d92d861000c"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGE = "tests/tools/round105-mm-admission-join-verify.py"
STAGE_PIN = "8dc136fc8db0d25ce1f66de871119bda278e01b1"
FIXTURE = "tests/runtime/native/fixtures/round106-controller-terminal.c"
FIXTURE_PIN = "9442a6d445d34370ea6d7156923eb674255c0456"
SOURCE = {
    "dm-target.c": "b17a17c1096eaa6f43bf42a18c009b8d379e080b",
    "native-observation-controller.c": "556b99a0d04e3027c3027c387a0a9552e22a19ec",
    "native-observation-controller.h": "dac2e2844d893b0090b4c1da3614e4a8d0cc2253",
    "native-observation-integration.h": "e3bca3367459c7f79960105f63e9ddef4e95b4d6",
}
RECORDER = {
    "native-observation-adapter.c": "00700206f1c6df7e0494cdbfe9da86ec209b5ce3",
    "native-observation-adapter.h": "ffa547fbecad79b3fabf0ded4bb182c201e4a33d",
    "native-observation-owner.c": "88e53220ec7c2c610b0645229576418424f3376f",
    "native-observation-owner.h": "b80d36ff48f775c161c3ed3694f4e94a59f18f96",
    "native-observation-byte-collector.c": "d363f40f537722783777956f8920415b97639b93",
    "native-observation-byte-collector.h": "75a07d2913f8d7dd8071234c98463d444f98d9bd",
    "native-observation-byte-bridge.c": "81b86699c4790672ab6d35f1ac6ddbc70b9a165d",
    "native-observation-byte-bridge.h": "8105f87229b3aac1d0d3f9798a59915af0232526",
}
FROZEN_SOURCE = {
    "dm-target.c": "d3cb8525f482321c975cefd91a03aa73fcb7bef2",
    "native-observation-controller.c": "06cf0279cc449330e35873829aab1118a2bee151",
    "native-observation-controller.h": "7189c186874da4fa386fe536280b38bbd1648685",
    "native-observation-integration.h": "e3bca3367459c7f79960105f63e9ddef4e95b4d6",
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

def host(helper, state, evidence, scratch, linux):
    pin(ROOT / FIXTURE, FIXTURE_PIN)
    source = (ROOT / "src/kernel/dm-target.c").read_text()
    controller = (ROOT / "src/kernel/native-observation-controller.c").read_text()
    header = (ROOT / "src/kernel/native-observation-controller.h").read_text()
    carrier = linux / "include/linux/swapz_mm_carrier.h"
    pin(carrier, "bd88db905e5009e0e6161cad1d09b6d33bde2560")
    snapshot = re.search(r"(?ms)^struct swapz_mm_trial_terminal_snapshot \{.*?^\};", carrier.read_text())
    retained = re.search(r"(?ms)^struct swapz_trial_retained_scope \{.*?^\};", header)
    operations = re.search(r"(?ms)^struct swapz_trial_target_ops \{.*?^\};", header)
    require(snapshot and retained and operations, "actual terminal types")
    (scratch / "actual-mm-terminal-type.h").write_text(snapshot[0] + "\n")
    (scratch / "actual-retained-type.h").write_text(retained[0] + "\n" + operations[0] + "\n")
    ordered(function(controller, "swapz_controller_join_locked"),
            "swapz_mm_trial_scope_join_external", "swapz_controller_snapshot_locked",
            "swapz_controller_external_joined = true")
    ordered(function(controller, "swapz_controller_detach"),
            "swapz_controller_join_locked", "swapz_controller_detaching = true",
            "mutex_unlock(&swapz_controller_lock)", "swapz_mm_trial_scope_detach_files",
            "swapz_controller_snapshot_locked", "swapz_controller_mapper = NULL",
            "fput(mapper)", "swapz_controller_files_detached = true")
    ordered(function(controller, "swapz_trial_controller_retire_registered"),
            "ops->validate_retire", "mutex_unlock(&swapz_target_ops_lock)",
            "swapz_controller_detach", "ops->retire", "fput(released_mapper)", "module_put")
    ordered(function(controller, "swapz_trial_controller_finish"),
            "swapz_mm_broker_owner_retired", "SWAPZ_OBS_CLEANUP",
            "swapz_trial_observation_append_sequence", "swapz_trial_byte_event",
            "swapz_trial_observation_stop", "swapz_controller_finished = true")
    ordered(function(source, "swapz_scope_finish_retained"),
            "record->decoder", "swapz_round090_unpublish_target(ctx)",
            "flush_work(&ctx->original_teardown_work)", "swapz_round097_target_debt_free(ctx)",
            "swapz_scope_terminal_census", "swapz_trial_controller_finish",
            "*released_mapper = ctx->original_scope_file",
            "ctx->original_retained_scope = (struct swapz_trial_retained_scope){}")
    ordered(function(source, "swapz_scope_retire_final"),
            "swapz_scope_target_quiescent(ctx)", "ctx->original_scope_final_retirement = true",
            "swapz_trial_controller_revoke_joined", "swapz_round097_retire_target_records",
            "swapz_scope_finish_retained")
    for name in ("swapz_drain", "swapz_dtr"):
        code = function(source, name)
        require("swapz_scope_retire_final" not in code and "swapz_scope_finish_retained" not in code,
                "normal/late retirement " + name)
    require(not re.search(r"EXPORT_SYMBOL_GPL\(swapz_trial_controller_(begin|retire_registered|recover_uninstalled)", controller),
            "positive control export")
    require(controller.count("swapz_trial_observation_append_sequence(&cleanup)") == 1,
            "single cleanup append")
    # Extract the changed production functions, not a transcribed controller.
    control_names = ("swapz_trial_controller_begin", "swapz_controller_matches_locked",
        "swapz_controller_record_error", "swapz_controller_snapshot_locked",
        "swapz_controller_join_locked", "swapz_controller_detach", "swapz_trial_controller_join_external",
        "swapz_trial_controller_revoke_joined", "swapz_controller_recorder_join",
        "swapz_trial_controller_finish", "swapz_trial_controller_recover_uninstalled")
    target_names = ("swapz_scope_observe_invalid", "swapz_scope_observe_event",
        "swapz_round089_revoke_route_locked", "swapz_fail_at", "swapz_scope_install_locked",
        "swapz_scope_install", "swapz_scope_validate_controller", "swapz_scope_install_controller",
        "swapz_scope_stop_capture", "swapz_presuspend", "swapz_round090_cap_release_work",
        "swapz_round090_unpublish_target", "swapz_round094_teardown_work",
        "swapz_scope_external_join_missing", "swapz_scope_target_quiescent", "swapz_scope_terminal_census",
        "swapz_scope_finish_retained", "swapz_round097_retire_target_records",
        "swapz_scope_retire_final", "swapz_scope_validate_retire_controller",
        "swapz_scope_retire_controller", "swapz_round096_target_can_free")
    actual = function(controller, "swapz_trial_controller_stop_capture") + controller[
        controller.index("static DEFINE_MUTEX(swapz_controller_lock)"):
        controller.index("static int swapz_trial_controller_begin")]
    actual += controller[controller.index("static DEFINE_MUTEX(swapz_target_ops_lock)"):
                         controller.index("int swapz_trial_target_register")]
    actual += "".join(function(controller, name) for name in control_names)
    actual += "".join(function(controller, name) for name in ("swapz_trial_target_register",
        "swapz_trial_target_unregister", "swapz_trial_controller_begin_registered",
        "swapz_trial_controller_retire_registered"))
    actual += "static struct target_type swapz_target;\n" + "".join(function(source, name) for name in target_names)
    target_ops = re.search(r"(?ms)^static const struct swapz_trial_target_ops swapz_scope_target_ops = \{.*?^\};", source)
    require(target_ops, "actual target registration")
    actual += target_ops[0] + "\n"
    changes = (
        ("mm-debt", "snapshot->mm_callbacks ||", "false ||", "mm-debt"),
        ("wrong-area", "snapshot->area_epoch != swapz_controller_scope.area_epoch", "false", "wrong-area"),
        ("locked-detach", "mutex_unlock(&swapz_controller_lock);\n\n\terror = swapz_mm_trial_scope_detach_files",
         "/* mutant: retained controller lock */\n\n\terror = swapz_mm_trial_scope_detach_files", "clean"),
        ("skip-map", "maps += ctx->maps[index].valid != 0;", "maps += 0;", "ordinary-map"),
        ("skip-broker", "error = swapz_mm_broker_owner_retired(retained->session, retained->epoch);",
         "error = (swapz_mm_broker_owner_retired(retained->session, retained->epoch), 0);", "broker-busy"),
        ("early-finish", "(swapz_controller_installed && !swapz_controller_registered_retiring)",
         "false", "early-finish"),
        ("skip-retirement", "error = swapz_round097_retire_target_records(ctx);", "error = 0;", "final-live"),
        ("skip-pending", "!ctx->observation_release_operation && !ctx->observation_release_descriptor",
         "!ctx->observation_release_descriptor", "pending-event"),
    )
    variants = {"actual": (actual, None)}
    for label, old, new, mode in changes:
        require(actual.count(old) == 1, "mutant anchor " + label)
        variants[label] = (actual.replace(old, new, 1), mode)
    modes = ("clean", "wrong-key", "wrong-area", "mm-fault", "mm-debt", "dm-debt", "entrant-debt",
             "carrier-debt", "area-busy", "detach-busy", "target-debt", "final-live", "final-pinned",
             "broker-busy", "early-finish", "ordinary-map", "pending-event", "seal-failure",
             "append-failure", "bridge-failure", "failed-target")
    state["host"] = {}
    for cc in ("gcc", "clang"):
        state["host"][cc] = {"version": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
                             "cases": {}, "mutants": {}}
        for variant, (code, selected) in variants.items():
            binary = scratch / (cc + "-" + variant)
            (scratch / "actual-controller-target.h").write_text(code)
            helper.step(state, evidence, cc + "-" + variant + "-compile",
                        [cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                         "-Wno-unused-function" if variant == "skip-retirement" else "-Wunused-function",
                         "-fno-pie", "-no-pie", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-I" + str(scratch), str(ROOT / FIXTURE), "-o", str(binary)], timeout=90)
            for mode in modes if selected is None else (selected,):
                label = cc + "-" + variant + "-" + mode
                result = subprocess.run([str(binary), mode], capture_output=True, timeout=30)
                (evidence / (label + ".log")).write_bytes(result.stdout + result.stderr)
                if selected is None:
                    match = re.fullmatch(rb"R106_A3_HOST_ONLY mode=" + mode.encode() +
                                         rb" checks=(\d+) AUTH=0\n", result.stdout)
                    require(result.returncode == 0 and match and not result.stderr, label)
                    state["host"][cc]["cases"][mode] = int(match[1])
                    print(label, result.stdout.decode().strip(), flush=True)
                else:
                    require(result.returncode != 0 and b"Assertion" in result.stderr, "surviving mutant " + label)
                    state["host"][cc]["mutants"][variant] = "KILLED"
                    print(label, "KILLED", flush=True)

def native(helper, state, evidence, scratch, frozen, baseline, linux):
    manifest = json.loads((evidence / "r104-stage" / "r103-stage" / "unified-base-manifest.json").read_text())["authoritative_manifest"]
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
            "swapz_mm_trial_scope_terminal_snapshot", "swapz_mm_trial_scope_detach_files",
            "swapz_mm_trial_scope_revoke", "swapz_mm_broker_owner_retired",
            "swapz_trial_observation_append_sequence", "swapz_trial_byte_event",
            "swapz_trial_observation_start", "swapz_trial_observation_stop", "swapz_trial_byte_bind_scope"),
        module / "dm-target.o": ("swapz_mm_trial_scope_matches_exact", "swapz_trial_observation_append_sequence",
            "swapz_trial_byte_event", "swapz_trial_controller_revoke_joined", "swapz_trial_controller_finish",
            "swapz_trial_target_register", "swapz_trial_target_unregister"),
    }
    for obj, names in required.items():
        imports = subprocess.check_output(["nm", "-u", str(obj)], text=True)
        require(all(re.search(r"\b" + name + r"\b", imports) for name in names), "missing actual imports " + obj.name)
        (evidence / (obj.name + ".imports")).write_text(imports)
        shutil.copyfile(obj, evidence / obj.name)
        state["objects"][obj.name] = helper.image(obj)
        print("R106_A3_OBJECT", obj.name, state["objects"][obj.name], flush=True)
    require(not (out / "vmlinux").exists() and not (out / "Module.symvers").exists(), "unexpected full link")
    state["native"] = "PASS_DIRECTED_ONLY_UNRESOLVED_PEER_SYMBOLS"

def main():
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"round": 106, "agent": 3, "source": git("rev-parse", "HEAD").decode().strip(),
             "parent": git("rev-parse", "HEAD^").decode().strip(),
             "freeze": FREEZE, "task": TASK, "linux": LINUX, "AUTH": 0,
             "phase_a": "BLOCKED", "full_link": "NOT_RUN", "native": "NOT_RUN",
             "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        pin(ROOT / STAGE, STAGE_PIN)
        for name, expected in FROZEN_SOURCE.items():
            require(blob(git("show", FREEZE + ":src/kernel/" + name)) == expected, "frozen source " + name)
        for name, expected in SOURCE.items():
            pin(ROOT / "src/kernel" / name, expected)
        stage = load(ROOT / STAGE, "r105_exact_stage")
        previous, helper = stage.stage(state, evidence, frozen, baseline, linux)
        require(state["stage"] == "PASS", "R105 exact staged chain")
        with tempfile.TemporaryDirectory(prefix="r106-controller-") as directory:
            scratch = Path(directory)
            first_error = None
            try:
                host(helper, state, evidence, scratch, linux)
            except Exception as error:
                first_error = str(error)
            try:
                native(helper, state, evidence, scratch, frozen, baseline, linux)
            except Exception as error:
                state["native_error"] = str(error)[:400]
                if first_error is None:
                    first_error = str(error)
            if first_error:
                raise RuntimeError(first_error)
        state["status"] = "PASS_HOST_AND_DIRECTED_ONLY"
        print("R106_A3_PASS AUTH0 DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)[:400]
        print("R106_A3_FIRST_ERROR", state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    sys.exit(main())
