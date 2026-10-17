# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `45a5ccf09b2a4ce396d891215581476d3ee0dce3` passed all five qualification stages and is the current accepted performance baseline. Its learned singleton fast-close preserved one-block/one-request QD1 geometry while recovering useful WRITE throughput to about 0.89-0.94x raw on the slow model and 0.76-0.86x raw on the faster model. The loaded RAW/zero/flush, retained suspend/drain, byte-exact verification and synthetic WRITE/FLUSH fail-closed gates also passed.

The accepted baseline write-only pilot remains directional only. A later fully
qualified experiment at `fca890520f57af568ac74a626569a1b223a08572`
materially reduced 4MiB seeded-random lower READ bytes (to roughly 2.37-2.61MiB)
and improved slow mixed-QD32 useful WRITE throughput to about 6.5-6.6 MB/s, but
its write-only QD8 pilot regressed to about 0.73-0.74x raw on the slow model and
about 0.60-0.70x on the faster model with roughly 1536 lower requests. That
experiment therefore remains qualified correctness evidence, not the accepted
performance baseline.

The pilot used one pair per mode/QD and has no confidence interval.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify full finite-snapshot write coalescing: while any successor BIO is already accepted, do not split a useful pack mid-snapshot; flush once that accepted tail is exhausted or an ordering fence requires it.
2. Exclude successful synchronous independent-read service time from the retained write window's idle budget, while preserving the pinned no-future-arrival rule and all PREFLUSH/FUA/dependency gates.
3. Keep the qualified 512-entry metadata LRU and cursor-aware planner under observation. The next result must recover the exploratory QD8 request/throughput regression seen at `fca8905...` while retaining its large random-read lower-byte win and slow mixed-QD32 improvement.
4. If QD1 remains materially below raw after the retention tax is removed, profile its remaining production-C wall time across LZ4 preparation, planning/publication, lower WRITE completion and workqueue scheduling; remove temporary attribution once the decision is made.
4. Expand the write-only saturation study to at least five counterbalanced pairs per mode/QD/regime only after the C policy is stable, then report confidence intervals.
5. Exercise sustained live GC, reserve rotations, near-full churn, real lower error behavior and resource pressure on owned RAM devices. No observed GC means GC remains unqualified.
6. Extend read qualification beyond the current small RAM working set with controlled cache state before making cold swap-in claims.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
