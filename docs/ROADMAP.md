# V3 roadmap — measured lower-I/O improvement on main

**Status: ACTIVE; first bounded owner-loaded Stage 2 pilot PASS; alpha.9 Stage 3A FUA telemetry smoke PASS; alpha.10 age telemetry not loaded, 2026-10-14.**
`swapz3` V3.0.0-alpha.11 remains experimental and **NOT
production-ready**. V2.2 is retired from active builds and required
benchmarks. This roadmap proposes a conservative, source-inspired
**bounded dependency-aware write pipeline**; it does not report that the
pipeline has been implemented, loaded, or shown to improve performance.

The authoritative acceptance and engineering rules are
[vision](../VISION.md), [coding standards](../coding_standards.md),
[testing standards](../testing_standards.md),
[compile](../compile.md), and [benchmark](../benchmark.md).
Track short, actionable work in [the V3 TODO](TODO.md); preserve exact
results and outstanding release gates in
[the production-readiness ledger](PRODUCTION_READINESS.md).
Only `main` is used unless the owner explicitly authorizes otherwise.

## The measured problem, and the existing foundation

The goal is fewer **independently measured lower-device READ and WRITE
bytes AND requests** for identical byte-verified useful I/O, including
GC, flush, p95/p99 read latency, CPU and memory costs. Compression
ratio, smaller encoded records, mock callback counts and successful
compilation are not sufficient.

Prior sustained V3 evidence found frequent **single-page write
windows**, so a ~2KiB LZ4 payload could still produce a full aligned
4KiB backing write. In the current production-C
[`dm-target.c`](../kernel/extent-v3/dm-target.c), `sv3_process()`
flushes the pending window for **every non-write** and
`sv3_worker()` flushes at each worker quantum. Its synchronous
`dm_io` runs can further limit opportunities to accumulate writes.
Not every such flush is unnecessary: ordering, synchronous writers,
bounded latency and safety are real constraints.

**Preserve what already exists:** `sv3_order_window()` does
size-complementary ordering within an admitted window;
[`engine.c`](../kernel/extent-v3/engine.c) selects 4/8/16KiB
SWZ3 extents with read-cost constraints and merges contiguous
compressed + RAW lower runs (up to existing 64 blocks/256KiB, not
across a 1MiB segment). [`authority.c`](../kernel/extent-v3/authority.c)
stages immutable reservations and publishes mappings **only after
confirmed lower completion**. Existing exact-zero-write elision,
CRC/generation validation, GC reserve and fail-close remain required.
Do **not** replace this work with a new codec, format or generic
userspace scheduler.

## Upstream design patterns to adapt — not code to copy

| Source implementation | Reviewed mechanism | Bounded swapz adaptation |
| --- | --- | --- |
| [OpenZFS `vdev_queue_aggregate()`](https://github.com/openzfs/zfs/blob/master/module/zfs/vdev_queue.c) | Compatible nearby I/O grouped within queue/size/latency constraints | Measure write submission composition; aggregate physically contiguous, compatible SWZ3/RAW output using the **existing** lower-run path |
| [Btrfs `compress_file_range()` / `submit_compressed_extents()`](https://github.com/torvalds/linux/blob/master/fs/btrfs/inode.c) | Preparation can precede an ordered submission phase | Separate bounded page copying/LZ4/RAW classification from *ordered* physical commit, without permitting early mapping publication or false upper completion |
| [F2FS `f2fs_submit_page_write()`](https://github.com/torvalds/linux/blob/master/fs/f2fs/data.c) | Pending merged BIO retained until incompatible operation or another submission boundary | Experiment with retaining swapz's bounded pending *logical* write window across worker invocations, while keeping an explicit deadline and ordering fences |
| [Linux `zsmalloc` fullness groups and `zs_compact()`](https://github.com/torvalds/linux/blob/master/mm/zsmalloc.c) | Prefer fuller allocation groups and compact sparsely used groups | Later evaluate size-class/occupancy-informed V3 GC victim and destination choices, **only** where measured net GC read/write cost improves |

These are architecture analogies, not drop-in filesystem or memory
allocator APIs. In particular, zsmalloc manages **RAM**, not durable
block I/O; OpenZFS C is **CDDL-licensed**, so do not copy it into
swapz's GPL kernel module without a separate license review.
Preserve existing swapz mappings, transaction authority and device
admission rules.

## Stage 1 — preserve and extend the loaded correctness boundary

- Maintain exact production-kernel-C unit/fault regressions, W=1/W=2
  Kbuild and exact `.ko` source/hash/vermagic identity.
- Preserve the user-loaded owned RAM-`null_blk` zero-elision evidence:
  source `4c6e29b` passed nine skipped writes and byte-exact
  readback; the strengthened sector/read/write guard passed at
  `2e21fac5`. Neither is a matched off/V3 performance verdict.
- Extend lower READ/WRITE/flush device-originated failure coverage,
  overwrite authority, upper BIO exactly-once completion, CRC,
  PREFLUSH/FUA, DISCARD, GC relocation/reserve exhaustion,
  suspend/drain and safe owned-resource quarantine. A pre-submission
  synthetic `-EIO` is **not** a torn/device-originated write.
- Before changing the scheduling model, capture a safe same-source
  current-behavior baseline, including existing window counters,
  zero-elision and fully drained lower-sector reconciliation.

**Exit:** exercised correctness gates are reproducibly scoped with
their exact revisions, module identity and teardown evidence; failures
are reported, not hidden. This is not a release or performance gate.

## Stage 2 — first real off-versus-V3 benchmark, before optimization

- First owner-loaded opt-in `make bench-pair` pilot at `cebc8bd6`:
  2 owned RAM lowers, byte-exact common trace, matched achieved rate,
  independent V3 lower WRITE savings **9.91%** and READ savings
  **6.23%**, ordinary teardown PASS. This short synthetic
  single trial is not sustained performance qualification.
- Compare the same immutable logical pages, operation trace,
  prefill, completed work and full byte-exact readback on **two
  distinct owned RAM-backed `null_blk` lower devices**: uncompressed
  `off` vs loaded `swapz3`. Never change host swap state.
- Collect independent lower READ/WRITE 512-byte stat-sector deltas,
  actual requests, flushes, GC bytes and requests, full drain,
  achieved useful IOPS, kernel CPU/RAM and cold READ p95/p99.
  Explain any target/device counter mismatch. Per the current
  [benchmark contract](../benchmark.md), a pair outside the
  predeclared **5% achieved-IOPS matching threshold** is inconclusive.
- Include measured-LZ4 nonzero ~2:1 (especially ~2,072B),
  exact-zero, tiny compressible, mixed and incompressible RAW inputs;
  QD1/4/8/32, competing reads, overwrites, FUA/PREFLUSH and a
  GC-heavy phase. Distinguish `O_SYNC` single-page limits from
  asynchronous windows; no implementation can batch unseen future
  writes from a strictly synchronous QD1 issuer.
- Preserve negative and unmatched results. Compare with **off**,
  not retired V2.2 as a required gate.

**Exit:** a reproducible loaded off/V3 lower-I/O result identifies
where lost opportunities arise; a negative result is acceptable
evidence. Do not infer a packing win from this plan alone.

## Stage 3 — source-inspired production-C write pipeline

Implement as **small, independently tested and opt-in steps**, using
the current V3 format, authority, scratch ownership and
`null_blk` restriction. Attribute changes first to
[`dm-target.c`](../kernel/extent-v3/dm-target.c) and its direct
production-C/source tests; touch the engine or authority only when
measured evidence and a focused invariant require it.

### 3A. Diagnose **why** a pending window closes

- Introduce low-overhead, bounded telemetry for attempted/admitted
  window size, age, size-bin mix, RAW/compressed composition, lower
  contiguous-run length, singletons and independent backing results.
- Count **one actual closure reason per window**: capacity, bounded
  deadline, worker-quantum boundary, same-page conflict,
  unrelated READ, duplicate WRITE, DISCARD, PREFLUSH/FUA,
  GC/resource pressure, shutdown/drain or error. Do not double-count
  reasons or mistake target `dm_io` calls for device requests.
- Add exact-C and rootless source regressions for classification;
  then correlate counts with owner-loaded matched-rate traces.

**Go/no-go:** proceed only if significant safe batching opportunity
is actually lost at avoidable closures. Otherwise investigate the
measured lower layout, read cost or GC bottleneck instead.

### 3B. Retain **independent** pending writes across work quanta

- Following the F2FS/Btrfs pattern, prototype one **bounded,
  opt-in** staging/commit policy rather than flushing at every
  worker invocation. Retain at most the existing 64 accepted pages
  in preallocated scratch, with a **hard, finite age deadline**;
  a timer must drain pending work even without new BIO arrivals.
- Keep original upper BIO ownership/sequence and required mapping
  authority. Flush at full window, deadline, actual conflict,
  PRE/POST-FLUSH/FUA barrier, suspend/drain, or error. Maintain
  per-page read-after-write, same-slot generation, DISCARD semantics,
  fail-close and exact-once upper completion.
- Preserve a serialized commit worker first: no parallel LZ4,
  multiple concurrent authority publishers, new on-media format or
  asynchronous `dm_io` completion in the initial patch. Limit
  staging memory, wait age, work quantum, CPU use and read starvation.
- Test timer expiry with **no new incoming BIOs**, shutdown with an
  outstanding batch, mixed RAW/compressed, overwrite/flush failures,
  reserve exhaustion, and each window-boundary ordering permutation.

**Go/no-go:** compare same-source original policy versus opt-in
retention at matched achieved load. Keep it disabled unless it improves
actual lower I/O without unacceptable cold-read p99, CPU/memory or
safety regressions; report QD1/`O_SYNC` cases where no gain is
possible.

### 3C. Consider dependency-aware unrelated READ handling **only if needed**

- After 3B, measure how often unrelated reads force early closure.
  An already-published mapping for an unrelated slot *may* be
  readable while other writes remain unpublished **only if** strict
  original order, barriers, read dependencies and lifetime safety
  are proven. Same-page reads/overwrites must not see stale or
  speculative data. Flushes and FUA must retain their original
  ordering and completion semantics.
- The previous opt-in alpha.8 disjoint-read bypass **failed to
  establish a matched-rate lower-I/O win**. Do **not** silently
  reactivate it or make it default. Require a distinct source-C
  proof, independent review, and predeclared enabled/disabled A/B
  counters on the same immutable trace.
- Stop this experiment if write-request savings disappear at
  matched achieved rate or are offset by lower reads, cold-read
  p99, starvation or worker CPU. No broad read reordering.

### 3D. Optimize lower request composition only if necessary

- Reuse the existing physically contiguous mixed RAW/compressed
  lower-run writer and V3 4/8/16KiB dynamic planner. Honor 1MiB
  segment and 256KiB run bounds, physical alignment and explicit
  padding accounting; never combine logically dependent records.
- Measure requests **and** bytes independently at the backing
  device. Do not treat one synchronous `dm_io` as one hardware
  request or improve request counts by writing hidden padding.
- Only if data proves this path limiting, consider a small,
  separately gated production-C change. Avoid speculative
  format/allocator rewrites or unproven entropy prefilters.

**Stage 3 exit:** rootless and loaded byte-exact/fault/drain tests
pass, and a reproducible **same-source control-versus-candidate**
result improves the lower read/write/request trade-off at matched
achieved load. A layout-only or compression-only improvement does
not satisfy the gate. Re-run Stage 2 against uncompressed `off`.

## Stage 4 — occupancy-aware GC and steady-state qualification

- Borrow only zsmalloc's **fullness/size-class selection idea**.
  Measure authoritative live size bins, packing feasibility,
  victim occupancy, relocation READ/WRITE bytes, reserve rotations
  and failed/no-headroom attempts before changing GC selection.
- Prefer a GC candidate only when its **measured expected total
  lower-I/O and safely reusable space** improve over today's
  policy. Preserve exact liveness, CRC/generation authority,
  failed-write quarantine, bounded allocations and the prohibition
  on recycling partially live segments.
- Repeat matched `off` versus V3 tests under overwrite/discard
  churn, repeated rotations, near-full reserve, RAW/medium/tiny
  size mixes, competing reads, cold-read p95/p99, CPU and memory
  pressure. Compare steady-state outcomes, not just a burst.
- Report source-only, loaded RAM-`null_blk` and physical-device
  evidence as distinct levels. Preserve failed trials and
  conservative timeout/quarantine behavior.

**Exit:** sustained independently verified lower-I/O improvement
with correct data and acceptable read latency/CPU/memory, or an
explicitly documented negative result and next measured bottleneck.
Readiness still depends on
[the full production gates](PRODUCTION_READINESS.md).

## Stage 5 — release review, separate from experimental benchmarks

- Do not claim production-readiness from green CI, better packing,
  synthetic null_blk counters, one successful pilot or an isolated
  burst. Independently qualify completion ownership, genuine lower
  errors, GC liveness, exact resource bounds and end-to-end
  sustained behavior before release.
- V3 **must remain null_blk-only** throughout this roadmap.
  Any SD/SSD/HDD testing, admission-guard change, user system-swap
  integration, persistence or install automation requires a **separate
  explicitly owner-authorized and reviewed project**. No reboot,
  `swapon`, `swapoff`, active swap or physical/unowned device access
  is authorized here.

## Deferred scope

V3 mappings are volatile. Hibernation/resume persistence is potential
**V4** work requiring its own recovery format and kernel/boot review.

Historical [V3 goals and V2.2-era comparisons](archive/v3/V3_GOALS.md)
remain provenance, not active engineering or benchmark requirements.
