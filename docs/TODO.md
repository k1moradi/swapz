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

- [x] Owner-loaded alpha.11 corrected default smoke at `0a10cbfa`
      passed byte-exact I/O, lower READ/WRITE equality, FUA closure/age
      conservation, stable swap audit and ordinary teardown.
- [x] Owner alpha.12 `make run` on `2a3c872b` passed byte-exact,
      183/749,568B lower WRITE and 490/2,007,040B lower READ
      reconciliation, 119/119 FUA+age conservation and safe teardown.
- [ ] Qualify loaded alpha.13 `make run` and independent retained
      dependency/read-failure, FUA/PREFLUSH, expiry and suspend/drain
      paths. Header predicates and CI are not sufficient.

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
- [x] Owner-loaded alpha.11 control/candidate at `0a10cbfa`:
      matched immutable input and ~503 IOPS, full readback and teardown
      PASS. Retain=2 reduced WRITE bytes 26.99% and requests 67.14%;
      no READ saving, sampled WRITE p99 6.365ms versus off 1.081ms.
      Single short synthetic trial; sustained/CPU/GC NOT qualified.
- [x] Alpha.12 owner-loaded medium off/retain=0/retain=2 at
      `2a3c872b` passed byte-exact, matched ~503 IOPS,
      separate owned backing counters and teardown. Retain=2
      reduced WRITE bytes **34.8%** and WRITE requests **79.4%**
      versus off, with unchanged READ I/O; sampled WRITE p99
      **2.933ms** versus off **1.015ms** (unqualified tail).
- [x] Owner alpha.13 source `0a443ca4` loaded standard smoke
      and opt-in medium retain=0/retain=2 replay: byte-exact,
      matched ~503 IOPS, owned RAM safety and clean teardown.
      Retain=2: **1.5435 logical WRITE MB/s -> 1.0062 lower
      WRITE MB/s**, 34.81% fewer lower WRITE bytes and
      79.4% fewer WRITE requests than off. Sampled WRITE p99
      **2.788ms** vs off **0.984ms**; 17 cumulative early
      pack-ready and 1,168 deadline closures, no GC.
- [x] Owner alpha.14 `89c32842` default smoke and paced
      medium control/retained pilots PASS on independent,
      owned RAM null_blk. Retained: 1.54359 logical WRITE
      MB/s -> 1.00625 lower WRITE MB/s, 2,048,000 lower
      WRITE bytes/158 requests, zero GC, complete oracle,
      and ordinary teardown. Cumulative `close_pack_ready=64`;
      sampled WRITE p99 2.651ms (off 1.053ms).
      The **500 IOPS cap**, not the kernel maximum,
      set the low logical MB/s. Sustained CPU/p99 still open.
- [ ] Measure realistic ~2:1 nonzero LZ4 pages as well as exact zeros,
      compressible small objects and incompressible RAW controls.
      Verify actual compressed-size histograms, not assumed ratios.
- [x] Alpha.9 owner-loaded retest at `f9b9ec88` PASSED:
      exact lower reads 490/2,007,040B and writes 183/749,568B,
      119/119 FUA closures, full readback, unchanged host swap
      and clean teardown. Previous 8KiB mismatch unproven.
- [x] Alpha.11 owner smoke at `0a10cbfa` conserved all 119 window
      reasons and age bins. Medium candidate reported 199 unrelated-read
      closures and 1,086 deadline closures cumulatively.
- [x] Implement alpha.12 production-C immediate WRITE preparation,
      absolute hrtimer expiry, dependency-checked opt-in READ handling
      and fail-closed retained-WRITE abort. Source review only.
- [ ] Owner: qualify the exact production window-policy regression,
      no-arrival timer wake, mixed RAW/compressed records, dependent
      reads/overwrites, READ failure with pending writes, PREFLUSH/FUA
      and suspend/drain. Source/header predicates alone are insufficient.
- [ ] After matched loaded alpha.12 evidence, investigate lower-run
      composition and GC fullness economics only if still limiting.
      Historical alpha.8 READ bypass did not establish a matched win.
- [ ] Measure completed GC read/write traffic, reserve rotations,
      kernel CPU and RAM, achieved IOPS, cold read p95/p99 and full
      lower-I/O drain. Repeat runs and preserve negative/inconclusive results.
- [ ] Decide release readiness only from the gates in
      [VISION.md](../VISION.md) and the
      [readiness ledger](PRODUCTION_READINESS.md);
      V3 remains experimental and null_blk-only.

- [x] Owner alpha.15 `75d96be0` default loaded smoke
      and QD32/16,384-operation unpaced medium off/V3
      pair PASS on separately owned RAM devices. Off:
      **31.518 logical -> 31.518 lower WRITE MB/s** at
      10,248.9 achieved IOPS. V3 retained: **24.867
      logical -> 14.792 lower WRITE MB/s** at 8,086.3
      achieved IOPS. V3 completed 21.10% fewer IOPS,
      despite 40.52% fewer lower WRITE bytes and 83.25%
      fewer lower WRITE requests. READ lower bytes and
      requests matched the same trace; write p99 was
      2.333ms V3 versus 1.879ms off. Byte-exact final
      oracle and safe teardown PASS; no GC or CPU profile.
- [x] Owner alpha.16 `59acee35` default smoke and paced
      medium `retain=0` / `retain=2` comparisons PASS:
      independent READ/WRITE counters, byte-exact oracle,
      host swap unchanged and ordinary owned RAM teardown.
      Retained: 1.54353 useful WRITE MB/s -> 1.00621
      lower WRITE MB/s, 34.81% fewer bytes, 158 vs 767
      lower WRITE requests, sampled p99 2.688ms vs off
      1.104ms. The worker avoided 844 duplicate hrtimer
      arms but still armed 1,202 timers across 1,202
      cumulative windows. The owner's attached log
      contains NO unpaced alpha.16 trial, so no high-QD
      throughput improvement was verified.
- [ ] Owner alpha.17: after loaded default-off smoke and
      safe teardown, run the QD32 / 16,384-operation
      `make bench-pair-medium-unpaced` on newly owned RAM
      devices. Record completed logical WRITE MB/s, lower
      READ/WRITE bytes AND requests, achieved IOPS, p95/p99,
      GC, complete image and safe cleanup. Contrast
      alpha.15's 31.518 MB/s off vs 24.867 MB/s retained
      V3 and 40.52% lower WRITE bytes; test whether uniform
      ordering fast path improves throughput without
      sacrificing storage I/O. Do not claim saturation.

## Maintenance

- [ ] Resolve inconsistencies between older kernel/extent-v3 alpha
      documents and current V3.0.0-alpha.17 behavior when their claims
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
