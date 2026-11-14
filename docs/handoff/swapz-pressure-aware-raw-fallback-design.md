# Pressure-aware RAW fallback — architecture proposal

**Agent 6 design review (2026-11-14).** Source examined: `main` at
`084b80955a0ddd0c8155a7d22c633e700a8babd9`. **Proposal only; no module policy, format,
public API, module parameter, device or lifecycle change.** Preserve
`docs/VISION.md`, the existing owner-qualified K=1 ordered authority,
preallocated 64 preparation slots, existing submitter/background lanes,
and the strict published WRITE/READ completion rules.

## Upstream zswap collaboration is the first classification priority

**Code audit at `main` `c0a10f767d31bb07f02d22d4b2a9119d6500c7a6` (2026-11-14).** The canonical plan
already exists in `docs/ROADMAP.md`, section "MM-aware storage blueprint:
zswap collaboration and locality", with four separate milestones:

| Stage | Current implementation | Evidence |
| --- | --- | --- |
| A: authenticated `ZSWAP_STORED_WRITEBACK` origin across mm/swap, BIO clone/split and DM | **Not implemented** | `src/kernel/dm-target.c` has no zswap origin reader or verified per-BIO tag; `REQ_ZSWAP_WRITEBACK` is illustrative, not an upstream flag |
| B: bypass swapz LZ4/delta64 for selected proven-origin pages | **Not implemented** | Existing `preparation_force_raw`, `RAW_SELECTED`, 64-slot reservoir and publication paths are reusable but presently scheduling-only |
| C: matched, device-sensitive zswap-on/off and bypass-on/off tests | **Not qualified** | Roadmap defines workload/counter/fault gates; no source-bound positive zswap writeback result |
| D: hand off actual zswap-compressed payload to swapz without decompress/recompress | **Design only** | No codec/format/payload-lifetime/read-side integration |

### Representation and ratio semantics — do not misclassify zswap pages

A page stored in **zswap RAM** does not enter the swapz Device Mapper
backing target and is **absent from swapz's committed foreground counters**.
On later zswap eviction, Linux `zswap_writeback_entry()` reconstructs a
normal 4 KiB swap-cache folio and issues ordinary backing swap I/O.
The upper BIO contains the **decompressed original bytes**, not its prior
LZ4/ZSTD/zswap payload and not an authenticated compression-origin tag.

For that backing BIO, `swapz` counts a successful compressed payload as
`compressed`, a full original page committed without compression as `raw`,
and a proven all-zero representation as `zero_elided`. The number of
zswap compression attempts, their RAM bytes and their codec do **not**
contribute to the swapz cumulative write-ratio numerator or denominator.
A zswap-stored-and-later-recompressed page counts only **once** as a committed
swapz logical WRITE; it is not counted twice in the swapz ratio.

A zswap-origin bit is **not proof of useful compression**. Current upstream
zswap can retain full-size uncompressed pages under its writeback policy.
The provenance design should carry authenticated semantic origin separately
from optional proven **representation metadata** (compressed vs uncompressed,
codec and encoded byte count); initial rejection is a distinct case and is
not necessarily a bad compression result. Avoid treating zswap's name,
`REQ_SWAP`, current task, PG_reclaim or drop-behind as a reliable origin.

### Revised optimization ordering

1. **First, measure** whether the high RAW fraction is predominantly
   ordinary no-fit content, pressure-selected unfinished preparation or
   genuine zswap writeback. Use read-only interval deltas and zswap's own
   distinct system-level metrics. Kernel zswap statistics may span several
   backing devices: do not attribute a global counter to a named mapper.
   Never induce reclaim pressure on the owner's retained live mapper merely
   to obtain a benchmark sample.
2. **Then implement Stage A safely** in a separately reviewed kernel
   patch/integration, with a provenance lifetime bound to every BIO through
   split/clone; support ordinary and ambiguous fallback unchanged. Only
   after this stage may swapz safely classify a known zswap writeback.
3. **Stage B is a device-sensitive opt-in, not a universal RAW rule.**
   A page that was compressed in zswap is usually still compressible after
   Linux reconstructs it. If swapz could store it in one or two fewer
   physical blocks, a blind RAW bypass saves CPU at the cost of durable
   backing bytes, requests, cold-read work and wear. Compare marginal
   compression time against conservative device service/packing and current
   CPU pressure; retain normal compression when it is beneficial, and never
   weaken reclaim completion deadlines.
4. **Investigate Stage D as a distinct high-value experiment** only after
   end-to-end provenance and decode/ownership feasibility are proven. A
   direct compressed handoff avoids *both* zswap decompression and swapz
   recompression, and can retain compression efficiency. It must carry
   exact compressed length, codec and any dictionary/version dependencies,
   integrity proof, buffer ownership/release, and read/GC decoding.
   ZSTD/LZ4 are not interchangeable with swapz's existing LZ4/delta64
   encodings; do not reinterpret compressed zswap bytes as a current SWZ
   record. Revert to ordinary decompression/backing I/O when unavailable.
5. **Only afterward** experiment with generic CPU-budgeted predictor
   scheduling for the remaining untagged/ordinary workload. It must not
   accidentally optimize the wrong population by mixing zswap-eviction,
   naturally incompressible and pressure RAW pages in one ratio.

For illustration, if the original 4096-byte page occupied 1024 bytes in
zswap RAM and would occupy 1536 bytes after swapz recompression, committing
it RAW writes a full 4096-byte logical block instead. Whether that is faster
depends on the actual CPU and lower device. A hypothetical direct handoff
could retain the 1024-byte payload (subject to packing/physical-block
rounding and codec compatibility), but it is **not** implemented.

**Promotion criteria:** proven provenance and split/clone persistence;
bounded RAW snapshot and no producer-after-BIO lifetime; zero codec attempts
on deliberately bypassed tagged pages; intact generation/CRC/ordered
publication; byte-exact swap-in; FUA, overwrite, DISCARD, suspend, GC,
ENOMEM and error-path correctness; matched useful WRITE/READ throughput,
p95/p99, CPU/PSI and independently measured lower WRITE bytes and requests
for zswap-enabled cohorts on each device class. No extra lifecycle authority
or automatic manipulation of the currently active Lubuntu development
mapper follows from this design.

## Problem statement and evidence limits

Compression and the lower device have independent service capacities.
When incoming page-out demand `lambda` exceeds the effective compression
capacity `mu_cpu` for long enough, waiting for every page inevitably grows
a queue at least at rate `lambda - mu_cpu`. Bounded RAW fallback is necessary
to preserve reclaim progress; moving those pages into an unbounded RAM queue
would risk memory-reclaim deadlock and OOM. However, RAW selected **before a
potentially useful compressed candidate finishes** may waste CPU and lower
bytes simultaneously. The optimization problem is to reduce *avoidable*
RAW, not to forbid RAW or trade unlimited reclaim delay for density.

The existing public `swapzctl status` gives **successful cumulative**
`raw`, `compressed`, `zero_elided` and lower-byte counts, but cannot
attribute RAW to CPU load. A large RAW share is compatible with truly
incompressible/encrypted/previously compressed content, not-ready fallbacks,
and changes in workload. The same-source kernel INFO diagnostic already
offers `work_conserving_raw_not_ready`, `work_conserving_raw_ready`,
`prep_ordered_raw`, `prep_late_results_discarded`,
`lz4_raw_fallback`, `lz4_attempts`,
`ordered_lz4_page_ewma_ns` and
`lower_write_block_service_ewma_ns`. These are **not a common denominator**:
some are admission/attempt-side (including speculative, later aborted work)
and others are successfully committed pages. Take successive deltas and
compare like-for-like; do not equate the lifetime RAW percentage with
compression throughput or the attempt histogram with committed RAW.

## Existing mechanism: preserve its useful properties

- `swapz_compress_page()` tries ordinary LZ4 and selected predictor-first
  delta64+shuffle+LZ4 candidates; a valid compressed result is published
  only with a positive payload length. A zero result means no fitting codec
  representation. A negative result is an **error**, never a RAW success.
- Async preparation publishes into a fixed 64-slot, refcounted,
  `PREPARING / READY_COMPRESSED / READY_RAW` state machine. The ordered
  consumer may atomically select RAW when the producer is still preparing.
  Completed late candidates can then be discarded. Both actors already
  own distinct scratch and no producer may use a BIO after its lifetime ends.
- Ordered `swapz_accept_write()` consumes the ready representation when
  available; `work_conserving_raw_not_ready` or
  `preparation_force_raw` mark deadline/pressure RAW paths, while
  `work_conserving_raw_ready` denotes an already finished non-fitting
  preparation. The policy also checks marginal CPU-versus-lower-service
  estimates with `swapz_window_raw_hand_pays()` and respects whether the
  eight-record hand can actually dispatch.
- Once chosen, a RAW or compressed representation is immutable for the
  pending transaction. Only successful lower I/O grants latest-generation
  mapping authority and one upper-BIO completion. Do not weaken this rule.

## Recommended implementation sequence

### Phase 0 — prove which RAW is avoidable (read-only, lowest risk)

1. For the **same** target and exact code source, sample the named INFO
   counters before/after short, steady swap-out periods with matched
   incompressible, compressible, and representative anonymous-page input.
   Record useful page-out throughput, CPU PSI, attributed worker CPU,
   lower WRITE bytes/requests, busy/idle gaps and p95/p99 READ/WRITE latency.
   Record lower-device speed class and sustained vs burst arrival shape.
2. Attribute whether the excess RAW primarily consists of codec no-fit
   (ready RAW), not-ready/forced RAW, or late discarded compression.
   Normalize by completed foreground writes only where the code can prove
   completion, **not** by raw attempts. If existing mixed-lifetime counters
   cannot answer this, add strictly passive *commit-side, reason-labeled*
   page counters at the existing ordered publication boundary, with one
   unambiguous source per successfully committed page; keep attempt and
   success counters separately. Avoid extra clocks or locks in hot paths.
3. No dynamic policy change unless the not-ready/forced RAW class is material
   **and** the candidate pages have demonstrably compressible content.
   A workload with 90% genuine no-fit RAW needs a cheaper reject path or
   different source content, not more compression workers.

### Phase 1 — CPU-budgeted candidate routing (first performance experiment)

Preserve the existing preparation FIFO, ordered owner, K=1 physical run
and fixed resources. Evaluate the next candidate in this order:

1. **Avoid wasted codec CPU.** Make the lightweight existing predictor score
   useful for reliably identifying extremely unlikely-to-fit pages before
   spending a full LZ4/delta64 attempt. Guard false-negative compression
   savings with matched source content. Do not classify a page as
   incompressible from its filename, origin guess or past pages' scores.
   Never silently skip the mandated delta64 rescue on valid eligible
   pages in a qualifying workload.
2. **Prioritize work likely to save physical blocks/requests.** In the
   producer, compare expected marginal lower *allocation and WRITE
   service* from a compressed candidate (including 4/8/16 KiB packing
   geometry) against measured compute cost, overlappable lower service,
   and remaining deadline. A single 50% page-size heuristic does not
   account for pack-boundary crossings or request fragmentation. Keep the
   selector bounded/O(1) per admission using cached costs/cheap classes;
   do not sort an unbounded queue, create new threads or make map wait for
   compression.
3. **Preserve work-conserving fallback.** When the next lower WRITE can run
   and compression cannot finish within its conservative service budget,
   use the stable RAW snapshot. When lower service is busy or a ready
   compressed payload already exists, avoid discarding it solely because a
   queue-depth threshold was crossed. Never wait for a speculative future
   result past the existing finite idle/retention deadline.
4. Prefer a simple, independently reversible **default-off** experiment
   over a new persistent tuning API. If prediction fails against the fixed
   device-class goals, discard the candidate rather than permanently
   adding policy complexity or telemetry.

Candidate objective: improve normalized *useful page-out service*, preserve
p99 swap-in/out, reduce independently observed lower WRITE **bytes and
requests** and attributed CPU per useful page. A faster result with more
lower writes is not a universal improvement. Require ABBA same-content
controls and the project's existing source-bound acceptance screens.

### Phase 2 — optional background second-chance RAW recompression

**Not the first experiment.** Rewriting already-committed RAW cannot undo
its original 4 KiB WRITE. For a typical 4 KiB RAW page compressing later to
2 KiB, the additional operation incurs roughly **4 KiB lower READ plus
at least one allocated lower WRITE block/extent**, plus CRC, packing and
possible GC. It buys future occupancy/possible future reads, **not fewer
lifetime writes so far**. On nearly empty large backing swap, this is
usually worse for wear and device traffic than leaving the RAW page alone.
Zram's RAM-resident recompression is not an equivalent proof for disk swap.

Only consider this if full-media capacity pressure or future READ savings is
a separately demonstrated dominant workload. Any design requires:

- a **bounded, reclaim-safe** opportunistic worker, never triggered by a
  swap-in critical path and never allowed to steal memory or I/O needed by
  foreground reclaim;
- an immutable `(logical page, generation, original RAW location)` witness,
  a freshly validated lower READ and authority CRC; no direct pointer to an
  unpinned, possibly freed staging page;
- independent disjoint destination reservation and complete lower WRITE
  success/required FUA before a conditional generation/identity recheck
  and atomic authority publication; never overwrite the original RAW
  location in-place;
- legal cancellation on overwrite, DISCARD, swap-in and stale generation,
  with exactly once reservation/reference release and no data publication
  on a failed or uncertain I/O;
- flush/suspend/drain, GC reclaim, segment tail, shortage/ENOMEM, failure
  injection and module teardown guarantees that preserve the old mapping
  until commit. No physical backing header alteration or module unload
  during live swap.

Measured promotion must subtract **all** extra lower reads/writes, request
count, GC relocation, capacity released and added CPU, and cover hot swap
thrash. Disable rather than retry aggressively on CPU/IO/PSI pressure.

## Separate upstream optimization: zswap-origin recompression

The existing `docs/ROADMAP.md` contains a **separate, deferred** plan to
avoid compressing genuine `ZSWAP_STORED_WRITEBACK` pages twice. It requires
an explicit reviewed kernel-to-BIO origin signal; ordinary rejected pages
must never be treated as proven incompressible. Do not invent a kernel flag,
infer origin from a mapper name or silently bypass compression for all BIOs.
This could be a more profitable CPU optimization than post-write recompressing
an already compressed origin, **if** measured backing traffic is zswap-driven.

## Qualification and decision boundary

No change to the product, six public Make goals, source format, loaded
mapper or private development-trial lifecycle is authorized by this proposal.
First use exact-source rootless C policy tests for positive/negative paths,
then clean W=1/W=2 x86_64/ARM64 kernel builds, loaded `null_blk`
byte-exact readback, overwritten/duplicate-slot/flush/FUA/GC/DISCARD,
fault/ENOMEM, suspend, producer cancellation and concurrent shutdown.
Physical live-swap qualification is a separate **owner-gated** decision.

**Stop condition:** no demonstrated avoidable RAW; no savings in lower
requests/bytes; regressions in useful service, tail latency, memory reclaim,
CPU pressure or correctness. The right engineering outcome can be to keep
RAW rather than implement background recompression.

### Safe read-only measurement request

On an **already active** mapper, a named `dmsetup status` observation is
read-only. Use only the exact previously observed target name and extract
the diagnostics above; collect two timestamped samples without running
swapoff, module unload, `dmsetup remove`, mkswap or a device stress test.
Do not paste raw DM status or host-specific journal credentials. No
current-host physical operations are implied.
