#!/usr/bin/env python3
"""Rootless bounded packing benchmark, not a loaded-kernel latency benchmark."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random

from model import POLICIES, BLOCK_BYTES, Replay


def synthetic_trace(name: str, *, operations: int, window: int, working_set: int,
                    seed: int) -> list[tuple[int, bytes]]:
    if name not in ('fio50', 'fio75', 'clustered', 'mixed', 'hotcold'):
        raise ValueError('unknown synthetic trace')
    if operations < 1 or working_set < window:
        raise ValueError('working set smaller than bounded flush window')
    generator = random.Random(seed)
    result = []
    for start in range(0, operations, window):
        count = min(window, operations - start)
        if name == 'hotcold':
            # Bias 80% of the window toward a fixed hot subset without ever
            # duplicating a slot within one unresolved flush window.
            hot_pool = max(count, working_set // 8)
            hot_size = min(hot_pool, round(count * 0.8))
            cold_size = min(working_set - hot_pool, count - hot_size)
            hot_size = count - cold_size
            slots = (generator.sample(range(hot_pool), hot_size) +
                     generator.sample(range(hot_pool, working_set), cold_size))
            generator.shuffle(slots)
        else:
            slots = [(start + position) % working_set for position in range(count)]
        for position, slot in enumerate(slots):
            if name == 'fio50':
                length = 2072
            elif name == 'fio75':
                length = 1048
            elif name == 'clustered':
                length = 2200 if position < count // 2 else 1600
            elif name == 'mixed':
                length = generator.choice((600, 1048, 1600, 2072, 2200, 3500))
            else:
                length = generator.choice((1048, 1600, 2072, 2200))
            result.append((slot, generator.randbytes(length)))
    return result


def audit_lengths_trace(path: Path, *, seed: int, window: int,
                        working_set: int) -> list[tuple[int, bytes]]:
    """Use exact sampled *lengths*, NOT any purported fio payload bytes."""
    generator = random.Random(seed)
    result = []
    with path.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream, delimiter='\t')
        if reader.fieldnames != ['page_index', 'payload_bytes', 'kind']:
            raise ValueError('invalid audit TSV header')
        for index, row in enumerate(reader):
            if row['page_index'] != str(index):
                raise ValueError('nonsequential audit index')
            kind = row['kind']
            size = int(row['payload_bytes'])
            if kind not in ('compressed', 'raw') or not (0 < size <= BLOCK_BYTES):
                raise ValueError('invalid audit payload type/length')
            if kind == 'compressed' and size > 3568:
                raise ValueError('sample exceeds tested LZ4 admission threshold')
            if kind == 'raw' and size != BLOCK_BYTES:
                raise ValueError('raw page length mismatch')
            result.append((index % working_set, generator.randbytes(size)))
    if not result:
        raise ValueError('empty audit trace')
    return result


def run_trace(trace: list[tuple[int, bytes]], *, policy: str,
              window: int, segments: int, reserve_segments: int,
              read_penalty_bytes: int, read_seed: int, reads: int = 256) -> dict:
    replay = Replay(policy, segment_count=segments, reserve_segments=reserve_segments,
                    window=window, read_penalty_bytes=read_penalty_bytes)
    # Raw 4096-byte audit pages remain intact; compressed payloads are stored
    # exactly as sampled/generated, without re-compressing arbitrary synthetic data.
    expected_by_slot = {}
    for slot, payload in trace:
        replay.stage(slot, payload, raw=len(payload) == BLOCK_BYTES)
        expected_by_slot[slot] = payload
    replay.flush()
    # A completed, no-error replay must return the *exact* final payload for
    # every slot, not merely a self-consistent CRC of the wrong generation.
    if not replay.failed_logical_writes and not replay.failed_gc_runs:
        for slot, expected in expected_by_slot.items():
            mapping = replay.mappings.get(slot)
            if mapping is None or replay._read_mapping(mapping)[0] != expected:
                raise AssertionError('incorrect final payload or generation mapping')
    generator = random.Random(read_seed)
    slots = sorted(replay.mappings)
    for _ in range(reads):
        if slots:
            slot = slots[generator.randrange(len(slots))]
            replay.read(slot)
    return replay.report()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', choices=('fio50', 'fio75', 'clustered', 'mixed', 'hotcold'),
                        default='fio50')
    parser.add_argument('--audit-lengths', type=Path)
    parser.add_argument('--operations', type=int, default=1536)
    parser.add_argument('--window', type=int, default=16)
    parser.add_argument('--working-set', type=int, default=384)
    parser.add_argument('--segments', type=int, default=6)
    parser.add_argument('--reserve-segments', type=int, default=1)
    parser.add_argument('--read-penalty-bytes', type=int, default=0)
    parser.add_argument('--reads', type=int, default=256)
    parser.add_argument('--seed', type=int, default=12345)
    arguments = parser.parse_args()
    if arguments.window < 1 or arguments.working_set < arguments.window or arguments.reads < 0:
        parser.error('window/working-set/reads violate bounds')
    if arguments.audit_lengths:
        trace = audit_lengths_trace(arguments.audit_lengths, seed=arguments.seed,
                                    window=arguments.window, working_set=arguments.working_set)
        origin = {'type': 'external-audit-lengths-only',
                  'path': str(arguments.audit_lengths),
                  'sha256': hashlib.sha256(arguments.audit_lengths.read_bytes()).hexdigest()}
    else:
        trace = synthetic_trace(arguments.trace, operations=arguments.operations,
                                window=arguments.window, working_set=arguments.working_set,
                                seed=arguments.seed)
        origin = {'type': 'synthetic-lengths-and-payloads', 'name': arguments.trace}
    results = [run_trace(trace, policy=policy, window=arguments.window,
                         segments=arguments.segments,
                         reserve_segments=arguments.reserve_segments,
                         read_penalty_bytes=arguments.read_penalty_bytes,
                         read_seed=arguments.seed ^ 0x5A17,
                         reads=arguments.reads) for policy in POLICIES]
    comparable = len({result['completed_logical_bytes'] for result in results}) == 1 and all(
        not result['failed_logical_writes'] and not result['failed_gc_runs'] for result in results)
    output = {'origin': origin, 'seed': arguments.seed, 'operations': len(trace),
              'window': arguments.window, 'working_set': arguments.working_set,
              'segments': arguments.segments,
              'reserve_segments': arguments.reserve_segments,
              'read_penalty_bytes': arguments.read_penalty_bytes,
              'comparison_valid': comparable,
              'results': results,
              'limitations': ['rootless simulator, not kernel measurement',
                              'CRC32 checksum (not CRC32C) validates synthetic bytes',
                              'no I/O concurrency, queueing, or real read p99',
                              'payload-length audit does not contain actual memory bytes']}
    print(json.dumps(output, sort_keys=True, indent=2))
    return 0 if comparable else 2


if __name__ == '__main__':
    raise SystemExit(main())
