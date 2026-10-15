# V2.2 live-GC compressed payload isolation

## Second nested-GC alias identified

The earlier GC source snapshot fix protected each *original victim block* from
`swapz_compact_fill_buffer`'s `io_buffer` scratch.

A separate alias remained in `swapz_clean_segment`:

1. GC decompresses the victim's logical page into `input_buffer`, then
   `swapz_store_page` compresses it into `context->compressed_buffer`.
2. `swapz_add_compressed_record` may call `swapz_ensure_physical_block`
   or flush a full compressed pack *before* the pending compressed bytes
   are copied to `pack_buffer`.
3. The ensure/flush path can submit and compact a fill buffer.
   `swapz_compact_fill_buffer` uses `compressed_buffer` as its
   record-copy scratch. It overwrites the *not-yet-staged GC payload*.
4. `swapz_add_compressed_record` resumes and copies corrupted or
   unrelated compressed bytes into the GC relocation pack, potentially
   publishing an unreadable or incorrect replacement for a live page.

This is a source-derived conditional data-integrity hazard. It does not
establish that any real physical workload experienced this corruption.

## Small production correction

- Add `gc_compressed_buffer`, a separately allocated 4-KiB page in
  `struct swapz_context`. GC passes this as `swapz_store_page`'s
  compression output, while batch compaction continues using the older
  `compressed_buffer`.
- Keep `gc_source_buffer` (original physical source snapshot),
  `input_buffer` (decoded victim), `gc_compressed_buffer` (new compressed
  payload), `compressed_buffer` (batch-compactor scratch), and
  `write_compressed_buffer` (foreground compression) distinct.
- Require the extra page in constructor allocation failure checks and free
  it through the shared destructor/failure-unwind path. No allocation
  occurs inside `swapz_clean_segment` or `swapz_store_page`.
- Preserve source layout, mapping size, generation scheme, batch size,
  victim selection, on-disk format, and lifecycle release policy.

## Rootless regression contract

`tests/runtime/swapz-gc-compressed-contract-test.py` extracts the
**actual production C function** `swapz_add_compressed_record` into
an ordinary temporary unprivileged C executable.

Stubbed `swapz_ensure_physical_block` and `swapz_flush_pack` overwrite
the compactor scratch at precisely the boundary before the production
function copies its input. The harness checks:

- First pack staging from a protected source survives the overwrite.
- First pack staging from an aliased source reproduces the old bad bytes.
- Pack rollover with a protected source preserves the bytes.
- Pack rollover with an aliased source reproduces the old bad bytes.
- A mocked ensure I/O error never publishes a new pending record.

Source-anchored adversarial tests verify GC binds to the new buffer,
the allocation/failure/unwind path owns the exact extra page, mutation
of that source or allocation fails tests, and the foreground
compression buffer remains independent.

The mandatory rootless combined and teardown workflows execute the
new suite with a 25-second timeout and a new workflow-contract
negative test. They already run the earlier 17-test GC source
snapshot guard and 30-test kernel range guard.

The C harness models only the staging function and synthetic
compression bytes; it is **not** execution of real LZ4, full GC,
dm-io, upper BIO completion or the kernel itself. Whole-kernel
fault injection and concurrent device tests remain unqualified.
No live module, DM, loop, NBD, swap or physical device was operated.

Next audit: generation advancement before nested GC under foreground
allocation failure; stale generation wrap after 2^32 changes; FUA and
failed lower write completion; actual kernel GC with partially live
containers. V2.2 strategy and batch winner remain UNDETERMINED.

## Exact source CI qualification

Three workflows passed on the identical executable source
`f5379bc048b868be88210023229cdd133910c46c`:
[combined](https://github.com/k1moradi/swapz/actions/runs/38033528668),
[teardown](https://github.com/k1moradi/swapz/actions/runs/38033528694),
[standalone NBD](https://github.com/k1moradi/swapz/actions/runs/38033528707).
Both joint workflows ran 15/15 new GC compressed C tests, 17/17 previous
GC source tests, 30/30 kernel range C tests and 20/20 workflow-contract
tests. Combined also passed 25/25 standalone-process NBD repetitions.
None of these replace privileged, real-device or actual kernel GC
qualification.
