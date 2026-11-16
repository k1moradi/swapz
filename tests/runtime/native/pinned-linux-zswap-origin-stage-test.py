#!/usr/bin/env python3
"""Rootless tests for actual pinned Linux C/H staging transitions, not Kbuild."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


STAGER_PATH = Path(__file__).resolve().parents[2] / "tools/stage-pinned-linux-zswap-origin.py"
specification = importlib.util.spec_from_file_location("swapz_linux_stage", STAGER_PATH)
assert specification and specification.loader
stager = importlib.util.module_from_spec(specification)
sys.modules[specification.name] = stager
specification.loader.exec_module(stager)


class PinnedLinuxStageTests(unittest.TestCase):
    """Excerpts are literal from the frozen upstream blobs, not fake APIs."""

    def make_fixture(self, directory: Path) -> tuple[Path, dict[str, bytes]]:
        root = directory / "linux"
        root.mkdir()
        (root / ".git").mkdir()
        payloads = {"Makefile": b"VERSION = 7\nPATCHLEVEL = 3\nSUBLEVEL = 0\n"}
        for path, edits in stager.EDITS.items():
            # Each excerpt is independent and preserves the original exact bytes.
            payloads[path] = ("\n\n/* separator */\n\n".join(
                edit.before for edit in edits) + "\n").encode("utf-8")
        for path, payload in payloads.items():
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        return root, payloads

    def stage_fixture(self, root: Path, payloads: dict[str, bytes],
                      manifest: Path, *, with_kunit: bool = False):
        synthetic_preimages = {
            path: stager.blob_sha(payload) for path, payload in payloads.items()
        }
        with mock.patch.object(stager, "ORIGINAL_BLOBS", synthetic_preimages), \
             mock.patch.object(stager, "KUNIT_ORIGINAL_BLOBS", synthetic_preimages), \
             mock.patch.object(stager, "validate_checkout"):
            return stager.stage_checkout(root, manifest, with_kunit=with_kunit)

    def make_kunit_fixture(self, directory: Path):
        root, originals = self.make_fixture(directory)
        for path, edits in stager.KUNIT_EDITS.items():
            payload = ("\n\n/* separator */\n\n".join(
                edit.before for edit in edits) + "\n").encode("utf-8")
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            originals[path] = payload
        return root, originals

    def test_pinned_source_identity_and_real_anchor_structure(self):
        self.assertEqual(stager.LINUX_COMMIT,
                         "c339f4010dea8b0d754f84ace70cd1b089878ef8")
        self.assertEqual(len(stager.ORIGINAL_BLOBS), 7)
        self.assertEqual(set(stager.EDITS), set(stager.ORIGINAL_BLOBS) - {"Makefile"})
        self.assertEqual(sum(map(len, stager.EDITS.values())), 13)
        for path, edits in stager.EDITS.items():
            excerpts = "\n\n/* separator */\n\n".join(edit.before for edit in edits)
            updated = stager.render_source(path, excerpts)
            for edit in edits:
                self.assertIn(edit.after, updated)
                if edit.before not in edit.after:
                    self.assertNotIn(edit.before, updated)
            with self.assertRaises(stager.StagingError):
                stager.render_source(path, updated)


    def test_origin_postimage_mutations_are_rejected_before_publication(self):
        """A deliberately weakened real edit must fail, not merely lose a keyword."""
        probes = (
            ("block/bio.c",
             "bio_is_zswap_stored_writeback(bio_src) ?",
             "bio_src->bi_swap_origin ?"),
            ("block/bio.c",
             "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;",
             "bio->bi_swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"),
            ("mm/page_io.c",
             "!swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)",
             "swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)"),
            ("mm/page_io.c",
             "ctx->swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?",
             "ctx->swap_origin != SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK ?"),
            ("include/linux/bio.h",
             "(bio->bi_opf & REQ_SWAP) &&",
             "(bio->bi_opf & REQ_FUA) &&"),
            ("mm/zswap.c",
             "ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;",
             "ctx.swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;"),
        )
        for path, original, weakened in probes:
            with self.subTest(path=path, weakened=weakened):
                edits = tuple(
                    stager.Edit(edit.before, edit.after.replace(original, weakened))
                    for edit in stager.EDITS[path]
                )
                self.assertTrue(any(edit.after != previous.after
                                    for edit, previous in zip(edits, stager.EDITS[path])))
                with mock.patch.dict(stager.EDITS, {path: edits}):
                    source = "\n\n/* separator */\n\n".join(
                        edit.before for edit in edits)
                    with self.assertRaisesRegex(stager.StagingError,
                                                "invalid-origin-postimage"):
                        stager.render_source(path, source)

    def test_postimage_bio_lifecycle_reset_and_retry_contract(self):
        """Keep the layout/reset contract and same-payload reissue distinct."""
        block = stager.render_source(
            "block/bio.c",
            "\n\n/* separator */\n\n".join(
                edit.before for edit in stager.EDITS["block/bio.c"]))
        types = stager.render_source(
            "include/linux/blk_types.h",
            "\n\n/* separator */\n\n".join(
                edit.before for edit in stager.EDITS["include/linux/blk_types.h"]))
        self.assertLess(types.index("bi_swap_origin"),
                        types.index("atomic_t", types.index("bi_swap_origin")))
        self.assertIn("bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN",
                      block)
        self.assertIn("bio_is_zswap_stored_writeback(bio_src) ?", block)
        self.assertIn("Same-payload reissue preserves", block)
        self.assertNotIn("bio->bi_swap_origin = bio_src->bi_swap_origin;", block)
        # Independently inspected pinned upstream bio_reset() zeroes
        # BIO_RESET_BYTES=offsetof(struct bio, bi_max_vecs); bio_reuse()
        # calls bio_reset(), while bio_prepare_reissue() retries the same
        # operation and retains the tag. Real KUnit is a separate gate.

    def test_header_reset_layout_ignores_earlier_unrelated_atomics(self):
        excerpts = "\n\n/* separator */\n\n".join(
            edit.before for edit in stager.EDITS["include/linux/blk_types.h"])
        # The genuine pinned Linux header has unrelated atomic_t declarations
        # before struct bio. Only fields within struct bio define reset scope.
        prefixed = "atomic_t unrelated_before_bio;\n\n" + excerpts
        staged = stager.render_source("include/linux/blk_types.h", prefixed)
        self.assertLess(staged.index("atomic_t"),
                        staged.index("bi_swap_origin"))
        self.assertLess(staged.index("bi_swap_origin"),
                        staged.index("atomic_t", staged.index("bi_swap_origin")))

    def test_manifest_records_exact_pre_and_post_sha256(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            result = self.stage_fixture(root, originals, manifest)
            self.assertEqual(set(entry["path"] for entry in result["changed_paths"]),
                             set(stager.EDITS))
            self.assertEqual(result, json.loads(manifest.read_text()))
            for item in result["changed_paths"]:
                path = item["path"]
                before = originals[path]
                after = (root / path).read_bytes()
                self.assertEqual(item["original_sha256"],
                                 hashlib.sha256(before).hexdigest())
                self.assertEqual(item["staged_sha256"],
                                 hashlib.sha256(after).hexdigest())
                self.assertNotEqual(item["original_sha256"], item["staged_sha256"])

    def test_post_replace_failure_restores_even_current_source(self):
        """A write can replace bytes then raise: rollback must include that file."""
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            write_source = stager.write_atomic
            calls = 0

            def fail_after_replacement(destination: Path, payload: bytes):
                nonlocal calls
                calls += 1
                write_source(destination, payload)
                if calls == 3:
                    raise OSError("injected failure after successful replacement")

            with mock.patch.object(stager, "write_atomic",
                                   side_effect=fail_after_replacement):
                with self.assertRaisesRegex(stager.StagingError,
                                            "publication-failed-rolled-back"):
                    self.stage_fixture(root, originals, manifest)
            self.assertFalse(manifest.exists())
            self.assertEqual(originals, {p: (root / p).read_bytes()
                                         for p in originals})

    def test_interfered_rollback_is_reported_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            protected = root / sorted(stager.EDITS)[0]
            write_source = stager.write_atomic
            calls = 0

            def interfere_before_failure(destination: Path, payload: bytes):
                nonlocal calls
                calls += 1
                if calls == 3:
                    protected.write_bytes(b"concurrent-external-change\n")
                    raise OSError("injected failure and third-party edit")
                write_source(destination, payload)

            with mock.patch.object(stager, "write_atomic",
                                   side_effect=interfere_before_failure):
                with self.assertRaisesRegex(stager.StagingError,
                                            "rollback-incomplete:"):
                    self.stage_fixture(root, originals, manifest)
            self.assertEqual(protected.read_bytes(),
                             b"concurrent-external-change\n")
            self.assertFalse(manifest.exists())

    def test_pinned_cloned_origin_c_fixture(self):
        """Compile and run the emitted production C predicate/clone assignment.

        This source-coupled rootless fragment is not a Linux BIO runtime test.
        """
        import shutil
        import subprocess

        header = stager.EDITS["include/linux/bio.h"][0].after
        first = header.index("static inline bool bio_is_zswap_stored_writeback")
        last = header.index("\n}\n", first) + len("\n}\n")
        predicate = header[first:last]
        clone = stager.EDITS["block/bio.c"][1].after
        first = clone.index("\tbio->bi_swap_origin =")
        last = clone.index(";\n", first) + len(";\n")
        copy_origin = clone[first:last]
        harness = (
            "#include <assert.h>\n#include <stdbool.h>\n"
            "enum swap_bio_origin { SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0,"
            " SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1 };\n"
            "#define REQ_OP_WRITE 1U\n#define REQ_SWAP (1U << 4)\n"
            "struct bio { unsigned int operation; unsigned int bi_opf;"
            " enum swap_bio_origin bi_swap_origin; };\n"
            "static unsigned int bio_op(const struct bio *bio)"
            " { return bio->operation; }\n"
            + predicate
            + "static void copy_origin_from_bio(struct bio *bio,"
            " const struct bio *bio_src) {\n"
            + copy_origin + "}\n"
            "int main(void) {\n"
            " struct bio original = { REQ_OP_WRITE, REQ_SWAP,"
            " SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK };\n"
            " struct bio child = { REQ_OP_WRITE, REQ_SWAP,"
            " SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN };\n"
            " copy_origin_from_bio(&child, &original);\n"
            " assert(bio_is_zswap_stored_writeback(&child));\n"
            " original.bi_opf = 0U;\n"
            " copy_origin_from_bio(&child, &original);\n"
            " assert(child.bi_swap_origin == SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);\n"
            " original.bi_opf = REQ_SWAP; original.operation = 0U;\n"
            " copy_origin_from_bio(&child, &original);\n"
            " assert(child.bi_swap_origin == SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);\n"
            " original.operation = REQ_OP_WRITE;"
            " original.bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN;\n"
            " copy_origin_from_bio(&child, &original);\n"
            " assert(child.bi_swap_origin == SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);\n"
            " original.bi_swap_origin = (enum swap_bio_origin)2;\n"
            " copy_origin_from_bio(&child, &original);\n"
            " assert(child.bi_swap_origin == SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN);\n"
            " return 0;\n}\n"
        )
        compilers = tuple(compiler for compiler in ("gcc", "clang")
                          if shutil.which(compiler))
        if not compilers:
            self.skipTest("no C compiler available")
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "origin.c"
            source.write_text(harness, encoding="utf-8")
            for compiler in compilers:
                with self.subTest(compiler=compiler):
                    executable = Path(temporary) / f"origin-{compiler}"
                    build = subprocess.run(
                        [compiler, "-std=c11", "-O1", "-g", "-Wall", "-Wextra",
                         "-Wpedantic", "-Wconversion", "-Werror",
                         "-fsanitize=undefined", "-fno-sanitize-recover=all",
                         str(source), "-o", str(executable)],
                        capture_output=True, text=True, check=False,
                        timeout=30)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    run = subprocess.run(
                        [str(executable)], capture_output=True,
                        text=True, check=False, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stderr)

    def test_authentication_aggregation_reset_clone_and_post_decompression(self):
        changed = {path: stager.render_source(path, "\n".join(
            edit.before for edit in edits)) for path, edits in stager.EDITS.items()}
        header = changed["include/linux/bio.h"]
        self.assertIn("BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1", header)
        self.assertIn("bio_op(bio) == REQ_OP_WRITE", header)
        self.assertIn("(bio->bi_opf & REQ_SWAP)", header)
        self.assertIn("bio->bi_swap_origin == SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK", header)
        block = changed["block/bio.c"]
        self.assertIn("bio->bi_swap_origin = SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN", block)
        self.assertIn("bio->bi_swap_origin = bio_is_zswap_stored_writeback(bio_src) ?", block)
        types = changed["include/linux/blk_types.h"]
        self.assertIn("SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0", types)
        self.assertIn("SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1", types)
        self.assertLess(types.index("bi_swap_origin"),
                        types.index("atomic_t", types.index("bi_swap_origin")))
        swap = changed["mm/page_io.c"]
        self.assertIn("!swap_bio_origin_can_merge(ctx->sio->swap_origin, ctx->swap_origin)", swap)
        self.assertIn("bio->bi_swap_origin = sio->swap_origin", swap)
        self.assertIn("sio->swap_origin = rw == WRITE &&", swap)
        self.assertIn("SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN", swap)
        zswap = changed["mm/zswap.c"]
        self.assertIn("ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK", zswap)
        self.assertNotIn("REQ_ZSWAP_WRITEBACK", "".join(changed.values()))
        # Count the authenticated producer assignment, not guarded copies.
        self.assertEqual(zswap.count("ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK;"), 1)
        # Full-source Kbuild and actual clone/split runtime execution are separate gates.

    def test_preimage_git_hash_and_wrong_blob_refuse(self):
        payload = b"real\n"
        self.assertEqual(stager.blob_sha(payload),
                         "17e3475343c4c9b504473a7f0dc1d124cde7fa2a")
        with self.assertRaisesRegex(stager.StagingError, "original-blob-mismatch"):
            stager.check_preimage("mm/zswap.c", payload, "0" * 40)
        stager.check_preimage("mm/zswap.c", payload, stager.blob_sha(payload))

    def test_missing_checkout_refusal_has_no_absolute_path(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "no-linux-checkout"
            manifest = Path(temporary) / "evidence.json"
            result = subprocess.run(
                [sys.executable, "-B", str(STAGER_PATH),
                 "--linux-root", str(missing), "--manifest", str(manifest)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr,
                             "FAIL: complete-git-checkout-required\n")
            self.assertFalse(manifest.exists())

    def test_wrong_git_revision_refused_before_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / ".git").mkdir()
            def fake_git(_root: Path, *command: str) -> str:
                if command == ("rev-parse", "--show-toplevel"):
                    return str(root)
                if command == ("rev-parse", "HEAD"):
                    return "0" * 40
                self.fail("preflight must stop before source or status checks")
            with mock.patch.object(stager, "git_output", side_effect=fake_git):
                with self.assertRaisesRegex(stager.StagingError, "linux-commit-mismatch"):
                    stager.validate_checkout(root)

    def test_missing_and_duplicate_anchor_fail_closed(self):
        path = "mm/page_io.c"
        edits = stager.EDITS[path]
        valid = "\n".join(edit.before for edit in edits)
        with self.assertRaisesRegex(stager.StagingError, "missing-or-duplicate-anchor"):
            stager.render_source(path, valid.replace(edits[0].before, "erased"))
        with self.assertRaisesRegex(stager.StagingError, "missing-or-duplicate-anchor"):
            stager.render_source(path, valid + "\n" + edits[0].before)

    def test_overlap_rejected_without_mutation(self):
        path = "mm/zswap.c"
        edits = (stager.Edit("abcdef", "ABCDEFGHI"),
                 stager.Edit("cde", "CDE"))
        with mock.patch.dict(stager.EDITS, {path: edits}):
            with self.assertRaisesRegex(stager.StagingError, "overlapping-anchors"):
                stager.render_source(path, "abcdef")

    def test_stage_then_reapply_fails_without_changing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            result = self.stage_fixture(root, originals, manifest)
            self.assertEqual(result["status"], "STAGED_SOURCE_ONLY")
            self.assertEqual(len(result["changed_paths"]), 6)
            self.assertEqual(json.loads(manifest.read_text()), result)
            for entry in result["changed_paths"]:
                data = (root / entry["path"]).read_bytes()
                self.assertEqual(stager.blob_sha(data), entry["staged_git_sha1"])
            stage_bytes = {p: (root / p).read_bytes() for p in stager.EDITS}
            with self.assertRaisesRegex(stager.StagingError, "original-blob-mismatch"):
                self.stage_fixture(root, originals, manifest)
            self.assertEqual(stage_bytes,
                             {p: (root / p).read_bytes() for p in stager.EDITS})

    def test_late_wrong_blob_preflight_leaves_entire_tree_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            tampered = root / "mm/zswap.c"
            tampered.write_bytes(tampered.read_bytes() + b"unexpected\n")
            before = {p: (root / p).read_bytes() for p in originals}
            with self.assertRaisesRegex(stager.StagingError, "original-blob-mismatch"):
                self.stage_fixture(root, originals, Path(temporary) / "manifest.json")
            self.assertEqual(before, {p: (root / p).read_bytes() for p in originals})
            self.assertFalse((Path(temporary) / "manifest.json").exists())

    def test_write_failure_rolls_back_all_changed_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            original_write_atomic = stager.write_atomic
            calls = 0
            def inject_write_failure(destination: Path, payload: bytes):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected third file write failure")
                original_write_atomic(destination, payload)
            with mock.patch.object(stager, "write_atomic", side_effect=inject_write_failure):
                with self.assertRaisesRegex(stager.StagingError, "publication-failed-rolled-back"):
                    self.stage_fixture(root, originals, Path(temporary) / "manifest.json")
            self.assertEqual(originals, {p: (root / p).read_bytes() for p in originals})

    def test_manifest_creation_error_rolls_back_staged_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            original_replace = stager.os.replace
            def fail_manifest_replace(source: Path, destination: Path):
                if Path(destination) == manifest:
                    raise OSError("injected evidence write failure")
                return original_replace(source, destination)
            with mock.patch.object(stager.os, "replace",
                                   side_effect=fail_manifest_replace):
                with self.assertRaisesRegex(stager.StagingError,
                                            "manifest-write-failed-rolled-back"):
                    self.stage_fixture(root, originals, manifest)
            self.assertEqual(originals,
                             {p: (root / p).read_bytes() for p in originals})
            self.assertFalse(manifest.exists())


    def test_manifest_replace_reported_failure_rolls_back_both_domains(self):
        """No stale success evidence after replace succeeded but raised."""
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_fixture(Path(temporary))
            manifest = Path(temporary) / "evidence.json"
            original_replace = stager.os.replace

            def fail_after_manifest_replace(source: Path, destination: Path):
                original_replace(source, destination)
                if Path(destination) == manifest:
                    raise OSError("injected error after manifest was replaced")

            with mock.patch.object(stager.os, "replace",
                                   side_effect=fail_after_manifest_replace):
                with self.assertRaisesRegex(stager.StagingError,
                                            "manifest-write-failed-rolled-back"):
                    self.stage_fixture(root, originals, manifest)
            self.assertFalse(manifest.exists())
            self.assertEqual(originals, {p: (root / p).read_bytes()
                                         for p in originals})

    def test_manifest_inside_linux_checkout_forbidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, original = self.make_fixture(Path(temporary))
            with self.assertRaisesRegex(stager.StagingError, "manifest-must-be-outside"):
                self.stage_fixture(root, original, root / "evidence.json")


    def test_kunit_registration_and_source_contract(self):
        self.assertEqual(set(stager.KUNIT_EDITS), {"block/Kconfig", "block/Makefile"})
        self.assertEqual(stager.KUNIT_SOURCE.count("KUNIT_CASE("), 5)
        self.assertIn("#include <kunit/test.h>", stager.KUNIT_SOURCE)
        self.assertIn("bio_prepare_reissue(&bio, NULL)", stager.KUNIT_SOURCE)
        self.assertIn("bio_split(&original,", stager.KUNIT_SOURCE)
        self.assertIn("swap_bio_origin_can_merge(", stager.KUNIT_SOURCE)
        self.assertNotIn("REQ_ZSWAP_WRITEBACK", stager.KUNIT_SOURCE)
        for path, edits in stager.KUNIT_EDITS.items():
            source = "\n\n/* separator */\n\n".join(edit.before for edit in edits)
            staged = stager.render_source(path, source)
            for edit in edits:
                self.assertIn(edit.after, staged)
                if edit.before not in edit.after:
                    self.assertNotIn(edit.before, staged)
            with self.assertRaises(stager.StagingError):
                stager.render_source(path, staged)
            with self.assertRaisesRegex(stager.StagingError,
                                        "missing-or-duplicate-anchor"):
                stager.render_source(path, source + "\n" + edits[0].before)

    def test_kunit_stage_all_nine_paths_and_reapplication(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_kunit_fixture(Path(temporary))
            evidence = Path(temporary) / "source.json"
            result = self.stage_fixture(root, originals, evidence,
                                        with_kunit=True)
            self.assertEqual(len(result["changed_paths"]), 9)
            self.assertEqual(result, json.loads(evidence.read_text()))
            addition = next(item for item in result["changed_paths"]
                            if item["path"] == stager.KUNIT_SOURCE_PATH)
            self.assertIsNone(addition["original_git_sha1"])
            self.assertIsNone(addition["original_sha256"])
            stage_bytes = {entry["path"]: (root / entry["path"]).read_bytes()
                           for entry in result["changed_paths"]}
            for entry in result["changed_paths"]:
                self.assertEqual(entry["staged_sha256"],
                                 hashlib.sha256(stage_bytes[entry["path"]]).hexdigest())
            with self.assertRaises(stager.StagingError):
                self.stage_fixture(root, originals, evidence, with_kunit=True)
            self.assertEqual(stage_bytes,
                             {p: (root / p).read_bytes() for p in stage_bytes})

    def test_kunit_collision_wrong_blob_and_new_file_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_kunit_fixture(Path(temporary))
            evidence = Path(temporary) / "source.json"
            addition = root / stager.KUNIT_SOURCE_PATH
            addition.write_bytes(b"unrelated source\n")
            unchanged = {p: (root / p).read_bytes() for p in originals}
            with self.assertRaisesRegex(stager.StagingError,
                                        "kunit-source-already-present"):
                self.stage_fixture(root, originals, evidence, with_kunit=True)
            self.assertEqual(unchanged,
                             {p: (root / p).read_bytes() for p in unchanged})
            addition.unlink()
            corrupted = root / "block/Kconfig"
            original_config = corrupted.read_bytes()
            corrupted.write_bytes(original_config + b"foreign change\n")
            with self.assertRaisesRegex(stager.StagingError,
                                        "original-blob-mismatch"):
                self.stage_fixture(root, originals, evidence, with_kunit=True)
            corrupted.write_bytes(original_config)
            original_write = stager.write_atomic

            def fail_after_add(destination: Path, payload: bytes):
                original_write(destination, payload)
                if destination == addition:
                    raise OSError("injected after new source creation")

            with mock.patch.object(stager, "write_atomic",
                                   side_effect=fail_after_add):
                with self.assertRaisesRegex(stager.StagingError,
                                            "publication-failed-rolled-back"):
                    self.stage_fixture(root, originals, evidence,
                                       with_kunit=True)
            self.assertFalse(addition.exists())
            self.assertFalse(evidence.exists())
            self.assertEqual(originals, {p: (root / p).read_bytes()
                                         for p in originals})

    def test_kunit_workflow_cannot_infer_source_only_pass(self):
        workflow = (STAGER_PATH.parents[2] /
                    ".github/workflows/phase-a-zswap-origin-kunit.yml").read_text()
        for token in ("--with-kunit", "CONFIG_KUNIT=y",
                      "CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST=y",
                      "CONFIG_ZSWAP=y", "# CONFIG_ZSWAP is not set",
                      "tools/testing/kunit/kunit.py", "verify_real_tap",
                      "Subtest:", "not ok", "kunit_cases_passed=5",
                      "staged_sha256"):
            self.assertIn(token, workflow)
        self.assertNotIn("echo KUNIT_PASS", workflow)
        self.assertNotIn("modprobe", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
