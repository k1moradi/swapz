# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `45a5ccf09b2a4ce396d891215581476d3ee0dce3` passed all five qualification stages and is the current accepted performance baseline. Its learned singleton fast-close preserved one-block/one-request QD1 geometry while recovering useful WRITE throughput to about 0.89-0.94x raw on the slow model and 0.76-0.86x raw on the faster model. The loaded RAW/zero/flush, retained suspend/drain, byte-exact verification and synthetic WRITE/FLUSH fail-closed gates also passed.

The write-only pilot remains directional only:

- QD1: logical/lower stayed exactly 1.00x and 4096 requests, while the retention tax fell sharply.
- QD4: logical/lower stayed about 1.33x and useful throughput remained about 0.60-0.70x raw.
- QD8: slow-model swapz remained about 0.89-0.90x raw and faster-model async about 0.76x raw.
- QD32 slow model: swapz remained about 1.26-1.27x raw.
- QD32 faster model: swapz remained about 0.61-0.62x raw.
- Slow mixed QD32 still lost useful WRITE throughput, with most deadline closes attributed to `deadline_after_read`.

The pilot used one pair per mode/QD and has no confidence interval.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify bounded accepted-burst deadline handling and first-pack follow-up depth. The target is to stop slow independent READ latency from fragmenting already-accepted QD32 writes and to avoid QD4 orphan tails, without changing FUA/dependency ordering or regressing QD1/QD8.
2. Qualify alignment-aware physical staging for adjacent lower runs and a 512-entry metadata-block LRU. Preserve committed-prefix semantics, zero default padding and exact CRC/generation authority while reducing alignment holes and random-read lower bytes.
3. If QD1 remains materially below raw after the retention tax is removed, profile its remaining production-C wall time across LZ4 preparation, planning/publication, lower WRITE completion and workqueue scheduling; remove temporary attribution once the decision is made.
4. Expand the write-only saturation study to at least five counterbalanced pairs per mode/QD/regime only after the C policy is stable, then report confidence intervals.
5. Exercise sustained live GC, reserve rotations, near-full churn, real lower error behavior and resource pressure on owned RAM devices. No observed GC means GC remains unqualified.
6. Extend read qualification beyond the current small RAM working set with controlled cache state before making cold swap-in claims.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
