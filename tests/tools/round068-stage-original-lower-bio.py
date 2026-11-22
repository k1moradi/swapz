#!/usr/bin/env python3
"""Round068 stage an exact pinned original Linux native block BIO-only KUnit.

Pristine original block/bio.c, include/linux/bio.h and blk_types.h are
verified against immutable c339f... Git blobs BEFORE planning any write.
Only original block/bio.c receives a test-only appended suite, never product
DM, native decoder-owner or physical swap. No branch/worktree is created.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
}
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "runtime/native/fixtures/round068-original-lower-bio-owned.cfrag"
START = b"/* ROUND068_ORIGINAL_NATIVE_LOWER_BIO_BEGIN"
END = b"/* ROUND068_ORIGINAL_NATIVE_LOWER_BIO_END */"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_blob(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    ).hexdigest()


def plan(pristine: dict[str, bytes], existing: dict[str, bytes],
         fixture: bytes) -> bytes:
    for path, expected in ORIGINAL_BLOBS.items():
        if git_blob(pristine[path]) != expected:
            raise ValueError("pinned-original-blob:" + path)
        if existing[path] != pristine[path]:
            raise ValueError("pristine-original-replaced:" + path)
    if (fixture.count(START) != 1 or fixture.count(END) != 1 or
            fixture.count(b"kunit_test_suite(swapz_round068_native_lower_suite);") != 1 or
            fixture.count(b"bio_endio(async->bio);") != 1 or
            fixture.count(b"bio_for_each_segment(vector, bio, iterator)") != 1):
        raise ValueError("original-native-fixture-markers")
    if START in existing["block/bio.c"]:
        raise ValueError("already-staged")
    return existing["block/bio.c"] + b"\n" + fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if subprocess.check_output(
            ["git", "-C", str(args.linux_root), "rev-parse", "HEAD"],
            text=True).strip() != PIN:
        raise ValueError("unpinned-original-Linux-HEAD")
    pristine = {
        path: subprocess.check_output(
            ["git", "-C", str(args.linux_root), "show", "HEAD:" + path])
        for path in ORIGINAL_BLOBS
    }
    existing = {
        path: (args.linux_root / path).read_bytes()
        for path in ORIGINAL_BLOBS
    }
    fixture = FIXTURE.read_bytes()
    planned = plan(pristine, existing, fixture)
    if args.verify_only:
        rejected = 0
        candidates = [
            (dict(pristine, **{"block/bio.c": pristine["block/bio.c"] + b"x"}),
             existing, fixture, "pinned-original-blob:block/bio.c"),
            (pristine, dict(existing, **{
                "include/linux/blk_types.h":
                existing["include/linux/blk_types.h"] + b"x"}),
             fixture, "pristine-original-replaced:include/linux/blk_types.h"),
            (pristine, existing,
             fixture.replace(b"bio_endio(async->bio);",
                             b"/* missing callback */"),
             "original-native-fixture-markers"),
            (pristine, dict(existing, **{
                "block/bio.c": planned}), fixture,
             "pristine-original-replaced:block/bio.c"),
        ]
        for pins, current, altered, failure in candidates:
            original_snapshot = current.copy()
            try:
                plan(pins, current, altered)
            except ValueError as error:
                if str(error) != failure:
                    raise ValueError("negative-first-cause:" + str(error)) from error
            else:
                raise ValueError("negative-source-accepted:" + failure)
            if original_snapshot != current:
                raise ValueError("failed-plan-wrote-original-source")
            rejected += 1
        print("PASS round068_true_original_native_bio_pinned_plan=3 "
              "negative_sources=" + str(rejected) + " no_partial_writes=1")
        return
    destination = args.linux_root / "block/bio.c"
    destination.write_bytes(planned)
    if destination.read_bytes() != planned:
        raise ValueError("postimage-write-error")
    args.manifest.write_text(json.dumps({
        "source_original": PIN,
        "target_original_blob": ORIGINAL_BLOBS["block/bio.c"],
        "source_staged_modified": True,
        "SOURCE_MAPPED_AUTHENTICATED": 0,
        "PHASE_A": "BLOCKED",
        "native_bio_test_only": True,
        "path": "block/bio.c",
        "preimage_sha256": sha256(existing["block/bio.c"]),
        "postimage_sha256": sha256(planned),
        "fixture_sha256": sha256(fixture),
        "actual_native_cases": 3,
        "real_lower_device": False,
        "real_upper_ack": False,
    }, indent=2) + "\n")
    print("PASS round068_true_original_block_bio_C_staged="
          "pristine_pin_verified actual_kernel_bio=TEST_ONLY AUTH0")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("ROUND068_NATIVE_STAGE_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError)
               else type(error).__name__)[:170])
        raise SystemExit(2) from None
