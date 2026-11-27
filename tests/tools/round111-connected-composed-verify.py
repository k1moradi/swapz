#!/usr/bin/env python3
"""One exact R111 composed AUTH0 kernel/module link; never boot or load."""
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
FREEZE = "4345f21b1da720e6c8d685c7b232bfcebe635d50"
TREE = "98cb27a3f57d6482d859a260526edb5614ec7994"
# Prior immutable declaration contract, not the self-referential R109 task commit.
COMPOSITION_FREEZE = "1ede7cfc7be8e870cadf34afec7a655d4630750e"
CONNECTED_FREEZE = "6394bf9aec7709744caf294f8bd7e935ca481dcd"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
HISTORICAL = "d2baba1bda02b78eb7df265d22c5e9dbee09e2b1"
BASELINE = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
COMPOSITION = "tests/tools/round110-connected-preflight-stage.py"
COMPOSITION_PIN = "b2ab565043799e96adc374aeb4cdaacbce45c1df"
DM_PATCH = "tests/tools/round110-original-dm-composed-preflight.patch"
DM_PATCH_PIN = "61a83b92c43be93d0a3ebffe614de4bc8ebe8660"
DM_PRE = "332fc3faf1ad05f3756bf7d90b476f28bd50a012"
DM_POST = "5e446e6b80f5744e082ed13a506506499ecb854f"
AREA_QUERY = "swapz_mm_trial_area_preflight"
TARGET_QUERY = "swapz_trial_controller_query_registered"
COMBINED_QUERY = "dm_swapz_combined_preflight"
OFF = ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT", "MODULE_SIG",
       "DEBUG_INFO", "DEBUG_INFO_BTF", "TINY_RCU", "MODULE_FORCE_UNLOAD")
PRIVATE_ONLY = {"swapz_trial_controller_begin_registered", "swapz_trial_controller_query_registered",
                "swapz_trial_controller_retire_registered", "dm_swapz_retire_final_table",
                "swapz_mm_trial_scope_publish", AREA_QUERY, COMBINED_QUERY}
CONTROLLER_DEFINITIONS = {"swapz_trial_controller_begin_registered",
    "swapz_trial_controller_query_registered", "swapz_trial_controller_retire_registered",
    "swapz_trial_target_register", "swapz_trial_target_unregister"}
STARTUP_IMPORTS = {"swapz_mm_trial_area_get", "swapz_mm_trial_scope_publish",
                   "swapz_trial_observation_start", "swapz_trial_byte_bind_scope"}
TERMINAL_IMPORTS = {"swapz_mm_trial_scope_join_external", "swapz_mm_trial_scope_terminal_snapshot",
                    "swapz_mm_trial_scope_detach_files", "swapz_mm_trial_scope_revoke",
                    "swapz_mm_broker_owner_retired", "swapz_trial_observation_append_sequence",
                    "swapz_trial_byte_event", "swapz_trial_observation_stop"}
QUERY = "swapz_mm_trial_scope_matches_exact"
REQUIRED_IMPORTS = {QUERY, "swapz_trial_observation_append_sequence",
                    "swapz_trial_byte_event", "swapz_trial_controller_revoke_joined",
                    "swapz_trial_controller_finish", "swapz_trial_target_register",
                    "swapz_trial_target_unregister"}


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
    spec = importlib.util.spec_from_file_location("r109_frozen_r107", path)
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


def definition_present(symbols, name, kind, allow_clone=False):
    """Match actual nm definition fields, never a prefix or undefined symbol."""
    return any(len(fields) == 3 and fields[1] == kind and
               (fields[2] == name or (allow_clone and fields[2].startswith(name + ".") and
                                      len(fields[2]) > len(name) + 1))
               for line in symbols.splitlines() if (fields := line.split()))


def relocation_present(relocations, name):
    return re.search(r"(?<![\w.])" + re.escape(name) + r"(?![\w.])", relocations) is not None


def symbol_census_selftest():
    # Actual R108 symbol row shapes; no build credit from this parser test.
    rows = ("0000000000000760 T swapz_trial_controller_begin_registered\n"
            "ffffffff8129a980 t dm_swapz_retire_final_table\n"
            "0000000000000020 t dm_swapz_retire_final_table.isra.0\n"
            "                 U swapz_trial_controller_retire_registered\n"
            "0000000000000000 T swapz_mm_trial_scope_publish_extra\n")
    require(definition_present(rows, "swapz_trial_controller_begin_registered", "T"),
            "symbol selftest actual global")
    require(definition_present(rows, "dm_swapz_retire_final_table", "t", True) and
            definition_present("0000000000000020 t dm_swapz_retire_final_table.isra.0",
                               "dm_swapz_retire_final_table", "t", True),
            "symbol selftest actual local and compiler clone")
    require(not definition_present(rows, "swapz_trial_controller_retire_registered", "T") and
            not definition_present(rows, "swapz_mm_trial_scope_publish", "T") and
            not definition_present(rows, "dm_swapz_retire_final_table", "T") and
            not definition_present("0000000000000020 t dm_swapz_retire_final_table.",
                                   "dm_swapz_retire_final_table", "t", True),
            "symbol selftest undefined, prefix, wrong type and malformed clone")
    name = "swapz_trial_controller_retire_registered"
    require(relocation_present("0000000 R_X86_64_PLT32 " + name + " - 4", name) and
            not relocation_present(name + "_extra", name) and
            not relocation_present(name + ".isra.0", name),
            "relocation selftest exact symbol")
    print("R111_SYMBOL_CENSUS_SELFTEST_PASS", flush=True)


def stage(state, evidence, frozen, composition_inputs, connected_frozen,
          historical, baseline, linux, module):
    for checkout, expected in (
        (frozen, FREEZE), (composition_inputs, COMPOSITION_FREEZE),
        (connected_frozen, CONNECTED_FREEZE), (historical, HISTORICAL),
        (baseline, BASELINE), (linux, LINUX),
    ):
        require(git(checkout, "rev-parse", "HEAD").decode().strip() == expected,
                "checkout identity " + checkout.name)
        require(not git(checkout, "status", "--porcelain", "--untracked-files=all"),
                "dirty checkout " + checkout.name)
    require(git(frozen, "rev-parse", "HEAD^{tree}").decode().strip() == TREE,
            "R111 frozen tree")
    require(git(frozen, "rev-parse", "HEAD:src/kernel") ==
            git(connected_frozen, "rev-parse", "HEAD:src/kernel"),
            "R111 product subtree drift")
    composition = load(frozen / COMPOSITION, COMPOSITION_PIN)
    patch = frozen / DM_PATCH
    pin(patch, DM_PATCH_PIN)
    previous = {"completed_steps": []}
    previous_evidence = evidence / "r110-composition"
    previous_evidence.mkdir()
    helper = composition.stage(previous, previous_evidence, composition_inputs,
                               connected_frozen, historical, baseline, linux, module)
    require(previous["stage"] == "PASS_R110_COMPOSED_SOURCE_ONLY" and
            len(previous["linux_stage"]) == 34 and len(previous["module_stage"]) == 57,
            "accepted R110 source composition")
    state["composition"] = previous
    dm_path = "drivers/md/dm.c"
    pin(linux / dm_path, DM_PRE)
    command = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    for label, args, expected in (
        ("check", ["--check"], DM_PRE), ("apply", [], DM_POST),
        ("reverse-check", ["--reverse", "--check"], DM_POST),
        ("reverse", ["--reverse"], DM_PRE), ("reapply", [], DM_POST),
    ):
        helper.step(state, evidence, "r111-dm-" + label, command + args + [str(patch)], linux)
        pin(linux / dm_path, expected)
    # Bind both recorder and module build metadata to the same full frozen
    # composition, not to its earlier product-only checkout.
    makefile_path = helper.GLUE_DIR + "/Makefile"
    makefile = linux / makefile_path
    pin(makefile, "d60db4dabdabab69267800debf05f3d36e821ec1")
    original = makefile.read_bytes()
    anchor = CONNECTED_FREEZE.encode()
    require(original.count(anchor) == 1, "exact recorder source anchor")
    makefile.write_bytes(original.replace(anchor, FREEZE.encode(), 1))
    git(linux, "add", "--", makefile_path)
    staged_paths = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    require(staged_paths == previous["linux_stage"].keys(), "R111 staged path census")
    for name, metadata in previous["linux_stage"].items():
        if name == makefile_path:
            require((linux / name).read_bytes() == original.replace(anchor, FREEZE.encode(), 1),
                    "recorder metadata-only replacement")
        else:
            pin(linux / name, DM_POST if name == dm_path else metadata["blob"])
    for name, metadata in previous["module_stage"].items():
        pin(module / name, metadata["blob"])
    require(not git(linux, "diff", "--name-only") and
            not git(linux, "ls-files", "--others", "--exclude-standard"),
            "unstaged/untracked Linux source")
    helper.step(state, evidence, "r111-staged-diff-check",
                ["git", "diff", "--cached", "--check"], linux)
    state["linux_stage"] = {name: helper.image(linux / name) for name in sorted(staged_paths)}
    state["module_stage"] = previous["module_stage"]
    state["stage"] = "PASS_R111_COMPOSED_SOURCE"
    (evidence / "r111-connected-source.diff").write_bytes(
        git(linux, "diff", "--cached", "--binary"))
    return helper


def build(helper, state, evidence, linux, output, module):
    helper.prerequisites(state, evidence)
    require(shutil.which("modinfo"), "missing-build-tool:modinfo")
    # One guard set for all built-in and module TUs; only Kbuild's MODULE
    # distinction differs. No runtime control is invoked.
    flags = (helper.MODULE_GUARDS + helper.OBSERVATION_GUARDS +
             " -DSWAPZ_ROUND098_SCOPED_PRODUCER_TEST -DSWAPZ_ROUND098_SCOPED_TARGET_TEST"
             " -DSWAPZ_ROUND102_CONTROLLER_TEST -DSWAPZ_ROUND103_EXTERNAL_JOIN_TEST"
             " -DSWAPZ_ROUND104_INTEGRATION_TEST -DSWAPZ_ROUND106_ADMITTED_OWNER_TEST"
             " -DSWAPZ_ROUND107_FINAL_REMOVAL_TEST -DSWAPZ_ROUND109_AREA_PREFLIGHT_TEST"
             " -DSWAPZ_ROUND110_COMPOSED_PREFLIGHT_TEST -I" + str(linux / helper.GLUE_DIR) +
             ' -DSWAPZ_BUILD_SOURCE_SHA=\\"' + FREEZE + '\\" -DSWAPZ_BUILD_SOURCE_CLEAN=1')
    state["guards"] = flags
    output.mkdir()
    make = ["make", "-C", str(linux), "O=" + str(output), "ARCH=x86_64", "CC=gcc", "KCFLAGS=" + flags]
    external = make + ["M=" + str(module)]
    state["commands"] = {"kernel": make + ["-j2", "vmlinux", "modules"],
                         "module": external + ["-j2", "modules"]}
    helper.step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    configure = ["bash", str(linux / "scripts/config"), "--file", str(output / ".config")]
    for key in (*helper.REQUIRED, "MODULE_UNLOAD"):
        configure += ["--enable", key]
    for key in OFF:
        configure += ["--disable", key]
    configure += ["--set-val", "NR_CPUS", "4"]
    helper.step(state, evidence, "configure", configure)
    helper.step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    effective = (output / ".config").read_text().splitlines()
    require(all("CONFIG_" + key + "=y" in effective for key in (*helper.REQUIRED, "MODULE_UNLOAD")) and
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
    require(not (PRIVATE_ONLY & exports.keys()), "unexpected private positive entry export")
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
    require(not (PRIVATE_ONLY & rows.keys()), "private positive entry exported by actual kernel")
    # Check the real linked-in objects from this build. No alternate
    # guard-off profile or repeated build is used to force terminal imports.
    glue = output / helper.GLUE_DIR
    controller_object = glue / "native-observation-controller.o"
    dm_object = output / "drivers/md/dm.o"
    mm_object = output / "mm/zswap.o"
    swapfile_object = output / "mm/swapfile.o"
    for label, obj in (("controller", controller_object), ("dm-core", dm_object), ("mm", mm_object),
                       ("swapfile", swapfile_object)):
        require(obj.is_file(), "missing actual " + label + " object")
        state["artifacts"][label + ".o"] = helper.image(obj)
        shutil.copyfile(obj, evidence / (label + ".o"))
    controller_symbols = text_command(evidence, "controller-object-symbols", ["nm", str(controller_object)])
    controller_imports = undefined(text_command(evidence, "controller-object-imports",
                                               ["nm", "-u", str(controller_object)]))
    require(all(definition_present(controller_symbols, name, "T")
                for name in CONTROLLER_DEFINITIONS), "native controller definitions")
    require({"try_module_get", "module_put"} <= controller_imports, "native module lifetime imports")
    require(not (STARTUP_IMPORTS & controller_imports), "AUTH0 controller positive startup imports")
    dm_symbols = text_command(evidence, "dm-core-object-symbols", ["nm", str(dm_object)])
    dm_relocations = text_command(evidence, "dm-core-object-relocations", ["readelf", "-Wr", str(dm_object)])
    require(definition_present(dm_symbols, "dm_swapz_retire_final_table", "t", True) and
            "swapz_trial_controller_retire_registered" in undefined(dm_symbols) and
            relocation_present(dm_relocations, "swapz_trial_controller_retire_registered"),
            "native private DM final-removal seam and actual controller relocation")
    linked = text_command(evidence, "kernel-all-symbols", ["nm", "--defined-only", str(kernel)])
    require(definition_present(linked, "dm_swapz_retire_final_table", "t", True) and
            all(definition_present(linked, name, "T") for name in CONTROLLER_DEFINITIONS),
            "private native definitions retained in linked kernel")
    swapfile_symbols = text_command(evidence, "swapfile-object-symbols", ["nm", str(swapfile_object)])
    require(definition_present(swapfile_symbols, AREA_QUERY, "T") and
            definition_present(kernel_symbols, AREA_QUERY, "T") and
            definition_present(dm_symbols, COMBINED_QUERY, "t", True) and
            definition_present(linked, COMBINED_QUERY, "t", True),
            "actual composed MM and DM private definitions")
    require({AREA_QUERY, TARGET_QUERY} <= undefined(dm_symbols),
            "actual DM composed private imports")
    counts = {name: sum(relocation_present(line, name) for line in dm_relocations.splitlines())
              for name in (AREA_QUERY, TARGET_QUERY)}
    require(counts == {AREA_QUERY: 2, TARGET_QUERY: 1}, "actual MM-target-MM relocations")
    state["composed_native"] = {"relocations": counts, "mm_definition": AREA_QUERY,
                                "dm_local_definition": COMBINED_QUERY,
                                "private_exports": sorted({AREA_QUERY, COMBINED_QUERY} & rows.keys())}
    state["auth0_native"] = {"controller_lifetime_imports": ["module_put", "try_module_get"],
        "positive_startup_imports": sorted(STARTUP_IMPORTS & controller_imports),
        "terminal_imports": {name: name in controller_imports for name in sorted(TERMINAL_IMPORTS)},
        "private_dm_seam": "LOCAL_DEFINED_AND_LINKED_WITH_RETIRE_RELOCATION",
        "private_entry_exports": sorted(PRIVATE_ONLY & rows.keys()),
        "terminal_import_note": "AUTH0 publication unreachable; optimizer may remove terminal paths"}
    # Ensure the original MM negative entry is actually emitted, not a stub
    # replacing the real frozen source. Retain real object disassembly.
    mm_symbols = text_command(evidence, "mm-object-symbols", ["nm", str(mm_object)])
    require(definition_present(mm_symbols, "swapz_mm_trial_scope_publish", "T"), "native MM admission definition")
    for label, obj, name in (("mm", mm_object, "swapz_mm_trial_scope_publish"),
                             ("controller", controller_object, "swapz_trial_controller_begin_registered")):
        code = text_command(evidence, label + "-admission-disassembly",
                            ["objdump", "-dr", "--disassemble=" + name, str(obj)])
        require("<" + name + ">:" in code, "actual admission disassembly " + label)
    print("R111_A10_AUTH0_NATIVE", json.dumps(state["auth0_native"], sort_keys=True), flush=True)
    state["private_export_rows"] = {name: rows.get(name) for name in sorted(private)}
    # Actual MODPOST resolves against the same full kernel's Module.symvers.
    # Do not use KBUILD_MODPOST_WARN or hand-written symbol files.
    helper.step(state, evidence, "external-module-modpost-link", state["commands"]["module"], timeout=1200)
    ko = module / "dm-swapz.ko"
    require(ko.is_file(), "missing actual dm-swapz.ko")
    state["modpost"] = "PASS_GENUINE"
    state["module_link"] = "PASS"
    counts = {}
    for line in symvers.read_text().splitlines():
        fields = line.split()
        if len(fields) >= 4:
            counts[fields[1]] = counts.get(fields[1], 0) + 1
    require(private <= rows.keys() and all(counts[name] == 1 and
            rows[name][2:4] == ["vmlinux", "EXPORT_SYMBOL_GPL"] for name in private),
            "private built-in GPL export census")
    module_symbols = text_command(evidence, "module-symbols", ["nm", "-g", "--defined-only", str(ko)])
    final_imports = undefined(text_command(evidence, "module-imports", ["nm", "-u", str(ko)]))
    require({name for name in final_imports if name.startswith(("swapz_", "dm_swapz_"))} == private,
            "final private import drift")
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
            {"SMP", "mod_unload"} <= set(info["vermagic"].split()), "module GPL/vermagic/unload")
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
    frozen, composition_inputs, connected_frozen, historical, baseline, linux, scratch, evidence = map(
        lambda value: Path(value).resolve(), sys.argv[1:])
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    scratch.mkdir(mode=0o700, parents=True, exist_ok=False)
    start = time.monotonic()
    state = {"round": 111, "agent": 10, "source_freeze": FREEZE, "source_tree": TREE,
             "linux": LINUX, "tested_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
             "parent": git(ROOT, "rev-parse", "HEAD^").decode().strip(),
             "AUTH": 0, "phase_a": "BLOCKED", "actual_physical_io": False, "runtime": "NOT_RUN",
             "handoff": "OFF", "forced_raw": "OFF", "import": "OFF",
             "stage": "NOT_RUN", "status": "FAIL", "full_build_attempts": 0,
             "full_kernel_link": "NOT_RUN", "module_link": "NOT_RUN", "modpost": "NOT_RUN",
             "completed_steps": [], "artifacts": {}, "first_error": None}
    try:
        symbol_census_selftest()
        for key in ("KBUILD_MODPOST_WARN", "KBUILD_EXTRA_SYMBOLS"):
            require(not os.environ.get(key), "forbidden build environment " + key)
        helper = stage(state, evidence, frozen, composition_inputs, connected_frozen,
                       historical, baseline, linux, scratch / "module")
        build(helper, state, evidence, linux, scratch / "output", scratch / "module")
        state["status"] = "PASS_CONNECTED_COMPILE_LINK_ONLY"
        print("R111_A10_CONNECTED_COMPILE_LINK_PASS AUTH0 NO_RUNTIME", flush=True)
        return 0
    except Exception as error:
        state["first_error"] = str(error).split("\n", 1)[0][:500]
        print("R111_A10_FIRST_ERROR " + state["first_error"], file=sys.stderr, flush=True)
        return 1
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        state["resources"] = {"elapsed_seconds": round(time.monotonic() - start, 3),
                              "child_user_seconds": usage.ru_utime, "child_system_seconds": usage.ru_stime,
                              "child_max_rss_kib": usage.ru_maxrss}
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
