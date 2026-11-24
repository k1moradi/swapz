#!/usr/bin/env python3
"""Rootless exact-pinned original Linux READ-side GC and decoder-owner KUnit stage.

The baseline comes from the independently published Round058/069 original
source composers, not from Round072's writer joining. This appends only a
test-only independent reader suite and byte-identical read-side helpers to an
ephemeral Linux checkout. No kernel or product production file is published.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
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
FIXTURE = ROOT / "tests/runtime/native/fixtures/round073-original-reader-pin-gc-kunit.cfrag"
SOURCE_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-zswap-stored-source.cfrag"
BIO_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-bio-authority-joined.cfrag"
AUTH_DIR = "mm/swapz_round069"
DECODER_DIR = "mm/swapz_round073"
TEST_BEGIN = b"/* ROUND073_ORIGINAL_READER_PIN_GC_BEGIN"
TEST_END = b"/* ROUND073_ORIGINAL_READER_PIN_GC_END */"
SUITE = b"kunit_test_suite(swapz_round073_original_reader_suite);"


class StageFailure(Exception):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise StageFailure(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob(data: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def checked_output(arguments: list[str]) -> bytes:
    return subprocess.run(arguments, capture_output=True, check=True,
                          timeout=55).stdout


def validate_reader_cleanup(fixture: bytes) -> None:
    """One native/host contract; validate actual executable helper and order."""
    label = "original-reader-late-lease-must-release-before-closer-join"
    begin = b"/* ROUND080_READER_LEASE_CLEANUP_BEGIN"
    end = b"/* ROUND080_READER_LEASE_CLEANUP_END */"
    call = b"swapz_round080_release_decoder_leases(&lease, &late);"
    join = b"kthread_stop(closer_task);"
    require(fixture.count(begin) == 1 and fixture.count(end) == 1 and
            fixture.count(call) == 1 and fixture.count(join) == 1 and
            fixture.index(call) < fixture.index(join), label)
    helper = fixture[fixture.index(begin):fixture.index(end)]
    late_put = b"if (late->owner)\n\t\terror = swapz_zswap_import_decoder_owner_put(late);"
    primary_put = b"if (lease->owner) {\n\t\tcleanup_error = swapz_zswap_import_decoder_owner_put(lease);"
    require(helper.count(late_put) == 1 and helper.count(primary_put) == 1 and
            helper.index(late_put) < helper.index(primary_put) and
            b"if (!error)" in helper and b"return error;" in helper, label)
    require(fixture.count(b"complete_all(&closer->returned);") == 1 and
            b"complete(&closer->returned);" not in fixture and
            b"wait_for_completion(&closer->returned);" not in fixture and
            b"wait_for_completion(&closer.returned);" not in fixture and
            b"ROUND080_READER_NATIVE_FIRST_ERROR stalled_phase=" in fixture and
            fixture.count(b"get_task_struct(closer_task);") == 1 and
            fixture.count(b"put_task_struct(closer_task);") == 1 and
            fixture.count(b"wake_up_process(closer_task);") == 1 and
            fixture.index(b"get_task_struct(closer_task);") <
            fixture.index(b"wake_up_process(closer_task);") and
            fixture.count(b"refcount_inc(&closer->references);") == 1 and
            fixture.count(b"swapz_round082_close_put(closer);") == 2 and
            b"cancel_delayed_work_sync(&stall.delayed);" in fixture and
            b"if (wait_for_completion_timeout(&closer->returned," in fixture,
            label)


def plan(current: bytes, manifest: dict, original: dict[str, bytes],
         product: dict[str, bytes], fixture: bytes,
         source_fixture: bytes, bio_fixture: bytes) -> dict[str, bytes]:
    require(manifest.get("original_sha") == PIN and
            manifest.get("source_mapped_authenticated") is False,
            "inherited-original-pin-auth0")
    rows = manifest.get("changed_paths")
    require(isinstance(rows, list) and len(rows) == 1 and
            rows[0].get("path") == "mm/zswap.c" and
            rows[0].get("staged_sha256") == sha256(current),
            "inherited-original-zswap-postimage")
    for name, expected in ORIGINAL_BLOBS.items():
        require(git_blob(original[name]) == expected,
                "original-Linux-blob:" + name)
    for name, expected in PRODUCT_BLOBS.items():
        require(git_blob(product[name]) == expected,
                "actual-product-C-blob:" + name)
    require(source_fixture in current and
            current.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_BEGIN") == 1 and
            current.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_END */") == 1,
            "inherited-original-XArray-zsmalloc-source")
    require(bio_fixture.count(
                b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_BEGIN") == 1 and
            bio_fixture.count(b"/* ROUND069_ORIGINAL_BIO_AUTHORITY_JOIN_END */") == 1 and
            bio_fixture.count(b"bio_endio(io->bio);") == 1 and
            b"swapz_round069_native_gc_copy_fua(" in bio_fixture and
            b'#include "swapz_round069/authority.c"' in bio_fixture,
            "inherited-original-BIO-real-authority-reader")
    validate_reader_cleanup(fixture)
    require(fixture.count(b"#include <linux/delay.h>") == 1 and
            fixture.index(b"#include <linux/delay.h>") <
            fixture.index(b"usleep_range(1000, 2000);") and
            b"for (iteration = 0; iteration < 1500U &&" in fixture,
            "original-native-delay-header-or-bounded-context")
    require(fixture.count(TEST_BEGIN) == 1 and
            fixture.count(TEST_END) == 1 and fixture.count(SUITE) == 1 and
            b"swapz_import_lower_begin_read(" in fixture and
            b"swapz_round069_native_gc_copy_fua(" in fixture and
            b"swapz_zswap_import_decoder_owner_decode(" in fixture and
            b"zs_obj_read_sg_begin(" in fixture and
            b"swapz_zswap_import_decoder_owner_close_and_drain(" in fixture,
            "new-original-reader-GC-lease-KUnit-fixture")
    for name in ("swapz_round073_original_lz4_old_reader_gc",
                 "swapz_round073_original_lzo1x_old_reader_gc",
                 "swapz_round073_original_stale_crc_sha_codec",
                 "swapz_round073_original_decoder_retire_with_pin"):
        require(fixture.count(("KUNIT_CASE(" + name + ")").encode()) == 1,
                "native-unique-KUnit-case:" + name)
    require(TEST_BEGIN not in current and
            b"ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_BEGIN" not in current,
            "writer-join-or-duplicate-reader-stage-forbidden")
    staged = {"mm/zswap.c": current.rstrip(b"\n") + b"\n\n" +
              bio_fixture + b"\n" + fixture}
    staged.update({AUTH_DIR + "/" + name: product[name]
                   for name in ("authority.c", "authority.h", "codec.c",
                                "codec.h", "gc-cost.h")})
    staged.update({DECODER_DIR + "/" + name: product[name]
                   for name in ("zswap-import-decoder-owner.c",
                                "zswap-import-decoder-owner.h",
                                "zswap-import-codec.h", "codec.h")})
    return staged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--base-manifest", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--verify-stage", action="store_true")
    args = parser.parse_args()
    require(not (args.verify_only and args.verify_stage),
            "exclusive-stage-verification-mode")
    linux = args.linux_root
    require(checked_output(["git", "-C", str(linux), "rev-parse", "HEAD"])
            .decode().strip() == PIN, "actual-original-Linux-commit")
    original = {path: checked_output(
        ["git", "-C", str(linux), "show", "HEAD:" + path])
        for path in ORIGINAL_BLOBS}
    product = {name: (ROOT / "src/kernel" / name).read_bytes()
               for name in PRODUCT_BLOBS}
    base_bytes = args.base_manifest.read_bytes()
    base = json.loads(base_bytes)
    source_fixture, bio_fixture, fixture = (
        SOURCE_FIXTURE.read_bytes(), BIO_FIXTURE.read_bytes(),
        FIXTURE.read_bytes())

    if args.verify_stage:
        evidence = json.loads(args.manifest.read_text())
        require(evidence.get("original_linux_pin") == PIN and
                evidence.get("source_mapped_authenticated") is False and
                evidence.get("phase_a") == "BLOCKED" and
                evidence.get("inherited_manifest_sha256") == sha256(base_bytes),
                "staged-native-manifest-safety")
        require(len(evidence.get("files", [])) == 10,
                "staged-native-postimage-count")
        for entry in evidence["files"]:
            path = entry["path"]
            require(path in ({"mm/zswap.c"} |
                    {AUTH_DIR + "/" + name for name in
                     ("authority.c", "authority.h", "codec.c", "codec.h",
                      "gc-cost.h")} |
                    {DECODER_DIR + "/" + name for name in
                     ("zswap-import-decoder-owner.c",
                      "zswap-import-decoder-owner.h",
                      "zswap-import-codec.h", "codec.h")}),
                    "unexpected-staged-native-path")
            require(sha256((linux / path).read_bytes()) == entry["sha256"],
                    "staged-native-postimage:" + path)
        require(len({entry["path"] for entry in evidence["files"]}) == 10,
                "staged-native-duplicate-path")
        print("PASS ROUND073_ORIGINAL_NATIVE_POSTIMAGE files=10 pin=YES AUTH0")
        return 0

    current = (linux / "mm/zswap.c").read_bytes()
    output = plan(current, base, original, product, fixture,
                  source_fixture, bio_fixture)
    if args.verify_only:
        attempts = [
            ("inherited-original-pin-auth0",
             current, dict(base, source_mapped_authenticated=True),
             original, product, fixture, source_fixture, bio_fixture),
            ("original-Linux-blob:mm/zswap.c",
             current, base, {**original, "mm/zswap.c": b"bad"},
             product, fixture, source_fixture, bio_fixture),
            ("inherited-original-zswap-postimage",
             current + b"x", base, original, product, fixture,
             source_fixture, bio_fixture),
            ("actual-product-C-blob:zswap-import-decoder-owner.c",
             current, base, original,
             {**product, "zswap-import-decoder-owner.c": b"bad"},
             fixture, source_fixture, bio_fixture),
            ("original-reader-late-lease-must-release-before-closer-join",
             current, base, original, product,
             fixture.replace(b"swapz_round080_release_decoder_leases(&lease, &late);",
                             b"/* leaked late lease */"),
             source_fixture, bio_fixture),
            ("original-reader-late-lease-must-release-before-closer-join",
             current, base, original, product,
             fixture.replace(b"error = swapz_zswap_import_decoder_owner_put(late);",
                             b"error = 0;"),
             source_fixture, bio_fixture),
            ("original-reader-late-lease-must-release-before-closer-join",
             current, base, original, product,
             fixture.replace(b"kthread_stop(closer_task);", b"/* no join */", 1)
                    .replace(b"cleanup_error = swapz_round080_release_decoder_leases",
                             b"kthread_stop(closer_task);\n\tcleanup_error = swapz_round080_release_decoder_leases", 1),
             source_fixture, bio_fixture),
            ("original-reader-late-lease-must-release-before-closer-join",
             current, base, original, product,
             fixture.replace(b"complete_all(&closer->returned);",
                             b"complete(&closer->returned);"),
             source_fixture, bio_fixture),
            ("original-reader-late-lease-must-release-before-closer-join",
             current, base, original, product,
             fixture.replace(b"get_task_struct(closer_task);", b"/* missing ref */"),
             source_fixture, bio_fixture),
            ("original-native-delay-header-or-bounded-context",
             current, base, original, product,
             fixture.replace(b"#include <linux/delay.h>", b"/* missing */"),
             source_fixture, bio_fixture),
            ("new-original-reader-GC-lease-KUnit-fixture",
             current, base, original, product,
             fixture.replace(SUITE, b"/* killed */"), source_fixture,
             bio_fixture),
            ("inherited-original-BIO-real-authority-reader",
             current, base, original, product, fixture,
             source_fixture, bio_fixture.replace(
                 b"bio_endio(io->bio);", b"/* removed */")),
        ]
        for wanted, source, altered_manifest, pristine, components, own, original_source, bio in attempts:
            try:
                plan(source, altered_manifest, pristine, components,
                     own, original_source, bio)
            except StageFailure as failure:
                require(str(failure) == wanted,
                        "first-negative-" + wanted + ":" + str(failure))
            else:
                raise StageFailure("staging-mutant-accepted:" + wanted)
        print("PASS ROUND073_READER_STAGE_PLAN negatives=12 "
              "pristine_original_blobs=2 product_blobs=8 "
              "original_XArray_source=YES real_BIO_authority=YES AUTH0")
        return 0

    require(not args.manifest.exists(), "native-manifest-already-exists")
    require(not (linux / AUTH_DIR).exists() and
            not (linux / DECODER_DIR).exists(),
            "native-owned-directory-already-staged")
    # All original/product blob and inherited postimage validation precedes
    # first scratch write; no user disk or original checked-in file mutates.
    (linux / AUTH_DIR).mkdir(mode=0o700)
    (linux / DECODER_DIR).mkdir(mode=0o700)
    for path, data in output.items():
        target = linux / path
        target.write_bytes(data)
        require(target.read_bytes() == data, "postimage-write:" + path)
    args.manifest.write_text(json.dumps({
        "original_linux_pin": PIN,
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": "DISABLED",
        "forced_raw_bypass": "DISABLED",
        "import_active": False,
        "actual_physical_io": False,
        "actual_upper_ack": False,
        "test_created_xarray_stored": True,
        "native_original_read_bio_gc_decoder_lease": True,
        "inherited_manifest_sha256": sha256(base_bytes),
        "files": [{"path": path, "sha256": sha256(data)} for
                  path, data in output.items()],
    }, indent=2) + "\n")
    print("PASS ROUND073_ORIGINAL_READER_STAGE postimages=10 "
          "source_original_LZO1X_LZ4=YES native_read_pin_GC=YES AUTH0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (StageFailure, KeyError, ValueError, OSError,
            subprocess.SubprocessError, json.JSONDecodeError) as error:
        detail = str(error) if isinstance(error, StageFailure) else type(error).__name__
        print("ROUND073_READER_STAGE_FIRST_ERROR " + detail[:220],
              file=sys.stderr)
        raise SystemExit(2) from None
