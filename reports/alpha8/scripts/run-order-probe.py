#!/usr/bin/env python3
"""Run the test-only upper-BIO read-after-write ordering probe on owned null_blk."""
import argparse, hashlib, json, pathlib, re, subprocess, sys, time
E=pathlib.Path('/tmp/swapz-alpha8-evidence')
NULL='/dev/nullb_swapz_pr59_68dca6f'
CONF=pathlib.Path('/sys/kernel/config/nullb/nullb_swapz_pr59_68dca6f')
SYS=pathlib.Path('/sys/block/nullb_swapz_pr59_68dca6f')
HELPER=pathlib.Path(__file__).parents[1]/'helpers/sv3-read-bypass-probe.ko'
MODULE=E/'build/dm-swapz-W1.ko'
def call(argv,timeout=120):
 t=time.monotonic_ns();p=subprocess.run(list(map(str,argv)),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 return {'argv':list(map(str,argv)),'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_ns':time.monotonic_ns()-t}
def run(argv,timeout=120):
 x=call(argv,timeout)
 if x['rc']: raise RuntimeError(json.dumps(x))
 return x
def sudo(*args,timeout=120):return run(['sudo','-n',*args],timeout)
def stat():return [int(x) for x in (SYS/'stat').read_text().split()]
def status(name):return run(['sudo','-n','dmsetup','status',name])['stdout'].strip()
def parse(s):
 d={}
 for x in s.split():
  if '=' in x:k,v=x.split('=',1);d[k]=v
 return d
def save(p,o):
 p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(o,indent=2)+'\n');q.replace(p)
def power_cycle():
 if run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found'):raise RuntimeError('DM mapping exists')
 if list((SYS/'holders').iterdir()) or stat()[8]:raise RuntimeError('backing holder or in-flight I/O')
 sudo('sh','-c',f"printf '0\\n' > {CONF/'power'}")
 deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('null_blk did not power off')
 sudo('sh','-c',f"printf '1\\n' > {CONF/'power'}")
 deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists() or (SYS/'dev').read_text().strip()!='251:0' or (CONF/'memory_backed').read_text().strip()!='1':raise RuntimeError('null_blk identity changed')
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--label',required=True);ap.add_argument('--mode',type=int,choices=range(6),required=True);ap.add_argument('--bypass',type=int,choices=(0,1),required=True);ap.add_argument('--count',type=int,default=None)
 a=ap.parse_args();count=a.count if a.count is not None else (63 if a.mode==0 else 3)
 name=f'swz59o-{a.label}'[:63];uuid=f'SWZ59O-{a.label.upper()}'[:120]
 out=E/'ordering'/f'{a.label}.json'
 if out.exists():raise RuntimeError(f'trial already exists: {out}')
 x={'label':a.label,'mode':a.mode,'read_bypass':a.bypass,'count':count,'target_name':name,'target_uuid':uuid,
    'candidate_sha':'68dca6fcd2b322524555becfd54d475cdaf973e1','module_sha256':hashlib.sha256(MODULE.read_bytes()).hexdigest(),
    'helper_sha256':hashlib.sha256(HELPER.read_bytes()).hexdigest(),'start_unix':time.time(),'phase':'preflight'}
 save(out,x)
 try:
  if (CONF/'power').read_text().strip()!='1' or (CONF/'memory_backed').read_text().strip()!='1' or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity/config mismatch')
  if run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found'):raise RuntimeError('unrelated mapping present')
  if pathlib.Path('/sys/module/dm_swapz/srcversion').read_text().strip()!=run(['modinfo','-F','srcversion',MODULE])['stdout'].strip():raise RuntimeError('loaded module is not alpha8 W1 artifact')
  power_cycle();lower0=stat()
  sectors=4096*8
  table=f'0 {sectors} swapz3 {NULL} 0 64 0 2 4 0 1 0 {a.bypass}'
  x['table_requested']=table;x['lower_before']=lower0
  run(['sudo','-n','dmsetup','create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table])
  actual=run(['sudo','-n','dmsetup','table',name])['stdout'].strip();gotuuid=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','uuid',name])['stdout'].strip()
  info=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
  mm=(SYS/'dev').read_text().strip()
  if actual!=table.replace(NULL,mm) or gotuuid!=uuid or info.split(':')[-1]!='0':raise RuntimeError(f'DM identity mismatch: {actual} {gotuuid} {info}')
  dmdev=f'/dev/dm-{info.split(":")[1]}'
  x.update({'table_actual':actual,'uuid_actual':gotuuid,'dm_info':info,'dm_device':dmdev,'status_before':status(name)})
  x['dmesg_before']=run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-10000:]
  x['probe']=call(['sudo','-n','insmod',HELPER,f'target={dmdev}',f'mode={a.mode}',f'count={count}',f'expected_bypass={a.bypass}'],timeout=180)
  if pathlib.Path('/sys/module/sv3_read_bypass_probe').exists():x['probe_unload']=sudo('rmmod','sv3_read_bypass_probe')
  x['status_after']=status(name);x['lower_after']=stat()
  x['dmesg_after']=run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-20000:]
  x['probe_lines']=[line for line in x['dmesg_after'].splitlines() if 'SV3BYPASS' in line]
  x['counter_fields']=parse(x['status_after'])
  x['lower_delta']={'read_requests':x['lower_after'][0]-lower0[0],'read_sectors_512':x['lower_after'][2]-lower0[2],
                    'write_requests':x['lower_after'][4]-lower0[4],'write_sectors_512':x['lower_after'][6]-lower0[6],
                    'flush_requests':x['lower_after'][15]-lower0[15]}
  x['lower_delta']['read_bytes']=x['lower_delta']['read_sectors_512']*512;x['lower_delta']['write_bytes']=x['lower_delta']['write_sectors_512']*512
  f=x['counter_fields'];log='\n'.join(x['probe_lines'])
  if x['probe']['rc'] or f.get('failed')!='0' or f.get('error')!='0':raise RuntimeError(f'probe/target failed: rc={x["probe"]["rc"]}, status={f}')
  if a.mode==0:
   if int(f.get('read_bypassed','-1')) != a.bypass:raise RuntimeError(f'bypass count mismatch {f.get("read_bypassed")}')
   if a.bypass and not re.search(r'read_seq=(\d+).*min_write_seq=(\d+)',log):raise RuntimeError('missing completion order log')
  else:
   if int(f.get('read_conflict_flushes','0'))<1:raise RuntimeError('same-page read did not count conflict flush')
   if int(f.get('read_bypassed','0')):raise RuntimeError('same-page read incorrectly bypassed')
  if stat()[8]:raise RuntimeError('in-flight backing I/O before teardown')
  info=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
  if info.split(':')[-1]!='0':raise RuntimeError(f'open count before remove is not zero: {info}')
  x['remove']=sudo('dmsetup','remove','--uuid',uuid)
  if run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found') or list((SYS/'holders').iterdir()):raise RuntimeError('ordinary teardown did not clear target/holder')
  power_cycle();x['lower_after_reset']=stat();x['phase']='PASS';x['end_unix']=time.time();save(out,x)
  print(json.dumps({'label':a.label,'phase':'PASS','mode':a.mode,'read_bypass':a.bypass,
                    'read_bypassed':f.get('read_bypassed'),'read_conflict_flushes':f.get('read_conflict_flushes'),
                    'probe_lines':x['probe_lines'],'lower_delta':x['lower_delta']},sort_keys=True));return 0
 except Exception as e:
  x['phase']='FAILED_OR_PRESERVED';x['error']=repr(e);x['end_unix']=time.time();save(out,x)
  print(f'PRESERVED mapping={name} uuid={uuid} error={e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
