# V2.2 live-GC source snapshot and staged-generation audit

## Confirmed data-path hazard: GC shared scratch alias

In the former implementation, `swapz_clean_segment` read a victim physical
block into `context->io_buffer`, then decoded every live logical record from
that buffer. But `swapz_store_page` can synchronously submit a full fill
buffer while relocating an earlier record. Submission calls
`swapz_compact_fill_buffer`, which snapshots an unrelated stream block by
`memcpy(context->io_buffer, ...)`. If the victim source block contains
multiple live compressed records, a later decode can therefore use changed
bytes even though all calls run in one serialized I/O worker.

One reachable sequence, especially with small configured batches:

1. GC reads a packed victim block with two or more live records into
   `context->io_buffer`.
2. It decodes and stages the first record. The staging/flush path can submit
   an already-full fill batch.
3. Before submitting, compaction overwrites `context->io_buffer` with a
   different buffered physical block.
4. GC resumes and tries decoding the victim's next live record from the
   overwritten `io_buffer`. Container validation can fail, or the source
   record is no longer the verified physical block.

This is a **source-level defect**, not evidence of live data corruption.
The real trigger requires a populated partial-live victim and batch-state
interleaving; no block-device experiment was performed.

## Minimal production fix

- Add one preallocated `gc_source_buffer` PAGE_SIZE (4 KiB) to
  `struct swapz_context`.
- GC reads its source physical block into this dedicated snapshot and passes
  the snapshot explicitly into `swapz_decode_loaded_mapping` for every live
  source record. A nested submit/compaction may still use `io_buffer`.
- The decoder now takes an explicit source pointer for raw and compressed
  paths; ordinary readback passes the existing `io_buffer`.
- Construct and allocation-failure unwind require the extra page; teardown
  frees it exactly once. There are **no per-operation allocations in GC**.
- Segment victim selection, generation arithmetic, mapping structure, lower
  physical layout, upper BIO ownership and strategy knobs are unchanged.

## State and invariant audit

| Transition | Source-level invariant | Assessment |
|---|---|---|
| write generation N -> N+1 | Old uncommitted generation flushed before increment | Existing `swapz_commit_previous_generation` ordering retained |
| write generation wrap | Skip generation 0 | Existing code; actual 2^32-cycle collision not kernel-verified |
| discard | Full logical extent checked before any generation/mapping mutation | Previously corrected rootless C guard |
| stage current generation | Staged ref carries generation and block/record coordinates | Existing source contract, not live-tested |
| finalize late obsolete record | Only generation-matching record may install a mapping | Production `swapz_stream_record_current` compiled in source-only C harness |
| lower-write error | Early-completed authoritative data retained in resident failed buffer | Source-level retention condition checked; not real fault injection |
| GC packed source -> nested submit | Victim source contents cannot be overwritten by compaction scratch | **Fixed**, exact production decoder and source-call bindings tested |
| GC victim CLEANING -> FREE | Lower batch flush and zero live-block count precede reuse | Source-order regression added |
| allocation failure | No GC snapshot allocation succeeds partially | Constructor requires buffer; shared cleanup unwinds |
| kernel I/O quiescence | Need real lower device and outstanding I/O accounting | **Not established**; offline-only |

## Rootless qualification procedure

Run:

```bash
python3 -B tests/runtime/swapz-gc-source-contract-test.py -v
python3 -B tests/runtime/swapz-kernel-range-contract-test.py -v
```

The new harness extracts **verbatim C functions** for decoding a compressed
mapping and checking a generation from `kernel/dm-swapz.c`, compiles them
into an ordinary user-mode executable, and tests them with synthetic fixed
container records. It injects a fake batch compactor overwrite of
`io_buffer` between two live decodes: a deliberately aliased GC source
fails, while the independent snapshot succeeds. This exercises actual
source decoder logic with a small **stub** LZ4 expansion function; it is
not a full LZ4, dm-io, GC state machine or running kernel.

Additional source contracts pin the GC read/decode buffer identity,
preallocation/free, current generation predicate, old-generation commit
ordering, failed-buffer retention, flush-before-victim-reclaim and
mutation rejection if the source reverts to shared scratch.

The mandatory joint GitHub Actions workflows run this suite under a
25-second timeout. Their workflow-contract tests refuse a skipped test.
Changes to `kernel/dm-swapz.c` already trigger both workflows.

## Limits and next review

The source inspection also identifies another subtle ordering question:
a foreground write increments its generation *before* a subsequent
`swapz_store_page` call can trigger GC. When GC relocates the previous
mapping for that same logical page, it copies the current generation.
A single serialized worker prevents simultaneous execution, but this
nested transitional state merits specific whole-kernel fault-injection
before treating GC publication as independently verified. No assertion
is made here that this behavior is a confirmed second defect.

A later authorized real-kernel qualification must exercise mixed
compressed/raw partially live victims, 4-KiB/1-MiB batches, failpoints
for compaction and submit, torn lower writes, watchdog completion,
generation reset, flush/FUA ordering, and exact readback across segment
reuse. Do not infer physical performance, kernel quiescence, or backing
release authority from source-only CI.

No real DM, loop, NBD, swap, module, pressure, physical device or
destructive operation was exercised. Strategy/batch winner remains
**UNDETERMINED**.
