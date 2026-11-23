#!/usr/bin/env python3
"""Stage exact pristine original zswap source with a new no-device KUnit.

Only an ephemeral pinned Linux test checkout is modified, after complete
preflight; never creates a swap device, source hook, or production carrier.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

LINUX_PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
ORIGINAL_BLOBS = {
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/swapfile.c": "254ce86fa923e6b5f1fefda88c39315c4cc00642",
    "mm/swap.h": "d5bf21f517dceae58eb94fb0ce5f4e1fdc679409",
}
SOURCE_PATH = "mm/zswap.c"
FRAGMENT = (Path(__file__).resolve().parents[1] /
            "runtime/native/fixtures/round072-original-swapcache-provenance.cfrag")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git_blob_sha(value: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(value)).encode() + b"\0" +
                        value).hexdigest()


def plan(originals: dict[str, bytes], staged: bytes, inherited: dict,
         fragment: bytes) -> bytes:
    if any(git_blob_sha(originals.get(path, b"")) != wanted
           for path, wanted in ORIGINAL_BLOBS.items()):
        raise ValueError("original-pristine-blob-mismatch")
    if inherited.get("original_sha") != LINUX_PIN or \
       inherited.get("original_zswap_git_blob") != ORIGINAL_BLOBS[SOURCE_PATH] or \
       inherited.get("source_mapped_authenticated") is not False or \
       inherited.get("real_swapcache_source") != "BLOCKED_NO_SWAP_DEVICE":
        raise ValueError("original-inherited-pin-or-auth")
    records = inherited.get("changed_paths")
    if not isinstance(records, list) or len(records) != 1 or \
       not isinstance(records[0], dict) or \
       records[0].get("path") != SOURCE_PATH or \
       records[0].get("staged_sha256") != sha256(staged):
        raise ValueError("original-inherited-postimage-mismatch")
    zswap = originals[SOURCE_PATH]
    swapfile = originals["mm/swapfile.c"]
    swap_header = originals["mm/swap.h"]
    source_anchors = (
        b"static bool zswap_store_page(struct folio *folio",
        b"old = xa_store(swap_zswap_tree(page_swpentry)",
        b"entry->pool_idx = pool->idx;",
        b"zswap_lru_add(entry);",
        b"VM_WARN_ON_ONCE(!folio_test_swapcache(folio));",
        b"static int zswap_writeback_entry(struct zswap_entry *entry,",
        b"si = get_swap_device(swpentry);",
        b"folio = __swap_cache_alloc_folio(swpentry,",
        b"if (entry != xa_load(tree, offset)) {",
        b"zswap_entry_free(entry);",
        b"__swap_writeout(&ctx, folio);",
    )
    if any(anchor not in zswap for anchor in source_anchors):
        raise ValueError("original-zswap-lifecycle-anchor-missing")
    writeback = zswap.split(b"static int zswap_writeback_entry(struct zswap_entry *entry,", 1)[1]
    if not (writeback.index(b"si = get_swap_device(swpentry);") <
            writeback.index(b"folio = __swap_cache_alloc_folio(swpentry,") <
            writeback.index(b"if (entry != xa_load(tree, offset)) {") <
            writeback.index(b"if (!zswap_decompress(entry, folio)) {") <
            writeback.index(b"xa_erase(tree, offset);") <
            writeback.index(b"zswap_entry_free(entry);") <
            writeback.index(b"__swap_writeout(&ctx, folio);")):
        raise ValueError("original-writeback-lifetime-order-mismatch")
    if (b"struct swap_info_struct *get_swap_device(swp_entry_t entry)" not in swapfile or
        b"if (!entry.val)" not in swapfile or
        b"si = swap_entry_to_info(entry);" not in swapfile or
        b"if (!get_swap_device_info(si))" not in swapfile or
        b"if (offset >= si->max)" not in swapfile or
        b"if (!folio_test_swapcache(folio))" not in swap_header or
        b"folio_matches_swap_entry(const struct folio *folio," not in swap_header or
        b"- Hold a reference by get_swap_device()" not in swap_header):
        raise ValueError("original-device-and-folio-api-anchor-missing")
    if (staged.count(b"/* ROUND071_ORIGINAL_ZSWAP_PROVENANCE_BEGIN") != 1 or
        staged.count(b"kunit_test_suite(swapz_round071_provenance_native_suite);") != 1 or
        b"swapz_round028_allocation_epoch" not in staged):
        raise ValueError("inherited-native-source-missing")
    if b"ROUND072_ORIGINAL_SWAPCACHE_PROVENANCE_BEGIN" in staged:
        raise ValueError("original-provenance-double-stage")
    if (fragment.count(b"/* ROUND072_ORIGINAL_SWAPCACHE_PROVENANCE_BEGIN") != 1 or
        fragment.count(b"/* ROUND072_ORIGINAL_SWAPCACHE_PROVENANCE_END */") != 1 or
        fragment.count(b"kunit_test_suite(swapz_round072_native_swapcache_provenance_suite);") != 1):
        raise ValueError("original-provenance-fixture-marker")
    return staged.rstrip(b"\n") + b"\n\n" + fragment


def run_negative_controls(originals: dict[str, bytes], staged: bytes,
                          inherited: dict, fragment: bytes) -> None:
    wrong_original = dict(originals, **{SOURCE_PATH: originals[SOURCE_PATH] + b"tamper"})
    wrong_swapfile = dict(originals, **{"mm/swapfile.c": originals["mm/swapfile.c"] + b"tamper"})
    wrong_swap_header = dict(originals, **{"mm/swap.h": originals["mm/swap.h"] + b"tamper"})
    wrong_manifest = json.loads(json.dumps(inherited))
    wrong_manifest["changed_paths"][0]["staged_sha256"] = "0" * 64
    corrupted_marker = fragment.replace(
        b"/* ROUND072_ORIGINAL_SWAPCACHE_PROVENANCE_END */", b"/* broken */")
    cases = (
        (wrong_original, staged, inherited, fragment,
         "original-pristine-blob-mismatch"),
        (wrong_swapfile, staged, inherited, fragment,
         "original-pristine-blob-mismatch"),
        (wrong_swap_header, staged, inherited, fragment,
         "original-pristine-blob-mismatch"),
        (originals, staged, dict(inherited, original_sha="0" * 40), fragment,
         "original-inherited-pin-or-auth"),
        (originals, staged, dict(inherited, source_mapped_authenticated=True), fragment,
         "original-inherited-pin-or-auth"),
        (originals, staged, wrong_manifest, fragment,
         "original-inherited-postimage-mismatch"),
        (originals, staged + b"tamper", inherited, fragment,
         "original-inherited-postimage-mismatch"),
        (originals, staged, inherited, corrupted_marker,
         "original-provenance-fixture-marker"),
    )
    for pristine, postimage, manifest, candidate, expected in cases:
        try:
            plan(pristine, postimage, manifest, candidate)
        except ValueError as error:
            if str(error) != expected:
                raise ValueError("negative-first-error:" + str(error)) from error
        else:
            raise ValueError("negative-survived:" + expected)
    twice = plan(originals, staged, inherited, fragment)
    updated_manifest = json.loads(json.dumps(inherited))
    updated_manifest["changed_paths"][0]["staged_sha256"] = sha256(twice)
    try:
        plan(originals, twice, updated_manifest, fragment)
    except ValueError as error:
        if str(error) != "original-provenance-double-stage":
            raise ValueError("double-stage-first-error:" + str(error)) from error
    else:
        raise ValueError("duplicate-stage-survived")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true")
    arguments = parser.parse_args()
    root = arguments.linux_root
    current_head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if current_head != LINUX_PIN:
        raise ValueError("original-linux-commit-mismatch")
    originals = {path: subprocess.check_output([
        "git", "-C", str(root), "show", "HEAD:" + path]) for path in ORIGINAL_BLOBS}
    staged = (root / SOURCE_PATH).read_bytes()
    inherited_content = arguments.base_manifest.read_bytes()
    inherited = json.loads(inherited_content)
    fixture = FRAGMENT.read_bytes()
    staged_result = plan(originals, staged, inherited, fixture)
    if arguments.verify_only:
        run_negative_controls(originals, staged, inherited, fixture)
        print("ROUND072_ORIGINAL_SWAPCACHE_STAGE_NEGATIVES_PASS cases=9 "
              "original_blob_count=3 no_partial_writes=1 source_auth=0")
        return
    (root / SOURCE_PATH).write_bytes(staged_result)
    if (root / SOURCE_PATH).read_bytes() != staged_result:
        raise ValueError("original-staged-source-readback-mismatch")
    arguments.manifest.write_text(json.dumps({
        "original_sha": LINUX_PIN,
        "original_blobs": ORIGINAL_BLOBS,
        "source_mapped_authenticated": False,
        "original_swap_device_ref": "BLOCKED_NO_SWAP_DEVICE",
        "original_selected_stored_source": "NOT_AUTHENTICATED",
        "inherited_manifest_sha256": sha256(inherited_content),
        "changed_paths": [{"path": SOURCE_PATH,
                           "base_sha256": sha256(staged),
                           "staged_sha256": sha256(staged_result)}],
    }, indent=2) + "\n")
    print("ROUND072_ORIGINAL_SWAPCACHE_NATIVE_KUNIT_STAGED AUTH0 NO_SWAPON")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print("ROUND072_ORIGINAL_SWAPCACHE_STAGE_FIRST_ERROR " +
              (str(error) if isinstance(error, ValueError) else type(error).__name__)[:180])
        raise SystemExit(2) from None
