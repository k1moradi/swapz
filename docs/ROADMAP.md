# V3 roadmap — active development only

**Status: ACTIVE, 2026-10-14.** `swapz3` V3.0.0-alpha.7 is
experimental and **NOT production-ready**. V2.2 is retired from
required builds and benchmarks. This plan is subordinate to
[the project vision](../VISION.md), [coding standards](../coding_standards.md),
[testing standards](../testing_standards.md),
[compile](../compile.md), and [benchmark](../benchmark.md).
The short [action queue](TODO.md) is the place to track open work.

## Stage 1 — prove the current loaded correctness boundary

- Continue exact production-kernel-C tests for page codec, generation
  authority, GC liveness, upper-BIO completion, flush/FUA and fail-close.
- Compile V3 at W=1/W=2; verify the exact `.ko` SHA/vermagic.
- Preserve the verified post-zero-elision loaded smoke at source
  `4c6e29b`: nine skipped zero-page lower writes, byte-exact
  readback and clean teardown on an owned RAM-backed `null_blk`.
  The strengthened nine-elision/lower-sector guard PASSED on the
  user's owned host at `2e21fac5`, including exact lower read/write
  deltas and safe teardown. Retest following production C changes;
  report BLOCKED if ownership or prerequisites cannot be proven.
- Expand real lower-read/write/flush failure qualification and GC
  callback/drain ownership without misrepresenting pre-submission
  synthetic failures as device-originated events.

**Exit:** byte-exact readback and verified safe completion/teardown
for the exercised cases, with unresolved faults explicitly listed.
This is not proof of a lower-I/O performance win.

## Stage 2 — establish the first valid two-arm measurement

- Use the **same immutable pages and operation trace** for the
  *uncompressed* direct off arm and the *loaded V3* arm on equivalent,
  separately owned RAM-backed `null_blk` devices. Do **not**
  disable or modify host swap.
- Record paired independent lower-device READ and WRITE **bytes and
  request counts** separately, completed useful work, FUA/flush and GC
  I/O, full final readback, achieved IOPS, read p95/p99, CPU and RAM.
- Cover real measured ~2:1 nonzero LZ4, exact zeros, RAW controls,
  mixed sizes, low QD, competing reads, overwrites and actual drain.
- Repeat qualified runs; preserve rejected trials and unexplained
  counter differences. Source tests, geometry and synthetic compression
  ratios cannot replace the loaded measurements.

**Exit:** an honest reproducible off-versus-V3 result with integrity,
matched achieved load, provenance and stated limits (including a
negative or inconclusive finding if that is what the evidence shows).

## Stage 3 — fix the measured production-C bottleneck

- Prioritize the singleton-write-window and physical lower-request
  submission path where Stage 2 measures it. Evaluate bounded,
  generation-safe independent-page aggregation and 4/8/16KiB extent
  packing with real request and sector deltas.
- Preserve read-after-write, DISCARD, PREFLUSH/FUA, exactly-once
  completion, authoritative publication, GC relocation and bounded
  reserve usage. Do not weaken assertions or null_blk-only admission.
- Re-run stages 1 and 2 after each material change and record whether
  lower **read plus write** I/O actually improved without unacceptable
  swap-in p99, CPU or memory cost.

## Stage 4 — steady state and release gates

- Require long-lived overwrite/GC, full drain, fault handling and
  repetition under matched achieved load. Track read and write
  amplification and resource cost, not just compressed size.
- Keep [the readiness ledger](PRODUCTION_READINESS.md) honest about
  current, historical and missing evidence. Do not claim a general
  win or ship V3 based on compile/rootless/small smoke PASS alone.
- Any future real SD/SSD/HDD testing is a **separate explicitly
  owner-authorized project**, after host safety and appropriate
  kernel admission review. This roadmap authorizes **no** physical
  device access, system swap activation, reboot or automatic DKMS install.

## Deferred scope

V3 is volatile-only. Persistent hibernation/resume is a potential
**V4** milestone requiring a separately designed safe persistent
format, recovery model, boot integration and validation.

The previous more speculative alpha.6/alpha.7 goals and V2.2
control comparisons remain [archived for provenance](archive/v3/V3_GOALS.md),
not an alternative current benchmark mandate.
