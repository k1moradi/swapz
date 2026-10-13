#!/usr/bin/env python3
import hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path('/root/swapz-pr57-validation')
E=ROOT/'evidence/gc-write-fault-rerun'
E.mkdir(parents=True,exist_ok=True)
NULLNAME='nullb_swapz_pr57_2e71c0c9';NULL=f'/dev/{NULLNAME}'
SYS=Path('/sys/block')/NULLNAME;CONF=Path('/sys/kernel/config/nullb')/NULLNAME
MOD=ROOT/'pr57/kernel/extent-v3/dm-swapz.ko'
HELP=Path('/home/keivan/swapz-gc-fault-fixture')
FIX=ROOT/'evidence/sustained/fixtures/mixed-1024-pages.bin'
SECTORS=8192*8

def run(argv,timeout=240):
 t=time.monotonic();p=subprocess.run(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 return {'argv':list(map(str,argv)),'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_s':time.monotonic()-t}
def check(argv,timeout=120):
 r=run(argv,timeout)
 if r['rc']:raise RuntimeError(f'command failed: {r}')
 return r
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def parse_status(x):
 t=x.split();return dict(a.split('=',1) for a in t[3:] if '=' in a)
def blockstat():return [int(x) for x in (SYS/'stat').read_text().split()]
def stat_fields(x):return {'read_reqs':x[0],'read_sectors_512':x[2],'write_reqs':x[4],'write_sectors_512':x[6],'inflight':x[8],'flush_reqs':x[15]}
def no_dm():
 s=check(['dmsetup','ls','--noheadings'])['stdout'].strip();return not s or s=='No devices found'
def swap_identity(text):
 return sorted(tuple(row.split()[i] for i in (0,1,2,4)) for row in text.splitlines()[1:] if row.split())
def wait_open(name):
 t=time.monotonic()+5; seen=[]
 while time.monotonic()<t:
  x=check(['dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip();seen.append(x)
  if x.endswith(':0'):return seen
  time.sleep(.1)
 return seen
def cycle():
 if not no_dm() or list((SYS/'holders').iterdir()) or blockstat()[8]:raise RuntimeError('refuse owned null_blk reset with mapping, holders, or in-flight I/O')
 if (CONF/'memory_backed').read_text().strip()!='1':raise RuntimeError('owned backing lost memory_backed flag')
 (CONF/'power').write_text('0\n');deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('owned null_blk failed to power off')
 (CONF/'power').write_text('1\n');deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists():raise RuntimeError('owned null_blk failed to power on')
 for k,v in [('size','40'),('memory_backed','1'),('blocksize','512'),('mbps','20'),('completion_nsec','500000'),('queue_mode','2'),('hw_queue_depth','64'),('submit_queues','1')]:
  if (CONF/k).read_text().strip()!=v:raise RuntimeError(f'config changed: {k}')
def module_ready():
 want=check(['modinfo','-F','srcversion',str(MOD)])['stdout'].strip();p=Path('/sys/module/dm_swapz/srcversion');have=p.read_text().strip() if p.exists() else None
 if have!=want:
  if have:
   rows=[x.split() for x in check(['lsmod'])['stdout'].splitlines()[1:] if x.split() and x.split()[0]=='dm_swapz']
   if len(rows)!=1 or rows[0][2]!='0':raise RuntimeError(f'cannot unload module refcount: {rows}')
   check(['rmmod','dm_swapz'])
  check(['insmod',str(MOD)])
 if not p.exists() or p.read_text().strip()!=want:raise RuntimeError('wrong module loaded')
 return {'path':str(MOD),'sha256':sha(MOD),'srcversion':want}
def one(label,nth):
 name='swz57-gc-'+label;uuid='SWZ57-GC-'+label.upper();out=E/f'{label}.json'
 if not no_dm():raise RuntimeError('unexpected preexisting mapping')
 r={'label':label,'fault_nth':nth,'started':time.time(),'module':module_ready(),'fixture_sha256':sha(FIX),'helper_sha256':sha(HELP),'nullb':NULL,'major_minor':(SYS/'dev').read_text().strip(),'config':{k:(CONF/k).read_text().strip() for k in ['size','memory_backed','blocksize','mbps','completion_nsec','queue_mode','hw_queue_depth','submit_queues','power']},'swaps_before':Path('/proc/swaps').read_text(),'backing_before':blockstat(),'dmesg_before':check(['dmesg','--time-format','iso'])['stdout'][-10000:]}
 table=f'0 {SECTORS} swapz3 {NULL} 0 64 0 2 0 0 1 {nth}'
 r['table_requested']=table;r['create']=check(['dmsetup','create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table])
 r['table_actual']=check(['dmsetup','table',name])['stdout'].strip();r['uuid_actual']=check(['dmsetup','info','-c','--noheadings','-o','uuid',name])['stdout'].strip()
 r['open_settle']=wait_open(name)
 if r['table_actual']!=table.replace(NULL,'251:0') or r['uuid_actual']!=uuid or not r['open_settle'][-1].endswith(':0'):raise RuntimeError('DM table, UUID, or open count mismatch')
 # DM creation can trigger an asynchronous udev block-device probe. Drain
 # that event before injecting a fail-closed I/O error so the probe itself
 # cannot issue a read through an already-failed target.
 r['udevadm_settle']=run(['udevadm','settle','--timeout=30'],30)
 if r['udevadm_settle']['rc']!=0:raise RuntimeError(f"udev did not settle before fault test: {r['udevadm_settle']}")
 r['open_after_udev_settle']=wait_open(name)
 if not r['open_after_udev_settle'][-1].endswith(':0') or blockstat()[8]:raise RuntimeError('target open count or backing in-flight I/O did not settle after udev')
 dmdev='/dev/dm-'+r['open_settle'][-1].split(':')[1];r['dmdev']=dmdev
 cmd=[str(HELP),'--device',dmdev,'--fixture',str(FIX),'--pages','8192','--hot-pages','128','--overwrites','1024','--trigger-page','0']
 if nth:r['helper_command']=cmd+['--expect-write-eio'];r['helper']=run(r['helper_command'],300)
 else:r['helper_command']=cmd;r['helper']=run(cmd,300)
 r['status_after']=check(['dmsetup','status',name])['stdout'].strip();r['status_fields']=parse_status(r['status_after']);r['backing_after']=blockstat();a=stat_fields(r['backing_before']);b=stat_fields(r['backing_after']);r['backing_delta']={k:b[k]-a[k] for k in a if k!='inflight'};r['backing_delta']['read_bytes']=r['backing_delta']['read_sectors_512']*512;r['backing_delta']['write_bytes']=r['backing_delta']['write_sectors_512']*512
 r['inflight_after']=r['backing_after'][8];r['open_before_remove']=wait_open(name);r['dmesg_after']=check(['dmesg','--time-format','iso'])['stdout'][-30000:];r['swaps_after']=Path('/proc/swaps').read_text();r['swap_identity_before']=swap_identity(r['swaps_before']);r['swap_identity_after']=swap_identity(r['swaps_after'])
 if r['swap_identity_before']!=r['swap_identity_after']:raise RuntimeError('active swap identities changed during owned test')
 hs=[x.name for x in (SYS/'holders').iterdir()]
 if r['inflight_after'] or len(hs)!=1:raise RuntimeError(f'unsafe removal preflight inflight={r["inflight_after"]} holders={hs}')
 if len(hs)!=1:raise RuntimeError(f'expected exactly this target holder, got {hs}')
 r['holder_names_before_remove']=hs
 if r['open_before_remove'][-1].split(':')[-1]!='0':raise RuntimeError('DM open count did not settle to zero')
 r['ordinary_remove']=check(['dmsetup','remove','--uuid',uuid]);r['dm_after_remove']=check(['dmsetup','ls','--tree'])['stdout'];r['holders_after_remove']=[x.name for x in (SYS/'holders').iterdir()]
 if not no_dm() or r['holders_after_remove']:raise RuntimeError('owned target or backing holder remains')
 cycle();r['backing_stat_after_cycle']=blockstat();r['dmesg_final']=check(['dmesg','--time-format','iso'])['stdout'][-30000:];r['completed']=time.time()
 f=r['status_fields'];h=r['helper'];out_text=h.get('stdout','');out_err=h.get('stderr','')
 if nth:
  r['verdict']='PASS' if h['rc']==0 and 'EXPECTED_PRESSURE_WRITE_EIO' in out_text and 'NO_POST_FAILURE_READS_ISSUED' in out_text and f.get('write_fault_calls')=='9217' and f.get('write_fault_injected')=='1' and f.get('failed')=='1' and f.get('error')=='-5' and int(f.get('gc_read_reqs','0'))>0 and int(f.get('gc_write_reqs','0'))>0 and int(f.get('gc_role_rotations','0'))==int(f.get('gc_victims','-1')) and int(f.get('gc_selected_pages','0'))>int(f.get('gc_pages','0')) else 'FAIL_NOT_TARGETED_GC_WRITE'
 else:
  r['verdict']='PASS' if h['rc']==0 and 'mismatches=0 result=PASS' in out_text and f.get('failed')=='0' and int(f.get('gc_role_rotations','0'))>=1 and int(f.get('gc_read_reqs','0'))>0 and int(f.get('gc_write_reqs','0'))>0 else 'FAIL_GC_CONTROL'
 r['helper_stderr']=out_err
 save=out.with_suffix('.tmp');save.write_text(json.dumps(r,indent=2)+'\n');save.replace(out)
 print(json.dumps({'label':label,'verdict':r['verdict'],'helper_rc':h['rc'],'status':r['status_fields'],'backing_delta':r['backing_delta'],'teardown':'PASS'},sort_keys=True))
 if r['verdict']!='PASS':raise RuntimeError(f'GC test did not meet its assertions: {r["verdict"]}')
 return r
if __name__=='__main__':
 if len(sys.argv)!=2 or sys.argv[1] not in {'control','fault'}:raise SystemExit('usage: run-gc-fault-test.py control|fault')
 if not no_dm():raise SystemExit('unexpected existing DM mapping')
 if (SYS/'dev').read_text().strip()!='251:0' or (CONF/'power').read_text().strip()!='1' or (CONF/'memory_backed').read_text().strip()!='1':raise SystemExit('owned null_blk identity failed')
 one(sys.argv[1],0 if sys.argv[1]=='control' else 9217)
