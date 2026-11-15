#!/usr/bin/env python3
"""Fail-closed, read-only proof that pinned Linux Kbuild manifests match output bytes.

This verifies an isolated build tree, not a trusted kernel producer or loaded ABI.
All filesystem reads use no-follow file descriptors; validation is not an
atomic snapshot if an untrusted writer concurrently mutates the build tree.
"""

import argparse
from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import unittest

LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
GCC_CLASS = "pinned-linux-targeted-objects-and-linked-external-module"
LLVM_CLASS = "LLVM_STOCK_SOURCE_OBJECT_KBUILD"
COMMON_OBJECTS = ("mm/page_io.o", "block/bio.o")
GCC_STAGES = ("defconfig", "scripts_config", "olddefconfig", "prepare",
              "compile_objects", "modules_prepare", "kernel_export_build",
              "kernel_export_modules", "swapz_module_kbuild")
LLVM_STAGES = GCC_STAGES[:5]
HASH_PATTERN = re.compile(r"[a-f0-9]{64}\Z")
SHA_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
UINT_PATTERN = re.compile(r"0|[1-9][0-9]*\Z")
SCALAR_FIELDS = set("""source_repository source_sha source_modified swapz_sha
 requested_zswap result evidence_class phase_a_qualified producer_authenticated
 upstream_patched compiler linker clang_package lld_package llvm_package
 llvm_make_setting kbuild_jobs kbuild_warning_level kbuild_recorded_compiler
 effective_swap effective_zswap effective_modules effective_blk_dev_dm
 effective_crypto_lz4 effective_lz4_compress effective_lz4_decompress
 effective_cc_is_clang config_sha256 config_verification_exit_code
 module_symvers_sha256 module_linked module_bytes module_sha256
 module_warning_count error_category""".split())
for stage in GCC_STAGES:
    SCALAR_FIELDS.update((f"{stage}_command", f"{stage}_exit_code",
                          f"{stage}_warning_count"))
REPEATED_FIELDS = {"compiled_object", "object", "object_sha256"}
MAX_FILE_BYTES = {"manifest": 32768, "config": 2 * 1024 * 1024,
                  "object": 512 * 1024 * 1024, "symvers": 64 * 1024 * 1024,
                  "module": 512 * 1024 * 1024}


class IntegrityError(ValueError):
    """Bounded failure category; never report untrusted manifest values."""


def require(condition: bool, field: str) -> None:
    if not condition:
        raise IntegrityError("invalid integrity: " + field)


def canonical_uint(value: str | None, field: str, positive: bool = False) -> int:
    require(value is not None and len(value) <= 20 and
            UINT_PATTERN.fullmatch(value) is not None, field)
    number = int(value)
    require(number <= 0xffffffffffffffff and (not positive or number > 0), field)
    return number


def expected_hash(value: str | None, field: str) -> str:
    require(value is not None and HASH_PATTERN.fullmatch(value) is not None, field)
    return value


def checked_path(path: Path) -> tuple[str, ...]:
    """Reject noncanonical/escaping names before no-follow directory traversal."""
    raw = os.fspath(path)
    require(path.is_absolute() and "//" not in raw and
            all(part not in (".", "..") for part in raw.split("/")[1:]) and
            not raw.endswith("/"), "path")
    parts = tuple(part for part in raw.split("/") if part)
    require(bool(parts), "path")
    return parts


def regular_bytes(path: Path, kind: str, retain: bool = False,
                  prefix_length: int = 0) -> tuple[int, str, bytes]:
    """Stream a bounded file through O_NOFOLLOW, rejecting symlink ancestors.

    Caller owns the build outputs. A concurrently malicious writer is out of
    scope; fstat before/after detects ordinary replacement/size/write races.
    """
    parts = checked_path(path)
    with ExitStack() as stack:
        directory_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        stack.callback(os.close, directory_fd)
        for component in parts[:-1]:
            directory_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY |
                                   os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory_fd)
            stack.callback(os.close, directory_fd)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW |
                             os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory_fd)
        file = stack.enter_context(os.fdopen(descriptor, "rb"))
        before = os.fstat(file.fileno())
        require(stat.S_ISREG(before.st_mode) and
                0 < before.st_size <= MAX_FILE_BYTES[kind], kind + "_file")
        sha256 = hashlib.sha256()
        content = bytearray() if retain or prefix_length else None
        count = 0
        while True:
            chunk = file.read(min(65536, MAX_FILE_BYTES[kind] + 1 - count))
            if not chunk:
                break
            count += len(chunk)
            require(count <= MAX_FILE_BYTES[kind], kind + "_bound")
            sha256.update(chunk)
            if content is not None:
                content.extend(chunk if retain else chunk[:max(0, prefix_length - len(content))])
        after = os.fstat(file.fileno())
        identity = lambda record: (record.st_dev, record.st_ino, record.st_size,
                                    record.st_mtime_ns, record.st_ctime_ns)
        require(count == before.st_size and identity(before) == identity(after),
                kind + "_changed")
        return count, sha256.hexdigest(), bytes(content) if content is not None else b""


def read_checked(path: Path, kind: str, retain: bool = False,
                 prefix_length: int = 0) -> tuple[int, str, bytes]:
    try:
        return regular_bytes(path, kind, retain, prefix_length)
    except (OSError, ValueError) as error:
        if isinstance(error, IntegrityError):
            raise
        raise IntegrityError("invalid integrity: " + kind + "_unavailable") from error


def manifest_fields(data: bytes) -> tuple[dict[str, str], list[str], list[tuple[str, str]]]:
    require(0 < len(data) <= MAX_FILE_BYTES["manifest"] and
            data.endswith(b"\n") and b"\r" not in data, "manifest_boundary")
    try:
        text = data.decode("ascii", errors="strict")
    except UnicodeDecodeError as error:
        raise IntegrityError("invalid integrity: manifest_encoding") from error
    lines = text.splitlines()
    require(len(lines) <= 160, "manifest_lines")
    fields: dict[str, str] = {}
    compiled: list[str] = []
    objects: list[tuple[str, str]] = []
    pending: str | None = None
    for line in lines:
        require(len(line) <= 4096 and "=" in line, "manifest_line")
        key, value = line.split("=", 1)
        require(KEY_PATTERN.fullmatch(key) is not None and
                all(32 <= ord(character) <= 126 for character in value),
                "manifest_grammar")
        require(key in SCALAR_FIELDS or key in REPEATED_FIELDS, "manifest_key")
        if key == "compiled_object":
            compiled.append(value)
        elif key == "object":
            require(pending is None, "object_pair")
            pending = value
        elif key == "object_sha256":
            require(pending is not None, "object_pair")
            objects.append((pending, value))
            pending = None
        else:
            require(key not in fields, "duplicate_" + key)
            fields[key] = value
    require(pending is None, "object_pair")
    return fields, compiled, objects


def check_config(build_dir: Path, fields: dict[str, str], profile: str,
                 mode: str) -> None:
    _, actual_digest, content = read_checked(build_dir / ".config", "config", True)
    require(actual_digest == expected_hash(fields.get("config_sha256"),
                                           "config_sha256"), "config_digest")
    try:
        lines = content.decode("utf-8", errors="strict").splitlines()
    except UnicodeDecodeError as error:
        raise IntegrityError("invalid integrity: config_encoding") from error
    for option, expected in (("SWAP", "CONFIG_SWAP=y"),
                             ("ZSWAP", "CONFIG_ZSWAP=y" if profile == "y" else
                              "# CONFIG_ZSWAP is not set")):
        matches = [line for line in lines if line.startswith("CONFIG_" + option + "=")
                   or line == "# CONFIG_" + option + " is not set"]
        require(matches == [expected], "config_" + option.lower())
    compiler_config = [line for line in lines if
                       line.startswith("CONFIG_CC_IS_CLANG=") or
                       line == "# CONFIG_CC_IS_CLANG is not set"]
    if mode == "llvm":
        require(compiler_config == ["CONFIG_CC_IS_CLANG=y"], "config_clang")
    else:
        require("CONFIG_CC_IS_CLANG=y" not in compiler_config,
                "config_gcc")
        for option in ("MODULES", "BLK_DEV_DM", "CRYPTO_LZ4",
                       "LZ4_COMPRESS", "LZ4_DECOMPRESS"):
            require(lines.count("CONFIG_" + option + "=y") == 1,
                    "config_" + option.lower())


def verify(manifest: Path, mode: str, profile: str, source_sha: str,
           build_dir: Path, swapz_sha: str | None = None,
           module_dir: Path | None = None) -> str:
    """Validate actual file bytes and a pre-PASS manifest; return evidence class."""
    require(mode in ("gcc", "llvm") and profile in ("y", "n"), "arguments")
    require(SHA_PATTERN.fullmatch(source_sha) is not None, "expected_source_sha")
    require((mode == "gcc") == (module_dir is not None and swapz_sha is not None),
            "module_arguments")
    if mode == "gcc":
        require(swapz_sha is not None and SHA_PATTERN.fullmatch(swapz_sha) is not None,
                "expected_swapz_sha")
    _, _, data = read_checked(manifest, "manifest", True)
    fields, compiled, objects = manifest_fields(data)
    require("result" not in fields, "premature_result")
    for name, expected in (("source_repository", "torvalds/linux"),
                           ("source_sha", source_sha),
                           ("requested_zswap", profile),
                           ("effective_swap", "y"),
                           ("effective_zswap", profile),
                           ("source_modified", "no"),
                           ("phase_a_qualified", "no"),
                           ("kbuild_warning_level", "1")):
        require(fields.get(name) == expected, name)
    require(fields.get("producer_authenticated") in (None, "no") and
            fields.get("upstream_patched") in (None, "no"), "producer_claim")
    require(fields.get("error_category") in (None, "none"), "error_category")
    require(1 <= canonical_uint(fields.get("kbuild_jobs"), "kbuild_jobs") <= 4,
            "kbuild_jobs")
    require(bool(fields.get("kbuild_recorded_compiler")), "compiler_identity")
    stages = GCC_STAGES if mode == "gcc" else LLVM_STAGES
    for stage in stages:
        require(bool(fields.get(stage + "_command")) and
                fields.get(stage + "_exit_code") == "0", "stage_" + stage)
        if mode == "llvm":
            require(fields.get(stage + "_warning_count") == "0",
                    "warnings_" + stage)
    require(fields.get("evidence_class") ==
            (GCC_CLASS if mode == "gcc" else LLVM_CLASS), "evidence_class")
    expected_objects = COMMON_OBJECTS + (("mm/zswap.o",) if profile == "y" else ())
    check_config(build_dir, fields, profile, mode)
    if mode == "gcc":
        require(not objects and sorted(compiled) == sorted(expected_objects),
                "compiled_object")
        require(fields.get("swapz_sha") == swapz_sha, "swapz_sha")
        require("gcc" in fields.get("compiler", "").lower() and
                "gcc" in fields["kbuild_recorded_compiler"].lower(),
                "gcc_compiler")
        for option in ("effective_modules", "effective_blk_dev_dm",
                       "effective_crypto_lz4", "effective_lz4_compress",
                       "effective_lz4_decompress"):
            require(fields.get(option) == "y", option)
        require(fields.get("module_linked") == "yes" and
                fields.get("config_verification_exit_code") == "0" and
                canonical_uint(fields.get("module_warning_count"),
                               "module_warning_count") == 0, "gcc_module_claim")
        # The module build is not proof without a completed in-tree modpost.
        symvers_size, symvers_hash, _ = read_checked(build_dir / "Module.symvers",
                                                     "symvers")
        require(symvers_size > 0 and symvers_hash == expected_hash(
            fields.get("module_symvers_sha256"), "module_symvers_sha256"),
            "module_symvers_digest")
        module_size, module_hash, module_header = read_checked(
            module_dir / "dm-swapz.ko", "module", prefix_length=64)
        require(module_size == canonical_uint(fields.get("module_bytes"),
                                              "module_bytes", True), "module_bytes")
        require(module_hash == expected_hash(fields.get("module_sha256"),
                                            "module_sha256"), "module_digest")
        # A digest-matching arbitrary blob is not a linked kernel ELF module.
        # This checks only minimal ELF64 x86-64 relocatable structure; modpost
        # and authenticated producer/ABI qualification are separate gates.
        require(len(module_header) == 64 and module_header[:4] == b"\x7fELF" and
                module_header[4:7] == b"\x02\x01\x01" and
                int.from_bytes(module_header[16:18], "little") == 1 and
                int.from_bytes(module_header[18:20], "little") == 62,
                "module_elf_header")
        section_offset = int.from_bytes(module_header[40:48], "little")
        section_entry_size = int.from_bytes(module_header[58:60], "little")
        section_count = int.from_bytes(module_header[60:62], "little")
        string_table_index = int.from_bytes(module_header[62:64], "little")
        require(section_entry_size == 64 and section_count >= 2 and
                0 < string_table_index < section_count and
                64 <= section_offset <= module_size and
                section_offset + section_count * section_entry_size <= module_size,
                "module_elf_sections")
    else:
        require(not compiled and not any(field.startswith("module_") or
                                         field == "swapz_sha" for field in fields),
                "llvm_not_linked")
        require(fields.get("effective_cc_is_clang") == "y" and
                fields.get("llvm_make_setting") == "LLVM=-18" and
                "clang" in fields["kbuild_recorded_compiler"].lower(),
                "llvm_compiler")
        require(all(fields.get(key) for key in ("compiler", "linker",
                    "clang_package", "lld_package", "llvm_package")) and
                "clang" in fields["compiler"].lower() and
                "lld" in fields["linker"].lower(), "llvm_toolchain")
        require(sorted(name for name, _ in objects) == sorted(expected_objects),
                "llvm_object_set")
        for name, digest in objects:
            require(digest == expected_hash(digest, "object_sha256"),
                    "object_sha256")
            _, actual_digest, _ = read_checked(build_dir / name, "object")
            require(actual_digest == digest, "object_digest")
    if mode == "gcc":
        for name in expected_objects:
            read_checked(build_dir / name, "object")
    if profile == "n":
        # lexists also catches dangling links, empty files and special files.
        require(not os.path.lexists(build_dir / "mm/zswap.o"), "disabled_zswap")
    return fields["evidence_class"]


class ArtifactIntegrityTests(unittest.TestCase):
    """Actual disposable on-disk bytes, never a simulated kernel build."""

    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory(prefix="swapz-artifact-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.build = self.root / "build"
        self.module = self.root / "staged"
        self.build.mkdir()
        self.module.mkdir()
        self.manifest = self.root / "enabled.txt"
        self.swapz_sha = "a" * 40
        self.profile = "y"
        self.mode = "gcc"
        self.write_fixture()

    @staticmethod
    def digest(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def write_fixture(self) -> None:
        profile, mode = self.profile, self.mode
        required = COMMON_OBJECTS + (("mm/zswap.o",) if profile == "y" else ())
        config_lines = ["CONFIG_SWAP=y", "CONFIG_ZSWAP=y" if profile == "y" else
                        "# CONFIG_ZSWAP is not set"]
        if mode == "llvm":
            config_lines.append("CONFIG_CC_IS_CLANG=y")
        else:
            config_lines.extend("CONFIG_" + option + "=y" for option in
                                ("MODULES", "BLK_DEV_DM", "CRYPTO_LZ4",
                                 "LZ4_COMPRESS", "LZ4_DECOMPRESS"))
        config = ("\n".join(config_lines) + "\n").encode()
        (self.build / ".config").write_bytes(config)
        records = ["source_repository=torvalds/linux", "source_sha=" + LINUX_SHA,
                   "requested_zswap=" + profile, "effective_swap=y",
                   "effective_zswap=" + profile, "source_modified=no",
                   "phase_a_qualified=no", "kbuild_jobs=4", "kbuild_warning_level=1",
                   "config_sha256=" + self.digest(config), "evidence_class=" +
                   (LLVM_CLASS if mode == "llvm" else GCC_CLASS)]
        for name in required:
            output = self.build / name
            output.parent.mkdir(parents=True, exist_ok=True)
            content = (name + ":" + profile).encode()
            output.write_bytes(content)
            if mode == "llvm":
                records.extend(("object=" + name,
                                "object_sha256=" + self.digest(content)))
            else:
                records.append("compiled_object=" + name)
        stages = LLVM_STAGES if mode == "llvm" else GCC_STAGES
        for stage in stages:
            records.extend((stage + "_command=make " + stage,
                            stage + "_exit_code=0"))
            if mode == "llvm":
                records.append(stage + "_warning_count=0")
        if mode == "llvm":
            records.extend(("compiler=clang version 18", "linker=LLD 18",
                            "clang_package=18", "lld_package=18", "llvm_package=18",
                            "llvm_make_setting=LLVM=-18", "effective_cc_is_clang=y",
                            "kbuild_recorded_compiler=clang version 18"))
        else:
            symvers = b"0x01\tlinux_symbol\tvmlinux\tEXPORT_SYMBOL\n"
            # Minimal ELF64 x86-64 ET_REL header with bounded section table.
            header = bytearray(64)
            header[:7] = b"\x7fELF\x02\x01\x01"
            header[16:18] = (1).to_bytes(2, "little")
            header[18:20] = (62).to_bytes(2, "little")
            header[40:48] = (64).to_bytes(8, "little")
            header[58:60] = (64).to_bytes(2, "little")
            header[60:62] = (2).to_bytes(2, "little")
            header[62:64] = (1).to_bytes(2, "little")
            module_bytes = bytes(header) + bytes(128)
            (self.build / "Module.symvers").write_bytes(symvers)
            (self.module / "dm-swapz.ko").write_bytes(module_bytes)
            records.extend(("swapz_sha=" + self.swapz_sha, "compiler=gcc 13",
                            "kbuild_recorded_compiler=gcc 13", "module_linked=yes",
                            "module_bytes=" + str(len(module_bytes)),
                            "module_sha256=" + self.digest(module_bytes),
                            "module_symvers_sha256=" + self.digest(symvers),
                            "module_warning_count=0", "config_verification_exit_code=0"))
            records.extend("effective_" + option + "=y" for option in
                           ("modules", "blk_dev_dm", "crypto_lz4", "lz4_compress",
                            "lz4_decompress"))
        self.manifest.write_text("\n".join(records) + "\n", encoding="ascii")

    def check(self) -> str:
        return verify(self.manifest, self.mode, self.profile, LINUX_SHA,
                      self.build, self.swapz_sha if self.mode == "gcc" else None,
                      self.module if self.mode == "gcc" else None)

    def update(self, key: str, value: str | None) -> None:
        lines = self.manifest.read_text(encoding="ascii").splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(key + "="))
        if value is None:
            del lines[index]
        else:
            lines[index] = key + "=" + value
        self.manifest.write_text("\n".join(lines) + "\n", encoding="ascii")

    def test_real_byte_positive_profiles(self) -> None:
        for mode in ("gcc", "llvm"):
            for profile in ("y", "n"):
                with self.subTest(mode=mode, profile=profile):
                    self.mode, self.profile = mode, profile
                    for item in self.build.glob("mm/*.o"):
                        item.unlink()
                    self.write_fixture()
                    self.assertEqual(self.check(), GCC_CLASS if mode == "gcc" else LLVM_CLASS)

    def test_refuse_forged_digest_and_altered_real_object(self) -> None:
        self.update("config_sha256", "0" * 64)
        with self.assertRaisesRegex(IntegrityError, "config_digest"):
            self.check()
        self.write_fixture()
        (self.build / "mm/page_io.o").write_bytes(b"changed object")
        self.mode = "llvm"
        self.write_fixture()
        (self.build / "mm/page_io.o").write_bytes(b"changed object")
        with self.assertRaisesRegex(IntegrityError, "object_digest"):
            self.check()

    def test_refuse_module_size_and_symvers(self) -> None:
        (self.module / "dm-swapz.ko").write_bytes(b"")
        with self.assertRaises(IntegrityError):
            self.check()
        self.write_fixture()
        (self.build / "Module.symvers").unlink()
        with self.assertRaises(IntegrityError):
            self.check()
        self.write_fixture()
        (self.build / "Module.symvers").write_bytes(b"forged export")
        with self.assertRaisesRegex(IntegrityError, "module_symvers_digest"):
            self.check()

    def test_refuse_fabricated_linked_module(self) -> None:
        forged_bytes = b"arbitrary bytes presented as a linked module"
        (self.module / "dm-swapz.ko").write_bytes(forged_bytes)
        self.update("module_bytes", str(len(forged_bytes)))
        self.update("module_sha256", self.digest(forged_bytes))
        with self.assertRaisesRegex(IntegrityError, "module_elf_header"):
            self.check()

    def test_refuse_symlinks_and_nonregular(self) -> None:
        object_path = self.build / "mm/page_io.o"
        object_path.unlink()
        object_path.symlink_to(self.root / "outside")
        with self.assertRaises(IntegrityError):
            self.check()
        object_path.unlink()
        self.write_fixture()
        (self.module / "dm-swapz.ko").unlink()
        (self.module / "dm-swapz.ko").symlink_to(self.build / ".config")
        with self.assertRaises(IntegrityError):
            self.check()
        (self.module / "dm-swapz.ko").unlink()
        self.write_fixture()
        (self.build / "Module.symvers").unlink()
        (self.build / "Module.symvers").mkdir()
        with self.assertRaises(IntegrityError):
            self.check()

    def test_refuse_stale_profile_cross_profile_objects(self) -> None:
        self.profile = "n"
        self.write_fixture()
        with self.assertRaisesRegex(IntegrityError, "disabled_zswap"):
            self.check()
        (self.build / "mm/zswap.o").unlink()
        self.assertEqual(self.check(), GCC_CLASS)
        (self.build / "mm/zswap.o").symlink_to(self.root / "unavailable")
        with self.assertRaisesRegex(IntegrityError, "disabled_zswap"):
            self.check()
        (self.build / "mm/zswap.o").unlink()
        self.update("requested_zswap", "y")
        with self.assertRaisesRegex(IntegrityError, "requested_zswap"):
            self.check()

    def test_refuse_bad_config_and_identity(self) -> None:
        self.update("source_sha", "0" * 40)
        with self.assertRaisesRegex(IntegrityError, "source_sha"):
            self.check()
        self.write_fixture()
        (self.build / ".config").write_bytes(b"CONFIG_SWAP=n\nCONFIG_ZSWAP=y\n")
        with self.assertRaises(IntegrityError):
            self.check()

    def test_refuse_sizes_and_truncated_manifest(self) -> None:
        for value in ("00", "-1", "+12", "00031", "18446744073709551616"):
            with self.subTest(value=value):
                self.update("module_bytes", value)
                with self.assertRaises(IntegrityError):
                    self.check()
                self.write_fixture()
        self.manifest.write_bytes(self.manifest.read_bytes()[:-1])
        with self.assertRaisesRegex(IntegrityError, "manifest_boundary"):
            self.check()

    def test_refuse_false_success_or_modpost(self) -> None:
        with self.manifest.open("a", encoding="ascii") as output:
            output.write("result=PASS\n")
        with self.assertRaisesRegex(IntegrityError, "premature_result"):
            self.check()
        self.write_fixture()
        self.update("kernel_export_modules_exit_code", "1")
        with self.assertRaisesRegex(IntegrityError, "stage_kernel_export_modules"):
            self.check()

    def test_refuse_duplicates_and_llvm_module_claim(self) -> None:
        with self.manifest.open("a", encoding="ascii") as output:
            output.write("source_sha=" + LINUX_SHA + "\n")
        with self.assertRaisesRegex(IntegrityError, "duplicate_source_sha"):
            self.check()
        self.mode = "llvm"
        self.write_fixture()
        with self.manifest.open("a", encoding="ascii") as output:
            output.write("module_linked=yes\n")
        with self.assertRaisesRegex(IntegrityError, "llvm_not_linked"):
            self.check()
        self.write_fixture()
        with self.manifest.open("a", encoding="ascii") as output:
            output.write("object=mm/page_io.o\nobject_sha256=" + "0" * 64 + "\n")
        with self.assertRaisesRegex(IntegrityError, "llvm_object_set"):
            self.check()

    def test_refuse_traversal_and_source_mismatch(self) -> None:
        with self.assertRaisesRegex(IntegrityError, "path"):
            verify(self.root / ".." / "enabled.txt", "gcc", "y", LINUX_SHA,
                   self.build, self.swapz_sha, self.module)
        with self.assertRaisesRegex(IntegrityError, "swapz_sha"):
            verify(self.manifest, "gcc", "y", LINUX_SHA, self.build,
                   "b" * 40, self.module)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--mode", choices=("gcc", "llvm"))
    parser.add_argument("--profile", choices=("y", "n"))
    parser.add_argument("--source-sha")
    parser.add_argument("--swapz-sha")
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--module-dir", type=Path)
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(ArtifactIntegrityTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if any(value is None for value in (args.manifest, args.mode, args.profile,
                                       args.source_sha, args.build_dir)):
        parser.error("--manifest, --mode, --profile, --source-sha and --build-dir required")
    try:
        evidence_class = verify(args.manifest, args.mode, args.profile,
                                args.source_sha, args.build_dir,
                                args.swapz_sha, args.module_dir)
    except IntegrityError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("PASS: validated real local bytes, class=" + evidence_class)
    return 0


if __name__ == "__main__":
    sys.exit(main())
