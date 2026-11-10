#!/usr/bin/env bash
# Private make-test control: interrupt only our own RAM benchmark creator.
set -Eeuo pipefail
[[ $# == 2 && $1 == --validated-source && $2 =~ ^[a-f0-9]{40}$ && $EUID == 0 ]] || exit 2
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
cd "$ROOT"
python3 -I -B - "$ROOT" "$2" <<'PY'
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

root, source = Path(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location("resources", root / "tests/tools/owned-ram-resources.py")
resources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resources)
check = resources.require
backend = resources.Linux()
check(backend.module() is None, "recovery-control-needs-idle-host")
swaps_before = resources.swap_identity(Path("/proc/swaps").read_bytes())
child = subprocess.Popen([
    "bash", "tests/tools/benchmark-owned-pair.sh", "--validated-source", source,
    "--run-owned-ram-pair", "--profile", "medium", "--retain-ms", "2", "--unpaced",
    "--lower-mbps", "10", "--hw-queue-depth", "1", "--completion-nsec", "1000000"],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True)
pidfd = os.pidfd_open(child.pid)
try:
    deadline = time.monotonic() + 40
    session = claim = None
    while time.monotonic() < deadline and child.poll() is None:
        for candidate in Path("/tmp").glob("swapz-benchmark.????????"):
            temporary_root = os.open("/tmp", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                directory = resources.open_session(temporary_root, candidate.name)
                try:
                    owner, _ = resources.secure_read(directory, ".swapz-benchmark-owner", 128)
                    if owner != f"pid={child.pid}\nsource_sha={source}\n".encode():
                        continue
                    data, _ = resources.secure_read(directory, resources.RECORD)
                    claim = resources.parse_claim(data, resources.identity(os.fstat(directory)), owner)
                    session = candidate
                finally:
                    os.close(directory)
            except (FileNotFoundError, resources.Refused):
                continue
            finally:
                os.close(temporary_root)
        if claim is not None:
            break
        time.sleep(0.02)
    check(claim is not None and child.poll() is None, "producer-proof-not-observed")
    # Freeze this exact child only; never signal inferred device holders.
    signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
    live = subprocess.run(["python3", "-I", "-B", "tests/tools/owned-ram-resources.py", "recover"],
                          capture_output=True, timeout=35)
    check(live.returncode == 0 and (session / resources.RECORD).exists(), "live-creator-not-preserved")
    check(backend.mapper(claim["mapper"]["name"], claim["mapper"]["uuid"]) is not None and
          all(backend.device(d["name"]) is not None for d in claim["devices"]),
          "live-resources-not-preserved")
    signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    check(child.wait(timeout=10) == -signal.SIGKILL, "creator-not-joined")
    # Finite child I/O can still own descriptors after its parent dies. Let it
    # finish naturally; a reference must block recovery rather than be killed.
    deadline = time.monotonic() + 50
    while True:
        recovered = subprocess.run(["bash", "tests/tools/loaded-preflight.sh"],
                                   capture_output=True, timeout=35)
        if recovered.returncode == 0:
            break
        check(time.monotonic() < deadline and any(token in recovered.stderr for token in
              (b"device-process-reference", b"mapper-changed-or-busy")), "abandoned-recovery-refused")
        time.sleep(0.1)
    check(backend.mapper(claim["mapper"]["name"], claim["mapper"]["uuid"]) is None and
          all(backend.device(d["name"]) is None for d in claim["devices"]) and
          backend.module() is None, "owned-resources-remain")
    check(session.is_dir() and (session / "session.log").is_file() and
          not (session / resources.RECORD).exists() and
          not (session / ".swapz-benchmark-complete").exists(), "failure-evidence-not-retained")
    check(resources.swap_identity(Path("/proc/swaps").read_bytes()) == swaps_before,
          "recovery-control-changed-native-swap")
    print("PASS_LOADED_OWNED_RAM_RECOVERY=live_creator_preserved abandoned_released evidence_retained native_swap_unchanged")
finally:
    if child.poll() is None:
        signal.pidfd_send_signal(pidfd, signal.SIGCONT)
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        try:
            child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            # Do not escalate: a stuck owned teardown retains its evidence.
            print("BLOCKED: recovery control child teardown remains incomplete", file=sys.stderr)
    os.close(pidfd)
PY
