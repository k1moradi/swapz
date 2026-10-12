# swapz V3 — production readiness ledger

**Status: NOT READY — V3.0.0-alpha.2.** This is an evidence gate, not a
marketing release label. See [VISION.md](VISION.md): primary success means
verified **real lower-device** 4 KiB-equivalent read and write savings,
including every GC read/rewrite and request, with acceptable swap-in p99.
Correctness tests are mandatory but do not establish this outcome.

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
**write amplification**, not steady-state savings. The study did not
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

## Required production exit gates (hard)

- [ ] **G1, loaded alpha.2 correctness.** Independent static review followed
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
- [ ] **G5, measured V2.2 control.** Same actual LZ4 page bytes,
      compressed-size histogram, arrivals, read/write mix and achieved
      load on independently owned equal `null_blk` configuration, with
      **mutually exclusive builds** of V2.2 and V3 `dm-swapz.ko`. Report
      independently measured lower read/write sectors and requests,
      including GC. Do not use ordered4 modeled geometry as control.
- [ ] **G6, authorized physical-media qualification.** After G1–G5
      pass and a separate review removes the current **null_blk-only**
      constructor guard, test only a clearly isolated, verified target
      SD/SSD/HDD backing. For the user-authorized `/dev/sdb1`, recheck
      active swap, mounts, holders, available memory and consent scope.
      **Do not touch any active swap** or force a cleanup. **NEVER REBOOT.**
      Compare physical medium host sectors, requests, CPU, p99 and GC,
      and device health/telemetry where available. Do not infer NAND
      endurance from host sectors alone.
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
