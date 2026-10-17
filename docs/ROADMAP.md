# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`9f11a1a63bc4a3fc447d5ae7be9493b6e690f7ff` passed all five stages and
is qualified exploratory evidence, but is not promoted.

The worker-tail burst experiment simultaneously preserved mixed QD32 and
restored deep request aggregation. Slow mixed useful WRITE reached 7.12/7.27
MB/s sync/async with about 544 lower WRITE requests and a 1.47x
logical/backing ratio. Faster mixed reached 19.58/22.81 MB/s with about
1066/951 lower requests, 1.44x logical/backing ratio, and packed reads faster
than raw. Write-only QD8 returned to roughly 520 requests and QD32 to 139
requests on the faster model; slow QD32 reached 201/141 requests sync/async.

The remaining rejection signal is useful throughput at intermediate queue
depth on the faster model: QD8 reached only 17.00/28.39 MB/s against about
49.9 MB/s raw, and QD4 remained about 13 MB/s against about 22 MB/s raw.
Mixed faster-model worker-empty deadlines also remained high at about 89.5
per pair. QD1 async improved materially versus the previous async-preparation
candidate but still pays avoidable producer wakeup competition.

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

1. Qualify the worker-only retained-close candidate now on `main`.
   PACK_READY is evaluated only after the serialized worker refreshes local
   plus incoming; an already-admitted first-wave width may raise the one-shot
   current target without waiting for future BIOs.
2. Verify that service-proven dry residues remove the faster mixed
   `deadline_worker_empty` cluster without increasing lower WRITE bytes,
   request count or read tails. A packed commit or independent retained read
   is required before a below-target dry residue may close.
3. Verify demand-driven asynchronous preparation wakeups: QD1 should avoid
   producer/inline-steal races, while second-or-later queued writes and active
   lower WRITE intervals must retain measurable high-QD preparation overlap.
4. Measure whether idempotent empty-LRU invalidation reduces write-hot-path
   overhead. Metadata residency semantics remain unchanged; hash indexing and
   compressed-payload zero-copy are not part of this candidate.
5. Keep the circular GC destination probe only if loaded correctness remains
   unchanged. No endurance or sustained-GC claim is permitted unless the
   loaded run actually exercises GC victims.
6. After policy stabilizes, add statistically repeated saturation with
   confidence intervals; genuine lower errors, sustained GC, kernel-worker CPU
   attribution and long-run resource pressure remain release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
