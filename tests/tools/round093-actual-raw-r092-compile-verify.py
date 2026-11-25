#!/usr/bin/env python3
"""One x86_64 compile/link-only attempt on the actual raw R092 module boundary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASELINE = "78f630c9d0a2d5bfb626f2dbdef172f6024cf5ea"
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PATCHES = {
    "tests/tools/round089-original-mm-carrier.patch": "059d1bf29cf4990e22a2f608d5d552abeec3a8d1",
    "tests/tools/round090-original-mm-lifetime.patch": "337f7ff29e72d955251de0c54a9349f20c2586ec",
    "tests/tools/round091-original-mm-eviction.patch": "94bb74549c54a614406b71f28a9e8e8c22527d6a",
    "tests/tools/round088-original-dm-selected-clone.patch": "5c8587c3d8205fc1ab346011c092601f2113a45a"
}
PATCH_STAGES = {
    "tests/tools/round089-original-mm-carrier.patch": {
        "mm/zswap.c": "8bf7e885376c5ef521adf40b1ec736e062067bff",
        "include/linux/swap_ops.h": "a39a1921daf6f272e9812eb63b1aa64fec96c57f",
        "include/linux/blk_types.h": "0bf866c1571fe6b4d2e49d01b1b2c87fcf2cf04c",
        "include/linux/bio.h": "f4c5f1730514cf1816ffd5e9787562439dfae236",
        "block/bio.c": "3ba0e12a96ba3235eb909e3b3dd0be44657c6f6e",
        "mm/page_io.c": "0b0fe917fa3af5deaef8263274edffbf1a62eedb",
        "include/linux/swapz_mm_carrier.h": "72100483b42a59db8f522d3f2f4ee10d4f856550"
    },
    "tests/tools/round090-original-mm-lifetime.patch": {
        "mm/zswap.c": "cbf160877e8d8b584d6010c009a3e500f8b99f38",
        "include/linux/blk_types.h": "50c94617b08e581021ba25fa6e182a5b88ecfa43",
        "include/linux/bio.h": "4079365b37690164f85ba962a0bd0918c85899cb",
        "block/bio.c": "38f24ee2e414107be390d3a01c6b907e06a9dca7",
        "mm/page_io.c": "c3bd481117dbd29edd821df452f74990d6d5f00a",
        "include/linux/swapz_mm_carrier.h": "f170d2c2ac63679adb0885f746585ed77c2746a5"
    },
    "tests/tools/round091-original-mm-eviction.patch": {
        "mm/zswap.c": "a9a0201c29f177a37ec95a652e79e4ea2008167a",
        "include/linux/swapz_mm_carrier.h": "a516cab0813a5ecb70054bf488d536b05dcd4c52"
    },
    "tests/tools/round088-original-dm-selected-clone.patch": {
        "drivers/md/dm.c": "e51af0d14465e92323970a84c1d62df3a8eb61c3"
    }
}
IMAGES = {
    "mm/zswap.c": [
        "ae19e301fced7e357a4c7587dfdd6abb890b9163",
        "a9a0201c29f177a37ec95a652e79e4ea2008167a"
    ],
    "include/linux/swap_ops.h": [
        "57ac6c703f685883d3a15ebc1a5c7f6c298deb1b",
        "a39a1921daf6f272e9812eb63b1aa64fec96c57f"
    ],
    "include/linux/blk_types.h": [
        "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
        "50c94617b08e581021ba25fa6e182a5b88ecfa43"
    ],
    "include/linux/bio.h": [
        "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
        "4079365b37690164f85ba962a0bd0918c85899cb"
    ],
    "block/bio.c": [
        "b0fcc69de653524479e3b328aa29a37e97945b84",
        "38f24ee2e414107be390d3a01c6b907e06a9dca7"
    ],
    "mm/page_io.c": [
        "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
        "c3bd481117dbd29edd821df452f74990d6d5f00a"
    ],
    "drivers/md/dm.c": [
        "1881d86111fb2e655893ad898cf21b88f0e4e7f3",
        "e51af0d14465e92323970a84c1d62df3a8eb61c3"
    ],
    "include/linux/swapz_mm_carrier.h": [
        None,
        "a516cab0813a5ecb70054bf488d536b05dcd4c52"
    ]
}
GLUE_PREIMAGES = {
    "mm/Makefile": "2a3ec53d62eef629486b87736d560b1fa1798096",
    "mm/Kconfig": "afff1b25b5438756f15e464f63dabdbd5ec6102c",
}
PRODUCT = {
    "Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "VERSION": "ce022e35e5c13bea0de8a9fae9c9d6f3f0dad904",
    "authority.c": "14fe52cf4cf28f18568d3bf2b6ced449c9c182a3",
    "authority.h": "c63741157141b2aa9a15de1e9182e27435fc0a3e",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "dm-target.c": "420751247bdfd0be9c7271b180ee5cfcc7ca5d92",
    "engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
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
    "zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "zswap-original-decoder-handles.c": "c01c056fdd7f9f8aa68c7083a9e4e3ca2cdc8d6d",
    "zswap-original-decoder-handles.h": "0f103783aee10d18df5c502fdf553f7ac6a0035d",
    "zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "zswap-original-storage.c": "1f9030030f5d0fb3b06d0b0a159dd8aa6818f8dd",
    "zswap-original-storage.h": "38924c3931419a93a7783de9ba622024a5e2e65c",
    "zswap-original-ticket.c": "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
    "zswap-original-ticket.h": "0630f9e4fad26458ed0778ca6ae040150e28f078"
}
GUARDS = ("-DSWAPZ_ORIGINAL_TICKET_TEST -DSWAPZ_ROUND088_SELECTED_DM_CANDIDATE_TEST "
          "-DSWAPZ_ROUND089_ORIGINAL_DM_CORE_TEST -DSWAPZ_ROUND090_SELECTED_DM_COMPOSITION_TEST "
          "-DSWAPZ_ORIGINAL_EXTENT_TEST "
          "-DSWAPZ_ORIGINAL_STORAGE_TEST -DSWAPZ_SHARED_ORIGINAL_TEST "
          "-DSWAPZ_ROUND066_IMPORT_DISK_TEST -DSWAPZ_ROUND067_IMPORT_DISK_PAYLOAD_TEST -Werror")
BVECPIN = "b63914ff56e33df302055fabf2a84ba490bc8d2c"
R092_OVERLAY = "tests/tools/round092-original-module-boundary.patch"
R092_OVERLAY_PIN = "62db468c14f23b59e7adaae65a11dcb9969f02b3"
R092_IMAGES = {
    "mm/zswap.c": [
        "a9a0201c29f177a37ec95a652e79e4ea2008167a",
        "98a8a6a66858204b61875ad9b2e8cfb0ecf8980a"
    ],
    "include/linux/swapz_mm_carrier.h": [
        "a516cab0813a5ecb70054bf488d536b05dcd4c52",
        "da1e7a367f4f5d16dc6854f33064631251acb153"
    ],
    "src/kernel/zswap-original-ticket.c": [
        "7ba56c5ee602853c8d0717f23aad9efc69d111ea",
        "634b38e52b3b1e6493d6b10a694065ccc4b698ad"
    ],
    "src/kernel/zswap-original-ticket.h": [
        "0630f9e4fad26458ed0778ca6ae040150e28f078",
        "6afac83a0655e532ce1ef9b8f290a367e8aabfce"
    ]
}
BROKER_INPUTS = ("zswap-original-ticket.c", "zswap-original-ticket.h")

def final_raw_pin(path):
    return R092_IMAGES[path][1] if path in R092_IMAGES else IMAGES[path][1]


def final_product_pin(name):
    path = "src/kernel/" + name
    return R092_IMAGES[path][1] if path in R092_IMAGES else PRODUCT[name]


MODULE_BOUNDARY = [
    "swapz_mm_candidate_get",
    "swapz_mm_register_provider",
    "swapz_mm_unregister_provider",
    "swapz_ticket_put",
    "swapz_ticket_view",
    "swapz_ticket_broker_put",
    "swapz_ticket_broker_try_get",
    "swapz_ticket_claim_under_queue_lock",
    "dm_swapz_round088_clone_matches",
    "dm_swapz_round090_route_live",
    "dm_swapz_round090_selected_origin",
    "dm_swapz_round091_accepted_clone_matches"
]
EXTRA_MODULE = ("zswap-original-extent.o", "zswap-original-storage.o",
                "zswap-original-decode.o", "zswap-import-decoder-owner.o",
                "zswap-original-decoder-bridge.o", "zswap-original-decoder-handles.o")
PRODUCT_OBJECTS = ("dm-target.o", "authority.o", "engine.o", "codec.o", *EXTRA_MODULE)
GLUE_DIR = "mm/round093-swapz"
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
# Round093 isolated compile-only link of immutable broker and codec.
ccflags-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += -I$(srctree)/mm/round093-swapz
obj-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += round093-swapz/
"""
OBJECTS = ("mm/zswap.o", "mm/page_io.o", "block/bio.o", "drivers/md/dm.o",
           GLUE_DIR + "/zswap-original-ticket.o", GLUE_DIR + "/codec.o")
REQUIRED = ("64BIT", "X86_64", "MMU", "BLOCK", "SWAP", "ZSWAP", "MD",
            "BLK_DEV_DM", "MODULES", "CRYPTO_LZO", "CRYPTO_LZ4",
            "CRYPTO_SHA256", "CRYPTO_LIB_SHA256", "CRYPTO_CRC32C",
            "LZ4_COMPRESS", "LZ4_DECOMPRESS", "LZO_DECOMPRESS", "CRC32",
            "SWAPZ_ORIGINAL_MM_CARRIER_TEST")


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
            return re.sub(r"/(?:[^/\s:]+/)+(linux|swapz|round093-product-module|round093-x86-build)/", r"\1/", line)[:400]
    return (lines[-1][:400] if lines else "no child diagnostic") + f" (exit={returncode})"


def step(state, evidence, name, argv, cwd=None, timeout=60):
    state["phase"] = name
    log = evidence / (name + ".log")
    print("R093_BEGIN " + name, flush=True)
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
    print("R093_PASS " + name, flush=True)


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
    header = pin(linux / "include/linux/bvec.h", BVECPIN)
    require(b"unsigned int\t\tbi_offset;" in header and b"bi_bvec_done" not in header,
            "pinned-bvec-api")
    source = baseline / "src/kernel"
    require({p.name for p in source.iterdir()} == set(PRODUCT), "product-source-census")
    for name, expected in PRODUCT.items():
        pin(source / name, expected)
    require(not (linux / GLUE_DIR).exists(), "unexpected-glue-directory")
    require(not module.exists(), "module-stage-exists")
    state["completed_steps"].append("pin-preflight")
    # The MM patch has zero-context hunks. --unidiff-zero is needed to parse
    # that format; full pristine and predicted postimage hashes fence it.
    # Corrected DM patch packaging is frozen. No normalization,
    # --ignore-whitespace or --whitespace=fix.
    apply = ["git", "apply", "--index", "--unidiff-zero", "--whitespace=error"]
    state["ordered_patch_stages"] = {}
    for index, path in enumerate(PATCHES, 1):
        name = f"raw-patch-{index}"
        patch = [str(baseline / path)]
        step(state, evidence, name + "-check", apply + ["--check"] + patch, linux)
        require(not git(linux, "diff", "--name-only"), "apply-check-mutated-source")
        step(state, evidence, name + "-apply", apply + patch, linux)
        for changed, expected in PATCH_STAGES[path].items():
            pin(linux / changed, expected)
        state["ordered_patch_stages"][path] = {
            changed: image(linux / changed) for changed in PATCH_STAGES[path]}
    state["phase"] = "postimage-check"
    actual = set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
    require(actual == set(IMAGES), "patched-path-census")
    for path, (_, after) in IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-postimage-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["r091_postimages"] = {path: image(linux / path) for path in IMAGES}
    # The actual R092 patch spans Linux and product broker files. Stage the
    # exact unmodified broker inputs in the same scratch index first.
    state["phase"] = "raw-r092-preimages"
    broker_root = linux / "src/kernel"
    require(not broker_root.exists(), "unexpected-staged-broker-directory")
    broker_root.mkdir(parents=True)
    broker_paths = ["src/kernel/" + name for name in BROKER_INPUTS]
    for name in BROKER_INPUTS:
        shutil.copyfile(source / name, broker_root / name)
    git(linux, "add", "--", *broker_paths)
    pin(baseline / R092_OVERLAY, R092_OVERLAY_PIN)
    for path, (before, _) in R092_IMAGES.items():
        pin(linux / path, before)
    state["r092_preimages"] = {path: image(linux / path) for path in R092_IMAGES}
    patch = [str(baseline / R092_OVERLAY)]
    step(state, evidence, "raw-r092-overlay-check", apply + ["--check"] + patch, linux)
    require(not git(linux, "diff", "--name-only"), "r092-check-mutated-source")
    step(state, evidence, "raw-r092-overlay-apply", apply + patch, linux)
    for path, (_, after) in R092_IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-r092-overlay-reverse-check",
         apply + ["--reverse", "--check"] + patch, linux)
    raw_paths = set(IMAGES) | set(broker_paths)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths, "r092-raw-path-census")
    require(not git(linux, "diff", "--name-only"), "r092-unstaged-changes")
    step(state, evidence, "raw-r092-overlay-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["r092_postimages"] = {path: image(linux / path) for path in R092_IMAGES}
    state["raw_patches_applied"] = True
    state["actual_raw_r092_overlay"] = True
    state["patch_postimages"] = {path: image(linux / path) for path in sorted(raw_paths)}
    write_json(evidence / "raw-stage-manifest.json", state)

    # Frozen R091 DM uses pinned bi_offset; no obsolete overlay.
    require(b"bi_bvec_done" not in (linux / "drivers/md/dm.c").read_bytes(),
            "unexpected-obsolete-core-bvec-api")
    # Exclusively scratch Kbuild additions; the real overlay is already staged.
    # Both built-in owner and external consumer must see the patched header.
    state["phase"] = "scratch-kbuild"
    glue = linux / GLUE_DIR
    glue.mkdir()
    for name in MM_INPUTS:
        input_path = broker_root / name if name in BROKER_INPUTS else source / name
        shutil.copyfile(input_path, glue / name)
        pin(glue / name, final_product_pin(name))
    (glue / "Makefile").write_text("obj-y += zswap-original-ticket.o codec.o\n")
    for path, text in (("mm/Kconfig", KCONFIG), ("mm/Makefile", MAKEFILE)):
        with (linux / path).open("ab") as output:
            output.write(text.encode())
    additions = list(GLUE_PREIMAGES) + [GLUE_DIR + "/" + name for name in
                                       (*MM_INPUTS, "Makefile")]
    git(linux, "add", "--", *additions, "mm/zswap.c")
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths | set(additions), "scratch-path-census")
    require(not git(linux, "diff", "--name-only"), "unstaged-linux-changes")
    step(state, evidence, "scratch-source-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    for path in raw_paths:
        pin(linux / path, final_raw_pin(path))
    module.mkdir()
    for name in PRODUCT:
        input_path = broker_root / name if name in BROKER_INPUTS else source / name
        shutil.copyfile(input_path, module / name)
        pin(module / name, final_product_pin(name))
    require((module / "zswap-original-ticket.h").read_bytes() ==
            (glue / "zswap-original-ticket.h").read_bytes(), "broker-header-mismatch")
    require(b"bi_bvec_done" not in (module / "dm-target.c").read_bytes(),
            "unexpected-obsolete-target-bvec-api")
    # No product namespace overlay: frozen R091 carries the actual fix.
    # Only this isolated module Makefile is extended, retaining real original
    # product Makefile flags and exact components (including SIMD dispatch).
    makefile = module / "Makefile"
    text = makefile.read_text()
    anchor = "dm-swapz-y := dm-target.o codec.o authority.o engine.o predictor.o\n"
    require(text.count(anchor) == 1, "module-kbuild-anchor")
    state["module_makefile_raw"] = image(makefile)
    makefile.write_text(text.replace(anchor, anchor + "dm-swapz-y += " +
                                     " ".join(EXTRA_MODULE) + "\n" +
                                     "ccflags-y += -I$(src)\n", 1))
    state["module_makefile_compatible"] = image(makefile)
    version = (module / "VERSION").read_text().strip()
    require(re.fullmatch(r"3\.0\.0-alpha\.[0-9]+", version), "product-version")
    (module / "swapz-version.h").write_text(f'#define SWAPZ_ALPHA_VERSION "{version}"\n')
    state["scratch_postimages"] = {path: image(linux / path) for path in additions}
    state["module_inputs"] = {p.name: image(p) for p in module.iterdir()}
    state["completed_steps"].append("scratch-kbuild")
    write_json(evidence / "stage-manifest.json", state)


def build(state, evidence, linux, out, module):
    state["phase"] = "toolchain"
    for name in ("gcc", "make", "ld", "nm", "ar", "objcopy", "objdump",
                 "readelf", "bc", "bison", "flex", "perl", "pkg-config", "openssl",
                 "python3", "awk", "sed", "sort", "grep", "xz", "cpio"):
        require(shutil.which(name), "missing-build-tool:" + name)
    state["compiler"] = subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0]
    state["linker"] = subprocess.check_output(["ld", "--version"], text=True).splitlines()[0]
    # Actual compile and link, not merely package presence. Execute only the
    # harmless userspace probe on its own executable, never kernel/module.
    step(state, evidence, "libelf-pkg-config", ["pkg-config", "--exists", "libelf"])
    probe = evidence / "elf-prerequisite.c"
    executable = evidence.parent / "round093-elf-prerequisite"
    require(not executable.exists(), "elf-probe-output-exists")
    probe.write_text(
        "#include <fcntl.h>\n#include <unistd.h>\n#include <gelf.h>\n#include <libelf.h>\n"
        "int main(int argc, char **argv) {\n"
        "  if (argc != 2 || elf_version(EV_CURRENT) == EV_NONE) return 1;\n"
        "  int fd = open(argv[1], O_RDONLY); if (fd < 0) return 2;\n"
        "  Elf *elf = elf_begin(fd, ELF_C_READ, 0); GElf_Ehdr header;\n"
        "  int ok = elf && gelf_getehdr(elf, &header) && header.e_machine == EM_X86_64;\n"
        "  if (elf) elf_end(elf);\n  close(fd);\n  return ok ? 0 : 3;\n}\n")
    step(state, evidence, "elf-header-link", ["gcc", "-std=c17", "-Wall", "-Wextra",
         "-Werror", str(probe), "-lelf", "-o", str(executable)])
    step(state, evidence, "elf-probe-execute", [str(executable), str(executable)])
    state["elf_prerequisite"] = "PASS"
    executable.unlink()
    step(state, evidence, "openssl-prerequisite", ["pkg-config", "--exists", "openssl"])
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
         make + ["-j2", "M=" + str(module), *PRODUCT_OBJECTS], timeout=1200)
    state["product_objects"] = {path: image(module / path) for path in PRODUCT_OBJECTS}
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
                "swapz_ticket_retain", "swapz_crc32c_bytes", "swapz_ticket_claim_under_queue_lock",
                "swapz_ticket_broker_try_get", "swapz_ticket_broker_put",
                "swapz_mm_register_provider", "swapz_mm_unregister_provider",
                "dm_swapz_round090_selected_origin", "dm_swapz_round090_route_live",
                "dm_swapz_round091_accepted_clone_matches", "swapz_ticket_view"}
    require(required <= defined, "missing-kernel-symbols:" + ",".join(sorted(required - defined)))
    unresolved = subprocess.check_output(["nm", "-u", str(kernel)], text=True)
    (evidence / "kernel-undefined.txt").write_text(unresolved)
    require(not any(line.split()[:1] == ["U"] for line in unresolved.splitlines()),
            "unresolved-strong-kernel-symbol")
    # Record exports separately; no fake exports or duplicated broker owner.
    exports = {line.split()[1] for line in symvers.read_text().splitlines()
               if len(line.split()) >= 2}
    state["required_kernel_exports_present"] = sorted(required & exports)
    state["required_kernel_exports_absent"] = sorted(required - exports)
    export_rows = {fields[1]: fields for line in symvers.read_text().splitlines()
                   if len(fields := line.split()) >= 4}
    state["boundary_export_rows"] = {s: export_rows.get(s) for s in MODULE_BOUNDARY}
    require(all(s in export_rows and export_rows[s][2] == "vmlinux" and
                export_rows[s][3] == "EXPORT_SYMBOL_GPL" for s in MODULE_BOUNDARY),
            "missing-or-wrong-guarded-gpl-boundary")
    require(not ((required - set(MODULE_BOUNDARY)) & exports), "forbidden-internal-export")
    state["kernel_symbols"] = sorted(required)
    state["full_kernel_link"] = True
    state["kernel_sha256"] = digest(kernel.read_bytes())
    state["module_symvers_sha256"] = digest(symvers.read_bytes())
    state["completed_steps"].append("kernel-symbol-check")
    # Retain bounded binary artifacts before the module attempt; never execute/load.
    if kernel.stat().st_size <= 48 * 1024 * 1024:
        shutil.copyfile(kernel, evidence / "vmlinux")
        state["kernel_binary_retained"] = True
    shutil.copyfile(symvers, evidence / "kernel-Module.symvers")

    def record_composite():
        composite = module / "dm-swapz.o"
        if composite.is_file():
            state["composite"] = image(composite)
            (evidence / "composite-undefined.txt").write_text(
                subprocess.check_output(["nm", "-u", str(composite)], text=True))

    try:
        step(state, evidence, "product-module-link", make + ["-j2", "M=" + str(module), "modules"],
             timeout=900)
    except Failure:
        try:
            record_composite()
        except (OSError, subprocess.SubprocessError):
            state["composite_diagnostic_collection"] = "FAILED"
        raise
    record_composite()
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
    module_symbols = subprocess.check_output(["nm", "-g", "--defined-only", str(ko)], text=True)
    module_defined = {line.split()[-1] for line in module_symbols.splitlines() if line.split()}
    required_module = {"swapz_original_extent_begin", "swapz_original_storage_write",
                       "swapz_shared_storage_write", "swapz_original_decode",
                       "swapz_zswap_import_decoder_owner_get", "swapz_original_decoder_bridge_init",
                       "swapz_original_decoder_bridge_read", "swapz_shared_storage_reserve",
                       "swapz_shared_storage_commit_reserved"}
    require(required_module <= module_defined,
            "missing-module-symbols:" + ",".join(sorted(required_module - module_defined)))
    required_module.update({"swapz_original_decoder_handles_init", "swapz_original_decoder_handle_get",
                            "swapz_original_decoder_handle_put", "swapz_original_decoder_handle_read",
                            "swapz_original_decoder_handles_close"})
    require(required_module <= module_defined,
            "missing-module-value-handle-symbols:" + ",".join(sorted(required_module - module_defined)))
    require(not (set(["swapz_ticket_put","swapz_ticket_view","swapz_ticket_broker_put","swapz_ticket_broker_try_get","swapz_ticket_claim_under_queue_lock"]) & module_defined),
            "duplicate-module-broker-owner")
    boundary_imports = {s for s in strong if s.startswith(("swapz_mm_", "swapz_ticket_", "dm_swapz_"))}
    require(boundary_imports <= set(MODULE_BOUNDARY), "unreviewed-boundary-import")
    state["actual_boundary_imports"] = sorted(boundary_imports)
    state["module_symbols"] = sorted(required_module)
    state["module_imports"] = sorted(strong)
    state["product_module_sha256"] = digest(ko.read_bytes())
    require(ko.stat().st_size <= 16 * 1024 * 1024, "module-binary-size-budget")
    shutil.copyfile(ko, evidence / "dm-swapz.ko")
    state["module_binary_retained"] = True
    state["product_module_link"] = True
    state["completed_steps"].append("module-symbol-check")
    # Recheck source pins after compiler/link; no patch edits or peer outputs.
    for path in set(IMAGES) | set(R092_IMAGES):
        pin(linux / path, final_raw_pin(path))
    for name, expected in PRODUCT.items():
        if name == "Makefile":
            require(image(module / name) == state["module_makefile_compatible"],
                    "module-kbuild-drift")
        else:
            pin(module / name, final_product_pin(name))
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
        "raw_patches_applied": False, "actual_raw_r092_overlay": False,
        "r092_overlay_pin": R092_OVERLAY_PIN, "old_scratch_exports": False,
        "elf_prerequisite": "NOT_RUN", "build_attempts": 0,
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
        print("R093_COMPILE_LINK_PASS actual_raw_r092_overlay=YES old_scratch_exports=NO full_kernel=YES product_module=YES NO_BOOT AUTH0", flush=True)
        return 0
    except (Failure, OSError, ValueError, subprocess.SubprocessError) as error:
        state["status"] = "FAILURE"
        state["first_error"] = str(error)[:450]
        print("R093_FIRST_ERROR phase=" + state["phase"] + " " + state["first_error"],
              file=sys.stderr, flush=True)
        return 2
    finally:
        write_json(evidence / "results.json", state)


if __name__ == "__main__":
    sys.exit(main())
