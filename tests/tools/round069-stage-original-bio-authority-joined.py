#!/usr/bin/env python3
"""Stage ONE exact original native bio.c KUnit with byte-identical real product C.

Pristine original torvalds/linux@c339f... SHA and all ORIGINAL block/bio.c,
bio.h and blk_types.h Git blobs are pinned. This test-only rootless composer
appends a guarded original native KUnit to block/bio.c and copies the original
product authority.c/codec.c and headers into an isolated test-only include
subdirectory, WITHOUT editing product C, original DM, zswap, decoder-owner,
original Makefiles, the real physical lower or any loaded kernel.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ORIGINAL = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
}
# Historical native composition only; current host qualification is separate.
HISTORICAL_PRODUCT_COMMIT = "22fbdd0090e302bd17b3811145395ceb0a814a6c"
ACTUAL_PRODUCT_BLOBS = {
    "authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "gc-cost.h": "2d317f1274ef36bdde157ff72acc26a9f7ae1e0e",
}
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-bio-authority-joined.cfrag"
DEST = "block/swapz_round069"
BEG = b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_BEGIN"
END = b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_END */"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def plan(original: dict[str, bytes], current: dict[str, bytes],
         product: dict[str, bytes], fixture: bytes) -> dict[str, bytes]:
    for path, expected in ORIGINAL_BLOBS.items():
        if git_blob(original[path]) != expected:
            raise ValueError("pinned-original-blob:" + path)
        if current[path] != original[path]:
            raise ValueError("original-source-not-pristine:" + path)
    for name, expected in ACTUAL_PRODUCT_BLOBS.items():
        if git_blob(product[name]) != expected:
            raise ValueError("real-product-git-blob-drift:" + name)
    # The original-kernel current task macro must be isolated ONLY while
    # including the byte-identical product authority.c and then restored.
    authority_macro_guard = (
        b'#pragma push_macro("current")\n'
        b'#undef current\n'
        b'#include "swapz_round069/authority.c"\n'
        b'#pragma pop_macro("current")'
    )
    if (fixture.count(BEG) != 1 or fixture.count(END) != 1 or
            fixture.count(authority_macro_guard) != 1 or
            fixture.count(b'#include "swapz_round069/authority.c"') != 1 or
            fixture.count(b'#include "swapz_round069/codec.c"') != 1 or
            fixture.count(b"bio_endio(io->bio);") != 1 or
            fixture.count(b"swapz_import_lower_end_write(") != 2 or
            fixture.count(b"swapz_import_lower_end_read(") != 1 or
            fixture.count(b"swapz_import_lower_end_flush(") != 1 or
            fixture.count(b"kunit_test_suite(swapz_round069_joined_native_suite);") != 1):
        raise ValueError("actual-original-native-joined-fixture-source")
    if BEG in current["block/bio.c"]:
        raise ValueError("double-native-stage")
    staged = {"block/bio.c": current["block/bio.c"] + b"\n" + fixture}
    staged.update({DEST + "/" + name: data for name, data in product.items()})
    return staged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    linux = args.linux_root
    if subprocess.check_output(
            ["git", "-C", str(linux), "rev-parse", "HEAD"],
            text=True).strip() != ORIGINAL:
        raise ValueError("not-pristine-original-linux-pin")
    original = {
        path: subprocess.check_output(["git", "-C", str(linux),
                                       "show", "HEAD:" + path])
        for path in ORIGINAL_BLOBS
    }
    current = {path: (linux / path).read_bytes() for path in ORIGINAL_BLOBS}
    product = {
        name: subprocess.check_output([
            "git", "--no-replace-objects", "-C", str(ROOT), "show",
            HISTORICAL_PRODUCT_COMMIT + ":src/kernel/" + name], timeout=60)
        for name in ACTUAL_PRODUCT_BLOBS
    }
    fixture = FIXTURE.read_bytes()
    staged = plan(original, current, product, fixture)
    if args.verify_only:
        negatives = [
            (dict(original, **{"block/bio.c": b"bad"}), current, product,
             fixture, "pinned-original-blob:block/bio.c"),
            (original, dict(current, **{
                "include/linux/bio.h": current["include/linux/bio.h"] + b"X"}),
             product, fixture, "original-source-not-pristine:include/linux/bio.h"),
            (original, current, dict(product, **{
                "authority.c": product["authority.c"] + b"/* mutant */"}),
             fixture, "real-product-git-blob-drift:authority.c"),
            (original, current, product,
             fixture.replace(b"bio_endio(io->bio);", b"/* missing endio */"),
             "actual-original-native-joined-fixture-source"),
            (original, current, product,
             fixture.replace(b'#undef current\n',
                             b'/* current macro not hidden */\n'),
             "actual-original-native-joined-fixture-source"),
            (original, dict(current, **{
                "block/bio.c": staged["block/bio.c"]}), product,
             fixture, "original-source-not-pristine:block/bio.c"),
        ]
        for pinned, actual, source, test, cause in negatives:
            saved = dict(actual)
            try:
                plan(pinned, actual, source, test)
            except ValueError as error:
                if str(error) != cause:
                    raise ValueError("wrong-first-negative:" + str(error)) from error
            else:
                raise ValueError("invalid-native-source-accepted:" + cause)
            if saved != actual:
                raise ValueError("invalid-native-source-altered")
        print("PASS original_native_join_source_plan=6_paths pristine_pin=3 "
              "actual_authority_codec_blobs=5 negative_plans=6 no_partial_write=1")
        return
    if (linux / DEST).exists():
        raise ValueError("joined-source-copy-already-exists")
    (linux / DEST).mkdir(mode=0o700)
    for path, content in staged.items():
        target = linux / path
        target.write_bytes(content)
        if target.read_bytes() != content:
            raise ValueError("joined-source-postimage:" + path)
    args.manifest.write_text(json.dumps({
        "original": ORIGINAL,
        "historical_product_commit": HISTORICAL_PRODUCT_COMMIT,
        "original_original_bio_blob": ORIGINAL_BLOBS["block/bio.c"],
        "source_mapped_authenticated": False,
        "import_active": False,
        "phase_a": "BLOCKED",
        "joined_real_linux_bio_endio_to_real_authority": True,
        "kernel_source_composition_test_only": True,
        "files": [
            {"path": path, "sha256": digest(content),
             "source_product_blob": ACTUAL_PRODUCT_BLOBS.get(Path(path).name)}
            for path, content in staged.items()
        ],
    }, indent=2) + "\n")
    print("PASS original_native_join_source_staged=6 "
          "original_bio_and_actual_authority_C same_translation_unit=YES AUTH0")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("ROUND069_JOIN_STAGE_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError)
               else type(error).__name__)[:180])
        raise SystemExit(2) from None
