#!/usr/bin/env python3
"""One x86_64 compile/link-only attempt on immutable R088 MM + DM sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASELINE = "db9252db73721a768be912965ad4402e332039e8"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PATCHES = {
    "tests/tools/round088-original-mm-carrier.patch": "b9a10044c7cd750d908730b5a95a4e945883ec45",
    "tests/tools/round088-original-dm-selected-clone.patch": "e465dacabfb12fc93382143308e7ba1a188f59e6",
}
# Independently calculated from the exact original and raw hunk bytes.
IMAGES = {
    "mm/zswap.c": ("ae19e301fced7e357a4c7587dfdd6abb890b9163", "e3caa72ca37a7a3cdb3ed51639d9507b22fe4e51"),
    "include/linux/swap_ops.h": ("57ac6c703f685883d3a15ebc1a5c7f6c298deb1b", "a39a1921daf6f272e9812eb63b1aa64fec96c57f"),
    "include/linux/blk_types.h": ("0cc09b975d8ffbd45ca3dc47533a71f8e8164de6", "0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c"),
    "include/linux/bio.h": ("7a794ce723b84b2a148f8f9beccf057b266e8ac9", "f4c5f1730514cf1816ffd5e9787562439dfae236"),
    "block/bio.c": ("b0fcc69de653524479e3b328aa29a37e97945b84", "3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e"),
    "mm/page_io.c": ("c6824fcd483e0aa2c412e14dae0d2a356b17c373", "0b0fe917fa3af5deaef8263274edffbf1a62eedb"),
    "include/linux/swapz_mm_carrier.h": (None, "7ac3fe204983aa7ba5a291aa756d37e235f8508f"),
    "drivers/md/dm.c": ("1881d86111fb2e655893ad898cf21b88f0e4e7f3", "59ff578305062e9a63f900a661c6ce0cf3d8a9eb"),
}
GLUE_PREIMAGES = {
    "mm/Makefile": "2a3ec53d62eef629486b87736d560b1fa1798096",
    "mm/Kconfig": "afff1b25b5438756f15e464f63dabdbd5ec6102c",
}
PRODUCT = {
    "Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "VERSION": "ce022e35e5c13bea0de8a9fae9c9d6f3f0dad904",
    "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "dm-target.c": "cb0b20aa3a52a0a136e2a84e87b838d75a462e28",
    "engine.c": "20e91329fc1a1b713cb6638236c001e7d5e3f815",
    "engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "flush-qual.h": "095d3ef7665ba268f28c2235fbb1c8e26cb8b7d1",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "gc-recovery-policy.h": "26cddb997ad9f4b5b15616eba7cc0e26aaeb58eb",
    "lane-gap.h": "e97870b218c7c9b338b43323fff77181be877649",
    "predictor-avx2.c": "0fa5746f187b2fa017782448e052f7a2c39bfc8f",
    "predictor-avx512.c": "a9892552f516ec47157c4aacdd4f3aca994192b2",
    "predictor-internal.h": "6b49267dac50d92e58a950ca80541d2928de6d23",
    "predictor-neon.c": "98554e4c601ee542973bc680a7549c6ad45f073e",
    "predictor-route.h": "ea14590608d7a92b4fb379aca26864467e158bac",
    "predictor-shuffle.h": "d0ebd77af875c6d34757eb9b14080934af32b08a",
    "predictor-sse2.c": "0993632a2e5f6ff7fe66cd828e7cd88ff8c577d6",
    "predictor.c": "b1ce85ef0fb6a20d720dfba562d3a9a3588f127c",
    "predictor.h": "54cce4ad8bcb63ee724001fff4831948ec8e8de5",
    "preparation-slots.h": "aaa6a0420bda460dbcc42072d74f57bab9fcbbfd",
    "superblock.h": "ba73845837b4c604b01d72f50f05ae8d4378eddd",
    "swapz-build-info.h": "51ce0bc3a5947bb6ff660e4e5bb63aa5477cb226",
    "window-policy.h": "cb14486a3ef4324761cde8c54b22c5f0e5d89494",
    "zswap-direct-handoff.h": "864abf9a12071b98f5c157a44f4ed0c04d4a594c",
    "zswap-import-admission.h": "a411da35437cbf9a43c88083d830dc9280f108e8",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
    "zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "zswap-original-decode.c": "eb1cd7f90d5edade9640e1ffe9dac3c8fe774644",
    "zswap-original-decode.h": "a247d1aaf9865de71f97cd980be806b8d8c7c20e",
    "zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "zswap-original-storage.c": "50b0b1cf92a3294b6ecba8374069c2ddf9a44ef3",
    "zswap-original-storage.h": "90537c12e39f45ded5f0411d471fcc716b4981dc",
    "zswap-original-ticket.c": "dcea7cbc40094fed2997d6704c712ac47aa164a1",
    "zswap-original-ticket.h": "b772cc28755a68719f4dcdabefeefe57b5efea67",
}
GUARDS = "-DSWAPZ_ORIGINAL_TICKET_TEST -DSWAPZ_ROUND088_SELECTED_DM_CANDIDATE_TEST -Werror"
GLUE_DIR = "mm/round089-swapz"
MM_INPUTS = ("codec.c", "codec.h", "zswap-original-ticket.c", "zswap-original-ticket.h")
KCONFIG = """
# Isolated compile-only staging; never shipped or booted.
config SWAPZ_ORIGINAL_MM_CARRIER_TEST
	bool "Compile-only frozen swapz MM carrier"
	depends on ZSWAP && BLK_DEV_DM
	select CRYPTO_SHA256
	default n
"""
MAKEFILE = """
# Round089 isolated compile-only link of immutable broker and codec.
ccflags-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += -I$(srctree)/mm/round089-swapz
obj-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += round089-swapz/
"""
OBJECTS = ("mm/zswap.o", "mm/page_io.o", "block/bio.o", "drivers/md/dm.o",
           GLUE_DIR + "/zswap-original-ticket.o", GLUE_DIR + "/codec.o")
REQUIRED = ("64BIT", "X86_64", "MMU", "BLOCK", "SWAP", "ZSWAP", "MD",
            "BLK_DEV_DM", "MODULES", "CRYPTO_LZO", "CRYPTO_LZ4",
            "CRYPTO_SHA256", "CRYPTO_LIB_SHA256", "CRYPTO_CRC32C",
            "LZ4_COMPRESS", "LZ4_DECOMPRESS", "SWAPZ_ORIGINAL_MM_CARRIER_TEST")


class Failure(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Failure(reason)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def pin(path, expected):
    require(path.is_file() and not path.is_symlink(), "missing-or-symlink:" + path.name)
    data = path.read_bytes()
    require(blob(data) == expected, "blob-mismatch:" + path.name)
    return data


def image(path):
    data = path.read_bytes()
    return {"blob": blob(data), "sha256": digest(data), "bytes": len(data)}


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def diagnostic(log, returncode):
    # Prefer first real compiler/link error, not a secondary make summary.
    lines = log.read_text(errors="replace").splitlines()
    for line in lines:
        if re.search(r"fatal error:|error:|undefined reference|undefined symbol|"
                     r"ERROR: modpost|error\[|patch failed:|patch does not apply|"
                     r"not found|No such file|unrecognized option", line, re.I):
            return line[:400]
    return (lines[-1][:400] if lines else "no child diagnostic") + f" (exit={returncode})"


def step(state, evidence, name, argv, cwd=None, timeout=60):
    state["phase"] = name
    log = evidence / (name + ".log")
    print("R089_BEGIN " + name, flush=True)
    try:
        with log.open("wb") as output:
            result = subprocess.run(argv, cwd=cwd, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise Failure(f"{name}: timeout after {error.timeout}s") from error
    except OSError as error:
        raise Failure(f"{name}: {error.strerror}") from error
    if result.returncode:
        state["child_exit"] = result.returncode
        raise Failure(name + ": " + diagnostic(log, result.returncode))
    state["completed_steps"].append(name)
    print("R089_PASS " + name, flush=True)


def stage(state, evidence, baseline, linux, module):
    state["phase"] = "pin-preflight"
    for root, expected in ((baseline, BASELINE), (linux, LINUX)):
        require(git(root, "rev-parse", "HEAD").decode().strip() == expected, "checkout-pin")
        require(not git(root, "status", "--porcelain", "--untracked-files=all"), "checkout-dirty")
    for path, expected in PATCHES.items():
        pin(baseline / path, expected)
    for path, (before, _) in IMAGES.items():
        if before is None:
            require(not (linux / path).exists(), "unexpected-new-header-preimage")
        else:
            pin(linux / path, before)
    for path, expected in GLUE_PREIMAGES.items():
        pin(linux / path, expected)
    source = baseline / "src/kernel"
    require({p.name for p in source.iterdir()} == set(PRODUCT), "product-source-census")
    for name, expected in PRODUCT.items():
        pin(source / name, expected)
    require(not (linux / GLUE_DIR).exists(), "unexpected-glue-directory")
    require(not module.exists(), "module-stage-exists")
    state["completed_steps"].append("pin-preflight")
    # The MM patch has zero-context hunks. --unidiff-zero is needed to parse
    # that format; full pristine and predicted postimage hashes fence it.
    # The DM patch's line70 starts with a space + tab as *context*, not an
    # added C line. No normalization, --ignore-whitespace or --whitespace=fix.
    raw = [str(baseline / path) for path in PATCHES]
    apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    step(state, evidence, "raw-apply-check", apply + ["--check"] + raw, linux)
    require(not git(linux, "status", "--porcelain", "--untracked-files=all"),
            "apply-check-mutated-source")
    step(state, evidence, "raw-apply", apply + raw, linux)
    state["phase"] = "postimage-check"
    actual = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    require(actual == set(IMAGES), "patched-path-census")
    for path, (_, after) in IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-postimage-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["raw_patches_applied"] = True
    state["patch_postimages"] = {path: image(linux / path) for path in IMAGES}
    write_json(evidence / "raw-stage-manifest.json", state)

    # These are exclusively scratch Kbuild additions; real product code is
    # copied byte-for-byte, not edited or replaced by API stubs.
    state["phase"] = "scratch-kbuild"
    glue = linux / GLUE_DIR
    glue.mkdir()
    for name in MM_INPUTS:
        shutil.copyfile(source / name, glue / name)
        pin(glue / name, PRODUCT[name])
    (glue / "Makefile").write_text("obj-y += zswap-original-ticket.o codec.o\n")
    for path, text in (("mm/Kconfig", KCONFIG), ("mm/Makefile", MAKEFILE)):
        with (linux / path).open("ab") as output:
            output.write(text.encode())
    additions = list(GLUE_PREIMAGES) + [GLUE_DIR + "/" + name for name in
                                       (*MM_INPUTS, "Makefile")]
    git(linux, "add", "--", *additions)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == set(IMAGES) | set(additions), "scratch-path-census")
    require(not git(linux, "diff", "--name-only"), "unstaged-linux-changes")
    step(state, evidence, "scratch-source-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    for path, (_, after) in IMAGES.items():
        pin(linux / path, after)
    module.mkdir()
    for name, expected in PRODUCT.items():
        shutil.copyfile(source / name, module / name)
        pin(module / name, expected)
    version = (module / "VERSION").read_text().strip()
    require(re.fullmatch(r"3\.0\.0-alpha\.[0-9]+", version), "product-version")
    (module / "swapz-version.h").write_text(f'#define SWAPZ_ALPHA_VERSION "{version}"\n')
    state["scratch_postimages"] = {path: image(linux / path) for path in additions}
    state["module_inputs"] = {p.name: image(p) for p in module.iterdir()}
    state["completed_steps"].append("scratch-kbuild")
    write_json(evidence / "stage-manifest.json", state)


def build(state, evidence, linux, out, module):
    state["phase"] = "toolchain"
    for name in ("gcc", "make", "ld", "nm", "bc", "bison", "flex", "perl"):
        require(shutil.which(name), "missing-build-tool:" + name)
    state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    state["linker"] = subprocess.check_output(["ld", "--version"], text=True).splitlines()[0]
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64",
            "CC=gcc", "KCFLAGS=" + GUARDS]
    out.mkdir()
    step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for key in REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF"):
        config += ["--disable", key]
    step(state, evidence, "set-build-config", config)
    step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    effective = (out / ".config").read_text().splitlines()
    state["phase"] = "effective-config"
    for key in REQUIRED:
        require("CONFIG_" + key + "=y" in effective, "missing-effective-config:" + key)
    for key in ("ZSWAP_DEFAULT_ON", "KUNIT"):
        require("CONFIG_" + key + "=y" not in effective, "unexpected-enabled-config:" + key)
    shutil.copyfile(out / ".config", evidence / "effective.config")
    state["config_sha256"] = digest((out / ".config").read_bytes())
    state["completed_steps"].append("effective-config")
    # Cheap directed objects before an expensive whole-kernel link. All are
    # real Kbuild invocations; do not rerun after a failed source diagnostic.
    state["build_attempts"] = 1
    step(state, evidence, "original-directed-objects",
         make + ["-j2", *OBJECTS], timeout=900)
    state["original_objects"] = {path: image(out / path) for path in OBJECTS}
    step(state, evidence, "product-directed-object",
         make + ["-j2", "M=" + str(module), "dm-target.o"], timeout=900)
    state["target_object"] = image(module / "dm-target.o")
    step(state, evidence, "full-kernel-link", make + ["-j2", "vmlinux", "modules"],
         timeout=4800)
    state["phase"] = "kernel-symbol-check"
    kernel = out / "vmlinux"
    symvers = out / "Module.symvers"
    require(kernel.is_file() and symvers.is_file(), "missing-full-link-artifact")
    symbols = subprocess.check_output(["nm", "-g", "--defined-only", str(kernel)], text=True)
    defined = {line.split()[-1] for line in symbols.splitlines() if line.split()}
    required = {"swapz_mm_candidate_get", "swapz_mm_drop", "dm_swapz_round088_clone_matches",
                "swapz_ticket_reserve", "swapz_ticket_seal", "swapz_ticket_put",
                "swapz_ticket_retain", "swapz_crc32c_bytes"}
    require(required <= defined, "missing-kernel-symbols:" + ",".join(sorted(required - defined)))
    unresolved = subprocess.check_output(["nm", "-u", str(kernel)], text=True)
    (evidence / "kernel-undefined.txt").write_text(unresolved)
    require(not any(line.split()[:1] == ["U"] for line in unresolved.splitlines()),
            "unresolved-strong-kernel-symbol")
    state["kernel_symbols"] = sorted(required)
    state["full_kernel_link"] = True
    state["kernel_sha256"] = digest(kernel.read_bytes())
    state["module_symvers_sha256"] = digest(symvers.read_bytes())
    state["completed_steps"].append("kernel-symbol-check")
    step(state, evidence, "product-module-link", make + ["-j2", "M=" + str(module), "modules"],
         timeout=900)
    state["phase"] = "module-symbol-check"
    ko = module / "dm-swapz.ko"
    require(ko.is_file(), "missing-module")
    imports = subprocess.check_output(["nm", "-u", str(ko)], text=True)
    (evidence / "module-undefined.txt").write_text(imports)
    exported = {line.split()[1] for line in symvers.read_text().splitlines()
                if len(line.split()) >= 2}
    strong = {line.split()[1] for line in imports.splitlines()
              if len(line.split()) == 2 and line.split()[0] == "U"}
    require(strong <= exported, "unresolved-module-imports:" + ",".join(sorted(strong - exported)))
    state["module_imports"] = sorted(strong)
    state["product_module_sha256"] = digest(ko.read_bytes())
    state["product_module_link"] = True
    state["completed_steps"].append("module-symbol-check")
    # Recheck source pins after compiler/link; no patch edits or peer outputs.
    for path, (_, expected) in IMAGES.items():
        pin(linux / path, expected)
    for name, expected in PRODUCT.items():
        pin(module / name, expected)
    for path, expected in state["scratch_postimages"].items():
        require(image(linux / path) == expected, "scratch-postimage-drift:" + path)
    require(digest((out / ".config").read_bytes()) == state["config_sha256"], "config-drift")
    state["completed_steps"].append("final-source-check")


def main():
    parser = argparse.ArgumentParser()
    for name in ("baseline", "linux", "out", "module", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-parent", required=True)
    args = parser.parse_args()
    baseline, linux, out, module, evidence = (
        getattr(args, name).resolve() for name in ("baseline", "linux", "out", "module", "evidence"))
    os.umask(0o077)
    evidence.mkdir(parents=True, exist_ok=True)
    state = {
        "status": "IN_PROGRESS", "phase": "preflight", "first_error": None,
        "source_sha": args.source_sha, "source_parent": args.source_parent,
        "frozen_product": BASELINE, "linux_pin": LINUX, "patches": PATCHES,
        "raw_patches_applied": False, "build_attempts": 0,
        "full_kernel_link": False, "product_module_link": False,
        "vm_boot": False, "vm_build": False, "module_loaded": False,
        "source_mapped_authenticated": 0, "phase_a": "BLOCKED",
        "direct_handoff": False, "forced_raw_bypass": False, "import_active": False,
        "completed_steps": [],
    }
    try:
        require(len({baseline, linux, out, module, evidence}) == 5, "path-alias")
        require(all(not a.is_relative_to(b) for a in (out, module, evidence)
                    for b in (baseline, linux)), "output-in-source")
        require(not out.exists() and not module.exists(), "output-not-pristine")
        stage(state, evidence, baseline, linux, module)
        build(state, evidence, linux, out, module)
        state["status"] = "SUCCESS"
        state["phase"] = "complete"
        print("R089_COMPILE_LINK_PASS full_kernel=YES product_module=YES NO_BOOT AUTH0", flush=True)
        return 0
    except (Failure, OSError, ValueError, subprocess.SubprocessError) as error:
        state["status"] = "FAILURE"
        state["first_error"] = str(error)[:450]
        print("R089_FIRST_ERROR phase=" + state["phase"] + " " + state["first_error"],
              file=sys.stderr, flush=True)
        return 2
    finally:
        write_json(evidence / "results.json", state)


if __name__ == "__main__":
    sys.exit(main())
