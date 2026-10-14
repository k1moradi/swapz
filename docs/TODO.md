# Active V3 work queue

**Status: ACTIVE — 2026-10-14.** This is the *current* prioritized
checklist, not the dated V2.2 work log. Read
[the project vision](../VISION.md), [V3 roadmap](ROADMAP.md),
[testing standard](../testing_standards.md), and
[benchmark standard](../benchmark.md) for the acceptance criteria.
Use `main` only and follow the device/host safety restrictions.

## Blocking correctness and loaded qualification

- [x] Verify zero-elision loaded correctness on a uniquely owned
      RAM-backed `null_blk` at source `4c6e29b`: the 128-page
      write/overwrite/readback and flush smoke passed, 9 exact-zero
      writes were elided, and 183 writes / 1,464 lower 512B sectors
      agreed independently (see [benchmark](../benchmark.md)).
      This is not a matched off-versus-V3 benchmark.
- [x] Owner-loaded strengthened zero-elision and independent
      lower READ/WRITE sector guard PASSED at `2e21fac5`:
      9 elisions, 183 writes/749,568 B and 431 reads/1,765,376 B
      matched the owned null_blk counters; byte-exact oracle,
      flush, unchanged active swap and safe teardown passed.
      This is a synchronous smoke, not a paired comparison.
- [ ] Extend trustworthy loaded tests for mapping publication, upper BIO
      completion ownership, GC live-object relocation, reserve exhaustion,
      suspend/drain, and actual lower read/write/flush failure paths.
      Distinguish synthetic pre-submission EIO from real device failures.
- [ ] Reconcile V3 driver counters with independently measured
      lower-device reads and writes, including verification, GC and flush
      work. Preserve any unexplained differences.

## Blocking performance evidence

- [x] Owner-loaded `make bench-pair` pilot PASS at `cebc8bd6`,
      with 9.91% WRITE and 6.23% READ lower I/O reduction at
      matched 503 IOPS and byte-exact clean teardown. Short
      synthetic run only; sustained GC, CPU and p99 NOT qualified.
- [x] First loaded identical-trace, matched-achieved-load uncompressed
      off/V3 pilot at `cebc8bd6` (single synthetic short run);
      additional nonzero-medium paired pilot at `43be096c` qualified
      exact lower bytes/requests with negligible write savings.
      Sustained and production-qualification tests remain open.
- [x] Loaded opt-in alpha.10 `make bench-pair-medium` at `43be096c`:
      128 nonzero 2,073B pages, identical byte-exact oracle, matched
      503.48 IOPS, independent 4KiB/0.13% lower-write-byte savings,
      0% lower-read savings, ordinary teardown PASS. No GC;
      1,957/1,961 cumulative windows closed idle.
- [ ] Run separate exact-head `make bench-pair-medium` (control)
      and `make bench-pair-medium-retain` (explicit candidate);
      retain=0 is still the default. Validate both tables/status,
      identical SHA fixture/trace, independent lower bytes/requests,
      exact final readback and matching useful IOPS. Require
      loaded byte-exact FUA/READ/GC/drain/fault and strict 5% IOPS
      matching before any recommendation to enable retention.
- [ ] Measure realistic ~2:1 nonzero LZ4 pages as well as exact zeros,
      compressible small objects and incompressible RAW controls.
      Verify actual compressed-size histograms, not assumed ratios.
- [x] Alpha.9 owner-loaded retest at `f9b9ec88` PASSED:
      exact lower reads 490/2,007,040B and writes 183/749,568B,
      119/119 FUA closures, full readback, unchanged host swap
      and clean teardown. Previous 8KiB mismatch unproven.
- [ ] Load alpha.10 on newly owned RAM null_blk and qualify
      `sum(open-age bins)==windows` alongside all existing
      byte-exact, reason and independent lower-I/O gates.
      Next measure medium nonzero ~2KiB pages, not FUA smoke alone.
- [ ] Profile why production-C windows close (worker quantum,
      unrelated READ, conflicts, FUA/PREFLUSH, deadline, capacity), with
      actual device-request/sector evidence on matched asynchronous load.
      Follow [roadmap Stage 3A](ROADMAP.md#3a-diagnose-why-a-pending-window-closes).
- [ ] If the telemetry shows avoidable singleton closures, prototype
      bounded **opt-in write-window retention across worker quanta**;
      preserve a hard timer deadline, exact completion/mapping authority,
      GC/drain and barriers, and compare against same-source control.
      See [roadmap Stage 3B](ROADMAP.md#3b-retain-independent-pending-writes-across-work-quanta).
- [ ] Only if justified by measurements, independently test an unrelated
      READ bypass (historical alpha.8 bypass had no matched-load win),
      then investigate lower-run composition and GC fullness economics;
      do not enable unqualified behavior by default.
- [ ] Measure completed GC read/write traffic, reserve rotations,
      kernel CPU and RAM, achieved IOPS, cold read p95/p99 and full
      lower-I/O drain. Repeat runs and preserve negative/inconclusive results.
- [ ] Decide release readiness only from the gates in
      [VISION.md](../VISION.md) and the
      [readiness ledger](PRODUCTION_READINESS.md);
      V3 remains experimental and null_blk-only.

## Maintenance

- [ ] Resolve inconsistencies between older kernel/extent-v3 alpha
      documents and current V3.0.0-alpha.11 behavior when their claims
      are revisited; do not silently apply superseded host commands.
- [ ] Keep this checklist short: close verified items with an exact
      commit/test reference, update the owning standard with lessons,
      and move historical transcripts to existing evidence reports.
- [ ] Track documentation location and links using
      [the documentation guidelines](DOCUMENTATION_GUIDELINES.md).

**Retired work:** The 2026-10-08 to 2026-10-10 V2.x task history,
including legacy checkboxes, is retained *unchanged* in
[archive/v2.2/TODO.md](archive/v2.2/TODO.md) for provenance;
unchecked entries there are **not active V3 tasks**.
