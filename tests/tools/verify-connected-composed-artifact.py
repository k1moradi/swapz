#!/usr/bin/env python3
"""Independently inspect an AUTH0 connected-build archive; no execution of its ELF files."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

PRIVATE = {"swapz_mm_trial_scope_publish", "swapz_mm_trial_area_preflight",
           "dm_swapz_combined_preflight", "dm_swapz_retire_final_table",
           "swapz_trial_controller_begin_registered", "swapz_trial_controller_query_registered",
           "swapz_trial_controller_retire_registered"}
REQUIRED = {"vmlinux", "dm-swapz.ko", "kernel-Module.symvers", "controller.o",
            "dm-core.o", "mm.o", "swapfile.o"}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True, timeout=60)


def symbols(path):
    return [line.split() for line in command("nm", str(path)).splitlines() if line.strip()]


def undefined(rows):
    return {row[-1] for row in rows if row[0] == "U"}


def defined(rows, name, kind):
    return any(len(row) == 3 and row[1:] == [kind, name] for row in rows)


def verify(path, archive_sha, freeze, tree):
    require(sha(path.read_bytes()) == archive_sha, "archive SHA256")
    with zipfile.ZipFile(path) as archive, tempfile.TemporaryDirectory() as temporary:
        names = archive.namelist()
        require(len(names) == len(set(names)) and archive.testzip() is None, "archive integrity")
        result = json.loads(archive.read("results.json"))
        require(result["source_freeze"] == freeze and result["source_tree"] == tree and
                result["AUTH"] == 0 and result["status"] == "PASS_CONNECTED_COMPILE_LINK_ONLY" and
                result["full_kernel_link"] == result["module_link"] == "PASS" and
                result["modpost"] == "PASS_GENUINE", "qualification scope")
        require(REQUIRED <= result["artifacts"].keys(), "missing binary evidence")
        root = Path(temporary)
        for name in REQUIRED:
            data = archive.read(name)
            metadata = result["artifacts"][name]
            require(len(data) == metadata["bytes"] and sha(data) == metadata["sha256"], name)
            (root / name).write_bytes(data)
        config = archive.read("effective.config").decode().splitlines()
        for option in ("CONFIG_SMP=y", "CONFIG_TREE_RCU=y", "CONFIG_NR_CPUS=4", "CONFIG_MODULE_UNLOAD=y"):
            require(option in config, option)
        for option in ("MODULE_FORCE_UNLOAD", "ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON"):
            require("CONFIG_" + option + "=y" not in config, option)
        kernel = symbols(root / "vmlinux")
        module = undefined(symbols(root / "dm-swapz.ko"))
        dm = symbols(root / "dm-core.o")
        mm = symbols(root / "swapfile.o")
        exports = {row[1]: row for line in (root / "kernel-Module.symvers").read_text().splitlines()
                   if (row := line.split())}
        require(not undefined(kernel) and module <= exports.keys(), "unresolved strong import")
        require(not PRIVATE & exports.keys(), "private entry exported")
        for name, kind in (("swapz_mm_trial_area_preflight", "T"),
                           ("swapz_trial_controller_query_registered", "T"),
                           ("dm_swapz_combined_preflight", "t"), ("dm_swapz_retire_final_table", "t")):
            require(defined(kernel, name, kind), "linked definition " + name)
        require(defined(mm, "swapz_mm_trial_area_preflight", "T") and
                defined(dm, "dm_swapz_combined_preflight", "t"), "native object definitions")
        relocations = command("readelf", "-Wr", str(root / "dm-core.o")).splitlines()
        counts = {name: sum(name in line.split() for line in relocations) for name in
                  ("swapz_mm_trial_area_preflight", "swapz_trial_controller_query_registered")}
        require(list(counts.values()) == [2, 1], "MM-target-MM relocations")
        info = command("readelf", "-p", ".modinfo", str(root / "dm-swapz.ko"))
        require("swapz_build_source_sha=" + freeze in info and "swapz_build_source_clean=1" in info and
                "license=GPL" in info and freeze.encode() in (root / "vmlinux").read_bytes(), "build metadata")
        # Specific x86_64 AUTH0 build: actual mov -EACCES, ret instruction bytes.
        for file, name in (("mm.o", "swapz_mm_trial_scope_publish"),
                           ("controller.o", "swapz_trial_controller_begin_registered")):
            body = command("objdump", "-d", "--disassemble=" + name, str(root / file))
            instructions = [line.split("\t")[1].split() for line in body.splitlines()
                            if "\t" in line and len(line.split("\t")) >= 3]
            require(instructions == [["b8", "f3", "ff", "ff", "ff"], ["c3"]], "AUTH0 body " + name)
        return {"status": "PASS_ARCHIVE_BINARY_INSPECTION_ONLY", "members": len(names),
                "strong_module_imports": len(module), "strong_kernel_imports": 0,
                "composed_relocations": counts, "AUTH": 0, "runtime": "NOT_RUN"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("sha256")
    parser.add_argument("freeze")
    parser.add_argument("tree")
    args = parser.parse_args()
    print(json.dumps(verify(args.archive, args.sha256, args.freeze, args.tree), sort_keys=True))
