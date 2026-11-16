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

    def stage_fixture(self, root: Path, payloads: dict[str, bytes], manifest: Path):
        synthetic_preimages = {
            path: stager.blob_sha(payload) for path, payload in payloads.items()
        }
        with mock.patch.object(stager, "ORIGINAL_BLOBS", synthetic_preimages), \
             mock.patch.object(stager, "validate_checkout"):
            return stager.stage_checkout(root, manifest)

    def test_pinned_source_identity_and_real_anchor_structure(self):
        self.assertEqual(stager.LINUX_COMMIT,
                         "c339f4010dea8b0d754f84ace70cd1b089878ef8")
        self.assertEqual(len(stager.ORIGINAL_BLOBS), 7)
        self.assertEqual(set(stager.EDITS), set(stager.ORIGINAL_BLOBS) - {"Makefile"})
        self.assertEqual(sum(map(len, stager.EDITS.values())), 11)
        for path, edits in stager.EDITS.items():
            excerpts = "\n\n/* separator */\n\n".join(edit.before for edit in edits)
            updated = stager.render_source(path, excerpts)
            for edit in edits:
                self.assertIn(edit.after, updated)
                self.assertNotIn(edit.before, updated)
            with self.assertRaises(stager.StagingError):
                stager.render_source(path, updated)

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
        self.assertIn("bio->bi_swap_origin = bio_src->bi_swap_origin", block)
        types = changed["include/linux/blk_types.h"]
        self.assertIn("SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN = 0", types)
        self.assertIn("SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK = 1", types)
        self.assertLess(types.index("bi_swap_origin"), types.index("atomic_t"))
        swap = changed["mm/page_io.c"]
        self.assertIn("rw == WRITE && ctx->sio->swap_origin != ctx->swap_origin", swap)
        self.assertIn("bio->bi_swap_origin = sio->swap_origin", swap)
        self.assertIn("sio->swap_origin = rw == WRITE ? ctx->swap_origin", swap)
        self.assertIn("SWAP_BIO_ORIGIN_ORDINARY_OR_UNKNOWN", swap)
        zswap = changed["mm/zswap.c"]
        self.assertIn("ctx.swap_origin = SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK", zswap)
        self.assertNotIn("REQ_ZSWAP_WRITEBACK", "".join(changed.values()))
        self.assertEqual("".join(changed.values()).count("= SWAP_BIO_ORIGIN_ZSWAP_STORED_WRITEBACK"), 2)
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

    def test_manifest_inside_linux_checkout_forbidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, original = self.make_fixture(Path(temporary))
            with self.assertRaisesRegex(stager.StagingError, "manifest-must-be-outside"):
                self.stage_fixture(root, original, root / "evidence.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
