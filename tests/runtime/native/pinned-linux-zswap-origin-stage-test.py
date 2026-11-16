#!/usr/bin/env python3
"""Rootless tests for actual pinned Linux C/H staging transitions, not Kbuild."""

from __future__ import annotations

import importlib.util
import json
import re
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



# A names-only grep can count skipped, repeated or forged cases as PASS.
# This parser consumes the raw output of exit-zero pinned kunit.py, and checks
# the complete named suite plan, all five unique cases and its suite result.
KUNIT_CASE_NAMES = (
    "swap_bio_origin_authentication_test",
    "swap_bio_origin_reset_reuse_reissue_test",
    "swap_bio_origin_clone_test",
    "swap_bio_origin_split_test",
    "swap_bio_origin_merge_reject_test",
)
KUNIT_LOG_LIMIT = 8 * 1024 * 1024
KUNIT_RESULT_LINE = re.compile(
    r"^(?P<state>ok|not ok)\s+(?P<ordinal>[0-9]+)\s+"
    r"(?:-\s*)?(?P<name>swap_bio_origin(?:_[a-z_]+_test)?)"
    r"(?:\s+(?P<directive>#.*))?$"
)


def verify_kunit_tap(output: str) -> int:
    """Require the real five-case BIO suite; no absent, skipped or torn TAP."""
    if not output or len(output.encode("utf-8")) > KUNIT_LOG_LIMIT or "\x00" in output:
        raise ValueError("invalid KUnit output extent")
    # --raw_output=kunit removes normal printk prefixes; --raw_output=all
    # retains bounded kernel timestamps. Both are supported here.
    lines = [
        re.sub(r"^\[\s*[0-9]+\.[0-9]+\]\s*", "", line.strip())
        for line in output.splitlines()
    ]
    headers = [index for index, line in enumerate(lines)
               if line == "# Subtest: swap_bio_origin"]
    if len(headers) != 1 or not any(
        line in ("TAP version 13", "TAP version 14", "KTAP version 1")
        for line in lines[:headers[0]]
    ):
        raise ValueError("missing or duplicate genuine KUnit suite header")
    if any(re.match(r"^not ok\s+[0-9]+(?:\s|$)", line) for line in lines):
        raise ValueError("failed KUnit TAP result")

    header_index = headers[0]
    plan_count = 0
    executed: list[str] = []
    summary_count = 0
    for line in lines[header_index + 1:]:
        if line == "1..5":
            if executed or summary_count:
                raise ValueError("late KUnit suite plan")
            plan_count += 1
            continue
        result = KUNIT_RESULT_LINE.fullmatch(line)
        if result:
            if result["directive"] or result["state"] != "ok":
                raise ValueError("skipped or failed BIO case")
            if result["name"] == "swap_bio_origin":
                if len(executed) != len(KUNIT_CASE_NAMES):
                    raise ValueError("premature BIO suite summary")
                summary_count += 1
                continue
            if summary_count or not plan_count or result["name"] not in KUNIT_CASE_NAMES:
                raise ValueError("unplanned or late BIO test")
            expected_index = len(executed)
            if (expected_index >= len(KUNIT_CASE_NAMES) or
                int(result["ordinal"]) != expected_index + 1 or
                result["name"] != KUNIT_CASE_NAMES[expected_index]):
                raise ValueError("missing, duplicated or reordered BIO case")
            executed.append(result["name"])
        elif not summary_count and re.match(r"^(?:ok|not ok)\s+[0-9]+(?:\s|$)", line):
            raise ValueError("unexpected BIO case result")
        elif not summary_count and "# SKIP" in line.upper():
            raise ValueError("skipped BIO case")
    if plan_count != 1 or executed != list(KUNIT_CASE_NAMES) or summary_count != 1:
        raise ValueError("incomplete or duplicate BIO KUnit TAP")
    return len(executed)


def verify_kunit_workflow_contract(contents: str) -> None:
    """Reject real YAML shell ordering/identity gaps before coordinator CI."""
    required = (
        "c339f4010dea8b0d754f84ace70cd1b089878ef8",
        # Both immutable upstream checkout and runtime pin must agree.
        f"ref: {stager.LINUX_COMMIT}",
        f"pinned={stager.LINUX_COMMIT}",
        '[[ "$(git -C linux rev-parse HEAD)" == "$pinned" ]]',
        '--linux-root linux --manifest "$evidence/sources.json" --with-kunit',
        "block/swap-bio-origin-kunit.c",
        "block/swap-bio-origin-kunit.o",
        "CONFIG_SWAP=y",
        "CONFIG_KUNIT=y",
        "CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST=y",
        "CONFIG_ZSWAP=y",
        "# CONFIG_ZSWAP is not set",
        '# CONFIG_BLK_CGROUP is not set',
        '# CONFIG_CGROUPS is not set',
        'run_checked verify_uml_config ',
        'run_checked verify_profile_pair ',
        'pinned-linux-kunit-uml-config-test.py',
        "--make_options=W=1",
        'grep -Fxq CONFIG_ZSWAP=y "$uml_dir/.config"',
        """grep -Fxq '# CONFIG_ZSWAP is not set' "$uml_dir/.config" """.strip(),
        'sha256sum "$captured"',
        '--verify-kunit-tap "$captured"',
        "kunit_cases_passed=5",
        "if: always()",
    )
    if (any(value not in contents for value in required) or
        contents.count("block/swap-bio-origin-kunit.c") != 2 or
        contents.count("block/swap-bio-origin-kunit.o") != 2 or
        contents.count("# CONFIG_CGROUPS is not set") != 2):
        raise ValueError("incomplete pinned KUnit workflow contract")
    ordered = (
        "run_checked rootless ",
        "run_checked stage ",
        "run_checked modified_objects ",
        "run_checked uml_kunit ",
        "run_checked verify_uml_config ",
        'cp -- "$log" "$captured"',
        "run_checked verify_real_tap ",
        "kunit_cases_passed=5",
        "run_checked verify_profile_pair ",
    )
    positions = [contents.find(token) for token in ordered]
    if any(index < 0 for index in positions) or positions != sorted(positions):
        raise ValueError("KUnit publication before source, execution or TAP verification")
    if "echo KUNIT_PASS" in contents or "printf 'kunit_cases_passed=5" in contents[:positions[-2]]:
        raise ValueError("forged or premature KUnit PASS marker")


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



    def test_round012_tap_accepts_exact_five_executed_cases(self):
        tap = ("TAP version 14\n1..1\n"
               "    # Subtest: swap_bio_origin\n    1..5\n" +
               "".join(f"    ok {number} - {name}\n"
                       for number, name in enumerate(KUNIT_CASE_NAMES, 1)) +
               "ok 1 - swap_bio_origin\n")
        self.assertEqual(verify_kunit_tap(tap), 5)
        self.assertEqual(verify_kunit_tap(
            tap.replace("TAP version 14", "[    0.123456] KTAP version 1")), 5)

    def test_round012_tap_refuses_adversarial_executed_case_claims(self):
        good = ("TAP version 14\n1..1\n"
                "# Subtest: swap_bio_origin\n1..5\n" +
                "".join(f"ok {number} - {name}\n"
                        for number, name in enumerate(KUNIT_CASE_NAMES, 1)) +
                "ok 1 - swap_bio_origin\n")
        cases = {
            "missing-header": good.replace("TAP version 14\n", ""),
            "wrong-version": good.replace("TAP version 14", "TAP version 99"),
            "missing-suite": good.replace("# Subtest: swap_bio_origin", "# other"),
            "duplicated-suite": good + good,
            "missing-plan": good.replace("1..5\n", ""),
            "wrong-plan": good.replace("1..5\n", "1..4\n"),
            "duplicate-plan": good.replace("1..5\n", "1..5\n1..5\n"),
            "missing-case": good.replace(
                f"ok 5 - {KUNIT_CASE_NAMES[4]}\n", ""),
            "reordered-cases": good.replace(
                f"ok 2 - {KUNIT_CASE_NAMES[1]}",
                f"ok 2 - {KUNIT_CASE_NAMES[2]}"),
            "duplicate-case": good.replace(
                f"ok 2 - {KUNIT_CASE_NAMES[1]}",
                f"ok 1 - {KUNIT_CASE_NAMES[0]}"),
            "failed-case": good.replace(
                f"ok 2 - {KUNIT_CASE_NAMES[1]}",
                f"not ok 2 - {KUNIT_CASE_NAMES[1]}"),
            "skipped-case": good.replace(
                f"ok 3 - {KUNIT_CASE_NAMES[2]}",
                f"ok 3 - {KUNIT_CASE_NAMES[2]} # SKIP disabled"),
            "missing-summary": good.replace("ok 1 - swap_bio_origin\n", ""),
            "failed-summary": good.replace(
                "ok 1 - swap_bio_origin\n", "not ok 1 - swap_bio_origin\n"),
            "duplicate-summary": good + "ok 1 - swap_bio_origin\n",
            "shell-echo-forgery": good.replace(
                f"ok 1 - {KUNIT_CASE_NAMES[0]}",
                f"echo ok 1 - {KUNIT_CASE_NAMES[0]}"),
            "unrelated-failed-test": good + "not ok 2 - unrelated_suite\n",
            "incomplete-suffix": good[:-2],
            "NUL-byte": good + "\x00",
            "unexpected-sixth-case": good.replace(
                "ok 1 - swap_bio_origin\n",
                "ok 6 - unrelated_extra_test\nok 1 - swap_bio_origin\n"),
            "standalone-skip-directive": good.replace(
                f"ok 2 - {KUNIT_CASE_NAMES[1]}\n",
                f"ok 2 - {KUNIT_CASE_NAMES[1]}\n# SKIP ignored\n"),
            "excessive-output": good + "X" * KUNIT_LOG_LIMIT,
        }
        self.assertEqual(len(cases), 22)
        for name, invalid in cases.items():
            with self.subTest(negative=name):
                with self.assertRaises(ValueError):
                    verify_kunit_tap(invalid)

    def test_round012_real_kunit_source_mutation_negatives(self):
        source = stager.KUNIT_SOURCE
        mutations = {
            "wrong-sector-units": source.replace(
                "PAGE_SIZE >> (SECTOR_SHIFT + 1)", "PAGE_SIZE >> 10"),
            "missing-bio-clone": source.replace(
                "bio_init_clone(NULL, &clone, &original, GFP_KERNEL)",
                "bio_init(&clone, NULL, &vector, 1, REQ_OP_WRITE | REQ_SWAP)"),
            "missing-reissue": source.replace("bio_prepare_reissue(&bio, NULL);", ""),
            "missing-bio-reuse": source.replace(
                "bio_reuse(&bio, REQ_OP_WRITE | REQ_SWAP);", ""),
            "missing-bio-reset": source.replace(
                "bio_reset(&bio, NULL, REQ_OP_WRITE | REQ_SWAP);", ""),
            "missing-bio-put": source.replace("bio_put(split);", ""),
            "missing-page-free": source.replace("__free_page(page);", ""),
            "missing-case": source.replace(
                "KUNIT_CASE(swap_bio_origin_split_test),", ""),
            "duplicate-case": source.replace(
                "KUNIT_CASE(swap_bio_origin_split_test),",
                "KUNIT_CASE(swap_bio_origin_split_test),\n"
                "\tKUNIT_CASE(swap_bio_origin_split_test),"),
            "missing-source": "",
        }
        self.assertEqual(len(mutations), 10)
        for name, invalid in mutations.items():
            with self.subTest(negative=name):
                self.assertNotEqual(invalid, source)
                with self.assertRaisesRegex(stager.StagingError,
                                            "invalid-kunit-source-contract"):
                    stager.validate_kunit_source(invalid)
        # An invalid generated C source must stop the *real* stager before
        # publishing any of the eight edited upstream files or the new C file.
        with tempfile.TemporaryDirectory() as temporary:
            root, originals = self.make_kunit_fixture(Path(temporary))
            evidence = Path(temporary) / "source.json"
            with mock.patch.object(stager, "KUNIT_SOURCE",
                                   mutations["wrong-sector-units"]):
                with self.assertRaisesRegex(stager.StagingError,
                                            "invalid-kunit-source-contract"):
                    self.stage_fixture(root, originals, evidence, with_kunit=True)
            self.assertEqual(originals,
                             {path: (root / path).read_bytes()
                              for path in originals})
            self.assertFalse((root / stager.KUNIT_SOURCE_PATH).exists())
            self.assertFalse(evidence.exists())

    def test_round012_registration_mutation_refuses_staging(self):
        mutations = (
            ("block/Kconfig", "config SWAP_BIO_ORIGIN_KUNIT_TEST",
             "config SWAP_BIO_ORIGIN_TEST_DISABLED"),
            ("block/Kconfig", "depends on KUNIT && SWAP", "depends on SWAP"),
            ("block/Makefile", "obj-$(CONFIG_SWAP_BIO_ORIGIN_KUNIT_TEST)",
             "obj-$(CONFIG_SWAP_BIO_ORIGIN_MISSING)"),
        )
        for path, original, corrupt in mutations:
            with self.subTest(path=path, corrupt=corrupt):
                updated = tuple(stager.Edit(
                    edit.before, edit.after.replace(original, corrupt))
                    for edit in stager.KUNIT_EDITS[path])
                with mock.patch.dict(stager.KUNIT_EDITS, {path: updated}):
                    excerpt = "\n".join(edit.before for edit in updated)
                    with self.assertRaisesRegex(stager.StagingError,
                                                "invalid-origin-postimage"):
                        stager.render_source(path, excerpt)

    def test_round012_workflow_mutation_negatives(self):
        path = STAGER_PATH.parents[2] / ".github/workflows/phase-a-zswap-origin-kunit.yml"
        workflow = path.read_text(encoding="utf-8")
        verify_kunit_workflow_contract(workflow)
        mutations = (
            ("missing-tap-verifier",
             'run_checked verify_real_tap ', 'echo PASS # '),
            ("missing-UML-Kconfig-validation",
             'grep -Fxq CONFIG_ZSWAP=y "$uml_dir/.config"', 'true # missing'),
            ("missing-UML-effective-diagnostic",
             "run_checked verify_uml_config ", "printf ignored "),
            ("missing-conditional-CGROUPS-protection",
             "# CONFIG_CGROUPS is not set", "CONFIG_CGROUPS=y"),
            ("missing-final-independent-profile-gate",
             "run_checked verify_profile_pair ", "printf profile_pass "),
            ("missing-untracked-C-source",
             "block/swap-bio-origin-kunit.c", "block/not-the-kunit-source.c"),
            ("missing-modified-build",
             "run_checked modified_objects ", "printf modified_objects "),
            ("missing-run",
             "run_checked uml_kunit ", "printf uml_kunit "),
            ("wrong-source",
             stager.LINUX_COMMIT, "0" * 40),
            ("missing-W1",
             "--make_options=W=1", "--make_options=W=0"),
            ("missing-disabled-profile",
             """grep -Fxq '# CONFIG_ZSWAP is not set' "$uml_dir/.config" """.strip(),
             "true # disabled profile not checked"),
            ("missing-object-allowlist",
             "block/swap-bio-origin-kunit.o", "block/other.o"),
            ("forged-PASS",
             "run_checked verify_real_tap ", "echo KUNIT_PASS\n"
              "            run_checked verify_real_tap "),
            ("premature-PASS",
             "run_checked verify_real_tap ",
             "printf 'kunit_cases_passed=5\\n' >> \"$manifest\"\n"
             "            run_checked verify_real_tap "),
        )
        for name, original, modified in mutations:
            with self.subTest(negative=name):
                self.assertIn(original, workflow)
                with self.assertRaises(ValueError):
                    verify_kunit_workflow_contract(
                        workflow.replace(original, modified, 1))

    def test_kunit_registration_and_source_contract(self):
        self.assertEqual(set(stager.KUNIT_EDITS), {"block/Kconfig", "block/Makefile"})
        self.assertEqual(stager.KUNIT_SOURCE.count("KUNIT_CASE("), 5)
        stager.validate_kunit_source(stager.KUNIT_SOURCE)
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
                      "--verify-kunit-tap", "--raw_output", "kunit_cases_passed=5",
                      "staged_sha256"):
            self.assertIn(token, workflow)
        self.assertNotIn("echo KUNIT_PASS", workflow)
        self.assertNotIn("modprobe", workflow)


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--verify-kunit-tap":
        try:
            path = Path(sys.argv[2])
            if not path.is_file() or path.stat().st_size > KUNIT_LOG_LIMIT:
                raise ValueError("missing or oversized KUnit evidence")
            verify_kunit_tap(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            print("FAIL: incomplete-or-invalid-swap-bio-origin-kunit-tap",
                  file=sys.stderr)
            return 1
        return 0
    unittest.main(verbosity=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
