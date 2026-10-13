#!/usr/bin/env python3
"""Summarize a null_blk-filtered block trace without treating issues as completions."""
import collections
import json
import re
import sys
from pathlib import Path

RX = re.compile(r"block_(rq_issue|rq_complete|bio_queue|bio_complete):\s+(\d+),(\d+)\s+(\S+)(?:\s+(\d+))?")

def main(path):
    rows = []
    for line in Path(path).read_text(errors='replace').splitlines():
        m = RX.search(line)
        if not m:
            continue
        event, major, minor, rwbs, size = m.groups()
        rows.append({'event': event, 'major': int(major), 'minor': int(minor),
                     'rwbs': rwbs, 'bytes': int(size) if size else None, 'line': line})
    out = {'trace_file': str(path), 'events': len(rows), 'counts': {},
           'rq_issue_by_operation': dict(collections.Counter(
               'flush' if 'F' in x['rwbs'] else 'write' if 'W' in x['rwbs'] else 'read'
               for x in rows if x['event'] == 'rq_issue')),
           'rq_complete_by_operation': dict(collections.Counter(
               'flush' if 'F' in x['rwbs'] else 'write' if 'W' in x['rwbs'] else 'read'
               for x in rows if x['event'] == 'rq_complete')),
           'zero_byte_rq_issues': [x['line'] for x in rows if x['event'] == 'rq_issue' and x['bytes'] == 0],
           'devices': sorted({f"{x['major']}:{x['minor']}" for x in rows})}
    out['counts'] = dict(collections.Counter(x['event'] for x in rows))
    print(json.dumps(out, indent=2))

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: summarize-block-trace.py TRACE')
    main(sys.argv[1])
