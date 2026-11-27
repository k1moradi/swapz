#!/usr/bin/env python3
"""R107 A11: pinned original DM final-removal seam, extracted host and dm.o only."""
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
FREEZE = "0c908d5506f75a430171c627cd28b9994ff5765e"
TREE = "726cdb128b39ec60087a2f14cf9d81522d1940ee"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TOOLS = ROOT / "tests/tools"
PRIOR = TOOLS / "round106-mm-owner-boundary-verify.py"
PATCH = TOOLS / "round107-original-dm-final-removal.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round107-dm-final-removal.c"
DM = "drivers/md/dm.c"
PRE = "6912eb7ec5a9ef325f7282ef9c9226b39265f01d"
POST = "332fc3faf1ad05f3756bf7d90b476f28bd50a012"
PATCH_PIN = "7d761ce14c8f452c277d945381e15a02227ed2c2"
FIXTURE_PIN = "7f3bebc2706e47a1686be321899a665c6979b74a"
PRIOR_PIN = "56bad5e8e15eedebb147981d780d57d3d928da22"
GUARD = "SWAPZ_ROUND107_FINAL_REMOVAL_TEST"
MODES = ("ordinary", "preflight", "close-wait", "reentry", "retry",
         "quarantine", "stale-key", "stale-after", "late-pending")


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


def frozen_file(path, expected):
    data = git(ROOT, "show", FREEZE + ":" + path)
    require(blob(data) == expected, "frozen source " + path)
    return data


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:__used noinline )?"
                               r"(?:bool|int|void|struct dm_table \*)\s*" +
                               re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "actual function anchor " + name)
    match = matches[0]
    return source[match.start():source.index("\n}", match.end()) + 2]


def extract(source):
    begin = "#ifdef " + GUARD + "\n/* One private"
    end = "static void do_deferred_remove(struct work_struct *w);"
    seam_begin = "#ifdef " + GUARD + "\nstatic bool dm_swapz_final_drained"
    seam_end = "/*\n * Swap in a new table, returning the old one"
    for anchor in (begin, end, seam_begin, seam_end):
        require(source.count(anchor) == 1, "actual extraction anchor")
    return (source[source.index(begin):source.index(end)] +
            "".join(function(source, name) + "\n\n" for name in
                    ("dm_blk_open", "dm_lock_for_deletion")) +
            source[source.index(seam_begin):source.index(seam_end)] +
            "".join(function(source, name) + "\n\n" for name in
                    ("__dm_destroy", "dm_swap_table", "dm_resume")))


def guard_off(source):
    depth = 0
    lines = []
    for line in source.splitlines(keepends=True):
        if not depth and line.strip() == "#ifdef " + GUARD:
            depth = 1
        elif depth:
            if re.match(r"^#if(?:def|ndef)?\b", line):
                depth += 1
            elif re.match(r"^#endif\b", line):
                depth -= 1
        else:
            lines.append(line)
    require(not depth, "unclosed guard")
    # Only guard insertion whitespace may differ; compare all other bytes.
    return re.sub(r"\n{3,}", "\n\n", "".join(lines))


def audit(before, after, linux):
    require(guard_off(after) == guard_off(before), "unguarded DM source changed")
    require(after.count("dm_swapz_retire_final_table(") == 1 and
            after.count("swapz_trial_controller_retire_registered(target, &key)") == 1 and
            "EXPORT_SYMBOL_GPL(dm_swapz_retire_final_table)" not in after,
            "private seam must have no installed caller or export")
    for name in ("dm_suspend", "__dm_internal_suspend", "__dm_internal_resume",
                 "dm_internal_suspend_fast", "dm_internal_resume_fast", "dm_blk_close"):
        require(function(before, name) == function(after, name),
                "ordinary lifecycle path changed " + name)
    pin(linux / "drivers/md/dm-ioctl.c", "8f945f0aeda5d6af52134a1c2920d16af9fe7980")
    ioctl = (linux / "drivers/md/dm-ioctl.c").read_text()
    require(ioctl.count("dm_destroy_immediate(md);") == 1 and
            "dm_hash_remove_all(0);" in ioctl and
            "DM_REMOVE_KEEP_OPEN_DEVICES | DM_REMOVE_ONLY_DEFERRED" in ioctl and
            "DM_REMOVE_KEEP_OPEN_DEVICES | DM_REMOVE_INTERRUPTIBLE" in ioctl and
            "r = dm_lock_for_deletion(md," in ioctl,
            "native ordinary/deferred/forced caller census")
    controller = frozen_file("src/kernel/native-observation-controller.c",
                             "556b99a0d04e3027c3027c387a0a9552e22a19ec").decode()
    target = frozen_file("src/kernel/dm-target.c", "b17a17c1096eaa6f43bf42a18c009b8d379e080b").decode()
    retire = function(controller, "swapz_trial_controller_retire_registered")
    require(retire.index("ops->validate_retire(target, retained)") <
            retire.index("swapz_controller_detach(retained)") <
            retire.index("ops->retire(target, retained, &released_mapper)") <
            retire.index("fput(released_mapper)") <
            retire.index("module_put(owner)"),
            "frozen registered callback order")
    require(retire.rfind("mutex_unlock(&swapz_target_ops_lock);") <
            retire.index("fput(released_mapper)"), "frozen file drop outside registry")
    validate = function(target, "swapz_scope_validate_retire_controller")
    require(all("key->" + field + " != retained->" + field in validate for field in
                ("identity", "session", "epoch", "target_epoch", "registration_epoch")),
            "frozen target exact key validation")
    return {"unguarded_source": "UNCHANGED", "private_caller": "ABSENT_AUTH0",
            "native_open_count_gate": "PRESERVED", "ordinary_suspend": "UNCHANGED",
            "frozen_callback": "EXACT_R106", "forced_live_removal": "BUILTIN_ONLY_GUARDED",
            "authority": "ABSENT", "native_runtime": "NOT_RUN"}


def stage(state, evidence, frozen, baseline, linux):
    pin(PRIOR, PRIOR_PIN)
    pin(PATCH, PATCH_PIN)
    pin(FIXTURE, FIXTURE_PIN)
    spec = importlib.util.spec_from_file_location("r107_r106_frozen", PRIOR)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    historical = evidence / "r106-stage"
    historical.mkdir()
    previous = {"completed_steps": []}
    helper = prior.stage(previous, historical, frozen, baseline, linux)
    require(previous["stage"] == "PASS", "R106 historical stage only")
    state["historical_stage"] = previous
    pin(linux / DM, PRE)
    pin(linux / "mm/zswap.c", "9e1efceae44c384370d0aa3e25748d127a5cd4ad")
    before = (linux / DM).read_text()
    staged = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    unstaged = set(git(linux, "diff", "--name-only").decode().splitlines())
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, expected in (("check", ["--check"], PRE), ("apply", [], POST),
                                  ("reverse-check", ["--reverse", "--check"], POST),
                                  ("reverse", ["--reverse"], PRE), ("reapply", [], POST)):
        helper.step(state, evidence, "r107-" + label, command + args + [str(PATCH)], linux)
        pin(linux / DM, expected)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            staged | {DM}, "staged path census")
    require(set(git(linux, "diff", "--name-only").decode().splitlines()) == unstaged,
            "unstaged path census")
    helper.step(state, evidence, "r107-staged-diff-check", ["git", "diff", "--cached", "--check"], linux)
    state["audit"] = audit(before, (linux / DM).read_text(), linux)
    # Only exact frozen declarations; no current-round peer source.
    glue = linux / helper.GLUE_DIR
    for name, sha in (("native-observation-owner.h", "dad3cbe3ff93ef2a2bf56bb2b7eef4a6a64e60cb"),
                      ("native-observation-adapter.h", "ffa547fbecad79b3fabf0ded4bb182c201e4a33d"),
                      ("native-observation-integration.h", "e3bca3367459c7f79960105f63e9ddef4e95b4d6"),
                      ("native-observation-controller.h", "dac2e2844d893b0090b4c1da3614e4a8d0cc2253")):
        (glue / name).write_bytes(frozen_file("src/kernel/" + name, sha))
        pin(glue / name, sha)
    state["stage"] = "PASS_EXACT_APPLY_REVERSE_REAPPLY"
    state["postimage"] = POST
    (evidence / "unified-r107.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    print("R107_A11_STAGE_PASS", POST, flush=True)
    return helper


MUTANTS = (
    ("false-close", "else if (!drained || dm_open_count(md) || dm_swapz_final_pending(md))",
     "else if (!drained || dm_swapz_final_pending(md))", "close-wait"),
    ("native-open-bypass", "if (dm_open_count(md)) {", "if (false) {", "ordinary"),
    ("normal-suspend-gate", "return dm_suspended_md(md) && !dm_suspended_internally_md(md) &&",
     "return !dm_suspended_internally_md(md) &&", "preflight"),
    ("resume-race", "if (dm_swapz_final_fenced(md)) {\n\t\tr = -EBUSY;",
     "if (dm_swapz_final_fenced(md) && false) {\n\t\tr = -EBUSY;", "reentry"),
    ("replace-race", "if (dm_swapz_final_fenced(md)) {\n\t\tmap = ERR_PTR(-EBUSY);",
     "if (dm_swapz_final_fenced(md) && false) {\n\t\tmap = ERR_PTR(-EBUSY);", "reentry"),
    ("second-remover", "dm_swapz_final.phase != DM_SWAPZ_FINAL_READY ||",
     "false ||", "reentry"),
    ("fresh-open", "if (dm_swapz_final.md == md) {\n\t\tmd = NULL;",
     "if (dm_swapz_final.md == md && false) {\n\t\tmd = NULL;", "reentry"),
    ("missing-holder", "dm_get(md);\n\t\tdm_swapz_final.md = md;",
     "if (false) dm_get(md);\n\t\tdm_swapz_final.md = md;", "close-wait"),
    ("double-holder-drop", "if (release_holder)\n\t\tdm_put(md);",
     "if (release_holder) {\n\t\tdm_put(md);\n\t\tdm_put(md);\n\t}", "close-wait"),
    ("holder-drop-under-lock", "mutex_unlock(&md->suspend_lock);\n\tif (release_holder)\n\t\tdm_put(md);",
     "if (release_holder)\n\t\tdm_put(md);\n\tmutex_unlock(&md->suspend_lock);", "close-wait"),
    ("stale-registration", "key->registration_epoch == dm_swapz_final.key.registration_epoch;",
     "true;", "close-wait"),
    ("stale-table-after-callback", "if (!same_table || test_bit(DMF_FREEING, &md->flags) ||",
     "if ((!same_table && false) || test_bit(DMF_FREEING, &md->flags) ||", "stale-after"),
    ("callback-error-retry", "if (error && error != -EBUSY) {",
     "if (error && error != -EBUSY && false) {", "quarantine"),
    ("repeat-retired-callback", "invoke = dm_swapz_final.phase == DM_SWAPZ_FINAL_RETRY;",
     "invoke = true;", "close-wait"),
    ("ignore-late-pending", "else if (!drained || dm_open_count(md) || dm_swapz_final_pending(md))",
     "else if ((!drained && false) || dm_open_count(md))", "late-pending"),
    ("premature-dtr-proof", "\tdm_table_destroy(__unbind(md));",
     "#ifdef SWAPZ_ROUND107_FINAL_REMOVAL_TEST\n"
     "\tif (dm_swapz_final.md == md)\n\t\tdm_swapz_final.phase = DM_SWAPZ_FINAL_DESTROYED;\n"
     "#endif\n\tdm_table_destroy(__unbind(md));", "close-wait"),
)


def host(helper, state, evidence, linux, scratch):
    model = scratch / "host"
    model.mkdir()
    source = extract((linux / DM).read_text())
    require(blob(source.encode()) == "b44742c3850abb7dc94736b7d25f992b778b16b1",
            "actual extracted source hash")
    header = model / "actual-dm-final-removal.h"
    header.write_text(source)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        # dm_blk_open's original blk_mode_t parameter is intentionally unused.
        command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-parameter", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(model), str(FIXTURE), "-o", str(binary)]
        result = {"compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                  "modes": {}, "mutants": {}}
        state["host"][compiler] = result
        for enabled in (False, True):
            selected = command + (["-D" + GUARD] if enabled else [])
            label = compiler + ("-guard-on" if enabled else "-guard-off")
            helper.step(state, evidence, label + "-compile", selected, timeout=180)
            for mode in (MODES if enabled else ("ordinary",)):
                case = label + "-" + mode
                helper.step(state, evidence, case, [str(binary), mode])
                match = re.fullmatch(r"R107_A11_HOST_ONLY mode=" + re.escape(mode) + r" checks=(\d+) AUTH0\n",
                                     (evidence / (case + ".log")).read_text())
                require(match, "host output " + case)
                result["modes"][case] = int(match[1])
                print("R107_A11_HOST_PASS", case, match[1], flush=True)
        for name, before, after, mode in MUTANTS:
            require(source.count(before) == 1, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                header.write_text(source.replace(before, after))
                helper.step(state, evidence, label + "-compile", command + ["-D" + GUARD], timeout=180)
                run = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(run.stdout)
                require(run.returncode == 77 and b"R107_A11_FIRST_ERROR" in run.stdout,
                        "surviving mutant " + label)
                result["mutants"][name] = {"exit": run.returncode,
                    "first_error": run.stdout.decode().splitlines()[0]}
                print("R107_A11_MUTANT_REJECTED", label, flush=True)
            finally:
                header.write_text(source)
    state["host_status"] = "PASS_ACTUAL_EXTRACTED_HOST_ONLY"


def native(helper, state, evidence, linux, build):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND102_CONTROLLER_TEST"
              " -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST -DSWAPZ_ROUND104_INTEGRATION_TEST"
              " -DSWAPZ_ROUND106_ADMITTED_OWNER_TEST -I" + str(glue))
    state["native_guards"] = guards.replace(str(glue), helper.GLUE_DIR)
    build.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(build), "ARCH=x86_64", "CC=gcc"]
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
    data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(data)
    lines = data.decode().splitlines()
    for key in helper.REQUIRED:
        require("CONFIG_" + key + "=y" in lines, "missing " + key)
    require("CONFIG_NR_CPUS=4" in lines and not any("CONFIG_" + key + "=y" in lines
            for key in ("TINY_RCU", "ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON")),
            "default-off SMP/TREE_RCU")
    state["config_sha256"] = hashlib.sha256(data).hexdigest()
    state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    state["objects"] = {}
    print("R107_A11_CONFIG_SHA256", state["config_sha256"], state["compiler"], flush=True)
    for enabled in (False, True):
        label = "guard-on" if enabled else "guard-off"
        flags = guards + (" -D" + GUARD if enabled else "")
        helper.step(state, evidence, label + "-changed-dm-object",
                    make + ["KCFLAGS=" + flags, "-j2", "drivers/md/dm.o"], timeout=1000)
        source = build / "drivers/md/dm.o"
        destination = evidence / "objects" / label / "dm.o"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)
        symbols = subprocess.check_output(["nm", str(source)], text=True)
        (evidence / (label + "-dm.o.symbols")).write_text(symbols)
        local = re.search(r"(?m)\bt dm_swapz_retire_final_table(?:\.[^\s]+)?$", symbols)
        callback = re.search(r"(?m)\bU swapz_trial_controller_retire_registered$", symbols)
        require(bool(local) == enabled and bool(callback) == enabled and
                "__ksymtab_dm_swapz_retire_final_table" not in symbols,
                "private guarded native symbol census " + label)
        require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(),
                "unexpected link")
        state["objects"][label] = helper.image(source)
        print("R107_A11_NATIVE_OBJECT", label, json.dumps(state["objects"][label]), flush=True)
    pin(linux / DM, POST)
    state["native"] = "PASS_CHANGED_DM_OBJECT_GUARD_ON_AND_OFF"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 107, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "freeze_tree": TREE, "linux": LINUX, "AUTH": 0,
             "phase_a": "BLOCKED", "native_link": "NOT_RUN", "stage": "NOT_RUN",
             "native": "NOT_RUN", "host_status": "NOT_RUN", "completed_steps": [],
             "status": "FAIL", "first_error": None}
    try:
        require(git(ROOT, "rev-parse", FREEZE + "^{tree}").decode().strip() == TREE, "freeze tree")
        require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux pin")
        helper = stage(state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r107-a11-") as temp:
            scratch = Path(temp)
            errors = []
            for action, args in ((host, (helper, state, evidence, linux, scratch)),
                                 (native, (helper, state, evidence, linux, scratch / "build"))):
                try:
                    action(*args)
                except Exception as error:
                    errors.append(str(error))
            require(not errors, "; ".join(errors))
        state["status"] = "PASS_PRIVATE_SEAM_ONLY_ADMISSION_BLOCKED"
        print("R107_A11_PASS AUTH0 HOST_AND_DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)
        print("R107_A11_FIRST_ERROR", error, file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
