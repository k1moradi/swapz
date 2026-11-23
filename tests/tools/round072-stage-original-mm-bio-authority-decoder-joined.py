#!/usr/bin/env python3
"""Compose source-exact original mm/zswap.c + real BIO/authority/decoder native KUnit.

Requires *already staged* pristine pinned original Linux through the previous
Round058 MM/BIO composer and Round069 zswap STORED source composer. The only
kernel source postimage this stage changes is mm/zswap.c; no original production
kernel file is checked in or edited outside an ephemeral rootless test image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LINUX_PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
}
PRODUCT_BLOBS = {
    "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
    "zswap-import-decoder-owner.c": "8e0c8f4d2085af7f2e17df412f3a1af654063571",
    "zswap-import-decoder-owner.h": "e1b4b903567070e2307f7d05f8e48c14e0bb3768",
    "zswap-import-codec.h": "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6",
}
SOURCE_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-zswap-stored-source.cfrag"
BIO_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-bio-authority-joined.cfrag"
JOIN_FIXTURE = ROOT / "tests/runtime/native/fixtures/round072-original-mm-bio-authority-decoder-joined.cfrag"
INCLUDE_AUTHORITY = "mm/swapz_round069"
INCLUDE_DECODER = "mm/swapz_round072"
JOIN_BEGIN = b"/* ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_BEGIN"
JOIN_END = b"/* ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_END */"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def plan(current: bytes, base_manifest: dict,
         original: dict[str, bytes], product: dict[str, bytes],
         source_fixture: bytes, bio_fixture: bytes,
         new_fixture: bytes) -> dict[str, bytes]:
    for path, original_data in original.items():
        if git_blob(original_data) != ORIGINAL_BLOBS[path]:
            raise ValueError("pristine-original-kernel-blob:" + path)
    if (base_manifest.get("original_sha") != LINUX_PIN or
            base_manifest.get("source_mapped_authenticated") is not False):
        raise ValueError("source-stage-original-pin-or-auth")
    records = base_manifest.get("changed_paths")
    if (not isinstance(records, list) or len(records) != 1 or
            records[0].get("path") != "mm/zswap.c" or
            records[0].get("staged_sha256") != sha256(current)):
        raise ValueError("inherited-original-mm-zswap-postimage")
    if (current.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_BEGIN") != 1 or
            current.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_END */") != 1 or
            source_fixture not in current):
        raise ValueError("unchanged-original-source-fixture-not-linked")
    for name, expected in PRODUCT_BLOBS.items():
        if git_blob(product[name]) != expected:
            raise ValueError("actual-product-byte-identity:" + name)
    if (bio_fixture.count(b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_BEGIN") != 1 or
            bio_fixture.count(b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_END */") != 1 or
            bio_fixture.count(b"bio_endio(io->bio);") != 1 or
            bio_fixture.count(b"swapz_round069_native_gc_copy_fua(") != 2 or
            bio_fixture.count(b'#include "swapz_round069/authority.c"') != 1 or
            bio_fixture.count(b'#include "swapz_round069/codec.c"') != 1):
        raise ValueError("inherited-genuine-original-bio-fixture-drift")
    if (new_fixture.count(JOIN_BEGIN) != 1 or
            new_fixture.count(JOIN_END) != 1 or
            new_fixture.count(b"kunit_test_suite(swapz_round072_native_joined_suite);") != 1 or
            new_fixture.count(b"swapz_round069_capture_stored(") != 1 or
            new_fixture.count(b"swapz_round069_run_io(") < 2 or
            new_fixture.count(b"swapz_zswap_import_decoder_owner_decode(") != 2 or
            new_fixture.count(b"zs_free(") < 2):
        raise ValueError("new-original-MM-BIO-authority-decoder-chain-missing")
    if JOIN_BEGIN in current:
        raise ValueError("double-joined-stage")
    target = current.rstrip(b"\n") + b"\n\n" + bio_fixture + b"\n" + new_fixture
    outputs = {"mm/zswap.c": target}
    outputs.update({INCLUDE_AUTHORITY + "/" + name: product[name]
                    for name in ("authority.c", "authority.h", "codec.c",
                                 "codec.h", "gc-cost.h")})
    outputs.update({INCLUDE_DECODER + "/" + name: product[name]
                    for name in ("zswap-import-decoder-owner.c",
                                 "zswap-import-decoder-owner.h",
                                 "zswap-import-codec.h", "codec.h")})
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    linux = args.linux_root
    actual_pin = subprocess.check_output(
        ["git", "-C", str(linux), "rev-parse", "HEAD"], text=True).strip()
    if actual_pin != LINUX_PIN:
        raise ValueError("not-pristine-original-Linux-pin")
    original = {path: subprocess.check_output([
        "git", "-C", str(linux), "show", "HEAD:" + path])
        for path in ORIGINAL_BLOBS}
    current = (linux / "mm/zswap.c").read_bytes()
    source_fixture, bio_fixture, new_fixture = (
        SOURCE_FIXTURE.read_bytes(), BIO_FIXTURE.read_bytes(),
        JOIN_FIXTURE.read_bytes())
    product = {name: (ROOT / "src/kernel" / name).read_bytes()
               for name in PRODUCT_BLOBS}
    base_manifest = json.loads(args.base_manifest.read_text())
    staged = plan(current, base_manifest, original, product,
                  source_fixture, bio_fixture, new_fixture)
    if args.verify_only:
        cases = [
            ("inherited-original-mm-zswap-postimage",
             current + b"tampered", base_manifest, original, product,
             source_fixture, bio_fixture, new_fixture),
            ("source-stage-original-pin-or-auth", current,
             dict(base_manifest, source_mapped_authenticated=True), original,
             product, source_fixture, bio_fixture, new_fixture),
            ("pristine-original-kernel-blob:mm/zswap.c", current,
             base_manifest, dict(original, **{"mm/zswap.c": b"bad"}),
             product, source_fixture, bio_fixture, new_fixture),
            ("actual-product-byte-identity:authority.c", current,
             base_manifest, original,
             dict(product, **{"authority.c": product["authority.c"] + b"X"}),
             source_fixture, bio_fixture, new_fixture),
            ("inherited-genuine-original-bio-fixture-drift", current,
             base_manifest, original, product, source_fixture,
             bio_fixture.replace(b"bio_endio(io->bio);", b"/* removed */"),
             new_fixture),
            ("new-original-MM-BIO-authority-decoder-chain-missing", current,
             base_manifest, original, product, source_fixture, bio_fixture,
             new_fixture.replace(
                 b"kunit_test_suite(swapz_round072_native_joined_suite);",
                 b"/* removed */")),
        ]
        for expected, before, manifest, pristine, real_product, source, bio, new in cases:
            try:
                plan(before, manifest, pristine, real_product,
                     source, bio, new)
            except ValueError as error:
                if str(error) != expected:
                    raise ValueError("wrong-first-negative:" + str(error)) from error
            else:
                raise ValueError("invalid-native-source-accepted:" + expected)
        print("PASS round072_original_join_source_plan originals=2 "
              "inherited-MM-XArray-source=1 original-BIO-endio=1 "
              "actual-production-blobs=8 staged_postimages=10 "
              "negative_plans=6 no_partial_writes=1 AUTH0")
        return
    if (linux / INCLUDE_AUTHORITY).exists() or (linux / INCLUDE_DECODER).exists():
        raise ValueError("joined-product-copy-already-exists")
    for directory in (INCLUDE_AUTHORITY, INCLUDE_DECODER):
        (linux / directory).mkdir(mode=0o700)
    for path, content in staged.items():
        target = linux / path
        target.write_bytes(content)
        if target.read_bytes() != content:
            raise ValueError("native-original-postimage:" + path)
    args.manifest.write_text(json.dumps({
        "original": LINUX_PIN,
        "tested_original_source": "mm/zswap.c+block/bio.c",
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": "DISABLED",
        "actual_physical_io": False,
        "actual_upper_bio_ack": False,
        "joined_original_source_XArray_zsmalloc_bio_authority_decoder": True,
        "inherited_original_mm_manifest_sha256": sha256(
            args.base_manifest.read_bytes()),
        "files": [{"path": path, "sha256": sha256(data),
                   "actual_product_git_blob":
                   PRODUCT_BLOBS.get(Path(path).name)}
                  for path, data in staged.items()],
    }, indent=2) + "\n")
    print("PASS round072_staged_actual_native_join=10 "
          "original_source_XArray_zsmalloc=YES actual_native_bio_endio=YES "
          "exact_product_authority=YES real_independent_decoder_owner=YES "
          "model_only=YES AUTH0")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError,
            subprocess.SubprocessError, json.JSONDecodeError) as error:
        print("ROUND072_JOIN_FIRST_ERROR " + (
            str(error) if isinstance(error, ValueError)
            else type(error).__name__)[:220], file=sys.stderr)
        sys.exit(2)
