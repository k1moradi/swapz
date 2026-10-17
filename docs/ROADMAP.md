# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`658f390a03f546b35ba068900d5ec700126b7e99` passed all five stages and is
qualified exploratory evidence, but is not promoted.

The retained-service candidate restored the intended write-only geometry.
QD8 used exactly 520 lower WRITE requests in both modes on both RAM models.
On the faster model QD32 used 147/138 requests sync/async, back near the prior
~139-request deep-window result. QD1 async also retained its scheduling result
at 7.39 MB/s and 0.37 ms p99.

Mixed behavior improved without changing the lower-byte/read-tail safety gates.
Slow mixed reached 7.12/7.28 MB/s with about 544 lower WRITE requests. Faster
mixed reached 20.19/22.65 MB/s against 19.54 MB/s raw, with packed reads faster
than raw and lower READ bytes below raw. Faster mixed worker-empty deadlines
fell from about 88 to 59 per pair and one-page deadline closes from about 43 to
31.5, so the retained-service repair is directionally effective but incomplete.

The remaining rejection signal is asynchronous intermediate-QD throughput.
Faster write-only QD8 remained 17.10/17.21 MB/s sync/async against about
49.9 MB/s raw despite the restored 520-request geometry. QD4 likewise remained
about 12.85 MB/s with no async gain. QD32 async improved over sync
(33.21 vs 29.25 MB/s) but remained well below raw. This isolates scheduling of
LZ4 preparation rather than window chopping as the next experiment.

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

1. Qualify the credited opposite-end preparation candidate now on `main`.
   Keep the 658f390 retained-window policy and lower-byte geometry unchanged.
2. Outside synchronous lower WRITE wait, permit only one producer tail claim
   per ordered-work credit. An inline ordered WRITE reserves the head first;
   READ/barrier service may grant one bounded credit; producer-owned FIFO heads
   grant no new credit. This should prevent the producer from serially claiming
   every next QD4/QD8 BIO and forcing the ordered worker into completion waits.
3. Require the official report to expose producer head/tail claims, ordered
   inline/handoff counts and actual blocking waits. QD8 should show work split
   across ordered-inline and producer-tail preparation with few blocking waits,
   while QD1 keeps its lone-head behavior.
4. Preserve write-only QD8 at ~520 lower requests and faster QD32 near ~139.
   Reject any async-throughput gain that increases lower WRITE bytes, worsens
   packed-read tails or reintroduces the prior 2-16-record window chopping.
5. After preparation scheduling is isolated, revisit the residual faster mixed
   worker-empty deadline cluster (~59 per pair, ~31.5 one-page deadlines).
   Do not combine another retention-policy change with this scheduling test.
6. Keep metadata-LRU invalidation and circular GC destination probing unchanged.
   No endurance or sustained-GC claim is permitted until loaded qualification
   actually observes GC victims.
7. After policy stabilizes, add statistically repeated saturation with
   confidence intervals; genuine lower errors, sustained GC, kernel-worker CPU
   attribution and long-run resource pressure remain release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
