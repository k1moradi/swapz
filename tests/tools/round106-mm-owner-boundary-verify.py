#!/usr/bin/env python3
"""R106 A11: exact source guard/revoke check and changed MM object only, AUTH0."""
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
FREEZE = "8a83828717ea3000d102043ead78fd86ad0391a8"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TOOLS = ROOT / "tests/tools"
PRIOR = TOOLS / "round105-mm-admission-join-verify.py"
PATCH = TOOLS / "round106-original-mm-owner-boundary.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round106-mm-owner-boundary.c"
MM = "mm/zswap.c"
TERMINAL = "mm/swapz-trial-terminal.inc"
PRE = "058389456ee1586f5a26d40f78cd5cde99312060"
POST = "9e1efceae44c384370d0aa3e25748d127a5cd4ad"
MODES = ("denied", "late-fault", "late-debt", "late-carrier", "late-unjoin", "retry", "detached")
PATCH_PIN = "24b9c16de84e8e4795c8c2378220bf2e0dfae25e"
FIXTURE_PIN = "90e53cebafbee7dfaf816d3119590fdfdbb4880a"
PRIOR_PIN = "01ff882ddcdbdd27da6b354a078921169aebce38"


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(path.is_file() and not path.is_symlink() and blob(path.read_bytes()) == expected,
            "blob mismatch " + str(path))


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), "--no-replace-objects", *args])


def function(source, name):
    matches = list(re.finditer(r"(?m)^(?:static )?(?:bool|int|void|u64)\s+" +
                               re.escape(name) + r"\([^;]+?\)\n\{", source))
    require(len(matches) == 1, "function anchor " + name)
    match = matches[0]
    return source[match.start():source.index("\n}", match.end()) + 3]


def frozen_file(path, expected):
    data = git(ROOT, "show", FREEZE + ":" + path)
    require(blob(data) == expected, "frozen source " + path)
    return data.decode()


def audit(linux):
    # Prove only the frozen API/source boundary, not runtime or authorization.
    dm = (linux / "drivers/md/dm.c").read_text()
    pin(linux / "drivers/md/dm.c", "6912eb7ec5a9ef325f7282ef9c9226b39265f01d")
    carrier = (linux / "include/linux/swapz_mm_carrier.h").read_text()
    pin(linux / "include/linux/swapz_mm_carrier.h", "bd88db905e5009e0e6161cad1d09b6d33bde2560")
    target = frozen_file("src/kernel/dm-target.c", "d3cb8525f482321c975cefd91a03aa73fcb7bef2")
    controller = frozen_file("src/kernel/native-observation-controller.c",
                             "06cf0279cc449330e35873829aab1118a2bee151")
    header = frozen_file("src/kernel/native-observation-controller.h",
                         "7189c186874da4fa386fe536280b38bbd1648685")
    lookup = function(target, "swapz_round090_provider_lookup")
    ready = function(target, "swapz_scope_route_ready_locked")
    require("swapz_scope_route_ready_locked(ctx, bdev, sector)" in lookup and
            "scope->identity" in ready and "&ctx->original_scope" in ready,
            "provider cannot bootstrap missing installation")
    route = re.search(r"(?ms)^struct swapz_mm_route \{\n.*?^\};", carrier)
    require(route and "registration_epoch" not in route[0], "route registration identity ABI changed")
    ops = re.search(r"(?ms)^struct swapz_trial_target_ops \{\n.*?^\};", header)
    require(ops and "validate;" in ops[0] and "install;" in ops[0] and
            "(*retire)" in ops[0] and "lookup" not in ops[0], "registry ABI changed")
    begin = function(controller, "swapz_trial_controller_begin")
    require(begin.index("swapz_trial_observation_start(") < begin.index("swapz_mm_trial_scope_publish("),
            "MM rejection is defense in depth, not safe caller preflight")
    deletion = function(dm, "dm_lock_for_deletion")
    destroy = function(dm, "__dm_destroy")
    require(deletion.index("spin_lock(&_minor_lock)") < deletion.index("dm_open_count(md)") <
            deletion.index("DMF_DELETING") < deletion.index("spin_unlock(&_minor_lock)"),
            "native deletion gate order")
    require(destroy.index("dm_table_postsuspend_targets(map)") <
            destroy.index("dm_put_live_table(md, srcu_idx)") <
            destroy.index("atomic_read(&md->holders)") <
            destroy.index("dm_table_destroy(__unbind(md))"), "native final destructor order")
    quiescent = function(target, "swapz_scope_target_quiescent")
    require("ctx->original_target_drained" in quiescent and "!ctx->accepting" in quiescent,
            "final target retirement requires independent drain")
    require("ctx->original_scope_file" in quiescent and
            "fput(mapper);" in function(target, "swapz_scope_finish_retained"),
            "target retains mapper until retirement")
    return {"provider_requires_installed_scope": True, "route_lacks_registration_epoch": True,
            "registry_lacks_preinstall_query": True, "recorder_precedes_mm_publish": True,
            "open_count_precedes_deletion": True, "destructor_after_ref_wait": True,
            "target_requires_independent_drain": True, "target_retains_mapper": True,
            "positive_caller": "BLOCKED_NO_AUTHORITY_OR_FROZEN_ROUTE_ABI",
            "predestruction_caller": "BLOCKED_NO_EXACT_RETAINED_TARGET_KEY_AND_SAFE_LIFETIME_RENDEZVOUS"}


def stage(state, evidence, frozen, baseline, linux):
    pin(PRIOR, PRIOR_PIN)
    pin(PATCH, PATCH_PIN)
    pin(FIXTURE, FIXTURE_PIN)
    spec = importlib.util.spec_from_file_location("r106_r105_corrected", PRIOR)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    historical = evidence / "r105-stage"
    historical.mkdir()
    previous_state = {"completed_steps": []}
    previous, helper = prior.stage(previous_state, historical, frozen, baseline, linux)
    require(previous_state["stage"] == "PASS", "R105 stage only")
    state["r105_stage"] = previous_state
    state["boundary_audit"] = audit(linux)
    pin(linux / MM, PRE)
    pin(linux / TERMINAL, "697f3c9fc51738fedabc58cefc4eee6fddc8358c")
    staged = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    unstaged = set(git(linux, "diff", "--name-only").decode().splitlines())
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, expected in (("check", ["--check"], PRE), ("apply", [], POST),
                                  ("reverse-check", ["--reverse", "--check"], POST),
                                  ("reverse", ["--reverse"], PRE), ("reapply", [], POST)):
        helper.step(state, evidence, "r106-" + label, command + args + [str(PATCH)], linux)
        pin(linux / MM, expected)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            staged | {MM}, "changed source path census")
    require(set(git(linux, "diff", "--name-only").decode().splitlines()) == unstaged,
            "unexpected unstaged changes")
    helper.step(state, evidence, "r106-diff-check", ["git", "diff", "--cached", "--check"], linux)
    # Replace only the deliberately staged historical declaration with the exact
    # R106 frozen declaration. No R106 peer source or implementation is read.
    glue = linux / helper.GLUE_DIR
    for name, sha in (("native-observation-owner.h", "b80d36ff48f775c161c3ed3694f4e94a59f18f96"),
                      ("native-observation-adapter.h", "ffa547fbecad79b3fabf0ded4bb182c201e4a33d"),
                      ("native-observation-integration.h", "e3bca3367459c7f79960105f63e9ddef4e95b4d6")):
        data = frozen_file("src/kernel/" + name, sha).encode()
        (glue / name).write_bytes(data)
        pin(glue / name, sha)
    state["stage"] = "PASS"
    state["postimage"] = POST
    (evidence / "unified-r106.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    return helper


def host(helper, state, evidence, linux, scratch):
    model = scratch / "host"
    model.mkdir()
    mm = (linux / MM).read_text()
    terminal = (linux / TERMINAL).read_text()
    paths = {
        "actual-scope-control.h": "\n".join(function(mm, name) for name in
            ("swapz_mm_scope_valid", "swapz_mm_trial_scope_publish",
             "swapz_mm_trial_scope_stop_capture", "swapz_mm_trial_scope_revoke")) + "\n",
        "actual-terminal-helpers.h": "\n".join(function(terminal, name) for name in
            ("swapz_mm_trial_scope_retained", "swapz_mm_terminal_ready")) + "\n",
    }
    require(blob(paths["actual-scope-control.h"].encode()) == "605d3023ddae7b2e609f6d7ca7c8918dd7788fcf",
            "actual scope control extraction")
    require(blob(paths["actual-terminal-helpers.h"].encode()) == "fbafa9241d63afee4167f039589c42610f38e42c",
            "actual terminal helpers extraction")
    for path, data in paths.items():
        (model / path).write_text(data)
    control = "actual-scope-control.h"
    ready = "actual-terminal-helpers.h"
    code = paths[control]
    start = code.index("\t/* Recheck actual retained debt, never manufacture a zero count. */")
    end = code.index("\terror = swapz_ticket_broker_put(&swapz_mm_scope_cap);", start)
    mutants = (
        ("no-admission-denial", control, "\treturn -EACCES;", "\t/* mutant removes denial */", "denied", 1),
        ("no-post-grace-check", control, code[start:end],
         "\tif (atomic_read_acquire(&swapz_mm_busy))\n\t\tgoto finish;\n", "late-fault", 1),
        ("ignore-debt-count", ready, "!swapz_mm_terminal_debt.fault && !swapz_mm_terminal_debt.count &&",
         "!swapz_mm_terminal_debt.fault &&", "late-debt", 1),
        ("ignore-carrier", ready, "!atomic_read_acquire(&swapz_mm_busy);", "true;", "late-carrier", 1),
        ("ignore-joined", control, "if (!swapz_mm_terminal_joined || !swapz_mm_terminal_ready()) {",
         "if (!swapz_mm_terminal_ready()) {", "late-unjoin", 2),
    )
    state["host"] = {}
    for compiler in ("gcc", "clang"):
        binary = model / compiler
        command = [compiler, "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fno-omit-frame-pointer", "-fno-pie", "-no-pie",
                   "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(model), str(FIXTURE), "-o", str(binary)]
        helper.step(state, evidence, compiler + "-compile", command, timeout=180)
        result = {"version": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                  "modes": {}, "mutants": {}}
        state["host"][compiler] = result
        for mode in MODES:
            label = compiler + "-" + mode
            helper.step(state, evidence, label, [str(binary), mode])
            match = re.fullmatch(r"R106_A11_HOST_ONLY mode=" + re.escape(mode) + r" checks=(\d+) AUTH0\n",
                                 (evidence / (label + ".log")).read_text())
            require(match, "host result " + label)
            result["modes"][mode] = int(match[1])
        for name, path, before, after, mode, count in mutants:
            require(paths[path].count(before) == count, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                (model / path).write_text(paths[path].replace(before, after))
                helper.step(state, evidence, label + "-compile", command, timeout=180)
                run = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(run.stdout)
                require(run.returncode == 77 and b"R106_A11_FIRST_ERROR" in run.stdout,
                        "surviving mutant " + label)
                result["mutants"][name] = {"exit": run.returncode, "first_error": run.stdout.decode().splitlines()[0]}
            finally:
                (model / path).write_text(paths[path])
    state["host_status"] = "PASS_ACTUAL_EXTRACTED_HOST_ONLY"


def native(helper, state, evidence, linux, build):
    helper.prerequisites(state, evidence)
    glue = linux / helper.GLUE_DIR
    guards = (helper.GUARDS + helper.OBSERVATION_GUARDS +
              " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST"
              " -DSWAPZ_ROUND104_INTEGRATION_TEST -DSWAPZ_ROUND106_ADMITTED_OWNER_TEST -I" + str(glue))
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
    data = (build / ".config").read_bytes()
    (evidence / "effective.config").write_bytes(data)
    lines = data.decode().splitlines()
    for key in helper.REQUIRED:
        require("CONFIG_" + key + "=y" in lines, "missing " + key)
    require("CONFIG_NR_CPUS=4" in lines and not any("CONFIG_" + key + "=y" in lines
            for key in ("TINY_RCU", "ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON")), "default-off SMP")
    state["config_sha256"] = hashlib.sha256(data).hexdigest()
    helper.step(state, evidence, "changed-native-object", make + ["-j2", "mm/zswap.o"], timeout=1000)
    source = build / "mm/zswap.o"
    destination = evidence / "objects/mm/zswap.o"
    destination.parent.mkdir(parents=True)
    shutil.copyfile(source, destination)
    state["objects"] = {"mm/zswap.o": helper.image(source)}
    symbols = subprocess.check_output(["nm", str(source)], text=True)
    (evidence / "zswap.o.symbols").write_text(symbols)
    for name in ("swapz_mm_trial_scope_publish", "swapz_mm_trial_scope_revoke"):
        require(re.search(r"\bT " + name + r"\b", symbols), "missing native symbol " + name)
    require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(), "unexpected link")
    pin(linux / MM, POST)
    state["native"] = "PASS_CHANGED_OBJECT_ONLY"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 106, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "linux": LINUX, "AUTH": 0, "phase_a": "BLOCKED",
             "native_link": "NOT_RUN", "stage": "NOT_RUN", "native": "NOT_RUN",
             "host_status": "NOT_RUN", "completed_steps": [], "status": "FAIL", "first_error": None}
    try:
        require(git(ROOT, "rev-parse", FREEZE + "^{tree}").decode().strip() ==
                "1d175df983eb17b8611624ec8b83ea8ddc89b2e8", "freeze tree")
        require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux pin")
        helper = stage(state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r106-a11-") as temp:
            scratch = Path(temp)
            errors = []
            for action, args in ((host, (helper, state, evidence, linux, scratch)),
                                 (native, (helper, state, evidence, linux, scratch / "build"))):
                try:
                    action(*args)
                except Exception as error:
                    errors.append(str(error))
            require(not errors, "; ".join(errors))
        state["status"] = "PASS_NARROW_BOUNDARY_ONLY_ADMISSION_BLOCKED"
        return 0
    except Exception as error:
        state["first_error"] = str(error)
        print("R106_A11_FIRST_ERROR", error, file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
