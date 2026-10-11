#!/usr/bin/env python3
"""No-device benchmark approval contract; refuse unsanctioned live VM work.

--show-statement prints the exact proposed scope for an independent VM owner
to review; printing it does NOT confer authorization. --check requires an
identical independently supplied SWAPZ_BENCH_AUTHORIZATION in the environment.
VM detection only establishes a guest indication; it does not authenticate a
VM label, passthrough devices or isolation. Never launches block operations.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "swapz_benchmark_authorization_planner", HERE / "streaming-benchmark-plan.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("missing benchmark admission planner")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)

SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
VM = re.compile(r"disposable-[A-Za-z0-9._-]{1,60}\Z")


def _number(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    if re.fullmatch(r"(?:0|[1-9][0-9]{0,9})", raw) is None:
        raise ValueError(f"{name} must be a decimal integer")
    return int(raw)


def proposal(env: Mapping[str, str]) -> tuple[str, dict[str, object]]:
    vm = env.get("SWAPZ_BENCH_VM_ID", "")
    source = env.get("SWAPZ_BENCH_SOURCE_SHA", "")
    module = env.get("SWAPZ_BENCH_MODULE_SHA256", "")
    path = env.get("SWAPZ_BENCH_MODULE_PATH", "")
    if VM.fullmatch(vm) is None:
        raise ValueError("SWAPZ_BENCH_VM_ID must be a disposable-<label> VM")
    if SHA.fullmatch(source) is None or DIGEST.fullmatch(module) is None:
        raise ValueError("source SHA and selected module SHA-256 must be full lowercase digests")
    if not path.startswith("/") or "\n" in path or "\r" in path:
        raise ValueError("selected module path must be a nonempty absolute path")

    backend = env.get("SWAPZ_BENCH_BACKEND", "null_blk")
    bandwidth = _number(env, "SWAPZ_BENCH_MBPS", 20)
    latency = _number(env, "SWAPZ_BENCH_LATENCY_NS", 500000)
    runtime = _number(env, "SWAPZ_BENCH_RUNTIME", 3)
    qd = _number(env, "SWAPZ_BENCH_QD", 64)
    compress = _number(env, "SWAPZ_BENCH_COMPRESS", 50)
    read_iops = _number(env, "SWAPZ_BENCH_READ_IOPS", 100)
    discard = _number(env, "SWAPZ_BENCH_DISCARD", 0)
    retain = _number(env, "SWAPZ_BENCH_KEEP_ARTIFACTS", 0)
    if not 1 <= read_iops <= 2000:
        raise ValueError("read IOPS target must be 1..2000")
    if discard not in (0, 1) or retain not in (0, 1):
        raise ValueError("discard and retain options must be exactly 0 or 1")
    if backend != "null_blk":
        raise ValueError("benchmark execution only supports null_blk, never NBD")
    if bandwidth > 0 and discard:
        raise ValueError("lower DISCARD must be off for throttled null_blk")

    p = planner.plan(
        backend=backend, bandwidth=bandwidth, latency_ns=latency,
        strategies=env.get("SWAPZ_BENCH_STRATEGIES",
                           "immediate opportunistic staged"),
        batches=env.get("SWAPZ_BENCH_BATCHES", "auto"),
        repeats=1, runtime=runtime, write_qd=qd, compress=compress)
    if p["qualified_winner"] is not None or not p["backend_runnable"]:
        raise ValueError("benchmark planner admission refused execution")
    cases = ",".join(
        f"{x['strategy']}:{x['batch_kib']}KiB" for x in p["cases"])
    # Exact cases, not merely a broad batch-size ceiling: changing the
    # strategy subset, order or size changes the required approval statement.
    statement = (
        "I AUTHORIZE swapz V2.2 diagnostic benchmark only on disposable VM "
        f"{vm} with source {source} and selected module SHA-256 {module}; "
        f"cases in order [{cases}]; backend=null_blk "
        f"bandwidth={bandwidth}MiB/s latency={latency}ns "
        f"runtime={runtime}s/case writer_qd={qd} "
        f"reader_iops_target={read_iops} compressibility={compress}% "
        f"lower_discard={discard} keep_artifacts={retain}; "
        "permitted operations are modprobe null_blk nr_devices=0, optional "
        "mount/unmount of this run's configfs, creation and shutdown of "
        "one test-owned memory-backed 256MiB null_blk instance, creation "
        "and ordinary removal of one test-owned swapz DM target per case, "
        "fio and dd direct 4KiB read/write/verification I/O only within "
        "each owned 32MiB logical target, explicit fsync, DM status "
        "queries, and owned temporary artifact creation/removal; "
        "not authorized are physical storage, NBD, swap activation, "
        "loading/unloading dm_swapz, forced removal, host reboot, "
        "or destructive external cleanup."
    )
    return statement, p


def vm_indication(command: object = subprocess.run) -> str:
    try:
        result = command(
            ["systemd-detect-virt", "--vm"], capture_output=True, text=True,
            timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"cannot confirm disposable-VM environment: {exc}") from exc
    kind = result.stdout.strip()
    if (result.returncode != 0 or
            re.fullmatch(r"[A-Za-z0-9_-]{1,32}", kind) is None or
            kind.lower() in ("none", "docker", "podman", "lxc", "wsl")):
        raise ValueError("systemd-detect-virt did not establish a VM guest")
    return kind


def check(env: Mapping[str, str], command: object = subprocess.run) -> str:
    statement, _ = proposal(env)
    # Do not log the supplied authorization; failures return only the reason.
    if env.get("SWAPZ_BENCH_AUTHORIZATION", "") != statement:
        raise ValueError("explicit exact benchmark authorization is missing or mismatched")
    vm_indication(command)
    return "BENCH_LIVE_SCOPE=AUTHORIZED_STATEMENT_AND_VM_GUEST_INDICATION_ONLY"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--show-statement", action="store_true",
                        help="print proposed scope; NEVER grants authorization")
    action.add_argument("--check", action="store_true",
                        help="fail closed on missing exact approval and VM guest indication")
    args = parser.parse_args()
    try:
        if args.show_statement:
            statement, _ = proposal(os.environ)
            print(statement)
            print("PROPOSAL_ONLY_NO_AUTHORIZATION_OR_DEVICE_OPERATIONS", file=sys.stderr)
        else:
            print(check(os.environ))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
