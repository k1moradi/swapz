#!/usr/bin/env python3
"""Strict source-linked credential helper and genuine native result checks."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/runtime/native/fixtures"
HELPER = FIXTURES / "round084-original-store-credential-helper.cfrag"
HOST = FIXTURES / "round084-original-store-credential-host.cfrag"
SUITE = "swapz_round084_original_store_credential"
CASES = {
    "r084_original_lz4", "r084_original_lzo1x", "r084_original_raw_optional",
    "r084_original_unsupported", "r084_original_generation",
}

# Each mutant edits the actual helper, not the oracle or a standalone model.
# Every edit must have a unique anchor, compile cleanly, and reach the explicit
# behavioral failure exit; compilation failures or sanitizer crashes never count.
MUTANTS = [
    ("lz4-name", '!strcmp(name, "lz4")', 'strcmp(name, "unused") != 0'),
    ("lz4-driver", '!strcmp(driver, "lz4-scomp")', 'strcmp(driver, "unused") != 0'),
    ("lzo-driver", '!strcmp(driver, "lzo-scomp")', 'strcmp(driver, "unused") != 0'),
    ("storage-failure", "!stored || compression_error", "(!stored && length == 1) || compression_error"),
    ("compression-error", "|| compression_error ||", "|| (compression_error && length == 1) ||"),
    ("zero-length", "!length || length >= 4096", "length == 1 || length >= 4096"),
    ("ceiling", "length > context->ceiling", "length > 4095"),
    ("invalid-ceiling", "(context->ceiling != 3568 && context->ceiling != 4095)", "context->ceiling > 4095"),
    ("copy-capacity", "length > context->capacity", "length > context->capacity + 4096U"),
    ("session", "!context->session || !context->area_epoch", "context->session == 99 || !context->area_epoch"),
    ("area-epoch", "!context->area_epoch ||", "context->area_epoch == 99 ||"),
    ("slot-range", "context->slot >= context->slot_limit", "context->slot > context->slot_limit"),
    ("type-range", "context->type >= context->type_limit", "context->type > context->type_limit"),
    ("sequence-overflow", "context->last_sequence == ~(u64)0", "context->last_sequence == 99"),
    ("sequence-increment", "++context->last_sequence", "(context->last_sequence += 2)"),
    ("profile-version", "context->record.version = 1;", "context->record.version = 2;"),
    ("digest-input", "r084_sha(original, 4096,", "r084_sha(compressed, 4096,"),
    ("compressed-crc", "r084_crc(compressed, length)", "r084_crc(compressed, length - 1)"),
    ("immutable-copy", "memcpy(context->payload, compressed, length);", "memcpy(context->payload, compressed, length - 1);"),
    ("clear-on-failed-capture", "r084_clear(context);\n\tcodec", "if (stored)\n\t\tr084_clear(context);\n\tcodec"),
    ("clear-on-store-failure", "r084_clear(context);\n\t\treturn;", "context->record.state = R084_PREPUBLICATION;\n\t\treturn;"),
    ("stale-sequence", "candidate->sequence == live->sequence", "candidate->sequence != 0"),
    ("stale-session", "candidate->session == live->session", "candidate->session != 0"),
    ("stale-digest", "!memcmp(candidate->digest, live->digest, sizeof(live->digest))", "sizeof(live->digest) == 32"),
    ("stale-crc", "candidate->crc == live->crc", "candidate->crc != UINT32_C(0xdeadbeef)"),
    ("payload-corruption", "r084_crc(context->payload, live->length) == live->crc", "context->payload != NULL"),
]


class FirstError(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise FirstError(reason)


def first_line(message):
    lines = message.splitlines()
    for line in lines:
        if re.search(r"error:|R084_CHECK:|AddressSanitizer|runtime error:", line):
            return re.sub(r"(?:/[^:\s]+)+/", "source/", line)[:250]
    return lines[0][:250] if lines else "no-diagnostic"


def host():
    helper = HELPER.read_text()
    fixture = HOST.read_text()
    marker = "/* R084_INSERT_ACTUAL_HELPER */"
    require(fixture.count(marker) == 1, "host-insertion-anchor")
    sources = [("baseline", helper)]
    for name, old, new in MUTANTS:
        require(helper.count(old) == 1, "mutant-anchor:" + name)
        sources.append((name, helper.replace(old, new, 1)))
    require(len({source for _, source in sources}) == len(sources), "duplicate-mutant")
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    with tempfile.TemporaryDirectory(prefix="round084-host-") as temporary:
        directory = Path(temporary)
        for compiler in ("gcc", "clang"):
            spelling = "c2x" if compiler == "gcc" else "c23"
            probe = subprocess.run([compiler, "-std=" + spelling, "-x", "c",
                                    "-fsyntax-only", "-"], input="int value;\n",
                                   text=True, capture_output=True, timeout=20)
            if compiler == "clang" and probe.returncode:
                spelling = "c2x"
            count = 0
            for name, source in sources:
                cfile = directory / (name + ".c")
                binary = directory / name
                cfile.write_text(fixture.replace(marker, source))
                build = subprocess.run([
                    compiler, "-std=" + spelling, "-O1", "-g", "-Wall", "-Wextra",
                    "-Wpedantic", "-Werror", "-Wshadow", "-Wconversion",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-fno-pie", "-no-pie", str(cfile), "-lcrypto", "-o", str(binary),
                ], text=True, capture_output=True, timeout=60)
                require(build.returncode == 0,
                        compiler + ":compile:" + name + ":" + first_line(build.stderr))
                execution = subprocess.run([str(binary)], env=environment, text=True,
                                           capture_output=True, timeout=20)
                if name == "baseline":
                    require(execution.returncode == 0 and
                            execution.stdout.strip() == "R084_HOST_BASELINE_PASS" and
                            not execution.stderr, compiler + ":baseline:" +
                            first_line(execution.stderr))
                else:
                    require(execution.returncode == 77 and
                            execution.stderr.startswith("R084_CHECK:") and
                            "Sanitizer" not in execution.stderr and
                            "runtime error:" not in execution.stderr,
                            compiler + ":mutant-not-behaviorally-killed:" + name +
                            ":" + first_line(execution.stderr))
                    count += 1
                    print(f"PASS R084_MUTANT compiler={compiler} case={name} compiled=1 executed=1", flush=True)
            print(f"PASS R084_HOST compiler={compiler} std={spelling} "
                  f"baseline=PASS compiled_executed_semantic_mutants={count} "
                  "ASAN_UBSAN=YES AUTH0", flush=True)


def verify_native(document, ktap):
    pending = [document]
    matches = []
    while pending:
        node = pending.pop()
        require(isinstance(node, dict), "json-node")
        if node.get("name") == SUITE:
            matches.append(node)
        children = node.get("sub_groups", [])
        require(isinstance(children, list), "json-child-list")
        pending.extend(children)
    require(len(matches) == 1, "native-suite-count")
    suite = matches[0]
    cases = suite.get("test_cases")
    require(isinstance(cases, list) and len(cases) == len(CASES) and
            all(isinstance(case, dict) and case.get("status") == "PASS" for case in cases) and
            {case.get("name") for case in cases} == CASES, "native-case-verdict")
    misc = suite.get("misc", {})
    for key, expected in (("tests", len(CASES)), ("passed", len(CASES)),
                          ("failed", 0), ("skipped", 0), ("crashed", 0), ("errors", 0)):
        require(type(misc.get(key)) is int and misc[key] == expected, "native-misc:" + key)
    require(ktap.count("# Subtest: " + SUITE) == 1, "native-KTAP-suite")
    for case in CASES:
        require(len(re.findall(r"(?m)^\s*ok\s+[0-9]+\s+(?:-\s+)?" +
                               re.escape(case) + r"\s*$", ktap)) == 1,
                "native-KTAP-case:" + case)
    require(re.search(r"(?i)kernel panic|KASAN:|UBSAN:|BUG: sleeping|"
                      r"not ok\s+[0-9]+\s+(?:-\s+)?(?:r084_|" + SUITE + ")", ktap) is None,
            "native-KTAP-failure")
    print("PASS R084_GENUINE_ORIGINAL_COMPRESSOR_NATIVE JSON_KTAP=5/5 "
          "actual_zswap_compress=YES test_created_XArray=YES "
          "live_zswap_store_page=NO selected_DM=UNPROVEN AUTH0", flush=True)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("host")
    native = commands.add_parser("verify-native")
    native.add_argument("--result", type=Path, required=True)
    native.add_argument("--kernel-log", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "host":
        host()
    else:
        verify_native(json.loads(args.result.read_text()),
                      args.kernel_log.read_text(errors="replace"))


if __name__ == "__main__":
    try:
        main()
    except (FirstError, OSError, ValueError, subprocess.SubprocessError) as error:
        print("R084_FIRST_ERROR " + (str(error) if isinstance(error, FirstError)
              else type(error).__name__), file=sys.stderr)
        sys.exit(2)
