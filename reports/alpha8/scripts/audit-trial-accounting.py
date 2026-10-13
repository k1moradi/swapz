#!/usr/bin/env python3
"""Cross-check V3 status counters against independent backing stat deltas."""
import json
import sys
from pathlib import Path

ROOT = Path('/tmp/swapz-alpha8-evidence/benchmark')

def status(text):
    return dict(part.split('=', 1) for part in text.split() if '=' in part)

def main(paths):
    trials=[]
    for manifest_path in map(Path, paths):
        manifest=json.loads(manifest_path.read_text())
        for command in manifest['commands']:
            try: envelope=json.loads(command['stdout'].strip().splitlines()[-1])
            except Exception: envelope={}
            label=envelope.get('label')
            if not label: continue
            matches=list((ROOT/'trials').glob(f'{label}/trial.json'))
            if len(matches)!=1: raise SystemExit(f'{label}: expected one raw trial, got {len(matches)}')
            trial=json.loads(matches[0].read_text())
            if trial.get('phase')!='PASS': raise SystemExit(f'{label}: phase={trial.get("phase")}')
            if not isinstance(trial.get('verification'),dict) or trial['verification'].get('rc')!=0 or '"mismatches":0' not in trial['verification'].get('stdout',''):
                raise SystemExit(f'{label}: full-image verification missing/failed')
            m=trial.get('measurement_summary') or {}; low=trial.get('lower_delta') or {}; td=trial.get('target_counter_deltas') or {}
            errors=[]
            if m.get('errors') or m.get('mismatches'): errors.append('helper_errors')
            if trial.get('target_status_fields_after_measurement',{}).get('failed')!='0': errors.append('target_failed')
            useful=int(m.get('reads',0))+int(m.get('writes',0))
            if int(manifest.get('iops',0))>0 and useful!=int(manifest['iops'])*int(manifest['seconds']): errors.append('matched_useful_ops_count')
            for target,independent in [('physical_write_reqs','write_requests'),('physical_write','write_bytes'),('physical_read_reqs','read_requests'),('physical_read','read_bytes')]:
                if command['candidate']=='v22': continue
                if int(td.get(target,-1))!=int(low.get(independent,-2)):
                    errors.append(f'{target}!={independent}:{td.get(target)}!={low.get(independent)}')
            if command['candidate']!='v22':
                before=status(trial.get('status_before_measurement',''))
                after=trial.get('target_status_fields_after_measurement',{})
                bins=sum(int(trial.get('target_counter_deltas',{}).get(k,0)) for k in ('win1','win2','win3_4','win5_8','win9_16','win17_64'))
                if bins!=int(td.get('windows',0)): errors.append('window_histogram_sum')
                if int(td.get('one_page_windows',0))!=int(td.get('win1',0)): errors.append('one_page_windows!=win1')
                trial['read_bypassed_delta']=int(after.get('read_bypassed',0))-int(before.get('read_bypassed',0))
                trial['read_conflict_flushes_delta']=int(after.get('read_conflict_flushes',0))-int(before.get('read_conflict_flushes',0))
            trials.append({'label':label,'candidate':command['candidate'],'qd':command['qd'],'phase':trial.get('phase'),
                           'ops':int(m.get('reads',0))+int(m.get('writes',0)),'verification':'PASS','accounting_errors':errors,
                           'lower_write_requests':low.get('write_requests'),'lower_write_bytes':low.get('write_bytes'),
                           'lower_read_requests':low.get('read_requests'),'lower_read_bytes':low.get('read_bytes'),
                           'target_write_requests':td.get('physical_write_reqs'),'target_write_bytes':td.get('physical_write'),
                           'target_read_requests':td.get('physical_read_reqs'),'target_read_bytes':td.get('physical_read'),
                           'read_bypassed_delta':trial.get('read_bypassed_delta'),'window_records':td.get('window_records'),
                           'windows':td.get('windows'),'window_histogram_total':bins if command['candidate']!='v22' else None,
                           'mean_records_per_window':(td.get('window_records',0)/td.get('windows',1)) if command['candidate']!='v22' and td.get('windows') else None,
                           'read_conflict_flushes_delta':trial.get('read_conflict_flushes_delta')})
            if errors: raise SystemExit(f'{label}: accounting/verification failed: {errors}')
    out=Path('/tmp/swapz-alpha8-evidence/benchmark/accounting-audit.json');out.write_text(json.dumps({'trials':trials,'trial_count':len(trials),'all_passed':True},indent=2)+'\n')
    print(f'PASS: {len(trials)} trial records audited, all V3 read/write request and byte counters match independent backing stats; target-failure and window-histogram assertions pass. {out}')

if __name__=='__main__':
    if len(sys.argv)<2: raise SystemExit('usage: audit-trial-accounting.py MATRIX.json [MATRIX.json ...]')
    main(sys.argv[1:])
