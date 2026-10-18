# Roadmap

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

This file contains only active work. Completed experiments and detailed historical transcripts belong in Git history.

## Current baseline

The latest owner-qualified source is
`fda75f9c06d7181623c6f90c0885efbda499e9a6`. All five qualification stages
passed. The generated report was published as the normal report-only successor.
The two RAM-only storage models remain synthetic evidence, not claims about a
particular physical SD card, HDD or SSD.

The slow model (10 MiB/s, 1 ms completion) reached 7.11 MB/s mixed async WRITE
versus 7.07 sync and 7.85 raw. The fast model (80 MiB/s, 0.15 ms completion)
reached 21.05 MB/s async versus 19.78 sync and 19.23 raw. The write-only pilot
shows strong queue-depth dependence: slow-model async beats raw at QD8/QD32,
while fast-model async is -7.1% at QD1, approximately flat at QD4, +33.2% at
QD8 and +4.0% at QD32. Those write-only points are still one matched pair each.

The serialized CPU cleanup qualified. On the fast mixed model, commit non-I/O
fell to about 40.8 ms with 5.3 ms planning, 10.9 ms packing, 16.3 ms publication
and 8.3 ms residual. On the slow model it is about 49.0 ms with 6.1/14.8/18.6
ms plan/pack/publish. Pack-side payload CRC precomputation and one-pass immutable
metadata validation are therefore accepted production optimizations. The
publish-side payload CRC over final `bulk_scratch` remains mandatory.

The slow model exposes the next scheduling problem directly: about 612.6 ms of
lower-WRITE wall time coincided with only about 0.2 ms of preparation-LZ4
overlap. The fast model recorded about 225.1 ms lower-WRITE wall with 7.3 ms
overlap. The closed-loop replay submits the next QD wave only after every BIO
in the current wave completes, while swapz still submits lower READ/WRITE I/O
synchronously through one ordered worker. Higher modeled latency therefore
mostly extends serialized wait instead of automatically becoming preparation
time.

The completed dry PACK_READY arrival experiment is retired from the hot path.
Slow-model followups averaged about 4.706 ms and showed no <=200us concentration;
fast-model followups averaged about 1.468 ms. A microsecond grace/spin policy is
therefore rejected. Current diagnostic source instead measures the exact
unclaimed preparation queue depth at synchronous lower-WRITE start/end.

Loaded live-GC is now a qualified correctness gate: the baseline exercised
20 live victims, 20 role rotations, nonzero GC READ/WRITE requests and verified
all 4096 logical pages byte-exact. The current diagnostic source additionally
counts committed victim evacuations per segment so the next run can establish
reuse-distribution evidence before any DISCARD/TRIM experiment.

The rejected callback `task_cputime_adjusted()` metric and rejected bound/
CPU-local preparation experiment remain deleted. Whole-callback counters are
wall residency only and may contain scheduler delay or synchronous lower-I/O
sleep.

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
| 3 | Global serialized publication/authority on one shared backing device | **1** | Keep as the correctness boundary; CPU preparation may become parallel around it. |
| 4 | `WQ_UNBOUND` preparation placement | **1** | Qualified placement; let the scheduler load-balance instead of pinning work. |
| 5 | Inline RAW no-bounce staging | **1** | Qualified; remaining explicit copy cost is small. |
| 6 | `task_cputime_adjusted()` per-callback CPU attribution | **2** | Rejected metric and deleted; short callbacks were implausibly undercounted. |
| 7 | CPU-local/bound preparation worker | **3** | Rejected and deleted; overlap improved while useful mixed behavior regressed. |
| 8 | Maximize LZ4/lower-I/O overlap as the optimization objective | **3** | Rejected; overlap is attribution, not an acceptance metric. |
| 9 | Precompute payload CRC during preparation and pass it to packing | **1** | Qualified; pack wall fell while final-image CRC remains. |
| 10 | Validate immutable metadata once in `swapz_finish()` | **1** | Qualified; validated descriptor lookup keeps final payload checks. |
| 11 | Split final-image publish CRC from authority/liveness work | **4** | **Instrumented now**; time only the exact final `crc32c()` calls and report authority residual separately. |
| 12 | Split stage/pause hash/hole-clear residual | **4** | Later diagnostic if the ~8-10 ms residual remains material. |
| 13 | Dry PACK_READY close -> next accepted WRITE timing | **1 completed measurement** | Question answered; telemetry deleted. It refutes a general microsecond grace fix. |
| 14 | Controlled multi-credit preparation replenishment | **4** | Test only after the new lower-WRITE queue-depth evidence shows useful eligible backlog. |
| 15 | >=5 counterbalanced pairs for mixed/QD points | **6** | Mandatory statistical evidence gate before performance claims. |
| 16 | N=2/4 prep workers with the current one-credit/single-work-item design | **5** | Refuted as formulated; more workers cannot consume work that is not made eligible. |
| 17 | Prepared-page pointer handoff solely to remove current copies | **5** | Current copy slice is too small for the ownership complexity. |
| 18 | Rewrite the bounded DP planner | **5** | Planner is not the dominant serialized CPU phase. |
| 19 | Skip final publish-side payload CRC | **5** | Rejected; it would remove the final-image integrity boundary. |
| 20 | Remove batch pause/resume transaction CRC immediately | **5** | No evidence it dominates residual; keep fail-closed snapshot protection. |
| 21 | Direct LZ4 decompression into the read BIO | **5** | Read-copy cost is small relative to lower READ wall. |
| 22 | DMA/hardware offload specifically for current 4KiB copies | **5** | Targets the wrong bottleneck. |
| 23 | Per-CPU independent authorities on one shared device | **5** | Reject; would fragment ordering/allocation/GC and aggregation. |
| 24 | Accurate kernel-worker on-CPU attribution by another mechanism | **6** | Mandatory architecture evidence for CPU-pressure/heterogeneous-core decisions; callback wall is insufficient. |
| 25 | Async lower-I/O state machine | **4** | Next architecture phase only after bounded immutable in-flight run slots exist. |
| 26 | NUMA-local preparation domains | **6** | Hardware-blocked until a real NUMA system can qualify locality. |
| 27 | One swapz instance per NUMA node with genuinely node-local NVMe | **6** | Deployment topology, not default shared-device design. |
| 28 | Sustained live-GC workload | **1** | Qualified mandatory gate: 20 victims/20 rotations/4096 verified pages. |
| 29 | Dead-segment DISCARD/TRIM | **4** | Unblocked for evidence work only after victim/reuse spread is measured; physical wear remains unproven. |
| 30 | Tiny microsecond grace timer after dry PACK_READY | **5** | Refuted by measured millisecond-scale followups; experiment telemetry deleted. |
| 31 | Shared descriptor queue + multiple unbound CPU-preparation workers | **4** | Leading Phase-A architecture experiment after Step-1 queue evidence; test explicit N=1/2/4. |
| 32 | One affinity-pinned worker per physical core | **3** | Reject affinity form; use an unbound concurrency cap/hint instead. |
| 33 | Linux kernel CRC32C primitive | **1** | Already implemented through `crc32c()`; keep architecture-selected implementation. |
| 34 | Hand-selected SIMD/CPU instructions beyond kernel/LZ4 primitives | **6** | Hardware-specific; justify only after trustworthy CPU attribution identifies a worthwhile phase. |
| 35 | Firmware/device/upper/lower compute offload | **6** | Interface/hardware-dependent; preserve integrity and ordering before evaluation. |
| 36 | Heavy-CPU plus low-RAM qualification | **6** | Mandatory gate before accepting a multi-worker architecture. |

## Current Step 1 diagnostic source

The current source changes measurement only; scheduling, credit, retention,
authority and synchronous lower-I/O policy are unchanged.

1. Publication attribution exposes `engine_publish_crc_wall_ns` around only the
   final payload `swapz_crc32c_bytes()` calls. The reported
   `engine_publish_auth_wall_ns` is the exact publication residual.
2. Each synchronous lower WRITE samples the exact unclaimed
   `preparation_incoming` descriptor count under `queue_lock` at start and
   end, plus nonempty-event counts. This tests whether the slow-model I/O
   interval actually has preparation work available.
3. Successful committed GC victim rotations increment a bounded per-segment
   eviction counter. Status reports distinct victim segments and min/max
   evictions among those segments.
4. The completed dry-close histogram/timestamp experiment is deleted.

## Immediate work queue

1. Run the official owner qualification on the current Step-1 diagnostic source
   and use the automatically published report to classify publish CRC versus
   authority cost, lower-WRITE queue starvation, and GC victim spread.
2. If meaningful preparation backlog is present, implement Phase A as a bounded
   shared descriptor queue with independent `WQ_UNBOUND` preparation work
   items and private LZ4 workmem/fallback scratch. Compare explicit N=1/2/4;
   physical-core topology is a concurrency hint, never CPU affinity.
3. Replace the binary tail token with a bounded credit count only as part of the
   Phase-A experiment and preserve the FIFO head cushion, prepared-page cap,
   one-completion-owner rule and global publication authority.
4. Before asynchronous lower WRITE, introduce a bounded pool of immutable
   in-flight run objects owning packed bytes, staged transactions, upper-BIO
   references, ordering/FUA state and completion state. Only then test
   asynchronous `dm_io` continuations.
5. Parallel READ service comes later and requires per-request/per-worker read
   scratch; the current read buffers/cache state remain single-owner.
6. Use the new GC victim distribution before any DISCARD/TRIM trial.
7. Implement >=5 counterbalanced matched pairs and deliberate CPU-pressure /
   low-memory qualification before promoting the parallel architecture.

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
