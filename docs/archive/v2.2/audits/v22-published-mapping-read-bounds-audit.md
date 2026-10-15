# V2.2 published mapping: lower-read extent admission

## Scope

Independent main-developer audit based on
`f17dd4145834492a008d23e8ed976a346fdb9ee7`.
This is separate from the native Linux kernel build and regression
verification assigned to Codex.

## Source-level defect and impact

Prior to this change, `swapz_read_mapping()` checked only whether the
published mapping had its valid bit, then directly passed
`mapping.physical_block` to `swapz_read_block()`, which computes
the lower-sector address from that block number. The target allocates
only `context->physical_blocks` usable backing blocks. A corrupted
but valid in-RAM mapping with `physical_block >= physical_blocks`
therefore reached lower dm-io without being rejected first.

The backing device may be larger than the segment-aligned usable
target area, so the requested sector could fall outside swapz's own
physical extent while still being within the opened backing device.
Whether any deployed workload can corrupt a published physical block
was **not** demonstrated; this is a malformed-in-memory metadata
admission defect, not an observed cross-device incident.

## Narrow code change

`swapz_read_mapping()` now checks
`mapping.physical_block >= context->physical_blocks` after its
existing unmapped-zero-fill fast path and **before** calling
`swapz_read_block()`. An out-of-range address returns `-EUCLEAN`
without submitting lower I/O and without modifying the caller's
destination buffer.

The code keeps the ordinary compact mapping structure and existing
LZ4 decode, GC compaction statistics, failure propagation, zero-fill
semantics, and read allocation behavior. No new heap allocations,
device operations, format changes, or concurrency paths are added.
This is defense-in-depth against invalid published metadata, not a
new way to recover corrupt data.

## Regression and mutation evidence

`tests/runtime/swapz-published-read-bounds-contract-test.py`
extracts actual production C definitions of
`swapz_mapping_valid()`, `swapz_decode_loaded_mapping()`, and
`swapz_read_mapping()`, compiles them under
`-std=c11 -O2 -Wall -Wextra -Werror`, and substitutes a bounded
in-memory `swapz_read_block()` plus a deterministic LZ4 stub.
The suite checks:

- Unmapped zero-fill without any lower I/O.
- Valid raw reads at the first and last usable block, plus valid
  compressed read/decode and compaction accounting.
- Both exact end-of-extent and `UINT32_MAX` physical addresses,
  including an invalid compressed mapping, rejected before lower read.
- Existing lower-I/O error propagation.
- A deliberately broken binary that removes the pre-I/O guard and
  demonstrably reaches the mock lower-read function with out-of-range
  addresses.

The source workflow and both joint rootless workflows must execute
the bounded test, and the workflow regression test ensures neither
joint gate can silently omit it.

## Qualification constraints

This harness never loads the kernel module or creates a dm target.
A mock lower read is not real dm-io, a real backing device, or a swap
runtime. The independent Codex native build is on a different earlier
revision and does not directly qualify this kernel change.

Before promoting this candidate, record the exact pull-request and
post-merge kernel, combined, teardown, and NBD rootless workflow
conclusions. Real-device/fault/teardown qualification still requires
separate explicit authorization. No benchmark was run and the V2.2
strategy/batch winner remains **UNDETERMINED**.

## Exact merged-source evidence

The reviewed change merged as
[`03e6e6459fed5317918d1314f3ccf0bdab47564a`](https://github.com/k1moradi/swapz/commit/03e6e6459fed5317918d1314f3ccf0bdab47564a).

All four **post-merge** rootless runs on this identical executable
commit passed:

- [Kernel source](https://github.com/k1moradi/swapz/actions/runs/38046890497)
- [Combined source qualification](https://github.com/k1moradi/swapz/actions/runs/38046890454)
- [Teardown safety](https://github.com/k1moradi/swapz/actions/runs/38046890382)
- [NBD source safety](https://github.com/k1moradi/swapz/actions/runs/38046890405)

The original PR head `617af668d022ad0c9fb89fd639ddca6f44c63ef4`
also passed those four PR qualification workflows before merge.
Later documentation-only commits on `main` do not modify the
qualified executable source. Independent native kernel compilation
has not yet been repeated on this revision.
