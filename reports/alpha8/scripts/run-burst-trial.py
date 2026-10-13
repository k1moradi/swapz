#!/usr/bin/env python3
"""Replay the frozen 1,024-page PR #56 burst on owned null_blk only."""
import importlib.util, json, os, sys, time
from pathlib import Path
P=Path(__file__).with_name('run-sustained-trial.py')
spec=importlib.util.spec_from_file_location('alpha8_runner',P)
R=importlib.util.module_from_spec(spec);sys.modules[spec.name]=R;spec.loader.exec_module(R)

def statv(raw): return R.stat_values(raw)
def main():
 import argparse
 ap=argparse.ArgumentParser()
 ap.add_argument('--candidate',choices=R.CANDS,required=True)
 ap.add_argument('--rep',type=int,required=True)
 a=ap.parse_args();c=R.CANDS[a.candidate]
 out=R.E/'burst'/f'{a.candidate}-r{a.rep}'
 out.mkdir(parents=True,exist_ok=False)
 name=f'swz59b-{a.candidate}-r{a.rep}'
 uuid=f'SWZ59B-{a.candidate.upper()}-R{a.rep}'
 r={'candidate':a.candidate,'source_sha':c['source'],'module_path':str(c['module']),'module_sha256':R.sha_file(c['module']),'fixture_sha256':R.sha_file(R.FIXTURE),'classmap_sha256':R.sha_file(R.CLASSMAP),'target_name':name,'target_uuid':uuid,'useful_pages':1024,'useful_bytes':4194304,'profile':{'backing':R.NULL,'size_mib':40,'memory_backed':1,'logical_block':512,'mbps':20,'completion_nsec':500000,'queue_mode':2,'hw_queue_depth':64,'submit_queues':1,'lower_bulk':c['bulk'],'read_bypass':c['bypass']},'phase':'preflight','start_wall':time.time()}
 def save():
  t=out/'trial.json.tmp';t.write_text(json.dumps(r,indent=2)+'\n');t.replace(out/'trial.json')
 def cmd(argv,timeout=180):
  x=R.call(argv,timeout);r.setdefault('commands',[]).append(x);return x
 try:
  if not R.no_dm():raise RuntimeError('pre-existing DM mapping prevents test')
  r['swaps_before']=Path('/proc/swaps').read_text()
  if R.swap_identity(r['swaps_before'])!=R.swap_identity((R.E/'swaps-initial.txt').read_text()):raise RuntimeError('active swap changed from initial inventory')
  r['module']=R.module_switch(c);R.power_cycle()
  dev_mm=(R.SYS/'dev').read_text().strip()
  if (R.CONF/'memory_backed').read_text().strip()!='1' or len(dev_mm.split(':'))!=2:raise RuntimeError('owned null_blk identity/config mismatch')
  if list((R.SYS/'holders').iterdir()):raise RuntimeError('unexpected lower holder before target')
  if subprocess_mount:=__import__('subprocess').run(['findmnt','-rn','-S',R.NULL],capture_output=True,text=True).stdout.strip():raise RuntimeError(f'owned backing mounted: {subprocess_mount}')
  if any(row.split() and row.split()[0]==R.NULL for row in Path('/proc/swaps').read_text().splitlines()[1:]):raise RuntimeError('owned backing is active swap')
  r['lower_before']={'major_minor':dev_mm,'stat_raw':R.read_stat(),'stat':statv(R.read_stat())}
  sectors=1024*8
  if c['impl']=='v22':table=f'0 {sectors} swapz {R.NULL} opportunistic 64'
  elif c['impl']=='pr57':table=f'0 {sectors} swapz3 {R.NULL} 0 64 0 2 0 0 {c["bulk"]} 0'
  else:table=f'0 {sectors} swapz3 {R.NULL} 0 64 0 2 0 0 {c["bulk"]} 0 {c["bypass"]}'
  r['table_requested']=table;save()
  r['dm_create']=R.dm('create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table)
  actual=R.dm('table',name)['stdout'].strip();r['table_actual']=actual
  r['dm_uuid_actual']=R.dm('info','-c','--noheadings','-o','uuid',name)['stdout'].strip()
  initial,quiet=R.wait_open_zero(name);r['dm_open_before_helper']={'initial':initial,'quiet':quiet}
  if actual!=table.replace(R.NULL,dev_mm) or r['dm_uuid_actual']!=uuid or quiet.split(':')[-1]!='0':raise RuntimeError('owned DM table/UUID/open preflight failed')
  dmdev='/dev/dm-'+quiet.split(':')[1]
  common=[str(R.BIN),'--device',dmdev,'--fixture',str(R.FIXTURE),'--classmap',str(R.CLASSMAP),'--logical-pages','1024','--writer-pages','1024','--reader-start','0','--reader-pages','1','--seed','0x57a7c0de']
  r['target_status_before']=R.dm('status',name)['stdout'].strip()
  r['lower_before_write']={'raw':R.read_stat(),'fields':statv(R.read_stat())}
  r['prefill_command']=common+['--mode','prefill'];r['prefill']=cmd(r['prefill_command'])
  r['target_status_after_write']=R.dm('status',name)['stdout'].strip()
  r['lower_after_write']={'raw':R.read_stat(),'fields':statv(R.read_stat())}
  before=r['lower_before_write']['fields'];after=r['lower_after_write']['fields']
  keys=['write_requests','write_sectors_512','read_requests','read_sectors_512','flush_requests']
  r['lower_write_delta']={k:after[k]-before[k] for k in keys}
  r['lower_write_delta']['write_bytes']=r['lower_write_delta']['write_sectors_512']*512
  r['verify_command']=common+['--mode','verify'];r['verification']=cmd(r['verify_command'])
  r['lower_after_verify']={'raw':R.read_stat(),'fields':statv(R.read_stat())}
  if r['prefill']['rc'] or r['verification']['rc']:raise RuntimeError('prefill or complete byte-exact verification failed')
  status=R.fields(r['target_status_after_write']);r['target_fields']=status
  if c['impl']!='v22' and (status.get('failed')!='0' or status.get('read_bypassed')!='0'):raise RuntimeError('V3 failure or unexpected read bypass in write-only burst')
  if any(row.split() and row.split()[0]==R.NULL for row in Path('/proc/swaps').read_text().splitlines()[1:]):raise RuntimeError('owned backing became active swap')
  if R.read_stat()[8]!=0:raise RuntimeError('lower I/O still in flight before teardown')
  _,quiet=R.wait_open_zero(name);r['dm_open_before_remove']=quiet
  if quiet.split(':')[-1]!='0':raise RuntimeError('target open references did not drain')
  r['dm_remove']=R.dm('remove','--uuid',uuid)
  if not R.no_dm() or list((R.SYS/'holders').iterdir()):raise RuntimeError('ordinary DM teardown did not clear owned mapping/holder')
  R.power_cycle()
  r['final_dm_inventory']=R.dm('ls','--tree')['stdout']
  r['swaps_after']=Path('/proc/swaps').read_text()
  if R.swap_identity(r['swaps_after'])!=R.swap_identity(r['swaps_before']):raise RuntimeError('active swap changed during burst')
  r['phase']='PASS';r['end_wall']=time.time();save()
  print(json.dumps({'candidate':a.candidate,'phase':r['phase'],'lower_write_delta':r['lower_write_delta'],'verification':r['verification']['stdout'].strip(),'target_status':r['target_fields']},sort_keys=True))
  return 0
 except Exception as exc:
  r['phase']='FAILED_OR_QUARANTINED';r['error']=repr(exc);r['end_wall']=time.time();save();print(f'PRESERVED {name} UUID={uuid} error={exc}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
