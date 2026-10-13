#!/usr/bin/env python3
"""Run matched three-way 80/20 size-class comparisons at QD8."""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/tmp/swapz-alpha8-evidence')
MATRIX = Path('/tmp/swapz-pr59-validation/reports/alpha8/scripts/run-ratio-matrix.py')
UNIFORM = ROOT / 'pr58-reference/sustained/fixtures/uniform'
CASES = {
    'c1031': ('uniform-1032-1024-pages.bin', 'uniform-1032-1024-class.bin'),
    'c2088': ('uniform-2089-1024-pages.bin', 'uniform-2089-1024-class.bin'),
    'c3499': ('uniform-3500-1024-pages.bin', 'uniform-3500-1024-class.bin'),
    'raw': ('uniform-raw-1024-pages.bin', 'uniform-raw-1024-class.bin'),
}


def main():
    result = {'source': 'uniform fixtures archived from PR #58 and SHA verified',
              'seeded_source_manifest': str(UNIFORM / 'uniform-fixtures-manifest.json'),
              'cases': []}
    for label, (pages, classes) in CASES.items():
        fixture = UNIFORM / pages
        classmap = UNIFORM / classes
        if not fixture.is_file() or not classmap.is_file():
            raise SystemExit(f'missing fixture for {label}')
        tag = f'matched5000-q8-rp20-{label}'
        cmd = [sys.executable, str(MATRIX), '--design', 'matched',
               '--repetitions', '3', '--qds', '8', '--iops', '5000',
               '--read-pct', '20', '--seconds', '30', '--warmup', '10',
               '--tag', tag, '--fixture', str(fixture),
               '--classmap', str(classmap)]
        start = time.time()
        p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        row = {'fixture_class': label, 'pages_path': str(fixture),
               'classmap_path': str(classmap), 'command': cmd,
               'started': start, 'ended': time.time(),
               'exit_code': p.returncode, 'stdout': p.stdout,
               'stderr': p.stderr}
        result['cases'].append(row)
        (ROOT / 'benchmark/matrix/sizeclass-orchestration.json').write_text(
            json.dumps(result, indent=2) + '\n')
        print(json.dumps({'fixture_class': label, 'exit_code': p.returncode,
                          'stdout_tail': '\n'.join(p.stdout.splitlines()[-2:]),
                          'stderr': p.stderr.strip()}), flush=True)
        if p.returncode:
            return p.returncode
    result['complete'] = True
    (ROOT / 'benchmark/matrix/sizeclass-orchestration.json').write_text(
        json.dumps(result, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
