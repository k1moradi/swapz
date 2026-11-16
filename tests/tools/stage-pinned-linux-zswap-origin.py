#!/usr/bin/env python3
"""Stage verified zswap stored-writeback provenance in a complete pinned Linux tree.

This is a source mutation tool, NOT a patch generator or a kernel ABI claim.
Callers supply an untouched full torvalds/linux checkout. Nothing is fetched.
Only the six pinned C/H sources are changed; every original blob is verified
before any write. An all-file in-memory plan prevents partial preflight edits.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile


LINUX_COMMIT = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MINIMUM_TRACKED_FILES = 50_000
ORIGINAL_BLOBS = {
    "Makefile": "7e6baa461b91a79d12b5dcbce06795dd0ff37e81",
    "mm/zswap.c": "ae19e301fced7e357a4c7587dfdd6abb890b9163",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
    "include/linux/swap_ops.h": "57ac6c703f685883d3a15ebc1a5c7f6c298deb1b",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
}


@dataclass(frozen=True)
class Edit:
    before: str
    after: str


# Anchors copied from actual upstream C/H at the pinned Git blob IDs above.
# Every replacement is exact, unique, and tested against the full source.
EDITS: dict[str, tuple[Edit, ...]] = {
    "include/linux/blk_types.h": (
        Edit(
            "#define BLK_QC_T_NONE\t\t-1U\n\n/*\n * main unit of I/O",
            "#define BLK_QC_T_NONE\t\t-1U\n\n"
            "/* Only a verified zswap stored-entry eviction can set nonzero. */\n"
            "enum swap_bio_origin {\n"
            "\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,\n"
            "\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,\n"
            "};\n\n/*\n * main unit of I/O",
        ),
        Edit(
            "\tu8\t\t\tbi_bvec_gap_bit;\n\n\tatomic_t",
            "\tu8\t\t\tbi_bvec_gap_bit;\n"
            "\tu8\t\t\tbi_swap_origin; /* scalar source, never encoding */\n\n"
            "\tatomic_t",
        ),
    ),
    "include/linux/bio.h": (
        Edit(
            "\t(op_is_write(bio_op(bio)) ? WRITE : READ)\n\n"
            "static inline bool bio_flagged(",
            "\t(op_is_write(bio_op(bio)) ? WRITE : READ)\n\n"
            "/* Capability of this *built* kernel; absent from stock headers. */\n"
            "#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1\n\n"
            "static inline bool bio_is_zswap_stored_writeback(const struct bio *bio)\n"
            "{\n"
            "\treturn bio_op(bio) == REQ_OP_WRITE &&\n"
            "\t\t(bio->bi_opf & REQ_SWAP) &&\n"
            "\t\tbio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;\n"
            "}\n\n"
            "static inline bool bio_flagged(",
        ),
    ),
    "block/bio.c": (
        Edit(
            "\tbio->bi_bvec_gap_bit = 0;\n\tbio->bi_iter.bi_sector = 0;",
            "\tbio->bi_bvec_gap_bit = 0;\n"
            "\tbio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\tbio->bi_iter.bi_sector = 0;",
        ),
        Edit(
            "\tbio->bi_bvec_gap_bit = bio_src->bi_bvec_gap_bit;\n"
            "\tbio->bi_iter = bio_src->bi_iter;",
            "\tbio->bi_bvec_gap_bit = bio_src->bi_bvec_gap_bit;\n"
            "\tbio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?\n"
            "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\tbio->bi_iter = bio_src->bi_iter;",
        ),
        Edit(
            "\tbio->bi_bvec_gap_bit = 0;\n\tatomic_set(&bio->__bi_remaining, 1);",
            "\tbio->bi_bvec_gap_bit = 0;\n"
            "\t/* Same-payload reissue preserves the verified origin tag. */\n"
            "\tatomic_set(&bio->__bi_remaining, 1);",
        ),
    ),
    "include/linux/swap_ops.h": (
        Edit(
            "\tint\t\t\tlen;\n};\n\nstruct swap_io_ctx",
            "\tint\t\t\tlen;\n"
            "\tenum swap_bio_origin\tswap_origin;\n"
            "};\n\nstruct swap_io_ctx",
        ),
        Edit(
            "\tstruct swap_info_struct\t*sis;\n};",
            "\tstruct swap_info_struct\t*sis;\n"
            "\t/* Zero initialized for every ordinary or rejected swap page. */\n"
            "\tenum swap_bio_origin\tswap_origin;\n};",
        ),
    ),
    "mm/page_io.c": (
        Edit(
            "\tif (ctx->sis != sis)\n\t\treturn false;\n"
            "\treturn sis->ops->can_merge(",
            "\tif (ctx->sis != sis)\n\t\treturn false;\n"
            "\t/* Never combine ordinary and stored-entry writes in one BIO. */\n"
            "\tif (rw == WRITE && ctx->sio->swap_origin != ctx->swap_origin)\n"
            "\t\treturn false;\n"
            "\treturn sis->ops->can_merge(",
        ),
        Edit(
            "\t\tsio->nr_bvecs = 0;\n\t\tsio->len = 0;\n\t}\n"
            "\tbvec_set_folio(",
            "\t\tsio->nr_bvecs = 0;\n\t\tsio->len = 0;\n"
            "\t\tsio->swap_origin = rw == WRITE &&\n"
            "\t\t\tctx->swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?\n"
            "\t\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            "\t}\n\tbvec_set_folio(",
        ),
        Edit(
            "\t\t\tREQ_OP_WRITE | REQ_SWAP);\n"
            "\tbio->bi_iter.bi_size = sio->len;",
            "\t\t\tREQ_OP_WRITE | REQ_SWAP);\n"
            "\tbio->bi_swap_origin = sio->swap_origin;\n"
            "\tbio->bi_iter.bi_size = sio->len;",
        ),
    ),
    "mm/zswap.c": (
        Edit(
            "\tfolio_set_dropbehind(folio);\n\n\t/*\n"
            "\t * Drop our reference before starting writeback",
            "\tfolio_set_dropbehind(folio);\n"
            "\t/* Entry identity was checked and decompression succeeded. */\n"
            "\tctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;\n\n"
            "\t/*\n\t * Drop our reference before starting writeback",
        ),
    ),
}


class StagingError(RuntimeError):
    """Refuse a preflight, source transition or publication failure."""


def blob_sha(payload: bytes) -> str:
    """SHA-1 of the exact Git blob; independent of local Git config."""
    header = b"blob " + str(len(payload)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + payload).hexdigest()


def check_preimage(path: str, payload: bytes, expected_hash: str) -> None:
    if blob_sha(payload) != expected_hash:
        raise StagingError(f"original-blob-mismatch:{path}")


def render_source(path: str, original: str) -> str:
    """Reject missing, duplicate and overlapping anchors before any mutation."""
    if path not in EDITS:
        raise StagingError(f"unexpected-source-path:{path}")
    spans = []
    for edit in EDITS[path]:
        if edit.before == edit.after or not edit.before or not edit.after:
            raise StagingError(f"invalid-transition:{path}")
        offset = original.find(edit.before)
        if offset < 0 or original.find(edit.before, offset + 1) >= 0:
            raise StagingError(f"missing-or-duplicate-anchor:{path}")
        if edit.after in original:
            raise StagingError(f"already-staged-or-mixed-source:{path}")
        spans.append((offset, offset + len(edit.before), edit))
    spans.sort(key=lambda span: span[0])
    for previous, current in zip(spans, spans[1:]):
        if previous[1] > current[0]:
            raise StagingError(f"overlapping-anchors:{path}")
    changed = original
    for begin, end, edit in reversed(spans):
        changed = changed[:begin] + edit.after + changed[end:]
    if changed == original:
        raise StagingError(f"no-source-transition:{path}")
    validate_origin_postimage(path, changed)
    return changed



def validate_origin_postimage(path: str, staged_source: str) -> None:
    """Check safety-critical emitted C snippets, not only anchor counts.

    A later edit must not silently replace the positive-origin predicate with
    a raw scalar copy, promote a noncanonical context, or remove the merge
    boundary. Whole-file upstream Git blobs are separately pinned.
    """
    required: dict[str, tuple[str, ...]] = {
        "include/linux/blk_types.h": (
            "SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,",
            "SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1,",
            "bi_swap_origin; /* scalar source, never encoding */",
        ),
        "include/linux/bio.h": (
            "bio_op(bio) == REQ_OP_WRITE &&",
            "(bio->bi_opf & REQ_SWAP) &&",
            "bio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
        ),
        "block/bio.c": (
            "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "bio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?\n"
            "\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "Same-payload reissue preserves the verified origin tag.",
        ),
        "include/linux/swap_ops.h": (
            "enum swap_bio_origin\tswap_origin;",
        ),
        "mm/page_io.c": (
            "rw == WRITE && ctx->sio->swap_origin != ctx->swap_origin",
            "sio->swap_origin = rw == WRITE &&\n"
            "\t\t\tctx->swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?\n"
            "\t\t\tSWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK :\n"
            "\t\t\tSWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
            "bio->bi_swap_origin = sio->swap_origin;",
        ),
        "mm/zswap.c": (
            "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
        ),
    }
    if path not in required or any(
        staged_source.count(fragment) != (2 if path == "include/linux/swap_ops.h" else 1)
        for fragment in required[path]
    ):
        raise StagingError(f"invalid-origin-postimage:{path}")
    if path == "block/bio.c" and (
        "bio->bi_swap_origin = bio_src->bi_swap_origin;" in staged_source
    ):
        raise StagingError("unguarded-origin-clone:block/bio.c")
    if path == "include/linux/blk_types.h":
        origin_offset = staged_source.find("bi_swap_origin;")
        # The original header also contains unrelated atomic_t fields before
        # struct bio. Check the next member instead of the first in the file.
        next_member = staged_source.find("atomic_t", origin_offset)
        if origin_offset < 0 or next_member <= origin_offset:
            raise StagingError("origin-reset-layout:include/linux/blk_types.h")
        bio_start = staged_source.find("struct bio {")
        if bio_start >= 0:
            preserved_start = staged_source.find("bi_max_vecs;", bio_start)
            if (origin_offset <= bio_start or
                preserved_start <= origin_offset or
                "#define BIO_RESET_BYTES\t\toffsetof(struct bio, bi_max_vecs)"
                    not in staged_source):
                raise StagingError("origin-reset-layout:include/linux/blk_types.h")

def git_output(root: Path, *args: str) -> str:
    try:
        call = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True,
            text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StagingError("git-preflight-unavailable") from error
    if call.returncode:
        raise StagingError("git-preflight-command-failed:" + args[0])
    return call.stdout.strip()


def validate_checkout(root: Path) -> None:
    """Require the exact clean, complete upstream checkout before writing."""
    if not root.is_dir() or not (root / ".git").exists():
        raise StagingError("complete-git-checkout-required")
    if Path(git_output(root, "rev-parse", "--show-toplevel")) != root:
        raise StagingError("unexpected-git-top-level")
    if git_output(root, "rev-parse", "HEAD") != LINUX_COMMIT:
        raise StagingError("linux-commit-mismatch")
    if git_output(root, "status", "--porcelain", "--untracked-files=no"):
        raise StagingError("tracked-source-is-dirty")
    if len(git_output(root, "ls-files").splitlines()) < MINIMUM_TRACKED_FILES:
        raise StagingError("incomplete-linux-checkout")
    for path, expected_hash in ORIGINAL_BLOBS.items():
        full_path = root / path
        if full_path.is_symlink() or not full_path.is_file():
            raise StagingError(f"missing-or-symlink-source:{path}")
        lines = git_output(root, "ls-files", "--stage", "--", path).splitlines()
        if len(lines) != 1 or not lines[0].startswith("100644 " + expected_hash + " 0\t"):
            raise StagingError(f"index-blob-mismatch:{path}")
        check_preimage(path, full_path.read_bytes(), expected_hash)


def write_atomic(destination: Path, payload: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".swapz-origin-", dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o644)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)



def rollback_sources(root: Path, originals: dict[str, bytes],
                     staged: dict[str, bytes], paths: list[str]) -> list[str]:
    """Restore touched paths, including a write that raised after replacement.

    Never overwrite unexpected third-party bytes. Such interference is a
    reported partial rollback, not a successful source stage.
    """
    failed = []
    for path in reversed(paths):
        try:
            current = (root / path).read_bytes()
            if current == originals[path]:
                continue
            if current != staged[path]:
                raise StagingError("rollback-source-interference")
            write_atomic(root / path, originals[path])
        except (OSError, StagingError):
            failed.append(path)
    return failed


def stage_checkout(root: Path, manifest_path: Path) -> dict[str, object]:
    try:
        root = root.resolve(strict=True)
    except OSError as error:
        raise StagingError("complete-git-checkout-required") from error
    manifest_path = manifest_path.resolve(strict=False)
    if manifest_path == root or root in manifest_path.parents:
        raise StagingError("manifest-must-be-outside-linux-checkout")
    validate_checkout(root)

    originals: dict[str, bytes] = {}
    staged: dict[str, bytes] = {}
    for path in EDITS:
        original = (root / path).read_bytes()
        check_preimage(path, original, ORIGINAL_BLOBS[path])
        originals[path] = original
        staged[path] = render_source(path, original.decode("utf-8")).encode("utf-8")

    # Recheck the entire plan before any mutation, then recheck each file
    # immediately before replacement to catch late source interference.
    for path in sorted(staged):
        destination = root / path
        if destination.is_symlink() or not destination.is_file():
            raise StagingError(f"missing-or-symlink-source:{path}")
        check_preimage(path, destination.read_bytes(), ORIGINAL_BLOBS[path])

    committed: list[str] = []
    attempted: str | None = None
    try:
        for path in sorted(staged):
            destination = root / path
            check_preimage(path, destination.read_bytes(), ORIGINAL_BLOBS[path])
            attempted = path
            write_atomic(destination, staged[path])
            committed.append(path)
            attempted = None
    except (OSError, StagingError) as error:
        touched = committed + ([attempted] if attempted is not None else [])
        rollback_errors = rollback_sources(root, originals, staged, touched)
        if rollback_errors:
            raise StagingError("rollback-incomplete:" + ",".join(rollback_errors)) from error
        raise StagingError("publication-failed-rolled-back") from error

    result: dict[str, object] = {
        "schema": "swapz-pinned-linux-zswap-origin-v1",
        "source_repository": "torvalds/linux",
        "source_sha": LINUX_COMMIT,
        "status": "STAGED_SOURCE_ONLY",
        "changed_paths": [
            {
                "path": path,
                "original_git_sha1": ORIGINAL_BLOBS[path],
                "original_sha256": hashlib.sha256(originals[path]).hexdigest(),
                "staged_git_sha1": blob_sha(staged[path]),
                "staged_sha256": hashlib.sha256(staged[path]).hexdigest(),
                "bytes": len(staged[path]),
            }
            for path in sorted(staged)
        ],
        "compiled": False,
        "kunit_executed": False,
        "phase_a_qualified": False,
        "phase_b_enabled": False,
    }
    # The manifest is a bounded evidence file *outside* the Linux checkout.
    temporary_manifest = None
    previous_manifest: bytes | None = None
    manifest_text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    manifest_bytes = manifest_text.encode("utf-8")
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            previous_manifest = manifest_path.read_bytes()
        except FileNotFoundError:
            pass
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".linux-origin-manifest-",
            dir=manifest_path.parent, delete=False,
        ) as stream:
            temporary_manifest = Path(stream.name)
            stream.write(manifest_text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_manifest, manifest_path)
        temporary_manifest = None
    except OSError as error:
        # Even an os.replace() that succeeded before a reported failure
        # must not leave manifest evidence claiming rolled-back source edits.
        manifest_rollback_incomplete = False
        try:
            if manifest_path.is_file():
                current_manifest = manifest_path.read_bytes()
                if current_manifest == manifest_bytes:
                    if previous_manifest is None:
                        manifest_path.unlink()
                    else:
                        write_atomic(manifest_path, previous_manifest)
                elif current_manifest != previous_manifest:
                    manifest_rollback_incomplete = True
            elif previous_manifest is not None:
                manifest_rollback_incomplete = True
        except OSError:
            manifest_rollback_incomplete = True
        rollback_errors = rollback_sources(root, originals, staged, committed)
        if manifest_rollback_incomplete:
            rollback_errors.append("manifest")
        if rollback_errors:
            raise StagingError("manifest-failed-rollback-incomplete:" +
                               ",".join(rollback_errors)) from error
        raise StagingError("manifest-write-failed-rolled-back") from error
    finally:
        if temporary_manifest is not None:
            temporary_manifest.unlink(missing_ok=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = stage_checkout(arguments.linux_root, arguments.manifest)
    except (StagingError, OSError, UnicodeError, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    # Success remains quiet; structured source evidence is in --manifest.
    assert len(result["changed_paths"]) == 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
