#!/usr/bin/env python3
"""R107 A3 exact R106 stage, read-only preflight and negative admission, changed objects only."""
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
FREEZE = "0c908d5506f75a430171c627cd28b9994ff5765e"
TASK = "e7716a8d44c23f7c209b9c2f34ccd04af81efa36"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGE = "tests/tools/round105-mm-admission-join-verify.py"
# A1: exact R105 inherited declaration pin correction; product postimages unchanged.
STAGE_PIN = "01ff882ddcdbdd27da6b354a078921169aebce38"
FIXTURE = "tests/runtime/native/fixtures/round107-controller-preflight.c"
FIXTURE_PIN = "2d88e8bf2fa75b5fb476025545ff213af850bf2d"
MM_PATCH = "tests/tools/round106-original-mm-owner-boundary.patch"
MM_PATCH_PIN = "24b9c16de84e8e4795c8c2378220bf2e0dfae25e"
ADMISSION_GUARD = "-DSWAPZ_ROUND106_ADMITTED_OWNER_TEST"
SOURCE = {
    "dm-target.c": "5ecc477dc6c795d89e2a67ad2f6424a94d314b2d",
    "native-observation-controller.c": "0ea943f55449cacae473c182f33e75c48eb371bb",
    "native-observation-controller.h": "df0112eaa70989a827c5964ae42fecbd51c9860a",
    "native-observation-integration.h": "e3bca3367459c7f79960105f63e9ddef4e95b4d6",
}
RECORDER = {
    "native-observation-adapter.c": "00700206f1c6df7e0494cdbfe9da86ec209b5ce3",
    "native-observation-adapter.h": "ffa547fbecad79b3fabf0ded4bb182c201e4a33d",
    "native-observation-owner.c": "088b9ba8ad59cff94510dbd0452df734c96590bb",
    "native-observation-owner.h": "dad3cbe3ff93ef2a2bf56bb2b7eef4a6a64e60cb",
    "native-observation-byte-collector.c": "d363f40f537722783777956f8920415b97639b93",
    "native-observation-byte-collector.h": "75a07d2913f8d7dd8071234c98463d444f98d9bd",
    "native-observation-byte-bridge.c": "81b86699c4790672ab6d35f1ac6ddbc70b9a165d",
    "native-observation-byte-bridge.h": "8105f87229b3aac1d0d3f9798a59915af0232526",
}
FROZEN_SOURCE = {
    "dm-target.c": "b17a17c1096eaa6f43bf42a18c009b8d379e080b",
    "native-observation-controller.c": "556b99a0d04e3027c3027c387a0a9552e22a19ec",
    "native-observation-controller.h": "dac2e2844d893b0090b4c1da3614e4a8d0cc2253",
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
    preflight = re.search(r"(?ms)^struct swapz_trial_target_preflight \{.*?^\};", header)
    require(snapshot and retained and operations and preflight, "actual terminal/preflight types")
    (scratch / "actual-mm-terminal-type.h").write_text(snapshot[0] + "\n")
    (scratch / "actual-retained-type.h").write_text("struct swapz_ticket_broker;\n" + retained[0] + "\n" + preflight[0] + "\n" + operations[0] + "\n")
    begin = function(controller, "swapz_trial_controller_begin_registered")
    ordered(begin, "#ifdef SWAPZ_ROUND106_ADMITTED_OWNER_TEST", "return -EACCES;",
            "if (!target", "mutex_lock", "try_module_get", "ops->validate", "swapz_trial_controller_begin(")
    query = function(controller, "swapz_trial_controller_query_registered")
    ordered(query, "*result = (struct swapz_trial_target_preflight){}", "mutex_lock",
            "try_module_get", "ops->query", "mutex_unlock", "module_put", "*result = selected")
    target_query = function(source, "swapz_scope_query_controller")
    ordered(target_query, "*result =", "file_bdev", "spin_lock_irqsave",
            "route = &ctx->original_route", "rcu_read_lock", "dm_swapz_round090_route_live",
            "rcu_read_unlock", "*result = (struct swapz_trial_target_preflight){\n", "spin_unlock_irqrestore")
    require("swapz_scope_route_ready_locked" not in target_query and
            "swapz_round090_provider_lookup" not in target_query, "installed-scope dependency")
    require(not re.search(r"EXPORT_SYMBOL_GPL\(swapz_trial_controller_query_registered", controller),
            "query must remain private")
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
        "swapz_scope_install", "swapz_scope_query_controller", "swapz_scope_validate_controller", "swapz_scope_install_controller",
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
        "swapz_trial_target_unregister", "swapz_trial_controller_query_registered", "swapz_trial_controller_begin_registered",
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
    query_modes = ("query-clean", "query-no-broker-hint", "query-full-range", "query-unregistered",
                   "query-unloading", "query-null-target", "query-null-mapper", "query-wrong-target",
                   "query-no-private", "query-wrong-context", "query-no-table", "query-wrong-mapper",
                   "query-partition", "query-nonblock", "query-zero", "query-unaligned", "query-overflow",
                   "query-out-of-range", "query-logical-limit", "query-trial-limit", "query-stale-registration",
                   "query-stale-snapshot", "query-stale-session", "query-stale-cap", "query-stale-route",
                   "query-zero-target-epoch", "query-zero-registration", "query-wrong-broker",
                   "query-no-storage", "query-not-listed", "query-not-accepting", "query-failed",
                   "query-installed", "query-consumed", "query-wrong-route")
    guarded_changes = (
        ("installed-scope", "ctx->original_scope.identity || ctx->original_retained_scope.identity ||",
         "!ctx->original_scope.identity || ctx->original_retained_scope.identity ||", "query-clean"),
        ("stale-epoch", "route->registration_epoch != ctx->original_snapshot_epoch)", "false)", "query-stale-registration"),
        ("stale-cap", "ctx->original_cap.session != route->broker_session ||\n\t    ctx->original_cap.epoch != route->table_epoch ||",
         "ctx->original_cap.session != route->broker_session ||\n\t    false ||", "query-stale-route"),
        ("missed-module-put", "if (owner)\n\t\tmodule_put(owner);\n\tif (!error)\n\t\t*result = selected;",
         "if (owner)\n\t\t(void)owner;\n\tif (!error)\n\t\t*result = selected;", "query-clean"),
        ("wrong-route", "if (!dm_swapz_round090_route_live(ti, bdev, sector))",
         "if (!dm_swapz_round090_route_live(ti, bdev, first_sector))", "query-wrong-route"),
    )
    guarded = {"guarded-actual": (actual, None)}
    for label, old, new, mode in guarded_changes:
        require(actual.count(old) == 1, "guarded mutant anchor " + label)
        guarded[label] = (actual.replace(old, new, 1), mode)
    require(actual.count("\treturn -EACCES;") == 1 and
            actual.count("\tswapz_controller_used = true;") == 1, "late-denial mutant anchors")
    guarded["late-admission"] = (actual.replace("\treturn -EACCES;", "\t/* delayed denial */", 1).replace(
        "\tswapz_controller_used = true;", "\terror = -EACCES;\n\tgoto put_area;\n\tswapz_controller_used = true;", 1), "denied")
    state["host"] = {}
    for cc in ("gcc", "clang"):
        state["host"][cc] = {"version": subprocess.check_output([cc, "--version"], text=True).splitlines()[0],
                             "cases": {}, "mutants": {}}
        for variant, (code, selected) in {**variants, **guarded}.items():
            guard = variant in guarded
            binary = scratch / (cc + "-" + variant)
            (scratch / "actual-controller-target.h").write_text(code)
            helper.step(state, evidence, cc + "-" + variant + "-compile",
                        [cc, "-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                         "-Wno-unused-function" if variant == "skip-retirement" else "-Wunused-function",
                         *([ADMISSION_GUARD] if guard else []),
                         "-fno-pie", "-no-pie", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                         "-I" + str(scratch), str(ROOT / FIXTURE), "-o", str(binary)], timeout=90)
            selected_modes = (query_modes + ("denied", "denied-invalid") if guard else
                              modes + ("query-stale-install",)) if selected is None else (selected,)
            for mode in selected_modes:
                label = cc + "-" + variant + "-" + mode
                result = subprocess.run([str(binary), mode], capture_output=True, timeout=30)
                (evidence / (label + ".log")).write_bytes(result.stdout + result.stderr)
                if selected is None:
                    match = re.fullmatch(rb"R107_A3_HOST_ONLY mode=" + mode.encode() +
                                         rb" checks=(\d+) AUTH=0\n", result.stdout)
                    require(result.returncode == 0 and match and not result.stderr, label)
                    state["host"][cc]["cases"][("guarded:" if guard else "historical:") + mode] = int(match[1])
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
    historical_guards = helper.GUARDS + helper.OBSERVATION_GUARDS + extra + " -I" + str(glue)
    guards = historical_guards + " " + ADMISSION_GUARD
    module_guards = helper.MODULE_GUARDS + helper.OBSERVATION_GUARDS + extra + " " + ADMISSION_GUARD + " -DSWAPZ_ROUND098_SCOPED_TARGET_TEST -I" + str(glue)
    out = scratch / "build"
    out.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64", "CC=gcc"]
    helper.step(state, evidence, "allnoconfig", make + ["KCFLAGS=" + guards, "allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for key in (*helper.REQUIRED, "MODULE_UNLOAD"):
        config += ["--enable", key]
    config += ["--disable", "MODULE_FORCE_UNLOAD"]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
                "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "set-config", config)
    helper.step(state, evidence, "olddefconfig", make + ["KCFLAGS=" + guards, "olddefconfig"], timeout=120)
    effective = (out / ".config").read_text().splitlines()
    require(all("CONFIG_" + key + "=y" in effective for key in helper.REQUIRED) and
            "CONFIG_MODULE_UNLOAD=y" in effective and "CONFIG_MODULE_FORCE_UNLOAD=y" not in effective and
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
    terminal_imports = ("swapz_mm_trial_scope_join_external",
        "swapz_mm_trial_scope_terminal_snapshot", "swapz_mm_trial_scope_detach_files",
        "swapz_mm_trial_scope_revoke", "swapz_mm_broker_owner_retired",
        "swapz_trial_observation_append_sequence", "swapz_trial_byte_event",
        "swapz_trial_observation_stop")
    startup_imports = ("swapz_mm_trial_area_get", "swapz_mm_trial_scope_publish",
        "swapz_trial_observation_start", "swapz_trial_byte_bind_scope")
    target_imports = ("swapz_mm_trial_scope_matches_exact", "swapz_trial_observation_append_sequence",
        "swapz_trial_byte_event", "swapz_trial_controller_revoke_joined", "swapz_trial_controller_finish",
        "swapz_trial_target_register", "swapz_trial_target_unregister")

    def has_symbol(symbols, name):
        return bool(re.search(r"\b" + name + r"\b", symbols))

    def collect(obj, label):
        imports = subprocess.check_output(["nm", "-u", str(obj)], text=True)
        symbols = subprocess.check_output(["nm", str(obj)], text=True)
        (evidence / (label + ".imports")).write_text(imports)
        (evidence / (label + ".symbols")).write_text(symbols)
        shutil.copyfile(obj, evidence / label)
        state["objects"][label] = helper.image(obj)
        print("R107_A3_OBJECT", label, state["objects"][label], flush=True)
        return imports, symbols

    # The AUTH0 begin is an unconditional denial. The private publication
    # flag is never set, so optimization may eliminate terminal imports.
    # Require those imports in the historical object below, not unreachable
    # guard-on paths. Retain the complete actual census in both modes.
    obj = out / controller_object
    imports, symbols = collect(obj, obj.name)
    controller = (ROOT / "src/kernel/native-observation-controller.c").read_text()
    require(controller.count("swapz_controller_published = true;") == 1 and
            "swapz_controller_published = true;" in function(controller, "swapz_trial_controller_begin") and
            controller.count("swapz_trial_controller_begin(") == 2,
            "publication path no longer single guarded caller")
    require(all(has_symbol(symbols, name) for name in (
        "swapz_trial_controller_begin_registered", "swapz_trial_controller_query_registered",
        "swapz_trial_controller_retire_registered", "swapz_trial_target_register",
        "swapz_trial_target_unregister")), "guarded controller definitions missing")
    require(all(has_symbol(imports, name) for name in ("try_module_get", "module_put")),
            "guarded controller module lifetime imports missing")
    require(not any(has_symbol(imports, name) for name in startup_imports),
            "guarded admission still imports positive startup")
    state["guarded_terminal_imports"] = {name: has_symbol(imports, name) for name in terminal_imports}
    print("R107_A3_GUARDED_TERMINAL_IMPORTS", state["guarded_terminal_imports"], flush=True)
    imports, _ = collect(module / "dm-target.o", "dm-target.o")
    require(all(has_symbol(imports, name) for name in target_imports), "missing actual target imports")
    # Historical guard-off controller must retain all original terminal and
    # startup imports. This is not a full link or permission to invoke it.
    obj.unlink()
    helper.step(state, evidence, "controller-historical-object",
                make + ["KCFLAGS=" + historical_guards, "-j2", controller_object], timeout=900)
    imports, _ = collect(obj, "controller-historical.o")
    missing = [name for name in terminal_imports + startup_imports if not has_symbol(imports, name)]
    require(not missing, "historical startup/terminal imports missing: " + repr(missing))
    require(not (out / "vmlinux").exists() and not (out / "Module.symvers").exists(), "unexpected full link")
    state["native"] = "PASS_DIRECTED_ONLY_UNRESOLVED_PEER_SYMBOLS"

def main():
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"round": 107, "agent": 3, "source": git("rev-parse", "HEAD").decode().strip(),
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
        pin(linux / "drivers/md/dm.c", "6912eb7ec5a9ef325f7282ef9c9226b39265f01d")
        pin(ROOT / MM_PATCH, MM_PATCH_PIN)
        mm = linux / "mm/zswap.c"
        pre, post = "058389456ee1586f5a26d40f78cd5cde99312060", "9e1efceae44c384370d0aa3e25748d127a5cd4ad"
        pin(mm, pre)
        staged = subprocess.check_output(["git", "-C", str(linux), "diff", "--cached", "--name-only"])
        unstaged = subprocess.check_output(["git", "-C", str(linux), "diff", "--name-only"])
        command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
        for label, args, expected in (("check", ["--check"], pre), ("apply", [], post),
                                      ("reverse-check", ["--reverse", "--check"], post),
                                      ("reverse", ["--reverse"], pre), ("reapply", [], post)):
            helper.step(state, evidence, "r106-owner-" + label,
                        command + args + [str(ROOT / MM_PATCH)], linux)
            pin(mm, expected)
        require(subprocess.check_output(["git", "-C", str(linux), "diff", "--cached", "--name-only"]) == staged,
                "R106 owner overlay changes staged path census")
        require(subprocess.check_output(["git", "-C", str(linux), "diff", "--name-only"]) == unstaged,
                "unexpected unstaged change")
        helper.step(state, evidence, "r106-owner-diff-check", ["git", "diff", "--cached", "--check"], linux)
        state["r106_mm_postimage"] = post
        require("return -EACCES;" in function(mm.read_text(), "swapz_mm_trial_scope_publish"),
                "frozen MM admission denial absent")
        (evidence / "unified-r106.diff").write_bytes(subprocess.check_output(
            ["git", "-C", str(linux), "diff", "--cached", "--binary"]))
        with tempfile.TemporaryDirectory(prefix="r107-controller-") as directory:
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
        print("R107_A3_PASS AUTH0 DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)[:400]
        print("R107_A3_FIRST_ERROR", state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")

if __name__ == "__main__":
    sys.exit(main())
