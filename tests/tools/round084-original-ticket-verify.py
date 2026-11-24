#!/usr/bin/env python3
"""Qualify actual disconnected ticket broker, not a copied state model."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src/kernel/zswap-original-ticket.c"
FIXTURE = ROOT / "tests/runtime/native/fixtures/round084-original-ticket.c"
PINNED = {"src/kernel/codec.h":"e89d316b9cf49f82df0b77648c1be1731607987d","src/kernel/codec.c":"d920dcaac6f2b7de1334d4133770bd649719c66d","src/kernel/authority.h":"3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031","src/kernel/dm-target.c":"f1cab252cd990190646c82da81378d1563475826","src/kernel/Makefile":"ed6e19ae28a84a4a3e92117812adc445d5c2e8e5"}
ORIGINAL = {"mm/zswap.c":"ae19e301fced7e357a4c7587dfdd6abb890b9163","mm/zsmalloc.c":"7ef80e0da6267661cea4d48a4a615444724782e7","drivers/md/dm.c":"1881d86111fb2e655893ad898cf21b88f0e4e7f3"}
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
MUTANTS = [
  [
    "ceiling",
    "max_length != 3568U && max_length != 4095U",
    "max_length != 3568U && max_length != 4096U"
  ],
  [
    "alignment",
    "(unsigned long)payload % SWAPZ_TICKET_ALIGNMENT ||",
    "(unsigned long)payload % 1U ||"
  ],
  [
    "exact_capacity",
    "bytes == count * stride",
    "bytes <= count * stride"
  ],
  [
    "overlap",
    "overlap(payload, payload_bytes, free_indices, index_bytes) ||",
    "(false && overlap(payload, payload_bytes, free_indices, index_bytes)) ||"
  ],
  [
    "byte_budget_init",
    "byte_limit > (swapz_u64)count * max_length",
    "byte_limit > (swapz_u64)count * SWAPZ_BLOCK_BYTES"
  ],
  [
    "zero_length",
    "!key->length || key->length > broker->max_length",
    "key->length > broker->max_length"
  ],
  [
    "codec",
    "key->codec == SWAPZ_TICKET_LZO1X",
    "key->codec == 3U"
  ],
  [
    "version",
    "key->version == 1U",
    "key->version == 2U"
  ],
  [
    "dictionary",
    "!key->dictionary",
    "key->dictionary <= 1U"
  ],
  [
    "representation",
    "key->representation == SWAPZ_TICKET_ORIGINAL",
    "key->representation != SWAPZ_TICKET_ORIGINAL"
  ],
  [
    "store_identity",
    "key->area_epoch && key->store_sequence && key->target_session",
    "key->area_epoch && key->target_session"
  ],
  [
    "decoded_length",
    "key->decoded_length == SWAPZ_BLOCK_BYTES",
    "key->decoded_length >= 4095U"
  ],
  [
    "route_session",
    "key->target_session != broker->session ||",
    "(false && key->target_session != broker->session) ||"
  ],
  [
    "route_epoch",
    "key->table_epoch != broker->epoch)",
    "key->table_epoch < broker->epoch)"
  ],
  [
    "count_credit",
    "else if (!broker->free_count)",
    "else if (broker->free_count <= 1U)"
  ],
  [
    "byte_credit",
    "key->length > broker->byte_limit - broker->used_bytes",
    "key->length > broker->byte_limit"
  ],
  [
    "trylock_result",
    "error == EBUSY && nonblocking ? -EAGAIN : -EIO",
    "error == EBUSY && nonblocking ? -ENOSPC : -EIO"
  ],
  [
    "generation_wrap",
    "broker->next_generation == ~(swapz_u64)0",
    "broker->next_generation == ~(swapz_u64)1"
  ],
  [
    "generation_increment",
    "slot->generation = ++broker->next_generation;",
    "slot->generation = broker->next_generation;"
  ],
  [
    "charge",
    "broker->used_bytes += key->length;",
    "broker->used_bytes += 0U;"
  ],
  [
    "copy_length",
    "length != slot->key.length ||",
    "length > slot->key.length ||"
  ],
  [
    "copy_exact",
    "memcpy(destination, source, length);",
    "memcpy(destination, source, length - 1U);"
  ],
  [
    "crc",
    "crc != expected_crc",
    "crc == expected_crc"
  ],
  [
    "retain_count",
    "++slot->refs;",
    "slot->refs += 0U;"
  ],
  [
    "retain_overflow",
    "slot->refs == ~(swapz_u32)0",
    "slot->refs == ~(swapz_u32)1"
  ],
  [
    "claim_identity",
    "a->store_sequence == b->store_sequence &&",
    "a->store_sequence <= b->store_sequence &&"
  ],
  [
    "claim_once",
    "slot->state != SWAPZ_TICKET_SEALED)",
    "slot->state != SWAPZ_TICKET_SEALED && slot->state != SWAPZ_TICKET_CLAIMED)"
  ],
  [
    "stale_generation",
    "slot->generation != ref->generation",
    "slot->generation < ref->generation"
  ],
  [
    "final_credit",
    "broker->used_bytes -= slot->key.length;",
    "broker->used_bytes -= 0U;"
  ],
  [
    "revoke_epoch",
    "broker->epoch = next_epoch;",
    "broker->epoch = next_epoch - 1U;"
  ],
  [
    "close",
    "broker->closing = true;",
    "broker->closing = false;"
  ],
  [
    "cancel",
    "else\n\t\tslot->state = SWAPZ_TICKET_REVOKED;",
    "else\n\t\tslot->state = SWAPZ_TICKET_SEALED;"
  ]
]


def require(condition, detail):
    if not condition:
        raise RuntimeError(detail)


def blob(path):
    data = path.read_bytes()
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def first(result):
    lines = (result.stderr + result.stdout or "no diagnostic").splitlines()
    return next((line for line in lines if "error:" in line or "FIRST_ERROR" in line),
                lines[0])[:400]


def run(compiler, standard, source, executable):
    command = [compiler, standard, "-D_POSIX_C_SOURCE=200809L",
               "-DSWAPZ_ORIGINAL_TICKET_TEST", "-O1", "-g",
               "-Wall", "-Wextra", "-Wconversion", "-Wsign-conversion",
               "-Wshadow", "-Wstrict-prototypes", "-Werror", "-pedantic",
               "-pthread", "-fsanitize=address,undefined",
               "-fno-sanitize-recover=all", "-fno-omit-frame-pointer", "-no-pie",
               "-I", str(ROOT / "src/kernel"), str(source), str(FIXTURE),
               str(ROOT / "src/kernel/codec.c"), "-o", str(executable)]
    compiled = subprocess.run(command, text=True, capture_output=True, timeout=90)
    require(compiled.returncode == 0 and not compiled.stderr.strip(),
            f"{compiler} compile {source.name}: {first(compiled)}")
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1")
    return subprocess.run([str(executable)], text=True, capture_output=True,
                          timeout=15, env=env)


def verify(original_dir, report):
    for path, expected in PINNED.items():
        require(blob(ROOT / path) == expected, f"product blob drift {path}")
    for path, expected in ORIGINAL.items():
        require(blob(original_dir / path) == expected, f"original blob drift {path}")
    text = SOURCE.read_text()
    header = SOURCE.with_suffix(".h").read_text()
    require("#define SWAPZ_ORIGINAL_TICKET_ACTIVE 0U" in header and
            "#ifdef SWAPZ_ORIGINAL_TICKET_TEST" in text, "activation guard")
    require(len(MUTANTS) >= 20, "mutation count")
    for name, before, after in MUTANTS:
        require(text.count(before) == 1 and before != after, f"mutation anchor {name}")
    report["preflight"] = "PASS"
    with tempfile.TemporaryDirectory(prefix="round084-ticket-") as directory:
        temp = Path(directory)
        for name in ("gcc", "clang"):
            compiler = shutil.which(name)
            require(compiler, f"missing {name}")
            standard = next((flag for flag in ("-std=c23", "-std=c2x")
                             if subprocess.run([compiler, flag, "-x", "c", "-fsyntax-only", "-"],
                                               input="int main(void){return 0;}\n",
                                               text=True, capture_output=True).returncode == 0), None)
            require(standard, f"{name} missing C23/C2x")
            result = {"standard": standard, "baseline": "PENDING", "mutants_compiled": 0,
                      "mutants_executed": 0, "mutants_killed": 0, "mutants": []}
            report["compilers"][name] = result
            baseline = run(compiler, standard, SOURCE, temp / "baseline")
            require(baseline.returncode == 0 and not baseline.stderr and
                    "PASS_HOST_ONLY ROUND084_AGENT11 actual broker" in baseline.stdout,
                    f"{name} baseline: {first(baseline)}")
            result["baseline"] = baseline.stdout.strip()
            print(name + " " + baseline.stdout.strip(), flush=True)
            for index, (mutation, before, after) in enumerate(MUTANTS):
                changed = temp / f"mutant-{index:02d}.c"
                changed.write_text(text.replace(before, after, 1))
                executed = run(compiler, standard, changed, temp / "mutant")
                result["mutants_compiled"] += 1
                result["mutants_executed"] += 1
                require(executed.returncode == 77 and
                        executed.stderr.startswith("FIRST_ERROR line=") and
                        "AddressSanitizer" not in executed.stderr and
                        "runtime error:" not in executed.stderr,
                        f"{name} mutant {mutation} no semantic kill: {first(executed)}")
                result["mutants_killed"] += 1
                result["mutants"].append(mutation)
                print(f"{name} executed semantic kill {mutation}: {first(executed)}", flush=True)
    report["status"] = "PASS_HOST_ONLY"
    print(f"PASS_HOST_ONLY ROUND084_AGENT11 GCC {len(MUTANTS)}/{len(MUTANTS)} "
          f"Clang {len(MUTANTS)}/{len(MUTANTS)} independently compiled and executed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-dir", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    report = {"status": "FAIL", "original_pin": LINUX, "product_blobs": PINNED,
              "original_blobs": ORIGINAL, "compilers": {}, "first_error": None,
              "broker_source_blob": blob(SOURCE), "kernel_adapter": "UNQUALIFIED",
              "source_mapped_authenticated": 0, "phase_a": "BLOCKED",
              "direct_handoff": "DISABLED", "forced_raw_bypass": "DISABLED",
              "import_active": 0}
    try:
        verify(args.original_dir, report)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        report["first_error"] = str(exc)[:700]
        print(f"ROUND084_AGENT11_FIRST_ERROR {report['first_error']}", file=sys.stderr)
    finally:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "PASS_HOST_ONLY" else 1


if __name__ == "__main__":
    sys.exit(main())
