# swapz V3 — active project goals (supersedes the old V2.x sequencing)

## Mission and decisive success test

> **The ultimate success criterion is lower measured host-visible storage
> I/O cost — READ and WRITE BYTES plus REQUEST COUNTS separately, including
> GC — under an identical verified workload on the actual SD card, SSD or
> HDD, while keeping correctness, CPU and swap-in latency acceptable.
> The existing 4KiB layout is an implementation choice, NOT a universal
> device physical-sector or operation size.**

Read the normative [VISION.md](VISION.md), device-size/sector/partition/
swap-file distinctions in [DEVICE_GEOMETRY.md](DEVICE_GEOMETRY.md) and the
measured algorithm-vs-implementation diagnosis in
[PERFORMANCE_DIAGNOSIS.md](PERFORMANCE_DIAGNOSIS.md). Together they govern
feature priority, design, performance evidence and release decisions.

- **Correctness first:** full 4 KiB logical data readback, safe upper/lower
  completion and flush ordering, mapping generations, GC, reserve ownership
  and teardown are mandatory prerequisites, not performance indicators.
- **Primary lower-I/O evidence:** report owned-device read and write
  **bytes** (Linux `stat` **512-byte** sector counts multiplied by 512)
  and independent read/write **request counts**, including GC, flushes
  and error attempts. Optional 4KiB-equivalent units are normalization
  only. One 16KiB command transfers 16KiB (four normalized units)
  in ONE request, not four physical operations.
- **Observable performance:** compare achieved useful swap-in/out IOPS,
  cold-read p95/p99, worker stalls, CPU and RAM costs under matched actual
  workloads. Extra read blocks, GC rewrites or latency may erase write savings.
- **Evidence hierarchy:** geometry is a hypothesis, rootless exact-C/CI
  establishes safety boundaries, owned `null_blk` establishes loaded-kernel
  behavior, and verified SD/SSD/HDD tests establish whether V3 actually
  benefits the target device class. Do not silently promote one level into
  another.
- **Release decision:** no overall 'winner' unless exact data integrity
  holds, the measured total lower-I/O frontier improves materially on
  matched workloads, and swap-in latency/CPU/GC do not regress
  unacceptably. Preserve V2.2 as control and publish counterexamples.

**Measurement caveat:** V3's aligned 4KiB lower *allocation* unit and
supported 4KiB `PAGE_SIZE` are not universal physical-sector sizes.
512n/512e/4Kn, physical alignment, reported minimum/optimal transfer
sizes, filesystem cluster sizes and device-internal programming can differ.
Profile and qualify per device class; do not infer NAND endurance from
host-visible sectors.

## Product direction

**Minimize actually observed lower-device read/write cost on slow
SD/eMMC, SATA SSD, HDD and USB storage while preserving byte-exact
swap semantics.** V3.0-alpha currently allocates aligned 4KiB lower
*format units* and submits contiguous 4/8/16KiB extents. Measure
host-visible **BYTES and REQUEST COUNTS** separately; normalize to
4KiB-equivalent bytes for comparison but never label that normalization
the number of physical operations or internal disk sectors.

V3 is inspired by zsmalloc's **object-size classification and compaction**,
not by copying its in-memory page allocator. It is a volatile Device Mapper
swap target, with individual 4 KiB logical pages compressed using LZ4.

The necessary pipeline is:

1. Compress 4 KiB logical pages immediately.
2. Reorder **only already accepted, safe-to-reorder, different-slot** records
   inside a bounded 64-record window to pair complementary sizes.
3. Prefer tightly packed **aligned 4KiB V3 container units** when
   records fit; do NOT presume this is optimal for every 512n, 512e,
   4Kn or larger-preferred-I/O lower device.
4. Use versioned, aligned **8 or 16 KiB extents** for cases such as
   2,072-byte LZ4 objects where two cannot fit inside a single 4 KiB block.
   An aligned V3 allocation unit can contain fragments of different
   compressed records; this is NOT a statement about device physical sectors.
5. Read only the 4 KiB metadata block and additional blocks actually
   containing the requested record. Expose a per-record 4 KiB read budget.
6. Reclaim stale records with generation-safe segment-local GC, relocating
   only live objects into dense extents, without invalidating old authority
   until replacement lower writes finish. Recycle a victim only after all
   live records have moved and read pins / IO ownership are safe.
7. Preserve raw incompressible 4 KiB pages and zero/discard handling.
8. Drain before flush/FUA, reject torn writes, preserve mapping authority
   and byte-exact reads, and account lower **completed bytes and requests**.
9. Benchmark meaningful workloads on verified disposable devices: uniform
   2,072B, 1,048B, clustered 2,200/1,600B, alternating, mixed and hot/cold;
   report **read/write bytes+requests** and GC separately, device sector
   geometry, actual achieved IOPS, CPU, drain and p95/p99.
10. Diagnose and improve **actual write-window occupancy** (including the
    observed singleton-window/low-queue-depth bottleneck). Evaluate
    bounded, safe size-class staging across producer turns and concurrent
    lower-I/O overlap before adding complexity to the bin-packing sorter.
    Keep all mapping-generation and flush/FUA/discard barriers explicit.
11. Compare full GC cost by **live bytes and relocation read/write cost**,
    not only live record counts; qualify steady-state hot/cold workloads.
    Do not infer SSD/SD wear reduction from host sectors alone.

The optimization is a **write/read/CPU/GC Pareto frontier**, not compression
ratio or write bytes alone. A 512n drive can address 512-byte sectors,
512e may incur hidden 4KiB RMW penalties, and 4Kn normally requires
4KiB-aligned I/O. Device-reported preferred I/O size and real latency
are measurements, not substitutes for actual completed lower requests.
The current V3 codec reads aligned 4KiB units even where the device
could potentially address smaller sectors.

## Version decision

- **V2.2** is retained unchanged as the stable *control implementation* and
  any proven production-like functionality. Package `dkms.conf` for the old
  `dm-swapz.ko` intentionally stays `0.2.2`; old installations must never
  silently upgrade to an incompatible layout.
- **V3.0.0-alpha.5** is the **new active development line**. Its distinct
  `SWZ3` format and the experimental DM target name `swapz3` do not
  decode V2.2's `SPWZ` layout. No in-place migration is supported.
  V3 does **not** imply persistent/resumable data.
- Prior ROADMAP.md reserved V3.0 for persistent hibernation. That was a
  planning name, not a released contract. **Persistent hibernation/resume
  moves to a separate future V4.0 architecture** and remains forbidden
  until crash-consistent durable metadata, boot/resume and power-loss tests
  are independently qualified.

The current release-blocking qualification checklist is [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md), not a claimed alpha.2 production approval.

## Hard exit gates (do not imply success merely from CI)

**M1 — codec + transaction core.** Versioned 4/8/16KiB bytes, CRC32C,
staged-generation immutability, quarantine and fail-closed publication.
PRs #40, #42, #43 and independent PR #41 underpin these tests.

**M2 — actual standalone V3 Device Mapper target.** Separate
`dm-swapz.ko` with actual LZ4+raw fallback, sorted bounded write windows,
lower synchronous DM I/O, exact per-upper-BIO ownership and completion,
targeted reads, whole-range discard, flush/FUA and safe removal.
Validate on rootless source tests and *real loaded* `null_blk` only after
source/static+kernel compile gates. Target must not borrow the V2.2 tables.

**M3 — reclaim and density maintenance.** Low-live segment selection, bounded
relocation through size-class regrouping, GC lower **read and write** counters,
no allocation recursion, victim reuse only after full migration and safe
read ownership. Pressure test repeated victim reuse and reserve exhaustion.
**No sustained swap pressure or SD-card benchmark before M3 passes.**

**M4 — physical-medium qualification.** Guarded SD-specific harness for the
user-authorized dedicated `/dev/sdb1`, with exact identity/active swap,
holders, mount and memory checks; SSD/HDD as separately available. No
reboot. Compare against V2.2 on identical LZ4 inputs and achieved reader
load, including concurrency, GC, p99 and physical sectors. No unsupported
claims of flash program granularity, endurance or partial-block reads.

**M5 — hardening and release.** Repeated teardown, error/timeout/fault cases,
module provenance and CI, DKMS opt-in V3 packaging, system integration and
explicit incompatible-format labeling.

## Agent roles and test authorization

ChatGPT writes and reviews production allocator, DM, GC and disk-format code.
Codex independently reproduces defects, tests real host/kernel and benches,
and may repair minor build/harness defects on isolated review branches.
No test agent may reinterpret rootless geometry as loaded-kernel speed.

The physical host / dedicated `/dev/sdb1` testing authorization already
exists after verifying device identity and safety. **ABSOLUTELY NO REBOOT.**
Do not point a null_blk-only runner at the SD card or change existing swap.
Only touch owned devices, and no performance test counts unless the exact
source, `.ko`, active mapper and lower-device identity are reconciled.

## Version success criteria

V3 becomes a user-facing release only when it handles real compressed and
raw swap pages with long-lived GC, passes exact readback under real device
fault/pressure conditions and **materially improves measured lower-device
read/write bytes AND request-count/latency tradeoffs including GC**, under
matched achieved load, sector geometry and flush/drain rules, without
unacceptable swap-in p99, CPU or memory regressions. The detailed go/no-go and inconclusive
criteria are mandatory in [VISION.md](VISION.md).
