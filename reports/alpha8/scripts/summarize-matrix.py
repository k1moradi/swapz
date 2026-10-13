#!/usr/bin/env python3
"""Extract trial-level lower-device, latency, CPU and window metrics."""
import csv
import json
import statistics
import sys
from pathlib import Path


def status_fields(s):
    return dict(part.split('=', 1) for part in s.split() if '=' in part)


def main(path):
    manifest = json.loads(Path(path).read_text())
    rows = []
    for cmd in manifest['commands']:
        try:
            envelope = json.loads(cmd['stdout'].strip().splitlines()[-1])
        except Exception:
            envelope = {}
        label = envelope.get('label')
        matches = list((Path('/tmp/swapz-alpha8-evidence/benchmark/trials')).glob(f'{label}/trial.json')) if label else []
        if not matches:
            rows.append({'candidate': cmd['candidate'], 'qd': cmd['qd'], 'rep': cmd['rep'],
                         'phase': 'MISSING_TRIAL_JSON', 'label': label or ''})
            continue
        trial = json.loads(matches[0].read_text())
        before = status_fields(trial.get('status_before_measurement', ''))
        after = trial.get('target_status_fields_after_measurement', {})
        delta = trial.get('target_counter_deltas', {})
        s = trial.get('measurement_summary') or {}
        lower = trial.get('lower_delta') or {}
        useful = int(s.get('reads', 0)) + int(s.get('writes', 0))
        windows = int(delta.get('windows', 0))
        records = int(delta.get('window_records', 0))
        rows.append({
            'label': label, 'candidate': cmd['candidate'], 'qd': cmd['qd'], 'rep': cmd['rep'],
            'phase': trial.get('phase'), 'requested_iops': s.get('requested_iops'),
            'reads': s.get('reads'), 'writes': s.get('writes'), 'useful_ops': useful,
            'achieved_iops': useful / float(s.get('seconds', 1) or 1),
            'lower_write_requests': lower.get('write_requests'),
            'lower_write_bytes': lower.get('write_bytes'),
            'lower_read_requests': lower.get('read_requests'),
            'lower_read_bytes': lower.get('read_bytes'),
            'flush_requests': lower.get('flush_requests'), 'discard_requests': lower.get('discard_requests'),
            'write_reqs_per_useful_write': (lower.get('write_requests', 0) / s['writes']) if s.get('writes') else None,
            'write_bytes_per_useful_write': (lower.get('write_bytes', 0) / s['writes']) if s.get('writes') else None,
            'read_reqs_per_useful_read': (lower.get('read_requests', 0) / s['reads']) if s.get('reads') else None,
            'read_bytes_per_useful_read': (lower.get('read_bytes', 0) / s['reads']) if s.get('reads') else None,
            'write_p50_ns': s.get('write_p50_ns'), 'write_p95_ns': s.get('write_p95_ns'),
            'write_p99_ns': s.get('write_p99_ns'), 'write_samples': s.get('write_samples'),
            'read_p50_ns': s.get('read_p50_ns'), 'read_p95_ns': s.get('read_p95_ns'),
            'read_p99_ns': s.get('read_p99_ns'), 'read_samples': s.get('read_samples'),
            'helper_process_cpu_s': s.get('process_cpu_s'), 'helper_peak_rss_kb': s.get('peak_rss_kb'),
            'window_records': records, 'windows': windows,
            'avg_records_per_window': records / windows if windows else None,
            'one_page_windows': delta.get('one_page_windows'),
            'win1': delta.get('win1'), 'win2': delta.get('win2'), 'win3_4': delta.get('win3_4'),
            'win5_8': delta.get('win5_8'), 'win9_16': delta.get('win9_16'),
            'win17_64': delta.get('win17_64'),
            'read_bypassed': int(after.get('read_bypassed', 0)) - int(before.get('read_bypassed', 0)),
            'read_conflict_flushes': int(after.get('read_conflict_flushes', 0)) - int(before.get('read_conflict_flushes', 0)),
            'gc_rotations': delta.get('gc_role_rotations'), 'gc_read_bytes': delta.get('gc_read'),
            'gc_write_bytes': delta.get('gc_write'), 'gc_read_requests': delta.get('gc_read_reqs'),
            'gc_write_requests': delta.get('gc_write_reqs'),
            'target_write_req_delta': delta.get('physical_write_reqs'),
            'target_write_bytes_delta': delta.get('physical_write'),
            'target_read_req_delta': delta.get('physical_read_reqs'),
            'target_read_bytes_delta': delta.get('physical_read'),
            'verification': 'PASS' if isinstance(trial.get('verification'), dict) and
                trial['verification'].get('rc') == 0 and '"mismatches":0' in
                trial['verification'].get('stdout', '') else 'FAIL_OR_MISSING',
            'fixture_sha256': trial.get('fixture_sha256'), 'module_sha256': trial.get('module', {}).get('module_sha256'),
        })
    outdir = Path(path).parent
    all_fields = sorted({k for row in rows for k in row})
    with (outdir / 'trials.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=all_fields)
        w.writeheader(); w.writerows(rows)
    groups = {}
    for row in rows:
        key = (row['candidate'], row['qd'])
        groups.setdefault(key, []).append(row)
    summaries = []
    metrics = ['achieved_iops', 'lower_write_requests', 'lower_write_bytes', 'lower_read_requests',
               'lower_read_bytes', 'write_reqs_per_useful_write', 'write_bytes_per_useful_write',
               'write_p50_ns', 'write_p95_ns', 'write_p99_ns', 'read_p50_ns', 'read_p95_ns',
               'read_p99_ns', 'helper_process_cpu_s', 'helper_peak_rss_kb', 'avg_records_per_window',
               'one_page_windows', 'read_bypassed', 'gc_rotations', 'gc_read_bytes', 'gc_write_bytes']
    for (cand, qd), group in sorted(groups.items()):
        summary = {'candidate': cand, 'qd': qd, 'n': len(group),
                   'all_trials_passed': all(x.get('phase') == 'PASS' and x.get('verification') == 'PASS' for x in group)}
        for metric in metrics:
            values = [x.get(metric) for x in group if isinstance(x.get(metric), (int, float))]
            if values:
                summary[metric + '_median'] = statistics.median(values)
                summary[metric + '_min'] = min(values)
                summary[metric + '_max'] = max(values)
        summaries.append(summary)
    (outdir / 'summary.json').write_text(json.dumps(summaries, indent=2) + '\n')
    if summaries:
        keys = sorted({k for row in summaries for k in row})
        with (outdir / 'summary.csv').open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(summaries)
    print(f'wrote {outdir / "trials.csv"} ({len(rows)} rows)')
    print(f'wrote {outdir / "summary.csv"} ({len(summaries)} groups)')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: summarize-matrix.py orchestration.json')
    main(sys.argv[1])
