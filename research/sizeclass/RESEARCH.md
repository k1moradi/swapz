# swapz: block-aligned size classes, first-principles prototype (2026-10-11)

**Scope:** Rootless, source-informed geometry experiment. This is **not** a kernel patch, segment-GC implementation, replay of Codex's real 10,240-page payload captures, or live block-device measurement. Source reference: PR #31, `3a89ebbeba21c814dcf724e227b31d38445a3f9a`, `kernel/dm-swapz.c` (`swapz_compact_fill_buffer`, `swapz_repack_can_fit`, `swapz_add_compressed_record`).

## The useful part of zsmalloc

Borrow **size classes**, **page-chain allocation**, **fullness-group accounting**, and **compaction-victim selection**. Do not use zsmalloc's RAM pointers/handles or memory allocator as a disk allocator. On disk, write only whole 4 KiB-aligned extents (8/16/64 KiB are divisible by 4 KiB), and keep bounded *volatile* mapping metadata for the live target. A record can cross a 4 KiB sub-block boundary within an aligned larger extent; this incurs an additional block read for the affected records. It also requires explicit multi-block read/error bounds and mapping publication after the *whole* extent is safe.

A compressed record near 2,072 B consumes one descriptor (8 B); every container needs one header (8 B).

| Unit | Pages stored when full | Gross physical reduction | Straddling read fraction | Mean 4 KiB blocks per record read | Idealized GC victim-live break-even |
|---|---:|---:|---:|---:|---:|
| 4 KiB | 1 | 1.000x | 0% | 1.000 | 0% |
| 8 KiB | 3 | 1.500x | 33.3% | 1.333 | 33.3% |
| 16 KiB | 7 | 1.750x | 42.9% | 1.429 | 42.9% |
| 64 KiB | 31 | 1.9375x | 48.4% | 1.484 | 48.4% |

Example 8 KiB byte count: `8 header + 3*8 descriptors + 3*2072 payload = 6248 <=8192`. In this layout the middle of three payloads straddles the 4 KiB boundary. The real benefits under bounded dispatch and GC may be much smaller; partial slabs are charged at their full size.

### Dispatch/underfill changes the ranking

The full-slab table deliberately assumes sufficient queued records to fill each slab. This can be misleading on reclaim-limited, latency-sensitive swap. A separate **illustrative 16-record forced-flush window** (not the driver's actual physical-block-based batching rule) yields: 8 KiB slab `16 pages -> 6x8 KiB -> 1.333x`; 16 KiB slab `16 pages -> 3x16 KiB -> 1.333x`; 64 KiB slab `16 pages -> 1x64 KiB -> 1.000x`. The apparently best 64 KiB geometry loses all benefit if its 31-slot class is frequently flushed half-full. On highly compressible ~1,048 B records a 64 KiB underfilled slab may be worse than existing 4 KiB three-packs. **An implementation therefore needs class-specific admission, a bounded flush policy, and honest accounting of partial slabs.**

**Important hard constraint:** If each ~2,072 B record must be readable from exactly one physical 4 KiB block *and* the device only performs full aligned 4 KiB writes, two such records cannot share a physical block. A '2.5 KiB slot in a 4 KiB block, 1 block per read, 1.6x saved writes' architecture is therefore not realizable without hidden spanning, separate sub-block writes, caching, deduplication, or compression improvements. zsmalloc's multi-page zspages work *because* objects may span page boundaries.

## Correcting the existing-packer comparison

The real `swapz_compact_fill_buffer()` loops over resident records *in order* and only retains one current `repack_buffer`. After emitting that container it never reopens it for later smaller records. In the 16-record fixture `8*[2200] + 8*[1600]`, a source-shaped sequential packer uses 12 containers, whereas a size-aware 16-record best-fit arrangement needs 8. An *alternating* `2200,1600` trace uses 8 containers under either policy. This does not validate safe BIO reordering; it disproves claims that the current code performs retrospective best-fit or that its incremental opportunity is always zero.

## GC sensitivity, NOT a GC prediction

At uniform idealized victim-live fraction `f`, the toy copy-cost relationship `WAF = 1/(1-f)` gives `net logical/physical ratio = gross_ratio*(1-f)`. `f` denotes the fraction **still live inside selected cleaning victims**, not total device occupancy; these are not interchangeable. This formula ignores partial-bin waste, hot/cold segregation, allocation reserve, queueing, segment selection, underfill, read I/O, and re-relocation. E.g. 8 KiB/3 loses its gross 1.5x benefit above f=1/3; 16 KiB/7 above 3/7. A reviewer claim of exactly 5x WAF at 80% *device occupancy* is not justified by occupancy alone.

## Rootless prototype usage

```
python3 -B -m unittest -v test_swapz_sizeclass_experiment.py
python3 -B swapz_sizeclass_experiment.py > swapz_sizeclass_results.json
# Optional: pass exact per-page length TSV from Codex's retained fio audit
python3 -B swapz_sizeclass_experiment.py --lengths /path/to/raw-lengths-50.tsv
```

`--lengths` accepts the `page_index<TAB>payload_bytes<TAB>kind` audit format from PR #31. The provided fixtures are **illustrative**, not measured traces. The prototype does not reproduce container generation metadata, GC, data integrity, or host I/O latencies. Its W=16 flush is a comparative thought experiment, not a model of the kernel's actual stream-buffer capacity or timeout logic. Best-fit is an **offline comparator**, not an allowed immediate kernel reorder. For mixed distributions the simplistic homogeneous slab uses a single class from the largest compressed length; it is not a dynamic allocator.

## Next staged design questions (for external reviewers to implement and test)

1. Design a **block-native size-class allocator** with no unaligned lower I/O: choose among existing 4 KiB compressed and raw containers, 8 KiB/3, 16 KiB/7, and optionally 64 KiB/31 under a documented dispatch/buffer cap. State exactly how class choice and tail-flush work on mixed-size data and how many SRAM/RAM bytes are pinned. Preserve the existing single-block path for highly compressible pages.
2. Build a **deterministic overwrite-and-GC simulator** tracking slot generations, class occupancy, physical segments, allocated and reclaimed blocks, partial slabs, chosen victim-live fraction, relocation writes and candidate torn-write failure. Compare identical write-slot trace and capacity reserve under all designs. Never multiply an assumed global-occupancy WAF into gross ratios and call it a measurement.
3. Show a **multi-block format sketch** with base LBA, extent-block count, per-record logical slot/offset/length, check bounds, checksum/integrity plan, and generation-safe publication. Prove that losing one 4 KiB sub-write cannot publish an unreadable record or silently corrupt unrelated acknowledged records. Explicitly decide whether crash/reboot swap recovery is in scope; do not assume it.
4. Propose **size-class admission** that optimizes physical writes and read amplification at comparable cold-read load, handles partial fills and bounded waits, preserves preflush/FUA/BIO completion semantics, and never strands pages under reclaim.
5. Provide executable rootless tests with exact source, seed, input trace SHA-256, command lines and validation logs, plus adversarial fixtures (partial slab, early flush, duplicate slot, stale generation, mixed hot/cold, 90% space pressure, failed extent write). No host privileged operations or kernel changes.

**Current decision:** investigate adaptive 4 KiB/8 KiB/16 KiB class allocation and source-faithful bounded reorder as **rootless competing prototypes**; do not choose a kernel format until a dynamic GC and latency model supports it. This is strictly a research result.