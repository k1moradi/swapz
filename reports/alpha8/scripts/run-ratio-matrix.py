#!/usr/bin/env python3
"""Counterbalanced, fail-closed orchestration for the owned null_blk trials."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/tmp/swapz-alpha8-evidence/benchmark')
SCRIPT = Path('/tmp/swapz-pr59-validation/reports/alpha8/scripts/run-sustained-trial.py')
CANDIDATES = ['v22', 'a8off', 'a8on']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--design', choices=['matched', 'saturation'], required=True)
    ap.add_argument('--repetitions', type=int, required=True)
    ap.add_argument('--qds', type=int, nargs='+', default=[4])
    ap.add_argument('--iops', type=int, default=0)
    ap.add_argument('--seconds', type=int, default=30)
    ap.add_argument('--warmup', type=int, default=10)
    ap.add_argument('--read-pct', type=int, default=20)
    ap.add_argument('--fixture')
    ap.add_argument('--classmap')
    ap.add_argument('--tag', required=True)
    a = ap.parse_args()
    if a.design == 'matched' and a.iops <= 0:
        ap.error('matched design requires positive --iops')
    summary = {'design': a.design, 'qds': a.qds, 'repetitions': a.repetitions,
               'iops': a.iops, 'seconds': a.seconds, 'warmup': a.warmup,
               'read_pct': a.read_pct, 'tag': a.tag, 'commands': []}
    outdir = ROOT / 'matrix' / a.tag
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / 'orchestration.json'
    path.write_text(json.dumps(summary, indent=2) + '\n')
    trial = 0
    for qd in a.qds:
        for rep in range(1, a.repetitions + 1):
            rot = (rep - 1 + qd) % len(CANDIDATES)
            order = CANDIDATES[rot:] + CANDIDATES[:rot]
            for candidate in order:
                trial += 1
                suffix = f'{a.tag}-qd{qd}-r{rep}'
                cmd = ['sudo', '-n', sys.executable, str(SCRIPT),
                       '--candidate', candidate, '--rep', str(rep), '--qd', str(qd),
                       '--read-pct', str(a.read_pct), '--warmup', str(a.warmup),
                       '--seconds', str(a.seconds), '--iops', str(a.iops),
                       '--label-suffix', suffix]
                if a.fixture:
                    cmd.extend(['--fixture', a.fixture])
                if a.classmap:
                    cmd.extend(['--classmap', a.classmap])
                started = time.time()
                p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
                row = {'index': trial, 'candidate': candidate, 'qd': qd,
                       'rep': rep, 'started': started, 'command': cmd,
                       'exit_code': p.returncode, 'stdout': p.stdout,
                       'stderr': p.stderr, 'ended': time.time()}
                summary['commands'].append(row)
                path.write_text(json.dumps(summary, indent=2) + '\n')
                print(json.dumps({'index': trial, 'total_expected': len(a.qds) * a.repetitions * len(CANDIDATES),
                                  'candidate': candidate, 'qd': qd, 'rep': rep,
                                  'exit_code': p.returncode,
                                  'stdout': p.stdout.strip(),
                                  'stderr': p.stderr.strip()}), flush=True)
                if p.returncode:
                    print('Stopping matrix on first nonzero trial exit; inspect ownership before continuing.', flush=True)
                    return p.returncode
    summary['complete'] = True
    path.write_text(json.dumps(summary, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
