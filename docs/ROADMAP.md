# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`5aeae47f82c71bbc3e5722b977f684d08eee0083` passed all five owner-loaded
qualification stages and requalified the preferred exploratory preparation/window
behavior restored from `6642e7ebfce3255267f51fe99b66114122bda7e0`.

At `5aeae47`, slow-model mixed QD32 async reached 7.10 MB/s with 544.5
lower WRITE requests. Faster-model mixed async reached 21.18 MB/s against
19.49 MB/s sync and 19.39 MB/s raw, with 1029 lower WRITE requests and
2.58 ms mixed READ p99. Faster write-only QD8 async reached 29.75 MB/s while
preserving 520 lower WRITE requests; QD32 async reached 46.89 MB/s with 138
requests. These write-only points remain one-pair directional evidence.

The rollback is a clear recovery from rejected `2ad805b`, but it has not yet
matched every qualified `6642e7e` mixed metric: faster mixed worker-empty
deadline closes are 70.2 per pair rather than about 59.5, and lower WRITE
requests are 1029 rather than about 1007. Loaded GC victims remain zero.

Low/medium-QD preparation is now the most useful scheduling target. On the
faster write-only model, QD4 async recorded only 30 producer-tail claims against
5346 ordered-inline preparations; QD8 recorded only 9 tail claims against 5363
inline preparations. The producer therefore usually receives work after the
ordered worker has already consumed the useful preparation interval.

## Immediate work queue

1. Test one bounded accepted-wave preparation kick. After the ordered worker
   atomically captures a finite incoming wave, it may grant one producer tail
   credit only when at least two unclaimed WRITE preparations already exist.
   This supplies real FIFO-distance evidence without waiting for future BIOs.
2. Preserve the producer-side singular-head guard, one-for-one tail pacing,
   head-first preparation during synchronous lower WRITE wait, sole ordered
   mapping/publication ownership, retained-window policy, extent planning,
   lower-byte/read policy and GC behavior.
3. Attribute the idle timeline directly: accumulate producer LZ4 time wholly
   contained inside lower-WRITE waits, actual ordered completion-wait time, and
   accepted-wave producer kicks. Do not add overlapping wall counters together.
4. Remove dead coordination state. `ordered_worker_busy` had no reader and is
   deleted; rejected experiment state is not retained as production archaeology.
5. Keep raw and sync as compact performance controls, but move verbose cache,
   window and per-control diagnostics out of the console. The complete evidence
   remains in `build/test_results.json.xz`.
6. Acceptance is simultaneous: QD1 must keep zero producer claims; QD4/QD8
   producer participation should increase without recreating blocking handoff
   convoys; QD8/QD32 lower-request geometry should remain near 520/~138;
   faster mixed lower WRITE requests and worker-empty deadlines must not regress;
   lower WRITE bytes and packed-read tails remain hard gates.
7. Statistically repeated saturation, sustained GC with nonzero victims,
   genuine lower-error coverage and kernel-worker CPU attribution remain
   release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
