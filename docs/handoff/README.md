# Handoff reference and evidence index

This directory combines **supporting current observations**, **immutable
source-bound history**, **abandoned/rejected experiments** and **deferred research**.
A historical `Current` heading, old source path, helper argument, source SHA,
PASS, or approval instruction is not authority for the current checkout.
Keep the original records intact; use the linked contract and current
exact-source evidence before action.

## Active contracts and supplementary observations

The mandatory instructions are [AGENTS.md](../../AGENTS.md), the compact
[operating context](../AGENT_CONTEXT.md) and [vision](../VISION.md).
[ROADMAP.md](../ROADMAP.md) owns priority/experiment decisions;
[coding standards](../coding_standards.md) and
[testing standards](../testing_standards.md) own implementation/qualification
invariants. The [frozen acceptance manifest](../production-acceptance.json),
current [test report](../../test_results.json) and current CI/source identity
must be checked together; no handoff snapshot can replace them.
The official test interface remains `make test`; `make fast_test` is
development-only and never qualifies or publishes a source.

- [Systemd runtime health](systemd-runtime-health.md) is supplementary
  operational explanation, not a substitute for the package/boot contracts.
- [Host-history registry](host-history.json) is an audited, **active input**
  to private descriptive per-host plotting; it is not a release verdict.

## Historical qualification and physical observations

- [Production-readiness snapshot](production-readiness.json) is explicitly
  **HISTORICAL**, not a live status or an acceptance-policy source.
- [Source qualification snapshots](historical-source-qualification-snapshots.md)
  and [benchmark qualification narratives](historical-benchmark-qualification-narratives.md)
  preserve earlier source-specific PASS/FAIL/BLOCKED and measured tradeoffs.
- [Benchmark experiment memory](historical-benchmark-experiment-memory.md)
  retains older results, confidence limits and proposals without promoting them.
- [Old-host physical and live-swap evidence](old-host-physical-and-live-swap-evidence.md)
  records the retired `/dev/sda4` host, **not** the dedicated current card.
- [Alpha.29 harness failure chronology](alpha29-loaded-qualification-observability.md)
  distinguishes historical preflight/visibility failures from current
  post-stage qualification verdicts.
- [ID73 CPU/cache batch](id73-cpu-cache-qualification-batch.md)
  preserves the older source-bound implementation and test summary.

## Abandoned/rejected experiments and superseded work orders

- [Rejected optimization pilots](historical-rejected-optimization-pilots.md)
  keep removed candidates, measurements and reopening conditions.
- [Old bottleneck ranking](historical-bottleneck-ranking-9123b811-7ff94fd4.md)
  is tied to two older host reports, not present scheduling priorities.
- [November 2 work queue](2026-11-02-optimization-work-queue.md)
  preserves the retired ID181 cleanup and previous qualification tasks.
- [Lane-gap instrumentation brief](lane-gap-diagnostics.md) is a completed
  historical assignment; its private parser TODO is no longer current.
- [Physical-swap review prompt](physical-swap-external-review-prompt.md)
  is an unissued historical draft, not a present approval requirement.

## Deferred optimization research (not current assignments)

- [November 1 content/concurrency backlog](2026-11-01-content-concurrency-backlog.md)
  contains superseded old-host restrictions and deferred observations.
- [Benchmark experiment memory: deferred ideas](historical-benchmark-experiment-memory.md#deferred-idea-evidence)
  keeps hypotheses and negative evidence. Reopen only using current
  [ROADMAP decisions](../ROADMAP.md) and fresh exact-source measurements.

Read these archives selectively. Preserve negative/blocked results and their
original provenance rather than converting a stage PASS or historical host
authorization into present production-readiness evidence.
