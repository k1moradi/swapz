# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `c4539b3afe222372d5266be5a79bb96f23dfdeea` passed all five current qualification stages. Correctness included 64 RAW writes, nine zero elisions, explicit flushes, retained-window suspend/drain with 128-page verification, and synthetic retained WRITE/FLUSH fail-closed phases. This baseline includes the alignment-aware adjacent lower-run planner tie-break and accepted-incoming first-pack tail fix.

The write-only pilot produced these directional patterns:

- QD1: no lower-byte/request reduction; swapz remained substantially slower than raw in both models.
- QD4: lower WRITE requests remained roughly halved versus raw, but useful WRITE throughput remained lower.
- QD8: the accepted-tail fix removed the prior millisecond-scale stall; slow-model swapz reached about 0.88-0.90x raw and faster-model swapz about 0.61-0.76x raw while retaining strong request reduction.
- QD32 slow model: swapz remained about 1.27x raw useful WRITE throughput.
- QD32 faster model: swapz remained about 0.61-0.63x raw and the medium write-only logical/lower ratio fell to about 1.37x, showing that first-pack closure can still fragment a fast finite wave. The mixed async arm retained a preliminary gain.

The pilot used one pair per mode/QD and has no confidence interval.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify one bounded zero-delay first-pack tail recheck. The hypothesis is that QD4 and fast QD32 submitters often miss the current accepted snapshot by only one scheduler turn: one immediate worker handoff should reduce QD4 lower requests and recover fast-model packing ratio without reintroducing a millisecond retention stall. Reject lower-WRITE byte growth, QD8 regression, correctness loss or unacceptable read-tail regression.
2. Profile the remaining QD1 production-C wall time after that policy is stable. Attribute retention wait, LZ4 preparation, planning/publication, lower WRITE completion and workqueue scheduling; remove temporary attribution once the decision is made.
3. Expand the write-only saturation study to at least five counterbalanced pairs per mode/QD/regime only after the C policy is stable, then report confidence intervals.
4. Exercise sustained live GC, reserve rotations, near-full churn, real lower error behavior and resource pressure on owned RAM devices. No observed GC means GC remains unqualified.
5. Extend read qualification beyond the current small RAM working set with controlled cache state before making cold swap-in claims.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
