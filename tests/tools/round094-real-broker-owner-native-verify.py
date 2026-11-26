#!/usr/bin/env python3
"""Directed native compile of the actual R094 built-in broker; no full link/load."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "40b52f8e7a80680dcb6b074df5be897f57eae1b9"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
HOST = ROOT / "tests/tools/round094-real-broker-owner-verify.py"
PRIOR = ROOT / "tests/tools/round093-external-broker-owner-verify.py"
CONFIG = ROOT / "tests/tools/round093-actual-raw-r092-compile-verify.py"
PINS = {
    HOST: "d0207a8bc0021f12c8d11927b4dfbae4444e5c26",
    PRIOR: "d26d5b6c645c90742d50b70e4c1e1f04f265053e",
    CONFIG: "2aa197fe2d22446f27e6af5777eb3daf5cbed620",
}
GLUE = "mm/round094-broker-owner"
EXPORTS = {
    "swapz_ticket_put", "swapz_ticket_view", "swapz_ticket_broker_put",
    "swapz_ticket_broker_try_get", "swapz_ticket_claim_under_queue_lock",
    "swapz_mm_broker_owner_open", "swapz_mm_broker_owner_begin_close",
    "swapz_mm_broker_owner_finish_close",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(args, cwd=ROOT, timeout=180):
    return subprocess.run(args, cwd=cwd, capture_output=True, check=False, timeout=timeout)


def checked(args, cwd=ROOT):
    result = command(args, cwd)
    require(result.returncode == 0, "command failed: " + str(args[0]))
    return result.stdout


def digest(data):
    return hashlib.sha256(data).hexdigest()


def pin(path, expected):
    require(checked(["git", "hash-object", str(path)]).decode().strip() == expected,
            "blob pin " + path.name)


def step(state, evidence, label, args, timeout=180):
    state["phase"] = label
    result = command(args, timeout=timeout)
    output = result.stdout + result.stderr
    (evidence / (label + ".log")).write_bytes(output)
    if result.returncode:
        lines = output.decode(errors="replace").splitlines()
        first = next((line for line in lines if re.search(r"fatal error:|error:|Error |No rule to make|not found", line)),
                     next((line for line in lines if line.strip()), "no diagnostic"))
        raise RuntimeError(label + ": exit " + str(result.returncode) + ": " + first[:350])
    state["completed_steps"].append(label)
    return result.stdout


def stage(state, linux, evidence):
    require(checked(["git", "rev-parse", "HEAD"], linux).decode().strip() == LINUX,
            "original Linux pin")
    require(not checked(["git", "status", "--porcelain", "--untracked-files=all"], linux),
            "dirty original Linux")
    for path, expected in PINS.items():
        pin(path, expected)
    host = runpy.run_path(str(HOST))
    prior = runpy.run_path(str(CONFIG))
    glue = linux / GLUE
    require(not glue.exists(), "scratch glue already exists")
    glue.mkdir()
    with tempfile.TemporaryDirectory(prefix="r094-native-owner-stage-") as temporary:
        staged = Path(temporary)
        # Exact R092/R094 broker C/H staging only; do not execute host tests.
        host["stage"](staged)
        paths = [host["BROKER"], host["HEADER"], host["OWNER"],
                 "src/kernel/codec.h"]
        expected = {**host["PRIOR"]["PINS"], **host["PINS"], **host["POST"]}
        state["inputs"] = {}
        for path in paths:
            source = staged / path
            pin(source, expected[path])
            target = glue / source.name
            shutil.copyfile(source, target)
            pin(target, expected[path])
            state["inputs"][path] = {"blob": expected[path], "sha256": digest(target.read_bytes())}
    # Only scratch Kbuild changes, not the repository's production build.
    (glue / "Makefile").write_text("obj-y += zswap-original-ticket.o\n")
    with (linux / "mm/Kconfig").open("a") as out:
        out.write(prior["KCONFIG"])
    with (linux / "mm/Makefile").open("a") as out:
        out.write("\nobj-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += round094-broker-owner/\n")
    state["completed_steps"].append("exact-stage")
    return prior["REQUIRED"]


def build(state, evidence, linux, out, required):
    require(not out.exists(), "existing build output")
    out.mkdir(parents=True)
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64",
            "CC=gcc", "KCFLAGS=-DSWAPZ_ORIGINAL_TICKET_TEST -Werror"]
    for tool in ("gcc", "ld", "nm", "objcopy", "readelf", "make", "flex", "bison", "bc"):
        require(shutil.which(tool), "missing runner prerequisite " + tool)
    state["compiler"] = checked(["gcc", "--version"]).decode().splitlines()[0]
    step(state, evidence, "allnoconfig", make + ["allnoconfig"])
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for name in required:
        config += ["--enable", name]
    for name in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                 "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF"):
        config += ["--disable", name]
    step(state, evidence, "set-config", config)
    step(state, evidence, "olddefconfig", make + ["olddefconfig"])
    effective = (out / ".config").read_bytes()
    config_lines = set(effective.decode().splitlines())
    require(all("CONFIG_" + name + "=y" in config_lines for name in required),
            "missing required effective config")
    require("CONFIG_ZSWAP_DEFAULT_ON=y" not in config_lines and "CONFIG_KUNIT=y" not in config_lines,
            "unexpected activation config")
    (evidence / "effective.config").write_bytes(effective)
    state["config_sha256"] = digest(effective)
    state["build_attempts"] = 1
    relative = GLUE + "/zswap-original-ticket.o"
    step(state, evidence, "directed-native-object", make + ["-j2", relative], timeout=900)
    obj = out / relative
    require(obj.is_file() and 0 < obj.stat().st_size <= 4 * 1024 * 1024, "object size")
    # The pinned Linux export.h emits local __export_symbol_* labels in
    # .export_symbol; license bytes begin at each section-relative offset.
    symbols = step(state, evidence, "symbol-inventory", ["nm", "-a", "--defined-only", str(obj)])
    exports = {}
    for line in symbols.decode().splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)\s+\w\s+__export_symbol_(\w+)", line)
        if match:
            exports[match[2]] = int(match[1], 16)
    require(set(exports) == EXPORTS, "exact built-in broker export inventory")
    section = evidence / "export-symbol.bin"
    step(state, evidence, "export-section",
         ["objcopy", "--dump-section", ".export_symbol=" + str(section), str(obj),
          str(out / "export-inspection.o")])
    data = section.read_bytes()
    require(all(data[offset:offset + 4] == b"GPL\0" for offset in exports.values()),
            "non-GPL export in native object")
    defined = step(state, evidence, "global-definitions", ["nm", "-g", "--defined-only", str(obj)])
    names = {line.split()[-1] for line in defined.decode().splitlines() if line.split()}
    require(EXPORTS <= names, "missing native public definition")
    undefined = step(state, evidence, "undefined-symbols", ["nm", "-u", str(obj)])
    imports = {line.split()[-1] for line in undefined.decode().splitlines() if line.split()}
    require(not (EXPORTS & imports), "unresolved owner/broker definition")
    require("swapz_crc32c_bytes" in imports, "unexpected missing external codec dependency")
    header = step(state, evidence, "elf-header", ["readelf", "-h", str(obj)]).decode()
    require("ELF64" in header and "REL (Relocatable file)" in header and "X86-64" in header,
            "unexpected native ELF type")
    shutil.copyfile(obj, evidence / obj.name)
    state.update(object_bytes=obj.stat().st_size, object_sha256=digest(obj.read_bytes()),
                 native_exports=sorted(exports), native_gpl_exports=len(exports),
                 undefined_symbols=sorted(imports), native_compile="PASS",
                 native_link="NOT_RUN", native_modpost="NOT_RUN")
    state["completed_steps"].append("native-object-export-verification")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    linux, out, evidence = (p.resolve() for p in (args.linux, args.out, args.evidence))
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"status": "IN_PROGRESS", "phase": "stage", "owner_source": SOURCE,
             "tested_commit": checked(["git", "rev-parse", "HEAD"]).decode().strip(),
             "original_linux": LINUX, "completed_steps": [], "build_attempts": 0,
             "first_error": None, "native_compile": "NOT_RUN", "native_link": "NOT_RUN",
             "native_modpost": "NOT_RUN", "native_rcu": "NOT_RUN", "full_build": False,
             "host_corpus_replayed": False, "vm": False, "module_loaded": False,
             "physical": False, "auth": 0, "phase_a": "BLOCKED",
             "compressed_handoff": False, "forced_raw_bypass": False, "import": False}
    try:
        require(len({linux, out, evidence, ROOT}) == 4, "aliased paths")
        required = stage(state, linux, evidence)
        build(state, evidence, linux, out, required)
        state.update(status="PASS_NATIVE_OBJECT_ONLY", phase="complete")
        print("R094_A11_NATIVE_OBJECT_PASS exports=8 gpl=8 full_build=NO modpost=NO AUTH0")
        return 0
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        state.update(status="FAIL", first_error=str(error)[:450])
        print("R094_A11_NATIVE_FIRST_ERROR " + state["first_error"], file=sys.stderr)
        return 2
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2) + "\n")


if __name__ == "__main__":
    sys.exit(main())
