# swapz V3 — production readiness ledger

**Status: NOT READY — V3.0.0-alpha.7 (draft mixed lower-write candidate).** This is an evidence gate, not a
marketing release label. See [VISION.md](VISION.md),
[DEVICE_GEOMETRY.md](DEVICE_GEOMETRY.md) and
[PERFORMANCE_DIAGNOSIS.md](PERFORMANCE_DIAGNOSIS.md). Primary success
means verified, workload-matched reductions in **host-visible lower
read/write BYTES and REQUEST COUNTS**, accounting for all GC and
flush operations and the device's actual logical/physical sector and
preferred I/O sizes, with acceptable swap-in p99 and CPU. 4KiB
equivalents are a normalization, not physical operation counts.
Correctness tests are mandatory but do not establish this outcome.

## Alpha.7: independent loaded bounded-burst win; sustained gate STILL OPEN

[Developer PR #55](https://github.com/k1moradi/swapz/pull/55) adds
mixed raw/compressed lower-write streaming. [Independent Codex
validation PR #56](https://github.com/k1moradi/swapz/pull/56) tested
the exact unchanged source `0e199159cea3dd479224ce59513ee9c0a810a0d6`
on test-owned memory-backed `null_blk` and reports **35 successful,
fully byte-verified 1,024-page trials**, five each for frozen V2.2,
alpha.6 bulk=0/1/2, and alpha.7 bulk=0/1/2. Backing request/sector
deltas reconciled to DM target write counters.

| Loaded candidate | Backing write requests | Backing write bytes |
|---|---:|---:|
| Frozen V2.2 | 26 | 1,679,360 |
| V3 alpha.6 bulk=0/1/2 | 419 | 1,716,224 |
| V3 alpha.7 bulk=0 | 419 | 1,716,224 |
| **V3 alpha.7 bulk=1/2** | **16** | **905,216** |

The original frozen workload includes 819 compressed records and
205 raw pages; **each compressed record is only ~57B after LZ4**,
a highly favorable case. Exactly 205 raw physical blocks plus 16
compressed blocks account for the 221 × 4KiB observed lower write
bytes. Source status reports 16 mixed runs, and independent backing
stats report 16 actual writes. This validates a *real bounded-burst*
improvement, not merely modeled submissions.

The loaded tests also passed the exercised mixed read/overwrite/discard,
FUA/PREFLUSH, synthetic lower-flush EIO, eight reserve-role GC
rotations with refill, and 1,024-BIO drain/suspend cases. The tested
GC full-destination case refused relocation with zero GC I/O.
**These do NOT establish** real lower-device write fault behavior,
partial/torn lower completion, steady-state GC cost, sustained fio
throughput, achieved-rate matching, realistic 1–3KiB compressed-page
mixes, CPU/memory, or cold-read p95/p99. The five-trial matrix was
grouped rather than counterbalanced; treat the result as repeatable
for its deterministic burst, not as an unrestricted performance claim.

[Follow-up draft PR #57](https://github.com/k1moradi/swapz/pull/57)
adds an opt-in, target-local, **pre-submission** lower-write EIO test
boundary to exercise mixed-run/GC error propagation on owned null_blk,
and extends the exact production-C tests with realistic 1–3KiB
compressed/raw mixed records. That new source and its live tests require
separate SHA-pinned qualification. The injector does not model torn media.

**Release remains NOT READY.** Gates: loaded fault/error and prefix
publication, varied realistic-size input, matched achieved IOPS,
read/write request+byte accounting including GC, CPU, p95/p99,
and repeated counterbalanced V2.2 comparison; no active swap or
physical storage tests. See
[alpha.7 design](kernel/extent-v3/MIXED_LOWER_WRITE_AGGREGATION.md)
and [fault qualification gate](
kernel/extent-v3/LOWER_WRITE_FAULT_QUALIFICATION.md).

## What is already supported by evidence

Codex's **independent V3.0.0-alpha.1** loaded host [PR #46 report](
https://github.com/k1moradi/swapz/blob/codex/pr45-live-nullblk-validation/docs/validation/v3-alpha1-2026-10-12/validation-report.md)
records byte-exact actual LZ4/raw lower I/O on a controlled memory-backed
`null_blk`, verified 4/8/16 KiB packing and complementary-size reordering,
two GC rotations under each of two workloads, fault-based fail-stop,
healthy lower sector/request reconciliation, ordinary suspend/teardown,
and no active-swap or SD modification.

Its **limitations** are material: the kernel emitted 19 workqueue CPU-hog
diagnostics under concurrency; explicit loaded `REQ_FUA` was not observed;
64-page *ordered4* control was geometry, not a loaded V2.2 comparison;
and GC churn wrote 1.040x compressed and 1.143x raw logical bytes, both
**write amplification relative to completed logical bytes**, not
steady-state savings nor proof of a V2.2 regression. The other 64-page
loaded test demonstrated real packing, but its ordered4 control was
only a geometry model; size-class opportunity was limited by
singleton write windows during churn. The study did not
measure production p99 on SD/SSD/HDD.

## Main-developer alpha.2 changes after the host run

- **Restore module basename `dm-swapz.ko`**, separate from V2.2 source
  by branch/build tree; in early V3 alpha the actual DM table target keyword
  is still `swapz3` to distinguish test-device mappings. Do not install,
  load or use the mutually incompatible V2.2 and V3 `dm_swapz` modules
  on the same kernel concurrently.
- Bound workqueue execution to 64 incoming upper BIOs, preserving older BIO
  FIFO and draining finite reordering windows before requeue. GC yields CPU
  while traversing potentially large logical maps. **These scheduling
  changes must be independently checked for zero warnings and unchanged
  throughput on the real host**.
- **Critical independently identified GC safety invariant:** V3's mapping
  authority had fields `gc_forbidden_open`/`gc_forbidden_victim`, but
  neither the caller set them nor the dead-segment allocator checked them.
  A GC relocation could reuse an apparently dead foreground OPEN segment
  while its saved cursor was about to be restored. Alpha.2 binds and
  checks both forbidden physical segments and clears them on GC exit.
  Exact-production-C regression covers exclusion, exhausted reserve
  and normal non-GC reclaim. This finding was **not** discovered by Codex
  in the limited two-victim happy-path host study.
- Store CRC32C for raw 4KiB pages in volatile mapping metadata and verify
  every raw logical read and raw GC source. Raw pages remain **one** physical
  4KiB write; their CRC metadata is RAM-only, not a persistent format change.
- Add optional `verify=0|1` fourth `swapz3` target argument. When enabled,
  complete compressed extents and raw 4KiB writes are read back before
  mapping publication. This has extra physical-read cost; it is **OFF** in
  the normal benchmark mode and does not prove persistence after power loss.
- Separate attempted lower I/O bytes/requests from successful-completion
  counters, and expose singleton-write-window counts and worker requeues
  for independent sector reconciliation and compression-cliff analysis.
- Report experimental live-GC mode truthfully in module/status metadata;
  add Codex's 400-window exact-C oracle to the primary test CI and build
  production module separately with W=1 and W=2.

**All host alpha.1 module hashes and performance results are HISTORICAL.**
They do not validate the renamed/rebuilt alpha.2 `dm-swapz.ko`.

## Failure classification — do not confuse readiness and algorithm proof

- **Demonstrated algorithmic benefit:** loaded V3 combined 64 logical
  pages into 31 normalized 4KiB lower units in 24 requests; the
  41-unit ordered4 comparison was **modeled**, not loaded V2.2.
- **Architectural performance weakness:** bounded greedy pairing
  cannot combine records absent from the same submitted worker
  window. Single-record windows during churn sharply reduce the
  gain. Improve and measure staging opportunity and GC live-*byte*
  cost, not only the sorting function.
- **Real implementation bugs:** the alpha.1 workqueue CPU-hog report,
  missing forbidden-GC-segment enforcement, and earlier status/raw
  integrity defects. Alpha.2/3 fixes are not yet independently
  qualified on the loaded physical host.
- **Missing evidence:** loaded V2.2 apples-to-apples measurements,
  loaded alpha.2 FUA and hostile GC, repeated concurrency with no
  kernel scheduling warnings, and a safe **physical-media**
  benchmark. This is an **unproven release benefit**, not a
  demonstrated failure of zsmalloc-style size classes.

See [PERFORMANCE_DIAGNOSIS.md](PERFORMANCE_DIAGNOSIS.md) for
sourced numbers and the concrete engineering response.

## Main-developer alpha.3: the online-I/O performance candidate

[PR #49](https://github.com/k1moradi/swapz/pull/49) implements the
**actual Device Mapper** changes described by the prior diagnosis:

- **Admission pipeline:** bounded `coalesce_ms=0..4` batches arrival
  across an opt-in timer, without perpetually resetting the deadline.
  Urgent reads, discard, preflush and FUA bypass it. Default `0` preserves
  the alpha.2 latency/control policy. Worker owns all delayed BIOs and
  drains the timer during suspend/removal.
- **Measured opportunity:** exact window-size buckets `win1`, `win2`,
  `win3_4`, `win5_8`, `win9_16`, `win17_64`,
  `window_records` and coalescing counters, so increased density
  cannot be claimed without proving compatible pages were actually
  staged together. The new delay may hurt QD1 swap-out p99.
- **GC economics:** authoritative volatile `payload_length` is recorded
  only after full CRC-checked extent publication, and verified against
  subsequent reads. Raw records cost 4096B; compressed records cost
  verified LZ4 bytes plus 16B descriptor each. `gc=1` selects
  lowest estimated LIVE bytes; `gc=0` preserves old live-record-count
  comparison. Report both estimated victim bytes and **ACTUAL GC read
  and write bytes AND request counts**, not invented flash wear savings.
- **Exact-C qualification:** a deterministic regression shows old
  count-based GC would prefer one 3500B page, whereas the new byte
  estimator prefers three 500B pages. Separate authority tests verify
  actual 2200B/1600B records publish those precise payload lengths,
  fail-closed limits, and raw record cost.
- **Version/provenance:** `V3.0.0-alpha.6`, installed V3 build artifact
  `dm-swapz.ko` and alpha DM target keyword `swapz3`. Rebuilt host
  module SHA, source blobs, vermagic and backing major/minor must be
  captured anew. The alpha.1 and alpha.2 evidence cannot certify it.

The precise independent actual-kernel workload and safety instructions
are in [ONLINE_IO_RETEST.md](kernel/extent-v3/ONLINE_IO_RETEST.md).
**The release gates below remain unchecked until new host evidence
exists.** No SD/HDD/SSD I/O or active swap manipulation is authorized
by this source update; the `null_blk` constructor guard remains.

## CRITICAL alpha.3 GC progress failure and alpha.4 correction

Codex's exact [loaded report](https://github.com/k1moradi/swapz/pull/49#issuecomment-6129397157)
found a **REAL GC reclaim-progress failure** on a 32MiB/1024-page
owned RAM null_blk. The previous selector considered reserve
segments30/31 as GC victims even though normal foreground staging
could only reuse segments0..29; GC restored the old fixed
foreground cursor. After two successful relocations, reserve30→31
had NOT produced any foreground-usable space; the next write
returned `-ENOSPC` without a false success. Neither this fault nor
Codex's report demonstrates data corruption.

Main developer [PR #50](https://github.com/k1moradi/swapz/pull/50)
changes the **allocator ownership model**, not just the victim score:
a preallocated segment-role map identifies foreground vs reserve;
GC can select only foreground victims and allocate into ONE
wholly-dead reserve-role destination; a verified complete live-record
evacuation exchanges the victim/destination roles, keeping the
foreground cursor in the compacted destination. On any I/O/error
path no roles change and the target fails closed. A fully emptied
former foreground victim therefore becomes next cycle's reserve.
Memory-only exact-production-C authority and codec/engine tests
exercise repeated handoffs, old-map preservation on incomplete
relocation, and eight rotations on the exact 32MiB geometry.
**Current experimental development version: 3.0.0-alpha.7.**

This is **source implementation evidence**, NOT a loaded-kernel
approval. [ONLINE_IO_RETEST.md](kernel/extent-v3/ONLINE_IO_RETEST.md)
makes the exact original workload and ≥8 GC rotations the **first
host gate**. No physical SD/HDD/SSD test or relaxing the null_blk
safety restriction until this and later independent gates pass.

## Alpha.5: correct upper-flush contract, bounded fault injection and I/O-aware GC

The independent [alpha.4 loaded report](https://github.com/k1moradi/swapz/pull/51)
validated the original 32MiB/1024-page GC progress correction with eight
rotating reserves, full readback and bounded failures. It also found two
new release-significant points:

- **Incorrect flush test:** a test helper submitted a standalone
  `REQ_OP_FLUSH` **BIO**. This opcode is *only synthesized inside Linux
  at the request layer*; `block/blk-core.c` rejects direct BIOs with
  `-EOPNOTSUPP` BEFORE the Device Mapper target sees them. The
  supported **zero-length upper standalone flush** is a
  `REQ_OP_WRITE | REQ_PREFLUSH` BIO. That valid encoding and upper
  FUA succeeded during alpha.4 bounded loaded testing. Therefore the
  invalid BIO rejection is **NOT a proven kernel target flush bug**.
  Nevertheless, genuine lower-cache-flush failure propagation and
  once-only upper completion remain loaded release gates.
- **Invalid GC cost assumption:** the default byte-only policy chose
  three 496B compressed survivors (three actual 4KiB lower reads,
  one 4KiB relocation write) over one 3335B survivor (one read,
  one write). Choosing fewer compressed bytes **doubled the total
  measured GC transfers** in that matched case; it does not make
  size-aware GC inherently a failure, but requires read-inclusive
  measurement.

[Main-developer PR #52](https://github.com/k1moradi/swapz/pull/52)
adds an actual production adapter around every lower
`blkdev_issue_flush()` call, with `flush_calls/ok/err/injected`
counters. A **default-OFF diagnostic 0..64th-flush EIO** can be
configured only on the existing strictly null_blk-only alpha target.
It returns a **synthetic failure before lower submission**, exercises
the target's fail-closed and BIO completion logic, and must not be
reported as a real device-originated error. Independently injected
genuine lower failures remain a separate gate.

GC policy **`2` is now the default**, conservatively scoring
per-record lower selective-read overhead in addition to copied
payload+descriptor bytes. `gc=0` live-record count and `gc=1`
live bytes are preserved as matched controls; `gc=2` is an
**estimate**, not a measured winner. Physical lower GC bytes/requests
must be recorded for all three. Candidates whose live byte lower
bound already consumes an entire 1MiB destination are excluded
**before any relocation I/O**—there is no possibility of reclaiming
a foreground-writable block from them.

Alpha.5 has **not been loaded** on Codex's host at time of
implementation. Its new module hash is different from the validated
alpha.4 `dm-swapz.ko`. Retest valid upper flush success, injected
synthetic failure, real lower failure (if safely possible), then GC
policy 0/1/2 and only afterward sustained I/O performance. The
`null_blk`-only constructor guard remains unchanged. **NO REBOOT,
NO active swap or physical-media I/O**.

## Alpha.6 main-developer response to the first measured V2.2 performance regression

[Independent Codex PR #53](https://github.com/k1moradi/swapz/pull/53)
verified alpha.5 FUA/PREFLUSH, eight full GC reserve rotations for each
victim policy, exact readback and 1,024-BIO suspend/resume on owned
RAM-backed null_blk. Its measured, same-input 1,024-write V2.2 control
is **NEGATIVE** for the previous V3 defaults:

| 1024 upper 4KiB writes, full readback | V2.2 | V3 alpha.5 |
|---|---:|---:|
| Lower WRITE bytes | 1,679,360 | 1,716,224 (2.20% WORSE) |
| Lower WRITE requests | 26 | 419 engine submissions / 420 backing |
| Lower READ bytes | 4,194,304 | 4,194,304 |

The roughly **16× request regression** is explained by actual source:
alpha.5 sent one synchronous `dm_io` per small 4/8/16KiB extent,
while V2.2 issued large stream writes. In isolated, favorable
16-page runs V3 coalescing could reduce written bytes, but sometimes
doubled read traffic and increased write completion to multiple
milliseconds. Those microbursts are NOT a sustained or physical-media
performance win. The user's project vision is emphatically NOT yet
satisfied.

[Main-developer draft PR #54](https://github.com/k1moradi/swapz/pull/54)
implements **real physical lower request aggregation**, not another
isolated packer simulation. The exact kernel engine stages up to 64
independently valid SWZ3 extents, keeps every logical mapping
UNPUBLISHED, and submits a synchronous, bounded **256KiB** lower
write. Only after complete lower success is each saved, CRC32C
snapshot-restored stage validated and published via unchanged
`sv3_finish`. A failed/short lower run aborts every unpublished
extent without acknowledging its upper BIO; previously confirmed
complete runs retain their exact committed-prefix semantics.
No group crosses a 1MiB segment boundary. Any attempted
unrelated stage or discard during paused transactions is rejected.

**Still-blocking mixed-format request economics:** the loaded
1,024-write alpha.5 fixture contained **819 compressed and 205
incompressible/raw pages**. Alpha.6's bounded bulk submission applies
only to compressed extents: each raw fallback still produces one
synchronous `dm_io` lower write. So on the same fixture, alpha.6
still entails **at least 205 raw lower submissions** independently
of any gains aggregating compressed extents. This source-level floor
does NOT equal independently measured block-layer requests, but it
means **compressed-only batching cannot plausibly erase the entire
V2.2 26-request deficit**. Mixed raw/compressed lower streaming
is a separate, high-priority architectural development requirement,
not a feature to assume has been implemented or qualified in PR #54.

Three **same-binary** controls:
`lower_bulk=0` historical per-extent synchronous calls,
`lower_bulk=1` **default adjacent-only**, with NO new padding
write bytes, and `lower_bulk=2` permits explicitly counted
zero-padding across alignment holes to trade additional bytes for
possibly fewer requests. Verification readback mode remains
serialized. Status `bulk_mode,bulk_io,bulk_extents,bulk_padding`
are source-level lower submission diagnostics; the independent
backing `null_blk` stats, NOT `dm_io` call counts, prove actual
request counts after any block-layer splitting.

In addition, Codex reported one GC victim of **256 compressed
~3535B live records** that cost **1MiB read + 1MiB write**
and then failed `-ENOSPC` with no role rotation. Alpha.6 now
uses the exact SWZ3 4/8/16KiB codec geometry to prove that
**every compressed record >=3258B consumes at least one physical
4KiB block**, even under ideal packing (five such records
cannot fit 16KiB with metadata). Raw pages similarly consume
one block. A candidate containing >=256 such live records
is rejected as **provably unable to free one block** before
any GC copy; `gc_no_headroom_skips` counts candidate checks,
not saved IO operations. The earlier total-payload minimum
also remains. This reduces unnecessary GC I/O in the reported
fragmentation class but does not solve all no-progress layouts.

Exact-C ASan/UBSan and W=1/W=2 build are necessary but NOT
sufficient. A new alpha.6 module (different hash from alpha.5)
must pass the original 1024-write independent readback, combined
lower error/short completion and prefix preservation, live GC,
upper FUA/PREFLUSH/suspend, and real V2.2 sustained, matched-achieved
IOPS tests. **Do not count this as a win before lower READ and WRITE
bytes AND request counts, CPU and p99 improve without damaging
correctness.** See the [dedicated alpha.6 gate](kernel/extent-v3/LOWER_WRITE_AGGREGATION.md).
The constructor remains null_blk-only; no active /dev/sdb1, physical
disk, /swapfile or reboot is authorized.

## Required production exit gates (hard)

- [ ] **G1, loaded alpha.5 correctness.** Independent static review followed
      by exact-source/module hash, target UUID and owned memory-backed
      `null_blk` checks. Repeat all exact 4KiB compressed, raw,
      overwrite, discard, sparse, reorder, CRC and GC cases. Demonstrate
      *both* GC forbidden-segment exclusions with staged LIVE mappings and
      several full-space wraps, not merely two clean turnovers. A
      kernel warning/Oops/lockdep report is an open defect until explained.
- [ ] **G2, explicit FUA / flush durability semantics.** Submit an actual
      `REQ_FUA` upper BIO in a controlled kernel test (not merely
      `fdatasync`). Trace matching lower completion and cache flush
      ordering. Inject both lower write and lower flush failure; upper
      completion must remain one-and-only-one with correct error status.
- [ ] **G3, concurrency and tail latency.** Rerun Codex's concurrent
      reader/writer test with exact matched load. Prove worker bounded
      requeue preserves global BIO ordering and does not recur with
      `sv3_worker hogged CPU`. Quantify p50/p95/p99, GC stalls, achieved
      read/write IOPS, CPU, and one-page-window incidence.
- [ ] **G4, repeated GC/fault/liveness.** Multiple hot/cold workloads
      beyond steady-state capacity, full image readbacks, corrupt
      lower raw/compressed payloads, errors in GC read/write, reserve
      exhaustion and failed relocation. Never reuse partly live segments.
      Under faults, no upper success for unpublished data; preserve old
      mapping data and leave teardown ownership safe.
- [ ] **G5, repeatable V2.2-vs-V3 measured IO WIN and request aggregation.**
      The alpha.5 default's actual write requests were ~16× V2.2,
      so alpha.6 requires an independently measured improvement, not
      merely compilation or lower dm_io *submission* counters.
      Compare lower_bulk 0/1/2 under equal workload, all GC and
      latency costs, then the ACTUAL mutually exclusive loaded V2.2
      control. Preserve negative/mixed results. Same
      actual LZ4 page bytes, compressed-size histogram, arrivals,
      read/write mix and achieved load on independently owned equal
      `null_blk` configuration, with **mutually exclusive builds** of
      V2.2 and V3 `dm-swapz.ko`. Record write-window occupancy,
      singleton-window fraction, 4/8/16KiB allocations, empty bytes
      and GC relocation bytes; compare options for bounded cross-worker
      size-bin staging under the same flush/FUA and upper BIO ownership.
      Report lower read/write **512-byte stat sectors** and request
      counts, including GC; a 4KiB equivalent is stat sectors / 8,
      **NOT** the number of physical I/O commands. Do not use ordered4
      modeled geometry as an observed control.
- [ ] **G6, authorized physical-media qualification.** After G1–G5
      pass and a separate review removes the current **null_blk-only**
      constructor guard, test only a clearly isolated, verified target
      SD/SSD/HDD backing. For the user-authorized `/dev/sdb1`, recheck
      active swap, mounts, holders, available memory and consent scope.
      **Do not touch any active swap** or force a cleanup. **NEVER REBOOT.**
      Before loading, profile backing logical and physical sectors
      (`512n/512e/4Kn` where applicable), alignment, minimum/optimal
      I/O, partition start and cache/flush behavior; never presume
      4096-byte units are the device's native sectors. Compare device
      **read/write bytes and requests** (plus GC), CPU, p99 and
      device health/telemetry where available. Use 512-byte sysfs-stat
      sectors in conversion, irrespective of 4Kn. Do not infer NAND
      program operations or endurance from host sector totals alone.
- [ ] **G7, packaging/deployment/recovery.** Independent DKMS packaging
      for the retained `dm-swapz.ko` module name, explicit incompatible
      volatile V3 format, system integration, bounded reclaim pressure,
      safe uninstall and recovery from failures. V2.2 is the comparison
      and rollback baseline, not a simultaneously loaded target.

**Release is blocked if any integrity, write/flush ownership, GC liveness,
module identity or physical performance gate fails.** A `null_blk`
functional PASS does not imply G6. Do not call a build `production-ready`
until the independent evidence exists and each gate is checked.

### Engineering workflow

The main developer owns data-path architecture, code, counter semantics and
kernel fixes; Codex is the independent loaded-host and measurement tester.
Review findings and source changes are stacked in draft PRs. The currently
strict `null_blk` device restriction is deliberate and is **not** to be
waived merely to produce an SSD/HDD/SD benchmark.
