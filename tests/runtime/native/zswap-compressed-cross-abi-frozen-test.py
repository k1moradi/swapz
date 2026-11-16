#!/usr/bin/env python3
"""Round023 frozen-source compiled producer->consumer interoperability audit.

Only Git object reads and short-lived host C executables. The producer's #if 0
model is compiled *only* into an isolated test translation unit; the real
kernel bridge and consumer import remain disabled. All authority/mapping
inputs in the C harness are explicitly MOCK/UNTRUSTED, not a live BIO or ACK.
"""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
FROZEN_COMMIT = "8ad53ee4f57c5f8b272ca3ef4fadf1d8cd7cfbc8"
ORIGINAL_BLOBS = {
    "tests/tools/stage-pinned-linux-zswap-origin.py":
        "6f20406ca0efea9fd1488c089b3d96c2e27ee774",
    "src/kernel/zswap-import-codec.h":
        "8c496c53546462ae14ade8990231d3cdaca3294e",
    "src/kernel/codec.c":
        "ce36845428743ce506c143ef9a3be1aacadd6bbd",
    "src/kernel/codec.h":
        "e89d316b9cf49f82df0b77648c1be1731607987d",
}
FIXTURE = (Path(__file__).resolve().parent / "fixtures" /
           "round023-cross-abi-interop.c")
INJECTION = "/* ROUND023_EXACT_DISABLED_PRODUCER_FUNCTIONS */"
DISABLED_START = "#if 0 /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */"
DISABLED_END = "#endif /* SWAPZ_COMPRESSED_HANDOFF_DISABLED_NO_PINNED_BIO_ABI */"
SOURCE_INCLUDE_LINES = (
    "#include <linux/crc32c.h>",
    "#include <crypto/sha2.h>",
)
CRC_REFERENCES = (
    "~crc32c(~0U, owned_bytes, entry->length)",
    "~crc32c(~0U, transfer->owned_bytes, transfer->compressed_length)",
)


def git_source(object_name: str) -> bytes:
    """Read only the exact committed Git object; no source-tree mutation."""
    command = ["git", "-C", str(ROOT), "show", object_name]
    result = subprocess.run(command, capture_output=True, timeout=20,
                            check=False)
    if result.returncode:
        raise AssertionError(
            f"frozen Git object unavailable: {object_name} "
            f"(exit {result.returncode}); no unverified replacement allowed")
    if len(result.stdout) > 1_048_576:
        raise AssertionError("frozen source object exceeds bounded test input")
    return result.stdout


def git_blob_sha(source: bytes) -> str:
    header = b"blob " + str(len(source)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + source).hexdigest()


def exact_round022_files() -> dict[str, bytes]:
    frozen = {}
    for name, expected_sha in ORIGINAL_BLOBS.items():
        source = git_source(f"{FROZEN_COMMIT}:{name}")
        if git_blob_sha(source) != expected_sha:
            raise AssertionError(f"frozen blob content mismatch: {name}")
        frozen[name] = source
    return frozen


def producer_model(stager_source: bytes) -> str:
    """Extract the actual source-owned literal without executing the stager."""
    syntax = ast.parse(stager_source.decode("utf-8"))
    candidates = [
        statement.value
        for statement in syntax.body
        if isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == "COMPRESSED_HANDOFF_SOURCE"
    ]
    if len(candidates) != 1:
        raise AssertionError("missing/duplicate original source literal")
    source = ast.literal_eval(candidates[0])
    if not isinstance(source, str) or not 3000 <= len(source) <= 30_000:
        raise AssertionError("bounded disabled producer source not found")
    if source.count(DISABLED_START) != 1 or source.count(DISABLED_END) != 1:
        raise AssertionError("original compressed producer not disabled")
    if source.index(DISABLED_START) >= source.index(DISABLED_END):
        raise AssertionError("producer disable guard is not ordered")
    for fragment in CRC_REFERENCES:
        if source.count(fragment) != 1:
            raise AssertionError("incorrect original producer CRC32C convention")
    if ("ZSWAP_SWAPZ_COMPRESSED_MAX 3568U" not in source or
            "ZSWAP_SWAPZ_LOGICAL_BYTES 4096U" not in source or
            "ZSWAP_SWAPZ_RECORD_VERSION 1U" not in source or
            "zswap_swapz_bind_stored_entry(" not in source or
            "zswap_swapz_capture_owned_payload(" not in source or
            "zswap_swapz_owned_payload_submit(" not in source or
            "zswap_swapz_owned_payload_finish(" not in source or
            "zswap_swapz_owned_payload_abort(" not in source):
        raise AssertionError("producer source not the frozen stored-entry model")
    return source


def compiler_source(disabled_model: str) -> str:
    """Compile the unedited C bodies, removing the #if 0 only in host memory."""
    if disabled_model.count(DISABLED_START) != 1 or \
            disabled_model.count(DISABLED_END) != 1:
        raise AssertionError("no uniquely disabled model to compile")
    source = disabled_model.replace(DISABLED_START, "", 1)
    source = source.replace(DISABLED_END, "", 1)
    for include in SOURCE_INCLUDE_LINES:
        if source.count(include) != 1:
            raise AssertionError("kernel-only include unexpectedly changed")
        source = source.replace(include, "", 1)
    return source


def mutated_producer(source: str, fault: str) -> str:
    """Changing both producer CRC uses is deliberately incorrect and isolated."""
    if fault == "seed_zero":
        replacements = (
            "~crc32c(0U, owned_bytes, entry->length)",
            "~crc32c(0U, transfer->owned_bytes, transfer->compressed_length)",
        )
    elif fault == "ieee":
        replacements = (
            "crc32_ieee_bytes(owned_bytes, entry->length)",
            "crc32_ieee_bytes(transfer->owned_bytes, transfer->compressed_length)",
        )
    else:
        raise ValueError("unsupported negative compiler fixture")
    for expected, replacement in zip(CRC_REFERENCES, replacements):
        if source.count(expected) != 1:
            raise AssertionError("cannot mutate source-authenticated CRC site")
        source = source.replace(expected, replacement, 1)
    return source


class Round023CrossAbi(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frozen = exact_round022_files()
        cls.producer = producer_model(
            cls.frozen["tests/tools/stage-pinned-linux-zswap-origin.py"])
        cls.fixture = FIXTURE.read_text(encoding="utf-8")
        if cls.fixture.count(INJECTION) != 1:
            raise AssertionError("source insertion marker must be unique")

    def test_round023_original_source_is_disabled_and_frozen(self) -> None:
        self.assertIn(DISABLED_START, self.producer)
        header = self.frozen["src/kernel/zswap-import-codec.h"].decode("utf-8")
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U", header)
        self.assertIn("swapz_crc32c_bytes(compressed_bytes", header)
        self.assertIn("LZ4_decompress_safe(", header)
        codec = self.frozen["src/kernel/codec.c"].decode("utf-8")
        self.assertIn("return ~swapz_crc32c_state(~0U, data, length);", codec)
        self.assertIn("return crc32c(state, data, length);", codec)
        self.assertIn("0x82f63b78", self.fixture)
        self.assertIn("0xedb88320", self.fixture)
        self.assertNotIn("submit_bio(", self.producer)

        # Concurrent Round023 workers cannot silently enable either route.
        current_stager = (ROOT / "tests/tools/stage-pinned-linux-zswap-origin.py")
        current_import = ROOT / "src/kernel/zswap-import-codec.h"
        self.assertIn(DISABLED_START,
                      current_stager.read_text(encoding="utf-8"))
        self.assertIn("#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U",
                      current_import.read_text(encoding="utf-8"))

    def test_round023_source_mutations_fail_closed(self) -> None:
        for fragment in CRC_REFERENCES:
            with self.subTest(fragment=fragment):
                changed = self.producer.replace(fragment, "crc32(0,", 1)
                with self.assertRaisesRegex(
                        AssertionError, "CRC32C convention"):
                    producer_model(
                        ("COMPRESSED_HANDOFF_SOURCE = " +
                         repr(changed)).encode("utf-8"))
        for deleted in (DISABLED_START, DISABLED_END):
            with self.subTest(guard=deleted):
                changed = self.producer.replace(deleted, "", 1)
                with self.assertRaisesRegex(
                        AssertionError, "not disabled"):
                    producer_model(
                        ("COMPRESSED_HANDOFF_SOURCE = " +
                         repr(changed)).encode("utf-8"))

    def _run_compiler(self, compiler: str) -> None:
        executable = shutil.which(compiler)
        self.assertIsNotNone(executable, f"required compiler missing: {compiler}")
        base_producer = compiler_source(self.producer)
        with tempfile.TemporaryDirectory(
                prefix=f"swapz-round023-cross-{compiler}-") as temp:
            directory = Path(temp)
            for name in ("codec.c", "codec.h", "zswap-import-codec.h"):
                repository_path = "src/kernel/" + name
                (directory / name).write_bytes(self.frozen[repository_path])
            # The original production codec.c is separately warning-clean at
            # its established -Wall/-Wextra/-Werror gate. Its legacy size_t
            # conversions do not belong to this Agent4 fixture. The NEW
            # producer adapter gets stricter conversion and shadow warnings.
            common_flags = [
                "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                "-fno-omit-frame-pointer", "-fno-sanitize-recover=all",
                "-fsanitize=address,undefined", "-pthread",
                "-I", str(directory),
            ]
            codec_object = directory / "production-codec.o"
            codec_command = [
                executable, *common_flags, "-c",
                str(directory / "codec.c"), "-o", str(codec_object),
            ]
            codec_build = subprocess.run(
                codec_command, capture_output=True, text=True,
                check=False, timeout=120)
            self.assertEqual(
                codec_build.returncode, 0,
                f"{compiler} original production codec compile failed:\n"
                f"{codec_build.stderr[-6000:]}")
            for fault in ("original", "seed_zero", "ieee"):
                with self.subTest(compiler=compiler, producer=fault):
                    producer = (base_producer if fault == "original" else
                                mutated_producer(base_producer, fault))
                    generated = self.fixture.replace(INJECTION, producer)
                    source_path = directory / f"round023-{fault}.c"
                    binary = directory / f"round023-{fault}"
                    source_path.write_text(generated, encoding="utf-8")
                    source_object = directory / f"round023-{fault}.o"
                    source_command = [
                        executable, *common_flags, "-Wconversion", "-Wshadow",
                    ]
                    if fault != "original":
                        source_command.append(
                            "-DROUND023_EXPECT_WRONG_PRODUCER_CRC=1")
                    source_command += [
                        "-c", str(source_path), "-o", str(source_object),
                    ]
                    built = subprocess.run(
                        source_command, capture_output=True, text=True,
                        check=False, timeout=120)
                    self.assertEqual(
                        built.returncode, 0,
                        f"{compiler} {fault} source compile failed:\n"
                        f"{built.stderr[-6000:]}")
                    link_command = [
                        executable, "-fsanitize=address,undefined", "-pthread",
                        str(source_object), str(codec_object),
                        "-llz4", "-lcrypto", "-o", str(binary),
                    ]
                    linked = subprocess.run(
                        link_command, capture_output=True, text=True,
                        check=False, timeout=120)
                    self.assertEqual(
                        linked.returncode, 0,
                        f"{compiler} {fault} link failed:\n"
                        f"{linked.stderr[-6000:]}")
                    environment = dict(os.environ)
                    environment.update(
                        ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
                    ran = subprocess.run([str(binary)], capture_output=True,
                                         text=True, env=environment,
                                         check=False, timeout=30)
                    self.assertEqual(
                        ran.returncode, 0,
                        f"{compiler} {fault} first runtime failure:\n"
                        f"{ran.stderr[-6000:]}")
                    expected = (
                        "ROUND023_CROSS_ABI_SOURCE_ONLY_PASS" if
                        fault == "original" else
                        "ROUND023_WRONG_PRODUCER_CRC_REJECTED_SOURCE_ONLY")
                    self.assertIn(expected, ran.stdout)
                    self.assertNotIn("LOADED_HANDOFF_PASS", ran.stdout)

    def test_round023_gcc_asan_ubsan_frozen_interoperability(self) -> None:
        self._run_compiler("gcc")

    def test_round023_clang_asan_ubsan_frozen_interoperability(self) -> None:
        self._run_compiler("clang")


if __name__ == "__main__":
    unittest.main()
