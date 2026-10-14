# Benchmark — Real Lower-I/O Performance Standards

**Authoritative benchmark policy.** Every agent task begins by reading [README](README.md), [VISION](VISION.md), [coding_standards.md](coding_standards.md), [testing_standards.md](testing_standards.md), and [compile.md](compile.md). The decisive goal is **fewer independently measured host-visible lower READ and WRITE bytes AND requests**, including GC and flushes, for identical byte-verified useful work, without unacceptable cold-read p99, CPU, memory or safety cost.

## Required comparison: exact same data and operations

Use three separate, sequential paths with equivalent **fresh test-owned, RAM-backed null_blk** configurations:

| Arm | Definition |
|---|---|
| **off** | bare null_blk, no swapz target, uncompressed 4096-byte direct logical I/O; **NOT `swapoff`** or disabling the host swap |
| **V2.2** | frozen/default SPWZ Device Mapper module on equivalent owned null_blk |
| **V3** | experimental SWZ3 `swapz3` Device Mapper module on equivalent owned null_blk; not production-ready |

The two modules share `dm-swapz.ko` and must never be loaded simultaneously. Variants such as alpha.8 read bypass **must be separately named**, never silently substituted for the pinned V3 tree.

**One immutable 4096-byte page fixture and one immutable logical operation trace per paired run**—generated **once** and supplied unchanged to all three. Verify fixture SHA-256; trace SHA-256; global write payload-stream SHA-256 incorporating logical offset, sequence number and all 4096 bytes; exact prefill SHA; phase/warmup boundaries; read generations; useful completed READ/WRITE operation counts; and **full byte-by-byte readback and final-image SHA**. Reject any mismatched arm or failed-close target. A common random seed used to generate separate traces is not enough.

The existing `tests/runtime/anon-page-fixture.py` and `tests/runtime/threeway-swap-replay.py` implement source fixture and strict wave-based replay; the wave barrier ensures page independence **within a wave**, not identical microsecond arrival timing or representative Linux VM reclaim. A rootless experiment with three scratch files named "off", "v22", "v3" validates only the helper, not real loaded kernel modules. The **loaded three-way replay on current `main` remains NOT RUN**.

## Realistic anonymous-memory compression distributions

Linux typically discards reclaimable *clean file-backed* text/source/ELF/image pages rather than sending them to swap. The main backing-swap workload consists of **anonymous heap, stack, dirty COW/private mappings and swap-backed tmpfs/shmem**; contents can include zero/patterned pages, partially filled object tables, strings, decoded raster, moderate entropy, encrypted/compressed streams and raw incompressible buffers. A DM target has no file-type knowledge. Upstream zswap/zram may change which pages reach backing swap.

Prioritize plausible **compressible anonymous-memory-style** data with **actual measured per-page LZ4 output-size histogram** (tiny, ~1KiB, ~2KiB, ~3KiB and near-cap), mixed moderate-entropy and fully incompressible **negative controls**. Do not label synthetic profile weights "representative 80% compressible" without independent observations. V3 *already* tries LZ4 and uses a whole 4KiB RAW fallback when compression cannot fit `SV3_MAX_COMPRESSED=3568`; this is content-driven selective storage, but failed LZ4 attempts still consume CPU. An entropy prefilter might save CPU **only after** proving false-positive and total I/O costs, and will not by itself fix singleton windows. Count codec attempts separately from successfully committed output and independent lower bytes.

## Measurement and accounting

Snapshot the **exact owned** `/sys/block/<null_blk>/stat` immediately before and after the measured phase; exclude prefill/warmup and post-run oracle reads, but keep active GC during measurement. `lower_read_bytes = delta_read_sectors_512 × 512` and `lower_write_bytes = delta_write_sectors_512 × 512`, regardless of 512n/512e/4Kn reported geometry. One 16KiB write request transfers 16KiB—not four lower commands. Host visible sectors cannot establish NAND wear, erases or internal RMW.

For every accepted trial independently report: achieved useful IOPS and completed operation counts; lower READ requests/bytes; lower WRITE requests/bytes; flush/discard and GC READ+WRITE separately **and included in totals**; READ/WRITE p50/p95/p99 and cold-read p99; kernel worker CPU and userspace helper CPU **separately**; target staging memory; window-size distribution (especially one-page windows); actual LZ4 histogram, packing, padding, compressed/raw population; full logical-image verification and teardown state. Report module SHA/vermagic, kernel, compiler, DM UUID/table, lower identity and counter boundaries. A reduced `dm_io` call count is not independent lower-I/O evidence.

## Experiment design

Run both **saturation** and **matched achieved IOPS + identical useful operation volume**, NEVER comparing absolute lower request totals at different throughput as though work were equal. Start with the historical matched 1500 IOPS rate where feasible, and add a second common sustainable rate. Sweep QD1/QD4/QD8/QD32, 80/20, 70/30 and 50/50 READ/WRITE, disjoint vs same-region read-after-write, compressible-heavy/medium/raw controls, cold/hot, FUA/flush and sustained GC. Suggested comparable trials: 10s warmup, 30–60s measured, **at least five counterbalanced paired repetitions** for primary claims, at least three secondary repetitions, identical input/hash and total completed work. Declare when controlled wave barriers limit arrival variability. Do not hide outliers, rejected trials or unmeasured kernel CPU.

### Existing evidence and unresolved diagnoses

- Highly favorable 1024-page burst (~819 pages compress to **~56–57 bytes**, 205 RAW): real V2.2 lower WRITE **26 requests / 1,679,360B**, V3 alpha.7 bulk=1/2 **16 / 905,216B**. This is a *burst-only* win, **not** a sustained anonymous-memory prediction.
- Codex [PR #58](https://github.com/k1moradi/swapz/pull/58): at **matched 1500 IOPS** V3 alpha.7 was slightly worse than V2.2 in lower I/O; QD1 nonzero coalesce delay severely lowered throughput/raised write p99. Many sustained writes formed singleton windows. Its fixed-duration saturation rows had unequal completed work.
- Codex [PR #60](https://github.com/k1moradi/swapz/pull/60): at **QD8 and 5000 achieved IOPS**, 150,000 useful operations, five repetitions, median real lower WRITE requests **V2.2 118,782**, V3 bypass-off **119,438**, bypass-on **119,512**; bytes **466.00/467.33/467.47 MiB**. Bypass-on did **not** improve the matched case, so alpha.8's optional disjoint read bypass was not adopted by default despite some saturation batching improvements.
- The historical **+1 independent backing WRITE request** versus V3 target counter in 120 prior trials remains unexplained with equal counted write bytes; do not silently subtract a request. Kernel-worker CPU attribution, source of generic asynchronous Buffer I/O messages, true device-originated READ/WRITE faults and loaded new three-way immutable replay remain unresolved. Report as **BLOCKED/NOT RUN/UNMEASURED**, never silently PASS.
- Larger packing windows are a hypothesis only: **one-record windows** cannot obtain multi-record benefits regardless of LZ4 ratio. Inspect read fragmentation, actual window histogram, lower extent geometry, GC and read amplification before another sort/entropy heuristic.

## Publishing and safety

Store reproducible scripts/CSV/JSON, module/fixture/trace hashes, rejected cases and a checksum manifest in versioned files **on `main`**, not on new Codex/PR branches. **After each implementation or new measured-learning task, update the relevant one of the four standards in the same commit**, with exact result scope, PASS/FAIL/BLOCKED and raw evidence link. Update `README.md` for user-visible workflow changes and `VISION.md` if the objective changes.

Never reboot, `swapoff`/`swapon`, touch `/dev/sdb1`, `/swapfile`, active swap, physical/unowned media, unowned DM or global faults. The bare null_blk "off" arm uses **no system swap mutation**. If a test-owned device's holders/BIOs cannot be proven safe to remove, quarantine it and label BLOCKED. Physical performance remains a separate explicitly owner-authorized future gate, not permission to bypass V3's null_blk-only constructor.
