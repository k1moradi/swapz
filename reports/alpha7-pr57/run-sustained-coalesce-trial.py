#!/usr/bin/env python3
import argparse,hashlib,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path('/root/swapz-pr57-validation')
E=ROOT/'evidence/sustained'
NULLNAME='nullb_swapz_pr57_2e71c0c9'
NULL=f'/dev/{NULLNAME}'
SYS=Path('/sys/block')/NULLNAME
CONF=Path('/sys/kernel/config/nullb')/NULLNAME
FIXTURE=Path(os.environ.get('SWAPZ_FIXTURE', E/'fixtures/mixed-1024-pages.bin'))
CLASSMAP=Path(os.environ.get('SWAPZ_CLASSMAP', E/'fixtures/mixed-1024-class.bin'))
BIN=E/'swapz-io-bench'
LOGICAL_PAGES=4096
SECTORS=LOGICAL_PAGES*8
CANDS={
 'v22':{'source':'3a89ebbeba21c814dcf724e227b31d38445a3f9a','module':ROOT/'v22/kernel/dm-swapz.ko','impl':'v22','bulk':0},
 'alpha6':{'source':'4324c98497891147896ad817f4593c5cc198953b','module':ROOT/'alpha6/kernel/extent-v3/dm-swapz.ko','impl':'alpha6','bulk':1},
 'alpha7':{'source':'0e199159cea3dd479224ce59513ee9c0a810a0d6','module':ROOT/'alpha7/kernel/extent-v3/dm-swapz.ko','impl':'alpha7','bulk':1},
 'pr57-b0':{'source':'2e71c0c90b7f6f4ec96340583a0bc5c517bae97c','module':ROOT/'pr57/kernel/extent-v3/dm-swapz.ko','impl':'pr57','bulk':0},
 'pr57-b1':{'source':'2e71c0c90b7f6f4ec96340583a0bc5c517bae97c','module':ROOT/'pr57/kernel/extent-v3/dm-swapz.ko','impl':'pr57','bulk':1},
 'pr57-b2':{'source':'2e71c0c90b7f6f4ec96340583a0bc5c517bae97c','module':ROOT/'pr57/kernel/extent-v3/dm-swapz.ko','impl':'pr57','bulk':2},
}
def call(argv,timeout=120):
 t=time.monotonic_ns();p=subprocess.run(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 return {'argv':argv,'rc':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'elapsed_ns':time.monotonic_ns()-t}
def checked(argv,timeout=120):
 r=call(argv,timeout)
 if r['rc']:raise RuntimeError(f'command failed: {r}')
 return r
def dm(*argv,timeout=30):return checked(['dmsetup',*argv],timeout)
def fields(text):return dict(x.split('=',1) for x in text.split() if '=' in x)
def read_stat():return [int(x) for x in (SYS/'stat').read_text().split()]
def stat_values(x):return {'read_requests':x[0],'read_sectors_512':x[2],'write_requests':x[4],'write_sectors_512':x[6],'inflight':x[8],'io_ticks_ms':x[9],'weighted_io_ticks_ms':x[10],'discard_requests':x[11],'discard_sectors_512':x[13],'flush_requests':x[15]}
def swap_identity(text):
 lines=text.splitlines()[1:]
 return sorted(tuple(row.split()[i] for i in (0,1,2,4)) for row in lines if row.split())
def no_dm():
 s=dm('ls','--noheadings')['stdout'].strip()
 return not s or s=='No devices found'
def sha_file(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def module_src(p):return checked(['modinfo','-F','srcversion',str(p)])['stdout'].strip()
def module_switch(c):
 if not no_dm():raise RuntimeError('existing mappings before module switch')
 if Path('/sys/module/sv3_queue_probe').exists() or Path('/sys/module/sv3_fault_probe').exists():raise RuntimeError('test helper remains loaded')
 p=c['module'];want=module_src(p);loaded=Path('/sys/module/dm_swapz/srcversion')
 curr=loaded.read_text().strip() if loaded.exists() else None;ev=[]
 if curr!=want:
  if curr:
   rows=[x.split() for x in checked(['lsmod'])['stdout'].splitlines()[1:] if x.split() and x.split()[0]=='dm_swapz']
   if len(rows)!=1 or rows[0][2]!='0':raise RuntimeError(f'dm_swapz not exclusively unused: {rows}')
   ev.append(checked(['rmmod','dm_swapz']))
   if loaded.exists():raise RuntimeError('old dm_swapz remains after rmmod')
  ev.append(checked(['insmod',str(p)]))
 if not loaded.exists() or loaded.read_text().strip()!=want:raise RuntimeError('loaded module srcversion differs from candidate')
 if sha_file(p)!=hashlib.sha256(p.read_bytes()).hexdigest():raise RuntimeError('module file hash unstable')
 target='swapz' if c['impl']=='v22' else 'swapz3'
 if not any(x.split() and x.split()[0]==target for x in checked(['dmsetup','targets'])['stdout'].splitlines()):raise RuntimeError(f'target {target} absent')
 return {'module_path':str(p),'module_sha256':sha_file(p),'srcversion':want,'switch_commands':ev,'target_type':target}
def power_cycle():
 if not no_dm():raise RuntimeError('refusing null_blk cycle with mappings')
 if list((SYS/'holders').iterdir()):raise RuntimeError('refusing null_blk cycle with holders')
 if read_stat()[8]!=0:raise RuntimeError('refusing null_blk cycle with lower I/O in flight')
 if (CONF/'memory_backed').read_text().strip()!='1':raise RuntimeError('owned device not memory backed')
 (CONF/'power').write_text('0\n')
 deadline=time.monotonic()+5
 while SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if SYS.exists():raise RuntimeError('owned null_blk did not power off')
 (CONF/'power').write_text('1\n')
 deadline=time.monotonic()+10
 while not SYS.exists() and time.monotonic()<deadline:time.sleep(.05)
 if not SYS.exists():raise RuntimeError('owned null_blk did not power on')
 for attr,val in [('size','40'),('memory_backed','1'),('blocksize','512'),('mbps','20'),('completion_nsec','500000'),('queue_mode','2'),('hw_queue_depth','64'),('submit_queues','1')]:
  if (CONF/attr).read_text().strip()!=val:raise RuntimeError(f'null_blk config mismatch {attr}')
def wait_open_zero(name,seconds=3):
 info=dm('info','-c','--noheadings','-o','major,minor,open',name)['stdout'].strip();initial=info
 deadline=time.monotonic()+seconds
 while info.split(':')[-1]!='0' and time.monotonic()<deadline:
  time.sleep(.1);info=dm('info','-c','--noheadings','-o','major,minor,open',name)['stdout'].strip()
 return initial,info
def parse_json(out):
 lines=[x for x in out.splitlines() if x.startswith('{') and x.endswith('}')]
 if not lines:raise RuntimeError(f'no JSON from helper: {out}')
 return json.loads(lines[-1])
def save(path,obj):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2)+'\n');tmp.replace(path)
def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--candidate',choices=CANDS,required=True)
 ap.add_argument('--rep',type=int,required=True)
 ap.add_argument('--qd',type=int,choices=[1,4,8,32],required=True)
 ap.add_argument('--read-pct',type=int,choices=[0,20,30,50],default=20)
 ap.add_argument('--coalesce-ms',type=int,choices=[0,1,2,4],default=0)
 ap.add_argument('--warmup',type=int,default=10)
 ap.add_argument('--seconds',type=int,default=30)
 ap.add_argument('--label-suffix',default='')
 a=ap.parse_args();c=CANDS[a.candidate]
 if a.coalesce_ms and c['impl']!='pr57':ap.error('nonzero coalesce-ms is only supported by PR #57')
 label=f'{a.candidate}-qd{a.qd}-rp{a.read_pct}-r{a.rep}-c{a.coalesce_ms}'
 if a.label_suffix: label += f'-{a.label_suffix}'
 out=E/'trials'/label;out.mkdir(parents=True,exist_ok=False)
 name=('swz57sc-'+a.candidate.replace('pr57-','p').replace('alpha','a')+f'-q{a.qd}-p{a.read_pct}-r{a.rep}-c{a.coalesce_ms}')[:63]
 uuid=('SWZ57SC-'+a.candidate.upper().replace('-','_')+f'-QD{a.qd}-P{a.read_pct}-R{a.rep}-C{a.coalesce_ms}')[:120]
 r={'label':label,'candidate':a.candidate,'source_sha':c['source'],'profile':{'backend':'null_blk','size_mib':40,'memory_backed':1,'logical_block':512,'mbps':20,'completion_nsec':500000,'queue_mode':2,'hw_queue_depth':64,'submit_queues':1,'logical_pages':LOGICAL_PAGES,'writer_pages':1024,'reader_start':2048,'reader_pages':1024,'lower_bulk':None if c['impl']=='v22' else c['bulk'],'gc':2 if c['impl']!='v22' else None,'window':64 if c['impl']!='v22' else 64,'coalesce_ms':a.coalesce_ms if c['impl']=='pr57' else None,'read_pct':a.read_pct,'warmup_s':a.warmup,'measurement_s':a.seconds,'qd':a.qd},'fixture_sha256':sha_file(FIXTURE),'classmap_sha256':sha_file(CLASSMAP),'target_name':name,'target_uuid':uuid,'start_wall':time.time(),'phase':'preflight'}
 def checkpoint():save(out/'trial.json',r)
 try:
  if not no_dm():raise RuntimeError('unexpected existing DM mapping')
  r['swaps_before']=Path('/proc/swaps').read_text()
  swaps_baseline=(ROOT/'evidence/swaps-initial.txt').read_text()
  if swap_identity(r['swaps_before'])!=swap_identity(swaps_baseline):raise RuntimeError('active swap devices differ from initial task inventory')
  r['module']=module_switch(c);power_cycle()
  if (CONF/'power').read_text().strip()!='1' or (SYS/'dev').read_text().strip()!='251:0':raise RuntimeError('owned null_blk identity failed')
  if list((SYS/'holders').iterdir()):raise RuntimeError('unexpected backing holder')
  if NULL in [x.split()[0] for x in Path('/proc/swaps').read_text().splitlines()[1:]]:raise RuntimeError('owned null_blk active swap')
  if subprocess.run(['findmnt','-rn','-S',NULL],capture_output=True,text=True).stdout.strip():raise RuntimeError('owned null_blk mounted')
  r['backing_before']={'device':NULL,'major_minor':(SYS/'dev').read_text().strip(),'stat':read_stat(),'config':{x:(CONF/x).read_text().strip() for x in ['size','memory_backed','blocksize','mbps','completion_nsec','queue_mode','hw_queue_depth','submit_queues','power']}}
  if c["impl"] == "v22":
   table="0 %d swapz %s opportunistic 64" % (SECTORS,NULL)
  elif c["impl"] == "pr57":
   table="0 %d swapz3 %s 0 64 0 2 %d 0 %d 0" % (SECTORS,NULL,a.coalesce_ms,c["bulk"])
  else:
   table="0 %d swapz3 %s 0 64 0 2 0 0 %d" % (SECTORS,NULL,c["bulk"])
  r['table_requested']=table;checkpoint()
  r['create']=dm('create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table)
  actual=dm('table',name)['stdout'].strip();actual_uuid=dm('info','-c','--noheadings','-o','uuid',name)['stdout'].strip();initial,quiescent=wait_open_zero(name)
  r['table_actual']=actual;r['uuid_actual']=actual_uuid;r['dm_info_initial']=initial;r['dm_info_quiescent']=quiescent
  if actual!=table.replace(NULL,'251:0') or actual_uuid!=uuid or quiescent.split(':')[-1]!='0':raise RuntimeError('DM table/UUID/open-count preflight mismatch')
  dmdev='/dev/dm-'+quiescent.split(':')[1];r['dm_device']=dmdev
  cmd=[str(BIN),'--device',dmdev,'--fixture',str(FIXTURE),'--classmap',str(CLASSMAP),'--logical-pages',str(LOGICAL_PAGES),'--writer-pages','1024','--reader-start','2048','--reader-pages','1024','--seed','0x57a7c0de']
  r['phase']='prefill';checkpoint();r['prefill_command']=cmd+['--mode','prefill'];r['prefill']=call(r['prefill_command'],180)
  if r['prefill']['rc']:raise RuntimeError('prefill failed')
  r['status_after_prefill']=dm('status',name)['stdout'].strip()
  r['verify_prefill_command']=cmd+['--mode','verify'];r['verify_prefill']=call(r['verify_prefill_command'],180)
  if r['verify_prefill']['rc']:raise RuntimeError('initial full-image verification failed')
  r['prefill_stat_after_verify']=read_stat()
  r['phase']='warmup';checkpoint();warmmap=str(out/'warm-map.bin')
  r['warmup_command']=cmd+['--mode','run','--qd',str(a.qd),'--read-pct',str(a.read_pct),'--seconds',str(a.warmup),'--map-out',warmmap]
  r['warmup']=call(r['warmup_command'],a.warmup+60)
  if r['warmup']['rc'] or parse_json(r['warmup']['stdout']).get('errors') or parse_json(r['warmup']['stdout']).get('mismatches'):raise RuntimeError('warm-up IO failed')
  r['status_before_measurement']=dm('status',name)['stdout'].strip()
  r['stat_before_measurement']=read_stat()
  r['phase']='measurement';checkpoint()
  r['measurement_command']=cmd+['--mode','run','--qd',str(a.qd),'--read-pct',str(a.read_pct),'--seconds',str(a.seconds),'--seed','0x57a7c0de','--map-in',warmmap,'--map-out',str(out/'final-map.bin'),'--csv',str(out/'latency.csv')]
  t0=time.time();r['measurement']=call(r['measurement_command'],a.seconds+120);r['measurement_wall_s']=time.time()-t0
  r['status_after_measurement']=dm('status',name)['stdout'].strip();r['stat_after_measurement']=read_stat()
  f=fields(r['status_after_measurement']);m=parse_json(r['measurement']['stdout']) if r['measurement']['stdout'].strip() else {}
  r['measurement_summary']=m
  r['lower_delta']={k:stat_values(r['stat_after_measurement'])[k]-stat_values(r['stat_before_measurement'])[k] for k in ['read_requests','read_sectors_512','write_requests','write_sectors_512','flush_requests','discard_requests']}
  r['lower_delta']['read_bytes']=r['lower_delta']['read_sectors_512']*512;r['lower_delta']['write_bytes']=r['lower_delta']['write_sectors_512']*512
  r['target_status_fields_after_measurement']=f
  before_fields=fields(r['status_before_measurement'])
  tracked=['physical_write','physical_write_reqs','physical_read','physical_read_reqs','write_submitted','write_submitted_reqs','read_submitted','read_submitted_reqs','bulk_io','bulk_extents','bulk_padding','bulk_mixed_io','bulk_raw_only_io','bulk_raw_entries','compressed','raw','windows','window_records','one_page_windows','win1','win2','win3_4','win5_8','win9_16','win17_64','coalesce_deferred','coalesce_urgent','worker_requeues','gc_victims','gc_role_rotations','gc_read','gc_write','gc_read_reqs','gc_write_reqs','write_fault_calls','write_fault_injected']
  r['target_counter_deltas']={k:int(f.get(k,0))-int(before_fields.get(k,0)) for k in tracked}
  r['verification']=None
  if r['measurement']['rc']==0 and m.get('errors')==0 and m.get('mismatches')==0 and (c['impl']=='v22' or (f.get('failed')=='0' and f.get('error')=='0')) and read_stat()[8]==0:
   r['phase']='verification';checkpoint();r['verification_command']=cmd+['--mode','verify','--map-in',str(out/'final-map.bin')];r['verification']=call(r['verification_command'],180);r['stat_after_verification']=read_stat()
  else:r['verification']='SKIPPED_TARGET_FAILED_OR_IO_ERROR'
  r['dmesg_after']=call(['dmesg','--time-format','iso'])['stdout'][-30000:]
  r['swap_after']=Path('/proc/swaps').read_text()
  if swap_identity(r['swap_after'])!=swap_identity(r['swaps_before']):raise RuntimeError('active swap devices changed during trial')
  r['phase']='teardown-preflight';checkpoint()
  if read_stat()[8]!=0:raise RuntimeError('lower IO remains in-flight; quarantine target')
  if Path('/sys/module/sv3_queue_probe').exists() or Path('/sys/module/sv3_fault_probe').exists():raise RuntimeError('test helper remains loaded')
  initial,quiescent=wait_open_zero(name);r['dm_info_before_remove']={'initial':initial,'quiescent':quiescent}
  if quiescent.split(':')[-1]!='0':raise RuntimeError('DM target still open; quarantine')
  holders=[p.name for p in (SYS/'holders').iterdir()]
  if len(holders)!=1:raise RuntimeError(f'unexpected lower holders: {holders}')
  r['ordinary_remove']=dm('remove','--uuid',uuid);r['dm_after_remove']=dm('ls','--tree')['stdout']
  if not no_dm() or list((SYS/'holders').iterdir()):raise RuntimeError('owned DM did not cleanly detach')
  power_cycle();r['backing_stat_after_reset']=read_stat()
  r['phase']='PASS' if r['verification'] and isinstance(r['verification'],dict) and r['verification']['rc']==0 else 'FAIL_DATA_OR_IO'
  r['end_wall']=time.time();checkpoint()
  print(json.dumps({'label':label,'phase':r['phase'],'verification':r['verification']['stdout'].strip() if isinstance(r['verification'],dict) else r['verification'],'measure':r['measurement_summary'],'lower_delta':r['lower_delta'],'target_failed':f.get('failed'),'gc_victims':f.get('gc_victims'),'rotation':f.get('gc_role_rotations')},sort_keys=True))
  return 0 if r['phase']=='PASS' else 1
 except Exception as e:
  r['phase']='QUARANTINED_OR_FAILED';r['error']=repr(e);r['end_wall']=time.time();checkpoint();print(f'PRESERVED: {e}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
