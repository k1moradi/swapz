#!/usr/bin/env python3
"""Round068 default-off genuine pinned-original UML decoder-owner KUnit.

Stage only a sealed test directory and one original Linux lib/Makefile line,
then run original UML KUnit with the actual source C, original spinlock/wait
queue, kernel kthreads and both selected original codec implementations.
No original MM/DM core staging, no loaded module, source AUTH or physical I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PIN = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
KERNEL_MAKEFILE = "lib/Makefile"
PINNED_LIB_MAKEFILE_BLOB = "a2afe954805cb8a9973762f017d352ec9315e419"
TEST_DIRECTORY = "lib/swapz-round068-owner-kunit"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round068-original-decoder-owner-kunit.c"
COMPONENTS = (
    ("src/kernel/zswap-import-decoder-owner.c", "8e0c8f4d2085af7f2e17df412f3a1af654063571"),
    ("src/kernel/zswap-import-decoder-owner.h", "e1b4b903567070e2307f7d05f8e48c14e0bb3768"),
    ("src/kernel/zswap-import-codec.h", "0d888fe4c74115ab2388f1df1dc0b86ae4b9b6c6"),
    ("src/kernel/codec.c", None),
    ("src/kernel/codec.h", None),
)
TEST_SUITE = "swapz_round068_decoder_owner"
CASES = (
    "swapz_round068_profile_and_fail_closed",
    "swapz_round068_native_close_wake",
    "swapz_round068_lzo1x_after_source_release",
    "swapz_round068_lz4_after_source_release",
)
COMPOSITE_MAKEFILE = (
    "obj-$(CONFIG_KUNIT) += swapz-round068-owner-tests.o\n"
    "swapz-round068-owner-tests-y := zswap-import-decoder-owner.o "
    "codec.o round068-original-decoder-owner-kunit.o\n"
)
PARENT_MAKEFILE_ADDITION = (
    "\n# Round068 test-only; original source and production imports stay disabled.\n"
    "obj-$(CONFIG_KUNIT) += swapz-round068-owner-kunit/\n"
)


class FirstError(Exception):
    pass


def require(condition: bool, label: str) -> None:
    if not condition:
        raise FirstError(label)


def git_blob(content: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def checked(command: list[str]) -> str:
    result = subprocess.run(command, text=True, capture_output=True,
                            check=False, timeout=50)
    require(result.returncode == 0 and not result.stderr,
            "original-git-prerequisite")
    return result.stdout.strip()


def stage(linux: Path, manifest: Path) -> None:
    require(checked(["git", "-C", str(linux), "rev-parse", "HEAD"]) == PIN,
            "original-kernel-pin")
    require(not checked(["git", "-C", str(linux), "status", "--porcelain",
                         "--untracked-files=all"]), "original-worktree-dirty")
    original_makefile = (linux / KERNEL_MAKEFILE).read_bytes()
    require(git_blob(original_makefile) == PINNED_LIB_MAKEFILE_BLOB,
            "original-lib-makefile-blob")
    require(not (linux / TEST_DIRECTORY).exists(),
            "test-only-kernel-directory-already-exists")
    require(not manifest.exists(), "manifest-exists")
    require(b"swapz-round068-owner-kunit" not in original_makefile,
            "duplicate-kernel-registration")
    fixture = FIXTURE.read_bytes()
    require(fixture.count(b"kunit_test_suite(swapz_round068_decoder_owner_suite);") == 1,
            "native-kunit-suite-registration")
    for case in CASES:
        require(fixture.count((case + "(").encode()) == 1,
                "native-kunit-case-definition:" + case)
    copied: list[tuple[str, bytes]] = []
    for relative_path, expected_blob in COMPONENTS:
        content = (ROOT / relative_path).read_bytes()
        if expected_blob is not None:
            require(git_blob(content) == expected_blob,
                    "production-decoder-owner-blob:" + relative_path)
        copied.append((Path(relative_path).name, content))
    require(b"#define SWAPZ_ZSWAP_IMPORT_ACTIVE 0U" in
            (ROOT / COMPONENTS[2][0]).read_bytes(),
            "dormant-import-activation-drift")
    copied.append((FIXTURE.name, fixture))
    copied.append(("Makefile", COMPOSITE_MAKEFILE.encode()))
    # All preflight evidence is checked before the first original tree write.
    staged_makefile = original_makefile + PARENT_MAKEFILE_ADDITION.encode()
    destination = linux / TEST_DIRECTORY
    destination.mkdir(mode=0o700)
    records = []
    for file_name, content in copied:
        target = destination / file_name
        target.write_bytes(content)
        require(digest(target.read_bytes()) == digest(content),
                "native-test-source-copy")
        records.append({"path": TEST_DIRECTORY + "/" + file_name,
                        "sha256": digest(content)})
    (linux / KERNEL_MAKEFILE).write_bytes(staged_makefile)
    records.append({"path": KERNEL_MAKEFILE,
                    "sha256": digest(staged_makefile)})
    report = {"original_pin": PIN, "staged_kernel_test_only": True,
              "source_mapped_authenticated": False, "active": False,
              "fixture_sha256": digest(fixture), "entries": records}
    manifest.write_text(json.dumps(report, indent=2) + "\n")
    print("ROUND068_ORIGINAL_DECODER_KUNIT_STAGE_PASS "
          "unchanged_owner_c=YES original_lib_makefile_pin=YES "
          f"source_files={len(records)} auth=0")


def verify_native(document: object, kernel_log: str) -> None:
    require(isinstance(document, dict),
            "native-kunit-json-not-object")
    groups = [document]
    matched = []
    while groups:
        group = groups.pop()
        require(isinstance(group, dict), "native-json-child")
        if group.get("name") == TEST_SUITE:
            matched.append(group)
        children = group.get("sub_groups", [])
        require(isinstance(children, list), "native-json-subgroups")
        groups.extend(children)
    require(len(matched) == 1, "native-suite-missing-or-duplicated")
    case_rows = matched[0].get("test_cases")
    require(isinstance(case_rows, list) and
            len(case_rows) == len(CASES),
            "native-kunit-actual-case-count")
    require({case.get("name") for case in case_rows if isinstance(case, dict)}
            == set(CASES) and
            all(case.get("status") == "PASS"
                for case in case_rows if isinstance(case, dict)),
            "native-executed-case-missing-fail-skip")
    misc = matched[0].get("misc", {})
    for name, expected in (
        ("tests", len(CASES)), ("passed", len(CASES)),
        ("failed", 0), ("skipped", 0), ("crashed", 0), ("errors", 0)
    ):
        require(type(misc.get(name)) is int and misc[name] == expected,
                "native-kunit-counts:" + name)
    require(kernel_log.count("# Subtest: " + TEST_SUITE) == 1,
            "native-KTAP-suite-missing-or-duplicated")
    for case in CASES:
        pattern = r"(?m)^\s*ok\s+[0-9]+\s+(?:-\s+)?" + re.escape(case) + r"\s*$"
        require(len(re.findall(pattern, kernel_log)) == 1,
                "native-KTAP-case-not-executed:" + case)
    require(re.search(
        r"(?i)(Kernel panic|KASAN:|UBSAN:|BUG: sleeping function called from invalid context|"
        r"not ok\s+[0-9]+\s+swapz_round068)", kernel_log) is None,
        "native-kernel-crash-or-failed-verdict")


def self_test() -> None:
    import copy

    def sample() -> tuple[dict, str]:
        case_rows = [{"name": case, "status": "PASS"} for case in CASES]
        node = {"name": TEST_SUITE, "test_cases": case_rows,
                "sub_groups": [],
                "misc": {"tests": len(CASES), "passed": len(CASES),
                         "failed": 0, "skipped": 0, "crashed": 0, "errors": 0}}
        text = "# Subtest: " + TEST_SUITE + "\n" + "".join(
            f"    ok {index} {case}\n"
            for index, case in enumerate(CASES, 1))
        return {"name": "kernel", "sub_groups": [node]}, text

    original, ktap = sample()
    verify_native(original, ktap)
    rejects = 0
    for kind in range(8):
        changed = copy.deepcopy(original)
        output = ktap
        node = changed["sub_groups"][0]
        if kind == 0:
            node["test_cases"][0]["status"] = "SKIP"
        elif kind == 1:
            node["test_cases"][1]["status"] = "FAIL"
        elif kind == 2:
            node["test_cases"].pop()
        elif kind == 3:
            node["misc"]["passed"] -= 1
        elif kind == 4:
            changed["sub_groups"].append(copy.deepcopy(node))
        elif kind == 5:
            output = output.replace("    ok 2 " + CASES[1], "    not ok 2 " + CASES[1])
        elif kind == 6:
            output += "KASAN: original native kernel failure\n"
        else:
            output = output.replace("# Subtest: " + TEST_SUITE,
                                    "# Subtest: forged_suite")
        try:
            verify_native(changed, output)
        except FirstError:
            rejects += 1
        else:
            raise FirstError("forged-native-verdict-accepted")
    require(rejects == 8, "native-verifier-mutant-count")
    print("ROUND068_ORIGINAL_DECODER_NATIVE_VERIFIER_SELFTEST_PASS "
          "baseline=1 rejected_semantic_verdict_mutants=8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    staging = sub.add_parser("stage")
    staging.add_argument("--linux-root", type=Path, required=True)
    staging.add_argument("--manifest", type=Path, required=True)
    checking = sub.add_parser("verify-native")
    checking.add_argument("--result", type=Path, required=True)
    checking.add_argument("--kernel-log", type=Path, required=True)
    sub.add_parser("self-test")
    args = parser.parse_args()
    try:
        if args.mode == "stage":
            stage(args.linux_root, args.manifest)
        elif args.mode == "verify-native":
            verify_native(json.loads(args.result.read_text()),
                          args.kernel_log.read_text(errors="replace"))
            print("ROUND068_GENUINE_PINNED_ORIGINAL_NATIVE_DECODER_OWNER_"
                  "KUNIT_JSON_KTAP_PASS cases=4 original_kernel=YES "
                  "spinlock_waitqueue_kthreads=YES original_LZO1X_LZ4=YES "
                  "full_original_4096=YES no_loaded_module=YES auth=0")
        else:
            self_test()
        return 0
    except (FirstError, OSError, ValueError, KeyError,
            subprocess.SubprocessError, subprocess.TimeoutExpired) as error:
        detail = str(error) if isinstance(error, FirstError) else type(error).__name__
        print("ROUND068_ORIGINAL_DECODER_NATIVE_FIRST_ERROR "
              "phase=" + args.mode + " reason=" + detail[:150],
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
