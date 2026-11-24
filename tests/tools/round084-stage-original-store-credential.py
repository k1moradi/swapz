#!/usr/bin/env python3
"""Reproducible, single-file test-only stage of the pinned original zswap.c."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/runtime/native/fixtures"
HELPER = FIXTURES / "round084-original-store-credential-helper.cfrag"
NATIVE = FIXTURES / "round084-original-store-credential-kunit.cfrag"
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TARGET = "mm/zswap.c"
LINUX_PINS = {
    TARGET: "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/zsmalloc.c": "7ef80e0da6267661cea4d48a4a615444724782e7",
    "crypto/lz4.c": "57b713516aefac823f2af9481c828027b42490dd",
    "crypto/lzo.c": "d43242b24b4e831e7e0d26f38d2f263877d5748e",
    "crypto/lzo-rle.c": "794e7ec49536b0694838bdf02972ee70ab46756e",
    "crypto/scompress.c": "de54227203ce96a095f4fd2a76c2309a5e00d0b9",
    "include/crypto/acompress.h": "5d5358dfab73458fc4bc345fe00650e938fe36c6",
    "include/crypto/sha2.h": "22fbc37ae840796ecbafd5eadf23373e51741f9e",
    "include/linux/crc32.h": "da78b215ff2e9365188cf6318c111163c0c7af32",
    "lib/lzo/lzo1x_compress.c": "01586af2347f5e2f8c8528b94e02622fc8b262c8",
    "lib/lzo/lzo1x_compress_safe.c": "371c9f849492814afed88a443acb2262dcf35dfe",
    "lib/lz4/lz4_compress.c": "2a397bb2c661d9c2e4a7a67d5f50f06bfd42f1f2",
}
PRODUCT_PINS = {
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "src/kernel/authority.c": "25bf2dbdc5a3af770d7027547a58254c1ba81265",
    "src/kernel/engine.h": "0e505915fb2e1578b4c1cee36e32be8a30f3745f",
    "src/kernel/engine.c": "20e91329fc1a1b713cb6638236c001e7d5e3f815",
    "src/kernel/dm-target.c": "f1cab252cd990190646c82da81378d1563475826",
}
GUARD = "SWAPZ_ROUND084_ORIGINAL_STORE_CREDENTIAL_TEST"


class FirstError(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise FirstError(reason)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def guarded(code):
    return "#ifdef " + GUARD + "\n" + code + "#endif\n"


def replace_once(source, old, new, label):
    require(source.count(old) == 1, "source-anchor:" + label)
    return source.replace(old, new, 1)


def patches(helper):
    # Do not alter the real compressor request, ordinary return, allocation,
    # raw fallback, or XArray/LRU code. Optional context is NULL on normal path.
    include = guarded(
        "#include <crypto/sha2.h>\n#include <linux/crc32.h>\n"
        "static void r084_sha(const u8 *bytes, size_t length, u8 *digest)\n"
        "{\n\tsha256(bytes, length, digest);\n}\n"
        "static u32 r084_crc(const u8 *bytes, size_t length)\n"
        "{\n\treturn crc32c(~(u32)0, bytes, length) ^ ~(u32)0;\n}\n"
        + helper + "\n"
    )
    parameter = "\n#ifdef " + GUARD + "\n\t\t\t   , struct r084_context *capture\n#endif\n"
    call_argument = "\n#ifdef " + GUARD + "\n\t\t\t    , capture\n#endif\n"
    ordinary_argument = "\n#ifdef " + GUARD + "\n\t\t\t    , NULL\n#endif\n"
    compressor = (
        "static bool zswap_compress(struct folio *folio, long index,\n"
        "\t\t\t   struct zswap_entry *entry, struct zswap_pool *pool)"
    )
    store = (
        "static bool zswap_store_page(struct folio *folio, long index,\n"
        "\t\t\t     struct obj_cgroup *objcg,\n"
        "\t\t\t     struct zswap_pool *pool)"
    )
    beginning = "\tbool mapped = false;\n\n\tacomp_ctx = raw_cpu_ptr(pool->acomp_ctx);"
    written = "\tentry->length = dlen;\n\nunlock:"
    store_beginning = "\tstruct zswap_entry *entry, *old;\n\n\t/* allocate entry */"
    store_compress = "\tif (!zswap_compress(folio, index, entry, pool))"
    store_ok = "\tif (old)\n\t\tzswap_entry_free(old);\n\n\t/*\n\t * The entry is successfully compressed"
    store_fail = "store_failed:\n\tzs_free(pool->zs_pool, entry->handle);\ncompress_failed:\n"
    ordinary = "\t\tif (!zswap_store_page(folio, index, objcg, pool))"
    return [
        ("compress-signature", compressor,
         include + compressor[:-1] + parameter + ")"),
        ("clear-at-compressor-entry", beginning,
         "\tbool mapped = false;\n\n" + guarded("\tr084_clear(capture);\n") +
         "\tacomp_ctx = raw_cpu_ptr(pool->acomp_ctx);"),
        ("actual-written-object", written,
         "\tentry->length = dlen;\n" + guarded(
             "\tif (capture && !mapped && dlen < PAGE_SIZE) {\n"
             "\t\tconst u8 *original = kmap_local_folio(folio, index * PAGE_SIZE);\n"
             "\t\tstruct crypto_acomp *selected = crypto_acomp_reqtfm(acomp_ctx->req);\n\n"
             "\t\tr084_capture(capture, true, comp_ret,\n"
             "\t\t\t     crypto_acomp_alg_name(selected),\n"
             "\t\t\t     crypto_acomp_driver_name(selected), original, dst, dlen);\n"
             "\t\tkunmap_local(original);\n"
             "\t}\n") + "\nunlock:"),
        ("store-signature", store, store[:-1] + parameter + ")"),
        ("clear-at-store-entry", store_beginning,
         "\tstruct zswap_entry *entry, *old;\n\n" + guarded(
             "\tr084_clear(capture);\n"
             "\tif (capture) {\n"
             "\t\tcapture->type = swp_type(page_swpentry);\n"
             "\t\tcapture->slot = swp_offset(page_swpentry);\n"
             "\t}\n") + "\n\t/* allocate entry */"),
        ("actual-store-compression", store_compress,
         store_compress[:-2] + call_argument + "))"),
        ("actual-xarray-success", store_ok,
         "\tif (old)\n\t\tzswap_entry_free(old);\n\n" +
         guarded("\tr084_finish(capture, true);\n") +
         "\n\t/*\n\t * The entry is successfully compressed"),
        ("actual-store-failure", store_fail,
         store_fail + guarded("\tr084_finish(capture, false);\n")),
        ("normal-store-no-capture", ordinary,
         ordinary[:-2] + ordinary_argument + "))"),
    ]


def patch_text(original, helper, native):
    result = original
    for label, old, new in patches(helper):
        result = replace_once(result, old, new, label)
    require(result.count("crypto_wait_req(crypto_acomp_compress(acomp_ctx->req)") == 1,
            "original-compressor-request")
    require(result.count("zs_obj_write(pool->zs_pool, handle, dst, dlen);") == 1,
            "original-zsmalloc-write")
    return result + "\n" + guarded(native)


def check_pins(root, pins, skip=()):
    for path, expected in pins.items():
        if path not in skip:
            require(blob((root / path).read_bytes()) == expected, "preimage:" + path)


def tracked_fixture(path):
    data = path.read_bytes()
    relative = path.relative_to(ROOT).as_posix()
    require(blob(data) == git(ROOT, "rev-parse", "HEAD:" + relative).decode().strip(),
            "fixture-blob:" + relative)
    return data


def plan(original, helper, native):
    require(blob(original) == LINUX_PINS[TARGET], "original-zswap-preimage")
    return patch_text(original.decode(), helper.decode(), native.decode()).encode()


def negative_preflight(original, helper, native):
    failures = 0
    try:
        plan(original + b"\n", helper, native)
    except FirstError:
        failures += 1
    else:
        raise FirstError("changed-preimage-accepted")
    source = original.decode()
    for label, old, _ in patches(helper.decode()):
        require(source.count(old) == 1, "preflight-anchor:" + label)
        for changed in (source.replace(old, "/* missing */", 1), source + "\n" + old):
            try:
                patch_text(changed, helper.decode(), native.decode())
            except FirstError:
                failures += 1
            else:
                raise FirstError("negative-anchor-accepted:" + label)
    return failures


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".round084-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        if path.exists():
            os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--stage", action="store_true")
    mode.add_argument("--verify-stage", action="store_true")
    args = parser.parse_args()
    linux = args.linux_root.resolve()
    target = linux / TARGET
    require(git(linux, "rev-parse", "HEAD").decode().strip() == PIN, "linux-pin")
    require(not args.manifest.resolve().is_relative_to(linux), "manifest-inside-linux")
    check_pins(ROOT, PRODUCT_PINS)
    check_pins(linux, LINUX_PINS, (TARGET,) if args.verify_stage else ())
    helper, native = tracked_fixture(HELPER), tracked_fixture(NATIVE)
    original = git(linux, "show", "HEAD:" + TARGET)
    postimage = plan(original, helper, native)
    require(postimage != original, "empty-stage")
    require(all(not line.endswith((b" ", b"\t")) for line in postimage.splitlines()
                if line not in original.splitlines()), "new-trailing-whitespace")
    negatives = negative_preflight(original, helper, native)
    manifest = {
        "linux_pin": PIN, "product_commit": git(ROOT, "rev-parse", "HEAD").decode().strip(),
        "original_blobs": LINUX_PINS, "product_blobs": PRODUCT_PINS,
        "fixture_blobs": {"helper": blob(helper), "native": blob(native)},
        "postimage_blob": blob(postimage), "postimage_sha256": hashlib.sha256(postimage).hexdigest(),
        "negative_stage_cases": negatives, "source_mapped_authenticated": 0,
    }
    if args.verify_stage:
        require(target.read_bytes() == postimage, "actual-postimage-mismatch")
        require(json.loads(args.manifest.read_text()) == manifest, "manifest-mismatch")
        require(git(linux, "diff", "--name-only").decode().splitlines() == [TARGET],
                "unexpected-staged-path")
        git(linux, "diff", "--check")
        print("PASS R084_STAGE_POSTIMAGE blob=" + manifest["postimage_blob"], flush=True)
        return
    require(not git(linux, "status", "--porcelain", "--untracked-files=all"),
            "pristine-linux-dirty")
    require(target.read_bytes() == original, "pristine-target-mismatch")
    print(f"PASS R084_STAGE_PLAN negatives={negatives} linux_blobs={len(LINUX_PINS)} "
          f"product_blobs={len(PRODUCT_PINS)} postimage={manifest['postimage_blob']} AUTH0",
          flush=True)
    if args.stage:
        # Only one file changes; preflight and all negative checks precede it.
        # Restore the original on any failed post-write verification/manifest.
        try:
            atomic_write(target, postimage)
            require(target.read_bytes() == postimage, "write-postimage")
            git(linux, "diff", "--check")
            atomic_write(args.manifest, (json.dumps(manifest, indent=2) + "\n").encode())
        except Exception:
            atomic_write(target, original)
            raise
        print("PASS R084_STAGE_APPLIED original compressor and store anchors AUTH0", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (FirstError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("R084_STAGE_FIRST_ERROR " + (str(error) if isinstance(error, FirstError)
              else type(error).__name__), file=sys.stderr)
        sys.exit(2)
