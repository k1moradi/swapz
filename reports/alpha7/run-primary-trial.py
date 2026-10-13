#!/usr/bin/env python3
"""Run one guarded 1024-page swapz primary-I/O comparison trial.

This research helper is bound to the task-owned configfs null_blk instance
nullb_swapz3_a7_0e199159. It does not load modules, select arbitrary backing
devices, or attempt cleanup after a failed test. A failed/ambiguous trial
leaves its exact owned mapping in place for inspection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


NULLB = "nullb_swapz3_a7_0e199159"
CONFIG = Path("/sys/kernel/config/nullb") / NULLB
SYSBLOCK = Path("/sys/block") / NULLB
DEVICE = Path("/dev") / NULLB
SECTORS = 8192
PAGES = 1024
EXPECTED_LOGICAL_BYTES = PAGES * 4096
EVIDENCE = Path("/tmp/swapz-v3-alpha7-evidence-0e199159")


class TrialError(RuntimeError):
    pass


def command(argv: list[str], *, input_text: str | None = None,
            timeout: float = 60) -> dict[str, object]:
    start = time.monotonic_ns()
    try:
        cp = subprocess.run(argv, input=input_text, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TrialError(f"timeout after {timeout}s: {argv!r}; output={exc.stdout!r} {exc.stderr!r}") from exc
    end = time.monotonic_ns()
    return {
        "argv": argv,
        "exit_code": cp.returncode,
        "start_monotonic_ns": start,
        "end_monotonic_ns": end,
        "elapsed_ns": end - start,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
    }


def checked(argv: list[str], *, input_text: str | None = None,
            timeout: float = 60) -> dict[str, object]:
    result = command(argv, input_text=input_text, timeout=timeout)
    if result["exit_code"] != 0:
        raise TrialError(f"command failed rc={result['exit_code']}: {argv!r}; stderr={result['stderr']!r}")
    return result


def text(result: dict[str, object]) -> str:
    return str(result["stdout"]).strip()


def dm(*args: str, timeout: float = 30) -> dict[str, object]:
    return checked(["sudo", "-n", "dmsetup", *args], timeout=timeout)


def no_devices(output: str) -> bool:
    rows = [line.strip() for line in output.splitlines()
            if line.strip() and line.strip() != "No devices found"]
    return not rows


def parse_status(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for token in line.split()[3:]:
        if "=" in token:
            k, v = token.split("=", 1)
            fields[k] = v
    return fields


def read_stat() -> list[int]:
    return [int(x) for x in (SYSBLOCK / "stat").read_text().split()]


def stat_summary(values: list[int]) -> dict[str, int]:
    if len(values) < 17:
        raise TrialError(f"unexpected block stat field count {len(values)}")
    return {
        "read_requests": values[0], "read_sectors_512": values[2],
        "write_requests": values[4], "write_sectors_512": values[6],
        "in_flight": values[8], "io_ticks_ms": values[9],
        "weighted_io_ticks_ms": values[10], "discard_requests": values[11],
        "discard_sectors_512": values[13], "flush_requests": values[15],
    }


def parse_kv(text_value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for token in text_value.split():
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = value
    return result


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise TrialError(message)


def capture_kernel_log() -> str:
    return text(checked(["sudo", "-n", "dmesg", "--time-format", "iso"], timeout=10))


def power_cycle_nullb() -> dict[str, object]:
    require(CONFIG.is_dir() and SYSBLOCK.is_dir(), "owned null_blk config/device absent")
    require(not any((SYSBLOCK / "holders").iterdir()), "null_blk still has holders; refusing power cycle")
    require(no_devices(text(dm("ls", "--noheadings"))), "DM mappings remain; refusing null_blk power cycle")
    require((CONFIG / "memory_backed").read_text().strip() == "1", "owned null_blk lost memory_backed=1")
    before = read_stat()
    off = checked(["sudo", "-n", "tee", str(CONFIG / "power")], input_text="0\n")
    deadline = time.monotonic() + 5
    while SYSBLOCK.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    require(not SYSBLOCK.exists(), "null_blk device did not disappear after power=0")
    on = checked(["sudo", "-n", "tee", str(CONFIG / "power")], input_text="1\n")
    deadline = time.monotonic() + 10
    while not SYSBLOCK.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    require(SYSBLOCK.exists(), "null_blk device did not return after power=1")
    require((CONFIG / "power").read_text().strip() == "1", "null_blk power did not return to 1")
    require((CONFIG / "memory_backed").read_text().strip() == "1", "null_blk memory_backed changed")
    require((CONFIG / "mbps").read_text().strip() == "20", "null_blk bandwidth changed")
    require((CONFIG / "completion_nsec").read_text().strip() == "500000",
            "null_blk latency changed")
    return {"before_stat": before, "power_off": off, "power_on": on,
            "after_stat": read_stat(), "dev": (SYSBLOCK / "dev").read_text().strip()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--implementation", required=True,
                    choices=["alpha7", "alpha6", "v22"])
    ap.add_argument("--bulk", type=int, choices=[0, 1, 2], default=0)
    ap.add_argument("--repetition", type=int, required=True)
    ap.add_argument("--module", type=Path, required=True)
    ap.add_argument("--module-sha256", required=True)
    ap.add_argument("--module-srcversion", required=True)
    ap.add_argument("--probe", type=Path, required=True)
    ap.add_argument("--verifier", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    args.output.mkdir(parents=True, exist_ok=False)
    result: dict[str, object] = {
        "implementation": args.implementation,
        "lower_bulk": args.bulk if args.implementation != "v22" else None,
        "repetition": args.repetition,
        "module_path": str(args.module),
        "module_sha256": hash_file(args.module),
        "module_srcversion_expected": args.module_srcversion,
        "probe_sha256": hash_file(args.probe),
        "verifier_sha256": hash_file(args.verifier),
        "kernel_release": os.uname().release,
        "start_wall_time": time.time(),
        "phase": "preflight",
    }
    (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")
    try:
        require(result["module_sha256"] == args.module_sha256,
                "selected module SHA-256 mismatch")
        require((CONFIG / "size").read_text().strip() == "40", "unexpected null_blk size")
        require((CONFIG / "memory_backed").read_text().strip() == "1", "null_blk is not memory_backed")
        require((CONFIG / "blocksize").read_text().strip() == "512", "unexpected logical block size")
        require((CONFIG / "mbps").read_text().strip() == "20", "unexpected null_blk bandwidth")
        require((CONFIG / "completion_nsec").read_text().strip() == "500000", "unexpected null_blk latency")
        require((CONFIG / "power").read_text().strip() == "1", "null_blk is powered off")
        require(DEVICE.exists() and DEVICE.is_block_device(), "owned null_blk node absent or not a block device")
        st = os.stat(DEVICE)
        dev = (SYSBLOCK / "dev").read_text().strip()
        require(f"{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}" == dev,
                "null_blk node major/minor does not match sysfs")
        require(not any((SYSBLOCK / "holders").iterdir()), "unexpected null_blk holder")
        mounted = command(["findmnt", "-rn", "-S", str(DEVICE)])
        require(mounted["exit_code"] in (0, 1), "findmnt failed while checking null_blk mounts")
        require(not text(mounted), "owned null_blk is mounted")
        swaps = Path("/proc/swaps").read_text().splitlines()[1:]
        require(all(row.split()[0] != str(DEVICE) for row in swaps), "owned null_blk is active swap")
        dm_before = text(dm("ls", "--noheadings"))
        require(no_devices(dm_before), f"unexpected DM mapping before trial: {dm_before!r}")
        require(Path("/sys/module/dm_swapz/srcversion").read_text().strip()
                == args.module_srcversion, "loaded dm_swapz source version mismatch")
        require(not Path("/sys/module/sv3_queue_probe").exists(),
                "test BIO helper is already loaded")
        target_type = "swapz" if args.implementation == "v22" else "swapz3"
        targets = text(dm("targets"))
        require(any(line.split() and line.split()[0] == target_type
                    for line in targets.splitlines()), f"target {target_type} not registered")

        tag = f"{args.implementation}-b{args.bulk}-r{args.repetition}"
        name = f"swapz-a7-primary-{tag}"
        uuid = f"SWZ-A7-PRIMARY-{args.implementation.upper()}-B{args.bulk}-R{args.repetition}"
        require(len(uuid) < 128, "DM UUID too long")
        result.update({"target_name": name, "target_uuid": uuid,
                       "backing_device": str(DEVICE), "backing_major_minor": dev,
                       "backing_capacity_bytes": int((SYSBLOCK / "size").read_text()) * 512,
                       "phase": "create"})
        if args.implementation == "v22":
            table = f"0 {SECTORS} swapz {DEVICE} opportunistic 64"
        else:
            table = f"0 {SECTORS} swapz3 {DEVICE} 0 64 0 2 0 0 {args.bulk}"
        result["requested_table"] = table
        (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")
        create = dm("create", name, "--uuid", uuid, "--noudevrules", "--noudevsync",
                    "--table", table)
        result["create"] = create
        actual_uuid = text(dm("info", "-c", "--noheadings", "-o", "uuid", name))
        require(actual_uuid == uuid, f"DM UUID mismatch: {actual_uuid!r}")
        actual_table = text(dm("table", name))
        expected_table = table.replace(str(DEVICE), dev)
        require(actual_table == expected_table,
                f"DM table mismatch actual={actual_table!r} expected={expected_table!r}")
        target_info = text(dm("info", "-c", "--noheadings", "-o",
                              "major,minor,open", name))
        parts = target_info.split(":")
        require(len(parts) == 3 and parts[2] == "0", f"target open count not zero: {target_info!r}")
        dm_path = Path(f"/dev/dm-{parts[1]}")
        require(dm_path.exists() and dm_path.is_block_device(),
                f"verified DM block node absent: {dm_path}")
        dm_st = os.stat(dm_path)
        require((os.major(dm_st.st_rdev), os.minor(dm_st.st_rdev))
                == (int(parts[0]), int(parts[1])),
                "DM block node major/minor does not match the owned mapping")
        result["actual_table"] = actual_table
        result["dm_major_minor_open"] = target_info
        result["target_device"] = str(dm_path)
        result["status_before"] = text(dm("status", name))
        result["backing_stat_before"] = read_stat()
        log_before = capture_kernel_log()
        (args.output / "dmesg-before.txt").write_text(log_before + "\n")
        result["phase"] = "upper-write"
        (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")

        # --noudevrules deliberately suppresses mapper aliases. Use the
        # exact major/minor-verified /dev/dm-N node instead.
        target_path = str(dm_path)
        marker = f"SV3QUEUE begin target={target_path} count={PAGES}"
        begins_before = log_before.count(marker)
        probe = checked(["sudo", "-n", "insmod", str(args.probe),
                         f"target={target_path}", f"count={PAGES}"], timeout=90)
        result["probe_command"] = probe
        log_after_probe = capture_kernel_log()
        (args.output / "dmesg-after-probe.txt").write_text(log_after_probe + "\n")
        lines = log_after_probe.splitlines()
        starts = [i for i, line in enumerate(lines) if marker in line]
        require(len(starts) > begins_before, "no new upper-BIO helper begin marker")
        event_lines = []
        for line in lines[starts[-1]:]:
            if "SV3QUEUE " in line:
                event_lines.append(line)
                if "SV3QUEUE done " in line:
                    break
        event_text = "\n".join(event_lines)
        require(f"SV3QUEUE submitted={PAGES} " in event_text,
                f"missing complete submission marker: {event_text!r}")
        require(f"SV3QUEUE done submitted={PAGES} completed={PAGES} errors=0" in event_text,
                f"upper BIO completion/status count failed: {event_text!r}")
        result["probe_kernel_events"] = event_lines
        helper_unload = checked(["sudo", "-n", "rmmod", "sv3_queue_probe"], timeout=20)
        result["probe_module_unload"] = helper_unload
        require(not Path("/sys/module/sv3_queue_probe").exists(),
                "test BIO helper remained loaded after ordinary rmmod")
        result["status_after_write"] = text(dm("status", name))
        result["backing_stat_after_write"] = read_stat()
        fields = parse_status(str(result["status_after_write"]))
        result["status_fields_after_write"] = fields
        if args.implementation != "v22":
            require(int(fields.get("logical_write", -1)) == EXPECTED_LOGICAL_BYTES,
                    f"logical write bytes mismatch: {fields.get('logical_write')}")
            require(fields.get("failed") == "0" and fields.get("error") == "0",
                    f"V3 target failed after write: {fields}")
            require(fields.get("compressed") == "819" and fields.get("raw") == "205",
                    f"expected 819 compressed/205 raw; got {fields.get('compressed')}/{fields.get('raw')}")
            require(int(fields.get("write_submitted", -1)) ==
                    int(fields.get("physical_write", -2)),
                    "V3 completed and submitted lower write counters differ")
        before_stat = stat_summary(result["backing_stat_before"])
        after_stat = stat_summary(result["backing_stat_after_write"])
        deltas = {
            "read_requests": after_stat["read_requests"] - before_stat["read_requests"],
            "read_sectors_512": after_stat["read_sectors_512"] - before_stat["read_sectors_512"],
            "write_requests": after_stat["write_requests"] - before_stat["write_requests"],
            "write_sectors_512": after_stat["write_sectors_512"] - before_stat["write_sectors_512"],
            "flush_requests": after_stat["flush_requests"] - before_stat["flush_requests"],
        }
        result["backing_deltas_after_write"] = deltas
        require(after_stat["in_flight"] == 0, "lower null_blk still has in-flight requests")
        result["phase"] = "readback"
        verify = checked(["sudo", "-n", str(args.verifier), target_path, str(PAGES)], timeout=90)
        result["verification"] = verify
        require("verify_pages=1024 errors=0 result=PASS" in str(verify["stdout"]),
                "byte-exact 1024-page readback failed")
        result["status_after_verify"] = text(dm("status", name))
        result["backing_stat_after_verify"] = read_stat()
        verify_stat = stat_summary(result["backing_stat_after_verify"])
        result["backing_deltas_verification"] = {
            "read_requests": verify_stat["read_requests"] - after_stat["read_requests"],
            "read_sectors_512": verify_stat["read_sectors_512"] - after_stat["read_sectors_512"],
            "write_requests": verify_stat["write_requests"] - after_stat["write_requests"],
            "write_sectors_512": verify_stat["write_sectors_512"] - after_stat["write_sectors_512"],
        }
        (args.output / "dmesg-after.txt").write_text(capture_kernel_log() + "\n")
        require(no_devices(text(dm("ls", "--noheadings"))) is False,
                "owned DM target unexpectedly absent before cleanup")
        result["phase"] = "ordinary-remove"
        (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")
        remove = dm("remove", "--uuid", uuid)
        result["ordinary_remove"] = remove
        require(no_devices(text(dm("ls", "--noheadings"))),
                "DM map remains after ordinary UUID removal")
        require(not any((SYSBLOCK / "holders").iterdir()), "null_blk holder remains after DM removal")
        result["phase"] = "reset-nullb"
        result["nullb_power_cycle"] = power_cycle_nullb()
        result["phase"] = "PASS"
        result["end_wall_time"] = time.time()
        result["status"] = "PASS"
        (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps({"status": "PASS", "implementation": args.implementation,
                          "bulk": args.bulk, "rep": args.repetition,
                          "write_deltas": deltas,
                          "verification": verify["stdout"].strip()}, sort_keys=True))
        return 0
    except Exception as exc:
        result.update({"phase": result.get("phase", "unknown"),
                       "status": "QUARANTINED_OR_FAILED", "error": repr(exc),
                       "end_wall_time": time.time()})
        (args.output / "trial.json").write_text(json.dumps(result, indent=2) + "\n")
        print(f"PRESERVED FOR INSPECTION: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
