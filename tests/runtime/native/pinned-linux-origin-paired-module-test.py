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
# Exactly six original ordinary sources and one authenticated opt-in source.
ALLOCATOR_PATCHED_PATH = "mm/swapfile.c"
ALLOCATOR_ORIGINAL_BLOB = "254ce86fa923e6b5f1fefda88c39315c4cc00642"
ALLOCATOR_SOURCE_EPOCH_STATUS = "NO_AUTHENTIC_GENERATION_NO_GO"
ALLOCATOR_PATCHED_PATHS = tuple(sorted((*PATCHED_PATHS, ALLOCATOR_PATCHED_PATH)))
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
          "symvers": 64 * 1024 * 1024, "module": 512 * 1024 * 1024,
          "build_log": 16 * 1024 * 1024}

# Exact unchanged upstream Linux Git blobs and W=1 diagnostics from run 43793863015.
# None of these four files is a patched producer or consumer source.
BASELINE_KERNEL_DOC = (
    ("ipc_sem", "ipc/sem.c", 629,
     "This comment starts with '/**', but isn't a kernel-doc comment. Refer to Documentation/doc-guide/kernel-doc.rst",
     1, "5ec41de7e85b2b4ce00def87f8a082b70d5efe49"),
    ("blk_map_op", "block/blk-map.c", 366,
     "Excess function parameter 'op' description in 'bio_copy_kern'",
     2, "81cba3af4e9c1de234dc9a8573a978cf3d942be0"),
    ("blk_dma_state", "block/blk-mq-dma.c", 379,
     "Excess function parameter 'state' description in 'blk_rq_integrity_dma_map_iter_next'",
     2, "88fd9cbc951f44af45c1f7af31571624bbad1263"),
    ("drm_shmem_proto", "drivers/gpu/drm/drm_gem_shmem_helper.c", 174,
     "expecting prototype for __drm_gem_shmem_release_sgt_locked(). Prototype was for __drm_gem_shmem_free_sgt_locked() instead",
     1, "d654a22a30dedac27574d1179a278c93185f03b1"),
)
BASELINE_IPC_CONTINUATION = " * perform_atomic_semop[_slow] - Attempt to perform semaphore"
BASELINE_WARNING_KEYS = (
    "kernel_export_build_baseline_warning_count",
    "kernel_export_build_baseline_warning_categories",
    "kernel_export_build_baseline_warning_sha256",
    "kernel_export_build_baseline_warning_source_sha",
    "kernel_export_build_baseline_warning_profile",
)


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
                        (before.st_size > 0 or category == "build_log") and
                        before.st_size <= LIMITS[category], category + "_file")
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
            match = re.fullmatch(r"(mm/page_io\.o|block/bio\.o|mm/swapfile\.o|mm/zswap\.o) sha256=([a-f0-9]{64})", value)
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
    require(isinstance(entries, list) and
            all(isinstance(entry, dict) and isinstance(entry.get("path"), str)
                for entry in entries), "source_manifest_paths")
    paths = tuple(entry["path"] for entry in entries)
    require(len(paths) == len(set(paths)) and
            paths in (PATCHED_PATHS, ALLOCATOR_PATCHED_PATHS),
            "source_manifest_paths")
    if paths == ALLOCATOR_PATCHED_PATHS:
        require(record.get("round026_allocator_epoch") ==
                ALLOCATOR_SOURCE_EPOCH_STATUS and
                record.get("round026_allocator_probe_compiled") is False and
                record.get("direct_compressed_handoff_enabled") is False,
                "source_manifest_allocator_profile")
        allocator = next(entry for entry in entries
                         if entry["path"] == ALLOCATOR_PATCHED_PATH)
        require(allocator.get("original_git_sha1") == ALLOCATOR_ORIGINAL_BLOB and
                RE_SHA256.fullmatch(str(allocator.get("original_sha256", "")))
                is not None, "source_manifest_allocator_blob")
    else:
        require("round026_allocator_epoch" not in record and
                "round026_allocator_probe_compiled" not in record,
                "source_manifest_allocator_profile")
    # Round028 optional epoch/store evidence is permitted only on the exact
    # original seven-source allocator profile, and never asserts compilation.
    if ("round028_epoch_store_binding" in record or
            "round028_epoch_compiled" in record):
        require(paths == ALLOCATOR_PATCHED_PATHS and
                record.get("round028_epoch_store_binding") ==
                    "CI_ONLY_MM_MINT_RETIRE_STORE_NO_BIO" and
                record.get("round028_epoch_compiled") is False and
                record.get("direct_compressed_handoff_enabled") is False,
                "source_manifest_round028_profile")
    return entries


def baseline_warning_summary(counts: tuple[int, ...]) -> tuple[int, str, str]:
    """Deterministic digest of approved signatures; no runner-private paths."""
    require(len(counts) == len(BASELINE_KERNEL_DOC), "baseline_counts")
    total = sum(counts)
    if total == 0:
        return 0, "none", hashlib.sha256(b"").hexdigest()
    require(counts == tuple(item[4] for item in BASELINE_KERNEL_DOC),
            "baseline_counts")
    categories = ",".join(f"{item[0]}:{count}" for item, count
                          in zip(BASELINE_KERNEL_DOC, counts))
    canonical = "".join(
        f"{item[0]}|{item[1]}:{item[2]}|{item[3]}\n" * count
        for item, count in zip(BASELINE_KERNEL_DOC, counts)
    ).encode("utf-8")
    return total, categories, hashlib.sha256(canonical).hexdigest()


def classify_kernel_doc_warnings(data: bytes, linux_root: Path, source_sha: str,
                                 profile: str, command_exit: int,
                                 original_blobs: dict[str, str]) -> dict[str, str]:
    """Allow exact pinned upstream kernel-doc warnings, never compiler errors."""
    require(source_sha == LINUX_SHA and profile in ("y", "n"),
            "baseline_source_identity")
    require(command_exit == 0 and len(data) <= LIMITS["build_log"],
            "baseline_kernel_export_exit")
    require(linux_root.is_absolute() and not linux_root.is_symlink(),
            "baseline_source_root")
    require(original_blobs == {item[1]: item[5] for item in BASELINE_KERNEL_DOC},
            "baseline_unmodified_blobs")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise VerificationError("paired-build-invalid: baseline_log_encoding") from error
    approved = {
        f"Warning: {linux_root / item[1]}:{item[2]} {item[3]}": index
        for index, item in enumerate(BASELINE_KERNEL_DOC)
    }
    counts = [0] * len(BASELINE_KERNEL_DOC)
    diagnostic = re.compile(
        r"(?i)(?:\bwarning:|\berror:|\bfatal:|\bfailed\b|"
        r"\bundefined reference\b|(?:^|\s)make(?:\[\d+\])?:\s*\*\*\*)"
    )
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("Warning: "):
            require(line in approved, "baseline_unknown_warning")
            position = approved[line]
            counts[position] += 1
            require(counts[position] <= BASELINE_KERNEL_DOC[position][4],
                    "baseline_excess_warning")
            if position == 0:
                index += 1
                require(index < len(lines) and
                        lines[index] == BASELINE_IPC_CONTINUATION,
                        "baseline_ipc_continuation")
        else:
            require(diagnostic.search(line) is None and
                    line != BASELINE_IPC_CONTINUATION,
                    "baseline_unapproved_diagnostic")
        index += 1
    count, categories, digest = baseline_warning_summary(tuple(counts))
    return dict(zip(BASELINE_WARNING_KEYS,
                    (str(count), categories, digest, source_sha, profile)))


def classify_real_kernel_export(log: Path, linux_root: Path, source_manifest: Path,
                                source_sha: str, profile: str, command_exit: int) -> dict[str, str]:
    """Reject any changed originally-unmodified upstream Git blob."""
    load_source_manifest(source_manifest)
    original_blobs: dict[str, str] = {}
    for _, path, _, _, _, expected in BASELINE_KERNEL_DOC:
        _, _, data, _ = read_regular(linux_root / path, "source", retain=True)
        blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        require(blob == expected, "baseline_source_changed")
        original_blobs[path] = blob
    _, _, data, _ = read_regular(log, "build_log", retain=True)
    return classify_kernel_doc_warnings(data, linux_root, source_sha, profile,
                                        command_exit, original_blobs)


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
        warnings = canonical_uint(fields.get(stage + "_warning_count"),
                                  "stage_warning_count")
        require(stage == "kernel_export_build" or warnings == 0,
                "unapproved_stage_warnings")
    baseline_count = canonical_uint(
        fields.get("kernel_export_build_baseline_warning_count"), "baseline_count")
    require(baseline_count == canonical_uint(
        fields.get("kernel_export_build_warning_count"), "baseline_warning_count") and
        fields.get("kernel_export_build_baseline_warning_source_sha") == LINUX_SHA and
        fields.get("kernel_export_build_baseline_warning_profile") == profile,
        "baseline_manifest_identity")
    baseline = baseline_warning_summary(
        tuple(item[4] if baseline_count else 0 for item in BASELINE_KERNEL_DOC))
    require((baseline_count, fields.get("kernel_export_build_baseline_warning_categories"),
             fields.get("kernel_export_build_baseline_warning_sha256")) == baseline,
            "baseline_manifest_evidence")
    validate_config(build_dir / ".config", fields.get("config_sha256", ""), profile)
    source_entries = load_source_manifest(source_manifest)
    expected_objects = ("mm/page_io.o", "block/bio.o") + (
        ("mm/swapfile.o",)
        if len(source_entries) == len(ALLOCATOR_PATCHED_PATHS) else ()) + (
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
    # The pinned baseline warning classifier calls the verifier before Kbuild.
    # Only the second invocation is the real post-link artifact verifier.
    module_verifier_command = (
        "python3 -B swapz/tests/runtime/native/pinned-linux-origin-paired-module-test.py"
    )
    require(build_step.count(module_verifier_command) == 2,
            "workflow_baseline_and_postlink_verifiers")
    locations = [
        build_step.rfind(token) if token == module_verifier_command
        else build_step.find(token)
        for token in required
    ]
    require(all(location >= 0 for location in locations) and locations == sorted(locations),
            "workflow_compile_to_pass_order")
    require("if: always()" in text and "actions/upload-artifact@v4" in text and
            "source-manifest.json" in text and "run_logged kernel_export_modules" in text,
            "workflow_failure_artifacts")
    require("git -C linux show HEAD:include/linux/bio.h" in text and
            "GITHUB_SHA" in text and "SWAPZ_BUILD_SOURCE_CLEAN_STRING" in text,
            "workflow_source_identity")
    # Source/epoch provenance MUST be checked before the kernel exporter.
    # A mismatched seventh source is not an upstream kernel-doc warning.
    staged_step = '      - name: "Modify actual pinned Linux C and H in disposable full checkout"'
    source_preflight = '      - name: "Verify original pinned source manifest before Kbuild"'
    build_step_marker = '      - name: "Build modified Linux and matched source-linked'
    require(text.count(source_preflight) == 1 and
            text.index(staged_step) < text.index(source_preflight) <
            text.index(build_step_marker), "workflow_source_manifest_preflight")
    preflight_source = text.split(source_preflight, 1)[1].split(
        build_step_marker, 1)[0]
    require("--verify-source-manifest-only" in preflight_source and
            '--source-manifest "$evidence_dir/source-manifest.json"'
            in preflight_source and
            "pinned-linux-origin-paired-module-test.py" in preflight_source and
            'exit 3' in preflight_source, "workflow_source_manifest_preflight")
    require(build_step.count("--classify-kernel-doc-warnings") == 1 and
            build_step.count("current_phase=kernel_export_build_warnings") == 1 and
            "if [[ \"$command_name\" == kernel_export_build ]]" in build_step and
            "warning_count" in build_step and
            "command_exit_code" in build_step and
            "--source-manifest \"$evidence_dir/source-manifest.json\"" in build_step,
            "workflow_baseline_fail_closed")
    require(build_step.index("current_phase=kernel_export_build_warnings") <
            build_step.index("for profile in enabled disabled") and
            build_step.index("run_logged kernel_export_build") <
            build_step.index("run_logged kernel_export_modules"),
            "workflow_baseline_warning_gate")
    # The matched Linux job must run on changes to the actual DM reader and
    # must test that reader before any potentially expensive linked build.
    trigger, separator, _ = text.partition("  workflow_dispatch:")
    require(bool(separator) and all(
        f'      - "{path}"' in trigger for path in (
            "src/kernel/dm-target.c",
            "tests/runtime/native/zswap-origin-consumer-source-test.py",
            "tests/runtime/native/zswap-origin-producer-consumer-abi-test.py")),
            "workflow_consumer_change_trigger")
    step_name = ('      - name: "Run actual DM origin and compiled once-only '
                 'foreground-commit source regressions"')
    require(text.count(step_name) == 1, "workflow_consumer_regression_step")
    rootless_step = text.split(step_name, 1)[1].split(
        '      - name: "Run disabled compressed handoff source/ownership negative regression"', 1)[0]
    require("set -euo pipefail" in rootless_step and
            "if python3 -B \"$script\"" in rootless_step and
            "zswap-origin-consumer-source-test.py" in rootless_step and
            "zswap-origin-producer-consumer-abi-test.py" in rootless_step and
            "tail -n 35" in rootless_step and
            text.index(step_name) < text.index(
                '      - name: "Build modified Linux and matched source-linked'),
            "workflow_consumer_regression_fail_closed")
    # This gate is intentionally read-only, and its expected exit 2 is
    # NOT a qualified loaded-kernel result. Removing the refusal test may
    # never silently turn a matched module compilation into Phase A PASS.
    require('      - "tests/runtime/native/zswap-origin-owned-ram-qualification.py"'
            in trigger, "workflow_owned_ram_trigger")
    guard = '      - name: "Run read-only owned-RAM provenance and 4096-byte guard"'
    require(text.count(guard) == 1 and
            text.index(guard) < text.index(
                '      - name: "Build modified Linux and matched source-linked'),
            "workflow_owned_ram_order")
    guard_step = text.split(guard, 1)[1].split(
        '      - name: "Run disabled compressed handoff source/ownership negative regression"',
        1)[0]
    require("zswap-origin-owned-ram-qualification.py" in guard_step and
            "--self-test" in guard_step and "--preflight" in guard_step and
            'if [[ "$first_exit" != 2 ]]' in guard_step and
            'LOADED_STORED_ENTRY=NOT_RUN' in guard_step and
            '4096_READBACK=NOT_RUN' in guard_step and
            'PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED'
            in guard_step, "workflow_owned_ram_refusal")
    # Claimed kernel/module/RAM/owner identities are explicitly untrusted.
    # The new source-controlled candidate check must run before paired Kbuild
    # and must itself refuse any unsafe candidate rather than emit PASS.
    require('      - "tests/runtime/native/zswap-origin-loaded-evidence-contract.py"'
            in trigger, "workflow_loaded_candidate_trigger")
    candidate_stage = (
        '      - name: "Run untrusted loaded-candidate '
        'identity/ownership negative regressions"')
    require(text.count(candidate_stage) == 1 and
            text.index(guard) < text.index(candidate_stage) <
            text.index('      - name: "Build modified Linux and matched source-linked'),
            "workflow_loaded_candidate_order")
    candidate_body = text.split(candidate_stage, 1)[1].split(
        '      - name: "Run disabled compressed handoff source/ownership negative regression"',
        1)[0]
    require("set -euo pipefail" in candidate_body and
            "zswap-origin-loaded-evidence-contract.py" in candidate_body and
            "--self-test" in candidate_body and "--inspect-candidate" in candidate_body and
            '--expected-source-sha "$GITHUB_SHA"' in candidate_body and
            'if [[ "$candidate_exit" != 2 ]]' in candidate_body and
            'ENVIRONMENT_NOT_QUALIFIED first_cause=manifest_file_type_or_size'
            in candidate_body and
            'LOADED_STORED_ENTRY=NOT_RUN' in candidate_body and
            '4096_READBACK=NOT_RUN' in candidate_body and
            'PHASE_A=BLOCKED PHASE_B=DISABLED DIRECT_COMPRESSED=DISABLED'
            in candidate_body, "workflow_loaded_candidate_refusal")


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
            self.fields[stage + "_warning_count"] = "0"
        baseline = baseline_warning_summary((0,) * len(BASELINE_KERNEL_DOC))
        self.fields.update(dict(zip(BASELINE_WARNING_KEYS, (
            str(baseline[0]), baseline[1], baseline[2], LINUX_SHA, self.profile))))
        self.save()

    def save(self) -> None:
        lines = [f"{key}={value}" for key, value in self.fields.items()]
        allocator_objects = (("mm/swapfile.o",)
                             if (self.build / "mm/swapfile.o").exists() else ())
        for obj in ("mm/page_io.o", "block/bio.o") + allocator_objects + (
                ("mm/zswap.o",) if self.profile == "y" else ()):
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
        self.fields["kernel_export_build_baseline_warning_profile"] = "n"
        self.put(".config", (self.build / ".config").read_bytes().replace(
            b"CONFIG_ZSWAP=y\n", b"# CONFIG_ZSWAP is not set\n"))
        self.fields["config_sha256"] = self.digest((self.build / ".config").read_bytes())
        (self.build / "mm/zswap.o").unlink()
        self.save()
        self.check()


    def enable_round027_allocator_fixture(self) -> None:
        """A synthetic seven-path manifest; never a real Linux build."""
        metadata = json.loads(self.source_manifest.read_text())
        content = b"synthetic-staged-allocator-for-manifest-only"
        self.put(ALLOCATOR_PATCHED_PATH, content, self.linux)
        metadata["changed_paths"].append({
            "path": ALLOCATOR_PATCHED_PATH,
            "bytes": len(content),
            "original_git_sha1": ALLOCATOR_ORIGINAL_BLOB,
            "original_sha256": self.digest(b"synthetic-original-content"),
            "staged_sha256": self.digest(content),
            "staged_git_sha1": hashlib.sha1(
                f"blob {len(content)}\0".encode() + content).hexdigest(),
        })
        metadata["changed_paths"].sort(key=lambda item: item["path"])
        metadata["round026_allocator_epoch"] = ALLOCATOR_SOURCE_EPOCH_STATUS
        metadata["round026_allocator_probe_compiled"] = False
        metadata["direct_compressed_handoff_enabled"] = False
        self.source_manifest.write_text(json.dumps(metadata) + "\n")
        self.put("mm/swapfile.o", b"compiled-source-mm/swapfile.o")
        self.save()

    def test_round027_source_profile_early_cli_fails_closed(self) -> None:
        # This source-only CLI must fail before full kernel compilation.
        command = (sys.executable, "-B", __file__,
                   "--verify-source-manifest-only", "--source-manifest",
                   str(self.source_manifest))
        self.assertEqual(subprocess.run(command, capture_output=True, text=True,
                                        timeout=15, check=False).returncode, 0)
        self.enable_round027_allocator_fixture()
        self.assertEqual(subprocess.run(command, capture_output=True, text=True,
                                        timeout=15, check=False).returncode, 0)
        original = json.loads(self.source_manifest.read_text())
        original["round026_allocator_epoch"] = "forged"
        self.source_manifest.write_text(json.dumps(original) + "\n")
        rejected = subprocess.run(command, capture_output=True, text=True,
                                  timeout=15, check=False)
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("paired-build-invalid: source_manifest_allocator_profile",
                      rejected.stderr)
        self.assertNotIn(str(self.scratch.name), rejected.stderr)

    def test_round028_exact_seven_epoch_source_and_forged_field_rejections(self) -> None:
        """Synthetic source metadata only, not a pinned Linux build."""
        self.enable_round027_allocator_fixture()
        metadata = json.loads(self.source_manifest.read_text())
        metadata["round028_epoch_store_binding"] = (
            "CI_ONLY_MM_MINT_RETIRE_STORE_NO_BIO")
        metadata["round028_epoch_compiled"] = False
        self.source_manifest.write_text(json.dumps(metadata) + "\n")
        load_source_manifest(self.source_manifest)
        # Preserve the earlier strict SHA256-checked compiled object set.
        self.put("mm/swapfile.o", b"synthetic-allocator-object", self.build)
        self.save()
        self.check()
        for name, replacement in (
            ("round028_epoch_store_binding", "caller-forged"),
            ("round028_epoch_compiled", True),
            ("direct_compressed_handoff_enabled", True),
        ):
            with self.subTest(name=name):
                bad = dict(metadata)
                bad[name] = replacement
                self.source_manifest.write_text(json.dumps(bad) + "\n")
                # The frozen Round026 allocator profile is checked first.
                # A forged global handoff flag must fail at that FIRST gate.
                first_error = ("source_manifest_allocator_profile"
                               if name == "direct_compressed_handoff_enabled"
                               else "source_manifest_round028_profile")
                with self.assertRaisesRegex(VerificationError, first_error):
                    load_source_manifest(self.source_manifest)
        metadata["changed_paths"] = [
            entry for entry in metadata["changed_paths"]
            if entry["path"] != ALLOCATOR_PATCHED_PATH]
        self.source_manifest.write_text(json.dumps(metadata) + "\n")
        # Removing the seventh path makes this a six-path default claim
        # while retaining Round026 fields: its first failure is allocator.
        with self.assertRaisesRegex(
                VerificationError, "source_manifest_allocator_profile"):
            load_source_manifest(self.source_manifest)

    def test_round027_exact_six_default_and_seven_allocator_y_n(self) -> None:
        self.check()
        self.enable_round027_allocator_fixture()
        self.check()
        self.profile = "n"
        self.fields["requested_zswap"] = "n"
        self.fields["effective_zswap"] = "n"
        self.fields["kernel_export_build_baseline_warning_profile"] = "n"
        updated = (self.build / ".config").read_bytes().replace(
            b"CONFIG_ZSWAP=y\n", b"# CONFIG_ZSWAP is not set\n")
        self.put(".config", updated)
        self.fields["config_sha256"] = self.digest(updated)
        (self.build / "mm/zswap.o").unlink()
        self.save()
        self.check()

    def test_round027_unknown_duplicate_reordered_allocator_paths(self) -> None:
        self.enable_round027_allocator_fixture()
        original = json.loads(self.source_manifest.read_text())
        modified = json.loads(json.dumps(original))
        modified["changed_paths"][-2]["path"] = "mm/unknown-seventh.c"
        self.source_manifest.write_text(json.dumps(modified) + "\n")
        self.assert_rejects("source_manifest_paths")
        modified = json.loads(json.dumps(original))
        modified["changed_paths"].append(dict(modified["changed_paths"][-2]))
        self.source_manifest.write_text(json.dumps(modified) + "\n")
        self.assert_rejects("source_manifest_paths")
        modified = json.loads(json.dumps(original))
        modified["changed_paths"].reverse()
        self.source_manifest.write_text(json.dumps(modified) + "\n")
        self.assert_rejects("source_manifest_paths")
        modified = json.loads(json.dumps(original))
        modified["changed_paths"].pop(-2)
        self.source_manifest.write_text(json.dumps(modified) + "\n")
        # The remaining six original paths are structurally legal, but the
        # still-asserted seventh-source opt-in marker must fail independently.
        self.assert_rejects("source_manifest_allocator_profile")

    def test_round027_allocator_blob_status_and_object_integrity(self) -> None:
        self.enable_round027_allocator_fixture()
        original = json.loads(self.source_manifest.read_text())
        allocator = next(entry for entry in original["changed_paths"]
                         if entry["path"] == ALLOCATOR_PATCHED_PATH)
        allocator["original_git_sha1"] = "a" * 40
        self.source_manifest.write_text(json.dumps(original) + "\n")
        self.assert_rejects("source_manifest_allocator_blob")
        allocator["original_git_sha1"] = ALLOCATOR_ORIGINAL_BLOB
        del original["round026_allocator_epoch"]
        self.source_manifest.write_text(json.dumps(original) + "\n")
        self.assert_rejects("source_manifest_allocator_profile")
        original["round026_allocator_epoch"] = ALLOCATOR_SOURCE_EPOCH_STATUS
        original["round026_allocator_probe_compiled"] = True
        self.source_manifest.write_text(json.dumps(original) + "\n")
        self.assert_rejects("source_manifest_allocator_profile")
        original["round026_allocator_probe_compiled"] = False
        original["compiled"] = True
        self.source_manifest.write_text(json.dumps(original) + "\n")
        self.assert_rejects("source_manifest_identity")
        original["compiled"] = False
        self.source_manifest.write_text(json.dumps(original) + "\n")
        manifest_lines = self.manifest.read_text().splitlines()
        self.manifest.write_text("\n".join(
            line for line in manifest_lines
            if not line.startswith("object=mm/swapfile.o ")) + "\n")
        self.assert_rejects("object_set")
        self.save()
        (self.build / "mm/swapfile.o").write_bytes(b"forged-object")
        self.assert_rejects("object_digest")

    def test_round027_six_default_rejects_fake_allocator_epoch(self) -> None:
        metadata = json.loads(self.source_manifest.read_text())
        metadata["round026_allocator_epoch"] = ALLOCATOR_SOURCE_EPOCH_STATUS
        self.source_manifest.write_text(json.dumps(metadata) + "\n")
        self.assert_rejects("source_manifest_allocator_profile")

    def test_forged_baseline_warning_metadata(self) -> None:
        self.fields["kernel_export_build_warning_count"] = "6"
        self.save()
        self.assert_rejects("baseline_manifest_identity")
        self.fields["kernel_export_build_baseline_warning_count"] = "6"
        self.fields["kernel_export_build_baseline_warning_categories"] = "none"
        self.save()
        self.assert_rejects("baseline_manifest_evidence")

    def test_unapproved_warning_stage(self) -> None:
        self.fields["swapz_module_kbuild_warning_count"] = "1"
        self.save()
        self.assert_rejects("unapproved_stage_warnings")

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



class KernelDocBaselineTests(unittest.TestCase):
    """Source-controlled exact warning classifier; synthetic log, not Linux PASS."""

    def setUp(self) -> None:
        self.linux_root = Path("/pinned-fixture/linux")
        self.original_blobs = {item[1]: item[5] for item in BASELINE_KERNEL_DOC}
        self.lines: list[str] = []
        for position, item in enumerate(BASELINE_KERNEL_DOC):
            for _ in range(item[4]):
                self.lines.append(
                    f"Warning: {self.linux_root / item[1]}:{item[2]} {item[3]}")
                if position == 0:
                    self.lines.append(BASELINE_IPC_CONTINUATION)

    def as_text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def classify(self, *, text: str | None = None, sha: str = LINUX_SHA,
                 profile: str = "y", status: int = 0,
                 blobs: dict[str, str] | None = None) -> dict[str, str]:
        return classify_kernel_doc_warnings(
            (self.as_text() if text is None else text).encode("utf-8"),
            self.linux_root, sha, profile, status,
            self.original_blobs if blobs is None else blobs)

    def bad(self, text: str, category: str) -> None:
        with self.assertRaisesRegex(VerificationError, category):
            self.classify(text=text)

    def test_positive_six_unchanged_baseline_warnings_not_module_pass(self) -> None:
        record = self.classify()
        count, categories, digest = baseline_warning_summary((1, 2, 2, 1))
        self.assertEqual(record["kernel_export_build_baseline_warning_count"], str(count))
        self.assertEqual(record["kernel_export_build_baseline_warning_categories"], categories)
        self.assertEqual(record["kernel_export_build_baseline_warning_sha256"], digest)
        self.assertNotIn("result", record)

    def test_positive_empty_log_is_not_module_pass(self) -> None:
        self.assertEqual(self.classify(text="")[
            "kernel_export_build_baseline_warning_count"], "0")

    def test_reject_moved_line(self) -> None:
        self.bad(self.as_text().replace("sem.c:629", "sem.c:630"),
                 "baseline_unknown_warning")

    def test_reject_wrong_wording(self) -> None:
        self.bad(self.as_text().replace("Excess function parameter", "Unknown function parameter", 1),
                 "baseline_unknown_warning")

    def test_reject_wrong_path(self) -> None:
        self.bad(self.as_text().replace("blk-map.c:366", "bio.c:366"),
                 "baseline_unknown_warning")

    def test_reject_modified_producer_warning(self) -> None:
        self.bad(self.as_text() +
                 f"Warning: {self.linux_root}/mm/zswap.c:101 new doc issue\n",
                 "baseline_unknown_warning")

    def test_reject_gcc_warning(self) -> None:
        self.bad(self.as_text() + "mm/zswap.c:101:4: warning: -Werror\n",
                 "baseline_unapproved_diagnostic")

    def test_reject_nonzero_make(self) -> None:
        with self.assertRaisesRegex(VerificationError, "baseline_kernel_export_exit"):
            self.classify(status=2)

    def test_reject_forged_source_sha(self) -> None:
        with self.assertRaisesRegex(VerificationError, "baseline_source_identity"):
            self.classify(sha="f" * 40)

    def test_reject_swapped_profile(self) -> None:
        with self.assertRaisesRegex(VerificationError, "baseline_source_identity"):
            self.classify(profile="enabled")

    def test_reject_changed_upstream_blob(self) -> None:
        blobs = dict(self.original_blobs)
        blobs["block/blk-map.c"] = "f" * 40
        with self.assertRaisesRegex(VerificationError, "baseline_unmodified_blobs"):
            self.classify(blobs=blobs)

    def test_reject_excess_warning(self) -> None:
        self.bad(self.as_text() + self.lines[2] + "\n", "baseline_excess_warning")

    def test_reject_missing_expected_warning(self) -> None:
        self.bad("\n".join(self.lines[:-1]) + "\n", "baseline_counts")

    def test_reject_missing_kernel_doc_continuation(self) -> None:
        self.bad(self.as_text().replace(BASELINE_IPC_CONTINUATION, ""),
                 "baseline_ipc_continuation")

    def test_reject_hidden_compiler_error(self) -> None:
        self.bad(self.as_text() + "ld: error: undefined reference\n",
                 "baseline_unapproved_diagnostic")

    def test_reject_unpaired_continuation(self) -> None:
        self.bad(BASELINE_IPC_CONTINUATION + "\n",
                 "baseline_unapproved_diagnostic")


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

    def test_consumer_source_changes_trigger_matched_linux(self) -> None:
        with tempfile.TemporaryDirectory(prefix="consumer-trigger-") as directory:
            text = self.workflow_path.read_text()
            anchor = '      - "src/kernel/dm-target.c"'
            self.assertEqual(text.count(anchor), 1)
            path = Path(directory) / "untriggered.yml"
            path.write_text(text.replace(anchor, '      - "unrelated.txt"'))
            with self.assertRaisesRegex(
                    VerificationError, "workflow_consumer_change_trigger"):
                assert_full_workflow_contract(path)

    def test_missing_real_consumer_regression_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="consumer-regression-") as directory:
            text = self.workflow_path.read_text()
            anchor = "            swapz/tests/runtime/native/zswap-origin-producer-consumer-abi-test.py; do"
            self.assertEqual(text.count(anchor), 1)
            path = Path(directory) / "unverified.yml"
            path.write_text(text.replace(
                anchor, "            swapz/tests/runtime/native/incorrect-test.py; do"))
            with self.assertRaisesRegex(
                    VerificationError, "workflow_consumer_regression_fail_closed"):
                assert_full_workflow_contract(path)

    def test_owned_ram_preflight_removed_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="owned-ram-preflight-") as directory:
            original = self.workflow_path.read_text()
            anchor = 'if [[ "$first_exit" != 2 ]]'
            self.assertEqual(original.count(anchor), 1)
            path = Path(directory) / "unsafe.yml"
            path.write_text(original.replace(anchor, 'if [[ "$first_exit" != 0 ]]'))
            with self.assertRaisesRegex(VerificationError,
                                        "workflow_owned_ram_refusal"):
                assert_full_workflow_contract(path)

    def test_owned_ram_source_trigger_removed_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="owned-ram-trigger-") as directory:
            original = self.workflow_path.read_text()
            anchor = '      - "tests/runtime/native/zswap-origin-owned-ram-qualification.py"'
            self.assertEqual(original.count(anchor), 1)
            path = Path(directory) / "untriggered.yml"
            path.write_text(original.replace(anchor, '      - "irrelevant.txt"'))
            with self.assertRaisesRegex(VerificationError,
                                        "workflow_owned_ram_trigger"):
                assert_full_workflow_contract(path)

    def test_loaded_candidate_expected_refusal_cannot_be_bypassed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loaded-candidate-exit-") as directory:
            original = self.workflow_path.read_text()
            anchor = 'if [[ "$candidate_exit" != 2 ]]'
            self.assertEqual(original.count(anchor), 1)
            path = Path(directory) / "unsafe.yml"
            path.write_text(original.replace(anchor, 'if [[ "$candidate_exit" != 0 ]]'))
            with self.assertRaisesRegex(VerificationError,
                                        "workflow_loaded_candidate_refusal"):
                assert_full_workflow_contract(path)

    def test_loaded_candidate_source_change_must_trigger_ci(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loaded-candidate-trigger-") as directory:
            original = self.workflow_path.read_text()
            anchor = '      - "tests/runtime/native/zswap-origin-loaded-evidence-contract.py"'
            self.assertEqual(original.count(anchor), 1)
            path = Path(directory) / "untriggered.yml"
            path.write_text(original.replace(anchor, '      - "unrelated.txt"'))
            with self.assertRaisesRegex(VerificationError,
                                        "workflow_loaded_candidate_trigger"):
                assert_full_workflow_contract(path)

    def test_missing_loaded_candidate_self_test_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="loaded-candidate-test-") as directory:
            original = self.workflow_path.read_text()
            anchor = 'if python3 -B "$candidate_guard" --self-test'
            self.assertEqual(original.count(anchor), 1)
            path = Path(directory) / "unchecked.yml"
            path.write_text(original.replace(anchor,
                                             'if python3 -B "$candidate_guard" --help'))
            with self.assertRaisesRegex(VerificationError,
                                        "workflow_loaded_candidate_refusal"):
                assert_full_workflow_contract(path)

    def test_removing_classifier_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="kernel-doc-gate-") as directory:
            text = self.workflow_path.read_text()
            anchor = "            current_phase=kernel_export_build_warnings"
            self.assertEqual(text.count(anchor), 1)
            changed = text.replace(anchor, "            current_phase=untrusted_warning_bypass")
            path = Path(directory) / "workflow.yml"
            path.write_text(changed)
            with self.assertRaisesRegex(VerificationError, "workflow_baseline_fail_closed"):
                assert_full_workflow_contract(path)

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
    parser.add_argument("--classify-kernel-doc-warnings", action="store_true")
    parser.add_argument("--verify-source-manifest-only", action="store_true")
    parser.add_argument("--kernel-log", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--kernel-export-exit", type=int)
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
            unittest.defaultTestLoader.loadTestsFromTestCase(KernelDocBaselineTests),
            unittest.defaultTestLoader.loadTestsFromTestCase(FullWorkflowContractTests)))
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.verify_source_manifest_only:
        if not args.source_manifest:
            parser.error("--verify-source-manifest-only requires --source-manifest")
        try:
            load_source_manifest(args.source_manifest)
        except (VerificationError, OSError, UnicodeError) as error:
            print(str(error) if isinstance(error, VerificationError)
                  else "paired-build-invalid: source_manifest_io",
                  file=sys.stderr)
            return 1
        return 0
    if args.classify_kernel_doc_warnings:
        if not all((args.kernel_log, args.linux_root, args.source_manifest,
                    args.source_sha, args.profile)) or args.kernel_export_exit is None:
            parser.error("kernel-doc classifier needs log, source identity, profile and make exit")
        try:
            result = classify_real_kernel_export(
                args.kernel_log, args.linux_root, args.source_manifest,
                args.source_sha, args.profile, args.kernel_export_exit)
        except (VerificationError, OSError, UnicodeError) as error:
            print(str(error) if isinstance(error, VerificationError)
                  else "paired-build-invalid: baseline_io", file=sys.stderr)
            return 1
        for field in BASELINE_WARNING_KEYS:
            print(f"{field}={result[field]}")
        return 0
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
