# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `a7996ecf20241fa8bde6d64fc961891bc4de94ac`
passed all five stages; the canonical report was published as report-only commit
`e3a4ffd87c348de1b9d1a4bf4e0a52486c6f53b8`. The two current latency
profiles are owned-RAM `null_blk` evidence, not protocol/media claims about
every SD card, HDD, SATA SSD or NVMe device.

The current slow profile (10 MiB/s, 1 ms timer completion) applies enough
upper-layer pressure to saturate the raw path: mixed QD32 raw reaches
7.84 MB/s WRITE + 2.60 MB/s READ. However, the profile does not explicitly
configure `null_blk` queue mode, submission-queue count or hardware queue
depth. Current Linux `null_blk` defaults are multi-queue, one submission queue
and hardware queue depth 64. Timer completion delays each I/O independently.
Therefore the current `SD_EMULATED` label is evidence for a low-bandwidth,
high-latency queued device, not proof of behavior on a strict one-command-at-a-
time SD/HDD path. A true serial-depth model is now mandatory before drawing
strong conclusions about high-latency serial media.

On that current slow queued model, async mixed WRITE is 7.10 MB/s versus
7.08 sync and 7.84 raw. Lower WRITE traffic falls to 4.83 MB/s and about
547.5 requests versus ~12203 raw requests, but useful mixed throughput does not
increase. Preparation-LZ4 overlaps only ~0.2 ms of ~606.6 ms lower-WRITE wall
and the unclaimed preparation queue remains 0.00/0.00 at lower-WRITE
start/end. The problem is not insufficient raw offered pressure; swapz is not
converting that pressure into a deep lower queue or useful concurrent CPU work.

The fast queued model (80 MiB/s, 0.15 ms) reaches 19.41 MB/s async WRITE versus
19.58 sync and 19.54 raw. Async increases lower-WRITE requests to ~1285 versus
~1046 sync, while LZ4/lower-I/O overlap rises to ~10.2 ms and preparation queue
depth to 0.31/0.08. More overlap again fails to imply higher useful throughput.

Write-only QD8 remains the repeatable conditional signal. Slow-model QD8 async
is +3.1% versus sync. Fast-model QD8 is +23.8%; previous owner runs also showed
large positive QD8 deltas. Neighboring QD4 regresses and QD32 remains nearly
flat. This keeps K=1 ping-pong as a narrow queue-geometry experiment, not a
default policy. The one-pair-per-QD pilot remains directional only.

Publication attribution remains stable. Slow publication is ~20.6 ms:
11.9 ms final-image CRC and 8.7 ms authority/liveness. Fast publication is
~19.1 ms: 9.9 ms CRC and 9.2 ms authority. Final CRC is therefore the largest
single **publication subphase**, but it is not the main end-to-end bottleneck.
Lower I/O wall and queue/serialization behavior dominate the workload, followed
by LZ4 preparation and total commit non-I/O work.

The unexplained commit residual remains ~9.2 ms slow / 8.9 ms fast. Splitting
stage/pause hash, allocation/alignment clearing and other control work remains
worthwhile, but lower-queue behavior now has higher architectural priority.

Packed reads are device-model dependent. Slow-model sequential/random packed
p99 is 19.94/22.85 ms versus 14.15/13.52 raw and remains NOT_FASTER despite
reduced lower traffic. Fast-model packed reads qualify FASTER: sequential/
random p99 4.96/5.81 ms versus 5.90/6.07 raw, while lower bytes and requests
also fall. Read optimization must remain latency-first and device-model aware.

Loaded live GC remains qualified: 20 live victims, 20 role rotations, 20
distinct victim segments, 1/1 min/max evictions, nonzero lower READ/WRITE
traffic and byte-exact verification of all 4096 logical pages.

The rejected `task_cputime_adjusted()` metric, CPU-local/bound preparation,
dry microsecond grace experiment and freeze-then-compress design remain deleted
or rejected.

## Current bottleneck ranking

These wall counters overlap and must not be added as if they formed one serial
timeline. The table ranks measured cost/importance, not an additive runtime
budget.

| Rank | Slow queued model | Wall | Fast queued model | Wall | Interpretation |
|---:|---|---:|---|---:|---|
| 1 | Lower WRITE / lower-device serialization | **606.6 ms** | Lower WRITE / lower-device serialization | **255.1 ms** | Dominant measured write-path wall. Current queue model and swapz lower concurrency are the first-order issue. |
| 2 | LZ4 preparation | **142.8 ms** | LZ4 preparation | **96.8 ms** | Largest CPU preparation phase; mostly fails to overlap slow lower I/O. |
| 3 | Commit non-I/O total | **50.5 ms** | Commit non-I/O total | **45.8 ms** | Serialized CPU/control work worth optimizing only after queue geometry is understood. |
| 4 | Publish total | **20.6 ms** | Publish total | **19.1 ms** | Largest commit subphase. |
| 5 | Pack | **14.7 ms** | Pack | **11.9 ms** | Includes final extent construction; already improved by prehashed CRC. |
| 6 | Payload CRC during preparation | **14.9 ms** | Payload CRC during preparation | **10.1 ms** | Parallelizable preparation cost. |
| 7 | Final-image publish CRC | **11.9 ms** | Final-image publish CRC | **9.9 ms** | Largest single publish subcomponent (~58%/~52% of publish), mandatory integrity boundary; **not** the main end-to-end bottleneck. |
| 8 | Commit residual | **9.2 ms** | Commit residual | **8.9 ms** | Still unexplained enough to justify a bounded attribution split. |
| 9 | Publish authority/liveness | **8.7 ms** | Publish authority/liveness | **9.2 ms** | Similar magnitude to final CRC on the fast model. |
| 10 | Planner | **6.0 ms** | Planner | **5.8 ms** | Not worth a planner rewrite from current evidence. |
| 11 | Explicit RAM copies | **4.7 ms** | Explicit RAM copies | **4.2 ms** | Too small to justify complex DMA/copy-elimination work. |

For packed reads, lower READ wall is even more dominant relative to CPU:
~509/673 ms slow sequential/random versus ~6.9/7.8 ms engine non-I/O, and
~103.5/121.2 ms fast versus ~5.7/7.3 ms engine non-I/O.

## Optimization evidence table

Classes are evidence states: **(1)** tested-valid/keep, **(2)** tested-invalid
because the implementation or metric cannot answer the intended question,
**(3)** tested-invalid despite a sound experiment, **(4)** ready for a bounded
experiment/evidence collection, **(5)** refuted/not worth implementing from
current evidence, and **(6)** architecture/deployment/evidence gate rather than
an immediately qualified optimization. IDs are stable even when priority
changes.

| ID | Idea | Class | Current decision |
|---:|---|---|---|
| 1 | Direct single-bvec BIO -> LZ4 input | **1** | Qualified; keep the owned-page direct input and fallback. |
| 2 | Commit plan/pack/publish attribution | **1** | Qualified; keep. |
| 3 | Global serialized publication/authority on one shared backing device | **1** | Keep correctness authority; pipeline preparation/I/O around it rather than splitting it. |
| 4 | `WQ_UNBOUND` preparation placement | **1** | Qualified placement; scheduler load-balancing remains preferred to affinity. |
| 5 | Inline RAW no-bounce staging | **1** | Qualified; copy cost remains small. |
| 6 | `task_cputime_adjusted()` callback CPU attribution | **2** | Rejected metric and deleted. |
| 7 | CPU-local/bound preparation worker | **3** | Rejected and deleted. |
| 8 | Maximize LZ4/lower-I/O overlap as the objective | **3** | Reinforced rejection: fast overlap rose to 10.2 ms without useful mixed throughput gain. |
| 9 | Precompute payload CRC during preparation | **1** | Qualified; keep. |
| 10 | Validate immutable metadata once during finish | **1** | Qualified; keep. |
| 11 | Split final-image publish CRC from authority/liveness | **1 completed measurement** | Reconfirmed: 11.9/20.6 ms slow and 9.9/19.1 ms fast are final CRC; CRC is a major publish subphase, not the global bottleneck. |
| 12 | Split stage/pause hash/hole-clear/control residual | **4** | Residual is still ~9 ms; retain as bounded CPU attribution work. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted. |
| 14 | Extra preparation credits in current synchronous geometry | **5** | Slow lower-WRITE queue remains empty; credits cannot manufacture eligible work. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Mandatory before default performance claims; QD8 remains directional. |
| 16 | N=2/4 preparation workers in old single-credit design | **5** | Refuted as formulated. |
| 17 | Pointer handoff solely to remove current copies | **5** | Copy cost remains too small. |
| 18 | Rewrite bounded DP planner | **5** | Planner remains ~6 ms; not dominant. |
| 19 | Skip final publish payload CRC | **5** | Rejected despite measured cost; final immutable-run integrity boundary is mandatory. |
| 20 | Remove batch pause/resume transaction CRC immediately | **5** | No isolated evidence justifies weakening snapshot protection. |
| 21 | Direct LZ4 decompression into read BIO | **5** | Copy remains tiny versus lower READ wall. |
| 22 | DMA/hardware offload for current 4KiB copies | **5** | Wrong bottleneck. |
| 23 | Per-CPU independent authorities on one shared device | **5** | Reject; fragments ordering, GC and global packing. |
| 24 | Trustworthy kernel-worker on-CPU attribution | **6** | Still required for heterogeneous-core and CPU-pressure policy. |
| 25 | Async lower-I/O state machine with immutable run ownership | **1** | Correctness-qualified infrastructure; keep. Performance policy remains separate. |
| 26 | NUMA-local preparation domains | **6** | Hardware-blocked. |
| 27 | One swapz target per NUMA node with node-local backing | **6** | Deployment topology only. |
| 28 | Sustained live-GC workload | **1** | Reconfirmed: 20 victims/rotations, 4096 verified pages. |
| 29 | Dead-segment DISCARD/TRIM | **4** | Synthetic victim distribution remains qualified; bounded owned-RAM experiment is ready. |
| 30 | Tiny microsecond grace timer | **5** | Refuted and deleted. |
| 31 | Shared descriptor queue + multiple unbound prep workers | **4 dependent** | Do not generalize yet. Fast model shows shallow backlog; slow model shows none. Only revisit after queue-shape evidence, beginning with N=2 in a repeated QD8 regime. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented; keep architecture-selected kernel backend. |
| 34 | Hand-selected SIMD/instructions beyond kernel/LZ4 | **6** | CRC is measurable, but verify active backend/on-CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Hardware/interface dependent. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory before multi-worker/pipeline promotion. |
| 37 | K=1 ping-pong WRITE pipeline | **4 conditional** | Correctness-qualified but not a mixed-QD32 win. Keep opt-in because write-only QD8 repeatedly improves; require repeated matched pairs. |
| 38 | Shared accumulator with K>1 lower-write slots | **5** | Do not increase K yet; K=1 already inflates fast mixed request count without throughput gain. |
| 39 | Latency-first READ busy-time queue | **4 dependent** | Device-model dependent: fast packed reads now qualify faster while slow packed reads regress. Requires private read scratch and idle bypass. |
| 40 | Freeze first, then start LZ4/CRC | **5** | Rejected; compression belongs during collection. |
| 41 | Per-lane isolated write accumulators / 2xN packing queues | **5** | Reject by default; destroys global packing view and risks request inflation. |
| 42 | Explicit serial-vs-parallel lower queue model + lower in-flight-depth telemetry | **4 highest priority** | **New.** Current slow profile is not a strict one-head model. Add a serial-depth owned-RAM profile with explicit queue parameters (including hardware queue depth 1), record configured/observed lower queue depth, and compare against the existing queued profile before making SD/HDD conclusions. |
| 43 | Huge/compound-page RAM input support (folio/THP/hugetlb), not only 4KiB page inputs | **6 roadmap architecture** | **New.** Accept larger/compound memory backing safely. First preserve the 4KiB SWZ3 logical/integrity unit while iterating/mapslicing a folio without extra copies; only later evaluate native larger logical records/extents because they change random-read latency, packing, metadata and on-disk-format assumptions. |

## Why the current slow test does not prove a serial-device result

The QD32 replay is intentionally unpaced and issues each wave concurrently, so
there is substantial upper pressure. The raw arm nearly consumes the complete
10 MiB/s cap. However, replay is closed-loop: the next wave is not submitted
until every operation in the current wave completes. swapz further aggregates
thousands of upper writes into only hundreds of lower writes and currently
allows one immutable lower WRITE run outstanding.

The owned `null_blk` profile sets `mbps`, `irqmode=2` and
`completion_nsec`, but does not yet pin `queue_mode`, `submit_queues` or
`hw_queue_depth`. The kernel default hardware queue depth is much greater
than one. A timer-delayed queued device and a mechanical/single-command device
are different scheduling experiments. The roadmap therefore treats the
existing slow profile as a queued latency model and adds an explicit
serial-depth qualification before interpreting results as SD/HDD behavior.

The serial-depth experiment must record both **offered upper QD** and
**observed lower in-flight depth** for raw/sync/async. It must distinguish:
upper queue occupancy, swapz collector/preparation backlog, block-layer
in-flight requests, and immutable swapz lower-run occupancy. A claim that
high-latency media gives swapz more organization time requires evidence that
upper work remains available while the single lower service slot is busy.

## Huge/compound-page support roadmap

swapz must not permanently assume that useful RAM input arrives as one ordinary
4KiB physical page. Add explicit support for compound/folio-backed inputs,
including transparent huge pages and hugetlb-backed memory where the block path
can expose them.

The first implementation should **not** silently change SWZ3 format semantics:
retain 4KiB logical records, generations, CRC boundaries and random-read units,
but walk/map 4KiB slices of a larger folio directly and avoid bounce copies.
Qualification must cover nonzero bio_vec offsets, boundaries crossing a base
page within a compound allocation, partial BIOs where permitted, lifetime/
pinning rules, direct LZ4 input safety, low-memory reclaim and byte-exact
readback.

A later experiment may evaluate larger native logical records/extents (for
example 16KiB/64KiB or huge-page-aware super-windows). That is a format and
latency experiment, not merely an input optimization: it changes compression
opportunity, metadata density, selective read amplification, CRC scope,
recovery, GC movement and random swap-in cost. It requires separate evidence
before any on-disk-format change.

## Immediate work queue

1. **Fix the storage model before interpreting SD/HDD behavior.** Add an
   explicit serial-depth owned-RAM profile with one hardware service slot and
   record queue-mode/submission-queue/hardware-depth configuration plus
   observed lower in-flight depth. Compare it against the existing queued
   slow profile using the same QD32 trace.
2. Add lower queue-pressure telemetry: current/peak/time-weighted lower
   READ/WRITE in-flight depth and swapz immutable-run occupancy. Existing
   preparation-queue depth is not a substitute for device queue depth.
3. Run >=5 counterbalanced pairs for mixed QD32 and write-only QD8 on the
   relevant queued and serial-depth models before promoting/deleting K=1.
4. Keep K=1 ping-pong opt-in. Do not add K=2/4/8 until lower-depth evidence
   shows an actual parallel service opportunity rather than fragmentation.
5. Split the remaining ~9 ms commit residual; keep the final-image CRC.
6. Prepare latency-first READ queueing with private scratch, especially because
   fast packed reads now qualify faster while the slow queued profile regresses.
7. Run the bounded owned-RAM dead-segment DISCARD/TRIM experiment.
8. Design and qualify huge/compound-page input support while preserving the
   current 4KiB logical/on-disk unit for the first implementation.
9. Add trustworthy kernel on-CPU attribution and heavy-CPU/low-RAM
   qualification before CPU-topology or multi-worker promotion.

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
