#!/usr/bin/env python3
"""Append test-only DM owner KUnit after verified pinned Round067 postimage.

Never changes upstream production C: the byte-identical dm-target.c is staged
as a NON-BUILT review source, not an activated DM target or source attestation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PIN = 'c339f4010dea8b0d754f84ace70cd1b089878ef8'
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'tests/runtime/native/fixtures/round071-original-dm-upper-owner.cfrag'
PRODUCT = ROOT / 'src/kernel/dm-target.c'
DM_PATH = 'drivers/md/dm.c'
PRODUCT_STAGE = 'drivers/md/dm-swapz-round071-review-only.c'
PINNED_ORIGINAL_DM_BLOB = '1881d86111fb2e655893ad898cf21b88f0e4e7f3'
PINNED_PRODUCT_BLOB = 'f1cab252cd990190646c82da81378d1563475826'
BEGIN = b'/* ROUND071_ORIGINAL_DM_UPPER_OWNER_BEGIN'
END = b'/* ROUND071_ORIGINAL_DM_UPPER_OWNER_END */'


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def blob(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def plan(files: dict[str, bytes], pristine_dm: bytes, base: dict,
         fragment: bytes, product: bytes) -> dict[str, bytes]:
    if base.get('original_sha') != PIN or base.get('staged_modified') is not True or \
            base.get('source_mapped_authenticated') is not False:
        raise ValueError('base-pin-or-noauth')
    if blob(pristine_dm) != PINNED_ORIGINAL_DM_BLOB:
        raise ValueError('pristine-original-dm-blob')
    if blob(product) != PINNED_PRODUCT_BLOB:
        raise ValueError('production-dm-target-source-drift')
    records = base.get('changed_paths')
    if not isinstance(records, list) or len(records) != 1 or \
            records[0].get('path') != DM_PATH or \
            digest(files[DM_PATH]) != records[0].get('staged_sha256'):
        raise ValueError('base-manifest-postimage')
    current = files[DM_PATH]
    if (b'kunit_test_suite(swapz_round067_native_dm_runtime_suite);' not in current or
            b'ROUND067_ORIGINAL_DM_RUNTIME_END' not in current):
        raise ValueError('prior-original-native-suite-missing')
    if BEGIN in current or END in current or PRODUCT_STAGE in files:
        raise ValueError('double-stage')
    if (fragment.count(BEGIN) != 1 or fragment.count(END) != 1 or
            fragment.count(b'kunit_test_suite(swapz_round071_native_upper_suite);') != 1 or
            fragment.count(b'#define SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE 0') != 1 or
            fragment.count(b'/* ROUND072_SELECTED_SOURCE_BEGIN */') != 1 or
            fragment.count(b'/* ROUND072_SELECTED_SOURCE_END */') != 1 or
            fragment.count(b'KUNIT_CASE(swapz_round072_native_current_table_negative_kunit)') != 1):
        raise ValueError('test-fixture-drift')
    return {DM_PATH: current + b'\n' + fragment, PRODUCT_STAGE: product}


def verify_negatives(files: dict[str, bytes], pristine_dm: bytes, base: dict,
                     fragment: bytes, product: bytes, output: dict[str, bytes]) -> None:
    mutants = []
    mutants.append((files, pristine_dm, dict(base, original_sha='0' * 40),
                    fragment, product, 'base-pin-or-noauth'))
    mutants.append((files, pristine_dm, dict(base, source_mapped_authenticated=True),
                    fragment, product, 'base-pin-or-noauth'))
    altered_files = dict(files, **{DM_PATH: files[DM_PATH] + b'/* unexpected */'})
    mutants.append((altered_files, pristine_dm, base, fragment, product,
                    'base-manifest-postimage'))
    mutants.append((files, pristine_dm + b'/* tamper */', base, fragment,
                    product, 'pristine-original-dm-blob'))
    mutants.append((files, pristine_dm, base, fragment, product + b'/* tamper */',
                    'production-dm-target-source-drift'))
    mutants.append((files, pristine_dm, base, fragment.replace(
                    b'#define SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE 0',
                    b'#define SWAPZ_ROUND071_SOURCE_AUTH_ACTIVE 1'), product,
                    'test-fixture-drift'))
    mutants.append((files, pristine_dm, base, fragment.replace(
                    b'/* ROUND072_SELECTED_SOURCE_BEGIN */',
                    b'/* ROUND072_SELECTED_SOURCE_DISABLED */'), product,
                    'test-fixture-drift'))
    replay = dict(files, **{DM_PATH: output[DM_PATH], PRODUCT_STAGE: product})
    replay_base = json.loads(json.dumps(base))
    replay_base['changed_paths'][0]['staged_sha256'] = digest(output[DM_PATH])
    mutants.append((replay, pristine_dm, replay_base, fragment, product, 'double-stage'))
    for source, original, manifest, fixture, original_product, expected in mutants:
        snapshot = dict(source)
        try:
            plan(source, original, manifest, fixture, original_product)
        except ValueError as error:
            if str(error) != expected:
                raise ValueError('incorrect-first-negative:' + str(error)) from error
        else:
            raise ValueError('mutation-survived:' + expected)
        if source != snapshot:
            raise ValueError('negative-partial-write')
    print('ROUND071_PINNED_STAGE_NEGATIVE_PASS refused=8 no_partial_writes=1 NO_AUTH')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--linux-root', required=True, type=Path)
    parser.add_argument('--base-manifest', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if subprocess.check_output(['git', '-C', str(args.linux_root),
                                'rev-parse', 'HEAD'], text=True).strip() != PIN:
        raise ValueError('original-linux-pin')
    base = json.loads(args.base_manifest.read_text())
    paths = {record['path'] for record in base.get('changed_paths', [])}
    paths.add(DM_PATH)
    files = {path: (args.linux_root / path).read_bytes() for path in paths}
    original_dm = subprocess.check_output(['git', '-C', str(args.linux_root),
                                           'show', 'HEAD:' + DM_PATH])
    product, fragment = PRODUCT.read_bytes(), FIXTURE.read_bytes()
    output = plan(files, original_dm, base, fragment, product)
    if args.verify_only:
        verify_negatives(files, original_dm, base, fragment, product, output)
        return
    for path, content in output.items():
        destination = args.linux_root / path
        if path == PRODUCT_STAGE and destination.exists():
            raise ValueError('review-source-already-exists')
        destination.write_bytes(content)
        if destination.read_bytes() != content:
            raise ValueError('postimage-mismatch:' + path)
    args.manifest.write_text(json.dumps({
        'original_sha': PIN, 'source_mapped_authenticated': False,
        'staged_modified': True, 'production_source_compiled': False,
        'production_dm_target_unchanged': True,
        'base_manifest_sha256': digest(args.base_manifest.read_bytes()),
        'changed_paths': [dict(path=path, base_sha256=digest(files[path]) if path in files else None,
                               staged_sha256=digest(data)) for path, data in output.items()]
    }, sort_keys=True, indent=2) + '\n')
    print('ROUND071_ORIGINAL_DM_TEST_ONLY_STAGED original_pin=PASS product_byte_identity=PASS NO_AUTH')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print('ROUND071_STAGE_FIRST_ERROR ' + (str(error) if isinstance(error, ValueError)
                                               else type(error).__name__)[:210])
        raise SystemExit(2) from None
