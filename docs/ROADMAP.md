# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`4529140f689183ead86d94526b9974b875d915f4` passed all five stages and is
the strongest request-reduction experiment so far, but is not promoted.

At `4529140...`, write-only QD4 converged to about 1032 lower WRITE requests
and QD8 to about 520 for 4096 medium writes. Faster-model QD32 reached about
138-139 requests, and slow async QD32 reached 141. Those are large endurance-
direction reductions. However, faster-model QD8 useful throughput fell to
0.35x/0.59x raw sync/async, mixed faster-model QD32 fell to 16.39/18.06 MB/s,
and mixed faster-model deadline closes rose to about 214 per pair. Slow QD32
sync also learned an invalidly narrow target of 3, produced 82 deadline closes
and 209 lower requests. Request reduction without acceptable throughput remains
diagnostic evidence, not acceptance.

The write-only pilot is still one pair per mode/QD with no confidence interval,
and live GC remains unexercised.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify dry accepted-pack closure: once a complete second pack is staged and
   the finite accepted queue is empty, close it instead of waiting only for a
   larger learned burst target and burning the absolute deadline.
2. Preserve learned width from the complete worker-local plus incoming accepted
   FIFO, and do not let one two/three-record deadline collapse the target below
   the original four-record anti-chopping floor.
3. Require the next run to preserve the QD4/QD8/QD32 lower-request gains while
   recovering mixed faster-model throughput and sharply reducing worker-empty
   deadline closes.
4. Keep asynchronous-preparation QD1 scheduling as a separate production-C
   experiment after burst closure stabilizes.
5. Revisit GC reserve/probe wear distribution only with direct rotation tests
   and then sustained loaded GC evidence; current loaded runs exercise no live
   GC, so do not mix allocator changes into the burst experiment.
6. Add statistically repeated saturation only after policy stabilizes; genuine
   lower errors and long-run resource pressure remain open gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
