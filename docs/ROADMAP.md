# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`6642e7ebfce3255267f51fe99b66114122bda7e0` passed all five owner-loaded
qualification stages and remains the preferred exploratory preparation/window
source.

At `6642e7e`, preserving a singular FIFO head eliminated the preparation
convoy without damaging deep write-only aggregation. SSD-model QD8 async used
520 lower WRITE requests and reached 26.24 MB/s against 19.58 sync; QD32 async
used 138 requests and reached 46.87 MB/s. Those write-only numbers are
single-pair directional evidence only. Mixed SSD async reached 21.80 MB/s with
1007 lower WRITE requests, 26.5 preparation blocking waits, 136 one-page
PACK_READY closes and 59.5 worker-empty deadlines. Packed read p99 was below
raw on that faster model.

Source `2ad805b02da02af95eed78945338876f831e61e0` also passed all five
qualification stages but regressed the measured objective and is rejected.
Suppressing credit-driven producer wakeups on an instantaneous singular-list
snapshot reduced SSD mixed async to 20.92 MB/s, raised lower WRITE requests to
1091.5, raised worker-empty deadlines to 74 and one-page PACK_READY closes to
146. SSD QD8 async fell to 20.74 MB/s while producer claims remained sparse.
The change therefore saved no meaningful preparation work and disturbed useful
retained-window scheduling/coalescing.

Slow-model mixed lower WRITE savings remained intact in both runs, and the
loaded run again recorded zero GC victims. No physical-media or endurance claim
is permitted. The project must not treat the one-pair write-only variation as
established performance.

## Immediate work queue

1. Restore `6642e7e`'s credit-driven wake behavior exactly while retaining its
   producer-side singular-head guard. Tail eligibility belongs in the producer,
   immediately before credit consumption under `queue_lock`.
2. Forbid mapper-side or inline-WRITE singular-list pre-screening. A queued
   producer may safely wake and reject a lone head without consuming its token;
   workqueue coalescing and a companion admission before execution are part of
   the measured schedule.
3. Keep persistent credit lifetime, unbound placement, dry-PACK_READY evidence
   consumption, retained targets, extent planning, lower-byte/read policy and
   GC unchanged for the rollback qualification.
4. Acceptance requires the current source to recover toward the qualified
   `6642e7e` mixed SSD result: roughly 1007 lower WRITE requests, about 60
   worker-empty deadlines, low preparation waits and no packed-read regression.
   QD1 must retain zero producer claims, QD8/QD32 request geometry must stay
   near 520/~138, and lower WRITE bytes remain a hard gate.
5. Do not add another preparation-ahead heuristic until the rollback is
   requalified. Further overlap work needs bounded FIFO-distance evidence
   rather than an instantaneous wake-site list snapshot.
6. Statistically repeated saturation, sustained GC with nonzero victims,
   genuine lower-error coverage and kernel-worker CPU attribution remain
   release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
