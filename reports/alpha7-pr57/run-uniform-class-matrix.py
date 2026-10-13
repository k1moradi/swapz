#!/usr/bin/env python3
"""Matched, counterbalanced 30-second QD8 size-class tests for V2.2 and PR57."""
import json
import os
import subprocess
import time
from pathlib import Path

EVIDENCE = Path("/root/swapz-pr57-validation/evidence/sustained")
RUNNER = EVIDENCE / "run-sustained-fixture-trial.py"
FIXTURE_DIR = EVIDENCE / "fixtures" / "uniform"
OUTPUT = EVIDENCE / "uniform-class-matrix.jsonl"
CLASSES = ("1032", "2089", "3500", "raw")


def main() -> int:
    for class_name in CLASSES:
        fixture = FIXTURE_DIR / f"uniform-{class_name}-1024-pages.bin"
        classmap = FIXTURE_DIR / f"uniform-{class_name}-1024-class.bin"
        for rep in (1, 2, 3):
            order = ["v22", "pr57-b1"]
            if (rep + int(class_name == "raw")) % 2:
                order.reverse()
            for candidate in order:
                command = [
                    "python3", str(RUNNER), "--candidate", candidate,
                    "--rep", str(rep), "--qd", "8", "--read-pct", "20",
                    "--warmup", "10", "--seconds", "30",
                    "--label-suffix", f"class-{class_name}",
                ]
                env = os.environ.copy()
                env["SWAPZ_FIXTURE"] = str(fixture)
                env["SWAPZ_CLASSMAP"] = str(classmap)
                started = time.time()
                completed = subprocess.run(
                    command, env=env, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, timeout=900,
                )
                row = {
                    "candidate": candidate, "class": class_name,
                    "rep": rep, "command": command,
                    "fixture": str(fixture), "classmap": str(classmap),
                    "rc": completed.returncode,
                    "elapsed_wall_s": time.time() - started,
                    "output": completed.stdout, "recorded_at": time.time(),
                }
                with OUTPUT.open("a") as stream:
                    stream.write(json.dumps(row) + "\n")
                print(json.dumps({
                    "candidate": candidate, "class": class_name, "rep": rep,
                    "rc": completed.returncode,
                    "elapsed": round(row["elapsed_wall_s"], 1),
                    "tail": completed.stdout[-500:],
                }, sort_keys=True), flush=True)
                if completed.returncode:
                    print("uniform-class matrix stopped after preserved failure", flush=True)
                    return completed.returncode
    print("UNIFORM_CLASS_MATRIX_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
