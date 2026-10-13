#!/usr/bin/env python3
"""Suspend/drain 1024 accepted BIOs on an owned alpha.8 null_blk target."""
import hashlib,json,pathlib,subprocess,sys,time
E=pathlib.Path('/tmp/swapz-alpha8-evidence');NULL='/dev/nullb_swapz_pr59_68dca6f'
CONF=pathlib.Path('/sys/kernel/config/nullb/nullb_swapz_pr59_68dca6f');SYS=pathlib.Path('/sys/block/nullb_swapz_pr59_68dca6f')
MODULE=E/'build/dm-swapz-W1.ko';HELPER=pathlib.Path(__file__).parents[1]/'helpers/sv3-queue-probe.ko';VERIFY=E/'build/verify-queue'
NAME='swz59susp1024';UUID='SWZ59-SUSPEND-1024';TAG='pr59alpha8suspend1024';COUNT=1024
def call(a,t=120):
 p=subprocess.run(list(map(str,a)),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=t)
 return {'argv':list(map(str,a)),'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_ns':p.elapsed_ns if hasattr(p,'elapsed_ns') else None}
def run(a,t=120):
 x=call(a,t)
 if x['rc']:raise RuntimeError(json.dumps(x))
 return x
def sudo(*a,t=120):return run(['sudo','-n',*a],t)
def stat():return [int(v) for v in (SYS/'stat').read_text().split()]
def status():return run(['sudo','-n','dmsetup','status',NAME])['stdout'].strip()
def empty_dm():return run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() in ('','No devices found')
def fields(s):return dict(z.split('=',1) for z in s.split() if '=' in z)
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2)+'\n');q.replace(p)
def cycle():
 if not empty_dm() or list((SYS/'holders').iterdir()) or stat()[8]:raise RuntimeError('refuse reset while mapping/holder/inflight IO exists')
 sudo('sh','-c',f"printf '0\\n' > {CONF/'power'}")
 deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('null_blk power off failed')
 sudo('sh','-c',f"printf '1\\n' > {CONF/'power'}")
 deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists() or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity changed')
def main():
 out=E/'suspend'/'1024-drain.json';x={'source_sha':'68dca6fcd2b322524555becfd54d475cdaf973e1','module_sha256':hashlib.sha256(MODULE.read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(HELPER.read_bytes()).hexdigest(),'fixture_sha256':'41426178c19fc6f64d7b23439ac02b3c9ca36231c8123371236e6b351952b5d8','name':NAME,'uuid':UUID,'tag':TAG,'count':COUNT,'coalesce_ms':4,'read_bypass':1,'phase':'preflight','start_unix':time.time()};save(out,x)
 proc=None
 try:
  if not empty_dm():raise RuntimeError('preexisting DM target')
  if (CONF/'memory_backed').read_text().strip()!='1' or (CONF/'power').read_text().strip()!='1' or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity/config mismatch')
  if pathlib.Path('/sys/module/dm_swapz/srcversion').read_text().strip()!=run(['modinfo','-F','srcversion',MODULE])['stdout'].strip():raise RuntimeError('wrong loaded module')
  cycle();mm=(SYS/'dev').read_text().strip();table=f'0 {COUNT*8} swapz3 {mm} 0 64 0 2 4 0 1 0 1';x['table_requested']=table;x['lower_before']=stat()
  run(['sudo','-n','dmsetup','create',NAME,'--uuid',UUID,'--noudevrules','--noudevsync','--table',table])
  actual=run(['sudo','-n','dmsetup','table',NAME])['stdout'].strip();info=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',NAME])['stdout'].strip()
  if actual!=table or info.split(':')[-1]!='0':raise RuntimeError(f'DM identity mismatch {actual} {info}')
  node=f'/dev/dm-{info.split(":")[1]}';x.update({'table_actual':actual,'dm_info':info,'dm_node':node,'status_before':status()})
  argv=['sudo','-n','insmod',HELPER,f'target={node}',f'count={COUNT}',f'hold_after_submit_ms=1000',f'run_tag={TAG}'];x['helper_command']=list(map(str,argv));x['phase']='submission';save(out,x)
  proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  marker=f'SV3QUEUE submitted tag={TAG} count={COUNT}'
  deadline=time.monotonic()+30;found=False
  while time.monotonic()<deadline:
   d=call(['sudo','-n','dmesg','--time-format','iso'])
   if marker in d.get('stdout',''):
    x['submitted_marker_seen']=True;x['submission_dmesg']=d['stdout'][-12000:];found=True;break
   if proc.poll() is not None:break
   time.sleep(.01)
  if not found:
   stdout,stderr=proc.communicate(timeout=120);x['helper_result']={'rc':proc.returncode,'stdout':stdout,'stderr':stderr};raise RuntimeError('did not observe 1024-BIO submission marker')
  x['status_at_suspend_request']=status();x['lower_at_suspend_request']=stat()
  t0=time.monotonic_ns();x['suspend']=call(['sudo','-n','dmsetup','suspend',NAME],t=120);x['suspend_elapsed_ns']=time.monotonic_ns()-t0
  if x['suspend']['rc']:raise RuntimeError(f'dmsetup suspend failed: {x["suspend"]}')
  x['suspended_info']=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','suspended,major,minor,open',NAME])['stdout'].strip();x['status_after_suspend']=status()
  stdout,stderr=proc.communicate(timeout=120);x['helper_result']={'rc':proc.returncode,'stdout':stdout,'stderr':stderr}
  if pathlib.Path('/sys/module/sv3_queue_probe').exists():x['helper_unload']=sudo('rmmod','sv3_queue_probe')
  if proc.returncode or 'errors=0' not in (run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-20000:]):raise RuntimeError('queue helper did not report complete success')
  x['resume']=call(['sudo','-n','dmsetup','resume',NAME],t=60)
  if x['resume']['rc']:raise RuntimeError(f'resume failed: {x["resume"]}')
  x['status_after_resume']=status();x['lower_after_resume']=stat();x['verify']=call(['sudo','-n',VERIFY,node,str(COUNT)],t=180)
  x['kernel_log']=run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-30000:]
  f=fields(x['status_after_resume'])
  if x['verify']['rc'] or f.get('failed')!='0' or f.get('logical_write')!=str(COUNT*4096):raise RuntimeError(f'suspend/resume/data verification failed: verify={x["verify"]} fields={f}')
  x['target_fields_after_resume']=f
  if stat()[8]:raise RuntimeError('lower I/O in flight at teardown')
  q=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',NAME])['stdout'].strip()
  if q.split(':')[-1]!='0':raise RuntimeError(f'open references before cleanup {q}')
  x['remove']=sudo('dmsetup','remove','--uuid',UUID)
  if not empty_dm() or list((SYS/'holders').iterdir()):raise RuntimeError('ordinary teardown incomplete')
  cycle();x['phase']='PASS';x['end_unix']=time.time();save(out,x)
  print(json.dumps({'phase':'PASS','suspended_info':x['suspended_info'],'suspend_seconds':x['suspend_elapsed_ns']/1e9,'verify':x['verify']['stdout'].strip(),'windows':f.get('windows'),'window_records':f.get('window_records'),'target_write_reqs':f.get('physical_write_reqs'),'trial':str(out)},sort_keys=True));return 0
 except Exception as e:
  if proc is not None and proc.poll() is None:
   stdout,stderr=proc.communicate(timeout=120);x['helper_result']={'rc':proc.returncode,'stdout':stdout,'stderr':stderr}
  x['phase']='FAILED_OR_PRESERVED';x['error']=repr(e);x['end_unix']=time.time();save(out,x);print(f'PRESERVED {NAME} UUID={UUID} error={e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
