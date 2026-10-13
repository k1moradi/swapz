#!/usr/bin/env python3
"""Run actual upper PREFLUSH/FUA/discard BIO checks on the owned null_blk target."""
import hashlib,json,pathlib,subprocess,sys,time
E=pathlib.Path('/tmp/swapz-alpha8-evidence');NULL='/dev/nullb_swapz_pr59_68dca6f'
CONF=pathlib.Path('/sys/kernel/config/nullb/nullb_swapz_pr59_68dca6f');SYS=pathlib.Path('/sys/block/nullb_swapz_pr59_68dca6f')
MODULE=E/'build/dm-swapz-W1.ko';HELPER=pathlib.Path(__file__).parents[1]/'helpers/sv3-barrier-probe.ko'
def call(a,t=120):
 p=subprocess.run(list(map(str,a)),text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=t)
 return {'argv':list(map(str,a)),'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
def run(a,t=120):
 x=call(a,t)
 if x['rc']:raise RuntimeError(json.dumps(x))
 return x
def sudo(*a,t=120):return run(['sudo','-n',*a],t)
def stat():return [int(v) for v in (SYS/'stat').read_text().split()]
def status(n):return run(['sudo','-n','dmsetup','status',n])['stdout'].strip()
def fields(s):return dict(z.split('=',1) for z in s.split() if '=' in z)
def save(p,x):p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix('.tmp');q.write_text(json.dumps(x,indent=2)+'\n');q.replace(p)
def empty_dm():return run(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() in ('','No devices found')
def cycle():
 if not empty_dm() or list((SYS/'holders').iterdir()) or stat()[8]:raise RuntimeError('refuse reset with mapping/holder/inflight IO')
 sudo('sh','-c',f"printf '0\\n' > {CONF/'power'}")
 deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('power off failed')
 sudo('sh','-c',f"printf '1\\n' > {CONF/'power'}")
 deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists() or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity changed')
def main():
 label='barrier-fua-discard';name='swz59barrier';uuid='SWZ59-BARRIER-FUA-DISCARD';out=E/'barriers'/f'{label}.json'
 x={'label':label,'source_sha':'68dca6fcd2b322524555becfd54d475cdaf973e1','module_sha256':hashlib.sha256(MODULE.read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256(HELPER.read_bytes()).hexdigest(),'name':name,'uuid':uuid,'phase':'preflight','start_unix':time.time()};save(out,x)
 try:
  if not empty_dm():raise RuntimeError('preexisting DM mapping')
  if (CONF/'memory_backed').read_text().strip()!='1' or (CONF/'power').read_text().strip()!='1' or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity/config mismatch')
  if pathlib.Path('/sys/module/dm_swapz/srcversion').read_text().strip()!=run(['modinfo','-F','srcversion',MODULE])['stdout'].strip():raise RuntimeError('wrong loaded module')
  cycle();before=stat();mm=(SYS/'dev').read_text().strip();table=f'0 32768 swapz3 {mm} 0 64 0 2 4 0 1 0 1'
  x.update({'table_requested':table,'backing_before':before,'null_mm':mm});run(['sudo','-n','dmsetup','create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table])
  actual=run(['sudo','-n','dmsetup','table',name])['stdout'].strip();info=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
  if actual!=table or info.split(':')[-1]!='0':raise RuntimeError(f'mapping identity mismatch: {actual}, {info}')
  node=f'/dev/dm-{info.split(":")[1]}';x.update({'table_actual':actual,'dm_info':info,'dm_node':node,'status_before':status(name)})
  x['helper']=call(['sudo','-n','insmod',HELPER,f'target={node}'],t=180)
  if pathlib.Path('/sys/module/sv3_barrier_probe').exists():x['helper_remove']=sudo('rmmod','sv3_barrier_probe')
  x['status_after_helper']=status(name);x['backing_after_helper']=stat();x['kernel_log']=run(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-30000:]
  x['helper_lines']=[line for line in x['kernel_log'].splitlines() if 'SV3BAR' in line and ('2026-10-13T' in line)]
  f=fields(x['status_after_helper']);x['target_fields']=f
  after=x['backing_after_helper'];x['lower_delta']={'read_requests':after[0]-before[0],'read_sectors_512':after[2]-before[2],'write_requests':after[4]-before[4],'write_sectors_512':after[6]-before[6],'discard_requests':after[11]-before[11],'discard_sectors_512':after[13]-before[13],'flush_requests':after[15]-before[15]}
  x['lower_delta']['read_bytes']=x['lower_delta']['read_sectors_512']*512;x['lower_delta']['write_bytes']=x['lower_delta']['write_sectors_512']*512
  if x['helper']['rc'] or f.get('failed')!='0' or int(f.get('flush_calls','0'))<4 or f.get('flush_calls')!=str(int(f.get('flush_ok','0'))+int(f.get('flush_err','0'))):raise RuntimeError(f'barrier/data test failed: rc={x["helper"]["rc"]} fields={f}')
  if stat()[8]:raise RuntimeError('inflight lower IO before cleanup')
  q=run(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
  if q.split(':')[-1]!='0':raise RuntimeError(f'DM target open at cleanup: {q}')
  x['remove']=sudo('dmsetup','remove','--uuid',uuid)
  if not empty_dm() or list((SYS/'holders').iterdir()):raise RuntimeError('ordinary teardown did not clear owned target/holder')
  cycle();x['backing_after_reset']=stat();x['phase']='PASS';x['end_unix']=time.time();save(out,x)
  print(json.dumps({'phase':'PASS','flush_calls':f.get('flush_calls'),'flush_ok':f.get('flush_ok'),'flush_err':f.get('flush_err'),'lower_delta':x['lower_delta'],'helper':x['helper']['rc'],'trial':str(out)},sort_keys=True));return 0
 except Exception as e:
  x['phase']='FAILED_OR_PRESERVED';x['error']=repr(e);x['end_unix']=time.time();save(out,x);print(f'PRESERVED {name} UUID={uuid} error={e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
