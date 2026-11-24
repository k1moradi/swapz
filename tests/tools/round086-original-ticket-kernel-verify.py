#!/usr/bin/env python3
"""Exact native-only stage and result gate for the actual disabled broker."""
import argparse
import hashlib
import json
import os
import shlex
import shutil
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
    "tests/runtime/native/fixtures/round086-original-ticket-kunit.c": "bdfb9fa138ba7acf2e20d8b49950b669da0e6e55"
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
    "tools/testing/kunit/kunit_json.py": "80fa4e354a17afde99c92666a71b0c7ca237a594",
    "tools/testing/kunit/qemu_configs/x86_64.py": "4a6bf4e048f5b05c889e3b9b03046f14cc9b0bcc",
    "tools/testing/kunit/kunit_kernel.py": "58557c47d85f696f82e165df58fa905094e45f5c",
    "tools/testing/kunit/qemu_config.py": "b1fba9016eed00d010c853f2910c9624e01d4af5",
    "arch/x86/Kconfig": "58dce0b66179b6039c4ec9cc4273194c8e382b77",
    "arch/x86/kernel/smpboot.c": "ba01a9e919b7840a0e625a39de0d473f222b3b64",
    "arch/x86/include/asm/spinlock.h": "934632b78d09c07f5337982b238db138c640738b",
    "arch/x86/include/asm/irqflags.h": "6f25de05ed58f59ba022f94146fa3ac2fedf49fc",
    "arch/x86/include/asm/qspinlock.h": "25a1919542d9d5222f44befffd08ed03d508b83d",
    "kernel/smp.c": "89a30d831ef5320561c676a4e69018d42d02eebb",
    "include/linux/timekeeping.h": "efa9442aaeef44a3b7ff88f247f616419b243553",
    "include/linux/ktime.h": "f247e564602fcc0614d8f1cf08e340dfa280c381"
}
STAGE = "lib/kunit/swapz-round086"
SUITE = "swapz_round086_original_ticket"
CASES = (
    "r086_capacity", "r086_irq_and_contention", "r086_seal_claim",
    "r086_revoke_close", "r086_generation_refs", "r086_copy_failures",
)
CONFIG = (
    "CONFIG_KUNIT=y", "CONFIG_X86_64=y", "CONFIG_SMP=y", "CONFIG_NR_CPUS=2",
    "CONFIG_SERIAL_8250=y", "CONFIG_SERIAL_8250_CONSOLE=y",
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


LAUNCHER = "tools/testing/kunit/kunit_kernel.py"
ACCEL_ANCHOR = (b"\t\t\t\t'-accel', 'kvm',\n"
                b"\t\t\t\t'-accel', 'hvf',\n"
                b"\t\t\t\t'-accel', 'tcg',\n")
ACCEL_TCG = b"\t\t\t\t'-accel', 'tcg,thread=multi',\n"
QEMU_ARGS = ["-machine", "pc", "-smp", "2", "-nic", "none",
             "-L", "/usr/share/qemu"]
FIRMWARE = Path("/usr/share/qemu/qboot.rom")


def launcher_postimage(data):
    require(data.count(ACCEL_ANCHOR) == 1, "TCG launcher anchor")
    return data.replace(ACCEL_ANCHOR, ACCEL_TCG, 1)


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
    launcher = originals[LAUNCHER]
    for changed in (launcher.replace(ACCEL_ANCHOR, b"", 1),
                    launcher + ACCEL_ANCHOR):
        try:
            launcher_postimage(changed)
        except RuntimeError:
            negatives += 1
        else:
            raise RuntimeError("accepted negative TCG launcher plan")
    files = {
        LAUNCHER: launcher_postimage(launcher),
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
    existing = {"lib/kunit/Makefile", "lib/kunit/Kconfig", LAUNCHER}
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
    print(f"R087_STAGE_{mode.upper()} PASS actual pinned files={len(files)} negative={negatives}",
          flush=True)


def verify_build(build, output):
    config = (build / ".config").read_text()
    for line in CONFIG:
        require(line in config.splitlines(), "effective-config " + line)
    for enabled in ("CONFIG_SWAP=y", "CONFIG_ZSWAP=y", "CONFIG_KUNIT_ALL_TESTS=y"):
        require(enabled not in config.splitlines(), "unexpected enabled " + enabled)
    image = build / "arch/x86/boot/bzImage"
    vmlinux = build / "vmlinux"
    require(image.is_file() and image.stat().st_size > 0 and vmlinux.is_file(),
            "missing x86 bzImage/vmlinux")
    symbols = subprocess.run(["nm", str(vmlinux)], capture_output=True,
                             text=True, check=True).stdout
    for name in ("swapz_ticket_reserve", "swapz_ticket_seal", "swapz_ticket_claim",
                 "swapz_ticket_revoke", "swapz_ticket_close", "swapz_ticket_put",
                 "swapz_crc32c_bytes", "crc32c", *CASES):
        require(re.search(r"(?m)^[0-9a-fA-F]+\s+[tT]\s+" + re.escape(name) + r"$", symbols),
                "missing actual built symbol " + name)
    # Stream binary hash rather than retaining the entire kernel image.
    with image.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    with vmlinux.open("rb") as binary:
        vmlinux_digest = hashlib.file_digest(binary, "sha256").hexdigest()
    output.write_text(json.dumps({"kernel_sha256": digest,
                                  "vmlinux_sha256": vmlinux_digest,
                                  "config_sha256": hashlib.sha256(config.encode()).hexdigest(),
                                  "effective_config": CONFIG, "symbols_verified": True,
                                  "kernel_bytes": image.stat().st_size,
                                  "backend": "x86_64 QEMU TCG only",
                                  "qemu_args": QEMU_ARGS}, indent=2) + "\n")
    print("R087_BUILD_IDENTITY PASS actual broker+CRC+six case symbols " + digest, flush=True)


def qemu_preflight(output):
    require(os.geteuid() != 0, "QEMU runtime must be unprivileged")
    for tool in ("gcc", "make", "bc", "bison", "flex", "ld", "nm", "python3",
                 "qemu-system-x86_64"):
        require(shutil.which(tool), "missing build/runtime tool " + tool)
    require(FIRMWARE.is_file() and FIRMWARE.stat().st_size > 0,
            "qboot.rom absent from explicit QEMU firmware directory")
    executable = shutil.which("qemu-system-x86_64")
    version = subprocess.run([executable, "--version"], text=True,
                             capture_output=True, check=True, timeout=10).stdout.splitlines()[0]
    # QMP proves the exact TCG machine and two instantiated vCPUs, and
    # firmware loading succeeds before the expensive kernel build.
    command = [executable, "-nodefaults", "-m", "1024", "-accel", "tcg,thread=multi",
               "-bios", "qboot.rom", "-display", "none", "-serial", "none",
               "-monitor", "none", "-qmp", "stdio", "-S", *QEMU_ARGS]
    requests = [{"execute": "qmp_capabilities", "id": "cap"},
                {"execute": "query-cpus-fast", "id": "cpus"},
                {"execute": "query-kvm", "id": "kvm"},
                {"execute": "quit", "id": "quit"}]
    completed = subprocess.run(command, text=True, capture_output=True,
                               input="\n".join(map(json.dumps, requests)) + "\n", timeout=30)
    # Raw child output stays in the private artifact, not arbitrary console.
    output.with_suffix(".stdout.log").write_text(completed.stdout)
    output.with_suffix(".stderr.log").write_text(completed.stderr)
    require(completed.returncode == 0, "QEMU TCG/firmware preflight exit " +
            str(completed.returncode))
    replies = [json.loads(line) for line in completed.stdout.splitlines() if line.startswith("{")]
    require(not any("error" in reply for reply in replies), "QEMU QMP error")
    by_id = {reply.get("id"): reply.get("return") for reply in replies if "id" in reply}
    require(isinstance(by_id.get("cpus"), list) and
            {cpu["cpu-index"] for cpu in by_id["cpus"]} == {0, 1}, "QEMU preflight CPU count")
    require(by_id.get("kvm", {}).get("enabled") is False, "QEMU KVM unexpectedly enabled")
    require(all(name in by_id for name in ("cap", "cpus", "kvm", "quit")), "QMP incomplete")
    output.write_text(json.dumps({"status": "PASS", "qemu_version": version,
                                  "firmware": identity(FIRMWARE.read_bytes()),
                                  "preflight_command": command, "vcpu_count": 2,
                                  "kvm_enabled": False, "runtime_euid_nonzero": True},
                                 indent=2) + "\n")
    print("R087_QEMU_PREFLIGHT PASS TCG_ONLY qboot.rom two_vcpus rootless", flush=True)


def first_diagnostic(raw, runner, phase, exit_code):
    # Earliest meaningful raw guest line wins over the parser's later
    # generic "no KTAP" summary. Only classified excerpts reach console.
    for text in (raw, runner):
        for line in text.splitlines():
            if "SMP is not supported with PTRACE userspace." in line:
                return "SMP is not supported with PTRACE userspace."
            match = re.search(r"\bnot ok\s+\d+\s+(?:-\s+)?(r086_\w+|" + SUITE + r")", line)
            if match:
                return match.group(0)
            match = re.search(r"(?i)(Kernel panic|KASAN:|UBSAN:|BUG:|WARNING:|"
                              r"sleeping function called from invalid context|"
                              r"spinlock.*(?:recursion|bad magic)|"
                              r"ROUND087_AGENT11_FIRST_ERROR|fatal error:|undefined reference|error:|^E:|"
                              r"could not load PC BIOS|failed to initialize|"
                              r"timed out|no KTAP)", line)
            if match:
                # Strip absolute paths/control characters and cap excerpt.
                excerpt = re.sub(r"[\x00-\x1f\x7f]", " ", line[match.start():])
                excerpt = re.sub(r"(?<!\w)/(?:[^\s:]+/)*[^\s:]+", "<path>", excerpt)
                return excerpt[:240]
    return f"{phase}: no classified diagnostic (exit {exit_code})"


def diagnostic_regressions():
    examples = (
        ("SMP is not supported with PTRACE userspace.\n", "error: no KTAP", "boot", 1,
         "SMP is not supported with PTRACE userspace."),
        ("", "error: no KTAP", "boot", 1, "error: no KTAP"),
        ("KTAP version 1\n    not ok 2 r086_irq_and_contention\n", "error: KUnit failed",
         "boot", 1, "not ok 2 r086_irq_and_contention"),
        ("BUG: sleeping function called from invalid context\nnot ok 2 r086_irq_and_contention",
         "error: no KTAP", "boot", 1, "BUG: sleeping function called from invalid context"),
        ("", "", "boot", 124, "boot: no classified diagnostic (exit 124)"),
        ("", "fatal error: /private/build/input.h", "build", 2, "fatal error: <path>"),
        ("", "ROUND087_AGENT11_FIRST_ERROR qboot.rom absent", "qemu-preflight", 2,
         "ROUND087_AGENT11_FIRST_ERROR qboot.rom absent"),
    )
    for raw, runner, phase, code, expected in examples:
        require(first_diagnostic(raw, runner, phase, code) == expected,
                "first-diagnostic regression " + expected)
    print(f"R087_DIAGNOSTIC_REGRESSIONS PASS {len(examples)}/{len(examples)}", flush=True)


def record_failure(raw, runner, phase, exit_code, output):
    def read(path):
        return path.read_text(errors="replace") if path.is_file() else ""
    message = first_diagnostic(read(raw), read(runner), phase, exit_code)
    output.write_text(json.dumps({"phase": phase, "exit": exit_code,
                                  "first_error": message}, indent=2) + "\n")
    print("ROUND087_AGENT11_FIRST_ERROR " + message, file=sys.stderr)


def verify_command(run_log, build, output):
    lines = [line[2:] for line in run_log.read_text(errors="replace").splitlines()
             if line.startswith("$ qemu-system-x86_64 ")]
    require(len(lines) == 1, "exact QEMU command missing or duplicate")
    command = shlex.split(lines[0])
    require(command.count("-accel") == 1 and
            command[command.index("-accel") + 1] == "tcg,thread=multi",
            "QEMU command accelerator drift")
    expected = {"-machine": "pc", "-smp": "2", "-nic": "none", "-bios": "qboot.rom",
                "-L": "/usr/share/qemu", "-kernel": str(build / "arch/x86/boot/bzImage")}
    for key, value in expected.items():
        require(command.count(key) == 1 and command[command.index(key) + 1] == value,
                "QEMU command drift " + key)
    require("-nodefaults" in command and "-no-reboot" in command and
            not any(arg in command for arg in ("-enable-kvm", "-drive", "-blockdev",
                                               "-hda", "-net", "-netdev", "-device")),
            "unexpected QEMU device/acceleration")
    output.write_text(json.dumps({"command": command, "tcg_only": True,
                                  "vcpu_count": 2, "disk_network": False}, indent=2) + "\n")


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
    cpus = re.findall(r"R087_CPUS online=(\d+) contender=(\d+) holder=(\d+)", ktap)
    require(len(cpus) == 1, "native cross-CPU contention marker missing")
    online, contender, holder = map(int, cpus[0])
    require(online >= 2 and {contender, holder} == {0, 1},
            "actual online CPU or contention identity mismatch")
    sizes = re.findall(r"R086_SIZEOF broker=(\d+) slot=(\d+) ref=(\d+) key=(\d+) index=(\d+)", ktap)
    require(len(sizes) == 1, "native sizeof marker")
    output.write_text(json.dumps({"status": "PASS_TEST_ONLY_KERNEL_ADAPTER",
                                  "cases": list(CASES), "counts": counts,
                                  "sizeof": dict(zip(("broker", "slot", "ref", "key", "index"),
                                                     map(int, sizes[0]))),
                                  "actual_kernel_adapter": True,
                                  "actual_online_cpus": online,
                                  "contender_cpu": contender, "holder_cpu": holder,
                                  "actual_selected_dm_claim": False,
                                  "source_mapped_authenticated": 0, "phase_a": "BLOCKED"},
                                 indent=2) + "\n")
    print("PASS R087_ACTUAL_BROKER_KERNEL_ADAPTER JSON_KTAP=6/6 "
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
    commands.add_parser("diagnostic-regressions")
    command = commands.add_parser("qemu-preflight")
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("record-failure")
    command.add_argument("--raw", type=Path, required=True)
    command.add_argument("--runner", type=Path, required=True)
    command.add_argument("--phase", required=True)
    command.add_argument("--exit-code", type=int, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("verify-command")
    command.add_argument("--run-log", type=Path, required=True)
    command.add_argument("--build", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "diagnostic-regressions":
        diagnostic_regressions()
    elif args.mode == "qemu-preflight":
        qemu_preflight(args.output)
    elif args.mode == "record-failure":
        record_failure(args.raw, args.runner, args.phase, args.exit_code, args.output)
    elif args.mode == "verify-command":
        verify_command(args.run_log, args.build, args.output)
    elif args.mode == "verify-build":
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
        print("ROUND087_AGENT11_FIRST_ERROR " + str(error)[:300], file=sys.stderr)
        sys.exit(2)
