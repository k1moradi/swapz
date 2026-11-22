#!/usr/bin/env python3
"""Stage original pinned native zswap STORED KUnit without partial publication.

Requires the existing Round058 original MM/BIO composer and manifest. The
default kernel and product C are unchanged; no imported path becomes active.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
ZSWAP_PATH = "mm/zswap.c"
FIXTURE = (Path(__file__).resolve().parents[1] /
           "runtime/native/fixtures/round069-original-zswap-stored-source.cfrag")

def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def blob_sha(value: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" + value).hexdigest()

def plan(files: dict[str, bytes], original: bytes, manifest: dict,
         fixture: bytes) -> bytes:
    if blob_sha(original) != ORIGINAL_BLOB:
        raise ValueError("pristine-original-mm-zswap-git-blob")
    if manifest.get("original_sha") != PIN or \
       manifest.get("source_mapped_authenticated") is not False:
        raise ValueError("original-manifest-pin-auth")
    records = manifest.get("changed_paths")
    if not isinstance(records, list):
        raise ValueError("original-postimage-record-list")
    seen: set[str] = set()
    for record in records:
        path = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path, str) or path.startswith("/") or \
           ".." in Path(path).parts or path in seen or path not in files or \
           sha256(files[path]) != record.get("sha256"):
            raise ValueError("original-postimage-or-duplicate")
        seen.add(path)
    if not {"mm/zswap.c", "mm/page_io.c", "mm/swapfile.c",
            "block/bio.c"}.issubset(seen):
        raise ValueError("required-original-source-missing")
    if fixture.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_BEGIN") != 1 or \
       fixture.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_END */") != 1 or \
       fixture.count(b"kunit_test_suite(swapz_round069_native_suite);") != 1:
        raise ValueError("round069-test-source-markers")
    source = files[ZSWAP_PATH]
    for anchor in (b"struct zswap_entry {",
                   b"swapz_round028_allocation_epoch",
                   b"swapz_round031_mm_bio_create(entry, swpentry, tree, offset)",
                   b"entry != xa_load(tree, offset)",
                   b"zswap_decompress(entry, folio)",
                   b"xa_erase(tree, offset)",
                   b"zswap_entry_free(entry)",
                   b"zs_obj_read_sg_begin("):
        if anchor not in source:
            raise ValueError("inherited-native-source-anchor:" + anchor.decode())
    if b"ROUND069_ORIGINAL_STORED_SOURCE_BEGIN" in source:
        raise ValueError("original-source-double-stage")
    return source.rstrip(b"\n") + b"\n\n" + fixture

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    linux = args.linux_root
    if subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"],
                               text=True).strip() != PIN:
        raise ValueError("original-commit-pin")
    original = subprocess.check_output(
        ["git", "-C", str(linux), "show", "HEAD:" + ZSWAP_PATH])
    manifest = json.loads(args.base_manifest.read_text())
    records = manifest.get("changed_paths")
    if not isinstance(records, list):
        raise ValueError("original-postimage-record-list")
    paths = {record["path"] for record in records if isinstance(record, dict)
             and isinstance(record.get("path"), str)}
    files = {path: (linux / path).read_bytes() for path in paths}
    fixture = FIXTURE.read_bytes()
    generated = plan(files, original, manifest, fixture)
    if args.verify_only:
        mutated_source = dict(files)
        mutated_source[ZSWAP_PATH] += b"tamper"
        second_source = dict(files)
        second_source[ZSWAP_PATH] = generated
        second_manifest = json.loads(json.dumps(manifest))
        for record in second_manifest["changed_paths"]:
            if record["path"] == ZSWAP_PATH:
                record["sha256"] = sha256(generated)
        duplicate = json.loads(json.dumps(manifest))
        duplicate["changed_paths"].append(duplicate["changed_paths"][0])
        rejected = (
            (files, original + b"tamper", manifest,
             "pristine-original-mm-zswap-git-blob"),
            (files, original, dict(manifest, original_sha="0" * 40),
             "original-manifest-pin-auth"),
            (mutated_source, original, manifest,
             "original-postimage-or-duplicate"),
            (second_source, original, second_manifest,
             "original-source-double-stage"),
            (files, original, duplicate,
             "original-postimage-or-duplicate"),
        )
        for source, pristine, claimed, wanted in rejected:
            before = source.copy()
            try:
                plan(source, pristine, claimed, fixture)
            except ValueError as error:
                if str(error) != wanted:
                    raise ValueError("negative-wrong-first-error:" + str(error)) from error
            else:
                raise ValueError("original-stage-negative-survived:" + wanted)
            if source != before:
                raise ValueError("original-stage-negative-partial-write")
        print("ROUND069_ORIGINAL_NATIVE_STAGE_PLAN_PASS negatives=5 no_partial_writes=1")
        return
    (linux / ZSWAP_PATH).write_bytes(generated)
    if sha256((linux / ZSWAP_PATH).read_bytes()) != sha256(generated):
        raise ValueError("original-source-postimage-readback")
    args.manifest.write_text(json.dumps({
        "original_sha": PIN,
        "source_mapped_authenticated": False,
        "original_zswap_git_blob": ORIGINAL_BLOB,
        "inherited_manifest_sha256": sha256(args.base_manifest.read_bytes()),
        "changed_paths": [{"path": ZSWAP_PATH,
                           "base_sha256": sha256(files[ZSWAP_PATH]),
                           "staged_sha256": sha256(generated)}]
    }, indent=2) + "\n")
    print("ROUND069_ORIGINAL_PINNED_ZSWAP_KUNIT_STAGED NO_AUTH")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("ROUND069_ORIGINAL_STAGE_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError) else type(error).__name__)[:180])
        raise SystemExit(2) from None
