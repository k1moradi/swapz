#!/usr/bin/env python3
"""Append source-only NO_AUTH provenance KUnit to the exact original Linux pin."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOB = "ae19e301fced7e357a4c7587dfdd6abb890b9163"
SOURCE_PATH = "mm/zswap.c"
FIXTURE = (Path(__file__).resolve().parents[1] /
           "runtime/native/fixtures/round071-original-zswap-provenance.cfrag")

def sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()

def git_blob_sha(contents: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(contents)).encode() + b"\0" +
                        contents).hexdigest()

def plan(pristine: bytes, current: bytes, manifest: dict,
         fixture: bytes) -> bytes:
    if git_blob_sha(pristine) != ORIGINAL_BLOB:
        raise ValueError("pristine-original-zswap-blob")
    if manifest.get("original_sha") != PIN or \
       manifest.get("original_zswap_git_blob") != ORIGINAL_BLOB or \
       manifest.get("source_mapped_authenticated") is not False:
        raise ValueError("inherited-original-pin-or-auth")
    records = manifest.get("changed_paths")
    if not isinstance(records, list) or len(records) != 1 or \
       records[0].get("path") != SOURCE_PATH or \
       records[0].get("staged_sha256") != sha256(current):
        raise ValueError("inherited-postimage-integrity")
    expected_native_anchors = (
        b"static bool zswap_store_page(struct folio *folio",
        b"old = xa_store(swap_zswap_tree(page_swpentry)",
        b"entry->swpentry = page_swpentry;",
        b"zswap_lru_add(entry);",
        b"static int zswap_writeback_entry(struct zswap_entry *entry,",
        b"si = get_swap_device(swpentry);",
        b"folio = __swap_cache_alloc_folio(swpentry,",
        b"if (entry != xa_load(tree, offset)) {",
        b"if (!zswap_decompress(entry, folio)) {",
        b"xa_erase(tree, offset);",
        b"__swap_writeout(&ctx, folio);",
        b"VM_WARN_ON_ONCE(!folio_test_swapcache(folio));",
    )
    if any(anchor not in pristine for anchor in expected_native_anchors):
        raise ValueError("pinned-original-store-writeback-prerequisite")
    if not (pristine.index(b"si = get_swap_device(swpentry);") <
            pristine.index(b"folio = __swap_cache_alloc_folio(swpentry,") <
            pristine.index(b"if (entry != xa_load(tree, offset)) {") <
            pristine.index(b"__swap_writeout(&ctx, folio);")):
        raise ValueError("pinned-original-writeback-order")
    if current.count(b"/* ROUND069_ORIGINAL_STORED_SOURCE_BEGIN") != 1 or \
       current.count(b"kunit_test_suite(swapz_round069_native_suite);") != 1 or \
       b"swapz_round028_allocation_epoch" not in current:
        raise ValueError("inherited-native-zswap-source-anchor")
    if b"ROUND071_ORIGINAL_ZSWAP_PROVENANCE_BEGIN" in current:
        raise ValueError("provenance-double-stage")
    if fixture.count(b"/* ROUND071_ORIGINAL_ZSWAP_PROVENANCE_BEGIN") != 1 or \
       fixture.count(b"/* ROUND071_ORIGINAL_ZSWAP_PROVENANCE_END */") != 1 or \
       fixture.count(b"kunit_test_suite(swapz_round071_provenance_native_suite);") != 1:
        raise ValueError("provenance-fixture-markers")
    return current.rstrip(b"\n") + b"\n\n" + fixture

def run_negative_tests(pristine: bytes, current: bytes, manifest: dict,
                       fixture: bytes) -> None:
    modified = json.loads(json.dumps(manifest))
    modified["changed_paths"][0]["staged_sha256"] = "0" * 64
    cases = (
        (pristine + b"tamper", current, manifest, fixture,
         "pristine-original-zswap-blob"),
        (pristine, current, dict(manifest, original_sha="0" * 40), fixture,
         "inherited-original-pin-or-auth"),
        (pristine, current, dict(manifest, source_mapped_authenticated=True),
         fixture, "inherited-original-pin-or-auth"),
        (pristine, current, modified, fixture,
         "inherited-postimage-integrity"),
        (pristine, current + b"tamper", manifest, fixture,
         "inherited-postimage-integrity"),
        (pristine, current, manifest, fixture.replace(
            b"/* ROUND071_ORIGINAL_ZSWAP_PROVENANCE_END */",
            b"/* marker tampered */"), "provenance-fixture-markers"),
    )
    for source, staged, claimed, candidate, expected in cases:
        try:
            plan(source, staged, claimed, candidate)
        except ValueError as error:
            if str(error) != expected:
                raise ValueError("negative-wrong-first-error:" + str(error)) from error
        else:
            raise ValueError("negative-control-survived:" + expected)
    generated = plan(pristine, current, manifest, fixture)
    replacement = json.loads(json.dumps(manifest))
    replacement["changed_paths"][0]["staged_sha256"] = sha256(generated)
    try:
        plan(pristine, generated, replacement, fixture)
    except ValueError as error:
        if str(error) != "provenance-double-stage":
            raise ValueError("double-stage-wrong-first-error") from error
    else:
        raise ValueError("double-stage-survived")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    linux = arguments.linux_root
    head = subprocess.check_output(["git", "-C", str(linux), "rev-parse", "HEAD"],
                                   text=True).strip()
    if head != PIN:
        raise ValueError("original-kernel-commit-pin")
    pristine = subprocess.check_output(
        ["git", "-C", str(linux), "show", "HEAD:" + SOURCE_PATH])
    current = (linux / SOURCE_PATH).read_bytes()
    original_manifest = arguments.base_manifest.read_bytes()
    inherited_manifest = json.loads(original_manifest)
    fragment = FIXTURE.read_bytes()
    generated = plan(pristine, current, inherited_manifest, fragment)
    if arguments.verify_only:
        run_negative_tests(pristine, current, inherited_manifest, fragment)
        print("ROUND071_PROVENANCE_ORIGINAL_STAGE_NEGATIVES_PASS cases=7 "
              "no_partial_writes=1 source_auth=0")
        return
    (linux / SOURCE_PATH).write_bytes(generated)
    if (linux / SOURCE_PATH).read_bytes() != generated:
        raise ValueError("staged-original-postimage-readback")
    arguments.manifest.write_text(json.dumps({
        "original_sha": PIN,
        "original_zswap_git_blob": ORIGINAL_BLOB,
        "source_mapped_authenticated": False,
        "real_swapcache_source": "BLOCKED_NO_SWAP_DEVICE",
        "inherited_manifest_sha256": sha256(original_manifest),
        "changed_paths": [{"path": SOURCE_PATH,
                           "base_sha256": sha256(current),
                           "staged_sha256": sha256(generated)}],
    }, indent=2) + "\n")
    print("ROUND071_PROVENANCE_ORIGINAL_ZSWAP_STAGED NO_AUTH")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("ROUND071_PROVENANCE_STAGE_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError) else type(error).__name__)[:180])
        raise SystemExit(2) from None
