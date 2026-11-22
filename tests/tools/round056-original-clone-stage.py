#!/usr/bin/env python3
"""Stage separate guarded clone-provenance C into pristine pinned Linux only.

Never writes to the swapz product tree or existing original composer. The
composed baseline retains all original 66 C KUnit registrations. The new
fixture is built only when explicit test-only KCFLAGS enable the guard.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

PINNED_LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PRISTINE_GIT_BLOBS = {
    "block/bio.c": "b0fcc69de653524479e3b328aa29a37e97945b84",
    "include/linux/blk_types.h": "0cc09b975d8ffbd45ca3dc47533a71f8e8164de6",
    "include/linux/bio.h": "7a794ce723b84b2a148f8f9beccf057b266e8ac9",
    "drivers/md/dm.c": "1881d86111fb2e655893ad898cf21b88f0e4e7f3",
    "mm/page_io.c": "c6824fcd483e0aa2c412e14dae0d2a356b17c373",
}
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "runtime/native/fixtures"
GUARD = "SWAPZ_ROUND056_ORIGINAL_CLONE_PROVENANCE_TEST"


class SourceError(RuntimeError):
    """Fail closed without publishing or modifying a wrongly pinned tree."""


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            check=False, timeout=60)
    if result.returncode:
        raise SourceError("git:" + " ".join(args) + ":" +
                          result.stderr.decode("utf-8", errors="replace")[-800:])
    return result.stdout


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def original_source_check(root: Path) -> None:
    if git(root, "rev-parse", "HEAD").decode().strip() != PINNED_LINUX:
        raise SourceError("first_error=wrong-original-kernel-pin")
    if git(root, "status", "--porcelain", "--untracked-files=all").strip():
        raise SourceError("first_error=dirty-original-before-composition")
    for name, wanted in PRISTINE_GIT_BLOBS.items():
        observed = git(root, "show", "HEAD:" + name)
        if blob_hash(observed) != wanted or (root / name).read_bytes() != observed:
            raise SourceError("first_error=wrong-original-blob:" + name)
    original_dm = (root / "drivers/md/dm.c").read_text()
    original_page = (root / "mm/page_io.c").read_text()
    for anchor in (
        "clone = bio_alloc_clone(NULL, bio, gfp_mask, &md->mempools->io_bs);",
        "clone->bi_bdev = md->disk->part0;",
        "clone->bi_end_io = clone_endio;",
        "case DM_MAPIO_SUBMITTED:",
        "io->orig_bio = bio;",
        "free_tio(bio);",
        "dm_io_dec_pending(io, error);",
        "if (requeued)",
    ):
        if anchor not in original_dm:
            raise SourceError("first_error=missing-real-DM-lifetime:" + anchor)
    for anchor in ("bio_uninit(bio);", "swap_write_end(sio, failed);",
                   "folio_end_writeback(folio);", "bio->bi_end_io = end_swap_bio_write;"):
        if anchor not in original_page:
            raise SourceError("first_error=missing-original-writeback:" + anchor)


def once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SourceError("first_error=drift:" + label + ":" + str(text.count(old)))
    return text.replace(old, new, 1)


def patch_function(source: str, signature: str, old: str, new: str, label: str) -> str:
    index = source.find(signature)
    if index == -1:
        raise SourceError("first_error=missing-function:" + label)
    next_function = source.find("\nEXPORT_SYMBOL", index)
    if next_function == -1:
        raise SourceError("first_error=missing-symbol-boundary:" + label)
    fragment = source[index:next_function]
    fragment = once(fragment, old, new, label)
    return source[:index] + fragment + source[next_function:]


def render_blk_types(original: str) -> str:
    """Reconstruct the exact guarded Round056 BIO header from composed source."""
    guard = "#if defined(" + GUARD + ")\n"
    close = "#endif /* " + GUARD + " */\n"
    field = (guard +
             "\tstruct swapz_round056_clone_ticket *bi_round056_ticket;\n"
             "\tstruct block_device *bi_round056_clone_device;\n"
             "\tbool bi_round056_candidate;\n" + close)
    header = original
    header = once(header, "struct bio {\n",
                  "struct swapz_round056_clone_ticket;\nstruct bio {\n",
                  "original-bio-struct")
    header = once(header, "\tunsigned short\t\tbi_vcnt;\t/* how many bio_vec's */\n",
                  "\tunsigned short\t\tbi_vcnt;\t/* how many bio_vec's */\n" + field,
                  "bio-ticket-before-reset-boundary")
    return header


def render_dm(original: str) -> str:
    """Reconstruct both inherited native alloc_tio and queue_io hooks."""
    dm = original
    guard = "#if defined(" + GUARD + ")\n"
    close = "#endif /* " + GUARD + " */\n"
    dm = patch_function(
        dm, "static struct bio *alloc_tio(struct clone_info *ci,",
        "\tclone->bi_bdev = md->disk->part0;\n",
        "\tclone->bi_bdev = md->disk->part0;\n" + guard +
        "\t/* Current target acceptance is NOT authenticated by a cloned marker. */\n"
        "\tclone->bi_round056_candidate = false;\n" + close,
        "original-DM-alloc-tio-requires-new-owner")
    dm = patch_function(
        dm, "static void queue_io(struct mapped_device *md, struct bio *bio)",
        "static void queue_io(struct mapped_device *md, struct bio *bio)\n{\n",
        "static void queue_io(struct mapped_device *md, struct bio *bio)\n{\n" +
        guard + "\t/* Suspended/requeued original BIO cannot reuse prior target witness. */\n"
        "\tbio->bi_round056_candidate = false;\n" + close,
        "original-DM-requeue-invalidation")

    return dm


def stage(root: Path, manifest: Path) -> None:
    original_source_check(root)
    composer = ROOT / "tools/stage-pinned-linux-zswap-composed.py"
    stage_manifest = manifest.with_name(manifest.stem + "-inherited66.json")
    result = subprocess.run(["python3", "-B", str(composer), "--linux-root",
                             str(root), "--manifest", str(stage_manifest)],
                            check=False, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise SourceError("first_error=original66-composer:" + result.stderr[-3000:])
    inherited = json.loads(stage_manifest.read_text())
    if inherited.get("source_sha") != PINNED_LINUX or not inherited.get("original_source_verified"):
        raise SourceError("first_error=inherited-composer-provenance")
    guard = "#if defined(" + GUARD + ")\n"
    close = "#endif /* " + GUARD + " */\n"
    header_path = root / "include/linux/blk_types.h"
    header = render_blk_types(header_path.read_text())
    bio_path = root / "block/bio.c"
    bio = bio_path.read_text()
    hooks = (FIXTURES / "round056-original-clone-hooks.cfrag").read_text()
    kunit = (FIXTURES / "round056-original-clone-kunit.cfrag").read_text()
    if hooks.count("ROUND056_ORIGINAL_CLONE_HOOKS_BEGIN") != 1 or \
       kunit.count("ROUND056_ORIGINAL_CLONE_KUNIT_BEGIN") != 1:
        raise SourceError("first_error=fixture-marker-count")
    bio = once(bio, "void bio_uninit(struct bio *bio)\n",
               "#if defined(" + GUARD + ")\n#include <linux/refcount.h>\n#endif\n" +
               hooks + "\nvoid bio_uninit(struct bio *bio)\n", "guarded-owner-at-original-bio")
    bio = patch_function(bio, "void bio_uninit(struct bio *bio)\n{",
                         "void bio_uninit(struct bio *bio)\n{\n",
                         "void bio_uninit(struct bio *bio)\n{\n" + guard +
                         "\tswapz_round056_drop_clone_ticket(bio);\n" + close,
                         "original-biouninit-drop")
    bio = patch_function(bio, "void bio_init(struct bio *bio,",
                         "\tbio->bi_private = NULL;\n",
                         "\tbio->bi_private = NULL;\n" + guard +
                         "\tbio->bi_round056_ticket = NULL;\n"
                         "\tbio->bi_round056_clone_device = NULL;\n"
                         "\tbio->bi_round056_candidate = false;\n" + close,
                         "original-bio-init-zero-ticket")
    bio = patch_function(bio, "void bio_prepare_reissue(struct bio *bio,",
                         "void bio_prepare_reissue(struct bio *bio, struct block_device *bdev)\n{\n",
                         "void bio_prepare_reissue(struct bio *bio, struct block_device *bdev)\n{\n" + guard +
                         "\tswapz_round056_invalidate_clone(bio);\n" + close,
                         "original-reissue-invalidation")
    bio = patch_function(bio, "static int __bio_clone(struct bio *bio,",
                         "\treturn 0;\n}", guard +
                         "\t/* Failed core clone must never acquire a provenance reference. */\n"
                         "\tif (atomic_xchg(&swapz_round056_fail_next_clone, 0))\n"
                         "\t\treturn -ENOMEM;\n"
                         "\tswapz_round056_propagate_full_clone(bio, bio_src);\n" + close +
                         "\treturn 0;\n}", "original-clone-success-only")
    bio = patch_function(bio, "struct bio *bio_split(struct bio *bio,",
                         "\tsplit->bi_iter.bi_size = sectors << 9;\n",
                         "\tsplit->bi_iter.bi_size = sectors << 9;\n" + guard +
                         "\tswapz_round056_invalidate_clone(split);\n" + close,
                         "original-split-child-invalidation")
    bio = patch_function(bio, "void bio_trim(struct bio *bio,",
                         "\tbio_advance(bio, offset << 9);\n",
                         guard + "\t/* Zero-offset trims still shorten this BIO. */\n"
                         "\tswapz_round056_invalidate_clone(bio);\n" + close +
                         "\tbio_advance(bio, offset << 9);\n",
                         "original-trim-invalidation")
    bio = patch_function(bio, "void __bio_advance(struct bio *bio,",
                         "void __bio_advance(struct bio *bio, unsigned bytes)\n{\n",
                         "void __bio_advance(struct bio *bio, unsigned bytes)\n{\n" + guard +
                         "\tif (bytes)\n\t\tswapz_round056_invalidate_clone(bio);\n" + close,
                         "original-internal-advance-invalidation")
    bio_header_path = root / "include/linux/bio.h"
    bio_header = bio_header_path.read_text()
    bio_header = once(
        bio_header,
        "static inline void bio_advance(struct bio *bio, unsigned int nbytes)\n{\n",
        "static inline void bio_advance(struct bio *bio, unsigned int nbytes)\n{\n" + guard +
        "\tif (nbytes)\n\t\tbio->bi_round056_candidate = false;\n" + close,
        "original-inline-advance-invalidation")
    bio = bio.rstrip("\n") + "\n\n" + kunit.rstrip("\n") + "\n"
    if any(bio.count(anchor) != 1 for anchor in
           ("ROUND056_ORIGINAL_CLONE_HOOKS_BEGIN",
            "ROUND056_ORIGINAL_CLONE_KUNIT_BEGIN")):
        raise SourceError("first_error=staged-marker-count")
    dm_path = root / "drivers/md/dm.c"
    dm = render_dm(dm_path.read_text())
    # Publication occurs only after every source anchor was checked.
    header_path.write_text(header)
    bio_header_path.write_text(bio_header)
    bio_path.write_text(bio)
    dm_path.write_text(dm)
    if not stage_manifest.is_file():
        raise SourceError("first_error=missing-composer-manifest")
    manifest.write_text(json.dumps({
        "original_sha": PINNED_LINUX,
        "inherited66_composer_manifest": str(stage_manifest),
        "inherited_original_verified": True,
        "default_guard": GUARD,
        "original_block_bio_sha256": hashlib.sha256(bio.encode()).hexdigest(),
        "original_blk_types_sha256": hashlib.sha256(header.encode()).hexdigest(),
        "original_bio_header_sha256": hashlib.sha256(bio_header.encode()).hexdigest(),
        "original_dm_sha256": hashlib.sha256(dm.encode()).hexdigest(),
        "own_changed_paths": ["block/bio.c", "include/linux/bio.h",
                              "include/linux/blk_types.h", "drivers/md/dm.c"],
        "positive_source_target_authorization": False,
    }, indent=2) + "\n")
    print("ROUND056_ORIGINAL_CLONE_STAGED pinned=" + PINNED_LINUX +
          " inherited66=preserved new_cases=4 default_guard=UNDEFINED")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        stage(arguments.linux_root.resolve(), arguments.manifest.resolve())
        return 0
    except (OSError, SourceError, ValueError, subprocess.TimeoutExpired) as error:
        print("ROUND056_ORIGINAL_CLONE_FIRST_ERROR phase=staging reason=" + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
