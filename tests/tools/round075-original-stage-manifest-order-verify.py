#!/usr/bin/env python3
"""Round075 Agent5: two-phase source-exact original-kernel manifest integrity.

The inherited Round069 manifest describes PRE-join original mm/zswap.c. The
Round072 joined manifest describes POST-join original mm/zswap.c and nine
byte-identical product test include files. Never compare the former SHA against
the latter source. Preserve BOTH checks and bind them to an exact immutable
pre-join snapshot and the byte-exact original BIO + joined witness suffix.

Only rootless disposable pinned original Linux staging; not a production
kernel edit, real swapcache source, durable device or upper ACK.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LINUX_PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_ZSWAP_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
ORIGINAL_BIO_BLOB = "b0fcc69de653524479e3b328aa29a37e97945b84"
HISTORICAL_PRODUCT_COMMIT = "22fbdd0090e302bd17b3811145395ceb0a814a6c"
SOURCE_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-zswap-stored-source.cfrag"
BIO_FIXTURE = ROOT / "tests/runtime/native/fixtures/round069-original-bio-authority-joined.cfrag"
JOIN_FIXTURE = ROOT / "tests/runtime/native/fixtures/round072-original-mm-bio-authority-decoder-joined.cfrag"
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
JOIN_PATHS = frozenset(
    {"mm/zswap.c"} |
    {"mm/swapz_round069/" + name for name in
     ("authority.c", "authority.h", "codec.c", "codec.h", "gc-cost.h")} |
    {"mm/swapz_round072/" + name for name in
     ("zswap-import-decoder-owner.c", "zswap-import-decoder-owner.h",
      "zswap-import-codec.h", "codec.h")}
)


def ensure(condition: bool, label: str) -> None:
    if not condition:
        raise ValueError(label)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_blob(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()


def validate_inherited(inherited: bytes, manifest: dict[str, Any]) -> None:
    ensure(manifest.get("original_sha") == LINUX_PIN,
           "inherited-original-pin")
    ensure(manifest.get("original_zswap_git_blob") == ORIGINAL_ZSWAP_BLOB,
           "inherited-original-blob")
    ensure(manifest.get("source_mapped_authenticated") is False,
           "inherited-source-auth-must-stay-off")
    records = manifest.get("changed_paths")
    ensure(isinstance(records, list) and len(records) == 1 and
           isinstance(records[0], dict) and
           records[0].get("path") == "mm/zswap.c",
           "inherited-original-source-paths")
    ensure(b"ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_BEGIN"
           not in inherited, "inherited-validation-after-join")
    ensure(records[0].get("staged_sha256") == sha256(inherited),
           "inherited-original-source-postimage-sha256")
    source_fixture = SOURCE_FIXTURE.read_bytes()
    ensure(inherited.count(
        b"/* ROUND069_ORIGINAL_STORED_SOURCE_BEGIN") == 1 and
        inherited.count(
            b"/* ROUND069_ORIGINAL_STORED_SOURCE_END */") == 1 and
        source_fixture in inherited,
        "inherited-original-source-exact-fixture")
    ensure(isinstance(records[0].get("base_sha256"), str) and
           len(records[0]["base_sha256"]) == 64,
           "inherited-pristine-base-source-sha256")


def validate_joined(inherited: bytes, inherited_bytes: bytes,
                    final_files: dict[str, bytes],
                    joined_manifest: dict[str, Any]) -> None:
    validate_inherited(inherited, json.loads(inherited_bytes))
    ensure(joined_manifest.get("original") == LINUX_PIN,
           "joined-original-pin")
    ensure(joined_manifest.get("source_mapped_authenticated") is False and
           joined_manifest.get("phase_a") == "BLOCKED" and
           joined_manifest.get("direct_compressed_handoff") == "DISABLED" and
           joined_manifest.get("actual_physical_io") is False and
           joined_manifest.get("actual_upper_bio_ack") is False and
           joined_manifest.get(
               "joined_original_source_XArray_zsmalloc_bio_authority_decoder")
           is True, "joined-original-source-auth-gates")
    ensure(joined_manifest.get("inherited_original_mm_manifest_sha256") ==
           sha256(inherited_bytes), "joined-inherited-manifest-binding")
    records = joined_manifest.get("files")
    ensure(isinstance(records, list) and len(records) == len(JOIN_PATHS),
           "joined-final-file-count")
    paths = [record.get("path") for record in records
             if isinstance(record, dict)]
    ensure(len(paths) == len(records) and set(paths) == JOIN_PATHS,
           "joined-final-paths-or-duplicates")
    for record in records:
        path = record["path"]
        ensure(path in final_files and
               record.get("sha256") == sha256(final_files[path]),
               "joined-final-file-postimage-sha256:" + path)
        if path != "mm/zswap.c":
            expected_blob = PRODUCT_BLOBS.get(Path(path).name)
            ensure(record.get("actual_product_git_blob") == expected_blob and
                   git_blob(final_files[path]) == expected_blob,
                   "joined-byte-identical-product-blob:" + path)
    expected_final = (inherited.rstrip(b"\n") + b"\n\n" +
                      BIO_FIXTURE.read_bytes() + b"\n" +
                      JOIN_FIXTURE.read_bytes())
    ensure(final_files["mm/zswap.c"] == expected_final,
           "joined-source-exact-prefix-and-witness-suffix")
    ensure(final_files["mm/zswap.c"].count(
        b"/* ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_BEGIN") == 1 and
        final_files["mm/zswap.c"].count(
        b"/* ROUND072_ORIGINAL_MM_BIO_AUTHORITY_DECODER_JOIN_END */") == 1,
        "joined-native-four-case-witness-unique")


def verify_original_git_pin(linux: Path) -> None:
    revision = subprocess.check_output(
        ["git", "-C", str(linux), "rev-parse", "HEAD"],
        text=True, timeout=40).strip()
    ensure(revision == LINUX_PIN, "pristine-original-Linux-pin")
    for path, expected in (
        ("mm/zswap.c", ORIGINAL_ZSWAP_BLOB),
        ("block/bio.c", ORIGINAL_BIO_BLOB),
    ):
        original = subprocess.check_output(
            ["git", "-C", str(linux), "show", "HEAD:" + path],
            timeout=40)
        ensure(git_blob(original) == expected,
               "pristine-original-Linux-git-blob:" + path)


def verify_native(args: argparse.Namespace) -> None:
    linux = args.linux_root
    verify_original_git_pin(linux)
    inherited_bytes = args.inherited_manifest.read_bytes()
    inherited_manifest = json.loads(inherited_bytes)
    if args.phase == "pre":
        ensure(not args.snapshot.exists(), "inherited-snapshot-already-exists")
        source = (linux / "mm/zswap.c").read_bytes()
        validate_inherited(source, inherited_manifest)
        # Sealed before appending the different, final joined source image.
        args.snapshot.write_bytes(source)
        ensure(sha256(args.snapshot.read_bytes()) == sha256(source),
               "inherited-snapshot-readback-sha256")
        print("PASS round075_inherited_original_zswap_prejoin_source_SHA256 "
              "original_pin=VERIFIED original_git_blobs=2 AUTH0")
        return
    ensure(args.snapshot.is_file(), "joined-inherited-snapshot-missing")
    joined_manifest = json.loads(args.joined_manifest.read_bytes())
    records = joined_manifest.get("files")
    ensure(isinstance(records, list), "joined-final-file-count")
    final_files = {}
    for record in records:
        ensure(isinstance(record, dict) and
               isinstance(record.get("path"), str) and
               record["path"] in JOIN_PATHS,
               "joined-final-paths-or-duplicates")
        final_files[record["path"]] = (
            linux / record["path"]).read_bytes()
    validate_joined(args.snapshot.read_bytes(), inherited_bytes,
                    final_files, joined_manifest)
    print("PASS round075_joined_original_postjoin_all_10_SHA256 "
          "inherited_prejoin_SHA256=RETAINED original_pin=VERIFIED "
          "original_BIO_decoder_owner=SOURCE_EXACT AUTH0")


def self_test() -> None:
    inherited = (b"/* pristine original KUnit test extension */\n" +
                 SOURCE_FIXTURE.read_bytes())
    inherited_metadata = {
        "original_sha": LINUX_PIN,
        "original_zswap_git_blob": ORIGINAL_ZSWAP_BLOB,
        "source_mapped_authenticated": False,
        "changed_paths": [{
            "path": "mm/zswap.c", "base_sha256": "a" * 64,
            "staged_sha256": sha256(inherited),
        }],
    }
    inherited_bytes = (json.dumps(inherited_metadata,
                                  sort_keys=True) + "\n").encode()
    final_source = (inherited.rstrip(b"\n") + b"\n\n" +
                    BIO_FIXTURE.read_bytes() + b"\n" +
                    JOIN_FIXTURE.read_bytes())
    # This self-test models the historical native stage, not the current host
    # qualification. Read the same immutable product bytes as the R072 stager.
    product = {}
    for name, expected_blob in PRODUCT_BLOBS.items():
        content = subprocess.check_output(
            ["git", "--no-replace-objects", "-C", str(ROOT), "show",
             HISTORICAL_PRODUCT_COMMIT + ":src/kernel/" + name], timeout=60)
        ensure(git_blob(content) == expected_blob,
               "historical-product-blob:" + name)
        product[name] = content
    files = {"mm/zswap.c": final_source}
    files.update({"mm/swapz_round069/" + name: product[name]
                  for name in ("authority.c", "authority.h", "codec.c",
                               "codec.h", "gc-cost.h")})
    files.update({"mm/swapz_round072/" + name: product[name]
                  for name in ("zswap-import-decoder-owner.c",
                               "zswap-import-decoder-owner.h",
                               "zswap-import-codec.h", "codec.h")})
    manifest = {
        "original": LINUX_PIN,
        "source_mapped_authenticated": False,
        "phase_a": "BLOCKED",
        "direct_compressed_handoff": "DISABLED",
        "actual_physical_io": False,
        "actual_upper_bio_ack": False,
        "joined_original_source_XArray_zsmalloc_bio_authority_decoder": True,
        "inherited_original_mm_manifest_sha256": sha256(inherited_bytes),
        "files": [{
            "path": path,
            "sha256": sha256(data),
            "actual_product_git_blob":
                PRODUCT_BLOBS.get(Path(path).name),
        } for path, data in files.items()],
    }
    validate_inherited(inherited, inherited_metadata)
    validate_joined(inherited, inherited_bytes, files, manifest)

    def reject(name: str, expected: str, before: bytes = inherited,
               metadata: dict[str, Any] = inherited_metadata,
               after: dict[str, bytes] = files,
               joined: dict[str, Any] = manifest,
               doc: bytes = inherited_bytes,
               pre_only: bool = False) -> None:
        try:
            if pre_only:
                validate_inherited(before, metadata)
            else:
                validate_joined(before, doc, after, joined)
        except (ValueError, KeyError) as error:
            ensure(str(error) == expected,
                   "wrong-negative-first-error:" + name + ":" + str(error))
        else:
            raise ValueError("negative-source-stage-mutant-survived:" + name)

    reject("inherited-source-tamper",
           "inherited-original-source-postimage-sha256",
           before=inherited + b"tamper", pre_only=True)
    reject("inherited-spoofed-SHA",
           "inherited-original-source-postimage-sha256",
           metadata={**inherited_metadata, "changed_paths":[{
               **inherited_metadata["changed_paths"][0],
               "staged_sha256": "0" * 64}]},
           pre_only=True)
    reject("wrong-original-pin", "inherited-original-pin",
           metadata={**inherited_metadata, "original_sha": "0" * 40},
           pre_only=True)
    reject("wrong-original-blob", "inherited-original-blob",
           metadata={**inherited_metadata,
                     "original_zswap_git_blob": "0" * 40},
           pre_only=True)
    reject("wrong-stage-order", "inherited-validation-after-join",
           before=final_source, pre_only=True)
    reject("tampered-final", "joined-final-file-postimage-sha256:mm/zswap.c",
           after={**files, "mm/zswap.c": final_source + b"bad"})
    changed_final = final_source + b"bad"
    changed_manifest = {**manifest, "files":[
        {**row, "sha256": sha256(changed_final)}
        if row["path"] == "mm/zswap.c" else row
        for row in manifest["files"]]}
    reject("spoofed-final-hash",
           "joined-source-exact-prefix-and-witness-suffix",
           after={**files, "mm/zswap.c": changed_final},
           joined=changed_manifest)
    reject("missing-original-appended-witness",
           "joined-source-exact-prefix-and-witness-suffix",
           after={**files, "mm/zswap.c": inherited},
           joined={**manifest, "files":[
               {**row, "sha256": sha256(inherited)}
               if row["path"] == "mm/zswap.c" else row
               for row in manifest["files"]]})
    reject("mismatched-inherited-manifest",
           "joined-inherited-manifest-binding",
           joined={**manifest,
                   "inherited_original_mm_manifest_sha256": "0" * 64})
    reject("mutated-product-blob",
           "joined-final-file-postimage-sha256:mm/swapz_round069/authority.c",
           after={**files, "mm/swapz_round069/authority.c":
                  files["mm/swapz_round069/authority.c"] + b"bad"})
    # Self-consistent replacement hashes cannot substitute altered bytes
    # for the immutable historical product identity.
    altered_product_path = "mm/swapz_round069/authority.c"
    altered_product = files[altered_product_path] + b"bad"
    reject("spoofed-product-hashes",
           "joined-byte-identical-product-blob:" + altered_product_path,
           after={**files, altered_product_path: altered_product},
           joined={**manifest, "files": [
               {**row, "sha256": sha256(altered_product),
                "actual_product_git_blob": git_blob(altered_product)}
               if row["path"] == altered_product_path else row
               for row in manifest["files"]]})
    reject("joined-wrong-original-pin", "joined-original-pin",
           joined={**manifest, "original": "0" * 40})
    reject("post-before-final-stage",
           "joined-final-file-postimage-sha256:mm/zswap.c",
           after={**files, "mm/zswap.c": inherited})
    print("PASS round075_original_stage_manifest_order_self_test "
          "baseline_pre=1 baseline_final=10 negatives=13 "
          "spoofed_both=REJECTED wrong_order=REJECTED "
          "inherited_and_final_hashes=INDEPENDENT AUTH0")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--phase", choices=("pre", "post"))
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--inherited-manifest", type=Path)
    parser.add_argument("--joined-manifest", type=Path)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if args.self_test:
        ensure(args.phase is None, "unexpected-phase-with-self-test")
        self_test()
    else:
        ensure(args.phase is not None and args.linux_root is not None and
               args.inherited_manifest is not None and
               args.snapshot is not None and
               (args.phase == "pre" or args.joined_manifest is not None),
               "source-manifest-order-cli")
        verify_native(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError,
            json.JSONDecodeError) as error:
        print("ROUND075_MANIFEST_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError)
               else type(error).__name__)[:240], file=sys.stderr)
        sys.exit(2)
