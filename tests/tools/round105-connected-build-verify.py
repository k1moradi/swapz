#!/usr/bin/env python3
"""One exact R105 frozen native compile/link, never boot or load (AUTH0)."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
FREEZE = "ae7dc02e5db07fc6d133e02ffd558cb68c8e3159"
TREE = "3cc943f1e9dd46d6174f18e5adf7519a7e2f3f7c"
TASK = "5148f7f941fa9144d01c51b047fec16a7b9e557f"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
HISTORICAL = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
BASELINE = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
PRIOR = "tests/tools/round104-mm-core-witness-verify.py"
PRIOR_PIN = "4e7bea38ad8529eb47eaae8718aacd1c5fbf3fde"
PATCH = "tests/tools/round105-original-mm-exact-query-export.patch"
PATCH_PIN = "3048e05e3f594dbaa6a10241fe1fa9c6092fbb54"
TERMINAL = "mm/swapz-trial-terminal.inc"
PRE = "1ecc86d30f20790f1fae7506a3f55d612200831a"
POST = "2bfc139f380461c71da78a8c7f9469d1e7eb0b22"
TARGET = "8a84ac4d395e2f635ae3e4216bade471c03618de"
NATIVE = {
    "native-observation-adapter.c": "00700206f1c6df7e0494cdbfe9da86ec209b5ce3",
    "native-observation-adapter.h": "ffa547fbecad79b3fabf0ded4bb182c201e4a33d",
    "native-observation-owner.c": "50271d7a08763efff55b8767489ea323a3dbf381",
    "native-observation-owner.h": "68750e6b7e78f5bb236c968b3694a429bff6813f",
    "native-observation-byte-collector.c": "d363f40f537722783777956f8920415b97639b93",
    "native-observation-byte-collector.h": "75a07d2913f8d7dd8071234c98463d444f98d9bd",
    "native-observation-byte-bridge.c": "6b3446f6b90257e704052dbf5a73979c64b6399f",
    "native-observation-byte-bridge.h": "8105f87229b3aac1d0d3f9798a59915af0232526",
    "native-observation-controller.c": "46ab3317c8160bfd8716360d281a7f46609fb6a3",
    "native-observation-controller.h": "3e917194fda1b1163ed047656a814350448b2523",
    "native-observation-integration.h": "e3bca3367459c7f79960105f63e9ddef4e95b4d6",
}
OFF = ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
       "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU")
QUERY = "swapz_mm_trial_scope_matches_exact"
REQUIRED_IMPORTS = {QUERY, "swapz_trial_observation_append_sequence",
                    "swapz_trial_byte_event", "swapz_trial_controller_revoke_joined",
                    "swapz_trial_controller_finish"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), "--no-replace-objects", *args])


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(path.is_file() and not path.is_symlink(), "missing exact input " + path.name)
    require(blob(path.read_bytes()) == expected, "blob mismatch " + path.name)


def load(path, expected):
    pin(path, expected)
    spec = importlib.util.spec_from_file_location("r105_frozen_r104", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def text_command(evidence, label, command):
    output = subprocess.check_output(command, text=True)
    (evidence / (label + ".txt")).write_text(output)
    return output


def undefined(output):
    return {fields[1] for line in output.splitlines() if len(fields := line.split()) == 2
            and fields[0] == "U"}


def stage(state, evidence, frozen, historical, baseline, linux, module):
    for directory, expected in ((frozen, FREEZE), (historical, HISTORICAL),
                                (baseline, BASELINE), (linux, LINUX)):
        require(git(directory, "rev-parse", "HEAD").decode().strip() == expected,
                "checkout identity " + directory.name)
        require(not git(directory, "status", "--porcelain", "--untracked-files=all"),
                "dirty checkout " + directory.name)
    require(git(frozen, "rev-parse", "HEAD^{tree}").decode().strip() == TREE, "frozen tree")
    require(git(ROOT, "show", TASK + ":src/kernel/native-observation-integration.h") ==
            (frozen / "src/kernel/native-observation-integration.h").read_bytes(),
            "immutable task header")
    require(all((linux / name).is_file() for name in
                ("Makefile", "init/main.c", "kernel/rcu/tree.c", "arch/x86/Kconfig")),
            "full pinned Linux checkout")
    prior = load(frozen / PRIOR, PRIOR_PIN)
    previous = prior.load_prior()
    helper = previous.load_helper()
    # Preserve all historical helper pins and source checks verbatim.
    prior.stage_source(previous, helper, state, evidence, historical, baseline, linux)
    require(state["stage"] == "PASS", "R104 exact historical stage")
    state["stage"] = "PASS_HISTORICAL_ONLY"
    patch = frozen / PATCH
    pin(patch, PATCH_PIN)
    pin(linux / TERMINAL, PRE)
    apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, options, expected in (
            ("check", ["--check"], PRE), ("apply", [], POST),
            ("reverse-check", ["--reverse", "--check"], POST),
            ("reverse", ["--reverse"], PRE), ("reapply", [], POST)):
        helper.step(state, evidence, "a1-export-" + label, apply + options + [str(patch)], linux)
        pin(linux / TERMINAL, expected)
    require((linux / TERMINAL).read_text().count("EXPORT_SYMBOL_GPL(" + QUERY + ");") == 1,
            "exact query GPL export census")
    state["a1_export"] = {"patch_blob": PATCH_PIN, "preimage": PRE, "postimage": POST,
                          "apply_reverse_reapply": "PASS"}
    manifest = json.loads((evidence / "r103-stage/unified-base-manifest.json").read_text())[
        "authoritative_manifest"]
    product = frozen / "src/kernel"
    overrides = dict(NATIVE, **{"dm-target.c": TARGET})
    expected_names = set(helper.PRODUCT) | set(NATIVE)
    require({item.name for item in product.iterdir()} == expected_names, "frozen inventory")
    for name in sorted(expected_names):
        pin(product / name, overrides.get(name, helper.PRODUCT.get(name)))
    state["frozen_product"] = {name: helper.image(product / name) for name in sorted(expected_names)}
    glue = linux / helper.GLUE_DIR
    module.mkdir()
    for name, metadata in manifest["module_final"].items():
        destination = module / name
        if name == "Makefile":
            original = (baseline / "src/kernel" / name).read_text()
            anchor = "dm-swapz-y := dm-target.o codec.o authority.o engine.o predictor.o\n"
            require(original.count(anchor) == 1, "historical module Kbuild anchor")
            destination.write_text(original.replace(anchor, anchor + "dm-swapz-y += " +
                " ".join(helper.EXTRA_MODULE) + "\nccflags-y += -I$(src)\n", 1))
        elif name == "swapz-version.h":
            version = (baseline / "src/kernel/VERSION").read_text().strip()
            destination.write_text(f'#define SWAPZ_ALPHA_VERSION "{version}"\n')
        elif name == "dm-target.c":
            shutil.copyfile(historical / "src/kernel" / name, destination)
        elif name in (*helper.BROKER_INPUTS, helper.OWNER_INC):
            shutil.copyfile(linux / "src/kernel" / name, destination)
        else:
            shutil.copyfile(baseline / "src/kernel" / name, destination)
        pin(destination, metadata["blob"])
    shutil.copyfile(product / "dm-target.c", module / "dm-target.c")
    pin(module / "dm-target.c", TARGET)
    for name, expected in NATIVE.items():
        shutil.copyfile(product / name, glue / name)
        pin(glue / name, expected)
        if name.endswith(".h"):
            shutil.copyfile(product / name, module / name)
            pin(module / name, expected)
    for name in helper.UNSELECTED:
        require(not (glue / name).exists() and not (module / name).exists(), "unselected recorder")
    makefile = glue / "Makefile"
    original = makefile.read_text()
    require(original.count(HISTORICAL) == 1, "recorder source anchor")
    makefile.write_text(original.replace(HISTORICAL, FREEZE, 1) +
        "obj-y += native-observation-controller.o native-observation-byte-collector.o "
        "native-observation-byte-bridge.o\n")
    # Build-info values derive from the verified frozen checkout, not moving main.
    # Keep definitions in the compiler command, not a modified product header.
    git(linux, "add", "--", helper.GLUE_DIR)
    require(not git(linux, "diff", "--name-only"), "unstaged source")
    helper.step(state, evidence, "connected-stage-diff-check", ["git", "diff", "--cached", "--check"], linux)
    staged_paths = git(linux, "diff", "--cached", "--name-only").decode().splitlines()
    state["linux_stage"] = {name: helper.image(linux / name) for name in staged_paths}
    state["module_stage"] = {item.name: helper.image(item) for item in sorted(module.iterdir())}
    (evidence / "connected-source.diff").write_bytes(git(linux, "diff", "--cached", "--binary"))
    state["stage"] = "PASS_CONNECTED_SOURCE"
    return helper


def build(helper, state, evidence, linux, output, module):
    helper.prerequisites(state, evidence)
    require(shutil.which("modinfo"), "missing-build-tool:modinfo")
    # One guard set for all built-in and module TUs; only Kbuild's MODULE
    # distinction differs. No runtime control is invoked.
    flags = (helper.MODULE_GUARDS + helper.OBSERVATION_GUARDS +
             " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND098_SCOPED_TARGET_TEST"
             " -DSWAPZ_ROUND102_CONTROLLER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST"
             " -DSWAPZ_ROUND104_INTEGRATION_TEST -I" + str(linux / helper.GLUE_DIR) +
             ' -DSWAPZ_BUILD_SOURCE_SHA=\\"' + FREEZE + '\\" -DSWAPZ_BUILD_SOURCE_CLEAN=1')
    state["guards"] = flags
    output.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(output), "ARCH=x86_64", "CC=gcc", "KCFLAGS=" + flags]
    external = make + ["M=" + str(module)]
    state["commands"] = {"kernel": make + ["-j2", "vmlinux", "modules"],
                         "module": external + ["-j2", "modules"]}
    helper.step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    configure = ["bash", str(linux / "scripts/config"), "--file", str(output / ".config")]
    for key in helper.REQUIRED:
        configure += ["--enable", key]
    for key in OFF:
        configure += ["--disable", key]
    configure += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "configure", configure)
    helper.step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    effective = (output / ".config").read_text().splitlines()
    require(all("CONFIG_" + key + "=y" in effective for key in helper.REQUIRED) and
            all("CONFIG_" + key + "=y" not in effective for key in OFF) and
            "CONFIG_NR_CPUS=4" in effective, "SMP TREE_RCU default-off config")
    shutil.copyfile(output / ".config", evidence / "effective.config")
    state["config"] = helper.image(output / ".config")
    helper.step(state, evidence, "modules-prepare", make + ["modules_prepare"], timeout=900)
    # Preflight the actual external composite, not a stub. Full kernel and
    # module modpost follow only if the real imported private ABI is exported.
    helper.step(state, evidence, "module-import-preflight", external + ["-j2", "dm-swapz.o"], timeout=1200)
    composite = module / "dm-swapz.o"
    imports = undefined(text_command(evidence, "preflight-imports", ["nm", "-u", str(composite)]))
    metadata = text_command(evidence, "preflight-modinfo-section",
                            ["readelf", "-p", ".modinfo", str(composite)])
    require(re.search(r"license=GPL(?:\s|$)", metadata), "actual GPL module license")
    require(REQUIRED_IMPORTS <= imports, "missing actual integrated module imports")
    private = {name for name in imports if name.startswith(("swapz_", "dm_swapz_"))}
    exports = {}
    for name in state["linux_stage"]:
        if name.startswith("src/kernel/") or not name.endswith((".c", ".h", ".inc")):
            continue
        for symbol in re.findall(r"EXPORT_SYMBOL_GPL\(\s*(\w+)\s*\)", (linux / name).read_text()):
            exports.setdefault(symbol, []).append(name)
    require(all(len(exports.get(name, [])) == 1 for name in private),
            "private missing/duplicate source GPL exports: " +
            ",".join(sorted(name for name in private if len(exports.get(name, [])) != 1)))
    state["preflight"] = {"all_strong_imports": sorted(imports),
                          "private_gpl_sources": {name: exports[name] for name in sorted(private)},
                          "license": "GPL"}
    require(not (output / "vmlinux").exists() and not (output / "Module.symvers").exists() and
            not (module / "dm-swapz.ko").exists(), "stale full-link artifact")
    state["full_build_attempts"] = 1
    helper.step(state, evidence, "full-kernel-link", state["commands"]["kernel"], timeout=4800)
    kernel, symvers = output / "vmlinux", output / "Module.symvers"
    require(kernel.is_file() and symvers.is_file(), "missing full kernel or symvers")
    state["artifacts"]["vmlinux"] = helper.image(kernel)
    state["artifacts"]["kernel-Module.symvers"] = helper.image(symvers)
    shutil.copyfile(symvers, evidence / "kernel-Module.symvers")
    if kernel.stat().st_size <= 64 * 1024 * 1024:
        shutil.copyfile(kernel, evidence / "vmlinux")
    kernel_symbols = text_command(evidence, "kernel-symbols", ["nm", "-g", "--defined-only", str(kernel)])
    require(not undefined(text_command(evidence, "kernel-imports", ["nm", "-u", str(kernel)])),
            "unresolved strong vmlinux symbol")
    require(all(sum(line.split()[-1] == name for line in kernel_symbols.splitlines() if line.split()) == 1
                for name in REQUIRED_IMPORTS), "connected built-in definition census")
    rows = {fields[1]: fields for line in symvers.read_text().splitlines()
            if len(fields := line.split()) >= 4}
    state["full_kernel_link"] = "PASS"
    state["private_export_rows"] = {name: rows.get(name) for name in sorted(private)}
    # Actual MODPOST resolves against the same full kernel's Module.symvers.
    # Do not use KBUILD_MODPOST_WARN or hand-written symbol files.
    helper.step(state, evidence, "external-module-modpost-link", state["commands"]["module"], timeout=1200)
    ko = module / "dm-swapz.ko"
    require(ko.is_file(), "missing actual dm-swapz.ko")
    state["modpost"] = "PASS_GENUINE"
    state["module_link"] = "PASS"
    require(private <= rows.keys() and all(rows[name][2:4] == ["vmlinux", "EXPORT_SYMBOL_GPL"]
                                           for name in private), "private built-in GPL export census")
    module_symbols = text_command(evidence, "module-symbols", ["nm", "-g", "--defined-only", str(ko)])
    final_imports = undefined(text_command(evidence, "module-imports", ["nm", "-u", str(ko)]))
    require(final_imports <= rows.keys(), "unresolved final module imports: " +
            ",".join(sorted(final_imports - rows.keys())))
    require(REQUIRED_IMPORTS <= final_imports, "missing connected final module imports")
    require(not any(line.split()[-1] in REQUIRED_IMPORTS for line in module_symbols.splitlines()
                    if line.split()), "duplicate built-in module implementation")
    relocations = text_command(evidence, "module-relocations", ["readelf", "-Wr", str(ko)])
    require(all(re.search(r"\b" + name + r"\b", relocations) for name in REQUIRED_IMPORTS),
            "missing real module relocations")
    header = text_command(evidence, "module-elf", ["readelf", "-h", str(ko)])
    require("REL (Relocatable file)" in header and "Advanced Micro Devices X86-64" in header,
            "module ELF architecture")
    kernel_header = text_command(evidence, "kernel-elf", ["readelf", "-h", str(kernel)])
    require("Advanced Micro Devices X86-64" in kernel_header, "kernel ELF architecture")
    info = {field: text_command(evidence, "module-" + field, ["modinfo", "-F", field, str(ko)]).strip()
            for field in ("license", "vermagic", "depends", "swapz_build_source_sha", "swapz_build_source_clean")}
    release = (output / "include/config/kernel.release").read_text().strip()
    require(info["license"] == "GPL" and info["vermagic"].startswith(release + " ") and
            "SMP" in info["vermagic"].split(), "module GPL/vermagic")
    require(info["swapz_build_source_sha"] == FREEZE and info["swapz_build_source_clean"] == "1",
            "module build-source metadata")
    state["module_info"] = info
    state["module_imports"] = sorted(final_imports)
    state["private_export_rows"] = {name: rows[name] for name in sorted(private)}
    state["artifacts"]["dm-swapz.ko"] = helper.image(ko)
    require(ko.stat().st_size <= 16 * 1024 * 1024, "module evidence size bound")
    shutil.copyfile(ko, evidence / "dm-swapz.ko")
    for name, metadata in state["linux_stage"].items():
        pin(linux / name, metadata["blob"])
    for name, metadata in state["module_stage"].items():
        pin(module / name, metadata["blob"])
    require(helper.image(output / ".config") == state["config"], "config drift")
    require(helper.image(symvers) == state["artifacts"]["kernel-Module.symvers"], "symvers drift")


def main():
    os.umask(0o077)
    frozen, historical, baseline, linux, scratch, evidence = map(lambda value: Path(value).resolve(), sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    scratch.mkdir(mode=0o700, parents=True, exist_ok=False)
    start = time.monotonic()
    state = {"round": 105, "agent": 10, "source_freeze": FREEZE, "source_tree": TREE,
             "linux": LINUX, "tested_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "parent": git(ROOT, "rev-parse", "HEAD^").decode().strip(),
             "AUTH": 0, "phase_a": "BLOCKED", "actual_physical_io": False, "runtime": "NOT_RUN",
             "handoff": "OFF", "forced_raw": "OFF", "import": "OFF",
             "stage": "NOT_RUN", "status": "FAIL", "full_build_attempts": 0,
             "full_kernel_link": "NOT_RUN", "module_link": "NOT_RUN", "modpost": "NOT_RUN",
             "completed_steps": [], "artifacts": {}, "first_error": None}
    try:
        for key in ("KBUILD_MODPOST_WARN", "KBUILD_EXTRA_SYMBOLS"):
            require(not os.environ.get(key), "forbidden build environment " + key)
        helper = stage(state, evidence, frozen, historical, baseline, linux, scratch / "module")
        build(helper, state, evidence, linux, scratch / "output", scratch / "module")
        state["status"] = "PASS_CONNECTED_COMPILE_LINK_ONLY"
        print("R105_A10_CONNECTED_COMPILE_LINK_PASS AUTH0 NO_RUNTIME", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error).split("\n", 1)[0][:500]
        print("R105_A10_FIRST_ERROR " + state["first_error"], file=sys.stderr, flush=True)
        return 1
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        state["resources"] = {"elapsed_seconds": round(time.monotonic() - start, 3),
                              "child_user_seconds": usage.ru_utime, "child_system_seconds": usage.ru_stime,
                              "child_max_rss_kib": usage.ru_maxrss}
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
