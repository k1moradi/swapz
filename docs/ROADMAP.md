# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

Owner qualification of `c8ba1180310878141f2179a3ce0fa6d95f93f049`
passed all five stages; the canonical report was published as report-only commit
`b0dc69a00c01a8301d553e3d109b963a7b15a10b`. The two latency models are
owned-RAM synthetic evidence, not protocol/media claims about every SD card,
HDD, SATA SSD or NVMe device.

The slow model (10 MiB/s, 1 ms completion) reached 7.11 MB/s mixed async WRITE
versus 7.09 sync and 7.84 raw. The fast model (80 MiB/s, 0.15 ms completion)
reached 21.37 MB/s async versus 19.81 sync and 18.85 raw: a preliminary async
gain over both controls. Write-only remains directional: slow-model QD8/QD32
async reached 11.35/13.23 MB/s; fast-model QD8 reached 26.61 MB/s (+29.4%
versus sync) while QD4 regressed -2.6% and QD32 improved only +2.6%.

Step-1 publication attribution is now answered. Slow-model publication was
21.3 ms: 12.4 ms final-image payload CRC and 8.9 ms authority/liveness work.
Fast-model publication was 18.2 ms: 9.9 ms CRC and 8.3 ms authority. Thus the
mandatory final payload CRC accounts for about 58% / 54% of publication wall
on these models. It is a real serialized cost, but skipping it remains
disallowed because it is the final integrity check over `bulk_scratch`.

The remaining commit residual is also still material: about 9.2 ms slow and
8.2 ms fast after planner/pack/publish attribution. Splitting stage/pause hash,
allocation/alignment clearing and control work therefore remains worthwhile
diagnostic work.

The lower-WRITE starvation probe rejects the idea that the current synchronous
design merely needs more preparation workers. Slow-model lower WRITE occupied
about 613 ms while preparation-LZ4 overlap was only 0.2 ms; mean unclaimed
preparation queue depth was 0.00 at both lower-WRITE start and end. Only about
1.5 start samples per pair were nonempty and none remained nonempty at end.
Fast-model lower WRITE occupied about 220.7 ms with 6.8 ms preparation overlap;
mean queue depth was only 0.11 at start and 0.07 at end. There is not sustained
eligible backlog for extra workers or extra credits to consume in the present
stop-and-wait ownership model.

This evidence instead promotes an asynchronous ping-pong architecture: while
one immutable sealed write run is in flight, a separate active collector may
accept, LZ4-compress and CRC new pages and maintain the global packing view.
When the in-flight run completes, the prepared collector can be sealed/planned
and submitted without waiting for compression. This is not permission to split
one well-packed outstanding QD wave merely to manufacture overlap: acceptance
still requires no regression in lower bytes/requests, correctness or tails.

Loaded live GC now also closes the Step-1 distribution question: 20 live
victims produced 20 role rotations across 20 distinct victim segments with
1/1 min/max evictions, nonzero GC READ/WRITE traffic and byte-exact verification
of all 4096 logical pages. Synthetic victim distribution is therefore qualified
and no longer blocks a bounded dead-segment DISCARD/TRIM experiment. Physical
wear/endurance claims remain blocked.

Packed-read results do not justify CPU-copy optimization. Slow-model packed
read p99 was worse than raw despite fewer lower requests; fast-model packed
reads were close but did not meet the faster verdict. Lower READ wall dominates
LZ4/copy cost. Any read-queue redesign must therefore be latency-first: dispatch
immediately when the device is idle, and only coalesce/reorder already-waiting
reads while lower I/O is busy.

The rejected `task_cputime_adjusted()` metric, CPU-local/bound preparation,
and dry microsecond grace experiment remain deleted.

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
| 2 | Commit plan/pack/publish attribution | **1** | Qualified; keep as the serialized-path diagnostic split. |
| 3 | Global serialized publication/authority on one shared backing device | **1** | Keep as the correctness boundary; preparation and lower-I/O submission may pipeline around it. |
| 4 | `WQ_UNBOUND` preparation placement | **1** | Qualified placement; scheduler load-balancing is preferred to CPU pinning. |
| 5 | Inline RAW no-bounce staging | **1** | Qualified; explicit copy cost remains small. |
| 6 | `task_cputime_adjusted()` per-callback CPU attribution | **2** | Rejected metric and deleted; short callbacks were materially undercounted. |
| 7 | CPU-local/bound preparation worker | **3** | Rejected and deleted; internal overlap improved while useful behavior regressed. |
| 8 | Maximize LZ4/lower-I/O overlap as the optimization objective | **3** | Rejected; overlap is diagnostic, not an acceptance metric. |
| 9 | Precompute payload CRC during preparation and pass it to packing | **1** | Qualified; keep. |
| 10 | Validate immutable metadata once in `swapz_finish()` | **1** | Qualified; keep. |
| 11 | Split final-image publish CRC from authority/liveness work | **1 completed measurement** | Qualified diagnostic: CRC is 12.4/21.3 ms slow and 9.9/18.2 ms fast; authority is 8.9/8.3 ms. |
| 12 | Split stage/pause hash/hole-clear residual | **4** | Promote in priority: residual is still ~9.2 ms slow / 8.2 ms fast. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered and telemetry deleted; millisecond followups refute a general microsecond grace fix. |
| 14 | Controlled multi-credit preparation replenishment in the current synchronous design | **5** | Step-1 queue evidence refutes it as a standalone fix: there is no sustained unclaimed backlog to spend more credits on. Revisit only inside a pipelined collector if backlog appears. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Mandatory statistical evidence gate before performance claims. |
| 16 | N=2/4 prep workers with the current one-credit/single-work-item design | **5** | Refuted as formulated; more workers cannot consume absent eligible work. |
| 17 | Prepared-page pointer handoff solely to remove current copies | **5** | Copy cost is too small for the ownership complexity. |
| 18 | Rewrite the bounded DP planner | **5** | Planner remains ~5-6 ms and is not the dominant serialized phase. |
| 19 | Skip final publish-side payload CRC | **5** | Rejected; measured cost is material but it is the final-image integrity boundary. |
| 20 | Remove batch pause/resume transaction CRC immediately | **5** | Do not weaken snapshot protection without isolated residual evidence. |
| 21 | Direct LZ4 decompression into the read BIO | **5** | Stronger rejection: read copy is ~1-1.4 ms while lower READ wall is ~104-676 ms. |
| 22 | DMA/hardware offload specifically for current 4KiB copies | **5** | Targets the wrong bottleneck. |
| 23 | Per-CPU independent authorities on one shared device | **5** | Reject; fragments ordering/allocation/GC and the global packing view. |
| 24 | Accurate kernel-worker on-CPU attribution by another mechanism | **6** | Still required before CPU-pressure or heterogeneous-core policy claims. |
| 25 | Async lower-I/O state machine with immutable run ownership | **4** | **Promoted to the primary architecture experiment.** Lower-WRITE wall is large while current prep backlog is nearly absent; immutable slots are the correctness prerequisite. |
| 26 | NUMA-local preparation domains | **6** | Hardware-blocked until a real NUMA system can qualify locality. |
| 27 | One swapz instance per NUMA node with genuinely node-local NVMe | **6** | Deployment topology, not the default shared-device design. |
| 28 | Sustained live-GC workload | **1** | Qualified mandatory gate: 20 victims/20 rotations/4096 verified pages. |
| 29 | Dead-segment DISCARD/TRIM | **4** | **Now ready for bounded synthetic evidence:** victim spread qualified at 20 distinct, 1/1 min/max. Physical-media admission remains separate. |
| 30 | Tiny microsecond grace timer after dry PACK_READY | **5** | Refuted and deleted. |
| 31 | Shared descriptor queue + multiple unbound CPU-preparation workers | **4 dependent** | Keep, but do not test standalone yet. Current lower-WRITE queue depth is too small; test N=1/2/4 only after the ping-pong collector creates sustained eligible backlog. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form; use bounded unbound concurrency instead. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented through `crc32c()`; keep architecture-selected implementation. |
| 34 | Hand-selected SIMD/CPU instructions beyond kernel/LZ4 primitives | **6** | CRC is now proven material, but first prove the active kernel backend and trustworthy CPU cost before bypassing kernel primitives. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Interface/hardware-dependent; preserve integrity and ordering before evaluation. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory gate before accepting a multi-worker/pipelined architecture. |
| 37 | Ping-pong WRITE pipeline: active collect/prepare vs immutable sealed/stream run | **4** | **New leading optimization.** Compress+CRC during collection, preserve one global packing view, then seal and submit when a lower slot is available. |
| 38 | Shared accumulator feeding bounded K in-flight lower-write slots | **4** | Use explicit K experiments; do not shard the accumulator per device lane. Serial testing means one lower run outstanding plus a separate collector; parallel devices may raise K only with evidence. |
| 39 | Latency-first READ busy-time queue: idle bypass + coalesce/reorder waiting reads | **4 dependent** | Requires per-request/per-worker read scratch first. Never wait for a batch when lower I/O is idle; only organize reads that are already blocked behind active lower I/O. |
| 40 | Freeze queue first, then start LZ4/CRC | **5** | Reject this formulation: it creates a CPU gap after lower I/O completes. Compression must happen during collection. |
| 41 | Isolated per-lane write accumulators / 2xN write queues | **5** | Reject as default: sharding destroys the global page-size view and can increase slack/lower requests. Parallelism belongs in sealed in-flight runs, not independent authorities/packers. |

## Interpretation of the ping-pong proposal

The core proposal is accepted for testing with three exact refinements.

First, the active write collector performs per-page zero detection, LZ4 and
payload CRC as BIOs arrive. The collector may update reorder/planning inputs as
lengths become known. “Freeze” means ownership becomes immutable; it must not
mean “begin compression now.”

Second, the lower device contributes **time for CPU work**, not compression
ratio by itself. Packing density improves only if a shared collector actually
has more prepared pages to choose from. The current closed-loop QD32 workload
can consume an entire outstanding wave in one well-packed run, so device busy
time does not automatically create another upper wave. Do not deliberately
split a good run just to create overlap unless measured useful throughput,
lower bytes/requests and tails all improve.

Third, distinguish collector buffers from lower queue depth. A serial lower
path needs at least two ownership domains (one immutable streaming run and one
active collector) but only one lower run outstanding. A parallel lower path may
permit multiple immutable runs outstanding, while still using one shared
collector/global planner. Start with explicit K=1/2/4/8 qualification rather
than inferring policy from protocol names or CPU topology.

Same-page ordering remains a hard gate. If logical page P is present in an
in-flight run, a later write to P must either reserve the next generation at
stage time or fence publication until the older run commits. Completed runs
publish in the required ordering domain; upper BIO completion still follows
successful lower I/O and fail-closed authority publication.

## Immediate work queue

1. Implement the bounded immutable `swapz_io_run` ownership object/pool first:
   packed bytes, staged transaction descriptors, generations, upper-BIO
   references, lower-I/O result, PREFLUSH/FUA ordering and completion state.
2. On top of that ownership, implement the WRITE ping-pong experiment with one
   active collector and one lower run outstanding. LZ4/CRC happens during
   collection; seal/plan/pack must be ready before the lower slot is reusable.
3. Compare against the current source without intentionally fragmenting a
   packable QD32 wave. Acceptance requires byte-exact correctness, no
   lower-byte/request regression, maintained read tails and useful throughput.
4. Only if a pipelined collector shows sustained eligible CPU backlog, compare
   N=1/2/4 unbound preparation workers and bounded credits. The old Step-1
   evidence is insufficient to justify extra workers in isolation.
5. Only after single-lower-slot ping-pong qualifies, test multiple immutable
   in-flight lower runs with explicit K=2/4/8. Keep one global accumulator and
   authority; do not create per-lane packers.
6. Prepare READ parallelism separately: give each request/run private scratch,
   dispatch immediately when lower I/O is idle, and only coalesce/reorder reads
   already waiting behind active lower work.
7. Run a bounded owned-RAM dead-segment DISCARD/TRIM experiment now that GC
   victim spread is qualified.
8. Split the ~8-9 ms commit residual and implement >=5 matched pairs plus
   CPU-pressure/low-RAM qualification before promoting architecture results.

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
