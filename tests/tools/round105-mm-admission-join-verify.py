#!/usr/bin/env python3
"""R105 A11 frozen MM/core source, focused host cases and changed objects only."""
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
FREEZE = "ae7dc02e5db07fc6d133e02ffd558cb68c8e3159"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TOOLS = ROOT / "tests/tools"
TERMINAL = "mm/swapz-trial-terminal.inc"
MM = "mm/zswap.c"
SWAPFILE = "mm/swapfile.c"
HEADER = "include/linux/swapz_mm_carrier.h"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round105-mm-admission-join.c"
PATCHES = (
    ("round105-original-mm-exact-query-export.patch", "3048e05e3f594dbaa6a10241fe1fa9c6092fbb54",
     {TERMINAL: ("1ecc86d30f20790f1fae7506a3f55d612200831a", "2bfc139f380461c71da78a8c7f9469d1e7eb0b22")}),
    ("round105-original-mm-terminal-correlation.patch", "ff20785a8b12780d94778b49aeaf0526ebfa1b80",
     {TERMINAL: ("2bfc139f380461c71da78a8c7f9469d1e7eb0b22", "b0acebd01b19ea0900300a609ffbf9448aec51d3")}),
    ("round105-original-mm-admission-join.patch", "c7870a4dca498b08b5fe42ab1d37325c6cffdd44",
     {TERMINAL: ("b0acebd01b19ea0900300a609ffbf9448aec51d3", "697f3c9fc51738fedabc58cefc4eee6fddc8358c"),
      MM: ("e088dd706763bec377d09a81905cf5de9b371c6a", "058389456ee1586f5a26d40f78cd5cde99312060"),
      SWAPFILE: ("031a93193886b093045e4aa15456016da49a7a43", "d20a7f0003405bd1450cc52af63a773c91ee86b6"),
      HEADER: ("b930f6f04a21d3f2b8b6f2279e028a94cfc99502", "bd88db905e5009e0e6161cad1d09b6d33bde2560")}),
)
MODES = ("accepted-before-offline", "offline-before-origin", "reused-epoch",
         "missing-correlation", "unobserved", "partial-correlation", "detach")
MUTANTS = (
    ("epoch", "swapz_mm_trial_area_epoch(scope->swap_type) == scope->area_epoch) {",
     "true) {", "offline-before-origin"),
    ("loss", "if (!ticket || missing_correlation)",
     "if (!ticket || (missing_correlation && false))", "missing-correlation"),
    ("snapshot", "if (!slot->ticket)\n\t\t\tcontinue;",
     "if (!slot->ticket || !slot->owner)\n\t\t\tcontinue;", "detach"),
    ("raw-bdev", "swapz_mm_scope_storage.bdev = NULL;",
     "/* mutant: retained raw bdev */", "detach"),
)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(path.is_file() and not path.is_symlink() and blob(path.read_bytes()) == expected,
            "blob mismatch: " + str(path))


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), "--no-replace-objects", *args])


def stage(state, evidence, frozen, baseline, linux):
    path = TOOLS / "round104-mm-core-witness-verify.py"
    pin(path, "4e7bea38ad8529eb47eaae8718aacd1c5fbf3fde")
    spec = importlib.util.spec_from_file_location("r105_frozen_r104", path)
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    r103 = previous.load_prior()
    helper = r103.load_helper()
    history = evidence / "r104-stage"
    history.mkdir()
    historical = {"completed_steps": []}
    previous.stage_source(r103, helper, historical, history, frozen, baseline, linux)
    require(historical["stage"] == "PASS", "historical stage")
    state["historical_stage"] = historical
    state["postimages"] = {}
    for name, expected, images in PATCHES:
        patch = TOOLS / name
        pin(patch, expected)
        for relative, pair in images.items():
            pin(linux / relative, pair[0])
        command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
        for label, options, side in (("check", ["--check"], 0), ("apply", [], 1),
                                     ("reverse-check", ["--reverse", "--check"], 1),
                                     ("reverse", ["--reverse"], 0), ("reapply", [], 1)):
            helper.step(state, evidence, name + "-" + label, command + options + [str(patch)], linux)
            for relative, pair in images.items():
                pin(linux / relative, pair[side])
        state["postimages"].update({relative: pair[1] for relative, pair in images.items()})
    helper.step(state, evidence, "staged-diff-check", ["git", "diff", "--cached", "--check"], linux)
    require(not git(linux, "diff", "--name-only"), "unexpected unstaged tracked changes")
    pin(linux / "include/linux/swapz_trial_debt.h", "d1d2fc65084936380c211094ce6f073273596338")
    # R105 frozen declarations, not moving-main peer implementations.
    glue = linux / helper.GLUE_DIR
    for name, expected in (("native-observation-integration.h", "e3bca3367459c7f79960105f63e9ddef4e95b4d6"),
                           ("native-observation-adapter.h", "ffa547fbecad79b3fabf0ded4bb182c201e4a33d"),
                           ("native-observation-owner.h", "68750e6b7e78f5bb236c968b3694a429bff6813f")):
        data = git(ROOT, "show", FREEZE + ":src/kernel/" + name)
        require(blob(data) == expected, "frozen declaration " + name)
        (glue / name).write_bytes(data)
    mm = (linux / MM).read_text()
    sf = (linux / SWAPFILE).read_text()
    require(sf.count("swapz_mm_trial_area_retired(p->type);") == 1, "retirement witness census")
    retirement = sf.index("swapz_mm_trial_area_retired(p->type);")
    require(sf.rfind("filp_close(", 0, retirement) >= 0 and
            sf.index("p->flags = 0;", retirement) > retirement, "retirement order")
    require(mm.count("swapz_mm_input_retire_unrepresented(") == 4, "input retirement census")
    state["stage"] = "PASS"
    (evidence / "unified-r105.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    return previous, helper


def host(previous, helper, state, evidence, linux, scratch):
    model = scratch / "host"
    model.mkdir()
    pin(FIXTURE, "1b37cbf993b7a17810bad644263cdb71e5d9b7fd")
    mm = (linux / MM).read_text()
    header = (linux / HEADER).read_text()
    snapshots = re.findall(r"(?ms)^struct swapz_mm_trial_terminal_snapshot \{\n.*?^\};", header)
    require(len(snapshots) == 1, "actual snapshot type")
    (model / "actual-snapshot.h").write_text(snapshots[0] + "\n")
    (model / "actual-scope-control.h").write_text("\n".join(previous.function(mm, name) for name in
        ("swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke")) + "\n")
    source = (linux / TERMINAL).read_text()
    staged = model / "swapz-trial-terminal.inc"
    staged.write_text(source)
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(model), "-I" + str(linux / "include"), str(FIXTURE), "-o", str(binary)]
        helper.step(state, evidence, compiler + "-compile", command, timeout=180)
        result = {"compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                  "modes": {}, "mutants": {}}
        state["host"][compiler] = result
        for mode in MODES:
            label = compiler + "-" + mode
            helper.step(state, evidence, label, [str(binary), mode])
            match = re.fullmatch(r"R105_A11_HOST_ONLY mode=" + re.escape(mode) + r" checks=(\d+) AUTH0\n",
                                 (evidence / (label + ".log")).read_text())
            require(match, "host result " + label)
            result["modes"][mode] = int(match[1])
        for name, before, after, mode in MUTANTS:
            require(source.count(before) == 1, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                staged.write_text(source.replace(before, after))
                helper.step(state, evidence, label + "-compile", command, timeout=180)
                run = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(run.stdout)
                require(run.returncode == 77 and b"R105_A11_FIRST_ERROR" in run.stdout, "surviving mutant " + label)
                result["mutants"][name] = {"exit": run.returncode, "first_error": run.stdout.decode().splitlines()[0]}
            finally:
                staged.write_text(source)
    state["host_status"] = "PASS_HOST_ONLY"


def native(helper, state, evidence, linux, build):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST"
              " -DSWAPZ_ROUND104_INTEGRATION_TEST -I" + str(glue))
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
    data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(data)
    lines = data.decode().splitlines()
    for key in helper.REQUIRED:
        require("CONFIG_" + key + "=y" in lines, "missing " + key)
    require("CONFIG_NR_CPUS=4" in lines and not any("CONFIG_" + key + "=y" in lines
            for key in ("TINY_RCU", "ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON")), "default-off SMP")
    state["config_sha256"] = hashlib.sha256(data).hexdigest()
    objects = ("mm/zswap.o", "mm/swapfile.o")
    state["objects"] = {}
    try:
        helper.step(state, evidence, "changed-native-objects", make + ["-j2", *objects], timeout=1000)
    finally:
        for relative in objects:
            source = build / relative
            if source.is_file():
                dest = evidence / "objects" / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
                state["objects"][relative] = helper.image(source)
    require(set(state["objects"]) == set(objects), "missing native object")
    for relative in objects:
        symbols = subprocess.check_output(["nm", str(build / relative)], text=True)
        (evidence / (Path(relative).name + ".symbols")).write_text(symbols)
        if relative == "mm/zswap.o":
            for name in ("swapz_mm_trial_scope_terminal_snapshot", "swapz_mm_trial_scope_detach_files",
                         "swapz_mm_trial_scope_matches_exact"):
                require(re.search(r"\b" + name + r"\b", symbols), "missing " + name)
        else:
            require(re.search(r"\bU swapz_mm_trial_area_retired\b", symbols), "missing retirement call")
    require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(), "unexpected link")
    state["native"] = "PASS_CHANGED_OBJECTS_ONLY"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 105, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED", "native_link": "NOT_RUN",
             "stage": "NOT_RUN", "native": "NOT_RUN", "host_status": "NOT_RUN",
             "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        require(git(ROOT, "rev-parse", FREEZE + "^{tree}").decode().strip() ==
                "3cc943f1e9dd46d6174f18e5adf7519a7e2f3f7c", "freeze tree")
        require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux pin")
        previous, helper = stage(state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r105-a11-") as temp:
            scratch = Path(temp)
            errors = []
            for action, args in ((host, (previous, helper, state, evidence, linux, scratch)),
                                 (native, (helper, state, evidence, linux, scratch / "build"))):
                try:
                    action(*args)
                except Exception as error:
                    errors.append(str(error))
            require(not errors, "; ".join(errors))
        state["status"] = "PASS_FOCUSED_ONLY"
        return 0
    except Exception as error:
        state["first_error"] = str(error)
        print("R105_A11_FIRST_ERROR", error, file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
