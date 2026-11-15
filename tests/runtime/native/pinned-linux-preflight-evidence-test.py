#!/usr/bin/env python3
"""Offline, rootless acceptance of the existing pinned-Linux CI profile schema.

Manifest text is not an authenticated artifact or a loaded-kernel test.
"""

import re
import unittest

LINUX_SHA = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
TEST_SWAPZ_SHA = "45a3e8e911e447d9807f786ca33e14eac99374f8"
GCC_CLASS = "pinned-linux-targeted-objects-and-linked-external-module"
LLVM_CLASS = "LLVM_STOCK_SOURCE_OBJECT_KBUILD"
GCC_STAGES = ("defconfig", "scripts_config", "olddefconfig", "prepare",
              "compile_objects", "modules_prepare", "kernel_export_build",
              "swapz_module_kbuild")
LLVM_STAGES = GCC_STAGES[:5]
COMMON_OBJECTS = ("mm/page_io.o", "block/bio.o")
KNOWN = set("""source_repository source_sha source_modified swapz_sha requested_zswap result
 evidence_class phase_a_qualified producer_authenticated upstream_patched compiler linker
 clang_package lld_package llvm_package llvm_make_setting kbuild_jobs
 kbuild_warning_level kbuild_recorded_compiler effective_swap effective_zswap
 effective_modules effective_blk_dev_dm effective_crypto_lz4
 effective_lz4_compress effective_lz4_decompress effective_cc_is_clang
 config_sha256 config_verification_exit_code compiled_object object object_sha256
 module_symvers_sha256 module_linked module_bytes module_sha256 module_warning_count
 error_category reason first_failure first_failure_phase first_failure_exit_code""".split())
for stage in GCC_STAGES:
    KNOWN.update((stage + "_command", stage + "_exit_code", stage + "_warning_count"))
RESERVED_PREFIXES = ("source_", "swapz_", "requested_", "effective_", "config_",
                     "kbuild_", "compiled_", "object_", "module_", "evidence_",
                     "producer_", "phase_a_", "result_", "first_failure",
                     "defconfig_", "scripts_config_", "olddefconfig_", "prepare_",
                     "compile_objects_", "modules_prepare_", "kernel_export_",
                     "upstream_", "error_", "llvm_", "clang_",
                     "compiler_", "linker_", "warning_")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
KEY = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
UINT = re.compile(r"0|[1-9][0-9]*\Z")


class InvalidEvidence(ValueError):
    """Bounded, field-only refusal (never includes untrusted values)."""


def require(condition: bool, name: str) -> None:
    if not condition:
        raise InvalidEvidence("invalid evidence: " + name)


def unsigned(value: str | None, name: str, positive: bool = False) -> int:
    require(value is not None and len(value) <= 20 and
            re.fullmatch(r"0|[1-9][0-9]*", value) is not None, name)
    number = int(value)
    require(number <= 0xffffffffffffffff and (not positive or number != 0), name)
    return number


def parse(data: bytes) -> tuple[dict[str, str], list[str], list[tuple[str, str]]]:
    require(isinstance(data, bytes) and 0 < len(data) <= 32768, "byte_limit")
    try:
        content = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise InvalidEvidence("invalid evidence: utf8") from error
    require(content.endswith("\n") and "\r" not in content, "newline")
    lines = content.splitlines()
    require(len(lines) <= 160, "line_limit")
    fields: dict[str, str] = {}
    compiled: list[str] = []
    objects: list[tuple[str, str]] = []
    pending_object: str | None = None
    for line in lines:
        require(len(line) <= 4096 and "=" in line, "line")
        name, value = line.split("=", 1)
        require(KEY.fullmatch(name) is not None and
                all(32 <= ord(character) <= 126 for character in value), "grammar")
        if name not in KNOWN:
            require(not name.startswith(RESERVED_PREFIXES), "unknown_reserved_key")
            continue
        if name == "compiled_object":
            compiled.append(value)
        elif name == "object":
            require(pending_object is None and bool(value), "object_pair")
            pending_object = value
        elif name == "object_sha256":
            require(pending_object is not None, "object_pair")
            objects.append((pending_object, value))
            pending_object = None
        else:
            require(name not in fields, "duplicate_" + name)
            fields[name] = value
    require(pending_object is None, "object_pair")
    return fields, compiled, objects


def validate(data: bytes, requested: str, expected_swapz_sha: str) -> str:
    """Validate a purported PASS; return GCC/LLVM class, never runtime proof."""
    require(requested in ("y", "n"), "requested_profile")
    fields, compiled, objects = parse(data)
    for forbidden in ("reason", "first_failure", "first_failure_phase",
                      "first_failure_exit_code"):
        require(forbidden not in fields, forbidden)
    for name, expected in (("result", "PASS"), ("source_repository", "torvalds/linux"),
                           ("source_sha", LINUX_SHA), ("requested_zswap", requested),
                           ("effective_swap", "y"), ("effective_zswap", requested),
                           ("source_modified", "no"), ("phase_a_qualified", "no"),
                           ("kbuild_warning_level", "1")):
        require(fields.get(name) == expected, name)
    require(SHA256.fullmatch(fields.get("config_sha256", "")) is not None,
            "config_sha256")
    require(1 <= unsigned(fields.get("kbuild_jobs"), "kbuild_jobs") <= 4,
            "kbuild_jobs")
    require(bool(fields.get("kbuild_recorded_compiler")), "kbuild_recorded_compiler")
    # A positive offline manifest must never relabel stock-source compilation
    # as an authenticated producer or as patched Linux.
    require(fields.get("producer_authenticated") in (None, "no"),
            "producer_authenticated")
    require(fields.get("upstream_patched") in (None, "no"),
            "upstream_patched")
    required_objects = COMMON_OBJECTS + (("mm/zswap.o",) if requested == "y" else ())
    evidence_class = fields.get("evidence_class")
    require(evidence_class in (GCC_CLASS, LLVM_CLASS), "evidence_class")
    if evidence_class == GCC_CLASS:
        require(not objects, "unexpected_llvm_objects")
        require(re.fullmatch(r"[a-f0-9]{40}", expected_swapz_sha) is not None and
                fields.get("swapz_sha") == expected_swapz_sha, "swapz_sha")
        require("gcc" in fields.get("compiler", "").lower(), "compiler")
        require("gcc" in fields["kbuild_recorded_compiler"].lower(),
                "kbuild_recorded_compiler")
        for name in ("effective_modules", "effective_blk_dev_dm", "effective_crypto_lz4",
                     "effective_lz4_compress", "effective_lz4_decompress"):
            require(fields.get(name) == "y", name)
        require(fields.get("producer_authenticated") == "no", "producer_authenticated")
        require(fields.get("module_linked") == "yes", "module_linked")
        unsigned(fields.get("module_bytes"), "module_bytes", positive=True)
        for name in ("module_sha256", "module_symvers_sha256"):
            require(SHA256.fullmatch(fields.get(name, "")) is not None, name)
        require(fields.get("config_verification_exit_code") == "0",
                "config_verification_exit_code")
        require(fields.get("error_category") == "none", "error_category")
        require(unsigned(fields.get("module_warning_count"), "module_warning_count") == 0,
                "module_warning_count")
        require(sorted(compiled) == sorted(required_objects), "compiled_object")
        require("llvm_make_setting" not in fields and
                "effective_cc_is_clang" not in fields, "unexpected_llvm_claim")
        stages = GCC_STAGES
    else:
        require(not compiled, "unexpected_gcc_objects")
        require(fields.get("effective_cc_is_clang") == "y", "effective_cc_is_clang")
        require(fields.get("llvm_make_setting") == "LLVM=-18", "llvm_make_setting")
        require("clang" in fields["kbuild_recorded_compiler"].lower(),
                "kbuild_recorded_compiler")
        for name in ("compiler", "linker", "clang_package", "lld_package", "llvm_package"):
            require(bool(fields.get(name)), name)
        require("clang" in fields["compiler"].lower(), "compiler")
        require("lld" in fields["linker"].lower(), "linker")
        for name in fields:
            require(not name.startswith(("module_", "swapz_module_kbuild",
                                             "kernel_export_build")) and name != "swapz_sha",
                    "llvm_not_linked")
        require(sorted(name for name, _ in objects) == sorted(required_objects), "object")
        for _, digest in objects:
            require(SHA256.fullmatch(digest) is not None, "object_sha256")
        stages = LLVM_STAGES
    for stage in stages:
        require(bool(fields.get(stage + "_command")), stage + "_command")
        require(fields.get(stage + "_exit_code") == "0", stage + "_exit_code")
        if evidence_class == LLVM_CLASS:
            require(fields.get(stage + "_warning_count") == "0", stage + "_warning_count")
    return evidence_class


def fixture(profile: str, requested: str) -> bytes:
    records = ["result=PASS", "source_repository=torvalds/linux",
               f"source_sha={LINUX_SHA}", f"requested_zswap={requested}",
               f"effective_zswap={requested}", "effective_swap=y", "source_modified=no",
               "phase_a_qualified=no", "config_sha256=" + "a" * 64, "kbuild_jobs=4",
               "kbuild_warning_level=1", "kbuild_recorded_compiler=clang 18.1"
               if profile == "llvm" else "kbuild_recorded_compiler=gcc 13.3"]
    objects = COMMON_OBJECTS + (("mm/zswap.o",) if requested == "y" else ())
    if profile == "gcc":
        records.extend([f"evidence_class={GCC_CLASS}", f"swapz_sha={TEST_SWAPZ_SHA}",
                        "compiler=gcc 13.3", "producer_authenticated=no",
                        "effective_modules=y", "effective_blk_dev_dm=y",
                        "effective_crypto_lz4=y", "effective_lz4_compress=y",
                        "effective_lz4_decompress=y", "module_linked=yes",
                        "module_bytes=1024", "module_sha256=" + "b" * 64,
                        "module_symvers_sha256=" + "c" * 64,
                        "module_warning_count=0", "config_verification_exit_code=0",
                        "error_category=none"])
        records.extend(f"compiled_object={name}" for name in objects)
        stages = GCC_STAGES
    else:
        records.extend([f"evidence_class={LLVM_CLASS}", "effective_cc_is_clang=y",
                        "llvm_make_setting=LLVM=-18", "compiler=clang 18.1",
                        "linker=LLD 18.1", "clang_package=18", "lld_package=18",
                        "llvm_package=18"])
        for name in objects:
            records.extend((f"object={name}", "object_sha256=" + "d" * 64))
        stages = LLVM_STAGES
    for stage in stages:
        records.extend((f"{stage}_command=make {stage}", f"{stage}_exit_code=0"))
        if profile == "llvm":
            records.append(f"{stage}_warning_count=0")
    return ("\n".join(records) + "\n").encode("ascii")


def change(data: bytes, name: str, value: str | None) -> bytes:
    lines = data.decode("ascii").splitlines()
    matches = [index for index, line in enumerate(lines)
               if line.split("=", 1)[0] == name]
    if len(matches) != 1:
        raise AssertionError("nonunique test mutation anchor: " + name)
    if value is None:
        del lines[matches[0]]
    else:
        lines[matches[0]] = name + "=" + value
    return ("\n".join(lines) + "\n").encode("ascii")


class PreflightEvidenceTests(unittest.TestCase):
    def test_valid_existing_profile_shapes(self) -> None:
        for profile, result in (("gcc", GCC_CLASS), ("llvm", LLVM_CLASS)):
            for requested in ("y", "n"):
                with self.subTest(profile=profile, requested=requested):
                    self.assertEqual(validate(fixture(profile, requested), requested,
                                              TEST_SWAPZ_SHA), result)

    def test_optional_unrelated_field(self) -> None:
        self.assertEqual(validate(fixture("gcc", "y") + b"collector_note=optional\n",
                                  "y", TEST_SWAPZ_SHA), GCC_CLASS)

    def test_adversarial_claims(self) -> None:
        gcc, llvm = fixture("gcc", "y"), fixture("llvm", "y")
        negative: list[tuple[str, bytes, str]] = [
            ("truncated", gcc[:-4], "y"),
            ("invalid_utf8", gcc + b"note=\xff\n", "y"),
            ("oversized", gcc + b"note=" + b"z" * 32768, "y"),
            ("duplicate_result", gcc + b"result=PASS\n", "y"),
            ("duplicate_requested", gcc + b"requested_zswap=n\n", "y"),
            ("unknown_reserved", gcc + b"module_fake_proof=yes\n", "y"),
            ("unknown_llvm_claim", llvm + b"llvm_module_linked=yes\n", "y"),
            ("unknown_compiler_claim", gcc + b"compiler_warning_count=5\n", "y"),
            ("duplicate_compiled_object", gcc + b"compiled_object=mm/page_io.o\n", "y"),
            ("duplicate_llvm_object", llvm + b"object=mm/page_io.o\n"
             b"object_sha256=" + b"d" * 64 + b"\n", "y"),
            ("false_first_failure", gcc + b"first_failure=build\n", "y"),
            ("false_failure_exit", llvm + b"first_failure_exit_code=1\n", "y"),
            ("false_not_run_reason", gcc + b"reason=skipped\n", "y"),
            ("missing_enabled_object", gcc.replace(b"compiled_object=mm/zswap.o\n",
                                                     b"", 1), "y"),
            ("disabled_extra_object", fixture("gcc", "n") +
             b"compiled_object=mm/zswap.o\n", "n"),
            ("llvm_disabled_zswap_object", fixture("llvm", "n") +
             b"object=mm/zswap.o\nobject_sha256=" + b"a" * 64 + b"\n", "n"),
            ("llvm_forged_link", llvm + b"module_linked=yes\n", "y"),
            ("llvm_orphan_hash", llvm + b"object_sha256=" + b"a" * 64 + b"\n", "y"),
        ]
        mutated = {
            "result": ["FAIL", "NOT_RUN"],
            "source_repository": ["other/linux"],
            "source_sha": ["f" * 40, None],
            "swapz_sha": ["e" * 40, None],
            "requested_zswap": ["n", None],
            "effective_zswap": ["n", None],
            "source_modified": ["yes"],
            "config_sha256": ["wrong", None],
            "module_linked": ["no", None],
            "module_bytes": ["0", "00", "+4", "18446744073709551616", None],
            "module_sha256": ["bad", None],
            "module_symvers_sha256": ["bad", None],
            "swapz_module_kbuild_exit_code": ["1", None],
            "kernel_export_build_exit_code": ["3"],
            "config_verification_exit_code": ["1"],
            "module_warning_count": ["1"],
            "phase_a_qualified": ["yes"],
            "compiler": ["clang 18.1"],
            "kbuild_recorded_compiler": ["clang 18.1"],
        }
        for name, replacements in mutated.items():
            for replacement in replacements:
                negative.append((f"gcc_{name}_{replacement}",
                                 change(gcc, name, replacement), "y"))
        for name, replacement in (("effective_cc_is_clang", "n"),
                                  ("compiler", "gcc 13"),
                                  ("linker", "GNU ld"),                                  ("compile_objects_exit_code", "1"),
                                  ("compile_objects_warning_count", "1"),
                                  ("llvm_make_setting", "LLVM=1"),
                                  ("config_sha256", "bad")):
            negative.append(("llvm_" + name, change(llvm, name, replacement), "y"))
        negative.extend((
            ("gcc_false_producer_authenticated",
             gcc + b"producer_authenticated=yes\n", "y"),
            ("gcc_false_upstream_patched", gcc + b"upstream_patched=yes\n", "y"),
            ("llvm_false_producer_authenticated",
             llvm + b"producer_authenticated=yes\n", "y"),
            ("llvm_false_upstream_patched", llvm + b"upstream_patched=yes\n", "y"),
        ))
        for label, evidence, requested in negative:
            with self.subTest(label=label):
                with self.assertRaises(InvalidEvidence):
                    validate(evidence, requested, TEST_SWAPZ_SHA)
        print(f"PASS: {len(negative)} adversarial claims rejected")


if __name__ == "__main__":
    unittest.main()
