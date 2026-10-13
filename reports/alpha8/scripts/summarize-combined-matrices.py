#!/usr/bin/env python3
"""Join independent matched-matrix manifests and summarize verified trials."""
import csv
import json
import statistics
import sys
from pathlib import Path

EVIDENCE = Path('/tmp/swapz-alpha8-evidence/benchmark')
OUT = Path('/tmp/swapz-alpha8-evidence/benchmark/matrix/matched5000-q8-rp20-five')
METRICS = (
    'achieved_iops', 'lower_write_requests', 'lower_write_bytes',
    'lower_read_requests', 'lower_read_bytes', 'write_p50_us', 'write_p95_us',
    'write_p99_us', 'read_p50_us', 'read_p95_us', 'read_p99_us',
    'helper_process_cpu_s', 'helper_peak_rss_kb', 'avg_records_per_window',
    'read_bypassed', 'gc_rotations', 'gc_read_bytes', 'gc_write_bytes',
)


def main(manifests):
    rows = []
    for manifest_file in map(Path, manifests):
        manifest = json.loads(manifest_file.read_text())
        for command in manifest['commands']:
            envelope = json.loads(command['stdout'].strip().splitlines()[-1])
            label = envelope['label']
            trial_path = EVIDENCE / 'trials' / label / 'trial.json'
            trial = json.loads(trial_path.read_text())
            m = trial['measurement_summary']
            low = trial['lower_delta']
            td = trial['target_counter_deltas']
            s = m['seconds']
            useful = int(m['reads']) + int(m['writes'])
            row = {
                'label': label,
                'candidate': command['candidate'],
                'rep': command['rep'],
                'phase': trial['phase'],
                'fixture_sha256': trial['fixture_sha256'],
                'classmap_sha256': trial['classmap_sha256'],
                'useful_ops': useful,
                'reads': m['reads'],
                'writes': m['writes'],
                'achieved_iops': useful / s,
                'lower_write_requests': low['write_requests'],
                'lower_write_bytes': low['write_bytes'],
                'lower_read_requests': low['read_requests'],
                'lower_read_bytes': low['read_bytes'],
                'write_reqs_per_useful_write': low['write_requests'] / m['writes'],
                'write_bytes_per_useful_write': low['write_bytes'] / m['writes'],
                'read_reqs_per_useful_read': low['read_requests'] / m['reads'],
                'read_bytes_per_useful_read': low['read_bytes'] / m['reads'],
                'write_p50_us': m['write_p50_ns'] / 1000,
                'write_p95_us': m['write_p95_ns'] / 1000,
                'write_p99_us': m['write_p99_ns'] / 1000,
                'read_p50_us': m['read_p50_ns'] / 1000,
                'read_p95_us': m['read_p95_ns'] / 1000,
                'read_p99_us': m['read_p99_ns'] / 1000,
                'helper_process_cpu_s': m['process_cpu_s'],
                'helper_peak_rss_kb': m['peak_rss_kb'],
                'windows': td['windows'],
                'window_records': td['window_records'],
                'avg_records_per_window': td['window_records'] / td['windows'] if td['windows'] else None,
                'one_page_windows': td['one_page_windows'],
                'read_bypassed': int(trial['target_status_fields_after_measurement'].get('read_bypassed', 0))
                    - int(dict(x.split('=', 1) for x in trial['status_before_measurement'].split() if '=' in x).get('read_bypassed', 0)),
                'gc_rotations': td['gc_role_rotations'],
                'gc_read_bytes': td['gc_read'],
                'gc_write_bytes': td['gc_write'],
                'verification': 'PASS' if trial.get('verification', {}).get('rc') == 0 and
                    'mismatches":0' in trial.get('verification', {}).get('stdout', '') else 'FAIL',
            }
            if row['phase'] != 'PASS' or row['verification'] != 'PASS' or useful != 150000:
                raise SystemExit(f'invalid matched trial: {label} phase={row["phase"]} verification={row["verification"]} ops={useful}')
            rows.append(row)
    for candidate in ('v22', 'a8off', 'a8on'):
        group = [row for row in rows if row['candidate'] == candidate]
        if len(group) != 5 or len({row['fixture_sha256'] for row in group}) != 1:
            raise SystemExit(f'{candidate}: expected five same-fixture trials, got {len(group)}')
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'trials.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=sorted({key for row in rows for key in row}))
        writer.writeheader(); writer.writerows(rows)
    summaries = []
    for candidate in ('v22', 'a8off', 'a8on'):
        group = [row for row in rows if row['candidate'] == candidate]
        summary = {'candidate': candidate, 'n': len(group),
                   'fixture_sha256': group[0]['fixture_sha256'],
                   'all_trials_passed': all(row['verification'] == 'PASS' for row in group)}
        for metric in METRICS:
            values = [row[metric] for row in group if row[metric] is not None]
            summary[metric + '_median'] = statistics.median(values) if values else None
            summary[metric + '_min'] = min(values) if values else None
            summary[metric + '_max'] = max(values) if values else None
        summaries.append(summary)
    (OUT / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
    with (OUT / 'summary.csv').open('w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=sorted({key for row in summaries for key in row}))
        writer.writeheader(); writer.writerows(summaries)
    print(f'PASS: combined {len(rows)} trials, 5 per candidate, identical fixture, 150000 useful ops and byte-exact verification')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: summarize-combined-matrices.py MATRIX.json [MATRIX.json ...]')
    main(sys.argv[1:])
