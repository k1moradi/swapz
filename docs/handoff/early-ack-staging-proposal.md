# Bounded early acknowledgement from staging — unapproved architecture proposal (ID164)

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

**Status: unapproved architectural investigation. Nothing is implemented,
and no kernel, test, default or report change is authorized.** The
production invariant is unchanged: an upper WRITE succeeds only after its
lower WRITE completed successfully and its mapping was published (lower-I/O-confirmed
acknowledgement). This document is a design question for owner review, not
performance evidence. It is tracked separately from the immediate work queue,
which stays focused on the screened SSD experiments (ID160 striping, ID162
hand threshold).

## 1. Why the question exists

Linux v7.0 references below are from
[torvalds/linux v7.0](https://github.com/torvalds/linux/tree/v7.0).
swapz references are to the current production C.

ARM64 owner report `e73614c` (source `6c33294`, quiet host) decomposes the
fast-model sustained WRITE waves:

| Fast model, K=1 | lower WRITE | reissue gap | non-I/O | raw | swapz |
| --- | --- | --- | --- | --- | --- |
| QD1 | about 182 us / 1 page (service EWMA) | not split | not split | 22.1 MB/s (latency-bound) | 20.9–21.1 MB/s |
| QD4 (sync4 path) | 179 us / 4 pages | 40–41 us | 3 us | 84.0 MB/s (bandwidth cap) | 73.2–73.4 MB/s |

With acknowledgement tied to lower completion, a writer at QD1 waits for one
lower service time per page, whether or not the page compresses. Compression
saves bytes, not latency, so QD1 on a latency-bound device can at best tie
raw. QD4's zero-gap K=1 ceiling is about 4 x 4096 B / 182 us ≈ 90 MB/s
(+7% over raw); parity needs a reissue gap of 13 us or less. Early
acknowledgement is the only mechanism identified so far that changes this,
because it removes lower service from the writer's critical path.

**Upper-bound estimate (model, not evidence):** with early acknowledgement,
sustained QD1/QD4 service would be bounded by the K=1 lane running full
windows, by writer CPU per operation and by reservoir backpressure. The same
report's sustained QD32 rates, 129–132 MB/s fast and 13.2–13.9 MB/s serial
(raw QD1: 22.1 and 3.7–3.9 MB/s), are the ceiling a pilot must try to
falsify. They are not a prediction.

## 2. What the contract change actually is

- **Swap issues no durability barrier.** v7.0 swap WRITEs are submitted as
  `REQ_OP_WRITE | REQ_SWAP` only
  ([page_io.c L416, L435](https://github.com/torvalds/linux/blob/v7.0/mm/page_io.c#L410-L440)).
  swapz already advertises a volatile write cache: `swapz_ctr` sets
  `ti->num_flush_bios = 1` and `ti->flush_supported = true`, so DM sets
  `BLK_FEAT_WRITE_CACHE | BLK_FEAT_FUA`
  ([dm-table.c L1873, L2059](https://github.com/torvalds/linux/blob/v7.0/drivers/md/dm-table.c#L1865-L1880)).
  That the block-layer feature *permits* completion before persistence is not
  a justification: swap never sends the PREFLUSH that would give the feature
  meaning. Swap relies on **per-WRITE completion status**.
- **Kernel recovery is lost.** On a failed swap WRITE,
  `__end_swap_bio_write()` re-dirties the folio and clears `PG_reclaim`, so
  the kernel keeps its RAM copy
  ([page_io.c L30-L50](https://github.com/torvalds/linux/blob/v7.0/mm/page_io.c#L30-L50)).
  After early success the folio may be reclaimed, and that recovery path no
  longer exists. swapz would become the only holder of the page.
- **A later READ error does not recover the page and has no single outcome.**
  An anonymous fault on a non-uptodate swap-in folio returns
  `VM_FAULT_SIGBUS` to the faulting task
  ([memory.c L4886-L4888](https://github.com/torvalds/linux/blob/v7.0/mm/memory.c#L4880-L4890)).
  `swapoff` instead installs a poisoned swap PTE, deferring the failure to a
  later access
  ([swapfile.c L2119-L2126](https://github.com/torvalds/linux/blob/v7.0/mm/swapfile.c#L2115-L2135)).
  A shmem swap-in returns `-EIO`
  ([shmem.c L2407-L2409](https://github.com/torvalds/linux/blob/v7.0/mm/shmem.c#L2400-L2412)).
  Kernel accessors and readahead differ again. A design must therefore never
  turn a lower failure into a READ error for an acknowledged page.
- **Crash and power loss.** swapz's mapping authority, generations and
  segment state are volatile RAM ([context.md](../context.md)), so swapz
  content is already unreadable after any crash or reboot, and ordinary swap
  does not read swap content across boot. Early acknowledgement would not
  lower ordinary-swap crash durability below today's zero, but it is not
  harmless: hibernation writes its image with `REQ_OP_WRITE | REQ_SYNC`,
  waits for completions and powers off
  ([kernel/power/swap.c](https://github.com/torvalds/linux/blob/v7.0/kernel/power/swap.c)),
  so an early-acknowledged image page would be lost. swapz's volatile
  authority already makes it unusable as a resume device. That is currently
  undocumented, and it must become an explicit documented, and if possible
  enforced, refusal before any early-acknowledgement opt-in.

## 3. Questions the proposal must answer before any code

### 3.1 Durability and fault semantics

Candidate rule, **retain until lower success**: an early-acknowledged
generation's staged slot is released only after a lower WRITE containing that
generation succeeds and is published, or after an overwrite or DISCARD
supersedes the generation. On lower EIO the slot is kept and the record is
re-planned to another physical location (bounded retries). READs of that
generation are served from the staged immutable copy. Under persistent
failure swapz stops early acknowledgement and returns EIO for new WRITEs, so
the kernel re-dirties them exactly as with raw swap. At most 64 pages
(256 KiB) stay readable from RAM.

The proposal must state what is still lost: the kernel never learns that an
acknowledged page lacks backing; swapz, not reclaim, owns that page
indefinitely; and removing the table or reloading it while retained pages are
unwritable would drop them unless removal is refused. It must also prove that
no READ can return stale lower data for a newer staged generation (no silent
corruption), and that terminal `ctx->failed` behavior is defined for staged
pages.

### 3.2 Bounded staging ownership, lifetime, backpressure, forward progress

- Reuse the existing 64-slot preparation reservoir. It already holds an
  immutable RAW snapshot of every ordinary WRITE: in `e73614c`,
  `submitter_copy_bytes` equals logical WRITE bytes. So early
  acknowledgement needs no new data buffer. What changes is that a slot
  outlives its upper BIO and must carry logical page, generation, payload and
  state on its own, without `dm_per_bio_data`.
- Producer lifetime: submitter-context and background preparation must not
  touch a slot after its BIO is completed. Define the single owner of the
  detached slot and its release.
- Backpressure: when every slot is staged but not yet lower-confirmed, a new
  WRITE falls back to today's lower-confirmed completion rather than blocking
  in a new wait state. That fallback is the simplest forward-progress
  argument. Prove there is no allocation on the stage → submit → publish
  path under reclaim (the existing queues are `WQ_MEM_RECLAIM`).
- Forward progress: every staged slot needs a guaranteed path to a lower
  WRITE without further upper arrivals. Use the existing retention bound
  (`SWAPZ_MAX_RETAIN_MS` = 4 ms production) as the maximum staged age, and
  prove no window can wait forever for records that never arrive.

### 3.3 PREFLUSH/FUA, DISCARD, overwrite, generation authority, GC, suspend/drain

- PREFLUSH completes only after every earlier early-acknowledged generation
  has reached lower success. This is the write-cache contract swapz already
  advertises. A FUA WRITE is never early-acknowledged.
- Overwrite: a newer generation stages and supersedes the older one. A late
  completion of the older lower WRITE must not publish over the newer
  mapping (generation check at publication).
- DISCARD invalidates a staged generation. Its later lower completion must not
  resurrect the page.
- READ of a staged page. Serving from the slot is the cached-READ problem the
  ROADMAP already flags: it needs pinned immutable cache/authority views plus
  pending same-page WRITE, GC, DISCARD and fence safety, and a generation check
  alone is insufficient. Waiting for publication is acceptable only while the
  lower device is healthy.
- GC: staged generations have no lower location. Victim selection and
  relocation must ignore them, and GC lower WRITEs share the K=1 lane with
  staged WRITEs.
- Suspend/drain: DM suspend waits only for in-flight upper BIOs, which no
  longer include early-acknowledged pages. `swapz_drain` must therefore drain
  staged slots to lower success itself, including noflush suspend, and a
  failure during drain has no upper BIO to report to. Table reload or
  destruction must refuse, or provably not discard, retained unwritten
  generations.

### 3.4 Can a durable staging design keep the benefit?

The QD1 deficit is the lower WRITE latency on the writer's critical path.

- Staging that is durable on the same lower device needs a lower WRITE before
  acknowledgement, which is the same latency. It also adds write
  amplification, against the endurance goal; compare retired ID161, whose
  QD1 RAW path was −12.7% on the old PC.
- Durable staging on a separate, faster persistent medium could keep part of
  the benefit, but it adds a device dependency outside owned null_blk
  qualification. It is not proposed.
- Volatile retain-until-success adds no crash durability, but swapz has none
  across reboot today. The real decision is whether losing kernel-visible
  per-WRITE failure status is acceptable.

No durable design on the same device has been identified that preserves the
QD1/QD4 benefit.

### 3.5 Evidence required before any opt-in consideration

- Shape: an opt-in, null_blk-only development switch, refused for physical
  backing, like the hand-threshold selector. Default off.
- Development comparison (`make fast_test`), three arms (raw,
  swapz-confirmed and swapz-early) on fast and serial sustained QD1/QD4/QD8,
  fast mixed QD32 and the SATA/NVMe envelopes. Report useful WRITE/READ
  throughput, acknowledgement p50/p99, READ-after-WRITE latency, lower
  bytes/requests, reservoir occupancy, fallback count and maximum staged age.
- Owned-null_blk failure injection, all byte-exact:
  - a single lower EIO after early acknowledgement: the retained page stays
    readable and the retry relocates;
  - persistent EIO: new WRITEs fail with EIO, the 64 retained pages stay
    readable and no stale data is ever returned;
  - overwrite, DISCARD and READ races on staged pages;
  - PREFLUSH drain ordering, and FUA never early-acknowledged;
  - suspend/resume and table removal with staged pages;
  - ID36 memory/CPU pressure with a full reservoir;
  - GC under staged load.
- Kill criteria: abandon if early arms do not beat raw at QD1/QD4 by the
  usual 5% practical criterion with intervals, or if any fault gate shows
  stale data, lost acknowledged data while the target lives, or unbounded
  retention.
- Qualification only through `make test`, and only after owner approval of
  the contract in 3.1.

## 4. Decision requested from the owner

Is losing kernel-visible per-WRITE lower failure status acceptable in
principle, in exchange for bounded retain-until-success staging? Until that
is decided, lower-I/O-confirmed acknowledgement remains the production
invariant and nothing here is implemented.
