#!/usr/bin/env python3
"""Reproduce a full 3535-byte-survivor destination on owned null_blk only."""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/tmp/swapz-pr59-validation')
EVIDENCE = Path('/tmp/swapz-alpha8-evidence/full-destination')
EVIDENCE.mkdir(parents=True, exist_ok=True)
NULLNAME = 'nullb_swapz_pr59_68dca6f'
NULL = f'/dev/{NULLNAME}'
SYS = Path('/sys/block') / NULLNAME
CONF = Path('/sys/kernel/config/nullb') / NULLNAME
MODULE = Path('/tmp/swapz-alpha8-evidence/build/dm-swapz-W1.ko')
HELPER = Path('/tmp/swapz-alpha8-evidence/build/full-destination-write')
FIXTURE = ROOT / 'reports/alpha8/fixtures/full-destination-3535-page.bin'
TRACEFS = Path('/sys/kernel/tracing')
PAGES = 8192   # 32 MiB logical target; 32 MiB foreground after V3 reserve.
SECTORS = PAGES * 8
NAME = 'swz59-full-destination'
UUID = 'SWZ59-FULL-3535B'


def run(argv, timeout=300):
    p = subprocess.run(list(map(str, argv)), text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout)
    return {'argv': list(map(str, argv)), 'rc': p.returncode,
            'stdout': p.stdout, 'stderr': p.stderr}


def checked(argv, timeout=120):
    result = run(argv, timeout)
    if result['rc']:
        raise RuntimeError(f'command failed: {result}')
    return result


def no_dm():
    text = checked(['dmsetup', 'ls', '--noheadings'])['stdout'].strip()
    return not text or text == 'No devices found'


def swaps_identity(text):
    return sorted(tuple(row.split()[i] for i in (0, 1, 2, 4))
                  for row in text.splitlines()[1:] if row.split())


def blockstat():
    return [int(x) for x in (SYS / 'stat').read_text().split()]


def status_fields(text):
    fields = {}
    for item in text.split()[3:]:
        if '=' in item:
            k, v = item.split('=', 1)
            fields[k] = v
    return fields


def wait_open():
    seen = []
    end = time.monotonic() + 5
    while time.monotonic() < end:
        text = checked(['dmsetup', 'info', '-c', '--noheadings', '-o',
                        'major,minor,open', NAME])['stdout'].strip()
        seen.append(text)
        if text.endswith(':0'):
            return seen
        time.sleep(.1)
    return seen


def main():
    if len(sys.argv) != 1:
        raise SystemExit('run without arguments; edits belong in the source constants')
    if not no_dm():
        raise SystemExit('BLOCKED: pre-existing DM mapping present')
    if (SYS / 'dev').read_text().strip() != '251:0':
        raise SystemExit('BLOCKED: owned null_blk major:minor changed')
    if (CONF / 'memory_backed').read_text().strip() != '1':
        raise SystemExit('BLOCKED: backing is not memory-backed')
    if (CONF / 'power').read_text().strip() != '1':
        raise SystemExit('BLOCKED: owned null_blk is not powered')
    for attr, expected in [('size', '40'), ('blocksize', '512'), ('mbps', '20'),
                           ('completion_nsec', '500000'), ('queue_mode', '2'),
                           ('hw_queue_depth', '64'), ('submit_queues', '1')]:
        if (CONF / attr).read_text().strip() != expected:
            raise SystemExit(f'BLOCKED: unexpected null_blk config {attr}')
    if list((SYS / 'holders').iterdir()) or blockstat()[8] != 0:
        raise SystemExit('BLOCKED: lower device has a holder or I/O in flight')
    if NULL in [x.split()[0] for x in Path('/proc/swaps').read_text().splitlines()[1:]]:
        raise SystemExit('BLOCKED: null_blk is active swap')
    if not MODULE.is_file() or not HELPER.is_file() or not FIXTURE.is_file():
        raise SystemExit('BLOCKED: verified module/helper/fixture missing')
    wanted_src = checked(['modinfo', '-F', 'srcversion', MODULE])['stdout'].strip()
    loaded = Path('/sys/module/dm_swapz/srcversion')
    current_src = loaded.read_text().strip() if loaded.exists() else None
    commands = []
    if current_src != wanted_src:
        if current_src:
            lsmod = checked(['lsmod'])['stdout'].splitlines()[1:]
            rows = [line.split() for line in lsmod
                    if line.split() and line.split()[0] == 'dm_swapz']
            if len(rows) != 1 or rows[0][2] != '0':
                raise RuntimeError(f'BLOCKED: dm_swapz is not exclusively unused: {rows}')
            commands.append(checked(['rmmod', 'dm_swapz']))
        commands.append(checked(['insmod', MODULE]))
    if not loaded.exists() or loaded.read_text().strip() != wanted_src:
        raise RuntimeError('loaded module srcversion mismatch')
    if not any(line.split() and line.split()[0] == 'swapz3'
               for line in checked(['dmsetup', 'targets'])['stdout'].splitlines()):
        raise RuntimeError('swapz3 target is not registered')

    swaps_before = Path('/proc/swaps').read_text()
    dmesg_before = checked(['dmesg', '--time-format=iso'])['stdout'][-20000:]
    before = blockstat()
    trace_path = TRACEFS / 'instances' / f'swapz_alpha8_full_{os.getpid()}'
    trace_path.mkdir()
    (trace_path / 'tracing_on').write_text('0\n')
    try:
        (trace_path / 'trace_clock').write_text('mono\n')
    except OSError:
        pass
    try:
        (trace_path / 'buffer_size_kb').write_text('16384\n')
    except OSError:
        pass
    major, minor = map(int, (SYS / 'dev').read_text().strip().split(':'))
    trace_dev = (major << 20) | minor
    trace_events = ['block_rq_issue', 'block_rq_complete',
                    'block_bio_queue', 'block_bio_complete']
    for event in trace_events:
        event_path = trace_path / 'events' / 'block' / event
        (event_path / 'enable').write_text('0\n')
        (event_path / 'filter').write_text(f'dev == {trace_dev}\n')
    (trace_path / 'trace').write_text('')
    for event in trace_events:
        (trace_path / 'events' / 'block' / event / 'enable').write_text('1\n')
    (trace_path / 'tracing_on').write_text('1\n')
    table = f'0 {SECTORS} swapz3 {NULL} 0 64 0 2 1 0 1 0 0'
    record = {
        'source_sha': '68dca6fcd2b322524555becfd54d475cdaf973e1',
        'module_path': str(MODULE),
        'module_sha256': hashlib.sha256(MODULE.read_bytes()).hexdigest(),
        'module_srcversion': wanted_src,
        'helper_sha256': hashlib.sha256(HELPER.read_bytes()).hexdigest(),
        'fixture_sha256': hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        'fixture_lz4_length': 3535,
        'backing': NULL,
        'major_minor': (SYS / 'dev').read_text().strip(),
        'config': {k: (CONF / k).read_text().strip() for k in
                   ['size', 'memory_backed', 'blocksize', 'mbps',
                    'completion_nsec', 'queue_mode', 'hw_queue_depth',
                    'submit_queues', 'power']},
        'logical_pages': PAGES,
        'table_requested': table,
        'table_args': {'read_cap': 0, 'window': 64, 'verify': 0,
                       'gc_policy': 2, 'coalesce_ms': 1,
                       'test_fail_flush_nth': 0, 'lower_bulk': 1,
                       'test_fail_write_nth': 0, 'read_bypass': 0},
        'module_switch_commands': commands,
        'swaps_before': swaps_before,
        'backing_stat_before': before,
        'dmesg_before': dmesg_before,
        'phase': 'preflight',
    }
    path = EVIDENCE / 'loaded-full-destination.json'
    path.write_text(json.dumps(record, indent=2) + '\n')
    try:
        record['create'] = checked(['dmsetup', 'create', NAME, '--uuid', UUID,
                                    '--noudevrules', '--noudevsync', '--table', table])
        actual = checked(['dmsetup', 'table', NAME])['stdout'].strip()
        uuid = checked(['dmsetup', 'info', '-c', '--noheadings', '-o', 'uuid', NAME])['stdout'].strip()
        settle = run(['udevadm', 'settle', '--timeout=30'], 35)
        opens = wait_open()
        expected_table = table.replace(NULL, (SYS / 'dev').read_text().strip())
        if actual != expected_table or uuid != UUID or not opens[-1].endswith(':0'):
            raise RuntimeError('DM identity/table/open-count verification failed')
        if settle['rc'] != 0 or blockstat()[8] != 0:
            raise RuntimeError('udev/lower I/O did not quiesce before target use')
        dmdev = '/dev/dm-' + opens[-1].split(':')[1]
        record.update({'table_actual': actual, 'uuid_actual': uuid,
                       'udev_settle': settle, 'open_samples': opens,
                       'dm_device': dmdev, 'phase': 'writes'})
        path.write_text(json.dumps(record, indent=2) + '\n')
        record['write_command'] = [str(HELPER), '--device', dmdev,
                                   '--fixture', str(FIXTURE), '--pages', str(PAGES),
                                   '--qd', '32', '--extra-writes', '1',
                                   '--results', str(EVIDENCE / 'completed-pages.csv'),
                                   '--expect-enospc']
        record['writer'] = run(record['write_command'], 600)
        record['status_after'] = checked(['dmsetup', 'status', NAME])['stdout'].strip()
        record['status_fields'] = status_fields(record['status_after'])
        record['backing_stat_after'] = blockstat()
        record['backing_delta'] = {
            'read_requests': record['backing_stat_after'][0] - before[0],
            'read_sectors_512': record['backing_stat_after'][2] - before[2],
            'write_requests': record['backing_stat_after'][4] - before[4],
            'write_sectors_512': record['backing_stat_after'][6] - before[6],
            'inflight': record['backing_stat_after'][8],
        }
        record['backing_delta']['read_bytes'] = record['backing_delta']['read_sectors_512'] * 512
        record['backing_delta']['write_bytes'] = record['backing_delta']['write_sectors_512'] * 512
        (trace_path / 'tracing_on').write_text('0\n')
        trace_file = EVIDENCE / 'lower-block-trace.txt'
        trace_data = (trace_path / 'trace').read_text()
        trace_file.write_text(trace_data)
        record['lower_block_trace'] = {
            'path': str(trace_file), 'device': f'{major}:{minor}',
            'events': trace_events,
            'lines': sum('block_' in line for line in trace_data.splitlines()),
        }
        for event in trace_events:
            (trace_path / 'events' / 'block' / event / 'enable').write_text('0\n')
        trace_path.rmdir()
        record['dmesg_after'] = checked(['dmesg', '--time-format=iso'])['stdout'][-30000:]
        record['swaps_after'] = Path('/proc/swaps').read_text()
        if swaps_identity(swaps_before) != swaps_identity(record['swaps_after']):
            raise RuntimeError('active swap identities changed')
        record['inflight_before_remove'] = blockstat()[8]
        holder_paths = list((SYS / 'holders').iterdir())
        record['holder_names_before_remove'] = [x.name for x in holder_paths]
        target_info = checked(['dmsetup', 'info', '-c', '--noheadings', '-o',
                               'name,uuid,major,minor,open', NAME])['stdout'].strip().split(':')
        expected_holder_dev = f'{target_info[2]}:{target_info[3]}'
        record['holder_identity_before_remove'] = [
            {'name': holder.name, 'resolved': str(holder.resolve()),
             'dev': (holder / 'dev').read_text().strip()}
            for holder in holder_paths
        ]
        record['open_before_remove'] = wait_open()
        if record['inflight_before_remove'] != 0:
            raise RuntimeError('lower I/O remains in-flight; preserve owned target')
        if (len(holder_paths) != 1 or
                (holder_paths[0] / 'dev').read_text().strip() != expected_holder_dev):
            raise RuntimeError('unexpected lower-device holder; preserve owned target')
        if not record['open_before_remove'][-1].endswith(':0'):
            raise RuntimeError('DM target still has open references; preserve owned target')
        record['ordinary_remove'] = checked(['dmsetup', 'remove', '--uuid', UUID])
        record['dm_after_remove'] = checked(['dmsetup', 'ls', '--tree'])['stdout']
        record['holders_after_remove'] = [x.name for x in (SYS / 'holders').iterdir()]
        if not no_dm() or record['holders_after_remove']:
            raise RuntimeError('owned DM mapping/holder remains after ordinary removal')
        record['phase'] = 'CLEANED'
        record['test_verdict'] = 'PASS' if (
            record['writer']['rc'] == 0
            and 'EXPECTED_ENOSPC' in record['writer']['stdout']
            and record['status_fields'].get('failed') == '1'
            and int(record['status_fields'].get('gc_no_headroom_skips', '0')) > 0
            and int(record['status_fields'].get('gc_read', '0')) == 0
            and int(record['status_fields'].get('gc_write', '0')) == 0
            and int(record['status_fields'].get('gc_role_rotations', '0')) == 0
            and int(record['status_fields'].get('error', '0')) == -28
            and record['backing_delta']['inflight'] == 0
        ) else 'FAIL_OR_DIVERGENT_BEHAVIOR'
        record['completed'] = time.time()
        path.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps({'verdict': record['test_verdict'],
                          'writer': record['writer']['stdout'],
                          'status': record['status_fields'],
                          'backing_delta': record['backing_delta'],
                          'teardown': 'ordinary removal PASS'}))
        return 0 if record['test_verdict'] == 'PASS' else 1
    except Exception as exc:
        if trace_path.exists():
            try:
                (trace_path / 'tracing_on').write_text('0\n')
                partial = EVIDENCE / 'lower-block-trace-partial.txt'
                partial.write_text((trace_path / 'trace').read_text())
                for event in trace_events:
                    (trace_path / 'events' / 'block' / event / 'enable').write_text('0\n')
                trace_path.rmdir()
                record['lower_block_trace_partial'] = str(partial)
            except Exception as trace_exc:
                record['trace_cleanup_error'] = repr(trace_exc)
        record.update({'phase': 'QUARANTINED_OR_FAILED', 'error': repr(exc),
                       'completed': time.time()})
        path.write_text(json.dumps(record, indent=2) + '\n')
        print(f'PRESERVED EVIDENCE: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
