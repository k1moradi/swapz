#!/usr/bin/env python3
"""Generate deterministic 4 KiB pages with exact raw-LZ4 output lengths.

This is a diagnostic payload fixture for the experimental 4 KiB best-fit
packer. It does not open devices or run a benchmark. Pages are compressed with
LZ4_compress_fast(acceleration=1), matching swapz's compression call and
3,568-byte maximum compressed payload.
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path
import random
from typing import Iterable

PAGE_BYTES = 4096
HEADER_BYTES = 8
DESCRIPTOR_BYTES = 8
MAX_COMPRESSED_BYTES = 3568
MAX_RECORDS = 64
PATTERNS = {
    "clustered": (2200,) * 8 + (1600,) * 8,
    "alternating": (2200, 1600) * 8,
    "uniform": (2072,) * 16,
}


class RawLZ4:
    def __init__(self) -> None:
        library = ctypes.util.find_library("lz4")
        if not library:
            raise RuntimeError("liblz4 is required for the payload fixture")
        self.library = ctypes.CDLL(library)
        self.compress = self.library.LZ4_compress_fast
        self.compress.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int,
        ]
        self.compress.restype = ctypes.c_int

    def length(self, page: bytes) -> int:
        if len(page) != PAGE_BYTES:
            raise ValueError("LZ4 input must be exactly 4 KiB")
        source = ctypes.create_string_buffer(page, PAGE_BYTES)
        destination = ctypes.create_string_buffer(MAX_COMPRESSED_BYTES)
        return int(self.compress(
            source, destination, PAGE_BYTES, MAX_COMPRESSED_BYTES, 1))


def pattern_lengths(pattern: str) -> tuple[int, ...]:
    try:
        return PATTERNS[pattern]
    except KeyError as exc:
        raise ValueError(f"unknown pattern: {pattern}") from exc


def container_count(lengths: Iterable[int]) -> int:
    """Count source-ordered 4 KiB containers under the V2.2 geometry."""
    blocks = 0
    count = 0
    payload = 0
    for length in lengths:
        if length <= 0 or length > MAX_COMPRESSED_BYTES:
            raise ValueError("fixture lengths must be successful compressed records")
        if (count >= MAX_RECORDS or
                HEADER_BYTES + DESCRIPTOR_BYTES * (count + 1) +
                payload + length > PAGE_BYTES):
            blocks += 1
            count = 0
            payload = 0
        count += 1
        payload += length
    return blocks + bool(count)


def bestfit_container_count(lengths: Iterable[int]) -> int:
    """Reproduce the bounded planner for all-compressed fixture records."""
    sizes = list(lengths)
    if len(sizes) > 128:
        return container_count(sizes)
    claimed: set[int] = set()
    blocks = 0
    while len(claimed) < len(sizes):
        first = next(i for i in range(len(sizes)) if i not in claimed)
        claimed.add(first)
        payload = sizes[first]
        records = 1
        blocks += 1
        while True:
            candidates = [
                i for i, size in enumerate(sizes)
                if i not in claimed and records < MAX_RECORDS and
                HEADER_BYTES + DESCRIPTOR_BYTES * (records + 1) +
                payload + size <= PAGE_BYTES
            ]
            if not candidates:
                break
            selected = max(candidates, key=lambda i: sizes[i])
            claimed.add(selected)
            records += 1
            payload += sizes[selected]
    return blocks


def _page_for_length(codec: RawLZ4, seed: int, index: int,
                     target: int) -> tuple[bytes, int]:
    # Every slot gets its own deterministic pseudorandom prefix. The zero tail
    # makes output size controllable without embedding a pre-compressed block.
    entropy = random.Random(seed ^ (index * 0x9E3779B97F4A7C15)).randbytes(PAGE_BYTES)
    preferred = range(max(0, target - 96), min(PAGE_BYTES, target + 1))
    for prefix in preferred:
        page = entropy[:prefix] + bytes(PAGE_BYTES - prefix)
        if codec.length(page) == target:
            return page, prefix
    for prefix in range(PAGE_BYTES + 1):
        page = entropy[:prefix] + bytes(PAGE_BYTES - prefix)
        if codec.length(page) == target:
            return page, prefix
    raise RuntimeError(f"could not construct exact {target}-byte LZ4 record")


def make_fixture(pattern: str, seed: int) -> tuple[bytes, dict[str, object]]:
    lengths = pattern_lengths(pattern)
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    codec = RawLZ4()
    pages = bytearray()
    observations: list[dict[str, object]] = []
    measured: list[int] = []
    for index, expected_length in enumerate(lengths):
        page, prefix = _page_for_length(codec, seed, index, expected_length)
        actual = codec.length(page)
        if actual != expected_length or actual <= 0:
            raise RuntimeError("payload did not meet its exact compressed length")
        measured.append(actual)
        pages.extend(page)
        observations.append({
            "logical_page": index,
            "expected_payload_bytes": expected_length,
            "measured_payload_bytes": actual,
            "random_prefix_bytes": prefix,
            "page_sha256": hashlib.sha256(page).hexdigest(),
        })

    ordered_blocks = container_count(measured)
    bestfit_blocks = bestfit_container_count(measured)
    manifest: dict[str, object] = {
        "schema": "swapz-bestfit4-mixed-payload-v1",
        "pattern": pattern,
        "seed": seed,
        "page_bytes": PAGE_BYTES,
        "page_count": len(measured),
        "compressor": "LZ4_compress_fast",
        "acceleration": 1,
        "max_compressed_bytes": MAX_COMPRESSED_BYTES,
        "header_bytes": HEADER_BYTES,
        "descriptor_bytes": DESCRIPTOR_BYTES,
        "measured_payload_lengths": measured,
        "ordered4_expected_containers": ordered_blocks,
        "bestfit4_expected_containers": bestfit_blocks,
        "pages": observations,
        "payload_file_sha256": hashlib.sha256(pages).hexdigest(),
        "scope": "userspace deterministic fixture; kernel result requires live readback and counters",
    }
    return bytes(pages), manifest


def write_fixture(pattern: str, seed: int, output_dir: Path) -> dict[str, object]:
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("output directory must not already exist")
    payload, manifest = make_fixture(pattern, seed)
    output_dir.mkdir(parents=True, mode=0o700)
    data_path = output_dir / "pages.bin"
    manifest_path = output_dir / "manifest.json"
    with data_path.open("xb") as output:
        output.write(payload)
        output.flush()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                             encoding="utf-8")
    return manifest


def verify_fixture(data_path: Path, manifest_path: Path) -> dict[str, object]:
    raw = data_path.read_bytes()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "swapz-bestfit4-mixed-payload-v1":
        raise ValueError("unexpected fixture manifest schema")
    if len(raw) != manifest.get("page_count") * PAGE_BYTES:
        raise ValueError("payload file page count differs from manifest")
    if hashlib.sha256(raw).hexdigest() != manifest.get("payload_file_sha256"):
        raise ValueError("payload file digest differs from manifest")
    codec = RawLZ4()
    measured = []
    for index in range(manifest["page_count"]):
        page = raw[index * PAGE_BYTES:(index + 1) * PAGE_BYTES]
        actual = codec.length(page)
        expected = manifest["pages"][index]
        if (actual != expected["measured_payload_bytes"] or
                hashlib.sha256(page).hexdigest() != expected["page_sha256"]):
            raise ValueError(f"page {index} differs from its compressed-length record")
        measured.append(actual)
    if measured != manifest.get("measured_payload_lengths"):
        raise ValueError("payload length order differs from manifest")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    generate = actions.add_parser("generate")
    generate.add_argument("--pattern", choices=tuple(PATTERNS), required=True)
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--output-dir", type=Path, required=True)
    verify = actions.add_parser("verify")
    verify.add_argument("--payload", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "generate":
            result = write_fixture(args.pattern, args.seed, args.output_dir)
        else:
            result = verify_fixture(args.payload, args.manifest)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
