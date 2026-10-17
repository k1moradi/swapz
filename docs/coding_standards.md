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

## Dead-code rule

Keep the working tree centered on code that ships or directly qualifies the current product. Historical reproduction belongs in immutable Git history. Delete alternate implementations, obsolete compatibility harnesses, unused models, stale workflow gates and historical test-only backends once no active product invariant depends on them.

Before deleting production code, identify all current callers and preserve necessary behavior in direct production-C tests. Never restore dead product code merely to satisfy an orphaned test; delete or rewrite the stale test when its subject no longer exists.

## Change discipline

Work directly on `main` unless the owner explicitly authorizes another branch. Check the current remote head before every write and use lease-protected fast-forward updates. Keep commits small enough to review. Do not force-push or overwrite concurrent work.

Every implementation task updates the relevant governing standard in the same commit. README/VISION change only when user-facing structure or acceptance criteria change.

## Host safety

Never reboot, `swapon`, `swapoff`, mount test storage, force-remove mappings or touch physical/unowned devices. Loaded development uses only positively owned RAM-backed `null_blk` with exact identity checks and ordinary teardown/quarantine.


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
retained READ service may carry across intermediate packed/fence commits within
the same accepted worker burst and is cleared at a true idle boundary.

A serviced useful pack may close on a refreshed dry worker tail. A sub-pack
1..3-record residue may do so only after successful retained READ service or a
forced zero/duplicate/raw/read interruption in the same accepted burst. This
exception must not make a prior PACK_READY write alone sufficient to cascade
write-only QD8/QD32 into singleton closes. Publication, FUA/PREFLUSH,
dependency, discard, shutdown, completion and fail-closed ownership are
unchanged.

### Opposite-end asynchronous preparation

The ordered worker owns FIFO execution and may atomically reserve an unclaimed
preparation entry from the head. The asynchronous producer is pure preparation:
it never publishes mappings, submits lower I/O, changes ordering, or completes
upper BIOs.

When synchronous lower WRITE I/O is active, the producer prepares from the
head because the ordered worker is blocked and will need that entry first.
Outside lower WRITE wait, tail preparation is explicitly credit-limited: each
ordered BIO that owns real execution time may grant at most one tail claim, and
an asynchronous WRITE grants that credit only after the ordered worker has
atomically reserved its own FIFO head. This prevents the producer from claiming
BIO 2, then 3, then 4 in succession and recreating a serial
`wait_for_completion` convoy despite nominal tail-first selection.

A lone truly idle head must not wake the unbound producer. `->map` wakes
parallel preparation only for active lower WRITE service or when
`ordered_worker_busy` and the one-shot `preparation_tail_credit` are both
published. An already queued multi-BIO burst therefore waits for the ordered
worker to reserve the first head before producer work can start.

For an asynchronous WRITE, the ordered worker sets `ordered_worker_busy`,
removes its own head preparation and publishes one tail credit in the same
`queue_lock` critical section. A producer consumes that credit atomically and
returns after one tail preparation unless synchronous lower WRITE begins in the
meantime. READ/barrier execution may likewise grant one tail credit so mixed
workloads retain bounded preparation overlap without allowing producer run-ahead.
Out-of-order preparation remains private to each BIO; FIFO publication,
completion and lower-I/O ownership are unchanged.

The producer may wait for a bounded preparation slot only after releasing
`queue_lock`. Tail claiming must never consume completion/publication
ownership: the FIFO worker can continue inline-stealing unclaimed heads and
releases prepared slots as it reaches completed tail entries. Separate LZ4
scratch/work memory remains mandatory for concurrent compression.

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
