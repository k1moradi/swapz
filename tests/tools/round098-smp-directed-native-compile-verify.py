#!/usr/bin/env python3
"""One SMP native directed compile of frozen R097 components, never booted or linked as a final module."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

BASELINE = "5a36cabf0989dfffc75de52a6ab8cc021092ebf6"
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
    "dm-target.c": "f1922cc26caf7bfa097c1f561f8719744c3a4e75",
    "engine.c": "e7c50c3e78449157439fba9c69e5d23b1c317f4e",
    "engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "flush-qual.h": "095d3ef7665ba268f28c2235fbb1c8e26cb8b7d1",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "gc-recovery-policy.h": "26cddb997ad9f4b5b15616eba7cc0e26aaeb58eb",
    "lane-gap.h": "e97870b218c7c9b338b43323fff77181be877649",
    "native-observation-adapter.c": "f94371ff06ba8296e292ccec9e28dd230ded5bbd",
    "native-observation-adapter.h": "27f1140f4dcc510662fbb1f4519f7be4236e1b10",
    "native-observation-owner.c": "69bd5c018bf4cc502c14c1c3f1cc02c1959c1673",
    "native-observation-owner.h": "e266f0e0c2dec0d399cc863da329e44f38b0c536",
    "native-observation-recorder.c": "3a9b9040b4f87a13d31361f4467809d82fc52da3",
    "native-observation-recorder.h": "f1959c40d58854fd9e2e2264c882db9a8b8dfe62",
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
    "zswap-original-broker-owner.inc": "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
    "zswap-original-decode.c": "eb1cd7f90d5edade9640e1ffe9dac3c8fe774644",
    "zswap-original-decode.h": "a247d1aaf9865de71f97cd980be806b8d8c7c20e",
    "zswap-original-decoder-bridge.c": "9324a581e27bad62d4e2d9c90192f6ad8b96faca",
    "zswap-original-decoder-bridge.h": "507b25debe0ca7b30b57ed6a350dab4868dced51",
    "zswap-original-decoder-handles.c": "c01c056fdd7f9f8aa68c7083a9e4e3ca2cdc8d6d",
    "zswap-original-decoder-handles.h": "0f103783aee10d18df5c502fdf553f7ac6a0035d",
    "zswap-original-decoder-shared.c": "3b48a4f6f31ef9c45034db7e0509efe92583e404",
    "zswap-original-decoder-shared.h": "19bce03addcee7a2eeb0983ea360d4e2a5df0912",
    "zswap-original-extent.c": "c6c5af281a636447126e1a8b67484d954158a300",
    "zswap-original-extent.h": "34572d01fffe1b276c2d023822266eda29a2137e",
    "zswap-original-storage-shared-decoder.c": "c59cdf4d4e203a9a40d09e9048d3eba786d2e0cc",
    "zswap-original-storage-shared-decoder.h": "6b1e3dc0230740be0d5f0e038b270d4984b5277d",
    "zswap-original-storage-value.c": "8f532824e9c63a6498d71fcb1ce4c35b18130f1e",
    "zswap-original-storage-value.h": "9b6be5452ff9a7ecb20fb8e661b593c290cc8b7e",
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
R094_OVERLAY = "tests/tools/round094-original-broker-owner.patch"
R094_OVERLAY_PIN = "e33bb8451210f9e1a97eb6d9bc0423f6b13a2edd"
OWNER_INC = "zswap-original-broker-owner.inc"
R094_IMAGES = {
    "src/kernel/zswap-original-ticket.c": [
        "634b38e52b3b1e6493d6b10a694065ccc4b698ad",
        "ba5e891ef7f80bf0b3021ee6c676529cb72f1972"
    ],
    "src/kernel/zswap-original-ticket.h": [
        "6afac83a0655e532ce1ef9b8f290a367e8aabfce",
        "c7f4ff59c11ee3475e7577dcc62f7c8db5a578ea"
    ]
}
R095_CAPTURE_OFF = "tests/tools/round095-mm-capture-off.patch"
R095_CAPTURE_OFF_PIN = "fee3d20b8ef872528b1301597eb33e0e0282da52"
R095_IMAGES = {
    "mm/zswap.c": [
        "98a8a6a66858204b61875ad9b2e8cfb0ecf8980a",
        "9278abca17077bf9c0e94885eb4d46cdbd9202bd"
    ]
}
R096_RETRY = "tests/tools/round096-original-owner-retry.patch"
R096_RETRY_PIN = "6ee63e6515dd2f0337c49d1a868f39435b93119c"
R096_IMAGES = {
    "src/kernel/zswap-original-ticket.c": [
        "ba5e891ef7f80bf0b3021ee6c676529cb72f1972",
        "70109f2c2ce9f60681649bd4807382248d0a41a2"
    ],
    "src/kernel/zswap-original-broker-owner.inc": [
        "0eda8753b91d3209c55f65eb90014fd9b8c6ad7c",
        "278a93a3fd3fd260444aebc55d4a87112e56f704"
    ]
}
R097_PRODUCER = "tests/tools/round097-original-mm-producer.patch"
R097_PRODUCER_PIN = "c35b35c18cc11f9b86c0b65856dbc0cd2a0bd2c8"
R097_IMAGES = {
    "mm/zswap.c": ["9278abca17077bf9c0e94885eb4d46cdbd9202bd",
                   "128495cf9b35d37b93db1b165dc1562de94b5b89"],
    "mm/page_io.c": ["c3bd481117dbd29edd821df452f74990d6d5f00a",
                     "08c11d2f9a16a322093b305afa10ba011f67fc2b"],
    "include/linux/swapz_mm_carrier.h": ["da1e7a367f4f5d16dc6854f33064631251acb153",
                                        "7083f7acdb439022a073c22261b7541d15806e5e"]
}
RECORDER = ("native-observation-adapter.c", "native-observation-adapter.h",
            "native-observation-owner.c", "native-observation-owner.h")
OBSERVATION_GUARDS = " -DSWAPZ_NATIVE_OBSERVATION_ADAPTER -DSWAPZ_TRIAL_OBSERVATION"
OBSERVATION_WRAPPERS = {"swapz_trial_observation_" + suffix for suffix in
                        ("active", "mint", "append")}
OBSERVATION_CONTROL = {"swapz_trial_observation_" + suffix for suffix in
                       ("start", "stop", "export", "release")}
UNSELECTED = {"native-observation-recorder.c", "native-observation-recorder.h"}
OWNER_EXPORTS = {"swapz_mm_broker_owner_open",
                 "swapz_mm_broker_owner_begin_close",
                 "swapz_mm_broker_owner_finish_close"}
BROKER_INPUTS = ("zswap-original-ticket.c", "zswap-original-ticket.h")
MODULE_GUARDS = GUARDS + (" -DSWAPZ_ROUND094_TARGET_OWNER_TEST"
                         " -DSWAPZ_SHARED_STORAGE_VALUE_TEST"
                         " -DSWAPZ_ORIGINAL_DECODER_SHARED_TEST"
                         " -DSWAPZ_SHARED_STORAGE_DECODER_TEST"
                         " -DSWAPZ_ROUND096_OWNER_RETRY_TEST"
                         " -DSWAPZ_ROUND097_GATED_TARGET_TEST"
                         " -DSWAPZ_ROUND097_TARGET_OBSERVATION_TEST")

def final_raw_pin(path):
    if path in R097_IMAGES:
        return R097_IMAGES[path][1]
    if path in R096_IMAGES:
        return R096_IMAGES[path][1]
    if path in R095_IMAGES:
        return R095_IMAGES[path][1]
    if path in R094_IMAGES:
        return R094_IMAGES[path][1]
    if path == "src/kernel/" + OWNER_INC:
        return PRODUCT[OWNER_INC]
    return R092_IMAGES[path][1] if path in R092_IMAGES else IMAGES[path][1]


def final_product_pin(name):
    path = "src/kernel/" + name
    return final_raw_pin(path) if path in R092_IMAGES or path in R094_IMAGES or path in R096_IMAGES else PRODUCT[name]


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
    "dm_swapz_round091_accepted_clone_matches", *sorted(OWNER_EXPORTS)
]
EXTRA_MODULE = ("zswap-original-extent.o", "zswap-original-storage.o",
                "zswap-original-decode.o", "zswap-import-decoder-owner.o",
                "zswap-original-decoder-bridge.o", "zswap-original-decoder-handles.o",
                "zswap-original-storage-value.o", "zswap-original-decoder-shared.o",
                "zswap-original-storage-shared-decoder.o")
PRODUCT_OBJECTS = ("dm-target.o", "zswap-original-storage-shared-decoder.o",
                   "zswap-original-decoder-shared.o")
GLUE_DIR = "mm/round098-swapz"
MM_INPUTS = ("codec.c", "codec.h", *BROKER_INPUTS, OWNER_INC, *RECORDER)
KCONFIG = """
# Isolated compile-only staging; never shipped or booted.
config SWAPZ_ORIGINAL_MM_CARRIER_TEST
	bool "Compile-only frozen swapz MM carrier"
	depends on ZSWAP && BLK_DEV_DM
	select CRYPTO_SHA256
	default n
"""
MAKEFILE = """
# Round098 isolated compile-only link of immutable broker and codec.
ccflags-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += -I$(srctree)/mm/round098-swapz
obj-$(CONFIG_SWAPZ_ORIGINAL_MM_CARRIER_TEST) += round098-swapz/
"""
OBJECTS = (GLUE_DIR + "/zswap-original-ticket.o", GLUE_DIR + "/native-observation-adapter.o",
           GLUE_DIR + "/native-observation-owner.o", "mm/zswap.o", "mm/page_io.o")
REQUIRED = ("64BIT", "X86_64", "SMP", "TREE_RCU", "MMU", "BLOCK", "SWAP", "ZSWAP", "MD",
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
            return re.sub(r"/(?:[^/\s:]+/)+(linux|swapz|round098-product-module|round098-x86-build)/", r"\1/", line)[:400]
    return (lines[-1][:400] if lines else "no child diagnostic") + f" (exit={returncode})"


def step(state, evidence, name, argv, cwd=None, timeout=60):
    state["phase"] = name
    log = evidence / (name + ".log")
    print("R098_BEGIN " + name, flush=True)
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
    print("R098_PASS " + name, flush=True)


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
    # Exact second overlay against the actual R092 broker; no source repair.
    state["phase"] = "raw-r094-preimages"
    pin(baseline / R094_OVERLAY, R094_OVERLAY_PIN)
    for path, (before, _) in R094_IMAGES.items():
        pin(linux / path, before)
    state["r094_preimages"] = {path: image(linux / path) for path in R094_IMAGES}
    owner_path = "src/kernel/" + OWNER_INC
    shutil.copyfile(source / OWNER_INC, linux / owner_path)
    pin(linux / owner_path, PRODUCT[OWNER_INC])
    git(linux, "add", "--", owner_path)
    raw_paths.add(owner_path)
    patch = [str(baseline / R094_OVERLAY)]
    step(state, evidence, "raw-r094-overlay-check", apply + ["--check"] + patch, linux)
    require(not git(linux, "diff", "--name-only"), "r094-check-mutated-source")
    step(state, evidence, "raw-r094-overlay-apply", apply + patch, linux)
    for path, (_, after) in R094_IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-r094-overlay-reverse-check",
         apply + ["--reverse", "--check"] + patch, linux)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths, "r094-raw-path-census")
    require(not git(linux, "diff", "--name-only"), "r094-unstaged-changes")
    step(state, evidence, "raw-r094-overlay-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    require((broker_root / BROKER_INPUTS[0]).read_bytes().count(
        b'#include "zswap-original-broker-owner.inc"') == 1, "owner-include-census")
    state["r094_postimages"] = {path: image(linux / path) for path in (*R094_IMAGES, owner_path)}
    state["actual_raw_r094_overlay"] = True
    # Apply ONLY the qualified unconditional capture-off overlay; R094
    # changes the broker C/H, not the exact R092 MM postimage.
    state["phase"] = "raw-r095-capture-off-preimage"
    pin(baseline / R095_CAPTURE_OFF, R095_CAPTURE_OFF_PIN)
    for path, (before, _) in R095_IMAGES.items():
        pin(linux / path, before)
    state["r095_preimages"] = {path: image(linux / path) for path in R095_IMAGES}
    patch = [str(baseline / R095_CAPTURE_OFF)]
    step(state, evidence, "raw-r095-capture-off-check", apply + ["--check"] + patch, linux)
    require(not git(linux, "diff", "--name-only"), "r095-check-mutated-source")
    step(state, evidence, "raw-r095-capture-off-apply", apply + patch, linux)
    for path, (_, after) in R095_IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-r095-capture-off-reverse-check",
         apply + ["--reverse", "--check"] + patch, linux)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths, "r095-raw-path-census")
    require(not git(linux, "diff", "--name-only"), "r095-unstaged-changes")
    step(state, evidence, "raw-r095-capture-off-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["r095_postimages"] = {path: image(linux / path) for path in R095_IMAGES}
    state["actual_raw_r095_capture_off"] = True
    state["phase"] = "raw-r096-owner-retry-preimage"
    pin(baseline / R096_RETRY, R096_RETRY_PIN)
    for path, (before, _) in R096_IMAGES.items():
        pin(linux / path, before)
    state["r096_preimages"] = {path: image(linux / path) for path in R096_IMAGES}
    patch = [str(baseline / R096_RETRY)]
    step(state, evidence, "raw-r096-owner-retry-check", apply + ["--check"] + patch, linux)
    require(not git(linux, "diff", "--name-only"), "r096-check-mutated-source")
    step(state, evidence, "raw-r096-owner-retry-apply", apply + patch, linux)
    for path, (_, after) in R096_IMAGES.items():
        pin(linux / path, after)
    pin(linux / "src/kernel/zswap-original-ticket.h", R094_IMAGES["src/kernel/zswap-original-ticket.h"][1])
    step(state, evidence, "raw-r096-owner-retry-reverse-check",
         apply + ["--reverse", "--check"] + patch, linux)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths, "r096-raw-path-census")
    require(not git(linux, "diff", "--name-only"), "r096-unstaged-changes")
    step(state, evidence, "raw-r096-owner-retry-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["r096_postimages"] = {path: image(linux / path) for path in R096_IMAGES}
    state["actual_raw_r096_owner_retry"] = True
    state["phase"] = "raw-r097-producer-preimage"
    pin(baseline / R097_PRODUCER, R097_PRODUCER_PIN)
    for path, (before, _) in R097_IMAGES.items():
        pin(linux / path, before)
    state["r097_preimages"] = {path: image(linux / path) for path in R097_IMAGES}
    patch = [str(baseline / R097_PRODUCER)]
    step(state, evidence, "raw-r097-producer-check", apply + ["--check"] + patch, linux)
    require(not git(linux, "diff", "--name-only"), "r097-check-mutated-source")
    step(state, evidence, "raw-r097-producer-apply", apply + patch, linux)
    for path, (_, after) in R097_IMAGES.items():
        pin(linux / path, after)
    step(state, evidence, "raw-r097-producer-reverse-check",
         apply + ["--reverse", "--check"] + patch, linux)
    require(set(git(linux, "diff", "--cached", "--name-only").decode().splitlines())
            == raw_paths, "r097-raw-path-census")
    require(not git(linux, "diff", "--name-only"), "r097-unstaged-changes")
    step(state, evidence, "raw-r097-producer-diff-check",
         ["git", "diff", "--cached", "--check"], linux)
    state["r097_postimages"] = {path: image(linux / path) for path in R097_IMAGES}
    state["actual_raw_r097_producer"] = True
    require(b"static const struct swapz_mm_trial_scope swapz_mm_scope;" in
            (linux / "mm/zswap.c").read_bytes(), "frozen-scope-not-hard-off")
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
        input_path = broker_root / name if name in (*BROKER_INPUTS, OWNER_INC) else source / name
        shutil.copyfile(input_path, glue / name)
        pin(glue / name, final_product_pin(name))
    (glue / "Makefile").write_text(
        "obj-y += zswap-original-ticket.o codec.o native-observation-adapter.o native-observation-owner.o\n"
        "CFLAGS_native-observation-owner.o += -DSWAPZ_OBSERVATION_BUILD_SOURCE=\\\"" +
        BASELINE + "\\\"\n")
    state["observation_build_source"] = BASELINE
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
    for name in PRODUCT.keys() - UNSELECTED - set(RECORDER):
        input_path = broker_root / name if name in (*BROKER_INPUTS, OWNER_INC) else source / name
        shutil.copyfile(input_path, module / name)
        pin(module / name, final_product_pin(name))
    require("zswap-original-ticket.o" not in EXTRA_MODULE, "duplicate-broker-kbuild")
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


def prerequisites(state, evidence):
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
    executable = evidence.parent / "round098-elf-prerequisite"
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
    # OpenSSL headers and actual libcrypto link, not just pkg-config presence.
    ssl_probe = evidence / "openssl-prerequisite.c"
    ssl_probe.write_text("#include <openssl/evp.h>\n"
                         "int main(void) { return EVP_sha256() ? 0 : 1; }\n")
    ssl_executable = evidence.parent / "round098-openssl-prerequisite"
    require(not ssl_executable.exists(), "openssl-probe-output-exists")
    step(state, evidence, "openssl-header-link", ["gcc", "-std=c17", "-Wall",
         "-Wextra", "-Werror", str(ssl_probe), "-lcrypto", "-o", str(ssl_executable)])
    step(state, evidence, "openssl-probe-execute", [str(ssl_executable)])
    ssl_executable.unlink()
    state["openssl_prerequisite"] = "PASS"


def build(state, evidence, linux, out, module):
    # Actual selected carrier header includes the recorder header. All
    # participating translation units must see the same exact guarded ABI.
    native_guards = OBSERVATION_GUARDS + " -I" + str(linux / GLUE_DIR)
    make = ["make", "-C", str(linux), "O=" + str(out), "ARCH=x86_64",
            "CC=gcc", "KCFLAGS=" + GUARDS + native_guards]
    module_make = make[:-1] + ["KCFLAGS=" + MODULE_GUARDS + native_guards, "M=" + str(module)]
    state["kernel_guards"] = GUARDS + OBSERVATION_GUARDS
    state["module_guards"] = MODULE_GUARDS + OBSERVATION_GUARDS
    out.mkdir()
    step(state, evidence, "allnoconfig", make + ["allnoconfig"], timeout=120)
    config = ["bash", str(linux / "scripts/config"), "--file", str(out / ".config")]
    for key in REQUIRED:
        config += ["--enable", key]
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF"):
        config += ["--disable", key]
    config += ["--set-val", "NR_CPUS", "4", "--disable", "TINY_RCU"]
    step(state, evidence, "set-build-config", config)
    step(state, evidence, "olddefconfig", make + ["olddefconfig"], timeout=120)
    effective = (out / ".config").read_text().splitlines()
    state["phase"] = "effective-config"
    shutil.copyfile(out / ".config", evidence / "effective.config")
    for key in REQUIRED:
        require("CONFIG_" + key + "=y" in effective, "missing-effective-config:" + key)
    require("CONFIG_TINY_RCU=y" not in effective and "CONFIG_NR_CPUS=4" in effective,
            "effective-smp-rcu-config")
    state["effective_smp"] = {"SMP": True, "TREE_RCU": True, "TINY_RCU": False, "NR_CPUS": 4}
    for key in ("ZSWAP_DEFAULT_ON", "ZSWAP_SHRINKER_DEFAULT_ON", "KUNIT",
                "MODULE_SIG", "DEBUG_INFO", "DEBUG_INFO_BTF"):
        require("CONFIG_" + key + "=y" not in effective, "unexpected-enabled-config:" + key)
    shutil.copyfile(out / ".config", evidence / "effective.config")
    state["config_sha256"] = digest((out / ".config").read_bytes())
    state["completed_steps"].append("effective-config")
    # Only changed objects and the provider dependency; no full link or MODPOST.
    state["build_attempts"] = 1
    state["retained_directed_objects"] = {}

    def retain_objects(group, root, paths):
        for path in paths:
            original = root / path
            if not original.is_file():
                continue
            destination = evidence / "directed" / group / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            require(original.stat().st_size <= 16 * 1024 * 1024,
                    "directed-object-size-budget:" + path)
            shutil.copyfile(original, destination)
            state["retained_directed_objects"][group + "/" + path] = image(destination)

    def compile_group(group, root, paths, name, command, timeout):
        try:
            step(state, evidence, name, command + ["-j2", *paths], timeout=timeout)
        except Failure:
            # Preserve actual earlier outputs, without masking the first error.
            try:
                retain_objects(group, root, paths)
            except (Failure, OSError):
                state["partial_object_collection"] = "FAILED"
            raise
        retain_objects(group, root, paths)
        return {path: image(root / path) for path in paths}

    state["original_objects"] = compile_group("kernel", out, OBJECTS,
        "original-directed-objects", make, 900)
    state["product_objects"] = compile_group("module", module, PRODUCT_OBJECTS,
        "product-directed-object", module_make, 1200)
    state["phase"] = "guarded-target-symbol-check"
    target = module / "dm-target.o"
    target_imports_text = subprocess.check_output(["nm", "-u", str(target)], text=True)
    (evidence / "target-undefined.txt").write_text(target_imports_text)
    target_imports = {line.split()[-1] for line in target_imports_text.splitlines() if line.split()}
    target_defined_text = subprocess.check_output(["nm", "--defined-only", str(target)], text=True)
    (evidence / "target-defined.txt").write_text(target_defined_text)
    target_defined = {line.split()[-1] for line in target_defined_text.splitlines() if line.split()}
    guard_work = {"swapz_round094_setup_work", "swapz_round094_teardown_work"}
    gated_calls = {"swapz_shared_storage_decoder_" + suffix for suffix in ("init", "read", "close")}
    gated_calls.add("swapz_original_decoder_shared_gate_init")
    bridge_calls = {name for name in target_imports if
                    name.startswith("swapz_original_decoder_bridge_")}
    require(guard_work <= target_defined, "guarded-work-functions-not-emitted")
    require(OWNER_EXPORTS <= target_imports, "owner-apis-not-referenced-by-target")
    require(gated_calls <= target_imports, "real-gated-storage-not-referenced-by-target")
    state["guarded_target_functions"] = sorted(guard_work)
    state["guarded_target_owner_imports"] = sorted(OWNER_EXPORTS & target_imports)
    state["guarded_target_bridge_storage_imports"] = sorted(bridge_calls)
    state["guarded_target_gated_storage_imports"] = sorted(gated_calls)
    state["target_value_shared_provider_imports"] = sorted(
        s for s in target_imports if s.startswith(("swapz_shared_storage_value_",
                                                  "swapz_original_decoder_shared_",
                                                  "swapz_shared_storage_decoder_")))
    target_relocations = subprocess.check_output(["readelf", "-Wr", str(target)], text=True)
    (evidence / "target-relocations.txt").write_text(target_relocations)
    require(all(re.search(r"\b" + re.escape(symbol) + r"\b", target_relocations)
                for symbol in OWNER_EXPORTS | gated_calls), "target-required-relocation-missing")
    adapter = module / "zswap-original-storage-shared-decoder.o"
    adapter_relocations = subprocess.check_output(["readelf", "-Wr", str(adapter)], text=True)
    (evidence / "storage-adapter-relocations.txt").write_text(adapter_relocations)
    adapter_imports = subprocess.check_output(["nm", "-u", str(adapter)], text=True)
    (evidence / "storage-adapter-undefined.txt").write_text(adapter_imports)
    adapter_symbols = {line.split()[-1] for line in adapter_imports.splitlines() if line.split()}
    direct_provider = {"swapz_original_decoder_shared_" + suffix for suffix in
                       ("init", "read", "begin_close", "finish_close")}
    gate_calls = {"swapz_original_decoder_shared_gate_" + suffix for suffix in
                  ("open", "read", "begin_close", "finish_close")}
    require(gate_calls <= adapter_symbols and not (direct_provider & adapter_symbols),
            "adapter-gated-provider-imports")
    require(all(re.search(r"\b" + re.escape(symbol) + r"\b", adapter_relocations)
                for symbol in gate_calls), "adapter-gate-relocations")
    state["adapter_direct_provider_imports"] = sorted(direct_provider & adapter_symbols)
    state["adapter_gate_imports"] = sorted(gate_calls)
    require({"swapz_trial_observation_active", "swapz_trial_observation_append"} <= target_imports,
            "missing-target-observation-wrapper-imports")
    require(all(name in target_relocations for name in
                ("swapz_trial_observation_active", "swapz_trial_observation_append")),
            "missing-target-observation-wrapper-relocations")
    state["completed_steps"].append("guarded-target-symbol-check")
    state["phase"] = "native-owner-recorder-symbol-check"

    def inspect(label, path):
        undefined = subprocess.check_output(["nm", "-u", str(path)], text=True)
        defined = subprocess.check_output(["nm", "--defined-only", str(path)], text=True)
        relocations = subprocess.check_output(["readelf", "-Wr", str(path)], text=True)
        disassembly = subprocess.check_output(["objdump", "-dr", str(path)], text=True)
        header = subprocess.check_output(["readelf", "-h", str(path)], text=True)
        require("REL (Relocatable file)" in header and "Advanced Micro Devices X86-64" in header,
                "not-native-x86-relocatable:" + label)
        for suffix, content in (("undefined", undefined), ("defined", defined),
                                ("relocations", relocations), ("disassembly", disassembly),
                                ("elf-header", header)):
            (evidence / (label + "-" + suffix + ".txt")).write_text(content)
        return ({line.split()[-1] for line in undefined.splitlines() if line.split()},
                {line.split()[-1] for line in defined.splitlines() if line.split()},
                relocations, disassembly)

    broker = out / OBJECTS[0]
    recorder = out / OBJECTS[1]
    broker_u, broker_d, broker_r, _ = inspect("owner", broker)
    require(OWNER_EXPORTS <= broker_d and "owner_retry_workfn" in broker_d,
            "owner-retry-definition-missing")
    queue_refs = {name for name in broker_u if name in
                  {"queue_work_on", "queue_work", "schedule_work", "queue_work_node"}}
    require(queue_refs and all(re.search(r"\b" + re.escape(name) + r"\b", broker_r)
                               for name in queue_refs), "owner-retry-workqueue-relocation")
    state["owner_retry_workqueue_imports"] = sorted(queue_refs)
    recorder_u, recorder_d, recorder_r, recorder_asm = inspect("recorder", recorder)
    recorder_api = {"swapz_observation_" + suffix for suffix in
                    ("init", "gate_init", "publish", "mint", "append", "stop", "seal", "export")}
    require(recorder_api <= recorder_d, "selected-recorder-definitions-missing")
    rcu_refs = {name for name in recorder_u if "synchronize_rcu" in name}
    require(rcu_refs and all(name in recorder_r for name in rcu_refs), "recorder-rcu-drain-relocation")
    require(re.search(r"\block\s+cmpxchg", recorder_asm), "recorder-atomic-reservation-instruction")
    state["recorder_api"] = sorted(recorder_api)
    state["recorder_rcu_imports"] = sorted(rcu_refs)
    state["recorder_atomic_cmpxchg_instruction"] = True
    state["locked_cmpxchg_sites"] = [line.strip() for line in recorder_asm.splitlines()
                                     if re.search(r"\block\s+cmpxchg", line)]
    state["recorder_undefined"] = sorted(recorder_u)
    state["target_recorder_imports"] = sorted(s for s in target_imports if
        s.startswith(("swapz_observation_", "swapz_trial_observation_")))
    owner_u, owner_d, owner_r, _ = inspect("observation-owner", out / OBJECTS[2])
    require(OBSERVATION_WRAPPERS | OBSERVATION_CONTROL <= owner_d,
            "observation-owner-definitions")
    require(recorder_api - {"swapz_observation_gate_init"} <= owner_u,
            "observation-owner-adapter-imports")
    require(all(name in owner_r for name in recorder_api - {"swapz_observation_gate_init"}),
            "observation-owner-adapter-relocations")
    state["observation_owner_definitions"] = sorted(OBSERVATION_WRAPPERS | OBSERVATION_CONTROL)
    state["observation_owner_adapter_imports"] = sorted(recorder_api & owner_u)
    state["producer_observation_imports"] = {}
    for label, path in (("mm-zswap", "mm/zswap.o"), ("mm-page-io", "mm/page_io.o")):
        imports, definitions, relocations, _ = inspect(label, out / path)
        refs = {name for name in imports if name.startswith(
            ("swapz_trial_observation_", "swapz_mm_observation_"))}
        require(all(name in relocations for name in refs), "producer-observation-relocation:" + label)
        state["producer_observation_imports"][label] = sorted(refs)
        if label == "mm-zswap":
            require("swapz_mm_candidate_observation" in definitions,
                    "producer-candidate-accessor-not-emitted")
            state["candidate_accessor_defined"] = True
    state["target_candidate_accessor_import"] = "swapz_mm_candidate_observation" in target_imports
    state["scope_and_event_limitations"] = [
        "FROZEN_SCOPE_CONST_ZERO_AND_ORDERED_CLAIM_HARD_OFF",
        "FROZEN_TARGET_MISSING_CORRELATION_APPEND_NULL",
        "FROZEN_MM_EVENT_RECORD_FIELD_REUSE_NOT_CONFORMANT",
        "R097_PRODUCER_HOST_STATUS_NOT_REQUIRED_FOR_THIS_COMPILE"]
    # Some producer paths are optimized away by the hard-off scope. Report
    # actual imports and relocations without manufacturing positive hooks.
    state["completed_steps"].append("native-owner-recorder-symbol-check")

    # A diagnostic mixed-domain relocatable, NOT a kernel or loadable module.
    # Keep the original objects to distinguish real cross-object relocations.
    composite = evidence / "changed-components.o"
    step(state, evidence, "changed-components-relocatable",
         ["ld", "-r", "-o", str(composite), *(str(out / p) for p in OBJECTS),
          *(str(module / p) for p in PRODUCT_OBJECTS)], timeout=60)
    composite_u, composite_d, _, _ = inspect("changed-composite", composite)
    require(OWNER_EXPORTS | recorder_api | gate_calls | OBSERVATION_WRAPPERS | OBSERVATION_CONTROL <= composite_d,
            "composite-required-definitions")
    require(not ((OWNER_EXPORTS | gate_calls | gated_calls | OBSERVATION_WRAPPERS | recorder_api) & composite_u),
            "composite-internal-unresolved")
    require(not (out / "vmlinux").exists() and not (module / "dm-swapz.ko").exists(),
            "unexpected-final-link")
    require(not (out / "Module.symvers").exists() and not (module / "Module.symvers").exists(),
            "unexpected-modpost-symvers")
    state["composite"] = image(composite)
    state["composite_undefined"] = sorted(composite_u)
    state["composite_scope"] = "MIXED_DOMAIN_DIAGNOSTIC_ET_REL_ONLY"
    state["completed_steps"].append("relocatable-symbol-check")
    for path in set(IMAGES) | set(R092_IMAGES) | set(R094_IMAGES) | set(R095_IMAGES) | set(R096_IMAGES) | set(R097_IMAGES):
        pin(linux / path, final_raw_pin(path))
    for name in PRODUCT.keys() - UNSELECTED - set(RECORDER):
        if name == "Makefile":
            require(image(module / name) == state["module_makefile_compatible"], "module-kbuild-drift")
        else:
            pin(module / name, final_product_pin(name))
    for path, expected in state["scratch_postimages"].items():
        require(image(linux / path) == expected, "scratch-postimage-drift:" + path)
    require(digest((out / ".config").read_bytes()) == state["config_sha256"], "config-drift")
    state["completed_steps"].append("final-source-check")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prerequisites-only", action="store_true")
    for name in ("baseline", "linux", "out", "module"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--source-parent", required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve()
    os.umask(0o077)
    evidence.mkdir(parents=True, exist_ok=True)
    state = {
        "status": "IN_PROGRESS", "phase": "preflight", "first_error": None,
        "source_sha": args.source_sha, "source_parent": args.source_parent,
        "frozen_product": BASELINE, "linux_pin": LINUX, "patches": PATCHES,
        "raw_patches_applied": False, "actual_raw_r092_overlay": False,
        "r092_overlay_pin": R092_OVERLAY_PIN, "r094_overlay_pin": R094_OVERLAY_PIN,
        "actual_raw_r094_overlay": False, "old_scratch_exports": False,
        "r095_capture_off_pin": R095_CAPTURE_OFF_PIN,
        "actual_raw_r095_capture_off": False,
        "observation_fence_stacked": False,
        "native_recorder": "SELECTED_RCU_OWNER_AND_ADAPTER_ONLY",
        "r097_producer_pin": R097_PRODUCER_PIN,
        "actual_raw_r097_producer": False,
        "r096_owner_retry_pin": R096_RETRY_PIN,
        "actual_raw_r096_owner_retry": False,
        "native_positive_path": "ABSENT_FROZEN_ORDERED_CLAIM_HARD_OFF",
        "modpost": "NOT_RUN", "actual_physical_io": False, "runtime": "NOT_RUN",
        "product_pins": PRODUCT,
        "elf_prerequisite": "NOT_RUN", "build_attempts": 0,
        "full_kernel_link": False, "product_module_link": False,
        "vm_boot": False, "vm_build": False, "module_loaded": False,
        "source_mapped_authenticated": 0, "phase_a": "BLOCKED",
        "direct_handoff": False, "forced_raw_bypass": False, "import_active": False,
        "completed_steps": [],
    }
    try:
        if args.prerequisites_only:
            prerequisites(state, evidence)
            state["status"] = "PREREQUISITES_PASS"
            state["phase"] = "prerequisites-complete"
            write_json(evidence / "prerequisites.json", state)
            return 0
        prior = json.loads((evidence / "prerequisites.json").read_text())
        require(prior["source_sha"] == args.source_sha and prior["source_parent"] == args.source_parent
                and prior["status"] == "PREREQUISITES_PASS"
                and prior["elf_prerequisite"] == prior["openssl_prerequisite"] == "PASS",
                "missing-verified-early-prerequisites")
        for key in ("compiler", "linker", "elf_prerequisite", "openssl_prerequisite"):
            state[key] = prior[key]
        state["completed_steps"] = prior["completed_steps"]
        require(all(getattr(args, name) is not None for name in ("baseline", "linux", "out", "module")),
                "missing-stage-arguments")
        baseline, linux, out, module = (getattr(args, name).resolve()
                                        for name in ("baseline", "linux", "out", "module"))
        require(len({baseline, linux, out, module, evidence}) == 5, "path-alias")
        require(all(not a.is_relative_to(b) for a in (out, module, evidence)
                    for b in (baseline, linux)), "output-in-source")
        require(not out.exists() and not module.exists(), "output-not-pristine")
        stage(state, evidence, baseline, linux, module)
        build(state, evidence, linux, out, module)
        state["status"] = "SUCCESS"
        state["phase"] = "complete"
        print("R098_SMP_DIRECTED_NATIVE_PASS SMP=YES TREE_RCU=YES owner_retry=YES selected_rcu=YES gated_target=YES composite=ET_REL full_kernel=NO modpost=NO final_ko=NO AUTH0", flush=True)
        return 0
    except (Failure, OSError, ValueError, subprocess.SubprocessError) as error:
        state["status"] = "FAILURE"
        state["first_error"] = str(error)[:450]
        print("R098_FIRST_ERROR phase=" + state["phase"] + " " + state["first_error"],
              file=sys.stderr, flush=True)
        return 2
    finally:
        write_json(evidence / "results.json", state)


if __name__ == "__main__":
    sys.exit(main())
