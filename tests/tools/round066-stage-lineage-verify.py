#!/usr/bin/env python3
"""Test exact pinned Round056/058 -> Round065 native staging with no writes."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
HERE = Path(__file__).resolve().parent
SOURCE = runpy.run_path(str(HERE / "round065-stage-original-dm-table.py"),
                        run_name="round066_stage_lineage_test")
verify_and_plan = SOURCE["verify_and_plan"]
sha = SOURCE["sha"]
ORIGINAL = SOURCE["ORIGINAL"]


def first_error(label: str):
    raise SystemExit("ROUND066_STAGE_FIRST_ERROR " + label)


def reject(label, source, pristine, base, inherited, cause):
    retained = source.copy()
    try:
        verify_and_plan(source, pristine, base, inherited)
    except (ValueError, KeyError) as error:
        if str(error) != cause:
            first_error(label + ":wrong-cause:" + str(error)[:100])
    else:
        first_error(label + ":accepted")
    if source != retained:
        first_error(label + ":partial-mutation")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--mode", choices=("inherited", "pristine"), required=True)
    args = parser.parse_args()
    root = args.linux_root
    if subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                               text=True).strip() != PIN:
        first_error("unverified-pin")
    base = json.loads(args.base_manifest.read_text())
    paths = {item["path"] for item in base["changed_paths"]}
    paths.update(("block/bio.c", "include/linux/bio.h", *ORIGINAL))
    sources = {path: (root / path).read_bytes() for path in paths}
    pristine = {path: subprocess.check_output(
        ["git", "-C", str(root), "show", "HEAD:" + path]) for path in ORIGINAL}
    inherited = None
    if args.mode == "inherited":
        manifest_path = args.base_manifest.with_name(
            args.base_manifest.stem + "-original70.json")
        if base.get("inherited70_manifest") != str(manifest_path.resolve()):
            first_error("inherited-path")
        inherited = json.loads(manifest_path.read_text())
        if not {"drivers/md/dm.c", "include/linux/blk_types.h"}.issubset(paths):
            first_error("aggregate-missing-inherited")
    else:
        if "inherited70_manifest" in base:
            first_error("unexpected-inherited-route")
    before = sources.copy()
    planned, records = verify_and_plan(sources, pristine, base, inherited)
    if sources != before or len(planned) != 4 or len(records) != 4:
        first_error("base-plan-mutated")
    staged_dm = planned["drivers/md/dm.c"].decode()
    for anchor in ("swapz_round065_original_table_select",
                   "swapz_round065_dm_owner_matches",
                   "swapz_round065_next_incarnation",
                   "swapz_round065_incarnation"):
        if anchor not in staged_dm:
            first_error("missing-native-core:" + anchor)
    if inherited:
        for anchor in ("clone->bi_round056_candidate = false;",
                       "Suspended/requeued original BIO cannot reuse prior target witness"):
            if anchor not in staged_dm:
                first_error("inherited-hook-lost")

    failures = 0
    changed = copy.deepcopy(base)
    changed["original_sha"] = "f" * 40
    changed["source_sha"] = "f" * 40
    reject("pin", sources, pristine, changed, inherited, "base-manifest-pin")
    failures += 1

    broken_pristine = pristine.copy()
    broken_pristine["drivers/md/dm.c"] += b"/* mutated pinned blob */"
    reject("pristine-blob", sources, broken_pristine, base, inherited,
           "pristine-git-blob:drivers/md/dm.c")
    failures += 1

    tampered = sources.copy()
    tampered["block/bio.c"] += b"/* injected */"
    reject("dirty-composed", tampered, pristine, base, inherited,
           "base-manifest-postimage:block/bio.c")
    failures += 1

    bad = copy.deepcopy(base)
    bad["changed_paths"].append(copy.deepcopy(bad["changed_paths"][0]))
    reject("duplicate-manifest", sources, pristine, bad, inherited,
           "base-manifest-postimage:" + bad["changed_paths"][0]["path"])
    failures += 1

    bad = copy.deepcopy(base)
    bad["changed_paths"] = [item for item in bad["changed_paths"]
                            if item["path"] != "block/bio.c"]
    reject("missing-source", sources, pristine, bad, inherited,
           "missing-composed-bio")
    failures += 1

    # A rejected second-stage attempt must not change any file. It cannot
    # accept the already staged bytes using the old pre-stage manifest.
    already_staged = sources | planned
    reject("double-stage", already_staged, pristine, base, inherited,
           "base-manifest-postimage:block/bio.c")
    failures += 1

    if inherited:
        reject("missing-inherited-manifest", sources, pristine, base, None,
               "pristine-core-blob:drivers/md/dm.c")
        failures += 1
        bad = copy.deepcopy(inherited)
        bad["original_dm_sha256"] = "0" * 64
        reject("forged-inherited-hash", sources, pristine, base, bad,
               "inherited-dm-postimage")
        failures += 1
        bad = copy.deepcopy(inherited)
        bad["own_changed_paths"].remove("drivers/md/dm.c")
        reject("inherited-unlisted", sources, pristine, base, bad,
               "inherited-manifest-lineage")
        failures += 1
        for path, key, cause in (
            ("drivers/md/dm.c", "original_dm_sha256", "inherited-dm-postimage"),
            ("include/linux/blk_types.h", "original_blk_types_sha256", "inherited-blk-types-postimage"),
        ):
            tampered = sources.copy()
            tampered[path] += b"/* malicious postimage with forged manifest */"
            bad_base = copy.deepcopy(base)
            for entry in bad_base["changed_paths"]:
                if entry["path"] == path:
                    entry["sha256"] = sha(tampered[path])
            bad_inherited = copy.deepcopy(inherited)
            bad_inherited[key] = sha(tampered[path])
            reject("forged-double-sha-" + path, tampered, pristine,
                   bad_base, bad_inherited, cause)
            failures += 1
        bad_base = copy.deepcopy(base)
        bad_base["changed_paths"] = [entry for entry in bad_base["changed_paths"]
                                     if entry["path"] != "drivers/md/dm.c"]
        reject("aggregate-missing-dm", sources, pristine, bad_base, inherited,
               "inherited-manifest-lineage")
        failures += 1
    else:
        modified = sources.copy()
        modified["drivers/md/dm.c"] += b"/* unknown dirty native core */"
        reject("dirty-pristine", modified, pristine, base, None,
               "pristine-core-blob:drivers/md/dm.c")
        failures += 1
        tampered = sources.copy()
        tampered["drivers/md/dm-core.h"] += b"/* unknown native core */"
        reject("dirty-core-header", tampered, pristine, base, None,
               "pristine-core-blob:drivers/md/dm-core.h")
        failures += 1
    print(f"ROUND066_REAL_PINNED_{args.mode.upper()}_LINEAGE_PASS "
          f"paths={len(base['changed_paths'])} rejected={failures} "
          "preimage_and_inherited_hooks=VERIFIED no_partial_writes=1 AUTH0")


if __name__ == "__main__":
    main()
