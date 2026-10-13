#!/usr/bin/env python3
"""Counterbalanced 30-second mixed-workload V2.2/PR57 read-ratio matrix."""
import json
import subprocess
import time
from pathlib import Path

EVIDENCE = Path("/root/swapz-pr57-validation/evidence/sustained")
RUNNER = EVIDENCE / "run-sustained-trial.py"
OUTPUT = EVIDENCE / "mix-ratio-matrix.jsonl"


def main() -> int:
    for read_pct in (30, 50):
        for rep in (1, 2, 3):
            order = ["v22", "pr57-b1"]
            if (rep + read_pct) % 2:
                order.reverse()
            for candidate in order:
                command = [
                    "python3", str(RUNNER), "--candidate", candidate,
                    "--rep", str(rep), "--qd", "8", "--read-pct", str(read_pct),
                    "--warmup", "10", "--seconds", "30",
                ]
                started = time.time()
                completed = subprocess.run(
                    command, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=900,
                )
                row = {
                    "candidate": candidate, "read_pct": read_pct,
                    "rep": rep, "command": command, "rc": completed.returncode,
                    "elapsed_wall_s": time.time() - started,
                    "output": completed.stdout, "recorded_at": time.time(),
                }
                with OUTPUT.open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
                print(json.dumps({
                    "candidate": candidate, "read_pct": read_pct, "rep": rep,
                    "rc": completed.returncode,
                    "elapsed": round(row["elapsed_wall_s"], 1),
                    "tail": completed.stdout[-500:],
                }, sort_keys=True), flush=True)
                if completed.returncode:
                    print("matrix stopped after preserved failed trial", flush=True)
                    return completed.returncode
    print("MIX_RATIO_MATRIX_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
