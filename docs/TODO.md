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

- [ ] Run the explicit `make bench-pair` owned-RAM pilot, confirm
      correct teardown and independent counters. Loaded status: NOT RUN.
      The bounded pilot does not qualify sustained GC or read p99.
- [ ] Perform the **first** immutable-fixture, same-operation,
      same-achieved-load **uncompressed off versus V3** loaded replay
      on *separately owned* RAM-backed `null_blk`; compare independent
      lower READ/WRITE bytes **and requests** and byte-exact readback.
- [ ] Measure realistic ~2:1 nonzero LZ4 pages as well as exact zeros,
      compressible small objects and incompressible RAW controls.
      Verify actual compressed-size histograms, not assumed ratios.
- [ ] Diagnose production-C singleton write windows under asynchronous
      matched load; evaluate bounded aggregation without violating same-page
      read ordering, generation authority or PREFLUSH/FUA.
- [ ] Measure completed GC read/write traffic, reserve rotations,
      kernel CPU and RAM, achieved IOPS, cold read p95/p99 and full
      lower-I/O drain. Repeat runs and preserve negative/inconclusive results.
- [ ] Decide release readiness only from the gates in
      [VISION.md](../VISION.md) and the
      [readiness ledger](PRODUCTION_READINESS.md);
      V3 remains experimental and null_blk-only.

## Maintenance

- [ ] Resolve inconsistencies between older kernel/extent-v3 alpha
      documents and current V3.0.0-alpha.7 behavior when their claims
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
