#!/usr/bin/env python3
"""Exact native-only stage and result gate for the actual disabled broker."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
LINUX = "c339f4010dea8b0d754f84ace70cd1b089878ef8"
PRODUCT = {
    "src/kernel/zswap-original-ticket.c": "dcea7cbc40094fed2997d6704c712ac47aa164a1",
    "src/kernel/zswap-original-ticket.h": "b772cc28755a68719f4dcdabefeefe57b5efea67",
    "src/kernel/codec.c": "d920dcaac6f2b7de1334d4133770bd649719c66d",
    "src/kernel/codec.h": "e89d316b9cf49f82df0b77648c1be1731607987d",
    "src/kernel/authority.h": "3bb5bab5a5bdb2aa087f5793fc8b5e90d6636031",
    "src/kernel/dm-target.c": "f1cab252cd990190646c82da81378d1563475826",
    "src/kernel/Makefile": "ed6e19ae28a84a4a3e92117812adc445d5c2e8e5",
    "tests/runtime/native/fixtures/round086-original-ticket-kunit.c": "90da2e570cc9177c8a674a47bbd404690b2578c7"
}
ORIGINAL = {
    "lib/kunit/Makefile": "204e02b10eba1030c6d511991fe2f6271de64603",
    "lib/kunit/Kconfig": "cbda6189a308a0b159f63b7c1933456c9427e39e",
    "include/linux/crc32c.h": "b8cff2f4309a70efb6521491438dce0be19e0d74",
    "include/linux/crc32.h": "da78b215ff2e9365188cf6318c111163c0c7af32",
    "include/linux/spinlock.h": "3d405cc4c1218c188b8cbaab24736ac7a8819ef6",
    "include/linux/spinlock_up.h": "3a50976471d7118ac66b3f3594329c1e96545dac",
    "include/linux/spinlock_api_smp.h": "90909d933dab7c6654546ac2a6bc1f6bee2feac1",
    "kernel/locking/spinlock_debug.c": "2338b3adfb55ffd806dedadc4fef20b1f1ee7e63",
    "arch/um/Kconfig": "7245e3ada1c5a7e8f3f23cb28dece946172e4361",
    "arch/x86/um/Kconfig": "44b12e45f9a058bb06d2c628168d21e961aa3943",
    "arch/um/kernel/smp.c": "92ea1beaed8b21d6a7ad45008dc240004bb65ee3",
    "arch/um/include/asm/irqflags.h": "31e49e0894c5e7ccf842ae81f9bfbe0af5958f49",
    "include/linux/irqflags.h": "57b074e0cfbbb3ac2a1384ead68c2f074e4c9a2a",
    "lib/Kconfig.debug": "2d22638ec13a63364d0f41d1086027ed48d320e0",
    "lib/crc/Kconfig": "927fc6a6b2b9d32fc78bf6f21d113c78c53894ab",
    "tools/testing/kunit/kunit.py": "91d234ac3b579260a33557955ecf7979c8439d01",
    "tools/testing/kunit/kunit_json.py": "80fa4e354a17afde99c92666a71b0c7ca237a594"
}
STAGE = "lib/kunit/swapz-round086"
SUITE = "swapz_round086_original_ticket"
CASES = (
    "r086_capacity", "r086_irq_and_contention", "r086_seal_claim",
    "r086_revoke_close", "r086_generation_refs", "r086_copy_failures",
)
CONFIG = (
    "CONFIG_KUNIT=y", "CONFIG_SMP=y", "CONFIG_NR_CPUS=2",
    "CONFIG_DEBUG_KERNEL=y", "CONFIG_DEBUG_SPINLOCK=y",
    "CONFIG_DEBUG_ATOMIC_SLEEP=y", "CONFIG_CRC32=y",
    "CONFIG_SWAPZ_ROUND086_TICKET_TEST=y",
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def identity(data):
    return {"git_blob": blob(data), "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, check=True)
    return result.stdout


def patch_tail(data, anchor, addition):
    require(data.count(anchor) == 1 and data.endswith(anchor), "stage-tail-anchor")
    return data + addition


def stage_plan(linux):
    require(git(linux, "rev-parse", "HEAD").decode().strip() == LINUX,
            "wrong original Linux HEAD")
    for path, expected in PRODUCT.items():
        require(blob((ROOT / path).read_bytes()) == expected, "product drift " + path)
    originals = {}
    for path, expected in ORIGINAL.items():
        data = git(linux, "show", f"HEAD:{path}")
        require(blob(data) == expected, "original blob drift " + path)
        originals[path] = data
    make_anchor = b"obj-$(CONFIG_KUNIT_EXAMPLE_TEST) +=\tkunit-example-test.o\n"
    config_anchor = b"endif # KUNIT\n"
    make_add = b"\nobj-$(CONFIG_SWAPZ_ROUND086_TICKET_TEST) += swapz-round086/\n"
    config_add = (b"\nconfig SWAPZ_ROUND086_TICKET_TEST\n"
                  b"\tbool \"Isolated swapz Round086 original ticket test\"\n"
                  b"\tdepends on KUNIT=y && SMP && DEBUG_SPINLOCK && DEBUG_ATOMIC_SLEEP\n"
                  b"\tselect CRC32\n"
                  b"\tdefault n\n")
    negatives = 0
    for path, anchor, addition in (("lib/kunit/Makefile", make_anchor, make_add),
                                   ("lib/kunit/Kconfig", config_anchor, config_add)):
        for changed in (originals[path].replace(anchor, b"", 1),
                        originals[path] + anchor, originals[path] + b"# drift\n"):
            try:
                patch_tail(changed, anchor, addition)
            except RuntimeError:
                negatives += 1
            else:
                raise RuntimeError("accepted negative stage plan " + path)
    files = {
        "lib/kunit/Makefile": patch_tail(originals["lib/kunit/Makefile"], make_anchor, make_add),
        "lib/kunit/Kconfig": patch_tail(originals["lib/kunit/Kconfig"], config_anchor, config_add),
        STAGE + "/Makefile": (b"ccflags-y += -DSWAPZ_ORIGINAL_TICKET_TEST=1 -Werror\n"
                              b"obj-y += zswap-original-ticket.o codec.o ticket-kunit.o\n"),
    }
    for name in ("zswap-original-ticket.c", "zswap-original-ticket.h", "codec.c", "codec.h"):
        files[STAGE + "/" + name] = (ROOT / "src/kernel" / name).read_bytes()
    files[STAGE + "/ticket-kunit.c"] = (
        ROOT / "tests/runtime/native/fixtures/round086-original-ticket-kunit.c").read_bytes()
    # Source audit is not runtime lockdep: exact source contains one copy,
    # one CRC, both between unlock and reacquire; no allocation/callback API.
    source = files[STAGE + "/zswap-original-ticket.c"].decode()
    require("spin_trylock_irqsave(&broker->lock, *flags)" in source and
            "spin_lock_irqsave(&broker->lock, *flags)" in source and
            "spin_unlock_irqrestore(&broker->lock, flags)" in source,
            "actual kernel adapter missing")
    sequence = ("ticket_unlock(broker, flags);\n"
                "\t/* Exclusive producer lease pins storage; revoke/close may invalidate\n"
                "\t * it during copy but cannot recycle it. No partial reader exposure. */\n"
                "\tmemcpy(destination, source, length);\n"
                "\tcrc = swapz_crc32c_bytes(destination, length);\n"
                "\terror = ticket_lock(broker, &flags, false);")
    require(source.count(sequence) == 1, "copy/CRC critical-section boundary drift")
    require(not re.search(r"\b(?:kmalloc|kzalloc|kcalloc|vmalloc|schedule|"
                          r"cond_resched|wait_event|mutex_lock|msleep)\s*\(", source),
            "unexpected kernel allocation/sleep call")
    return files, negatives


def stage(linux, mode, manifest):
    files, negatives = stage_plan(linux)
    existing = {"lib/kunit/Makefile", "lib/kunit/Kconfig"}
    pristine = mode != "verify-stage"
    if pristine:
        require(not git(linux, "status", "--porcelain", "--untracked-files=all"),
                "original checkout not pristine")
        require(not (linux / STAGE).exists(), "stage directory exists")
    if mode == "stage":
        (linux / STAGE).mkdir()
        for path, data in files.items():
            (linux / path).write_bytes(data)
    if mode in ("stage", "verify-stage"):
        for path, expected in files.items():
            require((linux / path).read_bytes() == expected, "staged postimage drift " + path)
        changed = set(git(linux, "diff", "--name-only").decode().splitlines())
        added = set(git(linux, "ls-files", "--others", "--exclude-standard").decode().splitlines())
        require(changed == existing and added == set(files) - existing,
                "unexpected original tree changes")
        for path, expected in ORIGINAL.items():
            if path not in existing:
                require(blob((linux / path).read_bytes()) == expected,
                        "untouched original drift " + path)
    report = {"mode": mode, "linux_head": LINUX,
              "product_head": git(ROOT, "rev-parse", "HEAD").decode().strip(),
              "product_blobs": PRODUCT, "original_blobs": ORIGINAL,
              "negative_stage_plans": negatives,
              "postimages": {path: identity(data) for path, data in files.items()},
              "source_authentication": 0, "phase_a": "BLOCKED"}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(report, indent=2) + "\n")
    print(f"R086_STAGE_{mode.upper()} PASS actual pinned files={len(files)} negative={negatives}",
          flush=True)


def verify_build(build, output):
    config = (build / ".config").read_text()
    for line in CONFIG:
        require(line in config.splitlines(), "effective-config " + line)
    for enabled in ("CONFIG_SWAP=y", "CONFIG_ZSWAP=y", "CONFIG_KUNIT_ALL_TESTS=y"):
        require(enabled not in config.splitlines(), "unexpected enabled " + enabled)
    image = build / "linux"
    require(image.is_file() and image.stat().st_size > 0, "missing UML binary")
    symbols = subprocess.run(["nm", str(image)], capture_output=True,
                             text=True, check=True).stdout
    for name in ("swapz_ticket_reserve", "swapz_ticket_seal", "swapz_ticket_claim",
                 "swapz_ticket_revoke", "swapz_ticket_close", "swapz_ticket_put",
                 "swapz_crc32c_bytes", "crc32c", *CASES):
        require(re.search(r"(?m)^[0-9a-fA-F]+\s+[tT]\s+" + re.escape(name) + r"$", symbols),
                "missing actual built symbol " + name)
    # Stream binary hash rather than retaining the entire kernel image.
    with image.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    output.write_text(json.dumps({"kernel_sha256": digest,
                                  "config_sha256": hashlib.sha256(config.encode()).hexdigest(),
                                  "effective_config": CONFIG, "symbols_verified": True,
                                  "kernel_bytes": image.stat().st_size}, indent=2) + "\n")
    print("R086_BUILD_IDENTITY PASS actual broker+CRC+six case symbols " + digest, flush=True)


def verify_native(result, kernel_log, output):
    document = json.loads(result.read_text())
    pending = [document]
    matches = []
    while pending:
        node = pending.pop()
        require(isinstance(node, dict), "native JSON node")
        if node.get("name") == SUITE:
            matches.append(node)
        children = node.get("sub_groups", [])
        require(isinstance(children, list), "native JSON child list")
        pending.extend(children)
    require(len(matches) == 1, "native JSON suite missing or duplicate")
    suite = matches[0]
    cases = suite.get("test_cases", [])
    require(len(cases) == len(CASES) and
            all(case.get("status") == "PASS" for case in cases) and
            {case.get("name") for case in cases} == set(CASES),
            "native JSON cases not exact PASS")
    counts = {"tests": len(CASES), "passed": len(CASES), "failed": 0,
              "skipped": 0, "crashed": 0, "errors": 0}
    for node in (suite, document):
        require(all(type(node.get("misc", {}).get(k)) is int and node["misc"][k] == v
                    for k, v in counts.items()), "native JSON counts")
    ktap = kernel_log.read_text(errors="replace")
    require(ktap.count("# Subtest: " + SUITE) == 1, "native KTAP suite count")
    for name in (*CASES, SUITE):
        require(len(re.findall(r"(?m)^\s*ok\s+\d+\s+(?:-\s+)?" +
                               re.escape(name) + r"\s*$", ktap)) == 1,
                "native KTAP result " + name)
    require(not re.search(r"(?i)kernel panic|KASAN:|UBSAN:|BUG:|WARNING:|"
                          r"not ok\s+\d+|spinlock.*(?:recursion|bad magic)|"
                          r"sleeping function called from invalid context", ktap),
            "native kernel warning/BUG/failure")
    sizes = re.findall(r"R086_SIZEOF broker=(\d+) slot=(\d+) ref=(\d+) key=(\d+) index=(\d+)", ktap)
    require(len(sizes) == 1, "native sizeof marker")
    output.write_text(json.dumps({"status": "PASS_TEST_ONLY_KERNEL_ADAPTER",
                                  "cases": list(CASES), "counts": counts,
                                  "sizeof": dict(zip(("broker", "slot", "ref", "key", "index"),
                                                     map(int, sizes[0]))),
                                  "actual_kernel_adapter": True,
                                  "actual_selected_dm_claim": False,
                                  "source_mapped_authenticated": 0, "phase_a": "BLOCKED"},
                                 indent=2) + "\n")
    print("PASS R086_ACTUAL_BROKER_KERNEL_ADAPTER JSON_KTAP=6/6 "
          "SMP_IRQSAVE=YES CRC=YES SELECTED_DM=UNPROVEN AUTH0", flush=True)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="mode", required=True)
    for mode in ("verify-only", "stage", "verify-stage"):
        command = commands.add_parser(mode)
        command.add_argument("--linux-root", type=Path, required=True)
        command.add_argument("--manifest", type=Path, required=True)
    command = commands.add_parser("verify-build")
    command.add_argument("--build", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("verify-native")
    command.add_argument("--result", type=Path, required=True)
    command.add_argument("--kernel-log", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "verify-build":
        verify_build(args.build, args.output)
    elif args.mode == "verify-native":
        verify_native(args.result, args.kernel_log, args.output)
    else:
        stage(args.linux_root.resolve(), args.mode, args.manifest)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, TypeError,
            subprocess.SubprocessError) as error:
        print("ROUND086_AGENT11_FIRST_ERROR " + str(error)[:300], file=sys.stderr)
        sys.exit(2)
