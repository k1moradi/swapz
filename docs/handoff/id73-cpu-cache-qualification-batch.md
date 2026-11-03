# Historical ID73 CPU/cache qualification batch

This file preserves the completed ROADMAP implementation and qualification
summary for ID73 from commit `49fa607fc36c52dcfb0a49dc2986543f7c5cf87f`. The text below is source-bound
historical evidence, not a current release PASS or a substitute for exact-source
owner qualification. Current production invariants live in
[coding_standards.md](../coding_standards.md); qualification requirements live
in [testing_standards.md](../testing_standards.md), whose ID73 section remains
the normative technical contract. Current operating and evidence policy is in
[AGENT_CONTEXT.md](../AGENT_CONTEXT.md) and [README.md](../README.md).

## ID73 — CPU/cache qualification batch

Status: **implemented on `main`; native and loaded qualification required before
any optional policy promotion**.

This batch targets work that current phase timings made visible without changing
SWZ geometry, authority ordering or the default compression policy.

- **SSE2 delta64 load path:** forward transform retains the previous XMM pair
  and forms `[previous.high,current.low]` with `shufpd`, so each 16-byte
  output consumes one new 16-byte input load. The inverse forms its shifted
  prefix operand with register-only `pslldq $8`. Both remain byte-identical
  to scalar delta64. Native qualification checks emitted instructions and
  continues to report backend ns/page.
- **Validated metadata hits:** metadata from the direct validated cache,
  metadata set, or validated extent LRU uses descriptor-only lookup rather than
  recomputing metadata CRC and duplicate-record validation. Cold metadata and
  provisional ID63 coalesced bytes still run full `swapz_validate()`.
  Cached metadata sequence must match the compact per-extent sequence index
  for the authoritative start block before any payload lower read; logical
  identity, generation, offsets, authority comparison and payload CRC still
  execute on every logical read.
- **Publication preflight:** `swapz_finish()` builds bounded old-extent and
  old-segment deltas in authority-owned scratch, validates aggregate mapped/GC
  accounting without touching global arrays, then applies each aggregate once.
  The old mutate/restore GC preflight and repeated per-record authority scans
  are removed. Paused transaction hashes cover only the active transaction
  prefix through `records[count]`; staging zero-initializes the transaction,
  and all semantically active header/record bytes remain protected.
- **Planner uniqueness reuse:** the generic planner retains duplicate-page
  defense. The private production batched path alone skips repeated duplicate
  scans after `swapz_validate_batched_pages()` has already proved the whole
  batch unique.
- **Early exact-zero routing:** after ordinary LZ4 returns a tiny candidate,
  the existing full-page zero scan runs before delta64 rescue and payload CRC.
  A true zero becomes the same logical hole as before and no payload bytes are
  copied into the ordered batch.
- **LZ4 acceleration evidence:** three-host loaded evidence closed the ordinary
  first-pass acceleration experiment without a repeatable service win.
  Production ordinary LZ4 is fixed at acceleration one and the runtime selector
  plus routine loaded 1/4 A/B are retired. Native qualification still sweeps
  1/2/3/4 as a byte-exact CPU/geometry regression check. Delta64's second LZ4
  retains its separate acceleration control, default 4 since ID115.
- **ID63 bounded adjacent-range chain:** the active path now extends the
  qualified pair mechanism to 2..8 physically adjacent immutable extents when
  their exact missing ranges form one zero-padding lower read. The lower-read
  span remains capped by the existing eight-block/32KiB scratch. Eight private
  engines share one 64-page decode-output pool rather than multiplying 256KiB
  buffers. Conservative 3+ full-extent counters remain opportunity evidence;
  `parallel_read_coalesced_reqs_saved` records N-1 for an N-extent chain.
- **Production delta64 wrapper cost:** kernel status reports transform calls
  and wrapper-inclusive transform wall, including `kernel_fpu_begin/end` on
  x86. Current loaded/native comparisons put the wrapper premium in the
  hundreds-of-nanoseconds range while total rescue work is tens of
  microseconds per page, so FPU-transition batching is deprioritized relative
  to compression and scheduling work.
- **Delta64 preparation width:** async preparation owns one producer lane
  regardless of delta64 policy. Two-host K=1/K=2 evidence and earlier K=4
  regressions closed the concurrency question; the runtime preparation-width
  selector and routine K=2/K=4 qualification are retired. Predictor scratch
  allocation remains conditional on rescue being enabled.
- **Low-risk companion work:** validated extent-cache refreshes copy only
  missing blocks; slot priming never republishes provisional coalesced bytes;
  GC relocation reuses the payload CRC just verified by the read engine; the
  GC sorter uses the existing uniform-length identity fast path; successful GC
  no longer rewinds the allocator's circular probe, and equal-cost victim scans
  begin from that probe. These are allocator-fairness changes, not NAND wear
  claims.
- **Scalar hot-path follow-up:** bounded planner fit/candidate evaluation,
  batched-run setup, publication preflight, READ eligibility, metadata lookup
  and SWZ descriptor validation avoid redundant scans/branches after the same
  operation has already proved the required invariant. This changes no SWZ
  bytes, extent classes, scheduling policy, lower-I/O depth, authority order or
  cache capacity. Treat it as CPU-work reduction only: exact-source
  qualification must preserve byte-exact output and lower bytes/requests, and
  any performance claim must compare useful service plus planner/publish/read
  non-I/O attribution against the pre-change `9202ce7` baseline.
- **Structural proof reuse:** after the scalar pass is qualified, publication
  authenticates metadata CRC once and folds descriptor adjacency/transaction
  identity into the existing Phase 1 walk; batched staging/appending reuse the
  window-wide uniqueness proof for their quadratic scans; and replay completion
  finishes through the CRC-authenticated authority-owned active transaction.
  Public validators/staging remain defensive. This remains CPU-only evidence:
  use `329a10c` as the immediate pre-change baseline, preserve exact geometry
  and lower-I/O invariants, and require owner `make test` before any
  performance promotion.

Acceptance is byte-exact native correctness, sanitizer cleanliness, x86 SSE2
instruction-shape checks, W=1/W=2 kernel builds, and the existing owner-only
loaded matrix. For performance promotion require matched same-host evidence.
For `lz4_acceleration`, report per-setting compression CPU plus planner
blocks/extents and loaded lower WRITE bytes/requests. For delta64, report
wrapper-inclusive transform ns/call alongside raw backend ns/page. For ID63, report both the conservative 3+ opportunity counters and active
request savings; any 3+ promotion requires exact-range native coverage plus
matched loaded lower-request, throughput and p99 evidence.
