# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner-loaded source `d63ab97c6cb104dc99c4792c207805e97e22d233` passed all
five qualification stages. Direct single-bvec BIO-to-LZ4 input remained fully
effective, explicit WRITE-copy cost stayed near 4 ms / 11 MiB on the faster
model, and write-only QD8 async reached 27.00 MB/s versus 19.58 sync (+37.9%)
with 524 lower WRITE requests. Mixed faster-model async reached 20.87 MB/s
versus 19.73 sync, but lower WRITE requests rose to 1078 and one-page
PACK_READY closes / worker-empty deadlines rose to 138.2 / 71.5. The stronger
historical mixed geometry at `e5c1721` therefore remains a useful reference.

The attempted per-callback CPU metric is rejected. `task_cputime_adjusted()`
can still rely on scheduler-accounted state that is too coarse for short,
nonblocking preparation callbacks under ordinary tick accounting. Production
must not infer producer saturation from that counter. The next source removes
those misleading CPU fields and reports callback wall residency only, explicitly
as wall time that may include scheduler delay and, for the ordered worker,
synchronous lower-I/O sleep.

Commit attribution is stable: faster-model mixed reports about 5.2 ms planner,
16.5 ms pack, 18.5 ms publish and 8.4 ms residual inside 48.5 ms commit non-I/O.
Two source-level redundancies are now strong enough to test without weakening
publication safety:

1. compute the compressed payload CRC during preparation/inline LZ4 and pass it
   into packing, removing the first serialized payload rescan;
2. validate the immutable SWZ3 metadata image once in `swapz_finish()`, then
   decode each already-validated descriptor and still verify every final
   `bulk_scratch` payload CRC before publishing mappings.

The publish-side payload CRC remains mandatory because it validates the final
image after the `batch_bytes -> bulk_scratch` copy. Transaction/generation/
liveness checks remain fail-closed.

The scheduling hypothesis is also promoted to direct measurement rather than
policy change. A worker-tail dry PACK_READY close records a timestamp only when
`incoming` is actually empty under `queue_lock`; the next admitted WRITE
records the elapsed time into <=10us, 11-50us, 51-200us and >200us bins. No
retention interval, credit count or worker count changes in this probe.

## Immediate work queue

1. Qualify the precomputed pack-side payload CRC and one-pass metadata
   validation. Accept only if correctness, lower bytes/requests and read tails
   remain intact and pack/publish wall time falls in the corresponding phase.
2. Use dry-close -> next-arrival timing to validate or refute the hypothesis
   that the ordered worker is closing useful retained work only microseconds
   before companion BIOs reach `->map`. Only after that evidence may
   multi-credit pacing or retention policy change.
3. Keep rejected CPU-local preparation and "maximize overlap" experiments
   deleted. They improved an internal overlap metric while regressing useful
   mixed throughput/request geometry.
4. Do not add N=2/4 preparation workers until sustained eligible backlog is
   demonstrated. More workers cannot repair a one-token/no-work dispatch gap.
5. The mandatory loaded smoke now includes a dedicated 16MiB logical / 64MiB
   physical owned-RAM pressure phase. Five deterministic incompressible logical
   generations retain one survivor per old segment, must produce at least two
   live GC victims and role rotations with nonzero GC READ/WRITE traffic, and
   verify all 4096 logical pages byte-exact afterward.
6. After nonzero live-GC qualification, add segment reuse-distribution evidence
   (per-segment role rotations/reuse counts, spread/max-min) before any physical
   endurance claim or lower DISCARD/TRIM experiment.
7. Implement >=5 counterbalanced matched pairs before promoting QD8 or mixed
   throughput from directional/preliminary to confirmatory evidence.

## NUMA / deployment topology

Preparation should become NUMA-local only after bounded multi-worker scaling is
proven. The preferred architecture is one preparation domain per memory-local
NUMA node (node-local LZ4 workmem/scratch/prepared pools, routed by source page
home), feeding one global ordered mapping/allocation/GC authority when all nodes
share one backing device. Do not equate a Linux NUMA node one-to-one with a
physical memory controller without hardware-specific topology evidence.

A fully independent `swapz` instance per NUMA node is a deployment topology,
not the default single-target design. It is appropriate to evaluate when each
NUMA node also has genuinely node-local backing storage (for example an NVMe
behind that node's PCIe root complex). If multiple nodes share one backing
device, preserve one global storage authority so extent packing, barriers,
physical allocation and GC do not fragment across independent writers.

## Release gates

A release or physical-media trial remains blocked until the same pinned source has repeated byte-exact loaded correctness, genuine lower error coverage, sustained GC, bounded resource behavior, acceptable read p95/p99 and CPU/RAM, statistically defensible matched performance, and an independent safety review. Physical-device admission is not part of the current roadmap implementation.
