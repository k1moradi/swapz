#!/usr/bin/env python3
"""Extend only a verified Round064 composed tree with pinned native DM core C."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import runpy

PIN = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
ORIGINAL = {'drivers/md/dm.c': '1881d86111fb2e655893ad898cf21b88f0e4e7f3',
            'drivers/md/dm-core.h': 'a3b8ad6e1c42def591694cb304994c2b8d5ca301',
            'include/linux/blk_types.h': '0cc09b975d8ffbd45ca3dc47533a71f8e8164de6'}
FIXTURES = Path(__file__).resolve().parents[1] / 'runtime/native/fixtures'
GUARD = r'''#if defined(SWAPZ_ROUND065_ORIGINAL_DM_TABLE_TEST) && \
    defined(SWAPZ_ROUND064_ORIGINAL_SLOT_TARGET_TEST) && \
    defined(SWAPZ_ROUND063_ORIGINAL_DM_OWNER_TEST) && \
    defined(SWAPZ_ROUND056_PREERASE_SINGLE_OWNER_TEST) && \
    defined(SWAPZ_ROUND032_BIO_COPY_VIEW_CI_ONLY) && \
    defined(SWAPZ_ROUND031_MM_BIO_SOURCE) && \
    defined(SWAPZ_ROUND028_SLOT_EPOCH_SOURCE) && \
    defined(SWAPZ_ROUND025_SIDEBAND_CI_ONLY) && defined(CONFIG_SWAP)''' + '\n'


def guarded(source):
    return GUARD + source + '\n#endif /* Round065 staged test only */\n'


def replace(text, anchor, replacement, label):
    if text.count(anchor) != 1:
        raise ValueError('anchor:' + label)
    return text.replace(anchor, replacement, 1)


def insert_before(text, anchor, insertion, label):
    return replace(text, anchor, insertion + anchor, label)


def insert_after(text, anchor, insertion, label):
    return replace(text, anchor, anchor + insertion, label)


def fragment(name):
    return (FIXTURES / ('round065-original-' + name + '.cfrag')).read_text()


def compose(path, text):
    if path == 'block/bio.c':
        text = insert_before(text, 'struct swapz_ci_owned_payload {\n',
                             guarded(fragment('table-state')), 'owner-state-definition')
        text = insert_after(text, '\tbool round064_route_bound;\n',
                            guarded('\tstruct swapz_round065_table_state round065_table;'), 'owner-state-field')
        text = insert_before(text, '\towner->round064_route_bound = true;\n',
                             guarded('\towner->round065_table.parent = bio;'), 'original-parent-bind')
        return text + '\n' + guarded(fragment('table-owner') + fragment('table-kunit'))
    if path == 'include/linux/bio.h':
        return insert_before(text, '#endif /* __LINUX_BIO_H */', guarded('''struct dm_target;
void swapz_round065_original_table_select(struct bio *parent, u64 incarnation);
bool swapz_round065_original_table_matches(const struct swapz_ci_owned_payload *owner,
        const struct bio *parent, const struct bio *clone, u64 incarnation);
bool swapz_round065_dm_owner_matches(struct dm_target *ti, struct bio *clone,
        const struct swapz_ci_owned_payload *owner);'''), 'native-guarded-prototypes')
    if path == 'drivers/md/dm-core.h':
        return insert_after(text, 'struct dm_table {\n',
                            guarded('\tu64 swapz_round065_incarnation;'), 'native-table-generation')
    if path == 'drivers/md/dm.c':
        text = insert_before(text, 'static void __map_bio(struct bio *clone)\n',
                             guarded(fragment('dm-core')), 'native-core-match-helper')
        text = insert_before(text, '\trcu_assign_pointer(md->map, (void *)t);\n',
                             guarded('\tWRITE_ONCE(t->swapz_round065_incarnation,\n\t\t   swapz_round065_next_incarnation());'), 'actual-table-publication')
        return insert_before(text, '\tdm_split_and_process_bio(md, map, bio);\n',
                             guarded('''\t/* First dispatched selection, NOT a suspended/deferred attempt. */
\tif (bio->bi_swapz_ci_sideband)
\t\tswapz_round065_original_table_select(bio,
\t\t\t\tREAD_ONCE(map->swapz_round065_incarnation));'''), 'actual-first-dispatch')
    raise ValueError('unexpected path')


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()



def verify_and_plan(original_files: dict[str, bytes], pristine_files: dict[str, bytes],
                    aggregate: dict, inherited: dict | None) -> tuple[dict[str, bytes], list[dict]]:
    """No writes; independently reconstruct every permitted inherited core byte."""
    if aggregate.get("source_sha", aggregate.get("original_sha")) != PIN:
        raise ValueError("base-manifest-pin")
    if aggregate.get("source_mapped_authenticated") is not False and inherited is not None:
        raise ValueError("base-authority-not-disabled")

    for path, blob in ORIGINAL.items():
        if path not in pristine_files or git_blob(pristine_files[path]) != blob:
            raise ValueError("pristine-git-blob:" + path)
    entries = aggregate.get("changed_paths")
    if not isinstance(entries, list):
        raise ValueError("base-manifest-paths")
    verified = set()
    for item in entries:
        path = item.get("path")
        if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("invalid-base-path")
        expected = item.get("staged_sha256", item.get("sha256"))
        if path in verified or path not in original_files or sha(original_files[path]) != expected:
            raise ValueError("base-manifest-postimage:" + path)
        verified.add(path)
    if not {"block/bio.c", "include/linux/bio.h"}.issubset(verified):
        raise ValueError("missing-composed-bio")

    previous_dm = original_files["drivers/md/dm.c"]
    if inherited is None:
        if "inherited70_manifest" in aggregate or (
                previous_dm != pristine_files["drivers/md/dm.c"]):
            raise ValueError("pristine-core-blob:drivers/md/dm.c")
    else:
        expected_owned = {"block/bio.c", "include/linux/bio.h",
                          "include/linux/blk_types.h", "drivers/md/dm.c"}
        if (inherited.get("original_sha") != PIN or
                inherited.get("inherited_original_verified") is not True or
                inherited.get("positive_source_target_authorization") is not False or
                inherited.get("default_guard") != "SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST" or
                set(inherited.get("own_changed_paths", [])) != expected_owned or
                not expected_owned.issubset(verified)):
            raise ValueError("inherited-manifest-lineage")
        original_clone_stager = runpy.run_path(
            str(Path(__file__).with_name("round056-original-clone-stage.py")),
            run_name="round066_clone_renderer")
        expected_dm = original_clone_stager["render_dm"](
            pristine_files["drivers/md/dm.c"].decode()).encode()
        if previous_dm != expected_dm or inherited.get("original_dm_sha256") != sha(expected_dm):
            raise ValueError("inherited-dm-postimage")

        # Rebuild the Round056 blk_types postimage from the exact original
        # pinned BIO header and the already used combined Round066 ancestors.
        original_composer = runpy.run_path(
            str(Path(__file__).with_name("stage-pinned-linux-zswap-composed.py")),
            run_name="round066_original_bio_renderer")
        previous_bio_header = original_composer["compose_postimage"](
            "include/linux/blk_types.h", pristine_files["include/linux/blk_types.h"])
        expected_bio_header = original_clone_stager["render_blk_types"](
            previous_bio_header.decode()).encode()
        if (original_files["include/linux/blk_types.h"] != expected_bio_header or
                inherited.get("original_blk_types_sha256") != sha(expected_bio_header)):
            raise ValueError("inherited-blk-types-postimage")

    for path in ("drivers/md/dm-core.h",):
        if original_files[path] != pristine_files[path]:
            raise ValueError("pristine-core-blob:" + path)
    planned, records = {}, []
    for path in ("block/bio.c", "include/linux/bio.h",
                 "drivers/md/dm.c", "drivers/md/dm-core.h"):
        old = original_files[path]
        if path not in verified and path not in ORIGINAL:
            raise ValueError("missing-composed-base:" + path)
        new = compose(path, old.decode()).encode()
        if new == old:
            raise ValueError("unchanged:" + path)
        planned[path] = new
        records.append({"path": path, "base_sha256": sha(old),
                        "staged_sha256": sha(new),
                        "pristine_blob": ORIGINAL.get(path),
                        "inherited_round056_dm": bool(inherited) if path == "drivers/md/dm.c" else False})
    return planned, records



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux-root', type=Path, required=True)
    parser.add_argument('--base-manifest', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    root = args.linux_root
    if subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip() != PIN:
        raise ValueError('original-commit')
    base = json.loads(args.base_manifest.read_text())
    inherited = None
    if "inherited70_manifest" in base:
        expected_path = args.base_manifest.with_name(
            args.base_manifest.stem + "-original70.json").resolve()
        if base["inherited70_manifest"] != str(expected_path) or not expected_path.is_file():
            raise ValueError("inherited-manifest-missing-or-mismatched")
        inherited = json.loads(expected_path.read_text())
        expected_composer_path = args.base_manifest.with_name(
            args.base_manifest.stem + "-original70-inherited66.json").resolve()
        if inherited.get("inherited66_composer_manifest") != str(expected_composer_path) or \
                not expected_composer_path.is_file():
            raise ValueError("inherited-composer-manifest-missing-or-mismatched")
        composer_manifest = json.loads(expected_composer_path.read_text())
        if composer_manifest.get("source_sha") != PIN or \
                composer_manifest.get("original_source_verified") is not True:
            raise ValueError("inherited-composer-manifest-pin")
    entries = base.get("changed_paths")
    if not isinstance(entries, list):
        raise ValueError("base-manifest-paths")
    paths = set()
    for item in entries:
        path = item.get("path")
        if not isinstance(path, str) or path.startswith("/") or ".." in Path(path).parts:
            raise ValueError("invalid-base-path")
        paths.add(path)
    paths.update(("block/bio.c", "include/linux/bio.h", *ORIGINAL))
    original_files = {path: (root / path).read_bytes() for path in paths}
    # Git HEAD is pinned before trusting any worktree file or manifest hash.
    pristine_files = {path: subprocess.check_output(
        ["git", "-C", str(root), "show", "HEAD:" + path]) for path in ORIGINAL}
    planned, records = verify_and_plan(
        original_files, pristine_files, base, inherited)
    for path, content in planned.items():
        (root / path).write_bytes(content)
    for item in records:
        if sha((root / item['path']).read_bytes()) != item['staged_sha256']:
            raise ValueError('postimage:' + item['path'])
    args.manifest.write_text(json.dumps({'original_sha': PIN, 'staged_modified': True,
        'source_mapped_authenticated': False, 'base_manifest_sha256': sha(args.base_manifest.read_bytes()),
        'changed_paths': records}, indent=2) + '\n')
    print('ROUND065_PINNED_DM_CORE_2_BLOBS_AND_COMPOSED_BASE_POSTIMAGES_PASS NO_AUTH')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        # Error classes and bounded stable labels only; no absolute paths.
        print('ROUND065_STAGE_FIRST_ERROR ' + (str(error) if isinstance(error, ValueError) else type(error).__name__)[:200])
        raise SystemExit(2) from None
