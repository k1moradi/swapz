#!/usr/bin/env python3
"""R097 newly emitted owner wire: current binding and correlation only."""
import json
from pathlib import Path
import struct
import subprocess
import sys

source, directory = sys.argv[1:]
directory = Path(directory)
parser = Path(__file__).resolve().parents[2] / "tools/native-observation-current-export.py"
scope = dict(source=source, mapping_source="ff972661a75ca7f8c3c0458c3feb8b603c185eb8",
             linux_source="c339f4010dea8b0d754f84ace70cd1b089878ef8",
             kernel_sha256="1"*64, module_sha256="2"*64, workload_sha256="3"*64,
             run_nonce="4"*32, target="5"*32, session=11, epoch=12, target_epoch=13,
             registration_epoch=14, first_logical=7, page_count=2, profile="M3568")
checks = 0


def invoke(raw, manifest, expected, status, reason=None):
    global checks
    run = subprocess.run([sys.executable, "-B", str(parser), expected,
                          json.dumps(manifest)], input=raw, capture_output=True,
                         check=False, timeout=10)
    result = json.loads(run.stdout)
    assert result["status"] == status, (status, result)
    assert run.returncode == (0 if status.startswith("CONSISTENT") else 2)
    assert not run.stderr and not result["source_mapped_authenticated"]
    if reason:
        assert result["reason"] == reason, result
    checks += 1
    return result


for compiler in ("gcc", "clang"):
    clean = (directory / f"{compiler}-clean.wire").read_bytes()
    result = invoke(clean, scope, source, "CONSISTENT_RECORDER_OBSERVATIONS_ONLY")
    assert result["records"] == 6 and result["counts"]["clone_acks"] == 1
    assert result["counts"]["upper_acks"] == 1
    invoke(clean, dict(scope, source="a"*40), source, "BLOCKED", "stale_build_source")
    invoke(clean, scope, "a"*40, "BLOCKED", "stale_build_source")
    invoke(clean, scope, scope["mapping_source"], "BLOCKED", "expected_build_source")
    invoke(clean, dict(scope, run_nonce="6"*32), source, "BLOCKED", "header_scope")
    # Actual owner-generated clone and upper records have different role IDs.
    wrong = bytearray(clean)
    struct.pack_into("<Q", wrong, 104 + 4*296 + 4*8, 4)  # original <- clone
    invoke(wrong, scope, source, "BLOCKED", "upper_endio")
    wrong = bytearray(clean)
    struct.pack_into("<Q", wrong, 104 + 3*8, 2)  # clone <- original at accept
    invoke(wrong, scope, source, "BLOCKED", "token_role_or_reuse")
    # Remove actual modeled upper observation; repair only frame counts and
    # sequence so the semantic missing-upper-debt check must detect it.
    wrong = bytearray(clean[:104+4*296] + clean[104+5*296:])
    struct.pack_into("<Q", wrong, 80, 5)
    struct.pack_into("<Q", wrong, 104+4*296, 5)
    struct.pack_into("<Q", wrong, len(wrong)-16, 5)
    invoke(wrong, scope, source, "BLOCKED", "incomplete_lifetime")
    for mode, expected_loss in (("join", 8), ("overflow", 2), ("invalid", 4)):
        raw = (directory / f"{compiler}-{mode}.wire").read_bytes()
        assert struct.unpack_from("<I", raw, len(raw)-8)[0] == expected_loss
        invoke(raw, scope, source, "BLOCKED", "recorder_loss")
print(json.dumps(dict(current_scope_and_correlation_cases=checks,
                      compilers=2, native_capture=False, auth=0), sort_keys=True))
