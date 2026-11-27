#!/usr/bin/env python3
"""R110 A11: exact connected source composition then private DM preflight."""
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
FREEZE = "1ede7cfc7be8e870cadf34afec7a655d4630750e"
TREE = "aca15a12f4691651fd6918935816d67620ac571e"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TASK = "62e5ae4bd5fe07cd0c0dfe0f1c3ea3068d570b50"
STAGE = "tests/tools/round110-connected-preflight-stage.py"
STAGE_PIN = "b2ab565043799e96adc374aeb4cdaacbce45c1df"
PATCH = ROOT / "tests/tools/round110-original-dm-composed-preflight.patch"
PATCH_PIN = "61a83b92c43be93d0a3ebffe614de4bc8ebe8660"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round110-dm-composed-preflight.c"
FIXTURE_PIN = "4c50c74227e401e34c901c0ebccc02c91067ca7a"
DM = "drivers/md/dm.c"
PRE = "332fc3faf1ad05f3756bf7d90b476f28bd50a012"
POST = "5e446e6b80f5744e082ed13a506506499ecb854f"
GUARD = "SWAPZ_ROUND110_COMPOSED_PREFLIGHT_TEST"
MODES = ("success", "invalid", "lifecycle", "topology", "failures", "races")
IMPORTS = {"swapz_mm_trial_area_preflight", "swapz_trial_controller_query_registered"}
PRIVATE = "dm_swapz_combined_preflight"

def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(path.is_file() and not path.is_symlink() and blob(path.read_bytes()) == expected,
            "blob mismatch " + str(path.name))


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), "--no-replace-objects", *args])


def extract(source):
    start = "#ifdef " + GUARD + "\n"
    end = "/*\n * Swap in a new table, returning the old one"
    require(source.count(start) == 1 and source.count(end) == 1, "DM extraction anchors")
    block = source[source.index(start):source.index(end)]
    require(block.endswith("#endif\n\n"), "DM extraction boundary")
    return block[:-1]


def function(source, name):
    match = re.search(r"(?m)^(?:static )?int " + re.escape(name) + r"\([^;]*?\)\n\{", source)
    require(match is not None, "frozen function " + name)
    return source[match.start():source.index("\n}", match.end()) + 2]


def stage(state, evidence, inputs, frozen, historical, baseline, linux, module):
    pin(PATCH, PATCH_PIN)
    pin(FIXTURE, FIXTURE_PIN)
    # Use the exact A1 helper as published, not a substitute stage.
    stage_path = ROOT / STAGE
    pin(stage_path, STAGE_PIN)
    require(git(ROOT, "show", TASK + ":" + STAGE) == stage_path.read_bytes(),
            "A1 task helper differs")
    spec = importlib.util.spec_from_file_location("r110_a1_stage", stage_path)
    compose = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compose)
    history = evidence / "composition"
    history.mkdir()
    state["phase"] = "A1-composition-stage-first"
    previous = {"completed_steps": []}
    try:
        helper = compose.stage(previous, history, inputs, frozen, historical, baseline, linux, module)
    finally:
        state["composition"] = previous
    require(previous["stage"] == "PASS_R110_COMPOSED_SOURCE_ONLY", "A1 composition stage")
    print("R110_A11_A1_COMPOSITION_PASS", flush=True)
    pin(linux / DM, PRE)
    before = (linux / DM).read_text()
    staged = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, expected in (("check", ["--check"], PRE), ("apply", [], POST),
                                  ("reverse-check", ["--reverse", "--check"], POST),
                                  ("reverse", ["--reverse"], PRE), ("reapply", [], POST)):
        helper.step(state, evidence, "r110-dm-" + label, command + args + [str(PATCH)], linux)
        pin(linux / DM, expected)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            staged | {DM}, "DM staged path census")
    require(not git(linux, "diff", "--name-only") and
            not git(linux, "ls-files", "--others", "--exclude-standard"), "dirty Linux source")
    helper.step(state, evidence, "r110-dm-diff-check", ["git", "diff", "--cached", "--check"], linux)
    after = (linux / DM).read_text()
    block = extract(after)
    require(after.replace(block + "\n", "", 1) == before, "guard-off source differs")
    require(after.count(PRIVATE + "(") == 1 and not any(word in block for word in
            ("EXPORT_SYMBOL", "get_file(", "fput(", "dm_get(", "dm_put(",
             "scope_publish(", "retire_registered(", "submit_bio(")), "unexpected ownership or caller")
    for name, meta in previous["linux_stage"].items():
        pin(linux / name, POST if name == DM else meta["blob"])
    for name, meta in previous["module_stage"].items():
        pin(module / name, meta["blob"])
    glue = linux / helper.GLUE_DIR
    controller = glue / "native-observation-controller.c"
    target = module / "dm-target.c"
    pin(controller, "0ea943f55449cacae473c182f33e75c48eb371bb")
    pin(target, "5ecc477dc6c795d89e2a67ad2f6424a94d314b2d")
    query = function(controller.read_text(), "swapz_trial_controller_query_registered")
    callback = function(target.read_text(), "swapz_scope_query_controller")
    require(query.index("mutex_lock(&swapz_target_ops_lock)") < query.index("ops->query(") <
            query.index("mutex_unlock(&swapz_target_ops_lock)") < query.index("module_put(owner)"),
            "frozen registry query order")
    require(callback.index("spin_lock_irqsave(&ctx->queue_lock") < callback.index("rcu_read_lock()") <
            callback.index("dm_swapz_round090_route_live(") < callback.index("rcu_read_unlock()") <
            callback.index("spin_unlock_irqrestore(&ctx->queue_lock"), "frozen queue/RCU query order")
    require(not any(word in query + callback for word in
            ("suspend_lock", "dm_suspend(", "dm_resume(", "dm_sync_table(", "fput(", "dm_put_device(")),
            "unexpected reverse lock or file release in query")
    require(block.index("mutex_lock(&md->suspend_lock)") < block.index("dm_get_live_table(") <
            block.index("swapz_mm_trial_area_preflight(") <
            block.index("swapz_trial_controller_query_registered(") <
            block.rindex("swapz_mm_trial_area_preflight(") <
            block.index("dm_put_live_table(") < block.index("mutex_unlock(&md->suspend_lock)"),
            "native composed query lock order")
    state["stage"] = "PASS_EXACT_R110_COMPOSITION_AND_DM_ROUNDTRIP"
    state["postimage"] = POST
    state["audit"] = {"guard_off": "BYTE_EXACT", "caller": "ABSENT",
                      "frozen_query_lock_order": "REGISTRY_QUEUE_RCU",
                      "admission": "ABSENT", "retained_references": "NONE"}
    (evidence / "r110-final.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    print("R110_A11_STAGE_PASS", POST, flush=True)
    return helper


MUTANTS = (
    ("no-clear", "*result = (struct dm_swapz_preflight){};",
     "/* stale output */", "invalid"),
    ("page-zero", "!first_sector || (first_sector & 7)", "(first_sector & 7)", "invalid"),
    ("range-bound", "sector_count > 16 * 8 || ", "", "invalid"),
    ("overflow", "sector_count > (sector_t)-1 - first_sector", "false", "invalid"),
    ("partition", "!bdev || bdev_is_partition(bdev)", "!bdev", "invalid"),
    ("wrong-disk", "md->disk->private_data == md &&", "true &&", "lifecycle"),
    ("final-reservation", "dm_swapz_final.md != md;", "true;", "lifecycle"),
    ("suspend", "!dm_suspended_md(md) &&", "true &&", "lifecycle"),
    ("deferred", "!test_bit(DMF_DEFERRED_REMOVE, &md->flags) &&", "true &&", "lifecycle"),
    ("wrong-table-owner", "dm_table_get_md(table) != md ||", "false ||", "topology"),
    ("wrong-target", 'strcmp(target->type->name, "swapz") ||', "false ||", "topology"),
    ("table-range", "sector_count > table_size - first_sector", "false", "topology"),
    ("target-epoch", "!route.registration_epoch ||", "false ||", "failures"),
    ("target-range", "route.sector_count != sector_count", "false", "failures"),
    ("mm-epoch", "before.area_epoch != after.area_epoch ||", "false ||", "races"),
    ("mm-type", "before.swap_type != after.swap_type ||", "false ||", "races"),
    ("late-table", "rcu_dereference_protected(md->map,\n\t\t\t\tlockdep_is_held(&md->suspend_lock)) != table ||",
     "false ||", "races"),
    ("late-lifecycle", "!dm_swapz_preflight_live(md, bdev))\n\t\tgoto put_table;",
     "false)\n\t\tgoto put_table;", "races"),
    ("no-borrow-release", "dm_put_live_table(md, srcu_idx);",
     "if (false) dm_put_live_table(md, srcu_idx);", "success"),
    ("release-order", "dm_put_live_table(md, srcu_idx);\nunlock:\n\tmutex_unlock(&md->suspend_lock);",
     "mutex_unlock(&md->suspend_lock);\n\tdm_put_live_table(md, srcu_idx);\n\treturn error;\nunlock:\n\tmutex_unlock(&md->suspend_lock);", "success"),
)


def host(helper, state, evidence, linux, scratch):
    model = scratch / "host"
    model.mkdir()
    source = extract((linux / DM).read_text())
    require(blob(source.encode()) == "7f3c7493373219340c489d3a6baf88bd747ae4e2",
            "actual extracted source hash")
    header = model / "actual-composed.h"
    header.write_text(source)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(model), str(FIXTURE), "-o", str(binary)]
        result = {"compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                  "modes": {}, "mutants": {}}
        state["host"][compiler] = result
        helper.step(state, evidence, compiler + "-compile", command + ["-D" + GUARD], timeout=180)
        for mode in MODES:
            case = compiler + "-" + mode
            helper.step(state, evidence, case, [str(binary), mode])
            match = re.fullmatch(r"R110_A11_HOST_ONLY mode=" + re.escape(mode) + r" checks=(\d+) AUTH0\n",
                                 (evidence / (case + ".log")).read_text())
            require(match, "host output " + case)
            result["modes"][mode] = int(match[1])
            print("R110_A11_HOST_PASS", case, match[1], flush=True)
        for name, before, after, mode in MUTANTS:
            require(source.count(before) == 1, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                header.write_text(source.replace(before, after))
                helper.step(state, evidence, label + "-compile", command + ["-D" + GUARD], timeout=180)
                run = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(run.stdout)
                require(run.returncode == 77 and b"R110_A11_FIRST_ERROR" in run.stdout,
                        "surviving mutant " + label)
                result["mutants"][name] = {"exit": run.returncode,
                    "first_error": run.stdout.decode().splitlines()[0]}
                print("R110_A11_MUTANT_REJECTED", label, flush=True)
            finally:
                header.write_text(source)
    state["host_status"] = "PASS_ACTUAL_EXTRACTED_HOST_ONLY"


def native(helper, state, evidence, linux, build, module):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.MODULE_GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND098_SCOPED_TARGET_TEST"
              " -DSWAPZ_ROUND102_CONTROLLER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST"
              " -DSWAPZ_ROUND104_INTEGRATION_TEST -DSWAPZ_ROUND106_ADMITTED_OWNER_TEST"
              " -DSWAPZ_ROUND107_FINAL_REMOVAL_TEST -I" + str(glue) +
              ' -DSWAPZ_BUILD_SOURCE_SHA=\\"6394bf9aec7709744caf294f8bd7e935ca481dcd\\" -DSWAPZ_BUILD_SOURCE_CLEAN=1')
    state["native_guards"] = guards.replace(str(glue), helper.GLUE_DIR)
    build.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(build), "ARCH=x86_64", "CC=gcc"]
    helper.step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(build / ".config")]
    required = (*helper.REQUIRED, "MODULE_UNLOAD")
    off = ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
           "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU", "MODULE_FORCE_UNLOAD")
    for key in required:
        config += ["--enable", key]
    for key in off:
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "configure", config)
    helper.step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(data)
    lines = data.decode().splitlines()
    require(all("CONFIG_" + key + "=y" in lines for key in required) and
            all("CONFIG_" + key + "=y" not in lines for key in off) and
            "CONFIG_NR_CPUS=4" in lines, "SMP/TREE_RCU default-off config")
    state["config"] = helper.image(build / ".config")
    state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    print("R110_A11_CONFIG", json.dumps(state["config"]), state["compiler"], flush=True)
    state["objects"] = {}
    for enabled in (False, True):
        label = "guard-on" if enabled else "guard-off"
        flags = guards + (" -DSWAPZ_ROUND109_AREA_PREFLIGHT_TEST -D" + GUARD if enabled else "")
        helper.step(state, evidence, label + "-changed-dm-object",
                    make + ["KCFLAGS=" + flags, "-j2", "drivers/md/dm.o"], timeout=1000)
        source = build / "drivers/md/dm.o"
        destination = evidence / "objects" / label / "dm.o"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)
        state["objects"][label] = helper.image(source)
        symbols = subprocess.check_output(["nm", str(source)], text=True)
        relocs = subprocess.check_output(["readelf", "-rW", str(source)], text=True)
        (evidence / (label + "-dm.symbols")).write_text(symbols)
        (evidence / (label + "-dm.relocs")).write_text(relocs)
        rows = [line.split() for line in symbols.splitlines() if line.split()]
        local = {row[-1] for row in rows if len(row) == 3 and row[1] == "t"}
        undefined = {row[-1] for row in rows if len(row) == 2 and row[0] == "U"}
        relocation_names = {token for line in relocs.splitlines() for token in line.split()}
        require((PRIVATE in local) == enabled and (IMPORTS & undefined) ==
                (IMPORTS if enabled else set()) and (IMPORTS & relocation_names) ==
                (IMPORTS if enabled else set()) and "__ksymtab_" + PRIVATE not in symbols,
                "private local symbol/import/relocation census " + label)
        require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists()
                and not (module / "dm-swapz.ko").exists(), "unexpected full link")
        print("R110_A11_NATIVE_OBJECT", label, json.dumps(state["objects"][label]), flush=True)
    pin(linux / DM, POST)
    state["native"] = "PASS_CHANGED_DM_OBJECT_GUARD_ON_AND_OFF"


def main():
    os.umask(0o077)
    inputs, frozen, historical, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 110, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "freeze_tree": TREE, "linux": LINUX, "AUTH": 0,
             "phase_a": "BLOCKED", "native_link": "NOT_RUN", "stage": "NOT_RUN",
             "native": "NOT_RUN", "host_status": "NOT_RUN", "completed_steps": [],
             "status": "FAIL", "first_error": None}
    try:
        require(git(ROOT, "rev-parse", FREEZE + "^{tree}").decode().strip() == TREE, "freeze tree")
        require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux pin")
        with tempfile.TemporaryDirectory(prefix="r110-a11-") as temp:
            scratch = Path(temp)
            module = scratch / "module"
            helper = stage(state, evidence, inputs, frozen, historical, baseline, linux, module)
            errors = []
            for action, args in ((host, (helper, state, evidence, linux, scratch)),
                                 (native, (helper, state, evidence, linux, scratch / "build", module))):
                try:
                    action(*args)
                except Exception as error:
                    errors.append(str(error))
            require(not errors, "; ".join(errors))
        state["status"] = "PASS_COMPOSED_PREFLIGHT_ONLY_ADMISSION_BLOCKED"
        print("R110_A11_PASS AUTH0 HOST_AND_DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)
        print("R110_A11_FIRST_ERROR", error, file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
