#!/usr/bin/env python3
"""Extend only a verified Round064 composed tree with pinned native DM core C."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
ORIGINAL = {'drivers/md/dm.c': '1881d86111fb2e655893ad898cf21b88f0e4e7f3',
            'drivers/md/dm-core.h': 'a3b8ad6e1c42def591694cb304994c2b8d5ca301'}
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
    if base.get('source_sha', base.get('original_sha')) != PIN:
        raise ValueError('base-manifest-pin')
    verified = {}
    for item in base['changed_paths']:
        path = item['path']
        expected = item.get('staged_sha256', item.get('sha256'))
        data = (root / path).read_bytes()
        if sha(data) != expected or path in verified:
            raise ValueError('base-manifest-postimage:' + path)
        verified[path] = expected
    paths = ('block/bio.c', 'include/linux/bio.h', *ORIGINAL)
    planned = {}
    records = []
    for path in paths:
        old = (root / path).read_bytes()
        if path in ORIGINAL:
            if git_blob(old) != ORIGINAL[path]:
                raise ValueError('pristine-core-blob:' + path)
        elif path not in verified:
            raise ValueError('missing-composed-base:' + path)
        new = compose(path, old.decode()).encode()
        if old == new:
            raise ValueError('unchanged:' + path)
        planned[path] = new
        records.append({'path': path, 'base_sha256': sha(old), 'staged_sha256': sha(new),
                        'pristine_blob': ORIGINAL.get(path)})
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
