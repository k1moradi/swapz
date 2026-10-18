# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`6642e7ebfce3255267f51fe99b66114122bda7e0` passed all five owner-loaded
qualification stages and is qualified exploratory evidence, not promoted.

The singular-head guard eliminated the `6330cb5` preparation convoy while
preserving write-only request aggregation and improving the mixed faster model.
Faster-model QD4/QD8/QD32 async blocking waits fell to zero, but tail
preparations fell to only 16/14/0. QD8 retained 520 lower WRITE requests and
QD32 retained 138, with QD1 still at zero producer claims. Faster-model
write-only QD8 async reached 26.24 MB/s versus 19.58 sync; QD32 async reached
46.87 MB/s versus 46.01 sync. Those one-pair results are directional only and
do not establish a reproducible gain.

Mixed faster-model async reached 21.80 MB/s with 1007 lower WRITE requests,
26.5 preparation blocking waits, 136 one-page PACK_READY closes, 59.5
worker-empty deadlines and packed read p99 below raw. Slow mixed remained
7.09 MB/s async with 544.5 lower WRITE requests and 12.0 blocking waits.
The lower-WRITE byte savings and existing read-tail limitations are still gates.

The qualified result shows that a one-entry preparation queue is too shallow
for useful opposite-end stealing under staggered write-only admission: the
guard eliminates harmful overlap but its repeated producer wake/return cycles
are scheduling overhead. There is not yet evidence that another eligibility
relaxation would improve actual throughput rather than rebuild the convoy.

The loaded run again recorded zero GC victims, so no physical-media or
endurance claim is permitted. Write-only saturation remains one pair per
mode/QD with no confidence interval.

## Immediate work queue

1. Keep `6642e7e`'s singular-head producer guard, persistent credit lifetime,
   unbound workqueue placement, retained targets, extent planning, physical
   byte policy, read policy and GC unchanged.
2. Suppress a producer wake in the inline-WRITE path when the protected
   preparation list is empty or singular. Preserve that earned token for the
   next real two-entry head/tail opportunity.
3. Under the same `queue_lock`, wake from `->map` on retained credit only when
   at least two unclaimed preparation entries exist. The independent active
   lower-WRITE wake must remain unconditional on list length.
4. Reject this scheduling-only experiment if it reduces mixed useful
   throughput, raises backing WRITE bytes/requests, harms packed READ p99, or
   causes QD1 producer claims or blocking waits. QD8/QD32 write-only requests
   should remain near 520/~138; tail claims cannot be manufactured from a
   singular FIFO head.
5. If skipping redundant wakes proves insufficient, further write-only
   parallelism requires an independently reviewed, bounded FIFO-preserving
   preparation-ahead design, not the proven harmful singular-head steal.
   Statistically repeated saturation, sustained GC, genuine lower errors and
   kernel-worker CPU attribution remain release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
