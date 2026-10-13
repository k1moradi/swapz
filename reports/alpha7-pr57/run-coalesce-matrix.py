#!/usr/bin/env python3
"""Sequential, counterbalanced PR #57 coalesce_ms QD1/QD8 experiment."""

import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path("/root/swapz-pr57-validation/evidence/sustained")
RUNNER = ROOT / "run-sustained-coalesce-trial.py"
OUTPUT = ROOT / "coalesce-matrix.jsonl"

# Rotate order by repetition while keeping each (delay, QD) pair represented
# once per repetition. Each child performs one complete create/run/verify/
# teardown cycle. A nonzero child status stops the sequence immediately.
orders = [
    [(1, 1), (4, 8), (2, 1), (1, 8), (4, 1), (2, 8)],
    [(2, 8), (4, 1), (1, 8), (2, 1), (4, 8), (1, 1)],
    [(4, 8), (1, 1), (4, 1), (2, 8), (1, 8), (2, 1)],
]


def main():
    for rep, order in enumerate(orders, 1):
        for coalesce_ms, qd in order:
            label_suffix = f"coalesce-{coalesce_ms}ms"
            command = [
                "python3", str(RUNNER),
                "--candidate", "pr57-b1",
                "--rep", str(rep),
                "--qd", str(qd),
                "--read-pct", "20",
                "--warmup", "10",
                "--seconds", "30",
                "--coalesce-ms", str(coalesce_ms),
            ]
            start = time.time()
            child = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            row = {
                "candidate": "pr57-b1",
                "coalesce_ms": coalesce_ms,
                "qd": qd,
                "read_pct": 20,
                "rep": rep,
                "command": command,
                "rc": child.returncode,
                "elapsed_wall_s": time.time() - start,
                "output": child.stdout,
                "recorded_at": time.time(),
            }
            with OUTPUT.open("a") as stream:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
            print(json.dumps({"candidate": row["candidate"], "coalesce_ms": coalesce_ms, "qd": qd, "rep": rep, "rc": child.returncode, "tail": child.stdout[-500:]}, sort_keys=True), flush=True)
            if child.returncode != 0:
                print("STOPPED: child trial failed; inspect owned resource state before continuing", file=sys.stderr)
                return child.returncode
    print("COALESCE_MATRIX_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
