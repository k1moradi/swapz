# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `f10a1e0173f45e6daf52773d0b4a559b7df7ddb7` remains the
accepted directional performance baseline. Source
`44363933e9e401ccaf3a3af6c1fa42b2878d2bab` passed all five stages and is
qualified exploratory evidence, but is not promoted.

The credited-preparation run preserved the deep write-only geometry: QD8 used
520 lower WRITE requests in async mode on both RAM models, and faster-model
QD32 async used 139 requests. QD1 async remained a lone-head path with zero
producer claims and 0.37 ms p99.

The new preparation counters rejected the one-shot execution-time credit
hypothesis for write-only bursts. On the faster model QD8 async recorded only
one producer tail claim against 5366 ordered-inline preparations; QD32 recorded
two tail claims against 5350 ordered-inline preparations. Useful throughput
therefore showed no asynchronous gain: 17.32 MB/s at QD8 and 31.15 MB/s at
QD32, approximately equal to sync.

Mixed QD32 did expose producer work because its longer ordered service intervals
kept credits consumable: slow async averaged 5023.5 producer-tail claims and
82.5 blocking waits, while faster async averaged 5464 tail claims and 275
blocking waits. Mixed throughput was 7.14 MB/s on the slow model and
20.49 MB/s on the faster model, with lower WRITE savings preserved. Faster
mixed still recorded about 70 worker-empty deadline closes, but retention
policy is not part of the next scheduling experiment.

The write-only pilot remains one pair per mode/QD with no confidence interval,
and the loaded run again reported zero GC victims. No physical-media or
endurance claim is permitted.

## Immediate work queue

1. Qualify a scheduling-only successor to `4436393`. Keep retained-window,
   extent-planning, lower-byte, read-tail and GC policy unchanged.
2. Define `preparation_tail_credit` as one token earned by ordered inline
   WRITE work in the currently open retained burst. Permit that token to survive
   the end of the individual `swapz_process()` call until the producer
   consumes it or the nonempty window closes.
3. Let an already-running producer consume a newly earned token without forcing
   a workqueue return/re-wake between every prepared page. Never permit
   uncredited tail draining.
4. Keep `batch_count` worker-private. The map path wakes preparation only for
   `lower_write_active` or an earned atomic tail token; it must not depend on
   `ordered_worker_busy` to bridge an inter-BIO gap.
5. Run the ordered Device Mapper worker on a serialized
   `WQ_MEM_RECLAIM | WQ_UNBOUND` workqueue so copy/LZ4 execution is not
   forced onto the submitting CPU. Publication and lower-I/O ownership remain
   single-threaded.
6. Acceptance requires QD1 to retain zero producer claims, QD8/QD32 lower
   requests to stay near 520/~139, and write-only async producer-tail work to
   become substantial without blocking waits turning into a convoy. Reject any
   throughput gain that raises lower WRITE bytes or regresses packed-read tails.
7. Revisit the residual faster mixed worker-empty deadline cluster only after
   preparation scheduling is isolated. Sustained GC, genuine lower errors,
   kernel-worker CPU attribution and statistically repeated saturation remain
   release gates.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
