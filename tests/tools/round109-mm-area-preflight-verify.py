#!/usr/bin/env python3
"""R109 A11: exact original MM scalar swap-area preflight; directed swapfile.o only."""
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
FREEZE = "6394bf9aec7709744caf294f8bd7e935ca481dcd"
TREE = "780198718469ec268f9b588ad5b36c63bc1b1806"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TOOLS = ROOT / "tests/tools"
PRIOR = TOOLS / "round107-dm-final-removal-verify.py"
PATCH = TOOLS / "round109-original-mm-area-preflight.patch"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round109-mm-area-preflight.c"
SWAPFILE = "mm/swapfile.c"
HEADER = "include/linux/swapz_mm_carrier.h"
IMAGES = {
    SWAPFILE: ("d20a7f0003405bd1450cc52af63a773c91ee86b6", "8b9826f09f7b3127d4cb739a072102763d8e1ecd"),
    HEADER: ("bd88db905e5009e0e6161cad1d09b6d33bde2560", "8d369c402780e06ffd317919acdd6bbd4802646e"),
}
PATCH_PIN = "3c38d165804cb62c7f0d99e27e1ed303987ec90e"
FIXTURE_PIN = "af24dc4430f157f8ca23707354ad948d365f1ef0"
PRIOR_PIN = "b6139ba044ce06c71e732187905dab8572415e90"
GUARD = "SWAPZ_ROUND109_AREA_PREFLIGHT_TEST"
MODES = ("historical", "invalid", "range", "mismatch", "races")

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


def guarded(source):
    anchor = "#ifdef " + GUARD + "\n"
    require(source.count(anchor) == 1, "guard anchor")
    start = source.index(anchor)
    end = source.index("\n#endif\n", start) + len("\n#endif\n")
    return source[start:end]


def extract(linux):
    sf = (linux / SWAPFILE).read_text()
    header = (linux / HEADER).read_text()
    anchor = "int swapz_mm_trial_area_get("
    require(sf.count(anchor) == 1, "historical function anchor")
    start = sf.index(anchor)
    end = sf.index("\n}", start) + 3
    return guarded(header) + "\n" + guarded(sf) + "\n" + sf[start:end] + "\n"


def stage(state, evidence, frozen, baseline, linux):
    pin(PRIOR, PRIOR_PIN)
    pin(PATCH, PATCH_PIN)
    pin(FIXTURE, FIXTURE_PIN)
    spec = importlib.util.spec_from_file_location("r109_r107_frozen", PRIOR)
    prior = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prior)
    historical = evidence / "r107-stage"
    historical.mkdir()
    previous = {"completed_steps": []}
    helper = prior.stage(previous, historical, frozen, baseline, linux)
    require(previous["stage"] == "PASS_EXACT_APPLY_REVERSE_REAPPLY", "R107 historical stage only")
    state["historical_stage"] = previous
    pin(linux / "mm/zswap.c", "9e1efceae44c384370d0aa3e25748d127a5cd4ad")
    pin(linux / "drivers/md/dm.c", "332fc3faf1ad05f3756bf7d90b476f28bd50a012")
    before = {}
    for path, pair in IMAGES.items():
        pin(linux / path, pair[0])
        before[path] = (linux / path).read_text()
    staged = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    unstaged = set(git(linux, "diff", "--name-only").decode().splitlines())
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, side in (("check", ["--check"], 0), ("apply", [], 1),
                              ("reverse-check", ["--reverse", "--check"], 1),
                              ("reverse", ["--reverse"], 0), ("reapply", [], 1)):
        helper.step(state, evidence, "r109-" + label, command + args + [str(PATCH)], linux)
        for path, pair in IMAGES.items():
            pin(linux / path, pair[side])
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines()) ==
            staged | IMAGES.keys(), "staged path census")
    require(set(git(linux, "diff", "--name-only").decode().splitlines()) == unstaged,
            "unstaged path census")
    helper.step(state, evidence, "r109-staged-diff-check", ["git", "diff", "--cached", "--check"], linux)
    for path in IMAGES:
        source = (linux / path).read_text()
        require(source.replace(guarded(source) + "\n", "", 1) == before[path],
                "guard-off source differs: " + path)
    source = guarded((linux / SWAPFILE).read_text())
    require(not any(word in source for word in ("get_file(", "fput(", "EXPORT_SYMBOL", "broker_",
                                                  "scope_publish(", "submit_bio(")),
            "unexpected reference transfer or publication")
    require(source.index("spin_lock(&swap_lock)") < source.index("plist_for_each_entry(") <
            source.index("swapz_mm_trial_area_epoch(") < source.index("spin_unlock(&swap_lock)"),
            "actual lock/epoch ordering")
    state["audit"] = {"guard_off": "BYTE_EXACT", "historical_area_get": "UNCHANGED",
                      "retained_references": "NONE_IN_SOURCE", "caller": "ABSENT",
                      "authorization": "NONE", "native_runtime": "NOT_RUN"}
    state["stage"] = "PASS_EXACT_APPLY_REVERSE_REAPPLY"
    state["postimages"] = {path: pair[1] for path, pair in IMAGES.items()}
    (evidence / "unified-r109.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    print("R109_A11_STAGE_PASS", state["postimages"], flush=True)
    return helper


MUTANTS = (
    ("missing-epoch", "if (!current_epoch)\n\t\t\tbreak;\n\t\tidentity->swap_type",
     "if (!current_epoch && false)\n\t\t\tbreak;\n\t\tidentity->swap_type", "mismatch"),
    ("retained-reference", "\t\tidentity->swap_type = si->type;",
     "\t\tget_file(si->swap_file);\n\t\tidentity->swap_type = si->type;", "range"),
    ("no-output-clear", "\t*identity = (struct swapz_mm_trial_area_identity){};",
     "\t/* mutant leaves previous output */", "invalid"),
    ("page-zero", "\t    !first || (first & 7) || !count || (count & 7) ||",
     "\t    (first & 7) || !count || (count & 7) ||", "invalid"),
    ("range-bound", "\t    count > 16 * 8 || count > (sector_t)-1 - first)",
     "\t    count > (sector_t)-1 - first)", "invalid"),
    ("overflow", "\t    count > 16 * 8 || count > (sector_t)-1 - first)",
     "\t    count > 16 * 8)", "invalid"),
    ("capacity", "\tif (bdev_read_only(bdev) || first >= capacity ||\n\t    count > capacity - first)",
     "\tif (bdev_read_only(bdev) || (capacity && false))", "range"),
    ("area-max", "\t\t    first / 8 >= si->max || count / 8 > si->max - first / 8)\n\t\t\tcontinue;\n\t\tcurrent_epoch = swapz_mm_trial_area_epoch(si->type);\n\t\tif (!current_epoch)\n\t\t\tbreak;\n\t\tidentity->swap_type",
     "\t\t    false)\n\t\t\tcontinue;\n\t\tcurrent_epoch = swapz_mm_trial_area_epoch(si->type);\n\t\tif (!current_epoch)\n\t\t\tbreak;\n\t\tidentity->swap_type", "range"),
    ("mapping", "\t\t    si->swap_file->f_mapping != mapper_file->f_mapping ||\n\t\t    first / 8 >= si->max || count / 8 > si->max - first / 8)\n\t\t\tcontinue;\n\t\tcurrent_epoch = swapz_mm_trial_area_epoch(si->type);\n\t\tif (!current_epoch)\n\t\t\tbreak;\n\t\tidentity->swap_type",
     "\t\t    first / 8 >= si->max || count / 8 > si->max - first / 8)\n\t\t\tcontinue;\n\t\tcurrent_epoch = swapz_mm_trial_area_epoch(si->type);\n\t\tif (!current_epoch)\n\t\t\tbreak;\n\t\tidentity->swap_type", "mismatch"),
    ("offline", "\t\tif (!(si->flags & SWP_WRITEOK) || si->ops != &swap_bdev_ops ||\n\t\t    si->bdev != bdev || !si->swap_file ||\n\t\t    !S_ISBLK(file_inode(si->swap_file)->i_mode) ||\n\t\t    si->swap_file->f_op != &def_blk_fops ||",
     "\t\tif (si->ops != &swap_bdev_ops ||\n\t\t    si->bdev != bdev || !si->swap_file ||\n\t\t    !S_ISBLK(file_inode(si->swap_file)->i_mode) ||\n\t\t    si->swap_file->f_op != &def_blk_fops ||", "mismatch"),
    ("partition", "\tif (!bdev || bdev_is_partition(bdev))\n\t\treturn -EINVAL;\n\n\tspin_lock(&swap_lock);",
     "\tif (!bdev)\n\t\treturn -EINVAL;\n\n\tspin_lock(&swap_lock);", "invalid"),
    ("read-only", "\tif (bdev_read_only(bdev) || first >= capacity ||",
     "\tif (first >= capacity ||", "mismatch"),
    ("path-file", "\t    (mapper_file->f_mode & FMODE_PATH) ||",
     "\t    false ||", "invalid"),
)


def host(helper, state, evidence, linux, scratch):
    model = scratch / "host"
    model.mkdir()
    source = extract(linux)
    require(blob(source.encode()) == "c439ff707fd4b1e7bb1fa2934ed56c89b77d6b6d",
            "actual extracted source hash")
    header = model / "actual-area.h"
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
        for enabled in (False, True):
            selected = command + (["-D" + GUARD] if enabled else [])
            label = compiler + ("-guard-on" if enabled else "-guard-off")
            helper.step(state, evidence, label + "-compile", selected, timeout=180)
            for mode in (MODES if enabled else ("historical",)):
                case = label + "-" + mode
                helper.step(state, evidence, case, [str(binary), mode])
                match = re.fullmatch(r"R109_A11_HOST_ONLY mode=" + re.escape(mode) + r" checks=(\d+) AUTH0\n",
                                     (evidence / (case + ".log")).read_text())
                require(match, "host output " + case)
                result["modes"][case] = int(match[1])
                print("R109_A11_HOST_PASS", case, match[1], flush=True)
        for name, before, after, mode in MUTANTS:
            require(source.count(before) == 1, "mutant anchor " + name)
            label = compiler + "-mutant-" + name
            try:
                header.write_text(source.replace(before, after))
                helper.step(state, evidence, label + "-compile", command + ["-D" + GUARD], timeout=180)
                run = subprocess.run([str(binary), mode], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     timeout=30, check=False)
                (evidence / (label + ".log")).write_bytes(run.stdout)
                require(run.returncode == 77 and b"R109_A11_FIRST_ERROR" in run.stdout,
                        "surviving mutant " + label)
                result["mutants"][name] = {"exit": run.returncode,
                    "first_error": run.stdout.decode().splitlines()[0]}
                print("R109_A11_MUTANT_REJECTED", label, flush=True)
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
    print("R109_A11_CONFIG_SHA256", state["config_sha256"], state["compiler"], flush=True)
    for enabled in (False, True):
        label = "guard-on" if enabled else "guard-off"
        flags = guards + (" -D" + GUARD if enabled else "")
        helper.step(state, evidence, label + "-changed-swapfile-object",
                    make + ["KCFLAGS=" + flags, "-j2", "mm/swapfile.o"], timeout=1000)
        source = build / "mm/swapfile.o"
        destination = evidence / "objects" / label / "swapfile.o"
        destination.parent.mkdir(parents=True)
        shutil.copyfile(source, destination)
        symbols = subprocess.check_output(["nm", str(source)], text=True)
        (evidence / (label + "-swapfile.o.symbols")).write_text(symbols)
        definitions = {line.split()[-1] for line in symbols.splitlines()
                       if len(line.split()) == 3 and line.split()[1] == "T"}
        require(("swapz_mm_trial_area_preflight" in definitions) == enabled and
                "swapz_mm_trial_area_get" in definitions and
                "__ksymtab_swapz_mm_trial_area_preflight" not in symbols,
                "private guarded native symbol census " + label)
        require(not (build / "vmlinux").exists() and not (build / "Module.symvers").exists(),
                "unexpected link")
        state["objects"][label] = helper.image(source)
        print("R109_A11_NATIVE_OBJECT", label, json.dumps(state["objects"][label]), flush=True)
    for path, pair in IMAGES.items():
        pin(linux / path, pair[1])
    state["native"] = "PASS_CHANGED_SWAPFILE_OBJECT_GUARD_ON_AND_OFF"


def main():
    os.umask(0o077)
    frozen, baseline, linux, evidence = (Path(arg).resolve() for arg in sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = {"round": 109, "agent": 11, "source": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "freeze": FREEZE, "freeze_tree": TREE, "linux": LINUX, "AUTH": 0,
             "phase_a": "BLOCKED", "native_link": "NOT_RUN", "stage": "NOT_RUN",
             "native": "NOT_RUN", "host_status": "NOT_RUN", "completed_steps": [],
             "status": "FAIL", "first_error": None}
    try:
        require(git(ROOT, "rev-parse", FREEZE + "^{tree}").decode().strip() == TREE, "freeze tree")
        require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX, "Linux pin")
        helper = stage(state, evidence, frozen, baseline, linux)
        with tempfile.TemporaryDirectory(prefix="r109-a11-") as temp:
            scratch = Path(temp)
            errors = []
            for action, args in ((host, (helper, state, evidence, linux, scratch)),
                                 (native, (helper, state, evidence, linux, scratch / "build"))):
                try:
                    action(*args)
                except Exception as error:
                    errors.append(str(error))
            require(not errors, "; ".join(errors))
        state["status"] = "PASS_SCALAR_PREFLIGHT_ONLY_ADMISSION_BLOCKED"
        print("R109_A11_PASS AUTH0 HOST_AND_DIRECTED_ONLY", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error)
        print("R109_A11_FIRST_ERROR", error, file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
