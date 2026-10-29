# Linux memory, swap and Swapz context

This document is required background for changes that depend on RAM identity,
swap locality, folios, zswap or the information visible at the Device Mapper
boundary. It describes semantic boundaries, not a new SWZ format or a current
qualification result.

The Linux-source observations below were rechecked against upstream
`torvalds/linux` master commit `c339f4010dea8b0d754f84ace70cd1b089878ef8`.
Kernel internals evolve; recheck the named functions before implementing an
upstream-coupled optimization.

## Memory objects and folios

Linux does not normally know arbitrary language-level object boundaries such as
a C++ `new` allocation. One 4KiB page may contain several application objects,
and one object may span many pages. A VMA is a process virtual-address region,
not an allocation boundary.

A Linux folio is the kernel MM ownership/accounting object for one or more
physically contiguous base pages. An order-0 folio is one base page; a large
folio contains multiple base pages. Same-folio membership is therefore a useful
MM-level locality hint, but it is not proof that pages belong to one application
object or will fault back together.

swapz must continue to treat each 4KiB logical page as independently
reconstructible authority. Folio identity, virtual locality and swap adjacency
may influence optional packing choices only after correctness and byte-minimal
planning constraints are satisfied.

## What is normally reclaimed and swapped

Reclaim is page/folio based, not process based. A sleeping process tends to
accumulate cold memory, but Linux does not ordinarily decide to "swap a stalled
program" as one unit.

At a high level:

- clean executable and other clean file-backed folios can normally be dropped
  and read again from their backing file;
- dirty file-backed folios are written back to their file;
- cold anonymous memory, private modified data, stack/heap pages and swappable
  shmem/tmpfs need a swap-backed copy before their RAM can be reclaimed;
- pinned or unevictable memory is not ordinary swap material.

Global reclaim may be driven by watermarks and `kswapd`; allocations can also
enter direct reclaim. Memory-cgroup and proactive reclaim are additional entry
points. Modern reclaim may use multi-generation LRU information, but by the time
a block BIO reaches swapz the original reclaim recency metadata is not carried
as a Device Mapper contract.

## Swap-out path to swapz

The relevant current Linux path is approximately:

1. reclaim selects an eligible anonymous/shmem folio;
2. the swap subsystem allocates swap entry/entries and associates the folio with
   swap cache;
3. `mm/page_io.c:swap_writeout()` handles the backing decision;
4. zero-filled folios can be represented by swap zeromap metadata with no
   backing-device write;
5. `zswap_store()` may intercept and retain the page in compressed RAM;
6. otherwise `__swap_writeout()` queues the folio for backing swap I/O;
7. block-backed swap builds a BIO with `REQ_OP_WRITE | REQ_SWAP`, derives the
   sector from the swap entry, and submits it through the normal block layer;
8. Device Mapper delivers the resulting BIO to `swapz_map()`.

For a swap file, filesystem block extents are resolved for swap operation; the
ordinary file/folder namespace is not part of the per-page BIO that reaches
swapz.

Current swapz deliberately requests 4KiB upper I/O with
`dm_set_target_max_io_len(ti, SWAPZ_SECTORS)` and accepts ordinary READ/WRITE
BIOs only when they cover exactly one swapz logical page. Linux can batch
compatible swap folios above Device Mapper, so this split can discard upstream
grouping information before `swapz_map()` sees individual pages.

## Information visible to swapz today

From the upper `struct bio` and its bvecs, swapz can observe information such
as:

- operation, sector, size, PREFLUSH/FUA and `REQ_SWAP`;
- the RAM pages/folios backing the BIO while the BIO remains owned;
- bvec offsets/lengths and whether a page belongs to a compound/large folio;
- the logical swapz page derived from the sector.

The Device Mapper interface does not provide a stable semantic field for:

- PID/process name or owning `mm_struct`;
- VMA or application virtual address;
- malloc/C++ object identity;
- executable section or original filename;
- reclaim generation/coldness;
- "this WRITE came from zswap writeback".

Do not reconstruct correctness policy from `current` or process identity: the
task performing reclaim/writeback may not own the memory being reclaimed.

## Locality-aware packing rule

Locality is an optimization hint, never a reason to wait for future work.

If multiple already-accepted layouts have the same lower-byte cost, the same
bounded cold-read cost and the same extent-count objective, a future planner may
prefer, in this order:

1. pages from the same large folio and nearby indexes within that folio;
2. adjacent logical swap pages;
3. existing stable ordering.

The dispatcher must not delay an otherwise dispatchable run to obtain a better
locality group, and locality must not increase physical blocks solely to keep a
group together. First collect passive evidence that same-folio or adjacent
swap-page placement predicts actual swap-in locality.

## zswap interaction

There are two different paths that must not be conflated.

### Initial zswap rejection

On normal swapout, `swap_writeout()` first tries `zswap_store(folio)`. When
zswap accepts the page, no backing-device BIO is issued at that time. When zswap
rejects it, Linux can continue through ordinary backing swap I/O. A rejection
may have several causes; a lower target must not assume it means
"incompressible" unless an explicit upstream semantic says so.

### Later zswap writeback

A page that was successfully compressed into zswap can later be evicted from
the zswap pool. Current `mm/zswap.c:zswap_writeback_entry()`:

1. allocates a swap-cache folio for the original swap entry;
2. **decompresses the zswap entry back into that folio**;
3. removes/frees the compressed zswap entry;
4. marks the folio for drop-behind handling;
5. resumes normal swap writeback with `__swap_writeout()` and
   `swap_write_submit()`.

Therefore current swapz does **not** receive zswap's compressed payload. It
receives the reconstructed page bytes through an ordinary swap WRITE BIO.

Current upstream happens to mark this writeback folio with the drop-behind bit,
and the swap I/O path observes that bit for completion handling. This is an
implementation detail shared with other MM/file paths, not a stable zswap-origin
ABI. It may be useful for controlled telemetry while developing against one
known kernel, but production representation policy must not depend on this
incidental flag.

`REQ_SWAP` is also insufficient: it means swap I/O generally and does not
distinguish normal swapout, zswap rejection or later zswap writeback.

## Required zswap collaboration design

The first collaboration candidate should require an **explicit end-to-end
zswap-writeback origin hint** from the swap/zswap layer to the backing BIO and
through Device Mapper. The exact upstream field/flag name is a kernel-interface
decision; do not overload unrelated BIO flags or infer origin from task/PID.

For an explicitly tagged zswap writeback, the first swapz candidate should skip
ordinary LZ4/delta64 preparation and feed the already reconstructed 4KiB page
through the existing stable RAW snapshot and authority path. This avoids a
second compression pass without adding a SWZ type, a completion owner or a new
authority state. It is a performance/storage tradeoff: lower CPU and dispatch
latency may cost lower-device bytes, so qualification must measure both.

A richer future interface could pass zswap compressed metadata or payload
directly, but that is a separate format/codec experiment. zswap may use a
compressor or representation different from SWZ. Direct compressed reuse would
need explicit codec identity, bounded length, integrity coverage, lifetime
ownership and read-side decode compatibility; it must never reinterpret
arbitrary zswap bytes as ordinary SWZ LZ4.

## Questions to answer with telemetry before policy expansion

Future actual-swap qualification should determine:

- fraction of backing WRITEs that are initial zswap rejects versus later zswap
  writebacks;
- CPU/time spent in zswap decompression immediately before a tagged backing
  write;
- CPU/time swapz would otherwise spend recompressing those reconstructed pages;
- zswap-origin RAW lower bytes/requests versus recompressed SWZ bytes/requests;
- whether same-folio and adjacent logical pages actually fault back close enough
  together to justify a packing tie-break;
- whether the existing 4KiB DM split is destroying useful upper swap-BIO group
  information.

Actual `swapon`/`swapoff` remains outside the current safe qualification
scope. These observations become loaded acceptance work only after that scope is
separately authorized.
