#!/usr/bin/env python3
"""Replay the archived PR #56 1024-BIO fixture on an owned null_blk target."""
import argparse, hashlib, json, os, pathlib, subprocess, sys, time

E = pathlib.Path('/tmp/swapz-alpha8-evidence')
NULL = '/dev/nullb_swapz_pr59_68dca6f'
CONF = pathlib.Path('/sys/kernel/config/nullb/nullb_swapz_pr59_68dca6f')
SYS = pathlib.Path('/sys/block/nullb_swapz_pr59_68dca6f')
FIXTURE = pathlib.Path(__file__).parents[1] / 'fixtures/alpha5-1024-pages.bin'
HELPER = pathlib.Path(__file__).parents[1] / 'helpers/sv3-queue-probe.ko'
VERIFY = E / 'build/verify-queue'
CANDIDATES = {
    'v22': ('3a89ebbeba21c814dcf724e227b31d38445a3f9a', E/'build/dm-swapz-v22.ko', 'v22'),
    'pr57': ('2e71c0c90b7f6f4ec96340583a0bc5c517bae97c', E/'build/dm-swapz-pr57.ko', 'pr57'),
    'a8off': ('68dca6fcd2b322524555becfd54d475cdaf973e1', E/'build/dm-swapz-W1.ko', 'a8off'),
    'a8on': ('68dca6fcd2b322524555becfd54d475cdaf973e1', E/'build/dm-swapz-W1.ko', 'a8on'),
}

def cmd(argv, timeout=120):
    t = time.monotonic_ns()
    p = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout)
    return {'argv': list(map(str, argv)), 'rc': p.returncode, 'stdout': p.stdout,
            'stderr': p.stderr, 'elapsed_ns': time.monotonic_ns()-t}

def checked(argv, timeout=120):
    x = cmd(argv, timeout)
    if x['rc']:
        raise RuntimeError(json.dumps(x))
    return x

def sudo(*args, timeout=120):
    return checked(['sudo', '-n', *map(str, args)], timeout)

def stat():
    return [int(x) for x in (SYS/'stat').read_text().split()]

def statdict(a):
    return {'read_requests':a[0], 'read_sectors_512':a[2], 'write_requests':a[4],
            'write_sectors_512':a[6], 'inflight':a[8], 'flush_requests':a[15]}

def parse_status(s):
    out={}
    for x in s.split():
        if '=' in x:
            k,v=x.split('=',1);out[k]=v
    return out

def swap_id(s):
    # /proc/swaps Used changes as normal host activity continues; identity is
    # filename, type, configured size, and priority, matching the prior gate.
    return sorted(tuple(x.split()[i] for i in (0,1,2,4)) for x in s.splitlines()[1:] if x.strip())

def save(p,o):
    p.parent.mkdir(parents=True,exist_ok=True)
    t=p.with_suffix('.tmp');t.write_text(json.dumps(o,indent=2)+'\n');t.replace(p)

def module_switch(module):
    loaded=pathlib.Path('/sys/module/dm_swapz/srcversion')
    wanted=checked(['modinfo','-F','srcversion',str(module)])['stdout'].strip()
    current=loaded.read_text().strip() if loaded.exists() else None
    commands=[]
    if current!=wanted:
        if current:
            rows=[x.split() for x in checked(['lsmod'])['stdout'].splitlines()[1:]
                  if x.split() and x.split()[0]=='dm_swapz']
            if len(rows)!=1 or rows[0][2]!='0':
                raise RuntimeError(f'dm_swapz is not exclusively unused: {rows}')
            commands.append(sudo('rmmod','dm_swapz'))
            if loaded.exists(): raise RuntimeError('old module remains loaded after rmmod')
        commands.append(sudo('insmod',module))
    if not loaded.exists() or loaded.read_text().strip()!=wanted:
        raise RuntimeError(f'loaded module srcversion mismatch: wanted {wanted}')
    return {'path':str(module),'sha256':hashlib.sha256(module.read_bytes()).hexdigest(),
            'srcversion':wanted,'commands':commands}

def power_cycle():
    if cmd(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found'):
        raise RuntimeError('refuse null_blk power cycle while any DM mapping exists')
    if list((SYS/'holders').iterdir()) or stat()[8]!=0:
        raise RuntimeError('refuse null_blk power cycle with holders or inflight I/O')
    sudo('sh','-c',f"printf '0\\n' > {CONF/'power'}")
    deadline=time.monotonic()+5
    while SYS.exists() and time.monotonic()<deadline: time.sleep(.05)
    if SYS.exists(): raise RuntimeError('owned null_blk failed to power off')
    sudo('sh','-c',f"printf '1\\n' > {CONF/'power'}")
    deadline=time.monotonic()+10
    while not SYS.exists() and time.monotonic()<deadline: time.sleep(.05)
    if not SYS.exists(): raise RuntimeError('owned null_blk failed to power on')
    if (SYS/'dev').read_text().strip()!='251:0' or (CONF/'memory_backed').read_text().strip()!='1':
        raise RuntimeError('owned null_blk identity changed across reset')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--candidate',choices=CANDIDATES,required=True)
    ap.add_argument('--rep',type=int,required=True)
    a=ap.parse_args()
    source,module,kind=CANDIDATES[a.candidate]
    name=f'swz59q-{a.candidate}-r{a.rep}'
    uuid=f'SWZ59Q-{a.candidate.upper()}-R{a.rep}'
    out=E/'burst-concurrent'/f'{a.candidate}-r{a.rep}.json'
    data={'candidate':a.candidate,'source_sha':source,'module_path':str(module),
          'module_sha256':hashlib.sha256(module.read_bytes()).hexdigest(),
          'helper_sha256':hashlib.sha256(HELPER.read_bytes()).hexdigest(),
          'fixture_sha256':hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
          'fixture_bytes':FIXTURE.stat().st_size,'target_name':name,'target_uuid':uuid,
          'logical_pages':1024,'logical_bytes':4194304,'initial_phase':'preflight',
          'start_unix':time.time()}
    save(out,data)
    try:
        if not (CONF/'power').exists() or (CONF/'memory_backed').read_text().strip()!='1':
            raise RuntimeError('owned null_blk identity/config failed')
        if (SYS/'dev').read_text().strip()!='251:0':
            raise RuntimeError('owned null_blk major:minor changed')
        if (CONF/'power').read_text().strip()!='1': raise RuntimeError('null_blk is not powered')
        if list((SYS/'holders').iterdir()): raise RuntimeError('existing backing holders')
        if any(x.split() and x.split()[0] == NULL for x in pathlib.Path('/proc/swaps').read_text().splitlines()[1:]):
            raise RuntimeError('owned null_blk unexpectedly active as swap')
        if cmd(['dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found'):
            raise RuntimeError('existing DM mapping prevents test')
        swaps=pathlib.Path('/proc/swaps').read_text()
        if swap_id(swaps)!=swap_id((E/'benchmark/swaps-initial.txt').read_text()):
            raise RuntimeError('swap inventory differs from baseline')
        # Verify the candidate module is actually loaded from the selected artifact.
        data['module']=module_switch(module)
        power_cycle()
        if kind=='v22': table=f'0 8192 swapz {NULL} opportunistic 64'
        elif kind=='pr57': table=f'0 8192 swapz3 {NULL} 0 64 0 2 0 0 1 0'
        else: table=f'0 8192 swapz3 {NULL} 0 64 0 2 0 0 1 0 {1 if kind=="a8on" else 0}'
        data['table_requested']=table
        data['backing_before']={'path':NULL,'major_minor':(SYS/'dev').read_text().strip(),
                                'config':{x:(CONF/x).read_text().strip() for x in
                                ['size','memory_backed','blocksize','mbps','completion_nsec','queue_mode','hw_queue_depth','submit_queues','power']},
                                'stat':stat()}
        major,minor=(SYS/'dev').read_text().strip().split(':')
        table_actual=table.replace(NULL,f'{major}:{minor}')
        sudo('dmsetup','create',name,'--uuid',uuid,'--noudevrules','--noudevsync','--table',table)
        got_table=checked(['sudo','-n','dmsetup','table',name])['stdout'].strip()
        got_uuid=checked(['sudo','-n','dmsetup','info','-c','--noheadings','-o','uuid',name])['stdout'].strip()
        info=checked(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
        if got_table!=table_actual or got_uuid!=uuid or info.split(':')[-1]!='0':
            raise RuntimeError(f'target identity mismatch table={got_table!r} uuid={got_uuid!r} info={info!r}')
        dmdev=f'/dev/dm-{info.split(":")[1]}'
        data.update({'table_actual':got_table,'uuid_actual':got_uuid,'dm_info':info,'dm_device':dmdev})
        data['status_before']=checked(['sudo','-n','dmsetup','status',name])['stdout'].strip()
        data['lower_before']=stat()
        data['phase']='concurrent_submission';save(out,data)
        p=cmd(['sudo','-n','insmod',HELPER,f'target={dmdev}','count=1024'],timeout=240)
        data['queue_probe']=p
        data['kernel_log_after_queue']=cmd(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-50000:]
        if pathlib.Path('/sys/module/sv3_queue_probe').exists():
            data['helper_unload']=sudo('rmmod','sv3_queue_probe')
        data['status_after_writes']=checked(['sudo','-n','dmsetup','status',name])['stdout'].strip()
        data['lower_after_writes']=stat()
        lower0=statdict(data['lower_before']);lower1=statdict(data['lower_after_writes'])
        data['lower_delta']={k:lower1[k]-lower0[k] for k in lower0 if k not in ('inflight',)}
        data['lower_delta']['read_bytes']=data['lower_delta']['read_sectors_512']*512
        data['lower_delta']['write_bytes']=data['lower_delta']['write_sectors_512']*512
        data['verify_command']=[str(VERIFY),dmdev,'1024']
        data['verification']=cmd(['sudo','-n',*map(str,data['verify_command'])],180)
        data['lower_after_verify']=stat()
        data['status_after_verify']=checked(['sudo','-n','dmsetup','status',name])['stdout'].strip()
        if data['queue_probe']['rc'] or data['verification']['rc']:
            raise RuntimeError('concurrent queue write or full-image verification failed')
        f=parse_status(data['status_after_writes'])
        if kind!='v22' and (f.get('failed')!='0' or (kind=='a8off' and f.get('read_bypassed')!='0')):
            raise RuntimeError(f'candidate failed or unexpected bypass activity: {f}')
        if stat()[8]!=0: raise RuntimeError('backing I/O remains in flight')
        if swap_id(pathlib.Path('/proc/swaps').read_text())!=swap_id(swaps):
            raise RuntimeError('swap inventory changed')
        info=checked(['sudo','-n','dmsetup','info','-c','--noheadings','-o','major,minor,open',name])['stdout'].strip()
        if info.split(':')[-1]!='0': raise RuntimeError('DM mapping still open')
        data['status_before_remove']=checked(['sudo','-n','dmsetup','status',name])['stdout'].strip()
        data['remove']=sudo('dmsetup','remove','--uuid',uuid)
        if cmd(['sudo','-n','dmsetup','ls','--noheadings'])['stdout'].strip() not in ('','No devices found'):
            raise RuntimeError('mapping remained after ordinary remove')
        if list((SYS/'holders').iterdir()): raise RuntimeError('backing holder remains after removal')
        power_cycle()
        data['backing_after_reset']=stat()
        data['kernel_log_final']=cmd(['sudo','-n','dmesg','--time-format','iso'])['stdout'][-50000:]
        data['phase']='PASS';data['end_unix']=time.time();save(out,data)
        print(json.dumps({'candidate':a.candidate,'trial':str(out),'phase':data['phase'],
            'queue_rc':p['rc'],'verify':data['verification']['stdout'].strip(),
            'lower_delta':data['lower_delta'],'status':f},sort_keys=True))
        return 0
    except Exception as e:
        data['phase']='FAILED_OR_PRESERVED';data['error']=repr(e);data['end_unix']=time.time();save(out,data)
        print(f'PRESERVED mapping={name} UUID={uuid} error={e}',file=sys.stderr)
        return 1

if __name__=='__main__': sys.exit(main())
