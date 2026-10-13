#!/usr/bin/env python3
"""Create one deterministic 4 KiB page whose actual raw-LZ4 output is 3535 B."""
import ctypes
import ctypes.util
import hashlib
import json
import random
import sys
from pathlib import Path

PAGE = 4096
CAPACITY = 3568
SEED = 0
REPEATED_SUFFIX = 587

def main(out):
    libname = ctypes.util.find_library('lz4')
    if not libname:
        raise SystemExit('liblz4 unavailable')
    lz = ctypes.CDLL(libname)
    lz.LZ4_versionString.restype = ctypes.c_char_p
    lz.LZ4_compress_fast.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lz.LZ4_compress_fast.restype = ctypes.c_int
    lz.LZ4_decompress_safe.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lz.LZ4_decompress_safe.restype = ctypes.c_int
    base = random.Random(SEED).randbytes(PAGE)
    page = bytearray(base)
    page[-REPEATED_SUFFIX:] = page[:REPEATED_SUFFIX]
    src = ctypes.create_string_buffer(bytes(page))
    compressed = ctypes.create_string_buffer(CAPACITY)
    length = lz.LZ4_compress_fast(src, compressed, PAGE, CAPACITY, 1)
    if length != 3535:
        raise SystemExit(f'expected 3535 B from pinned fixture inputs, got {length}')
    restored = ctypes.create_string_buffer(PAGE)
    decoded = lz.LZ4_decompress_safe(compressed, restored, length, PAGE)
    if decoded != PAGE or restored.raw != bytes(page):
        raise SystemExit('independent LZ4 roundtrip failed')
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(page)
    manifest = {
        'seed': SEED,
        'generator': 'random.Random(seed).randbytes(4096), then copy first 587 bytes to final 587 bytes',
        'lz4': 'LZ4_compress_fast(input=4096, capacity=3568, acceleration=1)',
        'liblz4_path': libname,
        'liblz4_version': lz.LZ4_versionString().decode(),
        'compressed_length': length,
        'raw_fallback': False,
        'decompression_roundtrip': 'PASS',
        'page_path': str(out),
        'page_sha256': hashlib.sha256(page).hexdigest(),
        'compressed_sha256': hashlib.sha256(compressed.raw[:length]).hexdigest(),
    }
    out.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))

if __name__ == '__main__':
    if len(sys.argv) != 2: raise SystemExit('usage: make-full-destination-fixture.py PAGE.bin')
    main(sys.argv[1])
