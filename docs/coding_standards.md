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
