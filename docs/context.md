# Linux memory, swap, zswap and Swapz: technical context

This is the durable **technical reference** for agents changing swapz behavior
around memory identity, Linux reclaim, swap I/O, folios, zswap and extent
locality. It explains what the kernel does and what information crosses the
Device Mapper boundary. It is **not** a project history, experiment log, backlog
or qualification claim. Decisions, implementation sequence and acceptance gates
belong in [ROADMAP.md](ROADMAP.md); normative constraints belong in
[coding_standards.md](coding_standards.md) and
[testing_standards.md](testing_standards.md).

**Immutable naming policy (read before every prompt):** The project is `swapz`; the kernel module is `dm-swapz.ko` (loaded as `dm_swapz`); the Device Mapper target is exactly `swapz`; and the module alias is `dm-swapz`. Never put implementation-generation numbers in product, module, target, source-path, report, workflow, helper, or schema names. `SWZ` is the current unversioned on-disk format identity; do not assign a format version until an incompatible format boundary is justified.

**Single official test command (read before every prompt):** Run `make test` at the repository root for every supported swapz test and benchmark. A complete run must report BLOCKED (nonzero) if safe noninteractive privileged qualification cannot run. Do not create, publish, recommend, or document alternative test commands; the sole owner-approved exception is the development decision loop `make fast_test`, which never qualifies a source, never writes or publishes `test_results.json` and never replaces `make test`. Private scripts and CI jobs are implementation details, not operator interfaces.

**Device safety:** official loaded qualification uses only newly created,
positively identified, RAM-backed `null_blk`. Nothing in this reference
authorizes active system swap, `swapon`, `swapoff`, mounting, reboot or
touching unrelated block devices; see [VISION.md](VISION.md).

The upstream functions cited here were inspected on Linux master at
`c339f4010dea8b0d754f84ace70cd1b089878ef8` and on tag `v7.0`; where the two
differ, the text names the version. The development host runs Ubuntu
`7.0.0-42-generic` (7.0.14 base), so the `v7.0` behavior is the nearest
upstream model for it; distribution backports can still differ. Kernel
internals are not a stable ABI; recheck the target kernel source before
implementing a coupled feature. The SWZ information describes the current
swapz implementation.

## 1. Storage abstractions: files, RAM objects, pages and extents

A block device exposes addressable sectors, **not** files, folders or
application objects. A filesystem layers inodes, names, directories and file
extents on top of blocks. A swap partition is not a conventional file tree; a
swapfile has a filesystem pathname but Linux resolves its backing extents for
swap I/O, so filenames are not carried on ordinary swap BIOs. A `tmpfs` file
has file-like names and inodes yet uses RAM and can itself be swap-backed.

An application's address space has virtual memory areas (VMAs) for regions
such as the heap, stack, executable mappings, private mappings and shared
mappings. An application or heap allocator knows `malloc` / `new` object
boundaries; the generic kernel page-reclaim and block layers do not generally
retain those boundaries. A 4KiB page may contain many small objects; one large
array/object may span many pages. One VMA may hold many allocations. The notion
of one *RAM object* per physical SWZ extent has no generally available
application-object identity at the Device Mapper layer.

A Linux **folio** is the MM's compound unit of page-cache or anonymous-memory
accounting and ownership. An order-0 folio contains one base page; an order-N
folio contains `2^N` base pages and is physically contiguous. With a 4KiB base
page, examples are 4KiB (order 0), 16KiB (order 2), 64KiB (order 4) and 2MiB
(order 9). Actual supported sizes depend on architecture and kernel features.
`page_folio(page)` identifies the owning folio while the referenced page is
valid. A large folio is a useful locality clue, **not** an application object.
Folios may be split, migrated, freed and reused; a folio pointer is not a
persistent object ID and must not outlive its safe ownership/reference.

```text
Application object(s) -> VMA(s) -> base pages within folio(s)
                                      |
                              swap entry/offset
                                      |
                                swap I/O BIO
                                      |
                           swapz logical 4KiB page
                                      |
                        SWZ record in physical extent
```

## 2. Which memory is reclaimed, and when?

Linux does not normally "swap a stalled process." Reclaim chooses eligible
**folios**, weighing recency, protection, refault history, memory type, swap
availability and policy. A sleeping process may accumulate cold anonymous
pages; an active process may also have large cold regions. The identity of the
task triggering reclaim need not be the owner of the selected folio.

Typical treatment:

| RAM content | Reclaim action |
| --- | --- |
| Clean executable/library/ordinary file-backed page | Drop and reload from original file on demand |
| Dirty ordinary file-backed page | Write back to original file, then reclaim when eligible |
| Anonymous heap, stack, privately modified mappings, `.bss` | Swap out if eligible and backing capacity/policy allow |
| Shmem/`tmpfs` | May be swap-backed despite having filesystem-like names |
| Unevictable, pinned or `mlock`ed memory | Not ordinarily reclaimable via swap |
| Some kernel-owned caches/allocations | Reclaim by their own mechanisms, not ordinary process swap |

The `kswapd` background thread is commonly woken as free memory approaches
zone low watermarks; allocations can enter **direct reclaim** when they cannot
otherwise obtain enough memory. Memory-cgroup pressure and proactive reclaim
can also trigger scans. Multi-Gen LRU may classify folios into access-recency
generations; swappiness and refault signals affect anonymous/file balancing.
None of the original LRU age, fault history, VMA or process context is an
ordinary Device Mapper BIO field.

## 3. Swap-out, swap-in and the actual block path

For a chosen anonymous/shmem folio, the swap subsystem reserves swap entry
space (swap type + offset), coordinates swap-cache and page-table state, and
arranges backing writeback when needed. Reclamation of the physical RAM occurs
only when it is safe to release that folio; submitting a BIO is not completion.
Exact locking, PTE replacement and folio lifetime vary across swap paths and
kernel releases.

The normal block-backed swap-out path is approximately:

```text
watermark / cgroup / proactive pressure
          -> mm/vmscan.c reclaim
          -> swap slot + swap cache / page-table swap entry
          -> mm/page_io.c:swap_writeout()
                 -> zero-filled folio? zeromap mark, no backing BIO
                 -> zswap_store() accepted? compressed RAM, no BIO yet
                 -> zswap writeback disabled for the memcg? stay in RAM
                 -> else master: __swap_writeout() -> swap_add_folio()
                         -> swap_write_submit() -> swap_bdev_submit_write()
                    v7.0:   __swap_writepage()
                         -> swap_writepage_bdev_sync() / _async()
          -> BIO (REQ_OP_WRITE | REQ_SWAP, sector, bvecs)
          -> block layer -> Device Mapper -> swapz_map()
          -> swapz preparation, packing, lower I/O and ordered publication
```

`mm/swapfile.c` maps swap entries into backing sectors
(`swap_folio_sector()`). Swapfile extent mapping is established at swap
activation (`setup_swap_extents()`) rather than by a pathname lookup for each
page. Upper BIO shape is version dependent (see section 4): in v7.0 each
block-backed swap WRITE carries exactly one folio, while master's
`swap_add_folio()` / `swap_write_submit()` can merge several sector-contiguous,
same-blkcg folios into one BIO.

Swap-in begins when a task faults on a page-table swap entry or when the
kernel performs swap readahead. The kernel checks swap cache, can obtain the
page directly from zswap with `zswap_load()`, or submits backing READ BIO(s)
through Device Mapper. Verified lower bytes are decompressed by swapz back
to an exact logical page; Linux then installs/uses the recovered folio as its
own fault and lifetime rules allow. Linux has swap-offset and VMA-based
readahead mechanisms, so neighboring swap offsets can be useful but are not
proof of correlated future access.

There are important exclusions: zero-filled folios may be recorded as swap
zeromap entries without lower I/O; zswap may retain pages entirely in RAM;
some swap backends are not block devices. Thus not every swap event reaches
swapz.

Source anchors:
- [Linux vmscan](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/vmscan.c)
- [Linux swap I/O](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c)
- [Linux swap slot/sector mapping](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/swapfile.c)
- [Linux swap cache and readahead](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/swap_state.c)

## 4. What Device Mapper hands to swapz

Swapz receives an upper `struct bio` in
[`swapz_map()`](../src/kernel/dm-target.c). The directly usable information
includes the operation, `bi_iter.bi_sector`, size, request flags including
`REQ_SWAP` where present, `REQ_PREFLUSH`/`REQ_FUA`, and the BIO's
`bio_vec` page references, offsets and lengths. A bvec page can be inspected
for compound/large-folio membership while the BIO/page lifetime is valid.

There is **no ordinary stable BIO contract** supplying process PID, owning
`mm_struct`, VMA, virtual address, application object/allocator identity,
filename/ELF section, page coldness, or zswap compressor/origin. `current`
may be a reclaimer, zswap worker or unrelated allocator and is not a reliable
owner. `REQ_SWAP` means swap I/O generally; it does not distinguish normal
swap-out, zswap rejection and zswap writeback. In Linux v7.0, the upper block-backed swap WRITE carries `REQ_SWAP`, but swap READ BIOs need not; do not filter READ correlations by that flag. Track upper WRITE provenance independently of swapz's own lower BIO flags.

Current swapz limits upper requests with
`dm_set_target_max_io_len(ti, SWAPZ_SECTORS)` and validates ordinary
READ/WRITE BIOs as exactly one 4KiB logical page. **Splitting changes the BIO
boundary but does not erase its backing `struct page` references**. Existing
`swapz_map()` inspection can detect compound/large-folio backing and bvec
offsets after that split. Larger upper BIO admission is therefore **not a
prerequisite** for observing same-folio membership among accepted WRITE pages.
The split *does* lose the original multi-folio BIO-group token (if one existed)
and does not preserve a safe identity for later swap-in comparison.

The upstream block-backed swap BIO shape is **kernel-version dependent**.
Linux `v7.0` `mm/page_io.c:swap_writepage_bdev_sync()` and
`swap_writepage_bdev_async()` construct one BIO from one folio (which itself
may be large). The later `master` implementation inspected at
`c339f4010dea8b0d754f84ace70cd1b089878ef8` uses
`swap_io_ctx`/`swap_add_folio()` to merge compatible folios into one BIO.
Do not attribute the newer multi-folio upstream batching behavior to v7.0,
or conclude from v7.0 that a large folio can never contain several base pages.
The reported development host in the related source audit was an Ubuntu
7.0.14-based kernel; revalidate the specific build before coding against
either upstream implementation.

- [v7.0 block-backed folio BIO construction](https://github.com/torvalds/linux/blob/v7.0/mm/page_io.c)
- [newer upstream multi-folio swap I/O](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c)

Swapz records independent 4KiB logical pages and maps them to its own 4/8/16KiB
physical SWZ extents. Compressed extents contain a header (magic, extent
blocks, record count, sequence, metadata CRC32C) and one or more record
descriptors: logical page, generation, payload offset/length and payload
CRC32C. A payload is LZ4, or, only on a target with the default-off
`delta64_rescue` enabled, a whole-page delta64 transform followed by LZ4,
flagged in the length field.
RAW fallback holds one whole 4KiB logical page in one physical block with
its mapping/integrity authority in RAM. A **SWZ record** is independently
decodable; a **physical extent** may hold multiple records; an **I/O run** may
concatenate several extents/RAW blocks. None represents a guaranteed language
object or whole folio.

Volatile swapz RAM state includes per-BIO admission descriptors, a bounded
64-slot preparation reservoir (stable RAW snapshots, optional compressed
payloads, atomic states and references), logical-page-to-extent mapping
authority/generations, physical segment and GC accounting, immutable lower-run
buffers/transaction snapshots, and read/metadata caches. That metadata is
swapz authority, not a directory of RAM objects.

Source anchors:
- [swapz DM admission and page validation](../src/kernel/dm-target.c)
- [SWZ compressed extent and record layout](../src/kernel/codec.h)
- [volatile mapping authority](../src/kernel/authority.h)
- [immutable write runs](../src/kernel/engine.h)
- [preparation state transitions](../src/kernel/preparation-slots.h)

## 5. zswap's two different routes to backing swap

zswap is a compressed **RAM cache** for swap pages, not the swap device's
on-disk compression format. It may intercept a swap-out and keep compressed
bytes in RAM, using a configured compressor and zsmalloc storage (v7.0 and the
inspected master use zsmalloc directly; the older zpool layer is gone). Its
success is not a promise that its compressed representation will remain
available forever.

### Initial rejection or inability to retain the page

`mm/page_io.c:swap_writeout()` checks zero-page handling and then attempts
`zswap_store(folio)`. A successful store has no immediate backing WRITE.
A failed store can fall through to normal swap-device writeback, subject to
policy such as whether zswap writeback is permitted. Rejection is **not**
synonymous with incompressibility: space pressure, limits, allocation failure,
compressor behavior and policy may all matter.

### Later eviction of a page previously compressed by zswap

When the zswap pool must release stored entries, its shrinker can call
`mm/zswap.c:zswap_writeback_entry()`. In both v7.0 and the inspected master:

1. Obtain the original swap entry and allocate a swap-cache folio for it
   (v7.0 `swap_cache_alloc_folio()`, master `__swap_cache_alloc_folio()`).
2. Verify that the zswap entry is still the entry authoritative for the slot,
   protecting against concurrent swap-in/invalidation/slot reuse.
3. Run `zswap_decompress(entry, folio)` to reconstruct the original page bytes.
4. Remove and release the compressed zswap entry.
5. Mark the reconstructed folio for prompt release after writeback: v7.0 sets
   `PG_reclaim` (`folio_set_reclaim()`); master sets drop-behind
   (`folio_set_dropbehind()`).
6. Submit an ordinary backing swap WRITE: v7.0 calls
   `__swap_writepage(folio, NULL)`; master calls `__swap_writeout(&ctx, folio)`
   and `swap_write_submit(&ctx)`.

```text
original 4KiB page
      -> zswap compression -> RAM-compressed entry
      -> later zswap eviction
      -> zswap DECOMPRESSION to a swap-cache folio
      -> normal backing BIO with reconstructed page bytes
      -> swapz may compress the page again (LZ4, optionally delta64+LZ4)
      -> physical SWZ or RAW storage
```

That **decompress-then-recompress** chain is real, but it is not equivalent to
passing zswap's existing compressed bytes to swapz. Current swapz receives a
reconstructed page, not zswap's compressed payload, payload length, compressor
ID or guaranteed semantic origin. zswap may compress with a different algorithm
from SWZ LZ4, so treating arbitrary zswap bytes as LZ4 would be incorrect.

In the inspected master, `folio_set_dropbehind(folio)` is used on this
writeback folio and `mm/page_io.c:swap_bdev_submit_write()` observes the
drop-behind bit to complete an async backing BIO in task context. v7.0 instead
sets `PG_reclaim`, and its `page_io.c` has no drop-behind check. Both bits
have other uses and neither is **a stable zswap-origin API**. It may help an investigation against a pinned
kernel, but cannot safely drive production bypass policy. Neither
`REQ_SWAP` nor the submitting PID provides origin. Some zswap-enabled
systems may never issue a writeback for particular entries (no eviction,
writeback disabled, or the entry is swapped in first).

Source anchors:
- [zswap store/eviction/writeback code](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/zswap.c)
- [backing swap BIO creation](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c)

## 6. Interfaces and representations that are technically possible

A robust distinction between normal swapping, initial zswap rejection and
**zswap-stored-then-evicted writeback** needs an explicit semantic signal at
the MM/swap layer. It must be transferred to the backing BIO and preserved by
block/Device Mapper cloning and splitting. `REQ_ZSWAP_WRITEBACK` is a useful
*illustrative name only*, not an existing Linux flag or an approved API.
An origin enumeration or another reviewed, stable, per-BIO mechanism could
serve; mixed-origin upstream BIOs need origin-safe splitting or per-folio
metadata. Do not derive origin from `current`, drop-behind or `PG_reclaim`.

With an authoritative writeback-origin hint, swapz has two conceptually
different choices:

- **RAW bypass:** accept the already reconstructed full 4KiB bytes, avoid
  another LZ4/delta64 pass and use existing RAW authority/CRC/generation paths.
  This saves CPU but generally consumes more lower-device bytes than a
  successfully recompressed SWZ record.
- **Direct compressed handoff:** change the upstream interface to transfer
  actual zswap compressed data and its compressor/encoding, length, integrity
  and lifetime ownership. This can avoid both the zswap decompress step and
  swapz recompression, but needs compatible read-side decoding, bounded memory
  management and a separately justified representation/format boundary.

A precise *initial-rejection reason* would be a different interface: only an
explicit, semantically reliable "compression was tried and ineffective" reason
could justify skipping swapz compression on that basis. "Zswap failed to
retain" alone is not enough.

## 7. Folio locality: source identity, READ correlation and packing

The **research hypothesis** is that certain WRITE-time page cohorts predict
subsequent backing-device READ co-access beyond simpler controls such as
adjacent swap offsets and arrival order. A cohort is a *volatile observation*
about pages seen during an already-accepted WRITE window, not a new object,
storage record, swap entry, ownership class or required page grouping.

### 7.1 WRITE and READ folios are not the same identity

A WRITE BIO may reference a page belonging to original RAM folio A. After its
data has been swapped and the source RAM reclaimed, a later swap-in may
allocate a **different destination folio B**. A page-table fault can also hit
swap cache or zswap without a backing READ at all. Comparing
`page_folio(write_page) == page_folio(read_page)`, retaining the original folio
pointer until a READ, or treating a physical folio pointer as a persistent
identifier is incorrect. Keeping a reference to the original folio for later
correlation could defeat the memory reclamation being studied.

The robust association is through **logical swapz page and successfully
committed generation** (and safe map identity/epoch when the authority changes):

```text
WRITE source folio A
    -> accepted 4KiB logical page L
    -> committed generation G
    -> observation cohort C

Later backing READ of logical page L
    -> resolve CURRENT authoritative generation G
    -> optional volatile lookup (L,G) -> cohort C
    -> READ destination folio B is irrelevant to cohort identity
```

Linux's swap-cache allocation path explicitly allocates a folio for a swap
entry when a suitable folio is not already cached. In v7.0 this path is
`mm/swap_state.c:swap_cache_alloc_folio()` (master:
`__swap_cache_alloc_folio()`). The WRITE-time folio pointer is
therefore **not** a key for READ correlation.

### 7.2 Capture a cohort without retaining application RAM

During a live upper WRITE BIO, swapz may observe
`page_folio(bvec.bv_page)`, the current folio's order/size and the base-page
index inside the folio. Those observations are valid only during owned
access to the page; folios can split, be migrated, freed or reused. For
segmented BIOs, bvec offsets and 4KiB logical-page boundaries need explicit
handling. Identical folio pointers within a *single safely observed window*
can support a provisional same-folio cohort, but pointers must not become a
persistent key, and their reuse must not create false cross-window matches.

Window-local observation covers **only** the subset of an original folio whose pages were in that owned window. If one folio crosses windows, missing members are **censored observations**, not proof of a different cohort. Compare folio pointers only while source memory ownership is valid and copy scalar index/order hints before releasing the BIO.

One bounded correlation design is:

1. While a WRITE window is owned and complete source bvecs remain valid,
   assign a bounded window-local cohort token to pages observed in the same
   folio, together with their offsets/indexes and logical page IDs. Also
   record independent controls for logical adjacency and WRITE arrival order.
2. Do **not** publish cohort metadata for a speculative, failed, partial or
   uncommitted mapping. Only upon confirmed lower completion and serialized
   publication associate the authoritative `(logical_page, generation)`
   with that cohort token. Only the serialized mapping-publication worker may update the voluntary correlation cache.
3. Keep association in a fixed-size, generation-checked volatile lookup cache,
   not in SWZ bytes or a correctness-critical mapping. Overwrite,
   DISCARD, slot reuse, generation change and stale publication invalidate or
   supersede associations. For GC relocation, either preserve an association
   only after verified matching authority/generation or invalidate it. Explicit zero-page elision must likewise invalidate any older tag. Cohort ID or epoch wrap must clear/retire previous tags before numeric reuse.
4. A cache eviction or missing entry means **unknown**, not a negative
   locality observation. Never use a generation-mismatched or unverified
   entry. Bound the lookup and cleanup cost, and leave the storage authority
   usable without this cache. Where analyzing committed physical co-location, retain a scalar committed extent identity with the cohort observation. Tear this cache down with the target; it is not another authority.
5. On a later backing READ, validate the current authoritative logical page
   and generation before attributing it to cohort C. The destination READ
   folio and the thread requesting it do not establish original ownership.

This can be done without enlarging the supported 4KiB upper BIO size. Original
upstream BIO membership, if needed, is an **additional** hint that requires a
deliberate propagation token; splitting alone does not erase source bvecs. The existing window is bounded to 64 records. A separate fixed-size, preallocated correlation cache can bound observation cost independently of the number of logical swap pages; the proposed implementation budget belongs in ROADMAP.

### 7.3 Kernel-version dependency and what READ observations mean

The block-backed swap I/O path differs across upstream releases:

- [Linux v7.0 `mm/page_io.c`](https://github.com/torvalds/linux/blob/v7.0/mm/page_io.c)
  submits one folio per block-backed BIO; a folio may span multiple 4KiB pages.
- [Newer Linux swap I/O](https://github.com/torvalds/linux/blob/c339f4010dea8b0d754f84ace70cd1b089878ef8/mm/page_io.c)
  can merge compatible folios within a `swap_io_ctx`.

These are different sources of potential batching/locality evidence. Verify
the actual running kernel's source and DM split behavior rather than assuming
both models coexist in one version.

A READ seen by swapz is a **backing READ**, not necessarily a user page fault:
Linux supports clustered swap readahead and VMA-based readahead. It may read
several pages speculatively, and many real accesses may be served from swap
cache or zswap without reaching swapz. Target-only READ sequences thus
measure *lower-I/O co-access* and cannot prove exact application-level
memory-access locality. A study of real fault/access locality additionally
needs properly scoped upstream fault/readahead observations.

- [Linux v7.0 swap-cache allocation and readahead](https://github.com/torvalds/linux/blob/v7.0/mm/swap_state.c)

### 7.4 Separate genuine folio evidence from synthetic buffer tests

Swapz's existing `tests/tools/device-roundtrip.c:series_thp()` maps a
2MiB `MADV_HUGEPAGE` transfer buffer, then performs logical I/O through it.
That proves compound-backed buffer admission and byte-exact behavior; it does
**not** prove that real swapped anonymous application pages shared their
original folio, nor that they will swap in together. Reusing one THP transfer buffer for unrelated logical I/O is a **negative control**: a shared source buffer does not imply common application semantics or future read locality. Likewise, seeing pages
arrive in one reclaim burst is not proof of correlated later faults.

Useful controls for any correlation result include equal logical adjacency,
arrival order, page compression size and content, read sequence timing, swap
readahead mode, upper cache hits and whether a target-visible READ was a
verified demand read or speculative readahead where such a distinction is
observable. Treat high cache-miss/eviction rates as unknown coverage rather
than manufacturing a stronger effect from a biased surviving sample. Report eligible/sampled/dropped/ambiguous cohorts, observed folio order and within-window index spans, censored window boundaries, committed extent co-location, RAW versus compressed records, bounded READ event-distance/time histograms, cache coverage, and independent lower bytes/requests. Separate target-visible backing co-access from user demand.

### 7.5 Equal-cost placement requires a whole-run geometry proof

The current [swapz greedy ordering](../src/kernel/dm-target.c) pairs
size-complementary compressed records before the
[bounded extent dynamic-programming planner](../src/kernel/engine.c)
optimizes the **given sequence**. Pre-sorting by folio identity is unsafe as
a blanket policy: a different length sequence can change record packing,
cold-read cost, extent classes, run boundaries, segment alignment holes,
tail waste or physically dispatched requests.

The strongest **first candidate** is to consider swapping only **compressed
records with identical encoded lengths**, *after* existing greedy ordering
has already fixed the sequence. This preserves the encoded-length sequence
seen by the planner. It is still a hypothesis, not an automatic geometry
proof: representation/encoding and other attributes, same-page ordering,
extent placement, segment crossings, lower-run splits, read cost, physical
padding and allocator waste must remain equivalent.

Any policy must verify the **whole window and resulting physical run(s)**,
not just a reported sum of bytes/cold-read cost/extent count. Compare actual
pre-/post-geometry including physical request count, alignment holes and
segment-tail waste. Never increase planner cost, dispatch latency or lower
traffic merely to co-locate a folio cohort. Never wait for a future page. A tie-break can still delay the lower submission through extra CPU work even without an explicit wait; measure that cost. Do not displace the live allocator-cursor tie-break with an equally scored geometry that produces more run splits or segment-tail waste. RAW remains whole-page blocks after the compressed prefix.

### 7.6 Scope of a positive result

A positive result would mean that WRITE-time folio cohorts predict **later
backing READ co-access** after controlling for logical adjacency and arrival
order. It would not establish one application object per physical extent,
accurate user fault proximity, or free compression/CPU cost. If the signal is
weak or masked by readahead/cache hits, retain passive telemetry and the
current byte-minimal, work-conserving placement.

The staged measurement and tie-break experiment is tracked as **ID113** in
[ROADMAP.md](ROADMAP.md); this context file intentionally contains no
experiment chronology or task history.
