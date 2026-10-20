# Coding Standards

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ3` is reserved for the on-disk format identity.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands. Private scripts and CI jobs are implementation details, not operator interfaces.

## Priority

More than half of ongoing development engineering time should concern production Linux kernel C: debugging, profiling, algorithms, I/O ownership, mapping authority, GC and measured performance. Do not invent tests or infrastructure when a direct C fix is the work that matters. Python and shell are thin qualification glue.

## Source and naming

Active product C/C++ and headers live under `src/`; test-only code lives under `tests/`; maintained Markdown lives under `docs/`; packaging code lives under `packaging/`. Do not recreate parallel `kernel/`, `userspace/`, `tools/`, legacy source trees, alternate research modules or historical models.

Use `swapz_` / `SWAPZ_` for implementation identifiers and `swapz` for the product/candidate. The Device Mapper target is exactly `swapz`; the module alias is `dm-swapz`. SWZ3 may appear only when discussing the disk format.

## Kernel C rules

Use Linux-kernel-style C, kernel types/APIs, explicit ownership and checked arithmetic. Keep functions cohesive, allocations bounded, stack use modest and concurrency ownership obvious. Avoid recursion, hidden allocations, libc/C++ in the module and duplicated state machines.

Every accepted BIO must have exactly one completion owner. Never publish a mapping before all required lower data and ordering work succeeds. Preserve generation/CRC checks, PREFLUSH/FUA ordering, same-page dependencies, discard semantics, suspend/drain safety and fail-closed teardown.

Allocation and GC must never reuse a possibly live or partially written extent. GC may relocate only current authoritative records and must account for its lower READ/WRITE cost.

## Performance work

State a concrete production-C hypothesis before changing policy. Measure useful logical work and independent lower bytes/requests. Request reduction that loses useful throughput can still be useful diagnostic evidence, but is not a win by itself. Read p95/p99, CPU, RAM and GC are part of the result.

Remove diagnostic branches and counters after they answer their question. A rejected experiment must not keep consuming hot-path CPU or schema surface.

A benchmark labeled sustained QD must pre-create its worker set before the
timed interval and must not use per-I/O `Future` submission, main-thread
completion handoff or a full-QD barrier between successive writes. Write-only
saturation traces must give each persistent lane disjoint logical-page
ownership while preserving that lane's operation order, so unconstrained
cross-lane completion cannot change the final image. A QD-wave driver may be
kept only when explicitly labeled as burst/wave evidence.

## Dead-code rule

Keep the working tree centered on code that ships or directly qualifies the current product. Historical reproduction belongs in immutable Git history. Delete alternate implementations, obsolete compatibility harnesses, unused models, stale workflow gates and historical test-only backends once no active product invariant depends on them.

Before deleting production code, identify all current callers and preserve necessary behavior in direct production-C tests. Never restore dead product code merely to satisfy an orphaned test; delete or rewrite the stale test when its subject no longer exists.

## Change discipline

Work directly on `main` unless the owner explicitly authorizes another branch. Check the current remote head before every write and use lease-protected fast-forward updates. Keep commits small enough to review. Do not force-push or overwrite concurrent work.

Every implementation task updates the relevant governing standard in the same commit. README/VISION change only when user-facing structure or acceptance criteria change.

## Host safety

Never reboot, `swapon`, `swapoff`, mount test storage, force-remove mappings or touch physical/unowned devices. Loaded development uses only positively owned RAM-backed `null_blk` with exact identity checks and ordinary teardown/quarantine.


### Deferred content-sharing and concurrency experiments

Same-filled-page and dedup optimizations must preserve the existing authority
model rather than create hidden aliases. A nonzero same-filled representation
needs an explicit type/format decision and exact 4KiB reconstruction; do not
reuse the zero-page encoding for nonzero values. Exact-content dedup requires
bounded ownership/refcount state, full-byte verification before sharing,
generation-safe copy-on-write on overwrite, and GC/DISCARD accounting that
cannot free a payload while any authoritative mapping references it. Hash
equality alone is never sufficient authority.

READ coalescing may combine only requests already waiting behind serialized
service. It must not delay an otherwise dispatchable read, cross an ordering or
authority mutation boundary, merge incompatible generations, or share mutable
decode scratch across concurrent completions.

A future background-GC worker remains subordinate to the single publication and
allocation authority. It may not consume the last reserve, race foreground
allocation for a destination, publish relocation before lower completion, or
continue after suspend/drain/failure has revoked ownership.

K>1 lower-WRITE slots require immutable per-run ownership exactly as K=1 does.
Adding a slot without measured ready-run pressure is forbidden. Same-page writes
across runs require an explicit generation/order fence; publication remains
serialized even if lower I/O is parallel.

Physical-device support is not a coding shortcut around current safety policy.
No production/test flag may silently relax the RAM-backed owned-device gate.

### Admission-policy cleanup

The old `coalesce_ms` constructor option is retired. Supported mappings had
used value zero, and retained writes bypassed it, so nonzero delayed admission
was a dormant experiment rather than current policy. With retention disabled,
ordinary writes preserve the former zero-delay behavior by queuing one
immediate worker instance; dependencies and retained writes wake the worker
immediately. Do not reintroduce an independent admission delay without new
production evidence and ordering qualification.


### Bulk scratch initialization

The grouped lower-write path must not clear the full 256KiB scratch buffer on
every run. Compressed extents initialize their exact extent image and RAW
entries overwrite their complete 4KiB block. Only alignment holes that are
actually submitted by explicit padding mode are zero-filled, and only for the
exact gap bytes. This keeps the no-padding path free of unrelated memory
bandwidth while preserving deterministic lower-media contents.


Repository naming guards must not contain their own banned implementation names
as literal searchable text. Express self-check patterns without embedding the
forbidden token verbatim so the guard audits the tree rather than matching
itself.


The public engine surface contains only paths used by the current Device Mapper
target. Native tests must not keep convenience wrappers alive; they can select
the production batched writer's sequential fallback or bounded planner
explicitly when qualifying those behaviors.


The authority header exports only implemented, production-used operations.
The current compressed read path is metadata peek plus
`swapz_read_authoritative_peeked()`; the older reparsing read wrapper and
unimplemented range-discard declaration are not retained for test convenience.


Codec interfaces likewise remain product-facing. Tests may derive expected
read-span geometry locally from decoded offsets, but that arithmetic is not a
reason to export an otherwise unused codec helper.


### Alignment-aware planner ties

The extent planner minimizes lower bytes first, bounded cold-read cost second,
and extent count third. If those objectives are exactly tied, prefer the larger
power-of-two extent class first. This does not add a lower byte or relax read
policy; it moves unavoidable allocator alignment before a run instead of
between extents, allowing adjacent-only lower aggregation to issue fewer WRITE
requests. Never trade extra padding bytes for this tie-break in the default
mode.


Alignment-aware tie-breaking is restricted to the adjacent lower-run writer.
The public/sequential planner retains its previously qualified deterministic
tie order, including verify-after-write and other non-bulk paths. A lower-run
optimization must not perturb layouts in modes that cannot consume the
resulting contiguity.

### Retained accepted-burst tails

A retained pack may remain open only for finite BIOs that are already accepted.
At the tail of the worker-local queue, already-accepted work includes BIOs
observed in `incoming` while holding `queue_lock`. The worker may append that
accepted tail to its private local FIFO and continue in the same invocation,
but only while the existing 64-BIO quantum has capacity. It must never sleep,
spin or schedule a grace period waiting for a future arrival, and future
arrivals never refresh the pinned retention budget.

Because asynchronous preparation and synchronous copy/LZ4 work occur after an
initial queue observation, pack-ready policy must refresh `incoming` after
that work before deciding that the current pack is isolated. FIFO order,
dependency fences and the one-completion-owner rule are unchanged.

This is distinct from the rejected zero-delay first-pack recheck: that policy
waited for a future scheduling turn and could lower byte efficiency. Draining
BIOs that were already accepted adds no future-arrival wait and lets the
existing no-padding batched writer combine their independent extents in one
lower run when physical geometry permits.

### Learned retained-singleton bypass

Initial singleton retention remains intact. After two consecutive one-page
deadlines reached with the worker and admission queue empty, the target may
fast-close later isolated singleton windows because the full retention
opportunity has twice produced no aggregation benefit. Any already-accepted
companion or any multi-record window immediately clears this learned bypass.

The bypass changes neither one-record lower-byte geometry nor completion
ownership. PREFLUSH/FUA, dependency, publication, suspend/drain and fail-closed
ordering remain unchanged.


### Already-accepted burst deadline handling

Retention bounds time available to collect companion writes, not time the sole
ordered worker is synchronously servicing an unrelated committed read. A
`deadline_before_bio` or `deadline_after_read` close must not split a window
while the current worker snapshot still has accepted follow-up BIOs. On a
successful independent-read bypass, advance `window_first_ns` by exactly that
read's synchronous service interval before re-evaluating expiry. An older
hrtimer may wake early and is harmless because the worker rechecks the shifted
origin before closing or rearming.

Future arrivals never refresh this budget. Dependencies, PREFLUSH/FUA,
same-page conflicts, suspend/drain and fail-closed behavior retain their
existing ordering gates.


### Cursor-aware adjacent-run reconstruction

The adjacent-only bulk writer may use the authority's current physical cursor
only to choose among planner alternatives already tied on lower bytes, bounded
cold-read cost and extent count. Keep logical page order, transaction staging
order and publication order identical; do not physically reorder later planner
groups ahead of an earlier group because a later lower/publication failure must
still describe a true committed logical prefix. Among equivalent candidates,
prefer zero alignment-hole placement first and the larger class only when hole
cost is equal. Default mode still writes no padding bytes.

### Metadata block LRU bound

The compressed-read metadata LRU contains 512 fixed 4KiB block-zero slots,
allocated once per target (2MiB payload storage plus bounded side arrays).
Indices that scan or select cache slots must be at least 16 bits. The cache
holds validated metadata only, never payload authority, and every existing
write/GC/discard/barrier mutation fence continues to invalidate residency
before authority changes.


### Exact zero-page scan

The zero-elision predicate may scan one complete 4KiB page in fixed 64-bit
chunks, but it must remain byte-exact and safe for unaligned portable callers.
Load each chunk through `memcpy` rather than casting a byte buffer to a wider
pointer; do not overread the page, allocate memory, or weaken the rule that any
single nonzero byte makes the page nonzero. This optimization changes CPU work
only and never changes lower-I/O or mapping authority semantics.


### Exact scratch initialization

Extent construction must not clear the full 4/8/16KiB scratch image when every
authoritative header, descriptor and payload byte will be overwritten. The
codec clears only the final unused gap at seal time before lower submission, so
no stale scratch byte can reach media. The selective read path likewise does
not zero blocks it never inspects: block-zero metadata and every requested
payload block are explicitly populated before validation. Full verify reads
overwrite the complete compared extent. Native production-C tests poison
scratch buffers so correctness cannot depend on incidental zero initialization.


### Adaptive retained-burst width

A momentarily empty `incoming` list is not sufficient evidence that a retained
closed-loop write burst ended. The worker starts with a four-record close target
and marks useful pack geometry without immediately closing it. A later BIO still
wakes the worker immediately through normal admission; no microsecond grace
timer, scheduler handoff, spin or sleep is added.

After a successful pack-ready lower write, the worker scans at most
`max_window` FIFO entries already present in `incoming` under `queue_lock`.
Only a contiguous prefix of ordinary writes counts. That finite admitted tail
raises the learned target and supplies a one-shot residual target. Future
arrivals are never predicted or waited for. A smaller multi-record stream may
shrink the learned target after one original absolute deadline. Singleton QD1
adaptation remains separate. The retired one/two-record packed-burst tail
shortcut must not coexist with this policy.


The retained-burst pure policy helpers must avoid identifiers such as `current`
that are macro names in Linux kernel headers. Pack-target closure in
`swapz_accept_write()` uses the existing admission snapshot; absolute expiry
remains enforced by the established process/worker deadline gates rather than
introducing a second pre-definition expiry path.


Kernel-header macro hygiene applies to every reference after a parameter rename;
native and Kbuild warning builds must both compile the exact helper body.


### Dry accepted-pack closure

A learned retained-burst width is a coalescing hint, not permission to idle on
an already useful packed window after all finite accepted work is exhausted.
When the worker has formed a complete second pack and has refreshed both its
private local FIFO and `incoming` to prove there is no accepted successor, it
closes immediately through the normal pack-ready commit path. It must not spend
the remaining absolute retention budget merely hoping a future BIO will satisfy
a larger historical target.

Admitted-tail learning scans the older worker-local FIFO before `incoming` and
counts only one contiguous prefix of ordinary writes, capped by `max_window`.
A fence or non-ordinary BIO ends that evidence. Downward learning from one
deadline must not cross below the original four-record target: a transient
two/three-record gap must not recreate the first-pack chopping that retention
was introduced to avoid. An active packed chain is not evidence for shrinking.

This policy changes neither lower-byte planning nor publication order. The
accepted-burst read cap remains two, future arrivals never refresh the pinned
deadline, and PREFLUSH/FUA, dependency, suspend/drain and fail-closed ownership
are unchanged.


### Service-proven dry retained closure

A useful packed window must not bypass a larger learned burst target from inside
write admission merely because `incoming` is momentarily empty. Admission may
close at the effective learned or sampled-tail target only. The ordered worker
may close below that target only after it has refreshed its private FIFO and
`incoming` and the current retained chain/window has concrete synchronous
service evidence: either an earlier packed commit in the same admitted chain or
a successful independent read serviced while the write window was open.

A sampled admitted tail is stronger evidence than dry closure and must be
drained to its finite target without an accepted-pack shortcut. The worker-tail
shortcut applies to either a first useful pack or a complete second pack after
service evidence; it adds no sleep, spin, grace interval or future-arrival wait.
PREFLUSH/FUA, dependency, publication, completion and fail-closed gates remain
unchanged.


### Ordered-worker preparation steal

Asynchronous preparation remains a bounded producer/consumer optimization, not
a publication owner. The ordered worker may remove its next FIFO BIO from
`preparation_incoming` only while holding the shared admission lock and only
if the producer has not already claimed that preparation entry. A claimed entry
retains the original completion handoff; an unclaimed stolen entry is compressed
inline by the ordered worker and is never waited on or producer-completed.

Once stealing is possible, producer and ordered compression may overlap.
Therefore they must have distinct input scratch and distinct LZ4 work memory.
Producer and ordered timing accumulation must also remain single-writer and may
be summed only for reporting. Prepared-page mempool/semaphore ownership applies
only to producer-prepared entries; inline entries allocate no prepared page and
must not release a slot they never acquired.


### Circular GC destination probe

Rotating GC destination selection must preserve the authority's circular
`next_segment_probe`; collection must not reset the probe to segment zero.
The dead-segment picker remains responsible for scanning from that cursor,
skipping the open foreground segment, victim, foreground roles and any second
reserve after one destination has been selected. Successful role handoff may
advance the cursor according to the existing committed rotation rule, and any
failed collection must restore the caller-saved foreground cursor and probe.

This is a wear-distribution rule, not permission to reuse uncertain media.
A destination still must be entirely non-authoritative and dead, GC still uses
exactly one reserve per cycle, and a victim becomes reserve only after every
mapping/refcount validation and successful lower relocation has completed.


### Retained target closure and serviced-burst evidence

Write admission may close PACK_READY only at the refreshed effective
learned/admitted target and only when no already-accepted follower is visible.
Below-target closure remains a serialized worker-tail decision after
`local` and `incoming` have been refreshed. This keeps the target gate fast
without treating a transient sub-target submission gap as proof that a burst
ended.

A one-shot `retained_tail_target` is sampled only after a real PACK_READY
lower write. Pre-write sampling is forbidden because it observes userspace
thread-submission skew before a lower-I/O service interval and can pin a QD8 or
QD32 wave to a transient short prefix.

An empty `swapz_flush_window()` call is not a committed window and must not
erase retained-chain/tail evidence for ordinary READ/zero processing. Real
ordering barriers still terminate that scheduling evidence. Successful
retained READ/fence service may carry across intermediate retained work, but a
PACK_READY close at a refreshed dry tail consumes that finite evidence so it
cannot fragment later windows into repeated singleton PACK_READY closes.
DUPLICATE/FULL closes are not dry-tail evidence consumers because the current
WRITE itself continues after flushing the older batch.

A serviced useful pack may close on a refreshed dry worker tail. A sub-pack
1..3-record residue may do so only after successful retained READ service or a
forced zero/duplicate/raw/read interruption in the same accepted burst. This
exception must not make a prior PACK_READY write alone sufficient to cascade
write-only QD8/QD32 into singleton closes. Publication, FUA/PREFLUSH,
dependency, discard, shutdown, completion and fail-closed ownership are
unchanged.

### Sampled-single-tail PACK_READY deferral

A post-PACK admitted-tail sample of exactly one WRITE is timing evidence, not
packed geometry. It may grow `retained_burst_target`, but it must not set a
one-shot `retained_tail_target == 1` or authorize an early one-record
PACK_READY close. The ordered owner records this state with
`retained_single_tail_deferred`.

ID53 is rejected. A deferred singleton uses the same ordinary absolute
first-record deadline as every other retained window. There is no shorter
singleton deadline, deadline watermark, second timer, sleep, spin or
future-arrival wait. While the deferral is active and `batch_count == 1`, both
admission target closure and worker service-proven closure return false. A
second admitted record resolves the companion; a real nonempty flush, hard
boundary or true empty burst boundary clears the state through the existing
lifecycle accounting.

### Deferred-singleton lifecycle attribution

ID50 policy changes are frozen while ID51 is active. Each transition into
`retained_single_tail_deferred` increments exactly one deferral. That state must
terminate exactly once as a companion WRITE, a one-page DEADLINE close, a
one-page IDLE close, or an explicit other clear. A later tail sample that
supersedes an unresolved singleton counts the previous lifecycle as other before
starting a new one. Empty hard boundaries and true empty burst boundaries must
also account before clearing state.

At drained/quiescent measurement boundaries the cumulative and timed-delta
conservation law is exact:
`deferrals == companions + deadline + idle + other`. The deadline and idle
subsets must not exceed their corresponding one-page close counters. Do not use
these counters to change policy in the same source revision that introduces the
measurement.

### Deferred-singleton timing/service diagnostics

ID52 must remain observational. Starting a sampled singleton records one
monotonic timestamp and clears two per-lifecycle service flags. Ordered
completion of an existing async lower-W run may set the lower-done flag;
successful independent retained READ service may set the read-bypass flag.
Neither event may close, extend or otherwise alter the retained window.

Only companion and one-page deadline terminal outcomes receive the original
<=250 us, 251-500 us, 501-1000 us and >1000 us histograms. The four companion
bins must sum exactly to `single_tail_companions`; the four deadline bins must
sum exactly to `win1_deadline_deferred_tail`. After ID53 rejection, companion
observations in the aggregate >1000 us bin are also partitioned passively into
1001-1250, 1251-1500, 1501-1750 and >1750 us; those four sub-bins must sum
exactly to the aggregate >1000 us companion bin. None changes retention policy.
Lower-done/read-bypass counters remain overlapping subsets; the both counter is
a subset of each. Other and idle terminal outcomes reset observation state
without being reclassified.

### PACK_READY primary-cause attribution

Every real `SWAPZ_CLOSE_PACK_READY` window has exactly one diagnostic primary
cause captured immediately before the close: a nonzero
`retained_tail_target`, the learned `retained_burst_target`, or
service-proven dry closure below target. The cumulative primary counters must
sum exactly to `close_pack_ready` at quiescent measurement boundaries.
`pack_close_tail_target_le4` is a subset of the tail-target counter and records
only closes whose actual window count is <=4. This attribution is passive: it
must not alter any readiness predicate, target, timer, ownership or completion.

ID55 further partitions only `SWAPZ_PACK_CLOSE_BURST_TARGET`. Snapshot the
learned target and decision site immediately when the close is authorized, then
at the real flush count exactly one admission/worker site, one learned-target
bin (<=4/5-8/9-16/17-64), one actual-count bin using the same ranges, and whether
count overshot target. Site totals, target bins and count bins must each
conserve exactly to `pack_close_burst_target`. This is diagnostic state only;
it must not alter `swapz_window_burst_close_ready()` or learned-target updates.

ID56 is measurement only. Every first post-PACK_READY tail observation
increments exactly one tail-size/state bucket: tail 0, 1 or 2+, crossed with
detached `inflight_write.active` versus idle. These six buckets conserve to
`pack_tail_samples`. Count a burst-target grow/shrink only when the existing
helper actually changes the target.

ID57 is rejected and reverted. Owner evidence showed that preserving a zero-tail
sample and prior completed-chain width across K=1 completion can contaminate the
next closed-loop wave, inflate the learned target beyond the active QD and arm
service-proven dry closure from stale service evidence. Post-PACK tail sampling
returns to the ID56 observational rule: every sample is consumed in its current
admitted-wave context. PACK_READY is never suppressed merely because K=1 lower
I/O is unfinished. Do not restore ID57 counters or policy without a new isolated
hypothesis.

### Whole-dead-segment lower DISCARD

ID29 is an advisory media-reclamation optimization, never an authority
transition. The authority may call one production hook only after a previously
written 1MiB segment is proven wholly dead and immediately before foreground/GC
reuse. A committed GC victim may be trimmed only after role rotation succeeds
and it has become a dead reserve. Exact segment mapping counts and all 256
physical live-record counts must be zero first.

The Device Mapper hook runs on the serialized owner, rejects internal ownership
inconsistency before reuse, and never trims the currently named foreground OPEN
segment. It issues one segment-aligned lower DISCARD only when the backing queue
advertises support. EOPNOTSUPP and real lower DISCARD errors are diagnostic and
nonfatal because TRIM cannot create logical deadness; failed TRIM must not
publish, free, or make any otherwise-live storage reusable.

### Passive K=1 ready-wait evidence

ID38 telemetry may observe a nonempty window entering the existing
swapz_flush_window ownership boundary while the sole immutable lower run is
active and its completion is not done. It records windows, records, max window,
exact wall spent in wait_for_completion and the existing close reason.
These counters must not wake workers, close windows, change timers, add a slot
or participate in policy.

### Bounded adjacent distinct-extent READ coalescing

ID63 may operate only on the already-admitted independent READ prefix. It never
waits for another BIO and never crosses a write, barrier or dependent read.
Eligibility must first inspect the ordered owner's direct/LRU residency metadata
without copying cached blocks into private slot scratch. Private slots are
primed only after the exact missing ranges prove one zero-padding coalesced
lower request.

Eligibility is based on the exact lower blocks still missing for every grouped
BIO, not merely full-extent adjacency. Each private extent's missing mask must
collapse to one contiguous range; both ranges must be nonempty, immediately
adjacent, remain inside one 1MiB segment and total at most 8 blocks / 32KiB.
Padding or gap reads are forbidden.

One synchronous lower READ may fetch the combined span into preallocated
scratch. Those bytes are seeded only into private slot residency and are marked
unvalidated. Normal swapz_engine_read_page validation must still verify SWZ3
metadata, logical identity, generation, sequence and payload CRC for every
constituent record before that seed becomes ordinary cache residency. A lower
I/O, metadata, generation, CRC, decode or upper-copy failure prevents shared
cache absorption and fails closed under the existing batch contract.

Actual merged pairs, requests saved, blocks fetched and extra blocks are
separate monotonic counters. Requests saved equals merged pairs for this
two-range design and extra blocks must stay zero.

Passive rejection attribution is allowed only when ID63 is enabled and the two
full extents are already physically adjacent under the same segment/size
bounds. A non-merge is classified once as cache-satisfied, noncontiguous
per-slot missing mask, adjacent-full-extents whose exact missing subranges have
a gap, or a defensive other/invariant bucket. These counters never change
eligibility, cache state, dispatch or completion. Qualification requires the
defensive other bucket to remain zero; do not force conservation against the
older passive-adjacent counter on hwq=1 because depth-one fallback can suppress
that legacy pair counter after the candidate was already observed.

### Worker scheduler-accounted CPU attribution

Keep callback wall residency and worker CPU attribution separate. At
ordered/preparation worker boundaries, sample
`READ_ONCE(current->se.sum_exec_runtime)` and accumulate nonnegative deltas in
dedicated counters. The retired ID39 helper has no worker boundary;
`read_worker_cpu_ns` is retained only as a zero-valued status compatibility
field. These samples exclude lower-I/O sleep and runqueue wall delay, but a direct
entry/exit sample can materially miss a short non-sleeping callback when the
scheduler has not updated the current entity between samples. Therefore the
counters are lower-bound diagnostics, not total or cycle-exact CPU time. Expose
separate ordered/preparation LZ4 and copy timers; reports may sum
LZ4+CRC+copy for the producer and LZ4+CRC+copy+commit-non-I/O for the ordered
path as measured non-sleeping phase floors. Floors are not total CPU either.
Do not call an unexported scheduler helper merely to sharpen this measurement.

### Synchronous READ grouping and ID63 control

The read-only `parallel_reads` and `read_coalesce` module parameters remain
evidence controls, not runtime auto-tuning policy. `parallel_reads=1` enables
the bounded grouping machinery; `read_coalesce=1` additionally permits exact
ID63 adjacent missing-range coalescing. They do not enable helper concurrency.

The rejected ID39 `swapz-read` workqueue, per-slot work/completion objects,
queue/wait/flush dispatch and helper CPU accounting are not part of current
production code. `parallel_reads_enabled` remains in status for schema
compatibility and must be zero; `read_worker_cpu_ns` must likewise remain
zero.

`swapz_try_parallel_read_batch()` is ID63-only. After the first immutable-read
prefix scan, it must reject before slot preparation, a second FIFO walk,
cache-LRU scans or cached-block memcpy unless read coalescing is enabled and the
first two distinct extents are physically adjacent in the same segment. Any cached/noncontiguous/gapped missing range must return before private-slot
priming and
BIO ownership transfers. Standalone same-extent slot grouping is retired;
ordinary `swapz_read()` already reuses the shared extent/metadata caches.
For a successful ID63 pair, lower-I/O/decode telemetry is committed before upper
BIO completion, but shared LRU cache absorption must occur only after every
successful upper BIO has been completed so cache memcpy is off the completion
critical path.

Fast and serial ID63 qualification keeps `parallel_reads=1` and varies only
`read_coalesce` for five matched rounds. The off arm is the ordinary FIFO read
path and must execute zero grouped/coalesced slot pairs. Dedicated ID39/ID60
loaded controls are removed after owner qualification/refutation; do not retain
dead benchmark sessions merely for historical telemetry.

### Offline predictor qualification before any format change

A reversible pre-LZ4 predictor is not production code until native/offline
evidence shows material physical benefit. Current evidence promotes whole-page
delta64 as the routing candidate; CL-Delta32x2 and 512-byte-reset delta64 remain
comparators, while cacheline byte-delta and whole-page delta32 are baseline
controls rather than active promotion candidates. Loads/stores must be
`memcpy`-safe and arithmetic explicitly unsigned.

The current SHAKE-generated benchmark hard regions are negative controls, not a
positive predictor corpus. Native evidence must also construct deterministic
pointer/page-table, integer counter/timestamp, float/double, fixed-layout
struct and independently based subpage archetypes. Routing evidence must be
separate from the full transform: sample the raw page first, never count a zero
delta as positive evidence, and report false calls by negative profile.
The sampled hot loop must cache each loaded 64-bit word and derive any 32-bit
lane evidence from those cached values rather than rereading the same bytes.
ID67a.3 uses an 8-pair page-wide first stage; fewer than two points is an
immediate reject. Passing pages extend to 32 evenly strided pairs. The fixed
three second-stage positions in each 512-byte region should be expressed
directly rather than paying a nested offset-loop branch in this intentionally
tiny classifier. Classifier timing must be batched across repeated eligible-page
sweeps so two timer calls cover many classifier invocations rather than
contaminating every page.
Thresholds are evidence, never kernel policy before measurement.

Every candidate must round-trip exactly. Measure transform, inverse and optional
second-LZ4 cost. Feed actual compressed-length sequences into the production
`swapz_engine_plan_bounded()` and report planned 4KiB blocks/extents, RAW
rescues and packing-cliff crossings. For every router threshold, also feed the
classifier-routed delta64 lengths through the same planner and report routed
blocks/extents saved; ungated transform opportunity alone is not routing
evidence. ID67a may place the portable, allocation-free
candidate helpers in `src/kernel/predictor.h` so native tests exercise the
exact C that a later kernel experiment could reuse, but no production
translation unit may include that header yet. Do not modify SWZ3 metadata,
authority, Device Mapper hot paths or retained-window policy as part of this
offline phase.

### One-shot in-flight-zero burst-target shrink guard

The passive ID56/ID64 attribution established a narrow timing defect: a
post-PACK sample may observe `tail == 0` while the detached K=1 lower write is
still active, clear retained-chain evidence, and leave the following residual
deadline window looking like a new smaller burst.

The read-only `guard_inflight_zero_shrink` module parameter is an owned-RAM
regression control and remains enabled by default after owner qualification.
The historical five-pair A/B is promotion evidence; current qualification keeps
only one directional off/on observation. It may affect
only the deadline learned-target shrink site. It must not suppress PACK_READY,
defer/re-sample tails, delay upper BIO completion, alter timer expiry, create
new waits, or change lower-run ownership/publication.

When the ordinary shrink helper produces a different candidate target and both
the guard and `last_pack_tail_zero_inflight` are true, keep the current target,
increment `burst_shrink_inflight_zero_skips`, and clear the flag immediately.
This consumes exactly one exemption. Otherwise apply the unchanged shrink
helper and retain the existing mutually-exclusive actual-shrink attribution.

A remembered in-flight-zero observation must never leak across unrelated
windows. Any later nonzero tail sample clears it. A nonempty hard boundary that
does not continue the retained chain also clears any unconsumed observation.
Therefore a first residual deadline window may be exempted, but a second
consecutive deadline window can down-adapt normally if no new in-flight-zero
sample occurred.

Actual shrinks continue to conserve across after-inflight-zero,
after-read-bypass/other and <=8/9..32/>32 target bins. Guarded skips are
separate from `burst_target_shrinks`; they are suppressed candidates, not
actual target updates.

### Zero-allocation DISCARD range prevalidation

Multi-page DISCARD must validate the complete logical range before committing
any mapping/generation invalidation. Shared physical extents require aggregate
liveness accounting: the serialized ordered worker may temporarily decrement
one `live_records[start]` reference per validated page, but it must restore the
exact validated prefix on both success and failure before entering the commit
loop.

Do not allocate per-physical-block epoch/count scratch for this check. The
temporary accounting pass performs no lower I/O and no mapping/generation
mutation; malformed start/class/liveness or generation overflow fails closed.
The subsequent `swapz_discard_page()` loop remains the sole commit path.

### Foreground GC pressure and scaling telemetry

ID61 evidence must observe the existing serialized collector without changing
victim policy, allocation authority, publication order or introducing a GC
worker. Time the complete `swapz_gc_compact_one()` attempt exactly once,
including RAW callers and failed/no-headroom attempts, and time victim choice
inside that total. Do not double-account GC wall at individual call sites.

For scaling evidence, count exact loop work rather than infer it from device
size: logical-map entries scanned while building victim scores, segment entries
examined during victim selection, and logical-map entries scanned during victim
relocation. Preserve the existing no-headroom skip counter alongside them so
reserve pressure is visible. These counters are diagnostics only and must never
influence selection. Existing `segment_mapped_pages` remains the authoritative O(1)
post-evacuation deadness check.

The private owned-RAM GC oracle may measure each successful foreground WRITE
with `CLOCK_MONOTONIC`, report one p99 per pressure round and retain exact final
image verification. Kernel GC wall and userspace WRITE wall are separate
clocks/contexts; their ratio is attribution evidence, not a CPU utilization
metric. A future background worker or reverse index requires a separate change
after this evidence demonstrates a material latency/scaling problem.

### Opposite-end asynchronous preparation

The ordered worker owns FIFO execution and may atomically reserve an unclaimed
preparation entry from the head. The asynchronous producer is pure preparation:
it never publishes mappings, submits lower I/O, changes ordering, or completes
upper BIOs.

When synchronous lower WRITE I/O is active, the producer prepares from the
head because the ordered worker is blocked and will need that entry first.
Outside lower WRITE wait, tail preparation is credit-limited: each ordered
inline WRITE may leave at most one unconsumed tail token. The token is earned
only after the ordered worker atomically reserves its own FIFO head.

For a retained window, an earned `preparation_tail_credit` may survive the end
of that individual `swapz_process()` call. This bridges the admission gap
between companion BIOs without exposing worker-owned `batch_count` to
`->map`. Outside lower WRITE wait, the producer must not consume a token when
`preparation_incoming` is singular: on a one-entry list the nominal tail is
also the FIFO head, so claiming it forces an avoidable ordered completion wait.
The sole head and its token remain intact until a true tail exists behind it.
The producer itself is the tail-eligibility authority. Do not suppress a
credit-driven wake merely because the protected list is singular at the wake
site: owner qualification showed that this timing optimization reduced useful
throughput and worsened retained-window request/deadline geometry even though
the producer still rejected the lone head safely. A queued work item may overlap
a companion admission before it runs, and workqueue coalescing is part of the
measured schedule. If ordered inline work earns a fresh token while the producer
is already running, the producer may continue for that new token; it must stop
when no eligible credited tail remains. A nonempty window close clears any
unused token.

A cold lone head has no token and therefore does not wake the producer.
`->map` may wake parallel preparation only for active lower WRITE service or
an already-earned atomic tail credit. It must not pre-screen that credit using
instantaneous preparation-list topology, read worker-private `batch_count`, or
depend on the instantaneous `ordered_worker_busy` interval. The producer
rechecks list shape under the same `queue_lock` before consuming the token.
READ/barrier execution may still grant one bounded token while it owns ordered
service time.

The ordered Device Mapper worker and LZ4 preparation worker both use
serialized `WQ_MEM_RECLAIM | WQ_UNBOUND` workqueues. The CPU-local preparation
experiment increased measured lower-I/O/LZ4 overlap but regressed useful mixed
throughput, lower-WRITE request geometry and worker-empty deadlines, so bound
placement is rejected and must not remain as production state. The single
preparation `work_struct` remains non-reentrant system-wide; scheduling
placement never changes FIFO, publication, completion or lower-I/O ownership.

Performance attribution belongs in kernel C at phase boundaries. Explicit RAM
copies are timed and byte-counted separately from LZ4. Engine write/read
processing also records wall time with synchronous lower-I/O wait subtracted.
Do not infer copy/CRC/packing cost from userspace elapsed time, and do not add
overlapping wall counters together.

For a complete single-bvec 4KiB WRITE, the still-owned BIO page may be mapped
with `kmap_local_page()` and used directly as the synchronous LZ4/zero-scan
input. The mapping must be released before the BIO can be completed or ownership
can change. Multi-bvec BIOs retain the copy fallback. An incompressible page in
retained bulk mode must be copied directly from the temporary mapping into its
durable `batch_bytes` slot exactly once before unmapping; do not bounce it
through `input_page`. In non-bulk RAW mode, BIO ownership survives the older
window flush, so release the temporary mapping and let `swapz_raw_write()`
perform its existing one copy afterwards. Direct mapping changes neither
publication nor lower-I/O semantics.

Engine write attribution separates planner, pack and publish phases. Pack
includes SWZ3 begin/append/seal work, including payload memcpy and first CRC.
Publish includes batch resume plus authoritative finish/revalidation after lower
completion. These diagnostics must not be used to skip CRC, generation or
transaction-snapshot validation without a separately qualified replacement.

The producer reserves bounded prepared-page capacity nonblocking before taking
`queue_lock` or claiming a BIO. Tail claiming never consumes
completion/publication ownership: the FIFO worker can continue inline-stealing
unclaimed heads and releases prepared slots as it reaches completed tail
entries. Separate LZ4 scratch/work memory remains mandatory for concurrent
compression.

### Idempotent metadata-cache invalidation

`read_metadata_lru_clock == 0` is the canonical empty metadata-LRU state.
A mutation fence must always invalidate the one-entry read cache, but it may
skip clearing the 512-slot metadata validity array when the clock already
proves a previous invalidation emptied it. The first invalidation after any
metadata insertion must still clear all valid slots and reset the clock.

This optimization does not weaken physical-reuse safety or make cached
metadata survive a write, discard, GC mutation or barrier. It only makes
back-to-back invalidation calls idempotent in cost as well as semantics.


### Nonblocking preparation-slot reservation

The asynchronous producer must reserve one bounded prepared-page slot before
claiming any BIO from `preparation_incoming`. Reservation is nonblocking:
`down_trylock()` runs before `queue_lock`, and failure returns without
removing any entry. This is required once producer claims may proceed from the
tail; blocking after claiming an earlier FIFO entry could otherwise strand the
ordered consumer behind later prepared entries that own every slot.

If the producer reserves a slot but finds no eligible entry (including a lone
idle head reserved for inline steal), it must release the slot before
returning. Once an entry is claimed, exactly one slot is either transferred to
its prepared page and later released by the ordered consumer, or released on
producer failure. Queue ownership, BIO completion and map publication remain
unchanged.


Do not expose scheduler-accounted per-callback CPU as a portable module
metric. The rejected task-cputime experiment undercounted short nonblocking
preparation callbacks on the qualification host. Exact hot-path attribution
uses explicit monotonic phase timers around LZ4, CRC, copies, planning, packing
and publication. Whole callback entry/exit timing may be reported only as wall
residency and must be labeled as such: ordered residency includes synchronous
lower-I/O sleep and either callback can include scheduler delay. Diagnostic
timing must never participate in ordering, timeout or scheduling policy.

A precomputed payload CRC may cross from preparation into serialized packing
only when it covers exactly the immutable compressed payload and length being
copied. It can remove the pack-side source rescan, but publication must still
verify the payload CRC over the final `bulk_scratch` bytes. Likewise,
`swapz_finish()` may validate immutable extent metadata once and decode
subsequent descriptors without repeating that global validation, but every
record still requires final payload CRC, generation, liveness and transaction
checks before any mapping is published.


### Codec input validation before payload inspection

Public codec append entry points must reject null/zero/oversized payload
descriptions before hashing or copying caller memory. In particular,
`swapz_append()` must validate `length <= SWAPZ_MAX_COMPRESSED` before
calling the payload CRC helper; an invalid length is not permission to read
that many bytes from the caller. The prehashed append path retains the same
authoritative mutation-time validation. Sanitizer qualification plus a
source-order contract pins this fail-before-read rule.


### Immutable lower-write run ownership

Batched lower-write packing must have an explicit ownership boundary before
asynchronous Device Mapper I/O is enabled. A `swapz_io_run` owns the exact
packed bytes, immutable staged transaction snapshots, per-extent offsets/takes,
raw/compressed identity and physical run geometry from the final
`swapz_batch_pause()` through definitive lower completion and authority
replay.

The portable engine separates `swapz_engine_prepare_batched_run()` from
`swapz_engine_complete_batched_run()`. Preparation may reserve and pack a
bounded prefix but must publish no mapping and submit no lower I/O.
Completion may replay/publish only after the caller supplies a definitive
completion result; failed, short or uncertain I/O quarantines every remaining
reservation. The existing synchronous writer is implemented on top of this same
split so the asynchronous path cannot grow a second publication state machine.

Upper BIO references, completions, PREFLUSH/FUA state and Linux callback
lifetime remain Device-Mapper-target ownership; the portable engine must not
depend on `struct bio`. A future async target may reuse a run buffer only after
its lower completion has been finalized and every paused transaction has been
published or aborted.


### K=1 ping-pong write pipeline

Idle asynchronous preparation must be self-gating. With no lower WRITE active,
a tail-credit workqueue wake requires at least four unclaimed preparation
descriptors. The initial accepted-wave starter observes the ordered head as
well, so it requires five descriptors total; after the head is stolen inline,
QD4 has only three tails and must remain entirely inline. The producer itself
must not consume an idle tail credit with fewer than two queued descriptors.
When a lower WRITE is actually active, any nonempty preparation queue remains
eligible for immediate head-first overlap. These gates add no timer, wait,
status token or mapping/publication owner.

The first asynchronous Device Mapper experiment is enabled only on the existing
`async_prepare` candidate. A complete multi-record non-FUA window may be
packed into the immutable `bulk_scratch`/`bulk_txs` run and submitted with
an asynchronous dm-io completion callback. The callback owns no mapping or
upper BIO completion: it records the definitive lower result, ends the lower
overlap interval, and wakes the single ordered worker. Only that worker calls
`swapz_engine_complete_batched_run()` and completes the original upper BIOs.

Once the full window has been copied into the sealed run, `batch_bytes` is
immediately reusable as the active collector. New WRITEs may therefore perform
zero/LZ4/payload-CRC preparation while the previous lower WRITE is in flight
without copying its packed run. A later close, read/barrier, zero/raw authority
mutation, GC retry or shutdown must finalize the prior run before staging or
mutating authority.

This first candidate keeps exactly one lower WRITE run outstanding. FUA and
hard control windows stay synchronous. If physical geometry yields only a
bounded prefix rather than the whole logical window, that prefix is completed
synchronously and the existing committed-prefix/GC retry path handles the
remainder. The experiment must never fragment a full packable window solely to
manufacture overlap.

Presuspend closes admission before waiting for an external lower completion,
then wakes/drains the ordered worker so every paused transaction is published
or aborted before teardown. The target drain invariant includes the asynchronous
run-active bit in addition to batch and authority state.


### Paused-run read independence

A paused immutable lower-WRITE group must not globally fence unrelated READs.
While the K=1 run is active, committed mappings remain authoritative until the
ordered worker replays and publishes the paused transactions. A READ may bypass
the active collector only when its logical page is absent from both the
collector and every transaction in the immutable run, authority replay is not
active, and no PREFLUSH/FUA/control fence applies. Malformed or mismatched run
metadata fails closed and forces ordered finalization. Same-page read-after-
write never bypasses the unpublished generation.

### Exact per-segment mapping counts

Production rotating-GC authority maintains one preallocated exact logical-map
count per physical segment. Every successful compressed/raw publication and
logical discard updates it in the same serialized authority phase as
`live_records`. Dead-segment selection and victim-role commit cross-check the
segment count against the sum of the segment's 256 physical live-record
refcounts; disagreement is corruption and fails closed. This sidecar replaces
production full-logical-map validation scans at dead-segment allocation and
post-evacuation role commit, while portable callers without the sidecar retain
the conservative full-map fallback. Victim discovery/evacuation may still scan
the logical map until a separately qualified reverse index exists.


### Timed benchmark telemetry ownership

Performance-policy counters used to explain measured mixed or write-only
throughput must be sampled at the same measure boundary as useful throughput and
independent lower-I/O deltas. Full-process status snapshots may remain private
session diagnostics, but prefill, warmup and post-measure activity must never be
reported as timed window, close-reason, deadline, burst-learning or preparation
evidence. Monotonic counters are differenced; policy state such as
`retained_burst_target` is an end-of-interval gauge and must not be subtracted.

### Explicit ordering-boundary state reset

Learned singleton fast-close state describes one uninterrupted admission stream.
FUA, PREFLUSH, DISCARD, shutdown and other explicit ordering boundaries clear
`singleton_deadline_streak` and `singleton_fast_close`, including empty
barrier flushes. Ordinary IDLE, DEADLINE and finite worker QUANTUM closes are
not ordering boundaries and must not erase the learned QD1 behavior they are
designed to preserve.

### Partial extent read residency

The serialized compressed-read cache may retain successfully fetched 4KiB
blocks from the current immutable extent in `read_scratch`. Residency is exact:
a block bit becomes valid only after its lower read succeeds, every authority-
changing write/GC/discard/barrier invalidates the mask, and generation,
descriptor and payload CRC validation still runs before returning a logical
page. This optimization may remove duplicate reads of sibling records but must
not turn cached bytes into mapping authority or weaken the existing mutation
fence.

### Synchronous grouped READ ownership

Grouped READ handling is bounded to `SWAPZ_PARALLEL_READ_SLOTS == 2`, but the
slots are scratch/telemetry containers executed synchronously by the ordered
worker. The read-only `parallel_reads` parameter, default true, controls
grouping eligibility only; it no longer enables independent lower-READ
concurrency or depends on backing queue depth.

The ordered worker remains the sole mapping, cache-publication, retained-window,
global-accounting and upper-BIO completion owner. The master engine owns the
512-entry metadata LRU and a 16-entry immutable extent-residency cache. Private
slot engine state is primed from master residency before a grouped operation and
absorbed only after successful validation/copy; it never mutates shared cache
state or authority independently.

Within one already-admitted contiguous independent-READ prefix, same-extent
siblings may be grouped. Two distinct extents may be consumed together only
when the exact ID63 coalescing predicate proves one zero-padding lower request.
Otherwise the helper returns without taking BIO ownership and the ordinary FIFO
`swapz_read()` path runs. No grace interval, fill timer, spin, sleep, helper
workqueue, completion wait or `flush_work()` is permitted.

The shared extent cache is fixed at 16 * 16KiB = 256KiB per target. Each slot
stores only blocks proven fetched for one immutable extent, with an exact block
mask. The 512-entry metadata LRU remains the block-zero fallback. Every
write/GC/discard/barrier mutation fence invalidates the master one-extent cache,
metadata LRU, shared extent cache and private-slot residency before authority
changes. Cache reuse never skips generation/descriptor/payload CRC validation.

A grouped read failure fails closed through the ordered owner. Teardown drains
the ordered worker before freeing read scratch; there is no read-helper work to
cancel or drain. End-to-end latency plus independently measured lower
bytes/requests remain the acceptance evidence.


### Incremental GC victim accounting

Victim-selection cost metadata is per physical 1MiB segment, never per logical
4KiB page. The serialized authority updates mapped-page count, live-byte cost,
conservative I/O cost and proven minimum-live-block cost in the same fail-closed
publication/discard transition. Score arithmetic is prevalidated before mapping
mutation. `swapz_gc_choose_victim()` may scan segments but must not rescan
`logical_pages`; relocation ownership discovery remains a separate measured
problem and must not gain a per-page reverse index without independent
evidence.
