#!/usr/bin/env python3
"""Derive deterministic 1,024-page uniform classes from measured mixed LZ4 input."""
import argparse
import collections
import ctypes
import ctypes.util
import hashlib
import json
from pathlib import Path

PAGES = 1024
PAGE_BYTES = 4096
CLASS_IDS = {"57": 0, "1032": 1, "2089": 2, "3500": 3, "raw": 4}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_dir / "mixed-1024-pages.bin"
    source_manifest = args.source_dir / "mixed-1024-manifest.json"
    manifest = json.loads(source_manifest.read_text())
    source_bytes = source.read_bytes()
    if len(source_bytes) != PAGE_BYTES * int(manifest["page_count"]):
        raise SystemExit("source page file length does not match manifest")

    libname = ctypes.util.find_library("lz4")
    if not libname:
        raise SystemExit("liblz4 unavailable")
    lz = ctypes.CDLL(libname)
    lz.LZ4_versionString.restype = ctypes.c_char_p
    lz.LZ4_compress_fast.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int
    ]
    lz.LZ4_compress_fast.restype = ctypes.c_int
    version = lz.LZ4_versionString().decode()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for label, class_id in CLASS_IDS.items():
        row = next(r for r in manifest["records"] if r["class"] == label)
        page_index = int(row["page"])
        page = source_bytes[page_index * PAGE_BYTES:(page_index + 1) * PAGE_BYTES]
        src = ctypes.create_string_buffer(page)
        dst = ctypes.create_string_buffer(3568)
        actual = lz.LZ4_compress_fast(src, dst, PAGE_BYTES, 3568, 1)
        expected = row["compressed_length"]
        if label == "raw":
            if actual != 0 or expected is not None:
                raise SystemExit(f"raw page unexpectedly compressed: {actual}")
        elif actual <= 0 or actual != int(expected):
            raise SystemExit(
                f"LZ4 output changed for class {label}: source={expected} now={actual}"
            )
        pages = page * PAGES
        classmap = bytes([class_id]) * PAGES
        page_path = args.output_dir / f"uniform-{label}-1024-pages.bin"
        class_path = args.output_dir / f"uniform-{label}-1024-class.bin"
        page_path.write_bytes(pages)
        class_path.write_bytes(classmap)
        records.append({
            "class": label,
            "class_id": class_id,
            "source_page_index": page_index,
            "compressed_length_bytes": None if actual == 0 else actual,
            "raw_fallback": actual == 0,
            "page_sha256": sha256(page),
            "pages_path": str(page_path),
            "pages_sha256": sha256(pages),
            "classmap_path": str(class_path),
            "classmap_sha256": sha256(classmap),
            "page_count": PAGES,
        })
    output = {
        "source_fixture_sha256": sha256(source_bytes),
        "source_manifest_sha256": sha256(source_manifest.read_bytes()),
        "liblz4_version": version,
        "compressor": "LZ4_compress_fast(input=4096, capacity=3568, acceleration=1)",
        "records": records,
    }
    out_manifest = args.output_dir / "uniform-fixtures-manifest.json"
    out_manifest.write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
