#!/usr/bin/env python3
"""Exact R103 external MM/core join: changed objects and actual-source host only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "e65d7042b41880c6fef99069d7f65bf6fb4356d4"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGE_FREEZE = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
STAGE_TOOL = "tests/tools/round102-unified-stage-verify.py"
STAGE_PIN = "20e6681c00ada2e72fc53d5dd6bc8073b1c4bf58"
HELPER = "tests/tools/round098-smp-directed-native-compile-verify.py"
HELPER_PIN = "96e6750971c182dfe87e6e57eac048c7c3a529b6"
PATCH = "tests/tools/round103-original-area-terminal-join.patch"
PATCH_PIN = "5c5e52add5976a96987de22d12cdaacad332f142"
FIXTURE = "tests/runtime/native/fixtures/round103-external-join.c"
FIXTURE_PIN = "11f7d56a8d934118f633f49dfe10898262b9ad50"
IMAGES = {
    "mm/zswap.c": ("fcb2f7487cb7ed02ae8ca9a8d486909f721a2ef6", "833f089bc01e8803f427732975d706c894436eb3"),
    "mm/page_io.c": ("08c11d2f9a16a322093b305afa10ba011f67fc2b", "5c3ebb46e2d885b0d3ab492a796996c004954d79"),
    "mm/swapfile.c": ("254ce86fa923e6b5f1fefda88c39315c4cc00642", "031a93193886b093045e4aa15456016da49a7a43"),
    "drivers/md/dm.c": ("f0c0cd4add03bf2b6f9bf37997444ecd08bbb83b", "e07dfd963edcdfb438af2ae1f43e3023e54544b7"),
    "include/linux/swapz_mm_carrier.h": ("f50911d4c1ff7f87b502cec042b90968ba3a282f", "7091e456b6c09f29d68140cfff3f072e940ccd2f"),
    "include/linux/swapz_trial_debt.h": (None, "207cd1b7a87f493992938cfa00ed4f95c7196811"),
    "mm/swapz-trial-terminal.inc": (None, "3f980d04958676c22d44a6ca2778c4bd40a464fb"),
}
FROZEN_CURRENT = {
    "src/kernel/dm-target.c": "087bec323ad59f365d77d3beaf1aa52907cfcfce",
    "src/kernel/native-observation-controller.c": "daa9bfcb321b2cc378994717a12f87a2c67c9b28",
    "src/kernel/native-observation-controller.h": "5dc62a0c7c3abc3999b8e16836a84bdbc2d8e061",
    "src/kernel/native-observation-byte-collector.c": "2fc41a64228b8f845192fd0107014f71b46391e3",
    "src/kernel/native-observation-byte-collector.h": "62fdf6f74709f958a3cd10d0faaa3191c40da1d1",
}
OBJECTS = ("mm/zswap.o", "mm/page_io.o", "mm/swapfile.o", "drivers/md/dm.o")
MODES = ("normal", "reopen", "wrong-completion", "split", "late", "overflow",
         "publish-race", "publish-quarantine")


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    if expected is None:
        require(not path.exists() and not path.is_symlink(), "unexpected new preimage " + path.name)
        return
    require(path.is_file() and not path.is_symlink(), "missing pinned file " + path.name)
    require(blob(path.read_bytes()) == expected, "blob mismatch " + path.name)


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), "--no-replace-objects", *args])


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:inline )?(?:bool|int|void|u64)\s+" +
                               re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    match = matches[0]
    return source[match.start():source.index("\n}", match.end()) + 3]


def ordered(code, anchors, reason):
    positions = []
    for anchor in anchors:
        require(code.count(anchor) == 1, reason + ": " + anchor)
        positions.append(code.index(anchor))
    require(positions == sorted(positions), reason)


def source_checks(linux):
    swapfile = (linux / "mm/swapfile.c").read_text()
    page = (linux / "mm/page_io.c").read_text()
    core = (linux / "drivers/md/dm.c").read_text()
    mm = (linux / "mm/zswap.c").read_text()
    enable = function(swapfile, "_enable_swap_info")
    ordered(enable, ("swapz_mm_trial_area_online(si->type);", "add_to_avail_list(si, true);"),
            "area publication")
    start = swapfile.index("SYSCALL_DEFINE1(swapoff,")
    end = swapfile.index("\n}", start) + 3
    off = swapfile[start:end]
    ordered(off, ("swapz_mm_trial_area_offline(p->type);", "del_from_avail_list(p, true);",
                  "wait_for_allocation(p);", "try_to_unuse(p->type);", "percpu_ref_kill(&p->users);",
                  "synchronize_rcu();", "wait_for_completion(&p->comp);",
                  "flush_work(&p->discard_work);", "flush_work(&p->reclaim_work);",
                  "destroy_swap_extents(p, p->swap_file);", "zswap_swapoff(p->type);",
                  "swapz_mm_trial_area_retired(p->type);"), "actual swapoff join")
    require("reinsert_swap_info(p);" in off and "goto out_dput;" in off,
            "failed swapoff branch retained")
    add = function(page, "swap_add_folio")
    ordered(add, ("mempool_alloc(sio_pool, GFP_NOIO);",
                  "swapz_mm_trial_mm_enter(sis->bdev, sis->type, sio);",
                  "bvec_set_folio("), "SIO pre-submit debt")
    for name in ("swap_write_end", "swap_read_end"):
        code = function(page, name)
        ordered(code, ("swapz_mm_trial_mm_take(sio);", "mempool_free(sio, sio_pool);",
                       "swapz_mm_trial_mm_put(terminal_ticket);"), "terminal SIO " + name)
    submit = function(core, "dm_submit_bio")
    ordered(submit, ("swapz_mm_trial_dm_enter(bio);", "dm_get_live_table(md, &srcu_idx);",
                     "dm_split_and_process_bio(md, map, bio);", "dm_put_live_table(md, srcu_idx);",
                     "swapz_mm_trial_dm_leave(terminal_entrant);"), "DM original pre-reference entry")
    origin = function(core, "dm_swapz_trial_observation_origin")
    ordered(origin, ("!route_live", "swapz_mm_trial_dm_origin(bio, sector)",
                     "op_id = swapz_trial_observation_mint();"), "retained one-shot original")
    require("rcu_dereference(swapz_mm_capture_scope) ||\n\t    atomic_cmpxchg_acquire(&swapz_mm_busy, 0, 1)" in mm,
            "carrier busy acquisition joined to capture stop")
    return {"actual_swapoff_order": True, "sio_terminal_order": True,
            "core_pre_reference_order": True, "carrier_capture_order": True}


def load_helper():
    pin(ROOT / HELPER, HELPER_PIN)
    spec = importlib.util.spec_from_file_location("r103_frozen_helper", ROOT / HELPER)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return helper


def stage_source(helper, state, evidence, frozen, baseline, linux):
    pin(ROOT / STAGE_TOOL, STAGE_PIN)
    pin(ROOT / PATCH, PATCH_PIN)
    for path, expected in FROZEN_CURRENT.items():
        require(blob(git(ROOT, "show", FREEZE + ":" + path)) == expected, "R103 frozen product " + path)
    state["frozen_current_product_uncompiled"] = FROZEN_CURRENT
    state["frozen_current_product_note"] = "R101 target in unified base; R103 target/controller/collector pins checked only, never compiled or substituted"
    require(git(frozen, "rev-parse", "HEAD").decode().strip() == STAGE_FREEZE, "base freeze")
    prior = evidence / "unified-base"
    prior.mkdir()
    helper.step(state, evidence, "exact-unified-base", [sys.executable, "-B", str(ROOT / STAGE_TOOL),
                str(frozen), str(baseline), str(linux), str(prior)], timeout=400)
    manifest = json.loads((prior / "unified-manifest.json").read_text())
    require(manifest["status"] == "PASS_STAGE_ONLY" and manifest["linux"] == LINUX,
            "exact unified base verdict")
    require(manifest["authoritative_manifest"]["frozen_product"]["dm-target.c"] ==
            "46c2cb832ff0071a028a27b35f63daa84f29914f", "historical target pin")
    state["unified_base_manifest_sha256"] = hashlib.sha256((prior / "unified-manifest.json").read_bytes()).hexdigest()
    shutil.copyfile(prior / "unified-manifest.json", evidence / "unified-base-manifest.json")
    previous_paths = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    for path, (before, _) in IMAGES.items():
        pin(linux / path, before)
    patch = str(ROOT / PATCH)
    apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for name, options, index in (("check", ["--check"], 0), ("apply", [], 1),
                                 ("reverse-check", ["--reverse", "--check"], 1),
                                 ("reverse", ["--reverse"], 0), ("reapply", [], 1)):
        helper.step(state, evidence, "r103-" + name, apply + options + [patch], linux)
        for path, pair in IMAGES.items():
            pin(linux / path, pair[index])
    require(not git(linux, "diff", "--name-only"), "unexpected unstaged source")
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            previous_paths | set(IMAGES), "R103 exact staged path census")
    helper.step(state, evidence, "r103-staged-diff-check", ["git", "diff", "--cached", "--check"], linux)
    (evidence / "unified-r103.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    state["postimages"] = {path: helper.image(linux / path) for path in IMAGES}
    state["static_checks"] = source_checks(linux)
    state["stage"] = "PASS"


def host(helper, state, evidence, linux, scratch):
    pin(ROOT / FIXTURE, FIXTURE_PIN)
    mm = (linux / "mm/zswap.c").read_text()
    carrier = (linux / "include/linux/swapz_mm_carrier.h").read_text()
    swapfile = (linux / "mm/swapfile.c").read_text()
    model = scratch / "host"
    model.mkdir()
    scope = re.findall(r"(?ms)^struct swapz_mm_trial_scope \{\n.*?^\};", carrier)
    require(len(scope) == 1, "actual scope type")
    (model / "actual-scope-type.h").write_text(scope[0] + "\n")
    declarations = carrier[carrier.index("int swapz_mm_trial_area_get("):
                           carrier.index("\n#endif", carrier.index("int swapz_mm_trial_area_get("))]
    (model / "actual-area-declarations.h").write_text(declarations + "\n")
    (model / "actual-next.h").write_text(function(mm, "swapz_mm_next"))
    (model / "actual-scope-control.h").write_text(function(swapfile, "swapz_mm_trial_area_get") +
        "\n".join(function(mm, name) for name in ("swapz_mm_scope_valid", "swapz_mm_trial_scope_publish",
             "swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke")))
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        helper.step(state, evidence, compiler + "-host-compile", [compiler, "-std=gnu11",
                    "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-fno-omit-frame-pointer",
                    "-fno-pie", "-no-pie", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I" + str(model), "-I" + str(linux / "mm"), "-I" + str(linux / "include"),
                    str(ROOT / FIXTURE), "-o", str(binary)], timeout=180)
        state["host"][compiler] = {"version": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                                    "modes": {}}
        for mode in MODES:
            label = compiler + "-" + mode
            helper.step(state, evidence, label, [str(binary), mode])
            result = (evidence / (label + ".log")).read_text()
            match = re.fullmatch(r"R103_A11_HOST_ONLY mode=" + re.escape(mode) +
                                 r" checks=(\d+) grace=(\d+) AUTH0\n", result)
            require(match, "host result or sanitizer " + label)
            state["host"][compiler]["modes"][mode] = {"checks": int(match[1]), "graces": int(match[2])}
            print(result.strip(), flush=True)


def native(helper, state, evidence, linux, build):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST -I" + str(glue))
    state["native_guards"] = guards.replace(str(glue), helper.GLUE_DIR)
    build.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(build), "ARCH=x86_64", "CC=gcc", "KCFLAGS=" + guards]
    helper.step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(build / ".config")]
    for key in helper.REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
                "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "set-config", config)
    helper.step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    config_data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(config_data)
    lines = config_data.decode().splitlines()
    for key in helper.REQUIRED:
        require("CONFIG_" + key + "=y" in lines, "missing effective config " + key)
    require("CONFIG_NR_CPUS=4" in lines and "CONFIG_TINY_RCU=y" not in lines and
            "CONFIG_ZSWAP_DEFAULT_ON=y" not in lines and "CONFIG_ZSWAP_SHRINKER_DEFAULT_ON=y" not in lines,
            "SMP default-off effective config")
    state["config_sha256"] = hashlib.sha256(config_data).hexdigest()
    state["objects"] = {}
    try:
        helper.step(state, evidence, "changed-native-objects", make + ["-j2", *OBJECTS], timeout=1000)
    finally:
        for path in OBJECTS:
            source = build / path
            if source.is_file():
                destination = evidence / "objects" / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                state["objects"][path] = helper.image(source)
    require(set(state["objects"]) == set(OBJECTS), "missing directed objects")
    symbols = {
        "mm/zswap.o": ("swapz_mm_trial_scope_join_external", "swapz_mm_trial_dm_enter",
                       "swapz_mm_trial_mm_enter", "swapz_mm_trial_area_online"),
        "mm/page_io.o": ("swapz_mm_trial_mm_enter", "swapz_mm_trial_mm_take", "swapz_mm_trial_mm_put"),
        "mm/swapfile.o": ("swapz_mm_trial_area_online", "swapz_mm_trial_area_offline",
                          "swapz_mm_trial_area_retired", "swapz_mm_trial_area_get"),
        "drivers/md/dm.o": ("swapz_mm_trial_dm_enter", "swapz_mm_trial_dm_leave", "swapz_mm_trial_dm_origin"),
    }
    for path, names in symbols.items():
        output = subprocess.check_output(["nm", str(build / path)], text=True)
        (evidence / (Path(path).name + ".symbols")).write_text(output)
        require(all(re.search(r"\b" + name + r"\b", output) for name in names), "missing symbol " + path)
        (evidence / (Path(path).name + ".relocations")).write_bytes(
            subprocess.check_output(["readelf", "-Wr", str(build / path)]))
    for path, (_, after) in IMAGES.items():
        pin(linux / path, after)
    require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(),
            "unexpected full link")
    state["native"] = "PASS_DIRECTED_OBJECTS_ONLY"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 103, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
             "native_link": "NOT_RUN", "native": "NOT_RUN", "stage": "NOT_RUN",
             "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        helper = load_helper()
        stage_source(helper, state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r103-join-") as temp:
            scratch = Path(temp)
            first_error = None
            # Host failure is retained, but does not prevent independent native
            # changed-object diagnostics for the exact same staged source.
            try:
                host(helper, state, evidence, linux, scratch)
            except Exception as error:
                first_error = str(error)
            try:
                native(helper, state, evidence, linux, scratch / "build")
            except Exception as error:
                state["native_error"] = str(error).split("\n", 1)[0][:350]
                if first_error is None:
                    first_error = str(error)
            if first_error is not None:
                raise RuntimeError(first_error)
        state["status"] = "PASS_HOST_AND_DIRECTED_ONLY"
        print("R103_A11_PASS AUTH0 DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error).split("\n", 1)[0][:350]
        print("R103_A11_FIRST_ERROR " + state["first_error"], file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
