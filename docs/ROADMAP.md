# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `1a3b30da5ad2435e2e174421ef62bc4837b38371` passed all five current qualification stages. Correctness included 64 RAW writes, nine zero elisions, explicit flushes, retained-window suspend/drain with 128-page verification, and synthetic retained WRITE/FLUSH fail-closed phases.

The write-only pilot produced these directional patterns:

- QD1: no lower-byte/request reduction; swapz remained substantially slower than raw in both models.
- QD4: lower WRITE requests were roughly halved versus raw, but useful WRITE throughput remained lower.
- QD8: request reduction remained strong, but useful throughput was still lower.
- QD32 slow model: swapz exceeded raw useful WRITE throughput.
- QD32 faster model: swapz remained below raw in the write-only pilot, while the mixed async arm showed a preliminary gain.

The pilot used one pair per mode/QD and has no confidence interval.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions are now covered by the owner-loaded `1a3b30da...` baseline.

## Immediate work queue

1. Qualify the alignment-aware planner tie-break that prefers larger equal-cost extents first. The expected QD4 effect is fewer lower WRITE requests with unchanged lower WRITE bytes; any byte increase or read-tail regression rejects it.
2. If QD4 improves as predicted, fix the retained first-pack tail: after a useful pack was deferred only because one already-accepted successor existed, do not pay the full 2ms deadline once that finite accepted tail is consumed.
3. Profile the remaining QD1 and QD8 production-C wall time. Attribute retention wait, LZ4 preparation, planning/publication, lower WRITE completion and workqueue scheduling; remove temporary attribution once the decision is made.
4. Expand the write-only saturation study to at least five counterbalanced pairs per mode/QD/regime only after the C policy is stable, then report confidence intervals.
5. Exercise sustained live GC, reserve rotations, near-full churn, real lower error behavior and resource pressure on owned RAM devices. No observed GC means GC remains unqualified.
6. Extend read qualification beyond the current small RAM working set with controlled cache state before making cold swap-in claims.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
