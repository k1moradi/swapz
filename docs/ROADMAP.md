# V3 roadmap — measured lower-I/O improvement on main

**Status: ACTIVE — V3 experimental and NOT production-ready (read the current version from [VERSION](../kernel/extent-v3/VERSION)).** V2.2 is retired from active builds and required
benchmarks. The bounded dependency-aware pipeline remains **opt-in**.
Owner-reported owner-run at commit
`59761be5a2bcb7a8f1b0b9f764c27f0339eac9b4` passed RAM-backed
correctness and 16 full benchmark pairs but showed severe 4MiB
packed-read regressions (1.86s vs 0.40s in the slow-delay model).
The owner subsequently ran the streamlined two-model/timing-boundary
revision at exact source `aacf8cc869dcfc60c179adcce92a3632688832c6`:
all five stages PASSED (204.61s loaded stage, eight pairs), and the
sanitized result was published as report-only `e221e053e052`.
SD useful WRITE remained 7.85 MB/s raw versus 4.61 sync/4.66 async;
SSD was 19.67 MB/s raw versus 17.57 sync/19.01 async. Both models
reduced backing WRITE traffic but the packed 4MiB reads remained
slower. The owner subsequently qualified read diagnosis at exact source
`933ff984f8f603a3fa6d79dcde7a522d491e9502`: all five stages
PASSED; eight pairs took 205.17s loaded, reported at `18bf37313e4c`.
For SD-model packed 4MiB reads, the serialized C path made exactly
1,024 metadata requests and 640 extra payload requests per pass,
returning decoded data in ~1.83s versus ~0.40s raw. SSD-model
payload requests averaged 635 sync / 632 async and packed passes
remained slower than raw. These are not cold flash reads.
The owner then ran `make test -j2` at exact source
`d2eac4a1697879a566e7ca22a6d66f19ffc1562e`: all five stages PASS,
202.14s loaded matrix, published in report-only `3d2f2507bab9`.
SD-model sequential 4MiB READ improved from ~1.83s to 1.24/1.26s
(sync/async), reducing metadata calls to 469/483 and backing READ
bytes to 4.54/4.60 MiB. Seeded-random stayed ~1.84/1.83s with
~1,024 metadata and 640 payload callbacks and ~6.81 MiB backing
traffic. SSD-model sequential fell to ~0.31s but remained slower
than ~0.22s raw; random stayed ~0.39/0.40s vs ~0.27s raw.
Write throughput remained behind raw. All results are synthetic
RAM models, not cold flash reads; the new full-extent-read experiment
is NOT YET LOADED.
The owner then ran all five stages at exact source
`35fb224caba5bf61ab637181d963dadd9a94e6ef` (loaded stage 195.24s,
report-only `0d9ec4017a5f`, eight paired sessions). SSD-model
4MiB sequential 0.20/0.19s and random 0.26/0.26s matched or beat raw
0.23/0.27s in that synthetic model, but seeded-random lower READ bytes
grew to ~8.10MiB versus raw 4MiB. SD-model sequential improved
to 0.57s against 0.39s raw and random 1.16s against 0.40s;
WRITE remained 4.61/4.66 MB/s against 7.85 raw. Successful 8KiB
prefetch is therefore NOT a three-axis performance win.
The owner has now run all five stages on report-only
`71f54532d9ab167d7f0842247c4609f1b6fd4951` with
exact code `b848304aff321e738b5be50177143ba8797d7c32`
(latest result-only publication `b481256360f8`).
Loaded stage 194.96s PASS, eight pairs. SD model random 4MiB
READ ~6.81MiB lower traffic and ~1.16s completion versus raw
4MiB / ~0.40s; compared with ~8.11MiB before the offset hint.
SSD model random ~6.80MiB and ~0.26s versus raw 4MiB / ~0.26s.
The 4KiB skipping works (about 320 cold skips per random pass),
but no established swap-in latency improvement or useful SD WRITE
speedup resulted from this code revision.
The owner then qualified exact code
`ea9fe5892bde824b4076529bbc81a79aea3469aa`
(report-only `8a6f56a4d801`): all five stages PASS, loaded stage
195.21s. SD V3 mixed WRITE spent ~4.92s in successful synchronous
lower callbacks versus ~5.22–5.23s total window-commit wall time;
~4.58k callbacks all landed in the 1–4ms bucket while LZ4 used only
~0.14s. SSD lower wait was ~0.82–0.84s and almost all callbacks
were <=1ms. This strongly implicates serialized lower-write callback
count/latency in the SD-model useful-WRITE gap, without proving
hardware latency or exclusive kernel CPU.
The next two-pack policy was owner-qualified at code
`269fd05bc6dd5584282b861117a1e23e51a14b95`, tested at report-only
parent `e42573afa5d879ac10a660dd6bae40478df06661` and published
as `1214f8c20a7c`. All five stages PASS. SD useful WRITE improved
from 4.60/4.66 to 5.19/5.27 MB/s while V3 lower requests and lower
callback wall both fell ~31%. SSD lower requests fell ~44%, but useful
WRITE regressed from 17.69/19.31 to 16.60/17.39 MB/s. This shows
request aggregation helps when callback latency dominates, while
unnecessary retention delay hurts the faster model.
The owner next qualified exact code
`bd8fe3a8ff3d0878f243240f2a4ac01587b5ade0` (report-only
`be387969176f`): all five stages PASS and all three CI workflows PASS.
SD useful WRITE was 5.18/5.26 MB/s with ~3.28k/~3.30k lower requests
and ~3.53/3.54s lower-WRITE callback wall, retaining almost all of the
unconditional two-pack gain. SSD recovered to 17.97/18.51 MB/s versus
19.14 raw while requests remained ~2.62k, and benchmark classification
improved from MATERIAL_LOSS to NO_ESTABLISHED_GAIN for both V3 modes.
This validates accepted-backlog gating as the better cross-regime policy.
The owner then qualified exact code
`b4d828db54924389a7ac35c6327f6ffbe18cd4d5` (report-only
`7e8bdb9abf38`): all five stages PASS, but the narrower
plain-WRITE-only successor filter failed its predeclared performance
gate. SD useful WRITE slipped to 5.15/5.22 MB/s and lower requests rose
to ~3.36k; SSD slipped to 17.52/17.96 MB/s and requests rose to
~2.87k. Revert that policy refinement rather than accumulating another
heuristic on it.
The owner next qualified exact code
`ed2ea3df84c66eb0747d4161da4309831c4072f8` (report-only
`adbe231e66d0`). The accepted-burst extension materially improved
writes: SD useful WRITE 5.43/5.50 MB/s, ~2.88k lower requests and
~3.10s lower-write wait; SSD 18.31/20.40 MB/s with 2309.5/2152
requests. However the globally larger planner windows shifted records
into read-hostile layouts. SD random 4MiB READ regressed to
1.82/1.85s, 8,316,928/8,361,984 lower bytes and ~628/651 payload
callbacks; SSD random rose to 0.34/0.33s with ~8.45/8.43ms p99.
This is a write-side mechanism win but a rejected three-axis outcome.
The owner then qualified exact code
`c60f24a28fec48b33d616f9cd85f6bde8b02d591` (report-only
`8e2557839a3d`). The accepted-burst cap restored the read side while
retaining the request/wait improvement: SD useful WRITE 5.44/5.54 MB/s,
2865/2838.5 lower requests and 3.08/3.05s lower wait; random 4MiB READ
1.16s with ~6.80MiB lower traffic. SSD reached 18.84/20.69 MB/s with
2198/2159 requests; async is `MATERIAL_GAIN_PRELIMINARY`, and random
4MiB READ is 0.26s with ~6.67MiB lower traffic. This is the best current
three-axis RAM-model baseline. Its cost is WRITE-byte density: 1.38x
logical/backing on SD and 1.42/1.43x on SSD, below the denser
`ed2ea3d` layout.
Write-only saturation, kernel worker CPU, cold-cache tests and live GC
remain open.

The authoritative acceptance and engineering rules are
[vision](../VISION.md), [coding standards](coding_standards.md),
[testing standards](testing_standards.md),
[compile](compile.md), and [benchmark](benchmark.md).
Track short, actionable work in the active work queue below; preserve exact
results and outstanding release gates in
[current testing and release gates](testing_standards.md).
Only `main` is used unless the owner explicitly authorizes otherwise.

## Current three-axis performance work

The [three-axis specification](benchmark.md#three-axis-qualification-specification)
develops the owner's swap-out speed, lower-write/endurance proxy and
data-ready swap-in goals. The **current default matrix is two RAM-only latency models**
(10MiB/s plus 1ms completion and 80MiB/s plus 0.15ms completion),
with four counterbalanced pairs per model and 4MiB byte-verified
packed-populated read passes within the official `make test`.
The prior 16-pair four-model evidence is retained in Git history.
Worker/buffer/fixture/device setup is now excluded from timed
measurements while the required I/O completion and WRITE drain remain. A full write-only
saturation matrix, actual cold-device reads and live-GC profiling
are still planned.

- [x] Implement alpha.22 production C idle drain for a valid one/two-page
      compressed tail after a successful pack-ready commit. Preserve
      initial retention, boundaries, physical publication and completion.
      Source reviewed; compilation/tests NOT RUN by owner instruction.
- [ ] Owner: run `make test -j2` at the exact committed HEAD and examine
      useful throughput, lower WRITE bytes/requests, READ tails,
      `burst_tail_flushes`, closure conservation and safe teardown.
      Current capped results cannot establish uncapped improvement.
- [x] Retain only **two latency-modeled QD32 regimes** in the
      mandatory path (four pairs each), with identical trace/fixture,
      order counterbalance, strict ownership and a 5% exploratory
      threshold. The removed 20MiB/s and uncapped-RAM diagnostic rows
      remain as prior versioned results, not current physical media claims.
- [x] Exclude replay worker pool and buffer setup from timed read I/O;
      retain valid CPU/process scope, final write `fsync`,
      independent sector deltas and all read/write byte oracles.
- [x] Merge redundant owner-pair shell preflight into the existing
      rootless Python safety/regression suite; keep native-C and kernel
      module tests distinct for fault localization.
- [x] Add timed actual **4MiB** fixed-volume sequential/random reads of
      datasets populated through packed concurrent writes; verify every
      returned page, keep distinct working set and RAM/cache limitations.
- [ ] Obtain separate authorization and a rollback/recovery plan before
      any destructive SD-card testing; do not touch swap partitions with
      the current experimental module or tests.
- [ ] Expand to separately measured write-only saturation (QD1/4/8/32)
      with at least five pairs per regime and confidence intervals.
- [ ] Extend packed reads to a larger distinct working set with realistic
      cache/working-set control; 4MiB is not 100MB cold swap-in.
- [ ] Profile actual C preparation, queue/retention, lower I/O, CRC/decode
      and live GC; use exclusive CPU attribution and interval counters.
      A diagnostic-only read-path change now distinguishes metadata from
      payload lower callback requests and snapshots C read/decode wall
      counters across each timed 4MiB read pass, without new workloads.
      The one-extent metadata cache was owner-qualified at exact
      `d2eac4a`: sequential SD-model read time improved to ~1.24s,
      but random still used ~1,024 metadata plus 640 payload calls
      and took ~1.84s. A bounded production-C experiment now replaces
      cold two-block (8KiB) metadata+dependent-payload reads with one
      complete extent read, retaining the bytes only in existing scratch
      for an immediately subsequent same-extent read. A strict one-block
      planning budget retains metadata-first reads, as do 4-block extents.
      No new allocations or mapping publication semantics; faults and
      mutations invalidate, authority and CRC are still checked. The new
      full-extent optimization was owner-qualified at exact `35fb224c`:
      SSD-mode timings improved, but random 4MiB V3 reads transferred
      ~8.1MiB versus 4MiB raw and SD-model random remained slower.
      The next C-first optimization stores each codec-validated
      compressed payload offset in the volatile mapping and cross-checks
      it against the on-media descriptor and CRC on every read. On a
      cold 8KiB extent where the target payload fits wholly in block
      zero, skip the speculative second block **without adding a lower
      request**. Other packed 8KiB reads preserve one-request prefetch.
      Owner-loaded `b848304` code (report-only tested HEAD
      `71f5453`, sanitized report `b481256`) confirms ~320 skip
      callbacks and ~1.31MiB less random READ traffic per 4MiB
      compared with `35fb224`, but SD-model random still requires
      ~1.16s and SD useful WRITE still 4.61/4.66 MB/s versus 7.85 raw.
      Owner-loaded `ea9fe58` profiling now shows synchronous lower
      WRITE wait dominates SD commit wall time: ~4.92s lower wait
      inside ~5.22–5.23s commit, versus ~0.14s LZ4, with every
      ~4.59k callback in the 1–4ms bucket. SSD lower wait is only
      ~0.82–0.84s and nearly all callbacks are <=1ms.
      Owner-loaded code `269fd05` validates the mechanism but rejects
      unconditional waiting as the final policy: SD lower callbacks and
      wait wall fell ~31% and useful WRITE rose ~13%, while SSD useful
      WRITE regressed ~6% sync/~10% async despite ~44% fewer requests.
      Owner-loaded `bd8fe3a` confirms that accepted-backlog gating
      preserves the SD improvement (~5.18/5.26 MB/s, ~3.29k lower
      requests) while recovering SSD to 17.97/18.51 MB/s and
      NO_ESTABLISHED_GAIN classification versus raw. The subsequent
      `b4d828d` plain-WRITE-only filter was owner-qualified and
      **rejected**: requests and useful WRITE both worsened in SD and
      SSD. Restore the broader accepted-local signal.
      Owner-loaded `ed2ea3d` validates accepted-burst lower-request
      aggregation but rejects its unconstrained on-media layout:
      lower WRITE requests/wait improved materially, while 4MiB packed
      READ amplification/p99 regressed in both modeled regimes and SD
      random time returned near the pre-read-optimization ~1.8s range.
      Owner-loaded `c60f24a` satisfies that read-cap experiment's
      predeclared direction: packed READ bytes/callbacks/time recovered
      essentially to the pre-extension behavior while lower WRITE requests
      and wait stayed below `bd8fe3a`; SSD async reached a preliminary
      material useful-WRITE gain. The cost is independently visible in
      lower WRITE bytes (1.38x SD and 1.42/1.43x SSD logical/backing,
      versus 1.48/1.56-1.57x for the rejected dense layout).
      Do **not** guess a new threshold yet. The next production-C change is
      diagnostic only: for every default-policy accepted-burst window,
      compute the same ordered planner both uncapped and with cap=2 before
      the unchanged real capped write. Accumulate exact extra 4KiB blocks,
      windows whose cap costs >1 block, 16KiB extents avoided, and any
      impossible planner inconsistency. No allocation, I/O, timing policy,
      authority or wire-format change. Exact-C tests pin the 16x2072 case
      at 10 blocks / four extents / one 16KiB extent uncapped versus
      11 blocks / six extents / zero 16KiB extents capped. The uncapped
      planner's read-cost tie-break selects 3+3+3+7 records rather than
      the byte-equivalent 7+7+2 layout. Use the loaded distribution to decide the next
      Pareto policy. New source **NOT YET OWNER-LOADED**.
- [ ] Qualify same-page/RAW/barrier/error/suspend cases and sustained live
      GC before promoting retained or concurrent preparation defaults.

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
with retention off, flushes the pending window for **every non-write**
and at each worker quantum. Alpha.12 positive retention prepares new
writes promptly and permits only dependency-checked independent reads
until the original absolute hrtimer deadline. Its synchronous
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
  `off` vs loaded `swapz`. Never change host swap state.
- Collect independent lower READ/WRITE 512-byte stat-sector deltas,
  actual requests, flushes, GC bytes and requests, full drain,
  achieved useful IOPS, kernel CPU/RAM and cold READ p95/p99.
  Explain any target/device counter mismatch. Per the current
  [benchmark contract](benchmark.md), a pair outside the
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

**Implementation checkpoint: alpha.11 owner pilot at `0a10cbfa` saved
26.99% WRITE bytes / 67.14% requests at matched load, with 6.365ms
sampled write p99. Alpha.12 repairs immediate preparation and absolute
timer scheduling; compilation, tests and loaded qualification NOT RUN
by owner request. Default retention remains disabled.**

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

### 3C. Qualify dependency-aware unrelated READ handling

**Alpha.12 checkpoint:** alpha.11's owner-reported 199 cumulative
unrelated-read closures justify an opt-in dependency-aware read path.
It shares the positive retention gate and serialized worker, checks
slot/flags/authority, completes valid independent reads before unrelated
write drain, and aborts pending writes without lower submission if the
READ fails. New native policy/source regressions are authored, NOT RUN.
Loaded lifecycle and performance qualification remain open; the combined
candidate does not separately attribute each scheduling change.

- Continue measuring how often unrelated reads force early closure.
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
[full qualification gates](testing_standards.md).

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

## Stage 5A — prove readiness for a controlled real swap-drive trial (BLOCKED)

**Purpose:** establish reproducible evidence that the **exact production V3
kernel module** is sufficiently stable and safe to *consider* a separately
authorized destructive test on a dedicated physical swap drive. This is a
**physical-trial readiness gate, not proof of production deployment readiness**:
green CI, successful RAM-only tests or a single pilot cannot establish
real-device safety. The current `null_blk`-only admission remains unchanged.

**Go/no-go checklist — every item must PASS on one pinned `main` revision:**

- [ ] **Reproducible build and complete qualification:** record source commit,
      release `VERSION`, exact `.ko` SHA-256/vermagic, Linux kernel and build
      environment. Run the sole public `make test` interface to completion,
      including W=1/W=2, native/source/safety gates, loaded owned-RAM
      `null_blk` correctness and counterbalanced off/V3 trials. A skipped,
      BLOCKED or NOT RUN required stage does not pass this gate.
- [ ] **Byte-exact loaded correctness under stress:** repeat the full readback
      oracle across zero/compressible/RAW pages, overwrites, competing
      reads, DISCARD, PREFLUSH/FUA, high queue depth, drain/suspend and
      concurrent GC. Demonstrate exactly-once BIO completion, mapping
      authority and no stale/torn data or integrity errors.
- [ ] **Real failure-path and resource safety:** exercise device-originated
      lower READ/WRITE/flush failures (not just pre-submit synthetic EIO),
      partial/error completions, CRC faults, ENOSPC/reserve exhaustion,
      memory pressure and interrupted teardown on owned RAM devices.
      Show bounded recovery/quarantine without hangs, double completion,
      use-after-free, leaks or damage to unrelated devices.
- [ ] **Sustained stability and performance envelope:** repeat long-running
      churn/near-full GC and mixed swap-like workload trials at declared
      loads; record achieved IOPS/MB/s, independent lower READ/WRITE bytes
      and requests, complete drain, memory/CPU growth and cold-read
      p95/p99. Predeclare acceptance limits; explain counter mismatches
      and fail on reproducible integrity, liveness, resource or unacceptable
      latency regressions. Retain negative/inconclusive evidence.
- [ ] **Independent review and signed evidence:** review kernel-C
      concurrency, BIO and buffer ownership, failure/teardown paths and
      host noninterference; attach exact-HEAD test artifacts, failures,
      cleanup proof and a PASS/FAIL/BLOCKED/NOT RUN matrix to the
      [testing/release ledger](testing_standards.md). Obtain explicit owner
      acceptance of remaining risks before *proposing* a physical trial.

**Exit:** all five checks independently reviewed and recorded as PASS.
Any missing, inconsistent or unrepeatable evidence means **NO-GO /
PHYSICAL TEST BLOCKED**. Even a PASS **does not authorize** `make install`,
`swapon`/`swapoff`, changing the `null_blk` guard, or accessing any
physical or active swap. The trial below still requires its own reviewed
procedure and fresh per-device owner authorization; production deployment
readiness can only be assessed *after* separately approved device-class
qualification, not inferred from this preflight.

## Future owner-authorized physical trial — `/dev/sdb1` (BLOCKED)

The objective is eventually to measure real lower WRITE bytes/requests,
READ latency, GC behavior and sustained work on a dedicated physical
device, potentially `/dev/sdb1`. **This is a planned milestone, not
current authorization.** No code or test may bypass the existing
`null_blk`-only constructor admission before an independently reviewed,
separately approved source and host procedure exists.

Prerequisites: exact module/source hash and matching kernel, repeated
owned-RAM correctness and fault/drain/teardown qualification, full
byte-exact oracle and independent lower counters; positive verification
of device identity, capacity, holders, mounts, active-swap aliases and
filesystem/partition ownership; a host backup and data-loss/recovery
plan; explicit fresh owner approval naming that device and precisely
which destructive operations are permitted; a fail-closed ordinary
teardown/quarantine procedure with no force, reboot, or unrelated
system-swap changes. Confirm controller/queue geometry and compare
same-input off/V3 under repeatable achieved loads. If any condition is
unknown, report **BLOCKED**, not a physical benchmark PASS.

## Deferred scope

V3 mappings are volatile. Hibernation/resume persistence is potential
**V4** work requiring its own recovery format and kernel/boot review.

Historical [V3 goals and V2.2-era comparisons](https://github.com/k1moradi/swapz/blob/efc6a8b34c26f46419996578100b54841aa5c84c/docs/archive/v3/V3_GOALS.md)
remain provenance, not active engineering or benchmark requirements.

### Alpha.16 high-QD throughput checkpoint — not loaded yet

At exact alpha.15 `75d96be0`, the first unpaced
QD32 immutable 16,384-operation replay found a
strong lower WRITE cost improvement **but lower
useful throughput**: off 31.518 logical WRITE
MB/s, V3 retained 24.867 logical WRITE MB/s
(-21.10%), while lower WRITE output was 14.792
MB/s in V3 and 31.518 MB/s off. The target
reported 12,228 retention timer arms for 3,124
write windows. Alpha.16's C-first experiment
skips a timer restart when the same pinned
absolute expiration is already queued. It adds
the `retain_timer_arm_skips` diagnostic but
does not alter independent-page mapping, FUA,
GC or completion. This should be benchmarked
at the same QD32 unpaced workload with the
same complete readback; a benefit has NOT been
proven. GC/CPU and stable swap-in p99 remain
open qualification milestones.

### Alpha.17 C-first stable-equal-length packing shortcut

Owner-loaded alpha.16 `59acee35` passed the default
smoke and two separately owned, paced medium-replay
sessions. Its retained candidate avoided 844
redundant timer arms while moving 34.81% fewer
physical lower WRITE bytes at matched 503 IOPS,
but alpha.16 **unpaced** speed remains unknown.
The 128-page medium fixture has exactly equal
2073B compressed lengths, so alpha.17 avoids
the quadratic greedy permutation for a window
whose result is provably unchanged. The next
loaded qualification is the identical QD32,
16,384-operation **unpaced** comparison,
read/write bytes and requests, useful MB/s,
read/write p99, final oracle and safe teardown.
This fast path is not a substitute for sustained
GC, CPU profile or fixed-bandwidth validation.

### Alpha.18 phase attribution before another speculative rewrite

The owner-loaded alpha.17 smoke and paced off/V3
medium comparison at `90c0d5b9` retained 34.81%
lower WRITE-byte savings with exact readback and safe
RAM teardown, but WRITE p99 remained 2.742ms against
off 0.994ms. The log contains no unpaced QD32
throughput result; the latest qualified unpaced V3
reference is still alpha.15 at 24.867 logical
WRITE MB/s versus bare 31.518 MB/s. Alpha.18
instruments real C compression, decompression,
ordering, synchronous lower I/O, engine commit and GC
phase elapsed nanoseconds to separate likely worker
work from lower-device waits before a further pipeline
change. These are cumulative wall-times with nested
scopes, not CPU profiles and not proven throughput wins.
Require an owner-loaded QD32 unpaced replay of the
same immutable medium bytes and valid lower-device
READ/WRITE counters, upper p99 and full oracle before
choosing the next C optimization. Lifecycle GC and
fixed physical bandwidth remain unqualified.

### Alpha.19 worker quantum reuse: C-first high-rate hypothesis

At exact alpha.18 `88197bf4`, owner-loaded
QD32 unpaced V3 still performed 19.07%
fewer completed useful IOPS than the
uncompressed owned-RAM baseline (24.664
vs 30.475 MB/s logical WRITEs), despite
40.51% lower WRITE byte savings and
83.24% request savings. Byte-exact oracle
and safe teardown passed; GC remained zero.
Cumulative wall timers showed that LZ4
(71.7ms), sorting (0.95ms) and lower dm_io
(127ms combined) are insufficient by
themselves to explain 2s of total replay
time (overlapping, non-aligned intervals).
Alpha.19 makes a real serialized-worker
C scheduling change: process newly arrived
BIOs inline within the **existing** 64-BIO
quantum rather than requeue every mini-wave;
force yield when the budget is spent and
preserve shutdown drain/FIFO invariants.
This is a performance hypothesis, NOT an
owner-loaded victory. Recheck actual
high-QD MB/s, requests/bytes, p99, GC,
no starvation, full oracle and safe
teardown before another algorithm change.

### Alpha.20 evidence-based return to finite quantum handoff

Alpha.19 `841f5517` passed exact bytes and
owned RAM I/O reconciliation at unpaced QD32,
but V3 retained input reached only **23.650
logical WRITE MB/s**, compared with **32.490
MB/s** off on the same source/trace. Physical
lower WRITE savings remained **40.48%**,
but write p99 rose to 2.594ms (off 1.813ms).
The proposed inline worker continuation
ran 3,153 times with zero requeues, without
a useful throughput benefit. Alpha.20
withdraws this hot-path candidate from
production C, restoring alpha.18's bounded
handoff/FIFO/drain policy. This is evidence-
driven regression correction, not a claimed
performance win. Owner-loaded alpha.20
is NOT RUN. Future C optimizations should
be guided by repeated, counterbalanced
same-source throughput measurements and
actual CPU/queueing attribution, not isolated
micro-optimizations. GC/CPU and fixed
physical disk-bandwidth remain open.

### Alpha.20 fixed-source retention duration A/B, not yet run at 1ms

At exact alpha.20 `faf17bc2`, the owner-loaded
unpaced QD32 medium replay recovered 24.971
logical WRITE MB/s from alpha.19's separate
23.650 MB/s trial, while saving 40.52% actual
lower WRITE bytes at retain=2; against its
same-run off baseline of 32.256 MB/s, V3
was still 22.58% slower. Cumulative status
recorded 1,482 deadline closures and 1,642
early pack-ready closures from 3,124 windows,
with zero GC. The next controlled experiment
**does not change the kernel C yet**: evaluate
its existing retain=1ms and retain=2ms policies
with the same unpaced QD32 immutable medium
trace and independent two-device RAM lower I/O.
Judge trade-offs in useful logical MB/s,
lower WRITE bytes/requests, lower READ cost
and read/write p99; collect counterbalanced
repeats before an actual C scheduling
revision. The 1ms trial remains NOT RUN.

### Alpha.21: useful early packing at 2/3-record geometry

This is the first explicit production C modification
after the alpha.20 rollback and 1ms-test-only
increment. Under QD32, seven 2073B records can fit
16KiB, but a window of three has already earned
a real 4KiB WRITE-byte saving in one 8KiB extent.
The opt-in worker now allows that earlier commit,
plus a 2-record 4KiB case for sufficiently small
LZ4 pages. It does NOT alter mapping authority,
engine physical-success gates, FUA, GC or default
retention off. Its cost is a possible physical
WRITE-byte/request increase from fragmented
3+3+1 placements versus seven in 16KiB. Only
loaded, same-source null_blk lower counters and
upper useful MB/s/p99 can validate this trade-off;
alpha.21 remains NOT RUN. If byte efficiency
collapses or useful throughput does not improve,
revert the policy rather than add more wrappers.


## Current unresolved V3 work — merged TODO checklist

The 18 unfinished items below were moved from the former active TODO file.
Completed historic alpha.9–alpha.20 trial transcripts are summarized in
[benchmark](benchmark.md); the old TODO remains recoverable in Git history.
**Source/version priority:** alpha.21 and concurrent-preparation gates are
current; any alpha.12/13/20-specific experiment must be reproduced against
an explicitly pinned corresponding source and module before interpreting its
result. The **only official test/benchmark invocation is `make test`** from
repository root. It includes rootless checks plus loaded owned-RAM
smoke and paired benchmarks, and reports BLOCKED nonzero without
preauthorized noninteractive privileges. No direct script or other
Make goal is an official alternative.

### Experimental concurrent-preparation gate

- [ ] Run the full `make test` pipeline at the exact async source SHA,
      including its rootless checks, W=1/W=2 Kbuild, loaded oracle and
      paired benchmark, or record BLOCKED if safe privilege is unavailable.
- [ ] Verify full owned-RAM/null_blk FIFO readback for over 64 queued
      WRITEs, repeated same-page writes, READ/FLUSH/FUA/DISCARD ordering,
      lower WRITE injection, ENOSPC/GC and suspend/teardown; require no
      leaked or double-completed BIO.
- [ ] Counterbalanced medium QD32 off, synchronous V3 and
      `--async-prepare` V3 same-source runs at verified fixed
      ~20 MB/s independent lower WRITE cap. Measure input/lower
      READ/WRITE MB/s, requests, read p95/p99, CPU, memory,
      overlap starts, GC, integrity and teardown. Physical devices
      remain prohibited. **Loaded async outcome: NOT RUN**.

### Blocking correctness and loaded qualification

- [ ] Extend trustworthy loaded tests for mapping publication, upper BIO
      completion ownership, GC live-object relocation, reserve exhaustion,
      suspend/drain, and actual lower read/write/flush failure paths.
      Distinguish synthetic pre-submission EIO from real device failures.
- [ ] Reconcile V3 driver counters with independently measured
      lower-device reads and writes, including verification, GC and flush
      work. Preserve any unexplained differences.
- [ ] Qualify loaded alpha.13 a separately authorized owned-RAM V3 smoke and independent retained
      dependency/read-failure, FUA/PREFLUSH, expiry and suspend/drain
      paths. Header predicates and CI are not sufficient.

- [ ] Close the **Stage 5A physical-trial readiness gate** above with a
      pinned-source `make test` PASS, repeated loaded integrity/fault and
      sustained GC/latency evidence, independent kernel safety review and
      owner sign-off. Until all are documented: **NO-GO / PHYSICAL TEST
      BLOCKED**; no physical-device or active-swap test is authorized.

### Blocking performance evidence

- [ ] Measure realistic ~2:1 nonzero LZ4 pages as well as exact zeros,
      compressible small objects and incompressible RAW controls.
      Verify actual compressed-size histograms, not assumed ratios.
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
      [readiness ledger](testing_standards.md);
      V3 remains experimental and null_blk-only.
- [ ] Owner alpha.20: only after rootless and kernel
      build pass, run a separately authorized owned-RAM V3 smoke followed by
      a separately authorized QD32 unpaced owned-RAM off/V3 paired trial with newly
      owned RAM/null_blk and unchanged active swaps.
      Record logical WRITE/READ MB/s, independent
      lower READ/WRITE bytes and request counts,
      worker_requeues, GC, p95/p99, full oracle
      and clean teardown. Compare against exact
      alpha.18 and alpha.19 pilots. A repeated
      counterbalanced trial is needed to establish
      statistical confidence; no result yet proves
      higher maximum V3 input MB/s.

### Maintenance

- [ ] Resolve inconsistencies between older kernel/extent-v3 alpha
      documents and current V3.0.0-alpha.21 behavior when their claims
      are revisited; do not silently apply superseded host commands.
- [ ] Keep this checklist short: close verified items with an exact
      commit/test reference, update the owning standard with lessons,
      and retain detailed transcripts in immutable Git history or test artifacts.
- [ ] Track documentation location and links using
      the documentation ownership rules in [coding standards](coding_standards.md).
- [ ] On the SAME alpha.20 source/module, run
      a separately authorized same-source 1ms owned-RAM paired trial
      as a distinctly owned, opt-in RAM-only trial
      of the existing 1ms retention knob, and
      compare with the unchanged 2ms unpaced
      medium benchmark. Preserve equal immutable
      logical work and lower READ/WRITE bytes and
      requests, exact final oracle, p95/p99,
      achieved useful IOPS/MB/s, pack-ready/
      deadline closure reasons and safe teardown.
      Reject trade-offs that sacrifice I/O savings
      or latency; no new kernel alpha version for
      unchanged production C. Repeat in alternating
      order before claiming significant gains.
- [ ] Owner alpha.21 production-C short packed window qualification:
      run `make test` once; its internal stages cover rootless tests,
      owned-RAM V3 smoke and counterbalanced unpaced QD32 off/V3
      comparisons (retain_ms=2, 16384 measured operations).
      Require the exact full-image oracle, independent
      owned lower-device READ/WRITE bytes and requests,
      FUA/GC/suspend invariants, useful WRITE/READ
      MB/s, p95/p99 and clean teardown.
      Contrast with alpha.20's 24.971 logical input,
      14.854 lower WRITE MB/s and 40.52% byte saving.
      Do not promote early 3-record closure if request,
      read, latency or GC costs negate the input benefit.
      Repeat paired/counterbalanced tests before claims.
- [ ] Treat any alpha.20 1ms vs 2ms retention comparison
      as **version-specific**. Alpha.21 changed the
      kernel's early closure eligibility, so the
      previously planned 1ms trial is NOT a clean
      alpha.20-only configuration comparison once
      sources are updated. Compare experiments by
      exact source SHA and module hash, never mix
      C policy changes into a pure knob A/B claim.
