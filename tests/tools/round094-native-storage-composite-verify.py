#!/usr/bin/env python3
"""One native, relocatable Kbuild composite; no full kernel or module build."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

FREEZE = "efd77858cd20650213559ceb9cb4d0362db32ea5"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
STAGER = "tests/tools/round093-actual-raw-r092-compile-verify.py"
STAGER_PIN = "2aa197fe2d22446f27e6af5777eb3daf5cbed620"
FIXTURE = "tests/runtime/native/fixtures/round094-native-value-decoder-link.c"
FIXTURE_PIN = "4b861621223356bc9e1a6fa5c96f377771f216f0"
PRIOR_SOURCE = "9f944f4e83762b846e02aade88d2c36574c8ac13"
PRIOR_CONFIG = "89127024a38ad68dd091c9dd5787bba097b85c8ce69d118cd147a8d7ff4c6d0b"
PRIOR_KERNEL = "6f2c6dc03232256884c4fbdb0e17ffdd6f229fc8819f528389cc1abca2af6438"
PRIOR_MODULE = "88add0aa34b6f86db24b7e9fb10b2945ed7936f35ac5220243ff07b14198bd56"
VALUE_PINS = {
    "dm-target.c": "27d3af6f4146bc62adfb091e0d4f1fbc9f1dd285",
    "zswap-original-storage-value.c": "8f532824e9c63a6498d71fcb1ce4c35b18130f1e",
    "zswap-original-storage-value.h": "9b6be5452ff9a7ecb20fb8e661b593c290cc8b7e",
}
VALUE_FUNCTIONS = {
    "swapz_shared_storage_value_" + suffix for suffix in (
        "init", "write", "reserve", "cancel_reserved", "commit_reserved",
        "pin", "put", "read_pinned", "decode_pinned", "relocate", "close")
}
DECODER_FUNCTIONS = {
    "swapz_original_decoder_handle_get", "swapz_original_decoder_handle_put",
    "swapz_original_decoder_handle_read", "swapz_original_decoder_handles_init",
    "swapz_original_decoder_handles_close",
}
WITNESS = "round094-native-value-decoder-link.c"


def load_stager(baseline):
    # Verify exact bytes before executing the accepted staging helper.
    import hashlib
    path = baseline / STAGER
    data = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != STAGER_PIN:
        raise ValueError("inherited-stager-blob-mismatch")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("frozen_r093_stager", path)
    stager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stager)
    return stager


def strong_undefined(path):
    output = subprocess.check_output(["nm", "-u", str(path)], text=True)
    return output, {fields[1] for line in output.splitlines()
                    if len(fields := line.split()) == 2 and fields[0] == "U"}


def prior_reference(stager, state, prior):
    stager.require(prior.is_dir(), "missing-prior-reference")
    previous = json.loads((prior / "results.json").read_text())
    stager.require(previous["source_sha"] == PRIOR_SOURCE and
                   previous["status"] == "SUCCESS" and
                   previous["actual_raw_r092_overlay"] and
                   previous["full_kernel_link"] and previous["product_module_link"],
                   "prior-result-identity")
    for filename, expected in (("vmlinux", PRIOR_KERNEL),
                               ("dm-swapz.ko", PRIOR_MODULE),
                               ("effective.config", PRIOR_CONFIG),
                               ("kernel-Module.symvers", previous["module_symvers_sha256"])):
        stager.require(stager.digest((prior / filename).read_bytes()) == expected,
                       "prior-reference-hash:" + filename)
    rows = {fields[1]: fields for line in (prior / "kernel-Module.symvers").read_text().splitlines()
            if len(fields := line.split()) >= 4}
    stager.require(all(symbol in rows and rows[symbol][2] == "vmlinux" and
                       rows[symbol][3] == "EXPORT_SYMBOL_GPL"
                       for symbol in stager.MODULE_BOUNDARY), "prior-boundary-exports")
    state["prior_reference"] = {
        "run_id": 45666130617, "artifact_id": 15047232671,
        "source": PRIOR_SOURCE, "config_sha256": PRIOR_CONFIG,
        "kernel_sha256": PRIOR_KERNEL, "module_sha256": PRIOR_MODULE,
        "symvers_sha256": previous["module_symvers_sha256"],
        "usage": "read-only comparison, not copied into Kbuild, no new modpost",
    }
    return rows


def compile_composite(stager, state, evidence, linux, out, module, prior):
    step = stager.step
    require = stager.require
    state["phase"] = "prior-reference"
    rows = prior_reference(stager, state, prior)
    state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    state["linker"] = subprocess.check_output(["ld", "--version"], text=True).splitlines()[0]
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64",
            "CC=gcc", "KCFLAGS=" + stager.GUARDS]
    out.mkdir()
    step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for key in stager.REQUIRED:
        config += ["--enable", key]
    disabled = ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF")
    for key in disabled:
        config += ["--disable", key]
    step(state, evidence, "set-build-config", config)
    step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    state["phase"] = "effective-config"
    effective = (out / ".config").read_bytes()
    shutil.copyfile(out / ".config", evidence / "effective.config")
    state["config_sha256"] = stager.digest(effective)
    lines = effective.decode().splitlines()
    require(all("CONFIG_" + key + "=y" in lines for key in stager.REQUIRED),
            "missing-effective-required-config")
    require(all("CONFIG_" + key + "=y" not in lines for key in disabled),
            "unexpected-effective-config")
    require(state["config_sha256"] == PRIOR_CONFIG, "effective-config-differs-from-prior")
    # Prepare native kernel headers and host tools only, not vmlinux.
    step(state, evidence, "modules-prepare", make + ["-j2", "modules_prepare"], timeout=600)
    module_make = make[:-1] + ["KCFLAGS=" + stager.GUARDS +
                              " -DSWAPZ_SHARED_STORAGE_VALUE_TEST", "M=" + str(module)]
    directed = (*stager.PRODUCT_OBJECTS, WITNESS.replace(".c", ".o"))
    state["build_attempts"] = 1
    step(state, evidence, "directed-native-objects", module_make + ["-j2", *directed], timeout=900)
    state["directed_objects"] = {name: stager.image(module / name) for name in directed}
    for name in directed:
        require((module / name).stat().st_size <= 16 * 1024 * 1024, "object-size-budget:" + name)
        shutil.copyfile(module / name, evidence / name)
    state["phase"] = "callback-link-witness"
    witness_nm, witness_imports = strong_undefined(module / WITNESS.replace(".c", ".o"))
    (evidence / "witness-undefined.txt").write_text(witness_nm)
    require({"swapz_original_decoder_handle_get", "swapz_original_decoder_handle_put",
             "swapz_original_decoder_handle_read", "swapz_shared_storage_value_init"}
            <= witness_imports, "missing-real-callback-relocations")
    value_nm, value_imports = strong_undefined(module / "zswap-original-storage-value.o")
    (evidence / "value-undefined.txt").write_text(value_nm)
    require({"swapz_shared_storage_init", "swapz_shared_storage_read_pinned",
             "swapz_shared_storage_reserve", "swapz_shared_storage_commit_reserved"}
            <= value_imports, "missing-real-storage-relocations")
    # Kbuild's single .o goal invokes actual multi-object ld -r.
    # Do not ask for modules/.ko, and do not synthesize Module.symvers.
    step(state, evidence, "native-composite-link", module_make + ["-j2", "dm-swapz.o"], timeout=900)
    state["phase"] = "composite-symbol-check"
    composite = module / "dm-swapz.o"
    require(composite.is_file(), "missing-composite")
    require(composite.stat().st_size <= 32 * 1024 * 1024, "composite-size-budget")
    shutil.copyfile(composite, evidence / "dm-swapz.o")
    state["composite"] = stager.image(composite)
    state["composite_link"] = True
    step(state, evidence, "composite-elf", ["readelf", "-h", str(composite)])
    elf = (evidence / "composite-elf.log").read_text()
    require("ELF64" in elf and "REL (Relocatable file)" in elf and
            "Advanced Micro Devices X86-64" in elf, "wrong-composite-elf")
    defined_text = subprocess.check_output(["nm", "-g", "--defined-only", str(composite)], text=True)
    (evidence / "composite-defined.txt").write_text(defined_text)
    defined = {line.split()[-1] for line in defined_text.splitlines() if line.split()}
    required = VALUE_FUNCTIONS | DECODER_FUNCTIONS | {"round094_value_bind",
        "swapz_original_decode", "swapz_shared_storage_init", "swapz_shared_storage_reserve",
        "swapz_shared_storage_commit_reserved", "swapz_shared_storage_read_pinned"}
    require(required <= defined, "missing-composite-definitions:" + ",".join(sorted(required - defined)))
    imports_text, imports = strong_undefined(composite)
    (evidence / "composite-undefined.txt").write_text(imports_text)
    # __this_module is generated by a future actual modpost/module link.
    # Do not count it as a kernel export or hide any other unknown import.
    metadata = imports & {"__this_module"}
    external = imports - metadata
    require(not (required & imports), "unresolved-internal-storage-decoder")
    boundary = {symbol for symbol in external if symbol.startswith(
        ("swapz_mm_", "swapz_ticket_", "dm_swapz_"))}
    require(boundary <= set(stager.MODULE_BOUNDARY), "unreviewed-boundary-import")
    require(not (set(stager.MODULE_BOUNDARY) & defined), "duplicate-built-in-boundary")
    missing = external - rows.keys()
    state["actual_composite_imports"] = sorted(imports)
    state["module_metadata_imports"] = sorted(metadata)
    state["actual_boundary_imports"] = sorted(boundary)
    state["required_internal_definitions"] = sorted(required)
    state["missing_prior_export_rows"] = sorted(missing)
    require(not missing, "new-import-not-in-prior-export-inventory:" + ",".join(sorted(missing)))
    require(not (out / "vmlinux").exists() and not (module / "dm-swapz.ko").exists(),
            "unexpected-full-kernel-or-module")
    state["phase"] = "final-source-check"
    for path in set(stager.IMAGES) | set(stager.R092_IMAGES):
        stager.pin(linux / path, stager.final_raw_pin(path))
    for name in stager.PRODUCT:
        if name == "Makefile":
            require(stager.image(module / name) == state["module_makefile_compatible"],
                    "module-kbuild-drift")
        else:
            stager.pin(module / name, stager.final_product_pin(name))
    stager.pin(module / WITNESS, FIXTURE_PIN)
    for path, expected in state["scratch_postimages"].items():
        require(stager.image(linux / path) == expected, "scratch-drift:" + path)
    require(stager.digest((out / ".config").read_bytes()) == PRIOR_CONFIG, "config-drift")
    state["completed_steps"].append("final-source-check")


def main():
    parser = argparse.ArgumentParser()
    for name in ("baseline", "linux", "out", "module", "evidence", "prior"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-parent", required=True)
    args = parser.parse_args()
    baseline, linux, out, module, evidence, prior = (
        getattr(args, name).resolve() for name in ("baseline", "linux", "out", "module", "evidence", "prior"))
    os.umask(0o077)
    evidence.mkdir(parents=True, exist_ok=True)
    state = {
        "status": "IN_PROGRESS", "phase": "preflight", "first_error": None,
        "source_sha": args.source_sha, "source_parent": args.source_parent,
        "frozen_product": FREEZE, "linux_pin": LINUX, "inherited_stager": STAGER_PIN,
        "raw_patches_applied": False, "actual_raw_r092_overlay": False,
        "old_scratch_exports": False, "build_attempts": 0,
        "composite_link": False, "full_kernel_link": False, "modpost": "NOT_RUN",
        "final_ko": "NOT_RUN", "vm_boot": False, "vm_build": False,
        "module_loaded": False, "actual_physical_io": False, "source_mapped_authenticated": 0,
        "phase_a": "BLOCKED", "direct_handoff": False, "forced_raw_bypass": False,
        "import_active": False, "completed_steps": [],
    }
    try:
        if len({baseline, linux, out, module, evidence, prior}) != 6 or any(
                a.is_relative_to(b) for a in (out, module, evidence) for b in (baseline, linux, prior)):
            raise ValueError("path-alias")
        if out.exists() or module.exists():
            raise ValueError("output-not-pristine")
        stager = load_stager(baseline)
        stager.require(stager.LINUX == LINUX and
                       stager.R092_OVERLAY_PIN == "62db468c14f23b59e7adaae65a11dcb9969f02b3",
                       "inherited-stage-contract")
        stager.BASELINE = FREEZE
        stager.PRODUCT = {**stager.PRODUCT, **VALUE_PINS}
        stager.EXTRA_MODULE = (*stager.EXTRA_MODULE, "zswap-original-storage-value.o",
                               WITNESS.replace(".c", ".o"))
        stager.PRODUCT_OBJECTS = (*stager.PRODUCT_OBJECTS, "zswap-original-storage-value.o")
        state["product_pins"] = stager.PRODUCT
        state["patches"] = {**stager.PATCHES, stager.R092_OVERLAY: stager.R092_OVERLAY_PIN}
        stager.stage(state, evidence, baseline, linux, module)
        state["phase"] = "fixture-stage"
        source_root = Path(__file__).resolve().parents[2]
        stager.require(stager.git(source_root, "rev-parse", "HEAD").decode().strip() == args.source_sha,
                       "source-checkout-pin")
        fixture_bytes = stager.pin(source_root / FIXTURE, FIXTURE_PIN)
        (module / WITNESS).write_bytes(fixture_bytes)
        stager.pin(module / WITNESS, FIXTURE_PIN)
        state["module_inputs"][WITNESS] = stager.image(module / WITNESS)
        stager.write_json(evidence / "stage-manifest.json", state)
        compile_composite(stager, state, evidence, linux, out, module, prior)
        state["status"] = "SUCCESS"
        state["phase"] = "complete"
        print("R094_NATIVE_COMPOSITE_PASS actual_raw_r092=YES real_value_decoder=YES full_kernel=NO modpost=NO final_ko=NO NO_BOOT AUTH0", flush=True)
        return 0
    except Exception as error:
        # Preserve the original stage diagnostic; never retry the build.
        state["status"] = "FAILURE"
        state["first_error"] = str(error)[:450]
        print("R094_FIRST_ERROR phase=" + state["phase"] + " " + state["first_error"],
              file=sys.stderr, flush=True)
        return 2
    finally:
        (evidence / "results.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    sys.exit(main())
