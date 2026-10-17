# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`0d8f7f7ea90c33fbac3a57d95f410e68275c1cea` passed all five stages and
is qualified exploratory evidence, but is not promoted.

The dry accepted-pack experiment recovered the mixed path: slow-model useful
WRITE reached 7.09/7.25 MB/s sync/async with only about 2.8 mean deadline
closes, while the faster model reached 19.04/22.63 MB/s and retained faster
packed reads. Random 4MiB lower READ traffic remained strongly below raw.

Its write-only attribution exposed a different failure: a complete medium
second pack could close at six records below learned QD8/QD32 targets. Faster
QD8 therefore used roughly 1008-1028 lower WRITE requests and faster QD32
roughly 868-892, with many 1-8-record windows; this surrendered much of the
request reduction previously demonstrated by `4529140...`. Slow QD8 showed
the same request fragmentation even though useful throughput remained closer
to raw. Request reduction and mixed recovery must coexist before promotion.

The write-only pilot remains one pair per mode/QD with no confidence interval,
and the loaded run still reported zero GC victims.

## Completed cleanup after that baseline

- Removed duplicate metadata parsing/CRC work from the compressed read path while retaining current authority, sequence and payload CRC checks.
- Removed the rejected cap=3/uncapped planner-stat diagnostics from the production write hot path, status and official report schema. The accepted-burst production planner remains capped at two cold read blocks per record.
- Removed the standalone research kernel module and retired C++ model.
- Removed historical compatibility, NBD, recall, pressure and obsolete evidence-model infrastructure from the active working tree.
- Made implementation/report/workflow terminology version-neutral; SWZ3 remains only the format identity.

These cleanup revisions, the alignment-aware adjacent lower-run tie-break and the accepted-incoming first-pack tail fix are covered by the owner-loaded `c4539b3...` baseline.

## Immediate work queue

1. Qualify the current burst candidate: write admission may close only at the
   learned/sampled target; below-target useful-pack closure is restricted to a
   refreshed worker tail with prior packed-chain or independent-read service
   evidence.
2. Require QD8/QD32 write-only windows to recover deep-queue aggregation
   without losing the mixed-path recovery. In particular, compare lower WRITE
   requests against both `0d8f7f7...` and the earlier request-reduction
   experiment, while rejecting any increase in lower WRITE bytes.
3. Qualify ordered-worker stealing of only unstarted asynchronous preparation.
   QD1 async should narrow its throughput/p99 gap without removing the measured
   high-QD producer/lower-I/O overlap or weakening completion ownership.
4. Keep the circular GC destination probe only if direct rotation/engine tests
   remain exact and loaded correctness is unchanged. No endurance or sustained
   GC claim is permitted unless the loaded run actually exercises GC victims.
5. After policy stabilizes, add statistically repeated saturation with
   confidence intervals; genuine lower errors, sustained GC, kernel-worker CPU
   attribution and long-run resource pressure remain release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
