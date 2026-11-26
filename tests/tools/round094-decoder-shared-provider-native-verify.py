#!/usr/bin/env python3
"""One directed native compile of the R094 actual shared provider; no replay/link/load."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "0bd024561b2b03fa7837556cbd723f8f27d80b27"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PINS = {
    "zswap-original-decoder-shared.c": "a5432d7330134c08a44356f49ef47cf0d02080ee",
    "zswap-original-decoder-shared.h": "4cffad5778872b063eda7d8e5d781aa508f547cd",
    "zswap-original-decoder-handles.h": "0f103783aee10d18df5c502fdf553f7ac6a0035d",
    "zswap-original-decode.h": "a247d1aaf9865de71f97cd980be806b8d8c7c20e",
    "zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
}
DEFINITIONS = {"swapz_original_decoder_shared_" + name for name in
               ("init", "read", "begin_close", "finish_close")}
IMPORTS = {"swapz_original_decode"} | {
    "swapz_zswap_import_decoder_owner_" + name for name in
    ("init", "get", "put", "close_and_drain")}


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def step(state, evidence, name, args, timeout=180):
    state["phase"] = name
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    data = result.stdout + result.stderr
    (evidence / (name + ".log")).write_bytes(data)
    if result.returncode:
        lines = data.decode(errors="replace").splitlines()
        diagnostic = next((line for line in lines if re.search(
            r"fatal error:|error:|Error |No rule to make|not found", line)), "")
        # Retain full private log, expose only bounded known source basename/line.
        location = re.search(r"(zswap-original-decoder-shared\.[ch]):(\d+)(?::(\d+))?", diagnostic)
        state["first_error"] = {"phase": name, "exit": result.returncode,
                                "location": location.group(0) if location else "unavailable"}
        raise RuntimeError("native step failed: " + name)
    state["completed_steps"].append(name)
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("linux", "out", "module", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    linux, out, module, evidence = (getattr(args, name).resolve() for name in
                                    ("linux", "out", "module", "evidence"))
    os.umask(0o077)
    evidence.mkdir(parents=True, exist_ok=True)
    state = {"round": "094", "agent": 7, "status": "FAIL", "phase": "preflight",
             "provider_source": SOURCE, "linux_pin": LINUX, "first_error": None,
             "completed_steps": [], "native_compile": "NOT_RUN", "native_link": "NOT_RUN",
             "native_modpost": "NOT_RUN", "native_runtime": "NOT_RUN", "build_attempts": 0,
             "host_corpus_replayed": False, "full_kernel_build": False, "vm": False,
             "module_loaded": False, "physical": False, "source_mapped_authenticated": 0,
             "phase_a": "BLOCKED", "compressed_handoff": False,
             "forced_raw_bypass": False, "import_active": False}
    try:
        require(len({ROOT, linux, out, module, evidence}) == 5 and
                not any(a.is_relative_to(b) for a in (out, module, evidence)
                        for b in (ROOT, linux)), "aliased scratch paths")
        require(not out.exists() and not module.exists(), "scratch exists")
        state["tested_commit"] = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
        require(subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"],
                                        text=True).strip() == LINUX, "Linux pin drift")
        require(not subprocess.check_output(["git", "-C", str(linux), "status",
                                             "--porcelain", "--untracked-files=all"]), "dirty Linux")
        for tool in ("gcc", "ld", "nm", "readelf", "make", "flex", "bison", "bc"):
            require(shutil.which(tool), "missing runner prerequisite " + tool)
        state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
        module.mkdir()
        out.mkdir()
        for name, expected in PINS.items():
            data = (ROOT / "src/kernel" / name).read_bytes()
            require(blob(data) == expected, "source pin drift: " + name)
            (module / name).write_bytes(data)
        state["inputs"] = PINS
        require("#define SWAPZ_ORIGINAL_DECODER_SHARED_ACTIVE 0U" in
                (module / "zswap-original-decoder-shared.h").read_text(), "activation drift")
        (module / "Makefile").write_text(
            "obj-m += zswap-original-decoder-shared.o\n"
            "ccflags-y += -DSWAPZ_ORIGINAL_STORAGE_TEST -DSWAPZ_ORIGINAL_DECODER_SHARED_TEST -Werror\n")
        make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64", "CC=gcc"]
        step(state, evidence, "allnoconfig", make + ["allnoconfig"])
        config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
        step(state, evidence, "set-config", config + ["--enable", "MODULES",
             "--disable", "ZSWAP_DEFAULT_ON", "--disable", "KUNIT",
             "--disable", "DEBUG_INFO", "--disable", "DEBUG_INFO_BTF"])
        step(state, evidence, "olddefconfig", make + ["olddefconfig"])
        effective = (out / ".config").read_bytes()
        (evidence / "effective.config").write_bytes(effective)
        require(b"CONFIG_MODULES=y\n" in effective and b"CONFIG_ZSWAP_DEFAULT_ON=y\n" not in effective,
                "unexpected effective configuration")
        state["config_sha256"] = hashlib.sha256(effective).hexdigest()
        step(state, evidence, "modules-prepare", make + ["-j2", "modules_prepare"], timeout=600)
        state["build_attempts"] = 1
        step(state, evidence, "directed-native-object",
             make + ["M=" + str(module), "-j2", "zswap-original-decoder-shared.o"], timeout=600)
        obj = module / "zswap-original-decoder-shared.o"
        require(obj.is_file() and 0 < obj.stat().st_size <= 4 * 1024 * 1024, "object size")
        defined = step(state, evidence, "defined-symbols", ["nm", "-g", "--defined-only", str(obj)])
        undefined = step(state, evidence, "undefined-symbols", ["nm", "-u", str(obj)])
        names = {line.split()[-1] for line in defined.decode().splitlines() if line.split()}
        imports = {line.split()[-1] for line in undefined.decode().splitlines() if line.split()}
        require(DEFINITIONS <= names and not DEFINITIONS & imports, "missing native definitions")
        require(IMPORTS <= imports, "missing actual decoder-owner call relocations")
        require(not any(name.startswith(("pthread_", "malloc", "free", "module_get",
                                         "try_module_get", "module_put")) for name in imports),
                "unexpected host/allocation/module reference import")
        elf = step(state, evidence, "elf-header", ["readelf", "-h", str(obj)]).decode()
        require("ELF64" in elf and "REL (Relocatable file)" in elf and "X86-64" in elf,
                "wrong ELF object")
        require(not (out / "vmlinux").exists() and not list(module.glob("*.ko")),
                "unexpected kernel/module build")
        require(all(blob((module / name).read_bytes()) == expected for name, expected in PINS.items()),
                "staged source drift")
        require(not subprocess.check_output(["git", "-C", str(linux), "status",
                                             "--porcelain", "--untracked-files=all"]), "Linux changed")
        shutil.copyfile(obj, evidence / obj.name)
        state.update(status="PASS_NATIVE_OBJECT_ONLY", phase="complete", native_compile="PASS",
                     object_bytes=obj.stat().st_size, object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),
                     defined_symbols=sorted(names), undefined_symbols=sorted(imports))
        print("PASS ROUND094_AGENT7_NATIVE_OBJECT_ONLY AUTH0", flush=True)
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        if state["first_error"] is None:
            state["first_error"] = {"phase": state["phase"], "kind": type(error).__name__,
                                    "reason": str(error).split("\n", 1)[0][:200]}
        print("FIRST_ERROR ROUND094_AGENT7_NATIVE " + json.dumps(state["first_error"]), file=sys.stderr)
        return 1
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
        print(json.dumps(state, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
