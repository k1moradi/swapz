# Linux memory, swap, zswap and Swapz: technical context

This is the durable **technical reference** for agents changing swapz behavior
around memory identity, Linux reclaim, swap I/O, folios, zswap and extent
locality. It explains what the kernel does and what information crosses the
Device Mapper boundary. It is **not** a project history, experiment log, backlog
or qualification claim. Decisions, implementation sequence and acceptance gates
belong in [ROADMAP.md](ROADMAP.md); normative constraints belong in
[coding_standards.md](coding_standards.md) and
[testing_standards.md](testing_standards.md).

The upstream functions cited here were inspected on Linux master at
`c339f4010dea8b0d754f84ace70cd1b089878ef8`. Kernel internals are not a
stable ABI; recheck the target kernel source before implementing a coupled
feature. The SWZ information describes the current swapz implementation.

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
                 -> zero-page metadata? no backing BIO
                 -> zswap_store() accepted? compressed RAM, no BIO yet
                 -> else __swap_writeout() / swap_write_submit()
          -> swap_bdev_submit_write()
          -> BIO (REQ_OP_WRITE | REQ_SWAP, sector, bvecs)
          -> block layer -> Device Mapper -> swapz_map()
          -> swapz preparation, packing, lower I/O and ordered publication
```

`mm/swapfile.c` maps swap entries into backing sectors. Swapfile extent
mapping is established for swap activation rather than doing a pathname
lookup for each page. An ordinary block-backed swap WRITE may contain several
compatible folios in one upstream BIO; `mm/page_io.c:swap_add_folio()` /
`swap_write_submit()` merge compatible entries.

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
swap-out, zswap rejection and zswap writeback.

Current swapz limits upper requests with
`dm_set_target_max_io_len(ti, SWAPZ_SECTORS)` and validates ordinary
READ/WRITE BIOs as exactly one 4KiB logical page. Upstream Linux can merge
multiple swap folios into a larger BIO; splitting at the DM boundary may lose
the original grouping. A bvec's compound-page flag may remain observable,
but does not recover a persistent original swap grouping, especially if folios
were split or newly allocated for writeback.

Swapz records independent 4KiB logical pages and maps them to its own 4/8/16KiB
physical SWZ extents. Compressed extents contain a header and one or more
record descriptors: logical page, generation, payload offset/length and CRC.
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
bytes in RAM, using a configured compressor and zpool. Its success is not a
promise that its compressed representation will remain available forever.

### Initial rejection or inability to retain the page

`mm/page_io.c:swap_writeout()` checks zero-page handling and then attempts
`zswap_store(folio)`. A successful store has no immediate backing WRITE.
A failed store can fall through to normal swap-device writeback, subject to
policy such as whether zswap writeback is permitted. Rejection is **not**
synonymous with incompressibility: space pressure, limits, allocation failure,
compressor behavior and policy may all matter.

### Later eviction of a page previously compressed by zswap

When the zswap pool must release stored entries, its shrinker can call
`mm/zswap.c:zswap_writeback_entry()`. For the inspected upstream implementation:

1. Obtain the original swap entry and allocate a swap-cache folio for it.
2. Verify that the zswap entry is still the entry authoritative for the slot,
   protecting against concurrent swap-in/invalidation/slot reuse.
3. Run `zswap_decompress(entry, folio)` to reconstruct the original page bytes.
4. Remove and release the compressed zswap entry.
5. Mark the reconstructed folio for drop-behind handling.
6. Call `__swap_writeout(&ctx, folio)` and `swap_write_submit(&ctx)`, which
   produce an ordinary backing swap WRITE.

```text
original 4KiB page
      -> zswap compression -> RAM-compressed entry
      -> later zswap eviction
      -> zswap DECOMPRESSION to a swap-cache folio
      -> normal backing BIO with reconstructed page bytes
      -> swapz may LZ4-COMPRESS the page again
      -> physical SWZ or RAW storage
```

That **decompress-then-recompress** chain is real, but it is not equivalent to
passing zswap's existing compressed bytes to swapz. Current swapz receives a
reconstructed page, not zswap's compressed payload, payload length, compressor
ID or guaranteed semantic origin. zswap may compress with a different algorithm
from SWZ LZ4, so treating arbitrary zswap bytes as LZ4 would be incorrect.

In the inspected kernel, `folio_set_dropbehind(folio)` is used on this
writeback folio; `mm/page_io.c` observes the drop-behind bit when deciding
completion handling for an async backing BIO. The flag has other uses and is
**not a stable zswap-origin API**. It may help an investigation against a pinned
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
metadata. Do not derive origin from `current` or `folio_set_dropbehind`.

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

## 7. Physical locality versus logical locality

Promising but non-authoritative hints for pages likely to be read together
include (in rough order): same **current large folio** and nearby base-page
indexes; adjacent **logical swap offsets** (also used by swap readahead);
compatible folios delivered in one upstream swap BIO; and arrival in the
same reclaim burst. Same-folio identity and original BIO grouping can be
weakened/lost through splitting, allocation and writeback. Swap-out proximity
does **not** guarantee swap-in proximity.

Locality can only be used on already-accepted independent writes. An
immediately dispatchable lower run must not wait for more pages, and grouping
must not violate same-page generations, upper ordering, fences, CRC, GC
authority or completion ownership. Between equally economical layouts,
locality can be a final tie-break; it cannot justify extra physical blocks
or a larger cold-read cost by itself. Actual swap-in clustering, cold-read
amplification and lower request counts determine whether the hint is useful.

The operational proposal and evidence gates for zswap origin and locality are
in [ROADMAP.md](ROADMAP.md); this document intentionally contains no historical
trial chronology, benchmark winners or task queue.
