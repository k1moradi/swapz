#!/usr/bin/env python3
"""Stage one test-only native KUnit suite on exact pinned Round065 DM postimage.

Both main source and all older stage manifests must already be verified. The
planner is read-only; failure never writes a partially staged original tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'runtime/native/fixtures/round067-original-dm-dispatch-runtime.cfrag'
DM_PATH = 'drivers/md/dm.c'
CORE_PATH = 'drivers/md/dm-core.h'
BLOB = {
    DM_PATH: '1881d86111fb2e655893ad898cf21b88f0e4e7f3',
    CORE_PATH: 'a3b8ad6e1c42def591694cb304994c2b8d5ca301',
}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_blob(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def plan(files: dict[str, bytes], pristine: dict[str, bytes], base: dict,
         fixture: bytes) -> bytes:
    if base.get('original_sha') != PIN or base.get('staged_modified') is not True or \
       base.get('source_mapped_authenticated') is not False:
        raise ValueError('base-manifest-authority-or-pin')
    for path, expected in BLOB.items():
        if path not in pristine or git_blob(pristine[path]) != expected:
            raise ValueError('pristine-original-blob:' + path)
    records = base.get('changed_paths')
    if not isinstance(records, list):
        raise ValueError('base-manifest-records')
    seen = set()
    for record in records:
        path = record.get('path')
        if not isinstance(path, str) or path.startswith('/') or '..' in Path(path).parts or \
           path in seen or path not in files or digest(files[path]) != record.get('staged_sha256'):
            raise ValueError('base-manifest-postimage')
        seen.add(path)
    if not {DM_PATH, CORE_PATH, 'block/bio.c', 'include/linux/bio.h'}.issubset(seen):
        raise ValueError('base-manifest-missing-native-owners')
    if (fixture.count(b'/* ROUND067_ORIGINAL_DM_RUNTIME_BEGIN') != 1 or
            fixture.count(b'/* ROUND067_ORIGINAL_DM_RUNTIME_END */') != 1 or
            fixture.count(b'kunit_test_suite(swapz_round067_native_dm_runtime_suite);') != 1):
        raise ValueError('test-only-runtime-source-drift')
    old = files[DM_PATH]
    for required in (b'swapz_round065_next_incarnation',
                     b'swapz_round065_original_table_select',
                     b'clone->bi_round056_candidate = false;',
                     b'Suspended/requeued original BIO cannot reuse prior target witness'):
        if required not in old:
            raise ValueError('missing-inherited-native-hook')
    if (b'ROUND067_ORIGINAL_DM_RUNTIME_BEGIN' in old or
            b'ROUND067_ORIGINAL_DM_RUNTIME_END' in old):
        raise ValueError('double-stage')
    return old + b'\n' + fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux-root', type=Path, required=True)
    parser.add_argument('--base-manifest', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = args.linux_root
    if subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                               text=True).strip() != PIN:
        raise ValueError('original-commit')
    base = json.loads(args.base_manifest.read_text())
    paths = {item['path'] for item in base.get('changed_paths', [])}
    paths.update(BLOB)
    files = {path: (root / path).read_bytes() for path in paths}
    pristine = {path: subprocess.check_output(['git', '-C', str(root), 'show',
                                              'HEAD:' + path]) for path in BLOB}
    new = plan(files, pristine, base, FIXTURE.read_bytes())
    # Negative plan cases use the actual fully staged original kernel bytes.
    if args.verify_only:
        rejected = 0
        cases = []
        altered_base = dict(base, original_sha='0' * 40)
        cases.append((files, pristine, altered_base, 'base-manifest-authority-or-pin'))
        altered_files = dict(files)
        altered_files[DM_PATH] += b'/* tamper */'
        cases.append((altered_files, pristine, base, 'base-manifest-postimage'))
        altered_files = dict(files)
        altered_files[DM_PATH] = new
        altered_base = json.loads(json.dumps(base))
        for record in altered_base['changed_paths']:
            if record['path'] == DM_PATH:
                record['staged_sha256'] = digest(new)
        cases.append((altered_files, pristine, altered_base, 'double-stage'))
        altered_pristine = dict(pristine)
        altered_pristine[DM_PATH] += b'/* tampered pristine */'
        cases.append((files, altered_pristine, base, 'pristine-original-blob:' + DM_PATH))
        altered_base = json.loads(json.dumps(base))
        altered_base['changed_paths'].append(altered_base['changed_paths'][0])
        cases.append((files, pristine, altered_base, 'base-manifest-postimage'))
        for source, pinned, manifest, error_name in cases:
            retained = source.copy()
            try:
                plan(source, pinned, manifest, FIXTURE.read_bytes())
            except ValueError as error:
                if str(error) != error_name:
                    raise ValueError('wrong-negative-cause') from error
            else:
                raise ValueError('negative-accepted')
            if retained != source:
                raise ValueError('rejected-partial-write')
            rejected += 1
        print('ROUND067_REAL_PINNED_STAGE_PLAN_PASS negatives=' + str(rejected) +
              ' no_partial_writes=1 NO_AUTH')
        return
    (root / DM_PATH).write_bytes(new)
    if digest((root / DM_PATH).read_bytes()) != digest(new):
        raise ValueError('postimage-write')
    args.manifest.write_text(json.dumps({
        'original_sha': PIN, 'staged_modified': True,
        'source_mapped_authenticated': False,
        'base_manifest_sha256': digest(args.base_manifest.read_bytes()),
        'changed_paths': [{'path': DM_PATH, 'base_sha256': digest(files[DM_PATH]),
                           'staged_sha256': digest(new),
                           'pristine_git_blob': BLOB[DM_PATH]}]}, indent=2) + '\n')
    print('ROUND067_NATIVE_TEST_ONLY_DM_RUNTIME_STAGED exact_original_pin=PASS NO_AUTH')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print('ROUND067_STAGE_FIRST_ERROR ' +
              (str(error) if isinstance(error, ValueError) else type(error).__name__)[:180])
        raise SystemExit(2) from None
