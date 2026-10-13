#!/usr/bin/env python3
"""Deterministic *synthetic* anonymous-memory-style 4KiB swap page generator.

Never reads process memory, /proc/<pid>/mem, user files, live swap or storage.
Only writes user-chosen regular output files. Profiles are hypotheses, not a
measurement of a Linux workload's population. Measures actual liblz4 output.
"""
import argparse
import ctypes
import ctypes.util
import hashlib
import json
import random
import struct
from collections import Counter
from pathlib import Path

PAGE = 4096
CAP = 3568
PROFILES = ("zero", "heap", "text", "cow", "raster", "mixed", "entropy")
DEFAULT_WEIGHTS = "zero=8,heap=32,text=20,cow=12,raster=15,mixed=8,entropy=5"


def deterministic_bytes(seed, index, domain, n):
    label = (str(seed) + ":" + str(index) + ":" + domain).encode()
    return hashlib.shake_256(label).digest(n)


def page_bytes(seed, index, profile):
    raw = deterministic_bytes(seed, index, profile, PAGE)
    b = bytearray(PAGE)
    if profile == "zero":
        return bytes(b)
    if profile == "entropy":
        return raw
    if profile == "heap":
        # Array of live tagged heap objects with zero padding and repeated
        # field names. Object contents vary by slot; fill ratio is controlled.
        live = 20 + (index * 37) % 70
        for pos in range(0, PAGE * live // 100, 48):
            rec = (b"object:memory\0" +
                   struct.pack("<IIQ", pos, index % 17, index * 17 + pos) +
                   b"flags:data\0")
            b[pos:min(pos + len(rec), PAGE)] = rec[:PAGE - pos]
    elif profile == "text":
        lines = [b"def update_cache(node, value):\n",
                 b"    if node is None: return value\n",
                 b"    node.next = node.next or value\n",
                 b"    return node.data + 1\n",
                 b"class Renderer: # structured text buffer\n"]
        out = b"".join(lines[(index + i) % len(lines)] for i in range(180))
        b[:] = out[:PAGE].ljust(PAGE, b" ")
    elif profile == "cow":
        # Dirty private copy-on-write page shaped like executable/data
        # sections, NOT evidence that clean file-backed ELF pages swap.
        b[:] = (b"\x48\x89\xe5\x90\x90\x90\x00\x00" * 512)
        for off in range(index % 19, PAGE, 257):
            b[off:off + 8] = raw[off:off + 8]
    elif profile == "raster":
        # Decoded in-memory RGBA pixel buffer: a few palette colors,
        # repeated scan lines and a little per-pixel variation.
        colors = ((32, 48, 64, 255), (84, 108, 132, 255),
                  (220, 228, 240, 255), (245, 122, 55, 255))
        for pixel in range(PAGE // 4):
            rgba = colors[((pixel // 32) + (pixel // 256) + index) % 4]
            b[pixel * 4:pixel * 4 + 4] = bytes(rgba)
            if pixel % 23 == 0:
                b[pixel * 4] = raw[pixel]
    elif profile == "mixed":
        # Partial high-entropy / partial sparse anonymous application
        # buffer, without guessing that every byte is readily compressed.
        prefix = 512 + (index * 29) % 3072
        b[:prefix] = raw[:prefix]
        for pos in range(prefix, PAGE, 64):
            b[pos:min(pos + 16, PAGE)] = b"MEM:node:value:42"[:PAGE - pos]
    else:
        raise ValueError(profile)
    return bytes(b)


def parse_weights(text):
    weights = {}
    for item in text.split(","):
        name, separator, number = item.partition("=")
        if not separator or name not in PROFILES or name in weights:
            raise ValueError("invalid/duplicate profile: " + item)
        value = int(number)
        if value < 0:
            raise ValueError("negative weight: " + item)
        weights[name] = value
    if not any(weights.values()):
        raise ValueError("all weights are zero")
    return weights


def schedule(seed, count, weights):
    total = sum(weights.values())
    quotas = {name: count * value // total for name, value in weights.items()}
    missing = count - sum(quotas.values())
    # Largest remainder, stable tie-break using public profile order.
    order = sorted(weights, key=lambda n: (-(count * weights[n] % total),
                                            PROFILES.index(n)))
    for name in order[:missing]:
        quotas[name] += 1
    names = [name for name in PROFILES for _ in range(quotas.get(name, 0))]
    random.Random(seed).shuffle(names)
    assert len(names) == count
    return names


def lz4_compressor():
    name = ctypes.util.find_library("lz4")
    if not name:
        raise RuntimeError("liblz4 unavailable: install ordinary liblz4 runtime")
    lib = ctypes.CDLL(name)
    compress = lib.LZ4_compress_fast
    compress.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                         ctypes.c_int, ctypes.c_int)
    compress.restype = ctypes.c_int
    return compress


def measure(compress, page):
    source = ctypes.create_string_buffer(page, PAGE)
    output = ctypes.create_string_buffer(CAP)
    size = compress(source, output, PAGE, CAP, 1)
    if not 0 <= size <= CAP:
        raise RuntimeError("invalid liblz4 result")
    return size  # 0 means no compressed payload within the output cap


def classify(size):
    if size == 0:
        return "raw"
    if size <= 256:
        return "1_256"
    if size <= 1024:
        return "257_1024"
    if size <= 2048:
        return "1025_2048"
    if size <= 3072:
        return "2049_3072"
    return "3073_3568"


def generate(seed, count, weights, compress):
    names = schedule(seed, count, weights)
    payload = bytearray()
    counts = Counter()
    histogram = Counter()
    profile_histogram = {name: Counter() for name in PROFILES}
    total_compressed = 0
    for index, name in enumerate(names):
        page = page_bytes(seed, index, name)
        if len(page) != PAGE:
            raise RuntimeError("fixture output is not exactly 4096 bytes")
        size = measure(compress, page)
        bucket = classify(size)
        payload.extend(page)
        counts[name] += 1
        histogram[bucket] += 1
        profile_histogram[name][bucket] += 1
        if size:
            total_compressed += size
    result = {
        "definition": "synthetic anonymous-memory-style, not sampled Linux swap",
        "seed": seed, "pages": count, "page_bytes": PAGE,
        "compression": "liblz4 LZ4_compress_fast(src=4096, max_dst=3568, accel=1)",
        "requested_profile_weights": weights,
        "profile_pages": dict(counts),
        "lz4_size_buckets": dict(histogram),
        "profile_lz4_buckets": {k: dict(v) for k, v in profile_histogram.items()},
        "lz4_accepted_payload_bytes": total_compressed,
        "raw_pages": histogram["raw"],
        "raw_page_bytes": histogram["raw"] * PAGE,
        "fixture_sha256": hashlib.sha256(payload).hexdigest(),
    }
    return bytes(payload), result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-prefix", type=Path, required=True)
    ap.add_argument("--pages", type=int, default=1024)
    ap.add_argument("--seed", type=lambda s: int(s, 0), default=0x51A0A9)
    ap.add_argument("--weights", default=DEFAULT_WEIGHTS)
    args = ap.parse_args()
    if not 1 <= args.pages <= 65536:
        ap.error("--pages must be in 1..65536")
    weights = parse_weights(args.weights)
    content, manifest = generate(args.seed, args.pages, weights,
                                 lz4_compressor())
    args.output_prefix.parent.mkdir(parents=True, exist_ok=True)
    args.output_prefix.with_suffix(".bin").write_bytes(content)
    args.output_prefix.with_suffix(".json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
