#!/usr/bin/env python3
"""Corrupt one known block on the owned null_blk during a paused probe."""
import hashlib,json,pathlib,re,subprocess,sys,time
E=pathlib.Path('/tmp/swapz-alpha8-evidence');NULL='/dev/nullb_swapz_pr59_68dca6f'
CONF=pathlib.Path('/sys/kernel/config/nullb/nullb_swapz_pr59_68dca6f');SYS=pathlib.Path('/sys/block/nullb_swapz_pr59_68dca6f')
MODULE=E/'build/dm-swapz-W1.ko';HELPER=pathlib.Path(__file__).parents[1]/'helpers/sv3-read-bypass-probe.ko'
NAME='swz59readfail';UUID='SWZ59-READ-BYPASS-FAIL';PAUSE=5000;READ_PAGE=2048
def call(a,t=120):
 p=subprocess.run(list(map(str,a)),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=t)
 return {'argv':list(map(str,a)),'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def run(a,t=120):
 x=call(a,t)
 if x['rc']:raise RuntimeError(json.dumps(x))
 return x
def sudo(*a,t=120):return run(['sudo','-n',*a],t)
def stat():return [int(v) for v in (SYS/'stat').read_text().split()]
def status():return run(['sudo','-n','dmsetup','status',NAME])['stdout'].strip()
def fields(s):return dict(z.split('=',1) for z in s.split() if '=' in z)
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2)+'\n');q.replace(p)
def empty_dm():return run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() in ('','No devices found')
def power_cycle():
 if not empty_dm() or list((SYS/'holders').iterdir()) or stat()[8]:raise RuntimeError('refuse reset with mapping/holder/inflight IO')
 sudo('sh','-c',f"printf '0\\n' > {CONF/'power'}")
 deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('power-off failed')
 sudo('sh','-c',f"printf '1\\n' > {CONF/'power'}")
 deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists() or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('null_blk identity changed')
def main():
 out=E/'read-failure'/'bypassed-read-pending-writes.json'
 x={'candidate_sha':'68dca6fcd2b322524555becfd54d475cdaf973e1','module_sha256':hashlib.sha256(MODULE.read_bytes()).hexdigest(),
    'helper_sha256':hashlib.sha256(HELPER.read_bytes()).hexdigest(),'target':NAME,'uuid':UUID,'corrupted_lower_block':0,
    'read_logical_page':READ_PAGE,'pause_before_submit_ms':PAUSE,'phase':'preflight','start_unix':time.time()};save(out,x)
 proc=None
 try:
  if not empty_dm():raise RuntimeError('preexisting DM mapping')
  if (CONF/'memory_backed').read_text().strip()!='1' or (CONF/'power').read_text().strip()!='1' or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity mismatch')
  if pathlib.Path('/sys/module/dm_swapz/srcversion').read_text().strip()!=run(['modinfo','-F','srcversion',MODULE])['stdout'].strip():raise RuntimeError('wrong module loaded')
  power_cycle();mm=(SYS/'dev').read_text().strip()
  table=f'0 32768 swapz3 {mm} 0 64 0 2 4 0 1 0 1'
  x['table_requested']=table;run(['sudo','-n','dmsetup','create',NAME,'--uuid',UUID,'--noudevrules','--noudevsync','--table',table])
  actual=run(['sudo','-n','dmsetup','table',NAME])['stdout'].strip();info=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',NAME])['stdout'].strip()
  if actual!=table or info.split(':')[-1]!='0':raise RuntimeError(f'DM identity mismatch {actual} {info}')
  node=f'/dev/dm-{info.split(":")[1]}';x.update({'table_actual':actual,'dm_node':node,'dm_info':info})
  x['seed']=call(['sudo','-n','insmod',HELPER,f'target={node}','mode=0','count=1','expected_bypass=1','seed_only=1',f'read_logical={READ_PAGE}'])
  if x['seed']['rc']:raise RuntimeError(f'seed failed: {x["seed"]}')
  if pathlib.Path('/sys/module/sv3_read_bypass_probe').exists():x['seed_unload']=sudo('rmmod','sv3_read_bypass_probe')
  x['status_after_seed']=status();sf=fields(x['status_after_seed'])
  if sf.get('failed')!='0' or int(sf.get('physical_write','0'))!=4096 or int(sf.get('cursor','0'))!=1:raise RuntimeError(f'expected seed at block0 not established: {sf}')
  x['lower_before_corrupt']=stat()
  # This is an exclusive, test-owned, memory-backed null_blk. No real device
  # or shared fault-injection facility is used. Block zero is the observed
  # first 4KiB allocation (cursor=1) from the fresh V3 target.
  x['corrupt_command']=call(['sudo','-n','dd','if=/dev/zero',f'of={NULL}','bs=4096','count=1','seek=0','conv=notrunc','oflag=direct,dsync','status=none'])
  if x['corrupt_command']['rc']:raise RuntimeError(f'owned lower corruption write failed: {x["corrupt_command"]}')
  x['status_after_corrupt']=status();x['lower_after_corrupt']=stat()
  marker=f'SV3BYPASS batch_ready mode=0 read_logical={READ_PAGE} skip_prefill=1 pause_ms={PAUSE}'
  argv=['sudo','-n','insmod',HELPER,f'target={node}','mode=0','count=63','expected_bypass=1','expected_read_error=1','skip_prefill=1',f'read_logical={READ_PAGE}',f'pause_before_submit_ms={PAUSE}']
  x['fault_probe_command']=list(map(str,argv));x['phase']='pending_read_failure';save(out,x)
  proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  found=False;deadline=time.monotonic()+4.0
  while time.monotonic()<deadline:
   log=call(['sudo','-n','dmesg','--time-format','iso'])
   if marker in log.get('stdout',''):
    x['batch_ready_seen']=True;x['batch_ready_dmesg']=log['stdout'][-8000:];found=True;break
   if proc.poll() is not None:break
   time.sleep(.05)
  if not found:
   stdout,stderr=proc.communicate(timeout=120);x['fault_probe_rc']=proc.returncode;x['fault_probe_stdout']=stdout;x['fault_probe_stderr']=stderr
   raise RuntimeError('could not observe helper pause; it was allowed to finish before cleanup')
  x['lower_before_pending_batch']=stat()
  x['fault_probe_ready_marker']=marker
  stdout,stderr=proc.communicate(timeout=120);x['fault_probe_rc']=proc.returncode;x['fault_probe_stdout']=stdout;x['fault_probe_stderr']=stderr
  if pathlib.Path('/sys/module/sv3_read_bypass_probe').exists():x['fault_probe_unload']=sudo('rmmod','sv3_read_bypass_probe')
  x['status_after_failure']=status();x['lower_after_failure']=stat()
  x['kernel_log_after_failure']=run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-30000:]
  x['failure_lines']=[z for z in x['kernel_log_after_failure'].splitlines() if 'SV3BYPASS' in z and marker.split(' ')[2] in z]
  ff=fields(x['status_after_failure']);seed=fields(x['status_after_seed']);before=x['lower_before_pending_batch'];after=x['lower_after_failure']
  x['target_counter_delta']={k:int(ff.get(k,0))-int(seed.get(k,0)) for k in ['logical_write','physical_write','physical_write_reqs','write_submitted','write_submitted_reqs','read_submitted','read_submitted_reqs','read_bypassed','read_conflict_flushes']}
  x['lower_delta_after_corrupt']={'read_requests':after[0]-before[0],'read_sectors_512':after[2]-before[2],'write_requests':after[4]-before[4],'write_sectors_512':after[6]-before[6]}
  x['lower_delta_after_corrupt']['read_bytes']=x['lower_delta_after_corrupt']['read_sectors_512']*512;x['lower_delta_after_corrupt']['write_bytes']=x['lower_delta_after_corrupt']['write_sectors_512']*512
  if x['fault_probe_rc'] or ff.get('failed')!='1' or ff.get('error')=='0' or int(ff.get('read_bypassed','0'))!=1:raise RuntimeError(f'failed-read expectations not met: rc={x["fault_probe_rc"]} status={ff}')
  for key in ['logical_write','physical_write','physical_write_reqs','write_submitted','write_submitted_reqs']:
   if x['target_counter_delta'][key]!=0:raise RuntimeError(f'pending writes reached lower/publication after failed read: {key} delta={x["target_counter_delta"][key]}')
  if x['lower_delta_after_corrupt']['write_requests'] or x['lower_delta_after_corrupt']['write_sectors_512']:raise RuntimeError('pending writes reached lower after failed read')
  if stat()[8]:raise RuntimeError('in-flight lower IO after failed read')
  q=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',NAME])['stdout'].strip()
  if q.split(':')[-1]!='0':raise RuntimeError(f'target still open: {q}')
  x['remove']=sudo('dmsetup','remove','--uuid',UUID)
  if not empty_dm() or list((SYS/'holders').iterdir()):raise RuntimeError('ordinary teardown did not detach owned target')
  power_cycle();x['phase']='PASS';x['end_unix']=time.time();save(out,x)
  print(json.dumps({'phase':'PASS','read_bypassed':ff.get('read_bypassed'),'failed':ff.get('failed'),'error':ff.get('error'),'target_delta':x['target_counter_delta'],'lower_delta_after_corrupt':x['lower_delta_after_corrupt'],'trial':str(out)},sort_keys=True));return 0
 except Exception as e:
  if proc is not None and proc.poll() is None:
   # Never signal or abandon the kernel helper while it owns upper BIOs.
   stdout,stderr=proc.communicate(timeout=120);x['helper_after_exception']={'rc':proc.returncode,'stdout':stdout,'stderr':stderr}
  x['phase']='FAILED_OR_PRESERVED';x['error']=repr(e);x['end_unix']=time.time();save(out,x);print(f'PRESERVED {NAME} UUID={UUID} error={e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
