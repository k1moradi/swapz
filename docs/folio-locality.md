# Folio locality: reviewed measurement proposal

Status: design and source audit, 2026-10-29. No packing-policy or telemetry
implementation is promoted. ROADMAP ID113 tracks the evidence gate.

The useful hypothesis is narrower than object-aware compression: among records
already accepted and dispatchable, WRITE-time folio membership might predict
later backing READ locality beyond what logical adjacency already predicts.
It is an optional hint; logical-page/generation authority remains unchanged.

## Verified boundary

The audit host reports Ubuntu `7.0.0-42.42-generic`, upstream base `7.0.14`.
Installed headers and the pinned Linux 7.0 baseline were inspected; the full
Ubuntu patched MM source was not available locally. Moving upstream `master`
must not be treated as proof of this VM's implementation.

- In the [Linux 7.0 block swap path](https://github.com/torvalds/linux/blob/v7.0/mm/page_io.c),
  one folio supplies each BIO; it may be large. Filesystem swap has a separate
  batching path. Newer upstream `swap_io_ctx` code is a different baseline.
- In current swapz, `swapz_ctr()` limits upper I/O to 4KiB and `swapz_map()`
  validates that size. Split BIOs still contain page references, so this limit
  does not by itself erase all same-folio evidence. It does not expose an
  explicit original-BIO group token either.
- `swapz_map()` currently records compound-buffer shape for READs and WRITEs.
  It does not classify that observation as original anonymous swapout, or
  correlate it with a later swap-in. ID43's THP direct-I/O test is input-shape
  and byte-exact correctness evidence.
- [Swap-in allocation and readahead](https://github.com/torvalds/linux/blob/v7.0/mm/swap_state.c)
  operate on newly allocated destination memory when the old folio is gone.
  READ bvec identity cannot recover the original WRITE folio.
- [Folio lifetime rules](https://docs.kernel.org/core-api/mm-api.html#c.page_folio)
  apply to observations. Membership is not a persistent application, process
  or VMA identity. Splitting, remapping and allocator reuse must not turn a
  stale address into a new cohort match.

The stable observation is the logical swapz record, not its old RAM address:

```text
owned WRITE buffer -> observed cohort C -> logical page L, committed generation G
later READ of L,G   -> cohort lookup C   -> unrelated destination RAM buffer
```

An upper WRITE's `REQ_SWAP` is useful provenance to record. It is not sufficient
proof of representative reclaim. Linux 7.0 swap READ BIOs do not necessarily
carry that flag; requiring it on READ would miss observations. Swapz's own lower
BIO flags must not be mistaken for upper-source provenance.

## Measurement design before any policy

A concrete first prototype can restrict membership discovery to the existing
bounded staged window, while all of its upper BIOs still own their source
memory. Assign fresh numeric cohort IDs within that observation window. Copy
scalar order/index hints before releasing those BIOs. Do not keep a bare folio
pointer as a lasting identity, and do not retain source-folio references until
swap-in: doing so would obstruct the RAM reclamation being measured.

This measures observed same-folio subsets, not a complete large folio spanning
many windows. Cross-window continuity is unknown unless a later design proves
it using overlapping valid ownership. Window boundaries must be reported as
censoring rather than evidence that all members were observed or separated.

For sampled successful publications, retain a separate bounded volatile lookup
keyed by `(logical page, committed generation)`, with numeric cohort, captured
order/index and committed extent identity. A proposed initial hard cap is 256
fixed 64-byte entries (16KiB), allocated before admission; window-local state
stays bounded by the existing 64-record collector. This is a reviewable budget,
not an allocation or runtime knob currently present in the product.

Only the serialized worker updates the lookup. Failed/unpublished writes install
no tag. Overwrite, zero elision and DISCARD invalidate affected tags; GC may
invalidate relocated samples instead of trying to preserve unproved continuity.
Stale generations, evictions and untracked reads are explicitly unknown. Cohort
ID/epoch wrap clears correlation state before reuse. None of this metadata can
authorize a read, publish a mapping, affect allocation or survive target teardown.

The measurement must report:

- WRITE provenance and observed folio order, per-window cohort size and member
  index span; eligible, sampled, ambiguous and dropped observations separately.
- How often known members occupy different committed SWZ extents, separating
  RAW members and unavoidable geometry from actual equal-cost alternatives.
- Later logical READ co-access in bounded event-distance/time histograms,
  current generation, cache/lower-read outcome and sample coverage. READ RAM
  folio addresses are not used to match WRITE cohorts.
- Predictive value conditional on logical adjacency, page sizes, representation
  and arrival order, compared with adjacency-only and arrival-only controls.
- Incremental worker CPU/RAM, useful READ/WRITE, p95/p99, independent lower
  bytes/requests and accepted-work idle. A counter increase alone is not a win.

Target-visible READs include readahead and omit accesses satisfied above the
target. They establish backing-I/O co-access, not application demand or VMA
identity. Reused THP transfer buffers in synthetic direct I/O are negative
controls for semantic inference: one RAM folio may serve unrelated logical data.
No current owned-null_blk result establishes representative real-swap locality.
Actual swap collection remains a separately authorized disposable-VM project;
the host's swap configuration must not be changed for this proposal.

## Packing experiment only after positive evidence

The current greedy reorder feeds a DP planner over a fixed record order. Its
byte/read/extent optimum is conditional on that order. Reordering by logical
page or folio before invoking the DP can change the primary result. Equal slack
for one greedy pair is not proof of equal cost for the whole window.

Any locality candidate must preserve complete planned lower bytes, the existing
cold-read objective/cap and extent count, plus physical run splits and segment
tail waste. It cannot displace the allocator-cursor tie-break with an equally
scored layout that needs more actual lower I/O. RAW remains a whole-page extent
after the compressed prefix under current SWZ.

A particularly narrow first policy is to permute only compressed records with
exactly equal encoded lengths after the existing ordering decision. The length
sequence, metadata geometry and planner input costs then remain identical.
This is an experimental candidate, not proof that such ties are frequent or
that their added CPU cost is worthwhile. An arbitrary length-changing reorder
would need a complete baseline/candidate plan comparison with baseline fallback.

No path waits for another arrival or compression result, crosses a same-page
or PREFLUSH/FUA/DISCARD boundary, publishes before confirmed lower completion,
or adds an extent class. The serialized authority and upper completion owner
remain unchanged. Useful throughput, cold lower READs and tails must justify
the extra CPU. Avoiding an explicit wait does not guarantee unchanged dispatch
latency.

Larger upper BIO support is a separate architecture experiment: per-slice
descriptor ownership, partial error handling and one aggregate upper completion
would need to preserve ordering, draining and reclaim-safe memory bounds. The
4KiB limit must not be relaxed as a telemetry shortcut.

## Decision and next gate

Keep the current layout, K=1, producer/reservoir bounds and 4KiB upper-I/O
contract. Review a bounded measurement implementation and an appropriate data
collection environment before adding hot-path diagnostics. Promote locality
only after it adds predictive information beyond logical adjacency and improves
verified useful service without increasing lower WRITE cost. This audit has no
new benchmark result or performance claim; historical plots remain based on the
existing committed owner reports.
