#!/usr/bin/env python3
"""Verify a real paired patched-Linux / swapz Kbuild output, not runtime IO.

Uses only the Python standard library. Tests create explicitly synthetic files;
those passes are never substitute evidence for a hosted kernel/module link.
No writes are made outside --self-test's isolated temporary fixtures.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from typing import Callable

LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
EVIDENCE_CLASS = "HOSTED_PATCHED_LINUX_MATCHED_SWAPZ_MODULE_KBUILD"
PATCHED_PATHS = (
    "block/bio.c", "include/linux/bio.h", "include/linux/blk_types.h",
    "include/linux/swap_ops.h", "mm/page_io.c", "mm/zswap.c",
)
BIO_ORIGIN_MACRO = b"#define BIO_HAS_ZSWAP_STORED_WRITEBACK_ORIGIN 1\n"
MODULE_ORIGIN_MARKER = b" origin_carrier_compiled=1"
MODULE_STOCK_MARKER = b" origin_carrier_compiled=0"
STAGES = (
    "defconfig", "scripts_config", "olddefconfig", "prepare", "compile_objects",
    "modules_prepare", "kernel_export_build", "kernel_export_modules",
    "swapz_module_kbuild",
)
RE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RE_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
RE_UINT = re.compile(r"(?:0|[1-9][0-9]*)\Z")
RE_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
LIMITS = {"manifest": 32768, "source_manifest": 65536, "source": 16 * 1024 * 1024,
          "config": 2 * 1024 * 1024, "object": 512 * 1024 * 1024,
          "symvers": 64 * 1024 * 1024, "module": 512 * 1024 * 1024}


class VerificationError(ValueError):
    """Fail-only bounded error category, never a private path or content."""


def require(condition: bool, category: str) -> None:
    if not condition:
        raise VerificationError("paired-build-invalid: " + category)


def canonical_uint(value: str | None, category: str, positive: bool = False) -> int:
    require(value is not None and len(value) <= 20 and RE_UINT.fullmatch(value) is not None,
            category)
    number = int(value)
    require(number <= 0xffffffffffffffff and (not positive or number > 0), category)
    return number


def sha256_field(value: str | None, category: str) -> str:
    require(value is not None and RE_SHA256.fullmatch(value) is not None, category)
    return value


def read_regular(path: Path, category: str, *, retain: bool = False,
                 markers: tuple[bytes, ...] = (),
                 prefix_length: int = 0) -> tuple[int, str, bytes, tuple[bool, ...]]:
    """Bounded streamed SHA256 with no-follow for every directory component.

    The checkout/build tree is owned by the disposable runner. A malicious
    concurrent filesystem writer is out of scope; pre/post fstat detects ordinary
    in-place writes and replacement races, but is not a global atomic snapshot.
    """
    raw_path = os.fspath(path)
    require(path.is_absolute() and not raw_path.endswith("/") and "//" not in raw_path and
            all(part not in ("", ".", "..") for part in raw_path.split("/")[1:]),
            category + "_path")
    components = raw_path.split("/")[1:]
    try:
        with ExitStack() as stack:
            directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            stack.callback(os.close, directory_fd)
            for component in components[:-1]:
                directory_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY |
                                       os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
                stack.callback(os.close, directory_fd)
            file_descriptor = os.open(components[-1], os.O_RDONLY | os.O_NOFOLLOW |
                                      os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory_fd)
            with os.fdopen(file_descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode) and
                        0 < before.st_size <= LIMITS[category], category + "_file")
                digest = hashlib.sha256()
                saved = bytearray() if retain or prefix_length else None
                seen = [False] * len(markers)
                overlap = b""
                count = 0
                longest = max(map(len, markers), default=0)
                while chunk := stream.read(65536):
                    count += len(chunk)
                    require(count <= LIMITS[category], category + "_limit")
                    digest.update(chunk)
                    if saved is not None:
                        saved.extend(chunk if retain else chunk[:max(0, prefix_length - len(saved))])
                    if markers:
                        window = overlap + chunk
                        for index, marker in enumerate(markers):
                            seen[index] = seen[index] or marker in window
                        overlap = window[-(longest - 1):] if longest > 1 else b""
                after = os.fstat(stream.fileno())
                identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                          value.st_mtime_ns, value.st_ctime_ns)
                require(count == before.st_size and identity(before) == identity(after),
                        category + "_changed")
                return count, digest.hexdigest(), bytes(saved or b""), tuple(seen)
    except (OSError, UnicodeError) as error:
        raise VerificationError("paired-build-invalid: " + category + "_unavailable") from error


def read_manifest(path: Path) -> tuple[dict[str, str], list[tuple[str, str]]]:
    _, _, data, _ = read_regular(path, "manifest", retain=True)
    require(data.endswith(b"\n") and b"\r" not in data, "manifest_boundary")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as error:
        raise VerificationError("paired-build-invalid: manifest_encoding") from error
    lines = text.splitlines()
    require(len(lines) <= 160, "manifest_lines")
    fields: dict[str, str] = {}
    objects: list[tuple[str, str]] = []
    for line in lines:
        require(len(line) <= 4096 and "=" in line, "manifest_line")
        name, value = line.split("=", 1)
        require(RE_KEY.fullmatch(name) is not None and
                all(32 <= ord(character) <= 126 for character in value), "manifest_grammar")
        if name == "object":
            match = re.fullmatch(r"(mm/page_io\.o|block/bio\.o|mm/zswap\.o) sha256=([a-f0-9]{64})", value)
            require(match is not None, "object_pair")
            objects.append((match.group(1), match.group(2)))
        else:
            require(name not in fields, "manifest_duplicate")
            fields[name] = value
    return fields, objects


def load_source_manifest(path: Path) -> list[dict[str, object]]:
    _, _, data, _ = read_regular(path, "source_manifest", retain=True)

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in pairs:
            require(name not in result, "source_manifest_duplicate")
            result[name] = value
        return result

    try:
        record = json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as error:
        if isinstance(error, VerificationError):
            raise
        raise VerificationError("paired-build-invalid: source_manifest_json") from error
    require(isinstance(record, dict) and
            record.get("schema") == "swapz-pinned-linux-zswap-origin-v1" and
            record.get("source_sha") == LINUX_SHA and
            record.get("source_repository") == "torvalds/linux" and
            record.get("status") == "STAGED_SOURCE_ONLY" and
            record.get("compiled") is False and
            record.get("phase_a_qualified") is False, "source_manifest_identity")
    entries = record.get("changed_paths")
    require(isinstance(entries, list) and len(entries) == len(PATCHED_PATHS) and
            all(isinstance(entry, dict) for entry in entries), "source_manifest_paths")
    require(tuple(sorted(entry.get("path") for entry in entries)) == PATCHED_PATHS,
            "source_manifest_paths")
    return entries


def validate_config(path: Path, expected_sha: str, profile: str) -> None:
    _, digest, data, _ = read_regular(path, "config", retain=True)
    require(digest == sha256_field(expected_sha, "config_hash"), "config_digest")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise VerificationError("paired-build-invalid: config_encoding") from error
    settings = {"SWAP": "CONFIG_SWAP=y", "ZSWAP": "CONFIG_ZSWAP=y" if profile == "y"
                else "# CONFIG_ZSWAP is not set", "MODULES": "CONFIG_MODULES=y",
                "BLK_DEV_DM": "CONFIG_BLK_DEV_DM=y", "CRYPTO_LZ4": "CONFIG_CRYPTO_LZ4=y",
                "LZ4_COMPRESS": "CONFIG_LZ4_COMPRESS=y",
                "LZ4_DECOMPRESS": "CONFIG_LZ4_DECOMPRESS=y"}
    for option, expected in settings.items():
        matches = [line for line in lines if line.startswith("CONFIG_" + option + "=")
                   or line == "# CONFIG_" + option + " is not set"]
        require(matches == [expected], "config_" + option.lower())
    require("CONFIG_CC_IS_CLANG=y" not in lines, "config_compiler")


def elf64_relocatable(data: bytes, total_size: int) -> bool:
    if len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01":
        return False
    section_offset = int.from_bytes(data[40:48], "little")
    section_size = int.from_bytes(data[58:60], "little")
    section_count = int.from_bytes(data[60:62], "little")
    string_index = int.from_bytes(data[62:64], "little")
    return (int.from_bytes(data[16:18], "little") == 1 and
            int.from_bytes(data[18:20], "little") == 62 and
            section_size == 64 and section_count >= 2 and
            0 < string_index < section_count and
            64 <= section_offset <= total_size and
            section_offset + section_size * section_count <= total_size)


def actual_modinfo(module: Path, field: str) -> str:
    try:
        process = subprocess.run(("modinfo", "-F", field, os.fspath(module)),
                                 capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError("paired-build-invalid: modinfo_unavailable") from error
    require(process.returncode == 0 and len(process.stdout) <= 4096,
            "modinfo_failed")
    return process.stdout.strip()


def verify(manifest: Path, source_manifest: Path, linux_root: Path,
           stock_bio_header: Path, build_dir: Path, module_stage: Path,
           swapz_root: Path, profile: str, swapz_sha: str,
           modinfo: Callable[[Path, str], str] = actual_modinfo) -> None:
    require(profile in ("y", "n") and RE_SHA1.fullmatch(swapz_sha) is not None,
            "identity_arguments")
    fields, object_claims = read_manifest(manifest)
    require(fields.get("build_state") == "IN_PROGRESS" and "result" not in fields,
            "premature_pass")
    for name, value in (("source_repository", "torvalds/linux"),
                        ("source_sha", LINUX_SHA), ("source_modified", "yes"),
                        ("requested_zswap", profile), ("effective_swap", "y"),
                        ("effective_zswap", profile), ("effective_modules", "y"),
                        ("effective_blk_dev_dm", "y"),
                        ("effective_crypto_lz4", "y"),
                        ("effective_lz4_compress", "y"),
                        ("effective_lz4_decompress", "y"),
                        ("evidence_class", EVIDENCE_CLASS),
                        ("phase_a_qualified", "no"),
                        ("phase_b_enabled", "no"),
                        ("swapz_sha", swapz_sha),
                        ("module_build_source_sha", swapz_sha),
                        ("module_build_source_clean", "1"),
                        ("module_linked", "yes")):
        require(fields.get(name) == value, "manifest_" + name)
    require("gcc" in fields.get("compiler", "").lower() and
            "gcc" in fields.get("kbuild_recorded_compiler", "").lower(),
            "compiler_identity")
    require(canonical_uint(fields.get("kbuild_jobs"), "jobs", True) in (1, 2),
            "jobs")
    require(fields.get("kbuild_warning_level") == "1" and
            fields.get("module_warning_count") == "0", "warnings")
    for stage in STAGES:
        require(fields.get(stage + "_exit_code") == "0" and
                bool(fields.get(stage + "_command")), "stage_" + stage)
    validate_config(build_dir / ".config", fields.get("config_sha256", ""), profile)
    expected_objects = ("mm/page_io.o", "block/bio.o") + (
        ("mm/zswap.o",) if profile == "y" else ())
    require(tuple(sorted(name for name, _ in object_claims)) ==
            tuple(sorted(expected_objects)), "object_set")
    for name, expected_digest in object_claims:
        _, digest, _, _ = read_regular(build_dir / name, "object")
        require(digest == sha256_field(expected_digest, "object_hash"),
                "object_digest")
    if profile == "n":
        require(not os.path.lexists(build_dir / "mm/zswap.o"), "disabled_object")
    require(read_regular(build_dir / "Module.symvers", "symvers")[1] ==
            sha256_field(fields.get("module_symvers_sha256"), "symvers_hash"),
            "symvers_digest")

    source_entries = load_source_manifest(source_manifest)
    for entry in source_entries:
        name = entry["path"]
        length, sha256, data, _ = read_regular(linux_root / name, "source", retain=True)
        sha1 = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        require(entry.get("bytes") == length and entry.get("staged_sha256") == sha256 and
                entry.get("staged_git_sha1") == sha1 and
                RE_SHA1.fullmatch(str(entry.get("original_git_sha1", ""))) is not None and
                entry.get("original_git_sha1") != sha1, "source_postimage")
    _, _, stock, _ = read_regular(stock_bio_header, "source", retain=True)
    _, _, patched, _ = read_regular(linux_root / "include/linux/bio.h", "source",
                                    retain=True)
    require(BIO_ORIGIN_MACRO not in stock and patched.count(BIO_ORIGIN_MACRO) == 1 and
            stock != patched, "patched_header_capability")
    stock_sha1 = hashlib.sha1(f"blob {len(stock)}\0".encode() + stock).hexdigest()
    bio_record = next(item for item in source_entries if item["path"] == "include/linux/bio.h")
    require(bio_record.get("original_git_sha1") == stock_sha1,
            "stock_header_preimage")

    # Staged real consumer sources (including generated build-info identity)
    # must remain byte-identical to the pinned clean repository checkout.
    kernel_source = swapz_root / "src/kernel"
    for name in ("Makefile", "dm-target.c", "codec.c", "authority.c", "engine.c",
                 "predictor.c"):
        require(read_regular(kernel_source / name, "source")[1] ==
                read_regular(module_stage / name, "source")[1],
                "staged_consumer_source")
    build_info = (f'#define SWAPZ_BUILD_SOURCE_SHA "{swapz_sha}"\n'
                  '#define SWAPZ_BUILD_SOURCE_CLEAN 1\n'
                  '#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n').encode("ascii")
    _, build_info_sha, bytes_on_disk, _ = read_regular(
        module_stage / "swapz-build-info.h", "source", retain=True)
    require(bytes_on_disk == build_info and
            build_info_sha == sha256_field(fields.get("build_info_sha256"),
                                           "build_info_hash"), "build_info_source")

    module = module_stage / "dm-swapz.ko"
    module_size, module_sha, module_bytes, markers = read_regular(
        module, "module", prefix_length=64,
        markers=(MODULE_ORIGIN_MARKER, MODULE_STOCK_MARKER))
    require(module_size == canonical_uint(fields.get("module_bytes"),
                                          "module_bytes", True) and
            module_sha == sha256_field(fields.get("module_sha256"), "module_hash"),
            "module_digest")
    require(elf64_relocatable(module_bytes[:64], module_size), "module_elf")
    require(markers == (True, False), "module_origin_reader_compiled")
    require(modinfo(module, "name") in ("dm_swapz", "dm-swapz"), "modinfo_name")
    require(modinfo(module, "swapz_build_source_sha") == swapz_sha and
            modinfo(module, "swapz_build_source_clean") == "1", "modinfo_source")
    kernel_release = fields.get("kernel_release", "")
    require(kernel_release and len(kernel_release) <= 160 and
            modinfo(module, "vermagic").split(" ")[0] == kernel_release,
            "modinfo_vermagic")


def assert_full_workflow_contract(workflow: Path) -> None:
    """Inspect whole existing YAML, extract both Bash steps, reject PASS bypass.

    Parsing YAML syntax is separately done using PyYAML when locally available;
    this stdlib check deliberately tests the committed full workflow, not a
    separately hand-written snippet that could omit a production bypass.
    """
    _, _, data, _ = read_regular(workflow, "source", retain=True)
    text = data.decode("utf-8")
    require(text.startswith('name: "Phase A pinned Linux zswap provenance source prototype"\n')
            and "permissions:\n  contents: read" in text and
            "ref: c339f4010dea8b0d754f84ace70cd1b089878ef8" in text and
            "tests/tools/stage-pinned-linux-zswap-origin.py" in text,
            "workflow_identity")
    require(text.count("result=PASS") == 1 and text.count("result=FAIL") == 1,
            "workflow_unique_result")
    build_step = text.split(
        '      - name: "Build modified Linux and matched source-linked swapz module for both configurations"',
        1)[-1]
    require(build_step != text and '      - name: "Retain source, build and first-failure evidence"'
            in build_step, "workflow_build_step")
    build_step = build_step.split(
        '      - name: "Retain source, build and first-failure evidence"', 1)[0]
    required = ("run_logged compile_objects", "run_logged kernel_export_build",
                "run_logged kernel_export_modules", "run_logged swapz_module_kbuild",
                "current_phase=verify_matched_paired_artifacts",
                "python3 -B swapz/tests/runtime/native/pinned-linux-origin-paired-module-test.py",
                "printf 'result=PASS\\n'")
    locations = [build_step.find(token) for token in required]
    require(all(location >= 0 for location in locations) and locations == sorted(locations),
            "workflow_compile_to_pass_order")
    require("if: always()" in text and "actions/upload-artifact@v4" in text and
            "source-manifest.json" in text and "run_logged kernel_export_modules" in text,
            "workflow_failure_artifacts")
    require("git -C linux show HEAD:include/linux/bio.h" in text and
            "GITHUB_SHA" in text and "SWAPZ_BUILD_SOURCE_CLEAN_STRING" in text,
            "workflow_source_identity")


class PairedModuleTests(unittest.TestCase):
    """No kernel module, device, root, or network required: synthetic bytes."""

    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="paired-module-rootless-")
        self.addCleanup(self.scratch.cleanup)
        root = Path(self.scratch.name)
        self.linux = root / "linux"
        self.build = root / "build"
        self.module = root / "module"
        self.swapz = root / "swapz"
        self.stock = root / "stock-bio.h"
        self.source_manifest = root / "source-manifest.json"
        self.manifest = root / "enabled.txt"
        self.sha = "1" * 40
        self.profile = "y"
        for directory in (self.linux, self.build, self.module,
                          self.swapz / "src/kernel"):
            directory.mkdir(parents=True)
        self.fields: dict[str, str] = {}
        self.make_fixture()

    @staticmethod
    def write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def put(self, name: str, content: bytes, root: Path | None = None) -> None:
        self.write((root or self.build) / name, content)

    @staticmethod
    def fake_elf() -> bytes:
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        header[16:18] = (1).to_bytes(2, "little")
        header[18:20] = (62).to_bytes(2, "little")
        header[40:48] = (64).to_bytes(8, "little")
        header[58:60] = (64).to_bytes(2, "little")
        header[60:62] = (2).to_bytes(2, "little")
        header[62:64] = (1).to_bytes(2, "little")
        return bytes(header) + bytes(128) + MODULE_ORIGIN_MARKER

    def make_fixture(self) -> None:
        self.stock.write_bytes(b"#define STOCK_ONLY 1\n")
        entries = []
        for name in PATCHED_PATHS:
            contents = (BIO_ORIGIN_MACRO if name == "include/linux/bio.h" else b"") + name.encode()
            self.put(name, contents, self.linux)
            before = self.stock.read_bytes() if name == "include/linux/bio.h" else b"old-" + name.encode()
            entries.append({"path": name, "bytes": len(contents),
                            "staged_sha256": self.digest(contents),
                            "staged_git_sha1": hashlib.sha1(
                                f"blob {len(contents)}\0".encode() + contents).hexdigest(),
                            "original_git_sha1": hashlib.sha1(
                                f"blob {len(before)}\0".encode() + before).hexdigest()})
        self.source_manifest.write_text(json.dumps({
            "schema": "swapz-pinned-linux-zswap-origin-v1",
            "source_repository": "torvalds/linux", "source_sha": LINUX_SHA,
            "status": "STAGED_SOURCE_ONLY", "compiled": False,
            "phase_a_qualified": False, "changed_paths": entries}) + "\n")
        for name in ("Makefile", "dm-target.c", "codec.c", "authority.c",
                     "engine.c", "predictor.c"):
            data = b"real-source-file-" + name.encode()
            self.put(name, data, self.swapz / "src/kernel")
            self.put(name, data, self.module)
        info = (f'#define SWAPZ_BUILD_SOURCE_SHA "{self.sha}"\n'
                '#define SWAPZ_BUILD_SOURCE_CLEAN 1\n'
                '#define SWAPZ_BUILD_SOURCE_CLEAN_STRING "1"\n').encode()
        self.put("swapz-build-info.h", info, self.module)
        config = b"".join((
            b"CONFIG_SWAP=y\n", b"CONFIG_ZSWAP=y\n", b"CONFIG_MODULES=y\n",
            b"CONFIG_BLK_DEV_DM=y\n", b"CONFIG_CRYPTO_LZ4=y\n",
            b"CONFIG_LZ4_COMPRESS=y\n", b"CONFIG_LZ4_DECOMPRESS=y\n"))
        self.put(".config", config)
        objects = ["mm/page_io.o", "block/bio.o", "mm/zswap.o"]
        for obj in objects:
            self.put(obj, b"compiled-source-" + obj.encode())
        self.put("Module.symvers", b"exported-symbol\n")
        module_data = self.fake_elf()
        self.put("dm-swapz.ko", module_data, self.module)
        self.fields = {
            "build_state": "IN_PROGRESS", "source_repository": "torvalds/linux",
            "source_sha": LINUX_SHA, "source_modified": "yes",
            "requested_zswap": "y", "effective_swap": "y", "effective_zswap": "y",
            "effective_modules": "y", "effective_blk_dev_dm": "y",
            "effective_crypto_lz4": "y", "effective_lz4_compress": "y",
            "effective_lz4_decompress": "y", "swapz_sha": self.sha,
            "module_build_source_sha": self.sha, "module_build_source_clean": "1",
            "module_linked": "yes", "compiler": "gcc 13", "kbuild_recorded_compiler": "gcc 13",
            "kbuild_jobs": "2", "kbuild_warning_level": "1",
            "module_warning_count": "0", "evidence_class": EVIDENCE_CLASS,
            "phase_a_qualified": "no", "phase_b_enabled": "no",
            "module_bytes": str(len(module_data)), "module_sha256": self.digest(module_data),
            "module_symvers_sha256": self.digest(b"exported-symbol\n"),
            "build_info_sha256": self.digest(info), "config_sha256": self.digest(config),
            "kernel_release": "6.14.0-test",
        }
        for stage in STAGES:
            self.fields[stage + "_command"] = "make " + stage
            self.fields[stage + "_exit_code"] = "0"
        self.save()

    def save(self) -> None:
        lines = [f"{key}={value}" for key, value in self.fields.items()]
        for obj in ("mm/page_io.o", "block/bio.o") + (("mm/zswap.o",)
                 if self.profile == "y" else ()):
            data = (self.build / obj).read_bytes()
            lines.append(f"object={obj} sha256={self.digest(data)}")
        self.manifest.write_text("\n".join(lines) + "\n")

    def check(self, modinfo: Callable[[Path, str], str] | None = None) -> None:
        values = {"name": "dm_swapz", "swapz_build_source_sha": self.sha,
                  "swapz_build_source_clean": "1", "vermagic": "6.14.0-test SMP"}
        verify(self.manifest, self.source_manifest, self.linux, self.stock,
               self.build, self.module, self.swapz, self.profile, self.sha,
               modinfo or (lambda module, key: values[key]))

    def assert_rejects(self, category: str) -> None:
        with self.assertRaisesRegex(VerificationError, category):
            self.check()

    def test_both_profiles_pass_only_synthetic(self) -> None:
        self.check()
        self.profile = "n"
        self.fields["requested_zswap"] = self.fields["effective_zswap"] = "n"
        self.put(".config", (self.build / ".config").read_bytes().replace(
            b"CONFIG_ZSWAP=y\n", b"# CONFIG_ZSWAP is not set\n"))
        self.fields["config_sha256"] = self.digest((self.build / ".config").read_bytes())
        (self.build / "mm/zswap.o").unlink()
        self.save()
        self.check()

    def test_wrong_sha_and_dirty_preimage(self) -> None:
        self.fields["source_sha"] = "f" * 40
        self.save()
        self.assert_rejects("manifest_source_sha")
        self.fields["source_sha"] = LINUX_SHA
        self.save()
        self.stock.write_bytes(b"tampered-stock\n")
        self.assert_rejects("stock_header_preimage")

    def test_missing_or_empty_symvers(self) -> None:
        path = self.build / "Module.symvers"
        path.unlink()
        self.assert_rejects("symvers_unavailable")
        path.touch()
        self.assert_rejects("symvers_file")

    def test_incorrect_profile_and_extra_object(self) -> None:
        self.fields["requested_zswap"] = "n"
        self.save()
        self.assert_rejects("manifest_requested_zswap")
        self.fields["requested_zswap"] = "y"
        self.save()
        self.profile = "n"
        self.assert_rejects("manifest_requested_zswap")

    def test_stock_header_or_missing_capability(self) -> None:
        self.put("include/linux/bio.h", b"stock-only", self.linux)
        self.assert_rejects("source_postimage")

    def test_missing_and_empty_module(self) -> None:
        path = self.module / "dm-swapz.ko"
        path.unlink()
        self.assert_rejects("module_unavailable")
        path.touch()
        self.assert_rejects("module_file")

    def test_tampered_elf_module_identity(self) -> None:
        path = self.module / "dm-swapz.ko"
        content = bytearray(path.read_bytes())
        content[0] = 0
        path.write_bytes(content)
        self.fields["module_sha256"] = self.digest(content)
        self.save()
        self.assert_rejects("module_elf")

    def test_wrong_modinfo_source_sha(self) -> None:
        values = {"name": "dm_swapz", "swapz_build_source_sha": "f" * 40,
                  "swapz_build_source_clean": "1", "vermagic": "6.14.0-test SMP"}
        with self.assertRaisesRegex(VerificationError, "modinfo_source"):
            self.check(lambda module, key: values[key])

    def test_forged_premature_pass_and_truncated(self) -> None:
        self.fields["result"] = "PASS"
        self.save()
        self.assert_rejects("premature_pass")
        del self.fields["result"]
        self.save()
        self.manifest.write_bytes(self.manifest.read_bytes()[:-3])
        self.assert_rejects("manifest_boundary")

    def test_duplicate_and_noncanonical_byte_size(self) -> None:
        self.fields["module_bytes"] = "0001"
        self.save()
        self.assert_rejects("module_bytes")
        self.fields["module_bytes"] = str((self.module / "dm-swapz.ko").stat().st_size)
        self.save()
        with self.manifest.open("a") as stream:
            stream.write("source_sha=" + LINUX_SHA + "\n")
        self.assert_rejects("manifest_duplicate")

    def test_symlink_and_stale_staged_source(self) -> None:
        path = self.module / "dm-swapz.ko"
        path.rename(self.module / "saved")
        path.symlink_to("saved")
        self.assert_rejects("module_unavailable")
        path.unlink()
        (self.module / "saved").rename(path)
        (self.module / "dm-target.c").write_bytes(b"stale-modified-source")
        self.assert_rejects("staged_consumer_source")

    def test_hidden_modpost_failure(self) -> None:
        self.fields["kernel_export_modules_exit_code"] = "1"
        self.save()
        self.assert_rejects("stage_kernel_export_modules")

    def test_origin_carrier_must_be_compiled(self) -> None:
        module_path = self.module / "dm-swapz.ko"
        blob = module_path.read_bytes().replace(MODULE_ORIGIN_MARKER,
                                                 MODULE_STOCK_MARKER)
        module_path.write_bytes(blob)
        self.fields["module_sha256"] = self.digest(blob)
        self.save()
        self.assert_rejects("module_origin_reader_compiled")


class FullWorkflowContractTests(unittest.TestCase):
    workflow_path: Path

    def extract_entire_build_script(self) -> str:
        text = self.workflow_path.read_text()
        start_marker = ('      - name: "Build modified Linux and matched source-linked '
                        'swapz module for both configurations"\n')
        _, start, following = text.partition(start_marker)
        self.assertEqual(start, start_marker)
        section, boundary, _ = following.partition(
            '      - name: "Retain source, build and first-failure evidence"')
        self.assertTrue(boundary)
        self.assertIn('        run: |\n', section)
        _, _, indented = section.partition('        run: |\n')
        lines = indented.splitlines()
        self.assertTrue(lines)
        self.assertTrue(all(not line or line.startswith('          ') for line in lines))
        return "\n".join(line[10:] if line else "" for line in lines) + "\n"

    def test_actual_build_script_preflight_failures(self) -> None:
        # Execute the *whole YAML-embedded Bash* with a fake checkout command.
        # Both negative paths terminate before any make, compiler or device action.
        script = self.extract_entire_build_script()
        for label, bad_sha, expected_phase in (
            ("wrong_linux_sha", True, "initialization"),
            ("dirty_swapz_checkout", False, "verify_swapz_checkout"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory(
                    prefix="full-bash-negative-") as directory:
                root = Path(directory)
                evidence = root / "zswap-origin-evidence"
                evidence.mkdir()
                (evidence / "source-manifest.json").write_text("{}\n")
                (root / "swapz/src/kernel").mkdir(parents=True)
                (root / "swapz/src/kernel/Makefile").write_text("fixture\n")
                (root / "swapz/src/kernel/dm-target.c").write_text("fixture\n")
                tools = root / "stub-bin"
                tools.mkdir()
                git = tools / "git"
                git.write_text(
                    '#!/bin/sh\n'
                    'if [ "$3" = rev-parse ]; then\n'
                    '  if [ "$2" = linux ]; then\n'
                    '    echo ' + ("0" * 40 if bad_sha else LINUX_SHA) + '\n'
                    '  else echo ' + ("1" * 40) + '; fi\n'
                    'elif [ "$3" = status ]; then\n'
                    '  echo " M src/kernel/dm-target.c"\n'
                    'else exit 23; fi\n')
                git.chmod(0o700)
                environment = os.environ.copy()
                environment.update({"RUNNER_TEMP": str(root), "KBUILD_JOBS": "2",
                                    "GITHUB_SHA": "1" * 40,
                                    "PATH": str(tools) + os.pathsep + environment["PATH"]})
                process = subprocess.run(("bash", "-c", script), cwd=root,
                                         env=environment, capture_output=True,
                                         text=True, timeout=10, check=False)
                self.assertEqual(process.returncode, 1, process.stderr)
                status = (evidence / "setup.txt").read_text()
                self.assertIn("result=FAIL\n", status)
                self.assertIn("first_failure_phase=" + expected_phase + "\n", status)
                self.assertNotIn("result=PASS", status)
                self.assertFalse((evidence / "enabled.txt").exists())

    def test_real_full_workflow(self) -> None:
        assert_full_workflow_contract(self.workflow_path)

    def test_guard_rejects_full_workflow_pass_bypass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="workflow-integrity-") as directory:
            text = self.workflow_path.read_text()
            # Move the only PASS ahead of the artifact check: must fail.
            original = "            printf 'result=PASS\\n' >> \"$current_manifest\""
            self.assertEqual(text.count(original), 1)
            forged = text.replace(original, "")
            anchor = "            current_phase=verify_matched_paired_artifacts"
            self.assertEqual(forged.count(anchor), 1)
            forged = forged.replace(anchor, original + "\n" + anchor)
            path = Path(directory) / "full.yml"
            path.write_text(forged)
            with self.assertRaises(VerificationError):
                assert_full_workflow_contract(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--workflow", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--linux-root", type=Path)
    parser.add_argument("--stock-bio-header", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--module-stage", type=Path)
    parser.add_argument("--swapz-root", type=Path)
    parser.add_argument("--profile", choices=("y", "n"))
    parser.add_argument("--swapz-sha")
    args = parser.parse_args()
    if args.self_test:
        FullWorkflowContractTests.workflow_path = (args.workflow or
            Path(__file__).resolve().parents[3] /
            ".github/workflows/phase-a-zswap-origin-prototype.yml")
        suite = unittest.TestSuite((
            unittest.defaultTestLoader.loadTestsFromTestCase(PairedModuleTests),
            unittest.defaultTestLoader.loadTestsFromTestCase(FullWorkflowContractTests)))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if not all((args.manifest, args.source_manifest, args.linux_root,
                args.stock_bio_header, args.build_dir, args.module_stage,
                args.swapz_root, args.profile, args.swapz_sha)):
        parser.error("all paired-build inputs are required")
    try:
        verify(args.manifest, args.source_manifest, args.linux_root,
               args.stock_bio_header, args.build_dir, args.module_stage,
               args.swapz_root, args.profile, args.swapz_sha)
    except (VerificationError, OSError, UnicodeError) as error:
        print(str(error) if isinstance(error, VerificationError)
              else "paired-build-invalid: io", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
