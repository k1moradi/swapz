# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`3e2344134de2548c5d6f71b48f6e8bbe508bb3df` passed all five stages and
is qualified exploratory evidence, but is not promoted.

The demand-gated preparation experiment preserved the slow mixed path at
7.09/7.21 MB/s sync/async with about 557/560 lower WRITE requests and a 1.47x
logical/backing ratio. Faster mixed remained competitive at 19.50/21.34 MB/s
against 19.33 MB/s raw, with packed reads faster than raw and lower READ bytes
well below raw.

Its attribution exposed two regressions relative to `9f11a1a...`. Faster
write-only QD8 async fell from 28.39 to 17.31 MB/s while requests rose from
about 520 to 555, and faster QD32 request counts rose from about 139 to
241/210 sync/async. The window histogram gained many 2-8-record closes.
Meanwhile faster mixed still recorded about 88.2 worker-empty deadline closes
and 43.2 one-page deadline closes per pair. QD1 async did improve to 7.43 MB/s
with 0.37 ms p99, showing that avoiding the lone-head producer race is useful
but must not disable high-QD preparation parallelism.

The write-only pilot remains one pair per mode/QD with no confidence interval,
and the loaded run again reported zero GC victims. Circular GC destination
probing therefore has direct native correctness evidence only, not loaded
endurance qualification.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify the retained-service/opposite-end-preparation candidate now on
   `main`. Tail-width sampling occurs only after a real PACK_READY lower
   write; target-level admission closure is restored after an accepted-follower
   refresh, while below-target closure remains worker-tail-only.
2. Require write-only QD8 to return toward the ~520-request geometry and faster
   QD32 toward ~139 requests without surrendering the QD1 async improvement.
   QD8/QD32 async throughput should recover materially from the
   3e23441 regression while lower WRITE bytes remain unchanged or better.
3. Require faster mixed QD32 `deadline_worker_empty` and one-page deadline
   closes to fall materially from ~88 and ~43. Empty read/zero fences must no
   longer erase retained service state, but hard ordering boundaries and true
   worker idle must still clear it.
4. Verify opposite-end asynchronous preparation under bounded capacity:
   ordered FIFO execution remains head-first, producer preparation is tail-first
   while the ordered worker runs and head-first during lower WRITE wait, and no
   producer may block after claiming a BIO. QD1 must keep the idle-head
   inline-steal benefit.
5. Keep metadata-LRU invalidation semantics and the circular GC destination
   probe unchanged. No endurance or sustained-GC claim is permitted unless a
   loaded run actually exercises GC victims.
6. After policy stabilizes, add statistically repeated saturation with
   confidence intervals; genuine lower errors, sustained GC, kernel-worker CPU
   attribution and long-run resource pressure remain release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
