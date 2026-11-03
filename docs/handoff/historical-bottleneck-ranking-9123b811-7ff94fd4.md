# Historical bottleneck ranking for 9123b811 / 7ff94fd4

This file preserves the former ROADMAP "Current bottleneck ranking" verbatim
from commit `320ca3a30ee26689e1f455585d16a49b851155ff`. The measurements are source- and host-bound to older
x86/ARM64 reports and are retained as optimization evidence, not as a current
production-readiness statement or qualification of present `main`. The active
priority order is canonical in [AGENT_CONTEXT.md](../AGENT_CONTEXT.md); current
performance decisions belong in the [ROADMAP evidence table](../ROADMAP.md)
and must be refreshed from exact-source evidence before promotion. Durable
telemetry and qualification semantics remain in
[coding_standards.md](../coding_standards.md) and
[testing_standards.md](../testing_standards.md).

## Current bottleneck ranking

1. **SATA/NVMe mixed envelopes (owner reports for `9123b811` x86 and
   `7ff94fd4` ARM64: SATA -22.5/-33.8%, NVMe4 -54.0/-39.7%, NVMe5
   -47.8/-40.1%).** Lower savings stay intact (bytes saved 28-30%, requests
   saved 84-91%), so the loss is lower-WRITE service time on one lane, not I/O
   volume. **Leading hypothesis, not a proven diagnosis: single-lane pipeline
   recovery.** The interval from one lower WRITE completing to the next one
   starting is roughly a fixed per-run cost (~31-35 us on x86, ~40-59 us on
   ARM64) while device service per run ranges 21-122 us, so the faster the
   device the larger the idle share. Existing counters, measured window:

   | Host / envelope | swapz vs raw | Lane busy | Runs | Pages/run | Service/run | Gap/run | Completion→publication/run | Accepted-work idle | Deferred ACKs | READ p99 raw/swapz |
   | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
   | x86 SATA | -22.5% | 76% | 1053 | 11.7 | 108 us | 34 us | 4.5 us | 0.3 ms | 5348 | 114/240 us |
   | x86 NVMe4 | -54.0% | 51% | 1157 | 10.6 | 33 us | 31 us | 3.9 us | 2.3 ms | 6547 | 38/97 us |
   | x86 NVMe5 | -47.8% | 38% | 1335 | 9.2 | 21 us | 35 us | 3.9 us | 5.1 ms | 8611 | 36/102 us |
   | ARM64 SATA | -33.8% | 68% | 1057 | 11.6 | 122 us | 59 us | 5.9 us | 7.4 ms | 4443 | 260/187 us |
   | ARM64 NVMe4 | -39.7% | 48% | 1510 | 8.1 | 39 us | 42 us | 4.4 us | 12.8 ms | 8736 | 110/136 us |
   | ARM64 NVMe5 | -40.1% | 38% | 1905 | 6.5 | 25 us | 40 us | 4.6 us | 18.2 ms | 8951 | 88/145 us |

   Busy is `lower_write_wall_ns` over measured wall; gap/run is the remaining
   wall per lower-WRITE request; completion→publication is
   `pipeline_post_lower_wall_ns` per request. `1 / busy` (1.3-2.65x) is a
   **ceiling** at 100% utilization and unchanged run size, not an expected gain;
   closing any gap can expose another bottleneck. Interpretation limits:
   `k1_ready_wait_windows=0` means only that no completed window had to wait
   for a pending lower WRITE (the policy never sealed while the lane was busy),
   not that no accepted work existed during lower I/O. `accepted_work_lower_idle_*`
   starts only when the owner retains a staged window with the lane idle; its
   small totals (0.3-18 ms against 36-77 ms of lane idle) say that retained
   staged work explains little of the idle: 65-86% of each gap has no
   attributing counter (owner pickup, upper round trip of ACK, writer reissue
   and admission, READ service on the owner, and sealing, which has no per-gap
   counter). Owner CPU/wall
   (19-25%) does not show where the owner is off-CPU, and admission→owner
   (15-21 us per WRITE) may overlap lower service. ID178 partitions exactly
   the completion→next-submit interval before any architecture change.
   Envelope arms still lack `host_cpu`, so host-bound NVMe rows cannot yet be
   separated from host contention. History: pre-ID108 SATA wave traces showed
   stragglers staged behind the first K=1 WRITE leaving ~17 us after its
   completion; ID109 straggler waiting traded the same time it saved and the
   post-ID107/ID108 K=2 trial (ID110) reached depth two without useful-service
   gain and with more requests.
2. **Fast QD4 (latency guard; x86 +4.4% MET, ARM64 -14.7% MISSED).** K=1
   completes all four writers together, so their reissue spread sits on every
   cycle while raw overlaps it. ID110 did not improve it because four-record
   windows without followers still dispatch synchronously. Reopening needs a
   separately justified shallow-window ownership policy; deprioritized behind
   item 1.
3. **QD8 bimodality and the 8KiB READ-amplification cap.** Unchanged from the
   ID101–ID104 analysis: merged eight-record windows win, and accepted-burst
   extents are capped at 8KiB, holding QD8 lower bytes near 0.75.

---

## What the pinned queue experiment establishes

The QD32 replay remains intentionally unpaced and closed-loop, but the lower
device geometry is no longer ambiguous. The slow model is blk-mq with one
submit queue and `hw_queue_depth=1`, and observed lower peaks stay at one.
The faster model uses `hw_queue_depth=64`; raw traffic reaches sampled depth
greater than one, proving that the model can expose parallel lower service.

This resolves the earlier SD-model uncertainty. On the serial-depth synthetic
model, swapz's compression and aggregation are strongly beneficial even though
K=1 async preparation is not. The correct conclusion is therefore not "more
WRITE concurrency is needed for SD-like media"; it is "data/request reduction
already wins on the serial model, while async WRITE concurrency currently adds
nothing measurable."

The fast model exposes a different problem. swapz lower READ and WRITE peaks
remain near one despite deeper raw service capability. For WRITEs, the K=1 run
slot is occupied only ~9% of mixed wall and preparation backlog is shallow, so
K>1 would add slots before proving ready-run pressure. For READs, raw reaches
sampled depth ~4 while swapz remains serialized at one; this is the cleaner
bounded concurrency opportunity.
