# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `8589a010f7c70c4f1f9737e688c434e4a11c9f9c` passed the complete qualification available at that revision. Correctness included 64 RAW writes, nine zero elisions, explicit flushes, retained-window suspend/drain with 128-page verification, and synthetic retained WRITE/FLUSH fail-closed phases.

The write-only pilot produced these directional patterns:

- QD1: no packing; swapz was substantially slower than raw in both models.
- QD4: request reduction appeared, but useful WRITE throughput remained lower.
- QD8: request reduction remained strong, but useful throughput was still lower.
- QD32 slow model: swapz exceeded raw useful WRITE throughput.
- QD32 faster model: swapz remained below raw.

The pilot used one pair per mode/QD and has no confidence interval.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions are **NOT YET OWNER-LOADED** as a complete current HEAD.

## Immediate work queue

1. Re-run the sole official `make test` at current `main`. Treat any correctness, build, source-contract, loaded-lifecycle or teardown failure as blocking.
2. Compare current mixed/QD results with the qualified `8589a010` baseline. The diagnostic-removal patch should not change lower-I/O geometry; unexpected layout/counter changes require investigation.
3. Profile the production C path at QD1, QD4 and QD8. Attribute wall time to retention wait, LZ4 preparation, ordering/planning, lower WRITE completion, metadata/CRC work and workqueue scheduling. Do not add telemetry that remains permanently after the decision.
4. Make the smallest C-first optimization supported by that attribution. The strongest open hypothesis is unnecessary fixed-window latency when no useful aggregation is achieved, but do not weaken dependency, FUA, authority or completion guarantees to chase QD1.
5. Only after the cleanup source is stable, expand the write-only saturation study to at least five counterbalanced pairs per mode/QD/regime and report confidence intervals.
6. Exercise sustained live GC, reserve rotations, near-full churn, real lower error behavior and resource pressure on owned RAM devices. No observed GC means GC remains unqualified.
7. Extend read qualification beyond the current small RAM working set with controlled cache state before making cold swap-in claims.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
