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
