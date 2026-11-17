#!/usr/bin/env python3
"""Round025 source-first pinned Linux BIO sideband adversarial audit.

The C host fixture executes precisely the new CI-only ownership helpers, but
its lifecycle clone/split objects are MOCKS. Actual Linux bio.c hooks and
KUnit cases must be independently compiled from the pinned original tree.
None of these tests authorizes a compressed BIO or a loaded swap device.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
STAGER_PATH = ROOT / "tests/tools/stage-pinned-linux-zswap-sideband.py"
FIXTURE_PATH = (Path(__file__).parent / "fixtures" /
                "round025-sideband-host.c")
LOADER = importlib.util.spec_from_file_location("round025_sideband_stager",
                                                STAGER_PATH)
if not LOADER or not LOADER.loader:
    raise RuntimeError("stage module missing")
STAGER = importlib.util.module_from_spec(LOADER)
sys.modules[LOADER.name] = STAGER
LOADER.loader.exec_module(STAGER)


def host_owned_source() -> str:
    fixture = FIXTURE_PATH.read_text(encoding="utf-8")
    marker = "/* ROUND025_EXACT_CI_HELPERS */"
    if fixture.count(marker) != 1:
        raise AssertionError("host fixture code marker drift")
    functions = STAGER.CI_HELPERS
    for kernel_include in (
            "#include <linux/refcount.h>",
            "#include <linux/crc32c.h>",
            "#include <kunit/test.h>"):
        if functions.count(kernel_include) != 1:
            raise AssertionError("unexpected kernel include count")
        functions = functions.replace(kernel_include, "", 1)
    return fixture.replace(marker, functions, 1)


class Round025PinnedSideband(unittest.TestCase):
    def test_round025_stock_bio_lifecycle_and_fail_closed_compiler_gate(self) -> None:
        self.assertEqual(STAGER.PINNED_LINUX_COMMIT,
                         "c339f4010dea8b0d754f84ace70cd1b089878ef8")
        self.assertIn("SWAPZ_ROUND025_SIDEBAND_CI_ONLY", STAGER.CI_HELPERS)
        self.assertIn("refcount_inc_not_zero(", STAGER.CI_HELPERS)
        self.assertIn("refcount_dec_and_test(", STAGER.CI_HELPERS)
        self.assertIn("kfree_sensitive(owner)", STAGER.CI_HELPERS)
        self.assertIn("~crc32c(~0U,", STAGER.CI_HELPERS)
        self.assertIn("owner->compressed_length > 3568U", STAGER.CI_HELPERS)
        self.assertIn("return -EOPNOTSUPP;", STAGER.CI_HELPERS)
        self.assertIn("bio_init_clone(", STAGER.CI_KUNIT)
        self.assertIn("bio_prepare_reissue(", STAGER.CI_KUNIT)
        self.assertIn("bio_reset(", STAGER.CI_KUNIT)
        self.assertIn("bio_uninit(", STAGER.CI_KUNIT)
        self.assertNotIn("submit_bio(", STAGER.CI_HELPERS)
        self.assertNotIn("bi_private", STAGER.CI_HELPERS)
        self.assertNotIn("bi_io_vec", STAGER.CI_HELPERS)

    def test_round025_stager_refuses_invalid_preimages_and_anchors(self) -> None:
        path = "block/bio.c"
        synthetic = (
            '#include "blk-cgroup.h"\n'
            "\tbio_crypt_free_ctx(bio);\n"
            "\tbio->bi_end_io = NULL;\n\tbio->bi_private = NULL;\n"
            "void bio_prepare_reissue(struct bio *bio, struct block_device *bdev)\n{\n"
            "\telse\n\t\tbio->bi_io_vec = bio_src->bi_io_vec;\n"
            "EXPORT_SYMBOL(bio_init_clone);\n"
        ).encode("utf-8")
        with patch.dict(STAGER.PINNED_BLOBS,
                        {path: STAGER.blob_sha(synthetic)}):
            staged = STAGER.render_source(path, synthetic)
            self.assertGreater(
                staged.count(b"SWAPZ_ROUND025_SIDEBAND_CI_ONLY"), 5)
            self.assertIn(b"swapz_ci_bio_detach(bio)", staged)
            self.assertIn(b"swapz_ci_owned_get(owner)", staged)
            self.assertIn(b"swapz_ci_clone_lifetime_kunit", staged)
            self.assertIn(b"swapz_ci_live_compressed_admit(", staged)
            with self.assertRaisesRegex(STAGER.SourceGateError,
                                        "original_git_blob_mismatch"):
                STAGER.render_source(path, synthetic + b"tamper")
            with self.assertRaisesRegex(STAGER.SourceGateError,
                                        "original_git_blob_mismatch"):
                STAGER.render_source(path, staged)
        with patch.dict(STAGER.PINNED_BLOBS,
                        {path: STAGER.blob_sha(synthetic + synthetic)}):
            with self.assertRaisesRegex(STAGER.SourceGateError,
                                        "anchor_missing_or_duplicated"):
                STAGER.render_source(path, synthetic + synthetic)
        with self.assertRaisesRegex(STAGER.SourceGateError, "outside_own_paths"):
            STAGER.render_source("mm/zswap.c", synthetic)

    def test_round025_exact_pinned_linux_source_when_available(self) -> None:
        root_name = os.environ.get("ROUND025_PINNED_LINUX")
        if not root_name:
            self.skipTest("Full pinned Linux tree NOT_RUN locally")
        root = Path(root_name)
        required = {
            "block/bio.c": (
                "void bio_reset(struct bio *bio",
                "bio_uninit(bio);",
                "void bio_reuse(struct bio *bio",
                "void bio_prepare_reissue(struct bio *bio",
                "static int __bio_clone(struct bio *bio",
                "bio_alloc_clone(",
                "bio_init_clone(",
                "bio_uninit(bio);",
            ),
            "include/linux/blk_types.h": (
                "struct bio {",
                "void\t\t\t*bi_private;",
                "#define BIO_RESET_BYTES",
            ),
        }
        for path, markers in required.items():
            with self.subTest(path=path):
                original = (root / path).read_bytes()
                self.assertEqual(STAGER.blob_sha(original),
                                 STAGER.PINNED_BLOBS[path])
                text = original.decode("utf-8")
                for marker in markers:
                    self.assertIn(marker, text)
                staged = STAGER.render_source(path, original)
                self.assertNotEqual(staged, original)
                self.assertIn(STAGER.CI_MACRO.encode("ascii"), staged)

    def _test_compiler(self, compiler: str) -> None:
        path = shutil.which(compiler)
        self.assertIsNotNone(path, f"{compiler} required for compiler audit")
        with tempfile.TemporaryDirectory(
                prefix=f"round025-sideband-{compiler}-") as temporary:
            source_path = Path(temporary) / "owned.c"
            binary = Path(temporary) / "owned"
            source_path.write_text(host_owned_source(), encoding="utf-8")
            command = [
                path, "-std=gnu11", "-O1", "-g",
                "-Wall", "-Wextra", "-Werror", "-Wconversion", "-Wshadow",
                "-fno-omit-frame-pointer", "-fno-sanitize-recover=all",
                "-fsanitize=address,undefined", "-pthread",
                str(source_path), "-o", str(binary),
            ]
            built = subprocess.run(command, text=True, capture_output=True,
                                   timeout=60, check=False)
            self.assertEqual(built.returncode, 0,
                             f"{compiler} first compiler failure:\n"
                             f"{built.stderr[-5000:]}")
            environment = dict(os.environ)
            environment.update(ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
            ran = subprocess.run([str(binary)], text=True,
                                 capture_output=True, timeout=30,
                                 env=environment, check=False)
            self.assertEqual(ran.returncode, 0,
                             f"{compiler} first runtime failure:\n"
                             f"{ran.stderr[-5000:]}")
            self.assertIn("ROUND025_SIDE_BAND_HOST_SOURCE_ONLY_PASS",
                          ran.stdout)
            self.assertIn("LIVE_COMPRESSED=DISABLED", ran.stdout)

    def test_round025_gcc_sanitizers_owned_copy_and_refcount(self) -> None:
        self._test_compiler("gcc")

    def test_round025_clang_sanitizers_owned_copy_and_refcount(self) -> None:
        self._test_compiler("clang")


if __name__ == "__main__":
    unittest.main(verbosity=2)
