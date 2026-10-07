#!/usr/bin/env python3
"""Model request-size plateau for serialized swap backing media.

This is deliberately simple: one lower request pays a fixed command latency plus
payload transfer time at the selected media bandwidth.  It is not a substitute
for null_blk or physical-media testing; it tells us how far to sweep before the
fixed-latency term is amortized.
"""

from __future__ import annotations

import argparse


def throughput_mib_s(size_kib: int, bandwidth_mib_s: float, latency_ms: float) -> float:
    size_mib = size_kib / 1024.0
    return size_mib / (latency_ms / 1000.0 + size_mib / bandwidth_mib_s)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bandwidth", type=float, default=20.0, help="media MiB/s")
    parser.add_argument(
        "--latencies",
        default="0.1,0.25,0.5,1,2",
        help="comma-separated fixed command latencies in ms",
    )
    parser.add_argument(
        "--sizes",
        default="4,8,16,32,64,128,256,512,1024,2048,4096",
        help="comma-separated request sizes in KiB",
    )
    parser.add_argument(
        "--plateau",
        type=float,
        default=0.97,
        help="fraction of largest tested throughput defining the plateau",
    )
    parser.add_argument(
        "--ratios",
        default="1,2,3,4",
        help="logical/physical byte-reduction ratios to project",
    )
    args = parser.parse_args()

    sizes = [int(x) for x in args.sizes.split(",")]
    latencies = [float(x) for x in args.latencies.split(",")]
    ratios = [float(x) for x in args.ratios.split(",")]

    print(
        f"media={args.bandwidth:.3f} MiB/s plateau={args.plateau:.3f} "
        f"sizes={sizes}"
    )
    for latency in latencies:
        values = [throughput_mib_s(s, args.bandwidth, latency) for s in sizes]
        best = max(values)
        plateau_size = next(s for s, value in zip(sizes, values) if value >= best * args.plateau)
        print(
            f"\nlatency_ms={latency:g} best_tested={best:.3f} MiB/s "
            f"first_plateau_kib={plateau_size}"
        )
        header = ["KiB", "physical"] + [f"logical@{r:g}x" for r in ratios]
        print(" ".join(f"{x:>13}" for x in header))
        previous = None
        for size, physical in zip(sizes, values):
            gain = "" if previous is None else f" gain={((physical / previous) - 1) * 100:5.2f}%"
            projected = [physical * ratio for ratio in ratios]
            print(
                f"{size:13d} {physical:13.3f} "
                + " ".join(f"{x:13.3f}" for x in projected)
                + gain
            )
            previous = physical


if __name__ == "__main__":
    main()
